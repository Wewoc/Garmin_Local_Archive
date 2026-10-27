#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_garmin_import.py — garmin_import (Garmin export import) and run_import

Run from the project folder:
    python tests/test_garmin_import.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import json
import shutil
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR, _isolated_log_env, _qdays  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_collector as _col5
import garmin_normalizer as _normalizer5
import garmin_quality as quality

# ══════════════════════════════════════════════════════════════════════════════
#  4k. garmin_import (Garmin export reader) and garmin_collector.run_import
#      (v1.7.4.0.2). The export is built from synthetic files, once as a folder
#      and once as a ZIP.
# ══════════════════════════════════════════════════════════════════════════════
section("4k. garmin_import, run_import — Garmin export import")
import garmin_import as _gi

_G_UDS   = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2024-05-01_2024-05-31.json"
_G_SLEEP = "DI_CONNECT/DI-Connect-Wellness/2024-05-01_2024-05-31_sleepData.json"
_G_READY = "DI_CONNECT/DI-Connect-Metrics/TrainingReadinessDTO_2024-05-01_2024-05-31.json"
_G_ACT   = "DI_CONNECT/DI-Connect-Fitness/user_summarizedActivities.json"


def _gdpr_sample():
    return {
        _G_UDS: [
            {"calendarDate": "2024-05-01", "totalSteps": 8000, "dailyStepGoal": 10000,
             "totalKilocalories": 2400, "activeKilocalories": 500, "totalDistanceMeters": 6000,
             "moderateIntensityMinutes": 10, "vigorousIntensityMinutes": 5,
             "floorsAscendedInMeters": 30, "restingHeartRate": 52,
             "currentDayRestingHeartRate": 54, "minHeartRate": 45,
             "maxHeartRate": 150,
             "allDayStress": {"aggregatorList": [{
                 "averageStressLevel": 30, "maxStressLevel": 90, "stressDuration": 1,
                 "restDuration": 2, "lowDuration": 3, "mediumDuration": 4, "highDuration": 5}]}},
            {"calendarDate": "2024-05-02", "totalSteps": 100},
            {"calendarDate": "2024-1-5", "totalSteps": 1},          # not YYYY-MM-DD
            {"calendarDate": None, "totalSteps": 1},
            {"calendarDate": 20240105, "totalSteps": 1},
        ],
        _G_SLEEP: [
            {"calendarDate": "2024-05-01", "deepSleepSeconds": 5000, "lightSleepSeconds": 10000,
             "remSleepSeconds": 6000, "awakeSleepSeconds": 900},
            {"calendarDate": "2024-05-03", "deepSleepSeconds": None,
             "lightSleepSeconds": None, "remSleepSeconds": None},
        ],
        _G_READY: [{"calendarDate": "2024-05-04", "level": "HIGH",
                    "feedbackLong": "long", "feedbackShort": "short"}],
        _G_ACT: [{"summarizedActivitiesExport": [
            {"name": "Run", "activityType": "running", "duration": 1800, "distance": 5000,
             "avgHr": 140, "maxHr": 170, "calories": 300, "aerobicTrainingEffect": 3.2,
             "anaerobicTrainingEffect": 1.1, "startTimeLocal": 1714564800000},   # milliseconds
            {"name": "Walk", "startTimeLocal": 1714564800},                        # seconds
            {"name": "NoTime"},
            {"name": "Bad", "startTimeLocal": "abc"},
        ]}],
        # files the reader must skip without stopping
        "DI_CONNECT/DI-Connect-Aggregator/UDSFile_not_a_list.json": {"a": 1},
        "DI_CONNECT/DI-Connect-Wellness/x_sleepData_not_a_list.json": {"a": 1},
        "DI_CONNECT/DI-Connect-Metrics/TrainingReadinessDTO_not_a_list.json": {"a": 1},
        "DI_CONNECT/DI-Connect-Fitness/other_summarizedActivities.json": {"a": 1},
        "DI_CONNECT/DI-Connect-Aggregator/UDSFile_broken.json": "{this is not json",
    }


def _write_export_dir(root, files):
    for rel, obj in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return Path(root)


def _write_export_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for rel, obj in files.items():
            z.writestr(rel, obj if isinstance(obj, str) else json.dumps(obj))
    return Path(path)


_M4K = _TMPDIR / "gdpr4k"
shutil.rmtree(_M4K, ignore_errors=True)
_M4K.mkdir()
_exp_dir = _write_export_dir(_M4K / "export", _gdpr_sample())
_exp_zip = _write_export_zip(_M4K / "export.zip", _gdpr_sample())

# -- load_bulk: inputs that are not an export ------------------------------------------------
check("load_bulk: path that does not exist -> no days, no crash",
      list(_gi.load_bulk(_M4K / "nothing_here")) == [])
(_M4K / "plain.txt").write_text("hello", encoding="utf-8")
check("load_bulk: a file that is neither ZIP nor folder -> no days",
      list(_gi.load_bulk(_M4K / "plain.txt")) == [])
(_M4K / "broken.zip").write_bytes(b"this is not a zip file")
check("load_bulk: a corrupt ZIP -> no days, no crash", list(_gi.load_bulk(_M4K / "broken.zip")) == [])

# -- load_bulk and parse_day on the sample export -----------------------------------------------
_days = list(_gi.load_bulk(_exp_dir))
_by = {d["date"]: d for d in _days}
check("load_bulk: days from all four file types, sorted by date",
      [d["date"] for d in _days] == ["2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04"])
check("load_bulk: invalid calendar dates and files that are not lists / not JSON are skipped",
      "2024-1-5" not in _by and len(_days) == 4)
_u = _by["2024-05-01"]["user_summary"]
check("parse_day: user summary values are carried over, meters become floors",
      _u["totalSteps"] == 8000 and _u["floorsAscended"] == 10
      and _u["dailyStepGoal"] == 10000 and _u["maxHeartRate"] == 150)
check("parse_day: resting heart rate is the value of the day, the 7-day average has its own field (v1.7.5.7)",
      _u["restingHeartRate"] == 54 and _u["lastSevenDaysAvgRestingHeartRate"] == 52)
_u_noday = _gi.parse_day({"uds": {"restingHeartRate": 52}}, "2024-05-05")["user_summary"]
check("parse_day: no day value -> resting heart rate stays empty, no fallback to the average (v1.7.5.7)",
      _u_noday["restingHeartRate"] is None and _u_noday["lastSevenDaysAvgRestingHeartRate"] == 52)
