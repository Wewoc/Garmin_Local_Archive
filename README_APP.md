# Garmin Local Archive — Desktop App (Standard)

## What this is

`Garmin_Local_Archive.exe` is a desktop launcher for all Garmin Local Archive scripts.
No terminal, no text editor — configure everything in the UI and click to run.

**This version requires Python to be installed on your machine.**
If you don't have Python or don't want to install it, use the Standalone version instead —
see `README_APP_Standalone.md`.

---

## First-time setup

### Step 1 — Extract the ZIP

Download `Garmin_Local_Archive.zip` and extract it. The folder must contain:

```
Garmin_Local_Archive.exe     ← double-click to launch
scripts/                     ← all .py files — must stay next to the .exe
info/                        ← documentation (optional)
```

> `scripts/` is required. Without it no buttons will work.

### Step 2 — Install Python and dependencies

1. Download Python 3.10 or newer from https://www.python.org/downloads/
2. Run the installer — tick **"Add Python to PATH"**
3. Open a terminal and run:

```bash
pip install garminconnect openpyxl keyring
```

### Step 3 — Run the app

Double-click `Garmin_Local_Archive.exe`.

> Windows may show a security warning ("Windows protected your PC"). Click **More info** → **Run anyway**. This happens because the .exe is not code-signed. The source code is open — you can review it before running.

### Step 4 — Fill in your settings

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
Click **Stop** to cancel a running sync at any time.

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

## Building from source

To rebuild after modifying scripts:

1. Place `build.py`, `build_standalone.py`, and all `garmin_*.py` scripts in the same folder
2. Run:

```bash
python build.py
```

`build.py` will automatically:
- Install PyInstaller and keyring if missing
- Move scripts to `scripts/` and docs to `info/`
- Build `Garmin_Local_Archive.exe`
- Create `Garmin_Local_Archive.zip` ready for distribution

To build the Standalone version instead:

```bash
python build_standalone.py
```

---

## Troubleshooting

**App doesn't start** — make sure the `scripts/` folder is in the same folder as the `.exe` and contains all `garmin_*.py` files.

**Script not found error** — a `garmin_*.py` file is missing from `scripts/`. Check all files are present.

**Login fails** — run `garmin_collector.py` directly in a terminal once to complete any captcha or MFA verification, then use the app normally.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid.

**Password not saved between sessions** — click Save Settings after entering your password. If keyring is unavailable, install it: `pip install keyring`.

**Stress / Body Battery missing from Excel or dashboard** — run `regenerate_summaries.py` once to rebuild all summary files from raw data.
