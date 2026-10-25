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
import zipfile
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

# ── #3c (v1.7.5.6): the repaired raw file replaces an older version in the monthly backup ZIP ────
_i2_3c_date = "2025-06-01"
_i2_3c_name = f"garmin_raw_{_i2_3c_date}.json"
fx.write_source_file(cfg.SOURCE_DIR, _i2_3c_date, fx.source_raw_good(_i2_3c_date))
cfg.RAW_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-06.zip", "w", zipfile.ZIP_DEFLATED) as _zf3c:
    _zf3c.writestr(_i2_3c_name, json.dumps({"date": _i2_3c_date, "marker": "old backup version"}))
_i2_3c_result = silo_repair.repair_silos(
    {**_i2_empty_fresh, "source_without_raw": [date.fromisoformat(_i2_3c_date)]})
with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-06.zip") as _zf3c:
    _i2_3c_zip = _zf3c.read(_i2_3c_name)
check("silo_repair: #3 → repaired (ok=1) although an older backup version exists",
      _i2_3c_result["ok"] == 1 and _i2_3c_result["items"][0]["status"] == "repaired")
check("silo_repair: #3 → the monthly backup ZIP holds the repaired raw file, not the old backup version (v1.7.5.6)",
      _i2_3c_zip == (cfg.RAW_DIR / _i2_3c_name).read_bytes() and b"old backup version" not in _i2_3c_zip)

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

# ── #7c (v1.7.5.6): a rewritten raw file replaces an older version in the monthly backup ZIP ────
_i2_7c_date = "2025-07-01"
_i2_7c_name = f"garmin_raw_{_i2_7c_date}.json"
fx.write_raw_file(cfg.RAW_DIR, _i2_7c_date)
with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-07.zip", "w", zipfile.ZIP_DEFLATED) as _zf7c:
    _zf7c.writestr(_i2_7c_name, json.dumps({"date": _i2_7c_date, "marker": "old backup version"}))
_i2_7c_result = silo_repair.repair_silos(
    {**_i2_empty_fresh, "raw_without_summary": [date.fromisoformat(_i2_7c_date)]})
with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-07.zip") as _zf7c:
    _i2_7c_zip = _zf7c.read(_i2_7c_name)
check("silo_repair: #7 → repaired (ok=1) although an older backup version exists",
      _i2_7c_result["ok"] == 1 and _i2_7c_result["items"][0]["status"] == "repaired")
check("silo_repair: #7 → the monthly backup ZIP holds the raw file that was written again, not the old backup version (v1.7.5.6)",
      _i2_7c_zip == (cfg.RAW_DIR / _i2_7c_name).read_bytes() and b"old backup version" not in _i2_7c_zip)

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

# ══════════════════════════════════════════════════════════════════════════════
#  I3. garmin_silo_repair — counters, loops that go on after a bad item, the
#      downgrade guard of #3, error paths (v1.7.4.0.3).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("I3. garmin_silo_repair — counters, loops, guard, errors")
from gla_testenv import _isolated_log_env as _iso_env3, _put_log as _put_log3

_E3 = {"raw_without_quality": [], "source_without_raw": [],
       "summary_without_raw": [], "raw_without_summary": []}


def _hr3(d):
    return {"date": d, "heart_rates": {"restingHeartRate": 55, "heartRateValues": [[1740787200000, 58]]}}


def _std3(d):
    return {"date": d, "stats": {"totalSteps": 1000}}


def _dt3(s):
    return date.fromisoformat(s)


def _put3(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


# -- #3: source file missing / broken must not stop the next date --------------------------------------------
with _iso_env3("sr3_src") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-06-02.json", _hr3("2025-06-02"))
    _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3("2025-06-01"), _dt3("2025-06-02")]})
    check("I3 #3: a missing source file is counted as failed, the next date is still repaired",
          _r["items"] == [{"category": "3", "date": "2025-06-01", "status": "no_source"},
                          {"category": "3", "date": "2025-06-02", "status": "repaired", "label": "high"}]
          and (_r["ok"], _r["failed"]) == (1, 1))
with _iso_env3("sr3_src_bad") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-06-03.json", "{broken")
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-06-04.json", _hr3("2025-06-04"))
    _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3("2025-06-03"), _dt3("2025-06-04")]})
    check("I3 #3: a broken source file is one error with a reason, the next date is still repaired",
          (_r["ok"], _r["failed"]) == (1, 1) and _r["items"][0]["status"] == "error"
          and _r["items"][0]["date"] == "2025-06-03" and _r["items"][0]["reason"]
          and _r["items"][1]["status"] == "repaired")

# -- #3: the downgrade guard looks at the entry of THIS date -------------------------------------------------------
with _iso_env3("sr3_guard") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put_log3({"days": [{"date": "2025-07-01", "quality": "standard"},
                        {"date": "2025-07-09", "quality": "standard"},
                        {"date": "2025-07-02", "quality": "high"}]})
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-07-02.json", _std3("2025-07-02"))
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-07-03.json", _hr3("2025-07-03"))
    _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3("2025-07-02"), _dt3("2025-07-03")]})
    check("I3 #3: a day that would be downgraded is skipped (existing and new label named), the next one is repaired",
          _r["items"] == [{"category": "3", "date": "2025-07-02", "status": "skipped",
                           "existing": "high", "new": "standard"},
                          {"category": "3", "date": "2025-07-03", "status": "repaired", "label": "high"}]
          and (_r["ok"], _r["failed"]) == (1, 0))
    check("I3 #3: a skipped day leaves no raw file behind",
          not (cfg.RAW_DIR / "garmin_raw_2025-07-02.json").exists()
          and (cfg.RAW_DIR / "garmin_raw_2025-07-03.json").exists())
    _e3 = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("I3 #3: the repaired day is recorded as written in the quality log, the guarded one is untouched",
          _e3["2025-07-03"].get("write") is True and _e3["2025-07-02"]["quality"] == "high")

