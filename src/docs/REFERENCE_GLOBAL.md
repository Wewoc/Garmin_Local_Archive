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
| `CONTEXT_WEATHER_SUMMARY_DIR` | `CONTEXT_DIR/weather/summary` | Archived weather files (daily, no raw/ — Open-Meteo Weather has no intraday resolution) |
| `CONTEXT_POLLEN_SUMMARY_DIR` | `CONTEXT_DIR/pollen/summary` | Archived pollen files, daily aggregate (v1.7.1.11 — renamed from `CONTEXT_POLLEN_DIR`) |
| `CONTEXT_POLLEN_RAW_DIR` | `CONTEXT_DIR/pollen/raw` | Archived pollen files, hourly/timestamped (v1.7.1.11) |
| `CONTEXT_BRIGHTSKY_SUMMARY_DIR` | `CONTEXT_DIR/brightsky/summary` | Archived Brightsky DWD files, daily aggregate (v1.7.1.11 — renamed from `CONTEXT_BRIGHTSKY_DIR`) |
| `CONTEXT_BRIGHTSKY_RAW_DIR` | `CONTEXT_DIR/brightsky/raw` | Archived Brightsky DWD files, hourly/timestamped (v1.7.1.11) |
| `CONTEXT_AIRQUALITY_SUMMARY_DIR` | `CONTEXT_DIR/airquality/summary` | Archived air quality files, daily aggregate (v1.7.1.11 — renamed from `CONTEXT_AIRQUALITY_DIR`) |
| `CONTEXT_AIRQUALITY_RAW_DIR` | `CONTEXT_DIR/airquality/raw` | Archived air quality files, hourly/timestamped (v1.7.1.11) |
| `LOCAL_CONFIG_FILE` | `BASE_DIR/local_config.csv` | User location config for context collect |
| `MCP_LLM_CONFIG_FILE` | `~/.garmin_mcp_llm_config.json` | Cloud LLM `provider`/`model` for `MCP_LLM_BACKEND="cloud"` — missing/incomplete = cloud backend unavailable, not an error (v1.7 Teilbauauftrag c). **(v1.7.2)** No longer carries `api_key` — the key itself is stored in Windows Credential Manager instead, one entry per provider (`clients/cloud_credential_store.py`), same mechanism `garmin_security.py` uses for the Garmin token encryption key. See `KEYRING_SERVICE`/`KEYRING_USER` below. |
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