# normalize() works in place — use copies so the days compared with the ZIP below stay untouched
_day_copy = json.loads(json.dumps(_by["2024-05-01"]))
_hr_day   = _normalizer5.normalize(_day_copy, source="bulk").get("heart_rates") or {}
_hr_noday = _normalizer5.normalize(_gi.parse_day({"uds": {"restingHeartRate": 52}}, "2024-05-05"),
                                   source="bulk").get("heart_rates") or {}
check("normalize(bulk): heart_rates carries the day value; a day without it has no resting value (v1.7.5.7)",
      _hr_day.get("restingHeartRate") == 54 and "restingHeartRate" not in _hr_noday
      and "lastSevenDaysAvgRestingHeartRate" not in _hr_day)
_hr_sum = _normalizer5.summarize(_day_copy)["heartrate"]
check("summarize: heartrate.resting_bpm of an imported day is the day value (v1.7.5.7)",
      _hr_sum["resting_bpm"] == 54)
check("parse_day: stress aggregate comes from the UDS file",
      _by["2024-05-01"]["stress"]["averageStressLevel"] == 30
      and _by["2024-05-01"]["stress"]["highDuration"] == 5)
_sl = _by["2024-05-01"]["sleep"]["dailySleepDTO"]
check("parse_day: total sleep is deep + light + REM, awake time is kept separately",
      _sl["sleepTimeSeconds"] == 21000 and _sl["awakeSleepSeconds"] == 900)
check("parse_day: sleep without any stage value -> total None",
      _by["2024-05-03"]["sleep"]["dailySleepDTO"]["sleepTimeSeconds"] is None)
check("parse_day: training readiness has no score in a bulk export",
      _by["2024-05-04"]["training_readiness"]["level"] == "HIGH"
      and _by["2024-05-04"]["training_readiness"]["score"] is None)
# v1.7.6.5, P2.3 (Fund 2): the score of the export entry is read (P2.1 pinned the old state: always None).
_ready_score = _gi.parse_day({"readiness": {"calendarDate": "2024-05-04", "level": "HIGH", "score": 77}},
                             "2024-05-04")["training_readiness"]
check("parse_day: an entry WITH a score gives it (P2.3; until P2.1 it was always None)",
      _ready_score["level"] == "HIGH" and _ready_score["score"] == 77)
_ready_zero = _gi.parse_day({"readiness": {"calendarDate": "2024-05-04", "level": "LOW", "score": 0}},
                            "2024-05-04")["training_readiness"]
_ready_none = _gi.parse_day({"readiness": {"calendarDate": "2024-05-04", "level": "LOW"}},
                            "2024-05-04")["training_readiness"]
check("parse_day: a score of 0 stays 0, an entry without a score gives None (as before)",
      _ready_zero["score"] == 0 and _ready_zero["score"] is not None and _ready_none["score"] is None
      and _ready_none["level"] == "LOW")
_acts = _by["2024-05-01"]["activities"]
check("load_bulk: activities with start time in ms and in s land on the same day",
      [a["activityName"] for a in _acts] == ["Run", "Walk"])
check("parse_day: activity fields are renamed to the API names",
      _acts[0]["averageHR"] == 140 and _acts[0]["maxHR"] == 170
      and _acts[0]["aerobicTrainingEffect"] == 3.2)
check("load_bulk: activities without a usable start time are dropped",
      all(a["activityName"] in ("Run", "Walk") for a in _acts))
check("load_bulk: a day without sleep or stress has no such keys",
      "sleep" not in _by["2024-05-02"] and "stress" not in _by["2024-05-02"])
check("load_bulk: a ZIP export gives exactly the same days as the folder",
      list(_gi.load_bulk(_exp_zip)) == _days)
check("parse_day: empty entries -> only the date", _gi.parse_day({}, "2024-05-01") == {"date": "2024-05-01"})

# -- helpers -----------------------------------------------------------------------------------------
check("_timestamp_to_date: None and unusable values -> None",
      _gi._timestamp_to_date(None) is None and _gi._timestamp_to_date("abc") is None)
check("_timestamp_to_date: seconds and milliseconds give the same day",
      _gi._timestamp_to_date(1714564800) == "2024-05-01"
      and _gi._timestamp_to_date(1714564800000) == "2024-05-01")
check("_valid_date: only YYYY-MM-DD strings that are real dates",
      _gi._valid_date("2024-05-01") and not _gi._valid_date("2024-13-01")
      and not _gi._valid_date("2024-5-1") and not _gi._valid_date(None)
      and not _gi._valid_date(20240501))
check("_meters_to_floors: None, text and numbers",
      _gi._meters_to_floors(None) is None and _gi._meters_to_floors("x") is None
      and _gi._meters_to_floors(31) == 10)
check("_total_sleep: no stage -> None, partial stages are summed",
      _gi._total_sleep({}) is None and _gi._total_sleep({"deepSleepSeconds": 100}) == 100)

# Fix 2 (v1.7.4.6): one malformed entry is skipped with a warning, the rest survives
_bad_exp = _write_export_dir(_M4K / "export_bad_entry", {_G_UDS: [
    {"calendarDate": "2024-05-01", "totalSteps": 1}, "garbage", {"calendarDate": "2024-05-02", "totalSteps": 2}]})
_real_gi_log = _gi.log
_bad_warnings = []
_gi.log = type("_L", (), {"warning": staticmethod(lambda m, *a, **k: _bad_warnings.append(m)),
                          "error": staticmethod(lambda m, *a, **k: None),
                          "info": staticmethod(lambda m, *a, **k: None)})()
try:
    _res_bad = list(_gi.load_bulk(_bad_exp))
finally:
    _gi.log = _real_gi_log
check("load_bulk: a malformed entry is skipped, the valid days before and after it survive",
      {d["date"] for d in _res_bad} == {"2024-05-01", "2024-05-02"})
check("load_bulk: the malformed entry is logged as a warning naming the file",
      any("malformed entry" in m and "garbage" in m for m in _bad_warnings))

# -- run_import ---------------------------------------------------------------------------------------------
_ev_calls = []


def _progress(i, total, d):
    _ev_calls.append((i, total, d))


