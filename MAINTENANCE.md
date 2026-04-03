# Maintenance & Developer Guide

This document is intended for anyone maintaining, extending, or debugging this project — including AI assistants picking up where a previous session left off.

For a complete reference of all environment variables, constants, file paths, and data structures, see `REFERENCE.md`.

---

## Project structure

```
/garmin-local-archive/              – repo root
|-- Garmin_Local_Archive.exe        – standard desktop app (built by build.py)
|-- Garmin_Local_Archive.zip        – standard release package (built by build.py)
|-- Garmin_Local_Archive_Standalone.exe   – standalone desktop app (built by build_standalone.py)
|-- Garmin_Local_Archive_Standalone.zip   – standalone release package
|-- build.py                        – builds Target 2 (Python required on target)
|-- build_standalone.py             – builds Target 3 (no Python required on target)
|-- build_all.py                    – runs both build targets sequentially
|-- build_manifest.py               – single source of truth for all build lists and signatures
|
+-- scripts/                        – all Python scripts
|       garmin_app.py               – desktop GUI entry point (Target 1 dev + Target 2 EXE)
|       garmin_app_standalone.py    – desktop GUI entry point (Target 3 standalone)
|       garmin_utils.py             – shared utilities, no project-module dependencies (v1.2.1b)
|       garmin_config.py            – all ENV variables, constants, and derived paths (v1.2.0)
|       garmin_api.py               – Garmin Connect login, API calls, device list (v1.2.0)
|       garmin_normalizer.py        – normalises raw data from any source (v1.2.0)
|       garmin_quality.py           – sole owner of quality_log.json (v1.2.0)
|       garmin_sync.py              – date range resolution, local date scan (v1.2.0)
|       garmin_import.py            – Garmin GDPR export importer — ZIP or folder (v1.3.0)
|       garmin_collector.py         – thin orchestrator, writes raw/ and summary/ (v1.2.0)
|       garmin_to_excel.py          – exports summary/ to daily overview Excel
|       garmin_timeseries_excel.py  – exports raw/ intraday data to Excel + charts
|       garmin_timeseries_html.py   – exports raw/ intraday data to interactive HTML
|       garmin_analysis_html.py     – analysis dashboard + JSON for Ollama
|       regenerate_summaries.py     – rebuilds summaries from raw without API call
|
+-- info/                           – documentation
|       README.md
|       README_APP.md               – Standard EXE docs (Python required)
|       README_APP_Standalone.md    – Standalone EXE docs (no Python required)
|       MAINTENANCE.md              – this file
|       REFERENCE.md                – all ENV variables, constants, paths, data structures
|
+-- raw/                            – one file per day, full API dump
|       garmin_raw_YYYY-MM-DD.json
|
+-- summary/                        – one file per day, compact summary
|       garmin_YYYY-MM-DD.json
|
\-- log/                            – session logs and quality register
        quality_log.json
        garmin_token.enc
        recent/garmin_YYYY-MM-DD_HHMMSS.log
        fail/garmin_YYYY-MM-DD_HHMMSS.log
```

Both `build.py` and `build_standalone.py` auto-migrate scripts and docs from root to their subfolders if they're still there — safe to run from any starting layout.

---

## Three build targets

| Target | Entry point | Build script | Output | Python on target |
|--------|-------------|--------------|--------|-----------------|
| 1 — Dev | `garmin_app.py` | — (run directly) | — | Required |
| 2 — Standard EXE | `garmin_app.py` | `build.py` | `Garmin_Local_Archive.exe` | Required |
| 3 — Standalone EXE | `garmin_app_standalone.py` | `build_standalone.py` | `Garmin_Local_Archive_Standalone.exe` | Not required |

---

## garmin_app.py (Target 1 + 2)

### Purpose

Desktop GUI built with tkinter. Wraps all scripts so the user never needs a terminal. Target 2 is distributed as a PyInstaller `.exe` — `scripts/` must stay next to it at runtime.

### Key design decisions

**Script execution** — scripts are run as subprocesses via a locally installed `python.exe`. `_find_python()` searches PATH and common Windows install locations. `_build_env()` sets all `GARMIN_*` environment variables before launching the subprocess.

**Configuration** — all config is passed via `os.environ` — no source patching, no temp files. `_build_env()` in `garmin_app.py` builds the full env dict from UI settings.

**Password security** — stored in Windows Credential Manager via `keyring`. Never written to the settings JSON or any temp file. Passed to subprocesses via `GARMIN_PASSWORD` env var only.

