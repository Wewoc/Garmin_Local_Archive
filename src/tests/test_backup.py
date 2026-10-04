#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_backup.py — garmin_backup, garmin_backup_source

Run from the project folder:
    python tests/test_backup.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock as _mock
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  4f. garmin_backup, garmin_backup_source — consolidation, force-replace,
#      quality-log backup, integrity check, restore (v1.7.4.0.2)
#      The raw and source backup modules are near-identical copies; the shared
#      scenarios run once per module so the two cannot drift apart unnoticed.
# ══════════════════════════════════════════════════════════════════════════════
section("4f. garmin_backup, garmin_backup_source — consolidation, restore")
import garmin_backup as _q_backup_mod
import garmin_backup_source as _q_backup_src

_BK_KINDS = [
    {"name": "raw", "mod": _q_backup_mod,
     "consolidate": "_consolidate_raw_months", "backup": "backup_raw",
     "src_dir": "RAW_DIR", "bk_dir": "RAW_BACKUP_DIR",
     "prefix": "garmin_raw_", "zip_prefix": "raw_backup_"},
    {"name": "source", "mod": _q_backup_src,
     "consolidate": "_consolidate_source_months", "backup": "backup_source",
     "src_dir": "SOURCE_DIR", "bk_dir": "SOURCE_BACKUP_DIR",
     "prefix": "garmin_source_", "zip_prefix": "source_backup_"},
]


def _bk_fn(k, day):
    return f"{k['prefix']}{day}.json"


def _bk_dir(k):
    return getattr(cfg, k["bk_dir"])


def _bk_src(k):
    return getattr(cfg, k["src_dir"])


def _bk_zip(k, month):
    return _bk_dir(k) / f"{k['zip_prefix']}{month}.zip"


def _zip_write(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)


