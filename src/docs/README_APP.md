# Garmin Local Archive — Desktop App v1.6.2.1

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

## Layout overview

The app window is divided into two areas:

**Fixed top area** — always visible regardless of which tab is active:
- Connection indicators (Token / Login / API Access / Data)
- Archive status (fail / recheck / missing / range / coverage / last sync)
- Device table
- Daily Actions: **Daily Sync**, **Mirror**, **Timer**, **Documentation**

**Tab area** — three tabs:
- **Home** — Dashboard viewer (HTML dashboards)
- **Files** — Excel viewer
- **Settings** — all configuration panels

---

## Settings

**Settings tab** (third tab):
- **Email** — your Garmin Connect login email
- **Password** — your Garmin Connect password (stored securely in the Windows Credential Manager, never written to disk as plain text)
- **Data folder** — where to store data (e.g. `C:\Users\YourName\local_archive`)
- **Sync mode** — `recent` for daily use, `range` for a specific period, `auto` for full history (everything since your oldest device — can take hours, **not recommended**, rate limit risk, use Bulk Import instead)
- **Export date range** — used by all dashboards. Leave empty to use the oldest/newest file in your archive automatically
- **Age / Sex** — used by the Health Analysis dashboard for reference ranges
- **Mirror folder** — optional second location for your archive (NAS, USB, external drive). Leave empty to disable. Set once, then use the **Mirror** button to sync.

Click **Save Settings** — settings are remembered between sessions.

---

## Buttons

### Connection & Archive Status

The top section shows two things at once:

**Connection indicators** (Token / Login / API Access / Data) — updated automatically when Sync Data runs. Green = OK, red = failed, grey = not yet tested. No manual test button — the connection is verified automatically before every sync.

**Archive info panel** — populated on startup from your local data, no sync required:

- **Days** — total days tracked in the quality log
- **high / std / fail** — breakdown by quality level (colour-coded). `high` = intraday data present, `std` = full daily data without intraday (typical for older devices or degraded history), `fail` = nothing usable
- **Device table** — one row per device showing date range, days high, days standard, total. Double-click the `unknown` row to assign a name to legacy entries (vívoactive era and similar)
- **Recheck** — days flagged for re-download by the background timer
- **Range** — earliest and latest date in your archive
- **Coverage** — percentage of days present vs. possible days in the date range
- **Last API / Last Bulk** — most recent date imported via live sync or bulk import
- **Source** — total source files archived · files present within the last 180-day window (e.g. `175 days · 180/180d`). The 180-day window reflects Garmin's intraday resolution boundary — days within it can be replayed from source if needed

The panel refreshes automatically after every Sync and Bulk Import.

### Silo-Check
Scans your data silos for inconsistencies the live pipeline does not catch — old gaps, interrupted runs, manual file operations, or import errors.

Click **🔍 Silo-Check** to run. The check is read-only and completes in the background. Results appear in the log:


- **"⚠ N days missing"** — backup copies exist, click to restore automatically
- **"⚠ N days missing, N no backup"** — some days have no backup; a dialog lists them so you can re-fetch manually via Sync Data

The check runs silently in the background at startup and takes a few seconds.

### Export to Mirror
Creates an encrypted backup of your full archive as a single `.gla` container file. The target path is configured under **Mirror target** in Settings. The button opens a dialog with two options: **Export to Mirror** (create or update the backup) and **Import from Mirror** (restore data from an existing container).

Both operations prompt for a password with confirmation. The password is never saved — it must be entered each time. This prevents the scenario where a typo is silently stored and requires manual cleanup in Windows Credential Manager.

The button is greyed out if no mirror target is configured or the target is unreachable. Disabled automatically while a Sync or Context Sync is running.

Import is non-destructive — existing data with higher quality is never overwritten by the container contents.

### Documentation
Opens a dialog with three entries: **Quickstart** (first-time setup), **User Guide** (full feature reference), and **README App** (this document). Files open in your default text editor or viewer.

### Sync Data / Stop
Downloads missing days from Garmin Connect. Watch the log at the bottom for progress. First run may take a while depending on how far back you go.

> **Standard:** Click **Stop** to cancel a running sync immediately.
> **Standalone:** Click **Stop** to cancel — the current day finishes saving before stopping.

