#!/usr/bin/env python3
"""
tools/set_device_rank_config.py

Einmalig: device_rank_config in quality_log.json befüllen.
Verwendet den gleichen Checksum-Algorithmus wie _save_quality_log().

Ausführen aus dem Repo-Root:
    python tools\set_device_rank_config.py
"""

import json
import os
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

DEVICE_RANK_CONFIG = {
    "3425438179": {"rank": 2, "name": "fenix 7X Sapphire Solar"},
    "3978475675": {"rank": 1, "name": "vívoactive 3"},
}

# ── Pfad ──────────────────────────────────────────────────────────────────────

settings_path = Path.home() / ".garmin_archive_settings.json"
if settings_path.exists():
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    base = settings.get("base_dir", "")
else:
    base = os.environ.get("GARMIN_OUTPUT_DIR", "")

if not base:
    print("ERROR: base_dir nicht gefunden.")
    sys.exit(1)

log_path = Path(base) / "garmin_data" / "log" / "quality_log.json"
if not log_path.exists():
    print(f"ERROR: quality_log.json nicht gefunden: {log_path}")
    sys.exit(1)

# ── garmin_quality importieren (korrekter Checksum-Algorithmus) ───────────────

garmin_dir = Path(__file__).parent.parent / "garmin"
sys.path.insert(0, str(garmin_dir))

from quality._io import _compute_checksum, _save_quality_log
import garmin_config as cfg

# ── Lesen ─────────────────────────────────────────────────────────────────────

data = json.loads(log_path.read_text(encoding="utf-8"))
print(f"Geladene Einträge: {len(data.get('days', []))}")
print(f"Aktueller device_rank_config: {data.get('device_rank_config', {})}")

# ── Setzen ────────────────────────────────────────────────────────────────────

data["device_rank_config"] = DEVICE_RANK_CONFIG
print(f"Neuer device_rank_config: {data['device_rank_config']}")

# ── Backup + Speichern via _save_quality_log (korrekter Checksum) ─────────────

backup_path = log_path.with_suffix(".json.bak_device_config2")
backup_path.write_bytes(log_path.read_bytes())
print(f"Backup: {backup_path}")

_save_quality_log(data, skip_backup=True)
print(f"✓ quality_log.json gespeichert (Checksum: {_compute_checksum(data)[:16]}...)")
print("Fertig — App neu starten.")