**Token persistence** — after the first successful SSO login, `garmin_api.login()` calls `garmin_security.save_token()` to encrypt the Garmin OAuth token with AES-256-GCM and store it at `LOG_DIR/garmin_token.enc`. The encryption key is user-defined (set once via popup on first setup) and stored in Windows Credential Manager under `GarminLocalArchive / token_enc_key`. On all subsequent runs, `login()` loads and decrypts the token — no SSO required (~1 year validity). If the token is rejected by Garmin, `clear_token()` removes it and a warning popup asks the user before triggering a new SSO login. If the WCM key is lost (e.g. after a Windows update), the user re-enters it via popup and the token file is decrypted again. Plaintext token never written to disk.

**Stop button** — only the collector has one. `self._active_proc` holds the subprocess reference. `_stop_collector()` calls `proc.terminate()`, waits 5 s, then `proc.kill()`.

**script_dir()** — returns `exe_folder/scripts/` when frozen (PyInstaller), `Path(__file__).parent` in dev mode.

**`_on_sync_mode_change()`** — callback bound to the Sync Mode combobox. Dims/enables the four sync fields (Days, From, To, Fallback) based on the selected mode. Called on every combobox change and once at startup via `_load_settings_to_ui()` to set the correct initial state.

**`_toggle_log_level()`** — toggles between `INFO` (Simple) and `DEBUG` (Detailed) GUI log display. Updates the button label and colour. If a sync is running when toggled, a yellow hint label appears above the button reading "Takes effect on next sync" — no restart occurs. The hint disappears automatically when the next sync starts. The current level is passed to subprocesses via `GARMIN_LOG_LEVEL` in `_build_env()`. Session log files always run at DEBUG regardless of this toggle.

**`_check_failed_days_popup()`** — called at the start of every `_run_collector()` call. Reads `log/quality_log.json` and counts `failed`+`low` entries with `recheck=true` within the current sync date range. If any are found, shows a German-language popup: "Es gibt fehlerhafte Datensätze: X Tage im gewählten Zeitraum — Aktualisieren?" If the user clicks Ja, `GARMIN_REFRESH_FAILED=1` is set in the ENV and the collector re-fetches those days.

**`_clean_archive()`** — reads `first_day` from `log/quality_log.json` and builds a list of all `raw/` and `summary/` files before that date. Opens a popup with a scrollable file list and a summary count. Deletes files and removes corresponding quality log entries only after the user confirms with "Löschen". Aborts silently on "Abbrechen". If `first_day` is not yet set or nothing is found before it, logs an informational message and returns without opening the popup.

**`_connection_verified`** — session flag, starts `False`. Set to `True` after the first successful connection test. `_run_collector()` skips the test on subsequent calls and starts the sync directly. Resets to `False` on app restart.

**Background Timer** — runs in a daemon thread started by `_toggle_timer()`. Cycles through three modes per run:
- **Repair:** reads `quality_log.json`, draws a random subset (min–max days, configurable) of `failed` days with `recheck=true`, fetches them with `GARMIN_REFRESH_FAILED=1` and `GARMIN_SYNC_DATES`.
- **Quality:** reads `quality_log.json`, draws a random subset of `low` days with `recheck=true`, re-downloads them to check if Garmin now returns better data. After `LOW_QUALITY_MAX_ATTEMPTS` attempts without improvement, the day's `recheck` is set to `false` — Garmin no longer has the detailed data and the day leaves the queue permanently.
- **Fill:** scans `raw/` for dates completely absent from both the filesystem and the quality log — true gaps never downloaded. Fetches them normally.

Cycle order: Repair → Quality → Fill → Repair → ... If a mode's queue is empty it is skipped. If all three queues are empty the timer stops automatically.

**Timer settings** — four fields in the GUI (BACKGROUND TIMER section, right panel), stored in `~/.garmin_archive_settings.json`:

| Setting | Key | Default | Description |
|---|---|---|---|
| Min. Interval (min) | `timer_min_interval` | `5` | Shortest wait between runs |
| Max. Interval (min) | `timer_max_interval` | `30` | Longest wait between runs |
| Min. Tage pro Run | `timer_min_days` | `3` | Fewest days fetched per run |
| Max. Tage pro Run | `timer_max_days` | `10` | Most days fetched per run |

Values are read fresh at the start of each run — changing them while the timer is running takes effect immediately on the next run without restarting.

**Thread safety** — each timer thread carries a `generation` integer. `_timer_generation` is incremented on every Start/Stop. A thread exits immediately if its generation no longer matches (`_stale()` check). This prevents ghost threads from multiple rapid Start/Stop clicks.

**`_timer_conn_verified`** — session flag for the timer's own connection test. On success, also sets `_connection_verified = True` and updates all four GUI indicators (Token, Login, API Access, Data) to green — so a subsequent manual sync also skips its test.

**Timer + manual sync interaction** — `_run_collector()` detects `_timer_active`, pauses the timer (increments generation, sets stop event), runs the manual sync, then resumes via `_timer_resume_after_sync()` in `on_done`. Timer Stop during an active timer sync sets `_stopped_by_user = True` — no false error log.

