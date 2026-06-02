# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.5.5.2**

---

## Planned

---

### v1.5.5.3 — Architecture Repair + Quality Module Cleanup

Four findings from the pre-milestone architecture health check.
`garmin_quality.py` is already open for the date parser — the sole-write
fix lands in the same session. Context and test findings complete the pass.

**What changes:**

- `garmin/garmin_quality.py` — new private helper `_extract_date_from_filename(path, prefix)`.
  Returns `date | None`. Replaces inline string slices and scattered `try/except`
  blocks in `_backfill_quality_log()`, `get_low_quality_dates()`, and
  `cleanup_before_first_day()`.

- `app/panel_archive.py` — `do_delete()` (Clean Archive): direct
  `quality_log.write_text()` replaced by routing through `garmin_quality`.
  Restores Sole-Write-Authority, QUALITY_LOCK coverage, and checksum
  recomputation on every write. Regression introduced during v1.5.4
  PyQt6 migration — v1.2.0 changelog explicitly required this routing.
  ⚠ Pre-session: verify whether `cleanup_before_first_day()` covers the
  full clean operation (raw/ + summary/ file deletion + log pruning) or
  whether a split call is needed.

- `maps/weather_map.py`, `pollen_map.py`, `brightsky_map.py`,
  `airquality_map.py` — `except (json.JSONDecodeError, OSError)` blocks
  in `_read_field()` extended with `log.warning`. Corrupt or missing
  context files currently produce silent `None` values with no observable
  trace. Applies identically to all four map modules.

- `tests/test_qt_app.py` — AST-based GUI-freedom guard added for
  `scheduler/daily_update.py`. Checks that neither tkinter nor Qt imports
  are present. Analogous to the existing Settings/Controller guard in
  `TestQtSmoke`. Regression safety — headless path must remain fully
  GUI-free across all future changes.

**What does not change:**
- Return values and behaviour of all three calling functions in
  `garmin_quality.py` — identical output
- Clean Archive behaviour visible to the user — identical
- Context map routing and field resolution — unchanged
- All existing test assertions — preserved

---

### v1.5.5.4 — Test Infrastructure Consolidation + Critical Archive Protocol

Combines two thematically related test infrastructure improvements into one release.

**Test Infrastructure Consolidation**

Extracts duplicated test-tracking boilerplate from four manual test scripts into a shared support module. Done before new tests are added — consolidating after further growth costs more.

- `tests/support.py` — new module. Contains `TestRunner` class with `check()`, `section()`, and summary output. Single implementation, no duplication.
- `tests/test_dashboard.py`, `tests/test_app_logic.py`, `tests/test_local.py`, `tests/test_local_context.py` — import `TestRunner` from `support.py`. Inline `_pass` / `_fail` / `_failures` / `check()` blocks removed.

**Critical Archive Protocol**

New test script and HTML report focused exclusively on archive integrity. Does not replace the existing test suites — adds a second layer: "Is the archive protected?" as a distinct question from "Does the code work?"

- `tests/test_critical_archive.py` — 58 checks across 9 risk groups. Imports `TestRunner` from `support.py`. Includes AST-based guard against drift from `test_local.py`. Runs as last step in `build_all.py`.
- `report_critical_archive.html` — generated after each run. Tab 1: failures only + guard errors (🦄 on guard failure). Tab 2: full check table, Happy Path / Corrupted Path. Tab 3: terminal log from build run (collapsed by default).
- `build_all.py` — extended with `test_critical_archive` as final step in `finally`-block. Terminal output written to temp file throughout the run.

Risk groups: Writer (A) · Normalizer (B) · Quality (C) · Collector (D) · Validator (E) · Sync (F) · Self-healing + corrupt log (G) · API + access protection (H) · Archive immutability (I).

**What does not change:**
- `tests/test_qt_app.py` — already uses pytest, not affected
- Test logic and assertions — behaviour identical, only the runner is centralised
- Test counts — all existing checks preserved

---

### v1.5.5.5 — Writer Flush Hardening

