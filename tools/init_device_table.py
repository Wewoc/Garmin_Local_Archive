#!/usr/bin/env python3
"""
tools/init_device_table.py

Einmalig: device_table.json initial befüllen.

Weist historische Einträge (device_rank=null) per Datum zu:
  - Einträge vor dem ersten Datum des höchsten Geräts → Rank des niedrigsten Geräts
  - Einträge ab dem ersten Datum des höchsten Geräts → dessen Rank

Liest device_rank_config aus quality_log.json.
Schreibt device_rank in die Einträge + device_table.json.

Ausführen aus dem Repo-Root:
    python tools\\init_device_table.py
"""

import json
import os
import sys
from pathlib import Path
from datetime import date

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

# ── garmin_quality importieren ────────────────────────────────────────────────

garmin_dir = Path(__file__).parent.parent / "garmin"
sys.path.insert(0, str(garmin_dir))

from quality._io import _compute_checksum, _save_quality_log, save_device_table
import garmin_config as cfg

# ── Lesen ─────────────────────────────────────────────────────────────────────

data = json.loads(log_path.read_text(encoding="utf-8"))
device_rank_config = data.get("device_rank_config", {})

if not device_rank_config:
    print("ERROR: device_rank_config ist leer — zuerst set_device_rank_config.py ausführen.")
    sys.exit(1)

print(f"Geladene Einträge: {len(data.get('days', []))}")
print(f"Geräte in Config: {list(device_rank_config.keys())}")

# ── Cutoff-Datum aus devices-Array ────────────────────────────────────────────
# Das Gerät mit dem höchsten Rank (bestes Gerät) hat ein first_used Datum —
# alle Einträge ab diesem Datum gehören zu diesem Gerät, alle davor zum nächsten.

devices_list = data.get("devices", [])
devices_by_id = {str(d["id"]): d for d in devices_list if "id" in d}

# Rank → device_id mapping
rank_to_id = {}
for dev_id, dev_cfg in device_rank_config.items():
    r = dev_cfg.get("rank")
    if r is not None:
        rank_to_id[r] = dev_id

sorted_ranks = sorted(rank_to_id.keys())
print(f"\nRank-Reihenfolge: {sorted_ranks}")
for r in sorted_ranks:
    dev_id = rank_to_id[r]
    name   = device_rank_config[dev_id].get("name", "?")
    dev    = devices_by_id.get(dev_id, {})
    fu     = dev.get("first_used", "unbekannt")
    print(f"  Rank {r}: {name} (ID: {dev_id}, first_used: {fu})")

# Cutoff-Daten: für jeden Rank ab wann er gilt
# Sortiert: niedrigster Rank = ältestes Gerät, höchster Rank = neuestes
cutoffs = {}  # rank → date ab dem dieses Gerät aktiv ist
for r in sorted_ranks:
    dev_id = rank_to_id[r]
    dev    = devices_by_id.get(dev_id, {})
    fu     = dev.get("first_used")
    if fu and fu != "unknown":
        try:
            cutoffs[r] = fu[:10]  # ISO date
        except Exception:
            pass

print(f"\nCutoff-Daten: {cutoffs}")

# ── Einträge zuweisen ─────────────────────────────────────────────────────────

assigned = 0
skipped  = 0

for entry in data["days"]:
    if entry.get("device_rank") is not None:
        skipped += 1
        continue

    entry_date = entry.get("date", "")
    if not entry_date:
        continue

    # Finde den passenden Rank für dieses Datum
    # Geht von höchstem Rank rückwärts — erstes Gerät dessen Cutoff <= entry_date
    assigned_rank = sorted_ranks[0]  # Default: ältestes Gerät
    for r in sorted(sorted_ranks, reverse=True):
        cutoff = cutoffs.get(r)
        if cutoff and entry_date >= cutoff:
            assigned_rank = r
            break

    entry["device_rank"] = assigned_rank
    assigned += 1

print(f"\nZugewiesen: {assigned} Einträge")
print(f"Übersprungen (bereits gesetzt): {skipped} Einträge")

# ── Speichern ─────────────────────────────────────────────────────────────────

backup_path = log_path.with_suffix(".json.bak_init_device_table")
backup_path.write_bytes(log_path.read_bytes())
print(f"Backup: {backup_path}")

_save_quality_log(data, skip_backup=True)
print("✓ quality_log.json gespeichert")

# ── device_table.json schreiben ───────────────────────────────────────────────

save_device_table(data)
print(f"✓ device_table.json geschrieben: {cfg.DEVICE_TABLE_FILE}")
print("\nFertig — App neu starten um die Tabelle zu sehen.")