**Timer + bulk import interaction** — `_run_import()` applies the same pause/resume pattern as `_run_collector()`. The timer is stopped before the import thread starts and resumed via `_timer_resume_after_sync()` in the `finally` block — guaranteed even if the import fails. Without this, the timer and import would write to `raw/` and `summary/` concurrently — the Writer has no own lock, only `QUALITY_LOCK` protects `quality_log.json`.

**Session logs** — background timer syncs write to `log/recent/garmin_background_YYYY-MM-DD_HHMMSS.log`. The `garmin_background_` prefix makes the source immediately identifiable in `log/fail/`.

**`_set_indicator(key, state)`** — updates a connection status dot. States: `"pending"` (orange), `"ok"` (green), `"fail"` (red), `"reset"` (grey).

**`_run_connection_test(on_success=None)`** — runs four sequential checks in a background thread: Token → Login → API Access (`get_user_profile`) → Data (`get_stats` for yesterday). Token check runs first — if the saved token is valid, Login lamp turns green without SSO. `on_success` callback is invoked on the main thread when all checks pass (used by `_run_collector()` to chain directly into the sync). Called automatically on Sync / Background Timer start — not triggered by a button.

**`_refresh_archive_info()`** — reads `quality_log.json` via `garmin_quality.get_archive_stats()` using the path from current Settings (no ENV required). Updates all Archive Info Panel labels on the main thread via `after()`. Called once on startup (`after(200, ...)`) and after every Sync and Bulk Import via `on_done`. Safe to call at any time — silently no-ops on error.

### Settings file

`~/.garmin_archive_settings.json` — all settings except password. Password field is stripped on save and removed on load (migration from older versions that stored it in plaintext).

---

## garmin_app_standalone.py (Target 3)

### Purpose

Identical to `garmin_app.py` with two differences that make it work without a local Python installation.

### Key differences from garmin_app.py

**`_find_python()`** — always returns `sys.executable`. In a PyInstaller standalone EXE, `sys.executable` is the EXE itself, which contains the embedded Python interpreter.

**`script_dir()`** — returns `Path(sys._MEIPASS) / "scripts"`. PyInstaller unpacks `--add-data` files to `sys._MEIPASS` at runtime. Scripts land in `sys._MEIPASS/scripts/`.

**`_run_module()` instead of `_run_script()`** — does not use subprocesses. Scripts are loaded with `importlib.util.spec_from_file_location()` and `main()` is called directly in a background thread. This avoids the problem where `sys.executable` would re-launch the GUI EXE instead of a Python interpreter.

**Output capture** — `sys.stdout`, `sys.stderr`, and the root logger are redirected to a `queue.Queue` via `_QueueWriter` and `_QueueHandler`. A 50ms poll (`_poll_log_queue`) drains the queue and writes lines to the GUI log.

**Stop mechanism** — `self._stop_event` is a `threading.Event`. `_stop_collector()` sets it. `garmin_collector.py` checks `_is_stopped()` at the top of each day loop and inside `api_call()`.

**`_apply_env()`** — writes directly to `os.environ` instead of building a dict. Must run before the module is imported since scripts read `os.environ.get()` at module level.

**`_toggle_log_level()`** — identical to `garmin_app.py`. Hint label shown above button if sync is running. No restart. Session logs unaffected.

**`_check_failed_days_popup()`** — identical to `garmin_app.py`. `refresh_failed` is passed to `_run_module()` which passes it to `_apply_env()`.

**`_connection_verified`** — identical behaviour to `garmin_app.py`. Session flag, skips connection test on subsequent sync starts.

**`_set_indicator()` / `_run_connection_test()`** — identical logic to `garmin_app.py`. In standalone mode log output goes via `self._log_queue` instead of `self.after(0, self._log, ...)` to stay thread-safe with the queue pump.

---

## Collector pipeline (v1.2.0+)

As of v1.2.0, `garmin_collector.py` is a thin orchestrator. The logic that was previously monolithic is now split across six focused modules. This section covers the full pipeline.

### Module overview

| Module | Role | Writes |
|---|---|---|
| `garmin_config.py` | All ENV variables, constants, derived paths | Nothing |
| `garmin_api.py` | Login, API calls, device list | Nothing |
| `garmin_normalizer.py` | Normalises raw dict from any source | Nothing |
| `garmin_quality.py` | Sole owner of `quality_log.json` | `quality_log.json` only |
| `garmin_sync.py` | Date range resolution, local date scan | Nothing |
| `garmin_import.py` | Garmin GDPR export importer — ZIP or folder | Nothing |
| `garmin_collector.py` | Orchestrator | `raw/` and `summary/` only |

