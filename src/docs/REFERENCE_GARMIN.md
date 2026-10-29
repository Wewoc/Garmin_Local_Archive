# Garmin Local Archive — Garmin Pipeline Reference

Technical reference for the Garmin data pipeline (`garmin/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.
For the broker request/response contract (`field_map.get()`) see `REFERENCE_BROKER.md`.
For the layout of Garmin's account data export (the input of the bulk import) and its known quirks see `REFERENCE_GARMIN_EXPORT.md`.

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
- `garmin_writer.py` is sole write authority for `raw/` and `summary/`. `raw/` holds only what the API delivered; since v1.7.6.1 a day with an aggregates file in the bulk store gets a resolved `summary/` (API data first, the export fills what is missing — field by field inside a section since v1.7.6.3) — see `garmin_writer.py` below
- `garmin_writer.write_day()` / `write_summary_only()` / `rebuild_summary()` return `False` when nothing was written (a write error, or an aggregates/raw file of the day that cannot be read); every caller evaluates the result (v1.7.6.1, F-4/F-5/F-6): silo repair #3/#7, `regenerate_raw.py`, the schema migration, the fetch loop of `main()` (for a writable label) and the mirror import count it as an error of the day
- `garmin_quality.py` is sole write authority for `quality_log.json`
- `garmin_backup.py` is sole write authority for `garmin_data/backup/raw/` and `backup/log/`, `garmin_backup_source.py` for `backup/source/`, `garmin_backup_bulk.py` (v1.7.6.2) for `backup/bulk/`. `garmin_backup_common.py` (v1.7.6.2) is the monthly folder / ZIP flow they share and owns nothing; `garmin_backup_bulk.py` only reads the bulk store
- `garmin_source_writer.py` is sole write authority for `garmin_data/source/` and `source_api_log.json` (v1.6.0.2 — genuinely enforced since v1.6.0.4.6: mirror bypass closed)
- `source/` contains exclusively live API responses — bulk import never writes to `source/`, not even during backfill (v1.6.0.2)
- `source/` files with `intraday_present=True` are never overwritten by a degraded response — Conservative guard in `write_source()` (v1.6.0.4.6). `force=True` (v1.7.1.7) bypasses this guard entirely — used exclusively by the deliberate per-day Force-Refetch path (`garmin_collector.run_force_refetch_preview()`), never by the normal sync path
- `garmin_force_refetch.py` is sole write authority for `garmin_data/backup/force_refetch/` (v1.7.1.7) — pre-overwrite `source/` snapshots for Force-Refetch, deliberately separate from `AUTORESTORE_DIR` (different purpose: quality_log-wide defect recovery vs. single-day safety net before an intentional freeze-guard bypass)
- `garmin_migration_snapshot.py` (v1.7.6.3, removable) is sole write authority for `garmin_data/backup/migration/` — the safety copy of `raw/`, `summary/` and the quality log that the migration makes before its first write; `garmin_track_migration.py` owns no files and writes only through `garmin_writer` and `garmin_quality`
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
- `garmin_repair_resting_hr.py` (v1.7.5.7, removable) never writes a file itself: `raw/` + `summary/` only through `garmin_writer.write_day()`, `quality_log.json` only through `garmin_quality` (`touch_last_checked()` + `_save_quality_log()`), under one continuous `QUALITY_LOCK` hold. A caller that keeps its quality log in memory must hand it over (`quality_data=`) — a copy loaded by the repair would be overwritten by the caller's next save
- `garmin_bulk_writer.py` (v1.7.6) is sole write authority for `garmin_data/bulk/raw/`, `garmin_data/bulk/aggregates/` (v1.7.6.1) and `garmin_data/bulk/source/`. The API sync never writes there, and the bulk writer never writes `raw/`, `source/` or `summary/`. It decides only whether a day may be replaced; which days and file types are written is the import's business
- A bulk day (series file or aggregates file) is never replaced by a smaller state: fewer source files, or a set that is not a superset, keeps the stored day; a day written by a newer schema version is kept. A day file that cannot be read for I/O reasons is `unreadable` (v1.7.6.1, F-1): it is not touched and the write answers `failed`; a damaged file (not JSON) still counts as `new`, the new write is the repair
- `garmin_bulk_fit_reader.py`, `garmin_bulk_export_scanner.py` and `garmin_bulk_normalizer.py` (v1.7.6) are leaf nodes — stdlib only, no project imports, no `garmin_config`. No entry name of the export is returned, counted or logged (the names carry the account's e-mail address): counters and hashes only
- `garmin_bulk_import.py` (v1.7.6) orchestrates only; it never touches `quality_log.json`, the backup or the API store. The caller marks the written days (`garmin_collector._mark_bulk_days()` → `garmin_quality.record_bulk_intraday()`, under `QUALITY_LOCK`). Since v1.7.6.2 the bulk store is covered by `garmin_backup_bulk.py` (backup), the container sections `bulk` and `bulk_source` (mirror) and the silo check (#5/#7 by the names of the aggregates files, #8/#9 below)
- `garmin_bulk_json_import.py` (v1.7.6.1) orchestrates only, like `garmin_bulk_import.py`: it never touches `quality_log.json`, `raw/`, `summary/` or the backup. The caller makes the summaries of the written days and the quality-log entries and marks (`garmin_collector._finish_aggregates()` → `_apply_aggregates()`, under `QUALITY_LOCK`, one save). A day of the export that is invalid or has too little data is rejected and reported; it is not a failure of the run (a rerun would reject it again). Since v1.7.6.7 the result also carries an inventory of the export (`garmin_import.build_inventory()`: counts per known kind and folder groups of what is not known, never a file name)
- `garmin_bulk_rebuild.py` (v1.7.6.5, removable) orchestrates only, like `garmin_bulk_json_import.py`, and works without the export: it reads the JSON originals kept in `bulk/source` itself (the SHA-256 of the bytes must equal the file name; a file that cannot be read, does not match its name or is not JSON is damaged: counted, skipped, and the run is not `ok`; a file of no known kind is only counted — since v1.7.6.7 without a warning per file, because the kept originals of `gear`, `personalRecord`, `courses` and the zone files, which have no content rule, are among them), lets `garmin_import.days_from_originals()` build the days and writes each one through `garmin_bulk_json_import.store_day()`, the step the import uses; `garmin_bulk_writer` stays the only writer. It creates no original and touches no quality log, `raw/`, `summary/` or backup. The caller (`garmin_collector._run_bulk_rebuild()`) makes the summaries, quality-log entries and marks of the written days with `_finish_aggregates(summary, quality_data)` on the run's own quality log
- `entry["bulk"]` in the quality log (a dict, keys `intraday` and `aggregates` = import date) is not `entry["source"] == "bulk"`: the first marks days with data in the bulk store (series, daily values), the second marks days of the older JSON import and the entries made for export-only days. A day with an aggregates file but no `raw/` file has an entry with `source` `bulk` and `write` false, so the start-up integrity check does not call it missing
- `QUALITY_LOCK` must be held around all load-modify-save sequences
- `garmin_backup_common.py` (v1.7.6.2) is a leaf node — standard library only; it knows no path of `garmin_config` (a `BackupKind` carries them). `garmin_backup_bulk.py` imports it and `garmin_config` (lazily), nothing else; both never raise: an error ends in the returned numbers and the log, a failed bulk backup is a warning at the caller (`garmin_collector._run_bulk_backup()`), never a failed run. Since v1.7.6.2.1 `garmin_backup.py` and `garmin_backup_source.py` are thin shells over `garmin_backup_common` as well (they import it and `garmin_config`, no pipeline module)
- A ZIP of the bulk originals is never appended to (v1.7.6.2): a prefix with new files gets a new ZIP written next to the old one (`<xx>.zip.tmp`: old entries copied, new ones added), verified, swapped in with `os.replace`; a ZIP that cannot be read or fails its check is left untouched and reported (`damaged_zips`). The monthly ZIPs of the day-file backups (raw, source, bulk day files) are checked before anything is appended or replaced (v1.7.6.2.1, finding F-9): a ZIP that does not open or fails its check is left untouched, the month folder stays as the fallback and one error line names the ZIP; a ZIP a call began and could not finish is removed again, so the next run builds it from the folder. The append mode itself is not atomic: an interrupted append can still damage a ZIP, the next run reports it and appends nothing more
- Files of the bulk store come back only through `garmin_bulk_writer` (v1.7.6.2): the mirror import and the silo repair (#8/#9) hand bytes to `import_day_file()` / `store_original()`, which validate them, check the hash and write atomically; the importer and the repair never write a bulk file themselves
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
- API-Capability-Scan candidates reach `summary/` — and therefore `get()`/`list_fields()` — only if `garmin_normalizer.summarize()` is explicitly extended for that candidate; landing in `raw/` alone is not sufficient, `summarize()` is a fixed field list, not a generic passthrough. Seven candidates are wired this way: `body_weight`, `calories_resting` (v1.6.8 pilot), `hydration_ml`, `endurance_score`, `hill_score`, `fitness_age` (v1.6.8 Session 4), `blood_pressure` (six `bp_*` scalar fields, v1.7.1.14, Issue #7). The remaining 12 are exposed as archived in `raw/` (no value extraction) via `get_raw()`/`list_raw_fields()` instead — see "Raw-passthrough fields" below — rather than left archived-but-unreachable
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
| `get_archive_stats(base_dir)` | Wraps `garmin_quality.get_archive_stats()`. Empty dict on any failure |
| `get_source_stats(s)` | `{"total", "present"}` — all `source/` files vs. those within the last 180 days. INTENTIONAL DIRECT READ |

**Timer-Modi und ihre Kandidaten-Funktionen** — sieben Modi: Bulk Recheck wird in jedem Durchlauf zuerst geprüft; die übrigen sechs wechseln reihum (Repair → Quality → Fill → Source Backfill → Steps Backfill → Bulk Field Backfill), ein Modus ohne Kandidaten wird übersprungen (`panel_timer.py::_timer_loop`, `_mode_cycle`):

| Modus | Funktion | Kandidaten |
|---|---|---|
| Bulk Recheck | `timer_run_bulk_recheck(s)` | `source="bulk"` + `recheck=True` + ≤180 Tage, älteste zuerst |
| Repair | `timer_run_repair(s)` | `quality="failed"` + `recheck=True` |
| Quality | `timer_run_quality(s)` | `quality="standard"` + `recheck=True` + `source≠"bulk"` + ≤180 Tage |
| Fill | `timer_run_fill(s)` | Tage im Datumsbereich ohne Raw-Datei in `raw/` |
| Source Backfill | `timer_run_source_backfill(s)` | API-Tage (≤180d) ohne `source/`-Datei, kein Bulk |
| Steps Backfill | `timer_run_steps_backfill(s)` | `quality="high"` + `source="api"` + `fields.steps != "high"` (schließt `"medium"`/`"low"`/`"failed"`/fehlend ein) + `field_backfill_attempts.steps < FIELD_BACKFILL_ATTEMPT_LIMIT` (2, analog `bulk_recheck`s Attempts-Limit). Kein Alters-Cutoff mehr (die frühere 140-Tage-Grenze beruhte auf einer widerlegten Annahme, siehe `changelog/anchor_delivery_bulk-api-backfill-diagnose.md`). Self-terminierend — Kandidat verschwindet sobald `fields.steps` auf `"high"` steht, oder sobald das Attempts-Limit erreicht ist (v1.6.3; Filter auf Wertvergleich + generisches Attempts-Limit statt Alters-Cutoff korrigiert) |
| Bulk Field Backfill | `timer_run_bulk_field_backfill(s)` | `source="bulk"` + mindestens eines von `BULK_GAP_FIELDS` (`hrv`/`spo2`/`body_battery`/`respiration`/`training_status`/`race_predictions`/`max_metrics` — von `load_bulk()` strukturell nie extrahiert) ist `!= "high"` **und** dessen `field_backfill_attempts.<feld> < FIELD_BACKFILL_ATTEMPT_LIMIT`. Kein Alters-Cutoff, kein `recheck`-Flag — getrennt von `bulk_recheck`, das nur das 180-Tage-Fenster abdeckt. Voller Tages-Fetch (`_fetch_and_assess()`, alle 15 Endpunkte auf einmal — ein Bulk-Tag fehlt meist mehrere der 7 Felder gleichzeitig, ein einziger Fetch deckt alle ab), aber additiver Schlüssel-für-Schlüssel-Merge beim Schreiben (`garmin_merge.merge_field()`, dieselbe "nie einen nicht-leeren Wert überschreiben"-Primitive wie bei `steps_backfill`) statt vollem Ersetzen — Bulk und API nutzen für Felder, die Bulk selbst befüllt (z. B. `stress`), inkompatible Roh-Strukturen; ein voller Ersatz könnte ein Feld schlechter machen, obwohl das Tages-Gesamtlabel nicht sinkt (`_check_downgrade()` vergleicht nur das Label, nie einzelne Felder). Kein separater Downgrade-Check nötig — additiver Merge kann per Konstruktion nicht schlechter machen. Self-terminierend pro Feld: ein Tag bleibt Kandidat solange mindestens eines der 7 Felder noch nicht aufgegeben hat, auch wenn andere Felder ihr Limit schon erreicht haben (v1.7.3) |

All seven candidate functions return a sorted `list[date]` (oldest first) or
`None` if there is nothing to do. `panel_timer.py`'s `_timer_loop()` checks Bulk
Recheck first, cycles through the other six in rotation
and dispatches the picked batch to
`garmin_collector.py` via `GARMIN_SYNC_DATES` + a mode-specific ENV flag.

---

## Documented Exceptions

Intentional deviations from the invariants above. Each exception is stable by design — not a TODO.

| Exception | Module | Reason |
|---|---|---|
| `regenerate_summaries.py` writes directly to `summary/` | `export/regenerate_summaries.py` | Maintenance utility — runs offline, outside pipeline. `garmin_writer` is not importable in that context. Acceptable: one-off backfill, not a runtime path. |
| `regenerate_raw.py` reads/writes `quality_log.json` directly via `_load_quality_log`/`_save_quality_log` | `export/regenerate_raw.py` | Maintenance utility — runs offline, outside the live pipeline, analogous to `regenerate_summaries.py`. Uses `garmin_writer.write_day()` for `raw/`/`summary/` writes (unlike `regenerate_summaries.py`); direct quality-log access is needed to apply downgrade-protected replay. `QUALITY_LOCK` is held correctly around both read and write. |
| `garmin_validator.py` imports `garmin_config` | `garmin/garmin_validator.py` | `garmin_config` is a pure constants module with no project-module imports. `garmin_validator` needs `DATAFORMAT_FILE` path. Leaf-node status refers to pipeline modules — `garmin_config` is infrastructure. |
| `process_status.py` imports `garmin_config` (lazily, inside `is_mcp_running()`) | `process_status.py` | Same reasoning as `garmin_validator.py` above — needs `MCP_HTTP_PORT`, `garmin_config` is infrastructure, not a pipeline import. Kept lazy (not module-level) specifically so this Leaf-Node stays safe to import from `scheduler/daily_update.py` at any point in its startup sequence — a module-level import here would risk the same premature-`GARMIN_OUTPUT_DIR`-caching bug `daily_update.py` already guards against elsewhere (v1.7.2.4). |
| Controller timer functions read `quality_log.json` directly | `app/garmin_app_controller.py` — `timer_run_repair`, `timer_run_bulk_recheck`, `timer_run_quality`, `timer_run_source_backfill`, `timer_run_steps_backfill`, `timer_run_bulk_field_backfill` | Read-only analytical fast-path. No mutation, no ownership transfer, no `QUALITY_LOCK` required. `garmin_quality` provides no filtered-list API for these queries; adding one would inflate the module into a query gateway. |
| `PanelArchive._check_resting_hr_repair()` scans `raw/` and tests whether `source/` files exist | `app/panel_archive.py` | Read-only pre-flight check in GUI context (v1.7.5.7, removable), same category as `_check_schema_migration()`: scans the archive of the current settings through `garmin_repair_resting_hr.find_candidates(raw_dir, source_dir)`, writes nothing, no `quality_log.json` access. The folders come from `base_dir`, so it does not depend on what `garmin_config` was imported with. |
| `PanelArchive._check_track_migration()` scans `raw/` and the file names of `source/` and `bulk/aggregates` | `app/panel_archive.py` | Read-only pre-flight check in GUI context (v1.7.6.3, removable, marker `TRACK-MIGRATION v1.7.6.3`), same category as `_check_resting_hr_repair()`: `garmin_track_migration.pending(scan_archive(raw_dir, source_dir, agg_dir))` with the folders of the current settings, writes nothing, no `quality_log.json` access. The scan cannot check the coverage (the full preview does, in the collector); a day the migration leaves alone is offered again at every start until it is gone. |
| `PanelArchive._check_bulk_rebuild()` scans the `schema_version` of the files in `bulk/aggregates` and the file names of `bulk/source` | `app/panel_archive.py` | Read-only pre-flight check in GUI context (v1.7.6.5, removable, marker `BULK-REBUILD v1.7.6.5`), same category as `_check_track_migration()`: reads the whole number `schema_version` of every `garmin_bulk_agg_*.json` (a damaged file or a non-integer counts as nothing) and compares it with `garmin_bulk_writer.AGG_SCHEMA_VERSION`; asks only if at least one day has an older number and at least one JSON original `<xx>/<64 hex>.json` lies in `bulk/source`. Writes nothing, no `quality_log.json` access. The folders come from `base_dir`. The scan cannot know the coverage: a day the rebuild does not bring to the current number (the stored day is fuller than the originals, `kept`) is offered again at every start. |

---

## `garmin_source_quality.py`

Sole Owner of source quality assessment logic. **Leaf-Node — stdlib only** (no `garmin_config`, no pipeline imports).
Called by `garmin_source_writer` to guard `write_source()` against overwriting high-resolution source files.

| Function | Purpose |
|---|---|
| `assess_source(raw_data)` | Assesses whether a raw API response contains intraday data. Checks `heartRateValues`, `stressValuesArray`, `bodyBatteryValuesArray`. Returns `{"intraday_present": bool}` |
| `assess_source_from_file(source_path)` | Reads existing source file from disk and assesses it. Returns `None` if absent. Returns `{"unreadable": True}` if file exists but cannot be read/parsed (v1.6.0.4.9). Returns `{"intraday_present": bool}` on success |
| `compare_source(existing_assessment, new_assessment, force=False)` | Conservative guard decision. Returns `"write"` \| `"skip"` \| `"skip_warn"`. Truth table: None (absent) → write; `{"unreadable": True}` → skip_warn (v1.6.0.4.9); intraday absent → write; intraday present + new present → skip; intraday present + new absent → skip_warn. `force=True` (v1.7.1.7) short-circuits the entire table, always returns `"write"` |

---

## `garmin_source_writer.py`

Sole Owner of `garmin_data/source/` and `source_api_log.json`. Depends on `garmin_source_quality` + `garmin_config` + stdlib.
`garmin_config` and `garmin_source_quality` imported lazily inside each function — same pattern as `garmin_security.py`.
After each actual write in `write_source()`: lazy import of `garmin_backup_source.backup_source()` — non-fatal. `patch_source_field()` does the same after a successful patch (v1.7.5.6), so the backup never keeps a version without the patched field.
No longer a Leaf-Node (v1.6.0.4.6) — imports `garmin_source_quality` for the write guard.

| Function | Purpose |
|---|---|
| `write_source(raw_data, date_str, force=False)` | Writes unmodified API response to `source/garmin_source_YYYY-MM-DD.json`. Guard: reads existing file → `assess_source_from_file` → `assess_source` → `compare_source` → write / skip / skip_warn. Atomic: `.tmp` → `fsync` → `os.replace`. Triggers `backup_source()` only on actual write. Returns `bool`. Non-fatal. `force` (v1.7.1.7) passed straight through to `compare_source()` |
| `update_log(date_str, val_result, endpoints_fetched, endpoints_failed, size_bytes, raw_data=None)` | Upserts entry in `source_api_log.json`. Stores `intraday_present` when `raw_data` provided (via `garmin_source_quality.assess_source()`). Atomic write. Returns `bool`. Non-fatal |
| `patch_source_field(date_str, field, value)` | Additively merges one top-level field into an existing `source/` file (backfill paths only, never the normal sync) and annotates `backfilled_fields` in `source_api_log.json`. No-op without a `source/` file. Since v1.7.5.6 it calls `backup_source()` after a successful patch (lazy import, a failing backup is a warning and does not fail the patch). Returns `bool` |

---

## `garmin_silo_check.py`

Read-only drift detection across the data silos. **Leaf-Node — `garmin_config` + stdlib only.**
No writes. No imports of write modules. Repair delegation lives in `panel_archive.py`.

| Function | Purpose |
|---|---|
| `check_silos()` | Scans raw/, summary/, source/, quality_log.json, the file names in `bulk/aggregates` and `bulk/raw`, the marks of the quality log, the `source_files` of the intraday day files and the entry names of `backup/bulk/source/<xx>.zip` for silo inconsistencies. Returns finding lists, totals, counts, checked_at. Read-only. Lockless (atomic writes guarantee complete-file reads, §9a). A day with an aggregates file counts as *export data* (v1.7.6.1): it may have no `raw/` file, so its summary is neither an orphan (#5 `summary_without_raw` = summary without `raw/` **and** without aggregates) nor fine without a summary (#7 `raw_without_summary` = `raw/` **or** aggregates, but no summary). Since v1.7.6.2: **#8 bulk file lost** (`bulk_lost_intraday`, `bulk_lost_aggregates`: the quality log marks the day with `entry["bulk"]["intraday"]` / `["aggregates"]` and the file is missing from the store; a damaged file is not detected, a day without a quality-log entry has no mark) and **#9 original missing**: `bulk_originals_missing` lists the FIT originals for which `bulk/source/<xx>/<hash>.fit` is missing — named in `source_files` of an intraday day file (reads every intraday day file) or held by the backup of the originals (v1.7.6.2.1); `bulk_json_originals_missing` (v1.7.6.2.1) lists the JSON originals the backup holds and the store lacks. The backup is read through the entry names of the ZIPs in `backup/bulk/source` (ZIP directories only, nothing is unpacked, a damaged ZIP is skipped), because the `source_files` of an aggregates file are hashes of single source entries, not of the JSON files kept in `bulk/source`. A day file and its original lost together are found by one check. An original lost before it was ever backed up is not found unless a day file names it. A day with a lost aggregates file is not an orphan (#5): its summary is the last copy of the resolved export values (F-10). The keys of #1/#3/#5/#7 keep their names; `totals` gains `aggregates` (count of `garmin_bulk_agg_*.json` files) |

**Result structure:**

```python
{
    "raw_without_quality":    [date, ...],   # #1
    "source_without_raw":     [date, ...],   # #3
    "summary_without_raw":    [date, ...],   # #5 — no raw, no export data, and not marked as having export data
    "raw_without_summary":    [date, ...],   # #7 — raw or export data exists, summary missing
    "bulk_lost_intraday":     [date, ...],   # #8 (v1.7.6.2) — marked bulk.intraday, file missing
    "bulk_lost_aggregates":   [date, ...],   # #8 (v1.7.6.2) — marked bulk.aggregates, file missing
    "bulk_originals_missing": [str, ...],    # #9 (v1.7.6.2) — SHA-256 (sorted) of a FIT original the store lacks: named by an intraday day file or held by the backup
    "bulk_json_originals_missing": [str, ...],  # #9 (v1.7.6.2.1) — SHA-256 (sorted) of a JSON original the backup holds and the store lacks
    "checked_at": "ISO-8601",
    "totals": {"raw": int, "summary": int, "source": int, "aggregates": int, "quality_days": int},
    "counts": {one count per finding list above},
}
```

`garmin_app_controller` and the panel add up `counts` to decide whether the repair button is enabled; a caller may not assume that exactly four keys exist.

---

## `garmin_backup_source.py`

Sole Owner of `garmin_data/backup/source/`. Since v1.7.6.2.1 a thin shell over `garmin_backup_common`: it imports that, `garmin_config` and the standard library, no pipeline module.

**Invariant refinement (v1.6.0.4):**
- `garmin_backup.py` — Sole Owner of `backup/raw/` + `backup/log/` (previously: all of `backup/`)
- `garmin_backup_source.py` — Sole Owner of `backup/source/`

| Function | Purpose |
|---|---|
| `backup_source(date_str, force=False)` | Copies `garmin_source_YYYY-MM-DD.json` to `backup/source/`. Called by `garmin_source_writer` after write. Returns `bool`. Non-fatal. Since v1.7.5.6 every call consolidates against today's real month, and a file whose content differs from its ZIP entry replaces that entry — see `_consolidate_source_months()`. `force=True` (v1.7.1.7) additionally replaces an entry with identical content |
| `backfill_source()` | Copies all source files without a backup copy. One-time operation. Returns `{"copied", "skipped", "failed"}` |
| *(v1.7.6.2.1)* Shell | Every function here calls `garmin_backup_common` with a `BackupKind` built at each call (`area` `source`, prefix `garmin_source_`, ZIP prefix `source_backup_`, validity = JSON object, `log` = this module's logger, so log lines and test captures stay with the module). `_consolidate_source_months()` and `_zip_contains()` remain as module names (patch points of the tests). `backup_source`, `backfill_source` and `refresh_source_backups` hand the module's own `_consolidate_source_months` to the shared flow |
| `check_source_backfill_needed()` | Returns count of source files without backup. Fast check, no copy |
| `check_source_stale_backups()` | Returns count of source files whose backup copy differs from them (v1.7.5.6). Compares bytes with the copy in the month folder, otherwise CRC32 and size with the monthly ZIP entry — nothing is unpacked. A file without any backup is not counted (that is `backfill_source()`'s job), nor is a file that is not a JSON object. Fast check, no copy |
| `refresh_source_backups()` | Brings those copies up to date (v1.7.5.6): copies the changed files into their month folders, then consolidates once, which replaces the ZIP entries. Content-based and idempotent, never modifies `source/`; a file that is not a JSON object is reported and not copied over its backup; a file that cannot be read counts in `errors` (v1.7.6.2.1). Returns `{"refreshed", "unreadable", "errors"}` |

**Constants:**
- `SOURCE_LOG_SCHEMA_VERSION = 1` — increment when log entry structure changes
- `SOURCE_FILE_PREFIX = "garmin_source_"`

**`source_api_log.json` entry format** (written by `garmin_source_writer.update_log()`, one key per date, the file is replaced atomically):

| Key | Content |
|---|---|
| `fetched_at` | UTC time of the write, `YYYY-MM-DDTHH:MM:SSZ` |
| `source` | always `"api"` |
| `schema_version` | `SOURCE_LOG_SCHEMA_VERSION` |
| `validator_status` | `ok` / `warning` / `critical` / `unknown` |
| `validator_issues` | names of the fields with an issue (type `missing_optional` left out) |
| `endpoints_fetched`, `endpoints_failed` | endpoint labels that delivered / did not deliver data |
| `size_bytes` | approximate size of the response |
| `intraday_present` | bool, only when the caller passed `raw_data` |

---

## `garmin_api.py`

Garmin Connect access: login with the token / SSO flow, the endpoint calls, the device list. Leaf towards the pipeline (no quality log, no writer).

| Function / Symbol | Purpose |
|---|---|
| `GarminLoginError` | Exception raised on unrecoverable login failure. Replaces `sys.exit(1)` |
| `login(on_key_required, on_token_expired, on_mfa_required, on_sso_required)` | Logs in to Garmin Connect. Tries saved token first, falls back to SSO. MFA via callback. `on_sso_required` blocks Path 3 until user confirms — `None` (headless/standalone) starts SSO automatically. Returns client or `None` if cancelled. Raises `GarminLoginError` on failure. **Note:** `support-tools/garmin-login-probe/garmin_login_probe.py` calls this directly with `on_sso_required=lambda: True` — a signature change here requires updating that tool too |
| `api_call(client, method, *args, label)` | Single API call with random delay and stop-check. Returns `(data, success)`. Logs `log.debug(f"Fetching {label or method} ...")` before the call (v1.7.1.7) — silent at the normal sync's default `INFO` level, visible when a caller raises the root logger to `DEBUG` for its own duration (e.g. Force-Refetch's progress dialog, `panel_outputs.py`). Deliberate reuse of the existing logging mechanism rather than a new `progress`-callback parameter threaded through `fetch_raw()`/`_fetch_and_assess()`/`run_force_refetch_preview()` |
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

**Manual reset — removed (v1.7.2.3).** `panel_connection.py::_reset_token()` and its Reset Token button were removed as unused; there is no GUI-triggered manual `clear_token()` call anymore. `clear_token()` itself is unaffected — it is still invoked automatically by the `login()` flow (Paths 1/2/3b above) on an expired, rejected, or missing-key token. Deliberately did NOT clear an unresolved MFA block (v1.6.5.9) while it existed — a deleted token says nothing about whether the MFA problem itself is resolved, only a real successful SSO proves that; this distinction is now moot for the manual path since it no longer exists.

---

## `garmin_silo_repair.py`

Headless-callable core for the five repair paths `garmin_silo_check.check_silos()`
detects. Extracted from `panel_archive.py::_on_silo_repair()` (v1.6.5.7) — the
repair logic previously lived only as a Qt-bound closure, uncallable without a
live `PanelArchive`/`QApplication` instance. Not a Leaf-Node — imports the
sole-write-authority modules it delegates to (`garmin_writer`, `garmin_quality`,
`garmin_normalizer`, and since v1.7.6.2 `garmin_bulk_writer` and `garmin_backup_bulk`). Never writes files directly itself.

| Function | Purpose |
|---|---|
| `repair_silos(fresh)` | Repairs all five silo-drift categories from `fresh` (the return value of `check_silos()` — caller must re-scan immediately before calling, never act on stale findings). Returns `{"ok", "failed", "items"}` — `items` is one dict per processed date/action (`category`, `date`, `status`, plus category/status-specific extra keys; #8 adds `kind` `intraday`/`aggregates`, #9 adds `hash` and has `date` `None`; the items of a JSON original add `kind` `json`, v1.7.6.2.1). The keys `bulk_lost_intraday`, `bulk_lost_aggregates`, `bulk_originals_missing`, `bulk_json_originals_missing` are optional in `fresh` (read with a default of `[]`) |

**Delegation per category:**

| # | Finding | Repair |
|---|---|---|
| 1 | `raw_without_quality` | `garmin_quality._backfill_quality_log()` under `QUALITY_LOCK` |
| 3 | `source_without_raw` | In-process replay: `normalize()` → `summarize()` → `assess_quality()` → `write_day()` → `record_attempt()`, under one continuous `QUALITY_LOCK` hold (v1.6.5.7 precondition fix — previously released the lock between load and per-day save, see `CHANGELOG.md`). `write_day()` returning `False` is an `error` of the day (v1.7.6.1, F-4) |
| 5 | `summary_without_raw` | `Path.unlink()` — removes the orphan summary (a day with export data, or marked as having export data, is never listed here, see `check_silos()`) |
| 7 | `raw_without_summary` | Inline `summarize()` + `write_day()` for a day with `raw/`; a day with export data and no `raw/` file: `writer.rebuild_summary()`, `summary/` only (v1.7.6.1). `False` from the writer is an `error` of the day |
| 8 | `bulk_lost_intraday`, `bulk_lost_aggregates` (v1.7.6.2) | Runs first, so that #3 and #7 see a restored aggregates file. The copy from `backup/bulk` (`garmin_backup_bulk.read_day_copy`) is handed to `garmin_bulk_writer.import_day_file()` (validates, writes atomically); for an aggregates day `writer.rebuild_summary()` follows. Status `repaired`, `present` (the file is back by now, not counted), `no_backup` (no copy: counts as failed, the summary stays untouched), `error` (exception, the writer refuses the copy, a copy with a newer schema than the program knows, the summary cannot be made). No `QUALITY_LOCK`: the quality log is not touched, the marks stay |
| 9 | `bulk_originals_missing` (v1.7.6.2), `bulk_json_originals_missing` (v1.7.6.2.1) | After #8, FIT before JSON. `garmin_backup_bulk.read_original_copy(hash, ".fit" or ".json")` → `garmin_bulk_writer.store_original(hash, data, suffix)` (checks the bytes against the hash). Same statuses as #8; the items of a JSON original carry `kind` `json`. Day file and original lost together: one check finds both (the backup names the original too, v1.7.6.2.1) and one repair restores both |

`panel_archive.py::_do_repair()` only formats this structured result for the
GUI log — no pipeline logic remains in the panel.

**Test coverage (v1.6.5.8, Netz 2):** all four repair categories now covered
in `test_silo_repair.py` Section I — category #1's remaining edge case
(`_backfill_quality_log()` with a non-empty `raw_without_quality`, including
the silent-skip behaviour on a corrupt raw file and the true-error path on a
failed `_save_quality_log()`), and #3/#7's replay path against a
`normalize()`-capable raw-data fixture derived from a real archive file (not
an invented shape — see `KONZEPT_broker_uebersetzungshandbuch.md` for why
that distinction matters). Diagnosed empirically first via the external
`gla-netz2/` workshop before any assertion was written.

---

## `garmin_repair_resting_hr.py`

**Removable (v1.7.5.7).** One-time repair of the resting heart rate of days
that were imported from the Garmin GDPR export before v1.7.5.7: until then
`garmin_import` stored the export's 7-day average as the value of the day.
Everything that belongs to this repair carries the marker
`RESTING-HR-REPAIR v1.7.5.7` (grep for it); the removal list is in the module
docstring and in `MAINTENANCE_GARMIN.md`. Not a Leaf-Node — imports
`garmin_config`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`. Never
writes files directly itself (Sole-Write-Authority unchanged, same principle as
`garmin_silo_repair.py`).

| Function | Purpose |
|---|---|
| `find_candidates(raw_dir=None, source_dir=None)` | Read-only. Returns `{"repairable": [...], "no_source": [...]}` (sorted ISO dates) — `raw/` days in the unrepaired import form, split by whether a `source/` file exists (its content is not read here). `raw_dir`/`source_dir` default to the configured folders; the GUI popup and the scheduler pass the archive of the current settings. Unreadable raw files are skipped |
| `repair_resting_hr(dry_run=False, should_stop=None, quality_data=None)` | Always scans anew, never acts on an earlier finding. Returns `{"ok", "failed", "no_source", "items"}`; `items` has one dict per day (`date`, `status` = `repaired` \| `would_repair` \| `error` \| `skipped`, and `old`/`new`/`avg` or `reason`). `dry_run=True` writes nothing and lists old and new value. `should_stop` ends the loop after the current day. `quality_data`: the caller's quality log — marked and saved in place (see invariants below); without it the log is loaded here |

**Detection (content only, no marker in the quality log):** `raw/` `heart_rates`
holds exactly the three keys the import wrote (`restingHeartRate`,
`minHeartRate`, `maxHeartRate`) and `user_summary` has no
`lastSevenDaysAvgRestingHeartRate`. A repaired day always carries that key (a
value or `None`), so a second run finds nothing. The quality log's `source`
cannot be used for this — on an archive checked in v1.7.5.7 all imported days
carried `source: "api"`.

**Per repaired day:** the day value and the 7-day average are read from the
day's `source/` file (`heart_rates.restingHeartRate`,
`heart_rates.lastSevenDaysAvgRestingHeartRate`; only real numbers count —
booleans and text are treated as missing). Three places in `raw/` change:
`heart_rates.restingHeartRate` (key removed if `source/` has no value),
`user_summary.restingHeartRate`, `user_summary.lastSevenDaysAvgRestingHeartRate`.
The summary is rebuilt from the corrected raw with `summarize()`, written with
`garmin_writer.write_day()` (the raw backup follows, v1.7.5.6). min/max, intraday
data, quality label and source label are not touched. A day without a `source/`
file is reported and left unchanged. One failing day never stops the loop.

