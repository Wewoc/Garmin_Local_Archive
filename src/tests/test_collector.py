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

# The quality log cannot be saved after a day was written. The downgrade guard
# keeps the stored 'high' entry, and the run now counts that day once (saved,
# not also as an error) while still keeping a failure log for it (ROADMAP v1.7.4.4
# point 2 — previously counted as both "saved" and "error" for the same day).
with _isolated_log_env("main_saveerr") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _real_save = quality._save_quality_log

    def _save_fails_per_day(data, skip_backup=False):
        if skip_backup:
            raise OSError("disk full")
        return _real_save(data, skip_backup=skip_backup)

    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}, LOG_FAIL_DIR=_b / "fail"):
        with patch.object(quality, "_save_quality_log", side_effect=_save_fails_per_day):
            _code, _exc, _fetch, _ = _run_main()
        _q = _qdays()
        check("main: a failing save after a written day -> run goes on, no crash",
              _code is None and _exc is None)
        check("main: the written day keeps its stored quality (downgrade blocked)",
              _q["2024-05-01"]["quality"] == "high" and _q["2024-05-01"]["write"] is True
              and (cfg.RAW_DIR / "garmin_raw_2024-05-01.json").exists()
              and (cfg.SUMMARY_DIR / "garmin_2024-05-01.json").exists())
        check("main: a failing save after a written day counts that day once (saved), keeps a failure log",
              len(_fail_logs_with("1 saved, 0 errors")) == 1)

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

# one invalid date in the quality log is skipped with a warning; the sync continues (ROADMAP v1.7.4.4)
with _isolated_log_env("main_baddate") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "not-a-date", "quality": "high", "source": "api", "write": True}]}), encoding="utf-8")
    with _cfg_values(**_RANGE):
        _code, _exc, _fetch, _ = _run_main()
        check("main: an invalid date in the quality log is skipped, the sync goes on",
              _exc is None and _fetch.called)
        check("main: the skipped entry is named in an integrity_warnings entry",
              any("not-a-date" in w for w in quality._load_quality_log().get("integrity_warnings", [])))

# a multi-day run with several valid entries and one unparseable date: the bad
# entry is skipped (named once in integrity_warnings) but left in the log as-is,
# the valid entries are untouched, and the sync still fetches exactly the one
# genuinely missing day (ROADMAP v1.7.4.4 point 1)
with _isolated_log_env("main_baddate_multi") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for _d in ("2024-05-01", "2024-05-02", "2024-05-04", "2024-05-05"):
        (cfg.RAW_DIR / f"garmin_raw_{_d}.json").write_text(json.dumps(_day_raw(_d, "high")), encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"first_day": "2024-05-01", "devices": [], "days": [
        {"date": "not-a-date", "quality": "high", "source": "api", "write": True},
        {"date": "2024-05-01", "quality": "high", "source": "api", "write": True},
        {"date": "2024-05-02", "quality": "high", "source": "api", "write": True},
        {"date": "2024-05-04", "quality": "high", "source": "api", "write": True},
        {"date": "2024-05-05", "quality": "high", "source": "api", "write": True},
    ]}), encoding="utf-8")
    with _cfg_values(**_RANGE):
        _code, _exc, _fetch, _ = _run_main()
        _q = _qdays()
        check("main: a multi-day run with one unparseable date fetches only the genuinely missing day",
              _exc is None and _fetched_dates(_fetch) == ["2024-05-03"])
        check("main: the four valid entries are left exactly as they were",
              all(_q[_d]["quality"] == "high" and _q[_d]["source"] == "api"
                  for _d in ("2024-05-01", "2024-05-02", "2024-05-04", "2024-05-05")))
        check("main: the bad entry itself stays in the log untouched (only skipped when building the date sets)",
              _q.get("not-a-date", {}).get("quality") == "high"
              and _q.get("not-a-date", {}).get("source") == "api")
        check("main: the bad entry is named exactly once in integrity_warnings",
              len([w for w in quality._load_quality_log().get("integrity_warnings", []) if "not-a-date" in w]) == 1)

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

    _real_write_summary_only = _writer5.write_summary_only

    def _write_summary_only_fails_on_05(summary, date_str):
        if date_str == _D6[4]:
            raise OSError("disk full")
        return _real_write_summary_only(summary, date_str)

    with patch.object(_writer5, "write_summary_only", side_effect=_write_summary_only_fails_on_05):
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
    # v1.7.4.5: a migration no longer touches raw/ — no backup copy is created.
    check("schema migration: raw/ is never touched, no raw backup copy appears",
          not (cfg.RAW_BACKUP_DIR / "2024-05" / f"garmin_raw_{_D6[0]}.json").exists())

    with patch.object(_writer5, "write_summary_only") as _wso:
        _col5._run_schema_migration({"days": [{"date": _D6[1]}]})
    check("schema migration: all summaries up to date -> nothing is written", not _wso.called)

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

# ══════════════════════════════════════════════════════════════════════════════
#  4q. garmin_collector — _fetch_and_assess, run_import, session logs
#      (v1.7.4.0.3, Group D1). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4q. garmin_collector — _fetch_and_assess, run_import, session logs")
import garmin_source_writer as _sw11
import garmin_quality as _q11


class _Rec11:
    """Stands in for garmin_collector.log and records (level, message)."""
    def __init__(self):
        self.calls = []
        for _lvl in ("debug", "info", "warning", "error", "critical"):
            setattr(self, _lvl, (lambda lv: lambda msg, *a, **k: self.calls.append((lv, msg)))(_lvl))

    def msgs(self, level):
        return [m for lv, m in self.calls if lv == level]


def _rt11(text):
    """Run-time built copy of a string (not the interned literal, so `is` cannot match by accident)."""
    return "".join(list(text))


_DAY11 = "2024-05-01"
_WARN11 = "⚠"


def _fa11(raw, failed=(), force=None, validate=None, label=None, write_source=True):
    """_fetch_and_assess with fetch_raw, write_source, update_log (and optionally validate / assess_quality)
    replaced. Returns (result, recorder, write_source mock, update_log mock)."""
    rec = _Rec11()
    kw = {} if force is None else {"force": force}
    with patch("garmin_collector.api.fetch_raw", return_value=(raw, list(failed))), \
            patch.object(_sw11, "write_source", return_value=write_source) as ws, \
            patch.object(_sw11, "update_log") as ul, \
            patch.object(_col5, "log", rec), \
            patch.object(_col5.validator, "validate", **({"side_effect": validate} if validate else {"wraps": _col5.validator.validate})), \
            patch.object(_col5.quality, "assess_quality",
                         **({"return_value": label} if label else {"wraps": _col5.quality.assess_quality})):
        res = _col5._fetch_and_assess(MagicMock(), _DAY11, **kw)
    return res, rec, ws, ul


def _val11(status, *issue_types):
    return lambda raw: {"status": status, "issues": [{"type": t} for t in issue_types]}


with _isolated_log_env("fa11") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _HIGH = _day_raw(_DAY11, "high")

    # -- force flag, failed endpoints, write_source result ------------------------------------------------------
    _res, _rec, _ws, _ul = _fa11(_HIGH)
    check("4q fetch_and_assess: force defaults to False and is handed to write_source",
          _ws.call_args.kwargs == {"force": False})
    _res, _rec, _ws, _ul = _fa11(_HIGH, force=True)
    check("4q fetch_and_assess: force=True is handed to write_source", _ws.call_args.kwargs == {"force": True})
    check("4q fetch_and_assess: no failed endpoints -> no warning about them",
          not any("endpoint(s) failed" in m for m in _rec.msgs("warning")))
    _res, _rec, _ws, _ul = _fa11(_HIGH, failed=["get_hrv_data", "get_spo2_data"])
    check("4q fetch_and_assess: failed endpoints are named in one warning",
          f"    {_WARN11} 2 endpoint(s) failed: get_hrv_data, get_spo2_data" in _rec.msgs("warning"))
    _res, _rec, _ws, _ul = _fa11(_HIGH, write_source=False)
    check("4q fetch_and_assess: write_source returning False is logged as an error, True is not",
          f"    source_writer.write_source failed for {_DAY11}" in _rec.msgs("error")
          and _fa11(_HIGH)[1].msgs("error") == [])

    # -- validator critical --------------------------------------------------------------------------------------------
    _RAW = {"date": _DAY11, "stats": {"totalSteps": 5}}
    _crit = _val11(_rt11("critical"))
    _res, _rec, _ws, _ul = _fa11(_RAW, failed=["f1"], validate=_crit)
    check("4q fetch_and_assess: validator critical -> ('failed', None, None, {}, validator result), day skipped",
          _res[:4] == ("failed", None, None, {}) and _res[4]["status"] == "critical"
          and f"    {_WARN11} Validator critical — skipping {_DAY11}" in _rec.msgs("warning"))
    check("4q fetch_and_assess: validator critical -> the source log still gets keys, failed endpoints, exact size, raw data",
          _ul.call_args.args[0] == _DAY11
          and _ul.call_args.kwargs == {"endpoints_fetched": ["date", "stats"], "endpoints_failed": ["f1"],
                                       "size_bytes": len(json.dumps(_RAW).encode()), "raw_data": _RAW})
    _res, _rec, _ws, _ul = _fa11(["not", "a", "dict"], validate=_crit)
    check("4q fetch_and_assess: validator critical with non-dict raw data -> empty keys, size 0, no raw data",
          _res[0] == "failed" and _ul.call_args.kwargs["endpoints_fetched"] == []
          and _ul.call_args.kwargs["size_bytes"] == 0 and _ul.call_args.kwargs["raw_data"] is None)

    # -- any other status is not critical ---------------------------------------------------------------------------
    for _st in ("aaa", "ok", "warning", "zzz"):
        _res, _rec, _ws, _ul = _fa11(_HIGH, validate=_val11(_st))
        check(f"4q fetch_and_assess: validator status {_st!r} is not critical (day is assessed)",
              _res[0] == "high" and _res[1] is not None and not any("Validator critical" in m for m in _rec.msgs("warning")))
    _res, _rec, _ws, _ul = _fa11(_HIGH, failed=["f1"], validate=_val11("ok"))
    check("4q fetch_and_assess: the source log update after the validator carries keys, failed endpoints, exact size, raw data",
          _ul.call_args.kwargs == {"endpoints_fetched": list(_HIGH), "endpoints_failed": ["f1"],
                                   "size_bytes": len(json.dumps(_HIGH).encode()), "raw_data": _HIGH})

    # -- range-warning downgrade ----------------------------------------------------------------------------------------
    _OOR = "out_of_range"
    _DOWN = f"    {_WARN11} 4 out_of_range warnings — quality downgraded: high → standard"
    _lab = {}
    for _name, _issues, _raw, _label in (
            ("3 out_of_range", [_OOR] * 3, _HIGH, None),
            ("2 out_of_range", [_OOR] * 2, _HIGH, None),
            ("2 out_of_range + 2 other", [_OOR] * 2 + ["missing_field"] * 2, _HIGH, None),
            ("4 of a type that sorts after it", ["zzz_type"] * 4, _HIGH, None),
            ("4 out_of_range", [_OOR] * 4, _HIGH, None),
            ("4 run-time built out_of_range", [_rt11(_OOR)] * 4, _HIGH, None),
            ("4 out_of_range, standard day", [_OOR] * 4, {"date": _DAY11, "stats": {"totalSteps": 5}}, None),
            ("4 out_of_range, failed day", [_OOR] * 4, {"date": _DAY11}, None),
            ("4 out_of_range, run-time built 'high'", [_OOR] * 4, _HIGH, _rt11("high"))):
        _res, _rec, _ws, _ul = _fa11(_raw, validate=_val11("warning", *_issues), label=_label)
        _lab[_name] = (_res[0], _DOWN in _rec.msgs("warning"))
    check("4q fetch_and_assess: up to 3 out_of_range warnings, or other issue types, never downgrade",
          _lab["3 out_of_range"] == ("high", False) and _lab["2 out_of_range"] == ("high", False)
          and _lab["2 out_of_range + 2 other"] == ("high", False)
          and _lab["4 of a type that sorts after it"] == ("high", False))
    check("4q fetch_and_assess: 4 out_of_range warnings downgrade 'high' to 'standard' with a warning "
          "(also for run-time built strings)",
          _lab["4 out_of_range"] == ("standard", True) and _lab["4 run-time built out_of_range"] == ("standard", True)
          and _lab["4 out_of_range, run-time built 'high'"] == ("standard", True))
    check("4q fetch_and_assess: 'standard' and 'failed' days are not touched by the downgrade",
          _lab["4 out_of_range, standard day"] == ("standard", False)
          and _lab["4 out_of_range, failed day"] == ("failed", False))


# -- run_import -------------------------------------------------------------------------------------------------------
def _imp11(days, qlog=None, validate=None, progress=None):
    """Runs run_import over the given raw days. Returns (result, recorder, quality log, save calls)."""
    rec, saves = _Rec11(), []
    if qlog is not None:
        _put_log(qlog)
    real_save = _q11._save_quality_log

    def _save(data, **kw):
        saves.append(kw)
        return real_save(data, **kw)

    with patch("garmin_import.load_bulk", return_value=iter(days)), \
            patch.object(_col5, "log", rec), \
            patch.object(_q11, "_save_quality_log", side_effect=_save), \
            patch.object(_col5.validator, "validate", **({"side_effect": validate} if validate else {"wraps": _col5.validator.validate})):
        res = _col5.run_import("unused", progress_callback=progress)
    return res, rec, json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8")), saves


_Dn = [f"2024-02-{n:02d}" for n in range(1, 8)]
_ok_val = lambda raw: {"status": "ok", "issues": []}      # noqa: E731

