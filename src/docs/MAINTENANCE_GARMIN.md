# Garmin Local Archive — Garmin Pipeline Maintenance Guide

Maintenance, debugging, and extension guide for the Garmin data pipeline (`garmin/`).
For build and release process see `MAINTENANCE_GLOBAL.md`.
For complete function reference see `REFERENCE_GARMIN.md`.

---

## Pipeline architecture

```
garmin_app.py (GUI)
  └── _build_env() / _apply_env()
        └── garmin_collector.main()
              ├── garmin_quality._load_quality_log()
              ├── garmin_quality._backfill_quality_log()   (first run only)
              ├── garmin_quality.get_low_quality_dates()
              ├── bulk recheck flagging                   (source:bulk + ≤180d → recheck:true, quality irrelevant)
              ├── garmin_api.login()
              ├── garmin_api.get_devices()
              ├── garmin_collector._device_id_backfill()  (einmalig — Einträge ohne device_id aus raw-Files befüllen)
              ├── garmin_quality.save_device_table()       (nach Backfill — device_table.json schreiben)
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
              │       └── garmin_quality.assess_quality()
              │     downgrade check                        → skip write if new < existing
              │     garmin_collector._write_assessed()     → skipped on downgrade
              │     garmin_quality.record_attempt()        (upsert + save, atomic)
              │     garmin_quality._save_quality_log()     (per-day crash-resilience, skip_backup=True)
              └── garmin_quality._save_quality_log()       (final safety-net save after loop)
```

