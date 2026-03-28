# Garmin Local Archive — Technical Reference

This document is the single source of truth for all environment variables, constants, file paths, and data structures in the project. Consult this before searching through source files.

---

## Environment variables

All configuration is passed between the GUI and scripts via `os.environ`. The GUI sets them in `_build_env()` (Target 1+2) or `_apply_env()` (Target 3). Scripts read them exclusively via `garmin_config.py` — no script reads `os.environ` directly (v1.2.0+).

| Variable | Type | Default | Set by | Read by | Purpose |
|---|---|---|---|---|---|
| `GARMIN_EMAIL` | str | `"your@email.com"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_api` | Garmin Connect login email |
| `GARMIN_PASSWORD` | str | `"yourpassword"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_api` | Garmin Connect password — never written to disk |
| `GARMIN_OUTPUT_DIR` | str | `~/garmin_data` | `_build_env()` / `_apply_env()` | `garmin_config` → all modules | Root data folder — `raw/`, `summary/`, `log/` live here |
| `GARMIN_SYNC_MODE` | str | `"recent"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_sync` | Sync mode: `"recent"`, `"range"`, or `"auto"` |
| `GARMIN_DAYS_BACK` | int | `90` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_sync` | Days to check in `"recent"` mode |
| `GARMIN_SYNC_START` | str | `"2024-01-01"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_sync` | Start date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_END` | str | `"2024-12-31"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_sync` | End date for `"range"` mode (`YYYY-MM-DD`) |
| `GARMIN_SYNC_FALLBACK` | str/None | `None` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_sync` | Manual start date fallback for `"auto"` mode |
| `GARMIN_REQUEST_DELAY` | float | `1.5` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_api` | Seconds between API calls — increase to `3.0` if rate-limited |
| `GARMIN_REFRESH_FAILED` | str | `"0"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_collector` | `"1"` = exclude days with `recheck=true` from local dates → re-fetch them. Set when user answers "Ja" to the failed days popup, or by background timer for Repair/Quality runs |
| `GARMIN_LOW_QUALITY_MAX_ATTEMPTS` | int | `3` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_quality` | Max re-download attempts for `low` quality days before `recheck` is set to `false`. Configurable because older Garmin data may never improve — this prevents endless retries |
| `GARMIN_SESSION_LOG_PREFIX` | str | `"garmin"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_collector` | Prefix for session log filenames. Background timer sets `"garmin_background"` → produces `garmin_background_YYYY-MM-DD_HHMMSS.log` |
| `GARMIN_SYNC_DATES` | str | `""` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_collector` | Comma-separated list of specific dates to fetch (`YYYY-MM-DD,YYYY-MM-DD,...`). If set, overrides `GARMIN_SYNC_MODE` entirely. Used by the background timer to fetch exactly the drawn days |
| `GARMIN_LOG_LEVEL` | str | `"INFO"` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_collector` | GUI log display level: `"INFO"` (Simple) or `"DEBUG"` (Detailed). Does NOT affect session log files — those always run at DEBUG |
| `GARMIN_MAX_DAYS_PER_SESSION` | int | `30` | `_build_env()` / `_apply_env()` | `garmin_config` → `garmin_collector` | Maximum days fetched per sync run. `0` = unlimited. Prevents account throttling on large backlogs. |
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

Constants defined in `garmin_config.py` (v1.2.0+). All modules import via `import garmin_config as cfg`.

| Constant | Value | ENV override | Purpose |
|---|---|---|---|
| `GARMIN_EMAIL` | `"your@email.com"` | `GARMIN_EMAIL` | Garmin Connect login email |
| `GARMIN_PASSWORD` | `"yourpassword"` | `GARMIN_PASSWORD` | Garmin Connect password |
| `BASE_DIR` | `~/garmin_data` | `GARMIN_OUTPUT_DIR` | Root data folder |
| `RAW_DIR` | `BASE_DIR/raw` | — | Derived from `BASE_DIR` |
| `SUMMARY_DIR` | `BASE_DIR/summary` | — | Derived from `BASE_DIR` |
| `LOG_DIR` | `BASE_DIR/log` | — | Derived from `BASE_DIR` |
| `LOG_RECENT_DIR` | `BASE_DIR/log/recent` | — | Derived from `LOG_DIR` |
| `LOG_FAIL_DIR` | `BASE_DIR/log/fail` | — | Derived from `LOG_DIR` |
| `QUALITY_LOG_FILE` | `BASE_DIR/log/quality_log.json` | — | Derived from `LOG_DIR` |
| `GARMIN_TOKEN_FILE` | `BASE_DIR/log/garmin_token.enc` | — | Encrypted OAuth token — managed exclusively by `garmin_security.py` |
| `SYNC_MODE` | `"recent"` | `GARMIN_SYNC_MODE` | Sync mode: `"recent"`, `"range"`, `"auto"` |
| `SYNC_DAYS` | `90` | `GARMIN_DAYS_BACK` | Days back in recent mode |
| `SYNC_FROM` | `"2024-01-01"` | `GARMIN_SYNC_START` | Start date for range mode |
| `SYNC_TO` | `"2024-12-31"` | `GARMIN_SYNC_END` | End date for range mode |
| `SYNC_AUTO_FALLBACK` | `None` | `GARMIN_SYNC_FALLBACK` | Manual fallback date for auto mode |
| `SYNC_DATES` | `None` | `GARMIN_SYNC_DATES` | Parsed list of `date` objects — overrides sync mode if set |
| `REQUEST_DELAY` | `1.5` | `GARMIN_REQUEST_DELAY` | Seconds between API calls |
| `REFRESH_FAILED` | `False` | `GARMIN_REFRESH_FAILED` | If `True`, days with `recheck=true` are excluded from local dates |
| `LOW_QUALITY_MAX_ATTEMPTS` | `3` | `GARMIN_LOW_QUALITY_MAX_ATTEMPTS` | Max re-download attempts for `low` quality days |
| `SESSION_LOG_PREFIX` | `"garmin"` | `GARMIN_SESSION_LOG_PREFIX` | Prefix for session log filenames |
| `LOG_RECENT_MAX` | `30` | — | Max session logs kept in `log/recent/` |
| `LOG_LEVEL` | `"INFO"` | `GARMIN_LOG_LEVEL` | Root logger level |
| `MAX_DAYS_PER_SESSION` | `30` | `GARMIN_MAX_DAYS_PER_SESSION` | Max days fetched per run. `0` = unlimited. |

**App constants** (defined in `garmin_app.py` / `garmin_app_standalone.py`):

| Constant | File | Value | Purpose |
|---|---|---|---|
| `KEYRING_SERVICE` | both | `"GarminLocalArchive"` | Windows Credential Manager service name |
| `KEYRING_USER` | both | `"garmin_password"` | Windows Credential Manager username key |
| `KEYRING_ENC_USER` | `garmin_security` | `"token_enc_key"` | WCM key for the token encryption key |
| `SETTINGS_FILE` | both | `~/.garmin_archive_settings.json` | Path to the settings JSON file |

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
│   ├── garmin_token.enc                – AES-256-GCM encrypted OAuth token (garmin_security)
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

**Token encryption key** (outside BASE_DIR):
```
Windows Credential Manager → GarminLocalArchive / token_enc_key
```

---

## Data structures

### `quality_log.json`

Located at `BASE_DIR/log/quality_log.json`.

**Why this file exists:** Garmin Connect stores intraday detail data (per-second heart rate, per-minute stress, sleep stage details) for a limited time — typically 1–2 years. After that, only daily aggregate data is available from the API. A raw file from an older day may be technically valid JSON but contain far less data than a recent day. File size alone cannot reliably distinguish between a complete file and a legitimately sparse one.

`quality_log.json` is a persistent register of every day the collector has ever downloaded. It tracks the quality of the raw data so the background timer knows which days are worth re-trying and which have reached their ceiling.

**On first run**, the collector migrates the old `failed_days.json` automatically — reads it, writes `quality_log.json`, and deletes the old file. Existing `"med"` quality entries are automatically upgraded to `"medium"`. Entries without a `write` field receive `"write": null`.

```json
{
  "first_day": "2021-05-10",
  "devices": [
    {
      "name": "fenix 7X Sapphire Solar",
      "id": 3425438179,
      "first_used": "2025-03-01",
      "last_used": "unknown"
    }
  ],
  "days": [
    {
      "date": "2025-11-15",
      "quality": "high",
      "reason": "Quality: high",
      "write": true,
      "recheck": false,
      "attempts": 0,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    },
    {
      "date": "2025-01-15",
      "quality": "low",
      "reason": "Quality: low — insufficient data from Garmin API",
      "write": true,
      "recheck": true,
      "attempts": 1,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    },
    {
      "date": "2024-11-03",
      "quality": "failed",
      "reason": "Timeout: connection reset",
      "write": false,
      "recheck": true,
      "attempts": 2,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11"
    }
  ]
}
```

**Root fields:**

| Field | Type | Description |
|---|---|---|
| `first_day` | str/null | ISO date of the earliest valid day in this Garmin account. Set once on first run, never overwritten. Used by auto mode and background timer as the lower bound. `null` until determined |
| `devices` | list | Registered Garmin devices. Updated on every successful login. Each entry has `name`, `id`, `first_used`, `last_used` (ISO dates, or `"unknown"` if not provided by the API) |
| `days` | list | Quality register — one entry per known day |

**Day entry fields:**

| Field | Type | Description |
|---|---|---|
| `date` | str | ISO date (`YYYY-MM-DD`) |
| `quality` | str | See quality levels below |
| `reason` | str | Human-readable description of the last assessment |
| `write` | bool/null | `true` = files written successfully, `false` = write skipped or failed, `null` = pre-v1.2.0 entry (unknown) |
| `recheck` | bool | `true` = background timer will re-download this day. `false` = leave it as-is |
| `attempts` | int | Number of re-download attempts for this day |
| `last_checked` | str | ISO date of last quality assessment |
| `last_attempt` | str/null | ISO datetime of last download attempt. `null` if never re-downloaded |

**Quality levels:**

| Level | Meaning | `recheck` default | Timer behaviour |
|---|---|---|---|
| `high` | Intraday data present — HR values, stress values, sleep stage details | `false` | Never re-downloaded |
| `medium` | Daily aggregates present but no intraday — typical for older Garmin data (1–2 years back) | `false` | Never re-downloaded — this is as good as it gets |
| `low` | Only summary-level data — minimum useful content | `true` (until `LOW_QUALITY_MAX_ATTEMPTS` reached, then `false`) | Re-downloaded up to 3 times, then left alone |
| `failed` | API error — no usable file created | `true` | Re-downloaded until successful |

**`assess_quality(raw)` logic** — called after every download:
- `high` if `heart_rates.heartRateValues` or `stress.stressValuesArray` contains entries
- `medium` if `stats.totalSteps` or `user_summary.totalSteps` is present (daily aggregate), but no intraday
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
| `generated_by` | Always `"garmin_normalizer.py"` |
| `sleep` | Sleep duration, stages, score, SpO2, HRV |
| `heartrate` | Resting, max, min, average BPM |
| `stress` | Stress average/max, Body Battery max/min/end |
| `day` | Steps, calories, intensity minutes, distance |
| `training` | Readiness score, training status, load, VO2max |
| `activities` | List of activity objects |

---

## Key functions reference

### `garmin_config.py`

Pure constants module — no functions. All other modules import via `import garmin_config as cfg`. See Code constants section above.

---

### `garmin_api.py`

| Function | Purpose |
|---|---|
| `login(on_key_required, on_token_expired)` | Logs in to Garmin Connect. Tries saved token first (Path 1), falls back to SSO on expiry (Path 2) or first setup (Path 3). Both callbacks optional — called via direct dialog (T1/T2) or threading.Event/queue (T3). Returns authenticated client. Calls `sys.exit(1)` on unrecoverable failure |
| `api_call(client, method, *args, label)` | Single API call with `cfg.REQUEST_DELAY` and stop-check. Returns `(data, success)` |
| `fetch_raw(client, date_str)` | Calls all 14 Garmin API endpoints for a given date. Returns raw dict with `{"date": ..., "sleep": ..., ...}` |
| `get_devices(client)` | Fetches registered device list, logs names and dates, returns sorted list |
| `_is_stopped()` | Returns `True` if standalone GUI has injected `_STOP_EVENT` and set it. Safe to call without injection |
| `_parse_device_date(val)` | Converts device date value to `YYYY-MM-DD`. Handles ISO strings, second and millisecond timestamps |

---

### `garmin_security.py`

| Function | Purpose |
|---|---|
| `get_enc_key()` | Reads encryption key from WCM. Returns `None` if not found |
| `store_enc_key(enc_key)` | Writes encryption key to WCM. Returns `True` on success |
| `save_token(token_string)` | Derives AES key via PBKDF2, encrypts token with AES-256-GCM, writes `garmin_token.enc` to `LOG_DIR`. Reads enc_key from WCM internally |
| `load_token()` | Reads enc_key from WCM, decrypts `garmin_token.enc`, returns plaintext token string. Plaintext never written to disk. Returns `None` if file missing, WCM empty, or decryption failed |
| `clear_token()` | Removes `garmin_token.enc` from disk and enc_key from WCM |
| `_derive_aes_key(enc_key)` | Private. Derives 32-byte AES key from enc_key string via PBKDF2-HMAC-SHA256 (600k iterations, fixed salt) |

---

### `garmin_normalizer.py`

| Function | Purpose |
|---|---|
| `normalize(raw, source)` | Entry point — delegates to source-specific normaliser. `source`: `"api"` or `"bulk"` |
| `summarize(raw)` | Distils a normalised raw dict into a compact daily summary (~2 KB). Sole owner of summary structure |
| `_normalize_api(raw)` | Normalises Garmin API raw dict. Passes through unchanged, guarantees `"date"` key present |
| `_normalize_import(raw)` | Placeholder for bulk import normalisation — not implemented in v1.2.0 |
| `safe_get(d, *keys, default)` | Safely traverses nested dicts — returns `default` if any key is missing. Used internally by `summarize()` |
| `_parse_list_values(lst, dict_key)` | Extracts numeric values from a list of dicts or `[timestamp, value]` pairs. Used internally by `summarize()` |

---

### `garmin_writer.py`

| Function | Purpose |
|---|---|
| `write_day(normalized, summary, date_str)` | Sole owner of `raw/` and `summary/`. Writes `garmin_raw_YYYY-MM-DD.json` and `garmin_YYYY-MM-DD.json`. Returns `True` on success, `False` on any error. Creates target directories if missing |

---

### `garmin_quality.py`

| Function | Purpose |
|---|---|
| `_load_quality_log()` | Loads `quality_log.json`. Migrates `failed_days.json`, timestamp dates, `"med"` → `"medium"`, missing `write` field (→ `null`), and old schema on first run. Returns empty structure if missing or corrupt |
| `_save_quality_log(data)` | Writes `quality_log.json` atomically via `.tmp` file |
| `assess_quality(raw)` | Inspects raw data content and returns `"high"`, `"medium"`, `"low"`, or `"failed"`. Pure function — no file IO |
| `_upsert_quality(data, day, quality, reason, written)` | Adds or updates a day entry. Increments `attempts` for `failed`/`low`. Sets `recheck=false` for `low` after `LOW_QUALITY_MAX_ATTEMPTS`. `written`: `True`/`False`/`None` — stored as `write` field |
| `get_low_quality_dates(folder, known_dates)` | Scans `raw/` for files not yet in the quality log and assesses their quality. Skips `known_dates` to avoid cloud downloads |
| `_backfill_quality_log(data)` | One-time backfill: scans all existing `raw/` files and adds any days not yet in the log. Only runs when `first_day` is not yet set |
| `_set_first_day(data, client)` | Determines and persists `first_day`. Resolution order: devices → account profile → `SYNC_AUTO_FALLBACK` → oldest local file. Never overwrites existing value |
| `cleanup_before_first_day(data, dry_run)` | Deletes all `raw/` and `summary/` files before `first_day` and removes corresponding log entries. Saves `quality_log.json` unless `dry_run=True` |
| `_parse_device_date(val)` | Converts device date value to `YYYY-MM-DD`. Handles ISO strings, second and millisecond timestamps |

---

### `garmin_sync.py`

| Function | Purpose |
|---|---|
| `resolve_date_range(first_day)` | Returns `(start, end)` based on `cfg.SYNC_MODE`. `first_day` comes from `quality_data["first_day"]` via `main()` — no internal file access |
| `get_local_dates(folder, recheck_dates)` | Returns set of dates with local data. `recheck_dates` (from `main()`) are subtracted when `cfg.REFRESH_FAILED` is `True` — no internal file access |
| `date_range(start, end)` | Generator — yields every `date` from `start` to `end` inclusive |

---

### `garmin_import.py`

| Function | Purpose |
|---|---|
| `load_bulk(path)` | Placeholder — not implemented in v1.2.0. Will load Garmin ZIP export and yield raw dicts per day |
| `parse_day(data, date_str)` | Placeholder — not implemented in v1.2.0. Will extract one day from bulk data |

---

### `garmin_collector.py`

| Function | Purpose |
|---|---|
| `_should_write(label)` | Decision function — returns `True` if quality label is acceptable for writing (`high`, `medium`, `low`). Returns `False` for `failed` |
| `_process_day(client, date_str)` | Isolated processing function: fetch → normalize → summarize → assess → write. Returns `(label, written)` tuple |
| `_is_stopped()` | Returns `True` if standalone GUI has injected `_STOP_EVENT` and set it |
| `_start_session_log()` | Opens `log/recent/{SESSION_LOG_PREFIX}_YYYY-MM-DD_HHMMSS.log` at DEBUG level. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if session had errors or low-quality downloads, enforces rolling limit |
| `main()` | Orchestrates the full sync pipeline: dirs → session log → quality load → login → devices → first_day → date resolution → fetch loop → save |

---

### `garmin_app.py` / `garmin_app_standalone.py`

| Function | Purpose |
|---|---|
| `_build_env(s, refresh_failed)` | Builds full ENV dict for subprocess. `refresh_failed=True` sets `GARMIN_REFRESH_FAILED=1` |
| `_apply_env(s, refresh_failed)` | Same as `_build_env` but writes directly to `os.environ` (standalone only) |
| `_apply_env_overrides(overrides)` | Applies a dict of ENV overrides on top of `_apply_env()` output (standalone only). Used by background timer to set `GARMIN_SYNC_DATES` etc. |
| `_check_failed_days_popup(...)` | Reads `quality_log.json`, counts `failed`+`low` entries with `recheck=true` in current sync range, shows Ja/Nein popup |
| `_clean_archive()` | Reads `first_day` from `quality_log.json`, shows popup with scrollable file list, calls `garmin_quality.cleanup_before_first_day()` on confirm |
| `_prompt_enc_key(mode)` | Modal popup to collect encryption key. `mode="setup"`: two fields + confirm. `mode="recovery"`: single field. Blocks calling thread via `threading.Event`. Returns key string or `None` |
| `_prompt_token_expired()` | Modal popup warning about 429 risk on SSO fallback. Returns `True` (Proceed) or `False` (Cancel). Blocks calling thread via `threading.Event` |
| `_reset_token()` | Calls `garmin_security.clear_token()`, resets Token lamp to ⚪, clears `_connection_verified` |
| `_toggle_log_level()` | Switches GUI display between INFO and DEBUG. Does NOT restart sync |
| `_connection_verified` | Session flag — `True` after first successful connection test |
| `_timer_conn_verified` | Session flag — `True` after background timer runs its own connection test |
| `_toggle_timer()` | Starts or stops the background timer. Increments `_timer_generation` to invalidate stale threads |
| `_timer_loop(generation)` | Main timer loop. Cycles through Repair → Quality → Fill modes |
| `_timer_run_repair(s)` | Returns dates with `quality=failed` and `recheck=true` |
| `_timer_run_quality(s)` | Returns dates with `quality=low` and `recheck=true` |
| `_timer_run_fill(s)` | Returns dates completely absent from `raw/` and not in the quality log |
| `_timer_update_btn()` | Updates timer button: green + countdown when active, grey when stopped |
| `_timer_resume_after_sync(was_active)` | Restarts timer after a manual sync if it was active before |
