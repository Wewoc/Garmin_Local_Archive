#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
regenerate_summaries.py

Regenerates all summary JSON files from the archive: from the raw JSON files in raw/ and from the
export data in the bulk store (bulk/aggregates, v1.7.6.1) — a day that has only export data and no
raw file gets its summary too, and a day with both gets the resolved summary.
No API calls needed — reads raw/ and bulk/aggregates, writes summary/ through garmin_writer
(garmin_writer.rebuild_summary, the sole owner of summary/; raw/ and its backup are never touched).
Run this after garmin_normalizer.py has been updated.

Configuration via environment variables — see garmin_config.py.
"""

import sys
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# Fixed v1.7.3.2 — sys.path resolution was one level short (this script
# used to live in export/, one level shallower than
# support-tools/archive-maintenance/, and the path math was never
# updated after the move).

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "garmin"))

try:
    import garmin_config as cfg
except ImportError as e:
    print(f"ERROR: Could not import garmin_config.py: {e}")
    print("Make sure garmin_config.py is in the same folder as this script.")
    sys.exit(1)

try:
    import garmin_writer as writer
    import garmin_bulk_writer as bulk_writer
except ImportError as e:
    print(f"ERROR: Could not import garmin_writer.py / garmin_bulk_writer.py: {e}")
    print("Make sure the garmin/ folder of the program is next to support-tools/.")
    sys.exit(1)


def _raw_days():
    """The days that have a raw file (from the file names)."""
    days = set()
    for f in cfg.RAW_DIR.glob("garmin_raw_*.json"):
        name = f.stem[len("garmin_raw_"):]
        try:
            date.fromisoformat(name)
        except ValueError:
            continue
        days.add(name)
    return days


def main():
    if not cfg.RAW_DIR.exists() and not cfg.BULK_AGG_DIR.exists():
        print(f"ERROR: Raw folder not found: {cfg.RAW_DIR}")
        sys.exit(1)

    cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

    raw_days = _raw_days() if cfg.RAW_DIR.exists() else set()
    export_days = set(bulk_writer.list_aggregate_days())
    days = sorted(raw_days | export_days)
    print(f"Regenerating summaries for {len(days)} days "
          f"({len(raw_days)} with raw files, {len(export_days)} with export data) ...")
    print(f"  Raw:     {cfg.RAW_DIR}")
    print(f"  Export:  {cfg.BULK_AGG_DIR}")
    print(f"  Summary: {cfg.SUMMARY_DIR}")
    print()

    ok, failed = 0, 0
    for day in days:
        try:
            if writer.rebuild_summary(day):
                print(f"  ✓ {day}")
                ok += 1
            else:
                print(f"  ✗ {day}: the summary could not be made (see the log lines above)")
                failed += 1
        except Exception as e:
            print(f"  ✗ {day}: {e}")
            failed += 1

    print()
    print(f"Done. {ok} regenerated, {failed} errors.")

if __name__ == "__main__":
    main()