**API-Capability-Scan (v1.6.8) — separate delegated entry, not part of the diagram above:**
`main()` step 0b, triggered by `GARMIN_CAPABILITY_SCAN=1`, bypasses the entire
regular sync flow with its own login and its own exit. See `REFERENCE_GARMIN.md`
→ `garmin_api_capability.py` / `run_capability_scan()` for the full contract.
Persistence (`garmin_api_capability_config.json`) is read once per *regular*
sync run too — inside the fetch loop's `QUALITY_LOCK`, before the per-day
loop — so the diagram above is accurate for the regular sync path, this note
only covers the scan's own separate entry.
```

### garmin/quality/ — known design decisions

`_safe_get()` is defined separately in both `_io.py` and `_assess.py` — intentional
duplication to avoid a cross-import between the two base modules. Both are leaf nodes
within the quality package; neither should import the other. If this redundancy becomes
a maintenance concern, `garmin_utils.py` is the correct consolidation point (v1.5.5.3
or later).

**Known scope boundary — no cross-field plausibility check:** the quality system
checks presence (structural intraday data, `garmin_source_quality.py`) and range
(value against fixed schema bounds, `garmin_validator.py` `out_of_range`). It does
not check internal consistency between two values from the same response (e.g.
finalized resting HR vs. intraday HR minimum). This check class is not relevant for
the current collection path: GLA is API-first, with bulk import as a documented
fallback — both paths receive already-finalized values via `garminconnect`. The
specific failure mode this check class would catch (provisional on-device value
vs. finalized value) only arises with direct on-device FIT reading, which is out
of scope.

| Module | Sole write authority |
|---|---|
| `garmin_writer.py` | `raw/` and `summary/` (since v1.7.6.1 `summary/` is resolved from the API data and the day's aggregates) |
| `garmin_quality.py` (facade → `quality/`) | `quality_log.json` and `device_table.json` |
| `garmin_security.py` | `garmin_token.enc` |
| `garmin_backup.py` | `garmin_data/backup/raw/` + `backup/log/` (v1.6.0.4: split with garmin_backup_source); the raw-file part is a thin shell over `garmin_backup_common` since v1.7.6.2.1 |
| `garmin_backup_source.py` | `garmin_data/backup/source/` (v1.6.0.4) — a thin shell over `garmin_backup_common` since v1.7.6.2.1 |
| `garmin_backup_bulk.py` | `garmin_data/backup/bulk/` (v1.7.6.2) — reads the bulk store, never writes it; nothing raises |
| `garmin_backup_common.py` | none — leaf node (v1.7.6.2), the monthly folder / ZIP flow shared by the raw, source and bulk day-file backups, parameterised by a `BackupKind`; since v1.7.6.2.1 a ZIP that does not open or fails its check is never appended to or replaced |
| `garmin_source_writer.py` | `garmin_data/source/` and `source_api_log.json` (v1.6.0.2) |
| `garmin_mirror.py` | mirror operation — delegates to `garmin_container.py` |
| `garmin_container.py` | `mirror.gla` — sole owner, no other module touches the container file |
| `garmin_import_mirror.py` | mirror import operation — orchestrates only; bulk files go through `garmin_bulk_writer` (`import_day_file`, `store_original`, v1.7.6.2) |
| `garmin_api_capability.py` | `garmin_api_capability_config.json` (v1.6.8) |
| `garmin_force_refetch.py` | `garmin_data/backup/force_refetch/` (v1.7.1.7) |
| `garmin_repair_resting_hr.py` (removable) | none — owns no files; writes only through `garmin_writer.write_day()` and `garmin_quality` (v1.7.5.7) |
| `garmin_track_migration.py` (removable) | none — owns no files; writes only through `garmin_writer` (`write_day()`, `rebuild_summary()`) and `garmin_quality` (`touch_last_checked()`) (v1.7.6.3) |
| `garmin_migration_snapshot.py` (removable) | `garmin_data/backup/migration/` (v1.7.6.3); puts files back only through `garmin_writer.restore_day_files()` and `garmin_quality` |
| `garmin_bulk_writer.py` | `garmin_data/bulk/raw/`, `garmin_data/bulk/aggregates/` (v1.7.6.1) and `garmin_data/bulk/source/` (v1.7.6) |
| `garmin_bulk_import.py` | none — orchestrates the four other bulk modules; writes only through `garmin_bulk_writer` (v1.7.6) |
| `garmin_bulk_json_import.py` | none — daily-values phase of the import; writes only through `garmin_bulk_writer`; touches no quality log, `raw/`, `summary/` or backup (v1.7.6.1); its result carries the inventory of the export (v1.7.6.7) |
| `garmin_bulk_rebuild.py` (removable) | none — owns no files; reads the originals in `bulk/source`, writes only through `garmin_bulk_json_import.store_day()` → `garmin_bulk_writer`; touches no quality log, `raw/`, `summary/` or backup (v1.7.6.5) |

### Invariants

- `garmin_validator.py` always runs before `garmin_normalizer.py`
- `garmin_utils.py` and `garmin_validator.py` are leaf nodes — no project-module imports
- `QUALITY_LOCK` must be held around all load-modify-save sequences on `quality_log.json`
- **`first_day` is not protected against manual edits or ENV overrides.** It is derived from Garmin's device history API, which does not guarantee completeness — older devices may not appear. `first_day` reflects the earliest known device registration, not necessarily the actual start of data collection. The GDPR Bulk Import is the only reliable source for data predating the oldest listed device. Incorrect `first_day` values can create archive gaps silently. Since v1.7.6.1 only the old import into `raw/` (`run_import()`) moves `first_day` back to the earliest imported day; the import of the daily values into the bulk store does not (`_finish_aggregates()` and the json phase never touch it). An export day older than `first_day` or older than the 180-day window therefore stays an export day: it has a `summary/` and counts as present, so the API sync does not fetch it.
- **`quality_log.json` is protected by a SHA-256 checksum** over stable core fields (`date` + `write`) stored in `_checksum`. Computed on every save, verified on every load. Mismatch triggers auto-restore from `backup/log/` and a yellow warning label in the GUI. Checksum covers only fields that never change through migration — adding new fields to entries does not invalidate it. Handle backups carefully — the schema migration creates a timestamped backup before any destructive operation, but ongoing integrity is the user's responsibility.
- `fetch_raw()` always returns `(raw, failed_endpoints)` — never raises
- `_fetch_and_assess()` always returns `(label, normalized, summary, fields, val_result)` — never raises
- `_write_assessed()` is only called after downgrade check passes — file never written if API result is inferior
- Downgrade protection is in `garmin_collector.main()` — not in `_upsert_quality()`
- `_save_quality_log()` is called after every successfully processed day in the fetch loop
  (`skip_backup=True`) and once more at loop-end as final safety-net (`skip_backup=False`).
  Every day is an atomic resume point — a hard abort cannot leave a raw file without a
  quality_log entry.
- No module reads `os.environ` directly — all config via `garmin_config`
- **A step that changes the quality log inside `garmin_collector.main()` works on the run's own `quality_data`** (like the backfills), never on a copy it loads itself: `main()` saves its in-memory log again after the sync, and a second copy's changes would be overwritten (v1.7.5.7, found on a real archive with the resting-HR repair — `last_checked` was lost and the MCP cache kept the old values)
- **Import mode is the exception to the rule above (v1.7.6):** it exits right after its phases and holds no quality log of its own, so `_mark_bulk_days()` and `_finish_aggregates()` (v1.7.6.1) load the log under `QUALITY_LOCK`, mark the days and save once. A step added to import mode that continues into the sync must hand its log over instead (the sync-start catch-up `_run_bulk_mark_catch_up()` does: it works on the run's own `quality_data`)
- **`entry["bulk"]` is not `entry["source"] == "bulk"` (v1.7.6):** every bulk-recheck rule (flagging, `bulk_upgrade_dates`, the timer's Bulk Recheck, `last_bulk` in the archive stats) reads `source`. `entry["bulk"]["intraday"]` and `entry["bulk"]["aggregates"]` are only written by `record_bulk_intraday()` / `record_bulk_aggregates()`; they take effect through `last_checked` (MCP cache) and are read by the catch-up of missing marks (`unmarked_bulk_days()`, v1.7.6.1, F-3). An export-only day (no `raw/`) has an entry with `source` `bulk` and `write` false: the bulk recheck then asks the API for it inside the 180 days, and the integrity check does not call it missing
- **Raising the bulk schema (v1.7.6):** `BULK_SCHEMA_VERSION` (`garmin_bulk_writer.py`) and `_BULK_MAX_SCHEMA` (`garmin_health_map.py`) are raised together — `tests/test_broker.py` pins that they are equal; the same for `AGG_SCHEMA_VERSION` and `_BULK_AGG_MAX_SCHEMA` (v1.7.6.1; both 2 since v1.7.6.5). A day with an older schema is written again the next time the same export is imported (same files, older schema → `update`) or when the rebuild from the kept originals runs; a day with a newer schema is kept and not read by an older reader. `tests/test_broker.py` and `tests/test_bulk_writer.py` take the "newer number" from `AGG_SCHEMA_VERSION + 1`, so the next raise does not break them
- **The result of a write is never ignored (v1.7.6.1, F-4/F-5/F-6):** `garmin_writer.write_day()` / `write_summary_only()` / `rebuild_summary()` answer `False` when nothing was written — also for a day whose aggregates file cannot be read (a summary without the export's values must not replace a complete one). A new caller counts that as an error of the day (`RuntimeError` inside the existing `except`, or `errors += 1`), never as done. Known open case: `commit_force_refetch()` and `_run_source_backfill()` call `_write_assessed()` and record the entry without looking at the answer (not examined for v1.7.6.1)
- **Resolved summary (v1.7.6.1):** a day with an aggregates file gets `summary/` from the API data plus the export's values (the API data win; a key or field the API lacks or holds empty comes from the export, field by field inside a section and one level deep since v1.7.6.3, F-11; `activities` is left out), `raw/` keeps API data only. Where the two sources define a value differently (floors climbed, sleep duration, minimum/maximum heart rate, the stress block of the day) the API value is used; the differences are listed in `REFERENCE_GARMIN.md`
- **API-Capability-Scan (v1.6.8):** the 15 baseline `fetch_raw()` endpoints
  always run — the capability config can only add optional candidates, never
  disable a baseline endpoint. Candidates are double-gated before joining a
  sync run (`enabled_by_user == True` **and** `status == "found"`), so a
  hand-edited config file cannot activate an unconfirmed endpoint.
  `run_capability_scan()` reuses `quality.QUALITY_LOCK` rather than a second,
  purpose-built lock — it never writes `quality_log.json` itself, but shares
  the Garmin client with the regular sync, and the two must never run
  concurrently.
- **Resolved (v1.6.8 Session 4):** all 19 capability-scan candidate fields
  are now broker-reachable — 6 interpreted into `summary/` fields
  (`body_weight`, `calories_resting`, `hydration_ml`, `endurance_score`,
  `hill_score`, `fitness_age`) via `get()`/`list_fields()`, the remaining
  13 exposed as archived in `raw/` (no value extraction) via the new
  `get_raw()`/`list_raw_fields()` path.
  Custom Dashboard/Explorer additionally gate the 6 interpreted fields by
  `enabled_by_user` (`list_fields(active_only=True)`, "Governance B"). See
  `REFERENCE_GARMIN.md` → "Raw-passthrough fields" and `NOTES_v168_D_01.md`/
  `NOTES_v168_D_02.md` for the full session history.
- **Resolved (v1.6.8 Session F, 2026-08-14):** dedicated test coverage
  added for `garmin_api_capability.py` (`load_config()`/`save_config()`/
  `update_endpoint()`/`reset_config()`/`build_args()`), `run_capability_scan()`,
  the `main()` step-0b entry point, `fetch_raw()`'s `extra_endpoints`
  param, `_fetch_and_assess()`'s `enabled_candidates` → `extra_endpoints`
  construction, `list_fields(active_only=True)`, `garmin_health_map`'s
  `get_raw()`/`list_raw_fields()`, and `health_map`/`gateway_map`'s
  passthroughs of both. `test_local.py` 631→696, `test_dashboard.py`
  464→496. See `NOTES_v168_F_01.md`.
- **Resolved (v1.6.8.1, 2026-08-16):** the inline double-gate
  candidate-selection filter (`enabled_by_user == True` **and**
  `status == "found"`) is extracted into
  `garmin_api_capability.get_enabled_candidates(config)` — a pure
  function, same double-gate condition, no behavior change.
  `garmin_collector.py::main()`'s fetch-loop section now calls it instead
  of inlining the filter; `load_config()` stays in `main()`, still read
  once per sync run inside `quality.QUALITY_LOCK`. 7 new checks added
  (`test_local.py` Section K): both gates satisfied, each gate alone,
  missing endpoint key, empty `endpoints` dict, multiple candidates,
  return order. `test_local.py` 696→703. DEPS scan also flagged
  `app/panel_outputs.py` as a possible shadow-copy — confirmed false
  positive (single-gate display filter, not the sync-time double-gate),
  no change made there. See `NOTES_v1681_01.md`.
- **Resolved (v1.6.9, Block 1a, 2026-08-21):** `garmin_collector.main()`'s
  regular sync fetch loop (Steps 1–9) now has dedicated end-to-end coverage —
  previously `main()` was only exercised via the step-0b Capability-Scan
  branch, never through the actual daily fetch path. New test runs `main()`
  against three fixed dates inside the existing `_TMPDIR` sandbox (`api.login`/
  `api.get_devices`/`api.fetch_raw` mocked, everything else — quality log,
  writer, validator, sync — real), covering all three outcomes in one pass:
  a clean `high` day (write confirmed on disk), a validator-`critical` `failed`
  day (write confirmed skipped, `recheck=True`), and a downgrade rejection
  (pre-existing `high`/`bulk` entry kept over a fresh, lower-ranked fetch) —
  the first test to exercise the downgrade guard (line 93 above) inside the
  real fetch loop rather than via the isolated `_check_downgrade()` unit
  tests (Section 15). `test_local.py` 703→716. See `NOTES_v169_01.md`.
- **Added (v1.7.1.7, 2026-08-31/09-01):** Force-Refetch mechanism — a
  deliberate, user-initiated opt-in to re-fetch a single day that two
  existing guards otherwise protect against overwriting
  (`garmin_sync.get_local_dates()`'s local-file presence check;
  `garmin_source_quality.compare_source()`'s freeze-when-present guard).
  Both guards remain fully intact for the normal sync path — Force-Refetch
  adds a `force` bypass parameter, it does not weaken either guard's
  default behavior. Two-phase design in `garmin_collector.py`
  (`run_force_refetch_preview()` / `commit_force_refetch()`) — considered
  and rejected a one-shot write-then-restore model, because reverting after
  writing would have to unwind four silos at once (`source/`,
  `raw/`+`summary/`, `quality_log.json`, backup ZIP); splitting fetch+compare
  from commit means nothing outside `source/` is touched until the user has
  confirmed the before/after comparison. New Sole-Write-Authority module
  `garmin_force_refetch.py` (snapshot + restore, `source/` only — `raw`/
  `summary` are derivable from `source` for the API origin). `get_local_dates()`
  deliberately NOT extended with a `force_dates` parameter — the orchestrator
  calls `_fetch_and_assess()` directly per date (same pattern as
  `_run_source_backfill()`), never routes through `main()`/the `missing`
  calculation, keeping the normal sync path's complexity (device history,
  `_check_downgrade()`, bulk-upgrade candidates, `MAX_DAYS_PER_SESSION`)
  completely unchanged and untouched by this feature. Field-level comparison
  (`quality/_fieldhash.py::compare_source_fields()`, new `KNOWN_FIELDS`
  constant in `quality/_assess.py`) is a label diff plus a per-field SHA-256
  hash diff — a label alone is too coarse, since two different payloads can
  coincidentally share a label. GUI (calendar dialog, confirmation flow)
  deferred to a later session. See `KNOWN_ISSUES.md` for the resolved entry
  and the two follow-up notes it left behind (`backfill_raw()`/
  `backfill_source()` name-check pattern unchecked; `garmin_writer.py`
  raw/summary atomicity gap now more relevant since Force-Refetch touches
  deliberately-risky days).
- **Resolved (v1.7.3):** `_run_bulk_field_backfill()` is a deliberate
  exception to the `_write_assessed()`-only-after-downgrade-check
  invariant above — it never calls `_write_assessed()`/`_check_downgrade()`
  at all. Instead every top-level raw key from the fresh fetch is merged
  additively into the existing `raw/` file via `garmin_merge.merge_field()`
  (never overwrites a non-empty value), which cannot downgrade a field by
  construction — a separate downgrade check would be redundant. Found live:
  bulk and api use incompatible raw shapes for fields bulk already
  populates (e.g. `stress.restDuration` vs. `stress.restStressDuration`),
  so a full-day replace (the mode's first, superseded implementation)
  could silently downgrade such a field even though the day's overall
  quality label never regressed. New generic give-up mechanism,
  independent of the existing day-level `attempts`/`recheck` bookkeeping:
  `quality.record_field_backfill_failure()` (single field) /
  `record_field_backfill_failures()` (batched — one persist/backup call
  for several fields, not one per field) increment
  `entry["field_backfill_attempts"][field]`; `timer_run_steps_backfill()`
  and the new `timer_run_bulk_field_backfill()` both read it via
  `FIELD_BACKFILL_ATTEMPT_LIMIT = 2` (mirrors `bulk_recheck`'s existing
  day-level "2 attempts, then final" pattern). See
  `changelog/anchor_delivery_bulk-field-backfill-additive-merge-fix.md`
  and the two anchor-deliveries preceding it for the full diagnosis
  history (live-verified, including a full `mirror.gla` restore
  specifically to re-run the days first touched by the superseded
  full-replace implementation).
- **Resolved (v1.7.4.0.4, 2026-10-06):** six gaps a mutation test pinned
  as current behaviour in v1.7.4.0.3 are now actually fixed, each with
  an extended test contract (not just "doesn't break"). Quality-log
  recovery: `_load_quality_log()` saves and tries to restore an
  unreadable file instead of silently starting empty, and now checks
  every entry's `date` on *every* load (not just once in `main()`) —
  moved here deliberately so the warning survives an independent call,
  e.g. the Archive Info panel's own refresh ("Variante B", chosen over
  a `main()`-local patch for exactly that reason). Found and fixed in
  the same pass: `_compute_checksum()` computed `source` before vs.
  after migration defaults were applied, causing a false mismatch (and
  a spurious restore) for any entry without an explicit `source` field —
  previously masked because `backup_quality_log()` always overwrote the
  monthly snapshot unconditionally; the new data-loss guard (below)
  surfaced it. Backup: `backup_raw()`/`backup_source()`'s Force-Refetch
  branch now actually runs (previously dead — see `REFERENCE_GARMIN.md`);
  `backup_quality_log()` refuses to overwrite a snapshot with less than
  half its day count. Collector: a negative `MAX_DAYS_PER_SESSION` is
  rejected instead of silently reaching `missing[:-1]`; a day can no
  longer be counted in both the saved and the error tally; `main()`
  tolerates an unparseable quality-log date instead of crashing before
  login. GDPR import (`run_import()`): downgrade protection now uses
  `_check_downgrade()` for every source, not just `source == "api"`
  (previously an existing `legacy`/non-API day with intraday data could
  be silently replaced by the export's aggregate-only version); date
  validated before any write (`except (ValueError, TypeError)` — a
  non-string date from a malformed entry used to crash it); stop event
  actually checked (`_is_stopped()` was registered but never read).
  `garmin_import.py`'s four bulk-entry loops tolerate a malformed
  (non-object) entry instead of aborting the whole generator. Schema
  migration: `_run_schema_migration()` now uses the new
  `write_summary_only()` — `raw/` is genuinely untouched, not just by
  convention (the log line/docstring claim was previously not quite
  true). Full detail per fix: `changelog/anchor_delivery_v1741-*.md`
  through `anchor_delivery_v1746-*.md`; decisions and the two
  self-found bugs above: `PROTOKOLL.md`, Baustein 6 and 8.

---

## garmin_app.py (Target 1 + 2)

Desktop GUI built with PyQt6. Target 2 is distributed as a PyInstaller `.exe` — `scripts/` must stay next to it at runtime.

### Key design decisions

**Script execution** — scripts run as subprocesses via locally installed `python.exe`. `_find_python()` searches PATH and common Windows install locations. `_build_env()` sets all `GARMIN_*` ENV variables before launch.

**Configuration** — all config passed via `os.environ`. `_build_env()` builds the full env dict from UI settings. No source patching, no temp files.

**Password security** — stored in Windows Credential Manager via `keyring`. Never written to disk. Passed to subprocesses via `GARMIN_PASSWORD` env var only.

**Token persistence** — after first SSO login, `garmin_security.save_token()` encrypts the OAuth token with AES-256-GCM. Library writes `garmin_tokens.json` to `GARMIN_TOKEN_DIR` — `save_token()` reads, encrypts, writes `.enc`, removes dir. On subsequent runs, `load_token()` decrypts and writes the file back for the library — removed immediately after login. The encryption key is stored in WCM under `GarminLocalArchive / token_enc_key`.

**Pitfall — lazy cfg in garmin_security:** `garmin_config` is imported lazily inside each function, not at module level. Reason: the GUI sets `GARMIN_OUTPUT_DIR` and calls `importlib.reload(cfg)` after the module is first imported — a module-level import would freeze the wrong path. Any future function added to `garmin_security.py` that needs `cfg` must follow this pattern: `import garmin_config as cfg` as the first line of the function body, never at module level.

**Stop button** — `self._active_proc` holds subprocess reference. `_stop_collector()` calls `proc.terminate()`, waits 5s, then `proc.kill()`.

**Background Timer** — daemon thread with priority mode: **Bulk Recheck** runs first as long as candidates exist (`source=bulk` + `recheck=True` + ≤180 days), oldest first — no random selection. Once exhausted, cycles through Repair → Quality → Fill. Repair re-fetches `failed` days, Quality re-checks `low` days, Fill fetches completely missing days. Each normal mode draws a random subset. Timer pauses during manual sync and resumes afterwards.

**Thread safety** — timer threads carry a `generation` integer. `_timer_generation` increments on Start/Stop — stale threads exit immediately.

---

## garmin_app_standalone.py (Target 3)

No subprocesses — runs collector in a thread via `_run_module()`. Uses `importlib` to load modules dynamically from `sys._MEIPASS/scripts/`. Stop handled via `module.main(stop_event=ev)` — the collector registers the event with itself and `garmin_api` via `set_stop_event()`. No `module.__dict__` injection (v1.5.6.3).

---

## `test_local.py`

> **Since v1.7.4.0.2 the sections below live in one file per module** (see `MAINTENANCE_GLOBAL.md`, "Test suite"); the numbers and letters (1–16, A–L, 4b–4l) are the historical section labels, still used in test comments and the changelog. Mapping: 1, 2, 8 → `test_basics.py`; 3 → `test_normalizer.py`; 4, 4b–4e, A → `test_quality.py`; 4f, B, F → `test_backup.py`; D → `test_source_writer.py`; 4g, C, C2, C3 → `test_container_mirror.py`; 4h, C4 → `test_import_mirror.py`; 4i, 4j, 6, 15, E, E2–E5, 16 → `test_collector.py`; 4k and Fix 3 → `test_garmin_import.py`; 4l, J → `test_api.py`; K → `test_api_capability.py`; H → `test_live_fetch.py`; 5, 5b, 10 → `test_writer.py`; 7 → `test_security.py`; R → `test_redact.py`; 9, 9b, 14 → `test_validator.py`; G → `test_silo_check.py`; I, I2 → `test_silo_repair.py`; L → `test_force_refetch.py`; 11, 12, 13 → `test_local.py` (cross-module).

`compare_source` truth table (8 checks — +2 für unreadable→skip_warn, v1.6.0.4.9)
`unlock_meta` / `fulfill_order` / `detect_source` error-path tests (18 checks — v1.6.0.4.9.3)


```bash
python tests/test_local.py
```

### What is tested

1. `garmin_config` — ENV parsing, path derivation, constants
2. `garmin_sync` — all three sync modes, `date_range()`, `get_local_dates()`
3. `garmin_normalizer` — `normalize()`, `safe_get()`, `_parse_list_values()` (dict-key lookup for list-of-dicts, positional index for list/tuple items — the latter fixed in v1.7.1.13, Issue #6, previously always read `item[1]` regardless of the index passed), `summarize()` (HRV `lastNightAvg` primary key, no fallback — v1.7.1.13, Issue #8; `blood_pressure` section added — six scalars from `get_blood_pressure`'s daily aggregate plus a derived `worstReading` object, same-category tiebreak on chronologically latest measurement — v1.7.1.14, Issue #7). `CURRENT_SCHEMA_VERSION` 3 → 4 alongside the new section (purely additive, but bumped so the self-healing/schema-migration loop regenerates already-archived summaries from `raw/` automatically)
4. `garmin_quality` — `high`/`standard`/`failed` labels (v1.5.7), upsert, round-trip, migrations, thread safety, device_id fields, field-level parseability guard (F8, v1.6.5.8 — malformed intraday arrays no longer labeled `high`; `field_downgrades` recorded and removed again on clean re-assessment). `body_battery`'s real `[ts,status,value]`/`[ts,status,value,extra]` triplet shape now correctly reaches `"high"` (v1.7.1.13, Issue #6 — regression-guarded against the `dict_key=1` path and short-tuple inputs). `hrv` field quality label reads `hrvSummary.lastNightAvg`, no fallback (v1.7.1.13, Issue #8)
5. `garmin_writer` — `write_day()`, file content, `read_raw()`
6. `garmin_collector` internals — `_fetch_and_assess()` tuple, `val_result` structure, `set_stop_event()` distribution to `garmin_api` and bilateral clearing (v1.5.6.3), `run_import()` quality-failed counting (Fix 3, v1.6.5.8 — `quality: "failed"` days counted in `failed`, not `ok`; tested via mocked `garmin_import.load_bulk()`). `main()`'s regular Steps 1–9 fetch loop — ok/failed/downgrade in one pass, mocked `api.login`/`api.get_devices`/`api.fetch_raw` against the real quality log + writer inside `_TMPDIR` (v1.6.9, Block 1a — see Invariants below)
7. `garmin_validator` — schema load, all issue types, status escalation
8. `garmin_writer` — `read_raw()` edge cases, `_should_write()`, `_is_stopped()`
9. `garmin_validator` — schema load, all issue types, status escalation, Fail-Closed when schema absent (v1.5.6.3)
10. `garmin_security` — AES key derivation, save/load round-trip, wrong key, clear
11. `garmin_utils` — `parse_device_date()`, `parse_sync_dates()`, `extract_date_from_filename()`
11. `INVARIANTS` — `fetch_raw` return type, `_process_day` tuple length, write-only ownership
12. `ROBUSTNESS` — empty raw, corrupt JSON, stop event, non-dict input
13. `PIPELINE_E2E` — full day through pipeline: write → quality → read
14. `v1.4.3` — value range validation, downgrade logic
15. `_check_downgrade` — all edge cases
16. `_run_self_healing` — schema version bump, status improvement
A. `garmin_quality` v1.5.1 — checksum, backup trigger, integrity warnings
B. `garmin_backup` — raw backup, consolidation, quality log snapshot, restore, integrity check, own downgrade guard in `restore_raw_days()` (Fix 2, v1.6.5.8 — `skipped_already_current` when an existing file is already at `"high"` quality). v1.7.5.6 (`test_backup.py` 4f3/4f4, both modules via `_BK_KINDS`): a rewritten day replaces its ZIP entry right away through `backup_raw()`/`write_day()` (and `patch_source_field()` for source), unchanged content leaves the ZIP byte-identical; `check_*_stale_backups()`/`refresh_*_backups()` — changed ZIP entry, same-size/other-content (CRC32), changed copy in the open month folder, no backup at all (not counted), identical (nothing), two months in one run, invalid file (broken JSON, list, for raw a wrong `date`) reported and not copied, copy failure counted, missing folders, unreadable ZIP; the collector step 3d in `test_collector.py` (runs once per store, also with a cancelled login or a login error, a failing check/refresh is a warning, the import mode returns before it). One check per write path pins that the monthly ZIP holds the rewritten day (each first moves the day into the ZIP, then runs the path): steps backfill (E2) and bulk field backfill (E5) in `test_collector.py`, mirror import in `test_import_mirror.py`, silo repair #3 and #7 in `test_silo_repair.py`; the collector helper reads the ZIP entry after the next consolidation, which is what exposes a stale backup. The old checks "file stays in the month folder" and "existing ZIP entry is kept" were turned around on purpose, in `test_backup.py`, `test_local_context.py` and `test_garmin_import.py`. v1.7.6.2.1: the module functions are thin shells over `garmin_backup_common`, so these checks also pin the wiring (names, return keys, the module's logger — `_blogged` swaps the module's `log`); the `testzip` patches count calls (check before the append, after it, of a rebuilt ZIP) and follow the order of the shared flow; the one `_zip_contains` probe patches `garmin_backup_common.zip_contains`
C. `garmin_mirror` — `is_reachable`, `run_mirror` → container, `is_container`, `garmin_token` exclusion. `device_table.json` in `quality_log`-Section (pack + restore). T2 Hidden-Import-Fix (`cryptography.hazmat.primitives.kdf`). Tests für `_restore_device_table` ausstehend.
C2. `garmin_container` — `unlock_meta`: happy path + wrong password + missing file + non-container + tampered HMAC (10 checks). `fulfill_order`: roundtrip + wrong password + empty order (5 checks). (v1.6.0.4.9.3)

**Steps Intraday Foundation + Backfill (v1.6.3):** `steps_series` in `garmin_map._FIELD_MAP`
(covered in `test_dashboard.py`, not here — see `MAINTENANCE_DASHBOARD.md`). In this suite:
`assess_quality_fields()` — `steps` field high/medium/failed (3 checks, Section 4).
`garmin_merge.merge_field()` — additive merge, no-overwrite, non-dict guard (6 checks).
`garmin_source_writer.patch_source_field()` — file patch, log annotation, no-op on
missing source file (6 checks). `_upsert_quality()` / `record_attempt()` —
`backfilled_fields` parameter, additive merge across calls (4 checks). Section E2:
`garmin_collector._run_steps_backfill()` — no-op on empty `SYNC_DATES`, correct
`api.api_call()` invocation, merge result in `raw/`, `backfilled_fields` + `fields`
recorded, stop-event respected, per-day error resilience, `write_day()` failure and
the generic `except Exception` path both increment `field_backfill_attempts.steps`
(v1.7.3 — previously only two of four failure paths were tracked, found while
live-verifying the give-up limit), plus a downgrade-guard case where `write_day()`
succeeds but `record_attempt()`'s `quality_log` update is itself silently blocked
by `_upsert_quality()`'s day-level downgrade guard — the success path still
increments `field_backfill_attempts.steps` in that case (found via an external
diagnostic tool after the rest of this section was written) (16 checks).

C3. `garmin_import_mirror` — `detect_source`: container / nonexistent path / plain folder (3 checks). (v1.6.0.4.9.3)
D. `garmin_source_writer` + `garmin_source_quality` (v1.6.0.2 / v1.6.0.4.6) — `SOURCE_DIR` + `SOURCE_API_LOG` path derivation, `write_source` round-trip + overwrite + error cases (None/str input), `update_log` round-trip + overwrite + multi-date + `intraday_present`. `assess_source` (5 checks), `compare_source` truth table (6 checks), `assess_source_from_file` (2 checks), `write_source` guard behavior — skip + skip_warn (4 checks), `update_log intraday_present` (3 checks). Leaf-Node AST check migrated to `garmin_source_quality` (stdlib-only).
E. `garmin_collector._run_source_backfill` (v1.6.0.3) — no-op when `SYNC_DATES` empty, fetch called with correct date when `SYNC_DATES` set, stop event respected, per-day error does not crash loop.
F. `garmin_backup_source` (v1.6.0.4) — `SOURCE_BACKUP_DIR` path derivation, `backup_source` round-trip + missing source → False, monthly dir write, `_consolidate_source_months` ZIP + skip current month, `backfill_source` copy + idempotent, `check_source_backfill_needed` count, `_zip_contains`, Leaf-Node AST check. v1.7.5.6: a changed source file replaces its ZIP entry, `check_source_stale_backups`/`refresh_source_backups` (same cases as for raw, see B), `patch_source_field` backs up the patched file and a failing backup does not fail the patch.
G. `garmin_silo_check` (v1.6.0.4.7) — result structure (all keys, totals/counts sub-keys, checked_at format), clean-silo baseline (isolated tmpdir), all four check categories (#1 raw without quality, #3 source without raw, #5 summary without raw, #7 raw without summary), counts match list lengths invariant, finding lists contain date objects, Leaf-Node AST check.

H. `garmin_live_fetch` (v1.6.5, extended v1.7.1.14) — `_ENDPOINTS` structure
(10 entries: 8 always-on baseline incl. `get_hrv_data`, plus `get_blood_pressure`/
`get_body_composition` gated behind `capability_gate` — the tuple shape grew a
third element for this, `(method, key, capability_gate)`), `fetch_live()` success
path (all baseline endpoints, `live.json` written correctly; gated endpoints
skipped rather than attempted when not `enabled_by_user`, verified not counted
against the success ratio via the new `attempted_count`), partial-failure
path (one endpoint fails, rest still written, no crash), three login paths (error,
cancelled, own-login reusing an existing client), `progress` callback (messages
received per attempted endpoint + completion, scoped to baseline-only entries
in the test scenario where the capability config is absent; default no-op
backward compatible), `_write_live()` directory creation. 31 checks total.

I. `garmin_silo_repair` (v1.6.5.7, extended v1.6.5.8) — return structure
(`ok`/`failed`/`items`), empty-`fresh`-dict no-op, category #5 (orphan
summary) full round-trip: file present → unlinked + `status: "repaired"`,
file already gone → `status: "gone"`. Category #1's remaining edge case
(non-empty `raw_without_quality`, silent-skip on a corrupt raw file, true
error on a failed `_save_quality_log()`) and #3/#7's replay path (against a
`normalize()`-capable raw-data fixture derived from a real archive file)
closed in v1.6.5.8 (Netz 2) — see `tests/fixtures_netz2.py` for the fixture
generators and `NOTES_v1658.md` for the full diagnosis history. v1.7.6.1: a day
with export data (`bulk/aggregates`) — #5 never lists it, #7 rebuilds its
summary with `rebuild_summary()`, #3/#7 write the resolved summary, and a
`write_day()` that wrote nothing is an `error` of the day (F-4); `regenerate_raw.py`
has its first test.

**Netz 3 (v1.6.5.7) — error-visibility regression tests, folded into
existing sections rather than new ones** (see `CHANGELOG.md` v1.6.5.7 for
the full module-by-module list): Section C — `run_import_mirror()`
wrong-password and unknown-source cases now assert an `error` field is
present, not just `ok=False`. Section B — `check_raw_integrity()` asserts
`error is None` on success and set on a corrupt `quality_log.json`;
`restore_raw_days()` asserts the new `errors` dict carries a reason.
Section 10 — `get_enc_key_status()` mocked WCM success/failure, `get_enc_key()`
wrapper behaviour unaffected; `clear_token()` mocked WCM failure asserts
`False` instead of the previous unconditional success. Section 6 —
`read_summary()` missing-file case; `_run_schema_migration()` missing-summary
case asserts no crash.

L. **Force-Refetch (v1.7.1.7, Session 4, 2026-09-01)** — full coverage for
Bausteine 1–5, previously manual-only (single real end-to-end run against
the Garmin API, see `NOTES_v17117.md` "Session-Abschluss (2026-09-01)").
`test_local.py` 716→780 across four anchors:
- `compare_source_fields()` (`quality/_fieldhash.py`, via the
  `garmin_quality` facade) — identical dicts, single-field diff, field
  absent on one side, nested key order irrelevance (`sort_keys=True`),
  unserializable value (`repr()` fallback), `None`/`None` input.
- `garmin_source_quality.compare_source(force=True)` — all four
  existing/new combinations forced to `"write"`, regression check that
  `force=False` leaves the existing truth table untouched.
- `garmin_source_writer.write_source(force=True)` — bypasses the
  freeze-when-present guard against a real high-res file; `force=False`
  regression check confirms the guard still holds.
- `garmin_force_refetch.snapshot_source()` / `restore_snapshot()` —
  `had_prior_data` True/False, snapshot content round-trip, restore with
  and without an existing snapshot. **Documented finding, not fixed this
  session:** `restore_snapshot()` does not delete the snapshot file it
  restores from — asserted as current behaviour (not a bug) so a future
  intentional change shows as a visible diff here, not a silent
  regression; relevant once the deferred Restore GUI is built (see
  `KNOWN_ISSUES.md`).
- `garmin_collector.run_force_refetch_preview()` — no-prior-file case
  (`had_prior_data=False`, `quality_before="failed"`), real field
  difference against an existing `source/` file, per-day exception
  isolation (one day's fetch failure does not stop the rest), stop-event
  mid-list abort.
- `garmin_collector.commit_force_refetch()` — confirmed + `"high"` (write,
  `record_attempt()`, both backups called with `force=True`), confirmed +
  `"failed"` (`_should_write()` still blocks the write, entry still
  recorded), **the previously-never-exercised reject path**
  (`restore_snapshot()` called for real, both with and without an
  existing snapshot — `"no snapshot to restore"` surfaced instead of a
  crash), a preview entry that already carried an `error` (`skipped_error`,
  no crash on the missing `_normalized`/`_summary`/etc. keys), a mid-batch
  exception on one date (`skipped_error` for that date, the rest still
  commit), and a regression check that `_check_downgrade()` is never
  called for confirmed dates (deliberate bypass, see
  `commit_force_refetch()` docstring).
- `garmin_collector._start_force_refetch_log()` /
  `_close_force_refetch_log()` — file creation under
  `LOG_FORCE_REFETCH_DIR`, handler DEBUG level, rolling-limit pruning.
  Two test-harness pitfalls surfaced and were worked around, not found in
  the production code: (1) the log filename has second-resolution
  (`strftime %H%M%S`), so calling the function in a tight loop collides
  on the same file — the rolling-limit check instead pre-creates distinct
  files with controlled `mtime`s and triggers one real close to exercise
  the prune step; (2) `test_local.py` calls `logging.disable(logging.CRITICAL)`
  at the top of the file — a global cutoff that overrides any per-logger
  level, so the DEBUG assertion must also call
  `logging.disable(logging.NOTSET)` before raising the root logger's own
  level, and restore both afterwards.
- `garmin_api.api_call()` — `label=""` falls back to the method name in
  the new debug log line without a format-string error, both on success
  and on an exception.

`test_qt_app.py` 73→79 — `panel_archive.py::_get_quality_by_date()`
(missing file → `{}`, date→label map from a real `quality_log.json`,
`category`-key fallback, an entry missing `date` skipped rather than
crashing, corrupt JSON → `{}`, missing `"days"` key → `{}`). Same category
as the existing `_check_failed_days_popup()` coverage — a pure data
lookup, not a GUI interaction — not an exception to "GUI is not
automated" below.

`test_static.py` — three findings from Baustein 5 fixed in the same
session, not GUI-behaviour related: unused `QSizePolicy` import in
`dialog_force_refetch.py` (ruff); `SHARED_SCRIPTS` manifest missing the
three new files from Bausteine 3–4 (`app/dialog_force_refetch.py`,
`garmin/garmin_force_refetch.py`, `garmin/quality/_fieldhash.py`); one new
silent `except: pass` handler in `garmin_backup.py`'s force-replace
tmp-ZIP cleanup (Baustein 2, `anchor_delivery_17117-04`) — resolved with a
`log.debug()` instead of `pass`, restoring the Baseline-0 guarantee
without changing behaviour (the underlying error was already surfaced via
the enclosing `log.error()` one level up).

M. **Background Timer — Bulk Field Backfill + Steps Backfill fixes (v1.7.3).**
Closes the structural gap `garmin_import.load_bulk()` leaves in `hrv`/
`spo2`/`body_battery`/`respiration`/`training_status`/`race_predictions`/
`max_metrics` regardless of the day's age, live-verified against the real
archive (including a full `mirror.gla` restore) — see
`changelog/anchor_delivery_bulk-field-backfill-additive-merge-fix.md` for
the full diagnosis/fix history.
- `quality/_maint.py` — `record_field_backfill_failure()` (single field,
  persists immediately) and `record_field_backfill_failures()` (batched —
  added after a live run showed the singular function triggering 7-8
  redundant `quality_log.json` writes per bulk day). Both generic,
  independent of the existing day-level `attempts`/`recheck` mechanism.
- `garmin_app_controller.timer_run_steps_backfill()` — filter changed from
  key-presence (`"steps" not in fields`) to value comparison
  (`fields.get("steps") == "high"`); 140-day window removed (the
  underlying degradation assumption was disproven live — see
  `changelog/anchor_delivery_bulk-api-backfill-diagnose.md`), replaced by
  the new `FIELD_BACKFILL_ATTEMPT_LIMIT = 2` give-up threshold.
- `garmin_collector._run_steps_backfill()` success path — found via an
  external diagnostic tool run after the rest of this section shipped:
  `record_attempt()` can itself be silently blocked by
  `_upsert_quality()`'s day-level downgrade guard even though
  `write_day()` already succeeded (freshly assessed whole-day label
  ranks below the entry's stored label, e.g. an already-inconsistent
  archive state) — `steps` then exists in `raw/` but `quality_log.json`
  never reflects it, and the day is re-selected as a candidate forever.
  The success path now re-reads the entry right after `record_attempt()`
  and counts it as a failed attempt too if `fields["steps"]` didn't
  actually land as `"high"` — see
  `changelog/anchor_delivery_steps-backfill-downgrade-guard-fix.md`.
- `garmin_app_controller.timer_run_bulk_field_backfill()` (new) —
  candidate filter tests, all-fields-`"high"` exclusion, `api`-source
  exclusion, attempts-limit exclusion, mixed-fields-still-open inclusion
  (Section 23, `test_app_logic.py`).
- `garmin_collector._run_bulk_field_backfill()` (new, Section E5,
  `test_local.py`) — the actual regression test: an existing non-empty
  raw field (bulk-shaped `stress`) is never overwritten by a fresh fetch
  with a different value; a field bulk never had is merged in additively;
  a field untouched by the fetch response stays exactly as-is; batched
  attempts-recording verified via a spy on the real
  `record_field_backfill_failures()` (confirms one call covering all open
  fields, not one call per field); error path records attempts for all
  still-open fields.

N. **Resting-HR repair (v1.7.5.7, removable).** The GDPR import had stored the
export's 7-day average as the resting heart rate of the day; new imports take
the day value, and `garmin_repair_resting_hr.py` corrects days already
archived (values from `source/`).
- `test_garmin_import.py` — `parse_day()` takes the day value, keeps the
  average as `lastSevenDaysAvgRestingHeartRate`, an absent day value stays empty;
  `normalize()`/`summarize()` carry it through (4 checks that turned the old
  behaviour around).
- `test_quality.py` — `touch_last_checked()` (4 checks: only `last_checked`
  changes, the log checksum stays, unknown day not created, never saves).
- `test_repair_resting_hr.py` — detection, repair of all value cases
  (different, equal, no day value, not a number), summary, quality log (only
  `last_checked`, checksum, one save), backup ZIP, lock, second run, dry run,
  failing days, stop, interruption, changed meanwhile, explicit folders,
  scheduler hint, and the shared quality log of the caller.
- `test_collector.py` section 4u — step 3e: only `"1"` starts it, the variable
  is removed when read, before the login, after migration and backup refresh,
  errors are warnings, import mode returns before it, and an end-to-end run in
  which the repair is followed by a save of the run's own log (the repaired
  day keeps its `last_checked`).
- `test_qt_app.py::TestRestingHrRepairHooks` — the popup (no folder, nothing
  to correct, Yes, No, days without an original, scan error) and the trigger in
  `run_collector()` for the four combinations with the schema migration.
Checked on a copy of a real archive and then on the real archive itself, see
`CHANGELOG.md`.

**Removal list** — everything that belongs to the repair carries the marker
`RESTING-HR-REPAIR v1.7.5.7` (grep for it; the same list is in the docstring of
the module):
1. `garmin/garmin_repair_resting_hr.py` and `tests/test_repair_resting_hr.py`.
2. `compiler/build_manifest.py` — the `SHARED_SCRIPTS` entry, the
   `SCRIPT_SIGNATURES_BASE` entry of the module and `"def _run_resting_hr_repair"`
   in the collector's signatures.
3. `run_tests.ps1` and `tests/conftest.py` — the test file entry.
4. `garmin/garmin_collector.py` — the section "Resting-HR repair"
   (`_run_resting_hr_repair()`) and step 3e in `main()`; in
   `tests/test_collector.py` the blocks "main resting HR repair" (section 4u and
   the end-to-end block).
5. `app/panel_archive.py::_check_resting_hr_repair()` and the three lines in
   `app/outputs/sync.py::run_collector()`; `tests/test_qt_app.py::TestRestingHrRepairHooks`.
6. `scheduler/daily_update.py` — `_check_resting_hr_repair()` and step 4b.
7. Docs — the module section, the exception row, the `_run_resting_hr_repair`
   row and the invariant bullets in `REFERENCE_GARMIN.md`, the three bullets
   in `REFERENCE_INVARIANTS.md`, the variable row and the tree line in
   `REFERENCE_GLOBAL.md`, the module and test rows in `MAINTENANCE_GLOBAL.md`,
   the owner row in `GLA_GUIDELINES.md`, this section and the section in
   `USER_GUIDE.txt`. `CHANGELOG.md` stays as history.

What stays when it is removed: `garmin_quality.touch_last_checked()` (generic,
usable by any repair that rewrites archived days) and the corrected mapping in
`garmin_import.parse_day()` with its tests. The point in time is a decision of
the maintainer: it cannot be known when no archive can still carry days imported
before v1.7.5.7 — a restored old backup or a mirror from an older version can
bring such days back. After removal those days simply stay uncorrected; nothing
else depends on the repair.

O. **Bulk store (v1.7.6).** The heart-rate series of the GDPR export go into
`garmin_data/bulk/`, not into `raw/`. All tests run on synthetic data
(`tests/fit_builder.py` builds the FIT files), none needs a real export.
- `test_bulk_fit_reader.py`, `test_bulk_export_scanner.py`,
  `test_bulk_normalizer.py`, `test_bulk_writer.py`, `test_bulk_import.py` — one
  file per module; `test_bulk_import.py` is the end-to-end test of the whole
  pipeline (preview writes nothing, rerun changes nothing, part of an export
  never shrinks a day, stop, summary without names).
- `test_bulk_writer.py`, block "F-1": a day file that cannot be read for I/O
  reasons is `unreadable` (v1.7.6.1; before, it counted as new and a smaller
  state could replace the stored day): `day_status()`, `write_day()` and the
  untouched file are pinned.
- `test_quality.py` — `record_bulk_intraday()`; `test_collector.py` — the
  phases, `_mark_bulk_days()` and the session log of the import branch;
  `test_broker.py` section 6 and `test_mcp.py` section 15 — the bulk track and
  the cache; `test_qt_app.py::TestBulkImportFlow` — dialog, environment
  variables, confirmation; `test_build_output.py` — hidden imports of the bulk
  modules.
Checked on a copy of a real archive and on the real archive itself, see
`CHANGELOG.md` and `PROTOKOLL.md`.

P. **Daily values in the bulk store (v1.7.6.1).** The daily values of the GDPR
export go into `bulk/aggregates`, `raw/` stays API-only, `summary/` is
resolved. Synthetic data only; the old JSON import tests stay for `run_import()`.
- `test_bulk_json_import.py` (new) — the phase end to end: originals kept by
  hash, rejected days (invalid, too little data) are reported and not a
  failure, preview writes nothing, rerun changes nothing, a fuller day is not
  shrunk, stop, `day_window`, no name from the export in any output.
- `test_bulk_writer.py` — aggregates files (`write_aggregates`,
  `aggregates_status`, `load_aggregates`, `list_days`, `list_aggregate_days`),
  JSON originals, the F-1 states; `test_bulk_normalizer.py` — `has_window()`;
  `test_garmin_import.py` — `load_bulk_with_entries()` and the read hook.
- `test_writer.py` — the resolved summary (`write_day`, `write_summary_only`,
  `rebuild_summary`): API data first, the export fills (field by field since
  v1.7.6.3, section 5g), an unreadable aggregates file writes nothing; `test_quality.py` — `record_bulk_aggregates()`,
  `unmarked_bulk_days()`, the catch-up, `_save_quality_log()` returning a bool.
- `test_collector.py` — the json phase and the finish (`_finish_aggregates()`,
  `_apply_aggregates()`), marks and catch-up (`_mark_bulk_days()`,
  `_run_bulk_mark_catch_up()`, step 3f), and "ways" — every way that writes a
  summary with an export day: the sync fetch (including the downgrade guard
  and an unreadable aggregates file, F-5), steps and field backfill, the
  schema migration (F-4). `test_import_mirror.py` (F-6, resolved summary),
  `test_silo_check.py`, `test_silo_repair.py` (#3, #5, #7 with export days,
  `regenerate_raw.py`, F-4), `test_repair_resting_hr.py` section 10.
- `test_broker.py` sections 7 and 8, `test_mcp.py`, `test_dashboard.py` — the
  `bulk_daily` fields (four stress durations), `sleep_*_pct` from the export,
  units and labels, the cache picking up the new fields.
Checked on a copy of a real archive, see `PROTOKOLL.md`; the run on the real
archive is the maintainer's step.

Q. **Archive protection for the bulk store (v1.7.6.2).** Backup, mirror and silo check cover
`garmin_data/bulk/`. Synthetic data only; the real folder layout (`garmin_data/...`) is built in the
round trip test by a small helper (`_layout_env`) that re-points the `garmin_config` paths.
- `test_backup_common.py` (new) — the shared monthly folder / ZIP flow. Part A pins the module on folders it
  is handed (incl. `BackupKind.log`); Part B runs 27 scenarios per kind through the module of the kind
  (`garmin_backup`, `garmin_backup_source`) and through the shared code on identical folders and compares
  folders, ZIPs, results — the differential tests that carried the conversion of v1.7.6.2.1, since then a net
  for the wiring of the two shells; **Part C (v1.7.6.2.1) is the hardening**: a garbage file, a truncated ZIP
  and a ZIP with a failing entry are left untouched (month folder kept, one error line with the ZIP name and the
  exception type), a damaged month does not stop the next, a new ZIP that could not be finished is removed and
  built again by the next run, a source file the refresh cannot read counts as an error, error lines carry
  the exception type, the traceback goes to debug level (`exc_info`); C4 pins what stays as it was on purpose
  (`zip_contains` silent). `test_backup_bulk.py` (new) — the bulk kinds, the originals (one ZIP per prefix,
  never appended to, a damaged ZIP left untouched and reported, a stop request asked only when there is
  work), progress lines, `read_day_copy` / `read_original_copy`; the state before and after a backup is read
  with two helpers (`_day_work`, `_originals_work`) that do not use the code under test (v1.7.6.2.1: they
  replaced `check_needed()`).
- `test_bulk_writer.py` — `import_day_file` (every refusal, the fuller-wins rule, unreadable, newer
  schema, atomic write), `describe_container_path`, `list_originals`.
- `test_container_mirror.py` — the sections `bulk` / `bulk_source` (older containers stay readable),
  progress lines of `lock()` and `fulfill_order()`, a callback that raises. `test_import_mirror.py` —
  section 12: the bulk part of the import (bytes equal, export-only day without a raw error — F-8 —,
  fuller day kept or replaced, invalid file, wrong hash, unknown names, order bulk before raw,
  dry run, progress) and section 13: the **round trip** — one bulk day (series, daily values, a FIT
  original) is backed up, mirrored and lost; route A restores it through silo check and repair from
  the backup (one round, also when day file and original are lost together — v1.7.6.2.1; before it took
  two), route B imports the container into an empty archive; every file comes back byte for byte.
- `test_collector.py` — `_run_bulk_backup`, step 3g, the call after the import; `test_silo_check.py`
  (G4, G5, G6) and `test_silo_repair.py` (I7, I8, I9) — finding #8 / #9, F-10, the restore, its statuses and
  order; v1.7.6.2.1 (G6, I9): JSON originals found through the names in the backup ZIPs and restored (items
  with `kind` json), FIT originals found through the backup too (so a lost day file and its original are one
  check), a damaged backup ZIP does not stop the check, the layout is pinned against the real
  `backup_originals()`, the known limit (an original never backed up is invisible) is a test;
  `test_qt_app.py` — silo lines (incl. the JSON line and the "(JSON)" repair lines), import texts,
  progress lines in the log.
Checked against a copy of a real archive (check only, read-only); the first backup of the ~37,000
files and a real mirror import are the maintainer's step. v1.7.6.2.1: the silo check was also run read-only against the real archive (no finding, about 2 s);
the repair and the consolidation of a damaged ZIP are covered by synthetic archives only.

**Marker `BULK-IMPORT-PHASES v1.7.6` (removable)** — the choice of phases and
its GUI hooks carry it (grep): `garmin/garmin_collector.py` (section "Bulk
import phases": `_BULK_PHASES`, `_bulk_phases()`, `_mark_bulk_days()`,
`_apply_bulk_marks()`, `_apply_aggregates()`, `_finish_aggregates()`,
`_run_bulk_import()`; the sync-start catch-up `_run_bulk_mark_catch_up()` and its
call in `main()` (step 3f) belong to the same family but carry the label F-3, not the marker), `app/outputs/bulk_import.py` (`ImportOptionsDialog`,
`build_env()`, `TRIGGER_VARS`), the matching blocks in `tests/test_collector.py`
and `tests/test_qt_app.py::TestBulkImportFlow`, and the rows for
`GARMIN_BULK_PHASES` / `GARMIN_BULK_DRYRUN` in `REFERENCE_GLOBAL.md`. The bulk
modules and the bulk store do not carry the marker.

R. **Migration of the mixed archive (v1.7.6.3, removable).** Days that the
earlier import wrote into `raw/` are made again from `source/`; the daily
summary is resolved field by field. All tests run on synthetic archives; the
migration itself was run on a copy of a real archive and then on the real one
(see `CHANGELOG.md`).
- `test_writer.py` 5g (F-11): an API section that exists with empty fields
  (`heart_rates` with `null` minimum and maximum, `stress` without the series,
  `user_summary` with `null` fields) is filled field by field by the export;
  `0` and `False` are values; one level deep; `activities` keeps the whole-key
  rule; type conflicts (list against dict) keep the API value without an error;
  inputs are not changed. 5e `_expected()` builds the same rule by hand. 5h:
  `resolve_preview()` (states `ok`, `none`, `unreadable`, nothing written).
- `test_track_migration.py` — M1a pins the key form `garmin_import.parse_day()`
  writes per section, that the aggregates file holds the same values, that API
  sections do not look like it, that no existing check finds a mixed day (turns
  red when `garmin_import` changes); M1b detection, classes, coverage and the
  preview on a synthetic archive of every class; M3a/M3b `run_migration` (safety
  copy first and no write without it, stop per day, check again right before
  the write, read-back, quality log only `last_checked`, one save, a failing day,
  rerun finds nothing, dry run, blocked days untouched); M4 `pending()` and the
  scheduler hint; M6a lists in any order (F-13).
- `test_migration_snapshot.py` — M2a pins that the raw backup keeps only the
  newest version of a day and that `write_day()` cannot put a stored summary
  back; M2b the ZIP (all or nothing, checks, stop, free space, name clash,
  tampering with a consistent CRC), `verify_snapshot`, `list_snapshots`,
  `restore_day_files` / `restore_snapshot` (exact bytes, quality log merge,
  repeat), and the command line tool.
- `test_collector.py` section 4u "main track migration" — only `"1"` and
  `"preview"` act, the variable is removed when read, before the login, before
  the schema migration, the backup refresh and the resting heart rate repair,
  a missing module or an error is a warning, the preview ends the run, and an
  end-to-end run with the real module (the run's own save keeps the
  `last_checked` of the migrated day).
- `test_qt_app.py` — the popup (nothing to offer, Migrate, Preview only, Not
  now, waiting days, scan error) and the trigger in `run_collector()`
  (no live fetch after a preview); `test_build_output.py` — the two signatures.
Mutation runs per block are recorded in `PROTOKOLL.md` / `NOTES_v1.7.6.3_PROTOKOLL.md`.

**Removal list** — everything that belongs to the migration carries the marker
`TRACK-MIGRATION v1.7.6.3` (grep for it):
1. `garmin/garmin_track_migration.py`, `garmin/garmin_migration_snapshot.py`,
   `support-tools/archive-maintenance/restore_migration_snapshot.py`,
   `tests/test_track_migration.py`, `tests/test_migration_snapshot.py`.
2. `compiler/build_manifest.py` — the two `SHARED_SCRIPTS` entries, the two
   `SCRIPT_SIGNATURES_BASE` entries and `"def _run_track_migration"` in the
   collector's signatures; `tests/test_build_output.py` — the two checks.
3. `run_tests.ps1` and `tests/conftest.py` — the two test file entries.
4. `garmin/garmin_collector.py` — the section "Track migration"
   (`_run_track_migration()`) and step 3b2 in `main()`; in `tests/test_collector.py`
   the blocks "main track migration".
5. `app/panel_archive.py` — `_ask_track_migration()` and `_check_track_migration()`;
   `app/outputs/sync.py::run_collector()` — the lines for the variable and the
   "no live fetch after a preview" branch; `tests/test_qt_app.py` — the tests of
   the popup and the trigger.
6. `scheduler/daily_update.py` — `_check_track_migration()` and step 4c.
7. `garmin/garmin_config.py` — `MIGRATION_BACKUP_DIR`; `garmin/garmin_writer.py` —
   `restore_day_files()` and `resolve_preview()` (only the migration uses them)
   with their tests in `test_writer.py` 5h and `test_migration_snapshot.py`.
8. Docs — the two module sections, the exception row, the writer rows and the
   invariant bullets in `REFERENCE_GARMIN.md`, the bullets in
   `REFERENCE_INVARIANTS.md`, the variable row, the path row and the tree lines
   in `REFERENCE_GLOBAL.md`, the module and test rows in `MAINTENANCE_GLOBAL.md`,
   the owner rows in `GLA_GUIDELINES.md`, this section and the common task, the
   section in `USER_GUIDE.txt`. `CHANGELOG.md` stays as history.

What stays when it is removed: the field-wise resolution in `garmin_writer`
(`_fill_fields`, F-11; it also fixes days that are never migrated), `touch_last_checked()`
and the safety copies already made (`backup/migration/` stays on disk; the app never
deletes them). The point in time is a decision of the maintainer: an archive restored from
an old backup or a mirror from an older version can bring mixed days back.

S. **Rebuild of the daily values from the kept originals (v1.7.6.5, removable).** `bulk/aggregates`
is built again from the JSON originals in `bulk/source`, without the export; the parser reads the
readiness `score` and `AGG_SCHEMA_VERSION` is 2. All tests run on synthetic archives; the rebuild
itself was run as a preview and then for real on the real archive (see `CHANGELOG.md`).
- `test_garmin_import.py` — `detect_kind()` (each kind, partial rules, ambiguity, empty and broken
  input, pure: the input is unchanged and nothing is logged), the choice between several readiness entries of a date (latest
  `timestamp` in every read order, tie-break, entry without or with an unreadable `timestamp`),
  `days_from_originals()` (kinds from content, unknown files, conflicts, the order the caller gives),
  the seam `_collect_entries()` / `_days_from_entries()` and `parse_day()` reading the `score`.
- `test_bulk_json_import.py` — `store_day()` / `empty_summary()` shared with the import (the import
  behaves as before); `test_bulk_writer.py` — version 2, a day with 1 stays readable, is an `update`
  for the same files and then `unchanged`; `test_broker.py` — the reader takes 1 and 2, not the next.
- `test_bulk_rebuild.py` (new, section B7) — the rebuild brings back what the import wrote (same
  aggregates and `source_files`, a day imported with version 1 becomes 2), preview writes and creates
  nothing, rerun changes nothing, a fuller stored day is kept, damaged originals (unreadable, wrong
  hash, not JSON) make `ok` false and are listed by hash prefix, unknown kinds are listed, conflicts
  are counted, no originals, stop, a failing day, an unexpected error, `format_summary()`, and the
  imports of the module (`garmin_config` only inside a function, no `print`).
- v1.7.6.7 (P3): `test_garmin_import.py` section 4k5 — `parse_day()` with the two new sections (as delivered, events
  in time order also when another key sorts first, empty entries add nothing), the modes of `_KINDS` (single with
  conflict, list without duplicates), reading by name, `detect_kind()` for the two kinds and the kept families
  (no rule), the kept families through the hook and not into a day (ZIP and folder, a name that only ends like a
  family is not kept), `build_inventory()` (counts, folders, hidden folder, no name or address in the result), the
  inventory filled before the first day, unreadable files and the size limit at, below and above the limit (ZIP and
  folder, warning without a name); `test_bulk_json_import.py` — hashes of the new entries, a first export, then one
  with the new entries: only the days that gain an entry are `changed`, the others byte-identical, a day with a
  health status only rejected, originals of the kept families in the store (not the unknown family), preview equals
  import, rerun unchanged, the older export `kept`, inventory lines identical in preview and import and free of
  names, the resolved summary of a day with the new sections, backup and mirror of a kept original;
  `test_bulk_rebuild.py` — the new sections come back from the originals, kept originals are counted not warned about.
  A comparison of the old and the new `garmin_import` on 400 generated exports (all four old kinds, damaged entries,
  conflicts) found no difference; that script was not kept in the repository.
- `test_collector.py` section 4u "main bulk rebuild" — only `"1"` and `"preview"` act, the variable
  is removed when read, the stop check is handed over, the summary is finished on the run's own
  quality log (an end-to-end run inside the sync keeps the entries on that log), a preview
  finishes nothing and ends the run, the order against the track migration, the schema migration
  and the backup refresh, a missing module or an error is a warning.
- `test_qt_app.py::TestBulkRebuildHooks` — the popup (nothing to offer without folders, current
  numbers, original or JSON original; Rebuild, Preview only, Not now; damaged files and invalid
  numbers do not count; folders from `base_dir`; error in the scan) and the trigger in
  `run_collector()` (alone and with the other triggers; not asked after the track-migration preview;
  no live fetch after a preview). `test_build_output.py` — the seven bulk scripts and the signatures.

**Removal list** — everything that belongs to the rebuild carries the marker `BULK-REBUILD v1.7.6.5`
(grep for it):
1. `garmin/garmin_bulk_rebuild.py`, `tests/test_bulk_rebuild.py`.
2. `compiler/build_manifest.py` — the `SHARED_SCRIPTS` entry, the `SCRIPT_SIGNATURES_BASE` entry and
   `"def _run_bulk_rebuild"` in the collector's signatures; `tests/test_build_output.py` — the checks;
   `run_tests.ps1` and `tests/conftest.py` — the test file entry.
3. `garmin/garmin_collector.py` — `_run_bulk_rebuild()` and step 3b3 in `main()`; in
   `tests/test_collector.py` the blocks "main bulk rebuild". The optional `quality_data` parameter of
   `_finish_aggregates()` stays (it is harmless and the import run does not pass it).
4. `app/panel_archive.py` — `_ask_bulk_rebuild()` and `_check_bulk_rebuild()`;
   `app/outputs/sync.py::run_collector()` — the lines for the variable and the "no live fetch after a
   preview" branch; `tests/test_qt_app.py::TestBulkRebuildHooks`.
5. Docs — the module section, the panel row and the collector row in `REFERENCE_GARMIN.md`, the
   bullets in `REFERENCE_INVARIANTS.md`, the variable row and the tree line in `REFERENCE_GLOBAL.md`,
   the module and test rows in `MAINTENANCE_GLOBAL.md`, the owner row in `GLA_GUIDELINES.md`, this
   section. `CHANGELOG.md` stays as history.

What stays when it is removed: reading the `score`, `AGG_SCHEMA_VERSION` 2, `detect_kind()` and
`days_from_originals()` (a content-based way to read originals, small and tested), the order-free
choice of the readiness entry, and `store_day()` shared with the import. Days that already have
version 2 stay as they are. Without the rebuild, days with version 1 get the `score` the next time the
export is imported again.

### What is NOT tested

- GUI (tkinter) — verified manually before release
- `garmin_api` — requires live Garmin Connect credentials for the login
  cascade itself (`login()`, `api_call()`, `fetch_raw()`, `get_devices()`).
  Exception: `_is_mfa_no_callback_error()` and `_cause_fields()` (v1.6.5.9)
  are pure helpers, no credentials needed — dedicated coverage in Section J
  (`test_local.py`)
- `garmin_import` — requires actual Garmin GDPR export ZIP
- Export scripts in `export/`
- Full end-to-end with real API data
- `garmin_security.log_token_event()` (v1.6.5.2) — no dedicated test coverage yet;
  existing Section 7 checks (`save_token`/`load_token`/`clear_token`) confirmed
  passing alongside it (1399/1399), but the function itself — event/trigger
  values, `garmin_token_log.json` append behaviour, best-effort exception
  handling — is unverified by the test suite. Same gap now also covers the
  `valid`/`token_reused` event pair, `_format_event()`'s mixed
  compact/`indent=2` serialization, and the new `caller` field (all added in
  v1.6.5.7.1) — existing Section 7 checks confirmed passing alongside it
  (536/536), but none of these three additions have dedicated coverage.
  Same gap now also covers the `mfa`/`challenge_presented` event and the
  `cause_type`/`cause_detail`/`solved` extra fields (v1.6.5.9) — logged but
  not asserted. `has_unresolved_mfa_block()` (v1.6.5.9), the read-side
  counterpart, DOES have dedicated coverage (Section 7, 4 checks) — the
  write side (`log_token_event()` itself) remains the open gap

### When to run

After any change to: `garmin_config`, `garmin_sync`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`, `garmin_collector`, `garmin_security`, `garmin_api`, `garmin_utils`, `garmin_validator`, `garmin_silo_check`, `garmin_backup`, `garmin_backup_source`, `garmin_live_fetch`, `garmin_bulk_fit_reader`, `garmin_bulk_export_scanner`, `garmin_bulk_normalizer`, `garmin_bulk_writer`, `garmin_bulk_import`, `garmin_bulk_json_import`, `garmin_silo_repair`, `garmin_import_mirror`, `garmin_backup_common`, `garmin_backup_bulk`, `garmin_container`, `garmin_mirror`, `garmin_track_migration`, `garmin_migration_snapshot`.

