#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_normalizer.py — garmin_bulk_normalizer (v1.7.6)

Run from the project folder:
    python tests/test_bulk_normalizer.py

Part 4a: the day boundaries (decision E27, with the change to E6). All windows
are synthetic; the expected UTC instants are computed here independently with
datetime/timezone. Shape of the windows as in raw/stats of the archive:
wellnessStartTimeGmt/Local and wellnessEndTimeGmt/Local.
"""

import ast
import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gla_testenv  # noqa: F401  sets up sys.path; must precede garmin_* imports
from support import check, section, summary

section("B3. garmin_bulk_normalizer — day boundaries (v1.7.6, E27/E6)")
import garmin_bulk_normalizer as nz


# ── Synthetic windows ──────────────────────────────────────────────────────────
def _ts(y, m, d, h=0, mi=0, s=0):
    return int(datetime(y, m, d, h, mi, s, tzinfo=timezone.utc).timestamp())


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.0")


def _day(d, start_off_h, end_off_h, start_local=None, end_local=None):
    """raw/stats of one day: window from local midnight to local midnight; the offsets
    (local minus GMT, hours) are the ones at the start and at the end of the window."""
    m = datetime.strptime(d, "%Y-%m-%d")
    sl = start_local or m
    el = end_local or (m + timedelta(days=1))
    return {"wellnessStartTimeGmt": _fmt(sl - timedelta(hours=start_off_h)),
            "wellnessStartTimeLocal": _fmt(sl),
            "wellnessEndTimeGmt": _fmt(el - timedelta(hours=end_off_h)),
            "wellnessEndTimeLocal": _fmt(el)}


def _dates(first, n):
    return [(datetime.strptime(first, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _plain(first, n, off=1.0, skip=()):
    return {d: _day(d, off, off) for d in _dates(first, n) if d not in skip}


def _year(correct=True):
    """2024 in the EU rule: +1 / +2 / +1. correct=True: the transition days as the API
    describes them (23 h and 25 h windows); False: as the import wrote them for 10 of
    15 transition days (24 h window, the end offset also at the start)."""
    out = {}
    for d in _dates("2024-01-01", 366):
        if d < "2024-03-31":
            so = eo = 1
        elif d == "2024-03-31":
            so, eo = (1, 2) if correct else (2, 2)
        elif d < "2024-10-27":
            so = eo = 2
        elif d == "2024-10-27":
            so, eo = (2, 1) if correct else (1, 1)
        else:
            so = eo = 1
        out[d] = _day(d, so, eo)
    return out


def _key(p):
    return {d: (x.start_utc, x.end_utc, x.offset_start_hours, x.offset_end_hours) for d, x in p.days.items()}


# ── A plain stretch of days ────────────────────────────────────────────────────
p = nz.plan_days(_plain("2024-02-01", 5))
check("plain days: the first day has no known boundary before it -> unknown", p.unknown == ["2024-02-01"])
check("plain days: the other four days are planned", sorted(p.days) == _dates("2024-02-02", 4))
d2 = p.days["2024-02-02"]
check("plain days: boundaries are local midnight minus the offset (+1 h -> 23:00Z the evening before)",
      (d2.start_utc, d2.end_utc) == (_ts(2024, 2, 1, 23), _ts(2024, 2, 2, 23)))
check("plain days: offsets, no transition, source is the end offset of the previous day",
      (d2.offset_start_hours, d2.offset_end_hours, d2.dst_transition, d2.offset_source) == (1.0, 1.0, False, "prev_day_end"))
check("plain days: nothing disagrees", p.disagreements == [])
half = nz.plan_days(_plain("2024-02-01", 3, off=5.5)).days["2024-02-02"]
check("a half-hour zone (+5.5 h) works: instants and hours",
      half.start_utc == _ts(2024, 2, 1, 18, 30) and (half.offset_start_hours, half.offset_end_hours) == (5.5, 5.5))
check("negative offsets work (-5 h)",
      nz.plan_days(_plain("2024-02-01", 3, off=-5.0)).days["2024-02-02"].start_utc == _ts(2024, 2, 2, 5))

# ── A whole year with both transitions ─────────────────────────────────────────
for label, year in (("API form", _year(True)), ("import form", _year(False))):
    py = nz.plan_days(year)
    lengths = Counter((x.end_utc - x.start_utc) // 3600 for x in py.days.values())
    check(f"year 2024 ({label}): 365 days planned, only the first one unknown",
          len(py.days) == 365 and py.unknown == ["2024-01-01"])
    check(f"year 2024 ({label}): 23 h on the spring day, 25 h on the autumn day, 24 h on all others",
          lengths == Counter({24: 363, 23: 1, 25: 1}))
    check(f"year 2024 ({label}): the spring day runs from 23:00Z to 22:00Z",
          (py.days["2024-03-31"].start_utc, py.days["2024-03-31"].end_utc) == (_ts(2024, 3, 30, 23), _ts(2024, 3, 31, 22)))
    check(f"year 2024 ({label}): the autumn day runs from 22:00Z to 23:00Z",
          (py.days["2024-10-27"].start_utc, py.days["2024-10-27"].end_utc) == (_ts(2024, 10, 26, 22), _ts(2024, 10, 27, 23)))
    ds = sorted(py.days)
    check(f"year 2024 ({label}): consecutive days tile exactly (no gap, no overlap)",
          all(py.days[a].end_utc == py.days[b].start_utc for a, b in zip(ds, ds[1:])))
    spring, autumn = py.days["2024-03-31"], py.days["2024-10-27"]
    check(f"year 2024 ({label}): transition days carry both offsets and the flag",
          (spring.offset_start_hours, spring.offset_end_hours, spring.dst_transition) == (1.0, 2.0, True)
          and (autumn.offset_start_hours, autumn.offset_end_hours, autumn.dst_transition) == (2.0, 1.0, True)
          and not py.days["2024-06-01"].dst_transition)

api_plan, imp_plan = nz.plan_days(_year(True)), nz.plan_days(_year(False))
check("the import form of the transition days gives the same plan as the API form", _key(api_plan) == _key(imp_plan))
check("API form: no day disagrees with the boundary used", api_plan.disagreements == [])
check("import form: exactly the two wrongly described transition days are reported",
      imp_plan.disagreements == ["2024-03-31", "2024-10-27"])

# ── Which day does an instant belong to ────────────────────────────────────────
check("day_for: the first instant of a day belongs to it, one second earlier to the day before",
      api_plan.day_for(_ts(2024, 3, 30, 23)) == "2024-03-31" and api_plan.day_for(_ts(2024, 3, 30, 22, 59, 59)) == "2024-03-30")
check("day_for: the last second of the 23 h day, and the first of the next",
      api_plan.day_for(_ts(2024, 3, 31, 21, 59, 59)) == "2024-03-31" and api_plan.day_for(_ts(2024, 3, 31, 22)) == "2024-04-01")
check("day_for: the 25 h day takes both hours around the change back",
      api_plan.day_for(_ts(2024, 10, 26, 22)) == "2024-10-27" and api_plan.day_for(_ts(2024, 10, 27, 0, 30)) == "2024-10-27"
      and api_plan.day_for(_ts(2024, 10, 27, 22, 59, 59)) == "2024-10-27" and api_plan.day_for(_ts(2024, 10, 27, 23)) == "2024-10-28")
check("day_for: before the first planned day and after the last one -> None",
      api_plan.day_for(_ts(2024, 1, 1, 12)) is None and api_plan.day_for(_ts(2025, 1, 2, 0)) is None)
check("day_for: accepts a float (seconds)", api_plan.day_for(float(_ts(2024, 6, 1, 12))) == "2024-06-01")
_last = max(api_plan.days.values(), key=lambda x: x.start_utc)
check("day_for: the end of the last planned day is already outside (end exclusive)",
      api_plan.day_for(_last.end_utc - 1) == _last.date and api_plan.day_for(_last.end_utc) is None)

# ── Missing days (E6, several in a row) ────────────────────────────────────────
miss = nz.plan_days(_plain("2024-02-01", 10, skip=("2024-02-04", "2024-02-05", "2024-02-06")))
check("three missing days in a row with the same offset on both sides: every day is planned",
      miss.unknown == ["2024-02-01"] and len(miss.days) == 9)
check("missing days: the boundaries come from the neighbours, marked as such",
      miss.days["2024-02-05"].offset_source == "neighbours" and miss.days["2024-02-03"].offset_source == "prev_day_end")
check("missing days: day 2024-02-05 runs from 23:00Z to 23:00Z",
      (miss.days["2024-02-05"].start_utc, miss.days["2024-02-05"].end_utc) == (_ts(2024, 2, 4, 23), _ts(2024, 2, 5, 23)))

gap = {**_plain("2024-02-01", 3, off=1.0), **{d: _day(d, 2, 2) for d in _dates("2024-02-05", 4)}}
pg = nz.plan_days(gap)
check("a gap whose neighbours disagree (a change inside it): the days around it are not planned and are counted",
      pg.unknown == ["2024-02-01", "2024-02-04", "2024-02-05"] and sorted(pg.days) == ["2024-02-02", "2024-02-03"] + _dates("2024-02-06", 3))
check("a gap whose neighbours disagree: no instant inside the unknown days is assigned",
      pg.day_for(_ts(2024, 2, 4, 12)) is None and pg.day_for(_ts(2024, 2, 5, 12)) is None)
check("a gap whose neighbours disagree: the end of the last planned day before it is not assigned to anything",
      pg.day_for(_ts(2024, 2, 3, 22, 59, 59)) == "2024-02-03" and pg.day_for(_ts(2024, 2, 3, 23)) is None)

# ── Partial days and invalid windows ───────────────────────────────────────────
part = _plain("2024-02-01", 6)
part["2024-02-03"] = _day("2024-02-03", 1, 1, end_local=datetime(2024, 2, 3, 5, 45))
pp = nz.plan_days(part)
check("a partial window: its day is still planned, the end boundary comes from the neighbours",
      "2024-02-03" in pp.days and pp.days["2024-02-03"].offset_source == "neighbours" and pp.unknown == ["2024-02-01"])
check("a partial window is not used as the source of the next boundary (full-day windows only)",
      pp.days["2024-02-03"].end_utc == _ts(2024, 2, 3, 23))

tol = _plain("2024-02-01", 4)
tol["2024-02-02"] = _day("2024-02-02", 1, 1, end_local=datetime(2024, 2, 2, 23, 59, 59))
check("a window ending one second before midnight counts as a full day",
      nz.plan_days(tol).days["2024-02-03"].offset_source == "prev_day_end")
tol["2024-02-02"] = _day("2024-02-02", 1, 1, end_local=datetime(2024, 2, 2, 23, 59, 0))
check("a window ending one minute before midnight does not",
      nz.plan_days(tol).days["2024-02-03"].offset_source == "neighbours")

bad = _plain("2024-02-01", 6)
bad["2024-02-03"] = None
bad["2024-02-04"] = {"wellnessStartTimeGmt": "nonsense"}
bad["2024-02-05"] = _day("2024-02-05", 15, 15)
check("unusable windows (None, wrong fields, an offset over 14 h) count as missing",
      nz.plan_days(bad).days.keys() == nz.plan_days(_plain("2024-02-01", 6, skip=("2024-02-03", "2024-02-04", "2024-02-05"))).days.keys())
odd = nz.plan_days({**_plain("2024-02-01", 4), "2024-02-02": _day("2024-02-02", 1.1, 1.1)})
check("a window whose offset is not a multiple of 15 minutes is unusable (the day is planned from its neighbours)",
      odd.days["2024-02-02"].offset_source == "neighbours" and odd.days["2024-02-02"].offset_start_hours == 1.0)
# end exactly at midnight (so it would pass as a full day) but the start lies behind the end: garbage, with a wrong offset
backwards = {**_plain("2024-02-01", 5), "2024-02-02": _day("2024-02-02", 2, 2, start_local=datetime(2024, 2, 3, 6, 0))}
pb = nz.plan_days(backwards)
check("a window that ends before it starts is unusable: its (wrong) end offset does not set a boundary, the neighbours do",
      pb.days["2024-02-03"].offset_start_hours == 1.0 and pb.days["2024-02-03"].offset_source == "neighbours"
      and pb.days["2024-02-03"].start_utc == _ts(2024, 2, 2, 23))

late = {**_plain("2024-02-01", 6, skip=("2024-02-03",)),
        "2024-02-04": _day("2024-02-04", 1, 1, start_local=datetime(2024, 2, 4, 8, 0))}
check("a neighbour whose window starts late in the day (not at midnight) is no sample of the midnight: the days next to the gap are left out",
      nz.plan_days(late).unknown == ["2024-02-01", "2024-02-03", "2024-02-04"])

# a missing day right before a transition day: the start offset of the transition day is a sample
# at exactly that midnight (right in the API form), so the neighbours agree there; in the import form
# that start offset is the wrong one and the two sides disagree -> the days are left out, not guessed
for label, correct, expect_unknown in (("API form", True, ["2024-01-01"]),
                                       ("import form", False, ["2024-01-01", "2024-03-30", "2024-03-31"])):
    y = _year(correct)
    del y["2024-03-30"]
    py2 = nz.plan_days(y)
    check(f"a missing day before the spring day ({label}): " + ("planned from the neighbours" if correct else "not planned, counted"),
          py2.unknown == expect_unknown)
    if correct:
        check("a missing day before the spring day (API form): the spring day keeps its 23 hours",
              py2.days["2024-03-31"].end_utc - py2.days["2024-03-31"].start_utc == 23 * 3600)

check("an empty input gives an empty plan",
      (lambda e: e.days == {} and e.unknown == [] and e.disagreements == [] and e.day_for(0) is None)(nz.plan_days({})))
check("keys that are not dates are ignored",
      nz.plan_days({**_plain("2024-02-01", 3), "garbage": _day("2024-02-01", 1, 1)}).days.keys() == nz.plan_days(_plain("2024-02-01", 3)).days.keys())

# ── Edges of the range and the date arguments ──────────────────────────────────
last_part = _plain("2024-02-01", 5)
last_part["2024-02-05"] = _day("2024-02-05", 1, 1, end_local=datetime(2024, 2, 5, 14, 0))
check("the last day with a partial window (today) is not planned",
      "2024-02-05" not in nz.plan_days(last_part).days and "2024-02-05" in nz.plan_days(last_part).unknown)
check("with one extra day before the range the first day is planned",
      nz.plan_days(_plain("2024-01-31", 6), first_date="2024-02-01").unknown == [])
ranged = nz.plan_days(_plain("2024-02-01", 10), first_date="2024-02-04", last_date="2024-02-06")
check("first_date/last_date restrict the days considered; the windows outside are still used",
      sorted(ranged.days) == _dates("2024-02-04", 3) and ranged.unknown == [])

# ── Travel across time zones (documented behaviour) ───────────────────────────
travel = {**_plain("2024-02-01", 3, off=1.0), **{d: _day(d, -5, -5) for d in _dates("2024-02-04", 3)}}
pt = nz.plan_days(travel)
check("travel: the boundary follows the previous day, the new day is reported as disagreeing and flagged",
      pt.days["2024-02-04"].offset_start_hours == 1.0 and pt.days["2024-02-04"].offset_end_hours == -5.0
      and pt.days["2024-02-04"].dst_transition and "2024-02-04" in pt.disagreements)

# ── Input is not changed; result is plain data ─────────────────────────────────
src = _year(False)
before = copy.deepcopy(src)
nz.plan_days(src)
check("the input windows are not modified", src == before)
check("DayPlan fields", nz.DayPlan._fields == ("date", "start_utc", "end_utc", "offset_start_hours", "offset_end_hours",
                                               "dst_transition", "offset_source"))

# ══════════════════════════════════════════════════════════════════════════════
#  Part 4b — the samples
# ══════════════════════════════════════════════════════════════════════════════
section("B3b. garmin_bulk_normalizer — samples (v1.7.6, 4b)")
E = nz.FIT_EPOCH_OFFSET
check("the FIT epoch offset is 1989-12-31 00:00 UTC in Unix seconds",
      E == 631065600 == int(datetime(1989, 12, 31, tzinfo=timezone.utc).timestamp()))


def _full(unix, bpm):
    return {253: unix - E, 27: bpm}


def _small(unix, bpm):
    return {26: (unix - E) & 0xFFFF, 27: bpm}


# ── Completing a 16-bit timestamp ──────────────────────────────────────────────
check("16-bit: a small step forward", nz.complete_timestamp(1000, 1060) == 1060)
check("16-bit: the same value", nz.complete_timestamp(1000, 1000) == 1000)
check("16-bit: roll-over of the low 16 bits (65530 -> 10 is 16 s later)", nz.complete_timestamp(65530, 10) == 65546)
check("16-bit: roll-over in a later cycle", nz.complete_timestamp(3 * 65536 + 65500, 20) == 3 * 65536 + 65556)
last = 100000                                              # low 16 bits 34464
check("16-bit: a record one minute BEFORE the last one is a small step back, not a roll-over (found in the export)",
      nz.complete_timestamp(last, (last - 60) & 0xFFFF) == last - 60)
check("16-bit: exactly half the range ahead is read as forward, one more as backward",
      nz.complete_timestamp(0, 0x8000) == 0x8000 and nz.complete_timestamp(0x20000, 0x20000 + 0x8001 - 0x10000 & 0xFFFF) == 0x20000 + 0x8001 - 0x10000)
check("16-bit: a step back across the low-16-bit boundary", nz.complete_timestamp(70000, (70000 - 5000) & 0xFFFF) == 65000)

# ── One file ───────────────────────────────────────────────────────────────────
T0 = _ts(2024, 2, 3, 12)
samples, counts = nz.file_samples([_full(T0, 60), _small(T0 + 60, 62), _small(T0 + 120, 64)])
check("a file: the full timestamp is the reference, 16-bit timestamps follow; Unix seconds, in order",
      samples == [(T0, 60), (T0 + 60, 62), (T0 + 120, 64)])
check("a file: counters of a clean file", (counts["records"], counts["before_first_full"], counts["no_timestamp"],
                                           counts["no_heart_rate"], counts["zero_heart_rate"]) == (3, 0, 0, 0, 0))
samples, counts = nz.file_samples([_small(T0, 60), _full(T0 + 60, 62), _small(T0 + 120, 64)])
check("a 16-bit record before the first full timestamp is dropped and counted",
      samples == [(T0 + 60, 62), (T0 + 120, 64)] and counts["before_first_full"] == 1)
samples, counts = nz.file_samples([{253: T0 - E, 27: None}, _small(T0 + 60, 61), {253: T0 + 120 - E, 27: 0}, _small(T0 + 180, 63)])
check("a record without a heart rate still sets the reference for the next 16-bit record; heart rate 0 is dropped and counted",
      samples == [(T0 + 60, 61), (T0 + 180, 63)] and counts["no_heart_rate"] == 1 and counts["zero_heart_rate"] == 1)
samples, counts = nz.file_samples([_full(T0, 60), {27: 70}, _small(T0 + 60, 62)])
check("a record without any timestamp is dropped and counted", samples == [(T0, 60), (T0 + 60, 62)] and counts["no_timestamp"] == 1)
samples, _ = nz.file_samples([_full(T0, 60), _small(T0 + 120, 64), _small(T0 + 60, 62)])
check("records one minute out of order do not jump 18 hours", [s[0] for s in samples] == [T0, T0 + 120, T0 + 60])
check("an empty file gives nothing", nz.file_samples([]) == ([], {"records": 0, "before_first_full": 0, "no_timestamp": 0,
                                                                   "no_heart_rate": 0, "zero_heart_rate": 0}))
check("heart rate 1 and 254 are kept",
      [s[1] for s in nz.file_samples([_full(T0, 1), _full(T0 + 1, 254)])[0]] == [1, 254])
recs = [_full(T0, 60), _small(T0 + 60, 62)]
recs_before = copy.deepcopy(recs)
nz.file_samples(recs)
check("the records are not modified", recs == recs_before)

# ── Collecting, assigning to days ──────────────────────────────────────────────
pl = nz.plan_days(_plain("2024-02-01", 6))                 # planned: 02-02 .. 02-06 (23:00Z the evening before to 23:00Z)


def _rf(*pairs):
    return [_full(u, b) for u, b in pairs]


a_, b_, c_, d_, e_ = (_ts(2024, 2, 2, 22, 59, 59), _ts(2024, 2, 2, 23), _ts(2024, 2, 3, 22, 59, 59),
                      _ts(2024, 2, 3, 23), _ts(2024, 2, 1, 12))
col = nz.SampleCollector(pl)
col.add_file("h1", 1000, _rf((a_, 61), (b_, 62), (c_, 63), (d_, 64), (e_, 65)))
run = col.finish()
check("samples go to the day whose [start, end) holds them: the first second of a day, the last second, the next day",
      [(d, [v for v in s.values]) for d, s in sorted(run.days.items())] ==
      [("2024-02-02", [[a_ * 1000, 61]]), ("2024-02-03", [[b_ * 1000, 62], [c_ * 1000, 63]]), ("2024-02-04", [[d_ * 1000, 64]])])
check("values are [milliseconds UTC, bpm]", run.days["2024-02-03"].values[0] == [b_ * 1000, 62])
check("a sample on a day that is not planned is counted with its UTC date",
      run.stats.unassigned == 1 and run.stats.unassigned_by_date == {"2024-02-01": 1})
check("planned days without any sample are listed",
      run.stats.planned_days_without_samples == ["2024-02-05", "2024-02-06"] and run.stats.days_with_samples == 3)
check("counters add up: kept = assigned + unassigned, assigned = values + duplicates",
      run.stats.samples_kept == 5 and run.stats.files == 1 and run.stats.records == 5
      and run.stats.samples_kept == sum(len(s.values) for s in run.days.values()) + run.stats.unassigned
      + run.stats.duplicates_same + run.stats.duplicates_conflict)
check("the source files of a day are the hashes of the files that put samples on it",
      run.days["2024-02-03"].source_files == ["h1"])
check("finish() can be called again with the same result", col.finish().days == run.days)
check("iter_days() yields the same days one by one, in date order",
      [d.date for d in col.iter_days()] == sorted(run.days) and {d.date: d for d in col.iter_days()} == run.days)
check("iter_days() is lazy: the first day can be taken without resolving the others",
      next(iter(col.iter_days())).date == "2024-02-02")
check("stats() gives the same counters as finish() and does not need the days to be iterated", col.stats() == run.stats)
check("iter_days() and stats() can be called again and again",
      list(col.iter_days()) == list(col.iter_days()) and col.stats() == col.stats())

empty = nz.SampleCollector(pl).finish()
check("nothing added: no days, all planned days listed as without samples",
      empty.days == {} and empty.stats.files == 0 and empty.stats.planned_days_without_samples == sorted(pl.days))

# ── Duplicates (E16) ───────────────────────────────────────────────────────────
T = _ts(2024, 2, 3, 12)


def _two(first, second):
    c = nz.SampleCollector(pl)
    for h, tc, b in (first, second):
        c.add_file(h, tc, _rf((T, b)))
    return c.finish()


X, Y = ("x", 200, 70), ("y", 100, 80)
r1, r2 = _two(X, Y), _two(Y, X)
check("duplicate seconds: the file created first wins, the other value is counted as a conflict",
      r1.days["2024-02-03"].values == [[T * 1000, 80]] and r1.stats.duplicates_conflict == 1 and r1.stats.duplicates_same == 0)
check("duplicate seconds: the result does not depend on the order the files arrive in", r1.days == r2.days)
check("duplicate seconds: both files are named as sources of the day", r1.days["2024-02-03"].source_files == ["x", "y"])
check("duplicate seconds: the conflict is counted for the day as well",
      r1.days["2024-02-03"].duplicates_conflict == 1 and r1.days["2024-02-03"].duplicates_same == 0)
check("a file without time_created ranks last",
      _two(("a", None, 90), ("b", 500, 71)).days["2024-02-03"].values == [[T * 1000, 71]])
check("with the same creation time the smaller hash wins",
      _two(("b", 100, 72), ("a", 100, 73)).days["2024-02-03"].values == [[T * 1000, 73]]
      and _two(("a", 100, 73), ("b", 100, 72)).days["2024-02-03"].values == [[T * 1000, 73]])
rs = _two(("p", 100, 75), ("q", 200, 75))
check("duplicate seconds with the same value are counted separately, one sample stays",
      rs.days["2024-02-03"].values == [[T * 1000, 75]] and rs.stats.duplicates_same == 1 and rs.stats.duplicates_conflict == 0)
check("a file without time_created and one with it, both None: smaller hash first",
      _two(("m", None, 10), ("k", None, 11)).days["2024-02-03"].values == [[T * 1000, 11]])

# ── Order of arrival does not matter, values are sorted ───────────────────────
f1 = _rf((_ts(2024, 2, 3, 13), 60), (_ts(2024, 2, 3, 11), 58))
f2 = _rf((_ts(2024, 2, 3, 12), 59), (T + 5, 66))
ca = nz.SampleCollector(pl)
ca.add_file("f1", 10, f1)
ca.add_file("f2", 20, f2)
cb = nz.SampleCollector(pl)
cb.add_file("f2", 20, f2)
cb.add_file("f1", 10, f1)
check("values of a day are sorted by time", [v[0] for v in ca.finish().days["2024-02-03"].values] ==
      sorted(v[0] for v in ca.finish().days["2024-02-03"].values))
check("any order of arrival gives the same days and the same statistics",
      ca.finish().days == cb.finish().days and ca.finish().stats == cb.finish().stats)

cc = nz.SampleCollector(pl)
cc.add_file("hi", 1, _rf((T, 200), (T + 1, 254), (T + 2, 127), (T + 3, 128)))
check("heart rates above 127 are stored correctly (unsigned)",
      [v[1] for v in cc.finish().days["2024-02-03"].values] == [200, 254, 127, 128])
cm = nz.SampleCollector(pl)
for i in range(300):
    cm.add_file(f"{i:03d}", i, _rf((T + i, 60 + i % 100)))
rm = cm.finish()
check("more than 255 files are supported (the file index is not a byte)",
      len(rm.days["2024-02-03"].values) == 300 and len(rm.days["2024-02-03"].source_files) == 300 and rm.stats.files == 300)
cr = nz.SampleCollector(pl)
cr.add_file("late", 1, _rf((_ts(2024, 2, 5, 12), 70)))
cr.add_file("mid", 2, _rf((_ts(2024, 2, 4, 12), 71)))
cr.add_file("early", 3, _rf((_ts(2024, 2, 3, 12), 72)))
check("days come out in date order whatever order the files arrived in",
      [d.date for d in cr.iter_days()] == ["2024-02-03", "2024-02-04", "2024-02-05"] and list(cr.finish().days) == ["2024-02-03", "2024-02-04", "2024-02-05"])

# ── The transition days of 2024 (API form of the windows) ─────────────────────
ply = nz.plan_days(_year(True))
cd = nz.SampleCollector(ply)
cd.add_file("dst", 1, _rf((_ts(2024, 3, 30, 22, 59, 59), 50), (_ts(2024, 3, 30, 23), 51), (_ts(2024, 3, 31, 21, 59, 59), 52),
                          (_ts(2024, 3, 31, 22), 53), (_ts(2024, 10, 26, 21, 59, 59), 54), (_ts(2024, 10, 26, 22), 55),
                          (_ts(2024, 10, 27, 22, 59, 59), 56), (_ts(2024, 10, 27, 23), 57)))
rd = cd.finish()
check("spring day (23 h): 23:00Z the evening before to 21:59:59Z belong to it, 22:00Z to the next day",
      [v[1] for v in rd.days["2024-03-31"].values] == [51, 52] and [v[1] for v in rd.days["2024-04-01"].values] == [53]
      and [v[1] for v in rd.days["2024-03-30"].values] == [50])
check("autumn day (25 h): 22:00Z the evening before to 22:59:59Z belong to it, 23:00Z to the next day",
      [v[1] for v in rd.days["2024-10-27"].values] == [55, 56] and [v[1] for v in rd.days["2024-10-26"].values] == [54]
      and [v[1] for v in rd.days["2024-10-28"].values] == [57])

# ── Several files, counters, unknown days ─────────────────────────────────────
cs = nz.SampleCollector(pl)
cs.add_file("g1", 1, [_full(T, 60), {253: T + 60 - E, 27: None}, {253: T + 120 - E, 27: 0}, _small(T + 180, 63)])
cs.add_file("g2", 2, [{253: T + 240 - E, 27: None}])
rs2 = cs.finish()
check("counters over several files: records, dropped records by reason, files",
      (rs2.stats.files, rs2.stats.records, rs2.stats.samples_kept, rs2.stats.no_heart_rate, rs2.stats.zero_heart_rate)
      == (2, 5, 2, 2, 1))
check("a file whose records give no sample is still counted and names no day", rs2.days["2024-02-03"].source_files == ["g1"])

gapplan = nz.plan_days(gap)
cg = nz.SampleCollector(gapplan)
cg.add_file("u", 1, _rf((_ts(2024, 2, 4, 12), 70), (_ts(2024, 2, 5, 12), 71), (_ts(2024, 2, 6, 12), 72)))
rg = cg.finish()
check("samples on days that could not be planned (neighbours disagree) are counted by UTC date, not guessed",
      rg.stats.unassigned_by_date == {"2024-02-04": 1, "2024-02-05": 1} and sorted(rg.days) == ["2024-02-06"])

# ── Leaf node, no output channel ───────────────────────────────────────────────
_tree = ast.parse(Path(nz.__file__).read_text(encoding="utf-8"))
_imports = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Import):
        _imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _imports.add(_n.module.split(".")[0])
check("leaf node: imports standard library only (no project module, no garmin_config)",
      _imports <= {"array", "bisect", "datetime", "typing", "__future__"})
check("no logging and no print",
      "logging" not in _imports and not any(
          isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree)))

summary()
