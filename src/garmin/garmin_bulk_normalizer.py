#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_normalizer.py

Normalisation of the GDPR-export intraday data for the bulk store (v1.7.6).
Pure calculation: it gets data and returns data, reads and writes no file.

Leaf node: standard library only, no project imports, no garmin_config. The
windows of the days come from the caller (raw/stats of the archive), so the
tests run on synthetic data (Leitregel).

Part 4a — the day boundaries (decision E27, with the change to E6)
  The FIT timestamps of the export are UTC. To say which local day an instant
  belongs to, the UTC instant of each local midnight is needed, and with it the
  offset that was in force at that midnight. Garmin's own windows describe the
  API days exactly (23 h on the spring day, 25 h on the autumn day), but the
  windows of the days imported from the export are wrong on 10 of the 15
  transition days from 2019 to 2026: the end offset stands at the start as well,
  or the window is 24 h long. The offset at the END of a window was right in
  every case examined. Rule:

  1. The boundary at the start of day d is the local midnight of d, taken to UTC
     with the end offset of day d-1 — but only if the window of d-1 is a full
     day (it ends at local midnight, one second of tolerance).
  2. A boundary that rule 1 cannot give (the window of the day before is
     missing, unusable or partial) is taken from the neighbours: the run of such
     boundaries gets the offset of the boundary before the run (rule 1) if it is
     equal to the start offset of the first usable window after the run (that
     window must start at local midnight). Works for any number of missing days
     in a row (E6). If they differ, or one side is missing, the boundary is
     unknown.
  3. A day is planned only if both of its boundaries are known. Every other day
     of the range is listed in `unknown` and gets no samples (the importer
     counts it); nothing is guessed.

  Consecutive planned days share their boundary, so they tile exactly: no gap,
  no overlap. Days are 23, 24 or 25 hours long, as on the API side. A day also
  carries the offset at its start and at its end; if they differ the day crosses
  a transition (`dst_transition`, like the broker flags it). The series of such a
  day is displayed with the start offset (A6, as the broker does for API days).

  `disagreements` lists the planned days whose own window starts at local
  midnight with another offset than the boundary used — on the wrongly described
  transition days, and when the time zone changes between two days (travel: the
  boundary follows the previous day, the day is flagged).

  Limits: offsets must be a multiple of 15 minutes and at most 14 hours, else a
  window counts as unusable. Only offsets from the data are used, no time zone
  rules.

Input
  windows : {"YYYY-MM-DD": stats dict} with the keys wellnessStartTimeGmt,
            wellnessStartTimeLocal, wellnessEndTimeGmt, wellnessEndTimeLocal
            (ISO strings as in raw/stats). Keys that are not dates and
            unusable values count as missing.

Part 4b — the samples
  Input are the records of the FIT message 55 of each monitoring file, as the
  reader returns them ({field number: value}: 253 full timestamp, 26 16-bit
  timestamp, 27 heart rate). Per file:
  - a full timestamp is the reference, a 16-bit timestamp is completed from the
    last completed one by the nearest distance modulo 65536 (a step of more than
    half the range is a small step BACK). The plain SDK rule — "lower than the
    last one means a roll-over, add 65536" — sends a record that lies one minute
    out of order 18 hours forward; it happens once in the maintainer's export.
  - a 16-bit record before the first full timestamp of its file is dropped
    (none in the export); a record without any timestamp is dropped. Records
    without a heart rate and with heart rate 0 are dropped; all of this is
    counted. FIT seconds become Unix seconds (+ FIT_EPOCH_OFFSET).
  The SampleCollector gives every sample to the day whose [start, end) holds it
  (plan_days), keeping the samples of a day in compact arrays (about 40 MB for
  the 3.3 million samples of the export). Duplicate seconds (E16): the sample of
  the file with the smaller rank wins; the rank is (time_created, hash), a file
  without time_created ranks last, so the result does not depend on the order
  the files arrive in. Duplicates with the same value and with another value
  are counted separately. Samples on a day that is not planned are not
  guessed: they are counted with their UTC date.
  Nothing is written; the caller (the import) writes the days.

