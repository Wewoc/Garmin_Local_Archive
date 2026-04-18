# Garmin Local Archive — Global Reference

Shared environment variables, constants, file paths, and project structure.
Consult this alongside `REFERENCE_GARMIN.md` and `REFERENCE_CONTEXT.md`.

---

## Environment variables

All configuration is passed between the GUI and scripts via `os.environ`. The GUI sets them in `_build_env()` (Target 1+2) or `_apply_env()` (Target 3). Scripts read them exclusively via `garmin_config.py` — no script reads `os.environ` directly.

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `GARMIN_OUTPUT_DIR` | str | `~/local_archive` | Root data folder — `garmin_data/`, `context_data/`, `local_config.csv` live here |
| `GARMIN_EMAIL` | str | `"your@email.com"` | Garmin Connect login email |
| `GARMIN_PASSWORD` | str | `"yourpassword"` | Garmin Connect password — never written to disk |
| `GARMIN_SYNC_MODE` | str | `"recent"` | Sync mode: `"recent"`, `"range"`, or `"auto"` |
| `GARMIN_DAYS_BACK` | int | `90` | Days to check in `"recent"` mode |
| `GARMIN_SYNC_START` | str | `"2024-01-01"` | Start date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_END` | str | `"2024-12-31"` | End date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_FALLBACK` | str/None | `None` | Manual start date fallback for `"auto"` mode |
| `GARMIN_REQUEST_DELAY_MIN` | float | `5.0` | Minimum seconds between Garmin API calls |
| `GARMIN_REQUEST_DELAY_MAX` | float | `20.0` | Maximum seconds between Garmin API calls |
| `GARMIN_REFRESH_FAILED` | str | `"0"` | `"1"` = re-fetch days with `recheck=true` |
| `GARMIN_LOW_QUALITY_MAX_ATTEMPTS` | int | `3` | Max re-download attempts for `low` quality days |
| `GARMIN_SESSION_LOG_PREFIX` | str | `"garmin"` | Prefix for session log filenames |
| `GARMIN_SYNC_DATES` | str | `""` | Comma-separated specific dates to fetch — overrides `GARMIN_SYNC_MODE` |
| `GARMIN_LOG_LEVEL` | str | `"INFO"` | GUI log display level: `"INFO"` or `"DEBUG"` |
| `GARMIN_MAX_DAYS_PER_SESSION` | int | `30` | Max days fetched per sync run. `0` = unlimited |
| `GARMIN_SYNC_CHUNK_SIZE` | int | `10` | Days per chunk before quality log is flushed. `0` = no chunking |
| `GARMIN_DATE_FROM` | str | 30 days back | Start date for dashboard build (`YYYY-MM-DD`) — fallback if GUI field empty |
| `GARMIN_DATE_TO` | str | today | End date for dashboard build (`YYYY-MM-DD`) — fallback if GUI field empty |
| `GARMIN_PROFILE_AGE` | str | `"35"` | User age for reference range calculation |
| `GARMIN_PROFILE_SEX` | str | `"male"` | User sex: `"male"` / `"female"` |
| `GARMIN_CONTEXT_LAT` | float | `0.0` | Default latitude for context API collect — set via GUI |
| `GARMIN_CONTEXT_LON` | float | `0.0` | Default longitude for context API collect — set via GUI |
| `PYTHONUTF8` | str | `"1"` | Forces UTF-8 mode — prevents encoding issues on Windows |
| `GARMIN_IMPORT_PATH` | str | `""` | Path to Garmin export ZIP or folder — triggers bulk import mode |

---

## Code constants (`garmin_config.py`)

All modules import via `import garmin_config as cfg`.

### Paths

| Constant | Value | Purpose |
|---|---|---|
| `BASE_DIR` | `~/local_archive` | Root data folder — ENV: `GARMIN_OUTPUT_DIR` |
| `GARMIN_DIR` | `BASE_DIR/garmin_data` | Garmin-specific data root |
| `RAW_DIR` | `GARMIN_DIR/raw` | Raw daily JSON files |
| `SUMMARY_DIR` | `GARMIN_DIR/summary` | Compact daily summary files |
| `LOG_DIR` | `GARMIN_DIR/log` | Session logs, quality log, token |
| `LOG_RECENT_DIR` | `LOG_DIR/recent` | Rolling session logs (max 30) |
| `LOG_FAIL_DIR` | `LOG_DIR/fail` | Error session logs (kept permanently) |
| `QUALITY_LOG_FILE` | `LOG_DIR/quality_log.json` | Quality register |
| `DATAFORMAT_FILE` | `garmin/garmin_dataformat.json` | Schema for garmin_validator |
| `GARMIN_TOKEN_DIR` | `LOG_DIR/garmin_token` | Temp dir for garminconnect library |
| `GARMIN_TOKEN_FILE` | `LOG_DIR/garmin_token.enc` | AES-256-GCM encrypted OAuth token |
| `CONTEXT_DIR` | `BASE_DIR/context_data` | External API data root |
| `CONTEXT_WEATHER_DIR` | `CONTEXT_DIR/weather/raw` | Archived weather files |
| `CONTEXT_POLLEN_DIR` | `CONTEXT_DIR/pollen/raw` | Archived pollen files |
| `LOCAL_CONFIG_FILE` | `BASE_DIR/local_config.csv` | User location config for context collect |

### File name prefixes

| Constant | Value | Used by |
|---|---|---|
| `SUMMARY_FILE_PREFIX` | `"garmin_"` | `garmin_map.py` |
| `RAW_FILE_PREFIX` | `"garmin_raw_"` | `garmin_map.py` |