with _isolated_log_env("gdpr_import") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _r = _col5.run_import(_exp_dir, progress_callback=_progress)
    check("run_import: days with data are imported, days without enough data count as failed",
          _r == {"ok": 2, "skipped": 0, "failed": 2})
    check("run_import: progress is reported once per day, total unknown",
          _ev_calls == [(1, None, "2024-05-01"), (2, None, "2024-05-02"),
                        (3, None, "2024-05-03"), (4, None, "2024-05-04")])
    _q = _qdays()
    check("run_import: imported days are written and logged as standard, source bulk",
          (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").exists()
          and (cfg.SUMMARY_DIR / "garmin_2024-05-02.json").exists()
          and all(_q[d]["quality"] == "standard" and _q[d]["source"] == "bulk"
                  and _q[d]["write"] is True for d in ("2024-05-01", "2024-05-02")))
    check("run_import: days without enough data are logged as failed and not written",
          all(_q[d]["quality"] == "failed" and _q[d]["write"] is False
              for d in ("2024-05-03", "2024-05-04"))
          and not (cfg.RAW_DIR / "garmin_raw_2024-05-03.json").exists())
    check("run_import: first_day is set to the earliest imported day",
          quality._load_quality_log()["first_day"] == "2024-05-01")

with _isolated_log_env("gdpr_skip") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    (cfg.RAW_DIR / "garmin_raw_2024-05-02.json").write_text('{"keep": "me"}', encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2023-01-01", "devices": [], "days": [
        {"date": "2024-05-02", "quality": "standard", "source": "api", "write": True}]}), encoding="utf-8")
    _ev_calls.clear()
    _r = _col5.run_import(_exp_dir, progress_callback=_progress)
    check("run_import: a day that is already standard/high from the API is skipped",
          _r["skipped"] == 1 and _r["ok"] == 1
          and (cfg.RAW_DIR / "garmin_raw_2024-05-02.json").read_text(encoding="utf-8") == '{"keep": "me"}')
    check("run_import: a skipped day is still reported to the progress callback",
          (2, None, "2024-05-02") in _ev_calls)
    check("run_import: an earlier stored first_day is not moved to a later date",
          quality._load_quality_log()["first_day"] == "2023-01-01")

with _isolated_log_env("gdpr_firstday") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-20", "devices": [], "days": []}),
                                    encoding="utf-8")
    _col5.run_import(_exp_dir)
    check("run_import: first_day moves back when the export reaches further into the past",
          quality._load_quality_log()["first_day"] == "2024-05-01")

# -- run_import: days that cannot be imported ----------------------------------------------------------------
with _isolated_log_env("gdpr_bad") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _stream = iter([
        {},                                                        # no date at all
        {"date": 99999},                                           # validator critical
        {"date": "2024-06-01", "user_summary": {"totalSteps": 5}},  # fine
        {"date": "2024-06-02", "user_summary": {"totalSteps": 6}},  # the summary step will fail
        {"date": "2024-06-03", "user_summary": {"totalSteps": 7}},  # fine
    ])
    _real_summarize = _normalizer5.summarize

    def _summarize_fails_on_02(normalized):
        if normalized.get("date") == "2024-06-02":
            raise RuntimeError("summary exploded")
        return _real_summarize(normalized)

    with patch.object(_gi, "load_bulk", return_value=_stream), \
         patch.object(_normalizer5, "summarize", side_effect=_summarize_fails_on_02):
        _r = _col5.run_import("ignored")
    check("run_import: a day without date, a critical day and an error count as failed, the rest goes on",
          _r == {"ok": 2, "skipped": 0, "failed": 3})
    check("run_import: the failing day leaves no quality log entry",
          set(_qdays()) == {"2024-06-01", "2024-06-03"})

    # Fix 3 (v1.7.4.6): the date is validated before anything is written
    with patch.object(_gi, "load_bulk", return_value=iter(
            [{"date": "2024-13-45", "user_summary": {"totalSteps": 10}}])):
        _r = _col5.run_import("ignored")
    check("run_import: an invalid date counts as failed and nothing is written for it",
          _r["failed"] == 1 and _r["ok"] == 0
          and not (cfg.RAW_DIR / "garmin_raw_2024-13-45.json").exists())

# -- Fix 1 (v1.7.4.6): an existing day not worse than the export stays protected -------------------------------
with _isolated_log_env("gdpr_protect") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    (cfg.RAW_BACKUP_DIR / "2024-05").mkdir(parents=True)
    _rich = {"date": "2024-05-01", "heart_rates": {"restingHeartRate": 50,
             "heartRateValues": [[1740787200000, 58], [1740787260000, 60]]}}
    (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").write_text(json.dumps(_rich), encoding="utf-8")
    (cfg.RAW_BACKUP_DIR / "2024-05" / "garmin_raw_2024-05-01.json").write_text(json.dumps(_rich), encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "2024-05-01", "quality": "high", "source": "legacy", "write": True}]}), encoding="utf-8")
    _r = _col5.run_import(_exp_dir)
    _after = json.loads((cfg.RAW_DIR / "garmin_raw_2024-05-01.json").read_text(encoding="utf-8"))
    check("run_import: an existing 'high' day from a non-API source ('legacy') is protected — "
          "the export is strictly worse (aggregate-only) and is skipped, not written",
          _r["skipped"] >= 1
          and "heartRateValues" in _after.get("heart_rates", {})
          and _qdays()["2024-05-01"]["quality"] == "high" and _qdays()["2024-05-01"]["source"] == "legacy")
    # v1.7.5.6: importing the other days consolidates the completed month, so the protected
    # day's backup copy may now sit in the monthly ZIP instead of the month folder — its
    # content must be untouched either way.
    import zipfile as _zipfile_gi
    _gi_bk_name = "garmin_raw_2024-05-01.json"
    _gi_bk_file = cfg.RAW_BACKUP_DIR / "2024-05" / _gi_bk_name
    if _gi_bk_file.exists():
        _gi_bk_text = _gi_bk_file.read_text(encoding="utf-8")
    else:
        with _zipfile_gi.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2024-05.zip") as _gi_zf:
            _gi_bk_text = _gi_zf.read(_gi_bk_name).decode("utf-8")
    check("run_import: the backup copy of the protected day is untouched too (month folder or monthly ZIP)",
          "heartRateValues" in json.loads(_gi_bk_text).get("heart_rates", {}))