**Trigger chain:** `PanelArchive._check_resting_hr_repair(base_dir)` (popup
"Data Correction — Backup Required": count, backup hint, days without an
original; shown at every Sync Garmin start while correctable days exist) →
`sync.run_collector()` adds `GARMIN_RESTING_HR_REPAIR=1` to the run's
environment after a Yes → `garmin_collector.main()` step 3e →
`_run_resting_hr_repair(quality_data)`. `scheduler/daily_update.py` step 4b
(`_check_resting_hr_repair(base_dir)`) only warns with the number of days and
goes on — unlike the schema migration it never stops the run.

**Invariants:**
- `QUALITY_LOCK` is held from loading to the last save; the caller must not hold it (not re-entrant). The log is saved **once** after the loop, also when an unexpected exception ends it — days written so far are recorded.
- `quality_log.json` is touched only through `garmin_quality.touch_last_checked()` (sets `last_checked` and nothing else, so the checksum is unchanged) — the MCP cache then re-reads the corrected days. Failed days are not recorded.
- When the caller keeps its quality log in memory for the rest of the run (`garmin_collector.main()`), it must pass it as `quality_data`. A log loaded here would be overwritten by the caller's next save, the marks would be lost and the MCP cache would keep the old values (found on a real archive, fixed in the same version).

