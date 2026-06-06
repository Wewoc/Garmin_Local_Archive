#!/usr/bin/env python3
"""
tools/extract_device_per_day.py

Extracts the recorded device(s) per day from all raw Garmin files.
Output: CSV with date, device_name, device_id, file_size_bytes.

Usage
-----
    python tools/extract_device_per_day.py

Run from project root. Uses GARMIN_OUTPUT_DIR if set, otherwise ~/local_archive.
Output file: tools/device_per_day.csv
"""

import csv
import json
import os
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_GARMIN = _ROOT / "garmin"

for p in [str(_ROOT), str(_GARMIN)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import garmin_config as cfg

# ── Output ─────────────────────────────────────────────────────────────────────
OUTPUT_FILE = _HERE / "device_per_day.csv"


def _extract_devices(raw: dict) -> list[dict]:
    """
    Extracts recorded devices from a raw dict.
    Returns list of {device_id, device_name} dicts.
    Falls back to latestTrainingStatusData keys if recordedDevices absent.
    """
    try:
        ts = raw.get("training_status") or {}
        most_recent = ts.get("mostRecentTrainingStatus") or {}
        recorded = most_recent.get("recordedDevices")
        if isinstance(recorded, list) and recorded:
            result = []
            for d in recorded:
                if isinstance(d, dict):
                    result.append({
                        "device_id":   str(d.get("deviceId", "unknown")),
                        "device_name": str(d.get("deviceName", "unknown")),
                    })
            if result:
                return result

        # Fallback: device IDs from latestTrainingStatusData keys
        latest = most_recent.get("latestTrainingStatusData") or {}
        if isinstance(latest, dict) and latest:
            return [{"device_id": str(k), "device_name": "unknown"} for k in latest.keys()]

    except Exception:
        pass

    return [{"device_id": "unknown", "device_name": "unknown"}]


def main() -> None:
    raw_dir = cfg.RAW_DIR

    print("=" * 60)
    print("  extract_device_per_day.py")
    print("=" * 60)
    print(f"  raw dir : {raw_dir}")
    print(f"  output  : {OUTPUT_FILE}")
    print()

    if not raw_dir.exists():
        print("  ERROR: raw/ directory not found.")
        sys.exit(1)

    raw_files = sorted(raw_dir.glob("garmin_raw_*.json"))
    print(f"  Files found: {len(raw_files)}")
    print()

    rows = []
    errors = 0

    for f in raw_files:
        date_str = f.stem.replace("garmin_raw_", "")
        file_size = f.stat().st_size

        try:
            with open(f, encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as e:
            print(f"  SKIP {date_str} — {e}")
            errors += 1
            continue

        devices = _extract_devices(raw)
        for d in devices:
            rows.append({
                "date":            date_str,
                "device_name":     d["device_name"],
                "device_id":       d["device_id"],
                "file_size_bytes": file_size,
            })

    # ── Write CSV ──────────────────────────────────────────────────────────────
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "device_name", "device_id", "file_size_bytes"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Rows written : {len(rows)}")
    print(f"  Errors       : {errors}")
    print()

    # ── Summary per device ─────────────────────────────────────────────────────
    from collections import defaultdict
    device_sizes: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        device_sizes[row["device_name"]].append(row["file_size_bytes"])

    print("  Device summary:")
    print(f"  {'Device':<30} {'Days':>6} {'Avg KB':>8} {'Min KB':>8} {'Max KB':>8}")
    print("  " + "-" * 64)
    for name, sizes in sorted(device_sizes.items()):
        avg_kb = sum(sizes) / len(sizes) / 1024
        min_kb = min(sizes) / 1024
        max_kb = max(sizes) / 1024
        print(f"  {name:<30} {len(sizes):>6} {avg_kb:>8.1f} {min_kb:>8.1f} {max_kb:>8.1f}")

    print()
    print(f"  CSV saved to: {OUTPUT_FILE}")
    print()


if __name__ == "__main__":
    main()
