# Garmin Local Archive — Garmin Pipeline Reference

Technical reference for the Garmin data pipeline (`garmin/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.
For the broker request/response contract (`field_map.get()`) see `REFERENCE_BROKER.md`.

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
              │     garmin_quality._save_quality_log()     (per-day crash-resilience, skip_backup=True)
              └── garmin_quality._save_quality_log()       (final safety-net save after loop)
```

**Invariants:**
- `garmin_validator.py` always runs before `garmin_normalizer.py`
- `garmin_writer.py` is sole write authority for `raw/` and `summary/`
- `garmin_quality.py` is sole write authority for `quality_log.json`
- `garmin_backup.py` is sole write authority for `garmin_data/backup/`
- `garmin_source_writer.py` is sole write authority for `garmin_data/source/` and `source_api_log.json` (v1.6.0.2 — genuinely enforced since v1.6.0.4.6: mirror bypass closed)
- `source/` contains exclusively live API responses — bulk import never writes to `source/`, not even during backfill (v1.6.0.2)
- `source/` files with `intraday_present=True` are never overwritten by a degraded response — Conservative guard in `write_source()` (v1.6.0.4.6)
- `garmin_collector.py` is the stop-event orchestrator (v1.5.6.3) — `set_stop_event(ev)` registers the event on the collector and distributes it to `garmin_api` in one call. The GUI calls `main(stop_event=ev)`; no module ever reads `_STOP_EVENT` via `globals()`
- `garmin_mirror.py` is sole owner of the mirror operation — delegates to `garmin_container.py` for container creation. `is_import_ready()` removed (v1.5.6.2) — import source selected via file picker, not stored path
- `garmin_container.py` is sole owner of `mirror.gla` — no other module reads or writes the container file directly
- `garmin_import_mirror.py` is sole owner of the mirror import operation — orchestrates only, never writes directly
- `normalize()` is never called during mirror import — raw in mirror is already normalized
- Container keys use POSIX forward-slash separators (`rel.as_posix()`) — cross-platform consistency
- `mirror.gla` is written atomically: `mirror.gla.tmp` → `fsync()` → `os.replace()` — interrupted writes never produce a corrupt container
- Password for `lock()` may be cached in WCM (user opt-in). Password for `unlock_meta()` / `fulfill_order()` is entered via `QFileDialog` file picker — no path configuration required on import device
- `garmin_utils.py` and `garmin_validator.py` are leaf nodes — no project-module imports
- `garmin_silo_check.py` is a leaf node — imports only `garmin_config` + stdlib. Read-only. No writes, no imports of write modules (v1.6.0.4.7)
- `QUALITY_LOCK` must be held around all load-modify-save sequences
- `fetch_raw()` returns `(raw, failed_endpoints)` — never raises
- `_fetch_and_assess()` returns `(label, normalized, summary, fields, val_result)` — never raises
- `garmin_backup` must never import `garmin_writer` or `garmin_quality` — avoids circular imports
- `normalize()` is never called during mirror import — raw in mirror is already normalized
- `garmin_live_fetch.py` is sole write authority for `garmin_data/live/` (v1.6.5) — single-file snapshot of the current day, no history, overwritten on every fetch. No `quality_log.json` contact, no validator/normalizer
- `garmin_health_map.py` shifts every intraday timestamp to the recording device's local time, derived per-day from Garmin's own `startTimestampGMT`/`Local` section metadata — never the system clock, never a hardcoded `zoneinfo` zone (v1.6.5.6, see "Timestamp handling" below)
- `garmin_api_capability.py` is sole write authority for `garmin_api_capability_config.json` — leaf node, imports only `garmin_config` + stdlib (v1.6.8)
- The 15 baseline `fetch_raw()` endpoints always run — the API-Capability-Scan config can never disable them, only add optional candidates (v1.6.8, Archive-First)
- API-Capability-Scan candidates are double-gated before joining a sync run: `enabled_by_user == True` **and** `status == "found"` — a hand-edited config file can never activate an endpoint that was never confirmed present (v1.6.8)
- Capability config is read once per sync run as an immutable snapshot, inside the same `QUALITY_LOCK` the sync loop already holds — `run_capability_scan()` reuses this same lock rather than introducing a second one: it never writes `quality_log.json` itself, but does share the Garmin client with the sync, and the two must never run concurrently (v1.6.8)
- API-Capability-Scan candidates reach `summary/` — and therefore `get()`/`list_fields()` — only if `garmin_normalizer.summarize()` is explicitly extended for that candidate; landing in `raw/` alone is not sufficient, `summarize()` is a fixed field list, not a generic passthrough. Six candidates are wired this way: `body_weight`, `calories_resting` (v1.6.8 pilot), `hydration_ml`, `endurance_score`, `hill_score`, `fitness_age` (v1.6.8 Session 4). The remaining 13 are exposed unprocessed via `get_raw()`/`list_raw_fields()` instead — see "Raw-passthrough fields" below — rather than left archived-but-unreachable
- `list_fields(active_only=True)` additionally excludes API-Capability-Scan candidate fields whose endpoint is not `enabled_by_user` in the capability config — used by the Custom Dashboard field picker and Explorer (v1.6.8 Session 4, "Governance B"). Baseline fields and raw-passthrough fields are unaffected: baseline fields are absent from the gating dict by design, raw-passthrough fields aren't part of `list_fields()`'s registry at all

---

## `garmin_app_controller.py`

Layer 3 — no tkinter, no Qt, no GUI imports. Sits between the GUI layer and
the Garmin pipeline: owns ENV construction, archive stats, connection
testing, and the Background Timer's candidate logic. No file ownership of
its own — reads and decides, never writes. See also `GLA_HANDBUCH.md` §14.

| Function | Purpose |
|---|---|
| `build_env_dict(s, refresh_failed=False)` | Pure ENV dict builder — no side effects, no `os.environ` write. Caller decides how to apply (`Popen env=` or `os.environ`) |
| `check_connection(s, callbacks)` | Tests Garmin Connect connectivity in a background thread. Communicates exclusively via callbacks — no GUI access, no `self.after()` |
| `check_integrity(s)` | Runs `garmin_backup.check_raw_integrity()`. Returns `{"missing_days", "no_backup", "total_checked", "error"}` — `error` passed through verbatim from `check_raw_integrity()` or set locally if the ENV/config setup itself fails (v1.6.5.7, Netz 3 Kandidat 2) |
| `check_mirror(s)` | Returns `True` if the configured `mirror_dir` is reachable |
| `get_archive_stats(base_dir)` | Wraps `garmin_quality.get_archive_stats()`. Empty dict on any failure |
| `get_source_stats(s)` | `{"total", "present"}` — all `source/` files vs. those within the last 180 days. INTENTIONAL DIRECT READ |

**Timer-Modi und ihre Kandidaten-Funktionen** — sechs Modi, Priorität von oben nach unten:

| Modus | Funktion | Kandidaten |
|---|---|---|
| Bulk Recheck | `timer_run_bulk_recheck(s)` | `source="bulk"` + `recheck=True` + ≤180 Tage, älteste zuerst |
| Repair | `timer_run_repair(s)` | `quality="failed"` + `recheck=True` |
| Quality | `timer_run_quality(s)` | `quality="standard"` + `recheck=True` + `source≠"bulk"` + ≤180 Tage |
| Fill | `timer_run_fill(s)` | Tage im Datumsbereich ohne Raw-Datei in `raw/` |
| Source Backfill | `timer_run_source_backfill(s)` | API-Tage (≤180d) ohne `source/`-Datei, kein Bulk |
| Steps Backfill | `timer_run_steps_backfill(s)` | `quality="high"` + `source="api"` + `"steps" not in fields` + ≤140 Tage (Garmin-Intraday-Degradierungsfenster). Self-terminierend — Kandidat verschwindet automatisch sobald `steps` im `fields`-Dict der Tages-Entry steht (v1.6.3) |

All six candidate functions return a sorted `list[date]` (oldest first) or
`None` if there is nothing to do. `panel_timer.py`'s `_timer_loop()` cycles
through them by priority and dispatches the picked batch to
`garmin_collector.py` via `GARMIN_SYNC_DATES` + a mode-specific ENV flag.

---

## Documented Exceptions

Intentional deviations from the invariants above. Each exception is stable by design — not a TODO.

| Exception | Module | Reason |
|---|---|---|
| `regenerate_summaries.py` writes directly to `summary/` | `export/regenerate_summaries.py` | Maintenance utility — runs offline, outside pipeline. `garmin_writer` is not importable in that context. Acceptable: one-off backfill, not a runtime path. |
| `regenerate_raw.py` reads/writes `quality_log.json` directly via `_load_quality_log`/`_save_quality_log` | `export/regenerate_raw.py` | Maintenance utility — runs offline, outside the live pipeline, analogous to `regenerate_summaries.py`. Uses `garmin_writer.write_day()` for `raw/`/`summary/` writes (unlike `regenerate_summaries.py`); direct quality-log access is needed to apply downgrade-protected replay. `QUALITY_LOCK` is held correctly around both read and write. |
| `garmin_validator.py` imports `garmin_config` | `garmin/garmin_validator.py` | `garmin_config` is a pure constants module with no project-module imports. `garmin_validator` needs `DATAFORMAT_FILE` path. Leaf-node status refers to pipeline modules — `garmin_config` is infrastructure. |
| Controller timer functions read `quality_log.json` directly | `app/garmin_app_controller.py` — `timer_run_repair`, `timer_run_bulk_recheck`, `timer_run_quality`, `timer_run_source_backfill`, `timer_run_steps_backfill` | Read-only analytical fast-path. No mutation, no ownership transfer, no `QUALITY_LOCK` required. `garmin_quality` provides no filtered-list API for these queries; adding one would inflate the module into a query gateway. |

---

## `garmin_source_quality.py`

Sole Owner of source quality assessment logic. **Leaf-Node — stdlib only** (no `garmin_config`, no pipeline imports).
Called by `garmin_source_writer` to guard `write_source()` against overwriting high-resolution source files.

| Function | Purpose |
|---|---|
| `assess_source(raw_data)` | Assesses whether a raw API response contains intraday data. Checks `heartRateValues`, `stressValuesArray`, `bodyBatteryValuesArray`. Returns `{"intraday_present": bool}` |
| `assess_source_from_file(source_path)` | Reads existing source file from disk and assesses it. Returns `None` if absent. Returns `{"unreadable": True}` if file exists but cannot be read/parsed (v1.6.0.4.9). Returns `{"intraday_present": bool}` on success |
| `compare_source(existing_assessment, new_assessment)` | Conservative guard decision. Returns `"write"` \| `"skip"` \| `"skip_warn"`. Truth table: None (absent) → write; `{"unreadable": True}` → skip_warn (v1.6.0.4.9); intraday absent → write; intraday present + new present → skip; intraday present + new absent → skip_warn |

---

## `garmin_source_writer.py`

Sole Owner of `garmin_data/source/` and `source_api_log.json`. Depends on `garmin_source_quality` + `garmin_config` + stdlib.
`garmin_config` and `garmin_source_quality` imported lazily inside each function — same pattern as `garmin_security.py`.
After each actual write in `write_source()`: lazy import of `garmin_backup_source.backup_source()` — non-fatal.
No longer a Leaf-Node (v1.6.0.4.6) — imports `garmin_source_quality` for the write guard.

| Function | Purpose |
|---|---|
| `write_source(raw_data, date_str)` | Writes unmodified API response to `source/garmin_source_YYYY-MM-DD.json`. Guard: reads existing file → `assess_source_from_file` → `assess_source` → `compare_source` → write / skip / skip_warn. Atomic: `.tmp` → `fsync` → `os.replace`. Triggers `backup_source()` only on actual write. Returns `bool`. Non-fatal |
| `update_log(date_str, val_result, endpoints_fetched, endpoints_failed, size_bytes, raw_data=None)` | Upserts entry in `source_api_log.json`. Stores `intraday_present` when `raw_data` provided (via `garmin_source_quality.assess_source()`). Atomic write. Returns `bool`. Non-fatal |

---

## `garmin_silo_check.py`

Read-only drift detection across the data silos. **Leaf-Node — `garmin_config` + stdlib only.**
No writes. No imports of write modules. Repair delegation lives in `panel_archive.py`.

| Function | Purpose |
|---|---|
| `check_silos()` | Scans raw/, summary/, source/, quality_log.json for silo inconsistencies. Returns finding lists, totals, counts, checked_at. Read-only. Lockless (atomic writes guarantee complete-file reads, §9a) |

**Result structure:**

Sole Owner of `garmin_data/backup/source/`. Leaf-Node — only `garmin_config` + stdlib.

**Invariant refinement (v1.6.0.4):**
- `garmin_backup.py` — Sole Owner of `backup/raw/` + `backup/log/` (previously: all of `backup/`)
- `garmin_backup_source.py` — Sole Owner of `backup/source/`

| Function | Purpose |
|---|---|
| `backup_source(date_str)` | Copies `garmin_source_YYYY-MM-DD.json` to `backup/source/`. Called by `garmin_source_writer` after write. Returns `bool`. Non-fatal |
| `backfill_source()` | Copies all source files without a backup copy. One-time operation. Returns `{"copied", "skipped", "failed"}` |
| `check_source_backfill_needed()` | Returns count of source files without backup. Fast check, no copy |

**Constants:**
- `SOURCE_LOG_SCHEMA_VERSION = 1` — increment when log entry structure changes
- `SOURCE_FILE_PREFIX = "garmin_source_"`

**`source_api_log.json` entry format:**

| Function / Symbol | Purpose |
|---|---|
| `GarminLoginError` | Exception raised on unrecoverable login failure. Replaces `sys.exit(1)` |
| `login(on_key_required, on_token_expired, on_mfa_required, on_sso_required)` | Logs in to Garmin Connect. Tries saved token first, falls back to SSO. MFA via callback. `on_sso_required` blocks Path 3 until user confirms — `None` (headless/standalone) starts SSO automatically. Returns client or `None` if cancelled. Raises `GarminLoginError` on failure. **Note:** `support-tools/garmin-login-probe/garmin_login_probe.py` calls this directly with `on_sso_required=lambda: True` — a signature change here requires updating that tool too |
| `api_call(client, method, *args, label)` | Single API call with random delay and stop-check. Returns `(data, success)` |
| `fetch_raw(client, date_str, extra_endpoints=None)` | Calls all 15 Garmin API endpoints, plus any `(method, args, key)` tuples passed via `extra_endpoints`. Stays config-blind — only ever receives a ready-made tuple list. `extra_endpoints` (v1.6.8) — used by `garmin_collector` to append user-enabled API-Capability-Scan candidates; baseline 15 always run regardless. Returns `(raw: dict, failed_endpoints: list[str])` |
| `get_devices(client)` | Fetches registered device list. Returns sorted list |
| `set_stop_event(ev)` | Registers the stop event (`threading.Event` or `None`). Same pattern as `garmin_validator.reload_schema()` — explicit setter, no `globals()` injection |
| `_is_stopped()` | Returns `True` if a registered stop event is set. Safe to call without a registered event |
| `_is_mfa_no_callback_error(e)` | Returns `True` if `e`'s message is garminconnect's exact `"MFA Required but no prompt_mfa mechanism supplied"` string — raised by `client.py::resolve_mfa()` once every login strategy in the 5-strategy chain has required MFA. Extracted as its own function so it's unit-testable with a synthetic exception (v1.6.5.9) |
| `_cause_fields(e)` | Best-effort extraction of `e.__cause__` for `log_token_event()`'s optional extra fields (`cause_type`/`cause_detail`). Returns `{}` if no cause chained. garminconnect's `_load_profile_and_settings()` masks the real failure behind a fixed `"Failed to retrieve social profile"` message after 3 retries — the chained cause often holds the actual reason (v1.6.5.9) |

**Auth token flow:**

- Path 1 (token valid): `load_token()` → `Garmin()` + `login(token_dir)` → `_clear_token_dir()` → probe call — success → `log_token_event("valid", "token_reused")` → return client (v1.6.5.7.1); 429/403 on probe → `log_token_event("blocked", "rate_limited", **_cause_fields(e))` → `GarminLoginError` (no SSO fallback); other probe failure → `log_token_event("invalidated", "rejected_by_garmin", **_cause_fields(e))` → `clear_token()` (cause-chaining added v1.6.5.9)
- Path 2 (token expired): `clear_token()` → `on_token_expired()` → Path 3
- Path 3 headless guard (v1.6.5.9): if `on_mfa_required is None` (no interactive caller — covers both the headless Daily Sync path and the GUI's own background sync subprocess) and `garmin_security.has_unresolved_mfa_block()` is `True` → `GarminLoginError` immediately, no SSO attempt
- Path 3 (SSO): `on_sso_required()` → confirm → `generate_enc_key()` (auto, no dialog) → `Garmin(email, pw, prompt_mfa=_logged_mfa_prompt if on_mfa_required else None)` → `login(token_dir)` → `save_token()` → `log_token_event("created", "sso_login")` (garminconnect ≥ 0.3.0). `_logged_mfa_prompt()` wraps `on_mfa_required` (when set) — logs `log_token_event("mfa", "challenge_presented", solved="yes"|"no")` with the resolved code or cancellation, try/finally so a crash inside the callback is still logged (v1.6.5.9). If MFA is required and no callback is available, `_is_mfa_no_callback_error(e)` detects it in the except-block → `log_token_event("blocked", "mfa_required_no_callback")` instead of the generic failure path (v1.6.5.9)
- Path 3b (key missing): `log_token_event("invalidated", "enc_key_missing_wcm")` → `on_key_required()` → store key → retry Path 1

**Manual reset** (`panel_connection.py::_reset_token()`): `clear_token()` → `log_token_event("invalidated", "manual_reset")` — outside the `login()` flow, GUI button only. Deliberately does NOT clear an unresolved MFA block (v1.6.5.9) — a deleted token says nothing about whether the MFA problem itself is resolved, only a real successful SSO proves that.

---

## `garmin_silo_repair.py`

Headless-callable core for the four repair paths `garmin_silo_check.check_silos()`
detects. Extracted from `panel_archive.py::_on_silo_repair()` (v1.6.5.7) — the
repair logic previously lived only as a Qt-bound closure, uncallable without a
live `PanelArchive`/`QApplication` instance. Not a Leaf-Node — imports the
sole-write-authority modules it delegates to (`garmin_writer`, `garmin_quality`,
`garmin_normalizer`). Never writes files directly itself.

| Function | Purpose |
|---|---|
| `repair_silos(fresh)` | Repairs all four silo-drift categories from `fresh` (the return value of `check_silos()` — caller must re-scan immediately before calling, never act on stale findings). Returns `{"ok", "failed", "items"}` — `items` is one dict per processed date/action (`category`, `date`, `status`, plus category/status-specific extra keys) |

**Delegation per category:**

| # | Finding | Repair |
|---|---|---|
| 1 | `raw_without_quality` | `garmin_quality._backfill_quality_log()` under `QUALITY_LOCK` |
| 3 | `source_without_raw` | In-process replay: `normalize()` → `summarize()` → `assess_quality()` → `write_day()` → `record_attempt()`, under one continuous `QUALITY_LOCK` hold (v1.6.5.7 precondition fix — previously released the lock between load and per-day save, see `CHANGELOG.md`) |
| 5 | `summary_without_raw` | `Path.unlink()` — removes the orphan summary |
| 7 | `raw_without_summary` | Inline `summarize()` + `write_day()` |

`panel_archive.py::_do_repair()` only formats this structured result for the
GUI log — no pipeline logic remains in the panel.

**Test coverage (v1.6.5.8, Netz 2):** all four repair categories now covered
in `test_local.py` Section I — category #1's remaining edge case
(`_backfill_quality_log()` with a non-empty `raw_without_quality`, including
the silent-skip behaviour on a corrupt raw file and the true-error path on a
failed `_save_quality_log()`), and #3/#7's replay path against a
`normalize()`-capable raw-data fixture derived from a real archive file (not
an invented shape — see `KONZEPT_broker_uebersetzungshandbuch.md` for why
that distinction matters). Diagnosed empirically first via the external
`gla-netz2/` workshop before any assertion was written.

---

## `garmin_security.py`

**Design note:** `garmin_config` is imported lazily inside each function (not at module level).
This ensures `cfg` paths always reflect the current state after `importlib.reload(cfg)` in the GUI —
avoiding stale paths when `GARMIN_OUTPUT_DIR` is set after the module was first imported.

| Function | Purpose |
|---|---|
| `get_enc_key_status()` | Sole implementation of the WCM read. Returns `(key, None)` on success or genuine absence, `(None, error_detail)` on a WCM read failure (v1.6.5.7, Netz 3 Kandidat 3) |
| `get_enc_key()` | Thin wrapper around `get_enc_key_status()`, kept for its five existing presence-only callers. Returns `None` if not found (absence or WCM failure — indistinguishable at this level) |
| `store_enc_key(enc_key)` | Writes encryption key to WCM. Returns `bool` |
| `generate_enc_key()` | Generates a random 256-bit key via `os.urandom(32)`, stores as hex string in WCM. Called automatically on first setup (Path 3). Returns `bool` |
| `save_token()` | Reads `garmin_tokens.json` from `GARMIN_TOKEN_DIR`, encrypts AES-256-GCM, writes `.enc`, removes dir. Returns `bool` |
| `load_token()` | Decrypts `.enc`, writes `garmin_tokens.json` to `GARMIN_TOKEN_DIR`. Returns `bool` |
| `clear_token()` | Removes `.enc`, `GARMIN_TOKEN_DIR`, and enc_key from WCM. Returns `bool` — `True` only if both removal steps completed without error (v1.6.5.7, Netz 3 Kandidat 3) |
| `_clear_token_dir()` | Removes `GARMIN_TOKEN_DIR`. Called after token login and on failure |
| `_derive_aes_key(enc_key, salt)` | PBKDF2-HMAC-SHA256, 600k iterations, 32-byte key |
| `log_token_event(event, trigger, **extra)` | Appends one entry to `garmin_token_log.json` (`LOG_DIR`). Best-effort — catches all exceptions internally, never raises. `event`: `created` \| `invalidated` \| `blocked` \| `valid` \| `mfa` (v1.6.5.9 adds `mfa`). `trigger`: `sso_login` \| `rejected_by_garmin` \| `enc_key_missing_wcm` \| `manual_reset` \| `rate_limited` \| `token_reused` \| `mfa_required_no_callback` \| `challenge_presented` (v1.6.5.9 adds the last two). Records timestamp, `app_version` (read from `version.py`, falls back to `"unknown"`), `caller` (read from the `GARMIN_SESSION_LOG_PREFIX` ENV var — one of `garmin`/`garmin_bulk`/`garmin_background`/`daily`/`test_connection`/`live_update`/`timer_connection_test` (v1.6.5.9 — found via DEPS scan, `panel_timer.py`'s own connection test was previously undocumented), `"unknown"` if unset, v1.6.5.7.1), and optional `exception_type`/`detail`/`cause_type`/`cause_detail`/`solved` — no credentials, no token content (v1.6.5.2; `cause_type`/`cause_detail` added v1.6.5.9, see `garmin_api.py::_cause_fields()`; `solved` added v1.6.5.9, see `mfa`/`challenge_presented`). `valid`/`token_reused` events carry no `exception_type`/`detail` and are serialized as a single compact JSON line; all other events keep the multi-line `indent=2` format (v1.6.5.7.1) |
| `has_unresolved_mfa_block()` | Read-side counterpart to `log_token_event()` (v1.6.5.9). Fail-open: unreadable/malformed `garmin_token_log.json` → `False` (no block). Scans events newest-first; `True` if the most recent relevant event is `blocked`/`mfa_required_no_callback` with no `created`/`sso_login` event since. Called from `garmin_api.py::login()`'s Path 3 headless guard |

**`garmin_token_log.json`** (v1.6.5.2) — observation-only file in `LOG_DIR`, sole write authority `garmin_security.py::log_token_event()`. Introduced to measure actual token lifetime empirically instead of guessing — see `ANALYSE_headless_mfa_login_2026-07-08.md`. Structure:


| Function | Purpose |
|---|---|
| `validate(raw)` | Validates raw dict against cached schema. Returns `{"status", "schema_version", "timestamp", "issues"}`. Never modifies input. Fail-Closed: returns `"critical"` with a `missing_required` issue on `field: "schema"` if schema is absent (v1.5.6.3) |
| `reload_schema()` | Reloads `garmin_dataformat.json` from disk — called by self-healing loop on version mismatch |
| `current_version()` | Returns currently cached schema version string |

**Issue types:**

| Type | Trigger | Severity | Status impact |
|---|---|---|---|
| `missing_required` | Required field absent or wrong type, or schema not loaded | `critical` | `critical` |
| `type_mismatch` | Known field present but wrong type | `critical` / `warning` | depends |
| `missing_optional` | Optional field absent | `info` | none |
| `unexpected_field` | Field not in schema | `warning` | `warning` |

Schema cached at module import. Leaf node.

---

## `garmin_utils.py`

Shared utilities — leaf node. No project-module imports.

| Function | Purpose |
|---|---|
| `parse_device_date(val)` | Converts device date value to `YYYY-MM-DD`. Handles ISO strings, ms timestamps, s timestamps. Returns `None` on failure. Internally uses `datetime.utcfromtimestamp()`, deprecated since Python 3.12 — found during the v1.6.5.6 sibling-sweep, not fixed there (see `ROADMAP.md`) |
| `parse_sync_dates(raw)` | Parses comma-separated `YYYY-MM-DD` string. Returns sorted `list[date]` or `None` |
| `extract_date_from_filename(path, prefix)` | Extracts `date` from filename like `garmin_raw_YYYY-MM-DD.json`. Default prefix `"garmin_raw_"`. Returns `None` on invalid format — no exception propagation |

---

## `garmin_merge.py`

Leaf-Node — additive field merge for backfill operations. Used exclusively
by backfill paths (Steps Backfill and any future case retrofitting an
optional field into an already-archived day).

| Function | Purpose |
|---|---|
| `merge_field(raw, field, value)` | Additively merges a single field into a raw dict — only sets `raw[field]` if absent or currently empty (`None`/`[]`/`{}`/`""`/`0`/`False`). Never overwrites an existing non-empty value — by construction incapable of downgrading already-archived content. Never mutates the input; returns a new dict. Returns the input unchanged (not a copy) if it is not a dict |

---

## `garmin_redact.py`

Leaf-Node — secret redaction for log output. Replaces the live
`GARMIN_EMAIL`/`GARMIN_PASSWORD` values with readable placeholders before
text reaches any log sink (file, GUI widget, clipboard). Reads
`garmin_config` fresh on every call — no caching, follows
`importlib.reload(cfg)` automatically. Exact-value match only — no pattern
matching on unknown text.

| Function / Class | Purpose |
|---|---|
| `redact(text)` | Replaces the current `GARMIN_EMAIL`/`GARMIN_PASSWORD` value (if non-empty) with `[GARMIN_EMAIL]`/`[GARMIN_PASSWORD]` |
| `RedactFilter` | `logging.Filter` — redacts both values from every `LogRecord`'s `msg` and string `args` as they pass through. Always returns `True` — never suppresses a record, only mutates its text |

---

## `garmin_normalizer.py`

| Function / Constant | Purpose |
|---|---|
| `CURRENT_SCHEMA_VERSION` | int — summary schema version. Increment on field changes |
| `normalize(raw, source)` | Entry point. `source`: `"api"` or `"bulk"` |
| `summarize(raw)` | Produces compact daily summary. Writes `schema_version` into every file. Emits `log.warning()` when `sleepTimeSeconds` is `None` (structurally absent — distinct from `0`, which is a legitimate no-sleep-recorded value). v1.5.6.3 |
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
| `assess_quality(raw)` | Returns `"high"` / `"standard"` / `"failed"`. Pure function |
| `assess_quality_fields(raw)` | Returns per-endpoint quality dict. Pure function. Reuses `garmin_normalizer._parse_list_values()` to verify an intraday array actually parses into `[ts,val]` pairs (`[ts,status,val]` for `body_battery`, `val_index=2`) before labeling a field `"high"` — a structurally malformed array falls through to the next applicable tier instead (v1.6.5.8, F8). Downgrade reasons are collected under a reserved key inside the returned dict, extracted by `_maint.py` into `entry["field_downgrades"]` — never present in the dict actually stored as `entry["fields"]` |
| `record_attempt(data, day, label, reason, written, source, fields, validator_result, device_id, device_name, prev_high)` | Public API — atomically calls `_upsert_quality` + `_save_quality_log`. Caller must hold `QUALITY_LOCK`. |
| `_upsert_quality(data, day, quality, reason, written, source, fields, validator_result, device_id, device_name, prev_high)` | Adds or updates day entry. Downgrade protection: `high` stays `high`. Stores `device_id` + `device_name` per entry. |
| `save_device_table(quality_data)` | Builds and writes `device_table.json`. Called after each sync and after device_id backfill. Groups entries by `device_id`; entries with `device_id=None` appear as `__unknown__` row. Sole write authority: `garmin_quality`. |
| `get_archive_stats(quality_log_path)` | Returns GUI stats dict: `total`, `high`, `standard`, `failed`, `recheck`, `missing`, `date_min`, `date_max`, `coverage_pct`, `last_api`, `last_bulk`, `integrity_warnings` |
| `_compute_checksum(data)` | SHA-256 over stable core fields (`date`, `write`, `quality`, `source`) of all day entries. Extended in v1.5.5. Migration bridge: `_compute_checksum_legacy()` (TODO: remove after v1.6) |
| `_compute_checksum_legacy(data)` | Pre-v1.5.5 algorithm (`date` + `write` only). Used once on load to detect planned upgrade — never for new saves |
| `_save_defective_log(data)` | Saves defective quality_log state to `AUTORESTORE_DIR` before auto-restore. Best-effort |
| `_load_quality_log()` | Now returns `integrity_warnings: list[str]` — empty if checksum OK, year labels if mismatch |
| `_save_quality_log(data, skip_backup)` | `skip_backup=True` suppresses backup trigger. Default `False` triggers `garmin_backup.backup_quality_log()` |
| `get_low_quality_dates(folder, known_dates)` | Scans `raw/` for files not in quality log |
| `_set_first_day(data, client)` | Determines and persists `first_day`. Never overwrites existing value |
| `cleanup_before_first_day(data, dry_run)` | Removes files and log entries before `first_day` |

**Quality levels (v1.5.7+):**

| Level | Meaning | `recheck` default |
|---|---|---|
| `high` | Intraday data present | `false` — never re-downloaded |
| `standard` | Daily aggregates only — maximum available for this day | `false` unless `prev_high=true` and day ≤ 180 days old |
| `failed` | API error — no file | `true` until successful |

**Per-entry device tracking (v1.5.7+):**

Each quality log entry stores `device_id` (str) and `device_name` (str) — set by `garmin_collector` from `training_status → mostRecentTrainingStatus → recordedDevices[0]`. Entries without `training_status` (older devices) have `device_id = None`. The `device_table.json` file is derived from these fields after each sync.

---

## `garmin_sync.py`

| Symbol | Purpose |
|---|---|
| `ConfigurationError` | Raised by `resolve_date_range()` when `SYNC_MODE=range` and `SYNC_FROM` / `SYNC_TO` is empty or not a valid ISO date. Fires before any API call. |
| `resolve_date_range(first_day)` | Returns `(start, end)` based on `cfg.SYNC_MODE` |
| `get_local_dates(folder, recheck_dates)` | Returns set of dates with local data |
| `date_range(start, end)` | Generator — yields every `date` from `start` to `end` inclusive |

---

## `garmin_collector.py`

| Function | Purpose |
|---|---|
| `main()` | Full sync orchestration: import mode (0) → Capability Scan mode (0b, delegated entry, own login, v1.6.8) → dirs → session log → quality load → bulk upgrade flagging → self-healing → schema migration → login → devices → device_id backfill → source backfill (5c) → first_day → date resolution → fetch loop → save |
| `_fetch_and_assess(client, date_str, enabled_candidates=None)` | Fetch → validate → normalize → assess. No file writes. Returns `(label, normalized, summary, fields, val_result)`. `enabled_candidates` (v1.6.8) — optional list of API-Capability-Scan candidate method names, pre-filtered by the caller (double-gate); turned into `extra_endpoints` for `api.fetch_raw()`. `None` (default) — used by `_run_source_backfill()`, which does not take part in the Capability Scan (scope boundary, v1.6.8) |
| `run_capability_scan(client, window_days=7)` | Probes the 19 optional health-endpoint candidates (`garmin_api_capability.CANDIDATE_ENDPOINTS`) over the last `window_days` days. Runs entirely under `quality.QUALITY_LOCK` (reused, not a new lock — see Invariants). Per-candidate try/except — one failing candidate never aborts the rest. Payload discarded, only the tri-state result (`found`/`not_observed`/`error`) persisted via `garmin_api_capability.update_endpoint()`/`save_config()`. Returns `{"scanned", "found", "not_observed", "error"}` (v1.6.8) |
| `_check_downgrade(new_label, existing_entry)` | Compares new quality label against stored entry. Returns `(is_downgrade, existing_label, existing_source)`. Delegates the actual rank comparison to `quality.is_downgrade()` (v1.6.5.7 — canonical location, also used by `export/regenerate_raw.py` and `garmin_silo_repair.py`; previously duplicated in each) |
| `_run_steps_backfill(client, quality_data)` | Backfills `steps_series` for existing high-quality API days. Per day: `api_call()` → `merge_field()` → `normalize()`/`summarize()` → `write_day()` → `record_attempt()` (with `backfilled_fields`) → `patch_source_field()`. On `patch_source_field()` failure: one automatic retry, then `log.error()` (not `warning`) if it still fails — `source/` will not be auto-retried on a future run, since the candidate filter checks `fields` from `raw/`, already correct at that point (v1.6.5.7) |
| `_write_assessed(normalized, summary, date_str, label)` | Writes pre-assessed day to disk. Returns `bool` |
| `run_import(path, progress_callback, stop_event)` | Bulk import orchestration via `garmin_import.load_bulk()`. Returns `{"ok", "skipped", "failed"}` — a day with `quality: "failed"` now counts in `failed`, not `ok` (v1.6.5.8, Fix 3; previously only an actual exception in the loop incremented `failed`). `main()`'s delegated exit code for the import mode (`sys.exit(0 if result["failed"] == 0 else 1)`) follows this count |
| `_run_self_healing(quality_data)` | Revalidates days with stale schema version against local `raw/` files — no API call |
| `_run_schema_migration(quality_data)` | Rewrites outdated summary files from raw when `GARMIN_SCHEMA_MIGRATE=1`. No API call. Raw files unchanged. Log output per day `[i/total]` |
| `_run_source_backfill(client, quality_data)` | Re-fetches API days from `cfg.SYNC_DATES` that have no `source/` file. Step 5c in `main()` — after login, triggered by `GARMIN_SOURCE_BACKFILL=1`. Non-fatal per-day errors. No-op if `SYNC_DATES` empty (v1.6.0.3) |
| `_start_session_log()` | Opens session log file. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if errors present |

**Bulk recheck logic:**

All days with `source: bulk` + date ≤ 180 days old are automatically flagged `recheck: true` on every startup (Step 3) — quality is irrelevant, source is the trigger. After 180 days Garmin degrades intraday data permanently; the local raw copy is then the only high-resolution source. In Step 7, bulk recheck days are collected into `bulk_upgrade_dates` and always excluded from `local_dates` — regardless of `REFRESH_FAILED`.

**Downgrade during bulk recheck:** If the API result is inferior to the existing bulk entry, `attempts` is incremented manually after `_upsert_quality()`. After 2 failed attempts `recheck` is set to `false` — the bulk quality is accepted as final.

**Downgrade protection:**

After `_fetch_and_assess()`, `_check_downgrade()` compares the new label against the existing quality log entry using rank `high=2 > standard=1 > failed=0` (`QUALITY_RANK` in `quality/_maint.py`). If the API result is inferior: file is not written, existing entry is preserved. If equal or better: `_write_assessed()` is called and entry is upserted as `source: api`.

**Resume safety:**

`_save_quality_log()` is called after every individual day — in all paths (upgrade, downgrade, error). Every successfully processed day is an atomic resume point. Stopping mid-run resumes from the next unprocessed day on the next start.

---

## `garmin_api_capability.py`

Sole Owner of `garmin_api_capability_config.json` (`cfg.CAPABILITY_CONFIG_FILE`).
Leaf-Node — imports only `garmin_config` + stdlib. No pipeline imports
(`garmin_collector`, `garmin_api`, `garmin_quality`, ...). (v1.6.8)

| Function | Purpose |
|---|---|
| `CANDIDATE_ENDPOINTS` | Module-level list of the 19 optional health-endpoint method names |
| `ENDPOINT_ARGS` | Maps a subset of `CANDIDATE_ENDPOINTS` to their non-default argument shape (`"no_args"` / `"date_range"`) — discovered empirically from real `TypeError`s during the first live scan, not from library docs |
| `build_args(endpoint, date_str)` | Returns the correct positional-args tuple for a candidate. Defaults to `"single_date"` `(date_str,)` for endpoints not listed in `ENDPOINT_ARGS` |
| `load_config()` | Loads the config JSON. Returns a fresh default (all 19 candidates at `not_observed`) if the file is missing or corrupt — never raises |
| `save_config(config)` | Atomic write (`.tmp → fsync → os.replace`). Returns `bool` |
| `update_endpoint(config, endpoint, status, **meta)` | Pure function — returns a new config dict with one entry updated, does not save itself. `status` must be one of `"found"` / `"not_observed"` / `"error"` |
| `reset_config()` | Returns a fresh default config. Does not save — public entry point for UI "Clear Config", so callers never need to reach into the private `_default_config()` |
| `get_enabled_candidates(config)` | Returns the subset of `CANDIDATE_ENDPOINTS` double-gated as enabled for a sync run (`status == "found"` **and** `enabled_by_user`). Pure function — takes an already-loaded config snapshot, does not call `load_config()` itself. Extracted from `garmin_collector.py::main()`'s fetch-loop section (v1.6.8.1) — see `NOTES_v1681_01.md` |

**Config entry shape** (per candidate, keyed by method name):
```json
{
  "status": "found",
  "last_scan": "2026-08-13T18:20:22",
  "discovered_at": "2026-08-13T18:20:22",
  "last_seen_with_data": "2026-08-13",
  "enabled_by_user": false
}
```

**Discovery result is tri-state, not binary:** `found` (non-empty data returned at least once in the scan window), `not_observed` (every attempt succeeded but returned nothing), `error` (at least one attempt failed/raised and `found` was never reached) — avoids treating a transient API error as proof of a missing capability.

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

**Not available in bulk export (API only):** intraday HR, stress curve, body battery curve, SpO2 series, respiration series, HRV details, training status. Bulk data always results in `standard` quality — never `high`.

---

## `garmin_import_mirror.py`

Import path for `.gla` mirror containers (encrypted, produced by
`garmin_mirror.py`) and — deprecated, folder-fallback only — a plain
mirror folder. Container path is primary; folder fallback is scheduled
for removal.

| Function | Purpose |
|---|---|
| `run_import_mirror(mirror_path, base_dir, password, dry_run)` | Entry point. Detects source type; dry-run previews counts; live-run copies raw + context + source, one `quality_log.json` save per processed day (v1.6.5.7 GP-2 fix — previously saved once at the end of the whole import) |
| `detect_source(mirror_path)` | Returns `"container"`, `"folder"`, or `"unknown"` |
| `_run_import_container(...)` / `_run_import_folder(...)` | Per-source-type orchestration, both under `QUALITY_LOCK` |
| `_import_raw_from_bytes(...)` / `_import_raw_folder(...)` | Per-day raw import — `_upsert_quality()` per day, `_save_quality_log(skip_backup=True)` per day (v1.6.5.7), one final save (with backup) after the loop |

**Return contract — `run_import_mirror()`:**
```python
{
    "raw_copied":     int,
    "raw_skipped":    int,
    "context_copied": int,
    "errors":         int,
    "ok":             bool,
    "error":          str,   # v1.6.5.7 — present only on early hard-stop
                              # failures (unrecognised source, unlock_meta
                              # failure, unreadable mirror_meta.json/
                              # quality_log). Absent when "ok" is False due
                              # to per-item errors during processing —
                              # those are individually logged, "errors" is
                              # their count.
}

Sole Owner of `garmin_data/backup/`. Does not import `garmin_writer` or `garmin_quality`.

| Function | Purpose |
|---|---|
| `backup_raw(date_str)` | Copies `garmin_raw_YYYY-MM-DD.json` into `backup/raw/YYYY-MM/`. Triggers `_consolidate_raw_months()`. Returns `bool` |
| `backup_quality_log()` | Creates monthly snapshot of `quality_log.json` as `quality_log_YYYY-MM.zip`. Triggers yearly consolidation |
| `restore_quality_log()` | Restores from latest valid monthly ZIP. Returns loaded `dict` or `None` |
| `check_raw_integrity()` | Compares `write=True` quality log entries vs. existing raw files. Returns `{"missing_days", "no_backup", "total_checked", "error"}` — `error` is `None` on success, set if `quality_log.json` itself could not be read (v1.6.5.7, Netz 3 Kandidat 2). Called via `garmin_app_controller.check_integrity()` which sets `GARMIN_OUTPUT_DIR` first |
| `restore_raw_days(date_strs)` | Restores raw files from backup (dir first, then ZIP). Returns `{"restored", "skipped_already_current", "failed", "errors"}` — `errors` is `dict[str, str]`, one reason per date in `failed` (v1.6.5.7, Netz 3 Kandidat 2). Own downgrade guard (v1.6.5.8, Fix 2): a date is skipped into `skipped_already_current` if a raw file already exists for it and its `quality_log` entry is already `"high"` — reads `quality_log.json` directly, same pattern as `check_raw_integrity()`, no `garmin_quality` import (this module deliberately has none) |
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

## `garmin_container.py`

Sole Owner of `mirror.gla`. No other module reads or writes the container file directly.
All paths from caller — no `garmin_config` import.

| Function | Purpose |
|---|---|
| `lock(source_dir, container_path, password)` | Creates/overwrites `mirror.gla` atomically. Packs quality_log (quality_log.json + device_table.json), raw, summary, context sections. Returns `{"files_packed", "errors", "ok"}` |
| `unlock_meta(container_path, password)` | Verifies header HMAC, decrypts quality_log section, extracts quality_log.json by explicit key. Returns `{"ok", "container_meta", "quality_log", "error"}` |
| `fulfill_order(container_path, password, order)` | Verifies HMAC, decrypts only ordered sections. Returns `{rel_path: bytes}` |
| `list_files(container_path, section)` | Returns file list from header — no decryption, no password. Returns `list[str]` |
| `is_container(path)` | Checks magic bytes `GLA1`. Fast, no password. Returns `bool` |

**Container format:**


---

## `garmin_dataformat.json`

Schema for `garmin_validator.py`. Located at `garmin/garmin_dataformat.json`.

**Current version:** `1.1` (unchanged by v1.6.8 — field-only addition, see below;
no re-validation wave needed for already-archived days)

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
| `steps` | list | — |
| `user_summary` | dict | — |
| `training_status` | dict | — |
| `training_readiness` | dict | — |
| `hrv` | dict | — |
| `race_predictions` | dict | — |
| `max_metrics` | dict | — |
| `activities` | list | — |

**API-Capability-Scan candidate fields (v1.6.8):** 19 fields, all `type: any`,
`required: false`. Keyed by raw method name (not a short label like the 15
above — `CANDIDATE_ENDPOINTS` defines no short-name convention yet).

| Field |
|---|
| `get_body_composition` |
| `get_daily_weigh_ins` |
| `get_blood_pressure` |
| `get_hydration_data` |
| `get_menstrual_calendar_data` |
| `get_pregnancy_summary` |
| `get_lifestyle_logging_data` |
| `get_nutrition_daily_food_log` |
| `get_nutrition_daily_meals` |
| `get_nutrition_daily_settings` |
| `get_calories_daily` |
| `get_floors` |
| `get_intensity_minutes_data` |
| `get_body_battery_events` |
| `get_endurance_score` |
| `get_fitnessage_data` |
| `get_hill_score` |
| `get_lactate_threshold` |
| `get_running_tolerance` |

As of v1.6.8 Session 4, all 19 are broker-reachable in some form: 6 are
interpreted into `summary/` fields (`body_weight`, `calories_resting`,
`hydration_ml`, `endurance_score`, `hill_score`, `fitness_age`), the
remaining 13 are exposed unprocessed via `get_raw()`/`list_raw_fields()`
— see "Raw-passthrough fields" below. `get_daily_weigh_ins` is a
suspected duplicate of `get_body_composition` (both empty/identical at
the pilot account) — see `NOTES_v168_C_01.md`, unresolved pending real
scale data.

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
      "validator_schema_version": "1.1"
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
| `day` | Steps, calories (active/total/resting), intensity minutes, distance |
| `body_composition` | Body weight in grams, raw from `get_body_composition` (v1.6.8 capability-scan pilot, unit unverified against real scale data) |
| `hydration` | Fluid intake in ml, raw from `get_hydration_data` (v1.6.8 Session 4) |
| `training` | Readiness, status, load, VO2max, Endurance Score, Hill Score, Fitness Age (v1.6.8 Session 4) |
| `activities` | List of activity objects |

---

## `garmin_live_fetch.py`

Worker — sole write authority over `garmin_data/live/live.json` (v1.6.5). Depends on `garmin_api` (reuses `login()` / `api_call()` — no second auth path, no own 429 handling).
Single-file snapshot of the current calendar day ("heute Nacht bis jetzt") — no history, overwritten on every fetch. No archive write access, no `quality_log.json` contact, no validator/normalizer — data is written as-is.

| Function | Purpose |
|---|---|
| `fetch_live(client=None, progress=None, state_cb=None)` | Fetches sleep + HRV + all six intraday endpoints for today. `client=None` logs in headless (or reuses an already-authenticated client, e.g. right after a Daily Sync run). `progress`: optional `callable(str) -> None` for GUI-visible fetch progress — deliberately not named `log`, which would shadow the module logger. `state_cb` (v1.6.5.1): optional `callable(key: str, state: str) -> None` for GUI connection-status indicators (token/login/api/data × ok/fail) — fires token+login right after the login step, then api+data via a lightweight probe (`client.get_user_profile()` / `client.get_stats(today)`, same pattern as `garmin_app_controller.check_connection()`) immediately after, independent of the endpoint loop's own per-endpoint tracking. Returns `{"ok": bool, "failed_endpoints": list[str]}`. `ok=False` only on login failure/unavailability — individual endpoint failures never abort the fetch |
| `_write_live(live_data)` | Writes the snapshot to `cfg.LIVE_FILE`. Plain write, no atomic tmp/fsync/replace sequence — `live.json` has no history to protect |

---

## `garmin_health_map.py`

Field resolver for the dashboard broker architecture. Called exclusively by `health_map.py` — never directly by specialists.

### `_FIELD_MAP` — descriptor types

Each field in `_FIELD_MAP` uses one of six descriptor types:

| Type | Key | Resolution | Source |
|---|---|---|---|
| `daily` | `("section", "key")` | daily | `summary/garmin_YYYY-MM-DD.json` |
| `intraday` | `("section", "array_key", extract_dict)` | intraday | `raw/garmin_raw_YYYY-MM-DD.json` |
| `raw_pct` | `("section", "dto_key", "seconds_key", "total_key")` | daily | `raw/garmin_raw_YYYY-MM-DD.json` |
| `live` | `("section", "array_key", extract_dict)` | live | `garmin_data/live/live.json` |
| `live_pct` | `("section", "dto_key", "seconds_key", "total_key")` | live | `garmin_data/live/live.json` |
| `live_nested` | `[("section", "dotted_key"), ...]` — each candidate may also be a 3-tuple `("section", "dotted_key", divisor)` | live | `garmin_data/live/live.json` |

`raw_pct` is used for fields that require percentage calculation from two seconds-based values in the raw file. `get()` detects `raw_pct` and bypasses the standard daily/intraday resolution fallback logic.

The three `live*` types (v1.6.5) exist only for `resolution="live"` — a single always-current snapshot, no archive equivalent to fall back to, `date_from`/`date_to` are ignored. `live` mirrors the `intraday` array-extraction logic against `live.json` instead of a dated `raw/` file. `live_pct` mirrors `raw_pct`'s percentage math. `live_nested` resolves a dotted key path, trying each candidate in an ordered fallback chain until one is non-`None`; an optional divisor divides the raw value (e.g. `sleepTimeSeconds / 3600` → hours). Missing `live.json` or no field/candidate found → `fallback=True`, empty `values`, never an exception — handled directly inside `garmin_health_map.py` (`_read_live`/`_read_live_pct`/`_read_live_nested`), not via `field_map`'s generic exception catch.

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
| `spo2_series` | intraday | `spo2.spO2HourlyAverages` | List of `[epoch_ms, value]` pairs — corrected in v1.6.3.1 (previously misread as dict-shaped, series was silently empty for every consumer) |
| `body_battery_series` | intraday | `stress.bodyBatteryValuesArray` | — |
| `respiration_series` | intraday | `respiration.respirationValuesArray` | List of `[epoch_ms, value]` pairs — same v1.6.3.1 fix as spo2_series. Raw data also contains a newer, parallel `wellnessEpochRespirationDataDTOList` (dict-shaped) — absent in all 4 raw files sampled during v1.6.5.6 (2024-03-07, 2025-03-10, 2025-03-30, 2026-07-01/27); not conclusive, still not evaluated as a data source, see `NOTES_v1656.md` |
| `steps_series` | intraday | `steps` (bare list at top level, not nested under a sub-key) | 15-min bins, `{"startGMT", "steps"}`. `_read_intraday()` handles this via its existing `isinstance(section_data, list)` branch — no code change needed for this shape |
| `body_weight` | daily | `body_composition.weight_g` | grams, raw/unconverted — Garmin's gram convention assumed but not verified against real data (no scale connected during pilot). First API-Capability-Scan candidate wired into the broker (v1.6.8) |
| `calories_resting` | daily | `day.calories_resting` | kcal — resting/basal calories from `get_calories_daily`, distinct from `calories_active`/`calories_total` (sourced from `user_summary`, unrelated raw section, likely redundant with this candidate's own `active`/`total` fields — only `resting` was adopted). Second API-Capability-Scan candidate wired into the broker (v1.6.8) |
| `hydration_ml` | daily | `hydration.value_ml` | ml, from `get_hydration_data` — only `valueInML` adopted, `goalInML` (a user-set target, not a measurement) intentionally excluded (v1.6.8 Session 4) |
| `endurance_score` | daily | `training.endurance_score` | index, from `get_endurance_score` — checked against `vo2max` for redundancy (Multi-LLM hint), none found — distinct, device-calculated index (v1.6.8 Session 4) |
| `hill_score` | daily | `training.hill_score` | index, from `get_hill_score` — not to be confused with that same endpoint's own internal `enduranceScore` sub-field, unrelated to the `endurance_score` field above (v1.6.8 Session 4) |
| `fitness_age` | daily | `training.fitness_age` | years, from `get_fitnessage_data` — only `fitnessAge` adopted; `chronologicalAge`/`achievableFitnessAge`/`previousFitnessAge`/`components` intentionally excluded (v1.6.8 Session 4) |

**Live route (v1.6.5):** 16 of the fields above also support `resolution="live"` (reads `garmin_data/live/live.json`, written by `garmin_live_fetch.py`, instead of the archive): `heart_rate_series`, `stress_series`, `spo2_series`, `body_battery_series`, `respiration_series`, `steps_series` (via `live`); `sleep_deep_pct`, `sleep_light_pct`, `sleep_rem_pct`, `sleep_awake_pct` (via `live_pct`); `hrv_last_night`, `sleep_score`, `sleep_score_feedback`, `sleep_score_qualifier`, `sleep_duration` (via `live_nested`). Fields with no live route (`resting_heart_rate`, `spo2_avg`, `body_battery_max`, `stress_avg`, `vo2max`) return `fallback=True`, empty `values`, for `resolution="live"`. Consumer: `dashboards/live_tracking_html_dash.py`.

*(v1.7.1.6)* `sleep_score` (the numeric score itself, distinct from its `_feedback`/`_qualifier` companions) previously had a `live_nested` route (`sleep.dailySleepDTO.sleepScores.overall.value`) and a `daily` route (`sleep.score`) but was missing its own row in both the Registered-fields table above and the live-route count/list — a pre-existing gap, not introduced in v1.6.5. Both closed this session (see `REFERENCE_BROKER.md`'s "Field index" for the added `0–100` unit row; the live-route count above corrected from 15 to 16 and `sleep_score` added to the `live_nested` list).

### Raw-passthrough fields (v1.6.8 Session 4)

13 of the 19 original API-Capability-Scan candidates have no known
daily-value extraction — list-of-entries structure, empty/unknown schema
at the pilot account, or event-log structure (see `NOTES_v168_D_02.md`
"Blocker-Typen" for the per-field reasoning). Rather than leave them
archived-but-broker-invisible, `garmin_health_map.py` exposes them
unprocessed via a second, deliberately separate access path — kept
entirely out of `_FIELD_MAP`/`get()`/`list_fields()` so existing
dashboards (which all assume the scalar `{"values": [{"date", "value"}]}`
shape) are structurally unaffected:

```python
def get_raw(field: str, date_from: str, date_to: str) -> dict:
    # Returns {"values": [{"date": str, "raw": any|None}, ...],
    #          "source_resolution": "raw"}
```

Unlike `get()`, there is no `"value"` extraction — the caller receives
exactly what Garmin returned for that day and is responsible for
interpreting it. `raw` is `None` if the day's `raw/` file is missing or
does not contain that endpoint's key. `health_map.py`/`gateway_map.py`
provide thin passthroughs — see `REFERENCE_BROKER.md`.

**Status:** open for community feedback — GitHub issue with a feedback
template pending (v1.6.8 doc-closure). Any of the 13 fields with a
concrete aggregation/display proposal backed by real filled data can move
to a proper `summarize()` field later, same as the six already wired.

| Field | Source endpoint |
|---|---|
| `daily_weigh_ins` | `get_daily_weigh_ins` |
| `blood_pressure` | `get_blood_pressure` |
| `menstrual_calendar_data` | `get_menstrual_calendar_data` |
| `pregnancy_summary` | `get_pregnancy_summary` |
| `lifestyle_logging_data` | `get_lifestyle_logging_data` |
| `nutrition_daily_food_log` | `get_nutrition_daily_food_log` |
| `nutrition_daily_meals` | `get_nutrition_daily_meals` |
| `nutrition_daily_settings` | `get_nutrition_daily_settings` |
| `floors` | `get_floors` |
| `intensity_minutes_data` | `get_intensity_minutes_data` |
| `body_battery_events` | `get_body_battery_events` |
| `lactate_threshold` | `get_lactate_threshold` |
| `running_tolerance` | `get_running_tolerance` |

### Timestamp handling (v1.6.5.6)

Intraday timestamps returned by `_extract_series()` are shifted to the
device's local time — not the system clock's timezone, not a hardcoded
reference zone. The offset is derived per raw/live file from Garmin's own
section metadata; no `zoneinfo`, no new hidden-import.

| Function | Purpose |
|---|---|
| `_device_offset(data)` | Returns `(offset_hours, dst_transition)` for one raw/live file's `data` dict. Tries `_OFFSET_SOURCE_SECTIONS` in order (`heart_rates → stress → respiration → spo2`), first section with a complete `startTimestampGMT/Local` + `endTimestampGMT/Local` pair wins. `dst_transition=True` when start-of-day and end-of-day offset differ (day crosses a DST change) — the offset used is always the start-of-day value, matching how Garmin Connect itself renders the day (it does not correct mid-day either). No usable section → `(0.0, False)` with a `log.warning` — never a silent UTC fallback, never an exception |
| `_section_offset(section_data)` | Computes `(start_offset_hours, end_offset_hours)` from one section's GMT/Local timestamp pair. Returns `None` if either pair is missing or malformed |
| `_parse_naive(ts)` | Parses a Garmin ISO timestamp string to a naive `datetime`, ignoring sub-second digits (`ts[:19]`) |
| `_ts_to_iso(ts, offset_hours=0.0)` | Normalizes an epoch-ms value or ISO string to an ISO-8601 string, shifted by `offset_hours`. Stays naive — no offset suffix. A suffix would be reapplied by Plotly's `xaxis: {type:'date'}` in the browser's own timezone, reintroducing the original bug at a different layer |
| `_extract_series(arr, section_data, extract, offset_hours=0.0)` | Extraction logic unchanged; `offset_hours` passed straight through to `_ts_to_iso()`. Not to be confused with `extract["offset_key"]` — Garmin's own *value* offset (e.g. `stressChartValueOffset`), a different concept entirely |

`_OFFSET_SOURCE_SECTIONS = ("heart_rates", "stress", "respiration", "spo2")`
— deliberately excludes `body_battery`: Body Battery data lives inside the
`stress` section's `bodyBatteryValuesArray` (see `body_battery_series`
above); there is no separate `body_battery` section that `garmin_health_map.py`
itself reads.

`_read_intraday()` and `_read_live()` both call `_device_offset()` once per
file and add `"dst_transition": bool` to every entry in `values` — part of
the broker response contract, see `REFERENCE_BROKER.md`.

**Architecture boundary:** Any Garmin-internal key (`section.field`, `dailySleepDTO`, etc.) appearing outside `garmin_health_map.py` is an architecture violation — detectable by name format alone.

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
| `_timer_loop(generation)` | Main timer loop, in `panel_timer.py` — six modes, candidate logic delegated to `garmin_app_controller.py` (see its own section below) |
| `_copy_last_error_log()` | Copies most recent fail log to clipboard |
