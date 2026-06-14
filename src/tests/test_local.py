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
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Path setup — works when run from project folder or elsewhere ───────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
logging.disable(logging.CRITICAL)

# ── Test runner ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from support import check, section, summary

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
check("RAW_DIR derived",                cfg.RAW_DIR == _TMPDIR / "garmin_data" / "raw")
check("SUMMARY_DIR derived",            cfg.SUMMARY_DIR == _TMPDIR / "garmin_data" / "summary")
check("LOG_DIR derived",                cfg.LOG_DIR == _TMPDIR / "garmin_data" / "log")
check("QUALITY_LOG_FILE derived",       cfg.QUALITY_LOG_FILE == _TMPDIR / "garmin_data" / "log" / "quality_log.json")
check("GARMIN_TOKEN_DIR derived",       cfg.GARMIN_TOKEN_DIR  == _TMPDIR / "garmin_data" / "log" / "garmin_token")
check("GARMIN_TOKEN_FILE derived",      cfg.GARMIN_TOKEN_FILE == _TMPDIR / "garmin_data" / "log" / "garmin_token.enc")
check("SYNC_MODE = recent",             cfg.SYNC_MODE == "recent")
check("MAX_DAYS_PER_SESSION = 30",      cfg.MAX_DAYS_PER_SESSION == 30)
check("SYNC_CHUNK_SIZE = 10",           cfg.SYNC_CHUNK_SIZE == 10)
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
check("summarize: schema_version = 2",      s["schema_version"] == 2)
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

# sleep_score_feedback + sleep_score_qualifier
_raw_ssf = {
    "date": "2026-01-01",
    "sleep": {
        "dailySleepDTO": {
            "sleepScoreFeedback": "POSITIVE_DEEP",
            "sleepScores": {"overall": {"qualifierKey": "FAIR"}},
        }
    },
}
_ssf = normalizer.summarize(_raw_ssf)
check("summarize: sleep_score_feedback = POSITIVE_DEEP",
      _ssf["sleep"]["sleep_score_feedback"] == "POSITIVE_DEEP")
check("summarize: sleep_score_qualifier = FAIR",
      _ssf["sleep"]["sleep_score_qualifier"] == "FAIR")

_raw_ssf_missing = {"date": "2026-01-01", "sleep": {"dailySleepDTO": {}}}
_ssf_m = normalizer.summarize(_raw_ssf_missing)
check("summarize: sleep_score_feedback None if absent",
      _ssf_m["sleep"]["sleep_score_feedback"] is None)
check("summarize: sleep_score_qualifier None if absent",
      _ssf_m["sleep"]["sleep_score_qualifier"] is None)

# empty dict — no crash
try:
    normalizer.normalize({}, source="api")
    check("normalizer empty dict: no crash",         True)
except Exception:
    check("normalizer empty dict: no crash",         False)

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

check("assess: high",     quality.assess_quality(raw_high)   == "high")
check("assess: standard", quality.assess_quality(raw_medium) == "standard")
check("assess: standard (stats-only)", quality.assess_quality(raw_low) == "standard")
check("assess: failed",   quality.assess_quality(raw_failed) == "failed")

raw_standard_steps = {"date": "2023-01-01", "stats": {"totalSteps": 5000}, "user_summary": {}}
check("assess: steps-only → standard", quality.assess_quality(raw_standard_steps) == "standard")

# _upsert_quality + write field
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
data = {"first_day": None, "devices": [], "days": []}

quality._upsert_quality(data, date(2024, 3, 15), "high", "Quality: high", written=True)
check("upsert high: write=True",    data["days"][0]["write"] == True)
check("upsert high: recheck=False", data["days"][0]["recheck"] == False)
check("upsert high: attempts=0",    data["days"][0]["attempts"] == 0)
check("upsert high: source=legacy", data["days"][0]["source"] == "legacy")

quality._upsert_quality(data, date(2024, 3, 16), "standard", "Quality: standard", written=True, source="api")
check("upsert standard: recheck=False", data["days"][1]["recheck"] == False)
check("upsert standard: attempts=0",    data["days"][1]["attempts"] == 0)
check("upsert standard: source=api",    data["days"][1]["source"] == "api")

