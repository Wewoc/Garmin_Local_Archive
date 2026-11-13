#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_export_scan_fit.py

EXPORT-SCAN v1.7.7 — REMOVABLE (removal list: see garmin_export_scan.py).

The FIT side of the export scan: how many FIT files of each type the user's own Garmin export holds,
per year. It walks the export with garmin_bulk_export_scanner.iter_fit_files (ZIP, folder, inner ZIPs;
a file of the same content counts once, as the import counts it) and reads every file with
garmin_bulk_fit_reader.parse_fit, which checks the file as a whole (signature, sizes, CRC) and gives
the type (field 0) and the creation time (field 4) of the first message, file_id. No message is
decoded (parse_fit is called without a list of wanted messages), so the cost is the walk plus the
check: on the maintainer's export 34,869 files took 3 s for the walk and 31 s with the check
(measured 2026-11-12, one account, one machine), which is why no faster reader of its own exists.

Not a leaf: it imports the two modules above (the JSON side, garmin_export_scan.py, is a leaf and
knows nothing of them). The window calls both and puts this result under the key "fit" of the result
of garmin_export_scan.scan(); the text and JSON report of that module show it.

Year of a file: from the creation time of file_id. A FIT time under 0x10000000 is not a date (the FIT
rule for system time; type 41 files carry such a value) and a missing or invalid time has no year:
both count for the year "unknown", as does a year outside 1990..2100.

Privacy (the same rule as garmin_bulk_export_scanner.py)
  The entries of a real export are named after the e-mail address of the account. This module never
  sees a name (the walk hands over hashes and bytes), returns numbers only, and logs and prints nothing.
  An error is counted by a short reason ("crc", "truncated", ...), never reported with its text.

Public API:
  scan_fit(path, should_stop=None, progress=None, index=None) -> dict
      should_stop() -> bool is asked before each file; progress(done) is called every PROGRESS_STEP
      files and once at the end (not twice with the same number); FileNotFoundError at the call if the
      path does not exist.
  SCHEMA_VERSION, PROGRESS_STEP, FIT_EPOCH_OFFSET, MONITORING_TYPE
"""

from datetime import datetime, timezone

import garmin_bulk_export_scanner as walker
import garmin_bulk_fit_reader as fit_reader

SCHEMA_VERSION = 1
PROGRESS_STEP = 250              # progress(done) after this many files, so the window is not flooded
FIT_EPOCH_OFFSET = 631065600     # 1989-12-31 00:00 UTC in Unix seconds
MONITORING_TYPE = 32             # file_id.type of a monitoring file (the heart-rate samples are in these)
MIN_FIT_DATE = 0x10000000        # below this a FIT time is system time, not a date
FIRST_YEAR, LAST_YEAR = 1990, 2100
UNKNOWN_YEAR = "unknown"
NO_TYPE = "none"                 # the key of files without a readable type


def _year_of(time_created) -> str:
    """The year (text) of the creation time of a FIT file, UNKNOWN_YEAR if there is none."""
    if isinstance(time_created, int) and not isinstance(time_created, bool) and time_created >= MIN_FIT_DATE:
        try:
            year = datetime.fromtimestamp(FIT_EPOCH_OFFSET + time_created, tz=timezone.utc).year
        except (OverflowError, OSError, ValueError):
            return UNKNOWN_YEAR
        if FIRST_YEAR <= year <= LAST_YEAR:
            return str(year)
    return UNKNOWN_YEAR


def _year_order(year: str):
    return (year == UNKNOWN_YEAR, year)


def _type_order(key: str):
    return (key == NO_TYPE, int(key) if key.isdigit() else 0)


def scan_fit(path, should_stop=None, progress=None, index=None) -> dict:
    """
    Counts the FIT files of an export by type and year.

    index: a dict the caller hands in, or None. If given, it receives {sha256 digest: creation time (raw FIT
    seconds)} of every monitoring file (type MONITORING_TYPE) that was read and whose creation time is a date
    (not system time, see MIN_FIT_DATE), for the heart-rate day view
    (garmin_export_scan_day.py: it finds the files of a day by their creation time). It is NOT part of the
    result and of no report: the caller keeps it in memory.

    Result: {"schema", "stopped",
             "files": {seen, read, duplicates, oversize, unreadable_entries, zips_opened, zips_unreadable,
                       too_deep, damaged: {reason: n}},
             "types": {"<type number>" | "none": {"files": n, "years": {year: n}}},   (types and years sorted,
                       the year "unknown" last)
             "years": {year: n}}                                                      (all types together)
    "read" is the number of different files that passed the check of parse_fit; "damaged" counts the others
    by reason (not_fit, truncated, crc, structure, other). A stopped scan returns what was counted so far.

    Raises FileNotFoundError (without the path) if the path does not exist.
    """
    stats = walker.ScanStats()
    damaged: dict = {}
    types: dict = {}
    years: dict = {}
    read = 0
    stopped = False
    reported = 0
    files = walker.iter_fit_files(path, stats)          # raises FileNotFoundError here, at the call
    try:
        for done, (digest, data) in enumerate(files, 1):
            if should_stop is not None and should_stop():
                stopped = True
                break
            try:
                fit = fit_reader.parse_fit(data)
            except fit_reader.FitFormatError as exc:
                damaged[exc.reason] = damaged.get(exc.reason, 0) + 1
            except Exception:                           # never report why: it could hold a name
                damaged["other"] = damaged.get("other", 0) + 1
            else:
                read += 1
                key = NO_TYPE if fit.file_type is None else str(fit.file_type)
                year = _year_of(fit.time_created)
                per_year = types.setdefault(key, {})
                per_year[year] = per_year.get(year, 0) + 1
                years[year] = years.get(year, 0) + 1
                if (index is not None and fit.file_type == MONITORING_TYPE and isinstance(fit.time_created, int)
                        and not isinstance(fit.time_created, bool) and fit.time_created >= MIN_FIT_DATE):
                    index[digest] = fit.time_created             # a file with system time instead of a date has no day
            if progress is not None and done % PROGRESS_STEP == 0:
                progress(done)
                reported = done
    finally:
        files.close()                                   # closes the ZIPs and the temporary files of the walk
    total = read + sum(damaged.values())
    if progress is not None and reported != total:
        progress(total)

    return {"schema": SCHEMA_VERSION, "stopped": stopped,
            "files": {"seen": stats.fit_seen, "read": read, "duplicates": stats.duplicates,
                      "oversize": stats.oversize, "unreadable_entries": stats.unreadable_entries,
                      "zips_opened": stats.zips_opened, "zips_unreadable": stats.zips_unreadable,
                      "too_deep": stats.too_deep, "damaged": dict(sorted(damaged.items()))},
            "types": {key: {"files": sum(per_year.values()),
                            "years": {y: per_year[y] for y in sorted(per_year, key=_year_order)}}
                      for key, per_year in sorted(types.items(), key=lambda kv: _type_order(kv[0]))},
            "years": {y: years[y] for y in sorted(years, key=_year_order)}}
