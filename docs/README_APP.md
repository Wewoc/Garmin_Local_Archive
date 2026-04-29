# Garmin Local Archive — Desktop App v1.4.8

Garmin Connect is still required — the app pulls data from there via API. This tool does not replace Connect, the Garmin app, or your device sync.

**Two versions are available:**

| | Standard | Standalone |
|---|---|---|
| Python required | Yes | No |
| `scripts/` folder needed | Yes | No |
| First launch speed | Normal | Slightly slower (first run only) |
| Stop button behaviour | Immediate process kill | Stops after current day finishes |
| Recommended for | Users who already have Python | Anyone |

---

## Project status & disclaimer

> GNU General Public License v3.0 — provided as-is.

- **Not an official Garmin product:** This tool is not affiliated with, endorsed, or supported by Garmin.
- **Unofficial API:** Garmin Local Archive uses Garmin's unofficial API — it may change or break without notice.
- **Not medical advice:** All health metrics, reference ranges, and dashboard data are for personal informational use only — not a substitute for medical advice.
- **Context data:** Weather data is provided by Open-Meteo and Brightsky (DWD), pollen data by Open-Meteo — accuracy and availability are not guaranteed.
- **Early stage:** Core functionality is stable. APIs and internal structure may still change.
- **No guaranteed support:** Development happens when time and interest allow.
- **Use at your own risk:** I am not responsible for data loss or Garmin account issues.
- **Feedback welcome:** If something feels off — logic, structure, results — open an issue.

---

## First-time setup

> Windows may show a security warning ("Windows protected your PC") for either version. Click **More info** → **Run anyway**. This happens because the .exe is not code-signed. The source code is open at github.com/Wewoc/Garmin_Local_Archive — you can review it before running.

### Standard version (`Garmin_Local_Archive.zip`)

**Step 1 — Extract the ZIP**

Download and extract. The folder must contain:

```
Garmin_Local_Archive.exe     ← double-click to launch
scripts/                     ← all .py files — must stay next to the .exe
info/                        ← documentation (optional)
```

> `scripts/` is required. Without it no buttons will work.

**Step 2 — Install Python and dependencies**

1. Download Python 3.10 or newer from https://www.python.org/downloads/
2. Run the installer — tick **"Add Python to PATH"**
3. Open a terminal and run:

```bash
pip install garminconnect openpyxl keyring
```

**Step 3 — Run the app**

Double-click `Garmin_Local_Archive.exe`.

---

### Standalone version (`Garmin_Local_Archive_Standalone.zip`)

**Step 1 — Extract the ZIP**

Download and extract. The folder contains:

```
Garmin_Local_Archive_Standalone.exe     ← double-click to launch
info/                                   ← documentation (optional)
```

No `scripts/` folder needed — everything is embedded inside the `.exe`.

**Step 2 — Run the app**

Double-click `Garmin_Local_Archive_Standalone.exe`.

> The first launch may take a few seconds longer than usual. Windows Defender and other antivirus software sometimes scan self-contained executables on first run. This is normal.

---

## Settings

Left panel:
- **Email** — your Garmin Connect login email
- **Password** — your Garmin Connect password (stored securely in the Windows Credential Manager, never written to disk as plain text)
- **Data folder** — where to store data (e.g. `C:\Users\YourName\local_archive`)
- **Sync mode** — `recent` for daily use, `range` for a specific period, `auto` for full history (everything since your oldest device — can take hours, **not recommended**, rate limit risk, use Bulk Import instead)
- **Export date range** — used by all dashboards. Leave empty to use the oldest/newest file in your archive automatically
- **Age / Sex** — used by the Health Analysis dashboard for reference ranges

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
Downloads missing days from Garmin Connect. Watch the log at the bottom for progress. First run may take a while depending on how far back you go.

> **Standard:** Click **Stop** to cancel a running sync immediately.
> **Standalone:** Click **Stop** to cancel — the current day finishes saving before stopping.

If there are days with failed or incomplete downloads in the selected sync range, a popup will appear before the sync starts: **"Incomplete records found: X days in the selected range — Refresh now?"** Click **Yes** to re-fetch those days, or **No** to skip them and sync normally.