Adds `os.fsync()` to `garmin_writer.write_day()` after the atomic write completes.
Without this, Python reports success from the OS page cache — a power loss between
write and physical flush produces a corrupt or empty raw file with no error signal.

Activates one additional check in `test_critical_archive.py` Group A:
"write_day calls fsync" — confirming the call is made, which is the maximum
assertion verifiable at application level.

**What changes:**
- `garmin/garmin_writer.py` — `write_day()`: `os.fsync(f.fileno())` added after
  `f.write()` inside the `tmp` file context, before `tmp.replace(target)`.

**What does not change:**
- Return value of `write_day()` — `True` / `False` unchanged
- Atomic write pattern — tmp → replace preserved
- All callers — interface unchanged

---

### v1.5.5.6 — Sync Mode Input Validation & Daily Update Fix
 
Two related fixes for the same failure chain. `daily_update.py` triggered
a `ValueError` crash by setting `sync_mode = range` with empty date fields
in edge cases. Both sides are hardened independently.
 
**Root cause:** `_build_env()` in `daily_update.py` sets `GARMIN_SYNC_MODE = range`
on both branches — including the fallback path. `garmin_config.py` uses
`"2024-01-01"` / `"2024-12-31"` as hardcoded defaults for `SYNC_FROM`/`SYNC_TO`
when the ENV keys are missing or empty. If the ENV keys are set to empty strings,
`garmin_sync.py` receives an empty isoformat string and crashes with `ValueError`
after login has already been established.
 
**What changes:**
- `scheduler/daily_update.py` — `_build_env()`: both branches replaced with
  `GARMIN_SYNC_MODE = recent`. `GARMIN_SYNC_START` and `GARMIN_SYNC_END` removed
  from the ENV dict entirely — `recent` mode does not use them.
  `GARMIN_DAYS_BACK` set to cover the detected gap range. Daily Update never
  falls back to `range` or `auto` — `recent` is the only permitted mode.
- `garmin/garmin_sync.py` — `resolve_date_range()`: defensive guard raises
  `ConfigurationError` with a human-readable message if `sync_mode = range`
  and either `SYNC_FROM` or `SYNC_TO` is empty or not a valid ISO date.
  Fires before any API call.
- `app/panel_outputs.py` — `on_done()` in `_run_dashboards()`: `os.startfile(output_dir)`
  removed. Dashboards are visible in Tab 2 (QWebEngineView) immediately after build —
  automatic folder open is redundant since v1.5.4.2. "Open Data Folder" button
  remains available for manual access.
**What does not change:**
- `garmin_config.py` — `SYNC_FROM`/`SYNC_TO` default values unchanged;
  they are only read when `sync_mode = range`, which `daily_update` no longer sets
- Gap detection logic in `daily_update.py` — unchanged
- All other sync modes (`auto`, `recent`) in `garmin_sync.py` — unaffected
- `panel_archive.py` — pre-flight check explicitly out of scope for this patch

---

### v1.5.6 — Mirror Import

Multi-device support via import from a mirrored archive. Extends the existing
mirror feature with a reverse direction: a second device can import data from
a mirror folder created by the primary device.

**`garmin_import_mirror.py` — new module**

Sole Owner of the mirror import operation. Reads `mirror_meta.json` for version
checks, performs a quality-log-based delta analysis, and imports only days that
are missing or have better quality than the local archive. Pipeline entry point
is `summarize()` — `normalize()` is skipped because mirrored raw files are
already normalized. Summaries are always regenerated locally from raw, which
eliminates schema version conflicts structurally.

Conflict resolution for raw files: quality rank comparison via the existing
`_upsert_quality()` downgrade protection (`high` > `medium` > `low` > `failed`).
Higher quality wins — the local archive is never silently downgraded.

Context files: delta only — files missing on the target device are imported;
existing files are not overwritten (source is master).

**`garmin_mirror.py` — extended**