# skipped days: any existing day not worse than the export, any source
with _isolated_log_env("imp11a") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ql = {"days": [
        {"date": "2024-03-01", "quality": "high", "source": "api"},     # later than every imported day
        {"date": _Dn[0], "quality": "high", "source": "api"},           # equal to export -> protected
        {"date": _Dn[1], "quality": "standard", "source": "api"},       # worse than export, even from API -> upgraded
        {"date": _Dn[2], "quality": "high", "source": "aaa"},           # equal, non-API source -> protected
        {"date": _Dn[3], "quality": "standard", "source": "bulk"},      # worse than export -> upgraded
        {"date": _Dn[4], "quality": "failed", "source": "api"}]}        # worse than export -> upgraded
    _prog = []
    _res, _rec, _qlog, _saves = _imp11([_day_raw(d, "high") for d in _Dn[:5]], _ql,
                                       progress=lambda *a: _prog.append(a))
    _by_date = {e["date"]: e for e in _qlog["days"]}
    check("4q run_import: an existing day that is not worse than the export (equal or better, any source) "
          "is skipped and left untouched",
          _by_date[_Dn[0]]["quality"] == "high" and _by_date[_Dn[0]]["source"] == "api"
          and _by_date[_Dn[2]]["quality"] == "high" and _by_date[_Dn[2]]["source"] == "aaa")
    check("4q run_import: an existing day that is worse than the export is upgraded by it, "
          "even one already sourced from the API",
          _by_date[_Dn[1]]["source"] == "bulk" and _by_date[_Dn[1]]["quality"] == "high"
          and _by_date[_Dn[3]]["source"] == "bulk" and _by_date[_Dn[3]]["quality"] == "high"
          and _by_date[_Dn[4]]["source"] == "bulk" and _by_date[_Dn[4]]["quality"] == "high")
    check("4q run_import: two protected days are skipped, three upgraded days count as ok, loop goes on",
          _res == {"ok": 3, "skipped": 2, "failed": 0})
    check("4q run_import: the progress callback is called for every day, skipped or not, with (i, None, date)",
          _prog == [(i, None, d) for i, d in enumerate(_Dn[:5], 1)])
    check("4q run_import: the skipped days are logged at debug level, the written days at info level",
          [m for m in _rec.msgs("info") if m.startswith("  import [")]
          == [f"  import [{i}]: {_Dn[i - 1]} — high" for i in (2, 4, 5)])

# validator status
with _isolated_log_env("imp11b") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _stat = {_Dn[0]: _rt11("critical"), _Dn[1]: "aaa", _Dn[2]: "zzz"}
    _res, _rec, _qlog, _saves = _imp11(
        [_day_raw(d, "high") for d in _Dn[:3]], {"days": []},
        validate=lambda raw: {"status": _stat[raw["date"]], "issues": []})
    check("4q run_import: only validator status 'critical' skips a day (counted as failed, loop goes on)",
          _res == {"ok": 2, "skipped": 0, "failed": 1}
          and f"  import [1]: {_Dn[0]} — validator critical, skipped" in _rec.msgs("warning")
          and {e["date"] for e in _qlog["days"]} == set(_Dn[1:3]))

# reasons, failed days, save calls
with _isolated_log_env("imp11c") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _qlog, _saves = _imp11(
        [_day_raw(_Dn[0], "high"), _day_raw(_Dn[1], "standard"), {"date": _Dn[2]}], {"days": []}, validate=_ok_val)
    _by = {e["date"]: e for e in _qlog["days"]}
    check("4q run_import: reasons for high, standard and failed days",
          _by[_Dn[0]]["reason"] == "Quality: high — bulk import"
          and _by[_Dn[1]]["reason"] == "Quality: standard — bulk import"
          and _by[_Dn[2]]["reason"] == "Quality: failed — insufficient data in bulk export")
    check("4q run_import: a day of quality 'failed' counts as failed, is not written and is logged as such",
          _res == {"ok": 2, "skipped": 0, "failed": 1} and _by[_Dn[2]]["quality"] == "failed"
          and _by[_Dn[2]]["write"] is False
          and f"  import [3]: {_Dn[2]} — quality failed, not written" in _rec.msgs("warning")
          and f"  import [2]: {_Dn[1]} — standard" in _rec.msgs("info"))
    check("4q run_import: the quality log is saved without backup after every day and with backup once at the end",
          [s.get("skip_backup") for s in _saves] == [True, True, True, None])
    check("4q run_import: the final line names the counts",
          "  Import done: 2 written, 0 skipped, 1 failed" in _rec.msgs("info"))

# invalid and missing dates
with _isolated_log_env("imp11d") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _bad = _day_raw("2024-13-45", "high")
    _prog = []
    _res, _rec, _qlog, _saves = _imp11([{"x": 1}, _bad, _day_raw(_Dn[0], "high")], {"days": []}, validate=_ok_val,
                                       progress=lambda *a: _prog.append(a))
    check("4q run_import: a missing date and an invalid date count as failed, the loop goes on with the next day",
          _res == {"ok": 1, "skipped": 0, "failed": 2} and [e["date"] for e in _qlog["days"]] == [_Dn[0]]
          and "  import [1]: missing date — skipped" in _rec.msgs("warning")
          and "  import [2]: invalid date '2024-13-45' — skipped" in _rec.msgs("warning"))
    # Fix 3 (v1.7.4.6): the date is validated before anything is written —
    # an invalid date leaves no raw file behind.
    check("4q run_import: a day with an invalid date is not written to raw/",
          not (cfg.RAW_DIR / "garmin_raw_2024-13-45.json").exists())
    check("4q run_import: the progress callback is called for every day, including a missing or invalid date",
          _prog == [(1, None, None), (2, None, "2024-13-45"), (3, None, _Dn[0])])


# first_day after the import
def _first_day11(name, entries, first_day, days, validate=_ok_val):
    with _isolated_log_env(name) as _bb:
        cfg.SUMMARY_DIR = _bb / "summary"
        _ql = {"days": entries}
        if first_day is not None:
            _ql["first_day"] = first_day
        _r, _rc, _q, _s = _imp11(days, _ql, validate=validate)
        return _r, _rc, _q


_msg_fd = "  Archive: first_day updated from {} to {} (GDPR export predates device history)"
_r, _rc, _q = _first_day11("imp11e1", [{"date": "2023-01-01", "quality": "high", "source": "bulk"}], "2024-01-01",
                           [{"date": _Dn[0]}])
check("4q run_import: no successful day (ok == 0) -> first_day stays",
      _r["ok"] == 0 and _q["first_day"] == "2024-01-01")
_r, _rc, _q = _first_day11("imp11e2", [{"date": "2023-01-01", "quality": "high", "source": "bulk"}], "2024-01-01",
                           [_day_raw(_Dn[0], "high")])
check("4q run_import: one successful day and an earlier bulk day in the log -> first_day moves to the earliest bulk day",
      _r["ok"] == 1 and _q["first_day"] == "2023-01-01"
      and _msg_fd.format("2024-01-01", "2023-01-01") in _rc.msgs("info"))
_r, _rc, _q = _first_day11("imp11e3", [{"date": "2020-01-01", "quality": "high", "source": "api"},
                                       {"date": "2021-01-01", "quality": "high", "source": "legacy"},
                                       {"date": "2022-01-01", "quality": "high", "source": "aaa"}],
                           None, [_day_raw(_Dn[0], "high")])
check("4q run_import: only source 'bulk' days count for first_day; none set yet -> first_day is set from the import",
      _q["first_day"] == _Dn[0] and _msg_fd.format(None, _Dn[0]) in _rc.msgs("info"))
_r, _rc, _q = _first_day11("imp11e4", [{"date": "garbage", "quality": "high", "source": "bulk"},
                                       {"quality": "high", "source": "bulk"}], "2030-01-01",
                           [_day_raw(_Dn[0], "high")])
check("4q run_import: a bulk entry with an invalid or missing date is ignored, not fatal",
      _r["ok"] == 1 and _q["first_day"] == _Dn[0])
_r, _rc, _q = _first_day11("imp11e5", [], _Dn[0], [_day_raw(_Dn[0], "high")])
check("4q run_import: an earliest day equal to first_day changes nothing and logs nothing",
      _q["first_day"] == _Dn[0] and not any("first_day updated" in m for m in _rc.msgs("info")))
_r, _rc, _q = _first_day11("imp11e6", [], "2023-01-01", [_day_raw(_Dn[0], "high")])
check("4q run_import: a first_day that is already earlier is kept",
      _q["first_day"] == "2023-01-01" and not any("first_day updated" in m for m in _rc.msgs("info")))

# an error inside the loop, a run-time built label, the stop event
with _isolated_log_env("imp11f") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _real_norm = _col5.normalizer.normalize

    def _norm_boom(raw, source="api"):
        if raw["date"] == _Dn[1]:
            raise RuntimeError("boom")
        return _real_norm(raw, source=source)

    _prog = []
    with patch.object(_col5.normalizer, "normalize", side_effect=_norm_boom):
        _res, _rec, _qlog, _saves = _imp11([_day_raw(d, "high") for d in _Dn[:3]], {"days": []}, validate=_ok_val,
                                           progress=lambda *a: _prog.append(a))
    check("4q run_import: an exception on one day counts as exactly one failure, is logged, the other days go on",
          _res == {"ok": 2, "skipped": 0, "failed": 1}
          and f"  import [2]: {_Dn[1]} — error: boom" in _rec.msgs("error")
          and {e["date"] for e in _qlog["days"]} == {_Dn[0], _Dn[2]})
    check("4q run_import: the progress callback is also called for the day with the error",
          _prog == [(i, None, d) for i, d in enumerate(_Dn[:3], 1)])

with _isolated_log_env("imp11g") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(_col5.quality, "assess_quality", return_value=_rt11("failed")):
        _res, _rec, _qlog, _saves = _imp11([_day_raw(_Dn[0], "high")], {"days": []}, validate=_ok_val)
    check("4q run_import: the label 'failed' is compared by value (run-time built string) -> counted as failed",
          _res == {"ok": 0, "skipped": 0, "failed": 1})

with _isolated_log_env("imp11h") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ev0, _ev1 = threading.Event(), threading.Event()
    _col5.set_stop_event(_ev0)
    _imp11([], {"days": []})
    check("4q run_import: without a stop_event the registered one stays", _col5._stop_event is _ev0)
    with patch("garmin_import.load_bulk", return_value=iter([])):
        _col5.run_import("unused", stop_event=_ev1)
    check("4q run_import: a given stop_event is registered with the collector and the API module",
          _col5._stop_event is _ev1 and _col5.api._stop_event is _ev1)
    _col5.set_stop_event(None)

# -- session logs -----------------------------------------------------------------------------------------------------
with _isolated_log_env("slog11") as _b:
    with _cfg_values(LOG_RECENT_DIR=_b / "x" / "recent", LOG_FAIL_DIR=_b / "y" / "z" / "fail"):
        _fh, _sp = _col5._start_session_log()
        _col5._close_session_log(_fh, _sp, False, False)
        check("4q start_session_log: log/recent and log/fail are created including missing parent folders",
              cfg.LOG_RECENT_DIR.is_dir() and cfg.LOG_FAIL_DIR.is_dir() and _sp.parent == cfg.LOG_RECENT_DIR)
    with _cfg_values(LOG_FORCE_REFETCH_DIR=_b / "p" / "q" / "ffr"):
        _fh, _sp = _col5._start_force_refetch_log()
        _col5._close_force_refetch_log(_fh)
        check("4q start_force_refetch_log: the folder is created including missing parent folders",
              cfg.LOG_FORCE_REFETCH_DIR.is_dir() and _sp.parent == cfg.LOG_FORCE_REFETCH_DIR)
        _fh, _sp2 = _col5._start_force_refetch_log()      # the folder exists by now
        _col5._close_force_refetch_log(_fh)
        check("4q start_force_refetch_log: an existing folder is fine", _sp2.parent == cfg.LOG_FORCE_REFETCH_DIR)


def _aged11(folder, names, prefix_ts=1000):
    folder.mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(names):
        (folder / n).write_text(n, encoding="utf-8")
        os.utime(folder / n, (prefix_ts + i, prefix_ts + i))


with _isolated_log_env("slog11b") as _b:
    _rec_dir, _fail_dir = _b / "recent", _b / "fail"
    with _cfg_values(LOG_RECENT_DIR=_rec_dir, LOG_FAIL_DIR=_fail_dir, LOG_RECENT_MAX=3):
        _fail_dir.mkdir()
        _aged11(_rec_dir, ["garmin_1.log", "garmin_2.log", "garmin_3.log", "garmin_4.log"])
        _sess = _rec_dir / "garmin_session.log"
        _fh = logging.FileHandler(_sess, encoding="utf-8")
        logging.getLogger().addHandler(_fh)
        _col5._close_session_log(_fh, _sess, False, False)
        check("4q close_session_log: of 5 logs with a limit of 3 the 2 oldest are deleted",
              sorted(p.name for p in _rec_dir.glob("garmin_*.log"))
              == ["garmin_3.log", "garmin_4.log", "garmin_session.log"])
        _fh = logging.FileHandler(_sess, encoding="utf-8")
        logging.getLogger().addHandler(_fh)
        _col5._close_session_log(_fh, _sess, False, False)
        check("4q close_session_log: with exactly as many logs as the limit nothing is deleted",
              len(list(_rec_dir.glob("garmin_*.log"))) == 3)

        _aged11(_rec_dir, ["garmin_old1.log", "garmin_old2.log"], prefix_ts=10)
        _real_unlink = Path.unlink

        def _vanishing(self, missing_ok=False):
            if self.name.startswith("garmin_old") and self.exists():
                os.remove(self)           # the file disappears between listing and deleting
            return _real_unlink(self, missing_ok=missing_ok)

        _fh = logging.FileHandler(_sess, encoding="utf-8")
        logging.getLogger().addHandler(_fh)
        with patch.object(Path, "unlink", _vanishing):
            _col5._close_session_log(_fh, _sess, False, False)
        check("4q close_session_log: a log that vanishes before it is deleted does not stop the rotation",
              sorted(p.name for p in _rec_dir.glob("garmin_*.log"))
              == ["garmin_3.log", "garmin_4.log", "garmin_session.log"])

