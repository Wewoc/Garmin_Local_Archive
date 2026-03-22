# Garmin Local Archive

> This project is provided as-is under the GNU General Public License v3.0, without warranty of any kind. Use at your own risk. No support, maintenance, or liability is implied or offered.

Archive and analyse your Garmin Connect data locally — no cloud, no third parties. Everything runs on your own machine.

---

## Why this exists

I'm not a software developer. I can't write Python.

But I wanted what everyone else wanted — to ask an AI questions about my Garmin health data. Sleep, HRV, stress, recovery.

The tools that exist send your data to OpenAI or Claude. Your heart rate, sleep patterns, and fitness data land on a US company's servers.

I didn't want that.

So I built this instead — with Claude as my coding partner, from zero, over many iterations. Everything runs locally. Nothing leaves your machine. The AI that analyses your data runs on your own hardware.

It works. And if I could build it, you can use it.

*Built with Claude · If this saved you time — [☕ buy me a coffee](https://ko-fi.com/wewoc)*

---

## Security & Trust

The full source code is open. If you don't trust the pre-built EXE:

- Read the scripts — or paste them into any AI and ask *"explain what this code does"*
- Build your own EXE: `python build_standalone.py`

Credentials are stored in the **Windows Credential Manager** (keyring) — encrypted by Windows, never written to disk as plain text. This is more secure than typical hobby scripts that ask you to hardcode your password directly into a config file.

The pre-built EXE is unsigned because code-signing certificates cost ~$500/year — money I'd rather spend on coffee. If the Windows security warning concerns you, the scripts are the primary way to run this and always will be.

---

## What is this?

Six Python scripts and an optional desktop app that work together:

| Script                       | What it does                                                           | Reads from  |
|------------------------------|------------------------------------------------------------------------|-------------|
| `garmin_collector.py`        | Downloads your Garmin data and keeps it up to date                     | Garmin API  |
| `garmin_to_excel.py`         | Daily summary spreadsheet — one row per day                            | `summary/`  |
| `garmin_timeseries_excel.py` | Full intraday data per metric as Excel with charts                     | `raw/`      |
| `garmin_timeseries_html.py`  | Interactive browser dashboard — zoomable, tabbed, offline              | `raw/`      |
| `garmin_analysis_html.py`    | Analysis dashboard: daily values vs personal baseline vs norm ranges   | `summary/`  |
| `garmin_app.py` + `build.py` | Optional desktop GUI — run all scripts without terminal or text editor | —           |

Each script is self-contained and designed to be extended. Add new fields, metrics, or analysis logic without touching the rest of the system. See `info/MAINTENANCE.md` for how.

The desktop app (v1.1.1) also includes a **Background Timer** — a fully automatic background sync that repairs failed/incomplete days and fills missing ones while the app is open, without any manual intervention.

Data is stored in three folders:

```
garmin_data/
├── raw/        – complete API dumps (~500 KB/day) — permanent archive
├── summary/    – compact daily JSONs (~2 KB/day)  — for Ollama / Open WebUI / AnythingLLM
└── log/        – session logs and failed days registry
```

---

## Quickstart — which version should I download?

There are three ways to run Garmin Local Archive:

| | Who it's for | Requirements |
|---|---|---|
| **Standalone EXE** | Anyone — no setup needed | Nothing |
| **Standard EXE** | Users comfortable with Python | Python + libraries installed |
| **Scripts only** | Developers | Python + libraries installed |

### Option 1 — Standalone EXE (recommended for most users)

**[⬇ Download Garmin_Local_Archive_Standalone.zip](https://github.com/Wewoc/Garmin_Local_Archive/releases/latest/download/Garmin_Local_Archive_Standalone.zip)**

Extract and double-click `Garmin_Local_Archive_Standalone.exe`.

```
Garmin_Local_Archive_Standalone.exe     ← double-click to launch — nothing else needed
info/                                   ← documentation (optional)
```

No Python, no terminal, no dependencies. Everything is built in.
See `info/README_APP_Standalone.md` for full details.

### Option 2 — Standard EXE (Python required)

**[⬇ Download Garmin_Local_Archive.zip](https://github.com/Wewoc/Garmin_Local_Archive/releases/latest/download/Garmin_Local_Archive.zip)**

Extract and double-click `Garmin_Local_Archive.exe`.

```
Garmin_Local_Archive.exe     ← double-click to launch
scripts/                     ← required, must stay next to the .exe
info/                        ← documentation (optional)
```

Python and the required libraries must be installed on your machine.
See `info/README_APP.md` for full details.

### Option 3 — Scripts only

```bash
pip install garminconnect openpyxl keyring
python garmin_collector.py
```

Python 3.10 or newer required. See the step-by-step setup below.

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

---

### Step 3 — Configure the collector

Open `garmin_collector.py` in any text editor and fill in the fallback values at the top of the CONFIG block:

```python
GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL",    "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "yourpassword")
BASE_DIR        = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()
```

**Sync mode** — choose how far back to go:

```python
SYNC_MODE = "recent"    # default: last 90 days
SYNC_MODE = "range"     # specific period: set SYNC_FROM and SYNC_TO below
SYNC_MODE = "auto"      # everything since your oldest device (can take hours)
```

---

### Step 4 — Run the collector

```bash
python garmin_collector.py
```

On first run the script will connect to Garmin Connect, detect your registered devices, and download all missing days. Subsequent runs only fetch what's new.

**First run may ask for browser verification** — if Garmin requires a captcha, follow the prompt in the terminal. This only happens once.

---

### Step 5 — Export to Excel (daily overview)

```bash
python garmin_to_excel.py
```

Produces `garmin_export.xlsx` — one row per day, colour-coded by category. Toggle columns on/off in the `FIELDS` block at the top of the script.

---

### Step 6 — Export intraday timeseries (Excel + charts)

```bash
python garmin_timeseries_excel.py
```

Produces one data sheet + one chart sheet per metric. Set the date range in the CONFIG block first.

> For ranges longer than ~30 days the HTML dashboard (Step 7) is faster and more usable.

---

### Step 7 — Interactive HTML dashboard

```bash
python garmin_timeseries_html.py
```

Generates `garmin_dashboard.html` — open in any browser. One tab per metric, fully zoomable, works offline.

---

### Step 8 — Analysis dashboard

```bash
python garmin_analysis_html.py
```

Set your age and sex in the CONFIG block first. Produces:

- `garmin_analysis.html` — daily values vs your 90-day personal baseline vs age/fitness reference ranges
- `garmin_analysis.json` — compact summary for AI tools with flagged days highlighted

> Reference ranges are based on published guidelines (AHA, ACSM, Garmin/Firstbeat) and are informational only — not medical advice.

---

### Step 9 — Desktop app (optional)

**Standard EXE (Python required on target machine):**

```bash
python build.py
```

Produces `Garmin_Local_Archive.exe` + `Garmin_Local_Archive.zip`.

**Standalone EXE (no Python required on target machine):**

```bash
python build_standalone.py
```

Produces `Garmin_Local_Archive_Standalone.exe` + `Garmin_Local_Archive_Standalone.zip`. All scripts and dependencies are embedded — the target machine needs nothing installed.

Both build scripts auto-migrate scripts to `scripts/` and docs to `info/` if they are still in the root folder. Safe to run from any starting layout.

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
0 7 * * * python3 /path/to/garmin_collector.py >> /path/to/garmin_data/log/collector.log 2>&1
```

---

### Step 11 — AI-assisted analysis (optional)

Connect a local AI model to your health data. Both options run entirely on your machine — your data never leaves your PC.

#### Option A — Open WebUI

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

4. Open http://localhost:3000 → Workspace → **Knowledge** → **+ New** → point to `garmin_data/summary`
5. In chat: type `#` → select the knowledge base

#### Option B — AnythingLLM

1. Download AnythingLLM Desktop: https://anythingllm.com
2. Connect Ollama (Settings → LLM → Ollama)
3. New Workspace → Upload documents → point to `garmin_data/summary`

#### Which one to choose?

| | Open WebUI | AnythingLLM |
|---|---|---|
| Setup effort | Medium (Docker) | Low (desktop app) |
| Chat interface | Full-featured | Clean, focused |
| Document/RAG quality | Good | Very good |
| Best for | General AI assistant + health data | Primarily health data Q&A |

**Tip:** upload `garmin_analysis.json` directly into a chat for targeted analysis — it contains pre-processed comparisons against your personal baseline and reference ranges.

Example questions:
- *"How was my sleep and HRV last week?"*
- *"Which days had Body Battery below 30?"*
- *"Compare my resting heart rate this month vs last month."*
- *"Based on the analysis file, which metrics need attention and why?"*

---

See `info/MAINTENANCE.md` for full technical documentation, how to add new fields, troubleshooting, and developer notes.

---

## Testing

No dedicated test suite. The effort-to-benefit ratio doesn't justify it for a single-person hobby project — the core scripts are stable and tested in daily use. GUI changes are verified manually before release.
