#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_atomic_io.py — atomic_io.py (the one atomic-write helper, Block 8 of the v1.7.8 line)

Covers: write_atomic (bytes and text, line endings, encoding, folder, replacing a file, own and default tmp name,
bad options refused before anything is written), failures (no .tmp left, a stored file untouched, also for an
encoding error and a failing fsync), the retry on a locked file (pause sequence, last error raised, other errors
not retried, a real lock on Windows), the three fsync modes, write_atomic_stream, the single steps (write_tmp,
replace_with_retry, remove_quietly) and guards (standard library only, no logging, the documented defaults, the import from a script in garmin/ the way the collector subprocess does it).

Run from the project folder:
    python tests/test_atomic_io.py

Everything is built here in a temporary folder — no archive of the maintainer is needed or touched.
"""

import ast
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede project imports
from support import check, section, skip, summary

_SRC = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC / "garmin"))      # atomic_io lives in garmin/ (see its docstring)

import atomic_io as aio  # noqa: E402

_ROOT = _TMPDIR / "atomic_io_tests"
shutil.rmtree(_ROOT, ignore_errors=True)
_ROOT.mkdir(parents=True)
_COUNTER = [0]
_REAL_REPLACE = os.replace
_REAL_FSYNC = os.fsync
LINESEP = os.linesep.encode()


def fresh():
    _COUNTER[0] += 1
    folder = _ROOT / f"t{_COUNTER[0]}"
    folder.mkdir()
    return folder


def tmps(folder):
    return sorted(p.name for p in Path(folder).rglob("*") if p.name.endswith(".tmp"))


def names(folder):
    return sorted(p.name for p in Path(folder).rglob("*"))


class ReplaceSpy:
    """os.replace that records its calls and fails the first `fail_times` ones (or all of them)."""

    def __init__(self, fail_times=0, exc=PermissionError, always=False):
        self.calls, self.fail_times, self.exc, self.always = [], fail_times, exc, always

    def __call__(self, src, dst):
        self.calls.append((Path(src), Path(dst)))
        if self.always or len(self.calls) <= self.fail_times:
            raise self.exc("locked")
        return _REAL_REPLACE(src, dst)


class FsyncSpy:
    """os.fsync that records its calls and can fail with an OSError."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, fd):
        self.calls.append(fd)
        if self.fail:
            raise OSError("fsync not supported")
        return _REAL_FSYNC(fd)


def run_with(replace=None, fsync=None, fn=None):
    """Runs fn() with os.replace / os.fsync / time.sleep replaced; returns (result or exception, sleeps)."""
    sleeps = []
    with patch.object(aio.time, "sleep", sleeps.append):
        with patch.object(aio.os, "replace", replace or _REAL_REPLACE):
            with patch.object(aio.os, "fsync", fsync or _REAL_FSYNC):
                try:
                    return fn(), sleeps
                except Exception as exc:  # noqa: BLE001 — the test wants the exception itself
                    return exc, sleeps


# ══════════════════════════════════════════════════════════════════════════════
section("1. write_atomic — content, line endings, folder, names")

d = fresh()
res = aio.write_atomic(d / "a.bin", b"\x00\x01bytes\r\n\xff")
check("bytes are written as they are, nothing is returned", res is None and (d / "a.bin").read_bytes() == b"\x00\x01bytes\r\n\xff")
check("no .tmp is left behind", tmps(d) == [] and names(d) == ["a.bin"])

aio.write_atomic(d / "ba.bin", bytearray(b"ba"))
check("a bytearray is written as bytes", (d / "ba.bin").read_bytes() == b"ba")

aio.write_atomic(d / "t.txt", "a\nb\n")
check("text with the default newline is written like Path.write_text (os.linesep)", (d / "t.txt").read_bytes() == b"a" + LINESEP + b"b" + LINESEP)
aio.write_atomic(d / "lf.txt", "a\nb\n", newline="\n")
check("text with newline='\\n' keeps the bytes (LF on every system)", (d / "lf.txt").read_bytes() == b"a\nb\n")
(d / "ref.txt").write_text("a\nb\n", encoding="utf-8")
check("the default text bytes equal Path.write_text's", (d / "ref.txt").read_bytes() == (d / "t.txt").read_bytes())
aio.write_atomic(d / "u.txt", "Grüße €", newline="\n")
check("text is written as UTF-8 by default", (d / "u.txt").read_bytes() == "Grüße €".encode("utf-8"))
aio.write_atomic(d / "l1.txt", "é", encoding="latin-1", newline="\n")
check("the encoding can be named", (d / "l1.txt").read_bytes() == b"\xe9")
aio.write_atomic(d / "empty.bin", b"")
check("an empty payload makes an empty file", (d / "empty.bin").exists() and (d / "empty.bin").stat().st_size == 0)

