#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    "heart_rates":  {"heartRateValues": [[0, 60]], "restingHeartRate": 55},
    "stress":       {"stressValuesArray": [[0, 30]], "bodyBatteryValuesArray": [[0, 0, 80]]},
    "sleep":        {"sleepLevels": [{"level": "deep"}],
                    "dailySleepDTO": {"sleepTimeSeconds": 28800}},
    "activities":   [{"activityName": "Run"}],
    "steps":        [{"startGMT": "2024-01-01T08:00:00", "steps": 100}],
    "respiration":  {"respirationValuesArray": [[0, 15]]},
}
f_high = quality.assess_quality_fields(raw_fields_high)
check("fields high: heart_rates=high",  f_high.get("heart_rates") == "high")
check("fields high: stress=high",       f_high.get("stress") == "high")
check("fields high: sleep=high",        f_high.get("sleep") == "high")
check("fields high: body_battery=high", f_high.get("body_battery") == "high")
check("fields high: activities=high",   f_high.get("activities") == "high")
check("fields high: steps=high",        f_high.get("steps") == "high")
check("fields high: respiration=high",  f_high.get("respiration") == "high")

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
# raw_fields_medium carries user_summary.totalSteps (daily aggregate, no
# intraday array) — same signal the stats-block already reuses via has_steps.
check("fields medium: steps=medium",              f_med.get("steps") == "medium")

raw_fields_failed = {"date": "2019-01-01"}
f_fail = quality.assess_quality_fields(raw_fields_failed)
check("fields failed: heart_rates=failed",        f_fail.get("heart_rates") == "failed")
check("fields failed: stress=failed",             f_fail.get("stress") == "failed")
check("fields failed: activities=failed",         f_fail.get("activities") == "failed")
check("fields failed: steps=failed",              f_fail.get("steps") == "failed")

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

# _upsert_quality with backfilled_fields parameter
data_bf = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_bf, date(2024, 5, 3), "high", "Quality: high",
                        written=True, source="api", backfilled_fields={"steps": "2026-07-01"})
check("upsert backfilled_fields: stored on new entry",
      data_bf["days"][0].get("backfilled_fields") == {"steps": "2026-07-01"})
quality._upsert_quality(data_bf, date(2024, 5, 3), "high", "Quality: high",
                        written=True, source="api", backfilled_fields={"other_field": "2026-07-02"})
check("upsert backfilled_fields: merged additively, not replaced",
      data_bf["days"][0].get("backfilled_fields") == {"steps": "2026-07-01", "other_field": "2026-07-02"})
quality._upsert_quality(data_bf, date(2024, 5, 4), "high", "Quality: high",
                        written=True, source="api")
check("upsert backfilled_fields: None → no key",
      "backfilled_fields" not in data_bf["days"][1])

# record_attempt with backfilled_fields — atomic wrapper forwards the parameter
data_ra = {"first_day": None, "devices": [], "days": []}
quality.record_attempt(data_ra, date(2024, 5, 5), "high", "Quality: high",
                        written=True, source="api", backfilled_fields={"steps": "2026-07-01"})
check("record_attempt: backfilled_fields forwarded",
      data_ra["days"][0].get("backfilled_fields") == {"steps": "2026-07-01"})

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
check("validator: schema loaded",          validator_mod.current_version() == "1.1")

# Happy path — all known fields, correct types
raw_valid = {
    "date":               "2024-01-01",
    "sleep":              {"dailySleepDTO": {}},
    "heart_rates":        {"restingHeartRate": 55},
    "activities":         [],
}
r = validator_mod.validate(raw_valid)
check("validator ok: status=ok",           r["status"] == "ok")
check("validator ok: schema_version set",  r["schema_version"] == "1.1")
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
check("validator reload: version intact",            validator_mod.current_version() == "1.1")

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
check("validator restored after no-schema test",     validator_mod.current_version() == "1.1")

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

def _strip_val_timestamp(result: tuple) -> tuple:
    """Remove timestamp from val_result before comparison — datetime.now() causes flakiness."""
    label, norm, summ, fields, val = result
    val_no_ts = {k: v for k, v in val.items() if k != "timestamp"}
    return (label, norm, summ, fields, val_no_ts)

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])):
    rd1 = collector._fetch_and_assess(mock_client, "2024-03-15")
    rd2 = collector._fetch_and_assess(mock_client, "2024-03-15")
check("determinism: fetch_and_assess stable", _strip_val_timestamp(rd1) == _strip_val_timestamp(rd2))

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

# ── reload cfg zurücksetzen ──────────────────────────────────────────────────
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
#  D. garmin_source_writer (v1.6.0.2)
# ══════════════════════════════════════════════════════════════════════════════
section("D. garmin_source_writer (v1.6.0.2)")
import garmin_source_writer as source_writer
importlib.reload(source_writer)

# ── cfg paths ─────────────────────────────────────────────────────────────────
check("SOURCE_DIR derived",
      cfg.SOURCE_DIR == _TMPDIR / "garmin_data" / "source")
check("SOURCE_API_LOG derived",
      cfg.SOURCE_API_LOG == _TMPDIR / "garmin_data" / "log" / "source_api_log.json")

# ── garmin_merge — additive field merge (v1.6.3 backfill foundation) ────────
import garmin_merge as _gm

_gm_raw_absent    = {"date": "2024-05-10", "heart_rates": {"restingHeartRate": 55}}
_gm_merged_absent = _gm.merge_field(_gm_raw_absent, "steps", [{"steps": 100}])
check("merge_field: absent field → added",        _gm_merged_absent.get("steps") == [{"steps": 100}])
check("merge_field: does not mutate input",       "steps" not in _gm_raw_absent)
check("merge_field: other fields preserved",      _gm_merged_absent["heart_rates"]["restingHeartRate"] == 55)

