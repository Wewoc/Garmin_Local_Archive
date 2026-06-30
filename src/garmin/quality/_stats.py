#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
garmin/quality/_stats.py

Archive statistics sub-module for garmin_quality.
Read-only — no file writes, no API calls.

Internal — import only via garmin_quality (facade).
"""

import json
import logging
from datetime import date as _date
from pathlib import Path


log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Archive stats (read-only, for GUI info panel)
# ══════════════════════════════════════════════════════════════════════════════

def get_archive_stats(quality_log_path=None) -> dict:
    """
    Returns a summary of the local archive state for display in the GUI.
    Reads quality_log.json — no API call, no side effects.

    quality_log_path: optional Path override — if None, uses cfg.QUALITY_LOG_FILE.

    Returns dict with keys:
      total        int   — total days tracked
      high         int   — days with quality 'high'
      standard     int   — days with quality 'standard'
      failed       int   — days with quality 'failed'
      recheck      int   — days with recheck=True
      missing      int   — days absent in range (possible - present) or None
      date_min     str   — earliest date tracked (YYYY-MM-DD) or None
      date_max     str   — latest date tracked (YYYY-MM-DD) or None
      coverage_pct int   — days present vs. possible days in range (0–100) or None
      last_api     str   — latest date with source='api' (YYYY-MM-DD) or None
      last_bulk    str   — latest date with source='bulk' (YYYY-MM-DD) or None
    """
    from quality._io import _load_quality_log

    try:
        if quality_log_path is not None:
            p = Path(quality_log_path)
            if p.exists():
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                if "days" not in data:
                    data = {"days": []}
            else:
                data = {"days": []}
        else:
            data = _load_quality_log()
    except Exception:
        data = {"days": []}

    days = data.get("days", [])

    counts = {"high": 0, "standard": 0, "failed": 0}
    recheck = 0
    dates = []
    api_dates = []
    bulk_dates = []

    for entry in days:
        q = entry.get("quality", "failed")
        if q in counts:
            counts[q] += 1
        if entry.get("recheck"):
            recheck += 1
        d = entry.get("date")
        if d:
            dates.append(d)
            src = entry.get("source", "")
            if src == "api":
                api_dates.append(d)
            elif src == "bulk":
                bulk_dates.append(d)

        # Accumulate per-device stats
        dev_id = str(entry.get("device_rank", "")) or None
        # Use a stable key: look up device_rank_config to find device_id
        # device_rank is int|null — not useful as key. We need device_id from
        # the config. Stats are built from config entries, not per-entry device_id
        # (device_id is not stored per entry — only device_rank is).
        # device_table is built from device_rank_config in the return block below.

    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    coverage_pct = None
    missing      = None
    if date_min and date_max:
        try:
            # If first_day is set and earlier than the oldest tracked entry,
            # use first_day as the range start — otherwise missing count is
            # understated on fresh archives after bulk import.
            first_day_str = data.get("first_day")
            if first_day_str and first_day_str < date_min:
                d0 = _date.fromisoformat(first_day_str)
            else:
                d0 = _date.fromisoformat(date_min)
            d1 = _date.fromisoformat(date_max)
            possible = (d1 - d0).days + 1
            present  = len(dates)
            coverage_pct = round(present / possible * 100) if possible > 0 else 100
            missing      = possible - present
        except Exception:
            pass

    # Build device_table from device_rank_config + day entries
    device_rank_config = data.get("device_rank_config", {})
    device_table = []
    for dev_id, dev_cfg in device_rank_config.items():
        dev_dates    = []
        days_high     = 0
        days_standard = 0
        for entry in days:
            # Match by device_rank: find rank in config for this device_id
            cfg_rank = dev_cfg.get("rank")
            entry_rank = entry.get("device_rank")
            if cfg_rank is not None and entry_rank == cfg_rank:
                ed = entry.get("date")
                if ed:
                    dev_dates.append(ed)
                eq = entry.get("quality", "failed")
                if eq == "high":
                    days_high += 1
                elif eq == "standard":
                    days_standard += 1
        device_table.append({
            "device_id":     dev_id,
            "name":          dev_cfg.get("name", ""),
            "rank":          dev_cfg.get("rank"),
            "date_from":     min(dev_dates) if dev_dates else None,
            "date_to":       max(dev_dates) if dev_dates else None,
            "days_high":     days_high,
            "days_standard": days_standard,
            "days_total":    days_high + days_standard,
        })
    # Sort by rank (null last), then by date_from
    device_table.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["date_from"] or ""))

    return {
        "total":              len(days),
        "high":               counts["high"],
        "standard":           counts["standard"],
        "failed":             counts["failed"],
        "recheck":            recheck,
        "missing":            missing,
        "date_min":           date_min,
        "date_max":           date_max,
        "coverage_pct":       coverage_pct,
        "last_api":           max(api_dates)  if api_dates  else None,
        "last_bulk":          max(bulk_dates) if bulk_dates else None,
        "integrity_warnings": data.get("integrity_warnings", []),
        "device_table":       device_table,
    }
