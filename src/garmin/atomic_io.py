#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
atomic_io.py

Leaf-Node. The one atomic-write helper of the project (Block 8 of the v1.7.8
line): write to a temporary file, flush it, move it over the target with
os.replace. Standard library only, no logging, no project import — same
category as garmin_utils.py. A caller that wants a log line catches the
exception itself.

It lives in garmin/ and not in the src/-root on purpose: the collector runs as
a script (python src/garmin/garmin_collector.py), and a script starts with its
own folder as the only project folder on sys.path, so everything it imports at
module level must be findable from garmin/ (garmin_config, garmin_utils, ...).
A module of the src/-root (log_utils.py, date_utils.py, version.py) is not. The
folders that reach the writers all have garmin/ on their path too: the app, the
scheduler, the standalone build, the MCP server, the tests (gla_testenv).

Before this module, every writer carried its own copy of the pattern and the
copies differed (fsync: never / swallowed / not guarded; a locked file:
tried again / not tried again; the .tmp: removed / left behind). The
parameters below name those differences, so a module that moves here keeps its
own behaviour on purpose instead of by accident. Defaults are the most
conservative values (fsync "off", one attempt); each caller passes what it
needs.

fsync modes:
  "off"    flush only (no fsync)
  "soft"   fsync; an OSError is ignored (not every file system supports it) EXCEPT one that says the data is not
           safe on disk: EIO, ENOSPC, EDQUOT and EBADF are raised. On Windows every failure of os.fsync arrives as
           EBADF (measured: a failed FlushFileBuffers leaves errno 9 and no winerror), so there EBADF is the
           only sign of a disk error; for the file we have just written through a valid handle it cannot mean
           anything else. EINVAL, ENOTSUP and the like (fsync not supported here) stay ignored.
  "strict" fsync, every OSError is raised

Two flows:
  write_atomic()         one file: write_tmp + replace_with_retry + cleanup
  write_atomic_stream()  one file written in parts by a callback (big files)
  write_tmp(), replace_with_retry(), remove_quietly()
                         the steps alone, for a caller that swaps two files
                         one after the other (garmin_writer.write_day)

Text payloads (str) are written like Path.write_text does: newline=None turns
"\\n" into os.linesep (CRLF on Windows). A caller that must keep its bytes
passes newline="\\n" or writes bytes. Bytes payloads are written as they are.

Every function raises on a failure; write_atomic()/write_atomic_stream()
remove their own .tmp first and leave a stored target untouched.
"""

import errno
import os
import time
from pathlib import Path

REPLACE_ATTEMPTS = 5          # the value of diary_writer and garmin_bulk_writer
REPLACE_PAUSE_S = 0.1         # the pause after the first failed attempt (grows with each one)

FSYNC_OFF = "off"
FSYNC_SOFT = "soft"
FSYNC_STRICT = "strict"
_FSYNC_MODES = (FSYNC_OFF, FSYNC_SOFT, FSYNC_STRICT)


def _check_options(fsync, attempts):
    """Refuses a bad option before anything is written (ValueError)."""
    if fsync not in _FSYNC_MODES:
        raise ValueError(f"fsync must be one of {_FSYNC_MODES}, not {fsync!r}")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise ValueError(f"attempts must be an integer of at least 1, not {attempts!r}")


def default_tmp(dst):
    """The usual temporary name: the target's name plus '.tmp', in the target's folder."""
    dst = Path(dst)
    return dst.with_name(dst.name + ".tmp")


def _tmp_for(dst, tmp):
    """The temporary path of a write to dst (refuses the target itself, which a cleanup would delete)."""
    dst = Path(dst)
    tmp = default_tmp(dst) if tmp is None else Path(tmp)
    if tmp == dst:
        raise ValueError("the temporary file must not be the target")
    return dst, tmp


def remove_quietly(path):
    """Removes a file; a file that is not there or cannot be removed is not an error."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


