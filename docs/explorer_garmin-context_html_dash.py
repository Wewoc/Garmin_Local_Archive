#!/usr/bin/env python3
"""
explorer_garmin-context_html_dash.py

Specialist: Explorer Dashboard — free metric exploration across all Garmin
daily fields and context sources (weather, pollen, air quality).

Page 1 (Summary):
  - 4 freely selectable metric dropdowns → line traces, shared X-axis
  - Each selected metric gets its own Y-axis (label + unit from dash_layout)
  - Fixed lower panel: stacked sleep phase bars (Deep/Light/REM/Awake)
  - Sleep score labels: vertical text trace per day inside sleep phase panel

Sources:
  - Garmin summary/ via field_map  (all daily Garmin fields)
  - Garmin raw/     via field_map  (sleep phases)
  - context_data/   via context_map (weather, pollen, air quality)

Rules:
- No direct file access.
- Calls field_map.get() and context_map.get() only.
- Returns neutral dict for dash_plotter_html_complex ("layout": "explorer").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map    import get as field_get, list_fields as garmin_list_fields
from maps.context_map  import get as context_get, list_fields as context_list_fields
from layouts.dash_layout import get_metric_meta

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Explorer",
    "description": "Free metric exploration — all Garmin + context fields, daily and intraday",
    "source":      "Garmin raw/ + summary/ + context_data/",
    "formats": {
        "html_complex": "explorer_garmin_context.html",
    },
}

# ── Sleep phase fields ────────────────────────────────────────────────────────

_PHASE_FIELDS = [
    {"field": "sleep_deep_pct",  "key": "deep"},
    {"field": "sleep_light_pct", "key": "light"},
    {"field": "sleep_rem_pct",   "key": "rem"},
    {"field": "sleep_awake_pct", "key": "awake"},
]

# ── Context sources ───────────────────────────────────────────────────────────

_CONTEXT_SOURCES = ["weather", "pollen", "airquality"]

# ── Fields excluded from daily dropdowns (categorical or phase-only) ──────────

_EXCLUDE_FROM_DAILY = {
    "sleep_score_feedback",
    "sleep_score_qualifier",
    "sleep_deep_pct",
    "sleep_light_pct",
    "sleep_rem_pct",
    "sleep_awake_pct",
}

_SERIES_SUFFIX = "_series"


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _values_by_date(result: dict, source_key: str = "garmin") -> dict:
    src = result.get(source_key, {})
    return {entry["date"]: entry["value"] for entry in src.get("values", [])}


def _context_by_date(result: dict) -> dict:
    source = next(iter(result.values()), {}) if result else {}
    return {entry["date"]: entry["value"] for entry in source.get("values", [])}


def _build_field_options(fields: list) -> list:
    options = []
    for f in fields:
        meta  = get_metric_meta(f)
        label = meta.get("label") or f
        unit  = meta.get("unit", "")
        options.append({"field": f, "label": label, "unit": unit})
    return options


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch all fields via field_map and context_map.
    Returns neutral dict for dash_plotter_html_complex with layout="explorer".

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI.

    Returns:
        {
            "layout":  "explorer",
            "title":   str,
            "subtitle": str,
            "daily": {
                "dates":         [str, ...],
                "field_options": [{"field": str, "label": str, "unit": str}, ...],
                "series":        {field: [value|None, ...]},
                "sleep_phases":  [{"date": str, "deep": float|None, ...}, ...],
                "sleep_scores":  [{"date": str, "feedback": str|None,
                                   "qualifier": str|None}, ...],
            },
            "intraday": {},
        }
    """

    # ── 1. Identify daily fields for dropdowns ────────────────────────────────
    all_garmin = garmin_list_fields()
    daily_garmin_fields = [
        f for f in all_garmin
        if not f.endswith(_SERIES_SUFFIX) and f not in _EXCLUDE_FROM_DAILY
    ]

    context_fields = []
    for src in _CONTEXT_SOURCES:
        context_fields.extend(context_list_fields(src))

    all_daily_fields = daily_garmin_fields + context_fields

    # ── 2. Fetch all daily series ─────────────────────────────────────────────
    daily_series: dict = {}

    for f in daily_garmin_fields:
        result = field_get(f, date_from, date_to, resolution="daily")
        daily_series[f] = _values_by_date(result, "garmin")

    for f in context_fields:
        result = context_get(f, date_from, date_to)
        daily_series[f] = _context_by_date(result)

    # ── 3. Collect all dates ──────────────────────────────────────────────────
    all_dates = sorted(set(
        d for src in daily_series.values() for d in src.keys()
    ))

    # ── 4. Fetch sleep phase fields ───────────────────────────────────────────
    phase_raw: dict = {}
    for f in _PHASE_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        phase_raw[f["key"]] = _values_by_date(result, "garmin")

    # ── 5. Fetch sleep score fields ───────────────────────────────────────────
    r_fb = field_get("sleep_score_feedback",  date_from, date_to, resolution="daily")
    r_qq = field_get("sleep_score_qualifier", date_from, date_to, resolution="daily")
    score_feedback_by_date  = _values_by_date(r_fb, "garmin")
    score_qualifier_by_date = _values_by_date(r_qq, "garmin")

    # ── 6. Build daily output ─────────────────────────────────────────────────
    daily_out = {
        "dates":        all_dates,
        "field_options": _build_field_options(all_daily_fields),
        "series": {
            f: [daily_series[f].get(d) for d in all_dates]
            for f in all_daily_fields
        },
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
        "sleep_scores": [
            {
                "date":      d,
                "feedback":  score_feedback_by_date.get(d),
                "qualifier": score_qualifier_by_date.get(d),
            }
            for d in all_dates
        ],
    }

    # ── 7. Subtitle ───────────────────────────────────────────────────────────
    subtitle = (
        f"{date_from} \u2192 {date_to} · "
        f"{len(daily_garmin_fields)} Garmin fields · "
        f"{len(context_fields)} context fields"
    )

    return {
        "layout":    "explorer",
        "title":     "Explorer",
        "subtitle":  subtitle,
        "date_from": date_from,
        "date_to":   date_to,
        "daily":     daily_out,
        "intraday":  {},
    }
