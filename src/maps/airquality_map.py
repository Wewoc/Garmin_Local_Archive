#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
airquality_map.py

Air quality field resolver for the dashboard broker architecture.

Knows the internal structure of locally archived Open-Meteo air quality data.
Maps generic field names (dashboard-side) to internal JSON keys in
context_data/airquality/raw/ files written by airquality_plugin.py.

Rules:
- Never writes. Never knows what a dashboard looks like.
- Never touches files of any other source.
- Called exclusively by context_map.py — never directly by specialists.
- Reads from context_data/airquality/raw/ — never from garmin_data/ or other sources.

Generic field names (dashboard-side):
  No Open-Meteo-internal keys must appear outside this module.
  Any internal key appearing outside this module is an architecture violation.

Note: Values are daily mean aggregations (24h average per day).
      See airquality_plugin.py for aggregation logic.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg
from maps._context_io import read_summary_field, read_raw_field

# ══════════════════════════════════════════════════════════════════════════════
#  Field map
#
#  Generic name → internal key in the "fields" dict of airquality_YYYY-MM-DD.json
#
#  v1.7.1.11 — each "_series" entry is an independent registry line, not
#  a resolution branch of its non-series counterpart. Additive — does
#  not change the existing daily fields' behaviour.
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {
    "airquality_pm2_5":                   "pm2_5",
    "airquality_pm2_5_series":            "pm2_5",
    "airquality_pm10":                    "pm10",
    "airquality_pm10_series":             "pm10",
    "airquality_european_aqi":            "european_aqi",
    "airquality_european_aqi_series":     "european_aqi",
    "airquality_nitrogen_dioxide":        "nitrogen_dioxide",
    "airquality_nitrogen_dioxide_series": "nitrogen_dioxide",
    "airquality_ozone":                   "ozone",
    "airquality_ozone_series":            "ozone",
}

_LABEL_MAP = {
    "airquality_pm2_5":            ("PM2.5",         "μg/m³"),
    "airquality_pm10":             ("PM10",          "μg/m³"),
    "airquality_european_aqi":     ("European AQI",  ""),
    "airquality_nitrogen_dioxide": ("NO₂",           "μg/m³"),
    "airquality_ozone":            ("Ozone",         "μg/m³"),
}

_FILE_PREFIX = "airquality_"

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — called exclusively by context_map.py
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Resolve a generic air quality field name to locally archived data.

    Args:
        field:      Generic field name (dashboard-side). Must exist in _FIELD_MAP.
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: Accepted for interface compatibility. Ignored for "_series"
                    fields (only one read path — raw/, always intraday). For
                    non-series fields, "intraday" returns fallback=True with
                    daily data, unchanged from before v1.7.1.11.

    Returns:
        {
            "values":            [...],
            "fallback":          bool,
            "source_resolution": "daily" | "intraday",
        }

    Raises:
        KeyError: if field is not registered in _FIELD_MAP.
    """
    if field not in _FIELD_MAP:
        raise KeyError(f"airquality_map: unknown field '{field}'")

    internal_key = _FIELD_MAP[field]

    if field.endswith("_series"):
        result = read_raw_field(cfg.CONTEXT_AIRQUALITY_RAW_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
        result["fallback"] = False
        return result

    result = read_summary_field(cfg.CONTEXT_AIRQUALITY_SUMMARY_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
    result["fallback"] = (resolution == "intraday")
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())


def get_label(field: str) -> tuple[str, str]:
    """Return (label, unit) for a generic field name."""
    return _LABEL_MAP.get(field, (field, ""))
