#!/usr/bin/env python3
"""
test_local_context.py — Garmin Local Archive — Context Pipeline Test

Run from the project folder:
    python tests/test_local_context.py

No external dependencies beyond what the project already requires.
No network calls — Open-Meteo API is mocked.
No GUI, no Garmin API calls.
Cleans up after itself — leaves no files behind.
"""

import json
import os
import sys
import shutil
import tempfile
import logging
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Path setup ─────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
sys.path.insert(0, str(Path(__file__).parent.parent))
logging.disable(logging.CRITICAL)

# ── Results tracking ───────────────────────────────────────────────────────────
_pass = 0
_fail = 0
_failures = []

def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✓  {name}")
    else:
        _fail += 1
        _failures.append(name)
        print(f"  ✗  {name}")

def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

# ── Temp directory ─────────────────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_context_test_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)

import importlib
import garmin_config as cfg
importlib.reload(cfg)

# ── Import context modules ─────────────────────────────────────────────────────
from context import weather_plugin, pollen_plugin
from context import context_api, context_writer, context_collector
from maps import weather_map, pollen_map, context_map


# ══════════════════════════════════════════════════════════════════════════════
#  1. garmin_config — context paths
# ══════════════════════════════════════════════════════════════════════════════
section("1. garmin_config — context paths")

check("CONTEXT_DIR derived",         cfg.CONTEXT_DIR         == _TMPDIR / "context_data")
check("CONTEXT_WEATHER_DIR derived", cfg.CONTEXT_WEATHER_DIR == _TMPDIR / "context_data" / "weather" / "raw")
check("CONTEXT_POLLEN_DIR derived",  cfg.CONTEXT_POLLEN_DIR  == _TMPDIR / "context_data" / "pollen"  / "raw")
check("LOCAL_CONFIG_FILE derived",   cfg.LOCAL_CONFIG_FILE   == _TMPDIR / "local_config.csv")
check("CONTEXT_LATITUDE default",    isinstance(cfg.CONTEXT_LATITUDE,  float))
check("CONTEXT_LONGITUDE default",   isinstance(cfg.CONTEXT_LONGITUDE, float))


# ══════════════════════════════════════════════════════════════════════════════
#  2. Plugin metadata — weather
# ══════════════════════════════════════════════════════════════════════════════
section("2. Plugin metadata — weather_plugin")

check("NAME = weather",              weather_plugin.NAME == "weather")
check("API_URL_HISTORICAL set",      weather_plugin.API_URL_HISTORICAL.startswith("https://"))
check("API_URL_FORECAST set",        weather_plugin.API_URL_FORECAST.startswith("https://"))
check("API_RESOLUTION = daily",      weather_plugin.API_RESOLUTION == "daily")
check("API_FIELDS is list",          isinstance(weather_plugin.API_FIELDS, list))
check("API_FIELDS not empty",        len(weather_plugin.API_FIELDS) > 0)
check("OUTPUT_DIR is Path",          isinstance(weather_plugin.OUTPUT_DIR, Path))
check("FILE_PREFIX set",             weather_plugin.FILE_PREFIX == "weather_")
check("SOURCE_TAG set",              weather_plugin.SOURCE_TAG == "open-meteo-weather")
check("CHUNK_DAYS > 0",              weather_plugin.CHUNK_DAYS > 0)


# ══════════════════════════════════════════════════════════════════════════════
#  3. Plugin metadata — pollen
# ══════════════════════════════════════════════════════════════════════════════
section("3. Plugin metadata — pollen_plugin")

check("NAME = pollen",               pollen_plugin.NAME == "pollen")
check("API_URL_HISTORICAL set",      pollen_plugin.API_URL_HISTORICAL.startswith("https://"))
check("API_RESOLUTION = hourly",     pollen_plugin.API_RESOLUTION == "hourly")
check("API_FIELDS is list",          isinstance(pollen_plugin.API_FIELDS, list))
check("API_FIELDS not empty",        len(pollen_plugin.API_FIELDS) > 0)
check("OUTPUT_DIR is Path",          isinstance(pollen_plugin.OUTPUT_DIR, Path))
check("FILE_PREFIX set",             pollen_plugin.FILE_PREFIX == "pollen_")
check("SOURCE_TAG set",              pollen_plugin.SOURCE_TAG == "open-meteo-pollen")
check("AGGREGATION = daily_max",     pollen_plugin.AGGREGATION == "daily_max")
check("CHUNK_DAYS > 0",              pollen_plugin.CHUNK_DAYS > 0)