---

## Common tasks

### Adding a new Garmin API endpoint

In `garmin_api.py`, append to `endpoints` in `fetch_raw()`:
```python
("get_method_name", (date_str,), "key_name"),
```

### Adding a new summary field

1. Add extraction logic to `summarize()` in `garmin_normalizer.py`
2. Run `export/regenerate_summaries.py` to backfill existing files

### Adding a new quality field

Add the endpoint key to `assess_quality_fields()` in `garmin_quality.py`.

### Updating the schema

1. Edit `garmin/garmin_dataformat.json`
2. Increment `schema_version` (minor for optional fields, major for required)
3. Update `CURRENT_SCHEMA_VERSION` in `garmin_normalizer.py` if summary schema changes
4. Self-healing loop will revalidate affected days on next run automatically
5. Schema migration loop will rewrite outdated summaries from raw on next sync — user sees backup popup before migration starts. No API call required. Raw files are never modified.
6. Since v1.7.6.6 the SQLite cache of the MCP layer reads all health days again by itself once every summary carries the new number (`mcp_update._reconcile_summary_schema()`); nothing to do. A new summary field that should be queryable also needs entries in `garmin_health_map._FIELD_MAP` and `mcp_field_registry.FIELD_UNITS` (`test_mcp.py` demands a unit for every registered health field), and a text field belongs in `_EXCLUDE_FROM_DAILY` of the Explorer and the Custom Dashboard (`test_dashboard.py` keeps the two sets equal). A damaged summary file is not repaired by the migration (it is skipped as "no summary file", finding F-16, pinned in `test_collector.py`).