Public API:
  plan_days(windows, first_date=None, last_date=None) -> BoundaryPlan
  BoundaryPlan   — .days {date: DayPlan}, .unknown [date], .disagreements [date],
                   .day_for(unix_seconds) -> date | None
  DayPlan        — NamedTuple: date, start_utc (inclusive), end_utc (exclusive),
                   offset_start_hours, offset_end_hours, dst_transition, offset_source
                   ("prev_day_end" | "neighbours")
  complete_timestamp(last, ts16) -> int
  file_samples(records) -> ([(unix_seconds, bpm)], counters)
  SampleCollector(plan) — .add_file(file_hash, time_created, records); then
                   .iter_days() -> DaySamples one at a time (for the writer: low memory),
                   .stats() -> RunStats, or .finish() -> NormalizedRun (all days at once)
  NormalizedRun  — .days {date: DaySamples}, .stats RunStats
  DaySamples     — NamedTuple: date, values [[ms UTC, bpm], ...] ascending, source_files
                   [hash, ...] sorted, duplicates_same, duplicates_conflict
  RunStats       — NamedTuple of counters (numbers, plus dates for the days without data)
"""

import bisect
from array import array
from datetime import datetime, timedelta
from typing import NamedTuple

_EPOCH = datetime(1970, 1, 1)
_DAY = timedelta(days=1)
_FULL_DAY_TOLERANCE_S = 1
_MAX_OFFSET_S = 14 * 3600
_OFFSET_STEP_S = 15 * 60
_KEYS = ("wellnessStartTimeGmt", "wellnessStartTimeLocal", "wellnessEndTimeGmt", "wellnessEndTimeLocal")


class DayPlan(NamedTuple):
    """One planned local day. start_utc/end_utc are Unix seconds, [start, end)."""
    date: str
    start_utc: int
    end_utc: int
    offset_start_hours: float
    offset_end_hours: float
    dst_transition: bool
    offset_source: str


class _Window(NamedTuple):
    start_offset: int            # seconds, start local minus start GMT
    end_offset: int              # seconds, end local minus end GMT
    start_local: datetime
    end_local: datetime


class BoundaryPlan:
    """Result of plan_days(): the planned days, the days that could not be planned,
    the days that disagree with the boundary used, and the lookup instant -> day."""

    def __init__(self, days, unknown, disagreements):
        self.days = days
        self.unknown = unknown
        self.disagreements = disagreements
        self._ordered = sorted(days.values(), key=lambda d: d.start_utc)
        self._starts = [d.start_utc for d in self._ordered]

    def day_for(self, unix_seconds):
        """The date whose [start_utc, end_utc) contains the instant, None if no planned day does."""
        i = bisect.bisect_right(self._starts, unix_seconds) - 1
        if i < 0:
            return None
        day = self._ordered[i]
        return day.date if unix_seconds < day.end_utc else None


# ══════════════════════════════════════════════════════════════════════════════
#  Windows
# ══════════════════════════════════════════════════════════════════════════════

def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _window(stats):
    """_Window from one stats dict, None if a field is missing, unparsable or implausible."""
    if not isinstance(stats, dict):
        return None
    try:
        s_gmt, s_loc, e_gmt, e_loc = (datetime.strptime(str(stats[k])[:19], "%Y-%m-%dT%H:%M:%S") for k in _KEYS)
    except (KeyError, ValueError):
        return None
    start_offset = int((s_loc - s_gmt).total_seconds())
    end_offset = int((e_loc - e_gmt).total_seconds())
    for offset in (start_offset, end_offset):
        if abs(offset) > _MAX_OFFSET_S or offset % _OFFSET_STEP_S:
            return None
    if e_loc <= s_loc:
        return None
    return _Window(start_offset, end_offset, s_loc, e_loc)


def has_window(stats) -> bool:
    """True if `stats` holds a usable window (all four fields, plausible offsets, the end after the
    start) — the test plan_days() applies to every entry. For a caller that has two possible
    sources of a day's window and wants the first usable one (v1.7.6.1)."""
    return _window(stats) is not None


def _at(moment, midnight):
    """True if `moment` is the given local midnight (within the tolerance)."""
    return abs((moment - midnight).total_seconds()) <= _FULL_DAY_TOLERANCE_S