aio.write_atomic(d / "a.bin", b"second")
check("an existing file is replaced", (d / "a.bin").read_bytes() == b"second" and tmps(d) == [])

deep = d / "x" / "y" / "z" / "f.json"
aio.write_atomic(deep, b"{}")
check("the folder is created (parents included)", deep.read_bytes() == b"{}" and tmps(d) == [])
d2 = fresh()
res2, _ = run_with(fn=lambda: aio.write_atomic(d2 / "no" / "f.bin", b"x", mkdir=False))
check("mkdir=False with a missing folder raises an OSError and creates nothing", isinstance(res2, OSError) and names(d2) == [])
aio.write_atomic(str(d2 / "str.bin"), b"s")
check("a str path works", (d2 / "str.bin").read_bytes() == b"s")

spy = ReplaceSpy()
d3 = fresh()
run_with(replace=spy, fn=lambda: aio.write_atomic(d3 / "name.json", b"1"))
check("the default tmp is the target's name plus '.tmp' in the same folder", spy.calls == [(d3 / "name.json.tmp", d3 / "name.json")])
spy = ReplaceSpy()
run_with(replace=spy, fn=lambda: aio.write_atomic(d3 / "name.json", b"2", tmp=d3 / "garmin_raw_2024.tmp"))
check("a named tmp is used", spy.calls == [(d3 / "garmin_raw_2024.tmp", d3 / "name.json")] and tmps(d3) == [])
check("default_tmp() gives the same name", aio.default_tmp(d3 / "name.json") == d3 / "name.json.tmp"
      and aio.default_tmp(str(d3 / "x.zip")) == d3 / "x.zip.tmp")

# ══════════════════════════════════════════════════════════════════════════════
section("2. Bad options and payloads are refused before anything is written")

d = fresh()
(d / "keep.bin").write_bytes(b"keep")
bad_cases = [
    ("a payload that is not str/bytes", lambda: aio.write_atomic(d / "n.bin", None), TypeError),
    ("an int payload", lambda: aio.write_atomic(d / "n.bin", 5), TypeError),
    ("a list payload", lambda: aio.write_atomic(d / "n.bin", [b"x"]), TypeError),
    ("an unknown fsync mode", lambda: aio.write_atomic(d / "n.bin", b"x", fsync="always"), ValueError),
    ("fsync=True instead of a mode", lambda: aio.write_atomic(d / "n.bin", b"x", fsync=True), ValueError),
    ("attempts=0", lambda: aio.write_atomic(d / "n.bin", b"x", attempts=0), ValueError),
    ("attempts=-1", lambda: aio.write_atomic(d / "n.bin", b"x", attempts=-1), ValueError),
    ("attempts=True", lambda: aio.write_atomic(d / "n.bin", b"x", attempts=True), ValueError),
    ("attempts=2.0", lambda: aio.write_atomic(d / "n.bin", b"x", attempts=2.0), ValueError),
    ("the target as its own tmp", lambda: aio.write_atomic(d / "keep.bin", b"x", tmp=d / "keep.bin"), ValueError),
    ("a bad option on the stream flow", lambda: aio.write_atomic_stream(d / "n.bin", lambda h: None, fsync="x"), ValueError),
    ("the target as its own tmp on the stream flow", lambda: aio.write_atomic_stream(d / "keep.bin", lambda h: None, tmp=d / "keep.bin"), ValueError),
    ("a bad payload on write_tmp", lambda: aio.write_tmp(d / "n.tmp", None), TypeError),
    ("a bad fsync mode on write_tmp", lambda: aio.write_tmp(d / "n.tmp", b"x", fsync="x"), ValueError),
    ("attempts=0 on replace_with_retry", lambda: aio.replace_with_retry(d / "a", d / "b", attempts=0), ValueError),
]
for label, fn, exc_type in bad_cases:
    res, _ = run_with(fn=fn)
    check(f"{label}: {exc_type.__name__}", type(res) is exc_type)
