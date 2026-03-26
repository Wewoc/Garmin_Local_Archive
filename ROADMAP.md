# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

## Currently stable — v1.1.2

- Local archiving of Garmin Connect health data
- Three sync modes: recent, range, auto
- Excel exports (daily overview + intraday timeseries)
- Interactive HTML dashboards (timeseries + analysis)
- Analysis dashboard with personal baseline and age/fitness reference ranges
- JSON export for local AI tools (Ollama / AnythingLLM / Open WebUI)
- Desktop GUI with connection test, log toggle, sync mode field dimming
- Three targets: scripts only, standard EXE (Python required), standalone EXE (no Python required)
- **Quality tracking** — every downloaded raw file is assessed for content quality (`high/med/low/failed`) and registered in `log/quality_log.json`. Content-based assessment replaces the old file-size heuristic, correctly handling the Garmin data retention limit (~1–2 years of intraday detail). Days with `recheck=true` are re-downloaded by the background timer; after `LOW_QUALITY_MAX_ATTEMPTS` (default 3) failed attempts a `low` day is left alone permanently.
- **Background Timer** — automatic background sync that cycles through three modes per run: Repair (API failures → `failed`), Quality (low-content days → `low`), Fill (true gaps never downloaded). Configurable interval and days-per-run. Live countdown and progress in the button. Connection test before first run. Stops cleanly on app close or when archive is complete. Background sessions logged with `garmin_background_` prefix.
- **Session logging** — every sync writes a full DEBUG log to `log/recent/`; sessions with errors or low-quality downloads are additionally copied to `log/fail/`
- **First Day Patch** — `first_day` anchor stored in `quality_log.json`. Detected once on first run (devices → account profile → fallback → oldest local file), never overwritten. Auto mode and background timer use it directly as the lower bound — no repeated API calls. Device history (`name`, `id`, `first_used`, `last_used`) stored alongside and refreshed on every login. One-time backfill on upgrade populates all existing `high`/`med` days that were previously missing from the quality log. **Clean Archive** button in the GUI opens a preview popup and removes all files and log entries before `first_day` on confirm.

---

## Planned — v1.2

### v1.2.0 — Collector Refactoring

The core architectural overhaul. `garmin_collector.py` is split into focused modules with clear single responsibilities. No new features — existing behaviour is preserved exactly.

**Target architecture:**

| Module | Role |
|---|---|
| `garmin_config.py` | All environment variables, defaults, are loaded first. |
| `garmin_api.py` | Login, session management, all API calls (`fetch_raw`, `api_call`, `get_devices`). No logic, no file writes. |
| `garmin_import.py` | Loads and parses Garmin bulk export data into raw input format (no normalization). |
| `garmin_normalizer.py` | Converts data from different sources into a unified schema and attaches minimal source metadata. |
| `garmin_quality.py` | Sole owner of `quality_log.json`. Loads, saves, assesses, upserts. Only module allowed to write the quality log. |
| `garmin_sync.py` | Determines what needs downloading. `resolve_date_range`, `get_local_dates`, missing-day calculation. Returns data only — no side effects. |
| `garmin_collector.py` | Thin orchestrator. Coordinates modules and is responsible for writing normalized data to `/raw`. |

**Also included:**
- `pending_jobs.json` — persistent job queue. If the app closes mid-sync, remaining dates are preserved and picked up on next start (resilience against crashes and power loss).
- Phase-by-phase extraction: Quality → API → Sync → Collector. One module at a time, behaviour verified identical after each step before proceeding.

**Refactoring rules (non-negotiable):**
- No logic changes during extraction — only move code, never modify it
- Only one module writes `quality_log.json`
- One step at a time, test after each step
- AI partner loads only the relevant module per session — keeps context window free for actual work

---

### v1.2.1 — GUI Cleanup + Polish

Housekeeping pass after the refactoring. No new functionality.

- All GUI labels and field names in English (currently mixed German/English)
- Request delay changed from fixed `1.5s` to a random value between configurable min/max (e.g. 1.0–3.0s) — breaks the fixed request pattern to reduce Garmin rate-limit risk
- Export date range: leaving **To** empty defaults to the most recent available file
- Export date range: leaving **From** empty defaults to the oldest available file
- Quality log: rename `"med"` → `"medium"` throughout (`quality_log.json`, `assess_quality`, all references)
- Session limit: max days per run configurable via `GARMIN_MAX_DAYS_PER_SESSION` (default: 30) — prevents account throttling on large backlogs

---

### v1.2.2 — Schema Versioning

**Dual tracking system** for both data format evolution and import origin:

1) A `schema_version` field in `summary/garmin_YYYY-MM-DD.json`. Makes it possible to detect when summaries were generated with an older version of `summarize()` and flag them for regeneration.

`CURRENT_SCHEMA_VERSION` in `garmin_quality.py` is the single source of truth after refactoring. When `summarize()` changes in a way that affects output fields, the version is incremented. Smart Regeneration (v1.3) picks up any summary where `schema_version < CURRENT_SCHEMA_VERSION`.

