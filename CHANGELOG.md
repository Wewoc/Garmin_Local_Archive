# Garmin Local Archive — Changelog

---

## v1.3.4 — API Structure Validation

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
- `garmin_app.py` / `garmin_app_standalone.py` — "→ Open README" link added next to "Request export at garmin.com". Opens `README_APP.md` / `README_APP_Standalone.md` in the system default text editor.

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
```

---

**REFERENCE** — Zeile 305, `_normalize_import` Beschreibung:

Alt:
```
| `_normalize_import(raw)` | Placeholder for bulk import normalisation — not implemented in v1.2.0 |
```

Neu:
```
| `_normalize_import(raw)` | Normalises a raw dict from `garmin_import.parse_day()`. Applies type validation (same as `_normalize_api()`) and remaps HR aggregate fields from `user_summary` into `heart_rates` so `summarize()` can read them — `heart_rates` key is not present in bulk raw dicts |

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
