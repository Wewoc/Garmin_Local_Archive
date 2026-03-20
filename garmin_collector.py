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
"""

import json
import os
import sys
import logging
import time
from datetime import date, timedelta
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

# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def api_call(client, method: str, *args, label: str = ""):
    """Single API call with delay and error handling. Returns (data, success)."""
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
    if dates:
        log.info(f"  Local days found: {len(dates)} (earliest: {min(dates)}, latest: {max(dates)})")
    return dates


def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    try:
        from garminconnect import Garmin
    except ImportError:
        log.error("garminconnect not installed: pip install garminconnect")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Connecting to Garmin Connect ...")
    try:
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()
        log.info("  ✓ Login successful")
    except Exception as e:
        log.error(f"Login failed: {e}")
        sys.exit(1)

    start, end = resolve_date_range(client)
    local      = get_local_dates(RAW_DIR)
    missing    = sorted(set(date_range(start, end)) - local)

    if not missing:
        log.info("All days already present — nothing to do.")
        return

    log.info(f"Local: {len(local)} days  |  Missing: {len(missing)} days")
    log.info(f"Fetching {missing[0]} to {missing[-1]} ...")

    ok, failed = 0, 0
    for i, day in enumerate(missing, 1):
        log.info(f"  [{i}/{len(missing)}] {day}")
        date_str = day.isoformat()
        try:
            raw     = fetch_raw(client, date_str)
            summary = summarize(raw)

            with open(RAW_DIR     / f"garmin_raw_{date_str}.json", "w", encoding="utf-8") as f:
                json.dump(raw,     f, ensure_ascii=False, indent=2)
            with open(SUMMARY_DIR / f"garmin_{date_str}.json",     "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            ok += 1
        except Exception as e:
            log.error(f"    Error on {day}: {e}")
            failed += 1

    log.info(f"Done. {ok} saved, {failed} errors.")
    log.info(f"Raw data:    {RAW_DIR}")
    log.info(f"Summaries:   {SUMMARY_DIR}  ← point Open WebUI Knowledge Base here")


if __name__ == "__main__":
    main()
