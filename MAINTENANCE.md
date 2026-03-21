# Maintenance & Developer Guide

This document is intended for anyone maintaining, extending, or debugging this project — including AI assistants picking up where a previous session left off.

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
|
+-- scripts/                        – all Python scripts
|       garmin_app.py               – desktop GUI entry point (Target 1 dev + Target 2 EXE)
|       garmin_app_standalone.py    – desktop GUI entry point (Target 3 standalone)
|       garmin_collector.py         – fetches + archives data from Garmin Connect
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
|
+-- raw/                            – one file per day, full API dump
|       garmin_raw_YYYY-MM-DD.json
|
\-- summary/                        – one file per day, compact summary
        garmin_YYYY-MM-DD.json
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

**Script execution** — scripts are run as subprocesses via a locally installed `python.exe`. `_find_python()` searches PATH and common Windows install locations. `_build_env()` sets all 18 `GARMIN_*` environment variables before launching the subprocess.

**Configuration** — all config is passed via `os.environ` — no source patching, no temp files. `_build_env()` in `garmin_app.py` builds the full env dict from UI settings.

**Password security** — stored in Windows Credential Manager via `keyring`. Never written to the settings JSON or any temp file. Passed to subprocesses via `GARMIN_PASSWORD` env var only.

**Stop button** — only the collector has one. `self._active_proc` holds the subprocess reference. `_stop_collector()` calls `proc.terminate()`, waits 5 s, then `proc.kill()`.

**script_dir()** — returns `exe_folder/scripts/` when frozen (PyInstaller), `Path(__file__).parent` in dev mode.

**`_on_sync_mode_change()`** — callback bound to the Sync Mode combobox. Dims/enables the four sync fields (Days, From, To, Fallback) based on the selected mode. Called on every combobox change and once at startup via `_load_settings_to_ui()` to set the correct initial state.

**`_toggle_log_level()`** — toggles between `INFO` (Simple) and `DEBUG` (Detailed) log output. Updates the button label and colour. Current level is passed to subprocesses via `GARMIN_LOG_LEVEL` ENV variable in `_build_env()`. If a sync is running when toggled, the subprocess is terminated and `_run_collector()` is called again after 500ms — already saved days are skipped automatically.

**`_connection_verified`** — session flag, starts `False`. Set to `True` after the first successful connection test. `_run_collector()` skips the test on subsequent calls and starts the sync directly. Resets to `False` on app restart.

**`_set_indicator(key, state)`** — updates a connection status dot. States: `"pending"` (orange), `"ok"` (green), `"fail"` (red), `"reset"` (grey).

**`_run_connection_test()`** — runs three sequential checks in a background thread: Login → API Access (`get_user_profile`) → Data (`get_stats` for yesterday). Each indicator updates live as checks complete. Button turns green on full success, red on first failure. Stops immediately on failure — no point testing further if login fails.

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

**`_on_sync_mode_change()`** — identical to `garmin_app.py`. Dims/enables sync fields based on selected mode.

**`_toggle_log_level()`** — identical to `garmin_app.py`. In standalone mode the level is applied directly to the root logger in `_run_module()` via `getattr(logging, self._log_level)`. Also written to `os.environ["GARMIN_LOG_LEVEL"]` via `_apply_env()`. If a sync is running, `_stop_event` is set and `_run_collector()` is called after 1000ms.

**`_connection_verified`** — identical behaviour to `garmin_app.py`. Session flag, skips connection test on subsequent sync starts.

**`_set_indicator()` / `_run_connection_test()`** — identical logic to `garmin_app.py`. In standalone mode log output goes via `self._log_queue` instead of `self.after(0, self._log, ...)` to stay thread-safe with the queue pump.

---

## garmin_collector.py

### Purpose

Connects to Garmin Connect, determines which days are missing locally, and downloads them. Runs unattended via Task Scheduler / cron after initial setup.

### Two-layer design

