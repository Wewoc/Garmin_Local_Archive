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
| `GARMIN_CAPABILITY_SCAN` | str | `"0"` | `"1"` = delegated entry point (`main()` step 0b) — probes the 19 optional health-endpoint candidates instead of running the regular sync. Own login, `sys.exit()` on completion (v1.6.8) |
| `GARMIN_CAPABILITY_WINDOW_DAYS` | str | `"7"` | Scan window for `GARMIN_CAPABILITY_SCAN=1` — days to probe per candidate (v1.6.8) |
| `GARMIN_MCP_LLM_BACKEND` | str | *(unset)* | `"ollama"`/`"cloud"` overrides `MCP_SERVER_CONFIG_FILE`'s `mcp_llm_backend` if set — ENV always wins, falls back to the config file, then to `"ollama"` (v1.7 Teilbauauftrag c, file fallback added Teilbauauftrag f). Not validated in `garmin_config.py`. |

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
| `LOG_DAILY_DIR` | `LOG_DIR/daily` | Rolling daily-sync session logs (v1.6.9.1 — added for `metadata_map.py`, path itself pre-existing since `daily_update.py`'s own `_start_daily_log()`) |
| `QUALITY_LOG_FILE` | `LOG_DIR/quality_log.json` | Quality register |
| `DEVICE_TABLE_FILE` | `LOG_DIR/device_table.json` | Device table — written by `garmin_quality` after each sync |
| `DATAFORMAT_FILE` | `garmin/garmin_dataformat.json` | Schema for garmin_validator |
| `REQUIRED_DATA_FILES` *(build_manifest.py)* | `[("garmin", "garmin_dataformat.json"), ("layouts", "plotly.min.js")]` | List of `(subdir, filename)` tuples — data files bundled alongside scripts for T2/T3, resolved relative to the given subdir (not hardcoded to `garmin/`, v1.6.0.4.4+) |
| `PLOTLY_VERSION` / `PLOTLY_SHA256` *(dash_layout_html.py)* | `"2.27.0"` / pinned SHA-256 | Fixed Plotly.js version — update both together when upgrading. Verified by `build_all.py.ensure_plotly_bundle()` before every build; upstream releases monitored via `check_deps.py` (`plotly/plotly.js`) (v1.6.0.4.4+) |
| `OLLAMA_MODEL` / `OLLAMA_URL` *(check_cve_whitelist.py)* | `"phi4:14b"` / `"http://localhost:11434/api/generate"` | Ollama model + endpoint for `unsure`-classification of CVE whitelist findings — only called when a package is in the whitelist but no direct function-name match exists (v1.6.0.4.4+) |
| `SOURCE_DIR` | `GARMIN_DIR/source` | Source archive — unmodified API responses (sole owner: `garmin_source_writer.py`) |
| `SOURCE_API_LOG` | `LOG_DIR/source_api_log.json` | Per-day fetch metadata: validator status, endpoints, byte size |
| `SOURCE_BACKUP_DIR` | `BACKUP_DIR/source` | Source backup — sole owner: `garmin_backup_source.py` (v1.6.0.4) |
| `LIVE_DIR` | `GARMIN_DIR/live` | Live Tracking snapshot dir — sole owner: `garmin_live_fetch.py` (v1.6.5) |
| `LIVE_FILE` | `LIVE_DIR/live.json` | Single-file snapshot of the current day — no history, overwritten on every fetch (v1.6.5) |
| `GARMIN_TOKEN_DIR` | `LOG_DIR/garmin_token` | Temp dir for garminconnect library |
| `GARMIN_TOKEN_FILE` | `LOG_DIR/garmin_token.enc` | AES-256-GCM encrypted OAuth token |
| `CAPABILITY_CONFIG_FILE` | `LOG_DIR/garmin_api_capability_config.json` | API-Capability-Scan config — sole owner: `garmin_api_capability.py` (v1.6.8) |
| `CRASH_LOG_DIR` *(documented exception)* | `%LOCALAPPDATA%\GarminLocalArchive\crash\` → `%TEMP%` → cwd fallback chain | Global crash logs — sole owner: `crash_handler.py` (v1.6.0.4.3). **Deliberately not under `BASE_DIR`**: the crash may itself be caused by `BASE_DIR` being unwritable or unreachable, so the crash logger cannot depend on it. Rotation: `CRASH_LOG_MAX = 30`, analogous to `LOG_RECENT_MAX`/`LOG_DAILY_MAX`. |
| `CONTEXT_DIR` | `BASE_DIR/context_data` | External API data root |
| `CONTEXT_WEATHER_DIR` | `CONTEXT_DIR/weather/raw` | Archived weather files |
| `CONTEXT_POLLEN_DIR` | `CONTEXT_DIR/pollen/raw` | Archived pollen files |
| `CONTEXT_BRIGHTSKY_DIR` | `CONTEXT_DIR/brightsky/raw` | Archived Brightsky DWD files |
| `CONTEXT_AIRQUALITY_DIR` | `CONTEXT_DIR/airquality/raw` | Archived air quality files |
| `LOCAL_CONFIG_FILE` | `BASE_DIR/local_config.csv` | User location config for context collect |
| `MCP_LLM_CONFIG_FILE` | `~/.garmin_mcp_llm_config.json` | Plaintext cloud LLM credentials (`provider`/`api_key`/`model`) for `MCP_LLM_BACKEND="cloud"` — missing/incomplete = cloud backend unavailable, not an error (v1.7 Teilbauauftrag c) |
| `MCP_SERVER_CONFIG_FILE` | `~/.garmin_mcp_server_config.json` | Six fields (v1.7.0.2 added the last two — see `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` below): `mcp_llm_backend`, `base_dir`, `mcp_http_port`, `mcp_headless`, `mcp_extra_hosts_enabled`, `mcp_extra_hosts` — enables `clients/mcp_server.py` to run fully standalone, without a GLA installation (v1.7 Teilbauauftrag f). `mcp_http_port` replaced the earlier `mcp_ollama_model` field in v1.7.0.1 (Ollama model selection removed — see `MCP_OLLAMA_MODEL` entry below); `mcp_headless` is new, not a replacement — see `MCP_HEADLESS` entry below. A field named `mcp_enabled` existed through Teil (f) but was removed in Teil (g) — the "Enable MCP server" checkbox it backed had no functional effect once `main()` stopped gating on it (Teil f), and the Teil (g) "Start MCP Server" button made the whole on/off concept moot; not to be confused with `mcp_headless`, a different, still-live field despite the naming similarity. Old files on disk may still carry a stale `mcp_enabled` key — harmless, simply ignored. Two documented writers (deliberate Sole-Write-Authority exception — mutually exclusive operating modes, never run concurrently against the file): `app/panel_mcp.py::_mcp_save_server_config()` (mirrors GLA's live values on every MCP settings save) and `clients/mcp_server_gui.py` (direct standalone-window input, merge-on-write). |
| `MCP_BASE_DIR` | `BASE_DIR`'s value, or the `MCP_SERVER_CONFIG_FILE` `base_dir` field | Server-owned archive path (v1.7 Teilbauauftrag f) — deliberately a separate constant from `BASE_DIR`, not an alias. Same `GARMIN_OUTPUT_DIR` ENV as `BASE_DIR` (shared, not a new ENV name) takes precedence if set; otherwise falls back to the config file, then to `~/local_archive`. `BASE_DIR` itself is unchanged by this — the pipeline's archive-path resolution was not touched. **Consumed only by `clients/mcp_server.py`'s own operational-log path (`_start_operational_log()`) and `clients/mcp_server_gui.py`'s Archive-path display/`base_dir` form field — never by the broker chain (`maps/mcp_map.py` → `gateway_map.py` → `metadata_map.py`/`health_map.py`/`context_map.py`), which reads `BASE_DIR` directly instead.** In a standalone install (`mcp_server.exe`, no GLA process ahead of it), `BASE_DIR` resolved to its hardcoded default (`~/local_archive`) rather than the configured archive path, since nothing set `GARMIN_OUTPUT_DIR` before `garmin_config` was imported — `MCP_BASE_DIR` showed the correct path while every actual data read used the wrong one. Fixed in v1.7.0.3: `clients/mcp_server.py` now sets `GARMIN_OUTPUT_DIR` from `MCP_SERVER_CONFIG_FILE`'s `base_dir` field before importing `garmin_config`, so `BASE_DIR` and `MCP_BASE_DIR` resolve to the same value in the standalone case — see `clients/mcp_server.py` entry below. |
| `MCP_HTTP_PORT` | `8756` | HTTP port for the MCP server's streamable-http transport (v1.7.0.1, replaces the stdio transport + PID-lockfile liveness model entirely — see `clients/mcp_server.py`/`clients/mcp_server_gui.py` entries below). ENV (`GARMIN_MCP_HTTP_PORT`) > `MCP_SERVER_CONFIG_FILE`'s `mcp_http_port` field > default `8756`, same precedence pattern as `MCP_LLM_BACKEND`. Host is deliberately NOT configurable — always `127.0.0.1`, hardcoded at the `FastMCP()` call site, never exposed as a field or ENV var. Liveness is now a plain TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` (`app/panel_mcp.py::_mcp_server_is_running()`, `clients/mcp_server_gui.py::_is_server_reachable()`) — no PID file, no `tasklist` parsing, no stale-file interpretation needed. |
| `MCP_HEADLESS` | `False` | Headless-mode toggle (v1.7.0.1). ENV (`GARMIN_MCP_HEADLESS`, `"1"`/`"true"`/`"yes"` case-insensitive) > `MCP_SERVER_CONFIG_FILE`'s `mcp_headless` field > default `False`, same precedence pattern as `MCP_HTTP_PORT`. Default stays `False` — the window remains the default entry point (`clients/mcp_server.py`'s "the window is the server" coupling from v1.7 Teilbauauftrag f is unchanged, session decision — see `clients/mcp_server.py` entry below); this field only opts a given install OUT of the window, e.g. for a scheduled/automated deployment, analogous to `scheduler/daily_update.py`. Settable from both `app/panel_mcp.py` and `clients/mcp_server_gui.py` (the latter only takes effect on the *next* start, not the instance you're looking at when you check it). |
| `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` | `False` | Opt-in toggle (v1.7.0.2) for extra `transport_security` allowed hosts, on top of the SDK's own `127.0.0.1`/`localhost`/`::1` — needed for MCP clients reaching the server through a different hostname, e.g. Open WebUI's own Docker container via `host.docker.internal`, which the SDK's built-in DNS-rebinding protection otherwise rejects. ENV (`GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED`) > `MCP_SERVER_CONFIG_FILE`'s `mcp_extra_hosts_enabled` field > default `False`, same precedence pattern as `MCP_HTTP_PORT`/`MCP_HEADLESS`. See `clients/mcp_server.py` entry below for the actual wiring. |
| `MCP_EXTRA_ALLOWED_HOSTS_RAW` | `"host.docker.internal"` | Comma-separated raw host string backing `MCP_EXTRA_ALLOWED_HOSTS` below — a real, stored default (not just a UI placeholder, session decision), since `host.docker.internal` is the common case. ENV (`GARMIN_MCP_EXTRA_ALLOWED_HOSTS`) > `MCP_SERVER_CONFIG_FILE`'s `mcp_extra_hosts` field > default `"host.docker.internal"`. |
| `MCP_EXTRA_ALLOWED_HOSTS` | `["host.docker.internal:*"]` | `MCP_EXTRA_ALLOWED_HOSTS_RAW` parsed via `_parse_extra_hosts()` — splits on commas, strips whitespace, drops empty entries, and appends `:*` to any entry with no explicit port so any port matches (mirrors the SDK's own wildcard-port convention for its three defaults). Only actually applied to `transport_security.allowed_hosts` when `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` is true. |
| `MCP_DB_PATH` *(clients/mcp_sql.py, not garmin_config.py)* | `BASE_DIR/sqlite/mcp_cache.db` | SQLite aggregation-proxy cache (v1.7.1) — a new top-level sibling to `garmin_data/`/`context_data/`, not nested inside either. Deliberately not a `garmin_config.py` constant — owned entirely by `clients/mcp_sql.py`, which builds the path itself from `cfg.BASE_DIR`. Pure consumer, never a source: every row is reconstructible from the archive via `maps/mcp_map.py`; a lost/corrupt file forces a full rebuild on the next sync, not data loss. `garmin_backup.py`/`garmin_mirror.py` are unaware this file exists — see `clients/mcp_sql.py` entry below. |

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
    ├── frozen_paths.py             ← Leaf-Node. Central frozen-path resolution —
    │                                  scripts_root(), add_to_path(), doc_path().
    │                                  Replaces duplicated sys.frozen/_MEIPASS/
    │                                  executable branches across panel_outputs.py
    │                                  (6x), panel_home.py, the garmin_live_fetch
    │                                  call site, and doc lookups (v1.6.0.4.3)
    ├── log_utils.py                ← Leaf-Node. with_timestamp(log_fn) — prefixes
    │                                  log-callback messages with a timestamp
    │                                  matching logging.Formatter's format.
    │                                  Domain-less, alongside frozen_paths.py —
    │                                  imported by context_collector.py and
    │                                  dash_runner.py without creating a
    │                                  dependency on garmin/ (v1.6.6.1)
    │
    ├── app/                        ← Layer 1+3: settings persistence + application logic (v1.5.2+)
    │   │                              NOTE: this block is a stale duplicate of the fuller
    │   │                              app/ listing further below (this file's own
    │   │                              pre-existing inconsistency, not introduced by v1.7 —
    │   │                              flagged during Teilbauauftrag (d), not resolved here;
    │   │                              out of scope for this session's changes)
    │   ├── garmin_app_controller.py ← Layer 3: application logic, ENV, timer, checks (no GUI)
    │   ├── panel_home.py           ← PanelHome(QWidget) — fixed top area: connection indicators, archive status, device table, Daily Actions (Daily Sync / Mirror / Timer / MCP-Settings); Home tab: Dashboard viewer (v1.6.0+, MCP-Settings button added v1.7 Teilbauauftrag d)
    │   ├── panel_settings.py       ← PanelSettings(QWidget) — credentials, paths, sync config (v1.5.4+)
    │   ├── panel_connection.py     ← PanelConnection(QWidget) — connection dialogs, token reset; indicators delegated to panel_home (v1.5.4+)
    │   ├── panel_archive.py        ← PanelArchive(QWidget) — integrity, mirror, clean, schema migration (v1.5.4+)
    │   ├── panel_timer.py          ← PanelTimer(QWidget) — background timer, loop, controller delegates (v1.5.4+)
    │   ├── panel_outputs.py        ← PanelOutputs(QWidget) — sync, import, context, dashboard build, output helpers (v1.5.4+)
    │   └── panel_mcp.py            ← PanelMcp(QWidget) — MCP server settings, fifth tab "MCP Server" (v1.7 Teilbauauftrag d)
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
├── app/                        ← GUI logic layer (v1.5.2+): settings, controller, panel Mixins (v1.5.3+)
    │   ├── __init__.py
    │   ├── dialogs.py              ← PasswordConfirmDialog(QDialog) — shared password entry/confirm dialog. mode="setup": two fields + match-check (new passwords). mode="unlock": one field, no confirm (existing passwords, e.g. mirror import where unlock_meta() validates anyway). Used by panel_archive.py (Mirror Container) and panel_outputs.py (Encrypted Dashboards). PyQt6-only import, no project-module imports, no business logic
    │   ├── garmin_app_settings.py  ← Layer 1: settings persistence, keyring helpers, constants (no tkinter/Qt)
    │   ├── garmin_app_controller.py ← Layer 3: application logic, ENV, timer, checks (no GUI)
    │   ├── panel_home.py           ← PanelHome(QWidget) — fixed top area: connection indicators, archive status, device table, Daily Actions (Daily Sync / Mirror / Timer); Home tab: Dashboard viewer (v1.6.0+)
    │   ├── panel_settings.py       ← PanelSettings(QWidget) — credentials, paths, sync config (v1.5.4+)
    │   ├── panel_connection.py     ← PanelConnection(QWidget) — connection dialogs, token reset; indicators delegated to panel_home (v1.5.4+)
    │   ├── panel_archive.py        ← PanelArchive(QWidget) — integrity, mirror, clean, schema migration (v1.5.4+)
    │   ├── panel_timer.py          ← PanelTimer(QWidget) — background timer, loop, controller delegates (v1.5.4+)
    │   ├── panel_outputs.py        ← PanelOutputs(QWidget) — sync, import, context, dashboard build, output helpers (v1.5.4+)
    │   ├── panel_chat.py           ← PanelChat(QWidget) — In-App Ollama Chat, Tab 3 "Ollama-Chat" (v1.6.6)
    │   └── panel_mcp.py            ← PanelMcp(QWidget) — MCP server settings, Tab 4 "MCP Server" (v1.7
    │                                  Teilbauauftrag d). LLM-backend dropdown (settings persistence —
    │                                  writes SETTINGS_FILE, no os.environ write). Port field (v1.7.0.1,
    │                                  replaces the removed Ollama-model dropdown) — the HTTP port the
    │                                  server listens on, mirrored into
    │                                  garmin_config.MCP_SERVER_CONFIG_FILE's mcp_http_port key. Headless
    │                                  checkbox (v1.7.0.1, new — not a replacement) mirrored into the same
    │                                  file's mcp_headless key; unchecked by default, since the window
    │                                  stays the default entry point for clients/mcp_server.py (session
    │                                  decision, see that module's entry below) — this only opts a given
    │                                  install OUT of it. "Start MCP Server" button (v1.7 Teilbauauftrag g)
    │                                  launches clients/mcp_server.py directly — build-context-aware
    │                                  launch command (_resolve_mcp_server_launch_command()): T1 =
    │                                  sys.executable + script path, T2 = clients/Starte_MCP_Server.bat
    │                                  next to the frozen EXE, T3.3 = mcp_server.exe next to the frozen
    │                                  EXE (plain existence check disambiguates T2/T3.3, no stored
    │                                  marker). Liveness check (_mcp_server_is_running(), v1.7.0.1) is now
    │                                  a TCP-connect probe against 127.0.0.1:MCP_HTTP_PORT — replaces the
    │                                  PID-lockfile + tasklist check (no more stale-file interpretation:
    │                                  the server either answers on its socket or it doesn't) — blocks
    │                                  with a warning dialog if the port is already reachable; works the
    │                                  same whether the launched process ends up windowed or headless,
    │                                  since either way it listens on the same port. The former "Enable
    │                                  MCP server" checkbox and its status row were removed in Teil (g) —
    │                                  both had become functionally inert once main() stopped gating on
    │                                  the flag (Teil f) and the Start button replaced the manual-start
    │                                  workflow they described; not to be confused with the new Headless
    │                                  checkbox above, a different, still-live control despite the
    │                                  similar-sounding name. The Ollama model dropdown and its "Refresh"
    │                                  button were removed in v1.7.0.1 along with
    │                                  garmin_config.MCP_OLLAMA_MODEL — model selection had no remaining
    │                                  consumer once local-model auto-discovery was dropped from scope.
    │                                  Cloud backend has its own credentials block (provider/API key/
    │                                  model) that reads and writes garmin_config.MCP_LLM_CONFIG_FILE
    │                                  directly — first and only GLA-side writer of that file
    │                                  (clients/mcp_server_gui.py is a second, standalone-context writer,
    │                                  v1.7 Teilbauauftrag f). API key is never reloaded into the widget
    │                                  after a save (write-only field). _mcp_save() additionally mirrors
    │                                  mcp_llm_backend/base_dir/mcp_http_port/mcp_headless into
    │                                  garmin_config.MCP_SERVER_CONFIG_FILE on every save (v1.7.0.1, field
    │                                  set changed from three to four — mcp_ollama_model swapped for
    │                                  mcp_http_port, mcp_headless added). Write failure there is logged
    │                                  only, not a blocking dialog. Wrapped in a QScrollArea at the
    │                                  garmin_app_base.py tab-embedding site (unlike panel_chat.py) —
    │                                  holds more stacked content than fits at low window heights.
    │
    ├── clients/                    ← External tool/service clients (v1.6.6) — no data silo, no
    │   │                              Sole-Write-Authority, distinct from garmin/'s pipeline scope.
    │   │                              Flat imports like garmin/, app/ — no sys.modules package
    │   │                              registration (no relative imports inside clients/)
    │   ├── __init__.py
    │   ├── ollama_client.py        ← Leaf-Node. Wraps Ollama HTTP API (localhost:11434),
    │   │                              non-streaming POST /api/chat. See Module reference
    │   │                              table below.
    │   ├── mcp_server.py           ← Standalone MCP server process, streamable-http transport
    │   │                              (v1.7.0.1, replaces the v1.7 Teilbauauftrag b stdio
    │   │                              transport — host hardcoded 127.0.0.1, port
    │   │                              garmin_config.MCP_HTTP_PORT). Registers maps/mcp_map.py's
    │   │                              six functions as MCP tools. Own sys.path root anchor
    │   │                              (not frozen_paths.add_to_path() — that pattern is
    │   │                              GUI-context-bound, this is a standalone subprocess;
    │   │                              extended v1.7 Teilbauauftrag f to also register
    │   │                              clients/ itself in the frozen/T3.3 case). main() still
    │   │                              opens the Tkinter window by default (v1.7.0.1, session
    │   │                              decision — the "the window is the server" coupling from
    │   │                              Teil f is unchanged, only the transport is new); set
    │   │                              garmin_config.MCP_HEADLESS to skip the window entirely
    │   │                              and run the server directly on this thread instead
    │   │                              (_run_headless() below, analogous to
    │   │                              scheduler/daily_update.py) — a config field, not a CLI
    │   │                              flag. A boot log (_setup_boot_log(), fixed path next to
    │   │                              MCP_SERVER_CONFIG_FILE) captures anything before the
    │   │                              operational log is up; the operational log
    │   │                              (LOG_MCP_MAX = 30) lives here (both the headless path and
    │   │                              mcp_server_gui.py::run_gui() call it — passed in as a
    │   │                              callable to avoid a circular import). No PID lockfile — a
    │   │                              bind failure at mcp.run() startup (OSError, port already
    │   │                              in use) is the natural "already running" signal instead.
    │   │                              See Module reference table below.
    │   └── mcp_server_gui.py       ← Standalone Tkinter window — "the window is the server"
    │                                  (v1.7 Teilbauauftrag f, unchanged coupling in v1.7.0.1 —
    │                                  window closed = process closed). Opened by default from
    │                                  mcp_server.py::main() (unless MCP_HEADLESS); starts
    │                                  mcp_instance.run(transport="streamable-http") — v1.7.0.1,
    │                                  was "stdio" — in a daemon thread (Tkinter's mainloop() is
    │                                  main-thread-bound). Config fields (LLM backend, archive
    │                                  path, Port, Headless checkbox — v1.7.0.1, the Ollama model
    │                                  field is gone along with garmin_config.MCP_OLLAMA_MODEL —
    │                                  or cloud credentials depending on backend), Simple/Detailed
    │                                  log toggle, queue-based log widget (unchanged — no prior
    │                                  Tkinter precedent in the project; ported from
    │                                  garmin_app_standalone.py's PyQt6 queue pattern; the
    │                                  server's own log records reach it too, since server and
    │                                  window share this process again). "🔄 Restart Server"
    │                                  (v1.7.0.1, replacing the v1.7 Teilbauauftrag h button of
    │                                  the same intent) — Self-Relaunch, confirmed via a
    │                                  TCP-connect probe (_is_server_reachable()) against
    │                                  MCP_HTTP_PORT instead of the old lockfile PID poll, then
    │                                  root.destroy() on confirmation to hand over. See Module
    │                                  reference table below.
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
    │   ├── REFERENCE_BROKER.md
    │   ├── MAINTENANCE_GLOBAL.md
    │   ├── MAINTENANCE_GARMIN.md
    │   ├── MAINTENANCE_CONTEXT.md
    │   ├── MAINTENANCE_DASHBOARD.md
    │   ├── CHANGELOG.md
    │   ├── ROADMAP.md
    │   └── CONCEPT_V2-0.md
    │
    └── tests/
        ├── test_local.py           ← Garmin pipeline
        ├── test_local_context.py   ← Context pipeline
        ├── test_dashboard.py       ← Dashboard pipeline
        ├── test_app_logic.py       ← App layer
        ├── test_qt_app.py          ← PyQt6 App layer (v1.5.4+)
        ├── test_build_output.py    ← Build output validation (8 sections)
        ├── test_static.py          ← ruff + bandit linting (v1.6.0 / v1.6.0.4.9.2+)
        ├── check_deps.py           ← Ecosystem monitor
        ├── cve_whitelist.py        ← CVE whitelist data + classify_finding() (v1.6.0.4.4+)
        ├── check_cve_whitelist.py  ← pip-audit wrapper + Ollama unsure-classification (v1.6.0.4.4+)
        └── support.py              ← Shared test helpers
```

---

## Module reference — App Layer & Shared Leaf-Nodes

Compact reference for app-layer and shared leaf-node modules with no
dedicated per-domain reference file. Full inline detail also lives in the
Project Structure tree above — this table exists so these modules are
findable by heading/table search (see `DOC_DRIFT_REPORT.md`, Punkt B).

| Module | Role |
|---|---|
| `app/dialogs.py` | `PasswordConfirmDialog(QDialog)` — shared password entry/confirm dialog. `mode="setup"`: two fields + match-check (new passwords). `mode="unlock"`: one field, no confirm (existing passwords — e.g. mirror import, where `unlock_meta()` validates anyway). Used by `panel_archive.py` (Mirror Container) and `panel_outputs.py` (Encrypted Dashboards). PyQt6-only import, no project-module imports, no business logic. |
| `app/panel_connection.py` | `PanelConnection(QWidget)` — connection dialogs, token reset; indicators delegated to `panel_home.py` (v1.5.4+). |
| `app/panel_home.py` | `PanelHome(QWidget)` — fixed top area: connection indicators, archive status, device table, Daily Actions (Daily Sync / Mirror / Timer / MCP-Settings); Home tab: Dashboard viewer (v1.6.0+, MCP-Settings button added v1.7 Teilbauauftrag d — jumps to Tab 4, no new dialog/action type, same `_action_btn()` factory as its siblings). |
| `app/panel_chat.py` | `PanelChat(QWidget)` — In-App Ollama Chat panel (v1.6.6), fourth tab ("Ollama-Chat"). Composition, no Mixin. Status box (context-file age + Ollama reachability + Start button) always visible; model dropdown/chat history/input unlock only after "Start" — no active chat prep beyond a lightweight reachability ping on tab-open (`garmin_app_base.py::_on_tab_changed`, `index == 3`). Non-streaming requests via `clients/ollama_client.py`. "Neuer Chat" / model switch reset history + system prompt. Full concept: `docs/KONZEPT_ollama_chat_panel.md`. |
| `app/panel_mcp.py` | `PanelMcp(QWidget)` — MCP server settings panel (v1.7 Teilbauauftrag d), fifth tab ("MCP Server"). `get_mcp_settings()`/`load_mcp_settings(s)` pair analogous to `panel_timer.py`'s, fused into `garmin_app_base.py::_collect_settings()` — four fields, `mcp_llm_backend`/`base_dir`/`mcp_http_port`/`mcp_headless` (v1.7.0.1 — `mcp_ollama_model` removed, Port and Headless fields added). No `os.environ` write, no subprocess start/stop bridge beyond the Start button below — the Teil b/c architecture decision (GUI-decoupled standalone subprocess) still holds. `_mcp_save()` additionally mirrors all four MCP fields into `garmin_config.MCP_SERVER_CONFIG_FILE` on every save (`_mcp_save_server_config()`) — lets a standalone `mcp_server.exe` discover them without a running GLA instance; write failure is logged only, not a blocking dialog. `_mcp_server_is_running()` (v1.7.0.1) is a TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` — replaces the PID-lockfile + `tasklist` check the stdio transport required; the "Start MCP Server" button blocks with a warning if the port already answers, regardless of whether the launched process ends up windowed or headless. Cloud backend credentials (provider/API key/model) read and write `garmin_config.MCP_LLM_CONFIG_FILE` directly — first and only GLA-side writer of that file (`clients/mcp_server_gui.py` is a second, standalone-context writer with the same read-merge-write shape, v1.7 Teilbauauftrag f); API key field is write-only (never reloaded after save). Embedded in a `QScrollArea` at the tab site in `garmin_app_base.py` — holds more stacked content than reliably fits at low window heights. (v1.7.0.2) New "Extra allowed hosts" checkbox + comma-separated field + live-parsed preview, gating `garmin_config.MCP_EXTRA_ALLOWED_HOSTS_ENABLED`/`_RAW` the same way the Headless checkbox gates `MCP_HEADLESS` — mirrored into `MCP_SERVER_CONFIG_FILE` by the same `_mcp_save_server_config()`. The Headless checkbox's German label (`"Headless starten (ohne Fenster)"`) was translated to English (`"Start headless (no window)"`) in the same pass. |
| `clients/ollama_client.py` | Leaf-Node (v1.6.6). Wraps the local Ollama HTTP API (`http://localhost:11434`) — `GET /api/tags`, non-streaming `POST /api/chat`. Typed exceptions per failure mode (`OllamaUnreachable`, `OllamaTimeout`, `OllamaModelNotFound`, `OllamaContextLimitExceeded`, generic `OllamaError`). No project-internal imports beyond stdlib/`requests`. Used by `app/panel_chat.py`, `app/panel_mcp.py`'s Ollama-model-refresh, and (v1.7 Teilbauauftrag f) `clients/mcp_server_gui.py`'s own Ollama-model-refresh. |
| `clients/mcp_server.py` | Standalone subprocess (v1.7 Teilbauauftrag b), streamable-http transport (`mcp>=1.28,<2`, v1.7.0.1 — replaces the earlier stdio transport), analogous to `scheduler/daily_update.py` — not an in-process thread off `garmin_app_base.py`. Registers `maps/mcp_map.py`'s original six functions as `@mcp.tool()`s, module-qualified calls to avoid name collision, plus a seventh (v1.7.1), `refresh_cache()`, which delegates directly to `clients/mcp_update.py::sync_all()` rather than to `mcp_map.py`. `FastMCP("Garmin Local Archive", host="127.0.0.1", port=cfg.MCP_HTTP_PORT)` — host is hardcoded, never configurable; only the port varies (`garmin_config.MCP_HTTP_PORT`). `sys.path` root anchor (`_SRC_ROOT`, `_GARMIN_DIR`; frozen case additionally registers `clients/` itself, v1.7 Teilbauauftrag f), not `frozen_paths.add_to_path()` — that helper is GUI-context-bound. Logging exclusively to stderr, plus a fixed-path boot log (`_setup_boot_log()`, next to `MCP_SERVER_CONFIG_FILE`, overwritten each run) attached before anything else; the operational log (`_start_operational_log()`, `LOG_MCP_MAX = 30`) lives here and is passed as a callable into `mcp_server_gui.py::run_gui()` (avoids a circular import) since both the windowed and headless paths need it. `main()` still opens the window by default (v1.7.0.1, session decision — the "the window is the server" coupling from Teil f is unchanged, only the transport is new) via `mcp_server_gui.py::run_gui()`; `garmin_config.MCP_HEADLESS` (a config field, not a CLI flag) instead routes to `_run_headless()`, which runs `mcp.run()` directly on this thread with no window at all, analogous to `scheduler/daily_update.py`. **(v1.7.1)** `main()` now calls `_run_startup_sync()` once, before the `MCP_HEADLESS` branch — runs `clients/mcp_update.py::sync_all()` synchronously and logs its result, so both startup paths perform the SQLite-proxy boot sync identically without the call being duplicated into `clients/mcp_server_gui.py`. Its own `import mcp_update` is a flat, absolute import (not `from . import mcp_update`) — this module is invoked as a standalone script, not imported as part of a package, so a relative import would raise `ImportError: attempted relative import with no known parent package`. No PID lockfile — `mcp.run()` raising `OSError` on an already-bound port is the natural "already running" signal, caught and logged instead of crashing (both paths); the same `socket.bind()` pattern additionally guards `sync_all()` itself against a second, parallel boot sync — see `clients/mcp_update.py` entry below. Build: T2 (`clients/Starte_MCP_Server.bat` launcher) and T3.3 (`mcp_server.exe`, `--onefile`, `windowed=False` left unchanged pending a real Windows build test — see `compiler/build_standalone.py`) both integrated as of Teilbauauftrag e/f. (v1.7.0.2) `FastMCP(...)`'s `transport_security` argument is `None` (SDK auto-default, unchanged) unless `garmin_config.MCP_EXTRA_ALLOWED_HOSTS_ENABLED` is set, in which case an explicit `TransportSecuritySettings` is built from the SDK's own three default hosts/origins plus `garmin_config.MCP_EXTRA_ALLOWED_HOSTS` — fixes reachability for MCP clients connecting via a non-localhost hostname (e.g. Open WebUI's Docker container via `host.docker.internal`), which the SDK's DNS-rebinding protection otherwise rejects outright. See `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` entry above. **(v1.7.1.1)** New `_route_query(kind) -> str` — an internal routing decision point all six query tools now call before delegating, placeholder today (always `"sqlite"`, `TODO v1.7.x` for a real cost/staleness heuristic). The `"sqlite"` branch calls the matching new `clients/mcp_sql.py` read function instead of the corresponding `maps/mcp_map.py` function; `query_fit_activities`/`list_available_fields` route through the same decision point but both branches currently call the identical `mcp_map.py` function (no `mcp_sql.get_fit_range()` until `fit_map.py` lands, v1.8; no cache benefit at all for a code-registry read in the latter case). `refresh_cache()` deliberately does not route — a sync trigger, not a data query. New flat `import mcp_sql`, same reasoning as the existing `import mcp_update`. **(v1.7.1.2)** `query_health()`'s `field` argument is now forwarded to `mcp_sql.get_health_range(date_from, date_to, field=field)` — previously silently dropped since `v1.7.1.1`, so the SQLite branch always returned every health field regardless of what was requested. |
| `clients/mcp_sql.py` *(v1.7.1, extended v1.7.1.1)* | Pure SQLite data-access layer for the aggregation proxy — schema, connection, typed read/write functions. Nine tables: `mcp_health_days`/`mcp_context_days`/`mcp_fit_days` (placeholder, stub pattern mirroring `gateway_map._DOMAIN_BROKERS['fit': None]`)/`mcp_day_status` for Form A (daily time series), `mcp_snapshots` for Form B (point-in-time archive metadata — `stats`/`device_table`/`token_log`/`capability_config`, always fully re-fetched, no delta concept), `mcp_structured_logs`/`mcp_recent_logs` for Form C (`quality_log`/`source_api_log` and the three raw-log directories), plus (v1.7.1.1) `mcp_raw_fields` (field-granular raw-passthrough cache, `recheck`/`attempts`/`last_attempt` columns — modelled on `garmin/quality/_maint.py`'s convention but deliberately reimplemented rather than imported, so `clients/` gains no dependency on `garmin/quality/`) and `mcp_raw_day_hashes` (one SHA-256 content hash per day, the change-detection signal `clients/mcp_update.py`'s raw-passthrough sync needs — content hash, not mtime, since a mirror/restore rewriting byte-identical bytes must not register as a change). `mcp_context_days` gained two additional columns in the same session, `complete_sources_json`/`attempted_sources_json`, tracking per-source completeness rather than a single existence flag. New read functions reassemble the day-keyed cache rows into the shapes `maps/mcp_map.py`'s own query functions return: `get_health_range()`/`get_context_range()`/`get_raw_range()` (time-series) and `get_metadata_range()` (routes internally between the `mcp_snapshots` and `mcp_structured_logs`/`mcp_recent_logs` read paths, mirroring `gateway_map._DATE_FILTERABLE_KINDS`'s own kind classification). **(v1.7.1.2)** `get_health_range()` gained a `field: str | None = None` parameter — when given, only that field is assembled, instead of every field the cached day payload holds (previously ignored entirely, since `mcp_server.py` never forwarded its own `field` argument — see that entry above). Also fixed the same session: each cached field's value carries an extra source-name layer (`{"garmin": {"values": ..., "fallback": ..., "source_resolution": ...}}`, mirrored unchanged from `health_map.get()`'s own result shape) that this function previously read straight through, missing "values"/"fallback"/"source_resolution" entirely since those live one level deeper — every field on every day silently produced an empty values list regardless of what the cache held, since the very first `v1.7.1.1` sync. Now reads through whichever single source is present rather than assuming the field's own keys directly, so this stays correct if a second source is ever added upstream. Single module-level, long-lived `sqlite3.Connection` (`check_same_thread=False`, `PRAGMA journal_mode=WAL`) — correct for the single-process model, since only `clients/mcp_server.py` ever opens this database. Every function raises on failure rather than degrading internally (unlike the `{"data":...,"error":...}` envelope used throughout `maps/`) — `clients/mcp_update.py` is responsible for catching and logging per-unit failures. Database file: `MCP_DB_PATH` above (`BASE_DIR/sqlite/mcp_cache.db`). Pure consumer per the Consumer Invariant (`KONZEPT_mcp_sqlite_proxy_V2.md`) — `garmin_backup.py`/`garmin_mirror.py` never reference this file. |
| `clients/mcp_update.py` *(v1.7.1, extended v1.7.1.1)* | Delta/sync logic — `sync_all()` is the single mechanism called both from `clients/mcp_server.py`'s boot sequence and from the `refresh_cache()` MCP tool (result only logged at boot; returned directly to the LLM as the tool's answer otherwise) — one mechanism, two callers, no second code path. Broker access exclusively through `maps/mcp_map.py` — never a direct import of `maps/gateway_map.py`/`maps/metadata_map.py`/any domain broker, and never direct filesystem access into `garmin_data/`/`context_data/`; the only crossing point between the `clients/` world and the broker layer is `mcp_map.py`, including for the three filename-only introspection functions (`list_daily_log_filenames`/`list_fail_log_filenames`/`list_recent_log_filenames`) that exist solely for this module's own sync bookkeeping. Health delta via `quality_log.json`'s `last_checked` **(v1.7.1.2, was `last_attempt`)** — `last_attempt` is written only on an actual recheck attempt, which never happened for any day in a healthy archive with no failed/rechecked entries, so the compare-value was `null` for every day and the sync silently synced nothing since `v1.7.1.0`; `last_checked` is written on every upsert (new day or recheck alike) and is therefore never null. The `quality_log`-kind branch of `_sync_structured_log()` below uses the same corrected field. `source_api_log` delta via `max(fetched_at, backfilled_fields values)`, not `fetched_at` alone (an additive backfill only updates the per-field `backfilled_fields` timestamp, never the entry's own `fetched_at`) — unaffected by this fix, already correct. Context delta (v1.7.1.1 rewrite) is now per-source completeness, not existence-only — a day with any of the four context sources still missing from its `complete_sources` set is revisited on the next sync; a source with one prior empty attempt gets exactly one more try, then is accepted as permanently empty (no unbounded retry — a context source either answers with data or with a definitive "nothing here", unlike raw/health's possible-later-availability case). New `_sync_raw_fields()`/`_sync_one_raw_field()` (v1.7.1.1) — field-granular, hash-gated delta for raw-passthrough: a day's cached content hash (`maps/metadata_map.py`'s `get_raw_file_hashes()`, via `mcp_map`) is compared against the freshly-read one; unchanged day → only currently-pending fields re-queried, changed or new day → every currently-registered raw field re-queried, which also covers nachtraegliche Datenlieferung (a GDPR bulk import or silo repair) to a day whose recheck window had already closed, without a separate manual-reset code path. New `RAW_RETRY_WINDOW_DAYS` module constant (v1.7.1.1) — deliberately independent from `garmin_quality.py`'s `GARMIN_INTRADAY_RETRY_WINDOW_DAYS` above, since raw-passthrough fields have no factual link to Garmin's own intraday-availability window. The three raw-log directories get a full filename diff on every sync rather than a delta tied to `mcp_health_days` — a log file's filename-encoded date is the sync timestamp, not necessarily the archived day it reports on. Concurrency: `sync_all(is_boot: bool = False)` **(v1.7.1.2, new parameter)** — a `socket.bind()` on `garmin_config.MCP_HTTP_PORT`, held for `sync_all()`'s duration, closes the gap between two parallel `mcp_server.py` boot syncs that would otherwise both start before either process's own `mcp.run()` bind guard could catch it, but now runs only when `is_boot=True`. Previously ran unconditionally on every call including from `refresh_cache()` — by the time that tool can be called at all, `mcp.run()` already legitimately holds the port, so the guard's own bind attempt always failed, making `refresh_cache()` unconditionally error out at runtime (confirmed in live logs, `[WinError 10048]` on every post-boot call). A plain `threading.Lock` (analogous to `garmin_quality.py`'s `QUALITY_LOCK`) serializes overlapping `refresh_cache()` calls after boot — this guard is unaffected by the `is_boot` change and remains identical for both callers. Result dict reports both `*_updated` and `*_failed` counts per data category (v1.7.1.1 additionally: `raw_days_touched`/`raw_fields_failed`) — see `AUDIT_FINDINGS_v1_7_1.md` F-2. Own `import mcp_sql` is a flat, absolute import for the same reason as `mcp_server.py`'s `import mcp_update` — this module is itself loaded via that flat import, so it carries no package context at import time. |
| `clients/mcp_server_gui.py` | Standalone Tkinter window (v1.7 Teilbauauftrag f) — "the window is the server," coupling unchanged in v1.7.0.1 (window closed = process closed), opened by default by `mcp_server.py::main()` unless `garmin_config.MCP_HEADLESS` is set. `run_gui(mcp_instance, logger, boot_handler, start_operational_log)` starts `mcp_instance.run(transport="streamable-http")` — v1.7.0.1, was `"stdio"` — in a `daemon=True` thread before building the window, then blocks in `root.mainloop()` on the main thread; a bind failure (`OSError`) in that thread is caught and surfaced via a status label + warning dialog shortly after the window appears, rather than crashing silently. `start_operational_log` is passed in from `mcp_server.py` (not imported) to avoid a circular import, since that module already imports this one to call `run_gui()`. Reads/writes `garmin_config.MCP_SERVER_CONFIG_FILE` directly (second writer alongside `panel_mcp.py`'s mirror — see that file's docstring for the documented Sole-Write-Authority exception; `mcp_http_port`/`mcp_headless` replace `mcp_ollama_model` as the fourth/fifth mirrored fields — see below) and `garmin_config.MCP_LLM_CONFIG_FILE` (cloud credentials, same read-merge-write shape as `panel_mcp.py::_mcp_save_cloud_config()`). Config fields: LLM backend, archive path, Port, Headless checkbox (v1.7.0.1, new — takes effect on the *next* start, not this running instance), or cloud credentials depending on backend — the Ollama model dropdown and its "Refresh" button are gone (v1.7.0.1, along with `garmin_config.MCP_OLLAMA_MODEL`). Log widget unchanged in shape from v1.7 — `_QueueLogHandler` + `root.after(100, ...)` poll loop, now receiving both this window's own log lines and the server's, since both run in this process again. "🔄 Restart Server" button (v1.7.0.1, replacing the v1.7 Teilbauauftrag h button of the same intent) — `_resolve_mcp_server_launch_command()` (shortened, standalone copy of `app/panel_mcp.py`'s function of the same name — `clients/` does not import from `app/`) resolves the T1/T2/T3.3 launch target, launches it via `subprocess.Popen` with the *saved* settings (Save first, then Restart — same two-step as before), then `_poll_reachable()` (`root.after(500, ...)`, 12s timeout) checks `_is_server_reachable()` — a real TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` — instead of polling a PID lockfile for a changed value. On success calls `root.destroy()`, which ends this process (and the old server's daemon thread with it) — the v1.7 Teilbauauftrag h **known limitation** (poll only confirmed a new PID, not real health) is resolved by construction here: a TCP accept only happens once `mcp.run()` has actually bound and is serving. On timeout the old server is left running and the button re-enables. (v1.7.0.2) Same "Extra allowed hosts" checkbox/field/preview as `app/panel_mcp.py`, backing the same `garmin_config` constants; also gained a `"🦄  GARMIN LOCAL ARCHIVE"` header label (text/font only, matching `garmin_app_base.py`'s branding — no color-theme or icon changes, deliberately out of scope this session). The Headless checkbox's German label was translated to English alongside `panel_mcp.py`'s. |
| `garmin_app_base.py` | View layer (`GarminApp`) — PyQt6 `QMainWindow`, fixed top (`panel_home`) + `QTabWidget`: Home / Files / Settings / Ollama-Chat / MCP Server (v1.6.0+, fourth tab added v1.6.6, fifth tab added v1.7 Teilbauauftrag d). Settings tab: two-column layout — Settings left (340px), Actions right (flex). `_sheet_arrow` label mirrors `_sheet_combo` visibility (v1.6.0.7). |
| `qwebengine_hardening.py` | Leaf-Node. `harden(view)` — disables `LocalContentCanAccessFileUrls`, `LocalContentCanAccessRemoteUrls`, `JavascriptCanOpenWindows`, `PluginsEnabled`, `JavascriptCanAccessClipboard` on a `QWebEngineView`. `JavascriptEnabled` stays `True` — Plotly dashboards require it. Idempotent — safe to call multiple times on the same view. Called from `panel_home.py` and `garmin_app_base.py` after each `QWebEngineView()` instantiation. |
| `frozen_paths.py` | Leaf-Node. Central frozen-path resolution — replaces previously duplicated `sys.frozen`/`sys._MEIPASS`/`sys.executable` branches (`panel_outputs.py` ×6, `panel_home.py`, the `garmin_live_fetch` call site, doc lookups). Three side-effect-separated functions: `scripts_root()` (root for `garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/` — T3 verified via canonical distinguisher: `dash_runner.py` must actually exist under `scripts/dashboards/`, not just `scripts/` itself), `add_to_path(root, *subs)` (mutates `sys.path` as an explicit, separate step), `doc_path(filename)` (finds bundled docs — `info/` next to the EXE when frozen, three-step dev chain otherwise: repo root → `src/docs/` → `src/scheduler/`; returns `None` if not found, never guesses). |
| `log_utils.py` | Leaf-Node (v1.6.6.1). One function: `with_timestamp(log_fn)` — wraps a log callback so every message gets a `"%Y-%m-%d %H:%M:%S "` prefix, matching the format `logging.Formatter` uses elsewhere in the project. Pass-through — returns `None` unchanged if `log_fn` is `None`. Deliberately not placed in `garmin/garmin_utils.py` despite that module's own Leaf-Node status — `dashboards/` has zero project-module imports by design, kept independent of `garmin/`; `log_utils.py` sits at the `src/` root instead, alongside `frozen_paths.py`, so `context/context_collector.py` and `dashboards/dash_runner.py` can both import it without creating a cross-domain dependency. Used to fix inconsistent console-log timestamps between the Garmin page (`logging` module) and the Context/Dashboard pipeline (`log_callback(str)`). |

`app/panel_settings.py`, `app/panel_archive.py`, `app/panel_timer.py`,
`app/panel_outputs.py` already carry sufficient inline detail in the
Project Structure tree above and are not duplicated here.

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
│       ├── daily/
│       ├── recent/
│       ├── fail/
│       └── mcp/                    ← MCP server logs (v1.7)
│           ├── mcp_<timestamp>.log     ← server operational log
│           ├── update/                 ← clients/mcp_update.py sync log (v1.7.1)
│           │   └── mcp_update_<timestamp>.log
│           └── sql/                    ← reserved for clients/mcp_sql.py's own log (v1.7.1)
│
├── context_data/                ← External API data (v1.4+)
│   ├── weather/
│   │   └── raw/
│   │       └── weather_YYYY-MM-DD.json
│   └── pollen/
│       └── raw/
│           └── pollen_YYYY-MM-DD.json
│
└── sqlite/                      ← SQLite aggregation-proxy cache (v1.7.1)
    └── mcp_cache.db                 ← derived, reconstructible from the archive —
                                        see MCP_DB_PATH above. Never touched by
                                        garmin_backup.py/garmin_mirror.py.
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