def _zip_read(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def _bk_old_zip_new_dir(k):
    """Month 2024-08: ZIP holds old 26/27; the month directory holds new 27/28."""
    _bk_dir(k).mkdir(parents=True, exist_ok=True)
    _zip_write(_bk_zip(k, "2024-08"), {_bk_fn(k, "2024-08-26"): "old-26",
                                       _bk_fn(k, "2024-08-27"): "old-27"})
    md = _bk_dir(k) / "2024-08"
    md.mkdir()
    (md / _bk_fn(k, "2024-08-27")).write_text("new-27", encoding="utf-8")
    (md / _bk_fn(k, "2024-08-28")).write_text("new-28", encoding="utf-8")
    return md


for _k in _BK_KINDS:
    _n, _mod = _k["name"], _k["mod"]
    _cons = getattr(_mod, _k["consolidate"])
    _bak = getattr(_mod, _k["backup"])
    _x27 = _bk_fn(_k, "2024-08-27")

    # -- Force-Replace through the consolidation function ----------------------
    with _isolated_log_env(f"bk_force_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        _cons(current_month="2024-09", force_filenames={_x27})
        check(f"{_n} consolidate force: the forced file replaces its ZIP entry",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "new-27")
        check(f"{_n} consolidate force: other ZIP entries stay untouched, new file appended",
              _zip_read(_bk_zip(_k, "2024-08")) == {
                  _bk_fn(_k, "2024-08-26"): "old-26", _x27: "new-27",
                  _bk_fn(_k, "2024-08-28"): "new-28"})
        with zipfile.ZipFile(_bk_zip(_k, "2024-08")) as _z:
            check(f"{_n} consolidate force: resulting ZIP passes its integrity check",
                  _z.testzip() is None)
        check(f"{_n} consolidate force: month directory removed, no .zip.tmp left",
              not _md.exists() and list(_bk_dir(_k).glob("*.tmp")) == [])

    with _isolated_log_env(f"bk_noforce_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        _cons(current_month="2024-09")
        check(f"{_n} consolidate without force: existing ZIP entry is kept, missing file appended",
              _zip_read(_bk_zip(_k, "2024-08")) == {
                  _bk_fn(_k, "2024-08-26"): "old-26", _x27: "old-27",
                  _bk_fn(_k, "2024-08-28"): "new-28"})
        check(f"{_n} consolidate without force: month directory removed", not _md.exists())

    with _isolated_log_env(f"bk_force_swapfail_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        with patch("os.replace", side_effect=OSError("locked")):
            _cons(current_month="2024-09", force_filenames={_x27})
        check(f"{_n} consolidate force: failing swap keeps the old ZIP entry",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "old-27")
        check(f"{_n} consolidate force: failing swap keeps the directory as fallback",
              _md.exists() and (_md / _x27).read_text(encoding="utf-8") == "new-27")
        check(f"{_n} consolidate force: failing swap cleans up its temp ZIP",
              list(_bk_dir(_k).glob("*.tmp")) == [])

    with _isolated_log_env(f"bk_force_cleanupfail_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        with patch("os.replace", side_effect=OSError("locked")), \
             patch.object(Path, "unlink", side_effect=OSError("also locked")):
            _cons(current_month="2024-09", force_filenames={_x27})
        check(f"{_n} consolidate force: failing swap and failing cleanup -> no crash, ZIP intact",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "old-27" and _md.exists())
        for _t in _bk_dir(_k).glob("*.tmp"):
            _t.unlink()

    with _isolated_log_env(f"bk_force_badzip_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        with patch.object(zipfile.ZipFile, "testzip", side_effect=[None, "broken.json"]):
            _cons(current_month="2024-09", force_filenames={_x27})
        check(f"{_n} consolidate force: rebuilt ZIP failing its check is not swapped in",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "old-27" and _md.exists())

    with _isolated_log_env(f"bk_append_badzip_{_n}"):
        _md = _bk_old_zip_new_dir(_k)
        with patch.object(zipfile.ZipFile, "testzip", return_value="broken.json"):
            _cons(current_month="2024-09")
        check(f"{_n} consolidate: ZIP failing its check after appending keeps the directory",
              _md.exists())

    with _isolated_log_env(f"bk_new_badzip_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        _md = _bk_dir(_k) / "2024-07"
        _md.mkdir()
        (_md / _bk_fn(_k, "2024-07-01")).write_text("seven", encoding="utf-8")
        with patch.object(zipfile.ZipFile, "testzip", return_value="broken.json"):
            _cons(current_month="2024-09")
        check(f"{_n} consolidate: newly built ZIP failing its check keeps the directory",
              _md.exists())

    # -- consolidation edge cases ----------------------------------------------
    with _isolated_log_env(f"bk_edges_{_n}"):
        _cons(current_month="2024-09")
        check(f"{_n} consolidate: no backup folder at all -> no crash", True)
        _bk_dir(_k).mkdir(parents=True)
        (_bk_dir(_k) / "2024-07").mkdir()
        (_bk_dir(_k) / "2024-09").mkdir()
        (_bk_dir(_k) / "2024-09" / _bk_fn(_k, "2024-09-01")).write_text("cur", encoding="utf-8")
        (_bk_dir(_k) / "stray.txt").write_text("not a month folder", encoding="utf-8")
        _cons(current_month="2024-09")
        check(f"{_n} consolidate: empty completed month folder is removed",
              not (_bk_dir(_k) / "2024-07").exists())
        check(f"{_n} consolidate: the current month folder is left alone",
              (_bk_dir(_k) / "2024-09" / _bk_fn(_k, "2024-09-01")).exists()
              and not _bk_zip(_k, "2024-09").exists())

    # -- backup of one day ------------------------------------------------------
    with _isolated_log_env(f"bk_one_{_n}"):
        _bk_src(_k).mkdir(parents=True)
        check(f"{_n} backup of a day: source file missing -> False",
              _bak("2024-08-27") == False)
        (_bk_src(_k) / _x27).write_text("content", encoding="utf-8")
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            _res = _bak("2024-08-27")
        check(f"{_n} backup of a day: write failure -> False, no crash", _res == False)

    # -- Ist-Stand: Force-Refetch of a day in an already consolidated month -----
    # The new version never reaches the ZIP (see ROADMAP v1.7.4.2). To be rewritten
    # to the new contract when that is fixed.
    with _isolated_log_env(f"bk_force_ist_{_n}"):
        _bk_src(_k).mkdir(parents=True)
        _bk_dir(_k).mkdir(parents=True)
        _zip_write(_bk_zip(_k, "2024-08"), {_x27: "old-27"})
        (_bk_src(_k) / _x27).write_text("new-27", encoding="utf-8")
        check(f"{_n} Ist-Stand force backup: call succeeds", _bak("2024-08-27", force=True) == True)
        check(f"{_n} Ist-Stand force backup: the ZIP still holds the old version",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "old-27")
        check(f"{_n} Ist-Stand force backup: the new version waits in the month directory",
              (_bk_dir(_k) / "2024-08" / _x27).read_text(encoding="utf-8") == "new-27")
        _later = _bk_fn(_k, "2024-10-01")
        (_bk_src(_k) / _later).write_text("later", encoding="utf-8")
        _bak("2024-10-01")
        check(f"{_n} Ist-Stand force backup: a later ordinary backup drops the new version",
              not (_bk_dir(_k) / "2024-08").exists()
              and _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "old-27")

    # -- backfill and the check that counts missing backups ---------------------
    with _isolated_log_env(f"bk_backfill_{_n}"):
        _empty = _mod.backfill_raw() if _n == "raw" else _mod.backfill_source()
        _check_fn = (_mod.check_raw_backfill_needed if _n == "raw"
                     else _mod.check_source_backfill_needed)
        check(f"{_n} backfill: no source folder -> nothing copied, no crash",
              _empty["copied"] == 0)
        check(f"{_n} backfill check: no source folder -> 0", _check_fn() == 0)

        _bk_src(_k).mkdir(parents=True)
        for _d in ("2024-08-01", "2024-08-02"):
            (_bk_src(_k) / _bk_fn(_k, _d)).write_text(f"day {_d}", encoding="utf-8")
        check(f"{_n} backfill check: counts the two files without a backup", _check_fn() == 2)
        _err_key = "errors" if _n == "raw" else "failed"
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            _res = _mod.backfill_raw() if _n == "raw" else _mod.backfill_source()
        check(f"{_n} backfill: copy failures are counted, nothing copied",
              _res[_err_key] == 2 and _res["copied"] == 0)
        _res = _mod.backfill_raw() if _n == "raw" else _mod.backfill_source()
        check(f"{_n} backfill: both files copied", _res["copied"] == 2)
        check(f"{_n} backfill: a completed month is consolidated into a ZIP right away",
              _zip_read(_bk_zip(_k, "2024-08")) == {
                  _bk_fn(_k, "2024-08-01"): "day 2024-08-01",
                  _bk_fn(_k, "2024-08-02"): "day 2024-08-02"}
              and not (_bk_dir(_k) / "2024-08").exists())
        check(f"{_n} backfill check: 0 once everything is backed up", _check_fn() == 0)


# -- quality_log backup, yearly consolidation, restore ---------------------------
with _isolated_log_env("bk_qlog"):
    _q_backup_mod.backup_quality_log()
    check("backup_quality_log: no quality_log.json -> nothing happens, no backup folder",
          not cfg.LOG_BACKUP_DIR.exists())
    _put_log({"days": [{"date": "2024-01-01"}]})
    with patch("zipfile.ZipFile", side_effect=OSError("disk full")):
        _q_backup_mod.backup_quality_log()
    check("backup_quality_log: ZIP creation failing -> no crash", True)

with _isolated_log_env("bk_years"):
    cfg.LOG_BACKUP_DIR.mkdir(parents=True)
    for _m in ("2022-11", "2022-12", "2025-01", "2023-12"):
        _zip_write(cfg.LOG_BACKUP_DIR / f"quality_log_{_m}.zip", {"quality_log.json": f"snap {_m}"})
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2023.zip", {"marker.txt": "already here"})
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_abcd-ef.zip", {"x": "bad name"})
    _yearly_2023_before = (cfg.LOG_BACKUP_DIR / "quality_log_2023.zip").read_bytes()
    _q_backup_mod._consolidate_log_years(current_year=2025)
    check("quality-log years: a completed year gets a yearly ZIP with all its monthly ZIPs",
          sorted(zipfile.ZipFile(cfg.LOG_BACKUP_DIR / "quality_log_2022.zip").namelist())
          == ["quality_log_2022-11.zip", "quality_log_2022-12.zip"])
    check("quality-log years: the monthly ZIPs are kept",
          (cfg.LOG_BACKUP_DIR / "quality_log_2022-11.zip").exists()
          and (cfg.LOG_BACKUP_DIR / "quality_log_2022-12.zip").exists())
    check("quality-log years: the current year is not consolidated",
          not (cfg.LOG_BACKUP_DIR / "quality_log_2025.zip").exists())
    check("quality-log years: an existing yearly ZIP is not overwritten",
          (cfg.LOG_BACKUP_DIR / "quality_log_2023.zip").read_bytes() == _yearly_2023_before)
    check("quality-log years: a file name with an unreadable year is skipped",
          not (cfg.LOG_BACKUP_DIR / "quality_log_abcd.zip").exists())

with _isolated_log_env("bk_years_fail"):
    cfg.LOG_BACKUP_DIR.mkdir(parents=True)
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2021-05.zip", {"quality_log.json": "snap"})
    with patch("zipfile.ZipFile", side_effect=OSError("disk full")):
        _q_backup_mod._consolidate_log_years(current_year=2025)
    check("quality-log years: yearly ZIP cannot be created -> no crash",
          not (cfg.LOG_BACKUP_DIR / "quality_log_2021.zip").exists())

with _isolated_log_env("bk_restore_qlog"):
    cfg.LOG_BACKUP_DIR.mkdir(parents=True)
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2024-02.zip",
               {"quality_log.json": json.dumps({"days": [{"date": "2024-02-01"}]})})
    (cfg.LOG_BACKUP_DIR / "quality_log_2024-03.zip").write_bytes(b"this is not a zip file")
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2024-04.zip", {"other.json": "{}"})
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2024-05.zip",
               {"quality_log.json": json.dumps({"days": "not a list"})})
    _restored = _q_backup_mod.restore_quality_log()
    check("restore_quality_log: skips unusable newer snapshots, takes the newest valid one",
          _restored is not None and _restored["days"][0]["date"] == "2024-02-01")
    with patch.object(zipfile.ZipFile, "testzip", return_value="quality_log.json"):
        check("restore_quality_log: snapshots failing their integrity check -> None",
              _q_backup_mod.restore_quality_log() is None)
    (cfg.LOG_BACKUP_DIR / "quality_log_2024-02.zip").unlink()
    check("restore_quality_log: only unusable snapshots left -> None",
          _q_backup_mod.restore_quality_log() is None)

# -- check_raw_integrity ----------------------------------------------------------
with _isolated_log_env("bk_integrity"):
    cfg.RAW_DIR.mkdir(parents=True)
    cfg.RAW_BACKUP_DIR.mkdir(parents=True)
    (cfg.RAW_DIR / "garmin_raw_2024-08-01.json").write_text("{}", encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_2024-08-02.json").write_text("{broken", encoding="utf-8")
    (cfg.RAW_BACKUP_DIR / "2024-08").mkdir()
    (cfg.RAW_BACKUP_DIR / "2024-08" / "garmin_raw_2024-08-02.json").write_text("{}", encoding="utf-8")
    _put_log({"days": [
        {"date": "2024-08-01", "write": True},
        {"date": "2024-08-02", "write": True},
        {"date": "2024-08-03", "write": True},
        {"write": True},
        {"date": "2024-08-04", "write": False},
    ]})
    _ri = _q_backup_mod.check_raw_integrity()
    check("check_raw_integrity: a present but unreadable raw file counts as missing",
          _ri["missing_days"] == ["2024-08-02", "2024-08-03"])
    check("check_raw_integrity: only days without any backup copy are listed as no_backup",
          _ri["no_backup"] == ["2024-08-03"])
    check("check_raw_integrity: entry without a date is skipped, write=False not examined",
          _ri["total_checked"] == 4 and _ri["error"] is None)

# -- restore_raw_days -------------------------------------------------------------
with _isolated_log_env("bk_restore_raw"):
    cfg.RAW_DIR.mkdir(parents=True)
    cfg.RAW_BACKUP_DIR.mkdir(parents=True)
    _payload = json.dumps({"date": "2024-08-27", "note": "Grüße"}, ensure_ascii=False)
    _name = "garmin_raw_2024-08-27.json"

    _zip_write(cfg.RAW_BACKUP_DIR / "raw_backup_2024-08.zip", {_name: _payload})
    _rr = _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: restores a day from the monthly ZIP",
          _rr["restored"] == ["2024-08-27"] and _rr["failed"] == [])
    check("restore_raw_days: the restored file is byte-identical to the backed-up one",
          (cfg.RAW_DIR / _name).read_bytes() == _payload.encode("utf-8"))

    (cfg.RAW_DIR / _name).unlink()
    (cfg.RAW_BACKUP_DIR / "2024-08").mkdir()
    (cfg.RAW_BACKUP_DIR / "2024-08" / _name).write_text("from the directory", encoding="utf-8")
    _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: the open month directory takes precedence over the ZIP",
          (cfg.RAW_DIR / _name).read_text(encoding="utf-8") == "from the directory")

    (cfg.RAW_DIR / _name).unlink()
    (cfg.RAW_BACKUP_DIR / "2024-08" / _name).unlink()
    (cfg.RAW_BACKUP_DIR / "2024-08" / _name).mkdir()     # exists, but cannot be read as a file
    _rr = _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: unreadable directory copy -> falls back to the ZIP",
          _rr["restored"] == ["2024-08-27"]
          and (cfg.RAW_DIR / _name).read_bytes() == _payload.encode("utf-8"))
    shutil.rmtree(cfg.RAW_BACKUP_DIR / "2024-08")

    (cfg.RAW_DIR / _name).unlink()
    _zip_write(cfg.RAW_BACKUP_DIR / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-01.json": "{}"})
    _rr = _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: ZIP without that day -> failed with a reason",
          _rr["failed"] == ["2024-08-27"] and "zip restore failed" in _rr["errors"]["2024-08-27"]
          and not (cfg.RAW_DIR / _name).exists())

    (cfg.RAW_BACKUP_DIR / "raw_backup_2024-08.zip").write_bytes(b"not a zip")
    _rr = _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: corrupt ZIP -> failed with a reason, no crash",
          _rr["failed"] == ["2024-08-27"] and "zip restore failed" in _rr["errors"]["2024-08-27"])

    _zip_write(cfg.RAW_BACKUP_DIR / "raw_backup_2024-08.zip", {_name: _payload})
    cfg.QUALITY_LOG_FILE.write_text("{broken json", encoding="utf-8")
    (cfg.RAW_DIR / _name).write_text("existing", encoding="utf-8")
    _rr = _q_backup_mod.restore_raw_days(["2024-08-27"])
    check("restore_raw_days: unreadable quality_log disables the guard, restore still runs",
          _rr["restored"] == ["2024-08-27"]
          and (cfg.RAW_DIR / _name).read_bytes() == _payload.encode("utf-8"))

# ══════════════════════════════════════════════════════════════════════════════
#  B. garmin_backup (v1.5.1)
# ══════════════════════════════════════════════════════════════════════════════
section("B. garmin_backup (v1.5.1)")
import garmin_backup as backup
importlib.reload(backup)

# Pfade korrekt aus cfg
check("backup: BACKUP_DIR",      cfg.BACKUP_DIR     == _TMPDIR / "garmin_data" / "backup")
check("backup: LOG_BACKUP_DIR",  cfg.LOG_BACKUP_DIR == cfg.BACKUP_DIR / "log")
check("backup: RAW_BACKUP_DIR",  cfg.RAW_BACKUP_DIR == cfg.BACKUP_DIR / "raw")
check("backup: AUTORESTORE_DIR", cfg.AUTORESTORE_DIR == cfg.BACKUP_DIR / "autorestore")

# backup_raw — Quelldatei fehlt → False
check("backup_raw: missing source → False",  backup.backup_raw("1900-01-01") == False)

# backup_raw — Quelldatei vorhanden → True, Datei landet in backup/raw/YYYY-MM/
_bkp_date = "2024-03-15"
_bkp_raw  = cfg.RAW_DIR / f"garmin_raw_{_bkp_date}.json"
cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
_bkp_raw.write_text(json.dumps({"date": _bkp_date, "test": True}), encoding="utf-8")
_bkp_result = backup.backup_raw(_bkp_date)
check("backup_raw: success → True",
      _bkp_result == True)
check("backup_raw: file in month dir",
      (cfg.RAW_BACKUP_DIR / "2024-03" / f"garmin_raw_{_bkp_date}.json").exists())

# _consolidate_raw_months — abgeschlossener Monat wird gezippt
_old_date = "2024-01-10"
_old_dir  = cfg.RAW_BACKUP_DIR / "2024-01"
_old_dir.mkdir(parents=True, exist_ok=True)
(_old_dir / f"garmin_raw_{_old_date}.json").write_text("{}", encoding="utf-8")
backup._consolidate_raw_months(current_month="2024-03")
check("consolidate: old month zipped",
      (cfg.RAW_BACKUP_DIR / "raw_backup_2024-01.zip").exists())
check("consolidate: old month dir removed",
      not _old_dir.exists())
check("consolidate: current month not zipped",
      not (cfg.RAW_BACKUP_DIR / "raw_backup_2024-03.zip").exists())

# backup_quality_log — erstellt monthly snapshot
import garmin_quality as quality_bsec
importlib.reload(quality_bsec)
_data_bsec = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": "2024-01-01", "quality": "high", "reason": "ok",
         "write": True, "source": "api", "recheck": False,
         "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None, "fields": {}}
    ]
}
quality_bsec._save_quality_log(_data_bsec, skip_backup=True)
backup.backup_quality_log()
_month_str = date.today().strftime("%Y-%m")
check("backup_quality_log: monthly snapshot created",
      (cfg.LOG_BACKUP_DIR / f"quality_log_{_month_str}.zip").exists())

# restore_quality_log — snapshot vorhanden → returns dict
_restored = backup.restore_quality_log()
check("restore_quality_log: returns dict",   isinstance(_restored, dict))
check("restore_quality_log: has days key",   "days" in (_restored or {}))

# restore_quality_log — kein Backup → None
_empty_bkp = Path(tempfile.mkdtemp(prefix="garmin_nobkp_"))
with _mock.patch.object(cfg, "LOG_BACKUP_DIR", _empty_bkp):
    _no_restore = backup.restore_quality_log()
check("restore_quality_log: no backup → None",  _no_restore is None)
shutil.rmtree(_empty_bkp, ignore_errors=True)

# check_raw_integrity — write=True Eintrag ohne Raw-Datei → missing
_missing_date = "2024-06-01"
_qlog_missing = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": _missing_date, "quality": "high", "reason": "ok",
         "write": True, "source": "api", "recheck": False,
         "attempts": 0, "last_checked": "2024-06-01", "last_attempt": None, "fields": {}}
    ]
}
quality_bsec._save_quality_log(_qlog_missing, skip_backup=True)
_integrity2 = backup.check_raw_integrity()
check("check_raw_integrity: returns dict",       isinstance(_integrity2, dict))
check("check_raw_integrity: keys present",
      all(k in _integrity2 for k in ("missing_days", "no_backup", "total_checked")))