**Communication model:** all modules communicate via function calls — parameters in, return value out. No module writes intermediate files for another to read. `main()` is the sole orchestration point; no module calls another directly.

**Central data carrier:** `quality_data` dict — loaded once at startup from `quality_log.json` by `garmin_quality`, passed as parameter through all calls, saved at the end. No other module reads or writes the file directly.

### Pipeline flow

```
main()
  ├── garmin_quality._load_quality_log()       → quality_data dict
  ├── garmin_quality._backfill_quality_log()   → quality_data updated (first run only)
  ├── garmin_quality.get_low_quality_dates()   → new low/failed entries
  ├── garmin_api.login()                       → client
  ├── garmin_api.get_devices()                 → devices list → quality_data["devices"]
  ├── garmin_quality._set_first_day()          → quality_data["first_day"]
  ├── garmin_sync.get_local_dates()            → set of present dates
  ├── garmin_sync.resolve_date_range()         → (start, end)
  ├── for each missing day:
  │     garmin_api.fetch_raw()                 → raw dict
  │     garmin_normalizer.normalize()          → normalised dict
  │     summarize()                            → summary dict
  │     write raw/ and summary/
  │     garmin_quality.assess_quality()        → quality string
  │     garmin_quality._upsert_quality(..., source="api") → quality_data updated
  └── garmin_quality._save_quality_log()       → quality_log.json written
```

### Two-layer data output

Every day produces two files:

- `raw/garmin_raw_YYYY-MM-DD.json` — complete normalised API response (~500 KB). Never modified after creation. Serves as the permanent source of truth.
- `summary/garmin_YYYY-MM-DD.json` — compact distillation (~2 KB). Used by Open WebUI / Ollama as a Knowledge Base. Can always be regenerated from raw without hitting the API again.

### Quality tracking and the quality log

Every raw file downloaded is assessed for content quality immediately after writing. The result is stored in `log/quality_log.json` — a persistent register of every day the collector has ever seen. Sole owner: `garmin_quality.py`.

**Why content-based quality instead of file size:**
Garmin Connect stores intraday detail data for approximately 1–2 years. Older data returns only daily aggregates — valid JSON but far less content than a recent day. File size cannot reliably distinguish between an incomplete download and a legitimately sparse historical record. Content inspection can.

**Quality levels** (`garmin_quality.assess_quality(raw)`):

| Level | Condition | Background Timer |
|---|---|---|
| `high` | Intraday data present — `heart_rates.heartRateValues` or `stress.stressValuesArray` has entries | Never re-downloaded |
| `med` | Daily aggregates present but no intraday — typical for data > ~1 year old | Never re-downloaded |
| `low` | Only minimal stats present — summary-level minimum | Re-tried up to `LOW_QUALITY_MAX_ATTEMPTS` times, then left alone |
| `failed` | API error — no usable data returned | Re-tried indefinitely until successful |

**Migration:** On the first run after upgrading from an older version, `garmin_quality._load_quality_log()` automatically reads the old `failed_days.json`, converts it to the new schema, writes `quality_log.json`, and deletes the old file.

### Session logging

Every sync run opens a new log file at `log/recent/`. The filename prefix is controlled by `GARMIN_SESSION_LOG_PREFIX`:
- Manual syncs: `garmin_YYYY-MM-DD_HHMMSS.log`
- Background timer syncs: `garmin_background_YYYY-MM-DD_HHMMSS.log`

The file handler always runs at `DEBUG` level. After the run:
- If the session had errors or low-quality downloads: the log is additionally copied to `log/fail/`
- `log/recent/` is capped at `LOG_RECENT_MAX` (30) files — oldest are deleted automatically
- `log/fail/` has no automatic limit

### Stop support (standalone mode)

`_is_stopped()` in both `garmin_collector.py` and `garmin_api.py` checks `globals().get("_STOP_EVENT")`. In standalone mode, `garmin_app_standalone.py` injects a `threading.Event` into both module dicts before calling `main()`. In all other modes the key is absent and `_is_stopped()` always returns `False`.

Stop is checked in two places: at the top of the day loop (collector), and at the start of each `api_call()` (api).

### Sync modes

| Mode | Behaviour |
|------|-----------|
| `"recent"` | Checks last `SYNC_DAYS` days (default 90). Good for daily automation. |
| `"range"` | Checks `SYNC_FROM` to `SYNC_TO` only. Good for targeted backfills. |
| `"auto"` | Checks from `first_day` (stored in `quality_log.json`) to today. `first_day` is detected on first run from devices → account profile → `SYNC_AUTO_FALLBACK`. After that, passed directly from `quality_data` — no repeated API calls. |

### Session limit