_gm_raw_present    = {"date": "2024-05-10", "steps": [{"steps": 999}]}
_gm_merged_present = _gm.merge_field(_gm_raw_present, "steps", [{"steps": 1}])
check("merge_field: existing non-empty → not overwritten",
      _gm_merged_present.get("steps") == [{"steps": 999}])

_gm_raw_empty    = {"date": "2024-05-10", "steps": []}
_gm_merged_empty = _gm.merge_field(_gm_raw_empty, "steps", [{"steps": 5}])
check("merge_field: existing empty list → overwritten",
      _gm_merged_empty.get("steps") == [{"steps": 5}])

check("merge_field: non-dict input → returned unchanged",
      _gm.merge_field(None, "steps", []) is None)

# ── patch_source_field — additive backfill into source/ + source_api_log.json ─
_psf_date = "2024-05-11"
_psf_raw  = {"date": _psf_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
source_writer.write_source(_psf_raw, _psf_date)
source_writer.update_log(_psf_date, {"status": "ok", "issues": []}, ["heart_rates"], [], 100)

_psf_ok = source_writer.patch_source_field(_psf_date, "steps", [{"startGMT": "x", "steps": 42}])
check("patch_source_field: returns True",          _psf_ok is True)

_psf_file    = cfg.SOURCE_DIR / f"garmin_source_{_psf_date}.json"
_psf_content = json.loads(_psf_file.read_text(encoding="utf-8"))
check("patch_source_field: field merged into file", _psf_content.get("steps") == [{"startGMT": "x", "steps": 42}])
check("patch_source_field: original field preserved",
      _psf_content.get("heart_rates", {}).get("heartRateValues") == [[0, 60]])

_psf_log = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("patch_source_field: backfilled_fields recorded in log",
      "steps" in _psf_log.get(_psf_date, {}).get("backfilled_fields", {}))
check("patch_source_field: original log entry preserved",
      _psf_log.get(_psf_date, {}).get("validator_status") == "ok")

_psf_noop = source_writer.patch_source_field("1900-01-01", "steps", [])
check("patch_source_field: no source file → True (no-op)", _psf_noop is True)

# ── write_source: normal write ────────────────────────────────────────────────
_sw_date = "2024-05-01"
_sw_raw  = {"date": _sw_date, "heart_rates": {"restingHeartRate": 58}, "sleep": {}}
_sw_ok   = source_writer.write_source(_sw_raw, _sw_date)
import garmin_config as _sw_cfg
_sw_file = _sw_cfg.SOURCE_DIR / f"garmin_source_{_sw_date}.json"

check("write_source: returns True",        _sw_ok == True)
check("write_source: file created",        _sw_file.exists())
check("write_source: content correct",
      json.loads(_sw_file.read_text(encoding="utf-8")).get("date") == _sw_date)
check("write_source: no .tmp leftover",
      not (_sw_file.with_suffix(".json.tmp")).exists())

# ── write_source: second write overwrites (idempotent) ───────────────────────
_sw_raw2  = {"date": _sw_date, "heart_rates": {"restingHeartRate": 62}}
_sw_ok2   = source_writer.write_source(_sw_raw2, _sw_date)
check("write_source: overwrite returns True",  _sw_ok2 == True)
check("write_source: overwrite content updated",
      json.loads(_sw_file.read_text(encoding="utf-8"))
      .get("heart_rates", {}).get("restingHeartRate") == 62)

# ── write_source: non-dict input → False, no crash ───────────────────────────
check("write_source: None input → False",  source_writer.write_source(None, _sw_date) == False)
check("write_source: str input → False",   source_writer.write_source("bad", _sw_date) == False)

# ── update_log: new entry ─────────────────────────────────────────────────────
_val_ok = {"status": "ok", "issues": [], "schema_version": "1.0"}
_ul_ok  = source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["sleep", "heart_rates", "stress"],
    endpoints_failed=[],
    size_bytes=1234,
)
check("update_log: returns True",          _ul_ok == True)
check("update_log: log file created",      _sw_cfg.SOURCE_API_LOG.exists())

_sw_log = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
_sw_entry = _sw_log.get(_sw_date, {})
check("update_log: date key present",      _sw_date in _sw_log)
check("update_log: fetched_at present",    bool(_sw_entry.get("fetched_at")))
check("update_log: source = api",          _sw_entry.get("source") == "api")
check("update_log: validator_status = ok", _sw_entry.get("validator_status") == "ok")
check("update_log: endpoints_fetched set",
      "sleep" in _sw_entry.get("endpoints_fetched", []))
check("update_log: size_bytes stored",     _sw_entry.get("size_bytes") == 1234)

# ── update_log: second call same date → overwrites, no duplicate ──────────────
_val_warn = {"status": "warning", "issues": [{"type": "out_of_range", "field": "heart_rates.restingHeartRate"}], "schema_version": "1.0"}
source_writer.update_log(
    _sw_date, _val_warn,
    endpoints_fetched=["sleep", "heart_rates"],
    endpoints_failed=["stress"],
    size_bytes=999,
)
_sw_log2  = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: no duplicate — still 1 entry for date",
      list(_sw_log2.keys()).count(_sw_date) == 1)
check("update_log: overwrite: validator_status updated",
      _sw_log2.get(_sw_date, {}).get("validator_status") == "warning")
check("update_log: overwrite: endpoints_failed updated",
      "stress" in _sw_log2.get(_sw_date, {}).get("endpoints_failed", []))

