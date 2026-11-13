#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_export_scan_day.py — garmin_export_scan_day
EXPORT-SCAN v1.7.7 — removable (see the removal list in garmin_export_scan.py).

Covers: which files belong to a day (the lead of 25 hours, the end of the day), prepare(), the heart rate of
a day in local time (offset, clock change), the same result as the modules of the import produce for the day,
duplicate seconds, damaged files, stop, the walk that ends when every candidate is met, the states, and the
privacy rule: no file name, no e-mail marker, nothing logged, the export unchanged.

Run from the project folder:
    python tests/test_export_scan_day.py

All exports are built here from scratch with fit_builder.py — no export of the maintainer is needed.
"""

import contextlib
import hashlib
import io
import json
import logging
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
import fit_builder as fb

section("EXPORT-SCAN v1.7.7 — garmin_export_scan_day")
import garmin_export_scan_day as sd
import garmin_export_scan_fit as sf
import garmin_bulk_normalizer as nz

BASE = _TMPDIR / "export_scan_day_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

SECRET = "secret.name@example.invalid"
AGG = "DI_CONNECT/DI-Connect-Aggregator/"


def utc(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp())


def _iso(unix):
    return datetime.fromtimestamp(unix, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0")


def window(day, off_start=1, off_end=1):
    """The wellness window of a local day: local midnight to local midnight, offsets in hours (UTC + offset = local)."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return {"calendarDate": day,
            "wellnessStartTimeGmt": _iso(int(start.timestamp()) - off_start * 3600), "wellnessStartTimeLocal": _iso(int(start.timestamp())),
            "wellnessEndTimeGmt": _iso(int(end.timestamp()) - off_end * 3600), "wellnessEndTimeLocal": _iso(int(end.timestamp()))}


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


def mon(created, start, count, step=60, bpm0=60, serial=7):
    """A monitoring file created at `created` (unix) with `count` samples from `start`, one every `step` s; the bpm rises by 1 and starts again after 100 (a byte)."""
    return fb.monitoring_fit(created, [(start + i * step, bpm0 + i % 100) for i in range(count)], serial=serial)


# Four local days (UTC+1): 2023-01-05 .. 2023-01-08, [2023-01-04 23:00 UTC, 2023-01-08 23:00 UTC)
DAYS = ["2023-01-05", "2023-01-06", "2023-01-07", "2023-01-08"]
D5_START, D6_START, D7_START = utc(2023, 1, 4, 23), utc(2023, 1, 5, 23), utc(2023, 1, 6, 23)

F_BEFORE = mon(utc(2023, 1, 4, 22, 30), utc(2023, 1, 4, 22, 30), 120, serial=1)      # 22:30 UTC .. 00:29 UTC: touches 2023-01-05
F_EVENING = mon(utc(2023, 1, 5, 20), utc(2023, 1, 5, 20), 240, bpm0=70, serial=2)    # 20:00 .. 23:59 UTC: crosses the local midnight
F_MORNING = mon(utc(2023, 1, 6, 6), utc(2023, 1, 6, 6), 60, bpm0=80, serial=3)       # 06:00 .. 06:59 UTC of 2023-01-06
F_DUP = mon(utc(2023, 1, 6, 6) + 1, utc(2023, 1, 6, 6), 10, bpm0=150, serial=4)      # created 1 s later: same seconds, other values
F_FAR = mon(utc(2023, 1, 20, 6), utc(2023, 1, 20, 6), 30, serial=5)                  # far outside the planned days
F_OTHER_TYPE = fb.simple_fit(49, utc(2023, 1, 6, 7), serial=6)
F_BAD = bytearray(mon(utc(2023, 1, 6, 8), utc(2023, 1, 6, 8), 5, serial=8))
F_BAD[-1] ^= 0xFF                                                                    # a wrong CRC
F_BAD = bytes(F_BAD)


