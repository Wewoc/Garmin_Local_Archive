# Garmin Local Archive — Technical Reference

This document is the single source of truth for all environment variables, constants, file paths, and data structures in the project. Consult this before searching through source files.

---

## Environment variables

All configuration is passed between the GUI and scripts via `os.environ`. The GUI sets them in `_build_env()` (Target 1+2) or `_apply_env()` (Target 3). Scripts read them at module level via `os.environ.get()`.

| Variable | Type | Default | Set by | Read by | Purpose |
|---|---|---|---|---|---|
| `GARMIN_EMAIL` | str | `"your@email.com"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Garmin Connect login email |
| `GARMIN_PASSWORD` | str | `"yourpassword"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Garmin Connect password — never written to disk |
| `GARMIN_OUTPUT_DIR` | str | `~/garmin_data` | `_build_env()` / `_apply_env()` | all scripts | Root data folder — `raw/`, `summary/`, `log/` live here |
| `GARMIN_SYNC_MODE` | str | `"recent"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Sync mode: `"recent"`, `"range"`, or `"auto"` |
| `GARMIN_DAYS_BACK` | int | `90` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Days to check in `"recent"` mode |
| `GARMIN_SYNC_START` | str | `"2024-01-01"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Start date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_END` | str | `"2024-12-31"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | End date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_FALLBACK` | str/None | `None` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Manual start date fallback for `"auto"` mode |
| `GARMIN_REQUEST_DELAY` | float | `1.5` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Seconds between API calls — increase to `3.0` if rate-limited |
| `GARMIN_INCOMPLETE_KB` | int | `100` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Raw files below this size (KB) are flagged as incomplete |
| `GARMIN_REFRESH_FAILED` | str | `"0"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | `"1"` = exclude incomplete days from local dates → re-fetch them. Set when user answers "Ja" to the failed days popup |
| `GARMIN_LOG_LEVEL` | str | `"INFO"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | GUI log display level: `"INFO"` (Simple) or `"DEBUG"` (Detailed). Does NOT affect session log files — those always run at DEBUG |
| `GARMIN_EXPORT_FILE` | str | `BASE_DIR/garmin_export.xlsx` | `_build_env()` / `_apply_env()` | `garmin_to_excel.py` | Output path for daily overview Excel |
| `GARMIN_TIMESERIES_FILE` | str | `BASE_DIR/garmin_timeseries.xlsx` | `_build_env()` / `_apply_env()` | `garmin_timeseries_excel.py` | Output path for timeseries Excel |
| `GARMIN_DASHBOARD_FILE` | str | `BASE_DIR/garmin_dashboard.html` | `_build_env()` / `_apply_env()` | `garmin_timeseries_html.py` | Output path for timeseries HTML dashboard |
| `GARMIN_ANALYSIS_HTML` | str | `BASE_DIR/garmin_analysis.html` | `_build_env()` / `_apply_env()` | `garmin_analysis_html.py` | Output path for analysis HTML dashboard |
| `GARMIN_ANALYSIS_JSON` | str | `BASE_DIR/garmin_analysis.json` | `_build_env()` / `_apply_env()` | `garmin_analysis_html.py` | Output path for Ollama/Open WebUI JSON |
| `GARMIN_DATE_FROM` | str | 90 days ago | `_build_env()` / `_apply_env()` | export scripts | Start date for export scripts (`YYYY-MM-DD`) |
| `GARMIN_DATE_TO` | str | today | `_build_env()` / `_apply_env()` | export scripts | End date for export scripts (`YYYY-MM-DD`) |
| `GARMIN_PROFILE_AGE` | str | `"35"` | `_build_env()` / `_apply_env()` | `garmin_analysis_html.py` | User age for reference range calculation |
| `GARMIN_PROFILE_SEX` | str | `"male"` | `_build_env()` / `_apply_env()` | `garmin_analysis_html.py` | User sex for reference range calculation (`"male"` / `"female"`) |
| `PYTHONUTF8` | str | `"1"` | `_build_env()` / `_apply_env()` | Python runtime | Forces UTF-8 mode — prevents encoding issues on Windows |

---

## Code constants

Constants defined at module level in source files. Not configurable via ENV.

| Constant | File | Value | Purpose |
|---|---|---|---|
| `INCOMPLETE_FILE_KB` | `garmin_collector.py` | `100` (ENV override: `GARMIN_INCOMPLETE_KB`) | Raw file size threshold in KB below which a day is considered incomplete |
| `REFRESH_FAILED` | `garmin_collector.py` | `False` (ENV override: `GARMIN_REFRESH_FAILED`) | Whether to re-fetch incomplete days in this sync run |
| `LOG_RECENT_MAX` | `garmin_collector.py` | `30` | Maximum number of session logs kept in `log/recent/` |
| `KEYRING_SERVICE` | `garmin_app.py` / `garmin_app_standalone.py` | `"GarminLocalArchive"` | Windows Credential Manager service name |
| `KEYRING_USER` | `garmin_app.py` / `garmin_app_standalone.py` | `"garmin_password"` | Windows Credential Manager username key |
| `SETTINGS_FILE` | `garmin_app.py` / `garmin_app_standalone.py` | `~/.garmin_archive_settings.json` | Path to the settings JSON file |

---

## File and folder structure

```
BASE_DIR/                               – configured in Settings → Data folder
├── raw/
│   └── garmin_raw_YYYY-MM-DD.json      – full API dump (~500 KB/day, never modified)
├── summary/
│   └── garmin_YYYY-MM-DD.json          – compact daily summary (~2 KB)
├── log/
│   ├── failed_days.json                – registry of failed and incomplete days
│   ├── recent/
│   │   └── garmin_YYYY-MM-DD_HHMMSS.log  – last 30 session logs (always DEBUG)
│   └── fail/
│       └── garmin_YYYY-MM-DD_HHMMSS.log  – sessions with errors or incomplete days (kept permanently)
├── garmin_export.xlsx                  – daily overview export
├── garmin_timeseries.xlsx              – intraday timeseries export
├── garmin_dashboard.html               – timeseries HTML dashboard
├── garmin_analysis.html                – analysis HTML dashboard
└── garmin_analysis.json                – compact summary for Ollama / Open WebUI
```

**Settings file** (outside BASE_DIR):
```
~/.garmin_archive_settings.json         – all UI settings except password
```

**Password** (outside BASE_DIR):
```
Windows Credential Manager → GarminLocalArchive / garmin_password
```

---

## Data structures

### `failed_days.json`

Located at `BASE_DIR/log/failed_days.json`.

```json
{
  "failed": [
    {
      "date": "2024-11-03",
      "reason": "Timeout: connection reset",
      "category": "error",
      "attempts": 2,
      "last_attempt": "2025-03-20T14:32:11"
    },
    {
      "date": "2025-01-15",
      "reason": "File too small: 18 KB (threshold: 100 KB)",
      "category": "incomplete",
      "attempts": 0,
      "last_attempt": null
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `date` | str | ISO date (`YYYY-MM-DD`) |
| `reason` | str | Human-readable description of why the day failed |
| `category` | str | `"error"` = API exception during download; `"incomplete"` = raw file below size threshold |
| `attempts` | int | Number of download attempts. `"error"` entries increment on each retry. `"incomplete"` entries stay at `0` until a real download is attempted |
| `last_attempt` | str/null | ISO datetime of last attempt. `null` for `"incomplete"` entries that have never been re-fetched |

Written atomically via a `.tmp` file to prevent corruption if the process is killed mid-write.

### Session log files

Located at `BASE_DIR/log/recent/garmin_YYYY-MM-DD_HHMMSS.log` and `BASE_DIR/log/fail/garmin_YYYY-MM-DD_HHMMSS.log`.

Plain text, one line per log record:

```
2026-03-22 09:46:03 INFO   Mode: range — 2025-01-01 → 2026-03-19
2026-03-22 09:46:03 INFO   Local days found: 141
2026-03-22 09:46:26 INFO   [1/304] 2025-01-01
```

Always written at `DEBUG` level regardless of the GUI log toggle. The GUI toggle only controls what is displayed in the GUI log window — it does not affect session log files.

Every sync session writes to `log/recent/`. If the session produced errors or incomplete days, the same file is additionally copied to `log/fail/`. `log/recent/` is capped at `LOG_RECENT_MAX` (30) files — oldest are deleted automatically. `log/fail/` has no automatic limit.

### Summary JSON (`summary/garmin_YYYY-MM-DD.json`)

Compact daily summary (~2 KB). Key top-level fields:

| Field | Description |
|---|---|
| `date` | ISO date string |
| `generated_by` | Always `"garmin_collector.py"` |
| `sleep` | Sleep duration, stages, score, SpO2, HRV |
| `heartrate` | Resting, max, min, average BPM |
| `stress` | Stress average/max, Body Battery max/min/end |
| `day` | Steps, calories, intensity minutes, distance |
| `training` | Readiness score, training status, load, VO2max |
| `activities` | List of activity objects |

---

## Key functions reference

### `garmin_collector.py`

| Function | Purpose |
|---|---|
| `get_incomplete_dates(folder)` | Scans `raw/` for files below `INCOMPLETE_FILE_KB`. Returns `{date: size_kb}` |
| `get_local_dates(folder)` | Returns set of dates with local data. If `REFRESH_FAILED=True`, filters out incomplete dates so they appear as missing |
| `_load_failed_days()` | Loads `log/failed_days.json`. Migrates `incomplete` entries with `attempts > 0` back to `0`. Returns empty structure if missing or corrupt |
| `_save_failed_days(data)` | Writes `log/failed_days.json` atomically via `.tmp` file |
| `_upsert_failed(data, day, category, reason)` | Adds new entry or updates existing one. For `"error"`: increments `attempts`. For `"incomplete"`: only updates `reason` |
| `_remove_failed(data, day)` | Removes a day after successful download |
| `_start_session_log()` | Opens `log/recent/garmin_YYYY-MM-DD_HHMMSS.log` at DEBUG level. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if needed, enforces rolling limit |

### `garmin_app.py` / `garmin_app_standalone.py`

| Function | Purpose |
|---|---|
| `_build_env(s, refresh_failed)` | Builds full ENV dict for subprocess. `refresh_failed=True` sets `GARMIN_REFRESH_FAILED=1` |
| `_apply_env(s, refresh_failed)` | Same as `_build_env` but writes directly to `os.environ` (standalone only) |
| `_check_failed_days_popup(...)` | Reads `log/failed_days.json`, counts entries in current sync range, shows Ja/Nein popup. Returns `True` if user wants re-fetch |
| `_toggle_log_level()` | Switches GUI display between INFO and DEBUG. Shows hint label above button if sync is running. Does NOT restart sync |
| `_connection_verified` | Session flag. `True` after first successful connection test — skips test on subsequent syncs |