# -- #5: orphan summaries --------------------------------------------------------------------------------------------
with _iso_env3("sr3_orphan") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SUMMARY_DIR / "garmin_2025-08-01.json", {"date": "2025-08-01"})
    _r = silo_repair.repair_silos({**_E3, "summary_without_raw": [_dt3("2025-08-02"), _dt3("2025-08-01")]})
    check("I3 #5: an orphan that is already gone is reported as gone, the next one is removed",
          _r["items"] == [{"category": "5", "date": "2025-08-02", "status": "gone"},
                          {"category": "5", "date": "2025-08-01", "status": "repaired"}]
          and (_r["ok"], _r["failed"]) == (1, 0)
          and not (cfg.SUMMARY_DIR / "garmin_2025-08-01.json").exists())
    _put3(cfg.SUMMARY_DIR / "garmin_2025-08-03.json", {"date": "2025-08-03"})
    _put3(cfg.SUMMARY_DIR / "garmin_2025-08-04.json", {"date": "2025-08-04"})
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        _r = silo_repair.repair_silos({**_E3, "summary_without_raw": [_dt3("2025-08-03"), _dt3("2025-08-04")]})
    check("I3 #5: failing deletes are one error each with the reason, nothing is removed",
          (_r["ok"], _r["failed"]) == (0, 2)
          and [i["status"] for i in _r["items"]] == ["error", "error"]
          and all("locked" in i["reason"] for i in _r["items"])
          and (cfg.SUMMARY_DIR / "garmin_2025-08-03.json").exists())
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        _r = silo_repair.repair_silos({**_E3, "summary_without_raw": [_dt3("2025-08-03")]})
    check("I3 #5: one failing delete -> failed is exactly 1", (_r["ok"], _r["failed"]) == (0, 1))

# -- #7: raw without summary ---------------------------------------------------------------------------------------------
with _iso_env3("sr3_summary") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.RAW_DIR / "garmin_raw_2025-09-02.json", _hr3("2025-09-02"))
    _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-09-01"), _dt3("2025-09-02")]})
    check("I3 #7: a raw file that is gone is reported as gone (not an error), the next day is repaired",
          _r["items"] == [{"category": "7", "date": "2025-09-01", "status": "gone"},
                          {"category": "7", "date": "2025-09-02", "status": "repaired"}]
          and (_r["ok"], _r["failed"]) == (1, 0)
          and (cfg.SUMMARY_DIR / "garmin_2025-09-02.json").exists())
    _put3(cfg.RAW_DIR / "garmin_raw_2025-09-03.json", "{broken")
    _put3(cfg.RAW_DIR / "garmin_raw_2025-09-04.json", _hr3("2025-09-04"))
    _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-09-03"), _dt3("2025-09-04")]})
    check("I3 #7: a broken raw file is one error with a reason, the next day is still repaired",
          (_r["ok"], _r["failed"]) == (1, 1) and _r["items"][0]["status"] == "error"
          and _r["items"][0]["reason"] and _r["items"][1]["status"] == "repaired")

# -- #7 with export data (v1.7.6.1): a day without a raw file but with aggregates gets its summary from there ----------
import garmin_bulk_writer as _bw7
import garmin_normalizer as _nz7
_H7 = "cd" * 32
_A7 = lambda d: {"date": d, "user_summary": {"totalSteps": 7000, "restingHeartRate": 54}, "stress": {"averageStressLevel": 25, "maxStressLevel": 70}}   # noqa: E731
with _iso_env3("sr3_agg7") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _d in ("2025-10-01", "2025-10-02", "2025-10-04"):
        assert _bw7.write_aggregates(_d, _A7(_d), [_H7]) == _bw7.WRITTEN
    _put3(cfg.RAW_DIR / "garmin_raw_2025-10-02.json", {"date": "2025-10-02", "user_summary": {"totalSteps": 100}})
    _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-10-01"), _dt3("2025-10-02"), _dt3("2025-10-03")]})
    check("I3 #7 export data: a day without raw but with export data is repaired (summary only), a day with raw and export data too, a day with neither is gone",
          _r["items"] == [{"category": "7", "date": "2025-10-01", "status": "repaired"},
                          {"category": "7", "date": "2025-10-02", "status": "repaired"},
                          {"category": "7", "date": "2025-10-03", "status": "gone"}]
          and (_r["ok"], _r["failed"]) == (2, 0))
    _s1 = json.loads((cfg.SUMMARY_DIR / "garmin_2025-10-01.json").read_text(encoding="utf-8"))
    check("I3 #7 export data: the summary of the day without raw comes from the export data and no raw file is created",
          _s1 == _nz7.summarize(_nz7.normalize(_A7("2025-10-01"), source="bulk")) and not (cfg.RAW_DIR / "garmin_raw_2025-10-01.json").exists())
    _s2 = json.loads((cfg.SUMMARY_DIR / "garmin_2025-10-02.json").read_text(encoding="utf-8"))
    check("I3 #7 export data: raw and export data are resolved: the API value wins (100 steps), the export fills the rest (stress 25)",
          _s2["day"]["steps"] == 100 and _s2["stress"]["stress_avg"] == 25)
    check("I3 #7 export data: nothing for the day with neither was created", not (cfg.SUMMARY_DIR / "garmin_2025-10-03.json").exists())
    # export data that cannot be used: one error with a reason, the next day is still repaired
    (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}2025-10-05.json").write_text("{ not json", encoding="utf-8")
    _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-10-05"), _dt3("2025-10-04")]})
    check("I3 #7 export data: a damaged aggregates file and no raw is one error with a reason, the next day is still repaired",
          (_r["ok"], _r["failed"]) == (1, 1) and _r["items"][0]["status"] == "error" and _r["items"][0]["date"] == "2025-10-05"
          and _r["items"][0]["reason"] and _r["items"][1]["status"] == "repaired")
    # the whole round: check -> repair -> check finds nothing more (no flip-flopping between #5 and #7)
    import garmin_silo_check as _sc7
    _put3(cfg.SUMMARY_DIR / "garmin_2025-10-08.json", {"date": "2025-10-08"})          # a real orphan
    _first = _sc7.check_silos()
    _rep = silo_repair.repair_silos(_first)
    _second = _sc7.check_silos()
    check("I3 #7 export data: check, repair, check: the second check finds nothing more except what cannot be repaired, and the day with export data keeps its summary",
          (cfg.SUMMARY_DIR / "garmin_2025-10-04.json").exists() and (cfg.SUMMARY_DIR / "garmin_2025-10-01.json").exists()
          and not (cfg.SUMMARY_DIR / "garmin_2025-10-08.json").exists()
          and _second["summary_without_raw"] == [] and _second["raw_without_summary"] == [_dt3("2025-10-05")])

# -- F-4 (v1.7.6.1): a write that did not happen is an error, not "repaired" ------------------------------------------------
section("I4. garmin_silo_repair — a failed write is an error (F-4)")
_real_wd = silo_repair.writer.write_day


def _wd_false_on(day):
    return lambda n, s, d: False if d == day else _real_wd(n, s, d)


with _iso_env3("sr4_3") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-11-01.json", _hr3("2025-11-01"))
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-11-02.json", _hr3("2025-11-02"))
    with patch.object(silo_repair.writer, "write_day", side_effect=_wd_false_on("2025-11-01")):
        _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3("2025-11-01"), _dt3("2025-11-02")]})
    check("I4 #3: a write_day that returns False is one error with a reason, the next day is still repaired",
          (_r["ok"], _r["failed"]) == (1, 1) and _r["items"][0]["status"] == "error" and _r["items"][0]["date"] == "2025-11-01"
          and "could not be written" in _r["items"][0]["reason"] and _r["items"][1]["status"] == "repaired")
    _e4 = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("I4 #3: the day that was not written has no quality-log entry and no raw file; the repaired day is recorded as written",
          "2025-11-01" not in _e4 and not (cfg.RAW_DIR / "garmin_raw_2025-11-01.json").exists()
          and _e4["2025-11-02"].get("write") is True)

