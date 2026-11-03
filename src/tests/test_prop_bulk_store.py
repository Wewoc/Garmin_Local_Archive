#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_prop_bulk_store.py — property tests of garmin_bulk_writer (v1.7.6.11)

Run from the project folder:
    python tests/test_prop_bulk_store.py

The rules of REFERENCE_INVARIANTS.md "Bulk store" with generated inputs instead of hand-picked
examples (the hand-picked ones stay in test_bulk_writer.py):
  - a day (and an aggregates file) is replaced only by a fuller one: over ANY sequence of writes
    the set of source files in the stored file never shrinks; "kept"/"unchanged"/"failed" touch
    not one byte
  - the one comparison rule (_compare), against an oracle written as set algebra
  - the writers never raise and leave nothing but valid files behind, whatever they are handed
  - files of another archive (mirror import) are taken over by the same rules, or refused
  - the names of a mirror container say what a file is, and nothing outside the store
  - originals are stored under the hash of their bytes only

Everything runs in isolated temp folders (gla_testenv); the examples are derived, not random
(prop_support.py). Findings are pinned at the end under "Findings".
"""

import hashlib
import json
import re
from pathlib import Path

from gla_testenv import cfg, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
from prop_support import prop, given, st, storage_is_outside, HASHES, DATES, JSON_VALUES

import garmin_bulk_normalizer as nz
import garmin_bulk_writer as bw

check("setup: hypothesis keeps its files in a temp folder, not in the working directory (no .hypothesis folder in the source tree)",
      storage_is_outside(Path.cwd()) and storage_is_outside(Path(__file__).parent.parent))

STATES = {bw.WRITTEN, bw.UNCHANGED, bw.KEPT, bw.FAILED}
SETS = st.sets(HASHES, max_size=5)


def _tree(root):
    """{relative path: bytes} of every file below root ({} if there is no folder)."""
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ══════════════════════════════════════════════════════════════════════════════
section("P1. the comparison rule — _compare")
# ══════════════════════════════════════════════════════════════════════════════

@prop("_compare: newer schema -> newer; same files -> unchanged/update; proper superset -> update; else smaller")
@given(SETS, st.integers(0, 4), SETS, st.integers(0, 4))
def _(old, stored_version, new, current_version):
    got = bw._compare(sorted(old), stored_version, sorted(new), current_version)
    if stored_version > current_version:
        want = "newer"
    elif old == new:
        want = "unchanged" if stored_version == current_version else "update"
    elif old < new:
        want = "update"
    else:
        want = "smaller"
    assert got == want, (got, want)


@prop("_compare: an update never loses a source file of the stored day")
@given(SETS, st.integers(0, 4), SETS, st.integers(0, 4))
def _(old, stored_version, new, current_version):
    if bw._compare(sorted(old), stored_version, sorted(new), current_version) == "update":
        assert old <= new


@prop("_compare: the order and duplicates in the two lists do not matter")
@given(SETS, st.integers(0, 3), SETS, st.integers(0, 3), st.randoms(use_true_random=False))
def _(old, stored_version, new, current_version, rnd):
    a, b = sorted(old), sorted(new)
    shuffled_a, shuffled_b = a + a[:1], b + b[:1]
    rnd.shuffle(shuffled_a)
    rnd.shuffle(shuffled_b)
    assert bw._compare(a, stored_version, b, current_version) == bw._compare(shuffled_a, stored_version, shuffled_b, current_version)


@prop("_valid_date: a day is a real calendar day written with ASCII digits only")
@given(st.text(max_size=12) | DATES | st.from_regex(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", fullmatch=True))
def _(text):
    if bw._valid_date(text):
        assert text.isascii() and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text)
        import datetime
        assert datetime.date.fromisoformat(text).isoformat() == text


@prop("_valid_date: every real day of the supported years is valid")
@given(DATES)
def _(text):
    assert bw._valid_date(text)


# ══════════════════════════════════════════════════════════════════════════════
section("P2. a day is replaced only by a fuller one — sequences of writes on disk")
# ══════════════════════════════════════════════════════════════════════════════

STEPS = st.lists(st.sets(HASHES, min_size=1, max_size=4), min_size=1, max_size=6)
OUTCOME_OF_STATUS = {"new": bw.WRITTEN, "update": bw.WRITTEN, "unchanged": bw.UNCHANGED,
                     "smaller": bw.KEPT, "newer": bw.KEPT}


@prop("write_aggregates: over any sequence of writes the stored source files never shrink and nothing else is touched", examples=40)
@given(DATES, STEPS)
def _(date, steps):
    with _isolated_log_env("prop_agg"):
        stored, winner = set(), None
        for i, files in enumerate(steps):
            before = _tree(cfg.BULK_AGG_DIR)
            status = bw.aggregates_status(date, sorted(files))
            got = bw.write_aggregates(date, {"write": i}, sorted(files), imported_at="2026-01-01T00:00:00")
            assert got == OUTCOME_OF_STATUS[status], (got, status)
            doc = bw.read_aggregates(date)
            now = set(doc["source_files"])
            assert now >= stored, "the stored set shrank"
            if got != bw.WRITTEN:
                assert _tree(cfg.BULK_AGG_DIR) == before, f"{got} changed a byte"
            else:
                assert now == files and (not stored or now > stored)
                winner = i
            assert doc["aggregates"] == {"write": winner}, "the stored payload is not the payload of the last write that won"
            stored = now
        assert not list(cfg.BULK_AGG_DIR.glob("*.tmp"))


def _day_of(date, files):
    n = len(files) + 1
    values = [[1706950800000 + k * 1000, 60 + k] for k in range(n)]
    plan = nz.DayPlan(date, 1706914800, 1707001200, 1.0, 1.0, False, "prev_day_end")
    return plan, nz.DaySamples(date, values, sorted(files), 0, 0)


@prop("write_day: over any sequence of writes the stored source files never shrink and nothing else is touched", examples=40)
@given(DATES, STEPS)
def _(date, steps):
    with _isolated_log_env("prop_day"):
        stored, winner_files = set(), None
        for files in steps:
            before = _tree(cfg.BULK_RAW_DIR)
            status = bw.day_status(date, sorted(files))
            plan, samples = _day_of(date, files)
            got = bw.write_day(plan, samples, imported_at="2026-01-01T00:00:00")
            assert got == OUTCOME_OF_STATUS[status], (got, status)
            doc = bw._load_day(date)[1]
            now = set(doc["source_files"])
            assert now >= stored
            if got != bw.WRITTEN:
                assert _tree(cfg.BULK_RAW_DIR) == before
            else:
                assert now == files
                winner_files = files
            assert doc["sections"]["intraday"]["heart_rate"]["count"] == len(winner_files) + 1
            stored = now
        assert not list(cfg.BULK_RAW_DIR.glob("*.tmp"))


@prop("a stored day of an older schema is rewritten by the same files; of a newer schema it never is", examples=30)
@given(DATES, st.sets(HASHES, min_size=1, max_size=3), st.integers(0, 3))
def _(date, files, delta):
    with _isolated_log_env("prop_schema"):
        plan, samples = _day_of(date, files)
        assert bw.write_day(plan, samples) == bw.WRITTEN
        path = cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{date}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["schema_version"] = bw.BULK_SCHEMA_VERSION - 1 if delta == 0 else bw.BULK_SCHEMA_VERSION + delta
        path.write_text(json.dumps(doc), encoding="utf-8")
        before = path.read_bytes()
        got = bw.write_day(plan, samples)
        if delta == 0:
            assert got == bw.WRITTEN and json.loads(path.read_text(encoding="utf-8"))["schema_version"] == bw.BULK_SCHEMA_VERSION
        else:
            assert got == bw.KEPT and path.read_bytes() == before


# ══════════════════════════════════════════════════════════════════════════════
section("P3. the writers never raise and leave nothing but valid files")
# ══════════════════════════════════════════════════════════════════════════════

ANY_FILES = st.lists(st.one_of(HASHES, st.text(max_size=10), st.integers(), st.none()), max_size=4) | JSON_VALUES
ANY_DATE = DATES | st.text(max_size=12) | st.none() | st.integers()


@prop("write_aggregates: whatever it is handed, one of four answers; only a valid file for a valid day is left behind", examples=80)
@given(ANY_DATE, JSON_VALUES | st.fixed_dictionaries({"date": DATES, "a": st.just(1)}), ANY_FILES)
def _(date, aggregates, files):
    with _isolated_log_env("prop_agg_junk"):
        got = bw.write_aggregates(date, aggregates, files)
        assert got in STATES
        left = _tree(cfg.BULK_AGG_DIR)
        if got in (bw.FAILED, bw.KEPT, bw.UNCHANGED):
            assert not left, "a refused write left a file"
        else:
            assert bw._valid_date(date) and isinstance(aggregates, dict) and aggregates
            assert aggregates.get("date", date) == date, "aggregates dated another day were stored under this day"
            assert isinstance(files, (list, tuple)) and files and all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in files)
            assert list(left) == [f"{cfg.BULK_AGG_FILE_PREFIX}{date}.json"]
            doc = json.loads(next(iter(left.values())).decode("utf-8"))
            assert doc["aggregates"] == aggregates and doc["source_files"] == sorted(files) and doc["date"] == date


@prop("write_day: a day that is not well formed is refused and nothing is written", examples=80)
@given(ANY_DATE, ANY_DATE, JSON_VALUES, ANY_FILES)
def _(plan_date, samples_date, values, files):
    with _isolated_log_env("prop_day_junk"):
        plan = nz.DayPlan(plan_date, 0, 1, 1.0, 1.0, False, "prev_day_end")
        samples = nz.DaySamples(samples_date, values, files, 0, 0)
        got = bw.write_day(plan, samples)
        assert got in STATES
        left = _tree(cfg.BULK_RAW_DIR)
        if got != bw.WRITTEN:
            assert not left
        else:
            doc = json.loads(next(iter(left.values())).decode("utf-8"))
            assert plan_date == samples_date == doc["date"] and bw._values_problem(doc["sections"]["intraday"]["heart_rate"]["values"]) is None


@prop("_values_problem: a list accepted is strictly ascending pairs of integers in range", examples=100)
@given(st.lists(st.tuples(st.integers(-5, 10**13), st.integers(-3, 300)).map(list), max_size=6) | JSON_VALUES)
def _(values):
    if bw._values_problem(values) is None:
        assert isinstance(values, list) and values
        assert all(len(v) == 2 and v[0] > 0 and 1 <= v[1] <= 254 for v in values)
        assert all(a[0] < b[0] for a, b in zip(values, values[1:]))


# ══════════════════════════════════════════════════════════════════════════════
section("P4. files of another archive (mirror import) — the same rules, or refused")
# ══════════════════════════════════════════════════════════════════════════════

_GOOD_VALUES = [[1706950800000, 61], [1706950860000, 62]]


@st.composite
def foreign_files(draw):
    kind = draw(st.sampled_from(["aggregates", "intraday", "aggregates", "intraday", "other"]))
    date = draw(DATES)
    doc = {
        "date": draw(st.sampled_from([date, date, date, date, "2000-01-01"])),
        "origin": draw(st.sampled_from(["gdpr_export", "gdpr_export", "gdpr_export", "api"])),
        "schema_version": draw(st.sampled_from([1, 1, 1, 2, 2, 3, 0, -1, "1", None, True])),
        "source_files": draw(st.lists(HASHES, min_size=1, max_size=3) | st.lists(HASHES, min_size=1, max_size=3)
                             | st.sampled_from([[], ["x"], None])),
        "aggregates": draw(st.sampled_from([{"a": 1}, {"a": 1}, {"a": 1}, {"a": 1, "date": date}, {"a": 1, "date": "2000-01-01"},
                                            {}, None, [1]])),
        "utc_offset_hours": draw(st.sampled_from([1.0, 1.0, 1.0, None, "1", True])),
        "sections": draw(st.sampled_from([
            {"intraday": {"heart_rate": {"values": _GOOD_VALUES}}}, {"intraday": {"heart_rate": {"values": _GOOD_VALUES}}},
            {"intraday": {"heart_rate": {"values": [[1706950800000, 61], [1706950800000, 62]]}}},
            {"intraday": {}}, {}, None])),
    }
    data = json.dumps(doc).encode("utf-8") if draw(st.integers(0, 9)) else draw(st.binary(max_size=30))
    return kind, date, data


def _foreign_ok(kind, date, data):
    """An independent statement of what a file of another archive must look like (REFERENCE_INVARIANTS, mirror of the bulk store)."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except ValueError:
        return False
    if kind not in ("intraday", "aggregates") or not isinstance(doc, dict):
        return False
    version, files = doc.get("schema_version"), doc.get("source_files")
    if doc.get("date") != date or doc.get("origin") != "gdpr_export":
        return False
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return False
    if not (isinstance(files, list) and files and all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in files)):
        return False
    if kind == "aggregates":
        aggregates = doc.get("aggregates")
        return isinstance(aggregates, dict) and bool(aggregates) and aggregates.get("date", date) == date
    offset = doc.get("utc_offset_hours")
    values = (((doc.get("sections") or {}).get("intraday") or {}).get("heart_rate") or {}).get("values") if isinstance(doc.get("sections"), dict) else None
    return (isinstance(offset, (int, float)) and not isinstance(offset, bool)
            and isinstance(values, list) and bool(values) and bw._values_problem(values) is None)


