#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_broker.py — Garmin Local Archive — Broker Layer Test

Run from the project folder:
    python tests/test_broker.py

No network, no GUI, no Garmin API calls.
Uses synthetic raw JSON files — no real data required.
Cleans up after itself — leaves no files behind.

Covers the Broker Layer (maps/) routing contract: health_map, context_map,
gateway_map. context_map's own fan-out logic (multi-source get(),
KeyError-skip, per-source exception degrade, list_fields()/list_sources())
gained dedicated coverage in Section 1b — closes the pre-existing gap
previously noted here (see NOTES_v1692.md).

Split out of test_dashboard.py (v1.6.9.2) — was Sections 2/2b there, mixed
in with Dashboard-specific specialist/plotter tests. Pure move, same
checks, same wording. The fixture setup below is its own reduced copy of
test_dashboard.py's (only what health_map/gateway_map actually need to
exercise real routing behavior), not an import from test_dashboard.py —
keeps both test files independently runnable.
"""

import json
import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT))
logging.disable(logging.CRITICAL)

# ── Test runner ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from support import check, section, summary

# ── Temp directory as BASE_DIR ─────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_broker_test_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)

import importlib
import garmin_config as cfg
importlib.reload(cfg)

# ── Synthetic raw data (identical to test_dashboard.py's _RAW) ─────────────────

_TEST_DATE = "2026-03-01"

_RAW = {
    "date": _TEST_DATE,
    "sleep": {
        "dailySleepDTO": {
            "sleepTimeSeconds":  27000,
            "deepSleepSeconds":  5400,
            "lightSleepSeconds": 13500,
            "remSleepSeconds":   6750,
            "awakeSleepSeconds": 1350,
        }
    },
    "heart_rates": {
        "heartRateValues": [
            [1740787200000, 58],
            [1740787260000, 60],
            [1740787320000, 62],
        ]
    },
    "stress": {
        "stressValuesArray": [
            [1740787200000, 25],
            [1740787260000, 30],
        ],
        "stressChartValueOffset": 0,
        "bodyBatteryValuesArray": [
            [1740787200000, "CHARGED", 85, 1],
            [1740787260000, "CHARGED", 83, 1],
        ],
    },
    "spo2": {
        "spO2HourlyAverages": [
            [1772352000000, 97],
            [1772355600000, 98],
        ]
    },
    "respiration": {
        "respirationValuesArray": [
            [1772352000000, 14.5],
            [1772355600000, 15.0],
        ]
    },
    "steps": [
        {"startGMT": "2026-03-01T08:00:00", "steps": 120, "pushes": 0,
         "primaryActivityLevel": "sedentary", "activityLevelConstant": True},
        {"startGMT": "2026-03-01T09:00:00", "steps": 450, "pushes": 0,
         "primaryActivityLevel": "highlyActive", "activityLevelConstant": False},
    ],
}

def _write_raw(base_dir: Path):
    raw_dir = base_dir / "garmin_data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / f"garmin_raw_{_TEST_DATE}.json"
    f.write_text(json.dumps(_RAW), encoding="utf-8")
    return raw_dir


_write_raw(_TMPDIR)
importlib.reload(cfg)

from maps import garmin_health_map

# ── Synthetic context raw data (weather/pollen/brightsky/airquality) ───────────
# "wind_speed_max" is deliberately registered in BOTH weather_map and
# brightsky_map's _FIELD_MAP — used below to exercise real multi-source
# fan-out, not just single-source routing.

# v1.7.1.11 — fixture dirs renamed to *_SUMMARY_DIR (old CONTEXT_*_DIR
# meaning: daily aggregate, now stored under summary/ not raw/). Fields
# below are unchanged — these fixtures only exercise the daily read path,
# not the new raw/ intraday path (covered separately in test_local_context.py).
_CONTEXT_FIXTURES = {
    "weather": {
        "dir":    cfg.CONTEXT_WEATHER_SUMMARY_DIR,
        "prefix": "weather_",
        "fields": {
            "temperature_2m_max": 25.0,
            "wind_speed_10m_max": 18.5,
        },
    },
    "pollen": {
        "dir":    cfg.CONTEXT_POLLEN_SUMMARY_DIR,
        "prefix": "pollen_",
        "fields": {
            "birch_pollen": 3.0,
        },
    },
    "brightsky": {
        "dir":    cfg.CONTEXT_BRIGHTSKY_SUMMARY_DIR,
        "prefix": "brightsky_",
        "fields": {
            "wind_speed": 22.0,
        },
    },
    "airquality": {
        "dir":    cfg.CONTEXT_AIRQUALITY_SUMMARY_DIR,
        "prefix": "airquality_",
        "fields": {
            "pm2_5": 8.0,
        },
    },
}

def _write_context_raw():
    for _fixture in _CONTEXT_FIXTURES.values():
        _fixture["dir"].mkdir(parents=True, exist_ok=True)
        f = _fixture["dir"] / f"{_fixture['prefix']}{_TEST_DATE}.json"
        f.write_text(
            json.dumps({"date": _TEST_DATE, "fields": _fixture["fields"]}),
            encoding="utf-8",
        )

_write_context_raw()


# ══════════════════════════════════════════════════════════════════════════════
#  1. health_map — routing to garmin_health_map
# ══════════════════════════════════════════════════════════════════════════════

section("1. health_map — routing to garmin_health_map")

from maps import health_map

result_fm = health_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, resolution="intraday")
check("health_map: garmin key in result",        "garmin" in result_fm)
check("health_map: values present",              len(result_fm["garmin"]["values"]) > 0)
check("health_map: fallback key present",        "fallback" in result_fm["garmin"])

# ── active_only passthrough + get_raw()/list_raw_fields() (v1.6.8 Session 4) ─

check("health_map list_fields: active_only passthrough for garmin",
      len(health_map.list_fields(source="garmin", active_only=True)) ==
      len(garmin_health_map.list_fields(active_only=True)))
check("health_map list_fields: unknown source → empty list",
      health_map.list_fields(source="nonexistent_source") == [])

check("health_map list_raw_fields: garmin → 12 fields",
      len(health_map.list_raw_fields(source="garmin")) == 12)
check("health_map list_raw_fields: unknown source → empty list",
      health_map.list_raw_fields(source="nonexistent_source") == [])

_hm_gr = health_map.get_raw("floors", "2000-01-01", "2000-01-01", source="garmin")
check("health_map get_raw: garmin delegates to garmin_health_map",
      _hm_gr["source_resolution"] == "raw")

try:
    health_map.get_raw("floors", "2000-01-01", "2000-01-01", source="nonexistent_source")
    check("health_map get_raw: unknown source raises KeyError", False)
except KeyError:
    check("health_map get_raw: unknown source raises KeyError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  1b. context_map — fan-out routing to weather/pollen/brightsky/airquality
# ══════════════════════════════════════════════════════════════════════════════

section("1b. context_map — fan-out routing to weather/pollen/brightsky/airquality")

from maps import context_map, weather_map

# ── Single-source field: only weather registers "temperature_max" ──────────────

result_cm_single = context_map.get("temperature_max", _TEST_DATE, _TEST_DATE)
check("context_map: single-source field → only weather key present",
      set(result_cm_single.keys()) == {"weather"})
check("context_map: single-source field → correct value",
      result_cm_single["weather"]["values"][0]["value"] == 25.0)

# ── Multi-source field: weather AND brightsky both register "wind_speed_max" ───

result_cm_multi = context_map.get("wind_speed_max", _TEST_DATE, _TEST_DATE)
check("context_map: multi-source field → weather+brightsky keys present",
      set(result_cm_multi.keys()) == {"weather", "brightsky"})
check("context_map: multi-source field → weather value from weather fixture",
      result_cm_multi["weather"]["values"][0]["value"] == 18.5)
check("context_map: multi-source field → brightsky value from brightsky fixture",
      result_cm_multi["brightsky"]["values"][0]["value"] == 22.0)

# ── Unknown field: no source registers it → empty dict, no crash (KeyError-skip) ─

check("context_map: field unknown to all sources → empty dict",
      context_map.get("definitely_unknown_field", _TEST_DATE, _TEST_DATE) == {})

# ── Intraday resolution → fallback=True passthrough (context sources are daily) ─

result_cm_intraday = context_map.get("temperature_max", _TEST_DATE, _TEST_DATE, resolution="intraday")
check("context_map: intraday resolution → fallback=True",
      result_cm_intraday["weather"]["fallback"] is True)

# ── Exception-degrade path: one source raises, others stay unaffected ──────────

_orig_weather_get = weather_map.get

def _raising_get(*args, **kwargs):
    raise RuntimeError("simulated source failure")

weather_map.get = _raising_get
try:
    result_cm_degrade = context_map.get("wind_speed_max", _TEST_DATE, _TEST_DATE)
    check("context_map: source exception → degraded error entry for that source",
          "error" in result_cm_degrade["weather"] and
          result_cm_degrade["weather"]["values"] == [])
    check("context_map: source exception → other source unaffected",
          result_cm_degrade["brightsky"]["values"][0]["value"] == 22.0 and
          "error" not in result_cm_degrade["brightsky"])
finally:
    weather_map.get = _orig_weather_get

# ── list_fields() / list_sources() ──────────────────────────────────────────────

# v1.7.1.11 — pollen/brightsky/airquality _FIELD_MAP now additionally
# registers one "_series" entry per daily field (Anchor 4.1) — list_fields()
# does not distinguish daily from series, so these counts doubled for the
# three hourly sources. weather has no _series variant, count unchanged.
check("context_map list_fields: default source=weather → 6 fields",
      len(context_map.list_fields()) == 6)
check("context_map list_fields: pollen → 12 fields (6 daily + 6 series)",
      len(context_map.list_fields("pollen")) == 12)
check("context_map list_fields: brightsky → 18 fields (9 daily + 9 series)",
      len(context_map.list_fields("brightsky")) == 18)
check("context_map list_fields: airquality → 10 fields (5 daily + 5 series)",
      len(context_map.list_fields("airquality")) == 10)
check("context_map list_fields: unknown source → empty list",
      context_map.list_fields("nonexistent_source") == [])

check("context_map list_sources: all four registered names",
      set(context_map.list_sources()) == {"weather", "pollen", "brightsky", "airquality"})


# ══════════════════════════════════════════════════════════════════════════════
#  2. gateway_map — routing to health_map/context_map
# ══════════════════════════════════════════════════════════════════════════════

section("2. gateway_map — routing to health_map/context_map")

from maps import gateway_map

result_gw = gateway_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, resolution="intraday")
check("gateway_map: health key in result",       "health" in result_gw)
check("gateway_map: fit key in result",          "fit" in result_gw)
check("gateway_map: context key in result",      "context" in result_gw)
check("gateway_map: health = health_map result", result_gw["health"] == health_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, resolution="intraday"))
check("gateway_map: fit not yet available",      result_gw["fit"] == {"error": "domain not yet available"})
check("gateway_map: context is dict",            isinstance(result_gw["context"], dict))

result_gw_health_only = gateway_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, resolution="intraday", domain="health")
check("gateway_map domain=health: only health key", list(result_gw_health_only.keys()) == ["health"])

result_gw_fit_only = gateway_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, domain="fit")
check("gateway_map domain=fit: degraded result", result_gw_fit_only == {"fit": {"error": "domain not yet available"}})

try:
    gateway_map.get("heart_rate_series", _TEST_DATE, _TEST_DATE, domain="banana")
    check("gateway_map: unknown domain raises ValueError", False)
except ValueError:
    check("gateway_map: unknown domain raises ValueError", True)

_gw_domains = gateway_map.list_domains()
check("gateway_map: list_domains has 3 entries", len(_gw_domains) == 3)
check("gateway_map: list_domains has health/fit/context", set(_gw_domains) == {"health", "fit", "context"})

# ── get_raw() / list_raw_fields() — symmetric to get()/list_domains() (v1.6.8) ─

_gw_raw_health = gateway_map.get_raw("floors", "2000-01-01", "2000-01-01", domain="health")
check("gateway_map get_raw domain=health: delegates to health_map",
      _gw_raw_health == {"health": health_map.get_raw("floors", "2000-01-01", "2000-01-01")})

_gw_raw_fit = gateway_map.get_raw("floors", "2000-01-01", "2000-01-01", domain="fit")
check("gateway_map get_raw domain=fit: degraded result (broker not registered)",
      _gw_raw_fit == {"fit": {"error": "domain not yet available"}})

try:
    gateway_map.get_raw("floors", "2000-01-01", "2000-01-01", domain="banana")
    check("gateway_map get_raw: unknown domain raises ValueError", False)
except ValueError:
    check("gateway_map get_raw: unknown domain raises ValueError", True)

_gw_raw_all = gateway_map.get_raw("floors", "2000-01-01", "2000-01-01")
check("gateway_map get_raw domain=None: all three keys present",
      set(_gw_raw_all.keys()) == {"health", "fit", "context"})
check("gateway_map get_raw domain=None: context degrades (no raw-passthrough)",
      _gw_raw_all["context"] == {"error": "domain has no raw-passthrough support"})

_gw_lrf_health = gateway_map.list_raw_fields(domain="health")
check("gateway_map list_raw_fields domain=health: 12 fields",
      len(_gw_lrf_health["health"]) == 12)

_gw_lrf_fit = gateway_map.list_raw_fields(domain="fit")
check("gateway_map list_raw_fields domain=fit: empty list (broker not registered)",
      _gw_lrf_fit == {"fit": []})

try:
    gateway_map.list_raw_fields(domain="banana")
    check("gateway_map list_raw_fields: unknown domain raises ValueError", False)
except ValueError:
    check("gateway_map list_raw_fields: unknown domain raises ValueError", True)

_gw_lrf_all = gateway_map.list_raw_fields()
check("gateway_map list_raw_fields domain=None: all three domain keys present",
      set(_gw_lrf_all.keys()) == {"health", "fit", "context"})
check("gateway_map list_raw_fields domain=None: fit is empty (not registered)",
      _gw_lrf_all["fit"] == [])
check("gateway_map list_raw_fields domain=None: context degrades to empty (no raw-passthrough)",
      _gw_lrf_all["context"] == [])

# ══════════════════════════════════════════════════════════════════════════════
#  3. metadata_map — archive-state introspection
# ══════════════════════════════════════════════════════════════════════════════

section("3. metadata_map — archive-state introspection")

from maps import metadata_map
from maps.metadata_map import _sanitize_line

# ── 3a. Missing file / missing directory — nothing written yet ─────────────────

_missing_dt = metadata_map.get_device_table()
check("get_device_table: missing file → data None",   _missing_dt["data"] is None)
check("get_device_table: missing file → error set",   _missing_dt["error"] is not None)

_missing_ql = metadata_map.get_quality_log()
check("get_quality_log: missing file → data None",    _missing_ql["data"] is None)
check("get_quality_log: missing file → error set",    _missing_ql["error"] is not None)

_missing_sal = metadata_map.get_source_api_log()
check("get_source_api_log: missing file → data None", _missing_sal["data"] is None)
check("get_source_api_log: missing file → error set", _missing_sal["error"] is not None)

_missing_tl = metadata_map.get_token_log()
check("get_token_log: missing file → data None",      _missing_tl["data"] is None)
check("get_token_log: missing file → error set",      _missing_tl["error"] is not None)

_missing_stats = metadata_map.get_stats()
check("get_stats: missing quality_log.json → degraded empty stats, no error",
      _missing_stats == {
          "data": {
              "total": 0, "high": 0, "standard": 0, "failed": 0, "recheck": 0,
              "missing": None, "date_min": None, "date_max": None,
              "coverage_pct": None, "last_api": None, "last_bulk": None,
              "integrity_warnings": [],
          },
          "error": None,
      })

# v1.7.0.4: get_daily_logs/get_fail_logs/get_recent_logs now accept
# date_from/date_to. Called here with an explicit wide-open range
# (date_from=None, date_to a date far in the future) instead of no
# arguments at all, specifically to avoid the 30-day-default "note"
# field this section is not testing for — the "missing dir" case is
# about the empty-list/no-error degrade path, not the default-range
# mechanism (that gets its own dedicated coverage in Section 3f below).
check("get_daily_logs: missing dir → empty list, no error",
      metadata_map.get_daily_logs(date_to="2099-12-31") ==
      {"data": [], "error": None})
check("get_fail_logs: missing dir → empty list, no error",
      metadata_map.get_fail_logs(date_to="2099-12-31") ==
      {"data": [], "error": None})
check("get_recent_logs: missing dir → empty list, no error",
      metadata_map.get_recent_logs(date_to="2099-12-31") ==
      {"data": [], "error": None})

# ── 3b. Happy path — device_table / quality_log / stats / source_api_log / token_log

cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

_DEVICE_TABLE_FIXTURE = {"devices": [{"deviceId": "123", "model": "Fenix"}]}
cfg.DEVICE_TABLE_FILE.write_text(json.dumps(_DEVICE_TABLE_FIXTURE), encoding="utf-8")
check("get_device_table: happy path → real content",
      metadata_map.get_device_table() == {"data": _DEVICE_TABLE_FIXTURE, "error": None})

_QUALITY_LOG_FIXTURE = {
    "days": [
        {"date": "2026-03-01", "quality": "high",     "source": "api",  "recheck": False},
        {"date": "2026-03-02", "quality": "standard", "source": "bulk", "recheck": True},
    ],
    "integrity_warnings": [],
}
cfg.QUALITY_LOG_FILE.write_text(json.dumps(_QUALITY_LOG_FIXTURE), encoding="utf-8")
# v1.7.0.4: explicit wide-open range, not the no-args default — this
# check is about the JSON round-trip (device_table-style happy path),
# not about the default-range mechanism (Section 3f below).
check("get_quality_log: happy path → real content",
      metadata_map.get_quality_log(date_from="2026-01-01", date_to="2026-12-31") ==
      {"data": _QUALITY_LOG_FIXTURE, "error": None})

check("get_stats: happy path → real content", metadata_map.get_stats() == {
    "data": {
        "total": 2, "high": 1, "standard": 1, "failed": 0, "recheck": 1,
        "missing": 0, "date_min": "2026-03-01", "date_max": "2026-03-02",
        "coverage_pct": 100, "last_api": "2026-03-01", "last_bulk": "2026-03-02",
        "integrity_warnings": [],
    },
    "error": None,
})

# v1.7.0.4: fixture corrected to match source_api_log.json's real shape
# — top-level keys ARE the ISO dates themselves (verified against a
# real archive file during the v1.7.0.4 session), not a nested "calls"
# list. The previous {"calls": [...]} fixture predates this and was
# never actually representative — get_source_api_log()'s new date-key
# filtering made that mismatch impossible to paper over any further,
# since filtering by top-level key against a "calls"-shaped dict would
# silently drop everything. Corrected here rather than worked around.
_SOURCE_API_LOG_FIXTURE = {"2026-03-01": {"status": "ok"}}
cfg.SOURCE_API_LOG.write_text(json.dumps(_SOURCE_API_LOG_FIXTURE), encoding="utf-8")
# Explicit wide-open range — see get_quality_log note above; this check
# is the plain JSON-round-trip/happy-path case, not the filter itself
# (Section 3f below covers date-key filtering with a purpose-built
# multi-day fixture).
check("get_source_api_log: happy path → real content",
      metadata_map.get_source_api_log(date_from="2026-01-01", date_to="2026-12-31") ==
      {"data": _SOURCE_API_LOG_FIXTURE, "error": None})

_TOKEN_LOG_FIXTURE = [{"event": "created", "timestamp": "2026-03-01T08:00:00"}]
(cfg.LOG_DIR / "garmin_token_log.json").write_text(json.dumps(_TOKEN_LOG_FIXTURE), encoding="utf-8")
check("get_token_log: happy path → real content",
      metadata_map.get_token_log() == {"data": _TOKEN_LOG_FIXTURE, "error": None})

# ── 3c. Corrupt JSON — representative case, same _read_json_file code path as
#        the four happy-path functions above ────────────────────────────────

cfg.CAPABILITY_CONFIG_FILE.write_text("{not valid json", encoding="utf-8")
_cc = metadata_map.get_capability_config()
check("get_capability_config: corrupt JSON → data None", _cc["data"] is None)
check("get_capability_config: corrupt JSON → error set", _cc["error"] is not None)

# ── 3d. Raw-log directories — sanitization, multi-file glob, unreadable entry ───
#
# v1.7.0.4: filenames corrected to the real "YYYY-MM-DD_HHMMSS.log" scheme
# (verified against a real archive tree during the v1.7.0.4 session,
# e.g. "daily_2026-08-13_061918.log") — the old bare-date fixture names
# ("2026-03-01.log") never matched that scheme and were never
# representative; get_daily_logs()'s new filename-date filter
# (_LOG_FILENAME_DATE_RE) made that mismatch actually break the test
# (files not matching the pattern are silently skipped, same "unmatched
# → excluded" rule as an unreadable file — see metadata_map.py). Both
# dated files are given the same day here (only their HHMMSS differs),
# since this section is about sanitization/glob/skip behaviour, not
# about date-range filtering itself (that gets its own dedicated
# coverage in Section 3f). Explicit date_from/date_to passed to avoid
# the unrelated 30-day-default "note" field interfering with this
# section's checks.

cfg.LOG_DAILY_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_DAILY_DIR / "daily_2026-03-01_060000.log").write_text(
    "sync completed successfully\n"
    "password: hunter2 — should be dropped entirely\n"
    "user contact: foo@bar.com from 10.0.0.5\n",
    encoding="utf-8",
)
(cfg.LOG_DAILY_DIR / "daily_2026-03-01_070000.log").write_text("second file, second line\n", encoding="utf-8")
(cfg.LOG_DAILY_DIR / "notes.txt").write_text("not a .log file — must be ignored\n", encoding="utf-8")
(cfg.LOG_DAILY_DIR / "broken.log").mkdir()  # directory named *.log — open() raises OSError, must be skipped

_daily = metadata_map.get_daily_logs(date_from="2026-01-01", date_to="2026-12-31")
check("get_daily_logs: error is None",               _daily["error"] is None)
check("get_daily_logs: explicit range → no 'note' field",
      "note" not in _daily)
check("get_daily_logs: secret line dropped",
      not any("hunter2" in line for line in _daily["data"]))
check("get_daily_logs: PII line masked, not dropped",
      "user contact: [EMAIL] from [IP]" in _daily["data"])
check("get_daily_logs: harmless line unchanged",
      "sync completed successfully" in _daily["data"])
check("get_daily_logs: second file included (multi-file glob)",
      "second file, second line" in _daily["data"])
check("get_daily_logs: non-.log file ignored",
      not any("not a .log file" in line for line in _daily["data"]))
check("get_daily_logs: unreadable entry (dir named *.log) skipped, no crash",
      len(_daily["data"]) == 3)
check("get_daily_logs: sorted file order preserved",
      _daily["data"].index("sync completed successfully") <
      _daily["data"].index("second file, second line"))

# v1.7.0.4: "fail.log"/"recent.log" do not match _LOG_FILENAME_DATE_RE
# (no "YYYY-MM-DD_HHMMSS" stamp in the name), so they are silently
# skipped by the new filename-date filter regardless of date_from/
# date_to — same "unmatched filename → excluded, never raise" behaviour
# as an unreadable file. Renamed to a real, dated filename so this
# section keeps testing what it was testing (own-directory read +
# sanitization), rather than accidentally testing the filename-filter's
# skip path instead. Filename-date-filter correctness itself gets
# dedicated coverage in Section 3f below.
cfg.LOG_FAIL_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_FAIL_DIR / "garmin_2026-03-01_080000.log").write_text(
    "fail entry, nothing sensitive\n", encoding="utf-8")
check("get_fail_logs: reads its own directory, sanitized",
      metadata_map.get_fail_logs(date_from="2026-01-01", date_to="2026-12-31") ==
      {"data": ["fail entry, nothing sensitive"], "error": None})

cfg.LOG_RECENT_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_RECENT_DIR / "garmin_2026-03-01_080000.log").write_text(
    "recent entry, nothing sensitive\n", encoding="utf-8")
check("get_recent_logs: reads its own directory, sanitized",
      metadata_map.get_recent_logs(date_from="2026-01-01", date_to="2026-12-31") ==
      {"data": ["recent entry, nothing sensitive"], "error": None})

# ── 3e. Hard exclusion — GARMIN_TOKEN_FILE / garmin_token.enc never referenced
#        in the module's actual code. The docstring mentions both by name to
#        document the exclusion, so it is deliberately excluded here: splitting
#        the source on triple-quotes and keeping only the even-indexed (i.e.
#        non-docstring) segments strips every docstring, module- and function-
#        level alike. ──────────────────────────────────────────────────────

_mm_source = (_ROOT / "maps" / "metadata_map.py").read_text(encoding="utf-8")
_mm_code_only = "".join(_mm_source.split('"""')[::2])
check("metadata_map.py: GARMIN_TOKEN_FILE never referenced in code",
      "GARMIN_TOKEN_FILE" not in _mm_code_only)
