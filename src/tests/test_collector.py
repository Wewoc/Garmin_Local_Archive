#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_collector.py — garmin_collector

Run from the project folder:
    python tests/test_collector.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import logging
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from gla_testenv import (  # sets up the environment; must precede garmin_* imports
    cfg, _TMPDIR, raw_full, _isolated_log_env, _put_log, _cfg_values, _run_main, _fetched_dates, _qdays, _fail_logs_with, _day_raw,
)
from support import check, section, summary

import garmin_backup_source as _q_backup_src
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

# ══════════════════════════════════════════════════════════════════════════════
#  4i. garmin_collector.main — sync flow, aborts, per-day errors, devices,
#      end-of-run backfill; garmin_sync.resolve_date_range (v1.7.4.0.2).
#      api.login / get_devices / fetch_raw are mocked; quality log, writer,
#      validator and sync run for real against isolated folders.
# ══════════════════════════════════════════════════════════════════════════════
section("4i. garmin_collector.main — sync flow, aborts, errors, devices, backfill")
import garmin_collector as _col5
import garmin_sync as _sync5


_RANGE = dict(SYNC_DATES=None, SYNC_MODE="range", SYNC_FROM="2024-05-01",
              SYNC_TO="2024-05-05", REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0)

# -- regular sync: session limit, picks up where it stopped --------------------------------
with _isolated_log_env("main_sync") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 2}):
        _code, _exc, _fetch, _ = _run_main()
        check("main sync: the session limit caps the number of fetched days",
              _fetched_dates(_fetch) == ["2024-05-01", "2024-05-02"] and _code is None and _exc is None)
        check("main sync: fetched days are written to raw/ and summary/",
              (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").exists()
              and (cfg.SUMMARY_DIR / "garmin_2024-05-02.json").exists()
              and not (cfg.RAW_DIR / "garmin_raw_2024-05-03.json").exists())
        _q = _qdays()
        check("main sync: quality log has an api entry per fetched day",
              set(_q) == {"2024-05-01", "2024-05-02"}
              and all(e["source"] == "api" and e["quality"] == "high" for e in _q.values()))
        check("main sync: the device table is written at the end of a run",
              cfg.DEVICE_TABLE_FILE.exists()
              and json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))[-1]["days_total"] == 2)
        _code, _exc, _fetch, _ = _run_main()
        check("main sync: the next run continues with the next missing days",
              _fetched_dates(_fetch) == ["2024-05-03", "2024-05-04"])

# -- main(): a raw file of failed quality that is not in the quality log gets an entry --
# (v1.7.4.0.2) Only with a quality log that already has a first_day; an empty log is
# rebuilt from raw/ by the one-time backfill instead (see Section 4j).
with _isolated_log_env("main_lowq") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / "garmin_raw_2024-04-20.json").write_text(
        json.dumps({"date": "2024-04-20"}), encoding="utf-8")
    _put_log({"first_day": "2024-04-01", "devices": [],
              "days": [{"date": "2024-04-01", "quality": "high", "write": True,
                        "source": "api", "attempts": 1}]})
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _code, _exc, _fetch, _ = _run_main()
    _q = _qdays()
    check("main sync: a failed-quality raw file missing from the log gets a log entry",
          "2024-04-20" in _q and _q["2024-04-20"]["quality"] == "failed"
          and _q["2024-04-20"]["attempts"] == 1)
    check("main sync: the day from the log and the fetched day are unaffected",
          _q["2024-04-01"]["quality"] == "high" and _q["2024-05-01"]["quality"] == "high"
          and _code is None and _exc is None)

with _isolated_log_env("main_recent") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(SYNC_DATES=None, SYNC_MODE="recent", SYNC_DAYS=3,
                     REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _code, _exc, _fetch, _ = _run_main()
        _expect = sorted((date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1))
        check("main sync: mode 'recent' fetches the last days up to yesterday",
              _fetched_dates(_fetch) == _expect)

# -- nothing to do ---------------------------------------------------------------------------
with _isolated_log_env("main_nothing") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _run_main()
        _before = _qdays()
        with _cfg_values(SYNC_DATES=[date(2024, 5, 1)]):
            _code, _exc, _fetch, _ = _run_main()
        check("main: every requested day already present -> nothing fetched, run ends cleanly",
              not _fetch.called and _code is None and _exc is None)
        check("main: nothing-to-do run leaves the quality log as it was",
              _qdays() == _before)

# -- login problems -----------------------------------------------------------------------------
with _isolated_log_env("main_login") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**_RANGE):
        _code, _exc, _fetch, _ = _run_main(login_error=_col5.api.GarminLoginError("bad password-xyz"))
        check("main: login error -> exit code 1, nothing fetched", _code == 1 and not _fetch.called)
        check("main: login error keeps the session log in log/fail/",
              len(_fail_logs_with("bad password-xyz")) == 1)
        _code, _exc, _fetch, _ = _run_main(login=None)
        check("main: login cancelled by the user -> clean return, no exit code, nothing fetched",
              _code is None and _exc is None and not _fetch.called)
        check("main: login cancelled -> no failure log is kept for it",
              _fail_logs_with("Login cancelled by user") == [])

# -- import mode ----------------------------------------------------------------------------------
with _isolated_log_env("main_import") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(_col5, "run_import", return_value={"failed": 0}) as _ri:
        _code, _exc, _fetch, _ = _run_main(env={"GARMIN_IMPORT_PATH": "C:/export.zip"},
                                           stop_event=threading.Event())
    check("main import mode: success -> exit code 0, no regular sync",
          _code == 0 and not _fetch.called)
    check("main import mode: the path and the stop event are handed to run_import",
          _ri.call_args.args == ("C:/export.zip",) and "stop_event" in _ri.call_args.kwargs)
    with patch.object(_col5, "run_import", return_value={"failed": 2}):
        _code, _exc, _fetch, _ = _run_main(env={"GARMIN_IMPORT_PATH": "C:/export.zip"})
    check("main import mode: failed days -> exit code 1", _code == 1)

# -- stop event -------------------------------------------------------------------------------------
with _isolated_log_env("main_stop") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ev = threading.Event()
    _ev.set()
    with _cfg_values(**_RANGE):
        _code, _exc, _fetch, _ = _run_main(stop_event=_ev)
        check("main: a stop event that is already set -> nothing fetched, clean end",
              not _fetch.called and _code is None and _exc is None)
        check("main: stopped run records no day", _qdays() == {})

# -- errors for single days ---------------------------------------------------------------------------
def _fetch_boom_on_02(client, date_str, extra_endpoints=None):
    if date_str == "2024-05-02":
        raise RuntimeError("Garmin said no")
    return _day_raw(date_str, "high"), []


with _isolated_log_env("main_dayerr") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 3}):
        _code, _exc, _fetch, _ = _run_main(fetch=_fetch_boom_on_02)
        _q = _qdays()
        check("main: an error on one day does not stop the other days",
              _q["2024-05-01"]["quality"] == "high" and _q["2024-05-03"]["quality"] == "high"
              and _code is None and _exc is None)
        check("main: the failed day is recorded as failed, not written, flagged for recheck",
              _q["2024-05-02"]["quality"] == "failed" and _q["2024-05-02"]["write"] is False
              and _q["2024-05-02"]["recheck"] is True)
        check("main: the reason of the error is kept in the quality log",
              "Garmin said no" in _q["2024-05-02"]["reason"])
        check("main: a session with an error keeps its log in log/fail/",
              len(_fail_logs_with("Garmin said no")) == 1)

# Ist-Stand: the quality log cannot be saved after a day was written. The downgrade
# guard keeps the stored 'high' entry, but the run reports the day as saved AND as an
# error ("1 saved, 1 errors") and keeps a failure log (ROADMAP v1.7.4.4).
with _isolated_log_env("main_saveerr") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _real_save = quality._save_quality_log

    def _save_fails_per_day(data, skip_backup=False):
        if skip_backup:
            raise OSError("disk full")
        return _real_save(data, skip_backup=skip_backup)

    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        with patch.object(quality, "_save_quality_log", side_effect=_save_fails_per_day):
            _code, _exc, _fetch, _ = _run_main()
        _q = _qdays()
        check("Ist-Stand main: a failing save after a written day -> run goes on, no crash",
              _code is None and _exc is None)
        check("Ist-Stand main: the written day keeps its stored quality (downgrade blocked)",
              _q["2024-05-01"]["quality"] == "high" and _q["2024-05-01"]["write"] is True
              and (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").exists()
              and (cfg.SUMMARY_DIR / "garmin_2024-05-01.json").exists())
        check("Ist-Stand main: the run counts that day as saved and as an error, keeps a failure log",
              len(_fail_logs_with("1 saved, 1 errors")) == 1)

# -- downgrade of a bulk day: attempts run out -------------------------------------------------------
def _fetch_downgrade(client, date_str, extra_endpoints=None):
    return _day_raw(date_str, "standard"), []        # worse than the bulk 'high' below


with _isolated_log_env("main_bulk") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "2024-05-01", "quality": "high", "source": "bulk", "write": True,
         "recheck": True, "attempts": 1}]}), encoding="utf-8")
    with _cfg_values(SYNC_DATES=[date(2024, 5, 1)], REFRESH_FAILED=True, MAX_DAYS_PER_SESSION=0):
        _code, _exc, _fetch, _ = _run_main(fetch=_fetch_downgrade)
        _q = _qdays()["2024-05-01"]
        check("main: a worse API result never replaces the stored bulk day",
              _q["quality"] == "high" and _q["source"] == "bulk")
        check("main: after the second rejected attempt the bulk recheck is switched off",
              _q["attempts"] == 2 and _q["recheck"] is False)

# -- bulk days flagged for a re-fetch, invalid entries --------------------------------------------------
with _isolated_log_env("main_bulkflag") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _recent = (date.today() - timedelta(days=5)).isoformat()
    _old = (date.today() - timedelta(days=cfg.INTRADAY_RETRY_WINDOW_DAYS + 200)).isoformat()
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": _old, "devices": [], "days": [
        {"date": _recent, "quality": "standard", "source": "bulk", "write": True, "recheck": False},
        {"date": _old, "quality": "standard", "source": "bulk", "write": True, "recheck": False},
        {"quality": "standard", "source": "bulk"},
    ]}), encoding="utf-8")
    (cfg.RAW_DIR).mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").write_text(json.dumps(_day_raw("2024-05-01")), encoding="utf-8")
    with _cfg_values(SYNC_DATES=[date(2024, 5, 1)], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _code, _exc, _fetch, _ = _run_main()
        _q = _qdays()
        check("main: a bulk day inside the high-resolution window is flagged for re-fetch",
              _q[_recent]["recheck"] is True)
        check("main: a bulk day older than the window is left alone", _q[_old]["recheck"] is False)
        check("main: a bulk entry without a date is skipped, no crash", _code is None and _exc is None)

# Ist-Stand: one invalid date in the quality log aborts the whole run (ROADMAP v1.7.4.4)
with _isolated_log_env("main_baddate") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "not-a-date", "quality": "high", "source": "api", "write": True}]}), encoding="utf-8")
    with _cfg_values(**_RANGE):
        _code, _exc, _fetch, _ = _run_main()
        check("Ist-Stand main: an invalid date in the quality log aborts the run with an error",
              isinstance(_exc, ValueError) and not _fetch.called)