# The maintainer's precision of the architecture decision: EQUAL quality from a non-API
# source must also stay protected, not just a strictly-better existing day.
with _isolated_log_env("gdpr_protect_equal") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    _existing_standard = {"date": "2024-05-01", "user_summary": {"totalSteps": 999, "marker": "existing-legacy"}}
    (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").write_text(json.dumps(_existing_standard), encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        # same label ("standard") as the export day for 2024-05-01 will assess to,
        # but from a non-API source — must stay protected per the maintainer's decision.
        {"date": "2024-05-01", "quality": "standard", "source": "legacy", "write": True}]}), encoding="utf-8")
    _r = _col5.run_import(_exp_dir)
    _after = json.loads((cfg.RAW_DIR / "garmin_raw_2024-05-01.json").read_text(encoding="utf-8"))
    check("run_import: an existing day of EQUAL quality from a non-API source ('legacy') "
          "is also protected — not just a strictly better one",
          _r["skipped"] >= 1
          and _after.get("user_summary", {}).get("marker") == "existing-legacy"
          and _qdays()["2024-05-01"]["source"] == "legacy")

# -- Fix 4 (v1.7.4.6): the stop event is honoured, checked once per day --------------------------------------
with _isolated_log_env("gdpr_stop") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ev = threading.Event()
    _ev.set()
    _r = _col5.run_import(_exp_dir, stop_event=_ev)
    check("run_import: the stop event is registered with the collector",
          _col5._stop_event is _ev)
    _col5.set_stop_event(None)
    check("run_import: a stop event that is already set stops the import before the first day",
          _r["ok"] == 0 and _r["skipped"] == 0 and _r["failed"] == 0
          and not (cfg.RAW_DIR / "garmin_raw_2024-05-02.json").exists())

# ══════════════════════════════════════════════════════════════════════════════
#  Fix 3 (v1.6.5.8) — run_import() quality-failed counting
# ══════════════════════════════════════════════════════════════════════════════
import garmin_collector as _f3_collector
import garmin_import as _f3_importer
from unittest import mock as _mock

def _f3_fake_load_bulk(path):
    yield {"date": "2026-05-01", "user_summary": {"totalSteps": 8000}, "stats": {"totalSteps": 8000}}
    yield {"date": "2026-05-02"}  # no usable data at all → quality "failed"

with _mock.patch.object(_f3_importer, "load_bulk", _f3_fake_load_bulk):
    _f3_result = _f3_collector.run_import("/fake/path/does/not/matter")

check("f3: standard-quality day counted as ok",           _f3_result["ok"] == 1)
check("f3: quality-failed day counted as failed, not ok", _f3_result["failed"] == 1)
check("f3: skipped stays 0",                              _f3_result["skipped"] == 0)

_f3_qlog  = quality._load_quality_log()
_f3_entry = next((e for e in _f3_qlog["days"] if e.get("date") == "2026-05-02"), None)
check("f3: quality_log entry for failed day exists",  _f3_entry is not None)
check("f3: quality_log entry quality=failed",         _f3_entry.get("quality") == "failed")
check("f3: quality_log entry write=False",            _f3_entry.get("write") is False)

# ══════════════════════════════════════════════════════════════════════════════
#  4k2. garmin_import — file filters, several files and entries, date and
#       timestamp edges, folder/ZIP detection (v1.7.4.0.3).
#       Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4k2. garmin_import — filters, loops, edges")


class _GLog:
    """Stands in for _gi.log and records (level, message)."""
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


def _g_logged(fn, *args, **kwargs):
    real, rec = _gi.log, _GLog()
    _gi.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        _gi.log = real


def _g_days(names, data):
    """Runs _process_entries over a fixed file list; reader serves `data` by name."""
    return {d["date"]: d for d in _gi._process_entries(list(names), reader=lambda n: data.get(n))}


# per type: (genuine name, key in the day, builder of a list for one date)
_TS_2030 = 1893456000                                            # 2030-01-01 00:00 UTC, seconds
_TS_2024 = 1717243200                                            # 2024-06-01 12:00 UTC, seconds


def _uds(d):
    return [{"calendarDate": d, "totalSteps": 1}]


def _sleep(d):
    return [{"calendarDate": d, "deepSleepSeconds": 1}]


def _ready(d):
    return [{"calendarDate": d, "level": "HIGH"}]


def _acts(ts):
    return [{"summarizedActivitiesExport": [{"name": "A", "startTimeLocal": ts}]}]


_TYPES = [
    ("uds", _G_UDS, "uds", lambda d: _uds(d), "DI_CONNECT/DI-Connect-Aggregator/other.json", "elsewhere/UDSFile_x.json"),
    ("sleep", _G_SLEEP, "sleep", lambda d: _sleep(d), "DI_CONNECT/DI-Connect-Wellness/other.json", "elsewhere/x_sleepData.json"),
    ("readiness", _G_READY, "readiness", lambda d: _ready(d),
     "DI_CONNECT/DI-Connect-Metrics/other.json", "elsewhere/TrainingReadinessDTO_x.json"),
    ("activities", _G_ACT, "activities", None,
     "DI_CONNECT/DI-Connect-Fitness/other.json", "elsewhere/summarizedActivities.json"),
]

# -- file filters: both parts of the name must match, and it must be a .json ----------------------------------
for _t, _genuine, _key, _mk, _prefix_only, _keyword_only in _TYPES:
    _good = _acts(_TS_2024) if _t == "activities" else _mk("2024-06-01")
    _decoy = _acts(_TS_2030) if _t == "activities" else _mk("2030-01-01")
    _kw = {"uds": "UDSFile_", "sleep": "sleepData", "readiness": "TrainingReadinessDTO",
           "activities": "summarizedActivities"}[_t]
    _pref = _genuine.rsplit("/", 1)[0] + "/"
    _names = [_prefix_only, _keyword_only, "random.json", _pref + _kw + "_x.txt", _genuine]
    _data = {n: _decoy for n in _names}
    _data[_genuine] = _good
    _res = _g_days(_names, _data)
    check(f"4k2 filter ({_t}): only the file with folder AND keyword AND .json is read",
          list(_res) == ["2024-06-01"])