check("check_raw_integrity: missing day detected",
      _missing_date in _integrity2["missing_days"])
check("check_raw_integrity: no backup for missing day",
      _missing_date in _integrity2["no_backup"])
check("check_raw_integrity: error is None on success",
      _integrity2.get("error") is None)

# check_raw_integrity — kaputtes quality_log.json → error gesetzt (Kandidat 2, Fehlersichtbarkeit)
_corrupt_qlog_backup = cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8")
cfg.QUALITY_LOG_FILE.write_text("{not valid json", encoding="utf-8")
_integrity_corrupt = backup.check_raw_integrity()
check("check_raw_integrity: error set on corrupt quality_log",
      _integrity_corrupt.get("error") is not None)
check("check_raw_integrity: empty missing_days on corrupt quality_log",
      _integrity_corrupt["missing_days"] == [])
cfg.QUALITY_LOG_FILE.write_text(_corrupt_qlog_backup, encoding="utf-8")

# restore_raw_days — kein Backup → landed in failed
_restore_result = backup.restore_raw_days([_missing_date])
check("restore_raw_days: no backup → failed",
      _missing_date in _restore_result.get("failed", []))
check("restore_raw_days: errors has reason for no-backup case",
      _restore_result.get("errors", {}).get(_missing_date) == "no backup found")