# -- one-time quality log backfill from raw/ ----------------------------------------------------------
with _isolated_log_env("main_firstday") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").write_text(
        json.dumps(_day_raw("2024-05-01", "high")), encoding="utf-8")
    with _cfg_values(SYNC_DATES=[date(2024, 5, 1)], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _code, _exc, _fetch, _ = _run_main()
        _q = _qdays()
        check("main: without first_day, existing raw files are added to the quality log",
              "2024-05-01" in _q and _q["2024-05-01"]["source"] == "legacy"
              and _q["2024-05-01"]["quality"] == "high")

# -- device history and device ids --------------------------------------------------------------------------
with _isolated_log_env("main_devices") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _code, _exc, _fetch, _ = _run_main(devices=[{"id": 555, "name": "Edge 1040"}])
        check("main: the device list from the API is stored in the quality log",
              quality._load_quality_log()["devices"] == [{"id": 555, "name": "Edge 1040"}])

with _isolated_log_env("main_devices_err") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _code, _exc, _fetch, _ = _run_main(devices_error=RuntimeError("devices endpoint down"))
        check("main: a failing device call is only a warning, the day is still fetched",
              _code is None and _exc is None and _fetched_dates(_fetch) == ["2024-05-01"])


def _fetch_with_device(client, date_str, extra_endpoints=None):
    raw = _day_raw(date_str, "high")
    raw["training_status"] = {"mostRecentTrainingStatus": {"latestTrainingStatusData": {"555": {}}}}
    return raw, []


with _isolated_log_env("main_devid") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _run_main(fetch=_fetch_with_device, devices=[{"id": 555, "name": "Edge 1040"}])
        _q = _qdays()["2024-05-01"]
        check("main: the device of a day is taken from the training status and named from the list",
              _q["device_id"] == "555" and _q["device_name"] == "Edge 1040")

# device_id backfill for archived days
with _isolated_log_env("main_devbackfill") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    _r1 = _day_raw("2024-04-01")
    _r1["training_status"] = {"mostRecentTrainingStatus": {
        "recordedDevices": [{"deviceId": 777, "deviceName": "Fenix"}]}}
    _r2 = _day_raw("2024-04-02")
    _r2["training_status"] = {"mostRecentTrainingStatus": {"latestTrainingStatusData": {"888": {}}}}
    for _d, _r in (("2024-04-01", _r1), ("2024-04-02", _r2)):
        (cfg.RAW_DIR / f"garmin_raw_{_d}.json").write_text(json.dumps(_r), encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-04-01", "devices": [], "days": [
        {"date": "2024-04-01", "quality": "high", "source": "api", "write": True},
        {"date": "2024-04-02", "quality": "high", "source": "api", "write": True},
        {"date": "2024-04-03", "quality": "high", "source": "api", "write": True},      # no raw file
        {"quality": "high", "source": "api", "write": True},                              # no date
    ]}), encoding="utf-8")
    with _cfg_values(SYNC_DATES=[date(2024, 4, 1)], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _run_main()
        _q = _qdays()
        check("main: device_id backfill reads the device from archived raw files",
              _q["2024-04-01"]["device_id"] == "777" and _q["2024-04-01"]["device_name"] == "Fenix")
        check("main: device_id backfill falls back to the training status keys",
              _q["2024-04-02"]["device_id"] == "888" and _q["2024-04-02"]["device_name"] == "")
        check("main: device_id backfill leaves days without a raw file unchanged",
              _q["2024-04-03"]["device_id"] is None)
        check("main: device_id backfill rewrites device_table.json",
              cfg.DEVICE_TABLE_FILE.exists())

# -- source backup backfill at the end of a run -----------------------------------------------------------------
with _isolated_log_env("main_srcbackfill") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.SOURCE_DIR / "garmin_source_2024-03-03.json").write_text("{}", encoding="utf-8")
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        _run_main()
        check("main: a source file without a backup is backed up at the end of a successful run",
              (cfg.SOURCE_BACKUP_DIR / "2024-03" / "garmin_source_2024-03-03.json").exists()
              or (cfg.SOURCE_BACKUP_DIR / "source_backup_2024-03.zip").exists())

with _isolated_log_env("main_srcbackfill_err") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}):
        with patch.object(_q_backup_src, "check_source_backfill_needed", side_effect=RuntimeError("zip broke")):
            _code, _exc, _fetch, _ = _run_main()
        check("main: a failing source backup check at the end is only a warning",
              _code is None and _exc is None and _qdays()["2024-05-01"]["quality"] == "high")

# -- garmin_sync.resolve_date_range -------------------------------------------------------------------------------
with _cfg_values(SYNC_MODE="range", SYNC_FROM="2024-01-05", SYNC_TO="2024-01-09"):
    check("resolve_date_range: mode 'range' returns the configured dates",
          _sync5.resolve_date_range(None) == (date(2024, 1, 5), date(2024, 1, 9)))
with _cfg_values(SYNC_MODE="range", SYNC_FROM="not-a-date", SYNC_TO="2024-01-09"):
    try:
        _sync5.resolve_date_range(None)
        _raised5 = None
    except Exception as e:                       # noqa: BLE001
        _raised5 = e
    check("resolve_date_range: mode 'range' with an invalid date -> ConfigurationError",
          isinstance(_raised5, _sync5.ConfigurationError))
_yday5 = date.today() - timedelta(days=1)
with _cfg_values(SYNC_MODE="auto", SYNC_AUTO_FALLBACK=None):
    check("resolve_date_range: mode 'auto' starts at first_day",
          _sync5.resolve_date_range("2023-06-01") == (date(2023, 6, 1), _yday5))
    check("resolve_date_range: mode 'auto' without first_day or fallback -> last 90 days",
          _sync5.resolve_date_range(None) == (date.today() - timedelta(days=90), _yday5))
with _cfg_values(SYNC_MODE="auto", SYNC_AUTO_FALLBACK="2022-02-02"):
    check("resolve_date_range: mode 'auto' without first_day uses the fallback date",
          _sync5.resolve_date_range(None) == (date(2022, 2, 2), _yday5))
with _cfg_values(SYNC_MODE="nonsense"):
    try:
        _sync5.resolve_date_range(None)
        _code5 = None
    except SystemExit as e:
        _code5 = e.code
    check("resolve_date_range: unknown mode -> exit code 1", _code5 == 1)

# ══════════════════════════════════════════════════════════════════════════════
#  4j. garmin_collector helpers — fetch robustness, session logs, self-healing,
#      schema migration, bulk field backfill, steps backfill, force-refetch
#      edge cases (v1.7.4.0.2). Same harness as Section 4i.
# ══════════════════════════════════════════════════════════════════════════════
section("4j. garmin_collector helpers — logs, self-healing, migration, backfills")
import garmin_force_refetch as _ffr5
import garmin_source_writer as _sw5
import garmin_validator as _validator5
import garmin_writer as _writer5
import garmin_normalizer as _normalizer5

# -- _fetch_and_assess: non-fatal problems ------------------------------------------------------
def _fa(raw, failed_endpoints=()):
    with patch("garmin_collector.api.fetch_raw", return_value=(raw, list(failed_endpoints))):
        return _col5._fetch_and_assess(MagicMock(), "2024-05-01")


with _isolated_log_env("fa") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res = _fa(_day_raw("2024-05-01", "high"), ["get_hrv_data", "get_spo2_data"])
    check("fetch_and_assess: failed endpoints are only reported, the day is still assessed",
          _res[0] == "high" and _res[1]["date"] == "2024-05-01")
    with patch.object(_sw5, "write_source", return_value=False):
        check("fetch_and_assess: source/ write reporting failure is not fatal",
              _fa(_day_raw("2024-05-01", "high"))[0] == "high")
    with patch.object(_sw5, "write_source", side_effect=OSError("disk full")):
        check("fetch_and_assess: source/ write raising is not fatal",
              _fa(_day_raw("2024-05-01", "high"))[0] == "high")
    with patch.object(_sw5, "update_log", side_effect=OSError("log locked")):
        check("fetch_and_assess: a failing source log update is not fatal",
              _fa(_day_raw("2024-05-01", "high"))[0] == "high")
        _res = _fa({"date": 99999})
        check("fetch_and_assess: validator critical + failing source log update -> still 'failed'",
              _res[0] == "failed" and _res[1] is None and _res[2] is None)