check("metadata_map.py: garmin_token.enc never referenced in code",
      "garmin_token.enc" not in _mm_code_only)


# ── 3f. Date-range filtering (v1.7.0.4) — the actual new behaviour ─────────────
#
# Dedicated coverage for the filter itself: entries/files strictly
# outside an explicit range are excluded (not just "entries inside are
# kept", which alone would not catch a filter that lets everything
# through), the 30-day default actually narrows a wider fixture, and
# the filename-date regex handles prefixes containing underscores
# (garmin_background_, test_connection_) — the exact case identified as
# a real risk (a naive split-on-first-underscore would misparse these).

# ── date-key filtering — quality_log, narrow range excludes out-of-range days
_QLOG_WIDE_FIXTURE = {
    "days": [
        {"date": "2026-01-10", "quality": "high", "source": "api", "recheck": False},
        {"date": "2026-06-15", "quality": "high", "source": "api", "recheck": False},
        {"date": "2026-06-16", "quality": "high", "source": "api", "recheck": False},
    ],
    "integrity_warnings": ["unrelated, always passed through"],
}
cfg.QUALITY_LOG_FILE.write_text(json.dumps(_QLOG_WIDE_FIXTURE), encoding="utf-8")

_qlog_filtered = metadata_map.get_quality_log(date_from="2026-06-15", date_to="2026-06-16")
check("get_quality_log: date range excludes out-of-range day",
      not any(d["date"] == "2026-01-10" for d in _qlog_filtered["data"]["days"]))
