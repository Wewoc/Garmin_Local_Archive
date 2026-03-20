# Garmin Local Archive — Desktop App

## What this is

`GarminArchive.exe` is a desktop launcher for all Garmin Archive scripts.
No terminal, no text editor — configure everything in the UI and click to run.

---

## First-time setup

### Step 1 — Extract the ZIP

Download `GarminArchive.zip` and extract it. The folder must contain:

```
GarminArchive.exe     ← double-click to launch
scripts/              ← all .py files — must stay next to the .exe
info/                 ← documentation (optional)
```

> `scripts/` is required. Without it no buttons will work.

### Step 2 — Install Python and dependencies

Python must be installed on the machine — the app calls Python scripts in the background.

1. Download Python 3.10 or newer from https://www.python.org/downloads/
2. Run the installer — tick **"Add Python to PATH"**
3. Open a terminal and run:

```bash
pip install garminconnect openpyxl keyring
```

### Step 3 — Run the app

Double-click `GarminArchive.exe`.

> Windows may show a security warning ("Windows protected your PC"). Click **More info** → **Run anyway**. This happens because the .exe is not code-signed. The source code is open — you can review it before running.

### Step 4 — Fill in your settings

Left panel:
- **Email** — your Garmin Connect login email
- **Password** — your Garmin Connect password (stored securely in the Windows Credential Manager, never written to disk as plain text)
- **Data folder** — where to store data (e.g. `C:\Users\YourName\garmin_data`)
- **Sync mode** — `recent` for daily use, `range` for a specific period, `auto` for full history
- **Export date range** — used by all export scripts (leave empty for all available data)
- **Age / Sex** — used by the Analysis Dashboard for reference ranges

Click **Save Settings** — settings are remembered between sessions. Your password is saved to the Windows Credential Manager, not to any file.

---

## Buttons

### Sync Data / Stop
Downloads missing days from Garmin Connect. Watch the log at the bottom for progress.
First run may take a while depending on how far back you go.
Click **Stop** to cancel a running sync at any time.

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

To remove the stored password: open Windows Credential Manager → Windows Credentials → look for `GarminLocalArchive` and delete it.

---

## Settings file

All settings except the password are saved to:

```
C:\Users\YourName\.garmin_archive_settings.json
```

Delete this file to reset all settings to defaults. The password must be cleared separately via the Windows Credential Manager.

---

## Building from source

If you want to rebuild the `.exe` after modifying scripts:

1. Place `build.py` and all `garmin_*.py` scripts in the same folder
2. Run:

```bash
python build.py
```

`build.py` will automatically:
- Install PyInstaller and keyring if missing
- Move scripts to `scripts/` and docs to `info/`
- Build `GarminArchive.exe`
- Create `GarminArchive.zip` ready for distribution

---

## Troubleshooting

**App doesn't start** — make sure the `scripts/` folder is in the same folder as the `.exe` and contains all `garmin_*.py` files.

**Script not found error** — a `garmin_*.py` file is missing from `scripts/`. Check all files are present.

**Login fails** — run `garmin_collector.py` directly in a terminal once to complete any captcha verification, then use the app normally.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid.

**Password not saved between sessions** — click Save Settings after entering your password. If keyring is unavailable, install it: `pip install keyring`.

**Stress / Body Battery missing from Excel or dashboard** — run `regenerate_summaries.py` once to rebuild all summary files from raw data.

**Second window opens on launch** — only double-click the `.exe`, do not run it from VS Code or a terminal at the same time.