# -- session logs ------------------------------------------------------------------------------------
def _open_session_log(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    logging.getLogger().addHandler(fh)
    return fh


with _isolated_log_env("sessionlog") as _b:
    _recent, _fail = _b / "recent", _b / "fail"
    with _cfg_values(LOG_RECENT_DIR=_recent, LOG_FAIL_DIR=_fail, LOG_RECENT_MAX=2):
        _recent.mkdir()
        _fail.mkdir()
        for _i, _n in enumerate(("garmin_1.log", "garmin_2.log", "garmin_3.log")):
            (_recent / _n).write_text(_n, encoding="utf-8")
            os.utime(_recent / _n, (1000 + _i, 1000 + _i))
        _sess = _recent / "garmin_session.log"
        _fh = _open_session_log(_sess)
        _col5._close_session_log(_fh, _sess, False, False)
        check("close_session_log: the handler is detached from the root logger",
              _fh not in logging.getLogger().handlers)
        check("close_session_log: only LOG_RECENT_MAX newest session logs are kept",
              sorted(p.name for p in _recent.glob("garmin_*.log"))
              == ["garmin_3.log", "garmin_session.log"])
        check("close_session_log: a clean session leaves nothing in log/fail/",
              list(_fail.glob("*.log")) == [])

        _fh = _open_session_log(_sess)
        _col5._close_session_log(_fh, _sess, True, False)
        check("close_session_log: a session with errors is copied to log/fail/",
              (_fail / "garmin_session.log").exists())
        (_fail / "garmin_session.log").unlink()
        _fh = _open_session_log(_sess)
        _col5._close_session_log(_fh, _sess, False, True)
        check("close_session_log: a session with incomplete days is copied to log/fail/",
              (_fail / "garmin_session.log").exists())

        _fh = _open_session_log(_sess)
        with patch("shutil.copy2", side_effect=OSError("nope")):
            _col5._close_session_log(_fh, _sess, True, False)
        check("close_session_log: a failing copy to log/fail/ is only a warning", True)
        _fh = _open_session_log(_sess)
        with patch.object(Path, "glob", side_effect=OSError("denied")):
            _col5._close_session_log(_fh, _sess, False, False)
        check("close_session_log: a failing rotation is only a warning", True)

with _isolated_log_env("ffrlog") as _b:
    with _cfg_values(LOG_FORCE_REFETCH_DIR=_b / "ffr_logs", LOG_FORCE_REFETCH_MAX=2):
        _fh, _p = _col5._start_force_refetch_log()
        with patch.object(Path, "glob", side_effect=OSError("denied")):
            _col5._close_force_refetch_log(_fh)
        check("close_force_refetch_log: a failing rotation is only a warning, handler detached",
              _fh not in logging.getLogger().handlers)

# -- self-healing -------------------------------------------------------------------------------------
with _isolated_log_env("selfheal") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _qd = {"days": [
        {"date": "2024-06-01", "validator_result": "warning", "validator_schema_version": "0.1"},
        {"validator_result": "warning", "validator_schema_version": "0.1"},
    ]}
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    _raw_sh = cfg.RAW_DIR / "garmin_raw_2024-06-01.json"
    _raw_sh.write_text(json.dumps({"date": "2024-06-01", "unexpected_field": 1}), encoding="utf-8")
    with patch.object(_validator5, "current_version", return_value="unknown"):
        _col5._run_self_healing(_qd)
    check("self-healing: schema not loaded -> nothing is touched, even with a raw file present",
          _qd["days"][0]["validator_schema_version"] == "0.1")
    _raw_sh.unlink()
    _col5._run_self_healing(_qd)
    check("self-healing: no raw file for a candidate -> skipped, entry unchanged",
          _qd["days"][0]["validator_schema_version"] == "0.1")
    _raw_sh.write_text(json.dumps({"date": "2024-06-01", "unexpected_field": 1}), encoding="utf-8")
    _col5._run_self_healing(_qd)
    check("self-healing: unchanged validator result -> only the schema version is stamped",
          _qd["days"][0]["validator_schema_version"] == _validator5.current_version()
          and _qd["days"][0]["validator_result"] == "warning")
    check("self-healing: an entry without a date is skipped",
          _qd["days"][1]["validator_schema_version"] == "0.1")

# -- schema migration ----------------------------------------------------------------------------------
_D6 = ["2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05"]
with _isolated_log_env("migration") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    cfg.SUMMARY_DIR.mkdir(parents=True)
    _cur = _normalizer5.CURRENT_SCHEMA_VERSION
    _raw_mig = _day_raw(_D6[0], "high")
    _raw_mig["note"] = "Grüße"
    for _d in (_D6[0], _D6[1], _D6[4]):          # _D6[3] gets a summary but no raw file
        (cfg.RAW_DIR / f"garmin_raw_{_d}.json").write_text(
            json.dumps({**_raw_mig, "date": _d}, ensure_ascii=False), encoding="utf-8")
    (cfg.SUMMARY_DIR / f"garmin_{_D6[0]}.json").write_text(
        json.dumps({"date": _D6[0], "schema_version": _cur - 1}), encoding="utf-8")       # old, raw present
    (cfg.SUMMARY_DIR / f"garmin_{_D6[1]}.json").write_text(
        json.dumps({"date": _D6[1], "schema_version": _cur}), encoding="utf-8")           # current
    (cfg.SUMMARY_DIR / f"garmin_{_D6[3]}.json").write_text(
        json.dumps({"date": _D6[3], "schema_version": _cur - 1}), encoding="utf-8")       # old, no raw file
    (cfg.SUMMARY_DIR / f"garmin_{_D6[4]}.json").write_text(
        json.dumps({"date": _D6[4], "schema_version": _cur - 1}), encoding="utf-8")       # old, write fails
    _cur_bytes = (cfg.SUMMARY_DIR / f"garmin_{_D6[1]}.json").read_bytes()
    _raw_before = json.loads((cfg.RAW_DIR / f"garmin_raw_{_D6[0]}.json").read_text(encoding="utf-8"))
    _qd = {"days": [{"date": d} for d in _D6] + [{"quality": "high"}]}      # _D6[2] has no summary at all

    _real_write_day = _writer5.write_day

    def _write_day_fails_on_05(normalized, summary, date_str):
        if date_str == _D6[4]:
            raise OSError("disk full")
        return _real_write_day(normalized, summary, date_str)

    with patch.object(_writer5, "write_day", side_effect=_write_day_fails_on_05):
        _col5._run_schema_migration(_qd)
    _sm = {d: json.loads((cfg.SUMMARY_DIR / f"garmin_{d}.json").read_text(encoding="utf-8"))
           for d in (_D6[0], _D6[1], _D6[3], _D6[4])}
    check("schema migration: an outdated summary is rewritten with the current schema version",
          _sm[_D6[0]]["schema_version"] == _cur and _sm[_D6[0]].get("generated_by"))
    check("schema migration: the raw content of the migrated day is unchanged",
          json.loads((cfg.RAW_DIR / f"garmin_raw_{_D6[0]}.json").read_text(encoding="utf-8")) == _raw_before)
    check("schema migration: a current summary is not touched",
          (cfg.SUMMARY_DIR / f"garmin_{_D6[1]}.json").read_bytes() == _cur_bytes)
    check("schema migration: no summary file, no date, no raw file -> skipped, nothing created",
          not (cfg.SUMMARY_DIR / f"garmin_{_D6[2]}.json").exists()
          and _sm[_D6[3]]["schema_version"] == _cur - 1)
    check("schema migration: an error on one day leaves that summary alone, others are done",
          _sm[_D6[4]]["schema_version"] == _cur - 1 and _sm[_D6[0]]["schema_version"] == _cur)
    # Ist-Stand: the run says "Raw files are not modified", but write_day() rewrites raw/
    # and refreshes the raw backup (ROADMAP v1.7.4.5).
    check("Ist-Stand migration: raw/ is rewritten too, a raw backup copy appears",
          (cfg.RAW_BACKUP_DIR / "2024-05" / f"garmin_raw_{_D6[0]}.json").exists())

    with patch.object(_writer5, "write_day") as _wd:
        _col5._run_schema_migration({"days": [{"date": _D6[1]}]})
    check("schema migration: all summaries up to date -> nothing is written", not _wd.called)

# -- bulk field backfill ---------------------------------------------------------------------------------
_BF_DAY = "2024-06-10"


def _bulk_qd():
    return {"days": [{"date": _BF_DAY, "quality": "standard", "source": "bulk",
                      "write": True, "fields": {}}]}


with _isolated_log_env("bulkfield") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(SYNC_DATES=None), patch("garmin_collector.api.fetch_raw") as _fr:
        _col5._run_bulk_field_backfill(MagicMock(), _bulk_qd())
    check("bulk field backfill: without GARMIN_SYNC_DATES nothing is fetched", not _fr.called)

    _ev = threading.Event()
    _ev.set()
    _col5.set_stop_event(_ev)
    with _cfg_values(SYNC_DATES=[date(2024, 6, 10)]), patch("garmin_collector.api.fetch_raw") as _fr:
        _col5._run_bulk_field_backfill(MagicMock(), _bulk_qd())
    _col5.set_stop_event(None)
    check("bulk field backfill: a stop event ends the loop before the first day", not _fr.called)

    _qd = _bulk_qd()
    with _cfg_values(SYNC_DATES=[date(2024, 6, 10)]), \
         patch("garmin_collector.api.fetch_raw", return_value=({"date": 99999}, [])):
        _col5._run_bulk_field_backfill(MagicMock(), _qd)
    _att = _qd["days"][0].get("field_backfill_attempts", {})
    check("bulk field backfill: validator critical -> every open gap field gets an attempt",
          set(_att) == set(_col5.BULK_GAP_FIELDS) and all(v == 1 for v in _att.values()))
    check("bulk field backfill: validator critical -> no raw file is written",
          not (cfg.RAW_DIR / f"garmin_raw_{_BF_DAY}.json").exists())

    with _cfg_values(SYNC_DATES=[date(2024, 6, 10)]), \
         patch("garmin_collector.api.fetch_raw", return_value=(_day_raw(_BF_DAY, "high"), [])), \
         patch.object(_writer5, "write_day", return_value=False):
        _col5._run_bulk_field_backfill(MagicMock(), _qd)
    check("bulk field backfill: write_day failing -> attempts count up again",
          all(v == 2 for v in _qd["days"][0]["field_backfill_attempts"].values()))

    with _cfg_values(SYNC_DATES=[date(2024, 6, 10)]), \
         patch("garmin_collector.api.fetch_raw", side_effect=RuntimeError("api down")):
        _col5._run_bulk_field_backfill(MagicMock(), _qd)
    check("bulk field backfill: an unexpected error counts as an attempt and the run goes on",
          all(v == 3 for v in _qd["days"][0]["field_backfill_attempts"].values()))

# -- steps backfill: archived day without a raw file --------------------------------------------------------
with _isolated_log_env("steps") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _qd = {"days": [{"date": "2024-06-11", "quality": "high", "source": "api", "write": True}]}
    with _cfg_values(SYNC_DATES=[date(2024, 6, 11)]), patch("garmin_collector.api.api_call") as _ac:
        _col5._run_steps_backfill(MagicMock(), _qd)
    check("steps backfill: a day without a raw file is skipped, no API call is made",
          not _ac.called)
    check("steps backfill: ... and counts as a failed attempt for 'steps'",
          _qd["days"][0]["field_backfill_attempts"] == {"steps": 1})

# -- force-refetch edge cases ---------------------------------------------------------------------------------
with _isolated_log_env("ffredge") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(FORCE_REFETCH_BACKUP_DIR=_b / "ffr_backup"):
        _res = _col5.commit_force_refetch(
            [{"date": "2024-06-12", "error": None, "quality_after": "high"}], set(), {"days": []})
        check("commit_force_refetch: a rejected day without a snapshot reports that",
              _res == [{"date": "2024-06-12", "action": "reverted", "error": "no snapshot to restore"}])
        with patch.object(_ffr5, "restore_snapshot", side_effect=RuntimeError("boom")):
            _res = _col5.commit_force_refetch(
                [{"date": "2024-06-12", "error": None, "quality_after": "high"}], set(), {"days": []})
        check("commit_force_refetch: a failing revert is reported with the reason, no crash",
              _res == [{"date": "2024-06-12", "action": "reverted", "error": "boom"}])

        cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        _sp = cfg.SOURCE_DIR / "garmin_source_2024-06-13.json"
        _sp.write_text("{broken", encoding="utf-8")
        with patch("garmin_collector.api.fetch_raw", return_value=(_day_raw("2024-06-13", "high"), [])):
            _res = _col5.run_force_refetch_preview(MagicMock(), ["2024-06-13"])
        check("force-refetch preview: an unreadable existing source file counts as no prior data",
              _res[0]["error"] is None and _res[0]["quality_before"] == "failed")

        _sp.write_text(json.dumps({"heart_rates": {"x": 1}}), encoding="utf-8")

        def _write_source_garbage(raw_data, date_str, force=False):
            (cfg.SOURCE_DIR / f"garmin_source_{date_str}.json").write_text("{garbage", encoding="utf-8")
            return True

        with patch("garmin_collector.api.fetch_raw", return_value=(_day_raw("2024-06-13", "high"), [])), \
             patch.object(_sw5, "write_source", side_effect=_write_source_garbage):
            _res = _col5.run_force_refetch_preview(MagicMock(), ["2024-06-13"])
        check("force-refetch preview: an unreadable new source file -> no crash, comparison still made",
              _res[0]["error"] is None and _res[0]["had_prior_data"] is True
              and isinstance(_res[0]["fields_changed"], list))

# ══════════════════════════════════════════════════════════════════════════════
#  6. garmin_collector internals
# ══════════════════════════════════════════════════════════════════════════════
section("6. garmin_collector internals")
import garmin_collector as collector

# _should_write
check("_should_write high=True",      collector._should_write("high")     == True)
check("_should_write standard=True",  collector._should_write("standard") == True)
check("_should_write medium=False",   collector._should_write("medium")   == False)
check("_should_write low=False",      collector._should_write("low")      == False)
check("_should_write failed=False",   collector._should_write("failed")   == False)
check("_should_write unknown=False",  collector._should_write("xyz")      == False)

# _is_stopped — now via set_stop_event (Option C, no globals injection)
check("_is_stopped: False by default", collector._is_stopped() == False)

ev = threading.Event(); ev.set()
collector.set_stop_event(ev)
check("_is_stopped: True when set",    collector._is_stopped() == True)
# Collector distributes to garmin_api — verify the API module sees it too
import garmin_api as _api_stop
check("_is_stopped: api sees event",   _api_stop._is_stopped() == True)

# set_stop_event(None) clears on both modules
collector.set_stop_event(None)
check("_is_stopped: cleared on collector", collector._is_stopped() == False)
check("_is_stopped: cleared on api",       _api_stop._is_stopped() == False)

# Mandatory cleanup — module-level state must not leak into later tests
collector.set_stop_event(None)

# summarize + safe_get no longer in collector
check("summarize not in collector", not hasattr(collector, "summarize"))
check("safe_get not in collector",  not hasattr(collector, "safe_get"))

# _fetch_and_assess — mocked
mock_client = MagicMock()
with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])):
    label, normalized, summary_data, fields, val_result = collector._fetch_and_assess(mock_client, "2024-03-15")
    check("_fetch_and_assess: label = high",          label      == "high")
    check("_fetch_and_assess: normalized is dict",    isinstance(normalized, dict))
    check("_fetch_and_assess: summary is dict",       isinstance(summary_data, dict))
    check("_fetch_and_assess: fields is dict",        isinstance(fields, dict))
    check("_fetch_and_assess: val_result is dict",    isinstance(val_result, dict))
    check("_fetch_and_assess: val_result has status", "status" in val_result)