check("get_quality_log: date range keeps in-range days",
      {d["date"] for d in _qlog_filtered["data"]["days"]} == {"2026-06-15", "2026-06-16"})
check("get_quality_log: integrity_warnings passed through unfiltered (not date-indexed)",
      _qlog_filtered["data"]["integrity_warnings"] == ["unrelated, always passed through"])
check("get_quality_log: explicit range → no 'note' field",
      "note" not in _qlog_filtered)

_qlog_default = metadata_map.get_quality_log()
check("get_quality_log: no args → 'note' field present",
      "note" in _qlog_default)
check("get_quality_log: no args → default range excludes the oldest day "
      "(2026-01-10 is >30 days before the latest day, 2026-06-16)",
      not any(d["date"] == "2026-01-10" for d in _qlog_default["data"]["days"]))
check("get_quality_log: no args → default range keeps the latest day",
      any(d["date"] == "2026-06-16" for d in _qlog_default["data"]["days"]))

# ── date-key filtering — source_api_log, same mechanism, dict-of-dates shape
_SALOG_WIDE_FIXTURE = {
    "2026-01-10": {"status": "ok"},
    "2026-06-15": {"status": "ok"},
    "2026-06-16": {"status": "ok"},
}
cfg.SOURCE_API_LOG.write_text(json.dumps(_SALOG_WIDE_FIXTURE), encoding="utf-8")