**Limits:** the export as a source (days without `source/`) is not built. The
per-field label `fields["heart_rates"]` in the quality log is not recalculated
(a day whose `source/` has no resting value would keep its old label).
`write_day()` replaces the raw file first and the summary second; if only the
second replace failed, `raw/` would already carry the marker (existing writer
behaviour, all callers).

---

## `garmin_track_migration.py`

**Removable (v1.7.6.3).** Migration of the mixed archive: days that the earlier
import (until v1.7.6) wrote into `raw/` and that the bulk field backfill
completed with API fields are made again from the archived Garmin originals
(`source/`); the export data stays in the bulk store. Everything that belongs to
it carries the marker `TRACK-MIGRATION v1.7.6.3` (grep for it); the removal list
is in `MAINTENANCE_GARMIN.md`. Not a Leaf-Node
(imports `garmin_bulk_writer`, `garmin_config`, `garmin_migration_snapshot`,
`garmin_normalizer`, `garmin_quality`, `garmin_writer`). Never writes files
directly (Sole-Write-Authority unchanged): `raw/` and `summary/` through
`garmin_writer`, the quality log through `garmin_quality`, the safety copy
through `garmin_migration_snapshot`. No API call, no login.

| Function | Purpose |
|---|---|
| `import_sections(raw)` | The sections of a raw dict that are in import form (sorted): keys a non-empty subset of what `garmin_import.parse_day()` writes for the section (`sleep`: exactly `{dailySleepDTO}`; `activities`: a list whose entries are all in form). No dict: `[]` |
| `classify_day(raw, has_source)` | `"migrate"` (import form, `source/` present), `"convert"` (import form, no `source/`, no other non-empty section), `"unresolved"` (import form plus API sections, no `source/`), `"api"` |
| `scan_archive(raw_dir=None, source_dir=None, agg_dir=None)` | Cheap, read-only: reads `raw/`, looks at file names in `source/` and `bulk/aggregates`. Returns `{"migrate", "convert", "unresolved", "unreadable", "no_aggregates": [ISO dates], "api_only": int}`. The GUI passes the folders of its settings |
| `pending(found)` | What a hook offers, from a scan: `{"ready": [...], "waiting": [...]}` (migrate days with / without an aggregates file). Used by the popup and the scheduler hint. Cannot know the coverage |
| `plan_migration(should_stop=None)` | Full preview, read-only. Returns `{"counts", "years", "items", "field_changes", "stopped"}`; one item per day (`date`, `kind`, `status` `ready` \| `blocked` \| `left`, `reason`/`keys` or `changes`). Includes the refresh days |
| `format_plan(plan, max_dates=5)` / `format_result(result)` | Log lines for the preview and for the result |
| `run_migration(dry_run=False, should_stop=None, quality_data=None)` | The only function that writes. Returns `{"ok", "migrated", "refreshed", "failed": [(date, reason)], "blocked": [(date, reason)], "unresolved", "convert_pending", "label_differs", "years", "snapshot", "log_saved", "stopped", "reason"}`. Always starts with a fresh preview. `quality_data`: the caller's quality log, marked and saved in place; without it the log is loaded here |

**Detection (content only):** the quality log's `source` cannot be used (the
bulk field backfill sets `api` on every day it completes). A day is an import day
when at least one of its sections is in import form; a day can be import form in
one section and API form in another (a day exists whose `heart_rates` is API
form while `sleep` and `stress` are import form), so the check runs per section.

**Coverage (preview, per day, before anything is written):** every non-empty
field of a section in import form must be held by the bulk store with the same
value (the store may hold more fields; lists are compared as the same entries in
any order, duplicates count — F-13); for a `migrate` day every other non-empty
section must equal the same section of `source/`. A day that fails is blocked
with the keys (`not_covered`), a day without a usable aggregates file is blocked
(`no_aggregates`: import the export first), unreadable files give
`raw_unreadable`, `source_unreadable`, `aggregates_unreadable`. A blocked day is
never touched.

**Refresh:** days with an aggregates file whose resolved summary differs from
`summary/` (ignoring `schema_version` and `generated_by`; a missing summary
counts) get `summary/` made again with `garmin_writer.rebuild_summary()`; `raw/`
stays.

**Per migrated day:** `normalize(copy(source), "api")` → `garmin_writer.write_day()`
(also makes the resolved summary) → the written raw file is read back and
compared. The day is checked again right before it is written. Label and `fields`
of the quality entry are not recalculated; a day whose recalculated label or
fields differ is only listed in `label_differs`.

**Trigger chain:** `PanelArchive._check_track_migration(base_dir)` (popup
"Migrate" / "Preview only" / "Not now"; shown at every Sync Garmin start while
`pending()["ready"]` is not empty) → `sync.run_collector()` sets
`GARMIN_TRACK_MIGRATION` (`1` or `preview`) → `garmin_collector.main()` step 3b2
(before 3c schema migration and 3e resting heart rate repair) →
`_run_track_migration(quality_data, preview)`. `"preview"` runs `plan_migration()`
and ends the run (no login, no fetch). The variable is removed with `os.environ.pop`
(T3: `garmin_app_standalone` sets it in `os.environ`, the same way as the resting
heart rate repair). Any error is a warning ("Track migration skipped"), the sync
goes on. `scheduler/daily_update.py` step 4c (`_check_track_migration(base_dir)`)
only warns with the number of days and goes on.

**Invariants:**
- A safety copy is made and checked before the first write; if it fails nothing is written (`reason: "snapshot_failed"`). No copy is made when there is nothing to do.
- `QUALITY_LOCK` is held from loading to the last save; the caller must not hold it (not re-entrant). The log is saved **once**, in a `finally`, also after an unexpected exception.
- `quality_log.json` is touched only through `garmin_quality.touch_last_checked()` for the written days (so the MCP cache re-reads them); no entry is created or recalculated.
- A day that fails stays untouched and the run goes on; the stop request is checked per day.
- A rerun finds what is left (detection by content); a migrated day is never found again.

**Limits:** the `convert` class (pure import days without `source/`) and the
`unresolved` class are reported, not changed. The scan of the popup reads every
`raw/` file (a few seconds on a large archive, on the GUI thread). The bulk timer
modes and the bulk steps of the sync stay in place for archives that still depend
on them.

---

## `garmin_migration_snapshot.py`

**Removable (v1.7.6.3, with the migration).** Sole owner of
`garmin_data/backup/migration/`. The raw backup keeps only the newest version of
a day, so a day rewritten by the migration would be in no backup in its old form;
the snapshot is a ZIP of everything the migration may touch (`raw/`, `summary/`,
`log/quality_log.json`), named `migration_YYYY-MM-DD_HHMMSS.zip` (suffix `_2` for
the same second). Not mirrored, not part of the silo check, never deleted by the
app. Imports `garmin_config`, `garmin_quality`, `garmin_writer`.

| Function | Purpose |
|---|---|
| `create_snapshot(should_stop=None)` | One ZIP per call, all or nothing: written to a temp file, free space checked (file sizes plus 10 MB), stop request checked per file, then read back (`testzip`, size and CRC of every entry against what was read from the archive, the set of entries, `MANIFEST.json` with time, program version and counts) and only then put in place with `os.replace`. A file that cannot be read stops the copy. Returns `{"ok", "path", "raw", "summary", "log", "bytes", "reason"}`; an archive without these files gives `ok` and no ZIP |
| `verify_snapshot(path)` | The same check for an existing ZIP, plus: only known entry names (no path tricks, valid dates). Returns `{"ok", "problems", ...}` |
| `list_snapshots()` | The ZIPs of the folder, oldest first (the oldest holds the original mixed state); temp files and foreign names are ignored |
| `restore_snapshot(path, dry_run=False, should_stop=None)` | The way back. Verifies the ZIP first (a damaged ZIP changes nothing), puts back only files that differ from the current ones (`unchanged` otherwise) through `garmin_writer.restore_day_files()`, leaves days that are not in the ZIP alone. Quality log: the entries of the restored days come from the ZIP, all other entries, devices and `first_day` stay, one save, new `last_checked` for the restored days; a day whose files could not be written keeps its entry. Returns `{"ok", "restored", "unchanged", "failed", "log_entries", "log_saved", "stopped", "reason", "problems"}` |

The caller of `restore_snapshot()` must not hold `QUALITY_LOCK` and must make sure
nothing else writes to `raw/` and `summary/` (no sync, timer paused). The command
line tool `support-tools/archive-maintenance/restore_migration_snapshot.py`
(`--list`, `--dry-run`, snapshot name; not part of the build, runs from the
source and needs Python) is the only caller in production code.

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
| `reload_schema()` | Reloads `garmin_dataformat.json` from disk. Not called in production — schema is already fresh at every app start (loaded at module import), and self-healing runs once right after that. Test-only utility |
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
| `RedactFilter` | `logging.Filter` — redacts both values from every `LogRecord`'s `msg` and string `args` as they pass through (tuple args element-wise; a single dict argument — which `logging` unwraps into `record.args` itself — value-wise, keys untouched). Always returns `True` — never suppresses a record, only mutates its text |

---

## `garmin_normalizer.py`