with _iso_env3("sr4_3agg") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-11-03.json", _hr3("2025-11-03"))
    with patch("garmin_bulk_writer.load_aggregates", return_value=("unreadable", None)):
        _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3("2025-11-03")]})
    check("I4 #3: an aggregates file of the day that cannot be read (write_day refuses) is an error, nothing is written, no entry",
          (_r["ok"], _r["failed"]) == (0, 1) and _r["items"][0]["status"] == "error"
          and not (cfg.RAW_DIR / "garmin_raw_2025-11-03.json").exists()
          and not (cfg.SUMMARY_DIR / "garmin_2025-11-03.json").exists()
          and all(e["date"] != "2025-11-03" for e in quality._load_quality_log()["days"]))

with _iso_env3("sr4_7") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.RAW_DIR / "garmin_raw_2025-11-04.json", _hr3("2025-11-04"))
    _put3(cfg.RAW_DIR / "garmin_raw_2025-11-05.json", _hr3("2025-11-05"))
    with patch.object(silo_repair.writer, "write_day", side_effect=_wd_false_on("2025-11-04")):
        _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-11-04"), _dt3("2025-11-05")]})
    check("I4 #7: a write_day that returns False is one error with a reason, the next day is still repaired",
          (_r["ok"], _r["failed"]) == (1, 1) and _r["items"][0]["status"] == "error" and _r["items"][0]["date"] == "2025-11-04"
          and "could not be written" in _r["items"][0]["reason"] and _r["items"][1]["status"] == "repaired"
          and not (cfg.SUMMARY_DIR / "garmin_2025-11-04.json").exists() and (cfg.SUMMARY_DIR / "garmin_2025-11-05.json").exists())

with _iso_env3("sr4_7agg") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.RAW_DIR / "garmin_raw_2025-11-06.json", _hr3("2025-11-06"))
    _raw_bytes = (cfg.RAW_DIR / "garmin_raw_2025-11-06.json").read_bytes()
    with patch("garmin_bulk_writer.load_aggregates", return_value=("unreadable", None)):
        _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3("2025-11-06")]})
    check("I4 #7: an aggregates file that cannot be read is an error: no summary, the raw file is as it was",
          (_r["ok"], _r["failed"]) == (0, 1) and _r["items"][0]["status"] == "error"
          and not (cfg.SUMMARY_DIR / "garmin_2025-11-06.json").exists()
          and (cfg.RAW_DIR / "garmin_raw_2025-11-06.json").read_bytes() == _raw_bytes)

# -- regenerate_raw.py (support tool, no test before; F-4 v1.7.6.1) ----------------------------------------------------------
section("I5. regenerate_raw.py — replay from source/, the result of write_day counts")
import contextlib
import importlib.util
import io
import sys as _sys

_RR_PATH = Path(__file__).resolve().parent.parent / "support-tools" / "archive-maintenance" / "regenerate_raw.py"
_rr_spec = importlib.util.spec_from_file_location("regenerate_raw_under_test", _RR_PATH)
regen = importlib.util.module_from_spec(_rr_spec)
_rr_spec.loader.exec_module(regen)


def _regen(*args):
    """main() of the tool with the given arguments: (exit code or None, printed text)."""
    out, code = io.StringIO(), None
    with patch.object(_sys, "argv", ["regenerate_raw.py", *args]), contextlib.redirect_stdout(out):
        try:
            regen.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


