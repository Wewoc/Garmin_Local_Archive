# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.3.4**

---

## Planned

### v1.4.0 — Dashboard Architecture Refactoring

Transition from individual monolithic scripts to a master/specialist model. No new dashboard content — pure architectural cleanup.

**Target structure:**

| Module | Content |
|---|---|
| `garmin_dashboard_base.py` | Shared frame: CSS, Dark Mode, Header, Disclaimer, Footer, Plotly integration, tab navigation |
| `garmin_content_timeseries.py` | Intraday metrics (HR, Stress, SpO2, Body Battery, Respiration) from `raw/` |
| `garmin_content_health.py` | HRV, Resting HR, Stress, Body Battery with baseline + reference ranges from `summary/` |
| `garmin_content_sleep.py` | Sleep total, Deep, REM, Sleep score, HRV night from `summary/` |
| `garmin_content_activity.py` | Steps, Distance, Training load, Readiness, VO2max from `summary/` |

**Benefits:** design changes in one place, disclaimer updated once everywhere, new dashboard = new specialist script with base untouched, Claude-efficient (300-line specialists vs. 2000-line monolith).

---

### v1.4.0 — Dashboard Architecture Refactoring + v2.0 Interface Validation

Transition from individual monolithic scripts to a master/specialist model.
No new dashboard content — pure architectural work.

This version serves a dual purpose: cleaning up the dashboard architecture
**and** validating the data broker concept planned for v2.0 — with real
Garmin data, before a second source makes a redesign expensive.

**Target structure:**

| Module | Role |
|---|---|
| `garmin_dashboard_base.py` | Shared frame: CSS, Dark Mode, Header, Disclaimer, Footer, Plotly integration, tab navigation |
| `garmin_map.py` | Garmin-specific data access — translates common field names to Garmin internals, reads `raw/` and `summary/` |
| `field_map.py` | Source-agnostic broker — registered sources only, single entry point for all dashboard and export scripts |
| `garmin_content_timeseries.py` | Intraday metrics (HR, Stress, SpO2, Body Battery, Respiration) |
| `garmin_content_health.py` | HRV, Resting HR, Stress, Body Battery with baseline + reference ranges |
| `garmin_content_sleep.py` | Sleep total, Deep, REM, Sleep score, HRV night |
| `garmin_content_activity.py` | Steps, Distance, Training load, Readiness, VO2max |

Content specialists call `field_map` only — no direct file access, no knowledge
of source-specific field names or directory structure.

**v2.0 validation goals:**

- Does `field_map.get(field, date_from, date_to)` hold as a stable interface,
  or does intraday (`raw/`) vs. daily (`summary/`) data require a split?
- Does `garmin_map.py` stay manageable, or does Garmin's data variety force
  a further split between raw and summary access?
- Does the broker add real value with a single source, or does friction appear
  before Strava is ever involved?

Findings feed directly into `CONCEPT_V2-0.md` — while it is still a document,
not running code.

---

### v1.4.x — Dashboard Features

New functionality built on the clean v1.4.0 base:

- **Smart Regeneration** — auto-detect summaries generated with an older
  `schema_version` and re-run `summarize()` on the corresponding raw files
  without hitting the Garmin API. Extends `regenerate_summaries.py`.
- **Auto-size dashboards** — if the requested date range exceeds available
  data, the dashboard adjusts to the actual range with a note explaining why.
- **Flagged Day Tooltips** — hovering over a flagged day marker shows the exact value and why it was flagged (above/below reference range, distance from baseline). Deferred from v1.3.3 — belongs in the dashboard refactor context.
- **Flag guard** — suppress flagged day markers when underlying data is
  absent or zero.
- **Outlier / measurement error cleanup** — detect and visually mark obvious
  outliers and likely sensor errors (e.g. HR spike during sleep).
- **Responsive output** — dynamic resolution and layout adapting to the
  display device (PC monitor vs. mobile).
- **Measurement accuracy disclaimer** — note on each dashboard indicating
  the typical accuracy range of consumer wearables under ideal conditions
  (e.g. HR ±X%).

---

### v1.4.x — Documentation & AI Usability

Focus on making the project easier to use, understand, and safer when used with local AI tools.

