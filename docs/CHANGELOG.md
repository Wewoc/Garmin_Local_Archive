# Garmin Local Archive — Changelog

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
- `import garmin_config as cfg` auf Modulebene entfernt — `cfg` wurde beim ersten
  Import eingefroren und ignorierte spätere `importlib.reload(cfg)` Aufrufe aus der GUI.
- Alle vier Funktionen die `cfg` nutzen (`_clear_token_dir`, `save_token`,
  `load_token`, `clear_token`) lesen `cfg` jetzt lazy per lokalem Import beim
  Funktionsaufruf — immer aktueller Stand nach Reload.

**`garmin_app.py` / `garmin_app_standalone.py`:**
- Token-Indikator nach Login: Zustand wird jetzt nach dem Login vom tatsächlichen
  Disk-Zustand abgelesen (`cfg.GARMIN_TOKEN_FILE.exists()`) statt vom
  Pre-Login-Boolean — Indikator zeigt nach SSO korrekt grün.

**Diagnosis path:** Live-Log + Windows Credential Manager check → Multi-LLM review
(Gemini, Copilot, Le Chat) → Schnittmenge: lazy cfg in `garmin_security.py` ist
der richtige Fix, nicht `importlib.reload(garmin_security)` in der GUI.

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

Drei Pfad-Bugs in der Standalone EXE behoben — gemeldet durch User-Feedback.

**`garmin_app_standalone.py`:**
- `script_path()` — Unterordner-Suche (`garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/`, `export/`) läuft jetzt in beiden Modi (Dev + Frozen) über `script_dir()` als Basis. Im Frozen-Modus wurde zuvor der Unterordner ignoriert, was zu `Script not found: …/scripts/garmin_collector.py` führte.
- Context-Collector: `_root` im Frozen-Modus korrigiert von `_MEIPASS` auf `_MEIPASS/scripts/` — `context/` liegt unter `scripts/context/`, nicht direkt unter `_MEIPASS`.

**`build_standalone.py`:**
- `garmin_dataformat.json` Einpack-Ziel korrigiert von `scripts` auf `scripts/garmin` — `garmin_config.py` sucht die Datei via `Path(__file__).parent`, was im Frozen-Modus `scripts/garmin/` ergibt.

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
