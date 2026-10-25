#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_track_migration.py — migration of the mixed archive (v1.7.6.3)

Run from the project folder:
    python tests/test_track_migration.py

Part M1a: Ist-Stand. Pins the facts the detection of the migration rests on, before the
module exists: the form garmin_import wrote into raw/ (key sets per section), that the
bulk store holds the same values (coverage), that an API day does not look like it, and
that no existing check recognises a mixed day. All days are synthetic; shared setup and
helpers live in gla_testenv.py.
"""

import copy
import json

from gla_testenv import cfg, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_bulk_writer as bw
import garmin_import as importer
import garmin_normalizer as normalizer

# ══════════════════════════════════════════════════════════════════════════════
#  M1a. Ist-Stand — the form the old import wrote
# ══════════════════════════════════════════════════════════════════════════════
section("M1a. Ist-Stand: the form garmin_import wrote into raw/ (key sets per section)")

# The key sets below are what the detection will use. They are written out here on purpose:
# when garmin_import changes, these checks fail and the detection must be looked at again.
IMPORT_USER_SUMMARY = frozenset({
    "totalSteps", "dailyStepGoal", "totalKilocalories", "activeKilocalories", "totalDistanceMeters",
    "moderateIntensityMinutes", "vigorousIntensityMinutes", "floorsAscended", "restingHeartRate",
    "lastSevenDaysAvgRestingHeartRate", "minHeartRate", "maxHeartRate"})
IMPORT_STRESS = frozenset({
    "averageStressLevel", "maxStressLevel", "stressDuration", "restDuration", "lowDuration",
    "mediumDuration", "highDuration"})
IMPORT_SLEEP_DTO = frozenset({
    "sleepTimeSeconds", "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds"})
IMPORT_READINESS = frozenset({"level", "feedbackLong", "feedbackShort", "score"})
IMPORT_ACTIVITY = frozenset({
    "activityName", "activityType", "duration", "distance", "averageHR", "maxHR", "calories",
    "aerobicTrainingEffect", "anaerobicTrainingEffect"})
IMPORT_HEART_RATES = frozenset({"restingHeartRate", "minHeartRate", "maxHeartRate"})

_D = "2022-03-04"
_ENTRIES = {
    "uds": {"calendarDate": _D, "totalSteps": 7000, "dailyStepGoal": 8000, "totalKilocalories": 2300.0,
            "activeKilocalories": 400.0, "totalDistanceMeters": 5000.0, "moderateIntensityMinutes": 10,
            "vigorousIntensityMinutes": 5, "floorsAscendedInMeters": 30.0, "currentDayRestingHeartRate": 52,
            "restingHeartRate": 55, "minHeartRate": 44, "maxHeartRate": 150,
            "allDayStress": {"aggregatorList": [{"averageStressLevel": 28, "maxStressLevel": 90,
                                                 "stressDuration": 1, "restDuration": 2, "lowDuration": 3,
                                                 "mediumDuration": 4, "highDuration": 5}]}},
    "sleep": {"calendarDate": _D, "deepSleepSeconds": 5000, "lightSleepSeconds": 15000,
              "remSleepSeconds": 4000, "awakeSleepSeconds": 600},
    "readiness": {"calendarDate": _D, "level": "HIGH", "feedbackLong": "long", "feedbackShort": "short"},
    "activities": [{"name": "Walk", "activityType": "walking", "duration": 809835.0, "distance": 107463.0,
                    "avgHr": 92, "maxHr": 110, "calories": 335.0, "aerobicTrainingEffect": 1.0,
                    "anaerobicTrainingEffect": 0.0}],
}

_parsed = importer.parse_day(copy.deepcopy(_ENTRIES), _D)
check("M1a parse_day: user_summary holds exactly the twelve keys of the import form",
      set(_parsed["user_summary"]) == IMPORT_USER_SUMMARY)
check("M1a parse_day: stress holds exactly the seven aggregate keys",
      set(_parsed["stress"]) == IMPORT_STRESS)
check("M1a parse_day: sleep is {dailySleepDTO} with exactly the five duration keys",
      set(_parsed["sleep"]) == {"dailySleepDTO"} and set(_parsed["sleep"]["dailySleepDTO"]) == IMPORT_SLEEP_DTO)
check("M1a parse_day: training_readiness holds exactly four keys, activities is a list of exactly nine keys each",
      set(_parsed["training_readiness"]) == IMPORT_READINESS
      and isinstance(_parsed["activities"], list) and set(_parsed["activities"][0]) == IMPORT_ACTIVITY)
check("M1a parse_day: no heart_rates, hrv or any API-only section - the day holds only the import sections",
      set(_parsed) == {"date", "user_summary", "stress", "sleep", "training_readiness", "activities"})

_norm = normalizer.normalize(copy.deepcopy(_parsed), source="bulk")
check("M1a normalize(bulk): heart_rates is made from user_summary, exactly the three keys (value of the day 52, not the average 55)",
      _norm["heart_rates"] == {"restingHeartRate": 52, "minHeartRate": 44, "maxHeartRate": 150})
_p2 = copy.deepcopy(_parsed)
_p2["user_summary"]["minHeartRate"] = None
check("M1a normalize(bulk): a missing value is left out of heart_rates (subset of the three keys, not always all three)",
      set(normalizer.normalize(_p2, source="bulk")["heart_rates"]) == {"restingHeartRate", "maxHeartRate"})

# ══════════════════════════════════════════════════════════════════════════════
#  M1a. Ist-Stand — the bulk store holds the same values (coverage)
# ══════════════════════════════════════════════════════════════════════════════
section("M1a. Ist-Stand: the aggregates file of the bulk store reproduces the old import form")

with _isolated_log_env("m1a_cover"):
    _wr = bw.write_aggregates(_D, copy.deepcopy(_parsed), ["ab" * 32])
    _doc = bw.read_aggregates(_D)
    _from_store = normalizer.normalize(copy.deepcopy(_doc["aggregates"]), source="bulk")
    check("M1a the aggregates file is written", _wr == bw.WRITTEN and isinstance(_doc, dict))
    check("M1a normalize(stored aggregates) equals normalize(parse_day) section by section - what raw/ got from the old import",
          all(_from_store[k] == _norm[k] for k in _norm))

# ══════════════════════════════════════════════════════════════════════════════
#  M1a. Ist-Stand — an API day does not look like that, and nothing recognises a mixed day
# ══════════════════════════════════════════════════════════════════════════════
section("M1a. Ist-Stand: API sections differ from the import form; no existing check finds a mixed day")

_API = {
    "date": _D,
    "heart_rates": {"userProfilePK": 1, "calendarDate": _D, "maxHeartRate": None, "minHeartRate": None,
                    "restingHeartRate": 64, "heartRateValues": None},
    "stress": {"calendarDate": _D, "avgStressLevel": 28, "maxStressLevel": 99, "stressValuesArray": None},
    "user_summary": {"totalSteps": 3126, "floorsAscended": 0.69554, "activeKilocalories": None,
                     "abnormalHeartRateAlertsCount": 0},
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 28000, "id": 7, "calendarDate": _D}, "remSleepData": True},
    "training_readiness": [{"score": 50}],
    "activities": {"ActivitiesForDay": {"statusCode": 200, "payload": []}},
}
check("M1a API heart_rates, stress, user_summary and sleep carry keys outside the import form",
      not set(_API["heart_rates"]) <= IMPORT_HEART_RATES and not set(_API["stress"]) <= IMPORT_STRESS
      and not set(_API["user_summary"]) <= IMPORT_USER_SUMMARY
      and not (set(_API["sleep"]) == {"dailySleepDTO"} and set(_API["sleep"]["dailySleepDTO"]) <= IMPORT_SLEEP_DTO))
check("M1a API training_readiness is a list and API activities a dict - the import writes a dict and a list",
      isinstance(_API["training_readiness"], list) and isinstance(_API["activities"], dict)
      and isinstance(_parsed["training_readiness"], dict) and isinstance(_parsed["activities"], list))

import garmin_repair_resting_hr as _rr

with _isolated_log_env("m1a_none") as _b:
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    # a day in the import form that the resting-HR repair has already corrected, and its source/ file
    _mixed = copy.deepcopy(_norm)
    _mixed["date"] = _D
    _mixed["body_battery"] = [{"value": 40}]           # a section merged in from the API afterwards
    (cfg.RAW_DIR / f"garmin_raw_{_D}.json").write_text(json.dumps(_mixed), encoding="utf-8")
    (cfg.SOURCE_DIR / f"garmin_source_{_D}.json").write_text(json.dumps(_API), encoding="utf-8")
    _found = _rr.find_candidates(raw_dir=cfg.RAW_DIR, source_dir=cfg.SOURCE_DIR)
    check("M1a Ist-Stand: the resting-HR repair finds nothing in a corrected import day - no existing check recognises it as mixed",
          _found == {"repairable": [], "no_source": []})

# ══════════════════════════════════════════════════════════════════════════════
#  M1b. garmin_track_migration — detection and preview (read-only)
# ══════════════════════════════════════════════════════════════════════════════
section("M1b. garmin_track_migration - form of a section and class of a day")
import garmin_track_migration as tm
from pathlib import Path
from unittest.mock import patch

check("M1b the key sets of the module are the ones pinned in M1a (a change of garmin_import must be looked at here)",
      tm.IMPORT_USER_SUMMARY == IMPORT_USER_SUMMARY and tm.IMPORT_STRESS == IMPORT_STRESS
      and tm.IMPORT_SLEEP_DTO == IMPORT_SLEEP_DTO and tm.IMPORT_READINESS == IMPORT_READINESS
      and tm.IMPORT_ACTIVITY == IMPORT_ACTIVITY and tm.IMPORT_HEART_RATES == IMPORT_HEART_RATES)

_ALL6 = ["activities", "heart_rates", "sleep", "stress", "training_readiness", "user_summary"]
check("M1b import_sections: a day made by the old import has all six sections in import form",
      tm.import_sections(_norm) == _ALL6)
check("M1b import_sections: an API day has none (null fields, extra keys, a list where the import has a dict and the other way round)",
      tm.import_sections(_API) == [])
check("M1b import_sections: a raw that is no dict, an empty dict and empty sections give []",
      tm.import_sections(None) == [] and tm.import_sections([1]) == [] and tm.import_sections({}) == []
      and tm.import_sections({"stress": {}, "activities": [], "sleep": {}, "heart_rates": None}) == [])
_ex = copy.deepcopy(_norm)
_ex["user_summary"]["abnormalHeartRateAlertsCount"] = 0
_ex["sleep"]["dailySleepDTO"]["id"] = 7
_ex["activities"][0]["extra"] = 1
_ex["stress"]["avgStressLevel"] = 28
check("M1b import_sections: one key outside the import set takes a section out of the form (user_summary, sleep DTO, activity, stress)",
      tm.import_sections(_ex) == ["heart_rates", "training_readiness"])
_ex2 = copy.deepcopy(_norm)
_ex2["sleep"]["remSleepData"] = True
_ex2["activities"] = [_norm["activities"][0], "text"]
check("M1b import_sections: sleep needs exactly {dailySleepDTO}, a list of activities needs every entry to be a dict of the import form",
      "sleep" not in tm.import_sections(_ex2) and "activities" not in tm.import_sections(_ex2))
_part = {"date": _D, "heart_rates": _API["heart_rates"], "sleep": _norm["sleep"], "stress": _norm["stress"], "hrv": {}}
check("M1b import_sections: a day can have some sections in import form and others in API form (API heart_rates, import sleep and stress)",
      tm.import_sections(_part) == ["sleep", "stress"])

_mixed_raw = {**copy.deepcopy(_norm), "body_battery": [{"value": 40}]}
check("M1b classify_day: import sections and a source/ file -> migrate (also when API sections are mixed in)",
      tm.classify_day(_norm, True) == "migrate" and tm.classify_day(_mixed_raw, True) == "migrate")
check("M1b classify_day: import sections, no source/, nothing else -> convert; with a non-empty API section -> unresolved",
      tm.classify_day(_norm, False) == "convert" and tm.classify_day(_mixed_raw, False) == "unresolved")
check("M1b classify_day: empty extra sections (hrv {}, body_battery []) do not make a pure import day mixed",
      tm.classify_day({**_norm, "hrv": {}, "body_battery": [], "spo2": None}, False) == "convert")
check("M1b classify_day: an API day is api with or without source/, a raw that is no dict too",
      tm.classify_day(_API, True) == "api" and tm.classify_day(_API, False) == "api" and tm.classify_day("x", True) == "api")

# ── an archive in several forms ───────────────────────────────────────────────────────
section("M1b. garmin_track_migration - scan_archive and plan_migration on synthetic archives")


def _put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def _parsed_day(d, steps=7000, stress=28):
    ent = copy.deepcopy(_ENTRIES)
    ent["uds"]["calendarDate"] = d
    ent["uds"]["totalSteps"] = steps
    ent["uds"]["allDayStress"]["aggregatorList"][0]["averageStressLevel"] = stress
    ent["sleep"]["calendarDate"] = d
    ent["readiness"]["calendarDate"] = d
    return importer.parse_day(ent, d)


def _agg(d, parsed=None):
    assert bw.write_aggregates(d, copy.deepcopy(parsed or _parsed_day(d)), ["cd" * 32]) == bw.WRITTEN


def _old_raw(d, parsed=None, **extra):
    """A day as the old import wrote it, plus whatever the API merged in afterwards."""
    raw = normalizer.normalize(copy.deepcopy(parsed or _parsed_day(d)), source="bulk")
    raw.update(copy.deepcopy(extra))
    return raw


def _put_day(d, raw, source=None, summary_of=None):
    _put(cfg.RAW_DIR / f"garmin_raw_{d}.json", raw)
    _put(cfg.SUMMARY_DIR / f"garmin_{d}.json", normalizer.summarize(summary_of if summary_of is not None else raw))
    if source is not None:
        _put(cfg.SOURCE_DIR / f"garmin_source_{d}.json", source)


def _api_source(d, floors=0.5, body_battery=None):
    """What Garmin's API answered for an old day: sections with null fields, no import keys."""
    return {"date": d,
            "heart_rates": {"userProfilePK": 1, "calendarDate": d, "maxHeartRate": None, "minHeartRate": None,
                            "restingHeartRate": 64, "heartRateValues": None},
            "stress": {"calendarDate": d, "avgStressLevel": 28, "maxStressLevel": 99, "stressValuesArray": None},
            "user_summary": {"totalSteps": 7000, "floorsAscended": floors, "activeKilocalories": None,
                             "abnormalHeartRateAlertsCount": 0},
            "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 24000, "id": 7, "calendarDate": d}, "remSleepData": True},
            "activities": {"ActivitiesForDay": {"statusCode": 200, "payload": []}},
            "body_battery": body_battery if body_battery is not None else [{"value": 40}]}