check("nothing was written or removed by them", names(d) == ["keep.bin"] and (d / "keep.bin").read_bytes() == b"keep")

# ══════════════════════════════════════════════════════════════════════════════
section("3. Failures — no .tmp left, a stored file untouched")

d = fresh()
target = d / "f.json"
target.write_bytes(b"OLD")

res, _ = run_with(replace=ReplaceSpy(always=True, exc=OSError), fn=lambda: aio.write_atomic(target, b"NEW"))
check("a failing swap raises the error", isinstance(res, OSError) and not isinstance(res, PermissionError))
check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])

res, _ = run_with(fn=lambda: aio.write_atomic(target, "é€", encoding="ascii"))
check("an encoding error is raised", isinstance(res, UnicodeEncodeError))
check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])

res, _ = run_with(fsync=FsyncSpy(fail=True), fn=lambda: aio.write_atomic(target, b"NEW", fsync="strict"))
check("a failing strict fsync raises", isinstance(res, OSError))
check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])

d_new = fresh()
res, _ = run_with(replace=ReplaceSpy(always=True, exc=OSError), fn=lambda: aio.write_atomic(d_new / "n.json", b"x"))
check("a new target whose write fails leaves no file and no .tmp", isinstance(res, OSError) and names(d_new) == [])

# a failure of the tmp itself (a folder in its place) leaves the folder alone
d_blk = fresh()
(d_blk / "blocked.tmp").mkdir()
res, _ = run_with(fn=lambda: aio.write_atomic(d_blk / "blocked", b"x", tmp=d_blk / "blocked.tmp"))
check("an unusable tmp raises an OSError", isinstance(res, OSError))
check("... and the target was not created", not (d_blk / "blocked").exists())

# ══════════════════════════════════════════════════════════════════════════════
section("4. A locked file — retry and pause")

d = fresh()
target = d / "f.bin"
target.write_bytes(b"OLD")

spy = ReplaceSpy(fail_times=2)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW", attempts=5, pause_s=0.5))
check("two locked attempts, then it works", res is None and len(spy.calls) == 3 and target.read_bytes() == b"NEW")
check("the pauses grow with each failed attempt (pause, 2 x pause)", sleeps == [0.5, 1.0])
check("no .tmp is left", tmps(d) == [])

target.write_bytes(b"OLD")
spy = ReplaceSpy(fail_times=4)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW", attempts=5, pause_s=0.25))
check("the last attempt may be the one that works", res is None and len(spy.calls) == 5 and target.read_bytes() == b"NEW")
check("four pauses: 1, 2, 3, 4 x pause", sleeps == [0.25, 0.5, 0.75, 1.0])

target.write_bytes(b"OLD")
spy = ReplaceSpy(always=True)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW", attempts=3, pause_s=0.5))
check("a lock that stays: the PermissionError is raised after all attempts", isinstance(res, PermissionError) and len(spy.calls) == 3)
check("... with a pause between them only (2 pauses)", sleeps == [0.5, 1.0])
check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])

spy = ReplaceSpy(always=True)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW"))
check("the default is one attempt: no retry, no pause", isinstance(res, PermissionError) and len(spy.calls) == 1 and sleeps == [])
check("... still without a .tmp", tmps(d) == [])

spy = ReplaceSpy(always=True, exc=OSError)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW", attempts=5))
check("another OSError is not tried again", isinstance(res, OSError) and len(spy.calls) == 1 and sleeps == [])

spy = ReplaceSpy(always=True, exc=FileNotFoundError)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic(target, b"NEW", attempts=5))
check("a FileNotFoundError is not tried again either", isinstance(res, FileNotFoundError) and len(spy.calls) == 1 and sleeps == [])

# replace_with_retry alone
d = fresh()
(d / "a.tmp").write_bytes(b"A")
(d / "a").write_bytes(b"OLD")
spy = ReplaceSpy(fail_times=1)
res, sleeps = run_with(replace=spy, fn=lambda: aio.replace_with_retry(d / "a.tmp", d / "a", attempts=2, pause_s=0.3))
check("replace_with_retry alone: one pause, then moved", res is None and sleeps == [0.3] and (d / "a").read_bytes() == b"A" and not (d / "a.tmp").exists())
check("its pause defaults to REPLACE_PAUSE_S", run_with(replace=ReplaceSpy(fail_times=1),
      fn=lambda: (aio.write_tmp(d / "b.tmp", b"B"), aio.replace_with_retry(d / "b.tmp", d / "b", attempts=2)))[1] == [aio.REPLACE_PAUSE_S])