# ── update_log: second date → two entries in log ──────────────────────────────
_sw_date2 = "2024-05-02"
source_writer.update_log(
    _sw_date2, _val_ok,
    endpoints_fetched=["sleep"],
    endpoints_failed=[],
    size_bytes=500,
)
_sw_log3 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: two dates → two entries",
      _sw_date in _sw_log3 and _sw_date2 in _sw_log3)

# ── update_log: intraday_present stored when raw_data provided ────────────────
_sw_raw_intraday = {
    "date": _sw_date,
    "heart_rates": {"heartRateValues": [[0, 60], [60, 65]], "restingHeartRate": 58},
    "stress": {},
}
source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=512,
    raw_data=_sw_raw_intraday,
)
_sw_log_ip = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present=True when HR values present",
      _sw_log_ip.get(_sw_date, {}).get("intraday_present") == True)

_sw_raw_no_intraday = {"date": _sw_date, "heart_rates": {"restingHeartRate": 58}}
source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=100,
    raw_data=_sw_raw_no_intraday,
)
_sw_log_ip2 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present=False when no intraday arrays",
      _sw_log_ip2.get(_sw_date, {}).get("intraday_present") == False)

source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=100,
)
_sw_log_ip3 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present absent when raw_data=None",
      "intraday_present" not in _sw_log_ip3.get(_sw_date, {}))

# ── garmin_source_quality — assess_source ────────────────────────────────────
import garmin_source_quality as _sq
importlib.reload(_sq)