def _tree(base):
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(Path(base).rglob("*")) if p.is_file()}


import garmin_writer as _gw

_DM, _DNA, _DNC, _DSU, _DSR, _DAPI, _DBAD, _DCV, _DCB, _DCX, _DUN, _DLK = (
    "2022-03-01", "2022-03-02", "2022-03-03", "2022-03-04", "2022-03-05", "2022-04-01", "2022-04-02",
    "2023-05-01", "2023-05-02", "2023-05-03", "2023-05-04", "2023-05-05")

with _isolated_log_env("m1b_archive") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _MB = [{"value": 40}]
    # migrate, ready: import sections + an API section merged in; source/ holds the API answer; the store holds the export
    _agg(_DM)
    _put_day(_DM, _old_raw(_DM, body_battery=_MB), source=_api_source(_DM))
    # migrate, blocked: no aggregates file for the day
    _put_day(_DNA, _old_raw(_DNA, body_battery=_MB), source=_api_source(_DNA))
    # migrate, blocked: the stored export is another one (stress differs from the raw file)
    _agg(_DNC, _parsed_day(_DNC, stress=77))
    _put_day(_DNC, _old_raw(_DNC, body_battery=_MB), source=_api_source(_DNC))
    # migrate, blocked: raw/ holds an API section that source/ lacks
    _agg(_DSU)
    _put_day(_DSU, _old_raw(_DSU, body_battery=_MB, spo2={"x": 1}), source=_api_source(_DSU))
    # migrate, blocked: source/ file unusable
    _agg(_DSR)
    _put_day(_DSR, _old_raw(_DSR, body_battery=_MB), source="{ not json")
    # migrate, ready although the raw file lacks a field the export has (newer parse): the export covers the raw section
    _agg(_DCX)
    _o = _old_raw(_DCX, body_battery=_MB)
    _o["user_summary"].pop("lastSevenDaysAvgRestingHeartRate")
    _put_day(_DCX, _o, source=_api_source(_DCX))
    # migrate, blocked: aggregates file cannot be read
    _agg(_DLK)
    _put_day(_DLK, _old_raw(_DLK, body_battery=_MB), source=_api_source(_DLK))
    # convert, ready; convert, blocked (store differs)
    _agg(_DCV)
    _put_day(_DCV, _old_raw(_DCV))
    _agg(_DCB, _parsed_day(_DCB, steps=1))
    _put_day(_DCB, _old_raw(_DCB))
    # unresolved: import sections and an API section, no source/
    _agg(_DUN)
    _put_day(_DUN, _old_raw(_DUN, body_battery=_MB))
    # an API day without export data, an unreadable raw file, a name that is no day
    _put_day(_DAPI, {"date": _DAPI, "heart_rates": {"calendarDate": _DAPI, "restingHeartRate": 55, "heartRateValues": [[1, 60]]}})
    _put(cfg.RAW_DIR / f"garmin_raw_{_DBAD}.json", "{ not json")
    _put(cfg.RAW_DIR / "garmin_raw_junk.json", "{}")
    # refresh: an API day whose heart rate min/max the API left empty, summary made without the export; an up-to-date one;
    # an export-only day without and one with its summary
    _R1, _R2, _R3, _R4 = "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"
    for _d in (_R1, _R2, _R3, _R4):
        _agg(_d)
    _put_day(_R1, {"date": _R1, "heart_rates": {"calendarDate": _R1, "restingHeartRate": 55, "minHeartRate": None,
                                                 "maxHeartRate": None, "heartRateValues": None}})
    _ok_raw = {"date": _R2, "heart_rates": {"calendarDate": _R2, "restingHeartRate": 55, "minHeartRate": 44,
                                             "maxHeartRate": 150, "heartRateValues": None}}
    _put_day(_R2, _ok_raw)
    _put(cfg.SUMMARY_DIR / f"garmin_{_R2}.json", _gw.resolve_preview(_ok_raw, _R2)["summary"])      # made with the export, up to date
    _put(cfg.SUMMARY_DIR / f"garmin_{_R4}.json", _gw.resolve_preview({}, _R4)["summary"])
    # an up-to-date summary of an older schema version (written by an earlier program version): not a refresh by itself
    _R5 = "2024-01-05"
    _agg(_R5)
    _ok5 = {"date": _R5, "heart_rates": {"calendarDate": _R5, "restingHeartRate": 55, "minHeartRate": 44, "maxHeartRate": 150, "heartRateValues": None}}
    _put_day(_R5, _ok5)
    _put(cfg.SUMMARY_DIR / f"garmin_{_R5}.json", {**_gw.resolve_preview(_ok5, _R5)["summary"], "schema_version": 0, "generated_by": "an older version"})

    # days that are handled by their class must not turn up as refresh days either, also without a summary
    (cfg.SUMMARY_DIR / f"garmin_{_DUN}.json").unlink()
    (cfg.SUMMARY_DIR / f"garmin_{_DSR}.json").unlink()

    _before = _tree(_b)
    _s = tm.scan_archive()
    check("M1b scan_archive: migrate days (with source/, even a damaged source/ or a missing aggregates file) are listed",
          _s["migrate"] == sorted([_DM, _DNA, _DNC, _DSU, _DSR, _DCX, _DLK]))
    check("M1b scan_archive: convert, unresolved, unreadable (and the name that is no day is ignored), API days counted",
          _s["convert"] == [_DCV, _DCB] and _s["unresolved"] == [_DUN] and _s["unreadable"] == [_DBAD] and _s["api_only"] == 4)
    check("M1b scan_archive: migrate/convert days without an aggregates file are named", _s["no_aggregates"] == [_DNA])
    check("M1b scan_archive: nothing is written", _tree(_b) == _before)
    check("M1b scan_archive: a folder that does not exist gives an empty result",
          tm.scan_archive(raw_dir=_b / "nowhere")["migrate"] == [] and tm.scan_archive(raw_dir=_b / "nowhere")["api_only"] == 0)
    _other = _b / "other"
    _so = tm.scan_archive(raw_dir=cfg.RAW_DIR, source_dir=_other / "s", agg_dir=_other / "a")
    check("M1b scan_archive: other folders can be passed (the GUI passes the archive of its settings): without source/ files the "
          "mixed days are unresolved, without aggregates files every migrate/convert day is named",
          _so["migrate"] == [] and _so["unresolved"] == sorted([_DUN, _DM, _DNA, _DNC, _DSU, _DSR, _DCX, _DLK])
          and _so["convert"] == [_DCV, _DCB] and _so["no_aggregates"] == [_DCV, _DCB])

    _agg_lock = cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_DLK}.json"
    _real_rt = Path.read_text

    def _locked(self, *a, **k):
        if self == _agg_lock:
            raise PermissionError("locked by another process")
        return _real_rt(self, *a, **k)

    with patch.object(Path, "read_text", _locked):
        _plan = tm.plan_migration()
    _by = {(i["date"], i["kind"]): i for i in _plan["items"]}

    check("M1b plan: a migrate day covered by the store and by source/ is ready, with the summary fields that change",
          _by[(_DM, "migrate")]["status"] == "ready" and "day.floors_climbed" in _by[(_DM, "migrate")]["changes"]
          and _by[(_DM, "migrate")]["import_sections"] == _ALL6)
    check("M1b plan: the heart rate min and max do not change (the export fills what the API leaves empty - F-11) and the activities become empty",
          "heartrate.min_bpm" not in _by[(_DM, "migrate")]["changes"] and "heartrate.max_bpm" not in _by[(_DM, "migrate")]["changes"]
          and "activities" in _by[(_DM, "migrate")]["changes"])
    check("M1b plan: a migrate day whose raw section is held by the store with more fields is ready (newer parse)",
          _by[(_DCX, "migrate")]["status"] == "ready")
    check("M1b plan: no aggregates file -> blocked 'no_aggregates'",
          _by[(_DNA, "migrate")] == {"date": _DNA, "kind": "migrate", "status": "blocked", "reason": "no_aggregates"})
    check("M1b plan: another export in the store -> blocked 'not_covered', the section is named (stress)",
          _by[(_DNC, "migrate")]["reason"] == "not_covered" and _by[(_DNC, "migrate")]["keys"] == ["stress"])
    check("M1b plan: an API section in raw/ that source/ does not reproduce -> blocked 'not_covered' (spo2)",
          _by[(_DSU, "migrate")]["reason"] == "not_covered" and _by[(_DSU, "migrate")]["keys"] == ["spo2"])
    check("M1b plan: an unusable source/ file -> blocked 'source_unreadable'", _by[(_DSR, "migrate")]["reason"] == "source_unreadable")
    check("M1b plan: an aggregates file that cannot be read -> blocked 'aggregates_unreadable'", _by[(_DLK, "migrate")]["reason"] == "aggregates_unreadable")
    check("M1b plan: a pure import day covered by the store is a ready convert day; one the store does not reproduce is blocked",
          _by[(_DCV, "convert")]["status"] == "ready" and _by[(_DCB, "convert")]["reason"] == "not_covered"
          and "user_summary" in _by[(_DCB, "convert")]["keys"])
    check("M1b plan: a mixed day without source/ is left ('unresolved'), an unreadable raw file is left, neither is touched",
          _by[(_DUN, "unresolved")] == {"date": _DUN, "kind": "unresolved", "status": "left", "reason": "mixed_without_source"}
          and _by[(_DBAD, "api")]["reason"] == "raw_unreadable" and _by[(_DBAD, "api")]["status"] == "left")
    check("M1b plan: refresh lists the days whose resolved summary differs from summary/ (API day with empty min/max; export-only day without summary)",
          _by[(_R1, "refresh")]["status"] == "ready" and "heartrate.min_bpm" in _by[(_R1, "refresh")]["changes"]
          and _by[(_R3, "refresh")]["changes"] == ["(summary missing)"])
    check("M1b plan: refresh does not list a day whose summary is up to date (API day, export-only day, an older schema_version alone), nor a migrate/convert/unresolved day",
          (_R2, "refresh") not in _by and (_R4, "refresh") not in _by and (_R5, "refresh") not in _by
          and not any(i["kind"] == "refresh" and i["date"] in (_DM, _DCV, _DUN, _DSR, _DNA, _DCB) for i in _plan["items"]))
    _c = _plan["counts"]
    check("M1b plan: counts (migrate 2 ready / 5 blocked, convert 1/1, unresolved 1, unreadable 1, refresh 2, API days 4)",
          (_c["migrate_ready"], _c["migrate_blocked"], _c["convert_ready"], _c["convert_blocked"]) == (2, 5, 1, 1)
          and (_c["unresolved"], _c["unreadable"], _c["refresh"], _c["refresh_blocked"], _c["api_only"]) == (1, 1, 2, 0, 4))
    check("M1b plan: years count migrate/convert/refresh/blocked per year",
          _plan["years"]["2022"] == {"migrate": 1, "convert": 0, "refresh": 0, "blocked": 4}
          and _plan["years"]["2023"] == {"migrate": 1, "convert": 1, "refresh": 0, "blocked": 2}
          and _plan["years"]["2024"] == {"migrate": 0, "convert": 0, "refresh": 2, "blocked": 0})
    check("M1b plan: field_changes counts the ready days per field (floors climbed in both ready migrate days)",
          _plan["field_changes"]["migrate"].get("day.floors_climbed") == 2 and "heartrate.min_bpm" in _plan["field_changes"]["refresh"])
    check("M1b plan: items are sorted by date and nothing is written", [i["date"] for i in _plan["items"]] == sorted(i["date"] for i in _plan["items"])
          and _tree(_b) == _before)
    check("M1b plan: the same preview twice gives the same result (idempotent)",
          tm.plan_migration()["items"] == tm.plan_migration()["items"] and tm.plan_migration() == tm.plan_migration())

    _stop_after = iter([False, False, True])
    _ps = tm.plan_migration(should_stop=lambda: next(_stop_after, True))
    check("M1b plan: a stop request ends the preview after the current day ('stopped' is set, fewer items)",
          _ps["stopped"] is True and len(_ps["items"]) < len(_plan["items"]))
    _p0 = tm.plan_migration(should_stop=lambda: True)
    check("M1b plan: a stop request before the first day: no day is looked at (only the days left by their class are listed)",
          _p0["stopped"] is True and all(i["status"] == "left" for i in _p0["items"])
          and _p0["counts"]["migrate_ready"] == 0 and _p0["counts"]["refresh"] == 0)
    _p1 = tm.plan_migration(should_stop=iter([False] * 9 + [True]).__next__)       # 7 migrate + 2 convert days, then the first refresh day
    check("M1b plan: a stop request after the last migrate/convert day still ends the refresh step",
          _p1["stopped"] is True and _p1["counts"]["migrate_ready"] + _p1["counts"]["migrate_blocked"] == 7
          and _p1["counts"]["refresh"] == 0)

    _lines = tm.format_plan(_plan)
    _text = "\n".join(_lines)
    check("M1b format_plan: says nothing is written, names the counts, the reasons with example dates and the changed fields",
          "nothing is written" in _lines[0] and "migrate): 2 ready, 5 blocked" in _text
          and "import the Garmin export first" in _text and _DNA in _text and "day.floors_climbed" in _text)
    check("M1b format_plan: warns that the activity lists of the old import become empty; marks an incomplete preview",
          "activity lists of the old import" in _text and "(stopped" in "\n".join(tm.format_plan(_ps)) and "(stopped" not in _text)

