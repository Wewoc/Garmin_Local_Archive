#!/usr/bin/env python3
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

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ══════════════════════════════════════════════════════════════════════════════
#  Field map
#
#  Generic name → internal key in the "fields" dict of airquality_YYYY-MM-DD.json
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {
    "airquality_pm2_5":            "pm2_5",
    "airquality_pm10":             "pm10",
    "airquality_european_aqi":     "european_aqi",
    "airquality_nitrogen_dioxide": "nitrogen_dioxide",
    "airquality_ozone":            "ozone",
}

_LABEL_MAP = {
    "airquality_pm2_5":            ("PM2.5",         "μg/m³"),
    "airquality_pm10":             ("PM10",          "μg/m³"),
    "airquality_european_aqi":     ("European AQI",  ""),
    "airquality_nitrogen_dioxide": ("NO₂",           "μg/m³"),
    "airquality_ozone":            ("Ozone",         "μg/m³"),
}

_FILE_PREFIX = "airquality_"


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
        f     = cfg.CONTEXT_AIRQUALITY_DIR / f"{_FILE_PREFIX}{ds}.json"
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
    Resolve a generic air quality field name to locally archived data.

    Args:
        field:      Generic field name (dashboard-side). Must exist in _FIELD_MAP.
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: Accepted for interface compatibility — air quality is always daily.
                    "intraday" request returns fallback=True with daily data.

    Returns:
        {
            "values":            [{"date": str, "value": float|None}, ...],
            "fallback":          bool,
            "source_resolution": "daily",
        }

    Raises:
        KeyError: if field is not registered in _FIELD_MAP.
    """
    if field not in _FIELD_MAP:
        raise KeyError(f"airquality_map: unknown field '{field}'")

    fallback = resolution == "intraday"
    result   = _read_field(field, date_from, date_to)
    result["fallback"] = fallback
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())


def get_label(field: str) -> tuple[str, str]:
    """Return (label, unit) for a generic field name."""
    return _LABEL_MAP.get(field, (field, ""))