_salog_filtered = metadata_map.get_source_api_log(date_from="2026-06-15", date_to="2026-06-16")
check("get_source_api_log: date range excludes out-of-range key",
      "2026-01-10" not in _salog_filtered["data"])
check("get_source_api_log: date range keeps in-range keys",
      set(_salog_filtered["data"].keys()) == {"2026-06-15", "2026-06-16"})
check("get_source_api_log: explicit range → no 'note' field",
      "note" not in _salog_filtered)

# ── filename-date filtering — prefixes containing underscores must not
#    confuse the regex (garmin_background_, test_connection_, mcp_proxy_
#    style prefixes were the specifically identified real-world risk)
shutil.rmtree(cfg.LOG_RECENT_DIR, ignore_errors=True)
cfg.LOG_RECENT_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_RECENT_DIR / "garmin_2026-01-10_080000.log").write_text(
    "old entry\n", encoding="utf-8")
(cfg.LOG_RECENT_DIR / "garmin_background_2026-06-15_071434.log").write_text(
    "background entry\n", encoding="utf-8")
(cfg.LOG_RECENT_DIR / "test_connection_2026-06-16_081325.log").write_text(
    "test connection entry\n", encoding="utf-8")

_recent_filtered = metadata_map.get_recent_logs(date_from="2026-06-15", date_to="2026-06-16")
check("get_recent_logs: filename date filter excludes out-of-range file",
      not any("old entry" in line for line in _recent_filtered["data"]))
check("get_recent_logs: filename date filter handles 'garmin_background_' prefix correctly",
      any("background entry" in line for line in _recent_filtered["data"]))
check("get_recent_logs: filename date filter handles 'test_connection_' prefix correctly",
      any("test connection entry" in line for line in _recent_filtered["data"]))


# ══════════════════════════════════════════════════════════════════════════════
#  4. _sanitize_line() — security filter, per-pattern coverage
# ══════════════════════════════════════════════════════════════════════════════

section("4. _sanitize_line() — security filter")

# secret material — dropped entirely (None)
check("_sanitize_line: JWT fragment dropped",
      _sanitize_line("token: eyJhbGciOiJIUzI1NiJ9.abcdefghij") is None)
check("_sanitize_line: Authorization header dropped",
      _sanitize_line("Authorization: Bearer abc123") is None)
check("_sanitize_line: bearer keyword dropped (case-insensitive)",
      _sanitize_line("BEARER: xyz789") is None)
check("_sanitize_line: refresh_token keyword dropped",
      _sanitize_line("refresh_token=abcdef") is None)
check("_sanitize_line: access-token keyword dropped",
      _sanitize_line("access-token: abcdef") is None)
check("_sanitize_line: id_token keyword dropped",
      _sanitize_line("id_token=abcdef") is None)
check("_sanitize_line: password dropped",
      _sanitize_line("password: hunter2") is None)
check("_sanitize_line: password dropped (case-insensitive)",
      _sanitize_line("PASSWORD=hunter2") is None)
check("_sanitize_line: cookie dropped",
      _sanitize_line("Cookie: session=abc123") is None)

# PII — masked, not dropped
check("_sanitize_line: email masked",
      _sanitize_line("contact me at foo@bar.com please") == "contact me at [EMAIL] please")
check("_sanitize_line: IPv4 masked",
      _sanitize_line("connected from 192.168.1.1") == "connected from [IP]")
check("_sanitize_line: lat masked",
      _sanitize_line("lat=52.520008 recorded") == "lat=[COORD] recorded")
check("_sanitize_line: lon masked",
      _sanitize_line("lon=13.404954 recorded") == "lon=[COORD] recorded")
check("_sanitize_line: multiple PII types in one line all masked",
      _sanitize_line("email foo@bar.com from 10.0.0.5") == "email [EMAIL] from [IP]")

# edge cases
check("_sanitize_line: harmless line unchanged",
      _sanitize_line("sync completed successfully") == "sync completed successfully")
check("_sanitize_line: empty line unchanged",
      _sanitize_line("") == "")
check("_sanitize_line: secret + PII together → dropped (secret check runs first)",
      _sanitize_line("password=hunter2 email foo@bar.com") is None)


# ══════════════════════════════════════════════════════════════════════════════
#  5. gateway_map.get_metadata() — dispatch
# ══════════════════════════════════════════════════════════════════════════════

section("5. gateway_map.get_metadata() — dispatch")

# v1.7.1 — three filename-only kinds added for the SQLite proxy's
# internal sync use (clients/mcp_update.py) — not part of the original
# nine LLM-facing kinds, but registered through the same dispatch
# mechanism per the single-broker-entry-point architecture decision
# (NOTES_v1.7.1_session2.md).
#
# v1.7.1.1 — "raw_file_hashes" added for the raw-passthrough SQLite
# cache's content-change detection (NOTES_v1.7.1.1_session2.md, Ziel 4)
# — deliberately excluded from the zero-arg loop below and from
# _expected_kinds' generic-loop membership: unlike every other kind
# here, gateway_map.get_metadata() requires date_from/date_to for this
# one (see metadata_map.get_raw_file_hashes()'s own docstring — no
# 30-day default, no optional-range branch), so a bare
# gateway_map.get_metadata("raw_file_hashes") call would exercise the
# error path (a TypeError from _parse_iso_date(None), caught and
# degraded into {"data": None, "error": ...}) rather than the success
# path the other kinds' loop iteration below is meant to confirm.
# Tested explicitly with a real range instead, so this kind's actual
# contract is verified rather than incidentally passing via the same
# try/except every other metadata_map function also happens to have.
#
# No ordinal/total kind-count named here on purpose (a prior version of
# this comment said "a fourteenth kind" / "exactly the fourteen
# registered kinds" — off by one, since _expected_kinds already has
# twelve entries, not thirteen — corrected by removing the count
# entirely rather than fixing the number in place: any hard-coded count
# here has to be kept in sync by hand every time a kind is added or
# removed, the exact failure mode that produced this bug. The
# assertion below is a pure set-equality check and needs no restated
# count to be correct; the current total lives in docs/METRICS.md
# (generated, not hand-maintained) for anyone who wants to look it up.)
_expected_kinds = {
    "stats", "device_table", "quality_log", "source_api_log", "token_log",
    "capability_config", "daily_logs", "fail_logs", "recent_logs",
    "daily_log_filenames", "fail_log_filenames", "recent_log_filenames",
    "context_resync_pending",
}
_all_registered_kinds = _expected_kinds | {"raw_file_hashes"}
check("list_metadata_kinds: matches the registered kind set exactly",
      set(gateway_map.list_metadata_kinds()) == _all_registered_kinds)