# -- several files and entries: a bad one must not stop the next ---------------------------------------------------
for _t, _genuine, _key, _mk, _p, _k in _TYPES:
    _gen2 = _genuine.replace(".json", "_b.json") if _t != "activities" else _genuine.replace(".json", "_b.json")
    _good = _acts(_TS_2024) if _t == "activities" else _mk("2024-06-01")
    _res = _g_days([_genuine, _gen2], {_genuine: {"not": "a list"}, _gen2: _good})
    check(f"4k2 loop ({_t}): a file whose content is not a list does not stop the next file",
          list(_res) == ["2024-06-01"])
    if _t == "activities":
        _bad_first = [{"summarizedActivitiesExport": [
            {"name": "bad", "startTimeLocal": None}, {"name": "worse", "startTimeLocal": "x"},
            {"name": "ok", "startTimeLocal": _TS_2024}]}]
        _res = _g_days([_genuine], {_genuine: _bad_first})
        check("4k2 loop (activities): activities without a usable start time do not stop the next ones",
              [a["activityName"] for a in _res["2024-06-01"]["activities"]] == ["ok"])
    else:
        _entries = [dict(_mk("bad-date")[0]), dict(_mk("2024-06-02")[0])]
        _res = _g_days([_genuine], {_genuine: _entries})
        check(f"4k2 loop ({_t}): an entry with an invalid date does not stop the next entry",
              list(_res) == ["2024-06-02"])

# -- the seam of _process_entries (v1.7.6.5, P2.2a-prep): collect by name, then build the days -----------------------
_s_names = [_G_UDS, _G_SLEEP, _G_READY, _G_ACT]
_s_data = {_G_UDS: _uds("2024-06-01"), _G_SLEEP: _sleep("2024-06-02"), _G_READY: _ready("2024-06-01"),
           _G_ACT: _acts(_TS_2024)}
_s_by_date = _gi._collect_entries(list(_s_names), reader=lambda n: _s_data.get(n))
check("4k2 seam: _collect_entries indexes the entries by date, kind by file name, activities as a list",
      sorted(_s_by_date) == ["2024-06-01", "2024-06-02"]
      and set(_s_by_date["2024-06-01"]) == {"uds", "readiness", "activities"}
      and list(_s_by_date["2024-06-02"]) == ["sleep"]
      and len(_s_by_date["2024-06-01"]["activities"]) == 1)
check("4k2 seam: _days_from_entries gives the days sorted, with the entries of the day on request",
      [d["date"] for d in _gi._days_from_entries(_s_by_date)] == ["2024-06-01", "2024-06-02"]
      and [e for _, e in _gi._days_from_entries(_s_by_date, True)] == [_s_by_date["2024-06-01"], _s_by_date["2024-06-02"]])
check("4k2 seam: _process_entries is exactly the two parts one after the other",
      list(_gi._process_entries(list(_s_names), reader=lambda n: _s_data.get(n), with_entries=True))
      == list(_gi._days_from_entries(_s_by_date, True)))
_s_res, _s_log = _g_logged(lambda: list(_gi._process_entries(list(_s_names), reader=lambda n: _s_data.get(n))))
check("4k2 seam: the 'days found' line is still written, once, before the first day",
      [m for lv, m in _s_log if "days found in export" in m] == ["  load_bulk: 2 days found in export"])

# -- _index_file (v1.7.6.5, P2.4a): the entries of ONE file, the part that reading by name and by content share ---------
_i_same = True
for _k, _n in (("uds", _G_UDS), ("sleep", _G_SLEEP), ("readiness", _G_READY), ("activities", _G_ACT)):
    _i_by = {}
    _gi._index_file(_i_by, _k, "label", _s_data[_n])
    _i_same = _i_same and _i_by == _gi._collect_entries([_n], reader=lambda n: _s_data.get(n)) and _i_by != {}
check("4k2 _index_file: for each kind one file gives what _collect_entries gives for that file",
      _i_same)
_i_by = {}
for _bad in (None, {"calendarDate": "2024-06-01"}, "text", 5):
    _gi._index_file(_i_by, "uds", "label", _bad)
check("4k2 _index_file: a file whose content is not a list adds nothing and raises nothing", _i_by == {})
_i_res, _i_log = _g_logged(lambda: _gi._index_file({}, "sleep", "my-label", ["x"]))
check("4k2 _index_file: the warning for an entry that is no object names the label it was given",
      any(lv == "warning" and "my-label" in m and "malformed entry" in m for lv, m in _i_log))

# -- days_from_originals (v1.7.6.5, P2.4b): the kind from the content, files that carry no path ------------------------
def _r_uds(d, steps=1):
    return {"calendarDate": d, "totalSteps": steps, "uuid": "u-" + d}


def _r_sleep(d, deep=1):
    return {"calendarDate": d, "sleepStartTimestampGMT": "x", "deepSleepSeconds": deep}


def _r_ready(d, level, ts):
    return {"calendarDate": d, "level": level, "acwrFactorPercent": 1, "timestamp": ts}


def _r_act(ts, name):
    return [{"summarizedActivitiesExport": [{"name": name, "startTimeLocal": ts}]}]


_o_data = {_G_UDS: [_r_uds("2024-06-01"), _r_uds("2024-06-02", 5)], _G_SLEEP: [_r_sleep("2024-06-01")],
           _G_READY: [_r_ready("2024-06-01", "LOW", "2024-06-01T16:00:00.0"), _r_ready("2024-06-01", "HIGH", "2024-06-01T05:00:00.0")],
           _G_ACT: _r_act(_TS_2024, "A")}
_o_by_name = list(_gi._days_from_entries(_gi._collect_entries(list(_o_data), reader=lambda n: _o_data.get(n)), True))
check("4k2 days_from_originals: the same files, kind from the content, give the days and entries the reading by name gives",
      list(_gi.days_from_originals(list(_o_data.items()))) == _o_by_name and len(_o_by_name) == 2)
_o_un = []
_o_days = list(_gi.days_from_originals([("junk", [{"x": 1}]), ("text", "x"), ("u", [_r_uds("2024-06-03")])], on_unrecognised=_o_un.append))
check("4k2 days_from_originals: a file of no recognised kind is reported by its label and skipped, the others go on",
      _o_un == ["junk", "text"] and [d["date"] for d, _ in _o_days] == ["2024-06-03"])