---

### A damaged monthly backup ZIP (v1.7.6.2.1)

- **Symptom:** at each consolidation of that month an error line `... <zip> is damaged (BadZipFile: ...) — not touched, <area>/<month>/ kept as fallback`
  (line prefix `backup`, `backup_source` or `backup_bulk`), and a warning `backup refresh: cannot read <zip>` when the refresh reads its directory.
- **What the code does:** nothing is appended to or replaced in the ZIP; the month folder with the newest days stays where it is. A new ZIP that a call
  began and could not finish is removed again, so it never blocks the next run.
- **Cause:** damage from outside the app (disk, copy, sync client) or an interrupted append (the append mode is not atomic).
- **Rebuild:** (1) check that the daily files (`raw/`, `source/`, `bulk/raw` and `bulk/aggregates`) still exist; (2) move the damaged ZIP aside;
  (3) the bulk backup makes the copies again at the next sync start (`backup_all`), the source backup at the end of the next sync (`backfill_source`),
  the raw backup only through `garmin_backup.backfill_raw()` (offered once by a dialog after an update, no button); (4) read the closing line
  (`backfill_raw: N copied ...`). If the daily files are gone as well, the mirror container is the second copy.
- Not covered: `zip_contains` stays silent, so a damaged ZIP counts as "file missing" in the backfill check; the sync does not read the result of the
  backup refresh (its error count is only in the closing line `backup refresh (...)`).

