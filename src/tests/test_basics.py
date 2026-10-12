#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_basics.py — config, sync and utils

Run from the project folder:
    python tests/test_basics.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import os
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  1. garmin_config
# ══════════════════════════════════════════════════════════════════════════════
section("1. garmin_config")
importlib.reload(cfg)

check("BASE_DIR from ENV",              cfg.BASE_DIR == _TMPDIR)
check("RAW_DIR derived",                cfg.RAW_DIR == _TMPDIR / "garmin_data" / "raw")
check("SUMMARY_DIR derived",            cfg.SUMMARY_DIR == _TMPDIR / "garmin_data" / "summary")
check("LOG_DIR derived",                cfg.LOG_DIR == _TMPDIR / "garmin_data" / "log")
check("QUALITY_LOG_FILE derived",       cfg.QUALITY_LOG_FILE == _TMPDIR / "garmin_data" / "log" / "quality_log.json")
check("GARMIN_TOKEN_DIR derived",       cfg.GARMIN_TOKEN_DIR  == _TMPDIR / "garmin_data" / "log" / "garmin_token")
check("GARMIN_TOKEN_FILE derived",      cfg.GARMIN_TOKEN_FILE == _TMPDIR / "garmin_data" / "log" / "garmin_token.enc")
check("SYNC_MODE = recent",             cfg.SYNC_MODE == "recent")
check("MAX_DAYS_PER_SESSION = 30",      cfg.MAX_DAYS_PER_SESSION == 30)
check("REFRESH_FAILED = False",         cfg.REFRESH_FAILED == False)
check("SYNC_DATES = None",              cfg.SYNC_DATES is None)
check("BACKUP_DIR derived",             cfg.BACKUP_DIR == _TMPDIR / "garmin_data" / "backup")
check("LOG_BACKUP_DIR derived",         cfg.LOG_BACKUP_DIR == _TMPDIR / "garmin_data" / "backup" / "log")
check("RAW_BACKUP_DIR derived",         cfg.RAW_BACKUP_DIR == _TMPDIR / "garmin_data" / "backup" / "raw")
check("AUTORESTORE_DIR derived",        cfg.AUTORESTORE_DIR == _TMPDIR / "garmin_data" / "backup" / "autorestore")

# SYNC_DATES parsing
os.environ["GARMIN_SYNC_DATES"] = "2024-01-01,2024-01-02,bad-date"
importlib.reload(cfg)
check("SYNC_DATES: 2 valid parsed",     cfg.SYNC_DATES is not None and len(cfg.SYNC_DATES) == 2)
check("SYNC_DATES: invalid skipped",    date(2024, 1, 1) in cfg.SYNC_DATES)
os.environ["GARMIN_SYNC_DATES"] = ""
importlib.reload(cfg)

