# Garmin Local Archive — Changelog

## v1.7.0.4 — Metadata Date-Range Filtering

Fixes `get_archive_metadata` blowing past cloud-LLM token budgets when queried through Open WebUI over MCP. Real `mcp-proxy` logs showed `get_archive_metadata(kind="quality_log")` returning an unfiltered 2.8 MB dump on every single call (~2800 archive days, one entry per day since archive start) — enough to exhaust an 8k–12k TPM budget on Groq/Gemini's free tier in one request, independent of which LLM was asked. Traced through the full call chain (`mcp_server.py` → `mcp_map.py` → `gateway_map.py` → `metadata_map.py`) rather than assumed — the initially suspected fix, the planned v1.7.1 SQLite aggregation proxy, does not apply here: that proxy sits in front of `gateway_map.get()` (health/context time-series queries), while `get_archive_metadata` runs through the entirely separate `gateway_map.get_metadata()` path, which has no time-series/resolution concept to aggregate over.

**Date-range filtering:**
- `maps/metadata_map.py`: five of the nine introspection functions (`get_quality_log`, `get_source_api_log`, `get_daily_logs`, `get_fail_logs`, `get_recent_logs`) gained optional `date_from`/`date_to` (ISO `YYYY-MM-DD`, inclusive). `get_stats`, `get_device_table`, `get_capability_config`, `get_token_log` deliberately untouched — already small/bounded, do not grow with archive length. `get_quality_log`/`get_source_api_log` filter by JSON date-keys; the three log-directory functions filter by *filename* date (`{prefix}_YYYY-MM-DD_HHMMSS.log`, session-per-file model), never by scanning line-by-line inside a file. New `_LOG_FILENAME_DATE_RE` regex anchors on the digit pattern itself, not on a fixed underscore-segment count — real archive filenames include prefixes that themselves contain underscores (`garmin_background_`, `test_connection_`), which a naive first-underscore split would have misparsed.
- Neither given: defaults to the last 30 days, anchored on the latest date actually present in the data (not on today's calendar date, so a slightly stale archive still returns something useful) — plus a `"note"` field in the response explaining the default was applied. Never an error, never the old unfiltered dump.
- No `resolution` parameter and no `mcp_map.py`-style `"_meta"` weekday block added — this is a plain range filter over an already date-indexed collection, not a time-series query; kept structurally distinct from `query_health`/`query_context`'s contract on purpose.
- `maps/gateway_map.py`: `get_metadata()` gained the same optional `date_from`/`date_to`, forwarded only for the five filterable kinds (new `_DATE_FILTERABLE_KINDS` set) — the other four kinds silently ignore the arguments rather than raising, so a caller does not need to know in advance which kinds support filtering.
- `maps/mcp_map.py` / `clients/mcp_server.py`: `get_archive_metadata()` forwards the two new parameters end-to-end; the MCP tool's docstring now also steers the LLM toward `"stats"` for "how big/healthy is my archive" questions instead of `"quality_log"`, which even filtered to a range remains the wrong tool for an overview question.

**Cleanup:**
- `maps/metadata_map.py::_read_log_dir()` removed — had no remaining callers once `get_daily_logs`/`get_fail_logs`/`get_recent_logs` were rewired onto a new shared `_read_filtered_log_dir()` helper (filter + read + sanitize in one place instead of duplicated three times). Removed rather than left as dead code (Cluster D principle).

**Deliberately not implemented:**
- `mcp/`, `mcp_proxy/` log directories NOT added to `metadata_map.py` — these belong to `support-tools/mcp-call-logger/mcp_call_logger.py`, a standalone diagnostic tool alongside GLA, not part of its broker chain. Briefly considered and reversed mid-session once the tool's actual ownership was clarified.
- SQLite aggregation proxy (v1.7.1) — separate, still-planned work; does not apply to this fix (see above).
- `list_available_fields()` payload reduction (`maps/mcp_map.py`) — the second-largest contributor to the original token-budget problem (2186 bytes, called on nearly every chat start per the real proxy logs), scoped out as its own follow-up session; different module, different data flow, own test implications.

**Precondition Teil B (Drift-Check):** PFLICHT this session — `maps/metadata_map.py`, `maps/gateway_map.py`, `maps/mcp_map.py` changed. Confirmed via `dep_map_delta.md` (`build_dep_map.py`, 2026-08-25_Run-02 → 2026-08-27_Run-01): 12 NEU / 1 WEG exceptions, 15 NEU / 3 WEG fileio, 0 GEKIPPT-Regression — clean. The four WEG entries are exactly `_read_log_dir()`'s removal (expected). Two `critical`-flagged entries outside this session's scope reviewed on request: `support-tools/mcp-call-logger/mcp_call_logger.py` is a standalone tool alongside GLA, not evaluated further; `clients/mcp_server.py :: <module>`'s `(FileNotFoundError, ValueError)` handler predates this session (v1.7.0.3's `GARMIN_OUTPUT_DIR` bootstrap fix) and degrades to an already-documented, already-safe fallback — assessed as an existing, acceptable pattern, not a regression.

**Test result:** 716 / 265 / 465 / 123 / 65 / 165 / 73 / 16 — all green (test_local / test_local_context / test_dashboard / test_broker / test_mcp / test_app_logic / test_qt_app / test_static), Total 1888 (`docs/METRICS.md`).
---

## v1.7.0.3 — MCP Server Archive-Path Fix

Fixes silently wrong archive-data reads in the standalone MCP server — `clients/mcp_server.py` resolved `garmin_config.BASE_DIR` (and everything derived from it: `LOG_DIR`, `RAW_DIR`, `SUMMARY_DIR`, `CONTEXT_DIR`) to its hardcoded default (`~/local_archive`) instead of the configured archive path, because `GARMIN_OUTPUT_DIR` was never set before `garmin_config` was imported when running standalone (no GLA process ahead of it to set that ENV var). `garmin_config.MCP_BASE_DIR` — used only for this module's own operational-log path and the GUI's Archive-path display — resolved correctly from the same config file the whole time, producing a silent divergence between what the server showed and what it actually read. First surfaced through a real Open WebUI session: `device_table` queries failed outright (`[Errno 2] No such file or directory` against the wrong path), while health/context queries degraded quietly to `null`/empty values instead of erroring.

**Fix:**
- `clients/mcp_server.py`: new ENV setup block, placed before `import garmin_config as cfg` — reads `MCP_SERVER_CONFIG_FILE` (`~/.garmin_mcp_server_config.json`) directly and sets `os.environ["GARMIN_OUTPUT_DIR"]` from its `base_dir` field if the ENV var is not already set. Mirrors the same caching-at-import-time workaround `scheduler/daily_update.py` already documents and applies at its own Schritt 3. `import os` added (was missing from this module entirely). Single eight-line duplication of `garmin_config._read_mcp_server_config()`'s fallback shape — unavoidable, since `garmin_config` is not importable yet at the point this code runs.
- No other module changed — `garmin_config.py`, `clients/mcp_server_gui.py`, `maps/metadata_map.py`, `maps/health_map.py`, `maps/context_map.py`, `maps/garmin_health_map.py`, `maps/weather_map.py`, `maps/pollen_map.py`, `maps/brightsky_map.py`, `maps/airquality_map.py` were all confirmed as downstream consumers of `BASE_DIR` (nine files, `DEPS_CRITICAL_v1703_01.md`) but the root cause was isolated entirely to `mcp_server.py`'s import-order — fixing it there resolves all nine transitively, with zero changes to the broker chain.
- `_run_headless()` path explicitly checked: `cfg.MCP_HEADLESS` is read only after `garmin_config` is already fully imported, so both the headless and windowed startup paths share the identical bootstrap sequence — one fix location covers both. The `subprocess.Popen`-based Restart button (`clients/mcp_server_gui.py::_on_restart()`) always launches a fresh process through the same `main()` entry point — no in-process reload path exists that could bypass this fix.

**Verified live:** after applying the fix and restarting the server, `get_archive_metadata`, `query_health`, and `query_context` all returned correct, plausible values through Open WebUI (qwen3:14b) against the real `D:/Garmin_Data` archive — all three previously affected tool categories confirmed working.

**Deliberately not implemented:**
- Unifying `BASE_DIR` and `MCP_BASE_DIR` in `garmin_config.py` (e.g. extending `BASE_DIR`'s own fallback to read `MCP_SERVER_CONFIG_FILE`) — considered as an alternative, but would have weakened the deliberately documented separation ("`BASE_DIR` remains the pipeline's sole archive-path source") for no added benefit over the chosen ENV-before-import fix. Left as a possible future architecture discussion, not a bug.

**Precondition Teil B (Drift-Check):** not run this session — scope was an isolated bootstrap-order fix in a single file, no architecture change.

**Test result:** 716 / 265 / 465 / 107 / 64 / 165 / 73 / 16 — all green (test_local / test_local_context / test_dashboard / test_broker / test_mcp / test_app_logic / test_qt_app / test_static), Total 1871 (`docs/METRICS.md`).

---

## v1.7.0.2 — MCP Transport Security (Docker Reachability)

Fixes MCP server reachability for MCP clients running inside Docker (e.g. Open WebUI's own container connecting via `host.docker.internal`) — the `mcp` Python SDK's built-in DNS-rebinding protection rejects any `Host` header outside `127.0.0.1`/`localhost`/`::1` by default, which silently blocked exactly this case. Verified live end-to-end against a real Open WebUI Docker container after the fix, including a real MCP tool call reaching the archive.

**Transport security:**
- `clients/mcp_server.py`: `FastMCP(...)` now passes an explicit `transport_security=TransportSecuritySettings(...)` when the new opt-in is enabled — built from the SDK's own three default hosts/origins (`127.0.0.1`/`localhost`/`::1`, verified directly against the installed `mcp==1.29.0` source, since passing any explicit `TransportSecuritySettings` skips the SDK's own auto-default branch entirely) plus the configured extra host(s). Disabled (default): `transport_security=None`, unchanged SDK auto-default behavior.
- New `garmin_config._parse_extra_hosts(raw)` helper (comma-separated, whitespace-stripped, bare hostnames get `:*` appended so any port matches) plus three new constants — `MCP_EXTRA_ALLOWED_HOSTS_ENABLED` (bool, ENV `GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED` > `MCP_SERVER_CONFIG_FILE`'s `mcp_extra_hosts_enabled` > default `False`), `MCP_EXTRA_ALLOWED_HOSTS_RAW` (str, same precedence, default `"host.docker.internal"` — a real default, not just a UI placeholder, per session decision), `MCP_EXTRA_ALLOWED_HOSTS` (the parsed list). Same ENV > file > default idiom as `MCP_HTTP_PORT`/`MCP_HEADLESS`.
- `allowed_origins` deliberately left at the SDK's own three defaults, not extended — a server-to-server HTTP client (e.g. Open WebUI's backend) typically sends no `Origin` header at all, and the SDK's own `_validate_origin()` passes automatically when the header is absent. Revisit only if a real `Invalid Origin header` rejection is observed in the log.

**UI (both `app/panel_mcp.py` and `clients/mcp_server_gui.py`):**
- New checkbox ("Extra allowed hosts") gates a comma-separated text field (pre-filled with the real default, `host.docker.internal`) plus a read-only live preview of the parsed entries below it — same `_parse_extra_hosts()` helper drives both the preview and the actual server wiring, so the preview never diverges from what would actually be used. Unchecking the box dims/locks the field but preserves its content (session decision) rather than clearing it.
- Same-session bug found and fixed: `app/panel_mcp.py`'s new field defaulted to `enabled=True` (Qt's own `QLineEdit` default) on construction, regardless of the checkbox's unchecked starting state — only `load_mcp_settings()` explicitly synced the two, so a freshly-constructed panel (before any settings load) showed an active field next to an unchecked box. Fixed by explicitly setting the initial enabled/preview state once at construction time, mirroring the checkbox's own starting value.

**Docs/branding:**
- The small set of German UI strings in these two files translated to English — one pre-existing from v1.7.0.1 (`"Headless starten (ohne Fenster)"` → `"Start headless (no window)"`, both files) and the five introduced by this session's own Extra-Hosts feature (checkbox label, placeholder text, and the two preview messages). `tests/test_qt_app.py`'s three assertions on the old German preview text updated to match.
- `clients/mcp_server_gui.py` gained a `"🦄  GARMIN LOCAL ARCHIVE"` header label above its config section, matching `garmin_app_base.py`'s branding — text/font only, deliberately not the full color-theme parity (would require switching the window's `ttk` theme away from the native Windows look, a bigger, separate change) or a custom titlebar icon (no icon asset exists anywhere in this codebase yet; would need one created and wired into the PyInstaller build).

**Tests:**
- `tests/test_mcp.py` Section 8 grew from eighteen to thirty-three checks: ten new for `_parse_extra_hosts()` edge cases and the `MCP_EXTRA_ALLOWED_HOSTS(_ENABLED/_RAW)` ENV > file > default precedence (8f), five new for the actual `transport_security` wiring on `mcp_server.mcp.settings` itself, enabled and disabled (8g).
- Two of those fifteen new checks initially failed on a real run once the "Extra allowed hosts" checkbox had actually been saved on this machine via live GUI testing — the real `~/.garmin_mcp_server_config.json` then carried `mcp_extra_hosts_enabled: true`, which the "default is False" assertions read straight through (unlike the deliberately file-layer-untested `MCP_HTTP_PORT`/`MCP_HEADLESS` checks above them). Fixed by isolating `Path.home()` to the test's own `_TMPDIR` for just those two reloads, leaving the real config file untouched.
- `tests/test_qt_app.py::TestPanelMcp` grew from 13 to 17 tests — four new (checkbox enables/dims the field, preview reflects parsed hosts, preview shows the disabled message, `get_mcp_settings()` includes both new keys) plus the existing settings-dict-equality tests extended with the two new keys.

**Precondition Teil B (Drift-Check):** PFLICHT this session — `garmin/garmin_config.py` was changed. Confirmed via `dep_map_delta.md` (`build_dep_map.py`, 2026-08-25_Run-01 → 2026-08-25_Run-02): 0 NEU, 0 WEG, 0 GEKIPPT-Regression, 0 GEKIPPT-Verbesserung — clean.

**Deliberately not implemented:**
- Full `ttk` color-theme parity for `clients/mcp_server_gui.py` (would need `ttk.Style().theme_use("clam")` since the native Windows theme mostly ignores custom widget colors — a bigger, separate change) and a custom titlebar icon (no icon asset exists in this codebase; would also need a `build_manifest.py`/PyInstaller bundling entry) — both scoped out this session, "just the unicorn" (text label only).
- `allowed_origins` extension — see Transport security above.
- KNOWN_ISSUES Cluster F ("verstreute lokale Konstanten-Kopien ohne gemeinsame Quelle") — the new `MCP_EXTRA_ALLOWED_HOSTS`/`_ENABLED`/`_RAW` trio technically adds to this existing pattern (same as `MCP_HTTP_PORT`/`MCP_HEADLESS` before them) but wasn't newly introduced by this session — left with the rest of the cluster, unscanned, for its own future session.

**Test result:** 716 / 265 / 465 / 107 / 64 / 165 / 73 / 16 — all green (test_local / test_local_context / test_dashboard / test_broker / test_mcp / test_app_logic / test_qt_app / test_static), Total 1871 (`docs/METRICS.md`).

---

## v1.7.0.1 — MCP HTTP Transport

Migrates the MCP server from stdio to streamable-http transport. The window/server coupling from v1.7.0's Teil (f) — "the window is the server" — is deliberately KEPT as the default (session decision, `NOTES_v1.7.0.1vorbereitung.md` Eckpunkt 6); a new config field adds an explicit, opt-in headless mode for automation instead. Also removes the Ollama model preference field, architecturally misplaced in `garmin_config.py` (no remaining consumer once local-model auto-discovery was dropped from scope).

**Transport:**
- `clients/mcp_server.py`: `mcp.run(transport="streamable-http")` replaces `transport="stdio"`. `FastMCP(..., host="127.0.0.1", port=cfg.MCP_HTTP_PORT)` — host is hardcoded, never configurable; only the port varies.
- New `garmin_config.MCP_HTTP_PORT` — ENV (`GARMIN_MCP_HTTP_PORT`) > `MCP_SERVER_CONFIG_FILE`'s `mcp_http_port` field > default `8756`, same precedence pattern as `MCP_LLM_BACKEND`.
- PID lockfile liveness (`MCP_SERVER_LOCK_FILE`, `tasklist` parsing) removed entirely — replaced by an `OSError` catch at `mcp.run()`'s bind call (start-guard case) and a TCP-connect probe against `127.0.0.1:MCP_HTTP_PORT` (restart-confirmation / health-check case), used in `app/panel_mcp.py::_mcp_server_is_running()` and `clients/mcp_server_gui.py::_is_server_reachable()`. The Restart button's Option C self-relaunch shape (v1.7 Teilbauauftrag h) is otherwise unchanged — only its health-check mechanism moved from lockfile-PID-poll to this TCP probe.

**Headless mode (new, opt-in — NOT the new default):**
- New `garmin_config.MCP_HEADLESS` (bool) — ENV (`GARMIN_MCP_HEADLESS`, `"1"`/`"true"`/`"yes"`) > `MCP_SERVER_CONFIG_FILE`'s `mcp_headless` field > default `False`. Default `False` means `clients/mcp_server.py::main()` still opens `clients/mcp_server_gui.py::run_gui()` by default, coupled to the server exactly as before (window closed = process closed) — only when `MCP_HEADLESS` is true does `main()` route to the new `_run_headless()` instead, running the server directly with no window at all, analogous to `scheduler/daily_update.py`.
- Settable from both `app/panel_mcp.py` (new checkbox, mirrored on save) and `clients/mcp_server_gui.py` itself (new checkbox — takes effect on the *next* start, not the running instance).
- The operational log start (`_start_operational_log()`, `LOG_MCP_MAX = 30`) now lives in `clients/mcp_server.py` (moved out of `mcp_server_gui.py`) since both the headless and windowed paths need it; passed into `run_gui()` as a callable to avoid a circular import.

**Removed:**
- `garmin_config.MCP_OLLAMA_MODEL` and the Ollama model dropdown + "Refresh" button in both `app/panel_mcp.py` and `clients/mcp_server_gui.py`.
- `garmin_config.MCP_SERVER_LOCK_FILE` (see Transport above).

**Configuration:**
- `MCP_SERVER_CONFIG_FILE`'s field set changes from `mcp_llm_backend`/`base_dir`/`mcp_ollama_model` (three fields) to `mcp_llm_backend`/`base_dir`/`mcp_http_port`/`mcp_headless` (four fields) — one field swapped, one added. Both documented writers (`app/panel_mcp.py`, `clients/mcp_server_gui.py`) updated together.

**Build integration:**
- T3.3 (`mcp_server.exe`) `windowed=False` deliberately left unchanged in this Bauauftrag — the original reason (stdio needing real console `stdin`/`stdout`) no longer applies under streamable-http, but flipping it risks `sys.stderr` being invalid under `--windowed`, crashing `logging.basicConfig()` before any log handler exists. Untestable in this environment (no Windows build available) — flip only after a real Windows T3.3 build confirms logging still starts cleanly with no console.

**Deliberately not implemented:**
- `windowed=True` for T3.3 (see Build integration above) — left for Timo to test and decide on a real Windows build.

**Tests:**
- `tests/test_mcp.py` Section 8 grew from nine to eighteen checks — nine new checks for `MCP_HTTP_PORT`/`MCP_HEADLESS` ENV > file > default precedence and for the `MCP_SERVER_LOCK_FILE`/`MCP_OLLAMA_MODEL` removal.
- `tests/test_qt_app.py::TestPanelMcp` — six tests corrected to match the new `panel_mcp.py` UI (Ollama model dropdown + Refresh button removed, Port + Headless checkbox added): the two backend-visibility tests no longer assert on the removed `_mcp_ollama_box`, `test_get_mcp_settings_reflects_checkbox_and_backend` now expects `mcp_http_port`/`mcp_headless` instead of `mcp_ollama_model`, and the three `_mcp_on_ollama_models_loaded()` tests were removed outright (tested functionality that no longer exists). 72→69 checks. Found via a full `test_all` run after the initial anchor delivery — not part of the original Bauauftrag scope, fixed in the same session once discovered.

**Precondition Teil B (Drift-Check):** PFLICHT this session — `garmin/garmin_config.py` was changed. Confirmed via `dep_map_delta.md` (`build_dep_map.py`, 2026-08-24_Run-03 → 2026-08-25_Run-01): 12 NEU, 19 WEG, 0 GEKIPPT-Regression, 0 GEKIPPT-Verbesserung. All 12 NEU handlers reviewed individually: either the new TCP-probe/form-validation patterns this Bauauftrag introduces (`_mcp_server_is_running`, `_is_server_reachable`, the port-field `ValueError` guards in `run_gui`) or a pure relocation of `_start_operational_log()` from `mcp_server_gui.py` into `mcp_server.py` (visible as a matching WEG entry in its old location) — no undocumented risk, no Handlungsbedarf. All 19 WEG entries are the expected removal of the lockfile/`tasklist` liveness code and the Ollama-refresh worker, plus that same relocation. New `dep_map_records.json` committed to `docs/` as the baseline for the next session.

**Test result:** 716 / 265 / 465 / 107 / 49 / 165 / 69 / 16 — all green (test_local / test_local_context / test_dashboard / test_broker / test_mcp / test_app_logic / test_qt_app / test_static), ruff 0 errors, bandit 0 HIGH.

---

## v1.7.0 — MCP Server

Exposes GLA's archive to local LLMs via the Model Context Protocol — natural-language queries against health and context data without manual export or file upload. Runs as an independent standalone process, fully decoupled from the main GUI.

**New modules:**
- `maps/mcp_map.py` — thin, stateless protocol translator on top of `gateway_map`. Three domain-separated query functions (`query_health`, `query_context`, `query_fit_activities` — deliberately not a single generic `query(domain=...)`, so a misspelled domain name fails as a Python error, not a silent string mismatch) for time-series data, plus `query_raw` for direct broker pass-through, `get_archive_metadata` (archive-level introspection via `gateway_map`'s metadata registry — coverage stats, device table, quality log, capability config, raw logs; not time-series, one function per known archive file/folder), and `list_available_fields` as a discovery/overview helper across domains and metadata kinds. Every date-bound response carries a `_meta` block with explicit weekday tables, addressing an LLM weekday-hallucination risk identified during design. No write access, no MCP-SDK import — testable in isolation.
- `clients/mcp_server.py` — standalone MCP server process (stdio transport, `mcp>=1.28,<2`). Always opens a Tkinter configuration/log window (`clients/mcp_server_gui.py`) rather than running headless — the window owns the server thread (`mcp.run()` in a daemon thread), live Ollama model refresh, cloud-LLM backend fields, boot/operational log with rotation, and a Start/Restart control surface.
- `app/panel_mcp.py` — new standalone GUI tab (`PanelMcp`), mirroring archive path and backend choice into the same config file the standalone process reads. Includes a "▶️ Start MCP Server" button with PID-lockfile-based duplicate-instance protection, resolving the correct launch target per build (T1 script / T2 batch launcher / T3.3 executable).
- `clients/mcp_server_gui.py` — "🔄 Restart Server" button using a self-relaunch pattern: the new process starts, the old window stays responsive until the new PID is confirmed in the lockfile, then hands over. Avoids a dual-stdio-reader conflict inherent to in-process reloading.

**Configuration:**
- New per-user config file (`~/.garmin_mcp_server_config.json`) holding archive path, LLM backend choice, and Ollama model — written by both `panel_mcp.py` (GUI mirror) and `mcp_server_gui.py` (standalone edits), each aware of the other.
- Optional cloud-LLM backend via a separate plaintext config file (`~/.garmin_mcp_llm_config.json`, provider/api_key/model) — Ollama remains the default and requires no configuration.

**Build integration:**
- New build target T3.3 — standalone `mcp_server.exe`, `--onefile`, no Python required, independent of the main GLA executable. Console window intentionally retained despite the Tkinter GUI: `mcp.run(transport="stdio")` requires real `stdin`/`stdout` streams, unavailable under PyInstaller's windowed mode.
- T2 gains `clients/Starte_MCP_Server.bat` as a loose-script launcher.

**Deliberately not implemented:**
- Health-check on restart — the restart poll confirms a new PID appears in the lockfile, not that the new process is actually operational (e.g. a misconfigured archive path at restart time is not caught). Documented, not fixed — a real health check would need a stdio handshake and is a larger, separate piece of work.
- Cloud-LLM API calls (config storage only; the actual backend integration is v1.7.2), WCM-encrypted cloud credentials (plaintext + on-screen warning is the deliberate v1.7.x choice).

**Test result:** 1846 / 1846 checks across all eight suites — all green (test_local / test_local_context / test_dashboard / test_broker / test_mcp / test_app_logic / test_qt_app / test_static).

---

## v1.6.9.2 — Broker Test Suite (Split + metadata_map Coverage)

Two-part follow-up to v1.6.9.1: the broker-layer routing-contract tests that
sat mixed into `test_dashboard.py` since v1.6.7 move into their own test
file, and the test coverage for `metadata_map.py`/`gateway_map.get_metadata()`
deferred at the end of v1.6.9.1 is added — nine functions plus dispatch,
including edge cases (missing files, corrupt JSON, unreadable raw-log
directories, and a hard-exclusion regression guard for `GARMIN_TOKEN_FILE`).
No production code changed — test-only and documentation session.

**New files:**
- `tests/test_broker.py` — Broker layer. Sections 1–2: `health_map` and
  `gateway_map` routing-contract checks (31 checks), moved verbatim out of
  `test_dashboard.py`, no content changes. Section 3: `metadata_map.py`
  coverage — all nine functions, missing-file/dir cases first, then
  happy-path fixtures, corrupt-JSON handling, and unreadable raw-log
  directories (31 checks). Section 4: `_sanitize_line()` security filter —
  secret-drop and PII-mask paths (17 checks). Section 5:
  `gateway_map.get_metadata()` dispatch (13 checks). 92 checks total.

**Changed modules:**
- `tests/test_dashboard.py` — Section 2 (`health_map` routing) and Section 2b
  (`gateway_map` routing) removed (114 lines), relocated to `tests/test_broker.py`
  without modification. 496→465 checks.
- `run_tests.ps1` / `compiler/build_all.py` — `tests/test_broker.py` added to
  the pre-build test chain, directly after `test_dashboard.py`.
- `docs/MAINTENANCE_GLOBAL.md` — new `tests/test_broker.py` section added;
  `test_dashboard.py` description updated to reflect the split.
- `docs/MAINTENANCE_DASHBOARD.md` — Section 2/2b rows removed from the
  `test_dashboard.py` coverage table; `gateway_map.get()` contract note
  repointed to `tests/test_broker.py`.
- `docs/ROADMAP.md` — `**Currently stable**` bumped to v1.6.9.2.

**Documentation:**
- `docs/CHANGELOG.md` — all pre-existing German-language entries (7 of 114)
  translated to English; no content changed beyond language, including one
  entry title (`v1.6.2.1`). Historical test-result numbers, file names, and
  code identifiers preserved verbatim.

**Bug fixed during implementation:**
- `tests/test_broker.py` — ruff `E741` (ambiguous variable name `l`) on two
  generator-expression loop variables in the raw-log tests; renamed to `line`.

**Precondition Teil B (Drift-Check):** N/A — no code in `garmin/`·`context/`·
`maps/`·`dashboards/`·`layouts/` changed this session (test-only + doc
session). Confirmed via `dep_map_delta.md` (`build_dep_map.py`,
2026-08-22_Run-02 → 2026-08-23_Run-01): 0 NEU, 0 WEG, 0 GEKIPPT-Regression.

**Test result:** 716 / 265 / 465 / 92 / 165 / 59 / 16 — all green
(test_local / test_local_context / test_dashboard / test_broker /
test_app_logic / test_qt_app / test_static), ruff 0 errors, bandit 0 HIGH.

**Addendum — context_map broker-level coverage (delivered as
`anchor_delivery_1692-01`, pending local confirmation):**
- `tests/test_broker.py` — new Section 1b: `context_map` fan-out routing
  (multi-source `get()`, KeyError-skip for fields unknown to a source,
  per-source exception degrade via monkeypatch, `list_fields()`/
  `list_sources()`). Closes the pre-existing gap noted in this file's header
  docstring and in `NOTES_v1692.md` — `health_map` has only one registered
  source, so its own tests never exercised the multi-source fan-out path;
  `context_map` (four sources: weather/pollen/brightsky/airquality) is the
  first place this logic gets real coverage. 15 new checks — 92→107 in
  `tests/test_broker.py`.
- `docs/MAINTENANCE_GLOBAL.md` — `tests/test_broker.py` section text updated
  to reflect the closed gap; "Run after any change to" list extended with
  `context_map` and its four source modules (`weather_map`/`pollen_map`/
  `brightsky_map`/`airquality_map`).
- Verified in isolation this session — Section 1b run standalone (107/107
  green) and `ruff check` against the project's `ruff.toml` (0 errors) —
  not yet run through `run_tests.ps1` on Timo's machine.

---

## v1.6.9.1 — metadata_map Broker

Third domain broker in the broker layer (`maps/`), on par with
`health_map`/`context_map`: archive metadata (coverage stats, device table,
quality log, token event log, capability config, raw logs) is now queryable
through the broker layer instead of via four scattered direct import paths.
Pulled forward from a v1.9 roadmap note (see `KNOWN_ISSUES.md`,
block 1b), because `gateway_map.py` is the planned v1.9 MCP docking point —
without this broker, archive metadata would remain unreachable for a future
MCP client. Design cross-checked by a multi-LLM review gate (Gemini, ChatGPT,
Copilot, Le Chat); security filter and error behavior adjusted according to
the feedback.

**New modules:**
- `maps/metadata_map.py` — introspection broker, nine named functions
  (`get_stats`, `get_device_table`, `get_quality_log`, `get_source_api_log`,
  `get_token_log`, `get_capability_config`, `get_daily_logs`,
  `get_fail_logs`, `get_recent_logs`). Not time-series-based — each
  function reads exactly one known archive file or raw-log folder.
  Uniform return envelope `{"data": ..., "error": str | None}`,
  never raising (read/parse errors are caught internally and returned
  degraded — analogous to `health_map`/`context_map`). Hard
  exclusion boundary: `GARMIN_TOKEN_FILE` (`garmin_token.enc`) is not
  referenced anywhere. The three raw-log functions filter every
  line through `_sanitize_line()` — detected auth material (JWT/Base64
  fragments, Bearer/Authorization headers, token keywords, password
  fragments, cookies) is dropped, detected PII (email, IPv4,
  GPS coordinates) is masked rather than removed, to preserve
  diagnostic value.

**Changed modules:**
- `maps/gateway_map.py` — new function `get_metadata(kind: str) -> dict`,
  separate from `get()`, since archive metadata structurally
  doesn't fit the time-series-based `field`/`date_from`/`date_to`/
  `resolution` schema of `get()`. `_METADATA_KINDS` dispatch dict
  (nine entries, 1:1 with `metadata_map`), `ValueError` on unknown
  `kind` — same stability pattern as the existing `domain` handling
  in `get()`. New function `list_metadata_kinds()`. Docstring header
  extended with the metadata registry (previously only the domain
  registry was documented).
- `garmin/garmin_config.py` — new constant `LOG_DAILY_DIR`, additive
  alongside the existing `LOG_RECENT_DIR`/`LOG_FAIL_DIR`.
- `compiler/build_manifest.py` — `maps/metadata_map.py` added to
  `SHARED_SCRIPTS`.

**Deliberately not implemented:**
- Migration of the four existing direct `get_archive_stats()` callers
  (`garmin_app_controller.py`, `panel_archive.py`, `context_collector.py`,
  `garmin_mobile_landing.py`) — left unchanged, the `app/` layer has
  no direct relationship to the broker layer. `garmin_mobile_landing.py`
  additionally remains a documented special case (see `KNOWN_ISSUES.md`
  cluster A), to be adjusted at the next substantive touch.
- `get_schema_versions()` (proposed by the multi-LLM review) —
  deferred: `garmin_normalizer.py`'s `CURRENT_SCHEMA_VERSION` is only
  the target version in code, the module has no file/archive access
  per its own docstring. A real actual-state function would have had to
  search `SUMMARY_DIR` — a different character from the nine single-file
  functions, not built without further analysis.
- Test coverage for `metadata_map.py`/`gateway_map.get_metadata()` —
  deferred to v1.6.9.2, together with a planned extraction of
  all broker tests out of `test_dashboard.py` into a dedicated test file.

**Drift-Check (`build_dep_map.py`, 2026-08-22_Run-01 → Run-02):**
10 NEU exceptions + 5 NEU fileio, all in `maps/metadata_map.py` — nine
broad-`Exception` handlers (architecturally intended, see "never
raising" above) + one narrow `OSError` handler in `_read_log_dir()`, plus
five fileio findings in the two internal read helpers
(`_read_json_file`, `_read_log_dir`). 0 WEG, 0 GEKIPPT-Regression.

**Test result:** 716 / 265 / 496 / 165 / 59 / 16 — all green, ruff 0
errors, bandit 0 HIGH.

---

## v1.6.9 — Review Follow-up / v1.6 Wrap-up

Closes the findings with real data-damage/escalation potential from
code review sessions 1–6 (`REVIEW_GESAMTAUSWERTUNG.md`), before v1.7
(FIT pipeline) and v1.7.1 (MCP/SQLite proxy) build on the same code areas.
Four blocks, as planned in `v1.6.9_ROADMAP_EINTRAG.md`.
Additionally: `garminconnect` dependency update to 0.3.11, T3 rebuilt.

**Block 1a — E2E test for the daily sync-fetch loop:**
- `tests/test_local.py` — new test block, runs `garmin_collector.main()`
  across three fixed days through the real fetch loop (steps 1–9) instead of
  just through the capability-scan branch: clean day (`high`), validator
  `critical` (`failed`, `recheck=True`), downgrade rejection (`high`/`bulk`
  holds against a fresher, lower-rated fetch). 13 new
  checks, `test_local.py` 703→716.

**Block 1b — `quality/_stats.py::get_archive_stats()` device_table fix:**
- `garmin/quality/_stats.py` — removed dead `device_table` construction
  (dead-code block + entire matching branch against `device_rank`, which
  has not been set per day entry since the v1.5.7 migration).
  Removed the `"device_table"` key from the return value. All four real
  callers already use `_io.py::save_device_table()` or read
  `device_table.json` directly — no consumer affected.
- `garmin/garmin_quality.py` — docstring correction (facade doc still
  mentioned `device_table` as part of `get_archive_stats()`).

**Block 2 — QUALITY_LOCK access from `panel_archive.py`:**
- `app/garmin_app_controller.py` — new function
  `rename_unknown_device(s, new_name)`, encapsulates the full
  load-modify-save cycle under `QUALITY_LOCK`, never raises.
- `app/panel_archive.py` — `_archive_on_device_name_click()` now delegates
  to the controller instead of acquiring `QUALITY_LOCK` directly and
  calling private facade functions. Closes the third, undocumented
  access path.
- `GLA_HANDBUCH.md` §10/§14 — updated to fully list all six
  actual lock holders (docs previously named only two);
  documented `garmin_app_controller`'s write access.

**Block 3 — one-liner cleanup batch (8 findings):**
- `layouts/garmin_mobile_landing.py` — corrected the wrong expected file
  name for the sleep dashboard embed (`sleep_garmin_html-xls_dash.html`) to
  the actual specialist output (`sleep_dashboard.html`) — the
  `_read_dash()` call, docstring, and visible HTML label, all three
  spots. This caused the embed on the mobile landing page to remain
  permanently empty, with no logged error.
- `garmin/garmin_config.py` — removed duplicate `LOCAL_CONFIG_FILE` assignment.
- `garmin/garmin_mirror.py` — removed a duplicate, entirely unused
  `EXCLUDE_DIRS` constant (both occurrences; `garmin_container.py`
  uses its own, independent `_EXCLUDE_DIRS`).
- `app/panel_outputs.py` — removed a duplicate `_exe_dir`
  assignment in `_create_task_scheduler_xml()`.
- `maps/pollen_map.py` — removed a commented-out `_FILE_PREFIX` duplicate
  above `_FIELD_MAP`.
- `garmin/quality/_assess.py` — removed a redundant `elif`
  branch (`training_readiness`, field-level); the remaining branch
  already covers the same case.
- `dashboards/health_garmin_html-json_dash.py` — removed a dead
  `vo2_raw` expression (unused, silenced with `# noqa: F841` instead of
  being properly removed).
- `dashboards/dash_runner.py` — removed an unreachable defensive check
  in `scan()` (`dash_runner.py` can structurally never match the
  `*_dash.py` glob).
- `docs/REFERENCE_DASHBOARD.md` — updated the "Dashboard links"
  line (previously named the same wrong sleep dashboard file name as the
  code finding).

**Dependency:**
- `garminconnect` — updated to release 0.3.11.
- `version.py` — `APP_VERSION` set to `1.6.9`, T3 standalone rebuilt.

**Drift-Check (`build_dep_map.py`, baseline 2026-08-16 → 2026-08-22):**
1 NEU exception + 1 NEU fileio (both `garmin_app_controller.py::
rename_unknown_device`, architecturally intended — encapsulates the
load-modify-save cycle, never raises), 1 WEG exception (the removed
`QUALITY_LOCK` block in `panel_archive.py`, superseded by the controller
delegation — an improvement, not a gap). 0 GEKIPPT-Regression.

**Test result:** 716 / 265 / 496 / 165 / 59 / 16 — all green, ruff 0 errors,
bandit 0 HIGH.

---

## v1.6.8.2 — Standalone Log Order Fix

Fixes a display-order bug found in the Standalone build (T3): the
`on_done`/`on_success` callbacks of `_run()` were dispatched directly via
the inherited `_dispatch()` (Qt queued signal, near-immediate delivery),
while regular log output from the running script went through
`_log_queue` + `_poll_log_queue()` (100ms polling). When a callback itself
produced log text — as in the API Capability Scan's "finished" message —
it could overtake log lines still waiting on the next poll tick, showing
the callback's text before lines that logically preceded it. Confirmed via
code reading (both delivery paths in `garmin_app_standalone.py`), not
guessed from the log symptom alone. No data-integrity issue — Standalone
and Target 2 (`garmin_app.py`) produced identical, correct scan results;
only the on-screen line order in the Standalone log widget was affected.
Target 2 was never affected — it has no `_log_queue`/polling architecture,
so no competing delivery path exists there.

**Changed modules:**
- `garmin_app_standalone.py` — `worker()`'s `finally` block: `on_success`
  and `on_done` are now enqueued via `q.put(...)` instead of dispatched
  directly via `self._dispatch(...)`, so they run after any log lines
  already ahead of them in the queue. `_poll_log_queue()` extended to
  handle both queue item types — log-line strings (unchanged path) and
  zero-arg callables (new: invoked directly instead of passed to
  `self._log()`). The `enable_stop`-related `_dispatch()` call (button
  enable/disable, no text output) is unaffected and left unchanged.

**Investigated, not changed:** the `on_done`/`_dispatch()` pattern also
appears in `panel_outputs.py::_run_all_dashboards()` /
`_run_dashboards()` and in the shared `_run()` signature across
`garmin_app.py` / `garmin_app_base.py` / `garmin_app_standalone.py` (DEPS
scan `v1682_01`, confirmed via Scope-Snapshot). Read in full:
`panel_home.py`'s Daily-Sync callback chain (`_on_garmin_done` →
`_on_context_done` → `_on_all_done`) produces no log text of its own, only
chains the next step and re-enables a button — not affected by the
display-order symptom, no change needed. `garmin_app_base.py._dispatch()`
itself (Qt `pyqtSignal` queued connection) is correct and shared by
Target 2, which has no competing queue — left unchanged.

**Test result:** 703 / 265 / 496 / 165 / 59 / 16 — all green, drift-check
clean (`dep_map_delta.md`, 2026-08-16 Run-01 → Run-02: 0 NEU / 0 WEG / 0
GEKIPPT-Regression — no code in `garmin/`·`context/`·`maps/`·
`dashboards/`·`layouts/` changed this session, scan run anyway for extra
confidence).

---

## v1.6.8.1 — Doppel-Gate Filter Extraction + Test Coverage

Closes the one test gap deliberately carried forward from v1.6.8 Session F:
the API-Capability-Scan candidate-selection filter
(`enabled_by_user == True` **and** `status == "found"`) sat inline in
`garmin_collector.py::main()`'s fetch-loop section, not independently unit
testable without invoking the rest of `main()`. Pure refactoring — no
behavior change, no new feature.

**Changed modules:**
- `garmin/garmin_api_capability.py` — new `get_enabled_candidates(config)`,
  placed between `reset_config()` and the `ENDPOINT_ARGS` block (sync-time
  helper, alongside `build_args()`). Pure function, `config.get("endpoints",
  {})` defensive access consistent with the rest of the module's
  never-raise contract. No new import — Leaf-Node status unchanged.
- `garmin/garmin_collector.py` — `main()`'s fetch-loop section now calls
  `capability.get_enabled_candidates(_capability_config)` instead of
  inlining the double-gate list comprehension. `load_config()` stays in
  `main()`, still read once per sync run inside `quality.QUALITY_LOCK` —
  the race-safety snapshot semantics are unchanged, only the filter step
  moved.
- `tests/test_local.py` — 7 new checks for `get_enabled_candidates()`
  (Section K): both gates satisfied, `status`-only, `enabled_by_user`-only,
  missing endpoint key (no `KeyError`), empty `endpoints` dict, multiple
  enabled candidates, return order follows `CANDIDATE_ENDPOINTS`. No mocks
  needed — pure dict fixtures via `_default_config()`/`update_endpoint()`.

**Investigated, not a fix:** DEPS scan flagged `app/panel_outputs.py`
(Edit Config dialog) as a possible shadow-copy of the double-gate filter.
Confirmed false positive after reading the file — it's a single-gate
display filter (`status == "found"` only, decides which endpoints appear
as checkboxes), not a reconstruction of the sync-time double-gate. No
change made.

**Test result:** 703 / 265 / 496 / 165 / 59 / 16 — all green, ruff 0
errors, bandit 0 HIGH. Drift-check clean (`2026-08-14_Run-02` →
`2026-08-16_Run-01`: 3 NEU / 0 WEG / 0 GEKIPPT-Regression, all traced to
`support-tools/login-probe/garmin_login_probe.py` — a standalone
diagnostic tool outside the GLA package tree, unrelated to this session).

---

## v1.6.8 — API Capability Scan + Broker Extension

Detects per-user which of 19 additional Garmin health endpoints — beyond
the 15 hardcoded baseline `fetch_raw()` endpoints — actually return real
data, and wires the confirmed ones into the archive and broker layer.
Baseline-15 stay unconditional (Archive-First: a scan false-negative must
never disable an existing capture). Six sub-sessions.

**New modules:**
- `garmin/garmin_api_capability.py` — Sole-Write-Authority for the new
  `garmin_api_capability_config.json`. Leaf module (`garmin_config` +
  stdlib only). `CANDIDATE_ENDPOINTS` (19 names), `load_config()` /
  `save_config()` (atomic write), `update_endpoint()`, `reset_config()`,
  `ENDPOINT_ARGS` + `build_args()` (5 endpoints need `no_args`/
  `date_range` instead of the default single-date signature).

**Changed modules:**
- `garmin/garmin_config.py` — new `CAPABILITY_CONFIG_FILE` path constant.
- `garmin/garmin_collector.py` — `run_capability_scan(client,
  window_days=7)`: per-candidate isolated try/except, three-valued result
  (`found`/`not_observed`/`error`), runs under the existing
  `quality.QUALITY_LOCK` (no separate lock needed — mutual exclusion with
  the regular sync already guaranteed). New "0b. Capability Scan mode"
  entry point in `main()` (`GARMIN_CAPABILITY_SCAN=1`,
  `GARMIN_CAPABILITY_WINDOW_DAYS`). `_fetch_and_assess()`: new
  `enabled_candidates` param, config read once per sync run as an
  immutable snapshot inside the existing `QUALITY_LOCK` block, filtered by
  double-gate (`enabled_by_user == True` **and** `status == "found"`).
- `garmin/garmin_api.py` — `fetch_raw()`: new `extra_endpoints` param,
  appended to the fixed 15-endpoint baseline list. Stays config-blind.
- `garmin/garmin_dataformat.json` — 19 new optional fields
  (`{"type": "any", "required": false}`), `schema_version` unchanged
  (`"1.1"`) — no re-validation wave for already-archived days.
- `garmin/garmin_normalizer.py` — `CURRENT_SCHEMA_VERSION` 2 → 3.
  `summarize()` extended for 6 of the 19 candidates: `s["day"]
  ["calories_resting"]`, `s["body_composition"]["weight_g"]`,
  `s["hydration"]["hydration_ml"]`, `s["training"]["endurance_score"]`,
  `s["training"]["hill_score"]`, `s["fitness_age"]`. Remaining 13
  candidates stay archive-only (structurally not day-values, or unclear
  schema) — reachable via the new raw-passthrough path below, no
  `summarize()` interpretation.
- `maps/garmin_health_map.py` — 6 new `_FIELD_MAP` entries (existing
  `"daily"` descriptor, no new broker mechanism). New
  `_CAPABILITY_FIELDS` whitelist + `list_fields(active_only=False)` —
  filters capability-derived fields by `enabled_by_user` when `True`;
  baseline fields always visible; default unchanged. New
  `_RAW_PASSTHROUGH_FIELDS` dict (separate from `_FIELD_MAP`) +
  `list_raw_fields()`/`get_raw()` for the remaining 13 candidates — reads
  directly from `raw/`, no interpretation, existing `get()`/`list_fields()`
  contracts untouched.
- `maps/health_map.py` — `list_fields(source, active_only=False)` and new
  `get_raw()`/`list_raw_fields()` pass `active_only`/raw-access through to
  `source="garmin"` only (sole source with a capability concept); other
  sources unaffected.
- `maps/gateway_map.py` — `get_raw()`/`list_raw_fields()` added,
  symmetric to `get()`/`list_domains()` (unknown domain → `ValueError`,
  unregistered/unsupported domain → degraded `{"error": ...}` result).
  Cross-domain raw access for the future MCP server (v1.9).
- `app/panel_outputs.py` — new "🔍 API Scan" button in DATA COLLECTION,
  popup with Start Scan / Edit Config / Clear Config
  (`_open_capability_scan_popup()` + three dialogs). Start Scan reuses the
  existing subprocess mechanism (`self._app._run("garmin_collector.py",
  env_overrides={...})`); Edit/Clear Config run in-process. Edit Config
  only offers confirmed `found` candidates (double-gate holds). Two call
  sites (`garmin_list_fields()`) switched to `active_only=True` —
  governance decision: Custom Dashboard / Explorer show only
  user-activated capability fields, no new import into `dashboards/`
  (the `active_only` param travels through the existing broker path
  instead).
- `custom_dash_builder.py`, `explorer_garmin-context_html_dash.py` — one
  line each, `garmin_list_fields(active_only=True)`.
- `tests/test_local.py` — schema-version check now dynamic
  (`normalizer.CURRENT_SCHEMA_VERSION`, no longer hardcoded `== 2`); two
  outdated E4b mock signatures fixed (`extra_endpoints=None` added — a
  pre-existing gap from Bauauftrag 03, unrelated to the pilot itself, hit
  by chance in this session's test run).

**External tooling, not part of this repo:** `test_capability_fetch.py` —
ad-hoc diagnostic script (real-account payload inspection across all 19
candidates), lives outside `src/`, not part of the build.

**Documentation:**
- `REFERENCE_GARMIN.md` — broker-visibility invariant (6 interpreted / 13
  raw, deduplicated from an earlier "2 wired / 17 open" note),
  `active_only` invariant, new "Raw-passthrough fields" section (13
  entries, open-GitHub-issue status note), Summary-JSON table
  (`hydration` new, `training` extended).
- `REFERENCE_BROKER.md` — new `health_map.get_raw()` section, Auxiliary
  Functions table extended (`active_only`/`list_raw_fields`),
  `gateway_map` section extended (`get_raw()`/`list_raw_fields()`), field
  index 21 → 25 registered fields + new 13-field raw-passthrough table.
- `MAINTENANCE_GARMIN.md` — known-open-point resolved,
  `get_fitnessAge()`/`get_fitnessage_data()` naming-collision quirk
  clarified, test-gap notes for the four untested new paths
  (`active_only`, `get_raw()`/`list_raw_fields()` at both broker levels).
- `GLA_HANDBUCH.md` — Broker-Pattern section (§3): raw-passthrough noted
  as a documented, deliberate exception.

**What does not change:**
- Baseline 15 `fetch_raw()` endpoints — always run, regardless of scan
  result.
- `garmin_live_fetch.py` — separate 8-field live-snapshot path for the
  Ollama Chat panel, explicitly out of scope, not touched.
- No dedicated `NETZ 2` core module touched at any point in this arc.

**Known open points, carried forward (not part of this entry):**
- GitHub issue + feedback template for the 13 raw-passthrough fields
  (community input on aggregation/display, real filled examples needed).
- Suspected duplicate `get_body_composition` / `get_daily_weigh_ins` and
  the assumed gram unit for `weight_g` — both only verifiable by a user
  with a real Garmin-compatible scale, to be raised in the GitHub issue
  above, not resolved here.
- Netz-2 diagnosis for `run_netz2_steps_async.py` /
  `run_netz2_stop_abort.py` / `run_netz2_bulk_import.py` not re-run since
  the capability-scan changes to `garmin_collector.py` (baseline
  `v167_01` predates them) — hash-confirmed change, no regression
  expected, re-run not scheduled for this release.
- Inline double-gate candidate-filter logic in `garmin_collector.py::main()`
  (fetch-loop section) has no independent unit coverage — would require
  extracting it out of `main()` first. Planned as its own small fix+test
  follow-up, see `MAINTENANCE_GARMIN.md`.

**Test coverage addendum (Session F, 2026-08-14):** dedicated test
Bauauftrag for this arc's new paths completed post-release —
`garmin_api_capability.py`, `run_capability_scan()`, the `main()` step-0b
entry point, `fetch_raw()`'s `extra_endpoints`, `list_fields(active_only=True)`,
and both `get_raw()`/`list_raw_fields()` broker levels are now covered
(`test_local.py` 631→696, `test_dashboard.py` 464→496). See
`NOTES_v168_F_01.md`. One narrower gap remains, carried forward above.

**Test result:** 696 / 265 / 496 / 165 / 59 / 16 — all green, ruff 0
errors, bandit 0 HIGH. Drift-check clean throughout (final delta
`2026-08-14_Run-01` → `Run-02`: 4 NEU / 0 WEG / 0 GEKIPPT-Regression, all
traced to the raw-passthrough addition).

---

## v1.6.7 — Broker Layer Restructuring (health_map / garmin_health_map / gateway_map)

Prepares the Broker Layer for the v1.7 FIT Pipeline: `field_map.py` and
`garmin_map.py` become true domain-prefixed peers to the upcoming
`fit_map.py`/`garmin_fit_map.py`, and a new `gateway_map.py` broker adds a
selective cross-domain entry point for future consumers (`mcp_map`, v1.9)
without rerouting any existing named specialist. Alongside this, full test
coverage was added for the v1.6.6 Ollama Chat interface. Four sub-sessions,
each with its own DEPS-Scan + Scope-Snapshot pair.

**New modules:**
- `maps/health_map.py` — renamed from `maps/field_map.py`. Functional code
  unchanged, docstring references updated. True peer to `context_map.py`
  and the future `fit_map.py`.
- `maps/garmin_health_map.py` — renamed from `maps/garmin_map.py`.
  Domain-prefix convention established: sources that can plausibly serve
  multiple domains (device/platform vendors — Garmin, Apple, Fitbit) get
  the prefix from day one; single-domain external APIs (Weather, Pollen,
  Brightsky) do not. `_FIELD_MAP` and all functional code unchanged.
- `maps/gateway_map.py` — new broker, pass-through routing over
  `_DOMAIN_BROKERS` (`{"health": health_map, "fit": None, "context":
  context_map}`, `fit` key reserved for v1.7). Unknown domain string →
  `ValueError`; known but unregistered domain → degraded result with an
  `error` key, never a hard fail on a broker exception. No unwrapping —
  passes each domain broker's return value through unchanged
  (`result[domain][source] = {"values", "fallback",
  "source_resolution", "error"?}`). `list_domains()` added, analogous to
  `list_sources()` in `health_map`/`context_map`. Scope is deliberately
  selective, not universal — named specialists keep importing their
  domain broker directly; `gateway_map` exists for future cross-domain
  consumers only.

**Changed modules:**
- `compiler/build_manifest.py` — `SHARED_SCRIPTS`: `maps/field_map.py` →
  `maps/health_map.py`, `maps/garmin_map.py` → `maps/garmin_health_map.py`,
  new entry `maps/gateway_map.py` added.
- `maps/context_map.py` — comment fix ("Structurally identical to
  health_map.py").
- 11 dashboard/test files — import line + all `field_get` call sites
  renamed to `health_get` (full rename, no alias):
  `custom_dash_builder.py`, `explorer_garmin-context_html_dash.py`,
  `health_garmin-weather-pollen_html-xls_dash.py`,
  `health_garmin_html-json_dash.py`, `heatmap_garmin_html_dash.py`,
  `live_tracking_html_dash.py`, `overview_garmin_xls_dash.py`,
  `sleep_garmin_html-xls_dash.py`, `sleep_recovery_context_dash.py`,
  `timeseries_garmin_html-xls_dash.py`, `tests/test_dashboard.py`.
- `garmin/quality/_assess.py`, `garmin/garmin_config.py`,
  `garmin/garmin_live_fetch.py`, `dashboards/heatmap_garmin_html_dash.py`
  — comment-only references to `garmin_map` updated to
  `garmin_health_map`.
- `tests/test_dashboard.py` — import line, 3 section headers, and all
  `garmin_map.get(...)`/`.list_fields()` call sites renamed (39 anchors);
  new section "2b. gateway_map — routing" added (11 checks: `domain=None`
  fan-out, single-domain queries, unknown-domain `ValueError`,
  `list_domains()`).
- `tests/test_app_logic.py` — new Section 21: full-depth coverage for
  `clients/ollama_client.py` (`is_reachable()`, `list_models()`, `chat()`
  — 2 success + 9 error paths). First `requests`-mocking pattern in the
  test tree (`unittest.mock.patch`).
- `tests/test_qt_app.py` — new `TestPanelChat` class (13 smoke-level
  tests), inserted before `TestGarminAppBase`.

**Documentation:**
- `REFERENCE_BROKER.md` — broker table gains `gateway_map.py`, `mcp_map.py`
  row corrected (protocol translation, not aggregator), new
  `gateway_map.get()` contract section, "Future brokers" section
  corrected (third correction of this section).
- `REFERENCE_GARMIN.md`, `REFERENCE_DASHBOARD.md` — rename references
  updated.
- `GLA_HANDBUCH.md` — architecture diagram (§2), Broker-Pattern text (§3),
  hard-rule line (§4) updated to `health_map`; new paragraph on
  `gateway_map`.
- `MAINTENANCE_DASHBOARD.md`, `MAINTENANCE_GLOBAL.md` — pipeline
  diagrams, "Run after any change to" lists, test section tables updated.

**Test result:** 631 / 265 / 464 / 165 / 59 / 16 — all green, ruff 0
errors, bandit 0 HIGH. `test_dashboard.py` 453 → 464 (+11, exactly the new
`gateway_map` checks — no silent loss/gain elsewhere). Drift-check
(`build_dep_map.py`, 2026-08-13 vs. 2026-08-11 baseline): 0 GEKIPPT-
Regression, all NEU/WEG entries traced to the `garmin_map`→
`garmin_health_map` rename plus one genuinely new, intentional broad
exception handler in `gateway_map.get()`.

---

## v1.6.6.1 — Log Timestamp Consistency (Context/Dashboard Pipeline)

Closes Punkt 3 from the v1.6.6.1 candidate list (`ROADMAP.md`) — the Garmin
page uses the `logging` module (timestamp added automatically), while the
Context/Dashboard pipeline (`context_collector.py`, `dash_runner.py`) used
only `log_callback(str)`/`log(str)` with no timestamp, producing
inconsistent console output when both appear in the same GUI log widget
(e.g. during Daily Sync). Purely cosmetic, no functional bug. Implements a
refined version of the two options the roadmap entry weighed: option (a)
(timestamp prefix at the callback) without touching each individual
`log(...)` call site individually — the callback is wrapped once, at
function entry, instead.

**New modules:**
- `log_utils.py` — new Leaf-Node in `src/`, alongside `frozen_paths.py`,
  `crash_handler.py`, `qwebengine_hardening.py`. One function,
  `with_timestamp(log_fn)`: wraps a log callback so every message gets a
  `"%Y-%m-%d %H:%M:%S "` prefix, matching the format `logging.Formatter`
  already uses everywhere else in the project. Pass-through — returns
  `None` unchanged if `log_fn` is `None`, so existing `if log is None:`
  guards in callers keep working without modification.

**Changed modules:**
- `context/context_collector.py` — `run()`: `log_callback` wrapped via
  `log_utils.with_timestamp()` once at function entry — applies to every
  message emitted through the callback without touching the single
  `log_callback(...)` call site itself. New `sys.path.insert()` (reaching
  `src/`, alongside the existing insert for `src/garmin/`) + `import
  log_utils`.
- `dashboards/dash_runner.py` — `scan()` and `build()`: same wrap
  pattern, applied before the existing `if log is None: log = lambda msg:
  None` fallback so the headless no-op path is unaffected. New `sys.path`
  anchor + `import log_utils` — the module previously had zero
  project-module imports.
- `compiler/build_manifest.py` — `log_utils.py` added to `SHARED_SCRIPTS`
  (next to `frozen_paths.py`) and to `SCRIPT_SIGNATURES_BASE`
  (`["def with_timestamp"]`).

**Architecture note:** deliberately not added to `garmin/garmin_utils.py`
despite that module's own "no project-module imports" Leaf-Node
docstring — `dashboards/` has zero project-module imports today by
design (kept independent of `garmin/`), and importing `garmin_utils`
from there would have created exactly the cross-domain dependency the
project avoids elsewhere (see the `clients/` vs. `garmin/` boundary,
v1.6.6). Follows the `frozen_paths.py` precedent instead — a
domain-less Leaf-Node at the `src/` root, importable by any package
without creating a domain dependency.

**Deliberately not touched:**
- `scheduler/daily_update.py` — its headless `dash_runner.build()` call
  already wraps `log=` with `log.info(f"  {msg}")` (the `logging`
  module, timestamped by its own `Formatter`). Wrapping the source as
  well means headless `log/daily/*.log` lines now carry two timestamps
  back-to-back for dashboard-build messages — cosmetic only, never
  visible in the GUI, accepted rather than adding special-case logic to
  strip it.

**Known open item:** verified against `test_local.py` /
`test_local_context.py` / `test_dashboard.py` / `test_app_logic.py` /
`test_qt_app.py` / `test_static.py` (T1/Dev) — a T2/T3 `build_all.py` run
has not yet confirmed `log_utils.py` resolves cleanly via `dash_runner.py`'s
new `sys.path` anchor inside a frozen build (`_load_plotters()` elsewhere
in the same file notes `__file__` can point into a `_MEIPASS` temp path in
T3 — same class of risk, not yet ruled out for this change).

**Test result:** 631 / 265 / 453 / 145 / 46 / 15 — all green, ruff 0
errors, bandit 0 HIGH.

---

## v1.6.6 — In-App Ollama Chat Panel

Native chat panel against a local Ollama instance, directly inside the GUI —
no external tool (Open WebUI/AnythingLLM) required for the existing
Health-Analysis-Prompt exports. Fourth tab ("Ollama-Chat"), non-streaming
requests only (`"stream": false`) — one request/response cycle per message,
fits the existing Worker-Thread + `_dispatch()` pattern without a new
threading concept. Full concept: `docs/KONZEPT_ollama_chat_panel.md`.

**Currently, the chat only works against summary data - full intraday resolution will be added in version 1.9 mcp_map.py.**

**New modules:**
- `clients/__init__.py` — package marker for a new top-level package,
  dedicated to stateless external tool/service clients (no data silo, no
  Sole-Write-Authority) — distinct from `garmin/`'s Garmin-pipeline scope
  and from the `context/`-plugin data-source meaning reserved for v2.0.
  Flat-import style like `garmin/`/`app/`, no `sys.modules` package
  registration (no relative imports inside `clients/`).
- `clients/ollama_client.py` — Leaf-Node. Wraps `POST /api/chat` and
  `GET /api/tags` against `http://localhost:11434`. Typed exceptions for
  all six documented failure modes (unreachable, no models, timeout,
  model not found, context-limit exceeded, generic HTTP error). Known,
  documented trade-off: context-limit detection uses a substring check on
  the HTTP 400 body — Ollama exposes no dedicated status code for this —
  flagged in-code and in `NOTES_v1.6.6.md` as a case for the next
  architecture scan, not a clean finding.
- `app/panel_chat.py` — `PanelChat(QWidget)`, Composition (no Mixin, D-1).
  Status box (context-file age + Ollama reachability + Start button)
  always visible; model dropdown, chat history, input only unlock after
  "Start" — no active chat prep or network traffic beyond a lightweight
  reachability ping on tab-open. "Neuer Chat" resets history + system
  prompt; model switch does the same automatically (different models,
  different context limits). Own design decision, not concept-mandated: a
  failed send removes the just-appended user message from history again,
  so a retry doesn't duplicate it.

**Changed modules:**
- `garmin_app_base.py` — `PanelChat` imported and instantiated
  (`self._panel_chat`), added as fourth tab ("Ollama-Chat", index 3, no
  reindexing of existing tabs). `_on_tab_changed()` gains an `elif index
  == 3` branch — same pattern as the existing Files-tab branch, no new
  tab-change mechanism.
- `garmin_app.py` — `clients/` added to both `sys.path` setup loops
  (frozen + dev). `script_path()` deliberately left untouched —
  `ollama_client.py` is never subprocess-launched.
- `garmin_app_standalone.py` — `clients/` added to the dev-mode loop and
  to `_register_embedded_packages()` (frozen), flat `sys.path.insert`
  alongside `garmin_dir`/`app_dir` — not the `sys.modules` package loop.
- `compiler/build_manifest.py` — new `clients` block in `SHARED_SCRIPTS`
  (`__init__.py` + `ollama_client.py`), `app/panel_chat.py` added to
  `SHARED_SCRIPTS`, both modules added to `SCRIPT_SIGNATURES_BASE`.
- `requirements.txt` — `requests` added explicitly. Cosmetic, not a build
  fix: `RUNTIME_DEPS` and `HIDDEN_IMPORTS_T3_EXTRA` in `build_manifest.py`
  already covered it, `requirements.txt` was the only place missing it.

**What does not change:**
- `dash_plotter_json.py` / `dash_prompt_templates.py` /
  `health_garmin_html-json_dash.py` — unchanged, consumed as-is by the new
  panel (`health_garmin.json` / `health_garmin_prompt.md` age display +
  system-prompt load). Broker layer untouched.
- `daily_update.py` — deliberately not wired to `clients/`; chat is a
  GUI-only feature, never needed headless.

**Found but deliberately not fixed here:**
- Precondition Teil B (Drift-Check) flagged one broad `except Exception`
  in `panel_chat.py::_chat_refresh_age_display` — narrowed to `(OSError,
  ValueError, AttributeError)` in the same session (confirmed by a
  follow-up `dep_map_delta.md` run: broad → ok, clean swap, no
  side-effect). A second flagged handler
  (`ollama_client.py::is_reachable`, tool risk-class "critical") was
  reviewed and left as-is — documented with reasoning in
  `AUDIT_FINDINGS_v166.md` rather than changed.
- Dedicated test coverage for `clients/ollama_client.py` and
  `app/panel_chat.py` — deliberately deferred, own Bewerten-round
  documented in `NOTES_v1.6.6.md`. Decision: no new test file, extend
  `test_app_logic.py` (mocked `requests`, analogous to the existing
  `context_api — fetch (mocked)` section) and `test_qt_app.py`
  (`TestPanelChat`, analogous to `TestPanelOutputs`/`TestPanelTimer`).
  Test depth (smoke-level vs. full worker-thread flows) still open.
- Intraday data in the Ollama chat context (`health_garmin.json` currently
  daily-aggregate only) — roadmap note added, explicitly deferred to the
  v1.9 `mcp_map.py` on-demand query model rather than a static second
  export file, to avoid worsening the context-window problem this session
  just addressed. See `ROADMAP.md`.

**Test result:** 631 / 265 / 453 / 145 / 46 / 15 — all green, ruff 0
errors, bandit 0 HIGH. `dep_map_delta.md` (Precondition Teil B): 1 NEU / 1
WEG / 0 GEKIPPT-Regression against the pre-narrowing baseline of this same
session (broad-exception fix, see above).

**Dependency review (post-release, 2026-08-11):**
- `garminconnect` 0.3.6 → 0.3.9: Breaking changes check performed (no code changed – purely an evaluation triggered by a `check_deps.py` notification).
  Result: low risk. Issue #386 (widget/MFA login strategy) fully resolved with versions 0.3.7+0.3.9. No impact on GLAs used endpoints. The `requirements.txt` file is intentionally unpinned – the update was performed outside the repository (`pip install --upgrade`).
  Details: `NOTES_token_log_observation.md`, commit 3b.

## v1.6.5.11 — Auto-size Rollout (Explorer + Heatmap)

Closes the rollout deferred in v1.6.5.10: the last two of eight dashboard
specialists now use `layouts/dash_autosize.py` instead of a fixed
`date_from → date_to` subtitle. Both needed a small adaptation rather than
a drop-in — their date data isn't a simple `{date: value}` dict like the
original six call sites.

**Changed modules:**
- `dashboards/explorer_garmin-context_html_dash.py` — new `garmin_dates`
  set (Garmin daily fields + sleep phases + sleep score feedback/qualifier,
  filtered to `v is not None`), fed to `compute_autosize_bounds()`/
  `autosize_note()`. Context fields excluded from the boundary, same
  rationale as `health-weather-pollen`/`sleep_recovery_context`. `build()`
  return shape unchanged.
- `dashboards/heatmap_garmin_html_dash.py` — new `_dates_with_data(metric)`
  helper: a metric's padded `dates` list (every requested day gets a row,
  see `_build_metric_matrix()`) filtered down to dates whose matrix row has
  at least one non-`None` value. Pooled (union) across all six metrics
  into `garmin_dates` before the bounds call. Subtitle base case also
  switched from the literal word `"to"` to `→`, matching the other
  seven specialists — incidental to the same line being rewritten, not a
  separate pass.

**What does not change:**
- `layouts/dash_autosize.py` — untouched, both new call sites use the
  existing `compute_autosize_bounds()`/`autosize_note()` signatures as-is.
- No specialist's public `build()` signature or return dict shape changed.
- `layouts/render/heatmap.py` / `layouts/render/explorer.py` — verified via
  DEPS-Scan that neither parses the `subtitle` string; both pass it through
  verbatim to `layout_html.build_header()`. Confirms the subtitle content
  change is safe.

**Known gap found, not fixed this session:** `overview_garmin_xls_dash.py`
builds its `all_dates` set without filtering `v is not None` — unlike the
other seven `dash_autosize` call sites. Since `field_get(resolution="daily")`
pads every requested day with an entry regardless of data presence,
`all_dates` there always equals the full requested range, so its auto-size
call never actually adjusts the boundary. Latent, harmless. See
`docs/REFERENCE_DASHBOARD.md` → `dash_autosize.py` → "Known gap".

**Test result:** 631 / 265 / 453 / 145 / 46 / 15 — all green (1555/1555 total,
`docs/METRICS.md`), ruff/bandit unchanged. `dep_map_delta.md` (Precondition
Teil B): 0 NEU / 0 WEG / 0 GEKIPPT-Regression against v1.6.5.10 baseline.
Netz-2 hash check (`NETZ2_DELTA_v16511_01.md`): all six core modules
unchanged — expected, this session never touched them.

## v1.6.5.10 — Auto-size Helper-Extract

Extracts the auto-size boundary logic — duplicated near-identically across
six dashboard specialists since v1.4.6 — into a shared `layouts/dash_autosize.py`
helper. Pure refactor for five of the six call sites; `health_garmin_html-json_dash.py`
additionally gets a latent bug fix found during the extraction (see below).
Rollout to the two specialists still without auto-size (`explorer_garmin-context_html_dash.py`,
`heatmap_garmin_html_dash.py`) deferred to a separate session — different
underlying data shape (matrix vs. flat series), not a drop-in of this helper.

**New modules:**
- `layouts/dash_autosize.py` — Leaf-Node (stdlib only), analogous to
  `layouts/reference_ranges.py`. Two functions, deliberately separate:
  `compute_autosize_bounds(dates, date_from, date_to)` — pure boundary
  calculation, identical across all six call sites, no text formatting.
  `autosize_note(bounds, date_from, date_to)` — optional formatting helper
  for the recurring `" · adjusted to available data (requested: X → Y)"`
  subtitle fragment. Called by specialists — never by plotters.

**Changed modules:**
- `dashboards/health_garmin-weather-pollen_html-xls_dash.py` — boundary
  calculation + subtitle assembly now via `dash_autosize`. No behaviour change.
- `dashboards/overview_garmin_xls_dash.py` — same.
- `dashboards/sleep_garmin_html-xls_dash.py` — same.
- `dashboards/sleep_recovery_context_dash.py` — same.
- `dashboards/timeseries_garmin_html-xls_dash.py` — same.
- `dashboards/health_garmin_html-json_dash.py` — same, plus bugfix:
  the previous subtitle fragment used `{adjusted_from}` without an
  `or date_from` fallback, unlike the other five specialists. When only
  the end of the range was clipped (`adjusted_to` set, `adjusted_from`
  still `None`), the subtitle rendered the literal text `requested: None →
  ...`. `autosize_note()` closes this — the fallback is now identical
  across all six specialists by construction, not by convention.
- `compiler/build_manifest.py` — `layouts/dash_autosize.py` added to
  `SHARED_SCRIPTS`.

**What does not change:**
- `explorer_garmin-context_html_dash.py`, `heatmap_garmin_html_dash.py` —
  still no auto-size, unchanged, deferred (see above).
- `custom_dash_builder.py` — not evaluated this session.
- No specialist's return dict shape or public `build()` signature changed.

**Test result:** 631 / 265 / 453 / 145 / 46 / 15 — all green, ruff 0 errors,
bandit 0 HIGH.

Closes the deferred `skip_strategies`/retry-lock item from `v1.6.5.2`'s
token-lifecycle analysis — reframed after reading the actual
`garminconnect` source: headless callers (`garmin_collector.py`'s
subprocess and Daily Sync paths) never had an interactive MFA callback to
begin with, so the real risk was a doomed automatic SSO retry on every
subsequent run once an account requires MFA. Fixed with a token-log-based
marker instead of a generic failure counter, plus GUI-side MFA observation
and richer rejection-cause logging found along the way.

**Changed modules:**
- `garmin/garmin_security.py` — new `has_unresolved_mfa_block()`,
  read-side counterpart to `log_token_event()`. Fail-open: unreadable or
  malformed `garmin_token_log.json` → `False` (no block). Scans events
  newest-first; `blocked`/`mfa_required_no_callback` blocks further
  headless SSO until a `created`/`sso_login` event (necessarily
  interactive) appears after it. Deliberately not cleared by
  `clear_token()`/manual reset — a deleted token says nothing about
  whether the MFA problem itself is resolved.
- `garmin/garmin_api.py` — `login()`: new guard before Path 3, active
  only when `on_mfa_required is None` (covers both the headless Daily
  Sync path and the GUI's own background sync subprocess — neither has
  ever had a way to resolve MFA interactively, confirmed via DEPS scan of
  all real `login()` callers). New `_is_mfa_no_callback_error(e)` —
  detects garminconnect's exact `"MFA Required but no prompt_mfa
  mechanism supplied"` message (`client.py::resolve_mfa()`, raised only
  once every login strategy in the 5-strategy chain has required MFA)
  and logs `"blocked"/"mfa_required_no_callback"` instead of falling
  through to the generic failure path. Interactive callers
  (`on_mfa_required` set) now go through a `_logged_mfa_prompt()`
  wrapper that logs `"mfa"/"challenge_presented"` with the
  resolved/cancelled outcome (`solved="yes"|"no"`) in a single entry,
  try/finally so a crash inside the callback itself still gets logged.
  New `_cause_fields(e)` — extracts `e.__cause__` (Python exception
  chaining) for `log_token_event()`'s optional extra fields; applied to
  both existing Path-1 exception sites (`rate_limited`,
  `rejected_by_garmin`). Motivation: `garminconnect`'s
  `_load_profile_and_settings()` masks the real cause behind a fixed
  `"Failed to retrieve social profile"` string after three retries — all
  four historical `invalidated` entries in the token log carried this
  same uninformative detail regardless of the actual underlying failure.
- `tests/test_local.py` — 4 new checks for `has_unresolved_mfa_block()`
  (Section 7), new Section J (6 checks) for the two new pure
  `garmin_api.py` helpers — no live Garmin Connect credentials required
  for either.

**What does not change:**
- No existing function signature changed. `login()`'s callback contract
  (`on_key_required`/`on_token_expired`/`on_mfa_required`/`on_sso_required`)
  is unchanged.
- `garminconnect`'s own native `skip_strategies` attribute (found while
  reading `client.py` for this session) is a separate, unrelated
  mechanism — not used here, scoped to its own roadmap entry
  (`v1.6.6.1`) instead.

**Found but not fixed here:** `panel_timer.py`'s own connection test runs
with `caller="timer_connection_test"` — a seventh value missing from
`REFERENCE_GARMIN.md`'s previous six-value list. Pure doc gap, corrected
in the same documentation pass (see `REFERENCE_GARMIN.md`), not a code
change.

**Test result:** 631 / 265 / 453 / 145 / 46 / 15 — all green (baseline at
session start: 621 / 265 / 453 / 145 / 46 / 15), ruff 0 errors, bandit 0
HIGH.

---

## v1.6.5.8 — Netz 2: Fixtures + Tests, Sessionende-Fixes

Closes the last open item from the `v1.6.5.7` KONZEPT-Reihenfolge — Netz 2
(fixture-based headless functional tests), full scope (all six Class-I
actions from `BESTANDSAUFNAHME_schadensklassen.md`, not just the
Mirror-Container subset originally listed in `KONZEPT_fehlersichtbarkeit_v2.md`).
Diagnosis-first workflow throughout: a non-asserting `gla-netz2/` workshop
(external, not part of this repo) observed each error state against the
real core functions before any assertion was written — avoiding the
v1.6.3.1 failure mode where a test fixture itself was wrongly shaped and
never verified against real data.

**Four priorities diagnosed, two with full regression coverage:**

- **Priority 1 — Mirror-Container + Silo-Repair (#1/#3/#7):** Mirror-Import
  error states turned out already covered by `v1.6.5.7`'s Netz-3-Kandidat-1
  work (wrong password, missing file, junk file, tampered HMAC, unknown
  source) — only a version-mismatch gutfall check was missing, added.
  Silo-Repair's three remaining test gaps (`#1` backfill edge case,
  `#3`/`#7` replay path) closed with real fixtures derived from an actual
  archive file, not invented shapes.
- **Priority 2 — Source-/Steps-Backfill:** the GP-2 integrity gap assumed
  in the original Bestandsaufnahme did not exist — both functions already
  call `record_attempt()` per day (confirmed in `v1.6.5.7`'s own Netz-4
  correction). Actual remaining points: Steps-Backfill's `raw/`/`source/`
  silo-async state on a permanently failing `patch_source_field()` (now
  empirically confirmed, including that the candidate filter correctly
  excludes the day on the next run), and mid-loop abort atomicity for both
  functions (confirmed clean — no partial writes, no corrupted
  `quality_log.json`).
- **Priority 3 — Restore Data:** `restore_raw_days()` had no protection of
  its own against overwriting an already-current, high-quality file with
  an older backup — the only observed protection was an accidental
  side-effect of `write_day()` → `backup_raw()` timing, not a real
  mechanism. Diagnosed, then fixed (see below).
- **Priority 4 — Import Bulk Export:** the suspected `sys.executable`
  subprocess issue (same class as the `v1.6.5.7` trigger) does not apply —
  already fixed years earlier in `v1.3.0b` via delegated entry points.
  Actual finding: `run_import()`'s `ok`/`skipped`/`failed` counting did
  not reflect a day's actual quality outcome. Diagnosed, then fixed (see
  below).

**Three silent-failure fixes, found during diagnosis, closed at session
end:**

**F8 — `assess_quality_fields()` field-level parseability guard:**
- `garmin/quality/_assess.py` — the per-field `"high"` check for
  `heart_rates`, `stress`, `spo2`, `respiration`, `body_battery` required
  only a non-empty intraday array — a structurally malformed array (e.g. a
  flat list instead of `[ts,val]` pairs) still passed, silently degrading
  a derived value (e.g. `avg_bpm`) to `None` while keeping the label
  `"high"`. Now reuses `garmin_normalizer._parse_list_values()` to verify
  the array actually yields parseable values before labeling `"high"`; on
  failure the label falls through the existing tier chain instead of
  staying `"high"` on unusable data. `body_battery` checks whichever of
  its two possible raw-form sources actually holds data (verified against
  a real archived raw file, not assumed).
- `garmin/quality/_maint.py` — new `entry["field_downgrades"]` in
  `quality_log.json`, additive, carries a short per-field reason when a
  downgrade occurred; removed again on a clean re-assessment.
- Found but deliberately not fixed: `raw["body_battery"]`'s top-level
  fallback path (both in `_assess.py` and `garmin_normalizer.summarize()`)
  expects a shape real Garmin data never has — pre-existing, inert,
  independent of this fix.
- Deliberately not retroactive: days already labeled `"high"` under the
  old, incorrect check are not re-assessed by this fix.

**Fix 2 — `restore_raw_days()` own downgrade guard:**
- `garmin/garmin_backup.py` — reads `quality_log.json` directly (same
  pattern as `check_raw_integrity()`, no `garmin_quality` import, avoiding
  the circular import this module deliberately does not have) and skips a
  date into the new `skipped_already_current` return key if a raw file
  already exists for it and its logged quality is already `"high"`.
  Restore Data's original purpose — filling in a genuinely missing file —
  is unaffected; only `"standard"`/no-entry cases are left unblocked.
- `app/panel_archive.py` — `_do_restore()` surfaces the new category in
  its log line.

**Fix 3 — `run_import()` quality-failed counting:**
- `garmin/garmin_collector.py` — a day with `quality: "failed"`
  (deliberately not written, insufficient data) previously counted as
  `"ok"` in the return value, even though `quality_log.json` already
  recorded it correctly. Now counted in `failed`. `main()`'s delegated
  exit code for bulk-import mode follows this more honest count — a GDPR
  export with even one low-quality day now returns exit 1, even if the
  rest imported cleanly (confirmed acceptable, not decoupled).
- Found but deliberately not unified: two structurally identical error
  cases (a missing endpoint for one day) are handled inconsistently — one
  variant drops the day entirely, the other writes it with a gap. Left
  as-is, no unilateral behavior change.

**New/changed test files:**
- `tests/fixtures_netz2.py` — new, laufzeit-generierte Fixture-Generatoren
  für Netz 2, keine eingecheckten Fixture-Dateien (Staleness-Risiko,
  siehe v1.6.3.1). Erste Health-Pipeline-Bausteine, strukturell offen für
  spätere Andockung durch `v1.7.0.1` (FIT) und `v1.8` (Context/Output).
- `tests/test_local.py` — new checks across Sections C/E/E2/I for all four
  priorities plus the three fixes above.

**External tooling, not part of this repo:** `gla-netz2/` — non-asserting
diagnosis workshop, five `run_netz2_*.py` scenario scripts, reports under
`gla-netz2/output/`. `netz2_delta.py` (change-detection for the six Netz-2
core modules, analogous to `build_dep_map.py`'s delta feature) scoped and
deferred to its own session, to avoid growing this one further.

**Test result:** 621 / 265 / 453 / 145 / 46 / 15 — all green (baseline at
session start: 536 / 265 / 453 / 145 / 46 / 15), ruff 0 errors, bandit 0
HIGH.

---

## v1.6.5.7.1 — Token Log: valid Event + Mixed Serialization

Adds the previously missing silent success path to `garmin_token_log.json`
(Path 1 in `garmin_api.py::login()` — token still valid, no SSO needed),
switches serialization to a mixed format: `valid` events collapse to a
single compact line, while all other events (`created`/`invalidated`/
`blocked`) keep the existing multi-line `indent=2` format unchanged, and
adds a `caller` field identifying which of the six login entry points
(GUI Sync, Bulk Import, Daily Sync, Background Timer, GUI Test Connection,
Live Update) produced a given event. A pure observation-layer extension for
the open causality question from `ANALYSE_headless_mfa_login_2026-07-08.md`
— no effect on the login flow itself.

**Changed modules:**
- `garmin/garmin_api.py` — `login()` Path 1: new call
  `garmin_security.log_token_event("valid", "token_reused")` right before
  `return client`, after the successful probe (`get_user_summary()`).
- `garmin/garmin_security.py` — `log_token_event()`: new local
  `_format_event()` — serializes `valid` events compactly
  (`json.dumps(e, separators=(",", ":"))`), all other events still with
  `indent=2`, both forms assembled manually into one shared JSON array.
  New `caller` field, read directly from the `GARMIN_SESSION_LOG_PREFIX`
  ENV var (not `cfg.SESSION_LOG_PREFIX` — the latter is a module-level
  constant computed once at import time and would go stale in T3's shared
  process). Reuses the four values already set for that ENV elsewhere
  (`garmin`, `garmin_bulk`, `garmin_background`, `daily`) at no extra cost.
- `garmin/garmin_live_fetch.py` — `fetch_live()`: sets
  `GARMIN_SESSION_LOG_PREFIX = "live_update"` before its own `login()` call.
  New `import os` (previously unused in this module).
- `app/garmin_app_controller.py` — `check_connection()`'s worker: sets
  `GARMIN_SESSION_LOG_PREFIX = "test_connection"` alongside the existing
  ENV assignments, before its own `login()` call.
- `app/panel_timer.py` — `_timer_loop()`'s one-time connection test: sets
  `GARMIN_SESSION_LOG_PREFIX = "timer_connection_test"` alongside the
  existing ENV assignments, before its own `login()` call.

**Test result:** 536 / 265 / 453 / 145 / 46 / 15 — all green, ruff 0
errors, bandit 0 HIGH.

---

## v1.6.5.7 — T3.1 Silent-Failure Investigation (Netz 0/1/3/4 + Silo-Repair-Kern-Extraktion)

Trigger: `_on_silo_repair()`'s repair path #3 called
`subprocess.run([sys.executable, ...])` directly — in any frozen build,
`sys.executable` is the EXE itself, not a Python interpreter. Found while
tracing P1-07 (v1.6.5.5). Investigated via a three-net concept: Netz 1
(module loadability self-test), Netz 3 (error audibility for the four
highest-risk write paths), Netz 4 (crash-resilience for quality_log.json
writes), Netz 0 (static-analysis regression guards) — Netz 2
(fixture-based headless functional tests) split off as its own arc,
`v1.6.5.8`. Session 1's architecture decision: `silo_repair` gets a real
headless-callable core (`garmin_silo_repair.py`) rather than staying a
GUI-T2-only limitation.

**Changed modules — Netz 1 (Laufzeit-Selbsttest):**
- `garmin_app_standalone.py` — new `_run_self_test()`, called via
  `--self-test` before any GUI initialisation. Loads every module in
  `build_manifest.SHARED_SCRIPTS` directly from disk via
  `importlib.util.spec_from_file_location()` — the same technique already
  used by `dash_runner._load_specialist()`. Exercises the real runtime
  import machinery, not a parallel one. `_import_family_submodule()`
  handles the two coexisting import conventions for `app/`, `context/`,
  `maps/`, `dashboards/`, `layouts/` (flat vs. package-qualified for the
  six `panel_*.py` files and `dialogs.py`) — tries flat first, falls back
  to dotted, found via a real self-test run rather than assumed. `_out()`
  is a best-effort console print (never raises — `--windowed` builds may
  have no usable `sys.stdout`), independent of the actual pass/fail signal
  (`failures` list + return code).
- `compiler/build_all.py` — self-test wired into the build gate (Session 1
  Schritt 3).

**Changed modules — Netz 3 (Fehler-Hörbarkeit, vier Kandidaten):**
- **Kandidat 1 — Mirror-Import:** `garmin_import_mirror.py` — `run_import_mirror()`
  and `mirror()` gain an `error` field on hard-stop failures (unrecognised
  source, `unlock_meta()` failure, unreadable `mirror_meta.json`/quality_log)
  — absent when `ok=False` comes from per-item errors during processing
  instead, which are individually logged and counted. `garmin_mirror.py`
  — same `error` field when the mirror cannot start at all (missing
  source directory). `app/panel_archive.py` — dry-run failures show the
  actual cause instead of a generic "check log for details"; the live-run
  message now shows ✓/⚠/✗ depending on outcome instead of always ✓.
- **Kandidat 2 — Backup/Restore:** `garmin_backup.py` — three previously
  silent `except: pass`/bare-except handlers now log
  (`_consolidate_log_years`, the unreadable-raw-file branch in
  `check_raw_integrity`, `check_raw_backfill_needed`); `restore_raw_days()`
  gains an `errors: dict[str, str]` (date → reason) alongside the existing
  `failed` list; `check_raw_integrity()` gains an `error` field for when
  the check itself could not complete (e.g. unreadable quality_log), kept
  distinct from "checked, nothing missing". `app/garmin_app_controller.py`
  — `check_integrity()` passes the new `error` field through instead of
  swallowing every failure into empty lists. `app/panel_archive.py` — the
  startup integrity check logs a failed check explicitly instead of
  looking identical to a clean archive; the restore-data flow lists each
  failed date's reason (capped at 10, with a count for the rest).
- **Kandidat 3 — Security:** `garmin_security.py` — `log_token_event()`'s
  `version.py` import fallback now logs at debug; new
  `get_enc_key_status()` is the sole WCM-read implementation, returning
  `(key, None)` on success/genuine absence or `(None, error_detail)` on a
  WCM read failure — `get_enc_key()` becomes a thin wrapper kept for its
  five existing presence-only callers; `clear_token()` now returns `bool`
  instead of `None`. `app/panel_connection.py` — `_reset_token()` surfaces
  an incomplete `clear_token()` instead of always claiming success.
  `app/garmin_app_controller.py` — connection check distinguishes "key
  genuinely absent" from "WCM read failed", with the specific reason in
  the log line. `garmin_api.py` — a failed `store_enc_key()` or
  `save_token()` now logs a warning instead of silently proceeding as if
  the token were safely persisted.
- **Kandidat 4 — Writer:** `garmin_writer.py` — `read_summary()` now logs
  a missing-file case the same way `read_raw()` already did.
  `garmin_collector.py` — the schema-migration loop logs when a day is
  skipped for having no summary file at all, instead of silently
  continuing.

**Changed modules — Silo-Repair-Kern-Extraktion (KONZEPT-Schritt 5, Blocker):**
- `garmin/quality/_maint.py` — new `is_downgrade()`, the canonical
  downgrade-rank comparison, re-exported via `garmin_quality.py`. Replaces
  duplicated logic in `garmin_collector.py::_check_downgrade()` and
  `export/regenerate_raw.py`'s `_rank()`/`_existing_label()` pair — both
  now call the shared helper (sibling-sweep finding).
- `app/panel_archive.py` — repair path #3 (source without raw) rewritten
  in-process (`normalize()` → `summarize()` → `assess_quality()` →
  `write_day()` → `record_attempt()`), replacing the `subprocess.run([sys.
  executable, ...])` call that triggered this whole investigation. A
  missing `garmin_quality` import introduced during this rewrite was
  caught and fixed in the same session (F-823-style scan finding).
- **New module `garmin/garmin_silo_repair.py`** — `repair_silos(fresh:
  dict) -> dict`, headless-callable, Qt-free. Holds the four repair
  categories (#1/#3/#5/#7) that previously lived only as a Qt-bound
  closure inside `panel_archive.py::_on_silo_repair()`, with no entry
  point callable without a live `PanelArchive`/`QApplication` instance.
  This supersedes the v1.6.0.4.7 decision ("Repair stays in
  `panel_archive` and delegates to existing owners") — a deliberate
  architecture change, not an oversight; that decision predates the T3.1
  headless-callable-core requirement. `panel_archive.py::_do_repair()` now
  only formats the structured result for the GUI log.
- `compiler/build_manifest.py` — `garmin_silo_repair.py` added to
  `SHARED_SCRIPTS` and `SCRIPT_SIGNATURES_BASE`.

**Changed modules — Netz 4 (Umsetzung, GP-2-Muster + Steps-Backfill-Retry):**
- `garmin_collector.py::run_import()` and
  `garmin_import_mirror.py::run_import_mirror()` (both the container path
  and the deprecated folder fallback) now persist `quality_log.json` after
  every processed day (`skip_backup=True`), not only once after the whole
  batch — matching `main()`'s existing per-day pattern. A bulk import or
  mirror import aborted mid-run no longer leaves already-written raw
  files invisible to `quality_log.json`. `_run_source_backfill()` and
  `_run_steps_backfill()` already had this pattern via `record_attempt()`
  — confirmed by reading the current files, not assumed from the original
  KONZEPT Bestandsaufnahme, which had over-counted this as four affected
  functions instead of two.
- `garmin_collector.py::_run_steps_backfill()` — one automatic retry for a
  failed `patch_source_field()` call; logs at `error` level (not
  `warning`) if the retry also fails, since `source/` will not be
  auto-retried on a future run (the candidate filter checks `fields` from
  `raw/`, which is already correct after `write_day()`).

**Changed modules — Netz 0 (vier neue Regeln in `tests/test_static.py`):**
- SHARED_SCRIPTS-Manifest-Vollständigkeit, bidirektional: jeder gelistete
  Pfad existiert; jede `.py`-Datei in den vollständig erfassten Ordnern
  (`app`, `garmin`, `garmin/quality`, `context`, `maps`, `dashboards`,
  `layouts`, `layouts/render`, `export`) ist gelistet, mit einer
  Ausnahmeliste für bewusst nicht gebaute Dev-/Maintenance-Skripte
  (`export/backfill_source_backup.py`, `export/backfill_source_intraday.py`,
  `export/regenerate_summaries.py`, `garmin_app_screenshot.py`).
- AST-basierter Regressions-Wächter für stille `except: pass`-Handler in
  den vier Netz-3-Kandidatenmodulen, mit gemessener Baseline statt
  Nullforderung (5/0/0/2).
- Verbotene Importmuster: Leaf-Node-Invariante für `garmin_utils.py` und
  `garmin_validator.py` (mit dokumentierter Ausnahme `garmin_config` für
  Letzteres — steht in dessen eigenem Docstring); Lazy-Import-Pflicht für
  `garmin_config` in `garmin_security.py`.
- AST-basierter Regressions-Wächter für `spec_from_file_location`-Fundstellen
  in `SHARED_SCRIPTS`, Baseline 10 (alle mit berechnetem statt
  literalem Zielpfad — echter Manifest-Abgleich bereits über die erste
  Regel abgedeckt).

**Precondition-Fix (vor der Doku-Kette gefunden, nicht Teil der ursprünglichen
KONZEPT-Liste):**
- `garmin_silo_repair.py::repair_silos()` — Kategorie #3 hielt
  `QUALITY_LOCK` nur für den initialen Load, gab ihn danach frei und
  re-acquired ihn nur pro Tag für den jeweiligen `record_attempt()`-Save.
  Ein konkurrierender `quality_log`-Schreiber in diesem Fenster hätte
  seine Änderungen durch die veraltete In-Memory-Kopie dieser Schleife
  überschrieben bekommen — gefunden während der Architektur-Precondition,
  nicht während des ursprünglichen Bauauftrags. Jetzt ein durchgehender
  Lock-Hold für den gesamten Load-Modify-Save-Zyklus, wie überall sonst in
  der Pipeline (`main()`, `run_import()`, `_run_source_backfill()`,
  `_run_steps_backfill()`, sowie Kategorie #1 direkt daneben in derselben
  Datei).
- `template/build_dep_map/build_dep_map_config.py` /
  `build_dep_map.py` (GLA-NeedfulThings, nicht Teil dieses Repos) — neue
  `ACCEPTED_GEKIPPT`-Whitelist für zwei Fälle, in denen die
  Klassifikations-Heuristik (nur `raise`/Reraise gilt als „ok") ein
  bewusst gewähltes Muster — Fehler über strukturierten Rückgabewert statt
  Exception — fälschlich als Regression einstuft. Bleibt im Delta-Report
  sichtbar, zählt aber nicht mehr in die Blocker-Summe.

**Found but deliberately not fixed here:**
- Testlücken in `garmin_silo_repair.py` — #1 fehlt
  (`_backfill_quality_log()`s interner Kontrakt nicht gelesen), #3/#7
  fehlen (bräuchten eine `normalize()`-taugliche Rohdaten-Fixture).
  Kandidat für `v1.6.5.8` (Netz 2).
- `main()`'s Fetch-Loop: `record_attempt()` (löst bereits einen Backup pro
  Tag aus) gefolgt von einem expliziten
  `_save_quality_log(..., skip_backup=True)` sieht nach doppeltem Save pro
  Tag aus — nur vermerkt, nicht untersucht.
- `_run_steps_backfill()`s Retry deckt nur transiente
  `patch_source_field()`-Fehler ab. Eine dauerhafte Lösung (feldbasierte
  Candidate-Erkennung statt reiner `fields`-Prüfung) bräuchte
  `garmin_app_controller.py` — eigener Bauauftrag, nicht Teil dieser
  Session.
- P3-03-Verifikation (Dashboard-Tab + XLSX-Preview im T3.1-Build öffnen),
  `os.environ`-Mutation in Worker-Threads (Finding F5, 13 Stellen),
  `panel_archive.py::_clean_archive()` (toter Code), fehlender
  `layouts/render/heatmap.py`-Signatureintrag in `build_manifest.py`, und
  `scheduler/daily_update.py`'s `crash_handler.install()`-Adoption — alle
  ursprünglich für diese Session vorgesehen, nicht angefasst, laut NOTES
  weiterhin offen. Verschoben zu `v1.6.5.8`.

**Test result:** 536 / 265 / 453 / 145 / 46 / 15 — all green, ruff 0
errors, bandit 0 HIGH.

---

## v1.6.5.6 — Intraday Timestamp Timezone Bug

Intraday series timestamps were rendered in GMT/UTC instead of the recording
device's local time, across two independent code paths inside `garmin_map.py`.
Fixed by deriving the device's UTC offset from each day's own archived
GMT/Local timestamp metadata — no `zoneinfo`, no system clock — with
DST-transition days detected and flagged rather than silently mis-rendered.

**Changed modules:**
- `maps/garmin_map.py` — new `_OFFSET_SOURCE_SECTIONS`, `_parse_naive()`,
  `_section_offset()`, `_device_offset()`: derives the day's device UTC
  offset from the first available section's `startTimestampGMT/Local` +
  `endTimestampGMT/Local` pair (priority `heart_rates → stress →
  respiration → spo2`), and flags `dst_transition` when start-of-day and
  end-of-day offset differ. `_ts_to_iso()` and `_extract_series()` gained
  an `offset_hours` parameter (default `0.0`, backward compatible);
  timestamps stay naive (no offset suffix) — Plotly's `xaxis:
  {type:'date'}` would otherwise reapply the browser's own timezone and
  reintroduce the bug one layer up. `_read_intraday()` / `_read_live()`
  now compute the offset once per file and add `dst_transition: bool` to
  every `values` entry in the intraday/live response contract. Root
  cause: the five array-based series (`heart_rate_series`,
  `stress_series`, `spo2_series`, `body_battery_series`,
  `respiration_series`) never actually read `"ts_key": "startGMT"` (dead
  configuration — `ts_index` is set, so `_extract_series()`'s dict-branch
  was unreachable); `steps_series` used the dict-branch and inherited the
  same UTC bug through a different mechanism.
- `layouts/dash_layout.py` — new `TIME_BASIS_NOTE` constant +
  `get_time_basis_note()` getter, alongside `DISCLAIMER`/`FOOTER`.
- `layouts/dash_layout_html.py` — `build_header()` gained an optional
  `time_basis_note` parameter (default `None`, backward compatible);
  renders as an extra `<p class="time-basis">` line when provided. New
  `.time-basis` CSS rule.
- `layouts/render/heatmap.py`, `layouts/render/sleep.py`,
  `layouts/render/recovery_context.py` — pass
  `dash_layout.get_time_basis_note()` into `build_header()`.
- `layouts/render/live.py` — own dark-theme markup line for the same note
  text (this renderer never used `dash_layout_html.build_header()` — see
  module docstring), sourced from the same getter.
- `tests/test_dashboard.py` — 8 new checks: offset shift on a synthetic
  day with real GMT/Local metadata (epoch-ms and GMT-string paths both),
  `dst_transition` detection on 2026-03-29 (real EU spring-forward date)
  with the series still using the start-of-day offset, `dst_transition =
  False` fallback on a day with no offset metadata at all, and two
  `dst_transition`-key checks added to the Broker-Contract section.

**Found but deliberately not fixed here** (see `docs/NOTES_v1656.md` for
full detail):
- `context/context_api.py`'s hourly-to-daily aggregation was checked as
  part of the sibling-sweep — confirmed unaffected, both Open-Meteo and
  Brightsky requests specify localized timestamps at the API level
  (`timezone: "auto"` / `tz: "Europe/Berlin"`).
- `garmin_utils.py::parse_device_date()` uses the same UTC-epoch-to-string
  pattern via the deprecated (Python 3.12+) `datetime.utcfromtimestamp()`
  — a day-level sibling of this bug, out of this session's scope, carried
  to ROADMAP.
- Duplicate intraday chart code between `layouts/render/recovery_context.py`
  and `layouts/dash_plotter_html_complex.py` (M-2 pattern) — found during
  the sibling-sweep, unrelated to the bug itself.
- Timestamp-metadata field naming drift (`Z`-suffixed UTC strings vs.
  naive `datetime.now()`) across five write-time-stamping modules —
  cosmetic, carried to ROADMAP.

**Also in this session (out of original scope, approved ad hoc):**
`MAINTENANCE_CONTEXT.md`, `MAINTENANCE_DASHBOARD.md`, and the three
`MAINTENANCE_GLOBAL.md` sections for `test_local.py` /
`test_local_context.py` / `test_dashboard.py` no longer restate hardcoded
"Current count: N checks" numbers — brought in line with the convention
`MAINTENANCE_GARMIN.md` already used, after the count mismatch this
session's own doc updates produced (445 vs. 453) surfaced the duplication
risk directly. `docs/METRICS.md` is now the single stated source for these
three files too; `tools/doc_guard.py` required no change — it already
treats an absent count line as `no_count_claimed`, not drift.

**Test result:** 498 / 261 / 453 / 145 / 46 / 4 — all green, ruff 0
errors, bandit 0 HIGH.

---

## v1.6.5.5 — Hidden-Import Consolidation + Test + P1-07

Closes P3-02, P7-03, and (as a bonus, combined with P7-02) P7-01 from the
v1.6.5.2 standalone-parity audit (`docs/AUDIT_FINDINGS_standalone_parity_v1652.md`),
plus P1-07 in a deliberately narrow scope. Order was binding: consolidation
before test, since a test against a still-duplicated list would have tested
the wrong target.

**Changed modules:**
- `compiler/build_manifest.py` — new `HIDDEN_IMPORTS_COMMON` (19 entries,
  needed by the GUI build T2, Python required on target) and
  `HIDDEN_IMPORTS_T3_EXTRA` (10 entries, only needed by T3's full embed —
  `openpyxl.styles/chart/utils`, `cryptography` + three submodules,
  `requests`, `lxml` + `lxml.etree`). Deliberately not a single merged
  list: a fresh diff showed `build.py`'s 19 entries are already a full
  subset of `build_standalone.py`'s current 29 — merging them would give
  T2 ten unverified hidden-imports it has never needed, an unrelated
  behaviour change outside this session's scope. Also new: `embed_dest()`
  (see below) — new `SHARED_SCRIPTS` entry `export/regenerate_raw.py`
  (P1-07, see below).
- `compiler/build.py` — the 19 literal `--hidden-import` pairs in
  `build_exe()`'s `cmd` list replaced by a loop over
  `manifest.HIDDEN_IMPORTS_COMMON`. Identical resulting PyInstaller
  command.
- `compiler/build_standalone.py` — the 29-entry literal `hidden` list in
  `build_exe()` replaced by `manifest.HIDDEN_IMPORTS_COMMON +
  manifest.HIDDEN_IMPORTS_T3_EXTRA`. New function `embed_dest(subfolder)`
  — single source of truth for the `--add-data` destination path under
  `scripts/`, used both by `build_exe()` itself (for `EMBEDDED_SCRIPTS`
  and `REQUIRED_DATA_FILES`) and imported directly by
  `tests/test_build_output.py` §8 (P7-02) instead of being reconstructed
  there as a private, drift-prone copy.
- `tests/test_build_output.py` — §1: seven new checks guarding
  `HIDDEN_IMPORTS_COMMON`/`_T3_EXTRA` against silent drift (not empty, no
  internal duplicates, no overlap between the two lists, and the four
  known lazy deps — `curl_cffi`, `curl_cffi.requests`, `ua_generator`,
  `openpyxl.cell._writer` — explicitly present in `HIDDEN_IMPORTS_COMMON`).
  Closes P7-03: previously no test asserted anything about the
  hidden-import lists at all. §8: now imports `embed_dest` from
  `build_standalone` instead of reconstructing the destination logic
  locally (P7-02); the `REQUIRED_DATA_FILES` check that used to be a bare
  `check(..., True)` tautology (P7-01) now asserts the real computed
  destination equals the expected `scripts/{subdir}` path. P7-01 could not
  be fixed independently of P7-02 — `REQUIRED_DATA_FILES`'s destination
  has no non-trivial transform of its own to test against; the file's
  existence is already verified in §2, so the only meaningful fix was
  testing against the real function.
- `compiler/build_manifest.py` — P1-07: `export/regenerate_raw.py` added
  to `SHARED_SCRIPTS`. It is called via `subprocess` from
  `app/panel_archive.py::_on_silo_repair()` but was entirely missing from
  the manifest, so T2's `prepare_scripts_dir()` never copied it to
  `scripts/export/` — Silo-Repair finding #3 (source without raw) would
  fail against a built T2 EXE. Verified via a real `build_all.py` run:
  `scripts/export/regenerate_raw.py` now present in the T2 `scripts/`
  folder and ZIP, and embedded in T3.

**Found but deliberately not fixed here:**
- While tracing P1-07, `_on_silo_repair()`'s repair path was found to use
  `subprocess.run([sys.executable, str(regen_script), ...])` directly,
  bypassing the established `_find_python()` pattern `garmin_app.py` uses
  elsewhere for exactly this reason. In a frozen build, `sys.executable`
  is the EXE itself, not a Python interpreter — the call cannot work as
  written in either T2 or T3. Worse for T3: `garmin_app_standalone.py` has
  no subprocess execution model at all (`_run_module()` uses `importlib`
  in-process) — this is the concrete architecture gap already flagged as
  "`silo_repair` has no headless-callable core" for the T3.1
  silent-failure investigation. Fixing it here would have pre-empted that
  investigation's own Netz 1–3 work without using it; fed into that
  investigation instead, not fixed in this session.
- P7-01/P7-02 optional split (per the session prompt) — done together, see
  above; treated as one combined change rather than two independent ones.

**Test result:** 498 / 261 / 445 / 4 — all green, ruff 0 errors, bandit 0
HIGH. `test_build_output.py`: 679 / 679 after a full `build_all.py` run
(T2 + T3, both verified). `test_app_logic.py`: 145 / 145.

---

## v1.6.5.4 — Frozen-Path Centralization

Closes P1-01, P1-02, P1-04 from the v1.6.5.2 standalone-parity audit
(`docs/AUDIT_FINDINGS_standalone_parity_v1652.md`), plus a fifth,
previously unlisted finding (P1-05) that surfaced while re-reading
`_run_live_fetch()` for this session. Five deliveries, each independently
verified — the isolated bug fix (P1-05) shipped before the six-site
sweep, so the new helper had a real proof point before being applied
everywhere else.

**New modules:**
- `frozen_paths.py` — new Leaf-Node in `src/`, alongside `crash_handler.py`
  and `qwebengine_hardening.py`. Three deliberately separate functions:
  `scripts_root()` (seiteneffektfrei, canonical T2/T3 distinguisher —
  checks `dash_runner.py` under `scripts/dashboards/`, not just `scripts/`
  itself, resolving the P1-02 doc-drift against `MAINTENANCE_GLOBAL.md`),
  `add_to_path(root, *subs)` (explicit `sys.path` mutation, kept separate
  since one call site needs the root without any path insertion),
  `doc_path(filename)` (mirrors `compiler/build.py::prepare_scripts_dir()`'s
  three-step search chain: repo root → `src/docs/` → `src/scheduler/`).

**Changed modules:**
- `compiler/build_manifest.py` — `frozen_paths.py` added to `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.
- `app/panel_outputs.py` — P1-05: `_run_live_fetch()` had no frozen branch
  at all (`root = Path(__file__).parent.parent` unconditionally) — broke
  silently in T3 (`ℹ Live Tracking update skipped: ...`). Verified broken,
  then fixed via `frozen_paths.scripts_root()` in an actual T3 build (log
  now shows `✓ Live Tracking updated`) before touching any other call site.
  P1-01/P1-02: all six copies of the non-centralized 3-way root branch
  (Context-Sync, Create Reports, Encrypted Export, Custom-Dashboard-Encrypt,
  Custom-Dashboard-Encrypted-ad-hoc, All-Dashboards) replaced with
  `frozen_paths.scripts_root()` + `frozen_paths.add_to_path()`. Three
  different loop-variable names (`s`/`sp`/`_s`) across the copies — itself
  evidence of the drift P1-01 described — removed along with the
  duplication. One site (`_run_custom_dashboard_encrypted`) never added to
  `sys.path` in the original; that difference is preserved, not
  harmonized. P1-04: README-link lookup (bug fix — dev-mode fallback used
  `Path(__file__).parent / "docs"`, resolving to `src/app/docs/` instead of
  `src/docs/`; link was silently dead in T1) and Task-Scheduler-XML
  template lookup both replaced with `frozen_paths.doc_path()`. A follow-up
  correction restored a locally-scoped `_exe_dir` variable inside
  `_create_task_scheduler_xml()` that is still used by `_default_path()`
  for T2/T3 entry-point defaults — unrelated to the doc lookup, missed on
  first read of the function.
- `app/panel_home.py` — P1-04: `_home_docs_dialog._open()`'s two-way
  branch (no fallback chain) replaced with `frozen_paths.doc_path()` —
  gains the same three-step chain as the other two sites. Was previously
  the only hard frozen-branch without a candidate list (audit note).
  `import sys` removed (dead after the replacement).
- `docs/AUDIT_FINDINGS_standalone_parity_v1652.md` — P1-01, P1-02, P1-04,
  P1-05 marked resolved.

**What does not change:**
- `garmin_app.py` / `garmin_app_standalone.py` — their own `script_dir()`/
  `script_path()` helpers are a different root concept (point at
  `garmin/` in dev mode, not the project root) and were deliberately left
  untouched — no scope creep onto functioning code.
- `dashboards/dash_runner.py::_load_plotters()` and
  `layouts/dash_plotter_html_complex.py` — both use `__file__`-relative
  resolution within their own package boundary, a structurally different
  and already-safe case. Reviewed, not touched.
- `scheduler/daily_update.py::_setup_paths()` — reviewed as a sibling,
  left as its own, already-consistent implementation.

**Test result:** 1399 / 1399 — all green (498 + 261 + 445 + 145 + 46 + 4),
test_build_output 665 / 665, ruff 0 errors, bandit 0 HIGH.

---

## v1.6.5.3 — Standalone Parity: Quick Fixes

Four independent, low-risk fixes from the v1.6.5.2 standalone-parity audit
(`docs/AUDIT_FINDINGS_standalone_parity_v1652.md`), each confined to its own
file. No shared scope between them — each shipped as its own anchor and
verified independently.

**Changed modules:**
- `compiler/build_standalone.py` — four hidden-import entries missing
  against `build.py` (T2) added to the `hidden` list: `curl_cffi`,
  `curl_cffi.requests`, `ua_generator` (garminconnect transport, lazy
  imported by the library itself), `openpyxl.cell._writer` (Excel write
  internals). Build-breaking in the sense that `ImportError` on these four
  only surfaces at runtime — on the first real API call or the first `.xlsx`
  export — never in the PyInstaller build log. Verified via a real T3 build
  with an actual Garmin login/sync and four Excel-format dashboard exports;
  both succeeded.
- `compiler/build_manifest.py` — five package `__init__.py` files were
  present on disk but missing from `SHARED_SCRIPTS`
  (`context/`, `dashboards/`, `garmin/`, `layouts/`, `maps/` — only
  `app/__init__.py`, `garmin/quality/__init__.py`, and
  `layouts/render/__init__.py` were listed). All eight are code-free;
  decision was to list all eight rather than leave the omission
  undocumented, since `build_manifest.py` is the single source of truth for
  script lists. `SCRIPTS`, `EMBEDDED_SCRIPTS`, `ALL_SCRIPTS` update
  automatically (all three are derived from `SHARED_SCRIPTS`).
- `garmin_app_base.py` — removed `_find_script()`, dead code confirmed via a
  project-wide reference scan (exactly one match: the definition itself, no
  callers). Removing it left `import sys` unused (`sys.executable` was its
  only use in the file) — removed in the same fix, caught by the
  `test_static.py` ruff gate before the build proceeded.
- `docs/MAINTENANCE_GLOBAL.md` — documented that `daily_update.py`
  intentionally has no equivalent to the GUI Timer's maintenance modes
  (`repair`, `quality`, `fill`, `source_backfill`, `steps_backfill`,
  `bulk_recheck`, `check_integrity`). Same reasoning already applied to
  excluding `_run_live_fetch()` from headless (v1.6.5): these are
  interventions on the archive that benefit from someone watching and able
  to abort.

**Not in scope (deferred):**
- Frozen-path centralization (P1-01, P1-02, P1-04) — v1.6.5.4.
- Hidden-import consolidation + tests (P3-02, P7-01–03) — v1.6.5.5.
- `garmin_map.py` / `startGMT` timezone bug — v1.6.5.6.
- New finding surfaced during T3 verification: `dash_runner.py` path
  resolution fails in the frozen Standalone EXE (`_internal/dashboards/
  dash_runner.py` not found, Live Tracking update silently skipped) — same
  category as the deferred frozen-path work, logged in
  `docs/AUDIT_FINDINGS_standalone_parity_v1652.md` for v1.6.5.4, not fixed
  here.

**Test result:** 1399 / 1399 — all green (498 + 261 + 445 + 145 + 46 + 4),
test_build_output 656 / 656, ruff 0 errors, bandit 0 HIGH.

## v1.6.5.2 — Token Lifecycle Log

Observation-only addition, triggered by an unresolved MFA login failure in the
headless path (analysis: `ANALYSE_headless_mfa_login_2026-07-08.md`). Before
deciding whether to throttle the login cascade, actual token lifetime needed
to be measurable instead of guessed. No existing behaviour changes — four new
log calls at already-existing call sites, one new observation-only file.

**Changed modules:**
- `garmin/garmin_security.py` — new function `log_token_event(event, trigger,
  **extra)`, sole write authority for the new `garmin_token_log.json` (in
  `LOG_DIR`). Best-effort, catches all exceptions internally — a logging
  failure must never affect the login flow. Records only metadata (timestamp,
  event/trigger type, `app_version`, exception type name, truncated detail
  string) — no credentials, no token content. `save_token()` calls it on
  success (`"created"`, `"sso_login"`).
- `garmin/garmin_api.py` — `login()`: three new call sites. Path 1 rate-limit
  branch logs `"blocked"`/`"rate_limited"` (token is deliberately *not*
  deleted there, kept separate from `"invalidated"` to avoid skewing
  lifetime analysis). Path 1 genuine rejection logs `"invalidated"`/
  `"rejected_by_garmin"`. Path 3b (encryption key missing from WCM) logs
  `"invalidated"`/`"enc_key_missing_wcm"`.
- `app/panel_connection.py` — `_reset_token()` logs `"invalidated"`/
  `"manual_reset"`.

**What does not change:**
- No existing function signature or return value changed.
- No new dependency, no `build_manifest.py` entry needed — no new module,
  only additions inside three already-listed files.
- `skip_strategies` / retry-lock on the login cascade — considered during
  this session's analysis, deliberately deferred, not implemented here (see
  `ANALYSE_headless_mfa_login_2026-07-08.md`, Section 6).

**Test result:** 1399 / 1399 — all green (498 + 261 + 445 + 145 + 46 + 4),
ruff 0 errors, bandit 0 HIGH.

## v1.6.5.1 — Live Tracking Follow-ups

Three follow-ups to the v1.6.5 Live Tracking Dashboard, all confined to
`garmin_live_fetch.py` and `panel_outputs.py`. Live-fetch connection-status
indicators — the app-wide Token/Login/API Access/Data dots didn't react at
all when triggered via `fetch_live()` (only via the Daily Sync path).

**Changed modules:**
- `garmin/garmin_live_fetch.py` — new optional `state_cb(key, state)`
  parameter on `fetch_live()`, default no-op (backward compatible). Fires
  token/login right after login succeeds or fails. Fires api/data via a
  lightweight probe (`client.get_user_profile()` / `client.get_stats(today)`)
  immediately after login — same probe pattern as
  `garmin_app_controller.check_connection()` — instead of waiting for the
  full ~30-60s, 8-endpoint fetch to complete. Probe result is independent of
  the endpoint loop's own `failed_endpoints` tracking.
- `app/panel_outputs.py` — `_run_live_fetch()` wires `state_cb` into the
  same `self._app._dispatch(...)` pattern already established in
  `panel_timer.py` for background-thread → GUI updates. No new dispatch
  mechanism introduced.

**Test result:** 1399 / 1399 — all green (498 + 261 + 445 + 145 + 46 + 4).

## v1.6.5 — Live Tracking Dashboard

Adds an always-current snapshot dashboard — today's intraday progression
(Body Battery, Heart Rate, Steps, Stress) plus last night's sleep summary,
refreshed automatically after every GUI Sync Garmin and on demand via a new
"Update Live" button. Introduces a new, lightweight live-fetch path
alongside the existing daily archive pipeline — deliberately separate, no
shared file access, no shared write authority.

**New modules:**
- `garmin/garmin_live_fetch.py` — Worker, sole write authority over
  `garmin_data/live/live.json`. Fetches sleep + HRV + all six intraday
  endpoints for the current calendar day via the existing `garmin_api`
  (reused login/api_call, no second auth path, no own 429 handling).
  Single-file snapshot, no history, overwritten on every fetch. Optional
  `progress` callback for GUI-visible fetch progress (deliberately not
  named `log` — the module already has a `log = logging.getLogger(...)`
  a same-named parameter would shadow).
- `dashboards/live_tracking_html_dash.py` — Specialist. Fetches exclusively
  via `field_map.get(..., resolution="live")`. Precedence rule for the
  sleep block: a single representative field (`sleep_score`) decides the
  source — falls back to the full archive block if live is unavailable,
  never mixes live and archive data for the same night. Steps summed as a
  cumulative counter, not read as a single intraday point.
- `layouts/render/live.py` — Render module for the new `"live"` layout key.
  Deliberately diverges from the shared renderer pattern: dark theme
  matching the app's own palette (not the shared light-theme dashboard
  CSS), no Plotly (inline SVG sparklines — four small charts don't justify
  the full bundle), self-built header/disclaimer/footer markup (disclaimer
  text still sourced from `dash_layout.get_disclaimer()`, only its wrapper
  markup is local).

**Changed modules:**
- `garmin/garmin_config.py` — `LIVE_DIR` / `LIVE_FILE` path constants,
  analogous to the existing `SOURCE_DIR` pattern.
- `maps/garmin_map.py` — new `resolution="live"` value, bypasses the
  daily/intraday fallback logic entirely (analogous to the existing
  `raw_pct` bypass). Three new internal descriptor types: `"live"`
  (intraday series, six fields), `"live_pct"` (percentage math against the
  live snapshot, four sleep-phase fields), `"live_nested"` (dotted-path
  lookup with an optional fallback chain and optional divisor, five
  fields: `hrv_last_night`, `sleep_score`, `sleep_score_feedback`,
  `sleep_score_qualifier`, `sleep_duration`). Missing `live.json` or
  missing field → `fallback=True`, empty values, never an exception.
- `layouts/dash_plotter_html_complex.py` — one `_REGISTRY` entry for the
  new `"live"` layout key, same pattern as the Heatmap dashboard. No
  change to existing dispatch logic.
- `app/panel_outputs.py` — `_run_collector()`'s `_internal_done()` now
  fires `_run_live_fetch()` after every GUI Sync Garmin (headless
  `daily_update.py` deliberately excluded — a headless run has no one
  watching a "live" view). New method `_run_live_fetch()`: background
  thread, fetches, builds only the Live Tracking specialist via the
  regular `dash_runner.scan()`/`build()` path, then auto-loads it into the
  dashboard viewer. Fire-and-forget — any failure is logged and swallowed,
  never affects the rest of the sync chain.
- `app/panel_home.py` — new "Update Live" button, next to "Daily Sync".
  Handler calls the same `panel_outputs._run_live_fetch()` used by the
  automatic sync hook — no separate fetch/build logic.
- `tests/test_local.py` — new Section H: `garmin_live_fetch.py` coverage
  (`_ENDPOINTS` structure, fetch success/partial-failure/login paths,
  `_write_live()`, `progress` callback). +29 checks (469 → 498).
- `tests/test_dashboard.py` — Section 15 extended (`garmin_map`'s new
  live-route descriptor types, including the HRV fallback chain and
  missing-file behaviour) and new Section 15b (`layouts/render/live.py` —
  structure, formatting, archive-fallback note, error handling). +36
  checks (409 → 445).
- `version.py` — `APP_VERSION` bumped to `1.6.5`.

**What does not change:**
- No archive silo touched — `raw/`, `summary/`, `source/` untouched by the
  live-fetch path.
- `daily_update.py` / headless T3.2 path — completely untouched, no live
  fetch triggered there.
- `field_map.py` — untouched. Pure passthrough already supported the new
  `resolution="live"` value without modification.

**Known follow-ups (see NOTES_v1_6_5.md):**
- Live Tracking currently also appears in the manual "Create Reports"
  dialog (auto-discovery doesn't yet exclude it) — a dedicated trigger was
  the design intent.
- Connection-status indicators (Token/Login/API Access/Data) don't react
  to the in-process live fetch — deferred to v1.6.5.1.
- `fetch_live(client=None)` in the GUI path triggers a second, independent
  login shortly after the Sync Garmin subprocess's own login (subprocess
  architecture prevents client reuse) — structurally the same concern as
  the open T3.2 MFA-cascade investigation, not resolved here.

**Test result:** 498 / 261 / 445 / 145 / 46 / 4 — all green, ruff 0 errors,
bandit 0 HIGH

---

# v1.6.4.2 — Settings Shadow Copy + Update Notice Title

Two small, self-contained fixes — no new feature.

## Changed modules

**`export/backfill_source_backup.py`**
`sys.path` extended to include `app/`; `SETTINGS_FILE` is now imported from `garmin_app_settings` instead of being independently hardcoded (`Path.home() / ".garmin_archive_settings.json"`). Finding from the v1.6.4 session's DEPS scan (`settings_persistence_pattern`). Behavior identical, just a single source of truth for the path now.

**`garmin_app_base.py`**
`_check_version()`: now additionally reads the `name` field from the GitHub Release API response (`title = data.get("name", "").strip() or latest`, falling back to `tag_name`). `_show_update_popup()` gets a new `title` parameter and displays the full release title (e.g. "v1.6.4 — Custom Dashboard Builder") instead of just the version number. Comparison logic unchanged — still compares against `tag_name`. `scheduler/daily_update.py`'s standalone, headless `_check_version()` copy is deliberately left untouched (no popup there).

**`version.py`**
`APP_VERSION` bumped to 1.6.4.2.

## What does not change

- No pipeline touched — both changes live in the App/Script layer
- `garmin_config`, `garmin_backup_source`, `daily_update.py` — unchanged
- No new field, no new constant needed in `REFERENCE_GLOBAL.md`

## Test result

469 / 261 / 409 / 145 / 46 / 4 — all green, ruff 0 errors, bandit 0 HIGH
---

## v1.6.4.1 — Broker Layer Reference

Consolidates the Broker Layer's outward-facing API contract into its own
reference file. Documentation-only change — no code touched.

**New file:**
- `docs/REFERENCE_BROKER.md` — single reference for `field_map.get()` and
  `context_map.get()`: signatures, request/response contract, error
  behaviour, broker overview table. Field-level internal mappings stay in
  `REFERENCE_GARMIN.md` / `REFERENCE_CONTEXT.md` — referenced, not
  duplicated. Includes a names-only field index across all five registered
  sources (garmin/weather/pollen/brightsky/airquality) as a quick lookup —
  not the source of truth, `list_fields()` remains authoritative. Notes the
  `wind_speed_max` naming collision between `weather` and `brightsky`
  (independently defined, different internal keys). Placeholder section for
  `fit_map` (v1.7) and `mcp_map` (v1.9).

**Changed files:**
- `REFERENCE_DASHBOARD.md` — "Broker interface" section replaced with a
  pointer to `REFERENCE_BROKER.md`. Plotter interface section unchanged.
- `REFERENCE_GARMIN.md` — header note added, pointing to
  `REFERENCE_BROKER.md` for the broker contract.
- `REFERENCE_CONTEXT.md` — same header note added.
- `MAINTENANCE_DASHBOARD.md` — header corrected: interface reference split
  between `REFERENCE_DASHBOARD.md` (specialist/plotter) and
  `REFERENCE_BROKER.md` (broker contract).
- `REFERENCE_GLOBAL.md` — `REFERENCE_BROKER.md` added to the documentation
  file list.
- `version.py` — `APP_VERSION` bumped to `1.6.4.1`.

**What does not change:**
- No code touched — `field_map.py`, `context_map.py`, and all `*_map.py`
  modules are untouched.
- No test suite impact — documentation-only change.

---

## v1.6.4 — Custom Dashboard Builder

A dialog in `panel_outputs.py` that replaces the fixed specialist list with
free field selection. The user picks Garmin and Context daily fields, sets a
date range and output format, and the app assembles and renders the result
directly — no specialist file is written to disk. Presets let a chosen field
selection be saved, reloaded, or deleted by name. An "Encrypt" option reuses
the existing password/AES-256 flow for the HTML output.

Confirmed during analysis: `dash_runner.build()` requires no changes — it
only needs an object with `.META`, `.build()`, and `.__name__`, satisfied by
an in-memory `types.ModuleType`. The file-based assumptions found in
`dash_runner.scan()` / `_load_specialist()` only apply to the auto-discovery
checkbox popup ("Create Reports"), which the Custom Dashboard Builder never
goes through.

**New modules:**
- `dashboards/custom_dash_builder.py` — Builds an ad-hoc, in-memory
  specialist from a user field selection. Deliberately not named `*_dash.py`
  so `dash_runner.scan()`'s glob never picks it up as a real specialist.
  `list_available_fields()` mirrors the Explorer specialist's Daily-field
  enumeration (local copy of its exclusion set, by design — specialists are
  standalone, no cross-specialist imports). Output shape matches the
  existing `health_garmin-weather-pollen_html-xls_dash` contract
  (`"fields"` list with `"days"`) — renders via the existing
  `dash_plotter_html_mobile` and `dash_plotter_excel`, no new plotter, no
  new `dash_plotter_html_complex` layout key.
- `app/garmin_dashboard_presets.py` — Sole Owner of the Custom Dashboard
  preset file (`~/.garmin_dashboard_presets.json`), mirroring the
  persistence pattern in `garmin_app_settings.py`. `load_presets()` /
  `save_preset()` / `delete_preset()`. Preset schema includes `"encrypt"`
  (bool) — the password itself is never persisted, only the on/off
  preference.

**Changed modules:**
- `app/panel_outputs.py` — New "🎛 Custom Dashboard" button in the Export
  section. New `_open_custom_dashboard_popup()`: field picker (Garmin +
  Context), date range (fixed or relative "days back"), format checkboxes
  (HTML / Excel), preset load/save/delete. `_run_dashboards()` extended with
  optional `date_from`/`date_to` parameters (default `None` → unchanged
  behaviour, falls back to Settings) so the Custom Dashboard can use its own
  date range without touching the existing Create Reports call site. New
  `_run_custom_dashboard_encrypted()` — a structural copy of
  `_run_encrypted_dashboards()`, applied to the ad-hoc module and the
  dialog's own date range instead of a full specialist scan and the global
  Settings range; `_run_encrypted_dashboards()` itself is untouched. The
  "Encrypt" checkbox disables and clears "Excel" while active — the app has
  no Excel encryption anywhere, made explicit here rather than silently
  dropped later.
- `compiler/build_manifest.py` — both new modules added to `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.

**What does not change:**
- `dash_runner.py`, `dash_plotter_html_mobile.py`, `dash_plotter_excel.py`,
  `dash_plotter_html_complex.py` — no changes needed
- Existing specialists and the Create Reports flow — unaffected
- `_run_encrypted_dashboards()` — unaffected, left as-is

**Test result:** 469 / 261 / 409 / 145 / 46 / 4 — all green, ruff 0 errors,
bandit 0 HIGH

---

## v1.6.3.1 — Heatmap Dashboard + spo2/respiration Fix + Mirror Password Mode

Ships the Heatmap dashboard specialist deferred from v1.6.3, and uncovers two
independent, pre-existing bugs along the way — both found only because the
new SpO2/Respiration panels stayed empty instead of showing data, reaching
well beyond the heatmap itself.

**New modules:**
- `dashboards/heatmap_garmin_html_dash.py` — Specialist. Pivots six intraday
  fields (Heart Rate, Steps, Stress, Body Battery, SpO2, Respiration) into
  date × hourly-bin matrices. Aggregation: mean for continuous metrics, sum
  for Steps (a count metric). Pivot logic deliberately lives in the
  specialist, not the renderer — it's a data transformation, not a rendering
  decision, consistent with the existing sleep-phase-percentage pattern.
- `layouts/render/heatmap.py` — Renderer. One Plotly heatmap panel per
  metric, tab navigation (analogous to Recovery Context). Colorscales:
  HR = `RdYlBu` (reversed), Steps = `Viridis`, Body Battery = `RdYlGn` —
  library scales. Stress/SpO2/Respiration = custom scales derived from each
  metric's own brand color in `dash_layout.METRIC_META`, for consistency
  with the rest of the app rather than generic library colors for metrics
  that already have a fixed color everywhere else.

**Changed modules:**
- `layouts/dash_plotter_html_complex.py` — one entry `"heatmap"` in
  `_REGISTRY`. The Render Registry pattern (v1.6.0.5) worked exactly as
  designed — no `if/elif` edit needed.
- `layouts/dash_layout.py` — `METRIC_META` entry for `steps_series` added
  (was missing entirely, even though the field has existed since v1.6.3).
- `compiler/build_manifest.py` — two new entries in `SHARED_SCRIPTS`.
- `tests/test_dashboard.py` — new Section 18 (META, `build()` structure,
  hourly aggregation, HTML render, ValueError guard).

**Bug found #1 — `maps/garmin_map.py`: `spo2_series`/`respiration_series`
have been returning empty data for every consumer, for an unknown amount of
time:**
The real Garmin raw data (`spO2HourlyAverages`, `respirationValuesArray`) is
a list of `[epoch_ms, value]` pairs — exactly like `heartRateValues`/
`stressValuesArray`. `_FIELD_MAP` expected a dict structure for both fields
instead (`ts_index`/`val_index` = `None`). Every item fell through both
extraction branches in `_extract_series()` and hit `else: continue` — the
series was empty for every day, for every existing consumer
(`timeseries_garmin`, `explorer_garmin-context`, `sleep_recovery_context`),
not just the new heatmap. Went unnoticed because the test fixtures in
`test_dashboard.py` were themselves built dict-shaped — they validated the
wrong assumption against itself. No data loss: `raw/` stores the API
response unmodified, this was a pure read-path bug in the broker.
- `maps/garmin_map.py` — `ts_index`/`val_index` changed from `None` to
  `0`/`1` for both fields, matching the already-correct pattern used by
  `heart_rate_series`/`stress_series`/`body_battery_series`.
- `tests/test_dashboard.py` — fixtures switched to the real list-pair
  structure.

**Bug found #2 — `garmin/quality/_assess.py`: wrong key name for
respiration quality assessment:**
Caught incidentally by the DEPS scan for bug #1. `assess_quality_fields()`
reads `resp.get("respirationValues")` — a key that doesn't exist anywhere
(the real key is `respirationValuesArray`). `resp_values` is therefore
always `None`, so the respiration field-level label can never become
`"high"`. Independent of bug #1 (different module, different failure mode —
a key-name typo, not a structural misassumption). Only affects the
field-level quality label, does not feed into `assess_quality()`'s
top-level label (precedent: SpO2/Body Battery/Respiration/Steps) — no
downgrade risk, but a wrong diagnosis nonetheless.
- `garmin/quality/_assess.py` — key corrected.
- `tests/test_local.py` — the `raw_fields_high` fixture had no
  `respiration` entry at all; added, including a new check.

**Bug found #3 — `app/dialogs.py`: Mirror Import shows a meaningless
confirm-password field:**
`_on_import_mirror()` used the same `PasswordConfirmDialog` (password +
confirm) as `_on_mirror()` (export). But import enters an already-existing
password — `unlock_meta()` verifies it regardless, so a confirm field
serves no purpose.
- `app/dialogs.py` — `PasswordConfirmDialog` gains `mode: str = "setup"`
  (default preserves existing behavior for export + Encrypted Dashboards).
  `mode="unlock"` hides the confirm field and the match check. Pattern
  borrowed from `panel_connection.py`'s encryption-key dialog, which
  already does this.
- `app/panel_archive.py` — `_on_import_mirror()` now calls the dialog with
  `mode="unlock"`.
- `tests/test_qt_app.py` — new `TestPasswordConfirmDialog` class (4 checks).

**Carry-over from v1.6.3:**
- `garmin/garmin_collector.py` — `_run_steps_backfill()` now checks the
  return value of `patch_source_field()`. Separate counter
  `source_patch_failed` (not counted in `ok`/`failed`, since raw/summary/
  quality_log had already been written successfully before the patch is
  attempted) — visibility without skewing the statistics.

**Open, deliberately deferred:** The respiration raw data also contains
`wellnessEpochRespirationDataDTOList` (dict-shaped) — an apparently newer,
parallel Garmin structure alongside the still-populated
`respirationValuesArray`. Not touched, no urgency. Candidate for its own
analysis session.

**DEPS scans this session:** `v1631_01` (Heatmap render-registry shadow,
build-manifest, steps_series consumers — clean, one known documented
exception in `dash_plotter_excel.py`), `v1631_02` (spo2/respiration
dict-key shadow, consumer-empty-assumption — also caught bug #2).

**Test result:** 469 / 261 / 377 / 145 / 46 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.3 — Steps Intraday Foundation + Backfill

Adds Steps Intraday data (15-minute bins via `get_steps_data`) as the 15th archive endpoint, plus a sixth background timer mode that incrementally backfills this field into already archived high-quality days from the last 140 days. The backfill updates both `raw/` and `source/` without downgrade risk and without re-fetching the other 13 endpoints. Originally planned as part of the Heatmap Dashboard, the feature was resequenced during development into a Foundation + Backfill implementation, while the Heatmap itself was deferred to v1.6.3.1 (Archive-First priority: the backfill window is time-limited, the dashboard is not).

New module:

- `garmin/garmin_merge.py` — Leaf node. `merge_field()` implements additive field merge logic that never overwrites an already populated value and never mutates the input object.

Changed modules:

- `garmin/garmin_api.py` — `fetch_raw()` adds the new `get_steps_data` endpoint (15th endpoint).
- `garmin/garmin_dataformat.json` — adds optional `steps` field (`type: list`); schema version updated from 1.0 to 1.1.
- `maps/garmin_map.py` — adds `_FIELD_MAP` entry `steps_series`, using dictionary-based intraday extraction analogous to `respiration_series`.
- `garmin/quality/_assess.py` — `assess_quality_fields()` gains a new `steps` block (high/medium/low/failed), reusing `has_steps` from the statistics block. Intentionally excluded from the top-level `assess_quality()` label to preserve the existing precedence of SpO₂, Body Battery, and Respiration.
- `garmin/garmin_source_writer.py` — adds `patch_source_field()` for additive updates within `source/`. Deliberately bypasses `compare_source()` because full-file replacement semantics are unsuitable for additive patches. Writes `backfilled_fields` directly into `source_api_log.json` without using `update_log()`.
- `garmin/quality/_maint.py` — `_upsert_quality()` and `record_attempt()` gain an optional `backfilled_fields` parameter, merged additively using the existing `fields` pattern.
- `app/garmin_app_controller.py` — adds `timer_run_steps_backfill()`, selecting candidates where `quality == "high"`, `source == "api"`, `"steps"` is absent from `fields`, and the date is within the last 140 days. Self-terminating by design: candidates disappear automatically once the `steps` field has been backfilled.
- `app/panel_timer.py` — introduces a sixth timer mode (`steps_backfill`) with the lowest priority after Source Backfill. Updates `_mode_cycle`, label dictionary, batch selection, delegate dispatch, and adds the `GARMIN_STEPS_BACKFILL` environment override. Replaces `% 4` with `% len(_mode_cycle)` at both dispatch points as an additional robustness improvement.
- `garmin/garmin_collector.py` — adds `_run_steps_backfill()`, a narrow worker performing one API call per day via `api.api_call()` (instead of the 14 calls used by Source Backfill). Workflow: `read_raw()` → `merge_field()` → `normalize()` + `summarize()` → `write_day()` → `record_attempt()` → `patch_source_field()`. Adds `GARMIN_STEPS_BACKFILL` handling in `main()` (step 5d).
- `compiler/build_manifest.py` — registers `garmin_merge.py` in `SHARED_SCRIPTS` and `SCRIPT_SIGNATURES_BASE`, and updates signatures for `garmin_app_controller.py` and `garmin_collector.py`.

Live correction during development:

- The `GARMIN_STEPS_BACKFILL` flag was initially missing from the `env_overrides` dictionary in `panel_timer.py`. The issue was discovered during an actual timer run: candidates were correctly identified, but the collector never entered the new worker path. A one-line fix was applied and verified successfully in a subsequent live run.

Known non-blocking issue (see `NOTES_v1_6_3.md`, §9):

- `_run_steps_backfill()` currently ignores the return value of `patch_source_field()`. This creates a debugging blind spot but carries no data loss risk. A fix is scheduled for v1.6.3.1.

Test results:

- 468 / 261 / 336 / 145 / 42 / 4 — all green
- Ruff: 0 errors
- Bandit: 0 HIGH findings

---

## v1.6.2.1 — Build: T3 ZIP Structure + Docs Path

Hotfix for two build errors in T3 (Standalone). The documentation files
QUICKSTART.txt, USER_GUIDE.txt and README_APP.md were missing from the
T3 package because the info-copy path src/docs/ was unknown. Additionally,
info/ ended up next to instead of inside the standalone folder after
extraction — the Documentation button couldn't find the files. Both
errors fixed.

**Changed modules:**
- `compiler/build_standalone.py` — info-copy loop: added a third search
  path `src/docs/` (QUICKSTART.txt, USER_GUIDE.txt, README_APP.md).
  `build_combined_zip()`: switched ZIP layout to flat
  (`f.relative_to(t31_dir)` instead of `f.relative_to(root)`) — EXE,
  `_internal/`, `daily_update.exe` and `info/` sit directly at the root
  after extraction.
- `compiler/build.py` — info-copy loop: added the identical third search
  path `src/docs/`.
- `tests/test_build_output.py` — updated ZIP checks section 7 for the flat
  structure: EXE + `_internal/` flat at the root, `info/QUICKSTART.txt`
  checked.

**Test result:** 439 / 261 / 332 / 136 / 42 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.2 — Sleep Dashboard + Intraday Explorer

Extends the Sleep Dashboard with an embedded intraday explorer section.
Each row in the sleep table carries a click handler — clicking a row jumps
to the Intraday Detail section below and selects the correct date automatically.
The explorer shows four fixed intraday traces (Heart Rate, Stress, Body Battery,
Respiration) rendered inline via Plotly with no companion file required.
Single self-contained HTML output — no second file, no relative links.

**Changed modules:**
- `dashboards/sleep_garmin_html-xls_dash.py` — `build()` fetches four intraday
  fields (heart_rate_series, stress_series, body_battery_series, respiration_series)
  via `field_map.get(..., resolution="intraday")`. New helper `_intraday_by_date()`.
  New `_INTRADAY_FIELDS` constant. Return dict gains `"intraday"` key
  (`{date: {heart_rate, stress, body_battery, respiration}}`). Excel render
  unaffected — plotter ignores `"intraday"` key.
- `layouts/render/sleep.py` — `import json` added. `_LAYOUTS_DIR` module constant.
  `_render_sleep()` extended: calls new `_build_intraday_explorer()`, embeds
  Plotly inline (conditional — only when intraday data present). Plotly loaded
  before explorer script to avoid race condition. Row `<tr>` elements carry
  `onclick="sleepJumpToDay(date)"` for direct navigation. New private function
  `_build_intraday_explorer()`: Date dropdown, Plotly chart (4 traces, 4 Y-axes),
  `sleepUpdateIntraday()` + `sleepJumpToDay()` JS functions.
- `tests/test_dashboard.py` — 12 new checks in Section 14: `"intraday"` key in
  build return dict, intraday day structure, HTML contains explorer div + chart id
  + Plotly + JS functions + trace names.

**Architecture note — Plotly load order:**
`plotly_script` must appear in the HTML **before** `explorer_div`. The explorer
script calls `Plotly.react()` immediately on load — if Plotly is not yet defined,
the call fails silently and the chart never renders. Pattern to follow in all
future renderers that embed Plotly inline.

**What does not change:**
- `dash_runner.py` — no companion file, no second output, unchanged.
- `layouts/render/explorer.py` — standalone Explorer unaffected.
- `dash_plotter_excel.py` — ignores `"intraday"` key, Excel output unchanged.
- `build_manifest.py` — `layouts/render/sleep.py` already listed, no change.

**Test result:** 439 / 261 / 332 / 136 / 42 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.1 — Encrypted Dashboard Export

Adds password-protected HTML dashboard export for secure transport on USB drives
or other removable media. All HTML dashboards are built via the standard pipeline
and then encrypted with AES-256-GCM — the encrypted file is self-contained and
decrypts fully in the browser via Web Crypto API. No server, no Python callback,
no external asset required.

**New modules:**
- `layouts/dash_encryptor.py` — Sole Owner of HTML encryption logic. Leaf-Node
  (stdlib + cryptography only). `encrypt_html(html_content, password) -> str` —
  takes a finished HTML string, returns a self-decrypting HTML with inline
  password dialog and Web Crypto API decrypt logic. AES-256-GCM, PBKDF2-HMAC-SHA256
  (100,000 iterations), random salt + IV per file.
- `dialogs.py` — Shared `PasswordConfirmDialog` for Mirror and Encrypted Dashboards.
  Two password fields with confirmation, QMessageBox validation, Default-Button-Fix
  (`setAutoDefault(False)`), Enter-flow pw1 → pw2 → OK. Located in `src/` (flat
  import alongside other project modules).

**Changed modules:**
- `app/panel_outputs.py` — new "🔒 Encrypted Dashboards" button in the Export
  section. `_open_encrypted_dashboard_popup()` shows the shared password dialog.
  `_run_encrypted_dashboards()` builds all HTML dashboards (html + html_complex,
  html_mobile excluded), encrypts each file in-place, writes to `basedir/encrypted/`
  with `_enc` suffix (e.g. `health_garmin_enc.html`). Explorer opens automatically.
  Not triggered by Daily Sync or daily_update.py.
- `app/panel_archive.py` — `MirrorPasswordDialog` replaced by `PasswordConfirmDialog`.
  WCM save-checkbox removed — mirror password is always entered manually, never
  cached. Prevents the WCM corruption scenario (typo → manual WCM cleanup required).
- `compiler/build_manifest.py` — `dash_encryptor.py` and `dialogs.py` added to
  `SHARED_SCRIPTS` and `SCRIPT_SIGNATURES_BASE`.
- `version.py` — `APP_VERSION` bumped to `1.6.1`.

**What does not change:**
- Normal "Create Reports" flow — unaffected, no encrypt step.
- Daily Sync / daily_update.py — encrypted export is never triggered automatically.
- `basedir/dashboards/` — unchanged, encrypted files go to `basedir/encrypted/`.
- `garmin_mobile_landing.py` — unaffected (not part of encrypted export).
- All Garmin pipeline modules — unaffected.

**Architecture notes:**
- `basedir/encrypted/` is an isolated silo — no other module reads or writes it.
- `dialogs.py` is a flat module in `src/` — imported as `import dialogs`, same
  pattern as all other project modules. Not in `app/` to avoid package import issues.
- Mirror password WCM helper functions (`_archive_load_mirror_password`,
  `_archive_save_mirror_password`) remain in `panel_archive.py` but are no longer
  called — cleanup deferred.

**Test result:** 439 / 261 / 320 / 136 / 42 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.0.7 — Determinism Fix, Dropdown Indicators, Device Table Edit, Single Instance

Fixes a flaky pre-build-gate test, adds visual dropdown indicators to all
QComboBox widgets, makes the device name field re-editable after initial
assignment, and prevents multiple simultaneous GLA instances from corrupting
the archive.

**Changed modules:**
- `tests/test_local.py` — Section 11: `_strip_val_timestamp()` helper strips
  `val_result["timestamp"]` (generated via `datetime.now()`) before comparing
  two `_fetch_and_assess()` calls — eliminates flaky determinism check.
- `app/panel_home.py` — `_dash_combo`: wrapped in `QHBoxLayout` with `▼` label
  (Qt6/Windows suppresses native drop-down arrow when any stylesheet is applied);
  `setSelectionMode` changed from `NoSelection` to `SingleSelection` to enable
  `cellDoubleClicked` signal on device table; `::item:selected` hidden via
  stylesheet so table remains visually non-interactive; `setToolTip` added on
  `_dash_combo`.
- `garmin_app_base.py` — `_xlsx_combo` and `_sheet_combo`: `▼` labels added
  after each combo; `self._sheet_arrow` stored as instance attribute so
  `_scan_xlsx_files()` can mirror its visibility with `_sheet_combo`.
- `app/panel_archive.py` — `_refresh_archive_info()`: `device_id` stored as
  `Qt.ItemDataRole.UserRole` on the name item so the edit guard does not rely
  on display text. `_archive_on_device_name_click()`: guard changed from
  `text() != "unknown"` to numeric-ID / `__total__` check — rows with
  non-numeric sentinel IDs (e.g. `__unknown__`) are now re-editable after
  the first name has been set.
- `garmin_app.py` — single-instance guard via `QLocalServer`/`QLocalSocket`
  added before `QApplication` construction: pings named socket, shows warning
  dialog and exits if another instance responds.
- `garmin_app_standalone.py` — identical single-instance guard.
- `compiler/build.py` — `PyQt6.QtNetwork` added as hidden import (required
  by `QLocalServer`/`QLocalSocket` in PyInstaller T2 builds).
- `compiler/build_standalone.py` — `PyQt6.QtNetwork` added to hidden list
  (T3 builds).
- `docs/USER_GUIDE.txt` — note added at end of Section 1 pointing to
  Documentation → README App for full `Connection & Archive Status` field
  reference.
- `version.py` — `APP_VERSION` bumped to `1.6.0.7`.

**Test result:** 439 / 261 / 310 / 136 / 42 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.0.6 — UI/UX Update: Documentation, Tooltips, Mirror Labels

Adds a Documentation button with in-app access to Quickstart, User Guide and
README. Introduces tooltips on all buttons and input fields across the Settings
and Home panels. Unifies Mirror-related button labels throughout the app.
Widens the Settings left column from 340px to 400px for better readability
at Full HD. Aligns DATA MANAGEMENT buttons to left with equal width.

**New files:**
- `src/docs/QUICKSTART.txt` — first-time setup guide (English)
- `src/docs/USER_GUIDE.txt` — full user guide with all features (English)

**Changed modules:**
- `app/panel_home.py` — Documentation button + `_home_docs_dialog()` (opens
  QUICKSTART.txt / USER_GUIDE.txt / README_APP.md via OS file handler);
  tooltips on Daily Sync, Mirror, Timer, Documentation buttons;
  Mirror dialog titles unified to "Export to Mirror"
- `app/panel_connection.py` — DATA MANAGEMENT buttons left-aligned with equal
  width (`QSizePolicy.Expanding`); `addStretch()` removed; Mirror button
  renamed "⬡  Export to Mirror"; tooltips on all 6 buttons
- `app/panel_archive.py` — `set_mirror_button_state()` calls updated to
  "⬡  Export to Mirror"; all `QMessageBox` titles "Data Mirror" →
  "Export to Mirror"
- `app/panel_settings.py` — tooltips on all input fields and buttons
  (Email, Password, Data folder, Mirror target, Sync Mode, Days/From/To/
  Fallback, Export Date Range From/To, Age, Sex, Delay min/max, Maps URL,
  Set Location, Save Settings, Log Level); Export Date Range tooltips include
  default fallback values (30 days back / today)
- `app/panel_outputs.py` — `_tip()` label fixed width (300px) so all action
  buttons render at equal width
- `garmin_app_base.py` — Settings left column widened 340px → 400px;
  `QApplication.instance().setStyleSheet()` with `QToolTip` selector added
  to activate tooltips globally; `QApplication` added to imports
- `build_manifest.py` — `QUICKSTART.txt` and `USER_GUIDE.txt` added to
  `INFO_INCLUDE_T2` and `INFO_INCLUDE_T3`
- `version.py` — `APP_VERSION` bumped to `1.6.0.6`

**Test result:** 439 / 261 / 310 / 136 / 42 / 4 — all green

---

## v1.6.0.4.9.3 — Container Security Tests

Extends `test_local.py` with targeted tests for the encrypted mirror
container — the most security-critical module with no direct test coverage
until now. No production code changed.

**Changed modules:**
- `tests/test_local.py` — three new sections (C2, C3, C4): `unlock_meta`
  happy path + wrong password + missing file + non-container file + tampered
  HMAC; `fulfill_order` roundtrip + wrong password + empty order;
  `detect_source` container / nonexistent / plain folder. 18 new checks.
- `version.py` — `APP_VERSION` bumped to `1.6.0.4.9.3`

**Test result:** 439 / 261 / 310 / 136 / 42 / 4 — all green

---

## v1.6.0.4.9.2 — Security Linting Gate (bandit)

Adds `bandit` as a permanent pre-build security linting gate alongside the
existing `ruff` linting gate. No pipeline changes, no new features, no user-
visible behaviour changes.

**Fix — `garmin/garmin_extended_anaysis.py`:**
Three `hashlib.md5()` calls used for pseudo-deterministic date hashing
(Easter Egg — no security context) flagged as HIGH severity by bandit.
Fixed with `usedforsecurity=False` — semantically accurate, silences the
finding without changing behaviour.

**New gate — `tests/test_static.py`:**
Section 2 activated: `bandit -r . --severity-level high --confidence-level high`.
0 HIGH findings required — build aborts on violation. Section 3 slot renamed
to `(reserved) mypy`. Docstring updated.

**New pre-build step — `compiler/build_all.py`:**
`test_static.py` runs as the final pre-build step after `test_local`,
`test_local_context`, and `test_dashboard`. Build aborts if bandit or ruff
report any findings.

**Changed modules:**
- `garmin/garmin_extended_anaysis.py` — three `md5()` calls: `usedforsecurity=False` added
- `tests/test_static.py` — bandit section activated; mypy slot renumbered to 3
- `compiler/build_all.py` — `test_static.py` added as pre-build gate

**Test result:** 420 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.0.4.9.1 — Bugfix: Device Name Dialog + BAT Folder

Two GUI bugfixes and a structural cleanup. No pipeline changes, no new modules.

**Fix 1 — `app/panel_archive.py`:**
`_archive_on_device_name_click()` referenced `self._app._panel_connection`
to retrieve `_info_device_table`. The table was moved to `panel_home` in
v1.6.0. Double-click on an unknown device row caused an `AttributeError`
crash. Fix: `_panel_connection` → `_panel_home`.

**Fix 2 — `garmin/quality/_io.py`:**
After `set_unknown_device_name()` wrote the new name into `quality_log.json`,
`save_device_table()` still showed `"unknown"` in the device table — the
display name was hardcoded. Fix: `_names` set accumulated from entries with
`device_id=None`; if all entries carry the same name, it is used as the
display name. Mixed or empty → falls back to `"unknown"`.

**Structural — `src/bat/`:**
Five dev-launcher BAT files moved from `src/` into `src/bat/`. All BATs
updated with `cd /d "%~dp0.."` so they work on double-click without
requiring a specific CWD. `run_tests.ps1` stays in `src/` (called via
relative path from `bat/run_test_all.bat`).

**Changed modules:**
- `app/panel_archive.py` — `_archive_on_device_name_click()`: panel reference fixed
- `garmin/quality/_io.py` — `save_device_table()`: unknown row displays actual device name
- `src/bat/run_T1.bat` — moved + cd fix
- `src/bat/run_build_all.bat` — moved + cd fix
- `src/bat/run_build_all_-_check_deps.bat` — moved + cd fix
- `src/bat/run_cve_check.bat` — moved + cd fix
- `src/bat/run_test_all.bat` — moved + cd fix

**Test result:** 420 / 261 / 310 / 136 / 42 / 2 — all green

---

## v1.6.0.5 — Dashboard Render Registry

Replaces the `if/elif` dispatch in `dash_plotter_html_complex.py` with a
render registry pattern. `dash_plotter_html_complex.py` becomes a pure
facade (67 lines, was 1217): it looks up the renderer for the incoming
layout key and delegates — no layout-specific logic remains. Adding a new
dashboard layout now requires one line in the registry, not an edit to the
plotter. Additionally, `check_source_backfill_needed()` is now called
automatically at the end of each normal Daily Sync (Step 9b in
`garmin_collector.main()`) so unbackedup `source/` files are secured
without any manual script.

**New modules:**
- `layouts/render/__init__.py` — package marker
- `layouts/render/recovery_context.py` — Recovery Context renderer: `_build_tab1`, `_build_tab2`, `_render_recovery_context`, tab navigation (530 lines)
- `layouts/render/sleep.py` — Sleep Dashboard renderer: `_render_sleep` (214 lines)
- `layouts/render/explorer.py` — Explorer renderer: `_build_explorer_tab1`, `_render_explorer` (520 lines)

**Changed modules:**
- `layouts/dash_plotter_html_complex.py` — facade only: `_REGISTRY` dict + `render()` dispatcher. Renderer loading via `importlib.util.spec_from_file_location` — robust against `sys.path` context variations. `render/` registered as package in `sys.modules` on first load.
- `garmin/garmin_collector.py` — Step 9b added after the normal backup cycle: `check_source_backfill_needed() > 0` → `backfill_source()`. Guard: `ok > 0 and GARMIN_SOURCE_BACKFILL != "1"`. Non-fatal (`try/except` → `log.warning`).
- `compiler/build_manifest.py` — four new entries in `SHARED_SCRIPTS` (`layouts/render/__init__.py`, `layouts/render/recovery_context.py`, `layouts/render/sleep.py`, `layouts/render/explorer.py`) + three entries in `SCRIPT_SIGNATURES_BASE`.

**What does not change:**
- Neutral dict contract between specialist and plotter — identical
- `dash_runner.py` — no changes; calls `plotter.render()` as before
- All `*_dash.py` specialists — no changes; layout key in return dict drives dispatch as before
- `test_dashboard.py` — no changes; imports `dash_plotter_html_complex` directly, tests pass against new facade

**Test result:** 439 / 261 / 310 / 136 / 42 / 4 — all green, ruff 0 errors, bandit 0 HIGH

---

## v1.6.0.4.9 — Audit Hardening: Silent-Failure-Fixes (F-1 bis F-5)

Closes all five actionable findings from the Dependency Audit (v1.6.0.4.8).
Primary lens: Silent Failure. All fixes reflect existing good patterns
applied to the places they were missing — no new architectural concepts.
F-6 (source backfill surfacing) is already on the ROADMAP and receives no
separate Bauauftrag here.

**F-3 (HOCH) — `garmin/garmin_api.py`:**
Rate-limit detection via substring (`"429" in str(e)`) replaced by typed
exception check. `GarminConnectTooManyRequestsError` is now caught via
`isinstance` (primary); substring remains as fallback (Defense-in-Depth).
Applied to both `api_call()` and `login()` Path 1 Token-Probe.
`GarminConnectAuthenticationError` deliberately excluded from Stelle B —
it also covers 401 (token expired), which must still fall through to SSO.
Multi-LLM review gate passed (Gemini, ChatGPT, Copilot) — intersection
confirmed the 403-substring fallback must be retained.

**F-1 (MITTEL) — `garmin/garmin_source_writer.py`:**
`update_log()`: read failure on existing `source_api_log.json` previously
fell back to `existing = {}`, causing a subsequent write to silently replace
the entire log history with a single entry. Fix: `return False` on read
failure — existing file is left untouched. Log message updated to name the
protection reason explicitly.

**F-5 (NIEDRIG) — `maps/garmin_map.py`:**
`_read_daily()`, `_read_intraday()`, `_read_raw_pct()`: all three had
`except (json.JSONDecodeError, OSError): pass` with no logging. A corrupt
file in the dashboard read path was silently skipped — indistinguishable
from "data never existed". Fix: `log.warning` added (exact pattern of the
four Context Maps since v1.5.5.4). `_read_raw_pct` was not named in the
audit finding — discovered during file read, fixed in the same pass (M-2).
`import logging` + `log = logging.getLogger(__name__)` added (was missing).

**F-4 (NIEDRIG) — `garmin/garmin_source_quality.py`:**
`assess_source_from_file()` returned `None` for both absent and unreadable
files. `compare_source(None, ...) → "write"` always — a degraded API
response could overwrite an unreadable (potentially high-resolution)
`source/` file. Fix: unreadable files now return `{"unreadable": True}`;
`compare_source` handles the new case with `"skip_warn"` (conservative —
file may contain intraday data that cannot be assessed).
`garmin_source_writer.write_source()` unchanged — existing `skip_warn`
handler covers the new case correctly.

**F-2 (NIEDRIG) — `garmin/garmin_collector.py`:**
`write_source()` return value was discarded in `_fetch_and_assess()`.
A `source/` write failure was only a `log.warning`, while `raw/` write
failures surface as `log.error`. Fix: return value captured; `False` →
`log.error`. Exception path also upgraded from `log.warning` to `log.error`.
Visibility parity between `source/` and `raw/` write failures established.
Pipeline remains non-fatal.

**Changed files:**
- `garmin/garmin_api.py`
- `garmin/garmin_source_writer.py`
- `maps/garmin_map.py`
- `garmin/garmin_source_quality.py`
- `garmin/garmin_collector.py`
- `tests/test_local.py` (+2 checks for F-4)

**Test result:** 420 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors

---
 
## v1.6.0.4.8 — Dependency Audit
 
Full systematic dependency audit across all 88 modules (6 clusters).
Read-only session — no code changes. Produces the findings register
`AUDIT_FINDINGS_v1_6_0_4_8.md` that drives the v1.6.0.4.9 hardening series.
 
**Methodology:**
- `build_dep_map.py` Run-04 (2026-06-23) — AST-based full dependency map:
  imports, importers, exception handlers, file I/O, dynamic imports, caller map.
- 6 clusters audited: garmin Write-Core, garmin Pipeline, context,
  maps, layouts + dashboards, app + entry points.
- Primary lens: Silent Failure (unobservable errors that mask data loss).
- Each finding classified on two axes: gewollt (by design) × Handlungsbedarf
  (action required). Only `gewollt=nein + Handlungsbedarf=ja` are fix candidates.
**Findings: 6 total — 1× HOCH, 1× MITTEL, 4× NIEDRIG.**
All five actionable findings fixed in v1.6.0.4.9. F-6 carried to ROADMAP v1.6.0.5.
 
**Cross-check patterns identified:**
- M-1: Aggregat-Writer Read→fallback{}→overwrite — exists only in F-1 (closed).
- M-2 (dominant signal): good patterns not applied everywhere — 4 of 6 findings
  are existing hardening measures missing from sibling locations.
**No changed files** — audit only. No test run.

--- 

## v1.6.0.4.7 — Silo-Reconciliation-Check

Read-only drift detection across the data silos. Surfaces inconsistencies
that the live pipeline does not catch: old gaps, interrupted runs, manual
file operations, and import errors — across raw/, summary/, source/, and
quality_log.json. Repair delegates to existing tools; no new write paths.

**New modules:**
- `garmin/garmin_silo_check.py` — Read-only, Leaf-Node (garmin_config + stdlib
  only). Single public function `check_silos() -> dict`. Covers four checks
  based on the reconstructability principle (KONZEPT §3):
  #1 raw without quality_log entry (orphan — processed but not logged),
  #3 source without raw (raw rebuildable from existing source via regenerate_raw),
  #5 summary without raw (orphan summary — source raw gone),
  #7 raw without summary (derived file missing — rebuildable from raw).
  Check #2 (quality_log entry without raw) remains with
  `garmin_backup.check_raw_integrity()` — not re-implemented (Option C).
  Returns finding lists, totals per silo, counts, and a checked_at timestamp.

**Changed modules:**
- `app/panel_connection.py` — `_silo_check_btn` and `_silo_repair_btn` added
  to DATA MANAGEMENT row. Accessor methods `set_silo_check_button_state()` and
  `set_silo_repair_button_state()` added (same pattern as mirror/restore buttons).
- `app/panel_archive.py` — `_on_silo_check()` and `_on_silo_repair()` added.
  Silo-Check runs in background thread; findings written to `_app._log()` stream.
  Gate: disabled while any pipeline job runs (`_is_running()`, `_ctx_running`,
  `_timer_active`, `_mirror_running`). Repair re-scans before acting (never on
  stale findings). Repair delegation:
  #1 → `garmin_quality._backfill_quality_log()` under QUALITY_LOCK,
  #3 → subprocess `regenerate_raw.py --date`,
  #5 → `Path.unlink()` (orphan summary),
  #7 → inline `garmin_normalizer.summarize()` + `garmin_writer.write_day()`.
- `compiler/build_manifest.py` — `garmin_silo_check.py` in `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.
- `export/backfill_source_intraday.py` — pre-existing ruff warnings fixed
  (E402 `# noqa`, F541 bare f-strings removed).
- `tests/test_local.py` — Section G added (37 checks): result structure,
  clean-silo baseline, all four check categories, counts/list consistency,
  date-object type check, Leaf-Node AST check.

**Architecture:**
- `garmin_silo_check` is a pure detection layer — no writes, no imports of
  write modules. Repair stays in `panel_archive` and delegates to existing
  owners. No new Sole-Write-Authority assignments.
- Lockless read is safe (§9a): quality_log is written atomically via
  `os.replace()`, so a concurrent read always sees a complete file.
- Gate via app state (not file lock): established house pattern from
  `_on_import_mirror()`.
- `_extract_date()` implemented inline in `garmin_silo_check` — mirrors
  `garmin_utils.extract_date_from_filename()` logic without importing it,
  preserving Leaf-Node isolation.

**Test result:** 418 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors

---

## v1.6.0.4.6 — Source Quality Guard

Introduces `garmin_source_quality.py` as the sole owner of source quality
assessment logic. Prevents `source/` files from being overwritten by degraded
API responses — the same sync that correctly protects `raw/` from a degraded
re-fetch now also protects `source/`. Sole-Write-Authority for `source/` is
genuinely consolidated: the mirror import path previously bypassed
`garmin_source_writer` and is now routed through it.

**New modules:**
- `garmin/garmin_source_quality.py` — Leaf-Node (stdlib only). Sole owner of
  source quality assessment. Three public functions:
  `assess_source(raw_data) -> dict` — determines `intraday_present` (bool):
  at least one of `heartRateValues`, `stressValuesArray`,
  `bodyBatteryValuesArray` is non-empty/non-null in the raw API response.
  `assess_source_from_file(source_path) -> dict | None` — reads and assesses
  an existing source file from disk; returns `None` if absent or unreadable.
  `compare_source(existing_assessment, new_assessment) -> str` — Conservative
  guard decision: `"write" | "skip" | "skip_warn"`.

**Guard truth table (Conservative — freeze-when-present):**

| Existing file | New response | Action |
|---|---|---|
| none | any | write |
| intraday absent | present | write |
| intraday absent | absent | write (refresh, harmless) |
| intraday present | present | skip (freeze — first good capture wins) |
| intraday present | absent | skip_warn (degradation blocked — core fix) |

**Changed modules:**
- `garmin/garmin_source_writer.py` — imports `garmin_source_quality`.
  `write_source()` reads existing file → `assess_source_from_file` →
  `assess_source` → `compare_source` → write / skip / skip_warn. Backup
  triggered only on actual write. Leaf-Node status removed (now depends on
  `garmin_source_quality`). `update_log()` gains optional `raw_data` parameter;
  stores `intraday_present` in `source_api_log.json` when provided.
- `garmin/garmin_import_mirror.py` — `_import_source_from_bytes()` now
  delegates to `garmin_source_writer.write_source()` (Option 1). Sole-Write-
  Authority for `source/` is genuinely restored — mirror is no longer a second
  undocumented writer. `_analyse_source_delta_container()` comment corrected:
  "overwrite is safe and correct" replaced by correct description.
- `garmin/garmin_collector.py` — both `update_log()` call sites extended with
  `raw_data=raw_data` so `intraday_present` is recorded on every live sync.
- `compiler/build_manifest.py` — `garmin_source_quality.py` in `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.
- `tests/test_local.py` — Section D extended: `assess_source` (5 checks),
  `compare_source` truth table (6 checks), `assess_source_from_file` (2 checks),
  `write_source` guard behavior (4 checks), `update_log intraday_present`
  (3 checks), `garmin_source_quality` Leaf-Node AST check (1 check).
  Old `garmin_source_writer` Leaf-Node AST check retired (correct — writer
  now imports `garmin_source_quality`).

**Architecture:**
- `garmin_source_quality` is the new Leaf-Node for source quality logic,
  analogous to the role `garmin_quality` plays for `raw/` quality.
- Binary `intraday_present` flag is sufficient for the documented degradation
  cliff (populated arrays → null, ~13× size drop). Numerical scoring is
  explicitly out of scope.
- `source_backfill` timer inherits the guard automatically — it routes through
  `write_source()` unchanged.

**Invariants updated:**
- `garmin_source_writer.py` is Sole Write Authority for `source/` and
  `source_api_log.json` — now genuinely true (mirror bypass closed).
- `source/` files with intraday data are never overwritten by a degraded
  response, regardless of whether the write originates from a live sync or
  a mirror import.

**Test result:** 382 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors

---

## v1.6.0.4.5 — Reliability Audit follow-up

Closes the remaining open items from the Reliability Audit (GP-2) and
Architecture Check (2026-06-20) that were not part of the v1.6.0.4.4 bucket.

**TODO-2 — Panel-Composition documentation:**
- `docs/GLA_PROMPT_1_Architektur-Check.md` — section "Panel-Mixin-Regeln"
  replaced by "Panel-Composition-Regeln (seit v1.6.0)": Assembler model
  documented, `__init__`/MRO rules removed, `setAutoFillBackground` hint added.
  Analysis section 5 updated to match.

**TODO-3 — _QUALITY_RANK isolation comment:**
- `src/garmin/garmin_import_mirror.py` — explanatory comment added to the
  local `_QUALITY_RANK` copy: documents why it is not imported from
  `quality/_maint` directly (facade principle, no sub-package internals),
  and flags it for manual sync if labels change.

**TODO-5 — Per-day quality_log save (GP-2, High):**
- `src/garmin/garmin_collector.py` — `_save_quality_log` now called after
  every successfully processed day in the fetch loop (Step 8), not only at
  loop-end (Step 9). `skip_backup=True` in-loop — backup triggered once in
  Step 9. Save failure aborts the loop immediately (`raise`) — prevents
  accumulation of orphaned raw files without quality_log entries on hard abort.

**B4 — api_call timeout (T3 hang) — assessed, not implemented:**
- Verified locally: `garminconnect.Garmin.__init__` has no `timeout` parameter.
  `curl_cffi.requests.Session.request` supports timeout but is not reachable
  via the public client API. Thread-wrapper approach rejected (zombie threads,
  maintenance overhead). Worst-case analysis: no data loss, no corrupt state —
  atomic write design holds. Parked as ROADMAP note pending library-side support.

**TODO-6 — Silo-Reconciliation-Check — scoped, moved to v1.6.0.4.6:**
- Full scope defined: `garmin_silo_check.py` (new) — read-only drift detection
  across all five silos (`raw/`, `source/`, `summary/`, `quality_log.json`,
  `source_api_log.json`) plus delegation to `regenerate_raw.py` /
  `regenerate_summaries.py` and GUI integration in `panel_archive.py`.
  Moved to v1.6.0.4.6 (replaces Dependency Audit as that version's content).

**Changed modules:** `src/garmin/garmin_collector.py`,
`src/garmin/garmin_import_mirror.py`,
`docs/GLA_PROMPT_1_Architektur-Check.md`

**Test result:** 361 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors

---

## v1.6.0.4.4.1 — Hotfix: Daily Sync Gap Detection
 
Fixes a regression introduced in v1.6.0.4.4 where the automated Daily Sync
aborted with "Gap too large — please open the app" despite the archive being
only 1–2 days behind.
 
## What happened
 
v1.6.0.4.4 added secret redaction (`RedactFilter`) to the daily log file —
a correct security improvement. However, the filter was registered inside
`_start_daily_log()`, which runs before the archive path is written to
`os.environ`. This caused `garmin_config` to be imported with the wrong path,
which in turn caused gap detection to read the wrong `quality_log.json` and
report a false gap count, triggering the hard stop.
 
## Fix
 
`RedactFilter` registration is now deferred to a new `_attach_redact_filter()`
function, called immediately after the archive path is set. Redaction coverage
is identical at runtime — only the registration timing changes.
 
## Affected versions
 
- v1.6.0.4.4 only
## Upgrade
 
Replace `scheduler/daily_update.py` and `version.py` with the files from
this release. No other changes required.
 
---

## v1.6.0.4.4 — Security and Architecture Fixes (small collection)

A collection of small, independent security and verification fixes —
each item built and tested separately, bundled here under one version
number. See `ROADMAP.md` for the original item list (A1–A5, B1–B3, C1–C3).

**A1 — CVE Whitelist Check:**
- `tests/cve_whitelist.py` + `tests/check_cve_whitelist.py` — new.
  `pip-audit -r requirements.txt` wrapped with a whitelist-based verdict
  report (`relevant` / `not_relevant` / `unsure`) — pure report, no
  build-abort criterion. `unsure` findings additionally classified via
  local Ollama (`phi4:14b` default) comparing CVE description against
  actual package usage — upgrades marked `(via Ollama)` for
  traceability. Integrated as final post-build step in `build_all.py`
  (return code ignored); also runnable standalone via `run_cve_check.bat`.
- Real-Ollama verification of the `unsure` path deliberately deferred —
  no synthetic test run; Timo will verify reactively the first time a
  real CVE finding triggers an `unsure` classification.

**A2 — Plotly Hash-Pinning + Runtime Consolidation:**
- Plotly bundling consolidated to a single runtime path with SHA-256
  hash verification — removes the previously unchecked CDN fallback at
  runtime. `REQUIRED_DATA_FILES` in `build_manifest.py` generalized to
  tuples to support the hash alongside the filename.
- `check_deps.py` extended with Plotly version monitoring against the
  pinned hash.

**A3 — Secret Redaction in Logs:**
- `garmin/garmin_redact.py` — new. `redact()` replaces the live
  `GARMIN_EMAIL`/`GARMIN_PASSWORD` value with
  `[GARMIN_EMAIL]`/`[GARMIN_PASSWORD]` placeholders — exact-value match
  only, no pattern matching on exception text. `RedactFilter(logging.Filter)`
  applies `redact()` to every `LogRecord`, never suppresses a record.
- `garmin_collector.py._start_session_log()` — `RedactFilter()` registered
  on the session `FileHandler`.
- `garmin_app_base.py._log()` — calls `redact()` before writing to the GUI
  log widget.
- Registered at the handler level (not the root logger) everywhere it's
  used — deliberate: avoids filtering log records from unrelated/third-party
  loggers that may share the root logger.
- **Follow-up fix (B2, this session):** `daily_update.py._start_daily_log()`
  and `garmin_app_standalone.py._run()` (Queue handler for the GUI log)
  were missing the same registration — an oversight, not an intentional
  scope limit. Both now register `RedactFilter()` on their respective
  handler, consistent with the `garmin_collector.py` pattern.
  `garmin_app.py` (subprocess execution model) does not run its own
  `logging` setup — it already masks `GARMIN_PASSWORD` separately via a
  dict comprehension before logging the ENV snapshot on a failed exit;
  left unchanged.

**A4 — Cloud Folder Notice:**
- `SECURITY.md` — new "Plaintext Archive & Cloud Folders" subsection:
  the live archive (`raw/`, `summary/`, `context_data/`) is not encrypted
  by design; placing `garmin_data/` inside a cloud sync folder uploads
  unencrypted health data automatically — the project cannot detect or
  prevent this. Points to the Mirror feature for safe cloud backup.
- `docs/MINDSET.md` — new "Open archive over at-rest encryption"
  principle explaining the design rationale.
- `README.md` — short pointer to `SECURITY.md#container-security`.
- NTFS ACLs on `garmin_data/` deliberately not implemented — pure user
  responsibility, out of scope.

**A5 — QWebEngineSettings Hardening + HTML/JS Escaping:**
- `src/qwebengine_hardening.py` — new Leaf-Node. `harden(view)` disables
  `LocalContentCanAccessFileUrls`, `LocalContentCanAccessRemoteUrls`,
  `JavascriptCanOpenWindows`, `PluginsEnabled`,
  `JavascriptCanAccessClipboard` on a `QWebEngineView`.
  `JavascriptEnabled` stays enabled — Plotly requires it. Called from
  `panel_home.py` (dashboard viewer) and `garmin_app_base.py` (XLSX
  preview) after each `QWebEngineView()` instantiation. A second,
  previously undocumented `QWebEngineView` instance (XLSX preview) was
  discovered during the dependency scan for this item.
- `dash_layout_html.py`, `dash_plotter_html.py`,
  `dash_plotter_html_mobile.py`, `dash_plotter_html_complex.py` —
  specialist-sourced text fields (labels, units, dates, qualifiers,
  feedback text) now escaped before HTML interpolation (`html.escape()`,
  imported as `html_escape` to avoid a naming collision with an existing
  local variable named `html`) or serialized via `json.dumps()` before
  JS string-literal interpolation (Plotly trace `name`/`hovertemplate`).
  A new JS-side `_escapeHtml()` helper covers HTML assembled at JS
  runtime via `innerHTML` (Explorer sleep quality log).

**B1 — Code Signing Status:**
- Confirmed: the released EXEs are not code-signed, and this is not
  planned — a recurring certificate cost doesn't fit a free,
  single-developer tool. Documented in `SECURITY.md` as an accepted,
  known state (Windows SmartScreen warning on first run is expected
  behaviour).

**B2 — Log Path Credential Audit:**
- Audited all logging entry points for credential exposure. Found and
  fixed the `RedactFilter` registration gap described under A3 above.

**B3 — `base_dir` Cloud-Sync Verification:**
- Confirmed: both default sources (`garmin_config.BASE_DIR`,
  `garmin_app_settings.DEFAULT_SETTINGS["base_dir"]`) resolve to the
  plain home directory (`~/local_archive`) — never a cloud-sync path by
  default. No code change required.

**C1 / C2 — Documentation:**
- `docs/MINDSET.md` — "Open archive over at-rest encryption" principle
  (see A4 above).
- `SECURITY.md` — plaintext status of live data + cloud folder note (see
  A4 above).

**Also verified — ROADMAP "Architecture Check (2026-06-15)" TODO-1:**
- The reported `_should_write` discrepancy between code and
  `test_local.py` does not exist — `garmin_collector._should_write()`
  already returns `label in ("high", "standard")`, matching the test
  exactly. Closed with no code change.

**Test result:** 361 / 261 / 310 / 136 / 42 / 2 — all green, ruff 0 errors.

---

## v1.6.0.4.3 — Global Exception Capture (Crash Visibility)

Forensic analysis of a `Garmin_Local_Archive.exe` Windows crash report
(`0xc0000409` / `FATAL_APP_EXIT`, Qt6Core.dll) found that uncaught exceptions
on the GUI's main thread or in background `threading.Thread` workers
terminated the process via `qFatal`/`abort` with no trace on disk — the GUI
process had no own file logging; only an active sync session ever wrote to
`recent/`/`fail/`/`daily/`. This crash class was invisible by design.

**New modules:**
- `crash_handler.py` — Leaf-Node (stdlib only, no project imports). Installs
  global crash capture at process start: `sys.excepthook` (main thread,
  fail-loud — writes crash log, flushes, best-effort message box, `exit(1)`),
  `threading.excepthook` (daemon workers, fail-isolated — writes crash log,
  thread dies, GUI stays alive — per the existing worker rule: file-only,
  never touches widgets), and an optional `qInstallMessageHandler` for Qt's
  own fatal/critical messages. `QThread` surfaces are intentionally out of
  scope — the project does not use `QThread` (see architecture decision).
  A true native segfault remains outside Python's reach — acknowledged limit.
  Crash logs are written to a **fixed local path**
  (`%LOCALAPPDATA%\GarminLocalArchive\crash\`, falling back to `%TEMP%` then
  cwd) — deliberately *not* under the configurable `base_dir/garmin_data/log/`
  tree, because the crash itself may be caused by `base_dir` being unwritable
  or unreachable. Rotation: `CRASH_LOG_MAX = 30`, analogous to the existing
  `LOG_RECENT_MAX` / `LOG_DAILY_MAX` pattern. Entry-point agnostic
  (`install(log_dir, app_version, exit_on_main)`) so headless entry points
  (`daily_update.py`, `garmin_collector.main()`) can adopt it in a future step.

**Changed modules:**
- `garmin_app.py` — `crash_handler.install(...)` called at the top of
  `__main__`, before `QApplication` is constructed.
- `garmin_app_standalone.py` — same install, identical placement. Both entry
  points written out explicitly per project convention.
- `compiler/build_manifest.py` — `crash_handler.py` added to `SHARED_SCRIPTS`
  (flat src-root, alongside `version.py` / `garmin_app_base.py`) and to
  `SCRIPT_SIGNATURES_BASE` (`["def install"]`).
- `export/backfill_source_backup.py` — two extraneous `f`-string prefixes
  removed (`F541`, no placeholders present) — unrelated ruff finding caught
  by the same test run, fixed in passing.
- `version.py` — `APP_VERSION` bumped to `1.6.0.4.3`.

**What does not change:**
- No change to `garmin_collector`, `daily_update`, or any pipeline module.
- The April `AppHang` cluster and the May `RADAR_PRE_LEAK` event found during
  the same forensic session are separate, unrelated issues and are not
  addressed here — tracked separately for future investigation.

**Test result:** 361 / 261 / 303 / 136 / 42 — all green, ruff 0 errors

---

## v1.6.0.4.2 — Dashboard Output Path Fix

Daily Sync (both GUI and headless `daily_update.py`) wrote dashboard files
to `garmin_data/dashboards/` instead of `dashboards/`. The Dashboard viewer
and Create Reports both read from `dashboards/`, so after a Daily Sync the
viewer showed stale files from the previous manual build — missing the most
recent day.

Root cause: `_run_all_dashboards()` in `panel_outputs.py` and
`_run_dashboards()` in `daily_update.py` both used
`base / "garmin_data" / "dashboards"` as output path. All other consumers
(`_scan_dashboards`, `_scan_xlsx_files`, `_run_dashboards` manual build,
`garmin_mobile_landing.py`) already used the correct `base / "dashboards"`.

**Changed modules:**
- `app/panel_outputs.py` — `_run_all_dashboards()`: output path changed from
  `base / "garmin_data" / "dashboards"` to `base / "dashboards"`
- `scheduler/daily_update.py` — `_run_dashboards()`: output path changed from
  `base / "garmin_data" / "dashboards"` to `base / "dashboards"`
- `garmin_app_base.py` — `_scan_dashboards()` docstring corrected
  ("garmin_data/dashboards/" → "dashboards/")
- `version.py` — `APP_VERSION` bumped to `1.6.0.4.2`

**What does not change:**
- No archive data affected — `garmin_data/` contents untouched
- No dashboard rendering logic changed — only the output directory
- No new dependencies

**Manual cleanup:** Delete `garmin_data/dashboards/` if present — it is no
longer written to and contains stale files.

**Verified via DEPS-Scan (`v1604_01`):** all dashboard path references checked
project-wide. The two fixed locations are the only ones using the wrong path.

---

## v1.6.0.4.1 — Login Failure Masking Fix

`daily_update.py` reported success even when the entire Garmin sync failed
due to a login error (e.g. MFA required in headless mode, or a rate-limited
token probe after an invalid refresh token). Root cause: `garmin_collector.main()`
caught `GarminLoginError` and returned silently — no exception, no exit code —
so every caller saw a normal return and reported success regardless.

**Changed modules:**
- `garmin/garmin_collector.py` — `main()`: `except api.GarminLoginError` branch
  now calls `sys.exit(1)` instead of a bare `return`, after the session log is
  closed exactly as before. Matches the existing pattern already used in the
  bulk-import branch of the same function.
- `version.py` — `APP_VERSION` bumped to `1.6.0.4.1`.

**Verified via DEPS-Scan (`v16005_01`):** isolated to this one location —
`garmin_api.py`'s own `except GarminLoginError: raise` already re-raises
correctly, no shadow copies elsewhere. All three real callers of `main()`
already handle a non-zero exit correctly, no changes needed there:
`daily_update.py` (`except SystemExit`), T1/T2 GUI subprocess
(`proc.returncode` check), T3 Standalone (`except SystemExit` around
`module.main(...)`).

**What does not change:**
- No callback/MFA handling added — headless mode still cannot resolve an
  MFA challenge interactively. The fix only makes that failure visible
  (Exit-Code 3, `daily_update.py` log landet unter `log/fail/`) statt stumm.
- No GUI behaviour change.

---

## v1.6.0.4 — Source Replay + Source Status + Source Backup

Closes the source archive triad: replay from source, backup of source,
and live status display. Together with v1.6.0.2 (Source Archive) and
v1.6.0.3 (Source Backfill), `source/` is now a fully protected and
operationally visible data silo.

**New modules:**
- `export/regenerate_raw.py` — Source Replay. Reads `garmin_data/source/`,
  runs each day through `normalize()` → `assess_quality()` → `write_day()` →
  `_upsert_quality()`. Identical output to a live pipeline run. No API call,
  no login required. Analog to `export/regenerate_summaries.py`.
  Flags: `--dry-run` (show without writing), `--date YYYY-MM-DD` (single day).
  Downgrade protection: days with a higher quality label in `quality_log.json`
  than the replay produces are skipped entirely — no file write, no log update.
  Protects days captured at full intraday resolution before Garmin's 180-day
  degradation boundary. Documented Exception: reads/writes `quality_log.json`
  directly via `_load_quality_log` / `_save_quality_log` — offline maintenance
  utility, outside the live pipeline.
- `garmin/garmin_backup_source.py` — Source Backup. Sole Owner of
  `garmin_data/backup/source/`. Leaf-Node: only `garmin_config` + stdlib.
  Three public functions: `backup_source(date_str)` (copy one file after write),
  `backfill_source()` (copy all missing files, one-time), `check_source_backfill_needed()`
  (count without copying). Flat copy strategy — no monthly consolidation.

**Changed modules:**
- `garmin/garmin_source_writer.py` — lazy import of `garmin_backup_source`
  after each successful `write_source()`. Non-fatal — pipeline continues on
  failure. Analog to `garmin_writer` → `garmin_backup`.
- `garmin/garmin_config.py` — `SOURCE_BACKUP_DIR = BACKUP_DIR / "source"` added.
- `compiler/build_manifest.py` — `garmin_backup_source.py` added to
  `SHARED_SCRIPTS` and `SCRIPT_SIGNATURES_BASE`.
- `app/garmin_app_controller.py` — `get_source_stats(s)` added. INTENTIONAL
  DIRECT READ: scans `source/` directory, returns `{"total": int, "present": int}`.
  `total` = all source files on disk (no time limit). `present` = source files
  within the last 180 calendar days. No `quality_log.json` access required.
- `app/panel_home.py` — Source status label `_info_source` added to Row 1 of
  the Archive Status block (inline with fail / Recheck / Missing), separated
  by `||`. Always displayed as `Source: N days · M/180d`.
- `app/panel_archive.py` — `_refresh_archive_info()` extended: calls
  `get_source_stats()`, formats and sets `_info_source` label.

**Invariant refinement:**
- Previous: `garmin_backup.py` — Sole Owner of `garmin_data/backup/`
- Revised: `garmin_backup.py` — Sole Owner of `backup/raw/` + `backup/log/`
           `garmin_backup_source.py` — Sole Owner of `backup/source/`

**Documented Exception added:**
- `regenerate_raw.py` — reads `quality_log.json` directly and writes via
  `garmin_writer`. Offline maintenance utility, not a runtime path.
  Analog to existing exception for `regenerate_summaries.py`.

**Test result:** 344 / 261 / 303 / 136 / 42 — all green, ruff 0 errors

---

## v1.6.0.3 — Source Backfill (Background Timer)

Closes the gap between the `source/` archive introduced in v1.6.0.2 and
historical API days fetched before v1.6.0.2 was active.

**What is added:**
- `garmin_collector._run_source_backfill(client, quality_data)` — re-fetches
  API days passed via `GARMIN_SYNC_DATES` + `GARMIN_SOURCE_BACKFILL=1`. Called
  at step 5c in `main()` (after login, after device_id backfill). Non-fatal:
  per-day errors are logged as warnings, loop continues. No-op if `SYNC_DATES`
  is empty.
- `app/garmin_app_controller.timer_run_source_backfill(s)` — identifies api-sourced
  days within the last 180 days that have no `garmin_data/source/` file. Returns
  sorted list oldest-first. `None` if complete. INTENTIONAL DIRECT READ.
- `app/panel_timer.py` — `source_backfill` added as fourth timer mode in
  `_mode_cycle`. Oldest-first pick (`days[:n_days]`), analogous to bulk.
  `GARMIN_SOURCE_BACKFILL=1` set only when `mode == "source_backfill"`.
  `_timer_run_source_backfill()` delegate added. Timer button text fixed:
  `"⏱  Timer: On"` when active (was missing), `"⏱  Syncing · N"` during sync.
- `compiler/build_manifest.py` — signature check for `_run_source_backfill`.

**Architecture:**
- Candidates are determined by the Controller (`timer_run_source_backfill`),
  not by the Collector — consistent with repair / quality / fill / bulk pattern.
- `_run_source_backfill()` reads `cfg.SYNC_DATES` directly — no internal
  candidate scan, no new quality log fields.
- `source/` Sole-Write-Authority unchanged: only `garmin_source_writer.write_source()`
  writes source files — backfill uses the same call as the live pipeline.

**What does not change:**
- `garmin_source_writer.py` — untouched
- `quality_log.json` — no new fields; existing entries updated as normal
- Regular GUI sync and `daily_update.py` — unaffected

**Test result:** `344 / 261 / 303 / 136 / 42 — all green, ruff 0 errors`

---

## v1.6.0.2 — Source Archive

Introduces the third data silo: `garmin_data/source/` stores the unmodified
API response for every day, permanently and before any pipeline processing.
`source_api_log.json` records fetch metadata per day (validator status,
endpoints, byte size). Mirror container extended to include the source section.
Mirror import extended to transfer source files to the target device.

**Motivation:** Garmin silently degrades historical intraday data resolution
over time. What is not saved today cannot be recovered later. `source/` is the
permanent, pipeline-independent record of what the Garmin API actually delivered.
`raw/` is derived from it and reproducible; `source/` is not.

**New modules:**
- `garmin/garmin_source_writer.py` — Sole Owner of `garmin_data/source/` and
  `source_api_log.json`. Leaf-Node: only `garmin_config` + stdlib. Two public
  functions: `write_source()` (called before validator, atomic write) and
  `update_log()` (called after validator, records status + endpoints). Both
  non-fatal — failures are logged as warnings, pipeline continues.

**Changed modules:**
- `garmin/garmin_config.py` — `SOURCE_DIR` and `SOURCE_API_LOG` constants added.
- `garmin/garmin_collector.py` — `_fetch_and_assess()` extended with two non-fatal
  call sites: `write_source()` before `validator.validate()`, `update_log()` after
  the critical check. Both wrapped in `try/except` — pipeline never blocked.
- `garmin/garmin_container.py` — `_SECTIONS` extended with `"source"`.
  `_classify_file()` extended to classify `garmin_data/source/**` into the
  `source` section. Existing containers without the section import silently.
- `garmin/garmin_import_mirror.py` — source section added to container import
  path: `list_files("source")`, `_analyse_source_delta_container()`,
  `_import_source_from_bytes()`. `dry_run` return dict extended with
  `source_to_copy`. Return dict extended with `source_copied`.
- `compiler/build_manifest.py` — `garmin_source_writer.py` in `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.
- `tests/test_local.py` — new Section D (18 checks): `SOURCE_DIR` + `SOURCE_API_LOG`
  path derivation, `write_source` round-trip + overwrite + error cases, `update_log`
  round-trip + overwrite + multi-date, Leaf-Node AST check.

**Invariants:**
- `source/` contains exclusively live API responses. Bulk import never writes
  to `source/` — not even during backfill.
- Days without a `source/` file after the 180-day window cannot be recovered
  (Garmin degrades intraday resolution permanently beyond that boundary).
- `garmin_source_writer.py` is the sole write authority for `source/` and
  `source_api_log.json`. No other module writes to these paths.

**Windows note:** `os.fsync()` is silently ignored on Windows filesystems that
do not support it (`OSError` caught). `os.replace()` provides atomicity on all
platforms.

**Test result:** 339 / 261 / 303 / 128 / 42 — all green, ruff 0 errors

---

## v1.6.0.1 — Repository /src Layout

Structural refactoring — no logic changes, no new features.

All source files moved from repo root into `src/`. Repository root now contains
only `README.md`, `SECURITY.md`, and `requirements.txt`.

**What changed:**
- New `src/` folder — contains all modules, folders, scripts, and assets
- `README.md`, `SECURITY.md`, `requirements.txt` — remain in repo root
- `compiler/build.py` + `compiler/build_standalone.py` — README path updated:
  `root / "README.md"` → `root.parent / "README.md"` (README lives one level above `src/`)
- `compiler/build.py` + `compiler/build_standalone.py` — comments updated:
  `# compiler/ → Root/` → `# compiler/ → src/`
- `README.md` — all screenshot paths updated: `screenshots/` → `src/screenshots/`

**What did not change:**
- No module imports
- No `sys.path` anchors in pipeline modules
- No test paths
- No architectural invariants

**Test result:** 316 / 261 / 303 / 128 / 42 — all green, ruff 0 errors

---

## v1.6.0 — Home Tab & Daily Workflow Refactor

Complete redesign of the main window layout. The Settings sidebar is removed;
all panels move into a scrollable Settings tab. A new fixed top area shows
connection status, archive stats, and the device table at all times — visible
regardless of which tab is active. Daily actions (Sync, Mirror, Timer) are
permanently accessible without switching tabs.

**New modules:**
- `app/panel_home.py` — owns the fixed top area (connection indicators,
  archive status labels, device table) and the Home tab content (Dashboard
  viewer). Also owns the Daily Sync orchestration (gap detection → Garmin
  Sync → Context Sync → Create All), Mirror dialogs, and the Daily Actions
  button group.

**Changed modules:**
- `garmin_app_base.py` — `_build_ui()` rebuilt: Settings sidebar + Splitter
  removed; new fixed top (`_panel_home`) above a QTabWidget with three tabs:
  Dashboard / Files / Settings. Log height reduced to 90px. Default dashboard
  (`health_garmin`) and default XLSX (`overview_garmin`) selected on startup.
- `app/panel_connection.py` — `_conn_indicators` dict, all `_info_*` labels,
  and `_info_device_table` removed (moved to `panel_home`). `_set_indicator()`
  now delegates to `self._app._panel_home._conn_indicators`.
- `app/panel_archive.py` — `_refresh_archive_info()` `_update()` lambda
  retargeted from `panel_connection` to `panel_home`.
- `app/panel_timer.py` — `_timer_update_btn()` and countdown lambda retargeted
  to `self._app._panel_home._timer_btn`.
- `garmin_app_standalone.py` — `days_left` lambda retargeted to
  `self._app._panel_home._timer_btn`.
- `garmin_app_screenshot.py` — `_scan_dashboards()` retargeted to
  `self._panel_home._dash_combo` / `._dash_view`.
- `tests/test_qt_app.py` — `TestPanelConnection` indicator tests updated:
  `app_mock._panel_home._conn_indicators` pre-populated with real QLabel
  objects so `_set_indicator()` can call `setStyleSheet()` on real widgets.
- `version.py` — bumped to `1.6.0`.
- `ruff.toml` — added; `E501` and `W292` ignored globally. Per-file ignores
  for test files, entry points, and intentional Easter Egg style.

**Test result:** 316 / 261 / 303 / 128 / 42 — all green, ruff 0 errors

---

## v1.5.9 — Standalone EXE: --onedir Migration + Code-Hygiene

Replaces `--onefile` with `--onedir` for T3.1 (GUI standalone), eliminating
per-launch extraction to `%TEMP%\_MEIxxxxxx`. Startup time drops significantly.
T3.2 (`daily_update.exe`) stays `--onefile` — Task Scheduler launches are
infrequent and startup time is irrelevant there. Also fixes two real `NameError`
bugs found via `ruff`, cleans the entire codebase to `ruff check . → 0 errors`,
and removes zombie `export/` references from the build system. Additionally
upgrades the mobile landing page (`index.html`) to a single-page layout — both
dashboards are now embedded directly, making them accessible on OneDrive mobile
without broken relative links.

**Changed modules:**
- `compiler/build_standalone.py` — `build_exe()` gets `onedir` parameter;
  T3.1 uses `--onedir`, T3.2 stays `--onefile`. `cmd.append("--windowed")`
  replaces position-dependent `cmd.insert(3, ...)`. `build_combined_zip()`
  packs the `Garmin_Local_Archive_Standalone/` folder recursively; `daily_update.exe`
  remains flat in ZIP root. Abort with message if folder/EXE missing.
- `tests/test_build_output.py` — T3 checks updated for `--onedir` folder
  structure: `_T3_DIR`, `_T3_EXE`, `_T3_BUILT` use new paths; Section 7
  checks for `_internal/` and updated ZIP paths.
- `context/context_collector.py` — `prev_ds = dates[0]` initialised before
  `for` loop in `_split_into_segments()` — fixes `NameError` on first location
  segment change.
- `scheduler/daily_update.py` — `import json` added to top-level imports —
  fixes `NameError` in `_check_schema_migration()` and `_check_version()`.
- `garmin/garmin_collector.py` — `QUALITY_RANK` imported from `garmin_quality`
  facade (not directly from `quality._maint`). Duplicate import and `known_dates`
  unused variable removed.
- `garmin/quality/_stats.py` — unused `device_map = {}` removed.
- `app/panel_archive.py` — unused `total` variable removed; theme variable
  assignments split onto separate lines (E702).
- `compiler/build.py` — `export/` mkdir removed from `prepare_scripts_dir()`;
  unused `sep` and `scripts_dir` variables removed.
- `garmin_app.py` — `"export"` removed from `script_path()` subfolder list.
- `garmin_app_standalone.py` — `"export"` removed from `script_path()` subfolder list.
- `layouts/dash_layout_html.py` — duplicate `get_plotly_cdn()` definition removed (F811).
- `layouts/garmin_mobile_landing.py` — single-page embed: `_render_html()`
  accepts `dash_mobile` + `dash_sleep` parameters; `_read_dash()` extracts
  `<script>` tags from `<head>` + `<body>` content (drops `<style>` to prevent
  CSS override); dashboard buttons switch inline views via JS; `html` element
  gets explicit dark background. `write_index_html()` also triggered from
  `panel_outputs.py` after "Create Dashboards" — ensures fresh dashboard content.
- `app/panel_outputs.py` — `write_index_html()` called in `on_done` after
  `_scan_dashboards()` to regenerate `index.html` with freshly built dashboards.
- `dashboards/dash_runner.py` — `# noqa: E731` on lambda noop.
- `dashboards/health_garmin_html-json_dash.py` — `# noqa: F841` on `vo2_raw`.
- `ruff.toml` (new) — `per-file-ignores` for `garmin_quality.py` (F401),
  `tests/*` (E712, E402, E702, E731, F841), entry points (E402), `tools/*` (E402),
  `garmin_extended_anaysis.py` (E701, F841, B, SIM),
  `sleep_recovery_context_dash.py` (E701).
- `scheduler/daily_update.py` — `yesterday` unused variable removed.
- `version.py` — `APP_VERSION` → `"1.5.9"`.

**Test result:** 316 / 261 / 303 / 128 / 42 — all green

---

## v1.5.8.1 — Mobile Landing Page

Adds a local mobile landing page (`index.html`) that is automatically
generated in `BASE_DIR/dashboards/` after every sync and on app start.
The page shows archive status, device table, and links to the two main
dashboards — readable in any mobile browser via local file access.

**New modules:**
- `layouts/garmin_mobile_landing.py` — generates `index.html` with archive
  status and device table embedded as a JS variable (`window.__GLA_STATUS__`).
  No `fetch()` — works with `file://` protocol. `write_index_html(base_dir)`
  always regenerates; `ensure_index_html(base_dir)` writes only if absent.

**Changed modules:**
- `app/panel_archive.py` — `_refresh_archive_info()` calls
  `write_index_html(base_dir)` after every refresh.
- `garmin_app_base.py` — `QTimer.singleShot(400, self._ensure_mobile_landing)`
  added to `__init__`. New method `_ensure_mobile_landing()` writes
  `index.html` on app start if not yet present.
- `compiler/build_manifest.py` — `layouts/garmin_mobile_landing.py` added
  to `SHARED_SCRIPTS` and `SCRIPT_SIGNATURES_BASE`.

**Test result:** 316 / 261 / 303 / 128 / 42 — all green (unchanged)

---

## v1.5.8 — In-App File Viewer

Third tab ("Files") added to the existing `QTabWidget` (Tab 1 "Actions",
Tab 2 "Dashboards"). Renders XLSX dashboard output directly inside the app
via openpyxl + `QWebEngineView`. Sheet selector appears automatically for
multi-sheet files. Chart sheets (`- Chart` suffix) are filtered out — only
data sheets shown. Sleep phase bar enhanced with per-cell letters (D/L/R/A)
in contrast color. No new Python dependencies — openpyxl and PyQt6-WebEngine
already in stack.

**Changed modules:**
- `garmin_app_base.py` — Tab 3 "Files" added to `QTabWidget`. `QComboBox`
  (`_xlsx_combo`) scans `dashboards/*.xlsx` on tab switch via `_on_tab_changed()`.
  Second `QComboBox` (`_sheet_combo`) for sheet selection — hidden for
  single-sheet files, visible for multi-sheet. `QWebEngineView` (`_xlsx_view`)
  renders selected sheet as HTML. "Open File" button calls `os.startfile()`.
  `_render_sheet()` writes HTML to `%TEMP%/gla_xlsx_view.html` and loads via
  `setUrl()` — avoids `setHtml()` stale-render on large sheets.
  Single-char columns (D/L/R/A phase bar) detected automatically and rendered
  with `width:10px` in HTML. `_right_tabs` stored as `self._right_tabs`.
- `app/panel_outputs.py` — `_scan_xlsx_files()` called after `_scan_dashboards()`
  in `on_done` — Tab 3 refreshes automatically after dashboard build.
- `garmin_app_screenshot.py` — `_scan_xlsx_files()` override: loads
  `DEMO_XLSX_HTML` (10 demo rows: Date, Steps, Resting HR, Body Battery,
  Sleep, Quality) into Tab 3. No file I/O. Docstring updated.
- `layouts/dash_plotter_excel.py` — `_write_sleep_sheet()`: every phase-bar
  cell now contains a letter (D/L/R/A) in contrast color. Phase-bar column
  width reduced from 1.5 to 1.0.
- `tests/test_qt_app.py` — `_xlsx_combo` + `_xlsx_view` added to
  `test_all_panels_created`.

**What does not change:**
- Tab 1 and Tab 2 — unchanged
- Dashboard build pipeline — no changes to specialists or plotters
- JSON workflow — Open Folder in Tab 1 remains the access path
- No new Python dependencies

**Test result:** 316 / 261 / 303 / 128 / 42 — all green

**Mirror Fixes**

Two bugs fixed in the mirror pipeline, no new version.

**T2 Mirror — cryptography hidden imports:**
`compiler/build.py` was missing five `--hidden-import` entries for
`cryptography.hazmat` submodules (`kdf.pbkdf2`, `kdf.hkdf`,
`ciphers.aead`, `hmac`, `hashes`). All are imported lazily inside
functions in `garmin_container.py` — PyInstaller did not detect them
automatically. Result: T2 Mirror returned `0 files packed, 1 errors`
while T1 and T3 worked correctly.

**device_table.json added to mirror container:**
`garmin_container._classify_file()` extended to include
`device_table.json` in the `quality_log` section alongside
`quality_log.json`. `unlock_meta()` updated to extract
`quality_log.json` by explicit key instead of `next(iter())`.
`garmin_import_mirror._run_import_container()` gains Step 8:
`_restore_device_table()` writes `device_table.json` from the
fulfilled order to `garmin_data/log/` on the target device. Silent
if absent (older containers).

**Changed files:**
- `compiler/build.py` — 5 hidden-imports added for `cryptography.hazmat`
- `garmin/garmin_container.py` — `_classify_file()`, `unlock_meta()`
- `garmin/garmin_import_mirror.py` — `_run_import_container()`, `_restore_device_table()` (new)

---

## v1.5.7.2 — Legacy Quality Label Cleanup

Removes all remaining references to the old `high / medium / low` quality label
system from productive code. The `high / standard / failed` system introduced in
v1.5.7 was complete in logic but still had stale strings in docstrings, a
dead filter branch, and a now-obsolete config constant. No behavior changes.

**Changed modules:**
- `garmin/garmin_collector.py` — `_fetch_and_assess()` docstring: label
  string updated to `"high" | "standard" | "failed"`.
- `garmin/quality/_scan.py` — `get_low_quality_dates()`: docstring, filter
  condition (`q in ("low", "failed")` → `q == "failed"`), and log message
  updated. Dead `"low"` branch removed — `assess_quality()` never returns
  `"low"` since v1.5.7.
- `garmin/quality/_stats.py` — `get_archive_stats()` docstring: `medium int`
  and `low int` entries replaced with `standard int`.
- `garmin/garmin_config.py` — `LOW_QUALITY_MAX_ATTEMPTS` constant and its
  3-line comment block removed. Was kept for test backward-compatibility;
  no longer needed.
- `tests/test_local.py` — `check("LOW_QUALITY_MAX_ATTEMPTS = 3", ...)` removed
  from Section 1. Section 4 loop already hardcoded in a prior session.

**Test result:** 316 / 261 / 303 / 128 / 42 — all green

---

## v1.5.7.1 — Mirror Import Patch

Fixes two gaps in `garmin_import_mirror.py` discovered during the v1.5.7
architecture review. Both import paths now correctly extract and forward
`device_id` / `device_name` from raw files to `_upsert_quality` — imported
days are no longer written with `device_id = None` regardless of device info
present in the raw data. The backfill on next Garmin sync still resolves
any entries already imported without device info, so no data loss occurs.

**Changed modules:**
- `garmin/garmin_import_mirror.py` — new private helper `_extract_device(raw)`.
  Extracts `device_id` + `device_name` from
  `training_status → mostRecentTrainingStatus → recordedDevices[0]`.
  Mirrors `garmin_collector` device lookup — no `latestTrainingStatusData` Keys
  fallback. Both `_import_raw_from_bytes` (container path) and `_import_raw_folder`
  (deprecated folder fallback) now call `_extract_device()` and pass the result
  to `_upsert_quality`. `prev_high` intentionally not forwarded — mirror import
  has no prior-day context.

**Test result:** 317 / 261 / 303 / 128 / 42 — all green

---

## v1.5.7 — Quality System Redefinition

Replaces the `high / medium / low` quality label system with `high / standard / failed`.
Archive analysis showed that 2492 of 2725 entries were `medium` — the label was
factually incorrect. The new `standard` label describes what the device actually
delivers: full daily data without intraday. Device identity (`device_id`,
`device_name`) is now stored per entry, sourced from
`training_status → recordedDevices`. A `device_table.json` written after each
sync drives a new device breakdown table in the GUI. Startup integrity check
now correctly uses the configured data directory instead of the default path.

**New files:**
- `garmin_data/log/device_table.json` — written by `garmin_quality` after each
  sync. Read directly by `panel_archive` (INTENTIONAL DIRECT READ). JSON array
  sorted by `date_to` descending; `__total__` row at end filtered by GUI.

**Changed modules:**
- `garmin/quality/_assess.py` — `assess_quality()`: `medium`/`low` → `standard`.
  Sleep-distinction removed (was only needed for medium vs. low).
- `garmin/quality/_maint.py` — `QUALITY_RANK = {"high": 2, "standard": 1, "failed": 0}`
  (public, no leading underscore). `_upsert_quality()`: `device_id` + `device_name`
  parameters added; `standard` recheck logic: `day_age < 180 AND prev_high`.
  `record_attempt()`: `device_id` + `device_name` + `prev_high` forwarded.
  New `set_unknown_device_name(data, name)`: sets `device_name` on all entries
  with `device_id = None`. Returns count updated.
- `garmin/quality/_io.py` — on-load migration: `device_id = None` + `device_name = ""`
  added to entries missing these fields. New `save_device_table(data)`: groups
  entries by `device_id`, writes `device_table.json` atomically.
- `garmin/quality/_stats.py` — counts: `medium`/`low` → `standard`.
- `garmin/garmin_quality.py` — facade exports: `QUALITY_RANK` (was `_QUALITY_RANK`),
  `save_device_table`, `set_unknown_device_name` added.
- `garmin/garmin_config.py` — `INTRADAY_RETRY_WINDOW_DAYS = 180` added.
  `DEVICE_TABLE_FILE = LOG_DIR / "device_table.json"` added.
- `garmin/garmin_collector.py` — `_should_write`: `("high", "standard")`.
  Fetch loop: `device_id`/`device_name` lookup from `recordedDevices`.
  `prev_high` lookup per day. Retry window uses `cfg.INTRADAY_RETRY_WINDOW_DAYS`.
  `_QUALITY_RANK` local dict removed → `from quality._maint import QUALITY_RANK`.
  `_run_self_healing()`: recheck only on `failed`.
  `run_import()`: skip condition `("high", "standard")`.
  Backfill (Step 5b in `main()`): entries with `device_id = None` resolved from
  raw files on first run. 881 entries set (fenix 7X + fenix 5x).
- `garmin/garmin_import_mirror.py` — `_QUALITY_RANK`: `{"high": 2, "standard": 1, "failed": 0}`.
- `app/garmin_app_controller.py` — `check_integrity()`: sets `GARMIN_OUTPUT_DIR`
  from `s["base_dir"]` and reloads `garmin_config` before check. Fixes false
  positives when configured data directory differs from default.
- `app/panel_archive.py` — device table rendered in `_refresh_archive_info()`.
  Double-click on "unknown" row opens `QInputDialog` → calls
  `set_unknown_device_name()` → saves log + device table → refreshes.
  `_check_failed_days_popup`: filter `== "failed"` (was `in ("failed", "low")`).
- `app/panel_connection.py` — `_QCOLORS`: `"standard"` replaces `"medium"`/`"low"`.
  `_info_qdots` loop: `("standard", "std")`. Row 3: `QTableWidget` 6 columns
  (From / To / Device / High / Standard / Total). All columns `ResizeToContents`.
- `garmin_app_screenshot.py` — demo values updated for new label set.
- `tests/test_local.py` — all `medium`/`low` expectations updated to `standard`.
  New baseline: 317 checks.
- `tools/migrate_quality_reclassify_v2.py` — one-time migration script.
  2727 entries: 218 high → unchanged, 2509 medium/low → standard. Run before
  session start.

**Known devices in archive:**
- fenix 7X Sapphire Solar (ID: 3425438179) — 2025-03-10 → 2026-06-06
- fenix 5x (ID: 3952922857) — 2024-01-01 → 2025-03-02
- vívoactive 3 era (device_id = None) — 2018-12-19 → ~2024

**Test result:** 317 / 261 / 303 / 128 / 42 — all green

---

## v1.5.6.3 — Code Quality Patch

Maintenance release addressing seven findings from two independent code reviews
of v1.5.6.1 (Claude direct review + Gemini blind review). No new features, no
pipeline changes, no user-visible behaviour changes. One real behaviour change:
the validator now returns `critical` instead of `ok` when its schema file is
missing — pipeline already handles `critical` (day flagged for recheck, no
data lost).

The largest change architecturally is F4: the `_STOP_EVENT` monkey-patching
via `module.__dict__` is replaced by explicit module-level setters
(`set_stop_event(ev)`) on both `garmin_collector` and `garmin_api`. The
collector is now the stop orchestrator — it distributes the event to
`garmin_api`. The Standalone GUI no longer needs to know about `garmin_api`.

**Changed modules:**
- `garmin/garmin_collector.py` — `_QUALITY_RANK` removed (now imported from
  `quality._maint`). `_STOP_EVENT` global removed; `_stop_event` module
  variable + `set_stop_event(ev)` added; setter distributes to `garmin_api`.
  `main(stop_event=None)` and `run_import(..., stop_event=None)` accept and
  register the event.
- `garmin/garmin_api.py` — `_STOP_EVENT` global removed; `_stop_event` +
  `set_stop_event(ev)` added (same pattern as collector). 429 rate-limit
  handler reads `_stop_event` directly instead of `globals().get()`. Module
  docstring updated.
- `garmin/garmin_validator.py` — Fail-Open → Fail-Closed: schema absent now
  returns `critical` with a `missing_required` issue on `field: "schema"`,
  not `ok`.
- `garmin/garmin_normalizer.py` — `log.warning()` added in `summarize()` when
  `sleepTimeSeconds` is `None` (structurally absent). `None`-trigger only;
  `0` is a legitimate value (no sleep recorded) and stays silent.
- `app/garmin_app_controller.py` — three `INTENTIONAL DIRECT READ` comments
  extended with the `os.replace()` atomicity rationale (reader always sees
  either the old or the new complete file).
- `app/panel_archive.py` — `INTENTIONAL DIRECT READ` comment added to
  `_check_failed_days_popup()` quality_log.json read (was undocumented).
- `garmin_app_standalone.py` — `module.__dict__["_STOP_EVENT"]` double
  injection (collector + garmin_api) replaced by
  `module.main(stop_event=effective_stop)`. The GUI no longer references
  `garmin_api` directly.
- `scheduler/daily_update.py` — `SETTINGS_FILE` literal and local
  `DEFAULT_SETTINGS` removed. `_load_settings()` delegates to
  `garmin_app_settings.load_settings()` (lazy import after `_setup_paths()`)
  and filters to `_DAILY_SETTINGS_KEYS` — the eight fields the scheduler
  actually uses. Removed keys (`sync_mode`, `timer_*`, `mirror_dir`,
  `date_from/to`, `sync_auto_fallback`) were either ignored by `_build_env`
  or never read.
- `docs/REFERENCE_GARMIN.md` — `set_stop_event(ev)` documented for both
  `garmin_api` and `garmin_collector`. `_is_stopped()` description updated.

**Test changes:**
- `tests/test_local.py` Section 6: `_STOP_EVENT` direct assignment replaced
  by `set_stop_event(ev)`. Two new checks verify cross-module distribution
  (collector → garmin_api) and bilateral clearing on `set_stop_event(None)`.
  Explicit cleanup at section end against state leak.
- `tests/test_local.py` Section 9: F6 fail-closed test added with guaranteed
  schema restore via `reload_schema()`.

**What does not change:**
- Pipeline behaviour — identical (F6 only affects schema-absent edge case)
- Quality log format — unchanged
- 429 self-stop chain — preserved, same event object across both modules
- Subprocess mode (T1/T2) — `stop_event=None`, behaviour identical to before
- User-visible behaviour — unchanged

**Test result:** 316 / 261 / 303 / 128 / 42 — all green

---

## v1.5.6.2 — assess_quality Fix + Retroactive Migration

Bug fix in `assess_quality()`: the inner condition `if has_sleep or has_steps:`
was always True when reached via `has_steps`, making `return "low"` unreachable.
Days with only `totalSteps` and no sleep or restingHR were silently classified
as `medium`. Fixed to `if has_sleep or has_hr_resting:`. One new test case added.
Standalone migration script provided for retroactive correction of existing entries.

**New modules:**
- `tools/migrate_quality_reclassify.py` — standalone migration script. Reads
  `quality_log.json`, re-runs `assess_quality()` on all `medium` entries, corrects
  any that now return `"low"`. Creates timestamped backup before writing.
  Run once with app closed. Not in `build_manifest.py` — one-time tool.
- `tools/extract_device_per_day.py` — analysis tool. Extracts recorded device per
  day from all raw files. Output: CSV + console summary (device, days, avg/min/max KB).
  Used for archive-quality analysis. Not in `build_manifest.py`.

**Changed modules:**
- `garmin/quality/_assess.py` — one-line fix: `if has_sleep or has_steps:` →
  `if has_sleep or has_hr_resting:`. Steps alone no longer sufficient for `medium`.
- `tests/test_local.py` — one new check: `assess: steps-only → low`.

**Note:** Migration script ran against live archive — 0 entries corrected. The
specific bug pattern (steps-only, no sleep, no restingHR) does not occur in this
archive because Garmin always includes sleep and stress blocks. Fix remains correct
for archives where the pattern may occur.

**Test result:** 310 / 261 / 303 / 128 / 42 — all green

---

## v1.5.5.4 — Test Infrastructure Consolidation + Maps Logging + AST-Guard

Duplicate test-tracking boilerplate extracted from four manual test scripts
into a shared `tests/support.py` module. All four suites now import `check()`,
`section()`, and `summary()` as free functions — no inline implementation.
Summary output unified to a single format. Four Maps modules gain `log.warning()`
in their `_read_field()` except-blocks — previously silent JSON/OS errors are now
observable. New AST-based regression guard in `test_qt_app.py` verifies that
`scheduler/daily_update.py` stays GUI-free.

---

## v1.5.6.1 — Encrypted Mirror Container

Replaces the plain mirror folder with a single encrypted container file (`mirror.gla`).
Health data on USB, NAS, or a cloud folder of choice is unreadable without the password.
No cloud dependency, no third-party service — extends the local-first philosophy to transport.

**New modules:**
- `garmin/garmin_container.py` — Sole Owner of `mirror.gla`. Section-based AES-256-GCM
  container with independent encrypted sections (quality_log, raw, summary, context).
  Key derivation: PBKDF2-HMAC-SHA256 (600,000 iterations) → master key → HKDF-Expand →
  per-section keys. Plaintext header authenticated via HMAC-SHA256. Atomic writes via
  `mirror.gla.tmp` → `fsync()` → `os.replace()`. API: `lock()`, `unlock_meta()`,
  `fulfill_order()`, `is_container()`, `list_files()`.

**Changed modules:**
- `garmin/garmin_mirror.py` — delegates to `garmin_container.lock()` instead of
  `shutil.copy2()`. `password` parameter added. `_collect_files()`, `_remove_empty_dirs()`,
  `_run_spot_check()`, `_write_mirror_meta()` removed — superseded by container logic.
  `is_reachable()` now checks parent directory existence (container file may not exist yet
  on first mirror). `is_import_ready()` uses `garmin_container.is_container()`.
- `garmin/garmin_import_mirror.py` — reads via `garmin_container.unlock_meta()` and
  `fulfill_order()`. `list_files()` used for context delta analysis (header-only, no
  decryption). Summary fast-path: if `schema_version` matches, summary taken from container;
  otherwise `summarize()` regenerated on target. Plain folder fallback retained for
  v1.5.6 compatibility (`detect_source()` dispatches). `password` parameter added.
  Dead import (`garmin_config`) removed.
- `app/panel_archive.py` — `MirrorPasswordDialog` added (password entry + optional WCM
  save checkbox). `_on_mirror()`: WCM lookup first, dialog if not stored, password forwarded
  to `run_mirror()`. `_on_import_mirror()`: always manual password dialog (no WCM),
  password forwarded to `run_import_mirror()`. Spot-check output removed from log.
  Module-level WCM helpers: `_archive_load_mirror_password()`, `_archive_save_mirror_password()`.
- `compiler/build_manifest.py` — `garmin_container.py` added to `SHARED_SCRIPTS` and
  `SCRIPT_SIGNATURES_BASE`.
- `tests/test_local.py` — Section C rewritten for container model. `_collect_files`,
  `_remove_empty_dirs`, `copied/skipped/deleted` tests replaced by container round-trip
  tests: `is_reachable`, `is_import_ready`, `run_mirror` → `mirror.gla`, `is_container`.
  `sys.modules` stubs for `version` + `garmin_normalizer` added (test path isolation).

**What does not change:**
- Import protocol from delta analysis onward — identical to v1.5.6
- Pipeline entry point (`summarize()`), sole owner principle, all existing invariants
- No new package dependencies (`cryptography` already required)
- `garmin_writer`, `garmin_quality`, `context_writer` — unmodified

**Compatibility:** Plain mirror folder (v1.5.6 format) remains importable for one release
cycle via folder fallback in `garmin_import_mirror.py`. Folder support will be removed
in a future version.

**Post-release fixes (Session 2):**
- `garmin_app_standalone.py` — Splash Screen vollständig entfernt (war als "removed"
  dokumentiert aber noch aktiv). `__main__`-Block auf 4 Zeilen reduziert.
  `QEventLoop`-Blockade entfällt — T3.1 startet direkt ohne Hänger.
- `garmin_app_base.py` — `_splash_base_path()` + `build_splash_pixmap()` gelöscht.
  Kein toter Code mehr.
- `compiler/build_manifest.py` — `ASSET_FILES` (splash_base.png) entfernt.
  `is_import_ready` aus Mirror-Signaturliste entfernt.
- `compiler/build_standalone.py` — `ASSET_FILES`-Loop entfernt. cryptography
  Hidden Imports vervollständigt: `.kdf.pbkdf2`, `.kdf.hkdf`, `.hashes`, `.hmac`,
  `.ciphers.aead`, `cryptography.hazmat.backends`, `cryptography.exceptions` —
  behebt `cannot import name 'hmac'` und `No module named kdf` in T3.
- `compiler/build.py` — `ASSET_FILES`-Loop entfernt.
- `garmin/garmin_mirror.py` — `is_import_ready()` gelöscht (toter Code).
- `app/panel_archive.py` — `_startup_mirror_check()`: Import-Button immer aktiv,
  `is_import_ready`-Pfad-Check entfernt. `_on_import_mirror()`: `QFileDialog.
  getOpenFileName` statt gespeichertem `mirror_dir` — Gerät 2 kann `.gla` direkt
  per Datei-Picker laden, ohne Mirror-Pfad konfigurieren zu müssen.
- `garmin/garmin_import_mirror.py` — Pfad-Bug behoben: Raw-Dateien liegen flach
  (`garmin_data/raw/garmin_raw_YYYY-MM-DD.json`), Import-Code erwartete fälschlich
  einen Unterordner pro Tag. Alle vier betroffenen Key-Ausdrücke korrigiert
  (`raw_rel_paths`, `summary_rel_paths`, `raw_rel`, `sum_rel`). Ohne Fix:
  0 raw imported, 199 errors. Nach Fix: 197 raw imported, 0 path errors.

**Test result:** 311 / 261 / 303 / 128 / 42 — all green

---

## v1.5.6 — Mirror Import

Multi-device support via selective import from a mirrored archive. A second device
running GLA can import raw days and context files from a mirror folder created by the
primary device. Only days that are missing or have better quality than the local archive
are imported. Summary files are always regenerated locally — schema version conflicts
are structurally eliminated.

**New modules:**
- `garmin/garmin_import_mirror.py` — Sole Owner of the mirror import operation.
  Reads `mirror_meta.json` for version checks. Quality-log-based delta analysis:
  raw days imported by rank (`high` > `medium` > `low` > `failed`), downgrade
  protected via `_upsert_quality()`. Context files: source wins (overwrite existing).
  Pipeline entry at `summarize()` — `normalize()` skipped (raw already normalized).
  Dry-run mode returns delta counts before import. Returns
  `{"raw_copied", "raw_skipped", "context_copied", "errors", "ok"}`.

**Changed modules:**
- `garmin/garmin_mirror.py` — writes `mirror_meta.json` after successful `run_mirror()`
  (`ok=True` only). New public function `is_import_ready(mirror_dir)` — returns `True`
  if folder is reachable and contains `mirror_meta.json`. Internal `_write_mirror_meta()`
  is atomic and non-fatal on error.
- `context/context_writer.py` — new `write_file(dest_path, data)` function. Atomic
  write via temp file + `os.replace()`. Preserves sole-write-authority for `context_data/`
  when called from `garmin_import_mirror`.
- `compiler/build_manifest.py` — `garmin_import_mirror.py` added to `SHARED_SCRIPTS`
  and `SCRIPT_SIGNATURES_BASE`.
- `app/panel_archive.py` — new `_on_import_mirror()` method. Dry-run dialog shows delta
  before import. Background thread, timer pause/resume (same pattern as Bulk Import).
  `_startup_mirror_check()` extended to also set Import from Mirror button state.
- `app/panel_connection.py` — `_import_mirror_btn` widget added.
  `set_import_mirror_button_state()` accessor added (same pattern as mirror/restore buttons).

**What does not change:**
- `garmin_writer`, `garmin_quality`, `garmin_mirror` core logic — unmodified
- `normalize()` — never called during mirror import
- No new package dependencies

**Additional changes (post-build fixes):**
- `garmin_app.py` + `garmin_app_standalone.py` — Splash Screen removed.
  `QEventLoop`, `processEvents()`, and `QThread.msleep()` all tested — none
  rendered reliably on Windows with background thread dispatching active.
  `build_splash_pixmap()` remains in `garmin_app_base.py` as reserve.
- `app/panel_connection.py` — "Clean Archive" button removed (legacy relikt).
  `_clean_archive()` in `panel_archive.py` retained as inactive code.
- `app/panel_archive.py` — `_startup_mirror_check()` made fully non-blocking
  (no `join()`) to prevent startup delay on network mirror paths.

**Test result:** 319 / 261 / 303 / 128 / 42 — all green

---

---

## v1.5.5.5 — Sync Mode Input Validation & Daily Update Fix

Two targeted fixes for the same failure chain. `daily_update.py` set
`GARMIN_SYNC_MODE = range` on both branches of `_build_env()` — including
the normal "up to date" path. `garmin_sync.py` crashed with `ValueError`
if `SYNC_FROM` / `SYNC_TO` were empty strings, because `garmin_config.py`
only applies its default when the ENV key is entirely absent.

**Changed modules:**
- `scheduler/daily_update.py` — `_build_env()`: both branches now set
  `GARMIN_SYNC_MODE = "recent"`. `GARMIN_SYNC_START` and `GARMIN_SYNC_END`
  removed from the ENV dict. Invariant documented in comment:
  `# daily_update setzt immer recent — nie range oder auto`.
  Gap-detected date range is used for logging only; the collector determines
  the fetch window via `GARMIN_DAYS_BACK`.
- `garmin/garmin_sync.py` — new `ConfigurationError` exception class.
  `resolve_date_range()` `range`-branch: `date.fromisoformat()` calls wrapped
  in `try/except (ValueError, TypeError)` — raises `ConfigurationError` with a
  human-readable message before any API call is made.

**Test result:** 319 / 261 / 303 / 128 / 42 — all green

---

## v1.5.5.4 — Test Infrastructure Consolidation + Maps Logging + AST-Guard

Duplicate test-tracking boilerplate extracted from four manual test scripts
into a shared `tests/support.py` module. All four suites now import `check()`,
`section()`, and `summary()` as free functions — no inline implementation.
Summary output unified to a single format. Four Maps modules gain `log.warning()`
in their `_read_field()` except-blocks — previously silent JSON/OS errors are now
observable. New AST-based regression guard in `test_qt_app.py` verifies that
`scheduler/daily_update.py` stays GUI-free.

**New modules:**
- `tests/support.py` — shared test runner: `check()`, `section()`, `summary()`.
  Free functions, no class wrapper. Import via `from support import check, section, summary`.

**Changed modules:**
- `tests/test_local.py` — imports from `support.py`. Inline boilerplate removed.
  Local variable `summary` → `summary_data` (collision with imported `summary()`).
  Summary format unified to Option A.
- `tests/test_local_context.py` — imports from `support.py`. Inline boilerplate removed.
  Summary format unified.
- `tests/test_dashboard.py` — imports from `support.py`. Inline boilerplate removed.
  Summary format unchanged (already Option A).
- `tests/test_app_logic.py` — imports from `support.py`. Inline boilerplate removed.
  Summary format unified.
- `maps/weather_map.py` — `import logging`, `log = logging.getLogger(__name__)`,
  `except`-block extended with `log.warning(f"weather_map: could not read {f}: {e}")`.
- `maps/pollen_map.py` — same treatment as `weather_map.py`.
- `maps/brightsky_map.py` — same treatment as `weather_map.py`.
- `maps/airquality_map.py` — same treatment as `weather_map.py`.
- `tests/test_qt_app.py` — new test `test_daily_update_gui_free` in `TestQtSmoke`.
  AST-based guard: verifies `scheduler/daily_update.py` contains no GUI imports
  (tkinter, PyQt6, PyQt5, PySide6, PySide2).

**Test result:** 319 / 261 / 303 / 128 / 42 — all green

---

## v1.5.5.3 — Unified Date Parser

Duplicate inline date-parsing code eliminated across three quality sub-module
functions. A new shared helper `extract_date_from_filename()` in `garmin_utils.py`
replaces four identical `try/except`-wrapped `date.fromisoformat(f.stem.replace(...))`
blocks in `_scan.py` and `_maint.py`. Leaf-node invariant preserved — only stdlib
imports. Five new checks added to `test_local.py` Sektion 8.

**Changed modules:**
- `garmin/garmin_utils.py` — new `extract_date_from_filename(path, prefix)`.
  Returns `date | None`. No exception propagation. Default prefix `"garmin_raw_"`.
  Added `from pathlib import Path` import.
- `garmin/quality/_scan.py` — `_backfill_quality_log()` and `get_low_quality_dates()`
  use `extract_date_from_filename()`. `ValueError` removed from `get_low_quality_dates`
  except-clause — date parsing no longer raises there.
- `garmin/quality/_maint.py` — `cleanup_before_first_day()` uses
  `extract_date_from_filename()` for both raw/ (default prefix) and summary/
  (`prefix="garmin_"`). Both `try/except ValueError` blocks removed.
- `tests/test_local.py` — 5 new checks in section 8: valid raw, valid summary
  with explicit prefix, invalid format → None, wrong prefix → None, str path works.

**Test result:** 319 / 261 / 303 / 128 / 41 — all green

---

## v1.5.5.2 — Splash Screen + Quality Log Transaction API

Splash screen added to both GUI entry points. Appears immediately after PyQt6
initializes — version number and animated progress bar painted dynamically at
runtime onto a base image. No manual asset update required on future releases.
Internally, quality log writes are now atomic: `record_attempt()` replaces the
scattered `_upsert_quality + _save_quality_log` call pattern in the collector.

**Changed modules:**
- `garmin_app_base.py` — new module-level functions `_splash_base_path()` and
  `build_splash_pixmap(version)`. Shared by both entry points. Paints title,
  version, and progress bar track onto `screenshots/splash_base.png` at runtime.
- `garmin_app.py` — `__main__` block: `QSplashScreen` + `QProgressBar` with
  2.5s minimum display time via `QEventLoop`
- `garmin_app_standalone.py` — identical to `garmin_app.py` (explicit)
- `compiler/build_manifest.py` — new `ASSET_FILES` list for optional build assets
- `compiler/build_standalone.py` — iterates `ASSET_FILES` for `--add-data`;
  duplicate hardcoded splash block removed
- `compiler/build.py` — iterates `ASSET_FILES` instead of hardcoded splash path
- `garmin/quality/_maint.py` — new `record_attempt()`: atomically calls
  `_upsert_quality` + `_save_quality_log` as a single unit. Caller must hold
  `QUALITY_LOCK`. Lazy import of `_save_quality_log` avoids cross-module cycle.
- `garmin/garmin_quality.py` — `record_attempt` added to facade re-exports
- `garmin/garmin_collector.py` — three `_upsert_quality + _save_quality_log`
  pairs replaced with `record_attempt()`. Downgrade-bulk path kept as direct
  call (`# INTENTIONAL DIRECT CALL`) — manual recheck/attempts patch after
  upsert makes atomic wrapper unsuitable there.

**New assets:**
- `screenshots/splash_base.png` — base image (frame without text); painted at runtime

**Test result:** 314 / 261 / 303 / 128 / 41 — all green

---

## v1.5.5.1 — Quality Module Refactoring

`garmin_quality.py` (~934 lines) converted to a facade. Implementation split into five sub-modules under `garmin/quality/`. All callers remain unchanged — the facade re-exports every public symbol identically.

**New modules:**
- `garmin/quality/__init__.py` — package init, empty
- `garmin/quality/_io.py` — Load, Save, Checksum, Defective log, `_safe_get`, `_parse_device_date` alias
- `garmin/quality/_assess.py` — `assess_quality`, `assess_quality_fields`
- `garmin/quality/_scan.py` — `get_low_quality_dates`, `_backfill_quality_log`
- `garmin/quality/_maint.py` — `_QUALITY_RANK`, `_upsert_quality`, `_set_first_day`, `cleanup_before_first_day`
- `garmin/quality/_stats.py` — `get_archive_stats`

**Changed modules:**
- `garmin/garmin_quality.py` — converted to facade; all logic delegated to sub-modules via flat imports (`from quality._io import ...`). `QUALITY_LOCK` remains here — never in sub-modules.
- `compiler/build_manifest.py` — six new entries in `SHARED_SCRIPTS`; signature check for `garmin_quality.py` updated to `from quality._maint import` + `QUALITY_LOCK`.

**Architecture note:** Sub-modules use flat imports (`from quality._io import ...`, not relative `from ._io import ...`) because `garmin/` is on `sys.path` directly — same pattern as `context/`, `maps/`, `dashboards/`.

**Test result:** 314 / 261 / 303 / 128 / 41 — all green · T2 + T3 build clean · GUI verified

---

`garmin_quality.py` (~934 lines) converted to a facade. Implementation split into five sub-modules under `garmin/quality/`. All callers remain unchanged — the facade re-exports every public symbol identically.

**New modules:**
- `garmin/quality/__init__.py` — package init, empty
- `garmin/quality/_io.py` — Load, Save, Checksum, Defective log, `_safe_get`, `_parse_device_date` alias
- `garmin/quality/_assess.py` — `assess_quality`, `assess_quality_fields`
- `garmin/quality/_scan.py` — `get_low_quality_dates`, `_backfill_quality_log`
- `garmin/quality/_maint.py` — `_QUALITY_RANK`, `_upsert_quality`, `_set_first_day`, `cleanup_before_first_day`
- `garmin/quality/_stats.py` — `get_archive_stats`

**Changed modules:**
- `garmin/garmin_quality.py` — converted to facade; all logic delegated to sub-modules via flat imports (`from quality._io import ...`). `QUALITY_LOCK` remains here — never in sub-modules.
- `compiler/build_manifest.py` — six new entries in `SHARED_SCRIPTS`; signature check for `garmin_quality.py` updated to `from quality._maint import` + `QUALITY_LOCK`.

**Architecture note:** Sub-modules use flat imports (`from quality._io import ...`, not relative `from ._io import ...`) because `garmin/` is on `sys.path` directly — same pattern as `context/`, `maps/`, `dashboards/`.

**Test result:** 314 / 261 / 303 / 128 / 41 — all green · T2 + T3 build clean · GUI verified

---
Three independent improvements to integrity detection, UI feedback, and mirror verification.

**Changed modules:**
- `garmin/garmin_quality.py` — `_compute_checksum()` extended from 2 to 4 fields (`date`, `write`, `quality`, `source`). `_compute_checksum_legacy()` added as migration bridge (TODO: remove after v1.6): on first load after upgrade, a legacy-algorithm match is detected and treated as a planned migration — no restore, no warning, new checksum written on next save. `med → medium` migration removed (obsolete since v1.2.0, all archives already migrated).
- `garmin/garmin_mirror.py` — CRC32 spot-check after copy phase: up to 10 random files compared between source and mirror. Result added to return dict as `spot_check: {"sampled": N, "mismatches": M}`. New helper `_run_spot_check()`. `import random`, `import zlib` added.
- `app/panel_archive.py` — `_refresh_archive_info()` now evaluates `stats["integrity_warnings"]` and sets `_integrity_warning_lbl` in `PanelConnection` (widget already existed, was never populated). Mirror log output extended with spot-check result when mismatches > 0.
- `tests/test_local.py` — `med → medium` migration test removed. `source=legacy` migration test fixed (direct file write, no `_save` → no checksum conflict). Section A `_data_save` extended with `source` field.
- `tests/test_local_context.py` — Section A `_data_save` extended with `source` field (same fix as `test_local.py`).

**Test result:** 314 / 261 / 303 / 128 / 41 — all green

---

## v1.5.4.4 — Auth Flow Cleanup, Fresh Archive Fixes & Architecture Hygiene

Three independent fix groups, each separately releasable.

**Step a — Architecture Repair:**
- `app/panel_archive.py`: `do_delete()` now delegates to `garmin_quality.cleanup_before_first_day()` — fixes ownership violation (direct write to `quality_log.json` without `QUALITY_LOCK`, without backup trigger). Dialog and file list preview unchanged.
- `app/garmin_app_controller.py`: Timer direct reads of `quality_log.json` documented as intentional exceptions (`INTENTIONAL DIRECT READ` comment in `timer_run_repair`, `timer_run_bulk_recheck`, `timer_run_quality`).
- `docs/REFERENCE_GARMIN.md`: New `§ Documented Exceptions` section — three intentional invariant deviations documented: `regenerate_summaries.py`, `garmin_validator` → `garmin_config`, Controller timer reads.

**Step b — Fresh Archive Fixes:**
- `app/panel_outputs.py`: `_on_import_done()` wrapper pops `GARMIN_IMPORT_PATH` from `os.environ` after bulk import — prevents T3 timer from re-entering import path on next cycle.
- `garmin/garmin_collector.py`: `run_import()` updates `first_day` after bulk import if GDPR export predates device history — guard: only when `ok > 0`.
- `garmin/garmin_quality.py`: `get_archive_stats()` uses `first_day` as range start when earlier than `date_min` — fixes understated missing count on fresh archives.

**Step c — Auth + Sync Fixes:**
- `context/context_collector.py`: `run()` accepts optional `log_callback=None` — called every 25 days written per plugin. `daily_update.py` unaffected (passes `None`).
- `app/panel_outputs.py`: `_run_context_sync()` passes `log_callback=self._app._log_bg` to context collector.
- Items 1 (SsoRequiredDialog) and 5 (GARMIN_DAYS_BACK) — traced and closed: no bug found. Dialog blocks correctly in PyQt6. `_collect_settings()` already used in `_run()`.

**Pre-session fix (T2 EXE):**
- `compiler/build.py`: Added `keyring`, `keyring.backends`, `keyring.backends.Windows` as hidden imports — fixes password field empty on every T2 start.
- `docs/MAINTENANCE_GLOBAL.md`: Known hidden imports table updated.

**Post-release fix (same version):**
- `app/panel_archive.py`: `_refresh_archive_info()` now uses `get_archive_stats()` instead of local calculation — fixes `Missing` showing `low+failed` count instead of actual absent days, fixes `Last API` / `Last Bulk` always showing `—` (wrong key names), fixes `Coverage` not using `first_day` as range base.

**Test result:** 315 / 261 / 303 / 128 / 41 — all green

## v1.5.4.3 — UI Bug Fixes, Backup Integrity & Settings Persistence

Six bugs fixed across three sessions. No new features.

**Changed modules:**
- `garmin/garmin_backup.py` — Three bugs fixed in the backup pipeline:
  (1) `backfill_raw()`: `zip_path.exists()` used as skip-guard without checking
  whether the specific file is inside the ZIP — files were silently lost.
  Fixed via `_zip_contains()` (already present, unused here). (CRITICAL)
  (2) `check_raw_backfill_needed()`: same guard logic → backfill need
  systematically underestimated when a monthly ZIP already existed. (MEDIUM)
  (3) `_consolidate_raw_months()`: ZIP + directory coexist (e.g. after Background
  Timer fetches a historical day) → directory silently skipped, never consolidated,
  grows unbounded. Fixed: missing files appended to existing ZIP via `zipfile 'a'`
  mode with integrity check; directory deleted afterwards. (HIGH)
- `app/panel_archive.py` — `_refresh_archive_info()`: `Missing:` label showed
  count of `low`+`failed` quality entries instead of physically absent days in
  the tracked date range. Fixed: `missing = (possible days in range) - total`.
  Added `RuntimeError` guard against pytest-qt widget teardown race.
- `app/panel_outputs.py` — Create Reports dialog: (1) individual checkboxes
  unresponsive — Qt6 on Windows disables native hit-testing on QCheckBox widgets
  that inherit a background from a styled QDialog parent. Fixed: full explicit
  stylesheet with all indicator states (normal, checked, hover) and explicit
  width/height. Container transparent style also removed. (2) "Abbrechen" → "Cancel".
- `compiler/build.py` — T2 EXE: `garminconnect`, `curl_cffi`, `curl_cffi.requests`,
  `ua_generator` added as hidden imports. These transitive dependencies of
  garminconnect 0.3.0+ are not auto-detected by PyInstaller. T3 already had them;
  T2 was missing them since v1.5.4.1 (deferred at the time, now resolved).
- `app/garmin_app_settings.py` — `read_text()` / `write_text()` without explicit
  `encoding="utf-8"` — on Windows under PyInstaller the default encoding is
  non-deterministic. Settings were silently unreadable → `except: pass` →
  defaults returned and written back on close, wiping all user settings on every
  update. Fixed: `encoding="utf-8"` explicit in both calls. (CRITICAL)
- `garmin_app_base.py` — `closeEvent()`: `_collect_settings()` wrapped in
  `try/except RuntimeError` as secondary guard for edge cases where widgets
  are deleted before close completes.
- `tests/test_qt_app.py` — `_TestApp` in all four `TestGarminAppBase` tests
  overrides `closeEvent` with `event.accept()` — prevents pytest-qt teardown
  from triggering settings save with empty widget values into the real
  `~/.garmin_archive_settings.json`.
- `tests/test_local_context.py` — 6 new checks for `garmin_backup` bug fixes
  (Bug 1: backfill skips correctly; Bug 2: count correctly > 0; Bug 3: append
  + directory removal verified).

**Test result:** 41 / 315 / 267 / 303 / 128 — all green
(test_qt_app / test_local / test_local_context / test_dashboard / test_app_logic)

---

## v1.5.4.2 — InApp Dashboards

QWebEngineView integrated as a second tab on the right side of the app.
HTML dashboards are now viewable directly inside the app without an external
browser. The Screenshot/Demo mode loads an embedded demo dashboard with
synthetic data — no real user data exposed.

**Changed modules:**
- `garmin_app_base.py` — right side replaced by `QTabWidget`: Tab 1 "Actions" (unchanged content), Tab 2 "Dashboards" with `QComboBox` dropdown + `QWebEngineView` fullscreen. `_scan_dashboards()` and `_load_selected_dashboard()` added as methods on `GarminApp`. Startup scan via `QTimer.singleShot(300)`. New imports: `QTabWidget`, `QComboBox`, `QUrl`, `QWebEngineView`.
- `app/panel_outputs.py` — `on_done` in `_run_dashboards()` calls `self._app._scan_dashboards(auto_load=...)` after a build to rescan and auto-load the new dashboard in Tab 2. No WebEngine code in this module.
- `garmin_app_screenshot.py` — `_scan_dashboards()` overridden: loads `DEMO_HTML` (embedded as string constant, `dashboard_desktop.html` with synthetic data) via `setHtml()` into Tab 2. No file access, no real data.
- `requirements.txt` — `PyQt6-WebEngine` added (direct import dependency).

**Dependencies note:** `curl_cffi` and `ua-generator` (mandatory since garminconnect 0.3.0) are installed transitively — not added explicitly since neither is imported directly by this project.

**Test result:** 315 / 255 / 303 / 128 — all green
(test_local / test_local_context / test_dashboard / test_app_logic)

---

## v1.5.4.1 — Auth Hardening

Four independent improvements to the login flow and dependency monitoring.
Trigger: rate-limit incident 2026-05-19 (settings lost during UI migration
→ token unusable → automatic SSO login → immediate 429 → account-side
block 48h+).

**Changed modules:**
- `garmin/garmin_api.py` — `login()`: new optional callback `on_sso_required()` (Path 3) — user explicitly confirms before garminconnect sends the first SSO request. Headless/Standalone: default `None`, SSO starts automatically as before. Auto-generates encryption key via `generate_enc_key()` if no key is present and no manual callback is provided.
- `garmin/garmin_security.py` — new function `generate_enc_key()`: generates a 256-bit key via `os.urandom(32)`, stores it as a hex string directly in WCM. No user input, no password dialog.
- `app/garmin_app_controller.py` — `check_connection()`: `on_sso_required` wired into `login()` call, callback documentation updated.
- `app/panel_connection.py` — new `SsoRequiredDialog` (analogous to `TokenExpiredDialog`), `_prompt_sso_required()`, `_show_prompt` branch `"sso_required"`. Dialog informs the user about automatic key generation and 429 risk in a single step.
- `tests/check_deps.py` — optional probe call against Garmin Connect after findings display: token status, 429, 401, no token. Read-only, never deletes token. Order: findings → probe? → start anyway?

**Item 3 deferred:** `requirements.txt` + `build_manifest.py` (`curl_cffi` / `ua-generator`) — pending `garminconnect 0.3.4` PyPI release. Released to PyPI during this session (0.3.4 ✓) — follows in a patch or v1.5.4.2.

**Test result:** 315 / 255 / 303 / 128 — all green
(test_local / test_local_context / test_dashboard / test_app_logic)

---

## v1.5.4 — PyQt6 Migration

tkinter replaced entirely by PyQt6. All five panel mixins were rebuilt as
standalone QWidget subclasses. GarminAppBase became
GarminApp(QMainWindow) as a pure assembler. Thread-safe dispatch via
pyqtSignal replaced self.after(). No behavior changed — pure
toolkit migration in preparation for QWebEngineView (v1.5.4.1).

**Changed modules:**
- `garmin_app_base.py` — GarminApp(QMainWindow), pyqtSignal-based _dispatch(), composition instead of mixin inheritance
- `garmin_app.py` — entry point T1/T2, Qt event loop, subprocess model unchanged
- `garmin_app_standalone.py` — entry point T3, QTimer instead of self.after() for _poll_log_queue
- `app/panel_settings.py` — PanelSettings(QWidget), QLineEdit/QComboBox instead of StringVar
- `app/panel_connection.py` — PanelConnection(QWidget), pyqtSignal for modal dialogs (D-2), EncKeyDialog/TokenExpiredDialog/MfaDialog as QDialog subclasses
- `app/panel_archive.py` — PanelArchive(QWidget), QDialog for Clean Archive
- `app/panel_timer.py` — PanelTimer(QWidget), timer loop unchanged
- `app/panel_outputs.py` — PanelOutputs(QWidget), QDialog for dashboard popup and Task Scheduler XML

**New files:**
- `tests/conftest.py` — pytest-qt QApplication fixture
- `tests/test_qt_app.py` — 41 checks, 7 classes
- `tests/run_qt_tests.bat` — quick start

**Test result:** 315 / 255 / 303 / 128 / 41 — all green
(test_local / test_local_context / test_dashboard / test_app_logic / test_qt_app)

**Critical fix found during implementation:**
- `_dispatch()` initially used `QTimer.singleShot()` from worker threads —
  not thread-safe in PyQt6. Fixed via `pyqtSignal(object)` at class level
  with an `@pyqtSlot(object)` receiver. Qt queues cross-thread emissions
  automatically. Rule: `QTimer.singleShot()` from Main Thread only.

---

## v1.5.3.1 — State Hardening
 
Hardening step in preparation for the PyQt6 migration. No behaviour changes,
no new features. Cross-LLM review (Gemini) identified a critical Event-recycling
risk in the original plan (`clear()` on shared Event = potential Zombie-Thread);
corrected to per-run `threading.Event()` instantiation with Dummy-Event in Base-Init.
 
**Changed modules:**
- `garmin_app_base.py` — State-Block: `_ctx_running = False` and `_context_stop_event = threading.Event()` added with owner + thread-rule comments; `hasattr`-guard in `_on_close` removed (direct call)
- `panel_outputs.py` — `_stop_context_sync`: `hasattr`-guard removed (direct call)
- `panel_archive.py` — `_on_mirror`: `getattr`-guard replaced by direct `self._ctx_running` access; all direct `self._mirror_btn.config()` and `self._restore_btn.config()` calls replaced by accessor calls
- `panel_connection.py` — `_set_mirror_button_state()` and `_set_restore_button_state()` accessor methods added; sole authorised write-path for cross-panel button access
**Architecture decisions:**
- `_context_stop_event` initialised as `threading.Event()` (not `None`) in Base-Init — eliminates `hasattr`-guards; per-run reassignment (`= threading.Event()`) retained so each sync thread holds its own Event reference (no `clear()` recycling)
- Accessor methods carry no threading logic — `self.after()` wrappers remain explicit in `panel_archive` as Qt migration markers for v1.5.4
- E-7 prefix audit: no collision risk found — Phase 3 skipped by design
**Test result:** 128 / 128 — all green.
 
**Hotfix (post-release):** T2 and T3 EXEs failed to start with `ImportError: cannot import name 'filedialog' from 'tkinter'`. PyInstaller does not auto-detect tkinter submodules — `tkinter.filedialog`, `tkinter.messagebox`, `tkinter.ttk`, `tkinter.scrolledtext` added as explicit hidden imports in `build.py` and `build_standalone.py`. `cloudscraper` removed from T3 hidden imports (leftover from pre-March 2026 `garth` era, not used since `garminconnect 0.3.x`). Both targets confirmed working after fix.
 
---

## v1.5.3 — UI Panel Decomposition

Structural refactoring — no logic changes, no new features.

`garmin_app_base.py` (~1952 lines after v1.5.2) decomposed into five dedicated
panel Mixin modules. The base class becomes a pure assembler (~440 lines).
Panel-by-panel decomposition enables mechanical translation to PyQt6 in v1.5.4.
Cross-LLM review (Gemini + ChatGPT) identified `_ctx_running` bug and confirmed
Mixin as the correct architectural pattern for Qt migration.

**New modules:**
- `app/panel_settings.py` — `PanelSettingsMixin`: credentials, paths, sync config, context location
- `app/panel_connection.py` — `PanelConnectionMixin`: connection test, status indicators, enc-key/MFA/token prompts, reset token, archive info panel
- `app/panel_archive.py` — `PanelArchiveMixin`: archive info refresh, integrity check, restore data, clean archive, schema migration popup, failed-days popup, mirror operation
- `app/panel_timer.py` — `PanelTimerMixin`: timer UI, toggle, resume-after-sync, timer loop, controller delegates
- `app/panel_outputs.py` — `PanelOutputsMixin`: data collection (sync, import, context sync), dashboard popup, output buttons; includes `_ctx_running` bug fix

**Changed modules:**
- `garmin_app_base.py` — rewritten as pure assembler: inherits all five Mixins (`PanelSettingsMixin, PanelConnectionMixin, PanelArchiveMixin, PanelTimerMixin, PanelOutputsMixin, tk.Tk`); MRO order documented and binding; shared state block with owner + thread-rule per flag; `_stop_collector` abstract hook added; 440 lines (was ~2500 at v1.5.2 start, ~1952 after v1.5.2)
- `compiler/build_manifest.py` — five new entries in `SHARED_SCRIPTS` (`app/panel_settings.py`, `app/panel_connection.py`, `app/panel_archive.py`, `app/panel_timer.py`, `app/panel_outputs.py`)
- `tests/test_app_logic.py` — tkinter mock updated (`_tk_mock.Tk = type("Tk", (object,), {})`); Section 12 `patch.dict` extended with panel mocks; Section 14 `_timer_run_bulk_recheck` migrated to `PanelTimerMixin`

**Architecture decisions:**
- Mixin pattern (not function delegation) — enables panel-by-panel PyQt6 translation without wrapper layer
- MRO order: Settings → Connection → Archive → Timer → Outputs → tk.Tk
- Invariant: no Mixin may define `__init__`
- Panel-private helpers use `_{panel}_*` prefix to prevent silent MRO collisions (E-7)
- `_ctx_running` bug fixed in `panel_outputs.py` (no setter existed — context sync never blocked mirror)

**Test result:** 315 / 255 / 303 / 128 — all green.

---

## v1.5.2 — GUI / Controller Separation

Structural refactoring — no logic changes, no new features.

`garmin_app_base.py` (~2500 lines) separated into three distinct layers.

**New modules:**
- `app/garmin_app_settings.py` — Layer 1: settings persistence, keyring helpers, constants. No tkinter dependency — importable in any context including headless.
- `app/garmin_app_controller.py` — Layer 3: application logic (ENV construction, archive stats, connection testing, timer calculations, startup integrity/mirror checks). No tkinter, no Qt — pure functions, return values and callbacks only.
- `app/__init__.py` — package marker

**Changed modules:**
- `garmin_app_base.py` — becomes pure View (Layer 4): imports settings and controller via module references. All former settings/keyring functions replaced by re-exports from `garmin_app_settings`. All former logic methods delegated to `garmin_app_controller`. New `_safe_save()` wrapper centralises OSError handling for `save_settings()` calls. Layer 4 Schicht-4-Blockkommentar set before mixed-callback methods (`_create_task_scheduler_xml`, `_open_dashboard_popup`, `_on_mirror`, `_on_restore_data`, `_check_version`).
- `garmin_app.py` — `sys.path` extended with `app/`; `load_password`/`save_password` imported directly from `garmin_app_settings` (Option B — no re-export via base)
- `garmin_app_standalone.py` — `sys.path` + `_register_embedded_packages()` extended with `app/`; same direct import pattern
- `compiler/build_manifest.py` — three new entries in `SHARED_SCRIPTS` (`app/__init__.py`, `app/garmin_app_settings.py`, `app/garmin_app_controller.py`) + corresponding `SCRIPT_SIGNATURES_BASE` entries
- `tests/test_app_logic.py` — import paths updated (Sections 3–5, 11); `garmin_app_controller` imported and tested (Sections 15–18); B15 AST-test added

**Callback contract (v1.5.3-ready):**
Controller communicates with View exclusively via return values and callbacks. No tkinter-specific types in parameters or return values. In v1.5.3, the View replaces lambda callbacks with `pyqtSignal` emitters — the controller remains unchanged.

**Test result:** 315 / 255 / 303 / 129 / 356 — all green.

---

## v1.5.1.1 — Log Improvement

Daily logs and GUI session logs are now always written in detail mode (DEBUG). Fixes a structural bug: `logging.basicConfig()` is idempotent — the file handler was set to DEBUG, but the root logger filtered at INFO, so DEBUG messages never reached the handler. Additionally, the token-expired warning now logs the exact exception type and text.

**Changed modules:**
- `daily_update.py` — root logger and `GARMIN_LOG_LEVEL` ENV changed from `INFO` to `DEBUG`
- `garmin_app_base.py` — `GARMIN_LOG_LEVEL` ENV changed from `getattr(self, "_log_level", "INFO")` to `"DEBUG"`
- `garmin_api.py` — token-expired warning now includes `type(e).__name__` and `str(e)`

**Test result:** 315 / 217 / 303 / 102 — all green.

---

## v1.5.1 — Archive Integrity & Backup

Protection of the local archive against software errors and silent data loss.

**New modules:**
- `garmin/garmin_backup.py` — Sole Owner of `garmin_data/backup/`. Incremental raw backup after each write, monthly ZIP consolidation, `quality_log.json` monthly snapshots + yearly consolidation, restore from backup, startup integrity check (raw files vs. quality log).
- `garmin/garmin_mirror.py` — Sole Owner of mirror operation. Mirrors `BASE_DIR` → user-configured target (NAS, USB, OneDrive). Comparison: filename + filesize. Excludes `__pycache__`, `garmin_token`.

**Changed modules:**
- `garmin/garmin_config.py` — 4 new paths: `BACKUP_DIR`, `LOG_BACKUP_DIR`, `RAW_BACKUP_DIR`, `AUTORESTORE_DIR`.
- `garmin/garmin_quality.py` — `_save_quality_log()`: `skip_backup` parameter, sorts `days` by date, computes SHA-256 checksum over stable core fields (`date` + `write`), triggers `garmin_backup.backup_quality_log()`. `_load_quality_log()`: verifies checksum after load, populates `integrity_warnings` list, triggers auto-restore from backup on mismatch. New helpers: `_compute_checksum()`, `_save_defective_log()`. `get_archive_stats()`: passes `integrity_warnings` through.
- `garmin/garmin_writer.py` — `write_day()`: triggers `garmin_backup.backup_raw()` after successful write (lazy import, failure non-fatal).
- `garmin_app_base.py` — `DEFAULT_SETTINGS`: `mirror_dir`. Storage panel: Mirror folder field + `…` button. CONNECTION & ARCHIVE STATUS: `Restore Data` button (raw integrity check at startup, restore from backup), `Data Mirror` button (disabled when unreachable, race condition guard). New methods: `_startup_integrity_check()`, `_on_restore_data()`, `_startup_mirror_check()`, `_browse_mirror_folder()`, `_on_mirror()`. `_integrity_warning_lbl`: yellow label in Archive Info Panel on checksum mismatch.

**Backup structure:**
garmin_data/backup/
log/    — quality_log_YYYY-MM.zip (monthly), quality_log_YYYY.zip (yearly)
raw/    — YYYY-MM/ (open month), raw_backup_YYYY-MM.zip (completed months)
autorestore/ — auto-restore-YYYY-MM-DD.zip (defective log before restore)

**Test result:** 315 / 217 / 303 / 102 — all green.

**Nachtrag — Raw Backfill:**
- `garmin/garmin_backup.py`: `check_raw_backfill_needed()` + `backfill_raw()` — einmalige Sicherung aller bestehenden Raw-Dateien die noch kein Backup haben. Idempotent.
- `garmin_app_base.py`: `_check_raw_backfill_popup()` — wird beim ersten Sync aufgerufen. Zeigt Popup mit Anzahl ungesicherter Dateien und Option zur Sicherung im Hintergrund. Flag `backup_raw_backfill_asked` in Settings verhindert wiederholte Anzeige.

---

## v1.5.0.1 — API Hotfix & Dependency Pinning

**Fixed: Broken login flow due to Garmin SSO changes.**

Garmin tightened security for login endpoints (Cloudflare/Rate-Limiting), resulting in HTTP 429 errors. This release restores synchronization functionality.

- **Dependency:** Pinned `garminconnect==0.3.4` in `requirements.txt` to resolve 429 Rate-Limit issues caused by Garmin SSO changes.
- **Verification:** Confirmed existing 429-protection logic in `garmin_api.py` and token-based login are fully operational with the updated library.

**Changed files:**
- `requirements.txt` — Fixed version to `0.3.4`

**New column: HRV 7d Ø** — added to Sleep Dashboard (HTML + Excel).

Displays the 7-day rolling average of nightly HRV per row.
Calculated in `sleep_garmin_html-xls_dash.py` from archived data — no new API field required.
Color-coded using the same HRV reference range as the daily value.

**Changed files:**
- `sleep_garmin_html-xls_dash.py` — `build()`: computes `hrv_7d_avg` per row
- `dash_plotter_html_complex.py` — `_render_sleep()`: new column in HTML table
- `dash_plotter_excel.py` — `_write_sleep_sheet()`: new column `COL_HRV7D`

---

## v1.5.0 — Root Cleanup

**Structural refactoring — no logic changes, no new features.**

Root reduced from 18 to 10 files. Build scripts and scheduler files moved to dedicated subfolders.

**New folders:**
- `compiler/` — `build.py`, `build_all.py`, `build_manifest.py`, `build_standalone.py`
- `scheduler/` — `daily_update.py`, `daily_update.bat`, `daily_update_task.xml`

**Removed from root:** `generate_tree.bat`, `struktur.md` (local dev tools, not repo content)

**Path changes:**
- All build scripts: `root = Path(__file__).parent.parent` — anchors on repo root, not `compiler/`
- `.spec` files: `--specpath` → `compiler/` — spec files stay in `compiler/` alongside build scripts
- `build.py` ZIP: `daily_update.bat` sourced from `scheduler/`
- `build_standalone.py`: `daily_update.py` entry point sourced from `scheduler/`
- `build_all.py`: all five test paths updated to `parent.parent / "tests" / ...`
- `daily_update.py`: sys.path root anchor inserted before `from version import APP_VERSION`; T1/T2 branch: `_root = Path(__file__).parent.parent`
- `garmin_app_base.py`: `_default_path()` T2 → `scheduler/daily_update.bat`; template candidate → `scheduler/daily_update_task.xml`
- `test_build_output.py`: `build_manifest` import from `compiler/`; existence checks for `compiler/build_manifest.py` and `scheduler/daily_update.py`; signature lookup uses path override for `daily_update.py`
- Both BAT launchers: `python .\build_all.py` → `python .\compiler\build_all.py`

**Test result:** 227 / 217 / 303 / 102 / 313 — all green.

**T2 ZIP distribution fix (post-release patch):**
- `scheduler/` preserved as subfolder in ZIP — `daily_update.py` requires `.parent.parent = ZIP-Root` for module resolution
- `Starte_Daily_Sync.bat` added to ZIP root — single user entry point; `cd`s into `scheduler/` before calling `daily_update.py`
- `build.py` `validate_scripts()`: scheduler files (`daily_update.bat`, `daily_update.py`, `daily_update_task.xml`, `Starte_Daily_Sync.bat`) now checked before build
- `scheduler/daily_update.py`: `_scripts_early` path inserted before `from version import APP_VERSION` (T2 fix); `_ctx_dir` corrected to `_base / "context"`
- `tests/test_build_output.py`: Section 2 + Section 6 extended with scheduler file checks
- `docs/WORKFLOW_TEMPLATE.md`: "Analysestrategie — Laufzeitfehler" added

---

## [1.4.9.1] - New Design

### **Changed - new design**
- Color palette updated: Navy/Red → Dark-Purple/Violet accent
  (`ACCENT #e94560 → #a259f7`, `ACCENT2 #533483 → #6e3fcf`,
  `BG #1a1a2e → #12101f`, `BG2 #16213e → #1a1729`, `BG3 #0f3460 → #231f38`)
- Header icon updated: `⌚` → `🦄`
- Visual identity now aligned with project logo and GLA-Translate aesthetic
- HTML dashboard titles now prefixed with `🦄 GARMIN LOCAL ARCHIVE — `
  across all HTML plotters (`dash_plotter_html.py`, `dash_plotter_html_complex.py`,
  `dash_plotter_html_mobile.py`) — Excel and JSON unaffected
- HTML dashboard header color updated: Navy `#1F3864` → Dark-Purple `#231f38` (background)
  and `#6e3fcf` (accents/borders) across `dash_layout_html.py` and
  `dash_plotter_html_mobile.py` — visual identity now consistent with GUI palette

### **Fix**
- [Fix] dash_plotter_html: replaced f-string HTML assembly with string concatenation to prevent NameError when CSS or JS contains unescaped curly braces

### Project & Ecosystem
- **Needful Things Repo**: Formalized the separation of the tools ecosystem. The [GLA-NeedfulThings](https://github.com/Wewoc/GLA-NeedfulThings) repository provides independent utilities (Translator, Chat Pipeline, etc.) that function without a local GLA installation[cite: 14].

## **Archive Info Panel — Missing Days:**
**New:**
- `garmin_quality.py` — `get_archive_stats()`: `missing` key added (`possible - present`). If determined in the same calculation step as` coverage_pct `, no additional run.
- `garmin_app_base.py` — Widget `_info_missing` inserted in `row1` after `_info_recheck`. `_refresh_archive_info()`: Label is filled from `stats['missing']`.
- `garmin_app_screenshot.py` — Demo value `Missing: 37` added.

---

## v1.4.9 — GarminAppBase · Daily Sync

**New: `garmin_app_base.py`:**
- `GarminAppBase(tk.Tk)` — shared base class for all GUI entry points.
- Contains all UI constants, `DEFAULT_SETTINGS`, `load_settings()`, `save_settings()`, keyring helpers, `apply_style()`, full GUI layout, all settings methods, all business methods, all timer methods.
- Three abstract hooks: `_run()`, `_log_bg()`, `_is_running()` — subclasses implement per execution model. Template Method Pattern.
- `_build_env_dict(s, refresh_failed) → dict` — pure ENV builder, no side effects. Both entry points call this; App passes result to `Popen`, Standalone writes to `os.environ`.
- `DEFAULT_SETTINGS` unified: `context_latitude` + `context_longitude` added (were missing in Standalone).
- `APP_VERSION = "v1.4.9"` replaced by `from version import APP_VERSION`.
- New method `_create_task_scheduler_xml()` — generates a configured `daily_update_task.xml` for Windows Task Scheduler.
- New button "🗓  Create Task Scheduler XML" in Output section. Dialog: target selection (T2/T3/T1), entry point path auto-filled from current exe location (T2/T3), Browse button, Generate & Save. XML written as UTF-16 (required by Windows Task Scheduler). Template sourced from `info/daily_update_task.xml` (builds) or `docs/daily_update_task.xml` (dev).
- Bugs fixed during consolidation: `s` not defined in `_run_collector` (Standalone), `_clean_archive` ownership violation (Standalone inline → Quality module), `toggle_btn` double definition (Standalone), `FONT_MONO` missing (Standalone), `_timer_generation` double increment (Standalone), inline `root`-path logic replaced with `script_dir()`.

**`garmin_app.py` — Target 1+2:**
- Now subclasses `GarminAppBase`. Retains only: `script_dir()`, `script_path()`, `_find_python()`, subprocess `_run()`, `_log_bg()`, `_is_running()`, `_stop_collector()`.
- Reduced from 2476 → 228 lines.

**`garmin_app_standalone.py` — Target 3:**
- Now subclasses `GarminAppBase`. Retains only: `script_dir()`, `script_path()`, `_register_embedded_packages()`, `_QueueWriter`, `_QueueHandler`, importlib `_run()`, `_log_bg()`, `_is_running()`, `_stop_collector()`, `_poll_log_queue()`.
- Reduced from 2467 → 279 lines.

**New: `version.py`:**
- Single source of truth for `APP_VERSION` in repo root.
- No tkinter dependency — safe for all build targets.
- Imported by `garmin_app_base.py` and `daily_update.py`.

**New: `daily_update.py`:**
- Thin headless entry point for automated daily operation via Windows Task Scheduler.
- Workflow: preconditions → version check → gap detection → Garmin sync → context sync → dashboards → exit.
- Gap detection: reads `quality_log.json` — gaps ≤ 7 days healed automatically, gaps > 7 days → hard stop with message.
- Error logic: both APIs run through even on error; dashboards skipped if any API had errors.
- Exit codes: 0 = success, 1 = migration required, 2 = settings missing, 3 = API error, 4 = dashboard error, 5 = update available.
- Logging: `BASE_DIR/garmin_data/log/daily/` — rolling 30 files, prefix `daily`.
- Console closes automatically on success (exit 0); stays open with message on any other exit.
- Reads `~/.garmin_archive_settings.json` and Windows Credential Manager — identical to GUI config.
- All project module imports lazy (after `os.environ` set) — `garmin_config` safe.
- `APP_VERSION` import replaced by `from version import APP_VERSION` — sync warning removed.
- `context` package registered as `types.ModuleType` in `sys.modules` — relative imports resolve correctly.
- `_setup_paths()`: all package subdirs (`dashboards/`, `layouts/`, `maps/`, `context/`) added to `sys.path` — flat imports (`import dash_runner`) work correctly in T3.2 frozen context.

**`garmin_api.py` + `garmin_security.py` — WinError 5 fix:**
- Root cause: `garminconnect` stores `_tokenstore_path` internally and writes back to `garmin_tokens.json` on token refresh — after `login()` returns. `shutil.rmtree` failed because the library was actively re-creating the file.
- Fix: `client._tokenstore_path = None` before `_clear_token_dir()` — library can no longer write back.
- `_clear_token_dir()` retry-loop extended: 3× 200 ms → 5× 1 s as secondary safety net.

**New: `daily_update.bat` — T2 wrapper:**
- Calls `python daily_update.py` — Task Scheduler entry point for Target 2.

**New: `docs/daily_update_task.xml` — Task Scheduler template:**
- Ready-to-import XML with placeholder `{ENTRY_POINT_PATH}` — ships in `info/` (T2/T3) and `docs/` (T1).

**`build_manifest.py`:**
- `"garmin_app_base.py"` added as first entry in `SHARED_SCRIPTS`.
- `"version.py"` added to `SHARED_SCRIPTS`.
- `daily_update.py` added to `ALL_SCRIPTS`.
- `daily_update_task.xml` added to `INFO_INCLUDE_T2` + `INFO_INCLUDE_T3`.

**`build_standalone.py`:**
- `build_exe()` parametrized: `name`, `entry_point`, `windowed`.
- `build_combined_zip()` — T3.1 + T3.2 EXEs in one ZIP (`Garmin_Local_Archive_Standalone.zip`).
- T3.2 (`daily_update.exe`) built without `--windowed` — console visible for Task Scheduler exit code.
- `validate_scripts()` extended: `daily_update.py` + signature `"def main"`.

**`build.py`:**
- `daily_update.bat` packed into T2 ZIP.

**`build_all.py`:**
- Console output updated — T2 and T3 blocks labelled separately.
- `test_app_logic.py` added as final post-build step after `test_build_output.py`.

**`tests/test_app_logic.py`:**
- Sections 1–5, 11–12 updated: Settings, keyring, password tests moved to `garmin_app_base`. Re-export checks confirm `app` and `standalone` share base functions.
- Section 12 replaced: Hook implementation tests — `_run`, `_log_bg`, `_is_running` override verification; `_build_env_dict` unit test (keys, `GARMIN_REFRESH_FAILED`, no `os.environ` side-effect).
- **Total: 102/102 passed.**

**`tests/test_build_output.py`:**
- Section 1: `ALL_SCRIPTS contains daily_update.py` added.
- Section 2: `daily_update.py exists` + signature `"def main"` added.
- Section 7: extended — both EXEs + combined ZIP checked.
- **Total: 306/306 passed.**

---

## v1.4.8 — Sleep Dashboard + Pipeline Hardening

**New: `dashboards/sleep_garmin_html-xls_dash.py`:**
- Specialist: one row per night — sleep phases (segmented bar), duration, score, quality badge, feedback text, HRV, Body Battery.
- `layout = "sleep"` in return dict — dispatched by both `dash_plotter_html_complex` and `dash_plotter_excel`.
- `refs` dict passes age/sex/fitness-adjusted reference ranges to plotters.
- Age-cast with `int(float(...))` fallback — consistent with other specialists.

**`maps/garmin_map.py`:**
- `sleep_score` registered as daily field reading from `summary/sleep/score`.

**`layouts/dash_plotter_html_complex.py`:**
- `render()` dispatch extended: `"sleep"` → `_render_sleep()` (new), `"explorer"` → `_render_explorer()`, otherwise → `_render_recovery_context()`.
- `_render_sleep()` — pure HTML/CSS table render, no Plotly dependency. Phase bar as CSS flex with proportional segments. Colored numbers via HSL interpolation (continuous gradient, no discrete buckets). Qualifier as colored badge. Feedback as cleaned plain text (enum → readable label).

**`layouts/dash_plotter_excel.py`:**
- `render()` dispatch: `layout == "sleep"` checked before `"rows"` check to prevent collision with Overview mode.
- `_write_sleep_sheet()` — phase bar as 20 narrow `PatternFill` cells. Colored numbers via font color from HSL anchor-point interpolation. Qualifier with background fill. HRV column with medium left border as visual separator.

**`build_manifest.py`:**
- `dashboards/sleep_garmin_html-xls_dash.py` added to `SHARED_SCRIPTS`.

**`tests/test_dashboard.py`:**
- Section 14 added: 26 checks — META, `build()` return structure, all field values, HTML render, Excel render, ValueError guards for both plotters.
- Section 15 added: `garmin_map` broker contract — `values` (list), `fallback` (bool), `source_resolution` (str); fallback behaviour daily/intraday; `KeyError` on unknown field; `ValueError` on invalid resolution; `list_fields()`.
- Section 16 added: Specialist return contract — all 6 specialists called with synthetic data; mandatory keys per specialist verified.
- **Total: 303/303 passed.**

**Pipeline hardening:**

**`dashboards/dash_runner.py`:**
- `_load_plotters()`: import errors no longer silently discarded. Error string stored as `plotters["{fmt}_err"]`. `build()` returns `success=False` with exact import error in `"error"` field when a format's plotter failed to load.

**`garmin_app.py` + `garmin_app_standalone.py`:**
- `save_settings()`: `write_text()` wrapped in try/except. `OSError` → `messagebox.showerror()`. Previously a non-writable settings file caused a silent unhandled exception in the GUI thread.
- Create Reports popup: **Select/Deselect All** toggle button added bottom-left, next to Create. State resets on each popup open.

**`dashboards/sleep_recovery_context_dash.py` + `dashboards/health_garmin_html-json_dash.py`:**
- `age`-cast hardened: `int(float(settings.get("age") or 35))` with `(TypeError, ValueError)` guard, fallback 35. Prevents crash on float-string input (`"35.5"`) or invalid value.

**`garmin/garmin_collector.py`:**
- Bulk recheck flagging: all days with `source=bulk` + date ≤ 180 days → `recheck=True` on every startup (quality irrelevant). Previously: only `medium` + ≤90 days.
- Downgrade path: if API result inferior to existing bulk entry, `attempts` is incremented manually after `_upsert_quality()`. After 2 failed attempts `recheck=False` — bulk quality accepted as final.

**`garmin_app.py` + `garmin_app_standalone.py` — Background Timer:**
- `_timer_run_bulk_recheck()` added: returns bulk recheck candidates (`source=bulk` + `recheck=True` + ≤180 days), sorted oldest first. Returns `None` if empty.
- `_timer_loop()`: Bulk Recheck runs as priority mode before the normal Repair → Quality → Fill cycle. While candidates exist, only bulk days are processed — oldest first, no random selection. Label `"Bulk Recheck"` in log.

**`tests/test_app_logic.py`:**
- Sections 11–13 added: OSError handling for `save_settings()` in both app files; structural source-check for `age`-cast guard in both dash specialists.
- Section 14 added: `_timer_run_bulk_recheck()` exists in both app classes; returns `None` without log file; filters candidates correctly by source, recheck, and 180-day window.
- **Total: 293/293 passed.**

**`tests/test_local_context.py`:**
- Broker contract added: `weather_map.get()`, `pollen_map.get()`, `context_map.get()` — same contract as `garmin_map`; fallback behaviour; `KeyError`; `list_fields()`; `list_sources()`.
- **Total: 217/217 passed.**

**`REFERENCE_GARMIN.md`:** Bulk recheck logic updated (180 days, quality irrelevant, downgrade behaviour); `_timer_run_bulk_recheck()` added to app method table.

**`MAINTENANCE_GARMIN.md`:** Pipeline diagram updated; Background Timer description extended with Bulk Recheck priority mode; Quality table: `medium` + `source=bulk` exception noted.

**`MAINTENANCE_DASHBOARD.md`:** Test section table updated (248→303, sections 14→16).

**`README.md`:** Background Timer description updated to include Bulk Recheck.

**`README_APP.md`:** Background Timer section fully rewritten — 4 modes with priority order documented.

**`REFERENCE_DASHBOARD.md`:** New section "Broker interface" — `field_map.get()` and `context_map.get()` contract fully documented including `weather_map`/`pollen_map` deviation.

**`MAINTENANCE_DASHBOARD.md`:** Test section table updated (248→303, 14→16 sections); broker contract and specialist return contract notes added.

**Documentation:**
- `README.md`: Link in dashboard table adjusted — AI guide referenced inline instead of "at the end of this README".
- `README_APP.md`: Standalone troubleshooting — CMD-block replaced with log file navigation via Windows Explorer (`garmin_data\log\fail\`).
- `MAINTENANCE_GARMIN.md`: `first_day` caution added — not protected against manual edits or ENV overrides; derived from device history API, not guaranteed complete. Integrity note added — `quality_log.json` has no checksums; corruption is not automatically detected.

---

## v1.4.7.1 — Context Pipeline Extension & Explorer Dashboard

**`maps/context_map.py`:**
- `airquality_map` imported and registered in `_SOURCES` as `"airquality"`.
- `list_sources()` now returns `{"weather", "pollen", "brightsky", "airquality"}`.

**`maps/field_map.py`:**
- `airquality_map` import and `_SOURCES` entry removed — air quality is a context source, not a Garmin source. Corrected from Session 1.

**`context/context_collector.py`:**
- Bounding-box guard before plugin dispatch: lat 47.2–55.1, lon 5.8–15.1. `brightsky_plugin` skipped for segments outside Germany. Log entry written on skip.
- `airquality_plugin` imported, added to `_PLUGINS` and `OUTPUT_DIR` override block.

**New: `context/airquality_plugin.py`:**
- Metadata-only plugin. Open-Meteo Air Quality endpoint, no API key. 5 fields: `pm2_5`, `pm10`, `european_aqi`, `nitrogen_dioxide`, `ozone`. `AGGREGATION_MAP` (all mean), `CHUNK_DAYS = 30`.

**New: `maps/airquality_map.py`:**
- Field resolver for `context_data/airquality/raw/`. Generic names → internal JSON keys. `get_label()` returns `(label, unit)` per field.

**`garmin/garmin_config.py`:**
- `CONTEXT_AIRQUALITY_DIR` added after `CONTEXT_BRIGHTSKY_DIR`.

**`context/context_api.py`:**
- `_parse_hourly_to_daily(response, fields, aggregation_map)` — new parser for mean-aggregated hourly fields. Dispatch via `hasattr(plugin, "AGGREGATION_MAP")` before existing `else` branch.

**`garmin/garmin_normalizer.py`:**
- `sleep_score_feedback` from `dailySleepDTO.sleepScoreFeedback` added to `s["sleep"]`.
- `sleep_score_qualifier` from `dailySleepDTO.sleepScores.overall.qualifierKey` added to `s["sleep"]`.
- `CURRENT_SCHEMA_VERSION` bumped from `1` to `2`.

**`maps/garmin_map.py`:**
- `sleep_score_feedback` and `sleep_score_qualifier` registered in `_FIELD_MAP` as daily fields reading from `summary/sleep/`.

**New: `dashboards/explorer_garmin-context_html_dash.py`:**
- Specialist: free metric exploration across all Garmin daily fields and context sources.
- Single page: 4 freely selectable metric dropdowns → line traces on shared X-axis, each with own Y-axis. Fixed lower panel: stacked sleep phase bars + vertical sleep score text labels per day (Plotly text trace, colour from `qualifier`).

**`layouts/dash_plotter_html_complex.py`:**
- `render()` now dispatches by `data.get("layout")`: `"explorer"` → `_render_explorer()`, otherwise → `_render_recovery_context()` (unchanged).
- New: `_build_explorer_tab1()`, `_render_explorer()`. Explorer renders as single page — no tab navigation.
- Sleep score chips replaced by Plotly text trace (`mode='text'`, `textangle=-90`, `y=2`) inside sleep phase panel.
- `_TAB_SWITCH_JS` updated: `showComplexTab()` now receives full element ID — no implicit `"chart-"` prefix. `_build_tab_buttons()` updated accordingly.
- Dead `tab1_div.replace()` call removed from `_render_recovery_context()`.

**`tests/test_local_context.py`:**
- Section 11: `list_sources` expected set updated to include `"airquality"`.
- 6 new checks for `airquality_plugin` and `_parse_hourly_to_daily` (Session 1).
- **Total: 187/187 passed.**

**`tests/test_local.py`:**
- 4 new checks for `sleep_score_feedback` + `sleep_score_qualifier`. `schema_version` expectation updated to `2`.
- Section 15: 8 new checks for `_check_downgrade` — covers no-entry, same label, downgrade, upgrade, missing-quality-key edge case.
- Section 16: 7 new checks for `_run_self_healing` — covers no-candidate, missing raw file, status improved, status unchanged.
- **Total: 237/237 passed.**

**`layouts/dash_plotter_html_complex.py` — Explorer refinements:**
- Sleep score annotation: after multiple iterations, reverted to stable stacked bar only — text/marker traces caused data loss and layout instability at scale. Score data (`_scores`) retained in JS for future use.
- Three collapsible panels added below the chart:
  - **Sleep Quality Log** — chronological table (newest first) with qualifier badge + short feedback label per day.
  - **Field Descriptions** — one-line explanation per field in the dataset. Garmin fields brief; context fields with units and context.
  - **Air Quality Guide** — visible only when airquality fields are present. AQI scale with colour-coded thresholds, PM2.5/PM10/NO₂/Ozone interpretation, WHO/EU reference values, correlation tips.
- `_FEEDBACK_SHORT` mapping added — 26 Garmin `sleepScoreFeedback` enum values mapped to short display labels.
- `_FIELD_DESCRIPTIONS` added — descriptions for all airquality, pollen, weather, and key Garmin fields.

**`tests/test_dashboard.py`:**
- Explorer specialist picked up by auto-discovery (section 7). 214/214 passed.

---

## v1.4.7 — Brightsky DWD Context Plugin

New context source: Brightsky API (Deutscher Wetterdienst) as third plugin alongside Open-Meteo weather and pollen.

**Architecture extension — `context/context_api.py`:**
- `from statistics import mean, mode as stats_mode` added.
- `_parse_brightsky(response, aggregation_map)` — new parser for Brightsky `weather[]` array structure. Aggregates hourly entries to daily values with field-specific methods (mean / sum / max / mode).
- `_fetch_chunk()` — new `adapter` parameter (`default="open_meteo"`). Brightsky uses different URL parameters (`lat`, `lon`, `date`, `last_date`, `tz`, `units`) vs. Open-Meteo (`latitude`, `longitude`, `start_date`, `end_date`). Dispatch by adapter string — not by URL.
- `fetch()` — reads `FETCH_ADAPTER` from plugin via `getattr`. Passes adapter to `_fetch_chunk()` and routes to `_parse_brightsky()` when `adapter == "brightsky"`. Open-Meteo path unchanged.

**New: `context/brightsky_plugin.py`:**
- Metadata-only plugin. `FETCH_ADAPTER = "brightsky"`, `AGGREGATION_MAP` with per-field method (mean/sum/max/mode), `CHUNK_DAYS = 30`, `SOURCE_TAG = "brightsky-dwd"`.
- `API_URL_HISTORICAL` and `API_URL_FORECAST` both point to single Brightsky endpoint — no split needed. `HISTORICAL_LAG_DAYS = 0`.

**New: `maps/brightsky_map.py`:**
- Field resolver for `context_data/brightsky/raw/`. Generic names → internal Brightsky keys. 9 fields: `temperature_avg`, `humidity_avg`, `precipitation_sum`, `sunshine_sum`, `wind_speed_max`, `wind_gust_max`, `cloud_cover_avg`, `pressure_avg`, `condition`.

**`context/context_collector.py`:**
- `brightsky_plugin` imported and added to `_PLUGINS`.
- `brightsky_plugin.OUTPUT_DIR` override added to `base_dir` block in `run()`.

**`maps/context_map.py`:**
- `brightsky_map` imported and registered in `_SOURCES` as `"brightsky"`.

**`garmin/garmin_config.py`:**
- `CONTEXT_BRIGHTSKY_DIR = CONTEXT_DIR / "brightsky" / "raw"` added.

**`build_manifest.py`:**
- `maps/brightsky_map.py` and `context/brightsky_plugin.py` added to `SHARED_SCRIPTS`.
- Signatures for both new modules added to `SCRIPT_SIGNATURES_BASE`.

**`garmin/garmin_writer.py`:**
- `read_summary(date_str)` — new function. Reads and returns a summary JSON file. Used by schema migration loop. Sole owner contract maintained.

**`garmin/garmin_collector.py`:**
- `_run_schema_migration(quality_data)` — new function. Iterates quality log days, checks `schema_version` against `CURRENT_SCHEMA_VERSION`, rewrites summary from raw if outdated. Log output per day `[i/total]`. No API call, no login required.
- Step 3c in `main()`: runs `_run_schema_migration()` when `GARMIN_SCHEMA_MIGRATE=1`.

**`garmin/garmin_app.py` + `garmin/garmin_app_standalone.py`:**
- `_check_schema_migration()` — new method. Scans `summary/` for outdated `schema_version`, shows backup warning popup (English) if candidates found. Returns `True` if user confirms.
- Sync trigger: sets `GARMIN_SCHEMA_MIGRATE=1` in env overrides when migration confirmed.

**`build_manifest.py`:**
- `maps/airquality_map.py`, `context/airquality_plugin.py`, `dashboards/explorer_garmin-context_html_dash.py` added to `SHARED_SCRIPTS`.
- `SCRIPT_SIGNATURES_BASE` — new entries: `airquality_plugin`, `airquality_map`, `garmin_writer.read_summary`, `garmin_collector._run_schema_migration`. Duplicate `garmin_collector` key removed.

**`tests/test_local_context.py`:**
- Section 4 added: `brightsky_plugin` metadata checks (FETCH_ADAPTER, AGGREGATION_MAP keys + methods, no AGGREGATION string).
- Section 6 extended: `_parse_brightsky()` — mean/sum/max/mode aggregation, null values, single-entry day.
- Section 10 added: `brightsky_map` field resolution, condition string field, intraday fallback, KeyError for unknown.
- Section 11 extended: `context_map` — `list_sources()` includes `"brightsky"`, `list_fields("brightsky")` correct, `get()` routes to brightsky.
- Section 13 extended: `run()` — brightsky plugin present in result, written=2, files on disk, source tag correct, skip on second run, network error → written=0.
- All section numbers updated (old 4–11 → new 5–12, new sections inserted at 4 and 10).

---

## v1.4.6 — Dashboard Features

**`dashboards/health_garmin_html-json_dash.py`:**
- Auto-size: actual data boundaries determined across all fields. `d_from`/`d_to` adjusted if requested range exceeds available data. Subtitle shows adjusted range + original request.
- Flag guard `sleep_duration`: `0.0h` treated as missing data (`val = None`) — Garmin delivers `0.0` when no sleep was recorded (device not worn).
- Local `_fitness_level` / `_reference_ranges` replaced by import from `layouts/reference_ranges.py`.
- New format target: `html_mobile` → `health_garmin_mobile.html`.

**`dashboards/timeseries_garmin_html-xls_dash.py`:**
- Auto-size: actual data boundaries determined from intraday timestamps. Subtitle shows adjusted range if applicable.

**`dashboards/health_garmin-weather-pollen_html-xls_dash.py`:**
- Auto-size: boundaries determined from Garmin fields only — context data excluded. Subtitle shows adjusted range if applicable.

**`dashboards/sleep_recovery_context_dash.py`:**
- Auto-size: boundaries determined from Garmin fields only. Subtitle shows adjusted range if applicable.
- Dynamic reference ranges: reads `age`/`sex` from `settings`, fetches VO2max, computes fitness level and thresholds via `layouts/reference_ranges.py`.
- Per-day status fields added to `daily` output: `hrv_status`, `body_battery_status`, `sleep_status`.

**`dashboards/overview_garmin_xls_dash.py`:**
- Auto-size: boundaries determined from loaded rows. `subtitle` key added to return dict.

**`layouts/dash_plotter_html.py`:**
- Flagged Day Markers: per-point `marker.color` and `marker.size` based on `status`. `customdata` passes status string to hovertemplate.
- Null values render as gaps via Plotly native `null` handling — no guard needed.

**`layouts/dash_plotter_html_complex.py`:**
- Flagged day markers: HRV, Body Battery, Sleep traces in Tab 1 use per-point `marker.color` and `marker.size`. Flagged points (`low`/`high`) rendered in red, larger size.

**`layouts/dash_layout.py`:**
- Measurement accuracy disclaimer added to `DISCLAIMER`. Applies to all HTML dashboards and Excel automatically.

**New: `layouts/reference_ranges.py`:**
- Shared reference range logic extracted from `health_garmin_html-json_dash.py`.
- Provides `fitness_level(age, sex, vo2max)` and `reference_ranges(age, sex, fitness)`.
- Used by `health_garmin_html-json_dash.py` and `sleep_recovery_context_dash.py`.

**New: `layouts/dash_plotter_html_mobile.py`:**
- Mobile-optimised HTML plotter for landscape phone viewing.
- All metrics stacked vertically — no tabs.
- Global range dropdown (All / last 7d / 30d / 90d / calendar months / calendar weeks) controls all charts simultaneously.
- Zoom/drag disabled. Reference band, baseline, and flagged markers included.

**`dashboards/dash_runner.py`:**
- `html_mobile` registered in plotter registry.
- `display_label()` returns `"mobile"` for `html_mobile`.

---

## v1.4.5 — Write Robustness + API Resilience

**`garmin/garmin_writer.py`:**
- `write_day()`: atomic writes via temp file + `os.replace()` — partial writes on crash no longer possible. Cleanup of temp files on failure.

**`context/context_writer.py`:**
- `write()`: atomic writes via temp file + `os.replace()` per day file.
- `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` — fixes Python 3.12 deprecation warning.

**`garmin/garmin_security.py`:**
- `_clear_token_dir()`: retry loop (3 attempts, 200 ms delay) — fixes intermittent WinError 5 when garminconnect briefly holds the token file handle after login.

**`garmin_app.py` / `garmin_app_standalone.py`:**
- Sync completion message changed from `✓ Done.` to `✓ Done. — please update context`.

**`context/context_api.py`:**
- `_fetch_chunk()`: retry with exponential backoff (3 attempts, 1s → 2s) — silent failures on HTTP 429/500 or unstable connections now logged and retried.
- New module-level constants: `_RETRY_COUNT = 3`, `_RETRY_BACKOFF = 1.0`.

---

## v1.4.4 — Token Path Fix (garmin_security lazy cfg)

Root cause fix for token not being found after app start or Reset Token, causing
an unexpected encryption key prompt on every sync.

**`garmin/garmin_security.py`:**
- Removed `import garmin_config as cfg` at module level — `cfg` was frozen
  at first import and ignored later `importlib.reload(cfg)` calls from the GUI.
- All four functions using `cfg` (`_clear_token_dir`, `save_token`,
  `load_token`, `clear_token`) now read `cfg` lazily via a local import at
  call time — always the current state after a reload.

**`garmin_app.py` / `garmin_app_standalone.py`:**
- Token indicator after login: state is now read from the actual
  disk state after login (`cfg.GARMIN_TOKEN_FILE.exists()`) instead of the
  pre-login boolean — indicator now correctly shows green after SSO.

**Diagnosis path:** Live log + Windows Credential Manager check → multi-LLM review
(Gemini, Copilot, Le Chat) → consensus: lazy cfg in `garmin_security.py` is
the right fix, not `importlib.reload(garmin_security)` in the GUI.

---

## v1.4.3 — Test Suite Extension (App Logic + Build Output)

Two new test modules completing the test suite. No changes to production code.

**`tests/test_app_logic.py`** — new, 80 checks, 10 sections:
- `DEFAULT_SETTINGS` completeness — both entry points (`garmin_app`, `garmin_app_standalone`)
- `load_settings` / `save_settings` — roundtrip, password strip, corrupt JSON → defaults, missing file → defaults
- `load_password` / `save_password` — keyring mock, None → empty string, exception → empty string, empty pw → delete
- `script_dir()` / `script_path()` — dev mode and frozen mode (mocked `sys.frozen` / `sys._MEIPASS` / `sys.executable`) for both entry points
- v1.4.2 regression check: `script_path()` frozen — file at wrong location (`scripts/garmin_collector.py` instead of `scripts/garmin/`) is not returned as correct path
- `_find_python()` — dev mode returns `sys.executable`; frozen mode returns `shutil.which()` result

**`tests/test_build_output.py`** — new, 8 sections:
- Section 1: `build_manifest` consistency — list invariants, no duplicates, signature keys valid
- Section 2: source integrity — all `SHARED_SCRIPTS` present in project folder, `REQUIRED_DATA_FILES` present, all signatures match (always runs, no build required)
- Section 3–6: Target 2 — EXE exists, `scripts/` folder structure complete, `py_compile` syntax check on all scripts, ZIP contents match manifest (runs after build)
- Section 7: Target 3 — Standalone EXE exists, larger than T2 EXE, ZIP contains EXE and no `scripts/` folder (embedded)
- Section 8: Target 3 embed validation — reconstructs `--add-data` destination paths exactly as `build_standalone.py` builds them; verifies all scripts land under `scripts/{subfolder}/`, never flat in `scripts/`; all subdirectories covered; `EMBEDDED_SCRIPTS == SHARED_SCRIPTS`

**`build_all.py`:**
- Post-build step added: `test_build_output.py` runs after both builds complete. Exit code 1 aborts and prints failed checks.

---

## v1.4.3 — Standalone Frozen-Path Hotfix

Fixed three path bugs in the standalone EXE — reported via user feedback.

**`garmin_app_standalone.py`:**
- `script_path()` — subfolder lookup (`garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/`, `export/`) now runs through `script_dir()` as the base in both modes (dev + frozen). In frozen mode the subfolder was previously ignored, leading to `Script not found: …/scripts/garmin_collector.py`.
- Context collector: corrected `_root` in frozen mode from `_MEIPASS` to `_MEIPASS/scripts/` — `context/` lives under `scripts/context/`, not directly under `_MEIPASS`.

**`build_standalone.py`:**
- Corrected the `garmin_dataformat.json` packaging target from `scripts` to `scripts/garmin` — `garmin_config.py` looks up the file via `Path(__file__).parent`, which resolves to `scripts/garmin/` in frozen mode.

---

## v1.4.3 — Value Range Validation + Test Hardening
Semantic validation of numeric field values against defined min/max ranges. Test suite extended to 218 checks.

**`garmin/garmin_dataformat.json`:**
- `sub_fields` added to `stress`, `heart_rates`, `respiration`, `spo2` — each sub_field carries `type`, `min`, `max` for range validation.
- `body_battery`, `training_readiness`, `max_metrics`, `activities` corrected to `type: "any"` — Garmin API delivers inconsistent types for these fields (list or dict depending on date/device). Eliminates persistent false-positive type_mismatch warnings.

**`garmin/garmin_validator.py`:**
- New issue type `out_of_range` (severity: `warning`) — emitted when a numeric sub_field value falls outside the schema-defined `min`/`max` range.
- Range check runs after structural type check. Only applies to numeric values (`int`, `float`). Sub_field absent → no issue.
- Issue field format: `parent_field.sub_key` (e.g. `heart_rates.restingHeartRate`).

**`garmin/garmin_collector.py`:**
- Range-warning downgrade: after `assess_quality()`, if `validator_result` contains > 3 `out_of_range` warnings and label is `high` or `medium`, label is capped to `low`.
- `assess_quality()` remains a pure function — downgrade decision stays in the collector.
- `low` label triggers standard recheck cycle: 3 attempts via `LOW_QUALITY_MAX_ATTEMPTS`, then `recheck: false`. Raw file is written and fully accessible regardless of label.

**`tests/test_local_context.py`:**
- 134 checks (up from 123). New checks across sections 4, 5, 6, 10, 11:
  - Section 4: `write({}, lat, lon)` → written=0, failed=0 (empty dict, no crash)
  - Section 5: `_parse_hourly_to_daily_max` with null values in arrays (Open-Meteo delivers null for missing entries) → no crash, max of non-null values correct, all-null field tolerated
  - Section 6: `fetch()` with network error (OSError) → returns empty dict, does not raise
  - Section 10: `_load_csv()` with malformed row → valid rows kept, bad row skipped
  - Section 11: `run()` with network error → returns dict, stopped=False, written=0

**`tests/test_dashboard.py`:**
- 211 checks (up from 193). New checks across sections 1, 6, 7, 10, 11, plus new `_NULL_DATE`/`_NULL_RAW` fixture:
  - Section 1: garmin_map with null intraday arrays in raw (heartRateValues=None, stressValuesArray=None, bodyBatteryValuesArray=None, empty spo2/respiration dicts) → series is None for all 5 series, no crash
  - Section 6: HTML output contains dataset title
  - Section 7: `dash_runner.build()` with invalid format key → success=False, error key present, no crash
  - Section 10: health specialist `build()` with summary missing `hrv_last_night_ms` → returns dict, field absent or value=None
  - Section 11: overview specialist `build()` over two dates → 2 rows returned, sorted ascending
  - Test isolation fix: after the no-hrv test in section 10, original `_SUMMARY` file is restored — prevents summary file overwrite from breaking section 12

**`tests/test_local.py`:**
- 218 checks (up from 199). New checks across sections 1, 3, 7, 9, and new section 14:
  - Section 1: `garmin_config` reload follows `GARMIN_OUTPUT_DIR`; `GARMIN_TOKEN_FILE` stays under `BASE_DIR`
  - Section 3: `garmin_normalizer.normalize({})` — no crash on empty dict
  - Section 7: `load_token` with corrupt `.enc` file → `False`; `save_token` with missing `garmin_tokens.json` → `False`
  - Section 9: `validate(None)` → no crash; `validate({})` → critical; `out_of_range` issue type and field name correct; in-range value → no issue
  - Section 14: downgrade count logic; threshold boundary (exactly 3 → no downgrade); `assess_quality()` pure function confirmed

---

## v1.4.2 — Bulk Upgrade + Downgrade Protection

Automatic upgrade of bulk-imported days to API quality within the 90-day API window, with full downgrade protection and per-day resume safety.

**`garmin/garmin_collector.py`:**
- `_process_day()` split into `_fetch_and_assess()` (fetch + normalize + assess, no write) and `_write_assessed()` (write only). Required for correct downgrade protection — write decision now happens after quality comparison.
- Step 3: bulk upgrade flagging — on every startup, days with `source: bulk` + `quality: medium` + date ≤ 90 days old are automatically flagged `recheck: true` for API re-fetch.
- Step 7: `bulk_upgrade_dates` set — bulk recheck days are always excluded from `local_dates`, regardless of `REFRESH_FAILED`. Normal failed/low recheck path unchanged.
- Step 8: downgrade protection — after `_fetch_and_assess()`, new label is compared to existing. If inferior: file not written, existing quality log entry preserved, `recheck: false` set to prevent repeat. Equal or better: write + upsert as `source: api`.
- Step 8: chunk logic removed. `_save_quality_log()` now called after every individual day — in all three paths (upgrade, downgrade, error). Every day is an atomic resume point. `SYNC_CHUNK_SIZE` config constant deprecated (no longer used).

---

## v1.4.1 — Auth Hotfix (garminconnect 0.3.x)

Garmin changed their authentication infrastructure in mid-March 2026. The `garth` library is deprecated, `garminconnect < 0.3.0` no longer works. This release updates the auth stack and fixes a config path bug in the connection test.

**`garmin/garmin_api.py`:**
- Path 3 (SSO) rewritten for `garminconnect 0.3.x`: `return_on_mfa=True` + `resume_login()` removed, replaced by `prompt_mfa=on_mfa_required` in constructor and `client.login(token_dir)`. `cfg.GARMIN_TOKEN_DIR.mkdir()` added before login call.
- Path 1 (token probe): 429/403 responses no longer fall back to SSO — `GarminLoginError` is raised immediately. Prevents cascading rate-limit hits (Garmin rate-limits by IP + clientId + account email combined).

**`garmin_app.py` / `garmin_app_standalone.py`:**
- `_run_connection_test()` worker: `GARMIN_OUTPUT_DIR`, `GARMIN_EMAIL`, `GARMIN_PASSWORD` are now set before `garmin_config` is imported, followed by `importlib.reload(cfg)`. Fixes a bug where `cfg` resolved to `~/local_archive` instead of the configured data folder, causing Path 1 to miss the saved token and fall through to SSO.
- `_timer_loop()` `_test_conn()`: same fix applied. Previously used raw `Garmin(email, pw)` + `client.login()` — bypassing token, ENV setup, and 429 protection entirely. Now routes through `garmin_api.login()` identically to `_run_connection_test()`.

**`requirements.txt`:**
- `garminconnect` minimum version bumped to `>=0.3.0`.

--- 

### v1.4.0 — Dashboard Features

New functionality built on the clean v1.4.0 base:

- ✅ **Sleep & Recovery Context Dashboard** — `sleep_recovery_context_dash.py` + `dash_plotter_html_complex.py`. HRV, Body Battery, Sleep with sleep phase composition (Deep/Light/REM/Awake %) + temperature and pollen context. Tab 1: daily dual-Y overview + stacked sleep phase bars. Tab 2: intraday drill-down per day. New `raw_pct` field type in `garmin_map`.
- ✅ **Disclaimer strengthened** — medical disclaimer now includes source citations (AHA, ACSM, Garmin/Firstbeat) and individual variation note.
- ✅ **Baseline note** — `health_garmin_html-json_dash` adds human-readable explanation of the 90-day dashed baseline line to the disclaimer area.

**Deferred to Stufe 2 (Sleep & Recovery):**
- Sleep window as shaded band on X-axis (requires `sleepStartTimestampGMT` / `sleepEndTimestampGMT` — data available in raw/)
- Humidity trace (requires `weather_plugin.py` + `weather_map.py` extension + re-collect)
- Sleep phase optimal range bands (`sleepScores.remPercentage.optimalStart` etc. available in raw/)

---

## v1.4.0 — Dashboard Architecture Refactoring

Replaces four monolithic export scripts with a modular specialist/plotter architecture. No new dashboard content — pure architectural work. Serves as v2.0 testbed: validates the `field_map` / `context_map` data broker pattern with real Garmin and Open-Meteo data before a second source makes a redesign expensive.

**New architecture:**

| Layer | Module | Role |
|---|---|---|
| Runner | `dashboards/dash_runner.py` | Auto-discovery of specialists, popup matrix, orchestration |
| Specialist | `dashboards/*_dash.py` | Declares META, fetches data via brokers, returns neutral Dict |
| Plotter | `layouts/dash_plotter_*.py` | Renders Dict to output format — no knowledge of data sources |
| Layout | `layouts/dash_layout*.py` | Passive resources: CSS, color tokens, disclaimer, footer, prompt templates |
| Broker | `maps/field_map.py` | Routes specialist requests → `garmin_map` → `garmin_data/` |
| Broker | `maps/context_map.py` | Routes specialist requests → `weather_map` / `pollen_map` / `brightsky_map` → `context_data/` |

**New modules:**

- `dashboards/dash_runner.py` — scans `dashboards/` at startup, builds GUI popup matrix, orchestrates build
- `dashboards/timeseries_garmin_html-xls_dash.py` — intraday HR, Stress, SpO2, Body Battery, Respiration
- `dashboards/health_garmin_html-json_dash.py` — HRV, Resting HR, SpO2, Sleep, Body Battery, Stress with 90-day baseline + age/fitness-adjusted reference ranges
- `dashboards/overview_garmin_xls_dash.py` — daily summary table, all fields, Activities sheet
- `dashboards/health_garmin-weather-pollen_html-xls_dash.py` — Garmin health + Weather + Pollen context (first multi-source specialist)
- `layouts/dash_layout.py` — shared color tokens, metric metadata, disclaimer, footer
- `layouts/dash_layout_html.py` — HTML-specific CSS, Plotly CDN, template builders
- `layouts/dash_plotter_html.py` — renders Dict → self-contained HTML with Plotly charts + tabs. Supports Timeseries (single trace) and Analysis (4 traces: value, baseline, reference band) chart types
- `layouts/dash_plotter_excel.py` — renders Dict → .xlsx. Timeseries/Analysis mode: per-field data + chart sheets. Overview mode: broad flat table
- `layouts/dash_plotter_json.py` — renders Dict → .json data dump + `_prompt.md` start prompt (always together)
- `layouts/dash_prompt_templates.py` — passive resource: Markdown prompt templates per specialist type for Open WebUI / Ollama

**Changed modules:**

- `garmin_map.py` — intraday normalization: `_FIELD_MAP` extended with `extract` descriptor per field (`ts_index`, `val_index`, `ts_key`, `val_key`, `val_min`, `offset_key`). New `_ts_to_iso()` and `_extract_series()` — raw Garmin arrays normalized to `[{"ts": str, "value": float}, ...]` before leaving the module. Garmin-internal knowledge stays entirely inside `garmin_map`
- `maps/api_map.py` renamed to `maps/context_map.py` — name reflects actual function (reads local context archive, never calls live APIs)
- `garmin_app.py` / `garmin_app_standalone.py` — four individual export buttons replaced by single "📊 Berichte erstellen" button. Opens popup matrix: rows = specialists, columns = available formats, checkboxes for selection. Build runs in background thread with progress log
- `build_manifest.py` — `dashboards/` and `layouts/` modules added
- `build_all.py` — `test_dashboard.py` added to pre-build test sequence

**Removed:**

- `export/garmin_timeseries_html.py` — replaced by `timeseries_garmin_html-xls_dash.py` + `dash_plotter_html.py`
- `export/garmin_timeseries_excel.py` — replaced by `timeseries_garmin_html-xls_dash.py` + `dash_plotter_excel.py`
- `export/garmin_analysis_html.py` — replaced by `health_garmin_html-json_dash.py` + `dash_plotter_html.py` + `dash_plotter_json.py`
- `export/garmin_to_excel.py` — replaced by `overview_garmin_xls_dash.py` + `dash_plotter_excel.py`

**Testing:**

- `tests/test_dashboard.py` — 166 checks, 12 sections, no network, no GUI. Covers full pipeline: `garmin_map` intraday normalization → `field_map` routing → layout resources → all specialists → all plotters → runner

**Hotfix — garminconnect 0.3.x compatibility (April 2026):**

- `garmin/garmin_api.py` — Path 3 (SSO) angepasst: `return_on_mfa=True` + `resume_login()` entfernt, ersetzt durch `prompt_mfa=on_mfa_required` im Konstruktor und `client.login(token_dir)`. Hintergrund: Garmin hat im März 2026 den Auth-Flow geändert, `garth` ist deprecated, `garminconnect ≥ 0.3.0` verwendet neuen Mobile-SSO-Flow mit `curl_cffi`. Frischer SSO-Login nach Update erforderlich (alter Token inkompatibel).

---

## v1.3.4— API Structure Validation

Introduces a dedicated validation layer at the pipeline entry point. Closes the gap between raw API data and the normalizer, which previously assumed structural correctness without verification.

**New modules:**
- `garmin_validator.py` — structural integrity check against `garmin_dataformat.json`. Runs before `garmin_normalizer.py` on every incoming raw dict — both API sync and bulk import paths. Degraded mode: no hard stop on warning, critical skips the day. Returns a structured result object per call. Leaf-node: imports only `garmin_config` and standard libs.
- `garmin_dataformat.json` — schema definition: 15 fields, `required`/`optional` categories, expected types, schema version `1.0`. Minor version for optional changes, major version for required-field changes.

**Changed modules:**
- `garmin_config.py` — `DATAFORMAT_FILE` path constant added.
- `garmin_normalizer.py` — `_EXPECTED_DICT` / `_EXPECTED_LIST` type checks removed. Structural validation is now the sole responsibility of `garmin_validator.py`. Minimal guard remains: `ValueError` on non-dict input.
- `garmin_quality.py` — `_upsert_quality()` extended with optional `validator_result` parameter (dict, default `None`). Three new fields per day entry in `quality_log.json`: `validator_result` (`"ok"` / `"warning"` / `"critical"`), `validator_issues` (structured list), `validator_schema_version`. Existing callers without the parameter are unaffected.
- `garmin_writer.py` — `read_raw(date_str) → dict` added. Sole read access to `raw/` — used exclusively by the self-healing loop. Returns `{}` on missing or corrupt file.
- `garmin_collector.py` — validator wired into both pipeline paths. `_process_day()` returns `(label, written, fields, val_result)`. `run_import()` skips days with `critical` validator result. New `_run_self_healing()` function: runs at every process start, revalidates days with open issues when schema version has changed — no API call, reads from `raw/` only. Quality re-evaluated only if validator result actually changes.

**Validator issue types:**

| Type | Trigger | Status |
|---|---|---|
| `missing_required` | required field absent or wrong type | `critical` |
| `type_mismatch` | known field present but wrong type | `warning` / `critical` if required |
| `missing_optional` | optional field absent | `ok` — logged only |
| `unexpected_field` | field not in schema | `warning` |

**Testing:**
- `test_local.py` — Section 6 updated (new `_process_day` signature), Section 4 extended (validator fields in quality log), Section 9 added (garmin_validator — 18 checks), Section 10 added (garmin_writer read_raw — 4 checks). Total: 177 checks.

---

## v1.3.3 — Error Log Access + Chunked Sync + QoL

**Error log access:**
- `garmin_app.py` / `garmin_app_standalone.py` — new "📋 Copy Last Error Log" button in Output section. Reads the most recent file from `log/fail/`, copies its contents to the clipboard. `self.update()` called after `clipboard_append()` to ensure Windows retains the clipboard contents after focus changes. If `log/fail/` is absent or empty, a clear message is written to the GUI log instead.

**Chunked sync:**
- `garmin_config.py` — new `SYNC_CHUNK_SIZE` constant (ENV: `GARMIN_SYNC_CHUNK_SIZE`, default: 10). Set to `0` to disable chunking (single pass, previous behaviour).
- `garmin_collector.py` — fetch loop restructured: `batch` is split into sub-lists of `SYNC_CHUNK_SIZE` days. `quality_log.json` is flushed to disk after each chunk via `_save_quality_log()`, within the existing `QUALITY_LOCK`. If a sync is interrupted mid-run, the next run resumes automatically from the first unwritten day — no separate checkpoint state needed. Stop-event aborts the current chunk cleanly via `for/else` pattern. `run_import()` is unaffected — chunking applies to API sync only.

**QoL:**
- `garmin_app_standalone.py` — header label updated from `"local · private · yours"` to `"local · private · yours · Standalone"`. Makes the build variant immediately visible in screenshots and support contexts.

**Testing:**
- `test_local.py` — 1 new check: `SYNC_CHUNK_SIZE` default value. Total: 142 checks.

---

## v1.3.2 — Auth Stack Rebuild + Version Check + QoL

**Auth stack rebuild (garminconnect ≥ 0.2.40):**
- `garmin_config.py` — `GARMIN_TOKEN_DIR = LOG_DIR / "garmin_token"` added (temporary working dir for library). `GARMIN_TOKEN_FILE` unchanged.
- `garmin_security.py` — `save_token()` now reads `garmin_tokens.json` written by the library, encrypts its contents, writes `garmin_token.enc`, then removes the working dir. `load_token()` decrypts `garmin_token.enc` and writes `garmin_tokens.json` back into `GARMIN_TOKEN_DIR` so the library can read it directly — returns `bool` instead of `str`. `clear_token()` also removes `GARMIN_TOKEN_DIR`. New internal helper `_clear_token_dir()`. AES-256-GCM and WCM/keyring unchanged.
- `garmin_api.py` — `login()` rewritten for new library API: token path uses `Garmin()` + `garmin.login(token_dir)` instead of `garth.loads()`. SSO path uses `Garmin(email, pw, return_on_mfa=True)`. New `on_mfa_required` callback — returns MFA code or `None` to cancel. `_clear_token_dir()` called after token login to remove plaintext from disk.
- `garmin_app.py` / `garmin_app_standalone.py` — new `_prompt_mfa()` popup (non-blocking input dialog). `on_mfa_required` callback wired into `garmin_api.login()`.
- `test_local.py` — security tests updated for new `bool` return values and file-based round-trip. `GARMIN_TOKEN_DIR` path check added.

**Version check on startup:**
- `garmin_app.py` / `garmin_app_standalone.py` — `APP_VERSION` constant added (replaces hardcoded version string in header). Background thread checks GitHub API on startup, shows non-blocking update popup if a newer release is available. Silent on no internet or no update.

**QoL:**
- `garmin_app.py` / `garmin_app_standalone.py` — "→ Open README" link added next to "Request export at garmin.com". Opens `README_APP.md` in the system default text editor.

---

## v1.3.1 — Archive Info Panel

**New feature:**
- `garmin_quality.py` — new `get_archive_stats(quality_log_path=None)` function: reads `quality_log.json` directly from a given path (no ENV required) and returns a plain dict with total days, quality breakdown, recheck count, date range, coverage %, last API date, last bulk date. No API call, no side effects.
- `garmin_app.py` / `garmin_app_standalone.py` — CONNECTION section replaced with **CONNECTION & ARCHIVE STATUS** panel. Status indicators (Token / Login / API Access / Data) moved inline into the button row. Archive info panel added below: two compact rows showing Days, quality breakdown with colour-coded dots, Recheck count, date range, coverage %, Last API, Last Bulk. Populated on startup from Settings path — no sync required. Refreshes automatically after every Sync and Bulk Import.
- Test Connection button removed — it had no assigned command and was never clickable.

---

## v1.3.0c — Bulk Import Summary Fix

**Bug fix:**
- `garmin_normalizer.py` — `_normalize_import()`: HR aggregate values (`restingHeartRate`, `minHeartRate`, `maxHeartRate`) were present in `user_summary` after bulk import but not accessible to `summarize()`, which reads from `heart_rates`. Fix: `_normalize_import()` now copies these fields into `heart_rates` when the key is absent.
- `garmin_normalizer.py` — `summarize()`: stress fields (`stress_avg`, `stress_max`) were always `None` after bulk import because `summarize()` computed them from `stressValuesArray` — an intraday array not present in GDPR exports. Fix: fallback to precomputed aggregate fields `averageStressLevel` / `maxStressLevel` when no array is available. API path unaffected.

**Notes:**
- Body Battery, HRV, SpO2, Respiration remain `null` after bulk import — these fields are not included in the Garmin GDPR export.
- Users who ran bulk import before this fix and have a `quality_log.json` without `source` fields can use the one-time migration script `fix_quality_source.py` (sets `source="api"` for all entries without a source field) to restore correct skip behaviour before re-importing.

---

## v1.3.0b — Bulk Import Subprocess Fix

**Bug fix:**
- `garmin_app.py` + `garmin_app_standalone.py`: `_run_import()` ran the bulk import in-process via `importlib.reload()`. `garmin_config` was already cached in memory — `cfg.RAW_DIR` pointed to the default path (`~/garmin_data/raw/`) instead of the configured folder. Files were written there silently; the configured archive received nothing.
- Fix: `garmin_collector.main()` now checks `GARMIN_IMPORT_PATH` at startup (before login, before sync). If set, it calls `run_import()` and exits. `_run_import()` in both GUIs now delegates to `_run_script()` (Target 1+2) and `_run_module()` (Target 3) with `env_overrides={"GARMIN_IMPORT_PATH": path}` — identical pattern to the normal API sync. `garmin_config` is always loaded fresh in the new process/module context.
- Stop button is now active during bulk import (consistent with API sync).
- Log prefix `garmin_bulk` — import sessions produce `garmin_bulk_YYYY-MM-DD_HHMMSS.log`, separate from API sync logs.

**Architecture:**
- `garmin_collector.main()` now supports delegated entry points via ENV flags. Pattern is extensible for v2.0 (`STRAVA_IMPORT_PATH`, `KOMOOT_IMPORT_PATH` etc.) — one entry point, multiple source modes.

**Docs:**
- `REFERENCE.md`: `GARMIN_IMPORT_PATH` added to ENV variable table.

---

## v1.3.0a — Hotfix + Polish

**Bug fix:**
- `garmin_app.py` + `garmin_app_standalone.py`: `_run_import()` now pauses the background timer before starting the import thread and resumes it in a `finally` block after completion. Previously the timer and import could write to `raw/` and `summary/` concurrently — the Writer has no own lock, only `QUALITY_LOCK` protects `quality_log.json`.

**GUI:**
- Import button: link to Garmin export page added below the button (`→ Request export at garmin.com`)
- Import button description updated to include "recommended for history"

**Docs:**
- README: test count corrected (98 → 136), Bulk Import section added prominently, Download table added, second pipeline flow diagram for bulk import added, Garmin export link added
- MAINTENANCE: Timer + bulk import interaction documented

---

## v1.3.0 — Bulk Import + Field-Level Quality

Garmin GDPR export import and per-endpoint quality tracking. Two independent features delivered together.

**Bulk Import:**
- `garmin_import.py` — fully implemented (was placeholder since v1.2.0). `load_bulk(path)` reads a Garmin GDPR export ZIP or unpacked folder and yields one raw dict per day. `parse_day(entries, date_str)` assembles a day from UDSFile (steps, HR, calories, stress aggregates), sleepData (sleep stages), TrainingReadinessDTO (readiness level), and summarizedActivities. Iterator design: read → build → write → repeat — partial imports survive aborts.
- `garmin_collector.py`: `run_import(path)` — new public function. Iterates `load_bulk()`, runs each day through the full pipeline (normalize → summarize → assess → write), skips days already present with `high`/`medium` quality from API, writes quality log after each day. Returns `{"ok", "skipped", "failed"}`.
- `garmin_normalizer.py`: `_normalize_import()` fully implemented — applies same type validation as `_normalize_api()`. Bulk data maps directly to canonical schema via `parse_day()`.
- Bulk data characteristics: no intraday data in GDPR export → quality always `medium` or `low`, never `high`. `recheck=False` for all bulk entries — no live source to re-fetch from. `source="bulk"` in quality log.
- `garmin_app.py` + `garmin_app_standalone.py`: Import button added to DATA COLLECTION section. ZIP/folder choice dialog. Runs in background thread, progress logged to existing log window.

**Field-Level Quality:**
- `garmin_quality.py`: `assess_quality_fields(raw) → dict` — new pure function. Returns one quality label (`high`/`medium`/`low`/`failed`) per endpoint: `heart_rates`, `stress`, `sleep`, `hrv`, `spo2`, `stats`, `body_battery`, `respiration`, `activities`, `training_status`, `training_readiness`, `race_predictions`, `max_metrics`.
- `garmin_quality.py`: `_upsert_quality()` extended with optional `fields` parameter — stores per-endpoint scores in quality log entry. Existing calls without `fields` are unchanged.
- `garmin_quality.py`: `_load_quality_log()` migration — existing entries without `fields` receive `"fields": {}` on first load.
- `garmin_collector.py`: `_process_day()` now calls `assess_quality_fields()` and passes result to `_upsert_quality()`. Return value extended to `(label, written, fields)`.
- Top-level `quality` field unchanged — all existing logic (timer, recheck, collector) continues to work against it. `fields` is additive.
- `build_manifest.py`: signatures for `garmin_import.py` (`load_bulk`, `parse_day`) and `run_import` in `garmin_collector.py` added.

**Testing:**
- `test_local.py`: 20 new checks — `assess_quality_fields` (high/medium/failed), `_upsert_quality` with fields (new entry, update, None→no key), migration `fields={}`, `_process_day` fields return. Total: 136 checks (previously 116).

---

## v1.2.2a — Rate Limit Hotfix

Hotfix for HTTP 429 (Too Many Requests) handling. No architectural changes.

**Rate limit protection:**
- `garmin_api.py`: HTTP 429 is now explicitly detected in `api_call()` and triggers an immediate stop via `_STOP_EVENT` instead of being treated as a regular warning and continuing. A `CRITICAL` log entry is written on stop.
- `garmin_api.py`: `fetch_raw()` now checks for a stop request at the start of each endpoint iteration. A 10–20 sec inter-day pause is added after all 14 endpoints of a day have been processed (skipped if stopped).
- `garmin_config.py` / `garmin_app.py` / `garmin_app_standalone.py`: Default request delays raised from 1/3 sec to 5/20 sec to protect new installations from rate-limit bans out of the box.

---

## v1.2.2 — Schema Versioning

Introduces schema versioning for summary files and origin tracking for quality log entries. No architectural changes.

**Schema versioning:**
- `garmin_normalizer.py`: `CURRENT_SCHEMA_VERSION = 1` added as module constant. Increment when fields in `summarize()` are added, removed, or renamed.
- `garmin_normalizer.py`: `summarize()` now writes `"schema_version": CURRENT_SCHEMA_VERSION` into every summary dict. Basis for Smart Regeneration in v1.3.x — summaries where `schema_version < CURRENT_SCHEMA_VERSION` can be detected and regenerated without hitting the Garmin API.

**Origin tracking:**
- `garmin_quality.py`: `_upsert_quality()` extended with `source` parameter (`"api"` | `"bulk"` | `"csv"` | `"manual"` | `"legacy"`). Default: `"legacy"`. Stored in every quality log entry. Most recent write always wins.
- `garmin_quality.py`: `_load_quality_log()` migration — existing entries without `source` field receive `"source": "legacy"` on first load.
- `garmin_quality.py`: `_backfill_quality_log()` passes `source="legacy"` explicitly.
- `garmin_collector.py`: active API pull passes `source="api"` to `_upsert_quality()`. Scan for newly discovered low/failed files retains default `"legacy"`.

**Tests:**
- `test_local.py`: 4 new checks — `schema_version=1` in summary output, `source=legacy` (default), `source=api` (explicit), migration `source=legacy` for existing entries. Total: 116 checks.

---

## v1.2.1 — Bug Fixes + Security + Polish

Bug fixes, security improvements, and GUI polish. No architectural changes.

**Bug fixes:**
- `garmin_api.py`: `login()` no longer calls `sys.exit(1)` on failure — replaced with `GarminLoginError` exception. `sys.exit(0)` on user cancel replaced with `return None`. `garmin_collector.py` catches both cases and closes the session log cleanly in all exit paths.
- `garmin_api.py`: `fetch_raw()` now returns `(raw, failed_endpoints)` tuple instead of just `raw`. Failed endpoints are explicitly tracked and logged as warnings by the collector. Previously the `success` flag from `api_call()` was silently discarded.
- `garmin_normalizer.py`: `_normalize_api()` now validates types of all known structured keys before passing data downstream. Keys with unexpected types (e.g. a string where a dict is expected) are removed and logged. Prevents silent corruption from unexpected Garmin API responses.
- `garmin_quality.py`: `QUALITY_LOCK = threading.Lock()` added at module level. `garmin_collector.py` acquires it around all quality log read-modify-write sequences (steps 3, 6, and 8+9). Preventive — the UI mutex already prevents concurrent access in practice, but the lock makes the invariant explicit and safe for future features.

**Security:**
- `garmin_security.py`: Fixed salt replaced with `os.urandom(16)` random salt generated on each `save_token()`. New token file format: `[salt 16B][nonce 12B][ciphertext]`. Salt is read back on `load_token()`. Eliminates fixed-salt weakness — each save produces a unique ciphertext. Existing token files in the old format will fail to decrypt on first run — a clean re-login is required (no health data lost).
- `garmin_app.py` + `garmin_app_standalone.py`: Recovery dialog text corrected — previously implied that re-entering the encryption key would restore the saved token. With random salt this is no longer possible; the dialog now correctly states that a re-login will follow.

**GUI:**
- All remaining German labels translated to English: "Min. Tage pro Run" → "Min. Days per Run", "Max. Tage pro Run" → "Max. Days per Run", messagebox "Fehlerhafte Datensätze gefunden" → "Incomplete records found".
- Request delay changed from fixed `1.5s` to random float between configurable min/max (default `1.0`–`3.0s`). GUI shows two fields: "Delay min (s)" / "Delay max (s)". ENV: `GARMIN_REQUEST_DELAY_MIN` / `GARMIN_REQUEST_DELAY_MAX`.
- Export date range: leaving "From" or "To" empty now defaults to the oldest/newest file in `summary/` instead of a hardcoded 90-day window.
- Default data folder changed from `C:\garmin` to `Path.home() / "garmin_data"` — works on all systems regardless of drive letter.

**Testing:**
- `test_local.py`: 3 new QUALITY_LOCK tests, 2 `fetch_raw` mocks updated to tuple return, `_derive_aes_key` tests updated for salt parameter, `import threading` moved to top-level. Total: 112 checks (previously 98).

---

## v1.2.1b — Code Hygiene

Technical debt cleanup. No functional changes.

**Build:**
- `build_manifest.py` added — single source of truth for all script lists and signatures shared between build scripts. `SHARED_SCRIPTS`, `SCRIPT_SIGNATURES_BASE`, `RUNTIME_DEPS`, `INFO_INCLUDE_T2/T3`, `DOCS` defined here. Both build scripts import from it — adding a new module requires one edit in one place.
- `build.py` + `build_standalone.py`: all hardcoded lists removed, imported from `build_manifest`. Step numbering unified to `[1/4]`–`[4/4]`.
- `build_all.py` added — runs both build targets sequentially. Standalone build is not started if the standard build fails.

**Shared utilities:**
- `garmin_utils.py` added — shared helpers with no project-module dependencies. Contains `parse_device_date()` (consolidated from `garmin_api.py` and `garmin_quality.py`) and `parse_sync_dates()` (extracted from `garmin_config.py`).
- `garmin_config.py`: SYNC_DATES parsing loop replaced by `garmin_utils.parse_sync_dates()`. `from datetime import date` import removed. Docstring principle ("no logic") now holds.
- `garmin_api.py` + `garmin_quality.py`: local `_parse_device_date()` definitions removed, replaced with `_parse_device_date = utils.parse_device_date` alias.

**Testing:**
- `test_local.py`: new section 8 (`garmin_utils`) with 11 checks covering `parse_device_date` and `parse_sync_dates`. Makes import failures from `garmin_utils` immediately identifiable instead of surfacing as a cascading `ImportError` in section 1.

---

## v1.2.0 — Collector Refactoring + Token Persistence + Architecture Extension

Architectural overhaul of the collector pipeline plus encrypted token persistence. The collector changes have no end-user impact. Token persistence eliminates repeated SSO logins that triggered Captcha/MFA, especially critical in the Standalone version.

**New modules:**
- `garmin_config.py` — all ENV variables, constants, and derived paths centralised here. No module reads `os.environ` directly anymore.
- `garmin_api.py` — login, `api_call`, `fetch_raw`, `get_devices` extracted from collector. `login()` is now a standalone function. `_STOP_EVENT` injection extended here for standalone stop support.
- `garmin_normalizer.py` — new adapter layer between data sources and the pipeline. `normalize(raw, source)` as single entry point. `summarize()` moved here from collector. Extensible for future import sources (bulk, CSV, manual).
- `garmin_quality.py` — sole owner of `quality_log.json`. All quality functions extracted from collector. `cleanup_before_first_day()` now called by GUI Clean Archive button instead of inline write logic.
- `garmin_sync.py` — date strategy extracted from collector. `resolve_date_range` receives `first_day` as parameter, `get_local_dates` receives `recheck_dates` as parameter — no internal file reads.
- `garmin_import.py` — placeholder for future Garmin bulk export import. Structure and interfaces defined, implementation planned for a later version.
- `garmin_writer.py` — new module. Sole owner of `raw/` and `summary/`. Single public entry point: `write_day(normalized, summary, date_str) -> bool`.

**Collector changes:**
- `garmin_collector.py` reduced to thin orchestrator — coordinates modules, no write logic, no business logic
- `_should_write(label)` — isolated decision function: returns `True` if quality label is acceptable for writing
- `_process_day(client, date_str)` — isolated processing function: fetch → normalize → summarize → assess → write. Returns `(label, written)`
- `summarize()`, `safe_get()`, `_parse_list_values()` moved to `garmin_normalizer.py`
- Direct file writes (`json.dump` to `raw/` and `summary/`) replaced by `garmin_writer.write_day()`
- Config block (60 lines) replaced by `import garmin_config as cfg`
- 19 functions removed (moved to their respective modules)
- 5 legacy aliases removed (`_upsert_failed`, `_remove_failed`, `_load_failed_days`, `_save_failed_days`, `_mark_quality_ok`)
- `MAX_DAYS_PER_SESSION` (default 30) applied in fetch loop — `0` = unlimited

**Quality log changes:**
- Quality level `"med"` renamed to `"medium"` throughout — `assess_quality()`, `_upsert_quality()`, all log strings
- Automatic migration: existing `"med"` entries in `quality_log.json` are upgraded to `"medium"` on first load
- `write` field added to every day entry: `true` = files written successfully, `false` = write skipped or failed, `null` = pre-v1.2.0 entry (unknown)
- `_upsert_quality()` extended with `written` parameter — collector passes the result from `garmin_writer`

**App changes:**
- `garmin_app.py` + `garmin_app_standalone.py`: Clean Archive Button now calls `garmin_quality.cleanup_before_first_day()` instead of writing `quality_log.json` directly
- `garmin_app_standalone.py`: `_STOP_EVENT` injection extended to `garmin_api` module
- Version bumped to v1.2.0 in both GUI files

**Token Persistence (new in v1.2.0):**
- `garmin_security.py` — new module. Sole authority over token encryption/decryption. AES-256-GCM + PBKDF2-HMAC-SHA256 (600k iterations). No plaintext on disk
- `garmin_api.py`: `login()` extended with 3-path token flow — token valid → no SSO; token expired → 429 warning popup → SSO; no token → SSO + save
- `garmin_config.py`: `GARMIN_TOKEN_FILE = LOG_DIR / "garmin_token.enc"` added
- `garmin_app.py` + `garmin_app_standalone.py`: Token lamp added (4th indicator, shown before Login), Test Connection button click removed (check runs automatically on Sync/Timer), Reset Token button added, enc-key setup popup and token-expired warning popup added
- New dependency: `cryptography` (AES-256-GCM)
- Token file stored in `LOG_DIR` — not in `BASE_DIR` root to avoid accidental deletion

**Build changes:**
- `build.py` + `build_standalone.py`: `garmin_security.py`, `garmin_writer.py`, and `cryptography` added to script lists and dependency checks
- `validate_scripts()` added to both build scripts — pre-build check that verifies all required scripts are present and contain their expected function/class signatures. Build aborts immediately with a clear message if any check fails. Catches missing files and accidentally replaced file content before PyInstaller runs

**Testing:**
- `test_local.py` added — local test script covering all core modules (98 checks: config, sync, normalizer, quality incl. migrations, writer, collector internals, security crypto layer). No network, no API, no GUI required. Run with `python test_local.py`

---

## v1.1.2 — First Day Patch
- `first_day` anchor added to `quality_log.json` — detected once on first run (devices → account profile → fallback → oldest local file), never overwritten
- Device history (`name`, `id`, `first_used`, `last_used`) stored in `quality_log.json`, refreshed on every successful login
- One-time backfill on upgrade: all existing `raw/` files (including `high`/`med` quality) are now registered in the quality log — previously only `low` and `failed` days were tracked
- Auto mode and background timer now read `first_day` directly — no repeated device API calls on every sync
- **Clean Archive** button added to CONNECTION section — preview popup lists all files before `first_day`, deletes on confirm
- Bug fix: device dates stored as Unix timestamps are now correctly converted to ISO dates on read and write
- `_parse_device_date()` helper added for robust timestamp normalisation
- `_backfill_quality_log()`, `_set_first_day()`, `cleanup_before_first_day()` added to `garmin_collector.py`

---

## v1.1.1 — Background Timer + Quality Level
- Background timer added — automatically repairs and fills the archive while the app is open
- Three modes per cycle: **Repair** (failed days), **Quality** (low-content days), **Fill** (completely missing days)
- Configurable interval (min/max) and days-per-run (min/max)
- Live countdown shown in timer button
- Own connection test before first run
- Stops cleanly on app close or when all queues are empty
- Background sessions logged with `garmin_background_` prefix — source immediately identifiable in `log/fail/`
- `quality_log.json` replaces `failed_days.json` — automatic migration on first run
- `GARMIN_REFRESH_FAILED=1` flag: days with `recheck=true` treated as missing and re-fetched
- Content-based quality assessment replaces file-size heuristic
- `assess_quality(raw)` returns `high`, `medium`, `low`, or `failed` based on actual data content
- `high`: intraday data present (HR values, stress curve, sleep stages)
- `medium`: daily aggregates only — expected for Garmin data older than ~1–2 years
- `low`: minimal summary-level data only
- `failed`: API error, no usable file
- `LOW_QUALITY_MAX_ATTEMPTS` (default 3): after N attempts without improvement, `low` days set `recheck=false` permanently

---

## v1.1.0 — Failed Days + Session Logging
- Failed and incomplete days tracked in `failed_days.json`
- Popup before sync: re-fetch failed days in current range (Ja/Nein)
- Session logging: every sync writes a full DEBUG log to `log/recent/`
- Sessions with errors or incomplete downloads copied to `log/fail/` permanently
- Rolling limit: 30 files in `log/recent/`

---

## v1.0 — Standalone EXE
- Target 3 introduced: fully self-contained standalone EXE — no Python required on target machine
- `garmin_app_standalone.py` — uses `_run_module()` instead of `_run_script()`, scripts run as imported modules in threads
- Output capture via `_QueueWriter` / `_QueueHandler` → Queue → 50ms poll → GUI log
- Stop mechanism via `threading.Event` injected into module dict
- `build_standalone.py` added
- Log level toggle added: Simple (INFO) / Detailed (DEBUG)
- Hint shown in GUI if log level is changed while a sync is running
- Connection test indicators added: Login / API Access / Data
- Each indicator turns green on success, red on failure
- Connection test result cached for the session — subsequent syncs skip re-testing
- GUI polish and visual refinements

---

## v0.9 — Rename + ZIP Cleanup
- File and folder naming cleaned up
- ZIP packaging refined for distribution

---

## v0.6 — Window Size + Export Range
- Window size adjustments
- Export date range fields added to GUI

---

## v0.5 — Config
- Settings saved to `~/.garmin_archive_settings.json`
- All config fields editable in GUI without touching source files

---

## v0.4 — Keyring
- Password stored in Windows Credential Manager via `keyring`
- Never written to disk as plain text

---

## v0.3 — ZIP
- Build output packaged as ZIP for distribution

---

## v0.2 — Stop + Link
- Stop button added for collector
- GitHub link added to header

---

## v0.1 — Folder Structure
- `raw/` and `summary/` two-layer archive structure established
- `scripts/` and `info/` subfolders introduced

---

## v0 — Stable Baseline
- Initial working version: Target 2 standard EXE (Python required on target)
- GUI with basic settings, sync, and export buttons
- `garmin_collector.py` fetches and archives Garmin Connect data
- Excel and HTML export scripts

## Pre-v0 — Early Experiments
- Basic idea
- First Python scripts
