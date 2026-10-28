# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.7.6.6**

---

### v1.7.6.7 — More export file types and import inventory

- Health status and pulse alert events of the export are read into the bulk
  store.
- Further export families (gear, personal records, courses, zones) are kept
  as originals.
- The import result lists the known and the unknown file types of the export.

### v1.7.6.8 — Source comparison in the import summary

- For the fields both sources deliver, the import reports per field how many
  days are equal, added or contradicting. Nothing is overwritten or stored.

### v1.7.6.9 — Device repair

- Days without a device are completed from the device recorded in the kept
  files (preview and backup first). Devices can be named in the app.

### v1.7.6.10 — Race predictions on their own day

- Race predictions are filed under their own date instead of the day they were
  retrieved; existing days are cleaned up by a step in the app (preview and
  backup first). The history comes from the export.

### v1.7.6.11 — Property tests and fuzzing of the new modules

- The decision rules of the modules added during v1.7.6.x (bulk store, export
  import, backups) are tested with generated inputs instead of hand-picked
  examples: rules from `REFERENCE_INVARIANTS.md` become properties (a day is
  replaced only by a fuller one, API data first in the resolved summary, a
  worse quality label never over a better one).
- The parsers that read foreign bytes (FIT reader, export scanner) are fuzzed
  with mutated valid files; they must end in their declared errors only.
- Each finding gets a fixed regression test; whether the code is changed, the
  behaviour is pinned or the finding is dropped is decided per finding.
  Otherwise tests only, no change in behaviour. New development dependency:
  `hypothesis`.

### v1.7.6.12 — Mutation test of the new modules

- The modules added during v1.7.6.x (bulk store, export import, backups) go
  through the mutation test; changes the tests miss get new tests or are
  documented as equivalent. Tests only, no change in behaviour.

**Release:** Each step gets its own documented release round; the first build
of the download packages was made after v1.7.6.4, a second one follows v1.7.6.10.

**Not part of it:** FIT activities (v1.8); stress as a replacement for the API
value.

---

## Planned — v1.7.7

### v1.7.7 — Export scanner (Idea)

> **Status: Idea, unverified — no build order, no architecture decision.**

Checks the user's own export: which file types it contains, which fields are
filled or only empty per year. The report holds names and numbers, no values.
Possibly its own tab in the app.

---

## Planned — v1.8

### v1.8.0 — FIT Pipeline

Standalone pipeline for Garmin activity data (.fit files). The existing
Health pipeline is not modified — the FIT pipeline runs as an independent,
parallel pipeline alongside it.