- **AI prompts** — provide ready-to-use system prompts for local AI tools (Ollama / AnythingLLM) to correctly interpret `garmin_analysis.json` (quality flags, HRV meaning, stress direction, etc.)
- **Documentation reorganization** — split into clear user, developer, and AI-focused sections (`USER_GUIDE.md`, `ARCHITECTURE.md`, `AI_CONTEXT.md`) with improved navigation, reduced redundancy, and a unified structure that makes the project easier to understand, maintain, and safely extend.
  - README structure: move AI-assisted analysis (Step 11) up directly after the philosophy section — the end result (asking an AI about your health data) should be visible before the technical pipeline details
  - "What is included" script table moved to end of README or fully into `MAINTENANCE.md` — relevant for developers, not for first-time users
  - Standalone troubleshooting: replace all CMD-based instructions with log file navigation via Windows Explorer — point users to `log/fail/` in Notepad instead of a terminal
- **Warnings & disclaimers** — make health-related limitations and AI interpretation risks more prominent in README and dashboards
- **`first_day` caution** — clarify in documentation that `first_day` in `quality_log.json` is **not protected against manual JSON edits or environment variable overrides**; changes can create gaps or inconsistent archival data.
- **Integrity notes** — mention that **no checksums or signatures are currently applied** to `quality_log.json`; modifications or corruption are not automatically detected — users should handle backups carefully.

---

## Planned — v1.5

### v1.5 — Archive Integrity & Backup

Protection of the local archive against software errors and silent data loss — independent of OS-level backup.

**`quality_log.json`**

- **Monthly backup** — `_save_quality_log()` creates a snapshot once per month as `quality_log_YYYY-MM.zip` in `log/backup/`. On the first save of a new year, the previous year is consolidated into `quality_log_YYYY.zip` and all monthly zips for that year are removed.
- **Per-year checksums** — on every save, a SHA-256 hash is computed over all `days` entries for each calendar year and stored in a `checksums` block inside `quality_log.json`. On load, all completed years are verified — a mismatch triggers a warning in the log and GUI indicating which year is affected and where the backup is located.

**`raw/`** — incremental backup of newly written files. Motivation: Garmin degrades intraday data after ~1–2 years — the local raw copy is then the only source. A software bug in the writer that overwrites or corrupts a raw file is not recoverable without a backup. This is a direct extension of the data erosion protection that is a core promise of this project.

- Ownership: writer or a dedicated backup module — to be evaluated
- Strategy: incremental, newly written files only
- Scope and implementation to be defined after v1.4 is stable

---

## Deferred — end of v1.x

### v1.x — Include-today Flag

An optional `INCLUDE_TODAY` flag that allows syncing today's incomplete data. Currently today is always excluded because the data is partial — this flag makes it opt-in. Lives in `garmin_sync.py`.

Low priority — only relevant once API access is stable and the bulk import backlog is resolved.

---


## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**`GarminAppBase` — GUI Consolidation (Pre-v2.0 Preparation)**

`garmin_app.py` and `garmin_app_standalone.py` currently share identical GUI code but differ fundamentally in their execution model: Target 2 spawns subprocesses (`_run_script`), Target 3 imports modules directly in threads with queue-based output (`_run_module`). This means every GUI fix currently requires changes in two places.

The clean solution is a base class `GarminAppBase` in a shared `garmin_app_base.py` containing all GUI logic. Each target file then only defines what differs: `script_dir()`, `_find_python()`, and the run mechanism. This is a significant refactor — not a simple extraction — and requires careful handling of PyInstaller dependency detection and the `_STOP_EVENT` injection mechanism.

Intentionally deferred until v2.0 architecture is stable: the multi-source architecture will likely require further GUI changes, making it more efficient to consolidate once rather than twice.

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
Core modules are covered by `test_local.py` (136 checks, extended in v1.2.1/v1.2.1b/v1.2.2/v1.3.0). Build integrity is covered by `validate_scripts()` in both build scripts. Full CI/CD with GitHub Actions for automated builds and release packaging requires a stable v1.x architecture as a foundation — intentionally deferred until v1.4 is complete. No timeline, no commitment, but the intention is there.

---

## Post-release tasks

- **Screenshots** — 2–3 GUI screenshots + Dashboard screenshots in README.md once v1.2.0 is stable in the repo

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