with patch("garmin_collector.api.fetch_raw", return_value=({"date": 99999}, [])), \
     patch("garmin_collector.writer.write_day") as mock_w:
    label2, normalized2, summary_data2, fields2, val_result2 = collector._fetch_and_assess(mock_client, "2024-03-20")
    check("_fetch_and_assess failed: label=failed",         label2       == "failed")
    check("_fetch_and_assess failed: normalized is None",   normalized2  is None)
    check("_fetch_and_assess failed: write_day not called", not mock_w.called)
    check("_fetch_and_assess failed: fields is dict",       isinstance(fields2, dict))
    check("_fetch_and_assess failed: val_result is dict",   isinstance(val_result2, dict))

# _run_schema_migration — missing summary file → skipped without crash
qd_migrate = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": "1900-02-02", "quality": "high"},
    ]
}
try:
    collector._run_schema_migration(qd_migrate)
    check("_run_schema_migration: missing summary → no crash", True)
except Exception:
    check("_run_schema_migration: missing summary → no crash", False)

# ── _fetch_and_assess() — extra_endpoints construction from enabled_candidates
#    (v1.6.8) ──────────────────────────────────────────────────────────────
import garmin_api_capability as capability

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])) as _mock_fetch_extra:
    collector._fetch_and_assess(mock_client, "2024-03-15",
                                 enabled_candidates=["get_body_composition", "get_hydration_data"])
    _extra_kwargs = _mock_fetch_extra.call_args.kwargs
    check("_fetch_and_assess: extra_endpoints built from enabled_candidates",
          _extra_kwargs.get("extra_endpoints") == [
              ("get_body_composition",
               capability.build_args("get_body_composition", "2024-03-15"),
               "get_body_composition"),
              ("get_hydration_data",
               capability.build_args("get_hydration_data", "2024-03-15"),
               "get_hydration_data"),
          ])

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])) as _mock_fetch_none:
    collector._fetch_and_assess(mock_client, "2024-03-15")
    check("_fetch_and_assess: extra_endpoints=None when enabled_candidates=None",
          _mock_fetch_none.call_args.kwargs.get("extra_endpoints") is None)

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])) as _mock_fetch_empty:
    collector._fetch_and_assess(mock_client, "2024-03-15", enabled_candidates=[])
    check("_fetch_and_assess: extra_endpoints=None when enabled_candidates=[]",
          _mock_fetch_empty.call_args.kwargs.get("extra_endpoints") is None)

# ── run_capability_scan() (v1.6.8) ───────────────────────────────────────────

# all not_observed
with patch("garmin_collector.api.api_call", side_effect=lambda *a, **k: (None, True)), \
     patch("garmin_collector.capability.save_config") as _mock_save_a:
    _rcs_a = collector.run_capability_scan(mock_client, window_days=1)
check("run_capability_scan: all not_observed — counts",
      _rcs_a == {"scanned": 19, "found": 0, "not_observed": 19, "error": 0})
check("run_capability_scan: save_config called exactly once",
      _mock_save_a.call_count == 1)

# mixed: one found, one error (API call failure), rest not_observed
def _rcs_mixed_side_effect(client_arg, endpoint, *args, label=None):
    if endpoint == "get_body_composition":
        return ({"weight": 70}, True)
    if endpoint == "get_daily_weigh_ins":
        return (None, False)
    return (None, True)

with patch("garmin_collector.api.api_call", side_effect=_rcs_mixed_side_effect), \
     patch("garmin_collector.capability.save_config"):
    _rcs_b = collector.run_capability_scan(mock_client, window_days=1)
check("run_capability_scan: mixed result — counts",
      _rcs_b == {"scanned": 19, "found": 1, "not_observed": 17, "error": 1})

# per-candidate error isolation — one candidate raises, rest still scanned
def _rcs_raise_side_effect(client_arg, endpoint, *args, label=None):
    if endpoint == "get_blood_pressure":
        raise Exception("boom (simuliert)")
    return (None, True)

with patch("garmin_collector.api.api_call", side_effect=_rcs_raise_side_effect), \
     patch("garmin_collector.capability.save_config"):
    _rcs_c = collector.run_capability_scan(mock_client, window_days=1)
check("run_capability_scan: exception isolation — all 19 still scanned",
      _rcs_c["scanned"] == 19)
check("run_capability_scan: exception isolation — raising candidate counted as error",
      _rcs_c["error"] == 1)
check("run_capability_scan: exception isolation — rest not_observed",
      _rcs_c["not_observed"] == 18)

# _is_stopped() respected — breaks before first candidate
_rcs_stop_ev = threading.Event()
_rcs_stop_ev.set()
collector.set_stop_event(_rcs_stop_ev)
with patch("garmin_collector.api.api_call", side_effect=lambda *a, **k: (None, True)), \
     patch("garmin_collector.capability.save_config"):
    _rcs_d = collector.run_capability_scan(mock_client, window_days=1)
check("run_capability_scan: stopped before first candidate — scanned=0",
      _rcs_d["scanned"] == 0)
collector.set_stop_event(None)

# QUALITY_LOCK held during scan — second acquire (non-blocking) must fail
_rcs_lock_results = []
def _rcs_lock_side_effect(client_arg, endpoint, *args, label=None):
    _acquired = quality.QUALITY_LOCK.acquire(blocking=False)
    _rcs_lock_results.append(_acquired)
    if _acquired:
        quality.QUALITY_LOCK.release()
    return (None, True)

with patch("garmin_collector.api.api_call", side_effect=_rcs_lock_side_effect), \
     patch("garmin_collector.capability.save_config"):
    collector.run_capability_scan(mock_client, window_days=1)
check("run_capability_scan: QUALITY_LOCK held during scan",
      len(_rcs_lock_results) == 19 and all(a is False for a in _rcs_lock_results))

# cleanup — leave capability config file as Section K found it
capability.cfg.CAPABILITY_CONFIG_FILE.unlink(missing_ok=True)

# ── main() — 0b. Capability Scan entry point (v1.6.8) ────────────────────────

_orig_capscan_env   = os.environ.get("GARMIN_CAPABILITY_SCAN")
_orig_capwindow_env = os.environ.get("GARMIN_CAPABILITY_WINDOW_DAYS")

os.environ["GARMIN_CAPABILITY_SCAN"]        = "1"
os.environ["GARMIN_CAPABILITY_WINDOW_DAYS"] = "3"

# Case 1 — success (error=0) → sys.exit(0), window_days passed through
with patch("garmin_collector.api.login", return_value=MagicMock()), \
     patch("garmin_collector.run_capability_scan",
           return_value={"scanned": 19, "found": 5, "not_observed": 14, "error": 0}) as _mock_scan_ok, \
     patch("garmin_collector.sys.exit", side_effect=SystemExit) as _mock_exit_ok:
    try:
        collector.main()
        check("main() 0b: raises SystemExit (success)", False)
    except SystemExit:
        check("main() 0b: raises SystemExit (success)", True)
    check("main() 0b: window_days passed through from ENV",
          _mock_scan_ok.call_args.kwargs.get("window_days") == 3)
    check("main() 0b: sys.exit(0) on error=0",
          _mock_exit_ok.call_args.args == (0,))

# Case 2 — partial failure (error>0) → sys.exit(1)
with patch("garmin_collector.api.login", return_value=MagicMock()), \
     patch("garmin_collector.run_capability_scan",
           return_value={"scanned": 19, "found": 3, "not_observed": 14, "error": 2}), \
     patch("garmin_collector.sys.exit", side_effect=SystemExit) as _mock_exit_err:
    try:
        collector.main()
    except SystemExit:
        pass
    check("main() 0b: sys.exit(1) on error>0",
          _mock_exit_err.call_args.args == (1,))

# Case 3 — login raises GarminLoginError → sys.exit(1), scan never reached
with patch("garmin_collector.api.login",
           side_effect=collector.api.GarminLoginError("bad creds (simuliert)")), \
     patch("garmin_collector.run_capability_scan") as _mock_scan_noreach, \
     patch("garmin_collector.sys.exit", side_effect=SystemExit) as _mock_exit_login:
    try:
        collector.main()
    except SystemExit:
        pass
    check("main() 0b: login failure → sys.exit(1)",
          _mock_exit_login.call_args.args == (1,))
    check("main() 0b: login failure → scan never called",
          not _mock_scan_noreach.called)

# Case 4 — login cancelled (client is None) → plain return, no sys.exit
with patch("garmin_collector.api.login", return_value=None), \
     patch("garmin_collector.run_capability_scan") as _mock_scan_cancel, \
     patch("garmin_collector.sys.exit") as _mock_exit_cancel:
    collector.main()
    check("main() 0b: login cancelled → no sys.exit call",
          not _mock_exit_cancel.called)
    check("main() 0b: login cancelled → scan never called",
          not _mock_scan_cancel.called)

# restore ENV
if _orig_capscan_env is None:
    os.environ.pop("GARMIN_CAPABILITY_SCAN", None)
else:
    os.environ["GARMIN_CAPABILITY_SCAN"] = _orig_capscan_env
if _orig_capwindow_env is None:
    os.environ.pop("GARMIN_CAPABILITY_WINDOW_DAYS", None)
else:
    os.environ["GARMIN_CAPABILITY_WINDOW_DAYS"] = _orig_capwindow_env

# ── main() — regular sync fetch loop (v1.6.9, Block 1a) ──────────────────────
# Runs main() through the actual Step 1-9 fetch loop instead of the
# Capability-Scan branch (0b) — closes the E2E gap noted in
# REVIEW_GESAMTAUSWERTUNG.md / v1.6.9_ROADMAP_EINTRAG.md Block 1a.
# Uses the file's existing _TMPDIR sandbox (already active as BASE_DIR since
# Section 1) — no separate tmp mechanism. Three fixed dates cover ok/failed/
# downgrade in one pass. api.login / api.get_devices / api.fetch_raw are
# mocked; everything else (quality_log, writer, validator, sync) runs for
# real against files under _TMPDIR.

_e2e_d1, _e2e_d2, _e2e_d3 = "2025-06-01", "2025-06-02", "2025-06-03"

# Day 3 raw payload — raw_full plus the extra sub_fields needed to push
# out_of_range_count > 3 in _fetch_and_assess() (high → standard downgrade),
# while staying a "warning" (not "critical") validator status so the day
# is still fetched, just at lower quality than the pre-existing log entry.
_e2e_raw_downgrade = {
    **raw_full,
    "date": _e2e_d3,
    "heart_rates": {"restingHeartRate": 400, "maxHeartRate": 500,
                     "heartRateValues": [[0, 52], [60, 55]]},
    "stress": {"averageStressLevel": 500},
    "respiration": {"avgWakingRespirationValue": 900},
}

def _e2e_fetch_raw_side_effect(client, date_str, extra_endpoints=None):
    if date_str == _e2e_d1:
        return {**raw_full, "date": _e2e_d1}, []
    if date_str == _e2e_d2:
        return {"date": 99999}, []  # required field wrong type → validator critical
    if date_str == _e2e_d3:
        return _e2e_raw_downgrade, []
    raise AssertionError(f"unexpected date in E2E fetch loop: {date_str}")

# Pre-existing high/bulk entry for day 3 — the fresh fetch above must rank
# lower (standard), so the fetch loop's downgrade guard must reject it and
# keep this entry unchanged.
with quality.QUALITY_LOCK:
    _e2e_qd = quality._load_quality_log()
    quality._upsert_quality(_e2e_qd, date.fromisoformat(_e2e_d3), "high",
                            "Quality: high (pre-existing, simuliert)",
                            written=True, source="bulk")
    quality._save_quality_log(_e2e_qd)

