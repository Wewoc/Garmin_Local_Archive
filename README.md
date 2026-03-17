# Garmin Local Archive

> This project is provided as-is under the GNU General Public License v3.0, without warranty of any kind. Use at your own risk. No support, maintenance, or liability is implied or offered.

Two scripts to archive and analyse your Garmin Connect data locally.
No cloud services, no third parties — everything runs on your own machine.

---

## Overview

```
garmin_data/
├── raw/        – full API dumps (~500 KB/day), kept as archive
└── summary/    – compact daily JSONs (~2 KB/day) → for Ollama / Open WebUI
```

| Script                  | Purpose                                        |
|-------------------------|------------------------------------------------|
| `garmin_collector.py`   | Fetch data from Garmin Connect and save locally |
| `garmin_to_excel.py`    | Export summary data as a formatted Excel file   |

---

## Requirements

### Python

Both scripts require Python 3.10 or newer. Check if installed:

```bash
python --version
```

If not installed: https://www.python.org/downloads/

> **Windows:** tick **"Add Python to PATH"** during installation, otherwise `python` won't be available in the terminal.

### Libraries

```bash
pip install garminconnect openpyxl
```

---

## garmin_collector.py

### What it does

- Connects to Garmin Connect
- Checks which days are missing locally (handles multiple folder layouts and legacy naming)
- Downloads missing days automatically (backfill + daily sync)
- Saves two files per day: full raw dump and compact summary

### Configuration (top of script)

| Variable           | Description                                      | Default            |
|--------------------|--------------------------------------------------|--------------------|
| `GARMIN_EMAIL`     | Your Garmin Connect login email                  | —                  |
| `GARMIN_PASSWORD`  | Your Garmin Connect password                     | —                  |
| `BASE_DIR`         | Root folder for all data                         | `~/garmin_data`    |
| `SYNC_START_DATE`  | Earliest date to backfill, e.g. `"2022-01-01"`  | 90-day fallback    |
| `REQUEST_DELAY`    | Pause between API requests (seconds)             | `1.5`              |

All settings can also be passed as environment variables instead of editing the script.

### Run manually

```bash
python garmin_collector.py
```

### Automate on login (Windows Task Scheduler)

```powershell
$action  = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument "C:\path\to\garmin_collector.py"

$trigger = New-ScheduledTaskTrigger -AtLogOn

Register-ScheduledTask -TaskName "GarminCollector" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

With log output:
```powershell
-Argument "C:\path\to\garmin_collector.py >> C:\garmin_data\collector.log 2>&1"
```

### Automate on login (Linux/macOS cron)

```bash
crontab -e
# Add: runs daily at 07:00
0 7 * * * python3 /path/to/garmin_collector.py >> /path/to/garmin_data/collector.log 2>&1
```

### Data fields collected

- **Sleep:** phases, score, SpO2, respiration rate, HRV
- **Heart rate:** resting, min, max, average
- **Stress & Body Battery**
- **Steps, calories, distance, intensity minutes**
- **Training readiness, training status, 7-day load, VO2max**
- **Activities** (compact per activity)
- Race predictions, max metrics

---

## garmin_to_excel.py

### What it does

Reads all `garmin_YYYY-MM-DD.json` files from the `summary` folder and produces
a formatted Excel file with two sheets:

- **Garmin Daily Overview** — one row per day, colour-coded by category
- **Activities** — one row per activity (optional)

### Configuration (CONFIG block at top of script)

| Variable                  | Description                             |
|---------------------------|-----------------------------------------|
| `SUMMARY_DIR`             | Path to the summary folder              |
| `OUTPUT_FILE`             | Path and filename for the Excel output  |
| `DATE_FROM` / `DATE_TO`   | Date filter (`None` = export all)       |
| `FIELDS`                  | Toggle columns on/off (`True`/`False`)  |
| `EXPORT_ACTIVITIES_SHEET` | Include activities sheet (`True`/`False`) |

### Toggling columns

In the `FIELDS` block, set `True` or `False`:

```python
"sleep.light_h":     False,  # hide light sleep
"heartrate.avg_bpm": True,   # show average heart rate
```

Column order in the spreadsheet follows the order in `FIELDS`.

### Date filter

```python
DATE_FROM = "2025-01-01"   # from January 2025
DATE_TO   = "2025-12-31"   # until end of 2025
DATE_FROM = None            # no filter — export everything
```

### Run

```bash
python garmin_to_excel.py
```

---

## Maintenance

### Adding new fields from raw data

The `raw/` folder contains the complete API response for every day. If Garmin
adds new metrics or you want additional fields:

1. Open any `garmin_raw_YYYY-MM-DD.json` and locate the field
2. Add it to `summarize()` in `garmin_collector.py` under the appropriate category
3. Add the field key and label to `FIELDS` and `LABELS` in `garmin_to_excel.py`
4. Existing summary files do **not** need to be re-downloaded —
   they can be regenerated from the raw files without any API calls

### Re-fetching a specific day

Delete the corresponding `garmin_raw_YYYY-MM-DD.json` (and optionally the summary),
then run the collector again — it will re-fetch that day automatically.

### Rate limiting by Garmin

If Garmin throttles requests (many warnings, slow responses):
increase `REQUEST_DELAY` from `1.5` to `3.0`.

### Login fails / Captcha

On first run or after a long pause, Garmin may require browser-based
verification. Run the script manually in a terminal and follow the prompt.
Subsequent automated runs will work without interaction.

### Older Garmin devices (e.g. Vivosmart, Fenix 5)

Many fields will be `null` for older devices — this is expected.
Sleep, heart rate, and steps are available even with older hardware.
Set `SYNC_START_DATE` to control how far back to go:

```python
SYNC_START_DATE = "2018-06-01"
```

---

## Open WebUI / Ollama integration

Point the Knowledge Base at the `summary` folder:

1. Open WebUI → **Workspace** → **Knowledge** → **+ New**
2. Name: `Garmin Health Data`
3. Folder: path to your `summary` directory
4. In chat: type `#` → select the knowledge base

Example questions:
- *"How was my sleep and HRV last week?"*
- *"Which days had Body Battery below 30?"*
- *"Show me my VO2max trend over January."*
- *"When did I have the highest training load?"*
- *"Compare my resting heart rate this month vs last month."*