def _entries(extra=None):
    uds = [window("2023-01-04")] + [window(d) for d in DAYS]      # the first window only gives the start of the first day
    entries = {
        AGG + "UDSFile_2023-01-01_2023-03-31.json": json.dumps(uds).encode(),
        f"DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_{SECRET}_Part1.zip": _zip_bytes({
            f"{SECRET}_before.fit": F_BEFORE, f"{SECRET}_evening.fit": F_EVENING, f"{SECRET}_morning.fit": F_MORNING,
            f"{SECRET}_dup.fit": F_DUP, f"{SECRET}_other.fit": F_OTHER_TYPE, f"{SECRET}_bad.fit": F_BAD,
            f"{SECRET}_far.fit": F_FAR}),
    }
    entries.update(extra or {})
    return entries


def _make_zip(name="export.zip", entries=None):
    return _put(BASE / name, _zip_bytes(entries if entries is not None else _entries()))


def _make_dir(name="export_dir", entries=None):
    root = BASE / name
    for entry, data in (entries if entries is not None else _entries()).items():
        _put(root / entry, data)
    return root


def _index(path):
    index = {}
    sf.scan_fit(path, index=index)
    return index


zip_path = _make_zip()
index = _index(zip_path)
prepared = sd.prepare(zip_path, index)

# ── 1. which files belong to a day ───────────────────────────────────────────

section("1. the files of a day — created in [start - 25 h, end)")

check("the lead is 25 hours (a file holds at most 24 h after its creation time, measured, plus one hour)", sd.LEAD_SECONDS == 25 * 3600)
fake = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7}


def _fake_prepared(created_by_name):
    plan = nz.plan_days({d: {k: v for k, v in window(d).items() if k != "calendarDate"} for d in DAYS})
    ordered = sorted((c, name) for name, c in created_by_name.items())
    return {"plan": plan, "ordered": ordered, "days": []}


lead = sd.LEAD_SECONDS
edge = _fake_prepared({"early": D6_START - lead - 1, "first": D6_START - lead, "inside": D6_START + 5,
                       "last": D7_START - 1, "end": D7_START, "late": D7_START + 5})
check("a file created exactly 25 h before the start is a candidate, one second earlier is not",
      "first" in sd.candidates(edge, "2023-01-06") and "early" not in sd.candidates(edge, "2023-01-06"))
check("a file created in the last second of the day is a candidate, one created at the end is not",
      "last" in sd.candidates(edge, "2023-01-06") and "end" not in sd.candidates(edge, "2023-01-06")
      and "late" not in sd.candidates(edge, "2023-01-06"))
check("the candidates are the names in creation order, nothing twice", sd.candidates(edge, "2023-01-06") == ["first", "inside", "last"])
check("a day that is not planned has no candidates", sd.candidates(edge, "2023-02-01") == [] and sd.candidates(edge, "") == [])

# ── 2. prepare ───────────────────────────────────────────────────────────────

section("2. prepare — the plan, the index, the days that have files")

check("the index of the FIT scan holds the monitoring files with a date (5 files: 4 near the days, 1 far; the other type and the bad one are not)",
      len(index) == 5 and hashlib.sha256(F_OTHER_TYPE).hexdigest() not in index and hashlib.sha256(F_BAD).hexdigest() not in index)
check("prepare: the planned days that have at least one candidate file, sorted",
      prepared["days"] == ["2023-01-05", "2023-01-06", "2023-01-07"] and set(prepared["plan"].days) == set(DAYS)
      and prepared["days"] == sorted(prepared["days"]))
check("prepare: the last day has no file near it and is planned, but not offered", "2023-01-08" in prepared["plan"].days
      and "2023-01-08" not in prepared["days"])
check("prepare: the file of 2023-01-20 does not make a day (it is not planned)", "2023-01-20" not in prepared["days"])
check("prepare: no index, an empty index → None, and the walk of the windows is not even started",
      sd.prepare(zip_path, None) is None and sd.prepare(zip_path, {}) is None)
