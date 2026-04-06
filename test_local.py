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
import threading
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
os.environ["GARMIN_SYNC_CHUNK_SIZE"]      = "10"

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
check("GARMIN_TOKEN_DIR derived",       cfg.GARMIN_TOKEN_DIR  == _TMPDIR / "log" / "garmin_token")
check("GARMIN_TOKEN_FILE derived",      cfg.GARMIN_TOKEN_FILE == _TMPDIR / "log" / "garmin_token.enc")
check("SYNC_MODE = recent",             cfg.SYNC_MODE == "recent")
check("MAX_DAYS_PER_SESSION = 30",      cfg.MAX_DAYS_PER_SESSION == 30)
check("SYNC_CHUNK_SIZE = 10",           cfg.SYNC_CHUNK_SIZE == 10)
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
check("summarize: schema_version = 1",      s["schema_version"] == 1)
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
check("upsert high: source=legacy", data["days"][0]["source"] == "legacy")

quality._upsert_quality(data, date(2024, 3, 16), "low", "Quality: low", written=True, source="api")
check("upsert low: recheck=True",   data["days"][1]["recheck"] == True)
check("upsert low: attempts=1",     data["days"][1]["attempts"] == 1)
check("upsert low: source=api",     data["days"][1]["source"] == "api")

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

# Migration: source=legacy for old entries
data_nosource = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-08-01", "quality": "high", "reason": "old", "write": True,
     "recheck": False, "attempts": 0, "last_checked": "2023-08-01", "last_attempt": None}
]}
quality._save_quality_log(data_nosource)
data_ns = quality._load_quality_log()
check("migration: source=legacy added", data_ns["days"][0].get("source") == "legacy")

# QUALITY_LOCK — exists and blocks concurrent access
check("QUALITY_LOCK: exists",         hasattr(quality, "QUALITY_LOCK"))
check("QUALITY_LOCK: is Lock",        isinstance(quality.QUALITY_LOCK, type(threading.Lock())))

_lock_held_during = []
def _lock_tester():
    acquired = quality.QUALITY_LOCK.acquire(blocking=False)
    _lock_held_during.append(acquired)
    if acquired:
        quality.QUALITY_LOCK.release()

with quality.QUALITY_LOCK:
    t = threading.Thread(target=_lock_tester)
    t.start(); t.join()
check("QUALITY_LOCK: blocks second thread", _lock_held_during == [False])

# assess_quality_fields
raw_fields_high = {
    "date": "2024-01-01",
    "heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 55},
    "stress":      {"stressValuesArray": [[0, 30]], "bodyBatteryValuesArray": [[0, 0, 80]]},
    "sleep":       {"sleepLevels": [{"level": "deep"}],
                    "dailySleepDTO": {"sleepTimeSeconds": 28800}},
    "activities":  [{"activityName": "Run"}],
}
f_high = quality.assess_quality_fields(raw_fields_high)
check("fields high: heart_rates=high",  f_high.get("heart_rates") == "high")
check("fields high: stress=high",       f_high.get("stress") == "high")
check("fields high: sleep=high",        f_high.get("sleep") == "high")
check("fields high: body_battery=high", f_high.get("body_battery") == "high")
check("fields high: activities=high",   f_high.get("activities") == "high")

raw_fields_medium = {
    "date": "2022-01-01",
    "heart_rates":        {"restingHeartRate": 55},
    "sleep":              {"dailySleepDTO": {"sleepTimeSeconds": 25200}},
    "training_readiness": {"score": 72},
    "training_status":    {"latestTrainingStatus": "productive"},
    "race_predictions":   {"marathon": 14400},
    "max_metrics":        {"vo2MaxPreciseValue": 52.3},
    "user_summary":       {"totalSteps": 8000},
}
f_med = quality.assess_quality_fields(raw_fields_medium)
check("fields medium: heart_rates=medium",        f_med.get("heart_rates") == "medium")
check("fields medium: sleep=medium",              f_med.get("sleep") == "medium")
check("fields medium: training_readiness=medium", f_med.get("training_readiness") == "medium")
check("fields medium: training_status=medium",    f_med.get("training_status") == "medium")
check("fields medium: stats=medium",              f_med.get("stats") == "medium")
check("fields medium: max_metrics=medium",        f_med.get("max_metrics") == "medium")