os.environ["GARMIN_SYNC_DATES"]     = f"{_e2e_d1},{_e2e_d2},{_e2e_d3}"
os.environ["GARMIN_REFRESH_FAILED"] = "1"
importlib.reload(cfg)
# garmin_collector imported cfg by reference — reload() updates the same
# module object collector.cfg points to, no separate patch needed there.

with patch("garmin_collector.api.login", return_value=MagicMock()), \
     patch("garmin_collector.api.get_devices", return_value=[]), \
     patch("garmin_collector.api.fetch_raw", side_effect=_e2e_fetch_raw_side_effect):
    collector.main()

os.environ["GARMIN_SYNC_DATES"]     = ""
os.environ["GARMIN_REFRESH_FAILED"] = "0"
importlib.reload(cfg)

_e2e_qd_after = quality._load_quality_log()
_e2e_entries  = {e["date"]: e for e in _e2e_qd_after["days"] if e.get("date") in (_e2e_d1, _e2e_d2, _e2e_d3)}

check("main() fetch loop: all 3 days present in quality_log",
      set(_e2e_entries) == {_e2e_d1, _e2e_d2, _e2e_d3})

check("main() fetch loop: day1 quality=high",   _e2e_entries.get(_e2e_d1, {}).get("quality") == "high")
check("main() fetch loop: day1 write=True",     _e2e_entries.get(_e2e_d1, {}).get("write")   == True)
check("main() fetch loop: day1 raw/ written",   (cfg.RAW_DIR / f"garmin_raw_{_e2e_d1}.json").exists())
check("main() fetch loop: day1 summary/ written", (cfg.SUMMARY_DIR / f"garmin_{_e2e_d1}.json").exists())

check("main() fetch loop: day2 quality=failed", _e2e_entries.get(_e2e_d2, {}).get("quality") == "failed")
check("main() fetch loop: day2 write=False",    _e2e_entries.get(_e2e_d2, {}).get("write")   == False)
check("main() fetch loop: day2 recheck=True",   _e2e_entries.get(_e2e_d2, {}).get("recheck") == True)
check("main() fetch loop: day2 raw/ not written", not (cfg.RAW_DIR / f"garmin_raw_{_e2e_d2}.json").exists())

check("main() fetch loop: day3 downgrade rejected — quality stays high",
      _e2e_entries.get(_e2e_d3, {}).get("quality") == "high")
check("main() fetch loop: day3 downgrade rejected — source stays bulk",
      _e2e_entries.get(_e2e_d3, {}).get("source") == "bulk")
check("main() fetch loop: day3 reason mentions downgrade rejection",
      "downgrade rejected" in _e2e_entries.get(_e2e_d3, {}).get("reason", ""))
check("main() fetch loop: day3 raw/ not overwritten (no summary/ file)",
      not (cfg.SUMMARY_DIR / f"garmin_{_e2e_d3}.json").exists())

# ── Cleanup — remove all 3 E2E days from quality_log + any written files so
#    later sections sharing the same _TMPDIR are not affected. ──────────────
with quality.QUALITY_LOCK:
    _e2e_qd_cleanup = quality._load_quality_log()
    _e2e_qd_cleanup["days"] = [
        e for e in _e2e_qd_cleanup["days"] if e.get("date") not in (_e2e_d1, _e2e_d2, _e2e_d3)
    ]
    quality._save_quality_log(_e2e_qd_cleanup)

for _e2e_d in (_e2e_d1, _e2e_d2, _e2e_d3):
    (cfg.RAW_DIR / f"garmin_raw_{_e2e_d}.json").unlink(missing_ok=True)
    (cfg.SUMMARY_DIR / f"garmin_{_e2e_d}.json").unlink(missing_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  15. _check_downgrade
# ══════════════════════════════════════════════════════════════════════════════
section("15. _check_downgrade")
import garmin_collector as collector_dg

# Kein existing entry → nie downgrade
is_dg, el, es = collector_dg._check_downgrade("high", None)
check("downgrade: no entry → not a downgrade",       is_dg == False)
check("downgrade: no entry → existing_label=failed", el == "failed")
check("downgrade: no entry → existing_source=api",   es == "api")

# Gleiche Qualität → kein Downgrade
entry_high = {"quality": "high", "source": "api"}
is_dg, el, es = collector_dg._check_downgrade("high", entry_high)
check("downgrade: same label → not a downgrade",     is_dg == False)

# Echter Downgrade: high → low
entry_high2 = {"quality": "high", "source": "api"}
is_dg, el, es = collector_dg._check_downgrade("low", entry_high2)
check("downgrade: low < high → is_downgrade",        is_dg == True)
check("downgrade: existing_label = high",            el == "high")
check("downgrade: existing_source = api",            es == "api")

# Upgrade: low → high → kein Downgrade
entry_low = {"quality": "low", "source": "bulk"}
is_dg, el, es = collector_dg._check_downgrade("high", entry_low)
check("downgrade: high > low → not a downgrade",     is_dg == False)
check("downgrade: source = bulk preserved",          es == "bulk")

# failed → standard: Upgrade, kein Downgrade
entry_failed = {"quality": "failed", "source": "api"}
is_dg, el, es = collector_dg._check_downgrade("standard", entry_failed)
check("downgrade: standard > failed → not a downgrade", is_dg == False)

# standard → failed: Downgrade
entry_standard = {"quality": "standard", "source": "api"}
is_dg, el, es = collector_dg._check_downgrade("failed", entry_standard)
check("downgrade: failed < standard → is_downgrade",   is_dg == True)

# Grenzfall: fehlende 'quality'-Key im Entry → fällt auf "failed" zurück
entry_no_q = {"source": "api"}
is_dg, el, es = collector_dg._check_downgrade("standard", entry_no_q)
check("downgrade: missing quality key → existing=failed, no downgrade", is_dg == False)


# ══════════════════════════════════════════════════════════════════════════════
#  E. _run_source_backfill
# ══════════════════════════════════════════════════════════════════════════════
section("E. _run_source_backfill")

import garmin_collector as collector_bf
from unittest.mock import MagicMock, patch
from datetime import timedelta as _timedelta

# ── Hilfsfunktion: synthetischen Quality-Eintrag bauen ──────────────────────
def _make_api_entry(date_str, quality_label="high"):
    return {
        "date":                     date_str,
        "quality":                  quality_label,
        "reason":                   "test",
        "recheck":                  False,
        "attempts":                 0,
        "write":                    True,
        "source":                   "api",
        "last_checked":             date_str,
        "last_attempt":             None,
        "validator_result":         "ok",
        "validator_schema_version": "1.0",
        "validator_issues":         [],
        "fields":                   {},
        "device_id":                None,
        "device_name":              "",
    }

_patched_result = ("high", {}, {}, {}, {"status": "ok", "issues": []})

# ── 1. No-Op: GARMIN_SYNC_DATES leer → keine Candidates ─────────────────────
_qd_empty = {"first_day": "2024-01-01", "devices": [], "days": []}
with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("GARMIN_SYNC_DATES", None)
    import importlib as _il
    import garmin_config as _cfg_tmp
    _il.reload(_cfg_tmp)
    _mock_client_noop = MagicMock()
    collector_bf._run_source_backfill(_mock_client_noop, _qd_empty)
check("backfill: empty SYNC_DATES → no fetch",
      _mock_client_noop.call_count == 0)

# ── 2. Fetch: GARMIN_SYNC_DATES gesetzt → _fetch_and_assess aufgerufen ───────
_fetch_date = (date.today() - _timedelta(days=30)).isoformat()
_qd_fetch = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_fetch_date),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _fetch_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      return_value=_patched_result) as mock_faa:
        collector_bf._run_source_backfill(MagicMock(), _qd_fetch)
check("backfill: SYNC_DATES set → _fetch_and_assess called",
      mock_faa.call_count == 1)
check("backfill: _fetch_and_assess called with correct date",
      mock_faa.call_args[0][1] == _fetch_date)

# ── 3. Stop-Event wird respektiert ──────────────────────────────────────────
import threading as _threading
_stop_date1 = (date.today() - _timedelta(days=20)).isoformat()
_stop_date2 = (date.today() - _timedelta(days=21)).isoformat()
_sync_two   = f"{_stop_date1},{_stop_date2}"

_qd_stop = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stop_date1),
    _make_api_entry(_stop_date2),
]}

_ev = _threading.Event()
_ev.set()
collector_bf.set_stop_event(_ev)

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _sync_two}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      return_value=_patched_result) as mock_stop:
        collector_bf._run_source_backfill(MagicMock(), _qd_stop)

check("backfill: stop event set → fetch loop aborted (0 or 1 calls)",
      mock_stop.call_count <= 1)
collector_bf.set_stop_event(None)

# ── 4. Fehler pro Tag → kein Crash, Loop läuft weiter ───────────────────────
_err_date1 = (date.today() - _timedelta(days=40)).isoformat()
_err_date2 = (date.today() - _timedelta(days=41)).isoformat()
_sync_err  = f"{_err_date1},{_err_date2}"

_qd_err = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_err_date1),
    _make_api_entry(_err_date2),
]}

def _raise_on_first(client, date_str):
    if date_str == _err_date1:
        raise RuntimeError("simulated API error")
    return _patched_result

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _sync_err}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      side_effect=_raise_on_first):
        try:
            collector_bf._run_source_backfill(MagicMock(), _qd_err)
            check("backfill: per-day error → no crash, loop continues", True)
        except Exception:
            check("backfill: per-day error → no crash, loop continues", False)

# ── reload cfg zurücksetzen ──────────────────────────────────────────────────
os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ══════════════════════════════════════════════════════════════════════════════
#  E2. _run_steps_backfill
# ══════════════════════════════════════════════════════════════════════════════
section("E2. _run_steps_backfill")

_stb_patched_steps = [{"startGMT": "2024-01-01T08:00:00", "steps": 42}]

# ── 1. No-Op: GARMIN_SYNC_DATES leer → keine Candidates ─────────────────────
_qd_stb_empty = {"first_day": "2024-01-01", "devices": [], "days": []}
with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("GARMIN_SYNC_DATES", None)
    _il.reload(_cfg_tmp)
    _mock_client_stb_noop = MagicMock()
    with patch.object(collector_bf.api, "api_call") as mock_stb_noop:
        collector_bf._run_steps_backfill(_mock_client_stb_noop, _qd_stb_empty)
check("steps_backfill: empty SYNC_DATES → no fetch",
      mock_stb_noop.call_count == 0)

# ── 2. Enrichment: SYNC_DATES gesetzt → Tag wird angereichert ───────────────
_stb_fetch_date = (date.today() - _timedelta(days=30)).isoformat()
_stb_raw = {"date": _stb_fetch_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
writer.write_day(_stb_raw, normalizer.summarize(_stb_raw), _stb_fetch_date)

_qd_stb_fetch = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_fetch_date),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_fetch_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)) as mock_stb_call:
        collector_bf._run_steps_backfill(MagicMock(), _qd_stb_fetch)

check("steps_backfill: SYNC_DATES set → api_call invoked once",
      mock_stb_call.call_count == 1)
check("steps_backfill: api_call requested get_steps_data",
      mock_stb_call.call_args[0][1] == "get_steps_data")
check("steps_backfill: api_call requested correct date",
      mock_stb_call.call_args[0][2] == _stb_fetch_date)

_stb_raw_after = writer.read_raw(_stb_fetch_date)
check("steps_backfill: steps merged into raw/",
      _stb_raw_after.get("steps") == _stb_patched_steps)
check("steps_backfill: existing field preserved",
      _stb_raw_after.get("heart_rates", {}).get("heartRateValues") == [[0, 60]])