with _isolated_log_env("slog11c") as _b:
    _ffr_dir = _b / "ffr"
    with _cfg_values(LOG_FORCE_REFETCH_DIR=_ffr_dir, LOG_FORCE_REFETCH_MAX=2):
        _aged11(_ffr_dir, ["force_refetch_1.log", "force_refetch_2.log", "force_refetch_3.log"])
        _fh = logging.FileHandler(_ffr_dir / "force_refetch_4.log", encoding="utf-8")
        logging.getLogger().addHandler(_fh)
        _col5._close_force_refetch_log(_fh)
        check("4q close_force_refetch_log: only the newest LOG_FORCE_REFETCH_MAX logs are kept",
              sorted(p.name for p in _ffr_dir.glob("force_refetch_*.log"))
              == ["force_refetch_3.log", "force_refetch_4.log"])

        _aged11(_ffr_dir, ["force_refetch_old1.log", "force_refetch_old2.log"], prefix_ts=10)

        def _vanishing2(self, missing_ok=False):
            if self.name.startswith("force_refetch_old") and self.exists():
                os.remove(self)
            return _real_unlink(self, missing_ok=missing_ok)

        _fh = logging.FileHandler(_ffr_dir / "force_refetch_5.log", encoding="utf-8")
        logging.getLogger().addHandler(_fh)
        with patch.object(Path, "unlink", _vanishing2):
            _col5._close_force_refetch_log(_fh)
        check("4q close_force_refetch_log: a log that vanishes before it is deleted does not stop the rotation",
              sorted(p.name for p in _ffr_dir.glob("force_refetch_*.log"))
              == ["force_refetch_4.log", "force_refetch_5.log"])

# ══════════════════════════════════════════════════════════════════════════════
#  4r. garmin_collector — self-healing, schema migration, Force-Refetch
#      commit and preview (v1.7.4.0.3, Group D2).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4r. garmin_collector — self-healing, schema migration, Force-Refetch")
import garmin_backup as _bkp12
import garmin_backup_source as _bsrc12

_ARROW = "→"

# -- _run_self_healing ----------------------------------------------------------------------------------------------------
_HD = [f"2024-07-{n:02d}" for n in range(1, 10)]


def _sh12(entries, raws, status_of, version="2.0", assess=None, second_empty=()):
    """Runs _run_self_healing with a controlled validator and raw reader.
    Returns (quality data, recorder, save mock, dates handed to validate)."""
    qd, rec, validated, reads = {"days": entries}, _Rec11(), [], {}

    def _read(d):
        reads[d] = reads.get(d, 0) + 1
        return {} if (d in second_empty and reads[d] > 1) else raws.get(d, {})

    def _validate(raw):
        validated.append(raw["date"])
        return {"status": status_of[raw["date"]], "issues": [{"type": "x"}]}

    with patch.object(_col5.writer, "read_raw", side_effect=_read), \
            patch.object(_col5.validator, "current_version", return_value=version), \
            patch.object(_col5.validator, "validate", side_effect=_validate), \
            patch.object(_col5.quality, "_save_quality_log") as save, \
            patch.object(_col5, "log", rec), \
            patch.object(_col5.quality, "assess_quality",
                         **({"return_value": assess} if assess else {"wraps": _col5.quality.assess_quality})):
        _col5._run_self_healing(qd)
    return qd, rec, save, validated


_RAW12 = {d: _day_raw(d, "high") for d in _HD}

# version "unknown" (by value) / any other value
_e = [{"date": _HD[0], "validator_result": "warning", "validator_schema_version": "0.1"}]
_qd, _rec, _save, _val = _sh12(_e, _RAW12, {_HD[0]: "warning"}, version=_rt11("unknown"))
check("4r self-healing: schema version 'unknown' (compared by value) -> nothing is read or touched",
      _val == [] and _qd["days"][0]["validator_schema_version"] == "0.1")
for _v in ("zzz", "aaa"):
    _e = [{"date": _HD[0], "validator_result": "warning", "validator_schema_version": "0.1"}]
    _qd, _rec, _save, _val = _sh12(_e, _RAW12, {_HD[0]: "warning"}, version=_v)
    check(f"4r self-healing: schema version {_v!r} is a real version (entry is revalidated and stamped)",
          _val == [_HD[0]] and _qd["days"][0]["validator_schema_version"] == _v)

# candidate selection
_entries = [
    {"date": _HD[0], "validator_result": "warning", "validator_schema_version": rt} for rt in [_rt11("2.0")]
] + [
    {"date": _HD[1], "validator_result": "warning", "validator_schema_version": "1.0"},     # older
    {"date": _HD[2], "validator_result": "warning", "validator_schema_version": "3.0"},     # newer
    {"date": _HD[3], "validator_result": "critical"},                                       # no version stored
    {"date": _HD[4], "validator_result": "ok", "validator_schema_version": "1.0"},          # ok -> never
    {"date": _HD[5], "validator_result": None, "validator_schema_version": "1.0"},          # none -> never
    {"date": _HD[6], "validator_schema_version": "1.0"},                                    # no result -> never
]
_qd, _rec, _save, _val = _sh12(_entries, _RAW12, {d: "warning" for d in _HD}, version="2.0")
check("4r self-healing: candidates are days with a result other than ok/None and a different (older, newer or missing) "
      "schema version; the same version (by value), ok and missing results are left alone",
      _val == [_HD[1], _HD[2], _HD[3]])
check("4r self-healing: the number of candidates and the schema version are logged",
      "  Self-healing: 3 day(s) to revalidate (schema 2.0)" in _rec.msgs("info"))
_qd, _rec, _save, _val = _sh12([{"date": _HD[0], "validator_result": "ok", "validator_schema_version": "1.0"}],
                               _RAW12, {_HD[0]: "ok"}, version="2.0")
check("4r self-healing: no candidates -> nothing is revalidated or saved",
      _val == [] and not _save.called and "  Self-healing: no candidates — schema versions match" in _rec.msgs("debug"))

# loop keeps going after skips; unchanged vs changed; quality only when the result became ok
_entries = [
    {"validator_result": "warning", "validator_schema_version": "1.0"},                                  # no date
    {"date": _HD[0], "validator_result": "warning", "validator_schema_version": "1.0"},                  # no raw file
    {"date": _HD[1], "validator_result": _rt11("warning"), "validator_schema_version": "1.0"},           # unchanged
    {"date": _HD[2], "validator_result": "critical", "validator_schema_version": "1.0", "quality": "keep"},  # changed, not ok
    {"date": _HD[3], "validator_result": "warning", "validator_schema_version": "1.0", "quality": "x"},   # -> ok, high
    {"date": _HD[4], "validator_result": "warning", "validator_schema_version": "1.0", "quality": "x"},   # -> ok, failed
    {"date": _HD[5], "validator_result": "warning", "validator_schema_version": "1.0", "quality": "x"},   # -> ok, standard
    {"date": _HD[6], "validator_result": "warning", "validator_schema_version": "1.0", "quality": "keep"},  # -> ok, 2nd read empty
]
_raws = {_HD[1]: _RAW12[_HD[1]], _HD[2]: _RAW12[_HD[2]], _HD[3]: _day_raw(_HD[3], "high"),
         _HD[4]: {"date": _HD[4]}, _HD[5]: _day_raw(_HD[5], "std"), _HD[6]: _day_raw(_HD[6], "high")}
_status = {_HD[1]: "warning", _HD[2]: "warning", _HD[3]: _rt11("ok"), _HD[4]: _rt11("ok"), _HD[5]: _rt11("ok"),
           _HD[6]: _rt11("ok")}
_qd, _rec, _save, _val = _sh12(_entries, _raws, _status, version="2.0", second_empty=(_HD[6],))
_d = {e.get("date"): e for e in _qd["days"]}
check("4r self-healing: an entry without a date, one without a raw file and one with an unchanged result "
      "do not stop the loop; the later entries are processed",
      _val == [_HD[1], _HD[2], _HD[3], _HD[4], _HD[5], _HD[6]]
      and "  Self-healing: no raw file for 2024-07-01 — skipped" in _rec.msgs("warning"))
check("4r self-healing: an unchanged result only stamps the schema version (compared by value)",
      _d[_HD[1]]["validator_schema_version"] == "2.0" and "validator_issues" not in _d[_HD[1]]
      and _d[_HD[1]]["validator_result"] == "warning")
check("4r self-healing: a changed result is recorded with its issues and the new version and logged; "
      "a result that is not 'ok' leaves quality alone",
      _d[_HD[2]]["validator_result"] == "warning" and _d[_HD[2]]["validator_issues"] == [{"type": "x"}]
      and _d[_HD[2]]["validator_schema_version"] == "2.0" and _d[_HD[2]]["quality"] == "keep"
      and f"  Self-healing: {_HD[2]} — critical {_ARROW} warning" in _rec.msgs("info"))
check("4r self-healing: result became ok -> quality, fields and recheck are re-evaluated (recheck only for 'failed')",
      (_d[_HD[3]]["quality"], _d[_HD[3]]["recheck"]) == ("high", False)
      and (_d[_HD[4]]["quality"], _d[_HD[4]]["recheck"]) == ("failed", True)
      and (_d[_HD[5]]["quality"], _d[_HD[5]]["recheck"]) == ("standard", False)
      and isinstance(_d[_HD[3]]["fields"], dict) and _d[_HD[3]]["fields"])
check("4r self-healing: result became ok but the second read of the raw file is empty -> quality stays",
      _d[_HD[6]]["quality"] == "keep" and _d[_HD[6]]["validator_result"] == "ok")
check("4r self-healing: 5 changed days are counted exactly, saved once and logged",
      "  Self-healing: 5 day(s) updated" in _rec.msgs("info") and _save.call_count == 1
      and _save.call_args.args[0] is _qd)
_qd, _rec, _save, _val = _sh12(
    [{"date": _HD[0], "validator_result": "warning", "validator_schema_version": "1.0"}],
    {_HD[0]: _RAW12[_HD[0]]}, {_HD[0]: _rt11("ok")}, version="2.0", assess=_rt11("failed"))
check("4r self-healing: the label 'failed' is compared by value (run-time built string) -> recheck",
      _qd["days"][0]["recheck"] is True and "  Self-healing: 1 day(s) updated" in _rec.msgs("info"))
_qd, _rec, _save, _val = _sh12(
    [{"date": d, "validator_result": "warning", "validator_schema_version": "1.0"} for d in _HD[:3]],
    {d: _RAW12[d] for d in _HD[:3]}, {d: "critical" for d in _HD[:3]}, version="2.0")
check("4r self-healing: 3 changed days -> '3 day(s) updated'", "  Self-healing: 3 day(s) updated" in _rec.msgs("info"))
_qd, _rec, _save, _val = _sh12(
    [{"date": _HD[0], "validator_result": "warning", "validator_schema_version": "1.0"}],
    {_HD[0]: _RAW12[_HD[0]]}, {_HD[0]: "warning"}, version="2.0")
check("4r self-healing: only unchanged results -> nothing is saved, no 'updated' line",
      not _save.called and not any("updated" in m for m in _rec.msgs("info")))

