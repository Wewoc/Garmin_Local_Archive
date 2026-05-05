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
import threading
from datetime import date, datetime
from pathlib import Path

import garmin_config as cfg
import garmin_utils as utils

log = logging.getLogger(__name__)

# Lock for quality_log.json access — acquire in any context where
# load → modify → save must not be interrupted by another thread.
QUALITY_LOCK = threading.Lock()


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

            # Migrate: add 'source' field if missing (entries before v1.2.2)
            if "source" not in entry:
                entry["source"] = "legacy"

            # Migrate: add 'fields' dict if missing (entries before v1.3.0)
            if "fields" not in entry:
                entry["fields"] = {}

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


def assess_quality_fields(raw: dict) -> dict:
    """
    Assesses quality per endpoint from a raw data dict.

    Returns a dict with one quality label per known endpoint:
      "high"   — intraday data present
      "medium" — daily aggregate present, no intraday
      "low"    — minimal data present
      "failed" — endpoint missing or empty

    Pure function — no file IO. Called after assess_quality() in the pipeline.
    """
    fields = {}

    # ── heart_rates ──
    hr = raw.get("heart_rates") or {}
    hr_values = hr.get("heartRateValues") if isinstance(hr, dict) else None
    if isinstance(hr_values, list) and len(hr_values) > 0:
        fields["heart_rates"] = "high"
    elif isinstance(hr, dict) and hr.get("restingHeartRate") is not None:
        fields["heart_rates"] = "medium"
    elif isinstance(hr, dict) and hr:
        fields["heart_rates"] = "low"
    else:
        fields["heart_rates"] = "failed"

    # ── stress ──
    stress = raw.get("stress") or {}
    stress_values = stress.get("stressValuesArray") if isinstance(stress, dict) else None
    if isinstance(stress_values, list) and len(stress_values) > 0:
        fields["stress"] = "high"
    elif isinstance(stress, dict) and stress.get("averageStressLevel") is not None:
        fields["stress"] = "medium"
    elif isinstance(stress, dict) and stress:
        fields["stress"] = "low"
    else:
        fields["stress"] = "failed"

    # ── sleep ──
    sleep = raw.get("sleep") or {}
    has_sleep_intraday = (
        isinstance(sleep, dict) and
        isinstance(sleep.get("sleepLevels"), list) and
        len(sleep["sleepLevels"]) > 0
    )
    has_sleep_aggregate = _safe_get(sleep, "dailySleepDTO", "sleepTimeSeconds") is not None
    if has_sleep_intraday:
        fields["sleep"] = "high"
    elif has_sleep_aggregate:
        fields["sleep"] = "medium"
    elif isinstance(sleep, dict) and sleep:
        fields["sleep"] = "low"
    else:
        fields["sleep"] = "failed"

    # ── hrv ──
    hrv = raw.get("hrv") or {}
    hrv_sum = _safe_get(hrv, "hrvSummary") if isinstance(hrv, dict) else None
    if isinstance(hrv_sum, dict) and hrv_sum.get("lastNight") is not None:
        fields["hrv"] = "medium"
    elif isinstance(hrv, dict) and hrv:
        fields["hrv"] = "low"
    else:
        fields["hrv"] = "failed"

    # ── spo2 ──
    spo2 = raw.get("spo2") or {}
    spo2_readings = spo2.get("spO2HourlyAverages") if isinstance(spo2, dict) else None
    if isinstance(spo2_readings, list) and len(spo2_readings) > 0:
        fields["spo2"] = "high"
    elif isinstance(spo2, dict) and spo2.get("averageSpO2") is not None:
        fields["spo2"] = "medium"
    elif isinstance(spo2, dict) and spo2:
        fields["spo2"] = "low"
    else:
        fields["spo2"] = "failed"

    # ── stats ──
    stats = raw.get("stats") or {}
    user_summary = raw.get("user_summary") or {}
    has_steps = (
        _safe_get(stats, "totalSteps") is not None or
        _safe_get(user_summary, "totalSteps") is not None
    )
    if has_steps:
        fields["stats"] = "medium"
    elif (isinstance(stats, dict) and stats) or (isinstance(user_summary, dict) and user_summary):
        fields["stats"] = "low"
    else:
        fields["stats"] = "failed"

    # ── body_battery ──
    bb = raw.get("body_battery") or {}
    bb_values = bb.get("bodyBatteryValuesArray") if isinstance(bb, dict) else None
    stress_bb = (raw.get("stress") or {}).get("bodyBatteryValuesArray") if isinstance(raw.get("stress"), dict) else None
    has_bb = (isinstance(bb_values, list) and len(bb_values) > 0) or \
             (isinstance(stress_bb, list) and len(stress_bb) > 0)
    if has_bb:
        fields["body_battery"] = "high"
    elif isinstance(bb, dict) and bb:
        fields["body_battery"] = "low"
    else:
        fields["body_battery"] = "failed"

    # ── respiration ──
    resp = raw.get("respiration") or {}
    resp_values = resp.get("respirationValues") if isinstance(resp, dict) else None
    if isinstance(resp_values, list) and len(resp_values) > 0:
        fields["respiration"] = "high"
    elif isinstance(resp, dict) and resp.get("avgWakingRespirationValue") is not None:
        fields["respiration"] = "medium"
    elif isinstance(resp, dict) and resp:
        fields["respiration"] = "low"
    else:
        fields["respiration"] = "failed"

    # ── activities ──
    acts = raw.get("activities")
    if isinstance(acts, list) and len(acts) > 0:
        fields["activities"] = "high"
    else:
        fields["activities"] = "failed"

    # ── training_status ──
    ts = raw.get("training_status") or {}
    if isinstance(ts, dict) and (ts.get("latestTrainingStatus") or ts.get("trainingStatus")):
        fields["training_status"] = "medium"
    elif isinstance(ts, dict) and ts:
        fields["training_status"] = "low"
    else:
        fields["training_status"] = "failed"

    # ── training_readiness ──
    tr = raw.get("training_readiness") or {}
    if isinstance(tr, dict) and (tr.get("score") is not None or tr.get("trainingReadinessScore") is not None):
        fields["training_readiness"] = "medium"
    elif isinstance(tr, dict) and tr.get("level") is not None:
        fields["training_readiness"] = "low"
    elif isinstance(tr, dict) and tr:
        fields["training_readiness"] = "low"
    else:
        fields["training_readiness"] = "failed"

    # ── race_predictions ──
    rp = raw.get("race_predictions") or {}
    if isinstance(rp, dict) and rp:
        fields["race_predictions"] = "medium"
    else:
        fields["race_predictions"] = "failed"

    # ── max_metrics ──
    mm = raw.get("max_metrics") or {}
    if isinstance(mm, dict) and (
        mm.get("vo2MaxPreciseValue") is not None or
        _safe_get(mm, "generic", "vo2MaxPreciseValue") is not None
    ):
        fields["max_metrics"] = "medium"
    elif isinstance(mm, dict) and mm:
        fields["max_metrics"] = "low"
    else:
        fields["max_metrics"] = "failed"

    return fields


