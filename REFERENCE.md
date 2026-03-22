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
| `GARMIN_REFRESH_FAILED` | str | `"0"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | `"1"` = exclude days with `recheck=true` from local dates → re-fetch them. Set when user answers "Ja" to the failed days popup, or by background timer for Repair/Quality runs |
| `GARMIN_LOW_QUALITY_MAX_ATTEMPTS` | int | `3` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Max re-download attempts for `low` quality days before `recheck` is set to `false`. Configurable because older Garmin data may never improve — this prevents endless retries |
| `GARMIN_SESSION_LOG_PREFIX` | str | `"garmin"` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Prefix for session log filenames. Background timer sets `"garmin_background"` → produces `garmin_background_YYYY-MM-DD_HHMMSS.log` |
| `GARMIN_SYNC_DATES` | str | `""` | `_build_env()` / `_apply_env()` | `garmin_collector.py` | Comma-separated list of specific dates to fetch (`YYYY-MM-DD,YYYY-MM-DD,...`). If set, overrides `GARMIN_SYNC_MODE` entirely. Used by the background timer to fetch exactly the drawn days |
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
| `REFRESH_FAILED` | `garmin_collector.py` | `False` (ENV: `GARMIN_REFRESH_FAILED`) | If True, days with `recheck=true` in quality log are excluded from local dates and re-fetched |
| `LOW_QUALITY_MAX_ATTEMPTS` | `garmin_collector.py` | `3` (ENV: `GARMIN_LOW_QUALITY_MAX_ATTEMPTS`) | After this many failed re-download attempts for a `low` quality day, `recheck` is set to `false` — Garmin no longer has the detailed data |
| `SESSION_LOG_PREFIX` | `garmin_collector.py` | `"garmin"` (ENV: `GARMIN_SESSION_LOG_PREFIX`) | Prefix for session log filenames |
| `SYNC_DATES` | `garmin_collector.py` | `None` (ENV: `GARMIN_SYNC_DATES`) | Parsed list of `date` objects. If set, `main()` fetches exactly these dates and skips `resolve_date_range()` |
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
│   ├── quality_log.json                – quality register for all known days
│   ├── recent/
│   │   └── garmin_YYYY-MM-DD_HHMMSS.log          – last 30 manual sync sessions (always DEBUG)
│   │   └── garmin_background_YYYY-MM-DD_HHMMSS.log  – background timer sessions
│   └── fail/
│       └── garmin_*_YYYY-MM-DD_HHMMSS.log  – sessions with errors or low quality (kept permanently)
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

### `quality_log.json`

Located at `BASE_DIR/log/quality_log.json`.

**Why this file exists:** Garmin Connect stores intraday detail data (per-second heart rate, per-minute stress, sleep stage details) for a limited time — typically 1–2 years. After that, only daily aggregate data is available from the API. A raw file from an older day may be technically valid JSON but contain far less data than a recent day. File size alone cannot reliably distinguish between a complete file and a legitimately sparse one.

`quality_log.json` is a persistent register of every day the collector has ever downloaded. It tracks the quality of the raw data so the background timer knows which days are worth re-trying and which have reached their ceiling.

**On first run**, the collector migrates the old `failed_days.json` automatically — reads it, writes `quality_log.json`, and deletes the old file.

```json
{
  "days": [
    {
      "date": "2025-11-15",
      "quality": "high",
      "reason": "Quality: high",
      "recheck": false,
      "attempts": 0,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    },
    {
      "date": "2025-01-15",
      "quality": "low",
      "reason": "Quality: low — insufficient data from Garmin API",
      "recheck": true,
      "attempts": 1,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    },
    {
      "date": "2024-11-03",
      "quality": "failed",
      "reason": "Timeout: connection reset",
      "recheck": true,
      "attempts": 2,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `date` | str | ISO date (`YYYY-MM-DD`) |
| `quality` | str | See quality levels below |
| `reason` | str | Human-readable description of the last assessment |
| `recheck` | bool | `true` = background timer will re-download this day. `false` = leave it as-is |
| `attempts` | int | Number of re-download attempts for this day |
| `last_checked` | str | ISO date of last quality assessment |
| `last_attempt` | str/null | ISO datetime of last download attempt. `null` if never re-downloaded |

**Quality levels:**

| Level | Meaning | `recheck` default | Timer behaviour |
|---|---|---|---|
| `high` | Intraday data present — HR values, stress values, sleep stage details | `false` | Never re-downloaded |
| `med` | Daily aggregates present but no intraday — typical for older Garmin data (1–2 years back) | `false` | Never re-downloaded — this is as good as it gets |
| `low` | Only summary-level data — minimum useful content | `true` (until `LOW_QUALITY_MAX_ATTEMPTS` reached, then `false`) | Re-downloaded up to 3 times, then left alone |
| `failed` | API error — no usable file created | `true` | Re-downloaded until successful |

**`assess_quality(raw)` logic** — called after every download:
- `high` if `heart_rates.heartRateValues` or `stress.stressValuesArray` contains entries
- `med` if `stats.totalSteps` or `user_summary.totalSteps` is present (daily aggregate), but no intraday
- `low` if only minimal stats present (bare `stats` or `user_summary` dict, but no meaningful values)
- `failed` if neither `stats` nor `user_summary` contains anything usable

**Startup scan:** On each run, `main()` loads the quality log and collects all already-known dates. Only raw files **not** in the log are read for quality assessment — preventing unnecessary downloads of cloud-synced files (e.g. OneDrive). The first run after installation scans all existing files; subsequent runs only scan new ones.

Written atomically via a `.tmp` file to prevent corruption.

### Session log files

Located at `BASE_DIR/log/recent/garmin_YYYY-MM-DD_HHMMSS.log` and `BASE_DIR/log/fail/garmin_YYYY-MM-DD_HHMMSS.log`.

Background timer sessions use the prefix `garmin_background_` → `BASE_DIR/log/recent/garmin_background_YYYY-MM-DD_HHMMSS.log`. In `log/fail/` the prefix immediately identifies the source.

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
| `assess_quality(raw)` | Inspects raw data content and returns `"high"`, `"med"`, `"low"`, or `"failed"` |
| `get_low_quality_dates(folder, known_dates)` | Scans `raw/` for files not yet in the quality log and assesses their quality. Skips `known_dates` to avoid cloud downloads |
| `get_local_dates(folder)` | Returns set of dates with local data. If `REFRESH_FAILED=True`, excludes days with `recheck=true` so they appear as missing |
| `_load_quality_log()` | Loads `quality_log.json`. Migrates old `failed_days.json` on first run. Returns empty structure if missing or corrupt |
| `_save_quality_log(data)` | Writes `quality_log.json` atomically via `.tmp` file |
| `_upsert_quality(data, day, quality, reason)` | Adds or updates a day entry. Increments `attempts` for `failed` and `low`. Sets `recheck=false` for `low` after `LOW_QUALITY_MAX_ATTEMPTS` |
| `_mark_quality_ok(data, day, quality)` | Marks a day as `high` or `med` — sets `recheck=false` |
| `_start_session_log()` | Opens `log/recent/{SESSION_LOG_PREFIX}_YYYY-MM-DD_HHMMSS.log` at DEBUG level. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if session had errors or low-quality downloads, enforces rolling limit |

### `garmin_app.py` / `garmin_app_standalone.py`

| Function | Purpose |
|---|---|
| `_build_env(s, refresh_failed)` | Builds full ENV dict for subprocess. `refresh_failed=True` sets `GARMIN_REFRESH_FAILED=1` |
| `_apply_env(s, refresh_failed)` | Same as `_build_env` but writes directly to `os.environ` (standalone only) |
| `_apply_env_overrides(overrides)` | Applies a dict of ENV overrides on top of `_apply_env()` output (standalone only). Used by background timer to set `GARMIN_SYNC_DATES` etc. |
| `_check_failed_days_popup(...)` | Reads `quality_log.json`, counts `failed`+`low` entries with `recheck=true` in current sync range, shows Ja/Nein popup |
| `_toggle_log_level()` | Switches GUI display between INFO and DEBUG. Shows hint label if sync is running. Does NOT restart sync |
| `_connection_verified` | Session flag — `True` after first successful connection test. Skips test on subsequent syncs |
| `_timer_conn_verified` | Session flag — `True` after background timer runs its own connection test. On success also sets `_connection_verified` |
| `_toggle_timer()` | Starts or stops the background timer. Increments `_timer_generation` to invalidate stale threads |
| `_timer_loop(generation)` | Main timer loop. Cycles through Repair → Quality → Fill modes. Exits if generation is stale |
| `_timer_run_repair(s)` | Returns dates with `quality=failed` and `recheck=true`. These are API errors — no file exists |
| `_timer_run_quality(s)` | Returns dates with `quality=low` and `recheck=true`. These have files but poor content |
| `_timer_run_fill(s)` | Returns dates completely absent from `raw/` and not in the quality log — true gaps |
| `_timer_update_btn()` | Updates timer button: green + countdown when active, grey + "Timer: Off" when stopped |
| `_timer_resume_after_sync(was_active)` | Restarts timer after a manual sync if it was active before |
