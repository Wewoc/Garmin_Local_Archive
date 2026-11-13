#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_export_scan_fit.py — garmin_export_scan_fit
EXPORT-SCAN v1.7.7 — removable (see the removal list in garmin_export_scan.py).

Covers: the year of a FIT file, the counts by type and year (outer ZIP, inner ZIP, folder), the same
content counted once, damaged files by reason, the limits of the walk, stop and progress, and the
privacy rule: the marker that stands for the e-mail address of the account never shows up in any output.

Run from the project folder:
    python tests/test_export_scan_fit.py

All exports are built here from scratch with fit_builder.py — no export of the maintainer is needed.
"""

import contextlib
import io
import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
import fit_builder as fb

section("EXPORT-SCAN v1.7.7 — garmin_export_scan_fit")
import garmin_export_scan_fit as sf

BASE = _TMPDIR / "export_scan_fit_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

SECRET = "secret.name@example.invalid"


def unix(year, month=6, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def fit(ftype, year, serial=7, month=6, day=1):
    return fb.simple_fit(ftype, unix(year, month, day), serial=serial)


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


def _entries():
    """Inner ZIP parts with FIT files of every kind the scan has to handle."""
    good = fit(32, 2019)
    part1 = {
        f"{SECRET}_a1.fit": good,
        f"{SECRET}_a2.fit": fit(32, 2019, serial=8),
        f"{SECRET}_a3.fit": fit(32, 2020),
        f"{SECRET}_dup.fit": good,                                   # the same content again
        f"{SECRET}_sleep.fit": fit(49, 2021),
        f"{SECRET}_act.fit": fit(4, 2019, month=12, day=31),
        "readme.txt": b"hello",
    }
    small = fb.build_fit(fb.file_id(41, 5))                           # a creation time under 0x10000000
    part2 = {
        f"{SECRET}_b1.fit": small,
        f"{SECRET}_b2.fit": fit(32, 2026),
        f"{SECRET}_b3.fit": fb.build_fit(fb.file_id(0xFF, unix(2022) - fb.FIT_EPOCH_OFFSET)),   # type invalid (0xFF)
        f"{SECRET}_bad_not_fit.fit": b"this is not a fit file at all, not even close",
        f"{SECRET}_bad_truncated.fit": fit(32, 2019, serial=9)[:-6],
        f"{SECRET}_bad_crc.fit": fit(32, 2019, serial=10)[:-1] + b"\x00",
    }
    return {
        f"DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_{SECRET}_Part1.zip": _zip_bytes(part1),
        f"DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_{SECRET}_Part2.zip": _zip_bytes(part2),
        f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_loose.fit": fit(68, 2025),
        "DI_CONNECT/DI-Connect-Aggregator/UDSFile_1.json": b"[]",
    }


def _make_zip(name="export.zip"):
    return _put(BASE / name, _zip_bytes(_entries()))


def _make_dir(name="export_dir"):
    root = BASE / name
    for entry, data in _entries().items():
        _put(root / entry, data)
    return root


def _snapshot(root):
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ── 1. the year of a FIT time ────────────────────────────────────────────────

section("1. the year of a FIT file")

e = sf.FIT_EPOCH_OFFSET
check("year: a FIT time of 2019-06-01 gives 2019", sf._year_of(unix(2019) - e) == "2019")
check("year: the last second of 2019 and the first of 2020",
      sf._year_of(int(datetime(2019, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()) - e) == "2019"
      and sf._year_of(int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()) - e) == "2020")
check("year: under 0x10000000 is system time, no date", sf._year_of(5) == "unknown" and sf._year_of(0x0FFFFFFF) == "unknown")
check("year: 0x10000000 is the first date (8.5 years after the FIT epoch: 1998)", sf._year_of(0x10000000) == "1998")
check("year: none, bool, text, float → unknown", all(sf._year_of(v) == "unknown" for v in (None, True, "2019", 1.5e9)))
check("year: an enormous value does not raise", sf._year_of(2 ** 62) == "unknown")
check("year: after 2100 → unknown", sf._year_of(unix(2150) - e) == "unknown")

# ── 2. a scan of an export ───────────────────────────────────────────────────

section("2. counts by type and year")

zip_path = _make_zip()
res = sf.scan_fit(zip_path)
f = res["files"]
check("not stopped, schema 1", res["stopped"] is False and res["schema"] == 1)
check("files: 13 seen (12 different, 1 duplicate)", f["seen"] == 13 and f["duplicates"] == 1)
check("files: 9 read, 3 damaged (not_fit, truncated, crc), one each",
      f["read"] == 9 and f["damaged"] == {"crc": 1, "not_fit": 1, "truncated": 1})
check("walk numbers: 3 ZIPs opened (outer + 2 inner), nothing unreadable, nothing too large",
      f["zips_opened"] == 3 and f["zips_unreadable"] == 0 and f["unreadable_entries"] == 0 and f["oversize"] == 0
      and f["too_deep"] == 0 and f["oversize"] == 0)
check("types: 4, 32, 41, 49, 68 and none (the type 0xFF file), sorted by number, none last",
      list(res["types"]) == ["4", "32", "41", "49", "68", "none"])
check("type 32: 4 files — 2019 twice (the duplicate counted once), 2020, 2026",
      res["types"]["32"] == {"files": 4, "years": {"2019": 2, "2020": 1, "2026": 1}})
check("type 4 and 49 and 68: one each, in the year of their creation time",
      res["types"]["4"]["years"] == {"2019": 1} and res["types"]["49"]["years"] == {"2021": 1}
      and res["types"]["68"]["years"] == {"2025": 1})
check("type 41 has no date (creation time under 0x10000000): year unknown",
      res["types"]["41"] == {"files": 1, "years": {"unknown": 1}})
check("a file without a readable type counts under none, with its year",
      res["types"]["none"] == {"files": 1, "years": {"2022": 1}})
check("years of all types together, sorted, unknown last",
      res["years"] == {"2019": 3, "2020": 1, "2021": 1, "2022": 1, "2025": 1, "2026": 1, "unknown": 1}
      and list(res["years"]) == ["2019", "2020", "2021", "2022", "2025", "2026", "unknown"])
check("the sum of the types is the number of files read", sum(t["files"] for t in res["types"].values()) == f["read"])
check("the result survives a JSON round trip", json.loads(json.dumps(res)) == res)

dir_path = _make_dir()
before = _snapshot(dir_path)
res_dir = sf.scan_fit(dir_path)
check("a folder with the inner ZIPs still packed gives the same result as the ZIP (the folder is no ZIP level)",
      res_dir["files"]["zips_opened"] == 2 and {**res_dir, "files": {**res_dir["files"], "zips_opened": 3}} == res)
check("the export folder was not changed by the scan", _snapshot(dir_path) == before)

loose = BASE / "loose"
for n, data in {"a.fit": fit(32, 2019), "b.fit": fit(32, 2020), "c.fit": fit(49, 2020)}.items():
    _put(loose / n, data)
res_loose = sf.scan_fit(loose)
check("a folder of loose .fit files", res_loose["types"] == {"32": {"files": 2, "years": {"2019": 1, "2020": 1}},
                                                          "49": {"files": 1, "years": {"2020": 1}}})
check("a single .fit file", sf.scan_fit(loose / "a.fit")["files"]["read"] == 1)
check("an export without FIT files: nothing counted, no error",
      sf.scan_fit(_put(BASE / "no_fit.zip", _zip_bytes({"a.json": b"[]"})))["types"] == {})

# ── 3. limits, bad input, stop, progress ─────────────────────────────────────

section("3. limits, bad input, stop, progress")

try:
    sf.scan_fit(BASE / "does_not_exist.zip")
    missing_ok = False
except FileNotFoundError as exc:
    missing_ok = "does_not_exist" not in str(exc) and str(BASE) not in str(exc)
check("missing path: FileNotFoundError without the path in the message", missing_ok)
check("a file that is neither ZIP nor FIT: counted as unreadable, no error",
      sf.scan_fit(_put(BASE / "plain.txt", b"hello"))["files"]["zips_unreadable"] == 1)
check("a damaged ZIP: counted as unreadable, no error",
      sf.scan_fit(_put(BASE / "broken.zip", _zip_bytes(_entries())[:80]))["files"]["zips_unreadable"] == 1)

with patch.object(sf.walker, "MAX_FIT_BYTES", 40):
    small = sf.scan_fit(zip_path)
check("a file over the size limit of the walk is counted as oversize and not read",
      small["files"]["oversize"] >= 1 and small["files"]["read"] < res["files"]["read"])

asked = []


def _stop_after_two():
    asked.append(1)
    return len(asked) > 2


stopped = sf.scan_fit(zip_path, should_stop=_stop_after_two)
check("should_stop: the scan ends early and says so, with what was counted until then",
      stopped["stopped"] is True and stopped["files"]["read"] + sum(stopped["files"]["damaged"].values()) == 2)

calls = []
with patch.object(sf, "PROGRESS_STEP", 3):
    sf.scan_fit(zip_path, progress=calls.append)
check("progress: every PROGRESS_STEP files; the total at the end only if it was not just reported",
      calls == [3, 6, 9, 12])
calls = []
with patch.object(sf, "PROGRESS_STEP", 5):
    sf.scan_fit(zip_path, progress=calls.append)
check("progress: a total that is no multiple of the step is reported once at the end", calls == [5, 10, 12])
check("no should_stop, no progress: nothing needed", sf.scan_fit(zip_path)["stopped"] is False)

# the generator of the walk is closed also when the scan stops early (its temporary files go)
closed = []
real_iter = sf.walker.iter_fit_files


def _spy(path, stats=None):
    gen = real_iter(path, stats)

    class Spy:
        def __iter__(self):
            return self

        def __next__(self):
            return next(gen)

        def close(self):
            closed.append(1)
            gen.close()
    return Spy()


with patch.object(sf.walker, "iter_fit_files", _spy):
    sf.scan_fit(zip_path, should_stop=lambda: True)
    sf.scan_fit(zip_path)
check("the walk is closed after a stopped and after a finished scan", closed == [1, 1])

# ── 4. privacy ────────────────────────────────────────────────────────────────

section("4. privacy — the marker of the e-mail address never shows up")

root_logger = logging.getLogger()
stream = io.StringIO()
handler = logging.StreamHandler(stream)
old_level = root_logger.level
root_logger.addHandler(handler)
root_logger.setLevel(logging.DEBUG)
out, err = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        priv_zip = sf.scan_fit(zip_path)
        priv_dir = sf.scan_fit(dir_path)
        priv_stop = sf.scan_fit(zip_path, should_stop=lambda: True)
finally:
    root_logger.removeHandler(handler)
    root_logger.setLevel(old_level)

check("the marker is in the names of the export (the test is meaningful)",
      any(SECRET in n for n in _entries()) and SECRET.encode() in zip_path.read_bytes())
check("the marker and its parts are in none of the results",
      all(SECRET not in json.dumps(r) and "secret.name" not in json.dumps(r) and "example.invalid" not in json.dumps(r)
          for r in (priv_zip, priv_dir, priv_stop)))
check("nothing is logged, printed or written to stderr during a scan",
      stream.getvalue() == "" and out.getvalue() == "" and err.getvalue() == "")

with patch.object(sf.fit_reader, "parse_fit", side_effect=RuntimeError(f"boom {SECRET}")):
    boom = sf.scan_fit(zip_path)
check("an unexpected error in the reader is counted as 'other', its text is not kept",
      boom["files"]["damaged"] == {"other": 12} and boom["files"]["read"] == 0 and SECRET not in json.dumps(boom))

# ── 5. the index of the monitoring files (the heart-rate day view) ───────────

section("5. index — the monitoring files by creation time, kept out of the result")

import hashlib

index = {}
with_index = sf.scan_fit(zip_path, index=index)
check("the result is the same with and without an index", with_index == sf.scan_fit(zip_path))
expected ={hashlib.sha256(fit(32, 2019)).hexdigest(): unix(2019) - sf.FIT_EPOCH_OFFSET,
            hashlib.sha256(fit(32, 2019, serial=8)).hexdigest(): unix(2019) - sf.FIT_EPOCH_OFFSET,
            hashlib.sha256(fit(32, 2020)).hexdigest(): unix(2020) - sf.FIT_EPOCH_OFFSET,
            hashlib.sha256(fit(32, 2026)).hexdigest(): unix(2026) - sf.FIT_EPOCH_OFFSET}
check("the index holds the digest and the creation time of each different monitoring file, nothing else",
      index == expected and len(index) == 4)
check("no other type, no damaged file, no file with system time instead of a date is in the index",
      all(hashlib.sha256(data).hexdigest() not in index for data in
          (fit(49, 2021), fit(4, 2019, month=12, day=31), fit(68, 2025), fb.build_fit(fb.file_id(41, 5)),
           fit(32, 2019, serial=9)[:-6], fit(32, 2019, serial=10)[:-1] + b"\x00")))
sys_time = fb.build_fit(fb.file_id(32, 5))
sys_zip = _put(BASE / "sys_time.zip", _zip_bytes({"a.fit": sys_time, "b.fit": fit(32, 2021, serial=3)}))
sys_index = {}
sf.scan_fit(sys_zip, index=sys_index)
check("a monitoring file whose creation time is system time (under 0x10000000) is not indexed, but counted",
      list(sys_index.values()) == [unix(2021) - sf.FIT_EPOCH_OFFSET] and sf.scan_fit(sys_zip)["types"]["32"]["files"] == 2)
dir_index = {}
sf.scan_fit(dir_path, index=dir_index)
check("a ZIP and the unpacked folder give the same index", dir_index == index)
check("the index is not in the result and the result holds no digest",
      "index" not in with_index and not any(d in json.dumps(with_index) for d in index))
stop_index = {}
sf.scan_fit(zip_path, should_stop=lambda: True, index=stop_index)
check("a scan stopped before the first file leaves the index empty", stop_index == {})

# ── 6. mutation round v1.7.7 — what Cosmic Ray found in this module ──────────

section("6. mutation round v1.7.7 — progress steps, the border of the year range, stop, counts, the border of system time")

check("the constants are what the documentation says", (sf.PROGRESS_STEP, sf.MONITORING_TYPE, sf.MIN_FIT_DATE, sf.LAST_YEAR) == (250, 32, 0x10000000, 2100))
check("year: 2100 is the last year, 2101 is none", sf._year_of(unix(2100, 12, 31) - e) == "2100" and sf._year_of(unix(2101, 1, 1) - e) == "unknown")


def _many(count, name):
    return _put(BASE / name, _zip_bytes({f"f{i:04d}.fit": fb.simple_fit(32, unix(2020), serial=i + 1) for i in range(count)}))


def _progress_of(path):
    seen = []
    sf.scan_fit(path, progress=seen.append)
    return seen


check("progress: every 250 files and once at the end (520 files: 250, 500, 520)", _progress_of(_many(520, "p520.zip")) == [250, 500, 520])
check("progress: 500 files end with 500 once, not twice", _progress_of(_many(500, "p500.zip")) == [250, 500])
check("progress: one file gives 1; no FIT file gives no progress at all", _progress_of(_many(1, "p1.zip")) == [1] and _progress_of(_many(0, "p0.zip")) == [])
check("progress: 251 files give 250 and 251", _progress_of(_many(251, "p251.zip")) == [250, 251])

real_walk = sf.walker.iter_fit_files
yielded = []


def _count_walk(path, stats=None):
    for item in real_walk(path, stats):
        yielded.append(1)
        yield item


with patch.object(sf.walker, "iter_fit_files", _count_walk):
    sf.scan_fit(_many(6, "stop6.zip"), should_stop=lambda: True)
check("stop: the walk ends at the first 'stop', the other files are not even taken from it", len(yielded) == 1)

timing = []
yielded.clear()
with patch.object(sf.walker, "iter_fit_files", _count_walk):
    sf.scan_fit(_many(520, "timing520.zip"), progress=lambda done: timing.append((done, len(yielded))))
check("progress: the number reported is the number of files taken so far, at the moment of the call", timing == [(250, 250), (500, 500), (520, 520)])

bad = {f"bad{s}.fit": fit(32, 2019, serial=s)[:-1] + b"\x00" for s in (20, 21, 22)}
check("damaged files of one reason are counted one by one (3 wrong CRCs: 3)", sf.scan_fit(_put(BASE / "three_bad.zip", _zip_bytes(bad)))["files"]["damaged"] == {"crc": 3})

edge_index = {}
sf.scan_fit(_put(BASE / "edge.zip", _zip_bytes({"a.fit": fb.build_fit(fb.file_id(32, 0x10000000, 3)), "b.fit": fb.build_fit(fb.file_id(32, 0x0FFFFFFF, 4))})), index=edge_index)
check("index: a creation time of exactly 0x10000000 is a date and is indexed, one second less is system time and is not",
      list(edge_index.values()) == [0x10000000])

summary()