# restore_raw_days — Backup vorhanden → restored
_restore_month_dir = cfg.RAW_BACKUP_DIR / "2024-06"
_restore_month_dir.mkdir(parents=True, exist_ok=True)
(_restore_month_dir / f"garmin_raw_{_missing_date}.json").write_text(
    json.dumps({"date": _missing_date}), encoding="utf-8")
_restore_result2 = backup.restore_raw_days([_missing_date])
check("restore_raw_days: from dir → restored",
      _missing_date in _restore_result2.get("restored", []))
check("restore_raw_days: file exists after restore",
      (cfg.RAW_DIR / f"garmin_raw_{_missing_date}.json").exists())

# Fix 2 — Gutfall: file exists but quality is "standard" (not "high") →
# guard does NOT block, restore proceeds as before.
_restore_std_date = "2024-06-15"
_qlog_std = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": _restore_std_date, "quality": "standard", "reason": "ok",
         "write": True, "source": "api", "recheck": False,
         "attempts": 0, "last_checked": _restore_std_date, "last_attempt": None, "fields": {}}
    ]
}
quality_bsec._save_quality_log(_qlog_std, skip_backup=True)
(cfg.RAW_DIR / f"garmin_raw_{_restore_std_date}.json").write_text(
    json.dumps({"date": _restore_std_date, "stale": True}), encoding="utf-8")