@prop("import_day_file: a file is taken over exactly when it passes the rules, with exactly its bytes; a refused one leaves nothing", examples=150)
@given(foreign_files())
def _(case):
    kind, date, data = case
    with _isolated_log_env("prop_import"):
        got = bw.import_day_file(kind, date, data)
        assert got in STATES
        folder = cfg.BULK_RAW_DIR if kind == "intraday" else cfg.BULK_AGG_DIR
        left = _tree(folder)
        ok = _foreign_ok(kind, date, data)
        if not ok:
            assert got == bw.FAILED and not left, (got, "a file that breaks the rules was not refused")
        else:
            known = bw.BULK_SCHEMA_VERSION if kind == "intraday" else bw.AGG_SCHEMA_VERSION
            if json.loads(data.decode("utf-8"))["schema_version"] > known:
                assert got == bw.KEPT and not left, "a file of a newer schema was stored"
            else:
                assert got == bw.WRITTEN and list(left.values()) == [data]
                assert bw.import_day_file(kind, date, data) == bw.UNCHANGED, "the same file twice must not be written twice"
        other_folder = cfg.BULK_AGG_DIR if kind == "intraday" else cfg.BULK_RAW_DIR
        assert not _tree(other_folder) and not _tree(cfg.BULK_SOURCE_DIR), "something landed in another folder"
        other_folder = cfg.BULK_AGG_DIR if kind == "intraday" else cfg.BULK_RAW_DIR
        assert not _tree(other_folder) and not _tree(cfg.BULK_SOURCE_DIR), "something landed in another folder"


