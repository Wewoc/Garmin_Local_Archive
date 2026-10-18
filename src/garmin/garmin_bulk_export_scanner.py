#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_export_scanner.py

Finds the FIT files in a Garmin GDPR export and hands them over as bytes —
the counterpart to garmin_bulk_fit_reader.py, which turns the bytes of one
file into messages. Part of the bulk store (v1.7.6). Reads only; the only thing
it ever writes are anonymous temporary files (see below).

Leaf node: standard library only, no project imports, no garmin_config.

Input — what the user chose in the import dialog, in any of these shapes:
  1. the whole export as one ZIP (inner ZIPs inside it),
  2. the export unpacked once to a folder (inner ZIPs still packed),
  3. a folder in which the inner ZIPs are unpacked as well (loose .fit files),
  4. one inner ZIP chosen directly — or a single .fit file.
One recursive walk covers all of them: a .fit entry is delivered, a .zip entry
is opened and walked the same way, anything else is counted and ignored.
Nothing is decided by folder or file names other than the extension (matched
case-insensitively), and nothing is filtered by FIT file type here — that is
the importer's job, with the reader.

Output — iter_fit_files() yields (sha256 hex digest, bytes) per file. The same
content is delivered once (counted as a duplicate afterwards): the export holds
a few files twice, and the bulk store names its originals by content hash. The
order is reproducible: entries are walked sorted by their path inside the ZIP
or folder.

Limits (a damaged or hostile file must not take the application down)
  MAX_ZIP_DEPTH   ZIP levels that are opened (an export has two) — deeper ZIPs
                  are not opened and counted in ScanStats.too_deep
  MAX_FIT_BYTES   size of one FIT file (the largest in the maintainer's export
                  is 368 KB) — larger entries are skipped, counted as oversize
A ZIP that cannot be read, or an entry with a wrong CRC, is counted and skipped;
the walk goes on. A path that does not exist raises FileNotFoundError, when
iter_fit_files() is called.

Inner ZIPs are copied to an anonymous temporary file (tempfile.TemporaryFile)
before they are opened: no memory peak for a large inner ZIP (70 MB takes about
0.3 s), and the file is closed — and so removed — in every case, also when the
caller stops reading early. Nothing is unpacked into a folder.

Privacy
  The entries of a real export are named after the e-mail address of the
  account. No entry name is returned, counted, logged or put into an exception
  here: ScanStats holds numbers only, and this module has no logging and no
  print. Callers must not print entry names either (there is nothing to print:
  they only ever get hashes).

Public API:
  iter_fit_files(path, stats=None) -> Iterator[(hash, bytes)]
  ScanStats          — dataclass of counters, filled while the walk runs
  MAX_ZIP_DEPTH, MAX_FIT_BYTES
"""

import hashlib
import shutil
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAX_ZIP_DEPTH = 3
MAX_FIT_BYTES = 64 * 1024 * 1024

# Everything that can go wrong while reading a ZIP or one of its entries.
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError,
               EOFError, zlib.error, NotImplementedError)


@dataclass
class ScanStats:
    """Counters of one walk. Numbers only — never a name.

    fit_seen            .fit entries met (= delivered + duplicates + oversize + unreadable_entries)
    fit_yielded         different files delivered
    duplicates          files not delivered again because the same content was delivered before
    oversize            .fit entries over MAX_FIT_BYTES (skipped)
    unreadable_entries  .fit entries that could not be read (wrong CRC, I/O error, ...)
    zips_opened         ZIPs opened successfully (the chosen one and the inner ones)
    zips_unreadable     ZIPs that could not be opened, or a chosen file that is neither ZIP nor FIT
    too_deep            ZIPs not opened because of MAX_ZIP_DEPTH
    ignored             entries and files that are neither .fit nor .zip
    """
    fit_seen: int = 0
    fit_yielded: int = 0
    duplicates: int = 0
    oversize: int = 0
    unreadable_entries: int = 0
    zips_opened: int = 0
    zips_unreadable: int = 0
    too_deep: int = 0
    ignored: int = 0


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def iter_fit_files(path, stats=None) -> Iterator[tuple]:
    """
    Walks an export (ZIP, folder, inner ZIP or single .fit file) and yields
    (sha256 hex digest, bytes) for every different FIT file.

    Parameters
    ----------
    path  : str | Path — what the user chose
    stats : ScanStats | None — filled while the caller iterates (a new one is
            used and discarded if None)

    Raises
    ------
    FileNotFoundError — at the call, if the path does not exist
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError("export path does not exist")
    return _scan(root, stats if stats is not None else ScanStats())


