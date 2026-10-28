#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_normalizer.py — garmin_normalizer

Run from the project folder:
    python tests/test_normalizer.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""


import gla_testenv  # noqa: F401  (sets up the environment; must precede garmin_* imports)
from support import check, section, summary

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

# v1.7.1.13, Issue #6 — dict_key as a real positional index for list/tuple
# items (previously silently ignored, always read item[1] regardless of
# dict_key). Real-world body_battery shapes from GitHub Issue #6:
# 2-element [ts, val] (dict_key=1, unaffected by the bug) and 4-element
# [ts, status_string, val, extra_float] (dict_key=2, was broken — read
# the status string at index 1 instead of the value at index 2).
check("_parse_list_values: dict_key=2 on 4-element triplet (bug case)",
      normalizer._parse_list_values(
          [[1788580800000, "MEASURED", 28, 3.0], [1788581100000, "MEASURED", 30, 3.0]], 2
      ) == [28, 30])
check("_parse_list_values: dict_key=1 unaffected by the dict_key=2 fix (regression guard)",
      normalizer._parse_list_values([[0, 55], [60, 60]], 1) == [55, 60])
check("_parse_list_values: dict_key=2 with too-short tuple → skipped, not IndexError",
      normalizer._parse_list_values([[0, 1], [0, 1, 2]], 2) == [2])

# summarize — structure
s = normalizer.summarize({"date": "2024-03-15"})
check("summarize: returns dict",            isinstance(s, dict))
check("summarize: date correct",            s["date"] == "2024-03-15")
check(f"summarize: schema_version = {normalizer.CURRENT_SCHEMA_VERSION}",
      s["schema_version"] == normalizer.CURRENT_SCHEMA_VERSION)
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
#  3b. garmin_normalizer — summarize/normalize in depth (v1.7.4.0.3)
#  Closes the survivors of the mutation test: every value of the daily summary
#  is checked against hand-calculated expectations (conversions, rounding,
#  fall-backs, limits), plus normalize()/_normalize_import() and the helpers.
# ══════════════════════════════════════════════════════════════════════════════
section("3b. garmin_normalizer — summarize in depth")


class _NLogRec:
    """Stands in for normalizer.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg))

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg))


def _logged(fn, *args, **kwargs):
    """fn(*args) with the normalizer's logger recorded -> (result, calls)."""
    real, rec = normalizer.log, _NLogRec()
    normalizer.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        normalizer.log = real


def _sum(**sections):
    return normalizer.summarize({"date": "2025-02-03", **sections})


# ── Golden day: every section filled with distinct values ────────────────────
_g_raw = {
    "date": "2025-02-03",
    "sleep": {"dailySleepDTO": {
        "sleepTimeSeconds": 25999, "deepSleepSeconds": 5500, "remSleepSeconds": 6320,
        "lightSleepSeconds": 12650, "awakeSleepSeconds": 1700,
        "sleepScores": {"overall": {"value": 81, "qualifierKey": "GOOD"}},
        "averageSpO2Value": 94.5, "averageRespirationValue": 14.2,
        "sleepScoreFeedback": "POSITIVE_LONGER", "breathingDisruptionSeverity": "LOW"}},
    "hrv": {"hrvSummary": {"lastNightAvg": 47, "weeklyAvg": 52, "status": "BALANCED",
                           "feedbackPhrase": "HRV_BALANCED_2"}},
    "heart_rates": {"restingHeartRate": 52, "maxHeartRate": 171, "minHeartRate": 44,
                    "heartRateValues": [[0, 50], [60, 55], [120, 56]]},
    "stress": {"stressChartValueOffset": 2,
               "stressValuesArray": [[0, 12], [60, 33], [120, 1], [180, -5]],
               "bodyBatteryValuesArray": [[0, "MEASURED", 78], [60, "MEASURED", 91],
                                          [120, "MEASURED", 40]]},
    "user_summary": {"totalSteps": 8421, "dailyStepGoal": 9000, "activeKilocalories": 512,
                     "totalKilocalories": 2733, "moderateIntensityMinutes": 31,
                     "vigorousIntensityMinutes": 12, "floorsAscended": 14,
                     "totalDistanceMeters": 6789, "abnormalHeartRateAlertsCount": 1,
                     "stressQualifier": "BALANCED",
                     "bodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": "LOW"},
                     "endOfDayBodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": "MODERATE"}},
    "get_calories_daily": [{"resting": 1850}],
    "get_body_composition": {"totalAverage": {"weight": 78250}},
    "get_hydration_data": {"valueInML": 1800},
    "get_blood_pressure": {"measurementSummaries": [{
        "highSystolic": 138, "highDiastolic": 88, "lowSystolic": 118, "lowDiastolic": 76,
        "numOfMeasurements": 3, "category": "STAGE_1",
        "measurements": [
            {"category": "NORMAL", "systolic": 118, "diastolic": 76, "pulse": 60,
             "measurementTimestampLocal": "2025-02-03T07:00:00.0"},
            {"category": "STAGE_1", "systolic": 138, "diastolic": 88, "pulse": 72,
             "measurementTimestampLocal": "2025-02-03T21:30:00.0"},
            {"category": "STAGE_1", "systolic": 132, "diastolic": 84, "pulse": 68,
             "measurementTimestampLocal": "2025-02-03T12:00:00.0"}]}]},
    "training_readiness": {"score": 74, "level": "HIGH", "feedbackLong": "GOOD_TO_GO"},
    "training_status": {"latestTrainingStatus": 7,
                        "trainingLoadBalance": {"sevenDayTrainingLoad": 330}},
    "max_metrics": {"vo2MaxPreciseValue": 51.3},
    "get_endurance_score": {"overallScore": 6700},
    "get_hill_score": {"overallScore": 52},
    "get_fitnessage_data": {"fitnessAge": 34},
    "activities": [{"activityName": "Morning Run", "activityType": {"typeKey": "running"},
                    "duration": 3725, "distance": 10234, "averageHR": 148, "maxHR": 171,
                    "calories": 640, "aerobicTrainingEffect": 3.4,
                    "anaerobicTrainingEffect": 1.1}],
}
_g_expected = {
    "date": "2025-02-03",
    "schema_version": normalizer.CURRENT_SCHEMA_VERSION,
    "generated_by": "garmin_normalizer.py",
    "sleep": {"duration_h": 7.22, "deep_h": 1.53, "rem_h": 1.76, "light_h": 3.51,
              "awake_h": 0.47, "score": 81, "spo2_avg": 94.5, "respiration_avg": 14.2,
              "hrv_last_night_ms": 47, "hrv_weekly_avg_ms": 52, "hrv_status": "BALANCED",
              "hrv_feedback": "HRV_BALANCED_2", "sleep_score_feedback": "POSITIVE_LONGER",
              "sleep_score_qualifier": "GOOD"},
    "heartrate": {"resting_bpm": 52, "max_bpm": 171, "min_bpm": 44, "avg_bpm": 53.7},
    "stress": {"stress_avg": 20.5, "stress_max": 31.0, "body_battery_max": 91.0,
               "body_battery_min": 40.0, "body_battery_end": 40.0},
    "day": {"steps": 8421, "steps_goal": 9000, "calories_active": 512, "calories_total": 2733,
            "calories_resting": 1850, "intensity_min_moderate": 31,
            "intensity_min_vigorous": 12, "floors_climbed": 14, "distance_km": 6.79},
    "body_composition": {"weight_g": 78250},
    "hydration": {"value_ml": 1800},
    "blood_pressure": {"high_systolic": 138, "high_diastolic": 88, "low_systolic": 118,
                       "low_diastolic": 76, "num_measurements": 3, "category": "STAGE_1",
                       "worstReading": {"systolic": 138, "diastolic": 88, "pulse": 72,
                                        "timestamp": "2025-02-03T21:30:00.0"}},
    "training": {"readiness_score": 74, "readiness_level": "HIGH",
                 "readiness_feedback": "GOOD_TO_GO", "training_status": 7,
                 "training_status_code": None, "training_load_7d": 330, "vo2max": 51.3, "endurance_score": 6700,
                 "hill_score": 52, "fitness_age": 34},
    "alerts": {"hr_alert_count": 1, "breathing_disruption": "LOW", "acwr_status": None,
               "body_battery_level": "LOW", "body_battery_level_end_of_day": "MODERATE",
               "stress_qualifier": "BALANCED"},
    "activities": [{"name": "Morning Run", "type": "running", "duration_min": 62.1,
                    "distance_km": 10.23, "avg_hr": 148, "max_hr": 171, "calories": 640,
                    "training_effect_aerobic": 3.4, "training_effect_anaerobic": 1.1}],
}
_g = normalizer.summarize(_g_raw)
for _sec in _g_expected:
    check(f"3b golden day: section '{_sec}' exact", _g.get(_sec) == _g_expected[_sec])
