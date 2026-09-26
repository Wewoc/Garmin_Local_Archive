#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
compare_raw_source.py

Read-only diagnostic: compares two garmin_raw_*.json files structurally to
check whether the bulk/api size gap (~14.5 KB vs ~1 KB, per Timo's finding)
is a client-side extraction gap or points to a server-side difference.

Does NOT call the Garmin API. Only reads existing raw/ files and reports:
  - file size + ratio
  - top-level keys present only in one side, or in both
  - for keys in both: rough content comparison (dict/list length, or value)
  - cross-reference against the fields load_bulk() (garmin_import.py) is
    known to never populate: hrv, spo2, body_battery, respiration,
    activities, training_status, training_readiness, race_predictions,
    max_metrics

A key missing entirely from the bulk raw file confirms client-side
extraction gap (load_bulk() never wrote it) for that date. It does not
rule out a server-side cause for other dates/fields — that needs an actual
API re-fetch of the bulk-sourced day for direct comparison.

Usage:
    python compare_raw_source.py [date_bulk] [date_api]

    Defaults to 2023-12-31 (bulk) vs 2024-01-01 (api) if omitted.
    Reads GARMIN_OUTPUT_DIR (falls back to garmin_config default) to find
    garmin_data/raw/garmin_raw_<date>.json for each side.
"""

import json
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_ROOT   = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_SRC_ROOT / "garmin"))

import garmin_config as cfg  # noqa: E402

# Fields load_bulk() (garmin_import.py) has no extraction logic for at all —
# structurally absent from any bulk raw file, regardless of date/device.
KNOWN_BULK_GAP_FIELDS = {
    "hrv", "spo2", "body_battery", "respiration", "activities",
    "training_status", "training_readiness", "race_predictions",
    "max_metrics",
}


def _describe(value) -> str:
    if isinstance(value, dict):
        return f"dict[{len(value)} keys]"
    if isinstance(value, list):
        return f"list[{len(value)} items]"
    return repr(value)


def _load(date_str: str) -> tuple[dict, int]:
    path = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)
    size = path.stat().st_size
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, size


def main(date_bulk: str, date_api: str) -> None:
    print("=" * 70)
    print("  compare_raw_source.py")
    print(f"  Raw dir : {cfg.RAW_DIR}")
    print(f"  Bulk day: {date_bulk}")
    print(f"  API day : {date_api}")
    print("=" * 70)

    bulk_data, bulk_size = _load(date_bulk)
    api_data,  api_size  = _load(date_api)

    ratio = (api_size / bulk_size) if bulk_size else float("inf")
    print()
    print(f"  Size (bulk, {date_bulk}) : {bulk_size:>8} bytes")
    print(f"  Size (api,  {date_api})  : {api_size:>8} bytes")
    print(f"  Ratio api/bulk           : {ratio:.2f}x")

    bulk_keys = set(bulk_data.keys())
    api_keys  = set(api_data.keys())

    only_bulk = sorted(bulk_keys - api_keys)
    only_api  = sorted(api_keys - bulk_keys)
    common    = sorted(bulk_keys & api_keys)

    print()
    print(f"  Top-level keys — bulk only ({len(only_bulk)}):")
    for k in only_bulk:
        flag = "  [known bulk-gap field]" if k in KNOWN_BULK_GAP_FIELDS else ""
        print(f"    {k}{flag}")

    print()
    print(f"  Top-level keys — api only ({len(only_api)}):")
    for k in only_api:
        flag = "  [known bulk-gap field]" if k in KNOWN_BULK_GAP_FIELDS else ""
        print(f"    {k}{flag}")

    print()
    print(f"  Top-level keys — in both ({len(common)}):")
    for k in common:
        print(f"    {k:<22} bulk={_describe(bulk_data[k]):<20} api={_describe(api_data[k])}")

    print()
    print("=" * 70)
    gap_missing_from_bulk = sorted(KNOWN_BULK_GAP_FIELDS & set(only_api))
    gap_present_in_bulk   = sorted(KNOWN_BULK_GAP_FIELDS & (bulk_keys | api_keys) - set(only_api))
    print(f"  Known bulk-gap fields missing from bulk raw : {gap_missing_from_bulk or 'none'}")
    if gap_present_in_bulk:
        print(f"  Known bulk-gap fields present in bulk raw   : {gap_present_in_bulk}"
              f"  <-- unexpected, worth a closer look")
    print("=" * 70)
    print("  NOTE: a key missing from the bulk file confirms a client-side")
    print("  extraction gap (load_bulk() never wrote it) for THIS date/device.")
    print("  It does not prove or disprove a server-side limit for other")
    print("  dates or devices — that needs an actual API re-fetch to compare.")
    print("=" * 70)


if __name__ == "__main__":
    d_bulk = sys.argv[1] if len(sys.argv) > 1 else "2023-12-31"
    d_api  = sys.argv[2] if len(sys.argv) > 2 else "2024-01-01"
    main(d_bulk, d_api)