_restore_std_month_dir = cfg.RAW_BACKUP_DIR / "2024-06"
(_restore_std_month_dir / f"garmin_raw_{_restore_std_date}.json").write_text(
    json.dumps({"date": _restore_std_date, "from_backup": True}), encoding="utf-8")
_restore_std_result = backup.restore_raw_days([_restore_std_date])
check("f2: standard quality does not block restore",
      _restore_std_date in _restore_std_result.get("restored", []))
check("f2: standard quality — file overwritten from backup",
      json.loads((cfg.RAW_DIR / f"garmin_raw_{_restore_std_date}.json").read_text()).get("from_backup") is True)

# Fix 2 — Schlechtfall: file exists AND quality is "high" → guard blocks,
# restore is skipped, existing file untouched.
_restore_high_date = "2024-06-20"
_qlog_high = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": _restore_high_date, "quality": "high", "reason": "ok",
         "write": True, "source": "api", "recheck": False,
         "attempts": 0, "last_checked": _restore_high_date, "last_attempt": None, "fields": {}}
    ]
}
quality_bsec._save_quality_log(_qlog_high, skip_backup=True)
(cfg.RAW_DIR / f"garmin_raw_{_restore_high_date}.json").write_text(
    json.dumps({"date": _restore_high_date, "current": True}), encoding="utf-8")
