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
              │     garmin_quality._upsert_quality()
              └── garmin_quality._save_quality_log()       (after every day)
```

### Module ownership

| Module | Sole write authority |
|---|---|
| `garmin_writer.py` | `raw/` and `summary/` |
| `garmin_quality.py` | `quality_log.json` |
| `garmin_security.py` | `garmin_token.enc` |

### Invariants

- `garmin_validator.py` always runs before `garmin_normalizer.py`
- `garmin_utils.py` and `garmin_validator.py` are leaf nodes — no project-module imports
- `QUALITY_LOCK` must be held around all load-modify-save sequences on `quality_log.json`
- **`first_day` is not protected against manual edits or ENV overrides.** It is derived from Garmin's device history API, which does not guarantee completeness — older devices may not appear. `first_day` reflects the earliest known device registration, not necessarily the actual start of data collection. The GDPR Bulk Import is the only reliable source for data predating the oldest listed device. Incorrect `first_day` values can create archive gaps silently.
- **`quality_log.json` has no checksums or integrity verification.** Manual edits or file corruption are not automatically detected. Handle backups carefully — the schema migration creates a timestamped backup before any destructive operation, but ongoing integrity is the user's responsibility.
- `fetch_raw()` always returns `(raw, failed_endpoints)` — never raises
- `_fetch_and_assess()` always returns `(label, normalized, summary, fields, val_result)` — never raises
- `_write_assessed()` is only called after downgrade check passes — file never written if API result is inferior
- Downgrade protection is in `garmin_collector.main()` — not in `_upsert_quality()`
- `_save_quality_log()` is called after every individual day — every day is an atomic resume point
- No module reads `os.environ` directly — all config via `garmin_config`

---

## garmin_app.py (Target 1 + 2)

Desktop GUI built with tkinter. Target 2 is distributed as a PyInstaller `.exe` — `scripts/` must stay next to it at runtime.

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

No subprocesses — runs collector in a thread via `_run_module()`. Uses `importlib` to load modules dynamically from `sys._MEIPASS/scripts/`. Stop handled via `threading.Event` injected into module globals.

---

## `test_local.py`

**Current count: 199 checks, 13 sections.**

```bash
python tests/test_local.py
```

### What is tested

1. `garmin_config` — ENV parsing, path derivation, constants
2. `garmin_sync` — all three sync modes, `date_range()`, `get_local_dates()`
3. `garmin_normalizer` — `normalize()`, `safe_get()`, `_parse_list_values()`, `summarize()`
4. `garmin_quality` — all four quality levels, upsert, round-trip, migrations, thread safety
5. `garmin_writer` — `write_day()`, file content, `read_raw()`
6. `garmin_collector` internals — `_process_day()` tuple, `val_result` structure
7. `garmin_validator` — schema load, all issue types, status escalation
8. `garmin_writer` — `read_raw()` edge cases, `_should_write()`, `_is_stopped()`
9. `garmin_security` — AES key derivation, save/load round-trip, wrong key, clear
10. `garmin_utils` — `parse_device_date()`, `parse_sync_dates()`
11. `INVARIANTS` — `fetch_raw` return type, `_process_day` tuple length, write-only ownership
12. `ROBUSTNESS` — empty raw, corrupt JSON, stop event, non-dict input
13. `PIPELINE_E2E` — full day through pipeline: write → quality → read

### What is NOT tested

- GUI (tkinter) — verified manually before release
- `garmin_api` — requires live Garmin Connect credentials
- `garmin_import` — requires actual Garmin GDPR export ZIP
- Export scripts in `export/`
- Full end-to-end with real API data

### When to run

After any change to: `garmin_config`, `garmin_sync`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`, `garmin_collector`, `garmin_security`, `garmin_utils`, `garmin_validator`.

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

---

## Quality tracking

Every downloaded file is assessed immediately. Result stored in `quality_log.json`.

**Why content-based quality:**
Garmin stores intraday detail for ~1–2 years. Older data returns daily aggregates only — valid JSON, far less content. File size is unreliable. Content inspection is the only safe method.

**Quality levels:**

| Level | Condition | Background Timer |
|---|---|---|
| `high` | Intraday data present (`heartRateValues` or `stressValuesArray` has entries) | Never re-downloaded |
| `medium` | Daily aggregates present, no intraday — as good as it gets | Never re-downloaded unless `source=bulk` within 180-day window |
| `low` | Minimal stats only | Re-tried up to `LOW_QUALITY_MAX_ATTEMPTS` times |
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

## Chunked sync

`SYNC_CHUNK_SIZE` (default 10) — days processed per chunk before `quality_log.json` is flushed. If interrupted, next run resumes from first unwritten day. Set to `0` for single-pass. Does not affect `run_import()`.

---

## Known Garmin API quirks

- `get_fitnessAge()` does not exist in current `garminconnect` versions — removed.
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