_stb_entry_after = next(
    (e for e in _qd_stb_fetch["days"] if e.get("date") == _stb_fetch_date), None
)
check("steps_backfill: backfilled_fields recorded",
      _stb_entry_after is not None and
      "steps" in (_stb_entry_after.get("backfilled_fields") or {}))
check("steps_backfill: fields dict includes steps",
      _stb_entry_after is not None and
      _stb_entry_after.get("fields", {}).get("steps") == "high")

# ── 3. Stop-Event wird respektiert ──────────────────────────────────────────
_stb_stop_date1 = (date.today() - _timedelta(days=50)).isoformat()
_stb_stop_date2 = (date.today() - _timedelta(days=51)).isoformat()
_stb_sync_two   = f"{_stb_stop_date1},{_stb_stop_date2}"

_qd_stb_stop = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_stop_date1),
    _make_api_entry(_stb_stop_date2),
]}

_stb_ev = _threading.Event()
_stb_ev.set()
collector_bf.set_stop_event(_stb_ev)

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_sync_two}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)) as mock_stb_stop:
        collector_bf._run_steps_backfill(MagicMock(), _qd_stb_stop)

check("steps_backfill: stop event set → loop aborted (0 calls)",
      mock_stb_stop.call_count == 0)
collector_bf.set_stop_event(None)

# ── 4. Fehler pro Tag → kein Crash, Loop läuft weiter ───────────────────────
_stb_err_date1 = (date.today() - _timedelta(days=60)).isoformat()
_stb_err_date2 = (date.today() - _timedelta(days=61)).isoformat()
_stb_sync_err  = f"{_stb_err_date1},{_stb_err_date2}"

# raw/ muss existieren, sonst greift der frühere "keine raw/-Datei"-Zweig
# zuerst und der hier eigentlich getestete except-Exception-Pfad (über den
# gemockten api_call unten) wird nie erreicht.
for _d in (_stb_err_date1, _stb_err_date2):
    _stb_err_raw = {"date": _d, "heart_rates": {"heartRateValues": [[0, 60]]}}
    writer.write_day(_stb_err_raw, normalizer.summarize(_stb_err_raw), _d)

_qd_stb_err = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_err_date1),
    _make_api_entry(_stb_err_date2),
]}

def _stb_raise_on_first(client, method, date_str, label=None):
    if date_str == _stb_err_date1:
        raise RuntimeError("simulated API error")
    return (_stb_patched_steps, True)

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_sync_err}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      side_effect=_stb_raise_on_first):
        try:
            collector_bf._run_steps_backfill(MagicMock(), _qd_stb_err)
            check("steps_backfill: per-day error → no crash, loop continues", True)
        except Exception:
            check("steps_backfill: per-day error → no crash, loop continues", False)

_stb_err_entry1 = next(e for e in _qd_stb_err["days"] if e["date"] == _stb_err_date1)
_stb_err_entry2 = next(e for e in _qd_stb_err["days"] if e["date"] == _stb_err_date2)
check("steps_backfill: except-Exception path increments field_backfill_attempts.steps",
      _stb_err_entry1.get("field_backfill_attempts", {}).get("steps") == 1)
check("steps_backfill: successful day has no field_backfill_attempts entry",
      "field_backfill_attempts" not in _stb_err_entry2)

# ── reload cfg zurücksetzen ──────────────────────────────────────────────────
os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── 4b. write_day() liefert False → vierter Fehlerpfad, erst jetzt ─────────
#       nachgerüstet (war beim ursprünglichen Baustein-2-Fix übersehen worden,
#       symmetrisch zum bereits korrekt behandelten Fall in
#       _run_bulk_field_backfill()) — zählt jetzt ebenfalls den Attempt.
_stb_wd_date = (date.today() - _timedelta(days=71)).isoformat()
_stb_wd_raw  = {"date": _stb_wd_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
writer.write_day(_stb_wd_raw, normalizer.summarize(_stb_wd_raw), _stb_wd_date)

_qd_stb_wd = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_wd_date),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_wd_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)), \
         patch.object(collector_bf.writer, "write_day", return_value=False):
        collector_bf._run_steps_backfill(MagicMock(), _qd_stb_wd)

_stb_wd_entry = next(e for e in _qd_stb_wd["days"] if e["date"] == _stb_wd_date)
check("steps_backfill: write_day failure path increments field_backfill_attempts.steps",
      _stb_wd_entry.get("field_backfill_attempts", {}).get("steps") == 1)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ── 4c. record_attempt() silently blocked by _upsert_quality()'s day-level ──
#       downgrade guard even though write_day() succeeded (Netz-2 tool finding,
#       "steps_async"). Stored entry already claims "high" (e.g. an
#       already-inconsistent archive state); the merged raw here has nothing
#       else, so its freshly assessed day-level label is "failed" — lower
#       rank than the stored one, so _upsert_quality() returns before setting
#       fields/backfilled_fields at all. The post-check added alongside this
#       test must still count it as a failed attempt so the give-up limit
#       eventually applies instead of retrying the day forever.
_stb_dg_date = (date.today() - _timedelta(days=72)).isoformat()
_stb_dg_raw  = {"date": _stb_dg_date}
writer.write_day(_stb_dg_raw, normalizer.summarize(_stb_dg_raw), _stb_dg_date)

_qd_stb_dg = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_dg_date, quality_label="high"),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_dg_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)):
        collector_bf._run_steps_backfill(MagicMock(), _qd_stb_dg)

_stb_dg_raw_after = writer.read_raw(_stb_dg_date)
check("steps_backfill downgrade-guard: steps still written to raw/ despite blocked quality_log update",
      _stb_dg_raw_after.get("steps") == _stb_patched_steps)

_stb_dg_entry = next(e for e in _qd_stb_dg["days"] if e["date"] == _stb_dg_date)
check("steps_backfill downgrade-guard: quality_log entry left blocked (fields.steps not 'high')",
      _stb_dg_entry.get("quality") == "high" and
      _stb_dg_entry.get("fields", {}).get("steps") != "high")
check("steps_backfill downgrade-guard: field_backfill_attempts.steps still incremented",
      _stb_dg_entry.get("field_backfill_attempts", {}).get("steps") == 1)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ── 5. get_steps_data returns success=False → attempt counter increments ───
# (explicit failure branch, distinct from the except-Exception path above),
# and after FIELD_BACKFILL_ATTEMPT_LIMIT real failures the day drops out of
# timer_run_steps_backfill()'s own candidate list.
_stb_gu_date = (date.today() - _timedelta(days=70)).isoformat()
_stb_gu_raw  = {"date": _stb_gu_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
writer.write_day(_stb_gu_raw, normalizer.summarize(_stb_gu_raw), _stb_gu_date)

_qd_stb_gu = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_stb_gu_date),
]}
quality._save_quality_log(_qd_stb_gu, skip_backup=True)

for _n in (1, 2):
    with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _stb_gu_date}):
        _il.reload(_cfg_tmp)
        with patch.object(collector_bf.api, "api_call",
                          return_value=(None, False)):
            collector_bf._run_steps_backfill(MagicMock(), _qd_stb_gu)
    _stb_gu_entry = next(e for e in _qd_stb_gu["days"] if e["date"] == _stb_gu_date)
    check(f"steps_backfill give-up: success=False path — attempts == {_n} after fail #{_n}",
          _stb_gu_entry.get("field_backfill_attempts", {}).get("steps") == _n)

quality._save_quality_log(_qd_stb_gu, skip_backup=True)

_app_dir_gu = str(Path(__file__).parent.parent / "app")
if _app_dir_gu not in sys.path:
    sys.path.insert(0, _app_dir_gu)
import garmin_app_controller as controller_gu

_stb_gu_candidates = controller_gu.timer_run_steps_backfill({"base_dir": str(_TMPDIR)})
_stb_gu_still_candidate = (
    _stb_gu_candidates is not None
    and date.fromisoformat(_stb_gu_date) in _stb_gu_candidates
)
check("steps_backfill give-up: day excluded once attempts reach FIELD_BACKFILL_ATTEMPT_LIMIT",
      not _stb_gu_still_candidate)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ══════════════════════════════════════════════════════════════════════════════
#  E3. Steps-Backfill — Silo-Async-Zustand (Priorität 2 Punkt 2)
# ══════════════════════════════════════════════════════════════════════════════
section("E3. Steps-Backfill — Silo-Async-Zustand (Punkt 2)")

import fixtures_netz2 as fx_netz2

# ── Gutfall: patch_source_field() gelingt ───────────────────────────────────
_e3_ok_date = (date.today() - _timedelta(days=90)).isoformat()
_e3_raw_ok  = {"date": _e3_ok_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
writer.write_day(_e3_raw_ok, normalizer.summarize(_e3_raw_ok), _e3_ok_date)
fx_netz2.write_source_file(cfg.SOURCE_DIR, _e3_ok_date, dict(_e3_raw_ok))

_qd_e3_ok = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_e3_ok_date),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e3_ok_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)):
        with patch.object(collector_bf.log, "error") as mock_e3_ok_err:
            collector_bf._run_steps_backfill(MagicMock(), _qd_e3_ok)

check("silo_async Gutfall: raw/ hat steps",
      writer.read_raw(_e3_ok_date).get("steps") == _stb_patched_steps)
_e3_ok_source_after = json.loads(
    (cfg.SOURCE_DIR / f"garmin_source_{_e3_ok_date}.json").read_text(encoding="utf-8"))
check("silo_async Gutfall: source/ hat steps",
      _e3_ok_source_after.get("steps") == _stb_patched_steps)
check("silo_async Gutfall: kein ERROR-Log",
      mock_e3_ok_err.call_count == 0)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── Schlechtfall: source/ vorhanden, aber korrupt (JSONDecodeError-Pfad) ────
_e3_bad_date = (date.today() - _timedelta(days=91)).isoformat()
_e3_raw_bad  = {"date": _e3_bad_date, "heart_rates": {"heartRateValues": [[0, 61]]}}
writer.write_day(_e3_raw_bad, normalizer.summarize(_e3_raw_bad), _e3_bad_date)
fx_netz2.write_corrupt_source_file(cfg.SOURCE_DIR, _e3_bad_date)
_e3_corrupt_before = (cfg.SOURCE_DIR / f"garmin_source_{_e3_bad_date}.json").read_text(encoding="utf-8")

_qd_e3_bad = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_e3_bad_date),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e3_bad_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)):
        with patch.object(collector_bf.log, "warning") as mock_e3_bad_warn, \
             patch.object(collector_bf.log, "error")   as mock_e3_bad_err:
            collector_bf._run_steps_backfill(MagicMock(), _qd_e3_bad)

check("silo_async Schlechtfall: raw/ hat steps trotz source/-Fehlschlag",
      writer.read_raw(_e3_bad_date).get("steps") == _stb_patched_steps)
check("silo_async Schlechtfall: source/ bleibt unverändert (weiterhin korrupt)",
      (cfg.SOURCE_DIR / f"garmin_source_{_e3_bad_date}.json").read_text(encoding="utf-8")
      == _e3_corrupt_before)
check("silo_async Schlechtfall: WARNING beim ersten Fehlschlag ('retrying once')",
      any("retrying once" in str(c) for c in mock_e3_bad_warn.call_args_list))
check("silo_async Schlechtfall: ERROR nach Retry-Erschöpfung ('permanently out of sync')",
      any("permanently out of sync" in str(c) for c in mock_e3_bad_err.call_args_list))

_e3_bad_entry = next(
    (e for e in _qd_e3_bad["days"] if e.get("date") == _e3_bad_date), None
)
check("silo_async Schlechtfall: fields['steps']='high' trotz source/-Fehlschlag",
      _e3_bad_entry is not None and _e3_bad_entry.get("fields", {}).get("steps") == "high")