Writes `mirror_meta.json` to the mirror folder after a successful run. Contains
`gla_version`, `schema_version`, and `mirrored_at`. Written only on `ok=True` —
a failed or partial mirror never produces a meta file.

**What changes:**
- `garmin/garmin_import_mirror.py` — new module. Returns
  `{"raw_copied", "raw_skipped", "context_copied", "errors", "ok"}`
- `garmin/garmin_mirror.py` — writes `mirror_meta.json` on successful completion
- `garmin_app_base.py` — "Import from Mirror" button in Archive panel.
  Active only when mirror folder is configured and reachable. Dry-run dialog
  shows delta before import ("45 raw days, 12 context days"). Background thread,
  progress in log window. Timer pause/resume wired (same pattern as Bulk Import).

**What does not change:**
- `garmin_writer.py`, `context_writer.py`, `garmin_quality.py` — sole owner
  principle unchanged; import writes exclusively through existing owners
- `garmin_mirror.py` core logic — `shutil.copy2()`, EXCLUDE_DIRS, stats dict
- No encryption, no new dependencies

**Import invariants:**
- `normalize()` is never called on mirrored raw files — already normalized
- Summary files are never imported — always regenerated from raw
- `garmin_token` and `__pycache__` are never included in a mirror
- Import pauses the background timer for the duration of the operation

*Pre-condition: v1.5.5 stable. Mirror folder configured and populated by
the source device before import is attempted.*

---

### v1.5.6.1 — Encrypted Mirror Container

Introduces `mirror.gla` — a single encrypted container file replacing the plain
mirror folder. Extends v1.5.6 without changing the import protocol or pipeline.

The container format extends the "local-only" philosophy to transport: health
data on USB, NAS, or a cloud folder of the user's choice remains unreadable
without the password. No cloud dependency, no third-party service.

**`garmin_container.py` — new module**

Sole Owner of `mirror.gla`. Implements a section-based AES-256-GCM container
with three independent encrypted sections (quality_log, raw, context). Each
section has its own derived key — knowledge of one section key does not
compromise the others.

Key derivation: PBKDF2-HMAC-SHA256 (600,000 iterations) produces a master key
from the user's password and a per-container salt. HKDF-Expand derives
independent section keys from the master. The plaintext header is authenticated
via HMAC-SHA256 — offset manipulation without the master key is not possible.

Container writes are atomic: `mirror.gla.tmp` → `fsync()` → `os.replace()`.
An interrupted write never produces a corrupt container.

Import reads only what it needs: `unlock_meta()` decrypts only the quality_log
section for delta analysis; `fulfill_order()` decrypts only the sections
containing requested files. Raw and context data are never decrypted unless
explicitly ordered. No plaintext ever touches disk.

Spot-Check (introduced in v1.5.5) is removed from `garmin_mirror.py` — HMAC
verification on every container open provides stronger integrity guarantees than
a CRC32 sample check.

**Compatibility:** `garmin_import_mirror.py` retains support for plain mirror
folders (v1.5.6 format) for one release cycle. Folder support will be removed
in a future version.

**What changes:**
- `garmin/garmin_container.py` — new module. API: `lock()`, `unlock_meta()`,
  `fulfill_order()`, `is_container()`
- `garmin/garmin_mirror.py` — delegates to `garmin_container.lock()`.
  Password parameter added. Spot-Check removed.
- `garmin/garmin_import_mirror.py` — reads via `garmin_container.unlock_meta()`
  and `fulfill_order()`. Plain folder fallback retained for compatibility.
- `garmin_app_base.py` — password dialog for Mirror and Import operations.
  Settings field relabelled "Mirror target" (accepts folder or `.gla` file).
  `is_container()` used for button state detection.

**What does not change:**
- Import protocol from delta analysis onward — identical to v1.5.6
- Pipeline entry point, sole owner principle, all existing invariants
- No new package dependencies (`cryptography` already required)



---

### v1.5.7 — In-App File Viewer