Days with `quality=low` or `quality=failed` can be treated as `schema_version: 0` — permanently below any real version. Smart Regeneration will always include them once their raw file is complete.

2) **`source` flag** in `quality_log.json` — tracks the origin of each day's raw data:

"source": "api" // Live Garmin Connect API pull
"source": "bulk" // Garmin bulk export ZIP
"source": "csv" // Manual CSV import
"source": "manual" // User-provided JSON

**Benefits:**
- **Smart Regeneration** skips `bulk`/`csv` (no API), only re-processes `api`
- **Quality expectations** by source (`api` → full intraday, `csv` → daily only)
- **Archive transparency** — Archive Info Panel shows source breakdown (v1.2.4)
- **Debugging** — low quality on `bulk` expected, on `api` → investigate

**Example `quality_log.json` entry:**
```json
{
  "2026-03-24": {
    "quality": "high",
    "source": "api",
    "schema_version": 2,
    "source_metadata": {
      "api_version": "1.2.0"
    }
  }
}

```

`garmin_normalizer.py` sets `source` based on calling module (v1.2.0 refactoring).
    - only Data with `source` API will have the option for "recheck": true,
      - data older than 6 month get "max. "attempts": 1" befor "recheck": false,

**Legacy Migration:** 
- Existing `quality_log.json` entries → add `"source": "legacy"` on first write
- **Legacy CAN be Smart-Regenerated** (raw files exist, quality already assessed)
- quality_log.json schema extended non-breaking: `source`, `source_metadata` added

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

### v1.2.7 — Dashboard Rework Preparation

`quality_log.json` - extended

The overall status `failed/low/medium/high` remains as before; individual records are now evaluated in detail.

**Goal:**

Downstream scripts (dashboards & AI summaries) no longer need their own validation logic. They query the "State Owner" (`garmin_quality.py`) and immediately know which data can be visualized and which cannot.

**Introduction of granular status flags per data type:**

🟢 **High Quality:** Complete intraday dataset available. Enables high-resolution graphs (e.g., 2-minute heart rate intervals).

🟡 **Medium Quality (Erosion Protection):** Only daily summaries available. The system automatically detects when Garmin has "smoothed" older data and adjusts the dashboard display accordingly.

🔴 **Low Quality:** Daily data exists, but specific metrics (e.g., HRV or sleep stages) are missing. Dashboards display clean "N/A" values instead of errors.

⚪ **Failed / Pending:** Marks days with download errors or timeouts for automatic retry attempts (retry logic to be defined).

---

### v1.2.8 — Documentation & AI Usability

Focus on making the project easier to use, understand, and safer when used with local AI tools.

- **AI prompts** — provide ready-to-use system prompts for local AI tools (Ollama / AnythingLLM) to correctly interpret `garmin_analysis.json` (quality flags, HRV meaning, stress direction, etc.)  
- **Documentation reorganization** — split into clear user, developer, and AI‑focused sections (`USER_GUIDE.md`, `ARCHITECTURE.md`, `AI_CONTEXT.md`) with improved navigation, reduced redundancy, and a unified structure that makes the project easier to understand, maintain, and safely extend.  
- **Warnings & disclaimers** — make health-related limitations and AI interpretation risks more prominent in README and dashboards  
- **Script-level tests (non-GUI)** — basic validation tests for core parsing and transformation logic (e.g. date parsing, quality assessment)  
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

**Multiple Garmin accounts**
Currently one account per Windows user. Switching between accounts requires manually changing credentials in Settings. Multi-account support would allow profiles per user.

**External factors & correlations**
Import external data (weather, activity logs, custom notes) and correlate with health metrics. Did poor sleep correlate with high stress? Did training load predict HRV drops?

**Adaptive Baselines**
Extend the Analysis Dashboard beyond fixed 90-day baselines. Rolling windows (7-day, 30-day), seasonal patterns, and load vs. recovery phase detection. The raw data is already there — this is purely an analytical layer on top of `garmin_analysis_html.py`.

**AI health report PDF**
Generate a formatted PDF health summary using the local AI model **only summarie no analythis** — personal baseline, flagged days, trends. Fully local, no cloud.

**Route heatmap**
Generate a local heatmap of GPS routes from activity data. No third-party mapping services.

**Windows notifications**
Toast notifications for sync completion, failed days, or significant metric changes.

**Stats dashboard & session log analysis**
Local overview of archive health built from session logs — days synced vs failed over time, which API endpoints fail most often, Garmin API response patterns by time of day. Builds on the Archive Info Panel (v1.2.4) and the quality data in `quality_log.json`. No extra API calls needed.

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected — it just isn't used beyond the summary.

---

## Post-release tasks

- **Screenshots** — 2–3 GUI screenshots + Dashboard screenshots in README.md once v1.2.0 is stable in the repo

---

## Not planned

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- Support for non-Windows platforms (currently Windows only)
- Code signing or automatic updates

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*
