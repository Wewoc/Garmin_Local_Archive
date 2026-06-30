#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin/quality/_scan.py

Scan sub-module for garmin_quality.
Scans raw/ for quality issues and backfills the quality log.

Internal — import only via garmin_quality (facade).
"""

import json
import logging
from pathlib import Path

import garmin_config as cfg

from garmin_utils import extract_date_from_filename
from quality._assess import assess_quality
from quality._maint import _upsert_quality

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Backfill
# ══════════════════════════════════════════════════════════════════════════════

def _backfill_quality_log(data: dict) -> int:
    """
    One-time backfill: scans all raw/ files and adds any days not yet in the
    quality log — including high and med quality days that were never recorded.
    Only runs when first_day is not yet set.
    Returns the number of newly added entries.
    """
    if not cfg.RAW_DIR.exists():
        return 0

    known = {e["date"] for e in data.get("days", []) if "date" in e}
    added = 0

    for f in sorted(cfg.RAW_DIR.glob("garmin_raw_*.json")):
        day = extract_date_from_filename(f)
        if day is None:
            continue
        if day.isoformat() in known:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
            q = assess_quality(raw)
            _upsert_quality(data, day, q, f"Quality: {q} — backfill on first_day init",
                            written=True, source="legacy")
            added += 1
        except (OSError, json.JSONDecodeError):
            pass

    if added:
        log.info(f"  Backfill: {added} existing days added to quality log")
    return added


# ══════════════════════════════════════════════════════════════════════════════
#  Scan for low/failed files
# ══════════════════════════════════════════════════════════════════════════════

def get_low_quality_dates(folder: Path, known_dates: set = None) -> dict:
    """
    Scans raw/ for files with quality 'failed' based on content.
    Skips dates already in the quality log (known_dates set).
    Returns {date: quality} for newly discovered failed files.
    """
    result = {}
    if not folder.exists():
        return result
    for f in folder.glob("garmin_raw_*.json"):
        day = extract_date_from_filename(f)
        if day is None:
            continue
        try:
            if known_dates and day in known_dates:
                continue  # already in quality log — skip OneDrive download
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
            q = assess_quality(raw)
            if q == "failed":
                result[day] = q
        except (OSError, json.JSONDecodeError):
            pass
    if result:
        log.info(f"  Newly discovered failed quality files: {len(result)}")
    return result