check("3b golden day: no extra top-level keys", set(_g) == set(_g_expected))

# ── Sleep: conversion to hours and the missing-sleepTimeSeconds warning ──────
def _sleep_h(**dto):
    return _sum(sleep={"dailySleepDTO": dto})["sleep"]


# seconds picked just below / just above a rounding edge: /3599 and /3601 give another result
for _key, _secs, _exp in [("sleepTimeSeconds", 26009, 7.22), ("sleepTimeSeconds", 26011, 7.23),
                          ("deepSleepSeconds", 26009, 7.22), ("deepSleepSeconds", 26011, 7.23),
                          ("remSleepSeconds", 26009, 7.22), ("remSleepSeconds", 26011, 7.23),
                          ("lightSleepSeconds", 26009, 7.22), ("lightSleepSeconds", 26011, 7.23),
                          ("awakeSleepSeconds", 26009, 7.22), ("awakeSleepSeconds", 26011, 7.23)]:
    _field = {"sleepTimeSeconds": "duration_h", "deepSleepSeconds": "deep_h",
              "remSleepSeconds": "rem_h", "lightSleepSeconds": "light_h",
              "awakeSleepSeconds": "awake_h"}[_key]
    check(f"3b sleep: {_key}={_secs} -> {_field} {_exp}",
          _sleep_h(**{_key: _secs})[_field] == _exp)

_sl = _sleep_h()
check("3b sleep: nothing present -> all hours 0.0, others None",
      [_sl[k] for k in ("duration_h", "deep_h", "rem_h", "light_h", "awake_h")] == [0.0] * 5
      and all(_sl[k] is None for k in ("score", "spo2_avg", "respiration_avg",
                                       "hrv_last_night_ms", "sleep_score_feedback")))
_res, _calls = _logged(normalizer.summarize, {"date": "2025-02-03", "sleep": {"dailySleepDTO": {}}})
check("3b sleep: missing sleepTimeSeconds -> warning with date",
      len(_calls) == 1 and _calls[0][0] == "warning"
      and "[NORMALIZER] summarize 2025-02-03:" in _calls[0][1]
      and "sleepTimeSeconds missing" in _calls[0][1] and "0.0h" in _calls[0][1])
_res, _calls = _logged(normalizer.summarize, {"sleep": {}})
check("3b sleep: warning without a date uses '?'",
      len(_calls) == 1 and "summarize ?:" in _calls[0][1])
