#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
tests/fixtures_netz2.py

Netz 2 (Fixtures + Tests) — Regressionsschutz-Fixtures, laufzeit-generiert
(kein Repo-Ballast, analog zum bestehenden #5-Roundtrip-Muster in
test_local.py). Diagnose-Werkstatt ist gla-netz2/ — eine getrennte Rolle
(siehe NOTES_v1658.md, Entscheidung C): baut Fehlerzustände, ruft die
echte Kernfunktion auf, beobachtet und berichtet, verändert aber nichts
am Produktivcode und asserted nichts. Dieses Modul hier ist der daraus
abgeleitete, dauerhafte Regressionsschutz.

Aufteilung (Entscheidung, Bauauftrag Priorität 1): einzelne Datei, kein
_health.py-Baustein unter einer Fassade. Bei aktuell nur einer fertigen
Pipeline (Health) bringt die Aufspaltung keinen Vorteil, nur zusätzliche
Indirektion. Funktionen sind bewusst mit "raw_"/"source_" statt generischem
Namen präfixiert und thematisch gruppiert, damit ein späterer Umzug nach
tests/fixtures_netz2/_health.py (mit dünner __init__.py-Fassade, sobald
FIT oder Context andocken — siehe NOTES_v1658.md Entscheidung B) ein
reiner Verschiebe-Schritt bleibt, kein Umbau.

Deckt aktuell ab: Silo-Repair-Testlücken
  #1 — raw_without_quality (Backfill, _backfill_quality_log())
  #3 — source_without_raw (In-Process-Replay, inkl. F8-Schlechtfall)
  #7 — raw_without_summary (Inline summarize() + write_day())
"""

import json
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
#  #1 — raw_without_quality (Backfill)
# ══════════════════════════════════════════════════════════════════════════════

def raw_minimal(date_str: str) -> dict:
    """Minimal valides Raw-Dict für Backfill-Fixtures — nur date + ein Feld,
    genug für assess_quality(). Kein Anspruch auf ein bestimmtes Label,
    Testlücke #1 prüft nur den Backfill-Mechanismus, nicht das Label."""
    return {"date": date_str, "heart_rates": {"restingHeartRate": 55}}


def write_raw_file(raw_dir: Path, date_str: str, content: dict = None) -> Path:
    """Schreibt eine gültige garmin_raw_{date}.json. content=None → raw_minimal()."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"garmin_raw_{date_str}.json"
    path.write_text(json.dumps(content or raw_minimal(date_str)), encoding="utf-8")
    return path


def write_corrupt_raw_file(raw_dir: Path, date_str: str) -> Path:
    """Schreibt eine garmin_raw_{date}.json mit kaputtem JSON — für den
    Schlechtfall-A-Check: _backfill_quality_log() fängt (OSError,
    JSONDecodeError) intern mit pass ab, siehe NOTES_v1658.md."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"garmin_raw_{date_str}.json"
    path.write_text("{not valid json", encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  #3 — source_without_raw (In-Process-Replay)
# ══════════════════════════════════════════════════════════════════════════════

def source_raw_good(date_str: str) -> dict:
    """Source-Raw mit korrekt geformten heartRateValues ([ts, val]-Paaren) —
    Gutfall, normalize()/summarize()-fähig, ergibt Label 'high' und einen
    korrekt berechneten avg_bpm."""
    return {
        "date": date_str,
        "heart_rates": {
            "restingHeartRate": 55,
            "heartRateValues": [[0, 58], [60000, 62], [120000, 60]],
        },
    }


def source_raw_malformed_heartrate(date_str: str) -> dict:
    """Source-Raw mit strukturell falsch geformtem heartRateValues (flache
    Liste statt [ts, val]-Paaren) — Fund F8 (v1.6.5.8, Netz 2 Priorität 1).
    assess_quality()/assess_quality_fields() prüfen nur, ob die Liste
    nicht-leer ist, nicht ihre innere Struktur — das Label bleibt 'high'.
    _parse_list_values() verschluckt die falsche Form still: avg_bpm wird
    null, resting_bpm/max_bpm/min_bpm (separate Felder) bleiben korrekt.
    Kein Crash, kein status='error'. Empirisch nachgewiesen in
    gla-netz2/output/NETZ2_BEFUND_v1658_01.md — siehe dort und
    NOTES_v1658.md für den vollständigen Befund."""
    return {
        "date": date_str,
        "heart_rates": {
            "restingHeartRate": 55,
            "heartRateValues": [58, 62, 60],
        },
    }


def write_source_file(source_dir: Path, date_str: str, content: dict) -> Path:
    """Schreibt eine garmin_source_{date}.json mit beliebigem Inhalt."""
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"garmin_source_{date_str}.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
#  #7 — raw_without_summary (Inline summarize() + write_day())
# ══════════════════════════════════════════════════════════════════════════════

def raw_without_date_field() -> dict:
    """Raw-Dict ohne 'date'-Schlüssel — Schlechtfall #7. Der Dateiname beim
    Reparieren kommt aus dem Finding (date_str-Parameter von repair_silos),
    nicht aus dem Rohinhalt — summary['date'] wird dagegen null, weil
    summarize() raw.get('date') liest. Siehe NOTES_v1658.md, Befund #7."""
    return {"heart_rates": {"restingHeartRate": 55}}


# ══════════════════════════════════════════════════════════════════════════════
#  Steps-Backfill Silo-Async-Zustand (Priorität 2 Punkt 2, patch_source_field)
# ══════════════════════════════════════════════════════════════════════════════

def write_corrupt_source_file(source_dir: Path, date_str: str) -> Path:
    """Schreibt eine VORHANDENE, aber ungültige garmin_source_{date}.json —
    trifft gezielt den except (json.JSONDecodeError, OSError)-Pfad in
    patch_source_field(). Analog write_corrupt_raw_file() für #1, aber für
    den Silo-Async-Regressionstest von _run_steps_backfill(). Testdouble-
    Entscheidung aus gla-netz2 (siehe NOTES_v1658.md): eine FEHLENDE
    source/-Datei ist bewusst kein Fehlerfall (patch_source_field() gibt
    dort True/No-Op zurück) — nur eine vorhandene, aber korrupte Datei
    trifft den Fehlerpfad."""
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"garmin_source_{date_str}.json"
    path.write_text("{not valid json", encoding="utf-8")
    return path