with _iso_env3("sr5_ok") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-12-01.json", _hr3("2025-12-01"))
    _bw7.write_aggregates("2025-12-01", _A7("2025-12-01"), [_H7])
    _code, _txt = _regen("--dry-run")
    check("I5 dry run: says what it would do and writes nothing (no raw, no summary, no log entry)",
          _code is None and "would write (high) [new]" in _txt and "Dry run complete. 1 would be processed" in _txt
          and not (cfg.RAW_DIR / "garmin_raw_2025-12-01.json").exists() and not (cfg.SUMMARY_DIR / "garmin_2025-12-01.json").exists())
    _code, _txt = _regen("--date", "2025-12-01")
    _s5 = json.loads((cfg.SUMMARY_DIR / "garmin_2025-12-01.json").read_text(encoding="utf-8"))
    _raw5 = json.loads((cfg.RAW_DIR / "garmin_raw_2025-12-01.json").read_text(encoding="utf-8"))
    check("I5 a day: regenerated (printed, counted), the summary is the resolved one (export steps 7000 and stress 25), raw/ holds only the API data",
          _code is None and "✓ 2025-12-01 (high)" in _txt and "Done. 1 regenerated, 0 downgrade-protected, 0 errors." in _txt
          and _s5["day"]["steps"] == 7000 and _s5["stress"]["stress_avg"] == 25 and "user_summary" not in _raw5 and "stress" not in _raw5)
    _e5 = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("I5 a day: the quality log has an entry from the replay, written", _e5["2025-12-01"]["reason"].endswith("source replay")
          and _e5["2025-12-01"].get("write") is True)

with _iso_env3("sr5_fail") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-12-02.json", _hr3("2025-12-02"))
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-12-03.json", _hr3("2025-12-03"))
    with patch.object(regen.writer, "write_day", side_effect=lambda n, s, d: False if d == "2025-12-02" else _real_wd(n, s, d)):
        _code, _txt = _regen()
    _e5 = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("I5 write_day returns False: the day is an error (printed, counted), the next day is still regenerated, the failed day has no log entry",
          "✗ 2025-12-02: write_day failed" in _txt and "✓ 2025-12-03 (high)" in _txt
          and "Done. 1 regenerated, 0 downgrade-protected, 1 errors." in _txt
          and "2025-12-02" not in _e5 and _e5["2025-12-03"].get("write") is True
          and not (cfg.RAW_DIR / "garmin_raw_2025-12-02.json").exists())

with _iso_env3("sr5_agg") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put3(cfg.SOURCE_DIR / "garmin_source_2025-12-04.json", _hr3("2025-12-04"))
    with patch("garmin_bulk_writer.load_aggregates", return_value=("unreadable", None)):
        _code, _txt = _regen()
    check("I5 an aggregates file that cannot be read: an error, nothing written, no log entry",
          "✗ 2025-12-04" in _txt and "1 errors" in _txt and not (cfg.RAW_DIR / "garmin_raw_2025-12-04.json").exists()
          and all(e["date"] != "2025-12-04" for e in quality._load_quality_log()["days"]))

# -- days with export data (v1.7.6.1, Baustein 6b-3): silo repair #3 and #7, regenerate_raw ----------------------------------
# write_day resolves the summary of a day that has an aggregates file: the API data win per top-level key, the export fills the
# rest; raw/ keeps exactly the API data. A day without an aggregates file is written as before.
section("I6. silo repair #3/#7 and regenerate_raw — days with export data")
_API999 = {"user_summary": {"totalSteps": 999}}


def _sum6(day):
    return json.loads((cfg.SUMMARY_DIR / f"garmin_{day}.json").read_text(encoding="utf-8"))


def _raw6(day):
    return json.loads((cfg.RAW_DIR / f"garmin_raw_{day}.json").read_text(encoding="utf-8"))


with _iso_env3("sr6_3") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _x1, _x2, _x3 = "2025-12-10", "2025-12-11", "2025-12-12"
    for _d, _extra in ((_x1, _API999), (_x2, {}), (_x3, _API999)):
        _put3(cfg.SOURCE_DIR / f"garmin_source_{_d}.json", {**_hr3(_d), **_extra})
    for _d in (_x1, _x2):                                                       # _x3 has no export data
        assert _bw7.write_aggregates(_d, _A7(_d), [_H7]) == _bw7.WRITTEN
    _r = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3(_x1), _dt3(_x2), _dt3(_x3)]})
    check("I6 #3: three days with and without export data are all repaired", (_r["ok"], _r["failed"]) == (3, 0)
          and [i["status"] for i in _r["items"]] == ["repaired"] * 3)
    check("I6 #3: a day with export data: the API's steps win (999), the export fills the stress (25); raw/ holds the API data only",
          _sum6(_x1)["day"]["steps"] == 999 and _sum6(_x1)["stress"]["stress_avg"] == 25
          and _raw6(_x1).get("user_summary") == {"totalSteps": 999} and "stress" not in _raw6(_x1) and "heart_rates" in _raw6(_x1))
    check("I6 #3: a day whose source has no steps: the export's steps (7000) and stress (25) are in the summary, none of them in raw/",
          _sum6(_x2)["day"]["steps"] == 7000 and _sum6(_x2)["stress"]["stress_avg"] == 25
          and "user_summary" not in _raw6(_x2) and "stress" not in _raw6(_x2))
    check("I6 #3: a day without export data is as before (the source's steps 999, no stress)",
          _sum6(_x3)["day"]["steps"] == 999 and _sum6(_x3)["stress"]["stress_avg"] is None)
    _e6 = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("I6 #3: all three days are recorded as written API days", all((_e6[d]["source"], _e6[d]["write"]) == ("api", True) for d in (_x1, _x2, _x3)))