_res, _calls = _logged(normalizer.summarize, {"date": "d", "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 0}}})
check("3b sleep: sleepTimeSeconds=0 present -> no warning", _calls == [])
check("3b sleep: sleep=None does not crash", _sum(sleep=None)["sleep"]["duration_h"] == 0.0)

# HRV: from 'hrv', else from the sleep payload
_h1 = _sum(hrv={"hrvSummary": {"lastNightAvg": 40}},
           sleep={"dailySleepDTO": {}, "hrvSummary": {"lastNightAvg": 99}})["sleep"]
check("3b hrv: 'hrv' wins over the sleep payload", _h1["hrv_last_night_ms"] == 40)
_h2 = _sum(sleep={"dailySleepDTO": {}, "hrvSummary": {"lastNightAvg": 38, "weeklyAvg": 41,
                                                     "status": "LOW", "feedbackPhrase": "F"}})["sleep"]
check("3b hrv: falls back to the sleep payload",
      [_h2[k] for k in ("hrv_last_night_ms", "hrv_weekly_avg_ms", "hrv_status", "hrv_feedback")]
      == [38, 41, "LOW", "F"])
_h3 = _sum(hrv={"hrvSummary": {}}, sleep={"dailySleepDTO": {}, "hrvSummary": {"weeklyAvg": 44}})["sleep"]
check("3b hrv: empty hrvSummary falls back too", _h3["hrv_weekly_avg_ms"] == 44)
check("3b hrv: absent everywhere -> None",
      _sum()["sleep"]["hrv_last_night_ms"] is None and _sum()["sleep"]["hrv_status"] is None)

# ── Heart rate ───────────────────────────────────────────────────────────────
check("3b heartrate: average rounded to 1 decimal",
      _sum(heart_rates={"heartRateValues": [[0, 50], [1, 55], [2, 56]]})["heartrate"]["avg_bpm"] == 53.7)
check("3b heartrate: average of 2 values",
      _sum(heart_rates={"heartRateValues": [[0, 60], [1, 65]]})["heartrate"]["avg_bpm"] == 62.5)
check("3b heartrate: non-numeric values are ignored",
      _sum(heart_rates={"heartRateValues": [[0, None], [1, "x"], [2, 70], [3]]})["heartrate"]["avg_bpm"] == 70)
_hr0 = _sum(heart_rates={})["heartrate"]
check("3b heartrate: nothing present -> all None",
      _hr0 == {"resting_bpm": None, "max_bpm": None, "min_bpm": None, "avg_bpm": None})
check("3b heartrate: only values, no aggregates",
      _sum(heart_rates={"restingHeartRate": 48})["heartrate"]["resting_bpm"] == 48
      and _sum(heart_rates={"minHeartRate": 40})["heartrate"]["min_bpm"] == 40
      and _sum(heart_rates={"maxHeartRate": 180})["heartrate"]["max_bpm"] == 180)

# ── Stress ───────────────────────────────────────────────────────────────────
_st = _sum(stress={"stressChartValueOffset": 10, "stressValuesArray": [
    [0, 10], [1, 9], [2, 25], [3], "x", [4, None], [5, "abc"], (6, 40)]})["stress"]
check("3b stress: offset subtracted, negative dropped, 0 kept, junk skipped",
      _st["stress_avg"] == 15.0 and _st["stress_max"] == 30.0)
_st = _sum(stress={"stressValuesArray": [[0, 20], [1, 33]]})["stress"]
check("3b stress: no offset -> average 26.5, max 33.0",
      _st["stress_avg"] == 26.5 and _st["stress_max"] == 33.0)
_st = _sum(stress={"stressValuesArray": [[0, 10], [1, 20], [2, 25]]})["stress"]
check("3b stress: average rounded to 1 decimal (18.3)", _st["stress_avg"] == 18.3)
_st = _sum(stress={"averageStressLevel": 33, "maxStressLevel": 88})["stress"]
check("3b stress: bulk fallback without intraday array",
      _st["stress_avg"] == 33 and _st["stress_max"] == 88)
_st = _sum(stress={"stressChartValueOffset": 50, "stressValuesArray": [[0, 10]],
                   "averageStressLevel": 21, "maxStressLevel": 66})["stress"]
check("3b stress: all values filtered out -> bulk fallback",
      _st["stress_avg"] == 21 and _st["stress_max"] == 66)
_st = _sum(stress=[1, 2])["stress"]
check("3b stress: 'stress' is not a dict -> everything None, no crash",
      _st == {"stress_avg": None, "stress_max": None, "body_battery_max": None,
              "body_battery_min": None, "body_battery_end": None})
_st = _sum()["stress"]
check("3b stress: nothing present -> everything None",
      all(v is None for v in _st.values()))

# ── Body battery ─────────────────────────────────────────────────────────────
_bb = _sum(stress={"bodyBatteryValuesArray": [
    [0, "M", 50], [1, "M"], [2, "M", "x"], [3, "M", 70]]})["stress"]
check("3b body battery: 3-element items used, short and non-numeric skipped",
      [_bb["body_battery_max"], _bb["body_battery_min"], _bb["body_battery_end"]] == [70.0, 50.0, 70.0])
_bb = _sum(stress={"bodyBatteryValuesArray": [[0, "M", 40], [1, "M", 90], [2, "M", 60]]})["stress"]
check("3b body battery: max, min, last value are different elements",
      [_bb["body_battery_max"], _bb["body_battery_min"], _bb["body_battery_end"]] == [90.0, 40.0, 60.0])
_bb = _sum(body_battery={"bodyBatteryValuesArray": [{"value": 20}, {"value": 80}, {"value": "x"}]})["stress"]
check("3b body battery: fallback to body_battery dict",
      [_bb["body_battery_max"], _bb["body_battery_min"], _bb["body_battery_end"]] == [80, 20, 80])
_bb = _sum(body_battery=[{"value": 35}, {"value": 15}])["stress"]
check("3b body battery: fallback to body_battery list",
      [_bb["body_battery_max"], _bb["body_battery_min"], _bb["body_battery_end"]] == [35, 15, 15])
_bb = _sum(stress={"bodyBatteryValuesArray": [[0, "M", "x"]]},
           body_battery=[{"value": 12}])["stress"]
check("3b body battery: unusable stress array -> fallback", _bb["body_battery_end"] == 12)
_bb = _sum(stress={"bodyBatteryValuesArray": [[0, "M", 55]]},
           body_battery=[{"value": 12}])["stress"]
check("3b body battery: stress array wins over the fallback", _bb["body_battery_end"] == 55.0)
_bb = _sum(body_battery="garbage")["stress"]
check("3b body battery: garbage -> None",
      _bb["body_battery_max"] is None and _bb["body_battery_min"] is None
      and _bb["body_battery_end"] is None)

# ── Daily stats ──────────────────────────────────────────────────────────────
check("3b day: steps from user_summary over stats",
      _sum(user_summary={"totalSteps": 100}, stats={"totalSteps": 4000})["day"]["steps"] == 100)
check("3b day: steps fall back to stats when user_summary has none",
      _sum(user_summary={}, stats={"totalSteps": 4000})["day"]["steps"] == 4000)
check("3b day: user_summary steps 0 -> stats value (as implemented)",
      _sum(user_summary={"totalSteps": 0}, stats={"totalSteps": 4000})["day"]["steps"] == 4000)
check("3b day: steps absent -> None", _sum()["day"]["steps"] is None)
check("3b day: resting calories from the first daily entry",
      _sum(get_calories_daily=[{"resting": 1700}, {"resting": 1}])["day"]["calories_resting"] == 1700)
check("3b day: resting calories None when the list is empty or the key is missing",
      _sum(get_calories_daily=[])["day"]["calories_resting"] is None
      and _sum(get_calories_daily=[{}])["day"]["calories_resting"] is None)
for _m, _km in [(1500, 1.5), (14, 0.01), (4, None), (0, None), (12345, 12.35), (999, 1.0)]:
    check(f"3b day: totalDistanceMeters={_m} -> distance_km {_km}",
          _sum(user_summary={"totalDistanceMeters": _m})["day"]["distance_km"] == _km)
check("3b day: distance absent -> None", _sum()["day"]["distance_km"] is None)
check("3b body composition / hydration: absent -> None",
      _sum()["body_composition"]["weight_g"] is None and _sum()["hydration"]["value_ml"] is None)

# ── Blood pressure ───────────────────────────────────────────────────────────
_bp = _sum()["blood_pressure"]
check("3b blood pressure: nothing present -> all None",
      all(v is None for v in _bp.values()) and len(_bp) == 7)
_bp = _sum(get_blood_pressure={"measurementSummaries": []})["blood_pressure"]
check("3b blood pressure: empty summaries -> all None", all(v is None for v in _bp.values()))
_bp_day = {"category": "HIGH", "measurements": [
    {"category": "HIGH", "systolic": 150, "diastolic": 95, "pulse": 80,
     "measurementTimestampLocal": "2025-02-03T08:00:00.0"},
    "junk",
    {"category": "HIGH", "systolic": 160, "diastolic": 99, "pulse": 85,
     "measurementTimestampLocal": "2025-02-03T09:00:00.0"},
    {"category": "NORMAL", "systolic": 120, "diastolic": 80, "pulse": 60,
     "measurementTimestampLocal": "2025-02-03T23:00:00.0"}]}
_bp = _sum(get_blood_pressure={"measurementSummaries": [_bp_day]})["blood_pressure"]
check("3b blood pressure: latest reading of the day's category wins, others ignored",
      _bp["worstReading"] == {"systolic": 160, "diastolic": 99, "pulse": 85,
                              "timestamp": "2025-02-03T09:00:00.0"})
_bp_day2 = {"category": "HIGH", "measurements": [
    {"category": "HIGH", "systolic": 1, "diastolic": 2, "pulse": 3},
    {"category": "HIGH", "systolic": 4, "diastolic": 5, "pulse": 6,
     "measurementTimestampLocal": "2025-02-03T01:00:00.0"}]}
_bp = _sum(get_blood_pressure={"measurementSummaries": [_bp_day2]})["blood_pressure"]
check("3b blood pressure: reading without timestamp sorts first",
      _bp["worstReading"]["systolic"] == 4)
_bp = _sum(get_blood_pressure={"measurementSummaries": [
    {"category": "LOW", "measurements": [{"category": "NORMAL", "systolic": 1}]}]})["blood_pressure"]
check("3b blood pressure: no reading of the day's category -> worstReading None",
      _bp["worstReading"] is None and _bp["category"] == "LOW")
_bp = _sum(get_blood_pressure={"measurementSummaries": [{"category": "X"}]})["blood_pressure"]
check("3b blood pressure: no measurements list -> worstReading None", _bp["worstReading"] is None)
_bp = _sum(get_blood_pressure={"measurementSummaries": [{"highSystolic": 1}, {"highSystolic": 2}]})["blood_pressure"]
check("3b blood pressure: only the first summary is used", _bp["high_systolic"] == 1)

# ── Training ─────────────────────────────────────────────────────────────────
_tr = _sum(training_readiness={"trainingReadinessScore": 60, "trainingReadinessLevel": "MODERATE"},
           training_status={"trainingStatus": 4},
           max_metrics={"generic": {"vo2MaxPreciseValue": 48.2}})["training"]
check("3b training: fall-back keys",
      [_tr["readiness_score"], _tr["readiness_level"], _tr["training_status"], _tr["vo2max"]]
      == [60, "MODERATE", 4, 48.2])
_tr = _sum(training_readiness={"score": 70, "trainingReadinessScore": 60,
                               "level": "HIGH", "trainingReadinessLevel": "LOW"},
           training_status={"latestTrainingStatus": 7, "trainingStatus": 4},
           max_metrics={"vo2MaxPreciseValue": 51.0, "generic": {"vo2MaxPreciseValue": 48.2}})["training"]
check("3b training: primary keys win over the fall-backs",
      [_tr["readiness_score"], _tr["readiness_level"], _tr["training_status"], _tr["vo2max"]]
      == [70, "HIGH", 7, 51.0])
_tr = _sum()["training"]
check("3b training: nothing present -> all None", all(v is None for v in _tr.values()) and len(_tr) == 10)

# ── Activities ───────────────────────────────────────────────────────────────
_acts = _sum(activities=[
    {"activityType": "cycling", "duration": 90, "distance": 0},
    {"activityName": "bare"},
    {"activityType": {"typeKey": "swimming"}, "duration": 1830, "distance": 1234}])["activities"]
check("3b activities: three entries", len(_acts) == 3)
check("3b activities: type as plain string, duration 90 s = 1.5 min, distance 0 -> None",
      _acts[0]["type"] == "cycling" and _acts[0]["duration_min"] == 1.5
      and _acts[0]["distance_km"] is None)
check("3b activities: bare entry -> everything None",
      _acts[1] == {"name": "bare", "type": None, "duration_min": None, "distance_km": None,
                   "avg_hr": None, "max_hr": None, "calories": None,
                   "training_effect_aerobic": None, "training_effect_anaerobic": None})
check("3b activities: swimming 1830 s = 30.5 min, 1234 m = 1.23 km",
      _acts[2]["type"] == "swimming" and _acts[2]["duration_min"] == 30.5
      and _acts[2]["distance_km"] == 1.23)
check("3b activities: duration rounding to 1 decimal",
      _sum(activities=[{"duration": 100}])["activities"][0]["duration_min"] == 1.7)
check("3b activities: not a list / empty -> []",
      _sum(activities="x")["activities"] == [] and _sum(activities=None)["activities"] == []
      and _sum(activities={})["activities"] == [])
check("3b summarize: empty raw -> date None",
      normalizer.summarize({})["date"] is None)

# ── normalize() and _normalize_import() ──────────────────────────────────────
_raw = {"date": "d", "x": 1}
_res, _calls = _logged(normalizer.normalize, _raw, "xyz")
check("3b normalize: unknown source passes the dict through and warns",
      _res is _raw and len(_calls) == 1 and "unknown source 'xyz'" in _calls[0][1])
_res, _calls = _logged(normalizer.normalize, _raw)
check("3b normalize: default source is api, same object back, no warning",
      _res is _raw and _calls == [])
_res, _calls = _logged(normalizer.normalize, None, "api")
check("3b normalize api: non-dict -> unknown, warning names the function",
      _res == {"date": "unknown"} and len(_calls) == 1 and "_normalize_api: received non-dict" in _calls[0][1])
_res, _calls = _logged(normalizer.normalize, None, "bulk")
check("3b normalize bulk: non-dict -> unknown, warning names the function",
      _res == {"date": "unknown"} and len(_calls) == 1 and "_normalize_import: received non-dict" in _calls[0][1])

_raw = {"date": "d", "user_summary": {"restingHeartRate": 55, "minHeartRate": 0,
                                       "maxHeartRate": None, "totalSteps": 1}}
_res = normalizer.normalize(_raw, "bulk")
check("3b bulk remap: heart_rates built from user_summary, None dropped, 0 kept",
      _res is _raw and _res["heart_rates"] == {"restingHeartRate": 55, "minHeartRate": 0})
_raw = {"date": "d", "user_summary": {"restingHeartRate": 55}, "heart_rates": {"restingHeartRate": 1}}
check("3b bulk remap: existing heart_rates is not overwritten",
      normalizer.normalize(_raw, "bulk")["heart_rates"] == {"restingHeartRate": 1})
check("3b bulk remap: empty user_summary -> no heart_rates",
      "heart_rates" not in normalizer.normalize({"date": "d", "user_summary": {}}, "bulk"))
check("3b bulk remap: user_summary without HR fields -> no heart_rates",
      "heart_rates" not in normalizer.normalize({"date": "d", "user_summary": {"totalSteps": 5}}, "bulk"))
check("3b bulk remap: all three fields are taken over",
      normalizer.normalize({"date": "d", "user_summary": {
          "restingHeartRate": 50, "minHeartRate": 40, "maxHeartRate": 150}}, "bulk")["heart_rates"]
      == {"restingHeartRate": 50, "minHeartRate": 40, "maxHeartRate": 150})
check("3b bulk remap: user_summary None -> no crash, no heart_rates",
      "heart_rates" not in normalizer.normalize({"date": "d", "user_summary": None}, "bulk"))

# ── safe_get / _parse_list_values ────────────────────────────────────────────
check("3b safe_get: intermediate value is not a dict -> default",
      normalizer.safe_get({"a": 5}, "a", "b", default=7) == 7)
check("3b safe_get: intermediate None -> default",
      normalizer.safe_get({"a": None}, "a", "b", default=7) == 7)
check("3b safe_get: final value None is returned as None, not as the default",
      normalizer.safe_get({"a": None}, "a", default=5) is None)
check("3b safe_get: missing key at the first level -> default",
      normalizer.safe_get({"a": 1}, "z", default=3) == 3)
check("3b safe_get: no keys -> the dict itself", normalizer.safe_get({"a": 1}) == {"a": 1})
check("3b safe_get: not a dict -> default", normalizer.safe_get(None, "a", default=2) == 2)
check("3b _parse_list_values: None / empty / not a list -> []",
      normalizer._parse_list_values(None, 1) == [] and normalizer._parse_list_values([], "v") == []
      and normalizer._parse_list_values("abc", 1) == [])
check("3b _parse_list_values: floats count, strings and None do not",
      normalizer._parse_list_values([[0, 1.5], [1, "2"], [2, None], [3, 4]], 1) == [1.5, 4])
check("3b _parse_list_values: dict items need a matching key",
      normalizer._parse_list_values([{"v": 1}, {"w": 2}, {"v": "x"}, {"v": 3.5}], "v") == [1, 3.5])
check("3b _parse_list_values: string key ignores list items, int key ignores dict items",
      normalizer._parse_list_values([[0, 1]], "v") == []
      and normalizer._parse_list_values([{1: 5}], 1) == [5])
check("3b _parse_list_values: junk items are skipped",
      normalizer._parse_list_values(["x", 5, None, [0, 9]], 1) == [9])
check("3b _parse_list_values: tuple items work, length must exceed the index",
      normalizer._parse_list_values([(0, 7), (0,)], 1) == [7])

# ── Second round (after the first mutation measurement) ──────────────────────
# The schema version is the identity of the summary format: a bump must be a conscious
# decision, so it is pinned here (update this check together with the bump).
check("3b schema: CURRENT_SCHEMA_VERSION is 5 and written into the summary",
      normalizer.CURRENT_SCHEMA_VERSION == 5 and _sum()["schema_version"] == 5)

# source dispatch: only the exact strings 'api' and 'bulk' count (strings built at run
# time so that identity ('is') and prefix/ordering comparisons cannot pass by accident)
_api_dyn, _bulk_dyn = "".join(["a", "pi"]), "".join(["bu", "lk"])
_raw = {"date": "d", "user_summary": {"restingHeartRate": 55}}
check("3b normalize: 'bulk' built at run time still takes the bulk path",
      "heart_rates" in normalizer.normalize(dict(_raw), _bulk_dyn))
_r, _c = _logged(normalizer.normalize, dict(_raw), _api_dyn)
check("3b normalize: 'api' built at run time still takes the api path (no remap, no warning)",
      "heart_rates" not in _r and _c == [])
for _src in ("a", "ap", "", "bu", "bul", "apia", "bulkk"):
    _r, _c = _logged(normalizer.normalize, dict(_raw), _src)
    check(f"3b normalize: source '{_src}' is unknown -> passthrough, warning, no remap",
          "heart_rates" not in _r and len(_c) == 1 and "unknown source" in _c[0][1])

# stress / body battery items may carry more elements than the minimum
check("3b stress: items with 3 elements are used (>= 2, not == 2)",
      _sum(stress={"stressValuesArray": [[0, 20, "x"], [1, 40, "y"]]})["stress"]["stress_avg"] == 30.0)
check("3b body battery: 4-element items are used (>= 3, not == 3) — Issue #6 shape",
      _sum(stress={"bodyBatteryValuesArray": [[0, "M", 28, 3.0], [1, "M", 30, 3.0]]}
           )["stress"]["body_battery_end"] == 30.0)

# blood pressure: category match must be exact equality, and the LAST candidate wins
_bp_cat = "".join(["HI", "GH"])
_bp = _sum(get_blood_pressure={"measurementSummaries": [{"category": "HIGH", "measurements": [
    {"category": _bp_cat, "systolic": 1, "measurementTimestampLocal": "2025-02-03T01:00:00.0"},
    {"category": "AAA", "systolic": 2, "measurementTimestampLocal": "2025-02-03T23:00:00.0"}]}]}
           )["blood_pressure"]
check("3b blood pressure: category compared by value (equal strings), others ignored",
      _bp["worstReading"]["systolic"] == 1)
_bp = _sum(get_blood_pressure={"measurementSummaries": [{"category": "HIGH", "measurements": [
    {"category": "HIGH", "systolic": 1, "measurementTimestampLocal": "2025-02-03T01:00:00.0"},
    {"category": "HIGH", "systolic": 2, "measurementTimestampLocal": "2025-02-03T02:00:00.0"},
    {"category": "HIGH", "systolic": 3, "measurementTimestampLocal": "2025-02-03T03:00:00.0"}]}]}
           )["blood_pressure"]
check("3b blood pressure: with 3 candidates the latest (last after sorting) wins",
      _bp["worstReading"]["systolic"] == 3)

# _parse_list_values: an item shorter than the index is skipped, never read
check("3b _parse_list_values: empty and one-element items with index 1/2 are skipped",
      normalizer._parse_list_values([[], [0]], 1) == []
      and normalizer._parse_list_values([[0]], 2) == [])

# ── P1.1/P1.2 (v1.7.6.6): the "training" section on the shapes of the API day, finding 3 ───────
# The raw day of the API holds training_readiness and max_metrics as LISTS of objects and the
# training status nested under mostRecentTrainingStatus.latestTrainingStatusData.<device id>.
# Until P1.1 summarize() read dicts with other keys, so "training" stayed empty on every such day;
# P1.1 pinned that state, P1.2 turned the pins around (the checks below keep their P1.1 names).
# Synthetic values, the shapes follow the real archive.
_P11_DEV = "1111111111"
_p11_raw = {
    "training_readiness": [
        {"calendarDate": "2025-02-03", "timestamp": "2025-02-03T05:00:00.0",
         "score": 61, "level": "MODERATE", "feedbackLong": "RECOVERED_AND_READY"},
        {"calendarDate": "2025-02-03", "timestamp": "2025-02-03T09:00:00.0",
         "score": 74, "level": "HIGH", "feedbackLong": "GOOD_TO_GO"},
    ],
    "training_status": {
        "mostRecentTrainingStatus": {"latestTrainingStatusData": {_P11_DEV: {
            "trainingStatus": 4, "timestamp": 1738573200000,
            "acuteTrainingLoadDTO": {"acwrStatus": "OPTIMAL"}}}},
        "mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {_P11_DEV: {"deviceId": 1}}},
    },
    "max_metrics": [{"generic": {"calendarDate": "2025-02-03", "vo2MaxPreciseValue": 51.3, "fitnessAge": 33}}],
    "stats": {"abnormalHeartRateAlertsCount": 1, "stressQualifier": "BALANCED",
              "bodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": "HIGH"}},
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 25000, "breathingDisruptionSeverity": "LOW"}},
}
_p11_s = _sum(**_p11_raw)
_p11_tr = _p11_s["training"]
check("P1.2 real-archive shapes: readiness from the element with the latest timestamp",
      [_p11_tr["readiness_score"], _p11_tr["readiness_level"], _p11_tr["readiness_feedback"]]
      == [74, "HIGH", "GOOD_TO_GO"])
