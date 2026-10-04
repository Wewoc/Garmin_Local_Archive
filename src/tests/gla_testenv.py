#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/gla_testenv.py
Garmin Local Archive — shared test environment for the per-module test files

Importing this module (before any garmin_* module) does the setup that used to be
the head of test_local.py: puts src/garmin on sys.path, disables logging, creates
one temp folder as BASE_DIR (GARMIN_OUTPUT_DIR) and imports garmin_config.
The temp folder is removed again when the interpreter exits.

It also holds the helpers and fixtures that more than one test file needs.
Everything a module needs that only that module's tests use stays in that test file.

Usage in a test file:
    from gla_testenv import cfg, _TMPDIR, _isolated_log_env, ...
    from support import check, section, summary
"""

import atexit
import contextlib
import importlib
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Path setup — works when run from project folder or elsewhere ───────────────
_TESTS_DIR = Path(__file__).parent
_SRC_ROOT = _TESTS_DIR.parent
sys.path.insert(0, str(_SRC_ROOT / "garmin"))
sys.path.insert(0, str(_TESTS_DIR))
logging.disable(logging.CRITICAL)

# ── Temp directory as BASE_DIR ─────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_test_"))
os.environ["GARMIN_OUTPUT_DIR"]           = str(_TMPDIR)
os.environ["GARMIN_SYNC_MODE"]            = "recent"
os.environ["GARMIN_DAYS_BACK"]            = "7"
os.environ["GARMIN_SYNC_DATES"]           = ""
os.environ["GARMIN_REFRESH_FAILED"]       = "0"
os.environ["GARMIN_MAX_DAYS_PER_SESSION"] = "30"


def cleanup():
    shutil.rmtree(_TMPDIR, ignore_errors=True)


atexit.register(cleanup)

import garmin_config as cfg  # noqa: E402

importlib.reload(cfg)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def make_raw_full():
    """A raw day with sleep, heart rate, steps and one activity (fresh copy)."""
    return {
        "date": "2024-03-15",
        "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 28800, "deepSleepSeconds": 5400}},
        "heart_rates": {"restingHeartRate": 52, "heartRateValues": [[0, 52], [60, 55]]},
        "user_summary": {"totalSteps": 8500, "dailyStepGoal": 10000},
        "activities": [{"activityName": "Run", "activityType": {"typeKey": "running"},
                        "duration": 3600, "distance": 8000}],
    }


raw_full = make_raw_full()
mock_client = MagicMock()


def _day_raw(d, kind="high", device=None):
    raw = {"date": d}
    if kind == "high":
        raw["heart_rates"] = {"restingHeartRate": 55,
                              "heartRateValues": [[1740787200000, 58]]}
    else:
        raw["stats"] = {"totalSteps": 1000}
    if device:
        raw["training_status"] = {"mostRecentTrainingStatus": {
            "recordedDevices": [{"deviceId": device[0], "deviceName": device[1]}]}}
    return raw


# ── Config / log isolation ─────────────────────────────────────────────────────

@contextlib.contextmanager
def _isolated_log_env(name):
    """Point cfg's log/raw/backup paths at a fresh folder; restore afterwards."""
    base = _TMPDIR / f"iso_{name}"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    names = ("LOG_DIR", "QUALITY_LOG_FILE", "DEVICE_TABLE_FILE", "RAW_DIR",
             "LOG_BACKUP_DIR", "AUTORESTORE_DIR", "RAW_BACKUP_DIR",
             "SOURCE_DIR", "SOURCE_BACKUP_DIR", "SUMMARY_DIR")
    saved = {n: getattr(cfg, n) for n in names}
    cfg.LOG_DIR           = base / "log"
    cfg.QUALITY_LOG_FILE  = base / "log" / "quality_log.json"
    cfg.DEVICE_TABLE_FILE = base / "log" / "device_table.json"
    cfg.RAW_DIR           = base / "raw"
    cfg.LOG_BACKUP_DIR    = base / "backup_log"
    cfg.AUTORESTORE_DIR   = base / "autorestore"
    cfg.RAW_BACKUP_DIR    = base / "backup_raw"
    cfg.SOURCE_DIR        = base / "source"
    cfg.SOURCE_BACKUP_DIR = base / "backup_source"
    cfg.LOG_DIR.mkdir(parents=True)
    try:
        yield base
    finally:
        for n, v in saved.items():
            setattr(cfg, n, v)


