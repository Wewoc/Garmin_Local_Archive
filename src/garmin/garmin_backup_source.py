#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

Since v1.7.6.2.1 this module is a thin shell: the month-folder / monthly-ZIP flow
lives once in garmin_backup_common (shared with raw/ and the bulk store); here only
the description of the source kind (folders, names, validity check) and the public
names remain. The kind is built at every call from the paths of garmin_config and
this module's logger, so the log lines and the tests keep their module.

Public API:
  backup_source(date_str)          → bool  — copy one source file to backup/
  backfill_source()                → dict  — copy all missing source files
  check_source_backfill_needed()   → int   — count missing backup files
  check_source_stale_backups()     → int   — count backup copies that differ from source/ (v1.7.5.6)
  refresh_source_backups()         → dict  — bring those copies up to date (v1.7.5.6)

Imports garmin_config, garmin_backup_common (a leaf node) and stdlib. No pipeline module imports.

Called by:
  garmin/garmin_source_writer.py — write_source() (lazy import, non-fatal)
"""

import logging
from pathlib import Path

import garmin_backup_common as common
import garmin_config as cfg

log = logging.getLogger(__name__)

# Filename prefix for source files — must match garmin_source_writer.py
_SOURCE_PREFIX = "garmin_source_"


def _kind() -> common.BackupKind:
    """The source backup as a kind of file for garmin_backup_common (built at call time)."""
    return common.BackupKind(
        area="source", src_dir=cfg.SOURCE_DIR, backup_dir=cfg.SOURCE_BACKUP_DIR,
        prefix=_SOURCE_PREFIX, zip_prefix="source_backup_",
        is_valid=common.is_json_object, log_prefix="backup_source", log=log)


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def backup_source(date_str: str, force: bool = False) -> bool:
    """
    Copies garmin_source_YYYY-MM-DD.json from source/ into
    backup/source/YYYY-MM/ after a successful write. Consolidates
    completed months into ZIP archives.

    Called by garmin_source_writer.write_source() after a successful write.
    Non-fatal — caller logs a warning on False, pipeline continues.

    The consolidation runs against today's real calendar month, so an
    already-completed month is consolidated right away and a rewritten day
    replaces its ZIP entry when its content differs (v1.7.4.2, v1.7.5.6); a
    date still in the open current month simply stays in its month folder.

    force (v1.7.1.7): when True, this date's file is allowed to replace an
    already-consolidated entry of the same name inside a completed month's
    ZIP (see _consolidate_source_months()), even when the bytes are identical.
    Scope is exactly this one date — never the whole month directory — so an
    unrelated batch of already-good, already-consolidated days sharing the
    same month is never touched or at risk. Used exclusively by the deliberate
    per-day Force-Refetch path.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format
    force    : bool — allow replacing an already-consolidated ZIP entry for
               this exact date (see above)

    Returns
    -------
    bool — True on success, False on any error
    """
    return common.backup_file(_kind(), date_str, force=force, consolidate=_consolidate_source_months)


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
    return common.backfill(_kind(), consolidate=_consolidate_source_months)


def check_source_backfill_needed() -> int:
    """
    Returns the number of source files in source/ that have no backup copy yet.

    Fast check — only counts, does not copy anything.
    Returns 0 if source/ does not exist or backup is complete.

    Returns
    -------
    int — number of source files without a backup
    """
    return common.check_backfill_needed(_kind())


# ══════════════════════════════════════════════════════════════════════════════
#  Refresh — outdated backup copies (v1.7.5.6)
# ══════════════════════════════════════════════════════════════════════════════

def check_source_stale_backups() -> int:
    """
    Returns the number of source files whose backup copy differs from them.

    Fast check — compares bytes with the copy in the month folder, or CRC32
    and size with the entry in the monthly ZIP (nothing is unpacked); copies
    nothing. A source file with no backup at all is not counted (that is
    backfill_source()'s job), nor is a source file that is not valid JSON
    (refresh_source_backups() reports those).
    """
    return common.check_stale(_kind())


def refresh_source_backups() -> dict:
    """
    Brings outdated backup copies up to date: every source file whose backup
    copy differs is copied into its month folder, then the completed months
    are consolidated once — a changed file replaces its ZIP entry (see
    _consolidate_source_months()).

    Before v1.7.5.6 a source file changed after its first backup (the steps
    patch, a refreshed response) kept its old version in the monthly ZIP; this
    catches up archives that already have such copies. Content-based and
    idempotent: a second run finds nothing. source/ is never modified.

    A source file that is not a JSON object is never copied over its backup —
    it is reported and the backup copy stays as it is.

    Returns dict: {"refreshed": int, "unreadable": int, "errors": int}
    """
    return common.refresh(_kind(), consolidate=_consolidate_source_months)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _consolidate_source_months(current_month: str, force_filenames: set[str] | None = None) -> None:
    """
    Zips all completed month directories in backup/source/.
    A month is complete if it is not the current_month.

    Two cases handled:
      - ZIP does not exist yet → create new ZIP from directory, delete directory.
      - ZIP already exists, directory also exists → append missing files,
        then delete directory.
        v1.7.5.6: a file that is already in the ZIP but whose bytes differ
        from the directory copy is REPLACED — the directory copy is always
        the newest backup of that day (backup_source() overwrites it on every
        call). Identical files are left alone; the ZIP is not rewritten for
        them.

    force_filenames (v1.7.1.7): set of filenames (e.g.
    "garmin_source_2026-08-27.json") that are replaced even when the
    directory copy is byte-identical — used by the deliberate per-day
    Force-Refetch path. Scope is intentionally per-filename, never per-month:
    only the files present in the month directory may touch the ZIP's
    existing entries, every other entry (including in the same month) is
    left as-is. None (default) — only files whose bytes differ are replaced.

    Deletes the directory after successful ZIP creation/update. The flow itself
    is garmin_backup_common.consolidate_months().
    """
    common.consolidate_months(_kind(), current_month, force_filenames)


def _zip_contains(zip_path: Path, filename: str) -> bool:
    """Returns True if filename exists inside zip_path. Silent on error."""
    return common.zip_contains(zip_path, filename)