### The migration of the mixed archive and its safety copy (v1.7.6.3)

- **Symptom of a day that is left:** the popup at the start of a sync still offers days, or the log of a run names blocked days.
  `Preview only` (popup) or `plan_migration()` names every blocked day with the reason: `no_aggregates` (import the Garmin export first), `not_covered`
  (the keys are named: the store holds other values than the raw file for them; import the export again if it is a newer one), `source_unreadable`,
  `raw_unreadable`, `aggregates_unreadable`. A blocked day is never changed.
- **Safety copies:** `garmin_data/backup/migration/migration_YYYY-MM-DD_HHMMSS.zip`, one per run that wrote something; the oldest holds the state before the first
  migration. The app never deletes them (about 25 MB for an archive of 2,900 days); delete old ones by hand when they are not needed any more.
- **Put a copy back:** stop every sync and timer, then `python support-tools/archive-maintenance/restore_migration_snapshot.py --list`, `... --dry-run <name>`,
  `... <name>` (from the source folder, Python needed). Only files that differ are put back (byte for byte, the raw backup follows); days that are not in the ZIP
  stay; the quality-log entries of the restored days come from the ZIP, the others stay. A migrated archive that is restored is offered the migration again.
- **After a restore of the whole copy** the next migration run makes the same days again; it makes a new copy first.
- Not covered: the tool is a command line (no button in the app); a damaged ZIP is refused before anything is written.