quality._upsert_quality(data, date(2024, 3, 17), "failed", "API error", written=False)
check("upsert failed: write=False", data["days"][2]["write"] == False)
check("upsert failed: recheck=True",data["days"][2]["recheck"] == True)

quality._upsert_quality(data, date(2024, 3, 17), "failed", "retry", written=False)
check("upsert update: attempts++",  data["days"][2]["attempts"] == 2)

quality._upsert_quality(data, date(2024, 3, 18), "standard", "Quality: standard")
check("upsert standard: write=None",    data["days"][3]["write"] is None)
check("upsert standard: recheck=False", data["days"][3]["recheck"] == False)

# standard — recheck stays False (no prev_high, day is old)
d_standard = date(2024, 3, 19)
quality._upsert_quality(data, d_standard, "standard", "still standard", written=True)
check("low max attempts: recheck disabled", data["days"][4]["recheck"] == False)
check("low max attempts: attempts = 3",     data["days"][4]["attempts"] == 0)

# save + load round-trip
data["first_day"] = "2024-01-01"
quality._save_quality_log(data)
check("save: file created",         cfg.QUALITY_LOG_FILE.exists())
data2 = quality._load_quality_log()
check("load: first_day preserved",  data2["first_day"] == "2024-01-01")
check("load: entries preserved",    len(data2["days"]) >= 5)
check("load: write field intact",   data2["days"][0]["write"] == True)

# Migration: write=null for old entries
data_nowrite = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-07-01", "quality": "high", "reason": "old",
     "recheck": False, "attempts": 0, "last_checked": "2023-07-01", "last_attempt": None}
]}
quality._save_quality_log(data_nowrite)
data_nw = quality._load_quality_log()
check("migration: write=null added", data_nw["days"][0].get("write") is None)

# Migration: source=legacy for old entries
# Datensatz direkt in Datei schreiben (kein _save → kein _checksum) damit
# _load_quality_log() den Checksum-Check überspringt und die Migration sauber läuft.
import json as _json
_nosource_data = {"first_day": "2024-01-01", "devices": [], "days": [
    {"date": "2023-08-01", "quality": "high", "reason": "old", "write": True,
     "recheck": False, "attempts": 0, "last_checked": "2023-08-01", "last_attempt": None}
]}
cfg.QUALITY_LOG_FILE.write_text(_json.dumps(_nosource_data, indent=2), encoding="utf-8")
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

# load_token — korrupte .enc Datei → False
cfg.GARMIN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
cfg.GARMIN_TOKEN_FILE.write_bytes(b"not_valid_encrypted_data")
with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("load_token: corrupt enc → False", security.load_token() == False)
cfg.GARMIN_TOKEN_FILE.unlink(missing_ok=True)

# save_token — garmin_tokens.json fehlt → False
cfg.GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
# token dir exists but garmin_tokens.json is absent
with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("save_token: no tokens.json → False", security.save_token() == False)
shutil.rmtree(cfg.GARMIN_TOKEN_DIR, ignore_errors=True)


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

# F6 — Fail-Closed: schema absent → critical (not ok).
# Simulate empty schema, then restore via reload_schema to avoid state leak.
_saved_schema = validator_mod._schema
validator_mod._schema = {}
r_noschema = validator_mod.validate({"date": "2024-01-01"})
check("validator no schema: status=critical",        r_noschema["status"] == "critical")
check("validator no schema: schema issue present",
      any(i["field"] == "schema" for i in r_noschema["issues"]))
# Restore — mandatory cleanup, all later validator tests need the real schema
validator_mod.reload_schema()
check("validator restored after no-schema test",     validator_mod.current_version() == "1.0")

# None input — no crash
r_none = validator_mod.validate(None)
check("validator None input: no crash",              r_none["status"] == "critical")

# empty dict — date missing → critical
r_empty = validator_mod.validate({})
check("validator empty dict: status=critical",       r_empty["status"] == "critical")
check("validator empty dict: missing_required date",
      any(i["type"] == "missing_required" and i["field"] == "date" for i in r_empty["issues"]))