# ══════════════════════════════════════════════════════════════════════════════
#  4. context_writer — write + already_written
# ══════════════════════════════════════════════════════════════════════════════
section("4. context_writer")

# Override OUTPUT_DIR to temp
import types
_fake_weather_plugin = types.SimpleNamespace(
    NAME        = "weather",
    SOURCE_TAG  = "open-meteo-weather",
    FILE_PREFIX = "weather_",
    OUTPUT_DIR  = _TMPDIR / "context_data" / "weather" / "raw",
    AGGREGATION = None,
)
_fake_pollen_plugin = types.SimpleNamespace(
    NAME        = "pollen",
    SOURCE_TAG  = "open-meteo-pollen",
    FILE_PREFIX = "pollen_",
    OUTPUT_DIR  = _TMPDIR / "context_data" / "pollen" / "raw",
    AGGREGATION = "daily_max",
)

_weather_data = {
    "2026-01-01": {"temperature_2m_max": 5.2, "temperature_2m_min": -1.1,
                   "precipitation_sum": 0.0,  "wind_speed_10m_max": 12.3,
                   "uv_index_max": 1.2,        "sunshine_duration": 3600.0},
    "2026-01-02": {"temperature_2m_max": 7.0, "temperature_2m_min": 1.0,
                   "precipitation_sum": 2.5,  "wind_speed_10m_max": 8.0,
                   "uv_index_max": 0.8,        "sunshine_duration": 0.0},
}
_pollen_data = {
    "2026-01-01": {"birch_pollen": 0.0, "grass_pollen": 0.0, "alder_pollen": 5.2,
                   "mugwort_pollen": 0.0, "olive_pollen": 0.0, "ragweed_pollen": 0.0},
}

result_w = context_writer.write(_fake_weather_plugin, _weather_data, 52.11, 8.67)
check("write weather: written=2",    result_w["written"] == 2)
check("write weather: failed=0",     result_w["failed"]  == 0)

f1 = _fake_weather_plugin.OUTPUT_DIR / "weather_2026-01-01.json"
f2 = _fake_weather_plugin.OUTPUT_DIR / "weather_2026-01-02.json"
check("weather file 1 exists",       f1.exists())
check("weather file 2 exists",       f2.exists())

data1 = json.loads(f1.read_text(encoding="utf-8"))
check("weather file 1: date correct",   data1["date"]   == "2026-01-01")
check("weather file 1: source correct", data1["source"] == "open-meteo-weather")
check("weather file 1: lat correct",    data1["latitude"]  == 52.11)
check("weather file 1: lon correct",    data1["longitude"] == 8.67)
check("weather file 1: fields dict",    isinstance(data1["fields"], dict))
check("weather file 1: temp_max value", data1["fields"]["temperature_2m_max"] == 5.2)
check("weather file 1: no aggregation", "aggregation" not in data1)

result_p = context_writer.write(_fake_pollen_plugin, _pollen_data, 52.11, 8.67)
check("write pollen: written=1",     result_p["written"] == 1)

fp = _fake_pollen_plugin.OUTPUT_DIR / "pollen_2026-01-01.json"
check("pollen file exists",          fp.exists())
data_p = json.loads(fp.read_text(encoding="utf-8"))
check("pollen file: aggregation set", data_p.get("aggregation") == "daily_max")
check("pollen file: birch value",     data_p["fields"]["birch_pollen"] == 0.0)

check("already_written weather True",
      context_writer.already_written(_fake_weather_plugin, "2026-01-01"))
check("already_written weather False",
      not context_writer.already_written(_fake_weather_plugin, "2026-03-01"))
check("already_written pollen True",
      context_writer.already_written(_fake_pollen_plugin, "2026-01-01"))

