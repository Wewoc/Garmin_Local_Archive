# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.
> There are no deadlines, no guarantees, and no support obligations.
> Features get built when they get built.

---

## Currently stable — v1.1.0

- Local archiving of Garmin Connect health data
- Three sync modes: recent, range, auto
- Excel exports (daily overview + intraday timeseries)
- Interactive HTML dashboards (timeseries + analysis)
- Analysis dashboard with personal baseline and age/fitness reference ranges
- JSON export for local AI tools (Ollama / AnythingLLM / Open WebUI)
- Desktop GUI with connection test, log toggle, sync mode field dimming
- Three targets: scripts only, standard EXE (Python required), standalone EXE (no Python required)
- **Failed days tracking** — incomplete and failed raw files detected automatically, logged to `log/failed_days.json`, re-fetchable via popup on sync start
- **Session logging** — every sync writes a full DEBUG log to `log/recent/`; sessions with errors or incomplete days are additionally copied to `log/fail/`

---

## Planned — v1.1 (remaining)

### 2. Background Timer

Background sync that runs while the app is open. Picks up failed and missing days automatically without manual intervention.

- Start/Stop button (green when active)
- Interval: random 5–30 min between runs
- Days per Run: random 3–10 days
- Live countdown to next run (MM:SS)
- Queue display: open days (missing + failed, from `failed_days.json`)
- Does not run while manual sync is active
- Stops cleanly on app close

### 3. Version Check on Startup

Checks GitHub for a newer release on app start and notifies the user if one is available.

- GitHub API: `GET /repos/Wewoc/Garmin_Local_Archive/releases/latest` → compare `tag_name` with embedded `APP_VERSION` constant
- Runs in a background thread — non-blocking
- No internet: silently ignored
- Notification: popup or log entry (not yet decided)
- Version definition: constant in app files or external `version.txt` (not yet decided)

No dependency on #2 — can be implemented independently.

### 4. Schema Versioning

A `schema_version` field in `summary/garmin_YYYY-MM-DD.json`. Makes it possible to detect when summaries were generated with an older version of `summarize()` and flag them for regeneration.

`CURRENT_SCHEMA_VERSION` in `garmin_collector.py` is the single source of truth. When the `summarize()` function changes in a way that affects output fields, the version is incremented. Smart Regeneration (v1.2) then picks up any summary where `schema_version < CURRENT_SCHEMA_VERSION`.

**Coupling with Failed Days Tracking:** days logged in `failed_days.json` are written with `schema_version: 0` — permanently below any real version. This means Smart Regeneration will always include them in its regeneration queue once their raw file is complete, without needing a separate code path.

### 5. Include-today Flag

An optional `INCLUDE_TODAY` flag that allows syncing today's incomplete data. Currently today is always excluded because the data is partial — this flag makes it opt-in.

### 6. Analysis Dashboard — Flagged Day Tooltips

Small UX improvement: hovering over a flagged day marker in the Analysis Dashboard shows the exact value and why it was flagged (above/below reference range, distance from baseline). Currently the information is only visible by reading the chart carefully.

---

## Planned — v1.2

### Dashboard Architecture Refactoring

Transition from individual scripts to a master/specialist model:

- `garmin_dashboard_base.py` — shared frame: CSS, Dark Mode, Header, Disclaimer, Footer, Plotly integration, tab navigation
- `garmin_content_timeseries.py` — intraday metrics (HR, Stress, SpO2, Body Battery, Respiration) from `raw/`
- `garmin_content_health.py` — HRV, Resting HR, Stress, Body Battery with baseline + reference ranges from `summary/`
- `garmin_content_sleep.py` — Sleep total, Deep, REM, Sleep score, HRV night from `summary/`
- `garmin_content_activity.py` — Steps, Distance, Training load, Readiness, VO2max from `summary/`

**Why this order matters:** Remaining v1.1 items first — a beautiful modular dashboard on top of incomplete data is still incomplete data. v1.2 refactors the architecture, v1.3 adds the new dashboards on the clean base.

**Benefits:**
- Design changes in one place — applies to all dashboards
- Disclaimer updated once — everywhere
- New dashboard = new specialist script, base untouched
- Claude-efficient: a specialist script is ~300 lines vs. a 2000-line monolith — future sessions only load the relevant file, which reduces token usage and keeps the full context window available for actual work

### Smart Regeneration

Automatic detection of summaries that were generated with an older `schema_version` and re-running `summarize()` on the corresponding raw files — without hitting the Garmin API again.

Builds directly on Schema Versioning (v1.1 #4) and extends the existing `regenerate_summaries.py`. The logic: scan all `summary/` files, compare `schema_version` against the current version, collect outdated entries, regenerate in batch. Clean runs produce no output.

---

## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**Multiple Garmin accounts**
Currently one account per Windows user. Switching between accounts requires manually changing credentials in Settings. Multi-account support would allow profiles per user.

**External factors & correlations**
Import external data (weather, activity logs, custom notes) and correlate with health metrics. Did poor sleep correlate with high stress? Did training load predict HRV drops?

**Adaptive Baselines**
Extend the Analysis Dashboard beyond fixed 90-day baselines. Rolling windows (7-day, 30-day), seasonal patterns, and load vs. recovery phase detection. The raw data is already there — this is purely an analytical layer on top of `garmin_analysis_html.py`.

**AI training recommendations**
Context-aware training suggestions based on your own data — HRV trends, Body Battery recovery, sleep quality, training load. Uses published guidelines (AHA, ACSM, Firstbeat whitepapers, Jack Daniels VDOT) as the knowledge base, fed to a local AI model alongside your `garmin_analysis.json`. No proprietary algorithms, no cloud — just your data + open science + local AI. Example output: "Your HRV is 15% below your 7-day baseline and Body Battery recovery is slow — an easy day would be appropriate."

> ⚠️ **Known risk:** Local LLMs can hallucinate when interpreting medical or health data. A coach that draws wrong conclusions from HRV trends could mislead users. Mitigation strategy to be defined before implementation — likely strict output templates, explicit uncertainty markers, and a prominent disclaimer that suggestions are informational only and not medical advice.

**AI health report PDF**
Generate a formatted PDF health summary using the local AI model — personal baseline, flagged days, trends. Fully local, no cloud.

**Route heatmap**
Generate a local heatmap of GPS routes from activity data. No third-party mapping services.

**Windows notifications**
Toast notifications for sync completion, failed days, or significant metric changes.

**Stats dashboard & session log analysis**
Local overview of archive health built from session logs written by v1.1 — days synced vs failed over time, which API endpoints fail most often, average file size trends (useful for catching incomplete days before they accumulate), Garmin API response patterns by time of day. No extra API calls needed.

---

## Not planned

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- Support for non-Windows platforms (currently Windows only)
- Code signing or automatic updates

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected by the collector — it just isn't used beyond the summary. Would provide additional context for AI training recommendations.

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*