Third tab in the existing `QTabWidget` structure (Tab 1 "Actions", Tab 2 "Dashboards", Tab 3 "Files"). Renders Excel output directly inside the app via AG Grid Community (MIT licence). JSON output is intentionally excluded — Open Folder in Tab 1 is the intended path for JSON.

**What changes:**
- `garmin_app_base.py` — Tab 3 "Files" added to `QTabWidget`. `QComboBox` lists recent output files from `dashboards/` folder (`.xlsx` only), scanned on tab switch. `QWebEngineView` renders selected file via AG Grid. "Open File" button calls `os.startfile(path)` — opens in whatever the system has registered for `.xlsx` (Excel, LibreOffice, WPS).
- `app/panel_outputs.py` — after a successful dashboard build, Tab 3 file list is refreshed automatically (same pattern as Tab 2 dashboard rescan after build).

**What does not change:**
- Tab 1 and Tab 2 — unchanged
- Dashboard build pipeline — no changes to specialists or plotters
- JSON workflow — Open Folder remains the access path

**Dependencies:**
- AG Grid Community (MIT) — loaded via CDN into QWebEngineView. No new Python package. Requires internet on first load unless bundled locally.
- Offline fallback: if AG Grid fails to load, a plain HTML table is rendered from the XLSX data as fallback.

**Licence:** AG Grid Community is MIT-licenced without restrictions. Handsontable CE is explicitly excluded — Commons Clause makes it incompatible with redistribution.

---

### v1.5.8 — Standalone EXE: --onedir Migration

Replaces `--onefile` with `--onedir` in `build_standalone.py` for T3.
Eliminates the per-launch extraction to `%TEMP%\_MEIxxxxxx` — all files
sit permanently unpacked next to the EXE. Startup time for T3 drops
significantly as a result.

**What changes:**
- `compiler/build_standalone.py` — `--onefile` → `--onedir`
- `build_combined_zip()` — ZIP logic updated to pack the output folder
  instead of a single EXE file
- `tests/test_build_output.py` — T3 checks updated for folder structure

**What does not change:**
- T2 (`build.py`) — stays `--onefile`, unaffected
- Total installed size — identical, only distribution format changes
- User workflow — ZIP download unchanged, EXE name unchanged

---

## Planned — v1.6

### v1.6 — Dashboard Render Registry

**Step 1 — Dashboard Consolidation & UI Refactor (pre-condition)**

The existing specialist set has grown organically and contains redundancy.
Before the registry is introduced — and before new specialists are added —
the current set is reviewed and cleaned up:

- Redundant or overlapping specialists are merged or removed
- `META["description"]` entries are revised for clarity
- The Create Reports popup widget (`garmin_app.py`) is reworked:
  full descriptions visible, column layout readable at a glance

Rationale: the registry should be built over a clean, stable specialist set —
not over a baseline that will be restructured again afterwards.

**Step 2 — Render Registry**

The dashboard render layer currently dispatches layout types via an `if/elif`
block in `dash_plotter_html_complex.py`. Every new dashboard requires a direct
edit to this file — the plotter grows as a side effect of new specialists, not
by its own logic.

v1.7 replaces this with a render registry: each specialist declares its render
function alongside its `META` and `build()`. `dash_plotter_html_complex.py`
becomes a pure dispatcher — it routes to the registered renderer without
knowing anything about layout-specific logic.

**What changes:**
- `dash_plotter_html_complex.py` — dispatch by registry lookup, not `if/elif`
- Each `*_dash.py` specialist — declares a `render()` function or a
  `RENDERER` reference alongside `META` and `build()`
- Adding a new dashboard no longer requires touching the plotter

**What does not change:**
- The neutral dict contract between specialist and plotter remains identical
- `dash_runner.py` — no changes; it calls `plotter.render()` as before
- Existing specialists — migrated mechanically, no logic changes

**Motivation:** v1.6 introduces a second Garmin source; v2.0 adds external
sources (Strava, Komoot). Each will bring new dashboard layouts. A growing
`if/elif` chain is not a sustainable dispatch pattern at that scale.
The registry closes this before v2.0 begins.

