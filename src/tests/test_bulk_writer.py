#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_writer.py — garmin_bulk_writer (v1.7.6)

Run from the project folder:
    python tests/test_bulk_writer.py

Sole owner of garmin_data/bulk/raw/ (one JSON file per day) and bulk/source/
(the unchanged export files, named by their SHA-256). Everything runs in an
isolated temp folder with synthetic days; shared setup lives in gla_testenv.py.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

section("B4. garmin_bulk_writer (v1.7.6)")
import garmin_bulk_normalizer as nz
import garmin_bulk_writer as bw


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()


H1, H2, H3 = _h("file one"), _h("file two"), _h("file three")


def _day(date="2024-02-03", hashes=(H1,), values=None, offsets=(1.0, 1.0), dst=False, source="prev_day_end", same=0, conflict=0):
    values = values if values is not None else [[1706950800000, 61], [1706950860000, 62], [1706950920000, 200]]
    plan = nz.DayPlan(date, 1706914800, 1707001200, offsets[0], offsets[1], dst, source)
    return plan, nz.DaySamples(date, values, sorted(hashes), same, conflict)


def _tree(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


with _isolated_log_env("bulk_writer") as base:
    day_file = cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json"

    # ── A new day ──────────────────────────────────────────────────────────────
    plan, samples = _day(same=2, conflict=1)
    check("a new day is written", bw.write_day(plan, samples, imported_at="2026-10-17T13:30:00") == bw.WRITTEN and day_file.exists())
    text = day_file.read_text(encoding="utf-8")
    doc = json.loads(text)
    check("the file name is the configured prefix + date in bulk/raw/", day_file.name == f"{cfg.BULK_FILE_PREFIX}2024-02-03.json")
    check("head: date, schema version, generator, origin, import time",
          (doc["date"], doc["schema_version"], doc["generated_by"], doc["origin"], doc["imported_at"])
          == ("2024-02-03", bw.BULK_SCHEMA_VERSION, "garmin_bulk_writer", "gdpr_export", "2026-10-17T13:30:00"))
    check("head: offsets at the start and at the end of the day, transition flag, source of the offset",
          (doc["utc_offset_hours"], doc["utc_offset_end_hours"], doc["dst_transition"], doc["offset_source"]) == (1.0, 1.0, False, "prev_day_end"))
    check("head: the files of the day (full hashes) and the duplicate counters",
          doc["source_files"] == [H1] and doc["duplicates"] == {"same": 2, "conflict": 1})
    check("the heart rate is in sections.intraday.heart_rate with count and [ms, bpm] pairs",
          doc["sections"] == {"intraday": {"heart_rate": {"count": 3, "values": samples.values}}})
    check("the JSON is compact (no line breaks, no spaces after separators)", "\n" not in text and ", " not in text and ": " not in text)
    check("schema version is 1", bw.BULK_SCHEMA_VERSION == 1)
    check("_load_day returns exactly what is in the file", bw._load_day("2024-02-03")[1] == doc)
    check("_load_day of a missing day gives no document", bw._load_day("2024-02-04")[1] is None)
    check("no temporary file is left behind", not list(cfg.BULK_RAW_DIR.glob("*.tmp")))

    # ── imported_at default ────────────────────────────────────────────────────
    plan_b, samples_b = _day(date="2024-02-04")
    bw.write_day(plan_b, samples_b)
    stamp = bw._load_day("2024-02-04")[1]["imported_at"]
    check("imported_at defaults to the local time without time zone, to the second",
          len(stamp) == 19 and stamp[10] == "T" and "+" not in stamp and "Z" not in stamp)

    # ── Same day again ─────────────────────────────────────────────────────────
    before = _tree(cfg.BULK_RAW_DIR)
    check("the same day again is unchanged", bw.write_day(plan, samples, imported_at="2099-01-01T00:00:00") == bw.UNCHANGED)
    check("unchanged means: not a byte rewritten (also not the import time)", _tree(cfg.BULK_RAW_DIR) == before)
    check("day_status: unchanged", bw.day_status("2024-02-03", [H1]) == "unchanged")
    check("day_status: a day that does not exist yet is new", bw.day_status("2024-03-03", [H1]) == "new")

    # ── Never shrink ───────────────────────────────────────────────────────────
    plan2, samples2 = _day(hashes=(H1, H2), values=[[1706950800000, 61], [1706950860000, 62], [1706950920000, 200], [1706950980000, 70]])
    check("day_status: more files than stored is an update", bw.day_status("2024-02-03", [H1, H2]) == "update")
    check("more files: the day is replaced", bw.write_day(plan2, samples2, imported_at="2026-10-18T09:00:00") == bw.WRITTEN)
    check("... and now holds both files and four values",
          bw._load_day("2024-02-03")[1]["source_files"] == sorted([H1, H2]) and bw._load_day("2024-02-03")[1]["sections"]["intraday"]["heart_rate"]["count"] == 4)
    kept_state = _tree(cfg.BULK_RAW_DIR)
    check("day_status: fewer files than stored is smaller", bw.day_status("2024-02-03", [H1]) == "smaller")
    check("fewer files (a partial import) never replaces a fuller day", bw.write_day(plan, samples) == bw.KEPT)
    check("... and the file stays as it was", _tree(cfg.BULK_RAW_DIR) == kept_state)
    other_plan, other_samples = _day(hashes=(H1, H3))
    check("a different set that is neither smaller nor larger (H1+H3 against H1+H2) is kept as well",
          bw.day_status("2024-02-03", [H1, H3]) == "smaller" and bw.write_day(other_plan, other_samples) == bw.KEPT
          and _tree(cfg.BULK_RAW_DIR) == kept_state)

    # ── Schema version ─────────────────────────────────────────────────────────
    old = dict(bw._load_day("2024-02-03")[1])
    old["schema_version"] = 0
    day_file.write_text(json.dumps(old), encoding="utf-8")
    check("day_status: same files but an older schema is an update", bw.day_status("2024-02-03", [H1, H2]) == "update")
    check("same files, older schema: rewritten with the current schema", bw.write_day(plan2, samples2) == bw.WRITTEN
          and bw._load_day("2024-02-03")[1]["schema_version"] == bw.BULK_SCHEMA_VERSION)
    newer = dict(bw._load_day("2024-02-03")[1])
    newer["schema_version"] = 99
    day_file.write_text(json.dumps(newer), encoding="utf-8")
    state_newer = _tree(cfg.BULK_RAW_DIR)
    check("a day written by a newer version is not overwritten", bw.day_status("2024-02-03", [H1, H2]) == "newer"
          and bw.write_day(plan2, samples2) == bw.KEPT and _tree(cfg.BULK_RAW_DIR) == state_newer)

    # ── Damaged files ──────────────────────────────────────────────────────────
    for label, content in (("garbage", "this is not json {"), ("empty", ""), ("a list", "[1, 2]"),
                           ("without source_files", json.dumps({"schema_version": 1})),
                           ("source_files not a list", json.dumps({"schema_version": 1, "source_files": "x"}))):
        day_file.write_text(content, encoding="utf-8")
        check(f"a damaged day file ({label}) counts as new and is overwritten",
              bw.day_status("2024-02-03", [H1]) == "new" and bw.write_day(plan, samples) == bw.WRITTEN
              and bw._load_day("2024-02-03")[1]["source_files"] == [H1])

    # ── Atomic, durable ────────────────────────────────────────────────────────
    plan_c, samples_c = _day(date="2024-02-05")
    synced = []
    real_fsync = os.fsync

    def _spy(fd):
        synced.append(fd)
        return real_fsync(fd)

    with patch.object(bw.os, "fsync", _spy):
        check("a day file is flushed to disk (fsync on the write handle)", bw.write_day(plan_c, samples_c) == bw.WRITTEN and len(synced) == 1)

    good = bw._load_day("2024-02-03")[1]
    good_bytes = day_file.read_bytes()
    plan_d, samples_d = _day(hashes=(H1, H2, H3))
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        check("a failing replace returns failed", bw.write_day(plan_d, samples_d) == bw.FAILED)
    check("... the old day is untouched and no temporary file is left", day_file.read_bytes() == good_bytes and not list(cfg.BULK_RAW_DIR.glob("*.tmp")))
    plan_e, samples_e = _day(date="2024-02-06")
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        check("a failing replace for a new day returns failed", bw.write_day(plan_e, samples_e) == bw.FAILED)
    check("... and leaves neither a day nor a temporary file", not (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-06.json").exists()
          and not list(cfg.BULK_RAW_DIR.glob("*.tmp")))
    check("a date that is not a date is refused and writes nothing",
          bw.write_day(*_day(date="../../x")) == bw.FAILED and bw.write_day(*_day(date="2024-2-3")) == bw.FAILED
          and bw._load_day("../x")[1] is None and bw.day_status("nonsense", [H1]) == "new")
    check("dates that look like dates but are none (month 13, February 30) are refused",
          bw.write_day(*_day(date="2024-13-01")) == bw.FAILED and bw.write_day(*_day(date="2024-02-30")) == bw.FAILED
          and bw._load_day("2024-02-30")[1] is None)
    pu, su = _day(date="2024-02-13")
    check("source files are stored sorted whatever order they come in",
          bw.write_day(pu, nz.DaySamples("2024-02-13", su.values, [H3, H1, H2], 0, 0)) == bw.WRITTEN
          and bw._load_day("2024-02-13")[1]["source_files"] == sorted([H1, H2, H3]))
    pt, st = _day(date="2024-03-31", offsets=(1.0, 2.0), dst=True, source="neighbours")
    bw.write_day(pt, st)
    tday = bw._load_day("2024-03-31")[1]
    check("a transition day keeps both offsets, the flag and the source of the offset",
          (tday["utc_offset_hours"], tday["utc_offset_end_hours"], tday["dst_transition"], tday["offset_source"]) == (1.0, 2.0, True, "neighbours"))
    p7, s7 = _day(date="2024-02-07")
    for label, files in (("not a string", [H1, 5]), ("not a hash", [H1, "x" * 10]), ("upper case", [H1.upper()]), ("empty", []),
                         ("not a list", "abc"), ("a short hex string", [H1, H1[:40]]), ("a hash with one character too many", [H1 + "0"])):
        check(f"a day whose source files are {label} is refused and writes nothing",
              bw.write_day(p7, nz.DaySamples("2024-02-07", s7.values, files, 0, 0)) == bw.FAILED
              and not (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-07.json").exists())
    check("values that are not [ms, bpm] pairs of integers are refused",
          all(bw.write_day(p7, nz.DaySamples("2024-02-07", v, [H1], 0, 0)) == bw.FAILED
              for v in ([[1, 2, 3]], [["a", 2]], [[1.5, 2]], [[1, 300]], "x", [[1, 0]], [[True, 61]], [[5, True]], [[0, 61]])))
    check("values that are not strictly ascending in time are refused (also two at the same time)",
          all(bw.write_day(p7, nz.DaySamples("2024-02-07", v, [H1], 0, 0)) == bw.FAILED
              for v in ([[2000, 61], [1000, 62]], [[5000, 61], [5000, 62]])))
    check("a day with no values at all is refused (the importer writes only days that have samples)",
          bw.write_day(p7, nz.DaySamples("2024-02-07", [], [H1], 0, 0)) == bw.FAILED)
    check("the date inside the samples must be the date of the plan",
          bw.write_day(p7, nz.DaySamples("2024-02-09", s7.values, [H1], 0, 0)) == bw.FAILED)

    # ── A short lock on the new file (virus scanner, indexer) must not fail the import ──
    plan_f, samples_f = _day(date="2024-02-10")
    calls = []
    real_replace = os.replace

    def _busy_twice(src, dst):
        calls.append((src, dst))
        if len(calls) <= 2:
            raise PermissionError(13, "sharing violation")
        return real_replace(src, dst)

    with patch.object(bw.os, "replace", _busy_twice), patch.object(bw.time, "sleep") as slept:
        check("a day: two sharing violations in a row are retried and the day is written",
              bw.write_day(plan_f, samples_f) == bw.WRITTEN and len(calls) == 3 and slept.call_count == 2
              and bw._load_day("2024-02-10")[1] is not None)
    calls.clear()
    blob = b"original that is busy for a moment"
    with patch.object(bw.os, "replace", _busy_twice), patch.object(bw.time, "sleep"):
        check("an original: two sharing violations in a row are retried and the original is written",
              bw.store_original(hashlib.sha256(blob).hexdigest(), blob) == bw.WRITTEN and len(calls) == 3)
    always = []

    def _always_busy(src, dst):
        always.append(1)
        raise PermissionError(13, "sharing violation")

    with patch.object(bw.os, "replace", _always_busy), patch.object(bw.time, "sleep") as slept:
        check("a lock that does not go away: failed after five attempts, with pauses in between",
              bw.write_day(*_day(date="2024-02-11")) == bw.FAILED and len(always) == 5 and slept.call_count == 4)
    check("... and no temporary file or day is left", not list(cfg.BULK_RAW_DIR.glob("*.tmp"))
          and not (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-11.json").exists())
    always.clear()
    with patch.object(bw.os, "replace", _always_busy), patch.object(bw.time, "sleep"):
        blob2 = b"original that stays busy"
        check("an original under a lasting lock: failed after five attempts, no temporary file left",
              bw.store_original(hashlib.sha256(blob2).hexdigest(), blob2) == bw.FAILED and len(always) == 5
              and not list(cfg.BULK_SOURCE_DIR.rglob("*.tmp")))
    other_errors = []

    def _full(src, dst):
        other_errors.append(1)
        raise OSError(28, "no space left")

    with patch.object(bw.os, "replace", _full), patch.object(bw.time, "sleep") as slept:
        check("other errors (disk full) are not retried", bw.write_day(*_day(date="2024-02-12")) == bw.FAILED
              and len(other_errors) == 1 and slept.call_count == 0)

    # ── The originals ──────────────────────────────────────────────────────────
    data = b"\x0e\x10FIT original bytes " + bytes(range(200))
    digest = hashlib.sha256(data).hexdigest()
    target = cfg.BULK_SOURCE_DIR / digest[:2] / f"{digest}.fit"
    synced.clear()
    with patch.object(bw.os, "fsync", _spy):
        check("an original is stored in source/<first two characters>/<hash>.fit",
              bw.store_original(digest, data) == bw.WRITTEN and target.read_bytes() == data)
    check("originals are not fsynced one by one (they can be made again from the export)", synced == [])
    stat1 = target.stat().st_mtime_ns
    check("the same original again is present and not rewritten", bw.store_original(digest, data) == bw.PRESENT and target.stat().st_mtime_ns == stat1)
    target.write_bytes(data[:10])
    check("an original with the wrong size is replaced", bw.store_original(digest, data) == bw.WRITTEN and target.read_bytes() == data)
    check("no temporary file is left in the originals", not list(cfg.BULK_SOURCE_DIR.rglob("*.tmp")))
    check("an empty original works (its hash is the hash of nothing)",
          bw.store_original(hashlib.sha256(b"").hexdigest(), b"") == bw.WRITTEN)
    check("original_present: yes for a stored original of the same size",
          bw.original_present(digest, len(data)) is True)
    check("original_present: no for another size, and no for an original that is not stored",
          bw.original_present(digest, len(data) + 1) is False and bw.original_present(_h("not stored"), 3) is False)
    absent = _h("an original that was never written")
    check("original_present: refuses names that are not a SHA-256 without an exception",
          [bw.original_present(n, 1) for n in ("../x", digest.upper(), digest[:63], "", 5, None)] == [False] * 6)
    check("original_present only looks: it creates no folder and no file",
          bw.original_present(absent, 3) is False and not (cfg.BULK_SOURCE_DIR / absent[:2]).exists())

    bad_state = _tree(cfg.BULK_SOURCE_DIR)
    bogus = [("name that is not the hash of the bytes", _h("something else"), data),
             ("upper-case hash", digest.upper(), data),
             ("short hash", digest[:63], data),
             ("hash with a non-hex character", "g" + digest[1:], data),
             ("path trick", "../" * 20 + digest[:40], data),
             ("empty name", "", data),
             ("hash as bytes", digest.encode(), data),
             ("data that is not bytes", digest, "text")]
    for label, name, payload in bogus:
        check(f"refused, nothing written: {label}", bw.store_original(name, payload) == bw.FAILED)
    check("... the originals folder is unchanged by all refusals", _tree(cfg.BULK_SOURCE_DIR) == bad_state)
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        other = b"another original"
        check("a failing replace for an original returns failed and leaves no temporary file",
              bw.store_original(hashlib.sha256(other).hexdigest(), other) == bw.FAILED and not list(cfg.BULK_SOURCE_DIR.rglob("*.tmp")))
    ba = bytearray(b"bytearray original")
    check("a bytearray is accepted as bytes", bw.store_original(hashlib.sha256(bytes(ba)).hexdigest(), ba) == bw.WRITTEN)

    # ── Only the bulk folders are touched ──────────────────────────────────────
    for d, name in ((cfg.RAW_DIR, "garmin_raw_2024-02-03.json"), (cfg.SOURCE_DIR, "garmin_source_2024-02-03.json"),
                    (cfg.SUMMARY_DIR, "garmin_2024-02-03.json")):
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text("{}", encoding="utf-8")
    api_before = {d: _tree(d) for d in (cfg.RAW_DIR, cfg.SOURCE_DIR, cfg.SUMMARY_DIR, cfg.LOG_DIR)}
    bw.write_day(*_day(date="2024-02-08"))
    bw.store_original(hashlib.sha256(b"y").hexdigest(), b"y")
    check("raw/, source/, summary/ and log/ are not touched by the bulk writer",
          all(_tree(d) == api_before[d] for d in api_before))
    check("what the writer creates lies below bulk/raw/ and bulk/source/ only",
          all(Path(p).is_relative_to(cfg.BULK_DIR) for p in cfg.BULK_DIR.rglob("*")))

    # ── End to end with the real normaliser output ────────────────────────────
    from datetime import datetime, timedelta, timezone

    def _stats(day, off):
        m = datetime.strptime(day, "%Y-%m-%d")
        f = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.0")
        return {"wellnessStartTimeGmt": f(m - timedelta(hours=off)), "wellnessStartTimeLocal": f(m),
                "wellnessEndTimeGmt": f(m + timedelta(days=1) - timedelta(hours=off)), "wellnessEndTimeLocal": f(m + timedelta(days=1))}

    windows = {d: _stats(d, 1) for d in ("2024-03-01", "2024-03-02", "2024-03-03", "2024-03-04")}
    pl = nz.plan_days(windows)
    E = nz.FIT_EPOCH_OFFSET
    t0 = int(datetime(2024, 3, 2, 12, tzinfo=timezone.utc).timestamp())
    col = nz.SampleCollector(pl)
    col.add_file(H1, 100, [{253: t0 - E, 27: 70}, {26: (t0 + 60 - E) & 0xFFFF, 27: 72}, {26: (t0 + 120 - E) & 0xFFFF, 27: 74}])
    col.add_file(H2, 200, [{253: t0 + 86400 - E, 27: 80}])
    results = [bw.write_day(pl.days[d.date], d, imported_at="2026-10-17T14:00:00") for d in col.iter_days()]
    check("the whole chain: two days written from the normaliser output", results == [bw.WRITTEN, bw.WRITTEN] and sorted(p.name for p in cfg.BULK_RAW_DIR.glob("garmin_bulk_2024-03-0*.json"))
          == ["garmin_bulk_2024-03-02.json", "garmin_bulk_2024-03-03.json"])
    d2 = bw._load_day("2024-03-02")[1]
    check("the whole chain: values and offsets arrive as the normaliser gave them",
          d2["sections"]["intraday"]["heart_rate"]["values"] == [[t0 * 1000, 70], [(t0 + 60) * 1000, 72], [(t0 + 120) * 1000, 74]]
          and (d2["utc_offset_hours"], d2["utc_offset_end_hours"], d2["source_files"]) == (1.0, 1.0, [H1]))
    check("the whole chain: running it again changes nothing",
          [bw.write_day(pl.days[d.date], d) for d in col.iter_days()] == [bw.UNCHANGED, bw.UNCHANGED])

    import re
    names_ok = all(re.fullmatch(r"garmin_bulk_\d{4}-\d{2}-\d{2}\.json", p.name) for p in cfg.BULK_RAW_DIR.iterdir())
    originals_ok = all(re.fullmatch(r"[0-9a-f]{2}", d.name) and all(re.fullmatch(rf"{d.name}[0-9a-f]{{62}}\.fit", f.name) for f in d.iterdir())
                       for d in cfg.BULK_SOURCE_DIR.iterdir())
    check("every name in the store is a day file name or <two hash characters>/<hash>.fit (nothing from the export's own names)",
          names_ok and originals_ok)

# ── Register finding F-1 (found in v1.7.6, fixed in v1.7.6.1): a day file that cannot be READ is not "new" ──
# _load_day() still answers no document for a damaged file (ValueError) and for a file that cannot be read for an
# I/O reason (OSError, e.g. a lock, or no access to stat it), but day_status() now tells them apart: a
# damaged file is "new" (the new write is the repair and is wanted), an unreadable one is "unreadable"
# and write_day() leaves it as it is and answers "failed". Before the fix a smaller stand was written
# over a fuller day that only could not be read for a moment.
with _isolated_log_env("bulk_writer_f1") as base:
    _day_file = cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json"
    _plan2, _samples2 = _day(hashes=(H1, H2), values=[[1706950800000, 61], [1706950860000, 62], [1706950920000, 200], [1706950980000, 70]])
    bw.write_day(_plan2, _samples2, imported_at="2026-10-18T09:00:00")
    _fuller = _day_file.read_bytes()
    _real_read_text = Path.read_text
    _real_exists = Path.exists

    def _locked(self, *a, **k):
        if self == _day_file:
            raise PermissionError("locked by another process")
        return _real_read_text(self, *a, **k)

    def _no_stat(self, *a, **k):
        if self == _day_file:
            raise PermissionError("no access to stat")
        return _real_exists(self, *a, **k)

    _small_plan, _small_samples = _day(hashes=(H1,))
    _big_plan, _big_samples = _day(hashes=(H1, H2, H3))
    check("F-1 baseline: a readable fuller day is kept against a smaller stand", bw.write_day(_small_plan, _small_samples) == bw.KEPT)
    with patch.object(Path, "read_text", _locked), patch.object(bw.log, "warning") as _warn:
        check("F-1: a day file that cannot be read for an I/O reason: _load_day still gives no document", bw._load_day("2024-02-03")[1] is None)
        check("F-1: ... but day_status says 'unreadable', not 'new'", bw.day_status("2024-02-03", [H1]) == "unreadable")
        check("F-1: ... and 'unreadable' for a fuller stand as well (an update is not risked either)", bw.day_status("2024-02-03", [H1, H2, H3]) == "unreadable")
        check("F-1: ... so a smaller stand is NOT written over the fuller day: failed, the file is byte for byte as it was",
              bw.write_day(_small_plan, _small_samples) == bw.FAILED and _day_file.read_bytes() == _fuller)
        check("F-1: ... a fuller stand is not written either: failed, the file is as it was",
              bw.write_day(_big_plan, _big_samples) == bw.FAILED and _day_file.read_bytes() == _fuller)
        check("F-1: ... and no temporary file is left behind", not list(cfg.BULK_RAW_DIR.glob("*.tmp")))
        _texts = " | ".join(str(c.args[0]) for c in _warn.call_args_list)
        check("F-1: ... the warning names the day and says what to do (run again, else delete the file by hand)",
              "2024-02-03" in _texts and "delete the file" in _texts and "I/O error" in _texts)
    check("F-1: with the lock gone the fuller day is kept against the smaller stand again, and 'unreadable' is gone",
          bw.day_status("2024-02-03", [H1]) == "smaller" and bw.write_day(_small_plan, _small_samples) == bw.KEPT and _day_file.read_bytes() == _fuller)
    check("F-1: ... and the fuller stand is written as an update once the file can be read (the lock only delayed it)",
          bw.write_day(_big_plan, _big_samples) == bw.WRITTEN and bw._load_day("2024-02-03")[1]["source_files"] == sorted([H1, H2, H3]))
    _day_file.write_bytes(_fuller)
    with patch.object(Path, "exists", _no_stat):
        check("F-1: no access even to find out whether the file exists (PermissionError in exists()) is 'unreadable' too",
              bw._load_day("2024-02-03")[1] is None and bw.day_status("2024-02-03", [H1]) == "unreadable"
              and bw.write_day(_small_plan, _small_samples) == bw.FAILED and _day_file.read_bytes() == _fuller)
    _day_file.write_text("{ not json", encoding="utf-8")
    check("F-1: a damaged day file (ValueError) is answered with None, day_status 'new': the repair by a new write is wanted",
          bw._load_day("2024-02-03")[1] is None and bw.day_status("2024-02-03", [H1]) == "new"
          and bw.write_day(_small_plan, _small_samples) == bw.WRITTEN and bw._load_day("2024-02-03")[1]["source_files"] == [H1])
    _day_file.write_bytes(b"\xff\xfe\x00 not utf-8")
    check("F-1: a file that is not text at all (UnicodeDecodeError, a ValueError) is damaged, not unreadable: 'new'",
          bw.day_status("2024-02-03", [H1]) == "new" and bw.write_day(_small_plan, _small_samples) == bw.WRITTEN)
    _day_file.write_text("[1, 2, 3]", encoding="utf-8")
    check("F-1: valid JSON that is not an object is damaged too: 'new'",
          bw._load_day("2024-02-03")[1] is None and bw.day_status("2024-02-03", [H1]) == "new")
    _day_file.unlink()
    check("F-1: a day without a file is 'new' (missing is not unreadable)", bw.day_status("2024-02-03", [H1]) == "new" and bw._load_day("2024-02-03")[1] is None)

# ── list_days (v1.7.6.1, F-3): the dates of the day files, from the file names only ─────────────────
with _isolated_log_env("bulk_writer_list") as base:
    check("list_days: no bulk folder -> [] and no folder is created", bw.list_days() == [] and not cfg.BULK_DIR.exists())
    for _d in ("2024-02-05", "2024-02-03", "2024-02-04"):
        _p, _s = _day(date=_d)
        bw.write_day(_p, _s)
    check("list_days: the dates of the day files, sorted", bw.list_days() == ["2024-02-03", "2024-02-04", "2024-02-05"])
    (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-06.json.tmp").write_bytes(b"x")
    (cfg.BULK_RAW_DIR / "garmin_bulk_2024-13-45.json").write_bytes(b"{}")
    (cfg.BULK_RAW_DIR / "garmin_bulk_notadate.json").write_bytes(b"{}")
    (cfg.BULK_RAW_DIR / "garmin_raw_2024-02-07.json").write_bytes(b"{}")
    (cfg.BULK_RAW_DIR / ("x" * len(cfg.BULK_FILE_PREFIX) + "2024-02-08.json")).write_bytes(b"{}")      # same length, other prefix
    (cfg.BULK_RAW_DIR / "notes.txt").write_bytes(b"x")
    check("list_days: a temporary file, a name with no date, another prefix and other files are not days",
          bw.list_days() == ["2024-02-03", "2024-02-04", "2024-02-05"])
    (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-04.json").write_text("{ not json", encoding="utf-8")
    _real_rt = Path.read_text

    def _no_read(self, *a, **k):
        raise PermissionError("locked by another process")

    with patch.object(Path, "read_text", _no_read), patch.object(Path, "read_bytes", _no_read):
        check("list_days: reads no file (a damaged or locked day file is listed all the same)",
              bw.list_days() == ["2024-02-03", "2024-02-04", "2024-02-05"])
    check("list_days: does not touch the store", sorted(p.name for p in cfg.BULK_RAW_DIR.iterdir()).count("garmin_bulk_2024-02-04.json") == 1)
    with patch.object(Path, "glob", side_effect=PermissionError("no access")), patch.object(bw.log, "warning") as _w:
        check("list_days: a folder that cannot be listed -> [] and a warning, nothing raised",
              bw.list_days() == [] and _w.call_count == 1)

# ── Aggregates (v1.7.6.1): one file per day in bulk/aggregates, apart from the intraday day files ──
_AGG = {"date": "2024-02-03", "user_summary": {"totalSteps": 9000, "restingHeartRate": 55},
        "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 25000}}, "stats": {"wellnessStartTimeGmt": "2024-02-02T23:00:00.0"}}
J1, J2, J3 = _h("json one"), _h("json two"), _h("json three")

with _isolated_log_env("bulk_writer_agg") as base:
    agg_file = cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-03.json"
    check("aggregates: no folder and no file at the start: list_aggregate_days is [] and creates nothing",
          bw.list_aggregate_days() == [] and not cfg.BULK_AGG_DIR.exists())
    check("aggregates: a day that does not exist is 'new', read_aggregates is None",
          bw.aggregates_status("2024-02-03", [J1]) == "new" and bw.read_aggregates("2024-02-03") is None)
    check("aggregates: a new day is written", bw.write_aggregates("2024-02-03", _AGG, [J1], imported_at="2026-10-18T15:00:00") == bw.WRITTEN
          and agg_file.is_file())
    doc = json.loads(agg_file.read_text(encoding="utf-8"))
    check("aggregates: the file name is the configured prefix + date in bulk/aggregates/, the intraday folder is untouched",
          agg_file.name == f"{cfg.BULK_AGG_FILE_PREFIX}2024-02-03.json" and not cfg.BULK_RAW_DIR.exists())
    check("aggregates: head and content (date, version, generator, origin, import time, sorted source files, the values as given)",
          (doc["date"], doc["schema_version"], doc["generated_by"], doc["origin"], doc["imported_at"], doc["source_files"])
          == ("2024-02-03", bw.AGG_SCHEMA_VERSION, "garmin_bulk_writer", "gdpr_export", "2026-10-18T15:00:00", [J1])
          and doc["aggregates"] == _AGG and set(doc) == {"date", "schema_version", "generated_by", "origin", "imported_at", "source_files", "aggregates"})
    check("aggregates: compact JSON, no temporary file left", "\n" not in agg_file.read_text(encoding="utf-8")
          and not list(cfg.BULK_AGG_DIR.glob("*.tmp")))
    check("aggregates: read_aggregates returns exactly what is in the file", bw.read_aggregates("2024-02-03") == doc)
    check("aggregates: the same files again: 'unchanged', nothing written (not a byte, not the import time)",
          bw.aggregates_status("2024-02-03", [J1]) == "unchanged"
          and bw.write_aggregates("2024-02-03", _AGG, [J1], imported_at="2099-01-01T00:00:00") == bw.UNCHANGED
          and json.loads(agg_file.read_text(encoding="utf-8"))["imported_at"] == "2026-10-18T15:00:00")

    _agg2 = {**_AGG, "user_summary": {"totalSteps": 9100}}
    check("aggregates: more files than stored is an update, the day is replaced",
          bw.aggregates_status("2024-02-03", [J1, J2]) == "update"
          and bw.write_aggregates("2024-02-03", _agg2, sorted([J1, J2], reverse=True)) == bw.WRITTEN
          and bw.read_aggregates("2024-02-03")["source_files"] == sorted([J1, J2])
          and bw.read_aggregates("2024-02-03")["aggregates"]["user_summary"]["totalSteps"] == 9100)
    _before = agg_file.read_bytes()
    check("aggregates: fewer files never replace a fuller day (an import of part of an export)",
          bw.aggregates_status("2024-02-03", [J1]) == "smaller" and bw.write_aggregates("2024-02-03", _AGG, [J1]) == bw.KEPT
          and agg_file.read_bytes() == _before)
    check("aggregates: a set that is no superset is smaller as well",
          bw.aggregates_status("2024-02-03", [J1, J3]) == "smaller" and bw.write_aggregates("2024-02-03", _AGG, [J1, J3]) == bw.KEPT
          and agg_file.read_bytes() == _before)

    _old = json.loads(_before.decode("utf-8"))
    _old["schema_version"] = 0
    agg_file.write_text(json.dumps(_old), encoding="utf-8")
    check("aggregates: the same files under an older schema are an update",
          bw.aggregates_status("2024-02-03", [J1, J2]) == "update" and bw.write_aggregates("2024-02-03", _agg2, [J1, J2]) == bw.WRITTEN
          and bw.read_aggregates("2024-02-03")["schema_version"] == bw.AGG_SCHEMA_VERSION)
    _new = json.loads(agg_file.read_text(encoding="utf-8"))
    _new["schema_version"] = bw.AGG_SCHEMA_VERSION + 1
    agg_file.write_text(json.dumps(_new), encoding="utf-8")
    _state_newer = agg_file.read_bytes()
    check("aggregates: a file written by a newer schema is kept",
          bw.aggregates_status("2024-02-03", [J1, J2]) == "newer" and bw.write_aggregates("2024-02-03", _agg2, [J1, J2, J3]) == bw.KEPT
          and agg_file.read_bytes() == _state_newer)

    # F-1 semantics, from the start: a damaged file is repaired, an unreadable one is left alone
    agg_file.write_text("{ not json", encoding="utf-8")
    check("aggregates: a damaged file (not JSON) is answered with None and 'new': the new write is the repair",
          bw.read_aggregates("2024-02-03") is None and bw.aggregates_status("2024-02-03", [J1]) == "new"
          and bw.write_aggregates("2024-02-03", _AGG, [J1]) == bw.WRITTEN and bw.read_aggregates("2024-02-03")["source_files"] == [J1])
    for _what, _bytes in (("not text at all", b"\xff\xfe\x00 x"), ("valid JSON that is no object", b"[1, 2]"), ("a file without source_files", b"{}")):
        agg_file.write_bytes(_bytes)
        check(f"aggregates: {_what} is damaged, not unreadable: 'new'", bw.aggregates_status("2024-02-03", [J1]) == "new")
    bw.write_aggregates("2024-02-03", _agg2, [J1, J2])
    _fuller = agg_file.read_bytes()
    _real_rt, _real_ex = Path.read_text, Path.exists

    def _locked(self, *a, **k):
        if self == agg_file:
            raise PermissionError("locked by another process")
        return _real_rt(self, *a, **k)

    def _no_stat(self, *a, **k):
        if self == agg_file:
            raise PermissionError("no access to stat")
        return _real_ex(self, *a, **k)

    for _label, _target, _fn in (("a lock on reading", "read_text", _locked), ("no access to stat", "exists", _no_stat)):
        with patch.object(Path, _target, _fn), patch.object(bw.log, "warning") as _w:
            check(f"aggregates: {_label}: read_aggregates None, status 'unreadable' (also for a fuller stand)",
                  bw.read_aggregates("2024-02-03") is None and bw.aggregates_status("2024-02-03", [J1]) == "unreadable"
                  and bw.aggregates_status("2024-02-03", [J1, J2, J3]) == "unreadable")
            check(f"aggregates: {_label}: a smaller and a fuller stand are both 'failed', the file is as it was, no temporary file",
                  bw.write_aggregates("2024-02-03", _AGG, [J1]) == bw.FAILED and bw.write_aggregates("2024-02-03", _agg2, [J1, J2, J3]) == bw.FAILED
                  and agg_file.read_bytes() == _fuller and not list(cfg.BULK_AGG_DIR.glob("*.tmp")))
            _texts = " | ".join(str(c.args[0]) for c in _w.call_args_list)
            check(f"aggregates: {_label}: the warning names the day and what to do",
                  "2024-02-03" in _texts and "delete the file" in _texts and "bulk/aggregates" in _texts)
    check("aggregates: with the lock gone the fuller stand is written as an update (the lock only delayed it)",
          bw.write_aggregates("2024-02-03", _agg2, [J1, J2, J3]) == bw.WRITTEN)

    # the two kinds count their schema versions on their own
    _pd, _sd = _day(date="2024-02-20", hashes=(H1,))
    bw.write_day(_pd, _sd)
    bw.write_aggregates("2024-02-20", {"date": "2024-02-20", "a": 1}, [J1])
    with patch.object(bw, "AGG_SCHEMA_VERSION", bw.AGG_SCHEMA_VERSION + 1):
        check("aggregates: a higher aggregates version makes the aggregates file an update and leaves the intraday day unchanged",
              bw.aggregates_status("2024-02-20", [J1]) == "update" and bw.day_status("2024-02-20", [H1]) == "unchanged")
    with patch.object(bw, "BULK_SCHEMA_VERSION", bw.BULK_SCHEMA_VERSION + 1):
        check("aggregates: ... and a higher intraday version the other way round",
              bw.day_status("2024-02-20", [H1]) == "update" and bw.aggregates_status("2024-02-20", [J1]) == "unchanged")
    for _f in (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-20.json",):
        _f.unlink()

    # list_aggregate_days: names only
    (cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-06.json.tmp").write_bytes(b"x")
    (cfg.BULK_AGG_DIR / "garmin_bulk_agg_notadate.json").write_bytes(b"{}")
    (cfg.BULK_AGG_DIR / "garmin_bulk_2024-02-07.json").write_bytes(b"{}")
    (cfg.BULK_AGG_DIR / ("x" * len(cfg.BULK_AGG_FILE_PREFIX) + "2024-02-08.json")).write_bytes(b"{}")
    bw.write_aggregates("2024-01-31", {**_AGG, "date": "2024-01-31"}, [J1])
    with patch.object(Path, "read_text", side_effect=PermissionError("no")), patch.object(Path, "read_bytes", side_effect=PermissionError("no")):
        check("aggregates: list_aggregate_days lists the days by name, sorted; other names are no days; no file is read",
              bw.list_aggregate_days() == ["2024-01-31", "2024-02-03", "2024-02-20"])
    check("aggregates: the intraday list is not affected by the aggregates folder", bw.list_days() == [])
    with patch.object(Path, "glob", side_effect=PermissionError("no access")), patch.object(bw.log, "warning") as _w2:
        check("aggregates: a folder that cannot be listed -> [] and a warning", bw.list_aggregate_days() == [] and _w2.call_count == 1)

    # refused input
    _tree_before = sorted(p.name for p in cfg.BULK_AGG_DIR.iterdir())
    _bad = ("../../x", "2024-2-3", "2024-13-01", "2024-02-30", "", None, 20240203)
    check("aggregates: a date that is no date is refused, nothing is created",
          all(bw.write_aggregates(d, _AGG, [J1]) == bw.FAILED for d in _bad) and bw.aggregates_status("../x", [J1]) == "new"
          and bw.read_aggregates("../../x") is None)
    check("aggregates: aggregates that are empty or no dict are refused",
          all(bw.write_aggregates("2024-02-10", a, [J1]) == bw.FAILED for a in ({}, None, [], "x", [1])))
    check("aggregates: source files that are empty or no SHA-256 are refused",
          all(bw.write_aggregates("2024-02-10", _AGG | {"date": "2024-02-10"}, f) == bw.FAILED
              for f in ([], None, "abc", [J1.upper()], [J1[:63]], ["../../x"], [123])))
    check("aggregates: a date inside the aggregates that is another day is refused",
          bw.write_aggregates("2024-02-10", {**_AGG, "date": "2024-02-11"}, [J1]) == bw.FAILED)
    check("aggregates: values that cannot be written as JSON are 'failed', nothing raised, nothing left",
          bw.write_aggregates("2024-02-10", {"date": "2024-02-10", "x": object()}, [J1]) == bw.FAILED
          and sorted(p.name for p in cfg.BULK_AGG_DIR.iterdir()) == _tree_before)
    check("aggregates: a day without a 'date' key inside is accepted (the head carries the date)",
          bw.write_aggregates("2024-02-10", {"user_summary": {"totalSteps": 1}}, [J1]) == bw.WRITTEN)

    # fsync, retry: the same machinery as the intraday files
    synced = []
    with patch("os.fsync", side_effect=lambda fd: synced.append(fd)):
        check("aggregates: a file is flushed to disk (fsync on the write handle)",
              bw.write_aggregates("2024-02-12", {"date": "2024-02-12", "a": 1}, [J1]) == bw.WRITTEN and len(synced) == 1)
    _real_replace, _calls = os.replace, []

    def _flaky(src, dst):
        _calls.append(1)
        if len(_calls) < 3:
            raise PermissionError("sharing violation")
        return _real_replace(src, dst)

    with patch("os.replace", side_effect=_flaky), patch("time.sleep") as _sl:
        check("aggregates: a short lock on the target is waited out (os.replace tried again)",
              bw.write_aggregates("2024-02-13", {"date": "2024-02-13", "a": 1}, [J1]) == bw.WRITTEN and len(_calls) == 3 and _sl.call_count == 2)
    with patch("os.replace", side_effect=PermissionError("sharing violation")), patch("time.sleep"):
        check("aggregates: a lock that does not go away is 'failed', the temporary file is removed",
              bw.write_aggregates("2024-02-14", {"date": "2024-02-14", "a": 1}, [J1]) == bw.FAILED
              and not (cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-14.json.tmp").exists()
              and not (cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-14.json").exists())

# ── Originals as JSON (v1.7.6.1) ────────────────────────────────────────────────
with _isolated_log_env("bulk_writer_json_orig") as base:
    _jdata = b'{"uds": [1, 2, 3]}'
    _jh = hashlib.sha256(_jdata).hexdigest()
    _jpath = cfg.BULK_SOURCE_DIR / _jh[:2] / f"{_jh}.json"
    check("json original: not present before, a dry-run question creates nothing",
          not bw.original_json_present(_jh, len(_jdata)) and not cfg.BULK_DIR.exists())
    check("json original: stored as <xx>/<hash>.json with the exact bytes",
          bw.store_original_json(_jh, _jdata) == bw.WRITTEN and _jpath.read_bytes() == _jdata)
    check("json original: present with the same size, a second store is 'present' and writes nothing",
          bw.original_json_present(_jh, len(_jdata)) and not bw.original_json_present(_jh, len(_jdata) + 1)
          and bw.store_original_json(_jh, _jdata) == bw.PRESENT)
    check("json original: the .json file is not taken for a .fit file with the same hash (and the other way round)",
          not bw.original_present(_jh, len(_jdata)) and bw.store_original(_jh, _jdata) == bw.WRITTEN
          and (cfg.BULK_SOURCE_DIR / _jh[:2] / f"{_jh}.fit").read_bytes() == _jdata and _jpath.exists())
    check("json original: bytes that do not match the name, a name that is no SHA-256 and non-bytes are refused",
          bw.store_original_json(_h("other"), _jdata) == bw.FAILED and bw.store_original_json("../x", _jdata) == bw.FAILED
          and bw.store_original_json(_jh, "text") == bw.FAILED)
    check("json original: another suffix is refused and nothing is created",
          bw.store_original(_jh, _jdata, ".txt") == bw.FAILED and bw.store_original(_jh, _jdata, "") == bw.FAILED
          and bw.store_original(_jh, _jdata, "/../x") == bw.FAILED and not bw.original_present(_jh, len(_jdata), ".txt")
          and sorted(p.name for p in (cfg.BULK_SOURCE_DIR / _jh[:2]).iterdir()) == sorted([f"{_jh}.fit", f"{_jh}.json"]))
    check("json original: no temporary file is left", not list(cfg.BULK_SOURCE_DIR.rglob("*.tmp")))

# ── A day or aggregates file of another archive (v1.7.6.2): import_day_file and its helpers ───────────────────
K1, K2, K3 = _h("aggregates one"), _h("aggregates two"), _h("aggregates three")
_DEL = object()

with _isolated_log_env("bulk_writer_imp_src") as base:
    # the files of a first archive, made by the writer itself
    _ip1, _is1 = _day(hashes=(H1,))
    _ip2, _is2 = _day(hashes=(H1, H2), values=[[1706950800000, 61], [1706950860000, 62], [1706950920000, 200], [1706950980000, 70]])
    bw.write_day(_ip1, _is1, imported_at="2026-10-17T13:30:00")
    DAY_SMALL = (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json").read_bytes()
    bw.write_day(_ip2, _is2, imported_at="2026-10-18T09:00:00")
    DAY_FULL = (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json").read_bytes()
    bw.write_aggregates("2024-02-03", {"date": "2024-02-03", "uds": {"steps": 1}}, [K1], imported_at="2026-10-18T10:00:00")
    AGG_SMALL = (cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-03.json").read_bytes()
    bw.write_aggregates("2024-02-03", {"date": "2024-02-03", "uds": {"steps": 2}}, [K1, K2], imported_at="2026-10-18T11:00:00")
    AGG_FULL = (cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-03.json").read_bytes()


def _mut(raw, **changes):
    """The bytes of a day or aggregates file with some keys changed (value _DEL removes the key)."""
    doc = json.loads(raw.decode("utf-8"))
    for k, v in changes.items():
        if v is _DEL:
            doc.pop(k, None)
        else:
            doc[k] = v
    return json.dumps(doc, separators=(",", ":")).encode("utf-8")


with _isolated_log_env("bulk_writer_imp") as base:
    _dp = cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json"
    _ap = cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-02-03.json"

    # -- into an empty archive: byte for byte -----------------------------------------------------------
    check("import: a day of another archive is written, with exactly the bytes it came with",
          bw.import_day_file("intraday", "2024-02-03", DAY_SMALL) == bw.WRITTEN and _dp.read_bytes() == DAY_SMALL)
    check("import: the aggregates file of another archive is written byte for byte, in bulk/aggregates",
          bw.import_day_file("aggregates", "2024-02-03", AGG_SMALL) == bw.WRITTEN and _ap.read_bytes() == AGG_SMALL)
    check("import: the written files obey the rules of the module (day_status and aggregates_status call them unchanged)",
          bw.day_status("2024-02-03", [H1]) == "unchanged" and bw.aggregates_status("2024-02-03", [K1]) == "unchanged")
    _before = _tree(base)
    check("import: the same files again are unchanged and not a byte is rewritten",
          bw.import_day_file("intraday", "2024-02-03", DAY_SMALL) == bw.UNCHANGED
          and bw.import_day_file("aggregates", "2024-02-03", AGG_SMALL) == bw.UNCHANGED and _tree(base) == _before)
    check("import: no temporary file is left", not list(base.rglob("*.tmp")))

    # -- a fuller stand replaces, a smaller or a different one never does -------------------------------
    check("import: a fuller day (more files) replaces the stored day",
          bw.import_day_file("intraday", "2024-02-03", DAY_FULL) == bw.WRITTEN and _dp.read_bytes() == DAY_FULL)
    check("import: fuller aggregates replace the stored aggregates",
          bw.import_day_file("aggregates", "2024-02-03", AGG_FULL) == bw.WRITTEN and _ap.read_bytes() == AGG_FULL)
    _full_state = _tree(base)
    check("import: a smaller stand never replaces a fuller one (day and aggregates)",
          bw.import_day_file("intraday", "2024-02-03", DAY_SMALL) == bw.KEPT
          and bw.import_day_file("aggregates", "2024-02-03", AGG_SMALL) == bw.KEPT and _tree(base) == _full_state)
    _other_set = _mut(DAY_FULL, source_files=sorted([H1, H3]))
    check("import: a different set of files that is not a superset is kept out (the stored day stays)",
          bw.import_day_file("intraday", "2024-02-03", _other_set) == bw.KEPT and _tree(base) == _full_state)

    # -- schema versions -------------------------------------------------------------------------------
    _dp.write_bytes(_mut(DAY_FULL, schema_version=2))
    _state2 = _tree(base)
    check("import: a stored day of a newer schema is not replaced by an older one (same files)",
          bw.import_day_file("intraday", "2024-02-03", DAY_FULL) == bw.KEPT and _tree(base) == _state2)
    _dp.write_bytes(DAY_FULL)
    _dp.write_bytes(_mut(DAY_FULL, schema_version=0))
    # a stored day of an older version cannot be made here (the known version is the lowest), so the
    # rule is pinned with the known version raised for the duration of the check
    with patch.object(bw, "BULK_SCHEMA_VERSION", 2):
        _inc = _mut(DAY_FULL, schema_version=2)
        check("import: same files but a newer schema than the stored one is an update (a program that knows version 2)",
              bw.import_day_file("intraday", "2024-02-03", _inc) == bw.WRITTEN and _dp.read_bytes() == _inc)
    _dp.write_bytes(DAY_FULL)
    _newer = _mut(DAY_FULL, schema_version=bw.BULK_SCHEMA_VERSION + 1, source_files=sorted([H1, H2, H3]))
    check("import: a schema newer than this program knows is not stored (kept in the container), over a stored day",
          bw.import_day_file("intraday", "2024-02-03", _newer) == bw.KEPT and _dp.read_bytes() == DAY_FULL)
    _agg_newer = _mut(AGG_FULL, schema_version=bw.AGG_SCHEMA_VERSION + 1)
    check("import: the same for aggregates",
          bw.import_day_file("aggregates", "2024-02-03", _agg_newer) == bw.KEPT and _ap.read_bytes() == AGG_FULL)
    _dp.unlink()
    check("import: ... and over a missing day nothing is stored either",
          bw.import_day_file("intraday", "2024-02-03", _newer) == bw.KEPT and not _dp.exists())

    # -- damaged and unreadable stored files --------------------------------------------------------------
    for _label, _content in (("garbage", b"this is not json {"), ("empty", b""), ("a list", b"[1, 2]"),
                             ("without source_files", b'{"schema_version": 1}')):
        _dp.write_bytes(_content)
        check(f"import: a damaged stored day ({_label}) is replaced by the file that comes in",
              bw.import_day_file("intraday", "2024-02-03", DAY_SMALL) == bw.WRITTEN and _dp.read_bytes() == DAY_SMALL)
    _dp.write_bytes(DAY_FULL)
    _real_read_text = Path.read_text

    def _locked(self, *a, **k):
        if self == _dp or self == _ap:
            raise PermissionError("locked by another process")
        return _real_read_text(self, *a, **k)

    with patch.object(Path, "read_text", _locked), patch.object(bw.log, "warning") as _warn:
        _r1 = bw.import_day_file("intraday", "2024-02-03", _mut(DAY_FULL, source_files=sorted([H1, H2, H3])))
        _r2 = bw.import_day_file("aggregates", "2024-02-03", _mut(AGG_FULL, source_files=sorted([K1, K2, K3])))
    check("import: a stored file that cannot be read (a lock) is not touched, not even by a fuller stand: failed",
          _r1 == bw.FAILED and _r2 == bw.FAILED and _dp.read_bytes() == DAY_FULL and _ap.read_bytes() == AGG_FULL
          and not list(base.rglob("*.tmp")))
    check("import: ... and the warning says to run the import again",
          any("Run the import again" in str(c.args[0]) for c in _warn.call_args_list))

    # -- bytes as they come, whatever their formatting ---------------------------------------------------
    _pretty = json.dumps(json.loads(DAY_FULL.decode("utf-8")), indent=2, ensure_ascii=False).encode("utf-8")
    _dp.unlink()
    check("import: the bytes are written as they came (an indented file stays indented), not re-serialised",
          bw.import_day_file("intraday", "2024-02-03", _pretty) == bw.WRITTEN and _dp.read_bytes() == _pretty
          and bw.import_day_file("intraday", "2024-02-03", bytearray(_pretty)) == bw.UNCHANGED)

# -- files that must be refused: nothing written, one warning each ---------------------------------------------
_V = {"intraday": DAY_SMALL, "aggregates": AGG_SMALL}
_BAD = [
    ("intraday", "date of the file differs", {"date": "2024-02-04"}), ("intraday", "no date", {"date": _DEL}),
    ("intraday", "origin of another kind", {"origin": "api"}), ("intraday", "no origin", {"origin": _DEL}),
    ("intraday", "schema_version a bool", {"schema_version": True}), ("intraday", "schema_version 0", {"schema_version": 0}),
    ("intraday", "schema_version a string", {"schema_version": "1"}), ("intraday", "no source_files", {"source_files": _DEL}),
    ("intraday", "empty source_files", {"source_files": []}), ("intraday", "source_files that are no hashes", {"source_files": ["x"]}),
    ("intraday", "source_files not a list", {"source_files": H1}),
    ("intraday", "no utc_offset_hours", {"utc_offset_hours": _DEL}), ("intraday", "utc_offset_hours a string", {"utc_offset_hours": "1"}),
    ("intraday", "utc_offset_hours a bool", {"utc_offset_hours": True}),
    ("intraday", "no sections", {"sections": _DEL}), ("intraday", "sections not an object", {"sections": []}),
    ("intraday", "no heart_rate", {"sections": {"intraday": {}}}),
    ("intraday", "values not a list", {"sections": {"intraday": {"heart_rate": {"values": "x"}}}}),
    ("intraday", "no values", {"sections": {"intraday": {"heart_rate": {"values": []}}}}),
    ("intraday", "values not ascending", {"sections": {"intraday": {"heart_rate": {"values": [[2000, 61], [1000, 62]]}}}}),
    ("intraday", "a value out of range", {"sections": {"intraday": {"heart_rate": {"values": [[1000, 300]]}}}}),
    ("intraday", "a value that is no pair", {"sections": {"intraday": {"heart_rate": {"values": [[1000]]}}}}),
    ("aggregates", "date of the file differs", {"date": "2024-02-04"}), ("aggregates", "origin of another kind", {"origin": "x"}),
    ("aggregates", "schema_version 0", {"schema_version": 0}), ("aggregates", "no source_files", {"source_files": _DEL}),
    ("aggregates", "no aggregates", {"aggregates": _DEL}), ("aggregates", "aggregates empty", {"aggregates": {}}),
    ("aggregates", "aggregates a list", {"aggregates": [1]}),
    ("aggregates", "the date inside the aggregates differs", {"aggregates": {"date": "2024-02-04", "a": 1}}),
]
with _isolated_log_env("bulk_writer_imp_bad") as base, patch.object(bw.log, "warning") as _warn:
    _not_failed, _no_warning = [], []
    for _kind, _label, _chg in _BAD:
        _warn.reset_mock()
        _res = bw.import_day_file(_kind, "2024-02-03", _mut(_V[_kind], **_chg))
        if _res != bw.FAILED:
            _not_failed.append(f"{_kind}: {_label}")
        if _warn.call_count != 1 or "refused (" not in str(_warn.call_args.args[0]):
            _no_warning.append(f"{_kind}: {_label}")
    check(f"import: {len(_BAD)} kinds of invalid file are refused as 'failed' ({_not_failed or 'none missed'})", _not_failed == [])
    check("import: ... each with exactly one warning that says 'refused (' and why", _no_warning == [])
    check("import: ... and none of them wrote anything, not even a folder or a temporary file", not cfg.BULK_DIR.exists())
    for _name, _data in (("not JSON", b"{ nope"), ("not UTF-8", b"\xff\xfe\x00"), ("a JSON list", b"[1, 2]"), ("empty", b""), ("text, not bytes", "text")):
        check(f"import: bytes that are {_name} are refused", bw.import_day_file("intraday", "2024-02-03", _data) == bw.FAILED)
    _warn.reset_mock()
    bw.import_day_file("intraday", "2024-02-03", "text")
    check("import: bytes that are text are refused with the reason 'data is not bytes' (not by a crash further on)",
          _warn.call_count == 1 and "data is not bytes" in str(_warn.call_args.args[0]))
    check("import: a kind that is neither intraday nor aggregates is refused",
          bw.import_day_file("original", "2024-02-03", DAY_SMALL) == bw.FAILED and bw.import_day_file(None, "2024-02-03", DAY_SMALL) == bw.FAILED)
    check("import: a date that is no date is refused and writes nothing (no path out of the folder)",
          all(bw.import_day_file("intraday", _d, _mut(DAY_SMALL, date=_d)) == bw.FAILED for _d in ("../../x", "2024-13-01", "2024-2-3", "", None))
          and not cfg.BULK_DIR.exists())

# -- failures while writing, retries, durability, one writing flow ----------------------------------------------
with _isolated_log_env("bulk_writer_imp_write") as base:
    _dp = cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json"
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        check("import: a failing replace is 'failed', nothing raised, no day and no temporary file",
              bw.import_day_file("intraday", "2024-02-03", DAY_SMALL) == bw.FAILED and not _dp.exists() and not list(base.rglob("*.tmp")))
    bw.import_day_file("intraday", "2024-02-03", DAY_SMALL)
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        check("import: ... a stored day stays as it was when the replace of a fuller one fails",
              bw.import_day_file("intraday", "2024-02-03", DAY_FULL) == bw.FAILED and _dp.read_bytes() == DAY_SMALL
              and not list(base.rglob("*.tmp")))
    _calls = []
    _real_replace = os.replace

    def _busy_twice(src, dst):
        _calls.append(1)
        if len(_calls) <= 2:
            raise PermissionError(13, "sharing violation")
        return _real_replace(src, dst)

    with patch.object(bw.os, "replace", _busy_twice), patch.object(bw.time, "sleep"):
        check("import: two sharing violations in a row are retried and the file is written (as for every other file)",
              bw.import_day_file("intraday", "2024-02-03", DAY_FULL) == bw.WRITTEN and len(_calls) == 3 and _dp.read_bytes() == DAY_FULL)
    _synced = []
    _real_fsync = os.fsync
    with patch.object(bw.os, "fsync", lambda fd: (_synced.append(fd), _real_fsync(fd))[1]):
        check("import: the file is flushed to disk (fsync on the write handle)",
              bw.import_day_file("aggregates", "2024-02-03", AGG_SMALL) == bw.WRITTEN and len(_synced) == 1)
    _spy_calls = []
    _real_wa = bw._write_atomic
    with patch.object(bw, "_write_atomic", lambda dst, payload: (_spy_calls.append(dst.name), _real_wa(dst, payload))[1]):
        bw.write_day(*_day(date="2024-02-08"))
        bw.write_aggregates("2024-02-08", {"date": "2024-02-08", "a": 1}, [K1])
        bw.import_day_file("intraday", "2024-02-09", _mut(DAY_SMALL, date="2024-02-09"))
        bw.import_day_file("aggregates", "2024-02-09", _mut(AGG_SMALL, date="2024-02-09", aggregates={"date": "2024-02-09", "uds": {"steps": 1}}))
        _written_names = list(_spy_calls)
        bw.import_day_file("intraday", "2024-02-09", _mut(DAY_SMALL, date="2024-02-09"))             # unchanged
        bw.import_day_file("intraday", "2024-02-03", DAY_SMALL)                                          # kept
    check("import: write_day, write_aggregates and import_day_file all write through the one _write_atomic, and only when they write",
          _written_names == ["garmin_bulk_2024-02-08.json", "garmin_bulk_agg_2024-02-08.json",
                             "garmin_bulk_2024-02-09.json", "garmin_bulk_agg_2024-02-09.json"] and _spy_calls == _written_names)
    _p, _s = _day(date="2024-02-20")
    with patch.object(bw.os, "replace", side_effect=OSError("disk full")):
        check("_write_atomic: a failure keeps neither a temporary file nor the new day (write_day), an exception never leaves the module",
              bw.write_day(_p, _s) == bw.FAILED and bw.write_aggregates("2024-02-20", {"date": "2024-02-20", "a": 1}, [K1]) == bw.FAILED
              and not list(base.rglob("*.tmp")) and not (cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-20.json").exists())

# -- describe_container_path -----------------------------------------------------------------------------------
_HX = "ab" + "0" * 62
with _isolated_log_env("bulk_writer_imp_path"):
    _CASES = [
        ("garmin_data/bulk/raw/garmin_bulk_2024-02-03.json", ("intraday", "2024-02-03")),
        ("garmin_data/bulk/aggregates/garmin_bulk_agg_2024-02-03.json", ("aggregates", "2024-02-03")),
        (f"garmin_data/bulk/source/ab/{_HX}.fit", ("original", _HX, ".fit")),
        (f"garmin_data/bulk/source/ab/{_HX}.json", ("original", _HX, ".json")),
        ("garmin_data/bulk/raw/garmin_bulk_agg_2024-02-03.json", None),                  # an aggregates name in the day folder
        ("garmin_data/bulk/aggregates/garmin_bulk_2024-02-03.json", None),
        ("garmin_data/bulk/raw/garmin_xxxx_2024-02-03.json", None),                        # a prefix of the same length, but not the prefix
        ("garmin_data/bulk/aggregates/garmin_bulk_zzz_2024-02-03.json", None),
        ("garmin_data/bulk/raw/2024-02-03.json", None),
        ("garmin_data/bulk/raw/garmin_bulk_2024-13-01.json", None),                        # not a date
        ("garmin_data/bulk/raw/garmin_bulk_2024-02-03.json.tmp", None),
        ("garmin_data/bulk/raw/garmin_bulk_2024-02-03.txt", None),
        ("garmin_data/bulk/raw/sub/garmin_bulk_2024-02-03.json", None),                    # one part too many
        ("garmin_data/bulk/garmin_bulk_2024-02-03.json", None),                            # one part too few
        (f"garmin_data/bulk/source/cd/{_HX}.fit", None),                                   # not in the folder of its first two characters
        (f"garmin_data/bulk/source/{_HX}.fit", None),
        (f"garmin_data/bulk/source/ab/{_HX}.txt", None),
        (f"garmin_data/bulk/source/ab/{_HX.upper()}.fit", None),
        (f"garmin_data/bulk/source/ab/{_HX[:-1]}.fit", None),
        (f"garmin_data/bulk/source/ab/{_HX}.fit.tmp", None),
        ("garmin_data/bulk/other/garmin_bulk_2024-02-03.json", None),
        ("garmin_data/raw/garmin_raw_2024-02-03.json", None), ("garmin_data/backup/bulk/raw/garmin_bulk_2024-02-03.json", None),
        ("context_data/bulk/raw/garmin_bulk_2024-02-03.json", None),
        ("garmin_data/bulk/raw/../raw/garmin_bulk_2024-02-03.json", None), ("garmin_data/bulk", None), ("", None), (None, None), (5, None),
    ]
    _wrong = [(p, e, bw.describe_container_path(p)) for p, e in _CASES if bw.describe_container_path(p) != e]
    check(f"describe_container_path: {len(_CASES)} paths are described as expected ({_wrong or 'all'})", _wrong == [])
    check("describe_container_path: looks at the name only, nothing is created", not cfg.BULK_DIR.exists())

# -- list_originals -----------------------------------------------------------------------------------------------
with _isolated_log_env("bulk_writer_imp_list") as base:
    check("list_originals: no bulk/source folder -> an empty set and no folder created",
          bw.list_originals() == set() and not cfg.BULK_DIR.exists())
    _oa, _ob = b"original a", b"original b"
    _ha, _hb = hashlib.sha256(_oa).hexdigest(), hashlib.sha256(_ob).hexdigest()
    bw.store_original(_ha, _oa)
    bw.store_original_json(_hb, _ob)
    (cfg.BULK_SOURCE_DIR / _ha[:2] / f"{_ha}.fit.tmp").write_bytes(b"half")
    (cfg.BULK_SOURCE_DIR / _ha[:2] / "notes.txt").write_bytes(b"x")
    (cfg.BULK_SOURCE_DIR / _ha[:2] / ("0" * 64 + ".fit")).write_bytes(b"in the wrong folder unless the prefix is 00")
    (cfg.BULK_SOURCE_DIR / "stray.fit").write_bytes(b"in the root")
    (cfg.BULK_SOURCE_DIR / "zz").mkdir()
    (cfg.BULK_SOURCE_DIR / "zz" / (_ha + ".fit")).write_bytes(b"folder zz is not the prefix of this hash")
    check("list_originals: the names of the originals, with their suffix; a .tmp, other names, a name in the wrong folder and files in the root are left out",
          bw.list_originals() == {f"{_ha}.fit", f"{_hb}.json"})
    _before = _tree(base)
    bw.list_originals()
    check("list_originals: only looks (nothing changed)", _tree(base) == _before)
    with patch.object(Path, "iterdir", side_effect=PermissionError("no access")), patch.object(bw.log, "warning") as _warn:
        check("list_originals: a folder that cannot be listed gives an empty set and a warning, not an exception",
              bw.list_originals() == set() and _warn.call_count == 1)

# ── Imports: standard library only, garmin_config lazily, no other owner involved ─
_tree_ast = ast.parse(Path(bw.__file__).read_text(encoding="utf-8"))
_top, _all = set(), set()
for _n in _tree_ast.body:
    if isinstance(_n, ast.Import):
        _top |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _top.add(_n.module.split(".")[0])
for _n in ast.walk(_tree_ast):
    if isinstance(_n, ast.Import):
        _all |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _all.add(_n.module.split(".")[0])
check("module level: standard library only (garmin_config is imported inside the functions)",
      _top <= {"hashlib", "json", "logging", "os", "re", "time", "datetime", "__future__"} and "garmin_config" not in _top)
check("garmin_config is the only project module used at all",
      (_all - {"hashlib", "json", "logging", "os", "re", "time", "datetime", "__future__"}) <= {"garmin_config"})
check("no print", not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree_ast)))

summary()
