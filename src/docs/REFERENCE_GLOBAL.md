# Garmin Local Archive — Global Reference

Shared environment variables, constants, file paths, and project structure.
Consult this alongside `REFERENCE_GARMIN.md` and `REFERENCE_CONTEXT.md`.

---

## Environment variables

All configuration is passed between the GUI and scripts via `os.environ`. The GUI builds them via `build_env_dict()` in `app/garmin_app_controller.py` (delegated from `GarminAppBase._build_env_dict()`) — Target 1+2 passes the result to `Popen`, Target 3 writes it to `os.environ` before module import. Scripts read them exclusively via `garmin_config.py` — no script reads `os.environ` directly.

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
| `GARMIN_SESSION_LOG_PREFIX` | str | `"garmin"` | Prefix for session log filenames |
| `GARMIN_SYNC_DATES` | str | `""` | Comma-separated specific dates to fetch — overrides `GARMIN_SYNC_MODE` |
| `GARMIN_LOG_LEVEL` | str | `"INFO"` | GUI log display level: `"INFO"` or `"DEBUG"` |
| `GARMIN_MAX_DAYS_PER_SESSION` | int | `30` | Max days fetched per sync run. `0` = unlimited |
| `GARMIN_SYNC_CHUNK_SIZE` | int | `10` | Days per chunk before quality log is flushed. `0` = no chunking |
| `GARMIN_INTRADAY_RETRY_WINDOW_DAYS` | int | `180` | Days within which a `standard` day with `prev_high=True` is eligible for recheck |
| `GARMIN_DATE_FROM` | str | 30 days back | Start date for dashboard build (`YYYY-MM-DD`) — fallback if GUI field empty |
| `GARMIN_DATE_TO` | str | today | End date for dashboard build (`YYYY-MM-DD`) — fallback if GUI field empty |
| `GARMIN_PROFILE_AGE` | str | `"35"` | User age for reference range calculation |
| `GARMIN_PROFILE_SEX` | str | `"male"` | User sex: `"male"` / `"female"` |
| `GARMIN_CONTEXT_LAT` | float | `0.0` | Default latitude for context API collect — set via GUI |
| `GARMIN_CONTEXT_LON` | float | `0.0` | Default longitude for context API collect — set via GUI |
| `PYTHONUTF8` | str | `"1"` | Forces UTF-8 mode — prevents encoding issues on Windows |
| `GARMIN_IMPORT_PATH` | str | `""` | Path to Garmin export ZIP or folder — triggers bulk import mode |
| `GARMIN_SOURCE_BACKFILL` | str | `"0"` | `"1"` = run source backfill in `main()` step 5c — set by timer `source_backfill` mode only |
| `GARMIN_SCHEMA_MIGRATE` | str | `"0"` | `"1"` = rewrite outdated summary files in `main()` step 3c |

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
| `DEVICE_TABLE_FILE` | `LOG_DIR/device_table.json` | Device table — written by `garmin_quality` after each sync |
| `DATAFORMAT_FILE` | `garmin/garmin_dataformat.json` | Schema for garmin_validator |
| `REQUIRED_DATA_FILES` *(build_manifest.py)* | `[("garmin", "garmin_dataformat.json"), ("layouts", "plotly.min.js")]` | List of `(subdir, filename)` tuples — data files bundled alongside scripts for T2/T3, resolved relative to the given subdir (not hardcoded to `garmin/`, v1.6.0.4.4+) |
| `PLOTLY_VERSION` / `PLOTLY_SHA256` *(dash_layout_html.py)* | `"2.27.0"` / pinned SHA-256 | Fixed Plotly.js version — update both together when upgrading. Verified by `build_all.py.ensure_plotly_bundle()` before every build; upstream releases monitored via `check_deps.py` (`plotly/plotly.js`) (v1.6.0.4.4+) |
| `OLLAMA_MODEL` / `OLLAMA_URL` *(check_cve_whitelist.py)* | `"phi4:14b"` / `"http://localhost:11434/api/generate"` | Ollama model + endpoint for `unsure`-classification of CVE whitelist findings — only called when a package is in the whitelist but no direct function-name match exists (v1.6.0.4.4+) |
| `SOURCE_DIR` | `GARMIN_DIR/source` | Source archive — unmodified API responses (sole owner: `garmin_source_writer.py`) |
| `SOURCE_API_LOG` | `LOG_DIR/source_api_log.json` | Per-day fetch metadata: validator status, endpoints, byte size |
| `SOURCE_BACKUP_DIR` | `BACKUP_DIR/source` | Source backup — sole owner: `garmin_backup_source.py` (v1.6.0.4) |
| `GARMIN_TOKEN_DIR` | `LOG_DIR/garmin_token` | Temp dir for garminconnect library |
| `GARMIN_TOKEN_DIR` | `LOG_DIR/garmin_token` | Temp dir for garminconnect library |
| `GARMIN_TOKEN_FILE` | `LOG_DIR/garmin_token.enc` | AES-256-GCM encrypted OAuth token |
| `CRASH_LOG_DIR` *(documented exception)* | `%LOCALAPPDATA%\GarminLocalArchive\crash\` → `%TEMP%` → cwd fallback chain | Global crash logs — sole owner: `crash_handler.py` (v1.6.0.4.3). **Deliberately not under `BASE_DIR`**: the crash may itself be caused by `BASE_DIR` being unwritable or unreachable, so the crash logger cannot depend on it. Rotation: `CRASH_LOG_MAX = 30`, analogous to `LOG_RECENT_MAX`/`LOG_DAILY_MAX`. |
| `CONTEXT_DIR` | `BASE_DIR/context_data` | External API data root |
| `CONTEXT_WEATHER_DIR` | `CONTEXT_DIR/weather/raw` | Archived weather files |
| `CONTEXT_POLLEN_DIR` | `CONTEXT_DIR/pollen/raw` | Archived pollen files |
| `CONTEXT_BRIGHTSKY_DIR` | `CONTEXT_DIR/brightsky/raw` | Archived Brightsky DWD files |
| `CONTEXT_AIRQUALITY_DIR` | `CONTEXT_DIR/airquality/raw` | Archived air quality files |
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

### App constants (`app/garmin_app_settings.py`)

| Constant | Value | Purpose |
|---|---|---|
| `KEYRING_SERVICE` | `"GarminLocalArchive"` | Windows Credential Manager service name |
| `KEYRING_USER` | `"garmin_password"` | WCM username key for password |
| `SETTINGS_FILE` | `~/.garmin_archive_settings.json` | GUI settings persistence |

Note: `KEYRING_ENC_USER` (`"token_enc_key"`) does not exist in the codebase — removed in Trockenlauf (Neu-3).

---

## Project structure

```
/                               ← repo root
├── README.md
├── SECURITY.md
├─── requirements.txt
│
└── src/                        ← all source files (v1.6.0.1+)
    ├── garmin_app.py               ← Entry Point Target 1+2 (GUI)
    ├── garmin_app_standalone.py    ← Entry Point Target 3 (GUI, Standalone)
    ├── garmin_app_base.py          ← View layer (GarminApp) — PyQt6 QMainWindow, fixed top (panel_home) + QTabWidget: Home / Files / Settings (v1.6.0+). Settings tab: two-column layout — Settings left (340px), Actions right (flex). `_sheet_arrow` label mirrors `_sheet_combo` visibility (v1.6.0.7).
    ├── version.py                  ← Single source of truth for APP_VERSION
    ├── crash_handler.py            ← Leaf-Node. Global crash capture (sys.excepthook,
    │                                  threading.excepthook, qInstallMessageHandler).
    │                                  Installed at the top of both GUI entry points'
    │                                  __main__, before QApplication (v1.6.0.4.3)
    ├── qwebengine_hardening.py     ← Leaf-Node. harden(view) — disables
    │                                  LocalContentCanAccessFileUrls,
    │                                  LocalContentCanAccessRemoteUrls,
    │                                  JavascriptCanOpenWindows, PluginsEnabled,
    │                                  JavascriptCanAccessClipboard on a
    │                                  QWebEngineView. JavascriptEnabled stays
    │                                  True (Plotly requires JS). Called from
    │                                  panel_home.py and garmin_app_base.py
    │                                  after each QWebEngineView() instantiation
    │                                  (v1.6.0.4.4, A5)
    │
    ├── layouts/                    ← Format renderers + passive resources
    │   ├── __init__.py
    │   ├── dash_layout.py
    │   ├── dash_layout_html.py
    │   ├── dash_plotter_html.py
    │   ├── dash_plotter_html_complex.py
    │   ├── dash_plotter_html_mobile.py
    │   ├── dash_plotter_excel.py
    │   ├── dash_plotter_json.py
    │   ├── dash_prompt_templates.py
    │   ├── reference_ranges.py
    │   └── garmin_mobile_landing.py  ← Mobile landing page generator (v1.5.8.1+)
    │   ├── garmin_app_controller.py ← Layer 3: application logic, ENV, timer, checks (no GUI)
    │   ├── panel_home.py           ← PanelHome(QWidget) — fixed top area: connection indicators, archive status, device table, Daily Actions (Daily Sync / Mirror / Timer); Home tab: Dashboard viewer (v1.6.0+)
    │   ├── panel_settings.py       ← PanelSettings(QWidget) — credentials, paths, sync config (v1.5.4+)
    │   ├── panel_connection.py     ← PanelConnection(QWidget) — connection dialogs, token reset; indicators delegated to panel_home (v1.5.4+)
    │   ├── panel_archive.py        ← PanelArchive(QWidget) — integrity, mirror, clean, schema migration (v1.5.4+)
    │   ├── panel_timer.py          ← PanelTimer(QWidget) — background timer, loop, controller delegates (v1.5.4+)
    │   └── panel_outputs.py        ← PanelOutputs(QWidget) — sync, import, context, dashboard build, output helpers (v1.5.4+)
    │
    ├── run_tests.ps1               ← PowerShell test runner (UTF-8-safe, called by bat/run_test_all.bat)
    ├── ruff.toml
    │
    ├── bat/                        ← Dev launcher scripts (Doppelklick, cd .. vor Ausführung)
    │   ├── run_T1.bat              ← check_deps → garmin_app.py
    │   ├── run_build_all.bat       ← Qt-Tests → build_all.py
    │   ├── run_build_all_-_check_deps.bat ← Qt-Tests → check_deps → build_all.py
    │   ├── run_cve_check.bat       ← Standalone CVE whitelist check (v1.6.0.4.4+)
    │   └── run_test_all.bat        ← run_tests.ps1 aufrufen
    │
    ├── compiler/                   ← Build scripts
    │   ├── build.py
    │   ├── build_all.py
    │   ├── build_manifest.py       ← Single source of truth for all script lists
    │   └── build_standalone.py
    │
    ├── scheduler/                  ← Daily Sync entry points
    │   ├── daily_update.py         ← Entry Point Daily Sync (headless, all targets)
    │   ├── daily_update.bat        ← T1 wrapper (calls python daily_update.py)
    │   ├── Starte_Daily_Sync.bat   ← T2 user entry point (in ZIP root — cd into scheduler/ first)
    │   └── daily_update_task.xml   ← Task Scheduler template
    │
    ├── garmin/                     ← Garmin pipeline (source-specific)
    │   ├── __init__.py
    │   ├── garmin_api.py
    │   ├── garmin_collector.py
    │   ├── garmin_config.py
    │   ├── garmin_dataformat.json
    │   ├── garmin_import.py
    │   ├── garmin_normalizer.py
    │   ├── garmin_quality.py       ← Facade — delegates to quality/
    │   ├── quality/                ← Quality sub-modules (v1.5.5.1+)
    │   │   ├── __init__.py
    │   │   ├── _io.py
    │   │   ├── _assess.py
    │   │   ├── _scan.py
    │   │   ├── _maint.py
    │   │   └── _stats.py
    │   ├── garmin_redact.py        ← Leaf-Node. Secret redaction for log output —
    │   │                              redact() + RedactFilter(logging.Filter).
    │   │                              Used by garmin_collector.py (FileHandler)
    │   │                              and garmin_app_base.py._log() (v1.6.0.4.4+)
    │   ├── garmin_security.py
    │   ├── garmin_sync.py
    │   ├── garmin_utils.py
    │   ├── garmin_validator.py
    │   ├── garmin_writer.py
    │   ├── garmin_backup_source.py ← Sole Owner backup/source/ (v1.6.0.4)
    │   ├── garmin_silo_check.py    ← Leaf-Node. Read-only silo drift detection. check_silos() → dict (v1.6.0.4.7)
    │   ├── garmin_merge.py         ← Leaf-Node. Additive field merge for backfill operations. merge_field() (v1.6.3)
    │   └── garmin_extended_anaysis.py
    │
    ├── context/                    ← External API collect pipeline (v1.4+)
    │   ├── __init__.py
    │   ├── context_collector.py
    │   ├── context_api.py
    │   ├── context_writer.py
    │   ├── weather_plugin.py
    │   ├── pollen_plugin.py
    │   ├── brightsky_plugin.py
    │   └── airquality_plugin.py
    │
    ├── maps/                       ← Data brokers — routing only, no collect
    │   ├── __init__.py
    │   ├── field_map.py
    │   ├── garmin_map.py
    │   ├── context_map.py
    │   ├── weather_map.py
    │   ├── pollen_map.py
    │   ├── brightsky_map.py
    │   └── airquality_map.py
    │
    ├── dashboards/                 ← Dashboard specialists (Auto-Discovery)
    │   ├── __init__.py
    │   ├── dash_runner.py
    │   ├── timeseries_garmin_html-xls_dash.py
    │   ├── health_garmin_html-json_dash.py
    │   ├── overview_garmin_xls_dash.py
    │   ├── health_garmin-weather-pollen_html-xls_dash.py
    │   ├── sleep_recovery_context_dash.py
    │   ├── sleep_garmin_html-xls_dash.py
    │   └── explorer_garmin-context_html_dash.py
    │
    ├── layouts/                    ← Format renderers + passive resources
    │   ├── __init__.py
    │   ├── dash_layout.py
    │   ├── dash_layout_html.py
    │   ├── dash_plotter_html.py
    │   ├── dash_plotter_html_complex.py
    │   ├── dash_plotter_html_mobile.py
    │   ├── dash_plotter_excel.py
    │   ├── dash_plotter_json.py
    │   ├── dash_prompt_templates.py
    │   ├── reference_ranges.py
    │   └── garmin_mobile_landing.py  ← Mobile landing page generator (v1.5.8.1+)
    │
    ├── export/                     
    │   ├── regenerate_summaries.py
    │   └── regenerate_raw.py       ← Source Replay — regenerates raw/ from source/ (v1.6.0.4)
    │
    ├── screenshots/                ← GUI screenshots + architecture diagrams
    │
    ├── docs/                       ← Documentation
    │   ├── REFERENCE_GLOBAL.md     ← this file
    │   ├── REFERENCE_GARMIN.md
    │   ├── REFERENCE_CONTEXT.md
    │   ├── REFERENCE_DASHBOARD.md
    │   ├── MAINTENANCE_GLOBAL.md
    │   ├── MAINTENANCE_GARMIN.md
    │   ├── MAINTENANCE_CONTEXT.md
    │   ├── MAINTENANCE_DASHBOARD.md
    │   ├── CHANGELOG.md
    │   ├── ROADMAP.md
    │   └── CONCEPT_V2-0.md
    │
    └── tests/
        ├── test_local.py           ← Garmin pipeline (468 checks)
        ├── test_local_context.py   ← Context pipeline (261 checks)
        ├── test_dashboard.py       ← Dashboard pipeline (336 checks)
        ├── test_app_logic.py       ← App layer (145 checks)
        ├── test_qt_app.py          ← PyQt6 App layer (42 checks, v1.5.4+)
        ├── test_build_output.py    ← Build output validation (8 sections)
        ├── test_static.py          ← ruff linting (2 checks, v1.6.0+)
        ├── check_deps.py           ← Ecosystem monitor
        ├── cve_whitelist.py        ← CVE whitelist data + classify_finding() (v1.6.0.4.4+)
        ├── check_cve_whitelist.py  ← pip-audit wrapper + Ollama unsure-classification (v1.6.0.4.4+)
        └── support.py              ← Shared test helpers