res, _ = run_with(fn=lambda: aio.replace_with_retry(d / "missing.tmp", d / "x"))
check("replace_with_retry alone: a missing source raises and keeps the target away", isinstance(res, FileNotFoundError) and not (d / "x").exists())

# a real lock (Windows: a file that is open cannot be replaced)
if sys.platform == "win32":
    d = fresh()
    target = d / "locked.bin"
    target.write_bytes(b"OLD")
    holder = open(target, "rb")
    try:
        try:
            aio.write_atomic(target, b"NEW")
            real_one = None
        except PermissionError as exc:
            real_one = exc
        check("a real lock: one attempt raises a PermissionError", isinstance(real_one, PermissionError))
        check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])
        timer = threading.Timer(0.15, holder.close)
        timer.start()
        aio.write_atomic(target, b"NEW", attempts=8, pause_s=0.1)
        timer.join()
        check("a real lock that goes away is waited for", target.read_bytes() == b"NEW" and tmps(d) == [])
    finally:
        holder.close()
else:
    skip("a real lock on the file", "the lock is a Windows behaviour")

# ══════════════════════════════════════════════════════════════════════════════
section("5. fsync modes")

d = fresh()
spy = FsyncSpy()
run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "off.bin", b"x"))
check("default: no fsync", spy.calls == [] and (d / "off.bin").read_bytes() == b"x")
spy = FsyncSpy()
run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "off2.bin", b"x", fsync="off"))
check("'off': no fsync", spy.calls == [])
spy = FsyncSpy()
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "soft.bin", b"x", fsync="soft"))
check("'soft': one fsync", res is None and len(spy.calls) == 1 and (d / "soft.bin").read_bytes() == b"x")
spy = FsyncSpy()
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "strict.bin", b"x", fsync="strict"))
check("'strict': one fsync", res is None and len(spy.calls) == 1 and (d / "strict.bin").read_bytes() == b"x")
spy = FsyncSpy(fail=True)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "soft2.bin", b"data", fsync="soft"))
check("'soft': an OSError of fsync is ignored, the file is written", res is None and len(spy.calls) == 1
      and (d / "soft2.bin").read_bytes() == b"data" and tmps(d) == [])
spy = FsyncSpy(fail=True)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "strict2.bin", b"data", fsync="strict"))
check("'strict': an OSError of fsync is raised, nothing is stored", isinstance(res, OSError) and not (d / "strict2.bin").exists() and tmps(d) == [])
spy = FsyncSpy()
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "txt.txt", "text", fsync="strict"))
check("a text payload is synced too", res is None and len(spy.calls) == 1)
spy = FsyncSpy(fail=True)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "txt2.txt", "text", fsync="soft"))
check("... and the soft mode holds for text", res is None and (d / "txt2.txt").exists())
# the flush comes before the fsync: the data are in the file when fsync is called
seen = []


def _size_at_fsync(fd):
    seen.append(os.fstat(fd).st_size)
    return _REAL_FSYNC(fd)


run_with(fsync=_size_at_fsync, fn=lambda: aio.write_atomic(d / "flushed.bin", b"123456789", fsync="strict"))
check("the data are flushed before fsync is called", seen == [9])

# ── 5b. the soft mode raises an fsync error that says the data is not safe on disk, and only that (step 10) ────────────
import errno as _errno


class FsyncErrSpy:
    """os.fsync that records its calls and fails with an OSError of the given errno (None: an OSError without a number)."""

    def __init__(self, code):
        self.calls, self.code = [], code

    def __call__(self, fd):
        self.calls.append(fd)
        if self.code is None:
            raise OSError("fsync error without a number")
        raise OSError(self.code, os.strerror(self.code))


_DISK_ERRORS = [("EIO", _errno.EIO), ("ENOSPC", _errno.ENOSPC), ("EDQUOT", _errno.EDQUOT), ("EBADF", _errno.EBADF)]
_HARMLESS = [("EINVAL", _errno.EINVAL), ("ENOTSUP", _errno.ENOTSUP), ("ENOSYS", _errno.ENOSYS), ("EACCES", _errno.EACCES),
             ("no number", None)]