def _epoch(local_midnight):
    return int((local_midnight - _EPOCH).total_seconds())


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def plan_days(windows, first_date=None, last_date=None) -> BoundaryPlan:
    """
    Plans the local days first_date..last_date (default: the first and the last
    day that has a usable window). Windows outside the range are still used for
    the boundaries at its edges.

    Parameters
    ----------
    windows    : {date string: stats dict} — see the module docstring
    first_date : "YYYY-MM-DD" | None
    last_date  : "YYYY-MM-DD" | None

    Returns
    -------
    BoundaryPlan
    """
    parsed = {}
    for key, stats in windows.items():
        if _parse_date(key) is None:
            continue
        window = _window(stats)
        if window is not None:
            parsed[key] = window
    if (first_date is None or last_date is None) and not parsed:
        return BoundaryPlan({}, [], [])
    first = _parse_date(first_date or min(parsed))
    last = _parse_date(last_date or max(parsed))
    if first is None or last is None or last < first:
        return BoundaryPlan({}, [], [])

    n = (last - first).days + 1                       # days; n + 1 boundaries
    midnights = [first + i * _DAY for i in range(n + 1)]
    keys = [m.strftime("%Y-%m-%d") for m in midnights]

    # Rule 1: end offset of a full-day window of the day before.
    boundary = [None] * (n + 1)                       # (offset seconds, source) or None
    for i, midnight in enumerate(midnights):
        prev = parsed.get((midnight - _DAY).strftime("%Y-%m-%d"))
        if prev is not None and _at(prev.end_local, midnight):
            boundary[i] = (prev.end_offset, "prev_day_end")

    # Rule 2: runs of boundaries rule 1 could not give — both neighbours must agree.
    i = 0
    while i <= n:
        if boundary[i] is not None:
            i += 1
            continue
        j = i
        while j + 1 <= n and boundary[j + 1] is None:
            j += 1
        left = boundary[i - 1][0] if i > 0 else None
        after = parsed.get(keys[j])
        right = after.start_offset if after is not None and _at(after.start_local, midnights[j]) else None
        if left is not None and right is not None and left == right:
            for k in range(i, j + 1):
                boundary[k] = (left, "neighbours")
        i = j + 1

    # Rule 3: a day needs both boundaries.
    days, unknown, disagreements = {}, [], []
    for k in range(n):
        a, b = boundary[k], boundary[k + 1]
        if a is None or b is None:
            unknown.append(keys[k])
            continue
        both_direct = a[1] == "prev_day_end" and b[1] == "prev_day_end"
        days[keys[k]] = DayPlan(keys[k], _epoch(midnights[k]) - a[0], _epoch(midnights[k + 1]) - b[0],
                                a[0] / 3600, b[0] / 3600, a[0] != b[0],
                                "prev_day_end" if both_direct else "neighbours")
        own = parsed.get(keys[k])
        if own is not None and _at(own.start_local, midnights[k]) and own.start_offset != a[0]:
            disagreements.append(keys[k])
    return BoundaryPlan(days, unknown, disagreements)


# ══════════════════════════════════════════════════════════════════════════════
#  Part 4b — samples
# ══════════════════════════════════════════════════════════════════════════════

FIT_EPOCH_OFFSET = 631065600          # 1989-12-31 00:00 UTC in Unix seconds
_FIELD_TIMESTAMP, _FIELD_TIMESTAMP_16, _FIELD_HEART_RATE = 253, 26, 27


class DaySamples(NamedTuple):
    """The heart-rate samples of one local day. values: [[milliseconds UTC, bpm], ...] ascending,
    one per second; source_files: hashes of all files that put a sample on this day (sorted)."""
    date: str
    values: list
    source_files: list
    duplicates_same: int
    duplicates_conflict: int


class RunStats(NamedTuple):
    """Counters of a run — numbers, plus dates for the days without data. samples_kept counts the
    samples left after dropping (before the duplicates are resolved)."""
    files: int
    records: int
    samples_kept: int
    before_first_full: int
    no_timestamp: int
    no_heart_rate: int
    zero_heart_rate: int
    unassigned: int
    unassigned_by_date: dict
    duplicates_same: int
    duplicates_conflict: int
    days_with_samples: int
    planned_days_without_samples: list


class NormalizedRun(NamedTuple):
    days: dict            # {date: DaySamples}
    stats: RunStats


def complete_timestamp(last, ts16):
    """Full FIT timestamp (seconds) for a 16-bit one, given the last completed timestamp:
    the nearest value with those low 16 bits; more than half the range ahead counts as a
    small step back (records one minute out of order), not as a roll-over."""
    delta = (ts16 - (last & 0xFFFF)) & 0xFFFF
    return last + delta - 0x10000 if delta > 0x8000 else last + delta


