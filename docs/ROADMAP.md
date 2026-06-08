# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.5.7.2**

---

## Planned

---

### v1.5.8 — In-App File Viewer

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

### v1.6 Step 1c — Home Tab & Daily Workflow Refactor

The app UI is restructured around actual usage behaviour instead of internal
module layout. Today every panel — settings, status, actions, log — sits on a
single plane with no hierarchy between "configure once" and "use daily". The
top-level container becomes a three-tab layout (currently tabs exist only on the
right side of a split layout).

**Tab 1 — Home (daily use):**
- Archive status panel: days archived, last sync, quality breakdown, integrity,
  failed days, background-timer status
- Three action buttons: Daily Sync, Backup, Timer Start/Stop
- Dashboard view (QWebEngineView + dropdown) — no tab switch required;
  Yesterday Overview specialist loaded as default on startup
- Collapsible activity log — auto-expands during sync

**Tab 2 — Settings (one-time configuration):**
- All existing panels: PanelSettings, PanelTimer (full config with interval
  fields), PanelConnection, PanelArchive
- Individual action buttons (Garmin Sync, Context Sync, Create All) retained for
  power-user and special-case access

**Tab 3 — Files:** unchanged (v1.5.7).

**`app/panel_home.py` — new module**

Owns the archive-status labels and the three Tab-1 action buttons. The status
figures come from `garmin_quality.get_archive_stats()` — already a side-effect-free
dict, so nothing is recomputed, only relocated. `_refresh_archive_info()` keeps its
side-effect contract; only the target label widgets move from PanelConnection to
this module. All four existing callers of `_refresh_archive_info()` remain unchanged.

**Daily Sync button**

Orchestrates gap detection → Garmin Sync → Context Sync → Create All in a single
sequential action. Reuses `_detect_gap()` (extracted to a shared module so the GUI
does not depend on the headless `daily_update.py` entry point) for the range, and
the Background Timer's `env_overrides` pattern for execution — `daily_update.main()`
itself is never invoked. Only missing days are fetched, regardless of the sync mode
configured in Settings. Not user-configurable by design. Disabled while running.

**Backup button**

Always clickable. With a mirror folder configured it runs the mirror operation;
without one it switches to Tab 2 and highlights the Mirror-folder field. No disabled
state.

**What changes:**
- `app/panel_home.py` — new module: archive-status labels + Daily Sync / Backup /
  Timer buttons + collapsible log + dashboard view container
- `garmin/garmin_sync.py` — `_detect_gap()` extracted here from `daily_update.py`;
  both import from the shared location
- `garmin_app_base.py` — top-level layout inverted: QTabWidget becomes root
  (Home / Settings / Files). Existing panels migrated into Tab 2. Archive-status
  labels removed from PanelConnection (relocated to PanelHome)
- `app/panel_connection.py` — archive-status labels removed; connection indicators
  and Restore button placement resolved per layout decision
- `app/panel_outputs.py` — Daily Sync orchestration wired (gap range + env_overrides
  chain); existing individual sync paths unchanged
- `garmin_app_screenshot.py` — demo-value injection retargeted to the new PanelHome
  labels; layout override aligned with the new tab structure
- `compiler/build_manifest.py` — `app/panel_home.py` added to `SHARED_SCRIPTS` +
  `SCRIPT_SIGNATURES_BASE`
- `tests/test_qt_app.py` — new `TestPanelHome` class; PanelConnection tests adjusted
  for relocated widgets
- `docs/MAINTENANCE_GLOBAL.md` — `test_qt_app.py` class list + check count updated
- `specialists/yesterday_overview.py` — new specialist: yesterday's key metrics
  (steps, resting HR, Body Battery, sleep) vs. 30-day average + count of high-quality
  days no longer retrievable at full resolution from Garmin servers. Registered via
  the standard dropdown; preselected on startup. Data sources: `summary/*.json` +
  `quality_log.json` — no API calls.

**What does not change:**
- The four callers of `_refresh_archive_info()` — interface and call sites identical
- `garmin_quality.get_archive_stats()` — already returns a pure dict, unchanged
- Pipeline logic, dashboard specialists, plotters — untouched
- Threading model — `threading.Thread` + `_dispatch()` retained (D-3); no asyncio,
  no QThread
- Cross-panel communication — stays on the existing `_app._panel_x.method()` pattern;
  no SignalBus in this step
- `daily_update.py` workflow for Task Scheduler — unaffected by `_detect_gap()`
  extraction (it imports from the shared location)

**Pre-condition:** none — this is the UI groundwork that precedes the Render Registry
(Step 2). Building the registry over the restructured UI avoids touching the same
panels twice.

**Open decisions (to confirm before build):**
- Gap > 7 days in the GUI path: dialog (use Bulk Import) vs. full-range sync
- Connection indicators (token/login/api/data): Tab 1 status bar vs. Tab 2
- Restore button: Tab 1 vs. Tab 2 (with connection logic)

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

### v1.9 — MCP Server

Exposes GLA data to local LLMs via the Model Context Protocol. Allows natural-language queries against the full archive — health data, FIT activities, and context data — without manual export or file upload.

**Architecture**

A new `mcp_map.py` module sits alongside the existing brokers in the Broker Layer as a dedicated MCP entry point. It receives queries from the MCP Server and distributes them across the full Broker Layer (`field_map`, `fit_map`, `context_map`). The MCP Server itself has no knowledge of GLA's internal structure — `mcp_map` owns that translation.

```
MCP Server (external)
    ↓
mcp_map.py  ←→  Broker Layer (field_map / fit_map / context_map)
    ↓
[Pipeline untouched]
```

**`garmin/mcp_map.py` — new module**

Sole Owner of MCP query translation. Accepts structured tool calls from the MCP Server and routes them to the appropriate broker. Returns normalized response dicts. No write access to any pipeline component — read-only by design.

**`mcp_server.py` — new module**

Standalone MCP server process. Implements the MCP tool definitions and delegates all data access to `mcp_map`. Can be started independently of the main GUI. Configurable via `local_config` — enabled/disabled, port, LLM backend.

**LLM backend support**

- Ollama (default, recommended) — fully local, no data leaves the machine
- Claude API — optional, user's choice; no default

The backend is a configuration option. GLA takes no position on which LLM the user runs.

**Example tools exposed via MCP**

- `query_day(date)` — full summary for a single day across all active sources
- `query_range(start, end, fields)` — aggregated data for a date range
- `query_fit_activities(start, end)` — FIT activity list with key metrics
- `get_archive_stats()` — archive health overview (coverage, quality distribution)

**What changes:**
- `garmin/mcp_map.py` — new module; read-only broker aggregator
- `mcp_server.py` — new standalone MCP server process
- `local_config` — two new fields: `MCP_ENABLED` (on/off), `MCP_LLM_BACKEND` (ollama / claude-api)
- `garmin_app_base.py` — optional "Start MCP Server" toggle in Settings panel

**What does not change:**
- Broker Layer internals — `field_map`, `fit_map`, `context_map` unchanged
- Pipeline — no access below the Broker Layer
- Sole owner principle — `mcp_map` reads via brokers only, never directly from archive files
- All existing workflows — GUI, dashboards, export pipeline unaffected

**Invariant:** `mcp_map.py` has no write access. The MCP Server cannot modify the archive.

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