check("P1.2 real-archive shapes: training status as text and as number",
      [_p11_tr["training_status"], _p11_tr["training_status_code"]] == ["MAINTAINING", 4])
check("P1.2 real-archive shapes: vo2max and fitness age from the max_metrics list",
      [_p11_tr["vo2max"], _p11_tr["fitness_age"]] == [51.3, 33])
check("P1.2 real-archive shapes: no source for the other fields -> None",
      [_p11_tr["training_load_7d"], _p11_tr["endurance_score"], _p11_tr["hill_score"]] == [None, None, None])
check("P1.2 the training section has 10 fields", len(_p11_tr) == 10)
check("P1.3 real-archive shapes: alerts from stats, sleep and the device entry",
      _p11_s["alerts"] == {"hr_alert_count": 1, "breathing_disruption": "LOW", "acwr_status": "OPTIMAL",
                           "body_battery_level": "HIGH", "body_battery_level_end_of_day": None,
                           "stress_qualifier": "BALANCED"})

# readiness: the choice does not depend on the order of the list
_p11_rev = _sum(training_readiness=list(reversed(_p11_raw["training_readiness"])))["training"]
check("P1.2 readiness: the same element wins when the list is reversed",
      [_p11_rev["readiness_score"], _p11_rev["readiness_level"]] == [74, "HIGH"])