**(v1.7.2)** `clients/cloud_credential_store.py` reuses the same
`KEYRING_SERVICE` ("GarminLocalArchive") for Cloud LLM API keys — one WCM
entry per provider under the username `"cloud_llm_<provider>_api_key"`
(e.g. `"cloud_llm_anthropic_api_key"`), so switching providers never
requires re-entering a key already saved once. Distinct usernames prevent
any collision with the Garmin password/token-encryption-key entries above.
No AES/PBKDF2 layer on top (unlike `garmin_security.py`'s own token
encryption) — an API key is a short string, not a multi-field JSON blob, so
it fits directly into one WCM credential entry.

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
    ├── garmin_app_base.py          ← View layer (GarminApp) — PyQt6 QMainWindow, fixed top (panel_home) + QTabWidget: Home / Files / Settings / Chat / MCP Server (v1.6.0+, fourth tab added v1.6.6 as "Ollama-Chat", renamed "Chat" v1.7.2, fifth tab added v1.7 Teilbauauftrag d). Settings tab: two-column layout — Settings left (340px), Actions right (flex). `_sheet_arrow` label mirrors `_sheet_combo` visibility (v1.6.0.7).
    ├── theme.py                    ← Single source of truth for all app/dashboard
    │                                  color tokens (v_theme_01) — see module table below
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
    │   ├── panel_chat.py           ← PanelChat(QWidget) — In-App Chat, Tab 3 "Chat" (v1.6.6, renamed
    │   │                              from "Ollama-Chat" v1.7.2) — see Module reference table below
    │   ├── dialog_chat_history.py  ← ChatHistoryDialog(QDialog) — saved chat sessions, Load/Delete
    │   │                              (v1.7.2), opened from panel_chat.py's "Chat History" button
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
    │   ├── mcp_server_gui.py       ← Standalone Tkinter window — "the window is the server"
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
    │   ├── mcp_client.py            ← Leaf-Node (v1.7.2). Typed HTTP client for
    │   │                              clients/mcp_server.py's own streamable-http endpoint —
    │   │                              is_reachable()/list_tools()/call_tool(), typed exceptions
    │   │                              (McpUnreachable/McpTimeout/McpToolError). Consumed by
    │   │                              app/panel_chat.py's tool-calling turn loops.
    │   ├── mcp_process.py           ← Leaf-Node (v1.7.2). Start/Stop process control for
    │   │                              clients/mcp_server.py — shared between app/panel_chat.py's
    │   │                              and app/panel_mcp.py's own Start/Stop button pairs.
    │   ├── mcp_tool_chat.py         ← Leaf-Node (v1.7.2). converse() — Ollama + MCP agentic turn
    │   │                              loop: call ollama_client.chat_with_tools() → inspect
    │   │                              tool_calls → execute via mcp_client.call_tool() → feed the
    │   │                              result back → repeat, capped at MAX_TOOL_TURNS.
    │   ├── openai_tool_schema.py    ← Leaf-Node (v1.7.2). to_openai_style_tools() — the
    │   │                              OpenAI-style tool-schema translator shared by Ollama and
    │   │                              OpenAI (Ollama's own tool-calling schema was modeled on
    │   │                              OpenAI's, one converter serves both).
    │   ├── cloud_llm_client.py      ← Cloud LLM dispatcher (v1.7.2) — normalizes
    │   │                              chat()/chat_with_tools()/chat_stream()/
    │   │                              chat_stream_with_tools() across providers; app/panel_chat.py
    │   │                              never knows which one is configured. Adding a provider =
    │   │                              adding one cloud_llm_<name>.py module + one _PROVIDERS line.
    │   ├── cloud_llm_anthropic.py   ← Anthropic provider (v1.7.2) behind cloud_llm_client.py —
    │   │                              wraps the official anthropic SDK. Real two-way message/
    │   │                              tool-schema translation (input_schema instead of
    │   │                              parameters, tool calls as tool_use content blocks instead
    │   │                              of a separate field) — Anthropic's shape genuinely differs
    │   │                              from OpenAI's/Ollama's.
    │   ├── cloud_llm_openai.py      ← OpenAI provider (v1.7.2) behind cloud_llm_client.py — wraps
    │   │                              the official openai SDK. No message-shape translation
    │   │                              needed (same shape Ollama already uses); tool schema reuses
    │   │                              openai_tool_schema.py unchanged.
    │   ├── cloud_tool_chat.py       ← Leaf-Node (v1.7.2). Cloud + MCP counterpart to
    │   │                              mcp_tool_chat.py — converse()/converse_stream(), sitting on
    │   │                              cloud_llm_client.chat_with_tools()/chat_stream_with_tools()
    │   │                              instead of Ollama's. converse_stream() is Cloud-only —
    │   │                              Ollama+MCP has no streaming counterpart, see
    │   │                              ollama_client.py's own note above.
    │   ├── chat_session_store.py    ← Leaf-Node (v1.7.2). Chat session persistence under
    │   │                              <base_dir>/chats/, one JSON file per conversation,
    │   │                              auto-saved after every turn. SHA-256 content hash of
    │   │                              health_garmin.json gates whether a json-datasource session
    │   │                              can still be resumed live or only viewed read-only
    │   │                              (mcp-datasource sessions are always resumable).
    │   └── cloud_credential_store.py ← Leaf-Node (v1.7.2). Cloud LLM API key storage via Windows
    │                                   Credential Manager, one entry per provider — same keyring
    │                                   mechanism garmin/garmin_security.py already uses for the
    │                                   Garmin token encryption key, no AES/PBKDF2 layer needed for
    │                                   a short string. See KEYRING_SERVICE entry above.
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
        ├── test_cloud_llm.py       ← cloud_llm_client/cloud_llm_anthropic/cloud_llm_openai (v1.7.2)
        ├── test_mcp_tool_chat.py   ← mcp_tool_chat.converse()/openai_tool_schema (v1.7.2)
        ├── test_cloud_tool_chat.py ← cloud_tool_chat.converse()/converse_stream() (v1.7.2)
        ├── test_chat_session_store.py     ← chat_session_store.py (v1.7.2)
        ├── test_cloud_credential_store.py ← cloud_credential_store.py (v1.7.2)
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
| `app/popups/capability_scan.py`, `app/popups/dashboard_create.py`, `app/popups/custom_dashboard.py`, `app/popups/encrypted_dashboards.py`, `app/popups/_dashboard_build.py` | Dashboard/config popups (v1.7.2.1 — Codereview & Cleanup), extracted from `panel_outputs.py`: the first four each expose one `open_popup(panel)`, called from a one-line delegate method still on `PanelOutputs` (button-wiring unchanged). `_dashboard_build.py` is the shared build/encrypt engine both `custom_dashboard.py` and `encrypted_dashboards.py` depend on (`run_dashboards()`/`run_encrypted()`) — neither popup imports the other. |
| `app/panel_connection.py` | `PanelConnection(QWidget)` — connection dialogs, token reset; indicators delegated to `panel_home.py` (v1.5.4+). |
| `app/panel_home.py` | `PanelHome(QWidget)` — fixed top area: connection indicators, archive status, device table, Daily Actions (Daily Sync / Mirror / Timer / MCP-Settings); Home tab: Dashboard viewer (v1.6.0+, MCP-Settings button added v1.7 Teilbauauftrag d — jumps to Tab 4, no new dialog/action type, same `_action_btn()` factory as its siblings). |
| `app/panel_chat.py` | `PanelChat(QWidget)` — In-App Chat panel (v1.6.6), fourth tab ("Chat", renamed from "Ollama-Chat" v1.7.2). Composition, no Mixin. Status box (context-file age + Ollama reachability + Start button) always visible; model dropdown/chat history/input unlock only after "Start" — no active chat prep beyond a lightweight reachability ping on tab-open (`garmin_app_base.py::_on_tab_changed`, `index == 3`). Full original concept: `docs/KONZEPT_ollama_chat_panel.md`. **(v1.7.2)** Substantially extended — full session narrative in `CHANGELOG.md`, this entry is the settled architecture. Two independent dropdowns replace the original single-backend design: **Backend** (`ollama` / `cloud` — the latter speaking to Anthropic or OpenAI via `clients/cloud_llm_client.py`, credentials configured on the MCP Server tab) and **Source** (`json` — the original daily-aggregate snapshot, non-streaming plain chat / `mcp` — live MCP tool-calling against the archive). Both lock for the duration of a running session the moment Start succeeds — previously a mid-chat switch only reset history without preventing a live `mcp`-backed conversation from silently mixing with a `json` one — and only unlock again on Stop or a failed Start. Four request shapes depending on the combination: `ollama`+`json` (`clients/ollama_client.py::chat_stream()`, streaming), `cloud`+`json` (`cloud_llm_client.chat_stream()`, streaming), `ollama`+`mcp` (`clients/mcp_tool_chat.py::converse()`, non-streaming turn loop — Ollama's own streaming+tool-calling support is currently unreliable upstream, deliberately not attempted), `cloud`+`mcp` (`clients/cloud_tool_chat.py::converse_stream()`, streaming turn loop — one chat bubble per LLM turn, a short "🔧 Calling `<tool>`…" system line between turns for each tool call). Streaming renders incrementally via `QTextCursor`-based methods (`_chat_start_stream_line()`/`_chat_append_stream_chunk()`) instead of `QTextEdit.append()`, which always starts a new paragraph. Split view (MCP log tail, `_chat_tail_mcp_log()`) shown whenever Source is `mcp`, tailing the same operational log file `clients/mcp_server.py` already writes — no separate logging mechanism. Every completed turn auto-saves the running conversation via `clients/chat_session_store.py` (one JSON file per "New Chat" span); a new "Chat History" button next to Start/Stop opens `app/dialog_chat_history.py`'s `ChatHistoryDialog` to load or delete a saved session — loading locks Backend/Source immediately, before Start is even clicked, and renders the transcript read-only right away; continuing it live still requires a Start click (same reachability checks as any fresh start). "Neuer Chat" / model switch still reset history + system prompt, unchanged in principle. **Post-v1.7.2 fix (garmin_collector-3_experiment):** each of `_chat_on_send()`'s four worker closures (Ollama+`json`, Ollama+`mcp`, Cloud+`json`, Cloud+`mcp`) used to call its lazy-loader functions (`_load_ollama_client()`/`_load_mcp_tool_chat()`/`_load_mcp_client()`/`_load_cloud_llm_client()`/`_load_cloud_tool_chat()`) *before* entering the worker's own `try:` block — an import failure there (a transient environment issue, e.g. antivirus locking a `scripts/clients/*.py` file mid-scan, reproduced in T2) ran completely unguarded, silently killing the background thread with zero `self._app._dispatch(...)` call: the UI stayed on "Waiting for response" forever, no error, no log entry. Root cause found via a real T2 reproduction (Open WebUI hitting the same MCP server worked instantly, ruling out the server/Ollama/network layer entirely) — see `PROTOKOLL_experiment.md`. Fix: each worker's lazy-import calls now sit in their own guarded `try:`/`except Exception` that dispatches to `_chat_on_error()` and returns early on failure, kept deliberately separate from the business-logic `try:` below it — the existing typed `except mcp_client.McpClientError`/`except ollama_client.OllamaError`-style clauses reference those very module names, so if the import binding that name had failed, evaluating the `except` clause itself would raise a fresh `NameError` while Python is still matching the original exception, just as unguarded as the original bug. Each business-logic `try:` also gained a trailing generic `except Exception`, so an unclassified failure inside `converse()`/`converse_stream()`/`chat_stream()` itself (not just at import time) now reaches the UI too, dispatched to `_chat_on_error()` (non-streaming branches) or `_chat_on_stream_error()` (streaming branches, preserving any partial text already rendered) instead of dying silently. **Post-v1.7.2 fix (garmin_collector-3_experiment, Baustein 30):** `_chat_load_system_prompt()` (called on every fresh Start via `_chat_on_models_loaded()`/`_chat_on_cloud_config_loaded()`, both Ollama and Cloud paths) already reset `self._history` on every non-resumed Start — a Stop then Start without an intervening "Neuer Chat" click was, from the model's point of view, already a fresh conversation. It never cleared `self._chat_view` (the visible transcript) though — only `_chat_on_new_chat()` did that — so the old conversation stayed on screen, looking like it was still part of the (actually fresh) one. Found live (Timo: Stop, Start again, old chat still shown). Fix: `self._chat_view.clear()` added to `_chat_load_system_prompt()`'s non-resume branch, right alongside the existing `self._history = []` reset — the resume branch (loading a saved session) is untouched, since that one deliberately renders the loaded transcript instead of clearing it. |
| `app/panel_mcp.py` | `PanelMcp(QWidget)` — MCP server settings panel (v1.7 Teilbauauftrag d), fifth tab ("MCP Server"). `get_mcp_settings()`/`load_mcp_settings(s)` pair analogous to `panel_timer.py`'s, fused into `garmin_app_base.py::_collect_settings()` — four fields, `mcp_llm_backend`/`base_dir`/`mcp_http_port`/`mcp_headless` (v1.7.0.1 — `mcp_ollama_model` removed, Port and Headless fields added). No `os.environ` write, no subprocess start/stop bridge beyond the Start button below — the Teil b/c architecture decision (GUI-decoupled standalone subprocess) still holds. `_mcp_save()` additionally mirrors all four MCP fields into `garmin_config.MCP_SERVER_CONFIG_FILE` on every save (`_mcp_save_server_config()`) — lets a standalone `mcp_server.exe` discover them without a running GLA instance; write failure is logged only, not a blocking dialog. `_mcp_server_is_running()` (v1.7.0.1) is a TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` — replaces the PID-lockfile + `tasklist` check the stdio transport required; the "Start MCP Server" button blocks with a warning if the port already answers, regardless of whether the launched process ends up windowed or headless. Cloud backend credentials (provider/model, plus the API key — see below) read and write `garmin_config.MCP_LLM_CONFIG_FILE` directly — first and only GLA-side writer of that file (`clients/mcp_server_gui.py` is a second, standalone-context writer with the same read-merge-write shape, v1.7 Teilbauauftrag f). Embedded in a `QScrollArea` at the tab site in `garmin_app_base.py` — holds more stacked content than reliably fits at low window heights. (v1.7.0.2) New "Extra allowed hosts" checkbox + comma-separated field + live-parsed preview, gating `garmin_config.MCP_EXTRA_ALLOWED_HOSTS_ENABLED`/`_RAW` the same way the Headless checkbox gates `MCP_HEADLESS` — mirrored into `MCP_SERVER_CONFIG_FILE` by the same `_mcp_save_server_config()`. The Headless checkbox's German label (`"Headless starten (ohne Fenster)"`) was translated to English (`"Start headless (no window)"`) in the same pass. **(v1.7.2)** Provider field is now a dropdown sourced from `clients/cloud_llm_client.py`'s `_PROVIDERS` registry instead of free text — closes a silent-typo failure mode; a previously-saved unknown/legacy value is inserted as an extra dropdown item rather than dropped. The API key itself no longer goes into `MCP_LLM_CONFIG_FILE` at all (write-only field dropped along with it) — it is stored in Windows Credential Manager, one entry per provider, via `clients/cloud_credential_store.py`; the key-status label refreshes live for whichever provider is currently selected in the dropdown, not only on load. |
| `clients/ollama_client.py` | Leaf-Node (v1.6.6). Wraps the local Ollama HTTP API (`http://localhost:11434`) — `GET /api/tags`, `POST /api/chat`. Typed exceptions per failure mode (`OllamaUnreachable`, `OllamaTimeout`, `OllamaModelNotFound`, `OllamaContextLimitExceeded`, generic `OllamaError`). No project-internal imports beyond stdlib/`requests`. Used by `app/panel_chat.py`, `app/panel_mcp.py`'s Ollama-model-refresh, and (v1.7 Teilbauauftrag f) `clients/mcp_server_gui.py`'s own Ollama-model-refresh. **(v1.7.2)** `chat()` stays non-streaming, unchanged; `chat_with_tools(model, messages, tools)` added (native `tool_calls` field, plus a content-text-JSON fallback for models that emit an otherwise-correct tool call outside that field — `parse_content_fallback_tool_call()`); `chat_stream()` (plain chat) and `chat_stream()`-with-tools were both evaluated — only plain `chat_stream()` was built, deliberately: Ollama's own streaming+tool-calling combination is currently unreliable upstream (High-severity open Ollama issue — tool calls arrive as one block with no accompanying text under `stream: true`+`tools`), so `chat_with_tools()` has no streaming counterpart, permanently, not a "not yet built" gap. Each addition duplicates rather than touches the already-tested function beside it, same precedent `chat_with_tools()` itself set for `chat()`. |
| `clients/mcp_client.py` | Leaf-Node (v1.7.2). Typed HTTP client for `clients/mcp_server.py`'s own streamable-http endpoint — `is_reachable()`, `list_tools()`, `call_tool(name, arguments)`. Typed exceptions (`McpUnreachable`, `McpTimeout`, `McpToolError`, base `McpClientError`) — the same tool-calling consumer surface `mcp_server.py`'s external clients (Open WebUI, Claude Desktop, ...) use, just from inside the GLA process. Consumed by `clients/mcp_tool_chat.py`/`clients/cloud_tool_chat.py` and directly by `app/panel_chat.py` (to catch `McpClientError` specifically, distinct from a provider-side error). |
| `clients/mcp_process.py` | Leaf-Node (v1.7.2). Start/Stop process control for `clients/mcp_server.py` — `start()`/`stop()`/`is_running()`, same build-context-aware launch-command resolution `app/panel_mcp.py`/`clients/mcp_server_gui.py` already had, now shared rather than duplicated a third time. Used by `app/panel_chat.py`'s Start (recognizes an already-running server, only launches a new one if the `mcp` source is selected and none is reachable) and Stop (pragmatic, not ownership-based — stops the server regardless of who started it), symmetric to `app/panel_mcp.py`'s own Start/Stop pair. **Post-Baustein-23 fix (garmin_collector-3_experiment):** now carries its own `sys.path` bridge to `garmin/` (same one-line pattern `maps/garmin_health_map.py` uses to reach `garmin/`), needed for its `import garmin_config as cfg` (`MCP_HTTP_PORT` default). Previously had none — its only two importers' lazy loaders (`app/panel_chat.py`/`app/panel_mcp.py`'s own `_load_mcp_process()`) only ever add `"clients"` to `sys.path`, never `"garmin"`, so the import silently relied on `garmin/` already being on `sys.path` from `garmin_app_base.py`'s own app-wide startup — true in practice (both loaders only ever run inside the fully-booted GUI app) but never guaranteed by this module itself, unlike every sibling `clients/` module that imports `garmin_config` (see Module path resolution table in `MAINTENANCE_GLOBAL.md`). **Post-Baustein-25 fix (garmin_collector-3_experiment, Baustein 29):** `COMMAND_TIMEOUT` raised 5s → 20s (5s was observed too short on Timo's machine — Windows Defender behavior-monitoring overhead on process creation, not netstat/taskkill themselves being slow). `start()` now remembers the launched process's own PID in module-level `_last_started_pid`; `stop()` tries killing that PID first via the new `_kill_pid_tree()` helper (`taskkill /PID <pid> /T /F` — `/T` is required, not optional: a T2 launch goes through `Starte_MCP_Server.bat`, so `Popen().pid` is the cmd.exe/bat host, not the `python.exe` it spawns, and a T3.3 `--onefile` `mcp_server.exe` always runs as a bootloader plus a second, real worker process it launches as its own child — see this file's `mcp_server.py` entry below for that two-process finding — so killing only the remembered PID without `/T` would leave the actual server running while `taskkill` reports success), skipping the `netstat -ano` scan entirely in the common case. Falls back to the pre-existing `netstat`-based lookup if no PID was remembered (server started externally) or the remembered PID is already stale. New `tests/test_mcp_process.py` (13 tests) covers both paths — previously untested; every `app/panel_*.py` test mocked this module wholesale. |
| `clients/mcp_tool_chat.py` | Leaf-Node (v1.7.2). `converse(model, messages, ...) -> dict` — the Ollama+MCP agentic turn loop: `ollama_client.chat_with_tools()` → inspect `tool_calls` → execute each via `mcp_client.call_tool()` (a tool-execution failure is fed back to the model as text, not raised — only the initial `mcp_client.list_tools()` failure propagates) → append the tool result → repeat, capped at `MAX_TOOL_TURNS` (8). Returns `{"content", "messages", "hit_max_turns"}` — `messages` carries the full turn-by-turn history including every tool round-trip, `app/panel_chat.py` replaces its own history with it wholesale rather than appending. `system_prompt` seeded only if `messages` has no existing system entry. Live-verified against a real Ollama + running MCP server; automated coverage in `tests/test_mcp_tool_chat.py` (SDK/HTTP layer mocked). |
| `clients/openai_tool_schema.py` | Leaf-Node (v1.7.2). One function, `to_openai_style_tools(mcp_tools) -> list[dict]` — reshapes `clients/mcp_client.py`'s `list_tools()` result into the `{"type": "function", "function": {"name", "description", "parameters"}}` shape both Ollama and OpenAI expect (Ollama's own tool-calling schema was modeled on OpenAI's) — one converter, not duplicated per consumer. Used by `clients/ollama_client.py::chat_with_tools()` and `clients/cloud_llm_openai.py`'s two `chat_with_tools`/`chat_stream_with_tools` functions. |
| `clients/cloud_llm_client.py` | Cloud LLM dispatcher (v1.7.2). Single entry point `app/panel_chat.py` imports for backend `"cloud"` — mirrors `clients/ollama_client.py`'s role for backend `"ollama"`. `_PROVIDERS = {"anthropic": "cloud_llm_anthropic", "openai": "cloud_llm_openai"}`; `_load_provider()` resolves and imports the matching module lazily. `chat()`/`chat_with_tools()` raise `CloudLlmConfigError` immediately for an unknown provider or missing model/API key, wrap every other failure into one `CloudLlmError` type (so `app/panel_chat.py` never needs a provider-specific `except` clause) — `chat_stream()`/`chat_stream_with_tools()` are generator functions, so that same validation and wrapping is deferred to the caller's first iteration instead of call time; the `try`/`except` inside each streaming function must wrap the `for` loop itself, not just the call that creates the generator, or a failure raised mid-stream would never be caught. Adding a new provider = one `cloud_llm_<name>.py` module (`chat()`, and optionally `chat_with_tools()`/`chat_stream()`/`chat_stream_with_tools()`) + one `_PROVIDERS` line — no `app/panel_chat.py` change needed. |
| `clients/cloud_llm_anthropic.py` | Anthropic provider (v1.7.2) behind `clients/cloud_llm_client.py`. Wraps the official `anthropic` SDK (`anthropic>=1.5,<2`) rather than a hand-rolled `requests` client, so most of Anthropic's own API-surface churn is absorbed by SDK version bumps. `_split_system()` — Anthropic takes the system prompt as a separate top-level parameter, not a `role: "system"` message. `to_anthropic_tools()`/`_history_to_anthropic()` — real two-way translation for `chat_with_tools()`/`chat_stream_with_tools()`: Anthropic's tool schema uses `input_schema` (not `parameters`), tool calls are `tool_use` content blocks embedded in the assistant message (not a separate `tool_calls` field), and tool results go back as a `tool_result` content block inside a *user* message (not a `role: "tool"` message) — a shape genuinely different from OpenAI's/Ollama's, unlike `cloud_llm_openai.py` below. `chat_stream_with_tools()` iterates the SDK's own streaming event union directly (`TextEvent`/`ContentBlockStopEvent`, not the simpler `.text_stream` helper `chat_stream()` uses) — the SDK already assembles a content block's final shape (including a completed `tool_use` block's `input`) by the time its stop event fires, no hand-rolled JSON accumulation needed. Not live-verified against the real API in this build (no API key available) — grounded against the installed SDK's own type stubs. |
| `clients/cloud_llm_openai.py` | OpenAI provider (v1.7.2) behind `clients/cloud_llm_client.py`. Wraps the official `openai` SDK (`openai>=3.14,<4`). No message-shape translation needed — OpenAI's Chat Completions API already takes the same `role: "system"/"user"/"assistant"` list shape `app/panel_chat.py`'s own history and `clients/ollama_client.py::chat()` use; tool schema reuses `clients/openai_tool_schema.py::to_openai_style_tools()` unchanged. `chat_stream_with_tools()` must assemble tool calls by hand, unlike Anthropic's SDK: each streamed chunk's `delta.tool_calls` is a list of fragments keyed by `index`, `.function.arguments` arriving as a JSON string split across many chunks that must be concatenated (not parsed) until the turn ends. Not live-verified against the real API in this build (no API key available) — grounded against the installed SDK's own type stubs. |
| `clients/cloud_tool_chat.py` | Leaf-Node (v1.7.2). Cloud + MCP counterpart to `clients/mcp_tool_chat.py` — deliberately a separate file, not a generalized `converse()`, so that already-tested/live-verified function stays untouched. `converse()` mirrors it exactly, sitting on `cloud_llm_client.chat_with_tools()` instead of Ollama's. `converse_stream()` (Cloud-only, no Ollama+MCP equivalent — see `clients/ollama_client.py`'s entry above) yields a sequence of small events instead of returning one dict: `{"type": "text", "text": ...}` per fragment of the turn in progress, `{"type": "tool_call", "name": ...}` once a turn's tool calls are known (before the next turn's own text begins), `{"type": "final", "messages": [...], "hit_max_turns": bool}` exactly once, last. `app/panel_chat.py` uses the `tool_call` event as the cue to end the current chat bubble and start a new one for the next turn. Provider-agnostic by construction — never imports a `cloud_llm_<provider>.py` module directly, only the dispatcher; `mcp_tools` passed through unmodified every turn, each provider module owns its own schema translation. Not live-verified against a real cloud provider; covered by `tests/test_cloud_tool_chat.py` with `cloud_llm_client` mocked. |
| `clients/chat_session_store.py` | Leaf-Node (v1.7.2). Chat session persistence under `<base_dir>/chats/` for `app/panel_chat.py`'s "Chat History" button (`app/dialog_chat_history.py` displays the list; this module owns every file access). One JSON file per conversation — bounded by `app/panel_chat.py`'s own "New Chat" boundary, every completed turn before the next one overwrites the same file (auto-save, no explicit "Save" action). Filename `chat_<timestamp>_<backend>_<datasource>.json`. `save_session()`/`load_session()`/`delete_session()`/`list_sessions()`/`is_resumable()`. `source_hash`: SHA-256 over the raw bytes of `dashboards/health_garmin.json` at save time (content hash, not mtime — an mtime can stay unchanged despite the content changing) — `None` for `mcp`-datasource sessions (always resumable, the data is live at query time) or if the file did not exist at save time. `is_resumable()`: `mcp` always `True`; `json` only if the current file hash still matches the stored one. Atomic writes (`.tmp` + `Path.replace()`). |
| `clients/cloud_credential_store.py` | Leaf-Node (v1.7.2). Cloud LLM API key storage via Windows Credential Manager, one entry per provider (`store_api_key()`/`get_api_key()`/`clear_api_key()`) — same `keyring` mechanism `garmin/garmin_security.py` already uses for the Garmin token encryption key (`get_enc_key()`/`store_enc_key()`), same plain "value in, value out" round-trip; no AES/PBKDF2 layer on top, since an API key is a short string, not a multi-field JSON blob. Deliberately a separate module from `garmin_security.py` (that module's own docstring: "No GUI logic. No direct calls to garmin_api or other project modules", and it lives in `garmin/`, the Sole-Write-Authority pipeline package for Garmin data specifically) — this lives in `clients/` instead, alongside the other external-tool/service integrations. Same `KEYRING_SERVICE` ("GarminLocalArchive") as `garmin_security.py`, distinct username per provider (`"cloud_llm_<provider>_api_key"`) so the two never collide. **Post-Baustein-23 fix (garmin_collector-3_experiment):** `_username()` now normalizes (strip + lower) the provider name before building the WCM username — closes a gap where `app/panel_mcp.py`/`clients/mcp_server_gui.py`'s own Save paths only `.strip()`, never `.lower()`, and both insert an unrecognized legacy provider value from `MCP_LLM_CONFIG_FILE` into their dropdown verbatim (pre-dropdown free-text data). Without this, a Save from that state stored the key under a differently-cased WCM username than `app/panel_chat.py`'s normalized read path ever queries — the key looked "missing" to the Chat tab immediately after being saved from the MCP tab. Fixed once at this module's own boundary rather than at each of the three call sites. |
| `app/dialog_chat_history.py` | `ChatHistoryDialog(QDialog)` (v1.7.2) — lists saved chat sessions (`app/panel_chat.py`'s "Chat History" button), Load/Delete. Reads/writes nothing itself — `sessions` handed in by the caller via `clients/chat_session_store.py::list_sessions()`; actually deleting a file is the caller's job too, once this dialog returns `("delete", path)`. Delete asks for confirmation (`QMessageBox.question`, same pattern as `panel_archive.py`'s/`panel_outputs.py`'s own destructive actions) before returning. Same rules as `app/dialogs.py`/`app/dialog_force_refetch.py`: no project-module imports besides PyQt6, no business logic beyond selection state, `app` instance passed as parent for theme colors. |
| `clients/mcp_server.py` | Standalone subprocess (v1.7 Teilbauauftrag b), streamable-http transport (`mcp>=1.28,<2`, v1.7.0.1 — replaces the earlier stdio transport), analogous to `scheduler/daily_update.py` — not an in-process thread off `garmin_app_base.py`. Registers `maps/mcp_map.py`'s original six functions as `@mcp.tool()`s, module-qualified calls to avoid name collision, plus a seventh (v1.7.1), `refresh_cache()`, which delegates directly to `clients/mcp_update.py::sync_all()` rather than to `mcp_map.py`. `FastMCP("Garmin Local Archive", host="127.0.0.1", port=cfg.MCP_HTTP_PORT)` — host is hardcoded, never configurable; only the port varies (`garmin_config.MCP_HTTP_PORT`). `sys.path` root anchor (`_SRC_ROOT`, `_GARMIN_DIR`; frozen case additionally registers `clients/` itself, v1.7 Teilbauauftrag f), not `frozen_paths.add_to_path()` — that helper is GUI-context-bound. Logging exclusively to stderr, plus a fixed-path boot log (`_setup_boot_log()`, next to `MCP_SERVER_CONFIG_FILE`, overwritten each run) attached before anything else; the operational log (`_start_operational_log()`, `LOG_MCP_MAX = 30`) lives here and is passed as a callable into `mcp_server_gui.py::run_gui()` (avoids a circular import) since both the windowed and headless paths need it. `main()` still opens the window by default (v1.7.0.1, session decision — the "the window is the server" coupling from Teil f is unchanged, only the transport is new) via `mcp_server_gui.py::run_gui()`; `garmin_config.MCP_HEADLESS` (a config field, not a CLI flag) instead routes to `_run_headless()`, which runs `mcp.run()` directly on this thread with no window at all, analogous to `scheduler/daily_update.py`. **(v1.7.1)** `main()` now calls `_run_startup_sync()` once, before the `MCP_HEADLESS` branch — runs `clients/mcp_update.py::sync_all()` synchronously and logs its result, so both startup paths perform the SQLite-proxy boot sync identically without the call being duplicated into `clients/mcp_server_gui.py`. Its own `import mcp_update` is a flat, absolute import (not `from . import mcp_update`) — this module is invoked as a standalone script, not imported as part of a package, so a relative import would raise `ImportError: attempted relative import with no known parent package`. No PID lockfile — `mcp.run()` raising `OSError` on an already-bound port is the natural "already running" signal, caught and logged instead of crashing (both paths); the same `socket.bind()` pattern additionally guards `sync_all()` itself against a second, parallel boot sync — see `clients/mcp_update.py` entry below. Build: T2 (`clients/Starte_MCP_Server.bat` launcher) and T3.3 (`mcp_server.exe`, `--onefile`, `windowed=False` left unchanged pending a real Windows build test — see `compiler/build_standalone.py`) both integrated as of Teilbauauftrag e/f. (v1.7.0.2) `FastMCP(...)`'s `transport_security` argument is `None` (SDK auto-default, unchanged) unless `garmin_config.MCP_EXTRA_ALLOWED_HOSTS_ENABLED` is set, in which case an explicit `TransportSecuritySettings` is built from the SDK's own three default hosts/origins plus `garmin_config.MCP_EXTRA_ALLOWED_HOSTS` — fixes reachability for MCP clients connecting via a non-localhost hostname (e.g. Open WebUI's Docker container via `host.docker.internal`), which the SDK's DNS-rebinding protection otherwise rejects outright. See `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` entry above. **(v1.7.1.1)** New `_route_query(kind) -> str` — an internal routing decision point all six query tools now call before delegating, placeholder today (always `"sqlite"`, `TODO v1.7.x` for a real cost/staleness heuristic). The `"sqlite"` branch calls the matching new `clients/mcp_sql.py` read function instead of the corresponding `maps/mcp_map.py` function; `query_fit_activities`/`list_available_fields` route through the same decision point but both branches currently call the identical `mcp_map.py` function (no `mcp_sql.get_fit_range()` until `fit_map.py` lands, v1.8; no cache benefit at all for a code-registry read in the latter case). `refresh_cache()` deliberately does not route — a sync trigger, not a data query. New flat `import mcp_sql`, same reasoning as the existing `import mcp_update`. **(v1.7.1.2)** `query_health()`'s `field` argument is now forwarded to `mcp_sql.get_health_range(date_from, date_to, field=field)` — previously silently dropped since `v1.7.1.1`, so the SQLite branch always returned every health field regardless of what was requested. **(v1.7.1.3)** `query_context()`'s `field` argument is now likewise forwarded to `mcp_sql.get_context_range(date_from, date_to, field=field)` — this was a distinct, longer-lived defect from `query_health()`'s: `get_context_range()`'s own signature never accepted a `field` argument at all until this fix, so `v1.7.1.1`'s partial `query_health()` fix never applied here in the first place. **Post-v1.7.2 fix (garmin_collector-3_experiment, Baustein 28):** `_register_embedded_packages()` now also adds the `scripts` root itself (not just `scripts/garmin`, `scripts/clients`, and the synthetic `maps` package) to `sys.path` in the frozen case. `frozen_paths.py`/`version.py`/`build_manifest.py`/`garmin_app_base.py` all live directly at that root; `clients/cloud_llm_client.py` (reached via `mcp_server_gui.py`'s `import cloud_llm_client`, the default non-headless branch) does `import frozen_paths` at module level, which raised `ModuleNotFoundError: No module named 'frozen_paths'` in a real T3.3 run before this fix — `garmin_app_standalone.py`'s own copy of this function had the identical gap, fixed the same way. **Note on Task Manager showing two `mcp_server.exe` processes:** expected `--onefile` PyInstaller behavior, not a bug — the bootloader process unpacks everything to a `sys._MEIPASS` temp folder and launches the real Python process from there as its own child; both share the same executable name. `clients/mcp_process.py::_kill_pid_tree()` (Baustein 29, see that module's own entry above) has to account for this — killing only the bootloader PID without `/T` would leave the real worker (and the port) still alive. |
| `clients/mcp_sql.py` *(v1.7.1, extended v1.7.1.1)* | Pure SQLite data-access layer for the aggregation proxy — schema, connection, typed read/write functions. Nine tables: `mcp_health_days`/`mcp_context_days`/`mcp_fit_days` (placeholder, stub pattern mirroring `gateway_map._DOMAIN_BROKERS['fit': None]`)/`mcp_day_status` for Form A (daily time series), `mcp_snapshots` for Form B (point-in-time archive metadata — `stats`/`device_table`/`token_log`/`capability_config`, always fully re-fetched, no delta concept), `mcp_structured_logs`/`mcp_recent_logs` for Form C (`quality_log`/`source_api_log` and the three raw-log directories), plus (v1.7.1.1) `mcp_raw_fields` (field-granular raw-passthrough cache, `recheck`/`attempts`/`last_attempt` columns — modelled on `garmin/quality/_maint.py`'s convention but deliberately reimplemented rather than imported, so `clients/` gains no dependency on `garmin/quality/`) and `mcp_raw_day_hashes` (one SHA-256 content hash per day, the change-detection signal `clients/mcp_update.py`'s raw-passthrough sync needs — content hash, not mtime, since a mirror/restore rewriting byte-identical bytes must not register as a change). `mcp_context_days` gained two additional columns in the same session, `complete_sources_json`/`attempted_sources_json`, tracking per-source completeness rather than a single existence flag. New read functions reassemble the day-keyed cache rows into the shapes `maps/mcp_map.py`'s own query functions return: `get_health_range()`/`get_context_range()`/`get_raw_range()` (time-series) and `get_metadata_range()` (routes internally between the `mcp_snapshots` and `mcp_structured_logs`/`mcp_recent_logs` read paths, mirroring `gateway_map._DATE_FILTERABLE_KINDS`'s own kind classification). **(v1.7.1.2)** `get_health_range()` gained a `field: str | None = None` parameter — when given, only that field is assembled, instead of every field the cached day payload holds (previously ignored entirely, since `mcp_server.py` never forwarded its own `field` argument — see that entry above). Also fixed the same session: each cached field's value carries an extra source-name layer (`{"garmin": {"values": ..., "fallback": ..., "source_resolution": ...}}`, mirrored unchanged from `health_map.get()`'s own result shape) that this function previously read straight through, missing "values"/"fallback"/"source_resolution" entirely since those live one level deeper — every field on every day silently produced an empty values list regardless of what the cache held, since the very first `v1.7.1.1` sync. Now reads through whichever single source is present rather than assuming the field's own keys directly, so this stays correct if a second source is ever added upstream. **(v1.7.1.3)** `get_context_range()` likewise gained a `field: str | None = None` parameter, filtering the `{source: {field: {...}}}` structure at the field level (not the source level) — a field name can be registered by more than one source simultaneously (e.g. `wind_speed_max` under both `weather` and `brightsky`, `context_map.py`'s documented naming collision), so filtering keeps every source carrying the requested field rather than collapsing a multi-source field down to one source. Previously this function's signature had no `field` parameter at all, a distinct and longer-lived gap than `get_health_range()`'s (which at least accepted `field` before `v1.7.1.2` fixed its handling) — `mcp_server.py`'s `query_context()` call site had nothing to forward it to even after `v1.7.1.1`. `field=None` preserves the pre-fix unfiltered behaviour. Single module-level, long-lived `sqlite3.Connection` (`check_same_thread=False`, `PRAGMA journal_mode=WAL`) — correct for the single-process model, since only `clients/mcp_server.py` ever opens this database. Every function raises on failure rather than degrading internally (unlike the `{"data":...,"error":...}` envelope used throughout `maps/`) — `clients/mcp_update.py` is responsible for catching and logging per-unit failures. Database file: `MCP_DB_PATH` above (`BASE_DIR/sqlite/mcp_cache.db`). Pure consumer per the Consumer Invariant (`KONZEPT_mcp_sqlite_proxy_V2.md`) — `garmin_backup.py`/`garmin_mirror.py` never reference this file. |
| `clients/mcp_update.py` *(v1.7.1, extended v1.7.1.1)* | Delta/sync logic — `sync_all()` is the single mechanism called both from `clients/mcp_server.py`'s boot sequence and from the `refresh_cache()` MCP tool (result only logged at boot; returned directly to the LLM as the tool's answer otherwise) — one mechanism, two callers, no second code path. Broker access exclusively through `maps/mcp_map.py` — never a direct import of `maps/gateway_map.py`/`maps/metadata_map.py`/any domain broker, and never direct filesystem access into `garmin_data/`/`context_data/`; the only crossing point between the `clients/` world and the broker layer is `mcp_map.py`, including for the three filename-only introspection functions (`list_daily_log_filenames`/`list_fail_log_filenames`/`list_recent_log_filenames`) that exist solely for this module's own sync bookkeeping. Health delta via `quality_log.json`'s `last_checked` **(v1.7.1.2, was `last_attempt`)** — `last_attempt` is written only on an actual recheck attempt, which never happened for any day in a healthy archive with no failed/rechecked entries, so the compare-value was `null` for every day and the sync silently synced nothing since `v1.7.1.0`; `last_checked` is written on every upsert (new day or recheck alike) and is therefore never null. The `quality_log`-kind branch of `_sync_structured_log()` below uses the same corrected field. `source_api_log` delta via `max(fetched_at, backfilled_fields values)`, not `fetched_at` alone (an additive backfill only updates the per-field `backfilled_fields` timestamp, never the entry's own `fetched_at`) — unaffected by this fix, already correct. Context delta (v1.7.1.1 rewrite) is now per-source completeness, not existence-only — a day with any of the four context sources still missing from its `complete_sources` set is revisited on the next sync; a source with one prior empty attempt gets exactly one more try, then is accepted as permanently empty (no unbounded retry — a context source either answers with data or with a definitive "nothing here", unlike raw/health's possible-later-availability case). New `_sync_raw_fields()`/`_sync_one_raw_field()` (v1.7.1.1) — field-granular, hash-gated delta for raw-passthrough: a day's cached content hash (`maps/metadata_map.py`'s `get_raw_file_hashes()`, via `mcp_map`) is compared against the freshly-read one; unchanged day → only currently-pending fields re-queried, changed or new day → every currently-registered raw field re-queried, which also covers nachtraegliche Datenlieferung (a GDPR bulk import or silo repair) to a day whose recheck window had already closed, without a separate manual-reset code path. New `RAW_RETRY_WINDOW_DAYS` module constant (v1.7.1.1) — deliberately independent from `garmin_quality.py`'s `GARMIN_INTRADAY_RETRY_WINDOW_DAYS` above, since raw-passthrough fields have no factual link to Garmin's own intraday-availability window. The three raw-log directories get a full filename diff on every sync rather than a delta tied to `mcp_health_days` — a log file's filename-encoded date is the sync timestamp, not necessarily the archived day it reports on. Concurrency: `sync_all(is_boot: bool = False)` **(v1.7.1.2, new parameter)** — a `socket.bind()` on `garmin_config.MCP_HTTP_PORT`, held for `sync_all()`'s duration, closes the gap between two parallel `mcp_server.py` boot syncs that would otherwise both start before either process's own `mcp.run()` bind guard could catch it, but now runs only when `is_boot=True`. Previously ran unconditionally on every call including from `refresh_cache()` — by the time that tool can be called at all, `mcp.run()` already legitimately holds the port, so the guard's own bind attempt always failed, making `refresh_cache()` unconditionally error out at runtime (confirmed in live logs, `[WinError 10048]` on every post-boot call). A plain `threading.Lock` (analogous to `garmin_quality.py`'s `QUALITY_LOCK`) serializes overlapping `refresh_cache()` calls after boot — this guard is unaffected by the `is_boot` change and remains identical for both callers. Result dict reports both `*_updated` and `*_failed` counts per data category (v1.7.1.1 additionally: `raw_days_touched`/`raw_fields_failed`) — see `AUDIT_FINDINGS_v1_7_1.md` F-2. Own `import mcp_sql` is a flat, absolute import for the same reason as `mcp_server.py`'s `import mcp_update` — this module is itself loaded via that flat import, so it carries no package context at import time. |
| `clients/mcp_field_registry.py` | Pure-data module (v1.7.2.1, split out of `mcp_server.py` — Codereview Baustein 2.1, extended Baustein 2.2). `FIELD_UNITS`/`HEALTH_FIELD_ALIASES`/`HEALTH_FIELD_AMBIGUOUS`/`CONTEXT_FIELD_ALIASES`/`CONTEXT_FIELD_AMBIGUOUS`/`_CONTEXT_CATEGORY_BUNDLES` — no logic, only data, imported by `mcp_query_common.py`/`mcp_health.py`/`mcp_context.py` below. |
| `clients/mcp_query_common.py` | Shared query-serving helpers (v1.7.2.1, split out of `mcp_server.py`). `_route_query(kind)`, `_get_field_unit(field)`, `_enrich_with_units(result, domain)` — fully self-contained, no `mcp`/`mcp_sql`/`mcp_map` dependency, so both `mcp_server.py`'s own four remaining tools and `mcp_health.py`/`mcp_context.py` below can import it without a circular import. |
| `clients/mcp_health.py` | `query_health(field, date_from, date_to, resolution="daily")` (v1.7.2.1, split out of `mcp_server.py`) — the routing/alias/fuzzy-match logic that function had grown, moved verbatim. Registered back onto `mcp_server.mcp` programmatically (`mcp.tool()(query_health)`), not via `@mcp.tool()` at the definition site, to avoid importing `mcp` back from `mcp_server.py`. See `REFERENCE_MCP.md`'s `(v1.7.2.1)` entry. |
| `clients/mcp_context.py` | `_resolve_context_bundle()`, `_fetch_context_field()`, `query_context(field, date_from, date_to, resolution="daily")` (v1.7.2.1, split out of `mcp_server.py`), same programmatic-registration pattern as `mcp_health.py` above. See `REFERENCE_MCP.md`'s `(v1.7.2.1)` entry. |
| `clients/mcp_server_gui.py` | Standalone Tkinter window (v1.7 Teilbauauftrag f) — "the window is the server," coupling unchanged in v1.7.0.1 (window closed = process closed), opened by default by `mcp_server.py::main()` unless `garmin_config.MCP_HEADLESS` is set. `run_gui(mcp_instance, logger, boot_handler, start_operational_log)` starts `mcp_instance.run(transport="streamable-http")` — v1.7.0.1, was `"stdio"` — in a `daemon=True` thread before building the window, then blocks in `root.mainloop()` on the main thread; a bind failure (`OSError`) in that thread is caught and surfaced via a status label + warning dialog shortly after the window appears, rather than crashing silently. `start_operational_log` is passed in from `mcp_server.py` (not imported) to avoid a circular import, since that module already imports this one to call `run_gui()`. Reads/writes `garmin_config.MCP_SERVER_CONFIG_FILE` directly (second writer alongside `panel_mcp.py`'s mirror — see that file's docstring for the documented Sole-Write-Authority exception; `mcp_http_port`/`mcp_headless` replace `mcp_ollama_model` as the fourth/fifth mirrored fields — see below) and `garmin_config.MCP_LLM_CONFIG_FILE` (cloud provider/model, same read-merge-write shape as `panel_mcp.py::_mcp_save_cloud_config()` — **(v1.7.2)** the API key itself goes to Windows Credential Manager instead, via `clients/cloud_credential_store.py`, same as `panel_mcp.py`'s own Provider-dropdown + WCM change, see that entry above). Config fields: LLM backend, archive path, Port, Headless checkbox (v1.7.0.1, new — takes effect on the *next* start, not this running instance), or cloud credentials depending on backend — the Ollama model dropdown and its "Refresh" button are gone (v1.7.0.1, along with `garmin_config.MCP_OLLAMA_MODEL`). Log widget unchanged in shape from v1.7 — `_QueueLogHandler` + `root.after(100, ...)` poll loop, now receiving both this window's own log lines and the server's, since both run in this process again. "🔄 Restart Server" button (v1.7.0.1, replacing the v1.7 Teilbauauftrag h button of the same intent) — `_resolve_mcp_server_launch_command()` (shortened, standalone copy of `app/panel_mcp.py`'s function of the same name — `clients/` does not import from `app/`) resolves the T1/T2/T3.3 launch target, launches it via `subprocess.Popen` with the *saved* settings (Save first, then Restart — same two-step as before), then `_poll_reachable()` (`root.after(500, ...)`, 12s timeout) checks `_is_server_reachable()` — a real TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` — instead of polling a PID lockfile for a changed value. On success calls `root.destroy()`, which ends this process (and the old server's daemon thread with it) — the v1.7 Teilbauauftrag h **known limitation** (poll only confirmed a new PID, not real health) is resolved by construction here: a TCP accept only happens once `mcp.run()` has actually bound and is serving. On timeout the old server is left running and the button re-enables. (v1.7.0.2) Same "Extra allowed hosts" checkbox/field/preview as `app/panel_mcp.py`, backing the same `garmin_config` constants; also gained a `"🦄  GARMIN LOCAL ARCHIVE"` header label (text/font only, matching `garmin_app_base.py`'s branding — no color-theme or icon changes, deliberately out of scope this session). The Headless checkbox's German label was translated to English alongside `panel_mcp.py`'s. |
| `garmin_app_base.py` | View layer (`GarminApp`) — PyQt6 `QMainWindow`, fixed top (`panel_home`) + `QTabWidget`: Home / Files / Settings / Chat / MCP Server (v1.6.0+, fourth tab added v1.6.6 as "Ollama-Chat", renamed "Chat" v1.7.2, fifth tab added v1.7 Teilbauauftrag d). Settings tab: two-column layout — Settings left (340px), Actions right (flex). `_sheet_arrow` label mirrors `_sheet_combo` visibility (v1.6.0.7). |
| `qwebengine_hardening.py` | Leaf-Node. `harden(view)` — disables `LocalContentCanAccessFileUrls`, `LocalContentCanAccessRemoteUrls`, `JavascriptCanOpenWindows`, `PluginsEnabled`, `JavascriptCanAccessClipboard` on a `QWebEngineView`. `JavascriptEnabled` stays `True` — Plotly dashboards require it. Idempotent — safe to call multiple times on the same view. Called from `panel_home.py` and `garmin_app_base.py` after each `QWebEngineView()` instantiation. |
| `frozen_paths.py` | Leaf-Node. Central frozen-path resolution — replaces previously duplicated `sys.frozen`/`sys._MEIPASS`/`sys.executable` branches (`panel_outputs.py` ×6, `panel_home.py`, the `garmin_live_fetch` call site, doc lookups). Three side-effect-separated functions: `scripts_root()` (root for `garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/` — T3 verified via canonical distinguisher: `dash_runner.py` must actually exist under `scripts/dashboards/`, not just `scripts/` itself), `add_to_path(root, *subs)` (mutates `sys.path` as an explicit, separate step), `doc_path(filename)` (finds bundled docs — `info/` next to the EXE when frozen, three-step dev chain otherwise: repo root → `src/docs/` → `src/scheduler/`; returns `None` if not found, never guesses). |
| `log_utils.py` | Leaf-Node (v1.6.6.1). One function: `with_timestamp(log_fn)` — wraps a log callback so every message gets a `"%Y-%m-%d %H:%M:%S "` prefix, matching the format `logging.Formatter` uses elsewhere in the project. Pass-through — returns `None` unchanged if `log_fn` is `None`. Deliberately not placed in `garmin/garmin_utils.py` despite that module's own Leaf-Node status — `dashboards/` has zero project-module imports by design, kept independent of `garmin/`; `log_utils.py` sits at the `src/` root instead, alongside `frozen_paths.py`, so `context/context_collector.py` and `dashboards/dash_runner.py` can both import it without creating a cross-domain dependency. Used to fix inconsistent console-log timestamps between the Garmin page (`logging` module) and the Context/Dashboard pipeline (`log_callback(str)`). |
| `theme.py` | Single source of truth for all app/dashboard color tokens (v_theme_01). Five built-in themes (`_THEMES` dict), active one read from settings (`active_theme` key, GUI dropdown in Settings tab, v1.7.1.8). Falls back to Theme 1 if the key is missing or invalid. See `REFERENCE_INVARIANTEN.md` → Dashboards / Layouts for the `theme.py` → `garmin_app_settings` coupling this creates in `dash_layout.py` and `layouts/render/live.py` — both import `theme` directly, the only break in `layouts/`'s otherwise strict independence from `app/`. |

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
│   │   └── summary/                 ← daily aggregate — weather has no raw/ (no intraday API data)
│   │       └── weather_YYYY-MM-DD.json
│   ├── pollen/
│   │   ├── summary/                 ← daily aggregate (v1.7.1.11 — renamed from raw/)
│   │   │   └── pollen_YYYY-MM-DD.json
│   │   └── raw/                     ← hourly, timestamped (v1.7.1.11)
│   │       └── pollen_YYYY-MM-DD.json
│   ├── brightsky/
│   │   ├── summary/                 ← daily aggregate (v1.7.1.11 — renamed from raw/)
│   │   │   └── brightsky_YYYY-MM-DD.json
│   │   └── raw/                     ← hourly, timestamped (v1.7.1.11)
│   │       └── brightsky_YYYY-MM-DD.json
│   └── airquality/
│       ├── summary/                 ← daily aggregate (v1.7.1.11 — renamed from raw/)
│       │   └── airquality_YYYY-MM-DD.json
│       └── raw/                     ← hourly, timestamped (v1.7.1.11)
│           └── airquality_YYYY-MM-DD.json
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

**Post-v1.7.2 (garmin_collector-3_experiment, Bausteine 27/31/32/33):** both `compiler/build.py`'s and `compiler/build_standalone.py`'s `build_exe()` now invoke PyInstaller from a shared, isolated venv (`compiler/build_manifest.py::BUILD_VENV_DIR`, `D:\Garmin\.venv_gla`) instead of `sys.executable` — `ensure_build_venv()` creates it on first use, installs `requirements.txt` + PyInstaller into it, and reuses it afterwards. Prevents a package installed globally for a different project on the same build machine from being swept into a GLA build (root cause of a >8 GB T3 ZIP, see `CHANGELOG.md`). New `compiler/build_gui.py` ("🦄 Garmin Local Archiv Builder", `bat/run_build_gui.bat`) wraps the manual "copy working dir into a build folder, then run `build_all.py`" workflow into one Tkinter window with a live, elapsed-time-stamped log — not a new build target, just a GUI front end for the existing `build_all.py` sequence (Qt-test gate + `build_all.py`, unchanged). Verified end-to-end on a real Windows build.
