#!/usr/bin/env python3
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

No other module writes to backup/.
Does NOT import garmin_writer or garmin_quality — avoids circular imports.
Reads from raw/ and log/ (read-only), writes only to backup/.
"""

import json
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Raw backup (B1 / B4)
# ══════════════════════════════════════════════════════════════════════════════

def backup_raw(date_str: str) -> bool:
    """
    Copies garmin_raw_YYYY-MM-DD.json into backup/raw/YYYY-MM/ after a
    successful write. Triggered by garmin_writer.write_day().

    Returns True on success, False on any error.
    Caller (garmin_writer) logs ERROR + shows panel warning on False.
    """
    try:
        raw_file = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
        if not raw_file.exists():
            log.warning(f"  backup_raw: source not found for {date_str}")
            return False

        month     = date_str[:7]          # YYYY-MM
        month_dir = cfg.RAW_BACKUP_DIR / month
        month_dir.mkdir(parents=True, exist_ok=True)

        dst = month_dir / raw_file.name
        dst.write_bytes(raw_file.read_bytes())
        log.debug(f"  backup_raw: {date_str} → backup/raw/{month}/")

        # Consolidate completed months (B4)
        _consolidate_raw_months(current_month=month)
        return True

    except Exception as e:
        log.error(f"  backup_raw: failed for {date_str}: {e}")
        return False


def _consolidate_raw_months(current_month: str) -> None:
    """
    Zips all completed month directories in backup/raw/ that don't yet have
    a ZIP. A month is complete if it is not the current_month.
    Deletes the directory after successful ZIP creation.
    """
    if not cfg.RAW_BACKUP_DIR.exists():
        return
    for month_dir in sorted(cfg.RAW_BACKUP_DIR.iterdir()):
        if not month_dir.is_dir():
            continue
        month_name = month_dir.name          # YYYY-MM
        if month_name >= current_month:
            continue                         # skip current month
        zip_path = cfg.RAW_BACKUP_DIR / f"raw_backup_{month_name}.zip"
        if zip_path.exists():
            continue                         # already consolidated
        try:
            files = list(month_dir.glob("garmin_raw_*.json"))
            if not files:
                month_dir.rmdir()
                continue
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, f.name)
            # Verify ZIP before deleting source directory
            with zipfile.ZipFile(zip_path, "r") as zf:
                if zf.testzip() is not None:
                    raise RuntimeError("ZIP integrity check failed")
            import shutil
            shutil.rmtree(month_dir)
            log.info(f"  backup: raw/{month_name}/ consolidated → {zip_path.name}")
        except Exception as e:
            log.error(f"  backup: failed to consolidate raw/{month_name}/: {e}")


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

        # Monthly snapshot — overwrite if exists (latest state of this month)
        payload = cfg.QUALITY_LOG_FILE.read_bytes()
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
        except (ValueError, IndexError):
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
      missing_days   list[str]  — dates in quality_log write=True but no raw file
      no_backup      list[str]  — missing days that also have no backup copy
      total_checked  int        — number of write=True entries examined
    """
    missing_days = []
    no_backup    = []

    if not cfg.QUALITY_LOG_FILE.exists():
        return {"missing_days": [], "no_backup": [], "total_checked": 0}

    try:
        data    = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        entries = [e for e in data.get("days", []) if e.get("write") is True]
    except Exception as e:
        log.warning(f"  check_raw_integrity: could not read quality_log: {e}")
        return {"missing_days": [], "no_backup": [], "total_checked": 0}

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
            except Exception:
                pass              # unreadable — treat as missing

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
    }


def restore_raw_days(date_strs: list[str]) -> dict:
    """
    Restores raw files for the given date strings from backup.
    Tries open month directory first, then monthly ZIP.

    Returns dict:
      restored  list[str] — dates successfully restored
      failed    list[str] — dates where restore failed (no backup or error)
    """
    restored = []
    failed   = []

    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)

    for date_str in date_strs:
        month    = date_str[:7]
        filename = f"garmin_raw_{date_str}.json"
        dst      = cfg.RAW_DIR / filename

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

        failed.append(date_str)
        log.warning(f"  restore_raw: no backup found for {date_str}")

    return {"restored": restored, "failed": failed}

# ══════════════════════════════════════════════════════════════════════════════
#  Backfill — existing raw files (one-time, on first sync after v1.5.1)
# ══════════════════════════════════════════════════════════════════════════════

def check_raw_backfill_needed() -> int:
    """
    Returns the number of raw files in raw/ that have no backup copy yet.
    Fast check — only counts, does not copy anything.
    Returns 0 if raw/ does not exist or backup is complete.
    """
    if not cfg.RAW_DIR.exists():
        return 0

    count = 0
    for raw_file in cfg.RAW_DIR.glob("garmin_raw_*.json"):
        try:
            date_str = raw_file.stem.replace("garmin_raw_", "")
            month    = date_str[:7]
            zip_path = cfg.RAW_BACKUP_DIR / f"raw_backup_{month}.zip"
            dir_path = cfg.RAW_BACKUP_DIR / month / raw_file.name
            if not zip_path.exists() and not dir_path.exists():
                count += 1
        except Exception:
            pass
    return count


def backfill_raw() -> dict:
    """
    Copies all raw files that have no backup yet into backup/raw/YYYY-MM/.
    Completed months are consolidated into ZIPs immediately.
    Idempotent — safe to call multiple times.

    Returns dict: {"copied": int, "skipped": int, "errors": int}
    """
    if not cfg.RAW_DIR.exists():
        return {"copied": 0, "skipped": 0, "errors": 0}

    copied  = 0
    skipped = 0
    errors  = 0
    months_touched = set()

    for raw_file in sorted(cfg.RAW_DIR.glob("garmin_raw_*.json")):
        try:
            date_str = raw_file.stem.replace("garmin_raw_", "")
            month    = date_str[:7]
            zip_path = cfg.RAW_BACKUP_DIR / f"raw_backup_{month}.zip"
            dir_path = cfg.RAW_BACKUP_DIR / month / raw_file.name

            if zip_path.exists() or dir_path.exists():
                skipped += 1
                continue

            month_dir = cfg.RAW_BACKUP_DIR / month
            month_dir.mkdir(parents=True, exist_ok=True)
            (month_dir / raw_file.name).write_bytes(raw_file.read_bytes())
            copied += 1
            months_touched.add(month)

        except Exception as e:
            log.error(f"  backfill_raw: failed for {raw_file.name}: {e}")
            errors += 1

    current_month = date.today().strftime("%Y-%m")
    for month in months_touched:
        if month < current_month:
            _consolidate_raw_months(current_month=current_month)
            break

    log.info(f"  backfill_raw: {copied} copied, {skipped} skipped, {errors} errors")
    return {"copied": copied, "skipped": skipped, "errors": errors}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _zip_contains(zip_path: Path, filename: str) -> bool:
    """Returns True if filename exists inside zip_path. Silent on error."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return filename in zf.namelist()
    except Exception:
        return False
