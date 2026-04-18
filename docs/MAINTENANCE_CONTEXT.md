# Garmin Local Archive — Context Pipeline Maintenance Guide

Maintenance, debugging, and extension guide for the external API collect pipeline (`context/` + `maps/`).
For build and release process see `MAINTENANCE_GLOBAL.md`.
For complete function reference see `REFERENCE_CONTEXT.md`.

---

## Pipeline architecture

```
GUI "API Sync" Button
  └── context_collector.run(settings, stop_event)
        ├── _ensure_csv()               → creates local_config.csv if missing
        ├── _resolve_date_range()       → reads quality_log for date range
        ├── _load_csv()                 → reads local_config.csv
        ├── _build_location_map()       → {date: (lat, lon)} with CSV + GUI fallback
        ├── _split_into_segments()      → contiguous segments per location
        └── per segment, per plugin:
              context_api.fetch()       → Open-Meteo API call
              context_writer.write()    → context_data/

Dashboard specialists
  └── context_map.get(field, date_from, date_to)
        ├── weather_map.get()           → reads context_data/weather/raw/
        └── pollen_map.get()            → reads context_data/pollen/raw/
```

### Module ownership

| Module | Sole write authority |
|---|---|
| `context_writer.py` | `context_data/` (all subfolders) |

### Invariants

- `maps/` modules never write files — routing and reading only
- `context/` modules never call dashboard code
- `context_map.py` never calls Open-Meteo directly — reads local files only
- Plugins contain NO executable logic — metadata only
- `context_writer.py` is the only module that creates files in `context_data/`
- `context_api.fetch()` never raises — `OSError` caught in `_fetch_chunk()` (returns `None`); `fetch()` returns empty dict on network failure
- `context_collector.run()` never raises — `Exception` caught around fetch+write block (`failed += 1`); always returns a result dict

---

## `test_local_context.py`

**Current count: 134 checks, 11 sections.**

```bash
python tests/test_local_context.py
```

### What is tested

1. `garmin_config` — new context paths (`CONTEXT_DIR`, `CONTEXT_WEATHER_DIR`, `CONTEXT_POLLEN_DIR`, `LOCAL_CONFIG_FILE`)
2. `weather_plugin` — all metadata attributes present and correct
3. `pollen_plugin` — all metadata attributes present, `AGGREGATION = "daily_max"`
4. `context_writer` — write, file content, already_written; empty dict input → written=0
5. `context_api` — `_parse_daily()`, `_parse_hourly_to_daily_max()`; null values in hourly arrays
6. `context_api` — `fetch()` with mocked network, `skip_dates` exclusion, network error → empty dict
7. `weather_map` — field resolution, fallback=True for intraday, KeyError for unknown
8. `pollen_map` — field resolution, fallback=True for intraday, KeyError for unknown
9. `context_map` — routing, unknown field returns `{}`, `list_sources()`, `list_fields()`
10. `context_collector` — CSV helpers: `_ensure_csv()`, `_load_csv()`, `_build_location_map()`, `_split_into_segments()`; malformed CSV row skipped
11. `context_collector` — `run()` with mocked archive + network, skip on second run, stop event, no-location error, empty archive error, network error → dict returned

### What is NOT tested

- Live Open-Meteo API calls — always mocked
- GUI integration (API Sync button)
- Geocoding flow

### When to run

After any change to: `context_collector`, `context_api`, `context_writer`, `weather_plugin`, `pollen_plugin`, `weather_map`, `pollen_map`, `context_map`, or context-related constants in `garmin_config`.

---

## Adding a new context source (plugin)

1. Create `context/new_source_plugin.py` with all required metadata attributes (see `REFERENCE_CONTEXT.md`)
2. Add to `_PLUGINS` list in `context/context_collector.py`:
   ```python
   from . import new_source_plugin
   _PLUGINS = [weather_plugin, pollen_plugin, new_source_plugin]
   ```
3. Create `maps/new_source_map.py` with `get()` and `list_fields()`
4. Register in `maps/context_map.py`:
   ```python
   from . import new_source_map
   _SOURCES = {"weather": weather_map, "pollen": pollen_map, "new_source": new_source_map}
   ```
5. Add `cfg.CONTEXT_NEW_SOURCE_DIR` to `garmin_config.py`
6. Add to `build_manifest.py` `SHARED_SCRIPTS`
7. Add tests to `tests/test_local_context.py`

No changes to `context_api.py` or `context_writer.py` — they read plugin metadata generically.

---

## Location config (`local_config.csv`)

Auto-created at `BASE_DIR/local_config.csv` on first API Sync if not present.

**Fallback chain per date:**
1. CSV entry covering the date → CSV coordinates
2. No CSV entry → GUI setting (`context_latitude` / `context_longitude`)
3. GUI setting = 0.0/0.0 → collect aborted with error message

**Editing the CSV:** Open in Excel or any text editor. No comment lines — header row directly followed by data. A `local_config_README.txt` in the same folder explains the format. Rows with missing or invalid coordinates are silently skipped. Overlapping date ranges: first matching row wins.

**Location setup:** GUI Settings → CONTEXT → paste Google Maps URL → "📍 Set Location" extracts lat/lon automatically and saves to settings. For travel entries: add rows manually in the CSV with the correct date range and coordinates.

---

## API details

### Open-Meteo Weather

- Historical: `https://archive-api.open-meteo.com/v1/archive`
- Recent: `https://api.open-meteo.com/v1/forecast` (with `past_days`)
- Switch point: `HISTORICAL_LAG_DAYS = 5` days before today
- Resolution: daily
- Chunk size: 365 days per call

### Open-Meteo Air Quality (pollen)

- Endpoint: `https://air-quality-api.open-meteo.com/v1/air-quality`
- Resolution: hourly — aggregated to daily max by `context_api._parse_hourly_to_daily_max()`
- Chunk size: 30 days per call (tighter API limits)
- Aggregation: daily max = highest hourly reading per day per field

### Rate limiting

Both APIs are free for non-commercial use with no authentication. `context_api.py` adds a 0.5s polite delay between chunk calls (`time.sleep(0.5)`). If rate limiting occurs, increase `CHUNK_DAYS` or add a longer delay.

---

## `maps/` architecture principles

`maps/` contains routing only — no data collection, no file writes, no API calls.

| What maps/ does | What maps/ does NOT do |
|---|---|
| Read locally archived files | Write any files |
| Route field requests to source-specific resolvers | Call Open-Meteo or any external API |
| Return neutral dicts to specialists | Know anything about dashboard layout |

**Architecture violation check:** If an Open-Meteo internal field name (e.g. `temperature_2m_max`) appears outside `weather_map.py` or `pollen_map.py`, that is an architecture violation. Generic names (`temperature_max`, `pollen_birch`) should appear everywhere else.

---

## Debugging

### No data returned for a date

1. Check if file exists: `context_data/weather/raw/weather_YYYY-MM-DD.json`
2. If missing: run API Sync — check for location configured (not 0.0/0.0)
3. Check `local_config.csv` for the date range — correct coordinates?
4. Check Open-Meteo API directly with the coordinates

### `context_map.get()` returns empty dict

The field is not registered in either `weather_map._FIELD_MAP` or `pollen_map._FIELD_MAP`. Add it or check the field name spelling.

### `context_collector.run()` returns `"error"` key

Two possible causes:
- `"Location not configured"` — set coordinates in GUI settings
- `"Archive empty"` — run Garmin sync first to populate `quality_log.json`

### Wrong coordinates for a date

Edit `local_config.csv` — add or update the row covering that date range. Delete the affected files in `context_data/` and re-run API Sync to refetch with correct coordinates.