# -- _run_schema_migration ---------------------------------------------------------------------------------------------
_MD = [f"2024-08-{n:02d}" for n in range(1, 9)]
with _isolated_log_env("mig12") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.RAW_DIR.mkdir(parents=True)
    cfg.SUMMARY_DIR.mkdir(parents=True)
    _cur = _normalizer5.CURRENT_SCHEMA_VERSION
    for _d, _v in ((_MD[1], _cur - 1), (_MD[2], _cur - 1), (_MD[3], _cur - 1), (_MD[4], _cur - 1),
                   (_MD[5], _cur - 1), (_MD[6], _cur + 1)):
        (cfg.SUMMARY_DIR / f"garmin_{_d}.json").write_text(json.dumps({"date": _d, "schema_version": _v}),
                                                           encoding="utf-8")
    for _d in (_MD[1], _MD[2], _MD[4], _MD[5], _MD[6]):        # _MD[3] has a summary but no raw file
        (cfg.RAW_DIR / f"garmin_raw_{_d}.json").write_text(json.dumps(_day_raw(_d, "high")), encoding="utf-8")
    _newer_bytes = (cfg.SUMMARY_DIR / f"garmin_{_MD[6]}.json").read_bytes()
    # entries: no date, no summary file, ok, no raw, ok, ok-then-write-error, newer than current
    _qd = {"days": [{"quality": "high"}, {"date": _MD[0]}, {"date": _MD[1]}, {"date": _MD[3]}, {"date": _MD[2]},
                    {"date": _MD[5]}, {"date": _MD[4]}, {"date": _MD[6]}]}
    _real_wso = _writer5.write_summary_only

    def _wso(summary, date_str):
        if date_str == _MD[5]:
            raise OSError("disk full")
        return _real_wso(summary, date_str)

    _rec = _Rec11()
    with patch.object(_writer5, "write_summary_only", side_effect=_wso), patch.object(_col5, "log", _rec):
        _col5._run_schema_migration(_qd)
    check("4r schema migration: entries without date / summary do not stop the loop; "
          "a summary newer than the current schema is not a candidate",
          json.loads((cfg.SUMMARY_DIR / f"garmin_{_MD[4]}.json").read_text(encoding="utf-8"))["schema_version"] == _cur
          and (cfg.SUMMARY_DIR / f"garmin_{_MD[6]}.json").read_bytes() == _newer_bytes)
    check("4r schema migration: progress counts from 1 over the 5 candidates, every outcome is logged",
          _rec.msgs("info")[:3] == [
              f"  Schema migration: 5 summary file(s) will be rewritten (schema version {_ARROW} {_cur})",
              "  Raw files are not modified.", f"  [1/5] {_MD[1]} — ok"]
          and f"  [2/5] {_MD[3]} — no raw file, skipped" in _rec.msgs("warning")
          and f"  [3/5] {_MD[2]} — ok" in _rec.msgs("info")
          and f"  [4/5] {_MD[5]} — error: disk full" in _rec.msgs("error")
          and f"  [5/5] {_MD[4]} — ok" in _rec.msgs("info"))
    check("4r schema migration: a day without a summary file is reported",
          f"  Schema migration: {_MD[0]} — no summary file, skipped" in _rec.msgs("warning"))
    check("4r schema migration: the final line counts exactly 3 rewritten and 2 skipped/failed",
          "  Schema migration complete: 3 rewritten, 2 skipped/failed." in _rec.msgs("info"))

    # a summary without schema_version counts as version 0
    (cfg.SUMMARY_DIR / f"garmin_{_MD[7]}.json").write_text(json.dumps({"date": _MD[7]}), encoding="utf-8")
    (cfg.RAW_DIR / f"garmin_raw_{_MD[7]}.json").write_text(json.dumps(_day_raw(_MD[7], "high")), encoding="utf-8")
    for _cv, _expect in ((1, True), (0, False)):
        _rec = _Rec11()
        with patch.object(_normalizer5, "CURRENT_SCHEMA_VERSION", _cv), \
                patch.object(_writer5, "write_summary_only") as _wso2, \
                patch.object(_col5, "log", _rec):
            _col5._run_schema_migration({"days": [{"date": _MD[7]}]})
        check(f"4r schema migration: a summary without schema_version counts as 0 (current version {_cv} -> "
              f"{'rewritten' if _expect else 'up to date'})",
              (_wso2.called and not _rec.msgs("warning")) is _expect
              and ("  Schema migration: all summaries up to date — nothing to do." in _rec.msgs("info")) is (not _expect))

# -- commit_force_refetch ----------------------------------------------------------------------------------------------
_CD = [f"2024-09-{n:02d}" for n in range(1, 8)]


def _pr12(date_str, label="high", **extra):
    return {"date": date_str, "error": None, "quality_after": label, "_normalized": {"n": 1}, "_summary": {"s": 1},
            "_fields": {"steps": "high"}, "_val_result": {"status": "ok"}, **extra}


_prev = [
    {"date": _CD[0], "error": "fetch failed"},                    # failed in the preview
    _pr12(_CD[1]),                                                # rejected, restore works
    _pr12(_CD[2]),                                                # rejected, nothing to restore
    _pr12(_CD[3]),                                                # rejected, restore raises
    _pr12(_CD[4]),                                                # confirmed, written
    _pr12(_CD[5], label="failed"),                                # confirmed, label failed
    _pr12(_CD[6]),                                                # confirmed, last one
]


def _restore12(date_str):
    if date_str == _CD[3]:
        raise OSError("snapshot locked")
    return date_str == _CD[1]


_rec = _Rec11()
_qdata = {"days": []}
with patch.object(_ffr5, "restore_snapshot", side_effect=_restore12) as _rs, \
        patch.object(_col5, "_write_assessed") as _wa, patch.object(_col5.quality, "record_attempt") as _ra, \
        patch.object(_bkp12, "backup_raw") as _br, patch.object(_bsrc12, "backup_source") as _bs, \
        patch.object(_col5, "log", _rec):
    _out = _col5.commit_force_refetch(_prev, {_CD[4], _CD[5], _CD[6]}, _qdata)
check("4r commit_force_refetch: one result per date, in order — error skipped, rejected ones reverted "
      "(error text when nothing to restore or restore raises), confirmed ones committed",
      _out == [
          {"date": _CD[0], "action": "skipped_error", "error": "fetch failed"},
          {"date": _CD[1], "action": "reverted", "error": None},
          {"date": _CD[2], "action": "reverted", "error": "no snapshot to restore"},
          {"date": _CD[3], "action": "reverted", "error": "snapshot locked"},
          {"date": _CD[4], "action": "committed", "error": None},
          {"date": _CD[5], "action": "committed", "error": None},
          {"date": _CD[6], "action": "committed", "error": None}])
check("4r commit_force_refetch: only confirmed days with a writable label are written to raw/summary and backed up; "
      "source/ is always backed up; every confirmed day is recorded",
      [c.args[2] for c in _wa.call_args_list] == [_CD[4], _CD[6]]
      and [c.args[0] for c in _br.call_args_list] == [_CD[4], _CD[6]]
      and all(c.kwargs == {"force": True} for c in _br.call_args_list + _bs.call_args_list)
      and [c.args[0] for c in _bs.call_args_list] == [_CD[4], _CD[5], _CD[6]]
      and [c.kwargs["written"] for c in _ra.call_args_list] == [True, False, True])
check("4r commit_force_refetch: rejected days are logged; a failing revert is logged as an error",
      f"  Force-Refetch commit: {_CD[1]} — rejected, source/ reverted" in _rec.msgs("info")
      and f"  Force-Refetch commit: {_CD[3]} — revert failed: snapshot locked" in _rec.msgs("error"))

# -- run_force_refetch_preview ------------------------------------------------------------------------------------------
_PD = [f"2024-10-{n:02d}" for n in range(1, 5)]


def _prev12(dates, snapshot, files=None, new_files=None, stops=None):
    """Runs the preview with stubbed snapshot / fetch. files: date -> text of the old source file; new_files:
    date -> text written by the fetch (None = the fetch removes the file). Returns (results, recorder, fetch calls,
    compare calls)."""
    rec, calls, cmp_calls = _Rec11(), [], []
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for d, t in (files or {}).items():
        (cfg.SOURCE_DIR / f"garmin_source_{d}.json").write_text(t, encoding="utf-8")

    def _fetch(client, d, **kw):
        calls.append((d, kw))
        p = cfg.SOURCE_DIR / f"garmin_source_{d}.json"
        t = (new_files or {}).get(d)
        if t is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(t, encoding="utf-8")
        return "high", {"n": 1}, {"s": 1}, {"steps": "high"}, {"status": "ok", "issues": []}

    real_cmp = _col5.quality.compare_source_fields

    def _cmp(old, new):
        cmp_calls.append((old, new))
        return real_cmp(old, new)

    stop_iter = iter(stops) if stops is not None else None
    with patch.object(_ffr5, "snapshot_source", side_effect=lambda d: {"had_prior_data": snapshot(d)}), \
            patch.object(_col5, "_fetch_and_assess", side_effect=_fetch), \
            patch.object(_col5.quality, "compare_source_fields", side_effect=_cmp), \
            patch.object(_col5, "_is_stopped", side_effect=(lambda: next(stop_iter, False)) if stops is not None
                         else (lambda: False)), \
            patch.object(_col5, "log", rec):
        res = _col5.run_force_refetch_preview(MagicMock(), dates)
    return res, rec, calls, cmp_calls


_OLD = {"date": _PD[0], "stats": {"totalSteps": 100}}
_NEW = {"date": _PD[0], "stats": {"totalSteps": 999}}
with _isolated_log_env("prev12a") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12([_PD[0]], lambda d: True, files={_PD[0]: json.dumps(_OLD)},
                                       new_files={_PD[0]: json.dumps(_NEW)})
    check("4r force-refetch preview: an existing source/ file is read and assessed (quality_before), "
          "the fetch runs with force=True, the changed fields are named",
          _calls == [(_PD[0], {"force": True})] and _res[0]["quality_before"] == _col5.quality.assess_quality(_OLD)
          and _res[0]["quality_before"] != "failed" and _res[0]["quality_after"] == "high"
          and _res[0]["had_prior_data"] is True and _res[0]["fields_changed"] == ["stats"]
          and _res[0]["error"] is None and _res[0]["_summary"] == {"s": 1} and _res[0]["_fields"] == {"steps": "high"})
    check("4r force-refetch preview: the field comparison gets the old and the new source file content",
          _cmp == [(_OLD, _NEW)])
    check("4r force-refetch preview: the result is logged",
          any(m.startswith(f"  Force-Refetch preview: {_PD[0]} — ") and m.endswith("| 1 field(s) changed")
              for m in _rec.msgs("info")))

with _isolated_log_env("prev12b") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12([_PD[1]], lambda d: False, new_files={_PD[1]: json.dumps(_NEW)})
    check("4r force-refetch preview: no old source file -> quality_before 'failed', nothing is compared, no warning",
          _res[0]["quality_before"] == "failed" and _res[0]["fields_changed"] == [] and _cmp == []
          and _rec.msgs("warning") == [])

with _isolated_log_env("prev12c") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12([_PD[0]], lambda d: True, files={_PD[0]: "{broken"},
                                       new_files={_PD[0]: json.dumps(_NEW)})
    check("4r force-refetch preview: an unreadable old source file is a warning; the comparison gets {} for it",
          _cmp == [({}, _NEW)] and _res[0]["quality_before"] == "failed"
          and any("could not read existing source/" in m for m in _rec.msgs("warning")))

with _isolated_log_env("prev12d") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12([_PD[0]], lambda d: True, files={_PD[0]: json.dumps(_OLD)}, new_files={})
    check("4r force-refetch preview: no new source file (but prior data) -> the comparison gets {} for it, no warning",
          _cmp == [(_OLD, {})] and _rec.msgs("warning") == [])

with _isolated_log_env("prev12e") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12([_PD[0]], lambda d: True, files={_PD[0]: json.dumps(_OLD)},
                                       new_files={_PD[0]: "{broken"})
    check("4r force-refetch preview: an unreadable new source file is a warning; the comparison gets {} for it",
          _cmp == [(_OLD, {})] and any("could not read new source/" in m for m in _rec.msgs("warning")))

with _isolated_log_env("prev12f") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _res, _rec, _calls, _cmp = _prev12(_PD[:3], lambda d: False, new_files={d: json.dumps(_NEW) for d in _PD},
                                       stops=[False, True, False, False, False])
    check("4r force-refetch preview: a stop request ends the list after the days done so far (it is not skipped over)",
          [r["date"] for r in _res] == [_PD[0]] and [c[0] for c in _calls] == [_PD[0]]
          and "  Force-Refetch preview: stopped after 1 day(s)." in _rec.msgs("info"))

# -- follow-up cases (second round) ----------------------------------------------------------------------------------
_qd, _rec, _save, _val = _sh12(
    [{"date": _HD[0], "validator_result": "warning", "validator_schema_version": "1.0", "quality": "keep"}],
    {_HD[0]: _RAW12[_HD[0]]}, {_HD[0]: "critical"}, version="2.0")
check("4r self-healing: a result that became 'critical' is recorded but does not re-evaluate quality",
      _qd["days"][0]["validator_result"] == "critical" and _qd["days"][0]["quality"] == "keep"
      and "recheck" not in _qd["days"][0])

_rec = _Rec11()
with patch.object(_ffr5, "restore_snapshot"), patch.object(_col5, "_write_assessed"),         patch.object(_col5.quality, "record_attempt", side_effect=[RuntimeError("log broken"), None]),         patch.object(_bkp12, "backup_raw"), patch.object(_bsrc12, "backup_source"), patch.object(_col5, "log", _rec):
    _out = _col5.commit_force_refetch([_pr12(_CD[0]), _pr12(_CD[1])], {_CD[0], _CD[1]}, {"days": []})
check("4r commit_force_refetch: an error while committing one day is recorded for that day, the next day is committed",
      _out == [{"date": _CD[0], "action": "skipped_error", "error": "log broken"},
               {"date": _CD[1], "action": "committed", "error": None}]
      and f"  Force-Refetch commit: {_CD[0]} — commit failed: log broken" in _rec.msgs("error"))

with _isolated_log_env("prev12g") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _rec = _Rec11()
    _good = ("high", {"n": 1}, {"s": 1}, {"steps": "high"}, {"status": "ok", "issues": []})
    with patch.object(_ffr5, "snapshot_source", return_value={"had_prior_data": False}),             patch.object(_col5, "_fetch_and_assess", side_effect=[RuntimeError("boom"), _good]),             patch.object(_col5, "log", _rec):
        _res = _col5.run_force_refetch_preview(MagicMock(), [_PD[0], _PD[1]])
    check("4r force-refetch preview: an error on one day is recorded for that day, the next day is still done",
          _res[0] == {"date": _PD[0], "error": "boom"} and _res[1]["date"] == _PD[1] and _res[1]["error"] is None
          and f"  Force-Refetch preview: {_PD[0]} — error: boom" in _rec.msgs("error"))

# ══════════════════════════════════════════════════════════════════════════════
#  4s. garmin_collector — source, steps and bulk-field backfill
#      (v1.7.4.0.3, Group D3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4s. garmin_collector — source, steps and bulk-field backfill")
import garmin_source_writer as _sw13

_BD = [f"2024-11-{n:02d}" for n in range(1, 11)]
_DECOYS13 = [{"date": "2030-01-01", "quality": "high", "source": "api", "fields": {"steps": "high"}},
             {"date": "2020-01-01", "quality": "high", "source": "api", "fields": {"steps": "high"}}]
_EM = "—"


def _dates13(ds):
    return [date.fromisoformat(d) for d in ds]


