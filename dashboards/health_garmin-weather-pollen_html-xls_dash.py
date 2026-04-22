#!/usr/bin/env python3
"""
health_garmin-weather-pollen_html-xls_dash.py

Specialist: Garmin health metrics combined with weather and pollen context.
Shows daily HRV, Stress, Body Battery alongside temperature, UV, pollen load.

Sources:
  - Garmin summary/ via field_map  (HRV, Stress, Body Battery)
  - context_data/   via context_map (Temperature, UV Index, Pollen Birch)

Rules:
- No direct file access.
- No source-internal field names outside this module.
- Calls field_map.get() and context_map.get() only.
- Returns neutral dict for plotters — no rendering logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map    import get as field_get
from maps.context_map  import get as context_get

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Health + Context",
    "description": "HRV, Stress, Body Battery alongside temperature, UV index and pollen",
    "source":      "Garmin summary/ + context_data/",
    "formats": {
        "html":  "health_context_garmin.html",
        "excel": "health_context_garmin.xlsx",
    },
}

# Garmin fields — via field_map
_GARMIN_FIELDS = [
    {"field": "hrv_last_night",   "label": "HRV",          "unit": "ms",    "group": "garmin"},
    {"field": "stress_avg",       "label": "Stress",        "unit": "level", "group": "garmin"},
    {"field": "body_battery_max", "label": "Body Battery",  "unit": "level", "group": "garmin"},
]

# Context fields — via context_map
_CONTEXT_FIELDS = [
    {"field": "temperature_max", "label": "Temp Max",   "unit": "°C",  "group": "weather"},
    {"field": "uv_index_max",    "label": "UV Index",   "unit": "",    "group": "weather"},
    {"field": "pollen_birch",    "label": "Pollen",     "unit": "idx", "group": "pollen"},
]


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch Garmin + context fields via their respective brokers.
    Returns neutral dict for plotters.

    Context data must be collected before build — if unavailable,
    context fields appear with None values (degraded mode, no hard stop).

    Returns:
        {
            "title":    str,
            "subtitle": str,
            "date_from": str,
            "date_to":   str,
            "fields": [
                {
                    "field":  str,
                    "label":  str,
                    "unit":   str,
                    "group":  str,   # "garmin" | "weather" | "pollen"
                    "days":   [{"date": str, "value": float|None}, ...],
                },
                ...
            ],
        }
    """
    fields_out = []

    # ── Garmin fields ─────────────────────────────────────────────────────────
    for f in _GARMIN_FIELDS:
        result = field_get(f["field"], date_from, date_to, resolution="daily")
        garmin = result.get("garmin", {})
        days   = [
            {"date": entry["date"], "value": entry["value"]}
            for entry in garmin.get("values", [])
        ]
        fields_out.append({
            "field": f["field"],
            "label": f["label"],
            "unit":  f["unit"],
            "group": f["group"],
            "days":  days,
        })

    # ── Context fields ────────────────────────────────────────────────────────
    for f in _CONTEXT_FIELDS:
        result = context_get(f["field"], date_from, date_to)

        # context_map returns {"weather": {...}} or {"pollen": {...}}
        # take first available source result
        source_result = next(iter(result.values()), {}) if result else {}
        days = [
            {"date": entry["date"], "value": entry["value"]}
            for entry in source_result.get("values", [])
        ]
        fields_out.append({
            "field": f["field"],
            "label": f["label"],
            "unit":  f["unit"],
            "group": f["group"],
            "days":  days,
        })

    # Auto-size: determine actual data boundaries from Garmin fields only
    garmin_dates = set()
    for f_out in fields_out:
        if f_out["group"] == "garmin":
            for day in f_out["days"]:
                if day["value"] is not None:
                    garmin_dates.add(day["date"])

    adjusted_from = None
    adjusted_to   = None
    if garmin_dates:
        actual_first = min(garmin_dates)
        actual_last  = max(garmin_dates)
        if actual_first > date_from:
            adjusted_from = date_from
        if actual_last < date_to:
            adjusted_to = date_to

    subtitle = f"{date_from} \u2192 {date_to} \u00b7 Garmin + Weather + Pollen"
    if adjusted_from or adjusted_to:
        actual_first = min(garmin_dates)
        actual_last  = max(garmin_dates)
        subtitle = (
            f"{actual_first} \u2192 {actual_last}"
            f" \u00b7 Garmin + Weather + Pollen"
            f" \u00b7 adjusted to available data"
            f" (requested: {adjusted_from or date_from} \u2192 {adjusted_to or date_to})"
        )

    return {
        "title":    "Garmin Health + Context",
        "subtitle": subtitle,
        "date_from": date_from,
        "date_to":   date_to,
        "fields":   fields_out,
    }