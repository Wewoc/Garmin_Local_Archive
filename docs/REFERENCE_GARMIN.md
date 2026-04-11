# Garmin Local Archive — Garmin Pipeline Reference

Technical reference for the Garmin data pipeline (`garmin/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.

---

## Pipeline overview

```
garmin_app.py (GUI)
  └── _build_env() / _apply_env()
        └── garmin_collector.main()
              ├── garmin_api.login()
              ├── garmin_quality._set_first_day()
              ├── garmin_sync.resolve_date_range()
              ├── per day:
              │     garmin_api.fetch_raw()
              │     garmin_validator.validate()
              │     garmin_normalizer.normalize() + summarize()
              │     garmin_quality.assess_quality()
              │     garmin_writer.write_day()
              │     garmin_quality._upsert_quality()
              └── garmin_quality._save_quality_log()
```

**Invariants:**
- `garmin_validator.py` always runs before `garmin_normalizer.py`
- `garmin_writer.py` is sole write authority for `raw/` and `summary/`
- `garmin_quality.py` is sole write authority for `quality_log.json`
- `garmin_utils.py` and `garmin_validator.py` are leaf nodes — no project-module imports
- `QUALITY_LOCK` must be held around all load-modify-save sequences
- `fetch_raw()` returns `(raw, failed_endpoints)` — never raises
- `_process_day()` returns `(label, written, fields, val_result)` — never raises

---

## `garmin_config.py`

Pure constants module — no functions. See `REFERENCE_GLOBAL.md` for full constant list.

---

## `garmin_api.py`

| Function / Symbol | Purpose |
|---|---|
| `GarminLoginError` | Exception raised on unrecoverable login failure. Replaces `sys.exit(1)` |
| `login(on_key_required, on_token_expired, on_mfa_required)` | Logs in to Garmin Connect. Tries saved token first, falls back to SSO. MFA via callback. Returns client or `None` if cancelled. Raises `GarminLoginError` on failure |
| `api_call(client, method, *args, label)` | Single API call with random delay and stop-check. Returns `(data, success)` |
| `fetch_raw(client, date_str)` | Calls all 14 Garmin API endpoints. Returns `(raw: dict, failed_endpoints: list[str])` |
| `get_devices(client)` | Fetches registered device list. Returns sorted list |
| `_is_stopped()` | Returns `True` if stop event is set. Safe to call without injection |

**Auth token flow:**

- Path 1 (token valid): `load_token()` → `Garmin()` + `login(token_dir)` → `_clear_token_dir()` → probe call
- Path 2 (token expired): `clear_token()` → `on_token_expired()` → Path 3
- Path 3 (SSO): `Garmin(email, pw, return_on_mfa=True)` → `login()` → MFA → `save_token()`
- Path 3b (key missing): `on_key_required()` → store key → retry Path 1

---

## `garmin_security.py`

| Function | Purpose |
|---|---|
| `get_enc_key()` | Reads encryption key from Windows Credential Manager. Returns `None` if not found |
| `store_enc_key(enc_key)` | Writes encryption key to WCM. Returns `bool` |
| `save_token()` | Reads `garmin_tokens.json` from `GARMIN_TOKEN_DIR`, encrypts AES-256-GCM, writes `.enc`, removes dir. Returns `bool` |
| `load_token()` | Decrypts `.enc`, writes `garmin_tokens.json` to `GARMIN_TOKEN_DIR`. Returns `bool` |
| `clear_token()` | Removes `.enc`, `GARMIN_TOKEN_DIR`, and enc_key from WCM |
| `_clear_token_dir()` | Removes `GARMIN_TOKEN_DIR`. Called after token login and on failure |
| `_derive_aes_key(enc_key, salt)` | PBKDF2-HMAC-SHA256, 600k iterations, 32-byte key |

---

## `garmin_validator.py`

| Function | Purpose |
|---|---|
| `validate(raw)` | Validates raw dict against cached schema. Returns `{"status", "schema_version", "timestamp", "issues"}`. Never modifies input |
| `reload_schema()` | Reloads `garmin_dataformat.json` from disk — called by self-healing loop on version mismatch |
| `current_version()` | Returns currently cached schema version string |

**Issue types:**

| Type | Trigger | Severity | Status impact |
|---|---|---|---|
| `missing_required` | Required field absent or wrong type | `critical` | `critical` |
| `type_mismatch` | Known field present but wrong type | `critical` / `warning` | depends |
| `missing_optional` | Optional field absent | `info` | none |
| `unexpected_field` | Field not in schema | `warning` | `warning` |

Schema cached at module import. Leaf node.

---

## `garmin_normalizer.py`

| Function / Constant | Purpose |
|---|---|
| `CURRENT_SCHEMA_VERSION` | int — summary schema version. Increment on field changes |
| `normalize(raw, source)` | Entry point. `source`: `"api"` or `"bulk"` |
| `summarize(raw)` | Produces compact daily summary. Writes `schema_version` into every file |
| `_normalize_api(raw)` | Normalises Garmin API raw dict |
| `_normalize_import(raw)` | Normalises bulk import raw dict. Remaps HR aggregate fields |
| `safe_get(d, *keys, default)` | Safe nested dict traversal |
| `_parse_list_values(lst, dict_key)` | Extracts numeric values from list-of-dicts or `[ts, val]` pairs |

---

## `garmin_writer.py`

| Function | Purpose |
|---|---|
| `write_day(normalized, summary, date_str)` | Sole write authority for `raw/` and `summary/`. Returns `bool` |
| `read_raw(date_str)` | Reads raw file for a date. Used by self-healing loop only. Returns `{}` on failure |

---

## `garmin_quality.py`

| Function | Purpose |
|---|---|
| `QUALITY_LOCK` | `threading.Lock()` — acquire around all load-modify-save sequences |
| `assess_quality(raw)` | Returns `"high"` / `"medium"` / `"low"` / `"failed"`. Pure function |
| `assess_quality_fields(raw)` | Returns per-endpoint quality dict. Pure function |
| `_upsert_quality(data, day, quality, reason, written, source, fields, validator_result)` | Adds or updates day entry. Downgrade protection: `high` stays `high` |
| `get_archive_stats(quality_log_path)` | Returns GUI stats dict: `total`, `high`, `medium`, `low`, `failed`, `recheck`, `date_min`, `date_max`, `coverage_pct`, `last_api`, `last_bulk` |
| `get_low_quality_dates(folder, known_dates)` | Scans `raw/` for files not in quality log |
| `_set_first_day(data, client)` | Determines and persists `first_day`. Never overwrites existing value |
| `cleanup_before_first_day(data, dry_run)` | Removes files and log entries before `first_day` |

**Quality levels:**

| Level | Meaning | `recheck` default |
|---|---|---|
| `high` | Intraday data present | `false` — never re-downloaded |
| `medium` | Daily aggregates only — as good as it gets for older data | `false` |
| `low` | Minimal data | `true` until `LOW_QUALITY_MAX_ATTEMPTS`, then `false` |
| `failed` | API error — no file | `true` until successful |

---

## `garmin_sync.py`

| Function | Purpose |
|---|---|
| `resolve_date_range(first_day)` | Returns `(start, end)` based on `cfg.SYNC_MODE` |
| `get_local_dates(folder, recheck_dates)` | Returns set of dates with local data |
| `date_range(start, end)` | Generator — yields every `date` from `start` to `end` inclusive |

---

## `garmin_collector.py`

| Function | Purpose |
|---|---|
| `main()` | Full sync orchestration: dirs → session log → quality load → login → devices → first_day → date resolution → fetch loop → save |
| `_process_day(client, date_str)` | Validate → fetch → normalize → summarize → assess → write. Returns `(label, written, fields, val_result)` |
| `run_import(path, progress_callback)` | Bulk import orchestration via `garmin_import.load_bulk()`. Returns `{"ok", "skipped", "failed"}` |
| `_run_self_healing(quality_data)` | Revalidates days with stale schema version against local `raw/` files — no API call |
| `_start_session_log()` | Opens session log file. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if errors present |

---

## `garmin_import.py`

| Function | Purpose |
|---|---|
| `load_bulk(path)` | Opens Garmin GDPR export ZIP or folder. Yields one raw dict per day |
| `parse_day(entries, date_str)` | Assembles canonical raw dict from export entries |

**Supported export files:**

| File | Location in export | Content |
|---|---|---|
| `UDSFile_*.json` | `DI-Connect-Aggregator/` | Steps, HR, calories, stress |
| `*_sleepData.json` | `DI-Connect-Wellness/` | Sleep stage durations |
| `TrainingReadinessDTO_*.json` | `DI-Connect-Metrics/` | Training readiness |
| `*_summarizedActivities.json` | `DI-Connect-Fitness/` | Activity summaries |

**Not available in bulk export (API only):** intraday HR, stress curve, body battery curve, SpO2 series, respiration series, HRV details, training status. Bulk data always results in `medium` or `low` quality — never `high`.

---

## `garmin_utils.py`

Leaf node — no project-module imports.

| Function | Purpose |
|---|---|
| `parse_device_date(val)` | Converts device date to `YYYY-MM-DD`. Handles ISO strings and Unix timestamps |
| `parse_sync_dates(raw)` | Parses comma-separated date string into sorted list of `date` objects |

---

## `garmin_dataformat.json`

Schema for `garmin_validator.py`. Located at `garmin/garmin_dataformat.json`.

**Current version:** `1.0`

| Field | Type | Required |
|---|---|---|
| `date` | str | ✅ |
| `sleep` | dict | — |
| `stress` | dict | — |
| `body_battery` | dict | — |
| `heart_rates` | dict | — |
| `respiration` | dict | — |
| `spo2` | dict | — |
| `stats` | dict | — |
| `user_summary` | dict | — |
| `training_status` | dict | — |
| `training_readiness` | dict | — |
| `hrv` | dict | — |
| `race_predictions` | dict | — |
| `max_metrics` | dict | — |
| `activities` | list | — |

---

## Data structures

### `quality_log.json`

```json
{
  "first_day": "2021-05-10",
  "devices": [{"name": "...", "id": 0, "first_used": "...", "last_used": "..."}],
  "days": [
    {
      "date": "2025-11-15",
      "quality": "high",
      "reason": "Quality: high",
      "write": true,
      "source": "api",
      "recheck": false,
      "attempts": 0,
      "last_checked": "2026-03-22",
      "last_attempt": "2026-03-22T14:32:11",
      "validator_result": "ok",
      "validator_issues": [],
      "validator_schema_version": "1.0"
    }
  ]
}
```

### Summary JSON (`summary/garmin_YYYY-MM-DD.json`)

| Field | Description |
|---|---|
| `date` | ISO date string |
| `generated_by` | Always `"garmin_normalizer.py"` |
| `sleep` | Duration, stages, score, SpO2, HRV |
| `heartrate` | Resting, max, min, average BPM |
| `stress` | Stress average/max, Body Battery max/min/end |
| `day` | Steps, calories, intensity minutes, distance |
| `training` | Readiness, status, load, VO2max |
| `activities` | List of activity objects |

---

## `garmin_app.py` / `garmin_app_standalone.py`

| Function | Purpose |
|---|---|
| `_build_env(s, refresh_failed)` | Builds full ENV dict for subprocess |
| `_apply_env(s, refresh_failed)` | Writes directly to `os.environ` (standalone only) |
| `_check_failed_days_popup(...)` | Shows Ja/Nein popup for failed/low days with `recheck=true` |
| `_clean_archive()` | Removes files before `first_day` after confirmation |
| `_prompt_enc_key(mode)` | Modal encryption key input — `"setup"` or `"recovery"` |
| `_prompt_token_expired()` | Warning popup for 429 risk on SSO fallback |
| `_reset_token()` | Clears encrypted token and resets lamp |
| `_toggle_log_level()` | Switches GUI log display between INFO and DEBUG |
| `_toggle_timer()` | Starts or stops background timer |
| `_timer_loop(generation)` | Main timer loop — Repair → Quality → Fill cycle |
| `_copy_last_error_log()` | Copies most recent fail log to clipboard |
