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
             "floorsAscendedInMeters": 30, "restingHeartRate": 52, "minHeartRate": 45,
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
      _u["totalSteps"] == 8000 and _u["restingHeartRate"] == 52 and _u["floorsAscended"] == 10
      and _u["dailyStepGoal"] == 10000 and _u["maxHeartRate"] == 150)
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

# Ist-Stand: one malformed entry in a list stops the whole export (ROADMAP v1.7.4.6)
_bad_exp = _write_export_dir(_M4K / "export_bad_entry", {_G_UDS: [
    {"calendarDate": "2024-05-01", "totalSteps": 1}, "garbage", {"calendarDate": "2024-05-02", "totalSteps": 2}]})
check("Ist-Stand load_bulk: one malformed entry makes the whole export yield no day at all",
      list(_gi.load_bulk(_bad_exp)) == [])

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

    # Ist-Stand: the date is only validated after write_day() (ROADMAP v1.7.4.6)
    with patch.object(_gi, "load_bulk", return_value=iter(
            [{"date": "2024-13-45", "user_summary": {"totalSteps": 10}}])):
        _r = _col5.run_import("ignored")
    check("Ist-Stand run_import: an invalid date counts as failed ...", _r["failed"] == 1 and _r["ok"] == 0)
    check("Ist-Stand run_import: ... but a raw file with that date is left behind",
          (cfg.RAW_DIR / "garmin_raw_2024-13-45.json").exists())

# -- Ist-Stand: a better day from a non-API source is overwritten (ROADMAP v1.7.4.6) -----------------------------
with _isolated_log_env("gdpr_overwrite") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    (cfg.RAW_BACKUP_DIR / "2024-05").mkdir(parents=True)
    _rich = {"date": "2024-05-01", "heart_rates": {"restingHeartRate": 50,
             "heartRateValues": [[1740787200000, 58], [1740787260000, 60]]}}
    (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").write_text(json.dumps(_rich), encoding="utf-8")
    (cfg.RAW_BACKUP_DIR / "2024-05" / "garmin_raw_2024-05-01.json").write_text(json.dumps(_rich), encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "2024-05-01", "quality": "high", "source": "legacy", "write": True}]}), encoding="utf-8")
    _col5.run_import(_exp_dir)
    _after = json.loads((cfg.RAW_DIR / "garmin_raw_2024-05-01.json").read_text(encoding="utf-8"))
    check("Ist-Stand run_import: an existing high day from source 'legacy' loses its intraday values ...",
          "heartRateValues" not in _after.get("heart_rates", {}) and "user_summary" in _after)
    check("Ist-Stand run_import: ... the quality log still says high (the downgrade guard only protects the log)",
          _qdays()["2024-05-01"]["quality"] == "high" and _qdays()["2024-05-01"]["source"] == "legacy")
    check("Ist-Stand run_import: ... and the backup copy in the month folder is overwritten as well",
          "heartRateValues" not in json.loads((cfg.RAW_BACKUP_DIR / "2024-05" / "garmin_raw_2024-05-01.json")
                                              .read_text(encoding="utf-8")).get("heart_rates", {}))

# -- Ist-Stand: the stop event is registered but never checked in the import loop (ROADMAP v1.7.4.6) ----------------
with _isolated_log_env("gdpr_stop") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ev = threading.Event()
    _ev.set()
    _r = _col5.run_import(_exp_dir, stop_event=_ev)
    check("run_import: the stop event is registered with the collector",
          _col5._stop_event is _ev)
    _col5.set_stop_event(None)
    check("Ist-Stand run_import: a stop event that is already set does not stop the import",
          _r["ok"] == 2 and (cfg.RAW_DIR / "garmin_raw_2024-05-02.json").exists())

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

summary()