check("silo_async Schlechtfall: backfilled_fields enthält 'steps' trotz source/-Fehlschlag",
      _e3_bad_entry is not None and "steps" in (_e3_bad_entry.get("backfilled_fields") or {}))

# ── Zweiter Lauf: echter Controller-Kandidatenfilter liefert den Tag nicht erneut ──
quality._save_quality_log(_qd_e3_bad, skip_backup=True)

_app_dir_e3 = str(Path(__file__).parent.parent / "app")
if _app_dir_e3 not in sys.path:
    sys.path.insert(0, _app_dir_e3)
import garmin_app_controller as controller_e3

_e3_candidates_after = controller_e3.timer_run_steps_backfill({"base_dir": str(_TMPDIR)})
_e3_still_candidate = (
    _e3_candidates_after is not None
    and date.fromisoformat(_e3_bad_date) in _e3_candidates_after
)
check("silo_async: Kandidatenfilter liefert den asynchronen Tag nicht erneut (dauerhaft)",
      not _e3_still_candidate)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ══════════════════════════════════════════════════════════════════════════════
#  E4. Abbruch-Atomarität — Steps-/Source-Backfill (Priorität 2 Punkt 3)
# ══════════════════════════════════════════════════════════════════════════════
section("E4. Abbruch-Atomarität — Steps-/Source-Backfill (Punkt 3)")

# Mechanismus (siehe NETZ2_BEFUND_stop_abort_v1658_02.md): Stop-Event wird als
# Seiteneffekt des gemockten API-Aufrufs für Tag 1 gesetzt — Tag 1s eigener
# _is_stopped()-Check liegt zu diesem Zeitpunkt bereits dahinter, läuft also
# normal durch. Erst der Iterationsstart für Tag 2 sieht das gesetzte Event
# und bricht davor ab. Tag 3 bleibt dadurch ebenfalls unberührt.

_app_dir_e4 = str(Path(__file__).parent.parent / "app")
if _app_dir_e4 not in sys.path:
    sys.path.insert(0, _app_dir_e4)
import garmin_app_controller as controller_e4

# ── E4a. Steps-Backfill ──────────────────────────────────────────────────────
_e4stb_d1 = (date.today() - _timedelta(days=102)).isoformat()
_e4stb_d2 = (date.today() - _timedelta(days=101)).isoformat()
_e4stb_d3 = (date.today() - _timedelta(days=100)).isoformat()
_e4stb_sync = f"{_e4stb_d1},{_e4stb_d2},{_e4stb_d3}"

for _d in (_e4stb_d1, _e4stb_d2, _e4stb_d3):
    _e4stb_raw = {"date": _d, "heart_rates": {"heartRateValues": [[0, 60]]}}
    writer.write_day(_e4stb_raw, normalizer.summarize(_e4stb_raw), _d)

_qd_e4stb = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_e4stb_d1),
    _make_api_entry(_e4stb_d2),
    _make_api_entry(_e4stb_d3),
]}
_e4stb_entry_d2_before = json.loads(json.dumps(
    next(e for e in _qd_e4stb["days"] if e["date"] == _e4stb_d2)))
_e4stb_entry_d3_before = json.loads(json.dumps(
    next(e for e in _qd_e4stb["days"] if e["date"] == _e4stb_d3)))

_e4stb_stop_ev = _threading.Event()

def _e4stb_side_effect(client, method, date_str, label=None):
    if date_str == _e4stb_d1:
        _e4stb_stop_ev.set()
    return (_stb_patched_steps, True)

collector_bf.set_stop_event(_e4stb_stop_ev)
with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e4stb_sync}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      side_effect=_e4stb_side_effect):
        collector_bf._run_steps_backfill(MagicMock(), _qd_e4stb)
collector_bf.set_stop_event(None)

check("abort steps: Tag 1 vollständig — raw/ hat steps",
      writer.read_raw(_e4stb_d1).get("steps") == _stb_patched_steps)
check("abort steps: Tag 2 (Abbruchpunkt) — raw/ unverändert",
      writer.read_raw(_e4stb_d2).get("steps") is None)
check("abort steps: Tag 3 — raw/ unverändert",
      writer.read_raw(_e4stb_d3).get("steps") is None)

_e4stb_entry_d2_after = next(e for e in _qd_e4stb["days"] if e["date"] == _e4stb_d2)
_e4stb_entry_d3_after = next(e for e in _qd_e4stb["days"] if e["date"] == _e4stb_d3)
check("abort steps: Tag 2 quality_log-Eintrag byte-identisch zum Ausgangszustand",
      _e4stb_entry_d2_after == _e4stb_entry_d2_before)
check("abort steps: Tag 3 quality_log-Eintrag byte-identisch zum Ausgangszustand",
      _e4stb_entry_d3_after == _e4stb_entry_d3_before)

try:
    json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
    check("abort steps: quality_log.json nach Abbruch valide (kein Parse-Fehler)", True)
except Exception:
    check("abort steps: quality_log.json nach Abbruch valide (kein Parse-Fehler)", False)

# ── zweiter, ungestörter Lauf — echter Controller-Kandidatenfilter ──────────
_e4stb_candidates = controller_e4.timer_run_steps_backfill({"base_dir": str(_TMPDIR)})
check("abort steps: Lauf 2 — Kandidatenliste enthält genau die zwei verbliebenen Tage",
      _e4stb_candidates is not None and
      set(_e4stb_candidates) == {date.fromisoformat(_e4stb_d2), date.fromisoformat(_e4stb_d3)})

_e4stb_sync2 = ",".join(d.isoformat() for d in (_e4stb_candidates or []))
with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e4stb_sync2}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "api_call",
                      return_value=(_stb_patched_steps, True)):
        collector_bf._run_steps_backfill(MagicMock(), _qd_e4stb)

check("abort steps: Lauf 2 — Tag 2 nachgeholt",
      writer.read_raw(_e4stb_d2).get("steps") == _stb_patched_steps)
check("abort steps: Lauf 2 — Tag 3 nachgeholt",
      writer.read_raw(_e4stb_d3).get("steps") == _stb_patched_steps)

quality._save_quality_log(_qd_e4stb, skip_backup=True)
_e4stb_candidates_final = controller_e4.timer_run_steps_backfill({"base_dir": str(_TMPDIR)})
check("abort steps: Lauf 2 — Kandidatenliste danach leer",
      _e4stb_candidates_final is None)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── E4b. Source-Backfill ─────────────────────────────────────────────────────
_e4src_d1 = (date.today() - _timedelta(days=112)).isoformat()
_e4src_d2 = (date.today() - _timedelta(days=111)).isoformat()
_e4src_d3 = (date.today() - _timedelta(days=110)).isoformat()
_e4src_sync = f"{_e4src_d1},{_e4src_d2},{_e4src_d3}"

_qd_e4src = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_api_entry(_e4src_d1),
    _make_api_entry(_e4src_d2),
    _make_api_entry(_e4src_d3),
]}
_e4src_entry_d2_before = json.loads(json.dumps(
    next(e for e in _qd_e4src["days"] if e["date"] == _e4src_d2)))
_e4src_entry_d3_before = json.loads(json.dumps(
    next(e for e in _qd_e4src["days"] if e["date"] == _e4src_d3)))

_e4src_stop_ev = _threading.Event()

def _e4src_fetch_raw_side_effect(client, date_str, extra_endpoints=None):
    _e4src_raw = {"date": date_str, "heart_rates": {"heartRateValues": [[0, 60], [60000, 62]]}}
    if date_str == _e4src_d1:
        _e4src_stop_ev.set()
    return _e4src_raw, []

collector_bf.set_stop_event(_e4src_stop_ev)
with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e4src_sync}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "fetch_raw",
                      side_effect=_e4src_fetch_raw_side_effect):
        collector_bf._run_source_backfill(MagicMock(), _qd_e4src)
collector_bf.set_stop_event(None)

check("abort source: Tag 1 vollständig — source/ geschrieben",
      (cfg.SOURCE_DIR / f"garmin_source_{_e4src_d1}.json").exists())
check("abort source: Tag 2 (Abbruchpunkt) — source/ NICHT geschrieben",
      not (cfg.SOURCE_DIR / f"garmin_source_{_e4src_d2}.json").exists())
check("abort source: Tag 3 — source/ NICHT geschrieben",
      not (cfg.SOURCE_DIR / f"garmin_source_{_e4src_d3}.json").exists())

_e4src_entry_d2_after = next(e for e in _qd_e4src["days"] if e["date"] == _e4src_d2)
_e4src_entry_d3_after = next(e for e in _qd_e4src["days"] if e["date"] == _e4src_d3)
check("abort source: Tag 2 quality_log-Eintrag byte-identisch zum Ausgangszustand",
      _e4src_entry_d2_after == _e4src_entry_d2_before)
check("abort source: Tag 3 quality_log-Eintrag byte-identisch zum Ausgangszustand",
      _e4src_entry_d3_after == _e4src_entry_d3_before)

try:
    json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
    check("abort source: quality_log.json nach Abbruch valide (kein Parse-Fehler)", True)
except Exception:
    check("abort source: quality_log.json nach Abbruch valide (kein Parse-Fehler)", False)

# ── zweiter, ungestörter Lauf ────────────────────────────────────────────────
_e4src_candidates = controller_e4.timer_run_source_backfill({"base_dir": str(_TMPDIR)})
check("abort source: Lauf 2 — Kandidatenliste enthält genau die zwei verbliebenen Tage",
      _e4src_candidates is not None and
      set(_e4src_candidates) == {date.fromisoformat(_e4src_d2), date.fromisoformat(_e4src_d3)})

def _e4src_fetch_raw_undisturbed(client, date_str, extra_endpoints=None):
    return {"date": date_str, "heart_rates": {"heartRateValues": [[0, 60], [60000, 62]]}}, []

_e4src_sync2 = ",".join(d.isoformat() for d in (_e4src_candidates or []))
with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _e4src_sync2}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf.api, "fetch_raw",
                      side_effect=_e4src_fetch_raw_undisturbed):
        collector_bf._run_source_backfill(MagicMock(), _qd_e4src)

check("abort source: Lauf 2 — Tag 2 nachgeholt",
      (cfg.SOURCE_DIR / f"garmin_source_{_e4src_d2}.json").exists())
check("abort source: Lauf 2 — Tag 3 nachgeholt",
      (cfg.SOURCE_DIR / f"garmin_source_{_e4src_d3}.json").exists())

quality._save_quality_log(_qd_e4src, skip_backup=True)
_e4src_candidates_final = controller_e4.timer_run_source_backfill({"base_dir": str(_TMPDIR)})
check("abort source: Lauf 2 — Kandidatenliste danach leer",
      _e4src_candidates_final is None)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ══════════════════════════════════════════════════════════════════════════════
#  E5. _run_bulk_field_backfill
# ══════════════════════════════════════════════════════════════════════════════
section("E5. _run_bulk_field_backfill")

def _make_bulk_entry(date_str, quality_label="standard", fields=None):
    return {
        "date": date_str, "quality": quality_label, "reason": "t", "recheck": False,
        "attempts": 0, "write": True, "source": "bulk", "last_checked": date_str,
        "last_attempt": None, "validator_result": "ok", "validator_schema_version": "1.0",
        "validator_issues": [], "fields": fields if fields is not None else {"heart_rates": "medium"},
        "device_id": None, "device_name": "",
    }

# ── 1. No-Op: GARMIN_SYNC_DATES leer → keine Candidates ─────────────────────
_qd_bfb_empty = {"first_day": "2024-01-01", "devices": [], "days": []}
with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("GARMIN_SYNC_DATES", None)
    _il.reload(_cfg_tmp)
    _mock_client_bfb_noop = MagicMock()
    with patch.object(collector_bf, "_fetch_and_assess") as mock_bfb_noop:
        collector_bf._run_bulk_field_backfill(_mock_client_bfb_noop, _qd_bfb_empty)
