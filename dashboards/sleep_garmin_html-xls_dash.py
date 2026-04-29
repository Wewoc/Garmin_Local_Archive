#!/usr/bin/env python3
"""
sleep_garmin_html-xls_dash.py

Specialist: Sleep Dashboard — one row per night.
Metrics: Sleep phases (segmented bar), duration, score, quality badge,
         feedback text, HRV, Body Battery.

Layout: "sleep" — rendered by dash_plotter_html_complex (_render_sleep)
        and dash_plotter_excel (_render_sleep_excel).

Sources:
  - Garmin summary/ via field_map (all fields daily)
  - Garmin raw/     via field_map (sleep phase % from raw seconds)

Rules:
- No direct file access.
- No source-internal field names outside this module.
- Calls field_map.get() only.
- Returns neutral dict for plotters — no rendering logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map import get as field_get
from layouts.reference_ranges import fitness_level as _fitness_level
from layouts.reference_ranges import reference_ranges as _reference_ranges

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Sleep Dashboard",
    "description": "One row per night — phases, duration, score, quality, HRV, Body Battery",
    "source":      "Garmin raw/ + summary/",
    "formats": {
        "html_complex": "sleep_dashboard.html",
        "excel":        "sleep_dashboard.xlsx",
    },
}

# ── Daily fields (summary/) ───────────────────────────────────────────────────

_DAILY_FIELDS = [
    {"field": "sleep_duration",       "key": "duration_h"},
    {"field": "sleep_score",          "key": "score"},
    {"field": "sleep_score_qualifier","key": "qualifier"},
    {"field": "sleep_score_feedback", "key": "feedback"},
    {"field": "hrv_last_night",       "key": "hrv"},
    {"field": "body_battery_max",     "key": "body_battery"},
]

# ── Sleep phase fields (raw/, computed as %) ──────────────────────────────────

_PHASE_FIELDS = [
    {"field": "sleep_deep_pct",  "key": "deep"},
    {"field": "sleep_light_pct", "key": "light"},
    {"field": "sleep_rem_pct",   "key": "rem"},
    {"field": "sleep_awake_pct", "key": "awake"},
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


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch all fields via field_map.
    Returns neutral dict for dash_plotter_html_complex and dash_plotter_excel.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI — reads age, sex, vo2max.

    Returns:
        {
            "layout":    "sleep",
            "title":     str,
            "subtitle":  str,
            "date_from": str,
            "date_to":   str,
            "refs": {
                "hrv_last_night":   (low, high),
                "sleep_duration":   (low, high),
                "body_battery_max": (low, high),
            },
            "rows": [
                {
                    "date":       str,
                    "deep":       float|None,   # %
                    "light":      float|None,   # %
                    "rem":        float|None,   # %
                    "awake":      float|None,   # %
                    "duration_h": float|None,
                    "score":      float|None,
                    "qualifier":  str|None,     # "EXCELLENT"|"GOOD"|"FAIR"|"POOR"
                    "feedback":   str|None,     # e.g. "NEGATIVE_LONG_BUT_NOT_ENOUGH_REM"
                    "hrv":        float|None,
                    "body_battery": float|None,
                },
                ...
            ],
        }
    """

    # ── Profile + reference ranges ────────────────────────────────────────────
    try:
        age = int(float(settings.get("age") or 35))
    except (TypeError, ValueError):
        age = 35
    sex    = settings.get("sex") or "male"
    vo2max = None
    result_vo2 = field_get("vo2max", date_from, date_to, resolution="daily")
    for entry in reversed(result_vo2.get("garmin", {}).get("values", [])):
        if entry["value"] is not None:
            vo2max = entry["value"]
            break
    fitness = _fitness_level(age, sex, vo2max) if vo2max is not None else "average"
    refs    = _reference_ranges(age, sex, fitness)

    # ── Fetch daily fields ────────────────────────────────────────────────────
    daily_raw = {}
    for f in _DAILY_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        daily_raw[f["key"]] = _values_by_date(result)

    # ── Fetch phase fields ────────────────────────────────────────────────────
    phase_raw = {}
    for f in _PHASE_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        phase_raw[f["key"]] = _values_by_date(result)

    # ── Collect dates ─────────────────────────────────────────────────────────
    all_dates = sorted(set(
        d
        for src in list(daily_raw.values()) + list(phase_raw.values())
        for d in src.keys()
    ))

    # ── Auto-size ─────────────────────────────────────────────────────────────
    garmin_dates = set(
        d
        for src in list(daily_raw.values()) + list(phase_raw.values())
        for d, v in src.items()
        if v is not None
    )

    adjusted_from = date_from if (garmin_dates and min(garmin_dates) > date_from) else None
    adjusted_to   = date_to   if (garmin_dates and max(garmin_dates) < date_to)   else None

    subtitle = f"{date_from} \u2192 {date_to} \u00b7 Sleep \u00b7 HRV \u00b7 Body Battery"
    if adjusted_from or adjusted_to:
        actual_first = min(garmin_dates)
        actual_last  = max(garmin_dates)
        subtitle = (
            f"{actual_first} \u2192 {actual_last}"
            f" \u00b7 Sleep \u00b7 HRV \u00b7 Body Battery"
            f" \u00b7 adjusted to available data"
            f" (requested: {adjusted_from or date_from} \u2192 {adjusted_to or date_to})"
        )

    # ── Build rows ────────────────────────────────────────────────────────────
    rows = [
        {
            "date":         d,
            "deep":         phase_raw["deep"].get(d),
            "light":        phase_raw["light"].get(d),
            "rem":          phase_raw["rem"].get(d),
            "awake":        phase_raw["awake"].get(d),
            "duration_h":   daily_raw["duration_h"].get(d),
            "score":        daily_raw["score"].get(d),
            "qualifier":    daily_raw["qualifier"].get(d),
            "feedback":     daily_raw["feedback"].get(d),
            "hrv":          daily_raw["hrv"].get(d),
            "body_battery": daily_raw["body_battery"].get(d),
        }
        for d in reversed(all_dates)
    ]

    return {
        "layout":    "sleep",
        "title":     "Sleep Dashboard",
        "subtitle":  subtitle,
        "date_from": date_from,
        "date_to":   date_to,
        "refs": {
            "hrv_last_night":   refs["hrv_last_night"],
            "sleep_duration":   refs["sleep_duration"],
            "body_battery_max": refs["body_battery_max"],
        },
        "rows": rows,
    }