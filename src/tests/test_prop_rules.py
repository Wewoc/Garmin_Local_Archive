#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_prop_rules.py — property tests of the decision rules of v1.7.6.x (v1.7.6.11)

Run from the project folder:
    python tests/test_prop_rules.py

Rules of REFERENCE_INVARIANTS.md with generated inputs; the hand-picked cases stay in the
tests of the modules:
  R1  resolved summary (garmin_writer._resolve): API data first, the export fills only what is
      missing or empty ("0" and "False" are values), nothing is invented, no input is changed
  R2  garmin_merge.merge_field: additive, never overwrites a non-empty value
  R3  quality labels: a worse label never replaces a better one (upsert, mirror delta), the
      markers that repairs set touch nothing but their own keys and keep the log checksum
  R4  race predictions on their own day (own_day_prediction, normalize)
  R5  export import: detect_kind, parse_day (resting heart rate, prediction, alert events)
  R6  the path guard of the mirror import
"""

import copy
import os
import posixpath
import re
from datetime import date, timedelta

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
from prop_support import prop, given, st, DATES, JSON_VALUES

import garmin_import as imp
import garmin_import_mirror as mirror
import garmin_merge as merge
import garmin_normalizer as nz
import garmin_quality as quality
import garmin_repair_predictions as rp
import garmin_writer as writer
from quality import _io as qio


def _raises(fn, *args):
    try:
        fn(*args)
    except Exception as e:                      # noqa: BLE001 - the type is the result
        return type(e).__name__
    return None


# ══════════════════════════════════════════════════════════════════════════════
section("R1. the resolved summary — API first, the export fills only what is empty")
# ══════════════════════════════════════════════════════════════════════════════

_EMPTY = [None, "", [], {}]
_SCALAR = st.one_of(st.none(), st.just(""), st.just(0), st.just(False), st.just([]), st.just({}),
                    st.integers(1, 99), st.text(min_size=1, max_size=4), st.just(0.0))
_SECTION = st.dictionaries(st.sampled_from(["a", "b", "c", "d"]), _SCALAR, max_size=4)
_ACTIVITIES = st.lists(st.fixed_dictionaries({"activityName": st.text(min_size=1, max_size=3)}), max_size=2)
_KEYS = ["user_summary", "stress", "sleep", "training_readiness", "health_status"]
_DAY = st.dictionaries(st.sampled_from(_KEYS), _SECTION | st.none(), max_size=4).flatmap(
    lambda d: _ACTIVITIES.map(lambda acts: {**d, "activities": acts} if acts else d))


def _is_empty(value):
    return value is None or value == "" or value == [] or value == {}


@prop("_resolve: whatever the API holds that is not empty stays as it is (a 0 and a False are values)", examples=200)
@given(_DAY, _DAY)
def _(api, export):
    resolved = writer._resolve(api, export)
    for key, value in api.items():
        if isinstance(value, dict) and value:
            for field, v in value.items():
                if not _is_empty(v):
                    assert resolved[key][field] == v and type(resolved[key][field]) is type(v), (key, field)
        elif value:
            assert resolved[key] == value


@prop("_resolve: the export fills a field the API lacks or holds empty, and nothing else changes", examples=200)
@given(_DAY, _DAY)
def _(api, export):
    resolved = writer._resolve(api, export)
    bulk = nz.normalize(copy.deepcopy(export), source="bulk")
    for key, value in bulk.items():
        if key not in api or not api[key]:
            assert resolved[key] == value or (key == "activities" and _is_empty(value)), key
        elif isinstance(api[key], dict) and isinstance(value, dict) and key != "activities":
            for field, v in value.items():
                if field not in api[key] or _is_empty(api[key][field]):
                    assert resolved[key][field] == v, (key, field)
    assert set(api) <= set(resolved) <= set(api) | set(bulk), "a key out of nowhere"


@prop("_resolve: neither the API data nor the export values are changed, and resolving twice gives the same day", examples=200)
@given(_DAY, _DAY)
def _(api, export):
    api_before, export_before = copy.deepcopy(api), copy.deepcopy(export)
    once = writer._resolve(api, export)
    assert api == api_before and export == export_before
    assert writer._resolve(once, export) == once


@prop("_resolve: with no API data the day is the export's day; with no export values it is the API's day", examples=100)
@given(_DAY)
def _(day):
    assert writer._resolve({}, day) == nz.normalize(copy.deepcopy(day), source="bulk") or not day
    assert writer._resolve(day, {}) == day


# ══════════════════════════════════════════════════════════════════════════════
section("R2. merge_field — additive, never overwrites")
# ══════════════════════════════════════════════════════════════════════════════

@prop("merge_field: a non-empty value is never overwritten; an empty one is filled; the input is not changed", examples=150)
@given(st.dictionaries(st.sampled_from(["a", "b", "c"]), JSON_VALUES, max_size=3), st.sampled_from(["a", "b", "c", "d"]), JSON_VALUES)
def _(raw, field, value):
    before = copy.deepcopy(raw)
    out = merge.merge_field(raw, field, value)
    assert raw == before
    for k in raw:
        if k != field:
            assert out[k] == raw[k]
    if raw.get(field):
        assert out[field] == raw[field]
    else:
        assert out[field] == value
    assert set(out) == set(raw) | {field}


@prop("merge_field: anything that is not a dict comes back as it is", examples=30)
@given(st.one_of(st.none(), st.integers(), st.text(max_size=5), st.lists(st.integers(), max_size=3)))
def _(raw):
    assert merge.merge_field(raw, "a", 1) is raw


# ══════════════════════════════════════════════════════════════════════════════
section("R3. quality labels — a worse label never replaces a better one")
# ══════════════════════════════════════════════════════════════════════════════

_LABELS = ["high", "standard", "failed"]
_RANK = {"high": 2, "standard": 1, "failed": 0}


@prop("is_downgrade: a strict order on the labels, consistent with the ranks; an unknown label ranks as the lowest", examples=80)
@given(st.sampled_from(_LABELS + ["bogus", None]), st.sampled_from(_LABELS + ["bogus", None]), st.sampled_from(_LABELS + ["bogus", None]))
def _(a, b, c):
    rank = lambda x: _RANK.get(x, 0)  # noqa: E731 - the oracle
    assert quality.is_downgrade(a, b) == (rank(a) < rank(b))
    assert not quality.is_downgrade(a, a)
    assert not (quality.is_downgrade(a, b) and quality.is_downgrade(b, a))
    if quality.is_downgrade(a, b) and quality.is_downgrade(b, c):
        assert quality.is_downgrade(a, c)


_UPSERT_STEPS = st.lists(st.tuples(st.integers(0, 2), st.sampled_from(_LABELS), st.booleans()), min_size=1, max_size=10)


@prop("_upsert_quality: over any sequence of writes the label of a day never gets worse, and a blocked write changes nothing", examples=150)
@given(_UPSERT_STEPS)
def _(steps):
    data = {"days": []}
    base = date(2024, 5, 1)
    for step, (offset, label, prev_high) in enumerate(steps):
        day = base + timedelta(days=offset)
        entry = next((e for e in data["days"] if e["date"] == day.isoformat()), None)
        before = copy.deepcopy(entry)
        quality._upsert_quality(data, day, label, f"step{step}", written=bool(step % 2), source=f"src{step}", prev_high=prev_high)
        entry = next(e for e in data["days"] if e["date"] == day.isoformat())
        if before is not None and _RANK[label] < _RANK[before["quality"]]:
            assert entry == before, "a blocked downgrade changed the entry"
        else:                                    # a new day, an equal or a better label: the write is taken as a whole
            assert (entry["quality"], entry["reason"], entry["write"], entry["source"]) == (label, f"step{step}", bool(step % 2), f"src{step}")
            assert entry["last_checked"] == date.today().isoformat()
            if before is not None:
                assert entry.get("attempts", 0) >= before.get("attempts", 0)
    assert len({e["date"] for e in data["days"]}) == len(data["days"]), "one entry per day"


_QENTRY = st.fixed_dictionaries({"date": DATES, "quality": st.sampled_from(_LABELS + ["bogus"]), "source": st.sampled_from(["api", "bulk"]),
                                 "write": st.sampled_from([True, False, None])})
_QLOG = st.lists(_QENTRY, max_size=6, unique_by=lambda e: e["date"]).map(lambda days: {"days": days})


@prop("mirror delta: a day is taken over only when the other archive has none or a strictly better one", examples=150)
@given(_QLOG, _QLOG)
def _(src, dst):
    to_copy, skipped = mirror._analyse_raw_delta(src, dst)
    by_dst = {e["date"]: e for e in dst["days"]}
    rank = lambda e: _RANK.get(e["quality"], 0)  # noqa: E731 - the oracle
    assert len(to_copy) + skipped == len(src["days"])
    for e in src["days"]:
        want = e["date"] not in by_dst or rank(e) > rank(by_dst[e["date"]])
        assert (e in to_copy) == want, e


def _entry_pool():
    return st.lists(st.fixed_dictionaries({"date": DATES, "quality": st.sampled_from(_LABELS), "source": st.sampled_from(["api", "bulk"]),
                                           "write": st.booleans(), "last_checked": st.sampled_from(["2020-01-01", None]),
                                           "fields": st.sampled_from([{"race_predictions": "medium", "steps": "high"}, None, 5]),
                                           "bulk": st.sampled_from([{"intraday": "2020-01-01"}, None, "x"])}),
                    max_size=6, unique_by=lambda e: e["date"])


@st.composite
def _entries_and_days(draw):
    """Log entries, and days to mark: mostly days that have an entry, some that have none."""
    entries = draw(_entry_pool())
    known = [e["date"] for e in entries]
    pool = st.sampled_from(known) | DATES if known else DATES
    return entries, draw(st.lists(pool, max_size=5))


@prop("the markers of the repairs and imports touch nothing but their own keys, never create an entry and keep the log checksum", examples=150)
@given(_entries_and_days(), st.sampled_from(["touch", "intraday", "aggregates", "labels"]),
       st.sampled_from(["high", "medium", "low", "failed", "bogus"]))
def _(entries_days, which, label):
    entries, days = entries_days
    data = {"days": copy.deepcopy(entries)}
    before = copy.deepcopy(data)
    checksum = qio._compute_checksum(data)
    if which == "touch":
        n = quality.touch_last_checked(data, days)
        allowed = {"last_checked"}
    elif which == "labels":
        n = quality.record_field_labels(data, {d: label for d in days}, "race_predictions")["set"]
        allowed = {"fields"}
    else:
        n = (quality.record_bulk_intraday if which == "intraday" else quality.record_bulk_aggregates)(data, days)
        allowed = {"bulk", "last_checked"}
    assert [e["date"] for e in data["days"]] == [e["date"] for e in before["days"]], "an entry was created or lost"
    assert qio._compute_checksum(data) == checksum, "the log checksum changed"
    changed = 0
    for new, old in zip(data["days"], before["days"]):
        diff = {k for k in set(new) | set(old) if new.get(k, "<absent>") != old.get(k, "<absent>")}
        assert diff <= allowed, (which, diff)
        if which == "labels" and diff:
            assert new["fields"]["race_predictions"] == label and set(new["fields"]) >= set(old["fields"])
            assert all(new["fields"][k] == v for k, v in old["fields"].items() if k != "race_predictions"), "another field label changed"
        if which in ("intraday", "aggregates") and "bulk" in diff and isinstance(old.get("bulk"), dict):
            assert all(new["bulk"].get(k) == v for k, v in old["bulk"].items() if k != which), "another bulk mark was lost"
        changed += bool(diff) or (which in ("touch", "intraday", "aggregates") and new["date"] in set(days))
    assert n >= 0 and (which == "labels" or n == len([e for e in data["days"] if e["date"] in set(days)]))


# ══════════════════════════════════════════════════════════════════════════════
section("R4. a race prediction stays only on its own day")
# ══════════════════════════════════════════════════════════════════════════════

_PRED = st.dictionaries(st.sampled_from(["calendarDate", "time5K", "time10K"]),
                        st.one_of(DATES, st.integers(0, 9999), st.none()), max_size=3)
_RAW = st.fixed_dictionaries({"date": DATES}, optional={"race_predictions": _PRED | st.none() | st.integers() | st.just([]),
                                                        "sleep": st.just({"x": 1})})


@prop("own_day_prediction: kept only when calendarDate is exactly the day; a dropped one is returned; the input is never changed", examples=200)
@given(_RAW, DATES)
def _(raw, day):
    before = copy.deepcopy(raw)
    out, dropped = nz.own_day_prediction(raw, day)
    assert raw == before
    pred = raw.get("race_predictions")
    judged = isinstance(pred, dict) and bool(pred)
    if not judged or pred.get("calendarDate") == day:
        assert out is raw and dropped is None
    else:
        assert dropped == pred and "race_predictions" not in out and out == {k: v for k, v in raw.items() if k != "race_predictions"}


@prop("normalize(api): the same rule with the day's own date; a dict without a usable date is not judged", examples=200)
@given(_RAW, st.sampled_from(["ok", "ok", "no_date", "bad_date"]))
def _(raw, mode):
    raw = dict(raw)
    if mode == "no_date":
        raw.pop("date")
    elif mode == "bad_date":
        raw["date"] = raw["date"].replace("-", "/")
    before = copy.deepcopy(raw)
    out = nz.normalize(raw, source="api")
    assert raw == before, "normalize(api) changed its argument"
    if mode != "ok":
        assert out is raw
    else:
        assert out == nz.own_day_prediction(raw, raw["date"])[0]
        assert nz.normalize(out, source="api") == out, "applying the rule twice changes the day"


@prop("normalize(api): a value that is no dict gives an empty day", examples=30)
@given(st.one_of(st.none(), st.integers(), st.text(max_size=4), st.lists(st.integers(), max_size=2)))
def _(raw):
    assert nz.normalize(raw, source="api") == {"date": "unknown"}


@prop("_is_iso_date: a real calendar day, ASCII digits, written YYYY-MM-DD", examples=100)
@given(DATES | st.text(max_size=12) | st.from_regex(r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}", fullmatch=True))
def _(text):
    try:
        want = text.isascii() and date.fromisoformat(text).isoformat() == text
    except ValueError:
        want = False
    assert nz._is_iso_date(text) == want


# ══════════════════════════════════════════════════════════════════════════════
section("R5. export import — detect_kind and parse_day")
# ══════════════════════════════════════════════════════════════════════════════

_KIND_ENTRIES = {
    "activities": {"summarizedActivitiesExport": []},
    "uds": {"totalSteps": 1, "uuid": "u"},
    "sleep": {"deepSleepSeconds": 1},
    "readiness": {"acwrFactorPercent": 1},
    "health_status": {"metrics": [], "outliersCount": 0},
    "alert_events": {"abnormalHrEventGMT": "x"},
    "race_predictions": {"raceTime5K": 1},
}
_ENTRY = st.one_of(st.sampled_from(sorted(_KIND_ENTRIES)).map(lambda k: (k, _KIND_ENTRIES[k])),
                   JSON_VALUES.map(lambda v: (None, v)))


@prop("detect_kind: any JSON gives a kind or nothing, never raises; two kinds in one file give nothing", examples=200)
@given(JSON_VALUES | st.lists(_ENTRY, max_size=5).map(lambda items: [e for _k, e in items]))
def _(data):
    got = imp.detect_kind(data)
    assert got is None or got in _KIND_ENTRIES
    if got is not None:
        assert isinstance(data, list) and any(isinstance(e, dict) for e in data)


@prop("detect_kind: the kind is the one kind of the entries, whatever their order", examples=150)
@given(st.lists(_ENTRY, max_size=5), st.randoms(use_true_random=False))
def _(items, rnd):
    entries = [e for _k, e in items]
    kinds = {k for k, _e in items if k}
    # an entry of a generated JSON value may by chance also match a rule; only decided cases are judged
    if all(k for k, _e in items):
        want = next(iter(kinds)) if len(kinds) == 1 else None
        assert imp.detect_kind(entries) == want
        shuffled = list(entries)
        rnd.shuffle(shuffled)
        assert imp.detect_kind(shuffled) == want


def _kind_entries(kind, day):
    """One export entry of a kind with JSON of any shape in the fields the importer reads."""
    j = JSON_VALUES
    # allDayStress and the sleep seconds are of any shape too: a value of the wrong type counts as empty (F-24, v1.7.6.11.1)
    stress = j | st.fixed_dictionaries({"aggregatorList": st.lists(
        st.dictionaries(st.sampled_from(["averageStressLevel", "maxStressLevel", "stressDuration"]), j, max_size=3) | j, max_size=2)})
    seconds = j | st.integers(0, 40000) | st.floats(0, 40000, allow_nan=False, allow_infinity=False)
    if kind == "uds":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "uuid": st.just("u"), "totalSteps": j, "allDayStress": stress,
                                      "floorsAscendedInMeters": j, "restingHeartRate": j, "currentDayRestingHeartRate": j})
    if kind == "sleep":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "deepSleepSeconds": seconds, "lightSleepSeconds": seconds,
                                      "remSleepSeconds": seconds})
    if kind == "readiness":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "acwrFactorPercent": j, "level": j, "score": j, "timestamp": j})
    if kind == "health_status":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "metrics": j, "outliersCount": j})
    if kind == "alert_events":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "abnormalHrEventGMT": j})
    if kind == "race_predictions":
        return st.fixed_dictionaries({"calendarDate": st.just(day), "raceTime5K": j, "raceTimeMarathon": j})
    return st.fixed_dictionaries({"summarizedActivitiesExport": st.lists(
        st.fixed_dictionaries({"startTimeLocal": st.just(1704067200000), "name": j, "activityType": j, "duration": j}), max_size=2)})


@st.composite
def export_files(draw):
    """A few parsed export files: [(label, [entry, ...])] — every entry an object, every field any JSON."""
    day = draw(DATES)
    kinds = draw(st.lists(st.sampled_from(sorted(_KIND_ENTRIES)), min_size=1, max_size=4))
    return [(f"f{i}", draw(st.lists(_kind_entries(k, day), min_size=1, max_size=2))) for i, k in enumerate(kinds)]


@prop("days_from_originals: JSON of any shape in the fields (allDayStress and the sleep seconds included, F-24) does not end the import", examples=100)
@given(export_files())
def _(files):
    days = list(imp.days_from_originals(files))
    for raw, entries in days:
        assert isinstance(raw, dict) and isinstance(entries, dict) and raw["date"]


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@prop("parse_day: a sleep second of the wrong type counts as empty, the total is the sum of the numbers, nothing raises (F-24)", examples=200)
@given(st.fixed_dictionaries({k: JSON_VALUES for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds")}), DATES)
def _(sleep, day):
    dto = imp.parse_day({"sleep": sleep}, day)["sleep"]["dailySleepDTO"]
    for k, v in sleep.items():
        assert dto[k] == v if _is_num(v) else dto[k] is None, k
        assert type(dto[k]) is type(v) if _is_num(v) else True
    nums = [sleep[k] for k in ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds") if _is_num(sleep[k])]
    assert dto["sleepTimeSeconds"] == (sum(nums) if nums else None)


@prop("parse_day: allDayStress of any shape does not raise; a stress block comes only from an object holding an aggregate object (F-24)", examples=200)
@given(JSON_VALUES | st.fixed_dictionaries({"aggregatorList": st.lists(JSON_VALUES, max_size=3)}), DATES)
def _(stress, day):
    out = imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": stress}}, day)
    assert out["user_summary"]["totalSteps"] == 5
    agg = stress.get("aggregatorList") if isinstance(stress, dict) else None
    has = isinstance(agg, list) and bool(agg) and isinstance(agg[0], dict)
    assert ("stress" in out) == has


_NUM = st.one_of(st.none(), st.integers(0, 5000), st.floats(0, 5000, allow_nan=False, allow_infinity=False))
_UDS = st.fixed_dictionaries({}, optional={"totalSteps": _NUM, "restingHeartRate": _NUM, "currentDayRestingHeartRate": _NUM,
                                           "minHeartRate": _NUM, "maxHeartRate": _NUM, "floorsAscendedInMeters": _NUM})


@prop("parse_day: the resting heart rate is the value of the day; an absent day value stays empty and never falls back to the average", examples=150)
@given(_UDS, DATES)
def _(uds, day):
    uds = {**uds, "totalSteps": 1}
    out = imp.parse_day({"uds": uds}, day)
    us = out["user_summary"]
    assert us["restingHeartRate"] == uds.get("currentDayRestingHeartRate")
    assert us["lastSevenDaysAvgRestingHeartRate"] == uds.get("restingHeartRate")
    assert "heart_rates" not in out and out["date"] == day


_PRED_ENTRY = st.dictionaries(st.sampled_from(["raceTime5K", "raceTime10K", "raceTimeHalf", "raceTimeMarathon", "userProfilePk", "deviceId", "timestamp", "calendarDate"]),
                              st.one_of(st.none(), st.integers(0, 99999), st.booleans(), st.text(max_size=5)), max_size=8)


@prop("parse_day: a prediction carries the day, the four times and nothing of the account or the device", examples=200)
@given(_PRED_ENTRY, DATES)
def _(entry, day):
    out = imp.parse_day({"race_predictions": entry}, day)
    pred = out.get("race_predictions")
    numbers = [entry.get(k) for k in ("raceTime5K", "raceTime10K", "raceTimeHalf", "raceTimeMarathon")]
    if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in numbers):
        assert pred is not None and pred["calendarDate"] == day
        assert set(pred) <= {"calendarDate", "time5K", "time10K", "timeHalfMarathon", "timeMarathon"}
    else:
        assert pred is None


_EVENT = st.fixed_dictionaries({"abnormalHrEventGMT": st.sampled_from(["2024-01-01T01:00:00.0", "2024-01-01T02:00:00.0", None]),
                                "text": st.sampled_from(["a", "b", "c"])})


@prop("parse_day: the alert events of a day come out in a fixed order, whatever order the files were read in", examples=100)
@given(st.lists(_EVENT, min_size=1, max_size=5), st.randoms(use_true_random=False), DATES)
def _(events, rnd, day):
    shuffled = list(events)
    rnd.shuffle(shuffled)
    assert imp.parse_day({"alert_events": events}, day) == imp.parse_day({"alert_events": shuffled}, day)


# ══════════════════════════════════════════════════════════════════════════════
section("R6. the path guard of the mirror import")
# ══════════════════════════════════════════════════════════════════════════════

_SEGMENTS = ["a", "b.json", "..", ".", "", "C:", "c:\\x", "\\", "../a", "garmin_data", "NUL", "x:y", "%2e%2e", " ", "a ", "...",
             "con.txt", "Com5", "lpt9.json", "aux.tar.gz", "NULL", "COM10", "COM0", "console", "nul_x", "x.nul"]
_REL = st.lists(st.sampled_from(_SEGMENTS), max_size=6).map("/".join) | st.text(alphabet="ab./\\:", max_size=12)
# the rule of F-24's neighbour F-23, written down again here without the module's helper: the part of a segment before
# the first dot, without trailing blanks, is CON, PRN, AUX, NUL, COM1-9 or LPT1-9 in any case
_DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


@prop("_safe_container_path: what it returns lies inside the base folder; a way up, an absolute path, a drive or a device name is refused", examples=250)
@given(_REL)
def _(rel):
    base = _TMPDIR / "prop_guard"
    base.mkdir(exist_ok=True)
    got = mirror._safe_container_path(base, rel)
    # "C:x" on the drive of the base folder is relative to the folder (pathlib), so the drive letter itself is no way out
    probe = rel[2:] if len(rel) >= 2 and rel[1] == ":" and rel[0].upper() == base.drive[:1].upper() and rel[2:3] not in ("/", "\\") else rel
    norm = posixpath.normpath(probe.replace("\\", "/")) if probe else "."
    way_out = norm == ".." or norm.startswith("../") or norm.startswith("/")
    # a stream or drive (":"), or a name Windows rewrites (blank, trailing space or dot): what the system makes of it
    # is its own affair, not judged here (a refusal is fail-closed anyway)
    segments = [s for s in probe.replace("\\", "/").split("/") if s not in ("", ".", "..")]
    colon = ":" in probe or any(s != s.strip() or s.endswith(".") for s in segments)
    device = any(_DEVICE.fullmatch(s.split(".", 1)[0].rstrip(" ")) for s in re.split(r"[\\/]", rel))
    if got is not None:
        assert got == base / rel
        assert not way_out, f"a way out was accepted: {rel!r}"
        assert not device, f"a device name was accepted: {rel!r}"
        # a name-wise check that does not ask the system (normpath, not abspath: a device name such as NUL would be mapped)
        assert os.path.commonpath([os.path.normpath(str(got)), os.path.normpath(str(base))]) == os.path.normpath(str(base))
    else:
        assert way_out or colon or device, f"a path inside the folder was refused: {rel!r}"


@prop("_safe_container_path: a plain relative path inside the folder is always accepted", examples=100)
@given(st.lists(st.sampled_from(["a", "b", "raw", "garmin_data", "x.json"]), min_size=1, max_size=5).map("/".join))
def _(rel):
    base = _TMPDIR / "prop_guard"
    base.mkdir(exist_ok=True)
    assert mirror._safe_container_path(base, rel) == base / rel


# ══════════════════════════════════════════════════════════════════════════════
section("R7. the prediction repair plan — date, never guess")
# ══════════════════════════════════════════════════════════════════════════════

_RP_DAYS = [f"2024-05-0{i}" for i in range(1, 7)]
_RP_TIMES = [{"time5K": 1200, "time10K": 2500}, {"time5K": 1210, "time10K": 2510}]


@st.composite
def rp_archives(draw):
    """{day: the race_predictions field of its raw file, or None for a day without the field}."""
    field = {}
    for d in _RP_DAYS:
        kind = draw(st.sampled_from(["none", "none", "own", "mis", "mis", "mis", "undated", "junk"]))
        if kind == "none":
            field[d] = None
        elif kind == "own":
            field[d] = {"calendarDate": d, **draw(st.sampled_from(_RP_TIMES))}
        elif kind == "mis":
            field[d] = {"calendarDate": draw(st.sampled_from(_RP_DAYS + ["2024-05-09", "2024-04-30"])), **draw(st.sampled_from(_RP_TIMES))}
        elif kind == "undated":
            field[d] = draw(st.sampled_from([{"time5K": 1}, {"calendarDate": "soon", "time5K": 1}, {"calendarDate": None, "time5K": 2}]))
        else:
            field[d] = draw(st.sampled_from(["x", 5, [1], {}]))
    return field


def _rp_plan(field):
    """find_candidates() of an archive written to a temp folder."""
    import json
    import shutil
    import tempfile
    from pathlib import Path
    folder = Path(tempfile.mkdtemp(prefix="prop_rp_", dir=_TMPDIR))
    try:
        for d, value in field.items():
            raw = {"date": d, "sleep": {"x": 1}}
            if value is not None:
                raw["race_predictions"] = value
            (folder / f"garmin_raw_{d}.json").write_text(json.dumps(raw), encoding="utf-8")
        return rp.find_candidates(folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _rp_usable(value):
    return value if isinstance(value, dict) and value else None


def _rp_apply(field, plan):
    after = dict(field)
    for d, p in plan["set"].items():
        after[d] = dict(p)
    for d in plan["remove"]:
        after[d] = None
    return after


@prop("repair plan: a day that already has its own prediction is never touched, whatever the others carry", examples=100)
@given(rp_archives())
def _(field):
    plan = _rp_plan(field)
    own = {d for d, v in field.items() if _rp_usable(v) and v.get("calendarDate") == d}
    assert plan["kept"] == len(own)
    touched = set(plan["set"]) | set(plan["remove"]) | set(plan["waiting"]) | set(plan["undated"]) | set(plan["replaced"])
    assert not (own & touched), own & touched
    assert not (set(plan["set"]) & set(plan["remove"]))


@prop("repair plan: a prediction is placed only on the existing day it is dated with, from copies that all agree; a removal is a misdated copy", examples=100)
@given(rp_archives())
def _(field):
    plan = _rp_plan(field)
    for target, prediction in plan["set"].items():
        assert target in field and prediction["calendarDate"] == target
        carriers = [v for d, v in field.items() if _rp_usable(v) and v.get("calendarDate") == target and d != target]
        assert carriers and all(c == prediction for c in carriers), "the placed prediction is not what every carrier holds"
    for d in plan["remove"]:
        value = _rp_usable(field[d])
        assert value is not None and value.get("calendarDate") != d and rp._valid_date(value.get("calendarDate"))
    for target in plan["conflict"]:
        group = [v for d, v in field.items() if _rp_usable(v) and v.get("calendarDate") == target and d != target]
        assert len({rp._canon(v) for v in group}) > 1 and target not in plan["set"]


@prop("repair plan: applying it loses no prediction that can be placed, changes nothing it did not name, and a second run finds nothing", examples=100)
@given(rp_archives())
def _(field):
    plan = _rp_plan(field)
    after = _rp_apply(field, plan)
    named = set(plan["set"]) | set(plan["remove"])
    for d in field:
        if d not in named:
            assert after[d] == field[d], f"{d} changed without being named"
    own_before = {d for d, v in field.items() if _rp_usable(v) and v.get("calendarDate") == d}
    for d in own_before:
        assert after[d] == field[d]
    # nothing placeable is lost: a removed copy lives on under its own date (or that day already had its own)
    for d in plan["remove"]:
        p = field[d]
        assert after[p["calendarDate"]] == p or p["calendarDate"] in own_before
    again = _rp_plan({d: v for d, v in after.items()})
    assert again["set"] == {} and again["remove"] == [], again


# ══════════════════════════════════════════════════════════════════════════════
section("Rules of v1.7.6.11.1 (F-23 and F-24: the former findings 3 and 4, pinned in v1.7.6.11, now rules)")
# ══════════════════════════════════════════════════════════════════════════════

# F-23 (finding 3 of v1.7.6.11): _safe_container_path() used to accept a Windows device name (NUL, CON, COM1, ...): it
# resolves "inside" the base folder, and where the returned path is a write destination (the context section:
# context_writer.write_file(dst_path, ...)) the data would go to the device and the import would count the file as copied.
# Now such a segment is refused on every platform; the caller stops the whole import (Fall 1, v1.7.4.3).
_guard_base = _TMPDIR / "prop_guard_rules"
_guard_base.mkdir(exist_ok=True)
check("F-23: a device name (NUL, CON, COM1, LPT1, AUX, PRN, any case, with an extension, trailing dot or blank) is refused",
      all(mirror._safe_container_path(_guard_base, rel) is None
          for rel in ("NUL", "context_data/NUL", "context_data/CON", "COM1", "nul", "Com1.txt", "context_data\\aux.json",
                      "lpt9", "PRN.tar.gz", "CONIN$", "CONOUT$", "NUL.", "NUL ", "a/nul /b", "COM\u00b9", "COM\u00b2", "COM\u00b3",
                      "x/LPT\u00b9.json", "LPT\u00b2", "x/LPT\u00b3.json", "com9", "COM5.x", "lpt5")))
check("F-23: ... a name that only contains or resembles one is accepted (NULL, COM10, COM0, console, nul_x, x.nul, ambient)",
      all(mirror._safe_container_path(_guard_base, rel) == _guard_base / rel
          for rel in ("NULL", "COM10", "COM0", "console.json", "nul_x", "x.nul", "context_data/ambient.json", "a/auxiliary", "LPT")))
check("F-23: ... a way up and an absolute path are still refused",
      all(mirror._safe_container_path(_guard_base, rel) is None for rel in ("../x", "a/../../x", "/x")))
if os.name == "nt":
    check("F-23: ... and so are a drive and a stream (x:y)",
          all(mirror._safe_container_path(_guard_base, rel) is None for rel in ("context_data/x:y", "C:\\x")))
else:
    from support import skip
    skip("F-23: a drive and a stream as container paths", "Windows only")
_ctx = mirror._analyse_context_delta_container
_src = mirror._analyse_source_delta_container
check("F-23: both container analyses stop with the path error on a device name, and still pass a plain list on",
      _raises(_ctx, ["context_data/NUL"], _guard_base) == "_PathTraversalError"
      and _raises(_src, ["garmin_data/source/COM3.json"], _guard_base) == "_PathTraversalError"
      and _ctx(["context_data/a.json"], _guard_base) == ["context_data/a.json"]
      and _src(["garmin_data/source/a.json"], _guard_base) == ["garmin_data/source/a.json"])

# F-24 (finding 4 of v1.7.6.11): parse_day() used to raise when the sleep seconds were not numbers (_total_sleep: sum of a
# list / string -> TypeError) or when allDayStress was no object / its first aggregate no object (.get on a bool, str or
# list -> AttributeError); the exception ended the iteration of load_bulk() and the days after the bad one were not
# imported. Now a value of the wrong type counts as empty (None, precedent _meters_to_floors) and the day is kept; only
# int and float are numbers ("3600" as text and True are not). One log line per day names the fields, never a value.
_good_uds = {"calendarDate": "2024-03-01", "uuid": "u", "totalSteps": 5}


def _sleep_dto(sleep):
    return imp.parse_day({"sleep": sleep}, "2024-03-01")["sleep"]["dailySleepDTO"]


_dto = _sleep_dto({"deepSleepSeconds": "3600", "lightSleepSeconds": 1800, "remSleepSeconds": [1], "awakeSleepSeconds": True})
check("F-24: sleep seconds of the wrong type (text, list, bool) count as empty; the total is made of the numbers",
      _dto == {"sleepTimeSeconds": 1800, "deepSleepSeconds": None, "lightSleepSeconds": 1800,
               "remSleepSeconds": None, "awakeSleepSeconds": None})
check("F-24: ... no number at all gives an empty total; 0 and a float are numbers",
      _sleep_dto({"deepSleepSeconds": {"a": 1}, "remSleepSeconds": False})["sleepTimeSeconds"] is None
      and _sleep_dto({"deepSleepSeconds": 0, "lightSleepSeconds": 90.5})["sleepTimeSeconds"] == 90.5
      and _sleep_dto({"deepSleepSeconds": 0})["sleepTimeSeconds"] == 0)
check("F-24: ... numbers, None and an absent field are as before",
      _sleep_dto({"deepSleepSeconds": 1, "lightSleepSeconds": None}) ==
      {"sleepTimeSeconds": 1, "deepSleepSeconds": 1, "lightSleepSeconds": None, "remSleepSeconds": None, "awakeSleepSeconds": None})
check("F-24: _total_sleep itself leaves out what is no number (text, bool, list) and sums the rest",
      imp._total_sleep({"deepSleepSeconds": "3600", "lightSleepSeconds": 5, "remSleepSeconds": [1]}) == 5
      and imp._total_sleep({"deepSleepSeconds": True, "remSleepSeconds": "x"}) is None
      and imp._total_sleep({"deepSleepSeconds": 2, "lightSleepSeconds": 3.5, "remSleepSeconds": None}) == 5.5)
_stress_ok = {"aggregatorList": [{"averageStressLevel": 30, "maxStressLevel": 80}]}
check("F-24: allDayStress that is no object, an aggregator list that is no list, an aggregate that is no object: no stress block, the day stays",
      all("stress" not in imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": v}}, "2024-03-01")
          and imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": v}}, "2024-03-01")["user_summary"]["totalSteps"] == 5
          for v in (True, "x", [], 7, {"aggregatorList": 3}, {"aggregatorList": "x"}, {"aggregatorList": [7]},
                    {"aggregatorList": [[1]]}, {"aggregatorList": [None]}, {})))
check("F-24: ... a valid stress block is read as before",
      imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": _stress_ok}}, "2024-03-01")["stress"]["averageStressLevel"] == 30)


class _Lines:
    """The log lines of garmin_import while the block runs (no value of the data is allowed in them)."""
    def __enter__(self):
        import logging
        self.records = []
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                outer.records.append((record.levelno, record.getMessage()))
        self.h, self.log = _H(), logging.getLogger("garmin_import")
        self._level, self._disable = self.log.level, logging.root.manager.disable
        logging.disable(logging.NOTSET)             # the suite switches logging off globally (gla_testenv)
        self.log.addHandler(self.h)
        self.log.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc):
        import logging
        self.log.removeHandler(self.h)
        self.log.setLevel(self._level)
        logging.disable(self._disable)


with _Lines() as _l:
    imp.parse_day({"sleep": {"deepSleepSeconds": "SECRET-3600", "remSleepSeconds": ["SECRET-1"]},
                   "uds": {"totalSteps": 5, "allDayStress": "SECRET-STRESS"}}, "2024-03-01")
_msgs = [m for _lvl, m in _l.records if "parse_day" in m]
check("F-24: one log line for the day, at warning level, with the date and the names of the fields — never a value",
      len(_msgs) == 1 and all(lvl == 30 for lvl, m in _l.records if "parse_day" in m)
      and "2024-03-01" in _msgs[0] and "sleep.deepSleepSeconds" in _msgs[0] and "sleep.remSleepSeconds" in _msgs[0]
      and "allDayStress" in _msgs[0] and "SECRET" not in _msgs[0])
with _Lines() as _l:
    imp.parse_day({"sleep": {"deepSleepSeconds": 5, "lightSleepSeconds": None}, "uds": {"totalSteps": 5, "allDayStress": _stress_ok}}, "2024-03-01")
check("F-24: ... a day without a wrong type writes no such line", not [m for _lvl, m in _l.records if "parse_day" in m])
with _Lines() as _l:
    imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": {"aggregatorList": "SECRET-LIST"}}}, "2024-03-02")
    imp.parse_day({"uds": {"totalSteps": 5, "allDayStress": {"aggregatorList": [7]}}}, "2024-03-03")
_msgs = [m for _lvl, m in _l.records if "parse_day" in m]
check("F-24: ... the aggregator list and the first aggregate are named as their own fields",
      len(_msgs) == 2 and "2024-03-02" in _msgs[0] and _msgs[0].endswith("allDayStress.aggregatorList")
      and "2024-03-03" in _msgs[1] and _msgs[1].endswith("allDayStress.aggregatorList[0]") and "SECRET" not in _msgs[0])


def _walk(files):
    """(dates yielded, exception type or None) of days_from_originals."""
    got = []
    try:
        for raw, _entries in imp.days_from_originals(files):
            got.append(raw["date"])
    except Exception as e:                      # noqa: BLE001 - the type is the result
        return got, type(e).__name__
    return got, None


_early = {**_good_uds, "calendarDate": "2024-03-01"}
_bad = {**_good_uds, "calendarDate": "2024-03-02", "allDayStress": True}
_late = {**_good_uds, "calendarDate": "2024-03-03"}
check("F-24: a bad day no longer ends the import: the days before, the bad day itself and the days after it are all yielded",
      _walk([("f", [_early, _bad, _late])]) == (["2024-03-01", "2024-03-02", "2024-03-03"], None))
_days = {raw["date"]: raw for raw, _e in imp.days_from_originals([("f", [_early, _bad, _late])])}
check("F-24: ... and the bad day keeps its other values",
      _days["2024-03-02"]["user_summary"]["totalSteps"] == 5 and "stress" not in _days["2024-03-02"])

# ══════════════════════════════════════════════════════════════════════════════
section("Findings of v1.7.6.11 (pinned as they are — the decision per finding is the maintainer's)")
# ══════════════════════════════════════════════════════════════════════════════

# Findings 3 and 4 (F-23, F-24) became rules in v1.7.6.11.1 — see the section above.

# Finding 5 (found by "normalize does not change its argument"): normalize(raw, source="bulk") fills heart_rates from
# user_summary IN the dict it was given and returns that same dict. normalize(source="api") never changes its argument.
# garmin_writer._resolve hands it a deep copy, so no caller is hit today; a new caller that passes a stored dict would be.
_bulk_in = {"date": "2024-03-01", "user_summary": {"restingHeartRate": 50, "minHeartRate": 40}}
_bulk_out = nz.normalize(_bulk_in, source="bulk")
check("finding 5: normalize(source='bulk') adds heart_rates to the dict it was given and returns that dict (pinned)",
      _bulk_out is _bulk_in and _bulk_in.get("heart_rates") == {"restingHeartRate": 50, "minHeartRate": 40})

# Finding 6 (documentation, found while reading for the mirror delta property): REFERENCE_INVARIANTS.md ("Mirror /
# Container") says garmin_import_mirror holds a deliberate local `_QUALITY_RANK` copy that must be kept in sync by hand.
# The module has none: _analyse_raw_delta() reads garmin_quality.QUALITY_RANK itself (also the comment in
# dashboards/custom_dash_builder.py points to that "precedent"). The text is out of date, the code is the better state.
check("finding 6: garmin_import_mirror has no local _QUALITY_RANK copy", not hasattr(mirror, "_QUALITY_RANK"))
_saved_rank = dict(quality.QUALITY_RANK)
try:
    quality.QUALITY_RANK["standard"] = 5            # the one table: moving a label moves the mirror delta with it
    _src = {"days": [{"date": "2024-01-01", "quality": "standard"}]}
    _dst = {"days": [{"date": "2024-01-01", "quality": "high"}]}
    _moved = mirror._analyse_raw_delta(_src, _dst)[0] == _src["days"]
finally:
    quality.QUALITY_RANK.clear()
    quality.QUALITY_RANK.update(_saved_rank)
check("finding 6: ... the mirror delta follows garmin_quality.QUALITY_RANK itself", _moved and mirror._analyse_raw_delta(_src, _dst)[0] == [])

summary()
