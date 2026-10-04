#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_silo_repair.py — garmin_silo_repair

Run from the project folder:
    python tests/test_silo_repair.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_quality as quality

# ══════════════════════════════════════════════════════════════════════════════
#  I. garmin_silo_repair (v1.6.5.7)
# ══════════════════════════════════════════════════════════════════════════════
section("I. garmin_silo_repair (v1.6.5.7)")
import garmin_silo_repair as silo_repair
importlib.reload(silo_repair)

# First delivery, deliberately scoped to what's safely testable without
# reading further internals: return structure, and the #5 (orphan-unlink)
# round trip. #1 depends on _backfill_quality_log()'s internal contract
# (not read this session) and #3/#7 need a normalize()-safe raw fixture
# (not built this session) — both deferred, not silently skipped.

_sr_empty_fresh = {
    "raw_without_quality": [], "source_without_raw": [],
    "summary_without_raw": [], "raw_without_summary": [],
}

# ── empty fresh dict → no-op, structured return present ──────────────────────
_sr_empty_result = silo_repair.repair_silos(_sr_empty_fresh)
check("silo_repair: returns dict",
      isinstance(_sr_empty_result, dict))
check("silo_repair: key ok present",
      "ok" in _sr_empty_result)
check("silo_repair: key failed present",
      "failed" in _sr_empty_result)
check("silo_repair: key items present",
      "items" in _sr_empty_result)
check("silo_repair: empty fresh → ok=0",
      _sr_empty_result["ok"] == 0)
check("silo_repair: empty fresh → failed=0",
      _sr_empty_result["failed"] == 0)
check("silo_repair: empty fresh → items=[]",
      _sr_empty_result["items"] == [])

# ── #5: orphan summary → unlink round trip ────────────────────────────────────
_sr5_sum_dir = _TMPDIR / "garmin_data" / "summary"
_sr5_sum_dir.mkdir(parents=True, exist_ok=True)
_sr5_date = "2024-11-10"
_sr5_file = _sr5_sum_dir / f"garmin_{_sr5_date}.json"
_sr5_file.write_text('{"date": "2024-11-10"}', encoding="utf-8")
check("silo_repair: #5 fixture — orphan file exists before repair",
      _sr5_file.exists())

_sr5_fresh = {**_sr_empty_fresh, "summary_without_raw": [date.fromisoformat(_sr5_date)]}
_sr5_result = silo_repair.repair_silos(_sr5_fresh)

check("silo_repair: #5 orphan removed from disk",
      not _sr5_file.exists())
check("silo_repair: #5 result ok=1",
      _sr5_result["ok"] == 1)
check("silo_repair: #5 result failed=0",
      _sr5_result["failed"] == 0)
check("silo_repair: #5 item category=5",
      _sr5_result["items"][0]["category"] == "5")
check("silo_repair: #5 item status=repaired",
      _sr5_result["items"][0]["status"] == "repaired")
check("silo_repair: #5 item date matches",
      _sr5_result["items"][0]["date"] == _sr5_date)

# ── #5: already gone → status=gone, not counted as ok or failed ──────────────
_sr5b_result = silo_repair.repair_silos(_sr5_fresh)  # same date, file now gone
check("silo_repair: #5 already-gone → status=gone",
      _sr5b_result["items"][0]["status"] == "gone")
check("silo_repair: #5 already-gone → ok=0",
      _sr5b_result["ok"] == 0)
check("silo_repair: #5 already-gone → failed=0",
      _sr5b_result["failed"] == 0)

# ══════════════════════════════════════════════════════════════════════════════
#  I2. garmin_silo_repair — Netz 2 Priorität 1 (v1.6.5.8)
#      Testlücken #1/#3/#7 — isolierter Tmpdir, analog dem Section-G-Muster
#      (silo_check "clean silo"-Isolation) — vermeidet Kontamination durch
#      raw/-Dateien anderer Sektionen (z. B. Section 5, PIPELINE_E2E), die
#      ohne quality_log-Eintrag im gemeinsamen _TMPDIR liegen bleiben und
#      #1s exakte ok==N-Erwartung sonst verfälschen würden.
# ══════════════════════════════════════════════════════════════════════════════
section("I2. garmin_silo_repair — Netz 2 Priorität 1 (v1.6.5.8)")
import fixtures_netz2 as fx

