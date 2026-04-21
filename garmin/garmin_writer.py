#!/usr/bin/env python3
"""
garmin_writer.py

Writer — sole owner of raw/ and summary/.

Responsibilities:
  - Write raw/garmin_raw_YYYY-MM-DD.json
  - Write summary/garmin_YYYY-MM-DD.json

No other module writes to raw/ or summary/ directly.
No API logic, no quality log access, no date strategy logic.

Public functions:
  write_day(normalized, summary, date_str) -> bool
  read_raw(date_str)                       -> dict
"""

import json
import logging
import os
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
    tmp_raw     = None
    tmp_summary = None
    try:
        cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

        raw_path     = cfg.RAW_DIR     / f"garmin_raw_{date_str}.json"
        summary_path = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"
        tmp_raw      = cfg.RAW_DIR     / f"garmin_raw_{date_str}.tmp"
        tmp_summary  = cfg.SUMMARY_DIR / f"garmin_{date_str}.tmp"

        tmp_raw.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp_summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        os.replace(tmp_raw, raw_path)
        tmp_raw = None
        os.replace(tmp_summary, summary_path)
        tmp_summary = None

        log.debug(f"  Writer: raw + summary written for {date_str}")
        return True

    except Exception as e:
        log.error(f"  Writer: failed to write {date_str}: {e}")
        for tmp in (tmp_raw, tmp_summary):
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        return False


def read_raw(date_str: str) -> dict:
    """
    Reads and returns the raw file for a given date.

    Used exclusively by the self-healing loop in garmin_collector.py —
    no API call, no re-download. Returns empty dict on any error.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    dict — parsed raw data, or {} if file is missing or corrupt
    """
    raw_path = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"

    if not raw_path.exists():
        log.warning(f"  Writer.read_raw: file not found for {date_str}")
        return {}

    try:
        with open(raw_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"  Writer.read_raw: failed to read {date_str}: {e}")
        return {}
