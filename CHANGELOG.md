# Garmin Local Archive — Changelog

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
