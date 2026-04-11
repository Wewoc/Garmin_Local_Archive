#!/usr/bin/env python3
"""
garmin_sync.py

Strategist — calculates which days are missing and returns the date list.

Responsibilities:
  - Resolve the date range to check based on SYNC_MODE
  - Scan local raw/ files to find already-present days
  - Subtract recheck days from local set (if REFRESH_FAILED is active)
  - Provide a date generator for iterating over a range

No side effects — reads only, never writes.
No API calls, no quality_log.json access.

Coupling resolved vs. original garmin_collector.py:
  - resolve_date_range() no longer loads quality_log.json internally.
    first_day is received as a parameter from main().
  - get_local_dates() no longer reads quality_log.json internally.
    recheck_dates is received as a parameter from main().
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Date range resolution
# ══════════════════════════════════════════════════════════════════════════════

def resolve_date_range(first_day: str | None) -> tuple[date, date]:
    """
    Returns (start, end) based on cfg.SYNC_MODE.

    "recent" → (today - SYNC_DAYS, yesterday)
    "range"  → (SYNC_FROM, SYNC_TO)
    "auto"   → (first_day, yesterday) — first_day from quality_data via main()

    first_day: str | None — value from quality_data["first_day"], passed by main()
    """
    today     = date.today()
    yesterday = today - timedelta(days=1)

    if cfg.SYNC_MODE == "recent":
        start = today - timedelta(days=cfg.SYNC_DAYS)
        log.info(f"  Mode: recent — last {cfg.SYNC_DAYS} days ({start} → {yesterday})")
        return start, yesterday

    if cfg.SYNC_MODE == "range":
        start = date.fromisoformat(cfg.SYNC_FROM)
        end   = date.fromisoformat(cfg.SYNC_TO)
        log.info(f"  Mode: range — {start} → {end}")
        return start, end

    if cfg.SYNC_MODE == "auto":
        log.info("  Mode: auto — detecting earliest available date ...")

        if first_day:
            start = date.fromisoformat(first_day)
            log.info(f"  first_day from quality log: {start}")
            return start, yesterday

        if cfg.SYNC_AUTO_FALLBACK:
            log.info(f"  Using SYNC_AUTO_FALLBACK: {cfg.SYNC_AUTO_FALLBACK}")
            return date.fromisoformat(cfg.SYNC_AUTO_FALLBACK), yesterday

        log.warning("  Could not determine start date — falling back to 90 days.")
        return today - timedelta(days=90), yesterday

    log.error(f"  Unknown SYNC_MODE: '{cfg.SYNC_MODE}' — use 'recent', 'range', or 'auto'.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Local date scan
# ══════════════════════════════════════════════════════════════════════════════

def get_local_dates(folder: Path, recheck_dates: set | None = None) -> set:
    """
    Returns dates for which local data already exists.
    Checks all locations and naming schemes:
      1. raw/garmin_raw_YYYY-MM-DD.json   (current schema)
      2. summary/garmin_YYYY-MM-DD.json   (current schema, fallback)
      3. BASE_DIR/garmin_YYYY-MM-DD.json  (legacy schema)

    recheck_dates: set[date] | None — dates to exclude from the result so they
                   appear as missing and get re-fetched. Passed by main() when
                   cfg.REFRESH_FAILED is True. None = no exclusion.
    """
    dates = set()
    checks = [
        (folder,                    "garmin_raw_*.json", "garmin_raw_"),
        (folder.parent / "summary", "garmin_*.json",     "garmin_"),
        (folder.parent,             "garmin_*.json",     "garmin_"),
    ]
    for directory, pattern, prefix in checks:
        if not directory.exists():
            continue
        for f in directory.glob(pattern):
            try:
                dates.add(date.fromisoformat(f.stem.replace(prefix, "")))
            except ValueError:
                pass

    if recheck_dates:
        before  = len(dates)
        dates  -= recheck_dates
        removed = before - len(dates)
        if removed:
            log.info(f"  Refresh mode: excluding {removed} recheck days for re-fetch")

    if dates:
        log.info(f"  Local days found: {len(dates)} (earliest: {min(dates)}, latest: {max(dates)})")
    return dates


# ══════════════════════════════════════════════════════════════════════════════
#  Date generator
# ══════════════════════════════════════════════════════════════════════════════

def date_range(start: date, end: date):
    """Yields every date from start to end (inclusive)."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
