#!/usr/bin/env python3
"""
health_garmin_html-json_dash.py

Specialist: Garmin daily health analysis.
Metrics: HRV, Resting HR, SpO2, Sleep, Body Battery, Stress.
Source: garmin_data/summary/ via field_map.

Provides:
- Daily values with 90-day rolling baseline
- Age/sex/fitness-adjusted reference ranges
- Flagged days (outside reference range)

Rules:
- No direct file access.
- No Garmin-internal field names outside this module.
- Calls field_map.get() only.
- Returns neutral dict for plotters — no rendering logic.
"""

import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map import get as field_get
from layouts.reference_ranges import fitness_level as _fitness_level
from layouts.reference_ranges import reference_ranges as _reference_ranges

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Health Analysis",
    "description": "HRV, Resting HR, SpO2, Sleep, Body Battery, Stress — baseline + reference ranges",
    "source":      "Garmin summary/",
    "formats": {
        "html":        "health_garmin.html",
        "json":        "health_garmin.json",
        "html_mobile": "health_garmin_mobile.html",
    },
}

BASELINE_DAYS = 90

# Field definitions — generic field key + display metadata
_FIELDS = [
    {"field": "hrv_last_night",    "label": "HRV",          "unit": "ms",    "higher_better": True},
    {"field": "resting_heart_rate","label": "Resting HR",   "unit": "bpm",   "higher_better": False},
    {"field": "spo2_avg",          "label": "SpO2",         "unit": "%",     "higher_better": True},
    {"field": "sleep_duration",    "label": "Sleep",        "unit": "h",     "higher_better": None},
    {"field": "body_battery_max",  "label": "Body Battery", "unit": "level", "higher_better": True},
    {"field": "stress_avg",        "label": "Stress",       "unit": "level", "higher_better": False},
]

# ══════════════════════════════════════════════════════════════════════════════
#  Rolling baseline
# ══════════════════════════════════════════════════════════════════════════════

def _rolling_avg(values: dict, d: date, window: int) -> float | None:
    nums = [
        v for i in range(1, window + 1)
        if (v := values.get((d - timedelta(days=i)).isoformat())) is not None
    ]
    return round(statistics.mean(nums), 2) if nums else None


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch daily health metrics via field_map.
    Computes 90-day rolling baseline and reference ranges.
    Returns neutral dict for plotters.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI — reads age, sex.

    Returns:
        {
            "title":          str,
            "subtitle":       str,
            "date_from":      str,
            "date_to":        str,
            "prompt_template": str,
            "profile":        {"age": int, "sex": str, "vo2max": float|None, "fitness": str},
            "fields": [
                {
                    "field":         str,
                    "label":         str,
                    "unit":          str,
                    "higher_better": bool|None,
                    "period_avg":    float|None,
                    "baseline_avg":  float|None,
                    "ref_low":       float,
                    "ref_high":      float,
                    "flagged_days":  int,
                    "flagged_dates": [str, ...],
                    "days": [
                        {"date": str, "value": float|None,
                         "baseline": float|None, "status": str|None},
                        ...
                    ],
                },
                ...
            ],
        }
    """
    age = int(settings.get("age") or 35)
    sex = settings.get("sex") or "male"

    # Extend window back for baseline calculation
    d_from    = date.fromisoformat(date_from)
    d_to      = date.fromisoformat(date_to)
    base_from = (d_from - timedelta(days=BASELINE_DAYS + 30)).isoformat()

    # Fetch all fields — extended window for baseline
    raw = {}
    for f in _FIELDS:
        result = field_get(f["field"], base_from, date_to, resolution="daily")
        garmin = result.get("garmin", {})
        raw[f["field"]] = {
            entry["date"]: entry["value"]
            for entry in garmin.get("values", [])
        }

    # Auto-detect VO2max from most recent non-null value
    vo2max  = None
    vo2_raw = raw.get("vo2max", {})  # not in _FIELDS but fetched separately below
    result_vo2 = field_get("vo2max", base_from, date_to, resolution="daily")
    for entry in reversed(result_vo2.get("garmin", {}).get("values", [])):
        if entry["value"] is not None:
            vo2max = entry["value"]
            break

    fitness = _fitness_level(age, sex, vo2max) if vo2max is not None else "average"
    refs    = _reference_ranges(age, sex, fitness)

    # Auto-size: determine actual data boundaries across all fields
    all_dates_with_data = set()
    for field_values in raw.values():
        for ds, v in field_values.items():
            if v is not None and ds >= date_from and ds <= date_to:
                all_dates_with_data.add(ds)

    adjusted_from = None
    adjusted_to   = None
    if all_dates_with_data:
        actual_first = min(all_dates_with_data)
        actual_last  = max(all_dates_with_data)
        if actual_first > date_from:
            adjusted_from = date_from
            d_from        = date.fromisoformat(actual_first)
        if actual_last < date_to:
            adjusted_to = date_to
            d_to        = date.fromisoformat(actual_last)

    # Build display date range
    display_dates = [
        (d_from + timedelta(days=i)).isoformat()
        for i in range((d_to - d_from).days + 1)
    ]
    fields_out = []
    for f in _FIELDS:
        field        = f["field"]
        values       = raw[field]
        ref_low, ref_high = refs[field]
        higher_better = f["higher_better"]

        days      = []
        all_vals  = []
        all_bases = []
        flagged   = []

        for ds in display_dates:
            val      = values.get(ds)
            # sleep_duration: 0.0 means no sleep recorded — treat as missing
            if field == "sleep_duration" and val == 0.0:
                val = None
            baseline = _rolling_avg(values, date.fromisoformat(ds), BASELINE_DAYS)
            status   = None
            if val is not None:
                if higher_better is True:
                    status = "low" if val < ref_low else "ok"
                elif higher_better is False:
                    status = "high" if val > ref_high else "ok"
                else:
                    status = "low" if val < ref_low else "high" if val > ref_high else "ok"
                if status in ("low", "high"):
                    flagged.append(ds)
            if val is not None:
                all_vals.append(val)
            if baseline is not None:
                all_bases.append(baseline)
            days.append({"date": ds, "value": val, "baseline": baseline, "status": status})

        fields_out.append({
            "field":         field,
            "label":         f["label"],
            "unit":          f["unit"],
            "higher_better": higher_better,
            "period_avg":    round(statistics.mean(all_vals),  2) if all_vals  else None,
            "baseline_avg":  round(statistics.mean(all_bases), 2) if all_bases else None,
            "ref_low":       ref_low,
            "ref_high":      ref_high,
            "flagged_days":  len(flagged),
            "flagged_dates": flagged[-5:],
            "days":          days,
        })

    return {
        "title":           "Garmin Health Analysis",
        "subtitle":        (
            f"{d_from.isoformat()} \u2192 {d_to.isoformat()} \u00b7 90-day baseline \u00b7 Age/fitness-adjusted ranges"
            + (f" \u00b7 adjusted to available data (requested: {adjusted_from} \u2192 {adjusted_to or date_to})" if adjusted_from or adjusted_to else "")
        ),
        "date_from":       date_from,
        "date_to":         date_to,
        "prompt_template": "health_analysis",
        "profile":         {"age": age, "sex": sex, "vo2max": vo2max, "fitness": fitness},
        "baseline_note":   f"Dashed line = personal {BASELINE_DAYS}-day rolling average (prior to display period).",
        "fields":          fields_out,
    }