no_uds = _make_zip("no_uds.zip", {k: v for k, v in _entries().items() if "UDSFile" not in k})
check("prepare: an export without UDS windows → None", sd.prepare(no_uds, index) is None)
check("prepare: stopped while the windows are read → None", sd.prepare(zip_path, index, should_stop=lambda: True) is None)
only_far = {hashlib.sha256(F_FAR).hexdigest(): index[hashlib.sha256(F_FAR).hexdigest()]}
check("prepare: only files far from every planned day → None", sd.prepare(zip_path, only_far) is None)
fit_epoch = nz.FIT_EPOCH_OFFSET
at_low = sd.prepare(zip_path, {"x": D5_START - sd.LEAD_SECONDS - fit_epoch})
check("prepare: a file created exactly 25 h before a day makes that day (and only that one) selectable",
      at_low is not None and at_low["days"] == ["2023-01-05"])
check("prepare: a file created one second earlier belongs to no day", sd.prepare(zip_path, {"x": D5_START - sd.LEAD_SECONDS - 1 - fit_epoch}) is None)
last_end = utc(2023, 1, 8, 23)                                          # the end of the last planned day
check("prepare: a file created exactly at the end of the last day belongs to no day, one second before it does",
      sd.prepare(zip_path, {"x": last_end - fit_epoch}) is None and sd.prepare(zip_path, {"x": last_end - 1 - fit_epoch})["days"] == ["2023-01-08"])

# ── 3. the heart rate of a day ───────────────────────────────────────────────

section("3. read_day — samples in local time")

d5 = sd.read_day(zip_path, prepared, "2023-01-05")
check("the day 2023-01-05: state ok, the documented keys, the family and field of the values view",
      d5["state"] == "ok" and d5["family"] == "fit_monitoring" and d5["field"] == "heartRate" and d5["supported"] is True
      and set(d5) == {"schema", "day", "state", "family", "label", "field", "supported", "stopped", "files", "read", "damaged",
                      "sources", "offset_hours", "dst_transition", "duplicates_same", "duplicates_conflict", "stats",
                      "histogram", "points", "thinned"})
# 2023-01-05 local = [2023-01-04 23:00 UTC, 2023-01-05 23:00 UTC)
check("the samples of the day: 90 of F_BEFORE (from 23:00 UTC) and 180 of F_EVENING (until 22:59 UTC), before and after the UTC midnight",
      len(d5["points"]) == 90 + 180)
first, last = d5["points"][0], d5["points"][-1]
check("the first sample is at 00:00:00 local (23:00 UTC + 1 h), the bpm is that of the 31st sample of F_BEFORE",
      first == ["2023-01-05 00:00:00", 60 + 30])
check("the times are local (UTC + 1 h) and rise", [p[0] for p in d5["points"]] == sorted(p[0] for p in d5["points"])
      and last[0].startswith("2023-01-05 "))
check("offset and clock change of the day", d5["offset_hours"] == 1.0 and d5["dst_transition"] is False)
check("sources: both files put samples on the day", d5["sources"] == 2)
check("the files counted: 2 candidates read, none damaged", (d5["files"], d5["read"], d5["damaged"]) == (2, 2, 0))
check("statistics and histogram cover the same numbers as the points",
      d5["stats"]["count"] == len(d5["points"]) and sum(d5["histogram"]["counts"]) == len(d5["points"])
      and d5["stats"]["min"] == min(p[1] for p in d5["points"]) and d5["stats"]["max"] == max(p[1] for p in d5["points"]))
check("thinned is always False (a day has about 1,200 samples)", d5["thinned"] is False)

d6 = sd.read_day(zip_path, prepared, "2023-01-06")
# local midnight 2023-01-06 = 2023-01-05 23:00 UTC; F_EVENING's last hour (23:00..23:59 UTC) lies on this day
check("a sample after the local midnight belongs to the next day (F_EVENING 23:00 UTC is 00:00 local of 2023-01-06)",
      d6["points"][0] == ["2023-01-06 00:00:00", 70 + 180 % 100] and len(d6["points"]) == 60 + 60)
check("the day 2023-01-06: the three files that put samples on it are counted as sources", d6["sources"] == 3)
check("the file with the wrong CRC is not in the index of the FIT scan, so no day has a damaged candidate", d6["damaged"] == 0 and d5["damaged"] == 0)

# ── 4. duplicates ────────────────────────────────────────────────────────────