check("bulk_field_backfill: empty SYNC_DATES → no fetch",
      mock_bfb_noop.call_count == 0)

# ── 2. Additiver Merge — der eigentliche Regressions-Fix: ein Feld, das ─────
#      Bulk schon (in eigener Roh-Form) befüllt hatte, darf beim Re-Fetch ──
#      NIE überschrieben werden, selbst wenn der neue Wert "anders" ist. ───
#      Ein Feld, das Bulk nie hatte, wird additiv aufgefüllt. ──────────────
_bfb_date1 = (date.today() - _timedelta(days=900)).isoformat()

_bfb_old_stress = {"averageStressLevel": 31, "restDuration": 36900}  # bulk-shaped
_bfb_existing_raw = {
    "date": _bfb_date1,
    "stress": _bfb_old_stress,
    "heart_rates": {"restingHeartRate": 60},
    # user_summary/stats.totalSteps or restingHeartRate is what
    # assess_quality() actually reads for the day-level "standard" label —
    # without this the merged day would assess as "failed" and
    # _upsert_quality()'s own downgrade guard would (correctly) block the
    # whole quality_log update, same as it would for a too-sparse real day.
    "user_summary": {"totalSteps": 2354, "restingHeartRate": 60},
}
writer.write_day(_bfb_existing_raw, normalizer.summarize(_bfb_existing_raw), _bfb_date1)

_bfb_fresh_normalized = {
    "date": _bfb_date1,
    "stress": {"averageStressLevel": 27, "restStressDuration": 43200},  # api-shaped, DIFFERENT
    "spo2": {"averageSpO2": 95, "lowestSpO2": 90},                      # bulk never had this
    "hrv": {},                                                          # bulk never had this, but empty
}
_bfb_patched_result = ("standard", _bfb_fresh_normalized, {}, {}, {"status": "ok", "issues": []})

_qd_bfb1 = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_bulk_entry(_bfb_date1),
]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _bfb_date1}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      return_value=_bfb_patched_result) as mock_bfb1:
        collector_bf._run_bulk_field_backfill(MagicMock(), _qd_bfb1)

check("bulk_field_backfill: _fetch_and_assess called once",
      mock_bfb1.call_count == 1)
check("bulk_field_backfill: _fetch_and_assess called with correct date",
      mock_bfb1.call_args[0][1] == _bfb_date1)

_bfb1_raw_after = writer.read_raw(_bfb_date1)
check("bulk_field_backfill: existing non-empty field (stress) is NEVER overwritten by the fresh fetch",
      _bfb1_raw_after.get("stress") == _bfb_old_stress)
check("bulk_field_backfill: field bulk never had (spo2) gets merged in from the fresh fetch",
      _bfb1_raw_after.get("spo2") == _bfb_fresh_normalized["spo2"])
check("bulk_field_backfill: field not touched by the fresh fetch (heart_rates) stays as-is",
      _bfb1_raw_after.get("heart_rates") == {"restingHeartRate": 60})

_bfb1_entry = next(e for e in _qd_bfb1["days"] if e["date"] == _bfb_date1)
check("bulk_field_backfill: source updated to api",
      _bfb1_entry.get("source") == "api")
check("bulk_field_backfill: quality_log fields reflect the merged (not the raw fresh) result — "
      "spo2 improves from bulk's 'failed' (never had it) to 'medium' (aggregate now present)",
      _bfb1_entry.get("fields", {}).get("spo2") == "medium")
check("bulk_field_backfill: spo2 not yet 'high' (no intraday) → still gets an attempt recorded "
      "(correctly stays eligible for a future attempt, not yet given up on)",
      _bfb1_entry.get("field_backfill_attempts", {}).get("spo2") == 1)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── 2b. Batching: mehrere offene Lücken-Felder → genau EIN Aufruf von ──────
#       record_field_backfill_failures(), nicht einer pro Feld (Fix nach
#       Live-Lauf: 7-8 redundante quality_log-Saves/Backups pro Tag beobachtet)
_bfb_date1b = (date.today() - _timedelta(days=903)).isoformat()
_qd_bfb1b = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_bulk_entry(_bfb_date1b),
]}
# Kein existing raw/ — alles wird additiv aus dem Fetch übernommen, die
# meisten Lücken-Felder bleiben trotzdem "failed" (leere/keine Nutzdaten
# in _bfb_fresh_normalized für hrv/body_battery/respiration/training_status/
# race_predictions/max_metrics).

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _bfb_date1b}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      return_value=_bfb_patched_result), \
         patch.object(collector_bf.quality, "record_field_backfill_failures",
                      side_effect=quality.record_field_backfill_failures) as mock_plural, \
         patch.object(collector_bf.quality, "record_field_backfill_failure") as mock_singular:
        collector_bf._run_bulk_field_backfill(MagicMock(), _qd_bfb1b)

check("bulk_field_backfill: batches all open gap fields into one record_field_backfill_failures() call",
      mock_plural.call_count == 1)
check("bulk_field_backfill: never calls the singular record_field_backfill_failure()",
      mock_singular.call_count == 0)
check("bulk_field_backfill: batched call covers several still-open gap fields",
      len(mock_plural.call_args[0][2]) >= 5)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── 3. Bereits-hohe Lücken-Felder bleiben unverändert (kein neuer Versuch), ──
#      auch wenn der frische Fetch für dasselbe Feld einen anderen Wert ─────
#      liefert — additiver Merge lässt "high"-Felder unangetastet. ──────────
_bfb_date2 = (date.today() - _timedelta(days=901)).isoformat()

_bfb_old_spo2 = {"averageSpO2": 98, "lowestSpO2": 95, "spO2SingleValues": [[0, 98]]}
_bfb_existing_raw2 = {"date": _bfb_date2, "spo2": _bfb_old_spo2}
writer.write_day(_bfb_existing_raw2, normalizer.summarize(_bfb_existing_raw2), _bfb_date2)

_qd_bfb2 = {"first_day": "2024-01-01", "devices": [], "days": [
    _make_bulk_entry(_bfb_date2, quality_label="high",
                     fields={"spo2": "high"}),
]}

_bfb_fresh2 = ("standard", {"date": _bfb_date2, "spo2": {"averageSpO2": 50}}, {}, {},
               {"status": "ok", "issues": []})

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _bfb_date2}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess", return_value=_bfb_fresh2):
        collector_bf._run_bulk_field_backfill(MagicMock(), _qd_bfb2)

_bfb2_raw_after = writer.read_raw(_bfb_date2)
check("bulk_field_backfill: already-populated gap field (spo2) is never overwritten either",
      _bfb2_raw_after.get("spo2") == _bfb_old_spo2)

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)

# ── 4. Fehler pro Tag → kein Crash, Attempts trotzdem für offene Felder ──────
_bfb_err_date  = (date.today() - _timedelta(days=902)).isoformat()
_bfb_err_entry = _make_bulk_entry(
    _bfb_err_date, fields={"heart_rates": "medium", "hrv": "failed"})
_qd_bfb_err = {"first_day": "2024-01-01", "devices": [], "days": [_bfb_err_entry]}

with patch.dict(os.environ, {"GARMIN_SYNC_DATES": _bfb_err_date}):
    _il.reload(_cfg_tmp)
    with patch.object(collector_bf, "_fetch_and_assess",
                      side_effect=RuntimeError("simulated API error")):
        try:
            collector_bf._run_bulk_field_backfill(MagicMock(), _qd_bfb_err)
            check("bulk_field_backfill: per-day error → no crash, loop continues", True)
        except Exception:
            check("bulk_field_backfill: per-day error → no crash, loop continues", False)

_bfb_err_after = next(e for e in _qd_bfb_err["days"] if e["date"] == _bfb_err_date)
check("bulk_field_backfill: except-Exception path records attempts for all still-open gap fields",
      all(_bfb_err_after.get("field_backfill_attempts", {}).get(f) == 1
          for f in collector_bf.BULK_GAP_FIELDS))

os.environ.pop("GARMIN_SYNC_DATES", None)
_il.reload(_cfg_tmp)


# ══════════════════════════════════════════════════════════════════════════════
#  16. _run_self_healing
# ══════════════════════════════════════════════════════════════════════════════
section("16. _run_self_healing")

import garmin_collector as collector_sh
import garmin_writer    as writer_sh
import garmin_normalizer as normalizer_sh

# Hilfsfunktion: synthetischen Quality-Eintrag bauen
def _make_entry(date_str, validator_result, schema_version, quality_label="high"):
    return {
        "date":                    date_str,
        "quality":                 quality_label,
        "reason":                  "test",
        "recheck":                 False,
        "attempts":                0,
        "write":                   True,
        "source":                  "api",
        "last_checked":            date_str,
        "last_attempt":            None,
        "validator_result":        validator_result,
        "validator_schema_version": schema_version,
        "validator_issues":        [],
        "fields":                  {},
    }

_current_ver = collector_sh.validator.current_version()

# 1. Kein Kandidat (Schema-Version stimmt überein) → nichts geändert
qd_no_candidate = {
    "first_day": "2024-01-01", "devices": [], "days": [
        _make_entry("2024-01-01", "ok", _current_ver),
    ]
}
collector_sh._run_self_healing(qd_no_candidate)
check("self-healing: no candidate → entry unchanged",
      qd_no_candidate["days"][0]["validator_schema_version"] == _current_ver)

# 2. Kandidat — kein Raw-File → Entry bleibt unverändert, kein Crash
qd_no_raw = {
    "first_day": "2024-01-01", "devices": [], "days": [
        _make_entry("1900-01-01", "warning", "0.9"),
    ]
}
try:
    collector_sh._run_self_healing(qd_no_raw)
    check("self-healing: no raw file → no crash",         True)
except Exception:
    check("self-healing: no raw file → no crash",         False)
check("self-healing: no raw file → entry not modified",
      qd_no_raw["days"][0]["validator_schema_version"] == "0.9")

# 3. Kandidat — Raw-File vorhanden, Status verbessert sich (warning → ok)
_heal_date = "2024-08-01"
_heal_raw  = {
    "date":        _heal_date,
    "heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58},
    "sleep":       {"dailySleepDTO": {"sleepTimeSeconds": 27000}},
}
writer_sh.write_day(_heal_raw, normalizer_sh.summarize(_heal_raw), _heal_date)

qd_improves = {
    "first_day": "2024-01-01", "devices": [], "days": [
        _make_entry(_heal_date, "warning", "0.9", quality_label="medium"),
    ]
}
collector_sh._run_self_healing(qd_improves)
check("self-healing: improved → schema_version updated",
      qd_improves["days"][0]["validator_schema_version"] == _current_ver)
check("self-healing: improved → validator_result updated",
      qd_improves["days"][0]["validator_result"] == "ok")

# 4. Kandidat — Status bleibt gleich (warning → warning) → nur schema_version aktualisiert
_heal_date2 = "2024-08-02"
_heal_raw2  = {"date": _heal_date2, "heart_rates": "corrupted"}
writer_sh.write_day(
    {"date": _heal_date2}, normalizer_sh.summarize({"date": _heal_date2}), _heal_date2
)

qd_same = {
    "first_day": "2024-01-01", "devices": [], "days": [
        _make_entry(_heal_date2, "warning", "0.9", quality_label="medium"),
    ]
}
with patch("garmin_collector.validator.validate",
           return_value={"status": "warning", "issues": [], "schema_version": _current_ver,
                         "timestamp": "2024-01-01T00:00:00"}):
    collector_sh._run_self_healing(qd_same)
check("self-healing: same status → schema_version bumped, quality unchanged",
      qd_same["days"][0]["validator_schema_version"] == _current_ver
      and qd_same["days"][0]["quality"] == "medium")

summary()