_restore_high_month_dir = cfg.RAW_BACKUP_DIR / "2024-06"
(_restore_high_month_dir / f"garmin_raw_{_restore_high_date}.json").write_text(
    json.dumps({"date": _restore_high_date, "from_backup": True}), encoding="utf-8")
_restore_high_result = backup.restore_raw_days([_restore_high_date])
check("f2: high quality blocks restore",
      _restore_high_date in _restore_high_result.get("skipped_already_current", []))
check("f2: high quality — file not overwritten",
      json.loads((cfg.RAW_DIR / f"garmin_raw_{_restore_high_date}.json").read_text()).get("current") is True)
check("f2: high quality — not counted as restored or failed",
      _restore_high_date not in _restore_high_result.get("restored", []) and
      _restore_high_date not in _restore_high_result.get("failed", []))

# check_raw_backfill_needed — alle bestehenden Raw-Dateien zuerst sichern
# damit der Zähler auf 0 steht, dann neue Datei hinzufügen
backup.backfill_raw()  # sichert alle bisherigen Test-Dateien
check("backfill_needed: after initial backfill → 0",
      backup.check_raw_backfill_needed() == 0)

# check_raw_backfill_needed — neue Raw-Datei ohne Backup → count > 0
_bf_date = "2024-10-01"
_bf_raw  = cfg.RAW_DIR / f"garmin_raw_{_bf_date}.json"
cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
_bf_raw.write_text(json.dumps({"date": _bf_date}), encoding="utf-8")
check("backfill_needed: unbackedup file → ≥1",
      backup.check_raw_backfill_needed() >= 1)

