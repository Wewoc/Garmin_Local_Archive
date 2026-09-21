# Garmin Local Archive — REFERENCE_INVARIANTS

Module- and feature-specific invariants. Core architecture invariants
(sole-write-authority overview, layer separation, locking principle,
bootstrap order) live in [`GLA_GUIDELINES.md`](GLA_GUIDELINES.md) —
this file is the per-module detail, to consult when that specific
module is being touched.

Pure rules, not session history or rationale — for the reasoning behind
a given rule, see `CHANGELOG.md`.

---

## Security / Token

- `garmin_security.py` — `cfg` is imported lazily (local import inside each function); sole owner of `garmin_token.enc` and `garmin_token_log.json` (events: `created`/`invalidated`/`blocked`/`valid`; `valid` is serialized compactly, all others with `indent=2`; the `caller` field reads `GARMIN_SESSION_LOG_PREFIX` directly from `os.environ`, not via `cfg`)
- `garmin_security.py::has_unresolved_mfa_block()` — fails open on a read error; `garmin_api.py::login()` blocks headless SSO until a genuine SSO login clears the block (a manual token reset does NOT clear it)

## Normalization / Schema

- `CURRENT_SCHEMA_VERSION = 3` in `garmin_normalizer.py`

## Dashboards / Layouts

