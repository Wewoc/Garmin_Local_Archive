#!/usr/bin/env python3
"""
garmin/quality/_maint.py

Maintenance sub-module for garmin_quality.
Upsert, first_day detection, archive cleanup.

Internal — import only via garmin_quality (facade).
"""

import logging
from datetime import date, datetime

import garmin_config as cfg

log = logging.getLogger(__name__)

# Quality rank — defined here, re-exported via facade
_QUALITY_RANK = {"high": 4, "medium": 3, "low": 2, "failed": 1}


# ══════════════════════════════════════════════════════════════════════════════
#  Upsert
# ══════════════════════════════════════════════════════════════════════════════

def _upsert_quality(data: dict, day: date, quality: str, reason: str,
                    written: bool = None, source: str = "legacy",
                    fields: dict = None,
                    validator_result: dict = None) -> None:
    """
    Adds or updates a day entry in the quality log.
      - 'failed': increments attempts, sets recheck=True
      - 'low':    increments attempts, sets recheck=False if attempts >= LOW_QUALITY_MAX_ATTEMPTS
      - 'medium'/'high': sets recheck=False (data is good)

    written : bool | None
      True  — writer wrote both files successfully
      False — label was 'failed', writer failed, or write was skipped
      None  — unknown (backfill, scan, or pre-v1.2.1 entry)

    source : str
      Origin of the data: "api" | "bulk" | "csv" | "manual" | "legacy"
      Always overwrites the existing value — the most recent write wins.

    validator_result : dict | None
      Complete result object from garmin_validator.validate().
      Three fields are extracted and stored per day entry:
        validator_result       — "ok" | "warning" | "critical"
        validator_issues       — list of structured issue dicts (empty if ok)
        validator_schema_version — schema version used for validation
      None = validator was not run (legacy entries, backfill).
    """
    day_str   = day.isoformat()
    today_str = date.today().isoformat()
    now_str   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Extract validator fields from result object
    v_status  = validator_result.get("status")         if validator_result else None
    v_issues  = validator_result.get("issues", [])     if validator_result else None
    v_version = validator_result.get("schema_version") if validator_result else None

    for entry in data["days"]:
        if entry.get("date") == day_str:
            existing_rank = _QUALITY_RANK.get(entry.get("quality", "failed"), 0)
            new_rank      = _QUALITY_RANK.get(quality, 0)
            if new_rank < existing_rank:
                log.info(f"    ℹ {day}: quality downgrade blocked ({entry['quality']} → {quality})")
                return
            entry["quality"]      = quality
            entry["reason"]       = reason
            entry["write"]        = written
            entry["source"]       = source
            entry["last_checked"] = today_str
            if fields is not None:
                entry["fields"]   = fields
            if validator_result is not None:
                entry["validator_result"]         = v_status
                entry["validator_issues"]         = v_issues
                entry["validator_schema_version"] = v_version
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
    entry = {
        "date":         day_str,
        "quality":      quality,
        "reason":       reason,
        "write":        written,
        "source":       source,
        "recheck":      quality in ("failed", "low"),
        "attempts":     attempts,
        "last_checked": today_str,
        "last_attempt": now_str if quality in ("failed", "low") else None,
    }
    if fields is not None:
        entry["fields"] = fields
    if validator_result is not None:
        entry["validator_result"]         = v_status
        entry["validator_issues"]         = v_issues
        entry["validator_schema_version"] = v_version
    data["days"].append(entry)


# ══════════════════════════════════════════════════════════════════════════════
#  Public Transaction API
# ══════════════════════════════════════════════════════════════════════════════

def record_attempt(data: dict, day, label: str, reason: str,
                   written: bool = None, source: str = "api",
                   fields: dict = None,
                   validator_result: dict = None) -> None:
    """
    Public API — atomically upserts a quality entry and persists the log.
    Caller must already hold QUALITY_LOCK.
    Replaces the _upsert_quality + _save_quality_log call pattern.
    """
    from quality._io import _save_quality_log
    _upsert_quality(data, day, label, reason,
                    written=written, source=source,
                    fields=fields, validator_result=validator_result)
    _save_quality_log(data)


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
            from quality._io import _safe_get
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
#  Clean archive
# ══════════════════════════════════════════════════════════════════════════════

def cleanup_before_first_day(data: dict, dry_run: bool = False) -> dict:
    """
    Removes all raw/ and summary/ files before first_day, and removes
    corresponding entries from quality_log.json.

    dry_run=True: only counts and returns stats, does not delete anything.
    Returns {"files_deleted": int, "entries_removed": int, "first_day": str}.
    """
    from quality._io import _save_quality_log

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
