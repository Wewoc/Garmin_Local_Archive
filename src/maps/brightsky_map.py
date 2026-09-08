#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
brightsky_map.py

Brightsky-side field resolver for the dashboard broker architecture.

Knows the internal structure of locally archived Brightsky DWD data.
Maps generic field names (dashboard-side) to internal JSON keys in
context_data/brightsky/raw/ files written by brightsky_plugin.py.

Rules:
- Never writes. Never knows what a dashboard looks like.
- Never touches files of any other source.
- Called exclusively by context_map.py — never directly by specialists.

Generic field names (dashboard-side):
  No Brightsky-internal keys must appear outside this module.
  Any internal key appearing outside this module is an architecture violation.

File structure read by this module:
  context_data/brightsky/raw/brightsky_YYYY-MM-DD.json
  {
      "date":       "YYYY-MM-DD",
      "source":     "brightsky-dwd",
      "fetched_at": "YYYY-MM-DDTHH:MM:SS",
      "latitude":   float,
      "longitude":  float,
      "fields": {
          "temperature":       float | None,   °C    daily mean
          "relative_humidity": float | None,   %     daily mean
          "precipitation":     float | None,   mm    daily sum
          "sunshine":          float | None,   min   daily sum
          "wind_speed":        float | None,   km/h  daily max
          "wind_gust_speed":   float | None,   km/h  daily max
          "cloud_cover":       float | None,   %     daily mean
          "pressure_msl":      float | None,   hPa   daily mean
          "condition":         str   | None,         mode
      }
  }
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
#  Generic name (dashboard-side) → internal key in "fields" dict of
#  brightsky_YYYY-MM-DD.json
#
#  v1.7.1.11 — each "_series" entry is an independent registry line, not
#  a resolution branch of its non-series counterpart. Additive — does
#  not change the existing daily fields' behaviour.
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {
    "temperature_avg":         "temperature",        # °C    daily mean
    "temperature_avg_series":  "temperature",
    "humidity_avg":            "relative_humidity",  # %     daily mean
    "humidity_avg_series":     "relative_humidity",
    "precipitation_sum":       "precipitation",       # mm    daily sum
    "precipitation_sum_series":"precipitation",
    "sunshine_sum":            "sunshine",           # min   daily sum
    "sunshine_sum_series":     "sunshine",
    "wind_speed_max":          "wind_speed",         # km/h  daily max
    "wind_speed_max_series":   "wind_speed",
    "wind_gust_max":           "wind_gust_speed",    # km/h  daily max
    "wind_gust_max_series":    "wind_gust_speed",
    "cloud_cover_avg":         "cloud_cover",        # %     daily mean
    "cloud_cover_avg_series":  "cloud_cover",
    "pressure_avg":            "pressure_msl",       # hPa   daily mean
    "pressure_avg_series":     "pressure_msl",
    "condition":               "condition",          # str   mode of hourly conditions
    "condition_series":        "condition",
}

_FILE_PREFIX = "brightsky_"

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — called exclusively by context_map.py
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Resolve a generic Brightsky field name to locally archived data.

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
        raise KeyError(f"brightsky_map: unknown field '{field}'")

    internal_key = _FIELD_MAP[field]

    if field.endswith("_series"):
        result = read_raw_field(cfg.CONTEXT_BRIGHTSKY_RAW_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
        result["fallback"] = False
        return result

    result = read_summary_field(cfg.CONTEXT_BRIGHTSKY_SUMMARY_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
    result["fallback"] = (resolution == "intraday")
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())