@prop("import_day_file: a fuller file replaces the stored one, a smaller or different one never does", examples=40)
@given(DATES, st.sets(HASHES, min_size=1, max_size=3), st.sets(HASHES, min_size=1, max_size=3))
def _(date, stored_files, incoming_files):
    with _isolated_log_env("prop_import_cmp"):
        assert bw.write_aggregates(date, {"stored": 1}, sorted(stored_files)) == bw.WRITTEN
        path = cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{date}.json"
        before = path.read_bytes()
        data = json.dumps({"date": date, "origin": bw.ORIGIN, "schema_version": bw.AGG_SCHEMA_VERSION,
                           "source_files": sorted(incoming_files), "aggregates": {"incoming": 1}}).encode("utf-8")
        got = bw.import_day_file("aggregates", date, data)
        if incoming_files > stored_files:
            assert got == bw.WRITTEN and path.read_bytes() == data
        elif incoming_files == stored_files:
            assert got == bw.UNCHANGED and path.read_bytes() == before
        else:
            assert got == bw.KEPT and path.read_bytes() == before


# ══════════════════════════════════════════════════════════════════════════════
section("P5. container names — what a file is, nothing outside the store")
# ══════════════════════════════════════════════════════════════════════════════

def _rebuild(described):
    """The container path a description stands for (the inverse of describe_container_path)."""
    if described[0] == "intraday":
        return f"garmin_data/bulk/raw/{cfg.BULK_FILE_PREFIX}{described[1]}.json"
    if described[0] == "aggregates":
        return f"garmin_data/bulk/aggregates/{cfg.BULK_AGG_FILE_PREFIX}{described[1]}.json"
    return f"garmin_data/bulk/source/{described[1][:2]}/{described[1]}{described[2]}"