> **Large archives:** If you have years of Garmin history, start with `range` mode for the last 1–2 years before using `auto`. Downloading everything at once can trigger Garmin rate limiting.

### Import Bulk Export
Imports a Garmin GDPR data export into your local archive — useful for historical data that is no longer available via the API (Garmin degrades intraday data in stages: full resolution for ~6 months, reduced detail up to ~2.5 years, summaries only beyond that).

1. Go to [garmin.com](https://www.garmin.com/en-US/account/datamanagement/exportdata/) → Request Data Export
2. Wait for the email (typically 20–30 minutes), download the ZIP
3. Click **📥 Import Bulk Export** — choose ZIP file or unpacked folder
4. Progress is shown in the log window

Imported days land in `raw/` and `summary/` alongside API data. Days already present with `high` or `medium` quality from the API are skipped — the better source wins. Imported data is marked `source: bulk` in the quality log and never re-fetched automatically.

### Sync Context / CSV

Downloads weather and pollen data for your full archive date range — free, no account required. Weather data is fetched from [Open-Meteo](https://open-meteo.com/) and [Brightsky (DWD)](https://brightsky.dev/), pollen data from Open-Meteo Air Quality. This data is used by the **Health + Context** and **Sleep & Recovery** dashboards to correlate Garmin metrics with environmental conditions.

**Setting your location:** Settings → CONTEXT → paste a Google Maps URL → click **📍 Set Location**. The app extracts latitude and longitude automatically. To get a URL: open Google Maps, navigate to your location, and copy the URL from the address bar.

**CSV button:** Opens `local_config.csv` directly in Excel. This file lets you define different coordinates for specific date ranges — useful if you travel or have relocated. It is created automatically on first Sync Context. For a fixed home location, the Settings entry is sufficient.

### Background Timer
Automatically repairs and fills your archive in the background while the app is open — no manual intervention needed.

Click the **⏱ Timer: Off** button to start. The button turns green and shows a live countdown to the next run. While a sync is running it shows **"Syncing · N offen"**.

The timer works through a priority queue each run:

1. **Bulk Recheck** *(priority)* — if you have imported a Garmin GDPR export, the timer first upgrades those days via the live API. Garmin keeps full intraday resolution available for approximately 6 months — bulk-imported days within that window are re-fetched oldest first before the high-resolution data is permanently gone. Runs exclusively until all candidates are resolved.
2. **Repair** — re-fetches days where the API call itself failed (no file created)
3. **Quality** — re-checks days with poor data quality (`low`)
4. **Fill** — fetches completely missing days between your earliest known date and yesterday

When all queues are empty the timer stops automatically and logs "Archive complete".

**Settings** (shown next to the button):

| Field | Default | Description |
|---|---|---|
| Min. Interval (min) | 5 | Shortest wait between runs |
| Max. Interval (min) | 30 | Longest wait between runs |
| Min. Days per Run | 3 | Fewest days fetched per run |
| Max. Days per Run | 10 | Most days fetched per run |

The timer runs its own connection test before the first sync. If successful, the connection indicators in the top panel turn green. Clicking the timer button while a sync is running stops the current download immediately.

### Berichte erstellen
Opens a popup with all available dashboards and their output formats. Select any combination of dashboards and formats, then click **Erstellen**.

| Dashboard | HTML | Mobile HTML | Excel | JSON |
|---|---|---|---|---|
| Timeseries | ✓ | — | ✓ | — |
| Health Analysis | ✓ | ✓ | — | ✓ |
| Daily Overview | — | — | ✓ | — |
| Health + Context | ✓ | — | ✓ | — |
| Sleep & Recovery | ✓ | — | — | — |

Output is written to `BASE_DIR/dashboards/`. The folder opens automatically after a successful build.

The **Health Analysis JSON** includes a ready-to-use Markdown start prompt (`health_garmin_prompt.md`) for Open WebUI / Ollama — load it as the system prompt for AI-assisted interpretation.

The **Health Analysis Mobile HTML** is optimised for landscape phone viewing — all metrics on one scrollable page, global range dropdown (calendar weeks, months, fixed ranges) controls all charts at once. Copy it to OneDrive or Google Drive to open on your phone.

The **Sleep & Recovery** dashboard shows HRV, Body Battery, and Sleep duration alongside sleep phase composition (Deep / Light / REM / Awake as %) and weather/pollen context. Tab 1 covers the full date range. Tab 2 shows intraday detail for any selected day.

> Reference ranges (Health Analysis) are based on published guidelines (AHA, ACSM, Garmin/Firstbeat) — informational only, not medical advice.
> Dashboard values from consumer wearables are indicative only — not medical-grade.

### Log: Simple / Log: Detailed
Toggles the log output level in the GUI. **Simple** shows only key steps (default). **Detailed** shows every API call — useful for diagnosing connection issues or Garmin API changes.

If you toggle while a sync is running, a yellow notice appears above the button: **"Takes effect on next sync"**. The current sync continues unchanged and the notice disappears automatically when the next sync starts.

Session log files (in `log/recent/` and `log/fail/`) always record at full detail regardless of this toggle.

### Open Data Folder
Opens your data folder in Windows Explorer.

### Copy Last Error Log
Copies the contents of the most recent error log from `log/fail/` to your clipboard — ready to paste into a GitHub issue or support chat.

> **Standalone:** Since there is no terminal, this is the primary way to retrieve diagnostic information when something goes wrong.

If no error logs exist, a message appears in the log area instead.

---

## Session logs

Every sync automatically writes a detailed log to your data folder:

```
local_archive/
  garmin_data/
    └── log/
       ├── recent/    – last 30 sync sessions (always full detail)
       └── fail/      – sessions with errors or incomplete days (kept permanently)
```

Manual sync sessions are named `garmin_YYYY-MM-DD_HHMMSS.log`. Background timer sessions are named `garmin_background_YYYY-MM-DD_HHMMSS.log`.

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

## Building from source

> **Standard version only.**

To rebuild after modifying scripts:

```bash
python build.py
```

`build.py` will automatically install PyInstaller if missing, move scripts to `scripts/` and docs to `info/`, build the EXE, and create a ZIP ready for distribution.

To build the Standalone version:

```bash
python build_standalone.py
```

---

## Troubleshooting

**App doesn't start**

> **Standard:** Make sure the `scripts/` folder is in the same folder as the `.exe` and contains all required files.
> **Standalone:** Open your data folder in Windows Explorer and navigate to `garmin_data\log\fail\`. Open the most recent `.log` file in Notepad — it contains the full error output. If the app never started and no data folder exists yet, use the **Copy Last Error Log** button if the app partially loaded, or re-run from the Standard version with Python to see terminal output.

**Login fails** — if Garmin requires MFA, the app will show a code input popup automatically. Enter the code from your Garmin app or authenticator.

> **Standalone:** If login fails due to captcha or browser verification, download the Standard version, install Python, and run `garmin_collector.py` once in a terminal to complete verification. After that the Standalone version will work normally using the saved session.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid and writable.

**Password not saved between sessions** — click Save Settings after entering your password.

> **Standard:** If keyring is unavailable: `pip install keyring`.

**Stress / Body Battery missing from Excel or dashboard** — run `regenerate_summaries.py` once to rebuild all summary files from raw data.

> **Standalone:** Click the Analysis Dashboard once — this regenerates summaries from raw data automatically.

**Background timer flags days as `low` after fetching them** — this is expected behaviour. For old dates (typically before 2022), Garmin returns little or no data via the API — either because intraday data has been degraded over time, or because the watch was not worn on those days. A day with no device produces a null response from Garmin and is not included in the GDPR export — `low` is the correct assessment. The timer will retry up to 3 times, then stop automatically and never touch those days again.

**Antivirus flags the EXE** — this is a false positive common with PyInstaller-built executables. The source code is fully open at github.com/Wewoc/Garmin_Local_Archive. You can whitelist the file in your antivirus settings or build the EXE yourself from source.
