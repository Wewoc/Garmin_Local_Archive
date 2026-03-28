#!/usr/bin/env python3
"""
test_local.py — Garmin Local Archive v1.2.0 Local Test Script

Run from the project folder:
    python test_local.py

No external dependencies beyond what the project already requires.
No network, no GUI, no Garmin API calls.
Cleans up after itself — leaves no files behind.
"""

import json
import os
import sys
import shutil
import tempfile
import logging
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Path setup — works when run from project folder or elsewhere ───────────────
sys.path.insert(0, str(Path(__file__).parent))
logging.disable(logging.CRITICAL)

# ── Results tracking ───────────────────────────────────────────────────────────
_pass = 0
_fail = 0
_failures = []

def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✓  {name}")
    else:
        _fail += 1
        _failures.append(name)
        print(f"  ✗  {name}")

def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

# ── Temp directory as BASE_DIR ─────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_test_"))
os.environ["GARMIN_OUTPUT_DIR"]          = str(_TMPDIR)
os.environ["GARMIN_SYNC_MODE"]           = "recent"
os.environ["GARMIN_DAYS_BACK"]           = "7"
os.environ["GARMIN_SYNC_DATES"]          = ""
os.environ["GARMIN_REFRESH_FAILED"]      = "0"
os.environ["GARMIN_MAX_DAYS_PER_SESSION"] = "30"

import importlib

# ══════════════════════════════════════════════════════════════════════════════
#  1. garmin_config
# ══════════════════════════════════════════════════════════════════════════════
section("1. garmin_config")
import garmin_config as cfg
importlib.reload(cfg)

check("BASE_DIR from ENV",              cfg.BASE_DIR == _TMPDIR)
check("RAW_DIR derived",                cfg.RAW_DIR == _TMPDIR / "raw")
check("SUMMARY_DIR derived",            cfg.SUMMARY_DIR == _TMPDIR / "summary")
check("LOG_DIR derived",                cfg.LOG_DIR == _TMPDIR / "log")
check("QUALITY_LOG_FILE derived",       cfg.QUALITY_LOG_FILE == _TMPDIR / "log" / "quality_log.json")
check("GARMIN_TOKEN_FILE derived",      cfg.GARMIN_TOKEN_FILE == _TMPDIR / "log" / "garmin_token.enc")
check("SYNC_MODE = recent",             cfg.SYNC_MODE == "recent")
check("MAX_DAYS_PER_SESSION = 30",      cfg.MAX_DAYS_PER_SESSION == 30)
check("LOW_QUALITY_MAX_ATTEMPTS = 3",   cfg.LOW_QUALITY_MAX_ATTEMPTS == 3)
check("REFRESH_FAILED = False",         cfg.REFRESH_FAILED == False)
check("SYNC_DATES = None",              cfg.SYNC_DATES is None)

# SYNC_DATES parsing
os.environ["GARMIN_SYNC_DATES"] = "2024-01-01,2024-01-02,bad-date"
importlib.reload(cfg)
check("SYNC_DATES: 2 valid parsed",     cfg.SYNC_DATES is not None and len(cfg.SYNC_DATES) == 2)
check("SYNC_DATES: invalid skipped",    date(2024, 1, 1) in cfg.SYNC_DATES)
os.environ["GARMIN_SYNC_DATES"] = ""
importlib.reload(cfg)

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
#  3. garmin_normalizer
# ══════════════════════════════════════════════════════════════════════════════
section("3. garmin_normalizer")
import garmin_normalizer as normalizer

# normalize
check("normalize api: dict returned",       isinstance(normalizer.normalize({"date": "2024-01-01"}, "api"), dict))
check("normalize api: date preserved",      normalizer.normalize({"date": "2024-01-01"}, "api")["date"] == "2024-01-01")
check("normalize api: non-dict → unknown",  normalizer.normalize(None, "api").get("date") == "unknown")
check("normalize bulk: passthrough",        normalizer.normalize({"date": "2024-01-01"}, "bulk")["date"] == "2024-01-01")

# safe_get
check("safe_get: nested hit",      normalizer.safe_get({"a": {"b": 42}}, "a", "b") == 42)
check("safe_get: missing → None",  normalizer.safe_get({"a": {}}, "a", "b") is None)
check("safe_get: default",         normalizer.safe_get({}, "x", default=99) == 99)

# _parse_list_values
check("_parse_list_values: dict list",   normalizer._parse_list_values([{"v": 10}, {"v": 20}], "v") == [10, 20])
check("_parse_list_values: ts,val pairs", normalizer._parse_list_values([[0, 55], [60, 60]], 1) == [55, 60])