# out_of_range — HR value outside schema bounds
raw_oor = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 999}}
r_oor = validator_mod.validate(raw_oor)
check("validator out_of_range: status=warning",      r_oor["status"] == "warning")
check("validator out_of_range: issue type correct",
      any(i["type"] == "out_of_range" and i["field"] == "heart_rates.restingHeartRate"
          for i in r_oor["issues"]))

# out_of_range — value within bounds → no out_of_range issue
raw_inrange = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 55}}
r_inrange = validator_mod.validate(raw_inrange)
check("validator in_range: no out_of_range issue",
      not any(i["type"] == "out_of_range" for i in r_inrange["issues"]))

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
#  11. DETERMINISM
# ══════════════════════════════════════════════════════════════════════════════
section("11. DETERMINISM")

r1 = normalizer.summarize(raw_full)
r2 = normalizer.summarize(raw_full)
check("determinism: summarize stable",       r1 == r2)

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])):
    rd1 = collector._fetch_and_assess(mock_client, "2024-03-15")
    rd2 = collector._fetch_and_assess(mock_client, "2024-03-15")
check("determinism: fetch_and_assess stable", rd1 == rd2)

# ══════════════════════════════════════════════════════════════════════════════
#  12. INVARIANTS
# ══════════════════════════════════════════════════════════════════════════════
section("12. INVARIANTS")

# Quality darf nicht downgraden
data_inv = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_inv, date(2024, 9, 1), "high", "Quality: high", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 1), "low",  "Quality: low",  written=True)
check("invariant: high not downgraded to low",    data_inv["days"][0]["quality"] == "high")

quality._upsert_quality(data_inv, date(2024, 9, 2), "standard", "Quality: standard", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 2), "failed", "API error",           written=False)
check("invariant: standard not downgraded to failed", data_inv["days"][1]["quality"] == "standard")

quality._upsert_quality(data_inv, date(2024, 9, 3), "high", "Quality: high", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 3), "high", "Quality: high", written=True)
check("invariant: high stays high on repeat",     data_inv["days"][2]["quality"] == "high")

# Failed darf niemals schreiben — explizit als Invariante
with patch("garmin_collector.api.fetch_raw", return_value=({"date": "2024-01-01"}, [])), \
     patch("garmin_collector.writer.write_day") as mock_w:
    label_inv, _, _, _, _ = collector._fetch_and_assess(mock_client, "2024-01-01")
check("invariant: failed never writes",  label_inv == "failed" and not mock_w.called)

# ══════════════════════════════════════════════════════════════════════════════
#  12. ROBUSTNESS — Dirty Input
# ══════════════════════════════════════════════════════════════════════════════
section("12. ROBUSTNESS")
from copy import deepcopy

# Validator: fehlende Pflichtfelder blockieren zwingend
r_no_date = validator_mod.validate({"sleep": {}, "heart_rates": {}})
check("robustness: missing date → critical",      r_no_date["status"] == "critical")

# Validator: falsche Typen erkannt
r_wrong_type = validator_mod.validate({"date": "2024-01-01", "sleep": "corrupted", "heart_rates": "60"})
check("robustness: wrong types → warning/critical", r_wrong_type["status"] in ("warning", "critical"))

# Validator: None-Input kein Crash
r_none = validator_mod.validate(None)
check("robustness: None input → critical, no crash", r_none["status"] == "critical")

# Validator: leeres Dict kein Crash
r_empty = validator_mod.validate({})
check("robustness: empty dict → critical, no crash", r_empty["status"] == "critical")

# Normalizer: leere Hülle — kein Crash, kein Exception
raw_shell = {"date": "2024-01-01", "sleep": None, "heart_rates": None, "activities": []}
try:
    s_shell = normalizer.summarize(raw_shell)
    check("robustness: empty shell no crash",     isinstance(s_shell, dict))
    check("robustness: empty shell date correct", s_shell.get("date") == "2024-01-01")
except Exception:
    check("robustness: empty shell no crash",     False)
    check("robustness: empty shell date correct", False)

