#!/usr/bin/env python3
"""
sleep_recovery_context_dash.py

Specialist: Sleep & Recovery Context dashboard.
Metrics: HRV, Body Battery, Sleep (daily) + sleep phase composition
         + temperature and pollen context.
Intraday: Heart Rate, Stress, Body Battery, Respiration (per day, Tab 2).

Sources:
  - Garmin summary/ via field_map  (HRV, Body Battery, Sleep duration)
  - Garmin raw/     via field_map  (sleep phases: Deep, Light, REM, Awake)
  - Garmin raw/     via field_map  (intraday HR, Stress, Body Battery, Respiration)
  - context_data/   via context_map (temperature, pollen)

Rules:
- No direct file access.
- No source-internal field names outside this module.
- Calls field_map.get() and context_map.get() only.
- Returns neutral dict for plotters — no rendering logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map   import get as field_get
from maps.context_map import get as context_get

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Sleep & Recovery",
    "description": "HRV, Body Battery, Sleep — with sleep phase breakdown and weather/pollen context",
    "source":      "Garmin raw/ + summary/ + context_data/",
    "formats": {
        "html_complex": "sleep_recovery_context.html",
    },
}

# ── Daily Garmin fields ───────────────────────────────────────────────────────

_DAILY_FIELDS = [
    {"field": "hrv_last_night",  "key": "hrv"},
    {"field": "body_battery_max","key": "body_battery"},
    {"field": "sleep_duration",  "key": "sleep_h"},
]

# ── Sleep phase fields (raw/, computed as %) ──────────────────────────────────

_PHASE_FIELDS = [
    {"field": "sleep_deep_pct",  "key": "deep"},
    {"field": "sleep_light_pct", "key": "light"},
    {"field": "sleep_rem_pct",   "key": "rem"},
    {"field": "sleep_awake_pct", "key": "awake"},
]

# ── Intraday Garmin fields ────────────────────────────────────────────────────

_INTRADAY_FIELDS = [
    {"field": "heart_rate_series",   "key": "heart_rate"},
    {"field": "stress_series",       "key": "stress"},
    {"field": "body_battery_series", "key": "body_battery"},
    {"field": "respiration_series",  "key": "respiration"},
]

# ── Context fields ────────────────────────────────────────────────────────────

_CONTEXT_FIELDS = [
    {"field": "temperature_max", "key": "temperature"},
    {"field": "pollen_birch",    "key": "pollen"},
]


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _values_by_date(result: dict) -> dict:
    """Extract {date: value} from a field_map result (garmin source)."""
    garmin = result.get("garmin", {})
    return {
        entry["date"]: entry["value"]
        for entry in garmin.get("values", [])
    }


def _context_by_date(result: dict) -> dict:
    """Extract {date: value} from a context_map result (first available source)."""
    source = next(iter(result.values()), {}) if result else {}
    return {
        entry["date"]: entry["value"]
        for entry in source.get("values", [])
    }


def _intraday_by_date(result: dict) -> dict:
    """Extract {date: series} from a field_map intraday result."""
    garmin = result.get("garmin", {})
    return {
        entry["date"]: entry.get("series")
        for entry in garmin.get("values", [])
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch all fields via field_map and context_map.
    Returns neutral dict for dash_plotter_html_complex.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI (unused here, reserved).

    Returns:
        {
            "title":    str,
            "subtitle": str,
            "date_from": str,
            "date_to":   str,

            "daily": {
                "dates":        [str, ...],
                "hrv":          [float|None, ...],
                "body_battery": [float|None, ...],
                "sleep_h":      [float|None, ...],
                "temperature":  [float|None, ...],
                "pollen":       [float|None, ...],
                "sleep_phases": [
                    {"date": str, "deep": float|None, "light": float|None,
                     "rem": float|None, "awake": float|None},
                    ...
                ],
            },

            "intraday": {
                "YYYY-MM-DD": {
                    "heart_rate":   [{"ts": str, "value": float}, ...] | None,
                    "stress":       [{"ts": str, "value": float}, ...] | None,
                    "body_battery": [{"ts": str, "value": float}, ...] | None,
                    "respiration":  [{"ts": str, "value": float}, ...] | None,
                    "temperature":  float|None,
                    "pollen":       float|None,
                },
                ...
            },
        }
    """

    # ── Fetch daily Garmin fields ─────────────────────────────────────────────
    daily_raw = {}
    for f in _DAILY_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        daily_raw[f["key"]] = _values_by_date(result)

    # ── Fetch sleep phase fields ──────────────────────────────────────────────
    phase_raw = {}
    for f in _PHASE_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        phase_raw[f["key"]] = _values_by_date(result)

    # ── Fetch context fields ──────────────────────────────────────────────────
    context_raw = {}
    for f in _CONTEXT_FIELDS:
        result = context_get(f["field"], date_from, date_to)
        context_raw[f["key"]] = _context_by_date(result)

    # ── Fetch intraday fields ─────────────────────────────────────────────────
    intraday_raw = {}
    for f in _INTRADAY_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="intraday")
        intraday_raw[f["key"]] = _intraday_by_date(result)

    # ── Collect all dates from daily data ─────────────────────────────────────
    all_dates = sorted(set(
        d
        for src in list(daily_raw.values()) + list(phase_raw.values()) + list(context_raw.values())
        for d in src.keys()
    ))

    # ── Build daily output ────────────────────────────────────────────────────
    daily_out = {
        "dates":        all_dates,
        "hrv":          [daily_raw["hrv"].get(d)          for d in all_dates],
        "body_battery": [daily_raw["body_battery"].get(d) for d in all_dates],
        "sleep_h":      [daily_raw["sleep_h"].get(d)      for d in all_dates],
        "temperature":  [context_raw["temperature"].get(d) for d in all_dates],
        "pollen":       [context_raw["pollen"].get(d)      for d in all_dates],
        "sleep_phases": [
            {
                "date":  d,
                "deep":  phase_raw["deep"].get(d),
                "light": phase_raw["light"].get(d),
                "rem":   phase_raw["rem"].get(d),
                "awake": phase_raw["awake"].get(d),
            }
            for d in all_dates
        ],
    }

    # ── Build intraday output — only dates with at least one data series ──────
    intraday_out = {}
    for d in all_dates:
        day = {
            "heart_rate":   intraday_raw["heart_rate"].get(d),
            "stress":       intraday_raw["stress"].get(d),
            "body_battery": intraday_raw["body_battery"].get(d),
            "respiration":  intraday_raw["respiration"].get(d),
            "temperature":  context_raw["temperature"].get(d),
            "pollen":       context_raw["pollen"].get(d),
        }
        has_data = any(
            day[k] is not None and len(day[k]) > 0
            for k in ("heart_rate", "stress", "body_battery", "respiration")
        )
        if has_data:
            intraday_out[d] = day
    return {
        "title":    "Sleep & Recovery Context",
        "subtitle": f"{date_from} \u2192 {date_to} \u00b7 HRV \u00b7 Body Battery \u00b7 Sleep phases \u00b7 Context",
        "date_from": date_from,
        "date_to":   date_to,
        "daily":    daily_out,
        "intraday": intraday_out,
    }
