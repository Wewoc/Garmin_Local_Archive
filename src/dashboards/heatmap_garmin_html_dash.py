#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
heatmap_garmin_html_dash.py

Specialist: Activity & Physiology Heatmaps.
Metrics: Heart Rate, Steps, Stress, Body Battery, SpO2, Respiration —
         time-of-day (hourly bins) x date, pivoted from intraday series.

Sources:
  - Garmin raw/ via health_map (intraday): heart_rate_series, steps_series,
    stress_series, body_battery_series, spo2_series, respiration_series

Aggregation per hourly bin:
  - Heart Rate, Stress, Body Battery: mean (continuous physiological values)
  - Steps: sum (count metric — sum per hour is more meaningful than average
    of 15-minute bins)

Rules:
- No direct file access.
- No source-internal field names outside this module.
- Calls health_map.get() only.
- Returns neutral dict for dash_plotter_html_complex ("layout": "heatmap").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.health_map import get as health_get
from layouts.dash_autosize import compute_autosize_bounds, autosize_note

# ══════════════════════════════════════════════════════════════════════════════
#  Specialist declaration
# ══════════════════════════════════════════════════════════════════════════════

META = {
    "name":        "Heatmap",
    "description": "Time-of-day x date heatmaps — Heart Rate, Steps, Stress, Body Battery, SpO2, Respiration",
    "source":      "Garmin raw/ via health_map (intraday)",
    "formats": {
        "html_complex": "heatmap_garmin.html",
    },
}

# ── Metrics — key, source field, hourly aggregation ───────────────────────────

_METRICS = [
    {"key": "heart_rate",   "field": "heart_rate_series",   "agg": "mean"},
    {"key": "steps",        "field": "steps_series",        "agg": "sum"},
    {"key": "stress",       "field": "stress_series",       "agg": "mean"},
    {"key": "body_battery", "field": "body_battery_series", "agg": "mean"},
    {"key": "spo2",         "field": "spo2_series",         "agg": "mean"},
    {"key": "respiration",  "field": "respiration_series",  "agg": "mean"},
]

_HOURS = list(range(24))


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _bucket_hourly(series, agg: str) -> list:
    """
    Buckets a [{'ts': iso-str, 'value': float}, ...] series into 24 hourly
    bins (0-23). Hour is read directly from the ISO timestamp string
    (positions 11:13 — ts is always "%Y-%m-%dT%H:%M:%S" per garmin_health_map's
    _ts_to_iso()). Returns a list of 24 values, None where no data fell
    into that hour.

    Args:
        series: [{"ts": str, "value": float}, ...] or None (missing day).
        agg:    "mean" (continuous values) or "sum" (count values, e.g. steps).
    """
    buckets = {h: [] for h in _HOURS}

    if series:
        for item in series:
            ts  = item.get("ts")
            val = item.get("value")
            if not ts or val is None or len(ts) < 13:
                continue
            try:
                hour = int(ts[11:13])
            except ValueError:
                continue
            if 0 <= hour <= 23:
                buckets[hour].append(val)

    result = []
    for h in _HOURS:
        vals = buckets[h]
        if not vals:
            result.append(None)
        elif agg == "sum":
            result.append(round(sum(vals), 1))
        else:
            result.append(round(sum(vals) / len(vals), 1))
    return result


def _build_metric_matrix(field: str, agg: str, date_from: str, date_to: str) -> dict:
    """
    Fetches an intraday field for the date range and pivots it to a
    date x hour matrix. A missing day (series=None) becomes an all-None
    row — same shape as a day with data, so the renderer never has to
    special-case row length.
    """
    result = health_get(field, date_from, date_to, resolution="intraday")
    garmin = result.get("garmin", {})

    dates  = []
    matrix = []
    for entry in garmin.get("values", []):
        dates.append(entry["date"])
        matrix.append(_bucket_hourly(entry.get("series"), agg))

    return {"dates": dates, "hours": _HOURS, "matrix": matrix}


def _dates_with_data(metric: dict) -> set:
    """
    Subset of metric['dates'] whose matrix row contains at least one
    non-None value. Needed because 'dates' itself is padded — every
    requested day gets a row regardless of data presence (see
    _build_metric_matrix docstring), so a day with no actual raw data
    still shows up there with an all-None row. Auto-size needs the
    narrower "has real data" set, not the padded request range.
    """
    return {
        d for d, row in zip(metric["dates"], metric["matrix"])
        if any(v is not None for v in row)
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Build
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Fetch all six intraday metrics via health_map and pivot each to a
    date x hourly-bin matrix.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        settings:  Settings dict from GUI (unused here, reserved).

    Returns:
        {
            "layout":    "heatmap",
            "title":     str,
            "subtitle":  str,
            "date_from": str,
            "date_to":   str,
            "metrics": {
                "heart_rate":   {"dates": [str], "hours": [0..23], "matrix": [[float|None]]},
                "steps":        {...},
                "stress":       {...},
                "body_battery": {...},
            },
        }
    """
    metrics = {}
    for m in _METRICS:
        metrics[m["key"]] = _build_metric_matrix(m["field"], m["agg"], date_from, date_to)

    # Auto-size: pool "has data" dates across all six metrics (a day counts
    # if any metric has a real sample that hour) — same pooling approach as
    # sleep_recovery_context_dash.py combining multiple field sources.
    garmin_dates = set()
    for metric in metrics.values():
        garmin_dates |= _dates_with_data(metric)

    _bounds = compute_autosize_bounds(garmin_dates, date_from, date_to)
    _note   = autosize_note(_bounds, date_from, date_to)
    if _note:
        subtitle = f"{_bounds['actual_first']} \u2192 {_bounds['actual_last']}{_note}"
    else:
        subtitle = f"{date_from} \u2192 {date_to}"

    return {
        "layout":    "heatmap",
        "title":     "Activity & Physiology Heatmaps",
        "subtitle":  subtitle,
        "date_from": date_from,
        "date_to":   date_to,
        "metrics":   metrics,
    }
