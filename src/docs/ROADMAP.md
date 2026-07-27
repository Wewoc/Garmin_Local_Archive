# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.6.5.5**

---

## v1.6.5.6 — Intraday Timestamp Timezone Bug

Intraday series timestamps (`heart_rate_series`, `stress_series`, `body_battery_series`,
`spo2_series`, `respiration_series`, `steps_series`) are displayed in GMT/UTC instead
of local time across all consuming dashboards.

**Root cause:** `garmin_map.py` — `_FIELD_MAP` intraday descriptors use
`"ts_key": "startGMT"` for all six series. `_ts_to_iso()` correctly converts the
epoch value to UTC, but the resulting ISO string is passed downstream unchanged —
no reconversion to local time happens anywhere in the chain. Confirmed via user
report: a 9:00 AM CEST activity appeared as 07:00 in the heart rate curve
(UTC+2 offset, matches DE summer time exactly).

**Distinct from:** `garmin_import.py` → `_timestamp_to_date()`, which deliberately
interprets `startTimeLocal` as UTC — that's a date-bucketing trick with no display
impact, unaffected by this bug.

**Affected — confirmed via cross-check, not yet verified in code:**
- Heatmap Dashboard (`heatmap_garmin_html_dash.py`, v1.6.3)
- Sleep Intraday Explorer (`layouts/render/sleep.py`, v1.6.2)
- Custom Dashboard Builder (v1.6.4) — when intraday fields selected
- Live Tracking Dashboard (v1.6.5) — separate path via `garmin_live_fetch.py`,
  needs own check whether it shares `_ts_to_iso()` or has independent logic
- Any Excel export path carrying intraday timestamps

**Fix options (to be evaluated in Analyse step):**
1. Use `startLocal` instead of `startGMT` as `ts_key` — simplest, but depends on
   Garmin reliably supplying `startLocal` for every series (unverified)
2. Keep `startGMT`, add explicit offset correction in `_ts_to_iso()` using
   `zoneinfo` (requires a reference timezone — device-local vs. system-local
   question resurfaces)
3. Fixed manual offset — rejected outright, breaks across DST transitions

**Scope note:** Sibling-Sweep required — single fix point likely in `garmin_map.py`
(`_ts_to_iso()` / `_extract_series()`), but every downstream renderer needs
verification that it doesn't do its own timestamp handling.

**Evaluate while the file is open:** `REFERENCE_GARMIN.md` (respiration_series)
notes a second, parallel structure Garmin ships alongside
`respirationValuesArray` — `wellnessEpochRespirationDataDTOList`, dict-shaped,
marked "not yet evaluated" since v1.6.3.1. Same series, same descriptor, same
file. Decide whether it carries anything the array form doesn't; assessment
only, no implementation implied. If it turns out to matter, it becomes its own
scope — not a rider on the timezone fix.

---

## v1.6.5.7 — T3.1 Silent-Failure Investigation

Two-session arc — Session 1 Analyse, Session 2 Bauauftrag. Not a
single-session fix: the underlying architecture question (can T3.1 run
any pipeline action headless at all, and does `silo_repair` get a
headless-callable core) has to be answered before any implementation —
reversing that order was exactly the mistake v1.6.5.5 deliberately avoided
when P1-07 surfaced this finding.

**Trigger:** concrete, confirmed instance found during v1.6.5.5 (while
tracing P1-07) — `_on_silo_repair()`'s repair path #3 (source without raw)
calls `subprocess.run([sys.executable, str(regen_script), ...])` directly.
In any frozen build, `sys.executable` is the EXE itself, not a Python
interpreter — the call cannot work as written, in T2 or T3.
`garmin_app.py` has `_find_python()` for exactly this reason;
`panel_archive.py` (shared code) doesn't use it. Worse for T3:
`garmin_app_standalone.py` has no subprocess execution model at all —
`_run_module()` uses `importlib` in-process. This is the concrete
mechanism behind the already-noted "`silo_repair` has no headless-callable
core" finding.

**Session 1 — Analyse:**
- Confirm whether T3.1 (`--onedir` GUI) can run any pipeline action
  headless at all — currently open, blocking.
- Three-net test concept: Netz 1 (module loadability), Netz 2
  (fixture-based headless functional tests), Netz 3 (error audibility for
  high-risk write paths — `silo_repair` is the concrete case).
- Review `test_build_output.py` before designing Netz 1 — avoid duplicate
  maintenance with existing build-output checks.
- Netz 2 overlaps v1.8 (Integration Test Suite) by design — decide the cut
  here, before either is built: Netz 2 covers the Health path only and v1.8
  extends it to FIT/Context/Output, or Netz 2 stays diagnostic and v1.8
  owns the fixtures. Deciding this after the fact is the hidden-import
  duplicate-maintenance problem again, with test suites.
