#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_quality.py — garmin_quality

Run from the project folder:
    python tests/test_quality.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import sys
import threading
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from gla_testenv import cfg, _TMPDIR, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

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

# F8 — malformed intraday arrays (flat list instead of [ts,val] pairs) —
# array present but not parseable → falls through instead of "high",
# field_downgrades recorded with a short reason.
raw_fields_malformed = {
    "date": "2026-07-27",
    "heart_rates": {"heartRateValues": [60, 62, 58], "restingHeartRate": 55},
    "stress":      {"stressValuesArray": [30, 32], "averageStressLevel": 28,
                    "bodyBatteryValuesArray": [80, 82]},
    "spo2":        {"spO2HourlyAverages": [97, 98], "averageSpO2": 96},
    "respiration": {"respirationValuesArray": [14, 15], "avgWakingRespirationValue": 13},
}
f_mal = quality.assess_quality_fields(raw_fields_malformed)
check("f8: heart_rates falls to medium",   f_mal.get("heart_rates") == "medium")
check("f8: stress falls to medium",        f_mal.get("stress") == "medium")
check("f8: spo2 falls to medium",          f_mal.get("spo2") == "medium")
check("f8: respiration falls to medium",   f_mal.get("respiration") == "medium")
check("f8: body_battery falls to failed",  f_mal.get("body_battery") == "failed")
check("f8: downgrade reasons recorded",    len(f_mal.get("_downgrade_reasons", {})) == 5)

# Good case unaffected — real [ts,val] pairs still reach "high", no downgrade marker
f8_good = quality.assess_quality_fields(raw_fields_high)
check("f8: good case still high",          f8_good.get("heart_rates") == "high")
check("f8: good case no downgrade marker", "_downgrade_reasons" not in f8_good)

# v1.7.1.13, Issue #6 — body_battery quality label with the real 4-element
# [ts, status, value, extra] shape from stress.bodyBatteryValuesArray
# (GitHub Issue #6, reporter Gene-Howard, confirmed 2026-09-05). Before the
# _parse_list_values dict_key fix this fell through to "failed" on every
# archived day — the status string at index 1 is not numeric, so the
# parseability check always failed despite valid data being present.
raw_bb_real_shape = {
    "date": "2026-09-05",
    "stress": {
        "bodyBatteryValuesArray": [
            [1788580800000, "MEASURED", 28, 3.0],
            [1788581100000, "MEASURED", 30, 3.0],
        ],
    },
}
f_bb_fixed = quality.assess_quality_fields(raw_bb_real_shape)
check("issue6: body_battery 4-element triplet → high (was: failed)",
      f_bb_fixed.get("body_battery") == "high")
check("issue6: body_battery — no downgrade marker on valid triplet data",
      "body_battery" not in f_bb_fixed.get("_downgrade_reasons", {}))

# Sparse 2-element [ts, val] entries with dict_key=2 (too short for index 2)
# — must be skipped per-item, not raise IndexError, and must not silently
# produce a wrong "high" from garbage. Placed under stress.bodyBatteryValuesArray
# artificially here to isolate the dict_key=2/short-tuple path in assess_
# quality_fields() specifically; the real 2-element shape from Issue #6
# (body_battery[0].bodyBatteryValuesArray) is a separate, pre-existing,
# deliberately-not-fixed path (F8 CHANGELOG note) not exercised by this test.
raw_bb_short_tuples = {
    "date": "2026-09-05",
    "stress": {
        "bodyBatteryValuesArray": [[1788580800000, 28], [1788603300000, 60]],
    },
}
f_bb_short = quality.assess_quality_fields(raw_bb_short_tuples)
check("issue6: dict_key=2 on 2-element tuples → no crash, correctly not parseable",
      f_bb_short.get("body_battery") in ("low", "failed"))

# field_downgrades — stored only when a downgrade actually occurred
data_f8 = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_f8, date(2026, 7, 27), "standard", "Quality: standard",
                        written=True, source="api", fields=f_mal)
check("f8: field_downgrades stored on new entry",
      len(data_f8["days"][0].get("field_downgrades", {})) == 5)
check("f8: fields dict clean, no leaked internal key",
      "_downgrade_reasons" not in data_f8["days"][0]["fields"])

# Re-assessment with clean data removes the stale marker
quality._upsert_quality(data_f8, date(2026, 7, 27), "standard", "Quality: standard",
                        written=True, source="api", fields=f8_good)
check("f8: stale field_downgrades removed on clean re-assessment",
      "field_downgrades" not in data_f8["days"][0])
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
#  4b-4e. garmin_quality — load/migrate, save, maintenance, assess/stats/scan
#         (v1.7.4.0.2; each test works in its own isolated log/raw/backup folders)
# ══════════════════════════════════════════════════════════════════════════════
from quality._io import _compute_checksum as _q_checksum
from quality._io import _compute_checksum_legacy as _q_checksum_legacy
from quality._io import _save_defective_log as _q_save_defective
from quality._fieldhash import _hash_field as _q_hash_field
from quality._maint import _set_first_day as _q_set_first_day
from quality._scan import _backfill_quality_log as _q_backfill
import garmin_backup as _q_backup_mod



# ── 4b. _load_quality_log — migrations and integrity ──────────────────────────
section("4b. garmin_quality — _load_quality_log migrations and integrity")

# old file name: failed_days.json with the 'failed' list and 'category' field
with _isolated_log_env("legacy_file"):
    (cfg.LOG_DIR / "failed_days.json").write_text(json.dumps(
        {"failed": [{"date": "2024-01-01", "category": "error"}]}), encoding="utf-8")
    d = quality._load_quality_log()
    check("load: failed_days.json migrated, 'failed' list becomes 'days'",
          len(d["days"]) == 1 and d["days"][0]["date"] == "2024-01-01")
    check("load: failed_days.json migrated, category 'error' becomes quality 'failed'",
          d["days"][0]["quality"] == "failed" and "category" not in d["days"][0])
    check("load: failed_days.json migrated to quality_log.json",
          cfg.QUALITY_LOG_FILE.exists())
    check("load: old failed_days.json is removed after migration",
          not (cfg.LOG_DIR / "failed_days.json").exists())

with _isolated_log_env("legacy_unlink_fail"):
    (cfg.LOG_DIR / "failed_days.json").write_text(json.dumps(
        {"failed": [{"date": "2024-01-05", "category": "error"}]}), encoding="utf-8")
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        d = quality._load_quality_log()
    check("load: failed_days.json cannot be removed -> migration still succeeds",
          len(d["days"]) == 1 and cfg.QUALITY_LOG_FILE.exists())

with _isolated_log_env("failed_key"):
    _put_log({"failed": [{"date": "2024-02-01", "quality": "high"}]})
    d = quality._load_quality_log()
    check("load: 'failed' key without 'days' in quality_log.json becomes 'days'",
          [e["date"] for e in d["days"]] == ["2024-02-01"])

with _isolated_log_env("days_not_list"):
    _put_log({"days": "not-a-list"})
    d = quality._load_quality_log()
    check("load: 'days' that is not a list -> empty structure",
          d["days"] == [] and d["first_day"] is None)

with _isolated_log_env("root_fields"):
    _put_log({"days": [{"date": "2024-03-01", "quality": "high"}]})
    d = quality._load_quality_log()
    check("load: missing first_day and devices are added",
          d["first_day"] is None and d["devices"] == [])

# Unix timestamps in first_day and device first_used/last_used
with _isolated_log_env("timestamps"):
    _put_log({"first_day": 1709294400, "days": [],
              "devices": [{"first_used": 1709294400, "last_used": "unknown"},
                          {"first_used": "2020-05-05", "last_used": 1709294400000}]})
    d = quality._load_quality_log()
    check("load: first_day stored as Unix timestamp becomes YYYY-MM-DD",
          d["first_day"] == "2024-03-01")
    check("load: device first_used as Unix timestamp becomes YYYY-MM-DD",
          d["devices"][0]["first_used"] == "2024-03-01")
    check("load: device last_used 'unknown' is left alone",
          d["devices"][0]["last_used"] == "unknown")
    check("load: device first_used already a date is left alone",
          d["devices"][1]["first_used"] == "2020-05-05")
    check("load: device last_used as millisecond timestamp becomes YYYY-MM-DD",
          d["devices"][1]["last_used"] == "2024-03-01")

# per-entry migrations
with _isolated_log_env("entries"):
    _put_log({"days": [
        {"date": "2024-04-01", "quality": "high", "device_rank": 2},
        {"date": "2024-04-02", "category": "incomplete"},
        {"date": "2024-04-03", "quality": "low", "attempts": 5},
    ]})
    d = quality._load_quality_log()
    e1, e2, e3 = d["days"]
    check("load: device_rank becomes device_id None with empty device_name",
          e1["device_id"] is None and e1["device_name"] == "" and "device_rank" not in e1)
    check("load: category other than 'error' becomes quality 'low'",
          e2["quality"] == "low" and "category" not in e2)
    check("load: missing entry fields get defaults (recheck, attempts, write, source, fields)",
          e1["recheck"] is False and e1["attempts"] == 0 and e1["write"] is None
          and e1["source"] == "legacy" and e1["fields"] == {}
          and e1["last_attempt"] is None and e1["last_checked"])
    check("load: a low entry is flagged for recheck by default",
          e2["recheck"] is True)
    check("load: attempts of a low entry are reset to 0",
          e3["attempts"] == 0)

# integrity: checksum written by the pre-v1.5.5 algorithm is accepted
with _isolated_log_env("legacy_checksum"):
    _cs_data = {"first_day": "2024-01-01", "devices": [],
                "days": [{"date": "2024-05-01", "quality": "high", "write": True}]}
    _legacy = _q_checksum_legacy(_cs_data)
    check("setup: legacy and current checksum differ for the test data",
          _legacy != _q_checksum(_cs_data))
    _cs_data["_checksum"] = _legacy
    _put_log(_cs_data)
    with patch.object(_q_backup_mod, "restore_quality_log") as _restore_mock:
        d = quality._load_quality_log()
    check("load: legacy checksum is accepted without an integrity warning",
          d["integrity_warnings"] == [])
    check("load: legacy checksum does not trigger a restore",
          not _restore_mock.called)

# integrity: mismatch while the backup module cannot be imported
with _isolated_log_env("mismatch_noimport"):
    _put_log({"first_day": "2024-01-01", "devices": [], "_checksum": "deadbeef",
              "days": [{"date": "2024-05-01", "quality": "high", "write": True}]})
    with patch.dict(sys.modules, {"garmin_backup": None}):
        d = quality._load_quality_log()
    check("load: checksum mismatch without garmin_backup -> no crash, warning for the year",
          d["integrity_warnings"] == ["log mismatch 2024"])
    check("load: checksum mismatch without garmin_backup -> current log is kept",
          len(d["days"]) == 1)

