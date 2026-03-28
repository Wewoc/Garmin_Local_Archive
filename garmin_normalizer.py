#!/usr/bin/env python3
"""
garmin_normalizer.py

Adapter — universal entry point between data sources and the pipeline.

Receives raw data from any source, ensures the canonical schema minimum
is present, and returns a normalised dict for the rest of the pipeline.
Extensibility is the core principle: a new data source is plugged in here
without touching collector, quality, or sync.

Current sources (v1.2.1):
  "api"  — live Garmin Connect API pull via garmin_api.py
  "bulk" — Garmin bulk export (placeholder, implemented in a later version)

Planned (v1.2.2):
  Sets "source" and "source_metadata" fields in the normalised dict.
  Until then the dict passes through unchanged — only "date" is guaranteed.

Public functions:
  normalize(raw, source) → dict   — normalise raw dict from any source
  summarize(raw)         → dict   — distill normalised dict into compact summary (~2 KB)

No file IO, no quality log access, no API calls, no ENV reads.
"""

import logging

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def normalize(raw: dict, source: str = "api") -> dict:
    """
    Normalises a raw data dict from any source into the canonical schema.

    Parameters
    ----------
    raw    : dict — raw data as returned by garmin_api.fetch_raw() or
                    garmin_import.load_bulk()
    source : str  — origin of the data: "api" | "bulk"

    Returns
    -------
    dict — normalised data dict, guaranteed to contain at least {"date": ...}

    Note: "source" and "source_metadata" fields will be added here from v1.2.2.
    """
    if source == "api":
        return _normalize_api(raw)
    if source == "bulk":
        return _normalize_import(raw)

    log.warning(f"  normalize: unknown source '{source}' — passing through unchanged")
    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  Source-specific normalisers
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_api(raw: dict) -> dict:
    """
    Normalises a raw dict from garmin_api.fetch_raw().

    In v1.2.0 the Garmin API already delivers the expected format —
    this function passes the dict through unchanged and guarantees
    the "date" key is present.

    From v1.2.2: will set "source": "api" and "source_metadata".
    """
    if not isinstance(raw, dict):
        log.warning("  _normalize_api: received non-dict — returning empty day")
        return {"date": "unknown"}

    # Guarantee canonical minimum: date must always be present
    if "date" not in raw:
        log.warning("  _normalize_api: 'date' key missing in raw dict")

    return raw


def _normalize_import(raw: dict) -> dict:
    """
    Normalises a raw dict from garmin_import.load_bulk().

    Placeholder — not implemented in v1.2.0.
    Returns the dict unchanged until bulk import is implemented.

    From v1.2.2: will set "source": "bulk" and "source_metadata".
    """
    if not isinstance(raw, dict):
        log.warning("  _normalize_import: received non-dict — returning empty day")
        return {"date": "unknown"}

    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  Summary extraction
# ══════════════════════════════════════════════════════════════════════════════

def summarize(raw: dict) -> dict:
    """Distills a normalised raw dict into a compact daily summary (~2 KB)."""
    s = {"date": raw.get("date"), "generated_by": "garmin_normalizer.py"}

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
    stress_src    = raw.get("stress") or {}
    stress_arr    = stress_src.get("stressValuesArray") or [] if isinstance(stress_src, dict) else []
    stress_offset = (stress_src.get("stressChartValueOffset") or 0) if isinstance(stress_src, dict) else 0
    stress_vals   = []
    for item in stress_arr:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                v = float(item[1]) - stress_offset
                if v >= 0:
                    stress_vals.append(v)
            except (TypeError, ValueError):
                pass

    bb_arr  = stress_src.get("bodyBatteryValuesArray") or [] if isinstance(stress_src, dict) else []
    bb_vals = []
    for item in bb_arr:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            try:
                bb_vals.append(float(item[2]))
            except (TypeError, ValueError):
                pass
    if not bb_vals:
        bb_raw  = raw.get("body_battery")
        bb_list = safe_get(bb_raw, "bodyBatteryValuesArray", default=[]) if isinstance(bb_raw, dict) else (bb_raw if isinstance(bb_raw, list) else [])
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


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def safe_get(d, *keys, default=None):
    """Traverses nested dicts safely. Returns default if any key is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


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
