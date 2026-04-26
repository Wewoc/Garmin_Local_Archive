# Garmin Local Archive — Context Pipeline Reference

Technical reference for the external API collect pipeline (`context/` + `maps/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.

---

## Architecture overview

```
GUI "API Sync" Button
  └── context_collector.run()
        ├── Reads date range from quality_log (first_day → newest day)
        ├── Reads location from local_config.csv + GUI fallback
        ├── Splits date range into segments per location
        └── Per segment, per plugin:
              context_api.fetch(plugin, ...)   → external API (Open-Meteo or Brightsky)
              context_writer.write(plugin, ...) → context_data/

Dashboard specialists
  └── context_map.get(field, date_from, date_to)
        ├── weather_map.get()    → context_data/weather/raw/
        ├── pollen_map.get()     → context_data/pollen/raw/
        ├── brightsky_map.get()  → context_data/brightsky/raw/
        └── airquality_map.get() → context_data/airquality/raw/
```

**Key principle:** `maps/` = routing only. `context/` = collect only. No crossover.

---

## Module responsibilities

| Module | Responsibility | Does NOT |
|---|---|---|
| `context_collector.py` | Orchestrates collect — date range, CSV, segments, plugin loop | Fetch data, write files |
| `context_api.py` | Fetches from external APIs based on plugin metadata and FETCH_ADAPTER | Write files, know about dashboards |
| `context_writer.py` | Writes context_data/ based on plugin metadata | Fetch data, know about dashboards |
| `weather_plugin.py` | Metadata only — URL, fields, prefix, output dir | Execute any logic |
| `pollen_plugin.py` | Metadata only — URL, fields, prefix, output dir, aggregation | Execute any logic |
| `brightsky_plugin.py` | Metadata only — URL, fields, prefix, output dir, FETCH_ADAPTER, AGGREGATION_MAP | Execute any logic |
| `context_map.py` | Routes dashboard requests to weather_map, pollen_map, brightsky_map, airquality_map | Fetch data, call APIs |
| `weather_map.py` | Resolves generic field names to weather archive files | Write files, call APIs |
| `pollen_map.py` | Resolves generic field names to pollen archive files | Write files, call APIs |
| `brightsky_map.py` | Resolves generic field names to Brightsky archive files | Write files, call APIs |
| `airquality_map.py` | Resolves generic field names to air quality archive files | Write files, call APIs |

---

## Plugin system

Plugins are **metadata-only** — no executable logic. Adding a new source means adding a new plugin file. `context_writer.py` never requires changes. `context_api.py` only requires changes if the new source uses a different API structure than Open-Meteo (add a `FETCH_ADAPTER` value and a corresponding parse function).

### Required plugin attributes

| Attribute | Type | Description |
|---|---|---|
| `NAME` | str | Unique source identifier (e.g. `"weather"`) |
| `DESCRIPTION` | str | Human-readable description |
| `API_URL_HISTORICAL` | str | Endpoint for historical data |
| `API_URL_FORECAST` | str | Endpoint for recent/forecast data |
| `HISTORICAL_LAG_DAYS` | int | Days before today where historical ends and forecast begins |
| `API_RESOLUTION` | str | `"daily"` or `"hourly"` |
| `API_FIELDS` | list[str] | Internal field names to request from the API |
| `OUTPUT_DIR` | Path | Write target — must be a `cfg.CONTEXT_*` path |
| `FILE_PREFIX` | str | File naming prefix (e.g. `"weather_"`) |
| `SOURCE_TAG` | str | Written into each output file as `"source"` |
| `CHUNK_DAYS` | int | Max days per API call |
| `AGGREGATION` | str | Optional — uniform aggregation method (`"daily_max"`). Omit if not applicable |
| `AGGREGATION_MAP` | dict[str, str] | Optional — field-specific aggregation (`{"temperature": "mean", "precipitation": "sum", ...}`). Used when aggregation differs per field. Triggers `_parse_hourly_to_daily()` in `context_api.py` for Open-Meteo hourly plugins. For Brightsky, requires `FETCH_ADAPTER = "brightsky"` |
| `FETCH_ADAPTER` | str | Optional — adapter key for `context_api.py`. Omit for Open-Meteo plugins (default). Set to `"brightsky"` for Brightsky DWD |

### Registered plugins

| Plugin | NAME | API | Resolution | Aggregation |
|---|---|---|---|---|
| `weather_plugin.py` | `weather` | Open-Meteo Weather + Archive API | daily | — |
| `pollen_plugin.py` | `pollen` | Open-Meteo Air Quality API | hourly → daily max | `daily_max` |
| `brightsky_plugin.py` | `brightsky` | Brightsky DWD API | hourly → daily (field-specific) | `AGGREGATION_MAP` |
| `airquality_plugin.py` | `airquality` | Open-Meteo Air Quality API | hourly → daily mean | `AGGREGATION_MAP` |

---

## `context_collector.py`

| Function | Purpose |
|---|---|
| `run(settings, stop_event)` | Main entry point — orchestrates full collect run. Returns result dict with per-plugin stats |
| `_ensure_csv()` | Creates `local_config.csv` with header comment if not present |
| `_load_csv()` | Loads location entries from CSV — skips comment lines, skips rows with missing coordinates |
| `_build_location_map(date_from, date_to, csv_entries, default_lat, default_lon)` | Builds `{date_str: (lat, lon)}` for every date — CSV priority, GUI fallback |
| `_split_into_segments(location_map)` | Splits location map into contiguous segments with identical coordinates |
| `_resolve_date_range()` | Reads `date_min` and `max(last_api, last_bulk, date_max)` from `quality_log` |

**Return structure of `run()`:**
```python
{
    "date_from": str | None,
    "date_to":   str | None,
    "segments":  int,
    "plugins": {
        "weather":    {"written": int, "skipped": int, "failed": int},
        "pollen":     {"written": int, "skipped": int, "failed": int},
        "brightsky":  {"written": int, "skipped": int, "failed": int},
        "airquality": {"written": int, "skipped": int, "failed": int},
    },
    "stopped": bool,
    "error":   str,   # optional — only present on abort
}
```

---

## `context_api.py`

| Function | Purpose |
|---|---|
| `fetch(plugin, date_from, date_to, lat, lon, skip_dates)` | Fetches data for a plugin over a date range. Returns `{date_str: {field: value}}`. Dates in `skip_dates` are excluded from result |
| `_parse_daily(response, fields)` | Parses daily Open-Meteo response to `{date: {field: value}}` |
| `_parse_hourly_to_daily_max(response, fields)` | Aggregates hourly Open-Meteo response to daily max per field — used by pollen |
| `_parse_hourly_to_daily(response, fields, aggregation_map)` | Aggregates hourly Open-Meteo response per field with method from `aggregation_map` (mean / max / sum / mode) — used by airquality |
| `_parse_brightsky(response, aggregation_map)` | Parses Brightsky `weather[]` array to `{date: {field: value}}` with field-specific aggregation (mean / sum / max / mode) |
| `_fetch_chunk(url, date_from, date_to, lat, lon, fields, resolution, adapter)` | Single API call — builds adapter-specific URL params, returns parsed JSON or None on failure |
| `_select_url(plugin, date_from)` | Selects historical or forecast URL based on `HISTORICAL_LAG_DAYS` |

**Never writes files.** Returns raw parsed data only.

---

## `context_writer.py`

| Function | Purpose |
|---|---|
| `write(plugin, data, lat, lon)` | Writes `{date: fields}` dict to `plugin.OUTPUT_DIR`. Returns `{"written": int, "failed": int}` |
| `already_written(plugin, date_str)` | Returns `True` if file for this plugin + date already exists |

**Sole write authority for `context_data/`.** No other module writes there.

---

## `context_map.py`

| Function | Purpose |
|---|---|
| `get(field, date_from, date_to, resolution)` | Routes field request to all registered sources. Returns `{source_name: result_dict}`. Unknown fields silently skipped. Errors return `"error"` key |
| `list_fields(source)` | Returns registered field names for a source. Default: `"weather"` |
| `list_sources()` | Returns all registered source names |

---

## `weather_map.py` / `pollen_map.py` / `brightsky_map.py` / `airquality_map.py`

All three follow identical interface:

| Function | Purpose |
|---|---|
| `get(field, date_from, date_to, resolution)` | Reads locally archived files. Returns `{"values": [...], "fallback": bool, "source_resolution": str}` |
| `list_fields()` | Returns all registered generic field names |

**Fallback behaviour:** All sources are always daily. If `resolution="intraday"` is requested, `fallback=True` is set but daily data is returned.

### Registered fields — `weather_map.py`

| Generic name | Internal key | Unit |
|---|---|---|
| `temperature_max` | `temperature_2m_max` | °C |
| `temperature_min` | `temperature_2m_min` | °C |
| `precipitation` | `precipitation_sum` | mm |
| `wind_speed_max` | `wind_speed_10m_max` | km/h |
| `uv_index_max` | `uv_index_max` | index |
| `sunshine_duration` | `sunshine_duration` | seconds |

### Registered fields — `pollen_map.py`

| Generic name | Internal key | Unit |
|---|---|---|
| `pollen_birch` | `birch_pollen` | grains/m³ |
| `pollen_grass` | `grass_pollen` | grains/m³ |
| `pollen_alder` | `alder_pollen` | grains/m³ |
| `pollen_mugwort` | `mugwort_pollen` | grains/m³ |
| `pollen_olive` | `olive_pollen` | grains/m³ |
| `pollen_ragweed` | `ragweed_pollen` | grains/m³ |

### Registered fields — `brightsky_map.py`

| Generic name | Internal key | Unit | Aggregation |
|---|---|---|---|
| `temperature_avg` | `temperature` | °C | daily mean |
| `humidity_avg` | `relative_humidity` | % | daily mean |
| `precipitation_sum` | `precipitation` | mm | daily sum |
| `sunshine_sum` | `sunshine` | min | daily sum |
| `wind_speed_max` | `wind_speed` | km/h | daily max |
| `wind_gust_max` | `wind_gust_speed` | km/h | daily max |
| `cloud_cover_avg` | `cloud_cover` | % | daily mean |
| `pressure_avg` | `pressure_msl` | hPa | daily mean |
| `condition` | `condition` | string | daily mode |

### Registered fields — `airquality_map.py`

| Generic name | Internal key | Unit | Aggregation |
|---|---|---|---|
| `airquality_pm2_5` | `pm2_5` | μg/m³ | daily mean |
| `airquality_pm10` | `pm10` | μg/m³ | daily mean |
| `airquality_european_aqi` | `european_aqi` | — | daily mean |
| `airquality_nitrogen_dioxide` | `nitrogen_dioxide` | μg/m³ | daily mean |
| `airquality_ozone` | `ozone` | μg/m³ | daily mean |

---

## File structures

### `context_data/weather/raw/weather_YYYY-MM-DD.json`

```json
{
    "date":        "2026-01-01",
    "source":      "open-meteo-weather",
    "fetched_at":  "2026-04-09T10:00:00",
    "latitude":    52.1134,
    "longitude":   8.6655,
    "fields": {
        "temperature_2m_max":  5.2,
        "temperature_2m_min": -1.1,
        "precipitation_sum":   0.0,
        "wind_speed_10m_max": 12.3,
        "uv_index_max":        1.2,
        "sunshine_duration":  3600.0
    }
}
```

### `context_data/pollen/raw/pollen_YYYY-MM-DD.json`

```json
{
    "date":        "2026-01-01",
    "source":      "open-meteo-pollen",
    "fetched_at":  "2026-04-09T10:00:00",
    "latitude":    52.1134,
    "longitude":   8.6655,
    "aggregation": "daily_max",
    "fields": {
        "birch_pollen":   45.2,
        "grass_pollen":    0.0,
        "alder_pollen":   12.1,
        "mugwort_pollen":  0.0,
        "olive_pollen":    0.0,
        "ragweed_pollen":  0.0
    }
}
```

### `context_data/brightsky/raw/brightsky_YYYY-MM-DD.json`

```json
{
    "date":        "2026-01-01",
    "source":      "brightsky-dwd",
    "fetched_at":  "2026-04-09T10:00:00",
    "latitude":    52.1134,
    "longitude":   8.6655,
    "fields": {
        "temperature":       4.8,
        "relative_humidity": 78.0,
        "precipitation":     1.2,
        "sunshine":          45.0,
        "wind_speed":        18.0,
        "wind_gust_speed":   32.0,
        "cloud_cover":       85.0,
        "pressure_msl":      1008.5,
        "condition":         "rain"
    }
}
```

### `context_data/airquality/raw/airquality_YYYY-MM-DD.json`

```json
{
    "date":        "2026-01-01",
    "source":      "open-meteo-airquality",
    "fetched_at":  "2026-04-09T10:00:00",
    "latitude":    52.5134,
    "longitude":   13.6655,
    "aggregation": "daily_mean",
    "fields": {
        "pm2_5":            12.4,
        "pm10":             18.7,
        "european_aqi":     32.0,
        "nitrogen_dioxide": 15.2,
        "ozone":            68.5
    }
}
```

---

## `local_config.csv`

Located at `BASE_DIR/local_config.csv`. User-managed, auto-created on first API Sync.

```csv
# Garmin Local Archive — Location Config
# date_from, date_to: YYYY-MM-DD
# country: country name in English (e.g. Germany, Spain, France)
# place: city or town name (e.g. Herford, Palma de Mallorca)
# latitude, longitude: filled automatically by the app after geocoding
#   Leave empty — the app fills them on next API Sync setup.
date_from,date_to,country,place,latitude,longitude
2025-01-01,2025-12-31,Germany,Herford,52.1134,8.6655
2025-07-14,2025-07-21,Spain,Palma de Mallorca,39.5696,2.6502
```

**Fallback chain per date:**
1. CSV entry covering the date → CSV coordinates
2. No CSV entry → GUI setting (`context_latitude` / `context_longitude`)
3. GUI setting = 0.0/0.0 → collect aborted with error message

---

## External APIs

| API | URL | Auth | Resolution | Historical |
|---|---|---|---|---|
| Open-Meteo Weather | `archive-api.open-meteo.com/v1/archive` | None | daily | 1940+ |
| Open-Meteo Forecast | `api.open-meteo.com/v1/forecast` | None | daily | recent weeks |
| Open-Meteo Air Quality (pollen) | `air-quality-api.open-meteo.com/v1/air-quality` | None | hourly | limited |
| Open-Meteo Air Quality (airquality) | `air-quality-api.open-meteo.com/v1/air-quality` | None | hourly | limited |
| Open-Meteo Geocoding | `geocoding-api.open-meteo.com/v1/search` | None | — | — |
| Brightsky DWD | `api.brightsky.dev/weather` | None | hourly | 2010-01-01+ |

All APIs are free for non-commercial use, no registration required.
