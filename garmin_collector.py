#!/usr/bin/env python3
"""
garmin_collector.py

Two-layer local archive of Garmin Connect data:
  raw/garmin_raw_YYYY-MM-DD.json   – full API dump (~500 KB/day)
  summary/garmin_YYYY-MM-DD.json  – compact daily summary (~2 KB) for Ollama / Open WebUI

On each run: compares local files against Garmin Connect and fills in any missing days.

Configuration via environment variables (all optional — hardcoded fallbacks below):
  GARMIN_EMAIL            Garmin Connect login email
  GARMIN_PASSWORD         Garmin Connect password
  GARMIN_OUTPUT_DIR       Root data folder (raw/ and summary/ live here)
  GARMIN_SYNC_MODE        "recent" | "range" | "auto"
  GARMIN_DAYS_BACK        Days to check in recent mode
  GARMIN_SYNC_START       Start date for range mode (YYYY-MM-DD)
  GARMIN_SYNC_END         End date for range mode (YYYY-MM-DD)
  GARMIN_SYNC_FALLBACK    Manual start date fallback for auto mode
  GARMIN_REQUEST_DELAY    Seconds between API calls
  GARMIN_INCOMPLETE_KB    Raw file size threshold in KB (default 100)
  GARMIN_SESSION_LOG_PREFIX    Prefix for session log filenames (default "garmin")
  GARMIN_SYNC_DATES            Comma-separated list of dates (YYYY-MM-DD) to fetch.
                               If set, overrides GARMIN_SYNC_MODE entirely.
"""

import json
import os
import sys
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — edit fallback values here, or set environment variables.
#  Environment variables always take priority over the values below.
# ══════════════════════════════════════════════════════════════════════════════

GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL",      "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD",   "yourpassword")
BASE_DIR        = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()
RAW_DIR         = BASE_DIR / "raw"
SUMMARY_DIR     = BASE_DIR / "summary"

# ── Sync mode ──────────────────────────────────────────────────────────────────
# "recent" → check last SYNC_DAYS days, fill any gaps (default, good for daily runs)
# "range"  → check SYNC_FROM to SYNC_TO only, fill any gaps
# "auto"   → check from oldest registered device to today, fill all gaps
SYNC_MODE = os.environ.get("GARMIN_SYNC_MODE", "recent")

# Used when SYNC_MODE = "recent"
SYNC_DAYS = int(os.environ.get("GARMIN_DAYS_BACK", "90"))

# Used when SYNC_MODE = "range"
SYNC_FROM = os.environ.get("GARMIN_SYNC_START", "2024-01-01")
SYNC_TO   = os.environ.get("GARMIN_SYNC_END",   "2024-12-31")

# Used when SYNC_MODE = "auto" and device detection fails — set manually e.g. "2018-01-01"
SYNC_AUTO_FALLBACK = os.environ.get("GARMIN_SYNC_FALLBACK") or None

# ── Advanced ───────────────────────────────────────────────────────────────────
# Delay between API requests in seconds — prevents rate limiting
REQUEST_DELAY = float(os.environ.get("GARMIN_REQUEST_DELAY", "1.5"))

# If "1": low/failed quality days are excluded from get_local_dates() → treated as missing → re-fetched
REFRESH_FAILED = os.environ.get("GARMIN_REFRESH_FAILED", "0") == "1"

# Max re-download attempts for 'low' quality days before giving up (recheck → false)
LOW_QUALITY_MAX_ATTEMPTS = int(os.environ.get("GARMIN_LOW_QUALITY_MAX_ATTEMPTS", "3"))

# Prefix for session log filenames — default "garmin", background timer sets "garmin_background"
SESSION_LOG_PREFIX = os.environ.get("GARMIN_SESSION_LOG_PREFIX", "garmin")

# Comma-separated list of specific dates to fetch (YYYY-MM-DD).
# If set, overrides GARMIN_SYNC_MODE — only these exact dates are fetched.
_sync_dates_raw = os.environ.get("GARMIN_SYNC_DATES", "").strip()
SYNC_DATES = None  # resolved after imports below