- `os.environ` mutation in worker threads (finding F5, v1.5.6.3 — an
  analysis session was required and never happened). 13 mutation sites,
  several inside `worker()` functions (`panel_outputs.py`) and the timer
  thread (`panel_timer.py`). In T1/T2 each script runs as a subprocess with
  its own environment snapshot, so a race stays harmless; T3's
  `_run_module()` loads via `importlib` **in-process**, where every thread
  shares one `os.environ` — and `garmin_config` reads it at import time.
  Same silent-in-T3-only family as the `sys.executable` finding, which is
  why it belongs in this session rather than its own.
- P3-03 verification (standalone-parity audit, still the only open finding):
  open the Dashboard tab and the XLSX preview in the T3.1 build that this
  session produces anyway. `NOTES_v1653.md` records that QtWebEngine showed
  no empty view during the v1.6.5.3 T3 run, but that was an observation in
  passing, not a targeted test of both views. If both render, close the
  finding; if not, `--collect-all PyQt6` or a targeted collect is the next
  step.
- Output of Session 1 is an architecture decision (real headless-callable
  core for `silo_repair`, vs. GUI-T2-only with an explicit, visible T3
  limitation) — not code.

**Session 2 — Bauauftrag:**
- Implements whatever Session 1 decided, plus the three-net tests
  themselves.
- No fix without the Session 1 decision in hand.

**Explicitly not assumed:** that the fix is "swap `sys.executable` for
`_find_python()`". That only helps T2. Session 1 decides the real scope.

**Carried along in Session 2** — small items in files this session opens
anyway. None of them justifies opening a file on its own; all three have been
sitting in NOTES without a home:

- `app/panel_archive.py` — remove `_clean_archive()` (line 303). Dead code,
  no caller project-wide, noted as removable since v1.5.6. Same class as
  P1-03 (`_find_script()`), removed in v1.6.5.3 for the same reason: a set
  trap for whoever wires it up later. `_on_silo_repair()` is in this file.
- `compiler/build_manifest.py` — add the missing `layouts/render/heatmap.py`
  entry to `SCRIPT_SIGNATURES_BASE`. The other four render modules
  (`recovery_context`, `sleep`, `explorer`, `live`) have one; `heatmap` does
  not, and unlike `garmin_extended_anaysis.py` there is no explicit
  exclusion comment. Found in the v1.6.5 sibling sweep, never pulled through.
- `scheduler/daily_update.py` — adopt `crash_handler.install()`.
  `MAINTENANCE_GLOBAL.md` records this as deliberately deferred ("can be
  adopted there in a future step; separate scope") and it has had no home
  since. `install()` is entry-point-agnostic; headless is exactly the target
  where an uncaught crash is least visible.

---

## v1.6.5.8 — Headless Login Hardening

`skip_strategies` / retry-lock on the login cascade. Considered during the
v1.6.5.2 token-lifecycle analysis and deliberately deferred there (see
`ANALYSE_headless_mfa_login_2026-07-08.md` §6, CHANGELOG v1.6.5.2) — the
token-event logging shipped first, on purpose, so that the cascade's actual
behaviour could be observed before changing it. That logging has been in place
since; the deferral has not been revisited.

Related but distinct, already noted in the v1.6.5.2 audit: headless login has
no `_connection_verified` gate. Both concern the same cascade — scope them
together in the Analyse step, decide separately.

Own entry rather than a rider: this touches the login path, which is not
something that happens in passing.

---

## v1.6.5.9 — Auto-size Rollout

Auto-size is implemented for the Health specialist only (v1.4.6). The other
specialists were deferred to "a separate session" because the implementation
is not identical across them — which is precisely why it never became a
by-product of another change.

Not urgent, never harmful. Scope: work out which specialists need which
variant, then apply per specialist rather than as one sweeping change.

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

**Scope boundary vs. v1.6.5.7:** Netz 2 (fixture-based headless functional
tests) covers the same ground. The cut is decided in v1.6.5.7 Session 1,
before either is built — see there.

**Chaos tests** — noted in v1.3.4 as a known gap, earmarked for v1.5, never
built. The corrupted-JSON case above covers part of it; disk full and a
corrupt keyring do not appear anywhere in the current suites. Both are
failure modes where a local-first archiving tool must not lose data silently.

**Specialist tests for `explorer_garmin-context_html_dash`** — deferred in
v1.4.7.1 with a roadmap note in `MAINTENANCE_DASHBOARD.md` that is no longer
findable there. Pulled in here rather than left orphaned; drop it in this pass
if it is no longer wanted.

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
- Removing the Sync Garmin / Sync Context / Create Reports buttons — discussed and analysed twice (v1.6.0), decided against: the Stop button for both sync paths hangs off the same widgets, so removal would take Stop functionality with it, and the CSV button belongs to the Context section thematically. Low benefit, real risk of silent side effects. Recorded here as a decision taken, not as a pending item — it sat on a parking list without a target version and was never one.

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*