raw_fields_failed = {"date": "2019-01-01"}
f_fail = quality.assess_quality_fields(raw_fields_failed)
check("fields failed: heart_rates=failed",        f_fail.get("heart_rates") == "failed")
check("fields failed: stress=failed",             f_fail.get("stress") == "failed")
check("fields failed: activities=failed",         f_fail.get("activities") == "failed")

# _upsert_quality with fields parameter
data_f = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_f, date(2024, 5, 1), "high", "Quality: high",
                        written=True, source="api", fields=f_high)
check("upsert fields: stored on new entry",   data_f["days"][0].get("fields") == f_high)
quality._upsert_quality(data_f, date(2024, 5, 1), "high", "Quality: high",
                        written=True, source="api", fields=f_med)
check("upsert fields: updated on existing",   data_f["days"][0].get("fields") == f_med)
quality._upsert_quality(data_f, date(2024, 5, 2), "medium", "Quality: medium",
                        written=True, source="api")
check("upsert fields: None → no fields key",  "fields" not in data_f["days"][1])

# _upsert_quality with validator_result
val_ok  = {"status": "ok",      "schema_version": "1.0", "timestamp": "2026-04-06T12:00:00", "issues": []}
val_warn = {"status": "warning", "schema_version": "1.0", "timestamp": "2026-04-06T12:00:00",
            "issues": [{"field": "sleep", "type": "type_mismatch", "expected": "dict",
                        "actual": "str", "severity": "warning"}]}
data_v = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_v, date(2024, 6, 1), "high", "Quality: high",
                        written=True, source="api", validator_result=val_ok)
check("upsert validator: result stored",         data_v["days"][0].get("validator_result") == "ok")
check("upsert validator: issues stored",         data_v["days"][0].get("validator_issues") == [])
check("upsert validator: version stored",        data_v["days"][0].get("validator_schema_version") == "1.0")

quality._upsert_quality(data_v, date(2024, 6, 2), "high", "Quality: high",
                        written=True, source="api", validator_result=val_warn)
check("upsert validator warning: result stored", data_v["days"][1].get("validator_result") == "warning")
check("upsert validator warning: issues stored", len(data_v["days"][1].get("validator_issues", [])) == 1)

quality._upsert_quality(data_v, date(2024, 6, 3), "high", "Quality: high",
                        written=True, source="api")
check("upsert validator: None → no validator fields", "validator_result" not in data_v["days"][2])

# Migration: fields={} for old entries
data_nofields = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-09-01", "quality": "high", "reason": "old", "write": True,
     "source": "legacy", "recheck": False, "attempts": 0,
     "last_checked": "2023-09-01", "last_attempt": None}
]}
quality._save_quality_log(data_nofields)
data_nf = quality._load_quality_log()
check("migration: fields={} added", data_nf["days"][0].get("fields") == {})

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

ev = threading.Event(); ev.set()
collector._STOP_EVENT = ev
check("_is_stopped: True when set",    collector._is_stopped() == True)
del collector._STOP_EVENT

# summarize + safe_get no longer in collector
check("summarize not in collector", not hasattr(collector, "summarize"))
check("safe_get not in collector",  not hasattr(collector, "safe_get"))

# _process_day — mocked
mock_client = MagicMock()
with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])), \
     patch("garmin_collector.writer.write_day", return_value=True):
    label, written, fields, val_result = collector._process_day(mock_client, "2024-03-15")
    check("_process_day: label = high",        label      == "high")
    check("_process_day: written = True",      written    == True)
    check("_process_day: fields is dict",      isinstance(fields, dict))
    check("_process_day: val_result is dict",  isinstance(val_result, dict))
    check("_process_day: val_result has status", "status" in val_result)