with _isolated_log_env("m1b_empty") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _pe = tm.plan_migration()
    check("M1b plan: an archive without raw/ gives an empty plan (no error)",
          _pe["items"] == [] and _pe["counts"]["migrate_ready"] == 0 and _pe["stopped"] is False)

with _isolated_log_env("m1b_refresh_raw") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _RB = "2024-02-01"
    _agg(_RB)
    _put(cfg.RAW_DIR / f"garmin_raw_{_RB}.json", "{ not json")
    check("M1b refresh step: a raw file that cannot be read is blocked, not guessed (the day is not listed as ready)",
          tm._plan_refresh(_RB) == {"date": _RB, "kind": "refresh", "status": "blocked", "reason": "raw_unreadable"})
    check("M1b refresh step: a day without aggregates file gives nothing", tm._plan_refresh("2024-02-02") is None)

# ══════════════════════════════════════════════════════════════════════════════
#  M3a. Ist-Stand - what the migration step relies on (before it exists)
# ══════════════════════════════════════════════════════════════════════════════
section("M3a. Ist-Stand: facts the migration step relies on")
import garmin_quality as _q3
import garmin_quality as quality
import garmin_writer as _w3

with _isolated_log_env("m3a_facts") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _d1, _d2 = "2022-05-01", "2022-05-02"
    _e1 = {"date": _d1, "quality": "standard", "source": "api", "write": True, "recheck": False, "attempts": 0,
           "last_checked": "2024-01-01", "last_attempt": None, "fields": {"stress": "medium"}}
    _log = {"first_day": "2022-01-01", "devices": [], "days": [copy.deepcopy(_e1)]}
    _n = _q3.touch_last_checked(_log, [_d1, _d2])
    check("M3a touch_last_checked: counts only the days that have an entry, never creates one, changes only last_checked",
          _n == 1 and len(_log["days"]) == 1 and _log["days"][0]["last_checked"] != "2024-01-01"
          and {k: v for k, v in _log["days"][0].items() if k != "last_checked"} == {k: v for k, v in _e1.items() if k != "last_checked"})
    _src = {"date": _d1, "stress": {"avgStressLevel": 28}}
    check("M3a normalize(api) returns the very dict it was given - the migration has to hand it a copy",
          normalizer.normalize(_src, source="api") is _src)
    _put_log(_log)
    _w3.write_day({"date": _d1, "stress": {"avgStressLevel": 28}}, {"date": _d1}, _d1)
    _log_bytes = cfg.QUALITY_LOG_FILE.read_bytes()
    _w3.write_day({"date": _d2, "stress": {"avgStressLevel": 30}}, {"date": _d2}, _d2)
    check("M3a write_day() does not touch the quality log - the migration step records its days itself",
          cfg.QUALITY_LOG_FILE.read_bytes() == _log_bytes and [e["date"] for e in _q3._load_quality_log()["days"]] == [_d1])
    check("M3a write_day() writes the raw file as JSON that reads back to the dict it was given (what a read-back check can compare)",
          _w3.read_raw(_d1) == {"date": _d1, "stress": {"avgStressLevel": 28}})

