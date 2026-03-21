# Garmin Local Archive — Desktop App (Standalone)

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

> Windows may show a security warning ("Windows protected your PC"). Click **More info** → **Run anyway**. This happens because the .exe is not code-signed. The source code is open at github.com/Wewoc/garmin-local-archive — you can review it before running.

> The first launch may take a few seconds longer than usual. Windows Defender and other antivirus software sometimes scan self-contained executables on first run. This is normal.

### Step 3 — Fill in your settings

Left panel:
- **Email** — your Garmin Connect login email
- **Password** — your Garmin Connect password (stored securely in the Windows Credential Manager, never written to disk as plain text)
- **Data folder** — where to store data (e.g. `C:\Users\YourName\garmin_data`)
- **Sync mode** — `recent` for daily use, `range` for a specific period, `auto` for full history
- **Export date range** — used by all export scripts (leave empty for all available data)
- **Age / Sex** — used by the Analysis Dashboard for reference ranges

Click **Save Settings** — settings are remembered between sessions.

---

## Buttons

### Test Connection
Tests the connection to Garmin Connect. Shows three indicators:

- **Login** — credentials valid, session established
- **API Access** — Garmin API is reachable and responding
- **Data** — data endpoint returns results

Each indicator turns green on success or red on failure. The button itself turns green if all three pass, red if any fail.

The test also runs automatically the first time you click Sync Data. After a successful test the result is remembered for the session — subsequent syncs start immediately without re-testing. The test resets when you restart the app.

### Sync Data / Stop
Downloads missing days from Garmin Connect. Watch the log at the bottom for progress.
First run may take a while depending on how far back you go.
Click **Stop** to cancel a running sync — the current day finishes saving before stopping.

> **Large archives:** If you have years of Garmin history, start with `range` mode for the last 1–2 years before using `auto`. Downloading everything at once can trigger Garmin rate limiting.

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
Toggles the log output level. **Simple** shows only key steps (default). **Detailed** shows every API call — useful for diagnosing connection issues or Garmin API changes.

If a sync is running when you toggle, it stops automatically and restarts with the new log level. Already downloaded days are not re-fetched.

### Open Data Folder
Opens your data folder in Windows Explorer.

### Open Last HTML
Opens the most recently generated HTML file in your default browser.

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

**Login fails** — Garmin sometimes requires browser-based MFA on first login or after long inactivity. If this happens, download the Standard version (`Garmin_Local_Archive.zip`), install Python, and run `garmin_collector.py` once in a terminal to complete verification. After that the Standalone version will work normally using the saved session.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid and writable.

**Password not saved between sessions** — click Save Settings after entering your password.

**Stress / Body Battery missing from Excel or dashboard** — click Analysis Dashboard once — this regenerates summaries from raw data automatically. Alternatively use the Standard version and run `regenerate_summaries.py`.

**Antivirus flags the EXE** — this is a false positive common with PyInstaller-built executables. The source code is fully open at github.com/Wewoc/garmin-local-archive. You can whitelist the file in your antivirus settings or build the EXE yourself from source.

---

## Differences from the Standard version

| | Standalone | Standard |
|---|---|---|
| Python required | No | Yes |
| `scripts/` folder needed | No | Yes |
| First launch speed | Slightly slower | Normal |
| Stop button behaviour | Stops after current day | Immediate process kill |
| Recommended for | Anyone | Users who already have Python |