with _isolated_log_env("mismatch_norestore"):
    _put_log({"first_day": "2024-01-01", "devices": [], "_checksum": "deadbeef",
              "days": [{"date": "2024-05-01", "quality": "high", "write": True}]})
    with patch.object(_q_backup_mod, "restore_quality_log", return_value=None):
        d = quality._load_quality_log()
    check("load: checksum mismatch and no valid backup -> warning raised, current log kept",
          d["integrity_warnings"] == ["log mismatch 2024"] and len(d["days"]) == 1)

# Current behaviour for an unreadable file (Ist-Stand). To be replaced by the
# recovery described in ROADMAP v1.7.4.1 (copy of the file, restore from backup).
with _isolated_log_env("unreadable"):
    cfg.QUALITY_LOG_FILE.write_text("{broken json", encoding="utf-8")
    with patch.object(_q_backup_mod, "restore_quality_log") as _restore_mock:
        d = quality._load_quality_log()
    check("Ist-Stand unreadable log: no crash, empty log with a 'days' list",
          d["days"] == [] and d["first_day"] is None)
    check("Ist-Stand unreadable log: no integrity warning is raised",
          d["integrity_warnings"] == [])
    check("Ist-Stand unreadable log: restore from backup is not attempted",
          not _restore_mock.called)
    check("Ist-Stand unreadable log: loading alone leaves the file untouched",
          cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8") == "{broken json")
    quality._save_quality_log(d)
    check("Ist-Stand unreadable log: the next save overwrites it, no copy is kept",
          json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"] == []
          and not cfg.AUTORESTORE_DIR.exists())


# ── 4c. save paths ────────────────────────────────────────────────────────────
section("4c. garmin_quality — save_device_table, _save_quality_log, defective log")

_dev_days = [
    {"date": "2024-01-01", "quality": "high",     "device_id": "A", "device_name": "Old Name"},
    {"date": "2024-01-02", "quality": "standard", "device_id": "A", "device_name": "New Name"},
    {"date": "2024-01-03", "quality": "failed",   "device_id": "A", "device_name": ""},
    {"date": "2024-03-01", "quality": "high",     "device_id": "B", "device_name": "Venu"},
    {"date": "2024-02-01", "quality": "high",     "device_id": None, "device_name": ""},
    {"date": "2024-02-02", "quality": "standard", "device_id": None, "device_name": ""},
]
with _isolated_log_env("device_table"):
    quality.save_device_table({"days": _dev_days})
    rows = json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))
    ids = [r["device_id"] for r in rows]
    by_id = {r["device_id"]: r for r in rows}
    check("device_table: newest device first, unknown row, total row last",
          ids == ["B", "A", "__unknown__", "__total__"])
    check("device_table: most recent non-empty device name wins",
          by_id["A"]["name"] == "New Name")
    check("device_table: date range per device includes every entry",
          by_id["A"]["date_from"] == "2024-01-01" and by_id["A"]["date_to"] == "2024-01-03")
    check("device_table: only high/standard days are counted (failed day is not)",
          by_id["A"]["days_high"] == 1 and by_id["A"]["days_standard"] == 1
          and by_id["A"]["days_total"] == 2)
    check("device_table: unknown row counts the entries without device_id",
          by_id["__unknown__"]["name"] == "unknown"
          and by_id["__unknown__"]["days_total"] == 2)
    check("device_table: total row sums all rows",
          by_id["__total__"]["days_high"] == 3 and by_id["__total__"]["days_standard"] == 2
          and by_id["__total__"]["days_total"] == 5)

    _table_before = cfg.DEVICE_TABLE_FILE.read_bytes()
    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        quality.save_device_table({"days": []})
    check("device_table: write failure -> no crash, existing table unchanged",
          cfg.DEVICE_TABLE_FILE.read_bytes() == _table_before)

with _isolated_log_env("device_table_unknown"):
    quality.save_device_table({"days": [
        {"date": "2024-01-01", "quality": "high", "device_id": None, "device_name": " Fenix 6 "},
        {"date": "2024-01-02", "quality": "high", "device_id": None, "device_name": "Fenix 6"}]})
    rows = json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))
    check("device_table: unknown entries sharing one name show that name",
          [r["name"] for r in rows if r["device_id"] == "__unknown__"] == ["Fenix 6"])
    quality.save_device_table({"days": [
        {"date": "2024-01-01", "quality": "high", "device_id": None, "device_name": "Fenix 6"},
        {"date": "2024-01-02", "quality": "high", "device_id": None, "device_name": "Venu"}]})
    rows = json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))
    check("device_table: unknown entries with different names show 'unknown'",
          [r["name"] for r in rows if r["device_id"] == "__unknown__"] == ["unknown"])

with _isolated_log_env("save_log"):
    _good = {"first_day": "2024-01-01", "devices": [],
             "days": [{"date": "2024-01-01", "quality": "high", "write": True}]}
    quality._save_quality_log(_good, skip_backup=True)
    _file_before = cfg.QUALITY_LOG_FILE.read_bytes()

    _changed = {"first_day": "2024-01-01", "devices": [],
                "days": [{"date": "2024-01-01", "quality": "standard", "write": True}]}
    with patch.object(_q_backup_mod, "backup_quality_log") as _bk_mock, \
         patch("json.dump", side_effect=OSError("disk full")):
        quality._save_quality_log(_changed)
    check("save: write failure -> no crash, existing quality_log.json unchanged",
          cfg.QUALITY_LOG_FILE.read_bytes() == _file_before)
    check("save: write failure -> no backup is triggered",
          not _bk_mock.called)
    check("save: write failure leaves its temp file behind (current behaviour)",
          cfg.QUALITY_LOG_FILE.with_suffix(".tmp").exists())

    quality._save_quality_log(_changed, skip_backup=True)
    check("save: the next save succeeds and consumes the leftover temp file",
          not cfg.QUALITY_LOG_FILE.with_suffix(".tmp").exists()
          and json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
          ["days"][0]["quality"] == "standard")

    with patch.object(_q_backup_mod, "backup_quality_log", side_effect=RuntimeError("zip broke")):
        quality._save_quality_log(_good)
    check("save: backup trigger raising -> file is still written",
          json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
          ["days"][0]["quality"] == "high")
    with patch.dict(sys.modules, {"garmin_backup": None}):
        quality._save_quality_log(_changed)
    check("save: backup module not importable -> file is still written",
          json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
          ["days"][0]["quality"] == "standard")

    cfg.AUTORESTORE_DIR.write_text("a file, not a folder", encoding="utf-8")
    _q_save_defective(_good)
    check("defective log: folder cannot be created -> no crash",
          cfg.AUTORESTORE_DIR.is_file())


# ── 4d. maintenance: first_day, device name, attempts ─────────────────────────
section("4d. garmin_quality — _set_first_day, record_attempt, device name, backfill failures")

_fallback_saved = cfg.SYNC_AUTO_FALLBACK

_fd = {"first_day": "2020-01-01", "devices": [{"first_used": "2010-01-01"}], "days": []}
_q_set_first_day(_fd, None)
check("first_day: an existing value is never overwritten", _fd["first_day"] == "2020-01-01")

_fd = {"devices": [{"first_used": "2020-05-01"}, {"first_used": "2019-03-02"},
                   {"first_used": "unknown"}, {}], "days": []}
_q_set_first_day(_fd, None)
check("first_day: earliest device first_used wins ('unknown' and missing ignored)",
      _fd["first_day"] == "2019-03-02")

_client = MagicMock()
_client.get_user_profile.return_value = {"userInfo": {"registrationDate": "2018-07-04T10:00:00"}}
_fd = {"devices": [], "days": []}
_q_set_first_day(_fd, _client)
check("first_day: account registration date is used when no device has one",
      _fd["first_day"] == "2018-07-04")

cfg.SYNC_AUTO_FALLBACK = "2017-01-01"
_client = MagicMock()
_client.get_user_profile.side_effect = RuntimeError("API down")
_fd = {"devices": [], "days": [{"date": "2022-02-02"}]}
_q_set_first_day(_fd, _client)
check("first_day: failing profile call is swallowed, SYNC_AUTO_FALLBACK is used",
      _fd["first_day"] == "2017-01-01")

cfg.SYNC_AUTO_FALLBACK = ""
_fd = {"devices": [], "days": [{"date": "2022-02-02"}, {"date": "2021-01-01"}, {"x": 1}]}
_q_set_first_day(_fd, None)
check("first_day: oldest known day is the last resort",
      _fd["first_day"] == "2021-01-01")

_client = MagicMock()
_client.get_user_profile.return_value = None
_fd = {"devices": [], "days": [{"date": "2022-02-02"}]}
_q_set_first_day(_fd, _client)
check("first_day: a profile that is not a dict is ignored, oldest known day is used",
      _fd["first_day"] == "2022-02-02")

_fd = {"devices": [], "days": []}
_q_set_first_day(_fd, None)
check("first_day: nothing to go on -> stays unset, no crash",
      not _fd.get("first_day"))
cfg.SYNC_AUTO_FALLBACK = _fallback_saved

# record_attempt on an existing entry: device info and field downgrades
with _isolated_log_env("record_attempt"):
    _ra = {"days": []}
    _day = date(2024, 6, 1)
    quality.record_attempt(_ra, _day, "high", "first", written=True, source="api")
    quality.record_attempt(_ra, _day, "high", "second", written=True, source="api",
                           device_id="123", device_name="Fenix",
                           fields={"hrv": "high", "_downgrade_reasons": {"hrv": "array"}})
    _e = _ra["days"][0]
    check("record_attempt: update sets device_id and device_name",
          _e["device_id"] == "123" and _e["device_name"] == "Fenix")
    check("record_attempt: update stores field_downgrades and keeps fields clean",
          _e["field_downgrades"] == {"hrv": "array"}
          and "_downgrade_reasons" not in _e["fields"])
    quality.record_attempt(_ra, _day, "high", "third", written=True, source="api",
                           device_id="123", device_name=None,
                           fields={"hrv": "high"})
    _e = _ra["days"][0]
    check("record_attempt: clean re-assessment drops the stale field_downgrades",
          "field_downgrades" not in _e)
    check("record_attempt: device_name None becomes an empty string",
          _e["device_name"] == "")

