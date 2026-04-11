#!/usr/bin/env python3
"""
regenerate_summaries.py

Regenerates all summary JSON files from existing raw JSON files.
No API calls needed — reads from raw/, writes to summary/.
Run this after garmin_normalizer.py has been updated.

Configuration via environment variables — see garmin_config.py.
"""

import json
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════

sys.path.insert(0, str(Path(__file__).parent))

try:
    import garmin_config as cfg
except ImportError as e:
    print(f"ERROR: Could not import garmin_config.py: {e}")
    print("Make sure garmin_config.py is in the same folder as this script.")
    sys.exit(1)

try:
    from garmin_normalizer import summarize
except ImportError as e:
    print(f"ERROR: Could not import garmin_normalizer.py: {e}")
    print("Make sure garmin_normalizer.py is in the same folder as this script.")
    sys.exit(1)

def main():
    if not cfg.RAW_DIR.exists():
        print(f"ERROR: Raw folder not found: {cfg.RAW_DIR}")
        sys.exit(1)

    cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(cfg.RAW_DIR.glob("garmin_raw_*.json"))
    print(f"Regenerating summaries from {len(raw_files)} raw files ...")
    print(f"  Raw:     {cfg.RAW_DIR}")
    print(f"  Summary: {cfg.SUMMARY_DIR}")
    print()

    ok, failed = 0, 0
    for f in raw_files:
        try:
            raw     = json.loads(f.read_text(encoding="utf-8"))
            summary = summarize(raw)
            out     = cfg.SUMMARY_DIR / f"garmin_{raw['date']}.json"
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
