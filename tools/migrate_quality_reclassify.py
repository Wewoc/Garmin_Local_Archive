#!/usr/bin/env python3
"""
tools/migrate_quality_reclassify.py

Standalone migration script — v1.5.6.2
Re-classifies quality_log.json entries that were wrongly stored as "medium"
due to the dead-code branch bug in assess_quality() (fixed in v1.5.6.2).

Run once with the app closed. No API calls. No lock required.

Background
----------
Before the fix, days with only totalSteps (no sleep, no restingHR) were
silently classified as "medium" because the inner condition
    if has_sleep or has_steps:
was always True when reached via has_steps — making "return low" unreachable.

After the fix the condition is:
    if has_sleep or has_hr_resting:
so steps alone no longer qualify for "medium".

This script:
  1. Loads quality_log.json
  2. Creates a timestamped backup before any changes
  3. For each entry with quality == "medium":
     reads the corresponding raw file → re-runs assess_quality()
     if result is "low" → updates the entry directly (bypasses downgrade guard)
  4. Saves the corrected quality_log.json
  5. Prints a summary

Usage
-----
    python tools/migrate_quality_reclassify.py

Run from the project root. App must be closed.
"""

import json
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# ── Path setup — run from project root ────────────────────────────────────────
_HERE   = Path(__file__).resolve().parent        # tools/
_ROOT   = _HERE.parent                           # project root
_GARMIN = _ROOT / "garmin"

for p in [str(_ROOT), str(_GARMIN)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Config ────────────────────────────────────────────────────────────────────
# GARMIN_OUTPUT_DIR must be set, or garmin_config falls back to ~/local_archive.
# The script reads the path from garmin_config so it honours the same ENV var
# as the main app and daily_update.py.

import garmin_config as cfg
from quality._assess import assess_quality
from quality._io import _load_quality_log, _save_quality_log


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _backup(quality_log_path: Path) -> Path:
    """Creates a timestamped backup of quality_log.json. Returns backup path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = quality_log_path.with_name(f"quality_log_backup_{ts}.json")
    shutil.copy2(quality_log_path, backup_path)
    return backup_path


def _read_raw(date_str: str) -> dict:
    """Reads raw file for a date. Returns {} on any failure."""
    raw_file = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
    try:
        with open(raw_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    quality_log_path = cfg.QUALITY_LOG_FILE

    print("=" * 60)
    print("  migrate_quality_reclassify.py — v1.5.6.2")
    print("=" * 60)
    print(f"  quality_log : {quality_log_path}")
    print(f"  raw dir     : {cfg.RAW_DIR}")
    print()

    # ── Sanity checks ─────────────────────────────────────────────────────────
    if not quality_log_path.exists():
        print("  ERROR: quality_log.json not found — nothing to migrate.")
        sys.exit(1)

    if not cfg.RAW_DIR.exists():
        print("  ERROR: raw/ directory not found — cannot re-read raw files.")
        sys.exit(1)

    # ── Load ──────────────────────────────────────────────────────────────────
    data = _load_quality_log()
    days = data.get("days", [])

    medium_entries = [e for e in days if e.get("quality") == "medium"]
    print(f"  Total entries  : {len(days)}")
    print(f"  medium entries : {len(medium_entries)}")
    print()

    if not medium_entries:
        print("  Nothing to migrate — no medium entries found.")
        return

    # ── Backup ────────────────────────────────────────────────────────────────
    backup_path = _backup(quality_log_path)
    print(f"  Backup created : {backup_path.name}")
    print()

    # ── Reclassify ────────────────────────────────────────────────────────────
    checked   = 0
    updated   = 0
    no_raw    = 0
    unchanged = 0

    for entry in medium_entries:
        date_str = entry.get("date", "")
        if not date_str:
            continue

        checked += 1
        raw = _read_raw(date_str)

        if not raw:
            no_raw += 1
            print(f"  SKIP  {date_str} — raw file not found or unreadable")
            continue

        new_label = assess_quality(raw)

        if new_label == "low":
            # Write directly — bypass _upsert_quality() downgrade guard,
            # which would block medium → low. This is the intended correction.
            entry["quality"] = "low"
            entry["reason"]  = entry.get("reason", "") + " [reclassified by migrate_quality_reclassify.py v1.5.6.2]"
            updated += 1
            print(f"  FIX   {date_str} — medium → low")
        else:
            unchanged += 1
            # medium that correctly stays medium (has sleep or restingHR)
            # or was already high/failed for some reason — leave untouched

    print()
    print("─" * 60)
    print(f"  Checked   : {checked}")
    print(f"  Updated   : {updated}  (medium → low)")
    print(f"  Unchanged : {unchanged}")
    print(f"  No raw    : {no_raw}  (raw file absent — skipped)")
    print("─" * 60)

    if updated == 0:
        print()
        print("  No corrections needed — quality_log.json unchanged.")
        print(f"  Backup at {backup_path.name} can be deleted manually.")
        return

    # ── Save ──────────────────────────────────────────────────────────────────
    # skip_backup=True — we made our own timestamped backup above.
    # The standard garmin_backup trigger is not needed for a one-time migration.
    _save_quality_log(data, skip_backup=True)

    print()
    print(f"  quality_log.json saved — {updated} entr{'y' if updated == 1 else 'ies'} corrected.")
    print(f"  Backup retained at: {backup_path.name}")
    print()


if __name__ == "__main__":
    main()