# set_unknown_device_name
_sd = {"days": [{"date": "2024-01-01", "device_id": None},
                {"date": "2024-01-02", "device_id": "7", "device_name": "Keep"},
                {"date": "2024-01-03", "device_id": None, "device_name": "old"}]}
_n = quality.set_unknown_device_name(_sd, "  Fenix 7  ")
check("set_unknown_device_name: returns the number of updated entries", _n == 2)
check("set_unknown_device_name: name is stripped and set on entries without device_id",
      _sd["days"][0]["device_name"] == "Fenix 7" and _sd["days"][2]["device_name"] == "Fenix 7")
check("set_unknown_device_name: entries with a device_id are untouched",
      _sd["days"][1]["device_name"] == "Keep")

# backfill-failure counters for a day that is not in the log
_bf = {"days": [{"date": "2024-01-01"}]}
check("record_field_backfill_failure: unknown day -> 0",
      quality.record_field_backfill_failure(_bf, date(2030, 1, 1), "steps") == 0)
check("record_field_backfill_failures: unknown day -> {}",
      quality.record_field_backfill_failures(_bf, date(2030, 1, 1), ["steps", "hrv"]) == {})


# ── 4e. assess_quality_fields, get_archive_stats, scan, field hash ────────────
section("4e. garmin_quality — assess, archive stats, scan, field hash")

# quality 'standard' from user_summary alone
check("assess_quality: user_summary without steps/resting HR -> standard",
      quality.assess_quality({"user_summary": {"somethingElse": 1}}) == "standard")

# per-field labels for the branches that were never exercised
_ASSESS_CASES = [
    ("heart_rates low",        {"heart_rates": {"other": 1}},                              "heart_rates", "low"),
    ("sleep low",              {"sleep": {"other": 1}},                                    "sleep", "low"),
    ("hrv medium",             {"hrv": {"hrvSummary": {"lastNightAvg": 50}}},              "hrv", "medium"),
    ("hrv low",                {"hrv": {"other": 1}},                                      "hrv", "low"),
    ("spo2 high",              {"spo2": {"spO2HourlyAverages": [[1740787200000, 97],
                                                                  [1740790800000, 96]]}}, "spo2", "high"),
    ("spo2 low",               {"spo2": {"other": 1}},                                     "spo2", "low"),
    ("stats low",              {"stats": {"other": 1}},                                    "stats", "low"),
    ("steps low (empty list)", {"steps": []},                                              "steps", "low"),
    ("body_battery low",       {"body_battery": {"other": 1}},                             "body_battery", "low"),
    ("respiration low",        {"respiration": {"other": 1}},                              "respiration", "low"),
    ("training_status low",    {"training_status": {"other": 1}},                          "training_status", "low"),
    ("training_readiness low", {"training_readiness": {"other": 1}},                       "training_readiness", "low"),
    ("max_metrics low",        {"max_metrics": {"other": 1}},                              "max_metrics", "low"),
]
for _label, _raw, _field, _want in _ASSESS_CASES:
    _got = quality.assess_quality_fields(_raw)[_field]
    check(f"assess_quality_fields: {_label} -> {_want}", _got == _want)

# get_archive_stats
with _isolated_log_env("stats"):
    _p = _TMPDIR / "iso_stats" / "stats_input.json"
    _p.write_text(json.dumps({"x": 1}), encoding="utf-8")
    s = quality.get_archive_stats(quality_log_path=_p)
    check("get_archive_stats: file without 'days' -> empty stats",
          s["total"] == 0 and s["date_min"] is None)
    s = quality.get_archive_stats(quality_log_path=_TMPDIR / "iso_stats" / "missing.json")
    check("get_archive_stats: missing file -> empty stats, no crash",
          s["total"] == 0 and s["coverage_pct"] is None)
    with patch("quality._io._load_quality_log", side_effect=RuntimeError("boom")):
        s = quality.get_archive_stats()
    check("get_archive_stats: default path with a failing loader -> empty stats, no crash",
          s["total"] == 0 and s["coverage_pct"] is None)

    _put_log({"first_day": None, "devices": [],
              "days": [{"date": "2024-01-01", "quality": "high", "source": "api"},
                       {"date": "2024-01-02", "quality": "failed", "source": "bulk"}]})
    s = quality.get_archive_stats()
    check("get_archive_stats: default path reads the quality log",
          s["total"] == 2 and s["high"] == 1 and s["failed"] == 1
          and s["last_api"] == "2024-01-01" and s["last_bulk"] == "2024-01-02")

    _p.write_text(json.dumps({"first_day": "2024-01-01", "days": [
        {"date": "2024-01-10", "quality": "high"},
        {"date": "2024-01-12", "quality": "high"}]}), encoding="utf-8")
    s = quality.get_archive_stats(quality_log_path=_p)
    check("get_archive_stats: an earlier first_day widens the range (missing days counted)",
          s["missing"] == 10 and s["coverage_pct"] == 17)

    _p.write_text(json.dumps({"days": [
        {"date": "2024-01-02", "quality": "high"},
        {"date": "not-a-date", "quality": "high"}]}), encoding="utf-8")
    s = quality.get_archive_stats(quality_log_path=_p)
    check("get_archive_stats: an invalid date -> no crash, coverage left empty",
          s["total"] == 2 and s["coverage_pct"] is None and s["missing"] is None)

# get_low_quality_dates / _backfill_quality_log
with _isolated_log_env("scan"):
    check("get_low_quality_dates: missing folder -> {}",
          quality.get_low_quality_dates(cfg.RAW_DIR) == {})
    check("_backfill_quality_log: missing raw folder -> 0",
          _q_backfill({"days": []}) == 0)

    cfg.RAW_DIR.mkdir(parents=True)
    (cfg.RAW_DIR / "garmin_raw_2024-07-02.json").write_text("{}", encoding="utf-8")        # failed content, known
    (cfg.RAW_DIR / "garmin_raw_2024-07-03.json").write_text("{bad json", encoding="utf-8")  # corrupt
    (cfg.RAW_DIR / "garmin_raw_2024-07-04.json").write_text("{}", encoding="utf-8")        # failed content, new
    (cfg.RAW_DIR / "garmin_raw_2024-07-05.json").write_text(
        json.dumps({"stats": {"totalSteps": 1000}}), encoding="utf-8")                     # standard, new
    (cfg.RAW_DIR / "garmin_raw_not-a-date.json").write_text("{}", encoding="utf-8")        # bad name
    found = quality.get_low_quality_dates(cfg.RAW_DIR, known_dates={date(2024, 7, 2)})
    check("get_low_quality_dates: only the new failed file is reported",
          found == {date(2024, 7, 4): "failed"})

    _bd = {"days": [{"date": "2024-07-02", "quality": "failed"}]}
    _added = _q_backfill(_bd)
    check("_backfill_quality_log: new days added, known/bad-name/corrupt files skipped",
          _added == 2 and sorted(e["date"] for e in _bd["days"])
          == ["2024-07-02", "2024-07-04", "2024-07-05"])
    check("_backfill_quality_log: added entries are marked source 'legacy'",
          all(e["source"] == "legacy" for e in _bd["days"] if e["date"] != "2024-07-02"))

# field hash for values json cannot serialise
_circular = []
_circular.append(_circular)
_hash_a = _q_hash_field({(1, 2): "tuple key"})
check("_hash_field: unserialisable value (tuple key) -> 64-char hex digest, deterministic",
      len(_hash_a) == 64 and _hash_a == _q_hash_field({(1, 2): "tuple key"}))
check("_hash_field: circular value -> 64-char hex digest, no crash",
      len(_q_hash_field(_circular)) == 64)


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
#  4m. garmin_quality._assess — every field and every boundary (v1.7.4.0.3)
#      Table of raw inputs and the COMPLETE expected result of
#      assess_quality_fields() (all 14 fields plus _downgrade_reasons when
#      expected). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4m. garmin_quality._assess — field assessment table")

_KF4M = quality.KNOWN_FIELDS
_DG4M = "_downgrade_reasons"
_PL4M = "array present, not parseable as [ts,val]"
_BB4M = "array present, not parseable as [ts,status,val]"


def _exp4m(over=None, dg=None):
    e = {f: "failed" for f in _KF4M}
    e.update(over or {})
    if dg:
        e[_DG4M] = dg
    return e


_CASES4M = []          # (name, raw, expected)


def _case4m(name, raw, over=None, dg=None):
    _CASES4M.append((name, raw, _exp4m(over, dg)))


# -- the four intraday fields share one shape: array / aggregate / dict / nothing ---------------------------------------
for _f, _arr, _agg in (("heart_rates", "heartRateValues", "restingHeartRate"),
                       ("stress", "stressValuesArray", "averageStressLevel"),
                       ("spo2", "spO2HourlyAverages", "averageSpO2"),
                       ("respiration", "respirationValuesArray", "avgWakingRespirationValue")):
    _case4m(f"{_f}: one parseable value -> high", {_f: {_arr: [[0, 5]]}}, {_f: "high"})
    _case4m(f"{_f}: two parseable values -> high", {_f: {_arr: [[0, 5], [1, 6]]}}, {_f: "high"})
    _case4m(f"{_f}: array and aggregate -> high", {_f: {_arr: [[0, 5]], _agg: 7}}, {_f: "high"})
    _case4m(f"{_f}: empty array + aggregate -> medium, no downgrade reason",
            {_f: {_arr: [], _agg: 5}}, {_f: "medium"})
    _case4m(f"{_f}: empty array alone -> low, no downgrade reason", {_f: {_arr: []}}, {_f: "low"})
    _case4m(f"{_f}: unparseable array + aggregate -> medium with downgrade reason",
            {_f: {_arr: ["x"], _agg: 5}}, {_f: "medium"}, {_f: _PL4M})
    _case4m(f"{_f}: unparseable array alone -> low with downgrade reason",
            {_f: {_arr: [[0]]}}, {_f: "low"}, {_f: _PL4M})
    _case4m(f"{_f}: aggregate only -> medium", {_f: {_agg: 5}}, {_f: "medium"})
    _case4m(f"{_f}: aggregate 0 counts as present -> medium", {_f: {_agg: 0}}, {_f: "medium"})
    _case4m(f"{_f}: other keys only -> low", {_f: {"x": 1}}, {_f: "low"})
    _case4m(f"{_f}: empty dict -> failed", {_f: {}}, {})
    _case4m(f"{_f}: text instead of a dict -> failed", {_f: "abc"}, {})
    _case4m(f"{_f}: list instead of a dict -> failed", {_f: [1]}, {})
    _case4m(f"{_f}: absent -> failed", {}, {})

