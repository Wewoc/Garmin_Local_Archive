# Garmin Local Archive — Garmin Pipeline Reference

Technical reference for the Garmin data pipeline (`garmin/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.

---

## Pipeline overview

```
garmin_app.py (GUI)
  └── _build_env() / _apply_env()
        └── garmin_collector.main()
              ├── garmin_quality._load_quality_log()
              ├── garmin_quality._backfill_quality_log()   (first run only)
              ├── garmin_quality.get_low_quality_dates()
              ├── bulk recheck flagging                    (source:bulk + ≤180d → recheck:true)
              ├── garmin_api.login()
              ├── garmin_api.get_devices()
              ├── garmin_quality._set_first_day()
              ├── garmin_sync.get_local_dates()            (bulk_upgrade_dates always excluded)
              ├── garmin_sync.resolve_date_range()
              ├── garmin_collector._run_self_healing()
              ├── per day:
              │     garmin_collector._fetch_and_assess()
              │       ├── garmin_api.fetch_raw()
              │       ├── garmin_validator.validate()      → label:failed if critical
              │       ├── garmin_normalizer.normalize()
              │       ├── garmin_normalizer.summarize()
              │       └── garmin_quality.assess_quality()  ← pure, no validator param
              │     [range-warning downgrade if >3 out_of_range]
              │     downgrade check                        → skip write if new < existing
              │     garmin_collector._write_assessed()     → skipped on downgrade
              │     garmin_quality.record_attempt()        (upsert + save, atomic)
              └── garmin_quality._save_quality_log()       (final safety-net save after loop)
```

**Invariants:**
- `garmin_validator.py` always runs before `garmin_normalizer.py`
- `garmin_writer.py` is sole write authority for `raw/` and `summary/`
- `garmin_quality.py` is sole write authority for `quality_log.json`
- `garmin_backup.py` is sole write authority for `garmin_data/backup/`
- `garmin_mirror.py` is sole owner of the mirror operation
- `garmin_utils.py` and `garmin_validator.py` are leaf nodes — no project-module imports
- `QUALITY_LOCK` must be held around all load-modify-save sequences
- `fetch_raw()` returns `(raw, failed_endpoints)` — never raises
- `_process_day()` returns `(label, written, fields, val_result)` — never raises
- `garmin_backup` must never import `garmin_writer` or `garmin_quality` — avoids circular imports

---

## Documented Exceptions

Intentional deviations from the invariants above. Each exception is stable by design — not a TODO.

| Exception | Module | Reason |
|---|---|---|
| `regenerate_summaries.py` writes directly to `summary/` | `export/regenerate_summaries.py` | Maintenance utility — runs offline, outside pipeline. `garmin_writer` is not importable in that context. Acceptable: one-off backfill, not a runtime path. |
| `garmin_validator.py` imports `garmin_config` | `garmin/garmin_validator.py` | `garmin_config` is a pure constants module with no project-module imports. `garmin_validator` needs `DATAFORMAT_FILE` path. Leaf-node status refers to pipeline modules — `garmin_config` is infrastructure. |
| Controller timer functions read `quality_log.json` directly | `app/garmin_app_controller.py` — `timer_run_repair`, `timer_run_bulk_recheck`, `timer_run_quality` | Read-only analytical fast-path. No mutation, no ownership transfer, no `QUALITY_LOCK` required. `garmin_quality` provides no filtered-list API for these queries; adding one would inflate the module into a query gateway. |

---

## `garmin_config.py`

Pure constants module — no functions. See `REFERENCE_GLOBAL.md` for full constant list.

---

## `garmin_api.py`

| Function / Symbol | Purpose |
|---|---|
| `GarminLoginError` | Exception raised on unrecoverable login failure. Replaces `sys.exit(1)` |
| `login(on_key_required, on_token_expired, on_mfa_required, on_sso_required)` | Logs in to Garmin Connect. Tries saved token first, falls back to SSO. MFA via callback. `on_sso_required` blocks Path 3 until user confirms — `None` (headless/standalone) starts SSO automatically. Returns client or `None` if cancelled. Raises `GarminLoginError` on failure |
| `api_call(client, method, *args, label)` | Single API call with random delay and stop-check. Returns `(data, success)` |
| `fetch_raw(client, date_str)` | Calls all 14 Garmin API endpoints. Returns `(raw: dict, failed_endpoints: list[str])` |
| `get_devices(client)` | Fetches registered device list. Returns sorted list |
| `_is_stopped()` | Returns `True` if stop event is set. Safe to call without injection |

**Auth token flow:**

- Path 1 (token valid): `load_token()` → `Garmin()` + `login(token_dir)` → `_clear_token_dir()` → probe call — 429/403 on probe → `GarminLoginError` (no SSO fallback)
- Path 2 (token expired): `clear_token()` → `on_token_expired()` → Path 3
- Path 3 (SSO): `on_sso_required()` → confirm → `generate_enc_key()` (auto, no dialog) → `Garmin(email, pw, prompt_mfa=on_mfa_required)` → `login(token_dir)` → `save_token()` (garminconnect ≥ 0.3.0)
- Path 3b (key missing): `on_key_required()` → store key → retry Path 1

---

## `garmin_security.py`

**Design note:** `garmin_config` is imported lazily inside each function (not at module level).
This ensures `cfg` paths always reflect the current state after `importlib.reload(cfg)` in the GUI —
avoiding stale paths when `GARMIN_OUTPUT_DIR` is set after the module was first imported.

| Function | Purpose |
|---|---|
| `get_enc_key()` | Reads encryption key from Windows Credential Manager. Returns `None` if not found |
| `store_enc_key(enc_key)` | Writes encryption key to WCM. Returns `bool` |
| `generate_enc_key()` | Generates a random 256-bit key via `os.urandom(32)`, stores as hex string in WCM. Called automatically on first setup (Path 3). Returns `bool` |
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
| `write_day(normalized, summary, date_str)` | Sole write authority for `raw/` and `summary/`. Triggers `garmin_backup.backup_raw()` after successful write (lazy import, failure non-fatal). Returns `bool` |
| `read_raw(date_str)` | Reads raw file for a date. Used by self-healing loop only. Returns `{}` on failure |
| `read_summary(date_str)` | Reads summary file for a date. Used by schema migration loop. Returns `{}` on failure |

---

## `garmin_quality.py`

| Function | Purpose |
|---|---|
*Implementation split into `garmin/quality/_io.py`, `_assess.py`, `_scan.py`, `_maint.py`, `_stats.py` — all symbols re-exported from this facade. Callers import from `garmin_quality` as before.*

| `QUALITY_LOCK` | `threading.Lock()` — acquire around all load-modify-save sequences |
| `assess_quality(raw)` | Returns `"high"` / `"medium"` / `"low"` / `"failed"`. Pure function |
| `assess_quality_fields(raw)` | Returns per-endpoint quality dict. Pure function |
| `record_attempt(data, day, label, reason, written, source, fields, validator_result)` | Public API — atomically calls `_upsert_quality` + `_save_quality_log`. Caller must hold `QUALITY_LOCK`. Use instead of the pair directly — except where manual state patch follows upsert (`# INTENTIONAL DIRECT CALL`) |
| `_upsert_quality(data, day, quality, reason, written, source, fields, validator_result)` | Adds or updates day entry. Downgrade protection: `high` stays `high` |
| `get_archive_stats(quality_log_path)` | Returns GUI stats dict: `total`, `high`, `medium`, `low`, `failed`, `recheck`, `missing`, `date_min`, `date_max`, `coverage_pct`, `last_api`, `last_bulk`, `integrity_warnings` |
| `_compute_checksum(data)` | SHA-256 over stable core fields (`date`, `write`, `quality`, `source`) of all day entries. Extended in v1.5.5. Migration bridge: `_compute_checksum_legacy()` (TODO: remove after v1.6) |
| `_compute_checksum_legacy(data)` | Pre-v1.5.5 algorithm (`date` + `write` only). Used once on load to detect planned upgrade — never for new saves |
| `_save_defective_log(data)` | Saves defective quality_log state to `AUTORESTORE_DIR` before auto-restore. Best-effort |
| `_load_quality_log()` | Now returns `integrity_warnings: list[str]` — empty if checksum OK, year labels if mismatch |
| `_save_quality_log(data, skip_backup)` | `skip_backup=True` suppresses backup trigger. Default `False` triggers `garmin_backup.backup_quality_log()` |
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
| `main()` | Full sync orchestration: dirs → session log → quality load → bulk upgrade flagging → login → devices → first_day → date resolution → fetch loop → save |
| `_fetch_and_assess(client, date_str)` | Fetch → validate → normalize → assess. No file writes. Returns `(label, normalized, summary, fields, val_result)` |
| `_check_downgrade(new_label, existing_entry)` | Compares new quality label against stored entry. Returns `(is_downgrade, existing_label, existing_source)` |
| `_write_assessed(normalized, summary, date_str, label)` | Writes pre-assessed day to disk. Returns `bool` |
| `run_import(path, progress_callback)` | Bulk import orchestration via `garmin_import.load_bulk()`. Returns `{"ok", "skipped", "failed"}` |
| `_run_self_healing(quality_data)` | Revalidates days with stale schema version against local `raw/` files — no API call |
| `_run_schema_migration(quality_data)` | Rewrites outdated summary files from raw when `GARMIN_SCHEMA_MIGRATE=1`. No API call. Raw files unchanged. Log output per day `[i/total]` |
| `_start_session_log()` | Opens session log file. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if errors present |

**Bulk recheck logic:**

All days with `source: bulk` + date ≤ 180 days old are automatically flagged `recheck: true` on every startup (Step 3) — quality is irrelevant, source is the trigger. After 180 days Garmin degrades intraday data permanently; the local raw copy is then the only high-resolution source. In Step 7, bulk recheck days are collected into `bulk_upgrade_dates` and always excluded from `local_dates` — regardless of `REFRESH_FAILED`.

**Downgrade during bulk recheck:** If the API result is inferior to the existing bulk entry, `attempts` is incremented manually after `_upsert_quality()`. After 2 failed attempts `recheck` is set to `false` — the bulk quality is accepted as final.

**Downgrade protection:**

After `_fetch_and_assess()`, `_check_downgrade()` compares the new label against the existing quality log entry using rank `high=3 > medium=2 > low=1 > failed=0`. If the API result is inferior: file is not written, existing entry is preserved. If equal or better: `_write_assessed()` is called and entry is upserted as `source: api`.

**Resume safety:**

`_save_quality_log()` is called after every individual day — in all paths (upgrade, downgrade, error). Every successfully processed day is an atomic resume point. Stopping mid-run resumes from the next unprocessed day on the next start.

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

## `garmin_backup.py`

Sole Owner of `garmin_data/backup/`. Does not import `garmin_writer` or `garmin_quality`.

| Function | Purpose |
|---|---|
| `backup_raw(date_str)` | Copies `garmin_raw_YYYY-MM-DD.json` into `backup/raw/YYYY-MM/`. Triggers `_consolidate_raw_months()`. Returns `bool` |
| `backup_quality_log()` | Creates monthly snapshot of `quality_log.json` as `quality_log_YYYY-MM.zip`. Triggers yearly consolidation |
| `restore_quality_log()` | Restores from latest valid monthly ZIP. Returns loaded `dict` or `None` |
| `check_raw_integrity()` | Compares `write=True` quality log entries vs. existing raw files. Returns `{"missing_days", "no_backup", "total_checked"}` |
| `restore_raw_days(date_strs)` | Restores raw files from backup (dir first, then ZIP). Returns `{"restored", "failed"}` |
| `_consolidate_raw_months(current_month)` | ZIPs completed month dirs, deletes dir after ZIP verified |
| `_consolidate_log_years(current_year)` | Creates `quality_log_YYYY.zip` for completed years without yearly ZIP |
| `_zip_contains(zip_path, filename)` | Returns `True` if filename exists in ZIP. Silent on error |
| `check_raw_backfill_needed()` | Returns count of raw files without backup. Fast, no copy. Returns 0 if complete |
| `backfill_raw()` | Copies all unbackedup raw files into `backup/raw/`. Consolidates completed months. Idempotent. Returns `{"copied", "skipped", "errors"}` |

**Backup directory structure:**
```
garmin_data/backup/
  log/         — quality_log_YYYY-MM.zip, quality_log_YYYY.zip
  raw/         — YYYY-MM/ (open month), raw_backup_YYYY-MM.zip (completed)
  autorestore/ — auto-restore-YYYY-MM-DD.zip (defective log before restore)
```

---

## `garmin_mirror.py`

Sole Owner of the mirror operation. No `garmin_config` import — all paths from caller.

| Function | Purpose |
|---|---|
| `run_mirror(source_dir, mirror_dir)` | Mirrors `source_dir` → `mirror_dir`. Returns `{"copied", "deleted", "skipped", "errors", "ok", "spot_check"}` |
| `is_reachable(mirror_dir)` | Returns `True` if `mirror_dir` is set and exists. Used for button state |
| `_collect_files(root)` | Returns `{relative_path → filesize}`. Skips `EXCLUDE_DIRS` |
| `_remove_empty_dirs(root)` | Removes empty subdirectories bottom-up. Silent on error |
| `_run_spot_check(source_dir, mirror_dir, source_files)` | CRC32 spot-check: up to 10 random files compared after copy phase. Returns `{"sampled": N, "mismatches": M}` |

`EXCLUDE_DIRS = {"__pycache__", "garmin_token"}`

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
  "_checksum": "sha256hex...",
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
| `sleep` | Duration, stages, score, SpO2, HRV, sleep_score_feedback, sleep_score_qualifier |
| `heartrate` | Resting, max, min, average BPM |
| `stress` | Stress average/max, Body Battery max/min/end |
| `day` | Steps, calories, intensity minutes, distance |
| `training` | Readiness, status, load, VO2max |
| `activities` | List of activity objects |

---

## `garmin_map.py`

Field resolver for the dashboard broker architecture. Called exclusively by `field_map.py` — never directly by specialists.

### `_FIELD_MAP` — descriptor types

Each field in `_FIELD_MAP` uses one of three descriptor types:

| Type | Key | Resolution | Source |
|---|---|---|---|
| `daily` | `("section", "key")` | daily | `summary/garmin_YYYY-MM-DD.json` |
| `intraday` | `("section", "array_key", extract_dict)` | intraday | `raw/garmin_raw_YYYY-MM-DD.json` |
| `raw_pct` | `("section", "dto_key", "seconds_key", "total_key")` | daily | `raw/garmin_raw_YYYY-MM-DD.json` |

`raw_pct` is used for fields that require percentage calculation from two seconds-based values in the raw file. `get()` detects `raw_pct` and bypasses the standard daily/intraday resolution fallback logic.

### Registered fields

| Generic field | Type | Source path | Notes |
|---|---|---|---|
| `hrv_last_night` | daily | `sleep.hrv_last_night_ms` | ms |
| `resting_heart_rate` | daily | `heartrate.resting_bpm` | bpm |
| `spo2_avg` | daily | `sleep.spo2_avg` | % |
| `sleep_duration` | daily | `sleep.duration_h` | hours |
| `body_battery_max` | daily | `stress.body_battery_max` | 0–100 |
| `stress_avg` | daily | `stress.stress_avg` | 0–100 |
| `vo2max` | daily | `training.vo2max` | — |
| `sleep_score_feedback` | daily | `sleep.sleep_score_feedback` | z.B. `POSITIVE_DEEP` |
| `sleep_score_qualifier` | daily | `sleep.sleep_score_qualifier` | z.B. `FAIR`, `EXCELLENT` |
| `sleep_deep_pct` | raw_pct | `sleep.dailySleepDTO`: `deepSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_light_pct` | raw_pct | `sleep.dailySleepDTO`: `lightSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_rem_pct` | raw_pct | `sleep.dailySleepDTO`: `remSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_awake_pct` | raw_pct | `sleep.dailySleepDTO`: `awakeSleepSeconds / sleepTimeSeconds * 100` | % |
| `heart_rate_series` | intraday | `heart_rates.heartRateValues` | `[{"ts", "value"}]` |
| `stress_series` | intraday | `stress.stressValuesArray` | offset applied |
| `spo2_series` | intraday | `spo2.spO2HourlyAverages` | — |
| `body_battery_series` | intraday | `stress.bodyBatteryValuesArray` | — |
| `respiration_series` | intraday | `respiration.respirationValuesArray` | — |

**Architecture boundary:** Any Garmin-internal key (`section.field`, `dailySleepDTO`, etc.) appearing outside `garmin_map.py` is an architecture violation — detectable by name format alone.

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
| `_test_conn()` | Inner function in `_timer_loop()` — uses `garmin_api.login()` with full ENV setup and reload. No raw SSO. |
| `_reset_token()` | Clears encrypted token and resets lamp |
| `_toggle_log_level()` | Switches GUI log display between INFO and DEBUG |
| `_toggle_timer()` | Starts or stops background timer |
| `_timer_loop(generation)` | Main timer loop — Bulk Recheck (priority) → Repair → Quality → Fill cycle |
| `_timer_run_bulk_recheck(s)` | Returns bulk recheck candidates: `source=bulk` + `recheck=True` + ≤180 days, oldest first. Returns `None` if empty |
| `_copy_last_error_log()` | Copies most recent fail log to clipboard |