`MAX_DAYS_PER_SESSION` (default 30, ENV: `GARMIN_MAX_DAYS_PER_SESSION`) caps the number of days fetched per run. Set to `0` for unlimited. Prevents account throttling on large backlogs. Configurable via GUI (Settings → Advanced → Session limit).

### Adding a new API endpoint

In `garmin_api.py`, append a tuple to the `endpoints` list in `fetch_raw()`:
```python
("get_method_name", (date_str,), "key_name"),
```

### Adding a new summary field

In `garmin_collector.py`, add the extraction logic to `summarize()`. The field will appear in all new `summary/garmin_YYYY-MM-DD.json` files. Run `regenerate_summaries.py` to backfill existing files.

### Known Garmin API quirks

- `get_fitnessAge()` does not exist in current `garminconnect` library versions — removed from endpoints list.
- `get_devices()` may return non-dict entries — filtered with `isinstance(d, dict)` check.
- **Stress data** lives in `stress.stressValuesArray` as `[timestamp_ms, value]` pairs. `stressChartValueOffset` may be present — subtract it. Negative results = unmeasured, filtered out.
- **Body Battery** lives in `stress.bodyBatteryValuesArray` as `[timestamp_ms, "MEASURED", level, version]`. Level is at index 2.
- Login may require browser captcha on first run or after long inactivity — run manually in terminal to complete.

---

## test_local.py

### Purpose

Local test script for the core pipeline modules. Runs without network, Garmin API, or GUI. Use it after making changes to any core module to verify nothing is broken before testing with a real sync.

```bash
python test_local.py
```

Exits with code `0` (all passed) or `1` (failures). Cleans up all temporary files after every run — leaves nothing behind.

### What is tested

**1. `garmin_config`** — ENV variable parsing and path derivation
- All derived paths (`RAW_DIR`, `SUMMARY_DIR`, `LOG_DIR`, `QUALITY_LOG_FILE`, `GARMIN_TOKEN_FILE`)
- Default constants (`MAX_DAYS_PER_SESSION`, `LOW_QUALITY_MAX_ATTEMPTS`, `REFRESH_FAILED`)
- `GARMIN_SYNC_DATES` parsing: valid dates accepted, invalid entries skipped, `None` when empty

**2. `garmin_sync`** — date range logic and local file scanning
- All three sync modes: `recent`, `range`, `auto` — correct start/end dates
- `date_range()` generator: correct count, first and last date
- `get_local_dates()`: finds files, excludes recheck dates when `REFRESH_FAILED=1`

**3. `garmin_normalizer`** — data normalisation and summary extraction
- `normalize()`: API source passes through with date guaranteed, non-dict returns `{"date": "unknown"}`, bulk and unknown sources handled
- `safe_get()`: nested hit, missing key, default value, non-dict mid-path
- `_parse_list_values()`: dict list and `[timestamp, value]` pair formats
- `summarize()`: all top-level keys present, `generated_by = "garmin_normalizer.py"`, correct values from dummy data (sleep hours, resting HR, steps, activity type)

**4. `garmin_quality`** — quality assessment, upsert logic, persistence, migrations, thread safety
- `assess_quality()`: all four levels — `high` (intraday HR), `medium` (daily aggregate), `low` (bare stats), `failed` (empty)
- `_upsert_quality()`: new entry, update existing, `write` field stored correctly, `recheck` and `attempts` logic for each quality level, `source` field stored and overwritten on update
- `LOW_QUALITY_MAX_ATTEMPTS` exhaustion: `recheck` disabled after 3 attempts
- Save + load round-trip: `first_day`, entries, `write` field all preserved
- Migration `"med"` → `"medium"`: old entries upgraded on load
- Migration `write=null`: pre-v1.2.0 entries without `write` field get `null` on load
- Migration `source=legacy`: pre-v1.2.2 entries without `source` field get `"legacy"` on load
- Migration `fields={}`: pre-v1.3.0 entries without `fields` dict get `{}` on load
- `assess_quality_fields()`: high/medium/failed per endpoint, `fields` stored via `_upsert_quality(fields=...)`
- `QUALITY_LOCK`: exists, correct type, blocks a second thread while held

**5. `garmin_writer`** — file output
- `write_day()` creates both `raw/garmin_raw_YYYY-MM-DD.json` and `summary/garmin_YYYY-MM-DD.json`
- Raw file content correct, summary `generated_by` field = `"garmin_normalizer.py"`, `schema_version` = `1`

**6. `garmin_collector` internals** — decision layer and module boundaries
- `_should_write()`: `True` for `high`/`medium`/`low`, `False` for `failed` and unknown labels
- `_is_stopped()`: `False` without injected event, `True` when `_STOP_EVENT` is set
- `summarize` and `safe_get` no longer present in collector (moved to normalizer)
- `_process_day()` via mocked API: correct label returned, `write_day` called on success, not called when label is `failed`, `fields` dict returned as third element

