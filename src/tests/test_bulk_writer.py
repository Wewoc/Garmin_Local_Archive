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
    check("read_day returns exactly what is in the file", bw.read_day("2024-02-03") == doc)
    check("read_day of a missing day is None", bw.read_day("2024-02-04") is None)
    check("no temporary file is left behind", not list(cfg.BULK_RAW_DIR.glob("*.tmp")))

    # ── imported_at default ────────────────────────────────────────────────────
    plan_b, samples_b = _day(date="2024-02-04")
    bw.write_day(plan_b, samples_b)
    stamp = bw.read_day("2024-02-04")["imported_at"]
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
          bw.read_day("2024-02-03")["source_files"] == sorted([H1, H2]) and bw.read_day("2024-02-03")["sections"]["intraday"]["heart_rate"]["count"] == 4)
    kept_state = _tree(cfg.BULK_RAW_DIR)
    check("day_status: fewer files than stored is smaller", bw.day_status("2024-02-03", [H1]) == "smaller")
    check("fewer files (a partial import) never replaces a fuller day", bw.write_day(plan, samples) == bw.KEPT)
    check("... and the file stays as it was", _tree(cfg.BULK_RAW_DIR) == kept_state)
    other_plan, other_samples = _day(hashes=(H1, H3))
    check("a different set that is neither smaller nor larger (H1+H3 against H1+H2) is kept as well",
          bw.day_status("2024-02-03", [H1, H3]) == "smaller" and bw.write_day(other_plan, other_samples) == bw.KEPT
          and _tree(cfg.BULK_RAW_DIR) == kept_state)

    # ── Schema version ─────────────────────────────────────────────────────────
    old = dict(bw.read_day("2024-02-03"))
    old["schema_version"] = 0
    day_file.write_text(json.dumps(old), encoding="utf-8")
    check("day_status: same files but an older schema is an update", bw.day_status("2024-02-03", [H1, H2]) == "update")
    check("same files, older schema: rewritten with the current schema", bw.write_day(plan2, samples2) == bw.WRITTEN
          and bw.read_day("2024-02-03")["schema_version"] == bw.BULK_SCHEMA_VERSION)
    newer = dict(bw.read_day("2024-02-03"))
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
              and bw.read_day("2024-02-03")["source_files"] == [H1])

    # ── Atomic, durable ────────────────────────────────────────────────────────
    plan_c, samples_c = _day(date="2024-02-05")
    synced = []
    real_fsync = os.fsync

    def _spy(fd):
        synced.append(fd)
        return real_fsync(fd)

    with patch.object(bw.os, "fsync", _spy):
        check("a day file is flushed to disk (fsync on the write handle)", bw.write_day(plan_c, samples_c) == bw.WRITTEN and len(synced) == 1)

    good = bw.read_day("2024-02-03")
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
          and bw.read_day("../x") is None and bw.day_status("nonsense", [H1]) == "new")
    check("dates that look like dates but are none (month 13, February 30) are refused",
          bw.write_day(*_day(date="2024-13-01")) == bw.FAILED and bw.write_day(*_day(date="2024-02-30")) == bw.FAILED
          and bw.read_day("2024-02-30") is None)
    pu, su = _day(date="2024-02-13")
    check("source files are stored sorted whatever order they come in",
          bw.write_day(pu, nz.DaySamples("2024-02-13", su.values, [H3, H1, H2], 0, 0)) == bw.WRITTEN
          and bw.read_day("2024-02-13")["source_files"] == sorted([H1, H2, H3]))
    pt, st = _day(date="2024-03-31", offsets=(1.0, 2.0), dst=True, source="neighbours")
    bw.write_day(pt, st)
    tday = bw.read_day("2024-03-31")
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
              and bw.read_day("2024-02-10") is not None)
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
    d2 = bw.read_day("2024-03-02")
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

# ── Ist-Stand, register finding F-1 (v1.7.6): a day file that cannot be READ counts as new ──────────
# read_day() answers None both for a damaged file (ValueError) and for a file that cannot be read for
# an I/O reason (OSError, e.g. a lock); day_status() turns None into "new". For a damaged file the new
# write is the repair and is wanted. For an unreadable but fine file the same path could replace a
# fuller stored day by a smaller one, against the rule "a day is never replaced by a smaller stand".
# Practically small (a lock that stops the read usually stops os.replace too, which is retried and
# then reported as failed), never observed. Pinned as it is today and NOT fixed: the day the
# behaviour is changed, the checks marked F-1 must be changed with it.
with _isolated_log_env("bulk_writer_f1") as base:
    _day_file = cfg.BULK_RAW_DIR / "garmin_bulk_2024-02-03.json"
    _plan2, _samples2 = _day(hashes=(H1, H2), values=[[1706950800000, 61], [1706950860000, 62], [1706950920000, 200], [1706950980000, 70]])
    bw.write_day(_plan2, _samples2, imported_at="2026-10-18T09:00:00")
    _fuller = _day_file.read_bytes()
    _real_read_text = Path.read_text

    def _locked(self, *a, **k):
        if self == _day_file:
            raise PermissionError("locked by another process")
        return _real_read_text(self, *a, **k)

    _small_plan, _small_samples = _day(hashes=(H1,))
    check("F-1 baseline: a readable fuller day is kept against a smaller stand", bw.write_day(_small_plan, _small_samples) == bw.KEPT)
    with patch.object(Path, "read_text", _locked):
        check("F-1 (Ist-Stand): a day file that cannot be read for an I/O reason is answered like a missing one: read_day gives None",
              bw.read_day("2024-02-03") is None)
        check("F-1 (Ist-Stand): ... and day_status turns that into 'new' (not 'smaller')", bw.day_status("2024-02-03", [H1]) == "new")
        check("F-1 (Ist-Stand): ... so a smaller stand is written over the fuller day", bw.write_day(_small_plan, _small_samples) == bw.WRITTEN
              and _day_file.read_bytes() != _fuller)
    _day_file.write_bytes(_fuller)
    check("F-1 baseline: with the fuller day back in place the smaller stand is kept again", bw.write_day(_small_plan, _small_samples) == bw.KEPT)
    _day_file.write_text("{ not json", encoding="utf-8")
    check("F-1: a damaged day file (ValueError) is answered with None, day_status 'new': the repair by a new write is wanted",
          bw.read_day("2024-02-03") is None and bw.day_status("2024-02-03", [H1]) == "new"
          and bw.write_day(_small_plan, _small_samples) == bw.WRITTEN and bw.read_day("2024-02-03")["source_files"] == [H1])

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
