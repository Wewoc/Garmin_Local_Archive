# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.6.8.2**

---

# v1.6.9 — Review Follow-Up

Basis: Code review sessions 1–6 (Garmin pipeline, GUI code, broker layer,
dashboard layer, context pipeline, test suite), consolidated in
`REVIEW_GESAMTAUSWERTUNG.md` and prioritized in `REVIEW_PRIO_TOP3.md`.

Goal: close the findings with actual data-damage or escalation potential
before v1.7 (FIT pipeline) and v1.7.1 (MCP/SQLite proxy) build on top of the
same code areas. Everything without current data impact moves to
`KNOWN_ISSUES.md` (backlog, checked automatically on file touch — see scope
snapshot extension).

## Block 1 — Critical cluster: sync loop + device_table

Handle together: Block 1a provides the test coverage that would have caught
Block 1b as an active bug.

- **1a — E2E test for the daily sync fetch loop.** `garmin_collector.main()`
  is currently only exercised via the capability-scan branch across the
  entire test suite, never via the regular fetch loop (steps 1–9). Affects
  `test_local.py`.
- **1b — `quality/_stats.py::get_archive_stats()` device_table fix.**
  `device_rank` has been dropped from every entry since the v1.5.7 migration
  in `_io.py`; `_stats.py` still reads `entry.get("device_rank")` and
  therefore returns an empty/incorrect `device_table` for every migrated
  archive. Clarify first whether this function is still actively used or has
  already been superseded by the `device_table.json` approach
  (`_io.py::save_device_table()`) before building the fix.

## Block 2 — QUALITY_LOCK access from panel_archive.py

Pulled forward ahead of v1.7.1 (MCP/SQLite proxy moves closer to
`quality_log.json` — this finding should be resolved beforehand).

- The device-rename function (`_archive_on_device_name_click`) acquires
  `QUALITY_LOCK` directly and calls private facade functions
  (`_load_quality_log()`/`_save_quality_log()`). A third, undocumented
  access path alongside orchestrator-writes and controller-reads. Goal:
  delegate through `garmin_app_controller.py`, consistent with all other
  timer candidate functions.

## Block 3 — One-line cleanup batch

Self-contained pass — low risk, no test impact, can be completed in a single
session with several small anchors.

| # | Finding | File |
|---|---|---|
| 1 | Wrong filename for sleep dashboard embed | `layouts/garmin_mobile_landing.py` |
| 2 | `LOCAL_CONFIG_FILE` defined twice | `garmin_config.py` |
| 3 | `EXCLUDE_DIRS` defined twice | `garmin_mirror.py` |
| 4 | `_exe_dir` assigned twice identically | `app/panel_outputs.py` |
| 5 | Commented-out duplicate above `_FIELD_MAP` | `maps/pollen_map.py` |
| 6 | Redundant `elif` branch (training_readiness) | `garmin/quality/_assess.py` |
| 7 | Dead `vo2_raw` expression | `dashboards/health_garmin_html-json_dash.py` |
| 8 | Unreachable defensive check | `dashboards/dash_runner.py` |

## Not in v1.6.9 — deliberately deferred

All remaining findings from the six review sessions (patterns A–G, remaining
medium/cosmetic individual findings) carry no current data impact and move
to `KNOWN_ISSUES.md`. They will be checked automatically whenever the
respective file(s) are touched in the future, rather than being worked
through as a dedicated build task in v1.6.9.

## Suggested order within v1.6.9

