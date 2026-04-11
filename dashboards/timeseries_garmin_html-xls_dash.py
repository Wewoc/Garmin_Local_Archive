#!/usr/bin/env python3
"""
timeseries_garmin_html-xls_dash.py

Specialist: Garmin intraday timeseries.
Metrics: Heart Rate, Stress, SpO2, Body Battery, Respiration.
Source: garmin_data/raw/ via field_map.

Rules:
- No direct file access.
- No Garmin-internal field names outside this module.
- Calls field_map.get() only — no knowledge of raw/ structure.
- Returns neutral dict for plotters — no rendering logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map import get as field_get

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Timeseries",
    "description": "Intraday heart rate, stress, SpO2, body battery, respiration",
    "source":      "Garmin raw/",
    "formats": {
        "html":  "timeseries_garmin.html",
        "excel": "timeseries_garmin.xlsx",
    },
}

_FIELDS = [
    "heart_rate_series",
    "stress_series",
    "spo2_series",
    "body_battery_series",
    "respiration_series",
]

# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch intraday data for all fields via field_map.
    Returns neutral dict for plotters.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI (unused here, reserved).

    Returns:
        {
            "title":    str,
            "subtitle": str,
            "fields": [
                {
                    "field":  str,           # generic field key
                    "series": list[dict],    # [{"ts": str, "value": float}, ...]
                                             # None if data unavailable
                },
                ...
            ],
        }
    """
    fields = []
    for field in _FIELDS:
        result = field_get(field, date_from, date_to, resolution="intraday")
        garmin = result.get("garmin", {})

        # Flatten per-day series into one list
        series = []
        for day_entry in garmin.get("values", []):
            day_series = day_entry.get("series")
            if isinstance(day_series, list):
                series.extend(day_series)

        fields.append({
            "field":  field,
            "series": series if series else None,
        })

    return {
        "title":    "Garmin Timeseries",
        "subtitle": f"{date_from} \u2192 {date_to} \u00b7 Use the range selector or drag to zoom",
        "fields":   fields,
    }