### Location (context collect)

| Constant | Default | ENV override | Purpose |
|---|---|---|---|
| `CONTEXT_LATITUDE` | `0.0` | `GARMIN_CONTEXT_LAT` | Default latitude — set via GUI geocoding |
| `CONTEXT_LONGITUDE` | `0.0` | `GARMIN_CONTEXT_LON` | Default longitude — set via GUI geocoding |

### App constants (`garmin_app.py` / `garmin_app_standalone.py`)

| Constant | Value | Purpose |
|---|---|---|
| `KEYRING_SERVICE` | `"GarminLocalArchive"` | Windows Credential Manager service name |
| `KEYRING_USER` | `"garmin_password"` | WCM username key for password |
| `KEYRING_ENC_USER` | `"token_enc_key"` | WCM key for token encryption key |
| `SETTINGS_FILE` | `~/.garmin_archive_settings.json` | GUI settings persistence |

---

## Project structure

```
/                               ← repo root
├── garmin_app.py               ← Entry Point Target 1+2
├── garmin_app_standalone.py    ← Entry Point Target 3
├── build.py
├── build_standalone.py
├── build_all.py
├── build_manifest.py
├── requirements.txt
│
├── garmin/                     ← Garmin pipeline (source-specific)
│   ├── __init__.py
│   ├── garmin_api.py
│   ├── garmin_collector.py
│   ├── garmin_config.py
│   ├── garmin_dataformat.json
│   ├── garmin_import.py
│   ├── garmin_normalizer.py
│   ├── garmin_quality.py
│   ├── garmin_security.py
│   ├── garmin_sync.py
│   ├── garmin_utils.py
│   ├── garmin_validator.py
│   └── garmin_writer.py
│
├── context/                    ← External API collect pipeline (v1.4+)
│   ├── __init__.py
│   ├── context_collector.py
│   ├── context_api.py
│   ├── context_writer.py
│   ├── weather_plugin.py
│   └── pollen_plugin.py
│
├── maps/                       ← Data brokers — routing only, no collect
│   ├── __init__.py
│   ├── field_map.py
│   ├── garmin_map.py
│   ├── context_map.py
│   ├── weather_map.py
│   └── pollen_map.py
│
├── dashboards/                 ← Dashboard specialists (Auto-Discovery)
│   ├── __init__.py
│   ├── dash_runner.py
│   ├── timeseries_garmin_html-xls_dash.py
│   ├── health_garmin_html-json_dash.py
│   ├── overview_garmin_xls_dash.py
│   ├── health_garmin-weather-pollen_html-xls_dash.py
│   └── sleep_recovery_context_dash.py
│
├── layouts/                    ← Format renderers + passive resources
│   ├── __init__.py
│   ├── dash_layout.py
│   ├── dash_layout_html.py
│   ├── dash_plotter_html.py
│   ├── dash_plotter_html_complex.py
│   ├── dash_plotter_excel.py
│   ├── dash_plotter_json.py
│   └── dash_prompt_templates.py
│
├── export/                     ← Legacy scripts — kept for 
│   └── regenerate_summaries.py
│
├── docs/                       ← Documentation
│   ├── REFERENCE_GLOBAL.md     ← this file
│   ├── REFERENCE_GARMIN.md
│   ├── REFERENCE_CONTEXT.md
│   ├── MAINTENANCE_GLOBAL.md
│   ├── MAINTENANCE_GARMIN.md
│   ├── MAINTENANCE_CONTEXT.md
│   ├── CHANGELOG.md
│   ├── ROADMAP.md
│   ├── CONCEPT_V1-4.md
│   └── CONCEPT_V2-0.md
│
└── tests/
    ├── test_local.py           ← Garmin pipeline (218 checks)
    ├── test_local_context.py   ← Context pipeline (134 checks)
    ├── test_dashboard.py       ← Dashboard pipeline (211 checks)
    ├── test_app_logic.py       ← App layer (80 checks)
    └── test_build_output.py    ← Build output validation (8 sections)
```

---

## Data folder structure (runtime)

```
BASE_DIR/                       ← user-configured, default: ~/local_archive
├── local_config.csv            ← user location config for context collect
├── dashboards/                 ← Dashboard output (HTML, Excel, JSON, Markdown)
│
├── garmin_data/                ← Garmin pipeline data
│   ├── raw/
│   │   └── garmin_raw_YYYY-MM-DD.json
│   ├── summary/
│   │   └── garmin_YYYY-MM-DD.json
│   └── log/
│       ├── quality_log.json
│       ├── garmin_token.enc
│       ├── recent/
│       └── fail/
│
└── context_data/               ← External API data (v1.4+)
    ├── weather/
    │   └── raw/
    │       └── weather_YYYY-MM-DD.json
    └── pollen/
        └── raw/
            └── pollen_YYYY-MM-DD.json
```

---

## Build targets

| Target | Entry point | Command | Note |
|---|---|---|---|
| 1 — Dev | `garmin_app.py` | `python garmin_app.py` | No build needed |
| 2 — Standard EXE | `garmin_app.py` | `python build.py` | Python required on target |
| 3 — Standalone EXE | `garmin_app_standalone.py` | `python build_standalone.py` | No Python required |

`build_all.py` runs `test_local.py`, `test_local_context.py`, and `test_dashboard.py` before the build. After both targets complete, `test_build_output.py` runs as a post-build gate.
`build_manifest.py` is the single source of truth for all script lists.