# backfill_raw — kopiert neue Datei
_bf_result = backup.backfill_raw()
check("backfill: returns dict",          isinstance(_bf_result, dict))
check("backfill: ≥1 copied",            _bf_result["copied"] >= 1)
check("backfill: 0 errors",             _bf_result["errors"] == 0)
check("backfill: zip created for 2024-10",
      (cfg.RAW_BACKUP_DIR / "raw_backup_2024-10.zip").exists())

# backfill_raw — idempotent, zweiter Aufruf → alles skipped
_bf_result2 = backup.backfill_raw()
check("backfill: idempotent → copied=0", _bf_result2["copied"] == 0)
check("backfill: idempotent → skipped≥1", _bf_result2["skipped"] >= 1)

# check_raw_backfill_needed — nach Backfill → 0
check("backfill_needed: after backfill → 0",
      backup.check_raw_backfill_needed() == 0)

# _zip_contains helper — eigenes Temp-Dir, keine Kollision mit anderen ZIPs
_zip_tmpdir = Path(tempfile.mkdtemp(prefix="garmin_zip_"))
_test_zip   = _zip_tmpdir / "test_helper.zip"
with zipfile.ZipFile(_test_zip, "w") as zf:
    zf.writestr("hello.json", "{}")
check("_zip_contains: present → True",   backup._zip_contains(_test_zip, "hello.json"))
check("_zip_contains: absent → False",   not backup._zip_contains(_test_zip, "nope.json"))
check("_zip_contains: bad path → False", not backup._zip_contains(_zip_tmpdir / "nonexistent.zip", "x"))
shutil.rmtree(_zip_tmpdir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  F. garmin_backup_source (v1.6.0.4)
# ══════════════════════════════════════════════════════════════════════════════
section("F. garmin_backup_source (v1.6.0.4)")
import garmin_backup_source as backup_src
importlib.reload(backup_src)

# ── Pfad-Ableitung ────────────────────────────────────────────────────────────
check("backup_src: SOURCE_BACKUP_DIR derived",
      cfg.SOURCE_BACKUP_DIR == _TMPDIR / "garmin_data" / "backup" / "source")

# ── backup_source: Quelldatei fehlt → False ───────────────────────────────────
check("backup_source: missing source → False",
      backup_src.backup_source("1900-01-01") == False)

# ── backup_source: normaler Write → True, Datei in YYYY-MM/ ──────────────────
_bsrc_date  = "2024-03-15"
_bsrc_file  = cfg.SOURCE_DIR / f"garmin_source_{_bsrc_date}.json"
cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
_bsrc_file.write_text('{"date": "2024-03-15"}', encoding="utf-8")

_bsrc_ok = backup_src.backup_source(_bsrc_date)
check("backup_source: returns True",
      _bsrc_ok == True)
check("backup_source: file in month dir",
      (cfg.SOURCE_BACKUP_DIR / "2024-03" / f"garmin_source_{_bsrc_date}.json").exists())

# ── consolidate: alter Monat wird gezippt ─────────────────────────────────────
from datetime import date as _bsrc_date_cls
_bsrc_current_month = _bsrc_date_cls.today().strftime("%Y-%m")
_old_src_date = "2024-01-10"
_old_src_dir  = cfg.SOURCE_BACKUP_DIR / "2024-01"
_old_src_dir.mkdir(parents=True, exist_ok=True)
(_old_src_dir / f"garmin_source_{_old_src_date}.json").write_text("{}", encoding="utf-8")
# Aktuellen Monatsordner anlegen damit consolidate ihn korrekt überspringt
_cur_src_dir = cfg.SOURCE_BACKUP_DIR / _bsrc_current_month
_cur_src_dir.mkdir(parents=True, exist_ok=True)
(_cur_src_dir / f"garmin_source_{_bsrc_current_month}-01.json").write_text("{}", encoding="utf-8")
backup_src._consolidate_source_months(current_month=_bsrc_current_month)
check("consolidate: old month zipped",
      (cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip").exists())
check("consolidate: old month dir removed",
      not _old_src_dir.exists())
check("consolidate: current month not zipped",
      not (cfg.SOURCE_BACKUP_DIR / f"source_backup_{_bsrc_current_month}.zip").exists())

# ── check_source_backfill_needed ──────────────────────────────────────────────
# Neue source-Datei ohne Backup → count ≥ 1
_bsrc_date2 = "2024-03-16"
_bsrc_file2 = cfg.SOURCE_DIR / f"garmin_source_{_bsrc_date2}.json"
_bsrc_file2.write_text('{"date": "2024-03-16"}', encoding="utf-8")
check("backfill_needed: unbackedup file → ≥1",
      backup_src.check_source_backfill_needed() >= 1)

# ── backfill_source ───────────────────────────────────────────────────────────
_bfill_result = backup_src.backfill_source()
check("backfill_source: returns dict",        isinstance(_bfill_result, dict))
check("backfill_source: ≥1 copied",           _bfill_result["copied"] >= 1)
check("backfill_source: failed=0",            _bfill_result["failed"] == 0)

# backfill idempotent
_bfill_result2 = backup_src.backfill_source()
check("backfill_source: idempotent → copied=0",   _bfill_result2["copied"] == 0)
check("backfill_source: idempotent → skipped≥1",  _bfill_result2["skipped"] >= 1)

# check_source_backfill_needed → 0 nach Backfill
check("backfill_needed: after backfill → 0",
      backup_src.check_source_backfill_needed() == 0)

# ── _zip_contains helper ──────────────────────────────────────────────────────
check("backup_src: _zip_contains present → True",
      backup_src._zip_contains(
          cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip",
          f"garmin_source_{_old_src_date}.json"))
check("backup_src: _zip_contains absent → False",
      not backup_src._zip_contains(
          cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip",
          "nonexistent.json"))

# ── Leaf-Node check — keine Pipeline-Imports ──────────────────────────────────
import ast as _bsrc_ast
_bsrc_py = Path(__file__).parent.parent / "garmin" / "garmin_backup_source.py"
if _bsrc_py.exists():
    _bsrc_tree     = _bsrc_ast.parse(_bsrc_py.read_text(encoding="utf-8"))
    _bsrc_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_source_writer",
    }
    _bsrc_imports = set()
    for _n in _bsrc_ast.walk(_bsrc_tree):
        if isinstance(_n, _bsrc_ast.Import):
            for _a in _n.names:
                _bsrc_imports.add(_a.name.split(".")[0])
        elif isinstance(_n, _bsrc_ast.ImportFrom):
            if _n.module:
                _bsrc_imports.add(_n.module.split(".")[0])
    check("backup_src: Leaf-Node — no forbidden pipeline imports",
          _bsrc_imports.isdisjoint(_bsrc_forbidden))

summary()