**7. `garmin_security`** — crypto layer (no keyring required)
- `_derive_aes_key()`: 32-byte output, deterministic for same salt+key, unique per different key
- `save_token()` + `load_token()` round-trip: correct plaintext recovered with random salt
- `load_token()` with wrong key: returns `None`
- `load_token()` with no enc_key: returns `None`
- `clear_token()`: token file removed from disk
- `load_token()` after clear: returns `None`

**8. `garmin_utils`** — shared utilities
- `parse_device_date()`: ISO string, ISO date, millisecond timestamp, second timestamp, `None`, empty string
- `parse_sync_dates()`: valid dates, sorted output, invalid entries skipped, empty → `None`, all invalid → `None`

### Total: 136 checks

### What is not tested

- GUI (tkinter) — verified manually before release
- `garmin_api` — requires live Garmin Connect credentials
- `garmin_import` — `load_bulk()` / `parse_day()` with real ZIP data (requires actual Garmin export)
- `garmin_app.py` / `garmin_app_standalone.py` — GUI entry points
- Export scripts (`garmin_to_excel.py`, `garmin_timeseries_*.py`, `garmin_analysis_html.py`)
- Full end-to-end pipeline with real API data

### When to run

- After any change to `garmin_config`, `garmin_sync`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`, `garmin_collector`, `garmin_security`, or `garmin_utils`
- After upgrading Python or dependencies
- Before building a release EXE

---

## garmin_to_excel.py

### Purpose

Reads all `summary/garmin_YYYY-MM-DD.json` files and produces a formatted daily overview Excel file.

### Structure

- Sheet 1 **Garmin Daily Overview** — one row per day, columns toggled via `FIELDS` dict.
- Sheet 2 **Activities** — one row per activity entry (optional, `EXPORT_ACTIVITIES_SHEET`).

### Adding a new column

1. Ensure the field exists in the summary JSON (add to `summarize()` in collector if not).
2. Add entry to `FIELDS` dict: `"section.field_name": True`.
3. Add human-readable label to `LABELS` dict.

### Configuration variables

| Variable | Description |
|----------|-------------|
| `SUMMARY_DIR` | Path to `summary/` folder |
| `OUTPUT_FILE` | Output `.xlsx` path |
| `DATE_FROM` / `DATE_TO` | Date filter; `None` exports everything |
| `FIELDS` | Dict of `"section.field": True/False` |
| `EXPORT_ACTIVITIES_SHEET` | Whether to include the activities sheet |

---

## garmin_timeseries_excel.py

### Purpose

Reads `raw/garmin_raw_YYYY-MM-DD.json` files and exports full intraday measurement points to Excel. Per metric: one data table sheet + one line chart sheet.

### Metrics and extractors

| Metric key | Extractor function | Source field in raw JSON |
|---|---|---|
| `heart_rate` | `extract_heart_rate()` | `heart_rates.heartRateValues` |
| `stress` | `extract_stress()` | `stress.stressValuesArray` |
| `spo2` | `extract_spo2()` | `spo2.spO2HourlyAverages` or `continuousReadingDTOList` |
| `body_battery` | `extract_body_battery()` | `stress.bodyBatteryValuesArray` |
| `respiration` | `extract_respiration()` | `respiration.respirationValuesArray` |

### Adding a new metric

1. Write an extractor function returning `list of (date_str, time_str, value)`.
2. Add to `EXTRACTORS` dict.
3. Add display name and unit to `METRIC_LABELS`.
4. Add fill colour to `METRIC_COLORS`, chart colour to `CHART_COLORS`.
5. Add `True` entry to `METRICS` config block.

> Excel becomes slow with many data points. For ranges longer than ~30 days, use the HTML dashboard instead.

---

## garmin_timeseries_html.py

### Purpose

Reads `raw/garmin_raw_YYYY-MM-DD.json` files and generates a self-contained interactive HTML file using Plotly. One tab per metric, fully zoomable, range selector and drag-to-zoom. Works offline after first load.

### Data flow

```
raw JSON files
    → load_raw_files()         – loads files within date range
    → EXTRACTORS[metric](raw)  – per-metric extraction (same logic as Excel script)
    → build_html(metric_data)  – generates complete HTML string with embedded JS data
    → write to OUTPUT_FILE