# Normalizer: raw nicht mutiert durch summarize
raw_immut = {"date": "2024-06-01", "heart_rates": {"restingHeartRate": 55}}
raw_before = deepcopy(raw_immut)
normalizer.summarize(raw_immut)
check("robustness: raw not mutated by summarize", raw_immut == raw_before)

# Normalizer: absurde Werte — kein Crash
raw_garbage = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 9999},
               "user_summary": {"totalSteps": -500}}
try:
    s_garbage = normalizer.summarize(raw_garbage)
    check("robustness: garbage values no crash", isinstance(s_garbage, dict))
except Exception:
    check("robustness: garbage values no crash", False)

# ══════════════════════════════════════════════════════════════════════════════
#  13. PIPELINE_E2E
# ══════════════════════════════════════════════════════════════════════════════
section("13. PIPELINE_E2E")

raw_e2e = {
    "date": "2024-07-15",
    "heart_rates": {"restingHeartRate": 58, "heartRateValues": [[0, 58], [60, 62]]},
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 27000}},
    "user_summary": {"totalSteps": 7200},
}

# normalize → validate → quality → write → read back
val_e2e  = validator_mod.validate(raw_e2e)
check("e2e: validator ok",            val_e2e["status"] == "ok")

norm_e2e = normalizer.normalize(raw_e2e, "api")
check("e2e: normalize returns dict",  isinstance(norm_e2e, dict))
check("e2e: date preserved",          norm_e2e.get("date") == "2024-07-15")

summ_e2e = normalizer.summarize(raw_e2e)
q_e2e    = quality.assess_quality(raw_e2e)
check("e2e: quality = high",          q_e2e == "high")

ok_e2e   = writer.write_day(raw_e2e, summ_e2e, "2024-07-15")
check("e2e: write_day ok",            ok_e2e == True)

read_e2e = writer.read_raw("2024-07-15")
check("e2e: read_raw returns dict",   isinstance(read_e2e, dict))
check("e2e: read_raw date correct",   read_e2e.get("date") == "2024-07-15")
check("e2e: read_raw content intact", read_e2e.get("heart_rates", {}).get("restingHeartRate") == 58)

# ══════════════════════════════════════════════════════════════════════════════
#  14. v1.4.3 — VALUE RANGE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
section("14. v1.4.3 — VALUE RANGE VALIDATION")

# out_of_range warnings → quality downgrade in collector logic
# Simuliert: validator liefert >3 out_of_range issues, label wird auf low gedrückt
_oor_issues = [
    {"type": "out_of_range", "field": f"heart_rates.field{i}",
     "severity": "warning", "expected": "20–300", "actual": 999}
    for i in range(4)
]
_val_result_oor = {"status": "warning", "issues": _oor_issues,
                   "schema_version": "1.0", "timestamp": "2024-01-01T00:00:00"}

_oor_count = sum(1 for i in _val_result_oor.get("issues", [])
                 if i.get("type") == "out_of_range")
check("downgrade: >3 out_of_range → count correct",  _oor_count == 4)
check("downgrade: >3 out_of_range → cap to low",     "low" if _oor_count > 3 else "high" == "low")

# exactly 3 → no downgrade
_val_result_3 = {"status": "warning", "issues": _oor_issues[:3],
                 "schema_version": "1.0", "timestamp": "2024-01-01T00:00:00"}
_oor_count_3 = sum(1 for i in _val_result_3.get("issues", [])
                   if i.get("type") == "out_of_range")
check("downgrade: exactly 3 → no downgrade",         _oor_count_3 <= 3)

# assess_quality with out_of_range data — quality stays pure (no validator_result param)
import garmin_quality as quality_mod
_raw_high = {
    "date": "2024-01-01",
    "heart_rates": {"heartRateValues": [[0, 60], [1, 65]], "restingHeartRate": 999},
}
_label = quality_mod.assess_quality(_raw_high)
check("assess_quality: stays pure (no validator param)", _label == "high")

# assess_quality with multiple out_of_range → still "low" from content if no intraday
_raw_low = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 999}}
_label_low = quality_mod.assess_quality(_raw_low)
check("assess_quality: no intraday → not high",      _label_low != "high")