for _name, _code in _DISK_ERRORS:
    d = fresh()
    target = d / "keep.bin"
    target.write_bytes(b"OLD")
    spy = FsyncErrSpy(_code)
    res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(target, b"NEW", fsync="soft"))
    check(f"'soft': an fsync error {_name} is raised, the stored file stays, no .tmp",
          isinstance(res, OSError) and res.errno == _code and len(spy.calls) == 1 and target.read_bytes() == b"OLD" and tmps(d) == [])
for _name, _code in _HARMLESS:
    d = fresh()
    spy = FsyncErrSpy(_code)
    res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "ok.bin", b"NEW", fsync="soft"))
    check(f"'soft': an fsync error {_name} (fsync not supported here) is ignored, the file is written",
          res is None and len(spy.calls) == 1 and (d / "ok.bin").read_bytes() == b"NEW" and tmps(d) == [])
for _name, _code in _DISK_ERRORS + _HARMLESS:
    d = fresh()
    spy = FsyncErrSpy(_code)
    res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "s.bin", b"NEW", fsync="strict"))
    check(f"'strict': an fsync error {_name} is raised (unchanged), nothing is stored",
          isinstance(res, OSError) and not (d / "s.bin").exists() and tmps(d) == [])

d = fresh()
spy = FsyncErrSpy(_errno.EIO)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_tmp(d / "w.tmp", b"x", fsync="soft"))
check("write_tmp (soft): EIO is raised and its own tmp is removed", isinstance(res, OSError) and res.errno == _errno.EIO and tmps(d) == [])
spy = FsyncErrSpy(_errno.EINVAL)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_tmp(d / "w2.tmp", b"x", fsync="soft"))
check("write_tmp (soft): EINVAL is ignored, the tmp is written", res is None and (d / "w2.tmp").read_bytes() == b"x")
target = d / "st.bin"
target.write_bytes(b"OLD")
spy = FsyncErrSpy(_errno.ENOSPC)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic_stream(target, lambda f: f.write(b"NEW"), fsync="soft"))
check("write_atomic_stream (soft): ENOSPC is raised, the stored file stays, no .tmp",
      isinstance(res, OSError) and res.errno == _errno.ENOSPC and target.read_bytes() == b"OLD" and tmps(d) == ["w2.tmp"])
spy = FsyncErrSpy(_errno.EINVAL)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic_stream(d / "st2.bin", lambda f: f.write(b"NEW"), fsync="soft"))
check("write_atomic_stream (soft): EINVAL is ignored", res is None and (d / "st2.bin").read_bytes() == b"NEW")
spy = FsyncErrSpy(_errno.EIO)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic(d / "off.bin", b"x", fsync="off"))
check("'off': no fsync is called, so no error either", res is None and spy.calls == [] and (d / "off.bin").exists())
check("the errors the soft mode raises are exactly EIO, ENOSPC, EDQUOT and EBADF",
      aio._DISK_ERRNO == {_errno.EIO, _errno.ENOSPC, _errno.EDQUOT, _errno.EBADF})

if sys.platform == "win32":
    d = fresh()
    (d / "ro.bin").write_bytes(b"x")
    with open(d / "ro.bin", "rb") as handle:
        try:
            aio.sync_file(handle, "soft")
            got = None
        except OSError as exc:
            got = exc
    check("on Windows a real failing os.fsync (a read-only handle) arrives as EBADF without a winerror, and the soft mode raises it",
          got is not None and got.errno == _errno.EBADF and getattr(got, "winerror", None) is None)
else:
    skip("a real failing os.fsync on Windows", "EBADF as the only sign of a disk error is a Windows behaviour")

# ══════════════════════════════════════════════════════════════════════════════
section("6. write_atomic_stream")

d = fresh()
target = d / "big.gla"
target.write_bytes(b"OLD")
handles = []


def writer(handle):
    handles.append(handle)
    handle.write(b"HEAD")
    handle.write(b"-")
    handle.write(b"BODY")


res, _ = run_with(fn=lambda: aio.write_atomic_stream(target, writer))
check("a file written in parts is stored whole", res is None and target.read_bytes() == b"HEAD-BODY" and tmps(d) == [])
check("the callback gets a handle opened for bytes", len(handles) == 1 and handles[0].mode == "wb" and handles[0].closed)

