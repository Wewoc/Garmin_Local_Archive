#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
sleep_recovery_context_dash.py

Specialist: Sleep & Recovery Context dashboard.
Metrics: HRV, Body Battery, Sleep (daily) + sleep phase composition
         + temperature and pollen context.
Intraday: Heart Rate, Stress, Body Battery, Respiration (per day, Tab 2).

Sources:
  - Garmin summary/ via health_map  (HRV, Body Battery, Sleep duration)
  - Garmin raw/     via health_map  (sleep phases: Deep, Light, REM, Awake)
  - Garmin raw/     via health_map  (intraday HR, Stress, Body Battery, Respiration)
  - context_data/   via context_map (temperature, pollen)

Rules:
- No direct file access.
- No source-internal field names outside this module.
- Calls health_map.get() and context_map.get() only.
- Returns neutral dict for plotters — no rendering logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.health_map   import get as health_get
from maps.context_map import get as context_get
from layouts.reference_ranges import fitness_level as _fitness_level
from layouts.reference_ranges import reference_ranges as _reference_ranges
from layouts.dash_autosize import compute_autosize_bounds, autosize_note
from layouts.dash_intraday import INTRADAY_FIELDS, intraday_by_date, build_intraday

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

# ── Context fields ────────────────────────────────────────────────────────────

_CONTEXT_FIELDS = [
    {"field": "temperature_max", "key": "temperature"},
    {"field": "pollen_birch",    "key": "pollen"},
]


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _values_by_date(result: dict) -> dict:
    """Extract {date: value} from a health_map result (garmin source)."""
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


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch all fields via health_map and context_map.
    Returns neutral dict for dash_plotter_html_complex.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI — reads age, sex, vo2max.

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

    # ── Profile + reference ranges ────────────────────────────────────────────
    try:
        age = int(float(settings.get("age") or 35))
    except (TypeError, ValueError):
        age = 35
    sex     = settings.get("sex") or "male"
    vo2max  = None
    result_vo2 = health_get("vo2max", date_from, date_to, resolution="daily")
    for entry in reversed(result_vo2.get("garmin", {}).get("values", [])):
        if entry["value"] is not None:
            vo2max = entry["value"]
            break
    fitness = _fitness_level(age, sex, vo2max) if vo2max is not None else "average"
    refs    = _reference_ranges(age, sex, fitness)

    # ── Fetch daily Garmin fields ─────────────────────────────────────────────
    daily_raw = {}
    for f in _DAILY_FIELDS:
        result = health_get(f["field"], date_from, date_to, resolution="daily")
        daily_raw[f["key"]] = _values_by_date(result)

    # ── Fetch sleep phase fields ──────────────────────────────────────────────
    phase_raw = {}
    for f in _PHASE_FIELDS:
        result = health_get(f["field"], date_from, date_to, resolution="daily")
        phase_raw[f["key"]] = _values_by_date(result)

    # ── Fetch context fields ──────────────────────────────────────────────────
    context_raw = {}
    for f in _CONTEXT_FIELDS:
        result = context_get(f["field"], date_from, date_to)
        context_raw[f["key"]] = _context_by_date(result)

    # ── Fetch intraday fields ─────────────────────────────────────────────────
    intraday_raw = {}
    for f in INTRADAY_FIELDS:
        result = health_get(f["field"], date_from, date_to, resolution="intraday")
        intraday_raw[f["key"]] = intraday_by_date(result)

    # ── Collect all dates from daily data ─────────────────────────────────────
    all_dates = sorted(set(
        d
        for src in list(daily_raw.values()) + list(phase_raw.values()) + list(context_raw.values())
        for d in src.keys()
    ))

    # ── Status per day — for flagged marker in plotter ────────────────────────
    ref_hrv_low,  ref_hrv_high  = refs["hrv_last_night"]
    ref_bb_low,   ref_bb_high   = refs["body_battery_max"]
    ref_slp_low,  ref_slp_high  = refs["sleep_duration"]

    def _status_hrv(v):
        if v is None: return None
        return "low" if v < ref_hrv_low else "ok"

    def _status_bb(v):
        if v is None: return None
        return "low" if v < ref_bb_low else "ok"

    def _status_sleep(v):
        if v is None or v == 0.0: return None
        return "low" if v < ref_slp_low else "high" if v > ref_slp_high else "ok"

    # ── Build daily output ────────────────────────────────────────────────────
    daily_out = {
        "dates":        all_dates,
        "hrv":          [daily_raw["hrv"].get(d)          for d in all_dates],
        "body_battery": [daily_raw["body_battery"].get(d) for d in all_dates],
        "sleep_h":      [daily_raw["sleep_h"].get(d)      for d in all_dates],
        "temperature":  [context_raw["temperature"].get(d) for d in all_dates],
        "pollen":       [context_raw["pollen"].get(d)      for d in all_dates],
        "hrv_status":          [_status_hrv(daily_raw["hrv"].get(d))          for d in all_dates],
        "body_battery_status": [_status_bb(daily_raw["body_battery"].get(d))  for d in all_dates],
        "sleep_status":        [_status_sleep(daily_raw["sleep_h"].get(d))    for d in all_dates],
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
    # The four series and the day filter are layouts/dash_intraday.py (shared with Sleep and Explorer);
    # the two context values are added after them, so the keys of a day keep their order.
    intraday_out = build_intraday(intraday_raw, all_dates)
    for d, day in intraday_out.items():
        day["temperature"] = context_raw["temperature"].get(d)
        day["pollen"]      = context_raw["pollen"].get(d)
    # Auto-size: determine actual data boundaries from Garmin fields only
    garmin_dates = set(
        d
        for src in list(daily_raw.values()) + list(phase_raw.values())
        for d, v in src.items()
        if v is not None
    )

    _bounds = compute_autosize_bounds(garmin_dates, date_from, date_to)
    _note   = autosize_note(_bounds, date_from, date_to)
    if _note:
        subtitle = f"{_bounds['actual_first']} \u2192 {_bounds['actual_last']} \u00b7 HRV \u00b7 Body Battery \u00b7 Sleep phases \u00b7 Context{_note}"
    else:
        subtitle = f"{date_from} \u2192 {date_to} \u00b7 HRV \u00b7 Body Battery \u00b7 Sleep phases \u00b7 Context"

    return {
        "title":    "Sleep & Recovery Context",
        "subtitle": subtitle,
        "date_from": date_from,
        "date_to":   date_to,
        "daily":    daily_out,
        "intraday": intraday_out,
    }
