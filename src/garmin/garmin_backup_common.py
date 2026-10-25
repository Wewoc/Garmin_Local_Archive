#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_backup_common.py

Shared month-folder / monthly-ZIP backup mechanics (v1.7.6.2). Leaf Node: stdlib
only, no garmin_config, no pipeline imports.

garmin_backup.py (raw/) and garmin_backup_source.py (source/) each carried a copy
of the same flow; the bulk store (v1.7.6.2) would have been a third. This module is
that flow once, taken over from the two modules unchanged in behaviour. It owns no
folder and decides nothing about *what* is backed up: the caller describes a kind of
file with a BackupKind (source folder, backup folder, name pattern, ZIP name,
validity check) and the module does the work. Sole-write-authority stays with the
caller's module: only the backup folder handed in is written, and the source folder
is only read.

Strategy (unchanged):
  backup_dir/YYYY-MM/<name>        open month: the newest copy of a day, overwritten
                                   by every backup of that day
  backup_dir/<zip_prefix>YYYY-MM.zip
                                   completed month: the folder is packed, verified
                                   and removed; a file that is in the ZIP with other
                                   bytes is replaced (a ZIP has no in-place replace:
                                   rebuilt without the old entry, verified, swapped
                                   in with os.replace)

Replace scope is always per file name, never per month: force_filenames replaces
those files even when the bytes are identical; every other entry of the ZIP is
copied as it is.

Public API (kind = BackupKind):
  backup_file(kind, date_str, force=False, consolidate=None)  -> bool
  consolidate_months(kind, current_month, force_filenames=None) -> None
  backfill(kind, consolidate=None)                            -> {"copied", "skipped", "failed"}
  check_backfill_needed(kind)                                 -> int
  find_outdated(kind)                                         -> (outdated, unreadable)
  check_stale(kind)                                           -> int
  refresh(kind, consolidate=None)                             -> {"refreshed", "unreadable", "errors"}
  read_copy(kind, name)                                       -> bytes | None   (v1.7.6.2, reads only)
  zip_index(zip_path), zip_contains(zip_path, filename)
  is_dated_object(data, date_str), is_json_object(data, date_str)   ready-made validity checks

Hardening (v1.7.6.2.1): a monthly ZIP that does not open or fails its check is never appended to or
replaced (the month folder stays as the fallback, one error line names the ZIP); a ZIP this module began
and could not finish is removed again; a file the refresh cannot read counts as an error; every error
line carries the exception type and the traceback goes to debug level; lines about a ZIP name it.

consolidate (optional) is the function the caller wants called for the consolidation
step instead of consolidate_months: it is called with the keyword arguments
current_month= and, for backup_file, force_filenames=. A caller whose tests patch its
own consolidation function passes it here.
"""

import json
import logging
import os
import shutil
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Description of a kind of file
# ══════════════════════════════════════════════════════════════════════════════

def is_dated_object(data: bytes, date_str: str) -> bool:
    """True if data is a JSON object whose "date" equals date_str (the check for raw/ day files)."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return False
    return isinstance(obj, dict) and obj.get("date") == date_str


def is_json_object(data: bytes, date_str: str) -> bool:
    """True if data is a JSON object (the check for source/ files; date_str is not used)."""
    try:
        return isinstance(json.loads(data.decode("utf-8")), dict)
    except Exception:
        return False


@dataclass(frozen=True)
class BackupKind:
    """
    What is backed up and where.

    area        short name used in the log lines and in function names of the messages
                ("raw", "source", ...): "backup: raw/2024-08/ ...", "backfill_raw: ..."
    src_dir     folder with the files to back up (read only)
    backup_dir  folder the month folders and monthly ZIPs live in
    prefix      the part of a file name before the date ("garmin_raw_")
    zip_prefix  the part of a ZIP name before the month ("raw_backup_" -> raw_backup_2024-08.zip)
    is_valid    is_valid(data, date_str) -> bool: may a file with these bytes replace its backup copy
    log_prefix  start of the log lines of the consolidation ("backup", "backup_source")
    suffix      file name suffix (".json")
    log         logger the kind's messages go to (v1.7.6.2.1): a caller that wraps this module hands in its own
                module logger, so its log lines and its tests keep their logger; None = this module's logger
    """
    area: str
    src_dir: Path
    backup_dir: Path
    prefix: str
    zip_prefix: str
    is_valid: Callable[[bytes, str], bool]
    log_prefix: str = "backup"
    suffix: str = ".json"
    log: object = None

    @property
    def pattern(self) -> str:
        return f"{self.prefix}*{self.suffix}"

    def zip_path(self, month: str) -> Path:
        return self.backup_dir / f"{self.zip_prefix}{month}.zip"

    def date_of(self, path: Path) -> str:
        return path.stem.replace(self.prefix, "")


