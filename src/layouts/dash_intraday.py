#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
dash_intraday.py

Sole owner of the intraday shaping that the Sleep, the Explorer and the
Recovery specialists share: which four intraday series a day view shows, how a
health_map intraday result becomes {date: series}, and which days are kept
(only days with at least one non-empty series).

Rules:
- Pure shaping. No file I/O, no broker call (the fetch stays in the
  specialist, which calls health_map), no imports beyond stdlib.
- Called by specialists in dashboards/ — never by plotters. The renderer
  of the day view is layouts/render/intraday_block.py.
"""

# The four series of the day view: health_map field -> key of the neutral dict.
INTRADAY_FIELDS = [
    {"field": "heart_rate_series",   "key": "heart_rate"},
    {"field": "stress_series",       "key": "stress"},
    {"field": "body_battery_series", "key": "body_battery"},
    {"field": "respiration_series",  "key": "respiration"},
]

INTRADAY_KEYS = tuple(f["key"] for f in INTRADAY_FIELDS)


def intraday_by_date(result: dict) -> dict:
    """Extract {date: series} from a health_map intraday result (garmin source)."""
    garmin = result.get("garmin", {})
    return {
        entry["date"]: entry.get("series")
        for entry in garmin.get("values", [])
    }


def build_intraday(raw_by_key: dict, dates) -> dict:
    """
    {date: {key: series|None}} for the days that have at least one non-empty series.

    Args:
        raw_by_key: {key: {date: series|None}} — one intraday_by_date() result per key
                    of INTRADAY_KEYS.
        dates:      the days to look at, in the order the result should have.
    """
    out = {}
    for d in dates:
        day = {key: raw_by_key[key].get(d) for key in INTRADAY_KEYS}
        if any(day[key] is not None and len(day[key]) > 0 for key in INTRADAY_KEYS):
            out[d] = day
    return out
