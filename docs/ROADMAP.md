# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.5.2**

---

## Planned

---

### v1.5.3 — UI Panel Decomposition

**Prerequisite: v1.5.2 GUI / Controller Separation complete.**

`garmin_app_base.py` remains in tkinter but is broken into dedicated
panel modules. The monolith becomes an assembler.
Pure structural move — no behaviour change, no bug fixes.

**New modules (all Mixin classes, no `__init__`):**
- `app/panel_settings.py` — Settings panel (credentials, paths, sync config)
- `app/panel_archive.py` — Archive Info + Integrity panel
- `app/panel_connection.py` — Connection test + indicators panel
- `app/panel_timer.py` — Background timer panel
- `app/panel_outputs.py` — Outputs + Dashboard panel

**What changes:**
- `garmin_app_base.py` — reduced to assembler: imports panels, wires
  them together, holds shared state. Target: under 400 lines.
- `app/` — new panel modules, each owning one UI section

**What does not change:**
- `app/garmin_app_settings.py` — untouched
- `app/garmin_app_controller.py` — untouched
- All three build targets — no behavioural change

**Why before PyQt6:**
Decomposition in tkinter is low-risk — the technology is well-known, tests are underway,
every error is clearly locatable. The subsequent PyQt6 conversion will be a
mechanical panel-by-panel translation with a clear gate after each step.

---

### v1.5.3.1 — State Hardening

**Prerequisite: v1.5.3 Panel Decomposition complete, all tests green.**

Hardening step in preparation for the PyQt6 migration.
Cross-LLM review (Gemini + ChatGPT) confirmed shared mutable state on `self`
as the primary long-term risk for Qt compatibility. This version addresses it
without touching behaviour or scope of v1.5.3.

**Three deliverables:**

1. **State block in `__init__`** — all `self._xyz` flags documented with
   owner panel and thread rule. Makes implicit state explicitly visible.

2. **`_ctx_running` bug fix** — setter added in `_run_context_sync` and
   `_on_context_sync_done`, initialization in `__init__`. Without this,
   Context Sync never blocks the Mirror operation — concurrent archive
   writes are possible.

3. **Widget accessor methods** — for the most critical cross-panel widget
   access. No panel writes directly to a widget owned by another panel.
   Candidates: `_mirror_btn`, `_restore_btn`, `_timer_btn`.

**What does not change:**
- Panel structure from v1.5.3 — untouched
- All three build targets — no behavioural change beyond the bug fix

---

### v1.5.4 — PyQt6 / QWebEngineView

**Prerequisite: v1.5.3.1 State Hardening complete.**

Each panel module is translated from tkinter to PyQt6 individually.
`garmin_app_base.py` (assembler) is rewritten last.

**Target: PyQt6 with QWebEngineView**

`QWebEngineView` — a fully embedded Chromium widget that renders Plotly
HTML dashboards natively inside the app. No external browser, no local
server, no pipeline changes required.

- Dashboards open inline in a dedicated "Dashboards" tab
- `QComboBox` dropdown above one `QWebEngineView` instance —
  no tab-per-dashboard (avoids Chromium subprocess proliferation)
- Full Plotly interactivity: zoom, hover, filter — all in-app
- v2.0 readiness: multi-source dashboards become a first-class UI element

**What changes:**
- All `app/panel_*.py` — rewritten in PyQt6 (Signals/Slots, QThread)
- `garmin_app_base.py` — rewritten as PyQt6 assembler
- `garmin_app.py` / `garmin_app_standalone.py` — entry points updated

**What does not change:**
- `app/garmin_app_settings.py` — untouched
- `app/garmin_app_controller.py` — untouched
- Dashboard pipeline — untouched
- All HTML output files — untouched

**Known risks:**
- QWebEngineView embeds Chromium — EXE size +150–200 MB, RAM significantly
  higher, PyInstaller needs additional flags (QtWebEngineProcess, codecs,
  locales, resources, sandbox binaries)
- GPU fallback required on NVIDIA systems:
  `os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")`
- `load(QUrl)` is async — QComboBox must be disabled during load,
  re-enabled on `loadFinished` signal

**Alternative: CustomTkinter**
If embedded dashboards are not a priority, CustomTkinter remains a valid
fallback — modern styling, no paradigm shift, PyInstaller-friendly.
Decision deferred until v1.5.3 is complete.

---

### v1.5.4.1 — UI Testsuite

**Prerequisite: v1.5.4 PyQt6 stable, all three build targets green.**

First dedicated test suite for the UI layer. PyQt6 allows headless
widget testing — `QApplication` starts without a visible window,
widgets are instantiable and inspectable in isolation.

**New:**
- `tests/test_ui.py` — headless QApplication, panel modules
  instantiated individually, controller return values injected,
  widget state verified. No screenshot comparison, no visual
  validation — logic correctness of UI reactions only.

**What gets tested:**
- Each panel initializes without exception
- Panel methods respond correctly to controller return values
  (label text, button enabled state, indicator color)
- Cross-panel wiring: signal in → correct callback triggered

**What does not get tested:**
- Visual rendering, layout, colors
- Screenshot comparison
- Any behaviour that requires a visible window

**Why separate from v1.5.4:**
During the PyQt6 rewrite, behaviour is still being defined.
Writing tests for something not yet stable is backwards.
v1.5.4.1 locks in the behaviour that v1.5.4 established —
analogous to how `test_app_logic.py` covers the app layer.

---

### v1.5.5 — Content Validation

Value range checks implemented in v1.4.3 (`garmin_validator`, `garmin_collector` downgrade logic). Remaining scope: dashboard integration of flagged days, flagged day markers in charts, outlier visualization.

**Archive Integrity Alert (GUI)**

Detection layer already exists: `check_raw_integrity()` in `garmin_backup.py` compares `quality_log` write-entries against actually present raw files; `integrity_warnings` in `garmin_quality.py` catches checksum mismatches with auto-restore. What is missing: a visible warning in the GUI status panel when either check fires. Users currently see nothing — warnings land only in the log.

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