# leeres dict — kein Absturz, written=0
result_empty = context_writer.write(_fake_weather_plugin, {}, 52.11, 8.67)
check("write empty dict: written=0",  result_empty["written"] == 0)
check("write empty dict: failed=0",   result_empty["failed"]  == 0)


# ══════════════════════════════════════════════════════════════════════════════
#  5. context_api — parse helpers (no network)
# ══════════════════════════════════════════════════════════════════════════════
section("5. context_api — parse helpers")

_daily_response = {
    "daily": {
        "time": ["2026-02-01", "2026-02-02"],
        "temperature_2m_max": [8.1, 9.3],
        "temperature_2m_min": [1.2, 2.4],
        "precipitation_sum":  [0.0, 1.5],
        "wind_speed_10m_max": [10.0, 14.2],
        "uv_index_max":       [1.0, 1.5],
        "sunshine_duration":  [7200.0, 3600.0],
    }
}
parsed_daily = context_api._parse_daily(
    _daily_response, weather_plugin.API_FIELDS
)
check("parse_daily: 2 dates",        len(parsed_daily) == 2)
check("parse_daily: temp_max day1",  parsed_daily["2026-02-01"]["temperature_2m_max"] == 8.1)
check("parse_daily: temp_max day2",  parsed_daily["2026-02-02"]["temperature_2m_max"] == 9.3)
check("parse_daily: all fields",     set(parsed_daily["2026-02-01"].keys()) == set(weather_plugin.API_FIELDS))

