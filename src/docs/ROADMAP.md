# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.6.4.2**

---

### v1.6.5 — Live Tracking Dashboard

Extends the sync path with a lightweight live fetch for the current day. The result is stored in `garmin_data/live/live.json` and rendered as a standalone dashboard in the Dashboards tab — not part of Create Reports.

**What is new:**

- `garmin_data/live/live.json` — snapshot of the current day: Body Battery intraday series, Heart Rate intraday series, steps, stress + sync timestamp
- `garmin/garmin_live_fetch.py` — lightweight module: fetches today's intraday data via the `garminconnect` API only; no archive write access, no `quality_log` contact
- `dashboards/live_tracking_html_dash.py` — specialist: reads today's live snapshot + last sleep entry **exclusively via `field_map.get()`**, returns a neutral dict. No direct file access — same broker discipline as every other specialist.
- `live_tracking.html` — generated dashboard: upper half shows today's progression (Body Battery, HR, steps, stress); lower half shows last night analogous to the Sleep Dashboard
- `panel_actions.py` — new "Update Live" button in the Life Tracking area (right side); triggers `garmin_live_fetch.py` and re-renders `live_tracking.html`
- `maps/field_map.py` / `garmin/garmin_map.py` — new live read route: `garmin_map` learns the `garmin_data/live/` silo and serves today's snapshot through the standard broker contract (`values` / `fallback` / `source_resolution`). Missing `live.json` → empty result with `fallback=True`, no crash. The exact parameter mechanism (dedicated resolution vs. date-aware intraday routing) is an implementation decision at build time. The specialist reaches live data and the last sleep entry through this route only.

**Triggers:**

- End of "Sync Garmin" → live fetch appended automatically
- "Update Live" button → live fetch only, no archive sync
- "Create Reports" → Live Tracking is **not** included

**What does not change:**

- Archive pipeline — no access to `quality_log`, `raw/`, `summary/`
- Existing dashboards — unaffected
- `garmin_live_fetch.py` — remains a pure fetcher: calls the `garminconnect` API directly and writes only to `garmin_data/live/`. Fetchers sit below the Broker Layer by design — this is the collector pattern, not a broker bypass. The Broker Layer reads what the fetcher wrote; it never fetches.

**Invariant:** `garmin_live_fetch.py` writes exclusively to `garmin_data/live/`. No write access to any other directory.

**Pre-condition:** none — independent of the v1.6 Render Registry; `live_tracking_html_dash.py` can use the existing HTML plotter path.

**Testing — `tests/test_dashboard.py` extension:**

- Broker live route (extends the broker-contract section): the live read path returns the standard contract dict (`values`, `fallback`, `source_resolution`). Missing `live.json` → empty `values`, `fallback=True`, no exception. Unknown field / invalid resolution honour the existing `KeyError` / `ValueError` rules.
- Live Tracking specialist (new section, parallel to the existing specialist sections): `live_tracking_html_dash.build()` runs against a synthetic `live.json` + synthetic last-sleep entry and returns a neutral dict with the documented mandatory keys. Asserts the specialist performs **no direct file access** — all data arrives through `field_map`.
- `test_local_context.py`: live route covered by the same broker-contract assertions applied to `garmin_map` / `field_map`.

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

### v1.9.1 — Export Layer
 
A new output layer parallel to `dashboards/` — reads via the Broker Layer,
writes to external formats and databases. GLA becomes local data infrastructure
for the broader Garmin ecosystem: other tools consume GLA's archive instead of
fetching from the Garmin API themselves, gaining access to intraday data that
would otherwise be lost after ~135 days.
 
**Architecture**
 
The Export Layer sits at the same level as the Dashboard Layer. Both consume
the Broker Layer — neither has knowledge of pipeline internals.
 
```
Broker Layer  (field_map / fit_map / context_map)
        ↓                          ↓
Dashboard Layer              Export Layer
dashboards/                  exports/
layouts/                     export_adapters/
```
 
**Design principles**
 