with _iso_env3("sr6_7") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _y1, _y2 = "2025-12-13", "2025-12-14"
    _put3(cfg.RAW_DIR / f"garmin_raw_{_y1}.json", {**_hr3(_y1), **_API999})
    _put3(cfg.RAW_DIR / f"garmin_raw_{_y2}.json", _hr3(_y2))
    _raw_before = {d: _raw6(d) for d in (_y1, _y2)}
    for _d in (_y1, _y2):
        assert _bw7.write_aggregates(_d, _A7(_d), [_H7]) == _bw7.WRITTEN
    _r = silo_repair.repair_silos({**_E3, "raw_without_summary": [_dt3(_y1), _dt3(_y2)]})
    check("I6 #7: two raw days with export data are repaired", (_r["ok"], _r["failed"]) == (2, 0))
    check("I6 #7: the API's steps win (999), the export fills the stress (25) and the steps of a day that has none (7000)",
          _sum6(_y1)["day"]["steps"] == 999 and _sum6(_y1)["stress"]["stress_avg"] == 25
          and _sum6(_y2)["day"]["steps"] == 7000 and _sum6(_y2)["stress"]["stress_avg"] == 25)
    check("I6 #7: raw/ holds the same data as before, none of the export's sections", all(_raw6(d) == _raw_before[d] for d in (_y1, _y2)))

with _iso_env3("sr6_regen") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _z1, _z2, _z3 = "2025-12-15", "2025-12-16", "2025-12-17"
    for _d, _extra in ((_z1, _API999), (_z2, {}), (_z3, _API999)):
        _put3(cfg.SOURCE_DIR / f"garmin_source_{_d}.json", {**_hr3(_d), **_extra})
    for _d in (_z1, _z2):                                                       # _z3 has no export data
        assert _bw7.write_aggregates(_d, _A7(_d), [_H7]) == _bw7.WRITTEN
    _code, _txt = _regen()
    check("I6 regenerate_raw: three days regenerated, no error", _code is None and "Done. 3 regenerated, 0 downgrade-protected, 0 errors." in _txt)
    check("I6 regenerate_raw: a day with export data: the API's steps win (999), the export fills the stress (25); raw/ holds the API data only",
          _sum6(_z1)["day"]["steps"] == 999 and _sum6(_z1)["stress"]["stress_avg"] == 25
          and _raw6(_z1).get("user_summary") == {"totalSteps": 999} and "stress" not in _raw6(_z1))
    check("I6 regenerate_raw: a day whose source has no steps gets the export's steps (7000) and stress (25) in the summary only",
          _sum6(_z2)["day"]["steps"] == 7000 and _sum6(_z2)["stress"]["stress_avg"] == 25
          and "user_summary" not in _raw6(_z2) and "stress" not in _raw6(_z2))
    check("I6 regenerate_raw: a day without export data is as before (the source's steps 999, no stress)",
          _sum6(_z3)["day"]["steps"] == 999 and _sum6(_z3)["stress"]["stress_avg"] is None)

# ── F-10 (v1.7.6.2) and #8: a bulk day file the log marks and the store lacks is restored from the backup ─────────────────────────
# Before Baustein 5a these checks pinned the wrong behaviour (the lost aggregates file made the day's summary an "orphan" and
# the repair deleted it). Now the day is a finding #8, the repair restores the file from backup/bulk and the summary stays.
section("I7. garmin_silo_repair — #8 bulk file lost: restore from the backup, F-10 fixed")
import garmin_silo_check as _sc10
import garmin_writer as _wr10
import garmin_backup_bulk as _bb10
import garmin_bulk_normalizer as _nz10
from gla_testenv import _isolated_log_env as _iso10, _put_log as _put_log10
_F10 = "2025-12-20"
_PLAN10 = _nz10.DayPlan(_F10, 1766188800, 1766275200, 0.0, 0.0, False, "prev_day_end")
_VALS10 = [[1766200000000 + 60000 * i, 60 + i] for i in range(5)]


def _lost10(extra_entries=(), with_backup=True, intraday=False):
    """Makes a day with export data (+ optionally an intraday file), a summary, the marks and (optionally) a backup; then loses the files."""
    assert _bw7.write_aggregates(_F10, _A7(_F10), [_H7]) == _bw7.WRITTEN
    assert _wr10.rebuild_summary(_F10) is True                                  # the resolved summary, made from the export values
    if intraday:
        assert _bw7.write_day(_PLAN10, _nz10.DaySamples(_F10, _VALS10, [_H7], 0, 0)) == _bw7.WRITTEN
    marks = {"aggregates": "2025-12-20", **({"intraday": "2025-12-20"} if intraday else {})}
    _put_log10({"days": [{"date": _F10, "quality": "standard", "source": "bulk", "write": False, "bulk": marks}, *extra_entries]})
    if with_backup:
        assert _bb10.backup_all()["ok"] is True
    agg = cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{_F10}.json"
    day = cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{_F10}.json"
    before = {"agg": agg.read_bytes(), "day": day.read_bytes() if intraday else None}
    agg.unlink()
    if intraday:
        day.unlink()
    return agg, day, before


with _iso10("sr7_f10") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _sum_f10 = cfg.SUMMARY_DIR / f"garmin_{_F10}.json"
    _agg_f10, _day_f10, _before = _lost10()
    _lost_f10 = _sc10.check_silos()
    check("I7 F-10: with the aggregates file gone the day is a finding #8 and its summary is no orphan (#5)",
          _lost_f10["bulk_lost_aggregates"] == [_dt3(_F10)] and _lost_f10["summary_without_raw"] == [])
    _rep_f10 = silo_repair.repair_silos(_lost_f10)
    check("I7 #8: the repair restores the aggregates file from the backup, byte for byte, and reports it",
          _agg_f10.read_bytes() == _before["agg"]
          and _rep_f10["items"] == [{"category": "8", "date": _F10, "kind": "aggregates", "status": "repaired"}]
          and (_rep_f10["ok"], _rep_f10["failed"]) == (1, 0))
    _s10 = json.loads(_sum_f10.read_text(encoding="utf-8"))
    check("I7 #8: the summary is there and made from the restored file (export steps 7000, stress 25); it was never deleted",
          _s10["day"]["steps"] == 7000 and _s10["stress"]["stress_avg"] == 25)
    _again = _sc10.check_silos()
    check("I7 #8: check, repair, check: the second check finds nothing at all",
          all(not _again[k] for k in ("raw_without_quality", "source_without_raw", "summary_without_raw",
                                     "raw_without_summary", "bulk_lost_intraday", "bulk_lost_aggregates")))
    # the file is back by now: a stale finding is reported as present and counts as neither fixed nor failed
    _rep_p = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10)]})
    check("I7 #8: a day whose file is back when the repair runs is 'present' — not fixed, not failed, nothing rewritten",
          _rep_p["items"] == [{"category": "8", "date": _F10, "kind": "aggregates", "status": "present"}]
          and (_rep_p["ok"], _rep_p["failed"]) == (0, 0))