# v1.7.5.1 Schritt 5: include_internal=False hides the five kinds registered
# for the SQLite proxy's internal sync only; the default stays the full set.
_internal_only = {
    "daily_log_filenames", "fail_log_filenames", "recent_log_filenames",
    "raw_file_hashes", "context_resync_pending",
}
check("list_metadata_kinds(include_internal=False): omits exactly the internal-sync-only kinds",
      set(gateway_map.list_metadata_kinds(include_internal=False))
      == _all_registered_kinds - _internal_only)
check("list_metadata_kinds: default is unchanged (include_internal=True)",
      gateway_map.list_metadata_kinds() == gateway_map.list_metadata_kinds(include_internal=True))

for _kind in sorted(_expected_kinds):
    _result = gateway_map.get_metadata(_kind)
    check(f"get_metadata({_kind!r}): returns data/error envelope",
          isinstance(_result, dict) and "data" in _result and "error" in _result)

# ── v1.7.1.1: raw_file_hashes — mandatory date_from/date_to, tested
#    with a real range rather than the zero-arg loop above (see comment
#    block above for why). _TEST_DATE's raw/ file was written at module
#    setup (_write_raw(_TMPDIR), top of this file) and is still present
#    here — so this section's own range check exercises the real-hash
#    path, with a second, different date (no fixture ever written for
#    it) as the contrasting "no file → None" case, matching
#    metadata_map.get_raw_file_hashes()'s own "hash_hex is None for a
#    day whose raw/ file does not exist" contract.
_rfh_result = gateway_map.get_metadata("raw_file_hashes", date_from=_TEST_DATE, date_to=_TEST_DATE)
check("get_metadata('raw_file_hashes'): returns data/error envelope",
      isinstance(_rfh_result, dict) and "data" in _rfh_result and "error" in _rfh_result)
check("get_metadata('raw_file_hashes'): no error for a valid range",
      _rfh_result["error"] is None)
check("get_metadata('raw_file_hashes'): one entry for the requested day",
      list(_rfh_result["data"].keys()) == [_TEST_DATE])
check("get_metadata('raw_file_hashes'): existing raw/ file yields a real hash string",
      isinstance(_rfh_result["data"][_TEST_DATE], str) and len(_rfh_result["data"][_TEST_DATE]) == 64)
check("get_metadata('raw_file_hashes'): delegates to metadata_map.get_raw_file_hashes()",
      _rfh_result == metadata_map.get_raw_file_hashes(_TEST_DATE, _TEST_DATE))

_rfh_missing_date = "2000-01-01"  # no raw/ file ever written for this date in this fixture
_rfh_missing_result = gateway_map.get_metadata(
    "raw_file_hashes", date_from=_rfh_missing_date, date_to=_rfh_missing_date)
check("get_metadata('raw_file_hashes'): day with no raw/ file yields hash None, not an error",
      _rfh_missing_result == {"data": {_rfh_missing_date: None}, "error": None})

check("get_metadata('stats'): delegates to metadata_map.get_stats()",
      gateway_map.get_metadata("stats") == metadata_map.get_stats())
check("get_metadata('daily_logs'): delegates to metadata_map.get_daily_logs()",
      gateway_map.get_metadata("daily_logs") == metadata_map.get_daily_logs())

# ── v1.7.1: filename-only kinds — same date_from/date_to forwarding as
#    their get_*_logs() siblings, verified against the same content
#    (excluding "data" itself, which naturally differs in shape —
#    filenames vs. sanitized lines — comparing the "error"/"note" keys
#    and delegation target is the actual contract here).
check("get_metadata('daily_log_filenames'): delegates to metadata_map.list_daily_log_filenames()",
      gateway_map.get_metadata("daily_log_filenames") ==
      metadata_map.list_daily_log_filenames())
check("get_metadata('fail_log_filenames'): delegates to metadata_map.list_fail_log_filenames()",
      gateway_map.get_metadata("fail_log_filenames") ==
      metadata_map.list_fail_log_filenames())
check("get_metadata('recent_log_filenames'): delegates to metadata_map.list_recent_log_filenames()",
      gateway_map.get_metadata("recent_log_filenames") ==
      metadata_map.list_recent_log_filenames())

# ── v1.7.2.3: context_resync_pending — internal-sync-only kind, same
#    category as the three filename-only kinds above. Content-level
#    checks here (missing/present/corrupt file), not just the shallow
#    envelope loop earlier in this section.
check("get_metadata('context_resync_pending'): delegates to "
      "metadata_map.get_context_resync_pending()",
      gateway_map.get_metadata("context_resync_pending") ==
      metadata_map.get_context_resync_pending())

_crp_path = cfg.CONTEXT_RESYNC_PENDING_FILE
check("get_context_resync_pending: no marker file yet — empty list, not an error",
      metadata_map.get_context_resync_pending() == {"data": [], "error": None})

_crp_path.parent.mkdir(parents=True, exist_ok=True)
_crp_path.write_text(
    json.dumps({"pending": [{"date": "2026-03-05", "source": "weather"}]}),
    encoding="utf-8")
check("get_context_resync_pending: existing marker — returns its pending list",
      metadata_map.get_context_resync_pending() ==
      {"data": [{"date": "2026-03-05", "source": "weather"}], "error": None})

_crp_path.write_text("{ not valid json", encoding="utf-8")
_crp_corrupt = metadata_map.get_context_resync_pending()
check("get_context_resync_pending: corrupt JSON — degrades to data=None, error set",
      _crp_corrupt["data"] is None and _crp_corrupt["error"] is not None)

_crp_path.unlink()  # restore no-marker state for any later section
check("get_metadata('daily_log_filenames', date_from/date_to): forwards to metadata_map",
      gateway_map.get_metadata("daily_log_filenames", date_from="2026-06-15", date_to="2026-06-16") ==
      metadata_map.list_daily_log_filenames(date_from="2026-06-15", date_to="2026-06-16"))

# ── v1.7.0.4: get_metadata() passes date_from/date_to through only for
#    the five date-filterable kinds; the four untouched kinds keep their
#    original, parameterless call signature exactly as before.
check("get_metadata('quality_log', date_from/date_to): forwards to metadata_map",
      gateway_map.get_metadata("quality_log", date_from="2026-06-15", date_to="2026-06-16") ==
      metadata_map.get_quality_log(date_from="2026-06-15", date_to="2026-06-16"))
check("get_metadata('stats', date_from/date_to): silently ignored, not a TypeError",
      gateway_map.get_metadata("stats", date_from="2026-06-15", date_to="2026-06-16") ==
      metadata_map.get_stats())

try:
    gateway_map.get_metadata("banana")
    check("get_metadata: unknown kind raises ValueError", False)