# ══════════════════════════════════════════════════════════════════════════════
#  The walk
# ══════════════════════════════════════════════════════════════════════════════

def _scan(root, stats):
    seen = set()
    if root.is_dir():
        yield from _walk_dir(root, seen, stats)
    elif zipfile.is_zipfile(root):
        yield from _walk_zip_file(root, 1, seen, stats)
    elif root.name.lower().endswith(".fit"):
        yield from _emit_file(root, seen, stats)
    else:
        stats.zips_unreadable += 1


def _register(data, seen, stats):
    """(digest, data) for new content, None for content delivered before."""
    digest = hashlib.sha256(data).hexdigest()
    if digest in seen:
        stats.duplicates += 1
        return None
    seen.add(digest)
    stats.fit_yielded += 1
    return digest, data


def _emit_file(path, seen, stats):
    stats.fit_seen += 1
    try:
        if path.stat().st_size > MAX_FIT_BYTES:
            stats.oversize += 1
            return
        data = path.read_bytes()
    except OSError:
        stats.unreadable_entries += 1
        return
    item = _register(data, seen, stats)
    if item is not None:
        yield item


def _walk_dir(root, seen, stats):
    """A folder is not a ZIP level; the ZIPs inside it start at level 1."""
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(root).as_posix())
    for path in files:
        name = path.name.lower()
        if name.endswith(".fit"):
            yield from _emit_file(path, seen, stats)
        elif name.endswith(".zip"):
            yield from _walk_zip_file(path, 1, seen, stats)
        else:
            stats.ignored += 1


def _walk_zip_file(path, level, seen, stats):
    """level = ZIP level of this ZIP (1 for the outermost)."""
    try:
        zf = zipfile.ZipFile(path)
    except _ZIP_ERRORS:
        stats.zips_unreadable += 1
        return
    with zf:
        stats.zips_opened += 1
        yield from _walk_zip(zf, level, seen, stats)


def _walk_zip(zf, level, seen, stats):
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        if info.is_dir():
            continue
        name = info.filename.lower()
        if name.endswith(".fit"):
            stats.fit_seen += 1
            if info.file_size > MAX_FIT_BYTES:
                stats.oversize += 1
                continue
            try:
                data = zf.read(info)
            except _ZIP_ERRORS:
                stats.unreadable_entries += 1
                continue
            item = _register(data, seen, stats)
            if item is not None:
                yield item
        elif name.endswith(".zip"):
            if level + 1 > MAX_ZIP_DEPTH:
                stats.too_deep += 1
                continue
            yield from _walk_nested(zf, info, level + 1, seen, stats)
        else:
            stats.ignored += 1


def _walk_nested(zf, info, level, seen, stats):
    """An inner ZIP: copied to a temporary file, opened, walked, closed in every case."""
    tmp = tempfile.TemporaryFile()
    try:
        try:
            with zf.open(info) as src:
                shutil.copyfileobj(src, tmp, 1024 * 1024)
            tmp.seek(0)
            inner = zipfile.ZipFile(tmp)
        except _ZIP_ERRORS:
            stats.zips_unreadable += 1
            return
        with inner:
            stats.zips_opened += 1
            yield from _walk_zip(inner, level, seen, stats)
    finally:
        tmp.close()
