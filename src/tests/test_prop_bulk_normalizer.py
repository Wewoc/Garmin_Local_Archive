#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_prop_bulk_normalizer.py — property tests of garmin_bulk_normalizer (v1.7.6.11)

Run from the project folder:
    python tests/test_prop_bulk_normalizer.py

The day boundaries (plan_days) and the samples (file_samples, SampleCollector) with generated
inputs; the hand-picked cases stay in test_bulk_normalizer.py. The module is a pure function
of its input, so no folder is needed:
  - planned days tile exactly (no gap, no overlap), length = 24 h + the change of the offset,
    and a planned day is never wrong: nothing is guessed, a day without proof is `unknown`
  - day_for() is the inverse of the plan
  - 16-bit timestamps are completed to the nearest value, never by a whole range
  - the result of a run does not depend on the order the files arrive in (E16), and the
    sample of the smaller (time_created, hash) rank wins a duplicate second
  - the counters add up
"""

import copy
from datetime import date, datetime, timedelta

from gla_testenv import cfg  # noqa: F401 - sets up the environment before any garmin_* import
from support import check, section, summary
from prop_support import prop, given, st, DATES, JSON_VALUES

import garmin_bulk_normalizer as nz

_FMT = "%Y-%m-%dT%H:%M:%S.0"
_EPOCH = datetime(1970, 1, 1)
_HOUR = 3600


def _stats(day, start_offset_s, end_offset_s):
    """The window of a local day as raw/stats holds it: local midnight to local midnight."""
    start_local = datetime.combine(day, datetime.min.time())
    end_local = start_local + timedelta(days=1)
    return {
        "wellnessStartTimeLocal": start_local.strftime(_FMT),
        "wellnessStartTimeGmt": (start_local - timedelta(seconds=start_offset_s)).strftime(_FMT),
        "wellnessEndTimeLocal": end_local.strftime(_FMT),
        "wellnessEndTimeGmt": (end_local - timedelta(seconds=end_offset_s)).strftime(_FMT),
    }


def _partial_stats(day, offset_s, hours):
    """A window that starts at local midnight and ends `hours` later, both ends with the same offset."""
    stats = _stats(day, offset_s, offset_s)
    end_local = datetime.combine(day, datetime.min.time()) + timedelta(hours=hours)
    stats["wellnessEndTimeLocal"] = end_local.strftime(_FMT)
    stats["wellnessEndTimeGmt"] = (end_local - timedelta(seconds=offset_s)).strftime(_FMT)
    return stats


def _utc_of_local_midnight(day, offset_s):
    return int((datetime.combine(day, datetime.min.time()) - _EPOCH).total_seconds()) - offset_s


@st.composite
def timelines(draw, never_back=True):
    """(first day, offsets at the n + 1 local midnights, windows {date: stats}, dropped days, days with a wrong start).

    never_back: the offset never returns to a value it had before (a time zone is not left and
    entered again) — the one assumption of the neighbour rule, see the findings at the end.
    """
    n = draw(st.integers(2, 14))
    first = draw(st.dates(min_value=date(2013, 1, 1), max_value=date(2034, 6, 1)))
    pool = draw(st.lists(st.integers(-56, 56), min_size=1, max_size=3, unique=True).map(lambda v: [x * 900 for x in v]))
    if never_back:                      # every value is used once, in ascending order
        cut_points = sorted(draw(st.sets(st.integers(1, n), max_size=len(pool) - 1)))
        values = sorted(pool)
    else:                               # a value may come back (A, B, A)
        cut_points = sorted(draw(st.sets(st.integers(1, n), max_size=4)))
        values = [draw(st.sampled_from(pool)) for _ in range(len(cut_points) + 1)]
    offsets, run = [], 0
    for i in range(n + 1):
        while run < len(cut_points) and i >= cut_points[run]:
            run += 1
        offsets.append(values[run])
    days = [first + timedelta(days=i) for i in range(n)]
    dropped = {d for d in days if draw(st.integers(0, 3)) == 0}
    wrong_start = {d for i, d in enumerate(days) if offsets[i] != offsets[i + 1] and draw(st.booleans())}
    # a partial window ends before local midnight (the device was read out or stopped early); its end offset is the
    # one of that moment, i.e. the offset the day started with, not the one at the following midnight
    partial = {d for d in days if d not in dropped and draw(st.integers(0, 5)) == 0}
    windows = {}
    for i, d in enumerate(days):
        if d in dropped:
            continue
        start_offset = offsets[i + 1] if d in wrong_start else offsets[i]
        if d in partial:
            windows[d.isoformat()] = _partial_stats(d, offsets[i], draw(st.integers(1, 23)))
        else:
            windows[d.isoformat()] = _stats(d, start_offset, offsets[i + 1])
    # a partial window is no proof of the boundary after it: those days count as dropped for the "nothing unknown" claim
    return first, offsets, windows, dropped | partial, wrong_start - partial


# ══════════════════════════════════════════════════════════════════════════════
section("N1. plan_days — the day boundaries")
# ══════════════════════════════════════════════════════════════════════════════

@prop("plan_days: a planned day is never wrong — its boundaries are the true local midnights, whatever windows are missing", examples=120)
@given(timelines())
def _(case):
    first, offsets, windows, _dropped, _wrong = case
    plan = nz.plan_days(windows, first.isoformat(), (first + timedelta(days=len(offsets) - 2)).isoformat())
    for k in range(len(offsets) - 1):
        day = first + timedelta(days=k)
        planned = plan.days.get(day.isoformat())
        if planned is None:
            continue
        assert planned.start_utc == _utc_of_local_midnight(day, offsets[k]), (day, "start")
        assert planned.end_utc == _utc_of_local_midnight(day + timedelta(days=1), offsets[k + 1]), (day, "end")
        assert planned.offset_start_hours == offsets[k] / _HOUR and planned.offset_end_hours == offsets[k + 1] / _HOUR
        assert planned.dst_transition == (offsets[k] != offsets[k + 1])


@prop("plan_days: a day with proof on both boundaries (source prev_day_end) is exact, even when the offset changes back and forth", examples=150)
@given(timelines(never_back=False))
def _(case):
    first, offsets, windows, _dropped, _wrong = case
    plan = nz.plan_days(windows, first.isoformat(), (first + timedelta(days=len(offsets) - 2)).isoformat())
    for k in range(len(offsets) - 1):
        day = first + timedelta(days=k)
        planned = plan.days.get(day.isoformat())
        if planned is not None and planned.offset_source == "prev_day_end":
            assert planned.start_utc == _utc_of_local_midnight(day, offsets[k])
            assert planned.end_utc == _utc_of_local_midnight(day + timedelta(days=1), offsets[k + 1])


@prop("plan_days: every day of the range is either planned or unknown, never both, never neither", examples=120)
@given(timelines())
def _(case):
    first, offsets, windows, _dropped, _wrong = case
    n = len(offsets) - 1
    plan = nz.plan_days(windows, first.isoformat(), (first + timedelta(days=n - 1)).isoformat())
    every = {(first + timedelta(days=k)).isoformat() for k in range(n)}
    assert set(plan.days) | set(plan.unknown) == every
    assert not set(plan.days) & set(plan.unknown)
    assert len(plan.unknown) == len(set(plan.unknown))


@prop("plan_days: consecutive planned days tile exactly (no gap, no overlap); a day is 24 h plus the change of the offset", examples=120)
@given(timelines())
def _(case):
    first, offsets, windows, _dropped, _wrong = case
    plan = nz.plan_days(windows, first.isoformat(), (first + timedelta(days=len(offsets) - 2)).isoformat())
    for d, p in plan.days.items():
        following = plan.days.get((date.fromisoformat(d) + timedelta(days=1)).isoformat())
        if following is not None:
            assert p.end_utc == following.start_utc
        assert p.end_utc - p.start_utc == 24 * _HOUR + round((p.offset_start_hours - p.offset_end_hours) * _HOUR)
        assert p.offset_source in ("prev_day_end", "neighbours")


@prop("plan_days: with every window present (and the one of the day before) nothing is unknown; a wrong start offset is a disagreement", examples=100)
@given(timelines())
def _(case):
    first, offsets, windows, dropped, wrong = case
    # put the dropped windows back as intact ones, and add the window of the day before the range
    full = dict(windows)
    for k, d in enumerate([first + timedelta(days=i) for i in range(len(offsets) - 1)]):
        if d in dropped:
            full[d.isoformat()] = _stats(d, offsets[k], offsets[k + 1])
    before = first - timedelta(days=1)
    full[before.isoformat()] = _stats(before, offsets[0], offsets[0])
    plan = nz.plan_days(full, first.isoformat(), (first + timedelta(days=len(offsets) - 2)).isoformat())
    assert not plan.unknown
    assert plan.disagreements == sorted(d.isoformat() for d in wrong if d not in dropped)


@prop("plan_days: the default range runs from the first to the last day that has a usable window, and the input is not changed", examples=100)
@given(timelines())
def _(case):
    first, offsets, windows, _dropped, _wrong = case
    before = copy.deepcopy(windows)
    plan = nz.plan_days(windows)
    assert windows == before
    if not windows:
        assert not plan.days and not plan.unknown
        return
    every = {d.isoformat() for d in (date.fromisoformat(min(windows)) + timedelta(days=k)
                                     for k in range((date.fromisoformat(max(windows)) - date.fromisoformat(min(windows))).days + 1))}
    assert set(plan.days) | set(plan.unknown) == every


@prop("plan_days: day_for is the inverse of the plan — each instant belongs to the day whose [start, end) holds it, or to none", examples=100)
@given(timelines(), st.integers(-3, 3))
def _(case, nudge):
    first, offsets, windows, _dropped, _wrong = case
    plan = nz.plan_days(windows, first.isoformat(), (first + timedelta(days=len(offsets) - 2)).isoformat())
    ordered = sorted(plan.days.values(), key=lambda p: p.start_utc)
    for p in ordered:
        assert plan.day_for(p.start_utc) == p.date
        assert plan.day_for(p.end_utc - 1) == p.date
        for instant in (p.start_utc + nudge * 1000, p.end_utc + nudge):
            holder = [q.date for q in ordered if q.start_utc <= instant < q.end_utc]
            assert plan.day_for(instant) == (holder[0] if holder else None)


@prop("plan_days: whatever the windows hold, it returns a plan (never raises) and plans only real days", examples=150)
@given(st.dictionaries(st.text(max_size=12) | DATES, JSON_VALUES, max_size=5),
       st.one_of(st.none(), DATES, st.text(min_size=1, max_size=12)), st.one_of(st.none(), DATES, st.text(min_size=1, max_size=12)))
def _(windows, first, last):
    plan = nz.plan_days(windows, first, last)
    for d, p in plan.days.items():
        assert datetime.strptime(d, "%Y-%m-%d") and p.date == d and p.end_utc > p.start_utc - 2 * 86400 * 365


# ══════════════════════════════════════════════════════════════════════════════
section("N2. 16-bit timestamps and the samples of one file")
# ══════════════════════════════════════════════════════════════════════════════

@prop("complete_timestamp: the result has the low 16 bits asked for and is the nearest such value (a step of more than half the range is a step back)", examples=200)
@given(st.integers(0, 2**32 - 1), st.integers(0, 0xFFFF))
def _(last, ts16):
    got = nz.complete_timestamp(last, ts16)
    assert got & 0xFFFF == ts16
    assert abs(got - last) <= 0x8000
    # no value with the same low 16 bits lies closer
    assert all(abs(got - last) <= abs(other - last) for other in (got - 0x10000, got + 0x10000))


_RECORD = st.fixed_dictionaries({}, optional={253: st.integers(0, 2**32 - 2), 26: st.integers(0, 0xFFFF),
                                              27: st.one_of(st.none(), st.integers(0, 254))})


@prop("file_samples: every record is counted exactly once, as a sample or as one of the four drops", examples=150)
@given(st.lists(_RECORD, max_size=12))
def _(records):
    samples, c = nz.file_samples(records)
    assert c["records"] == len(records)
    assert c["records"] == len(samples) + c["before_first_full"] + c["no_timestamp"] + c["no_heart_rate"] + c["zero_heart_rate"]
    assert all(bpm > 0 for _ts, bpm in samples)


@prop("file_samples: a 16-bit record before the first full timestamp is dropped and counted; no other record is lost silently", examples=150)
@given(st.lists(_RECORD, max_size=12))
def _(records):
    samples, c = nz.file_samples(records)
    seen_full = False
    expected_dropped = 0
    for r in records:
        if r.get(253) is not None:
            seen_full = True
        elif r.get(26) is not None and not seen_full:
            expected_dropped += 1
    assert c["before_first_full"] == expected_dropped
    assert len(samples) == len([1 for r in records if r.get(27)]) - sum(
        1 for i, r in enumerate(records) if r.get(27) and r.get(253) is None and (r.get(26) is None
        or not any(q.get(253) is not None for q in records[:i])))


# ══════════════════════════════════════════════════════════════════════════════
section("N3. SampleCollector — the result does not depend on the order of the files")
# ══════════════════════════════════════════════════════════════════════════════

_DAY0 = date(2024, 3, 10)
# three planned days (the window of the day before gives the first boundary)
_PLAN = nz.plan_days({(_DAY0 + timedelta(days=k)).isoformat(): _stats(_DAY0 + timedelta(days=k), _HOUR, _HOUR) for k in range(-1, 3)},
                     _DAY0.isoformat(), (_DAY0 + timedelta(days=2)).isoformat())
_T0 = _PLAN.days[_DAY0.isoformat()].start_utc - 4 * _HOUR           # Unix seconds, before the first planned day
_SPAN = 3 * 24 * _HOUR + 8 * _HOUR


def _fit_seconds(unix):
    return unix - nz.FIT_EPOCH_OFFSET


@st.composite
def runs(draw):
    """[(time_created or None, hash, records)] with distinct hashes; samples may lie outside the plan."""
    count = draw(st.integers(1, 4))
    hashes = draw(st.lists(st.binary(min_size=1, max_size=4).map(lambda b: b.hex().ljust(64, "0")),
                           min_size=count, max_size=count, unique=True))
    files = []
    for h in hashes:
        created = draw(st.one_of(st.none(), st.integers(1, 10**6)))
        # seconds are drawn from a small set so that files collide on the same second
        seconds = draw(st.lists(st.integers(0, 40), max_size=8))
        records = [{253: _fit_seconds(_T0 + (s % 3) * 24 * _HOUR + (s // 3) * 1800), 27: draw(st.sampled_from([0, 55, 56, None, 120]))}
                   for s in seconds]
        files.append((created, h, records))
    return files


def _collect(files):
    collector = nz.SampleCollector(_PLAN)
    for created, h, records in files:
        collector.add_file(h, created, records)
    return collector.finish()


@prop("SampleCollector: the order the files arrive in changes nothing (days, duplicates, counters)", examples=100)
@given(runs(), st.randoms(use_true_random=False))
def _(files, rnd):
    shuffled = list(files)
    rnd.shuffle(shuffled)
    a, b = _collect(files), _collect(shuffled)
    assert a.days == b.days
    assert a.stats._replace(files=0) == b.stats._replace(files=0)


@prop("SampleCollector: a duplicate second is won by the sample of the file with the smaller (time_created, hash) rank", examples=100)
@given(runs())
def _(files):
    competing = {}                               # unix second -> [(rank key, bpm), ...] of the samples inside the plan
    for created, h, records in files:
        key = (created is None, created or 0, h)
        for r in records:
            bpm = r.get(27)
            if bpm:                              # None and 0 are dropped
                ts = r[253] + nz.FIT_EPOCH_OFFSET
                if _PLAN.day_for(ts) is not None:
                    competing.setdefault(ts, []).append((key, bpm))
    result = _collect(files)
    got = {v[0] // 1000: v[1] for day in result.days.values() for v in day.values}
    # the smaller rank wins; two samples of one file (the same rank) keep the order of the file, so the first one wins
    ordered = {ts: sorted(candidates, key=lambda candidate: candidate[0]) for ts, candidates in competing.items()}
    winners = {ts: c[0][1] for ts, c in ordered.items()}
    assert got == winners
    # the others are counted: with the value of the winner as "same", with another value as "conflict"
    same = sum(1 for ts, c in ordered.items() for _k, bpm in c[1:] if bpm == winners[ts])
    conflict = sum(len(c) - 1 for c in competing.values()) - same
    assert (result.stats.duplicates_same, result.stats.duplicates_conflict) == (same, conflict)
    assert sum(d.duplicates_same for d in result.days.values()) == same
    for day in result.days.values():
        assert [v[0] for v in day.values] == sorted(set(v[0] for v in day.values)), "ascending, one value per second"
        assert all(_PLAN.days[day.date].start_utc * 1000 <= v[0] < _PLAN.days[day.date].end_utc * 1000 for v in day.values)


@prop("SampleCollector: every kept sample is a value, a duplicate or unassigned — the counters add up", examples=100)
@given(runs())
def _(files):
    r = _collect(files)
    kept = sum(1 for _c, _h, records in files for rec in records if rec.get(27))
    assert r.stats.samples_kept == kept
    assert kept == sum(len(d.values) for d in r.days.values()) + r.stats.duplicates_same + r.stats.duplicates_conflict + r.stats.unassigned
    assert r.stats.unassigned == sum(r.stats.unassigned_by_date.values())
    assert r.stats.files == len(files) and r.stats.days_with_samples == len(r.days)
    for d in r.days.values():
        assert d.source_files == sorted(d.source_files) and set(d.source_files) <= {h for _c, h, _r in files}


# ══════════════════════════════════════════════════════════════════════════════
section("Findings of v1.7.6.11 (pinned as they are — the decision per finding is the maintainer's)")
# ══════════════════════════════════════════════════════════════════════════════

def _outcome(fn, *args):
    try:
        fn(*args)
    except Exception as e:                      # noqa: BLE001 - the type is the result
        return type(e).__name__
    return "returned"


# Finding 1 (found by "never raises"): an empty string as first_date or last_date, with no usable window to take the
# default from, goes into `first_date or min(parsed)` and ends in ValueError ("min() iterable argument is empty").
# The guard at the top of plan_days() only knows None. Production calls plan_days(_load_windows()) without dates
# (garmin_bulk_import._work), so nothing reaches it today.
check("finding 1: plan_days({}, '', '') raises ValueError (pinned; production passes no dates)",
      _outcome(nz.plan_days, {}, "", "") == "ValueError")
check("finding 1: ... plan_days({}, '2024-01-01', '') raises ValueError as well (pinned)",
      _outcome(nz.plan_days, {}, "2024-01-01", "") == "ValueError")
check("finding 1: ... but with None for the dates, or a date that is no date, it returns an empty plan",
      all(not nz.plan_days({}, a, b).days and not nz.plan_days({}, a, b).unknown
          for a, b in ((None, None), ("2024-01-01", None), ("x", "y"))))

# Finding 2 (found by "a planned day is never wrong" once the offset may come back): the neighbour rule gives a run of
# boundaries without proof the offset of the boundary before it when that equals the start offset of the first window
# after it. If the offset was different in between (a one-day trip into another zone; summer time over a gap of months)
# the days are planned with the wrong offset. The plan says so: the days carry offset_source "neighbours" (rule 2 as
# written in the module docstring); only a day with source "prev_day_end" on both boundaries is exact (property above).
_A, _B = 1 * _HOUR, 3 * _HOUR
_trip = {  # windows of day 0 and day 3 only; the truth: the boundary between day 1 and day 2 lay in zone B
    "2024-05-01": _stats(date(2024, 5, 1), _A, _A),
    "2024-05-04": _stats(date(2024, 5, 4), _A, _A),
}
_trip_plan = nz.plan_days(_trip, "2024-05-02", "2024-05-03")
_wrong_day = _trip_plan.days.get("2024-05-02")
check("finding 2: a run without proof gets the offset both neighbours agree on, also if the offset differed in between (pinned)",
      _wrong_day is not None and _wrong_day.offset_source == "neighbours"
      and (_wrong_day.offset_start_hours, _wrong_day.offset_end_hours) == (1.0, 1.0)
      and _wrong_day.end_utc == _utc_of_local_midnight(date(2024, 5, 3), _A))
check("finding 2: ... and the plan marks every such day (source neighbours), so a reader can tell it from a proven one",
      all(p.offset_source == "neighbours" for p in _trip_plan.days.values()))

summary()
