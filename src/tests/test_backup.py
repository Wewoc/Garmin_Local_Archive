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

    # -- Force-Refetch of a day in an already consolidated month (v1.7.4.2) -----
    # Fixed contract: force=True makes the forced date's own month reachable
    # by the Force-Replace block, so the ZIP entry is replaced immediately —
    # no waiting for a later backup. Third step is now an idempotency check,
    # not a loss proof: Timo's call (2026-10-06) — kept deliberately instead
    # of dropped, catches exactly the order/state bug class this v1.7.4 round
    # is about: an unrelated later backup must not re-touch an
    # already-replaced entry.
    with _isolated_log_env(f"bk_force_ist_{_n}"):
        _bk_src(_k).mkdir(parents=True)
        _bk_dir(_k).mkdir(parents=True)
        _zip_write(_bk_zip(_k, "2024-08"), {_x27: "old-27"})
        (_bk_src(_k) / _x27).write_text("new-27", encoding="utf-8")
        check(f"{_n} force backup: call succeeds", _bak("2024-08-27", force=True) == True)
        check(f"{_n} force backup: the ZIP now holds the new version",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "new-27")
        check(f"{_n} force backup: the month directory is consolidated away",
              not (_bk_dir(_k) / "2024-08").exists())
        _later = _bk_fn(_k, "2024-10-01")
        (_bk_src(_k) / _later).write_text("later", encoding="utf-8")
        _bak("2024-10-01")
        check(f"{_n} force backup: a later ordinary backup does not re-touch the already-replaced entry",
              _zip_read(_bk_zip(_k, "2024-08"))[_x27] == "new-27")

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
#  4f2. garmin_backup, garmin_backup_source — several months at once, counters
#       and log lines, the failure of one month must not stop the next, glob
#       order, integrity check, restore loops (v1.7.4.0.3).
#       Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4f2. garmin_backup, garmin_backup_source — months, counters, loops")


