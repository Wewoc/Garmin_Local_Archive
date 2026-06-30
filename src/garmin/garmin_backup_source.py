#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_backup_source.py

Source Backup — Sole Owner of garmin_data/backup/source/.

Backs up unmodified API responses from garmin_data/source/ into
garmin_data/backup/source/YYYY-MM/. Completed months are consolidated
into source_backup_YYYY-MM.zip — analog to garmin_backup.py raw strategy.

Motivation: source/ contains the immutable API record before any pipeline
processing. If the normalizer had a bug, raw/ carries the bug — source/ does
not. Source Replay (regenerate_raw.py) depends on source/ being intact.
Backup protects against accidental deletion or filesystem errors.

Strategy: monthly directories → ZIP on month completion.
  backup/source/YYYY-MM/garmin_source_YYYY-MM-DD.json  ← open month
  backup/source/source_backup_YYYY-MM.zip              ← completed months

Public API:
  backup_source(date_str)          → bool  — copy one source file to backup/
  backfill_source()                → dict  — copy all missing source files
  check_source_backfill_needed()   → int   — count missing backup files

Leaf-Node: imports only garmin_config and stdlib. No pipeline module imports.

Called by:
  garmin/garmin_source_writer.py — write_source() (lazy import, non-fatal)
"""

import logging
import shutil
import zipfile
from datetime import date
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)

# Filename prefix for source files — must match garmin_source_writer.py
_SOURCE_PREFIX = "garmin_source_"


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def backup_source(date_str: str) -> bool:
    """
    Copies garmin_source_YYYY-MM-DD.json from source/ into
    backup/source/YYYY-MM/ after a successful write. Consolidates
    completed months into ZIP archives.

    Called by garmin_source_writer.write_source() after a successful write.
    Non-fatal — caller logs a warning on False, pipeline continues.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    bool — True on success, False on any error
    """
    try:
        src = cfg.SOURCE_DIR / f"{_SOURCE_PREFIX}{date_str}.json"
        if not src.exists():
            log.warning(f"  backup_source: source file not found for {date_str}")
            return False

        month     = date_str[:7]          # YYYY-MM
        month_dir = cfg.SOURCE_BACKUP_DIR / month
        month_dir.mkdir(parents=True, exist_ok=True)

        dst = month_dir / src.name
        dst.write_bytes(src.read_bytes())
        log.debug(f"  backup_source: {date_str} → backup/source/{month}/")

        # Consolidate completed months
        _consolidate_source_months(current_month=month)
        return True

    except Exception as e:
        log.error(f"  backup_source: failed for {date_str}: {e}")
        return False


def backfill_source() -> dict:
    """
    Copies all source files that have no backup copy yet.

    One-time operation after garmin_backup_source.py is first introduced.
    Safe to call repeatedly — skips files that already have a backup.
    Consolidates completed months after copying.

    Returns
    -------
    dict with keys:
      copied  int — files successfully backed up
      skipped int — files that already had a backup
      failed  int — files that could not be copied
    """
    if not cfg.SOURCE_DIR.exists():
        log.info("  backfill_source: source/ does not exist — nothing to do")
        return {"copied": 0, "skipped": 0, "failed": 0}

    copied         = 0
    skipped        = 0
    failed         = 0
    months_touched = set()

    for src in sorted(cfg.SOURCE_DIR.glob(f"{_SOURCE_PREFIX}*.json")):
        try:
            stem     = src.stem  # garmin_source_YYYY-MM-DD
            date_str = stem.replace(_SOURCE_PREFIX, "")
            month    = date_str[:7]

            zip_path = cfg.SOURCE_BACKUP_DIR / f"source_backup_{month}.zip"
            dir_dst  = cfg.SOURCE_BACKUP_DIR / month / src.name

            in_zip = zip_path.exists() and _zip_contains(zip_path, src.name)
            if dir_dst.exists() or in_zip:
                skipped += 1
                continue

            month_dir = cfg.SOURCE_BACKUP_DIR / month
            month_dir.mkdir(parents=True, exist_ok=True)
            (month_dir / src.name).write_bytes(src.read_bytes())
            copied += 1
            months_touched.add(month)

        except Exception as e:
            log.error(f"  backfill_source: failed for {src.name}: {e}")
            failed += 1

    current_month = date.today().strftime("%Y-%m")
    for month in months_touched:
        if month < current_month:
            _consolidate_source_months(current_month=current_month)
            break

    log.info(
        f"  backfill_source: {copied} copied, {skipped} already present, {failed} failed"
    )
    return {"copied": copied, "skipped": skipped, "failed": failed}


def check_source_backfill_needed() -> int:
    """
    Returns the number of source files in source/ that have no backup copy yet.

    Fast check — only counts, does not copy anything.
    Returns 0 if source/ does not exist or backup is complete.

    Returns
    -------
    int — number of source files without a backup
    """
    if not cfg.SOURCE_DIR.exists():
        return 0

    count = 0
    for src in cfg.SOURCE_DIR.glob(f"{_SOURCE_PREFIX}*.json"):
        stem     = src.stem
        date_str = stem.replace(_SOURCE_PREFIX, "")
        month    = date_str[:7]

        zip_path = cfg.SOURCE_BACKUP_DIR / f"source_backup_{month}.zip"
        dir_dst  = cfg.SOURCE_BACKUP_DIR / month / src.name

        in_zip = zip_path.exists() and _zip_contains(zip_path, src.name)
        if not dir_dst.exists() and not in_zip:
            count += 1

    return count


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _consolidate_source_months(current_month: str) -> None:
    """
    Zips all completed month directories in backup/source/.
    A month is complete if it is not the current_month.

    Two cases handled:
      - ZIP does not exist yet → create new ZIP from directory, delete directory.
      - ZIP already exists, directory also exists → append missing files,
        then delete directory.

    Deletes the directory after successful ZIP creation/update.
    """
    if not cfg.SOURCE_BACKUP_DIR.exists():
        return

    for month_dir in sorted(cfg.SOURCE_BACKUP_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        month_name = month_dir.name          # YYYY-MM
        if month_name >= current_month:
            continue                         # skip current month

        zip_path = cfg.SOURCE_BACKUP_DIR / f"source_backup_{month_name}.zip"
        try:
            files = list(month_dir.glob(f"{_SOURCE_PREFIX}*.json"))
            if not files:
                month_dir.rmdir()
                continue

            if zip_path.exists():
                # ZIP exists — append missing files
                appended = 0
                with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
                    existing = set(zf.namelist())
                    for f in files:
                        if f.name not in existing:
                            zf.write(f, f.name)
                            appended += 1
                if appended:
                    log.info(
                        f"  backup_source: source/{month_name}/ → {appended} "
                        f"file(s) appended to {zip_path.name}"
                    )
                # Verify ZIP integrity after append
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        log.error(
                            f"  backup_source: ZIP integrity check failed after "
                            f"append for {month_name} — directory kept as fallback"
                        )
                        continue
            else:
                # No ZIP yet — create from scratch
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in files:
                        zf.write(f, f.name)
                # Verify ZIP before deleting source directory
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if zf.testzip() is not None:
                        raise RuntimeError("ZIP integrity check failed")
                log.info(
                    f"  backup_source: source/{month_name}/ consolidated → "
                    f"{zip_path.name}"
                )

            shutil.rmtree(month_dir)

        except Exception as e:
            log.error(
                f"  backup_source: failed to consolidate source/{month_name}/: {e}"
            )


def _zip_contains(zip_path: Path, filename: str) -> bool:
    """Returns True if filename exists inside zip_path. Silent on error."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return filename in zf.namelist()
    except Exception:
        return False