spy = ReplaceSpy()
run_with(replace=spy, fn=lambda: aio.write_atomic_stream(target, writer))
check("default tmp: target name + '.tmp'", spy.calls == [(d / "big.gla.tmp", target)])
spy = ReplaceSpy()
run_with(replace=spy, fn=lambda: aio.write_atomic_stream(target, writer, tmp=d / "other.tmp"))
check("a named tmp is used", spy.calls == [(d / "other.tmp", target)] and tmps(d) == [])


def failing_writer(handle):
    handle.write(b"half")
    raise RuntimeError("boom")


target.write_bytes(b"OLD")
res, _ = run_with(fn=lambda: aio.write_atomic_stream(target, failing_writer))
check("an exception of the callback is raised as it is", type(res) is RuntimeError and str(res) == "boom")
check("... the stored file is untouched and no .tmp is left", target.read_bytes() == b"OLD" and tmps(d) == [])

spy = FsyncSpy(fail=True)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic_stream(target, writer, fsync="strict"))
check("a failing strict fsync raises on the stream flow, nothing changes", isinstance(res, OSError) and target.read_bytes() == b"OLD" and tmps(d) == [])
spy = FsyncSpy(fail=True)
res, _ = run_with(fsync=spy, fn=lambda: aio.write_atomic_stream(target, writer, fsync="soft"))
check("... and is ignored in the soft mode", res is None and target.read_bytes() == b"HEAD-BODY")

spy = ReplaceSpy(fail_times=2)
res, sleeps = run_with(replace=spy, fn=lambda: aio.write_atomic_stream(target, writer, attempts=4, pause_s=0.2))
check("a locked file is tried again on the stream flow", res is None and len(spy.calls) == 3 and sleeps == [0.2, 0.4])
spy = ReplaceSpy(always=True)
target.write_bytes(b"OLD")
res, _ = run_with(replace=spy, fn=lambda: aio.write_atomic_stream(target, writer, attempts=2))
check("... and the last PermissionError is raised, with a clean folder", isinstance(res, PermissionError) and target.read_bytes() == b"OLD" and tmps(d) == [])

deep = fresh() / "a" / "b" / "c.gla"
aio.write_atomic_stream(deep, writer)
check("the folder is created on the stream flow", deep.read_bytes() == b"HEAD-BODY")
d_nf = fresh()
res, _ = run_with(fn=lambda: aio.write_atomic_stream(d_nf / "no" / "c.gla", writer, mkdir=False))
check("mkdir=False with a missing folder raises and creates nothing", isinstance(res, OSError) and names(d_nf) == [])

# ══════════════════════════════════════════════════════════════════════════════
section("7. The single steps — two files swapped one after the other")

d = fresh()
(d / "raw.json").write_bytes(b"OLD-RAW")
(d / "sum.json").write_bytes(b"OLD-SUM")
aio.write_tmp(d / "raw.tmp", "raw\n", newline="\n")
aio.write_tmp(d / "sum.tmp", b"sum")
check("write_tmp writes only the tmp, the targets are untouched",
      (d / "raw.tmp").read_bytes() == b"raw\n" and (d / "sum.tmp").read_bytes() == b"sum"
      and (d / "raw.json").read_bytes() == b"OLD-RAW" and (d / "sum.json").read_bytes() == b"OLD-SUM")
aio.replace_with_retry(d / "raw.tmp", d / "raw.json")
aio.replace_with_retry(d / "sum.tmp", d / "sum.json")
check("replace_with_retry swaps each of them", (d / "raw.json").read_bytes() == b"raw\n" and (d / "sum.json").read_bytes() == b"sum" and tmps(d) == [])

aio.write_tmp(d / "deep" / "x.tmp", b"x")
check("write_tmp creates the folder", (d / "deep" / "x.tmp").read_bytes() == b"x")
d_nf = fresh()
res, _ = run_with(fn=lambda: aio.write_tmp(d_nf / "no" / "x.tmp", b"x", mkdir=False))
check("write_tmp with mkdir=False and no folder raises", isinstance(res, OSError) and names(d_nf) == [])
res, _ = run_with(fsync=FsyncSpy(fail=True), fn=lambda: aio.write_tmp(d / "bad.tmp", b"x", fsync="strict"))
check("a write_tmp that fails removes its own tmp", isinstance(res, OSError) and not (d / "bad.tmp").exists())
res, _ = run_with(fn=lambda: aio.write_tmp(d / "enc.tmp", "€", encoding="ascii"))
check("... also for an encoding error", isinstance(res, UnicodeEncodeError) and not (d / "enc.tmp").exists())
(d / "keep.tmp").write_bytes(b"left over")
aio.write_tmp(d / "keep.tmp", b"fresh")
check("write_tmp replaces a leftover tmp", (d / "keep.tmp").read_bytes() == b"fresh")