# ENV reload — BASE_DIR folgt GARMIN_OUTPUT_DIR nach reload
_TMPDIR2 = Path(tempfile.mkdtemp(prefix="garmin_test2_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR2)
importlib.reload(cfg)
check("config reload: BASE_DIR follows ENV",        cfg.BASE_DIR == _TMPDIR2)
check("config reload: GARMIN_TOKEN_FILE under BASE", str(cfg.GARMIN_TOKEN_FILE).startswith(str(_TMPDIR2)))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)
importlib.reload(cfg)
shutil.rmtree(_TMPDIR2, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  2. garmin_sync
# ══════════════════════════════════════════════════════════════════════════════
section("2. garmin_sync")
import garmin_sync as sync

today     = date.today()
yesterday = today - timedelta(days=1)

# recent mode
os.environ["GARMIN_SYNC_MODE"] = "recent"
os.environ["GARMIN_DAYS_BACK"] = "30"
importlib.reload(cfg); importlib.reload(sync)
start, end = sync.resolve_date_range(None)
check("recent: end = yesterday",        end == yesterday)
check("recent: 30 days back",           start == today - timedelta(days=30))

# range mode
os.environ["GARMIN_SYNC_MODE"]  = "range"
os.environ["GARMIN_SYNC_START"] = "2024-01-01"
os.environ["GARMIN_SYNC_END"]   = "2024-01-31"
importlib.reload(cfg); importlib.reload(sync)
start, end = sync.resolve_date_range(None)
check("range: start correct",           start == date(2024, 1, 1))
check("range: end correct",             end   == date(2024, 1, 31))

# auto mode
os.environ["GARMIN_SYNC_MODE"] = "auto"
importlib.reload(cfg); importlib.reload(sync)
start, end = sync.resolve_date_range("2023-06-01")
check("auto: uses first_day",           start == date(2023, 6, 1))
check("auto: end = yesterday",          end   == yesterday)

# date_range generator
days = list(sync.date_range(date(2024, 1, 1), date(2024, 1, 5)))
check("date_range: 5 days",             len(days) == 5)
check("date_range: start correct",      days[0]   == date(2024, 1, 1))
check("date_range: end correct",        days[-1]  == date(2024, 1, 5))

# get_local_dates
cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
(cfg.RAW_DIR / "garmin_raw_2024-03-01.json").write_text("{}")
(cfg.RAW_DIR / "garmin_raw_2024-03-02.json").write_text("{}")
importlib.reload(cfg); importlib.reload(sync)
local = sync.get_local_dates(cfg.RAW_DIR)
check("get_local_dates: 2 files found", len(local) >= 2)
check("get_local_dates: date correct",  date(2024, 3, 1) in local)

# recheck exclusion
os.environ["GARMIN_REFRESH_FAILED"] = "1"
importlib.reload(cfg); importlib.reload(sync)
local2 = sync.get_local_dates(cfg.RAW_DIR, {date(2024, 3, 1)})
check("get_local_dates: recheck excluded", date(2024, 3, 1) not in local2)

# reset
os.environ["GARMIN_SYNC_MODE"]      = "recent"
os.environ["GARMIN_DAYS_BACK"]      = "7"
os.environ["GARMIN_REFRESH_FAILED"] = "0"
importlib.reload(cfg); importlib.reload(sync)

# ══════════════════════════════════════════════════════════════════════════════
#  8. garmin_utils
# ══════════════════════════════════════════════════════════════════════════════
section("8. garmin_utils")
import garmin_utils as utils

# parse_device_date
check("parse_device_date: ISO string",      utils.parse_device_date("2024-03-15T10:00:00") == "2024-03-15")
check("parse_device_date: ISO date only",   utils.parse_device_date("2024-03-15") == "2024-03-15")
check("parse_device_date: ms timestamp",    utils.parse_device_date(1710489600000) == "2024-03-15")
check("parse_device_date: s timestamp",     utils.parse_device_date(1710489600) == "2024-03-15")
check("parse_device_date: None → None",     utils.parse_device_date(None) is None)
check("parse_device_date: empty → None",    utils.parse_device_date("") is None)

# parse_sync_dates
r1 = utils.parse_sync_dates("2024-01-01,2024-03-15")
check("parse_sync_dates: 2 valid",          r1 is not None and len(r1) == 2)
check("parse_sync_dates: sorted",           r1[0].isoformat() == "2024-01-01")
r2 = utils.parse_sync_dates("2024-01-01,invalid,2024-03-15")
check("parse_sync_dates: invalid skipped",  r2 is not None and len(r2) == 2)
check("parse_sync_dates: empty → None",     utils.parse_sync_dates("") is None)
check("parse_sync_dates: all invalid → None", utils.parse_sync_dates("bad,worse") is None)

# extract_date_from_filename
_p = lambda name: Path(f"/tmp/{name}")
check("extract_date: valid raw",             utils.extract_date_from_filename(_p("garmin_raw_2024-03-15.json")) == date(2024, 3, 15))
check("extract_date: valid summary",         utils.extract_date_from_filename(_p("garmin_2024-03-15.json"), prefix="garmin_") == date(2024, 3, 15))
check("extract_date: invalid format → None", utils.extract_date_from_filename(_p("garmin_raw_not-a-date.json")) is None)
check("extract_date: wrong prefix → None",   utils.extract_date_from_filename(_p("garmin_raw_2024-03-15.json"), prefix="garmin_") is None)
check("extract_date: str path works",        utils.extract_date_from_filename("/tmp/garmin_raw_2024-06-01.json") == date(2024, 6, 1))

# ══════════════════════════════════════════════════════════════════════════════
#  8b. garmin_sync.get_local_dates / garmin_utils date helpers (v1.7.4.0.3)
#  Closes the survivors of the mutation test: the three storage locations,
#  junk file names, the recheck log line, and the edges of parse_device_date.
# ══════════════════════════════════════════════════════════════════════════════
section("8b. get_local_dates and date helpers in depth")


class _SyncLogRec:
    """Stands in for sync.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg))

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg))


def _gld(folder, recheck=None):
    """sync.get_local_dates(folder, recheck) with the logger recorded -> (dates, calls)."""
    real, rec = sync.log, _SyncLogRec()
    sync.log = rec
    try:
        return sync.get_local_dates(folder, recheck), rec.calls
    finally:
        sync.log = real


def _fresh(name):
    base = _TMPDIR / name
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    return base


# raw/ is missing: summary/ and the legacy location are still looked at
_b = _fresh("gld_noraw")
(_b / "summary").mkdir()
(_b / "summary" / "garmin_2024-05-01.json").write_text("{}")
(_b / "garmin_2024-05-02.json").write_text("{}")
_d, _c = _gld(_b / "raw")
check("8b get_local_dates: raw/ missing -> summary and legacy files still found",
      _d == {date(2024, 5, 1), date(2024, 5, 2)})

# summary/ is missing: the legacy location is still looked at
_b = _fresh("gld_nosummary")
(_b / "raw").mkdir()
(_b / "raw" / "garmin_raw_2024-05-03.json").write_text("{}")
(_b / "garmin_2024-05-04.json").write_text("{}")
_d, _c = _gld(_b / "raw")
check("8b get_local_dates: summary/ missing -> raw and legacy files found",
      _d == {date(2024, 5, 3), date(2024, 5, 4)})

# nothing at all: empty set, no 'found' log line
_b = _fresh("gld_empty")
_d, _c = _gld(_b / "raw")
check("8b get_local_dates: nothing found -> empty set, nothing logged",
      _d == set() and _c == [])

# all three places, one date in two of them counted once
_b = _fresh("gld_all")
(_b / "raw").mkdir()
(_b / "summary").mkdir()
(_b / "raw" / "garmin_raw_2024-06-01.json").write_text("{}")
(_b / "raw" / "garmin_raw_2024-06-02.json").write_text("{}")
(_b / "summary" / "garmin_2024-06-02.json").write_text("{}")
(_b / "summary" / "garmin_2024-06-03.json").write_text("{}")
(_b / "garmin_2024-06-09.json").write_text("{}")
_d, _c = _gld(_b / "raw")
check("8b get_local_dates: union of all three places, duplicates once",
      _d == {date(2024, 6, d) for d in (1, 2, 3, 9)})
check("8b get_local_dates: log line with count, earliest and latest",
      len(_c) == 1 and _c[0][0] == "info"
      and "Local days found: 4 (earliest: 2024-06-01, latest: 2024-06-09)" in _c[0][1])

# junk file names are ignored, valid ones kept
_b = _fresh("gld_junk")
(_b / "raw").mkdir()
for _n in ("garmin_raw_junk.json", "garmin_raw_2024-13-45.json", "garmin_raw_.json",
           "garmin_raw_2024-07-01.json", "other_2024-07-02.json"):
    (_b / "raw" / _n).write_text("{}")
_d, _c = _gld(_b / "raw")
check("8b get_local_dates: junk names ignored, only the valid date kept",
      _d == {date(2024, 7, 1)})

# recheck: dates are removed and the count is logged
_b = _fresh("gld_recheck")
(_b / "raw").mkdir()
for _day in (1, 2, 3):
    (_b / "raw" / f"garmin_raw_2024-08-0{_day}.json").write_text("{}")
_d, _c = _gld(_b / "raw", {date(2024, 8, 1), date(2024, 8, 2), date(2024, 8, 20)})
check("8b recheck: the two existing dates are excluded, the unknown one changes nothing",
      _d == {date(2024, 8, 3)})
check("8b recheck: log names exactly 2 excluded days",
      any("Refresh mode: excluding 2 recheck days for re-fetch" in m for _, m in _c))
_d, _c = _gld(_b / "raw", {date(2024, 8, 20)})
check("8b recheck: a date that is not there -> nothing removed, no refresh log",
      len(_d) == 3 and not any("Refresh mode" in m for _, m in _c))
_d, _c = _gld(_b / "raw", set())
check("8b recheck: empty set -> nothing removed, no refresh log",
      len(_d) == 3 and not any("Refresh mode" in m for _, m in _c))
_d, _c = _gld(_b / "raw", {date(2024, 8, 1), date(2024, 8, 2), date(2024, 8, 3)})
check("8b recheck: everything excluded -> empty set, no 'found' line",
      _d == set() and not any("Local days found" in m for _, m in _c)
      and any("excluding 3 recheck days" in m for _, m in _c))

_b = _fresh("gld_recheck5")
(_b / "raw").mkdir()
for _day in range(1, 6):
    (_b / "raw" / f"garmin_raw_2024-09-0{_day}.json").write_text("{}")
_d, _c = _gld(_b / "raw", {date(2024, 9, 1), date(2024, 9, 2), date(2024, 9, 3)})
check("8b recheck: 5 days, 3 excluded -> 2 left, log says exactly 3",
      len(_d) == 2 and any("excluding 3 recheck days" in m for _, m in _c))

# parse_device_date: the length and character test of the ISO branch
check("8b parse_device_date: 9 characters with a dash is not an ISO date -> None",
      utils.parse_device_date("2024-03-1") is None)
check("8b parse_device_date: 10 characters with the dash in place -> cut to 10",
      utils.parse_device_date("2024-03-15") == "2024-03-15"
      and utils.parse_device_date("2024-03-15T23:59:59Z") == "2024-03-15")
check("8b parse_device_date: 10+ characters without a dash at index 4 is no ISO date",
      utils.parse_device_date("2024,03,15") is None
      and utils.parse_device_date("2024/03/15") is None)
check("8b parse_device_date: surrounding blanks are stripped",
      utils.parse_device_date("  2024-03-15 ") == "2024-03-15")
# seconds vs milliseconds: the switch is above 1e11
check("8b parse_device_date: 1e11+1 is milliseconds (1973-03-03)",
      utils.parse_device_date(100000000001) == "1973-03-03")
check("8b parse_device_date: 1e11 and 1e11-1 are seconds, not milliseconds",
      utils.parse_device_date(100000000000) != "1973-03-03"
      and utils.parse_device_date(99999999999) != "1973-03-03")
check("8b parse_device_date: ms and s timestamps of the same moment agree",
      utils.parse_device_date("1710489600000") == utils.parse_device_date("1710489600") == "2024-03-15")
# values that cannot be a date -> None, never an exception
for _bad in ("abc", "12.5", "1.5e12", "99999999999999999999", "-99999999999", True, 0):
    try:
        _got = utils.parse_device_date(_bad)
    except Exception as _exc:
        _got = f"RAISED {type(_exc).__name__}"
    check(f"8b parse_device_date: {_bad!r} -> None", _got is None)

# Ist-Stand: the number 0 is "no value" (None), the text "0" is the epoch
check("8b parse_device_date: text '0' is the epoch (Ist-Stand), number 0 is None",
      utils.parse_device_date("0") == "1970-01-01" and utils.parse_device_date(0) is None)

# extract_date_from_filename: the prefix is stripped once
check("8b extract_date: prefix repeated twice is not stripped twice -> None",
      utils.extract_date_from_filename(_p("garmin_raw_garmin_raw_2024-03-15.json")) is None)

# ══════════════════════════════════════════════════════════════════════════════
#  1b / 2b. garmin_config and garmin_sync.resolve_date_range — environment,
#           MCP server config file, mode dispatch (v1.7.4.0.3).
#           Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("1b / 2b. garmin_config (env + MCP file), garmin_sync.resolve_date_range")
import json as _json1b
from contextlib import contextmanager as _ctxm1b
from unittest.mock import patch as _patch1b


@_ctxm1b
def _cfg_env1b(env=None, mcp=None, drop_output_dir=False):
    """Reloads garmin_config with a controlled environment and a fake home
    directory (optionally holding the MCP server config file), restores the
    real state on exit."""
    home = Path(tempfile.mkdtemp(prefix="garmin_cfg1b_"))
    if mcp is not None:
        (home / ".garmin_mcp_server_config.json").write_text(
            mcp if isinstance(mcp, str) else _json1b.dumps(mcp), encoding="utf-8")
    try:
        with _patch1b.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home), **(env or {})}), \
                _patch1b.object(Path, "home", return_value=home):
            for _k in [k for k in os.environ if k.startswith("GARMIN_MCP_")]:
                if _k not in (env or {}):
                    del os.environ[_k]
            for _k in ("GARMIN_SYNC_FALLBACK", "GARMIN_REFRESH_FAILED") + (("GARMIN_OUTPUT_DIR",) if drop_output_dir else ()):
                if _k not in (env or {}):
                    os.environ.pop(_k, None)
            importlib.reload(cfg)
            yield home
    finally:
        importlib.reload(cfg)
        shutil.rmtree(home, ignore_errors=True)


# -- plain environment variables ---------------------------------------------------------------------------------
with _cfg_env1b():
    check("1b config: GARMIN_SYNC_FALLBACK unset -> None", cfg.SYNC_AUTO_FALLBACK is None)
    check("1b config: log rotation limits are 30 (sessions) and 30 (force-refetch)",
          cfg.LOG_RECENT_MAX == 30 and cfg.LOG_FORCE_REFETCH_MAX == 30)
with _cfg_env1b({"GARMIN_SYNC_FALLBACK": ""}):
    check("1b config: GARMIN_SYNC_FALLBACK empty -> None", cfg.SYNC_AUTO_FALLBACK is None)
with _cfg_env1b({"GARMIN_SYNC_FALLBACK": "2024-01-01"}):
    check("1b config: GARMIN_SYNC_FALLBACK set -> the value", cfg.SYNC_AUTO_FALLBACK == "2024-01-01")
_rf = {}
for _v in ("0", "1", "2", "", "true"):
    with _cfg_env1b({"GARMIN_REFRESH_FAILED": _v}):
        _rf[_v] = cfg.REFRESH_FAILED
check("1b config: REFRESH_FAILED is True only for exactly '1'",
      _rf == {"0": False, "1": True, "2": False, "": False, "true": False})
with _cfg_env1b():
    check("1b config: REFRESH_FAILED unset -> False", cfg.REFRESH_FAILED is False)

# -- _read_mcp_server_config ----------------------------------------------------------------------------------------
with _cfg_env1b() as _h:
    _f = _h / "other.json"
    with _patch1b.object(cfg, "MCP_SERVER_CONFIG_FILE", _f):
        check("1b mcp file: missing file -> {}", cfg._read_mcp_server_config() == {})
        _f.write_text("{broken", encoding="utf-8")
        check("1b mcp file: corrupt JSON -> {}", cfg._read_mcp_server_config() == {})
        _f.write_text("", encoding="utf-8")
        check("1b mcp file: empty file -> {}", cfg._read_mcp_server_config() == {})
        _f.write_text('{"mcp_http_port": 9000, "x": 1}', encoding="utf-8")
        check("1b mcp file: valid content is returned unchanged",
              cfg._read_mcp_server_config() == {"mcp_http_port": 9000, "x": 1})

# -- MCP_HTTP_PORT: ENV > file > default, corrupt file value falls back ---------------------------------
_ports = []
for _mcp, _env in ((None, None), ({"mcp_http_port": 9000}, None), ({"mcp_http_port": "9001"}, None),
                   ({"mcp_http_port": 0}, None), ({"mcp_http_port": None}, None), ({}, None),
                   ({"mcp_http_port": "abc"}, None), ({"mcp_http_port": [1]}, None),
                   ({"mcp_http_port": 9000}, {"GARMIN_MCP_HTTP_PORT": "9100"})):
    with _cfg_env1b(_env, _mcp):
        _ports.append(cfg.MCP_HTTP_PORT)
check("1b config: MCP_HTTP_PORT — file value, text number, default 8756 for missing/0/None, "
      "default for non-numeric (ValueError) and list (TypeError), ENV wins",
      _ports == [8756, 9000, 9001, 8756, 8756, 8756, 8756, 8756, 9100])

# -- MCP_HEADLESS / extra hosts ----------------------------------------------------------------------------------
_hl = []
for _mcp, _env in ((None, None), ({"mcp_headless": True}, None), ({"mcp_headless": False}, None),
                   ({"mcp_headless": True}, {"GARMIN_MCP_HEADLESS": "0"}),
                   (None, {"GARMIN_MCP_HEADLESS": " Yes "}), (None, {"GARMIN_MCP_HEADLESS": "true"}),
                   (None, {"GARMIN_MCP_HEADLESS": "1"}), (None, {"GARMIN_MCP_HEADLESS": "no"})):
    with _cfg_env1b(_env, _mcp):
        _hl.append(cfg.MCP_HEADLESS)
check("1b config: MCP_HEADLESS — default False, file value, ENV wins, ENV accepts 1/true/yes (trimmed, any case)",
      _hl == [False, True, False, False, True, True, True, False])
_xe = []
for _mcp, _env in ((None, None), ({"mcp_extra_hosts_enabled": True}, None),
                   ({"mcp_extra_hosts_enabled": True}, {"GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED": "0"}),
                   (None, {"GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED": "TRUE"})):
    with _cfg_env1b(_env, _mcp):
        _xe.append(cfg.MCP_EXTRA_ALLOWED_HOSTS_ENABLED)
check("1b config: MCP_EXTRA_ALLOWED_HOSTS_ENABLED — default False, file value, ENV wins",
      _xe == [False, True, False, True])
_xr = []
for _mcp, _env in ((None, None), ({"mcp_extra_hosts": "a.example,b.example:80"}, None),
                   ({"mcp_extra_hosts": ""}, None), ({"mcp_extra_hosts": "a.example"}, {"GARMIN_MCP_EXTRA_ALLOWED_HOSTS": "env.example"}),
                   (None, {"GARMIN_MCP_EXTRA_ALLOWED_HOSTS": ""})):
    with _cfg_env1b(_env, _mcp):
        _xr.append((cfg.MCP_EXTRA_ALLOWED_HOSTS_RAW, cfg.MCP_EXTRA_ALLOWED_HOSTS))
check("1b config: extra hosts — default host.docker.internal, file value, empty file value -> default, ENV wins "
      "(even when empty), parsed list follows the raw value",
      _xr == [("host.docker.internal", ["host.docker.internal:*"]),
              ("a.example,b.example:80", ["a.example:*", "b.example:80"]),
              ("host.docker.internal", ["host.docker.internal:*"]),
              ("env.example", ["env.example:*"]),
              ("", [])])

# -- _parse_extra_hosts ---------------------------------------------------------------------------------------------
check("1b _parse_extra_hosts: blanks and empty entries dropped, loop goes on after them, ':*' only without port",
      cfg._parse_extra_hosts(" , a ,, b:80 , c:* ,") == ["a:*", "b:80", "c:*"])
check("1b _parse_extra_hosts: empty / blank-only input -> []",
      cfg._parse_extra_hosts("") == [] and cfg._parse_extra_hosts("  ,  , ") == [])
check("1b _parse_extra_hosts: single host without port", cfg._parse_extra_hosts("h") == ["h:*"])

# -- MCP_BASE_DIR: ENV > file > default --------------------------------------------------------------------------
with _cfg_env1b({"GARMIN_OUTPUT_DIR": str(_TMPDIR)}, {"base_dir": "/from/file"}):
    check("1b config: MCP_BASE_DIR — GARMIN_OUTPUT_DIR wins over the file", cfg.MCP_BASE_DIR == _TMPDIR)
with _cfg_env1b(None, {"base_dir": "~/from_file"}, drop_output_dir=True) as _h:
    check("1b config: MCP_BASE_DIR — without ENV the file's base_dir is used (home expanded)",
          cfg.MCP_BASE_DIR == _h / "from_file")
with _cfg_env1b(None, {"base_dir": ""}, drop_output_dir=True) as _h:
    check("1b config: MCP_BASE_DIR — empty base_dir -> ~/local_archive", cfg.MCP_BASE_DIR == _h / "local_archive")
with _cfg_env1b(None, None, drop_output_dir=True) as _h:
    check("1b config: MCP_BASE_DIR — no ENV, no file -> ~/local_archive", cfg.MCP_BASE_DIR == _h / "local_archive")

# -- resolve_date_range: dispatch on the mode -------------------------------------------------------------------
import garmin_sync as _sync2b
_today2b = date.today()
_yest2b = _today2b - timedelta(days=1)


def _rdr2b(mode, first_day=None, **cfg_over):
    """resolve_date_range with a run-time built mode string (never interned,
    so a mutated `is` comparison cannot pass by accident)."""
    _mode = "".join(list(mode))
    with _patch1b.multiple(cfg, SYNC_MODE=_mode, **cfg_over):
        try:
            return _sync2b.resolve_date_range(first_day)
        except SystemExit as _e:
            return ("exit", _e.code)


check("2b resolve_date_range: recent -> (today - SYNC_DAYS, yesterday)",
      _rdr2b("recent", SYNC_DAYS=10) == (_today2b - timedelta(days=10), _yest2b))
check("2b resolve_date_range: range -> (SYNC_FROM, SYNC_TO)",
      _rdr2b("range", SYNC_FROM="2024-01-01", SYNC_TO="2024-01-31") == (date(2024, 1, 1), date(2024, 1, 31)))
try:
    _rdr2b("range", SYNC_FROM="nope", SYNC_TO="2024-01-31")
    _ce = None
except _sync2b.ConfigurationError as _e:
    _ce = str(_e)
check("2b resolve_date_range: range with a bad date raises ConfigurationError naming both values",
      _ce is not None and "'nope' / '2024-01-31'" in _ce)
check("2b resolve_date_range: auto with first_day -> (first_day, yesterday)",
      _rdr2b("auto", "2023-06-01", SYNC_AUTO_FALLBACK="2020-01-01") == (date(2023, 6, 1), _yest2b))
check("2b resolve_date_range: auto without first_day uses SYNC_AUTO_FALLBACK",
      _rdr2b("auto", None, SYNC_AUTO_FALLBACK="2020-01-01") == (date(2020, 1, 1), _yest2b))
check("2b resolve_date_range: auto without first_day and fallback -> 90 days",
      _rdr2b("auto", None, SYNC_AUTO_FALLBACK=None) == (_today2b - timedelta(days=90), _yest2b))
check("2b resolve_date_range: unknown modes (sorting before and after every known one) exit with code 1",
      all(_rdr2b(_m) == ("exit", 1) for _m in ("zzz", "aaa", "Recent", "", "ranges", "autos", "rang")))

summary()
