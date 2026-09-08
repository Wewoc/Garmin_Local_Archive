#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg
from maps._context_io import read_summary_field, read_raw_field

# ══════════════════════════════════════════════════════════════════════════════
#  Field map
#
#  Generic name → internal key in the "fields" dict of pollen_YYYY-MM-DD.json
#
#  v1.7.1.11 — each "_series" entry is an independent registry line, not
#  a resolution branch of its non-series counterpart (same pattern as
#  Garmin's _FIELD_MAP — see garmin_health_map.py). pollen_birch_series
#  is additive; it does not change pollen_birch's existing behaviour.

_FIELD_MAP = {
    "pollen_birch":          "birch_pollen",
    "pollen_birch_series":   "birch_pollen",
    "pollen_grass":          "grass_pollen",
    "pollen_grass_series":   "grass_pollen",
    "pollen_alder":          "alder_pollen",
    "pollen_alder_series":   "alder_pollen",
    "pollen_mugwort":        "mugwort_pollen",
    "pollen_mugwort_series": "mugwort_pollen",
    "pollen_olive":          "olive_pollen",
    "pollen_olive_series":   "olive_pollen",
    "pollen_ragweed":        "ragweed_pollen",
    "pollen_ragweed_series": "ragweed_pollen",
}

_FILE_PREFIX = "pollen_"

log = logging.getLogger(__name__)


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
        raise KeyError(f"pollen_map: unknown field '{field}'")

    internal_key = _FIELD_MAP[field]

    if field.endswith("_series"):
        # v1.7.1.11 — only one read path for a _series field (raw/),
        # no daily/intraday fallback branch needed. fallback is always
        # False: this field has no degraded alternate path to fall
        # back from, unlike the daily fields below.
        result = read_raw_field(cfg.CONTEXT_POLLEN_RAW_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
        result["fallback"] = False
        return result

    result = read_summary_field(cfg.CONTEXT_POLLEN_SUMMARY_DIR, _FILE_PREFIX,
                                 internal_key, date_from, date_to)
    result["fallback"] = (resolution == "intraday")
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())
