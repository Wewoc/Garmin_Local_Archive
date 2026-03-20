# Maintenance & Developer Guide

This document is intended for anyone maintaining, extending, or debugging this project — including AI assistants picking up where a previous session left off.

---

## Project structure

```
/garmin_collector/              – repo root
|-- GarminArchive.exe           – desktop app (built by build.py)
|-- GarminArchive.zip           – release package (built by build.py)
|-- build.py                    – builds the .exe and .zip
|
+-- scripts/                    – all Python scripts
|       garmin_app.py           – desktop GUI (tkinter)
|       garmin_collector.py     – fetches + archives data from Garmin Connect
|       garmin_to_excel.py      – exports summary/ to daily overview Excel
|       garmin_timeseries_excel.py  – exports raw/ intraday data to Excel + charts
|       garmin_timeseries_html.py   – exports raw/ intraday data to interactive HTML
|       garmin_analysis_html.py     – analysis dashboard + JSON for Ollama
|       regenerate_summaries.py     – rebuilds summaries from raw without API call
|
+-- info/                       – documentation
|       README.md
|       README_APP.md
|       MAINTENANCE.md          – this file
|       SETUP.md
|
+-- raw/                        – one file per day, full API dump
|       garmin_raw_YYYY-MM-DD.json
|
\-- summary/                    – one file per day, compact summary
        garmin_YYYY-MM-DD.json
```

`build.py` auto-migrates scripts and docs from root to their subfolders if they're still there — safe to run repeatedly.

---

## garmin_app.py

### Purpose

Desktop GUI built with tkinter. Wraps all scripts so the user never needs a terminal. Distributed as a PyInstaller `.exe`.

### Key design decisions

**Script execution** — the app does not import scripts as modules. Instead it patches config values directly into a temp copy (`_tmp_garmin_*.py`) and runs it as a subprocess via `python.exe`. This avoids import conflicts and makes each script independently runnable.

**Password security** — the password is stored in the Windows Credential Manager via the `keyring` library. It is never written to the settings JSON file or any temp file — it is passed exclusively via the `GARMIN_PASSWORD` environment variable, which is only visible to the child process.