class _BLog:
    """Stands in for a module logger and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def error(self, msg, *a, **k):
        self._add("error", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)


def _blogged(mod, fn, *args, **kwargs):
    real, rec = mod.log, _BLog()
    mod.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        mod.log = real


def _mk_month(k, month, days, content="x"):
    d = _bk_dir(k) / month
    d.mkdir(parents=True, exist_ok=True)
    for day in days:
        (d / _bk_fn(k, f"{month}-{day}")).write_text(content, encoding="utf-8")
    return d


def _put_src(k, day, content="{}"):
    _bk_src(k).mkdir(parents=True, exist_ok=True)
    (_bk_src(k) / _bk_fn(k, day)).write_text(content, encoding="utf-8")


_BF = {"raw": ("backfill_raw", "errors"), "source": ("backfill_source", "failed")}
_CUR = date.today().strftime("%Y-%m")

for _k in _BK_KINDS:
    _n, _mod = _k["name"], _k["mod"]
    _cons = getattr(_mod, _k["consolidate"])
    _bak = getattr(_mod, _k["backup"])
    _fn27 = _bk_fn(_k, "2024-08-27")
    _zname = lambda m: f"{_k['zip_prefix']}{m}.zip"      # noqa: E731

    # -- 1. force is passed on to the consolidation, two backups into one month folder
    with _isolated_log_env(f"bk2_wire_{_n}"):
        _put_src(_k, "2024-08-27")
        _calls = []
        with patch.object(_mod, _k["consolidate"], side_effect=lambda **kw: _calls.append(kw)):
            _ok1 = _bak("2024-08-27")
            _ok2 = _bak("2024-08-27", force=True)
        check(f"4f2 {_n} backup: both calls succeed (existing month folder is fine)",
              _ok1 is True and _ok2 is True)
        check(f"4f2 {_n} backup: without force the date's own month is passed through unchanged "
              f"(v1.7.4.2: with force, today's real month is passed instead, so the forced month "
              f"becomes reachable by the Force-Replace block)",
              _calls == [{"current_month": "2024-08", "force_filenames": None},
                         {"current_month": _CUR, "force_filenames": {_fn27}}])

    # -- 1b. force-refetched date whose month IS the current (still open) month —
    # ROADMAP v1.7.4.2 Open point: nothing to replace yet, no ZIP exists for an
    # open month, so the forced file simply lands in the month directory, same
    # as a non-force backup would.
    with _isolated_log_env(f"bk2_curmonth_{_n}"):
        _bk_src(_k).mkdir(parents=True)
        _today_day = f"{_CUR}-01"
        _today_fn  = _bk_fn(_k, _today_day)
        (_bk_src(_k) / _today_fn).write_text("today-content", encoding="utf-8")
        check(f"4f2 {_n} backup: force-refetch of a day in the open current month succeeds",
              _bak(_today_day, force=True) == True)
        check(f"4f2 {_n} backup: no ZIP exists yet for the open month",
              not _bk_zip(_k, _CUR).exists())
        check(f"4f2 {_n} backup: the file lands directly in the month directory",
              (_bk_dir(_k) / _CUR / _today_fn).read_text(encoding="utf-8") == "today-content")

    # -- 2. several months in one consolidation run
    with _isolated_log_env(f"bk2_months_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        (_bk_dir(_k) / "2024-04.txt").write_text("not a month folder", encoding="utf-8")
        _mk_month(_k, "2024-05", ["01"])
        _mk_month(_k, "2024-06", ["01"])
        _cons(current_month="2024-09")
        check(f"4f2 {_n} consolidate: a plain file between the month folders does not stop the run",
              _bk_zip(_k, "2024-05").exists() and _bk_zip(_k, "2024-06").exists()
              and not (_bk_dir(_k) / "2024-05").exists() and not (_bk_dir(_k) / "2024-06").exists()
              and (_bk_dir(_k) / "2024-04.txt").exists())
    with _isolated_log_env(f"bk2_future_{_n}"):
        _mk_month(_k, "2024-06", ["01"])
        _mk_month(_k, "2024-07", ["01"])
        _mk_month(_k, "2024-08", ["01"])
        _cons(current_month="2024-07")
        check(f"4f2 {_n} consolidate: the current month and any later month are left alone",
              _bk_zip(_k, "2024-06").exists() and not (_bk_dir(_k) / "2024-06").exists()
              and (_bk_dir(_k) / "2024-07").exists() and (_bk_dir(_k) / "2024-08").exists()
              and not _bk_zip(_k, "2024-07").exists() and not _bk_zip(_k, "2024-08").exists())
    with _isolated_log_env(f"bk2_empty_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        (_bk_dir(_k) / "2024-05").mkdir()
        _mk_month(_k, "2024-06", ["01"])
        _cons(current_month="2024-09")
        check(f"4f2 {_n} consolidate: an empty month folder is removed and the next month is still packed",
              not (_bk_dir(_k) / "2024-05").exists() and _bk_zip(_k, "2024-06").exists()
              and not (_bk_dir(_k) / "2024-06").exists())

    # -- 3. appended counter and its log line
    with _isolated_log_env(f"bk2_append_{_n}"):
        _bk_old_zip_new_dir(_k)
        _, _c = _blogged(_mod, _cons, current_month="2024-09")
        _app = [m for lv, m in _c if lv == "info" and "file(s) appended" in m]
        check(f"4f2 {_n} consolidate: log names exactly 1 appended file and the ZIP",
              len(_app) == 1 and f"→ 1 file(s) appended to {_zname('2024-08')}" in _app[0])
    with _isolated_log_env(f"bk2_noappend_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        _zip_write(_bk_zip(_k, "2024-08"), {_fn27: "old-27"})
        _mk_month(_k, "2024-08", ["27"], content="new-27")
        _, _c = _blogged(_mod, _cons, current_month="2024-09")
        check(f"4f2 {_n} consolidate: nothing new in the folder -> no 'appended' line, ZIP entry kept",
              not any("appended" in m for _, m in _c)
              and _zip_read(_bk_zip(_k, "2024-08")) == {_fn27: "old-27"})

    # -- 4. integrity failure in the first month does not stop the second
    with _isolated_log_env(f"bk2_integrity_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        for _m in ("2024-05", "2024-06"):
            _zip_write(_bk_zip(_k, _m), {_bk_fn(_k, f"{_m}-01"): "old"})
            _mk_month(_k, _m, ["02"])
        with patch.object(zipfile.ZipFile, "testzip", return_value="bad"):
            _, _c = _blogged(_mod, _cons, current_month="2024-09")
        _errs = [m for lv, m in _c if lv == "error"]
        check(f"4f2 {_n} consolidate: integrity failure is reported for every month, folders kept",
              any("integrity check failed after append for 2024-05" in m for m in _errs)
              and any("integrity check failed after append for 2024-06" in m for m in _errs)
              and (_bk_dir(_k) / "2024-05").exists() and (_bk_dir(_k) / "2024-06").exists())

    # -- 5. a failing force-replace in one month does not stop the next one
    for _cleanup_fails in (False, True):
        _tag = "cleanup_fails" if _cleanup_fails else "swap_fails"
        with _isolated_log_env(f"bk2_{_tag}_{_n}"):
            _bk_dir(_k).mkdir(parents=True)
            _zip_write(_bk_zip(_k, "2024-05"), {_bk_fn(_k, "2024-05-26"): "old-26",
                                                _bk_fn(_k, "2024-05-27"): "old-27"})
            _mk_month(_k, "2024-05", ["27"], content="new-27")
            _mk_month(_k, "2024-06", ["01"])
            _force = {_bk_fn(_k, "2024-05-27")}
            _patches = [patch("os.replace", side_effect=OSError("locked"))]
            if _cleanup_fails:
                _patches.append(patch.object(Path, "unlink", side_effect=OSError("also locked")))
            for _p in _patches:
                _p.start()
            try:
                _, _c = _blogged(_mod, _cons, current_month="2024-09", force_filenames=_force)
            finally:
                for _p in _patches:
                    _p.stop()
            _errs = [m for lv, m in _c if lv == "error"]
            check(f"4f2 {_n} consolidate ({_tag}): the failure is logged, the month folder is kept",
                  any("force-replace failed for 2024-05" in m for m in _errs)
                  and (_bk_dir(_k) / "2024-05").exists()
                  and _zip_read(_bk_zip(_k, "2024-05"))[_bk_fn(_k, "2024-05-27")] == "old-27")
            check(f"4f2 {_n} consolidate ({_tag}): the next month is still packed",
                  _bk_zip(_k, "2024-06").exists() and not (_bk_dir(_k) / "2024-06").exists())
            check(f"4f2 {_n} consolidate ({_tag}): the failed month is not reported as a consolidation failure",
                  not any("failed to consolidate" in m for m in _errs))
            if _cleanup_fails and _n == "raw":
                check("4f2 raw consolidate (cleanup_fails): the cleanup failure is logged at debug level",
                      any(lv == "debug" and "tmp zip cleanup failed for 2024-05" in m for lv, m in _c))
    for _p_dir in _bk_dir(_k).glob("*.tmp"):
        _p_dir.unlink()

    # -- 10. backfill: counters, ZIP without the file, which months get consolidated
    _bf_name, _bf_err = _BF[_n]
    _bf = getattr(_mod, _bf_name)
    with _isolated_log_env(f"bk2_bf_none_{_n}"):
        check(f"4f2 {_n} {_bf_name}: no source folder -> exact empty result",
              _bf() == {"copied": 0, "skipped": 0, _bf_err: 0})
    with _isolated_log_env(f"bk2_bf_counts_{_n}"):
        for _d in ("2024-03-01", "2024-03-02", "2024-03-03"):
            _put_src(_k, _d)
        _mk_month(_k, "2024-03", ["01", "02"])
        _r = _bf()
        check(f"4f2 {_n} {_bf_name}: 2 already backed up, 1 copied -> exact counts",
              _r == {"copied": 1, "skipped": 2, _bf_err: 0})
    with _isolated_log_env(f"bk2_bf_zip_{_n}"):
        _put_src(_k, "2024-08-05")
        _bk_dir(_k).mkdir(parents=True)
        _zip_write(_bk_zip(_k, "2024-08"), {_bk_fn(_k, "2024-08-01"): "other day"})
        _r = _bf()
        check(f"4f2 {_n} {_bf_name}: ZIP of the month exists but lacks the file -> it is copied",
              _r == {"copied": 1, "skipped": 0, _bf_err: 0}
              and _bk_fn(_k, "2024-08-05") in _zip_read(_bk_zip(_k, "2024-08")))
    with _isolated_log_env(f"bk2_bf_current_{_n}"):
        _put_src(_k, f"{_CUR}-15")
        _old = _mk_month(_k, "2024-03", ["01"])          # an old month that is still a folder
        _bf()
        check(f"4f2 {_n} {_bf_name}: only the current month touched -> no consolidation of old folders",
              _old.exists() and not _bk_zip(_k, "2024-03").exists()
              and (_bk_dir(_k) / _CUR / _bk_fn(_k, f"{_CUR}-15")).exists())
    with _isolated_log_env(f"bk2_bf_future_{_n}"):
        _put_src(_k, "2099-01-01")
        _old = _mk_month(_k, "2024-03", ["01"])          # an old month that is still a folder
        _bf()
        check(f"4f2 {_n} {_bf_name}: only a later month touched -> no consolidation of old folders",
              _old.exists() and not _bk_zip(_k, "2024-03").exists())
    with _isolated_log_env(f"bk2_bf_spy_{_n}"):
        _put_src(_k, "2024-05-01")
        _put_src(_k, "2024-06-01")
        with patch.object(_mod, _k["consolidate"], wraps=_cons) as _spy:
            _bf()
        check(f"4f2 {_n} {_bf_name}: several old months touched -> one consolidation run, not one per month",
              _spy.call_count == 1 and _bk_zip(_k, "2024-05").exists() and _bk_zip(_k, "2024-06").exists())

    # -- 11. _zip_contains
    with _isolated_log_env(f"bk2_zc_{_n}"):
        _bk_dir(_k).mkdir(parents=True)
        _zc = _mod._zip_contains
        _zp = _bk_dir(_k) / "z.zip"
        _zip_write(_zp, {"a.json": "1"})
        (_bk_dir(_k) / "notzip.zip").write_bytes(b"this is not a zip")
        check(f"4f2 {_n} _zip_contains: present -> True, absent -> False, corrupt -> False, missing ZIP -> False",
              _zc(_zp, "a.json") is True and _zc(_zp, "b.json") is False
              and _zc(_bk_dir(_k) / "notzip.zip", "a.json") is False
              and _zc(_bk_dir(_k) / "nothing.zip", "a.json") is False)

# -- 6. quality_log backup: nested target folder, yearly ZIPs in both glob orders
with _isolated_log_env("bk2_qlog_twice"):
    _put_log({"days": [{"date": "2024-01-01", "quality": "high"}]})
    _q_backup_mod.backup_quality_log()
    _put_log({"days": [{"date": "2024-01-02", "quality": "high"}]})
    _q_backup_mod.backup_quality_log()
    _snap = cfg.LOG_BACKUP_DIR / f"quality_log_{date.today().strftime('%Y-%m')}.zip"
    check("4f2 backup_quality_log: a second backup in the same month replaces the snapshot",
          json.loads(_zip_read(_snap)["quality_log.json"])["days"][0]["date"] == "2024-01-02")
with _isolated_log_env("bk2_qlog_deep"):
    _put_log({"days": []})
    _deep = cfg.LOG_BACKUP_DIR.parent / "deep" / "er" / "backup"
    with _mock.patch.object(cfg, "LOG_BACKUP_DIR", _deep):
        _q_backup_mod.backup_quality_log()
    check("4f2 backup_quality_log: a target folder with missing parents is created, snapshot written",
          (_deep / f"quality_log_{date.today().strftime('%Y-%m')}.zip").is_file())

# -- 6b. quality_log backup: data-loss guard (v1.7.4.1) ---------------------
# days[] only grows in normal operation — a drop of more than half the day
# count can only mean corruption/partial rebuild, never legitimate use.
with _isolated_log_env("bk2_qlog_shrink_guard"):
    _put_log({"days": [{"date": f"2024-01-{i:02d}", "quality": "high"} for i in range(1, 11)]})
    _q_backup_mod.backup_quality_log()
    _put_log({"days": [{"date": "2024-01-01", "quality": "high"},
                        {"date": "2024-01-02", "quality": "high"}]})
    _q_backup_mod.backup_quality_log()
    _snap = cfg.LOG_BACKUP_DIR / f"quality_log_{date.today().strftime('%Y-%m')}.zip"
    check("4f2 backup_quality_log: a drop below half the day count is refused, no crash, snapshot unchanged",
          len(json.loads(_zip_read(_snap)["quality_log.json"])["days"]) == 10)

with _isolated_log_env("bk2_qlog_shrink_ok"):
    _put_log({"days": [{"date": f"2024-01-{i:02d}", "quality": "high"} for i in range(1, 11)]})
    _q_backup_mod.backup_quality_log()
    _put_log({"days": [{"date": f"2024-01-{i:02d}", "quality": "high"} for i in range(1, 7)]})
    _q_backup_mod.backup_quality_log()
    _snap = cfg.LOG_BACKUP_DIR / f"quality_log_{date.today().strftime('%Y-%m')}.zip"
    check("4f2 backup_quality_log: a mild drop (above the 50% guard) still overwrites normally",
          len(json.loads(_zip_read(_snap)["quality_log.json"])["days"]) == 6)


def _glob_in_order(reverse):
    real = Path.glob

    def fake(self, pattern, *a, **k):
        found = sorted(real(self, pattern, *a, **k))
        return iter(found[::-1] if reverse else found)
    return fake


for _rev in (False, True):
    with _isolated_log_env(f"bk2_years_{_rev}"):
        cfg.LOG_BACKUP_DIR.mkdir(parents=True)
        for _nm in ("quality_log_0aaa-01.zip", "quality_log_2022-01.zip", "quality_log_2022-02.zip",
                    "quality_log_2023-05.zip", "quality_log_2025-03.zip", "quality_log_2031-01.zip",
                    "quality_log_zzzz-01.zip"):
            _zip_write(cfg.LOG_BACKUP_DIR / _nm, {"quality_log.json": "{}"})
        with patch.object(Path, "glob", _glob_in_order(_rev)):
            _, _c = _blogged(_q_backup_mod, _q_backup_mod._consolidate_log_years, 2025)
        _made = sorted(p.name for p in cfg.LOG_BACKUP_DIR.glob("quality_log_????.zip"))
        _order = "newest first" if _rev else "oldest first"
        check(f"4f2 yearly ZIPs ({_order}): past years are built, current/future years and bad names are not",
              _made == ["quality_log_2022.zip", "quality_log_2023.zip"])
        with zipfile.ZipFile(cfg.LOG_BACKUP_DIR / "quality_log_2022.zip") as _z:
            check(f"4f2 yearly ZIPs ({_order}): the year ZIP holds exactly that year's monthly ZIPs",
                  sorted(_z.namelist()) == ["quality_log_2022-01.zip", "quality_log_2022-02.zip"])
        check(f"4f2 yearly ZIPs ({_order}): unparseable names are logged as warnings",
              sum(1 for lv, m in _c if lv == "warning" and "could not parse year" in m) == 2)
with _isolated_log_env("bk2_years_exists"):
    cfg.LOG_BACKUP_DIR.mkdir(parents=True)
    for _nm in ("quality_log_2022-01.zip", "quality_log_2023-05.zip"):
        _zip_write(cfg.LOG_BACKUP_DIR / _nm, {"quality_log.json": "{}"})
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2022.zip", {"marker": "keep me"})
    _q_backup_mod._consolidate_log_years(2025)
    check("4f2 yearly ZIPs: an existing year ZIP is not rebuilt and does not stop the next year",
          _zip_read(cfg.LOG_BACKUP_DIR / "quality_log_2022.zip") == {"marker": "keep me"}
          and (cfg.LOG_BACKUP_DIR / "quality_log_2023.zip").exists())

# -- 7. restore_quality_log: latest first, corrupt latest falls back
with _isolated_log_env("bk2_restore_ql"):
    cfg.LOG_BACKUP_DIR.mkdir(parents=True)
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2024-05.zip",
               {"quality_log.json": json.dumps({"days": [{"date": "A"}]})})
    _zip_write(cfg.LOG_BACKUP_DIR / "quality_log_2024-06.zip",
               {"quality_log.json": json.dumps({"days": [{"date": "B"}]})})
    check("4f2 restore_quality_log: with two valid snapshots the latest one wins",
          _q_backup_mod.restore_quality_log() == {"days": [{"date": "B"}]})
    with patch.object(zipfile.ZipFile, "testzip",
                      new=lambda self: "bad" if str(self.filename).endswith("2024-06.zip") else None):
        _got = _q_backup_mod.restore_quality_log()
    check("4f2 restore_quality_log: corrupt latest snapshot -> the older valid one is used",
          _got == {"days": [{"date": "A"}]})

# -- 8. check_raw_integrity in detail
with _isolated_log_env("bk2_integrity_none"):
    check("4f2 check_raw_integrity: no quality log -> exact empty result",
          _q_backup_mod.check_raw_integrity()
          == {"missing_days": [], "no_backup": [], "total_checked": 0, "error": None})
    cfg.QUALITY_LOG_FILE.write_text("{broken", encoding="utf-8")
    _ri = _q_backup_mod.check_raw_integrity()
    check("4f2 check_raw_integrity: unreadable quality log -> empty lists, 0 checked, reason given",
          {k: v for k, v in _ri.items() if k != "error"}
          == {"missing_days": [], "no_backup": [], "total_checked": 0}
          and _ri["error"].startswith("could not read quality_log:"))
with _isolated_log_env("bk2_integrity_entries"):
    cfg.RAW_DIR.mkdir(parents=True)
    _bk_raw = cfg.RAW_BACKUP_DIR
    _bk_raw.mkdir(parents=True)
    _zip_write(_bk_raw / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-09.json": "{}"})
    (_bk_raw / "2024-09").mkdir()
    (_bk_raw / "2024-09" / "garmin_raw_2024-09-04.json").write_text("{}", encoding="utf-8")
    _put_log({"days": [
        {"write": True},                                   # no date: skipped, must not stop the loop
        {"date": "2024-08-01", "write": 1},                # truthy but not True: not counted
        {"date": "2024-08-02", "write": "yes"},            # truthy but not True: not counted
        {"date": "2024-08-03", "write": True},             # missing; ZIP exists but lacks the day
        {"date": "2024-09-04", "write": True},             # missing; folder backup exists
    ]})
    _ri, _c = _blogged(_q_backup_mod, _q_backup_mod.check_raw_integrity)
    check("4f2 check_raw_integrity: only write=True counts, undated entry skipped, loop goes on",
          _ri == {"missing_days": ["2024-08-03", "2024-09-04"], "no_backup": ["2024-08-03"],
                  "total_checked": 3, "error": None})
    check("4f2 check_raw_integrity: warning names the numbers",
          ("warning", "  check_raw_integrity: 2 missing raw files (1 without backup)") in _c)
    (cfg.RAW_DIR / "garmin_raw_2024-08-03.json").write_text("{}", encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_2024-09-04.json").write_text("{}", encoding="utf-8")
    _ri, _c = _blogged(_q_backup_mod, _q_backup_mod.check_raw_integrity)
    check("4f2 check_raw_integrity: everything present -> no missing days and no warning",
          _ri["missing_days"] == [] and _ri["no_backup"] == []
          and not any(lv == "warning" for lv, _ in _c))

# -- 9. restore_raw_days: nested target folder, loops go on after each restored day
with _isolated_log_env("bk2_restore_loops"):
    _deep_raw = cfg.RAW_DIR.parent / "deep" / "er" / "raw"
    _bk_raw = cfg.RAW_BACKUP_DIR
    _bk_raw.mkdir(parents=True)
    for _d in ("2024-08-01", "2024-08-02"):
        (_bk_raw / "2024-08").mkdir(exist_ok=True)
        (_bk_raw / "2024-08" / f"garmin_raw_{_d}.json").write_text(f"dir-{_d}", encoding="utf-8")
    _zip_write(_bk_raw / "raw_backup_2024-09.zip", {"garmin_raw_2024-09-01.json": "zip-1",
                                                    "garmin_raw_2024-09-02.json": "zip-2"})
    with _mock.patch.object(cfg, "RAW_DIR", _deep_raw):
        _deep_raw.parent.mkdir(parents=True)
        _deep_raw.mkdir()
        (_deep_raw / "garmin_raw_2024-07-01.json").write_text("current", encoding="utf-8")
        _put_log({"days": [{"date": "2024-07-01", "quality": "high"}]})
        _rr = _q_backup_mod.restore_raw_days(["2024-07-01", "2024-08-01", "2024-08-02",
                                              "2024-09-01", "2024-09-02"])
        check("4f2 restore_raw_days: skipped day, two from folders, two from the ZIP - all handled",
              _rr == {"restored": ["2024-08-01", "2024-08-02", "2024-09-01", "2024-09-02"],
                      "skipped_already_current": ["2024-07-01"], "failed": [], "errors": {}})
        check("4f2 restore_raw_days: the files carry the backed-up content, the skipped one is untouched",
              (_deep_raw / "garmin_raw_2024-08-02.json").read_text(encoding="utf-8") == "dir-2024-08-02"
              and (_deep_raw / "garmin_raw_2024-09-02.json").read_text(encoding="utf-8") == "zip-2"
              and (_deep_raw / "garmin_raw_2024-07-01.json").read_text(encoding="utf-8") == "current")
with _isolated_log_env("bk2_restore_deep"):
    _deep_raw = cfg.RAW_DIR.parent / "deep2" / "er" / "raw"
    cfg.RAW_BACKUP_DIR.mkdir(parents=True)
    _zip_write(cfg.RAW_BACKUP_DIR / "raw_backup_2024-09.zip", {"garmin_raw_2024-09-01.json": "zip-1"})
    with _mock.patch.object(cfg, "RAW_DIR", _deep_raw):
        _rr = _q_backup_mod.restore_raw_days(["2024-09-01"])
    check("4f2 restore_raw_days: a target folder with missing parents is created",
          _rr["restored"] == ["2024-09-01"] and (_deep_raw / "garmin_raw_2024-09-01.json").is_file())

# -- 10b. check_raw_backfill_needed: ZIP without the file, failing check is logged
with _isolated_log_env("bk2_needed"):
    cfg.RAW_DIR.mkdir(parents=True)
    cfg.RAW_BACKUP_DIR.mkdir(parents=True)
    (cfg.RAW_DIR / "garmin_raw_2024-08-05.json").write_text("{}", encoding="utf-8")
    _zip_write(cfg.RAW_BACKUP_DIR / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-01.json": "{}"})
    check("4f2 check_raw_backfill_needed: ZIP exists but lacks the file -> counted",
          _q_backup_mod.check_raw_backfill_needed() == 1)
    with patch.object(_q_backup_mod, "_zip_contains", side_effect=RuntimeError("probe")):
        _n_need, _c = _blogged(_q_backup_mod, _q_backup_mod.check_raw_backfill_needed)
    check("4f2 check_raw_backfill_needed: a failing check is logged per file and does not crash",
          _n_need == 0 and any(lv == "warning" and
                               "check_raw_backfill_needed: failed for garmin_raw_2024-08-05.json" in m
                               for lv, m in _c))

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