**Pre-condition:** `dash_plotter_html_complex.py` internal restructuring
(v1.4.8 pipeline hardening) must be complete — layout paths cleanly separated
before the registry is introduced.

---

### 1.6.1 — Encrypted Dashboards (Optional Export)

Introduction of an option to encrypt reports before saving with AES-256-GCM. This allows for the secure transfer of dashboards to third parties (e.g., trainers or doctors) without sending health data in plain text.

- Secure Transfer: Creates a password-protected HTML file that is only decrypted after entering the password in the browser.
- Privacy: Uses the proven encryption technique already used for securing login tokens in the project.
- Local Control: The password is set by the user during export; decryption occurs solely on the client side in the browser — no cloud server involved.

Motivation: Extension of the "Local-only" philosophy in case data must leave one's own computer.

---

### 1.6.2 Sleep Dashboard → Explorer drill-down

When the Sleep Dashboard is built, an Explorer HTML is automatically generated for the same date range with four preset intraday fields (Heart Rate, Stress, Body Battery, Respiration). Each row in the Sleep Dashboard carries a link to this Explorer file.

- Two output files, not one per row: `sleep_dashboard_RANGE.html` + `sleep_explorer_RANGE.html`
- Files are relative-linked — both must be in the same output folder
- The Explorer opens at full range; the user navigates to the relevant day themselves
- T3-compatible — no Python callback from the browser, no server component

*Pre-condition: Sleep Dashboard and Explorer Dashboard both stable and tested.*

---

### v1.6.3 — Heatmap Dashboard
New specialist: activity and physiological patterns visualized as time-of-day × date heatmaps.
New:

- `dashboards/heatmap_garmin_html_dash.py` — Specialist: fetches intraday series for N days via `field_map.py`, pivots to hourly bins, returns neutral heatmap dict
- `garmin_map._FIELD_MAP` — `steps_series` entry added (movement array, analogous to heart_rate_series)
- `dash_plotter_html_complex.py` — `heatmap` chart type added via render registry (v1.6 pre-condition)

Metrics (candidates):

- Heart Rate heatmap (X = time of day 0–24h, Y = date, color = bpm)
- Steps heatmap (activity regularity)
- Stress heatmap
- Body Battery heatmap

Pre-condition: v1.6 Render Registry must be complete — new specialist registers its own renderer, no `if/elif` edit required.

---

### v1.6.4 — Custom Dashboard Builder

A dialog in `panel_outputs.py` that replaces the fixed specialist list with free field selection. The user picks Garmin and Context fields, sets a date range and output format — the app assembles and renders the result directly, without persisting a specialist file.

**What changes:**
- `panel_outputs.py` — new "Custom Dashboard" button in the Export section; opens a dialog with field picker (Garmin + Context), date range input, and format selector
- `dash_runner.py` — accepts an ad-hoc specialist dict (fields + metadata) in addition to file-based specialists; no new file written to disk
- `field_map.py` / `context_map.py` — `list_fields()` used to populate the picker dynamically

**What does not change:**
- Plotter stack — called identically to the existing Create Reports flow
- Existing specialists — unaffected; the fixed list remains available

**Pre-condition:** v1.6 Render Registry stable — field_map.py broker and plotter dispatch finalized before the picker is built against it.

---

### v1.6.5 — Live Tracking Dashboard

Extends the sync path with a lightweight live fetch for the current day. The result is stored in `garmin_data/live/live.json` and rendered as a standalone dashboard in the Dashboards tab — not part of Create Reports.

**What is new:**

- `garmin_data/live/live.json` — snapshot of the current day: Body Battery intraday series, Heart Rate intraday series, steps, stress + sync timestamp
- `garmin/garmin_live_fetch.py` — lightweight module: fetches today's intraday data via the `garminconnect` API only; no archive write access, no `quality_log` contact
- `dashboards/live_tracking_html_dash.py` — specialist: reads `live.json` + last sleep entry from the archive, returns a neutral dict
- `live_tracking.html` — generated dashboard: upper half shows today's progression (Body Battery, HR, steps, stress); lower half shows last night analogous to the Sleep Dashboard
- `panel_actions.py` — new "Update Live" button in the Life Tracking area (right side); triggers `garmin_live_fetch.py` and re-renders `live_tracking.html`

