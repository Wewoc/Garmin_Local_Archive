#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
backfill_source_intraday.py

One-time backfill: adds intraday_present to existing source_api_log.json entries.

Iterates all garmin_source_*.json files in SOURCE_DIR, assesses each via
garmin_source_quality.assess_source(), and patches the existing log entry with
intraday_present. Entries without a log entry are skipped — this script only
patches, never creates new entries.

Idempotent: entries that already have intraday_present are skipped.

Usage:
    python export/backfill_source_intraday.py [--dry-run]

Output:
    N patched, M skipped (already set), K no log entry, L errors

Run once after upgrading to v1.6.0.4.6. Safe to re-run.
"""

import json
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_ROOT   = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SRC_ROOT / "garmin"))

import garmin_config as cfg         # noqa: E402
import garmin_source_quality as _sq  # noqa: E402


def main(dry_run: bool = False) -> None:
    print("=" * 60)
    print("  backfill_source_intraday.py")
    print(f"  Source dir : {cfg.SOURCE_DIR}")
    print(f"  Log file   : {cfg.SOURCE_API_LOG}")
    if dry_run:
        print("  Mode       : DRY RUN — no changes written")
    print("=" * 60)

    if not cfg.SOURCE_DIR.exists():
        print(f"ERROR: SOURCE_DIR not found: {cfg.SOURCE_DIR}")
        sys.exit(1)

    # ── Load existing log ─────────────────────────────────────────────────────
    log_data: dict = {}
    if cfg.SOURCE_API_LOG.exists():
        try:
            log_data = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"ERROR: Could not read source_api_log.json: {e}")
            sys.exit(1)
    else:
        print("WARNING: source_api_log.json not found — nothing to patch.")
        sys.exit(0)

    # ── Iterate source files ──────────────────────────────────────────────────
    source_files = sorted(cfg.SOURCE_DIR.glob("garmin_source_*.json"))
    if not source_files:
        print("No source files found — nothing to do.")
        sys.exit(0)

    print(f"  Source files found: {len(source_files)}")
    print()

    patched      = 0
    already_set  = 0
    no_log_entry = 0
    errors       = 0

    for src_file in source_files:
        # Extract date from filename: garmin_source_YYYY-MM-DD.json
        stem = src_file.stem  # garmin_source_YYYY-MM-DD
        date_str = stem.replace("garmin_source_", "")

        entry = log_data.get(date_str)

        if entry is None:
            no_log_entry += 1
            print(f"  SKIP (no log entry) : {date_str}")
            continue

        if "intraday_present" in entry:
            already_set += 1
            print(f"  SKIP (already set)  : {date_str} — intraday_present={entry['intraday_present']}")
            continue

        # Assess the source file
        try:
            raw_data   = json.loads(src_file.read_text(encoding="utf-8"))
            assessment = _sq.assess_source(raw_data)
            intraday   = assessment["intraday_present"]
        except Exception as e:
            errors += 1
            print(f"  ERROR               : {date_str} — {e}")
            continue

        if dry_run:
            print(f"  WOULD PATCH         : {date_str} — intraday_present={intraday}")
            patched += 1
            continue

        entry["intraday_present"] = intraday
        log_data[date_str] = entry
        patched += 1
        print(f"  PATCHED             : {date_str} — intraday_present={intraday}")

    # ── Write patched log atomically ──────────────────────────────────────────
    if not dry_run and patched > 0:
        tmp = cfg.SOURCE_API_LOG.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(log_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                with open(tmp, "rb") as f:
                    os.fsync(f.fileno())
            except OSError:
                pass  # fsync not supported on all platforms/filesystems
            os.replace(tmp, cfg.SOURCE_API_LOG)
        except Exception as e:
            print(f"\nERROR: Could not write patched log: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if dry_run:
        print("  DRY RUN complete")
        print(f"  Would patch  : {patched}")
    else:
        print("  Done")
        print(f"  Patched      : {patched}")
    print(f"  Already set  : {already_set}")
    print(f"  No log entry : {no_log_entry}")
    print(f"  Errors       : {errors}")
    print("=" * 60)

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
