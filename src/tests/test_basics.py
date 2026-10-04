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

summary()
