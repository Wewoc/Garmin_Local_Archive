#!/usr/bin/env python3
"""
tools/migrate_quality_reclassify_v2.py

Standalone migration script — v1.5.7
Reclassifies quality_log.json from the old 4-label schema
(high / medium / low / failed) to the new 3-label schema
(high / standard / failed).

Run once with the app closed. No API calls. No lock required.

Background
----------
v1.5.7 removes "medium" and "low" as quality labels. Both are replaced by
"standard" — the device, not the data content, determines quality tier.
Device-level differentiation is handled via the new device_rank field.

This script:
  1. Creates a timestamped backup before any changes
  2. Ensures "device_rank_config" root field exists (creates {} if absent)
  3. For each entry with quality in ("medium", "low"):
       - Sets quality = "standard"
       - Reads raw file → extracts deviceId from training_status
       - Looks up device_rank from device_rank_config
       - Sets device_rank on the entry (null if device not in config)
       - Sets recheck = False
         (Known limitation: days within the 180-day window that previously
          had recheck=True will not receive an automatic retry here. They
          will be re-evaluated by the collector on next run — but only if
          the previous day has quality="high". Partieller Verlust akzeptiert.)
  4. For each "high" entry: sets device_rank if raw file is available
     and device is in config (non-destructive enhancement)
  5. Saves the corrected quality_log.json via _save_quality_log(skip_backup=True)
  6. Prints a full summary

Usage
-----
    python tools/migrate_quality_reclassify_v2.py [--dry-run]

    --dry-run   Show what would change, write nothing.

Run from the project root. App must be closed.

Known limitations
-----------------
- Tage < 180d mit früherem recheck=True bekommen keinen automatischen Retry.
  Der Collector wertet sie beim nächsten echten Lauf neu aus — aber nur wenn
  der Vortag quality="high" hat.
- Zwei Legacy-Geräte ohne deviceId kollabieren im "unknown"-Slot.
  In der Praxis gibt es genau ein solches Gerät pro Archiv.
- Bulk-Einträge haben kein training_status in der Raw-Datei →
  device_rank bleibt null. Kein Bug — dokumentiertes Verhalten.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ── Path setup — run from project root ────────────────────────────────────────
_HERE   = Path(__file__).resolve().parent        # tools/
_ROOT   = _HERE.parent                           # project root
_GARMIN = _ROOT / "garmin"

for p in [str(_ROOT), str(_GARMIN)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import garmin_config as cfg
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


def _extract_device_id(raw: dict) -> str | None:
    """
    Extracts deviceId from training_status → mostRecentTrainingStatus
    → recordedDevices. Returns str(deviceId) or None if not found.
    Falls back to "unknown" only when the field exists but is explicitly empty.
    Returns None when training_status is absent entirely.
    """
    ts = raw.get("training_status")
    if not isinstance(ts, dict):
        return None

    mrts = ts.get("mostRecentTrainingStatus")
    if not isinstance(mrts, dict):
        return None

    devices = mrts.get("recordedDevices")
    if isinstance(devices, list) and len(devices) > 0:
        device_id = devices[0].get("deviceId")
        if device_id is not None:
            return str(device_id)
        # deviceId key present but None/empty → unknown slot
        return "unknown"

    # recordedDevices absent or empty list → unknown slot
    return "unknown"


def _get_rank_from_config(device_rank_config: dict, device_id: str | None) -> int | None:
    """Returns rank from config for a device_id, or None if not configured."""
    if device_id is None:
        return None
    entry = device_rank_config.get(device_id)
    if not isinstance(entry, dict):
        return None
    return entry.get("rank")


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main(dry_run: bool = False) -> None:
    quality_log_path = cfg.QUALITY_LOG_FILE

    print("=" * 60)
    print("  migrate_quality_reclassify_v2.py — v1.5.7")
    if dry_run:
        print("  MODE: DRY RUN — nothing will be written")
    print("=" * 60)
    print(f"  quality_log : {quality_log_path}")
    print(f"  raw dir     : {cfg.RAW_DIR}")
    print()

    # ── Sanity checks ─────────────────────────────────────────────────────────
    if not quality_log_path.exists():
        print("  ERROR: quality_log.json not found — nothing to migrate.")
        sys.exit(1)

    # ── Load ──────────────────────────────────────────────────────────────────
    data = _load_quality_log()
    days = data.get("days", [])

    # Ensure device_rank_config exists
    if "device_rank_config" not in data or not isinstance(data["device_rank_config"], dict):
        data["device_rank_config"] = {}

    device_rank_config = data["device_rank_config"]

    to_reclassify = [e for e in days if e.get("quality") in ("medium", "low")]
    already_standard = sum(1 for e in days if e.get("quality") == "standard")
    high_count  = sum(1 for e in days if e.get("quality") == "high")
    failed_count = sum(1 for e in days if e.get("quality") == "failed")

    print(f"  Total entries    : {len(days)}")
    print(f"  → high           : {high_count}")
    print(f"  → medium/low     : {len(to_reclassify)}  ← will become 'standard'")
    print(f"  → already standard: {already_standard}")
    print(f"  → failed         : {failed_count}")
    print(f"  device_rank_config: {len(device_rank_config)} device(s) configured")
    print()

    if not to_reclassify and already_standard == 0:
        print("  Nothing to migrate — no medium/low/standard entries found.")
        return

    if not to_reclassify:
        print("  No medium/low entries — schema already migrated.")
        print("  Checking device_rank backfill on existing standard/high entries ...")
        print()

    # ── Backup (before any changes) ───────────────────────────────────────────
    if not dry_run:
        backup_path = _backup(quality_log_path)
        print(f"  Backup created : {backup_path.name}")
        print()
    else:
        print("  (Dry run — no backup created)")
        print()

    # ── Reclassify medium/low → standard ─────────────────────────────────────
    reclassified    = 0
    rank_set        = 0
    rank_null       = 0
    no_raw          = 0
    no_training     = 0

    print("  Reclassifying medium/low → standard ...")
    print()

    for entry in to_reclassify:
        date_str  = entry.get("date", "")
        old_label = entry.get("quality", "?")
        if not date_str:
            continue

        raw = _read_raw(date_str)
        device_id = None
        rank      = None

        if not raw:
            no_raw += 1
            # No raw file — still reclassify, device_rank stays null
            print(f"  RECLASSIFY {date_str}  {old_label} → standard  "
                  f"[no raw file — device_rank=null]")
        else:
            device_id = _extract_device_id(raw)
            if device_id is None:
                no_training += 1
                print(f"  RECLASSIFY {date_str}  {old_label} → standard  "
                      f"[no training_status — device_rank=null]")
            else:
                rank = _get_rank_from_config(device_rank_config, device_id)
                if rank is not None:
                    rank_set += 1
                    print(f"  RECLASSIFY {date_str}  {old_label} → standard  "
                          f"[device={device_id}  rank={rank}]")
                else:
                    rank_null += 1
                    print(f"  RECLASSIFY {date_str}  {old_label} → standard  "
                          f"[device={device_id}  rank=null — not in config]")

        if not dry_run:
            entry["quality"]     = "standard"
            entry["device_rank"] = rank
            entry["recheck"]     = False
            entry["reason"]      = (
                entry.get("reason", "")
                + " [migrated by migrate_quality_reclassify_v2.py v1.5.7]"
            )

        reclassified += 1

    # ── device_rank backfill for existing standard/high entries ──────────────
    # Non-destructive: only sets device_rank if currently absent (None/missing)
    backfill_set  = 0
    backfill_skip = 0

    existing_nonstd = [
        e for e in days
        if e.get("quality") in ("high", "standard")
        and e.get("device_rank") is None
        and e not in to_reclassify  # already handled above
    ]

    if existing_nonstd:
        print()
        print(f"  Backfilling device_rank for {len(existing_nonstd)} existing entries ...")

    for entry in existing_nonstd:
        date_str = entry.get("date", "")
        if not date_str:
            continue

        raw = _read_raw(date_str)
        if not raw:
            backfill_skip += 1
            continue

        device_id = _extract_device_id(raw)
        if device_id is None:
            backfill_skip += 1
            continue

        rank = _get_rank_from_config(device_rank_config, device_id)
        if rank is not None:
            if not dry_run:
                entry["device_rank"] = rank
            backfill_set += 1
        else:
            backfill_skip += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("─" * 60)
    print(f"  Reclassified      : {reclassified}  (medium/low → standard)")
    print(f"    rank set        : {rank_set}")
    print(f"    rank=null       : {rank_null}  (device not in config)")
    print(f"    no raw file     : {no_raw}")
    print(f"    no training_status: {no_training}")
    if existing_nonstd:
        print(f"  Backfill (high/std): {backfill_set} set, {backfill_skip} skipped")
    print("─" * 60)

    if dry_run:
        print()
        print("  Dry run complete — quality_log.json NOT modified.")
        return

    if reclassified == 0 and backfill_set == 0:
        print()
        print("  No changes made — quality_log.json unchanged.")
        print(f"  Backup at {backup_path.name} can be deleted manually.")
        return

    # ── Save ──────────────────────────────────────────────────────────────────
    # skip_backup=True — timestamped backup already made above.
    _save_quality_log(data, skip_backup=True)

    print()
    print(f"  quality_log.json saved.")
    print(f"  Backup retained at: {backup_path.name}")
    print()
    if rank_null > 0:
        print("  ⚠  Some entries have device_rank=null.")
        print("     Configure device ranks in the app (Settings → Devices)")
        print("     or edit device_rank_config in quality_log.json manually.")
        print()
    print("  Known limitation: days within the 180-day window with prior")
    print("  recheck=True will not receive automatic retry. The collector")
    print("  re-evaluates them on next run if the previous day is 'high'.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate quality_log.json from medium/low to standard (v1.5.7)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing anything",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