def file_samples(records):
    """
    Heart-rate samples of one monitoring file.

    Parameters
    ----------
    records : list of {field number: value} — the message-55 records in file order

    Returns
    -------
    ([(unix_seconds, bpm), ...], counters) — samples in file order; counters has
    records, before_first_full, no_timestamp, no_heart_rate, zero_heart_rate
    """
    counts = {"records": 0, "before_first_full": 0, "no_timestamp": 0, "no_heart_rate": 0, "zero_heart_rate": 0}
    samples = []
    last = None
    for record in records:
        counts["records"] += 1
        full, small = record.get(_FIELD_TIMESTAMP), record.get(_FIELD_TIMESTAMP_16)
        if full is not None:
            ts = full
        elif small is not None:
            if last is None:
                counts["before_first_full"] += 1
                continue
            ts = complete_timestamp(last, small)
        else:
            counts["no_timestamp"] += 1
            continue
        last = ts
        bpm = record.get(_FIELD_HEART_RATE)
        if bpm is None:
            counts["no_heart_rate"] += 1
        elif bpm == 0:
            counts["zero_heart_rate"] += 1
        else:
            samples.append((ts + FIT_EPOCH_OFFSET, bpm))
    return samples, counts


class SampleCollector:
    """Collects the samples of many files day by day and resolves them in finish().
    Memory: three compact arrays per day (time, bpm, file index)."""

    def __init__(self, plan):
        self._plan = plan
        self._buckets = {}                      # date -> (array time, array bpm, array file index)
        self._files = []                        # (time_created, hash) in the order added
        self._counts = {"records": 0, "before_first_full": 0, "no_timestamp": 0, "no_heart_rate": 0, "zero_heart_rate": 0}
        self._kept = 0
        self._unassigned = {}                   # UTC date -> samples

    def add_file(self, file_hash, time_created, records):
        """Adds the message-55 records of one file; time_created is file_id.time_created
        (raw FIT seconds) or None."""
        samples, counts = file_samples(records)
        index = len(self._files)
        self._files.append((time_created, file_hash))
        for key, value in counts.items():
            self._counts[key] += value
        self._kept += len(samples)
        day_for = self._plan.day_for
        for ts, bpm in samples:
            day = day_for(ts)
            if day is None:
                key = (_EPOCH + timedelta(seconds=ts)).strftime("%Y-%m-%d")
                self._unassigned[key] = self._unassigned.get(key, 0) + 1
                continue
            bucket = self._buckets.get(day)
            if bucket is None:
                bucket = self._buckets[day] = (array("q"), array("B"), array("I"))
            bucket[0].append(ts)
            bucket[1].append(bpm)
            bucket[2].append(index)

    def _ranks(self):
        """File index -> rank by (time_created, hash); a file without time_created ranks last."""
        files = self._files
        rank = [0] * len(files)
        by_rank = sorted(range(len(files)),
                         key=lambda i: (files[i][0] is None, files[i][0] if files[i][0] is not None else 0, files[i][1]))
        for position, i in enumerate(by_rank):
            rank[i] = position
        return rank

    def _resolve(self, date, rank):
        """The DaySamples of one day: sorted by time, duplicate seconds resolved by file rank."""
        times, bpms, owners = self._buckets[date]
        order = sorted(range(len(times)), key=lambda k: (times[k], rank[owners[k]]))
        values, same, conflict, previous = [], 0, 0, None
        for k in order:
            if times[k] == previous:
                if bpms[k] == values[-1][1]:
                    same += 1
                else:
                    conflict += 1
                continue
            values.append([times[k] * 1000, bpms[k]])
            previous = times[k]
        sources = sorted({self._files[i][1] for i in set(owners)})
        return DaySamples(date, values, sources, same, conflict)

    def iter_days(self):
        """Yields the DaySamples one day at a time, in date order. Memory stays small when the
        caller writes each day and drops it (the whole export as lists would need ~450 MB)."""
        rank = self._ranks()
        for date in sorted(self._buckets):
            yield self._resolve(date, rank)

    def stats(self) -> RunStats:
        """The counters of the run. Resolves every day once to count the duplicates and keeps none of them."""
        rank = self._ranks()
        same = conflict = 0
        for date in self._buckets:
            day = self._resolve(date, rank)
            same += day.duplicates_same
            conflict += day.duplicates_conflict
        c = self._counts
        return RunStats(len(self._files), c["records"], self._kept, c["before_first_full"], c["no_timestamp"],
                        c["no_heart_rate"], c["zero_heart_rate"], sum(self._unassigned.values()),
                        dict(sorted(self._unassigned.items())), same, conflict, len(self._buckets),
                        sorted(d for d in self._plan.days if d not in self._buckets))

    def finish(self) -> NormalizedRun:
        """All days at once plus the counters (for tests and small inputs). Can be called again."""
        return NormalizedRun({day.date: day for day in self.iter_days()}, self.stats())