with patch("garmin_collector.api.fetch_raw", return_value=({"date": "2024-03-20"}, [])), \
     patch("garmin_collector.writer.write_day", return_value=False) as mock_w:
    label2, written2, fields2, val_result2 = collector._process_day(mock_client, "2024-03-20")
    check("_process_day failed: label=failed",         label2   == "failed")
    check("_process_day failed: write_day not called", not mock_w.called)
    check("_process_day failed: fields is dict",       isinstance(fields2, dict))
    check("_process_day failed: val_result is dict",   isinstance(val_result2, dict))

# ══════════════════════════════════════════════════════════════════════════════
#  7. garmin_security (crypto layer only)
# ══════════════════════════════════════════════════════════════════════════════
section("7. garmin_security (crypto layer)")
import garmin_security as security

# _derive_aes_key
_test_salt = b"\x00" * 16
k1 = security._derive_aes_key("test_key",   _test_salt)
k2 = security._derive_aes_key("test_key",   _test_salt)
k3 = security._derive_aes_key("other_key",  _test_salt)
check("_derive_aes_key: 32 bytes",       len(k1) == 32)
check("_derive_aes_key: deterministic",  k1 == k2)
check("_derive_aes_key: unique per key", k1 != k3)

# save_token + load_token round-trip
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
TEST_KEY = "local_test_enc_key"
TEST_PAYLOAD = b'{"oauth1_token": "test", "oauth2_token": "test"}'