- One adapter per target format — no shared state between adapters
- Adapters are read-only consumers of the Broker Layer
- No write access to any pipeline component or archive directory
- Sole-Write-Authority of existing pipeline modules is not affected
**Candidate adapter formats**
 
- InfluxDB Line Protocol — enables garmin-grafana and similar tools to consume
  GLA data without fetching from the Garmin API
- CSV — generic export for Python analysis, Excel, or LLM input
- Prometheus exposition format — for monitoring / alerting stacks
No adapter is a commitment. Each is evaluated independently when development begins.
 
**What changes:**
- `exports/` — new top-level directory, parallel to `dashboards/`
- `exports/export_runner.py` — orchestration; analogous to `dash_runner.py`
- `exports/export_adapters/` — one module per target format
**What does not change:**
- Broker Layer — `field_map`, `fit_map`, `context_map` unchanged
- Dashboard Layer — unaffected
- Pipeline — no access below the Broker Layer
- Sole owner principle — adapters read via brokers only

---
 
### v1.10 — Calendar Context (Concept)
 
> **Status: Concept only — no implementation decision made.**
> Visualisation concept confirmed; data source and auth path not yet decided.
> Preliminary research completed — see notes below before reopening.
 
Correlate calendar events with health metrics in dashboards. The core idea:
external schedule data (meetings, travel, events) appears as contextual
annotations alongside Garmin metrics — not as additional health fields,
but as visual markers that make patterns interpretable.
 
**Motivation**
 
An HRV drop or stress spike is more meaningful when a calendar entry confirms
"3-hour meeting block" or "travel day". The data is already there — it just
lives in a different silo.
 
**Visualisation concepts (two modes)**
 
- *Daily dashboards:* event flags per day — marker or hover tooltip showing
  event title/count. Low visual footprint, high informational value.
- *Intraday dashboards:* time spans as overlay bands — e.g. a 14:00–16:00
  meeting block rendered as a shaded region over the Stress or Heart Rate trace.
  Opt-in per chart, not applied globally. Plotly `vrect` handles this natively.
**Candidate sources — research status**
 
- Google Calendar API — **effectively ruled out.** Refresh tokens expire after
  7 days in testing status; weekly manual browser re-auth mandatory. Verified
  status would resolve this but requires hosted privacy policy, formal Google
  review, and ongoing compliance overhead — disproportionate for a hobby project.
  Public repo additionally requires Bring-Your-Own-Key (Client ID/Secret never
  in code).
- Microsoft Graph (Outlook) — same OAuth2 constraints as Google; not separately
  evaluated.
- CalDAV — open standard; works with Nextcloud, Baikal, and other self-hosted
  solutions; often only an app password instead of a full OAuth2 flow.
  **Not yet evaluated — promising.**
- OS-level calendar (Windows) — GLA reads the local calendar database directly;
  the OS handles cloud sync in the background; no outbound network requests from
  GLA. **Not yet evaluated — architecturally clean.**
- Manual `.ics` import — no auth, no cloud dependency; manual export from any
  calendar app. Remains valid as a fallback or first implementation step.
**Open questions (to resolve before any build decision)**
 
- Auth / source path: CalDAV and OS-level calendar not yet technically evaluated.
  One of these must be confirmed as viable before architecture work begins.
- Data model: calendar events are time-span objects with text, not numeric daily
  aggregates. The context plugin pattern (weather, pollen) does not apply directly
  — a separate storage path (`calendar_data/`) and a different map interface
  would be needed.
- Scope boundary: which charts get intraday overlays, and how is that configured?
  Not every intraday chart warrants a calendar layer.
**Pre-condition:** none from a pipeline perspective. Source and auth path decision
required before any architecture work. Not before v1.9.
 
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
- Code signing or automatic updates (see `TODO_HARDENING.md` D1 — decision-gated on commercial scope)
- Generated SBOM + hash-locked dependency lockfile (`TODO_HARDENING.md` D2 — dossier value only, no urgency for a hobby tool)
- Formal documented vulnerability-handling process beyond the existing `SECURITY.md` disclosure channel (`TODO_HARDENING.md` D3)

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*