def _stopper13(stops):
    it = iter(stops)
    return lambda: next(it, False)


# -- _run_source_backfill ------------------------------------------------------------------------------------------
def _src13(dates, fetch, entries, stops=None):
    rec, qd = _Rec11(), {"days": entries}
    with _cfg_values(SYNC_DATES=_dates13(dates)), \
            patch.object(_col5, "_fetch_and_assess", side_effect=fetch), \
            patch.object(_col5, "_write_assessed") as wa, \
            patch.object(_col5.quality, "record_attempt") as ra, \
            patch.object(_col5, "_is_stopped", side_effect=_stopper13(stops) if stops else (lambda: False)), \
            patch.object(_col5, "log", rec):
        _col5._run_source_backfill(MagicMock(), qd)
    return rec, wa, ra


def _val13():
    return {"status": "ok", "issues": []}


def _fetch_src13(client, d):
    if d == _BD[2]:
        raise RuntimeError("boom")
    label = {_BD[0]: "standard", _BD[1]: "standard", _BD[3]: "failed", _BD[4]: "high"}[d]
    return label, {"n": d}, {"s": d}, {"f": d}, _val13()


_entries = _DECOYS13 + [{"date": _BD[1], "quality": "high", "source": "api"}]
_rec, _wa, _ra = _src13(_BD[:5], _fetch_src13, _entries)
check("4s source backfill: progress counts from 1, every day is logged, the error is a warning, the end line counts",
      "  Source backfill: 5 day(s) to re-fetch" in _rec.msgs("info")
      and [m for m in _rec.msgs("info") if m.startswith("  Source backfill [")]
      == [f"  Source backfill [1/5]: {_BD[0]} {_EM} standard", f"  Source backfill [2/5]: {_BD[1]} {_EM} standard",
          f"  Source backfill [4/5]: {_BD[3]} {_EM} failed", f"  Source backfill [5/5]: {_BD[4]} {_EM} high"]
      and f"  Source backfill [3/5]: {_BD[2]} {_EM} error: boom" in _rec.msgs("warning")
      and "  Source backfill complete: 4 fetched, 1 failed." in _rec.msgs("info"))
check("4s source backfill: each day is compared with its own log entry; a downgrade is not written, "
      "the other days are handed to _write_assessed (also 'failed' ones, which it refuses itself)",
      [c.args[2] for c in _wa.call_args_list] == [_BD[0], _BD[3], _BD[4]])
check("4s source backfill: record_attempt gets reason, written (False for a downgrade and for 'failed'), source api",
      [(c.args[1].isoformat(), c.args[2], c.args[3], c.kwargs["written"], c.kwargs["source"])
       for c in _ra.call_args_list]
      == [(_BD[0], "standard", "Source backfill: standard", True, "api"),
          (_BD[1], "standard", "Source backfill: standard", False, "api"),
          (_BD[3], "failed", "Source backfill: failed", False, "api"),
          (_BD[4], "high", "Source backfill: high", True, "api")])
_rec, _wa, _ra = _src13(_BD[:3], lambda c, d: ("high", {}, {}, {}, _val13()), [], stops=[False, True, False, False])
check("4s source backfill: a stop request ends the list (it is not skipped over)",
      _wa.call_count == 1 and "  Source backfill: stopped after 1 days." in _rec.msgs("info"))


# -- _run_steps_backfill --------------------------------------------------------------------------------------------
_STEPS13 = [{"startGMT": "2024-11-01T08:00:00", "steps": 42}]


def _stp13(dates, entries, raws, api_of, write_ok, patch_of, stops=None):
    rec, qd, patch_calls = _Rec11(), {"days": entries}, []
    patches = {d: iter(v) for d, v in patch_of.items()}

    def _api(client, method, d, label=None):
        r = api_of[d]
        if isinstance(r, Exception):
            raise r
        return r

    def _patch(d, field, data):
        patch_calls.append(d)
        return next(patches[d])

    with _cfg_values(SYNC_DATES=_dates13(dates)), \
            patch.object(_col5.api, "api_call", side_effect=_api), \
            patch.object(_col5.writer, "read_raw", side_effect=lambda d: raws.get(d, {})), \
            patch.object(_col5.writer, "write_day", side_effect=lambda n, s, d: write_ok.get(d, True)), \
            patch.object(_col5.quality, "record_attempt") as ra, \
            patch.object(_col5.quality, "record_field_backfill_failure", return_value=7) as rf, \
            patch.object(_sw13, "patch_source_field", side_effect=_patch), \
            patch.object(_col5, "_is_stopped", side_effect=_stopper13(stops) if stops else (lambda: False)), \
            patch.object(_col5, "log", rec):
        _col5._run_steps_backfill(MagicMock(), qd)
    return rec, ra, rf, patch_calls


def _fld13(d, steps):
    return {"date": d, "fields": {"steps": steps}}


_S = _BD
_raws = {d: {"date": d, "heart_rates": {"restingHeartRate": 60}} for d in _S if d != _S[1]}
_api = {_S[0]: (_STEPS13, True), _S[1]: (_STEPS13, True), _S[2]: (None, True), _S[3]: (_STEPS13, False),
        _S[4]: (_STEPS13, True), _S[5]: (_STEPS13, True), _S[6]: (_STEPS13, True), _S[7]: (_STEPS13, True),
        _S[8]: (_STEPS13, True), _S[9]: RuntimeError("api down")}
_entries = _DECOYS13 + [_fld13(_S[0], _rt11("high")), _fld13(_S[5], "medium"), _fld13(_S[6], "failed"),
                        _fld13(_S[7], "high"), _fld13(_S[8], "high")]
_rec, _ra, _rf, _pc = _stp13(_S, _entries, _raws, _api, {_S[4]: False},
                             {_S[0]: [True], _S[5]: [True], _S[6]: [True], _S[7]: [False, False],
                              _S[8]: [False, True]})
check("4s steps backfill: every failing path (no raw file, no data, unsuccessful call, write_day fails, exception) "
      "and a blocked quality-log update count as one failed attempt each, with the attempt number in the message",
      [c.args[1].isoformat() for c in _rf.call_args_list] == [_S[1], _S[2], _S[3], _S[4], _S[5], _S[6], _S[9]]
      and all(c.args[2] == "steps" for c in _rf.call_args_list)
      and f"  Steps backfill [2/10]: {_S[1]} {_EM} no raw/ file, skipped (attempt 7)" in _rec.msgs("warning")
      and f"  Steps backfill [3/10]: {_S[2]} {_EM} get_steps_data failed (attempt 7)" in _rec.msgs("warning")
      and f"  Steps backfill [4/10]: {_S[3]} {_EM} get_steps_data failed (attempt 7)" in _rec.msgs("warning")
      and f"  Steps backfill [5/10]: {_S[4]} {_EM} write_day failed (attempt 7)" in _rec.msgs("warning")
      and f"  Steps backfill [10/10]: {_S[9]} {_EM} error: api down" in _rec.msgs("warning"))
check("4s steps backfill: the loop goes on after each failing path, successes are logged with their position",
      f"  Steps backfill [1/10]: {_S[0]} {_EM} steps added" in _rec.msgs("info")
      and f"  Steps backfill [9/10]: {_S[8]} {_EM} steps added" in _rec.msgs("info"))
check("4s steps backfill: a 'steps' field that is not 'high' after record_attempt (medium, failed) is reported as blocked; "
      "'high' (also a run-time built string) is not",
      sum("quality_log update blocked" in m for m in _rec.msgs("warning")) == 2
      and any(m.startswith(f"  Steps backfill [6/10]: {_S[5]} {_EM} quality_log update blocked") for m in _rec.msgs("warning"))
      and any(m.startswith(f"  Steps backfill [7/10]: {_S[6]} {_EM} quality_log update blocked") for m in _rec.msgs("warning")))
check("4s steps backfill: source/ patch is retried once; a second failure is an error and is counted; the end line counts exactly",
      _pc == [_S[0], _S[5], _S[6], _S[7], _S[7], _S[8], _S[8]]
      and f"  Steps backfill [8/10]: {_S[7]} {_EM} source/ patch failed, retrying once ..." in _rec.msgs("warning")
      and any("source/ patch failed after retry" in m and m.startswith(f"  Steps backfill [8/10]: {_S[7]}")
              for m in _rec.msgs("error"))
      and sum("source/ patch failed after retry" in m for m in _rec.msgs("error")) == 1
      and "  Steps backfill complete: 5 enriched, 5 failed, 1 source/ patch(es) failed." in _rec.msgs("info"))
check("4s steps backfill: record_attempt for an enriched day carries written=True, source api, the steps hint and a timestamp",
      [c.args[1].isoformat() for c in _ra.call_args_list] == [_S[0], _S[5], _S[6], _S[7], _S[8]]
      and all(c.kwargs["written"] is True and c.kwargs["source"] == "api"
              and list(c.kwargs["backfilled_fields"]) == ["steps"]
              and len(c.kwargs["backfilled_fields"]["steps"]) == 19 for c in _ra.call_args_list)
      and all(c.args[3] == "Steps backfill: field added" for c in _ra.call_args_list))
_rec, _ra, _rf, _pc = _stp13(_S[:3], [_fld13(_S[0], "high")], _raws, _api, {}, {_S[0]: [True]},
                             stops=[False, True, False, False])
check("4s steps backfill: a stop request ends the list (it is not skipped over)",
      "  Steps backfill: stopped after 1 days." in _rec.msgs("info") and _ra.call_count == 1 and not _rf.called)

# -- _run_bulk_field_backfill ---------------------------------------------------------------------------------------------
_GAP = list(_col5.BULK_GAP_FIELDS)
_OPEN_SPEC = {"hrv": _rt11("high"), "spo2": "medium", "body_battery": "failed", "respiration": "high"}
_EXP_OPEN = ["spo2", "body_battery", "training_status", "race_predictions", "max_metrics"]


def _blk13(dates, fetch, entries, write_ok=None, fields_after=None, stops=None):
    rec, qd = _Rec11(), {"days": entries}
    with _cfg_values(SYNC_DATES=_dates13(dates)), \
            patch.object(_col5, "_fetch_and_assess", side_effect=fetch), \
            patch.object(_col5.writer, "read_raw", return_value={}), \
            patch.object(_col5.writer, "write_day", side_effect=lambda n, s, d: (write_ok or {}).get(d, True)), \
            patch.object(_col5.quality, "assess_quality_fields",
                         side_effect=lambda raw: (fields_after or {}).get(raw["date"], {})), \
            patch.object(_col5.quality, "record_attempt") as ra, \
            patch.object(_col5.quality, "record_field_backfill_failures") as rf, \
            patch.object(_col5, "_is_stopped", side_effect=_stopper13(stops) if stops else (lambda: False)), \
            patch.object(_col5, "log", rec):
        _col5._run_bulk_field_backfill(MagicMock(), qd)
    return rec, ra, rf


def _fetch_ok13(client, d):
    return "standard", {"date": d, "x": {"a": 1}}, {}, {}, _val13()


def _fetch_crit13(client, d):
    return "failed", None, None, {}, _val13()


def _fetch_err13(client, d):
    raise RuntimeError("api down")


def _bulk_entry13(d, fields):
    return {"date": d, "quality": "standard", "source": "bulk", "fields": fields}


_T = _BD[4]
_log13 = [{"date": "2030-01-01", "fields": {f: "high" for f in _GAP}},
          {"date": "2020-01-01", "fields": {f: "high" for f in _GAP}}]
_paths = {
    "validator critical": dict(fetch=_fetch_crit13),
    "write_day fails": dict(fetch=_fetch_ok13, write_ok={_T: False}),
    "success (open fields come from the merged fields)": dict(fetch=_fetch_ok13, fields_after={_T: _OPEN_SPEC}),
    "exception": dict(fetch=_fetch_err13),
}
for _name, _kw in _paths.items():
    _pre = {} if _name.startswith("success") else _OPEN_SPEC
    _rec, _ra, _rf = _blk13([_T], entries=_log13 + [_bulk_entry13(_T, _pre)], **_kw)
    check(f"4s bulk field backfill [{_name}]: the gap fields that are not 'high' are handed to "
          "record_field_backfill_failures (own log entry found by date; 'high' also as run-time built string)",
          _rf.call_count == 1 and _rf.call_args.args[1].isoformat() == _T and _rf.call_args.args[2] == _EXP_OPEN)
for _name, _kw in (("validator critical", dict(fetch=_fetch_crit13)), ("exception", dict(fetch=_fetch_err13))):
    for _label, _ent in (("no log entry for the day", list(_log13)),
                         ("an entry without fields", _log13 + [{"date": _T, "fields": None}]),
                         ("an entry with an empty field set", _log13 + [{"date": _T}])):
        _rec, _ra, _rf = _blk13([_T], entries=_ent, **_kw)
        check(f"4s bulk field backfill [{_name}]: {_label} -> every gap field is open",
              _rf.call_count == 1 and _rf.call_args.args[2] == _GAP)

_fa13 = {_BD[2]: {"hrv": "high"}, _BD[4]: {"hrv": "high"}}
_ents = _log13 + [_bulk_entry13(d, {}) for d in _BD[:5]]
_rec, _ra, _rf = _blk13(_BD[:5], lambda c, d: {_BD[0]: _fetch_crit13, _BD[3]: _fetch_err13}.get(d, _fetch_ok13)(c, d),
                        _ents, write_ok={_BD[1]: False}, fields_after=_fa13)