def _lg(kind: BackupKind):
    """The logger of a kind: its own if it has one, otherwise this module's (looked up at call time)."""
    return kind.log if kind.log is not None else log


def _why(e: BaseException) -> str:
    """'Type: text' of an exception (v1.7.6.2.1): the type is what tells a PermissionError from a bug."""
    return f"{type(e).__name__}: {e}"


def _zip_problem(zip_path: Path) -> str | None:
    """
    Why a monthly ZIP cannot be built on (v1.7.6.2.1), or None if it is intact: it opens and every
    entry passes its check. 'a' mode would write a new archive behind a file that is no ZIP and the
    old entries would be gone unnoticed (register finding F-9), so nothing is appended to a ZIP
    this function complains about.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
    except Exception as e:
        return _why(e)
    return None if bad is None else f"entry {bad} fails its check"


def read_copy(kind: BackupKind, name: str) -> bytes | None:
    """
    The backup copy of one file: the month folder first (the newest copy of a day), otherwise
    the entry in the monthly ZIP. None if there is no copy or it cannot be read (a warning for
    a copy that exists but cannot be read; a month folder copy that cannot be read falls back
    to the ZIP). Reads only; nothing is written.
    """
    try:
        month = kind.date_of(Path(name))[:7]
        dir_copy = kind.backup_dir / month / name
        if dir_copy.exists():
            try:
                return dir_copy.read_bytes()
            except Exception as e:
                _lg(kind).warning(f"  backup read: could not read the month folder copy of {name}: {_why(e)}")
        zip_path = kind.zip_path(month)
        if zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if name in zf.namelist():
                        return zf.read(name)
            except Exception as e:
                _lg(kind).warning(f"  backup read: could not read {name} from {zip_path.name}: {_why(e)}")
                _lg(kind).debug("  traceback:", exc_info=True)
                return None
        return None
    except Exception as e:
        _lg(kind).warning(f"  backup read: could not read the backup copy of {name}: {_why(e)}")
        _lg(kind).debug("  traceback:", exc_info=True)
        return None


def _default_consolidate(kind: BackupKind) -> Callable:
    return lambda **kw: consolidate_months(kind, **kw)


# ══════════════════════════════════════════════════════════════════════════════
#  Backup of one file
# ══════════════════════════════════════════════════════════════════════════════

def backup_file(kind: BackupKind, date_str: str, force: bool = False, consolidate=None) -> bool:
    """
    Copies the file of one day from src_dir into backup_dir/YYYY-MM/ and consolidates the
    completed months against today's real calendar month (so a rewritten day in a
    completed month replaces its ZIP entry right away; a day of the open current month
    simply stays in its month folder).

    force: the file of this day replaces its ZIP entry even when the bytes are identical
    (scope: exactly this file name).

    Returns True on success, False on any error (logged, never raised).
    """
    fn = f"backup_{kind.area}"
    try:
        src = kind.src_dir / f"{kind.prefix}{date_str}{kind.suffix}"
        if not src.exists():
            _lg(kind).warning(f"  {fn}: source file not found for {date_str}")
            return False

        month     = date_str[:7]          # YYYY-MM
        month_dir = kind.backup_dir / month
        month_dir.mkdir(parents=True, exist_ok=True)

        dst = month_dir / src.name
        dst.write_bytes(src.read_bytes())
        _lg(kind).debug(f"  {fn}: {date_str} → backup/{kind.area}/{month}/")

        force_filenames   = {src.name} if force else None
        consolidate_month = date.today().strftime("%Y-%m")
        (consolidate or _default_consolidate(kind))(
            current_month=consolidate_month, force_filenames=force_filenames)
        return True

    except Exception as e:
        _lg(kind).error(f"  {fn}: failed for {date_str}: {_why(e)}")
        _lg(kind).debug("  traceback:", exc_info=True)
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Consolidation of completed months
# ══════════════════════════════════════════════════════════════════════════════

def consolidate_months(kind: BackupKind, current_month: str, force_filenames: set[str] | None = None) -> None:
    """
    Zips all completed month directories in backup_dir. A month is complete if it is
    not current_month and not later.

    Two cases:
      - the ZIP does not exist yet: create it from the directory, verify, delete the directory.
      - the ZIP exists and the directory too: append the files that are not in the ZIP; a file
        that is in the ZIP with other bytes is replaced (the directory copy is always the newest
        backup of that day); identical files are left alone. Then delete the directory.

    force_filenames: file names that are replaced even when the directory copy is
    byte-identical. Scope is per file name, never per month.

    Any failure keeps the directory as the fallback and goes to the log; the next month is
    still processed.
    """
    if not kind.backup_dir.exists():
        return
    lp, area = kind.log_prefix, kind.area
    for month_dir in sorted(kind.backup_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        month_name = month_dir.name          # YYYY-MM
        if month_name >= current_month:
            continue                         # skip current month and later
        zip_path = kind.zip_path(month_name)
        try:
            files = list(month_dir.glob(kind.pattern))
            if not files:
                month_dir.rmdir()
                continue
            if zip_path.exists():
                # v1.7.6.2.1: only an intact ZIP is built on. A ZIP that does not open or fails its
                # check is not touched (no append, no replace), the directory stays as the fallback.
                problem = _zip_problem(zip_path)
                if problem is not None:
                    _lg(kind).error(
                        f"  {lp}: {zip_path.name} is damaged ({problem}) — not touched, "
                        f"{area}/{month_name}/ kept as fallback"
                    )
                    continue
                # ZIP exists but the directory also has files — append the ones not yet
                # in the ZIP, replace the ones whose bytes differ, then delete the directory.
                appended   = 0
                to_replace = []
                with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
                    existing = set(zf.namelist())
                    for f in files:
                        if f.name not in existing:
                            zf.write(f, f.name)
                            appended += 1
                        elif (force_filenames and f.name in force_filenames) \
                                or zf.read(f.name) != f.read_bytes():
                            to_replace.append(f)
                if appended:
                    _lg(kind).info(
                        f"  {lp}: {area}/{month_name}/ → {appended} file(s) "
                        f"appended to {zip_path.name}"
                    )
                # Verify ZIP integrity after append
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        _lg(kind).error(
                            f"  {lp}: ZIP integrity check failed after append "
                            f"for {month_name} ({zip_path.name}) — directory kept as fallback"
                        )
                        continue

                # ── Replace ───────────────────────────────────────────────────
                # zipfile cannot replace an entry in place — rebuild without the
                # old entry, add the new version, verify, then swap in. Only the
                # to_replace file names are touched; every other entry is copied as-is.
                if to_replace:
                    tmp_zip = zip_path.with_suffix(".zip.tmp")
                    try:
                        with zipfile.ZipFile(zip_path, "r") as src_zf, \
                             zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as dst_zf:
                            replace_names = {f.name for f in to_replace}
                            for item in src_zf.infolist():
                                if item.filename in replace_names:
                                    continue  # drop old entry — replaced below
                                dst_zf.writestr(item, src_zf.read(item.filename))
                            for f in to_replace:
                                dst_zf.write(f, f.name)
                        with zipfile.ZipFile(tmp_zip, "r") as check_zf:
                            if check_zf.testzip() is not None:
                                raise RuntimeError("ZIP integrity check failed after force-replace")
                        os.replace(tmp_zip, zip_path)
                        _lg(kind).info(
                            f"  {lp}: {area}/{month_name}/ → {len(to_replace)} "
                            f"file(s) replaced in {zip_path.name}"
                        )
                    except Exception as e:
                        _lg(kind).error(
                            f"  {lp}: force-replace failed for {month_name} ({zip_path.name}): {_why(e)} "
                            f"— directory kept as fallback"
                        )
                        _lg(kind).debug("  traceback:", exc_info=True)
                        try:
                            if tmp_zip.exists():
                                tmp_zip.unlink()
                        except Exception as _cleanup_e:
                            _lg(kind).debug(
                                f"  {lp}: tmp zip cleanup failed for {month_name}: {_why(_cleanup_e)}")
                        continue
            else:
                # No ZIP yet — create from scratch
                try:
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for f in files:
                            zf.write(f, f.name)
                    # Verify ZIP before deleting the directory
                    with zipfile.ZipFile(zip_path, "r") as zf:
                        if zf.testzip() is not None:
                            raise RuntimeError("ZIP integrity check failed")
                except Exception:
                    # v1.7.6.2.1: a ZIP this call just began and could not finish is not kept. The
                    # damaged-ZIP check above would otherwise block the next run for good, while the
                    # intact directory is all the next run needs to build it again.
                    try:
                        zip_path.unlink(missing_ok=True)
                    except Exception as _cleanup_e:
                        _lg(kind).debug(
                            f"  {lp}: unfinished ZIP cleanup failed for {month_name}: {_why(_cleanup_e)}")
                    raise
                _lg(kind).info(f"  {lp}: {area}/{month_name}/ consolidated → {zip_path.name}")

            shutil.rmtree(month_dir)

        except Exception as e:
            _lg(kind).error(
                f"  {lp}: failed to consolidate {area}/{month_name}/ ({zip_path.name}): {_why(e)}")
            _lg(kind).debug("  traceback:", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Backfill — files without any backup copy
# ══════════════════════════════════════════════════════════════════════════════

def check_backfill_needed(kind: BackupKind) -> int:
    """
    Number of files in src_dir that have no backup copy yet (neither in the month folder nor
    in the monthly ZIP). Fast check — only counts, copies nothing. 0 if src_dir does not exist.

    A ZIP that exists is not enough: the file must be in it (zip_contains).
    """
    if not kind.src_dir.exists():
        return 0

    count = 0
    for src in kind.src_dir.glob(kind.pattern):
        try:
            month    = kind.date_of(src)[:7]
            zip_path = kind.zip_path(month)
            dir_path = kind.backup_dir / month / src.name
            in_zip   = zip_path.exists() and zip_contains(zip_path, src.name)
            if not dir_path.exists() and not in_zip:
                count += 1
        except Exception as e:
            _lg(kind).warning(f"  check_{kind.area}_backfill_needed: failed for {src.name}: {_why(e)}")
            _lg(kind).debug("  traceback:", exc_info=True)
    return count


def backfill(kind: BackupKind, consolidate=None) -> dict:
    """
    Copies every file of src_dir that has no backup copy into backup_dir/YYYY-MM/; completed
    months are consolidated into ZIPs once at the end. Idempotent.

    Returns {"copied": int, "skipped": int, "failed": int}.
    """
    area = kind.area
    if not kind.src_dir.exists():
        _lg(kind).info(f"  backfill_{area}: {area}/ does not exist — nothing to do")
        return {"copied": 0, "skipped": 0, "failed": 0}

    copied         = 0
    skipped        = 0
    failed         = 0
    months_touched = set()

    for src in sorted(kind.src_dir.glob(kind.pattern)):
        try:
            month    = kind.date_of(src)[:7]
            zip_path = kind.zip_path(month)
            dir_path = kind.backup_dir / month / src.name

            in_zip = zip_path.exists() and zip_contains(zip_path, src.name)
            if dir_path.exists() or in_zip:
                skipped += 1
                continue

            month_dir = kind.backup_dir / month
            month_dir.mkdir(parents=True, exist_ok=True)
            (month_dir / src.name).write_bytes(src.read_bytes())
            copied += 1
            months_touched.add(month)

        except Exception as e:
            _lg(kind).error(f"  backfill_{area}: failed for {src.name}: {_why(e)}")
            _lg(kind).debug("  traceback:", exc_info=True)
            failed += 1

    current_month = date.today().strftime("%Y-%m")
    for month in months_touched:
        if month < current_month:
            (consolidate or _default_consolidate(kind))(current_month=current_month)
            break

    _lg(kind).info(f"  backfill_{area}: {copied} copied, {skipped} skipped, {failed} failed")
    return {"copied": copied, "skipped": skipped, "failed": failed}


# ══════════════════════════════════════════════════════════════════════════════
#  Refresh — outdated backup copies
# ══════════════════════════════════════════════════════════════════════════════

def zip_index(zip_path: Path, logger=None) -> dict:
    """
    {filename: (crc32, size)} of a monthly ZIP, read from its directory only —
    nothing is decompressed. Empty (with a warning) if the ZIP cannot be read.
    The warning goes to logger (a kind's logger, see BackupKind.log), by default to this module's.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return {i.filename: (i.CRC, i.file_size) for i in zf.infolist()}
    except Exception as e:
        (log if logger is None else logger).warning(f"  backup refresh: cannot read {zip_path.name}: {_why(e)}")
        return {}


def zip_contains(zip_path: Path, filename: str) -> bool:
    """True if filename exists inside zip_path. Silent on error."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return filename in zf.namelist()
    except Exception:
        return False


def find_outdated(kind: BackupKind) -> tuple[list, list]:
    """
    Returns (outdated, unreadable): lists of paths in src_dir.

    outdated   — a backup copy exists and differs from the file. The copy in the month folder
                 counts first (it is the newest backup of a day), otherwise the entry in the
                 monthly ZIP (CRC32 and size, nothing is unpacked).
    unreadable — the copy differs, but the file is not valid (kind.is_valid says no).

    A file without any backup copy is in neither list. A file that cannot be checked at all
    (it cannot be read) is in neither list either; refresh() counts those as errors (_scan).
    """
    outdated, unreadable, _failed = _scan(kind)
    return outdated, unreadable


def _scan(kind: BackupKind) -> tuple[list, list, list]:
    """
    (outdated, unreadable, failed): find_outdated() plus the files that could not be checked
    (v1.7.6.2.1). Each failed check is a warning with the exception type, and the file is in
    `failed` so that refresh() can count it as an error instead of silently reporting
    '0 errors'.
    """
    outdated   = []
    unreadable = []
    failed     = []
    if not kind.src_dir.exists():
        return outdated, unreadable, failed

    indexes: dict = {}
    for src in sorted(kind.src_dir.glob(kind.pattern)):
        try:
            date_str = kind.date_of(src)
            month    = date_str[:7]
            data     = src.read_bytes()

            dir_copy = kind.backup_dir / month / src.name
            if dir_copy.exists():
                differs = dir_copy.read_bytes() != data
            else:
                if month not in indexes:
                    zip_path = kind.zip_path(month)
                    indexes[month] = zip_index(zip_path, _lg(kind)) if zip_path.exists() else {}
                entry = indexes[month].get(src.name)
                if entry is None:
                    continue                 # no backup copy at all — backfill's job
                differs = entry != (zlib.crc32(data) & 0xFFFFFFFF, len(data))

            if not differs:
                continue
            if kind.is_valid(data, date_str):
                outdated.append(src)
            else:
                unreadable.append(src)
        except Exception as e:
            _lg(kind).warning(f"  backup refresh: could not check {src.name}: {_why(e)}")
            _lg(kind).debug("  traceback:", exc_info=True)
            failed.append(src)
    return outdated, unreadable, failed


def check_stale(kind: BackupKind) -> int:
    """Number of files whose backup copy differs from them. Fast check, copies nothing."""
    outdated, _unreadable = find_outdated(kind)
    return len(outdated)


def refresh(kind: BackupKind, consolidate=None) -> dict:
    """
    Brings outdated backup copies up to date: every file whose backup copy differs is copied
    into its month folder, then the completed months are consolidated once — a changed file
    replaces its ZIP entry. Content-based and idempotent: a second run finds nothing.
    src_dir is never modified.

    A file that is not valid (kind.is_valid) is never copied over its backup — it is reported
    and the backup copy stays as it is.

    Returns {"refreshed": int, "unreadable": int, "errors": int}. errors counts the files that
    could not be checked (v1.7.6.2.1) and the copies that failed.
    """
    outdated, unreadable, failed = _scan(kind)
    refreshed = 0
    errors    = len(failed)

    for src in unreadable:
        _lg(kind).warning(
            f"  backup refresh: {src.name} is not a valid {kind.area} file — "
            f"its backup copy is left as it is"
        )

    for src in outdated:
        try:
            month     = kind.date_of(src)[:7]
            month_dir = kind.backup_dir / month
            month_dir.mkdir(parents=True, exist_ok=True)
            (month_dir / src.name).write_bytes(src.read_bytes())
            refreshed += 1
        except Exception as e:
            _lg(kind).error(f"  backup refresh: failed for {src.name}: {_why(e)}")
            _lg(kind).debug("  traceback:", exc_info=True)
            errors += 1

    if refreshed:
        (consolidate or _default_consolidate(kind))(current_month=date.today().strftime("%Y-%m"))

    _lg(kind).info(
        f"  backup refresh ({kind.area}): {refreshed} refreshed, "
        f"{len(unreadable)} unreadable, {errors} errors"
    )
    return {"refreshed": refreshed, "unreadable": len(unreadable), "errors": errors}
