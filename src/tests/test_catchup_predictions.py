#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_catchup_predictions.py — garmin_catchup_predictions (the catch-up of race predictions from Garmin)
PREDICTION-CATCHUP v1.7.6.11.2 — removable (see the module's removal list).

Covers: find_candidates (what counts as a candidate: no field, an entry in the quality log, not given up; the basis
rule; foreign copies and own predictions are left alone), the planning of the range calls (365 days, newest first,
gaps cost nothing), catch_up against a stand-in for the Garmin client that answers a range the way the real API does
(one entry per day, the bounds of the range in fromCalendarDate/toCalendarDate): dry run, the real run (raw/ + summary/
+ source/ + labels + marks), a second run, the safety copy and the way back, a prediction that differs from Garmin's
(kept), the start of Garmin's history found from the answers, an account without predictions, a failing call, a stop,
a write that fails, a day that changed during the calls, the shared quality log, and the scheduler hint.
Also: garmin_quality.record_field_given_up lives in test_quality.py (it stays when the catch-up is removed).

Run from the project folder:
    python tests/test_catchup_predictions.py

All data is synthetic; shared setup lives in gla_testenv.py.
"""

import importlib.util
import json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _cfg_values, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_migration_snapshot as snap
import garmin_quality as quality
import garmin_source_writer as sw
import garmin_writer as writer

section("C. garmin_catchup_predictions (v1.7.6.11.2)")
import garmin_catchup_predictions as cp

_TODAY = date.today().isoformat()
_SRC = Path(__file__).resolve().parent.parent


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


def _stored(d, base=1500):
    """The entry as the catch-up stores it: the bounds of the range replaced by the day."""
    return {**_pred(d, base), "fromCalendarDate": d, "toCalendarDate": d}


class _Garmin:
    """Stand-in for the garminconnect client: answers get_race_predictions(start, end, "daily") like the real API did in the
    probes — one entry per day that Garmin holds, fromCalendarDate/toCalendarDate carry the bounds of the range."""
    def __init__(self, held, fail_on=None, hook=None, extra=(), extra_calls=None):
        self.held, self.fail_on, self.hook, self.extra, self.calls = held, fail_on, hook, list(extra), []
        self.extra_calls = extra_calls                    # numbers (1-based) of the calls that get the extra entries; None = all

    def get_race_predictions(self, start, end, kind):
        self.calls.append((start, end, kind))
        if self.hook is not None:
            self.hook(len(self.calls))
        if self.fail_on == len(self.calls):
            raise RuntimeError("boom")
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        out = []
        for i in range((d1 - d0).days + 1):
            d = (d0 + timedelta(days=i)).isoformat()
            if d in self.held:
                out.append({**_pred(d, self.held[d]), "fromCalendarDate": start, "toCalendarDate": end})
        return out + (self.extra if self.extra_calls is None or len(self.calls) in self.extra_calls else [])


def _run(client, **kw):
    with patch("garmin_api.time.sleep"):
        return cp.catch_up(client, **kw)


def _qe(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False,
            "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None,
            "fields": {"heart_rates": "medium", "race_predictions": "failed"}, **kw}


def _raw_path(d):
    return cfg.RAW_DIR / f"garmin_raw_{d}.json"


def _put_raw(d, field="__absent__"):
    raw = {"date": d, "heart_rates": {"restingHeartRate": 50, "heartRateValues": [[1, 60]]},
           "user_summary": {"totalSteps": 7000 + int(d[-2:])}}
    if field != "__absent__":
        raw["race_predictions"] = field
    _raw_path(d).parent.mkdir(parents=True, exist_ok=True)
    _raw_path(d).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


def _load_raw(d):
    return json.loads(_raw_path(d).read_text(encoding="utf-8"))


def _bytes_of_raw():
    return {p.name: p.read_bytes() for p in sorted(cfg.RAW_DIR.glob("garmin_raw_*.json"))}


def _logbytes():
    return cfg.QUALITY_LOG_FILE.read_bytes()


def _snap_dir(base):
    return base / "backup" / "migration"


def _zips(base):
    f = _snap_dir(base)
    return sorted(p.name for p in f.glob("*.zip")) if f.exists() else []


def _no_field(raw):
    return {k: v for k, v in raw.items() if k != "race_predictions"}


def _by():
    return {e["date"]: e for e in quality._load_quality_log()["days"]}


_NOFIELD1 = ["2025-03-01", "2025-03-02", "2025-03-03", "2025-03-14", "2025-03-15", "2025-03-17", "2025-03-20",
             "2025-03-23", "2025-03-24", "2025-03-25"]


def _scenario1(base):
    """
    A raw archive of 17 days around the start of Garmin's history (2025-03-15):
      no field, candidates (10)   03-01 03-02 03-03 03-14 (before the history) 03-15 03-17 03-20 03-23 (attempts 1) 03-24 03-25 (a hole)
      own prediction (3)          03-16 (differs from Garmin in one value) 03-19 (differs in all) 03-26 (same)
      foreign copy                03-18 (a copy dated 03-19)
      no entry in the quality log 03-21 (no candidate)
      given up before             03-22 (attempts 2)
    Garmin holds every day from 03-15 to 03-31 except 03-25. 03-17 has a source file, 03-15 has none.
    """
    for d in _NOFIELD1 + ["2025-03-21", "2025-03-22"]:
        _put_raw(d)
    _put_raw("2025-03-16", {**_pred("2025-03-16", 1500), "timeMarathon": 1})      # differs from Garmin in one value only
    _put_raw("2025-03-19", _pred("2025-03-19", 1600))
    _put_raw("2025-03-26", _pred("2025-03-26", 1500))
    _put_raw("2025-03-18", _pred("2025-03-19", 1600))
    days = []
    for d in sorted(p.stem[len("garmin_raw_"):] for p in cfg.RAW_DIR.glob("garmin_raw_*.json")):
        if d == "2025-03-21":
            continue
        e = _qe(d)
        if d in ("2025-03-16", "2025-03-19", "2025-03-26"):
            e["fields"]["race_predictions"] = "medium"
        if d == "2025-03-22":
            e["field_backfill_attempts"] = {"race_predictions": 2}
        if d == "2025-03-23":
            e["field_backfill_attempts"] = {"race_predictions": 1, "steps": 1}
        days.append(e)
    _put_log({"first_day": "2025-03-01", "devices": [], "days": days})
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.SOURCE_DIR / "garmin_source_2025-03-17.json").write_text(
        json.dumps({"date": "2025-03-17", "user_summary": {"totalSteps": 1}}), encoding="utf-8")
    held = {(date(2025, 3, 15) + timedelta(days=i)).isoformat(): 1400 + i for i in range(17)}
    del held["2025-03-25"]
    held["2025-03-16"], held["2025-03-26"], held["2025-03-19"] = 1500, 1500, 1700
    return held


# ══════════════════════════════════════════════════════════════════════════════
#  0. Constants
# ══════════════════════════════════════════════════════════════════════════════
section("C0. Constants")
_ctrl = re.search(r"FIELD_BACKFILL_ATTEMPT_LIMIT\s*=\s*(\d+)", (_SRC / "app" / "garmin_app_controller.py").read_text(encoding="utf-8"))
check("C0 the give-up count is the one of the field backfills (FIELD_BACKFILL_ATTEMPT_LIMIT of the app controller)",
      _ctrl is not None and cp.GIVE_UP_ATTEMPTS == int(_ctrl.group(1)) == 2)
check("C0 a range is at most one year (365 days, a leap year stays inside it)", cp.MAX_RANGE_DAYS == 365)

# ══════════════════════════════════════════════════════════════════════════════
#  1. Planning the ranges
# ══════════════════════════════════════════════════════════════════════════════
section("C1. The ranges (365 days, newest first, a gap costs nothing)")
check("C1 365 days from the first to the last candidate are one range",
      cp._ranges(["2025-01-01", "2025-06-01", "2025-12-31"]) == [("2025-01-01", "2025-12-31", ["2025-01-01", "2025-06-01", "2025-12-31"])])
check("C1 366 days are two ranges, newest first, the old one ends with its own newest candidate",
      cp._ranges(["2024-12-31", "2025-12-31"]) == [("2025-12-31", "2025-12-31", ["2025-12-31"]), ("2024-12-31", "2024-12-31", ["2024-12-31"])])
check("C1 a gap of years between candidates costs nothing: two ranges, not six",
      len(cp._ranges(["2020-01-01", "2020-01-02", "2025-12-31"])) == 2
      and cp._ranges(["2020-01-01", "2020-01-02", "2025-12-31"])[1] == ("2020-01-01", "2020-01-02", ["2020-01-01", "2020-01-02"]))
check("C1 no candidate, no range", cp._ranges([]) == [])
check("C1 a range crossing a leap day counts its days, not the calendar: 2023-03-02 to 2024-02-29 is 365 days (one range), "
      "one day more is two",
      len(cp._ranges(["2023-03-02", "2024-02-29"])) == 1 and len(cp._ranges(["2023-03-01", "2024-02-29"])) == 2)

# ══════════════════════════════════════════════════════════════════════════════
#  2. find_candidates
# ══════════════════════════════════════════════════════════════════════════════
section("C2. find_candidates")
with _isolated_log_env("cp_find") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _scenario1(_b)
    _f = cp.find_candidates()
    check("C2 candidates: no field, an entry in the quality log, not given up (attempts 1 still counts)",
          _f["missing"] == _NOFIELD1)
    check("C2 not a candidate: no log entry (03-21), given up (03-22), own prediction, foreign copy",
          not {"2025-03-21", "2025-03-22", "2025-03-16", "2025-03-19", "2025-03-26", "2025-03-18"} & set(_f["missing"]))
    check("C2 the numbers: one range call, 3 own, the foreign copy listed, 1 given up, basis",
          (_f["calls"], _f["kept"], _f["foreign"], _f["given_up"], _f["basis"]) == (1, 3, ["2025-03-18"], 1, True))
    _before = _bytes_of_raw(), _logbytes()
    cp.find_candidates()
    check("C2 it only looks: no raw file and not the log changes", (_bytes_of_raw(), _logbytes()) == _before)
    check("C2 an explicit folder and log are read, not the configured ones",
          cp.find_candidates(raw_dir=_b / "nowhere")["missing"] == []
          and cp.find_candidates(quality_log_file=_b / "nowhere.json")["missing"] == [])
    _qd = {"days": [_qe("2025-03-15"), _qe("2025-03-17", field_backfill_attempts={"race_predictions": 2})]}
    check("C2 the run's own log can be passed instead of a file: only days with an entry, not given up",
          cp.find_candidates(quality_data=_qd)["missing"] == ["2025-03-15"])
    check("C2 a log that is not readable gives no candidate (nothing is created for a day without an entry)",
          (_b / "log" / "quality_log.json").write_text("{not json", encoding="utf-8") is not None
          and cp.find_candidates()["missing"] == [])

with _isolated_log_env("cp_basis") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _d in ("2025-04-01", "2025-04-02"):
        _put_raw(_d)
    _put_raw("2025-04-03", _pred("2025-04-04"))
    _put_log({"first_day": "2025-04-01", "devices": [], "days": [_qe(d) for d in ("2025-04-01", "2025-04-02", "2025-04-03")]})
    _f = cp.find_candidates()
    check("C2 without a single day that holds a prediction of its own date there is no basis: nothing is offered "
          "(an account without race predictions is never asked)", _f["missing"] == [] and _f["basis"] is False and _f["kept"] == 0)
    _g = _Garmin({"2025-04-01": 1500})
    _r = _run(_g)
    check("C2 and catch_up asks nothing then", _g.calls == [] and _r["filled"] == 0 and _r["calls"] == 0 and _r["missing"] == 0)

with _isolated_log_env("cp_attempts") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _put_raw("2025-05-01", _pred("2025-05-01"))
    for _d in ("2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05"):
        _put_raw(_d)
    _put_log({"first_day": "2025-05-01", "devices": [], "days": [
        _qe("2025-05-01"), _qe("2025-05-02"),
        _qe("2025-05-03", field_backfill_attempts={"race_predictions": 1}),
        _qe("2025-05-04", field_backfill_attempts={"race_predictions": 2}),
        _qe("2025-05-05", field_backfill_attempts={"race_predictions": 3}),
        _qe("2025-05-06")]})
    check("C2 attempts below the give-up count are candidates, the count itself and above are not",
          cp.find_candidates()["missing"] == ["2025-05-02", "2025-05-03"])
    check("C2 a log entry without a raw day is no candidate", "2025-05-06" not in cp.find_candidates()["missing"])
    _raw_path("2025-05-07").write_text("{broken", encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_notadate.json").write_text(json.dumps({"date": "x"}), encoding="utf-8")
    _put_raw("2025-05-08", {})
    _put_raw("2025-05-09", "not a dict")
    _put_raw("2025-05-10", [1500])
    _put_raw("2025-05-11", None)
    _put_log({"first_day": "2025-05-01", "devices": [], "days": [_qe("2025-05-01"), _qe("2025-05-07"), _qe("notadate")]
              + [_qe(f"2025-05-{n:02d}") for n in (8, 9, 10, 11)]})
    check("C2 an unreadable file and a file with a bad name are skipped; a field that is empty, not a dict, a list or null counts as no field",
          cp.find_candidates()["missing"] == ["2025-05-08", "2025-05-09", "2025-05-10", "2025-05-11"])
    _put_log({"first_day": "2025-05-01", "devices": [], "days": [
        _qe("2025-05-01"), _qe("2025-05-02"),
        _qe("2025-05-03", field_backfill_attempts={"race_predictions": 1}),
        _qe("2025-05-04", field_backfill_attempts={"race_predictions": 2}),
        _qe("2025-05-05", field_backfill_attempts={"race_predictions": 3}),
        _qe("2025-05-06")]})
    _put_log({"first_day": "2025-05-01", "devices": [], "days": [
        _qe("2025-05-01"), _qe("2025-05-02", field_backfill_attempts={"steps": 5}),
        _qe("2025-05-03", field_backfill_attempts="bad"), _qe("2025-05-04", field_backfill_attempts={"race_predictions": True}),
        _qe("2025-05-05", field_backfill_attempts={"race_predictions": "x"})]})
    check("C2 the counter of another field, a bad counter value (True, text) and a bad container count as zero attempts",
          cp.find_candidates()["missing"] == ["2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05"])

# ══════════════════════════════════════════════════════════════════════════════
#  3. catch_up — dry run and the real run
# ══════════════════════════════════════════════════════════════════════════════
section("C3. catch_up — dry run, the real run, a second run, the way back")
with _isolated_log_env("cp_run") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _g = _Garmin(_held)
        _bytes_before, _log_before = _bytes_of_raw(), _logbytes()
        _r = _run(_g, dry_run=True)
        check("C3 dry run: reports what would be asked (10 candidates, at most 1 call), asks nothing, writes nothing "
              "(raw and log byte-identical, no safety copy, no summary)",
              _r["missing"] == 10 and _r["calls"] == 1 and _g.calls == [] and _r["filled"] == 0
              and _bytes_of_raw() == _bytes_before and _logbytes() == _log_before and _zips(_b) == [] and not cfg.SUMMARY_DIR.exists())

        _raw_before = {d: _load_raw(d) for d in (p.stem[len("garmin_raw_"):] for p in cfg.RAW_DIR.glob("garmin_raw_*.json"))}
        _lock_seen, _real_wd = [], writer.write_day

        def _wd(n, s, d):
            _lock_seen.append(quality.QUALITY_LOCK.locked())
            return _real_wd(n, s, d)

        _rec = _Rec()
        with patch.object(writer, "write_day", side_effect=_wd), \
                patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv, \
                patch.object(cp, "log", _rec):
            _r = _run(_g)
        check("C3 the real run: one call for the range from the oldest to the newest candidate, asked 'daily'",
              _g.calls == [("2025-03-01", "2025-03-25", "daily")])
        check("C3 5 days got a prediction (03-15 03-17 03-20 03-23 03-24), 5 were asked and answered empty (03-01..03 03-14 03-25), none failed",
              (_r["filled"], _r["given_up"], _r["failed"], _r["calls"]) == (5, 5, 0, 1) and _r["stopped"] is False)
        _filled = ("2025-03-15", "2025-03-17", "2025-03-20", "2025-03-23", "2025-03-24")
        check("C3 the field is the entry of the day with fromCalendarDate/toCalendarDate set to the day (the range answer carried "
              "the bounds of the range) — the form the answer for one day has",
              all(_load_raw(d)["race_predictions"] == _stored(d, _held[d]) for d in _filled))
        check("C3 only that field changed on the filled days: every other key is exactly as it was",
              all(_no_field(_load_raw(d)) == _no_field(_raw_before[d]) for d in _filled))
        _marked = ("2025-03-01", "2025-03-02", "2025-03-03", "2025-03-14", "2025-03-25")
        check("C3 days answered empty and every day that was not a candidate are byte-identical (own, foreign, no log entry, given up)",
              all(_bytes_before[f"garmin_raw_{d}.json"] == _raw_path(d).read_bytes()
                  for d in _marked + ("2025-03-16", "2025-03-18", "2025-03-19", "2025-03-21", "2025-03-22", "2025-03-26")))
        check("C3 summaries are written for the five filled days only (through write_day)",
              sorted(p.name for p in cfg.SUMMARY_DIR.glob("*.json")) == [f"garmin_{d}.json" for d in _filled])
        check("C3 write_day ran under one continuous QUALITY_LOCK hold, once per filled day; the log was saved exactly once",
              _lock_seen == [True] * 5 and _sv.call_count == 1)
        _e = _by()
        check("C3 the label of the filled days is medium, last_checked is today (the MCP cache reads them again)",
              all(_e[d]["fields"]["race_predictions"] == "medium" and _e[d]["last_checked"] == _TODAY for d in _filled))
        check("C3 the days answered empty are marked: the counter is raised to the give-up count; label and last_checked stay",
              all(_e[d]["field_backfill_attempts"]["race_predictions"] == cp.GIVE_UP_ATTEMPTS
                  and _e[d]["fields"]["race_predictions"] == "failed" and _e[d]["last_checked"] == "2024-01-01" for d in _marked))
        check("C3 a filled day keeps its counter (03-23: 1, and the counter of another field), a day given up before keeps its count, "
              "the day without an entry gets none",
              _e["2025-03-23"]["field_backfill_attempts"] == {"race_predictions": 1, "steps": 1}
              and _e["2025-03-22"]["field_backfill_attempts"] == {"race_predictions": 2} and "2025-03-21" not in _e
              and "field_backfill_attempts" not in _e["2025-03-15"])
        check("C3 quality, source, write and the other labels stay everywhere",
              all(x["quality"] == "standard" and x["write"] is True and x["fields"]["heart_rates"] == "medium" for x in _e.values()))
        check("C3 source/: the day with a source file got the entry additively, the day without one got no file",
              json.loads((cfg.SOURCE_DIR / "garmin_source_2025-03-17.json").read_text(encoding="utf-8"))["race_predictions"]
              == _stored("2025-03-17", _held["2025-03-17"])
              and json.loads((cfg.SOURCE_DIR / "garmin_source_2025-03-17.json").read_text(encoding="utf-8"))["user_summary"] == {"totalSteps": 1}
              and not (cfg.SOURCE_DIR / "garmin_source_2025-03-15.json").exists())
        check("C3 a prediction of the day's own date is never overwritten, even where Garmin's values differ (03-19 in all, 03-16 in one "
              "value): it stays and the day is reported; the foreign copy (03-18) is not compared; no value in the log",
              _r["differs"] == ["2025-03-16", "2025-03-19"] and _load_raw("2025-03-19")["race_predictions"] == _pred("2025-03-19", 1600)
              and _load_raw("2025-03-16")["race_predictions"]["timeMarathon"] == 1
              and any("2025-03-19" in m and "differs" in m for m in _rec.m["info"])
              and not any("time5K" in m or "timeMarathon" in m or "userId" in m for lvl in _rec.m.values() for m in lvl))
        check("C3 the foreign copy (03-18) is not touched: that is the prediction repair's business; it is listed in the result",
              _load_raw("2025-03-18")["race_predictions"] == _pred("2025-03-19", 1600) and _r["foreign"] == ["2025-03-18"])
        check("C3 one safety copy of raw/ and the quality log, a valid migration_*.zip that holds the days as they were",
              len(_zips(_b)) == 1 and _zips(_b)[0].startswith("migration_") and snap.verify_snapshot(_snap_dir(_b) / _zips(_b)[0])["ok"]
              and _r["safety_copy"] == _zips(_b)[0])
        with zipfile.ZipFile(_snap_dir(_b) / _zips(_b)[0]) as _zf:
            _names = set(_zf.namelist())
            _old = json.loads(_zf.read("raw/garmin_raw_2025-03-15.json"))
        check("C3 the copy holds the raw files and the log (no summary), and 03-15 in it still has no prediction",
              "log/quality_log.json" in _names and "raw/garmin_raw_2025-03-17.json" in _names
              and not any(n.startswith("summary/") for n in _names) and "race_predictions" not in _old)
        check("C3 no error, and the run logged day names and counts only",
              not _rec.m["error"] and any("complete" in m for m in _rec.m["info"]))

        _after_bytes, _after_log, _n_calls = _bytes_of_raw(), _logbytes(), len(_g.calls)
        _r2 = _run(_g)
        check("C3 a second run asks nothing and changes nothing: no candidate left, 0 calls, raw and log byte-identical, no second copy",
              _r2["missing"] == 0 and _r2["calls"] == 0 and _r2["filled"] == 0 and len(_g.calls) == _n_calls
              and _bytes_of_raw() == _after_bytes and _logbytes() == _after_log and len(_zips(_b)) == 1)
        check("C3 find_candidates after the run offers nothing (the popup would not come again)", cp.find_candidates()["missing"] == [])

        _res = snap.restore_snapshot(_snap_dir(_b) / _r["safety_copy"])
        check("C3 way back: the filled days are as before (03-15 has no prediction again) and are offered again; the days Garmin answered "
              "empty keep their mark (their raw file never changed, the restore only touches days whose file it restores)",
              _res["ok"] is True and all("race_predictions" not in _load_raw(d) for d in _filled)
              and cp.find_candidates()["missing"] == list(_filled)
              and _by()["2025-03-01"]["field_backfill_attempts"]["race_predictions"] == cp.GIVE_UP_ATTEMPTS)

# ══════════════════════════════════════════════════════════════════════════════
#  4. The start of Garmin's history, an account without predictions
# ══════════════════════════════════════════════════════════════════════════════
section("C4. The start of Garmin's history is found from the answers")


def _scenario2(base):
    """Candidates over three years; Garmin holds every day from 2025-03-15 to 2025-12-31; 2025-10-01 holds its own prediction."""
    for d in ("2023-01-10", "2023-06-10", "2024-02-01", "2024-09-01", "2025-03-20", "2025-09-01"):
        _put_raw(d)
    _put_raw("2025-10-01", _pred("2025-10-01", 1500))
    days = [_qe(d) for d in ("2023-01-10", "2023-06-10", "2024-02-01", "2024-09-01", "2025-03-20", "2025-09-01", "2025-10-01")]
    _put_log({"first_day": "2023-01-10", "devices": [], "days": days})
    return {(date(2025, 3, 15) + timedelta(days=i)).isoformat(): 1400 + i for i in range(292)}


with _isolated_log_env("cp_hist") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario2(_b)
        _f = cp.find_candidates()
        _g = _Garmin(_held)
        _r = _run(_g)
        check("C4 three ranges are planned (a plan is an upper bound)", _f["calls"] == 3)
        check("C4 the newest range had entries, the second one (2024) is empty: Garmin holds nothing earlier, so the third is NOT asked",
              _g.calls == [("2025-03-20", "2025-09-01", "daily"), ("2024-02-01", "2024-09-01", "daily")] and _r["calls"] == 2)
        check("C4 the two days in Garmin's history got their prediction, all four older ones are marked (also the one in the range that was "
              "not asked)", _r["filled"] == 2 and _r["given_up"] == 4 and _r["failed"] == 0
              and all(_by()[d]["field_backfill_attempts"]["race_predictions"] == 2
                      for d in ("2023-01-10", "2023-06-10", "2024-02-01", "2024-09-01"))
              and all("field_backfill_attempts" not in _by()[d] for d in ("2025-03-20", "2025-09-01", "2025-10-01")))
        check("C4 afterwards nothing is offered: the old years are never asked again", cp.find_candidates()["missing"] == [])
        check("C4 only the quality log and the two raw days changed: the older raw days are byte-identical",
              all(_load_raw(d) == _no_field(_load_raw(d)) for d in ("2023-01-10", "2024-09-01")))

section("C4c. Entries outside the asked range and junk entries prove no history")
with _isolated_log_env("cp_junk") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario2(_b)
        _g = _Garmin({"2025-09-02": 1500},
                     extra=[{"calendarDate": "2025-09-0", "time5K": 1}, "x", None, {}, {"time5K": 1}, {"calendarDate": 20250901},
                            _pred("2025-09-02", 1500), _pred("2025-03-19", 1500)], extra_calls=(1,))
        _r = _run(_g)
        check("C4c a valid entry one day after the range (and one before it), a date that is not a date and entries that are no dict prove "
              "nothing: the newest range counts as empty, so all three ranges are asked (a range with an entry would have ended the walk after two)",
              len(_g.calls) == 3 and _r["filled"] == 0 and _r["given_up"] == 6)

section("C4b. An account whose archive believes in predictions but Garmin answers nothing")
with _isolated_log_env("cp_none") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario2(_b)
        _g = _Garmin({})
        _raw0, _log0 = _bytes_of_raw(), _logbytes()
        _r = _run(_g)
        check("C4b no entry anywhere: nothing proves a history, so every range is asked once (3 calls) and each is marked for its own days",
              len(_g.calls) == 3 and _r["calls"] == 3 and _r["filled"] == 0 and _r["given_up"] == 6)
        check("C4b raw/ is untouched, only marks went into the log; the copy holds the log only (quality_log_*.zip), no raw",
              _bytes_of_raw() == _raw0 and _logbytes() != _log0 and len(_zips(_b)) == 1 and _zips(_b)[0].startswith("quality_log_")
              and not any(n.startswith("raw/") for n in zipfile.ZipFile(_snap_dir(_b) / _zips(_b)[0]).namelist()))
        check("C4b afterwards nothing is offered", cp.find_candidates()["missing"] == [] and _run(_g)["calls"] == 0 and len(_g.calls) == 3)

# ══════════════════════════════════════════════════════════════════════════════
#  5. Failures, stop, the shared log
# ══════════════════════════════════════════════════════════════════════════════
section("C5. A failing call, a stop, a write that fails, a day that changed during the calls")
with _isolated_log_env("cp_fail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario2(_b)
        _g = _Garmin(_held, fail_on=2)
        _rec = _Rec()
        with patch.object(cp, "log", _rec):
            _r = _run(_g)
        check("C5 the second call fails: the walk ends, the first range is stored, nothing is marked for the failed range and the older ones",
              len(_g.calls) == 2 and _r["failed"] == 1 and _r["filled"] == 2 and _r["given_up"] == 0 and "reason" in _r
              and any("failed" in m for m in _rec.m["warning"]))
        check("C5 the days of the failed range are still candidates (asked again at the next run)",
              cp.find_candidates()["missing"] == ["2023-01-10", "2023-06-10", "2024-02-01", "2024-09-01"])

with _isolated_log_env("cp_fail1") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _scenario2(_b)
        _b4raw, _b4log = _bytes_of_raw(), _logbytes()
        _g = _Garmin({}, fail_on=1)
        _r = _run(_g)
        check("C5 the first call fails: nothing is written or marked, no safety copy (nothing to store), the failure is reported",
              _r["failed"] == 1 and _r["filled"] == 0 and _r["given_up"] == 0 and _r["safety_copy"] is None
              and _bytes_of_raw() == _b4raw and _logbytes() == _b4log and _zips(_b) == [])
        _g = _Garmin({"2025-03-20": 1500})
        with patch("garmin_api.time.sleep"), patch.object(cp.api, "api_call", return_value=({"not": "a list"}, True)):
            _r = cp.catch_up(_g)
        check("C5 an answer that is not a list is a failed call, not an empty one (nothing is marked)",
              _r["failed"] == 1 and _r["given_up"] == 0 and _logbytes() == _b4log)

with _isolated_log_env("cp_stop") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _b4raw, _b4log = _bytes_of_raw(), _logbytes()
        _g = _Garmin(_held)
        _r = _run(_g, should_stop=lambda: True)
        check("C5 a stop before the first call: nothing is asked, nothing is written, stopped is reported",
              _r["stopped"] is True and _g.calls == [] and _bytes_of_raw() == _b4raw and _logbytes() == _b4log and _zips(_b) == [])
        _flag = []
        _g = _Garmin(_held, hook=lambda n: _flag.append(1))
        _r = _run(_g, should_stop=lambda: bool(_flag))
        check("C5 a stop after the calls and before the write: nothing is written, no safety copy",
              _r["stopped"] is True and len(_g.calls) == 1 and _bytes_of_raw() == _b4raw and _logbytes() == _b4log and _zips(_b) == [])
        _flag, _real_wd = [], writer.write_day

        def _wd_stop(n, s, d):
            ok = _real_wd(n, s, d)
            _flag.append(1)
            return ok

        _g = _Garmin(_held)
        with patch.object(writer, "write_day", side_effect=_wd_stop):
            _r = _run(_g, should_stop=lambda: bool(_flag))
        _e = _by()
        check("C5 a stop during the loop ends it after the current day: the written day is recorded in the log, the others are not, "
              "and no mark is saved (the run was not completed)",
              _r["stopped"] is True and _r["filled"] == 1 and "race_predictions" in _load_raw("2025-03-15")
              and "race_predictions" not in _load_raw("2025-03-17") and _e["2025-03-15"]["fields"]["race_predictions"] == "medium"
              and _e["2025-03-17"]["fields"]["race_predictions"] == "failed" and _r["given_up"] == 0
              and "field_backfill_attempts" not in _e["2025-03-01"])

with _isolated_log_env("cp_wfail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _real_wd, _bad_before = writer.write_day, _raw_path("2025-03-17").read_bytes()
        _rec = _Rec()
        _g = _Garmin(_held)
        with patch.object(writer, "write_day", side_effect=lambda n, s, d: False if d == "2025-03-17" else _real_wd(n, s, d)), \
                patch.object(cp, "log", _rec):
            _r = _run(_g)
        check("C5 a day that cannot be written is counted as failed and never stops the loop; the others are done and the marks are saved",
              _r["failed"] == 1 and _r["filled"] == 4 and _r["given_up"] == 5 and any("2025-03-17" in m for m in _rec.m["error"]))
        check("C5 the failed day stays as it was (file and label), so it is found again at the next start",
              _raw_path("2025-03-17").read_bytes() == _bad_before and _by()["2025-03-17"]["fields"]["race_predictions"] == "failed"
              and cp.find_candidates()["missing"] == ["2025-03-17"])
        with patch.object(quality, "_save_quality_log", return_value=False), patch.object(cp, "log", _Rec()):
            _put_raw("2025-03-27")
            _log = json.loads(_logbytes())
            _log["days"].append(_qe("2025-03-27"))
            _put_log(_log)
            _r = _run(_Garmin({"2025-03-27": 1500}))
        check("C5 a log that cannot be saved is a failure with its reason (not silent)",
              _r["failed"] >= 1 and _r.get("reason") == "the quality log could not be saved")

with _isolated_log_env("cp_nocopy") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _b4raw, _b4log = _bytes_of_raw(), _logbytes()
        _rec = _Rec()
        _g = _Garmin(_held)
        with patch.object(cp, "log", _rec), patch.object(snap, "create_snapshot", return_value={"ok": False, "path": None, "reason": "disk full"}):
            _r = _run(_g)
        check("C5 no safety copy, no write: failed 1 with the reason, raw and log byte-identical, an error is logged (the call was made)",
              _r["failed"] == 1 and _r["reason"] == "disk full" and len(_g.calls) == 1 and _bytes_of_raw() == _b4raw and _logbytes() == _b4log
              and any("no safety copy" in m for m in _rec.m["error"]))
        with patch.object(snap, "create_snapshot", return_value={"ok": True, "path": None, "reason": "nothing"}):
            _r = _run(_Garmin(_held))
        check("C5 a snapshot call that is ok but made no file counts as no copy (nothing written)", _r["failed"] == 1 and _bytes_of_raw() == _b4raw)

with _isolated_log_env("cp_changed") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)

        def _hook(n):
            _put_raw("2025-03-17", _pred("2025-03-17", 999))        # the day gets a prediction while Garmin is asked

        _r = _run(_Garmin(_held, hook=_hook))
        check("C5 a day that got a prediction while Garmin was asked is not overwritten and not counted",
              _load_raw("2025-03-17")["race_predictions"] == _pred("2025-03-17", 999) and _r["filled"] == 4)

with _isolated_log_env("cp_srcfail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _rec = _Rec()
        with patch.object(sw, "patch_source_field", return_value=False), patch.object(cp, "log", _rec):
            _r = _run(_Garmin(_held))
        check("C5 a source/ patch that fails is a warning only: the day is still filled in raw/ and summary/ and counted as filled",
              _r["filled"] == 5 and _r["failed"] == 0 and _r["source_failed"] == 5
              and sum(1 for m in _rec.m["warning"] if "source/" in m) == 5
              and _load_raw("2025-03-15")["race_predictions"] == _stored("2025-03-15", _held["2025-03-15"]))

with _isolated_log_env("cp_shared") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _shared = quality._load_quality_log()
        _before_file = _logbytes()
        with patch.object(quality, "_load_quality_log", wraps=quality._load_quality_log) as _ld, \
                patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
            _r = _run(_Garmin(_held), quality_data=_shared)
        _sd = {e["date"]: e for e in _shared["days"]}
        check("C5 shared quality log: the caller's object gets labels, last_checked and marks, it is not loaded again, "
              "exactly that object is saved once",
              (_r["filled"], _r["given_up"]) == (5, 5) and _ld.call_count == 0 and _sv.call_count == 1 and _sv.call_args.args[0] is _shared
              and _sd["2025-03-15"]["fields"]["race_predictions"] == "medium" and _sd["2025-03-15"]["last_checked"] == _TODAY
              and _sd["2025-03-01"]["field_backfill_attempts"]["race_predictions"] == 2)
        _shared2 = {"days": [e for e in _shared["days"] if e["date"] != "2025-03-24"] + [
            _qe("2025-03-24", field_backfill_attempts={"race_predictions": 2})]}
        check("C5 the candidates come from the run's own log when it is passed (a day given up there is not asked)",
              "2025-03-24" not in cp.find_candidates(quality_data=_shared2)["missing"])

# ══════════════════════════════════════════════════════════════════════════════
#  6. Scheduler hint — scheduler/daily_update.py::_check_prediction_catchup
# ══════════════════════════════════════════════════════════════════════════════
section("C6. Scheduler hint")
_du_spec = importlib.util.spec_from_file_location("daily_update_cp", _SRC / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)

with _isolated_log_env("cp_sched") as _b:
    _arch = _b / "archive"
    (_arch / "garmin_data" / "raw").mkdir(parents=True)
    (_arch / "garmin_data" / "log").mkdir(parents=True)
    _days = {"2025-06-01": _pred("2025-06-01"), "2025-06-02": None, "2025-06-03": None, "2025-06-04": _pred("2025-06-09")}
    for _d, _f_ in _days.items():
        (_arch / "garmin_data" / "raw" / f"garmin_raw_{_d}.json").write_text(
            json.dumps({"date": _d, **({"race_predictions": _f_} if _f_ else {})}), encoding="utf-8")
    (_arch / "garmin_data" / "log" / "quality_log.json").write_text(
        json.dumps({"days": [_qe(d) for d in _days]}), encoding="utf-8")
    _before = {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()}
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n = _du._check_prediction_catchup(_arch)
    check("C6 counts the days Garmin can be asked for (06-02, 06-03; the foreign copy on 06-04 is the repair's) and warns with the number, nothing else",
          _n == 2 and _rec.m["warning"] == [
              "  Up to 2 day(s) hold no race prediction of their own date; Garmin can be asked for them.",
              "  Open the app and run Sync Garmin once to do so (a safety copy is made first)."] and not _rec.m["error"])
    check("C6 it only looks: no file of the archive changes, none is added",
          {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()} == _before)
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n_none = _du._check_prediction_catchup(_b / "no_archive_here")
    check("C6 no archive folder -> 0 and no warning", _n_none == 0 and not _rec.m["warning"])
    _rec = _Rec()
    with patch.object(_du, "log", _rec), patch.object(cp, "find_candidates", side_effect=RuntimeError("boom")):
        _n_err = _du._check_prediction_catchup(_arch)
    check("C6 an error in the scan never stops the run: 0, no warning, no error", _n_err == 0 and not _rec.m["warning"] and not _rec.m["error"])

# ══════════════════════════════════════════════════════════════════════════════
#  9. Mutation round v1.7.6.12 — survivors of the Cosmic Ray run
# ══════════════════════════════════════════════════════════════════════════════
section("C9. mutation round v1.7.6.12")

# -- helpers --------------------------------------------------------------------------------------------------------
check("C9 _valid_date: a date -> True", cp._valid_date("2025-03-01") is True)
check("C9 _valid_date: not a string -> False",
      all(cp._valid_date(v) is False for v in (None, 20250301, ["2025-03-01"], b"2025-03-01")))
check("C9 _valid_date: the basic ISO form 20250301 (valid for date.fromisoformat, 8 characters) is no archive date",
      cp._valid_date("20250301") is False)
check("C9 _valid_date: wrong length -> False", all(cp._valid_date(v) is False for v in ("2025-3-1", "2025-03-011", "")))
check("C9 _valid_date: ten characters that are no date -> False",
      all(cp._valid_date(v) is False for v in ("2025-13-45", "2025-02-30", "abcdefghij")))

with _isolated_log_env("cp_scan9") as _b:
    _put_raw("2025-03-20")
    _put_raw("0000")                                      # sorts before the day, its name is no date
    check("C9 _scan: a file whose name is no date is left out and does not end the scan",
          cp._scan(cfg.RAW_DIR) == {"2025-03-20": None})

_att = cp._attempts({"days": [
    "junk", None, {"date": "bad"}, {"date": "2025-03-01"},
    {"date": "2025-03-02", "field_backfill_attempts": {"steps": 1}},
    {"date": "2025-03-03", "field_backfill_attempts": {"race_predictions": 2}},
    {"date": "2025-03-04", "field_backfill_attempts": {"race_predictions": True}},
    {"date": "2025-03-05", "field_backfill_attempts": {"race_predictions": "2"}},
    {"date": "2025-03-06", "field_backfill_attempts": {"race_predictions": 1.5}},
    {"date": "2025-03-07", "field_backfill_attempts": "x"}]}, None)
check("C9 _attempts: only dict entries with a valid date; a missing or unusable counter is 0 (not a number, a bool, text, a float)",
      _att == {"2025-03-01": 0, "2025-03-02": 0, "2025-03-03": 2, "2025-03-04": 0, "2025-03-05": 0, "2025-03-06": 0, "2025-03-07": 0})

_pl = cp._plan({"2025-03-19": {"calendarDate": "2025-03-18"}, "2025-03-20": None}, {"2025-03-20": 0})
check("C9 _plan: a day that holds the prediction of an EARLIER day is foreign (no basis, nothing missing)",
      _pl == {"missing": [], "calls": 0, "kept": 0, "foreign": ["2025-03-19"], "given_up": 0, "basis": False})
_pl = cp._plan({"2025-03-19": {"calendarDate": "2025-03-19"}, "2025-03-20": None, "2025-03-21": None,
                "2025-03-22": None, "2025-03-23": None},
               {"2025-03-20": 2, "2025-03-21": 5, "2025-03-22": 1, "2025-03-23": 0})
check("C9 _plan: a counter at the limit or above it (2 and 5) is given up, below it (1, 0) is missing",
      _pl == {"missing": ["2025-03-22", "2025-03-23"], "calls": 1, "kept": 1, "foreign": [], "given_up": 2, "basis": True})

# -- a prediction of its own date is compared with Garmin's value by value -------------------------------------------
with _isolated_log_env("cp_differs") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _put_raw("2025-03-09")                                        # candidate
        _put_raw("2025-03-10", _pred("2025-03-10", 1500))             # own, identical to Garmin's
        _put_raw("2025-03-11", _pred("2025-03-11", 1800))             # own, every value LARGER than Garmin's
        _put_raw("2025-03-12", _pred("2025-03-11", 1900))             # a copy of an EARLIER day, values differ
        _put_raw("2025-03-13", _pred("2025-03-13", 1200))             # own, every value SMALLER than Garmin's
        _put_raw("2025-03-14")                                        # candidate
        _put_log({"first_day": "2025-03-09", "devices": [],
                  "days": [_qe(f"2025-03-{n:02d}") for n in range(9, 15)]})
        _rec = _Rec()
        with patch.object(cp, "log", _rec):
            _r = _run(_Garmin({f"2025-03-{n:02d}": 1500 for n in range(9, 15)}))
        check("C9 differs: only own predictions with other values, larger or smaller; identical ones and a copy of an earlier day are not",
              _r["differs"] == ["2025-03-11", "2025-03-13"] and _r["foreign"] == ["2025-03-12"] and _r["filled"] == 2)
        check("C9 the days of the write loop are numbered from 1: [1/2] and [2/2]",
              "  [1/2] 2025-03-09 — prediction set ok" in _rec.m["info"] and "  [2/2] 2025-03-14 — prediction set ok" in _rec.m["info"])

# -- a stop in the loop after three of five days: the count in the message, one line, the loop ends ------------------------
with _isolated_log_env("cp_stop9") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _held = _scenario1(_b)
        _flag, _real_wd = [], writer.write_day

        def _wd_count(n, s, d):
            ok = _real_wd(n, s, d)
            _flag.append(1)
            return ok

        _rec = _Rec()
        with patch.object(writer, "write_day", side_effect=_wd_count), patch.object(cp, "log", _rec):
            _r = _run(_Garmin(_held), should_stop=lambda: len(_flag) >= 3)
        check("C9 stopped at the fourth day: three written, 'stopped after 3 of 5 day(s).' once, the fourth and fifth untouched",
              _r["stopped"] is True and _r["filled"] == 3
              and [m for m in _rec.m["info"] if "stopped after" in m] == ["  Prediction catch-up: stopped after 3 of 5 day(s)."])

# -- the answer of the log save: only False is a failure, and it counts once --------------------------------------------
def _save_scenario(base):
    _put_raw("2025-03-25")                                    # candidate, Garmin holds nothing -> marked
    _put_raw("2025-03-26", _pred("2025-03-26", 1500))         # own: the basis
    _put_raw("2025-03-27")                                    # candidate, Garmin holds it -> filled
    _put_log({"first_day": "2025-03-25", "devices": [],
              "days": [_qe("2025-03-25"), _qe("2025-03-26"), _qe("2025-03-27")]})


with _isolated_log_env("cp_save9a") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _save_scenario(_b)
        with patch.object(quality, "_save_quality_log", return_value=False), patch.object(cp, "log", _Rec()):
            _r = _run(_Garmin({"2025-03-27": 1500}))
        check("C9 a log that cannot be saved counts exactly one failure and no marked day",
              _r["failed"] == 1 and _r["given_up"] == 0 and _r["reason"] == "the quality log could not be saved")
with _isolated_log_env("cp_save9b") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _save_scenario(_b)
        with patch.object(quality, "_save_quality_log", return_value=0), patch.object(cp, "log", _Rec()):
            _r = _run(_Garmin({"2025-03-27": 1500}))
        check("C9 a save that answers 0 (not False) is a save: no failure, the marked day is counted",
              _r["failed"] == 0 and _r["given_up"] == 1 and _r["filled"] == 1)

summary()