(d / "rm.tmp").write_bytes(b"x")
check("remove_quietly removes a file", aio.remove_quietly(d / "rm.tmp") is None and not (d / "rm.tmp").exists())
check("... a missing file is not an error", aio.remove_quietly(d / "never.tmp") is None)
with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
    res, _ = run_with(fn=lambda: aio.remove_quietly(d / "keep.tmp"))
check("... an OSError of the removal is swallowed", res is None and (d / "keep.tmp").exists())
check("remove_quietly takes a str path", aio.remove_quietly(str(d / "keep.tmp")) is None and not (d / "keep.tmp").exists())

# ══════════════════════════════════════════════════════════════════════════════
section("8. Guards")

source = (_SRC / "garmin" / "atomic_io.py").read_text(encoding="utf-8")
tree = ast.parse(source)
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom):
        imported.add((node.module or "").split(".")[0])
check("only the standard library is imported (errno, os, time, pathlib)", imported == {"errno", "os", "time", "pathlib"})
check("no logging in the module", "logging" not in imported and "log." not in source and "getLogger" not in source)
check("REPLACE_ATTEMPTS and REPLACE_PAUSE_S are the values of the writers (5 and 0.1)", aio.REPLACE_ATTEMPTS == 5 and aio.REPLACE_PAUSE_S == 0.1)
check("the defaults are the conservative ones: fsync 'off', one attempt",
      aio.write_atomic.__kwdefaults__["fsync"] == "off" and aio.write_atomic.__kwdefaults__["attempts"] == 1
      and aio.write_atomic_stream.__kwdefaults__["fsync"] == "off" and aio.write_atomic_stream.__kwdefaults__["attempts"] == 1
      and aio.write_tmp.__kwdefaults__["fsync"] == "off" and aio.replace_with_retry.__kwdefaults__["attempts"] == 1)
check("the three modes are named", (aio.FSYNC_OFF, aio.FSYNC_SOFT, aio.FSYNC_STRICT) == ("off", "soft", "strict"))
check("importing the module wrote nothing next to it", not any(p.name.endswith(".tmp") for p in (_SRC / "garmin").glob("*.tmp")))
check("the module is in garmin/ and not in the src/-root", (_SRC / "garmin" / "atomic_io.py").is_file() and not (_SRC / "atomic_io.py").exists())

# ══════════════════════════════════════════════════════════════════════════════
section("9. The import from a script in garmin/ (the collector runs as a subprocess)")

# The app starts the collector as `python src/garmin/garmin_collector.py`: the folder of the script is the only
# project folder on sys.path, so everything it imports at module level must be findable from garmin/. A module of
# the src/-root (log_utils.py, version.py, ...) is not. The first plan of step 2 had atomic_io in the src/-root: the
# collector would have stopped at its import, and no test in this process (src/ on the path) would have said so.
_PROBE = (
    "import importlib.util, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "assert importlib.util.find_spec('log_utils') is None, 'the probe can see the src/-root'\n"
    "import atomic_io\n"
    "import garmin_api_capability, garmin_container, garmin_source_writer, garmin_bulk_writer, garmin_collector\n"
    "print('imported', atomic_io.__name__, atomic_io.__file__)\n"
)
_probe = subprocess.run([sys.executable, "-I", "-c", _PROBE, str(_SRC / "garmin")], cwd=str(_TMPDIR), env=dict(os.environ),
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
if _probe.returncode != 0:
    print("  probe output:", (_probe.stdout + _probe.stderr).strip()[-800:])
check("a script that starts in garmin/ (only that folder on the path) imports atomic_io and the modules that use it",
      _probe.returncode == 0 and "imported atomic_io" in _probe.stdout)
check("... and the atomic_io it found is the one of garmin/",
      bool(_probe.stdout.split()) and Path(_probe.stdout.split()[-1]).resolve() == (_SRC / "garmin" / "atomic_io.py").resolve())

summary()