check("4k2 days_from_originals: an unrecognised file without a callback is skipped as well; the input may be a generator",
      [d["date"] for d, _ in _gi.days_from_originals(x for x in [("junk", [{"x": 1}]), ("u", [_r_uds("2024-06-03")])])] == ["2024-06-03"])
_o_early, _o_late = [_r_ready("2024-06-01", "MODERATE", "2024-06-01T05:17:24.0")], [_r_ready("2024-06-01", "LOW", "2024-06-01T16:02:34.0")]
check("4k2 days_from_originals: readiness of two files is chosen by the timestamp, in either order of the files",
      {e["readiness"]["level"] for o in ([("a", _o_early), ("b", _o_late)], [("a", _o_late), ("b", _o_early)])
       for _, e in _gi.days_from_originals(o)} == {"LOW"})
_o_conf = []
_o_two = list(_gi.days_from_originals([("a", [_r_uds("2024-06-01", 1)]), ("b", [_r_uds("2024-06-01", 2)])], on_conflict=lambda k, d: _o_conf.append((k, d))))
check("4k2 days_from_originals: two different UDS entries of one date call on_conflict once, the one given later wins",
      _o_conf == [("uds", "2024-06-01")] and _o_two[0][1]["uds"]["totalSteps"] == 2)
_o_conf.clear()
list(_gi.days_from_originals([("a", [_r_sleep("2024-06-01", 1)]), ("b", [_r_sleep("2024-06-01", 2)])], on_conflict=lambda k, d: _o_conf.append((k, d))))
check("4k2 days_from_originals: the same for sleep", _o_conf == [("sleep", "2024-06-01")])
_o_conf.clear()
list(_gi.days_from_originals([("a", [_r_uds("2024-06-01", 1)]), ("b", [_r_uds("2024-06-01", 1)]),
                              ("c", _o_early), ("d", _o_late)], on_conflict=lambda k, d: _o_conf.append((k, d))))
check("4k2 days_from_originals: the same entry twice and different readiness entries are no conflict (the timestamp decides)",
      _o_conf == [])
_o_acts = lambda order: [n["name"] for _, e in _gi.days_from_originals(order) for n in e["activities"]]
check("4k2 days_from_originals: the activities of a day stand in the order the files were given (the caller decides)",
      _o_acts([("a", _r_act(_TS_2024, "A")), ("b", _r_act(_TS_2024, "B"))]) == ["A", "B"]
      and _o_acts([("b", _r_act(_TS_2024, "B")), ("a", _r_act(_TS_2024, "A"))]) == ["B", "A"])
_i_conf = []
_gi._index_file({}, "uds", "x", [_r_uds("2024-06-01")], None)
_by_c = {}
_gi._index_file(_by_c, "uds", "x", [_r_uds("2024-06-01", 1)], lambda k, d: _i_conf.append(d))
_gi._index_file(_by_c, "uds", "y", [_r_uds("2024-06-01", 2)])
check("4k2 _index_file: without on_conflict the later entry replaces the earlier without any call (the import by name)",
      _i_conf == [] and _by_c["2024-06-01"]["uds"]["totalSteps"] == 2)

# -- detect_kind (v1.7.6.5, P2.2): the kind of a file from its content, for originals that carry no path -------------
_dk_uds = {"calendarDate": "2024-06-01", "totalSteps": 1, "uuid": "u"}
_dk_sleep_a = {"calendarDate": "2024-06-01", "sleepStartTimestampGMT": "x"}
_dk_sleep_b = {"calendarDate": "2024-06-01", "deepSleepSeconds": 1}
_dk_ready_a = {"calendarDate": "2024-06-01", "acwrFactorPercent": 1}
_dk_ready_b = {"calendarDate": "2024-06-01", "recoveryTimeFactorPercent": 1}
_dk_act = {"summarizedActivitiesExport": [{"name": "A"}]}
check("4k2 detect_kind: each kind is found by its key rule (sleep and readiness by either key)",
      _gi.detect_kind([_dk_uds]) == "uds" and _gi.detect_kind([_dk_act]) == "activities"
      and _gi.detect_kind([_dk_sleep_a]) == "sleep" and _gi.detect_kind([_dk_sleep_b]) == "sleep"
      and _gi.detect_kind([_dk_ready_a]) == "readiness" and _gi.detect_kind([_dk_ready_b]) == "readiness")
check("4k2 detect_kind: the daily aggregate needs totalSteps AND uuid, one of them alone is not recognised",
      _gi.detect_kind([{"totalSteps": 1}]) is None and _gi.detect_kind([{"uuid": "u"}]) is None)
check("4k2 detect_kind: entries of two kinds in one list, or two rules on one entry -> not recognised",
      _gi.detect_kind([_dk_uds, _dk_sleep_a]) is None
      and _gi.detect_kind([{"deepSleepSeconds": 1, "acwrFactorPercent": 1}]) is None
      and _gi.detect_kind([_dk_ready_a, _dk_act]) is None)
check("4k2 detect_kind: empty list, no rule, a dict, None, text and a list of non-objects -> not recognised",
      _gi.detect_kind([]) is None and _gi.detect_kind([{"calendarDate": "2024-06-01"}]) is None
      and _gi.detect_kind({"totalSteps": 1, "uuid": "u"}) is None and _gi.detect_kind(None) is None
      and _gi.detect_kind("totalSteps") is None and _gi.detect_kind(["x", 1, None]) is None)
check("4k2 detect_kind: an entry that is no object does not hide the kind of the others",
      _gi.detect_kind(["x", None, _dk_uds, 5]) == "uds")
check("4k2 detect_kind: the kind comes from the keys, an entry without a date or with a bad date still counts",
      _gi.detect_kind([{"totalSteps": 1, "uuid": "u"}]) == "uds"
      and _gi.detect_kind([dict(_dk_ready_a, calendarDate="bad")]) == "readiness")
_dk_in = [dict(_dk_uds), dict(_dk_sleep_a)]
_dk_before = json.dumps(_dk_in, sort_keys=True)
_dk_res, _dk_log = _g_logged(lambda: _gi.detect_kind(_dk_in))
check("4k2 detect_kind: a pure function — the input is not changed and nothing is logged, also when not recognised",
      _dk_res is None and json.dumps(_dk_in, sort_keys=True) == _dk_before and _dk_log == [])

