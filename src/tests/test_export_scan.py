#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_export_scan.py — garmin_export_scan
EXPORT-SCAN v1.7.7 — removable (see the module's removal list).

Covers: the table of families against garmin_import (_KINDS, _SAVED_FAMILIES, build_inventory, the file
size limit), classify(), the four shapes of a date, the four states of a field (filled / zero / empty /
absent), field paths (lists, ids, keys with "@"), the limits (paths per family, depth, file size), a ZIP
and a folder giving the same result, unreadable and stopped scans, the report files, and the privacy
rule: the marker that stands for the e-mail address of the account must never show up in any output.

Run from the project folder:
    python tests/test_export_scan.py

All exports are built here from scratch — no export of the maintainer is needed.
"""

import contextlib
import hashlib
import io
import json
import logging
import shutil
import zipfile
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

section("EXPORT-SCAN v1.7.7 — garmin_export_scan")
import garmin_export_scan as es
import garmin_import as gi

BASE = _TMPDIR / "export_scan_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

SECRET = "secret.name@example.invalid"

AGG = "DI_CONNECT/DI-Connect-Aggregator/"
WELL = "DI_CONNECT/DI-Connect-Wellness/"
MET = "DI_CONNECT/DI-Connect-Metrics/"
FITNESS = "DI_CONNECT/DI-Connect-Fitness/"


def _j(obj):
    return json.dumps(obj).encode()


def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# 1.7 million ms after 1970 is far below 1e11; these are real epoch milliseconds
MS_2023 = 1_700_000_000_000
MS_2024 = 1_720_000_000_000


def _export():
    """A small export with every kind of thing the scan has to handle."""
    uds = [
        {"calendarDate": "2023-01-05", "uuid": "u1", "totalSteps": 1000, "restingHeartRate": 55,
         "bodyBattery": None, "stress": {}, "floors": 0, "flags": [], "note": "", "john@home": "v"},
        {"calendarDate": "2023-01-06", "uuid": "u2", "totalSteps": 0, "restingHeartRate": 56,
         "bodyBattery": {"high": 90}, "stress": {"avg": 20}, "floors": 3, "flags": [True], "note": "x"},
        {"calendarDate": "2024-02-01", "uuid": "u3", "totalSteps": 500},
        {"uuid": "u4", "totalSteps": 7},                                   # no date → year unknown
    ]
    sleep = [
        {"calendarDate": "2023-01-05", "deepSleepSeconds": 3600, "sleepScores": {"overall": {"value": 80}},
         "devices": {"3412345678": {"x": 1}}, "napList": [{"a": None}, {"a": 1}]},
        {"calendarDate": "2023-01-06T10:00:00.0", "deepSleepSeconds": None, "napList": []},
    ]
    activities = [{"summarizedActivitiesExport": [
        {"activityId": 1, "startTimeLocal": MS_2023, "name": "Run", "distance": 5.5,
         "laps": [{"d": 1}, {"d": 0}], "hrTimeInZone_1": 10},
        {"activityId": 2, "startTimeLocal": MS_2024, "name": "", "distance": 0},
        "not an object",
    ]}]
    load = [{"calendarDate": MS_2023, "acwrPercent": 10, "status": "OPTIMAL"},
            {"calendarDate": MS_2024, "acwrPercent": 0, "status": None}]
    bio = [{"metaData": {"calendarDate": "2022-06-01"}, "weight": {"weight": 70000}, "vo2MaxRunning": 50},
           {"metaData": {"calendarDate": "2022-07-01"}, "vo2MaxRunning": None}]
    return {
        AGG + "UDSFile_2023-01-01_2023-03-31.json": _j(uds),
        WELL + "2023-01-01_2023-03-31_123456_sleepData.json": _j(sleep),
        WELL + "2023-04-01_2023-06-30_123456_sleepData.json": b"{ this is not json",
        FITNESS + f"{SECRET}_summarizedActivities.json": _j(activities),
        MET + "MetricsAcuteTrainingLoad_2023.json": _j(load),
        WELL + f"2022_{SECRET}_userBioMetrics.json": _j(bio),
        WELL + f"{SECRET}_heartRateZones.json": _j([{"zone1": 100, "sport": "RUNNING"}]),
        "DI_CONNECT/DI-Connect-User/profile.json": _j({"name": SECRET}),
        f"DI_CONNECT/{SECRET}/other.json": _j([1]),
        "IT_ORDERS/orders.json": _j([{"value": SECRET}]),
        "IT_ORDERS/readme.txt": b"hello",
        f"{SECRET}/notes.txt": b"hello",                                   # a folder named after the account
        "DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_1_Part1.zip": b"PK-not-really",
        "DI_CONNECT/DI-Connect-Uploaded-Files/loose.fit": b"FIT",
    }


def _make_zip(name="export.zip", entries=None):
    return _put(BASE / name, _zip_bytes(entries if entries is not None else _export()))


def _make_dir(name="export_dir", entries=None):
    root = BASE / name
    for entry, data in (entries if entries is not None else _export()).items():
        _put(root / entry, data)
    return root


def _fam(result, key):
    return result["families"][key]


def _field(result, key, path, year):
    return _fam(result, key)["fields"][path][year]


# ── 1. the table of families against the import ─────────────────────────────

section("1. table of families — the same families, folders and limits as garmin_import")

check("read families: same keys, same order as garmin_import._KINDS",
      [f.key for f in es._READ] == [k for k, *_ in gi._KINDS])
check("read families: folder and name part equal to garmin_import._KINDS",
      all((f.prefix, f.keyword) == (p, kw) for f, (_k, p, kw, _m) in zip(es._READ, gi._KINDS)))
check("kept families: same keys, same order as garmin_import._SAVED_FAMILIES",
      [f.key for f in es._KEPT] == [k for k, *_ in gi._SAVED_FAMILIES])
check("kept families: folder and pattern equal to garmin_import._SAVED_FAMILIES",
      all((f.prefix, f.pattern.pattern) == (p, rx.pattern) for f, (_k, p, rx) in zip(es._KEPT, gi._SAVED_FAMILIES)))
check("every family of the import is in FAMILIES with the status read / kept",
      all(es.FAMILIES[k].status == es.STATUS_READ for k, *_ in gi._KINDS)
      and all(es.FAMILIES[k].status == es.STATUS_KEPT for k, *_ in gi._SAVED_FAMILIES))
check("MAX_JSON_BYTES equal to garmin_import.MAX_JSON_BYTES", es.MAX_JSON_BYTES == gi.MAX_JSON_BYTES)
check("every family has a group of GROUPS and a known status",
      all(f.group in dict(es.GROUPS) and f.status in (es.STATUS_READ, es.STATUS_KEPT, es.STATUS_KNOWN)
          for f in es.FAMILIES.values()))
check("FAMILIES holds every table entry once", len(es.FAMILIES) == len(es._READ) + len(es._KEPT) + len(es._KNOWN))


def _names_for(fam):
    """Names around the standard one of a family: standard, no folder, wrapped root, wrong ending."""
    keyword = fam.keyword or fam.key
    stem = {"gear": "a_gear", "personalRecord": "a_personalRecord", "courses": "x_courses_1",
            "zones": "a_heartRateZones"}.get(fam.key, f"a_{keyword}")
    names = [fam.prefix + stem + ".json", fam.prefix + stem + "_2023.json",
             "wrap/" + fam.prefix + stem + ".json", "DI_CONNECT/Other/" + stem + ".json",
             fam.prefix + stem + ".txt", fam.prefix + "b" + stem + ".json"]
    if fam.key == "zones":
        names.append(fam.prefix + "a_powerZones.json")
    return names


def _import_view(name):
    inv = gi.build_inventory([name])
    for key, count in inv["read"].items():
        if count:
            return (es.STATUS_READ, key)
    for key, count in inv["kept"].items():
        if count:
            return (es.STATUS_KEPT, key)
    return None


agree = True
for family in list(es._READ) + list(es._KEPT):
    for n in _names_for(family):
        fam = es.classify(n)
        mine = (fam.status, fam.key) if fam is not None and fam.status != es.STATUS_KNOWN else None
        if mine != _import_view(n):
            agree = False
check("classify(): read / kept agree with garmin_import.build_inventory on %d names around the standard ones"
      % sum(len(_names_for(f)) for f in list(es._READ) + list(es._KEPT)), agree)

known_standard = all(
    es.classify(fam.prefix + f"a_{fam.keyword}.json") is fam and _import_view(fam.prefix + f"a_{fam.keyword}.json") is None
    for fam in es._KNOWN)
check("classify(): each known family is found by its folder and name part and is unknown to the import",
      known_standard)
check("classify(): the e-mail address of the name cannot match a known family",
      es.classify(FITNESS + "workout.fan@example.invalid_other.json") is None
      and es.classify(FITNESS + "x@example.invalid_workout.json").key == "workout")
check("classify(): a read family wins over a known one with the same name part",
      es.classify(FITNESS + "workout.fan@example.invalid_summarizedActivities.json").key == "activities")
check("classify(): not a .json name, not a string → None",
      es.classify(AGG + "UDSFile_1.txt") is None and es.classify(None) is None and es.classify(5) is None)

# ── 2. dates ────────────────────────────────────────────────────────────────

section("2. the year of a row — four shapes of a date")

check("year: ISO string", es._year_of("2023-04-05") == "2023")
check("year: ISO date-time", es._year_of("2022-12-31T23:59:59.0") == "2022")
check("year: epoch milliseconds", es._year_of(MS_2023) == "2023" and es._year_of(float(MS_2024)) == "2024")
check("year: list of numbers [y, m, d, ...]", es._year_of([2021, 5, 1, 0, 0, 0]) == "2021")
check("year: no date → None",
      all(es._year_of(v) is None for v in (None, "", "yesterday", True, [], [1, 2], ["a", 1, 2], {}, 1_700_000_000)))
check("year: outside 1990..2100 → None (0001-01-01, year 1969, year 3000)",
      es._year_of("0001-01-01") is None and es._year_of(-5_000_000_000_000) is None and es._year_of("3000-01-01") is None)
check("year: float infinity and nan do not raise",
      es._year_of(float("inf")) is None and es._year_of(float("nan")) is None)
check("date key with a path (metaData.calendarDate)", es._dig({"metaData": {"calendarDate": "x"}}, "metaData.calendarDate") == "x")
check("date key: path through a non-object → None", es._dig({"metaData": 5}, "metaData.calendarDate") is None)

# ── 3. what a scan of a standard export counts ──────────────────────────────

section("3. scan of an export — files, rows, years, field states")

zip_path = _make_zip()
res = es.scan(zip_path)

check("source zip, not stopped", res["source"] == "zip" and res["stopped"] is False)
files = res["files"]
check("JSON files: 10 total, 6 of them read, 1 unreadable",
      files["json_total"] == 10 and files["json_read"] == 6 and files["unreadable"] == 1 and files["too_large"] == 0)
check("not recognised: 3 JSON files (profile, the @ folder, orders)", files["unknown_json"] == 3)
check("nested ZIP, FIT and other files counted, not opened",
      files["nested_zips"] == 1 and files["fit"] == 1 and files["other"] == 2)
check("every family is in the result (also with 0 files)", set(res["families"]) == set(es.FAMILIES))
check("statuses: uds read, zones kept, MetricsAcuteTrainingLoad known",
      _fam(res, "uds")["status"] == "read" and _fam(res, "zones")["status"] == "kept"
      and _fam(res, "MetricsAcuteTrainingLoad")["status"] == "known")
check("a family without files has 0 files and no fields", _fam(res, "gear")["files"] == 0 and _fam(res, "gear")["fields"] == {})

uds = _fam(res, "uds")
check("uds: 1 file, 4 rows, years 2023: 2, 2024: 1, unknown: 1 (unknown last)",
      uds["files"] == 1 and uds["rows"] == 4 and uds["years"] == {"2023": 2, "2024": 1, "unknown": 1}
      and list(uds["years"]) == ["2023", "2024", "unknown"])
check("field filled: totalSteps 2023 → one filled, one zero",
      _field(res, "uds", "totalSteps", "2023") == {"filled": 1, "zero": 1, "empty": 0, "absent": 0})
check("field empty: bodyBattery null in one row, filled in the other (2023)",
      _field(res, "uds", "bodyBattery.high", "2023")["filled"] == 1
      and _field(res, "uds", "bodyBattery", "2023")["empty"] == 1)
check("field empty: {} and [] and \"\" count as empty",
      _field(res, "uds", "stress", "2023")["empty"] == 1 and _field(res, "uds", "flags", "2023")["empty"] == 1
      and _field(res, "uds", "note", "2023")["empty"] == 1)
check("field zero: 0 is a zero, not empty, not filled",
      _field(res, "uds", "floors", "2023") == {"filled": 1, "zero": 1, "empty": 0, "absent": 0})
check("field: true is a value (filled)", _field(res, "uds", "flags[]", "2023")["filled"] == 1)
check("a key with an @ becomes the mark <key>, the key itself is not in any path",
      "<key>" in uds["fields"] and not any("@" in p for p in uds["fields"]))
check("field absent: a key missing in the rows of a year", _field(res, "uds", "restingHeartRate", "2024")["absent"] == 1
      and _field(res, "uds", "restingHeartRate", "unknown")["absent"] == 1)
check("every field of every year adds up to the rows of that year",
      all(sum(c.values()) == fam["years"][y]
          for fam in res["families"].values() for per_year in fam["fields"].values() for y, c in per_year.items()))

sleep = _fam(res, "sleep")
check("sleep: 2 files found, 1 unreadable, rows of the readable one", sleep["files"] == 2 and sleep["unreadable"] == 1 and sleep["rows"] == 2)
check("sleep: the ISO date-time gives its year", sleep["years"] == {"2023": 2})
check("device-id key becomes <id>", "devices.<id>.x" in sleep["fields"] and "devices.3412345678.x" not in sleep["fields"])
check("a list of objects: the field is the path with [] and the best state of the row counts",
      _field(res, "sleep", "napList[].a", "2023") == {"filled": 1, "zero": 0, "empty": 0, "absent": 1}
      and _field(res, "sleep", "napList", "2023")["empty"] == 1)

acts = _fam(res, "activities")
check("activities: wrapper list read, 2 activities as rows, the string entry is skipped and counted",
      acts["rows"] == 2 and acts["skipped_rows"] == 1 and acts["years"] == {"2023": 1, "2024": 1})
check("activities: 0 distance is a zero, \"\" name is empty",
      _field(res, "activities", "distance", "2024")["zero"] == 1 and _field(res, "activities", "name", "2024")["empty"] == 1)

load = _fam(res, "MetricsAcuteTrainingLoad")
check("known family with epoch-millisecond date: years 2023 and 2024", load["years"] == {"2023": 1, "2024": 1})
bio = _fam(res, "userBioMetrics")
check("known family with a date key inside an object (metaData.calendarDate): years 2022", bio["years"] == {"2022": 2})
zones = _fam(res, "zones")
check("kept family has no date key: rows count for the year unknown", zones["years"] == {"unknown": 1})

unknown = res["unknown"]
check("unknown folders: the @ folder is <hidden>, the plain one is named",
      "<hidden>" in unknown["folders"] and "DI_CONNECT/DI-Connect-User" in unknown["folders"]
      and "IT_ORDERS" in unknown["folders"] and unknown["files"] == 3)
tops = {e["folder"]: e["files"] for e in res["folders"]}
check("top folders: DI_CONNECT and IT_ORDERS with their file counts (all file types)",
      tops.get("IT_ORDERS") == 2 and tops.get("DI_CONNECT", 0) >= 10)
check("top folders: a folder named after the account shows as <hidden>",
      tops.get("<hidden>") == 1 and not any("@" in name for name in tops))
check("groups: every family is in exactly one group, in the order of GROUPS",
      [g["key"] for g in res["groups"]] == [k for k, _ in es.GROUPS]
      and sorted(f for g in res["groups"] for f in g["families"]) == sorted(es.FAMILIES))
check("the result survives a JSON round trip", json.loads(json.dumps(res)) == res)

# ── 4. ZIP and folder ───────────────────────────────────────────────────────

section("4. a ZIP and the same export unpacked give the same result")

dir_path = _make_dir()
before = _snapshot(dir_path)
res_dir = es.scan(dir_path)
res_zip = dict(res)
check("folder: source folder", res_dir["source"] == "folder")
check("same result except the source", {**res_dir, "source": "zip"} == res_zip)
check("the export folder was not changed by the scan", _snapshot(dir_path) == before)

# ── 5. limits and bad input ────────────────────────────────────────────────

section("5. limits, bad input, stop")

with patch.object(es, "MAX_JSON_BYTES", 50):
    small = es.scan(zip_path)
check("a file over the size limit is counted as too large and not read",
      small["files"]["too_large"] >= 1 and _fam(small, "uds")["rows"] == 0 and _fam(small, "uds")["too_large"] == 1)

wide = {"calendarDate": "2023-01-01", **{f"k{i}": i for i in range(600)}}
wide_res = es.scan(_make_zip("wide.zip", {AGG + "UDSFile_1.json": _j([wide])}))
wf = _fam(wide_res, "uds")
check("more than MAX_PATHS_PER_FAMILY paths: kept paths are capped and reported as truncated",
      wf["truncated"] is True and len(wf["fields"]) == es.MAX_PATHS_PER_FAMILY and wf["rows"] == 1)

deep = cur = {}
for _ in range(40):
    cur["a"] = {}
    cur = cur["a"]
cur["leaf"] = 1
deep_res = es.scan(_make_zip("deep.zip", {AGG + "UDSFile_2.json": _j([{"calendarDate": "2023-01-01", "x": deep}])}))
check("deeply nested JSON does not raise; below MAX_DEPTH it counts as one value",
      _fam(deep_res, "uds")["rows"] == 1 and any(p.startswith("x") for p in _fam(deep_res, "uds")["fields"]))

with patch.object(es, "MAX_DEPTH", 3):
    capped = es.scan(_make_zip("capped.zip", {AGG + "UDSFile_7.json": _j([
        {"calendarDate": "2023-01-01", "a": {"b": {"c": {"d": 1}}}, "l": [[[[1]]]]}])}))
cf = set(_fam(capped, "uds")["fields"])
check("MAX_DEPTH: below the limit a nested object counts as one filled value at its path",
      cf == {"calendarDate", "a.b.c", "l[][]"}
      and _field(capped, "uds", "a.b.c", "2023")["filled"] == 1)

very_deep = ('{"calendarDate": "2023-01-01", "x": ' + '{"a": ' * 800 + "1" + "}" * 800 + "}").encode()
try:
    vd = es.scan(_make_zip("very_deep.zip", {AGG + "UDSFile_6.json": b"[" + very_deep + b"]"}))
    vd_ok = _fam(vd, "uds")["rows"] == 1 or _fam(vd, "uds")["unreadable"] == 1
except RecursionError:
    vd_ok = False
check("800 levels of nesting: no RecursionError (the row is counted, or the file is counted as unreadable)", vd_ok)

weird = es.scan(_make_zip("weird.zip", {AGG + "UDSFile_3.json": _j([
    {"calendarDate": "2023-01-01", "": 1, "a.b": 2, "x" * 50: 3, "a\nb": 4, "12345": 5, "123e4567-e89b-12d3-a456-426614174000": 6}])}))
wk = set(_fam(weird, "uds")["fields"])
check("keys of an odd kind become marks: empty, with dot, too long, control character, digits, UUID",
      wk == {"calendarDate", "<key>", "<id>"})

check("a top-level object (no list) counts as one row",
      _fam(es.scan(_make_zip("obj.zip", {AGG + "UDSFile_4.json": _j({"calendarDate": "2023-02-02", "totalSteps": 1})})),
           "uds")["rows"] == 1)
check("a JSON file of the wrong shape (a number) gives no rows and no error",
      _fam(es.scan(_make_zip("num.zip", {AGG + "UDSFile_5.json": b"5"})), "uds")["rows"] == 0)

try:
    es.scan(BASE / "does_not_exist.zip")
    missing_ok = False
except FileNotFoundError as e:
    missing_ok = "does_not_exist" not in str(e) and str(BASE) not in str(e)
check("missing path: FileNotFoundError without the path in the message", missing_ok)
check("a file that is not a ZIP: source unreadable, no error",
      es.scan(_put(BASE / "plain.txt", b"hello"))["source"] == "unreadable")
check("a damaged ZIP: source unreadable, no error",
      es.scan(_put(BASE / "broken.zip", _zip_bytes(_export())[:60]))["source"] == "unreadable")
(BASE / "empty").mkdir()
check("an empty folder: source folder, nothing counted",
      es.scan(BASE / "empty")["source"] == "folder" and es.scan(BASE / "empty")["files"]["json_total"] == 0)

asked = []


def _stop_after_first():
    asked.append(1)
    return len(asked) > 1


stopped = es.scan(zip_path, should_stop=_stop_after_first)
check("should_stop: the scan ends early and says so (partial numbers)",
      stopped["stopped"] is True and stopped["files"]["json_read"] < res["files"]["json_read"])
progress = []
es.scan(zip_path, progress=lambda done, total: progress.append((done, total)))
check("progress: called once per classified JSON file, done counts up to total",
      [d for d, _ in progress] == list(range(1, 8)) and {t for _, t in progress} == {7})
check("no should_stop, no progress: nothing needed", es.scan(zip_path)["stopped"] is False)

# ── 6. the report ───────────────────────────────────────────────────────────

section("6. the report — text, JSON, replaced at every run")

text = es.format_report(res)
check("text: header, status wording, group headings and a field line",
      text.startswith("GLA export scan") and "== Daily values ==" in text and "[read by GLA]" in text
      and "[known, not read by GLA]" in text and "totalSteps" in text)
check("text: families without files are listed once as not in this export",
      "Not in this export:" in text and "gear" in text)
check("text: shares are rounded whole percentages of all rows",
      any(line.strip().startswith("totalSteps") and line.rstrip().endswith("%") for line in text.splitlines()))
check("text: a stopped scan says its numbers are incomplete", "incomplete" in es.format_report(stopped))
check("text: a scan result of an unreadable source still formats", "Source: unreadable" in es.format_report(es.scan(BASE / "plain.txt")))

fit_part = {"schema": 1, "stopped": False,
            "files": {"seen": 10, "read": 7, "duplicates": 1, "oversize": 0, "unreadable_entries": 0, "zips_opened": 3,
                      "zips_unreadable": 0, "too_deep": 0, "damaged": {"crc": 1, "not_fit": 1}},
            "types": {"32": {"files": 4, "years": {"2019": 2, "2020": 1, "unknown": 1}},
                      "none": {"files": 1, "years": {"2022": 1}}},
            "years": {"2019": 2, "2020": 1, "2022": 1, "unknown": 1}}
text_fit = es.format_report({**res, "fit": fit_part})
check("text with a FIT part: its own section with the counts and the damaged reasons",
      "== FIT files ==" in text_fit
      and "7 different files read, 10 seen, 1 again with the same content, 2 damaged (crc: 1, not_fit: 1)" in text_fit)
check("text with a FIT part: one line per type with its years",
      "type 32: 4 files  (2019: 2, 2020: 1, unknown: 1)" in text_fit and "type none: 1 files  (2022: 1)" in text_fit)
check("text with a FIT part: the section stands between the families and the not recognised files",
      text_fit.index("== Training & metrics ==") < text_fit.index("== FIT files ==") < text_fit.index("== Not recognised =="))
check("text without a FIT part, or with an empty one: no FIT section",
      "FIT files ==" not in text and "FIT files ==" not in es.format_report({**res, "fit": None}))
bad_fit = {**fit_part, "stopped": True, "files": {**fit_part["files"], "oversize": 2, "zips_unreadable": 1, "damaged": {}}}
text_bad = es.format_report({**res, "fit": bad_fit})
check("text: a stopped FIT scan and the files the walk did not read are said",
      "The FIT scan was stopped before the end" in text_bad and "not read: too large 2, unreadable entries 0, unreadable ZIPs 1" in text_bad
      and "0 damaged" in text_bad and "damaged (" not in text_bad)
check("write_report: the FIT part is in the JSON file and the section in the text file",
      json.loads(es.write_report({**res, "fit": fit_part}, BASE / "log_fit")["json"].read_text(encoding="utf-8"))["fit"] == fit_part
      and "== FIT files ==" in (BASE / "log_fit" / "export_scan_report.txt").read_text(encoding="utf-8"))

log_dir = BASE / "log"
paths = es.write_report(res, log_dir)
check("write_report: both files exist, named export_scan_report.json / .txt",
      paths["json"] == log_dir / "export_scan_report.json" and paths["text"] == log_dir / "export_scan_report.txt"
      and paths["json"].exists() and paths["text"].exists())
check("text: the top folders are listed with their file counts, the account folder as <hidden>",
      "IT_ORDERS: 2 files" in text and "<hidden>: 1 files" in text and "== Not recognised ==" in text
      and "in folders:" in text)
check("write_report: the JSON file is the result", json.loads(paths["json"].read_text(encoding="utf-8")) == res)
check("write_report: the text file is the text report", paths["text"].read_text(encoding="utf-8") == text)
check("write_report: no line break conversion (LF only)", b"\r" not in paths["text"].read_bytes())
es.write_report(small, log_dir)
check("write_report: a second run replaces the first, no temporary file is left",
      json.loads(paths["json"].read_text(encoding="utf-8")) == small
      and not list(log_dir.glob("*.tmp")) and len(list(log_dir.iterdir())) == 2)

# ── 7. privacy ──────────────────────────────────────────────────────────────

section("7. privacy — the marker of the e-mail address never shows up")

root_logger = logging.getLogger()
stream = io.StringIO()
handler = logging.StreamHandler(stream)
old_level = root_logger.level
root_logger.addHandler(handler)
root_logger.setLevel(logging.DEBUG)
out, err = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        priv_zip = es.scan(zip_path)
        priv_dir = es.scan(dir_path)
        priv_text = es.format_report(priv_zip)
        priv_paths = es.write_report(priv_zip, BASE / "log_priv")
finally:
    root_logger.removeHandler(handler)
    root_logger.setLevel(old_level)

check("the marker is in the export names, folders and values (the test is meaningful)",
      any(SECRET in n for n in _export()) and any(SECRET.encode() in d for d in _export().values()))
check("the marker is not in the result of a ZIP scan, a folder scan, the text, or the written files",
      SECRET not in json.dumps(priv_zip) and SECRET not in json.dumps(priv_dir) and SECRET not in priv_text
      and SECRET.encode() not in priv_paths["json"].read_bytes() and SECRET.encode() not in priv_paths["text"].read_bytes())
check("no part of the marker (name or domain) is in the result",
      "secret.name" not in json.dumps(priv_zip) and "example.invalid" not in json.dumps(priv_zip))
check("nothing is logged, printed or written to stderr during a scan",
      stream.getvalue() == "" and out.getvalue() == "" and err.getvalue() == "")
check("no value of the export is in the result (a string value of the data)",
      "OPTIMAL" not in json.dumps(priv_zip) and "RUNNING" not in json.dumps(priv_zip)
      and '"Run"' not in json.dumps(priv_zip))

bad_entries = {AGG + "UDSFile_9.json": b"\xff\xfe not json " + SECRET.encode()}
bad = es.scan(_make_zip("bad_bytes.zip", bad_entries))
check("an unreadable file: counted, its content and name are not in any output",
      bad["files"]["unreadable"] == 1 and SECRET not in json.dumps(bad) and SECRET not in es.format_report(bad))

# ── 8. the detail of one field by month ─────────────────────────────────────

section("8. scan_field — one field by month, on demand")

check("month: ISO string and date-time", es._month_of("2023-04-05") == "2023-04" and es._month_of("2022-12-31T23:59:59.0") == "2022-12")
check("month: epoch milliseconds", es._month_of(MS_2023) == "2023-11" and es._month_of(float(MS_2024)) == "2024-07")
check("month: list of numbers [y, m, d, ...]", es._month_of([2021, 5, 1, 0, 0, 0]) == "2021-05")
check("month: no date, a month outside 1..12, a year outside the range → None",
      all(es._month_of(v) is None for v in (None, "", "yesterday", True, [], [1, 2], ["a", 1, 2], {}, 1_700_000_000,
                                           "2023-13-01", "2023-00-01", [2023, 0, 1], [2023, 13, 1], "0001-01-01", "3000-01-01",
                                           float("inf"), float("nan"))))
shapes = ["2023-04-05", "2022-12-31T23:59:59.0", MS_2023, float(MS_2024), [2021, 5, 1, 0, 0, 0], None, "x", True, [1, 2],
          "0001-01-01", "3000-01-01", 1_700_000_000, 2 ** 62]
check("month and year agree on every valid date shape (the year of the month is the year)",
      all((es._month_of(v) or "    ")[:4].strip() == (es._year_of(v) or "") for v in shapes))

fz = es.scan_field(zip_path, "uds", "totalSteps")
check("a field: months with the four states, rows, files, source",
      fz["months"] == {"2023-01": {"rows": 2, "filled": 1, "zero": 1, "empty": 0, "absent": 0},
                       "2024-02": {"rows": 1, "filled": 1, "zero": 0, "empty": 0, "absent": 0},
                       "unknown": {"rows": 1, "filled": 1, "zero": 0, "empty": 0, "absent": 0}}
      and fz["rows"] == 4 and fz["files"] == 1 and fz["source"] == "zip" and fz["stopped"] is False)
check("a field: first and last month with a value, the rows without a date do not count for them",
      fz["first"] == "2023-01" and fz["last"] == "2024-02" and list(fz["months"]) == ["2023-01", "2024-02", "unknown"])
check("the result names the family and the field, schema 1",
      fz["family"] == "uds" and fz["label"] == "UDSFile" and fz["field"] == "totalSteps" and fz["schema"] == 1)
rhr = es.scan_field(zip_path, "uds", "restingHeartRate")
check("a field in some rows only: absent in the others, first = last month with a value",
      rhr["months"]["2023-01"]["filled"] == 2 and rhr["months"]["2024-02"]["absent"] == 1
      and rhr["months"]["unknown"]["absent"] == 1 and rhr["first"] == "2023-01" and rhr["last"] == "2023-01")
check("empty, zero and absent are told apart (null, {}, 0)",
      es.scan_field(zip_path, "uds", "bodyBattery")["months"]["2023-01"]["empty"] == 1
      and es.scan_field(zip_path, "uds", "stress")["months"]["2023-01"] == {"rows": 2, "filled": 0, "zero": 0, "empty": 1, "absent": 1}
      and es.scan_field(zip_path, "uds", "floors")["months"]["2023-01"] == {"rows": 2, "filled": 1, "zero": 1, "empty": 0, "absent": 0})
nothing = es.scan_field(zip_path, "uds", "does.not.exist")
check("a field that is nowhere: every row absent, no first and no last month",
      nothing["first"] is None and nothing["last"] is None and nothing["rows"] == 4
      and all(m["absent"] == m["rows"] for m in nothing["months"].values()))
check("the same normalised path as the scan: a list of objects and an id key",
      es.scan_field(zip_path, "sleep", "napList[].a")["months"]["2023-01"] == {"rows": 2, "filled": 1, "zero": 0, "empty": 0, "absent": 1}
      and es.scan_field(zip_path, "sleep", "devices.<id>.x")["months"]["2023-01"]["filled"] == 1)
check("every field path of the scan result can be asked for (the counts agree with the table by year)",
      all(sum(m["filled"] + m["zero"] for k, m in es.scan_field(zip_path, "uds", p)["months"].items() if k[:4] == "2023") ==
          sum(res["families"]["uds"]["fields"][p].get("2023", {"filled": 0, "zero": 0}).get(s, 0) for s in ("filled", "zero"))
          for p in res["families"]["uds"]["fields"]))
act = es.scan_field(zip_path, "activities", "distance")
check("epoch-millisecond dates give their month; the wrapper list is followed; a row that is no object is skipped",
      act["months"] == {"2023-11": {"rows": 1, "filled": 1, "zero": 0, "empty": 0, "absent": 0},
                        "2024-07": {"rows": 1, "filled": 0, "zero": 1, "empty": 0, "absent": 0}} and act["rows"] == 2)
snl = es.scan_field(zip_path, "sleep", "deepSleepSeconds")
check("only the files of the family are read: 2 sleep files, one of them damaged (counted, no error)",
      snl["files"] == 2 and snl["unreadable"] == 1 and snl["rows"] == 2 and fz["files"] == 1)
check("a ZIP and the same export as a folder give the same detail (the source apart)",
      {**es.scan_field(dir_path, "uds", "totalSteps"), "source": "zip"} == fz)

many = _make_zip("many_months.zip", {AGG + "UDSFile_m.json": _j([
    {"calendarDate": "2024-12-01", "v": 1}, {"calendarDate": "2023-03-01", "v": 0}, {"calendarDate": "2023-01-15", "v": None},
    {"v": 5}, {"calendarDate": "2023-03-20", "v": 2}])})
fm = es.scan_field(many, "uds", "v")
check("months come out ascending with unknown last, whatever the order in the file",
      list(fm["months"]) == ["2023-01", "2023-03", "2024-12", "unknown"]
      and fm["months"]["2023-03"] == {"rows": 2, "filled": 1, "zero": 1, "empty": 0, "absent": 0}
      and fm["first"] == "2023-03" and fm["last"] == "2024-12")
zero_first = es.scan_field(_make_zip("zero_first.zip", {AGG + "UDSFile_z.json": _j([
    {"calendarDate": "2023-01-01", "v": 0}, {"calendarDate": "2023-02-01", "v": 5}, {"calendarDate": "2023-03-01", "v": None}])}),
    "uds", "v")
check("a 0 is a value: a month with only zeros is the first month with a value, an empty last month is not the last",
      zero_first["first"] == "2023-01" and zero_first["last"] == "2023-02")
check("a family without a date key: all rows count for unknown",
      es.scan_field(zip_path, "zones", "zone1")["months"] == {"unknown": {"rows": 1, "filled": 1, "zero": 0, "empty": 0, "absent": 0}})

try:
    es.scan_field(BASE / "does_not_exist.zip", "uds", "totalSteps")
    fnf_ok = False
except FileNotFoundError as exc:
    fnf_ok = "does_not_exist" not in str(exc) and str(BASE) not in str(exc)
check("missing path: FileNotFoundError without the path", fnf_ok)
bad_args = []
for args in (("nope", "totalSteps"), ("uds", ""), ("uds", None), ("uds", 5)):
    try:
        es.scan_field(zip_path, *args)
        bad_args.append(args)
    except ValueError as exc:
        if "uds" in str(exc) or "totalSteps" in str(exc) or str(BASE) in str(exc):
            bad_args.append(args)
check("an unknown family or an empty field: ValueError, the message names nothing", bad_args == [])
check("a file that is no ZIP / a damaged ZIP: source unreadable, nothing counted, no error",
      es.scan_field(BASE / "plain.txt", "uds", "totalSteps")["source"] == "unreadable"
      and es.scan_field(BASE / "broken.zip", "uds", "totalSteps")["rows"] == 0
      and es.scan_field(BASE / "broken.zip", "uds", "totalSteps")["months"] == {})
stop_field = es.scan_field(zip_path, "uds", "totalSteps", should_stop=lambda: True)
check("should_stop: the detail ends at once and says so", stop_field["stopped"] is True and stop_field["files"] == 0)
with patch.object(es, "MAX_JSON_BYTES", 50):
    check("a file over the size limit is counted as too large", es.scan_field(zip_path, "uds", "totalSteps")["too_large"] == 1)

import shutil as _shutil
copy_zip = BASE / "copy_to_remove.zip"
_shutil.copyfile(zip_path, copy_zip)
es.scan_field(copy_zip, "uds", "totalSteps")
es.scan(copy_zip)
try:
    copy_zip.unlink()
    closed_ok = True
except OSError:
    closed_ok = False
check("the ZIP is closed after scan() and scan_field() (the file can be deleted)", closed_ok)

opened_zips = []


class _SpyZip(zipfile.ZipFile):
    """Keeps every ZipFile it makes, so that a ZIP that was not closed stays open (the garbage collector would close it)."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        opened_zips.append(self)


with patch.object(es.zipfile, "ZipFile", _SpyZip):
    es.scan_field(zip_path, "uds", "totalSteps")
    es.scan(zip_path)
    es.scan_field(zip_path, "uds", "totalSteps", should_stop=lambda: True)
check("every ZIP the scan and the detail opened is closed when they return (also after a stop)",
      len(opened_zips) == 3 and all(z.fp is None for z in opened_zips))

stream_f = io.StringIO()
handler_f = logging.StreamHandler(stream_f)
root_logger.addHandler(handler_f)
root_logger.setLevel(logging.DEBUG)
out_f, err_f = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out_f), contextlib.redirect_stderr(err_f):
        priv_a = es.scan_field(zip_path, "activities", "name")
        priv_b = es.scan_field(dir_path, "uds", "totalSteps")