section("4. duplicate seconds — the file created first wins, as in the import")

morning = {p[0]: p[1] for p in d6["points"] if p[0].startswith("2023-01-06 07:")}
check("the ten seconds that two files hold take the value of the file created first (80.., not 150..)",
      morning["2023-01-06 07:00:00"] == 80 and morning["2023-01-06 07:09:00"] == 89)
check("the duplicates are counted: 10 with another value, none with the same value", (d6["duplicates_conflict"], d6["duplicates_same"]) == (10, 0))

# ── 5. the same as the import ────────────────────────────────────────────────

section("5. the same result as the modules of the import give for the day")

collector = nz.SampleCollector(prepared["plan"])
import garmin_bulk_export_scanner as walker
import garmin_bulk_fit_reader as reader
for digest, data in walker.iter_fit_files(zip_path):
    try:
        fit_file = reader.parse_fit(data, wanted=(55,))
    except reader.FitFormatError:
        continue
    if fit_file.file_type == 32:
        collector.add_file(digest, fit_file.time_created, fit_file.messages.get(55, []))
full = {d.date: d for d in collector.iter_days()}
same_all = True
for day in ("2023-01-05", "2023-01-06"):
    got, want = sd.read_day(zip_path, prepared, day), full[day]
    same_all = same_all and ([p[1] for p in got["points"]] == [v[1] for v in want.values] and len(got["points"]) == len(want.values)
                             and got["duplicates_same"] == want.duplicates_same and got["duplicates_conflict"] == want.duplicates_conflict
                             and got["sources"] == len(want.source_files))
check("bpm, number of samples, duplicates and sources equal a full run of SampleCollector over every file", same_all)
check("a ZIP and the unpacked folder give the same day", sd.read_day(_make_dir(), prepared, "2023-01-06") == d6)

# ── 6. clock change ──────────────────────────────────────────────────────────

section("6. a day that crosses a clock change")

# 2023-03-26: UTC+1 at the start, UTC+2 at the end (a 23 h day); the day before ends with +1, the day after starts with +2
dst_entries = {
    AGG + "UDSFile_dst.json": json.dumps([window("2023-03-25", 1, 1), window("2023-03-26", 1, 2), window("2023-03-27", 2, 2)]).encode(),
    "DI_CONNECT/x/dst.zip": _zip_bytes({"a.fit": mon(utc(2023, 3, 26), utc(2023, 3, 26, 0, 30), 30, serial=11)}),
}
dst_zip = _make_zip("dst.zip", dst_entries)
dst_prepared = sd.prepare(dst_zip, _index(dst_zip))
dst = sd.read_day(dst_zip, dst_prepared, "2023-03-26")
check("the day is flagged and shows the offset of its start (UTC + 1 h): 00:30 UTC is 01:30",
      dst["state"] == "ok" and dst["dst_transition"] is True and dst["offset_hours"] == 1.0 and dst["points"][0][0] == "2023-03-26 01:30:00")
check("the day after has the offset of its start (+2) and is not flagged",
      sd.read_day(dst_zip, dst_prepared, "2023-03-27")["dst_transition"] is False and sd.read_day(dst_zip, dst_prepared, "2023-03-27")["offset_hours"] == 2.0)

# ── 7. states ────────────────────────────────────────────────────────────────

section("7. states — nothing is guessed")

calls = []
real_walk = walker.iter_fit_files


def _count_walk(path, stats=None):
    calls.append(1)
    return real_walk(path, stats)


with patch.object(sd.walker, "iter_fit_files", _count_walk):
    unplanned = [sd.read_day(zip_path, prepared, d) for d in ("2023-02-01", "", None, 5, "2023-01-5")]
check("a day whose boundaries are not known is 'unplanned' (also a bad value) and the export is not even walked",
      [r["state"] for r in unplanned] == ["unplanned"] * 5 and calls == [] and all(r["points"] == [] and r["stats"] is None for r in unplanned))
check("the day of such a result is the text asked for, an empty text for a bad value",
      [r["day"] for r in unplanned] == ["2023-02-01", "", "", "", "2023-01-5"])