_p11_late = [{"score": 20, "level": "A", "timestamp": "2025-02-03T09:00:00.0"},
             {"score": 10, "level": "A", "timestamp": "2025-02-03T05:00:00.0"}]
check("P1.2 readiness: the later time wins even when the earlier entry has the smaller JSON text",
      _sum(training_readiness=_p11_late)["training"]["readiness_score"] == 20
      and _sum(training_readiness=list(reversed(_p11_late)))["training"]["readiness_score"] == 20)
_p11_one = _sum(training_readiness=[_p11_raw["training_readiness"][0]])["training"]
check("P1.2 readiness: a list with one element is used", _p11_one["readiness_score"] == 61)
_p11_nots = _sum(training_readiness=[{"score": 10, "level": "LOW"},
                                     {"score": 20, "level": "HIGH", "timestamp": "2025-02-03T05:00:00.0"}])["training"]
check("P1.2 readiness: an element with a time beats one without", _p11_nots["readiness_score"] == 20)
_p11_tie = _sum(training_readiness=[{"score": 30, "level": "B", "timestamp": "2025-02-03T05:00:00.0"},
                                    {"score": 20, "level": "A", "timestamp": "2025-02-03T05:00:00.0"}])["training"]
check("P1.2 readiness: same time -> the smaller canonical JSON text wins, in either order",
      _p11_tie["readiness_score"] == 20
      and _sum(training_readiness=[{"score": 20, "level": "A", "timestamp": "2025-02-03T05:00:00.0"},
                                   {"score": 30, "level": "B", "timestamp": "2025-02-03T05:00:00.0"}]
               )["training"]["readiness_score"] == 20)
