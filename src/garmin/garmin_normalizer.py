#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_normalizer.py

Adapter — universal entry point between data sources and the pipeline.

Receives raw data from any source, ensures the canonical schema minimum
is present, and returns a normalised dict for the rest of the pipeline.
Extensibility is the core principle: a new data source is plugged in here
without touching collector, quality, or sync.

Current sources (v1.2.2):
  "api"  — live Garmin Connect API pull via garmin_api.py
  "bulk" — Garmin bulk export (placeholder, implemented in a later version)

Public functions:
  normalize(raw, source) → dict   — normalise raw dict from any source
  summarize(raw)         → dict   — distill normalised dict into compact summary (~2 KB)

Module constants:
  CURRENT_SCHEMA_VERSION — version of the summary schema produced by summarize()

No file IO, no quality log access, no API calls, no ENV reads.
"""

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Version of the summary schema produced by summarize().
# Increment when fields are added, removed, or renamed in the summary dict.
# v1.7.1.14: 3 → 4 — new "blood_pressure" summary section (Issue #7).
# Purely additive (no existing field changed/removed), but bumped anyway
# so the self-healing / schema-migration loop picks up already-archived
# days and regenerates their summary from raw/ automatically — raw/
# already holds the full get_blood_pressure payload for those days
# (that was the original Issue #7 gap: data archived, never surfaced).
# v1.7.6.6: 4 → 5 — new "alerts" section, the "training" section is filled from the shapes of the
# API day (readiness and max_metrics as lists, the training status under its device id) and has the
# new field training_status_code. Already-archived days get the values through the schema migration
# (raw/ holds the data, no API call).
CURRENT_SCHEMA_VERSION = 5


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

    Source tracking ("source", "source_metadata") is planned for a later version.
    """
    if not isinstance(raw, dict):
        log.warning("  _normalize_api: received non-dict — returning empty day")
        return {"date": "unknown"}

    # Structural type checks removed in v1.3.4 — now handled by garmin_validator.py
    # before this function is called. Minimal guard above remains as bypass protection.
    return raw


def _normalize_import(raw: dict) -> dict:
    """
    Normalises a raw dict from garmin_import.parse_day().

    garmin_import.parse_day() already delivers the canonical schema —
    this function applies the same type validation as _normalize_api()
    and guarantees the "date" key is present.
    """
    if not isinstance(raw, dict):
        log.warning("  _normalize_import: received non-dict — returning empty day")
        return {"date": "unknown"}

    # Structural type checks removed in v1.3.4 — now handled by garmin_validator.py
    # before this function is called. Minimal guard above remains as bypass protection.

    # Bulk HR remap: user_summary → heart_rates
    # summarize() reads from heart_rates — not present in bulk raw.
    # Copy aggregate values so summarize() can find them.
    us = raw.get("user_summary") or {}
    if us and "heart_rates" not in raw:
        hr = {}
        for field in ("restingHeartRate", "minHeartRate", "maxHeartRate"):
            if us.get(field) is not None:
                hr[field] = us[field]
        if hr:
            raw["heart_rates"] = hr

    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  Summary extraction
# ══════════════════════════════════════════════════════════════════════════════