_i2_orig_env = os.environ["GARMIN_OUTPUT_DIR"]
_i2_dir      = Path(tempfile.mkdtemp(prefix="garmin_i2_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_i2_dir)
importlib.reload(cfg)
importlib.reload(silo_repair)

_i2_empty_fresh = {
    "raw_without_quality": [], "source_without_raw": [],
    "summary_without_raw": [], "raw_without_summary": [],
}

# ── #1a: Gutfall — N valide Raw-Dateien ohne quality_log-Eintrag ────────────
_i2_dates = ["2025-01-10", "2025-01-11", "2025-01-12"]
for _d in _i2_dates:
    fx.write_raw_file(cfg.RAW_DIR, _d)

_i2_1a_fresh  = {**_i2_empty_fresh,
                 "raw_without_quality": [date.fromisoformat(_d) for _d in _i2_dates]}
_i2_1a_result = silo_repair.repair_silos(_i2_1a_fresh)

check("silo_repair: #1 gutfall → ok == N",
      _i2_1a_result["ok"] == len(_i2_dates))
check("silo_repair: #1 gutfall → failed == 0",
      _i2_1a_result["failed"] == 0)
check("silo_repair: #1 gutfall → item[0] == erwartete Struktur",
      _i2_1a_result["items"][0] == {"category": "1", "date": None,
                                     "status": "backfilled", "count": len(_i2_dates)})

for _d in _i2_dates:
    (cfg.RAW_DIR / f"garmin_raw_{_d}.json").unlink(missing_ok=True)

# ── #1b: Schlechtfall A — eine korrupte Raw-Datei zusätzlich zu validen ─────
# _backfill_quality_log() fängt (OSError, JSONDecodeError) intern mit pass
# ab — kein Fehler in repair_silos(), added-Count einfach niedriger
# (stilles Skip-Verhalten, kein Bug — siehe NOTES_v1658.md).
_i2_1b_valid = ["2025-02-10", "2025-02-11"]
for _d in _i2_1b_valid:
    fx.write_raw_file(cfg.RAW_DIR, _d)
fx.write_corrupt_raw_file(cfg.RAW_DIR, "2025-02-12")

_i2_1b_fresh  = {**_i2_empty_fresh, "raw_without_quality": [date(2025, 2, 10)]}
_i2_1b_result = silo_repair.repair_silos(_i2_1b_fresh)

check("silo_repair: #1 schlechtfall A → kein Fehler trotz kaputter Datei",
      _i2_1b_result["failed"] == 0)
check("silo_repair: #1 schlechtfall A → nur valide Dateien gezählt",
      _i2_1b_result["items"][0]["count"] == len(_i2_1b_valid))

for _d in _i2_1b_valid:
    (cfg.RAW_DIR / f"garmin_raw_{_d}.json").unlink(missing_ok=True)
(cfg.RAW_DIR / "garmin_raw_2025-02-12.json").unlink(missing_ok=True)

# ── #1c: Schlechtfall B — _save_quality_log() schlägt fehl ─────────────────
# Einziger Pfad, der für Kategorie #1 tatsächlich in repair_silos()s
# eigenem except Exception landet (siehe NOTES_v1658.md).
fx.write_raw_file(cfg.RAW_DIR, "2025-03-10")
_i2_1c_fresh = {**_i2_empty_fresh, "raw_without_quality": [date(2025, 3, 10)]}

with patch.object(silo_repair.quality, "_save_quality_log",
                  side_effect=OSError("disk full (simuliert)")):
    _i2_1c_result = silo_repair.repair_silos(_i2_1c_fresh)

check("silo_repair: #1 schlechtfall B → failed=1",
      _i2_1c_result["failed"] == 1)
check("silo_repair: #1 schlechtfall B → item status=error",
      _i2_1c_result["items"][0]["status"] == "error")
check("silo_repair: #1 schlechtfall B → item category=1",
      _i2_1c_result["items"][0]["category"] == "1")
check("silo_repair: #1 schlechtfall B → reason gesetzt",
      bool(_i2_1c_result["items"][0].get("reason")))

(cfg.RAW_DIR / "garmin_raw_2025-03-10.json").unlink(missing_ok=True)

# ── #3a: Gutfall — source_without_raw, valide heartRateValues ──────────────
_i2_3a_date = "2025-04-01"
fx.write_source_file(cfg.SOURCE_DIR, _i2_3a_date, fx.source_raw_good(_i2_3a_date))

_i2_3a_fresh  = {**_i2_empty_fresh, "source_without_raw": [date.fromisoformat(_i2_3a_date)]}
_i2_3a_result = silo_repair.repair_silos(_i2_3a_fresh)

check("silo_repair: #3 gutfall → ok=1",
      _i2_3a_result["ok"] == 1)
check("silo_repair: #3 gutfall → item category=3",
      _i2_3a_result["items"][0]["category"] == "3")
check("silo_repair: #3 gutfall → item status=repaired",
      _i2_3a_result["items"][0]["status"] == "repaired")
check("silo_repair: #3 gutfall → item label=high",
      _i2_3a_result["items"][0]["label"] == "high")
check("silo_repair: #3 gutfall → raw-Datei geschrieben",
      (cfg.RAW_DIR / f"garmin_raw_{_i2_3a_date}.json").exists())

_i2_3a_summary = json.loads((cfg.SUMMARY_DIR / f"garmin_{_i2_3a_date}.json").read_text())
check("silo_repair: #3 gutfall → avg_bpm korrekt berechnet",
      _i2_3a_summary["heartrate"]["avg_bpm"] is not None)

_i2_3a_qdata = quality._load_quality_log()
_i2_3a_entry = next((e for e in _i2_3a_qdata["days"] if e["date"] == _i2_3a_date), None)
check("silo_repair: #3 gutfall → quality_log Eintrag vorhanden, Label high",
      _i2_3a_entry is not None and _i2_3a_entry.get("quality") == "high")

# ── #3b: Schlechtfall — heartRateValues strukturell falsch geformt (F8) ────
# Dokumentiert den AKTUELLEN Ist-Zustand — repaired, Label high, avg_bpm
# null. Bekannter Fund F8, siehe NOTES_v1658.md — kein korrigierter
# Erwartungswert, da sonst Test von Anfang an rot. Nicht als akzeptables
# Verhalten misszuverstehen.
_i2_3b_date = "2025-04-02"
fx.write_source_file(cfg.SOURCE_DIR, _i2_3b_date, fx.source_raw_malformed_heartrate(_i2_3b_date))

_i2_3b_fresh  = {**_i2_empty_fresh, "source_without_raw": [date.fromisoformat(_i2_3b_date)]}
_i2_3b_result = silo_repair.repair_silos(_i2_3b_fresh)

check("silo_repair: #3 schlechtfall (F8) → ok=1 (kein Crash)",
      _i2_3b_result["ok"] == 1)
check("silo_repair: #3 schlechtfall (F8) → item status=repaired (kein error)",
      _i2_3b_result["items"][0]["status"] == "repaired")
check("silo_repair: #3 schlechtfall (F8) → item label=high trotz kaputtem Inhalt",
      _i2_3b_result["items"][0]["label"] == "high")

_i2_3b_summary = json.loads((cfg.SUMMARY_DIR / f"garmin_{_i2_3b_date}.json").read_text())
check("silo_repair: #3 schlechtfall (F8) → avg_bpm ist null (bekannt, nicht behoben)",
      _i2_3b_summary["heartrate"]["avg_bpm"] is None)
check("silo_repair: #3 schlechtfall (F8) → resting_bpm bleibt korrekt (separates Feld)",
      _i2_3b_summary["heartrate"]["resting_bpm"] == 55)

# ── #7a: Gutfall — raw_without_summary ──────────────────────────────────────
_i2_7a_date = "2025-05-01"
fx.write_raw_file(cfg.RAW_DIR, _i2_7a_date)

_i2_7a_fresh  = {**_i2_empty_fresh, "raw_without_summary": [date.fromisoformat(_i2_7a_date)]}
_i2_7a_result = silo_repair.repair_silos(_i2_7a_fresh)

check("silo_repair: #7 gutfall → ok=1",
      _i2_7a_result["ok"] == 1)
check("silo_repair: #7 gutfall → item category=7",
      _i2_7a_result["items"][0]["category"] == "7")
check("silo_repair: #7 gutfall → item status=repaired",
      _i2_7a_result["items"][0]["status"] == "repaired")
check("silo_repair: #7 gutfall → summary-Datei geschrieben",
      (cfg.SUMMARY_DIR / f"garmin_{_i2_7a_date}.json").exists())

# ── #7b: Schlechtfall — raw ohne 'date'-Feld ────────────────────────────────
_i2_7b_date = "2025-05-02"
fx.write_raw_file(cfg.RAW_DIR, _i2_7b_date, fx.raw_without_date_field())

_i2_7b_fresh  = {**_i2_empty_fresh, "raw_without_summary": [date.fromisoformat(_i2_7b_date)]}
_i2_7b_result = silo_repair.repair_silos(_i2_7b_fresh)

check("silo_repair: #7 schlechtfall → ok=1 (kein Crash trotz fehlendem date)",
      _i2_7b_result["ok"] == 1)
check("silo_repair: #7 schlechtfall → item status=repaired",
      _i2_7b_result["items"][0]["status"] == "repaired")
check("silo_repair: #7 schlechtfall → Dateiname kommt aus dem Finding, nicht aus dem Inhalt",
      (cfg.SUMMARY_DIR / f"garmin_{_i2_7b_date}.json").exists())

_i2_7b_summary = json.loads((cfg.SUMMARY_DIR / f"garmin_{_i2_7b_date}.json").read_text())
check("silo_repair: #7 schlechtfall → summary['date'] ist null",
      _i2_7b_summary.get("date") is None)

# ── Aufräumen I2 — isolierte Umgebung zurücksetzen ──────────────────────────
os.environ["GARMIN_OUTPUT_DIR"] = _i2_orig_env
importlib.reload(cfg)
importlib.reload(silo_repair)
shutil.rmtree(_i2_dir, ignore_errors=True)

summary()