_VOCABULARY = ["garmin_data", "bulk", "raw", "aggregates", "source", "..", ".", "", "ab", "garmin_bulk_2024-02-03.json",
               "garmin_aggregates_2024-02-03.json", "x.json", "C:", "\\", "backup", "log"]
PATHS = (st.text(max_size=40)
         | st.lists(st.sampled_from(_VOCABULARY), max_size=6).map("/".join)
         # a valid file name one level too deep, or under a name that is no area: must not be taken for a day file
         | st.builds(lambda area, extra, date: "/".join(["garmin_data", "bulk", area, *extra,
                                                         f"{cfg.BULK_FILE_PREFIX if area == 'raw' else cfg.BULK_AGG_FILE_PREFIX}{date}.json"]),
                     st.sampled_from(["raw", "aggregates", "other"]), st.lists(st.sampled_from(["x", "..", "ab"]), max_size=2), DATES)
         | st.builds(lambda a, b, c: f"garmin_data/bulk/{a}/{b}/{c}", st.sampled_from(["raw", "aggregates", "source"]),
                     st.sampled_from(["ab", "00", ".."]), HASHES.map(lambda h: h + ".fit")))


@prop("describe_container_path: what it accepts is exactly one path inside bulk/ — no way up, no backslash, round trip", examples=150)
@given(PATHS)
def _(path):
    got = bw.describe_container_path(path)
    if got is not None:
        assert _rebuild(got) == path, "a different path would be written than the one named"
        assert ".." not in path.split("/") and "\\" not in path and "" not in path.split("/")
        assert path.startswith("garmin_data/bulk/")


