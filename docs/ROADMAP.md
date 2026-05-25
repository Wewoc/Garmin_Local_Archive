# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.5.4.4**

---

## Planned

---

### v1.5.5 — Content Validation

### v1.5.5 — Content Validation & Backup Hardening

Value range checks implemented in v1.4.3 (`garmin_validator`, `garmin_collector` downgrade logic). Remaining scope: dashboard integration of flagged days, flagged day markers in charts, outlier visualization.

**Archive Integrity Alert (GUI)**

Detection layer already exists: `check_raw_integrity()` in `garmin_backup.py` compares `quality_log` write-entries against actually present raw files; `integrity_warnings` in `garmin_quality.py` catches checksum mismatches with auto-restore. What is missing: a visible warning in the GUI status panel when either check fires. Users currently see nothing — warnings land only in the log.

**Checksum Coverage Extension**

`_compute_checksum()` in `garmin_quality.py` currently covers only `date` and `write` per entry. Extend to include `quality` and `source` — the two fields that drive dashboard rendering and recheck logic. Silent corruption of these fields currently passes the integrity check undetected.

**summary/ Backup**

`garmin_data/summary/` is the only active data stream without a backup path. `garmin_backup.py` covers `raw/` and `quality_log.json`; summary files are not included. While summary files are regenerable from raw via `regenerate_summaries.py`, that is a manual recovery step. Monthly ZIP consolidation analogous to raw backup added to `garmin_backup.py`.

**Mirror Spot-Check**

`garmin_mirror.py` compares by filename and filesize only — content integrity of copied files is not verified. After `run_mirror()`, 5–10 randomly selected files are cross-checked via CRC32 against the source. Result surfaced in the return dict as `spot_check: {sampled: N, mismatches: M}`.

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

*Pre-condition: v1.5.6 stable and in active use.*

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

## Planned — v1.7

- **Garmin FIT Pipeline & Plugin Architecture**
  The existing Garmin Health pipeline is being rebuilt into a plugin model — `garmin_map.py` → `garmin_health_map.py`, new `garmin_fit_map.py` as a second Garmin source (activity data via API + bulk import). `field_map.py` is being extended to become a source-agnostic broker. Goal: both Garmin sources run as equal pipelines side by side.

  *Pre-conditions (resolved before plugin work begins):*
  - `garmin_normalizer.py` — add real transformation layer; current pass-through insufficient once two sources deliver differing raw schemas
  - `run_import()` — narrow QUALITY_LOCK scope; currently held across entire bulk loop including file writes

---

### v1.7.1 — PDF Report

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

*Pre-condition: v1.7 FIT Pipeline stable — Activity data available via `field_map.py` broker before PDF Report is built.*

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

**`quality_context.json` — Context Location State Tracking**

Location-aware state tracking for the context pipeline — analogous to
`quality_log.json` for the Garmin pipeline.

Current problem: `context_writer.already_written()` is a file-existence check
only. If a travel period is entered in `local_config.csv` after the affected
days were already downloaded with home coordinates, the next sync silently
skips those days — wrong weather/pollen data remains without any warning.

Concept:
- `quality_context.json` is the single source of truth for which dates were
  fetched with which coordinates. Home location is the implicit default for
  all dates not explicitly listed.
- Travel entries are written into the JSON from `local_config.csv` on sync.
  Each date in a travel block gets a `true`/`false` flag (fetched / pending).
  After import, the CSV is cleared back to header-only.
- Removing a travel block from the JSON triggers a re-fetch of the affected
  dates with home coordinates (old `/raw/` files deleted first).
- A backup of `quality_context.json` is written before every destructive
  operation. Diff between backup and current JSON determines which dates need
  correction.
- Validation at CSV import time: multiple travel blocks in one CSV → hard
  stop, no import. Overlapping date ranges with existing JSON blocks → hard
  stop, no import.
- Home coordinate changes → Schema 2 migration path (not in scope here).
- Sole write authority: new `context_quality.py` module, symmetric to
  `garmin_quality.py`. `context_collector.py` remains orchestrator and calls
  `context_quality` — it does not write the JSON directly.

---

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