# Prepare: write garmin_tokens.json as the library would
cfg.GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
(cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").write_bytes(TEST_PAYLOAD)

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    ok_save = security.save_token()
    check("save_token: returns True",        ok_save == True)
    check("save_token: enc file created",    cfg.GARMIN_TOKEN_FILE.exists())
    check("save_token: token dir cleaned",   not cfg.GARMIN_TOKEN_DIR.exists())

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    ok_load = security.load_token()
    check("load_token: returns True",        ok_load == True)
    check("load_token: json written",        (cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").exists())
    check("load_token: correct content",     (cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").read_bytes() == TEST_PAYLOAD)
    security._clear_token_dir()

with patch("garmin_security.get_enc_key", return_value="wrong_key"):
    check("load_token: wrong key → False",   security.load_token() == False)

with patch("garmin_security.get_enc_key", return_value=None):
    check("load_token: no key → False",      security.load_token() == False)

# clear_token
mock_kr = MagicMock()
with patch.dict("sys.modules", {"keyring": mock_kr}):
    security.clear_token()
check("clear_token: enc file removed",      not cfg.GARMIN_TOKEN_FILE.exists())
check("clear_token: token dir removed",     not cfg.GARMIN_TOKEN_DIR.exists())

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("load_token: no file → False",     security.load_token() == False)


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

# ══════════════════════════════════════════════════════════════════════════════
#  9. garmin_validator
# ══════════════════════════════════════════════════════════════════════════════
section("9. garmin_validator")
import garmin_validator as validator_mod

# Schema loaded
check("validator: schema loaded",          validator_mod.current_version() == "1.0")

# Happy path — all known fields, correct types
raw_valid = {
    "date":               "2024-01-01",
    "sleep":              {"dailySleepDTO": {}},
    "heart_rates":        {"restingHeartRate": 55},
    "activities":         [],
}
r = validator_mod.validate(raw_valid)
check("validator ok: status=ok",           r["status"] == "ok")
check("validator ok: schema_version set",  r["schema_version"] == "1.0")
check("validator ok: timestamp set",       isinstance(r["timestamp"], str))
check("validator ok: no critical issues",  not any(i["severity"] == "critical" for i in r["issues"]))

# missing_optional — optional field absent → status stays ok
raw_no_sleep = {"date": "2024-01-01"}
r2 = validator_mod.validate(raw_no_sleep)
check("validator missing_optional: status=ok",     r2["status"] == "ok")
check("validator missing_optional: issue logged",
      any(i["type"] == "missing_optional" and i["field"] == "sleep" for i in r2["issues"]))

# unexpected_field — unknown field → warning
raw_new_field = {"date": "2024-01-01", "garmin_new_metric": {"value": 42}}
r3 = validator_mod.validate(raw_new_field)
check("validator unexpected_field: status=warning", r3["status"] == "warning")
check("validator unexpected_field: issue present",
      any(i["type"] == "unexpected_field" and i["field"] == "garmin_new_metric" for i in r3["issues"]))

# type_mismatch — optional field wrong type → warning
raw_bad_type = {"date": "2024-01-01", "sleep": "corrupted"}
r4 = validator_mod.validate(raw_bad_type)
check("validator type_mismatch: status=warning",    r4["status"] == "warning")
check("validator type_mismatch: issue present",
      any(i["type"] == "type_mismatch" and i["field"] == "sleep" for i in r4["issues"]))

# missing_required — date absent → critical
raw_no_date = {"sleep": {"dailySleepDTO": {}}}
r5 = validator_mod.validate(raw_no_date)
check("validator missing_required: status=critical", r5["status"] == "critical")
check("validator missing_required: issue present",
      any(i["type"] == "missing_required" and i["field"] == "date" for i in r5["issues"]))

# type_mismatch on required field — date wrong type → critical
raw_date_int = {"date": 20240101}
r6 = validator_mod.validate(raw_date_int)
check("validator date wrong type: status=critical",  r6["status"] == "critical")
check("validator date wrong type: severity=critical",
      any(i["severity"] == "critical" and i["field"] == "date" for i in r6["issues"]))

# non-dict input → critical
r7 = validator_mod.validate(None)
check("validator non-dict: status=critical",         r7["status"] == "critical")

r8 = validator_mod.validate("string input")
check("validator string input: status=critical",     r8["status"] == "critical")

# multiple issues — critical wins over warning
raw_multi = {"sleep": "bad_type", "garmin_new": 123}  # date missing + type_mismatch + unexpected
r9 = validator_mod.validate(raw_multi)
check("validator multi: critical wins",              r9["status"] == "critical")
check("validator multi: multiple issues",            len(r9["issues"]) > 1)

# evil API — date present as string but nonsense value → ok (content = quality's job)
raw_evil = {"date": "Gestern", "sleep": {}}
r10 = validator_mod.validate(raw_evil)
check("validator evil: nonsense date string → ok",   r10["status"] == "ok")

# reload_schema — no crash, version preserved
validator_mod.reload_schema()
check("validator reload: version intact",            validator_mod.current_version() == "1.0")

# ══════════════════════════════════════════════════════════════════════════════
#  10. garmin_writer — read_raw
# ══════════════════════════════════════════════════════════════════════════════
section("10. garmin_writer — read_raw")

# Happy path — file written by write_day, read back by read_raw
raw_rr = {"date": "2024-05-01", "heart_rates": {"restingHeartRate": 60}}
writer.write_day(raw_rr, normalizer.summarize(raw_rr), "2024-05-01")
result_rr = writer.read_raw("2024-05-01")
check("read_raw: returns dict",           isinstance(result_rr, dict))
check("read_raw: date correct",           result_rr.get("date") == "2024-05-01")
check("read_raw: content preserved",      result_rr.get("heart_rates", {}).get("restingHeartRate") == 60)

# File not found → empty dict
result_missing = writer.read_raw("1900-01-01")
check("read_raw: missing → empty dict",   result_missing == {})

# Corrupt JSON → empty dict
corrupt_path = cfg.RAW_DIR / "garmin_raw_2024-05-02.json"
corrupt_path.write_text("{ not valid json }")
result_corrupt = writer.read_raw("2024-05-02")
check("read_raw: corrupt → empty dict",   result_corrupt == {})

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