with _iso10("sr7_nobackup") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10(with_backup=False)
    _sum_f10 = cfg.SUMMARY_DIR / f"garmin_{_F10}.json"
    _sum_bytes = _sum_f10.read_bytes()
    _rep = silo_repair.repair_silos(_sc10.check_silos())
    check("I7 #8: without a backup copy the day is 'no_backup' (counted as failed), nothing is created, and the summary stays untouched",
          _rep["items"] == [{"category": "8", "date": _F10, "kind": "aggregates", "status": "no_backup"}]
          and (_rep["ok"], _rep["failed"]) == (0, 1) and not _agg_f10.exists() and _sum_f10.read_bytes() == _sum_bytes)

with _iso10("sr7_intraday") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10(intraday=True)
    _found = _sc10.check_silos()
    check("I7 #8: both files lost -> both lists name the day", _found["bulk_lost_intraday"] == [_dt3(_F10)] and _found["bulk_lost_aggregates"] == [_dt3(_F10)])
    _rep = silo_repair.repair_silos(_found)
    check("I7 #8: both files are restored byte for byte, the intraday one first, one item each",
          _day_f10.read_bytes() == _before["day"] and _agg_f10.read_bytes() == _before["agg"]
          and _rep["items"] == [{"category": "8", "date": _F10, "kind": "intraday", "status": "repaired"},
                                {"category": "8", "date": _F10, "kind": "aggregates", "status": "repaired"}]
          and (_rep["ok"], _rep["failed"]) == (2, 0))
    _after = _sc10.check_silos()
    check("I7 #8: after the restore of both files nothing is left to find",
          all(not _after[k] for k in ("bulk_lost_intraday", "bulk_lost_aggregates", "summary_without_raw")))

with _iso10("sr7_errors") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10()
    _d2 = _dt3("2025-12-21")
    # a loop that goes on: the first day has no backup copy, the second is restored
    _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_d2, _dt3(_F10)]})
    check("I7 #8: a day without a backup copy does not stop the next one; failed counts exactly the one",
          [(i["date"], i["status"]) for i in _rep["items"]] == [("2025-12-21", "no_backup"), (_F10, "repaired")]
          and (_rep["ok"], _rep["failed"]) == (1, 1))
    _agg_f10.unlink()
    with patch.object(silo_repair.backup_bulk, "read_day_copy", side_effect=[OSError("disk exploded"), None]):
        _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10), _d2]})
    check("I7 #8: an exception while reading the backup is one error with a reason, the next day goes on",
          _rep["items"][0]["status"] == "error" and "disk exploded" in _rep["items"][0]["reason"]
          and _rep["items"][1]["status"] == "no_backup" and (_rep["ok"], _rep["failed"]) == (0, 2))
    with patch.object(silo_repair.bulk_writer, "import_day_file", return_value=silo_repair.bulk_writer.KEPT):
        _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10)]})
    check("I7 #8: a backup copy with a schema version newer than the program knows is an error with that reason",
          _rep["items"][0]["status"] == "error" and "newer schema" in _rep["items"][0]["reason"] and (_rep["ok"], _rep["failed"]) == (0, 1))
    with patch.object(silo_repair.bulk_writer, "import_day_file", return_value=silo_repair.bulk_writer.FAILED):
        _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10)]})
    check("I7 #8: a copy the bulk writer refuses is an error with a reason",
          _rep["items"][0]["status"] == "error" and "refused" in _rep["items"][0]["reason"] and (_rep["ok"], _rep["failed"]) == (0, 1)
          and not _agg_f10.exists())
    with patch.object(silo_repair.writer, "rebuild_summary", return_value=False):
        _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10)]})
    check("I7 #8: the file is restored but the summary cannot be made: one error naming that, the restored file stays",
          _rep["items"][0]["status"] == "error" and "summary could not be made" in _rep["items"][0]["reason"]
          and (_rep["ok"], _rep["failed"]) == (0, 1) and _agg_f10.exists())

with _iso10("sr7_order") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10()
    _put3(cfg.SOURCE_DIR / f"garmin_source_{_F10}.json", _hr3(_F10))
    _sum_f10 = cfg.SUMMARY_DIR / f"garmin_{_F10}.json"
    _sum_f10.unlink()
    _rep = silo_repair.repair_silos({**_E3, "source_without_raw": [_dt3(_F10)], "bulk_lost_aggregates": [_dt3(_F10)]})
    check("I7 #8 runs before #3: the aggregates file is back when the raw day is made, so its summary carries the export values (steps 7000)",
          [i["category"] for i in _rep["items"]] == ["8", "3"] and (_rep["ok"], _rep["failed"]) == (2, 0)
          and json.loads(_sum_f10.read_text(encoding="utf-8"))["day"]["steps"] == 7000)

# ── #9 (v1.7.6.2): a FIT original an intraday day file names and the store lacks is restored from the backup ───────────────────
section("I8. garmin_silo_repair — #9 original missing: restore from the backup")
import hashlib as _hl11
_OR11 = b"fit-original-bytes of day 2025-12-22"
_OH11 = _hl11.sha256(_OR11).hexdigest()
_F11 = "2025-12-22"
_PLAN11 = _nz10.DayPlan(_F11, 1766361600, 1766448000, 0.0, 0.0, False, "prev_day_end")
_VALS11 = [[1766370000000 + 60000 * i, 60 + i] for i in range(5)]


