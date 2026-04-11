# Garmin Local Archive — Desktop App (Standalone) v1.3.4

## What this is

`Garmin_Local_Archive_Standalone.exe` is a fully self-contained desktop app.
No Python, no terminal, no dependencies — everything is built in.

Just extract the ZIP and double-click.

---

## First-time setup

### Step 1 — Extract the ZIP

Download `Garmin_Local_Archive_Standalone.zip` and extract it. The folder contains:

```
Garmin_Local_Archive_Standalone.exe     ← double-click to launch
info/                                   ← documentation (optional)
```

That's it. No `scripts/` folder needed — everything is embedded inside the `.exe`.

### Step 2 — Run the app

Double-click `Garmin_Local_Archive_Standalone.exe`.

> Windows may show a security warning ("Windows protected your PC"). Click **More info** → **Run anyway**. This happens because the .exe is not code-signed. The source code is open at github.com/Wewoc/Garmin_Local_Archive — you can review it before running.

> The first launch may take a few seconds longer than usual. Windows Defender and other antivirus software sometimes scan self-contained executables on first run. This is normal.

### Step 3 — Fill in your settings

Left panel:
- **Email** — your Garmin Connect login email
- **Password** — your Garmin Connect password (stored securely in the Windows Credential Manager, never written to disk as plain text)
- **Data folder** — where to store data (e.g. `C:\Users\YourName\garmin_data`)
- **Sync mode** — `recent` for daily use, `range` for a specific period, `auto` for full history
- **Export date range** — used by all export scripts. Leave empty to use the oldest/newest file in your archive automatically
- **Age / Sex** — used by the Analysis Dashboard for reference ranges

Click **Save Settings** — settings are remembered between sessions.

---

## Buttons

### Connection & Archive Status

The top section shows two things at once:

**Connection indicators** (Token / Login / API Access / Data) — updated automatically when Sync Data runs. Green = OK, red = failed, grey = not yet tested. No manual test button — the connection is verified automatically before every sync.

**Archive info panel** — populated on startup from your local data, no sync required:

- **Days** — total days tracked in the quality log
- **high / med / low / fail** — breakdown by quality level (colour-coded)
- **Recheck** — days flagged for re-download by the background timer
- **Range** — earliest and latest date in your archive
- **Coverage** — percentage of days present vs. possible days in the date range
- **Last API / Last Bulk** — most recent date imported via live sync or bulk import

The panel refreshes automatically after every Sync and Bulk Import.

### Clean Archive
Removes all data files that predate your `first_day` — the earliest valid day detected in your Garmin account.

Click the button to open a preview popup showing exactly which files will be deleted and how many quality log entries will be removed. Nothing is deleted until you confirm with **Delete**. Click **Cancel** to close without changes.

Use this to clean up files created accidentally by entering a date that is too early in range mode. The `first_day` anchor is detected automatically on first run and stored in `log/quality_log.json`. If the popup reports "nothing to clean", your archive is already consistent.

### Sync Data / Stop
Downloads missing days from Garmin Connect. Watch the log at the bottom for progress.
First run may take a while depending on how far back you go.
Click **Stop** to cancel a running sync — the current day finishes saving before stopping.

If there are days with failed or incomplete downloads in the selected sync range, a popup will appear before the sync starts: **"Incomplete records found: X days in the selected range — Refresh now?"** Click **Yes** to re-fetch those days, or **No** to skip them and sync normally.

> **Large archives:** If you have years of Garmin history, start with `range` mode for the last 1–2 years before using `auto`. Downloading everything at once can trigger Garmin rate limiting.

### Import Bulk Export
Imports a Garmin GDPR data export into your local archive — useful for historical data that is no longer available via the API (Garmin degrades intraday data after ~1–2 years).