**Architecture:**
- `garmin/fit/` — `fit_master.py` (plugin interface, `get_paths()` only),
  `fit_collector.py` (orchestrator, same shape as `garmin_collector.py`:
  `main()` for sync, `run_import()` for import), `fit_api.py`,
  `fit_import.py`, `fit_parser.py` (stable shell, one adapter: the project's own reader),
  `fit_normalizer.py`, `fit_quality.py`, `fit_writer.py`
- `garmin_data/fit/` — `source/` (.fit originals, unchanged, plus Garmin's
  activity metadata as `…connect.json`; GPX/TCX from the export stored
  unparsed in `source/other/`), `summary/` (one JSON per activity), `log/`.
  No `raw/`, no `tracks/` — both are generated from `source/` on demand.
- File name `YYYY-MM-DD_<fit_id>`: UTC start date plus an ID derived from
  the file itself (`manufacturer-serial-time_created`, fallbacks if the
  serial is missing) — identical for import and sync. Queries use
  `local_date` from the summary (activity offset → Garmin's
  `startTimeLocal` → configured time zone).
- Paths and ENV constants in `garmin_config.py`; `fit_master.get_paths()`
  passes them through.
- `fit_map.py` — peer broker alongside `health_map.py` and `context_map.py`,
  `garmin_fit_map.py` beneath it. Two query shapes: activity list and daily
  aggregate. Replaces `None` in `gateway_map._DOMAIN_BROKERS["fit"]`.
- Two entry points, both through `fit_collector`: Import (folder or GDPR
  export ZIP; history) and Sync (Garmin Connect API; new activities only,
  matched against the archive by start time). No background-timer mode.
- Import keeps only activity files (`file_id.type`); other FIT types in the
  export (monitoring, sleep, HRV) are out of scope here, see v1.7.6.

**Quality model:** matrix per activity — `file_integrity`, `session`, `gps`,
`fields`, `duplicate`, plus provenance (`origin`, `original`, `id_rule`,
`tz_source`, `meta_origin`). An existing `source/` file is never
overwritten. No merge candidates or extreme-event flags in v1.8.0.

**Not in v1.8.0:** backup, mirror and silo check for `garmin_data/fit/` —
see v1.8.5. Activities without an original file (manual entries) are only
logged.

**Build order:** .0.0 skeleton + offline import spine · .0.1 quality matrix
+ fixtures · .0.2 sync · .0.3 broker.

**Documentation and tests:** `docs/MAINTENANCE_FIT.md`,
`docs/REFERENCE_FIT.md` and `tests/test_fit.py` created with the first
module and maintained in every session that touches FIT modules. No new
dependency; new modules go into
`compiler/build_manifest.py`'s `SHARED_SCRIPTS` as they are created.

*Pre-condition: none.*

---

### v1.8.1 — FIT GUI Integration

Import and Sync control elements for the FIT pipeline added to `panel_outputs.py`.
Steuerungslogik only — no activity view, no dashboards, no map display.
Those follow once the pipeline is proven.

**What changes:**
- `app/panel_outputs.py` — FIT Import button (Bulk), FIT Sync button;
  same subprocess pattern, same log window as Health pipeline
- `REFERENCE_GLOBAL.md` — two new ENV variables:
  `GARMIN_FIT_IMPORT_PATH` (Bulk Import source folder),
  `GARMIN_FIT_SYNC_ENABLED` (FIT Sync on/off, separate from Health Sync)
  FIT sync runs together with the daily Health sync; the import folder is
  chosen per run via dialog, like the Health bulk import.

**What does not change:**
- Health pipeline controls — unchanged
- `garmin_security.py` — existing token reused, no second auth path
- `scheduler/daily_update.py` — FIT Sync path must be fully headless;
  no GUI dependency allowed

*Pre-condition: v1.8.0 FIT Pipeline stable.*

---

### v1.8.2 — Context Integration & Location Fallback

Location-aware context collection extended with GPS data from FIT activities
and a formal state tracking layer (`quality_context.json`).

**Fallback chain (coordinates per day):**
1. GPS start point from the activity summary (only when the activity has GPS
   and its bounding box is < 50 km). Several GPS activities on one day: the
   longest one counts; start points more than 50 km apart → step 2 instead.
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

*Pre-condition: v1.8.1 stable. FIT summaries delivering GPS start points and
bounding boxes reliably.*

---

### v1.8.3 — FIT MCP Integration

Wires FIT data into the MCP SQLite proxy and hardens MCP field resolution
for the FIT domain — two distinct pieces of work, not one.

**1. Sync plumbing (small)**
FIT gets its own cache file `BASE_DIR/sqlite/fit_cache.db` with its own
module next to `mcp_sql.py`: activity rows keyed by `fit_id`, plus a daily
aggregate. Same consumer invariant as `mcp_cache.db` — rebuildable from the
archive at any time. The placeholder `mcp_fit_days` and the `fit` column of
`mcp_day_status` in `mcp_cache.db` stay unused and are documented as
superseded. Cross-domain queries use SQLite `ATTACH`.
`query_fit_activities` gets the list shape; its current field signature
becomes the daily-aggregate form.

**2. MCP field-resolution hardening for FIT (large, empirical)**
Health and Context each went through their own multi-session hardening
cycle (`mcp_field_registry.py`'s `HEALTH_FIELD_ALIASES`/`_AMBIGUOUS` and
`CONTEXT_FIELD_ALIASES`/`_AMBIGUOUS`, plus dedicated resolver modules
`mcp_health.py`/`mcp_context.py`) — every alias entry and difflib cutoff
value came from real multi-model test runs against `mcp_test/`, not from
analysis alone. FIT needs the same treatment from scratch: a new
`mcp_fit.py` resolver mirroring the existing two, its own
`FIT_FIELD_ALIASES`/`FIT_FIELD_AMBIGUOUS` tables, and a new `mcp_test/`
question catalog run against multiple Ollama models to find silent
field-name mis-resolutions (pace vs. speed, distance vs. elevation gain,
sport-specific fields, etc.) before the cutoff/alias tables can be trusted.

*Pre-condition: v1.8.0 FIT Pipeline stable, v1.8.2 Context Integration in
place — FIT data needs to actually exist and be trustworthy before its MCP
exposure is worth hardening.*

---

### v1.8.4 — PDF Report

A standalone workflow for generating a formatted health report as PDF — separate from the Create Reports pipeline. Triggered via a dedicated **PDF Report** button in the Outputs section of the GUI (not via the Create Reports dialog, to avoid collision with Daily Update and the existing report workflow).

**Workflow (updated — LLM step now goes through the in-app pipeline, not manual copy-paste):**

1. User clicks **PDF Report** — a separate console/dialog opens
2. User selects sections (HRV, Sleep, Activity, ...) and date range
3. App generates `/dashboards/pdf-report/yyyy-mm-dd/report_data.json` and a prompt file with output structure instructions for the LLM
4. **Default:** app calls the local LLM directly through the existing MCP/Ollama pipeline (`ollama_client.py`/`mcp_tool_chat.py`, the same one `panel_chat.py` uses — hardened for health/context since v1.7.2, extended to FIT by v1.8.3) and writes `LLM-Output.md` itself, no manual step.
   **Fallback:** manual path stays available for anyone who wants a different/cloud LLM (Open WebUI, ChatGPT, anything) — same "drop `LLM-Output.md` into the folder yourself" flow as before, still needed for any model outside the local Ollama setup.
5. App checks whether `LLM-Output.md` exists → renders PDF with or without LLM analysis

**Output folder:** `/dashboards/pdf-report/yyyy-mm-dd/`
- `report_data.json` — section data for LLM input
- `LLM-Output.md` — LLM response, either auto-generated (default path) or user-provided (fallback path); still optional either way
- `report_yyyy-mm-dd.pdf` — final report

**Page 1:** mandatory disclaimer — no medical product, no diagnosis, no therapy recommendation.

**LLM step is fully optional** — report renders completely without it. No cloud dependency, no model lock-in on the default path (local Ollama only); the manual fallback path is what opens the door to cloud models, by the user's own explicit choice.

*Pre-condition: v1.8.3 FIT MCP Integration in place — the automatic LLM
step reuses that hardened field resolution, so report sections drawing on
FIT data should not go live before FIT itself is reliable through MCP.*

---

### v1.8.5 — FIT archive protection (mandatory)

Adds `garmin_data/fit/` to backup, mirror and silo check.

- Backup, mirror and silo check read their paths from the plugin interface
  (`fit_master.get_paths()` with path classes: must back up / rebuildable /
  state), never from a FIT special case.
- `garmin/health_master.py` as a pure adapter returning the existing
  `garmin_config` paths — no rename, no move of Health modules.
- Mirror container: new section for FIT (or a generic mapping via the path
  classes) in `garmin_container._classify_file()`; `garmin_import_mirror.py`
  restores it and keeps reading older containers without it.
- Plugin registry as a static list in code (listed in `build_manifest.py`).
- Decided before building: whether a plugin is a source (Garmin) or a
  source × domain (Garmin Health, Garmin FIT).

*Pre-condition: v1.8.0 stable.*

---

## Planned — v1.9

### v1.9 — Integration Test Suite (Post-FIT)

Full integration test suite against the built EXE using synthetic fixture data.
Four suites parallel to the pipeline structure:

- Health — `garmin_raw` / quality / backup / integrity
- FIT — `fit_source` / fit_quality / fit_writer
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

**Open mHealth / IEEE 1752.1 export format**

Researched during v1.7.4 (see
`changelog/anchor_delivery_exportlayer19-open-mhealth-recherche.md`).
Most of GLA's actual metrics (HRV, Stress series, Body Battery, Sleep
Score/Qualifier/Feedback, Intensity Minutes) have no schema in either
standard — a mapped export would be largely incomplete, and no
concrete consuming tool exists yet. Revisit if one appears, or once
IEEE P1752.2 (in progress) is published.

