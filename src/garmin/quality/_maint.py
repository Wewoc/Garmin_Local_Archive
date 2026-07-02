#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin/quality/_maint.py

Maintenance sub-module for garmin_quality.
Upsert, first_day detection, archive cleanup.

Internal — import only via garmin_quality (facade).
"""

import logging
from datetime import date, datetime

import garmin_config as cfg

from garmin_utils import extract_date_from_filename

log = logging.getLogger(__name__)

# Quality rank — defined here, re-exported via facade (without leading underscore)
# Used for downgrade protection in _upsert_quality and in garmin_collector.
QUALITY_RANK = {"high": 2, "standard": 1, "failed": 0}


# ══════════════════════════════════════════════════════════════════════════════
#  Upsert
# ══════════════════════════════════════════════════════════════════════════════

def _upsert_quality(data: dict, day: date, quality: str, reason: str,
                    written: bool = None, source: str = "legacy",
                    fields: dict = None,
                    validator_result: dict = None,
                    device_id: str | None = None,
                    device_name: str | None = None,
                    prev_high: bool = False,
                    backfilled_fields: dict = None) -> None:
    """
    Adds or updates a day entry in the quality log.
      - 'failed':   increments attempts, sets recheck=True
      - 'standard': sets recheck based on prev_high + age window (v1.5.7)
      - 'high':     sets recheck=False (intraday present — no retry needed)

    written : bool | None
      True  — writer wrote both files successfully
      False — label was 'failed', writer failed, or write was skipped
      None  — unknown (backfill, scan, or pre-v1.2.1 entry)

    source : str
      Origin of the data: "api" | "bulk" | "csv" | "manual" | "legacy"
      Always overwrites the existing value — the most recent write wins.

    device_id : str | None
      Numeric device ID string from training_status → latestTrainingStatusData.
      None = training_status absent or no devices found.

    device_name : str | None
      Human-readable device name — stored alongside device_id.

    prev_high : bool
      True if the previous calendar day has quality == "high".
      Used to determine whether a 'standard' day warrants a recheck.
      Lookup is done by the caller (garmin_collector) — not here.

    validator_result : dict | None
      Complete result object from garmin_validator.validate().
      Three fields are extracted and stored per day entry:
        validator_result       — "ok" | "warning" | "critical"
        validator_issues       — list of structured issue dicts (empty if ok)
        validator_schema_version — schema version used for validation
      None = validator was not run (legacy entries, backfill).

    backfilled_fields : dict | None
      Marks which optional fields were added to an already-archived day via
      a dedicated backfill pass (e.g. {"steps": "<ISO date>"}). Merged
      additively into any existing backfilled_fields on the entry — never
      overwrites a prior marker. None = no field was backfilled this call
      (the normal case for every regular sync day).
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
            existing_rank = QUALITY_RANK.get(entry.get("quality", "failed"), 0)
            new_rank      = QUALITY_RANK.get(quality, 0)
            if new_rank < existing_rank:
                log.info(f"    ℹ {day}: quality downgrade blocked ({entry['quality']} → {quality})")
                return
            entry["quality"]      = quality
            entry["reason"]       = reason
            entry["write"]        = written
            entry["source"]       = source
            entry["last_checked"] = today_str
            if device_id is not None:
                entry["device_id"]   = device_id
                entry["device_name"] = device_name or ""
            if fields is not None:
                entry["fields"]   = fields
            if backfilled_fields is not None:
                entry["backfilled_fields"] = {**entry.get("backfilled_fields", {}), **backfilled_fields}
            if validator_result is not None:
                entry["validator_result"]         = v_status
                entry["validator_issues"]         = v_issues
                entry["validator_schema_version"] = v_version
            if quality == "failed":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = True
            elif quality == "standard":
                day_age = (date.today() - day).days
                entry["recheck"]      = (day_age < cfg.INTRADAY_RETRY_WINDOW_DAYS and prev_high)
                entry["last_attempt"] = now_str
            else:  # "high"
                entry["recheck"]      = False
                entry["last_attempt"] = now_str
            return

    # New entry
    attempts = 1 if quality == "failed" else 0
    if quality == "failed":
        recheck_new = True
    elif quality == "standard":
        day_age = (date.today() - day).days
        recheck_new = (day_age < cfg.INTRADAY_RETRY_WINDOW_DAYS and prev_high)
    else:  # "high"
        recheck_new = False
    entry = {
        "date":         day_str,
        "quality":      quality,
        "reason":       reason,
        "write":        written,
        "source":       source,
        "recheck":      recheck_new,
        "attempts":     attempts,
        "last_checked": today_str,
        "last_attempt": now_str if quality == "failed" else None,
        "device_id":    device_id,
        "device_name":  device_name or "",
    }
    if fields is not None:
        entry["fields"] = fields
    if backfilled_fields is not None:
        entry["backfilled_fields"] = backfilled_fields
    if validator_result is not None:
        entry["validator_result"]         = v_status
        entry["validator_issues"]         = v_issues
        entry["validator_schema_version"] = v_version
    data["days"].append(entry)


# ══════════════════════════════════════════════════════════════════════════════
#  Public Transaction API
# ══════════════════════════════════════════════════════════════════════════════

def set_unknown_device_name(data: dict, name: str) -> int:
    """
    Sets device_name on all entries where device_id is None.
    Returns the number of entries updated.
    Caller is responsible for saving quality_log.json and device_table.json.
    """
    name = name.strip()
    count = 0
    for entry in data.get("days", []):
        if entry.get("device_id") is None:
            entry["device_name"] = name
            count += 1
    log.info(f"  set_unknown_device_name: {count} entries updated → '{name}'")
    return count


def record_attempt(data: dict, day, label: str, reason: str,
                   written: bool = None, source: str = "api",
                   fields: dict = None,
                   validator_result: dict = None,
                   device_id: str | None = None,
                   device_name: str | None = None,
                   prev_high: bool = False,
                   backfilled_fields: dict = None) -> None:
    """
    Public API — atomically upserts a quality entry and persists the log.
    Caller must already hold QUALITY_LOCK.
    Replaces the _upsert_quality + _save_quality_log call pattern.

    device_id         : numeric device ID string from training_status, or None.
    device_name       : human-readable device name, or None.
    prev_high         : True if the previous calendar day has quality == "high".
                        Used for 'standard' recheck logic — lookup done by caller.
    backfilled_fields : marks fields added via a backfill pass, e.g.
                        {"steps": "<ISO date>"}. None = no backfill this call.
    """
    from quality._io import _save_quality_log
    _upsert_quality(data, day, label, reason,
                    written=written, source=source,
                    fields=fields, validator_result=validator_result,
                    device_id=device_id, device_name=device_name,
                    prev_high=prev_high, backfilled_fields=backfilled_fields)
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
        d = extract_date_from_filename(f)
        if d is None:
            continue
        if d < cutoff:
            if not dry_run:
                f.unlink(missing_ok=True)
            files_deleted += 1

    # Delete summary files before cutoff
    for f in cfg.SUMMARY_DIR.glob("garmin_*.json"):
        d = extract_date_from_filename(f, prefix="garmin_")
        if d is None:
            continue
        if d < cutoff:
            if not dry_run:
                f.unlink(missing_ok=True)
            files_deleted += 1

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