# ══════════════════════════════════════════════════════════════════════════════

_log_level = getattr(logging, os.environ.get("GARMIN_LOG_LEVEL", "INFO"), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Resolve SYNC_DATES now that date is imported
if _sync_dates_raw:
    _parsed = []
    for _d in _sync_dates_raw.split(","):
        try:
            _parsed.append(date.fromisoformat(_d.strip()))
        except ValueError:
            pass
    SYNC_DATES = sorted(_parsed) if _parsed else None


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _is_stopped() -> bool:
    """Returns True if the standalone GUI has requested a stop."""
    ev = globals().get("_STOP_EVENT")
    return ev is not None and ev.is_set()


def api_call(client, method: str, *args, label: str = ""):
    """Single API call with delay and error handling. Returns (data, success)."""
    if _is_stopped():
        return None, False
    try:
        data = getattr(client, method)(*args)
        time.sleep(REQUEST_DELAY)
        return data, True
    except Exception as e:
        log.warning(f"    ✗ {label or method}: {e}")
        time.sleep(REQUEST_DELAY)
        return None, False


# ── Raw data fetch ─────────────────────────────────────────────────────────────

def fetch_raw(client, date_str: str) -> dict:
    """Fetches all available Garmin API endpoints and returns raw data."""
    raw = {"date": date_str}

    endpoints = [
        ("get_sleep_data",           (date_str,), "sleep"),
        ("get_stress_data",          (date_str,), "stress"),
        ("get_body_battery",         (date_str,), "body_battery"),
        ("get_heart_rates",          (date_str,), "heart_rates"),
        ("get_respiration_data",     (date_str,), "respiration"),
        ("get_spo2_data",            (date_str,), "spo2"),
        ("get_stats",                (date_str,), "stats"),
        ("get_user_summary",         (date_str,), "user_summary"),
        ("get_activities_fordate",   (date_str,), "activities"),
        ("get_training_status",      (date_str,), "training_status"),
        ("get_training_readiness",   (date_str,), "training_readiness"),
        ("get_hrv_data",             (date_str,), "hrv"),
        ("get_race_predictions",     (),          "race_predictions"),
        ("get_max_metrics",          (date_str,), "max_metrics"),
    ]

    for method, args, key in endpoints:
        data, _ = api_call(client, method, *args, label=key)
        if data is not None:
            raw[key] = data

    return raw


# ── Summary extraction ─────────────────────────────────────────────────────────

def _parse_list_values(lst, dict_key: str) -> list:
    """Extracts numeric values from a list of dicts or [timestamp, value] pairs."""
    result = []
    for item in (lst or []):
        if isinstance(item, dict):
            v = item.get(dict_key)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            v = item[1]
        else:
            continue
        if isinstance(v, (int, float)):
            result.append(v)
    return result


def summarize(raw: dict) -> dict:
    """Distills raw data into a compact daily summary (~2 KB)."""
    s = {"date": raw.get("date"), "generated_by": "garmin_collector.py"}

    # ── Sleep & HRV ──
    sleep_raw = raw.get("sleep", {}) or {}
    ds        = safe_get(sleep_raw, "dailySleepDTO", default={})
    hrv_raw   = raw.get("hrv", {}) or {}
    hrv_sum   = safe_get(hrv_raw, "hrvSummary", default={}) or safe_get(sleep_raw, "hrvSummary", default={})
    s["sleep"] = {
        "duration_h":          round((safe_get(ds, "sleepTimeSeconds") or 0) / 3600, 2),
        "deep_h":              round((safe_get(ds, "deepSleepSeconds")  or 0) / 3600, 2),
        "rem_h":               round((safe_get(ds, "remSleepSeconds")   or 0) / 3600, 2),
        "light_h":             round((safe_get(ds, "lightSleepSeconds") or 0) / 3600, 2),
        "awake_h":             round((safe_get(ds, "awakeSleepSeconds") or 0) / 3600, 2),
        "score":               safe_get(ds, "sleepScores", "overall", "value"),
        "spo2_avg":            safe_get(ds, "averageSpO2Value"),
        "respiration_avg":     safe_get(ds, "averageRespirationValue"),
        "hrv_last_night_ms":   safe_get(hrv_sum, "lastNight") or safe_get(hrv_sum, "lastNight5MinHigh"),
        "hrv_weekly_avg_ms":   safe_get(hrv_sum, "weeklyAvg"),
        "hrv_status":          safe_get(hrv_sum, "status"),
        "hrv_feedback":        safe_get(hrv_sum, "feedbackPhrase"),
    }

    # ── Heart rate ──
    hr_raw  = raw.get("heart_rates", {}) or {}
    hr_vals = _parse_list_values(safe_get(hr_raw, "heartRateValues"), 1)
    s["heartrate"] = {
        "resting_bpm": safe_get(hr_raw, "restingHeartRate"),
        "max_bpm":     safe_get(hr_raw, "maxHeartRate"),
        "min_bpm":     safe_get(hr_raw, "minHeartRate"),
        "avg_bpm":     round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None,
    }

    # ── Stress & Body Battery ──
    # stress.stressValuesArray = [[ts, val], ...] with optional offset
    stress_src = raw.get("stress") or {}
    stress_arr = stress_src.get("stressValuesArray") or [] if isinstance(stress_src, dict) else []
    stress_offset = (stress_src.get("stressChartValueOffset") or 0) if isinstance(stress_src, dict) else 0
    stress_vals = []
    for item in stress_arr:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                v = float(item[1]) - stress_offset
                if v >= 0:
                    stress_vals.append(v)
            except (TypeError, ValueError):
                pass

    # stress.bodyBatteryValuesArray = [[ts, "MEASURED", level, version], ...]
    bb_arr = stress_src.get("bodyBatteryValuesArray") or [] if isinstance(stress_src, dict) else []
    bb_vals = []
    for item in bb_arr:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            try:
                bb_vals.append(float(item[2]))
            except (TypeError, ValueError):
                pass
    # Fallback: body_battery key
    if not bb_vals:
        bb_raw = raw.get("body_battery")
        if isinstance(bb_raw, dict):
            bb_list = safe_get(bb_raw, "bodyBatteryValuesArray", default=[])
        elif isinstance(bb_raw, list):
            bb_list = bb_raw
        else:
            bb_list = []
        bb_vals = _parse_list_values(bb_list, "value")

    s["stress"] = {
        "stress_avg":       round(sum(stress_vals) / len(stress_vals), 1) if stress_vals else None,
        "stress_max":       max(stress_vals, default=None),
        "body_battery_max": max(bb_vals, default=None),
        "body_battery_min": min(bb_vals, default=None),
        "body_battery_end": bb_vals[-1] if bb_vals else None,
    }

    # ── Daily stats ──
    us = raw.get("user_summary", {}) or {}
    st = raw.get("stats", {}) or {}
    s["day"] = {
        "steps":                  safe_get(us, "totalSteps") or safe_get(st, "totalSteps"),
        "steps_goal":             safe_get(us, "dailyStepGoal"),
        "calories_active":        safe_get(us, "activeKilocalories"),
        "calories_total":         safe_get(us, "totalKilocalories"),
        "intensity_min_moderate": safe_get(us, "moderateIntensityMinutes"),
        "intensity_min_vigorous": safe_get(us, "vigorousIntensityMinutes"),
        "floors_climbed":         safe_get(us, "floorsAscended"),
        "distance_km":            round((safe_get(us, "totalDistanceMeters") or 0) / 1000, 2) or None,
    }

    # ── Training ──
    tr = raw.get("training_readiness", {}) or {}
    ts = raw.get("training_status", {}) or {}
    mm = raw.get("max_metrics", {}) or {}
    s["training"] = {
        "readiness_score":    safe_get(tr, "score") or safe_get(tr, "trainingReadinessScore"),
        "readiness_level":    safe_get(tr, "level") or safe_get(tr, "trainingReadinessLevel"),
        "readiness_feedback": safe_get(tr, "feedbackLong"),
        "training_status":    safe_get(ts, "latestTrainingStatus") or safe_get(ts, "trainingStatus"),
        "training_load_7d":   safe_get(ts, "trainingLoadBalance", "sevenDayTrainingLoad"),
        "vo2max":             safe_get(mm, "vo2MaxPreciseValue") or safe_get(mm, "generic", "vo2MaxPreciseValue"),
    }

    # ── Activities (compact) ──
    activities = raw.get("activities") or []
    s["activities"] = [
        {
            "name":                      a.get("activityName"),
            "type":                      a.get("activityType", {}).get("typeKey") if isinstance(a.get("activityType"), dict) else a.get("activityType"),
            "duration_min":              round(a.get("duration", 0) / 60, 1) if a.get("duration") else None,
            "distance_km":               round(a.get("distance", 0) / 1000, 2) if a.get("distance") else None,
            "avg_hr":                    a.get("averageHR"),
            "max_hr":                    a.get("maxHR"),
            "calories":                  a.get("calories"),
            "training_effect_aerobic":   a.get("aerobicTrainingEffect"),
            "training_effect_anaerobic": a.get("anaerobicTrainingEffect"),
        }
        for a in (activities if isinstance(activities, list) else [])
    ]

    return s


# ── Sync logic ─────────────────────────────────────────────────────────────────

def get_devices(client) -> list:
    """Fetches all registered devices, logs them, returns sorted list."""
    devices = []
    try:
        raw = client.get_devices()
        if not isinstance(raw, list):
            raw = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            name       = d.get("productDisplayName") or d.get("deviceTypeName") or "Unknown"
            device_id  = d.get("deviceId") or d.get("unitId")
            last_used  = (d.get("lastUsed") or "")[:10] or "unknown"
            first_used = None
            for field in ("registeredDate", "activationDate", "firstSyncTime"):
                val = d.get(field) or ""
                if val:
                    first_used = str(val)[:10]
                    break
            devices.append({
                "name":       name,
                "id":         device_id,
                "first_used": first_used,
                "last_used":  last_used,
            })
        devices.sort(key=lambda x: x["first_used"] or "9999")
        log.info(f"  Registered devices ({len(devices)}):")
        for dv in devices:
            log.info(f"    {dv['name']:30s}  first: {dv['first_used'] or '?':10s}  last: {dv['last_used']}")
    except Exception as e:
        log.warning(f"  Could not fetch device list: {e}")
    return devices


def resolve_date_range(client) -> tuple[date, date]:
    """
    Returns (start, end) based on SYNC_MODE.

    "recent" → (today - SYNC_DAYS, yesterday)
    "range"  → (SYNC_FROM, SYNC_TO)
    "auto"   → (oldest device / profile / fallback, yesterday)
    """
    today     = date.today()
    yesterday = today - timedelta(days=1)

    if SYNC_MODE == "recent":
        start = today - timedelta(days=SYNC_DAYS)
        log.info(f"  Mode: recent — last {SYNC_DAYS} days ({start} → {yesterday})")
        return start, yesterday

    if SYNC_MODE == "range":
        start = date.fromisoformat(SYNC_FROM)
        end   = date.fromisoformat(SYNC_TO)
        log.info(f"  Mode: range — {start} → {end}")
        return start, end

    if SYNC_MODE == "auto":
        log.info("  Mode: auto — detecting earliest available date ...")

        # Try devices first
        devices     = get_devices(client)
        first_dates = [
            d["first_used"] for d in devices
            if d["first_used"] and d["first_used"] != "unknown"
        ]
        if first_dates:
            earliest = min(first_dates)
            log.info(f"  Earliest device date: {earliest}")
            return date.fromisoformat(earliest), yesterday

        # Try account profile
        try:
            profile = client.get_user_profile()
            reg = safe_get(profile, "userInfo", "registrationDate")
            if reg:
                log.info(f"  Start date from account profile: {reg[:10]}")
                return date.fromisoformat(reg[:10]), yesterday
        except Exception:
            pass

        # Manual fallback
        if SYNC_AUTO_FALLBACK:
            log.info(f"  Using SYNC_AUTO_FALLBACK: {SYNC_AUTO_FALLBACK}")
            return date.fromisoformat(SYNC_AUTO_FALLBACK), yesterday

        log.warning("  Could not determine start date — falling back to 90 days.")
        return today - timedelta(days=90), yesterday

    log.error(f"  Unknown SYNC_MODE: '{SYNC_MODE}' — use 'recent', 'range', or 'auto'.")
    sys.exit(1)


def get_local_dates(folder: Path) -> set:
    """
    Returns dates for which local data already exists.
    Checks all locations and naming schemes:
      1. raw/garmin_raw_YYYY-MM-DD.json   (current schema)
      2. summary/garmin_YYYY-MM-DD.json   (current schema, fallback)
      3. BASE_DIR/garmin_YYYY-MM-DD.json  (legacy schema)
    """
    dates = set()
    checks = [
        (folder,                    "garmin_raw_*.json", "garmin_raw_"),
        (folder.parent / "summary", "garmin_*.json",     "garmin_"),
        (folder.parent,             "garmin_*.json",     "garmin_"),
    ]
    for directory, pattern, prefix in checks:
        if not directory.exists():
            continue
        for f in directory.glob(pattern):
            try:
                dates.add(date.fromisoformat(f.stem.replace(prefix, "")))
            except ValueError:
                pass
    if REFRESH_FAILED:
        # Remove days with recheck=True so they appear as missing and get re-fetched
        recheck_file = LOG_DIR / "quality_log.json"
        if recheck_file.exists():
            try:
                import json as _json
                qdata = _json.loads(recheck_file.read_text(encoding="utf-8"))
                recheck_dates = {
                    date.fromisoformat(e["date"])
                    for e in qdata.get("days", [])
                    if e.get("recheck", False)
                }
                before = len(dates)
                dates -= recheck_dates
                removed = before - len(dates)
                if removed:
                    log.info(f"  Refresh mode: excluding {removed} recheck days for re-fetch")
            except Exception:
                pass

    if dates:
        log.info(f"  Local days found: {len(dates)} (earliest: {min(dates)}, latest: {max(dates)})")
    return dates


def assess_quality(raw: dict) -> str:
    """
    Assesses the quality of a raw data dict based on content.

    Returns one of:
      "high"   — intraday data present (HR values, stress values, etc.)
      "med"    — daily aggregates present but no intraday (typical for older Garmin data)
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
        safe_get(stats, "totalSteps") is not None or
        safe_get(user_summary, "totalSteps") is not None
    )
    has_hr_resting = (
        safe_get(stats, "restingHeartRate") is not None or
        safe_get(user_summary, "restingHeartRate") is not None
    )

    if has_steps or has_hr_resting:
        # Has daily aggregates — check if meaningful
        sleep = raw.get("sleep") or {}
        has_sleep = safe_get(sleep, "dailySleepDTO", "sleepTimeSeconds") is not None

        if has_sleep or has_steps:
            return "med"
        return "low"

    # Check bare minimum — any stats at all
    if isinstance(stats, dict) and stats:
        return "low"
    if isinstance(user_summary, dict) and user_summary:
        return "low"

    return "failed"


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


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# ── Quality log helpers ───────────────────────────────────────────────────────

LOG_DIR          = BASE_DIR / "log"
QUALITY_LOG_FILE = LOG_DIR / "quality_log.json"
FAILED_DAYS_FILE = QUALITY_LOG_FILE  # backwards-compat alias


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
    old_file = LOG_DIR / "failed_days.json"

    # Try quality_log.json first, fall back to failed_days.json migration
    source = None
    if QUALITY_LOG_FILE.exists():
        source = QUALITY_LOG_FILE
    elif old_file.exists():
        source = old_file
        log.info("  Migrating failed_days.json → quality_log.json ...")

    if source is None:
        return {"days": []}

    try:
        with open(source, encoding="utf-8") as f:
            data = json.load(f)

        # Migrate old 'failed' key → 'days'
        if "failed" in data and "days" not in data:
            data["days"] = data.pop("failed")

        if "days" not in data or not isinstance(data["days"], list):
            return {"days": []}

        today_str = date.today().isoformat()
        for entry in data["days"]:
            # Migrate 'category' → 'quality'
            if "category" in entry and "quality" not in entry:
                old = entry.pop("category")
                entry["quality"] = "failed" if old == "error" else "low"

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
        return {"days": []}


# Keep old name as alias for compatibility with any external callers
_load_failed_days = _load_quality_log


def _save_quality_log(data: dict) -> None:
    """Writes quality_log.json atomically via temp file."""
    tmp = QUALITY_LOG_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(QUALITY_LOG_FILE)
    except Exception as e:
        log.warning(f"  Could not write quality_log.json: {e}")


# Keep old name as alias
_save_failed_days = _save_quality_log


def _upsert_quality(data: dict, day: date, quality: str, reason: str) -> None:
    """
    Adds or updates a day entry in the quality log.
    - 'failed': increments attempts, sets recheck=True
    - 'low': increments attempts, sets recheck=False if attempts >= LOW_QUALITY_MAX_ATTEMPTS
    - 'med'/'high': sets recheck=False (data is good)
    """
    day_str   = day.isoformat()
    today_str = date.today().isoformat()
    now_str   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for entry in data["days"]:
        if entry.get("date") == day_str:
            entry["quality"]       = quality
            entry["reason"]        = reason
            entry["last_checked"]  = today_str
            if quality == "failed":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = True
            elif quality == "low":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = entry["attempts"] < LOW_QUALITY_MAX_ATTEMPTS
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
        "recheck":      quality in ("failed", "low"),
        "attempts":     attempts,
        "last_checked": today_str,
        "last_attempt": now_str if quality in ("failed", "low") else None,
    })


# Keep old name as alias
_upsert_failed = _upsert_quality


def _mark_quality_ok(data: dict, day: date, quality: str) -> None:
    """
    Marks a day as good quality (high/med) — sets recheck=False.
    Updates existing entry or adds new one. Does NOT remove — keeps full history.
    """
    _upsert_quality(data, day, quality, f"Quality: {quality}")


# Keep old name as alias (will update quality to high/med instead of removing)
def _remove_failed(data: dict, day: date) -> None:
    """Legacy alias — marks day as high quality instead of removing."""
    _mark_quality_ok(data, day, "high")


# ── Session logging ────────────────────────────────────────────────────────────

LOG_RECENT_DIR = LOG_DIR / "recent"
LOG_FAIL_DIR   = LOG_DIR / "fail"
LOG_RECENT_MAX = 30


def _start_session_log() -> tuple:
    """
    Creates a new session log file in log/recent/ at DEBUG level.
    Returns (file_handler, log_path) so main() can close and evaluate it.
    """
    LOG_RECENT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FAIL_DIR.mkdir(parents=True, exist_ok=True)

    ts       = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = LOG_RECENT_DIR / f"{SESSION_LOG_PREFIX}_{ts}.log"

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)
    return fh, log_path


def _close_session_log(fh: logging.FileHandler, log_path: Path,
                        had_errors: bool, had_incomplete: bool) -> None:
    """
    Closes the session log file handler.
    Copies to log/fail/ if the session had errors or incomplete days.
    Enforces LOG_RECENT_MAX rolling limit on log/recent/.
    """
    logging.getLogger().removeHandler(fh)
    fh.close()

    # Copy to fail/ if session had issues
    if had_errors or had_incomplete:
        import shutil
        try:
            shutil.copy2(log_path, LOG_FAIL_DIR / log_path.name)
        except Exception as e:
            log.warning(f"  Could not copy to log/fail/: {e}")

    # Rolling: remove oldest logs in recent/ beyond limit
    try:
        logs = sorted(LOG_RECENT_DIR.glob("garmin_*.log"), key=lambda f: f.stat().st_mtime)
        for old in logs[:-LOG_RECENT_MAX]:
            old.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"  Could not rotate session logs: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    try:
        from garminconnect import Garmin
    except ImportError:
        log.error("garminconnect not installed: pip install garminconnect")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── Session log ───────────────────────────────────────────────────────────
    _session_fh, _session_path = _start_session_log()
    _session_had_errors     = False
    _session_had_incomplete = False

    # ── Load + update quality_log.json ───────────────────────────────────────
    quality_data = _load_quality_log()

    # Collect already-known dates to skip in scan (avoids OneDrive downloads)
    known_dates = {
        date.fromisoformat(e["date"])
        for e in quality_data.get("days", [])
        if "date" in e
    }

    # Scan raw/ for new files not yet in quality log
    new_low = get_low_quality_dates(RAW_DIR, known_dates=known_dates)
    for day, q in new_low.items():
        _upsert_quality(quality_data, day, q, f"Quality: {q} — insufficient data from Garmin API")

    _save_quality_log(quality_data)
    recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
    log.info(f"  Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")

    # ── Login ─────────────────────────────────────────────────────────────────
    log.info("Connecting to Garmin Connect ...")
    try:
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()
        log.info("  ✓ Login successful")
    except Exception as e:
        log.error(f"Login failed: {e}")
        sys.exit(1)

    # ── Resolve date list ─────────────────────────────────────────────────────
    if SYNC_DATES:
        # Background timer mode: fetch exactly these dates, ignore SYNC_MODE
        local   = get_local_dates(RAW_DIR)
        missing = sorted(d for d in SYNC_DATES if d not in local or REFRESH_FAILED)
        log.info(f"  SYNC_DATES mode: {len(SYNC_DATES)} requested, {len(missing)} to fetch")
    else:
        start, end = resolve_date_range(client)
        local      = get_local_dates(RAW_DIR)
        missing    = sorted(set(date_range(start, end)) - local)

    if not missing:
        log.info("All days already present — nothing to do.")
        return

    log.info(f"Local: {len(local)} days  |  Missing: {len(missing)} days")
    if SYNC_DATES:
        log.info(f"Fetching {len(missing)} specific days ...")
    else:
        log.info(f"Fetching {missing[0]} to {missing[-1]} ...")

    ok, failed = 0, 0
    for i, day in enumerate(missing, 1):
        if _is_stopped():
            log.info(f"  Stopped after {ok} days saved.")
            break
        log.info(f"  [{i}/{len(missing)}] {day}")
        date_str = day.isoformat()
        try:
            raw     = fetch_raw(client, date_str)
            summary = summarize(raw)

            raw_path = RAW_DIR / f"garmin_raw_{date_str}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(raw,     f, ensure_ascii=False, indent=2)
            with open(SUMMARY_DIR / f"garmin_{date_str}.json",     "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)

            # Assess quality and update log
            q = assess_quality(raw)
            _upsert_quality(quality_data, day, q,
                            f"Quality: {q}" if q in ("high", "med") else
                            f"Quality: {q} — insufficient data from Garmin API")
            if q in ("low", "failed"):
                _session_had_incomplete = True
                log.warning(f"    ⚠ Low data quality ({q}) — flagged for recheck")
            else:
                log.info(f"    ✓ Quality: {q}")
            ok += 1
        except Exception as e:
            log.error(f"    Error on {day}: {e}")
            _upsert_quality(quality_data, day, "failed", str(e))
            failed += 1
            _session_had_errors = True

    _save_quality_log(quality_data)
    log.info(f"Done. {ok} saved, {failed} errors.")
    recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
    log.info(f"Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")
    log.info(f"Raw data:    {RAW_DIR}")
    log.info(f"Summaries:   {SUMMARY_DIR}  ← point Open WebUI Knowledge Base here")

    _close_session_log(_session_fh, _session_path,
                       _session_had_errors, _session_had_incomplete)


if __name__ == "__main__":
    main()