# summarize — structure
s = normalizer.summarize({"date": "2024-03-15"})
check("summarize: returns dict",            isinstance(s, dict))
check("summarize: date correct",            s["date"] == "2024-03-15")
check("summarize: generated_by normalizer", s["generated_by"] == "garmin_normalizer.py")
check("summarize: has sleep",               "sleep" in s)
check("summarize: has heartrate",           "heartrate" in s)
check("summarize: has stress",              "stress" in s)
check("summarize: has day",                 "day" in s)
check("summarize: has training",            "training" in s)
check("summarize: has activities list",     isinstance(s.get("activities"), list))

# summarize — with data
raw_full = {
    "date": "2024-03-15",
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 28800, "deepSleepSeconds": 5400}},
    "heart_rates": {"restingHeartRate": 52, "heartRateValues": [[0, 52], [60, 55]]},
    "user_summary": {"totalSteps": 8500, "dailyStepGoal": 10000},
    "activities": [{"activityName": "Run", "activityType": {"typeKey": "running"},
                    "duration": 3600, "distance": 8000}],
}
sf = normalizer.summarize(raw_full)
check("summarize full: sleep 8.0h",         sf["sleep"]["duration_h"] == 8.0)
check("summarize full: resting_bpm = 52",   sf["heartrate"]["resting_bpm"] == 52)
check("summarize full: steps = 8500",       sf["day"]["steps"] == 8500)
check("summarize full: 1 activity",         len(sf["activities"]) == 1)
check("summarize full: activity type",      sf["activities"][0]["type"] == "running")

# ══════════════════════════════════════════════════════════════════════════════
#  4. garmin_quality
# ══════════════════════════════════════════════════════════════════════════════
section("4. garmin_quality")
import garmin_quality as quality

# assess_quality
raw_high   = {"date": "2024-01-01", "heart_rates": {"heartRateValues": [[0, 60]]}}
raw_medium = {"date": "2022-01-01", "stats": {"totalSteps": 7000},
              "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 25200}}, "user_summary": {}}
raw_low    = {"date": "2020-01-01", "stats": {"x": 1}, "user_summary": {}}
raw_failed = {"date": "2019-01-01"}

check("assess: high",   quality.assess_quality(raw_high)   == "high")
check("assess: medium", quality.assess_quality(raw_medium) == "medium")
check("assess: low",    quality.assess_quality(raw_low)    == "low")
check("assess: failed", quality.assess_quality(raw_failed) == "failed")

# _upsert_quality + write field
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
data = {"first_day": None, "devices": [], "days": []}

quality._upsert_quality(data, date(2024, 3, 15), "high", "Quality: high", written=True)
check("upsert high: write=True",    data["days"][0]["write"] == True)
check("upsert high: recheck=False", data["days"][0]["recheck"] == False)
check("upsert high: attempts=0",    data["days"][0]["attempts"] == 0)

quality._upsert_quality(data, date(2024, 3, 16), "low", "Quality: low", written=True)
check("upsert low: recheck=True",   data["days"][1]["recheck"] == True)
check("upsert low: attempts=1",     data["days"][1]["attempts"] == 1)

quality._upsert_quality(data, date(2024, 3, 17), "failed", "API error", written=False)
check("upsert failed: write=False", data["days"][2]["write"] == False)
check("upsert failed: recheck=True",data["days"][2]["recheck"] == True)

quality._upsert_quality(data, date(2024, 3, 17), "failed", "retry", written=False)
check("upsert update: attempts++",  data["days"][2]["attempts"] == 2)

quality._upsert_quality(data, date(2024, 3, 18), "medium", "Quality: medium")
check("upsert medium: write=None",  data["days"][3]["write"] is None)
check("upsert medium: recheck=False", data["days"][3]["recheck"] == False)

# LOW_QUALITY_MAX_ATTEMPTS
d_low = date(2024, 3, 19)
for _ in range(cfg.LOW_QUALITY_MAX_ATTEMPTS):
    quality._upsert_quality(data, d_low, "low", "still low", written=True)
check("low max attempts: recheck disabled", data["days"][4]["recheck"] == False)
check("low max attempts: attempts = 3",     data["days"][4]["attempts"] == 3)

# save + load round-trip
data["first_day"] = "2024-01-01"
quality._save_quality_log(data)
check("save: file created",         cfg.QUALITY_LOG_FILE.exists())
data2 = quality._load_quality_log()
check("load: first_day preserved",  data2["first_day"] == "2024-01-01")
check("load: entries preserved",    len(data2["days"]) == 5)
check("load: write field intact",   data2["days"][0]["write"] == True)

# Migration: med → medium
data_old = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-06-01", "quality": "med", "reason": "old",
     "recheck": False, "attempts": 0, "last_checked": "2023-06-01", "last_attempt": None}
]}
quality._save_quality_log(data_old)
data_m = quality._load_quality_log()
check("migration: med → medium",    data_m["days"][0]["quality"] == "medium")

# Migration: write=null for old entries
data_nowrite = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-07-01", "quality": "high", "reason": "old",
     "recheck": False, "attempts": 0, "last_checked": "2023-07-01", "last_attempt": None}
]}
quality._save_quality_log(data_nowrite)
data_nw = quality._load_quality_log()
check("migration: write=null added", data_nw["days"][0].get("write") is None)

