# Garmin Local Archive — Version History

Feature-driven log — for technical details, see [CHANGELOG.md](src/docs/CHANGELOG.md).

## v1.7.2.4.x — Self-Updater

- New "Update" button downloads, verifies, and applies a new version in place, then restarts the app automatically — no more manual download and re-extracting the ZIP.
- Optional unattended auto-apply via the scheduled Daily Sync.
- If a new version fails to start, it's automatically rolled back to the previous working version — no manual recovery needed.

## v1.7.2.x — Chat with Live Access & Cloud AI

- Chat now reads live from the archive instead of only a daily snapshot.
- Optional cloud AI connection (Anthropic/OpenAI) for real-time, word-by-word responses.
- Chat history is saved and preserved across model switches.
- New check function finds and repairs faulty location data in the context archive.

## v1.7.1.x — Improved Chat & New Health Metrics

- Chat reliably understands casual language, shorthand, and typos.
- Asks for clarification on ambiguous requests instead of returning wrong values.
- 23 additional health metrics (including training status, calories, HRV) and blood pressure now queryable in chat.
- New "Force Refetch" function for reloading individual days on demand.
- Theme switcher for the UI completed.

## v1.7.0.x — AI Querying of the Archive

- The archive can be queried in natural language via a local AI (MCP server).
- Integration for external programs such as Open WebUI.

## v1.6.9.x — Fixes

- Fixed empty sleep dashboard preview on the mobile home page.

## v1.6.8.x — API Scan for New Data Types

- New "API Scan" function: detects additional Garmin data types supported by your device and makes them usable in dashboards.

## v1.6.6.x – v1.6.7 — Chat with Local AI

- Local AI (Ollama) integrated directly into the app — no external companion program needed anymore.

## v1.6.5.x — Live Tracking Dashboard

- New "Live Tracking" dashboard: current-day status for Body Battery, heart rate, steps, stress, and last night's sleep.
- Explorer and Heatmap dashboards now automatically adapt to the available data range.
- Fixed: wrong timezone in intraday charts.
- Fixed: "Live Tracking" wasn't updating in the standalone version.

## v1.6.4.x — Custom Dashboard Builder

- Build your own dashboards from freely selectable data fields, save as a template, and encrypt.

## v1.6.3.x — Steps in Detail

- Step history (intraday) is now also captured, including backfill for already-archived days.
- New Heatmap dashboard.
- Fixed: SpO2 and respiration rate were showing empty in several dashboards.

## v1.6.2.x — Sleep Dashboard with Drilldown

- Clicking a night in the Sleep dashboard jumps straight to its intraday data (heart rate, stress, Body Battery, respiration).

## v1.6.1 — Encrypted Dashboard Export

- Dashboards can be exported password-protected and encrypted (e.g. for USB drives).

## v1.6.0.x — New Home Page & Archive Protection

- New home page: connection status, archive overview, and device list always visible.
- New "Silo Check" function: finds and repairs inconsistencies in the archive.
- The unmodified original response from Garmin is now also stored permanently (protection against future data loss).
- Several sync- and crash-related bug fixes.

## v1.5.8.x – v1.5.9 — Mobile Home Page

- Standalone version starts significantly faster.
- New mobile home page with archive status and links to the dashboards, accessible from your phone's browser.
- New "Files" tab: view Excel dashboards directly in the app without opening Excel.

## v1.5.7.x — Clearer Quality Levels

- Quality levels renamed and corrected ("high/standard/failed").
- New device overview table in the app.

## v1.5.6.x — Encrypted Mirror Export

- Mirror export to USB/NAS/cloud is now a single encrypted file instead of an open folder.
- Fixed: days with only a step count were incorrectly rated as higher quality.

## v1.5.4.x – v1.5.5.x — New User Interface

- Complete overhaul of the user interface to a more modern window system.
- Dashboards can now be viewed directly in the app, without an external browser.
- Login flow secured: active confirmation required before every first-time login.
- New splash screen on program startup.

## v1.5.0.x – v1.5.1.x — Automatic Archive Backup

- New backup function: the archive is automatically backed up and restored if corrupted.
- Mirror export to external drives added.
- Fixed Garmin login issue.
- New "HRV 7-day avg" column in the Sleep dashboard.

## v1.4.9.x — New Color Scheme

- New color scheme (dark purple) and new logo.
- New button to automatically set up a Windows scheduled task for the daily sync.

## v1.4.8 — Sleep Dashboard

- New Sleep dashboard with a night-by-night overview (sleep phases, duration, score, HRV, Body Battery).

## v1.4.6 – v1.4.7.x — New Weather Source

- New weather source (German Weather Service/DWD) for more accurate weather data in Germany.
- New "Explorer" dashboard: freely combine any metrics in one chart.
- Dashboards now automatically adapt to the available data range.

## v1.4.0.x – v1.4.5 — Login & Data Fixes

- Fixed Garmin login after changes on Garmin's side.
- Days imported from a GDPR export are automatically replaced by better live data once available.
- Values outside plausible ranges are now detected and downgraded in quality instead of being silently accepted.

## v1.3.0.x – v1.3.4 — GDPR Data Import

- New function: Garmin's GDPR data export can be imported.
- Data quality is now assessed per metric type individually.
- New archive info panel: day count, data quality, time range, and coverage at a glance.
- Login mechanism adapted to Garmin changes, including two-factor prompts.

## v1.2.0.x – v1.2.2.x — Encrypted Credentials

- Credentials (tokens) are now stored encrypted, which mostly eliminates repeated two-factor logins.
- Improved protection against account lockouts from too many requests.
- UI fully translated to English.

## v1.1.x — Automatic Archive Repair

- New background timer automatically repairs and completes the archive while the app is open.
- Failed days are remembered and retried before the next sync.
- Archive start date is now detected automatically.
- New "Clean Archive" button for cleaning up old data.

## v1.0 — Standalone Program

- New standalone program version (standalone EXE), runs without a separate Python installation.

## v0.x — First Version

- First working version: simple interface for setting up, syncing, and exporting Garmin data.
- Password stored securely in the Windows credential store.
- Window size and export time range configurable in the interface.
