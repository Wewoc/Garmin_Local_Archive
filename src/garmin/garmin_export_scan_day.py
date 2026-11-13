#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_export_scan_day.py

EXPORT-SCAN v1.7.7 — REMOVABLE (removal list: see garmin_export_scan.py).

The heart rate of ONE local day from the FIT monitoring files of the user's own Garmin export, for the day
view of the Export Scan window. It shows what the export holds, nothing is written to the archive and nothing
is stored between runs. The work is done by the modules of the import, which are only imported:
  garmin_bulk_normalizer   plan_days (the local days from the wellness windows) and SampleCollector (the
                           samples of a day, duplicate seconds resolved by the file rank, as the import does)
  garmin_bulk_fit_reader   parse_fit (the file is checked as a whole, message 55 decoded)
  garmin_bulk_export_scanner  iter_fit_files (the walk: a file of the same content comes once)

How a day is found (measured 2026-11-13 on the maintainer's export, one account, 2,855 planned days)
  A monitoring file starts at its creation time (file_id.time_created) and holds samples for at most 24 hours
  after it. The files of a day [start, end) are therefore those created in [start - LEAD_SECONDS, end); on that
  export this rule missed no file that touches a day (0 of 2,855 days), at a median of 8 candidates per day.
  The export has no random access (inner ZIPs), so a day is read by walking it once and parsing only the
  candidates; the walk stops when all of them are found. The index (digest -> creation time) comes from the
  FIT scan (garmin_export_scan_fit.scan_fit, parameter index); one day took 2.7 s there.

What is returned: samples [[local time "YYYY-MM-DD HH:MM:SS", bpm], ...] by time. The local time is the UTC
time plus the offset at the START of the day (the same rule as the broker for API days); a day that crosses a
clock change is flagged (dst_transition). Only the heart rate (message 55, field 27); nothing is guessed: a day
whose boundaries are not known (plan_days) is not read.

Privacy (the same rule as garmin_bulk_export_scanner.py)
  The result holds VALUES (the samples) and is for the window only, which keeps it in memory: never in the scan
  result, the report, the log, the status line or a file. This module writes and logs nothing. It never sees a
  file name (the walk hands over hashes and bytes), and an error is counted, never reported with its text.

Not a leaf: it imports the modules above and garmin_export_scan.py (windows, statistics).

Public API:
  prepare(path, index, should_stop=None) -> dict | None
      reads the windows of the days (garmin_export_scan.read_windows), plans the days and orders the index;
      the result ("prepared") holds the plan, the index and "days": the planned days that have at least one
      candidate file, sorted. None if there is nothing to show (no usable window, no monitoring file, stopped).
  read_day(path, prepared, day, should_stop=None) -> dict
      the heart rate of one day "YYYY-MM-DD": {"schema", "day", "state", "family", "label", "field",
      "supported", "stopped", "files", "read", "damaged", "sources", "offset_hours", "dst_transition",
      "duplicates_same", "duplicates_conflict", "stats", "histogram", "points", "thinned"}
      state: "ok" | "unplanned" (the boundaries of the day are not known) | "no_files" (no file is created
      near the day) | "no_samples" (the candidates hold no heart-rate sample for the day) | "stopped".
      The keys family, label, field, supported, stats, histogram, points, thinned are those of read_values, so
      the values view of the window shows a day like a field. Raises FileNotFoundError (without the path) if
      the path does not exist.
  candidates(prepared, day) -> [digest]    the files of a day by the rule above
  SCHEMA_VERSION, LEAD_SECONDS, FAMILY, FIELD, LABEL
"""

from datetime import datetime, timedelta

import garmin_bulk_export_scanner as walker
import garmin_bulk_fit_reader as fit_reader
import garmin_bulk_normalizer as normalizer
import garmin_export_scan as json_scan

SCHEMA_VERSION = 1
LEAD_SECONDS = 25 * 3600           # a file holds at most 24 h after its creation time (measured), one hour of slack
FAMILY = "fit_monitoring"          # the key the values view and its unit table know this data by
FIELD = "heartRate"
LABEL = "FIT monitoring"
_HEART_RATE_MESSAGE = 55
_EPOCH = datetime(1970, 1, 1)
_FORMAT = "%Y-%m-%d %H:%M:%S"


def _candidates(prepared, day_plan) -> list:
    low, high = day_plan.start_utc - LEAD_SECONDS, day_plan.end_utc
    return [digest for created, digest in prepared["ordered"] if low <= created < high]


def candidates(prepared, day) -> list:
    """The digests of the monitoring files that may hold samples of the day (empty for a day that is not planned)."""
    day_plan = prepared["plan"].days.get(day)
    return [] if day_plan is None else _candidates(prepared, day_plan)


def prepare(path, index, should_stop=None):
    """See the module docstring. index: {digest: creation time in raw FIT seconds} of the monitoring files."""
    if not index:
        return None
    read = json_scan.read_windows(path, should_stop)
    if read["stopped"]:
        return None
    plan = normalizer.plan_days(read["windows"])
    if not plan.days:
        return None
    ordered = sorted((created + normalizer.FIT_EPOCH_OFFSET, digest) for digest, created in index.items())
    # the days that have a candidate: the days tile in time, so one sweep over the files does for all of them
    days, first = [], 0
    for day, day_plan in sorted(plan.days.items()):
        low, high = day_plan.start_utc - LEAD_SECONDS, day_plan.end_utc
        while first < len(ordered) and ordered[first][0] < low:
            first += 1
        if first < len(ordered) and ordered[first][0] < high:
            days.append(day)
    return {"plan": plan, "ordered": ordered, "days": days} if days else None


def _empty(day, state) -> dict:
    return {"schema": SCHEMA_VERSION, "day": day, "state": state, "family": FAMILY, "label": LABEL, "field": FIELD,
            "supported": True, "stopped": False, "files": 0, "read": 0, "damaged": 0, "sources": 0,
            "offset_hours": None, "dst_transition": False, "duplicates_same": 0, "duplicates_conflict": 0,
            "stats": None, "histogram": None, "points": [], "thinned": False}


def read_day(path, prepared, day, should_stop=None) -> dict:
    """See the module docstring."""
    day_plan = prepared["plan"].days.get(day) if isinstance(day, str) else None
    if day_plan is None:
        return _empty(day if isinstance(day, str) else "", "unplanned")
    result = _empty(day, "no_files")
    result["offset_hours"], result["dst_transition"] = day_plan.offset_start_hours, day_plan.dst_transition
    wanted = set(_candidates(prepared, day_plan))
    result["files"] = len(wanted)
    if not wanted:
        return result
    collector = normalizer.SampleCollector(prepared["plan"])
    files = walker.iter_fit_files(path)                  # raises FileNotFoundError here, at the call
    met = 0
    try:
        for digest, data in files:
            if should_stop is not None and should_stop():
                result["stopped"] = True
                break
            if digest not in wanted:
                continue
            met += 1
            try:
                fit = fit_reader.parse_fit(data, wanted=(_HEART_RATE_MESSAGE,))
            except Exception:                            # never report why: it could hold a name
                result["damaged"] += 1
            else:
                collector.add_file(digest, fit.time_created, fit.messages.get(_HEART_RATE_MESSAGE, []))
                result["read"] += 1
            if met == len(wanted):                       # every candidate is met: no need to walk further
                break
    finally:
        files.close()                                    # closes the ZIPs and the temporary files of the walk
    if result["stopped"]:
        result["state"] = "stopped"
        return result
    samples = next((d for d in collector.iter_days() if d.date == day), None)
    if samples is None or not samples.values:
        result["state"] = "no_samples"
        return result
    shift = int(round(day_plan.offset_start_hours * 3600))
    result["points"] = [[(_EPOCH + timedelta(seconds=ms // 1000 + shift)).strftime(_FORMAT), bpm]
                        for ms, bpm in samples.values]
    numbers = [bpm for _local, bpm in result["points"]]
    result["state"] = "ok"
    result["sources"] = len(samples.source_files)
    result["duplicates_same"], result["duplicates_conflict"] = samples.duplicates_same, samples.duplicates_conflict
    result["stats"] = json_scan._stats(numbers)          # the statistics and the histogram of the values view
    result["histogram"] = json_scan._histogram(numbers)
    return result