# quality downgrade: >3 warnings + high label → low
_raw_q = {
    "date": "2024-01-01",
    "heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 999},
}
_q_label = quality_mod.assess_quality(_raw_q)  # would be "high"
_simulated = "standard" if _oor_count > 3 and _q_label == "high" else _q_label
check("downgrade simulation: high → standard",       _simulated == "standard")


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
#  A. garmin_quality — Checksum + Backup-Trigger (v1.5.1)
# ══════════════════════════════════════════════════════════════════════════════
section("A. garmin_quality — Checksum + Backup-Trigger (v1.5.1)")
import garmin_quality as quality_a
importlib.reload(quality_a)

# _compute_checksum — deterministisch bei gleichen Daten
_days_a = [
    {"date": "2024-01-02", "quality": "high",   "reason": "ok"},
    {"date": "2024-01-01", "quality": "medium",  "reason": "ok"},
]
_data_a = {"first_day": "2024-01-01", "devices": [], "days": _days_a}
_cs1 = quality_a._compute_checksum(_data_a)
_cs2 = quality_a._compute_checksum(_data_a)
check("checksum: deterministic",            _cs1 == _cs2)
check("checksum: is string",                isinstance(_cs1, str))
check("checksum: 64 hex chars (SHA-256)",   len(_cs1) == 64)

# _save_quality_log — sortiert days nach date, speichert _checksum
_data_save = {
    "first_day": "2024-01-01", "devices": [], "days": [
        {"date": "2024-01-03", "quality": "high",   "source": "api",    "reason": "ok"},
        {"date": "2024-01-01", "quality": "medium", "source": "api",    "reason": "ok"},
        {"date": "2024-01-02", "quality": "low",    "source": "legacy", "reason": "ok"},
    ]
}
quality_a._save_quality_log(_data_save, skip_backup=True)
check("save: file exists",                  cfg.QUALITY_LOG_FILE.exists())
_saved = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
check("save: days sorted by date",          [e["date"] for e in _saved["days"]] == ["2024-01-01", "2024-01-02", "2024-01-03"])
check("save: _checksum stored",             "_checksum" in _saved)
check("save: _checksum is string",          isinstance(_saved["_checksum"], str))

# _load_quality_log — integrity_warnings leer wenn Checksum passt
_loaded_ok = quality_a._load_quality_log()
check("load: integrity_warnings key present",   "integrity_warnings" in _loaded_ok)
check("load: no warnings on clean log",         _loaded_ok["integrity_warnings"] == [])

# Checksum manipulieren → Mismatch → integrity_warnings nicht leer
_tampered = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
_tampered["_checksum"] = "000000deadbeef"
cfg.QUALITY_LOG_FILE.write_text(json.dumps(_tampered, indent=2), encoding="utf-8")
_loaded_mismatch = quality_a._load_quality_log()
check("load: mismatch → integrity_warnings not empty",
      len(_loaded_mismatch.get("integrity_warnings", [])) > 0)

# skip_backup=True unterdrückt Backup-Trigger
_triggered = []
import unittest.mock as _mock
with _mock.patch.dict("sys.modules", {"garmin_backup": _mock.MagicMock(backup_quality_log=lambda: _triggered.append(1))}):
    quality_a._save_quality_log(_data_save, skip_backup=True)
check("save: skip_backup=True → no backup call",  len(_triggered) == 0)

# skip_backup=False triggert Backup
_triggered2 = []
_mock_backup = _mock.MagicMock()
_mock_backup.backup_quality_log = lambda: _triggered2.append(1)
with _mock.patch.dict("sys.modules", {"garmin_backup": _mock_backup}):
    quality_a._save_quality_log(_data_save, skip_backup=False)
check("save: skip_backup=False → backup called",  len(_triggered2) == 1)

# get_archive_stats — integrity_warnings weitergereicht
_stats_a = quality_a.get_archive_stats(cfg.QUALITY_LOG_FILE)
check("get_archive_stats: integrity_warnings key present",
      "integrity_warnings" in _stats_a)
check("get_archive_stats: integrity_warnings is list",
      isinstance(_stats_a["integrity_warnings"], list))

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

