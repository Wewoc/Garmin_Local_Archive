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

summary()