def summarize(raw: dict) -> dict:
    """Distills a normalised raw dict into a compact daily summary (~2 KB)."""
    s = {
        "date":           raw.get("date"),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generated_by":   "garmin_normalizer.py",
    }

    # ── Sleep & HRV ──
    sleep_raw = raw.get("sleep", {}) or {}
    ds        = safe_get(sleep_raw, "dailySleepDTO", default={})
    hrv_raw   = raw.get("hrv", {}) or {}
    hrv_sum   = safe_get(hrv_raw, "hrvSummary", default={}) or safe_get(sleep_raw, "hrvSummary", default={})
    _sleep_secs = safe_get(ds, "sleepTimeSeconds")
    if _sleep_secs is None:
        log.warning(f"[NORMALIZER] summarize {raw.get('date', '?')}: "
                    f"sleepTimeSeconds missing — writing 0.0h")
    s["sleep"] = {
        "duration_h":          round((_sleep_secs or 0) / 3600, 2),
        "deep_h":              round((safe_get(ds, "deepSleepSeconds")  or 0) / 3600, 2),
        "rem_h":               round((safe_get(ds, "remSleepSeconds")   or 0) / 3600, 2),
        "light_h":             round((safe_get(ds, "lightSleepSeconds") or 0) / 3600, 2),
        "awake_h":             round((safe_get(ds, "awakeSleepSeconds") or 0) / 3600, 2),
        "score":               safe_get(ds, "sleepScores", "overall", "value"),
        "spo2_avg":            safe_get(ds, "averageSpO2Value"),
        "respiration_avg":     safe_get(ds, "averageRespirationValue"),
        # v1.7.1.13, Issue #8: primary key was "lastNight" (never present in
        # the real Garmin payload — always None) with an unconditional
        # fallback to "lastNight5MinHigh" (the night's peak 5-min reading,
        # not an average) under a field name that promises an average.
        # Fallback removed deliberately — a missing lastNightAvg now surfaces
        # as None instead of silently substituting a differently-shaped value.
        "hrv_last_night_ms":   safe_get(hrv_sum, "lastNightAvg"),
        "hrv_weekly_avg_ms":   safe_get(hrv_sum, "weeklyAvg"),
        "hrv_status":          safe_get(hrv_sum, "status"),
        "hrv_feedback":        safe_get(hrv_sum, "feedbackPhrase"),
        "sleep_score_feedback":  safe_get(ds, "sleepScoreFeedback"),
        "sleep_score_qualifier": safe_get(ds, "sleepScores", "overall", "qualifierKey"),
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

    # Bulk fallback: if no intraday array, use precomputed aggregate fields
    stress_avg = round(sum(stress_vals) / len(stress_vals), 1) if stress_vals else \
                 stress_src.get("averageStressLevel") if isinstance(stress_src, dict) else None
    stress_max = max(stress_vals, default=None) if stress_vals else \
                 stress_src.get("maxStressLevel") if isinstance(stress_src, dict) else None

    s["stress"] = {
        "stress_avg":       stress_avg,
        "stress_max":       stress_max,
        "body_battery_max": max(bb_vals, default=None),
        "body_battery_min": min(bb_vals, default=None),
        "body_battery_end": bb_vals[-1] if bb_vals else None,
    }

    # ── Daily stats ──
    us = raw.get("user_summary", {}) or {}
    st = raw.get("stats", {}) or {}
    cd = raw.get("get_calories_daily") or []
    s["day"] = {
        "steps":                  safe_get(us, "totalSteps") or safe_get(st, "totalSteps"),
        "steps_goal":             safe_get(us, "dailyStepGoal"),
        "calories_active":        safe_get(us, "activeKilocalories"),
        "calories_total":         safe_get(us, "totalKilocalories"),
        "calories_resting":       safe_get(cd[0], "resting") if cd else None,
        "intensity_min_moderate": safe_get(us, "moderateIntensityMinutes"),
        "intensity_min_vigorous": safe_get(us, "vigorousIntensityMinutes"),
        "floors_climbed":         safe_get(us, "floorsAscended"),
        "distance_km":            round((safe_get(us, "totalDistanceMeters") or 0) / 1000, 2) or None,
    }

    # ── Body composition (v1.6.8 capability-scan pilot) ──
    bc = raw.get("get_body_composition") or {}
    s["body_composition"] = {
        "weight_g": safe_get(bc, "totalAverage", "weight"),
    }

    # ── Hydration (v1.6.8 Gruppe 1) ──
    hy = raw.get("get_hydration_data") or {}
    s["hydration"] = {
        "value_ml": safe_get(hy, "valueInML"),
    }

    # ── Blood pressure (v1.7.1.14, Issue #7) ──
    # raw["get_blood_pressure"]["measurementSummaries"] is a list, one
    # entry per day. The six aggregate scalars are pulled 1:1 from that
    # day-object. worstReading has no day-level Garmin aggregate (no
    # average/latest field, per GitHub issue #7 discussion) — derived
    # here from measurements[]: the measurement whose own "category"
    # matches the day's "category" (the reading that triggered it). If
    # more than one measurement shares that category, the chronologically
    # latest one wins (sorted by measurementTimestampLocal) — deterministic
    # regardless of the raw list's own order, which is not guaranteed
    # chronological. worstReading is intentionally NOT part of _FIELD_MAP
    # (Option B) — it stays a plain nested object here, read directly from
    # the summary by consumers that need it, not routed through the broker.
    bp_raw  = raw.get("get_blood_pressure") or {}
    bp_days = safe_get(bp_raw, "measurementSummaries", default=[]) or []
    bp_day  = bp_days[0] if bp_days else {}
    bp_worst_reading = None
    _bp_day_category = safe_get(bp_day, "category")
    _bp_candidates = [
        m for m in (safe_get(bp_day, "measurements", default=[]) or [])
        if isinstance(m, dict) and m.get("category") == _bp_day_category
    ]
    if _bp_candidates:
        _bp_candidates.sort(key=lambda m: m.get("measurementTimestampLocal") or "")
        _bp_worst = _bp_candidates[-1]
        bp_worst_reading = {
            "systolic":  _bp_worst.get("systolic"),
            "diastolic": _bp_worst.get("diastolic"),
            "pulse":     _bp_worst.get("pulse"),
            "timestamp": _bp_worst.get("measurementTimestampLocal"),
        }
    s["blood_pressure"] = {
        "high_systolic":    safe_get(bp_day, "highSystolic"),
        "high_diastolic":   safe_get(bp_day, "highDiastolic"),
        "low_systolic":     safe_get(bp_day, "lowSystolic"),
        "low_diastolic":    safe_get(bp_day, "lowDiastolic"),
        "num_measurements": safe_get(bp_day, "numOfMeasurements"),
        "category":         _bp_day_category,
        "worstReading":     bp_worst_reading,
    }

    # ── Training ──
    # v1.7.6.6, P1.2: the API day holds training_readiness and max_metrics as LISTS of objects and the
    # training status nested under mostRecentTrainingStatus.latestTrainingStatusData.<device id>;
    # the export values (bulk/aggregates) hold readiness as a dict. Both forms are read, the dict
    # forms and keys read before stay valid.
    tr = _pick_entry(raw.get("training_readiness"))
    ts = raw.get("training_status", {}) or {}
    mm = _pick_metrics(raw.get("max_metrics"))
    es = raw.get("get_endurance_score") or {}
    hs = raw.get("get_hill_score") or {}
    fa = raw.get("get_fitnessage_data") or {}
    _devices = safe_get(ts, "mostRecentTrainingStatus", "latestTrainingStatusData")
    _dev     = _latest_entry(list(_devices.values()) if isinstance(_devices, dict) else [])
    _code    = _dev.get("trainingStatus") if _dev else None
    if isinstance(_code, bool) or not isinstance(_code, int):
        _code = None
    _status_text = _TRAINING_STATUS_TEXT.get(_code)
    _fitness_age = safe_get(fa, "fitnessAge")
    if _fitness_age is None:
        _fitness_age = safe_get(mm, "generic", "fitnessAge")
    s["training"] = {
        "readiness_score":    safe_get(tr, "score") or safe_get(tr, "trainingReadinessScore"),
        "readiness_level":    safe_get(tr, "level") or safe_get(tr, "trainingReadinessLevel"),
        "readiness_feedback": safe_get(tr, "feedbackLong"),
        "training_status":    _status_text if _status_text is not None
                              else safe_get(ts, "latestTrainingStatus") or safe_get(ts, "trainingStatus"),
        "training_status_code": _code,
        "training_load_7d":   safe_get(ts, "trainingLoadBalance", "sevenDayTrainingLoad"),
        "vo2max":             safe_get(mm, "vo2MaxPreciseValue") or safe_get(mm, "generic", "vo2MaxPreciseValue"),
        "endurance_score":    safe_get(es, "overallScore"),
        "hill_score":         safe_get(hs, "overallScore"),
        "fitness_age":        _fitness_age,
    }

    # ── Alerts (v1.7.6.6, P1.3) ──
    # Values the API day already holds and the summary did not show. user_summary first, stats second
    # (the archive holds the same values in both). The export values (bulk/aggregates) carry none of
    # these fields, so a day without an API day has them all as None. Texts are passed on as Garmin
    # delivers them ("NONE" and "UNKNOWN" are values, not gaps); a value of another type is None.
    # The body battery levels are the category of the body battery at the time of the event: the
    # first event falls in the evening, the end-of-day event later, near bedtime (measured on the
    # archive, not a Garmin definition). The HRV status stays in sleep.hrv_status.
    s["alerts"] = {
        "hr_alert_count":       _first_count(safe_get(us, "abnormalHeartRateAlertsCount"),
                                             safe_get(st, "abnormalHeartRateAlertsCount")),
        "breathing_disruption": _first_text(safe_get(ds, "breathingDisruptionSeverity")),
        "acwr_status":          _first_text(safe_get(_dev, "acuteTrainingLoadDTO", "acwrStatus")),
        "body_battery_level":   _first_text(
            safe_get(us, "bodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel"),
            safe_get(st, "bodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel")),
        "body_battery_level_end_of_day": _first_text(
            safe_get(us, "endOfDayBodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel"),
            safe_get(st, "endOfDayBodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel")),
        "stress_qualifier":     _first_text(safe_get(us, "stressQualifier"), safe_get(st, "stressQualifier")),
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


# Names of the training status numbers (v1.7.6.6, P1.2). Origin: the API data of the archive itself —
# in every entry that carries the number and the text trainingStatusFeedbackPhrase, number and
# first word of the text agree (class A of the provenance rule; observed, not from a Garmin document).
# A number that is not listed gets no text; it is not guessed.
_TRAINING_STATUS_TEXT = {
    0: "NO_STATUS",
    1: "DETRAINING",
    3: "OVERREACHING",
    4: "MAINTAINING",
    5: "RECOVERY",
    7: "PRODUCTIVE",
}


def _entry_time(entry: dict):
    """Time of an entry as seconds, or None: "timestamp" is ISO text (readiness) or milliseconds (training status)."""
    ts = entry.get("timestamp")
    if isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        return ts / 1000.0
    if isinstance(ts, str):
        try:
            return datetime.strptime(ts[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None
    return None


def _latest_entry(entries):
    """
    The latest of several entries (dicts), independent of their order (v1.7.6.6, P1.2): an entry with
    a readable "timestamp" beats one without, the later beats the earlier; with the same time (or none
    on both sides) the smaller canonical JSON text wins. Entries that are no dict are ignored.
    Returns {} when there is none. Same rule as garmin_import._later_entry_wins (a core module, which
    reads ISO text only), kept apart here because the training status carries milliseconds.
    """
    best, best_t = None, None
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        t = _entry_time(e)
        if best is None:
            best, best_t = e, t
        elif t != best_t:
            if best_t is None or (t is not None and t > best_t):
                best, best_t = e, t
        elif _canon(e) < _canon(best):
            best, best_t = e, t
    return best if best is not None else {}


def _canon(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _pick_entry(value) -> dict:
    """A dict as it is; a list of entries -> the latest one (_latest_entry); anything else -> {}."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return _latest_entry(value)
    return {}


def _pick_metrics(value) -> dict:
    """max_metrics: a dict as it is; a list -> the element with the newest generic.calendarDate (the first on a tie)."""
    if isinstance(value, dict):
        return value
    best, best_day = None, ""
    for e in value if isinstance(value, list) else []:
        if not isinstance(e, dict):
            continue
        day = str(safe_get(e, "generic", "calendarDate") or "")
        if best is None or day > best_day:
            best, best_day = e, day
    return best if best is not None else {}


def _first_text(*values):
    """The first value that is a non-empty string, else None (v1.7.6.6, P1.3)."""
    for v in values:
        if isinstance(v, str) and v:
            return v
    return None


def _first_count(*values):
    """The first value that is a whole number (not a boolean), else None (v1.7.6.6, P1.3)."""
    for v in values:
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _parse_list_values(lst, dict_key: int | str) -> list:
    """
    Extracts numeric values from a list of dicts or [timestamp, ...] tuples.

    dict_key selects the extraction mode:
      - str: dict-key lookup (item.get(dict_key)) for list-of-dicts input.
      - int: positional index (item[dict_key]) for list/tuple input — e.g.
        dict_key=2 reads index 2 of a [ts, status, value] triplet, not just
        the [ts, value] pair case (dict_key=1).

    v1.7.1.13, Issue #6: previously ALWAYS read item[1] for list/tuple
    items regardless of dict_key — a call site passing dict_key=2 (e.g.
    body_battery's [ts, status, value] triplet) silently read the status
    field instead of the value, and non-numeric status strings made the
    result list empty. Existing callers all pass dict_key=1, so their
    behavior is unchanged (item[1] == item[dict_key] when dict_key == 1).
    """
    result = []
    for item in (lst or []):
        if isinstance(item, dict):
            v = item.get(dict_key)
        elif isinstance(item, (list, tuple)) and isinstance(dict_key, int) and len(item) > dict_key:
            v = item[dict_key]
        else:
            continue
        if isinstance(v, (int, float)):
            result.append(v)
    return result
