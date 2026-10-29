# Garmin Local Archive — Version History

Feature-driven log — for technical details, see [CHANGELOG.md](CHANGELOG.md).

## v1.7.6.8 — Source Comparison in the Import Summary

- When you import a Garmin export (and in the preview), the log now compares the export with the days the app already holds from the Garmin API. For seven fields (steps, resting, minimum and maximum heart rate, stress average, sleep duration, floors) it says how many days are equal, how many the export adds (the API day has no value) and how many differ, with the first three dates that differ.
- Nothing is overwritten and nothing is stored: the numbers only appear in the log, not in the quality log and not in any data file. Days of the export for which the app holds no API day are counted separately and not compared.
- The comparison runs only when you import an export, not during Sync or the daily update. It reads the daily files of the API archive once; for an archive of several thousand days this adds a few tens of seconds to the import or the preview.

## v1.7.6.7 — More Export File Types and Import Inventory

- The import of a Garmin export now also reads the health status of the day (a daily check of HRV, heart rate, SpO2, skin temperature and respiration against your baseline) and the single pulse alerts. They are stored with the daily values; for now no screen or AI query shows them.
- Gear, personal records, saved courses and the heart-rate and power zones of the export are kept unchanged in `garmin_data/bulk/source`, so they are not lost with the ZIP. They are part of the backup and the mirror. Nothing is read from them yet.
- At the end of the import (and of the preview) the log lists what the export held: how many files of each known kind, and how many JSON files the app did not know, with the folders they lie in. File names are never logged.
- A JSON file over 64 MB is skipped and counted.
- Nothing is changed in existing data by the update itself. When you run the import again with the same export, the days that gain a health status or a pulse alert are updated; all other days stay as they are. Run the preview first.

## v1.7.6.6 — Alerts and Training in the Daily Summary

- The daily summary file of each day has a new section `alerts` with warnings and ratings that Garmin already delivered but the summary did not show: pulse alerts of the day, breathing disruption of the night, the load ratio, two body battery levels (evening and near bedtime) and the stress rating of the day.
- The section `training` was empty before and is now filled: training readiness (score, level, feedback), the training status as text and as number, VO2max and fitness age. If Garmin's answer for a day holds several readiness entries or several devices, the latest one is used.
- `training_load_7d` stays empty for now. The `alerts` values come only from Garmin's own answer for the day; the Garmin export has none of them, so days that exist only in the export stay empty there.
- Existing days get the new values once through the data update (schema update): in the app when you start Sync Garmin (it asks for a backup first), or in the next daily sync if "Migrate data in Daily Sync" is on. Raw files are not changed and no login is needed.
- The six `alerts` values can be asked for in AI queries (MCP). The first start of the MCP server after the update reads all days again, once, and takes longer; the cache notices by itself when the summary files change their schema, nothing to do.
- The new text values are not offered in the dropdowns of the Explorer and the Custom Dashboard.

## v1.7.6.5 — Rebuild of the Daily Values from the Kept Originals

- The app keeps the JSON files of your Garmin export in `garmin_data/bulk/source`. From these files it can now make the daily values in `bulk/aggregates` again, without the export (the ZIP) and without a login. A popup "Rebuild / Preview only / Not now" appears before Sync Garmin starts when days were made by an older version. "Preview only" reports what would change and writes nothing.
- The import now also reads the training readiness score from the export (it was left out before). Days that were imported earlier get it with the rebuild. For now the score is stored in the bulk folder only; the daily files do not show it yet.
- If a day has several readiness entries, the latest of the day is used, whatever order the files are read in.
- No safety copy is made for the rebuild: the original files are not changed and the days can be rebuilt again at any time. The bulk backup follows at the end of the same sync start.
- Please note: an older version of the app does not read the rebuilt daily-values files. The scheduled Daily Sync does not show the popup and does not rebuild.

## v1.7.6.4 — Migration in the Daily Update and Documentation Viewer

- New setting "Migrate data in Daily Sync" (Settings tab, section "Daily Sync"), off by default. When a data update (schema update) is waiting, the daily update then makes a checked safety copy of your archive and migrates by itself, instead of stopping and asking you to open the app. With the setting off nothing changes: the daily update stops with a hint.
- If the safety copy cannot be made, nothing is changed and the daily update stops with a hint. The log names the safety copy and how to put it back (`restore_migration_snapshot.py`, Python needed). Old copies are not deleted by the app.
- If some files are still waiting afterwards, the log says how many; the daily update still counts as done.
- The Documentation button now shows the quick start, the user guide and the app README in a window inside the app. Links to web pages open in your browser. If a file cannot be shown there, it opens in your default program as before.
- Please note: the window shows no pictures and not the project README on GitHub.

## v1.7.6.3 — Migration of the Mixed Archive

- Days that the older import left in a mixed form (export data stored in the folder of the Garmin API data) are now made again from the archived Garmin originals, and the export data stays in the bulk folder. A step in the app asks once before the sync, offers a preview, and makes a safety copy of the daily files, the Garmin answers and the quality log first.
- The daily files in `summary` are now put together field by field: where Garmin's answer for an old day holds a field but leaves it empty, the export fills it (heart rate minimum and maximum, stress average). Before, such an old day showed no value at all.
- A few shown values change for migrated days: the climbed floors follow Garmin's own value, six sleep durations differ by 0.01 hours, and the activity list of days that came from the earlier import is empty instead of wrong (it showed minutes and kilometres a thousand and a hundred times too large).
- The safety copy is a ZIP in `backup/migration`, checked right after it is written. A command line tool puts it back (`restore_migration_snapshot.py`, Python needed). Old copies are not deleted by the app.
- The daily update only points to days that wait for the migration; it never changes your archive.
- Please note: days of the earlier import without an archived Garmin original, and days where the export differs from the stored data, are reported and left unchanged.

