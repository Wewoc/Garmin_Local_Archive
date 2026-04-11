#!/usr/bin/env python3
"""
overview_garmin_xls_dash.py

Specialist: Garmin daily overview — broad flat table.
All summary fields + Activities sheet.
Source: garmin_data/summary/ via field_map.

Rules:
- No direct file access.
- No Garmin-internal field names outside this module.
- Calls field_map.get() only.
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
    "name":        "Daily Overview",
    "description": "All daily summary fields in one table — sleep, HR, stress, steps, training",
    "source":      "Garmin summary/",
    "formats": {
        "excel": "overview_garmin.xlsx",
    },
}

# Column definitions — generic field key, label, group for color coding
_COLUMNS = [
    {"field": "sleep_duration",    "label": "Sleep (h)",          "group": "sleep"},
    {"field": "spo2_avg",          "label": "SpO2 avg (%)",       "group": "sleep"},
    {"field": "hrv_last_night",    "label": "HRV night (ms)",     "group": "sleep"},
    {"field": "resting_heart_rate","label": "Resting HR (bpm)",   "group": "heartrate"},
    {"field": "stress_avg",        "label": "Stress avg",         "group": "stress"},
    {"field": "body_battery_max",  "label": "Body Battery max",   "group": "stress"},
    {"field": "vo2max",            "label": "VO2max",             "group": "training"},
]


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch daily summary fields via field_map.
    Returns neutral dict for plotters.

    Returns:
        {
            "title":    str,
            "date_from": str,
            "date_to":   str,
            "columns":  [{"field": str, "label": str, "group": str}, ...],
            "rows":     [{"date": str, "values": {field: value}}, ...],
        }
    """
    # Collect all values per field
    field_values = {}
    all_dates    = set()

    for col in _COLUMNS:
        result = field_get(col["field"], date_from, date_to, resolution="daily")
        garmin = result.get("garmin", {})
        field_values[col["field"]] = {}
        for entry in garmin.get("values", []):
            field_values[col["field"]][entry["date"]] = entry["value"]
            all_dates.add(entry["date"])

    # Build rows — one per date
    rows = []
    for ds in sorted(all_dates):
        rows.append({
            "date":   ds,
            "values": {col["field"]: field_values[col["field"]].get(ds) for col in _COLUMNS},
        })

    return {
        "title":    "Garmin Daily Overview",
        "date_from": date_from,
        "date_to":   date_to,
        "columns":  _COLUMNS,
        "rows":     rows,
    }