```

### Adding a new metric

Same steps as for the Excel script. Additionally update `METRIC_META` with label, unit, and hex colour for the chart line.

---

## garmin_analysis_html.py

### Purpose

Reads `summary/garmin_YYYY-MM-DD.json` files and generates:

- `garmin_analysis.html` — interactive dashboard: daily value + 90-day personal baseline + age/fitness reference range band per metric
- `garmin_analysis.json` — compact summary for Ollama / Open WebUI with flagged days

### How it works

```
summary JSONs
    → load_summaries()              – loads display range + extra days for baseline
    → auto-detect VO2max            – scans most recent non-null training.vo2max
    → get_reference_ranges()        – builds age/sex/fitness norm bands
    → analyse()                     – computes daily values, baselines, flags
    → build_html()                  – generates Plotly dashboard
    → build_ollama_summary()        – generates compact JSON for AI context
```

### Reference range sources

| Metric | Source | Notes |
|--------|--------|-------|
| HRV | Shaffer & Ginsberg 2017, Garmin whitepaper | Age + sex + fitness adjusted |
| Resting HR | AHA guidelines | Fitness adjusted |
| SpO2 | WHO, AHA | Fixed range 95–100% |
| Sleep | National Sleep Foundation 2023 | Age adjusted |
| Body Battery | Garmin guidance | No external norm; >50 = adequate |
| Stress | Garmin scale | 0–50 = low/rest; >50 = elevated |

### Adding a new metric

1. Add the summary key to `METRIC_KEYS` dict.
2. Add display name and chart colour to `METRIC_META`.
3. Add reference range logic to `get_reference_ranges()`.
4. Set `higher_better` appropriately (`True`, `False`, or `None` for range).

### Configuration variables

| Variable | Description |
|----------|-------------|
| `SUMMARY_DIR` | Path to `summary/` folder |
| `OUTPUT_HTML` | Output `.html` path |
| `OUTPUT_JSON` | Output `.json` path for Ollama |
| `DATE_FROM` | Start date (`"YYYY-MM-DD"`) |
| `DATE_TO` | End date (`"YYYY-MM-DD"`) |
| `PROFILE` | Dict with `age` (int) and `sex` (`"male"`/`"female"`) |
| `BASELINE_DAYS` | Rolling average window (default 90) |

---

## Common maintenance tasks

### Re-generating summaries from raw data (no API call needed)

```bash
python regenerate_summaries.py
```

Run this whenever `summarize()` in `garmin_collector.py` is updated.

### Re-fetching a specific day

Delete `raw/garmin_raw_YYYY-MM-DD.json` (and `summary/garmin_YYYY-MM-DD.json` if it exists), then run the collector — it re-fetches automatically.

### Inspecting failed days

Open `log/quality_log.json` in any text editor or JSON viewer. The file lists all known days with their quality level, recheck flag, and attempt count. To force a re-fetch, start a sync and click "Ja" in the popup, or manually delete the raw file for that day.

`first_day` and `devices` are stored as root fields at the top of the file.

### Inspecting session logs

`log/recent/` contains the last 30 sync sessions at full DEBUG detail. `log/fail/` contains all sessions that had errors or incomplete days — these are never deleted automatically.

### Rate limiting

If Garmin throttles requests: increase `REQUEST_DELAY_MIN` and `REQUEST_DELAY_MAX` in Settings (GUI fields "Delay min (s)" / "Delay max (s)"). Default is `1.0`–`3.0s` random per call.

### Login / captcha issues

Garmin may require browser-based MFA on first run or after long inactivity. Run `garmin_collector.py` manually in a terminal and follow any prompts. After that the GUI versions work normally.

### Older devices (Vivosmart 3, Fenix 5)

Many fields return `null` — expected behaviour. Use `SYNC_AUTO_FALLBACK = "2018-06-01"` with `SYNC_MODE = "auto"` to control how far back to go.

### Removing the stored password

Open **Windows Credential Manager** → **Windows Credentials** → find `GarminLocalArchive` → delete.

### Clean uninstall

Deleting the app folder is not enough — two items remain on your system:

1. **Stored password** — Windows Credential Manager → Windows Credentials → find `GarminLocalArchive` → delete
2. **Settings file** — delete `C:\Users\YourName\.garmin_archive_settings.json`

Your data folder (`garmin_data/` or wherever you configured it) is never touched automatically — delete it manually if you no longer want the archived data.

### Pylance / VS Code import warning

The `garminconnect` import warning is cosmetic. Click the interpreter selector (bottom right in VS Code) and match it to `where python` in the terminal.

### Building a new release

**Target 2 — Standard EXE (Python required):**

```bash
python build.py
```

Produces `Garmin_Local_Archive.exe` and `Garmin_Local_Archive.zip`.

**Target 3 — Standalone EXE (no Python required):**

```bash
python build_standalone.py
```

Produces `Garmin_Local_Archive_Standalone.exe` and `Garmin_Local_Archive_Standalone.zip`.

Both scripts auto-migrate files to the correct subfolders if still in root. Safe to run from any starting layout. Upload both ZIPs to the GitHub release page.

**Pre-build validation (`validate_scripts()`):**

Both build scripts run a validation block before PyInstaller starts. It checks:

1. Every required script is present in `scripts/`
2. Key scripts contain their expected function or class signatures

| Script | Required signatures |
|---|---|
| `garmin_app.py` | `class GarminApp` |
| `garmin_app_standalone.py` | `class GarminApp` |
| `garmin_api.py` | `def login`, `def fetch_raw` |
| `garmin_collector.py` | `def main`, `def _process_day`, `def run_import` |
| `garmin_import.py` | `def load_bulk`, `def parse_day` |
| `garmin_quality.py` | `def _upsert_quality` |
| `garmin_config.py` | `GARMIN_EMAIL` |
| `garmin_security.py` | `def load_token`, `def save_token` |
| `garmin_normalizer.py` | `def normalize`, `def summarize` |
| `garmin_writer.py` | `def write_day` |
| `garmin_sync.py` | `def get_local_dates`, `def resolve_date_range` |

If any check fails, the build aborts immediately with a clear message identifying which file is missing or has wrong content. This catches cases where a file was accidentally replaced with the wrong content or never copied into the folder.

The signature list is defined in `build_manifest.py` as `SCRIPT_SIGNATURES_BASE` — update it there whenever a module's public interface changes. Both build scripts import from it automatically.

**Adding a new module:**

Add the filename to `SHARED_SCRIPTS` in `build_manifest.py`. Both builds pick it up automatically. No changes needed in `build.py` or `build_standalone.py`.

### Adding a missing hidden import to the standalone build

If the standalone EXE fails with an `ImportError` or `ModuleNotFoundError`, add the missing module name to the `hidden` list in `build_exe()` inside `build_standalone.py`, then rebuild.

---

## Session workflow

This project is built collaboratively with AI assistants (Claude as primary coding partner). The following workflow is established practice — document it here so any future session can pick it up immediately.

### Notes file

At the start of every version session, create a `NOTES_vX_Y_Z.md` file. Write to it after every delivered change — not at the end. This file is the working log for the session and the primary input for documentation closure.

**Minimum structure:**

```markdown