finally:
    root_logger.removeHandler(handler_f)
    root_logger.setLevel(old_level)
check("the detail holds no file name, no e-mail marker, no value of the data (names of activities)",
      all(SECRET not in json.dumps(r) and "secret.name" not in json.dumps(r) and "example.invalid" not in json.dumps(r)
          and '"Run"' not in json.dumps(r) for r in (priv_a, priv_b)))
check("nothing is logged, printed or written to stderr during a detail scan",
      stream_f.getvalue() == "" and out_f.getvalue() == "" and err_f.getvalue() == "")
check("the result holds only numbers, months, the family and the field",
      set(priv_a) == {"schema", "source", "family", "label", "field", "stopped", "files", "unreadable", "too_large",
                      "rows", "months", "first", "last"})

# ── 9. read_values — the values of one numeric field (the values view) ───────

section("9. read_values — values by date, kept apart from the scan")

SENTINEL = 987654.321                    # a value that must never appear in a scan result or a report
check("date: ISO string, date-time, epoch milliseconds, list of numbers",
      es._date_of("2023-04-05") == "2023-04-05" and es._date_of("2022-12-31T23:59:59.0") == "2022-12-31"
      and es._date_of(MS_2023) == "2023-11-14" and es._date_of(float(MS_2024)) == "2024-07-03"
      and es._date_of([2021, 5, 1, 0, 0, 0]) == "2021-05-01")