# -- sleep, hrv ------------------------------------------------------------------------------------------------------------
_case4m("sleep: one level -> high", {"sleep": {"sleepLevels": [{"x": 1}]}}, {"sleep": "high"})
_case4m("sleep: empty levels alone -> low", {"sleep": {"sleepLevels": []}}, {"sleep": "low"})
_case4m("sleep: empty levels + total sleep time -> medium",
        {"sleep": {"sleepLevels": [], "dailySleepDTO": {"sleepTimeSeconds": 28800}}}, {"sleep": "medium"})
_case4m("sleep: sleep time 0 counts as present -> medium",
        {"sleep": {"dailySleepDTO": {"sleepTimeSeconds": 0}}}, {"sleep": "medium"})
_case4m("sleep: levels beat the aggregate -> high",
        {"sleep": {"sleepLevels": [1], "dailySleepDTO": {"sleepTimeSeconds": 1}}}, {"sleep": "high"})
_case4m("sleep: other keys only -> low", {"sleep": {"x": 1}}, {"sleep": "low"})
_case4m("sleep: empty dict -> failed", {"sleep": {}}, {})
_case4m("sleep: text -> failed", {"sleep": "abc"}, {})
_case4m("sleep: list -> failed", {"sleep": [1]}, {})
_case4m("hrv: last night average -> medium", {"hrv": {"hrvSummary": {"lastNightAvg": 47}}}, {"hrv": "medium"})
_case4m("hrv: last night average 0 -> medium", {"hrv": {"hrvSummary": {"lastNightAvg": 0}}}, {"hrv": "medium"})
_case4m("hrv: empty summary -> low", {"hrv": {"hrvSummary": {}}}, {"hrv": "low"})
_case4m("hrv: other keys only -> low", {"hrv": {"x": 1}}, {"hrv": "low"})
_case4m("hrv: empty dict -> failed", {"hrv": {}}, {})
_case4m("hrv: text -> failed", {"hrv": "abc"}, {})
_case4m("hrv: list -> failed", {"hrv": [1]}, {})

# -- stats and steps ----------------------------------------------------------------------------------------------------------
_case4m("stats: total steps in stats -> stats medium, steps medium",
        {"stats": {"totalSteps": 100}}, {"stats": "medium", "steps": "medium"})
_case4m("stats: total steps in user_summary -> stats medium, steps medium",
        {"user_summary": {"totalSteps": 100}}, {"stats": "medium", "steps": "medium"})
_case4m("stats: 0 steps counts as present", {"stats": {"totalSteps": 0}}, {"stats": "medium", "steps": "medium"})
_case4m("stats: other keys in stats -> low", {"stats": {"x": 1}}, {"stats": "low"})
_case4m("stats: other keys in user_summary -> low", {"user_summary": {"x": 1}}, {"stats": "low"})
_case4m("stats: text in stats -> failed", {"stats": "abc"}, {})
_case4m("stats: text in user_summary -> failed", {"user_summary": "abc"}, {})
_case4m("stats: text in both -> failed", {"stats": "abc", "user_summary": "def"}, {})
_case4m("stats: empty stats + filled user_summary -> low", {"stats": {}, "user_summary": {"x": 1}}, {"stats": "low"})
_case4m("stats: filled stats + empty user_summary -> low", {"stats": {"x": 1}, "user_summary": {}}, {"stats": "low"})
_case4m("stats: text stats + filled user_summary -> low", {"stats": "abc", "user_summary": {"x": 1}}, {"stats": "low"})
_case4m("stats: filled stats + text user_summary -> low", {"stats": {"x": 1}, "user_summary": "def"}, {"stats": "low"})
_case4m("steps: one intraday bin -> high", {"steps": [{"a": 1}]}, {"steps": "high"})
_case4m("steps: two bins -> high", {"steps": [1, 2]}, {"steps": "high"})
_case4m("steps: intraday beats the aggregate -> high",
        {"steps": [1], "stats": {"totalSteps": 5}}, {"steps": "high", "stats": "medium"})
_case4m("steps: empty list alone -> low", {"steps": []}, {"steps": "low"})
_case4m("steps: empty list + total steps -> medium",
        {"steps": [], "stats": {"totalSteps": 5}}, {"steps": "medium", "stats": "medium"})
_case4m("steps: text -> failed", {"steps": "abc"}, {})
_case4m("steps: dict -> failed", {"steps": {"a": 1}}, {})

# -- body battery: own array, stress array, parseable as [ts, status, value] ---------------------------------------------------
_case4m("body_battery: one triplet -> high",
        {"body_battery": {"bodyBatteryValuesArray": [[0, "M", 50]]}}, {"body_battery": "high"})
_case4m("body_battery: two triplets -> high",
        {"body_battery": {"bodyBatteryValuesArray": [[0, "M", 50], [1, "M", 60]]}}, {"body_battery": "high"})
_case4m("body_battery: array inside the stress block -> high (stress itself stays low)",
        {"stress": {"bodyBatteryValuesArray": [[0, "M", 50]]}}, {"stress": "low", "body_battery": "high"})
_case4m("body_battery: two triplets inside the stress block -> high",
        {"stress": {"bodyBatteryValuesArray": [[0, "M", 50], [1, "M", 60]]}},
        {"stress": "low", "body_battery": "high"})
_case4m("body_battery: empty own array -> low, no downgrade reason",
        {"body_battery": {"bodyBatteryValuesArray": []}}, {"body_battery": "low"})
_case4m("body_battery: empty array inside the stress block -> failed, no downgrade reason",
        {"stress": {"bodyBatteryValuesArray": []}}, {"stress": "low"})
_case4m("body_battery: pairs instead of triplets -> low with downgrade reason",
        {"body_battery": {"bodyBatteryValuesArray": [[0, 1]]}}, {"body_battery": "low"}, {"body_battery": _BB4M})
_case4m("body_battery: text as value -> low with downgrade reason",
        {"body_battery": {"bodyBatteryValuesArray": [[0, "M", "x"]]}}, {"body_battery": "low"},
        {"body_battery": _BB4M})
_case4m("body_battery: unparseable array inside the stress block -> failed with downgrade reason",
        {"stress": {"bodyBatteryValuesArray": [[0, "M", "x"]]}}, {"stress": "low"}, {"body_battery": _BB4M})
_case4m("body_battery: parseable own array beats an unparseable stress array -> high",
        {"body_battery": {"bodyBatteryValuesArray": [[0, "M", 50]]},
         "stress": {"bodyBatteryValuesArray": [[0, 1]]}},
        {"stress": "low", "body_battery": "high"}, {})
_case4m("body_battery: parseable stress array beats an unparseable own array -> high",
        {"body_battery": {"bodyBatteryValuesArray": [[0, 1]]},
         "stress": {"bodyBatteryValuesArray": [[0, "M", 50]]}},
        {"stress": "low", "body_battery": "high"})
_case4m("body_battery: other keys only -> low", {"body_battery": {"x": 1}}, {"body_battery": "low"})
_case4m("body_battery: empty dict -> failed", {"body_battery": {}}, {})
_case4m("body_battery: text -> failed", {"body_battery": "abc"}, {})

# -- activities, training status, readiness, race predictions, max metrics -----------------------------------------------------
_case4m("activities: one -> high", {"activities": [{"a": 1}]}, {"activities": "high"})
_case4m("activities: empty list -> failed", {"activities": []}, {})
_case4m("activities: text -> failed", {"activities": "abc"}, {})
_case4m("activities: dict -> failed", {"activities": {"a": 1}}, {})
_case4m("training_status: latest status -> medium", {"training_status": {"latestTrainingStatus": 7}},
        {"training_status": "medium"})
_case4m("training_status: plain status -> medium", {"training_status": {"trainingStatus": 4}},
        {"training_status": "medium"})
_case4m("training_status: other keys only -> low", {"training_status": {"x": 1}}, {"training_status": "low"})
_case4m("training_status: empty dict -> failed", {"training_status": {}}, {})
_case4m("training_status: text -> failed", {"training_status": "abc"}, {})
_case4m("training_status: list -> failed", {"training_status": [1]}, {})
_case4m("training_readiness: score -> medium", {"training_readiness": {"score": 70}},
        {"training_readiness": "medium"})
_case4m("training_readiness: alternative score 0 -> medium", {"training_readiness": {"trainingReadinessScore": 0}},
        {"training_readiness": "medium"})
_case4m("training_readiness: other keys only -> low", {"training_readiness": {"x": 1}},
        {"training_readiness": "low"})
_case4m("training_readiness: empty dict -> failed", {"training_readiness": {}}, {})
_case4m("training_readiness: text -> failed", {"training_readiness": "abc"}, {})
_case4m("training_readiness: list -> failed", {"training_readiness": [1]}, {})
_case4m("race_predictions: filled -> medium", {"race_predictions": {"x": 1}}, {"race_predictions": "medium"})
_case4m("race_predictions: empty dict -> failed", {"race_predictions": {}}, {})
_case4m("race_predictions: text -> failed", {"race_predictions": "abc"}, {})
_case4m("race_predictions: list -> failed", {"race_predictions": [1]}, {})
_case4m("max_metrics: precise value -> medium", {"max_metrics": {"vo2MaxPreciseValue": 50.1}},
        {"max_metrics": "medium"})
_case4m("max_metrics: generic precise value -> medium", {"max_metrics": {"generic": {"vo2MaxPreciseValue": 51}}},
        {"max_metrics": "medium"})
_case4m("max_metrics: other keys only -> low", {"max_metrics": {"x": 1}}, {"max_metrics": "low"})
_case4m("max_metrics: empty dict -> failed", {"max_metrics": {}}, {})
_case4m("max_metrics: text -> failed", {"max_metrics": "abc"}, {})
_case4m("max_metrics: list -> failed", {"max_metrics": [1]}, {})

_bad4m = []
for _name4m, _raw4m, _exp_4m in _CASES4M:
    _got4m = quality.assess_quality_fields(_raw4m)
    _ok4m = _got4m == _exp_4m
    check(f"4m fields — {_name4m}", _ok4m)
    if not _ok4m:
        _bad4m.append((_name4m, _got4m, _exp_4m))
check("4m fields: the table has one expected entry per known field in every case",
      all(set(e) - {_DG4M} == set(_KF4M) for _, _, e in _CASES4M) and len(_CASES4M) > 100)