**Parquet export adapter**

Deferred after JSON/CSV/InfluxDB shipped in v1.7.4 — its main advantage
(compression, columnar, faster large-table reads) only pays off at
archive sizes CSV can't handle, and no consuming tool needs it the way
InfluxDB does. Revisit with a real need, via its own interface analysis.

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

**Dashboards on `gateway_map`:** dashboards currently import `health_map`/`fit_map`/`context_map` directly — a deliberate v1.6.7 decision (see `gateway_map.py`'s own docstring) to keep them coupled only to what they actually use. Revisit once a second source (e.g. Strava) actually exists: bundling all domains behind `gateway_map` then avoids re-wiring every dashboard specialist for each new source. Not worth the extra indirection before that point — confirmed in the v1.7.2.2 planning session (2026-09-19).

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

The same function treats the text `"0"` and the number `0` differently:
`parse_device_date("0")` returns `1970-01-01`, `parse_device_date(0)` returns
`None` (pinned by tests since v1.7.4.0.3). Probably both should be `None`; decide
when the function is touched for the deprecation anyway.

**Credential masking — password inside the e-mail address**
`garmin_redact.redact()` replaces the password first and the e-mail address
second. If the password is a substring of the e-mail address (for example
password `geheim`, address `geheim@example.org`), the address is no longer found as
a whole and the rest of it (`@example.org`) stays readable in the log. Pinned by tests since
v1.7.4.0.3. A one-line fix: replace the longer value first (e-mail, then
password).

**Disclaimer shadow-copy in `dash_prompt_templates.py`**
This module holds its own copy of the disclaimer text instead of calling `dash_layout.get_disclaimer()` — a second, un-flagged M-2 pattern found during the v1.6.5.6 sibling-sweep, next to the duplicate intraday chart code above. Same fix shape: collapse to the shared getter.

**`resolve_health_field()` / `resolve_context_field()` — move onto the shared `_match_field()`**
Since v1.7.5.4 the near-match step (`difflib`, cutoff 0.65, auto-resolve on
exactly one hit, otherwise error + `did_you_mean`) exists once in
`clients/mcp_query_common.py::_match_field()`, used by `query_raw`. The tails
of `resolve_health_field()` (`mcp_health.py`) and `resolve_context_field()`
(`mcp_context.py`) are still near-verbatim copies of it — an M-2 pattern, not
a bug. The helper is pinned to the health resolver's behaviour by parity
tests, so the swap is small and low-risk; do it when those files are touched
anyway, or fold it into the v1.8.3 FIT resolver (`mcp_fit.py`), which would
otherwise become a fourth copy.

**Raw-field pointers — the two remaining directions**
Since v1.7.5.5 `query_health` answers an exact raw-passthrough field name with
a pointer to `query_raw`, and `query_raw` answers the three paired fields with
a hint naming the processed counterpart (`RAW_FIELD_COUNTERPARTS` in
`clients/mcp_field_registry.py`). Not covered yet: a misspelled raw name at
`query_health` (`floor`, `daily_weigh_in`) is still the generic `unknown field`
— a check against the raw names would close it, natural to do together with the
resolver move above — and a processed name at `query_raw` (`floors_climbed`,
`body_weight`) returns `unknown field` without a pointer to `query_health`, which
the counterpart table could answer in reverse. `intensity_min_moderate` is
resolved to `intensity_minutes_data` there by the near-match step.

**`clients/mcp_server_gui.py` color-theme parity**
v1.7.0.2 added a GLA-branded text header (`"🦄  GARMIN LOCAL ARCHIVE"`) but deliberately stopped there — the window still runs Tkinter's native "vista" theme, which mostly ignores custom widget colors for `ttk` controls (Checkbutton, Entry, Button). Real color parity with the PyQt6 app's dark/purple palette would need `ttk.Style().theme_use("clam")` first, which also changes the whole widget look away from native Windows rendering — a bigger, separate change, deferred by choice ("just the unicorn" this session).

**MCP server window/taskbar icon**
No icon asset exists anywhere in this codebase yet — the titlebar "feather" seen on `clients/mcp_server_gui.py`'s window is Tkinter's own stock default, not a GLA icon gone missing. A real icon would need an asset created (or sourced under a free license, e.g. Twemoji/OpenMoji), wired in via `root.iconphoto()`, and — for the standalone build — a `build_manifest.py`/PyInstaller bundling entry so `mcp_server.exe` ships it too.

**`repair_silos()` Kategorie 7 — `date: null` in the written summary**

Found by an independent GLA-Netz-2 diagnostic run (2026-10-06), not by the
project's own test suite — not yet pinned by a test. When `repair_silos()`
rebuilds a missing `summary/` file from an existing `raw/` file whose
content has no `date` key, the written summary file's *content* carries
`"date": null` — the filename itself is still correct (it comes from
`check_silos()`, not from the content). Root cause: `summarize()`
(`garmin_normalizer.py`) takes the date from the content dict unchanged
(`raw.get("date")`), and `repair_silos()`'s Kategorie-7 branch
(`garmin_silo_repair.py`) passes `raw` through unmodified. The repair
itself still succeeds; only matters if a downstream consumer reads the
`date` field from inside the summary file instead of from its filename.

**Monthly backup ZIPs written through a temporary file**

Appending to a monthly backup ZIP would write a new ZIP next to the old one
and swap it in, as the replace of an entry already does, so that an interrupted
run never leaves a half-written ZIP.

**Backup problems visible in the app**

A damaged monthly backup ZIP and the error count of the backup refresh would
show as a warning of the sync and in the archive check instead of only in the
log; a damaged monthly ZIP could be rebuilt from the daily files by a step in
the app.

**Activities from the export in the daily summary**

The activities of the Garmin export would reach `summary/` with duration and
distance in the right units. Until then the daily summary of a day that comes
from the export holds no activities.

**Days of the earlier import without a Garmin original in the migration**

Days that only hold the earlier import form, without the archived Garmin
original, would be turned into days of the export by a step in the app
(preview and backup first). Until then they are reported by the migration and
stay as they are.

**Remove the bulk upgrade mechanism**

The two background timer modes for days of the export (bulk recheck and bulk
field backfill) and the matching steps of the sync would be removed once no
archive depends on them any more.

**Same days in the schema check and in the schema migration**

The check that offers the schema migration (popup, daily update) and the
migration itself would work on the same days. Today the check counts every
summary file with an outdated schema, the migration only the days of the
quality log.

**Damaged summary files**

A summary file that cannot be read would be found by the archive check and
made again from the raw file or the export data by a step in the app. Today
the schema migration skips it and it stays as it is.

**Training load in the daily summary**

The field `training_load_7d` of the daily summary would be filled from the
training load values of Garmin's answer. Until then it stays empty.

**Text fields in the dropdowns of the dashboards**

The older text fields (`hrv_status`, `hrv_feedback`, `bp_category`,
`readiness_level`, `readiness_feedback`, `training_status`) would be left out
of the daily dropdowns of the Explorer and the Custom Dashboard, like the
sleep score texts and the new alert texts.

**Pictures in the documentation viewer**

The repository README, with its screenshots, would open in the documentation
viewer of the app. The pictures would be shipped with the app or loaded from
GitHub when a network is there.

**MCP transport_security — `allowed_origins` extension**
v1.7.0.2's Docker-reachability fix (`MCP_EXTRA_ALLOWED_HOSTS`) deliberately left `allowed_origins` at the SDK's own three defaults — a server-to-server HTTP client typically sends no `Origin` header at all, and the SDK's own validator passes automatically when it's absent. Revisit only if a real `Invalid Origin header` rejection shows up in the log for some other MCP client.

---

## Not planned

> These items are explicitly out of scope for v1.x but may be revisited for v2.0. No timeline, no commitment — but the intention is there.

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- GUI and EXE are Windows-only and will remain so. The collector scripts work on Linux and macOS but are untested and unsupported — use at your own risk.
- Code signing of the EXEs. The EXEs are unsigned, so Windows SmartScreen may warn on first run (see `README_APP.md`); `updater_helper.ps1` strips Mark-of-the-Web after extraction as a partial mitigation, and automatic updates verify a SHA-256 checksum (see `SECURITY.md`, "Self-Update"). Not planned for now; will be revisited if the warning turns out to be a real barrier for users.
- Generated SBOM + hash-locked dependency lockfile (`TODO_HARDENING.md` D2 — dossier value only, no urgency for a hobby tool)
- Formal documented vulnerability-handling process beyond the existing `SECURITY.md` disclosure channel (`TODO_HARDENING.md` D3)
- Removing the Sync Garmin / Sync Context / Create Reports buttons — discussed and analysed twice (v1.6.0), decided against: the Stop button for both sync paths hangs off the same widgets, so removal would take Stop functionality with it, and the CSV button belongs to the Context section thematically. Low benefit, real risk of silent side effects. Recorded here as a decision taken, not as a pending item — it sat on a parking list without a target version and was never one.
- Streaming for the Ollama+MCP tool-calling path (v1.7.2) — Ollama's own
  streaming + tool-calling combination is currently unreliable upstream:
  confirmed against a High-severity open Ollama issue — with `stream: true`
  and `tools` both set, the tool call arrives as one complete block with no
  accompanying explanatory text, even when the model would normally produce
  some. Established client libraries work around this by forcing
  `stream: false` whenever tools are involved, which is what this project's
  Ollama+MCP path already does. Cloud+MCP (Anthropic/OpenAI) streams
  normally — this exclusion is Ollama-specific, not a general limitation of
  the tool-calling architecture. Revisit only if Ollama's own upstream
  support changes.
- qwen3/qwen2.5-coder enforcement for the Chat tab's `mcp` source (v1.7.2) —
  stays an advisory hint (`_mcp_model_hint`), not an enforced restriction;
  any installed Ollama model remains technically selectable. Decision taken
  during the v1.7.2 build, not a gap.
- `garmin_extended_anaysis.py` (Easter Egg) on T3 (v1.7.2.2) — investigated,
  not fixed. The file is already bundled on both T2 and T3
  (`build_manifest.py`'s `SHARED_SCRIPTS`), so it's not a bundling gap as
  originally suspected. The actual issue: the hidden trigger (a click on the
  header unicorn) calls `_run_extended_analysis()`, which `garmin_app_base.py`
  defines as a no-op stub ("Subclass (garmin_app.py) overrides with
  `_find_python()` access") — `garmin_app.py` (T1/T2) overrides it with a real
  `subprocess.Popen([_find_python(), script], ...)` call, but
  `garmin_app_standalone.py` (T3) never does, so on T3 the click silently does
  nothing. A real fix would need either a fourth standalone PyInstaller exe
  (next to the GUI, `daily_update.exe`, `mcp_server.exe`) or an in-process
  rewrite (e.g. `runpy` instead of a subprocess'd new console window) — both
  disproportionate effort for a hidden Easter Egg with no functional role
  (`MAINTENANCE_GLOBAL.md`/`MINDSET.md`: intentionally excluded from the
  regular reference docs, project-humor module, separately CC-BY-licensed).
  Left as a silent no-op on T3, decided against fixing.
- `write_summary_only()` (v1.7.4.0.4) used by `garmin_import_mirror.py`'s
  schema-match fast path too — considered and decided against during the
  v1.7.4.0.4 build: that fast path always needs a real `raw/` write (it is
  importing a day that doesn't exist locally yet, not recomputing a
  summary for an already-archived day), so the schema-migration case
  isn't actually analogous. Revisit only if a genuinely summary-only
  mirror-import case turns up.
- `dash_runner.py` `html_complex` filename bug (found v1.7.3.3) — `scan()`
  normalizes the `"html_complex"` format key to `"html"` for GUI display,
  but `build()`'s output-filename lookup uses that normalized key instead
  of the original, so every `html_complex` specialist (Sleep Dashboard,
  Sleep & Recovery, Explorer, Heatmap, Live Tracking) writes its file
  under `{module_name}.html` instead of the name declared in its own
  `META["formats"]`. In practice harmless for the GUI dashboard viewer
  (scans the `dashboards/` folder generically, no fixed filename
  expected) — only `garmin_mobile_landing.py`'s hardcoded Sleep Dashboard
  lookup broke, worked around locally there (v1.7.3.3). Root cause not
  fixed — real fix is `build()` using the already-computed `plotter_key`
  instead of `fmt` for the filename lookup ([dash_runner.py:247]). Left
  open, not a committed timeline — revisit if another fixed-filename
  consumer of an `html_complex` specialist is ever added.

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*