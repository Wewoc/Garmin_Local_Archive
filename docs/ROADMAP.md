# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.5.4**

---

## Maintenance

### garmin_api.py — 429/401 Fehlerbehandlung beim Token-Probe

`garmin_api.py` unterscheidet beim Token-Probe aktuell nicht zwischen 429 (Rate Limit) und 401 (Token abgelaufen). Bei einem 429 wird das gültige Token gelöscht und beim nächsten Lauf ein frischer SSO-Login erzwungen — der sofort wieder in den 429 läuft. Fix: 429 bricht ab ohne Token zu löschen. Nur 401 löst Token-Löschung und Re-Login aus.

Aufgedeckt: 2026-05-19 · Abhängigkeit: kein externes Upstream-Update nötig · Priorität: nach Rate-Limit-Abklingen

---

## Planned

---

### v1.5.4 — PyQt6 Migration

**Prerequisite: v1.5.3.1 State Hardening complete.**

Mechanical panel-by-panel translation from tkinter to PyQt6.
`garmin_app_base.py` (assembler) is rewritten last.
No behaviour changes. No new features.

**Scope decision (2026-05-18):** QWebEngineView is explicitly excluded
from this version. Chromium deployment (EXE size, PyInstaller flags,
GPU/ANGLE issues, antivirus false positives) is orthogonal to the
UI migration and would mix three problem classes simultaneously.
The Dashboards tab exists in v1.5.4 as a placeholder only.
QWebEngineView is v1.5.4.1 scope.

**Architecture decisions (locked):**
- Mixin pattern abandoned — each panel becomes a standalone `QWidget` subclass.
  `GarminApp(QMainWindow)` instantiates panels via composition, not inheritance.
  Reason: Qt forbids multiple inheritance from QObject subclasses.
- `self.after()` replaced by `pyqtSignal` — defined at class level only, never
  per instance. Qt queues cross-thread signal emissions automatically.
- Thread model: `threading.Thread` retained. `QThread` not introduced —
  business logic lives in the controller, not in threads.
- Shared state: hybrid — flags stay on the Base, owner-matrix is explicit
  (see below). `AppState(QObject)` deferred to v1.6.
- Dialog guard: `self._dialog_open: bool` on Base — set before `QDialog.exec()`,
  cleared in `finished` signal. Prevents reentrancy from nested event loop.
- Worker rule: workers never read or write widgets. They receive primitive
  copies (str, bool, dict) and emit signals.
- Shutdown: stop_events set in `_on_close()`, threads joined with `timeout=2.0`.

**State owner-matrix:**

| State | Owner | Other panels |
|---|---|---|
| `_ctx_running` | PanelOutputs | read-only |
| `_context_stop_event` | PanelOutputs | `.set()` allowed |
| `_mirror_running` | PanelArchive | read-only |
| `_connection_verified` | PanelConnection | read-only |
| `_timer_active` | PanelTimer | read-only |
| `_timer_stop` | PanelTimer | `.set()` allowed |
| `_timer_generation` | PanelTimer | read-only |
| `_stopped_by_user` | PanelOutputs | read-only |
| `_last_html` | PanelOutputs | read-only |

**What changes:**
- All `app/panel_*.py` — rewritten as `QWidget` subclasses (Signals/Slots)
- `garmin_app_base.py` — rewritten as `QMainWindow` assembler
- `garmin_app.py` / `garmin_app_standalone.py` — entry points updated
- `tests/test_app_logic.py` — migrated to `pytest-qt`, parallel to panel work

**What does not change:**
- `app/garmin_app_settings.py` — untouched
- `app/garmin_app_controller.py` — untouched
- Dashboard pipeline — untouched
- All HTML output files — untouched
- `scheduler/daily_update.py` — untouched, remains headless

**Known risks:**
- Modal dialog reentrancy — mitigated by dialog guard
- `daemon=True` threads during Qt shutdown — `join(timeout=2.0)` in `_on_close()`
  reduces risk; full fix deferred to v1.5.4.1 (with QWebEngine subprocess)

---

### v1.5.4.1 — InApp Dashboards (QWebEngineView)

**Prerequisite: v1.5.4 PyQt6 stable, all three build targets green.**

QWebEngineView integration into the Dashboards placeholder tab.

`QWebEngineView` — a fully embedded Chromium widget that renders Plotly
HTML dashboards natively inside the app. No external browser, no local
server, no pipeline changes required.

- `QComboBox` dropdown + single `QWebEngineView` instance in "Dashboards" tab
- No tab-per-dashboard (avoids Chromium subprocess proliferation)
- Full Plotly interactivity: zoom, hover, filter — all in-app
- v2.0 readiness: multi-source dashboards become a first-class UI element

**Known risks:**
- EXE size +150–300 MB (Chromium embedded)
- PyInstaller requires additional flags: QtWebEngineProcess, codecs,
  locales, resources, sandbox binaries — `build_manifest.py` must be extended
- GPU/ANGLE issues on NVIDIA systems: `--disable-gpu` as opt-in CLI flag
- `load(QUrl)` is async — `QComboBox` disabled during load,
  re-enabled on `loadFinished` signal
- Antivirus false positives on EXE with Chromium subprocess
- Daemon thread + WebEngine subprocess interaction during shutdown —
  requires robust teardown (own scope item within this version)

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
