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
| `MCP_SERVER_CONFIG_FILE` | `~/.garmin_mcp_server_config.json` | Three fields: `mcp_llm_backend`, `base_dir`, `mcp_ollama_model` — enables `clients/mcp_server.py` to run fully standalone, without a GLA installation (v1.7 Teilbauauftrag f). A fourth field, `mcp_enabled`, existed through Teil (f) but was removed in Teil (g) — the "Enable MCP server" checkbox it backed had no functional effect once `main()` stopped gating on it (Teil f), and the Teil (g) "Start MCP Server" button made the whole on/off concept moot. Old files on disk may still carry a stale `mcp_enabled` key — harmless, simply ignored. Two documented writers (deliberate Sole-Write-Authority exception — mutually exclusive operating modes, never run concurrently against the file): `app/panel_mcp.py::_mcp_save_server_config()` (mirrors GLA's live values on every MCP settings save) and `clients/mcp_server_gui.py` (direct standalone-window input, merge-on-write). |
| `MCP_BASE_DIR` | `BASE_DIR`'s value, or the `MCP_SERVER_CONFIG_FILE` `base_dir` field | Server-owned archive path (v1.7 Teilbauauftrag f) — deliberately a separate constant from `BASE_DIR`, not an alias. Same `GARMIN_OUTPUT_DIR` ENV as `BASE_DIR` (shared, not a new ENV name) takes precedence if set; otherwise falls back to the config file, then to `~/local_archive`. `BASE_DIR` itself is unchanged by this — the pipeline's archive-path resolution was not touched. |
| `MCP_OLLAMA_MODEL` | *(none)* | Ollama model preference (v1.7 Teilbauauftrag f) — file-only, deliberately no ENV override (pure convenience default, not an automation/deployment value like the three fields above). Populated by the "Refresh" button in both `app/panel_mcp.py` and `clients/mcp_server_gui.py`. |
| `MCP_SERVER_LOCK_FILE` | `~/.garmin_mcp_server.lock` | PID lockfile (v1.7 Teilbauauftrag g). Plain text, single value (the process PID). Written by `clients/mcp_server.py::main()` at startup — this happens before `base_dir` is checked, so the PID is written even if the archive path is later found unreachable (v1.7 Teilbauauftrag h, see below). Removed by two paths: `clients/mcp_server_gui.py`'s clean-shutdown path (`_on_close()`) — in practice a normal window close reliably triggers a `Fatal Python error` during interpreter shutdown (the `mcp.run(transport="stdio")` daemon thread's blocking stdin read cannot be cleanly interrupted), so the file staying present after a "clean" close is the expected common case, not an edge case; and the Restart button's `_on_restart()` (v1.7 Teilbauauftrag h), which attempts the same unlink *before* launching the replacement process, deliberately not waiting for confirmation it succeeded (same fail-open reasoning as `_on_close()`). Read by `app/panel_mcp.py::_mcp_server_is_running()` — `tasklist`-based liveness check (stdlib only, no `psutil`) before the "Start MCP Server" button launches a new process; a present-but-dead PID is treated as "not running", not an error. Also read by `mcp_server_gui.py`'s Restart poll cycle (v1.7 Teilbauauftrag h) — polls every 500ms for a PID different from the current process's own, 12s timeout; a new PID appearing is treated as "new process started", not as confirmation the new process is fully healthy (known limitation, see `clients/mcp_server_gui.py` entry below). Deliberately not a `QLocalServer`/`QLocalSocket` guard (unlike `garmin_app.py`'s single-instance guard) — that mechanism requires a running `QApplication`, which `mcp_server.py`/`mcp_server_gui.py` intentionally lacks (Tkinter, not PyQt6). |

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
    │                                  writes SETTINGS_FILE, no os.environ write). "Start MCP Server"
    │                                  button (v1.7 Teilbauauftrag g) launches clients/mcp_server.py
    │                                  directly — build-context-aware launch command
    │                                  (_resolve_mcp_server_launch_command()): T1 = sys.executable +
    │                                  script path, T2 = clients/Starte_MCP_Server.bat next to the
    │                                  frozen EXE, T3.3 = mcp_server.exe next to the frozen EXE (plain
    │                                  existence check disambiguates T2/T3.3, no stored marker). PID
    │                                  liveness check (_mcp_server_is_running(), stdlib tasklist parsing,
    │                                  no psutil) reads garmin_config.MCP_SERVER_LOCK_FILE before
    │                                  starting — blocks with a warning dialog if a live PID is found; a
    │                                  present-but-stale lock file (the common case after a normal
    │                                  mcp_server_gui.py window close, see that module's docstring on
    │                                  its interpreter-shutdown crash) is treated as "not running", not
    │                                  an error. The former "Enable MCP server" checkbox and its status
    │                                  row were removed in Teil (g) — both had become functionally
    │                                  inert once main() stopped gating on the flag (Teil f) and the
    │                                  Start button replaced the manual-start workflow they described.
    │                                  Ollama model list refreshed live via clients/ollama_client.py
    │                                  (same lazy-import pattern as panel_chat.py); model selection
    │                                  persisted (v1.7 Teilbauauftrag f — get_mcp_settings()/
    │                                  load_mcp_settings() carry mcp_ollama_model). Cloud backend has
    │                                  its own credentials block (provider/API key/model) that reads and
    │                                  writes garmin_config.MCP_LLM_CONFIG_FILE directly — first and
    │                                  only GLA-side writer of that file (clients/mcp_server_gui.py is a
    │                                  second, standalone-context writer, v1.7 Teilbauauftrag f). API
    │                                  key is never reloaded into the widget after a save (write-only
    │                                  field). _mcp_save() additionally mirrors mcp_llm_backend/
    │                                  base_dir/mcp_ollama_model into garmin_config.
    │                                  MCP_SERVER_CONFIG_FILE on every save (v1.7 Teilbauauftrag f,
    │                                  field reduced from four to three in Teil g) — lets a standalone
    │                                  mcp_server.exe discover these without a running GLA instance.
    │                                  Write failure there is logged only, not a blocking dialog.
    │                                  Wrapped in a QScrollArea at the garmin_app_base.py tab-embedding
    │                                  site (unlike panel_chat.py) — holds more stacked content than
    │                                  fits at low window heights.
    │
    ├── clients/                    ← External tool/service clients (v1.6.6) — no data silo, no
    │   │                              Sole-Write-Authority, distinct from garmin/'s pipeline scope.
    │   │                              Flat imports like garmin/, app/ — no sys.modules package
    │   │                              registration (no relative imports inside clients/)
    │   ├── __init__.py
    │   ├── ollama_client.py        ← Leaf-Node. Wraps Ollama HTTP API (localhost:11434),
    │   │                              non-streaming POST /api/chat. See Module reference
    │   │                              table below.
    │   ├── mcp_server.py           ← Standalone MCP server process, stdio transport (v1.7
    │   │                              Teilbauauftrag b). Registers maps/mcp_map.py's six
    │   │                              functions as MCP tools. Own sys.path root anchor
    │   │                              (not frozen_paths.add_to_path() — that pattern is
    │   │                              GUI-context-bound, this is a standalone subprocess;
    │   │                              extended v1.7 Teilbauauftrag f to also register
    │   │                              clients/ itself in the frozen/T3.3 case, for the
    │   │                              mcp_server_gui import below). main() always opens the
    │   │                              Tkinter window unconditionally — no enabled/disabled
    │   │                              gate exists (removed Teil f, the underlying
    │   │                              garmin_config.MCP_ENABLED constant itself removed
    │   │                              Teil g once the Start MCP Server button replaced the
    │   │                              flag's manual-start use case). A boot log
    │   │                              (_setup_boot_log(), fixed path next to
    │   │                              MCP_SERVER_CONFIG_FILE) captures anything before the
    │   │                              window/operational log is up. Writes its own PID to
    │   │                              garmin_config.MCP_SERVER_LOCK_FILE at startup (v1.7
    │   │                              Teilbauauftrag g) — read by app/panel_mcp.py's Start
    │   │                              button liveness check. See Module reference table
    │   │                              below.
    │   └── mcp_server_gui.py       ← Standalone Tkinter window — "the window is the server"
    │                                  (v1.7 Teilbauauftrag f). Opened unconditionally by
    │                                  mcp_server.py::main(); starts mcp.run(transport="stdio")
    │                                  in a daemon thread (Tkinter's mainloop() is main-
    │                                  thread-bound). Config fields (LLM backend, archive
    │                                  path, Ollama model or cloud credentials depending on
    │                                  backend), Simple/Detailed log toggle, queue-based log
    │                                  widget (new implementation — no prior Tkinter
    │                                  precedent in the project; ported from
    │                                  garmin_app_standalone.py's PyQt6 queue pattern). See
    │                                  Module reference table below.
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
| `app/panel_mcp.py` | `PanelMcp(QWidget)` — MCP server settings panel (v1.7 Teilbauauftrag d), fifth tab ("MCP Server"). `get_mcp_settings()`/`load_mcp_settings(s)` pair analogous to `panel_timer.py`'s, fused into `garmin_app_base.py::_collect_settings()` — now four fields incl. `mcp_ollama_model` (v1.7 Teilbauauftrag f). No `os.environ` write, no subprocess start/stop for `clients/mcp_server.py` — the Teil b/c architecture decision (GUI-decoupled standalone subprocess) means no such bridge exists. `_mcp_save()` additionally mirrors all four MCP fields into `garmin_config.MCP_SERVER_CONFIG_FILE` on every save (v1.7 Teilbauauftrag f, `_mcp_save_server_config()`) — lets a standalone `mcp_server.exe` discover them without a running GLA instance; write failure is logged only, not a blocking dialog. Ollama model list refreshed on-demand (Refresh button) via the same `_load_ollama_client()` lazy-import pattern as `panel_chat.py`. Cloud backend credentials (provider/API key/model) read and write `garmin_config.MCP_LLM_CONFIG_FILE` directly — first and only GLA-side writer of that file (`clients/mcp_server_gui.py` is a second, standalone-context writer with the same read-merge-write shape, v1.7 Teilbauauftrag f); API key field is write-only (never reloaded after save). Embedded in a `QScrollArea` at the tab site in `garmin_app_base.py` — holds more stacked content than reliably fits at low window heights. |
| `clients/ollama_client.py` | Leaf-Node (v1.6.6). Wraps the local Ollama HTTP API (`http://localhost:11434`) — `GET /api/tags`, non-streaming `POST /api/chat`. Typed exceptions per failure mode (`OllamaUnreachable`, `OllamaTimeout`, `OllamaModelNotFound`, `OllamaContextLimitExceeded`, generic `OllamaError`). No project-internal imports beyond stdlib/`requests`. Used by `app/panel_chat.py`, `app/panel_mcp.py`'s Ollama-model-refresh, and (v1.7 Teilbauauftrag f) `clients/mcp_server_gui.py`'s own Ollama-model-refresh. |
| `clients/mcp_server.py` | Standalone subprocess (v1.7 Teilbauauftrag b), stdio transport (`mcp>=1.28,<2`), analogous to `scheduler/daily_update.py` — not an in-process thread off `garmin_app_base.py`. Registers `maps/mcp_map.py`'s six functions as `@mcp.tool()`s, module-qualified calls to avoid name collision. `sys.path` root anchor (`_SRC_ROOT`, `_GARMIN_DIR`; frozen case additionally registers `clients/` itself, v1.7 Teilbauauftrag f), not `frozen_paths.add_to_path()` — that helper is GUI-context-bound. Logging exclusively to stderr (stdout is the stdio protocol channel), plus a fixed-path boot log (`_setup_boot_log()`, next to `MCP_SERVER_CONFIG_FILE`, overwritten each run) attached before anything else. `main()` no longer checks `garmin_config.MCP_ENABLED` (v1.7 Teilbauauftrag f, superseding the Teil c gate) — always calls `clients/mcp_server_gui.py::run_gui()` unconditionally; the window IS the server, no headless/console mode remains. Build: T2 (`clients/Starte_MCP_Server.bat` launcher) and T3.3 (`mcp_server.exe`, `--onefile`, `windowed=False` — `mcp.run(transport="stdio")` needs real console `sys.stdin`/`sys.stdout`, verified via a real build test after `windowed=True` failed with `'NoneType' object has no attribute 'buffer'`) both integrated as of Teilbauauftrag e/f. |
| `clients/mcp_server_gui.py` | Standalone Tkinter window (v1.7 Teilbauauftrag f) — "the window is the server," opened unconditionally by `mcp_server.py::main()`, blocks in `root.mainloop()` on the main thread. Starts `mcp.run(transport="stdio")` in a `daemon=True` thread — no cancel handshake (none exists on `mcp.run()`, none needed: a stdio responder holds no transactional state, the daemon thread dies with the process). Reads/writes `garmin_config.MCP_SERVER_CONFIG_FILE` directly (second writer alongside `panel_mcp.py`'s mirror — see that file's docstring for the documented Sole-Write-Authority exception) and `garmin_config.MCP_LLM_CONFIG_FILE` (cloud credentials, same read-merge-write shape as `panel_mcp.py::_mcp_save_cloud_config()`). Operational log (`<base_dir>/garmin_data/log/mcp/`, rotating, `LOG_MCP_MAX = 30`, same pattern as `daily_update.py::_start_daily_log()`) replaces the boot log once `base_dir` is confirmed reachable — boot handler removed from the root logger at that point, no permanent duplication. Log widget: `_QueueLogHandler` (new `logging.Handler` subclass, this module's own) + `root.after(100, ...)` poll loop — architectural port of `garmin_app_standalone.py`'s PyQt6 `_QueueWriter`/`_QueueHandler`/`_poll_log_queue` trio, no prior Tkinter implementation existed in the project. Simple/Detailed toggle (same wording as `app/panel_settings.py`) sets `logging.getLogger().setLevel(...)` globally — file handlers always stay at DEBUG regardless. "🔄 Restart Server" button (v1.7 Teilbauauftrag h) — Self-Relaunch with a transitional window state (Option C, session decision): `_resolve_mcp_server_launch_command()` (shortened, standalone copy of `app/panel_mcp.py`'s function of the same name — `clients/` does not import from `app/`) resolves the T1/T2/T3.3 launch target; on confirmation the old process's lock file unlink is attempted first, then the new process is started via `subprocess.Popen`, then `root.after(500, ...)` polls `MCP_SERVER_LOCK_FILE` every 500ms (12s timeout) for a PID different from the current process's own. On a new PID appearing, this window calls `root.destroy()` — the known interpreter-shutdown crash (`_enter_buffered_busy`) still occurs at that point but is no longer user-visible as a blank screen, since the new window is already up. **Known limitation** (v1.7 Teilbauauftrag h, real-tested): the poll cycle only confirms a new PID was written, not that the new process is fully healthy — `_write_lock_file()` in `mcp_server.py::main()` runs before `base_dir` is validated, so a restart with an invalid `base_dir` still reports success (new process falls back to the boot log with a warning, `mcp.run()` itself still starts). Documented, not fixed — a real health check (e.g. verifying the stdio handshake) is out of scope for Teilbauauftrag h. |
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
