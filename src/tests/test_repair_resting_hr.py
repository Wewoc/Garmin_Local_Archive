#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_repair_resting_hr.py — garmin_repair_resting_hr
RESTING-HR-REPAIR v1.7.5.7 — removable (see the module's removal list).

Run from the project folder:
    python tests/test_repair_resting_hr.py

All days are synthetic; shared setup and helpers live in gla_testenv.py.
"""

import copy
import json
import zipfile
from datetime import date
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env, _put_log, _qdays  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_quality as quality
import garmin_writer as writer

section("R. garmin_repair_resting_hr (v1.7.5.7)")
import garmin_repair_resting_hr as rr

_TODAY = date.today().isoformat()
_SEVEN = rr.SEVEN_DAY_KEY


class _Rec:
    """Stand-in for the module logger — keeps the messages per level."""
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


def _put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def _imp_raw(d, resting):
    """A day in the form garmin_import wrote before v1.7.5.7 (7-day average as resting HR)."""
    return {"date": d,
            "user_summary": {"totalSteps": 8000, "restingHeartRate": resting,
                             "minHeartRate": 45, "maxHeartRate": 150},
            "heart_rates": {"restingHeartRate": resting, "minHeartRate": 45, "maxHeartRate": 150},
            "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 21000}}}


def _api_raw(d):
    return {"date": d, "user_summary": {"totalSteps": 9000, "restingHeartRate": 52},
            "heart_rates": {"restingHeartRate": 52, "minHeartRate": 44, "maxHeartRate": 160,
                            "heartRateValues": [[1740787200000, 58]]}}


def _src(d, day=None, avg=None, with_day=True, with_avg=True):
    hr = {"calendarDate": d, "heartRateValues": [[1740787200000, 58]]}
    if with_day:
        hr["restingHeartRate"] = day
    if with_avg:
        hr[_SEVEN] = avg
    return {"date": d, "heart_rates": hr}


def _qe(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False,
            "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None,
            "fields": {"heart_rates": "medium"}, **kw}


def _log_of(*dates):
    return {"first_day": "2025-06-01", "devices": [], "days": [_qe(d) for d in dates]}


def _raw_path(d):
    return cfg.RAW_DIR / f"garmin_raw_{d}.json"


def _load_raw(d):
    return json.loads(_raw_path(d).read_text(encoding="utf-8"))


def _load_sum(d):
    return json.loads((cfg.SUMMARY_DIR / f"garmin_{d}.json").read_text(encoding="utf-8"))


def _setup(base, days, src_days=(), log_dates=None):
    """days: {date: raw dict}; src_days: {date: source dict}; log_dates: dates with a log entry."""
    cfg.SUMMARY_DIR = base / "summary"
    for d, raw in days.items():
        _put(_raw_path(d), raw)
    for d, src in dict(src_days).items():
        _put(cfg.SOURCE_DIR / f"garmin_source_{d}.json", src)
    _put_log(_log_of(*(log_dates if log_dates is not None else list(days))))


def _no_last_checked(entry):
    return {k: v for k, v in entry.items() if k != "last_checked"}


# ══════════════════════════════════════════════════════════════════════════════
#  1. Detection — find_candidates()
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_find") as _b:
    check("find: no raw folder -> nothing found",
          rr.find_candidates() == {"repairable": [], "no_source": []})
    _done = _imp_raw("2025-06-04", 60)
    _done["user_summary"][_SEVEN] = None
    _two = _imp_raw("2025-06-06", 60)
    del _two["heart_rates"]["minHeartRate"]
    _setup(_b, {"2025-06-01": _imp_raw("2025-06-01", 60), "2025-06-02": _imp_raw("2025-06-02", 61),
                "2025-06-03": _api_raw("2025-06-03"), "2025-06-04": _done, "2025-06-06": _two},
           {"2025-06-01": _src("2025-06-01", 57, 60), "2025-06-03": _src("2025-06-03", 52, 52)})
    _put(_raw_path("2025-06-05"), "{broken")
    _put(cfg.RAW_DIR / "garmin_raw_notadate.json", _imp_raw("x", 60))
    _res = rr.find_candidates()
    check("find: the import form without the 7-day marker is found; with a source/ file it is repairable, without it listed apart",
          _res == {"repairable": ["2025-06-01"], "no_source": ["2025-06-02"]})
    check("find: an API day, a day that carries the marker, a day with other heart_rates keys, a broken file and a bad file name are ignored",
          "2025-06-03" not in _res["repairable"] + _res["no_source"]
          and "2025-06-04" not in _res["repairable"] + _res["no_source"]
          and "2025-06-06" not in _res["repairable"] + _res["no_source"]
          and "2025-06-05" not in _res["repairable"] + _res["no_source"])

# ══════════════════════════════════════════════════════════════════════════════
#  2. Repair — values, summary, quality log, backup, second run
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_main") as _b:
    _D = ["2025-06-10", "2025-06-11", "2025-06-12", "2025-06-13", "2025-06-14"]
    _days = {_D[0]: _imp_raw(_D[0], 60), _D[1]: _imp_raw(_D[1], 58), _D[2]: _imp_raw(_D[2], 59),
             _D[3]: _api_raw(_D[3]), _D[4]: _imp_raw(_D[4], 62)}
    _srcs = {_D[0]: _src(_D[0], 57, 60), _D[1]: _src(_D[1], 58, 58),
             _D[2]: _src(_D[2], with_day=False, avg=59), _D[3]: _src(_D[3], 52, 52)}
    _setup(_b, _days, _srcs, log_dates=_D + ["2025-06-20"])
    _old_bytes = {d: _raw_path(d).read_bytes() for d in _D}
    _src_bytes = (cfg.SOURCE_DIR / f"garmin_source_{_D[0]}.json").read_bytes()
    cfg.RAW_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-06.zip", "w", zipfile.ZIP_DEFLATED) as _zf:
        _zf.writestr(f"garmin_raw_{_D[0]}.json", _old_bytes[_D[0]])
    _qd_before = _qdays()
    _sum_before = quality._compute_checksum(quality._load_quality_log())

    _lock_seen = []
    _real_wd = writer.write_day

    def _wd(n, s, d):
        _lock_seen.append(quality.QUALITY_LOCK.locked())
        return _real_wd(n, s, d)

    _rec = _Rec()
    with patch.object(writer, "write_day", side_effect=_wd), \
            patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv, \
            patch.object(rr, "log", _rec):
        _r = rr.repair_resting_hr()

    check("repair: three days corrected, none failed, the day without a source/ file is reported",
          (_r["ok"], _r["failed"]) == (3, 0) and _r["no_source"] == [_D[4]]
          and [(i["date"], i["status"]) for i in _r["items"]] == [(_D[0], "repaired"), (_D[1], "repaired"), (_D[2], "repaired")])
    _exp = copy.deepcopy(_days[_D[0]])
    _exp["heart_rates"]["restingHeartRate"] = 57
    _exp["user_summary"]["restingHeartRate"] = 57
    _exp["user_summary"][_SEVEN] = 60
    check("repair: day value in both raw places, the 7-day average in its own field, nothing else in raw changed",
          _load_raw(_D[0]) == _exp)
    check("repair: the summary is rebuilt from the corrected raw (resting 57, min/max unchanged)",
          _load_sum(_D[0])["heartrate"]["resting_bpm"] == 57
          and _load_sum(_D[0])["heartrate"]["min_bpm"] == 45 and _load_sum(_D[0])["heartrate"]["max_bpm"] == 150)
    check("repair: a day whose stored value happened to be right also gets the marker, value unchanged",
          _load_raw(_D[1])["heart_rates"]["restingHeartRate"] == 58
          and _load_raw(_D[1])["user_summary"][_SEVEN] == 58)
    _r2 = _load_raw(_D[2])
    check("repair: no day value in source/ -> resting key removed, user_summary None, marker set, summary empty",
          "restingHeartRate" not in _r2["heart_rates"] and _r2["user_summary"]["restingHeartRate"] is None
          and _r2["user_summary"][_SEVEN] == 59 and _load_sum(_D[2])["heartrate"]["resting_bpm"] is None)
    check("repair: an API day, a day without source/ and the source/ files stay byte-identical",
          _raw_path(_D[3]).read_bytes() == _old_bytes[_D[3]] and _raw_path(_D[4]).read_bytes() == _old_bytes[_D[4]]
          and (cfg.SOURCE_DIR / f"garmin_source_{_D[0]}.json").read_bytes() == _src_bytes)
    _qd_after = _qdays()
    check("repair: quality log — repaired days get today as last_checked, every other day and field is untouched",
          all(_qd_after[d]["last_checked"] == _TODAY for d in _D[:3])
          and all(_qd_after[d] == _qd_before[d] for d in (_D[3], _D[4], "2025-06-20"))
          and all(_no_last_checked(_qd_after[d]) == _no_last_checked(_qd_before[d]) for d in _D[:3]))
    check("repair: the log checksum is unchanged and the log is saved exactly once",
          quality._compute_checksum(quality._load_quality_log()) == _sum_before and _sv.call_count == 1)
    with zipfile.ZipFile(cfg.RAW_BACKUP_DIR / "raw_backup_2025-06.zip") as _zf:
        check("repair: the monthly backup ZIP holds the corrected raw, not the stale one",
              _zf.read(f"garmin_raw_{_D[0]}.json") == _raw_path(_D[0]).read_bytes()
              and _zf.read(f"garmin_raw_{_D[0]}.json") != _old_bytes[_D[0]])
    check("repair: QUALITY_LOCK is held while each day is written and free afterwards",
          _lock_seen == [True, True, True] and not quality.QUALITY_LOCK.locked())
    check("repair: log — a source-less day is warned about, every day has a numbered line, the final line counts",
          f"  Resting HR repair: {_D[4]} — no source/ file, left unchanged" in _rec.m["warning"]
          and f"  [1/3] {_D[0]} — 60 → 57 ok" in _rec.m["info"]
          and f"  [3/3] {_D[2]} — 59 → None ok" in _rec.m["info"]
          and "  Resting HR repair complete: 3 corrected, 0 failed, 1 without source/." in _rec.m["info"])

    # second run: nothing left, nothing written
    _after_bytes = {d: _raw_path(d).read_bytes() for d in _D}
    _log_bytes = cfg.QUALITY_LOG_FILE.read_bytes()
    _rec = _Rec()
    with patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv2, patch.object(rr, "log", _rec):
        _r3 = rr.repair_resting_hr()
    check("second run: finds nothing to correct, only the source-less day is still reported",
          (_r3["ok"], _r3["failed"], _r3["items"]) == (0, 0, [])
          and _r3["no_source"] == [_D[4]] and rr.find_candidates()["repairable"] == [])
    check("second run: no raw file and not the quality log changes, no save",
          all(_raw_path(d).read_bytes() == _after_bytes[d] for d in _D)
          and cfg.QUALITY_LOG_FILE.read_bytes() == _log_bytes and _sv2.call_count == 0)

# ══════════════════════════════════════════════════════════════════════════════
#  3. Dry run
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_dry") as _b:
    _d = "2025-06-15"
    _setup(_b, {_d: _imp_raw(_d, 60)}, {_d: _src(_d, 57, 60)})
    _raw_b, _log_b = _raw_path(_d).read_bytes(), cfg.QUALITY_LOG_FILE.read_bytes()
    with patch.object(writer, "write_day") as _wd2, patch.object(quality, "_save_quality_log") as _sv3:
        _r = rr.repair_resting_hr(dry_run=True)
    check("dry run: lists the day with old value, new value and average, counts it",
          _r["items"] == [{"date": _d, "status": "would_repair", "old": 60, "new": 57, "avg": 60}]
          and (_r["ok"], _r["failed"]) == (1, 0))
    check("dry run: nothing is written — no raw, no summary, no backup, no quality log",
          _raw_path(_d).read_bytes() == _raw_b and cfg.QUALITY_LOG_FILE.read_bytes() == _log_b
          and not _wd2.called and not _sv3.called and not (cfg.SUMMARY_DIR / f"garmin_{_d}.json").exists()
          and not cfg.RAW_BACKUP_DIR.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  4. Errors — a bad day never stops the loop, only repaired days are recorded
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_err") as _b:
    _E = [f"2025-06-{n}" for n in (20, 21, 22, 23, 24, 25)]
    _days = {d: _imp_raw(d, 60) for d in _E}
    _srcs = {_E[2]: _src(_E[2], 57, 60), _E[3]: _src(_E[3], 57, 60), _E[4]: _src(_E[4], 57, 60),
             _E[5]: _src(_E[5], 56, 60)}
    _setup(_b, _days, _srcs)
    _put(cfg.SOURCE_DIR / f"garmin_source_{_E[0]}.json", "{broken")                 # unreadable
    _put(cfg.SOURCE_DIR / f"garmin_source_{_E[1]}.json", {"date": _E[1], "stats": {}})   # no heart_rates section
    _old = {d: _raw_path(d).read_bytes() for d in _E}
    _real_wd = writer.write_day

    def _wd3(n, s, d):
        if d == _E[3]:
            return False
        if d == _E[4]:
            raise OSError("disk full")
        return _real_wd(n, s, d)

    _rec = _Rec()
    with patch.object(writer, "write_day", side_effect=_wd3), \
            patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv4, \
            patch.object(rr, "log", _rec):
        _r = rr.repair_resting_hr()
    _st = {i["date"]: i for i in _r["items"]}
    check("errors: broken source, source without heart_rates, write failure and exception are four failures, two days are repaired",
          (_r["ok"], _r["failed"]) == (2, 4)
          and [_st[d]["status"] for d in _E] == ["error", "error", "repaired", "error", "error", "repaired"]
          and all(_st[d]["reason"] for d in (_E[0], _E[1], _E[3], _E[4])))
    check("errors: every failed day keeps its raw file exactly as it was",
          all(_raw_path(d).read_bytes() == _old[d] for d in (_E[0], _E[1], _E[3], _E[4])))
    _q = _qdays()
    check("errors: only the two repaired days get last_checked, saved once; the failed ones are not recorded",
          _q[_E[2]]["last_checked"] == _TODAY and _q[_E[5]]["last_checked"] == _TODAY
          and all(_q[d]["last_checked"] == "2024-01-01" for d in (_E[0], _E[1], _E[3], _E[4]))
          and _sv4.call_count == 1)
    check("errors: the loop counts on, failed days are logged with their number and reason",
          any(m.startswith(f"  [1/6] {_E[0]} — error:") for m in _rec.m["error"])
          and f"  [5/6] {_E[4]} — error: disk full" in _rec.m["error"]
          and "  Resting HR repair complete: 2 corrected, 4 failed, 0 without source/." in _rec.m["info"])

# ══════════════════════════════════════════════════════════════════════════════
#  5. Values that are not numbers
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_num") as _b:
    _d = "2025-06-26"
    _setup(_b, {_d: _imp_raw(_d, 60)}, {_d: _src(_d, True, "x")})
    rr.repair_resting_hr()
    _rn = _load_raw(_d)
    check("values: a boolean or text in source/ counts as missing, never as a number",
          "restingHeartRate" not in _rn["heart_rates"] and _rn["user_summary"]["restingHeartRate"] is None
          and _rn["user_summary"][_SEVEN] is None)
    check("values: a day without a numeric average is still marked done (second scan finds nothing)",
          rr.find_candidates() == {"repairable": [], "no_source": []})

# ══════════════════════════════════════════════════════════════════════════════
#  6. Stop request, interruption, day that changed meanwhile, day without log entry
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_stop") as _b:
    _S = ["2025-06-27", "2025-06-28", "2025-06-29"]
    _setup(_b, {d: _imp_raw(d, 60) for d in _S}, {d: _src(d, 57, 60) for d in _S})
    _old = {d: _raw_path(d).read_bytes() for d in _S}
    _calls = []

    def _stop_after_one():
        _calls.append(1)
        return len(_calls) > 1

    _rec = _Rec()
    with patch.object(rr, "log", _rec):
        _r = rr.repair_resting_hr(should_stop=_stop_after_one)
    _q = _qdays()
    check("stop: the loop ends after the day in progress, the rest stays untouched",
          _r["ok"] == 1 and _load_raw(_S[0])["user_summary"][_SEVEN] == 60
          and _raw_path(_S[1]).read_bytes() == _old[_S[1]] and _raw_path(_S[2]).read_bytes() == _old[_S[2]]
          and "  Resting HR repair: stopped after 1 of 3 day(s)." in _rec.m["info"])
    check("stop: the day written before the stop is recorded in the quality log",
          _q[_S[0]]["last_checked"] == _TODAY and _q[_S[1]]["last_checked"] == "2024-01-01")

with _isolated_log_env("rr_boom") as _b:
    _S = ["2025-06-27", "2025-06-28"]
    _setup(_b, {d: _imp_raw(d, 60) for d in _S}, {d: _src(d, 57, 60) for d in _S})
    _n = []

    def _boom():
        _n.append(1)
        if len(_n) > 1:
            raise RuntimeError("interrupted")
        return False

    _raised = False
    try:
        rr.repair_resting_hr(should_stop=_boom)
    except RuntimeError:
        _raised = True
    check("interruption: an unexpected exception still records and saves the days written so far, and frees the lock",
          _raised and _qdays()[_S[0]]["last_checked"] == _TODAY and _qdays()[_S[1]]["last_checked"] == "2024-01-01"
          and not quality.QUALITY_LOCK.locked())

with _isolated_log_env("rr_gone") as _b:
    _d = "2025-06-30"
    _setup(_b, {_d: _api_raw(_d)}, {_d: _src(_d, 52, 52)})
    _ob = _raw_path(_d).read_bytes()
    with patch.object(rr, "find_candidates", return_value={"repairable": [_d], "no_source": []}), \
            patch.object(quality, "_save_quality_log") as _sv5:
        _r = rr.repair_resting_hr()
    check("changed meanwhile: a day that is no longer in the import form is skipped, not written, not recorded",
          _r["items"] == [{"date": _d, "status": "skipped"}] and (_r["ok"], _r["failed"]) == (0, 0)
          and _raw_path(_d).read_bytes() == _ob and _sv5.call_count == 0)

with _isolated_log_env("rr_nolog") as _b:
    _d = "2025-07-01"
    _setup(_b, {_d: _imp_raw(_d, 60)}, {_d: _src(_d, 57, 60)}, log_dates=["2025-07-09"])
    _r = rr.repair_resting_hr()
    check("no log entry: the day is still corrected, no entry is created in the quality log",
          _r["ok"] == 1 and _load_raw(_d)["heart_rates"]["restingHeartRate"] == 57
          and list(_qdays()) == ["2025-07-09"])

# ══════════════════════════════════════════════════════════════════════════════
#  7. Explicit folders — popup and scheduler pass the archive of the settings
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_dirs") as _b:
    _other = _b / "other_archive"
    _put(_other / "raw" / "garmin_raw_2025-07-10.json", _imp_raw("2025-07-10", 60))
    _put(_other / "raw" / "garmin_raw_2025-07-11.json", _imp_raw("2025-07-11", 61))
    _put(_other / "source" / "garmin_source_2025-07-10.json", _src("2025-07-10", 57, 60))
    _setup(_b, {"2025-07-12": _imp_raw("2025-07-12", 62)}, {"2025-07-12": _src("2025-07-12", 58, 62)})
    check("find (explicit folders): scans the given archive, not the configured one",
          rr.find_candidates(raw_dir=_other / "raw", source_dir=_other / "source")
          == {"repairable": ["2025-07-10"], "no_source": ["2025-07-11"]})
    check("find (explicit folders): without arguments the configured archive is used as before",
          rr.find_candidates() == {"repairable": ["2025-07-12"], "no_source": []})
    check("find (explicit folders): a missing raw folder finds nothing",
          rr.find_candidates(raw_dir=_b / "nowhere", source_dir=_b / "nowhere")
          == {"repairable": [], "no_source": []})

# ══════════════════════════════════════════════════════════════════════════════
#  8. Scheduler hint — scheduler/daily_update.py::_check_resting_hr_repair
# ══════════════════════════════════════════════════════════════════════════════
import importlib.util
from pathlib import Path

_du_spec = importlib.util.spec_from_file_location(
    "daily_update_rr", Path(__file__).resolve().parent.parent / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)

with _isolated_log_env("rr_sched") as _b:
    _arch = _b / "archive"
    _put(_arch / "garmin_data" / "raw" / "garmin_raw_2025-07-10.json", _imp_raw("2025-07-10", 60))
    _put(_arch / "garmin_data" / "raw" / "garmin_raw_2025-07-11.json", _imp_raw("2025-07-11", 61))
    _put(_arch / "garmin_data" / "raw" / "garmin_raw_2025-07-12.json", _api_raw("2025-07-12"))
    _put(_arch / "garmin_data" / "source" / "garmin_source_2025-07-10.json", _src("2025-07-10", 57, 60))
    _before = {p.name: p.read_bytes() for p in (_arch / "garmin_data").rglob("*.json")}
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n = _du._check_resting_hr_repair(_arch)
    check("scheduler hint: counts only the days that can be corrected and warns with the number, nothing else",
          _n == 1 and _rec.m["warning"] == [
              "  1 imported day(s) have a wrong resting heart rate.",
              "  Open the app and run Sync Garmin once to correct them."]
          and not _rec.m["error"])
    check("scheduler hint: it only looks — no file of the archive changes",
          {p.name: p.read_bytes() for p in (_arch / "garmin_data").rglob("*.json")} == _before)
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n_none = _du._check_resting_hr_repair(_b / "no_archive_here")
    check("scheduler hint: no archive folder -> 0 and no warning", _n_none == 0 and not _rec.m["warning"])
    _rec = _Rec()
    with patch.object(_du, "log", _rec), patch.object(rr, "find_candidates", side_effect=RuntimeError("boom")):
        _n_err = _du._check_resting_hr_repair(_arch)
    check("scheduler hint: an error in the scan never stops the run — 0 and no warning",
          _n_err == 0 and not _rec.m["warning"] and not _rec.m["error"])

# ══════════════════════════════════════════════════════════════════════════════
#  9. Shared quality log (Baustein 2f) — the caller's object, not a copy of its own
# ══════════════════════════════════════════════════════════════════════════════
with _isolated_log_env("rr_shared") as _b:
    _D = ["2025-08-01", "2025-08-02"]
    _setup(_b, {d: _imp_raw(d, 60) for d in _D}, {d: _src(d, 57, 60) for d in _D}, log_dates=_D + ["2025-08-09"])
    _shared = quality._load_quality_log()
    _other_before = json.loads(json.dumps([e for e in _shared["days"] if e["date"] == "2025-08-09"][0]))
    with patch.object(quality, "_load_quality_log", wraps=quality._load_quality_log) as _ld, \
            patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
        _r = rr.repair_resting_hr(quality_data=_shared)
    check("shared quality log: the object of the caller is updated in place — last_checked of the repaired days",
          _r["ok"] == 2 and all(e["last_checked"] == _TODAY for e in _shared["days"] if e["date"] in _D))
    check("shared quality log: it is not loaded again, and exactly that object is saved, once",
          _ld.call_count == 0 and _sv.call_count == 1 and _sv.call_args.args[0] is _shared)
    check("shared quality log: an entry that was not repaired stays as it was",
          [e for e in _shared["days"] if e["date"] == "2025-08-09"][0] == _other_before)

summary()