check("P1.2 readiness: a boolean is no time (that entry has none)",
      _sum(training_readiness=[{"score": 2, "timestamp": True}, {"score": 1}])["training"]["readiness_score"] == 1)
check("P1.2 readiness: a timestamp text that is no time counts as no time (the entry without one is not beaten by it)",
      _sum(training_readiness=[{"score": 2, "timestamp": "no time"}, {"score": 1}])["training"]["readiness_score"] == 1)
check("P1.2 readiness: ... and an entry with a readable time beats one with an unreadable timestamp text",
      _sum(training_readiness=[{"score": 3, "timestamp": "no time"},
                               {"score": 4, "timestamp": "2025-02-03T05:00:00.0"}])["training"]["readiness_score"] == 4)
check("P1.2 readiness: without times the smaller canonical JSON text wins",
      _sum(training_readiness=[{"score": 20}, {"score": 10}])["training"]["readiness_score"] == 10)
for _label, _val in (("empty list", []), ("list of junk", [None, 5, "x"]), ("string", "x"), ("None", None)):
    _t = _sum(training_readiness=_val)["training"]
    check(f"P1.2 readiness: {_label} -> no values, no crash",
          _t["readiness_score"] is None and _t["readiness_level"] is None and _t["readiness_feedback"] is None)