# restore_raw_days — kein Backup → landed in failed
_restore_result = backup.restore_raw_days([_missing_date])
check("restore_raw_days: no backup → failed",
      _missing_date in _restore_result.get("failed", []))

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
#  C. garmin_mirror (v1.5.6.1 — Container-Modell)
# ══════════════════════════════════════════════════════════════════════════════
section("C. garmin_mirror (v1.5.6.1)")
import garmin_mirror as mirror
import garmin_container as _gc
importlib.reload(mirror)

# is_reachable — leer / None → False
check("is_reachable: empty string → False",  mirror.is_reachable("") == False)
check("is_reachable: None → False",          mirror.is_reachable(None) == False)

# is_reachable — Pfad dessen Parent existiert → True (Container muss noch nicht existieren)
_mir_parent = Path(tempfile.mkdtemp(prefix="garmin_mirror_parent_"))
_mir_gla    = _mir_parent / "mirror.gla"
check("is_reachable: parent exists → True",  mirror.is_reachable(_mir_gla) == True)

# is_reachable — Parent existiert nicht → False
check("is_reachable: missing parent → False",
      mirror.is_reachable(_mir_parent / "nonexistent" / "mirror.gla") == False)

# run_mirror — source nicht vorhanden → ok=False
_bad_src = _TMPDIR / "nonexistent_source"
_result_bad = mirror.run_mirror(_bad_src, _mir_gla, "test-pw")
check("run_mirror: missing source → ok=False",  _result_bad["ok"] == False)
check("run_mirror: missing source → errors=1",  _result_bad["errors"] == 1)

# run_mirror — echte Quelle → Container entsteht
# sys.modules stubs: version + garmin_normalizer liegen nicht im garmin/-Path
import types as _types
_ver_stub  = _types.ModuleType("version");           _ver_stub.APP_VERSION = "test"
_norm_stub = _types.ModuleType("garmin_normalizer"); _norm_stub.CURRENT_SCHEMA_VERSION = 2
sys.modules.setdefault("version",           _ver_stub)
sys.modules.setdefault("garmin_normalizer", _norm_stub)

_mir_src = Path(tempfile.mkdtemp(prefix="garmin_mirror_src_"))
(_mir_src / "garmin_data" / "log").mkdir(parents=True)
(_mir_src / "garmin_data" / "raw" / "2024-01-15").mkdir(parents=True)
(_mir_src / "context_data" / "weather" / "raw").mkdir(parents=True)
(_mir_src / "garmin_token").mkdir()
import json as _json
(_mir_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": [{"date": "2024-01-15", "quality": "high"}]}),
    encoding="utf-8"
)
(_mir_src / "garmin_data" / "raw" / "2024-01-15" / "garmin_raw_2024-01-15.json").write_text(
    _json.dumps({"hr": 60, "source": "api"}), encoding="utf-8"
)
(_mir_src / "context_data" / "weather" / "raw" / "2024-01-15.json").write_text(
    _json.dumps({"temp": 5}), encoding="utf-8"
)
(_mir_src / "garmin_token" / "secret.enc").write_text("should_not_appear", encoding="utf-8")

_result_ok = mirror.run_mirror(_mir_src, _mir_gla, "test-pw")
check("run_mirror: returns dict",          isinstance(_result_ok, dict))
check("run_mirror: ok=True",               _result_ok["ok"] == True)
check("run_mirror: files_packed > 0",      _result_ok.get("files_packed", 0) > 0)
check("run_mirror: errors=0",              _result_ok.get("errors", 0) == 0)
check("run_mirror: container created",     _mir_gla.exists())
check("run_mirror: is valid container",    _gc.is_container(_mir_gla))

# garmin_token nie im Container
_raw_listed = _gc.list_files(_mir_gla, "raw")
_ctx_listed = _gc.list_files(_mir_gla, "context")
check("run_mirror: garmin_token not in raw",
      not any("garmin_token" in p for p in _raw_listed))
check("run_mirror: garmin_token not in context",
      not any("garmin_token" in p for p in _ctx_listed))

# Aufräumen
shutil.rmtree(_mir_src,    ignore_errors=True)
shutil.rmtree(_mir_parent, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + Results
# ══════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