check("date: a day that is not in the calendar, a year outside the range, no date → None",
      all(es._date_of(v) is None for v in ("2023-02-30", "2023-13-01", "2023-00-10", "2023-04-00", "0001-01-01", "3000-01-01",
                                           None, "", True, [], [2023, 2, 30], [2023, 13, 1], 1_700_000_000, float("inf"), float("nan")))
      and es._date_of("2024-02-29") == "2024-02-29" and es._date_of("2023-02-29") is None)
check("date and month agree on every valid date shape (the month of the date is the month)",
      all((es._date_of(v) or "")[:7] == (es._month_of(v) or "") for v in
          ["2023-04-05", "2022-12-31T23:59:59.0", MS_2023, float(MS_2024), [2021, 5, 1, 0, 0, 0], None, "x", True, [1, 2]]))
check("number: ints and floats are numbers, a bool, text, nan, inf and null are not",
      es._number(5) == 5 and es._number(2.5) == 2.5 and isinstance(es._number(5), int)
      and all(es._number(v) is None for v in (True, False, "5", None, float("nan"), float("inf"), [1], {})))
check("stats: odd and even number of values, zeros counted",
      es._stats([3, 1, 2]) == {"count": 3, "min": 1, "max": 3, "mean": 2.0, "median": 2, "zeros": 0}
      and es._stats([4, 1, 3, 0]) == {"count": 4, "min": 0, "max": 4, "mean": 2.0, "median": 2.0, "zeros": 1})