**Triggers:**

- End of "Sync Garmin" → live fetch appended automatically
- "Update Live" button → live fetch only, no archive sync
- "Create Reports" → Live Tracking is **not** included

**What does not change:**

- Archive pipeline — no access to `quality_log`, `raw/`, `summary/`
- Existing dashboards — unaffected
- `field_map.py` — no new broker entry required; `garmin_live_fetch.py` calls the API directly (intraday is not an archived field)

**Invariant:** `garmin_live_fetch.py` writes exclusively to `garmin_data/live/`. No write access to any other directory.

**Pre-condition:** none — independent of the v1.6 Render Registry; `live_tracking_html_dash.py` can use the existing HTML plotter path.

---

## Planned — v1.7

### v1.7 — FIT Pipeline

Standalone plugin pipeline for Garmin activity data (.fit files). The existing
Health pipeline is not modified — the FIT pipeline runs as an independent,
parallel pipeline alongside it. Full concept in `docs/KONZEPT_fit_pipeline.md`.

**Architecture:**
- `garmin/fit/` — isolated pipeline: `fit_master.py`, `fit_api.py`, `fit_import.py`,
  `fit_parser.py` (stable shell + adapter layer), `fit_normalizer.py`,
  `fit_quality.py`, `fit_writer.py`
- `garmin_data/fit/` — own directory: `raw/` (.fit originals), `summary/` (JSON),
  `tracks/` (GeoJSON, GPS only on demand), `log/`
- `fit_map.py` — peer broker alongside `field_map.py` and `context_map.py`;
  `garmin_fit_map.py` registered beneath it
- Two entry points: Bulk Import (manual .fit files) + Sync (Garmin Connect API)
- Both paths merge at `fit_parser.py` — identical pipeline from there onward

**Quality model:** matrix per activity — `file_integrity`, `session`, `gps`,
`fields`, `duplicate`, `merge_candidate`, `extreme_event`, `event_type`.
Merge candidates flagged silently at import; lazy hint shown when user opens
the activity. No auto-merge — user decides always.

**Documentation:** `docs/MAINTENANCE_FIT.md` and `docs/REFERENCE_FIT.md`
created with first module and maintained in every session that touches FIT modules.

*Pre-condition: PyQt6 migration (v1.5.4) complete for GUI control elements
(Import/Sync buttons in `panel_outputs.py`). Pipeline itself has no blocker.*

---

### v1.7.1 — FIT GUI Integration

Import and Sync control elements for the FIT pipeline added to `panel_outputs.py`.
Steuerungslogik only — no activity view, no dashboards, no map display.
Those follow after PyQt6 migration is stable and the pipeline is proven.

**What changes:**
- `app/panel_outputs.py` — FIT Import button (Bulk), FIT Sync button;
  same subprocess pattern, same log window as Health pipeline
- `REFERENCE_GLOBAL.md` — two new ENV variables:
  `GARMIN_FIT_IMPORT_PATH` (Bulk Import source folder),
  `GARMIN_FIT_SYNC_ENABLED` (FIT Sync on/off, separate from Health Sync)
- `compiler/build_manifest.py` — all new FIT modules added to `SHARED_SCRIPTS`

**What does not change:**
- Health pipeline controls — unchanged
- `garmin_security.py` — existing token reused, no second auth path
- `scheduler/daily_update.py` — FIT Sync path must be fully headless;
  no GUI dependency allowed

*Pre-condition: v1.7 FIT Pipeline stable.*

---

### v1.7.2 — Context Integration & Location Fallback

Location-aware context collection extended with GPS data from FIT activities
and a formal state tracking layer (`quality_context.json`).