# restore
quality._save_quality_log(data)

# ══════════════════════════════════════════════════════════════════════════════
#  5. garmin_writer
# ══════════════════════════════════════════════════════════════════════════════
section("5. garmin_writer")
import garmin_writer as writer

norm_w   = {"date": "2024-04-01", "heart_rates": {"restingHeartRate": 55}}
summary_w = normalizer.summarize(norm_w)

ok = writer.write_day(norm_w, summary_w, "2024-04-01")
raw_p = cfg.RAW_DIR     / "garmin_raw_2024-04-01.json"
sum_p = cfg.SUMMARY_DIR / "garmin_2024-04-01.json"

check("write_day: returns True",           ok == True)
check("write_day: raw file created",       raw_p.exists())
check("write_day: summary file created",   sum_p.exists())
check("write_day: raw date correct",       json.loads(raw_p.read_text())["date"] == "2024-04-01")
check("write_day: generated_by normalizer",
      json.loads(sum_p.read_text()).get("generated_by") == "garmin_normalizer.py")

# ══════════════════════════════════════════════════════════════════════════════
#  6. garmin_collector internals
# ══════════════════════════════════════════════════════════════════════════════
section("6. garmin_collector internals")
import garmin_collector as collector

# _should_write
check("_should_write high=True",    collector._should_write("high")    == True)
check("_should_write medium=True",  collector._should_write("medium")  == True)
check("_should_write low=True",     collector._should_write("low")     == True)
check("_should_write failed=False", collector._should_write("failed")  == False)
check("_should_write unknown=False",collector._should_write("xyz")     == False)

# _is_stopped
check("_is_stopped: False by default", collector._is_stopped() == False)

import threading
ev = threading.Event(); ev.set()
collector._STOP_EVENT = ev
check("_is_stopped: True when set",    collector._is_stopped() == True)
del collector._STOP_EVENT

# summarize + safe_get no longer in collector
check("summarize not in collector", not hasattr(collector, "summarize"))
check("safe_get not in collector",  not hasattr(collector, "safe_get"))

# _process_day — mocked
mock_client = MagicMock()
with patch("garmin_collector.api.fetch_raw", return_value=raw_full), \
     patch("garmin_collector.writer.write_day", return_value=True):
    label, written = collector._process_day(mock_client, "2024-03-15")
    check("_process_day: label = high",   label   == "high")
    check("_process_day: written = True", written == True)

with patch("garmin_collector.api.fetch_raw", return_value={"date": "2024-03-20"}), \
     patch("garmin_collector.writer.write_day", return_value=False) as mock_w:
    label2, written2 = collector._process_day(mock_client, "2024-03-20")
    check("_process_day failed: label=failed",        label2   == "failed")
    check("_process_day failed: write_day not called", not mock_w.called)

# ══════════════════════════════════════════════════════════════════════════════
#  7. garmin_security (crypto layer only)
# ══════════════════════════════════════════════════════════════════════════════
section("7. garmin_security (crypto layer)")
import garmin_security as security

# _derive_aes_key
k1 = security._derive_aes_key("test_key")
k2 = security._derive_aes_key("test_key")
k3 = security._derive_aes_key("other_key")
check("_derive_aes_key: 32 bytes",       len(k1) == 32)
check("_derive_aes_key: deterministic",  k1 == k2)
check("_derive_aes_key: unique per key", k1 != k3)

# save_token + load_token round-trip
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
TEST_KEY = "local_test_enc_key"
with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    ok_save = security.save_token("test_token_payload")
    check("save_token: returns True",        ok_save == True)
    check("save_token: file created",        cfg.GARMIN_TOKEN_FILE.exists())

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    loaded = security.load_token()
    check("load_token: correct content",     loaded == "test_token_payload")

with patch("garmin_security.get_enc_key", return_value="wrong_key"):
    check("load_token: wrong key → None",    security.load_token() is None)

with patch("garmin_security.get_enc_key", return_value=None):
    check("load_token: no key → None",       security.load_token() is None)

# clear_token
mock_kr = MagicMock()
with patch.dict("sys.modules", {"keyring": mock_kr}):
    security.clear_token()
check("clear_token: file removed",          not cfg.GARMIN_TOKEN_FILE.exists())

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("load_token: no file → None",      security.load_token() is None)

# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + Results
# ══════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_TMPDIR, ignore_errors=True)

total = _pass + _fail
print(f"\n{'═' * 55}")
print(f"  Results: {_pass}/{total} passed  |  {_fail} failed")
print(f"{'═' * 55}")

if _failures:
    print("\n  Failed:")
    for name in _failures:
        print(f"    ✗  {name}")
    sys.exit(1)
else:
    print("\n  All tests passed.")
    sys.exit(0)