# The errors of fsync that say "the data is not safe on disk" (the "soft" mode raises them, see the module docstring).
# A deny list on purpose: an unknown error on a file system that merely lacks fsync stays harmless.
_DISK_ERRNO = frozenset(code for code in (getattr(errno, name, None) for name in ("EIO", "ENOSPC", "EDQUOT", "EBADF"))
                        if code is not None)


def _is_disk_error(exc):
    """True for an OSError of fsync that says the disk is full or failing (see the "soft" fsync mode)."""
    return exc.errno in _DISK_ERRNO


def sync_file(handle, fsync):
    """Flushes an open file and, by the mode, fsyncs it."""
    handle.flush()
    if fsync == FSYNC_OFF:
        return
    try:
        os.fsync(handle.fileno())
    except OSError as exc:
        if fsync == FSYNC_STRICT or _is_disk_error(exc):
            raise
        # "soft": not supported on every file system


def replace_with_retry(tmp, dst, *, attempts=1, pause_s=REPLACE_PAUSE_S):
    """
    os.replace(tmp, dst). A PermissionError (a file locked for a moment, for example by a
    virus scanner or a viewer on Windows) is tried again up to `attempts` times in all, after a
    pause of pause_s, 2 * pause_s, ...; the last one is raised. Any other error is raised at once.
    """
    _check_options(FSYNC_OFF, attempts)
    for attempt in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause_s * (attempt + 1))


def write_tmp(tmp, payload, *, fsync=FSYNC_OFF, encoding="utf-8", newline=None, mkdir=True):
    """
    Writes payload (str or bytes) to the temporary file `tmp` and flushes it (fsync by the mode).
    Creates the folder when mkdir is set. Raises on any failure, after removing this tmp.
    The swap itself is a separate step (replace_with_retry).
    """
    _check_options(fsync, 1)
    if not isinstance(payload, (str, bytes, bytearray)):
        raise TypeError(f"payload must be str or bytes, not {type(payload).__name__}")
    tmp = Path(tmp)
    try:
        if mkdir:
            tmp.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            handle = open(tmp, "w", encoding=encoding, newline=newline)
        else:
            handle = open(tmp, "wb")
        with handle:
            handle.write(payload)
            sync_file(handle, fsync)
    except Exception:
        remove_quietly(tmp)
        raise


def write_atomic(dst, payload, *, fsync=FSYNC_OFF, attempts=1, pause_s=REPLACE_PAUSE_S,
                 encoding="utf-8", newline=None, tmp=None, mkdir=True):
    """
    Writes payload (str or bytes) to dst through a temporary file: written, flushed (fsync by the
    mode) and moved with os.replace (tried again while the file is locked, see replace_with_retry).
    `tmp` names the temporary file (default: dst + '.tmp'); `mkdir` creates the folder of dst.
    Raises on any failure; the .tmp is removed then and a stored dst is untouched.
    """
    _check_options(fsync, attempts)
    dst, tmp = _tmp_for(dst, tmp)
    try:
        write_tmp(tmp, payload, fsync=fsync, encoding=encoding, newline=newline, mkdir=mkdir)
        replace_with_retry(tmp, dst, attempts=attempts, pause_s=pause_s)
    except Exception:
        remove_quietly(tmp)
        raise


def write_atomic_stream(dst, write_fn, *, fsync=FSYNC_OFF, attempts=1, pause_s=REPLACE_PAUSE_S,
                        tmp=None, mkdir=True):
    """
    Like write_atomic for a file that is written in parts: write_fn(handle) gets the temporary
    file, opened for writing bytes, and writes into it; the rest is the same (flush, fsync by the
    mode, swap with retry, cleanup and re-raise on any failure, also one of write_fn).
    """
    _check_options(fsync, attempts)
    dst, tmp = _tmp_for(dst, tmp)
    try:
        if mkdir:
            tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as handle:
            write_fn(handle)
            sync_file(handle, fsync)
        replace_with_retry(tmp, dst, attempts=attempts, pause_s=pause_s)
    except Exception:
        remove_quietly(tmp)
        raise