check("P1.2 readiness: a dict (export values) is read as before",
      _sum(training_readiness={"score": 74, "level": "HIGH", "feedbackLong": "X"})["training"]["readiness_score"] == 74)

# training status: every number of the table, an unknown number, devices
def _p11_status(entries):
    return _sum(training_status={"mostRecentTrainingStatus": {"latestTrainingStatusData": entries}})["training"]

for _n, _name in ((0, "NO_STATUS"), (1, "DETRAINING"), (3, "OVERREACHING"), (4, "MAINTAINING"),
                  (5, "RECOVERY"), (7, "PRODUCTIVE")):
    _t = _p11_status({_P11_DEV: {"trainingStatus": _n}})
    check(f"P1.2 training status: {_n} -> {_name}, code {_n}",
          [_t["training_status"], _t["training_status_code"]] == [_name, _n])
for _n in (2, 6, 8, 99):
    _t = _p11_status({_P11_DEV: {"trainingStatus": _n}})
    check(f"P1.2 training status: unknown number {_n} -> no text, the number stays",
          [_t["training_status"], _t["training_status_code"]] == [None, _n])
for _label, _v in (("text", "4"), ("float", 4.0), ("bool", True), ("None", None)):
    _t = _p11_status({_P11_DEV: {"trainingStatus": _v}})
    check(f"P1.2 training status: value of type {_label} -> no text, no code",
          [_t["training_status"], _t["training_status_code"]] == [None, None])
_t = _p11_status({"1": {"trainingStatus": 1, "timestamp": 1000}, "2": {"trainingStatus": 7, "timestamp": 2000}})
check("P1.2 training status: with two devices the entry with the later timestamp wins",
      [_t["training_status"], _t["training_status_code"]] == ["PRODUCTIVE", 7])
_t = _p11_status({"2": {"trainingStatus": 7, "timestamp": 2000}, "1": {"trainingStatus": 1, "timestamp": 1000}})
check("P1.2 training status: ... independent of the order of the devices",
      [_t["training_status"], _t["training_status_code"]] == ["PRODUCTIVE", 7])
_t = _p11_status({"1": {"trainingStatus": 1}, "2": {"trainingStatus": 7, "timestamp": 2000}})
check("P1.2 training status: an entry with a timestamp beats one without", _t["training_status_code"] == 7)
for _label, _v in (("empty map", {}), ("map of junk", {"1": None, "2": 5}), ("list", [1]), ("None", None)):
    _t = _p11_status(_v)
    check(f"P1.2 training status: {_label} -> no values, no crash",
          [_t["training_status"], _t["training_status_code"]] == [None, None])
_t = _sum(training_status={"latestTrainingStatus": 9, "mostRecentTrainingStatus": {
    "latestTrainingStatusData": {_P11_DEV: {"trainingStatus": 4}}}})["training"]
check("P1.2 training status: the nested text wins over the old top-level key",
      [_t["training_status"], _t["training_status_code"]] == ["MAINTAINING", 4])
_t = _sum(training_status={"latestTrainingStatus": 9, "mostRecentTrainingStatus": {
    "latestTrainingStatusData": {_P11_DEV: {"trainingStatus": 2}}}})["training"]
check("P1.2 training status: unknown nested number -> the old top-level key is the fall-back, code stays",
      [_t["training_status"], _t["training_status_code"]] == [9, 2])
_t = _sum(training_status={"latestTrainingStatus": 7})["training"]
check("P1.2 training status: the old top-level key alone is unchanged (value as given, no code)",
      [_t["training_status"], _t["training_status_code"]] == [7, None])

# max_metrics: list forms, the newest element, fitness age
_mm = lambda *els: _sum(max_metrics=list(els))["training"]
check("P1.2 max_metrics: an empty list -> None", _mm()["vo2max"] is None and _mm()["fitness_age"] is None)
check("P1.2 max_metrics: the element with the newest generic.calendarDate wins, in either order",
      _mm({"generic": {"calendarDate": "2025-01-01", "vo2MaxPreciseValue": 40.0}},
          {"generic": {"calendarDate": "2025-02-01", "vo2MaxPreciseValue": 50.0}})["vo2max"] == 50.0
      and _mm({"generic": {"calendarDate": "2025-02-01", "vo2MaxPreciseValue": 50.0}},
              {"generic": {"calendarDate": "2025-01-01", "vo2MaxPreciseValue": 40.0}})["vo2max"] == 50.0)
check("P1.2 max_metrics: without dates the first element wins",
      _mm({"generic": {"vo2MaxPreciseValue": 41.0}}, {"generic": {"vo2MaxPreciseValue": 42.0}})["vo2max"] == 41.0)
check("P1.2 max_metrics: junk elements are skipped",
      _mm(None, 5, {"generic": {"vo2MaxPreciseValue": 43.0}})["vo2max"] == 43.0)
check("P1.2 fitness age: get_fitnessage_data comes first, the max_metrics value is the fall-back",
      _sum(get_fitnessage_data={"fitnessAge": 30}, max_metrics=[{"generic": {"fitnessAge": 33}}]
           )["training"]["fitness_age"] == 30
      and _sum(max_metrics=[{"generic": {"fitnessAge": 33}}])["training"]["fitness_age"] == 33)
check("P1.2 fitness age: 0 from get_fitnessage_data is a value, not a gap",
      _sum(get_fitnessage_data={"fitnessAge": 0}, max_metrics=[{"generic": {"fitnessAge": 33}}]
           )["training"]["fitness_age"] == 0)

# ── P1.3 (v1.7.6.6): the "alerts" section ────────────────────────────────────────────────────
_ALERT_FIELDS = ["hr_alert_count", "breathing_disruption", "acwr_status", "body_battery_level",
                 "body_battery_level_end_of_day", "stress_qualifier"]
_al = _sum()["alerts"]
check("P1.3 alerts: nothing present -> six fields, all None",
      list(_al) == _ALERT_FIELDS and all(v is None for v in _al.values()))
_al = _sum(sleep={"dailySleepDTO": {"breathingDisruptionSeverity": "NONE"}})["alerts"]
check("P1.3 alerts: breathing disruption 'NONE' is a value, not a gap", _al["breathing_disruption"] == "NONE")
_al = _sum(stats={"stressQualifier": "UNKNOWN"})["alerts"]
check("P1.3 alerts: stress qualifier 'UNKNOWN' is passed on", _al["stress_qualifier"] == "UNKNOWN")
check("P1.3 alerts: pulse alert count 0 is a value, not a gap",
      _sum(user_summary={"abnormalHeartRateAlertsCount": 0})["alerts"]["hr_alert_count"] == 0)

