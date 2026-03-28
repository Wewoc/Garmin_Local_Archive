#!/usr/bin/env python3
"""
garmin_quality.py

State Owner — sole authority over quality_log.json.

Responsibilities:
  - Load and save quality_log.json (exclusively — no other module writes it)
  - Assess data quality from a raw dict (in-memory, no file IO)
  - Upsert day entries with attempts tracking
  - Backfill quality log from existing raw/ files (one-time, on first run)
  - Determine and persist first_day
  - Scan raw/ for newly discovered low/failed quality files
  - Clean archive before first_day (dry run + delete)

All other modules receive quality data as a plain dict parameter — they
never read or write quality_log.json directly.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Load / Save
# ══════════════════════════════════════════════════════════════════════════════

def _load_quality_log() -> dict:
    """
    Loads quality_log.json. Returns empty structure if missing or corrupt.
    Applies migrations:
      - From failed_days.json (old name) → quality_log.json
      - From 'failed' list schema → 'days' list schema
      - 'category' field → 'quality' field
      - old 'error' → 'failed', old 'incomplete' → 'low'
      - Adds missing fields: recheck, last_checked
    """
    old_file = cfg.LOG_DIR / "failed_days.json"

    # Try quality_log.json first, fall back to failed_days.json migration
    source = None
    if cfg.QUALITY_LOG_FILE.exists():
        source = cfg.QUALITY_LOG_FILE
    elif old_file.exists():
        source = old_file
        log.info("  Migrating failed_days.json → quality_log.json ...")

    if source is None:
        return {"first_day": None, "devices": [], "days": []}

    try:
        with open(source, encoding="utf-8") as f:
            data = json.load(f)

        # Migrate old 'failed' key → 'days'
        if "failed" in data and "days" not in data:
            data["days"] = data.pop("failed")

        if "days" not in data or not isinstance(data["days"], list):
            return {"first_day": None, "devices": [], "days": []}

        # Ensure new root fields exist (migration from older schema)
        if "first_day" not in data:
            data["first_day"] = None
        if "devices" not in data:
            data["devices"] = []

        # Migrate first_day if stored as Unix timestamp instead of YYYY-MM-DD
        if data.get("first_day"):
            fixed = _parse_device_date(data["first_day"])
            if fixed and fixed != data["first_day"]:
                log.info(f"  Migrating first_day: {data['first_day']} -> {fixed}")
                data["first_day"] = fixed

        # Migrate devices.first_used / last_used if stored as Unix timestamps
        for dev in data.get("devices", []):
            for field in ("first_used", "last_used"):
                val = dev.get(field)
                if val and val != "unknown":
                    fixed = _parse_device_date(val)
                    if fixed and fixed != val:
                        dev[field] = fixed

        today_str = date.today().isoformat()
        for entry in data["days"]:
            # Migrate 'category' → 'quality'
            if "category" in entry and "quality" not in entry:
                old = entry.pop("category")
                entry["quality"] = "failed" if old == "error" else "low"

            # Migrate 'med' → 'medium'
            if entry.get("quality") == "med":
                entry["quality"] = "medium"

            # Ensure all new fields exist
            if "recheck" not in entry:
                q = entry.get("quality", "failed")
                entry["recheck"] = q in ("failed", "low")
            if "last_checked" not in entry:
                entry["last_checked"] = entry.get("last_attempt", today_str) or today_str
            if "attempts" not in entry:
                entry["attempts"] = 0
            if "last_attempt" not in entry:
                entry["last_attempt"] = None

            # Migrate: add 'write' field if missing (entries before v1.2.1)
            if "write" not in entry:
                entry["write"] = None  # unknown — written before this field existed

            # Reset attempts for low entries (Garmin archived data, not real failures)
            if entry.get("quality") == "low":
                entry["attempts"] = 0

        # Save to new location if migrated from old file
        if source == old_file:
            _save_quality_log(data)
            try:
                old_file.unlink()
                log.info("  Migration complete — failed_days.json removed.")
            except Exception:
                pass

        return data

    except Exception as e:
        log.warning(f"  Could not read quality log: {e} — starting fresh.")
        return {"first_day": None, "devices": [], "days": []}


def _save_quality_log(data: dict) -> None:
    """Writes quality_log.json atomically via temp file."""
    tmp = cfg.QUALITY_LOG_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(cfg.QUALITY_LOG_FILE)
    except Exception as e:
        log.warning(f"  Could not write quality_log.json: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Quality assessment (pure, no file IO)
# ══════════════════════════════════════════════════════════════════════════════

def assess_quality(raw: dict) -> str:
    """
    Assesses the quality of a raw data dict based on content.

    Returns one of:
      "high"   — intraday data present (HR values, stress values, etc.)
      "medium" — daily aggregates present but no intraday (typical for older Garmin data)
      "low"    — only summary-level data, minimum usable (stats or user_summary present)
      "failed" — nothing usable, not even basic stats
    """
    # Check for intraday data
    hr = raw.get("heart_rates") or {}
    hr_values = hr.get("heartRateValues") if isinstance(hr, dict) else None
    has_intraday_hr = isinstance(hr_values, list) and len(hr_values) > 0

    stress = raw.get("stress") or {}
    stress_values = stress.get("stressValuesArray") if isinstance(stress, dict) else None
    has_intraday_stress = isinstance(stress_values, list) and len(stress_values) > 0

    if has_intraday_hr or has_intraday_stress:
        return "high"

    # Check for daily aggregates
    stats = raw.get("stats") or {}
    user_summary = raw.get("user_summary") or {}

    has_steps = (
        _safe_get(stats, "totalSteps") is not None or
        _safe_get(user_summary, "totalSteps") is not None
    )
    has_hr_resting = (
        _safe_get(stats, "restingHeartRate") is not None or
        _safe_get(user_summary, "restingHeartRate") is not None
    )

    if has_steps or has_hr_resting:
        sleep = raw.get("sleep") or {}
        has_sleep = _safe_get(sleep, "dailySleepDTO", "sleepTimeSeconds") is not None

        if has_sleep or has_steps:
            return "medium"
        return "low"

    # Check bare minimum — any stats at all
    if isinstance(stats, dict) and stats:
        return "low"
    if isinstance(user_summary, dict) and user_summary:
        return "low"

    return "failed"


# ══════════════════════════════════════════════════════════════════════════════
#  Upsert
# ══════════════════════════════════════════════════════════════════════════════

def _upsert_quality(data: dict, day: date, quality: str, reason: str,
                    written: bool = None) -> None:
    """
    Adds or updates a day entry in the quality log.
      - 'failed': increments attempts, sets recheck=True
      - 'low':    increments attempts, sets recheck=False if attempts >= LOW_QUALITY_MAX_ATTEMPTS
      - 'medium'/'high': sets recheck=False (data is good)

    written : bool | None
      True  — writer wrote both files successfully
      False — label was 'failed', writer failed, or write was skipped
      None  — unknown (backfill, scan, or pre-v1.2.1 entry)
    """
    day_str   = day.isoformat()
    today_str = date.today().isoformat()
    now_str   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for entry in data["days"]:
        if entry.get("date") == day_str:
            entry["quality"]      = quality
            entry["reason"]       = reason
            entry["write"]        = written
            entry["last_checked"] = today_str
            if quality == "failed":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = True
            elif quality == "low":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = entry["attempts"] < cfg.LOW_QUALITY_MAX_ATTEMPTS
                if not entry["recheck"]:
                    log.info(f"    ℹ {day}: low quality after {entry['attempts']} attempts — recheck disabled")
            else:
                entry["recheck"]      = False
                entry["last_attempt"] = now_str
            return

    # New entry
    attempts = 1 if quality in ("failed", "low") else 0
    data["days"].append({
        "date":         day_str,
        "quality":      quality,
        "reason":       reason,
        "write":        written,
        "recheck":      quality in ("failed", "low"),
        "attempts":     attempts,
        "last_checked": today_str,
        "last_attempt": now_str if quality in ("failed", "low") else None,
    })


# ══════════════════════════════════════════════════════════════════════════════
#  first_day
# ══════════════════════════════════════════════════════════════════════════════

def _set_first_day(data: dict, client) -> None:
    """
    Determines and persists first_day in quality_log.json.
    Only runs when first_day is not yet set.
    Resolution order: devices → account profile → SYNC_AUTO_FALLBACK → oldest local file.
    Does not overwrite an existing first_day value.
    client is passed as a parameter — this module does not import garmin API directly.
    """
    if data.get("first_day"):
        return  # Already set — never overwrite

    log.info("  first_day not set — detecting from account ...")
    first_day = None

    # 1. Try devices
    devices = data.get("devices") or []
    first_dates = [d["first_used"] for d in devices if d.get("first_used") and d["first_used"] != "unknown"]
    if first_dates:
        first_day = min(first_dates)
        log.info(f"  first_day from devices: {first_day}")

    # 2. Try account profile
    if not first_day and client:
        try:
            profile = client.get_user_profile()
            reg = _safe_get(profile, "userInfo", "registrationDate")
            if reg:
                first_day = str(reg)[:10]
                log.info(f"  first_day from account profile: {first_day}")
        except Exception:
            pass

    # 3. Manual fallback from config
    if not first_day and cfg.SYNC_AUTO_FALLBACK:
        first_day = cfg.SYNC_AUTO_FALLBACK
        log.info(f"  first_day from SYNC_AUTO_FALLBACK: {first_day}")

    # 4. Oldest local file in raw/
    if not first_day and data.get("days"):
        known_dates = sorted(e["date"] for e in data["days"] if "date" in e)
        if known_dates:
            first_day = known_dates[0]
            log.info(f"  first_day from oldest local file: {first_day}")

    if first_day:
        data["first_day"] = first_day
        log.info(f"  ✓ first_day set to {first_day}")
    else:
        log.warning("  Could not determine first_day — will retry on next run.")


# ══════════════════════════════════════════════════════════════════════════════
#  Backfill
# ══════════════════════════════════════════════════════════════════════════════

def _backfill_quality_log(data: dict) -> int:
    """
    One-time backfill: scans all raw/ files and adds any days not yet in the
    quality log — including high and med quality days that were never recorded.
    Only runs when first_day is not yet set.
    Returns the number of newly added entries.
    """
    if not cfg.RAW_DIR.exists():
        return 0

    known = {e["date"] for e in data.get("days", []) if "date" in e}
    added = 0

    for f in sorted(cfg.RAW_DIR.glob("garmin_raw_*.json")):
        try:
            day = date.fromisoformat(f.stem.replace("garmin_raw_", ""))
        except ValueError:
            continue
        if day.isoformat() in known:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
            q = assess_quality(raw)
            _upsert_quality(data, day, q, f"Quality: {q} — backfill on first_day init",
                            written=True)
            added += 1
        except (OSError, json.JSONDecodeError):
            pass

    if added:
        log.info(f"  Backfill: {added} existing days added to quality log")
    return added


# ══════════════════════════════════════════════════════════════════════════════
#  Scan for low/failed files
# ══════════════════════════════════════════════════════════════════════════════

def get_low_quality_dates(folder: Path, known_dates: set = None) -> dict:
    """
    Scans raw/ for files with quality 'low' or 'failed' based on content.
    Skips dates already in the quality log (known_dates set).
    Returns {date: quality} for newly discovered problematic files.
    """
    result = {}
    if not folder.exists():
        return result
    for f in folder.glob("garmin_raw_*.json"):
        try:
            day = date.fromisoformat(f.stem.replace("garmin_raw_", ""))
            if known_dates and day in known_dates:
                continue  # already in quality log — skip OneDrive download
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
            q = assess_quality(raw)
            if q in ("low", "failed"):
                result[day] = q
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    if result:
        log.info(f"  Newly discovered low/failed quality files: {len(result)}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Clean archive
# ══════════════════════════════════════════════════════════════════════════════

def cleanup_before_first_day(data: dict, dry_run: bool = False) -> dict:
    """
    Removes all raw/ and summary/ files before first_day, and removes
    corresponding entries from quality_log.json.

    dry_run=True: only counts and returns stats, does not delete anything.
    Returns {"files_deleted": int, "entries_removed": int, "first_day": str}.
    """
    first_day_str = data.get("first_day")
    if not first_day_str:
        log.warning("  cleanup_before_first_day: first_day not set — nothing to clean.")
        return {"files_deleted": 0, "entries_removed": 0, "first_day": None}

    try:
        cutoff = date.fromisoformat(first_day_str)
    except ValueError:
        log.warning(f"  cleanup_before_first_day: invalid first_day '{first_day_str}'.")
        return {"files_deleted": 0, "entries_removed": 0, "first_day": first_day_str}

    files_deleted = 0

    # Delete raw files before cutoff
    for f in cfg.RAW_DIR.glob("garmin_raw_*.json"):
        try:
            d = date.fromisoformat(f.stem.replace("garmin_raw_", ""))
            if d < cutoff:
                if not dry_run:
                    f.unlink(missing_ok=True)
                files_deleted += 1
        except ValueError:
            pass

    # Delete summary files before cutoff
    for f in cfg.SUMMARY_DIR.glob("garmin_*.json"):
        try:
            d = date.fromisoformat(f.stem.replace("garmin_", ""))
            if d < cutoff:
                if not dry_run:
                    f.unlink(missing_ok=True)
                files_deleted += 1
        except ValueError:
            pass

    # Remove entries from quality log
    before = len(data["days"])
    data["days"] = [e for e in data["days"] if e.get("date", "9999") >= first_day_str]
    entries_removed = before - len(data["days"])

    if not dry_run:
        _save_quality_log(data)

    if dry_run:
        log.info(f"  cleanup_before_first_day (dry run): {files_deleted} files, {entries_removed} log entries would be removed")
    else:
        log.info(f"  cleanup_before_first_day: {files_deleted} files deleted, {entries_removed} log entries removed")

    return {"files_deleted": files_deleted, "entries_removed": entries_removed, "first_day": first_day_str}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _parse_device_date(val) -> str | None:
    """Converts a device date value to YYYY-MM-DD.
    Handles ISO strings, millisecond timestamps, and second timestamps."""
    if not val:
        return None
    s = str(val).strip()
    # Already ISO date (YYYY-MM-DD...)
    if len(s) >= 10 and s[4:5] == "-":
        return s[:10]
    # Unix timestamp (seconds ~10 digits, milliseconds ~13 digits)
    try:
        ts = int(s)
        if ts > 1e11:   # milliseconds → convert to seconds
            ts //= 1000
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


def _safe_get(d, *keys, default=None):
    """Traverses nested dicts safely. Returns default if any key is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d