except ValueError:
    check("get_metadata: unknown kind raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  6. Bulk track in the intraday read (v1.7.6)
# ══════════════════════════════════════════════════════════════════════════════

section("6. garmin_health_map — bulk track for heart_rate_series (v1.7.6)")

import garmin_bulk_writer as _bw6
from datetime import datetime as _dt6, timezone as _tz6
from unittest.mock import patch as _patch6

_T6 = int(_dt6(2026, 5, 1, 22, 0, tzinfo=_tz6.utc).timestamp() * 1000)     # 22:00Z = 00:00 local on 2026-05-02 at +2 h
_BULK_VALUES6 = [[_T6, 61], [_T6 + 60000, 62], [_T6 + 120000, 64]]


def _put_raw6(day, doc):
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{day}.json").write_text(json.dumps({"date": day, **doc}), encoding="utf-8")


def _put_bulk6(day, offset=2.0, dst=False, values=None, schema=1, drop=(), raw_text=None):
    cfg.BULK_RAW_DIR.mkdir(parents=True, exist_ok=True)
    values = _BULK_VALUES6 if values is None else values
    doc = {"date": day, "schema_version": schema, "utc_offset_hours": offset, "utc_offset_end_hours": (offset + (1.0 if dst else 0.0)) if isinstance(offset, float) else offset,
           "dst_transition": dst, "offset_source": "prev_day_end", "source_files": ["a" * 64],
           "sections": {"intraday": {"heart_rate": {"count": len(values), "values": values}}}}
    for key in drop:
        doc.pop(key, None)
    (cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{day}.json").write_text(raw_text if raw_text is not None else json.dumps(doc), encoding="utf-8")


def _hr6(day, field="heart_rate_series"):
    return garmin_health_map.get(field, day, day, resolution="intraday")["values"][0]


_API_SERIES6 = [[_T6, 80], [_T6 + 60000, 81]]
_put_raw6("2026-05-01", {"heart_rates": {"startTimestampGMT": "2026-04-30T22:00:00.0", "startTimestampLocal": "2026-05-01T00:00:00.0",
                                         "endTimestampGMT": "2026-05-01T22:00:00.0", "endTimestampLocal": "2026-05-02T00:00:00.0",
                                         "heartRateValues": _API_SERIES6}})
_put_bulk6("2026-05-01", values=[[_T6, 99], [_T6 + 60000, 98], [_T6 + 120000, 97], [_T6 + 180000, 96]])      # fuller than the API day
_put_bulk6("2026-05-02")                                                                                      # bulk only, no raw file
_put_raw6("2026-05-03", {"heart_rates": {"heartRateValues": []}})
_put_bulk6("2026-05-03")
_put_raw6("2026-05-04", {"stats": {"totalSteps": 1}})
_put_bulk6("2026-05-04")
_put_raw6("2026-05-05", {"stats": {"totalSteps": 1}})                                                         # raw, nothing else
_put_bulk6("2026-05-06", offset=1.0, dst=True)
_put_bulk6("2026-05-07", raw_text="{ not json")
_put_bulk6("2026-05-08", schema=2)
_put_bulk6("2026-05-09", drop=("utc_offset_hours",))
_put_bulk6("2026-05-10", raw_text="{ not json")
_put_raw6("2026-05-10", {"heart_rates": {"heartRateValues": []}})
_put_bulk6("2026-05-11", drop=("sections",))
_put_bulk6("2026-05-12", offset="two")
_put_bulk6("2026-05-13", values=[])
_put_bulk6("2026-05-15", values="oops")
_put_bulk6("2026-05-16", values=[[_T6, None]])
_put_bulk6("2026-05-17", schema=0)
_put_bulk6("2026-05-18", schema=True)
_put_raw6("2026-05-23", {"stats": {"totalSteps": 1}})
_put_bulk6("2026-05-14")
_put_raw6("2026-05-14", {"stress": {"stressValuesArray": [[_T6, 25]], "stressChartValueOffset": 0}})

# the day the API has: the API wins, the bulk day is not even read
with _patch6.object(garmin_health_map, "_read_bulk_series", wraps=garmin_health_map._read_bulk_series) as _rb:
    _e_api = _hr6("2026-05-01")
check("bulk track: a day the API has a series for -> source 'api', the bulk file is not read", _e_api["series_source"] == "api" and _rb.call_count == 0)
check("bulk track: ... with the API's own values, even though the bulk day is fuller",
      [p["value"] for p in _e_api["series"]] == [80.0, 81.0])
check("bulk track: ... shifted by the API day's own offset pair (+2 h: 22:00Z = 00:00 local)", _e_api["series"][0]["ts"] == "2026-05-02T00:00:00")

_e_b = _hr6("2026-05-02")
check("bulk track: no raw file, a bulk day -> source 'bulk'", _e_b["series_source"] == "bulk" and len(_e_b["series"]) == 3)
check("bulk track: the series has the form of an API series: {'ts', 'value'} with a float value",
      all(set(p) == {"ts", "value"} and isinstance(p["value"], float) for p in _e_b["series"]))
check("bulk track: the offset of the silo head is applied (22:00Z + 2 h = 00:00 local)",
      [p["ts"] for p in _e_b["series"]] == ["2026-05-02T00:00:00", "2026-05-02T00:01:00", "2026-05-02T00:02:00"]
      and [p["value"] for p in _e_b["series"]] == [61.0, 62.0, 64.0])
check("bulk track: the entry keeps its keys date, series, dst_transition and adds series_source",
      set(_e_b) == {"date", "series", "dst_transition", "series_source"} and _e_b["date"] == "2026-05-02" and _e_b["dst_transition"] is False)
check("bulk track: an API day empty after normalising ([]) -> bulk", _hr6("2026-05-03")["series_source"] == "bulk")
check("bulk track: a raw file without the heart-rate section -> bulk", _hr6("2026-05-04")["series_source"] == "bulk")

_e_none = _hr6("2026-05-05")
check("bulk track: a raw file and no bulk day -> series None, source None, as before",
      _e_none["series"] is None and _e_none["series_source"] is None and _e_none["dst_transition"] is False)
_e_nothing = _hr6("2026-05-20")
check("bulk track: no file at all -> series None, source None", _e_nothing["series"] is None and _e_nothing["series_source"] is None)

_e_dst = _hr6("2026-05-06")
check("bulk track: a day with a time change in the silo head -> dst_transition True, the start-of-day offset (+1 h) is used",
      _e_dst["dst_transition"] is True and _e_dst["series_source"] == "bulk"
      and _e_dst["series"][0]["ts"] == "2026-05-01T23:00:00")

with _patch6.object(garmin_health_map.log, "warning") as _warn6:
    for _day6, _why6 in (("2026-05-07", "damaged JSON"), ("2026-05-08", "a newer schema_version"), ("2026-05-09", "no utc_offset_hours"),
                         ("2026-05-11", "no sections"), ("2026-05-12", "an offset that is not a number"),
                         ("2026-05-15", "samples that are not a list"), ("2026-05-17", "schema_version 0"),
                         ("2026-05-18", "schema_version true")):
        _e6 = _hr6(_day6)
        check(f"bulk track: {_why6} -> as if there were no bulk day, no exception", _e6["series"] is None and _e6["series_source"] is None)
    _bulk_warns6 = lambda: [c for c in _warn6.call_args_list if "bulk day" in str(c)]      # noqa: E731  (the API read warns about its own offsets too)
    check("bulk track: a bulk day that cannot be used is a warning in the log", len(_bulk_warns6()) == 8)
    _warn6.reset_mock()
    _hr6("2026-05-07")
    _hr6("2026-05-07", "heart_rate_series")
    check("bulk track: ... once per day and process, not again at the next read", len(_bulk_warns6()) == 0)
    _warn6.reset_mock()
    _hr6("2026-05-21")                  # days nobody has read before: no file at all, a raw file only, a usable bulk day
    _hr6("2026-05-23")
    _hr6("2026-05-02")
    check("bulk track: a day without a bulk day, and a usable one, give no warning about a bulk day", len(_bulk_warns6()) == 0)
_e_eb = _hr6("2026-05-10")
check("bulk track: an empty API series and an unusable bulk day -> the API's [] stays, source None",
      _e_eb["series"] == [] and _e_eb["series_source"] is None)
_ex6 = garmin_health_map._FIELD_MAP["heart_rate_series"]["intraday"][2]
check("bulk track: samples that all drop out (no value) are not a series: the helper gives None, not []",
      garmin_health_map._read_bulk_series("heart_rate_series", "2026-05-16", _ex6) is None)
check("bulk track: the helper does not read the heart-rate samples for a field that has no bulk track",
      garmin_health_map._read_bulk_series("stress_series", "2026-05-02", _ex6) is None)
_e_empty6 = _hr6("2026-05-13")
check("bulk track: a bulk day without samples is not a series (None, source None)", _e_empty6["series"] is None and _e_empty6["series_source"] is None)

check("bulk track: stress_series never asks the bulk store, even where a bulk day exists",
      _hr6("2026-05-02", "stress_series")["series"] is None and _hr6("2026-05-02", "stress_series")["series_source"] is None)
check("bulk track: ... but carries series_source 'api' where the API has a stress series", _hr6("2026-05-14", "stress_series")["series_source"] == "api")
check("bulk track: the other intraday fields carry series_source too (None without data)",
      all("series_source" in garmin_health_map.get(f, "2026-05-20", "2026-05-20", resolution="intraday")["values"][0]
          for f in ("stress_series", "spo2_series", "respiration_series", "body_battery_series", "steps_series")))
check("bulk track: only heart_rate_series has a bulk track", garmin_health_map._SERIES_TRACKS == {"heart_rate_series": ("api", "bulk")})
check("bulk track: the schema version the reader accepts is the one the writer writes", garmin_health_map._BULK_MAX_SCHEMA == _bw6.BULK_SCHEMA_VERSION)

_range6 = garmin_health_map.get("heart_rate_series", "2026-05-01", "2026-05-03", resolution="intraday")
check("bulk track: a range gives every day in order with its own source",
      [(e["date"], e["series_source"]) for e in _range6["values"]] == [("2026-05-01", "api"), ("2026-05-02", "bulk"), ("2026-05-03", "bulk")]
      and _range6["source_resolution"] == "intraday" and _range6["fallback"] is False)
_via6 = health_map.get("heart_rate_series", "2026-05-02", "2026-05-02", resolution="intraday")
check("bulk track: through health_map and gateway_map the key arrives unchanged",
      _via6["garmin"]["values"][0]["series_source"] == "bulk"
      and gateway_map.get("heart_rate_series", "2026-05-02", "2026-05-02", resolution="intraday")["health"]["garmin"]["values"][0]["series_source"] == "bulk")
check("bulk track: the daily read is untouched (heart_rate_series has no daily form: falls back to intraday as before)",
      garmin_health_map.get("heart_rate_series", "2026-05-02", "2026-05-02", resolution="daily")["fallback"] is True)

shutil.rmtree(cfg.BULK_RAW_DIR, ignore_errors=True)
check("bulk track: without a bulk store at all the read is as before",
      _hr6("2026-05-02")["series"] is None and _hr6("2026-05-02")["series_source"] is None and _hr6("2026-05-01")["series_source"] == "api")


# ══════════════════════════════════════════════════════════════════════════════
#  7. Stress durations from bulk/aggregates (v1.7.6.1)
# ══════════════════════════════════════════════════════════════════════════════

section("7. garmin_health_map — stress durations from bulk/aggregates (v1.7.6.1)")

_DUR_FIELDS = {"stress_rest_duration": "restDuration", "stress_low_duration": "lowDuration",
               "stress_medium_duration": "mediumDuration", "stress_high_duration": "highDuration"}


def _put_agg7(day, aggregates=None, schema=1, raw_text=None, doc=None):
    cfg.BULK_AGG_DIR.mkdir(parents=True, exist_ok=True)
    body = doc if doc is not None else {"date": day, "schema_version": schema, "generated_by": "t", "origin": "garmin_export",
                                       "imported_at": "2026-10-18", "source_files": ["a" * 64], "aggregates": aggregates}
    (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{day}.json").write_text(raw_text if raw_text is not None else json.dumps(body), encoding="utf-8")


def _dur7(day, field="stress_rest_duration", resolution="daily"):
    return garmin_health_map.get(field, day, day, resolution=resolution)


_STRESS7 = {"averageStressLevel": 30, "maxStressLevel": 90, "stressDuration": 12000,
            "restDuration": 30000, "lowDuration": 7000, "mediumDuration": 4000, "highDuration": 1000}
_put_agg7("2026-06-01", {"date": "2026-06-01", "stress": _STRESS7})
_put_agg7("2026-06-02", {"stress": {"restDuration": 0, "lowDuration": 3600.5, "mediumDuration": None}})
_put_agg7("2026-06-03", {"user_summary": {"totalSteps": 5}})
_put_agg7("2026-06-04", {"stress": {"restDuration": "30000", "lowDuration": True, "mediumDuration": [1], "highDuration": {"a": 1}}})
_put_agg7("2026-06-05", raw_text="{ not json")
_put_agg7("2026-06-06", {"stress": _STRESS7}, schema=2)
_put_agg7("2026-06-07", raw_text=json.dumps([1, 2]))
_put_agg7("2026-06-08", {"stress": _STRESS7}, doc={"date": "2026-06-08", "schema_version": 1, "aggregates": "oops"})
_put_agg7("2026-06-09", {"stress": _STRESS7}, schema=0)
_put_agg7("2026-06-11", {"stress": _STRESS7}, schema=True)
_put_agg7("2026-06-12", {"stress": "oops"})
_put_agg7("2026-06-13", {"stress": {"restDuration": -5}})

check("stress durations: the four fields are registered, with no daily and no intraday form and a bulk_daily descriptor",
      all(f in garmin_health_map.list_fields() and garmin_health_map._FIELD_MAP[f]
          == {"intraday": None, "daily": None, "bulk_daily": ("stress", k)} for f, k in _DUR_FIELDS.items()))
check("stress durations: stressDuration (low + medium + high) is not a field of its own",
      not any(f for f in garmin_health_map.list_fields() if f in ("stress_duration", "stress_total_duration")))
_d1 = {f: _dur7("2026-06-01", f) for f in _DUR_FIELDS}
check("stress durations: a day with a stress object gives each field its number (seconds)",
      [_d1[f]["values"][0]["value"] for f in _DUR_FIELDS] == [30000, 7000, 4000, 1000])
check("stress durations: the answer has the form of a daily field: values [{date, value}], source_resolution daily, fallback False",
      all(set(r) == {"values", "source_resolution", "fallback"} and r["source_resolution"] == "daily" and r["fallback"] is False
          and set(r["values"][0]) == {"date", "value"} and r["values"][0]["date"] == "2026-06-01" for r in _d1.values()))
check("stress durations: 0 and a float are numbers and are returned as they are; null gives None",
      _dur7("2026-06-02", "stress_rest_duration")["values"][0]["value"] == 0
      and _dur7("2026-06-02", "stress_low_duration")["values"][0]["value"] == 3600.5
      and _dur7("2026-06-02", "stress_medium_duration")["values"][0]["value"] is None
      and _dur7("2026-06-02", "stress_high_duration")["values"][0]["value"] is None)
check("stress durations: a negative number is returned as it is (the broker does not judge values)",
      _dur7("2026-06-13")["values"][0]["value"] == -5)
check("stress durations: no file, no stress object (only other sections) and a stress object that is not an object give None",
      all(_dur7(d)["values"][0]["value"] is None for d in ("2026-06-10", "2026-06-03", "2026-06-12")))
check("stress durations: a text, a boolean, a list and an object are not numbers: None",
      all(_dur7("2026-06-04", f)["values"][0]["value"] is None for f in _DUR_FIELDS))

with _patch6.object(garmin_health_map.log, "warning") as _warn7:
    _unusable7 = ("2026-06-05", "2026-06-06", "2026-06-07", "2026-06-08", "2026-06-09", "2026-06-11")
    check("stress durations: a damaged file, a newer schema_version, a non-object, no aggregates object, schema_version 0 and true give None, no exception",
          all(_dur7(d)["values"][0]["value"] is None for d in _unusable7))
    _agg_warns7 = lambda: [c for c in _warn7.call_args_list if "daily values" in str(c)]      # noqa: E731
    check("stress durations: each day that cannot be used is one warning, naming the day", len(_agg_warns7()) == 6
          and all(any(d in str(c) for c in _agg_warns7()) for d in _unusable7))
    _warn7.reset_mock()
    for _d in _unusable7:
        _dur7(_d, "stress_high_duration")
    check("stress durations: ... once per day and process, not again at the next read (also not for another field)", len(_agg_warns7()) == 0)
    _warn7.reset_mock()
    for _d in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-10", "2026-06-12", "2026-06-13"):
        _dur7(_d)
    check("stress durations: usable days, days without a value and a missing file give no warning", len(_warn7.call_args_list) == 0)
    _put_bulk6("2026-06-05", raw_text="{ not json")
    _warn7.reset_mock()
    _hr6("2026-06-05")
    check("stress durations: a day damaged in bulk/raw has its own warning, apart from the one of its daily values (own key)",
          len([c for c in _warn7.call_args_list if "bulk day 2026-06-05 not used" in str(c) and "daily values" not in str(c)]) == 1)

check("stress durations: the schema version the reader accepts is the one the writer writes",
      garmin_health_map._BULK_AGG_MAX_SCHEMA == _bw6.AGG_SCHEMA_VERSION)
_r7 = garmin_health_map.get("stress_low_duration", "2026-06-01", "2026-06-04", resolution="daily")
check("stress durations: a range gives every day in order, with None where there is nothing",
      [(e["date"], e["value"]) for e in _r7["values"]] == [("2026-06-01", 7000), ("2026-06-02", 3600.5), ("2026-06-03", None), ("2026-06-04", None)])
_i7 = garmin_health_map.get("stress_low_duration", "2026-06-01", "2026-06-01", resolution="intraday")
check("stress durations: an intraday request gets the daily values with fallback True, as every daily field does",
      _i7["fallback"] is True and _i7["source_resolution"] == "daily" and _i7["values"][0]["value"] == 7000)
check("stress durations: a live request gives no values and fallback True, as every field without a live form does",
      garmin_health_map.get("stress_low_duration", "2026-06-01", "2026-06-01", resolution="live")
      == {"values": [], "fallback": True, "source_resolution": "live"})
check("stress durations: through health_map and gateway_map the values arrive unchanged",
      health_map.get("stress_medium_duration", "2026-06-01", "2026-06-01")["garmin"]["values"][0]["value"] == 4000
      and gateway_map.get("stress_high_duration", "2026-06-01", "2026-06-01")["health"]["garmin"]["values"][0]["value"] == 1000)
check("stress durations: the existing daily read of stress_avg is untouched (summary/, not the aggregates)",
      garmin_health_map.get("stress_avg", "2026-06-01", "2026-06-01")["values"][0]["value"] is None
      and garmin_health_map.get("stress_avg", "2026-06-01", "2026-06-01")["fallback"] is False)
try:
    garmin_health_map.get("stress_low_duration", "2026-06-01", "2026-06-01", resolution="weekly")
    check("stress durations: an unknown resolution still raises ValueError", False)
except ValueError:
    check("stress durations: an unknown resolution still raises ValueError", True)

shutil.rmtree(cfg.BULK_AGG_DIR, ignore_errors=True)
check("stress durations: without a bulk store at all the values are None, no exception",
      all(_dur7("2026-06-01", f)["values"][0]["value"] is None for f in _DUR_FIELDS))


# ══════════════════════════════════════════════════════════════════════════════
#  8. Sleep percentages: raw/ first, bulk/aggregates for a day without usable raw data (v1.7.6.1)
# ══════════════════════════════════════════════════════════════════════════════

section("8. garmin_health_map — sleep percentages with the export as second source (v1.7.6.1)")

_PCT_FIELDS = ("sleep_deep_pct", "sleep_light_pct", "sleep_rem_pct", "sleep_awake_pct")


def _dto8(total, deep=None, light=None, rem=None, awake=None):
    return {"sleepTimeSeconds": total, "deepSleepSeconds": deep, "lightSleepSeconds": light,
            "remSleepSeconds": rem, "awakeSleepSeconds": awake}


def _raw8(day, sleep="ABSENT", raw_text=None):
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"date": day, "stats": {"totalSteps": 1}}
    if sleep != "ABSENT":
        doc["sleep"] = sleep
    (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{day}.json").write_text(raw_text if raw_text is not None else json.dumps(doc), encoding="utf-8")


def _pct8(day, field="sleep_deep_pct"):
    return garmin_health_map.get(field, day, day, resolution="daily")["values"][0]["value"]


def _all8(day):
    return [_pct8(day, f) for f in _PCT_FIELDS]


_USABLE8 = _dto8(27000, 5400, 13500, 6750, 1350)                 # 20.0 / 50.0 / 25.0 / 5.0 %
_EXPORT8 = _dto8(3000, 1000, 1200, 500, 300)                      # 33.3 / 40.0 / 16.7 / 10.0 %
_EX_PCT8 = [33.3, 40.0, 16.7, 10.0]

_raw8("2026-07-01", {"dailySleepDTO": _USABLE8}); _put_agg7("2026-07-01", {"sleep": {"dailySleepDTO": _dto8(18000, 9000, 4500, 3600, 900)}})
_put_agg7("2026-07-02", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-03");                                      _put_agg7("2026-07-03", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-04", {"dailySleepDTO": _dto8(None)});      _put_agg7("2026-07-04", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-05", {"dailySleepDTO": _dto8(0, 0, 0, 0, 0)}); _put_agg7("2026-07-05", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-06", {"dailySleepDTO": _dto8(27000, 5400, 13500, None, 1350)}); _put_agg7("2026-07-06", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-07", raw_text="{ not json");                _put_agg7("2026-07-07", {"sleep": {"dailySleepDTO": _EXPORT8}})
_put_agg7("2026-07-08", raw_text="{ not json")
_put_agg7("2026-07-09", {"sleep": {"dailySleepDTO": _EXPORT8}}, schema=2)
_put_agg7("2026-07-10", {"user_summary": {"totalSteps": 5}})
_put_agg7("2026-07-11", {"sleep": {"dailySleepDTO": _dto8(None, 1000, 1200, 500, 300)}})
_put_agg7("2026-07-12", {"sleep": {"dailySleepDTO": _dto8(0, 1000, 1200, 500, 300)}})
_put_agg7("2026-07-13", {"sleep": {"dailySleepDTO": _dto8(True, 1000, 1200, 500, 300)}})
_put_agg7("2026-07-14", {"sleep": {"dailySleepDTO": _dto8("3000", 1000, 1200, 500, 300)}})
_put_agg7("2026-07-15", {"sleep": {"dailySleepDTO": _dto8(3000, "x", 1200, True, None)}})
_raw8("2026-07-16", None);                                _put_agg7("2026-07-16", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-17", {"dailySleepDTO": "oops"});           _put_agg7("2026-07-17", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-18", {"dailySleepDTO": _dto8(-5, 1, 1, 1, 1)}); _put_agg7("2026-07-18", {"sleep": {"dailySleepDTO": _EXPORT8}})
_raw8("2026-07-19", {"dailySleepDTO": _dto8(4000, 1000, 1000, 1000, 1000)}); _put_agg7("2026-07-19", {"sleep": {"dailySleepDTO": _dto8(None)}})
_put_agg7("2026-07-20", {"stress": {"restDuration": 7}})

check("sleep pct: a raw/ day with a usable total wins over the export, all four fields (20.0 / 50.0 / 25.0 / 5.0)",
      _all8("2026-07-01") == [20.0, 50.0, 25.0, 5.0])
check("sleep pct: a day without a raw file takes the export's object, rounded to one decimal",
      _all8("2026-07-02") == _EX_PCT8)
check("sleep pct: a raw file without a sleep section, with a total of null, with a total of 0 takes the export's object",
      _all8("2026-07-03") == _EX_PCT8 and _all8("2026-07-04") == _EX_PCT8 and _all8("2026-07-05") == _EX_PCT8)
check("sleep pct: a raw file whose sleep is null, or whose object is not an object, takes the export's object (no exception)",
      _all8("2026-07-16") == _EX_PCT8 and _all8("2026-07-17") == _EX_PCT8)
check("sleep pct: a negative total in raw/ is not usable: the export's object",
      _all8("2026-07-18") == _EX_PCT8)
check("sleep pct: one source per day — raw/ has a total but no REM seconds: REM stays None, the export's REM is not mixed in",
      _all8("2026-07-06") == [20.0, 50.0, None, 5.0])
check("sleep pct: raw/ usable and an export object without a total: raw/ stays",
      _all8("2026-07-19") == [25.0, 25.0, 25.0, 25.0])

with _patch6.object(garmin_health_map.log, "warning") as _warn8:
    _e7 = _all8("2026-07-07")
    check("sleep pct: a raw file that cannot be read is a warning (as before), the export's object is used",
          _e7 == _EX_PCT8 and any("could not read" in str(c) and "2026-07-07" in str(c) for c in _warn8.call_args_list))
    _warn8.reset_mock()
    _unusable8 = ("2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13", "2026-07-14")
    check("sleep pct: no raw file and an export day that cannot be used (damaged, newer schema, no sleep section) or has no usable total "
          "(null, 0, true, text) -> None for all four fields, no exception",
          all(_all8(d) == [None] * 4 for d in _unusable8))
    _agg_warn8 = [c for c in _warn8.call_args_list if "daily values" in str(c)]
    check("sleep pct: the two export days that cannot be used (damaged, newer schema) give one warning each, naming the day",
          len(_agg_warn8) == 2 and any("2026-07-08" in str(c) for c in _agg_warn8) and any("2026-07-09" in str(c) for c in _agg_warn8))
    _warn8.reset_mock()
    _all8("2026-07-08"); _all8("2026-07-09")
    check("sleep pct: ... once per day and process", len([c for c in _warn8.call_args_list if "daily values" in str(c)]) == 0)

check("sleep pct: seconds that are not numbers (text, true) give None for that field, the others are calculated",
      _all8("2026-07-15") == [None, 40.0, None, None])
check("sleep pct: neither a raw file nor an export day -> None", _all8("2026-07-31") == [None] * 4)
check("sleep pct: the answer has the form it had: values [{date, value}], source_resolution daily, fallback False",
      all(set(garmin_health_map.get(f, "2026-07-02", "2026-07-02", resolution="daily")) == {"values", "source_resolution", "fallback"}
          and garmin_health_map.get(f, "2026-07-02", "2026-07-02")["fallback"] is False
          and set(garmin_health_map.get(f, "2026-07-02", "2026-07-02")["values"][0]) == {"date", "value"} for f in _PCT_FIELDS))
_r8 = garmin_health_map.get("sleep_light_pct", "2026-07-01", "2026-07-03", resolution="daily")
check("sleep pct: a range gives every day in order, each from its own source (raw/, export, export)",
      [(e["date"], e["value"]) for e in _r8["values"]] == [("2026-07-01", 50.0), ("2026-07-02", 40.0), ("2026-07-03", 40.0)])
check("sleep pct: through health_map and gateway_map the value arrives unchanged",
      health_map.get("sleep_deep_pct", "2026-07-02", "2026-07-02")["garmin"]["values"][0]["value"] == 33.3
      and gateway_map.get("sleep_deep_pct", "2026-07-02", "2026-07-02")["health"]["garmin"]["values"][0]["value"] == 33.3)
check("sleep pct: the live request does not read the archive (unchanged)",
      garmin_health_map.get("sleep_deep_pct", "2026-07-02", "2026-07-02", resolution="live")["source_resolution"] == "live")
check("sleep pct: the stress durations still read bulk/aggregates after the loader was split out",
      _dur7("2026-07-02", "stress_rest_duration")["values"][0]["value"] is None
      and _dur7("2026-07-20", "stress_rest_duration")["values"][0]["value"] == 7)

shutil.rmtree(cfg.BULK_AGG_DIR, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════

shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