# -- readiness: choice between entries of one date, independent of the reading order (v1.7.6.5, P2.2a) -----------------
import datetime as _dtm
_G_READY_B = _G_READY.replace(".json", "_b.json")


def _rdy(ts, level="HIGH"):
    e = {"calendarDate": "2024-06-01", "level": level, "acwrFactorPercent": 1}
    if ts is not None:
        e["timestamp"] = ts
    return e


def _won(files):
    """Level of the readiness of 2024-06-01 after reading [(file name, entries), ...] in this order."""
    return _g_days([n for n, _ in files], dict(files))["2024-06-01"]["training_readiness"]["level"]


_r_early = _rdy("2024-06-01T05:17:24.0", "MODERATE")
_r_mid = _rdy("2024-06-01T06:36:07.0", "PRIME")
_r_late = _rdy("2024-06-01T16:02:34.0", "LOW")
check("4k2 readiness: the entry with the latest timestamp wins, wherever it stands in the list or in the files",
      {_won([(_G_READY, [_r_early, _r_mid, _r_late])]), _won([(_G_READY, [_r_late, _r_mid, _r_early])]),
       _won([(_G_READY, [_r_early]), (_G_READY_B, [_r_late])]), _won([(_G_READY, [_r_late]), (_G_READY_B, [_r_early])]),
       _won([(_G_READY_B, [_r_early]), (_G_READY, [_r_late])])} == {"LOW"})
check("4k2 readiness: a day with one entry is unchanged",
      _won([(_G_READY, [_r_early])]) == "MODERATE")
check("4k2 readiness: an entry with a timestamp beats one without, in both orders",
      _won([(_G_READY, [_rdy(None, "NOTS")]), (_G_READY_B, [_r_early])]) == "MODERATE"
      and _won([(_G_READY, [_r_early]), (_G_READY_B, [_rdy(None, "NOTS")])]) == "MODERATE")
check("4k2 readiness: a timestamp that is not a readable text counts as none",
      all(_won([(_G_READY, [_rdy(bad, "BAD")]), (_G_READY_B, [_r_early])]) == "MODERATE"
          and _won([(_G_READY, [_r_early]), (_G_READY_B, [_rdy(bad, "BAD")])]) == "MODERATE"
          for bad in ("bad", "", 5, "2024-13-45T99:99:99")))
_r_a = _rdy("2024-06-01T05:17:24.0", "AAA")
_r_b = _rdy("2024-06-01T05:17:24.0", "BBB")
check("4k2 readiness: the same time and different content -> the smaller canonical text, in both orders",
      {_won([(_G_READY, [_r_a, _r_b])]), _won([(_G_READY, [_r_b, _r_a])]),
       _won([(_G_READY, [_r_a]), (_G_READY_B, [_r_b])]), _won([(_G_READY, [_r_b]), (_G_READY_B, [_r_a])])} == {"AAA"}
      and {_won([(_G_READY, [_rdy(None, "AAA"), _rdy(None, "BBB")])]),
           _won([(_G_READY, [_rdy(None, "BBB"), _rdy(None, "AAA")])])} == {"AAA"})
_dup = _g_days([_G_READY, _G_READY_B], {_G_READY: [_r_late], _G_READY_B: [dict(_r_late)]})
check("4k2 readiness: the same entry in two files gives one day with that entry",
      list(_dup) == ["2024-06-01"] and _dup["2024-06-01"]["training_readiness"]["level"] == "LOW")
check("4k2 _entry_time: the Garmin format with '.0', a space instead of T, a fraction and a zone are read",
      _gi._entry_time({"timestamp": "2025-03-05T05:17:24.0"}) == _dtm.datetime(2025, 3, 5, 5, 17, 24)
      and _gi._entry_time({"timestamp": "2025-03-05 05:17:24"}) == _dtm.datetime(2025, 3, 5, 5, 17, 24)
      and _gi._entry_time({"timestamp": "2025-03-05T05:17:24.123Z"}) == _dtm.datetime(2025, 3, 5, 5, 17, 24))
check("4k2 _entry_time: missing, not a text and not readable -> None",
      _gi._entry_time({}) is None and _gi._entry_time({"timestamp": None}) is None
      and _gi._entry_time({"timestamp": 1717243200}) is None and _gi._entry_time({"timestamp": "x"}) is None)
_ist = _gi._collect_entries([_G_UDS, _G_UDS.replace(".json", "_b.json"), _G_SLEEP, _G_SLEEP.replace(".json", "_b.json")], reader=lambda n: {
    _G_UDS: [{"calendarDate": "2024-06-01", "totalSteps": 1}],
    _G_UDS.replace(".json", "_b.json"): [{"calendarDate": "2024-06-01", "totalSteps": 2}],
    _G_SLEEP: [{"calendarDate": "2024-06-01", "deepSleepSeconds": 1}],
    _G_SLEEP.replace(".json", "_b.json"): [{"calendarDate": "2024-06-01", "deepSleepSeconds": 2}]}.get(n))
check("4k2 Ist-Stand (v1.7.6.5): UDS and sleep keep 'the last one read wins' (the new rule is for readiness)",
      _ist["2024-06-01"]["uds"]["totalSteps"] == 2 and _ist["2024-06-01"]["sleep"]["deepSleepSeconds"] == 2)

# -- _valid_date, _timestamp_to_date, _meters_to_floors ---------------------------------------------------------------
check("4k2 _valid_date: only YYYY-MM-DD of exactly 10 characters (3.11 would accept 20240501)",
      _gi._valid_date("2024-05-01") is True and _gi._valid_date("20240501") is False
      and _gi._valid_date("2024-05-011") is False and _gi._valid_date("2024-13-01") is False
      and _gi._valid_date(20240501) is False and _gi._valid_date(None) is False)
check("4k2 _timestamp_to_date: more than 1e10 is milliseconds, exactly 1e10 and below is seconds",
      _gi._timestamp_to_date(10000000001) == "1970-04-26"
      and _gi._timestamp_to_date(10000000000) == "2286-11-20"
      and _gi._timestamp_to_date(9999999999) == "2286-11-20")
check("4k2 _timestamp_to_date: ordinary values in ms and s, zero, text digits",
      _gi._timestamp_to_date(1714564800000) == "2024-05-01"
      and _gi._timestamp_to_date(1714564800) == "2024-05-01"
      and _gi._timestamp_to_date(0) == "1970-01-01" and _gi._timestamp_to_date("1714564800") == "2024-05-01")
