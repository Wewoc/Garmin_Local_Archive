#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_export_scan.py

EXPORT-SCAN v1.7.7 — REMOVABLE.

Looks into the user's own Garmin account export (the whole ZIP, or the export unpacked to a folder)
and reports what its JSON files hold: per data family the number of files, the rows per year and, for
every field and year, how many rows have the field FILLED, as a ZERO, EMPTY (null, "", [], {}) or NOT AT
ALL. It is a check for the user, not a part of the import: nothing is written to the archive, nothing
is stored between runs (a report file is replaced at every run), and the export is only read.

Not to be mixed up with garmin_bulk_export_scanner.py: that module walks the export for FIT files and
hands them to the bulk store. This one reads the JSON files and counts.

Leaf node: standard library only, no project imports, no garmin_config, no logging. The folder for the
report files is given by the caller.

What is looked at (JSON files only; FIT files and nested ZIPs are only counted here. The FIT files are
counted by type and year by garmin_export_scan_fit.py, whose result the caller puts under the key "fit" of
the result of scan(); format_report() and write_report() show it)
  - Every JSON file is sorted into a family by FAMILIES (folder and part of the name, as the import does
    it for the families the import knows) or into "not recognised". Only files of a family are opened;
    a file of no family is counted and its folder named (an "@" in a folder name shows as "<hidden>").
  - Status of a family: "read" (the import takes data from it), "kept" (the import only keeps the file
    for the bulk store), "known" (listed in the export reference, the import does not read it).
  - A file is a list of rows (an object per day, per measurement, per activity); a file that holds one
    object counts as one row. The year of a row comes from the date key of its family (four shapes:
    ISO string, ISO date-time, epoch milliseconds, list of numbers). A row without a readable date, and
    every row of a family without a known date key, counts for the year "unknown".
  - A field is named by its path: keys joined with ".", every list as "[]" (so "a[].b"), keys made of
    digits only or of a UUID (device ids) as "<id>", keys with "@", ".", over 40 characters or without
    printable characters as "<key>". At most MAX_PATHS_PER_FAMILY paths are kept per family; more is
    reported as "truncated". The state of a field in one row is the best of all its occurrences in that
    row: filled, else zero, else empty. A number 0 is a zero; false is a value (filled).
  - A file larger than MAX_JSON_BYTES is not read (same limit as the import, a test pins that), a file
    that cannot be read or parsed is counted. Nothing aborts the scan.

Privacy (the same rule as garmin_bulk_export_scanner.py)
  The entries of a real export are named after the e-mail address of the account. The result, the text,
  the JSON, the exceptions and the report files hold only: names of the tables in this file, generic
  field paths, folder names ("@" hidden) and numbers. No value of the export, no file name, and nothing
  is logged or printed here.

Public API:
  scan(path, should_stop=None, progress=None) -> dict   — path: ZIP or folder; should_stop() -> bool is
        asked before each file; progress(done, total) after each file; FileNotFoundError at the call
        if the path does not exist. A ZIP that cannot be opened gives source "unreadable", no error.
  scan_field(path, family, field, should_stop=None) -> dict — one field by month (the detail window, on demand)
  read_values(path, family, field, should_stop=None, max_points=MAX_VALUE_POINTS) -> dict
        — the VALUES of one numeric field by date, for the values view: the only function that returns
        values of the export; the window keeps them in memory only (see its docstring)
  values_supported(field) -> bool                       — can the values of this field be read
  read_windows(path, should_stop=None) -> dict          — the four wellness times of each day (UDS files),
        for the heart-rate day view (garmin_export_scan_day.py); times only, kept in memory by the window
  format_report(result) -> str                          — the text report
  write_report(result, log_dir) -> {"json": Path, "text": Path} — writes both, replacing older ones
  classify(name) -> Family | None                       — the family of a JSON file name
  FAMILIES, GROUPS, SCHEMA_VERSION, MAX_JSON_BYTES, MAX_PATHS_PER_FAMILY

REMOVAL LIST (everything that belongs to this scan carries the marker "EXPORT-SCAN v1.7.7")
  - this file and tests/test_export_scan.py
  - compiler/build_manifest.py: file list entries + SCRIPT_SIGNATURES_BASE entries (this file and the
    two popups below)
  - run_tests.ps1 and tests/conftest.py: the test file entry
  - garmin_export_scan_fit.py and tests/test_export_scan_fit.py (the FIT side; its own entries in
    build_manifest.py, run_tests.ps1 and tests/conftest.py)
  - garmin_export_scan_day.py and tests/test_export_scan_day.py (the heart rate of one day; the same
    three entries)
  - app/popups/export_scan.py, app/popups/_export_scan_model.py and app/popups/_export_scan_units.py
    (the window, what it shows, and the units of the numeric fields with their evidence)
  - docs/README_EXPORT_SCAN.md (the guide behind the Help button of the window) and its entry in
    compiler/build_manifest.py INFO_INCLUDE
  - app/panel_outputs.py: the import of export_scan, the "Export Scan" button next to "API Scan" and
    _open_export_scan_window()
  - tests/test_qt_app.py: the class TestExportScanWindow