check("4s bulk field backfill: critical, write error, success, exception, success in a row — the loop goes on after "
      "each, progress counts from 1, the end line counts exactly",
      [c.args[1].isoformat() for c in _rf.call_args_list] == _BD[:5]
      and [m for m in _rec.msgs("warning")] == [
          f"  Bulk field backfill [1/5]: {_BD[0]} {_EM} validator critical, skipped",
          f"  Bulk field backfill [2/5]: {_BD[1]} {_EM} write_day failed",
          f"  Bulk field backfill [4/5]: {_BD[3]} {_EM} error: api down"]
      and "  Bulk field backfill complete: 2 processed, 3 failed." in _rec.msgs("info")
      and "  Bulk field backfill: 5 day(s) to re-fetch" in _rec.msgs("info"))
check("4s bulk field backfill: record_attempt for the processed days carries written=True, source api and the merged result",
      [c.args[1].isoformat() for c in _ra.call_args_list] == [_BD[2], _BD[4]]
      and all(c.kwargs["written"] is True and c.kwargs["source"] == "api" and c.kwargs["fields"] == {"hrv": "high"}
              and c.args[3] == f"Bulk field backfill: {c.args[2]}" for c in _ra.call_args_list)
      and [m for m in _rec.msgs("info") if m.startswith("  Bulk field backfill [")]
      == [f"  Bulk field backfill [3/5]: {_BD[2]} {_EM} {_ra.call_args_list[0].args[2]}",
          f"  Bulk field backfill [5/5]: {_BD[4]} {_EM} {_ra.call_args_list[1].args[2]}"])
_rec, _ra, _rf = _blk13(_BD[:3], _fetch_ok13, [], stops=[False, True, False, False])
check("4s bulk field backfill: a stop request ends the list (it is not skipped over)",
      _ra.call_count == 1 and "  Bulk field backfill: stopped after 1 days." in _rec.msgs("info"))

# ══════════════════════════════════════════════════════════════════════════════
#  4t. garmin_collector — capability scan and script entry
#      (v1.7.4.0.3, Group D4). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4t. garmin_collector — capability scan, script entry")
import runpy as _runpy14

_CAP14 = _col5.capability
_C14 = list(_CAP14.CANDIDATE_ENDPOINTS)
_TODAY14 = date.today()
_DATES14 = [(_TODAY14 - timedelta(days=d)).isoformat() for d in range(7)]


def _scan14(behaviour, window=None, stops=None):
    """run_capability_scan with a stubbed API: behaviour(endpoint, call number of that endpoint) -> (data, success)
    or an exception to raise. Returns (result, recorder, calls per endpoint, save_config mock)."""
    rec, calls = _Rec11(), {}

    def _api(client, endpoint, *args, label=None):
        calls.setdefault(endpoint, []).append(args)
        r = behaviour(endpoint, len(calls[endpoint]))
        if isinstance(r, Exception):
            raise r
        return r

    kw = {} if window is None else {"window_days": window}
    stop_it = iter(stops) if stops else None
    with patch.object(_col5.api, "api_call", side_effect=_api), \
            patch.object(_CAP14, "load_config", return_value=_CAP14._default_config()), \
            patch.object(_CAP14, "save_config") as sv, \
            patch.object(_col5, "_is_stopped", side_effect=(lambda: next(stop_it, False)) if stops else (lambda: False)), \
            patch.object(_col5, "log", rec):
        res = _col5.run_capability_scan(MagicMock(), **kw)
    return res, rec, calls, sv


def _mixed14(ep, n):
    if ep == _C14[0]:
        return ({"x": 1}, True) if n == 3 else (None, False)        # found on the third day, after two failures
    if ep == _C14[2]:
        return None, False                                          # fails every day
    if ep == _C14[3]:
        return RuntimeError("boom")                                 # raises
    return None, True                                               # answers, but with nothing


_res, _rec, _calls, _sv = _scan14(_mixed14)
_n = len(_C14)
_cfg14 = _sv.call_args.args[0]["endpoints"]
check("4t capability scan: counts per outcome are returned and logged exactly",
      _res == {"scanned": _n, "found": 1, "not_observed": _n - 3, "error": 2}
      and f"Capability scan complete: {_n} scanned, 1 found, {_n - 3} not observed, 2 error." in _rec.msgs("info")
      and _sv.call_count == 1)
check("4t capability scan: the window is the last 7 days, newest first; each endpoint is asked with its argument shape",
      _calls[_C14[1]] == [_CAP14.build_args(_C14[1], d) for d in _DATES14])
check("4t capability scan: a failed day does not end the endpoint's loop, a found day does (3 calls for the found endpoint); "
      "an endpoint that always fails is asked on every day",
      _calls[_C14[0]] == [_CAP14.build_args(_C14[0], d) for d in _DATES14[:3]]
      and len(_calls[_C14[2]]) == 7 and len(_calls[_C14[3]]) == 1)
_f, _o, _e, _x = (_cfg14[_C14[i]] for i in range(4))
check("4t capability scan: found after earlier failures stays 'found' with the discovery day and a timestamp",
      _f["status"] == "found" and _f["last_seen_with_data"] == _DATES14[2] and len(_f["discovered_at"]) == 19
      and _f["last_scan"] == _f["discovered_at"])
check("4t capability scan: 'not_observed' and 'error' carry only last_scan (no discovery data)",
      _o["status"] == "not_observed" and _e["status"] == "error" and _x["status"] == "error"
      and all(c["last_scan"] and c["discovered_at"] is None and c["last_seen_with_data"] is None for c in (_o, _e, _x)))
check("4t capability scan: progress counts from 1; an exception is logged for that candidate and the scan goes on",
      f"  Capability scan [1/{_n}]: {_C14[0]} — found" in _rec.msgs("info")
      and f"  Capability scan [2/{_n}]: {_C14[1]} — not_observed" in _rec.msgs("info")
      and f"  Capability scan [3/{_n}]: {_C14[2]} — error" in _rec.msgs("info")
      and f"  Capability scan [4/{_n}]: {_C14[3]} — error: boom" in _rec.msgs("warning")
      and f"  Capability scan [{_n}/{_n}]: {_C14[-1]} — not_observed" in _rec.msgs("info"))

_res, _rec, _calls, _sv = _scan14(lambda ep, n: (None, True), window=3)
check("4t capability scan: window_days sets the number of days asked per endpoint",
      all(len(v) == 3 for v in _calls.values()) and _res["not_observed"] == _n)

_res, _rec, _calls, _sv = _scan14(lambda ep, n: (None, True), stops=[False, True, False, False])
check("4t capability scan: a stop request ends the scan after the endpoints done so far (it is not skipped over)",
      _res["scanned"] == 1 and list(_calls) == [_C14[0]]
      and "  Capability scan: stopped after 1 endpoint(s)." in _rec.msgs("info"))

# -- script entry: `if __name__ == "__main__"` ------------------------------------------------------------------
with _isolated_log_env("main14") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _handlers14 = list(logging.getLogger().handlers)
    try:
        with patch.dict(os.environ, {"GARMIN_IMPORT_PATH": "unused"}), \
                patch("garmin_import.load_bulk", return_value=iter([])):
            try:
                _runpy14.run_path(_col5.__file__, run_name="".join(list("__main__")))
                _code14 = "main() did not run"
            except SystemExit as _e:
                _code14 = _e.code
    finally:
        for _h in list(logging.getLogger().handlers):
            if _h not in _handlers14:
                logging.getLogger().removeHandler(_h)
check("4t script entry: run as __main__ the file calls main() (import mode with nothing to import exits with 0)",
      _code14 == 0)

# ══════════════════════════════════════════════════════════════════════════════
#  4u. garmin_collector.main, part A — capability-scan entry, set-up, quality
#      log start, bulk upgrade, schema migration switch, device_id backfill,
#      first_day (v1.7.4.0.3, Group D5). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4u. garmin_collector.main A — entry, set-up, bulk upgrade, device_id backfill")

_SYNC1 = date(2024, 5, 1)
_TODAY15 = date.today()
_WINDOW15 = cfg.INTRADAY_RETRY_WINDOW_DAYS
_LE = "≤"
_EM15 = "—"


def _m15(**kw):
    """main() once with the collector's log recorded. Returns (exit code, exception, fetch mock, devices mock) and the recorder."""
    rec = _Rec11()
    with patch.object(_col5, "log", rec):
        out = _run_main(**kw)
    return out, rec


def _day_file15(d, content=None):
    d = str(d)
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / f"garmin_raw_{d}.json").write_text(json.dumps(content or _day_raw(d, "high")), encoding="utf-8")


def _log15(days, first_day="2024-01-01"):
    _put_log({"first_day": first_day, "devices": [], "days": days})


_API15 = {"quality": "high", "source": "api", "write": True}

# -- capability scan entry ---------------------------------------------------------------------------------------
with _isolated_log_env("main15cap") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _cl = MagicMock()
    _env = {"GARMIN_CAPABILITY_SCAN": "1"}
    with patch.object(_col5, "run_capability_scan", return_value={"error": 0}) as _rcs:
        (_code, _exc, _f, _), _ = _m15(env=_env, login=_cl)
        _calls = [(_code, _rcs.call_args.args == (_cl,), _rcs.call_args.kwargs)]
        (_code, _exc, _f, _), _ = _m15(env={**_env, "GARMIN_CAPABILITY_WINDOW_DAYS": "3"}, login=_cl)
        _calls.append((_code, _rcs.call_args.kwargs))
    check("4u main capability scan: with a login the scan runs for the configured window (default 7) and the run exits with 0",
          _calls == [(0, True, {"window_days": 7}), (0, {"window_days": 3})] and not _f.called)
    with patch.object(_col5, "run_capability_scan", return_value={"error": 2}):
        (_code, _exc, _f, _), _ = _m15(env=_env, login=_cl)
    check("4u main capability scan: errors in the scan -> exit code 1", _code == 1)
    with patch.object(_col5, "run_capability_scan") as _rcs:
        (_code, _exc, _f, _), _rec = _m15(env=_env, login_error=_col5.api.GarminLoginError("nope"))
        _c1 = (_code, _rcs.called, "Login failed — aborting capability scan: nope" in _rec.msgs("error"))
        (_code, _exc, _f, _), _rec = _m15(env=_env, login=None)
        _c2 = (_code, _exc, _rcs.called, "Login cancelled by user — aborting capability scan." in _rec.msgs("info"))
    check("4u main capability scan: a login error exits with 1 (no scan); a cancelled login returns cleanly (no scan)",
          _c1 == (1, False, True) and _c2 == (None, None, False, True))

# -- set-up: folders and session flags ---------------------------------------------------------------------------
with _isolated_log_env("main15dirs") as _b:
    _nested = dict(RAW_DIR=_b / "a" / "b" / "raw", SUMMARY_DIR=_b / "c" / "d" / "summary", LOG_DIR=_b / "e" / "f" / "log",
                   QUALITY_LOG_FILE=_b / "e" / "f" / "log" / "quality_log.json",
                   LOG_RECENT_DIR=_b / "recent", LOG_FAIL_DIR=_b / "fail")
    with _cfg_values(**_nested):
        (_code, _exc, _f, _), _ = _m15(login=None)
    check("4u main: raw/, summary/ and log/ are created including missing parent folders",
          _exc is None and all(_nested[k].is_dir() for k in ("RAW_DIR", "SUMMARY_DIR", "LOG_DIR")))

with _isolated_log_env("main15flags") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _log15([{"date": "2024-05-01", **_API15}])
    with _cfg_values(LOG_RECENT_DIR=_b / "recent", LOG_FAIL_DIR=_b / "fail", SYNC_DATES=[_SYNC1], REFRESH_FAILED=False,
                     MAX_DAYS_PER_SESSION=0):
        (_code, _exc, _f, _), _rec = _m15()
        check("4u main: a run with nothing to do keeps no failure log (the session flags start as False)",
              _code is None and _exc is None and not _f.called and "All days already present — nothing to do." in _rec.msgs("info")
              and list((_b / "fail").glob("*.log")) == [])
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": 1}, LOG_RECENT_DIR=_b / "recent", LOG_FAIL_DIR=_b / "fail"):
        (_code, _exc, _f, _), _ = _m15()
        check("4u main: a clean sync run keeps no failure log", _f.called and list((_b / "fail").glob("*.log")) == [])

# -- quality log at the start --------------------------------------------------------------------------------------
with _isolated_log_env("main15lowq") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _day_file15("2024-04-20", {"date": "2024-04-20"})
    _log15([{"date": "2024-05-01", **_API15}])
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _m15()
    check("4u main: a failed-quality raw file missing from the log gets an entry that counts as written",
          _qdays()["2024-04-20"]["write"] is True and _qdays()["2024-04-20"]["quality"] == "failed")

with _isolated_log_env("main15count") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _log15([{"date": "2024-04-01", **_API15, "recheck": True}, {"date": "2024-04-02", **_API15, "recheck": False},
            {"date": "2024-04-03", **_API15}])
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        _, _rec = _m15()
    check("4u main: the start line counts the tracked days and only the days with recheck=True",
          "  Quality log: 3 days tracked, 1 pending recheck" in _rec.msgs("info"))

# -- bulk upgrade ------------------------------------------------------------------------------------------------------
def _ago15(n):
    return (_TODAY15 - timedelta(days=n)).isoformat()


