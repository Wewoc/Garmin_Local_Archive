#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
restore_migration_snapshot.py

TRACK-MIGRATION v1.7.6.3 — the way back of the archive migration.

Lists the safety copies the migration made before it rewrote raw/ and summary/
(garmin_data/backup/migration/) and puts one of them back: raw/ and summary/ files that differ
from the copy are replaced byte for byte, the quality-log entries of those days come back, days
that are not in the copy stay as they are. Nothing is deleted.

Close the app and stop the background timer first. No API call, no login.

Configuration via environment variables — see garmin_config.py (GARMIN_OUTPUT_DIR).

Usage:
  python restore_migration_snapshot.py --list
  python restore_migration_snapshot.py migration_2026-10-26_101500.zip --dry-run
  python restore_migration_snapshot.py migration_2026-10-26_101500.zip
"""

import argparse
import sys
from pathlib import Path

# garmin/ must be on sys.path for all pipeline imports (this script lives two levels below src/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "garmin"))

try:
    import garmin_config as cfg
    import garmin_migration_snapshot as snap
except ImportError as e:
    print(f"ERROR: Could not import the pipeline modules: {e}")
    sys.exit(1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="List or restore a safety copy made by the archive migration.")
    parser.add_argument("name", nargs="?", help="file name of the copy (see --list) or a full path")
    parser.add_argument("--list", action="store_true", help="list the copies, oldest first (the oldest is the original state)")
    parser.add_argument("--dry-run", action="store_true", help="check the copy and count what would be put back, write nothing")
    args = parser.parse_args(argv)

    copies = snap.list_snapshots()
    if args.list or not args.name:
        if not copies:
            print(f"No copies in {cfg.MIGRATION_BACKUP_DIR}")
            return 0
        for c in copies:
            v = snap.verify_snapshot(c["path"])
            state = "ok" if v["ok"] else "DAMAGED: " + "; ".join(v["problems"][:2])
            print(f"  {c['name']}  {c['bytes'] // 1048576} MB  {v['raw']} raw, {v['summary']} summary, "
                  f"log {'yes' if v['log'] else 'no'}  [{state}]")
        if not args.name:
            print("\nName a copy to restore it (add --dry-run to only count).")
        return 0

    path = Path(args.name)
    if not path.is_absolute() and not path.exists():
        path = cfg.MIGRATION_BACKUP_DIR / args.name
    if not path.exists():
        print(f"ERROR: copy not found: {path}")
        return 1

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"{mode}Restoring {path.name} ...")
    res = snap.restore_snapshot(path, dry_run=args.dry_run)
    if res.get("reason"):
        print(f"ERROR: the copy was refused ({res['reason']}): " + "; ".join(res.get("problems", [])[:3]))
        return 1
    print(f"{mode}{res['restored']} day(s) {'would be ' if args.dry_run else ''}put back, {res['unchanged']} unchanged, "
          f"{len(res['failed'])} failed, {res['log_entries']} quality-log entr{'y' if res['log_entries'] == 1 else 'ies'} restored")
    for what, why in res["failed"][:10]:
        print(f"  x {what}: {why}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