| Function / Constant | Purpose |
|---|---|
| `CURRENT_SCHEMA_VERSION` | int — summary schema version. Increment on field changes (5 since v1.7.6.6: section `alerts`, section `training` filled, field `training_status_code`) |
| `normalize(raw, source)` | Entry point. `source`: `"api"` or `"bulk"` |
| `summarize(raw)` | Produces compact daily summary. Writes `schema_version` into every file. Emits `log.warning()` when `sleepTimeSeconds` is `None` (structurally absent — distinct from `0`, which is a legitimate no-sleep-recorded value). v1.5.6.3. `hrv_last_night_ms` reads `hrvSummary.lastNightAvg`, no fallback (v1.7.1.13, Issue #8; was `lastNight` — nonexistent key — falling back unconditionally to `lastNight5MinHigh`, the night's peak 5-min reading, under a field name that promises an average). A missing `lastNightAvg` now surfaces as `None`. Contrast with `garmin_health_map.py`'s `hrv_last_night`/`live_nested` descriptor, which deliberately keeps a fallback to `lastNight5MinHigh` for the live-only snapshot path |
| `_normalize_api(raw)` | Normalises Garmin API raw dict |
| `_normalize_import(raw)` | Normalises bulk import raw dict. Remaps HR aggregate fields |
| `safe_get(d, *keys, default)` | Safe nested dict traversal |
| `_parse_list_values(lst, dict_key)` | Extracts numeric values from list-of-dicts (`dict_key: str` → dict-key lookup) or list/tuple items (`dict_key: int` → positional index, e.g. `dict_key=2` for a `[ts, status, value]` triplet). v1.7.1.13: previously always read `item[1]` for list/tuple items regardless of `dict_key` — a call site passing `dict_key=2` silently read the wrong element. All pre-existing callers pass `dict_key=1`, unaffected by the fix (Issue #6) |
| `_TRAINING_STATUS_TEXT`, `_latest_entry(entries)`, `_pick_entry(value)`, `_pick_metrics(value)`, `_first_text(*values)`, `_first_count(*values)` (v1.7.6.6) | Helpers of the sections `training` and `alerts` of `summarize()`: the number-to-text table of the training status; the latest of several entries (a readable `timestamp`, ISO text or milliseconds, beats none, the later beats the earlier, at equal time the smaller canonical JSON text wins; the same rule as `garmin_import._later_entry_wins`, kept apart because that is a Netz-2 core module and reads ISO text only); a dict as it is or the latest element of a list; the `max_metrics` element with the newest `generic.calendarDate`; the first non-empty string, the first whole number (never a boolean) |

---

## `garmin_writer.py`

| Function | Purpose |
|---|---|
| `write_day(normalized, summary, date_str)` | Sole write authority for `raw/` and `summary/`. Triggers `garmin_backup.backup_raw()` after successful write (lazy import, failure non-fatal); since v1.7.5.6 a day that is already in a monthly backup ZIP replaces its entry there when the content differs. Resolved summary (v1.7.6.1): a day with an aggregates file in the bulk store gets `summarize()` of the API data plus the export's values instead of the summary passed in (a key the API lacks or holds empty comes from the export as a whole, `garmin_merge.merge_field`; a section that both hold as a dict is filled field by field, one level deep, `_fill_fields` — v1.7.6.3, F-11: the API value stays when it is not empty, the export fills a field that is missing or `None`/`""`/`[]`/`{}`, `0` and `False` are values; `activities` keeps the whole-key rule); `raw/` keeps what was passed in. An aggregates file that cannot be read for an I/O reason → nothing is written (`raw/` and `summary/` stay as they are), `False`; a missing, damaged or newer-schema file counts as none. Returns `bool` |
| `write_summary_only(summary, date_str)` | Writes only `summary/`; `raw/` and its backup are never touched — not even the temp-file/replace path (v1.7.4.0.4). Used by `_run_schema_migration()`, which must never rewrite the frozen `raw/` file. Same temp-file-and-replace pattern as `write_day()`, same resolved summary for a day with export data (v1.7.6.1). Returns `bool` |
| `rebuild_summary(date_str)` | `summary/` only, derived from `raw/` (if the day has a file; an unreadable one → `False`) and the day's aggregates, resolved as in `write_day()` (v1.7.6.1). The way to a summary for a day without a `raw/` file (an imported export day) and to one that has to be made again (schema migration, repair, `regenerate_summaries.py`). Neither raw nor usable aggregates, an unreadable aggregates file, a date that is no date or a write error: `False` (logged). Returns `bool` |
| `resolve_preview(api_raw, date_str)` | Read-only (v1.7.6.3): what the resolution would give for a day, nothing is written. `api_raw` is the API data as `write_day()` would get it (may be empty). Returns `{"state", "export", "summary"}`: `"ok"` (usable aggregates file: `export` = its values normalised like an import day, `summary` = the resolved summary `write_day()` would write), `"none"` (no usable file: `export` `None`, `summary` of the API data alone) or `"unreadable"` (I/O error: both `None`; `write_day()` would write nothing). Used by the migration preview so the resolution is not copied |
| `restore_day_files(date_str, raw_bytes, summary_bytes)` | Puts exact bytes back (v1.7.6.3, the way back of the migration safety copy): atomic temp file and `os.replace` per file; `None` leaves that file alone; a date that is no date → `False`; a restored raw file triggers the raw backup, so the backup follows the restored version. No resolution, no normalisation. Returns `bool` |
| `read_raw(date_str)` | Reads raw file for a date. Used by self-healing loop only. Returns `{}` on failure |
| `read_summary(date_str)` | Reads summary file for a date. Used by schema migration loop. Returns `{}` on failure |

---

## `garmin_quality.py`

| Function | Purpose |
|---|---|
*Implementation split into `garmin/quality/_io.py`, `_assess.py`, `_scan.py`, `_maint.py`, `_stats.py` — all symbols re-exported from this facade. Callers import from `garmin_quality` as before.*

| `QUALITY_LOCK` | `threading.Lock()` — acquire around all load-modify-save sequences |
| `assess_quality(raw)` | Returns `"high"` / `"standard"` / `"failed"`. Pure function |
| `assess_quality_fields(raw)` | Returns per-endpoint quality dict. Pure function. Reuses `garmin_normalizer._parse_list_values()` to verify an intraday array actually parses into `[ts,val]` pairs (`[ts,status,val]`/`[ts,status,val,extra]` for `body_battery`, `dict_key=2`) before labeling a field `"high"` — a structurally malformed array falls through to the next applicable tier instead (v1.6.5.8, F8). `body_battery`'s `dict_key=2` call was broken until v1.7.1.13 (Issue #6) — see `_parse_list_values()` entry above. The `hrv` field's quality check reads `hrvSummary.lastNightAvg` (v1.7.1.13, Issue #8; was the nonexistent `lastNight` key, always falling to `"low"`), no fallback — consistent with `garmin_normalizer.summarize()`'s own `hrv_last_night_ms` field (see below), which reads the same corrected key. Downgrade reasons are collected under a reserved key inside the returned dict, extracted by `_maint.py` into `entry["field_downgrades"]` — never present in the dict actually stored as `entry["fields"]` |
| `KNOWN_FIELDS` | Constant (tuple, 14 names) in `quality/_assess.py`, re-exported here (v1.7.1.7). Single source of truth for the field names `assess_quality_fields()` assesses — also used by `quality/_fieldhash.py` for `compare_source_fields()` |
| `compare_source_fields(old_source, new_source)` | SHA-256 field-by-field comparison of two `source/`-shaped dicts (v1.7.1.7, `garmin/quality/_fieldhash.py`). Each field's value serialized via `json.dumps(..., sort_keys=True)` before hashing — key order never causes a false difference. Returns `list[str]` — names (from `KNOWN_FIELDS`) of fields that differ, in `KNOWN_FIELDS` order. Used exclusively by `garmin_collector.run_force_refetch_preview()` to show the user what actually changed after a deliberate Force-Refetch |
| `record_attempt(data, day, label, reason, written, source, fields, validator_result, device_id, device_name, prev_high)` | Public API — atomically calls `_upsert_quality` + `_save_quality_log`. Caller must hold `QUALITY_LOCK`. |
| `_upsert_quality(data, day, quality, reason, written, source, fields, validator_result, device_id, device_name, prev_high)` | Adds or updates day entry. Downgrade protection: `high` stays `high`. Stores `device_id` + `device_name` per entry. |
| `touch_last_checked(data, days)` | Sets `last_checked` to today on the entries of the given days (date objects or ISO strings) — nothing else: `quality`, `source`, `recheck`, `write`, `attempts`, `fields` and the log checksum stay as they are. Returns the number of entries touched; a day without an entry is skipped, never created. Does **not** save — the caller holds `QUALITY_LOCK` from load to save and saves once after its loop. Purpose: a day whose `raw/`/`summary/` content was corrected in place must be re-read by the MCP cache, which re-reads a day when its `last_checked` differs from the cached value (`mcp_update._sync_health_days`); rotation and recheck do not use `last_checked`. Generic — not specific to one repair (v1.7.5.7) |
| `record_bulk_intraday(data, days)` | Marks days whose heart-rate series are in the bulk store (v1.7.6): `entry["bulk"]["intraday"]` = today's date (import date) and `last_checked` = today — nothing else on the entry changes, so `quality`, `source`, `recheck`, `write`, `attempts`, `fields` and the log checksum stay as they are. `entry["bulk"]` is a dict of its own so later imports can add keys without touching `intraday`; a non-dict value is replaced. A day without an entry is skipped, never created. Returns the number of entries marked. Does **not** save — the caller holds `QUALITY_LOCK` from load to save and saves once. `last_checked` is what makes the MCP cache re-read the day (`mcp_update._sync_health_days`) |
| `record_bulk_aggregates(data, days)` | The same contract for the daily values of the export (v1.7.6.1): `entry["bulk"]["aggregates"]` = today's date and `last_checked` = today, nothing else changes. Shares `_record_bulk_mark()` with `record_bulk_intraday()` |
| `unmarked_bulk_days(data, days, key="intraday")` | The days of `days` that have an entry but no `entry["bulk"][key]` mark (`key` `intraday` or `aggregates`; v1.7.6.1, F-3). Looks only; a day without an entry is not listed, a non-dict `bulk` counts as unmarked. Returns sorted ISO strings |
| `catch_up_bulk_intraday(data, days)` / `catch_up_bulk_aggregates(data, days)` | Mark the still unmarked days of `days` (v1.7.6.1, F-3): make good a mark that failed or could not be made when the data were written. Days that carry the mark keep it and their `last_checked`. Return the number marked; do **not** save |
| `save_device_table(quality_data)` | Builds and writes `device_table.json`. Called after each sync and after device_id backfill. Groups entries by `device_id`; entries with `device_id=None` appear as `__unknown__` row. Sole write authority: `garmin_quality`. |
| `get_archive_stats(quality_log_path)` | Returns GUI stats dict: `total`, `high`, `standard`, `failed`, `recheck`, `missing`, `date_min`, `date_max`, `coverage_pct`, `last_api`, `last_bulk`, `integrity_warnings` |
| `_compute_checksum(data)` | SHA-256 over stable core fields (`date`, `write`, `quality`, `source`) of all day entries. Extended in v1.5.5. Migration bridge: `_compute_checksum_legacy()` (TODO: remove after v1.6) |
| `_compute_checksum_legacy(data)` | Pre-v1.5.5 algorithm (`date` + `write` only). Used once on load to detect planned upgrade — never for new saves |
| `_save_defective_log(data)` | Saves defective quality_log state to `AUTORESTORE_DIR` before auto-restore. Best-effort |
| `_save_unreadable_log(source_path)` | Saves an unparseable quality_log file to `AUTORESTORE_DIR` before it gets overwritten (v1.7.4.1, same purpose as `_save_defective_log` but for a file that cannot be read at all) |
| `_load_quality_log()` | Now returns `integrity_warnings: list[str]` — empty if checksum OK, year labels if mismatch, `["log unreadable"]` if the file could not be parsed at all (v1.7.4.1; restore from the newest valid monthly backup is attempted first, same path as a checksum mismatch — the migration-only `failed_days.json` read uses the same function but is excluded, stays empty). Also checks every entry's `date` via `_is_parseable_date()` on every load (not just once in `main()`) and adds a warning per unparseable one — deliberately moved into this function (v1.7.4.0.4, "Variante B") so the warning survives an independent `_load_quality_log()` call too, e.g. from the Archive Info panel's own refresh |
| `_save_quality_log(data, skip_backup)` | `skip_backup=True` suppresses backup trigger. Default `False` triggers `garmin_backup.backup_quality_log()`. Returns `True` when `quality_log.json` was written, `False` when the write failed (logged, never raised; v1.7.6.1) — a failed backup trigger afterwards does not change the result. Callers that ignore the value behave as before; the bulk-import finish and the mark catch-up evaluate it |
| `get_low_quality_dates(folder, known_dates)` | Scans `raw/` for files not in quality log |
| `_set_first_day(data, client)` | Determines and persists `first_day`. Never overwrites existing value. A device's `first_used` is only accepted if it parses as a real date (`date.fromisoformat`) — a malformed value is logged and skipped, falling through to the next source instead of becoming `first_day` and later crashing sync mode `auto` (v1.7.4.0.4; `"unknown"` was already skipped before) |

**Quality levels (v1.5.7+):**

| Level | Meaning | `recheck` default |
|---|---|---|
| `high` | Intraday data present | `false` — never re-downloaded |
| `standard` | Daily aggregates only — maximum available for this day | `false` unless `prev_high=true` and day ≤ 180 days old |
| `failed` | API error — no file | `true` until successful |

**Per-entry device tracking (v1.5.7+):**

Each quality log entry stores `device_id` (str) and `device_name` (str) — set by `garmin_collector` from `training_status → mostRecentTrainingStatus → recordedDevices[0]`. Entries without `training_status` (older devices) have `device_id = None`. The `device_table.json` file is derived from these fields after each sync.

---

## `garmin_force_refetch.py`

Sole Owner of `garmin_data/backup/force_refetch/` (v1.7.1.7). Snapshots the
archived `source/` file for a single day before a deliberate Force-Refetch
overwrite, and can restore it if the new fetch turns out worse than
expected. Deliberately separate from `garmin_backup.py`/`AUTORESTORE_DIR` —
different purpose (single-day pre-overwrite safety net for an intentional
freeze-guard bypass, not quality_log-wide defect recovery). Scope is
`source/` only, not `raw/` — for the `"api"` origin, `raw`/`summary` are
derived from `source` (`garmin_normalizer._normalize_api()` is a
pass-through), so a `source/` snapshot alone is sufficient to reconstruct
the day. Flat directory, one file per day — no monthly ZIP consolidation
(Force-Refetch is a rare, deliberate maintenance action, not a high-volume
daily path).

| Function | Purpose |
|---|---|
| `snapshot_source(date_str)` | Copies the current `source/garmin_source_YYYY-MM-DD.json` into `backup/force_refetch/` before the guard-bypassing overwrite. Returns `{"snapshotted": bool, "had_prior_data": bool}` — `had_prior_data=False` is a valid, expected case (day was previously `"failed"`, never written), not an error |
| `restore_snapshot(date_str)` | Restores `source/garmin_source_YYYY-MM-DD.json` from a previously written snapshot, overwriting the current `source/` file. No GUI entry point yet (v1.7.1.7) — deferred to a later session. Does not consult `compare_source()` — a deliberate restore-to-known-good-state is, like Force-Refetch itself, an intentional exception to that guard. Returns `bool` — `False` if no snapshot exists or on any error |

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
| `main()` | Full sync orchestration: negative `GARMIN_MAX_DAYS_PER_SESSION` rejected with a named error before anything else runs (v1.7.4.0.4 — previously silently reached `missing[:-1]` instead of meaning "unlimited") → import mode (0; `_run_bulk_import()`, own session log `garmin_bulk_<timestamp>.log` in `log/recent`, copied to `log/fail` when the run failed, v1.7.6) → Capability Scan mode (0b, delegated entry, own login, v1.6.8) → dirs → session log → quality load → bulk upgrade flagging → self-healing → schema migration → backup refresh (3d, v1.7.5.6) → resting-HR repair (3e, v1.7.5.7, `GARMIN_RESTING_HR_REPAIR=1`) → bulk marks catch-up (3f, v1.7.6.1, `_run_bulk_mark_catch_up()`) → login → devices → device_id backfill → source backfill (5c) → steps backfill (5d) → bulk field backfill (5e, `GARMIN_BULK_FIELD_BACKFILL=1`, v1.7.3) → first_day → date resolution → fetch loop → save. `known_dates`/`recheck_dates`/`bulk_upgrade_dates` built via `_valid_dated_entries()` (v1.7.4.0.4) — a quality-log entry with an unparseable date is skipped with a warning instead of raising before login; a `_day_counted` flag in the fetch loop prevents one day being counted in both the saved and the error tally |
| `_fetch_and_assess(client, date_str, enabled_candidates=None, force=False)` | Fetch → validate → normalize → assess. No file writes of its own beyond `write_source()` (see below). Returns `(label, normalized, summary, fields, val_result)`. `enabled_candidates` (v1.6.8) — optional list of API-Capability-Scan candidate method names, pre-filtered by the caller (double-gate); turned into `extra_endpoints` for `api.fetch_raw()`. `None` (default) — used by `_run_source_backfill()`, which does not take part in the Capability Scan (scope boundary, v1.6.8). `force` (v1.7.1.7) passed straight through to the internal `write_source()` call — cannot be applied afterwards separately, since `write_source()` is called internally |
| `run_capability_scan(client, window_days=7)` | Probes the 19 optional health-endpoint candidates (`garmin_api_capability.CANDIDATE_ENDPOINTS`) over the last `window_days` days. Runs entirely under `quality.QUALITY_LOCK` (reused, not a new lock — see Invariants). Per-candidate try/except — one failing candidate never aborts the rest. Payload discarded, only the tri-state result (`found`/`not_observed`/`error`) persisted via `garmin_api_capability.update_endpoint()`/`save_config()`. Returns `{"scanned", "found", "not_observed", "error"}` (v1.6.8) |
| `_check_downgrade(new_label, existing_entry)` | Compares new quality label against stored entry. Returns `(is_downgrade, existing_label, existing_source)`. Delegates the actual rank comparison to `quality.is_downgrade()` (v1.6.5.7 — canonical location, also used by `export/regenerate_raw.py` and `garmin_silo_repair.py`; previously duplicated in each) |
| `_run_steps_backfill(client, quality_data)` | Backfills `steps_series` for existing high-quality API days. Per day: `api_call()` → `merge_field()` → `normalize()`/`summarize()` → `write_day()` → `record_attempt()` (with `backfilled_fields`) → `patch_source_field()`. On `patch_source_field()` failure: one automatic retry, then `log.error()` (not `warning`) if it still fails — `source/` will not be auto-retried on a future run, since the candidate filter checks `fields` from `raw/`, already correct at that point (v1.6.5.7). All four per-day failure paths (missing `raw/` file, `get_steps_data` returning no data, `write_day()` failing, generic `except Exception`) call `quality.record_field_backfill_failure()` — the give-up counter `timer_run_steps_backfill()`'s candidate filter reads (v1.7.3). Fifth case, found via an external diagnostic tool: `record_attempt()` itself can be silently blocked by `_upsert_quality()`'s day-level downgrade guard even after `write_day()` succeeded (freshly assessed whole-day label ranks below the entry's stored one) — the success path re-reads the entry right after `record_attempt()` and calls `record_field_backfill_failure()` too if `fields["steps"]` didn't actually land as `"high"`, so the give-up limit still applies instead of an infinite retry (v1.7.3) |
| `_run_bulk_field_backfill(client, quality_data)` | Closes the structural gap `garmin_import.load_bulk()` leaves in `hrv`/`spo2`/`body_battery`/`respiration`/`training_status`/`race_predictions`/`max_metrics` (`BULK_GAP_FIELDS`) regardless of the day's age. Per day: `_fetch_and_assess()` (full 15-endpoint fetch) → every top-level raw key merged additively into the existing `raw/` file via `garmin_merge.merge_field()` (never overwrites a field bulk already populated, even in its own incompatible shape) → re-normalize/assess the merged result → `write_day()` → `record_attempt()` → `quality.record_field_backfill_failures()` (batched — one persist call, not one per open field) for every `BULK_GAP_FIELDS` entry still not `"high"`. No day-level downgrade check needed — additive merge cannot regress a field by construction. Never touches `bulk_recheck`'s own day-level `attempts`/`recheck` bookkeeping (v1.7.3) |
| `_write_assessed(normalized, summary, date_str, label)` | Writes pre-assessed day to disk. Returns `bool` — `False` is also the answer for a label that is not written on purpose (`failed`). In the fetch loop of `main()` a `False` for a writable label (`high`/`standard`) is an error of the day (v1.7.6.1, F-5): the existing quality-log entry of an export day stays (the downgrade guard keeps it, `recheck` unchanged), a day without an entry becomes `failed` with `recheck` and is tried again |
| `run_import(path, progress_callback, stop_event)` | Bulk import orchestration via `garmin_import.load_bulk()`. Returns `{"ok", "skipped", "failed"}` — a day with `quality: "failed"` now counts in `failed`, not `ok` (v1.6.5.8, Fix 3; previously only an actual exception in the loop incremented `failed`). `main()`'s delegated exit code for the import mode (`sys.exit(0 if result["failed"] == 0 else 1)`) follows this count. `_is_stopped()` checked first per day — an import can actually be aborted mid-way (v1.7.4.0.4, previously registered but never read). Date validated (`except (ValueError, TypeError)`) before any write. An existing day is protected via `_check_downgrade()` — not worse than the imported day survives, including equal quality from a non-API source (previously only `source == "api"` was protected, and only after `write_day()` had already run) |
| `_run_self_healing(quality_data)` | Revalidates days with stale schema version against local `raw/` files — no API call |
| `_run_schema_migration(quality_data)` | Rewrites outdated summary files from raw when `GARMIN_SCHEMA_MIGRATE=1` (set by `sync.run_collector()` after the popup, or — v1.7.6.4, opt-in `daily_update_auto_migrate` — by `scheduler/daily_update.py` step 7b after a checked safety copy of `garmin_migration_snapshot`). No API call. Uses `writer.write_summary_only()` (v1.7.4.0.4) — `raw/` and its backup genuinely untouched, not just by convention; `False` from the writer is a failed day (v1.7.6.1, F-4). A day without a `raw/` file but with export data (`bulk/aggregates`) is made again with `writer.rebuild_summary()` (summary only, v1.7.6.1); with neither it stays skipped. Log output per day `[i/total]` |
| `_run_backup_refresh()` | Step 3d in `main()` (v1.7.5.6), after the schema migration and before the login. For raw and source: `check_*_stale_backups()`; if anything differs from its backup copy, logs `Backup refresh (raw\|source): N outdated backup copy/copies — refreshing` and calls `refresh_*_backups()`. Content-based and idempotent, so there is no popup, quality-log marker or environment variable. Runs on every normal start — also without new days and when the login fails; the import mode and the capability scan return before it. No API call, never modifies `raw/` or `source/`. Non-fatal: any error is a warning. Catches up archives that were written before a rewritten day replaced its ZIP entry (v1.7.5.6) |
| `_run_resting_hr_repair(quality_data)` | Step 3e in `main()` (v1.7.5.7, removable), after the schema migration and the backup refresh, before the login. Runs only when `GARMIN_RESTING_HR_REPAIR == "1"` (set by `sync.run_collector()` after the popup was confirmed); the variable is removed with `os.environ.pop()` as soon as it is read — in T3 the process, and with it `os.environ`, lives on between runs. Starts `garmin_repair_resting_hr.repair_resting_hr(should_stop=_is_stopped, quality_data=quality_data)`: the run's own quality log is handed over like the backfills get it, because a log loaded by the repair would be overwritten by the next save of this run. No API call. Non-fatal: any error (also a missing module) is a warning `Resting HR repair skipped: …`; failed days are warned about with their number and stay offered at the next start |
| `_bulk_phases()` | Reads and removes `GARMIN_BULK_PHASES` (v1.7.6). Unset or blank → `{"json"}` (the import as before v1.7.6); otherwise a comma list of `json` / `intraday` as a set; anything else → `None`. Removed with `os.environ.pop()` because in T3 the process lives on between runs |
| `_run_bulk_import(path)` | Runs the chosen import phases and returns `{"failed": n}` for the exit code (v1.7.6, changed v1.7.6.1). `json` = `garmin_bulk_json_import.run_aggregates_import()` (daily values and the JSON originals into `bulk/aggregates` and `bulk/source`; since v1.7.6.8 it is called with `read_raw=_raw_for_comparison` and so compares every day of the export with its API day; before v1.7.6.1 `run_import()` into `raw/`, which stays in the module but is no longer started here), `intraday` = `garmin_bulk_import.run_intraday_import()` (heart-rate series into `bulk/raw`). `json` runs first (its `day_window` entries are the second source of the day windows for the intraday phase). `GARMIN_BULK_DRYRUN=1` (also removed when read) makes a preview of both phases. A stop request ends the json phase on its own and the intraday phase is not started. Exit code: a phase whose summary is not `ok`, or a finish that cannot be completed (`_finish_aggregates()` / `_mark_bulk_days()` return `False`), counts as one failure each; a rejected day (invalid, too little data) does not. After the phases (not after a preview) `_run_bulk_backup("after the import")` backs up the bulk store (v1.7.6.2); that never changes the exit code |
| `_raw_for_comparison(date_str)` (v1.7.6.8) | The API day of `raw/` for the comparison of the sources in the export import, or `{}` when there is none. It looks for the file first (`cfg.RAW_DIR / garmin_raw_<date>.json`) because `garmin_writer.read_raw()` warns on every missing file, and an export reaches further back than the API archive; an existing file is read with `writer.read_raw()` (a damaged one gives `{}` and is reported there). Handed to `run_aggregates_import()` as `read_raw` |
| `_finish_aggregates(summary, quality_data=None)` | After a real daily-values phase (the json phase of the import, v1.7.6.1; the rebuild, v1.7.6.5): under `QUALITY_LOCK` loads the quality log, `_apply_aggregates()`, one save. `quality_data` (v1.7.6.5) is the run's own quality log when the phase runs inside a sync (the rebuild): the entries are made and saved on that object, because a log loaded here would be overwritten by the next save of the run; `None` (the import run) loads the log as before. Returns `True` when everything is as it should be, `False` when a day could not be completed or the log could not be written (the next import run makes it good: it looks at the content). Nothing written, nothing rejected and nothing in the store → the log is not even loaded |
| `_apply_aggregates(qdata, written_days, insufficient_days, agg_days)` | The work of the finish on a loaded log (v1.7.6.1): `writer.rebuild_summary()` for every day just written and every store day without an entry or without a summary; a quality-log entry for every such day without one (`source` `bulk`, `write` false, label and fields from the day's values, validator result; an existing entry is never relabelled); an entry `failed` (`source` `bulk`, `write` false) for each day with too little data, so the Fill and Repair timers try the API; the mark `bulk.aggregates` with `last_checked` (`record_bulk_aggregates()` and `catch_up_bulk_aggregates()`). Returns `(changed, failed_days, counts)` |
| `_run_bulk_rebuild(quality_data, preview)` | Step 3b3 of the sync (v1.7.6.5, removable, marker `BULK-REBUILD v1.7.6.5`), after the track migration (3b2) and before the schema migration (3c): `garmin_bulk_rebuild.run_aggregates_rebuild(dry_run=preview, should_stop=_is_stopped)`, after a real run `_finish_aggregates(summary, quality_data)` on the run's own quality log. Runs when `GARMIN_BULK_REBUILD` is `1` (rebuild) or `preview` (only reports; `main()` then ends the run before the login, like the track migration); the variable is removed with `os.environ.pop()` as soon as it is read (T3). Step 3g backs up the rebuilt files at the same start. No API call, no login, no export, no safety copy. Non-fatal: any error is a warning (`Bulk rebuild skipped: …`) and the sync goes on; a day that could not be rebuilt keeps its stored state and is offered again at the next start |
| `_summary_days()` | The ISO dates that have a file in `summary/`, from the file names only (v1.7.6.1) |
| `_mark_bulk_days(days)` | Marks the days of the intraday phase and catches up the unmarked days of the bulk store (`_apply_bulk_marks()`), under `QUALITY_LOCK`, one save (import mode holds no quality log of its own). Returns `True` when the log is as it should be, `False` when marking failed or the log could not be written (v1.7.6.1, F-3; before, it returned nothing and a failure was only a warning): the series are stored either way and the next import run or sync start makes it good, but the run counts it as failed |
| `_apply_bulk_marks(qdata, written_days, silo_days)` | `record_bulk_intraday()` for the written days and `catch_up_bulk_intraday()` for every day with a file in the bulk store (`garmin_bulk_writer.list_days()`), then one save only when something was marked. The caller holds `QUALITY_LOCK` from the load. Returns `(ok, marked, caught_up)` (v1.7.6.1) |
| `_run_bulk_mark_catch_up(quality_data)` | Step 3f of the sync (v1.7.6.1, F-3): marks every day that has a file in the bulk store but no `bulk.intraday` mark, on the run's own quality log, saved at once under `QUALITY_LOCK` (before the login). No API call, no export. Non-fatal: any error is a warning and the next start tries again |
| `_run_bulk_backup(where)` | Step 3g of the sync (v1.7.6.2; also called at the end of `_run_bulk_import`): `garmin_backup_bulk.backup_all(should_stop=_is_stopped)` with the stop request of the run. Looks first and does nothing, silently, when the backup is complete; the first backup of a large store takes minutes and logs a line every 10 % of the folders. Non-fatal: any error or an unsuccessful result is a warning naming `where`, the next sync start tries again (before the login, no API call) |
| `_run_source_backfill(client, quality_data)` | Re-fetches API days from `cfg.SYNC_DATES` that have no `source/` file. Step 5c in `main()` — after login, triggered by `GARMIN_SOURCE_BACKFILL=1`. Non-fatal per-day errors. No-op if `SYNC_DATES` empty (v1.6.0.3) |
| `run_force_refetch_preview(client, date_strs)` | Force-Refetch, Phase 1 (v1.7.1.7). Per date: snapshot `source/` via `garmin_force_refetch.snapshot_source()` → `_fetch_and_assess(force=True)` (writes `source/`, guard bypassed) → `garmin_quality.compare_source_fields()` against the pre-fetch version. Does NOT write `raw/`/`summary/`, does NOT call `record_attempt()`, does NOT touch backups — those happen only in `commit_force_refetch()` for user-confirmed dates. Two-phase split exists because a one-shot write-then-restore model would have to unwind four silos (`source/`, `raw/`+`summary/`, `quality_log.json`, backup ZIP) on rejection; splitting fetch+compare from commit means nothing outside `source/` is touched until confirmed. Returns `list[dict]`, one entry per date: `date`, `error`, `had_prior_data`, `quality_before`, `quality_after`, `fields_changed`, plus `_normalized`/`_summary`/`_fields`/`_val_result` carried through for Phase 2. Per-date exceptions caught and recorded, do not stop remaining dates |
| `commit_force_refetch(preview_results, confirmed_dates, quality_data)` | Force-Refetch, Phase 2 (v1.7.1.7). For each `preview_results` entry: if `date` is in `confirmed_dates` — `_should_write()` → `_write_assessed()` → `record_attempt()` → `garmin_backup.backup_raw(force=True)` (only if written) + `garmin_backup_source.backup_source(force=True)` (always — `source/` was written in Phase 1 regardless of label); if NOT confirmed — `garmin_force_refetch.restore_snapshot()` reverts `source/` only, since Phase 1 touched nothing else. `_check_downgrade()` deliberately bypassed for confirmed dates — the user has already seen the before/after comparison, which is the human decision `_check_downgrade()` would otherwise stand in for. Returns `list[dict]`: `date`, `action` (`"committed"` \| `"reverted"` \| `"skipped_error"`), `error` |
| `_start_session_log()` | Opens session log file. Returns `(handler, path)` |
| `_close_session_log(fh, path, had_errors, had_incomplete)` | Closes handler, copies to `log/fail/` if errors present |
| `_start_force_refetch_log()` | Opens a rolling Force-Refetch log file under `log/force_refetch/` (v1.7.1.7) — exact shape of `_start_session_log()` above, own directory (`cfg.LOG_FORCE_REFETCH_DIR`, own `LOG_FORCE_REFETCH_MAX = 30`, kept separate from `log/recent/` since Force-Refetch is a distinct, rare maintenance action, not a normal sync session). Fixed at `DEBUG` level (not caller-configurable) — deliberately matches the level the GUI worker raises the root logger to during the run, so the file and the live progress dialog show the same detail. Returns `(handler, path)` |
| `_close_force_refetch_log(fh)` | Closes the Force-Refetch log handler, enforces `LOG_FORCE_REFETCH_MAX` rolling limit. No `log/fail/`-style error-copy step — the dedicated directory is already small and rarely populated, a separate failure copy would be redundant |

**Bulk recheck logic:**

All days with `source: bulk` + date ≤ 180 days old are automatically flagged `recheck: true` on every startup (Step 3) — quality is irrelevant, source is the trigger. In Step 7, bulk recheck days are collected into `bulk_upgrade_dates` and always excluded from `local_dates` — regardless of `REFRESH_FAILED`.

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
| `load_bulk_with_entries(path, read_hook=None, inventory=None)` | Like `load_bulk()`, but yields `(raw dict, entries)` per day (v1.7.6.1): `entries` is the dict `{"uds", "sleep", "readiness", "activities", "health_status", "alert_events"}` (the last two since v1.7.6.7, only the parts the export has for the day) the day was built from, so the caller can form the proof of origin per entry. `read_hook(name, data)` is called with the bytes of every JSON file before it is parsed (to hash and keep the originals); it must not raise — an exception ends the iteration like any unexpected error (logged). `inventory` (a dict, v1.7.6.7) is filled with `build_inventory()` of the file list before the first day comes out; while the files are read, `unreadable` (not readable or not JSON) and `too_large` (over `MAX_JSON_BYTES`, 64 MB: not read, not hashed, not passed to the hook; warned about without a name) count up in it. Besides the four first kinds the files of `_SAVED_FAMILIES` (`gear`, `personalRecord`, `courses`, `zones`) go through the hook and nothing else happens to them. `load_bulk()` is the same generator without the extras |
| `parse_day(entries, date_str)` | Assembles canonical raw dict from export entries. Resting heart rate (v1.7.5.7): `user_summary.restingHeartRate` is the export's value of the day (`currentDayRestingHeartRate`) — an absent day value stays empty, never replaced by the average; the export's own `restingHeartRate` is its 7-day average and is kept as `user_summary.lastSevenDaysAvgRestingHeartRate` (not in `heart_rates`, so the three-key import form of older days stays recognisable). Days imported before v1.7.5.7 are corrected by `garmin_repair_resting_hr.py`. The readiness `score` is read (v1.7.6.5; before, `parse_day` stored `None` and dropped it) and passed on as it is, no type check. Since v1.7.6.7 two optional sections: `health_status` (the entry of the day as delivered) and `alert_events` (the list of pulse alert events of the day as delivered, in the order of `abnormalHrEventGMT` and then of the canonical text, so the import and the rebuild write the same file); a day without such an entry has neither key |
| `detect_kind(data)` (v1.7.6.5) | The kind of a parsed export file from its content, not its name: `"uds"` (an entry with `totalSteps` and `uuid`), `"sleep"` (`sleepStartTimestampGMT` or `deepSleepSeconds`), `"readiness"` (`acwrFactorPercent` or `recoveryTimeFactorPercent`), `"activities"` (the wrapper `summarizedActivitiesExport`), `"health_status"` (an entry with `metrics` and `outliersCount`, v1.7.6.7), `"alert_events"` (`abnormalHrEventGMT`, v1.7.6.7). A kind counts if the rule meets at least one entry; no kind or several → `None`. Something that is not a list → `None`, entries that are not objects are skipped, the date is not checked. Pure: the input is not changed, nothing is logged. The files kept in `bulk/source` carry only their hash as name, so the rebuild needs this. The kept families (`_SAVED_FAMILIES`) have no rule: their layout was not seen, so they stay `None` |
| `days_from_originals(originals, on_unrecognised=None, on_conflict=None)` (v1.7.6.5) | Like `load_bulk_with_entries()`, but from files already read that carry no path (`originals` = iterable of `(label, parsed JSON)`, the caller's order decides): the kind of each file from `detect_kind()`, a file of no known kind goes to `on_unrecognised(label)` and is skipped. Yields `(raw dict, entries)` per day, sorted by date. `on_conflict(kind, date_str)` is called when a UDS or sleep entry replaces a different one of the same date |
| `build_inventory(names)` (v1.7.6.7) | What an export holds in JSON files, from the file names alone: `{"read": {kind: files}` for every kind of `_KINDS` (0 where there is none), `"kept": {family: files}` for every family of `_SAVED_FAMILIES`, `"unknown": {"files": n, "folders": [...]}` (the JSON files of no known kind and the sorted folders they lie in; a folder with an `@` is shown as `<hidden>`, a file at the top as `(top level)`), `"unreadable": 0, "too_large": 0}`. Only names ending in `.json` count. Counts and folder groups only — never a file name, because the names carry the account's e-mail address. Pure: nothing is read, logged or changed. The preview and the import call it through `load_bulk_with_entries()`, so both show the same |

All per-entry loops (UDS, sleep, readiness, health status, alert events, activities) skip a malformed
entry that isn't an object (a bare string/number in the export's own list)
with a warning naming it, instead of crashing the whole `load_bulk()`
generator and silently yielding zero days (v1.7.4.0.4).

**Several entries for one date (v1.7.6.5):** for readiness the entry with the latest `timestamp` wins, whatever order the files were read in (`_later_entry_wins()`: an entry with a readable `timestamp` beats one without, a later one an earlier one; equal time, or none on both sides → the smaller canonical JSON text, so the choice is fixed). Only `YYYY-MM-DD` + `T` or a space + `HH:MM:SS` is read (fraction and zone are ignored; `datetime.fromisoformat` reads `.0` only from Python 3.11, the README says 3.10+). A day with one readiness entry is unchanged. UDS and sleep keep "the entry of the file read last wins", so two files with different entries of one date would give an order-dependent result (none was found in the export measured; the rebuild reads in hash order and counts such a day in `conflicts`). The order of the activities of a day follows the order of the files given. The import reads by name (`load_bulk()`, `_collect_entries()` over `_KINDS`), the rebuild by content (`days_from_originals()`); both use `_index_file()` and `_days_from_entries()`, so they build the same day.

**Supported export files:**

| File | Location in export | Content |
|---|---|---|
| `UDSFile_*.json` | `DI-Connect-Aggregator/` | Steps, HR, calories, stress |
| `*_sleepData.json` | `DI-Connect-Wellness/` | Sleep stage durations |
| `TrainingReadinessDTO_*.json` | `DI-Connect-Metrics/` | Training readiness |
| `*_summarizedActivities.json` | `DI-Connect-Fitness/` | Activity summaries |

This section lists only what `garmin_import.py` reads. The layout of the export, the meaning of its fields, its quirks and its differences from the API data are described in `REFERENCE_GARMIN_EXPORT.md`.

**Not extracted by `load_bulk()` (JSON files only):** intraday HR, stress curve, body battery curve, SpO2 series, respiration series, HRV details, training status. Bulk data always results in `standard` quality — never `high`. The heart-rate series of the same export (FIT files) are read by a separate phase, `garmin_bulk_import.py` (below), into the bulk store — not into `raw/`.

---

## `garmin_bulk_json_import.py`

Daily-values phase of the Garmin export import (v1.7.6.1): reads the JSON files of the export (UDS day aggregates, sleep data, training readiness, activities and, since v1.7.6.7, health status and pulse alert events) and writes the values of every day into the bulk store, `bulk/aggregates` — not into `raw/`. Orchestrates only: `garmin_import` reads the export, `garmin_validator` checks a day, `garmin_quality.assess_quality()` is the only quality call, `garmin_bulk_writer` is the only writer. Touches no quality log, `raw/`, `summary/` or backup; the caller (`garmin_collector._finish_aggregates()`) makes the summaries and the quality-log entries of the written days.

| Function | Purpose |
|---|---|
| `run_aggregates_import(path, dry_run=False, should_stop=None, read_raw=None)` | Hashes every JSON file of the export (SHA-256 of the bytes) and keeps it as an original in `bulk/source/<xx>/<hash>.json`; builds every day as the old import did (`parse_day`); a day invalid (validator `critical`) or with too little data (quality `failed`) is counted as rejected and not stored (a too-little-data day is listed in `insufficient_days` so the API may still deliver it); every other day is written with `write_aggregates` plus `day_window` (the four `wellnessStart/End` fields of the UDS entry, GMT and local, the second source of the day boundaries for the heart-rate phase). `should_stop` is asked before every day. Never raises: errors go into `summary["error"]`. Returns a dict of numbers and dates (`inventory` (v1.7.6.7, see `build_inventory()`), `originals`, `days` with `new`/`changed`/`unchanged`/`kept`/`failed`, `rejected` with `invalid`/`insufficient`, `days_with_window`, `written_days`, `insufficient_days`, and since v1.7.6.8 `comparison`: `None` without `read_raw`, else the counters of the comparison of the sources, see `compare_day()`); `ok` is false only for what a rerun can mend (an error, a day or an original that could not be written) — a rejected day is no failure. `dry_run=True` does the same work and creates and writes nothing, not even folders |
| `format_summary(summary, dry_run)` | The summary as text lines (counts only; no name from the export appears, the names carry the account's e-mail address). Since v1.7.6.7 it includes the inventory lines, since v1.7.6.8 the lines of the comparison (`comparison_lines()`) when the run compared |
| `inventory_lines(inventory)` (v1.7.6.7) | The inventory as text lines: one per known kind (`read, N file(s)`), one per kept family (`kept only, not read, N file(s)`), one `not recognised — N JSON file(s) in M folder(s): …` (the first 20 folders, then `…`), and, if any, one for files not readable or over the size limit. `[]` for no inventory |
| `compare_day(export_day, api_day)` (v1.7.6.8) | One day of the export against the same day of the API (`raw/`), field by field (pure function). Returns `{key: "equal" \| "added" \| "differ"}` for the fields of `COMPARE_FIELDS` the export has a value for: `equal` within the tolerance, `added` the API day has no value, `differ` both have one and they are further apart. A field the export has no value for does not count (both empty, or only the API has one). 0 is a value, a boolean is no number, a list of numbers counts with its maximum. Fields (key: export path / API path, tolerance): `steps` `user_summary.totalSteps` both, 0; `resting_hr`, `min_hr`, `max_hr` `user_summary.restingHeartRate` / `minHeartRate` / `maxHeartRate` both, 0; `stress_avg` `stress.averageStressLevel` / `stress.avgStressLevel`, 0; `sleep` sum of `sleep.dailySleepDTO.deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds` both, 60 s; `floors` `user_summary.floorsAscended` both, 1. The API paths were measured on an archive (the pulse extremes of an API day are in `user_summary`; `heart_rates` holds them on few days only) |
| `empty_comparison()`, `comparison_lines(comparison)` (v1.7.6.8) | The counters (`days_compared`, `days_without_api`, per field `equal`, `added`, `differ` and the first three differing days in date order) and their text: one header line (`compare: export against the API files in raw/ — N day(s) compared, M without an API file (not compared); nothing is changed or stored`) and one line per field, with the differing days and `, …` when there are more than three. Counts and dates only. The comparison is made in the day loop of the import, before the day is checked, so also for a day that is rejected; it is not part of `store_day()` (the rebuild has no API day to compare with) |
| `store_day(day, entries, imported_at, dry_run, summary)` (v1.7.6.5) | The step per day, taken out of the loop of `run_aggregates_import` so that the import and the rebuild (`garmin_bulk_rebuild`) share it: validator (`critical` → rejected as invalid), quality check (`failed` → rejected, the date goes to `insufficient_days`), then the aggregates (the day plus `day_window`) and `entry_hashes`, written with `write_aggregates` or, in a preview, only compared. Counts into `summary`; never raises on a rejected day |
| `empty_summary(dry_run)` (v1.7.6.5; was `_empty_summary`) | The result dict with all counters at zero; `garmin_bulk_rebuild` extends it |
| `entry_hashes(entries)` | The sorted SHA-256 of every source entry of a day (UDS, sleep, readiness, health status, each activity, each alert event; canonical JSON with its kind in front, `alert_event` for an alert event) — the proof of origin (`source_files`) of an aggregates file: an export with more entries for a day updates it, the same entries change nothing, fewer never replace a fuller day |
| `day_window(entries)` | The four window fields of the UDS entry as a dict, `None` unless all four are text |

A rerun with the same export changes nothing.

---

## `garmin_bulk_rebuild.py`

Rebuild of the daily values (v1.7.6.5, removable): builds the days in `bulk/aggregates` again from the JSON originals kept in `bulk/source`, without the export — so a change of the parser or of `AGG_SCHEMA_VERSION` reaches days that were imported earlier, also when the export ZIP is gone. Orchestrates only: `garmin_import.days_from_originals()` builds the days, `garmin_bulk_json_import.store_day()` checks and writes each one, `garmin_bulk_writer` is the only writer. Touches no quality log, `raw/`, `summary/` or backup, and creates no original; the caller (`garmin_collector._run_bulk_rebuild()`) makes the summaries, log entries and marks.

| Function | Purpose |
|---|---|
| `run_aggregates_rebuild(dry_run=False, should_stop=None)` | Reads the `.json` originals in the order of their hash (a fixed order). A file is used only if the SHA-256 of its bytes equals its name and it is JSON; otherwise it is damaged (counted, listed by the first 12 characters of its hash, skipped). FIT originals are only counted. A file whose kind `detect_kind()` does not recognise is counted, listed and skipped, never guessed (logged on debug level only since v1.7.6.7; the summary line says the kept originals of the families without a content rule are among them). Where two originals hold different UDS or sleep entries of one date, the one read later wins and the day is counted in `conflicts`. Then every day goes through `store_day()`. `should_stop` is asked before every original and every day. Never raises: an error goes into `summary["error"]`. Returns the dict of `garmin_bulk_json_import.empty_summary()` plus `originals` with `fit` / `damaged` / `unrecognised` / `bytes`, `conflicts`, `damaged_files`, `unrecognised_files`; `ok` is false for an error, a failed day or a damaged original, not for a rejected day or a file of unknown kind. `dry_run=True` does the same work and creates and writes nothing, not even folders |
| `format_summary(summary, dry_run)` | The result as text lines (counts, dates and the first 12 characters of a hash only) |

A day with the same original files and the current schema is `unchanged`, an older schema `changed` (the new `imported_at` is written), a stored day that is fuller than the originals `kept`. A rerun with nothing changed changes nothing. Trigger chain: `PanelArchive._check_bulk_rebuild()` (popup "Rebuild" / "Preview only" / "Not now", shown at every Sync Garmin start while a day has an older `schema_version`) → `sync.run_collector()` sets `GARMIN_BULK_REBUILD` (`1` or `preview`; not asked after "Preview only" of the track migration, no live fetch after a rebuild preview) → `garmin_collector.main()` step 3b3 → `_run_bulk_rebuild()`. The headless `daily_update.py` shows no popup and does not set the variable.

---

## `garmin_bulk_import.py`

Intraday phase of the Garmin export import (v1.7.6). Orchestrates the four modules below; touches no quality log, backup or API store.

| Function | Purpose |
|---|---|
| `run_intraday_import(path, dry_run=False, should_stop=None, keep_types=KEEP_TYPES)` | Reads the FIT files of the export (ZIP, folder, inner ZIP or single `.fit`), stores the originals of the kept FIT types (32, 49, 44, 68, 58, 79, 41) and writes one bulk day per local day with heart-rate samples. `should_stop` is asked once per file and once per day. Never raises: errors go into `summary["error"]` and `ok=False`. Returns a dict of numbers (`scan`, `rejected`, `by_type`, `originals`, `days`, `samples`, `unknown_days`, `planned_days_without_samples`, `written_days`) — no entry name appears in it. `dry_run=True` creates and writes nothing, not even folders |
| `format_summary(summary, dry_run)` | The summary as text lines (counts only) |

Day windows (v1.7.6.1): from `raw/stats` of the archive; a day whose raw file has no usable window, or that has no raw file at all, gets the window the daily-values phase stored with its values (`day_window` in `bulk/aggregates`) — the API's window always wins where it is usable. The status `unreadable` of a day file counts as a failed day in the summary.

A rerun with the same export changes nothing; part of an export never shrinks a day. Stopped while the files are read: no day is written, the originals read so far stay; stopped between two days: the days written stay.

---

## `garmin_bulk_export_scanner.py`

Leaf node. `iter_fit_files(path, stats=None)` yields `(sha256 hex, bytes)` once per different content, sorted by path; `ScanStats` counts `fit_seen`, `fit_yielded`, `duplicates`, `oversize`, `unreadable_entries`, `zips_opened`, `zips_unreadable`, `too_deep`, `ignored`. Limits `MAX_ZIP_DEPTH = 3`, `MAX_FIT_BYTES = 64 MB`. Inner ZIPs go through an anonymous `tempfile.TemporaryFile`. `FileNotFoundError` if the path does not exist.

---

## `garmin_bulk_fit_reader.py`

Leaf node. `parse_fit(data, wanted=())` → `FitFile(file_type, time_created, messages)`. The whole file is checked first (signature, header size, length, header CRC if set, file CRC); `FitFormatError.reason` is one of `not_fit` / `truncated` / `crc` / `structure`. Invalid base-type values become `None`. No plausibility checks, no time conversion.

---

## `garmin_bulk_normalizer.py`

Leaf node, pure calculation. `plan_days(windows)` → `BoundaryPlan`: the boundary at the start of a day is the local midnight taken to UTC with the end offset of the previous full-day window; a boundary that rule cannot give comes from the neighbours; a day with an unknown boundary is listed in `unknown` and gets no samples. `has_window(stats)` (v1.7.6.1) is the test `plan_days()` applies to every window (all four fields, plausible offsets, end after start), for a caller with two possible sources of a day's window. `file_samples(records)` / `complete_timestamp()`: 16-bit timestamps are completed by the nearest distance modulo 65536; records without heart rate or with 0 are dropped and counted. `SampleCollector` assigns samples to days (duplicate seconds: the file with the smaller `(time_created, hash)` wins; same and conflicting duplicates are counted separately); `iter_days()` yields one `DaySamples` at a time.

---

## `garmin_bulk_writer.py`

Sole owner of `garmin_data/bulk/`. Day file `bulk/raw/garmin_bulk_YYYY-MM-DD.json` (compact JSON, `schema_version` 1: `date`, `generated_by`, `origin`, `imported_at`, `utc_offset_hours`, `utc_offset_end_hours`, `dst_transition`, `offset_source`, `source_files`, `duplicates`, `sections.intraday.heart_rate {count, values [[ms UTC, bpm]]}`); aggregates file `bulk/aggregates/garmin_bulk_agg_YYYY-MM-DD.json` (v1.7.6.1, compact JSON, `schema_version` 2 = `AGG_SCHEMA_VERSION` (1 = before v1.7.6.5, when the training readiness `score` was not read; a file with 1 stays readable, and with the same files an `update` writes it again as 2): `date`, `generated_by`, `origin`, `imported_at`, `source_files` (SHA-256 of every source entry of the export that went into the day — UDS, sleep, readiness, each activity; not of the JSON files kept in `bulk/source`; sorted), `aggregates` = the day's values as `garmin_import.parse_day` delivers them, plus `day_window`); originals in `bulk/source/<xx>/<sha256>.fit` or `.json`. The two kinds of day file never touch each other. `_compare()` is the one place that decides `unchanged` / `update` / `smaller` / `newer` for both.

| Function | Purpose |
|---|---|
| `write_day(plan_day, day_samples, imported_at=None)` | → `written` / `unchanged` / `kept` / `failed`. Atomic (`.tmp` → `fsync` → `os.replace`, up to 5 tries on a lock); never raises |
| `day_status(date_str, source_files)` | `new` / `unchanged` / `update` / `smaller` / `newer` / `unreadable` (the file cannot be read for an I/O reason: not touched, a write answers `failed`; v1.7.6.1, F-1) |
| `list_days()` | The dates of the day files in `bulk/raw`, from the file names only: nothing is read, a damaged or unreadable file is listed too, no folder is created. `[]` (with a warning) if the folder cannot be listed (v1.7.6.1, F-3) |
| `write_aggregates(date_str, aggregates, source_files, imported_at=None)` | → `written` / `unchanged` / `kept` / `failed`, the same rules and the same atomic write as `write_day` (v1.7.6.1) |
| `aggregates_status(date_str, source_files)` | The same six states for the aggregates file |
| `read_aggregates(date_str)` | The stored aggregates file as a dict, `None` if there is none or it cannot be read |
| `load_aggregates(date_str)` | `(state, dict \| None)`, `state` `missing` / `damaged` / `unreadable` / `ok` — the only way to tell a damaged file from an unreadable one (the same states as the day loader) |
| `list_aggregate_days()` | The dates of the aggregates files, from the file names only |
| `store_original(file_hash, data, suffix=".fit")` / `original_present(file_hash, size, suffix=".fit")` | `written` / `present` / `failed`; the name must be a 64-character SHA-256; `suffix` is `.fit` or `.json` |
| `store_original_json(file_hash, data)` / `original_json_present(file_hash, size)` | The same for a JSON file of the export (`bulk/source/<xx>/<hash>.json`) |
| `import_day_file(kind, date_str, data)` (v1.7.6.2) | Takes over one day file (`kind` `intraday` → `bulk/raw`, `aggregates` → `bulk/aggregates`) of another archive from its bytes: the bytes must pass `_foreign_problem()` (JSON object, date equals the name, `origin` `gdpr_export`, `source_files` SHA-256 list, offsets / samples valid) or the file is refused (`failed`, reason in the log); a schema version newer than the program knows is `kept`; otherwise the stored file decides with the rules of the module (`_compare`): missing or damaged → written, unreadable → `failed`, same set `unchanged`, fuller or newer written, smaller or older `kept`. The bytes are written unchanged, atomically. → `written` / `unchanged` / `kept` / `failed`; never raises |
| `describe_container_path(rel_path)` (v1.7.6.2) | What a path inside a mirror container is, from its name alone: `("intraday", date)`, `("aggregates", date)`, `("original", hash, suffix)` or `None` (another folder or name, a date that is no date, wrong depth, the folder of an original not its first two characters) |
| `list_originals()` (v1.7.6.2) | The names `<hash><suffix>` of the originals in `bulk/source`, from the file names only; a `.tmp` or oddly named file is not listed; `set()` if there is no folder |

`write_day`, `write_aggregates` and `import_day_file` write through one private `_write_atomic(dst, payload)` (`.tmp` → `fsync` → `os.replace`, up to 5 tries on a lock; v1.7.6.2, F-11 fixed the header text about `source_files`). The day loader behind `day_status`/`write_day` is the private `_load_day()` (the former public `read_day()` was removed in v1.7.6.1 — only tests used it).

---

## `garmin_import_mirror.py`

Import path for `.gla` mirror containers (encrypted, produced by
`garmin_mirror.py`) and — deprecated, folder-fallback only — a plain
mirror folder. Container path is primary; folder fallback is scheduled
for removal.

| Function | Purpose |
|---|---|
| `run_import_mirror(mirror_path, base_dir, password, dry_run, progress=None)` | Entry point. `progress` (v1.7.6.2) is a callable that gets a line for every section decrypted and for every tenth of the raw days, bulk day files and originals; a callback that raises never fails the import; the folder fallback gives no lines. Detects source type; dry-run previews counts; live-run copies raw + context + source, one `quality_log.json` save per processed day (v1.6.5.7 GP-2 fix — previously saved once at the end of the whole import); aborts the whole import without writing anything if any container path resolves outside `base_dir` (fail-closed, v1.7.4.3) |
| `detect_source(mirror_path)` | Returns `"container"`, `"folder"`, or `"unknown"` |
| `_run_import_container(...)` / `_run_import_folder(...)` | Per-source-type orchestration, both under `QUALITY_LOCK` |
| `_import_raw_from_bytes(...)` / `_import_raw_folder(...)` | Per-day raw import — `_upsert_quality()` per day, `_save_quality_log(skip_backup=True)` per day (v1.6.5.7), one final save (with backup) after the loop. A day that `writer.write_day()` did not write (`False`: a write error, or an aggregates file of the day that cannot be read) is an error of the day, not a copied one: `errors += 1`, no quality-log entry, `ok` false (v1.7.6.1, F-6). `write_day()` gives a day with export data on this side the resolved summary, so the container's summary (fast path) is replaced for such a day; a day without export data keeps the container's summary as before |
| `_split_export_only(raw_order, raw_files_in_container)` (v1.7.6.2, F-8) | A day of the raw delta whose quality-log entry says `write` false and whose raw file is not in the container is an export-only day, no raw error; `write` true (or missing) without raw bytes stays an error; `write` false with a raw file is imported as a raw day |
| `_analyse_bulk_delta(bulk_files, bulk_source_files)` (v1.7.6.2) | Sorts the container's bulk files with `garmin_bulk_writer.describe_container_path()`: every day file is ordered (the writer decides), an original only when its name is missing here; unknown names are skipped with a warning, never an error |
| `_import_bulk_from_bytes(...)` (v1.7.6.2) | Originals through `store_original` (checks the hash), day files through `import_day_file`; run before the raw days so that `write_day()` resolves the summary with the daily values; each file is taken out of the fulfilled dict after use |
| `_import_export_days(...)` (v1.7.6.2) | `writer.rebuild_summary()` for every aggregates day written that was not imported as a raw day (`False` = error), then the quality-log entry of each export-only day that has daily values here (`written=False`, label / fields / source of the other archive; an unknown label is an error); then `catch_up_bulk_intraday` / `catch_up_bulk_aggregates` set the marks |

**Return contract — `run_import_mirror()`:**
```python
{
    "raw_copied":       int,
    "raw_skipped":      int,
    "context_copied":   int,
    "source_copied":    int,
    "bulk_copied":      int,   # v1.7.6.2 — bulk day files written (container only)
    "bulk_skipped":     int,   #            already there / fuller here
    "originals_copied": int,   #            originals taken over
    "export_days":      int,   #            export-only days that got their entry
    "errors":           int,
    "ok":               bool,
    "error":            str,   # v1.6.5.7 — present only on early hard-stop
                               # failures (unrecognised source, unlock_meta
                               # failure, unreadable mirror_meta.json/
                               # quality_log). Absent when "ok" is False due
                               # to per-item errors during processing —
                               # those are individually logged, "errors" is
                               # their count.
}
```
The dry run returns `raw_to_copy`, `context_to_copy`, `source_to_copy`, `bulk_to_copy` (day files missing here by name), `originals_to_copy`, `version_warning`, `ok` (and `error`). The backup of the imported bulk files is not made by the import: the next sync start (step 3g) backs them up.

---

## `garmin_backup.py`

Sole Owner of `garmin_data/backup/`. Does not import `garmin_writer` or `garmin_quality`. Since v1.7.6.2.1 the raw-file part (backup, consolidation, backfill, refresh) is a thin shell over `garmin_backup_common` (one `BackupKind` built at each call: `area` `raw`, prefix `garmin_raw_`, ZIP prefix `raw_backup_`, validity = JSON object with the matching `date`, `log` = this module's logger); the quality-log snapshots, `check_raw_integrity()` and `restore_raw_days()` stay here with their own code. Public names, return values (`backfill_raw` answers `errors`) and the module names `_consolidate_raw_months()` and `_zip_contains()` are unchanged.

| Function | Purpose |
|---|---|
| `backup_raw(date_str, force=False)` | Copies `garmin_raw_YYYY-MM-DD.json` into `backup/raw/YYYY-MM/`. Triggers `_consolidate_raw_months()`. Returns `bool`. Since v1.7.5.6 every call consolidates against today's real month, so a completed month is packed right away, and a file whose content differs from its ZIP entry replaces that entry — a rewritten day (backfill, mirror import, silo repair) no longer keeps its old version in the ZIP. `force=True` (v1.7.1.7) additionally replaces an entry with identical content. History: until v1.7.4.0.4 the replace branch was dead code (the call consolidated against the written day's own month, which the consolidation step then skips as "current"); until v1.7.5.6 only `force=True` consolidated against today's month. `backup_source()`/`garmin_backup_source.py` has the identical fix, kept deliberately separate (backup integrity) |
| `backup_quality_log()` | Creates monthly snapshot of `quality_log.json` as `quality_log_YYYY-MM.zip`. Triggers yearly consolidation. Refuses to overwrite a snapshot with a log whose day count is less than half the existing snapshot's (v1.7.4.0.4 data-loss guard) |
| `restore_quality_log()` | Restores from latest valid monthly ZIP. Returns loaded `dict` or `None` |
| `check_raw_integrity()` | Compares `write=True` quality log entries vs. existing raw files. Returns `{"missing_days", "no_backup", "total_checked", "error"}` — `error` is `None` on success, set if `quality_log.json` itself could not be read (v1.6.5.7, Netz 3 Kandidat 2). Called via `garmin_app_controller.check_integrity()` which sets `GARMIN_OUTPUT_DIR` first |
| `restore_raw_days(date_strs)` | Restores raw files from backup (dir first, then ZIP). Returns `{"restored", "skipped_already_current", "failed", "errors"}` — `errors` is `dict[str, str]`, one reason per date in `failed` (v1.6.5.7, Netz 3 Kandidat 2). Own downgrade guard (v1.6.5.8, Fix 2): a date is skipped into `skipped_already_current` if a raw file already exists for it and its `quality_log` entry is already `"high"` — reads `quality_log.json` directly, same pattern as `check_raw_integrity()`, no `garmin_quality` import (this module deliberately has none) |
| `_consolidate_raw_months(current_month, force_filenames=None)` | ZIPs completed month dirs, deletes dir after ZIP verified. `force_filenames` (v1.7.1.7) — set of filenames replaced even when the content is identical; since v1.7.5.6 a file in the month folder replaces its same-named ZIP entry whenever the bytes differ. Scope is per-filename, never per-month, so an unrelated batch of already-good consolidated days in the same month is never touched. `zipfile` has no in-place replace — a replace rebuilds the ZIP without the old entry, adds the new version, verifies integrity, then atomically swaps it in. `None` (default) — only files whose bytes differ from the ZIP entry are replaced (v1.7.5.6; before that nothing was replaced) |
| `_consolidate_log_years(current_year)` | Creates `quality_log_YYYY.zip` for completed years without yearly ZIP |
| `_zip_contains(zip_path, filename)` | Returns `True` if filename exists in ZIP. Silent on error |
| `check_raw_backfill_needed()` | Returns count of raw files without backup. Fast, no copy. Returns 0 if complete |
| `backfill_raw()` | Copies all unbackedup raw files into `backup/raw/`. Consolidates completed months. Idempotent. Returns `{"copied", "skipped", "errors"}` |
| `check_raw_stale_backups()` | Returns count of raw files whose backup copy differs from them (v1.7.5.6). Compares bytes with the copy in the month folder, otherwise CRC32 and size with the monthly ZIP entry — nothing is unpacked. A file without any backup is not counted (that is `backfill_raw()`'s job), nor is a file that is not a valid day file. Fast check, no copy |
| `refresh_raw_backups()` | Brings those copies up to date (v1.7.5.6): copies the changed files into their month folders, then consolidates once, which replaces the ZIP entries. Content-based and idempotent, never modifies `raw/`. A raw file that is not a JSON object, or whose `date` does not match its file name, is reported and not copied over its backup; a file that cannot be read counts in `errors` (v1.7.6.2.1). Returns `{"refreshed", "unreadable", "errors"}` |

**Backup directory structure:**
```
garmin_data/backup/
  log/         — quality_log_YYYY-MM.zip, quality_log_YYYY.zip
  raw/         — YYYY-MM/ (open month), raw_backup_YYYY-MM.zip (completed)
  autorestore/ — auto-restore-YYYY-MM-DD.zip (defective log before restore)
  source/      — see `garmin_backup_source.py`
  bulk/        — see `garmin_backup_bulk.py` (v1.7.6.2)
```

---

## `garmin_backup_common.py`

Leaf node (v1.7.6.2): the monthly folder / ZIP flow of the raw backup, once, parameterised by a `BackupKind` (area, source and backup folder, file prefix, ZIP prefix, validity check, log prefix). Standard library only; no path of `garmin_config` inside. Built for the bulk day files; since v1.7.6.2.1 `garmin_backup.py` (raw) and `garmin_backup_source.py` (source) are thin shells over it as well. `test_backup_common.py` pins the module on folders it is handed (Part A), that the two shells behave like it (Part B) and the hardening of v1.7.6.2.1 (Part C).

| Function | Purpose |
|---|---|
| `BackupKind` | Frozen dataclass; `suffix`, `date_of(path)` derive from the prefix. `log` (v1.7.6.2.1, optional): the logger the kind's messages go to — a module that wraps this one hands in its own; `None` = this module's logger, looked up at call time |
| `backup_file(kind, date_str, force=False, consolidate=None)` | Copies one day file into its month folder and consolidates completed months. `bool` |
| `consolidate_months(kind, current_month, force_filenames=None)` | ZIPs completed month folders, verifies, removes the folder; a file in the month folder replaces its ZIP entry when the bytes differ (rebuild without the old entry, verify, atomic swap). Since v1.7.6.2.1 an existing ZIP is opened and checked entry by entry (`testzip`) before anything is appended or replaced: one that fails is not touched, the month folder stays and one error line names the ZIP and the reason; a new ZIP that could not be finished is removed again |
| `check_backfill_needed(kind)` / `backfill(kind)` | Count / copy the files without any backup copy; `backfill` consolidates once |
| `find_outdated(kind)` / `check_stale(kind)` / `refresh(kind)` | Files whose copy differs (bytes against the month folder, otherwise CRC32 and size against the ZIP entry, nothing unpacked); `refresh` copies them and consolidates once. A file that cannot be read is in neither list; `refresh` counts it as an error (internal `_scan`, v1.7.6.2.1), `find_outdated` keeps its two-list form |
| `zip_index(zip_path, logger=None)`, `zip_contains(zip_path, name)` | `{name: (crc, size)}` of a ZIP (`{}` and a warning with the name and the exception type if it cannot be read) / presence of one entry; `zip_contains` swallows errors on purpose (a damaged ZIP counts as "file missing" in the backfill check; the consolidation reports the ZIP) |
| `read_copy(kind, name)` | The backup copy of one file: the month folder first, otherwise the ZIP entry; `None` if there is none or it cannot be read |
| `is_dated_object(data, date_str)`, `is_json_object(data, date_str)` | Ready-made validity checks for `BackupKind.is_valid` |

**Messages (v1.7.6.2.1):** every error or warning line of the module carries the exception type (`PermissionError: ...`), an unexpected error adds the traceback as a debug line (`exc_info`), and every line about a ZIP names it ("... failed for 2024-08 (raw_backup_2024-08.zip): OSError: ..."). A damaged ZIP is not repaired by the module: delete it and let a backfill make the copies again while the daily files exist — the source backup does that at the end of a sync, the raw backup through `backfill_raw()` (offered once by a dialog, no button).

---

## `garmin_backup_bulk.py`

Sole Owner of `garmin_data/backup/bulk/` (v1.7.6.2). Reads the bulk store, never writes it. Imports `garmin_backup_common` and `garmin_config` (lazily). Everything is non-fatal: an error ends in the returned numbers (and `ok` false) and the log; nothing raises.

| Folder | What | Scheme |
|---|---|---|
| `backup/bulk/raw/` | `bulk/raw/garmin_bulk_<date>.json` | month folder → `bulk_raw_backup_YYYY-MM.zip` (shared flow); a changed day replaces its copy |
| `backup/bulk/aggregates/` | `bulk/aggregates/garmin_bulk_agg_<date>.json` | the same, `bulk_aggregates_backup_YYYY-MM.zip` |
| `backup/bulk/source/` | `bulk/source/<xx>/<sha256>.fit` or `.json` | no dates, never changing: one `<xx>.zip` per first two hash characters, entries only added; a ZIP is never appended to — a new one is written (`.tmp`, old entries copied, new ones added, verified) and swapped in with `os.replace`; a ZIP that cannot be read or fails its check is not touched and reported |

| Function | Purpose |
|---|---|
| `backup_all(should_stop=None)` | Brings the bulk backup up to date: copies what has no backup, refreshes what changed, adds missing originals. Looks first and asks `should_stop` only when there is work. Returns `{"raw", "aggregates", "source", "ok", "stopped"}`; a first backup of many originals logs a line every 10 % of the folders |
| `backup_originals(should_stop=None)` | The originals only; `{"copied", "present", "failed", "damaged_zips", "stopped"}` |
| `read_day_copy(which, date_str)` | `"raw"` or `"aggregates"`; the backup copy as bytes, `None` if there is none |
| `read_original_copy(file_hash, suffix=".fit")` | The backup copy of one original; `None` if there is none |
| `day_kinds()` | The two `BackupKind`s, built from the paths of `garmin_config` now |

Callers: `garmin_collector._run_bulk_backup(where)` — at the sync start (step 3g, before the login) and after a bulk import; `garmin_silo_repair` (#8/#9) through `read_day_copy` / `read_original_copy`. The backup is not triggered per write (a day file is written thousands of times in one import): it runs after the import and at the next start.

---

## `garmin_container.py`

Sole Owner of `mirror.gla`. No other module reads or writes the container file directly.
All paths from caller — no `garmin_config` import.

| Function | Purpose |
|---|---|
| `lock(source_dir, container_path, password, progress=None)` | Creates/overwrites `mirror.gla` atomically. Packs the sections quality_log (quality_log.json + device_table.json), raw, summary, context, source and, since v1.7.6.2, bulk and bulk_source. `progress` (v1.7.6.2) gets a line for the reading ("N files to read", then every 10 % with the real percentage), each section packed and the write; a callback that raises never fails the mirror. Returns `{"files_packed", "errors", "ok"}` |
| `unlock_meta(container_path, password)` | Verifies header HMAC, decrypts quality_log section, extracts quality_log.json by explicit key. Returns `{"ok", "container_meta", "quality_log", "error"}` |
| `fulfill_order(container_path, password, order, progress=None)` | Verifies HMAC, decrypts only ordered sections. Returns `{rel_path: bytes}`. `progress` (v1.7.6.2) gets a line before and after each section it decrypts (a section takes up to a quarter of a minute) |
| `report_progress(progress, text)` | Public since v1.7.6.2 (the import uses it): passes one line to the callback; no callback is a no-op, a callback that raises is logged at debug level |
| `list_files(container_path, section)` | Returns file list from header — no decryption, no password. Returns `list[str]` |
| `is_container(path)` | Checks magic bytes `GLA1`. Fast, no password. Returns `bool` |

**Container format:**

```
magic_bytes      4 bytes   "GLA1"
format_version   1 byte    0x01   (unchanged by the bulk sections: a program that does not know them never asks for them)
salt             16 bytes  PBKDF2 salt (random per lock())
header_hmac      32 bytes  HMAC-SHA256 over header_json with the master key
header_len       4 bytes   big-endian uint32
header_json      N bytes   UTF-8 JSON: container_meta + section_index
[section data]             AES-256-GCM, one blob per section: nonce (12 bytes) + ciphertext
```

Key derivation: PBKDF2-HMAC-SHA256 (600 000 iterations) → master key; HKDF-Expand(master, `gla-{section}`) → section key. Sections: `quality_log`, `raw`, `summary`, `context`, `source`, `bulk`, `bulk_source`. `bulk` holds `garmin_data/bulk/raw/**` and `garmin_data/bulk/aggregates/**`, `bulk_source` holds `garmin_data/bulk/source/**` (v1.7.6.2); `_classify_file()` is a fixed mapping — a folder it does not name is silently not mirrored. A container made before v1.7.6.2 has neither section and stays readable (`list_files()` answers `[]`). A section is encrypted whole, so `fulfill_order()` decrypts a whole section per request. Measured on a copy of a real archive (2026-10-23): `lock()` 50 s → 116 s with the bulk store, container 58 → 233 MB, peak memory 3.85 → 4.11 GB (every byte is held as a JSON number while packing).

---

## `garmin_mirror.py`

Sole owner of the mirror operation; delegates the container to `garmin_container`. `run_mirror(source_dir, container_path, password, progress=None)` calls `lock()` (the callback is handed on only when there is one) and returns its result. `panel_archive._do_mirror` logs the progress lines indented in the GUI log.

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

As of v1.6.8 Session 4, all 19 are broker-reachable in some form. 7 are
interpreted into `summary/` fields (`body_weight`, `calories_resting`,
`hydration_ml`, `endurance_score`, `hill_score`, `fitness_age`,
`blood_pressure` — the last added v1.7.1.14, Issue #7), the remaining 12
are exposed as archived in `raw/` (no value extraction) via `get_raw()`/`list_raw_fields()` — see
"Raw-passthrough fields" below. `get_daily_weigh_ins`'s suspected
duplicate status against `get_body_composition` is now confirmed —
byte-identical on accounts without a smart scale (`sourceType:
"MANUAL"`, confirmed by a real-data report, v1.7.1.14 Issue #9) —
deliberately excluded from `garmin_live_fetch.py::_ENDPOINTS` for that
reason, but its `_RAW_PASSTHROUGH_FIELDS` registration is unaffected and
unchanged.

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
      "device_id": "3952922857",
      "device_name": "fenix 5x",
      "validator_result": "ok",
      "validator_issues": [],
      "validator_schema_version": "1.1",
      "fields": {
        "heart_rates": "high", "stress": "high", "sleep": "high",
        "hrv": "medium", "spo2": "high", "stats": "high", "steps": "high",
        "body_battery": "high", "respiration": "high", "activities": "failed",
        "training_status": "medium", "training_readiness": "failed",
        "race_predictions": "medium", "max_metrics": "failed"
      },
      "backfilled_fields": {
        "steps": "2026-09-26T11:35:23"
      },
      "field_backfill_attempts": {
        "max_metrics": 1
      },
      "bulk": {
        "intraday": "2026-10-17",
        "aggregates": "2026-10-20"
      }
    }
  ]
}
```

`bulk.intraday` (v1.7.6) is set only on days whose heart-rate series were written to the bulk store by an import; the value is the import date. `bulk.aggregates` (v1.7.6.1) is the same mark for the daily values of the export in `bulk/aggregates`. Both are independent of `source`. A day that exists only in the export has an entry made at the end of the import: `source` `bulk`, `write` false (there is no `raw/` file), label and fields from the day's values; a day with too little data has an entry `failed` (`source` `bulk`, `write` false) so that the Fill and Repair timers try the API.

### Summary JSON (`summary/garmin_YYYY-MM-DD.json`)

| Field | Description |
|---|---|
| `date` | ISO date string |
| `generated_by` | Always `"garmin_normalizer.py"` |
| `schema_version` | Number of the summary schema (`CURRENT_SCHEMA_VERSION`); 5 since v1.7.6.6 |
| `sleep` | Duration, stages, score, SpO2, HRV, sleep_score_feedback, sleep_score_qualifier |
| `heartrate` | Resting, max, min, average BPM |
| `stress` | Stress average/max, Body Battery max/min/end |
| `day` | Steps, calories (active/total/resting), intensity minutes, distance |
| `body_composition` | Body weight in grams, raw from `get_body_composition` (v1.6.8 capability-scan pilot, unit unverified against real scale data) |
| `hydration` | Fluid intake in ml, raw from `get_hydration_data` (v1.6.8 Session 4) |
| `training` | Readiness (`readiness_score`, `readiness_level`, `readiness_feedback`), training status as text (`training_status`) and as number (`training_status_code`), `training_load_7d`, `vo2max`, `endurance_score`, `hill_score`, `fitness_age` (v1.6.8 Session 4; filled from the shapes of the API day since v1.7.6.6, see below) |
| `alerts` | `hr_alert_count`, `breathing_disruption`, `acwr_status`, `body_battery_level`, `body_battery_level_end_of_day`, `stress_qualifier` (v1.7.6.6, schema 5) |
| `activities` | List of activity objects |

Resolved summary (v1.7.6.1): for a day with an aggregates file in the bulk store the file is not `summarize()` of the API data alone but of the day resolved from the API data and the export's values (see `garmin_writer.py`). The structure above is the same; only where a value comes from differs. Known differences between the two sources for the same value (measured on a real archive): floors climbed are the API's value rounded; the sleep duration differs by up to 46 s on about 5 % of the days (the stages are equal); minimum/maximum heart rate and the stress block of the day are defined differently by the export on about 350 days that have an API series. Where both exist the API value is used. Since v1.7.6.3 (F-11) a field the API lacks or holds as `null` is filled from the export, also inside a section the API delivered: for old days the minimum/maximum heart rate (from the export's `user_summary`), the stress average (`averageStressLevel`) and fields such as the active calories now reach `summary/`; a value the API has is never replaced. `activities` is not filled from the export: its list carries the duration in milliseconds and the distance in centimetres, `summarize()` reads seconds and metres, and the activity lists in summaries made by the earlier import show duration and distance in those wrong units.

Schema 5 (v1.7.6.6): `summarize()` reads the shapes of the API day for `training`: `training_readiness` and `max_metrics` are lists of objects and the training status sits under `mostRecentTrainingStatus.latestTrainingStatusData.<device id>`; the older dict forms and keys stay valid (the export's values hold the readiness as a dict). Where several entries compete (the readiness entries of a day, the device entries of the training status, the elements of `max_metrics`) the one with the latest `timestamp` wins, whatever the order of the list (`max_metrics`: the newest `generic.calendarDate`, the first on a tie); an entry with a readable time beats one without, and at equal time the smaller canonical JSON text wins. `training.training_status` is the text for the number in `trainingStatus` (0 `NO_STATUS`, 1 `DETRAINING`, 3 `OVERREACHING`, 4 `MAINTAINING`, 5 `RECOVERY`, 7 `PRODUCTIVE`); the table is the one observed in the API data of the archive, where the number and the first word of `trainingStatusFeedbackPhrase` agree (origin class A), not taken from a Garmin document. `training_status_code` is the number as delivered; a number outside the table has no text and keeps its code. `training_status_code` is a field of the summary only, the broker has no field for it. `training_load_7d`, `endurance_score` and `hill_score` stay empty unless the older dict form or the capability endpoints supply them. `alerts`: `hr_alert_count` (a whole number; on the measured archive the field exists only on days with an alert), `breathing_disruption` (`sleep.dailySleepDTO.breathingDisruptionSeverity`), `acwr_status` (`acuteTrainingLoadDTO.acwrStatus` of the same device entry as the training status), `body_battery_level` and `body_battery_level_end_of_day` (`bodyBatteryLevel` of `bodyBatteryDynamicFeedbackEvent` and `endOfDayBodyBatteryDynamicFeedbackEvent`) and `stress_qualifier`; `user_summary` first, `stats` second. Texts are passed on as delivered (`NONE` and `UNKNOWN` are values), a value of another type is `None`. The two body battery levels follow the body battery value at the time of the event, the first in the evening and the end-of-day event later, near bedtime; observed on one archive, not a Garmin definition. The Garmin export carries none of these fields, so a day without an API day has `alerts` with all fields `None`.

---

## `garmin_live_fetch.py`

Worker — sole write authority over `garmin_data/live/live.json` (v1.6.5). Depends on `garmin_api` (reuses `login()` / `api_call()` — no second auth path, no own 429 handling).
Single-file snapshot of the current calendar day ("heute Nacht bis jetzt") — no history, overwritten on every fetch. No archive write access, no `quality_log.json` contact, no validator/normalizer — data is written as-is.

| Function | Purpose |
|---|---|
| `fetch_live(client=None, progress=None, state_cb=None)` | Fetches sleep + HRV + all eight baseline intraday endpoints for today, plus `get_blood_pressure`/`get_body_composition` if capability-enabled (v1.7.1.14, Issue #9 — see `_ENDPOINTS` below; corrected from a previously inaccurate "six" here, which predates this session — the baseline was always 8). `client=None` logs in headless (or reuses an already-authenticated client, e.g. right after a Daily Sync run). `progress`: optional `callable(str) -> None` for GUI-visible fetch progress — deliberately not named `log`, which would shadow the module logger. `state_cb` (v1.6.5.1): optional `callable(key: str, state: str) -> None` for GUI connection-status indicators (token/login/api/data × ok/fail) — fires token+login right after the login step, then api+data via a lightweight probe (`client.get_user_profile()` / `client.get_stats(today)`, same pattern as `garmin_app_controller.check_connection()`) immediately after, independent of the endpoint loop's own per-endpoint tracking. Returns `{"ok": bool, "failed_endpoints": list[str]}`. `ok=False` only on login failure/unavailability — individual endpoint failures never abort the fetch |

**`_ENDPOINTS` (v1.7.1.14):** list of `(method, key, capability_gate)`
3-tuples, 10 entries — 8 baseline (`capability_gate=None`, always fetched
unconditionally, unchanged since before this session) plus
`get_blood_pressure`/`get_body_composition` (`capability_gate` set to the
matching Capability-Scan endpoint name — fetched only if the user has
enabled it via Settings → API Scan → Edit Config, same `enabled_by_user`
double-gate the broker's `_CAPABILITY_FIELDS` already applies).
`get_daily_weigh_ins` deliberately excluded — confirmed byte-identical
duplicate of `get_body_composition` on accounts without a smart scale.
`fetch_live()`'s success ratio in its log/progress output is computed
against `attempted_count` (only endpoints actually fetched, i.e. not
skipped by a gate), not the static list length — a disabled gated
endpoint must not lower the reported ratio for an otherwise fully
successful fetch.
| `_write_live(live_data)` | Writes the snapshot to `cfg.LIVE_FILE`. Plain write, no atomic tmp/fsync/replace sequence — `live.json` has no history to protect |

---

## `garmin_health_map.py`

Field resolver for the dashboard broker architecture. Called exclusively by `health_map.py` — never directly by specialists.

### `_FIELD_MAP` — descriptor types

Each field in `_FIELD_MAP` uses one of seven descriptor types:

| Type | Key | Resolution | Source |
|---|---|---|---|
| `daily` | `("section", "key")` | daily | `summary/garmin_YYYY-MM-DD.json` |
| `intraday` | `("section", "array_key", extract_dict)` | intraday | `raw/garmin_raw_YYYY-MM-DD.json` (for fields in `_SERIES_TRACKS` also `bulk/raw/garmin_bulk_YYYY-MM-DD.json`, v1.7.6) |
| `raw_pct` | `("section", "dto_key", "seconds_key", "total_key")` | daily | `raw/garmin_raw_YYYY-MM-DD.json`; for a day whose `raw/` has no usable object (no total above 0, or a raw file that cannot be read) the same object from `bulk/aggregates/garmin_bulk_agg_YYYY-MM-DD.json` (v1.7.6.1) — one source per day, never mixed |
| `bulk_daily` | `("section", "key")` | daily | `bulk/aggregates/garmin_bulk_agg_YYYY-MM-DD.json`, `aggregates.<section>.<key>` — fields only the Garmin export has (v1.7.6.1). `daily` and `intraday` of such a field are `None`; an intraday request gets the daily values with `fallback=True`. A day that cannot be used (no file, damaged, not an object, newer `schema_version` than `_BULK_AGG_MAX_SCHEMA`, no `aggregates` object) or a value that is not a number gives `None` for the day (a warning, once per day and process) |
| `live` | `("section", "array_key", extract_dict)` | live | `garmin_data/live/live.json` |
| `live_pct` | `("section", "dto_key", "seconds_key", "total_key")` | live | `garmin_data/live/live.json` |
| `live_nested` | `[("section", "dotted_key"), ...]` — each candidate may also be a 3-tuple `("section", "dotted_key", divisor)` | live | `garmin_data/live/live.json` |

`raw_pct` is used for fields that require percentage calculation from two seconds-based values in the raw file. `get()` detects `raw_pct` and bypasses the standard daily/intraday resolution fallback logic. A `raw_pct` field whose day has no usable object in `raw/` (a day that exists only in the export) reads the same object from `bulk/aggregates` (v1.7.6.1); `get_raw()` does not: it still reads `raw/` only, so it answers nothing for an export-only day.

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
| `stress_rest_duration` | bulk_daily | `stress.restDuration` from `bulk/aggregates` | seconds per day, only in the Garmin export (v1.7.6.1) |
| `stress_low_duration` | bulk_daily | `stress.lowDuration` from `bulk/aggregates` | seconds per day (v1.7.6.1) |
| `stress_medium_duration` | bulk_daily | `stress.mediumDuration` from `bulk/aggregates` | seconds per day (v1.7.6.1) |
| `stress_high_duration` | bulk_daily | `stress.highDuration` from `bulk/aggregates` | seconds per day (v1.7.6.1); the export's `stressDuration` is low + medium + high and is not registered |
| `vo2max` | daily | `training.vo2max` | — |
| `sleep_score_feedback` | daily | `sleep.sleep_score_feedback` | z.B. `POSITIVE_DEEP` |
| `sleep_score_qualifier` | daily | `sleep.sleep_score_qualifier` | z.B. `FAIR`, `EXCELLENT` |
| `sleep_deep_pct` | raw_pct | `sleep.dailySleepDTO`: `deepSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_light_pct` | raw_pct | `sleep.dailySleepDTO`: `lightSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_rem_pct` | raw_pct | `sleep.dailySleepDTO`: `remSleepSeconds / sleepTimeSeconds * 100` | % |
| `sleep_awake_pct` | raw_pct | `sleep.dailySleepDTO`: `awakeSleepSeconds / sleepTimeSeconds * 100` | % |
| `heart_rate_series` | intraday | `heart_rates.heartRateValues` | `[{"ts", "value"}]`; second track from the bulk store (`sections.intraday.heart_rate.values`) when the API has none, see `REFERENCE_BROKER.md` (v1.7.6) |
| `stress_series` | intraday | `stress.stressValuesArray` | offset applied |
| `spo2_series` | intraday | `spo2.spO2HourlyAverages` | List of `[epoch_ms, value]` pairs — corrected in v1.6.3.1 (previously misread as dict-shaped, series was silently empty for every consumer) |
| `body_battery_series` | intraday | `stress.bodyBatteryValuesArray` | — |
| `respiration_series` | intraday | `respiration.respirationValuesArray` | List of `[epoch_ms, value]` pairs — same v1.6.3.1 fix as spo2_series. Raw data also contains a newer, parallel `wellnessEpochRespirationDataDTOList` (dict-shaped) — absent in all 4 raw files sampled during v1.6.5.6 (2024-03-07, 2025-03-10, 2025-03-30, 2026-07-01/27); not conclusive, still not evaluated as a data source, see `NOTES_v1656.md` |
| `steps_series` | intraday | `steps` (bare list at top level, not nested under a sub-key) | 15-min bins, `{"startGMT", "steps"}`. `_read_intraday()` handles this via its existing `isinstance(section_data, list)` branch — no code change needed for this shape |
| `body_weight` | daily | `body_composition.weight_g` | grams, raw/unconverted — Garmin's gram convention assumed but not verified against real data (no scale connected during pilot). First API-Capability-Scan candidate wired into the broker (v1.6.8) |
| `calories_resting` | daily | `day.calories_resting` | kcal — resting/basal calories from `get_calories_daily`. Second API-Capability-Scan candidate wired into the broker (v1.6.8). `active`/`total` from this same candidate's response were left unadopted at the time (redundant-seeming against `user_summary`'s own fields) — later confirmed as a distinct, unregistered pair and adopted as `calories_active`/`calories_total` (v1.7.1.16) |
| `hydration_ml` | daily | `hydration.value_ml` | ml, from `get_hydration_data` — only `valueInML` adopted, `goalInML` (a user-set target, not a measurement) intentionally excluded (v1.6.8 Session 4) |
| `endurance_score` | daily | `training.endurance_score` | index, from `get_endurance_score` — checked against `vo2max` for redundancy (Multi-LLM hint), none found — distinct, device-calculated index (v1.6.8 Session 4) |
| `hill_score` | daily | `training.hill_score` | index, from `get_hill_score` — not to be confused with that same endpoint's own internal `enduranceScore` sub-field, unrelated to the `endurance_score` field above (v1.6.8 Session 4) |
| `fitness_age` | daily | `training.fitness_age` | years, from `get_fitnessage_data` — only `fitnessAge` adopted; `chronologicalAge`/`achievableFitnessAge`/`previousFitnessAge`/`components` intentionally excluded (v1.6.8 Session 4) |
| `bp_high_systolic` | daily | `blood_pressure.high_systolic` | mmHg, from `get_blood_pressure` — day's highest systolic reading, 1:1 from Garmin's own daily aggregate (v1.7.1.14, Issue #7) |
| `bp_high_diastolic` | daily | `blood_pressure.high_diastolic` | mmHg, same source/rollup as above |
| `bp_low_systolic` | daily | `blood_pressure.low_systolic` | mmHg, same source/rollup as above |
| `bp_low_diastolic` | daily | `blood_pressure.low_diastolic` | mmHg, same source/rollup as above |
| `bp_num_measurements` | daily | `blood_pressure.num_measurements` | count, measurements logged that day |
| `bp_category` | daily | `blood_pressure.category` | text, e.g. `STAGE_2_HIGH` — reflects the day's worst individual reading, not an average |
| `hrv_weekly_avg` | daily | `sleep.hrv_weekly_avg_ms` | ms — sibling of `hrv_last_night`, previously computed but unregistered (v1.7.1.16) |
| `hrv_status` | daily | `sleep.hrv_status` | text, e.g. `BALANCED` (v1.7.1.16) |
| `hrv_feedback` | daily | `sleep.hrv_feedback` | text (v1.7.1.16) |
| `stress_max` | daily | `stress.stress_max` | 0–100, sibling of `stress_avg` (v1.7.1.16) |
| `body_battery_min` | daily | `stress.body_battery_min` | 0–100, sibling of `body_battery_max` (v1.7.1.16) |
| `body_battery_end` | daily | `stress.body_battery_end` | 0–100 (v1.7.1.16) |
| `heart_rate_max` | daily | `heartrate.max_bpm` | bpm, sibling of `resting_heart_rate` (v1.7.1.16) |
| `heart_rate_min` | daily | `heartrate.min_bpm` | bpm (v1.7.1.16) |
| `heart_rate_avg` | daily | `heartrate.avg_bpm` | bpm (v1.7.1.16) |
| `steps_total` | daily | `day.steps` | steps, daily total — distinct from `steps_series` (intraday 15-min bins). Registered as `steps_total`, not `steps` — `steps` is already a `HEALTH_FIELD_ALIASES` entry pointing to `steps_series`, caught live after initial deploy (v1.7.1.16, see `NOTES_v1_7_1_16.md`) |
| `steps_goal` | daily | `day.steps_goal` | steps (v1.7.1.16) |
| `floors_climbed` | daily | `day.floors_climbed` (`user_summary.floorsAscended`) | floors — distinct from the still-unverified raw-passthrough candidate `floors`/`get_floors` (v1.7.1.16) |
| `intensity_min_moderate` | daily | `day.intensity_min_moderate` | minutes (v1.7.1.16) |
| `intensity_min_vigorous` | daily | `day.intensity_min_vigorous` | minutes (v1.7.1.16) |
| `distance` | daily | `day.distance_km` | km (v1.7.1.16) |
| `calories_active` | daily | `day.calories_active` | kcal, from `get_calories_daily` — same candidate as `calories_resting`, previously left unadopted (v1.7.1.16) |
| `calories_total` | daily | `day.calories_total` | kcal, same source (v1.7.1.16) |
| `readiness_score` | daily | `training.readiness_score` | 0–100 (v1.7.1.16) |
| `readiness_level` | daily | `training.readiness_level` | text (v1.7.1.16) |
| `readiness_feedback` | daily | `training.readiness_feedback` | text (v1.7.1.16) |
| `training_status` | daily | `training.training_status` | text, e.g. `PRODUCTIVE` (v1.7.1.16) |
| `training_load_7d` | daily | `training.training_load_7d` | unit/scale not independently verified (v1.7.1.16) |
| `respiration_avg` | daily | `sleep.respiration_avg` | breaths/min — sibling of `spo2_avg`, previously only reachable via `respiration_series` (intraday, ~70 KB/day) (v1.7.1.16) |

All six `bp_*` fields gated in `_CAPABILITY_FIELDS` against
`get_blood_pressure` (v1.7.1.14, Issue #7). A seventh value,
`worstReading` (`{systolic, diastolic, pulse, timestamp}` — the
individual measurement that produced the day's `bp_category`;
tiebreak on same-category ties: chronologically latest measurement
wins, by `measurementTimestampLocal`), is deliberately NOT part of
`_FIELD_MAP` — it has no single scalar shape. It lives as a plain nested
object under `blood_pressure.worstReading` in the summary JSON, read
directly by any consumer that needs it — same treatment as
`sleep_score_feedback` (excluded from Explorer/Custom Dashboard's daily
field iteration via `_EXCLUDE_FROM_DAILY`). See `CHANGELOG.md` v1.7.1.14
for the Composite-field-type evaluation (Option A vs. B) that led to
this choice, and `REFERENCE_BROKER.md`'s field index for the broker-side
table.

**Live route (v1.6.5):** 16 of the fields above also support `resolution="live"` (reads `garmin_data/live/live.json`, written by `garmin_live_fetch.py`, instead of the archive): `heart_rate_series`, `stress_series`, `spo2_series`, `body_battery_series`, `respiration_series`, `steps_series` (via `live`); `sleep_deep_pct`, `sleep_light_pct`, `sleep_rem_pct`, `sleep_awake_pct` (via `live_pct`); `hrv_last_night`, `sleep_score`, `sleep_score_feedback`, `sleep_score_qualifier`, `sleep_duration` (via `live_nested`). Fields with no live route (`resting_heart_rate`, `spo2_avg`, `body_battery_max`, `stress_avg`, `vo2max`) return `fallback=True`, empty `values`, for `resolution="live"`. Consumer: `dashboards/live_tracking_html_dash.py`.

*(v1.7.1.6)* `sleep_score` (the numeric score itself, distinct from its `_feedback`/`_qualifier` companions) previously had a `live_nested` route (`sleep.dailySleepDTO.sleepScores.overall.value`) and a `daily` route (`sleep.score`) but was missing its own row in both the Registered-fields table above and the live-route count/list — a pre-existing gap, not introduced in v1.6.5. Both closed this session (see `REFERENCE_BROKER.md`'s "Field index" for the added `0–100` unit row; the live-route count above corrected from 15 to 16 and `sleep_score` added to the `live_nested` list).

### Raw-passthrough fields (v1.6.8 Session 4)

12 of the 19 original API-Capability-Scan candidates have no known
daily-value extraction — list-of-entries structure, empty/unknown schema
at the pilot account, or event-log structure (see `NOTES_v168_D_02.md`
"Blocker-Typen" for the per-field reasoning; `blood_pressure` moved out
of this group in v1.7.1.14, Issue #7 — see below). Rather than leave
them archived-but-broker-invisible, `garmin_health_map.py` exposes them
as archived in `raw/` (no value extraction) via a second, deliberately separate access path — kept
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
template pending (v1.6.8 doc-closure). Any of the 12 fields with a
concrete aggregation/display proposal backed by real filled data can move
to a proper `summarize()` field later, same as the seven already wired —
`blood_pressure` did exactly that in v1.7.1.14 (Issue #7), once a real
multi-reading-day payload from a GitHub issue report gave the extraction
shape needed.

| Field | Source endpoint |
|---|---|
| `daily_weigh_ins` | `get_daily_weigh_ins` |
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
| `_device_offset(data)` | Returns `(offset_hours, dst_transition)` for one raw/live file's `data` dict. Tries `_OFFSET_SOURCE_SECTIONS` in order (`heart_rates → stress → respiration → spo2`), first section with a complete `startTimestampGMT/Local` + `endTimestampGMT/Local` pair wins. `dst_transition=True` when start-of-day and end-of-day offset differ (day crosses a DST change) — the offset used is always the start-of-day value, matching how Garmin Connect itself renders the day (it does not correct mid-day either). No usable section → `(0.0, False)` with a `log.warning` — never a silent UTC fallback, never an exception. The warning fires at most once per calendar day per process run (`_warned_offset_days`, Baustein 27) — not once per field that reads that day |
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
| `_prompt_enc_key(mode)` | Modal encryption key input — `"setup"` or `"recovery"` |
| `_prompt_token_expired()` | Warning popup for 429 risk on SSO fallback |
| `_test_conn()` | Inner function in `_timer_loop()` — uses `garmin_api.login()` with full ENV setup and reload. No raw SSO. |
| `_toggle_log_level()` | Switches GUI log display between INFO and DEBUG |
| `_toggle_timer()` | Starts or stops background timer |
| `_timer_loop(generation)` | Main timer loop, in `panel_timer.py` — six modes, candidate logic delegated to `garmin_app_controller.py` (see its own section below) |
| `_copy_last_error_log()` | Copies most recent fail log to clipboard |

---

## Force-Refetch GUI (v1.7.1.7, Baustein 5)

`app/dialog_force_refetch.py` (new file — deliberately not `app/dialogs.py`,
too large/multi-part a feature for the shared-dialog file) plus additions
to `panel_outputs.py` and `panel_archive.py`. No project-module imports in
`dialog_force_refetch.py` itself (same rule as `dialogs.py`) —
`quality_by_date`/`results` are always handed in by the caller, never read
by the dialog file itself.

| Symbol | Purpose |
|---|---|
| `panel_outputs.py::_on_force_refetch()` | Force-Refetch GUI orchestrator. Precondition check (`_is_running()`/timer/context-sync — same pattern as `_on_mirror()`/`_on_silo_check()`) before opening the calendar dialog, avoiding a collision on the module-global `garmin_collector._stop_event`. Timer paused for the whole interaction (calendar selection through commit/cancel), not just during the fetch. Opens `ForceRefetchDialog` → background worker thread (own `garmin_api.login()`, same pattern as `garmin_live_fetch.fetch_live()` — NOT `self._app._run()`/`main()`, since `run_force_refetch_preview()` needs an actual `client` object) → `ForceRefetchProgressDialog` (live) → `ForceRefetchReviewDialog` (confirm/reject) → `commit_force_refetch()` under `quality.QUALITY_LOCK` held by the caller for load+call+save (different contract than `_run_source_backfill()`, which holds the lock internally) |
| `panel_archive.py::_get_quality_by_date()` | Read-only `{date: label}` lookup from `quality_log.json` — same documented direct-read exception as `_check_failed_days_popup()` (see Documented Exceptions above). Own function rather than an extension of `_check_failed_days_popup()` — different return shape (full date→label map vs. a filtered count), not a variant of the same query |
| `dialog_force_refetch.py::DateToggleCalendar` | Reusable `QCalendarWidget` — click toggles a date in/out of an internal `set[str]`. Two independent color layers: an optional quality-status background (green/yellow/red, from a caller-supplied `{date: label}` dict, purely informational, set once at construction) and a selection highlight (bold + underline in the theme accent color — deliberately not red, which is reserved for `"failed"`). Known, accepted Qt limitation: `setDateTextFormat()` reliably shows only the most-recently-clicked cell's format; earlier selections can visually revert on a later click (selection state itself — `_selected`/`get_selected_dates()` — remains correct throughout). Not worked around — the `QListWidget` selection list is the reliable display |
| `dialog_force_refetch.py::SelectionOnlyCalendar` | Read-only calendar for the progress dialog — highlights a fixed, pre-given set of dates, no click interaction, no quality background. Separate class rather than a `read_only` flag on `DateToggleCalendar` — one class, one job |
| `dialog_force_refetch.py::ForceRefetchDialog` | Calendar-selection dialog. Hosts `DateToggleCalendar` + a mirrored `QListWidget` (clicking a list entry also deselects — second way to deselect, matching the calendar's own toggle) + Start button. `get_selected_dates()` returns the confirmed selection |
| `dialog_force_refetch.py::ForceRefetchProgressDialog` | Read-only `SelectionOnlyCalendar` + live `QPlainTextEdit` log + Stop button (`stop_requested` signal). `append_log()` — Main Thread only, caller dispatches from the worker thread. Pure UI + a thread-safe log sink — does not call `run_force_refetch_preview()` itself |
| `dialog_force_refetch.py::ForceRefetchReviewDialog` | One row per `run_force_refetch_preview()` result entry — quality-before → quality-after, changed-field count with field names shown (from `entry["fields_changed"]`), checkbox per day starting UNCHECKED (deliberate opt-in, not pre-confirmed), Confirm-all/Reject-all buttons. Error entries shown for information only, no checkbox — `commit_force_refetch()` already treats any non-confirmed date as rejected. `get_confirmed_dates()` returns the checked set |
