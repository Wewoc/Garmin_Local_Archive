#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_health_map.py

Garmin-side field resolver for the dashboard broker architecture.

Knows the full internal structure of Garmin data: which generic field name
maps to which resolution, which JSON section, and which key path.

Rules:
- Never writes. Never knows what a dashboard looks like.
- Never touches files of any other source.
- Called exclusively by health_map.py — never directly by specialists.

Generic field names (dashboard-side):
  no suffix   → daily    → reads from summary/
  _series     → intraday → reads from raw/ (and, for heart_rate_series, bulk/)
  daily values only the Garmin export has (stress durations) → bulk/aggregates

Internal Garmin key format (garmin-side, never visible to specialists):
  "section.key"  or  "section.nested.key"

Architecture boundary:
  Any Garmin-internal key (section.field) appearing outside this module
  is an architecture violation — detectable by name format alone.
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# garmin_health_map lives in maps/ — garmin/ is one level up (sibling package)
# This is the one sys.path bridge between maps/ and garmin/
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg
import garmin_api_capability as capability

# date_utils.py is domain-less, lives in src/-Root (not garmin/) — second bridge
sys.path.insert(0, str(Path(__file__).parent.parent))
from date_utils import date_range

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  Field map — single source of truth for all Garmin field definitions
#
#  Structure per field:
#    "intraday": (section, key)  or  None if intraday not available
#    "daily":    (section, key)  or  None if daily not available
#
#  section = top-level key in the raw/summary JSON
#  key     = dot-separated path within that section
#
#  A field that only the Garmin export has (v1.7.6.1) carries "bulk_daily":
#  (section, key) instead of "daily": the value of one day is read from
#  garmin_data/bulk/aggregates (see _read_bulk_daily), "daily" and "intraday" are None.
#  Fields the API also has are not listed per track: summary/ already holds the one
#  resolved value of the day (garmin_writer), so "daily" is enough for them.
#
#  "raw_pct": (section, object, seconds_key, total_key) — a percentage of two numbers of
#  one object. It reads raw/ and, for a day whose raw/ has no usable object (no total above
#  0), the same object from bulk/aggregates (v1.7.6.1); one source per day, never mixed.
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {

    # ── Daily fields (summary/) ───────────────────────────────────────────────

    "hrv_last_night": {
        "intraday": None,
        "daily":    ("sleep",     "hrv_last_night_ms"),
        # v1.7.1.13, Issue #8: primary candidate corrected from the
        # nonexistent "lastNight" key to "lastNightAvg". Unlike
        # summarize()/assess_quality_fields(), the fallback to
        # "lastNight5MinHigh" is DELIBERATELY KEPT here — this is the
        # live-only path (no archive equivalent to fall back to), and
        # Garmin may not have finished computing lastNightAvg yet at the
        # time of day this is typically queried. A peak-value stand-in is
        # judged acceptable for a live snapshot in a way it is not for an
        # archived daily value.
        "live_nested": [
            ("hrv", "hrvSummary.lastNightAvg"),
            ("hrv", "hrvSummary.lastNight5MinHigh"),
        ],
    },
    "sleep_deep_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "deepSleepSeconds",  "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "deepSleepSeconds",  "sleepTimeSeconds"),
    },
    "sleep_light_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "lightSleepSeconds", "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "lightSleepSeconds", "sleepTimeSeconds"),
    },
    "sleep_rem_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "remSleepSeconds",   "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "remSleepSeconds",   "sleepTimeSeconds"),
    },
    "sleep_awake_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "awakeSleepSeconds", "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "awakeSleepSeconds", "sleepTimeSeconds"),
    },
    "resting_heart_rate": {
        "intraday": None,
        "daily":    ("heartrate", "resting_bpm"),
    },
    "spo2_avg": {
        "intraday": None,
        "daily":    ("sleep",     "spo2_avg"),
    },
    "sleep_duration": {
        "intraday": None,
        "daily":    ("sleep",     "duration_h"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepTimeSeconds", 3600),
        ],
    },
    "body_battery_max": {
        "intraday": None,
        "daily":    ("stress",    "body_battery_max"),
    },
    "stress_avg": {
        "intraday": None,
        "daily":    ("stress",    "stress_avg"),
    },
    "vo2max": {
        "intraday": None,
        "daily":    ("training",  "vo2max"),
    },

    "sleep_score": {
        "intraday": None,
        "daily":    ("sleep", "score"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScores.overall.value"),
        ],
    },
    "sleep_score_feedback": {
        "intraday": None,
        "daily":    ("sleep", "sleep_score_feedback"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScoreFeedback"),
        ],
    },
    "sleep_score_qualifier": {
        "intraday": None,
        "daily":    ("sleep", "sleep_score_qualifier"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScores.overall.qualifierKey"),
        ],
    },
    "hydration_ml": {
        "intraday": None,
        "daily":    ("hydration", "value_ml"),
    },
    "endurance_score": {
        "intraday": None,
        "daily":    ("training", "endurance_score"),
    },
    "hill_score": {
        "intraday": None,
        "daily":    ("training", "hill_score"),
    },

    # ── Intraday fields (raw/) ────────────────────────────────────────────────
    #
    #  "intraday": (section, array_key, extract)
    #
    #  extract describes how to normalize each array item to {"ts": str, "value": float}:
    #    ts_index:   index of the timestamp in a list-item  (None = dict-based)
    #    val_index:  index of the value    in a list-item  (None = dict-based)
    #    ts_key:     dict key for timestamp  (used when ts_index is None)
    #    val_key:    dict key for value      (used when val_index is None)
    #    val_min:    drop items where value < val_min (None = no filter)
    #    offset_key: sibling key in the section dict to subtract from value (None = no offset)

    "heart_rate_series": {
        "intraday": ("heart_rates", "heartRateValues", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "heartRate",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("heart_rates", "heartRateValues", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "heartRate",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "stress_series": {
        "intraday": ("stress", "stressValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "stressLevel",
            "val_min":    0,
            "offset_key": "stressChartValueOffset",
        }),
        "live": ("stress", "stressValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "stressLevel",
            "val_min":    0,
            "offset_key": "stressChartValueOffset",
        }),
        "daily": None,
    },
    "spo2_series": {
        "intraday": ("spo2", "spO2HourlyAverages", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "spO2Reading",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("spo2", "spO2HourlyAverages", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "spO2Reading",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "body_battery_series": {
        "intraday": ("stress", "bodyBatteryValuesArray", {
            "ts_index":   0,
            "val_index":  2,
            "ts_key":     "startGMT",
            "val_key":    "bodyBatteryLevel",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("stress", "bodyBatteryValuesArray", {
            "ts_index":   0,
            "val_index":  2,
            "ts_key":     "startGMT",
            "val_key":    "bodyBatteryLevel",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "respiration_series": {
        "intraday": ("respiration", "respirationValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "respirationValue",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("respiration", "respirationValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "respirationValue",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "steps_series": {
        "intraday": ("steps", None, {
            "ts_index":   None,
            "val_index":  None,
            "ts_key":     "startGMT",
            "val_key":    "steps",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("steps", None, {
            "ts_index":   None,
            "val_index":  None,
            "ts_key":     "startGMT",
            "val_key":    "steps",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },

    # ── Capability-Scan pilot fields (v1.6.8) — flat daily values from
    #    summary/, same "daily" descriptor as the baseline fields above ──

    "body_weight": {
        "intraday": None,
        "daily":    ("body_composition", "weight_g"),
    },
    "calories_resting": {
        "intraday": None,
        "daily":    ("day", "calories_resting"),
    },
    "fitness_age": {
        "intraday": None,
        "daily":    ("training", "fitness_age"),
    },

    # ── Blood pressure scalars (v1.7.1.14, Issue #7) — six aggregate
    #    values 1:1 from Garmin's daily BP aggregate. worstReading (the
    #    measurement that triggered the day's category) is deliberately
    #    NOT part of _FIELD_MAP — Option B, see NOTES_v1_7_1_14.md:
    #    stored as a structured object directly in the summary, not
    #    routed through the broker. ──

    "bp_high_systolic": {
        "intraday": None,
        "daily":    ("blood_pressure", "high_systolic"),
    },
    "bp_high_diastolic": {
        "intraday": None,
        "daily":    ("blood_pressure", "high_diastolic"),
    },
    "bp_low_systolic": {
        "intraday": None,
        "daily":    ("blood_pressure", "low_systolic"),
    },
    "bp_low_diastolic": {
        "intraday": None,
        "daily":    ("blood_pressure", "low_diastolic"),
    },
    "bp_num_measurements": {
        "intraday": None,
        "daily":    ("blood_pressure", "num_measurements"),
    },
    "bp_category": {
        "intraday": None,
        "daily":    ("blood_pressure", "category"),
    },

    # ── v1.7.1.16 — Broker-Registrierungslücken geschlossen: alle 23
    #    Felder unten werden bereits von summarize() berechnet und liegen
    #    fertig in summary/*.json, waren aber nie in _FIELD_MAP
    #    registriert (unsichtbar für query_health()/list_available_
    #    fields()/den SQLite-Sync). Kein Normalizer-/Collector-Eingriff
    #    nötig — reine Registrierung. Siehe NOTES_v1.7.1.16.md für die
    #    volle Herleitung (Live-MCP-Test + Abgleich summarize() vs.
    #    _FIELD_MAP) und die Baseline-/Capability-Einordnung je Feld.
    #    Alle 23 Werte sind einfache Skalare (Zahl/Text) mit bereits
    #    laufender, verifizierter Extraktion — keiner hat ein unklares
    #    Datenformat wie worstReading (siehe dessen Option-B-Kommentar
    #    oben), daher keine Ausschlüsse in dieser Gruppe.

    # -- Geschwister von hrv_last_night (alle Baseline, "hrv"-Endpoint) --
    "hrv_weekly_avg": {
        "intraday": None,
        "daily":    ("sleep", "hrv_weekly_avg_ms"),
    },
    "hrv_status": {
        "intraday": None,
        "daily":    ("sleep", "hrv_status"),
    },
    "hrv_feedback": {
        "intraday": None,
        "daily":    ("sleep", "hrv_feedback"),
    },

    # -- Geschwister von stress_avg/body_battery_max (Baseline, "stress"-Endpoint) --
    "stress_max": {
        "intraday": None,
        "daily":    ("stress", "stress_max"),
    },
    "body_battery_min": {
        "intraday": None,
        "daily":    ("stress", "body_battery_min"),
    },
    "body_battery_end": {
        "intraday": None,
        "daily":    ("stress", "body_battery_end"),
    },

    # -- Stress durations, only in the Garmin export (v1.7.6.1), seconds per day --
    # Read from bulk/aggregates ("stress" section of the daily values), the API has
    # no such values. stressDuration of the export is low + medium + high and is not
    # registered on its own.
    "stress_rest_duration": {
        "intraday":   None,
        "daily":      None,
        "bulk_daily": ("stress", "restDuration"),
    },
    "stress_low_duration": {
        "intraday":   None,
        "daily":      None,
        "bulk_daily": ("stress", "lowDuration"),
    },
    "stress_medium_duration": {
        "intraday":   None,
        "daily":      None,
        "bulk_daily": ("stress", "mediumDuration"),
    },
    "stress_high_duration": {
        "intraday":   None,
        "daily":      None,
        "bulk_daily": ("stress", "highDuration"),
    },

    # -- Geschwister von resting_heart_rate (Baseline, "heart_rates"-Endpoint) --
    "heart_rate_max": {
        "intraday": None,
        "daily":    ("heartrate", "max_bpm"),
    },
    "heart_rate_min": {
        "intraday": None,
        "daily":    ("heartrate", "min_bpm"),
    },
    "heart_rate_avg": {
        "intraday": None,
        "daily":    ("heartrate", "avg_bpm"),
    },

    # -- "day"-Sektion (Baseline, "user_summary"/"stats"-Endpoints) --
    # v1.7.1.16 correction: originally registered as "steps" — dead on
    # arrival, HEALTH_FIELD_ALIASES already maps that exact name to
    # "steps_series" (clients/mcp_server.py) and alias resolution runs
    # before a direct _FIELD_MAP lookup, so query_health("steps", ...)
    # never reached this entry. Caught live post-deploy, see
    # NOTES_v1_7_1_16.md. Renamed to "steps_total" — no collision,
    # matches the "calories_total" naming already used in this same
    # batch.
    "steps_total": {
        "intraday": None,
        "daily":    ("day", "steps"),
    },
    "steps_goal": {
        "intraday": None,
        "daily":    ("day", "steps_goal"),
    },
    "floors_climbed": {
        "intraday": None,
        "daily":    ("day", "floors_climbed"),
    },
    "intensity_min_moderate": {
        "intraday": None,
        "daily":    ("day", "intensity_min_moderate"),
    },
    "intensity_min_vigorous": {
        "intraday": None,
        "daily":    ("day", "intensity_min_vigorous"),
    },
    "distance": {
        "intraday": None,
        "daily":    ("day", "distance_km"),
    },

    # -- "day"-Sektion, Capability-gated (get_calories_daily, gleicher
    #    Endpoint wie das bereits registrierte calories_resting) --
    "calories_active": {
        "intraday": None,
        "daily":    ("day", "calories_active"),
    },
    "calories_total": {
        "intraday": None,
        "daily":    ("day", "calories_total"),
    },

    # -- "training"-Sektion (Baseline, "training_readiness"/
    #    "training_status"-Endpoints) --
    "readiness_score": {
        "intraday": None,
        "daily":    ("training", "readiness_score"),
    },
    "readiness_level": {
        "intraday": None,
        "daily":    ("training", "readiness_level"),
    },
    "readiness_feedback": {
        "intraday": None,
        "daily":    ("training", "readiness_feedback"),
    },
    "training_status": {
        "intraday": None,
        "daily":    ("training", "training_status"),
    },
    "training_load_7d": {
        "intraday": None,
        "daily":    ("training", "training_load_7d"),
    },

    # -- Ursprünglicher Auslöser dieser Session (Live-MCP-Test): kein
    #    Tageswert für Atemfrequenz abfragbar, nur respiration_series
    #    (Intraday, ~70 KB/Tag) -- Wert liegt analog zu spo2_avg bereits
    #    unter "sleep" in summary/*.json. --
    "respiration_avg": {
        "intraday": None,
        "daily":    ("sleep", "respiration_avg"),
    },

    # -- v1.7.6.6, P1.5 — "alerts" section of summary/ (summarize(), schema 5): values the API day
    #    already held and the summary did not show. Baseline fields (no capability gate, they come
    #    from the baseline endpoints). Texts are passed on as Garmin delivers them ("NONE",
    #    "UNKNOWN" are values); the two body battery levels are the category of the body battery at
    #    the time of the event (evening / near bedtime) — observed on the archive, not a Garmin
    #    definition. training.training_status_code is deliberately NOT registered: a status number
    #    has no order, a baseline or anomaly flag over it would mean nothing. --
    "hr_alert_count": {
        "intraday": None,
        "daily":    ("alerts", "hr_alert_count"),
    },
    "breathing_disruption": {
        "intraday": None,
        "daily":    ("alerts", "breathing_disruption"),
    },
    "acwr_status": {
        "intraday": None,
        "daily":    ("alerts", "acwr_status"),
    },
    "body_battery_level": {
        "intraday": None,
        "daily":    ("alerts", "body_battery_level"),
    },
    "body_battery_level_end_of_day": {
        "intraday": None,
        "daily":    ("alerts", "body_battery_level_end_of_day"),
    },
    "stress_qualifier": {
        "intraday": None,
        "daily":    ("alerts", "stress_qualifier"),
    },
}

# ══════════════════════════════════════════════════════════════════════════════
#  Raw-passthrough fields (v1.6.8) — deliberately NOT part of _FIELD_MAP.
#
#  These 13 Capability-Scan candidates have no known daily-value extraction
#  (list-of-entries structure, empty/unknown schema at the maintainer's account, or
#  event-log structure) — see NOTES_v168_D_01.md "Blocker-Typen" for the
#  per-field reasoning. Rather than leave them archived-but-unreachable,
#  they are exposed as archived in raw/ (no value extraction) via get_raw()/list_raw_fields() — separate
#  from get()/list_fields() so existing dashboards (which assume a scalar
#  "value") are structurally unaffected. Interpretation is the caller's
#  responsibility. Status: open for community feedback, see GitHub issue
#  (linked in REFERENCE_BROKER.md "Raw-Passthrough-Felder").
# ══════════════════════════════════════════════════════════════════════════════

_RAW_PASSTHROUGH_FIELDS = {
    "daily_weigh_ins":          "get_daily_weigh_ins",
    "menstrual_calendar_data":  "get_menstrual_calendar_data",
    "pregnancy_summary":        "get_pregnancy_summary",
    "lifestyle_logging_data":   "get_lifestyle_logging_data",
    "nutrition_daily_food_log": "get_nutrition_daily_food_log",
    "nutrition_daily_meals":    "get_nutrition_daily_meals",
    "nutrition_daily_settings": "get_nutrition_daily_settings",
    "floors":                   "get_floors",
    "intensity_minutes_data":   "get_intensity_minutes_data",
    "body_battery_events":      "get_body_battery_events",
    "lactate_threshold":        "get_lactate_threshold",
    "running_tolerance":        "get_running_tolerance",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_nested(obj: dict, key: str):
    """Resolve a dot-separated key path within a dict. Returns None if missing."""
    parts = key.split(".")
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


# ── Device offset resolution — v1.6.5.6 Intraday Timestamp Timezone Bug ────────
#
#  Garmin's raw/live sections carry both a GMT and a Local timestamp for the
#  start and end of the covered period (e.g. startTimestampGMT/Local,
#  endTimestampGMT/Local). The difference is the device's UTC offset for
#  that day — derived from the data itself, no zoneinfo, no system clock.
#
#  If start-offset and end-offset differ, the day crosses a DST transition
#  (see NOTES v1.6.5.6 / A5). This is detected, not corrected — the offset
#  used remains the start-of-day value, consistent with how Garmin itself
#  renders the day (A6).

_OFFSET_SOURCE_SECTIONS = ("heart_rates", "stress", "respiration", "spo2")

# Days already warned about in this process run — _device_offset() is called
# once per intraday field per day, so without this the same day logs the
# same warning repeatedly (once per field reading that day).
_warned_offset_days: set[str] = set()


def _parse_naive(ts: str) -> datetime:
    """Parse a Garmin ISO timestamp string (naive, ignores sub-second digits)."""
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")


def _section_offset(section_data: dict) -> tuple[float, float] | None:
    """
    Compute (start_offset_hours, end_offset_hours) from a section's
    Start/End Timestamp GMT/Local pair. Returns None if either pair is
    missing or malformed.
    """
    s_gmt = section_data.get("startTimestampGMT")
    s_loc = section_data.get("startTimestampLocal")
    e_gmt = section_data.get("endTimestampGMT")
    e_loc = section_data.get("endTimestampLocal")
    if not all(isinstance(x, str) for x in (s_gmt, s_loc, e_gmt, e_loc)):
        return None
    try:
        start_off = (_parse_naive(s_loc) - _parse_naive(s_gmt)).total_seconds() / 3600
        end_off   = (_parse_naive(e_loc) - _parse_naive(e_gmt)).total_seconds() / 3600
        return start_off, end_off
    except ValueError:
        return None


def _device_offset(data: dict) -> tuple[float, bool]:
    """
    Determine the device UTC offset (hours) for a raw/live snapshot day.
    Tries _OFFSET_SOURCE_SECTIONS in fixed order, first complete GMT/Local
    pair wins. Returns (offset_hours, dst_transition) — dst_transition is
    True when start-of-day and end-of-day offset differ (day crosses a
    DST change). Returns (0.0, False) if no section has a usable pair,
    with a warning — never a silent UTC fallback, never an exception.
    """
    for section_name in _OFFSET_SOURCE_SECTIONS:
        section_data = data.get(section_name)
        if not isinstance(section_data, dict):
            continue
        offsets = _section_offset(section_data)
        if offsets is None:
            continue
        start_off, end_off = offsets
        return start_off, (start_off != end_off)
    day = data.get("date") or data.get("calendarDate") or "?"
    if day not in _warned_offset_days:
        _warned_offset_days.add(day)
        log.warning(f"garmin_health_map: no usable GMT/Local offset pair for {day} — defaulting to UTC (0h)")
    return 0.0, False


def _ts_to_iso(ts, offset_hours: float = 0.0) -> str:
    """
    Normalize a Garmin timestamp (ms epoch or ISO string) to ISO-8601,
    shifted by offset_hours (device UTC offset — see _device_offset()).
    Stays naive, without an offset suffix, by design (E9, NOTES v1.6.5.6) —
    downstream Plotly consumers would otherwise re-apply the browser's own
    timezone and reintroduce the offset error at a different layer.
    """
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
        else:
            dt = _parse_naive(str(ts))
        dt += timedelta(hours=offset_hours)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return str(ts)


def _extract_series(arr: list, section_data: dict, extract: dict,
                     offset_hours: float = 0.0) -> list:
    """
    Normalize a raw Garmin array to [{"ts": str, "value": float}, ...].
    Uses the extract descriptor from _FIELD_MAP to handle field-specific
    array structures without leaking Garmin internals to callers.

    offset_hours: device UTC offset for this day (see _device_offset()),
    applied to every timestamp via _ts_to_iso(). Not to be confused with
    `offset` below, which is Garmin's own value-offset (e.g.
    stressChartValueOffset) subtracted from the measurement value.
    """
    offset = 0
    if extract["offset_key"]:
        raw_offset = section_data.get(extract["offset_key"]) or 0
        try:
            offset = float(raw_offset)
        except (TypeError, ValueError):
            offset = 0

    result = []
    for item in arr:
        try:
            if extract["ts_index"] is not None and isinstance(item, (list, tuple)):
                ts  = item[extract["ts_index"]]
                val = item[extract["val_index"]]
            elif isinstance(item, dict):
                ts  = item.get(extract["ts_key"]) or item.get("timestamp")
                val = item.get(extract["val_key"]) or item.get("value")
            else:
                continue
            if val is None:
                continue
            v = float(val) - offset
            if extract["val_min"] is not None and v < extract["val_min"]:
                continue
            result.append({"ts": _ts_to_iso(ts, offset_hours), "value": v})
        except (TypeError, ValueError, IndexError):
            continue
    return result


def _read_raw_pct(field: str, date_from: str, date_to: str) -> dict:
    """
    Read a percentage value from raw/ by dividing seconds_key by total_key.
    For a day whose raw/ file has no usable object (no file, no sleep data, no total) the
    object comes from bulk/aggregates instead (v1.7.6.1) — see _pct_dto(); one source per day.
    Returns {"values": [{"date": str, "value": float|None}, ...], "source_resolution": "daily"}.
    """
    section, dto_key, seconds_key, total_key = _FIELD_MAP[field]["raw_pct"]

    values = []
    for ds in date_range(date_from, date_to):
        value = None
        dto   = _pct_dto(ds, section, dto_key, total_key)
        if dto is not None:
            part = dto.get(seconds_key)
            if _is_number(part):
                value = round(part / dto[total_key] * 100, 1)
        values.append({"date": ds, "value": value})

    return {"values": values, "source_resolution": "daily"}


def _read_daily(field: str, date_from: str, date_to: str) -> dict:
    """
    Read daily values from summary/.
    Returns {"values": [{"date": str, "value": any}, ...], "source_resolution": "daily"}.
    """
    section, key = _FIELD_MAP[field]["daily"]

    values = []
    for ds in date_range(date_from, date_to):
        f = cfg.SUMMARY_DIR / f"{cfg.SUMMARY_FILE_PREFIX}{ds}.json"
        value = None
        if f.exists():
            try:
                data         = json.loads(f.read_text(encoding="utf-8"))
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    value = _get_nested(section_data, key)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_health_map: could not read {f}: {e}")
        values.append({"date": ds, "value": value})

    return {"values": values, "source_resolution": "daily"}


# ── Bulk track for intraday series — v1.7.6 ────────────────────────────────────
#
#  Series fields that have a second track next to the API (raw/): the heart-rate
#  series from the Garmin export, stored in garmin_data/bulk/ (garmin_bulk_writer).
#  For such a field the tracks are tried in this order and the first non-empty
#  series of a day wins, whole — a day is never mixed from two tracks. A field
#  that is not listed reads the API track only. Changing the order is a change
#  in this table and touches no data.
_SERIES_TRACKS = {"heart_rate_series": ("api", "bulk")}

# Where a field's samples are in a bulk day: sections.intraday.<key>.values
_BULK_SERIES_KEY = {"heart_rate_series": "heart_rate"}

# Highest schema_version of a bulk day this reader understands. Must equal
# garmin_bulk_writer.BULK_SCHEMA_VERSION (tests/test_broker.py pins that); a day
# with a higher version is ignored — raise this together with the reader.
_BULK_MAX_SCHEMA = 1

_warned_bulk_days: set[str] = set()


def _bulk_unusable(ds: str, why: str) -> None:
    """One warning per day and process — a damaged bulk day is read once per field and call."""
    if ds not in _warned_bulk_days:
        _warned_bulk_days.add(ds)
        log.warning(f"garmin_health_map: bulk day {ds} not used: {why}")


def _read_bulk_series(field: str, ds: str, extract: dict):
    """
    The series of one day from the bulk store, in the form of an API series
    ([{"ts": str, "value": float}, ...]), shifted by the offset in the head of the
    bulk day (start-of-day offset, as A6 does for the API).

    Returns (series, dst_transition), or None when there is nothing to use: the field
    has no bulk track, no bulk day, a day without samples, or a day that cannot be
    used (damaged, newer schema_version, no numeric offset, no samples section — a
    warning, never an exception, never a guessed offset).
    """
    key = _BULK_SERIES_KEY.get(field)
    if key is None:
        return None
    f = cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{ds}.json"
    if not f.exists():
        return None
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _bulk_unusable(ds, f"cannot be read ({type(e).__name__})")
        return None
    if not isinstance(doc, dict):
        _bulk_unusable(ds, "not a JSON object")
        return None
    version = doc.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= _BULK_MAX_SCHEMA:
        _bulk_unusable(ds, f"schema_version {version!r} is not supported")
        return None
    offset = doc.get("utc_offset_hours")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        _bulk_unusable(ds, "no numeric utc_offset_hours")
        return None
    samples = _get_nested(doc, f"sections.intraday.{key}.values")
    if not isinstance(samples, list):
        _bulk_unusable(ds, "no samples section")
        return None
    series = _extract_series(samples, {}, extract, float(offset))
    if not series:
        return None
    return series, bool(doc.get("dst_transition"))


def _read_api_series(ds: str, section: str, array_key: str, extract: dict):
    """The series of one day from raw/ (API): (series|None, dst_transition). See _read_intraday()."""
    f = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
    series = None
    dst_transition = False
    if f.exists():
        try:
            data         = json.loads(f.read_text(encoding="utf-8"))
            offset_hours, dst_transition = _device_offset(data)
            section_data = data.get(section)
            if isinstance(section_data, dict):
                arr = section_data.get(array_key)
                if isinstance(arr, list):
                    series = _extract_series(arr, section_data, extract, offset_hours)
            elif isinstance(section_data, list):
                series = _extract_series(section_data, {}, extract, offset_hours)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_health_map: could not read {f}: {e}")
    return series, dst_transition


def _read_intraday(field: str, date_from: str, date_to: str) -> dict:
    """
    Read intraday series from raw/ (API) and, for the fields in _SERIES_TRACKS,
    from the bulk store.
    Normalizes each day's array to [{"ts": str, "value": float}, ...],
    timestamps shifted to the device's local time for that day
    (see _device_offset(), NOTES v1.6.5.6).
    Returns {"values": [{"date": str, "series": list|None, "dst_transition": bool,
                         "series_source": "api"|"bulk"|None}, ...],
             "source_resolution": "intraday"}.
    series is None if the file is missing or the field is absent.
    series is [] if the file exists but the array is empty after normalization.
    dst_transition is True if this day's device offset changes between the
    start and end of the covered period — the series is still built using
    the start-of-day offset (A6), the flag only signals the caller that
    this day is affected. Always False when series is None.
    series_source names the track that delivered a non-empty series; None when
    there is none (series None or []). The API track is read first; the bulk
    track only for a day the API has no series for (v1.7.6).
    """
    section, array_key, extract = _FIELD_MAP[field]["intraday"]
    tracks = _SERIES_TRACKS.get(field, ("api",))

    values = []
    for ds in date_range(date_from, date_to):
        series, dst_transition, source = None, False, None
        first = True
        for track in tracks:
            if track == "api":
                found = _read_api_series(ds, section, array_key, extract)
            else:
                found = _read_bulk_series(field, ds, extract) or (None, False)
            if found[0]:
                series, dst_transition = found
                source = track
                break
            if first:
                series, dst_transition = found      # what the first track found stays if no track delivers
            first = False
        values.append({"date": ds, "series": series, "dst_transition": dst_transition, "series_source": source})

    return {"values": values, "source_resolution": "intraday"}


# ── Bulk daily values — v1.7.6.1 ───────────────────────────────────────────────
#
#  Daily values only the Garmin export has (the stress durations) are read from the
#  daily values of the bulk store, garmin_data/bulk/aggregates (garmin_bulk_writer).
#  One file per day; the values are in its "aggregates" object, by section.

# Highest schema_version of an aggregates day this reader understands. Must equal
# garmin_bulk_writer.AGG_SCHEMA_VERSION (tests/test_broker.py pins that); a day with a
# higher version is ignored — raise this together with the reader.
_BULK_AGG_MAX_SCHEMA = 2


def _load_bulk_aggregates(ds: str):
    """
    The "aggregates" object of one day from bulk/aggregates (the export's values, by section).

    None when there is nothing to use: no file, or a day that cannot be used (damaged, not an
    object, newer schema_version, no "aggregates" object — a warning, once per day and
    process, never an exception).
    """
    f = cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{ds}.json"
    if not f.exists():
        return None
    label = f"{ds} (daily values)"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _bulk_unusable(label, f"cannot be read ({type(e).__name__})")
        return None
    if not isinstance(doc, dict):
        _bulk_unusable(label, "not a JSON object")
        return None
    version = doc.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= _BULK_AGG_MAX_SCHEMA:
        _bulk_unusable(label, f"schema_version {version!r} is not supported")
        return None
    aggregates = doc.get("aggregates")
    if not isinstance(aggregates, dict):
        _bulk_unusable(label, "no aggregates object")
        return None
    return aggregates


def _bulk_daily_value(ds: str, section: str, key: str):
    """
    One value of one day from bulk/aggregates: the number at aggregates.<section>.<key>.

    None when there is nothing to use: the day cannot be used (see _load_bulk_aggregates),
    no such section or key, or a value that is not a number (a text, a boolean, null).
    """
    aggregates = _load_bulk_aggregates(ds)
    if aggregates is None:
        return None
    section_data = aggregates.get(section)
    if not isinstance(section_data, dict):
        return None
    value = _get_nested(section_data, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _is_number(value) -> bool:
    """A real number (int or float), not a boolean, a text or None."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pct_dto(ds: str, section: str, dto_key: str, total_key: str):
    """
    The object (e.g. dailySleepDTO) one day's percentage fields are calculated from, taken
    whole from ONE source — the days of the two tracks are never mixed field by field.

    The API track first: raw/ holds the object and its total (total_key) is a number above 0.
    Otherwise, and only then, the same object of the day from bulk/aggregates under the same
    condition (a day the API has no sleep data for, e.g. a fresh install that imported the
    export first). A raw file that cannot be read is a warning, the export is tried then.
    None when neither track has a usable object — as before, the value of the day is None.
    """
    f = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            section_data = data.get(section) if isinstance(data, dict) else None
            dto = section_data.get(dto_key) if isinstance(section_data, dict) else None
            if isinstance(dto, dict) and _is_number(dto.get(total_key)) and dto[total_key] > 0:
                return dto
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_health_map: could not read {f}: {e}")
    aggregates = _load_bulk_aggregates(ds)
    if aggregates is not None:
        section_data = aggregates.get(section)
        dto = section_data.get(dto_key) if isinstance(section_data, dict) else None
        if isinstance(dto, dict) and _is_number(dto.get(total_key)) and dto[total_key] > 0:
            return dto
    return None


def _read_bulk_daily(field: str, date_from: str, date_to: str) -> dict:
    """
    Read daily values from bulk/aggregates, for the fields with a "bulk_daily" descriptor.
    Returns {"values": [{"date": str, "value": number|None}, ...], "source_resolution": "daily"},
    the same form as _read_daily(); value is None for a day without a usable value.
    """
    section, key = _FIELD_MAP[field]["bulk_daily"]
    values = [{"date": ds, "value": _bulk_daily_value(ds, section, key)}
              for ds in date_range(date_from, date_to)]
    return {"values": values, "source_resolution": "daily"}


def _read_live(field: str) -> dict:
    """
    Read an intraday series from the live snapshot (cfg.LIVE_FILE).
    Same array-extraction logic as _read_intraday(), single always-current
    source instead of a dated file — date_from/date_to are not used.
    Timestamps are shifted to the device's local time
    (see _device_offset(), NOTES v1.6.5.6).
    Returns {"values": [{"date": str, "series": list, "dst_transition": bool}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE or missing field in the snapshot → fallback=True,
    empty values, never an exception.
    """
    section, array_key, extract = _FIELD_MAP[field]["live"]

    series = None
    snapshot_date = None
    dst_transition = False
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            offset_hours, dst_transition = _device_offset(data)
            section_data  = data.get(section)
            if isinstance(section_data, dict):
                arr = section_data.get(array_key)
                if isinstance(arr, list):
                    series = _extract_series(arr, section_data, extract, offset_hours)
            elif isinstance(section_data, list):
                series = _extract_series(section_data, {}, extract, offset_hours)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_health_map: could not read {cfg.LIVE_FILE}: {e}")

    if series is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "series": series, "dst_transition": dst_transition}],
        "fallback":          False,
        "source_resolution": "live",
    }


def _read_live_pct(field: str) -> dict:
    """
    Read a percentage value from the live snapshot (cfg.LIVE_FILE) by
    dividing seconds_key by total_key. Same math as _read_raw_pct(), single
    always-current source instead of a dated file.
    Returns {"values": [{"date": str, "value": float}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE, missing section, or total <= 0 → fallback=True,
    empty values, never an exception.
    """
    section, dto_key, seconds_key, total_key = _FIELD_MAP[field]["live_pct"]

    value = None
    snapshot_date = None
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            dto           = data.get(section, {}).get(dto_key, {})
            if isinstance(dto, dict):
                part  = dto.get(seconds_key)
                total = dto.get(total_key)
                if part is not None and total and total > 0:
                    value = round(part / total * 100, 1)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_health_map: could not read {cfg.LIVE_FILE}: {e}")

    if value is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "value": value}],
        "fallback":          False,
        "source_resolution": "live",
    }


def _read_live_nested(field: str) -> dict:
    """
    Read a single nested value from the live snapshot (cfg.LIVE_FILE) via a
    dotted key path, trying each candidate in order until one resolves to a
    non-None value. Uses the existing _get_nested() helper against a fixed
    live source with a fallback chain instead of a single path.

    Candidates are 2-tuples (section, dotted_key) or 3-tuples (section,
    dotted_key, divisor) — divisor divides the raw value before it is
    returned (e.g. sleepTimeSeconds / 3600 → hours). Omit for values used
    as-is.

    Returns {"values": [{"date": str, "value": any}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE or no candidate resolves → fallback=True, empty
    values, never an exception.
    """
    candidates = _FIELD_MAP[field]["live_nested"]

    value = None
    snapshot_date = None
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            for candidate in candidates:
                section, dotted_key = candidate[0], candidate[1]
                divisor = candidate[2] if len(candidate) > 2 else None
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    raw = _get_nested(section_data, dotted_key)
                    if raw is not None:
                        value = round(raw / divisor, 1) if divisor else raw
                        break
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_health_map: could not read {cfg.LIVE_FILE}: {e}")

    if value is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "value": value}],
        "fallback":          False,
        "source_resolution": "live",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — called exclusively by health_map.py
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Resolve a generic field name to Garmin data.

    Args:
        field:       Generic field name (dashboard-side). Must exist in _FIELD_MAP.
        date_from:   Start date ISO string (YYYY-MM-DD), inclusive. Ignored
                     when resolution="live".
        date_to:     End date ISO string (YYYY-MM-DD), inclusive. Ignored
                     when resolution="live".
        resolution:  "daily", "intraday", or "live". Fallback applied if
                     requested "daily"/"intraday" resolution is unavailable
                     for this field. "live" bypasses fallback entirely —
                     single always-current snapshot, no archive equivalent
                     to swap to. See health_map.get()'s own docstring for
                     the same parameter, kept in sync with this one.

    Returns:
        {
            "values":            [...],
            "fallback":          bool,   # True if resolution was downgraded
            "source_resolution": str,    # actual resolution used
        }

    Raises:
        KeyError:   if field is not registered in _FIELD_MAP.
        ValueError: if resolution is not "daily", "intraday", or "live".
    """
    if field not in _FIELD_MAP:
        raise KeyError(f"garmin_health_map: unknown field '{field}'")
    if resolution not in ("daily", "intraday", "live"):
        raise ValueError(f"garmin_health_map: invalid resolution '{resolution}'")

    definition = _FIELD_MAP[field]

    # live fields bypass the daily/intraday fallback logic entirely — single
    # always-current snapshot, date_from/date_to are ignored, no archive
    # equivalent to swap to on a miss. Three live descriptor sub-types,
    # checked in order — a field registers at most one.
    if resolution == "live":
        if definition.get("live") is not None:
            return _read_live(field)
        if definition.get("live_pct") is not None:
            return _read_live_pct(field)
        if definition.get("live_nested") is not None:
            return _read_live_nested(field)
        return {"values": [], "fallback": True, "source_resolution": "live"}

    # raw_pct fields bypass the standard daily/intraday resolution logic
    if definition.get("raw_pct") is not None:
        result = _read_raw_pct(field, date_from, date_to)
        result["fallback"] = False
        return result

    # bulk_daily fields (only in the Garmin export) are daily values from bulk/aggregates;
    # they have no intraday form: an intraday request gets the daily values with
    # fallback=True, like any daily field
    if definition.get("bulk_daily") is not None:
        result = _read_bulk_daily(field, date_from, date_to)
        result["fallback"] = resolution != "daily"
        return result

    requested_available = definition[resolution] is not None

    if requested_available:
        fallback           = False
        actual_resolution  = resolution
    else:
        other = "daily" if resolution == "intraday" else "intraday"
        if definition[other] is not None:
            fallback          = True
            actual_resolution = other
        else:
            # Field registered but no resolution available — should not happen
            return {
                "values":            [],
                "fallback":          False,
                "source_resolution": resolution,
            }

    if actual_resolution == "daily":
        result = _read_daily(field, date_from, date_to)
    else:
        result = _read_intraday(field, date_from, date_to)

    result["fallback"] = fallback
    return result


# Capability-Scan-Kandidaten, die über den Broker sichtbar sind — Zuordnung
# generischer Feldname → Garmin-Capability-Endpoint. Baseline-Felder fehlen
# hier absichtlich (= immer sichtbar, kein Gate). Wächst mit jedem weiteren
# verdrahteten Kandidaten (v1.6.8).
_CAPABILITY_FIELDS = {
    "body_weight":         "get_body_composition",
    "calories_resting":    "get_calories_daily",
    "hydration_ml":        "get_hydration_data",
    "endurance_score":     "get_endurance_score",
    "hill_score":          "get_hill_score",
    "fitness_age":         "get_fitnessage_data",
    "bp_high_systolic":    "get_blood_pressure",
    "bp_high_diastolic":   "get_blood_pressure",
    "bp_low_systolic":     "get_blood_pressure",
    "bp_low_diastolic":    "get_blood_pressure",
    "bp_num_measurements": "get_blood_pressure",
    "bp_category":         "get_blood_pressure",
    # v1.7.1.16 -- same get_calories_daily endpoint calories_resting
    # already gates on; active/total live in the same one-element list
    # response, just previously unregistered (see NOTES_v1.7.1.16.md).
    "calories_active":     "get_calories_daily",
    "calories_total":      "get_calories_daily",
}


def list_fields(active_only: bool = False) -> list[str]:
    """
    Return all registered generic field names.

    active_only=True additionally excludes Capability-Scan candidate fields
    whose endpoint is not enabled_by_user in the capability config — for
    dynamic field pickers (Custom Dashboard, Explorer). Baseline fields are
    never affected — they are absent from _CAPABILITY_FIELDS by design.
    Default False preserves the full registry (e.g. for tests that assert
    a fixed field count).
    """
    fields = list(_FIELD_MAP.keys())
    if not active_only:
        return fields

    config = capability.load_config()
    return [
        f for f in fields
        if f not in _CAPABILITY_FIELDS
        or config.get("endpoints", {}).get(_CAPABILITY_FIELDS[f], {}).get("enabled_by_user")
    ]


def list_raw_fields() -> list[str]:
    """Return all registered raw-passthrough field names."""
    return list(_RAW_PASSTHROUGH_FIELDS.keys())


def get_raw(field: str, date_from: str, date_to: str) -> dict:
    """
    Return the archived raw/ entry for a Capability-Scan endpoint,
    without interpretation. raw/ is the normalized silo, but for
    API-fetched days the normalizer passes endpoint payloads through
    unchanged, so this is the endpoint response as Garmin delivered it.
    Unlike get(), there is no "value" extraction — the caller is
    responsible for interpreting it. See REFERENCE_BROKER.md
    "Raw-Passthrough-Felder" for the rationale.

    Args:
        field:      Generic raw-field name. Must exist in _RAW_PASSTHROUGH_FIELDS.
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.

    Returns:
        {"values": [{"date": str, "raw": any|None}, ...], "source_resolution": "raw"}
        raw is None if the day's raw/ file is missing or does not contain
        this endpoint's key.

    Raises:
        KeyError: if field is not registered in _RAW_PASSTHROUGH_FIELDS.
    """
    if field not in _RAW_PASSTHROUGH_FIELDS:
        raise KeyError(f"garmin_health_map: unknown raw field '{field}'")
    endpoint = _RAW_PASSTHROUGH_FIELDS[field]

    values = []
    for ds in date_range(date_from, date_to):
        f = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
        payload = None
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                payload = data.get(endpoint)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_health_map: could not read {f}: {e}")
        values.append({"date": ds, "raw": payload})

    return {"values": values, "source_resolution": "raw"}