check("histogram: all values counted, the largest value in the last bin, one bin when all are equal",
      sum(es._histogram([10, 20, 30])["counts"]) == 3 and es._histogram([10, 20, 30])["counts"][-1] == 1
      and es._histogram([10, 20, 30])["edges"][0] == 10 and es._histogram([10, 20, 30])["edges"][-1] == 30
      and len(es._histogram([10, 20, 30])["edges"]) == es.HISTOGRAM_BINS + 1
      and es._histogram([7, 7, 7]) == {"edges": [7, 7], "counts": [3]})
check("values_supported: plain paths yes; a list, a masked key, an empty part, nothing no",
      es.values_supported("a") and es.values_supported("a.b") and es.values_supported("weight.weight")
      and not any(es.values_supported(p) for p in ("a[].b", "devices.<id>.x", "x.<key>", "", "a..b", None, 5)))

values_zip = _make_zip("values.zip", {
    AGG + "UDSFile_v1.json": _j([
        {"calendarDate": "2023-01-05", "v": 10, "f": 2.5, "b": True, "z": 0, "nested": {"x": 7}, "sentinel": SENTINEL},
        {"calendarDate": "2023-01-05", "v": 30, "f": 0.5},
        {"calendarDate": "2022-12-31", "v": 20, "f": 1.5, "z": 0},
        {"v": 99},
        {"calendarDate": "2023-02-01", "v": "x", "b": False},
        {"calendarDate": "2023-02-02"},
        {"calendarDate": "2023-02-03", "v": None},
        "not an object"]),
    AGG + "UDSFile_v2.json": b'[{"calendarDate": "2023-03-01", "v": NaN}]',
    AGG + "UDSFile_v3.json": b"{ not json",
    WELL + "2023_sleepData.json": _j([{"calendarDate": "2023-01-05", "v": 5}]),
})
rv = es.read_values(values_zip, "uds", "v")
check("values of a field: the points by date (several per date, in file order), numbers kept as they are",
      rv["points"] == [["2022-12-31", 20], ["2023-01-05", 10], ["2023-01-05", 30]]
      and isinstance(rv["points"][1][1], int) and rv["supported"] is True and rv["source"] == "zip")