1. Go to [garmin.com](https://www.garmin.com/en-US/account/datamanagement/exportdata/) → Request Data Export
2. Wait for the email (typically 20–30 minutes), download the ZIP
3. Click **📥 Import Bulk Export** — choose ZIP file or unpacked folder
4. Progress is shown in the log window

Imported days land in `raw/` and `summary/` alongside API data. Days already present with `high` or `medium` quality from the API are skipped — the better source wins. Imported data is marked `source: bulk` in the quality log and never re-fetched automatically.

### Background Timer
Automatically repairs and fills your archive in the background while the app is open — no manual intervention needed.

Click the **⏱ Timer: Off** button to start. The button turns green and shows a live countdown to the next run. While a sync is running it shows **"Syncing · N offen"**.

The timer alternates between two modes each run:
- **Repair** — re-fetches days listed in `log/failed_days.json` (API errors and incomplete files)
- **Fill** — fetches completely missing days between your earliest local file and yesterday

When both queues are empty the timer stops automatically and logs "Archive complete".

**Settings** (shown next to the button):

| Field | Default | Description |
|---|---|---|
| Min. Interval (min) | 5 | Shortest wait between runs |
| Max. Interval (min) | 30 | Longest wait between runs |
| Min. Days per Run | 3 | Fewest days fetched per run |
| Max. Days per Run | 10 | Most days fetched per run |

The timer runs its own connection test before the first sync. If successful, the connection indicators in the top panel turn green. Clicking the timer button while a sync is running stops the current download immediately.

### Daily Overview
Exports `garmin_export.xlsx` — one row per day, colour-coded by category.
Reads from `summary/`.

### Timeseries Excel
Exports `garmin_timeseries.xlsx` — full intraday data + charts per metric.
Reads from `raw/`. Uses the Export Date Range from settings.

### Timeseries Dashboard
Generates `garmin_dashboard.html` — open in any browser.
Reads from `raw/`. Uses the Export Date Range from settings.

### Analysis Dashboard
Generates `garmin_analysis.html` + `garmin_analysis.json`.
Shows daily values vs your 90-day baseline vs age/fitness reference ranges.
Reads from `summary/`. The JSON file can be uploaded to Ollama / Open WebUI for AI-assisted interpretation.

### Log: Simple / Log: Detailed
Toggles the log output level in the GUI. **Simple** shows only key steps (default). **Detailed** shows every API call — useful for diagnosing connection issues or Garmin API changes.

If you toggle while a sync is running, a yellow notice appears above the button: **"Takes effect on next sync"**. The current sync continues unchanged and the notice disappears automatically when the next sync starts.

Session log files (in `log/recent/` and `log/fail/`) always record at full detail regardless of this toggle.

### Open Data Folder
Opens your data folder in Windows Explorer.

### Open Last HTML
Opens the most recently generated HTML file in your default browser.

### Copy Last Error Log
Copies the contents of the most recent error log from `log/fail/` to your clipboard — ready to paste into a GitHub issue or support chat. Since the Standalone version has no terminal, this is the easiest way to retrieve diagnostic information when something goes wrong. If no error logs exist, a message appears in the log area instead.

---

## Session logs

Every sync automatically writes a detailed log to your data folder:

```
garmin_data/
└── log/
    ├── recent/    – last 30 sync sessions (always full detail)
    └── fail/      – sessions with errors or incomplete days (kept permanently)
```

Manual sync sessions are named `garmin_YYYY-MM-DD_HHMMSS.log`. Background timer sessions are named `garmin_background_YYYY-MM-DD_HHMMSS.log` — the prefix makes the source immediately identifiable in `log/fail/`.

These are plain text files — open them in any text editor if you need to diagnose a problem.

---

## Password security

Your password is stored in the **Windows Credential Manager** (the same secure vault used by browsers and Windows itself). It is:

- Encrypted by Windows using your login credentials
- Never written to any file on disk
- Only readable by your Windows user account

To remove the stored password: open Windows Credential Manager → Windows Credentials → find `GarminLocalArchive` → delete.

---

## Settings file

All settings except the password are saved to:

```
C:\Users\YourName\.garmin_archive_settings.json
```

Delete this file to reset all settings to defaults. The password must be cleared separately via the Windows Credential Manager.

---

## Troubleshooting

**App doesn't start / disappears immediately** — open a terminal (`cmd`), navigate to the folder, and run the `.exe` directly to see the error output:

```
cd C:\path\to\folder
Garmin_Local_Archive_Standalone.exe
```

**Login fails** — if Garmin requires MFA, the app will show a code input popup automatically. Enter the code from your Garmin app or authenticator. If login still fails due to captcha or browser verification, download the Standard version (`Garmin_Local_Archive.zip`), install Python, and run `garmin_collector.py` once in a terminal to complete verification. After that the Standalone version will work normally using the saved session.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid and writable.

**Password not saved between sessions** — click Save Settings after entering your password.

**Stress / Body Battery missing from Excel or dashboard** — click Analysis Dashboard once — this regenerates summaries from raw data automatically. Alternatively use the Standard version and run `regenerate_summaries.py`.

**Antivirus flags the EXE** — this is a false positive common with PyInstaller-built executables. The source code is fully open at github.com/Wewoc/Garmin_Local_Archive. You can whitelist the file in your antivirus settings or build the EXE yourself from source.

---

## Differences from the Standard version

| | Standalone | Standard |
|---|---|---|
| Python required | No | Yes |
| `scripts/` folder needed | No | Yes |
| First launch speed | Slightly slower | Normal |
| Stop button behaviour | Stops after current day | Immediate process kill |
| Recommended for | Anyone | Users who already have Python |
