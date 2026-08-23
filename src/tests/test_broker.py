#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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

_CONTEXT_FIXTURES = {
    "weather": {
        "dir":    cfg.CONTEXT_WEATHER_DIR,
        "prefix": "weather_",
        "fields": {
            "temperature_2m_max": 25.0,
            "wind_speed_10m_max": 18.5,
        },
    },
    "pollen": {
        "dir":    cfg.CONTEXT_POLLEN_DIR,
        "prefix": "pollen_",
        "fields": {
            "birch_pollen": 3.0,
        },
    },
    "brightsky": {
        "dir":    cfg.CONTEXT_BRIGHTSKY_DIR,
        "prefix": "brightsky_",
        "fields": {
            "wind_speed": 22.0,
        },
    },
    "airquality": {
        "dir":    cfg.CONTEXT_AIRQUALITY_DIR,
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

check("health_map list_raw_fields: garmin → 13 fields",
      len(health_map.list_raw_fields(source="garmin")) == 13)
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

check("context_map list_fields: default source=weather → 6 fields",
      len(context_map.list_fields()) == 6)
check("context_map list_fields: pollen → 6 fields",
      len(context_map.list_fields("pollen")) == 6)
check("context_map list_fields: brightsky → 9 fields",
      len(context_map.list_fields("brightsky")) == 9)
check("context_map list_fields: airquality → 5 fields",
      len(context_map.list_fields("airquality")) == 5)
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
check("gateway_map list_raw_fields domain=health: 13 fields",
      len(_gw_lrf_health["health"]) == 13)

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

check("get_daily_logs: missing dir → empty list, no error",
      metadata_map.get_daily_logs() == {"data": [], "error": None})
check("get_fail_logs: missing dir → empty list, no error",
      metadata_map.get_fail_logs() == {"data": [], "error": None})
check("get_recent_logs: missing dir → empty list, no error",
      metadata_map.get_recent_logs() == {"data": [], "error": None})

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
check("get_quality_log: happy path → real content",
      metadata_map.get_quality_log() == {"data": _QUALITY_LOG_FIXTURE, "error": None})

check("get_stats: happy path → real content", metadata_map.get_stats() == {
    "data": {
        "total": 2, "high": 1, "standard": 1, "failed": 0, "recheck": 1,
        "missing": 0, "date_min": "2026-03-01", "date_max": "2026-03-02",
        "coverage_pct": 100, "last_api": "2026-03-01", "last_bulk": "2026-03-02",
        "integrity_warnings": [],
    },
    "error": None,
})

_SOURCE_API_LOG_FIXTURE = {"calls": [{"date": "2026-03-01", "status": "ok"}]}
cfg.SOURCE_API_LOG.write_text(json.dumps(_SOURCE_API_LOG_FIXTURE), encoding="utf-8")
check("get_source_api_log: happy path → real content",
      metadata_map.get_source_api_log() == {"data": _SOURCE_API_LOG_FIXTURE, "error": None})

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

cfg.LOG_DAILY_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_DAILY_DIR / "2026-03-01.log").write_text(
    "sync completed successfully\n"
    "password: hunter2 — should be dropped entirely\n"
    "user contact: foo@bar.com from 10.0.0.5\n",
    encoding="utf-8",
)
(cfg.LOG_DAILY_DIR / "2026-03-02.log").write_text("second file, second line\n", encoding="utf-8")
(cfg.LOG_DAILY_DIR / "notes.txt").write_text("not a .log file — must be ignored\n", encoding="utf-8")
(cfg.LOG_DAILY_DIR / "broken.log").mkdir()  # directory named *.log — open() raises OSError, must be skipped

_daily = metadata_map.get_daily_logs()
check("get_daily_logs: error is None",               _daily["error"] is None)
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

cfg.LOG_FAIL_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_FAIL_DIR / "fail.log").write_text("fail entry, nothing sensitive\n", encoding="utf-8")
check("get_fail_logs: reads its own directory, sanitized",
      metadata_map.get_fail_logs() == {"data": ["fail entry, nothing sensitive"], "error": None})

cfg.LOG_RECENT_DIR.mkdir(parents=True, exist_ok=True)
(cfg.LOG_RECENT_DIR / "recent.log").write_text("recent entry, nothing sensitive\n", encoding="utf-8")
check("get_recent_logs: reads its own directory, sanitized",
      metadata_map.get_recent_logs() == {"data": ["recent entry, nothing sensitive"], "error": None})

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

_expected_kinds = {
    "stats", "device_table", "quality_log", "source_api_log", "token_log",
    "capability_config", "daily_logs", "fail_logs", "recent_logs",
}
check("list_metadata_kinds: exactly the nine registered kinds",
      set(gateway_map.list_metadata_kinds()) == _expected_kinds)

for _kind in sorted(_expected_kinds):
    _result = gateway_map.get_metadata(_kind)
    check(f"get_metadata({_kind!r}): returns data/error envelope",
          isinstance(_result, dict) and "data" in _result and "error" in _result)

check("get_metadata('stats'): delegates to metadata_map.get_stats()",
      gateway_map.get_metadata("stats") == metadata_map.get_stats())
check("get_metadata('daily_logs'): delegates to metadata_map.get_daily_logs()",
      gateway_map.get_metadata("daily_logs") == metadata_map.get_daily_logs())

try:
    gateway_map.get_metadata("banana")
    check("get_metadata: unknown kind raises ValueError", False)
except ValueError:
    check("get_metadata: unknown kind raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════

shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
