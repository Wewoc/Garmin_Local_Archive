# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

## Currently stable — v1.2.2

- **Bug Fixes + Security + Polish (v1.2.1)** — `GarminLoginError` exception, per-endpoint failure tracking, input validation in normalizer, preventive `QUALITY_LOCK`, random salt in token encryption, GUI labels fully in English, random request delay, export date range auto-fill, default data folder fix. See CHANGELOG for details.
- **Code Hygiene (v1.2.1b)** — `build_manifest.py` as single source of truth for build lists, `build_all.py` added, `garmin_utils.py` added with shared helpers, `garmin_config.py` logic extracted to utils, `test_local.py` extended to 116 checks. See CHANGELOG for details.
- **Schema Versioning (v1.2.2)** — `schema_version` field in summary files, `CURRENT_SCHEMA_VERSION` in `garmin_normalizer.py`, `source` origin tracking in `quality_log.json`. See CHANGELOG for details.

---

### v1.2.3 — Include-today Flag

An optional `INCLUDE_TODAY` flag that allows syncing today's incomplete data. Currently today is always excluded because the data is partial — this flag makes it opt-in. Lives in `garmin_sync.py` after refactoring.

---

### v1.2.4 — Archive Info Panel

A compact read-only info panel in the GUI showing the current state of the local archive at a glance:

- Total days tracked in `quality_log.json`
- Breakdown by quality: `high / medium / low / failed`
- Days with `recheck=true` (pending background timer work)
- Earliest and latest date in `raw/`
- Archive completeness: days present vs. possible days in range (%)
- Last sync timestamp

Reads directly from `garmin_quality.py` after refactoring — no API call needed. Updates after every sync.

---

### v1.2.5 — Version Check on Startup

Checks GitHub for a newer release on app start and notifies the user if one is available.

- GitHub API: `GET /repos/Wewoc/Garmin_Local_Archive/releases/latest` → compare `tag_name` with embedded `APP_VERSION` constant
- Runs in a background thread — non-blocking
- No internet: silently ignored
- Notification: popup or log entry (not yet decided)

---

### v1.2.6 — Flagged Day Tooltips + MFA Hint

**Flagged Day Tooltips** — hovering over a flagged day marker in the Analysis Dashboard shows the exact value and why it was flagged (above/below reference range, distance from baseline).

**MFA / Captcha Hint** — when login fails with an authentication error (401/403 or MFA challenge), the GUI shows a specific actionable hint instead of just the raw error — especially important for the Standalone version where no terminal is available:

```
✗ Login failed — Garmin may require browser verification.
  → Download the Standard version, run garmin_collector.py once
    in a terminal to complete MFA, then use Standalone normally.
```

**Error log access for Standalone users** — when something goes wrong, Standalone users (no terminal available) should never need a command prompt to diagnose the issue. Add a "Copy last error log" button to the GUI that reads the most recent file from `log/fail/` and copies it to the clipboard — ready to paste into a GitHub issue or chat. Complements the existing session logging infrastructure.

### v1.2.7 — Dashboard Rework Preparation

`quality_log.json` - extended

The overall status `failed/low/medium/high` remains as before; individual records are now evaluated in detail.

**Goal:**

Downstream scripts (dashboards & AI summaries) no longer need their own validation logic. They query the "State Owner" (`garmin_quality.py`) and immediately know which data can be visualized and which cannot.

**Introduction of granular status flags per data type:**

🟢 **High Quality:** Complete intraday dataset available. Enables high-resolution graphs (e.g., 2-minute heart rate intervals).

🟡 **Medium Quality (Erosion Protection):** Only daily summaries available. The system automatically detects when Garmin has "smoothed" older data and adjusts the dashboard display accordingly.

🔴 **Low Quality:** Daily data exists, but specific metrics (e.g., HRV or sleep stages) are missing. Dashboards display clean "N/A" values instead of errors.

⚪ **Failed / Pending:** Marks days with download errors or timeouts for automatic retry attempts.

**Recheck Backoff Logic** — adds a `next_attempt` field to `quality_log.json` entries where `recheck=true`. The collector skips a day until `today >= next_attempt`, preventing repeated API queries on every session.

Backoff interval: `attempts × 5 days` (attempt 1 → 5 days, attempt 2 → 10 days, attempt 3 → 15 days).

- `failed`: 3 attempts, then `recheck=false`
- `low`, day younger than 1 year: 3 attempts, then `recheck=false`
- `low`, day older than 1 year: `recheck=false` immediately — Garmin does not retroactively improve historical intraday data

Replaces the placeholder note in v1.2.7 ("retry logic to be defined").

---