# -- assess_quality: the top-level label ---------------------------------------------------------------------------------------------
for _name, _raw, _label in [
    ("one heart-rate value", {"heart_rates": {"heartRateValues": [[0, 60]]}}, "high"),
    ("two heart-rate values", {"heart_rates": {"heartRateValues": [[0, 60], [1, 61]]}}, "high"),
    ("empty heart-rate array alone", {"heart_rates": {"heartRateValues": []}}, "failed"),
    ("empty heart-rate array + steps", {"heart_rates": {"heartRateValues": []}, "stats": {"totalSteps": 1}},
     "standard"),
    ("one stress value", {"stress": {"stressValuesArray": [[0, 10]]}}, "high"),
    ("two stress values", {"stress": {"stressValuesArray": [[0, 10], [1, 11]]}}, "high"),
    ("empty stress array alone", {"stress": {"stressValuesArray": []}}, "failed"),
    ("text as stress", {"stress": "abc"}, "failed"),
    ("steps only in stats", {"stats": {"totalSteps": 5}}, "standard"),
    ("steps only in user_summary", {"user_summary": {"totalSteps": 5}}, "standard"),
    ("resting heart rate only in stats", {"stats": {"restingHeartRate": 50}}, "standard"),
    ("resting heart rate only in user_summary", {"user_summary": {"restingHeartRate": 50}}, "standard"),
    ("steps 0 counts as present", {"stats": {"totalSteps": 0}}, "standard"),
    ("other stats keys only", {"stats": {"x": 1}}, "standard"),
    ("other user_summary keys only", {"user_summary": {"x": 1}}, "standard"),
    ("nothing", {}, "failed"),
    ("text stats and user_summary", {"stats": "abc", "user_summary": "def"}, "failed"),
]:
    check(f"4m assess_quality — {_name} -> {_label}", quality.assess_quality(_raw) == _label)

# ══════════════════════════════════════════════════════════════════════════════
#  4n. garmin_quality._io — checksums, load migrations, device table, save and
#      defective-log formats (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4n. garmin_quality._io — checksums, migrations, device table, saves")
import hashlib as _hl4n
import zipfile as _zf4n
import quality._io as _qio
import garmin_backup as _gb4n


class _QLog:
    """Stands in for _qio.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)


def _qlogged(fn, *args, **kwargs):
    real, rec = _qio.log, _QLog()
    _qio.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        _qio.log = real


def _nl(b):
    return b.replace(b"\r\n", b"\n")        # write_text/open('w') use CRLF on Windows


# -- 1. checksums: exact SHA-256 over the exact JSON text ---------------------------------------------------------------------
_days4n = [{"date": "2024-05-02", "quality": "high", "source": "Grüße", "write": True, "x": "ignored"},
           {"date": "2024-05-01", "quality": "low", "source": "api", "write": None}]
_txt4n = ('[{"date":"2024-05-01","quality":"low","source":"api","write":null},'
          '{"date":"2024-05-02","quality":"high","source":"Grüße","write":true}]')
check("4n checksum: SHA-256 of the sorted core fields as compact UTF-8 JSON",
      quality._compute_checksum({"days": _days4n}) == _hl4n.sha256(_txt4n.encode("utf-8")).hexdigest())
_leg4n = [{"date": "ä-1", "write": True, "quality": "high"}, {"date": "b-2", "write": None}]
_ltxt4n = '[{"date":"b-2","write":null},{"date":"ä-1","write":true}]'
check("4n checksum (legacy): SHA-256 over date and write only, UTF-8",
      quality._compute_checksum_legacy({"days": _leg4n}) == _hl4n.sha256(_ltxt4n.encode("utf-8")).hexdigest())

# -- 2. load: old schema and malformed files ------------------------------------------------------------------------------------
with _isolated_log_env("q4n_schema"):
    _put_log({"failed": [{"date": "2024-01-01"}], "days": [{"date": "2024-02-02"}]})
    check("4n load: a file with both 'failed' and 'days' keeps its 'days'",
          [e["date"] for e in quality._load_quality_log()["days"]] == ["2024-02-02"])
    _put_log({"failed": [{"date": "2024-01-01", "category": "error"}]})
    _l = quality._load_quality_log()
    check("4n load: the old 'failed' list becomes 'days'",
          [e["date"] for e in _l["days"]] == ["2024-01-01"] and _l["days"][0]["quality"] == "failed")
    _empty4n = {"first_day": None, "devices": [], "days": []}
    for _bad, _what in (({"days": "abc"}, "'days' is text"), ({"days": {"a": 1}}, "'days' is a dict"),
                        ({"x": 1}, "no 'days' at all")):
        _put_log(_bad)
        check(f"4n load: {_what} -> exactly the empty structure", quality._load_quality_log() == _empty4n)

# -- 3. load: entry migrations --------------------------------------------------------------------------------------------------------
_TODAY4N = date.today().isoformat()
with _isolated_log_env("q4n_entries"):
    _put_log({"days": [
        {"date": "2024-03-01", "category": "error"},
        {"date": "2024-03-02", "category": "incomplete"},
        {"date": "2024-03-03", "category": "aaa"},
        {"date": "2024-03-04", "category": "error", "quality": "high"},
        {"date": "2024-03-05"},
        {"date": "2024-04-01", "last_attempt": "2024-04-09"},
        {"date": "2024-04-02", "last_attempt": None},
        {"date": "2024-04-03", "quality": "standard", "attempts": 3},
        {"date": "2024-04-04", "quality": "low", "attempts": 3},
        {"date": "2024-04-05", "quality": "high", "attempts": 2},
    ]})
    _e = {x["date"]: x for x in quality._load_quality_log()["days"]}
    check("4n load: category 'error' -> failed, 'incomplete' and any other value -> low",
          [_e[f"2024-03-0{n}"]["quality"] for n in (1, 2, 3)] == ["failed", "low", "low"])
    check("4n load: an entry with both category and quality keeps its quality and its category",
          _e["2024-03-04"]["quality"] == "high" and _e["2024-03-04"]["category"] == "error")
    check("4n load: an entry with neither is filled with defaults, no crash",
          _e["2024-03-05"]["recheck"] is True and _e["2024-03-05"]["source"] == "legacy"
          and _e["2024-03-05"]["write"] is None and _e["2024-03-05"]["fields"] == {}
          and _e["2024-03-05"]["attempts"] == 0 and _e["2024-03-05"]["last_attempt"] is None
          and _e["2024-03-05"]["device_id"] is None and _e["2024-03-05"]["device_name"] == "")
    check("4n load: last_checked comes from last_attempt, else today",
          _e["2024-04-01"]["last_checked"] == "2024-04-09" and _e["2024-04-02"]["last_checked"] == _TODAY4N
          and _e["2024-03-05"]["last_checked"] == _TODAY4N)
    check("4n load: attempts are reset to 0 for 'low' only, not for 'standard' or 'high'",
          [_e[f"2024-04-0{n}"]["attempts"] for n in (3, 4, 5)] == [3, 0, 2])

# -- first_day and device dates ----------------------------------------------------------------------------------------------------------
with _isolated_log_env("q4n_firstday"):
    _put_log({"first_day": 1710489600, "devices": [
        {"first_used": 1710489600, "last_used": "2024-01-02"}, {"first_used": "unknown", "last_used": None}],
        "days": []})
    _l, _c = _qlogged(quality._load_quality_log)
    check("4n load: first_day as Unix time becomes a date and the migration is logged",
          _l["first_day"] == "2024-03-15"
          and ("info", "  Migrating first_day: 1710489600 -> 2024-03-15") in _c)
    check("4n load: device dates as Unix time become dates, readable and 'unknown' ones stay",
          _l["devices"][0] == {"first_used": "2024-03-15", "last_used": "2024-01-02"}
          and _l["devices"][1] == {"first_used": "unknown", "last_used": None})
    _put_log({"first_day": "2024-03-15", "devices": [], "days": []})
    _l, _c = _qlogged(quality._load_quality_log)
    check("4n load: first_day that is already a date is left alone and nothing is logged",
          _l["first_day"] == "2024-03-15" and not any("Migrating first_day" in m for _, m in _c))

# -- 4. migration from failed_days.json ---------------------------------------------------------------------------------------------------------
with _isolated_log_env("q4n_oldfile"):
    _old = cfg.LOG_DIR / "failed_days.json"
    _old.write_text(json.dumps({"failed": [{"date": "2024-05-05", "category": "error"}]}), encoding="utf-8")
    with patch.object(_qio, "_save_quality_log", wraps=_qio._save_quality_log) as _spy:
        _l = quality._load_quality_log()
    check("4n migration: failed_days.json is taken over, the old file removed, saved without backup",
          [e["date"] for e in _l["days"]] == ["2024-05-05"] and not _old.exists()
          and cfg.QUALITY_LOG_FILE.exists()
          and [c.kwargs for c in _spy.call_args_list] == [{"skip_backup": True}])
with _isolated_log_env("q4n_oldfile_cs"):
    _old = cfg.LOG_DIR / "failed_days.json"
    _old.write_text(json.dumps({"failed": [{"date": "2024-05-05", "quality": "high", "source": "api",
                                            "write": True}], "_checksum": "z" * 64}), encoding="utf-8")
    with patch.object(_qio, "_save_quality_log", new=lambda *a, **k: None):     # keep the stale checksum
        _l = quality._load_quality_log()
    check("4n migration: the checksum of a failed_days.json file is not verified",
          _l["integrity_warnings"] == [])

# -- 5. checksum comparison ------------------------------------------------------------------------------------------------------------------------
_D6 = [{"date": "2024-06-01", "quality": "high", "source": "api", "write": True}]
with _isolated_log_env("q4n_checksum"):
    _put_log({"days": _D6, "_checksum": quality._compute_checksum({"days": _D6})})
    check("4n integrity: the current checksum -> no warning", quality._load_quality_log()["integrity_warnings"] == [])
    _put_log({"days": _D6, "_checksum": quality._compute_checksum_legacy({"days": _D6})})
    _l, _c = _qlogged(quality._load_quality_log)
    check("4n integrity: a legacy checksum is an upgrade, not a warning",
          _l["integrity_warnings"] == [] and any("algorithm upgraded" in m for _, m in _c))
    for _bogus in ("z" * 64, "0" * 64):
        _put_log({"days": _D6, "_checksum": _bogus})
        _l, _c = _qlogged(quality._load_quality_log)
        check(f"4n integrity: a checksum that is neither current nor legacy ({_bogus[:1]}...) -> mismatch warning",
              _l["integrity_warnings"] == ["log mismatch 2024"]
              and any(lv == "warning" and "checksum mismatch — affected years: 2024" in m for lv, m in _c))

# -- 6. save_device_table ------------------------------------------------------------------------------------------------------------------------------
_hi = "".join(["hi", "gh"])
_st = "".join(["stand", "ard"])
_DT4N = {"days": [
    {"date": "2024-03-01", "device_id": "D1", "device_name": "Größe", "quality": "high"},
    {"date": "2024-03-02", "device_id": "D1", "quality": _hi},
    {"date": "2024-03-03", "device_id": "D1", "quality": "standard"},
    {"date": "2024-03-04", "device_id": "D1", "quality": "standard"},
    {"date": "2024-03-09", "device_id": "D1", "quality": _st},
    {"date": "2024-03-05", "device_id": "D1", "quality": "failed"},
    {"date": "2024-03-06", "device_id": "D1", "quality": "zzz"},
    {"date": "2024-03-07", "device_id": "D1", "quality": "low"},
    {"date": "2024-03-08", "device_id": "D1"},
    {"date": "2024-04-01", "device_id": "D2", "quality": "high"},
    {"date": "2024-03-20", "device_id": "D2", "quality": "high"},
    {"date": "2024-03-21", "device_id": "D2", "quality": "standard"},
    {"date": "2024-02-01", "device_name": "Alt", "quality": "high"},
    {"date": "2024-02-02", "device_id": "", "device_name": "Alt", "quality": "high"},
    {"date": "2024-02-03", "device_id": None, "quality": _hi},
    {"date": "2024-02-04", "quality": "standard"},
    {"date": "2024-02-05", "quality": _st},
    {"date": "2024-02-06", "quality": "failed"},
    {"quality": "zzz"},                                        # unknown label, no device: counted nowhere
    {"quality": "high", "device_id": "D2"},                    # no date: counted, no date range
]}
with _isolated_log_env("q4n_devtable") as _b:
    _r, _c = _qlogged(quality.save_device_table, _DT4N)
    _rows = json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))
    check("4n device table: rows sorted by newest end date, unknown device after the named ones, total last",
          [r["device_id"] for r in _rows] == ["D2", "D1", "__unknown__", "__total__"])
    check("4n device table: named devices count high and standard days only; total = high + standard",
          _rows[0] == {"device_id": "D2", "name": "D2", "date_from": "2024-03-20", "date_to": "2024-04-01",
                       "days_high": 3, "days_standard": 1, "days_total": 4}
          and _rows[1] == {"device_id": "D1", "name": "Größe", "date_from": "2024-03-01",
                           "date_to": "2024-03-09", "days_high": 2, "days_standard": 3, "days_total": 5})
    check("4n device table: entries without a device id form the unknown row, a single name is shown",
          _rows[2] == {"device_id": "__unknown__", "name": "Alt", "date_from": "2024-02-01",
                       "date_to": "2024-02-06", "days_high": 3, "days_standard": 2, "days_total": 5})
    check("4n device table: the total row sums every row",
          _rows[3] == {"device_id": "__total__", "name": "Total", "date_from": None, "date_to": None,
                       "days_high": 8, "days_standard": 6, "days_total": 14})
    _txt = _nl(cfg.DEVICE_TABLE_FILE.read_bytes()).decode("utf-8")
    check("4n device table: file is 2-space indented UTF-8 (umlauts not escaped)",
          '\n  {\n    "device_id": "D2",\n    "name": "D2",' in _txt and '"name": "Größe"' in _txt
          and "\\u00f6" not in _txt)
    check("4n device table: log names the number of devices (without the total row)",
          ("info", "  device_table.json written (3 device(s))") in _c)
    _nested = _b / "a" / "b" / "device_table.json"
    with patch.object(cfg, "DEVICE_TABLE_FILE", _nested):
        quality.save_device_table({"days": []})
    check("4n device table: a target folder with missing parents is created", _nested.is_file())
    quality.save_device_table({"days": [{"date": "2024-01-01", "device_id": "X", "device_name": "N",
                                         "quality": "high"},
                                        {"date": "2024-01-02", "device_id": "X", "device_name": "",
                                         "quality": "standard"}]})
    check("4n device table: a later entry without a name keeps the name already known",
          json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))[0]["name"] == "N")
    quality.save_device_table({"days": [{"date": "2024-01-01", "device_id": "Y", "device_name": "",
                                         "quality": "high"}]})
    check("4n device table: a device that never had a name is listed under its id",
          json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))[0]["name"] == "Y")

# -- 7. _save_quality_log -------------------------------------------------------------------------------------------------------------------------------
with _isolated_log_env("q4n_save") as _b:
    with patch.object(_gb4n, "backup_quality_log") as _bk:
        quality._save_quality_log({"days": [{"date": "2024-07-01"}]})
        quality._save_quality_log({"days": [{"date": "2024-07-01"}]}, skip_backup=True)
    check("4n save: by default the backup is triggered, with skip_backup=True it is not",
          _bk.call_count == 1)
    _data = {"first_day": None, "devices": [], "days": [
        {"date": "2024-07-02", "quality": "high", "source": "Grüße", "write": True},
        {"date": "2024-07-01", "quality": "low", "source": "api", "write": None}]}
    quality._save_quality_log(_data, skip_backup=True)
    _expect = {"first_day": None, "devices": [], "days": [_data["days"][0], _data["days"][1]],
               "_checksum": quality._compute_checksum(_data)}
    check("4n save: days sorted by date, checksum stored, file is 2-space indented UTF-8",
          [e["date"] for e in _data["days"]] == ["2024-07-01", "2024-07-02"]
          and _nl(cfg.QUALITY_LOG_FILE.read_bytes())
          == json.dumps(_expect, ensure_ascii=False, indent=2).encode("utf-8"))
    _deep = _b / "a" / "b" / "log"
    with patch.object(cfg, "LOG_DIR", _deep), patch.object(cfg, "QUALITY_LOG_FILE", _deep / "quality_log.json"):
        quality._save_quality_log({"days": []}, skip_backup=True)
    check("4n save: a log folder with missing parents is created", (_deep / "quality_log.json").is_file())

# -- 8. _save_defective_log -----------------------------------------------------------------------------------------------------------------------------------
with _isolated_log_env("q4n_defective") as _b:
    _ar = _b / "a" / "b" / "autorestore"
    from datetime import datetime as _dt4n
    _zname = f"auto-restore-{_dt4n.now().strftime('%Y-%m-%d')}.zip"
    with patch.object(cfg, "AUTORESTORE_DIR", _ar):
        _qio._save_defective_log({"days": [{"date": "2024-08-01", "source": "Grüße"}]})
        check("4n defective log: file named auto-restore-<date>.zip in a folder with missing parents",
              (_ar / _zname).is_file())
        with _zf4n.ZipFile(_ar / _zname) as _z:
            check("4n defective log: one entry, 2-space indented UTF-8 (umlauts not escaped)",
                  _z.namelist() == ["quality_log_defective.json"]
                  and _z.read("quality_log_defective.json")
                  == json.dumps({"days": [{"date": "2024-08-01", "source": "Grüße"}]},
                                ensure_ascii=False, indent=2).encode("utf-8"))
        _qio._save_defective_log({"days": [{"date": "2024-08-02"}]})
        with _zf4n.ZipFile(_ar / _zname) as _z:
            check("4n defective log: a second save on the same day replaces the first (folder already exists)",
                  json.loads(_z.read("quality_log_defective.json"))["days"][0]["date"] == "2024-08-02")

# ══════════════════════════════════════════════════════════════════════════════
#  4o. garmin_quality._maint — rank table, upsert in every branch, backfill
#      counters, first_day detection (v1.7.4.0.3).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4o. garmin_quality._maint — upsert, downgrade guard, first_day")
import copy as _copy4o
import re as _re4o
from datetime import timedelta as _td4o
import quality._maint as _qm
import quality._io as _qio4o

_TODAY4O = date.today()
_NOW_RE4O = _re4o.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")


def _d4o(age):
    return _TODAY4O - _td4o(days=age)


class _MLog:
    """Stands in for _qm.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg))

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg))


