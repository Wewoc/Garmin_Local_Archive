#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_repair_predictions.py — garmin_repair_predictions and what it stands on
PREDICTION-REPAIR v1.7.6.10 — removable (see the module's removal list).

Covers: the call with the day and the reduction of its answer to the entry of the day (before v1.7.6.10 the endpoint was called
without a date: pinned Ist-Stand), garmin_normalizer.own_day_prediction (the net under it, applied by normalize()) and
its use in garmin_collector._fetch_and_assess (source/ keeps the answer as delivered), the field label
rule in assess_quality_fields, garmin_quality.record_field_labels, find_candidates / repair_predictions
on synthetic raw days (dry run, real run, second run, safety copy and way back, shared quality log,
stop, failures, a day that changed after the scan) and the scheduler hint.

Run from the project folder:
    python tests/test_repair_predictions.py

All data is synthetic; shared setup lives in gla_testenv.py.
"""

import copy
import importlib.util
import json
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from gla_testenv import cfg, _cfg_values, _isolated_log_env, _put_log, _day_raw  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_api as api
import garmin_collector as col
import garmin_migration_snapshot as snap
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

section("P. garmin_repair_predictions (v1.7.6.10)")
import garmin_repair_predictions as rp

_TODAY = date.today().isoformat()


class _Rec:
    """Stand-in for a module logger — keeps the messages per level."""
    def __init__(self):
        self.m = {"debug": [], "info": [], "warning": [], "error": []}

    def debug(self, s, *a, **k):
        self.m["debug"].append(s)

    def info(self, s, *a, **k):
        self.m["info"].append(s)

    def warning(self, s, *a, **k):
        self.m["warning"].append(s)

    def error(self, s, *a, **k):
        self.m["error"].append(s)


def _pred(cd, base=1500):
    """A prediction in the form the API delivers (field names of get_race_predictions)."""
    return {"userId": 4711, "calendarDate": cd, "fromCalendarDate": None, "toCalendarDate": None,
            "time5K": base, "time10K": base * 2 + 11, "timeHalfMarathon": base * 4 + 7, "timeMarathon": base * 9 + 3}


def _qe(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False,
            "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None,
            "fields": {"heart_rates": "medium", "race_predictions": "medium"}, **kw}


def _log(*dates):
    return {"first_day": "2025-06-01", "devices": [], "days": [_qe(d) for d in dates]}


def _raw_path(d):
    return cfg.RAW_DIR / f"garmin_raw_{d}.json"


def _put_raw(d, field="__absent__", **extra):
    """A raw day with a heart-rate block, steps, and the given race_predictions field."""
    raw = {"date": d, "heart_rates": {"restingHeartRate": 50, "heartRateValues": [[1, 60]]},
           "user_summary": {"totalSteps": 7000 + int(d[-2:])}, **extra}
    if field != "__absent__":
        raw["race_predictions"] = field
    _raw_path(d).parent.mkdir(parents=True, exist_ok=True)
    _raw_path(d).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


def _load_raw(d):
    return json.loads(_raw_path(d).read_text(encoding="utf-8"))


def _snap_dir(base):
    return base / "backup" / "migration"


def _zips(base):
    f = _snap_dir(base)
    return sorted(p.name for p in f.glob("*.zip")) if f.exists() else []


def _logbytes():
    return cfg.QUALITY_LOG_FILE.read_bytes()


def _bytes_of_raw():
    return {p.name: p.read_bytes() for p in sorted(cfg.RAW_DIR.glob("garmin_raw_*.json"))}


def _no_field(raw):
    return {k: v for k, v in raw.items() if k != "race_predictions"}


# ══════════════════════════════════════════════════════════════════════════════
#  0. The call: until v1.7.6.9 without a date (pinned Ist-Stand), since v1.7.6.10 with the day
# ══════════════════════════════════════════════════════════════════════════════
section("P0. The race predictions are asked for with the day (v1.7.6.10; before: without a date)")
_cl = MagicMock()
with patch("garmin_api.time.sleep"):
    api.fetch_raw(_cl, "2025-06-01")
check("P0 fetch_raw asks get_race_predictions(day, day, 'daily') — the call without arguments (Ist-Stand until v1.7.6.9, it answers "
      "with the current prediction dated with the day of the call) is gone",
      _cl.get_race_predictions.call_args_list == [(("2025-06-01", "2025-06-01", "daily"), {})])
check("P0 the other fourteen baseline endpoints are still called with the day only",
      all(getattr(_cl, m).call_args.args == ("2025-06-01",) for m in
          ("get_sleep_data", "get_stress_data", "get_body_battery", "get_heart_rates", "get_respiration_data",
           "get_spo2_data", "get_stats", "get_steps_data", "get_user_summary", "get_activities_fordate",
           "get_training_status", "get_training_readiness", "get_hrv_data", "get_max_metrics")))


def _fetch_with(answer, day="2025-06-01"):
    cl = MagicMock()
    cl.get_race_predictions.return_value = answer
    with patch("garmin_api.time.sleep"):
        return api.fetch_raw(cl, day)


_raw0, _failed0 = _fetch_with([_pred("2025-06-01")])
check("P0 the answer is a list with one entry per day: the entry of the day becomes the field (a dict, as the archive holds it)",
      _raw0["race_predictions"] == _pred("2025-06-01") and "race_predictions" not in _failed0)
_raw0, _failed0 = _fetch_with([])
check("P0 an empty list (the API holds no prediction for that day) leaves no field and is not a failed endpoint",
      "race_predictions" not in _raw0 and "race_predictions" not in _failed0)
_raw0, _ = _fetch_with([_pred("2025-05-31"), _pred("2025-06-01", 1777), _pred("2025-06-02")])
check("P0 of several entries only the one dated with the day is taken",
      _raw0["race_predictions"] == _pred("2025-06-01", 1777))
_raw0, _ = _fetch_with([_pred("2025-06-02")])
check("P0 entries of other days only: no field (nothing is filed under a day it does not belong to)",
      "race_predictions" not in _raw0)
_raw0, _ = _fetch_with([{"time5K": 1500}, "x", None, 7])
check("P0 an entry without a calendarDate, and entries that are no dict: no field", "race_predictions" not in _raw0)
_raw0, _ = _fetch_with(_pred("2025-06-02"))
check("P0 a dict answer (the shape of the call without a date) is passed on as it is: own_day_prediction judges it later",
      _raw0["race_predictions"]["calendarDate"] == "2025-06-02")
_raw0, _ = _fetch_with("garbage")
check("P0 an answer that is neither list nor dict: no field", "race_predictions" not in _raw0)
_cl3 = MagicMock()
_cl3.get_race_predictions.side_effect = RuntimeError("boom")
with patch("garmin_api.time.sleep"):
    _raw0, _failed0 = api.fetch_raw(_cl3, "2025-06-01")
check("P0 a failing call is a failed endpoint and leaves no field; the other endpoints are not affected",
      "race_predictions" in _failed0 and "race_predictions" not in _raw0 and "heart_rates" in _raw0
      and _failed0 == ["race_predictions"])
check("P0 _prediction_of_day is pure: the list is not changed",
      (lambda lst: (api._prediction_of_day(lst, "2025-06-01"), lst == [_pred("2025-06-01"), _pred("2025-06-02")])[1])
      ([_pred("2025-06-01"), _pred("2025-06-02")]))

# ══════════════════════════════════════════════════════════════════════════════
#  1. garmin_normalizer.own_day_prediction (moved from garmin_api in v1.7.6.10)
# ══════════════════════════════════════════════════════════════════════════════
section("P1. garmin_normalizer.own_day_prediction (moved from garmin_api, v1.7.6.10)")
_own = {"date": "2025-06-10", "steps": [1], "race_predictions": _pred("2025-06-10")}
_r, _dropped = normalizer.own_day_prediction(_own, "2025-06-10")
check("P1 a prediction dated the day itself is kept: the very same dict comes back, nothing dropped",
      _r is _own and _dropped is None)
_next = {"date": "2025-06-10", "steps": [1], "race_predictions": _pred("2025-06-11")}
_snapshot = copy.deepcopy(_next)
_r, _dropped = normalizer.own_day_prediction(_next, "2025-06-10")
check("P1 a prediction dated the next day is dropped, the other keys stay, the dropped one is returned",
      "race_predictions" not in _r and _r == {"date": "2025-06-10", "steps": [1]}
      and _dropped == _snapshot["race_predictions"])
check("P1 the argument is not changed (a shallow copy is returned)", _next == _snapshot and _r is not _next)
check("P1 a prediction dated an earlier day is dropped too (not only a later one)",
      "race_predictions" not in normalizer.own_day_prediction({"race_predictions": _pred("2025-06-09")}, "2025-06-10")[0])
_nodate = {"race_predictions": {"time5K": 1500, "timeMarathon": 14000}}
_r, _dropped = normalizer.own_day_prediction(_nodate, "2025-06-10")
check("P1 a prediction without a calendarDate is not kept either (nothing is guessed)",
      "race_predictions" not in _r and _dropped == {"time5K": 1500, "timeMarathon": 14000})
check("P1 a date that only looks alike (other format, a datetime) is not the day",
      "race_predictions" in normalizer.own_day_prediction({"race_predictions": _pred("2025-06-10")}, "2025-06-10")[0]
      and "race_predictions" not in normalizer.own_day_prediction({"race_predictions": _pred("2025-06-10T00:00:00")}, "2025-06-10")[0]
      and "race_predictions" not in normalizer.own_day_prediction({"race_predictions": _pred("20250610")}, "2025-06-10")[0])
for _label, _val in (("empty dict", {}), ("text", "abc"), ("list", [1]), ("None", None)):
    _x = {"date": "2025-06-10", "race_predictions": _val}
    _r, _dropped = normalizer.own_day_prediction(_x, "2025-06-10")
    check(f"P1 a field that is not a filled dict ({_label}) is left to the validator/assessment: same dict, nothing dropped",
          _r is _x and _dropped is None)
_x = {"date": "2025-06-10"}
check("P1 no field at all: same dict", normalizer.own_day_prediction(_x, "2025-06-10") == (_x, None))
check("P1 a raw that is no dict comes back as it is", normalizer.own_day_prediction(None, "2025-06-10") == (None, None)
      and normalizer.own_day_prediction([1], "2025-06-10") == ([1], None))

section("P1b. normalize(source='api') applies the rule to every day it builds (v1.7.6.10)")
_n_own = {"date": "2025-06-10", "steps": [1], "race_predictions": _pred("2025-06-10")}
check("P1b a day whose prediction is dated with it passes normalize() as the very same dict",
      normalizer.normalize(_n_own, source="api") is _n_own)
_n_foreign = {"date": "2025-06-10", "steps": [1], "race_predictions": _pred("2025-06-11")}
_n_snap = copy.deepcopy(_n_foreign)
_n_out = normalizer.normalize(_n_foreign, source="api")
check("P1b a prediction dated another day is left out (a copy without the key, the argument is not changed)",
      "race_predictions" not in _n_out and _n_out == {"date": "2025-06-10", "steps": [1]} and _n_foreign == _n_snap)
check("P1b without a usable date of the day nothing is judged: no date, an invalid date, a datetime, a number, a text that only looks alike",
      all("race_predictions" in normalizer.normalize({"date": dd, "race_predictions": _pred("2025-06-11")}, source="api")
          for dd in ("unknown", "2025-13-40", "2025-06-10T00:00:00", 20250610, None, "10.06.2025", "2025-6-10"))
      and "race_predictions" in normalizer.normalize({"race_predictions": _pred("2025-06-11")}, source="api"))
check("P1b a leap day is a date, 2025-02-29 is none",
      "race_predictions" not in normalizer.normalize({"date": "2024-02-29", "race_predictions": _pred("2024-03-01")}, source="api")
      and "race_predictions" in normalizer.normalize({"date": "2025-02-29", "race_predictions": _pred("2025-03-01")}, source="api"))
check("P1b the import side is not touched: source='bulk' keeps whatever the day holds (the export's prediction carries the day's date by construction)",
      "race_predictions" in normalizer.normalize({"date": "2025-06-10", "race_predictions": _pred("2025-06-11")}, source="bulk"))
check("P1b a non-dict is still an empty day, an unknown source still passes through",
      normalizer.normalize(None, source="api") == {"date": "unknown"}
      and normalizer.normalize({"date": "2025-06-10", "race_predictions": _pred("2025-06-11")}, source="x")["race_predictions"])

# ══════════════════════════════════════════════════════════════════════════════
#  2. _fetch_and_assess keeps source/ as delivered and the day without the foreign prediction
# ══════════════════════════════════════════════════════════════════════════════
section("P2. _fetch_and_assess")


def _fetch_day(date_str, prediction):
    raw = _day_raw(date_str, "high")
    if prediction is not None:
        raw["race_predictions"] = prediction
    seen = {}

    def _write_source(raw_data, d, force=False):
        seen["source"] = copy.deepcopy(raw_data)
        return True

    with patch("garmin_collector.api.fetch_raw", return_value=(raw, [])), \
            patch("garmin_source_writer.write_source", side_effect=_write_source), \
            patch("garmin_source_writer.update_log"):
        out = col._fetch_and_assess(MagicMock(), date_str)
    return out, seen


with _isolated_log_env("rp_fetch") as _b:
    (_lab, _norm, _sm, _flds, _val), _seen = _fetch_day("2025-06-10", _pred("2025-06-11"))
    check("P2 a prediction dated the next day: source/ is written WITH it (as delivered), the normalized day has none",
          _seen["source"]["race_predictions"]["calendarDate"] == "2025-06-11" and "race_predictions" not in _norm)
    check("P2 the day is still assessed and its field label is failed (no prediction of the day)",
          _lab in ("high", "standard") and _flds["race_predictions"] == "failed")
    (_lab, _norm, _sm, _flds, _val), _seen = _fetch_day("2025-06-10", _pred("2025-06-10"))
    check("P2 a prediction dated the day itself is filed under it and counts: medium",
          _norm["race_predictions"]["calendarDate"] == "2025-06-10" and _flds["race_predictions"] == "medium")
    (_lab, _norm, _sm, _flds, _val), _seen = _fetch_day("2025-06-10", None)
    check("P2 an answer without the field: no field, label failed (as before)",
          "race_predictions" not in _norm and _flds["race_predictions"] == "failed")

# ══════════════════════════════════════════════════════════════════════════════
#  3. Field label rule in assess_quality_fields
# ══════════════════════════════════════════════════════════════════════════════
section("P3. assess_quality_fields — race_predictions")


def _lab(raw):
    return quality.assess_quality_fields(raw)["race_predictions"]


check("P3 a prediction with the day's own date -> medium",
      _lab({"date": "2025-06-10", "race_predictions": _pred("2025-06-10")}) == "medium")
check("P3 a filled prediction dated another day -> failed (it used to be medium)",
      _lab({"date": "2025-06-10", "race_predictions": _pred("2025-06-11")}) == "failed"
      and _lab({"date": "2025-06-10", "race_predictions": _pred("2025-06-09")}) == "failed")
check("P3 a filled dict without a calendarDate -> failed", _lab({"date": "2025-06-10", "race_predictions": {"time5K": 1}}) == "failed")
check("P3 a raw without a date can never match -> failed",
      _lab({"race_predictions": _pred("2025-06-10")}) == "failed" and _lab({"race_predictions": {"calendarDate": None}}) == "failed")
check("P3 empty dict, text, list, None, missing -> failed (unchanged)",
      all(_lab({"date": "2025-06-10", "race_predictions": v}) == "failed" for v in ({}, "abc", [1], None))
      and _lab({"date": "2025-06-10"}) == "failed")
check("P3 the other thirteen fields are not touched by the rule (steps/stats still graded as before)",
      quality.assess_quality_fields({"date": "2025-06-10", "stats": {"totalSteps": 5}})["steps"] == "medium")

# ══════════════════════════════════════════════════════════════════════════════
#  4. quality.record_field_labels
# ══════════════════════════════════════════════════════════════════════════════
section("P4. record_field_labels")
_q = {"first_day": "2025-06-01", "devices": [], "days": [
    _qe("2025-06-01"), _qe("2025-06-02", fields={"heart_rates": "high"}), _qe("2025-06-03", fields=None),
    _qe("2025-06-04")]}
_q["days"][2].pop("fields")
_sum_before = quality._compute_checksum(copy.deepcopy(_q))
_res = quality.record_field_labels(_q, {"2025-06-01": "failed", date(2025, 6, 2): "medium", "2025-06-03": "failed",
                                        "2025-06-09": "failed", "2025-06-04": "great"}, "race_predictions")
_by = {e["date"]: e for e in _q["days"]}
check("P4 sets the label of ONE field: an ISO string and a date object both work",
      _by["2025-06-01"]["fields"] == {"heart_rates": "medium", "race_predictions": "failed"}
      and _by["2025-06-02"]["fields"] == {"heart_rates": "high", "race_predictions": "medium"})
check("P4 never creates: a day without an entry, an entry without a fields dict and an unknown label are skipped and counted",
      _res == {"set": 2, "skipped_no_entry": 1, "skipped_no_fields": 1, "skipped_bad_label": 1}
      and "fields" not in _by["2025-06-03"] and _by["2025-06-04"]["fields"]["race_predictions"] == "medium")
check("P4 nothing else changes: quality, source, write, last_checked, and the checksum of the log",
      _by["2025-06-01"]["last_checked"] == "2024-01-01" and _by["2025-06-01"]["quality"] == "standard"
      and quality._compute_checksum(_q) == _sum_before)
check("P4 an empty field name changes nothing",
      quality.record_field_labels(_q, {"2025-06-01": "high"}, "")["set"] == 0 and _by["2025-06-01"]["fields"]["race_predictions"] == "failed")
check("P4 it is a public name of the facade", callable(quality.record_field_labels))

# ══════════════════════════════════════════════════════════════════════════════
#  5. find_candidates
# ══════════════════════════════════════════════════════════════════════════════
section("P5. find_candidates")
_PA, _PE = _pred("2025-06-05", 1500), _pred("2025-06-12", 1600)
_PB_OWN, _PB_COPY = _pred("2025-06-09", 1700), _pred("2025-06-09", 1700)
_PC, _PD1, _PD2 = _pred("2025-06-20", 1800), _pred("2025-06-11", 1900), _pred("2025-06-11", 1950)


def _scenario(base):
    """Raw days: copies of P_A on 06-01..03, 06-05 carries a copy of P_B, 06-09 has its own, ..."""
    cfg.SUMMARY_DIR = base / "summary"
    _put_raw("2025-06-01", _PA)
    _put_raw("2025-06-02", _PA)
    _put_raw("2025-06-03", _PA)
    _put_raw("2025-06-04", _PB_COPY)
    _put_raw("2025-06-05", _PB_COPY)                         # the day of P_A carries a copy of P_B
    _put_raw("2025-06-06", _PD1)                             # two copies of 06-11 that differ ...
    _put_raw("2025-06-07", _PD2)
    _put_raw("2025-06-08", {"time5K": 1500, "timeMarathon": 14000})   # no calendarDate
    _put_raw("2025-06-09", _PB_OWN)                          # correct
    _put_raw("2025-06-10", _PC)                              # P_C belongs to 06-20: no raw day
    _put_raw("2025-06-11")                                   # no field (target of the differing copies)
    _put_raw("2025-06-12")                                   # no field (target of P_E)
    _put_raw("2025-06-13", {})                               # empty field: ignored
    _put_raw("2025-06-15", _PE)                              # copy of P_E
    _raw_path("2025-06-14").write_text("{broken", encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_notadate.json").write_text(json.dumps({"race_predictions": _PA}), encoding="utf-8")
    _put_log(_log(*[f"2025-06-{n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15)]))


with _isolated_log_env("rp_find") as _b:
    check("P5 no raw folder -> nothing found",
          rp.find_candidates() == {"set": {}, "remove": [], "kept": 0, "conflict": [], "waiting": [], "undated": [], "replaced": []})
    _scenario(_b)
    _f = rp.find_candidates()
    check("P5 the prediction of 06-05 goes to its own day (06-05, replacing the copy of P_B it carries), P_E to 06-12 (no field yet)",
          _f["set"] == {"2025-06-05": _PA, "2025-06-12": _PE})
    check("P5 the copies are removed: 06-01..04 and 06-15 (06-05 is replaced, not removed)",
          _f["remove"] == ["2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-15"])
    check("P5 a day whose field already has its own date is kept and not touched (06-09: its own value is not replaced)",
          _f["kept"] == 1 and "2025-06-09" not in _f["set"] and "2025-06-09" not in _f["remove"])
    check("P5 differing copies of one date: reported as conflict, carriers untouched, nothing placed on 06-11",
          _f["conflict"] == ["2025-06-11"] and "2025-06-11" not in _f["set"]
          and "2025-06-06" not in _f["remove"] and "2025-06-07" not in _f["remove"])
    check("P5 a carrier of a date without a raw day waits (06-10), a field without a usable date is undated (06-08); both untouched",
          _f["waiting"] == ["2025-06-10"] and _f["undated"] == ["2025-06-08"]
          and "2025-06-10" not in _f["remove"] and "2025-06-08" not in _f["remove"])
    check("P5 empty field, missing field, a broken file and a bad file name are ignored",
          all(d not in list(_f["set"]) + _f["remove"] + _f["waiting"] + _f["undated"] for d in ("2025-06-13", "2025-06-14", "notadate")))
    _before = _bytes_of_raw()
    rp.find_candidates()
    check("P5 it only looks: no raw file changes, none is added", _bytes_of_raw() == _before)
    _other = _b / "other_raw"
    _other.mkdir()
    (_other / "garmin_raw_2025-07-02.json").write_text(json.dumps({"date": "2025-07-02", "race_predictions": _pred("2025-07-03")}), encoding="utf-8")
    (_other / "garmin_raw_2025-07-03.json").write_text(json.dumps({"date": "2025-07-03"}), encoding="utf-8")
    check("P5 an explicit folder is looked at, not the configured one",
          rp.find_candidates(raw_dir=_other)["set"] == {"2025-07-03": _pred("2025-07-03")}
          and rp.find_candidates(raw_dir=_other)["remove"] == ["2025-07-02"])
    check("P5 an explicit folder that is missing finds nothing and does not fail",
          rp.find_candidates(raw_dir=_b / "nowhere")["set"] == {})

with _isolated_log_env("rp_find2") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put_raw("2025-08-01", _pred("2025-08-03", 1500))
    _put_raw("2025-08-02", _pred("2025-08-03", 1500))
    _put_raw("2025-08-03", _pred("2025-08-04", 1500))
    _put_raw("2025-08-04")
    _f = rp.find_candidates()
    check("P5 two identical copies of one date are no conflict: placed once on its day, both copies go; the day that carried "
          "another day's copy is the target of the first",
          _f["set"] == {"2025-08-03": _pred("2025-08-03", 1500), "2025-08-04": _pred("2025-08-04", 1500)}
          and _f["remove"] == ["2025-08-01", "2025-08-02"] and _f["conflict"] == [])

with _isolated_log_env("rp_find3") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put_raw("2025-09-01", _pred("2025-09-02", 1500))          # the prediction of 09-02 ...
    _put_raw("2025-09-02", _pred("2025-09-09", 1600))          # ... whose day carries one for 09-09, a day without a raw file
    _put_raw("2025-09-04", _pred("2025-09-05", 1700))          # the prediction of 09-05 ...
    _put_raw("2025-09-05", {"time5K": 1800})                   # ... whose day carries one without a date
    _put_raw("2025-09-06", _pred("2025-09-08", 1900))          # two differing copies of 09-08 ...
    _put_raw("2025-09-07", _pred("2025-09-08", 1950))
    _put_raw("2025-09-03", _pred("2025-09-06", 2000))          # ... and the prediction of 09-06 sits on 09-03
    _put_raw("2025-09-08")
    _f = rp.find_candidates()
    check("P5 an unsettled carrier (waiting / undated / differing copies) that is itself the target of another prediction gets "
          "that prediction, and is listed as replaced — what it carried is not silently lost",
          _f["set"] == {"2025-09-02": _pred("2025-09-02", 1500), "2025-09-05": _pred("2025-09-05", 1700),
                        "2025-09-06": _pred("2025-09-06", 2000)}
          and _f["replaced"] == ["2025-09-02", "2025-09-05", "2025-09-06"])
    check("P5 and those days are no longer listed as waiting / undated; the copies that nobody can place stay (09-07 keeps its "
          "copy, the date 09-08 is still a conflict); the donors of the settled predictions go",
          _f["waiting"] == [] and _f["undated"] == [] and _f["conflict"] == ["2025-09-08"]
          and "2025-09-07" not in _f["remove"] and _f["remove"] == ["2025-09-01", "2025-09-03", "2025-09-04"])
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _put_log(_log(*[f"2025-09-{n:02d}" for n in range(1, 9)]))
        _rec = _Rec()
        with patch.object(rp, "log", _rec):
            _r = rp.repair_predictions()
    check("P5 the run reports each replaced day (warning, names the day and that the answer stays in source/), counts it in the result "
          "and stores the prediction of the day's own date",
          _r["replaced"] == ["2025-09-02", "2025-09-05", "2025-09-06"]
          and sum(1 for m in _rec.m["warning"] if "cannot be placed" in m and "source/" in m) == 3
          and _load_raw("2025-09-02")["race_predictions"]["calendarDate"] == "2025-09-02" and _r["failed"] == 0)

# ══════════════════════════════════════════════════════════════════════════════
#  6. repair_predictions
# ══════════════════════════════════════════════════════════════════════════════
section("P6. repair_predictions")

with _isolated_log_env("rp_run") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario(_b)
        _bytes_before, _log_before = _bytes_of_raw(), _logbytes()
        _r = rp.repair_predictions(dry_run=True)
        check("P6 dry run: reports what would happen, writes nothing (raw and log byte-identical, no safety copy, no summary)",
              (_r["set"], _r["removed"], _r["failed"], _r["kept"]) == (2, 5, 0, 1)
              and _bytes_of_raw() == _bytes_before and _logbytes() == _log_before and _zips(_b) == []
              and not cfg.SUMMARY_DIR.exists())
        check("P6 dry run reports what stays untouched too",
              _r["conflict"] == ["2025-06-11"] and _r["waiting"] == ["2025-06-10"] and _r["undated"] == ["2025-06-08"])

        _raw_before = {d: _load_raw(d) for d in (f"2025-06-{n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15))}
        _lock_seen = []
        _real_wd = writer.write_day

        def _wd(n, s, d):
            _lock_seen.append(quality.QUALITY_LOCK.locked())
            return _real_wd(n, s, d)

        _rec = _Rec()
        with patch.object(writer, "write_day", side_effect=_wd), \
                patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv, \
                patch.object(rp, "log", _rec):
            _r = rp.repair_predictions()
        check("P6 the real run: 2 days got their own prediction, 5 lost a copy, none failed",
              (_r["set"], _r["removed"], _r["failed"]) == (2, 5, 0) and _r["stopped"] is False)
        check("P6 06-05 and 06-12 now hold exactly the prediction dated with them; the copies are gone (field removed)",
              _load_raw("2025-06-05")["race_predictions"] == _PA and _load_raw("2025-06-12")["race_predictions"] == _PE
              and all("race_predictions" not in _load_raw(d) for d in
                      ("2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-15")))
        check("P6 only that field changed on the changed days: every other key is exactly as it was",
              all(_no_field(_load_raw(d)) == _no_field(_raw_before[d]) for d in
                  ("2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05", "2025-06-12", "2025-06-15")))
        check("P6 the days that stay untouched are byte-identical: own prediction (06-09), differing copies, waiting, undated, empty, no field",
              all(_bytes_before[f"garmin_raw_{d}.json"] == _raw_path(d).read_bytes() for d in
                  ("2025-06-06", "2025-06-07", "2025-06-08", "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-13", "2025-06-14")))
        check("P6 summaries are written for the seven changed days only (through write_day)",
              sorted(p.name for p in cfg.SUMMARY_DIR.glob("*.json")) == [f"garmin_2025-06-{n:02d}.json" for n in (1, 2, 3, 4, 5, 12, 15)])
        check("P6 write_day ran under one continuous QUALITY_LOCK hold, once per changed day; the log was saved exactly once",
              _lock_seen == [True] * 7 and _sv.call_count == 1)
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("P6 the label follows in the quality log: medium where the day's own prediction is now stored, failed where the field is gone",
              all(_by[d]["fields"]["race_predictions"] == "medium" for d in ("2025-06-05", "2025-06-12"))
              and all(_by[d]["fields"]["race_predictions"] == "failed" for d in
                      ("2025-06-01", "2025-06-02", "2025-06-03", "2025-06-04", "2025-06-15")))
        check("P6 last_checked is set on the changed days (the MCP cache reads them again), not on the others",
              all(_by[d]["last_checked"] == _TODAY for d in ("2025-06-01", "2025-06-05", "2025-06-12", "2025-06-15"))
              and all(_by[d]["last_checked"] == "2024-01-01" for d in
                      ("2025-06-06", "2025-06-07", "2025-06-08", "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-13")))
        check("P6 untouched days keep their label as it was; quality, source, write and the other labels stay everywhere",
              all(_by[d]["fields"]["race_predictions"] == "medium" for d in
                  ("2025-06-06", "2025-06-07", "2025-06-08", "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-13"))
              and all(e["quality"] == "standard" and e["write"] is True and e["fields"]["heart_rates"] == "medium"
                      for e in _by.values()))
        check("P6 what stays untouched is warned about / reported",
              any("2025-06-11" in m and "differs" in m for m in _rec.m["warning"])
              and any("2025-06-08" in m and "without a usable date" in m for m in _rec.m["warning"])
              and any("1 day(s) carry a prediction of a day that has no raw file yet" in m for m in _rec.m["info"])
              and not _rec.m["error"])
        check("P6 one safety copy of raw/ and the quality log, a valid migration_*.zip that holds the days as they were",
              len(_zips(_b)) == 1 and _zips(_b)[0].startswith("migration_") and snap.verify_snapshot(_snap_dir(_b) / _zips(_b)[0])["ok"]
              and _r["safety_copy"] == _zips(_b)[0])
        with zipfile.ZipFile(_snap_dir(_b) / _zips(_b)[0]) as _zf:
            _names = set(_zf.namelist())
            _old1 = json.loads(_zf.read("raw/garmin_raw_2025-06-01.json"))
        check("P6 the copy holds the raw files and the log (no summary), and 06-01 in it still carries the copy that was removed",
              "log/quality_log.json" in _names and "MANIFEST.json" in _names and "raw/garmin_raw_2025-06-05.json" in _names
              and not any(n.startswith("summary/") for n in _names) and _old1["race_predictions"] == _PA)

        _after_bytes, _after_log = _bytes_of_raw(), _logbytes()
        _r2 = rp.repair_predictions()
        check("P6 a second run changes nothing: 0 / 0, raw and log byte-identical, no second safety copy",
              (_r2["set"], _r2["removed"], _r2["failed"]) == (0, 0, 0) and _bytes_of_raw() == _after_bytes
              and _logbytes() == _after_log and len(_zips(_b)) == 1)
        check("P6 find_candidates after the repair finds nothing to do", rp.find_candidates()["set"] == {}
              and rp.find_candidates()["remove"] == [])

        # the waiting day: when 06-20 exists, the next run places P_C there and removes the copy on 06-10
        _put_raw("2025-06-20")
        with quality.QUALITY_LOCK:
            _q = quality._load_quality_log()
            _q["days"].append(_qe("2025-06-20", fields={"heart_rates": "medium", "race_predictions": "failed"}))
            quality._save_quality_log(_q)
        _f = rp.find_candidates()
        check("P6 once the raw day of the waiting date exists, the next scan offers it: placed on 06-20, the copy on 06-10 goes",
              _f["set"] == {"2025-06-20": _PC} and _f["remove"] == ["2025-06-10"] and _f["waiting"] == [])
        _r3 = rp.repair_predictions()
        check("P6 and the run does it (a second safety copy, one more day each way)",
              (_r3["set"], _r3["removed"], _r3["failed"]) == (1, 1, 0) and _load_raw("2025-06-20")["race_predictions"] == _PC
              and "race_predictions" not in _load_raw("2025-06-10") and len(_zips(_b)) == 2)

        # the way back
        _zname = _r["safety_copy"]
        _res = snap.restore_snapshot(_snap_dir(_b) / _zname)
        check("P6 way back: the raw days are as before the repair (06-01 carries the copy again, 06-05 the copy of P_B)",
              _res["ok"] is True and _load_raw("2025-06-01")["race_predictions"] == _PA
              and _load_raw("2025-06-05")["race_predictions"] == _PB_COPY)
        check("P6 after the way back the repair can run again (nothing was lost)", rp.repair_predictions()["set"] >= 2)

with _isolated_log_env("rp_shared") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario(_b)
        _shared = quality._load_quality_log()
        with patch.object(quality, "_load_quality_log", wraps=quality._load_quality_log) as _ld, \
                patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
            _r = rp.repair_predictions(quality_data=_shared)
        check("P6 shared quality log: the caller's object gets labels and last_checked, it is not loaded again, "
              "exactly that object is saved once",
              (_r["set"], _r["removed"]) == (2, 5) and _ld.call_count == 0 and _sv.call_count == 1
              and _sv.call_args.args[0] is _shared
              and {e["date"]: e["fields"]["race_predictions"] for e in _shared["days"]}["2025-06-05"] == "medium"
              and {e["date"]: e["fields"]["race_predictions"] for e in _shared["days"]}["2025-06-01"] == "failed"
              and {e["date"]: e["last_checked"] for e in _shared["days"]}["2025-06-01"] == _TODAY)

with _isolated_log_env("rp_fail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario(_b)
        _b4raw, _b4log = _bytes_of_raw(), _logbytes()
        _rec = _Rec()
        with patch.object(rp, "log", _rec), patch.object(snap, "create_snapshot",
                                                         return_value={"ok": False, "path": None, "reason": "disk full"}):
            _r = rp.repair_predictions()
        check("P6 no safety copy, no write: failed 1 with the reason, raw and log byte-identical, an error is logged",
              _r["failed"] == 1 and _r["reason"] == "disk full" and _bytes_of_raw() == _b4raw and _logbytes() == _b4log
              and any("no safety copy" in m for m in _rec.m["error"]))
        with patch.object(snap, "create_snapshot", return_value={"ok": True, "path": None, "reason": "nothing"}):
            _r = rp.repair_predictions()
        check("P6 a snapshot call that is ok but made no file counts as no copy (nothing written)",
              _r["failed"] == 1 and _bytes_of_raw() == _b4raw)

        _r = rp.repair_predictions(should_stop=lambda: True)
        check("P6 a stop before the write: nothing is written, no safety copy, stopped is reported",
              _r["stopped"] is True and _bytes_of_raw() == _b4raw and _zips(_b) == [])

        _flag, _real_wd = [], writer.write_day

        def _wd_stop(n, s, d):
            ok = _real_wd(n, s, d)
            _flag.append(1)
            return ok

        with patch.object(writer, "write_day", side_effect=_wd_stop):
            _r = rp.repair_predictions(should_stop=lambda: bool(_flag))
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("P6 a stop during the loop ends it after the current day; the written day is recorded in the log, the others are not",
              _r["stopped"] is True and (_r["set"], _r["removed"]) == (0, 1)
              and "race_predictions" not in _load_raw("2025-06-01") and _by["2025-06-01"]["fields"]["race_predictions"] == "failed"
              and _by["2025-06-01"]["last_checked"] == _TODAY
              and _load_raw("2025-06-02")["race_predictions"] == _PA and _by["2025-06-02"]["fields"]["race_predictions"] == "medium"
              and _by["2025-06-02"]["last_checked"] == "2024-01-01")

with _isolated_log_env("rp_wfail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario(_b)
        _real_wd = writer.write_day
        _bad_before = _raw_path("2025-06-03").read_bytes()
        _rec = _Rec()
        with patch.object(writer, "write_day", side_effect=lambda n, s, d: False if d == "2025-06-03" else _real_wd(n, s, d)), \
                patch.object(rp, "log", _rec):
            _r = rp.repair_predictions()
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("P6 a day that cannot be written is counted as failed and never stops the loop; the others are done",
              _r["failed"] == 1 and (_r["set"], _r["removed"]) == (2, 4) and any("2025-06-03" in m for m in _rec.m["error"]))
        check("P6 the failed day stays as it was (file and label), so it is found again at the next start",
              _raw_path("2025-06-03").read_bytes() == _bad_before and _by["2025-06-03"]["fields"]["race_predictions"] == "medium"
              and "2025-06-03" in rp.find_candidates()["remove"])
        with patch.object(quality, "_save_quality_log", return_value=False), patch.object(rp, "log", _Rec()):
            _put_raw("2025-06-30", _pred("2025-06-12", 1600))
            _r = rp.repair_predictions()
        check("P6 a log that cannot be saved is a failure with its reason (not silent)",
              _r["failed"] >= 1 and _r.get("reason") == "the quality log could not be saved")

with _isolated_log_env("rp_changed") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario(_b)
        _plan = {"set": {"2025-06-09": _pred("2025-06-09", 4000)}, "remove": ["2025-06-12"], "kept": 0,
                 "conflict": [], "waiting": [], "undated": [], "replaced": []}
        _b4raw = _bytes_of_raw()
        with patch.object(rp, "find_candidates", return_value=_plan):
            _r = rp.repair_predictions()
        check("P6 a day that changed after the scan is re-checked: one that has its own prediction now is not overwritten, "
              "one that has no copy any more is not rewritten",
              (_r["set"], _r["removed"], _r["failed"]) == (0, 0, 0) and _bytes_of_raw() == _b4raw)

# ══════════════════════════════════════════════════════════════════════════════
#  7. Scheduler hint — scheduler/daily_update.py::_check_prediction_repair
# ══════════════════════════════════════════════════════════════════════════════
section("P7. Scheduler hint")
_du_spec = importlib.util.spec_from_file_location(
    "daily_update_rp", Path(__file__).resolve().parent.parent / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)

with _isolated_log_env("rp_sched") as _b:
    _arch = _b / "archive"
    _raw_dir = _arch / "garmin_data" / "raw"
    _raw_dir.mkdir(parents=True)
    for _d, _f_ in (("2025-06-01", _pred("2025-06-02")), ("2025-06-02", None), ("2025-06-03", _pred("2025-06-03")),
                    ("2025-06-04", _pred("2025-06-09"))):
        _x = {"date": _d, **({"race_predictions": _f_} if _f_ else {})}
        (_raw_dir / f"garmin_raw_{_d}.json").write_text(json.dumps(_x), encoding="utf-8")
    _before = {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()}
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n = _du._check_prediction_repair(_arch)
    check("P7 counts the days that can be corrected (06-02 gets the prediction of its date, 06-01 loses its copy; 06-04 waits and "
          "is not counted) and warns with the number, nothing else",
          _n == 2 and _rec.m["warning"] == [
              "  2 day(s) carry a race prediction that belongs to another day.",
              "  Open the app and run Sync Garmin once to correct them (a safety copy is made first)."]
          and not _rec.m["error"])
    check("P7 it only looks: no file of the archive changes, none is added",
          {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()} == _before)
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n_none = _du._check_prediction_repair(_b / "no_archive_here")
    check("P7 no archive folder -> 0 and no warning", _n_none == 0 and not _rec.m["warning"])
    _rec = _Rec()
    with patch.object(_du, "log", _rec), patch.object(rp, "find_candidates", side_effect=RuntimeError("boom")):
        _n_err = _du._check_prediction_repair(_arch)
    check("P7 an error in the scan never stops the run: 0, no warning, no error", _n_err == 0 and not _rec.m["warning"] and not _rec.m["error"])

summary()