check("the counts: rows, numbers, not numbers (text, NaN), empty or absent, numbers without a date, files, damaged files",
      (rv["rows"], rv["numeric"], rv["other"], rv["missing"], rv["undated"]) == (8, 4, 2, 2, 1)
      and rv["files"] == 3 and rv["unreadable"] == 1 and rv["too_large"] == 0 and rv["stopped"] is False and rv["thinned"] is False)
check("the statistics and the histogram are those of the numbers with a date",
      rv["stats"] == {"count": 3, "min": 10, "max": 30, "mean": 20.0, "median": 20, "zeros": 0}
      and sum(rv["histogram"]["counts"]) == 3 and rv["histogram"]["edges"][0] == 10 and rv["histogram"]["edges"][-1] == 30)
check("only the files of the family are read (the sleepData file with the same field name is not)", 5 not in [p[1] for p in rv["points"]])
check("a field in an object, a float, a zero, a bool (a bool is no number)",
      es.read_values(values_zip, "uds", "nested.x")["points"] == [["2023-01-05", 7]]
      and es.read_values(values_zip, "uds", "f")["points"] == [["2022-12-31", 1.5], ["2023-01-05", 2.5], ["2023-01-05", 0.5]]
      and es.read_values(values_zip, "uds", "z")["stats"]["zeros"] == 2
      and es.read_values(values_zip, "uds", "b")["points"] == [] and es.read_values(values_zip, "uds", "b")["other"] == 2)
none = es.read_values(values_zip, "uds", "does_not_exist")
check("a field that is nowhere: no points, no statistics, every row counted as absent",
      none["points"] == [] and none["stats"] is None and none["histogram"] is None and none["missing"] == none["rows"] == 8)
check("a field that cannot be read as values: supported False, nothing read, nothing returned",
      all(r["supported"] is False and r["files"] == 0 and r["points"] == [] and r["source"] == "not read"
          for r in (es.read_values(values_zip, "uds", "a[].b"), es.read_values(values_zip, "uds", "devices.<id>.x"))))
check("a ZIP and the same export as a folder give the same values (the source apart)",
      {**es.read_values(_make_dir("values_dir", {AGG + "UDSFile_v1.json": _j([{"calendarDate": "2023-01-05", "v": 1}])}), "uds", "v"),
       "source": "zip"} == es.read_values(_make_zip("values_one.zip", {AGG + "UDSFile_v1.json": _j([{"calendarDate": "2023-01-05", "v": 1}])}), "uds", "v"))

many_rows = _make_zip("values_many.zip", {AGG + "UDSFile_m.json": _j(
    [{"calendarDate": f"2023-{1 + i // 28:02d}-{1 + i % 28:02d}", "v": i} for i in range(100)])})
thin = es.read_values(many_rows, "uds", "v", max_points=10)
check("more points than max_points: thinned evenly, the first and the last point stay, at most max_points",
      thin["thinned"] is True and len(thin["points"]) == 10 and thin["points"][0][1] == 0 and thin["points"][-1][1] == 99)
check("the statistics and the histogram use ALL the numbers, not the thinned ones",
      thin["stats"]["count"] == 100 and thin["stats"]["max"] == 99 and sum(thin["histogram"]["counts"]) == 100)
full = es.read_values(many_rows, "uds", "v")
check("up to max_points nothing is thinned; the default limit is MAX_VALUE_POINTS",
      full["thinned"] is False and len(full["points"]) == 100 and es.MAX_VALUE_POINTS == 20000
      and es.read_values(many_rows, "uds", "v", max_points=100)["thinned"] is False
      and len(es.read_values(many_rows, "uds", "v", max_points=1)["points"]) == 1)

try:
    es.read_values(BASE / "does_not_exist.zip", "uds", "v")
    rv_missing = False
except FileNotFoundError as exc:
    rv_missing = "does_not_exist" not in str(exc) and str(BASE) not in str(exc)
