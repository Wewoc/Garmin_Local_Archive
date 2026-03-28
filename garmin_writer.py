#!/usr/bin/env python3
"""
garmin_writer.py

Writer — sole owner of raw/ and summary/.

Responsibilities:
  - Write raw/garmin_raw_YYYY-MM-DD.json
  - Write summary/garmin_YYYY-MM-DD.json

No other module writes to raw/ or summary/ directly.
No API logic, no quality log access, no date strategy logic.

Single public entry point:
  write_day(normalized, summary, date_str) -> bool
"""

import json
import logging
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def write_day(normalized: dict, summary: dict, date_str: str) -> bool:
    """
    Writes a single day to raw/ and summary/.

    Parameters
    ----------
    normalized : dict — normalised raw data as returned by garmin_normalizer.normalize()
    summary    : dict — compact daily summary as returned by garmin_normalizer.summarize()
    date_str   : str  — date in YYYY-MM-DD format

    Returns
    -------
    bool — True if both files were written successfully, False on any error
    """
    try:
        cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

        raw_path     = cfg.RAW_DIR     / f"garmin_raw_{date_str}.json"
        summary_path = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"

        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        log.debug(f"  Writer: raw + summary written for {date_str}")
        return True

    except Exception as e:
        log.error(f"  Writer: failed to write {date_str}: {e}")
        return False