def _lost11(with_backup=True):
    """An intraday day that names one original; the original is stored, backed up (optionally), then lost."""
    assert _bw7.store_original(_OH11, _OR11) == _bw7.WRITTEN
    assert _bw7.write_day(_PLAN11, _nz10.DaySamples(_F11, _VALS11, [_OH11], 0, 0)) == _bw7.WRITTEN
    if with_backup:
        assert _bb10.backup_all()["ok"] is True
    path = cfg.BULK_SOURCE_DIR / _OH11[:2] / f"{_OH11}.fit"
    path.unlink()
    return path


with _iso10("sr8_restore") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig11 = _lost11()
    _found = _sc10.check_silos()
    check("I8 #9: the original the day names is lost -> a finding with its hash", _found["bulk_originals_missing"] == [_OH11])
    _rep = silo_repair.repair_silos(_found)
    check("I8 #9: the repair restores the original from the backup, byte for byte, and reports it by hash",
          _orig11.read_bytes() == _OR11
          and _rep["items"] == [{"category": "9", "date": None, "hash": _OH11, "status": "repaired"}]
          and (_rep["ok"], _rep["failed"]) == (1, 0))
    check("I8 #9: check, repair, check: the second check finds nothing",
          _sc10.check_silos()["bulk_originals_missing"] == [])
    _rep = silo_repair.repair_silos({**_E3, "bulk_originals_missing": [_OH11]})
    check("I8 #9: an original that is back when the repair runs is 'present' — not fixed, not failed",
          _rep["items"] == [{"category": "9", "date": None, "hash": _OH11, "status": "present"}] and (_rep["ok"], _rep["failed"]) == (0, 0))

with _iso10("sr8_nobackup") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig11 = _lost11(with_backup=False)
    _rep = silo_repair.repair_silos(_sc10.check_silos())
    check("I8 #9: without a backup copy the original is 'no_backup' (counted as failed) and nothing is created",
          _rep["items"] == [{"category": "9", "date": None, "hash": _OH11, "status": "no_backup"}]
          and (_rep["ok"], _rep["failed"]) == (0, 1) and not _orig11.exists())

with _iso10("sr8_errors") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig11 = _lost11()
    _other = "9f" * 32
    _rep = silo_repair.repair_silos({**_E3, "bulk_originals_missing": [_other, _OH11]})
    check("I8 #9: an original without a backup copy does not stop the next one; failed counts exactly the one",
          [(i["hash"][:2], i["status"]) for i in _rep["items"]] == [("9f", "no_backup"), (_OH11[:2], "repaired")]
          and (_rep["ok"], _rep["failed"]) == (1, 1))
    _orig11.unlink()
    with patch.object(silo_repair.backup_bulk, "read_original_copy", side_effect=[OSError("disk exploded"), None]):
        _rep = silo_repair.repair_silos({**_E3, "bulk_originals_missing": [_OH11, _other]})
    check("I8 #9: an exception while reading the backup is one error with a reason, the next original goes on",
          _rep["items"][0]["status"] == "error" and "disk exploded" in _rep["items"][0]["reason"]
          and _rep["items"][1]["status"] == "no_backup" and (_rep["ok"], _rep["failed"]) == (0, 2))
    with patch.object(silo_repair.bulk_writer, "store_original", return_value=silo_repair.bulk_writer.FAILED):
        _rep = silo_repair.repair_silos({**_E3, "bulk_originals_missing": [_OH11]})
    check("I8 #9: a copy the bulk writer refuses is an error with a reason, nothing is created",
          _rep["items"][0]["status"] == "error" and "refused" in _rep["items"][0]["reason"]
          and (_rep["ok"], _rep["failed"]) == (0, 1) and not _orig11.exists())
    # the backup holds bytes that do not match the name: store_original refuses them (the hash is checked)
    _zip11 = cfg.BULK_SOURCE_BACKUP_DIR / f"{_OH11[:2]}.zip"
    with zipfile.ZipFile(_zip11, "w") as _zf:
        _zf.writestr(f"{_OH11}.fit", b"other bytes")
    _rep = silo_repair.repair_silos({**_E3, "bulk_originals_missing": [_OH11]})
    check("I8 #9: a backup copy whose bytes do not match the hash is refused (an error), nothing is stored",
          _rep["items"][0]["status"] == "error" and not _orig11.exists())

with _iso10("sr8_order") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10()
    _orig11 = _lost11()
    _put3(cfg.SUMMARY_DIR / "garmin_2025-12-30.json", {"date": "2025-12-30"})                   # a real orphan (#5)
    _rep = silo_repair.repair_silos({**_E3, "bulk_lost_aggregates": [_dt3(_F10)], "bulk_originals_missing": [_OH11],
                                     "summary_without_raw": [_dt3("2025-12-30")]})
    check("I8 #9 runs after #8 and before the older categories (#5 follows); all three are repaired",
          [i["category"] for i in _rep["items"]] == ["8", "9", "5"] and (_rep["ok"], _rep["failed"]) == (3, 0)
          and _orig11.read_bytes() == _OR11)

# ── #9 JSON (v1.7.6.2.1): a JSON original of the export the backup holds and the store lacks is restored ───────────────────────
section("I9. garmin_silo_repair — #9 JSON original missing: restore from the backup")
_ORJ12 = b'{"export": "json original of day 2025-12-23"}'
_OHJ12 = _hl11.sha256(_ORJ12).hexdigest()
_ITEM12 = {"category": "9", "date": None, "hash": _OHJ12, "kind": "json"}


def _lost12(with_backup=True):
    """A JSON original of the export in the store, backed up (optionally), then lost."""
    assert _bw7.store_original_json(_OHJ12, _ORJ12) == _bw7.WRITTEN
    if with_backup:
        assert _bb10.backup_all()["ok"] is True
    path = cfg.BULK_SOURCE_DIR / _OHJ12[:2] / f"{_OHJ12}.json"
    path.unlink()
    return path


