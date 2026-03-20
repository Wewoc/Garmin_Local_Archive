#!/usr/bin/env python3
"""
regenerate_summaries.py

Regenerates all summary JSON files from existing raw JSON files.
No API calls needed — reads from raw/, writes to summary/.
Run this after garmin_collector.py has been updated.

Configuration via environment variables (all optional — hardcoded fallback below):
  GARMIN_OUTPUT_DIR    Root data folder (raw/ and summary/ live here)
"""

import json
import os
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — edit fallback value here, or set GARMIN_OUTPUT_DIR env variable.
#  Environment variable always takes priority over the value below.
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR    = Path(os.environ.get("GARMIN_OUTPUT_DIR",
                   r"C:\Users\timos\OneDrive\Desktop\Pen-and-Paper\Garmin\garmin_data"))
RAW_DIR     = BASE_DIR / "raw"
SUMMARY_DIR = BASE_DIR / "summary"

# ══════════════════════════════════════════════════════════════════════════════

# Import summarize() from garmin_collector.py in the same folder
sys.path.insert(0, str(Path(__file__).parent))
try:
    from garmin_collector import summarize
except ImportError as e:
    print(f"ERROR: Could not import garmin_collector.py: {e}")
    print("Make sure garmin_collector.py is in the same folder as this script.")
    sys.exit(1)

def main():
    if not RAW_DIR.exists():
        print(f"ERROR: Raw folder not found: {RAW_DIR}")
        sys.exit(1)

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(RAW_DIR.glob("garmin_raw_*.json"))
    print(f"Regenerating summaries from {len(raw_files)} raw files ...")
    print(f"  Raw:     {RAW_DIR}")
    print(f"  Summary: {SUMMARY_DIR}")
    print()

    ok, failed = 0, 0
    for f in raw_files:
        try:
            raw     = json.loads(f.read_text(encoding="utf-8"))
            summary = summarize(raw)
            out     = SUMMARY_DIR / f"garmin_{raw['date']}.json"
            out.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"  ✓ {raw['date']}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {f.name}: {e}")
            failed += 1

    print()
    print(f"Done. {ok} regenerated, {failed} errors.")

if __name__ == "__main__":
    main()