## v1.7.6.2.1 — Sturdier Backups

- The backups of the daily files and of the raw Garmin answers now run on the same code as the backup of the bulk folder.
- If a monthly backup file is damaged, nothing is written into it any more: it is left as it is, the new files wait in their month folder, and the log names the damaged file. Before, such a file could silently lose its old content.
- Backup messages now say what kind of error happened, and a file the backup cannot read is counted as an error.
- The archive check also notices a lost original JSON file of the export, and its repair restores it from the backup. If a bulk day file and its original file are lost together, one repair now brings back both.

## v1.7.6.2 — Protection for the Bulk Folder

- The bulk folder (heart-rate series, daily values and the kept files of the Garmin export) is now part of the backup and of the mirror. The first backup happens by itself at the next start of a sync; it can take a while with a large export.
- A mirror container carries the bulk folder along, and the import of a mirror brings it back. Older mirror containers stay readable. The log shows progress while a mirror is made or imported.
- A day that exists only in the export no longer counts as an error when a mirror is imported.
- The archive check finds bulk files that went missing and original export files that are gone; its repair restores them from the backup. A daily file that belongs to a lost bulk file is no longer removed as an orphan.
- Please note: the raw and source backups are unchanged; the next version moves them onto the same code.

## v1.7.6.1 — Daily Values from the Garmin Export in the Bulk Folder

- The daily values of the Garmin export are now stored in the bulk folder as well (`bulk/aggregates`), no longer mixed into the archive of data that came from the Garmin API. The daily files in `summary` are put together from both: what Garmin delivered through the API wins, the export fills the gaps.
- New for AI queries and dashboards: the time per day in the four stress zones (rest, low, medium, high) from the export. The sleep percentages also work for days that exist only in the export.
- The import dialog offers a preview for both parts, the daily values and the heart-rate series.
- Days that exist only in the export are no longer reported as orphaned by the archive check, and the repair can rebuild their summary.
- A day that could not be written is now reported as an error by the sync and by the mirror import instead of being counted as done.
- Please note: the bulk folder is still not part of the backup and the mirror; that follows in the next version.

## v1.7.6 — Heart-Rate Series from the Garmin Export

- The import of the Garmin export can now also read the heart-rate series over the day, not only the daily values. A new dialog lets you choose "Daily values" and/or "Heart-rate series" and shows a preview first.
- The series are stored in their own folder (`bulk`) next to the archive; your existing daily data is not changed. AI queries (MCP) and the dashboards that show the heart-rate curve use the series automatically for days that have none from the sync.
- Please note: this folder is not yet part of the backup and the mirror; the import asks you before it starts.

## v1.7.5.7 — Resting Heart Rate of Imported Days Corrected

- The Garmin export import used to store the 7-day average of the resting heart rate as the value of the day. New imports take the real value of the day.
- Days imported earlier are corrected from your saved Garmin originals: before Sync Garmin starts, a popup names the number of days and asks you to make a backup first. It comes back at every sync until the days are corrected; the scheduled Daily Sync only writes a note to its log.
- AI queries (MCP) show the corrected values after the next sync.

## v1.7.5.6 — Backups Follow Rewritten Days

- When a day is rewritten after its first backup (by a backfill, a mirror import or a repair), its entry in the monthly backup ZIP is now updated too, so "Restore Data" no longer brings back an older version of that day.
- Existing archives are checked at every sync start; outdated backup entries are replaced automatically, once, with nothing to do.

## v1.7.5.x — Statistics and Clearer Tools for AI Queries

- New statistics for AI queries: rolling baselines and normal ranges per health value, anomaly and streak detection, gap detection (now for health data too), and correlations between any two values with an optional day offset, for example "does pollen affect my HRV?".
- AI clients are guided better: short, clear tool descriptions; asking for a raw value that has a processed counterpart (floors, weight, intensity minutes) now points to the right tool; raw queries can be limited to one field; "stress_index" resolves to average stress.

## v1.7.4.x — Export Layer and Reliability

- New "Export Data" panel: export archive data as JSON, CSV or InfluxDB line protocol (for example for Grafana), optionally as part of the daily sync.
- Fixed: "Update Live" ignored the request-delay settings; five Heatmap tabs were too narrow; Export Data never ran in the headless daily sync; the dashboard range setting was ignored in the daily sync.
- An unreadable quality log is now restored from the backup instead of silently starting empty; Force-Refetch now updates the backup ZIP; mirror import rejects paths that point outside the archive.

## v1.7.3.3 – v1.7.3.4 — Security Hardening and Fixes

- Security: the dashboard viewer and the Excel preview now really run with their intended restrictions (file and remote access, pop-ups, plugins, clipboard); the hardening was documented but had never been switched on.
- Fixed: the Sleep dashboard showed "not available" on the mobile home page.
- Automated tests and checks now run on every push; release builds are started by hand.

## v1.7.3.2 — Demo Archive for Trying the MCP Server

- New synthetic demo archive (180 days of fictional health + weather/pollen data) lets anyone try the MCP server's AI querying without a real Garmin account — no setup beyond pointing the app at the downloaded folder.

## v1.7.3 — Background Timer Fills In Gaps From Old Bulk Imports

- Days imported from an older bulk export are missing several optional health metrics (HRV, SpO2, Body Battery, respiration, training status, race predictions, max metrics) — the background timer now fetches these automatically over time, without ever overwriting data the import already had.
- Fixed: the Timer's own Min/Max Interval and Days-per-Run settings fields were not actually being applied.

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