check("missing path: FileNotFoundError without the path", rv_missing)
rv_bad = []
for args in (("nope", "v"), ("uds", ""), ("uds", None), ("uds", 5)):
    try:
        es.read_values(values_zip, *args)
        rv_bad.append(args)
    except ValueError as exc:
        if "uds" in str(exc) or str(BASE) in str(exc):
            rv_bad.append(args)
check("an unknown family or an empty field: ValueError, the message names nothing", rv_bad == [])
check("a file that is no ZIP / a damaged ZIP: source unreadable, nothing counted",
      es.read_values(BASE / "plain.txt", "uds", "v")["source"] == "unreadable"
      and es.read_values(BASE / "broken.zip", "uds", "v")["rows"] == 0)
check("should_stop: the read ends at once and says so",
      es.read_values(values_zip, "uds", "v", should_stop=lambda: True)["stopped"] is True
      and es.read_values(values_zip, "uds", "v", should_stop=lambda: True)["points"] == [])
with patch.object(es, "MAX_JSON_BYTES", 50):
    check("a file over the size limit is counted as too large", es.read_values(values_zip, "uds", "v")["too_large"] >= 1)

# the rule of the views: only read_values returns values; the scan, the detail and the reports never do
sentinel_scan = es.scan(values_zip)
sentinel_field = es.scan_field(values_zip, "uds", "sentinel")
sentinel_text = es.format_report(sentinel_scan)
sentinel_files = es.write_report(sentinel_scan, BASE / "log_sentinel")
check("the sentinel is in the values (the test is meaningful) and the field has it",
      [p[1] for p in es.read_values(values_zip, "uds", "sentinel")["points"]] == [SENTINEL])
check("the sentinel (and no part of it) is in none of: the scan result, the field detail, the text report, the report files",
      all("987654" not in text for text in (json.dumps(sentinel_scan), json.dumps(sentinel_field), sentinel_text,
                                            sentinel_files["json"].read_text(encoding="utf-8"),
                                            sentinel_files["text"].read_text(encoding="utf-8"))))

stream_v = io.StringIO()
handler_v = logging.StreamHandler(stream_v)
root_logger.addHandler(handler_v)
root_logger.setLevel(logging.DEBUG)
out_v, err_v = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out_v), contextlib.redirect_stderr(err_v):
        priv_v = es.read_values(zip_path, "activities", "distance")
        priv_w = es.read_values(dir_path, "uds", "totalSteps")
finally:
    root_logger.removeHandler(handler_v)
    root_logger.setLevel(old_level)
check("the values result holds no file name and no e-mail marker (activities, names with the marker)",
      all(SECRET not in json.dumps(r) and "secret.name" not in json.dumps(r) and "example.invalid" not in json.dumps(r)
          for r in (priv_v, priv_w)) and priv_v["points"] and priv_w["points"])
check("nothing is logged, printed or written to stderr while the values are read",
      stream_v.getvalue() == "" and out_v.getvalue() == "" and err_v.getvalue() == "")
check("the result holds only the documented keys",
      set(priv_v) == {"schema", "source", "family", "label", "field", "supported", "stopped", "files", "unreadable",
                      "too_large", "rows", "numeric", "other", "missing", "undated", "thinned", "stats", "histogram", "points"})

# ── 10. read_windows — the four wellness times of each day (the heart-rate day view) ────────────

section("10. read_windows — times of the days, kept apart from the scan")

W1 = {"wellnessStartTimeGmt": "2023-01-04T23:00:00.0", "wellnessStartTimeLocal": "2023-01-05T00:00:00.0",
      "wellnessEndTimeGmt": "2023-01-05T23:00:00.0", "wellnessEndTimeLocal": "2023-01-06T00:00:00.0"}
W2 = {"wellnessStartTimeGmt": "2023-01-05T23:00:00.0", "wellnessStartTimeLocal": "2023-01-06T00:00:00.0"}
windows_entries = {
    AGG + "UDSFile_w1.json": _j([
        {"calendarDate": "2023-01-05", "totalSteps": 1, **W1},
        {"calendarDate": "2023-01-06", **W2, "wellnessEndTimeGmt": 5, "wellnessEndTimeLocal": None},   # only text keys count
        {"calendarDate": "2023-01-07", "totalSteps": 3},                                                  # no window: no entry
        {"wellnessStartTimeGmt": "2023-01-08T00:00:00.0"},                                                # no date: skipped
        {"calendarDate": "2023-02-30", **W1},                                                             # not a day
        "not an object",
    ]),
    AGG + "UDSFile_w2.json": _j([{"calendarDate": "2023-01-05", **{**W1, "wellnessEndTimeLocal": "later"}}]),   # replaces the first
    AGG + "UDSFile_w3.json": b"{ this is not json",
    WELL + "2023-01-01_2023-03-31_123456_sleepData.json": _j([{"calendarDate": "2023-03-01", **W1}]),        # not a UDS file
    f"DI_CONNECT/{SECRET}/UDSFile_x.json": _j([{"calendarDate": "2023-03-02", **W1}]),                        # not in the folder of the family
}
win_zip = _make_zip("windows.zip", windows_entries)
win_dir = _make_dir("windows_dir", windows_entries)
wr = es.read_windows(win_zip)
check("read_windows: the window of every day of the UDS files, text keys only",
      set(wr["windows"]) == {"2023-01-05", "2023-01-06"} and wr["windows"]["2023-01-06"] == W2
      and set(wr["windows"]["2023-01-05"]) == set(es.WINDOW_KEYS))
check("read_windows: a later row of the same day replaces the earlier one",
      wr["windows"]["2023-01-05"]["wellnessEndTimeLocal"] == "later" and wr["windows"]["2023-01-05"]["wellnessStartTimeGmt"] == W1["wellnessStartTimeGmt"])
check("read_windows: counts the UDS files and the one that cannot be read, no other family",
      (wr["source"], wr["files"], wr["unreadable"], wr["too_large"], wr["stopped"]) == ("zip", 3, 1, 0, False))
check("read_windows: a ZIP and the unpacked folder give the same windows", es.read_windows(win_dir)["windows"] == wr["windows"]
      and es.read_windows(win_dir)["source"] == "folder")
check("read_windows: stop before a file, a path that is not there, a ZIP that cannot be opened",
      es.read_windows(win_zip, should_stop=lambda: True)["stopped"] is True and es.read_windows(win_zip, should_stop=lambda: True)["windows"] == {}
      and es.read_windows(_put(BASE / "bad.zip", b"not a zip"))["source"] == "unreadable")
try:
    es.read_windows(BASE / "does_not_exist.zip")
    raised_w = None
except FileNotFoundError as exc:
    raised_w = str(exc)
check("read_windows: a missing path raises FileNotFoundError without the path", raised_w is not None and str(BASE) not in raised_w)
check("read_windows: the result holds only the documented keys, no file name",
      set(wr) == {"source", "stopped", "files", "unreadable", "too_large", "windows"} and SECRET not in json.dumps(wr))
before_w = _snapshot(BASE / "windows_dir")
es.read_windows(win_dir)
check("read_windows only reads: the export is unchanged", _snapshot(BASE / "windows_dir") == before_w)

# ── 11. mutation round v1.7.7 — what Cosmic Ray found in this module ─────────────────────────────

section("11. mutation round v1.7.7 — limits, boundaries, order of files and rows, lines of the report")

import pathlib

check("the limits are what the documentation says (a change is a decision, not an accident)",
      (es.SCHEMA_VERSION, es.MAX_PATHS_PER_FAMILY, es.MAX_DEPTH, es.MAX_FOLDERS, es.FIRST_YEAR, es.LAST_YEAR, es.HISTOGRAM_BINS,
       es.MAX_JSON_BYTES) == (1, 500, 16, 200, 1990, 2100, 30, 64 * 1024 * 1024))


def _scan_uds(name, rows):
    return es.scan(_make_zip(name, {AGG + "UDSFile_m.json": _j(rows)}))


# the limit of fields per family: exactly 500 fit, the 501st is cut, a known field is still counted after the cut
m500 = _scan_uds("m500.zip", [{f"f{i:03d}": 1 for i in range(500)}])
m501 = _scan_uds("m501.zip", [{f"f{i:03d}": 1 for i in range(501)}])
check("500 fields fit and are not 'truncated'; the 501st field is cut and the family says so",
      len(_fam(m500, "uds")["fields"]) == 500 and _fam(m500, "uds")["truncated"] is False
      and len(_fam(m501, "uds")["fields"]) == 500 and _fam(m501, "uds")["truncated"] is True and "f500" not in _fam(m501, "uds")["fields"])
mrows = _scan_uds("mrows.zip", [{f"f{i:03d}": 1 for i in range(500)}, {"zzz_new": 1, "f000": 2}])
check("after the cut a field that is already known is still counted in later rows (the new one before it does not stop the row)",
      _field(mrows, "uds", "f000", "unknown")["filled"] == 2 and "zzz_new" not in _fam(mrows, "uds")["fields"])
check("a family without that many fields is not 'truncated' (the default of the counter)", _fam(_scan_uds("m1.zip", [{"a": 1}]), "uds")["truncated"] is False
      and es._new_acc()["truncated"] is False)


# the depth limit: 16 levels of objects are read to the leaf, the 17th is one filled value at the 16th
def _nest(levels, leaf):
    value = leaf
    for _ in range(levels):
        value = {"a": value}
    return value