# source order: user_summary first, stats as the fall-back
for _field, _key, _sub in (("hr_alert_count", "abnormalHeartRateAlertsCount", None),
                           ("stress_qualifier", "stressQualifier", None),
                           ("body_battery_level", "bodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel"),
                           ("body_battery_level_end_of_day", "endOfDayBodyBatteryDynamicFeedbackEvent", "bodyBatteryLevel")):
    def _mk(v, _key=_key, _sub=_sub):
        return v if _sub is None else {_sub: v}
    _a, _b = (3, 4) if _sub is None and _field == "hr_alert_count" else ("AAA", "BBB")
    check(f"P1.3 alerts.{_field}: only stats -> read from stats",
          _sum(stats={_key: _mk(_a)})["alerts"][_field] == _a)
    check(f"P1.3 alerts.{_field}: only user_summary -> read from user_summary",
          _sum(user_summary={_key: _mk(_a)})["alerts"][_field] == _a)
    check(f"P1.3 alerts.{_field}: both present -> user_summary wins",
          _sum(user_summary={_key: _mk(_a)}, stats={_key: _mk(_b)})["alerts"][_field] == _a)
    check(f"P1.3 alerts.{_field}: user_summary has no usable value -> stats",
          _sum(user_summary={_key: _mk(None)}, stats={_key: _mk(_b)})["alerts"][_field] == _b)

# types: a text field takes only a non-empty string, the count only a whole number (no boolean)
for _label, _bad in (("number", 5), ("bool", True), ("list", ["x"]), ("dict", {"a": 1}), ("empty string", "")):
    _al = _sum(stats={"stressQualifier": _bad, "bodyBatteryDynamicFeedbackEvent": {"bodyBatteryLevel": _bad}},
               sleep={"dailySleepDTO": {"breathingDisruptionSeverity": _bad}})["alerts"]
    check(f"P1.3 alerts: a {_label} where a text belongs -> None",
          _al["stress_qualifier"] is None and _al["body_battery_level"] is None and _al["breathing_disruption"] is None)
for _label, _bad in (("text", "1"), ("float", 1.0), ("bool", True), ("None", None)):
    check(f"P1.3 alerts: a {_label} where the count belongs -> None",
          _sum(stats={"abnormalHeartRateAlertsCount": _bad})["alerts"]["hr_alert_count"] is None)
for _label, _bad in (("None", None), ("string", "x"), ("list", [1])):
    _al = _sum(stats=_bad, user_summary=_bad, sleep=_bad)["alerts"]
    check(f"P1.3 alerts: stats/user_summary/sleep as {_label} -> all None, no crash",
          all(v is None for v in _al.values()))
check("P1.3 alerts: an event that is no dict -> None",
      _sum(stats={"bodyBatteryDynamicFeedbackEvent": "HIGH"})["alerts"]["body_battery_level"] is None)

# acwr status: from the same device entry as the training status
def _p13_dev(entries):
    return _sum(training_status={"mostRecentTrainingStatus": {"latestTrainingStatusData": entries}})["alerts"]["acwr_status"]

check("P1.3 alerts.acwr_status: read from acuteTrainingLoadDTO of the device entry",
      _p13_dev({_P11_DEV: {"acuteTrainingLoadDTO": {"acwrStatus": "HIGH"}}}) == "HIGH")
check("P1.3 alerts.acwr_status: with two devices the one with the later timestamp, in either order",
      _p13_dev({"1": {"timestamp": 1000, "acuteTrainingLoadDTO": {"acwrStatus": "LOW"}},
                "2": {"timestamp": 2000, "acuteTrainingLoadDTO": {"acwrStatus": "HIGH"}}}) == "HIGH"
      and _p13_dev({"2": {"timestamp": 2000, "acuteTrainingLoadDTO": {"acwrStatus": "HIGH"}},
                    "1": {"timestamp": 1000, "acuteTrainingLoadDTO": {"acwrStatus": "LOW"}}}) == "HIGH")
_t = _sum(training_status={"mostRecentTrainingStatus": {"latestTrainingStatusData": {
    "1": {"timestamp": 1000, "trainingStatus": 1, "acuteTrainingLoadDTO": {"acwrStatus": "LOW"}},
    "2": {"timestamp": 2000, "trainingStatus": 7, "acuteTrainingLoadDTO": {"acwrStatus": "HIGH"}}}}})
check("P1.3 alerts.acwr_status: the training status and the acwr status come from the same device",
      [_t["training"]["training_status_code"], _t["alerts"]["acwr_status"]] == [7, "HIGH"])
check("P1.3 alerts.acwr_status: 'NONE' is a value", _p13_dev({_P11_DEV: {"acuteTrainingLoadDTO": {"acwrStatus": "NONE"}}}) == "NONE")
for _label, _v in (("no acuteTrainingLoadDTO", {_P11_DEV: {"trainingStatus": 4}}),
                   ("acuteTrainingLoadDTO empty", {_P11_DEV: {"acuteTrainingLoadDTO": {}}}),
                   ("acuteTrainingLoadDTO no dict", {_P11_DEV: {"acuteTrainingLoadDTO": "x"}}),
                   ("acwrStatus a number", {_P11_DEV: {"acuteTrainingLoadDTO": {"acwrStatus": 3}}}),
                   ("no device entry", {}), ("None", None)):
    check(f"P1.3 alerts.acwr_status: {_label} -> None", _p13_dev(_v) is None)

# the other sections do not change because of the alert fields
_with = _sum(stats={"stressQualifier": "CALM"}, user_summary={"totalSteps": 100, "abnormalHeartRateAlertsCount": 2})
_without = _sum(user_summary={"totalSteps": 100})
check("P1.3 alerts: the other sections are the same with and without alert fields",
      all(_with[k] == _without[k] for k in _without if k != "alerts"))

# counter-check: the same values in the old dict form are read, so the gap is the shape, not the keys
_p11_old = _sum(training_readiness={"score": 74, "level": "HIGH", "feedbackLong": "GOOD_TO_GO"},
                training_status={"latestTrainingStatus": 4},
                max_metrics={"generic": {"vo2MaxPreciseValue": 51.3}})["training"]
check("P1.1 counter-check: old dict forms still fill training",
      [_p11_old["readiness_score"], _p11_old["readiness_level"], _p11_old["readiness_feedback"],
       _p11_old["training_status"], _p11_old["vo2max"]] == [74, "HIGH", "GOOD_TO_GO", 4, 51.3])

summary()