**First sync after v1.5.1 upgrade:** If existing raw files have no backup copy yet, a one-time popup appears offering to create backups in the background. This runs independently of the sync — click **Yes** to secure your archive, or **No** to skip. New files are backed up automatically after every sync regardless of this choice.

If there are days with failed or incomplete downloads in the selected sync range, a popup will appear before the sync starts: **"Incomplete records found: X days in the selected range — Refresh now?"** Click **Yes** to re-fetch those days, or **No** to skip them and sync normally.

> **Large archives:** If you have years of Garmin history, start with `range` mode for the last 1–2 years before using `auto`. Downloading everything at once can trigger Garmin rate limiting.

### Import Bulk Export
Imports a Garmin GDPR data export into your local archive — useful for historical data that is no longer available via the API (Garmin degrades intraday data after roughly six months — once gone, the API can't retrieve it).

1. Go to [garmin.com](https://www.garmin.com/en-US/account/datamanagement/exportdata/) → Request Data Export
2. Wait for the email (typically 20–30 minutes), download the ZIP
3. Click **📥 Import Bulk Export** — choose ZIP file or unpacked folder
4. Progress is shown in the log window

Imported days land in `raw/` and `summary/` alongside API data. Days already present with `high` or `standard` quality from the API are skipped — the better source wins. Imported data is marked `source: bulk` in the quality log and never re-fetched automatically.

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
3. **Quality** — re-checks `standard` days where the previous day had intraday data and the retry window (180 days) is still open — worth trying again for a quality upgrade
4. **Fill** — fetches completely missing days between your earliest known date and yesterday
5. **Source Backfill** *(v1.6.0.3)* — if you were running GLA before v1.6.0.2, some historical days may be missing from the source archive. The timer fills this gap automatically, oldest first, within the 180-day window where Garmin still delivers full intraday resolution. Becomes a no-op once complete — runs invisibly in the background.

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

**Intraday data — what the Timeseries dashboard shows**

The Timeseries dashboard renders every data point captured from the API — no aggregation, no downsampling. The number of points per day depends on what Garmin delivered at the time of sync:

| Metric | API resolution | Data points / day |
|---|---|---|
| Heart Rate | ~1 minute | up to 1,440 |
| Stress | ~3 minutes | up to 480 |
| Body Battery | ~15 minutes | up to 96 |
| SpO2 | ~1 hour | up to 24 |
| Respiration | variable | variable |

Days synced within ~135 days of the recording date show full curves. Days beyond that threshold — or days from a GDPR bulk import — contain daily summary values only (`standard` quality). The quality badge in the archive panel shows the breakdown.

### Encrypted Dashboards

Builds all HTML dashboards and encrypts each file with a password (AES-256-GCM). Intended for
transport on USB drives or other removable media — the encrypted file opens in any browser and
decrypts locally without any server or internet connection.

- Click **🔒 Encrypted Dashboards** in Settings → Export
- Enter a password and confirm it — the password is never saved
- All HTML dashboards are built and encrypted automatically
- Mobile variants are not included
- Output is written to `BASE_DIR/encrypted/` — the folder opens automatically
- File names get an `_enc` suffix: e.g. `health_garmin_enc.html`

The encrypted file is self-contained: the password dialog and decryption logic are embedded
directly in the HTML file. No Python, no server, no external asset required to open it.

**Not triggered by Daily Sync** — encrypted export is always manual.

### Daily Sync button

One-click daily workflow. Detects the gap since your last sync, then runs in sequence:

1. Garmin Sync — downloads missing days
2. Context Sync — updates weather and pollen data
3. Create All — rebuilds all dashboards

If the gap is larger than 7 days a confirmation dialog appears before starting. The button is disabled while running. Progress is shown in the log at the bottom.

### Dashboard tab

The **Dashboard** tab (first tab) shows your HTML dashboards directly inside the app — no browser needed. The **Health Analysis** dashboard loads by default on startup.

Use the dropdown at the top to switch between all HTML dashboards in `BASE_DIR/dashboards/`. The view is fully interactive — zoom, hover, and filter work exactly as in a browser.

### Files tab

The **Files** tab (second tab) shows your Excel dashboards directly inside the app — no Excel required. The **Daily Overview** spreadsheet loads by default. Switch between files using the left dropdown and between sheets using the right dropdown (appears automatically for multi-sheet files). Chart sheets are hidden — only data sheets are shown.

**Open File** opens the selected file in whatever your system has registered for `.xlsx` (Excel, LibreOffice, WPS).

The file list refreshes automatically after every dashboard build and on every tab switch — new files appear without restarting the app.

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

## Daily Sync — automated daily operation

`daily_update` runs the full daily workflow headlessly — no GUI, no manual interaction. Configure the app once, then let `daily_update` handle the rest automatically via Windows Task Scheduler.

**What it does on each run:**
1. Checks the archive for gaps — heals gaps up to 7 days automatically
2. Syncs Garmin data for the missing period
3. Syncs context data (weather, pollen, air quality)
4. Rebuilds all dashboards
5. Closes the console window if everything completed cleanly

Gaps larger than 7 days trigger a hard stop — open the app and sync manually first.

**Entry point per version:**

| Version | Entry point |
|---|---|
| Standalone | `daily_update.exe` — double-click or Task Scheduler |
| Standard EXE | `Starte_Daily_Sync.bat` — double-click or Task Scheduler |
| Scripts only | `python scheduler/daily_update.py` |

**Task Scheduler setup:**

A ready-to-import XML template (`daily_update_task.xml`) ships in `info/`. Import it once into Windows Task Scheduler. Recommended settings:
- Run daily in the morning
- Enable "Run task as soon as possible after a scheduled start is missed" — ensures the sync runs after waking from sleep
- Disable "Restart on failure" — prevents flooding `log/daily/` with error files

**Console behaviour:**

| State | Behaviour |
|---|---|
| All OK | Console closes automatically |
| Update available | Stays open — yellow notice |
| Error | Stays open — red notice, check `garmin_data/log/daily/` |
| Migration required | Stays open — open the app first |
| Settings missing | Stays open — open the app and save settings first |

**Prerequisite:** The app must be configured at least once (email, password, folder, location saved) before `daily_update` can run. Running it before setup results in a hard stop with a clear message.

**After updating the app:** A fresh build occasionally causes Garmin to reject the saved token on the next login, sometimes paired with a step-up verification (MFA) — `daily_update` cannot resolve this headlessly and will fail visibly. If a scheduled run fails right after an update, open the GUI once and complete a normal login (entering the MFA code if prompted). This re-establishes a valid token, and the next scheduled run will succeed normally.

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

**First login (no saved token)** — the app shows a confirmation dialog before starting the SSO login. This is intentional — garminconnect sends several requests to Garmin during login and may trigger rate limiting if repeated too quickly. An encryption key is generated automatically in the background (no password required). Click **Proceed** to continue or **Cancel** to abort.

**Token expired (sync starts slowly)** — If the log shows repeated `401` errors or `DI token refresh failed` at the start of a sync, the saved token has expired. The app recovers utomatically — do not cancel. The re-login sequence takes 3–4 minutes. Wait for `✓ Login successful` before assuming something is wrong.

> **Standalone:** If login fails due to captcha or browser verification, download the Standard version, install Python, and run `garmin_collector.py` once in a terminal to complete verification. After that the Standalone version will work normally using the saved session.

**Log shows errors but no data** — check your email/password in Settings and make sure the data folder path is valid and writable.

**Password not saved between sessions** — click Save Settings after entering your password.

> **Standard:** If keyring is unavailable: `pip install keyring`.

**Stress / Body Battery missing from Excel or dashboard** — run `regenerate_summaries.py` once to rebuild all summary files from raw data.

> **Standalone:** Use the **🔍 Silo-Check** button (Settings tab → Data Management) to detect missing summaries, then click **🔧 Repair** to rebuild them automatically.

**Background timer shows days as `standard` instead of `high`** — this is expected behaviour. `standard` means the API returned full daily data but no intraday detail (heart rate curve, stress curve, etc.). This happens for older dates where Garmin has permanently degraded intraday resolution, or for device eras that never produced intraday data. The timer retries `standard` days only if the previous day had intraday data and the 180-day retry window is still open — after that the label is accepted as final and those days are never touched again.

**Antivirus flags the EXE** — this is a false positive common with PyInstaller-built executables. The source code is fully open at github.com/Wewoc/Garmin_Local_Archive. You can whitelist the file in your antivirus settings or build the EXE yourself from source.