def _mlogged(fn, *args, **kwargs):
    real, rec = _qm.log, _MLog()
    _qm.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        _qm.log = real


# -- 1. rank table and is_downgrade -----------------------------------------------------------------------------------------
check("4o QUALITY_RANK: exactly high 2, standard 1, failed 0", quality.QUALITY_RANK == {"high": 2, "standard": 1, "failed": 0})
_ID = [("high", "standard", False), ("high", "failed", False), ("standard", "high", True),
       ("failed", "high", True), ("failed", "standard", True), ("standard", "failed", False),
       ("high", "high", False), ("standard", "standard", False), ("failed", "failed", False),
       (None, "failed", False), (None, "standard", True), (None, "high", True), (None, None, False),
       ("failed", None, False), ("standard", None, False), ("high", None, False),
       ("zzz", "failed", False), ("zzz", "standard", True), ("zzz", "high", True),
       ("failed", "zzz", False), ("standard", "zzz", False), ("high", "zzz", False), ("zzz", "zzz", False)]
_bad = [(n, e, quality.is_downgrade(n, e)) for n, e, want in _ID if quality.is_downgrade(n, e) is not want]
check(f"4o is_downgrade: {len(_ID)} label pairs incl. None and unknown labels", _bad == [])

with patch.object(cfg, "INTRADAY_RETRY_WINDOW_DAYS", 7):
    # -- 2. a new entry, every branch ---------------------------------------------------------------------------------------
    def _new(q, age=3, **kw):
        data = {"days": []}
        quality._upsert_quality(data, _d4o(age), q, "r", **kw)
        return data["days"][0]

    _fl = _new("".join(["fai", "led"]))
    check("4o new entry (failed): attempts 1, recheck, last_attempt set, defaults filled",
          _fl["attempts"] == 1 and _fl["recheck"] is True and _NOW_RE4O.match(_fl["last_attempt"])
          and _fl["quality"] == "failed" and _fl["reason"] == "r" and _fl["write"] is None
          and _fl["source"] == "legacy" and _fl["last_checked"] == _TODAY4O.isoformat()
          and _fl["device_id"] is None and _fl["device_name"] == "" and _fl["date"] == _d4o(3).isoformat())
    for _age, _ph, _want in ((6, True, True), (7, True, False), (10, True, False), (3, False, False), (0, True, True)):
        _s = _new("".join(["stand", "ard"]), age=_age, prev_high=_ph)
        check(f"4o new entry (standard): age {_age}, window 7, prev_high {_ph} -> recheck {_want}",
              _s["recheck"] is _want and _s["attempts"] == 0 and _s["last_attempt"] is None)
    check("4o new entry (standard): prev_high defaults to False -> no recheck",
          _new("standard", age=3)["recheck"] is False)
    _h = _new("high", prev_high=True)
    check("4o new entry (high): no recheck, no attempts, no last_attempt",
          _h["recheck"] is False and _h["attempts"] == 0 and _h["last_attempt"] is None)
    for _odd in ("aaa", "zzz"):
        _o = _new(_odd, prev_high=True)
        check(f"4o new entry: unknown label {_odd!r} is treated like 'high' (no recheck, no attempts)",
              _o["recheck"] is False and _o["attempts"] == 0 and _o["last_attempt"] is None)

    # -- 3. an existing entry: the downgrade guard -------------------------------------------------------------------------------
    def _base(q="failed", **over):
        e = {"date": _d4o(3).isoformat(), "quality": q, "reason": "old", "write": True, "source": "api",
             "recheck": False, "attempts": 2, "last_checked": "2000-01-01", "last_attempt": None,
             "device_id": "D0", "device_name": "N0"}
        e.update(over)
        return {"days": [e]}

    for _ex, _nw in (("high", "standard"), ("standard", "failed"), ("standard", "zzz"), ("high", "zzz"),
                     ("high", "failed")):
        _data = _base(_ex)
        _before = _copy4o.deepcopy(_data)
        _r, _c = _mlogged(quality._upsert_quality, _data, _d4o(3), _nw, "new", written=False, source="bulk")
        check(f"4o guard: existing {_ex}, new {_nw} -> blocked, entry unchanged, logged",
              _data == _before and any(f"quality downgrade blocked ({_ex} → {_nw})" in m for _, m in _c))
    for _ex, _nw in (("failed", "high"), ("standard", "standard"), ("failed", "zzz"), ("zzz", "failed"),
                     ("standard", "high"), ("failed", "standard")):
        _data = _base(_ex)
        quality._upsert_quality(_data, _d4o(3), _nw, "new", written=True, source="bulk")
        check(f"4o guard: existing {_ex}, new {_nw} -> taken over",
              _data["days"][0]["quality"] == _nw and _data["days"][0]["reason"] == "new")
    _data = _base("failed")
    del _data["days"][0]["quality"]
    quality._upsert_quality(_data, _d4o(3), "failed", "new")
    check("4o guard: an existing entry without a quality counts as failed -> failed over it is taken over",
          _data["days"][0]["quality"] == "failed" and _data["days"][0]["attempts"] == 3)

    # the entry of THIS day is updated, not the first entry with a later date
    _data = {"days": [dict(_base("failed")["days"][0], date=_d4o(1).isoformat(), reason="later day"),
                      dict(_base("failed")["days"][0], date=_d4o(3).isoformat())]}
    quality._upsert_quality(_data, _d4o(3), "high", "target")
    check("4o update: only the entry of the given day changes, an entry with a later date stays untouched",
          _data["days"][1]["reason"] == "target" and _data["days"][1]["quality"] == "high"
          and _data["days"][0]["reason"] == "later day" and _data["days"][0]["quality"] == "failed")

    # -- 4. an existing entry: what an update changes -----------------------------------------------------------------------------
    _data = _base("failed", fields={"a": "low"}, field_downgrades={"a": "stale"},
                  backfilled_fields={"steps": "d1"}, validator_result="critical")
    _flds = {"a": "high"}
    quality._upsert_quality(_data, _d4o(3), "high", "r2", written=True, source="bulk", fields=_flds,
                            device_id="D9", device_name=None, backfilled_fields={"floors": "d2"},
                            validator_result={"status": "ok", "issues": [], "schema_version": "1.1"})
    _e = _data["days"][0]
    check("4o update (high): reason, write, source, last_checked, device, fields, markers, validator, recheck",
          _e["quality"] == "high" and _e["reason"] == "r2" and _e["write"] is True and _e["source"] == "bulk"
          and _e["last_checked"] == _TODAY4O.isoformat() and _e["device_id"] == "D9"
          and _e["device_name"] == "" and _e["fields"] == {"a": "high"} and "field_downgrades" not in _e
          and _e["backfilled_fields"] == {"steps": "d1", "floors": "d2"}
          and (_e["validator_result"], _e["validator_issues"], _e["validator_schema_version"]) == ("ok", [], "1.1")
          and _e["recheck"] is False and _NOW_RE4O.match(_e["last_attempt"]) and _e["attempts"] == 2)
    _data = _base("failed", fields={"a": "old"}, validator_result="critical", validator_issues=[1])
    _flds = {"a": "low", "_downgrade_reasons": {"a": "why"}}
    quality._upsert_quality(_data, _d4o(3), "high", "r")
    _e = _data["days"][0]
    check("4o update: without device, fields, backfill and validator the old values stay",
          _e["device_id"] == "D0" and _e["device_name"] == "N0" and _e["fields"] == {"a": "old"}
          and "backfilled_fields" not in _e and _e["validator_result"] == "critical"
          and _e["validator_issues"] == [1])
    quality._upsert_quality(_data, _d4o(3), "high", "r", fields=_flds)
    check("4o update: downgrade reasons are split off the fields and stored separately",
          _data["days"][0]["fields"] == {"a": "low"} and _data["days"][0]["field_downgrades"] == {"a": "why"}
          and "_downgrade_reasons" not in _flds)
    _data = _base("failed", device_name="N0")
    quality._upsert_quality(_data, _d4o(3), "high", "r", device_id="D9", device_name="Neu")
    check("4o update: a device id with a name stores both", _data["days"][0]["device_name"] == "Neu")
    # failed over failed
    _data = _base("failed")
    quality._upsert_quality(_data, _d4o(3), "".join(["fai", "led"]), "r")
    _e = _data["days"][0]
    check("4o update (failed): attempts +1, recheck, last_attempt set",
          _e["attempts"] == 3 and _e["recheck"] is True and _NOW_RE4O.match(_e["last_attempt"]))
    _data = _base("failed")
    del _data["days"][0]["attempts"]
    quality._upsert_quality(_data, _d4o(3), "failed", "r")
    check("4o update (failed): an entry without attempts counts from 1", _data["days"][0]["attempts"] == 1)
    for _age, _ph, _want in ((3, True, True), (7, True, False), (10, True, False), (3, False, False)):
        _data = _base("failed")
        quality._upsert_quality(_data, _d4o(_age), "".join(["stand", "ard"]), "r", prev_high=_ph) \
            if False else None
        _data = {"days": [dict(_base("failed")["days"][0], date=_d4o(_age).isoformat())]}
        quality._upsert_quality(_data, _d4o(_age), "".join(["stand", "ard"]), "r", prev_high=_ph)
        _e = _data["days"][0]
        check(f"4o update (standard): age {_age}, prev_high {_ph} -> recheck {_want}, last_attempt set",
              _e["recheck"] is _want and _NOW_RE4O.match(_e["last_attempt"]))
    _data = _base("failed")
    quality._upsert_quality(_data, _d4o(3), "standard", "r")
    check("4o update (standard): prev_high defaults to False", _data["days"][0]["recheck"] is False)
    for _odd in ("aaa", "zzz"):
        _data = _base("failed", recheck=True)
        quality._upsert_quality(_data, _d4o(3), _odd, "r", prev_high=True)
        _e = _data["days"][0]
        check(f"4o update: unknown label {_odd!r} behaves like 'high' (recheck off, last_attempt set)",
              _e["recheck"] is False and _NOW_RE4O.match(_e["last_attempt"]) and _e["attempts"] == 2)
    _data = _base("failed", recheck=True)
    quality._upsert_quality(_data, _d4o(3), "high", "r")
    check("4o update (high): recheck is switched off", _data["days"][0]["recheck"] is False)

    # -- 5. record_attempt: prev_high defaults to False --------------------------------------------------------------------------
    with patch.object(_qio4o, "_save_quality_log") as _sv:
        _data = {"days": []}
        quality.record_attempt(_data, _d4o(3), "standard", "r")
    check("4o record_attempt: prev_high defaults to False and the log is saved once",
          _data["days"][0]["recheck"] is False and _sv.call_count == 1)