## Quality tracking

Every downloaded file is assessed immediately. Result stored in `quality_log.json`.

**Why content-based quality:**
A response for an older day can contain daily aggregates only — valid JSON, far less content. File size is unreliable. Content inspection is the only safe method.

**Quality levels:**

| Level | Condition | Background Timer |
|---|---|---|
| `high` | Intraday data present (`heartRateValues` or `stressValuesArray` has entries) | Never re-downloaded |
| `standard` | Daily aggregates present, no intraday — as good as it gets for this day | Never re-downloaded unless `source=bulk` within 180-day window |
| `failed` | API error — no usable data | Re-tried until successful |

**Downgrade protection:** `high` stays `high`. No legitimate path exists for a `high` day to become lower quality.

---

## Sync modes

| Mode | Behaviour |
|---|---|
| `"recent"` | Last `SYNC_DAYS` days (default 90) |
| `"range"` | `SYNC_FROM` to `SYNC_TO` |
| `"auto"` | `first_day` → today. `first_day` detected once, stored permanently |

---

## Per-day resume safety

`_save_quality_log()` is called after every individual day (upgrade, downgrade, and error paths alike) — every day is its own atomic resume point. If interrupted, the next run resumes from the first unwritten day. Replaces the earlier chunk-based flushing (`SYNC_CHUNK_SIZE`, removed v1.4.2) — no separate checkpoint state needed. Does not affect `run_import()`.