with _isolated_log_env("main15bulk") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _bulk = {"quality": "standard", "source": "bulk", "write": True}
    _log15([{**_bulk},                                                                  # no date, in front of the others
            {"date": _ago15(5), **_bulk},                                               # flagged (no recheck key)
            {"date": _ago15(6), **_bulk, "recheck": True},                              # already flagged
            {"date": _ago15(_WINDOW15), **_bulk, "recheck": False},                     # exactly at the cut-off: flagged
            {"date": _ago15(_WINDOW15 + 1), **_bulk, "recheck": False},                 # one day older: left alone
            {"date": _ago15(3), "quality": "high", "source": "api", "write": True},
            {"date": _ago15(4), "quality": "high", "source": "legacy", "write": True},
            {"date": _ago15(7), "quality": "high", "source": "aaa", "write": True},
            {"date": _ago15(8), "quality": "high", "source": "zzz", "write": True}])
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        (_code, _exc, _f, _), _rec = _m15()
    _q = _qdays()
    check("4u main bulk upgrade: bulk days up to the cut-off day (inclusive) are flagged — also when the recheck key is "
          "missing — older ones and other sources are not; an entry without a date in front does not stop the loop",
          _exc is None and _q[_ago15(5)]["recheck"] is True and _q[_ago15(_WINDOW15)]["recheck"] is True
          and _q[_ago15(6)]["recheck"] is True and _q[_ago15(_WINDOW15 + 1)]["recheck"] is False
          and all(not _q[_ago15(n)].get("recheck") for n in (3, 4, 7, 8)))
    check("4u main bulk upgrade: the flagged days are counted exactly (an already flagged day does not count)",
          f"  Bulk recheck: 2 day(s) flagged for API re-fetch ({_LE}{_WINDOW15} days, source=bulk)" in _rec.msgs("info"))

with _isolated_log_env("main15bulk0") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _log15([{"date": _ago15(3), **_API15}])
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        (_code, _exc, _f, _), _rec = _m15()
    check("4u main bulk upgrade: nothing to flag -> no 'Bulk recheck' line", not any("Bulk recheck" in m for m in _rec.msgs("info")))

# -- schema migration switch -------------------------------------------------------------------------------------------
with _isolated_log_env("main15mig") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _log15([{"date": "2024-05-01", **_API15}])
    _res = {}
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0):
        for _val in ("1", "0", "2", None):
            with patch.object(_col5, "_run_schema_migration") as _mig:
                _m15(env={"GARMIN_SCHEMA_MIGRATE": _val} if _val is not None else {})
            _res[_val] = (_mig.call_count, isinstance(_mig.call_args.args[0], dict) if _mig.called else None)
    check("4u main: GARMIN_SCHEMA_MIGRATE=1 (and only that value) runs the schema migration with the quality log",
          _res == {"1": (1, True), "0": (0, None), "2": (0, None), None: (0, None)})

# -- device_id backfill ---------------------------------------------------------------------------------------------
_DV = [f"2024-03-{n:02d}" for n in range(1, 13)]


def _ts15(**kw):
    return {"training_status": {"mostRecentTrainingStatus": kw}}


with _isolated_log_env("main15dev") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _raws = {
        _DV[1]: {"date": _DV[1]},                                                              # no training status
        _DV[2]: {"date": _DV[2], "training_status": {"mostRecentTrainingStatus": "x"}},       # not a dict
        _DV[3]: {"date": _DV[3]},                                                              # (reader raises below)
        _DV[4]: {"date": _DV[4], **_ts15(recordedDevices=[{"deviceId": 777, "deviceName": "Fenix"},
                                                          {"deviceId": 888, "deviceName": "Edge"}])},
        _DV[5]: {"date": _DV[5], **_ts15(latestTrainingStatusData=[1])},                      # a list, not a dict
        _DV[6]: {"date": _DV[6], **_ts15(latestTrainingStatusData={"999": {}})},
        _DV[7]: {"date": _DV[7], **_ts15(recordedDevices=[{"deviceId": 111, "deviceName": "Other"}])},
        _DV[8]: {"date": _DV[8], **_ts15(recordedDevices=[{"deviceId": 222, "deviceName": "Other"}])},
        _DV[9]: {"date": _DV[9], **_ts15(recordedDevices=[{"deviceId": 333, "deviceName": "BulkDev"}])},
        _DV[10]: {"date": _DV[10], **_ts15(recordedDevices=[{"deviceId": 444, "deviceName": "LegacyDev"}])},
    }
    for _d, _r in _raws.items():
        _day_file15(_d, _r)
    _log15([{"date": _DV[0], **_API15},                                                       # no raw file
            {"date": _DV[1], **_API15}, {"date": _DV[2], **_API15}, {"date": _DV[3], **_API15},
            {"date": _DV[4], **_API15}, {"date": _DV[5], **_API15}, {"date": _DV[6], **_API15},
            {"date": _DV[7], **_API15, "device_id": "55"},                                     # has one already
            {"date": _DV[8], "quality": "high", "source": "aaa", "write": True},               # other source
            {"date": _DV[9], "quality": "high", "source": "bulk", "write": True},
            {"date": _DV[10], "quality": "high", "source": "legacy", "write": True},
            {"date": "2024-05-01", **_API15, "device_id": "1"}])
    _real_read = writer.read_raw

    def _read_raising(d):
        if d == _DV[3]:
            raise OSError("raw file locked")
        return _real_read(d)

    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0), \
            patch.object(_col5.writer, "read_raw", side_effect=_read_raising), \
            patch.object(_col5.quality, "save_device_table") as _sdt:
        (_code, _exc, _f, _), _rec = _m15()
    _q = _qdays()
    check("4u main device_id backfill: only entries without a device_id from api/bulk/legacy are processed",
          _exc is None and _q[_DV[7]]["device_id"] == "55" and _q[_DV[8]].get("device_id") is None)
    check("4u main device_id backfill: first recorded device wins; training-status keys are the fallback; "
          "a non-dict value gives no device; a missing raw file, no training status and a failing reader "
          "do not stop the later entries",
          (_q[_DV[4]]["device_id"], _q[_DV[4]]["device_name"]) == ("777", "Fenix")
          and (_q[_DV[6]]["device_id"], _q[_DV[6]]["device_name"]) == ("999", "")
          and _q[_DV[5]].get("device_id") is None
          and _q[_DV[9]]["device_id"] == "333" and _q[_DV[10]]["device_id"] == "444")
    check("4u main device_id backfill: the number of entries to process and the number updated are logged exactly; "
          "the device table is rewritten",
          "  device_id backfill: 9 entries to process ..." in _rec.msgs("info")
          and "  device_id backfill: 4 entries updated" in _rec.msgs("info") and _sdt.call_count == 1)

with _isolated_log_env("main15dev0") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _day_file15(_DV[0], {"date": _DV[0]})
    _log15([{"date": _DV[0], **_API15}, {"date": "2024-05-01", **_API15, "device_id": "1"}])
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0), \
            patch.object(_col5.quality, "save_device_table") as _sdt:
        (_code, _exc, _f, _), _rec = _m15()
    check("4u main device_id backfill: nothing found -> a note instead of 'updated', no device table rewrite",
          "  device_id backfill: no raw files with training_status found" in _rec.msgs("info")
          and not any("entries updated" in m for m in _rec.msgs("info")) and _sdt.call_count == 0)

# -- first_day ----------------------------------------------------------------------------------------------------------
with _isolated_log_env("main15fd") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_SYNC1)
    _cl = MagicMock()
    _log15([{"date": "2024-05-01", **_API15}], first_day="2024-01-01")
    with _cfg_values(SYNC_DATES=[_SYNC1], REFRESH_FAILED=False, MAX_DAYS_PER_SESSION=0), \
            patch.object(_col5.quality, "_set_first_day") as _sfd:
        _m15(login=_cl)
        _with_fd = _sfd.call_count
        _put_log({"devices": [], "days": [{"date": "2024-05-01", **_API15}]})
        _m15(login=_cl)
    check("4u main: _set_first_day is called (with the quality data and the client) only when the log has no first_day",
          _with_fd == 0 and _sfd.call_count == 1 and isinstance(_sfd.call_args.args[0], dict)
          and _sfd.call_args.args[1] is _cl)

# ══════════════════════════════════════════════════════════════════════════════
#  4v. garmin_collector.main, part B1 — date list, exclusions, messages, session
#      limit, counters (v1.7.4.0.3, Group D6a). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4v. garmin_collector.main B1 — date list, exclusions, session limit")

_R16 = [f"2024-05-0{n}" for n in range(1, 6)]


def _rng16(limit=0, refresh=False, fetch=None):
    """main() in range mode 2024-05-01..05-05. Returns (exception, fetched dates, recorder)."""
    kw = {"fetch": fetch} if fetch else {}
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": limit, "REFRESH_FAILED": refresh}):
        (_code, _exc, _f, _), _rec = _m15(**kw)
    return _exc, _fetched_dates(_f), _rec


# -- which days are fetched again: recheck days and bulk upgrade days -------------------------------------------------
_ENTRIES16 = [
    {"date": _R16[0], "quality": "high", "source": "api", "write": True, "recheck": True},
    {"date": _R16[1], "quality": "standard", "source": "bulk", "write": True, "recheck": True},
    {"date": _R16[2], "quality": "high", "source": "api", "write": True, "recheck": False},
    {"date": _R16[3], "quality": "high", "source": "aaa", "write": True, "recheck": True},
    {"date": _R16[4], "quality": "standard", "source": "bulk", "write": True, "recheck": False},
]
with _isolated_log_env("main16ex") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _d in _R16:
        _day_file15(_d)
    _log15(_ENTRIES16)
    _exc, _fd, _rec = _rng16(refresh=False)
    check("4v main: without REFRESH_FAILED only the bulk days flagged for re-fetch are fetched again (not api / other-source recheck days)",
          _exc is None and _fd == [_R16[1]]
          and "  Bulk upgrade: 1 day(s) queued for API re-fetch" in _rec.msgs("info"))
    _log15(_ENTRIES16)
    _exc, _fd, _rec = _rng16(refresh=True)
    check("4v main: with REFRESH_FAILED every recheck day is fetched again; bulk days are added to, not taken out of, that set",
          _exc is None and _fd == [_R16[0], _R16[1], _R16[3]])
with _isolated_log_env("main16ex0") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _d in _R16:
        _day_file15(_d)
    _log15([{"date": _R16[0], "quality": "high", "source": "api", "write": True, "recheck": True},
            {"date": _R16[1], "quality": "high", "source": "legacy", "write": True, "recheck": True},
            {"date": _R16[2], "quality": "high", "source": "zzz", "write": True, "recheck": True}])
    _exc, _fd, _rec = _rng16(refresh=False)
    check("4v main: no bulk day flagged (recheck days of api, legacy and other sources do not count) and no REFRESH_FAILED "
          "-> nothing to fetch, no 'Bulk upgrade' line",
          _exc is None and _fd == [] and not any("Bulk upgrade" in m for m in _rec.msgs("info")))

# -- SYNC_DATES mode --------------------------------------------------------------------------------------------------
with _isolated_log_env("main16sd") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15("2024-05-01")
    _res = {}
    for _refresh in (False, True):
        _log15([{"date": "2024-05-01", **_API15}])
        with _cfg_values(SYNC_DATES=[date(2024, 5, 1), date(2024, 5, 6)], REFRESH_FAILED=_refresh, MAX_DAYS_PER_SESSION=0):
            (_code, _exc, _f, _), _rec = _m15()
        _res[_refresh] = (_fetched_dates(_f), _rec.msgs("info"))
    check("4v main SYNC_DATES: only requested days without a local file are fetched; with REFRESH_FAILED all requested days",
          _res[False][0] == ["2024-05-06"] and _res[True][0] == ["2024-05-01", "2024-05-06"])
    check("4v main SYNC_DATES: the request, the number to fetch and 'Fetching N specific days' are logged exactly",
          "  SYNC_DATES mode: 2 requested, 1 to fetch" in _res[False][1] and "Fetching 1 specific days ..." in _res[False][1]
          and "  SYNC_DATES mode: 2 requested, 2 to fetch" in _res[True][1] and "Fetching 2 specific days ..." in _res[True][1])

# -- messages in range mode ---------------------------------------------------------------------------------------------
with _isolated_log_env("main16msg") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _day_file15(_R16[0])
    _day_file15(_R16[4])
    _log15([{"date": _R16[0], **_API15}, {"date": _R16[4], **_API15}])
    _exc, _fd, _rec = _rng16()
    check("4v main: the local and missing day counts and the first and last missing day are logged exactly",
          _fd == _R16[1:4] and "Local: 2 days  |  Missing: 3 days" in _rec.msgs("info")
          and f"Fetching {_R16[1]} to {_R16[3]} ..." in _rec.msgs("info"))

# -- session limit ---------------------------------------------------------------------------------------------------------
_LIM = {}
for _limit in (0, 1, 2, 5, 7):
    with _isolated_log_env(f"main16lim{_limit}") as _b:
        cfg.SUMMARY_DIR = _b / "summary"
        _log15([])
        _exc, _fd, _rec = _rng16(limit=_limit)
        _LIM[_limit] = (_fd, [m for m in _rec.msgs("info") if m.startswith("  Session limit:")])
check("4v main session limit: 0 = no limit; a limit below the number of missing days caps the batch and says so; "
      "a limit equal to or above it changes nothing and says nothing",
      _LIM[0] == (_R16, []) and _LIM[5] == (_R16, []) and _LIM[7] == (_R16, [])
      and _LIM[1] == (_R16[:1], ["  Session limit: processing 1 of 5 missing days (MAX_DAYS_PER_SESSION=1)"])
      and _LIM[2] == (_R16[:2], ["  Session limit: processing 2 of 5 missing days (MAX_DAYS_PER_SESSION=2)"]))

# a negative limit is refused outright, named in the message, before anything else runs
with _isolated_log_env("main16limneg") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _log15([])
    with _cfg_values(**{**_RANGE, "MAX_DAYS_PER_SESSION": -1}):
        (_code, _exc, _fetch, _), _rec = _m15()
    check("main session limit: a negative value aborts before login, names the setting",
          _code == 1 and not _fetch.called
          and any("GARMIN_MAX_DAYS_PER_SESSION" in m for m in _rec.msgs("error")))