@prop("describe_container_path: every name the store itself writes is recognised", examples=60)
@given(DATES, HASHES, st.sampled_from([".fit", ".json"]))
def _(date, file_hash, suffix):
    assert bw.describe_container_path(_rebuild(("intraday", date))) == ("intraday", date)
    assert bw.describe_container_path(_rebuild(("aggregates", date))) == ("aggregates", date)
    assert bw.describe_container_path(_rebuild(("original", file_hash, suffix))) == ("original", file_hash, suffix)


@prop("describe_container_path: anything that is not a string is nothing", examples=30)
@given(st.one_of(st.none(), st.integers(), st.binary(max_size=10), st.lists(st.text(max_size=5), max_size=3)))
def _(path):
    assert bw.describe_container_path(path) is None


# ══════════════════════════════════════════════════════════════════════════════
section("P6. originals — stored under the hash of their bytes only")
# ══════════════════════════════════════════════════════════════════════════════

@prop("store_original: only bytes under their own SHA-256 are stored; the file holds exactly those bytes", examples=60)
@given(st.binary(max_size=40), st.sampled_from(["own", "own", "other", "junk"]), st.sampled_from([".fit", ".json", ".txt", ""]))
def _(data, which, suffix):
    with _isolated_log_env("prop_orig"):
        own = hashlib.sha256(data).hexdigest()
        name = {"own": own, "other": hashlib.sha256(data + b"x").hexdigest(), "junk": own[:10] + "/../x"}[which]
        got = bw.store_original(name, data, suffix)
        left = _tree(cfg.BULK_SOURCE_DIR)
        if which == "own" and suffix in (".fit", ".json"):
            assert got == bw.WRITTEN and left == {f"{own[:2]}/{own}{suffix}": data}
            assert bw.store_original(name, data, suffix) == bw.PRESENT
            assert bw.original_present(own, len(data), suffix) and f"{own}{suffix}" in bw.list_originals()
        else:
            assert got == bw.FAILED and not left


# ══════════════════════════════════════════════════════════════════════════════
section("Findings of v1.7.6.11 (pinned as they are — the decision per finding is the maintainer's)")
# ══════════════════════════════════════════════════════════════════════════════

summary()