# ══════════════════════════════════════════════════════════════════════════════
#  M3b. run_migration - the migration of the "migrate" days and the refresh of summaries
# ══════════════════════════════════════════════════════════════════════════════
section("M3b. garmin_track_migration.run_migration")
import zipfile
import garmin_backup as _bk
import garmin_backup_common as _bkc
import garmin_migration_snapshot as _snap3
from gla_testenv import _cfg_values

_M1, _M2, _MB, _M3, _MU, _MC, _RF, _AP = ("2022-06-01", "2022-06-02", "2022-06-03", "2023-07-01", "2023-07-02",
                                          "2023-07-03", "2024-03-01", "2024-03-02")
_ALLD = [_M1, _M2, _MB, _M3, _MU, _MC, _RF, _AP]
_TODAY3 = __import__("datetime").date.today().isoformat()


def _qe3(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False, "attempts": 0,
            "last_checked": "2024-01-01", "last_attempt": None, "fields": {"stress": "medium"}, **kw}


def _archive3():
    """migrate x3 (2022, 2022, 2023), migrate without aggregates, unresolved, convert, refresh, API day up to date."""
    _MBY = [{"value": 40}]
    for d in (_M1, _M2, _M3):
        _agg(d)
        _put_day(d, _old_raw(d, body_battery=_MBY), source=_api_source(d))
    _put_day(_MB, _old_raw(_MB, body_battery=_MBY), source=_api_source(_MB))
    _agg(_MU)
    _put_day(_MU, _old_raw(_MU, body_battery=_MBY))
    _agg(_MC)
    _put_day(_MC, _old_raw(_MC))
    _agg(_RF)
    _put_day(_RF, {"date": _RF, "heart_rates": {"calendarDate": _RF, "restingHeartRate": 55, "minHeartRate": None,
                                                 "maxHeartRate": None, "heartRateValues": None}})
    _agg(_AP)
    _ap = {"date": _AP, "heart_rates": {"calendarDate": _AP, "restingHeartRate": 55, "minHeartRate": 44, "maxHeartRate": 150, "heartRateValues": None}}
    _put_day(_AP, _ap)
    _put(cfg.SUMMARY_DIR / f"garmin_{_AP}.json", _gw.resolve_preview(_ap, _AP)["summary"])
    _flds = {d: quality.assess_quality_fields(_api_source(d)) for d in (_M1, _M2, _M3)}
    _flds[_M2] = {**_flds[_M2], "stress": "high"}          # another field label than the recalculated one, same quality
    _put_log({"first_day": "2022-06-01", "devices": [],
              "days": [_qe3(d, **({"fields": _flds[d]} if d in _flds else {}), **({"quality": "high"} if d == _M3 else {})) for d in _ALLD]})