# ══════════════════════════════════════════════════════════════════════════════
#  Upsert
# ══════════════════════════════════════════════════════════════════════════════

_QUALITY_RANK = {"high": 4, "medium": 3, "low": 2, "failed": 1}

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
                            written=True, source="legacy")
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

# _parse_device_date moved to garmin_utils.py
_parse_device_date = utils.parse_device_date


def _safe_get(d, *keys, default=None):
    """Traverses nested dicts safely. Returns default if any key is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


# ══════════════════════════════════════════════════════════════════════════════
#  Archive stats (read-only, for GUI info panel)
# ══════════════════════════════════════════════════════════════════════════════

def get_archive_stats(quality_log_path=None) -> dict:
    """
    Returns a summary of the local archive state for display in the GUI.
    Reads quality_log.json — no API call, no side effects.

    quality_log_path: optional Path override — if None, uses cfg.QUALITY_LOG_FILE.

    Returns dict with keys:
      total        int   — total days tracked
      high         int   — days with quality 'high'
      medium       int   — days with quality 'medium'
      low          int   — days with quality 'low'
      failed       int   — days with quality 'failed'
      recheck      int   — days with recheck=True
      missing      int   — days absent in range (possible - present) or None
      date_min     str   — earliest date tracked (YYYY-MM-DD) or None
      date_max     str   — latest date tracked (YYYY-MM-DD) or None
      coverage_pct int   — days present vs. possible days in range (0–100) or None
      last_api     str   — latest date with source='api' (YYYY-MM-DD) or None
      last_bulk    str   — latest date with source='bulk' (YYYY-MM-DD) or None
    """
    try:
        if quality_log_path is not None:
            p = Path(quality_log_path)
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    import json as _json
                    data = _json.load(f)
                if "days" not in data:
                    data = {"days": []}
            else:
                data = {"days": []}
        else:
            data = _load_quality_log()
    except Exception:
        data = {"days": []}

    days = data.get("days", [])

    counts = {"high": 0, "medium": 0, "low": 0, "failed": 0}
    recheck = 0
    dates = []
    api_dates = []
    bulk_dates = []

    for entry in days:
        q = entry.get("quality", "failed")
        if q in counts:
            counts[q] += 1
        if entry.get("recheck"):
            recheck += 1
        d = entry.get("date")
        if d:
            dates.append(d)
            src = entry.get("source", "")
            if src == "api":
                api_dates.append(d)
            elif src == "bulk":
                bulk_dates.append(d)

    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    coverage_pct = None
    missing      = None
    if date_min and date_max:
        try:
            from datetime import date as _date
            d0 = _date.fromisoformat(date_min)
            d1 = _date.fromisoformat(date_max)
            possible = (d1 - d0).days + 1
            present  = len(dates)
            coverage_pct = round(present / possible * 100) if possible > 0 else 100
            missing      = possible - present
        except Exception:
            pass

    return {
        "total":        len(days),
        "high":         counts["high"],
        "medium":       counts["medium"],
        "low":          counts["low"],
        "failed":       counts["failed"],
        "recheck":      recheck,
        "missing":      missing,
        "date_min":     date_min,
        "date_max":     date_max,
        "coverage_pct": coverage_pct,
        "last_api":     max(api_dates)  if api_dates  else None,
        "last_bulk":    max(bulk_dates) if bulk_dates else None,
    }