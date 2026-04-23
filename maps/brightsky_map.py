#!/usr/bin/env python3
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

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ══════════════════════════════════════════════════════════════════════════════
#  Field map
#
#  Generic name (dashboard-side) → internal key in "fields" dict of
#  brightsky_YYYY-MM-DD.json
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {
    "temperature_avg":  "temperature",        # °C    daily mean
    "humidity_avg":     "relative_humidity",  # %     daily mean
    "precipitation_sum":"precipitation",       # mm    daily sum
    "sunshine_sum":     "sunshine",           # min   daily sum
    "wind_speed_max":   "wind_speed",         # km/h  daily max
    "wind_gust_max":    "wind_gust_speed",    # km/h  daily max
    "cloud_cover_avg":  "cloud_cover",        # %     daily mean
    "pressure_avg":     "pressure_msl",       # hPa   daily mean
    "condition":        "condition",          # str   mode of hourly conditions
}

_FILE_PREFIX = "brightsky_"


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _date_range(date_from: str, date_to: str) -> list[str]:
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _read_field(field: str, date_from: str, date_to: str) -> dict:
    internal_key = _FIELD_MAP[field]
    values = []
    for ds in _date_range(date_from, date_to):
        f     = cfg.CONTEXT_BRIGHTSKY_DIR / f"{_FILE_PREFIX}{ds}.json"
        value = None
        if f.exists():
            try:
                data  = json.loads(f.read_text(encoding="utf-8"))
                value = data.get("fields", {}).get(internal_key)
            except (json.JSONDecodeError, OSError):
                pass
        values.append({"date": ds, "value": value})
    return {"values": values, "source_resolution": "daily"}


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
        resolution: Accepted for interface compatibility — Brightsky data is
                    always stored as daily aggregates.
                    "intraday" request returns fallback=True with daily data.

    Returns:
        {
            "values":            [{"date": str, "value": float|str|None}, ...],
            "fallback":          bool,
            "source_resolution": "daily",
        }

    Raises:
        KeyError: if field is not registered in _FIELD_MAP.
    """
    if field not in _FIELD_MAP:
        raise KeyError(f"brightsky_map: unknown field '{field}'")

    fallback = resolution == "intraday"
    result   = _read_field(field, date_from, date_to)
    result["fallback"] = fallback
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())