### v1.2.8 — Documentation & AI Usability

Focus on making the project easier to use, understand, and safer when used with local AI tools.

- **AI prompts** — provide ready-to-use system prompts for local AI tools (Ollama / AnythingLLM) to correctly interpret `garmin_analysis.json` (quality flags, HRV meaning, stress direction, etc.)
- **Documentation reorganization** — split into clear user, developer, and AI-focused sections (`USER_GUIDE.md`, `ARCHITECTURE.md`, `AI_CONTEXT.md`) with improved navigation, reduced redundancy, and a unified structure that makes the project easier to understand, maintain, and safely extend.
  - README structure: move AI-assisted analysis (Step 11) up directly after the philosophy section — the end result (asking an AI about your health data) should be visible before the technical pipeline details
  - "What is included" script table moved to end of README or fully into `MAINTENANCE.md` — relevant for developers, not for first-time users
  - Standalone troubleshooting: replace all CMD-based instructions with log file navigation via Windows Explorer — point users to `log/fail/` in Notepad instead of a terminal
- **Warnings & disclaimers** — make health-related limitations and AI interpretation risks more prominent in README and dashboards
- **Script-level tests (non-GUI)** — ✅ done in v1.2.0, extended in v1.2.1/v1.2.1b: `test_local.py` covers all core modules with 112 checks (config, sync, normalizer, quality incl. migrations + QUALITY_LOCK, writer, collector internals, security crypto layer, utils). Run with `python test_local.py`.
- **`first_day` caution** — clarify in documentation that `first_day` in `quality_log.json` is **not protected against manual JSON edits or environment variable overrides**; changes can create gaps or inconsistent archival data.
- **Integrity notes** — mention that **no checksums or signatures are currently applied**, so modifications or corruption of `quality_log.json` are not automatically detected; users should handle backups carefully.

---

## Planned — v1.3

### v1.3.0 — Dashboard Architecture Refactoring

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

### v1.3.x — Dashboard Features

New functionality built on the clean v1.3.0 base:

- **Smart Regeneration** — auto-detect summaries generated with an older `schema_version` and re-run `summarize()` on the corresponding raw files without hitting the Garmin API. Extends `regenerate_summaries.py`.
- **Auto-size dashboards** — if requested date range exceeds available data, dashboard adjusts to actual data range with a note explaining the reason.
- **Flag guard** — suppress flagged day markers when underlying data is absent or zero.
- **Outlier / measurement error cleanup** — detect and visually mark obvious outliers and likely sensor errors (e.g. HR spike during sleep).
- **Responsive output** — dynamic resolution and layout adapting to the display device (PC monitor vs. mobile).
- **Measurement accuracy disclaimer** — note on each dashboard indicating the typical accuracy range of consumer wearables under ideal conditions (e.g. HR ±X%).

---

## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**`GarminAppBase` — GUI Consolidation (Pre-v2.0 Preparation)**

`garmin_app.py` and `garmin_app_standalone.py` currently share identical GUI code but differ fundamentally in their execution model: Target 2 spawns subprocesses (`_run_script`), Target 3 imports modules directly in threads with queue-based output (`_run_module`). This means every GUI fix currently requires changes in two places.

The clean solution is a base class `GarminAppBase` in a shared `garmin_app_base.py` containing all GUI logic. Each target file then only defines what differs: `script_dir()`, `_find_python()`, and the run mechanism. This is a significant refactor — not a simple extraction — and requires careful handling of PyInstaller dependency detection and the `_STOP_EVENT` injection mechanism.

Intentionally deferred until v2.0 architecture is stable: the multi-source architecture will likely require further GUI changes, making it more efficient to consolidate once rather than twice.

**`build_manifest.py`** — already done in v1.2.1b as a simpler analogue: shared script lists and signatures extracted into a single file, both build scripts import from it. Adding a new module now only requires one edit.

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
Local overview of archive health built from session logs — days synced vs failed over time, which API endpoints fail most often, Garmin API response patterns by time of day. Builds on the Archive Info Panel (v1.2.4) and the quality data in `quality_log.json`. No extra API calls needed.

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected — it just isn't used beyond the summary.

**Test suite & CI/CD**
Core modules are covered by test_local.py (116 checks, extended in v1.2.1/v1.2.1b/v1.2.2). Build integrity is covered by validate_scripts() in both build scripts — verifies all required scripts are present and contain expected signatures before PyInstaller runs (added in v1.2.0). Full CI/CD with GitHub Actions for automated builds and release packaging requires a stable v1.x architecture as a foundation — intentionally deferred until v1.3 is complete. No timeline, no commitment, but the intention is there.

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
