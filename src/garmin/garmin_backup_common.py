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
    """
    area: str
    src_dir: Path
    backup_dir: Path
    prefix: str
    zip_prefix: str
    is_valid: Callable[[bytes, str], bool]
    log_prefix: str = "backup"
    suffix: str = ".json"

    @property
    def pattern(self) -> str:
        return f"{self.prefix}*{self.suffix}"

    def zip_path(self, month: str) -> Path:
        return self.backup_dir / f"{self.zip_prefix}{month}.zip"

    def date_of(self, path: Path) -> str:
        return path.stem.replace(self.prefix, "")


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
                log.warning(f"  backup read: could not read the month folder copy of {name}: {e}")
        zip_path = kind.zip_path(month)
        if zip_path.exists():
            with zipfile.ZipFile(zip_path, "r") as zf:
                if name in zf.namelist():
                    return zf.read(name)
        return None
    except Exception as e:
        log.warning(f"  backup read: could not read the backup copy of {name}: {e}")
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
            log.warning(f"  {fn}: source file not found for {date_str}")
            return False

        month     = date_str[:7]          # YYYY-MM
        month_dir = kind.backup_dir / month
        month_dir.mkdir(parents=True, exist_ok=True)

        dst = month_dir / src.name
        dst.write_bytes(src.read_bytes())
        log.debug(f"  {fn}: {date_str} → backup/{kind.area}/{month}/")

        force_filenames   = {src.name} if force else None
        consolidate_month = date.today().strftime("%Y-%m")
        (consolidate or _default_consolidate(kind))(
            current_month=consolidate_month, force_filenames=force_filenames)
        return True

    except Exception as e:
        log.error(f"  {fn}: failed for {date_str}: {e}")
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
                    log.info(
                        f"  {lp}: {area}/{month_name}/ → {appended} file(s) "
                        f"appended to {zip_path.name}"
                    )
                # Verify ZIP integrity after append
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        log.error(
                            f"  {lp}: ZIP integrity check failed after append "
                            f"for {month_name} — directory kept as fallback"
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
                        log.info(
                            f"  {lp}: {area}/{month_name}/ → {len(to_replace)} "
                            f"file(s) replaced in {zip_path.name}"
                        )
                    except Exception as e:
                        log.error(
                            f"  {lp}: force-replace failed for {month_name}: {e} "
                            f"— directory kept as fallback"
                        )
                        try:
                            if tmp_zip.exists():
                                tmp_zip.unlink()
                        except Exception as _cleanup_e:
                            log.debug(f"  {lp}: tmp zip cleanup failed for {month_name}: {_cleanup_e}")
                        continue
            else:
                # No ZIP yet — create from scratch
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in files:
                        zf.write(f, f.name)
                # Verify ZIP before deleting the directory
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        raise RuntimeError("ZIP integrity check failed")
                log.info(f"  {lp}: {area}/{month_name}/ consolidated → {zip_path.name}")

            shutil.rmtree(month_dir)

        except Exception as e:
            log.error(f"  {lp}: failed to consolidate {area}/{month_name}/: {e}")


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
            log.warning(f"  check_{kind.area}_backfill_needed: failed for {src.name}: {e}")
    return count


def backfill(kind: BackupKind, consolidate=None) -> dict:
    """
    Copies every file of src_dir that has no backup copy into backup_dir/YYYY-MM/; completed
    months are consolidated into ZIPs once at the end. Idempotent.

    Returns {"copied": int, "skipped": int, "failed": int}.
    """
    area = kind.area
    if not kind.src_dir.exists():
        log.info(f"  backfill_{area}: {area}/ does not exist — nothing to do")
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
            log.error(f"  backfill_{area}: failed for {src.name}: {e}")
            failed += 1

    current_month = date.today().strftime("%Y-%m")
    for month in months_touched:
        if month < current_month:
            (consolidate or _default_consolidate(kind))(current_month=current_month)
            break

    log.info(f"  backfill_{area}: {copied} copied, {skipped} skipped, {failed} failed")
    return {"copied": copied, "skipped": skipped, "failed": failed}


# ══════════════════════════════════════════════════════════════════════════════
#  Refresh — outdated backup copies
# ══════════════════════════════════════════════════════════════════════════════

def zip_index(zip_path: Path) -> dict:
    """
    {filename: (crc32, size)} of a monthly ZIP, read from its directory only —
    nothing is decompressed. Empty (with a warning) if the ZIP cannot be read.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return {i.filename: (i.CRC, i.file_size) for i in zf.infolist()}
    except Exception as e:
        log.warning(f"  backup refresh: cannot read {zip_path.name}: {e}")
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

    A file without any backup copy is in neither list.
    """
    outdated   = []
    unreadable = []
    if not kind.src_dir.exists():
        return outdated, unreadable

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
                    indexes[month] = zip_index(zip_path) if zip_path.exists() else {}
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
            log.warning(f"  backup refresh: could not check {src.name}: {e}")
    return outdated, unreadable


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

    Returns {"refreshed": int, "unreadable": int, "errors": int}.
    """
    outdated, unreadable = find_outdated(kind)
    refreshed = 0
    errors    = 0

    for src in unreadable:
        log.warning(
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
            log.error(f"  backup refresh: failed for {src.name}: {e}")
            errors += 1

    if refreshed:
        (consolidate or _default_consolidate(kind))(current_month=date.today().strftime("%Y-%m"))

    log.info(
        f"  backup refresh ({kind.area}): {refreshed} refreshed, "
        f"{len(unreadable)} unreadable, {errors} errors"
    )
    return {"refreshed": refreshed, "unreadable": len(unreadable), "errors": errors}