---

## Known Garmin API quirks

- `get_fitnessAge()` (camelCase, no `_data` suffix) does not exist in
  current `garminconnect` versions — removed. Not to be confused with
  `get_fitnessage_data()` (the actual API-Capability-Scan candidate, wired
  into the broker as `fitness_age` in v1.6.8 Session 4) — different method,
  confirmed present and functional.
- `get_devices()` may return non-dict entries — filtered with `isinstance(d, dict)`.
- **Stress data:** `stress.stressValuesArray` as `[ts_ms, value]` pairs. Subtract `stressChartValueOffset` if present. Negative = unmeasured, filtered out.
- **Body Battery:** `stress.bodyBatteryValuesArray` as `[ts_ms, "MEASURED", level, version]`. Level at index 2.
- Login may require browser captcha on first run or after long inactivity — run manually in terminal.

---

## Session log behaviour

- Manual syncs: `log/recent/garmin_YYYY-MM-DD_HHMMSS.log`
- Background timer: `log/recent/garmin_background_YYYY-MM-DD_HHMMSS.log`
- Error sessions additionally copied to `log/fail/`
- `log/recent/` capped at 30 files — oldest deleted automatically
- `log/fail/` has no automatic limit
- Always written at DEBUG regardless of GUI log toggle
- Force-Refetch (v1.7.1.7): own rolling log at
  `log/force_refetch/force_refetch_YYYY-MM-DD_HHMMSS.log`
  (`garmin_collector.py::_start_force_refetch_log()`/
  `_close_force_refetch_log()`), capped at 30 files — same rotation shape
  as `log/recent/` above, own directory, no `log/fail/`-style error copy.
  Always DEBUG — includes `garmin_api.py::api_call()`'s per-endpoint
  "Fetching {label} ..." line, which is silent in a normal sync session
  (default `INFO`)