Every day produces two files:

- `raw/garmin_raw_YYYY-MM-DD.json` — complete API response for all endpoints (~500 KB). Never modified after creation. Serves as the permanent source of truth.
- `summary/garmin_YYYY-MM-DD.json` — compact distillation (~2 KB). Used by Open WebUI / Ollama as a Knowledge Base. Can always be regenerated from raw without hitting the API again.

### Stop support (standalone mode)

`_is_stopped()` checks `globals().get("_STOP_EVENT")`. In standalone mode, `garmin_app_standalone.py` injects a `threading.Event` into the module dict before calling `main()`. In all other modes the key is absent and `_is_stopped()` always returns `False` — no effect on Target 1 or 2.

Stop is checked in two places: at the top of the day loop, and at the start of each `api_call()`.

### Sync modes

| Mode | Behaviour |
|------|-----------|
| `"recent"` | Checks last `SYNC_DAYS` days (default 90). Good for daily automation. |
| `"range"` | Checks `SYNC_FROM` to `SYNC_TO` only. Good for targeted backfills. |
| `"auto"` | Checks from oldest registered device to today. Full historical sync. |

### Key functions

`fetch_raw(client, date_str)` — calls all Garmin API endpoints for a given date. To add a new endpoint, append a tuple `("method_name", (args,), "key_name")` to the `endpoints` list.

`summarize(raw)` — extracts fields from raw into compact summary. To expose a new field in Open WebUI, add it here.

`get_devices(client)` — fetches registered devices, logs first/last use dates. Used by `resolve_date_range()` in auto mode.

`resolve_date_range(client)` — returns `(start, end)` based on `SYNC_MODE`. Auto mode: tries devices → account profile → `SYNC_AUTO_FALLBACK` → 90-day fallback.

`get_local_dates(folder)` — scans across three locations and naming schemes (raw schema, summary schema, legacy flat schema) for robustness.

### Configuration variables

| Variable | Type | Description |
|----------|------|-------------|
| `GARMIN_EMAIL` | str | Garmin Connect login email |
| `GARMIN_PASSWORD` | str | Garmin Connect password |
| `BASE_DIR` | Path | Root folder; `raw/` and `summary/` live here |
| `SYNC_MODE` | str | `"recent"`, `"range"`, or `"auto"` |
| `SYNC_DAYS` | int | Days to check in `"recent"` mode (default 90) |
| `SYNC_FROM` | str | Start date for `"range"` mode (`"YYYY-MM-DD"`) |
| `SYNC_TO` | str | End date for `"range"` mode (`"YYYY-MM-DD"`) |
| `SYNC_AUTO_FALLBACK` | str/None | Manual start date fallback for `"auto"` mode |
| `REQUEST_DELAY` | float | Seconds between API calls (default 1.5) |
| `GARMIN_LOG_LEVEL` | str | `"INFO"` (default) or `"DEBUG"` — set by app log toggle |

### Known Garmin API quirks

- `get_fitnessAge()` does not exist in current `garminconnect` library versions — removed from endpoints list.
- `get_devices()` may return non-dict entries — filtered with `isinstance(d, dict)` check.
- **Stress data** lives in `stress.stressValuesArray` as `[timestamp_ms, value]` pairs. `stressChartValueOffset` may be present — subtract it. Negative results = unmeasured, filtered out.
- **Body Battery** lives in `stress.bodyBatteryValuesArray` as `[timestamp_ms, "MEASURED", level, version]`. Level is at index 2.
- Login may require browser captcha on first run or after long inactivity — run manually in terminal to complete.

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

### Rate limiting

If Garmin throttles requests: increase `REQUEST_DELAY` from `1.5` to `3.0`.

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

### Adding a missing hidden import to the standalone build

If the standalone EXE fails with an `ImportError` or `ModuleNotFoundError`, add the missing module name to the `hidden` list in `build_exe()` inside `build_standalone.py`, then rebuild.
