#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
dashboards/live_tracking_html_dash.py

Specialist — Live Tracking dashboard.

Fetches today's intraday progression (Body Battery, Heart Rate, Steps,
Stress) and last night's sleep summary via field_map — resolution="live"
throughout, with an archive fallback for the entire sleep block.

No direct file access — same broker discipline as every other specialist.
Not part of the normal "Create Reports" selection by product decision
(separate triggers: "Update Live" button / end of Sync Garmin) — that GUI
exclusion is a separate, not-yet-built piece, see NOTES_v1_6_5.md. Auto-
discovery in dash_runner.scan() will list this specialist like any other
until that exclusion exists.

Precedence rule (sleep block only): a single representative field
(sleep_score) decides the source. If it falls back to archive, the entire
sleep block — score, qualifier, feedback, duration, HRV, phases — is
fetched from the archive. Never a mix of live and archive data for the
same night.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map import get as field_get

META = {
    "name":        "Live Tracking",
    "description": "Today's progression + last night, always-current snapshot",
    "source":      "garmin_data/live/live.json via field_map (live), archive fallback for sleep",
    "formats": {
        "html_complex": "live_tracking.html",
    },
}

_TODAY_FIELDS = {
    "body_battery": "body_battery_series",
    "heart_rate":   "heart_rate_series",
    "steps":        "steps_series",
    "stress":       "stress_series",
}

_SLEEP_FIELDS = {
    "score":      "sleep_score",
    "qualifier":  "sleep_score_qualifier",
    "feedback":   "sleep_score_feedback",
    "duration_h": "sleep_duration",
    "hrv":        "hrv_last_night",
}

_PHASE_FIELDS = {
    "deep":  "sleep_deep_pct",
    "light": "sleep_light_pct",
    "rem":   "sleep_rem_pct",
    "awake": "sleep_awake_pct",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_today(today: str) -> dict:
    """Today's intraday progression, resolution='live' throughout."""
    out = {}
    for key, field in _TODAY_FIELDS.items():
        result = field_get(field, today, today, resolution="live")
        values = result.get("garmin", {}).get("values") or []
        series = (values[0].get("series") if values else None) or []

        if key == "steps":
            # Cumulative counter — sum the bins, not the last one
            current = sum(p["value"] for p in series) if series else None
        else:
            current = series[-1]["value"] if series else None

        out[key] = {"current": current, "series": series}
    return out


def _fetch_sleep_block(today: str, resolution: str) -> dict:
    """Fetch the full sleep block from a single resolution — never mixed."""
    block = {}
    for key, field in _SLEEP_FIELDS.items():
        result = field_get(field, today, today, resolution=resolution)
        values = result.get("garmin", {}).get("values") or []
        block[key] = values[0].get("value") if values else None

    phases = {}
    for key, field in _PHASE_FIELDS.items():
        result = field_get(field, today, today, resolution=resolution)
        values = result.get("garmin", {}).get("values") or []
        phases[key] = values[0].get("value") if values else None
    block["phases"] = phases

    return block


def _hrv_7d_avg(today: str) -> float | None:
    """Average of hrv_last_night over the trailing 7 days — archive only,
    no live equivalent for a multi-day average makes sense."""
    week_ago = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    result = field_get("hrv_last_night", week_ago, today, resolution="daily")
    values = result.get("garmin", {}).get("values") or []
    nums = [v["value"] for v in values if v.get("value") is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def build(date_from: str, date_to: str, settings: dict) -> dict:
    """
    Returns the neutral dict consumed by dash_plotter_html_complex.py via
    layouts/render/live.py.

    date_from/date_to are accepted for interface compatibility with
    dash_runner.build() (which always calls specialists this way) but are
    otherwise ignored — Live Tracking always shows "now", never a range.
    """
    today = date.today().isoformat()

    today_data = _fetch_today(today)

    # Precedence: one representative field decides the whole sleep block's source
    probe          = field_get("sleep_score", today, today, resolution="live")
    probe_fallback = probe.get("garmin", {}).get("fallback", True)
    source         = "archive" if probe_fallback else "live"

    last_night              = _fetch_sleep_block(today, source if source == "live" else "daily")
    last_night["hrv_7d_avg"] = _hrv_7d_avg(today)
    last_night["source"]     = source

    return {
        "layout":     "live",
        "title":      "Live Tracking",
        "subtitle":   f"{today} \u00b7 today so far",
        "today":      today_data,
        "last_night": last_night,
    }