**Fallback chain (coordinates per day):**
1. GPS start point from .fit (only when GPS track present and bounding box < 50 km)
2. `quality_context.json` (travel block or home)
3. `local_config.csv` (manual)
4. GUI default (home location)

**`quality_context.json` — new module `context_quality.py`**
Single source of truth for which dates were fetched with which coordinates.
Travel entries imported from `local_config.csv` on sync — CSV cleared to
header-only after import. Removing a travel block triggers re-fetch of affected
dates with home coordinates. Sole write authority: `context_quality.py`,
symmetric to `garmin_quality.py`.
Validation at CSV import: multiple travel blocks → hard stop. Overlapping
date ranges → hard stop.

**Extreme Events**
Activity with GPS bounding box > 50 km flagged as `extreme_event: true` in
`fit_quality_log.json`. Two categories:
- Slow (< 50 km/h between any two GPS points) → context pull 1× per hour
- Fast (> 50 km/h between two points) → context pull every 50 km

Context pull runs automatically after merge confirmation (if merge candidate)
or on import. Weather data written directly into activity summary JSON —
not into `context_data/`. Implemented via `activity_context_plugin.py`
(same APIs as context pipeline, output only differs).
Historical data available without time limit (Open-Meteo) — no urgency.

*Pre-condition: v1.7.1 stable. FIT pipeline delivering GPS tracks reliably.*

---

### v1.7.3 — PDF Report

A standalone workflow for generating a formatted health report as PDF — separate from the Create Reports pipeline. Triggered via a dedicated **PDF Report** button in the Outputs section of the GUI (not via the Create Reports dialog, to avoid collision with Daily Update and the existing report workflow).

**Workflow:**

1. User clicks **PDF Report** — a separate console/dialog opens
2. User selects sections (HRV, Sleep, Activity, ...) and date range
3. App generates `/dashboards/pdf-report/yyyy-mm-dd/report_data.json` and a prompt file with output structure instructions for the LLM
4. Console displays: instructions for the LLM step — user runs their local LLM externally and saves the response as `LLM-Output.md` in the same folder
5. User confirms → app checks whether `LLM-Output.md` exists → renders PDF with or without LLM analysis

**Output folder:** `/dashboards/pdf-report/yyyy-mm-dd/`
- `report_data.json` — section data for LLM input
- `LLM-Output.md` — optional, user-provided LLM response
- `report_yyyy-mm-dd.pdf` — final report

**Page 1:** mandatory disclaimer — no medical product, no diagnosis, no therapy recommendation.

**LLM step is fully optional** — report renders completely without it. No API calls, no cloud dependency, no model lock-in. User chooses their own LLM (Open WebUI, ChatGPT, anything).

---

### v1.8 — Integration Test Suite (Post-FIT)

Full integration test suite against the built EXE using synthetic fixture data.
Four suites parallel to the pipeline structure:

- Health — `garmin_raw` / quality / backup / integrity
- FIT — `fit_raw` / fit_quality / fit_writer
- Context — weather / pollen / brightsky
- Output — dashboard build / export / archive stats

`test_fixture/` — synthetic mini-archive with known quality levels,
intentionally corrupted JSONs, prepared backup ZIPs. Validates that
the pipeline actually runs inside the bundle — not just that files are present.

In the same pass: harden existing test suites — close gaps that have grown
since v1.3.

*Pre-condition: v1.7 FIT Pipeline stable.*

---

### Sync Mode "auto" — Deprecation Candidate

Sync mode `auto` fetches the complete history from `first_day` to yesterday
via the Garmin API. It was the original solution for building a full archive
before Bulk Import existed.

With the current toolset this use case is fully covered:

| Task | Tool |
|---|---|
| Complete history | Bulk Import — faster, no 429 risk |
| Gap repair | Background Timer |
| Daily updates | Daily Sync (v1.4.5) |

`auto` is no longer the recommended path for any standard workflow. It
remains functional but is not actively promoted. Removal or explicit
deprecation notice to be evaluated — not a priority while the mode causes
no active harm.

---

## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**`context_validator.py` — Context Pipeline Validation**