_hourly_response = {
    "hourly": {
        "time": [
            "2026-02-01T00:00", "2026-02-01T06:00",
            "2026-02-01T12:00", "2026-02-01T18:00",
            "2026-02-02T00:00", "2026-02-02T12:00",
        ],
        "birch_pollen":   [0.0, 2.5, 8.3, 4.1, 1.0, 3.2],
        "grass_pollen":   [0.0, 0.0, 0.5, 0.2, 0.0, 0.1],
        "alder_pollen":   [1.0, 1.5, 2.0, 1.8, 0.5, 0.8],
        "mugwort_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "olive_pollen":   [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "ragweed_pollen": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    }
}
parsed_hourly = context_api._parse_hourly_to_daily_max(
    _hourly_response, pollen_plugin.API_FIELDS
)
check("parse_hourly: 2 dates",             len(parsed_hourly) == 2)
check("parse_hourly: birch day1 = max",    parsed_hourly["2026-02-01"]["birch_pollen"] == 8.3)
check("parse_hourly: birch day2 = max",    parsed_hourly["2026-02-02"]["birch_pollen"] == 3.2)
check("parse_hourly: mugwort day1 = None or 0",
      parsed_hourly["2026-02-01"]["mugwort_pollen"] in (0.0, None))

# null-Werte in hourly-Arrays — Open-Meteo liefert null für fehlende Einträge
_hourly_with_nulls = {
    "hourly": {
        "time":         ["2026-02-03T00:00", "2026-02-03T12:00"],
        "birch_pollen": [None, 3.5],
        "grass_pollen": [None, None],
        "alder_pollen": [1.0, None],
        "mugwort_pollen": [None, None],
        "olive_pollen":   [None, None],
        "ragweed_pollen": [None, None],
    }
}
parsed_nulls = context_api._parse_hourly_to_daily_max(
    _hourly_with_nulls, pollen_plugin.API_FIELDS
)
check("parse_hourly nulls: returns dict",       isinstance(parsed_nulls, dict))
check("parse_hourly nulls: birch = 3.5",        parsed_nulls["2026-02-03"]["birch_pollen"] == 3.5)
check("parse_hourly nulls: grass all-null ok",
      parsed_nulls["2026-02-03"]["grass_pollen"] in (0.0, None))


# ══════════════════════════════════════════════════════════════════════════════
#  6. context_api — fetch (mocked network)
# ══════════════════════════════════════════════════════════════════════════════
section("6. context_api — fetch (mocked)")

_mock_response_bytes = json.dumps(_daily_response).encode("utf-8")

class _MockResp:
    def read(self): return _mock_response_bytes
    def __enter__(self): return self
    def __exit__(self, *a): pass

with patch("urllib.request.urlopen", return_value=_MockResp()):
    fetched = context_api.fetch(
        weather_plugin, "2026-02-01", "2026-02-02",
        52.11, 8.67
    )

check("fetch returns dict",           isinstance(fetched, dict))
check("fetch: 2 dates returned",      len(fetched) == 2)
check("fetch: day1 has fields",       isinstance(fetched.get("2026-02-01"), dict))

# fetch with skip_dates
with patch("urllib.request.urlopen", return_value=_MockResp()):
    fetched_skip = context_api.fetch(
        weather_plugin, "2026-02-01", "2026-02-02",
        52.11, 8.67, skip_dates={"2026-02-01"}
    )
check("fetch with skip: day1 absent", "2026-02-01" not in fetched_skip)

# Netzwerkfehler — fetch() darf nicht abstürzen, gibt leeres dict zurück
with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
    fetched_err = context_api.fetch(
        weather_plugin, "2026-02-01", "2026-02-02",
        52.11, 8.67
    )
check("fetch network error: returns dict",  isinstance(fetched_err, dict))
check("fetch network error: empty dict",    len(fetched_err) == 0)


# ══════════════════════════════════════════════════════════════════════════════
#  7. maps/weather_map — field resolution
# ══════════════════════════════════════════════════════════════════════════════
section("7. maps/weather_map")

check("list_fields not empty",        len(weather_map.list_fields()) > 0)
check("temperature_max registered",   "temperature_max" in weather_map.list_fields())
check("precipitation registered",     "precipitation"   in weather_map.list_fields())

# Write a test file for weather_map to read
_wmap_dir = cfg.CONTEXT_WEATHER_DIR
_wmap_dir.mkdir(parents=True, exist_ok=True)
_wmap_file = _wmap_dir / "weather_2026-03-01.json"
_wmap_file.write_text(json.dumps({
    "date": "2026-03-01",
    "fields": {
        "temperature_2m_max": 12.5,
        "temperature_2m_min": 3.1,
        "precipitation_sum":  0.0,
        "wind_speed_10m_max": 9.0,
        "uv_index_max":       2.1,
        "sunshine_duration":  14400.0,
    }
}), encoding="utf-8")

result_wmap = weather_map.get("temperature_max", "2026-03-01", "2026-03-01")
check("weather_map get: returns dict",         isinstance(result_wmap, dict))
check("weather_map get: values list",          isinstance(result_wmap["values"], list))
check("weather_map get: fallback=False",       result_wmap["fallback"] == False)
check("weather_map get: source_resolution",    result_wmap["source_resolution"] == "daily")
check("weather_map get: value correct",        result_wmap["values"][0]["value"] == 12.5)

result_wmap_missing = weather_map.get("temperature_max", "2026-03-02", "2026-03-02")
check("weather_map missing: value=None",       result_wmap_missing["values"][0]["value"] is None)

result_wmap_intraday = weather_map.get("temperature_max", "2026-03-01", "2026-03-01",
                                        resolution="intraday")
check("weather_map intraday: fallback=True",   result_wmap_intraday["fallback"] == True)
check("weather_map intraday: still daily",     result_wmap_intraday["source_resolution"] == "daily")

try:
    weather_map.get("unknown_field", "2026-03-01", "2026-03-01")
    check("weather_map unknown field: raises KeyError", False)
except KeyError:
    check("weather_map unknown field: raises KeyError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  8. maps/pollen_map — field resolution
# ══════════════════════════════════════════════════════════════════════════════
section("8. maps/pollen_map")

check("list_fields not empty",        len(pollen_map.list_fields()) > 0)
check("pollen_birch registered",      "pollen_birch"   in pollen_map.list_fields())
check("pollen_grass registered",      "pollen_grass"   in pollen_map.list_fields())

_pmap_dir = cfg.CONTEXT_POLLEN_DIR
_pmap_dir.mkdir(parents=True, exist_ok=True)
_pmap_file = _pmap_dir / "pollen_2026-03-01.json"
_pmap_file.write_text(json.dumps({
    "date": "2026-03-01",
    "aggregation": "daily_max",
    "fields": {
        "birch_pollen":   45.2,
        "grass_pollen":   0.0,
        "alder_pollen":   12.1,
        "mugwort_pollen": 0.0,
        "olive_pollen":   0.0,
        "ragweed_pollen": 0.0,
    }
}), encoding="utf-8")

result_pmap = pollen_map.get("pollen_birch", "2026-03-01", "2026-03-01")
check("pollen_map get: returns dict",       isinstance(result_pmap, dict))
check("pollen_map get: value correct",      result_pmap["values"][0]["value"] == 45.2)
check("pollen_map get: fallback=False",     result_pmap["fallback"] == False)
check("pollen_map get: source_resolution",  result_pmap["source_resolution"] == "daily")

result_pmap_missing = pollen_map.get("pollen_birch", "2026-03-02", "2026-03-02")
check("pollen_map missing: value=None",     result_pmap_missing["values"][0]["value"] is None)

try:
    pollen_map.get("unknown_field", "2026-03-01", "2026-03-01")
    check("pollen_map unknown field: raises KeyError", False)
except KeyError:
    check("pollen_map unknown field: raises KeyError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  9. maps/context_map — broker
# ══════════════════════════════════════════════════════════════════════════════
#  9. maps/context_map — broker

section("9. maps/context_map")

check("list_sources",                 set(context_map.list_sources()) == {"weather", "pollen"})
check("list_fields weather",          "temperature_max" in context_map.list_fields("weather"))
check("list_fields pollen",           "pollen_birch"    in context_map.list_fields("pollen"))
check("list_fields unknown = []",     context_map.list_fields("strava") == [])

result_api = context_map.get("temperature_max", "2026-03-01", "2026-03-01")
check("context_map get: weather in result",     "weather" in result_api)
check("context_map get: pollen not in result",  "pollen"  not in result_api)
check("context_map get: value correct",
      result_api["weather"]["values"][0]["value"] == 12.5)

result_api_pollen = context_map.get("pollen_birch", "2026-03-01", "2026-03-01")
check("context_map pollen: pollen in result",   "pollen"  in result_api_pollen)
check("context_map pollen: weather not in result", "weather" not in result_api_pollen)
check("context_map pollen: value correct",
      result_api_pollen["pollen"]["values"][0]["value"] == 45.2)

result_api_unknown = context_map.get("unknown_field", "2026-03-01", "2026-03-01")
check("context_map unknown: empty dict",        result_api_unknown == {})


# ══════════════════════════════════════════════════════════════════════════════
#  10. context_collector — CSV helpers
# ══════════════════════════════════════════════════════════════════════════════
section("10. context_collector — CSV helpers")

# ensure_csv creates file
context_collector._ensure_csv()
check("ensure_csv: file created",     cfg.LOCAL_CONFIG_FILE.exists())
content = cfg.LOCAL_CONFIG_FILE.read_text(encoding="utf-8")
check("ensure_csv: has comment",      content.startswith("#"))
check("ensure_csv: has header row",   "date_from" in content)

# ensure_csv idempotent
context_collector._ensure_csv()
check("ensure_csv: idempotent",       cfg.LOCAL_CONFIG_FILE.exists())

# load_csv — empty file returns []
entries = context_collector._load_csv()
check("load_csv empty: returns list", isinstance(entries, list))

# Write test CSV entries
_csv_content = (
    "# comment\n"
    "date_from;date_to;country;place;latitude;longitude\n"
    "2026-01-01;2026-06-30;Germany;Berlin;52.470933;13.365109\n"
    "2026-07-01;2026-07-14;Spain;Palma de Mallorca;39.5696;2.6502\n"
)
cfg.LOCAL_CONFIG_FILE.write_text(_csv_content, encoding="utf-8")
entries = context_collector._load_csv()
check("load_csv: 2 entries",          len(entries) == 2)
check("load_csv: lat correct",        entries[0]["lat"] == 52.470933)
check("load_csv: lon correct",        entries[0]["lon"] == 13.365109)
check("load_csv: date_from correct",  entries[0]["date_from"] == "2026-01-01")

# location map
loc_map = context_collector._build_location_map(
    "2026-01-01", "2026-07-14", entries, 0.0, 0.0
)
check("location_map: jan in berlin",  loc_map["2026-01-15"] == (52.470933, 13.365109))
check("location_map: july in palma",  loc_map["2026-07-05"] == (39.5696, 2.6502))

# segments
segments = context_collector._split_into_segments(loc_map)
check("segments: 2 segments",          len(segments) == 2)
check("segments: seg1 lat berlin",     segments[0]["lat"] == 52.470933)
check("segments: seg2 lat palma",      segments[1]["lat"] == 39.5696)


# ══════════════════════════════════════════════════════════════════════════════
#  11. context_collector — run (mocked archive + network)
# ══════════════════════════════════════════════════════════════════════════════
section("11. context_collector — run (mocked)")

_mock_stats = {
    "date_min": "2026-03-01",
    "date_max": "2026-03-02",
    "last_api": "2026-03-02",
    "last_bulk": None,
}

_mock_fetch_response = json.dumps({
    "daily": {
        "time": ["2026-03-01", "2026-03-02"],
        "temperature_2m_max": [10.0, 11.0],
        "temperature_2m_min": [2.0,  3.0],
        "precipitation_sum":  [0.0,  0.5],
        "wind_speed_10m_max": [8.0,  9.0],
        "uv_index_max":       [1.5,  1.8],
        "sunshine_duration":  [7200.0, 3600.0],
    }
}).encode("utf-8")

_mock_pollen_response = json.dumps({
    "hourly": {
        "time": ["2026-03-01T00:00", "2026-03-01T12:00",
                 "2026-03-02T00:00", "2026-03-02T12:00"],
        "birch_pollen":   [1.0, 5.0, 2.0, 3.0],
        "grass_pollen":   [0.0, 0.0, 0.0, 0.1],
        "alder_pollen":   [0.5, 1.0, 0.3, 0.8],
        "mugwort_pollen": [0.0, 0.0, 0.0, 0.0],
        "olive_pollen":   [0.0, 0.0, 0.0, 0.0],
        "ragweed_pollen": [0.0, 0.0, 0.0, 0.0],
    }
}).encode("utf-8")

class _MockRespWeather:
    def read(self): return _mock_fetch_response
    def __enter__(self): return self
    def __exit__(self, *a): pass

class _MockRespPollen:
    def read(self): return _mock_pollen_response
    def __enter__(self): return self
    def __exit__(self, *a): pass

_call_count = [0]
def _mock_urlopen(url, timeout=30):
    _call_count[0] += 1
    if "air-quality" in url:
        return _MockRespPollen()
    return _MockRespWeather()

# Reset output dirs
shutil.rmtree(cfg.CONTEXT_WEATHER_DIR, ignore_errors=True)
shutil.rmtree(cfg.CONTEXT_POLLEN_DIR,  ignore_errors=True)

with patch("garmin_quality.get_archive_stats", return_value=_mock_stats), \
     patch("urllib.request.urlopen", side_effect=_mock_urlopen):
    run_result = context_collector.run(
        settings={"context_latitude": "52.1134", "context_longitude": "8.6655"}
    )

check("run: returns dict",            isinstance(run_result, dict))
check("run: date_from correct",       run_result["date_from"] == "2026-03-01")
check("run: date_to correct",         run_result["date_to"]   == "2026-03-02")
check("run: not stopped",             run_result["stopped"]   == False)
check("run: no error",                "error" not in run_result)
check("run: weather plugin present",  "weather" in run_result["plugins"])
check("run: pollen plugin present",   "pollen"  in run_result["plugins"])
check("run: weather written=2",       run_result["plugins"]["weather"]["written"] == 2)
check("run: pollen written=2",        run_result["plugins"]["pollen"]["written"]  == 2)

# Verify files on disk
w1 = cfg.CONTEXT_WEATHER_DIR / "weather_2026-03-01.json"
w2 = cfg.CONTEXT_WEATHER_DIR / "weather_2026-03-02.json"
p1 = cfg.CONTEXT_POLLEN_DIR  / "pollen_2026-03-01.json"
p2 = cfg.CONTEXT_POLLEN_DIR  / "pollen_2026-03-02.json"
check("run: weather file 1 on disk",  w1.exists())
check("run: weather file 2 on disk",  w2.exists())
check("run: pollen file 1 on disk",   p1.exists())
check("run: pollen file 2 on disk",   p2.exists())

d_w1 = json.loads(w1.read_text(encoding="utf-8"))
check("run: weather content correct", d_w1["fields"]["temperature_2m_max"] == 10.0)

d_p1 = json.loads(p1.read_text(encoding="utf-8"))
check("run: pollen daily_max correct", d_p1["fields"]["birch_pollen"] == 5.0)

# Run again — all skipped
with patch("garmin_quality.get_archive_stats", return_value=_mock_stats), \
     patch("urllib.request.urlopen", side_effect=_mock_urlopen):
    run_result2 = context_collector.run(
        settings={"context_latitude": "52.1134", "context_longitude": "8.6655"}
    )
check("run2: weather skipped=2",      run_result2["plugins"]["weather"]["skipped"] == 2)
check("run2: pollen skipped=2",       run_result2["plugins"]["pollen"]["skipped"]  == 2)
check("run2: weather written=0",      run_result2["plugins"]["weather"]["written"] == 0)

# Run with no location configured
with patch("garmin_quality.get_archive_stats", return_value=_mock_stats):
    run_no_loc = context_collector.run(settings={})
check("run no location: error key",   "error" in run_no_loc)

# Run with empty archive
_empty_stats = {"date_min": None, "date_max": None, "last_api": None, "last_bulk": None}
with patch("garmin_quality.get_archive_stats", return_value=_empty_stats):
    run_empty = context_collector.run(
        settings={"context_latitude": "52.1134", "context_longitude": "8.6655"}
    )
check("run empty archive: error key", "error" in run_empty)

# Stop event
import threading
stop = threading.Event()
stop.set()
with patch("garmin_quality.get_archive_stats", return_value=_mock_stats), \
     patch("urllib.request.urlopen", side_effect=_mock_urlopen):
    run_stopped = context_collector.run(
        settings={"context_latitude": "52.1134", "context_longitude": "8.6655"},
        stop_event=stop
    )
check("run stopped: stopped=True",    run_stopped["stopped"] == True)

# CSV-Robustheit (D) — fehlerhafte Zeile wird übersprungen, gültige bleibt
_csv_bad = (
    "# comment\n"
    "date_from;date_to;country;place;latitude;longitude\n"
    "not-a-date;also-not;Germany;Berlin;not-a-float;13.365109\n"
    "2026-01-01;2026-06-30;Germany;Herford;52.1134;8.6655\n"
)
cfg.LOCAL_CONFIG_FILE.write_text(_csv_bad, encoding="utf-8")
entries_bad = context_collector._load_csv()
check("load_csv bad row: valid entry kept",  any(e["lat"] == 52.1134 for e in entries_bad))

# Netzwerkfehler während run() (E) — run() gibt dict zurück, kein Absturz
shutil.rmtree(cfg.CONTEXT_WEATHER_DIR, ignore_errors=True)
shutil.rmtree(cfg.CONTEXT_POLLEN_DIR,  ignore_errors=True)
with patch("garmin_quality.get_archive_stats", return_value=_mock_stats), \
     patch("urllib.request.urlopen", side_effect=OSError("network down")):
    run_net_err = context_collector.run(
        settings={"context_latitude": "52.1134", "context_longitude": "8.6655"}
    )
check("run network error: returns dict",     isinstance(run_net_err, dict))
check("run network error: not stopped",      run_net_err.get("stopped") == False)
check("run network error: weather written=0",
      run_net_err["plugins"]["weather"]["written"] == 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + Results
# ══════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_TMPDIR, ignore_errors=True)

total = _pass + _fail
print(f"\n{'═' * 55}")
print(f"  Results: {_pass}/{total} passed  |  {_fail} failed")
print(f"{'═' * 55}")

if _failures:
    print("\n  Failed:")
    for name in _failures:
        print(f"    ✗  {name}")
    sys.exit(1)
else:
    print("\n  All tests passed.")
    sys.exit(0)