p16 = ".".join(["a"] * 16)
d16 = _make_zip("d16.zip", {AGG + "UDSFile_d.json": _j([_nest(16, 0)])})
d17 = _make_zip("d17.zip", {AGG + "UDSFile_d.json": _j([_nest(17, 0)])})
r16, r17 = es.scan(d16), es.scan(d17)
check("depth: 16 levels reach the leaf (a 0 stays a zero); 17 levels count as one filled value at the 16th level",
      list(_fam(r16, "uds")["fields"]) == [p16] and _field(r16, "uds", p16, "unknown") == {"filled": 0, "zero": 1, "empty": 0, "absent": 0}
      and list(_fam(r17, "uds")["fields"]) == [p16] and _field(r17, "uds", p16, "unknown") == {"filled": 1, "zero": 0, "empty": 0, "absent": 0})
check("depth: scan_field starts at depth 0 (the same cut as scan)",
      es.scan_field(d16, "uds", p16)["months"]["unknown"]["zero"] == 1 and es.scan_field(d17, "uds", p16)["months"]["unknown"]["filled"] == 1)
deep_list = 1
for _ in range(3000):
    deep_list = [deep_list]
deep_out = {}
es._flatten(deep_list, "x", deep_out, 0)
check("depth: nested lists are cut at the same level and do not recurse without end", deep_out == {"x" + "[]" * 16: es._FILLED})

# a kept family counts only in its own folder
check("classify: a kept family needs its whole folder (a folder that merely sorts before it is no match)",
      es.classify("DI_CONNECT/DI-Connect-Fitness/x_gear.json").key == "gear" and es.classify("DI_CONNECT/DI-Connect-F/x_gear.json") is None
      and es.classify("DI_CONNECT/DI-Connect-Fitnesz/x_gear.json") is None)

# the limit of folders named in the result
f200 = es.scan(_make_zip("f200.zip", {f"d{i:03d}/f.json": _j([1]) for i in range(200)}))
f201 = es.scan(_make_zip("f201.zip", {f"d{i:03d}/f.json": _j([1]) for i in range(201)}))
check("folders: 200 are listed whole; the 201st is cut and the list says so (unknown files and top folders)",
      len(f200["unknown"]["folders"]) == 200 and f200["unknown"]["folders_truncated"] is False and len(f200["folders"]) == 200
      and len(f201["unknown"]["folders"]) == 200 and f201["unknown"]["folders_truncated"] is True and len(f201["folders"]) == 200
      and f201["unknown"]["files"] == 201)
check("the empty result: nothing unknown, nothing cut",
      es._empty_result("zip")["unknown"] == {"files": 0, "folders": [], "folders_truncated": False})

# dates: the borders of the year range and of the epoch, the shapes of a list
check("year range: 1989 is out, 1990 and 2100 are in, 2101 is out (year, month and day of a date)",
      all(f("1989-12-31") is None and f("2101-01-01") is None for f in (es._year_of, es._month_of, es._date_of))
      and (es._year_of("1990-01-01"), es._year_of("2100-12-31")) == ("1990", "2100")
      and (es._month_of("1990-01-15"), es._month_of("2100-12-15")) == ("1990-01", "2100-12")
      and (es._date_of("1990-01-01"), es._date_of("2100-12-31")) == ("1990-01-01", "2100-12-31"))
check("epoch milliseconds: a value below 1e11 is no date; one just above is 1973, outside of the year range (so the border itself cannot be seen: EQ in the notes)",
      all(f(99_999_999_999) is None and f(100_000_000_001) is None and f(1e11) is None for f in (es._year_of, es._month_of, es._date_of))
      and es._year_of(1_700_000_000_000.0) == "2023" and es._year_of(-1_700_000_000_000) is None)
check("epoch milliseconds: the first and the last millisecond of a year belong to that year (the division is by 1000)",
      es._year_of(1_704_067_200_000) == "2024" and es._year_of(1_704_067_199_999) == "2023"
      and es._month_of(1_704_067_200_000) == "2024-01" and es._month_of(1_704_067_199_999) == "2023-12"
      and es._date_of(1_704_067_200_000) == "2024-01-01" and es._date_of(1_704_067_199_999) == "2023-12-31")
check("a list of numbers: three are enough, two are not, only the first three count",
      (es._year_of([2021, 5, 1]), es._month_of([2021, 5, 1]), es._date_of([2021, 5, 1])) == ("2021", "2021-05", "2021-05-01")
      and all(f([2021, 5]) is None for f in (es._year_of, es._month_of, es._date_of))
      and (es._year_of([2021, 5, 1, "x"]), es._month_of([2021, 5, 1, "x"]), es._date_of([2021, 5, 1, "x"])) == ("2021", "2021-05", "2021-05-01")
      and all(f([2021, 5, "x"]) is None for f in (es._year_of, es._month_of, es._date_of))
      and es._date_of([2021, True, 1]) is None and es._month_of([2021, True, 1]) is None)

# field paths and states
check("a key of 40 characters is a field name, one of 41 is masked", es._segment("a" * 40) == "a" * 40 and es._segment("a" * 41) == "<key>"
      and es._segment("x@y") == "<key>" and es._segment("a.b") == "<key>")
check("a negative number is filled, only 0 and 0.0 are zero",
      es._leaf_state(-5) == es._FILLED and es._leaf_state(-0.5) == es._FILLED and es._leaf_state(0) == es._ZERO and es._leaf_state(0.0) == es._ZERO)
out_put = {}
es._put(out_put, "p", es._FILLED)
es._put(out_put, "p", es._EMPTY)
es._put(out_put, "q", es._EMPTY)
es._put(out_put, "q", es._FILLED)
check("the best state of a field in one row wins, whatever the order (filled then empty stays filled)", out_put == {"p": es._FILLED, "q": es._FILLED})
list_order = _scan_uds("order.zip", [{"l": [{"a": 1}, {"a": None}]}])
check("a list of objects with the value first and the empty one after: the field counts as filled",
      _field(list_order, "uds", "l[].a", "unknown")["filled"] == 1 and _field(list_order, "uds", "l[].a", "unknown")["empty"] == 0)
absent = _scan_uds("absent.zip", [{"calendarDate": "2023-01-01", "x": 1}] + [{"calendarDate": "2023-01-0%d" % d} for d in (2, 3, 4)])
check("absent is the rows without the field (4 rows, 1 with it: 3)", _field(absent, "uds", "x", "2023") == {"filled": 1, "zero": 0, "empty": 0, "absent": 3})


# an unreadable file, a file that is too large, a row that is no object, a row without a date: the next ones are still read
class _SizedReader:
    def __init__(self, size, data=b"[]"):
        self._size, self._data = size, data

    def size(self, name):
        return self._size

    def read(self, name):
        return self._data


check("the size limit: a file of exactly the limit is read, one byte more is too large, an unknown size is read, bad JSON is unreadable",
      es._read_file(_SizedReader(es.MAX_JSON_BYTES), "n") == ("ok", []) and es._read_file(_SizedReader(es.MAX_JSON_BYTES + 1), "n") == ("too_large", None)
      and es._read_file(_SizedReader(None), "n") == ("ok", []) and es._read_file(_SizedReader(5, b"{bad"), "n") == ("unreadable", None))
good_file = _j(["not an object", {"v": 1}, {"calendarDate": "2023-01-05", "v": 7, **W1}])
order_entries = {"A_first/readme.json": b"[1]", AGG + "UDSFile_1_bad.json": b"{ not json",
                 AGG + "UDSFile_2_big.json": b"[]" + b" " * 400, AGG + "UDSFile_3_good.json": good_file}
order_zip = _make_zip("order_files.zip", order_entries)
with patch.object(es, "MAX_JSON_BYTES", len(good_file) + 10):
    o_scan, o_vals = es.scan(order_zip), es.read_values(order_zip, "uds", "v")
    o_win, o_field = es.read_windows(order_zip), es.scan_field(order_zip, "uds", "v")
check("scan: one file too large, one unreadable, one read; the row that is no object is counted",
      (o_scan["files"]["json_total"], o_scan["files"]["json_read"], o_scan["files"]["unreadable"], o_scan["files"]["too_large"],
       o_scan["files"]["unknown_json"]) == (4, 1, 1, 1, 1)
      and (_fam(o_scan, "uds")["files"], _fam(o_scan, "uds")["unreadable"], _fam(o_scan, "uds")["too_large"],
           _fam(o_scan, "uds")["skipped_rows"], _fam(o_scan, "uds")["rows"]) == (3, 1, 1, 1, 2))
check("read_values: the files and rows after an unreadable, a too large file, a row that is no object are still read",
      (o_vals["files"], o_vals["unreadable"], o_vals["too_large"], o_vals["rows"], o_vals["numeric"], o_vals["undated"]) == (3, 1, 1, 2, 2, 1)
      and o_vals["points"] == [["2023-01-05", 7]])
check("read_windows: the same (an unclassified file first, a bad one, a big one, a row that is no object and one without a date)",
      (o_win["files"], o_win["unreadable"], o_win["too_large"]) == (3, 1, 1) and list(o_win["windows"]) == ["2023-01-05"])
check("scan_field: the same", (o_field["files"], o_field["unreadable"], o_field["too_large"], o_field["rows"]) == (3, 1, 1, 2)
      and o_field["months"]["2023-01"]["filled"] == 1 and o_field["months"]["unknown"]["filled"] == 1)

