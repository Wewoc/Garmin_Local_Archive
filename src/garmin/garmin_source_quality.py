#!/usr/bin/env python3
"""
garmin_source_quality.py

Source Quality Assessment — Sole Owner of source quality logic.

Assesses whether a Garmin API response contains intraday data, and decides
whether a new response should overwrite an existing source file.

Used by garmin_source_writer to guard write_source() against overwriting
high-resolution source files with degraded API responses.

Guard truth table (Conservative — freeze-when-present):

  Existing file   New response          Action
  ─────────────   ────────────────────  ──────────────
  none            any                   write
  present=False   present=True          write
  present=False   present=False         write  (refresh, harmless)
  present=True    present=True          skip   (freeze — first good capture wins)
  present=True    present=False         skip_warn  (degradation blocked — core fix)

Known limitation: binary detection only. Cannot distinguish shrinkage within
"present" (e.g. 1440 → 96 HR points). Freeze-when-present mitigates by never
overwriting a present file with another present file. Numerical scoring is
explicitly out of scope (KONZEPT_silo_check.md §2b §C).

Leaf-Node: imports only stdlib. No garmin_config, no pipeline module imports.

Called by:
    garmin/garmin_source_writer.py — write_source() guard
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Intraday keys whose presence signals high-resolution API data.
# At least one non-empty/non-null value means intraday is present.
# These keys exist in the raw API response dict (before normalization).
_INTRADAY_KEYS = (
    ("heart_rates",  "heartRateValues"),
    ("stress",       "stressValuesArray"),
    ("stress",       "bodyBatteryValuesArray"),
)


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def assess_source(raw_data: dict) -> dict:
    """
    Assesses whether a raw API response dict contains intraday data.

    Checks for at least one of heartRateValues, stressValuesArray,
    bodyBatteryValuesArray being non-empty and non-null.

    Parameters
    ----------
    raw_data : dict — unmodified API response from garmin_api.fetch_raw()

    Returns
    -------
    dict — {"intraday_present": bool}
    """
    if not isinstance(raw_data, dict):
        return {"intraday_present": False}

    for top_key, intraday_key in _INTRADAY_KEYS:
        top = raw_data.get(top_key)
        if not isinstance(top, dict):
            continue
        val = top.get(intraday_key)
        if val:  # non-empty list, non-null — truthy check is correct here
            return {"intraday_present": True}

    return {"intraday_present": False}


def assess_source_from_file(source_path: Path) -> dict | None:
    """
    Reads an existing source file from disk and assesses it.

    Returns None if the file does not exist or cannot be read/parsed.
    Returns {"intraday_present": bool} on success.

    Called by garmin_source_writer.write_source() to read the existing
    file state before deciding whether to overwrite.
    """
    if not source_path.exists():
        return None
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        return assess_source(raw)
    except Exception as e:
        log.warning(f"  source_quality: could not read existing file {source_path.name}: {e}")
        return None


def compare_source(existing_assessment: dict | None, new_assessment: dict) -> str:
    """
    Decides whether a new source response should overwrite the existing file.

    Conservative strategy (freeze-when-present):
      - No existing file  → write
      - Existing absent   → write (regardless of new)
      - Existing present, new present → skip  (first good capture wins)
      - Existing present, new absent  → skip_warn  (degradation blocked)

    Parameters
    ----------
    existing_assessment : dict | None
        Result of assess_source() on the existing file, or None if no file exists.
    new_assessment : dict
        Result of assess_source() on the incoming raw_data.

    Returns
    -------
    str — "write" | "skip" | "skip_warn"
    """
    if existing_assessment is None:
        # No existing file — always write
        return "write"

    existing_present = existing_assessment.get("intraday_present", False)
    new_present      = new_assessment.get("intraday_present", False)

    if not existing_present:
        # Existing file has no intraday — always write (upgrade or harmless refresh)
        return "write"

    # Existing file has intraday (existing_present=True)
    if new_present:
        # Both present — freeze, skip silently
        return "skip"
    else:
        # Existing present, new absent — degradation blocked
        return "skip_warn"