1. Block 1a (test first, so 1b isn't fixed without coverage)
2. Block 1b
3. Block 2
4. Block 3 (independent, can run before/after/in parallel)

Each block follows the normal workflow (Bewerten → Analyse → Bauauftrag,
DEPS scan + scope snapshot before the first Bauauftrag per block).

---

### v1.7 — MCP Server

Exposes GLA data to local LLMs via the Model Context Protocol. Allows natural-language queries against the full archive — health data and context data, FIT activities once the FIT pipeline exists — without manual export or file upload.

**Reordering note (2026-08-16):** Originally planned as v1.9, moved ahead of the FIT Pipeline. `mcp_map.py` and the SQLite Proxy build entirely on infrastructure that already exists (`gateway_map.py`, `quality_log.json`, `context_api.py`/`context_writer.py`) and carry none of the FIT Pipeline's four not-cheaply-reversible gate decisions. Full LLM access to the archive is a large, low-risk value-add on its own — see `docs/KONZEPT_mcp_sqlite_proxy_V2.md` and `NOTES_v1.9-eval_mcp-proxy-reihenfolge.md` for the full evaluation.

**Architecture**

`gateway_map.py` (v1.6.7) already provides the cross-domain routing layer this
feature needs — pass-through queries across `health_map`, `fit_map`, and
`context_map` behind a single entry point. `mcp_map.py` sits on top of
`gateway_map.py` as a thin MCP protocol translator: it no longer aggregates
or routes itself, that responsibility moved to `gateway_map` when it was
built. `mcp_map` accepts structured tool calls from the MCP Server, forwards
them to `gateway_map`, and shapes the response into the MCP tool-call format.
The MCP Server itself has no knowledge of GLA's internal structure —
`mcp_map` owns that translation.

```
MCP Server (external)
    ↓
mcp_map.py  ←→  gateway_map.py  ←→  health_map / fit_map / context_map
    ↓
[Pipeline untouched]
```

**FIT stub:** the FIT Pipeline is not built yet at this point (see v1.8).
`gateway_map.py` already returns a degraded `{"error": ...}` result for
unregistered domains — a `query_fit_activities()` call is therefore safe to
expose now; it simply answers "not available yet" until `fit_map.py` exists.
No FIT-specific code, no FIT skeleton, no config pre-decision happens here —
see `docs/KONZEPT_mcp_sqlite_proxy_V2.md`, section "FIT-Anbindung", for the
reasoning.

**`garmin/mcp_map.py` — new module**

Sole Owner of MCP protocol translation. Accepts structured tool calls from
the MCP Server and forwards them to `gateway_map.get()`. Returns normalized
response dicts. No write access to any pipeline component — read-only by
design, and no routing logic of its own — that lives in `gateway_map`.

**`mcp_server.py` — new module**

Standalone MCP server process. Implements the MCP tool definitions and delegates all data access to `mcp_map`. Can be started independently of the main GUI. Configurable via `local_config` — enabled/disabled, port, LLM backend.

**LLM backend support**

- Ollama (default, recommended) — fully local, no data leaves the machine
- Claude API — optional, user's choice; no default

The backend is a configuration option. GLA takes no position on which LLM the user runs.

**Example tools exposed via MCP**

- `query_day(date)` — full summary for a single day across all active sources
- `query_range(start, end, fields)` — aggregated data for a date range
- `query_fit_activities(start, end)` — FIT activity list with key metrics (returns "not available" until v1.8)
- `get_archive_stats()` — archive health overview (coverage, quality distribution)

**What changes:**
- `garmin/mcp_map.py` — new module; read-only MCP protocol translator on top of `gateway_map`
- `mcp_server.py` — new standalone MCP server process
- `local_config` — two new fields: `MCP_ENABLED` (on/off), `MCP_LLM_BACKEND` (ollama / claude-api)
- `garmin_app_base.py` — optional "Start MCP Server" toggle in Settings panel

**What does not change:**
- Broker Layer internals — `health_map`, `fit_map`, `context_map`, `gateway_map` unchanged
- Pipeline — no access below the Broker Layer
- Sole owner principle — `mcp_map` reads via `gateway_map` only, never directly from archive files or the domain brokers
- All existing workflows — GUI, dashboards, export pipeline unaffected

**Invariant:** `mcp_map.py` has no write access. The MCP Server cannot modify the archive.

---

### v1.7.1 — SQLite Proxy

Aggregation cache in front of `mcp_map.py` — turns range/trend questions
("average sleep last month") from an O(archive size) file-iteration into a
fast local SQL query. Full concept: `docs/KONZEPT_mcp_sqlite_proxy_V2.md`.

**Architecture**

```
LLM (Ollama/Open WebUI/Claude via MCP-Client)
        │
        ▼
  SQLite-Proxy   ← aggregation cache, MCP server/client
        │
        ▼
   mcp_map.py    ← pure protocol translator
        │
        ▼
   gateway_map.py
```

Standalone, upstream tool — not part of the broker chain itself, no new
responsibility for `mcp_map.py`. The proxy is always a derived, reproducible
cache — never written to independently, always rebuildable from the existing
silos. **Invariant: SQLite is always consumer, never source.** Backup and
Mirror do not need to know the SQLite file exists; losing it forces a
full rebuild, not data loss.

**Trigger model:** sync on process start, plus a manually callable sync tool
(`refresh_cache()`, working name) alongside `query_day`/`query_range` — same
delta mechanism, additional caller. Lets a long-running MCP server (e.g. in a
private network via Open WebUI) catch up without a restart. Reads only —
triggers no Garmin API call; a chat-triggered Daily Sync was evaluated and
explicitly rejected (would require a persistent background process and break
the "MCP Server cannot modify the archive" invariant).

**Delta interface:** targeted "what changed since timestamp X" query against
`quality_log.json` via the broker, not a full-file read-and-filter.

**Routing switch — point query vs. aggregation:** the Proxy itself decides,
per request, whether to pass it straight through to `mcp_map.py` (point
query — one day, one field) or answer it from SQLite (aggregation over a
range). The client never sees this — it always talks to the Proxy alone.
Built in from the start, not deferred: without it, every point query (e.g.
the in-app chat asking "how did I sleep today") would take the full SQLite
detour after data was just mirrored there — pure overhead, no speed gain.

**Schema:** simple per-source daily tables (Health, Context; FIT once it
exists), live SQL aggregation (`AVG(...) WHERE date BETWEEN ...`) — no
pre-aggregated weekly/monthly tables. Decided against the archive's real size
(2,797 days total as of 2026-08-16) — live aggregation is effectively
instant at this scale; pre-aggregation would add complexity without
measurable benefit.

**Scope:** Health and Context, not just Garmin — the combination is GLA's
actual value-add over a plain Garmin mirror. Context has no change-log of its
own (`context_api.py` never writes); the proxy mirrors the completeness check
`context_writer.already_written()` already uses internally (file exists for
day X → yes/no), verified against the real code. FIT joins later via the
same `gateway_map` mechanism, no rework needed here.

**Storage location:** `BASE_DIR/sqlite/mcp_cache.db` (working name) —
sibling to `garmin_data/`, `context_data/`, `dashboards/`.

*Pre-condition: v1.7 MCP Server stable.*

---

### v1.7.2 — Ollama Chat Tool-Calling Integration

Connects the existing in-app Ollama chat panel (`app/panel_chat.py`, v1.6.6)
to the Proxy, replacing the current daily-aggregate-only context export.

**Current limitation:** `panel_chat.py` currently reads `health_garmin.json`/
`health_garmin_prompt.md` — daily aggregates only, to avoid blowing the
context window on a stateless `/api/chat` call that resends the full system
message every turn. Intraday resolution (e.g. heart rate history for a
specific night) is missing from the model's context as a result.

**What changes:** instead of a second, larger static export file, the model
queries on demand via the Proxy when the chat history actually requires
intraday detail — the same single entry point external MCP clients (Ollama,
Open WebUI) use. The routing switch (v1.7.1) means most in-app chat queries
are point queries and get answered directly via `mcp_map.py`, with no SQLite
detour — `panel_chat.py` doesn't need to know or care. Requires
`panel_chat.py` to gain a tool/function-calling
interface against Ollama — a real extension beyond the current sync
request/response pattern, not a config change.

*Pre-condition: v1.7 + v1.7.1 stable.*

---

### v1.7.3 — Export Layer
 
A new output layer parallel to `dashboards/` — reads via the Broker Layer,
writes to external formats and databases. GLA becomes local data infrastructure
for the broader Garmin ecosystem: other tools consume GLA's archive instead of
fetching from the Garmin API themselves, gaining access to intraday data that
would otherwise be lost after ~135 days.
 
**Architecture**
 
The Export Layer sits at the same level as the Dashboard Layer. Both consume
the Broker Layer — neither has knowledge of pipeline internals.
 
```
Broker Layer  (health_map / fit_map / context_map)
        ↓                          ↓
Dashboard Layer              Export Layer
dashboards/                  exports/
layouts/                     export_adapters/
```
 
Export adapters are planned to read via `gateway_map.py` rather than
querying individual domain brokers directly (decided in the v1.6.7
`gateway_map` session) — one cross-domain entry point instead of each
adapter importing `health_map`/`fit_map`/`context_map` separately. Not yet
built; noted here for when this layer is implemented.
 
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
- Broker Layer — `health_map`, `fit_map`, `context_map`, `gateway_map` unchanged
- Dashboard Layer — unaffected
- Pipeline — no access below the Broker Layer
- Sole owner principle — adapters read via brokers only

---

## Planned — v1.8

### v1.8 — FIT Pipeline

Standalone plugin pipeline for Garmin activity data (.fit files). The existing
Health pipeline is not modified — the FIT pipeline runs as an independent,
parallel pipeline alongside it. Full concept in `docs/KONZEPT_fit_pipeline_V2.md`.

**Reordering note (2026-08-16):** Originally planned as v1.7, moved behind
MCP Server / SQLite Proxy / Export Layer. Four gate decisions from the FIT
concept (activity ID, orchestrator, config ownership, backup scope) are not
cheaply reversible once made — deliberately not rushed ahead of a
lower-risk, immediately useful MCP/Proxy build. See
`NOTES_v1.9-eval_mcp-proxy-reihenfolge.md`.

**Architecture:**
- `garmin/fit/` — isolated pipeline: `fit_master.py`, `fit_api.py`, `fit_import.py`,
  `fit_parser.py` (stable shell + adapter layer), `fit_normalizer.py`,
  `fit_quality.py`, `fit_writer.py`
- `garmin_data/fit/` — own directory: `raw/` (.fit originals), `summary/` (JSON),
  `tracks/` (GeoJSON, GPS only on demand), `log/`
- `fit_map.py` — peer broker alongside `health_map.py` and `context_map.py`;
  already reachable via `gateway_map.py`'s degraded-domain path since v1.7 —
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

### v1.8.1 — FIT GUI Integration

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

*Pre-condition: v1.8 FIT Pipeline stable.*

---

### v1.8.2 — Context Integration & Location Fallback

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

*Pre-condition: v1.8.1 stable. FIT pipeline delivering GPS tracks reliably.*

---

### v1.8.3 — PDF Report

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

## Planned — v1.9

### v1.9 — Integration Test Suite (Post-FIT)

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

## Planned — v1.10

### v1.10 — Docker / Linux Accessibility (Idea)

> **Status: Idea, unverified — no build order, no architecture decision.**
> Details in `KONZEPT_linux_zugang.md`.

Headless sync (`daily_update.py`, already GUI-free) as a Docker image for
Linux systems (NAS, server, homelab) — complements the Windows EXE, does not
replace it. Write access goes through the existing Mirror feature: `.gla` as
a Docker-owned, protected intermediate container; import into the main
archive stays a manual GUI step with existing downgrade protection. Mirror
password and token encryption key via Docker Secrets instead of Windows
Credential Manager.

Open: whether `garmin_mirror.py` is GUI-free, `.gla` merge behaviour,
behaviour under parallel token access (Windows GUI + container).

---
 
### v1.11 — Calendar Context (Concept)
 
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
required before any architecture work. Not before v1.10.
 
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

**Translation layer:** `health_map.py` is the single point of truth for mapping fields between sources and the common schema. Dashboard and export scripts have no knowledge of source details — they only query `health_map`. Adding a new source means extending `health_map` — all scripts work automatically.

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

**Device-time vs. viewer-time display mode**
v1.6.5.6 chose device-local time (from `startTimestampGMT`/`Local`, archived every day) as the intraday display basis — reisetreu by construction, but it means a day recorded while traveling shows in the device's time zone, not the viewer's current one. A toggle to show viewer-clock time instead (system clock, DST-correct year-round, loses device-time fidelity for travel days) would be a small, independent add-on if it's ever wanted. GPS-derived time zone (from FIT activities) would only close the remaining gap — a travel day that also happens to be a DST transition day — and isn't worth building ahead of the FIT pipeline. Natural anchor point: the travel block already planned for `quality_context.json` (v1.8.2).

**Dashboard header time-basis detail**
v1.6.5.6 added a static, fixed-text note to the header of every dashboard showing intraday timestamps. Showing the *actual* per-day offset instead would need a new key in the broker response contract, threaded through every specialist and plotter — bigger than the fix that prompted it, deliberately deferred.

**Duplicate intraday chart code**
`layouts/render/recovery_context.py` and `layouts/dash_plotter_html_complex.py` carry the same intraday chart block (`_makeIntradaySeries`/`updateIntradayChart`) near-verbatim. Found during the v1.6.5.6 sibling-sweep — an M-2 pattern, not a bug, but a maintenance-cost duplication worth collapsing into one shared source at some point.

**Timestamp-metadata field naming drift**
Several modules stamp "when this record was written" two different ways — some as `datetime.now(timezone.utc)` with a `Z` suffix (`context_writer`, `garmin_security`, `garmin_silo_check`, `garmin_source_writer`, `garmin_live_fetch`), others as naive `datetime.now()` with neither timezone nor suffix (`garmin/quality/_maint.py`, `garmin_collector.py`). Found during v1.6.5.6, unrelated to it — cosmetic, not a correctness issue.

**`garmin_utils.py` deprecation**
`parse_device_date()` uses `datetime.utcfromtimestamp()`, deprecated since Python 3.12. Currently harmless (project targets 3.10+), but worth a one-line swap to `datetime.fromtimestamp(ts, tz=timezone.utc)` before the deprecation becomes a removal.

**Disclaimer shadow-copy in `dash_prompt_templates.py`**
This module holds its own copy of the disclaimer text instead of calling `dash_layout.get_disclaimer()` — a second, un-flagged M-2 pattern found during the v1.6.5.6 sibling-sweep, next to the duplicate intraday chart code above. Same fix shape: collapse to the shared getter.

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