"""

import contextlib
import json
import math
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

SCHEMA_VERSION = 1

# A JSON file larger than this is not read. The same value as garmin_import.MAX_JSON_BYTES (a test pins it).
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PATHS_PER_FAMILY = 500     # distinct field paths kept per family; more is reported as truncated
MAX_DEPTH = 16                 # deeper nesting counts as one filled value
MAX_FOLDERS = 200              # folders named in the lists of the result
FIRST_YEAR, LAST_YEAR = 1990, 2100
UNKNOWN_YEAR = "unknown"

REPORT_JSON = "export_scan_report.json"
REPORT_TEXT = "export_scan_report.txt"

STATUS_READ = "read"
STATUS_KEPT = "kept"
STATUS_KNOWN = "known"
_STATUS_TEXT = {
    STATUS_READ: "read by GLA",
    STATUS_KEPT: "kept by GLA, not read",
    STATUS_KNOWN: "known, not read by GLA",
}

# The groups of the tree, in this order: (key, label)
GROUPS = (
    ("daily", "Daily values"),
    ("sleep_body", "Sleep & body"),
    ("training", "Training & metrics"),
    ("activities", "Activities"),
    ("account", "Account data"),
)


# ══════════════════════════════════════════════════════════════════════════════
#  The table of families
# ══════════════════════════════════════════════════════════════════════════════

class Family(NamedTuple):
    """One data family of the export.

    key        the key of the result (for the families the import knows, the import's own key)
    label      the name of the file family in the export
    group      one of GROUPS
    status     STATUS_READ | STATUS_KEPT | STATUS_KNOWN
    prefix     folder (read, known: part of the whole path; kept: the whole folder, ending with "/")
    keyword    part of the name (read: of the whole name; known: of the name after the last "@")
    pattern    regular expression for the file name (kept families only)
    date_path  where the date of a row is, keys joined with "." (None: no known date key)
    wrapper    key of the list inside each object of the file (activities), None otherwise
    """
    key: str
    label: str
    group: str
    status: str
    prefix: str
    keyword: Optional[str]
    pattern: Optional["re.Pattern"]
    date_path: Optional[str]
    wrapper: Optional[str]


_AGG = "DI_CONNECT/DI-Connect-Aggregator/"
_WELL = "DI_CONNECT/DI-Connect-Wellness/"
_MET = "DI_CONNECT/DI-Connect-Metrics/"
_FITNESS = "DI_CONNECT/DI-Connect-Fitness/"
_ROUTING = "DI_CONNECT/DI-Connect-Routing/"
_DEVICE = "DI_CONNECT/DI-Connect-Device/"


def _read(key, label, group, prefix, keyword, date_path, wrapper=None):
    return Family(key, label, group, STATUS_READ, prefix, keyword, None, date_path, wrapper)


def _kept(key, label, group, prefix, pattern):
    return Family(key, label, group, STATUS_KEPT, prefix, None, re.compile(pattern), None, None)


def _known(key, group, prefix, keyword, date_path):
    return Family(key, key, group, STATUS_KNOWN, prefix, keyword, None, date_path, None)


# Families the import reads — the same order, folders and name parts as garmin_import._KINDS (first match
# wins); a test compares both tables.
_READ = (
    _read("uds", "UDSFile", "daily", _AGG, "UDSFile_", "calendarDate"),
    _read("sleep", "sleepData", "sleep_body", _WELL, "sleepData", "calendarDate"),
    _read("readiness", "TrainingReadinessDTO", "training", _MET, "TrainingReadinessDTO", "calendarDate"),
    _read("activities", "summarizedActivities", "activities", _FITNESS, "summarizedActivities",
          "startTimeLocal", wrapper="summarizedActivitiesExport"),
    _read("health_status", "healthStatusData", "sleep_body", _WELL, "healthStatusData", "calendarDate"),
    _read("alert_events", "AbnormalHrEvents", "sleep_body", _WELL, "AbnormalHrEvents", "calendarDate"),
    _read("race_predictions", "RunRacePredictions", "training", _MET, "RunRacePredictions", "calendarDate"),
)

# Families the import only keeps — the same folders and patterns as garmin_import._SAVED_FAMILIES (the
# folder must be the whole folder of the file); a test compares both tables. No date key is known.
_KEPT = (
    _kept("gear", "gear", "activities", _FITNESS, r"(?:^|_)gear\.json$"),
    _kept("personalRecord", "personalRecord", "activities", _FITNESS, r"(?:^|_)personalRecord\.json$"),
    _kept("courses", "courses", "activities", _ROUTING, r"courses.*\.json$"),
    _kept("zones", "heartRateZones / powerZones", "sleep_body", _WELL,
          r"(?:^|_)(?:heartRateZones|powerZones)\.json$"),
)

# Families of the export reference (section 2 and 4) that the import does not read. The name part is
# looked for after the last "@" of the name, so that an e-mail address in the name cannot match.
_KNOWN = (
    _known("HydrationLogFile", "daily", _AGG, "HydrationLogFile_", "calendarDate"),
    _known("fitnessAgeData", "sleep_body", _WELL, "fitnessAgeData", "asOfDateGmt"),
    _known("userBioMetrics", "sleep_body", _WELL, "userBioMetrics", "metaData.calendarDate"),
    _known("bioMetrics_latest", "sleep_body", _WELL, "bioMetrics_latest", None),
    _known("userBioMetricProfileData", "sleep_body", _WELL, "userBioMetricProfileData", None),
    _known("MetricsMaxMetData", "training", _MET, "MetricsMaxMetData_", "calendarDate"),
    _known("TrainingHistory", "training", _MET, "TrainingHistory_", "calendarDate"),
    _known("MetricsAcuteTrainingLoad", "training", _MET, "MetricsAcuteTrainingLoad_", "calendarDate"),
    _known("EnduranceScore", "training", _MET, "EnduranceScore_", "calendarDate"),
    _known("HillScore", "training", _MET, "HillScore_", "calendarDate"),
    _known("MetricsHeatAltitudeAcclimation", "training", _MET, "MetricsHeatAltitudeAcclimation_", "calendarDate"),
    _known("workout", "training", _FITNESS, "workout", None),
    _known("trainingPlan", "training", _FITNESS, "trainingPlan", None),
    _known("weekly_training_report", "training", _FITNESS, "weekly_training_report", None),
    _known("DeviceBackups", "account", _DEVICE, "DeviceBackups", None),
)

FAMILIES = {fam.key: fam for fam in _READ + _KEPT + _KNOWN}


def classify(name) -> Optional[Family]:
    """
    The family of a JSON file name (path inside the export, "/" as separator), None if it belongs to none.
    Not a JSON file (the name must end with ".json") → None. Reads nothing, pure function.
    """
    if not isinstance(name, str) or not name.endswith(".json"):
        return None
    for fam in _READ:
        if fam.prefix in name and fam.keyword in name:
            return fam
    folder, _, base = name.rpartition("/")
    for fam in _KEPT:
        if (folder + "/") == fam.prefix and fam.pattern.search(base):
            return fam
    tail = base.rpartition("@")[2]
    for fam in _KNOWN:
        if fam.prefix in name and fam.keyword in tail:
            return fam
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Dates and field paths
# ══════════════════════════════════════════════════════════════════════════════

_ISO_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}")
_DIGITS = re.compile(r"^\d+$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _year_of(value) -> Optional[str]:
    """The year (text) of a date value in one of the four shapes of the export, None if it has none."""
    year = None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = _ISO_DATE.match(value)
        if match:
            year = int(match.group(1))
    elif isinstance(value, (int, float)):
        if abs(value) >= 1e11:                       # epoch milliseconds
            try:
                year = datetime.fromtimestamp(value / 1000, tz=timezone.utc).year
            except (OverflowError, OSError, ValueError):
                year = None
    elif isinstance(value, list) and len(value) >= 3:
        head = value[:3]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in head):
            year = head[0]
    if year is not None and FIRST_YEAR <= year <= LAST_YEAR:
        return str(year)
    return None


_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})-\d{2}")


def _month_of(value) -> Optional[str]:
    """The month ("YYYY-MM") of a date value, None if it has none. The same four shapes and the same year
    range as _year_of (a test pins that both give the same year); a month outside 1..12 is no date."""
    year = month = None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = _ISO_MONTH.match(value)
        if match:
            year, month = int(match.group(1)), int(match.group(2))
    elif isinstance(value, (int, float)):
        if abs(value) >= 1e11:                       # epoch milliseconds
            try:
                moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                year, month = moment.year, moment.month
            except (OverflowError, OSError, ValueError):
                pass
    elif isinstance(value, list) and len(value) >= 3:
        head = value[:3]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in head):
            year, month = head[0], head[1]
    if year is not None and FIRST_YEAR <= year <= LAST_YEAR and 1 <= month <= 12:
        return f"{year}-{month:02d}"
    return None


_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _date_of(value) -> Optional[str]:
    """The date ("YYYY-MM-DD") of a date value, None if it has none or is no real day. The same four shapes
    and the same year range as _month_of (a test pins that both give the same month)."""
    year = month = day = None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = _ISO_DAY.match(value)
        if match:
            year, month, day = (int(part) for part in match.groups())
    elif isinstance(value, (int, float)):
        if abs(value) >= 1e11:                       # epoch milliseconds
            try:
                moment = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                year, month, day = moment.year, moment.month, moment.day
            except (OverflowError, OSError, ValueError):
                pass
    elif isinstance(value, list) and len(value) >= 3:
        head = value[:3]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in head):
            year, month, day = head
    if year is None or not FIRST_YEAR <= year <= LAST_YEAR:
        return None
    try:
        datetime(year, month, day)
    except ValueError:                               # month or day outside the calendar
        return None
    return f"{year}-{month:02d}-{day:02d}"


def _dig(row, path):
    """The value at path (keys joined with ".") inside row, None if it is not there."""
    current = row
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _segment(key) -> str:
    """A key as a part of a field path: ids and keys that might hold personal text become a mark."""
    if not isinstance(key, str):
        return "<key>"
    if _DIGITS.match(key) or _UUID.match(key):
        return "<id>"
    if key == "" or "@" in key or "." in key or len(key) > 40 or not key.isprintable():
        return "<key>"
    return key


_EMPTY, _ZERO, _FILLED = 0, 1, 2


def _leaf_state(value) -> int:
    if value is None:
        return _EMPTY
    if isinstance(value, str):
        return _EMPTY if value == "" else _FILLED
    if isinstance(value, bool):
        return _FILLED
    if isinstance(value, (int, float)):
        return _ZERO if value == 0 else _FILLED
    return _FILLED


def _put(out: dict, path: str, state: int) -> None:
    if path and state > out.get(path, -1):
        out[path] = state


def _flatten(value, path: str, out: dict, depth: int) -> None:
    """Enters the state of every field below value into out (path → best state of its occurrences)."""
    if isinstance(value, dict):
        if not value:
            _put(out, path, _EMPTY)
        elif depth >= MAX_DEPTH:
            _put(out, path, _FILLED)
        else:
            for key, item in value.items():
                _flatten(item, f"{path}.{_segment(key)}" if path else _segment(key), out, depth + 1)
    elif isinstance(value, list):
        if not value:
            _put(out, path, _EMPTY)
        elif depth >= MAX_DEPTH:
            _put(out, path, _FILLED)
        else:
            for item in value:
                _flatten(item, path + "[]", out, depth + 1)
    else:
        _put(out, path, _leaf_state(value))


# ══════════════════════════════════════════════════════════════════════════════
#  Counting
# ══════════════════════════════════════════════════════════════════════════════

def _new_acc() -> dict:
    return {"files": 0, "unreadable": 0, "too_large": 0, "rows": 0, "skipped_rows": 0,
            "years": {}, "fields": {}, "truncated": False}


def _rows(data, fam: Family):
    """The rows of one parsed file."""
    if fam.wrapper:
        if isinstance(data, list):
            for wrapper in data:
                if isinstance(wrapper, dict):
                    inner = wrapper.get(fam.wrapper)
                    if isinstance(inner, list):
                        yield from inner
    elif isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        yield data


def _add_row(acc: dict, row: dict, fam: Family) -> None:
    year = (_year_of(_dig(row, fam.date_path)) if fam.date_path else None) or UNKNOWN_YEAR
    acc["rows"] += 1
    acc["years"][year] = acc["years"].get(year, 0) + 1
    states: dict = {}
    _flatten(row, "", states, 0)
    fields = acc["fields"]
    for path, state in states.items():
        per_year = fields.get(path)
        if per_year is None:
            if len(fields) >= MAX_PATHS_PER_FAMILY:
                acc["truncated"] = True
                continue
            per_year = fields[path] = {}
        counts = per_year.get(year)
        if counts is None:
            counts = per_year[year] = [0, 0, 0]          # empty, zero, filled
        counts[state] += 1


def _year_order(year: str):
    return (year == UNKNOWN_YEAR, year)


def _finish_family(fam: Family, acc: dict) -> dict:
    years = {y: acc["years"][y] for y in sorted(acc["years"], key=_year_order)}
    fields = {}
    for path in sorted(acc["fields"]):
        per_year = acc["fields"][path]
        entry = {}
        for year, rows in years.items():
            counts = per_year.get(year, [0, 0, 0])
            entry[year] = {"filled": counts[_FILLED], "zero": counts[_ZERO], "empty": counts[_EMPTY],
                           "absent": rows - sum(counts)}
        fields[path] = entry
    return {"label": fam.label, "group": fam.group, "status": fam.status,
            "files": acc["files"], "unreadable": acc["unreadable"], "too_large": acc["too_large"],
            "rows": acc["rows"], "skipped_rows": acc["skipped_rows"],
            "years": years, "fields": fields, "truncated": acc["truncated"]}


# ══════════════════════════════════════════════════════════════════════════════
#  Reading the export
# ══════════════════════════════════════════════════════════════════════════════

class _ZipReader:
    def __init__(self, zf):
        self._zf = zf
        self._sizes = {info.filename: info.file_size for info in zf.infolist()}

    def size(self, name):
        return self._sizes.get(name)

    def read(self, name):
        return self._zf.read(name)


class _DirReader:
    def __init__(self, root):
        self._root = root

    def size(self, name):
        return (self._root / name).stat().st_size

    def read(self, name):
        return (self._root / name).read_bytes()


def _empty_result(source: str) -> dict:
    return {"schema": SCHEMA_VERSION, "source": source, "stopped": False,
            "files": {"json_total": 0, "json_read": 0, "unreadable": 0, "too_large": 0,
                      "unknown_json": 0, "nested_zips": 0, "fit": 0, "other": 0},
            "groups": [{"key": key, "label": label,
                        "families": [fam.key for fam in FAMILIES.values() if fam.group == key]}
                       for key, label in GROUPS],
            "families": {},
            "unknown": {"files": 0, "folders": [], "folders_truncated": False},
            "folders": []}


def _hidden(folder: str) -> str:
    return "<hidden>" if "@" in folder else folder


def _read_file(reader, name):
    """("ok", data) | ("too_large", None) | ("unreadable", None) — never raises, never says why."""
    try:
        size = reader.size(name)
        if isinstance(size, int) and size > MAX_JSON_BYTES:
            return "too_large", None
        return "ok", json.loads(reader.read(name))
    except Exception:                                    # damaged ZIP entry, I/O error, bad JSON, ...
        return "unreadable", None


def _scan_names(source: str, names: list, reader, should_stop, progress) -> dict:
    result = _empty_result(source)
    counts = result["files"]
    accs = {key: _new_acc() for key in FAMILIES}
    work = []
    unknown_folders = set()
    top_folders: dict = {}
    for name in names:
        top = name.partition("/")[0] if "/" in name else "(top level)"
        top = _hidden(top)
        top_folders[top] = top_folders.get(top, 0) + 1
        lower = name.lower()
        if name.endswith(".json"):
            counts["json_total"] += 1
            fam = classify(name)
            if fam is None:
                counts["unknown_json"] += 1
                unknown_folders.add(_hidden(name.rpartition("/")[0] or "(top level)"))
            else:
                accs[fam.key]["files"] += 1
                work.append((name, fam))
        elif lower.endswith(".zip"):
            counts["nested_zips"] += 1
        elif lower.endswith(".fit"):
            counts["fit"] += 1
        else:
            counts["other"] += 1

    total = len(work)
    for done, (name, fam) in enumerate(work, 1):
        if should_stop is not None and should_stop():
            result["stopped"] = True
            break
        state, data = _read_file(reader, name)
        acc = accs[fam.key]
        if state == "ok":
            counts["json_read"] += 1
            for row in _rows(data, fam):
                if isinstance(row, dict):
                    _add_row(acc, row, fam)
                else:
                    acc["skipped_rows"] += 1
        elif state == "too_large":
            counts["too_large"] += 1
            acc["too_large"] += 1
        else:
            counts["unreadable"] += 1
            acc["unreadable"] += 1
        if progress is not None:
            progress(done, total)

    result["families"] = {key: _finish_family(FAMILIES[key], acc) for key, acc in accs.items()}
    folders = sorted(unknown_folders)
    result["unknown"] = {"files": counts["unknown_json"], "folders": folders[:MAX_FOLDERS],
                         "folders_truncated": len(folders) > MAX_FOLDERS}
    result["folders"] = [{"folder": folder, "files": top_folders[folder]}
                         for folder in sorted(top_folders)][:MAX_FOLDERS]
    return result


MAX_VALUE_POINTS = 20000       # points of one values view; more are thinned evenly (statistics use all)
HISTOGRAM_BINS = 30


def values_supported(field) -> bool:
    """True if the VALUES of a field can be read: a path of plain keys, no list ("[]"), no masked key
    ("<id>", "<key>": several keys of the export would share it)."""
    return (isinstance(field, str) and bool(field) and "[]" not in field
            and all(_segment(part) == part and part not in ("<id>", "<key>") for part in field.split(".")))


def _number(value):
    """The value itself if it is a finite number (not a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _stats(numbers: list) -> dict:
    ordered = sorted(numbers)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    return {"count": n, "min": ordered[0], "max": ordered[-1], "mean": sum(ordered) / n, "median": median,
            "zeros": sum(1 for v in ordered if v == 0)}


def _histogram(numbers: list, bins: int = HISTOGRAM_BINS) -> dict:
    low, high = min(numbers), max(numbers)
    if low == high:
        return {"edges": [low, high], "counts": [len(numbers)]}
    width = (high - low) / bins
    counts = [0] * bins
    for v in numbers:
        counts[min(int((v - low) / width), bins - 1)] += 1
    edges = [low + width * i for i in range(bins)] + [high]
    return {"edges": edges, "counts": counts}


def read_values(path, family, field, should_stop=None, max_points=MAX_VALUE_POINTS) -> dict:
    """
    The VALUES of ONE numeric field of a family, by date: for the values view of the window. This is the
    only function of this module that returns values of the export (scan(), scan_field() and the reports
    never do); the window keeps them in memory only, never in the scan result, the report, the log or a
    file. Nothing is written or logged here either.

    family, field : as for scan_field(); the field must be readable as values (values_supported()), else
                    the result says supported False and nothing is read.
    Result: {"schema", "source", "family", "label", "field", "supported", "stopped", "files", "unreadable",
             "too_large", "rows", "numeric", "other", "missing", "undated", "thinned", "stats", "histogram",
             "points"}
      points     [[YYYY-MM-DD, number], ...] by date (several per date possible), at most max_points
                 (thinned evenly, first and last kept: "thinned" True)
      stats      {count, min, max, mean, median, zeros} of ALL numbers with a date (None if there are none)
      histogram  {"edges": [...], "counts": [...]} of the same numbers (HISTOGRAM_BINS bins; one bin when
                 all values are equal)
      numeric / other / missing / undated   rows with a number / with something else than a number /
                 without the field or with null or "" / numbers whose row has no readable date (not shown)
    Raises FileNotFoundError (without the path) if the path does not exist, ValueError if the family is not
    in FAMILIES or the field is empty.
    """
    fam = FAMILIES.get(family)
    if fam is None or not isinstance(field, str) or not field:
        raise ValueError("unknown family or field")
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError("export path does not exist")
    result = {"schema": SCHEMA_VERSION, "source": "not read", "family": family, "label": fam.label, "field": field,
              "supported": values_supported(field), "stopped": False, "files": 0, "unreadable": 0, "too_large": 0,
              "rows": 0, "numeric": 0, "other": 0, "missing": 0, "undated": 0, "thinned": False,
              "stats": None, "histogram": None, "points": []}
    if not result["supported"]:
        return result
    points: list = []
    with _opened(root) as (source, names, reader):
        result["source"] = source
        for name in names:
            if classify(name) is not fam:
                continue
            if should_stop is not None and should_stop():
                result["stopped"] = True
                break
            result["files"] += 1
            state, data = _read_file(reader, name)
            if state != "ok":
                result["unreadable" if state == "unreadable" else "too_large"] += 1
                continue
            for row in _rows(data, fam):
                if not isinstance(row, dict):
                    continue
                result["rows"] += 1
                value = _dig(row, field)
                number = _number(value)
                if number is None:
                    result["missing" if value is None or value == "" else "other"] += 1
                    continue
                result["numeric"] += 1
                day = _date_of(_dig(row, fam.date_path)) if fam.date_path else None
                if day is None:
                    result["undated"] += 1
                    continue
                points.append((day, number))
    points.sort(key=lambda point: point[0])
    if points:
        numbers = [number for _day, number in points]
        result["stats"] = _stats(numbers)
        result["histogram"] = _histogram(numbers)
    limit = max(1, int(max_points))
    if len(points) > limit:
        step = -(-len(points) // limit)
        thinned = points[::step]
        thinned[-1] = points[-1]                         # the first point and the last one stay
        points, result["thinned"] = thinned, True
    result["points"] = [[day, number] for day, number in points]
    return result


WINDOW_KEYS = ("wellnessStartTimeGmt", "wellnessStartTimeLocal", "wellnessEndTimeGmt", "wellnessEndTimeLocal")


def read_windows(path, should_stop=None) -> dict:
    """
    The wellness window of each day of the UDS files: the four times that say when the day starts and ends
    (UTC and local), which the heart-rate day view needs to place the FIT samples on local days (the import
    plans its days with the same four keys). It returns times, no health value, and the window keeps them in
    memory only; nothing is written or logged here.

    Result: {"source", "stopped", "files", "unreadable", "too_large", "windows": {"YYYY-MM-DD": {key: text}}}
      with the keys WINDOW_KEYS; a day takes only keys that hold a text (a later row of the same day replaces
      an earlier one). Raises FileNotFoundError (without the path) if the path does not exist.
    """
    fam = FAMILIES["uds"]
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError("export path does not exist")
    result = {"source": "not read", "stopped": False, "files": 0, "unreadable": 0, "too_large": 0, "windows": {}}
    with _opened(root) as (source, names, reader):
        result["source"] = source
        for name in names:
            if classify(name) is not fam:
                continue
            if should_stop is not None and should_stop():
                result["stopped"] = True
                break
            result["files"] += 1
            state, data = _read_file(reader, name)
            if state != "ok":
                result["unreadable" if state == "unreadable" else "too_large"] += 1
                continue
            for row in _rows(data, fam):
                if not isinstance(row, dict):
                    continue
                day = _date_of(_dig(row, fam.date_path))
                if day is None:
                    continue
                window = {key: row[key] for key in WINDOW_KEYS if isinstance(row.get(key), str)}
                if window:
                    result["windows"][day] = window
    return result


@contextlib.contextmanager
def _opened(root: Path):
    """(source, names, reader) of an export: "zip" or "folder", or "unreadable" (no names, no reader) if it
    cannot be opened. A ZIP is closed when the block ends."""
    source, names, reader, zf = "unreadable", [], None, None
    if root.is_dir():
        try:
            names = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
            source, reader = "folder", _DirReader(root)
        except OSError:
            names = []
    else:
        try:
            if zipfile.is_zipfile(root):
                zf = zipfile.ZipFile(root)
                names = sorted({info.filename for info in zf.infolist() if not info.is_dir()})
                source, reader = "zip", _ZipReader(zf)
        except Exception:                                # a ZIP that cannot be opened
            names, reader, source = [], None, "unreadable"
            if zf is not None:
                zf.close()
                zf = None
    try:
        yield source, names, reader
    finally:
        if zf is not None:
            zf.close()


def scan(path, should_stop=None, progress=None) -> dict:
    """
    Scans an export (ZIP or unpacked folder) and returns the result (see the module docstring).

    Result: {"schema", "source": "zip"|"folder"|"unreadable", "stopped",
             "files": {json_total, json_read, unreadable, too_large, unknown_json, nested_zips, fit, other},
             "groups": [{key, label, families: [key, ...]}],
             "families": {key: {label, group, status, files, unreadable, too_large, rows, skipped_rows,
                                years: {year: rows},
                                fields: {path: {year: {filled, zero, empty, absent}}}, truncated}},
             "unknown": {files, folders, folders_truncated}, "folders": [{folder, files}]}
    Every family of FAMILIES is in "families" (with 0 files when the export has none). A stopped scan
    returns what was counted so far, with "stopped" True.

    Raises FileNotFoundError (without the path) if the path does not exist.
    """
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError("export path does not exist")
    with _opened(root) as (source, names, reader):
        return _scan_names(source, names, reader, should_stop, progress)


_STATE_NAMES = {_EMPTY: "empty", _ZERO: "zero", _FILLED: "filled"}


def scan_field(path, family, field, should_stop=None) -> dict:
    """
    The detail of ONE field: how many rows have it filled / as a zero / empty / not at all, per MONTH of
    the date of the row. Reads only the files of this family (on demand, the detail window asks for it);
    the result of scan() and the report stay as they are. Numbers and months only, no value.

    family : a key of FAMILIES; field : a field path as scan() names it ("stress.avg", "napList[].a",
             "devices.<id>.x"): the generic path, the same normalisation is applied to the rows here.
    Result: {"schema", "source", "family", "label", "field", "stopped", "files", "unreadable", "too_large",
             "rows", "months": {"YYYY-MM": {rows, filled, zero, empty, absent}, ..., "unknown": {...}},
             "first", "last"}   (months ascending, "unknown" last: the rows without a readable date;
             first / last: the first and last month in which at least one row has a value (filled or 0),
             None if there is none)
    Raises FileNotFoundError (without the path) if the path does not exist, ValueError if the family is not
    in FAMILIES or the field is empty.
    """
    fam = FAMILIES.get(family)
    if fam is None or not isinstance(field, str) or not field:
        raise ValueError("unknown family or field")
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError("export path does not exist")
    months: dict = {}
    result = {"schema": SCHEMA_VERSION, "family": family, "label": fam.label, "field": field, "stopped": False,
              "files": 0, "unreadable": 0, "too_large": 0, "rows": 0}
    with _opened(root) as (source, names, reader):
        result["source"] = source
        for name in names:
            if classify(name) is not fam:
                continue
            if should_stop is not None and should_stop():
                result["stopped"] = True
                break
            result["files"] += 1
            state, data = _read_file(reader, name)
            if state != "ok":
                result["unreadable" if state == "unreadable" else "too_large"] += 1
                continue
            for row in _rows(data, fam):
                if not isinstance(row, dict):
                    continue
                month = (_month_of(_dig(row, fam.date_path)) if fam.date_path else None) or UNKNOWN_YEAR
                states: dict = {}
                _flatten(row, "", states, 0)
                bucket = months.setdefault(month, {"rows": 0, "filled": 0, "zero": 0, "empty": 0, "absent": 0})
                bucket["rows"] += 1
                bucket[_STATE_NAMES.get(states.get(field), "absent")] += 1
                result["rows"] += 1
    dated = sorted(m for m in months if m != UNKNOWN_YEAR)
    result["months"] = {m: months[m] for m in dated + ([UNKNOWN_YEAR] if UNKNOWN_YEAR in months else [])}
    valued = [m for m in dated if months[m]["filled"] + months[m]["zero"] > 0]
    result["first"], result["last"] = (valued[0], valued[-1]) if valued else (None, None)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  The report
# ══════════════════════════════════════════════════════════════════════════════

def _pct(part: int, total: int) -> int:
    return round(100 * part / total) if total else 0


def _years_text(years: dict) -> str:
    return ", ".join(f"{year}: {rows}" for year, rows in years.items())


def _fit_lines(fit: dict) -> list:
    """The FIT section of the text report, from the "fit" part of a result (see garmin_export_scan_fit)."""
    files = fit["files"]
    damaged = sum(files["damaged"].values())
    lines = ["", "== FIT files ==",
             f"{files['read']} different files read, {files['seen']} seen, {files['duplicates']} again with the "
             f"same content, {damaged} damaged" + (f" ({_years_text(files['damaged'])})" if damaged else "")]
    if files["oversize"] or files["unreadable_entries"] or files["zips_unreadable"] or files["too_deep"]:
        lines.append(f"not read: too large {files['oversize']}, unreadable entries {files['unreadable_entries']}, "
                     f"unreadable ZIPs {files['zips_unreadable']}, nested too deep {files['too_deep']}")
    if fit["stopped"]:
        lines.append("The FIT scan was stopped before the end: the numbers are incomplete.")
    for key, entry in fit["types"].items():
        lines.append(f"type {key}: {entry['files']} files  ({_years_text(entry['years'])})")
    return lines


def format_report(result: dict) -> str:
    """The text report of a scan result: names and numbers only. A "fit" part (added by the caller, see
    garmin_export_scan_fit.scan_fit) is shown as a section of its own."""
    lines = ["GLA export scan (names and counts only: no values, no file names)"]
    files = result["files"]
    lines.append(f"Source: {result['source']}")
    lines.append(f"JSON files: {files['json_total']} (read {files['json_read']}, unreadable "
                 f"{files['unreadable']}, too large {files['too_large']}, not recognised {files['unknown_json']})")
    lines.append(f"Other files: nested ZIPs {files['nested_zips']}, FIT {files['fit']}, other {files['other']}")
    if result["stopped"]:
        lines.append("The scan was stopped before the end: the numbers are incomplete.")

    for group in result["groups"]:
        lines.append("")
        lines.append(f"== {group['label']} ==")
        missing = []
        for key in group["families"]:
            fam = result["families"][key]
            if fam["files"] == 0:
                missing.append(fam["label"])
                continue
            lines.append(f"{fam['label']}  [{_STATUS_TEXT[fam['status']]}]  files {fam['files']}, rows {fam['rows']}")
            if fam["years"]:
                lines.append(f"  rows per year: {_years_text(fam['years'])}")
            if fam["unreadable"] or fam["too_large"] or fam["skipped_rows"]:
                lines.append(f"  unreadable files {fam['unreadable']}, too large {fam['too_large']}, "
                             f"rows that are not objects {fam['skipped_rows']}")
            if fam["fields"]:
                lines.append("  field (share of all rows, rounded)" + " " * 14 + "filled  zero empty absent")
                for path, per_year in fam["fields"].items():
                    total = sum(c["filled"] + c["zero"] + c["empty"] + c["absent"] for c in per_year.values())
                    filled = sum(c["filled"] for c in per_year.values())
                    zero = sum(c["zero"] for c in per_year.values())
                    empty = sum(c["empty"] for c in per_year.values())
                    absent = sum(c["absent"] for c in per_year.values())
                    lines.append(f"    {path:<48}{_pct(filled, total):>5}% {_pct(zero, total):>4}% "
                                 f"{_pct(empty, total):>4}% {_pct(absent, total):>5}%")
            if fam["truncated"]:
                lines.append(f"  (field list cut at {MAX_PATHS_PER_FAMILY} paths)")
        if missing:
            lines.append(f"Not in this export: {', '.join(missing)}")

    if result.get("fit"):
        lines.extend(_fit_lines(result["fit"]))

    unknown = result["unknown"]
    lines.append("")
    lines.append("== Not recognised ==")
    lines.append(f"{unknown['files']} JSON files")
    if unknown["folders"]:
        lines.append("in folders: " + ", ".join(unknown["folders"])
                     + (" (list cut)" if unknown["folders_truncated"] else ""))
    lines.append("")
    lines.append("== Folders at the top of the export ==")
    for entry in result["folders"]:
        lines.append(f"{entry['folder']}: {entry['files']} files")
    return "\n".join(lines) + "\n"


def write_report(result: dict, log_dir) -> dict:
    """
    Writes the JSON and the text report into log_dir (created if needed), each replacing the file of the
    last run (written to a temporary file first, then renamed). Returns {"json": Path, "text": Path}.
    """
    folder = Path(log_dir)
    folder.mkdir(parents=True, exist_ok=True)
    written = {}
    for kind, name, text in (("json", REPORT_JSON, json.dumps(result, indent=1)),
                             ("text", REPORT_TEXT, format_report(result))):
        target = folder / name
        tmp = folder / (name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        written[kind] = target
    return written