with _iso10("sr9_restore") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig12 = _lost12()
    _found = _sc10.check_silos()
    check("I9 #9: the lost JSON original is a finding of its own list, the FIT list stays empty",
          _found["bulk_json_originals_missing"] == [_OHJ12] and _found["bulk_originals_missing"] == [])
    _rep = silo_repair.repair_silos(_found)
    check("I9 #9: the repair restores the JSON original from the backup, byte for byte, and reports it by hash with kind json",
          _orig12.exists() and _orig12.read_bytes() == _ORJ12 and _rep["items"] == [{**_ITEM12, "status": "repaired"}]
          and (_rep["ok"], _rep["failed"]) == (1, 0))
    _after = _sc10.check_silos()
    check("I9 #9: check, repair, check: the second check finds nothing in either list",
          _after["bulk_json_originals_missing"] == [] and _after["bulk_originals_missing"] == [])
    _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12]})
    check("I9 #9: a JSON original that is back when the repair runs is 'present' — not fixed, not failed",
          _rep["items"] == [{**_ITEM12, "status": "present"}] and (_rep["ok"], _rep["failed"]) == (0, 0))
    with patch.object(silo_repair.backup_bulk, "read_original_copy", return_value=None) as _read:
        silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12], "bulk_originals_missing": [_OH11]})
    check("I9 #9: the backup is read with the suffix of the list: .json for the JSON list, .fit for the FIT list (FIT first)",
          [c.args for c in _read.call_args_list] == [(_OH11, ".fit"), (_OHJ12, ".json")])

with _iso10("sr9_nobackup") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig12 = _lost12(with_backup=False)
    check("I9 #9: a JSON original lost before it was ever backed up cannot be seen by the check (the known limit of the "
          "backup comparison); the repair then has nothing to do",
          _sc10.check_silos()["bulk_json_originals_missing"] == []
          and silo_repair.repair_silos(_sc10.check_silos())["items"] == [])
    _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12]})
    check("I9 #9: asked for a JSON original that has no backup copy, the repair says 'no_backup' (counted as failed) and creates nothing",
          _rep["items"] == [{**_ITEM12, "status": "no_backup"}] and (_rep["ok"], _rep["failed"]) == (0, 1)
          and not _orig12.exists())

with _iso10("sr9_errors") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _orig12 = _lost12()
    _other = "9f" * 32
    _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_other, _OHJ12]})
    check("I9 #9: a JSON original without a backup copy does not stop the next one; failed counts exactly the one",
          [(i["hash"][:2], i["status"]) for i in _rep["items"]] == [("9f", "no_backup"), (_OHJ12[:2], "repaired")]
          and (_rep["ok"], _rep["failed"]) == (1, 1))
    _orig12.unlink()
    with patch.object(silo_repair.backup_bulk, "read_original_copy", side_effect=[OSError("disk exploded"), None]):
        _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12, _other]})
    check("I9 #9: an exception while reading the backup is one error with a reason, the next original goes on",
          _rep["items"][0]["status"] == "error" and "disk exploded" in _rep["items"][0]["reason"]
          and _rep["items"][0]["kind"] == "json" and _rep["items"][1]["status"] == "no_backup"
          and (_rep["ok"], _rep["failed"]) == (0, 2))
    with patch.object(silo_repair.bulk_writer, "store_original", return_value=silo_repair.bulk_writer.FAILED):
        _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12]})
    check("I9 #9: a copy the bulk writer refuses is an error with a reason, nothing is created",
          _rep["items"][0]["status"] == "error" and "refused" in _rep["items"][0]["reason"]
          and (_rep["ok"], _rep["failed"]) == (0, 1) and not _orig12.exists())
    _zip12 = cfg.BULK_SOURCE_BACKUP_DIR / f"{_OHJ12[:2]}.zip"
    with zipfile.ZipFile(_zip12, "w") as _zf:
        _zf.writestr(f"{_OHJ12}.json", b"other bytes")
    _rep = silo_repair.repair_silos({**_E3, "bulk_json_originals_missing": [_OHJ12]})
    check("I9 #9: a backup copy whose bytes do not match the hash is refused (an error), nothing is stored",
          _rep["items"][0]["status"] == "error" and not _orig12.exists())

with _iso10("sr9_both") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_f10, _day_f10, _before = _lost10()
    _orig11 = _lost11()
    _orig12 = _lost12()
    _put3(cfg.SUMMARY_DIR / "garmin_2025-12-30.json", {"date": "2025-12-30"})                   # a real orphan (#5)
    _found = _sc10.check_silos()
    check("I9 #9: a lost FIT and a lost JSON original are found together, each in its own list",
          _found["bulk_originals_missing"] == [_OH11] and _found["bulk_json_originals_missing"] == [_OHJ12])
    _rep = silo_repair.repair_silos({**_found, "bulk_lost_aggregates": [_dt3(_F10)], "summary_without_raw": [_dt3("2025-12-30")]})
    check("I9 #9: one repair run restores both, FIT before JSON, after #8 and before #5; all four are repaired",
          [(i["category"], i.get("kind")) for i in _rep["items"]] == [("8", "aggregates"), ("9", None), ("9", "json"), ("5", None)]
          and (_rep["ok"], _rep["failed"]) == (4, 0) and _orig11.exists() and _orig11.read_bytes() == _OR11
          and _orig12.exists() and _orig12.read_bytes() == _ORJ12)

# ── Aufräumen I2 — isolierte Umgebung zurücksetzen ──────────────────────────
os.environ["GARMIN_OUTPUT_DIR"] = _i2_orig_env
importlib.reload(cfg)
importlib.reload(silo_repair)
shutil.rmtree(_i2_dir, ignore_errors=True)

summary()
