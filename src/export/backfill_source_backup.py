#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
backfill_source_backup.py

Einmaliges Script — kopiert alle bestehenden source/-Dateien nach backup/source/.
Ausführen einmalig nach Einführung von garmin_backup_source.py (v1.6.0.4).

Ablage: src/export/ (neben regenerate_summaries.py)
Ausführung: python export/backfill_source_backup.py
"""

import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))

# ── ENV: GARMIN_OUTPUT_DIR aus garmin_settings lesen wenn nicht gesetzt ───────
import os as _os
if not _os.environ.get("GARMIN_OUTPUT_DIR"):
    _settings_file = Path.home() / ".garmin_archive_settings.json"
    if _settings_file.exists():
        import json as _json
        try:
            _s = _json.loads(_settings_file.read_text(encoding="utf-8"))
            _base = _s.get("base_dir", "")
            if _base:
                _os.environ["GARMIN_OUTPUT_DIR"] = _base
        except Exception:
            pass

try:
    import garmin_config as cfg
except ImportError as e:
    print(f"ERROR: Could not import garmin_config.py: {e}")
    sys.exit(1)

try:
    import garmin_backup_source as backup_src
except ImportError as e:
    print(f"ERROR: Could not import garmin_backup_source.py: {e}")
    sys.exit(1)


def main() -> None:
    if not cfg.SOURCE_DIR.exists():
        print(f"ERROR: Source folder not found: {cfg.SOURCE_DIR}")
        sys.exit(1)

    total = len(list(cfg.SOURCE_DIR.glob("garmin_source_*.json")))
    needed = backup_src.check_source_backfill_needed()

    print("Source Backup Backfill")
    print(f"  Source:        {cfg.SOURCE_DIR}")
    print(f"  Backup:        {cfg.SOURCE_BACKUP_DIR}")
    print(f"  Total files:   {total}")
    print(f"  Need backup:   {needed}")
    print()

    if needed == 0:
        print("Nothing to do — all source files already backed up.")
        return

    result = backup_src.backfill_source()
    print("Done.")
    print(f"  Copied:  {result['copied']}")
    print(f"  Skipped: {result['skipped']} (already present)")
    print(f"  Failed:  {result['failed']}")

    if result["failed"] > 0:
        print()
        print("WARNING: Some files could not be copied — check log output above.")


if __name__ == "__main__":
    main()
