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

summary()