**Stop button** — only the collector has a stop button (it's the only long-running process). `self._active_proc` holds the current subprocess reference. `_stop_collector()` calls `proc.terminate()`, waits 5 seconds, then `proc.kill()` as fallback.

**script_dir()** — returns `exe_folder/scripts/` when frozen, `Path(__file__).parent` in dev mode.

### Keyring helpers

```python
KEYRING_SERVICE = "GarminLocalArchive"
KEYRING_USER    = "garmin_password"
```

`load_password()` / `save_password()` / `delete_password()` — all wrapped in try/except so the app works even if keyring is unavailable (falls back to empty string).

### Settings file

`~/.garmin_archive_settings.json` — all settings except password. Password field is stripped on save and removed on load (migration from older versions that stored it in plaintext).

### _patch_and_run(script_name, patches, enable_stop=False)

Reads the script, applies string replacements from `patches` dict, writes `_tmp_{script_name}` to `scripts/`, runs it as a subprocess. `enable_stop=True` activates the stop button and stores `proc` in `self._active_proc`. Temp file is deleted on success, kept on failure for inspection.

---

## garmin_collector.py

### Purpose

Connects to Garmin Connect, determines which days are missing locally, and downloads them. Runs unattended via Task Scheduler / cron after initial setup.

### Two-layer design

Every day produces two files:

- `raw/garmin_raw_YYYY-MM-DD.json` — complete API response for all endpoints (~500 KB). Never modified after creation. Serves as the permanent source of truth.
- `summary/garmin_YYYY-MM-DD.json` — compact distillation (~2 KB). Used by Open WebUI / Ollama as a Knowledge Base. Can always be regenerated from raw without hitting the API again.

### Sync modes

| Mode       | Behaviour                                                             |
|------------|-----------------------------------------------------------------------|
| `"recent"` | Checks last `SYNC_DAYS` days (default 90). Good for daily automation. |
| `"range"`  | Checks `SYNC_FROM` to `SYNC_TO` only. Good for targeted backfills.   |
| `"auto"`   | Checks from oldest registered device to today. Full historical sync.  |

### Key functions

`fetch_raw(client, date_str)` — calls all Garmin API endpoints for a given date. To add a new endpoint, append a tuple `("method_name", (args,), "key_name")` to the `endpoints` list.

`summarize(raw)` — extracts fields from raw into compact summary. To expose a new field in Open WebUI, add it here.

`get_devices(client)` — fetches registered devices, logs first/last use dates. Used by `resolve_date_range()` in auto mode.

`resolve_date_range(client)` — returns `(start, end)` based on `SYNC_MODE`. Auto mode: tries devices → account profile → `SYNC_AUTO_FALLBACK` → 90-day fallback.

`get_local_dates(folder)` — scans across three locations and naming schemes (raw schema, summary schema, legacy flat schema) for robustness.

### Configuration variables

| Variable             | Type      | Description                                                      |
|----------------------|-----------|------------------------------------------------------------------|
| `GARMIN_EMAIL`       | str       | Garmin Connect login email                                       |
| `GARMIN_PASSWORD`    | str       | Garmin Connect password (env var `GARMIN_PASSWORD` when via GUI) |
| `BASE_DIR`           | Path      | Root folder; `raw/` and `summary/` live here                     |
| `SYNC_MODE`          | str       | `"recent"`, `"range"`, or `"auto"`                               |
| `SYNC_DAYS`          | int       | Days to check in `"recent"` mode (default 90)                    |
| `SYNC_FROM`          | str       | Start date for `"range"` mode (`"YYYY-MM-DD"`)                   |
| `SYNC_TO`            | str       | End date for `"range"` mode (`"YYYY-MM-DD"`)                     |
| `SYNC_AUTO_FALLBACK` | str/None  | Manual start date fallback for `"auto"` mode                     |
| `REQUEST_DELAY`      | float     | Seconds between API calls (default 1.5)                          |

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

| Variable                  | Description                                    |
|---------------------------|------------------------------------------------|
| `SUMMARY_DIR`             | Path to `summary/` folder                      |
| `OUTPUT_FILE`             | Output `.xlsx` path                            |
| `DATE_FROM` / `DATE_TO`   | Date filter; `None` exports everything         |
| `FIELDS`                  | Dict of `"section.field": True/False`          |
| `EXPORT_ACTIVITIES_SHEET` | Whether to include the activities sheet        |

---

## garmin_timeseries_excel.py

### Purpose

Reads `raw/garmin_raw_YYYY-MM-DD.json` files and exports full intraday measurement points to Excel. Per metric: one data table sheet + one line chart sheet.

### Metrics and extractors

| Metric key     | Extractor function       | Source field in raw JSON                              |
|----------------|--------------------------|-------------------------------------------------------|
| `heart_rate`   | `extract_heart_rate()`   | `heart_rates.heartRateValues`                         |
| `stress`       | `extract_stress()`       | `stress.stressValuesArray`                            |
| `spo2`         | `extract_spo2()`         | `spo2.spO2HourlyAverages` or `continuousReadingDTOList` |
| `body_battery` | `extract_body_battery()` | `stress.bodyBatteryValuesArray`                       |
| `respiration`  | `extract_respiration()`  | `respiration.respirationValuesArray`                  |

### Adding a new metric

1. Write an extractor function returning `list of (date_str, time_str, value)`.
2. Add to `EXTRACTORS` dict.
3. Add display name and unit to `METRIC_LABELS`.
4. Add fill colour to `METRIC_COLORS`, chart colour to `CHART_COLORS`.
5. Add `True` entry to `METRICS` config block.

### Configuration variables

| Variable      | Description                              |
|---------------|------------------------------------------|
| `RAW_DIR`     | Path to `raw/` folder                    |
| `OUTPUT_FILE` | Output `.xlsx` path                      |
| `DATE_FROM`   | Start date (required, `"YYYY-MM-DD"`)    |
| `DATE_TO`     | End date (required, `"YYYY-MM-DD"`)      |
| `METRICS`     | Dict of metric keys to `True`/`False`    |

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

### Configuration variables

| Variable      | Description                              |
|---------------|------------------------------------------|
| `RAW_DIR`     | Path to `raw/` folder                    |
| `OUTPUT_FILE` | Output `.html` path                      |
| `DATE_FROM`   | Start date (required, `"YYYY-MM-DD"`)    |
| `DATE_TO`     | End date (required, `"YYYY-MM-DD"`)      |
| `METRICS`     | Dict of metric keys to `True`/`False`    |

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

| Metric       | Source                                     | Notes                            |
|--------------|--------------------------------------------|----------------------------------|
| HRV          | Shaffer & Ginsberg 2017, Garmin whitepaper | Age + sex + fitness adjusted     |
| Resting HR   | AHA guidelines                             | Fitness adjusted                 |
| SpO2         | WHO, AHA                                   | Fixed range 95–100%              |
| Sleep        | National Sleep Foundation 2023             | Age adjusted                     |
| Body Battery | Garmin guidance                            | No external norm; >50 = adequate |
| Stress       | Garmin scale                               | 0–50 = low/rest; >50 = elevated  |

### Adding a new metric

1. Add the summary key to `METRIC_KEYS` dict.
2. Add display name and chart colour to `METRIC_META`.
3. Add reference range logic to `get_reference_ranges()`.
4. Set `higher_better` appropriately (`True`, `False`, or `None` for range).

### Configuration variables

| Variable        | Description                                            |
|-----------------|--------------------------------------------------------|
| `SUMMARY_DIR`   | Path to `summary/` folder                             |
| `OUTPUT_HTML`   | Output `.html` path                                   |
| `OUTPUT_JSON`   | Output `.json` path for Ollama                        |
| `DATE_FROM`     | Start date (`"YYYY-MM-DD"`)                           |
| `DATE_TO`       | End date (`"YYYY-MM-DD"`)                             |
| `PROFILE`       | Dict with `age` (int) and `sex` (`"male"`/`"female"`) |
| `BASELINE_DAYS` | Rolling average window (default 90)                   |

---

## Common maintenance tasks

### Re-generating summaries from raw data (no API call needed)

```bash
python regenerate_summaries.py
```

Set `BASE_DIR` at the top of the script to match your data folder. Run this whenever `summarize()` in `garmin_collector.py` is updated.

### Re-fetching a specific day

Delete `raw/garmin_raw_YYYY-MM-DD.json` (and `summary/garmin_YYYY-MM-DD.json` if it exists), then run the collector — it re-fetches automatically.

### Rate limiting

If Garmin throttles requests: increase `REQUEST_DELAY` from `1.5` to `3.0`.

### Login / captcha issues

Garmin may require browser-based MFA on first run or after long inactivity. Run `garmin_collector.py` manually in a terminal and follow any prompts.

### Older devices (Vivosmart 3, Fenix 5)

Many fields return `null` — expected behaviour. Use `SYNC_AUTO_FALLBACK = "2018-06-01"` with `SYNC_MODE = "auto"` to control how far back to go.

### Removing the stored password

Open **Windows Credential Manager** → **Windows Credentials** → find `GarminLocalArchive` → delete.

### Pylance / VS Code import warning

The `garminconnect` import warning is cosmetic. Click the interpreter selector (bottom right in VS Code) and match it to `where python` in the terminal.

### Building a new release

```bash
python build.py
```

Produces `GarminArchive.exe` and `GarminArchive.zip` in the root folder. Upload the ZIP to the GitHub release page.