none_files = sd.read_day(zip_path, prepared, "2023-01-08")
check("a planned day without a file near it is 'no_files', with its offset", none_files["state"] == "no_files"
      and none_files["files"] == 0 and none_files["points"] == [] and none_files["offset_hours"] == 1.0)
# a candidate whose samples all lie before the day
ns_entries = {AGG + "UDSFile_ns.json": json.dumps([window("2023-01-04")] + [window(d) for d in DAYS[:2]]).encode(),
              "DI_CONNECT/x/ns.zip": _zip_bytes({"a.fit": mon(utc(2023, 1, 4, 21), utc(2023, 1, 4, 21), 30, serial=12)})}
ns_zip = _make_zip("no_samples.zip", ns_entries)
ns_prepared = sd.prepare(ns_zip, _index(ns_zip))
ns = sd.read_day(ns_zip, ns_prepared, "2023-01-05")
check("a candidate that holds no sample for the day gives 'no_samples'", ns["state"] == "no_samples" and ns["files"] == 1
      and ns["read"] == 1 and ns["points"] == [] and ns["stats"] is None and ns["sources"] == 0)

# ── 8. damaged files, stop, the walk ─────────────────────────────────────────

section("8. damaged files, stop, and a walk that ends when every candidate is met")

bad_index = dict(index)
bad_index[hashlib.sha256(F_BAD).hexdigest()] = utc(2023, 1, 6, 8) - nz.FIT_EPOCH_OFFSET
bad_prepared = sd.prepare(zip_path, bad_index)
with_bad = sd.read_day(zip_path, bad_prepared, "2023-01-06")
check("a candidate that cannot be read is counted as damaged, the others are used",
      with_bad["damaged"] == 1 and with_bad["read"] == d6["files"] and with_bad["points"] == d6["points"])
with patch.object(sd.fit_reader, "parse_fit", side_effect=RuntimeError(f"boom {SECRET}")):
    boom = sd.read_day(zip_path, prepared, "2023-01-06")
check("an error in the reader is counted, its text is not kept, and no sample is shown",
      boom["damaged"] == d6["files"] and boom["read"] == 0 and boom["state"] == "no_samples" and SECRET not in json.dumps(boom))
stopped = sd.read_day(zip_path, prepared, "2023-01-06", should_stop=lambda: True)
check("a read stopped before the first file gives 'stopped' and shows nothing", stopped["state"] == "stopped" and stopped["stopped"] is True
      and stopped["points"] == [] and stopped["stats"] is None)
seen = iter([False, True])
stopped_later = sd.read_day(zip_path, prepared, "2023-01-06", should_stop=lambda: next(seen, True))
check("a read stopped after the first file is stopped as well (the samples of one file are not shown as the day)",
      stopped_later["state"] == "stopped" and stopped_later["points"] == [])

yielded, closed = [], []


def _spy_walk(path, stats=None):
    inner = real_walk(path, stats)

    def gen():
        try:
            for item in inner:
                yielded.append(1)
                yield item
        finally:
            closed.append(1)
            inner.close()
    return gen()


# a single-file day: the candidates are met after some of the files, not all
with patch.object(sd.walker, "iter_fit_files", _spy_walk):
    sd.read_day(zip_path, prepared, "2023-01-07")
check("the walk is closed after a read", closed == [1])
yielded.clear()
closed.clear()
with patch.object(sd.walker, "iter_fit_files", _spy_walk):
    sd.read_day(zip_path, prepared, "2023-01-05")                       # F_BEFORE and F_EVENING
all_files = sum(1 for _ in real_walk(zip_path))
check("the walk ends as soon as every candidate is met: fewer files are walked than the export holds",
      0 < len(yielded) < all_files and closed == [1])
try:
    sd.read_day(BASE / "does_not_exist.zip", prepared, "2023-01-06")
    raised = None
except FileNotFoundError as exc:
    raised = str(exc)
check("a path that is not there: FileNotFoundError without the path", raised is not None and str(BASE) not in raised)

# ── 9. privacy ───────────────────────────────────────────────────────────────

