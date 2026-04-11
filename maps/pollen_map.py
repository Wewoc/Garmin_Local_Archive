#!/usr/bin/env python3
"""
pollen_map.py

Pollen-side field resolver for the dashboard broker architecture.

Knows the internal structure of locally archived Open-Meteo pollen data.
Maps generic field names (dashboard-side) to internal JSON keys in
context_data/pollen/raw/ files written by pollen_plugin.py.

Rules:
- Never writes. Never knows what a dashboard looks like.
- Never touches files of any other source.
- Called exclusively by context_map.py — never directly by specialists.
- Reads from context_data/pollen/raw/ — never from garmin_data/ or weather/.

Generic field names (dashboard-side):
  No Open-Meteo-internal keys must appear outside this module.
  Any internal key appearing outside this module is an architecture violation.

Note: Values are daily max aggregations (highest hourly reading per day).
      See pollen_plugin.py for aggregation logic.
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
#  Generic name → internal key in the "fields" dict of pollen_YYYY-MM-DD.json
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {
    "pollen_birch":   "birch_pollen",
    "pollen_grass":   "grass_pollen",
    "pollen_alder":   "alder_pollen",
    "pollen_mugwort": "mugwort_pollen",
    "pollen_olive":   "olive_pollen",
    "pollen_ragweed": "ragweed_pollen",
}

_FILE_PREFIX = "pollen_"


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
        f     = cfg.CONTEXT_POLLEN_DIR / f"{_FILE_PREFIX}{ds}.json"
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
    Resolve a generic pollen field name to locally archived data.

    Args:
        field:      Generic field name (dashboard-side). Must exist in _FIELD_MAP.
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: Accepted for interface compatibility — pollen is always daily.
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
        raise KeyError(f"pollen_map: unknown field '{field}'")

    fallback = resolution == "intraday"
    result   = _read_field(field, date_from, date_to)
    result["fallback"] = fallback
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())