# stop: the walk ends at the first 'stop', it does not ask again for every file that is left
stop_zip = _make_zip("stop_calls.zip", {AGG + f"UDSFile_{c}.json": _j([{"calendarDate": "2023-01-05", "v": 1, **W1}]) for c in "abc"})
for label, call in (("scan", lambda stop: es.scan(stop_zip, should_stop=stop)),
                    ("read_values", lambda stop: es.read_values(stop_zip, "uds", "v", should_stop=stop)),
                    ("scan_field", lambda stop: es.scan_field(stop_zip, "uds", "v", should_stop=stop)),
                    ("read_windows", lambda stop: es.read_windows(stop_zip, should_stop=stop))):
    asked = []
    res = call(lambda: asked.append(1) or len(asked) >= 2)
    check(f"stop: {label} asks twice (the second answer is 'stop') and ends, it does not ask for the third file",
          len(asked) == 2 and (res["stopped"] is True))

# thinning of the points of the values view
thin_zip = _make_zip("thin.zip", {AGG + "UDSFile_t.json": _j([{"calendarDate": "2023-01-%02d" % d, "v": d * 10} for d in range(1, 11)])})
thin5, thin0 = es.read_values(thin_zip, "uds", "v", max_points=5), es.read_values(thin_zip, "uds", "v", max_points=0)
check("thinning: 10 points to at most 5 keep every 2nd one and the last (the step is rounded up)",
      [p[0][-2:] for p in thin5["points"]] == ["01", "03", "05", "07", "10"] and thin5["thinned"] is True and thin5["stats"]["count"] == 10)
check("thinning: a limit of 0 is taken as 1 (one point, the last one), no division by zero",
      thin0["points"] == [["2023-01-10", 100]] and thin0["thinned"] is True)

# statistics and histogram with numbers a wrong operator cannot hit by chance
check("median: odd count (5 and 7), even count (6, with an odd sum), the mean is not rounded, a negative number is no zero",
      es._stats([1, 2, 3, 4, 5])["median"] == 3 and es._stats([1, 2, 3, 4, 5, 6, 7])["median"] == 4
      and es._stats([1, 2, 4, 7, 16, 32])["median"] == 5.5 and es._stats([32, 16, 7, 4, 2, 1])["median"] == 5.5
      and es._stats([1, 2, 4])["mean"] == 7 / 3 and es._stats([-3, 0, 5])["zeros"] == 1)
hist = es._histogram([10, 20, 30])
check("histogram: 30 bins between the smallest and the largest value, each value in its bin, the largest in the last one",
      hist["counts"][0] == 1 and hist["counts"][15] == 1 and hist["counts"][29] == 1 and sum(hist["counts"]) == 3 and len(hist["counts"]) == 30
      and len(hist["edges"]) == 31 and hist["edges"][0] == 10 and hist["edges"][-1] == 30 and abs(hist["edges"][1] - (10 + 20 / 30)) < 1e-9
      and abs(hist["edges"][15] - 20) < 1e-9)
check("histogram: equal values (floats made at run time, two objects) are one bin, not a division by zero",
      es._histogram([float("1000.5"), float("1000.5")]) == {"edges": [1000.5, 1000.5], "counts": [2]})
check("folders: a few unknown folders are not 'truncated'", es.scan(order_zip)["unknown"]["folders_truncated"] is False and len(es.scan(order_zip)["unknown"]["folders"]) == 1)
check("values_supported: a part that would be masked (a mail address, 41 characters) is not readable",
      not es.values_supported("x@y") and not es.values_supported("a." + "b" * 41) and es.values_supported("a." + "b" * 40))
check("share in percent: rounded, 0 for no rows",
      (es._pct(1, 3), es._pct(2, 3), es._pct(3, 7), es._pct(0, 5), es._pct(5, 5), es._pct(1, 2), es._pct(3, 4), es._pct(1, 0)) == (33, 67, 43, 0, 100, 50, 75, 0))

# _opened: a folder that cannot be listed, a ZIP that cannot be read, a ZIP that is closed again after a failure
open_dir = _make_dir("opened_dir", {AGG + "UDSFile_1.json": _j([{"a": 1}])})
with patch.object(pathlib.Path, "rglob", side_effect=OSError("denied")):
    with es._opened(open_dir) as (src_o, names_o, reader_o):
        check("a folder that cannot be listed is 'unreadable' (no error, no names, no reader)", (src_o, names_o, reader_o) == ("unreadable", [], None))


class _BrokenZip:
    closed = []

    def __init__(self, *args, **kwargs):
        pass

    def infolist(self):
        raise RuntimeError("damaged")

    def close(self):
        _BrokenZip.closed.append(1)


with patch.object(es.zipfile, "ZipFile", _BrokenZip):
    with es._opened(order_zip) as (src_z, names_z, reader_z):
        check("a ZIP whose entries cannot be listed is 'unreadable' and is closed again", (src_z, names_z, reader_z) == ("unreadable", [], None)
              and _BrokenZip.closed == [1])
with patch.object(es.zipfile, "ZipFile", side_effect=OSError("cannot open")):
    with es._opened(order_zip) as (src_z, names_z, reader_z):
        check("a ZIP that cannot be opened is 'unreadable' (no error)", (src_z, names_z, reader_z) == ("unreadable", [], None))

# the lines of the text report, one by one
shares = [{"calendarDate": "2023-03-01", "x": v} for v in [5] * 5 + [0] * 3 + [None] * 2] + [{"calendarDate": "2023-03-01"}] * 7 \
    + [{"calendarDate": "2024-03-01", "x": v} for v in [5] * 1 + [0] * 4 + [None] * 6] + [{"calendarDate": "2024-03-01"}] * 2
report_entries = {AGG + "UDSFile_s.json": _j(shares), AGG + "HydrationLogFile_h.json": b"[]",
                  WELL + "2023-01-01_2023-03-31_123456_sleepData.json": _j(["x"]),
                  MET + "TrainingReadinessDTO_1.json": b"{ not json"}
rep = es.format_report(es.scan(_make_zip("report_shares.zip", report_entries)))
rep_lines = rep.split("\n")
check("report: the heading of the field table is exact", "  field (share of all rows, rounded)" + " " * 14 + "filled  zero empty absent" in rep_lines)
check("report: the shares of a field over two years use the sum of ALL its counts (6 / 7 / 8 / 9 of 30)",
      f"    {'x':<48}{20:>5}% {23:>4}% {27:>4}% {30:>5}%" in rep_lines)
check("report: rows per year only for a family that has rows; the line about unreadable files only for a family that has some",
      "  rows per year: 2023: 17, 2024: 13" in rep_lines
      and sum(1 for line in rep_lines if line.startswith("  rows per year")) == 1
      and [line for line in rep_lines if line.startswith("  unreadable files")] ==
      ["  unreadable files 0, too large 0, rows that are not objects 1", "  unreadable files 1, too large 0, rows that are not objects 0"])
big_zip = _make_zip("report_big.zip", {MET + "MetricsMaxMetData_1.json": b"[]" + b" " * 400, MET + "TrainingHistory_1.json": b"[]"})
with patch.object(es, "MAX_JSON_BYTES", 100):
    big_rep = es.format_report(es.scan(big_zip))
check("report: a family with a file that is too large says so alone",
      [line for line in big_rep.split("\n") if line.startswith("  unreadable files")] == ["  unreadable files 0, too large 1, rows that are not objects 0"])
check("report: the note about the cut list of fields, only where it was cut",
      "  (field list cut at 500 paths)" in es.format_report(m501).split("\n") and "(field list cut" not in es.format_report(m500))
check("report: '(list cut)' after the folders only if the list was cut",
      es.format_report(f201).count("(list cut)") == 1 and "(list cut)" not in es.format_report(f200))


def _fit_part(**kw):
    files = {"read": 1, "seen": 2, "duplicates": 0, "damaged": {}, "oversize": 0, "unreadable_entries": 0, "zips_unreadable": 0, "too_deep": 0}
    files.update(kw)
    return {"files": files, "stopped": False, "types": {}}


none_line = [line for line in es._fit_lines(_fit_part()) if line.startswith("not read")]
one_lines = {key: [line for line in es._fit_lines(_fit_part(**{key: 1})) if line.startswith("not read")]
             for key in ("oversize", "unreadable_entries", "zips_unreadable", "too_deep")}
check("report, FIT part: the line 'not read' is there if ANY one of the four counts is not 0, and not if all are 0",
      none_line == [] and all(len(v) == 1 for v in one_lines.values()) and "too large 1," in one_lines["oversize"][0]
      and "nested too deep 1" in one_lines["too_deep"][0])
check("report, FIT part: damaged files by reason",
      any("(crc: 2)" in line for line in es._fit_lines(_fit_part(damaged={"crc": 2}))))

# the report files: a folder that does not exist yet (several levels), the JSON text
rep_dir = BASE / "deep" / "er" / "log"
written = es.write_report(es.scan(_make_zip("report_files.zip", report_entries)), rep_dir)
json_text = written["json"].read_text(encoding="utf-8")
check("write_report creates the folder with its parents; the JSON has one space of indent",
      written["json"].parent == rep_dir and json_text.startswith('{\n "schema": 1,') and json.loads(json_text)["schema"] == 1)

summary()