- `dash_layout.py` + `dash_layout_html.py` + `reference_ranges.py` — passive resources, no I/O
- `dash_encryptor.py` — sole owner of the HTML encryption logic, Leaf Node
- `dialogs.py` — shared `PasswordConfirmDialog`, imported by `panel_archive` and `panel_outputs`
- The mirror password is never stored in Windows Credential Manager — always entered manually
- `reference_ranges.py` — imported by specialists, never by plotters
- `dash_autosize.py` — auto-size boundary calculation, Leaf Node; `compute_autosize_bounds()` + `autosize_note()`
- `dashboards/custom_dash_builder.py` — builds an in-memory specialist object (`types.ModuleType`) at runtime, deliberately not named `*_dash.py` (so `dash_runner.scan()` doesn't pick it up as a real specialist); `dash_runner.build()` accepts any object with `.META`/`.build()`/`.__name__`
- `app/garmin_dashboard_presets.py` — sole owner of `~/.garmin_dashboard_presets.json`
- `theme.py` — single source of truth for all app/dashboard color tokens; six built-in themes (`_THEMES` dict), active one read from settings (`active_theme` key, GUI dropdown in Settings tab). Falls back to Theme 1 if the key is missing or invalid. `dash_layout.py` and `layouts/render/live.py` both import `theme` directly — the only place `layouts/` breaks its otherwise strict independence from `app/`.

## App Layer / GUI

- `app/panel_chat.py` — Ollama chat panel, uses `clients/ollama_client.py` via a lazy-import helper, never at module level
- Settings tab: two columns — `PanelSettings` on the left (fixed 400px), action panels on the right (flexible)
- `scheduler/daily_update.py` — GUI-free; a `sys.path` root anchor is set before the first project import; every further project import is lazy (after the environment is configured)
- `APP_VERSION` comes from `version.py` — never kept in sync manually elsewhere
- `frozen_paths.py` — sole source for frozen-path resolution (`scripts_root()`, `add_to_path()`, `doc_path()`, `is_t3_standalone()` — v1.7.2.4, `is_t2_standard(reference_file=None)` — v1.7.2.4-Nacherweiterung), Leaf Node in `src/`. Does NOT cover `garmin_app.py`/`garmin_app_standalone.py`'s own `script_dir()`/`script_path()`, nor `dash_runner._load_plotters()` or `dash_plotter_html_complex.py`'s `render/` loader
- `log_utils.py` — domain-less Leaf Node in `src/`; `with_timestamp(log_fn)` prefixes log-callback messages with a timestamp
- `process_status.py` (v1.7.2.4) — sole source for "is process X running" where there's no port to probe (GUI, `daily_update.exe`) via a fixed PID-lock-file under `Path.home()` + `ctypes`/`OpenProcess` liveness check; also the sole `is_mcp_running()` (TCP probe), which `app/panel_mcp.py::_mcp_server_is_running()` delegates to rather than duplicating. Leaf Node in `src/`, with a documented exception (`garmin_config` imported lazily for `MCP_HTTP_PORT` — see `REFERENCE_GARMIN.md § Documented Exceptions`)
- `updater.py` (v1.7.2.4) — sole source for T3 self-update logic (GitHub release asset resolution, download+SHA256-verify+extract). Leaf Node in `src/`, stdlib only, no project imports at all. Fails closed: refuses to apply an update whose release publishes no checksum, rather than applying it unverified
- `export/backfill_source_backup.py` — imports `SETTINGS_FILE` from `garmin_app_settings` instead of hardcoding it independently — the sole source for the settings path in the project

## Build

- `build_manifest.py::HIDDEN_IMPORTS_COMMON`/`HIDDEN_IMPORTS_T3_EXTRA` — single source of truth for PyInstaller hidden imports; T2 = COMMON, T3 = COMMON + T3_EXTRA. `embed_dest(subfolder)` in `build_standalone.py` — the sole source for `--add-data` destination-path logic

## Mirror / Container

- `garmin_import_mirror.py` — sole owner of the mirror-import operation; orchestrates only, never writes directly (raw via `garmin_writer`, context via `context_writer.write_file()`, quality via `_upsert_quality()`); its local `_QUALITY_RANK` copy is deliberate (not imported from `quality/_maint`; must be kept in sync manually if labels change)
- `garmin_container.py` — sole owner of `mirror.gla`
- `normalize()` is never called during mirror import — raw data inside the mirror is already normalized
- Import pauses the background timer (same as Bulk Import)
- Container keys use POSIX forward slashes (`rel.as_posix()`)
- `mirror.gla` is written atomically: `mirror.gla.tmp` → `fsync()` → `os.replace()`
- The password for `lock()` may optionally be stored in Windows Credential Manager (user's choice); the password for `unlock_meta()`/`fulfill_order()` is always entered manually

## Source / Quality / Backup

- `garmin_source_quality.py` — sole owner of source-quality assessment, Leaf Node. Derives `intraday_present` from the raw API response; freeze-when-present strategy (intraday data already present is never overwritten by a degraded response); `assess_source_from_file` distinguishes "absent" from "unreadable"; `compare_source` returns `skip_warn` on unreadable. The `force=True` parameter overrides the whole decision table and forces `"write"` — exclusively for the deliberate Force-Refetch path, never for a normal sync
- `garmin_source_writer.py::write_source()` / `garmin_collector.py::_fetch_and_assess()` — both forward `force: bool = False` through to `compare_source()`; `_fetch_and_assess()`'s `force` cannot be applied separately afterwards, since `write_source()` is called internally
- `garmin_backup.py::backup_raw()` / `garmin_backup_source.py::backup_source()` — `force: bool = False` parameter, forwards `{filename}` as `force_filenames` to `_consolidate_raw_months()`/`_consolidate_source_months()`; the replace scope is always per filename, never per month (prevents collateral damage to other already-good days consolidated in the same monthly archive)

## MCP Server / Proxy

- `clients/mcp_server.py`, `clients/mcp_health.py`, and `clients/mcp_context.py` are the only crossing points between the `clients/` world and the broker layer, via `maps/mcp_map.py` (v1.7.2.1 — `query_health()`/`query_context()` moved into their own files, each calling `mcp_map.query_health()`/`mcp_map.query_context()` on its own live branch) — no exception for internal-only consumers, even ones not registered as a tool
- `mcp_sql.py` is a pure SQLite data-access layer — no validation or bundle-resolution logic; that logic lives in `clients/mcp_health.py`/`clients/mcp_context.py` (v1.7.2.1 — moved out of the `mcp_server.py` wrapper) plus the shared `clients/mcp_query_common.py` helpers
- SQLite is always a derived, reconstructible cache — never written independently, never a fourth data silo. `garmin_backup.py`/`garmin_mirror.py` do not need to know it exists; a lost or corrupt cache file forces a rebuild, not data loss
- `_route_query()` (`clients/mcp_query_common.py`, v1.7.2.1) is the single decision point every query tool passes through before branching into the SQLite or live-broker path
- `FIELD_UNITS` (unit annotations for `query_health()`/`query_context()`/`list_available_fields()`) is deliberately kept local to `clients/mcp_field_registry.py` (v1.7.2.1 — moved out of `mcp_server.py`), not placed in any `maps/` broker — the SQLite branch never reaches `mcp_map.py` today, so a broker-level unit source would currently be unreachable for any real request

---

*This file lists module-level rules only, not the reasoning behind them. See `CHANGELOG.md` for the session-by-session history that produced each rule.*