Structural validation of context archive files at read time — analogous to
`garmin_validator.py` for the Garmin pipeline. Would detect missing fields,
wrong types, or corrupt JSON in `context_data/` before `context_map.py`
passes data to dashboard specialists.

Not needed while context data is written exclusively by `context_writer.py`
under full project control. Becomes relevant when additional external sources
(SILAM, other APIs) are added — external API responses are structurally
unpredictable in the same way Garmin API responses are.

Prerequisite: v2.0 multi-source architecture stable.
Natural companion to `context_dataformat.json` (schema definition, analogous
to `garmin_dataformat.json`).

**context_data/ Backup**

`context_data/` (weather, pollen, air quality, Brightsky) has no backup path and no restore workflow. The mirror covers it when configured, but the mirror is optional and manually triggered. Re-fetching from Open-Meteo is possible but not unlimited for historical ranges. Becomes a must-have once external sources with restricted backfill windows are added (v2.0 multi-source). Trigger: any new source that cannot freely re-fetch its history.

---

**Multi-Source Architecture**

Extension to support multiple data sources (Strava, Komoot, ...) alongside Garmin. Full concept in `CONCEPT_V2-0.md`.

**Directory structure:** Each source gets its own isolated folder (`garmin_data/`, `strava_data/`, ...) with its own `raw/`, `summary/`, `log/`. A central `master/master_index.json` serves as a pure routing layer — which sources have data for a given day, and where. No logic, no decisions.

**Architecture principle — plugin modules:** Global actors (`writer`, `normalizer`, `sync`, `security`) remain source-agnostic. Each source provides a `*_master.py` plugin that delivers source-specific details on demand — paths, formats, validation rules, token location. Adding a new source means writing a new plugin and its source-specific actors (`*_api.py`, `*_quality.py`). All global actors work without modification.

**Translation layer:** `field_map.py` is the single point of truth for mapping fields between sources and the common schema. Dashboard and export scripts have no knowledge of source details — they only query `field_map`. Adding a new source means extending `field_map` — all scripts work automatically.

---

**Multiple User accounts**
Currently one account per Windows user. Switching between accounts requires manually changing credentials in Settings. Multi-account support would allow profiles per user.

**External factors & correlations**
Import external data (weather, activity logs, custom notes) and correlate with health metrics. Did poor sleep correlate with high stress? Did training load predict HRV drops?

**Adaptive Baselines**
Extend the Analysis Dashboard beyond fixed 90-day baselines. Rolling windows (7-day, 30-day), seasonal patterns, and load vs. recovery phase detection. The raw data is already there — this is purely an analytical layer on top of `garmin_analysis_html.py`.

**AI health report PDF**
Generate a formatted PDF health summary using the local AI model — personal baseline, flagged days, trends. Fully local, no cloud.

**Route heatmap**
Generate a local heatmap of GPS routes from activity data. No third-party mapping services.

**Windows notifications**
Toast notifications for sync completion, failed days, or significant metric changes.

**Stats dashboard & session log analysis**
Local overview of archive health built from session logs — days synced vs failed over time, which API endpoints fail most often, Garmin API response patterns by time of day. Builds on the Archive Info Panel (v1.3.1) and the quality data in `quality_log.json`. No extra API calls needed.

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected — it just isn't used beyond the summary.

**Test suite & CI/CD**
Core pipeline is covered by five test suites (218 + 134 + 211 + 80 checks + 8 sections for build output). Build integrity is covered by `validate_scripts()` in both build scripts and `test_build_output.py` as post-build gate. Full CI/CD with GitHub Actions for automated builds and release packaging is intentionally deferred — no timeline, no commitment, but the intention is there.

---

## Not planned

> These items are explicitly out of scope for v1.x but may be revisited for v2.0. No timeline, no commitment — but the intention is there.

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- GUI and EXE are Windows-only and will remain so. The collector scripts work on Linux and macOS but are untested and unsupported — use at your own risk.
- Code signing or automatic updates

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*
