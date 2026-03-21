# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.
> There are no deadlines, no guarantees, and no support obligations.
> Features get built when they get built.

---

## Currently stable — v1.0.1

- Local archiving of Garmin Connect health data
- Three sync modes: recent, range, auto
- Excel exports (daily overview + intraday timeseries)
- Interactive HTML dashboards (timeseries + analysis)
- Analysis dashboard with personal baseline and age/fitness reference ranges
- JSON export for local AI tools (Ollama / AnythingLLM / Open WebUI)
- Desktop GUI with connection test, log toggle, sync mode field dimming
- Three targets: scripts only, standard EXE (Python required), standalone EXE (no Python required)

---

## Planned — v1.1

### 1. Failed Days Tracking

> *"An archive without integrity checking is not an archive — it's a pile of notes."* — Gemini peer review

A `failed_days.json` file that logs days where the download was incomplete or failed entirely. Currently the collector saves partial files silently — this makes it impossible to know which days need re-fetching without manually checking file sizes.

Two categories:
- `"error"` — API exception during download
- `"incomplete"` — raw file exists but is below threshold (default `INCOMPLETE_FILE_KB = 100`)

JSON structure:
```json
{
  "failed": [
    { "date": "2024-11-03", "reason": "Timeout: ...", "category": "error", "attempts": 2, "last_attempt": "2025-03-20T14:32:11" },
    { "date": "2025-01-15", "reason": "File too small: 18 KB", "category": "incomplete", "attempts": 0, "last_attempt": null }
  ]
}
```

Changes only in `garmin_collector.py`:
- `get_incomplete_dates()` — scans `raw/`, filters files below threshold
- `main()` — loads `failed_days.json` at start, writes at end and on stop
- `except` block — logs failed day or increments `attempts`
- After successful download — removes day from `failed_days.json`
- Stop-aborted days are NOT marked as failed
- Incomplete days stay in `get_local_dates()` — no auto-redownload on normal sync, only via Background Timer

**Session logging** — each sync session writes a log file to `log/garmin_YYYY-MM-DD_HHMMSS.log`. Only written when the session produces errors or incomplete days — clean runs produce no log file. Older logs are kept up to a configurable limit (default: last 30 sessions). Provides a persistent record for debugging failed days without manual copy-paste from the GUI log.

### 2. Background Timer

Background sync that runs while the app is open. Picks up failed and missing days automatically without manual intervention.

- Start/Stop button (green when active)
- Interval: random 5–30 min between runs
- Days per Run: random 3–10 days
- Live countdown to next run (MM:SS)
- Queue display: open days (missing + failed, from `failed_days.json`)
- Does not run while manual sync is active
- Stops cleanly on app close

Requires TODO #1.

### 3. Version Check on Startup

Checks GitHub for a newer release on app start and notifies the user if one is available.

- GitHub API: `GET /repos/Wewoc/Garmin_Local_Archive/releases/latest` → compare `tag_name` with embedded `APP_VERSION` constant
- Runs in a background thread — non-blocking
- No internet: silently ignored
- Notification: popup or log entry (not yet decided)
- Version definition: constant in app files or external `version.txt` (not yet decided)

No dependency on #1 or #2 — can be implemented independently.

### 4. Schema Versioning

A `schema_version` field in `summary/garmin_YYYY-MM-DD.json`. Makes it possible to detect when summaries were generated with an older version of `summarize()` and flag them for regeneration.

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

**Why this order matters:** V1.1 first — a beautiful modular dashboard on top of incomplete data is still incomplete data. V1.2 refactors the architecture, V1.3 adds the new dashboards on the clean base.

**Benefits:**
- Design changes in one place — applies to all dashboards
- Disclaimer updated once — everywhere
- New dashboard = new specialist script, base untouched
- Claude-efficient: future sessions only need to read/write the relevant specialist, not the full HTML

---

## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**Multiple Garmin accounts**
Currently one account per Windows user. Switching between accounts requires manually changing credentials in Settings. Multi-account support would allow profiles per user.

**External factors & correlations**
Import external data (weather, activity logs, custom notes) and correlate with health metrics. Did poor sleep correlate with high stress? Did training load predict HRV drops?

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
Local overview of archive health built from session logs — days synced vs failed over time, which API endpoints fail most often, average time per day, Garmin API response patterns by time of day. Session logs written by TODO #1 are the data source. No extra API calls needed.

---

## Not planned

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- Support for non-Windows platforms (currently Windows only)
- Code signing or automatic updates

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected by the collector — it just isn't used beyond the summary. Would provide additional context for AI training recommendations.
Low effort, signals integrity to security-conscious users. Not a priority as long as build-from-source is available.

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*