```

---

## Data folder structure (runtime)

```
BASE_DIR/                       ← user-configured, default: ~/local_archive
├── local_config.csv            ← user location config for context collect
├── dashboards/                 ← Dashboard output (HTML, Excel, JSON, Markdown)
├── encrypted/                  ← Encrypted Dashboard Export output (v1.6.1+) — password-protected _enc.html files
│
├── garmin_data/                ← Garmin pipeline data
│   ├── raw/
│   │   └── garmin_raw_YYYY-MM-DD.json
│   ├── summary/
│   │   └── garmin_YYYY-MM-DD.json
│   └── log/
│       ├── quality_log.json
│       ├── device_table.json
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

| Target | GUI entry point | Daily Sync entry point | Build script | Python on target |
|---|---|---|---|---|
| 1 — Dev | `garmin_app.py` | `python scheduler/daily_update.py` | — | Required |
| 2 — Standard EXE | `garmin_app.py` | `Starte_Daily_Sync.bat` (ZIP root) | `compiler/build.py` | Required |
| 3.1 — Standalone GUI | `garmin_app_standalone.py` | — | `compiler/build_standalone.py` | Not required |
| 3.2 — Standalone headless | — | `daily_update.exe` | `compiler/build_standalone.py` | Not required |

`compiler/build_all.py` runs `test_local.py`, `test_local_context.py`, and `test_dashboard.py` before the build. After both targets complete, `test_build_output.py` runs as a post-build gate.
`compiler/build_manifest.py` is the single source of truth for all script lists.
