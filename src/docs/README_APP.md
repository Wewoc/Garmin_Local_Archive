# Garmin Local Archive — Desktop App v1.7.1.8

Drei Dokumente:
  QUICKSTART.txt   → first-time setup in a few minutes
  README_APP.md    → installation, security, technical setup (this document)
  USER_GUIDE.txt   → all features in daily use, troubleshooting

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

**Tab area** — five tabs:
- **Home** — Dashboard viewer (HTML dashboards)
- **Files** — Excel viewer
- **Settings** — all configuration panels
- **Ollama-Chat** — native chat against a local Ollama instance (v1.6.6)
- **MCP Server** — local LLM access to your archive via the Model Context Protocol (v1.7)

-> For how to use each tab day-to-day, see USER_GUIDE.txt.

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
- **Theme** *(v1.7.1.8)* — colour scheme for the app window and HTML dashboards, chosen from the Settings → Design dropdown. Six built-in themes (Monochrome + Rust Accent — default, Violet/Legacy, Amber & Copper, Olive & Sand, Toxic, Ice Blue). Choosing a theme opens a restart-to-apply dialog — themes are not applied live to an already-open window.
- **Delay min / max (s)** — randomized pause between individual Garmin API requests (default: 5 / 20). Garmin Connect has no official public API — this tool uses the same endpoints the mobile app itself calls. A randomized delay within this range keeps request timing within normal usage patterns and helps avoid rate limiting (HTTP 429). Lower values increase the risk of a temporary IP ban — 5/20 is the recommended minimum.

Click **Save Settings** — settings are remembered between sessions.

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

## Connection & Archive Status

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
- **Source** — total source files archived · files present within the last 180-day window (e.g. `175 days · 180/180d`). The 180-day window is the Background Timer's own retry buffer, not Garmin's intraday resolution boundary itself — see USER_GUIDE.txt, Section 5, for the distinction between the two.

The panel refreshes automatically after every Sync and Bulk Import.

-> For what the Background Timer does with this data, see USER_GUIDE.txt, Section 5.

---

## Troubleshooting

**App doesn't start**

> **Standard:** Make sure the `scripts/` folder is in the same folder as the `.exe` and contains all required files.
> **Standalone:** Open your data folder in Windows Explorer and navigate to `garmin_data\log\fail\`. Open the most recent `.log` file in Notepad — it contains the full error output. If the app never started and no data folder exists yet, use the **Copy Last Error Log** button if the app partially loaded, or re-run from the Standard version with Python to see terminal output.

**Login fails** — if Garmin requires MFA, the app will show a code input popup automatically. Enter the code from your Garmin app or authenticator.

**First login (no saved token)** — the app shows a confirmation dialog before starting the SSO login. This is intentional — garminconnect sends several requests to Garmin during login and may trigger rate limiting if repeated too quickly. An encryption key is generated automatically in the background (no password required). Click **Proceed** to continue or **Cancel** to abort.

**Token expired (sync starts slowly)** — If the log shows repeated `401` errors or `DI token refresh failed` at the start of a sync, the saved token has expired. The app recovers automatically — do not cancel. The re-login sequence takes 3–4 minutes. Wait for `✓ Login successful` before assuming something is wrong.

> **Standalone:** If login fails due to captcha or browser verification, download the Standard version, install Python, and run `garmin_collector.py` once in a terminal to complete verification. After that the Standalone version will work normally using the saved session.

**Password not saved between sessions** — click Save Settings after entering your password.

> **Standard:** If keyring is unavailable: `pip install keyring`.

**Antivirus flags the EXE** — this is a false positive common with PyInstaller-built executables. The source code is fully open at github.com/Wewoc/Garmin_Local_Archive. You can whitelist the file in your antivirus settings or build the EXE yourself from source.

-> For sync errors, missing dashboard data, context/weather issues, or background timer questions, see USER_GUIDE.txt, Section 8.

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

## Appendix: Connecting external AI tools (Open WebUI, AnythingLLM)

> **Note:** This section covers optional third-party tools (Ollama, Open
> WebUI, AnythingLLM). It is not actively maintained and may fall out of
> date — check each tool's own documentation for current install steps
> and options.

Connect a local AI model to your health data. All options run entirely on your machine — your data never leaves your PC.

> ⚠️ **Before you start:** Both the built-in chat and the prompt file used by the external options contain your personal health metrics. If you use a local model (Ollama), your data stays on your device. If you use a cloud service, remove any identifying details before uploading — name, date of birth, account information. AI interpretations of health data can be plausible but wrong. Always verify concerning findings with a healthcare professional.

### Option A — Built-in Chat (simplest, no separate setup)

1. Install Ollama: https://ollama.com/download
2. Pull a model that fits your GPU (see table below)
3. Open the **Ollama-Chat** tab in the app, click **Start**

That's it — no Docker, no separate desktop app. The panel loads the same
health-analysis system prompt used by the external options below.
Currently works against summary data only; full intraday resolution is
planned for v1.9. For document upload / knowledge-base RAG across your
whole archive, use Open WebUI or AnythingLLM below instead.

**Which model fits your GPU?** Rule of thumb: **VRAM in GB − 2 = usable
model size** (Q4 quantization, Ollama's default). Rough guide, not a
guarantee — actual headroom depends on context length and what else is
using the GPU.

| VRAM | Rule of thumb | Example |
|---|---|---|
| 8 GB | ~6B | `qwen2.5:7b` |
| 16 GB | ~14B | `qwen3:14b` |
| 24 GB | ~22B (next common tier: ~30–32B) | — |
| 48 GB | ~46B (next common tier: ~70B) | — |

No dedicated GPU / CPU-only also works — just noticeably slower per reply,
the panel's elapsed-time counter is there for exactly this case.

### Option B — Open WebUI

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

4. Open http://localhost:3000 → Workspace → **Knowledge** → **+ New** → point to `local_archive/garmin_data/summary`
5. In chat: type `#` → select the knowledge base

