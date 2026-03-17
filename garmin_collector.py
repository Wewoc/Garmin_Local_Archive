#!/usr/bin/env python3
"""
garmin_collector.py

Two-layer local archive of Garmin Connect data:
  raw/garmin_raw_YYYY-MM-DD.json   – full API dump (~500 KB/day)
  summary/garmin_YYYY-MM-DD.json  – compact daily summary (~2 KB) for Ollama / Open WebUI

On each run: compares local files against Garmin Connect and fills in any missing days.
"""

import json
import os
import sys
import logging
import time
from datetime import date, timedelta
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL",    "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "yourpassword")
BASE_DIR        = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()
RAW_DIR         = BASE_DIR / "raw"
SUMMARY_DIR     = BASE_DIR / "summary"

# Earliest date to backfill. Set manually if auto-detection fails, e.g. "2022-01-01"
SYNC_START_DATE = os.environ.get("GARMIN_SYNC_START", None)

# Delay between API requests in seconds — prevents rate limiting
REQUEST_DELAY   = float(os.environ.get("GARMIN_REQUEST_DELAY", "1.5"))
# ──────────────────────────────────────────────────────────────────────────────

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
    stress_vals = _parse_list_values(raw.get("stress"), "stressLevel")
    stress_vals = [v for v in stress_vals if v > 0]
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

def get_garmin_start(client) -> date:
    """Determines the earliest available date from the Garmin account."""
    if SYNC_START_DATE:
        return date.fromisoformat(SYNC_START_DATE)
    try:
        profile = client.get_user_profile()
        reg = safe_get(profile, "userInfo", "registrationDate")
        if reg:
            return date.fromisoformat(reg[:10])
    except Exception:
        pass
    log.warning("Could not determine registration date, falling back to 90 days.")
    return date.today() - timedelta(days=90)


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

    today     = date.today()
    yesterday = today - timedelta(days=1)
    start     = get_garmin_start(client)
    local     = get_local_dates(RAW_DIR)
    missing   = sorted(set(date_range(start, yesterday)) - local)

    if not missing:
        log.info("All days already present — nothing to do.")
        return

    log.info(f"Local: {len(local)} days  |  Missing: {len(missing)} days")
    log.info(f"Backfill from {missing[0]} to {missing[-1]} ...")

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