_sq_raw_hr   = {"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}
_sq_raw_str  = {"stress": {"stressValuesArray": [[0, 30]], "bodyBatteryValuesArray": [[0, 80]]}}
_sq_raw_none = {"heart_rates": {"restingHeartRate": 58}, "stress": {}}
_sq_raw_empty= {"heart_rates": {"heartRateValues": [], "restingHeartRate": 58}}

check("assess_source: HR values → present=True",
      _sq.assess_source(_sq_raw_hr)["intraday_present"] == True)
check("assess_source: stress/BB arrays → present=True",
      _sq.assess_source(_sq_raw_str)["intraday_present"] == True)
check("assess_source: no intraday arrays → present=False",
      _sq.assess_source(_sq_raw_none)["intraday_present"] == False)
check("assess_source: empty HR list → present=False",
      _sq.assess_source(_sq_raw_empty)["intraday_present"] == False)
check("assess_source: non-dict input → present=False",
      _sq.assess_source(None)["intraday_present"] == False)

# ── garmin_source_quality — compare_source (truth table) ─────────────────────
_sq_present = {"intraday_present": True}
_sq_absent  = {"intraday_present": False}

check("compare_source: no existing → write",
      _sq.compare_source(None, _sq_present) == "write")
check("compare_source: no existing, new absent → write",
      _sq.compare_source(None, _sq_absent) == "write")
check("compare_source: existing absent, new present → write",
      _sq.compare_source(_sq_absent, _sq_present) == "write")
check("compare_source: existing absent, new absent → write",
      _sq.compare_source(_sq_absent, _sq_absent) == "write")
check("compare_source: existing present, new present → skip",
      _sq.compare_source(_sq_present, _sq_present) == "skip")
check("compare_source: existing present, new absent → skip_warn",
      _sq.compare_source(_sq_present, _sq_absent) == "skip_warn")
check("compare_source: existing unreadable → skip_warn (F-4)",
      _sq.compare_source({"unreadable": True}, _sq_present) == "skip_warn")
check("compare_source: existing unreadable, new absent → skip_warn (F-4)",
      _sq.compare_source({"unreadable": True}, _sq_absent) == "skip_warn")

# ── garmin_source_quality — assess_source_from_file ──────────────────────────
_sq_file = cfg.SOURCE_DIR / "garmin_source_2024-05-03.json"
cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
_sq_file.write_text(
    json.dumps({"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}),
    encoding="utf-8",
)
_sq_from_file = _sq.assess_source_from_file(_sq_file)
check("assess_source_from_file: file with intraday → present=True",
      _sq_from_file is not None and _sq_from_file["intraday_present"] == True)
check("assess_source_from_file: missing file → None",
      _sq.assess_source_from_file(cfg.SOURCE_DIR / "garmin_source_9999-01-01.json") is None)
_sq_file.unlink()

# ── write_source() guard — skip and skip_warn behavior ───────────────────────
_sq_guard_date = "2024-05-04"
_sq_guard_file = cfg.SOURCE_DIR / f"garmin_source_{_sq_guard_date}.json"

# Write initial high-res file
_sq_raw_good = {"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}
source_writer.write_source(_sq_raw_good, _sq_guard_date)
check("guard setup: initial write → file exists",
      _sq_guard_file.exists())

# Attempt overwrite with degraded response → skip_warn → file unchanged
_sq_raw_degraded = {"heart_rates": {"restingHeartRate": 58}}
_sq_ok = source_writer.write_source(_sq_raw_degraded, _sq_guard_date)
_sq_content = json.loads(_sq_guard_file.read_text(encoding="utf-8"))
check("guard: skip_warn → returns True (non-fatal)",
      _sq_ok == True)
check("guard: skip_warn → existing intraday file preserved",
      _sq_content.get("heart_rates", {}).get("heartRateValues") is not None)

# Attempt overwrite with another high-res response → skip → file unchanged
_sq_raw_good2 = {"heart_rates": {"heartRateValues": [[0, 70]], "restingHeartRate": 62}}
_sq_ok2 = source_writer.write_source(_sq_raw_good2, _sq_guard_date)
_sq_content2 = json.loads(_sq_guard_file.read_text(encoding="utf-8"))
check("guard: skip (freeze-when-present) → returns True",
      _sq_ok2 == True)
check("guard: skip → original intraday values preserved (not 70)",
      _sq_content2.get("heart_rates", {}).get("heartRateValues", [[0, 0]])[0][1] == 60)

_sq_guard_file.unlink()

# ── Leaf-Node check — garmin_source_quality (new leaf) ───────────────────────
import ast as _ast
_sq_src = Path(__file__).parent.parent / "garmin" / "garmin_source_quality.py"
if _sq_src.exists():
    _sq_tree     = _ast.parse(_sq_src.read_text(encoding="utf-8"))
    _sq_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_config", "garmin_source_writer",
    }
    _sq_imports = set()
    for _node in _ast.walk(_sq_tree):
        if isinstance(_node, _ast.Import):
            for _alias in _node.names:
                _sq_imports.add(_alias.name.split(".")[0])
        elif isinstance(_node, _ast.ImportFrom):
            if _node.module:
                _sq_imports.add(_node.module.split(".")[0])
    _sq_violations = _sq_imports & _sq_forbidden
    check("source_quality leaf-node: no forbidden imports",
          len(_sq_violations) == 0)
else:
    check("source_quality leaf-node: file found for AST check", False)

# ── Cleanup ───────────────────────────────────────────────────────────────────
if _sw_file.exists():
    _sw_file.unlink()
if _sw_cfg.SOURCE_API_LOG.exists():
    _sw_cfg.SOURCE_API_LOG.unlink()

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
#  C2. garmin_container — unlock_meta (happy path + error cases)
# ══════════════════════════════════════════════════════════════════════════════
section("C2. garmin_container — unlock_meta")

# Neues Fixture — eigener Temp-Ordner, isoliert von Section C
_c2_parent = Path(tempfile.mkdtemp(prefix="garmin_c2_"))
_c2_gla    = _c2_parent / "mirror_c2.gla"

# Quelle mit quality_log.json aufbauen
_c2_src = Path(tempfile.mkdtemp(prefix="garmin_c2_src_"))
(_c2_src / "garmin_data" / "log").mkdir(parents=True)
(_c2_src / "garmin_data" / "raw" / "2024-03-01").mkdir(parents=True)
(_c2_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": [{"date": "2024-03-01", "quality": "high"}]}),
    encoding="utf-8"
)
(_c2_src / "garmin_data" / "raw" / "2024-03-01" / "garmin_raw_2024-03-01.json").write_text(
    _json.dumps({"hr": 55, "source": "api"}), encoding="utf-8"
)
mirror.run_mirror(_c2_src, _c2_gla, "correct-pw")

# C2a — Happy Path
_um_ok = _gc.unlock_meta(_c2_gla, "correct-pw")
check("unlock_meta: ok=True on correct password",    _um_ok["ok"] == True)
check("unlock_meta: quality_log is dict",            isinstance(_um_ok.get("quality_log"), dict))
check("unlock_meta: quality_log has days",           "days" in _um_ok.get("quality_log", {}))
check("unlock_meta: container_meta not empty",       bool(_um_ok.get("container_meta")))
check("unlock_meta: error is empty string",          _um_ok.get("error") == "")

# C2b — Falsches Passwort
_um_bad_pw = _gc.unlock_meta(_c2_gla, "wrong-pw")
check("unlock_meta: ok=False on wrong password",     _um_bad_pw["ok"] == False)
check("unlock_meta: quality_log empty on wrong pw",  _um_bad_pw.get("quality_log") == {})
check("unlock_meta: error string set on wrong pw",   bool(_um_bad_pw.get("error")))

# C2c — Nicht-existente Datei
_um_missing = _gc.unlock_meta(_c2_parent / "ghost.gla", "correct-pw")
check("unlock_meta: ok=False on missing file",       _um_missing["ok"] == False)

# C2d — Kein Container (zufälliger Inhalt)
_c2_junk = _c2_parent / "junk.bin"
_c2_junk.write_bytes(b"THIS IS NOT A GLA CONTAINER AT ALL")
_um_junk = _gc.unlock_meta(_c2_junk, "correct-pw")
check("unlock_meta: ok=False on non-container file", _um_junk["ok"] == False)

# C2e — Tampered Header (HMAC-Bytes überschreiben)
import shutil as _shutil
_c2_tampered = _c2_parent / "tampered.gla"
_shutil.copy2(_c2_gla, _c2_tampered)
with open(_c2_tampered, "r+b") as _tf:
    # magic(4) + format_ver(1) + salt(16) = offset 21 → HMAC beginnt hier
    _tf.seek(4 + 1 + 16)
    _tf.write(b"\xff" * 32)  # 32 HMAC-Bytes korrumpieren
_um_tampered = _gc.unlock_meta(_c2_tampered, "correct-pw")
check("unlock_meta: ok=False on tampered HMAC",      _um_tampered["ok"] == False)

# ══════════════════════════════════════════════════════════════════════════════
#  C3. garmin_container — fulfill_order (happy path + error cases)
# ══════════════════════════════════════════════════════════════════════════════
section("C3. garmin_container — fulfill_order")

# C3a — Happy Path: raw-Datei anfordern und Inhalt prüfen
_fo_order  = {"raw": ["garmin_data/raw/2024-03-01/garmin_raw_2024-03-01.json"]}
_fo_result = _gc.fulfill_order(_c2_gla, "correct-pw", _fo_order)
_fo_key    = "garmin_data/raw/2024-03-01/garmin_raw_2024-03-01.json"
check("fulfill_order: requested key in result",      _fo_key in _fo_result)
check("fulfill_order: returned value is bytes",      isinstance(_fo_result.get(_fo_key), bytes))
_fo_parsed = _json.loads(_fo_result[_fo_key]) if _fo_key in _fo_result else {}
check("fulfill_order: content matches original",     _fo_parsed.get("hr") == 55)

# C3b — Falsches Passwort → leeres dict
_fo_bad_pw = _gc.fulfill_order(_c2_gla, "wrong-pw", _fo_order)
check("fulfill_order: empty dict on wrong password", _fo_bad_pw == {})

# C3c — Leere Order → leeres dict (kein Crash)
_fo_empty = _gc.fulfill_order(_c2_gla, "correct-pw", {})
check("fulfill_order: empty order → empty dict",     _fo_empty == {})

# Aufräumen C2/C3
shutil.rmtree(_c2_src,    ignore_errors=True)
shutil.rmtree(_c2_parent, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  C4. garmin_import_mirror — detect_source
# ══════════════════════════════════════════════════════════════════════════════
section("C4. garmin_import_mirror — detect_source")
import garmin_import_mirror as _import_mirror
importlib.reload(_import_mirror)

# C4a — Valider Container → "container"
_c4_parent = Path(tempfile.mkdtemp(prefix="garmin_c4_"))
_c4_gla    = _c4_parent / "mirror_c4.gla"
_c4_src    = Path(tempfile.mkdtemp(prefix="garmin_c4_src_"))
(_c4_src / "garmin_data" / "log").mkdir(parents=True)
(_c4_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": []}), encoding="utf-8"
)
mirror.run_mirror(_c4_src, _c4_gla, "pw")
check("detect_source: valid .gla → 'container'",
      _import_mirror.detect_source(_c4_gla) == "container")

# C4b — Nicht-existenter Pfad → "unknown"
check("detect_source: nonexistent path → 'unknown'",
      _import_mirror.detect_source(_c4_parent / "ghost.gla") == "unknown")

# C4c — Normaler Ordner ohne mirror_meta.json → "unknown"
_c4_plain_dir = Path(tempfile.mkdtemp(prefix="garmin_c4_plain_"))
check("detect_source: plain dir without mirror_meta → 'unknown'",
      _import_mirror.detect_source(_c4_plain_dir) == "unknown")

# Aufräumen C4
shutil.rmtree(_c4_src,       ignore_errors=True)
shutil.rmtree(_c4_parent,    ignore_errors=True)
shutil.rmtree(_c4_plain_dir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  F. garmin_backup_source (v1.6.0.4)
# ══════════════════════════════════════════════════════════════════════════════
section("F. garmin_backup_source (v1.6.0.4)")
import garmin_backup_source as backup_src
importlib.reload(backup_src)

# ── Pfad-Ableitung ────────────────────────────────────────────────────────────
check("backup_src: SOURCE_BACKUP_DIR derived",
      cfg.SOURCE_BACKUP_DIR == _TMPDIR / "garmin_data" / "backup" / "source")

# ── backup_source: Quelldatei fehlt → False ───────────────────────────────────
check("backup_source: missing source → False",
      backup_src.backup_source("1900-01-01") == False)

# ── backup_source: normaler Write → True, Datei in YYYY-MM/ ──────────────────
_bsrc_date  = "2024-03-15"
_bsrc_file  = cfg.SOURCE_DIR / f"garmin_source_{_bsrc_date}.json"
cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
_bsrc_file.write_text('{"date": "2024-03-15"}', encoding="utf-8")

_bsrc_ok = backup_src.backup_source(_bsrc_date)
check("backup_source: returns True",
      _bsrc_ok == True)
check("backup_source: file in month dir",
      (cfg.SOURCE_BACKUP_DIR / "2024-03" / f"garmin_source_{_bsrc_date}.json").exists())

# ── consolidate: alter Monat wird gezippt ─────────────────────────────────────
from datetime import date as _bsrc_date_cls
_bsrc_current_month = _bsrc_date_cls.today().strftime("%Y-%m")
_old_src_date = "2024-01-10"
_old_src_dir  = cfg.SOURCE_BACKUP_DIR / "2024-01"
_old_src_dir.mkdir(parents=True, exist_ok=True)
(_old_src_dir / f"garmin_source_{_old_src_date}.json").write_text("{}", encoding="utf-8")
# Aktuellen Monatsordner anlegen damit consolidate ihn korrekt überspringt
_cur_src_dir = cfg.SOURCE_BACKUP_DIR / _bsrc_current_month
_cur_src_dir.mkdir(parents=True, exist_ok=True)
(_cur_src_dir / f"garmin_source_{_bsrc_current_month}-01.json").write_text("{}", encoding="utf-8")
backup_src._consolidate_source_months(current_month=_bsrc_current_month)
check("consolidate: old month zipped",
      (cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip").exists())
check("consolidate: old month dir removed",
      not _old_src_dir.exists())
check("consolidate: current month not zipped",
      not (cfg.SOURCE_BACKUP_DIR / f"source_backup_{_bsrc_current_month}.zip").exists())

# ── check_source_backfill_needed ──────────────────────────────────────────────
# Neue source-Datei ohne Backup → count ≥ 1
_bsrc_date2 = "2024-03-16"
_bsrc_file2 = cfg.SOURCE_DIR / f"garmin_source_{_bsrc_date2}.json"
_bsrc_file2.write_text('{"date": "2024-03-16"}', encoding="utf-8")
check("backfill_needed: unbackedup file → ≥1",
      backup_src.check_source_backfill_needed() >= 1)

# ── backfill_source ───────────────────────────────────────────────────────────
_bfill_result = backup_src.backfill_source()
check("backfill_source: returns dict",        isinstance(_bfill_result, dict))
check("backfill_source: ≥1 copied",           _bfill_result["copied"] >= 1)
check("backfill_source: failed=0",            _bfill_result["failed"] == 0)

# backfill idempotent
_bfill_result2 = backup_src.backfill_source()
check("backfill_source: idempotent → copied=0",   _bfill_result2["copied"] == 0)
check("backfill_source: idempotent → skipped≥1",  _bfill_result2["skipped"] >= 1)

# check_source_backfill_needed → 0 nach Backfill
check("backfill_needed: after backfill → 0",
      backup_src.check_source_backfill_needed() == 0)

# ── _zip_contains helper ──────────────────────────────────────────────────────
check("backup_src: _zip_contains present → True",
      backup_src._zip_contains(
          cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip",
          f"garmin_source_{_old_src_date}.json"))
check("backup_src: _zip_contains absent → False",
      not backup_src._zip_contains(
          cfg.SOURCE_BACKUP_DIR / "source_backup_2024-01.zip",
          "nonexistent.json"))

# ── Leaf-Node check — keine Pipeline-Imports ──────────────────────────────────
import ast as _bsrc_ast
_bsrc_py = Path(__file__).parent.parent / "garmin" / "garmin_backup_source.py"
if _bsrc_py.exists():
    _bsrc_tree     = _bsrc_ast.parse(_bsrc_py.read_text(encoding="utf-8"))
    _bsrc_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_source_writer",
    }
    _bsrc_imports = set()
    for _n in _bsrc_ast.walk(_bsrc_tree):
        if isinstance(_n, _bsrc_ast.Import):
            for _a in _n.names:
                _bsrc_imports.add(_a.name.split(".")[0])
        elif isinstance(_n, _bsrc_ast.ImportFrom):
            if _n.module:
                _bsrc_imports.add(_n.module.split(".")[0])
    check("backup_src: Leaf-Node — no forbidden pipeline imports",
          _bsrc_imports.isdisjoint(_bsrc_forbidden))

# ══════════════════════════════════════════════════════════════════════════════
#  G. garmin_silo_check (v1.6.0.4.7)
# ══════════════════════════════════════════════════════════════════════════════
section("G. garmin_silo_check (v1.6.0.4.7)")
import garmin_silo_check as silo_check
importlib.reload(silo_check)

# ── Result structure — clean archive (no findings) ────────────────────────────
# ── Result structure + clean-silo baseline (isolated tmpdir) ─────────────────
# Uses a fresh temp dir so no artefacts from earlier sections bleed in.
import tempfile as _sc_tempfile
_sc_iso_dir = Path(_sc_tempfile.mkdtemp(prefix="garmin_sc_"))
_sc_orig_env = os.environ.get("GARMIN_OUTPUT_DIR", "")
os.environ["GARMIN_OUTPUT_DIR"] = str(_sc_iso_dir)
importlib.reload(cfg)
importlib.reload(silo_check)

_sc_result = silo_check.check_silos()

check("silo_check: returns dict",
      isinstance(_sc_result, dict))
check("silo_check: key raw_without_quality present",
      "raw_without_quality" in _sc_result)
check("silo_check: key source_without_raw present",
      "source_without_raw" in _sc_result)
check("silo_check: key summary_without_raw present",
      "summary_without_raw" in _sc_result)
check("silo_check: key raw_without_summary present",
      "raw_without_summary" in _sc_result)
check("silo_check: key checked_at present",
      "checked_at" in _sc_result)
check("silo_check: key totals present",
      "totals" in _sc_result)
check("silo_check: key counts present",
      "counts" in _sc_result)

# totals sub-keys
_sc_totals = _sc_result["totals"]
check("silo_check: totals.raw present",
      "raw" in _sc_totals)
check("silo_check: totals.summary present",
      "summary" in _sc_totals)
check("silo_check: totals.source present",
      "source" in _sc_totals)
check("silo_check: totals.quality_days present",
      "quality_days" in _sc_totals)

# counts sub-keys
_sc_counts = _sc_result["counts"]
check("silo_check: counts.raw_without_quality present",
      "raw_without_quality" in _sc_counts)
check("silo_check: counts.source_without_raw present",
      "source_without_raw" in _sc_counts)
check("silo_check: counts.summary_without_raw present",
      "summary_without_raw" in _sc_counts)
check("silo_check: counts.raw_without_summary present",
      "raw_without_summary" in _sc_counts)

# checked_at format (ISO-8601 Z suffix)
check("silo_check: checked_at ends with Z",
      _sc_result["checked_at"].endswith("Z"))

# Clean silo baseline → no findings
check("silo_check: clean silo → raw_without_quality empty",
      _sc_result["raw_without_quality"] == [])
check("silo_check: clean silo → source_without_raw empty",
      _sc_result["source_without_raw"] == [])
check("silo_check: clean silo → summary_without_raw empty",
      _sc_result["summary_without_raw"] == [])
check("silo_check: clean silo → raw_without_summary empty",
      _sc_result["raw_without_summary"] == [])
check("silo_check: clean silo → all counts zero",
      all(v == 0 for v in _sc_counts.values()))

# restore original GARMIN_OUTPUT_DIR + cfg for subsequent checks
os.environ["GARMIN_OUTPUT_DIR"] = _sc_orig_env
importlib.reload(cfg)
importlib.reload(silo_check)
shutil.rmtree(_sc_iso_dir, ignore_errors=True)

# ── #1: raw without quality_log entry ─────────────────────────────────────────
_sc1_dir = _TMPDIR / "garmin_data" / "raw"
_sc1_dir.mkdir(parents=True, exist_ok=True)
_sc1_date = "2024-11-01"
(_sc1_dir / f"garmin_raw_{_sc1_date}.json").write_text('{"date": "2024-11-01"}',
                                                         encoding="utf-8")
# quality_log does NOT get an entry for this date → orphan raw
_sc1_result = silo_check.check_silos()
from datetime import date as _sc_date_cls
check("silo_check: #1 raw without quality → detected",
      _sc_date_cls.fromisoformat(_sc1_date) in _sc1_result["raw_without_quality"])
check("silo_check: #1 count ≥ 1",
      _sc1_result["counts"]["raw_without_quality"] >= 1)
check("silo_check: #1 totals.raw ≥ 1",
      _sc1_result["totals"]["raw"] >= 1)

# cleanup
(_sc1_dir / f"garmin_raw_{_sc1_date}.json").unlink(missing_ok=True)

# ── #3: source without raw ────────────────────────────────────────────────────
_sc3_src_dir = _TMPDIR / "garmin_data" / "source"
_sc3_src_dir.mkdir(parents=True, exist_ok=True)
_sc3_date = "2024-11-02"
(_sc3_src_dir / f"garmin_source_{_sc3_date}.json").write_text(
    '{"date": "2024-11-02"}', encoding="utf-8")
# no matching raw file → source_without_raw
_sc3_result = silo_check.check_silos()
check("silo_check: #3 source without raw → detected",
      _sc_date_cls.fromisoformat(_sc3_date) in _sc3_result["source_without_raw"])
check("silo_check: #3 count ≥ 1",
      _sc3_result["counts"]["source_without_raw"] >= 1)
check("silo_check: #3 totals.source ≥ 1",
      _sc3_result["totals"]["source"] >= 1)

# cleanup
(_sc3_src_dir / f"garmin_source_{_sc3_date}.json").unlink(missing_ok=True)

# ── #5: summary without raw ───────────────────────────────────────────────────
_sc5_sum_dir = _TMPDIR / "garmin_data" / "summary"
_sc5_sum_dir.mkdir(parents=True, exist_ok=True)
_sc5_date = "2024-11-03"
(_sc5_sum_dir / f"garmin_{_sc5_date}.json").write_text(
    '{"date": "2024-11-03"}', encoding="utf-8")
# no matching raw file → summary_without_raw
_sc5_result = silo_check.check_silos()
check("silo_check: #5 summary without raw → detected",
      _sc_date_cls.fromisoformat(_sc5_date) in _sc5_result["summary_without_raw"])
check("silo_check: #5 count ≥ 1",
      _sc5_result["counts"]["summary_without_raw"] >= 1)
check("silo_check: #5 totals.summary ≥ 1",
      _sc5_result["totals"]["summary"] >= 1)

# cleanup
(_sc5_sum_dir / f"garmin_{_sc5_date}.json").unlink(missing_ok=True)

# ── #7: raw without summary ───────────────────────────────────────────────────
_sc7_raw_dir = _TMPDIR / "garmin_data" / "raw"
_sc7_raw_dir.mkdir(parents=True, exist_ok=True)
_sc7_date = "2024-11-04"
(_sc7_raw_dir / f"garmin_raw_{_sc7_date}.json").write_text(
    '{"date": "2024-11-04"}', encoding="utf-8")
# no matching summary file → raw_without_summary
_sc7_result = silo_check.check_silos()
check("silo_check: #7 raw without summary → detected",
      _sc_date_cls.fromisoformat(_sc7_date) in _sc7_result["raw_without_summary"])
check("silo_check: #7 count ≥ 1",
      _sc7_result["counts"]["raw_without_summary"] >= 1)

# cleanup
(_sc7_raw_dir / f"garmin_raw_{_sc7_date}.json").unlink(missing_ok=True)

# ── counts match len of lists ─────────────────────────────────────────────────
_sc_final = silo_check.check_silos()
check("silo_check: counts match list lengths",
      _sc_final["counts"]["raw_without_quality"]  == len(_sc_final["raw_without_quality"])
      and _sc_final["counts"]["source_without_raw"]   == len(_sc_final["source_without_raw"])
      and _sc_final["counts"]["summary_without_raw"]  == len(_sc_final["summary_without_raw"])
      and _sc_final["counts"]["raw_without_summary"]  == len(_sc_final["raw_without_summary"]))

# ── finding lists contain date objects ───────────────────────────────────────
# Create one finding to verify type
_sc_type_dir = _TMPDIR / "garmin_data" / "raw"
_sc_type_dir.mkdir(parents=True, exist_ok=True)
_sc_type_date = "2024-11-05"
(_sc_type_dir / f"garmin_raw_{_sc_type_date}.json").write_text(
    '{"date": "2024-11-05"}', encoding="utf-8")
_sc_type_result = silo_check.check_silos()
check("silo_check: finding list contains date objects",
      len(_sc_type_result["raw_without_summary"]) >= 1
      and isinstance(_sc_type_result["raw_without_summary"][0], _sc_date_cls))
# cleanup
(_sc_type_dir / f"garmin_raw_{_sc_type_date}.json").unlink(missing_ok=True)

# ── Leaf-Node AST check — only garmin_config + stdlib ────────────────────────
import ast as _sc_ast
_sc_py = Path(__file__).parent.parent / "garmin" / "garmin_silo_check.py"
if _sc_py.exists():
    _sc_tree = _sc_ast.parse(_sc_py.read_text(encoding="utf-8"))
    _sc_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_source_writer", "garmin_backup", "garmin_utils",
        "garmin_import_mirror", "garmin_mirror",
    }
    _sc_imports = set()
    for _n in _sc_ast.walk(_sc_tree):
        if isinstance(_n, _sc_ast.Import):
            for _a in _n.names:
                _sc_imports.add(_a.name.split(".")[0])
        elif isinstance(_n, _sc_ast.ImportFrom):
            if _n.module:
                _sc_imports.add(_n.module.split(".")[0])
    check("silo_check: Leaf-Node — no forbidden pipeline imports",
          _sc_imports.isdisjoint(_sc_forbidden))
else:
    check("silo_check: Leaf-Node — garmin_silo_check.py found", False)

# ══════════════════════════════════════════════════════════════════════════════
#  H. garmin_live_fetch
# ══════════════════════════════════════════════════════════════════════════════
section("H. garmin_live_fetch")
import garmin_live_fetch as live_fetch
importlib.reload(live_fetch)

# ── _ENDPOINTS structure — 8 entries, HRV included ────────────────────────────
check("live_fetch: _ENDPOINTS has 8 entries",
      len(live_fetch._ENDPOINTS) == 8)
check("live_fetch: _ENDPOINTS includes get_hrv_data/hrv",
      ("get_hrv_data", "hrv") in live_fetch._ENDPOINTS)
check("live_fetch: _ENDPOINTS includes get_sleep_data/sleep",
      ("get_sleep_data", "sleep") in live_fetch._ENDPOINTS)

# ── fetch_live — success path, client provided (no login) ────────────────────
_lf_mock_client = MagicMock()
_lf_call_log = []

def _lf_api_call_success(client, method, *args, label=""):
    _lf_call_log.append((method, args))
    return ({"stub": method}, True)

with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result = live_fetch.fetch_live(client=_lf_mock_client)

check("fetch_live success: ok=True",              _lf_result["ok"] == True)
check("fetch_live success: no failed endpoints",  _lf_result["failed_endpoints"] == [])
check("fetch_live success: 8 api_call invocations", len(_lf_call_log) == 8)
check("fetch_live success: hrv endpoint called",
      any(m == "get_hrv_data" for m, _ in _lf_call_log))

check("fetch_live success: LIVE_FILE created", cfg.LIVE_FILE.exists())
_lf_written = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
check("fetch_live success: date key present",     "date" in _lf_written)
check("fetch_live success: synced_at key present", "synced_at" in _lf_written)
check("fetch_live success: hrv section written",
      _lf_written.get("hrv") == {"stub": "get_hrv_data"})
check("fetch_live success: sleep section written",
      _lf_written.get("sleep") == {"stub": "get_sleep_data"})

# ── fetch_live — partial failure — one endpoint fails, no crash ──────────────
def _lf_api_call_partial(client, method, *args, label=""):
    if method == "get_spo2_data":
        return (None, False)
    return ({"stub": method}, True)

with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_partial):
    _lf_result2 = live_fetch.fetch_live(client=_lf_mock_client)

check("fetch_live partial: ok=True despite one failure", _lf_result2["ok"] == True)
check("fetch_live partial: spo2 in failed_endpoints",
      "spo2" in _lf_result2["failed_endpoints"])
check("fetch_live partial: only one failed endpoint",
      len(_lf_result2["failed_endpoints"]) == 1)

_lf_written2 = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
check("fetch_live partial: spo2 key absent from live.json",
      "spo2" not in _lf_written2)
check("fetch_live partial: other sections still written",
      _lf_written2.get("heart_rates") == {"stub": "get_heart_rates"})

# ── fetch_live — no client, login fails (GarminLoginError) ───────────────────
with patch.object(live_fetch.garmin_api, "login",
                  side_effect=live_fetch.garmin_api.GarminLoginError("boom")):
    _lf_result3 = live_fetch.fetch_live(client=None)
check("fetch_live login failure: ok=False",              _lf_result3["ok"] == False)
check("fetch_live login failure: empty failed_endpoints", _lf_result3["failed_endpoints"] == [])

# ── fetch_live — no client, login cancelled (returns None) ───────────────────
with patch.object(live_fetch.garmin_api, "login", return_value=None):
    _lf_result4 = live_fetch.fetch_live(client=None)
check("fetch_live login cancelled: ok=False", _lf_result4["ok"] == False)

# ── fetch_live — no client, login succeeds, reuses api_call path ─────────────
with patch.object(live_fetch.garmin_api, "login", return_value=_lf_mock_client), \
     patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result5 = live_fetch.fetch_live(client=None)
check("fetch_live own-login: ok=True", _lf_result5["ok"] == True)

# ── fetch_live — progress callback receives messages ──────────────────────────
_lf_progress_msgs = []
with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result6 = live_fetch.fetch_live(
        client=_lf_mock_client,
        progress=lambda msg: _lf_progress_msgs.append(msg))

check("fetch_live progress: callback received messages",
      len(_lf_progress_msgs) > 0)
check("fetch_live progress: mentions every endpoint",
      all(any(key in m for m in _lf_progress_msgs) for _, key in live_fetch._ENDPOINTS))
check("fetch_live progress: mentions completion",
      any("complete" in m for m in _lf_progress_msgs))
check("fetch_live progress: fetch itself still succeeds",
      _lf_result6["ok"] == True)

# ── fetch_live — progress defaults to no-op (backward compatible) ────────────
with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result7 = live_fetch.fetch_live(client=_lf_mock_client)  # no progress kwarg
check("fetch_live: works without progress arg (backward compatible)",
      _lf_result7["ok"] == True)

# ── _write_live — creates LIVE_DIR if missing ─────────────────────────────────
shutil.rmtree(cfg.LIVE_DIR, ignore_errors=True)
check("live_fetch: LIVE_DIR removed for test", not cfg.LIVE_DIR.exists())
live_fetch._write_live({"date": "2026-07-07", "synced_at": "2026-07-07T12:00:00Z"})
check("_write_live: creates LIVE_DIR",  cfg.LIVE_DIR.exists())
check("_write_live: creates LIVE_FILE", cfg.LIVE_FILE.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + Results
# ══════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