@contextlib.contextmanager
def _cfg_values(**kw):
    saved = {k: getattr(cfg, k) for k in kw}
    for k, v in kw.items():
        setattr(cfg, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(cfg, k, v)


def _put_log(obj):
    cfg.QUALITY_LOG_FILE.write_text(json.dumps(obj), encoding="utf-8")


def _qdays():
    import garmin_quality as quality
    return {e["date"]: e for e in quality._load_quality_log()["days"] if "date" in e}


def _fail_logs_with(text):
    """Session logs kept in log/fail/ that contain the given text."""
    if not cfg.LOG_FAIL_DIR.exists():
        return []
    return [p for p in cfg.LOG_FAIL_DIR.glob("garmin_*.log")
            if text in p.read_text(encoding="utf-8", errors="replace")]


# ── Containers ─────────────────────────────────────────────────────────────────

_EMPTY_SRC = _TMPDIR / "gla_testenv_empty_src"


def _craft_container(path, sections, password="pw"):
    """Pack hand-made {section: {relative path: bytes}} into a real container.

    garmin_container.lock() imports version.APP_VERSION; the caller makes sure a
    'version' module is registered (see the container and mirror tests)."""
    import garmin_container as gc
    _EMPTY_SRC.mkdir(parents=True, exist_ok=True)

    def _fake_collect(_src):
        data = {s: {} for s in gc._SECTIONS}
        data.update(sections)
        data["_errors"] = 0
        return data
    with patch.object(gc, "_collect_sections", _fake_collect):
        return gc.lock(_EMPTY_SRC, path, password)


def _flip_byte(src, dst, index):
    """Copy a container and flip all bits of one byte (index < 0 counts from the end)."""
    data = bytearray(Path(src).read_bytes())
    data[index] ^= 0xFF
    Path(dst).write_bytes(bytes(data))


# ── Collector run ──────────────────────────────────────────────────────────────

_UNSET = object()


def _default_fetch(client, date_str, extra_endpoints=None):
    return _day_raw(date_str, "high"), []


def _run_main(fetch=_default_fetch, login=_UNSET, login_error=None, devices=None,
              devices_error=None, stop_event=None, env=None):
    """Runs collector.main() once. Returns (exit_code, exception, fetch_mock, devices_mock)."""
    import garmin_collector as col
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    # The suite disables logging globally; the session log (a file the tests read)
    # needs records, so logging is switched on for the duration of this run only.
    _disable_before, _level_before = logging.root.manager.disable, root.level
    logging.disable(logging.NOTSET)
    root.setLevel(logging.DEBUG)
    login_kw = ({"side_effect": login_error} if login_error is not None
                else {"return_value": MagicMock() if login is _UNSET else login})
    dev_kw = ({"side_effect": devices_error} if devices_error is not None
              else {"return_value": [] if devices is None else devices})
    exit_code, exc = None, None
    with patch("garmin_collector.api.login", **login_kw), \
         patch("garmin_collector.api.get_devices", **dev_kw) as _dev, \
         patch("garmin_collector.api.fetch_raw", side_effect=fetch) as _fetch, \
         patch.dict(os.environ, env or {}):
        try:
            col.main(stop_event)
        except SystemExit as e:
            exit_code = e.code
        except Exception as e:                # noqa: BLE001 - the test inspects it
            exc = e
    logging.disable(_disable_before)
    root.setLevel(_level_before)
    for h in list(root.handlers):             # a main() that aborted early leaves its session log open
        if h not in handlers_before:
            root.removeHandler(h)
            h.close()
    col.set_stop_event(None)
    return exit_code, exc, _fetch, _dev


def _fetched_dates(fetch_mock):
    return sorted(c.args[1] for c in fetch_mock.call_args_list)