# -- 6. record_field_backfill_failure(s) --------------------------------------------------------------------------------------------------
def _two_days():
    return {"days": [{"date": _d4o(2).isoformat()}, {"date": _d4o(5).isoformat()}]}


with patch.object(_qio4o, "_save_quality_log") as _sv:
    _data = _two_days()
    check("4o backfill failure: the right day is counted (not the first later one), 1 then 2",
          quality.record_field_backfill_failure(_data, _d4o(5), "steps") == 1
          and quality.record_field_backfill_failure(_data, _d4o(5), "steps") == 2
          and _data["days"][1]["field_backfill_attempts"] == {"steps": 2}
          and "field_backfill_attempts" not in _data["days"][0] and _sv.call_count == 2)
    _sv.reset_mock()
    check("4o backfill failure: a day that is not archived -> 0 and nothing is saved",
          quality.record_field_backfill_failure(_data, _d4o(9), "steps") == 0 and _sv.call_count == 0)
with patch.object(_qio4o, "_save_quality_log") as _sv:
    _data = _two_days()
    _res = quality.record_field_backfill_failures(_data, _d4o(5), ["steps", "floors"])
    check("4o backfill failures (batched): the right day, one count per field, one save",
          _res == {"steps": 1, "floors": 1} and _sv.call_count == 1
          and _data["days"][1]["field_backfill_attempts"] == {"steps": 1, "floors": 1}
          and "field_backfill_attempts" not in _data["days"][0])
    _res = quality.record_field_backfill_failures(_data, _d4o(5), ["steps"])
    check("4o backfill failures (batched): counts continue", _res == {"steps": 2} and _sv.call_count == 2)
    _sv.reset_mock()
    check("4o backfill failures (batched): a day that is not archived -> {} and nothing is saved",
          quality.record_field_backfill_failures(_data, _d4o(9), ["steps"]) == {} and _sv.call_count == 0)

# -- 7. _set_first_day ---------------------------------------------------------------------------------------------------------------------
class _Cl4o:
    def __init__(self, profile=None, boom=False):
        self.profile, self.boom, self.calls = profile, boom, 0

    def get_user_profile(self):
        self.calls += 1
        if self.boom:
            raise RuntimeError("offline")
        return self.profile