# Session Notes — vX.Y.Z

## Bugs / Priority — done
- [x] Short description

- What changed, which files, why

## Features — done
- [x] Short description

- What changed, which files

## Decisions (not implemented)

- [→] What was considered

- Why it was NOT done — reasoning preserved for future sessions

## Test results
| Status | Result |

|---|---|

| After change X | N/N ✅ |

## Changes to test_local.py

- What was added/changed and why
```

**Rules:**
- Write every entry immediately after delivering the change — not from memory at the end
- Document *why something was NOT done* — this is the part that gets lost without notes
- Notes are the input for CHANGELOG, ROADMAP, REFERENCE, MAINTENANCE updates at session end
- Notes are the input for the next `START_PROMPT_vX_Y_Z.md`

### Before every implementation — cross-dependency check

For every planned change, explicitly ask:

> **"Which modules, dialogs, or documentation sections implicitly assume the old behaviour — and which will be affected by the new behaviour?"**

- What assumes the *old* behaviour? → breaks silently after the change
- What is affected by the *new* behaviour? → must be explicitly updated
- For every new behaviour explicitly ask: **"Which other threads access the same resource?"**

Examples from practice:
- Random salt introduced → recovery dialog still implied "re-enter key = restore token" → had to be corrected
- `fetch_raw()` returns tuple → `test_local.py` mocks still returned a single dict → tests failed

### Closing checklist — before documentation closure

**Code:**
- [ ] All new modules in `build_manifest.py` (`SHARED_SCRIPTS`)?
- [ ] All new modules in README script table?
- [ ] All new modules in REFERENCE (own section)?
- [ ] All new modules in MAINTENANCE (project structure + "When to run")?

**Documentation:**
- [ ] All new ENV variables in REFERENCE?
- [ ] All changed function signatures in REFERENCE?
- [ ] Test count updated in MAINTENANCE + ROADMAP?
- [ ] Stale "planned for vX.Y.Z" references removed?
- [ ] GUI text in README_APP + README_APP_Standalone current?
- [ ] Version number in README updated?

### Documentation closure order

CHANGELOG → ROADMAP → REFERENCE → MAINTENANCE → README → README_APP → README_APP_Standalone → PATCHNOTES → START_PROMPT for next session

## Development Process (Human-AI Collaboration)

This project follows a rigorous, engineering-inspired collaboration process between the author and various AI models to ensure architectural stability and data integrity.

![Human-AI Collaboration Flowchart](screenshots/flowchart.png)

> [!TIP]
> **Interactive Version:** For a deep dive including detailed tooltips for every step, open the local [flowchart.html](info/flowchart.html) in your browser.