# -- counters --------------------------------------------------------------------------------------------------------------
def _fetch_boom_on_03(client, date_str, extra_endpoints=None):
    if date_str == _R16[2]:
        raise RuntimeError("Garmin said no")
    return _day_raw(date_str, "high"), []


with _isolated_log_env("main16cnt") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _log15([])
    _exc, _fd, _rec = _rng16()
    check("4v main: a clean run ends with 'Done. 5 saved, 0 errors.'", "Done. 5 saved, 0 errors." in _rec.msgs("info"))
with _isolated_log_env("main16cnt2") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _log15([])
    _exc, _fd, _rec = _rng16(fetch=_fetch_boom_on_03)
    check("4v main: one failing day -> 'Done. 4 saved, 1 errors.'", "Done. 4 saved, 1 errors." in _rec.msgs("info"))

# ══════════════════════════════════════════════════════════════════════════════
#  4w. garmin_collector.main, part B2 — fetch loop, downgrade guard, prev_high,
#      device, closing lines, source backup backfill (v1.7.4.0.3, Group D6b).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4w. garmin_collector.main B2 — fetch loop, downgrade guard, device, closing lines")

_OKM = "✓"
_WARN17 = "⚠"
_INFO17 = "ℹ"


def _std_day17(d):
    return _day_raw(d, "std")


def _fetch_kind17(kinds):
    """fetch_raw stub: kinds maps date -> 'high' / 'std' / 'failed' / raw dict / exception."""
    def _f(client, date_str, extra_endpoints=None):
        k = kinds.get(date_str, "high")
        if isinstance(k, Exception):
            raise k
        if isinstance(k, dict):
            return k, []
        return ({"date": date_str} if k == "failed" else _day_raw(date_str, k)), []
    return _f


def _run17(dates, entries, fetch, refresh=True, devices=None, env=None, stops=None, patches=(), name="x"):
    """main() in SYNC_DATES mode with a prepared quality log. Returns (exception, fetched dates, recorder, fail logs)."""
    with _isolated_log_env(f"main17{name}") as _b:
        cfg.SUMMARY_DIR = _b / "summary"
        _log15(entries)
        with _cfg_values(SYNC_DATES=[date.fromisoformat(d) for d in dates], REFRESH_FAILED=refresh,
                         MAX_DAYS_PER_SESSION=0, LOG_RECENT_DIR=_b / "recent", LOG_FAIL_DIR=_b / "fail"):
            from contextlib import ExitStack
            with ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                if stops:
                    it = iter(stops)
                    stack.enter_context(patch.object(_col5, "_is_stopped", side_effect=lambda: next(it, False)))
                (_code, _exc, _f, _), _rec = _m15(fetch=fetch, devices=devices, env=env)
        _q = _qdays()
        return _exc, _fetched_dates(_f), _rec, len(list((_b / "fail").glob("*.log"))), _q


_D17 = [f"2024-05-0{n}" for n in range(1, 8)]
_H = {"quality": "high", "write": True}

# -- capability line, progress, stop --------------------------------------------------------------------------------
_CAPCFG = _col5.capability.update_endpoint(_col5.capability._default_config(), "get_floors", "found", enabled_by_user=True)
_exc, _fd, _rec, _fl, _q = _run17(_D17[:3], [], _fetch_kind17({}), name="cap",
                                  patches=[patch.object(_col5.capability, "load_config", return_value=_CAPCFG)])
check("4w main: the number of capability-enabled endpoints is logged; progress counts from 1",
      "  Capability-enabled endpoints this run: 1" in _rec.msgs("info")
      and [m for m in _rec.msgs("info") if m.startswith("  [")] == [f"  [{i}/3] {d}" for i, d in enumerate(_D17[:3], 1)])
_exc, _fd, _rec, _fl, _q = _run17(_D17[:3], [], _fetch_kind17({}), name="nocap")
check("4w main: no enabled capability endpoint -> no such line",
      not any("Capability-enabled" in m for m in _rec.msgs("info")))
_exc, _fd, _rec, _fl, _q = _run17(_D17, [], _fetch_kind17({}), name="stop", stops=[False, True, False, False])
check("4w main: a stop request ends the loop after the days done so far (it is not skipped over)",
      _fd == [_D17[0]] and "  Stopped after 1 days saved." in _rec.msgs("info") and "Done. 1 saved, 0 errors." in _rec.msgs("info"))

# -- downgrade guard ---------------------------------------------------------------------------------------------------
_BULK = {"source": "bulk", **_H}
_ents = [
    {"date": "2030-01-01", **_BULK, "attempts": 9, "recheck": True},                  # decoys in front
    {"date": "2020-01-01", **_BULK, "attempts": 9, "recheck": True},
    {"date": _D17[0], **_BULK, "attempts": 0, "recheck": True},
    {"date": _D17[1], **_BULK, "attempts": 1, "recheck": True},
    {"date": _D17[2], "source": "api", **_H, "attempts": 3, "recheck": False},
    {"date": _D17[3], "source": "aaa", **_H, "attempts": 2, "recheck": False},
    {"date": _D17[4], "source": "zzz", **_H, "attempts": 2, "recheck": False},
    {"date": _D17[6], **_BULK, "attempts": 5, "recheck": True},
]
_kinds = {d: "std" for d in (_D17[0], _D17[1], _D17[2], _D17[3], _D17[4], _D17[6])}      # worse than the stored 'high'; _D17[5] has no entry
_exc, _fd, _rec, _fl, _q = _run17(_D17, _ents, _fetch_kind17(_kinds), name="down")
check("4w main downgrade: a worse API result keeps the stored quality and source for every day, "
      "every such day counts as saved and the loop goes on (the normal day after them is written)",
      _exc is None and all(_q[d]["quality"] == "high" for d in _D17[:5] + [_D17[6]])
      and (_q[_D17[0]]["source"], _q[_D17[2]]["source"], _q[_D17[3]]["source"], _q[_D17[4]]["source"])
      == ("bulk", "api", "aaa", "zzz")
      and _q[_D17[5]]["write"] is True and _q[_D17[5]]["source"] == "api"
      and "Done. 7 saved, 0 errors." in _rec.msgs("info"))
check("4w main downgrade: a bulk day counts its attempts (1, 2, 6) and keeps the recheck only below 2 attempts "
      "— each on its own entry, not on a decoy",
      (_q[_D17[0]]["attempts"], _q[_D17[0]]["recheck"]) == (1, True)
      and (_q[_D17[1]]["attempts"], _q[_D17[1]]["recheck"]) == (2, False)
      and (_q[_D17[6]]["attempts"], _q[_D17[6]]["recheck"]) == (6, False)
      and (_q["2030-01-01"]["attempts"], _q["2020-01-01"]["attempts"]) == (9, 9))
check("4w main downgrade: reasons carry the attempts only for bulk days; the exhausted recheck is announced",
      _q[_D17[0]]["reason"] == "Quality: high — API downgrade rejected (1 attempts)"
      and _q[_D17[1]]["reason"] == "Quality: high — API downgrade rejected (2 attempts)"
      and _q[_D17[6]]["reason"] == "Quality: high — API downgrade rejected (6 attempts)"
      and all(_q[d]["reason"] == "Quality: high — API downgrade rejected" for d in _D17[2:5])
      and f"    {_INFO17} {_D17[1]}: bulk recheck exhausted after 2 attempts — accepted" in _rec.msgs("info")
      and f"    {_INFO17} {_D17[6]}: bulk recheck exhausted after 6 attempts — accepted" in _rec.msgs("info")
      and not any(d in m and "exhausted" in m for d in [_D17[0]] + _D17[2:5] for m in _rec.msgs("info"))
      and sum("bulk recheck exhausted" in m for m in _rec.msgs("info")) == 2
      and f"    {_WARN17} API result inferior (standard < high) — kept existing" in _rec.msgs("warning"))

# -- prev_high -----------------------------------------------------------------------------------------------------------
_PD = ["2024-06-02", "2024-06-04", "2024-06-06", "2024-06-09"]
_ents = [
    {"date": "2030-06-01", "quality": "high", "write": True, "source": "api"},          # decoys in front
    {"date": "2020-06-01", "quality": "high", "write": True, "source": "api"},
    {"date": "2024-06-01", "quality": "high", "write": True, "source": "api"},          # day before _PD[0]
    {"date": "2024-06-03", "quality": "standard", "write": True, "source": "api"},      # day before _PD[1] (and after _PD[0])
    {"date": "2024-06-05", "quality": "failed", "write": True, "source": "api"},        # day before _PD[2]
]
_spy = patch.object(_col5.quality, "record_attempt", wraps=quality.record_attempt)
with _spy as _ra:
    _exc, _fd, _rec, _fl, _q = _run17(_PD, _ents, _fetch_kind17({}), name="prev", patches=[])
_ph = {c.args[1].isoformat(): c.kwargs.get("prev_high") for c in _ra.call_args_list}
check("4w main: prev_high is True only when the previous calendar day is in the log with quality 'high'",
      _ph == {_PD[0]: True, _PD[1]: False, _PD[2]: False, _PD[3]: False})

# -- device and message line ------------------------------------------------------------------------------------------
_DEVS = [{"id": 100, "name": "Low"}, {"id": 999, "name": "High"}, {"id": 555, "name": "Edge"}, {"id": 555, "name": "Dup"},
         {"id": 888, "name": ""}]


def _ts17(d, lts):
    raw = _day_raw(d, "high")
    raw["training_status"] = {"mostRecentTrainingStatus": {"latestTrainingStatusData": lts}}
    return raw


_DD = ["2024-07-01", "2024-07-02", "2024-07-03", "2024-07-04", "2024-07-05"]
_kinds = {_DD[0]: _ts17(_DD[0], {"555": {}}), _DD[1]: _ts17(_DD[1], [1]), _DD[2]: _ts17(_DD[2], {"777": {}}),
          _DD[3]: _ts17(_DD[3], {"888": {}}), _DD[4]: "failed"}
_exc, _fd, _rec, _fl, _q = _run17(_DD, [], _fetch_kind17(_kinds), devices=_DEVS, name="dev")
check("4w main device: the id is the first training-status key, named from the device list (first match, ids sorted "
      "before and after it do not matter); a list instead of a dict gives no device",
      (_q[_DD[0]]["device_id"], _q[_DD[0]]["device_name"]) == ("555", "Edge")
      and _q[_DD[1]]["device_id"] is None
      and (_q[_DD[2]]["device_id"], _q[_DD[3]]["device_id"]) == ("777", "888"))
_info = _rec.msgs("info")
check("4w main device: the result line names the quality and, with a device, the name (or the id when there is no name)",
      f"    {_OKM} Quality: high [device=Edge]" in _info and f"    {_OKM} Quality: high" in _info
      and f"    {_OKM} Quality: high [device=777]" in _info and f"    {_OKM} Quality: high [device=888]" in _info
      and not any("device=None" in m for m in _info))
check("4w main: a failed day is a warning, keeps the session log in log/fail/ and is the only pending recheck; "
      "the closing line counts exactly",
      f"    {_WARN17} Fetch failed (failed) — flagged for recheck" in _rec.msgs("warning") and _fl == 1
      and "Quality log: 5 days tracked, 1 pending recheck" in _info)
_exc, _fd, _rec, _fl, _q = _run17(_D17[:2], [], _fetch_kind17({_D17[1]: "std"}), name="clean")
check("4w main: high and standard days keep no failure log and are logged with their quality",
      _fl == 0 and f"    {_OKM} Quality: high" in _rec.msgs("info") and f"    {_OKM} Quality: standard" in _rec.msgs("info")
      and not _rec.msgs("warning"))

# -- source backup backfill at the end -----------------------------------------------------------------------------------
def _bk17(needed, ok_days=1, env=None):
    kinds = {} if ok_days else {d: RuntimeError("boom") for d in _D17[:1]}
    chk = patch.object(_bsrc12, "check_source_backfill_needed", return_value=needed)
    run = patch.object(_bsrc12, "backfill_source", return_value={"copied": 2, "skipped": 1, "failed": 0})
    sb = patch.object(_col5, "_run_source_backfill")
    with chk as c, run as r, sb:
        _exc, _fd, _rec, _fl, _q = _run17(_D17[:1], [], _fetch_kind17(kinds), env=env, name=f"bk{needed}{ok_days}{(env or {}).get('GARMIN_SOURCE_BACKFILL', 'n')}")
    return c.call_count, r.call_count, _rec.msgs("info")


_c, _r, _i = _bk17(3)
check("4w main source backup backfill: after a day was processed the missing source backups are counted, copied and reported",
      (_c, _r) == (1, 1) and "  Source backup backfill: 3 file(s) without backup — running ..." in _i
      and "  Source backup backfill done: 2 copied, 1 skipped, 0 failed." in _i)
_c, _r, _i = _bk17(0)
check("4w main source backup backfill: nothing missing -> counted, but not run and not reported",
      (_c, _r) == (1, 0) and not any("Source backup backfill" in m for m in _i))
_c, _r, _i = _bk17(3, ok_days=0)
check("4w main source backup backfill: no processed day -> not even counted", (_c, _r) == (0, 0))
_c, _r, _i = _bk17(3, env={"GARMIN_SOURCE_BACKFILL": "1"})
check("4w main source backup backfill: not during a source backfill run (GARMIN_SOURCE_BACKFILL=1)", (_c, _r) == (0, 0))
_c, _r, _i = _bk17(3, env={"GARMIN_SOURCE_BACKFILL": "0"})
check("4w main source backup backfill: GARMIN_SOURCE_BACKFILL=0 does not block it", (_c, _r) == (1, 1))

summary()
