# Garmin Local Archive

> This project is provided as-is under the GNU General Public License v3.0, without warranty of any kind. Use at your own risk. No support, maintenance, or liability is implied or offered.

Archive and analyse your Garmin Connect data locally — no cloud, no third parties. Everything runs on your own machine.

---

## Why this exists

I'm not a developer. I can't write Python.

But I wanted what everyone else wanted — to ask an AI questions about my Garmin health data. Sleep, HRV, stress, recovery.

The tools that exist send your data to OpenAI or Claude. Your heart rate, sleep patterns, and fitness data land on a US company's servers.

I didn't want that.

So I built this instead — with Claude as my coding partner, from zero, over many iterations. Everything runs locally. Nothing leaves your machine. The AI that analyses your data runs on your own hardware.

It works. And if I could build it, you can use it.

*Built with Claude · If this saved you time — [☕ buy me a coffee](https://ko-fi.com/wewoc)*

---

## What is this?

Five Python scripts and an optional desktop app that work together:

| Script                       | What it does                                                           | Reads from  |
|------------------------------|------------------------------------------------------------------------|-------------|
| `garmin_collector.py`        | Downloads your Garmin data and keeps it up to date                     | Garmin API  |
| `garmin_to_excel.py`         | Daily summary spreadsheet — one row per day                            | `summary/`  |
| `garmin_timeseries_excel.py` | Full intraday data per metric as Excel with charts                     | `raw/`      |
| `garmin_timeseries_html.py`  | Interactive browser dashboard — zoomable, tabbed, offline              | `raw/`      |
| `garmin_analysis_html.py`    | Analysis dashboard: daily values vs personal baseline vs norm ranges   | `summary/`  |
| `garmin_app.py` + `build.py` | Optional desktop GUI — run all scripts without terminal or text editor | —           |

Data is stored in two layers:

```
garmin_data/
├── raw/        – complete API dumps (~500 KB/day) — permanent archive
└── summary/    – compact daily JSONs (~2 KB/day)  — for Ollama / Open WebUI / AnythingLLM
```

---

## Quickstart — Desktop App (recommended)

Download `GarminArchive.zip` from the releases page, extract it, and double-click `GarminArchive.exe`.

```
GarminArchive.exe     ← double-click to launch
scripts/              ← required, must stay next to the .exe
info/                 ← documentation (optional)
```

The app handles everything without a terminal. See `info/README_APP.md` for details.

---

## Quickstart — Scripts only

```bash
pip install garminconnect openpyxl keyring
```

Python 3.10 or newer required. If not installed: https://www.python.org/downloads/

Each script reads its configuration from environment variables first, falling back to hardcoded values in the CONFIG block at the top of the file. To configure for terminal use: either edit the CONFIG block directly, or set the relevant `GARMIN_*` environment variables before running. See `MAINTENANCE.md` for the full variable reference.

---

## Step-by-step setup (scripts)

### Step 1 — Install Python

1. Go to https://www.python.org/downloads/ and download the latest Python 3.x installer
2. Run the installer
3. **Important:** tick **"Add Python to PATH"** before clicking Install
4. Open a terminal (Windows: press `Win+R`, type `cmd`, press Enter) and verify:

```bash
python --version
```

You should see something like `Python 3.13.0`.

---

### Step 2 — Install required libraries

In the terminal, run:

```bash
pip install garminconnect openpyxl keyring
```

Wait for all to finish installing.

---

### Step 3 — Configure the collector

Open `garmin_collector.py` in any text editor and fill in the fallback values at the top of the CONFIG block:

```python
GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL",    "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "yourpassword")
BASE_DIR        = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()
```

Replace `"your@email.com"`, `"yourpassword"`, and `"~/garmin_data"` with your actual values. Alternatively, set the environment variables `GARMIN_EMAIL`, `GARMIN_PASSWORD`, and `GARMIN_OUTPUT_DIR` — they always take priority over the hardcoded values.

**Sync mode** — choose how far back to go:

```python
SYNC_MODE = "recent"    # default: last 90 days
SYNC_MODE = "range"     # specific period: set SYNC_FROM and SYNC_TO below
SYNC_MODE = "auto"      # everything since your oldest device (can take hours)
```

For a full historical backfill set `SYNC_MODE = "auto"` and optionally:

```python
SYNC_AUTO_FALLBACK = "2018-01-01"   # safety net if device detection fails
```

---

### Step 4 — Run the collector

```bash
python garmin_collector.py
```

On first run the script will:
- Connect to Garmin Connect
- Detect your registered devices and their first-use dates
- Download all missing days (this can take a while for large backlogs)
- Save one raw file and one summary file per day

On subsequent runs it only fetches what's new.

**First run may ask for browser verification** — if Garmin requires a captcha, follow the prompt in the terminal. This only happens once.

---

### Step 5 — Export to Excel (daily overview)

Open `garmin_to_excel.py` and set the fallback paths in the CONFIG block — or set `GARMIN_OUTPUT_DIR` as an environment variable (the script derives all paths from it automatically):

```python
_BASE       = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()
SUMMARY_DIR = _BASE / "summary"
OUTPUT_FILE = Path(os.environ.get("GARMIN_EXPORT_FILE", str(_BASE / "garmin_export.xlsx")))
```

Optionally set a date range:

```python
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "") or None   # e.g. "2025-01-01"
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "") or None   # e.g. "2025-12-31"
```

Toggle any columns on or off in the `FIELDS` block, then run:

```bash
python garmin_to_excel.py
```

---

### Step 6 — Export intraday timeseries (Excel + charts)

Open `garmin_timeseries_excel.py` and set the fallback date range in the CONFIG block:

```python
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "2026-03-01")
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "2026-03-16")
```

Then run:

```bash
python garmin_timeseries_excel.py
```

Produces one data sheet + one chart sheet per metric (Heart Rate, Stress, SpO2, Body Battery, Respiration).

> For ranges longer than ~30 days the HTML dashboard (Step 7) is faster and more usable.

---

### Step 7 — Interactive HTML dashboard

Open `garmin_timeseries_html.py` and set the fallback date range in the CONFIG block:

```python
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "2026-03-01")
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "2026-03-16")
```

Then run:

```bash
python garmin_timeseries_html.py
```

Open the resulting `.html` file in any browser. Features:
- One tab per metric
- Zoom by dragging, or use the range buttons (1d / 7d / 1m / All)
- Hover for exact values
- Works fully offline after first load (Plotly is cached)

---

### Step 8 — Analysis dashboard

Open `garmin_analysis_html.py` and set the fallback date range and profile in the CONFIG block:

```python
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "2026-01-01")
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "2026-03-17")

PROFILE = {
    "age": int(os.environ.get("GARMIN_PROFILE_AGE", "35")),
    "sex": os.environ.get("GARMIN_PROFILE_SEX", "male"),
}
```

Replace the fallback values with your age and sex. Fitness level is detected automatically from your VO2max data — no manual entry needed.

Then run:

```bash
python garmin_analysis_html.py
```

Produces two files:

- `garmin_analysis.html` — browser dashboard showing daily values, your 90-day personal baseline (dashed), and age/fitness-adjusted reference range (green band) per metric
- `garmin_analysis.json` — compact summary for AI tools with flagged days highlighted

> Reference ranges are based on published guidelines (AHA, ACSM, Garmin/Firstbeat) and are informational only — not medical advice.

---

### Step 9 — Desktop app (optional)

If you prefer a GUI over editing scripts and running terminals, build the desktop app:

```bash
python build.py
```

`build.py` automatically:
- Installs PyInstaller and keyring if needed
- Moves scripts to `scripts/` and docs to `info/` if still in root
- Builds `GarminArchive.exe`
- Creates `GarminArchive.zip` ready for distribution

See `info/README_APP.md` for full app documentation.

---

### Step 10 — Automate the collector (optional)

**Windows Task Scheduler:**

```powershell
$action  = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument "C:\path\to\scripts\garmin_collector.py"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "GarminCollector" `
    -Action $action -Trigger $trigger -RunLevel Highest
```

**Linux / macOS** (daily at 07:00):

```bash
crontab -e
# add this line:
0 7 * * * python3 /path/to/garmin_collector.py >> /path/to/garmin_data/collector.log 2>&1
```

---

### Step 11 — AI-assisted analysis (optional)

If you want to go beyond Excel and dashboards, connect a local AI model to your health data. Two tools work equally well — choose whichever suits you. Both run entirely on your machine. Your data never leaves your PC.

---

#### Option A — Open WebUI

A full-featured chat interface for local AI models. Good all-round choice, widely used.

**Setup:**

1. Install Ollama: https://ollama.com/download
2. Pull a model: `ollama pull qwen2.5:14b`
3. Install Open WebUI via Docker:

```bash
docker run -d -p 3000:8080 --gpus all \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  --name open-webui --restart always \
  ghcr.io/open-webui/open-webui:cuda
```

4. Open http://localhost:3000 in your browser
5. Workspace → **Knowledge** → **+ New** → point to `garmin_data/summary`
6. In chat: type `#` → select the knowledge base

---

#### Option B — AnythingLLM

Purpose-built for document and knowledge base workflows. Stronger RAG than Open WebUI — better at finding specific days or metrics across large date ranges.

**Setup:**

1. Download AnythingLLM Desktop: https://anythingllm.com
2. Connect Ollama as LLM provider (Settings → LLM → Ollama)
3. New Workspace → Upload documents → point to `garmin_data/summary`

---

#### Which one to choose?

| | Open WebUI | AnythingLLM |
|---|---|---|
| Setup effort | Medium (Docker) | Low (desktop app) |
| Chat interface | Full-featured | Clean, focused |
| Document/RAG quality | Good | Very good |
| Best for | General AI assistant + health data | Primarily health data Q&A |

**Using the analysis JSON with either tool:**

Upload `garmin_analysis.json` directly into a chat for targeted analysis — it contains pre-processed comparisons against your personal baseline and reference ranges, much better context than raw numbers.

Example questions:
- *"How was my sleep and HRV last week?"*
- *"Which days had Body Battery below 30?"*
- *"When did I have the highest training load?"*
- *"Compare my resting heart rate this month vs last month."*
- *"Based on the analysis file, which metrics need attention and why?"*

---

See `info/MAINTENANCE.md` for full technical documentation, how to add new fields, troubleshooting, and developer notes.
