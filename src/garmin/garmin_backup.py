#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_backup.py

Backup — Sole Owner of garmin_data/backup/.

Responsibilities:
  - Incremental raw/ backup: copy daily raw file into backup/raw/YYYY-MM/
    after each successful write (triggered by garmin_writer.py)
  - Monthly raw consolidation: zip completed months into raw_backup_YYYY-MM.zip,
    delete the directory afterwards
  - quality_log.json backup: monthly snapshot + yearly consolidation
    (triggered by garmin_quality._save_quality_log)
  - Restore quality_log.json from latest valid backup ZIP
  - Startup check: compare quality_log write=True entries vs. existing raw files,
    report missing days for GUI Restore Data button
  - Refresh (v1.7.5.6): bring backup copies up to date that differ from the
    raw file they were made from (check_raw_stale_backups / refresh_raw_backups)

No other module writes to backup/.
Does NOT import garmin_writer or garmin_quality — avoids circular imports.
Reads from raw/ and log/ (read-only), writes only to backup/.

Since v1.7.6.2.1 the raw/ month-folder / monthly-ZIP flow (backup, consolidation, backfill,
refresh) lives once in garmin_backup_common (shared with source/ and the bulk store); here only
the description of the raw kind and the public names remain. The kind is built at every call from
the paths of garmin_config and this module's logger, so the log lines and the tests keep their
module. quality_log backup, the startup integrity check and the restore stay here.
"""

import json
import logging
import zipfile
from datetime import date
from pathlib import Path

import garmin_backup_common as common
import garmin_config as cfg

log = logging.getLogger(__name__)


def _kind() -> common.BackupKind:
    """The raw backup as a kind of file for garmin_backup_common (built at call time)."""
    return common.BackupKind(
        area="raw", src_dir=cfg.RAW_DIR, backup_dir=cfg.RAW_BACKUP_DIR,
        prefix="garmin_raw_", zip_prefix="raw_backup_",
        is_valid=common.is_dated_object, log=log)


# ══════════════════════════════════════════════════════════════════════════════
#  Raw backup (B1 / B4)
# ══════════════════════════════════════════════════════════════════════════════

def backup_raw(date_str: str, force: bool = False) -> bool:
    """
    Copies garmin_raw_YYYY-MM-DD.json into backup/raw/YYYY-MM/ after a
    successful write. Triggered by garmin_writer.write_day().

    The consolidation runs against today's real calendar month, so an
    already-completed month is consolidated right away and a rewritten day
    (backfill, mirror import, silo repair, ...) replaces its ZIP entry when
    its content differs (v1.7.4.2, v1.7.5.6); a date still in the open
    current month simply stays in its month folder.

    force (v1.7.1.7): when True, this date's file is allowed to replace an
    already-consolidated entry of the same name inside a completed month's
    ZIP (see _consolidate_raw_months()), even when the bytes are identical.
    Scope is exactly this one date — never the whole month directory — so an
    unrelated batch of already-good, already-consolidated days sharing the
    same month is never touched or at risk, even if that month sits past the
    180-day retry window. Used exclusively by the deliberate per-day
    Force-Refetch path.

    Returns True on success, False on any error.
    Caller (garmin_writer) logs ERROR + shows panel warning on False.
    """
    return common.backup_file(_kind(), date_str, force=force, consolidate=_consolidate_raw_months)


def _consolidate_raw_months(current_month: str, force_filenames: set[str] | None = None) -> None:
    """
    Zips all completed month directories in backup/raw/.
    A month is complete if it is not the current_month.

    Two cases handled:
      - ZIP does not exist yet → create new ZIP from directory, delete directory.
      - ZIP already exists, directory also exists → append missing files from
        directory into existing ZIP ('a' mode), then delete directory.
        This covers the case where a historical day is fetched after the month
        was already consolidated (e.g. via Background Timer).
        v1.7.5.6: a file that is already in the ZIP but whose bytes differ from
        the directory copy is REPLACED — the directory copy is always the
        newest backup of that day (backup_raw() overwrites it on every call).
        Identical files are left alone; the ZIP is not rewritten for them.

    force_filenames (v1.7.1.7): set of filenames (e.g. "garmin_raw_2026-08-27.json")
    that are replaced even when the directory copy is byte-identical — used by
    the deliberate per-day Force-Refetch path. Scope is intentionally
    per-filename, never per-month: a month can be mostly already-consolidated,
    good data with only one or two rewritten days mixed in, and only those
    exact filenames (the files present in the month directory) may touch the
    ZIP's existing entries. None (default) — only files whose bytes differ are
    replaced.

    Deletes the directory after successful ZIP creation/update. The flow itself
    is garmin_backup_common.consolidate_months().
    """
    common.consolidate_months(_kind(), current_month, force_filenames)



# ══════════════════════════════════════════════════════════════════════════════
#  quality_log backup (A2 / A4)
# ══════════════════════════════════════════════════════════════════════════════

def backup_quality_log() -> None:
    """
    Creates a monthly snapshot of quality_log.json and consolidates
    completed years into yearly ZIPs.
    Triggered by garmin_quality._save_quality_log().
    """
    if not cfg.QUALITY_LOG_FILE.exists():
        return

    try:
        cfg.LOG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        today     = date.today()
        month_str = today.strftime("%Y-%m")
        snap_path = cfg.LOG_BACKUP_DIR / f"quality_log_{month_str}.zip"

        payload = cfg.QUALITY_LOG_FILE.read_bytes()

        # Data-loss guard (v1.7.4.1 follow-up): refuse to overwrite an
        # existing snapshot with a log that lost more than half its day
        # entries. days[] only grows in normal operation, so a drop this
        # large can only mean corruption/partial rebuild, never legitimate use.
        if snap_path.exists():
            try:
                new_days = len(json.loads(payload).get("days", []))
                with zipfile.ZipFile(snap_path, "r") as zf:
                    old_days = len(json.loads(
                        zf.read("quality_log.json").decode("utf-8")
                    ).get("days", []))
                if old_days > 0 and new_days < old_days * 0.5:
                    log.warning(
                        f"  backup_quality_log: refusing to overwrite "
                        f"{snap_path.name} — new log has {new_days} day(s), "
                        f"existing snapshot has {old_days}."
                    )
                    _consolidate_log_years(current_year=today.year)
                    return
            except Exception as e:
                log.warning(
                    f"  backup_quality_log: day-count guard failed, "
                    f"proceeding with overwrite: {e}"
                )

        # Monthly snapshot — overwrite if exists (latest state of this month)
        with zipfile.ZipFile(snap_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("quality_log.json", payload)
        log.debug(f"  backup: quality_log snapshot → {snap_path.name}")

        # Yearly consolidation (A4) — all completed years without yearly ZIP
        _consolidate_log_years(current_year=today.year)

    except Exception as e:
        log.error(f"  backup_quality_log: failed: {e}")


def _consolidate_log_years(current_year: int) -> None:
    """
    For each completed calendar year (< current_year) that has monthly ZIPs
    but no yearly ZIP yet, creates quality_log_YYYY.zip containing all
    monthly snapshots. Monthly ZIPs are kept (yearly is additive, not replacing).
    """
    if not cfg.LOG_BACKUP_DIR.exists():
        return

    # Collect years from existing monthly ZIPs
    years: dict[int, list[Path]] = {}
    for p in cfg.LOG_BACKUP_DIR.glob("quality_log_????-??.zip"):
        try:
            yr = int(p.stem.split("_")[-1][:4])
        except (ValueError, IndexError) as e:
            log.warning(f"  _consolidate_log_years: could not parse year from {p.name}: {e}")
            continue
        if yr >= current_year:
            continue
        years.setdefault(yr, []).append(p)

    for yr, monthly_zips in sorted(years.items()):
        yearly_path = cfg.LOG_BACKUP_DIR / f"quality_log_{yr}.zip"
        if yearly_path.exists():
            continue
        try:
            with zipfile.ZipFile(yearly_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for mp in sorted(monthly_zips):
                    zf.write(mp, mp.name)
            log.info(f"  backup: quality_log_{yr}.zip created "
                     f"({len(monthly_zips)} monthly snapshots)")
        except Exception as e:
            log.error(f"  backup: failed to create quality_log_{yr}.zip: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Restore quality_log (A7)
# ══════════════════════════════════════════════════════════════════════════════

def restore_quality_log() -> dict | None:
    """
    Restores quality_log.json from the latest valid monthly backup ZIP.
    Returns the loaded dict on success, None if no valid backup found.
    Called by garmin_quality._load_quality_log() on checksum mismatch.
    Does NOT write quality_log.json — caller decides what to do with the dict.
    """
    if not cfg.LOG_BACKUP_DIR.exists():
        log.warning("  restore_quality_log: LOG_BACKUP_DIR does not exist.")
        return None

    # Find all monthly ZIPs, sorted descending (latest first)
    candidates = sorted(
        cfg.LOG_BACKUP_DIR.glob("quality_log_????-??.zip"),
        reverse=True,
    )
    if not candidates:
        log.warning("  restore_quality_log: no backup ZIPs found.")
        return None

    for zip_path in candidates:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if zf.testzip() is not None:
                    log.warning(f"  restore: ZIP corrupt — skipping {zip_path.name}")
                    continue
                data = json.loads(zf.read("quality_log.json").decode("utf-8"))
            if "days" in data and isinstance(data["days"], list):
                log.info(f"  restore_quality_log: restored from {zip_path.name}")
                return data
        except Exception as e:
            log.warning(f"  restore: failed to read {zip_path.name}: {e}")

    log.warning("  restore_quality_log: no valid backup found.")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Startup check — raw/ integrity (B5)
# ══════════════════════════════════════════════════════════════════════════════

def check_raw_integrity() -> dict:
    """
    Compares quality_log entries with write=True against actually present
    and readable raw files. Run at app startup in a background thread.

    Returns dict:
      missing_days   list[str]     — dates in quality_log write=True but no raw file
      no_backup      list[str]     — missing days that also have no backup copy
      total_checked  int           — number of write=True entries examined
      error          str | None    — reason the check could not complete, if any
    """
    missing_days = []
    no_backup    = []

    if not cfg.QUALITY_LOG_FILE.exists():
        return {"missing_days": [], "no_backup": [], "total_checked": 0, "error": None}

    try:
        data    = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        entries = [e for e in data.get("days", []) if e.get("write") is True]
    except Exception as e:
        reason = f"could not read quality_log: {e}"
        log.warning(f"  check_raw_integrity: {reason}")
        return {"missing_days": [], "no_backup": [], "total_checked": 0, "error": reason}

    for entry in entries:
        date_str = entry.get("date", "")
        if not date_str:
            continue
        raw_file = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
        if raw_file.exists():
            try:
                with open(raw_file, encoding="utf-8") as f:
                    json.load(f)
                continue          # file present and readable — OK
            except Exception as e:
                log.warning(f"  check_raw_integrity: {date_str} raw file present but unreadable: {e}")
                # unreadable — treat as missing

        missing_days.append(date_str)

        # Check if backup exists for this day
        month     = date_str[:7]
        zip_path  = cfg.RAW_BACKUP_DIR / f"raw_backup_{month}.zip"
        dir_path  = cfg.RAW_BACKUP_DIR / month / f"garmin_raw_{date_str}.json"
        has_backup = dir_path.exists() or (
            zip_path.exists() and _zip_contains(zip_path, f"garmin_raw_{date_str}.json")
        )
        if not has_backup:
            no_backup.append(date_str)

    if missing_days:
        log.warning(
            f"  check_raw_integrity: {len(missing_days)} missing raw files "
            f"({len(no_backup)} without backup)"
        )

    return {
        "missing_days":  missing_days,
        "no_backup":     no_backup,
        "total_checked": len(entries),
        "error":         None,
    }


def restore_raw_days(date_strs: list[str]) -> dict:
    """
    Restores raw files for the given date strings from backup.
    Tries open month directory first, then monthly ZIP.

    Own downgrade guard (v1.6.5.8, Fix 2): if a raw file already exists for
    a date AND its quality_log entry is already "high" — the best tier a
    day can have — the restore is skipped for that date. A backup copy
    cannot improve on "high"; the protection previously observed here was
    only a side effect of write_day() -> backup_raw() timing, not a
    guarantee of its own. Restore Data's original purpose — filling in a
    genuinely missing file — is unaffected; this only catches the case
    where the file has since reappeared at the best possible quality.
    Reads quality_log.json directly (same pattern as check_raw_integrity())
    rather than importing garmin_quality — avoids the circular import this
    module deliberately does not have. Best-effort: if the log can't be
    read, no date is treated as "already high" and every date proceeds
    through the normal restore path below.

    Returns dict:
      restored                list[str]      — dates successfully restored
      skipped_already_current list[str]      — dates skipped: file already
                                                present at "high" quality
      failed                  list[str]      — dates where restore failed (no backup or error)
      errors                  dict[str, str] — date → reason, one entry per date in 'failed'
    """
    restored                 = []
    skipped_already_current  = []
    failed                   = []
    errors                   = {}

    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)

    _quality_by_date = {}
    try:
        _qlog = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        _quality_by_date = {
            e.get("date"): e.get("quality")
            for e in _qlog.get("days", []) if e.get("date")
        }
    except Exception as e:
        log.warning(f"  restore_raw_days: could not read quality_log for downgrade guard: {e}")

    for date_str in date_strs:
        month      = date_str[:7]
        filename   = f"garmin_raw_{date_str}.json"
        dst        = cfg.RAW_DIR / filename
        last_error = None

        # Own downgrade guard — file already present at the best quality tier.
        if dst.exists() and _quality_by_date.get(date_str) == "high":
            skipped_already_current.append(date_str)
            log.info(f"  restore_raw: {date_str} — already present at high quality, skipped")
            continue

        # 1. Try open month directory
        dir_src = cfg.RAW_BACKUP_DIR / month / filename
        if dir_src.exists():
            try:
                dst.write_bytes(dir_src.read_bytes())
                restored.append(date_str)
                log.info(f"  restore_raw: {date_str} ← backup/raw/{month}/")
                continue
            except Exception as e:
                log.error(f"  restore_raw: dir copy failed for {date_str}: {e}")
                last_error = f"dir copy failed: {e}"

        # 2. Try monthly ZIP
        zip_path = cfg.RAW_BACKUP_DIR / f"raw_backup_{month}.zip"
        if zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    data = zf.read(filename)
                dst.write_bytes(data)
                restored.append(date_str)
                log.info(f"  restore_raw: {date_str} ← raw_backup_{month}.zip")
                continue
            except Exception as e:
                log.error(f"  restore_raw: zip restore failed for {date_str}: {e}")
                last_error = f"zip restore failed: {e}"

        failed.append(date_str)
        errors[date_str] = last_error or "no backup found"
        log.warning(f"  restore_raw: no backup found for {date_str}")

    return {"restored": restored, "skipped_already_current": skipped_already_current,
            "failed": failed, "errors": errors}


# ══════════════════════════════════════════════════════════════════════════════
#  Backfill — existing raw files (one-time, on first sync after v1.5.1)
# ══════════════════════════════════════════════════════════════════════════════

def check_raw_backfill_needed() -> int:
    """
    Returns the number of raw files in raw/ that have no backup copy yet.
    Fast check — only counts, does not copy anything.
    Returns 0 if raw/ does not exist or backup is complete.

    Bug 2 fix: zip_path.exists() alone is not sufficient — the file may be
    absent from the ZIP even if the ZIP for that month exists. The check
    looks for the specific file in the ZIP (garmin_backup_common.zip_contains).
    """
    return common.check_backfill_needed(_kind())


def backfill_raw() -> dict:
    """
    Copies all raw files that have no backup yet into backup/raw/YYYY-MM/.
    Completed months are consolidated into ZIPs immediately.
    Idempotent — safe to call multiple times.

    Bug 1 fix: zip_path.exists() alone is not sufficient as a skip guard —
    the specific file may be absent from the ZIP even if the ZIP for that
    month exists; the flow verifies the file is in the ZIP before skipping.

    Returns dict: {"copied": int, "skipped": int, "errors": int}
    """
    result = common.backfill(_kind(), consolidate=_consolidate_raw_months)
    return {"copied": result["copied"], "skipped": result["skipped"], "errors": result["failed"]}


# ══════════════════════════════════════════════════════════════════════════════
#  Refresh — outdated backup copies (v1.7.5.6)
# ══════════════════════════════════════════════════════════════════════════════

def check_raw_stale_backups() -> int:
    """
    Returns the number of raw files whose backup copy differs from them.

    Fast check — compares bytes with the copy in the month folder, or CRC32
    and size with the entry in the monthly ZIP (nothing is unpacked); copies
    nothing. A raw file with no backup at all is not counted (that is
    backfill_raw()'s job), nor is a raw file that is not a valid day file
    (refresh_raw_backups() reports those).
    """
    return common.check_stale(_kind())


def refresh_raw_backups() -> dict:
    """
    Brings outdated backup copies up to date: every raw file whose backup copy
    differs is copied into its month folder, then the completed months are
    consolidated once — a changed file replaces its ZIP entry (see
    _consolidate_raw_months()).

    Before v1.7.5.6 a day rewritten after its first backup (backfill, mirror
    import, silo repair, ...) kept its old version in the monthly ZIP; this
    catches up archives that already have such copies. Content-based and
    idempotent: a second run finds nothing. raw/ is never modified.

    A raw file that is not a valid day file (not a JSON object, or its "date"
    does not match the file name) is never copied over its backup — it is
    reported and the backup copy stays as it is.

    Returns dict: {"refreshed": int, "unreadable": int, "errors": int}
    """
    return common.refresh(_kind(), consolidate=_consolidate_raw_months)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _zip_contains(zip_path: Path, filename: str) -> bool:
    """Returns True if filename exists inside zip_path. Silent on error."""
    return common.zip_contains(zip_path, filename)