section("9. privacy — no file name, nothing logged, the export unchanged")

dir_path = _make_dir("priv_dir")
before = _snapshot(dir_path)
root_logger = logging.getLogger()
stream = io.StringIO()
handler = logging.StreamHandler(stream)
old_level = root_logger.level
root_logger.addHandler(handler)
root_logger.setLevel(logging.DEBUG)
out, err = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        priv_prepared = sd.prepare(dir_path, _index(dir_path))
        priv = [sd.read_day(dir_path, priv_prepared, d) for d in ("2023-01-05", "2023-01-06", "2023-01-08", "2023-02-01")]
finally:
    root_logger.removeHandler(handler)
    root_logger.setLevel(old_level)
check("the marker is in the names of the export (the test is meaningful)",
      any(SECRET in n for n in _entries()) and SECRET.encode() in zip_path.read_bytes())
check("no result holds the marker or its parts, and the prepared plan holds no name either",
      all(SECRET not in json.dumps(r) and "secret.name" not in json.dumps(r) and "example.invalid" not in json.dumps(r) for r in priv)
      and SECRET not in json.dumps({k: v for k, v in priv_prepared.items() if k != "plan"}) and priv[0]["points"])
check("nothing is logged, printed or written to stderr", stream.getvalue() == "" and out.getvalue() == "" and err.getvalue() == "")
check("reading a day only reads: the export is unchanged", _snapshot(dir_path) == before)

# ── 10. mutation round v1.7.7 — what Cosmic Ray found in this module ─────────

section("10. mutation round v1.7.7 — schema, defaults of a result, a file below the range, the day of the samples, stop")

check("the schema of the result is 1", sd.SCHEMA_VERSION == 1 and d5["schema"] == 1)
two = sd.prepare(zip_path, {"x": D5_START - sd.LEAD_SECONDS - 1000 - fit_epoch, "y": D5_START - sd.LEAD_SECONDS - fit_epoch})
check("prepare: a file below the range does not hide the one after it (two files, the first too early)", two is not None and two["days"] == ["2023-01-05"])
expected_empty = {"schema": 1, "day": "2023-02-01", "state": "unplanned", "family": "fit_monitoring", "label": "FIT monitoring",
                  "field": "heartRate", "supported": True, "stopped": False, "files": 0, "read": 0, "damaged": 0, "sources": 0,
                  "offset_hours": None, "dst_transition": False, "duplicates_same": 0, "duplicates_conflict": 0, "stats": None,
                  "histogram": None, "points": [], "thinned": False}
check("a day that is not planned: the whole result, every default", sd.read_day(zip_path, prepared, "2023-02-01") == expected_empty)
check("a planned day without a file: the same defaults, with the offset of the day",
      sd.read_day(zip_path, prepared, "2023-01-08") == {**expected_empty, "day": "2023-01-08", "state": "no_files", "offset_hours": 1.0})

yielded_d, closed_d = [], []


def _count_walk_d(path, stats=None):
    for item in real_walk(path, stats):
        yielded_d.append(1)
        yield item


with patch.object(sd.walker, "iter_fit_files", _count_walk_d):
    sd.read_day(zip_path, prepared, "2023-01-06", should_stop=lambda: True)
check("stop: the walk ends at the first 'stop', no other file is taken from it", len(yielded_d) == 1)

later_entries = {AGG + "UDSFile_l.json": json.dumps([window("2023-01-04")] + [window(d) for d in DAYS]).encode(),
                 "DI_CONNECT/x/later.zip": _zip_bytes({"a.fit": mon(utc(2023, 1, 4, 23, 30), utc(2023, 1, 6, 10), 10, serial=13)})}
later_zip = _make_zip("later.zip", later_entries)
later = sd.prepare(later_zip, _index(later_zip))
check("the samples of the day itself: a candidate with samples only on a LATER day gives 'no_samples' for the earlier day, not the later day's samples",
      sd.read_day(later_zip, later, "2023-01-05")["state"] == "no_samples" and sd.read_day(later_zip, later, "2023-01-06")["state"] == "ok")

summary()