def _bytes_of(d):
    out = {}
    for p in (cfg.RAW_DIR / f"garmin_raw_{d}.json", cfg.SUMMARY_DIR / f"garmin_{d}.json"):
        out[p.parent.name] = p.read_bytes() if p.exists() else None
    return out


def _lock_free():
    got = quality.QUALITY_LOCK.acquire(blocking=False)
    if got:
        quality.QUALITY_LOCK.release()
    return got


with _isolated_log_env("m3b_run") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _before = _tree(_b)
        _dry = tm.run_migration(dry_run=True)
        check("M3b dry run: ok, says what it would do (3 days rebuilt, 1 summary refreshed), names the blocked day, writes nothing, makes no copy",
              _dry["ok"] is True and (_dry["migrated"], _dry["refreshed"]) == (3, 1) and _dry["blocked"] == [(_MB, "no_aggregates")]
              and (_dry["unresolved"], _dry["convert_pending"]) == (1, 1) and _dry["snapshot"] is None and _tree(_b) == _before)

        _expect = {d: _gw.resolve_preview(_api_source(d), d)["summary"] for d in (_M1, _M2, _M3)}
        _expect_rf = _gw.resolve_preview(json.loads((cfg.RAW_DIR / f"garmin_raw_{_RF}.json").read_text(encoding="utf-8")), _RF)["summary"]
        _old = {d: _bytes_of(d) for d in _ALLD}
        _entries_before = {e["date"]: copy.deepcopy(e) for e in quality._load_quality_log()["days"]}
        _res = tm.run_migration()
        check("M3b run: ok, 3 days rebuilt, 1 summary refreshed, nothing failed, the log saved, one safety copy named",
              _res["ok"] is True and (_res["migrated"], _res["refreshed"], _res["failed"], _res["log_saved"]) == (3, 1, [], True)
              and _res["snapshot"] and len(_snap3.list_snapshots()) == 1 and _snap3.list_snapshots()[0]["name"] == _res["snapshot"])
        check("M3b run: counted per year (2022: 2 rebuilt, 2023: 1 rebuilt, 2024: 1 refreshed)",
              _res["years"] == {"2022": {"migrated": 2, "refreshed": 0, "failed": 0}, "2023": {"migrated": 1, "refreshed": 0, "failed": 0},
                                "2024": {"migrated": 0, "refreshed": 1, "failed": 0}})
        _newraw = {d: json.loads((cfg.RAW_DIR / f"garmin_raw_{d}.json").read_text(encoding="utf-8")) for d in (_M1, _M2, _M3)}
        check("M3b run: raw/ of a rebuilt day is now exactly the API data of source/ - no section in import form, the day is an API day",
              all(_newraw[d] == _api_source(d) and tm.import_sections(_newraw[d]) == [] and tm.classify_day(_newraw[d], True) == "api" for d in _newraw))
        check("M3b run: the summary of a rebuilt day is the resolved one (the export fills what the API leaves empty: min 44 and max 150 stay), "
              "the refreshed day has its summary made again and its raw file untouched",
              all(json.loads((cfg.SUMMARY_DIR / f"garmin_{d}.json").read_text(encoding="utf-8")) == _expect[d] for d in _newraw)
              and _expect[_M1]["heartrate"]["min_bpm"] == 44
              and json.loads((cfg.SUMMARY_DIR / f"garmin_{_RF}.json").read_text(encoding="utf-8")) == _expect_rf
              and _bytes_of(_RF)["raw"] == _old[_RF]["raw"] and _expect_rf["heartrate"]["min_bpm"] == 44)
        check("M3b run: blocked, unresolved, convert and up-to-date API days are not touched (raw and summary byte for byte)",
              all(_bytes_of(d) == _old[d] for d in (_MB, _MU, _MC, _AP)))
        _snap_path = _snap3.list_snapshots()[0]["path"]
        with zipfile.ZipFile(_snap_path) as _zf:
            _held = all(_zf.read(f"raw/garmin_raw_{d}.json") == _old[d]["raw"] and _zf.read(f"summary/garmin_{d}.json") == _old[d]["summary"] for d in _ALLD)
        check("M3b run: the safety copy holds the state BEFORE the run for every day (the old mixed raw files are in it)",
              _held and _snap3.verify_snapshot(_snap_path)["ok"] is True)
        _after = {e["date"]: e for e in json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"]}
        _written = (_M1, _M2, _M3, _RF)
        check("M3b run: the written days got a new last_checked, every other field of their entries and the entries of the other days are unchanged",
              all(_after[d]["last_checked"] == _TODAY3 and {k: v for k, v in _after[d].items() if k != "last_checked"}
                  == {k: v for k, v in _entries_before[d].items() if k != "last_checked"} for d in _written)
              and all(_after[d] == _entries_before[d] for d in (_MB, _MU, _MC, _AP)))
        check("M3b run: a day whose recalculated label (entry 'high', API data 'standard') or fields differ from its entry is reported, the entries are left alone",
              _res["label_differs"] == [_M2, _M3] and _after[_M3]["quality"] == "high" and _after[_M2]["fields"]["stress"] == "high")
        check("M3b run: the raw backup follows the rebuilt day (it holds the new version, the old one is in the safety copy)",
              _bkc.read_copy(_bk._kind(), f"garmin_raw_{_M1}.json") == (cfg.RAW_DIR / f"garmin_raw_{_M1}.json").read_bytes())
        check("M3b run: the quality lock is free afterwards", _lock_free())
        _lines = tm.format_result(_res)
        _text = "\n".join(_lines)
        check("M3b format_result: names the counts, the safety copy, the years, what was not touched and the label note",
              "3 day(s) rebuilt" in _lines[0] and _res["snapshot"] in _text and "2022: 2 rebuilt" in _text and "1 x no usable aggregates file" in _text
              and "1 mixed day(s)" in _text and "1 pure import day(s)" in _text and "another label or fields" in _text)

        _again = tm.run_migration()
        check("M3b a rerun finds nothing left to do: ok, nothing rebuilt or refreshed, no new safety copy, the blocked day is reported again",
              _again["ok"] is True and (_again["migrated"], _again["refreshed"]) == (0, 0) and _again["snapshot"] is None
              and len(_snap3.list_snapshots()) == 1 and _again["blocked"] == [(_MB, "no_aggregates")])
        check("M3b the preview after the run lists nothing ready", tm.plan_migration()["counts"]["migrate_ready"] == 0 and tm.plan_migration()["counts"]["refresh"] == 0)

with _isolated_log_env("m3b_stop") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _calls = {"n": 0}
        _real_wd = _gw.write_day

        def _counting_write_day(*a, **k):
            _calls["n"] += 1
            return _real_wd(*a, **k)

        with patch.object(_gw, "write_day", _counting_write_day):
            _st = tm.run_migration(should_stop=lambda: _calls["n"] >= 1)
        check("M3b a stop request after the first day: stopped, not ok, one day rebuilt, the safety copy exists, the log has that day marked",
              _st["stopped"] is True and _st["ok"] is False and _st["migrated"] == 1 and len(_snap3.list_snapshots()) == 1
              and sum(1 for e in json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"] if e["last_checked"] == _TODAY3) == 1)
        _rest = tm.run_migration()
        check("M3b the run can simply be started again and goes on where it stopped (the two other days and the refresh)",
              _rest["ok"] is True and (_rest["migrated"], _rest["refreshed"]) == (2, 1) and len(_snap3.list_snapshots()) == 2)

with _isolated_log_env("m3b_fail") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _before = _tree(_b)
        with patch.object(_snap3, "create_snapshot", return_value={"ok": False, "reason": "disk full", "path": None}):
            _nc = tm.run_migration()
        check("M3b no safety copy, no write: reason 'snapshot_failed', nothing in raw/, summary/ or the log changed, the text says it was not started",
              _nc["ok"] is False and _nc["reason"] == "snapshot_failed" and _nc["migrated"] == 0 and _tree(_b) == _before
              and "NOT started" in tm.format_result(_nc)[0] and "disk full" in tm.format_result(_nc)[0] and _lock_free())

        _d2_old = _bytes_of(_M2)

        def _fail_m2(normalized, summary, d):
            return False if d == _M2 else _real_wd(normalized, summary, d)

        with patch.object(_gw, "write_day", _fail_m2):
            _fl = tm.run_migration()
        check("M3b one day that cannot be written: it is named, the other days are done, its files stay as they were, its entry is not marked",
              _fl["ok"] is False and [d for d, _ in _fl["failed"]] == [_M2] and _fl["migrated"] == 2 and _bytes_of(_M2) == _d2_old
              and {e["date"]: e for e in json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"]}[_M2]["last_checked"] == "2024-01-01"
              and _fl["years"]["2022"]["failed"] == 1 and _lock_free())
        _fix = tm.run_migration()
        check("M3b after the failure a rerun does the day that failed", _fix["ok"] is True and _fix["migrated"] == 1 and _bytes_of(_M2) != _d2_old)

with _isolated_log_env("m3b_readback") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _real_rr = _gw.read_raw

        def _wrong_readback(d):
            return {"date": d, "something": "else"} if d == _M1 else _real_rr(d)

        with patch.object(_gw, "read_raw", _wrong_readback):
            _rb = tm.run_migration()
        check("M3b a raw file that does not read back as the source data is an error of the day (found right after writing)",
              _rb["ok"] is False and [d for d, _ in _rb["failed"]] == [_M1] and "differs" in _rb["failed"][0][1])

with _isolated_log_env("m3b_late") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _real_plan = tm.plan_migration

        def _plan_then_change(should_stop=None):
            plan = _real_plan(should_stop)
            changed = json.loads((cfg.RAW_DIR / f"garmin_raw_{_M2}.json").read_text(encoding="utf-8"))
            changed["spo2"] = {"x": 1}                     # data appears that source/ does not reproduce, after the preview
            (cfg.RAW_DIR / f"garmin_raw_{_M2}.json").write_text(json.dumps(changed), encoding="utf-8")
            return plan

        _m2_changed_bytes = None
        with patch.object(tm, "plan_migration", _plan_then_change):
            _lt = tm.run_migration()
        check("M3b a day is checked again right before it is written: one that is not covered any more is left alone and reported, the others are done",
              _lt["ok"] is True and _lt["migrated"] == 2 and (_M2, "not_covered") in _lt["blocked"]
              and json.loads((cfg.RAW_DIR / f"garmin_raw_{_M2}.json").read_text(encoding="utf-8")).get("spo2") == {"x": 1})

with _isolated_log_env("m3b_qdata") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _archive3()
        _qd = quality._load_quality_log()
        _qr = tm.run_migration(quality_data=_qd)
        _mem = {e["date"]: e for e in _qd["days"]}
        check("M3b with the caller's quality_data the marks are made on that object (the caller's next save keeps them) and it is saved",
              _qr["ok"] is True and _mem[_M1]["last_checked"] == _TODAY3 and _mem[_MB]["last_checked"] == "2024-01-01"
              and {e["date"]: e for e in json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"]}[_M1]["last_checked"] == _TODAY3)

with _isolated_log_env("m3b_empty") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _em = tm.run_migration()
        check("M3b an archive without raw/: ok, nothing done, no safety copy, no folder created",
              _em["ok"] is True and (_em["migrated"], _em["refreshed"]) == (0, 0) and _em["snapshot"] is None and not (_b / "migration").exists())

# ══════════════════════════════════════════════════════════════════════════════
#  M4a. Ist-Stand - what the hooks rely on (before they exist)
# ══════════════════════════════════════════════════════════════════════════════
section("M4a. Ist-Stand: the cheap scan cannot know the coverage")

with _isolated_log_env("m4a_again") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _DNC4 = "2022-08-01"
        _agg(_DNC4, _parsed_day(_DNC4, stress=77))             # the store holds another export than the raw file
        _put_day(_DNC4, _old_raw(_DNC4, body_battery=[{"value": 40}]), source=_api_source(_DNC4))
        _r4 = tm.run_migration()
        _s4 = tm.scan_archive()
        check("M4a a day the store does not cover is left by the run (blocked) - and the cheap scan still lists it as a migrate day "
              "with an aggregates file: a hook built on the scan offers that day again at every start",
              _r4["blocked"] == [(_DNC4, "not_covered")] and _s4["migrate"] == [_DNC4] and _s4["no_aggregates"] == [])

# ══════════════════════════════════════════════════════════════════════════════
#  M4b. pending - what a hook offers
# ══════════════════════════════════════════════════════════════════════════════
section("M4b. garmin_track_migration.pending")

_f4 = {"migrate": ["2022-01-01", "2022-01-02", "2022-01-03"], "convert": ["2022-02-01"], "unresolved": ["2022-03-01"],
       "unreadable": [], "no_aggregates": ["2022-01-02", "2022-02-01"], "api_only": 3}
_f4_before = copy.deepcopy(_f4)
check("M4b pending: the migrate days with an aggregates file are ready, those without wait for the export import; "
      "convert (a later step), unresolved and API days are not offered; the scan result is not changed",
      tm.pending(_f4) == {"ready": ["2022-01-01", "2022-01-03"], "waiting": ["2022-01-02"]} and _f4 == _f4_before)
check("M4b pending: nothing found -> nothing ready, nothing waiting",
      tm.pending(tm.scan_archive(raw_dir=Path("nowhere") / "raw")) == {"ready": [], "waiting": []})

# ══════════════════════════════════════════════════════════════════════════════
#  M4c. Scheduler hint - scheduler/daily_update.py::_check_track_migration
# ══════════════════════════════════════════════════════════════════════════════
section("M4c. Scheduler hint: daily_update._check_track_migration")
import importlib.util

_du_spec = importlib.util.spec_from_file_location(
    "daily_update_tm", Path(__file__).resolve().parent.parent / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)


class _Rec4:
    """Stand-in for the module logger - keeps the messages per level."""
    def __init__(self):
        self.m = {"debug": [], "info": [], "warning": [], "error": []}
        for lvl in self.m:
            setattr(self, lvl, (lambda lv: lambda s, *a, **k: self.m[lv].append(s))(lvl))


def _gd_archive(root, ready=2, waiting=0):
    """An archive in the layout of a base folder: root/garmin_data/{raw,source,summary,bulk/aggregates}."""
    gd = root / "garmin_data"
    days = [f"2022-09-{n:02d}" for n in range(1, ready + waiting + 1)]
    with _cfg_values(RAW_DIR=gd / "raw", SOURCE_DIR=gd / "source", SUMMARY_DIR=gd / "summary", BULK_AGG_DIR=gd / "bulk" / "aggregates"):
        for i, d in enumerate(days):
            if i < ready:
                _agg(d)
            _put_day(d, _old_raw(d, body_battery=[{"value": 40}]), source=_api_source(d))
        _put_day("2022-10-01", {"date": "2022-10-01", "heart_rates": {"calendarDate": "2022-10-01", "restingHeartRate": 55}})
    return days


with _isolated_log_env("m4c_sched") as _b:
    _arch = _b / "archive"
    _gd_archive(_arch, ready=2, waiting=1)
    _before4 = _tree(_arch)
    _rec = _Rec4()
    with patch.object(_du, "log", _rec):
        _n4 = _du._check_track_migration(_arch)
    check("M4c scheduler hint: counts the days that can be migrated now (not the one that waits for the export import) and warns with the number",
          _n4 == 2 and _rec.m["warning"] == [
              "  2 day(s) of the archive are still in the mixed form of the old export import.",
              "  Open the app and run Sync Garmin once to migrate them (a safety copy is made first)."]
          and not _rec.m["error"])
    check("M4c scheduler hint: it only looks - no file of the archive changes, nothing is created", _tree(_arch) == _before4)
    _rec = _Rec4()
    with patch.object(_du, "log", _rec):
        _n4n = _du._check_track_migration(_b / "no_archive_here")
    check("M4c scheduler hint: no archive folder -> 0 and no warning", _n4n == 0 and not _rec.m["warning"])
    _arch2 = _b / "archive_waiting"
    _gd_archive(_arch2, ready=0, waiting=2)
    _rec = _Rec4()
    with patch.object(_du, "log", _rec):
        _n4w = _du._check_track_migration(_arch2)
    check("M4c scheduler hint: only days that wait for the export import -> 0 and no warning (nothing the app could do yet)",
          _n4w == 0 and not _rec.m["warning"])
    _rec = _Rec4()
    with patch.object(_du, "log", _rec), patch.object(tm, "scan_archive", side_effect=RuntimeError("boom")):
        _n4e = _du._check_track_migration(_arch)
    check("M4c scheduler hint: an error in the scan never stops the run - 0 and no warning, no error",
          _n4e == 0 and not _rec.m["warning"] and not _rec.m["error"])

# ══════════════════════════════════════════════════════════════════════════════
#  M6a. A list in the store with the same entries in another order (F-13)
# ══════════════════════════════════════════════════════════════════════════════
section("M6a. activities that the store holds in another order cover the raw section (F-13)")

_DO1, _DO2, _DO3, _DO4 = "2022-09-01", "2022-09-02", "2022-09-03", "2022-09-04"


def _ride_day(d, reverse_raw, raw_change=None):
    """A migrate day with two activities; raw/ holds them in the order of the store or the other way round.
    raw_change (optional): called with the raw activities list to change what raw/ holds."""
    parsed = _parsed_day(d)
    ride = copy.deepcopy(parsed["activities"][0])
    ride["activityName"], ride["duration"] = "Ride", 1500000.0
    parsed["activities"] = [parsed["activities"][0], ride]
    _agg(d, parsed)
    raw = _old_raw(d, parsed, body_battery=[{"value": 40}])
    if reverse_raw:
        raw["activities"] = list(reversed(raw["activities"]))
    if raw_change:
        raw_change(raw["activities"])
    _put_day(d, raw, source=_api_source(d))


with _isolated_log_env("m6a_order") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _ride_day(_DO1, reverse_raw=True)
    _ride_day(_DO2, reverse_raw=False)
    _ride_day(_DO3, reverse_raw=True, raw_change=lambda acts: acts[0].__setitem__("duration", 1.0))          # one entry really differs
    _ride_day(_DO4, reverse_raw=False, raw_change=lambda acts: acts.__setitem__(1, copy.deepcopy(acts[0])))  # entry twice in raw/, once in the store
    _put_log({"first_day": _DO1, "devices": [],
              "days": [_qe3(d) for d in (_DO1, _DO2, _DO3, _DO4)]})
    _raw1 = json.loads((cfg.RAW_DIR / f"garmin_raw_{_DO1}.json").read_text(encoding="utf-8"))["activities"]
    _exp1 = _gw.resolve_preview({}, _DO1)["export"]["activities"]
    check("M6a setup: raw/ and the store hold the same two activities, in the opposite order for the first day",
          len(_raw1) == len(_exp1) == 2 and _raw1 != _exp1 and _raw1 == list(reversed(_exp1)))
    _by6 = {i["date"]: i for i in tm.plan_migration()["items"] if i["kind"] == "migrate"}
    check("M6a: the same activities in the same order -> ready",
          _by6[_DO2]["status"] == "ready")
    check("M6a: the same activities in another order -> ready (was a false alarm 'not_covered', F-13)",
          _by6[_DO1]["status"] == "ready")
    check("M6a: an activity that really differs, in another order -> still blocked 'not_covered' (activities)",
          _by6[_DO3]["status"] == "blocked" and _by6[_DO3]["reason"] == "not_covered" and _by6[_DO3]["keys"] == ["activities"])
    check("M6a: an entry twice in raw/ that the store holds once -> still blocked (duplicates count)",
          _by6[_DO4]["status"] == "blocked" and _by6[_DO4]["keys"] == ["activities"])
    check("M6a: _covers on lists - order free, duplicates counted, dicts and other values as before",
          tm._covers([{"a": 1}, {"b": 2}], [{"b": 2}, {"a": 1}]) and tm._covers([{"a": 1, "b": 2}], [{"b": 2, "a": 1}]) and not tm._covers([{"a": 1}], [{"a": 1}, {"a": 1}])
          and not tm._covers([{"a": 1}, {"a": 1}], [{"a": 1}, {"b": 2}]) and not tm._covers([1], {"a": 1})
          and tm._covers({"a": 1, "b": 2}, {"a": 1, "c": None}) and tm._covers(5, 5) and not tm._covers(5, 6))
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _res6 = tm.run_migration()
    check("M6a: the migration rebuilds the two covered days, the other two stay blocked",
          _res6["ok"] is True and _res6["migrated"] == 2 and sorted(d for d, _ in _res6["blocked"]) == [_DO3, _DO4])
    check("M6a: afterwards the cheap scan offers only the two blocked days (the popup does not come for the migrated ones)",
          tm.pending(tm.scan_archive())["ready"] == [_DO3, _DO4])

summary()