### Option C — AnythingLLM

1. Download AnythingLLM Desktop: https://anythingllm.com
2. Connect Ollama (Settings → LLM → Ollama)
3. New Workspace → Upload documents → point to `local_archive/garmin_data/summary`

### Which one to choose?

| | Built-in Chat | Open WebUI | AnythingLLM |
|---|---|---|---|
| Setup effort | None (Ollama only) | Medium (Docker) | Low (desktop app) |
| Chat interface | Basic, in-app | Full-featured | Clean, focused |
| Document/RAG quality | None — summary data only | Good | Very good |
| Best for | Quick questions without leaving the app | General AI assistant + health data | Primarily health data Q&A |

**Tip:** upload `garmin_analysis.json` directly into a chat for targeted analysis — it contains pre-processed comparisons against your personal baseline and reference ranges.

Example questions:
- *"How was my sleep and HRV last week?"*
- *"Which days had Body Battery below 30?"*
- *"Compare my resting heart rate this month vs last month."*
- *"Based on the analysis file, which metrics need attention and why?"*

### Connecting Open WebUI to the MCP Server

> **Note:** Same caveat as above — MCP client support in third-party tools
> is evolving quickly. Check Open WebUI's own documentation if this no
> longer matches what you see.

Start the MCP Server first (**MCP Server** tab in the app, or the standalone `mcp_server.exe`) — see USER_GUIDE.txt, Section 11, for backend, port, and Docker-specific settings.

In Open WebUI: **Settings → Connections → MCP Servers → Add Connection**.

- **Type:** MCP Streamable HTTP
- **Name:** any label, e.g. `GLA MCP`
- **URL:** `http://127.0.0.1:<port>/mcp` — if Open WebUI runs inside Docker, use `http://host.docker.internal:<port>/mcp` instead (the default port is `8756`; enable **Extra allowed hosts** on the MCP Server tab first, see USER_GUIDE.txt, Section 11)
- **Authentication:** None

Save the connection, then enable it in a chat via the tools/connectors picker.

**Claude Desktop** and other MCP clients connect the same server differently — usually via a JSON config file (`mcpServers` entry) rather than an in-app dialog. Check the client's own MCP documentation for the exact syntax; the server URL and port above stay the same regardless of client.