check("4k2 _timestamp_to_date: None, junk and out-of-range values -> None",
      _gi._timestamp_to_date(None) is None and _gi._timestamp_to_date("abc") is None
      and _gi._timestamp_to_date(10 ** 30) is None)
check("4k2 _meters_to_floors: rounded, not floored (11 m -> 4)",
      _gi._meters_to_floors(11) == 4 and _gi._meters_to_floors(10) == 3
      and _gi._meters_to_floors(30) == 10 and _gi._meters_to_floors(1.4) == 0)
check("4k2 _meters_to_floors: None and junk -> None",
      _gi._meters_to_floors(None) is None and _gi._meters_to_floors("x") is None)

# -- parse_day: first aggregate wins ------------------------------------------------------------------------------------
_pd = _gi.parse_day({"uds": {"allDayStress": {"aggregatorList": [
    {"averageStressLevel": 11}, {"averageStressLevel": 99}]}}}, "2024-06-01")
check("4k2 parse_day: with several stress aggregates the first one is used",
      _pd["stress"]["averageStressLevel"] == 11)

# -- load_bulk: how a path is recognised ---------------------------------------------------------------------------------
_zzz = _write_export_dir(_M4K / "export.zzz", _gdpr_sample())
check("4k2 load_bulk: a folder is read as a folder whatever its name ends with",
      list(_gi.load_bulk(_zzz)) == _days)
_upper = _write_export_zip(_M4K / "EXPORT.ZIP", _gdpr_sample())
check("4k2 load_bulk: .ZIP in capitals is read as a ZIP", list(_gi.load_bulk(_upper)) == _days)
_res, _c = _g_logged(lambda: list(_gi.load_bulk(_M4K / "broken.zip")))
check("4k2 load_bulk: a file that is no ZIP is reported as a bad ZIP, not as an unexpected error",
      _res == [] and any(lv == "error" and "bad ZIP file" in m for lv, m in _c)
      and not any("unexpected error" in m for _, m in _c))

# -- load_bulk_with_entries (v1.7.6.1): the entries of every day and a hook for every file that is read -----------------
section("4k3. garmin_import — load_bulk_with_entries, read hook")
import hashlib as _hl4k3

_pairs_dir = list(_gi.load_bulk_with_entries(_exp_dir))
_pairs_zip = list(_gi.load_bulk_with_entries(_exp_zip))
check("4k3 load_bulk_with_entries: the first element of every pair is the day load_bulk gives, folder and ZIP alike",
      [d for d, _ in _pairs_dir] == _days and [d for d, _ in _pairs_zip] == _days)
_ent = {d["date"]: e for d, e in _pairs_dir}
check("4k3 load_bulk_with_entries: the entries of a day are the parts of the export that have it (uds, sleep, activities)",
      set(_ent["2024-05-01"]) == {"uds", "sleep", "activities"} and set(_ent["2024-05-02"]) == {"uds"}
      and set(_ent["2024-05-03"]) == {"sleep"} and set(_ent["2024-05-04"]) == {"readiness"})
check("4k3 load_bulk_with_entries: the entries are the objects of the export, as they are (not the day built from them)",
      _ent["2024-05-01"]["uds"] == _gdpr_sample()[_G_UDS][0] and _ent["2024-05-01"]["sleep"] == _gdpr_sample()[_G_SLEEP][0]
      and [a["name"] for a in _ent["2024-05-01"]["activities"]] == ["Run", "Walk"]
      and _ent["2024-05-04"]["readiness"]["level"] == "HIGH")
check("4k3 load_bulk_with_entries: parse_day of the entries is the day that came with them",
      all(_gi.parse_day(e, d["date"]) == d for d, e in _pairs_dir))
check("4k3 load_bulk_with_entries: without a hook it reads exactly like load_bulk (no hook argument needed)",
      list(_gi.load_bulk_with_entries(_exp_dir, None)) == _pairs_dir)

for _label, _exp in (("folder", _exp_dir), ("ZIP", _exp_zip)):
    _seen = {}
    _order = []

    def _hook(name, data, _seen=_seen, _order=_order):
        _seen[name] = data
        _order.append(name)

    _got = list(_gi.load_bulk_with_entries(_exp, _hook))
    _expect_names = {n for n in _gdpr_sample() if any(k in n for k in ("UDSFile_", "sleepData", "TrainingReadinessDTO", "summarizedActivities"))}
    check(f"4k3 read hook ({_label}): called once for every JSON file the loader reads (also for ones that are not lists or not JSON)",
          set(_seen) == _expect_names and len(_order) == len(_expect_names))
    _orig = _gdpr_sample()
    check(f"4k3 read hook ({_label}): the bytes are those of the file in the export, so their SHA-256 is that of the original",
          all(_hl4k3.sha256(d).hexdigest() == _hl4k3.sha256((_orig[n] if isinstance(_orig[n], str) else json.dumps(_orig[n])).encode("utf-8")).hexdigest()
              for n, d in _seen.items()))
    check(f"4k3 read hook ({_label}): hooked reading gives the same pairs as unhooked reading", _got == _pairs_dir)

_none_called = []
check("4k3 read hook: a path that does not exist, a file that is no ZIP and a corrupt ZIP call the hook never and give no pairs",
      all(list(_gi.load_bulk_with_entries(_pth, lambda n, d: _none_called.append(n))) == []
          for _pth in (_M4K / "nothing_here", _M4K / "plain.txt", _M4K / "broken.zip")) and _none_called == [])

_boom_res, _boom_log = _g_logged(lambda: list(_gi.load_bulk_with_entries(_exp_dir, lambda n, d: (_ for _ in ()).throw(RuntimeError("hook broke")))))
check("4k3 read hook: an exception of the hook ends the iteration and is reported as an unexpected error, it does not escape",
      _boom_res == [] and any(lv == "error" and "unexpected error" in m and "hook broke" in m for lv, m in _boom_log))

_pre_calls = []
_ = list(_gi.load_bulk_with_entries(_exp_zip, lambda n, d: _pre_calls.append(len(d))))
check("4k3 read hook: the hook gets bytes, not text", all(isinstance(n, int) and n > 0 for n in _pre_calls) and _pre_calls)

summary()