_PROFILE = {"userInfo": {"registrationDate": "2021-03-04T10:00:00.000"}}
with patch.object(cfg, "SYNC_AUTO_FALLBACK", ""):
    for _unk in ("unknown", "".join(["unk", "nown"])):
        _data = {"devices": [{"first_used": _unk}], "days": []}
        _r, _c = _mlogged(quality._set_first_day, _data, None)
        check(f"4o first_day: only 'unknown' device dates ({_unk!r}) are ignored -> not set, warning",
              not _data.get("first_day") and any(lv == "warning" and "Could not determine first_day" in m
                                                  for lv, m in _c))
    _cl = _Cl4o(_PROFILE)
    _data = {"devices": [{"first_used": "2024-01-05"}, {"first_used": "unknown"}, {"first_used": None}, {}],
             "days": []}
    quality._set_first_day(_data, _cl)
    check("4o first_day: the earliest known device date wins and the account is not asked",
          _data["first_day"] == "2024-01-05" and _cl.calls == 0)
    _data = {"devices": [{"first_used": "zzz"}], "days": []}
    quality._set_first_day(_data, None)
    check("4o first_day: every device value except 'unknown' is taken (no date format check here)",
          _data["first_day"] == "zzz")
    _data = {"devices": [{"first_used": "2023-05-05"}, {"first_used": "2024-01-05"}], "days": []}
    quality._set_first_day(_data, None)
    check("4o first_day: several device dates -> the earliest", _data["first_day"] == "2023-05-05")
    _cl = _Cl4o(_PROFILE)
    _data = {"devices": [], "days": [{"date": "2022-02-02"}]}
    quality._set_first_day(_data, _cl)
    check("4o first_day: no device -> registration date of the account profile (first 10 characters)",
          _data["first_day"] == "2021-03-04" and _cl.calls == 1)
    for _bad_cl in (_Cl4o({"userInfo": {}}), _Cl4o(boom=True)):
        _data = {"devices": [], "days": [{"date": "2022-02-02"}, {"date": "2021-01-01"}]}
        quality._set_first_day(_data, _bad_cl)
        check("4o first_day: profile without date or failing -> oldest local day",
              _data["first_day"] == "2021-01-01")
    _data = {"first_day": "2000-01-01", "devices": [{"first_used": "1999-01-01"}], "days": []}
    _cl = _Cl4o(_PROFILE)
    quality._set_first_day(_data, _cl)
    check("4o first_day: an existing first_day is never overwritten", _data["first_day"] == "2000-01-01"
          and _cl.calls == 0)
with patch.object(cfg, "SYNC_AUTO_FALLBACK", "2019-01-01"):
    _data = {"devices": [{"first_used": "2024-01-05"}], "days": []}
    quality._set_first_day(_data, None)
    check("4o first_day: devices beat SYNC_AUTO_FALLBACK", _data["first_day"] == "2024-01-05")
    _data = {"devices": [], "days": [{"date": "2022-02-02"}]}
    quality._set_first_day(_data, None)
    check("4o first_day: without devices and account, SYNC_AUTO_FALLBACK beats the oldest local day",
          _data["first_day"] == "2019-01-01")
with patch.object(cfg, "SYNC_AUTO_FALLBACK", ""):
    _data = {"devices": [], "days": []}
    _, _c = _mlogged(quality._set_first_day, _data, _Cl4o(_PROFILE))
    check("4o first_day: set and logged when found",
          _data["first_day"] == "2021-03-04" and any("first_day set to 2021-03-04" in m for _, m in _c))

# ══════════════════════════════════════════════════════════════════════════════
#  4p. garmin_quality._stats and ._scan — archive statistics, quality-log
#      backfill, scan for failed days (v1.7.4.0.3).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4p. garmin_quality._stats, ._scan — statistics, backfill, scan")
import quality._scan as _qs


class _SLog4p:
    """Stands in for _qs.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg))

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg))


def _slogged4p(fn, *args, **kwargs):
    real, rec = _qs.log, _SLog4p()
    _qs.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        _qs.log = real


def _glob_sorted4p():
    real = Path.glob

    def fake(self, pattern, *a, **k):
        return iter(sorted(real(self, pattern, *a, **k)))
    return fake


_HIGH4P = {"date": "x", "heart_rates": {"heartRateValues": [[0, 60]]}}
_STD4P = {"date": "x", "stats": {"totalSteps": 5}}
_FAIL4P = {"date": "x"}

# -- _backfill_quality_log -----------------------------------------------------------------------------------------------------
with _isolated_log_env("q4p_backfill"):
    check("4p backfill: no raw folder -> 0", quality._backfill_quality_log({"days": []}) == 0)
    cfg.RAW_DIR.mkdir(parents=True)
    for _n, _c in (("0junk", _HIGH4P), ("2024-01-01", _HIGH4P), ("2024-01-02", _HIGH4P),
                   ("2024-01-03", _STD4P)):
        (cfg.RAW_DIR / f"garmin_raw_{_n}.json").write_text(json.dumps(_c), encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_2024-01-04.json").write_text("{broken", encoding="utf-8")
    _data = {"days": [{"date": "2024-01-02", "quality": "failed", "reason": "keep"}]}
    with patch.object(Path, "glob", _glob_sorted4p()):
        _n_added, _c = _slogged4p(quality._backfill_quality_log, _data)
    _by = {e["date"]: e for e in _data["days"]}
    check("4p backfill: a file without a date (listed first) does not stop it; known and corrupt days are skipped",
          _n_added == 2 and set(_by) == {"2024-01-01", "2024-01-02", "2024-01-03"}
          and _by["2024-01-02"]["reason"] == "keep")
    check("4p backfill: new entries carry the assessed quality, written=True, source legacy, the backfill reason",
          (_by["2024-01-01"]["quality"], _by["2024-01-03"]["quality"]) == ("high", "standard")
          and _by["2024-01-01"]["write"] is True and _by["2024-01-01"]["source"] == "legacy"
          and _by["2024-01-01"]["reason"] == "Quality: high — backfill on first_day init")
    check("4p backfill: the number of added days is logged",
          ("info", "  Backfill: 2 existing days added to quality log") in _c)
    _, _c = _slogged4p(quality._backfill_quality_log, _data)
    check("4p backfill: nothing new -> 0 and no 'added' line",
          quality._backfill_quality_log(_data) == 0 and not any("Backfill:" in m for _, m in _c))

# -- get_low_quality_dates -------------------------------------------------------------------------------------------------------
with _isolated_log_env("q4p_scan"):
    check("4p scan: missing folder -> {}", quality.get_low_quality_dates(cfg.RAW_DIR / "nope") == {})
    cfg.RAW_DIR.mkdir(parents=True)
    for _n, _c in (("0junk", _FAIL4P), ("2024-01-01", _FAIL4P), ("2024-01-02", _FAIL4P),
                   ("2024-01-03", _HIGH4P), ("2024-01-05", _FAIL4P), ("2024-01-06", _STD4P)):
        (cfg.RAW_DIR / f"garmin_raw_{_n}.json").write_text(json.dumps(_c), encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_2024-01-04.json").write_text("{broken", encoding="utf-8")
    with patch.object(Path, "glob", _glob_sorted4p()):
        _res, _c = _slogged4p(quality.get_low_quality_dates, cfg.RAW_DIR, {date(2024, 1, 1)})
        _res_all = quality.get_low_quality_dates(cfg.RAW_DIR)
        _res_none, _c2 = _slogged4p(quality.get_low_quality_dates, cfg.RAW_DIR,
                                    {date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 5)})
    check("4p scan: only failed days, known days and files without a date are skipped, loop goes on",
          _res == {date(2024, 1, 2): "failed", date(2024, 1, 5): "failed"})
    check("4p scan: without known dates every failed day is found",
          _res_all == {date(2024, 1, 1): "failed", date(2024, 1, 2): "failed", date(2024, 1, 5): "failed"})
    check("4p scan: the number of newly found failed days is logged, nothing found -> no line",
          ("info", "  Newly discovered failed quality files: 2") in _c and _res_none == {}
          and not any("Newly discovered" in m for _, m in _c2))

# -- get_archive_stats -------------------------------------------------------------------------------------------------------------
_DAYS4P = [
    {"date": "2024-01-01", "quality": "high", "source": "api", "recheck": False},
    {"date": "2024-01-02", "quality": "standard", "source": "bulk", "recheck": True},
    {"date": "2024-01-03", "quality": "failed", "source": "api", "recheck": True},
    {"date": "2024-01-05", "quality": "zzz", "source": "x"},
    {"date": "2024-01-10"},
    {"quality": "high"},
]


def _stats4p(days, **extra):
    p = _TMPDIR / "q4p_stats.json"
    p.write_text(json.dumps({"days": days, **extra}), encoding="utf-8")
    return quality.get_archive_stats(p)


_s = _stats4p(_DAYS4P)
check("4p stats: counts per quality (unknown labels counted nowhere, missing label = failed), total, recheck",
      (_s["total"], _s["high"], _s["standard"], _s["failed"], _s["recheck"]) == (6, 2, 1, 2, 2))
check("4p stats: date range, coverage and missing days without first_day (5 dated entries in 10 days)",
      (_s["date_min"], _s["date_max"], _s["coverage_pct"], _s["missing"]) == ("2024-01-01", "2024-01-10", 50, 5))
check("4p stats: last api and last bulk date; unknown and empty sources count as neither",
      (_s["last_api"], _s["last_bulk"]) == ("2024-01-03", "2024-01-02"))
check("4p stats: integrity_warnings default to an empty list", _s["integrity_warnings"] == [])
_s = _stats4p(_DAYS4P, first_day="2023-12-27", integrity_warnings=["log mismatch 2024"])
check("4p stats: an earlier first_day extends the range (5 of 15 days)",
      (_s["coverage_pct"], _s["missing"]) == (33, 10) and _s["integrity_warnings"] == ["log mismatch 2024"])
_s = _stats4p(_DAYS4P, first_day="2024-01-04")
check("4p stats: a later first_day does not shorten the range", (_s["coverage_pct"], _s["missing"]) == (50, 5))
_s = _stats4p([{"date": "2024-02-01"}, {"date": "2024-02-07"}])
check("4p stats: 2 of 7 days -> 29 %, 5 missing", (_s["coverage_pct"], _s["missing"]) == (29, 5))
_s = _stats4p([{"date": "2024-03-01"}, {"date": "2024-03-06"}])
check("4p stats: 2 of 6 days -> 33 %, 4 missing", (_s["coverage_pct"], _s["missing"]) == (33, 4))
_s = _stats4p([])
check("4p stats: an empty log -> zeros and None",
      _s["total"] == 0 and _s["date_min"] is None and _s["coverage_pct"] is None and _s["missing"] is None
      and _s["last_api"] is None and _s["last_bulk"] is None)
_s = _stats4p([{"date": "2024-03-01", "quality": "high"}])
check("4p stats: one day -> 100 %, 0 missing", (_s["coverage_pct"], _s["missing"]) == (100, 0))

summary()
