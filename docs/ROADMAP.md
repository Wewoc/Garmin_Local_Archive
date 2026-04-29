# Garmin Local Archive — Roadmap

> This is a hobby project built and maintained by one person without a programming background.  
> There are no deadlines, no guarantees, and no support obligations — development happens when it happens, and it may take a while.  
> Features get built when they get built.

---

**Currently stable — v1.4.8**

---

## Planned

---

### v1.4.9 — GUI Consolidation (GarminAppBase Refactoring)

`garmin_app.py` and `garmin_app_standalone.py` currently share ~2400 lines
each with ~90% identical content. Every GUI fix requires two identical
anchor-block changes. v1.4.9.1 (Daily Sync) would add a third entry point
that needs the same shared logic — making consolidation a prerequisite,
not a deferral.

#### What changes

A new `garmin_app_base.py` contains all shared code:
- UI constants (colors, fonts)
- `DEFAULT_SETTINGS`, `load_settings()`, `save_settings()`
- Keyring helpers — moved to `garmin_security.py` (where they belong)
- Full `GarminAppBase(tk.Tk)` class with all GUI layout and shared methods

`garmin_app.py` retains only:
- `script_dir()`, `_find_python()`
- `_run_script()` and `_stop_collector()` (subprocess model)
- `class GarminApp(GarminAppBase)`

`garmin_app_standalone.py` retains only:
- `script_dir()`, `_register_embedded_packages()`
- `_apply_env()`, `_apply_env_overrides()`
- `_run_module()`, `_poll_log_queue()` (thread + queue model)
- `class GarminApp(GarminAppBase)`

#### What does not change

- Class name `GarminApp` in both files — build validation signatures unchanged
- PyInstaller dependency detection — `garmin_app_base.py` added to
  `SHARED_SCRIPTS` in `build_manifest.py`; both builds pick it up automatically
- External behavior — no functional changes, pure structural consolidation

#### Result

One change, one file. `daily_update.py` (v1.4.9.1) imports shared logic
from `garmin_app_base.py` without duplicating it.

---

### v1.4.9.1 — Daily Sync (Automated Daily Workflow)

**Prerequisite:** v1.4.9 (GarminAppBase) complete. `_clear_token_dir()` in
`garmin_security.py` must reliably remove the token working dir after
`client.login()` — currently fails with WinError 5 when garminconnect holds
the file handle. Headless operation cannot tolerate a stale working dir.
Fix must land before implementation begins.

---

### v1.4.9.1 — Daily Sync (Automated Daily Workflow)

**Prerequisite:** `_clear_token_dir()` in `garmin_security.py` must reliably
remove the token working dir after `client.login()` — currently fails with
WinError 5 when garminconnect holds the file handle. Headless operation cannot
tolerate a stale working dir. Fix must land before v1.4.9 implementation begins.

Automated daily workflow as a standalone tool — no GUI, no manual interaction.
After initial setup in the desktop app, `daily_update` becomes the only daily
touchpoint with the system.

#### What it does

1. Call `garmin_collector` with date range: yesterday → yesterday
2. Call `context_collector` with date range: yesterday → yesterday
3. Call `dash_runner.build()` for all dashboards
4. Close the console window if everything completed cleanly

No new date logic, no new orchestration — existing collectors and runner
are called with parameters. `daily_update` is a thin entry point, not a
second orchestrator.

#### Gap detection

On each run `daily_update` checks the last successful sync date and acts
accordingly:

| Gap | Behaviour |
|---|---|
| ≤ 7 days | Closes the gap automatically — syncs all missing days |
| > 7 days | Hard stop — "X days missing, please open the app to sync" |

Keeps `daily_update` self-healing for normal interruptions (holiday,
machine off) without replicating Background Timer logic or introducing
a second orchestrator.

#### Console behaviour

| State | Behaviour |
|---|---|
| All OK | Console window closes automatically |
| New version available | Window stays open — yellow notice |
| Error | Window stays open — red notice |
| Migration required | Window stays open — hard stop, open the app |
| Settings missing | Window stays open — hard stop, open the app |

No silent failures. The window closing is the success signal.

Exit codes for Task Scheduler integration:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Migration required |
| 2 | Settings missing |
| 3 | API / Sync error |
| 4 | Dashboard error |

#### Delivery per build target

| Target | GUI | Daily Update |
|---|---|---|
| T1 — Dev/Scripts | `python garmin_app.py` | `python daily_update.py` or via `.bat` |
| T2 — Standard EXE | `Garmin_Local_Archive.exe` | `daily_update.bat` (calls `python daily_update.py`) |
| T3.1 — Standalone GUI | `Garmin_Local_Archive.exe` | — |
| T3.2 — Standalone headless | — | `daily_update.exe` |

T3.1 and T3.2 ship in the same ZIP — one download, both tools included.

#### Shared config

Both T3 executables read from the same `~/.garmin_archive_settings.json` and
the same Windows Credential Manager entry. Configure once in T3.1 — T3.2 picks
it up automatically. No duplicate setup.

#### Onboarding flow

```
1. Open T3.1 — enter email, password, folder, location → Save Settings
2. Run Bulk Import — full history
3. Run Sync Garmin + Sync Context once manually — archive up to date
4. Add daily_update.exe to Windows Task Scheduler → done
```

`daily_update` is step 4, not step 1. Running it before the app has been
configured once results in a hard stop with a clear message including the
expected settings file path and the name of the app to open.

#### Logging

Dedicated folder `BASE_DIR/log/daily/` — rolling 30 files, same mechanism
as `log/recent/`.

#### Task Scheduler setup notes (documentation)

Three settings to document for users configuring Windows Task Scheduler:

1. **"Run task as soon as possible after a scheduled start is missed"** — ensures the sync runs after waking from sleep even if the scheduled time was missed.
2. **"Do not restart on failure"** — prevents a restart loop from flooding `log/daily/` with error files within minutes.
3. **Run once daily, in the morning** — running more frequently than once per day is unnecessary and risks Garmin API rate limits (HTTP 429).

These are documentation items only — no code changes required.

A ready-to-import Task Scheduler XML template ships in `info/` (T2/T3)
and `docs/` (T1) — users import it once into Windows Task Scheduler.

**Auto-fill on Save Settings:** when the user clicks Save Settings in the
app, the XML template is automatically updated with the correct absolute
path to the `daily_update` entry point for that build target. No manual
editing required.

Path resolution uses the existing frozen-check pattern already used
throughout the project:

- T1 — `Path(__file__).parent / "docs"` → `daily_update.py`
- T2/T3 — `Path(sys.executable).parent / "info"` → `daily_update.bat` / `daily_update.exe`

`daily_update.py` lives in the project root alongside `garmin_app.py`.
No T1 ZIP — T1 users work directly in the repo.

#### Operational policy layer

Gap rules, exit code mapping, and stop conditions currently live in
`daily_update`. If GUI, Background Timer, and Daily Sync ever need to share
the same operational rules, this logic moves to a dedicated `sync_policy.py`
— consistent with the v2.0 global actor pattern (`sync.py`). No duplication,
no divergence. Noted here as the natural migration path when the time comes.

#### Build

Two entry points, one build run, one output folder. `build_manifest.py` gets
a second entry point definition. `build_standalone.py` builds both executables
sequentially. No additional maintenance overhead — identical codebase,
different packaging.

#### Implementation note — ENV loading order (T3.2)

T3.2 has no Python subprocess available — collector runs as a thread, not a
child process. `garmin_config` reads `os.environ` at import time, not
dynamically. This means ENVs must be set via `os.environ` *before*
`garmin_config` is imported — exactly the pattern already used in
`garmin_app_standalone.py` via `_apply_env()`.

`daily_update` must follow this same pattern. Any deviation would silently
use default config values instead of the user's settings — a classic silent
failure. The `_apply_env()` implementation in `garmin_app_standalone.py` is
the reference.

---

## Planned — v1.5

### v1.5 — Archive Integrity & Backup

Protection of the local archive against software errors and silent data loss — independent of OS-level backup.

**`quality_log.json`**

- **Monthly backup** — `_save_quality_log()` creates a snapshot once per month as `quality_log_YYYY-MM.zip` in `log/backup/`. On the first save of a new year, the previous year is consolidated into `quality_log_YYYY.zip` and all monthly zips for that year are removed.
- **Per-year checksums** — on every save, a SHA-256 hash is computed over all `days` entries for each calendar year and stored in a `checksums` block inside `quality_log.json`. On load, all completed years are verified — a mismatch triggers a warning in the log and GUI indicating which year is affected and where the backup is located.

**`raw/`** — incremental backup of newly written files. Motivation: Garmin degrades intraday data in stages (full resolution → reduced → summaries only), with the high-resolution window covering only the most recent ~6 months — the local raw copy is then the only source. A software bug in the writer that overwrites or corrupts a raw file is not recoverable without a backup. This is a direct extension of the data erosion protection that is a core promise of this project.

- Ownership: writer or a dedicated backup module — to be evaluated
- Strategy: incremental, newly written files only
- Scope and implementation to be defined after v1.4 is stable

**Mirror Backup (manual)** — a button in the GUI copies the full archive to a second location configured once in Settings (path, optional — leaving it empty disables the feature). On each run: destination is compared against source (filename + size), missing files are copied over. Follows the same manual trigger pattern as Sync Garmin and Sync Context — no automatic execution. Target location can be a NAS, external drive, or any local path. If the destination is unreachable, the operation logs a clear warning and exits cleanly.

### v1.5.1 — Content Validation

Value range checks implemented in v1.4.3 (`garmin_validator`, `garmin_collector` downgrade logic). Remaining scope: dashboard integration of flagged days, flagged day markers in charts, outlier visualization.

---

## Planned — v1.6

- **Garmin FIT Pipeline & Plugin Architecture**
  The existing Garmin Health pipeline is being rebuilt into a plugin model — `garmin_map.py` → `garmin_health_map.py`, new `garmin_fit_map.py` as a second Garmin source (activity data via API + bulk import). `field_map.py` is being extended to become a source-agnostic broker. Goal: both Garmin sources run as equal pipelines side by side.

  *Pre-conditions (resolved before plugin work begins):*
  - `garmin_normalizer.py` — add real transformation layer; current pass-through insufficient once two sources deliver differing raw schemas
  - `run_import()` — narrow QUALITY_LOCK scope; currently held across entire bulk loop including file writes

---

### Sync Mode "auto" — Deprecation Candidate

Sync mode `auto` fetches the complete history from `first_day` to yesterday
via the Garmin API. It was the original solution for building a full archive
before Bulk Import existed.

With the current toolset this use case is fully covered:

| Task | Tool |
|---|---|
| Complete history | Bulk Import — faster, no 429 risk |
| Gap repair | Background Timer |
| Daily updates | Daily Sync (v1.4.5) |

`auto` is no longer the recommended path for any standard workflow. It
remains functional but is not actively promoted. Removal or explicit
deprecation notice to be evaluated — not a priority while the mode causes
no active harm.

---

## Planned — v1.7

### v1.7 — Dashboard Render Registry

The dashboard render layer currently dispatches layout types via an `if/elif`
block in `dash_plotter_html_complex.py`. Every new dashboard requires a direct
edit to this file — the plotter grows as a side effect of new specialists, not
by its own logic.

v1.7 replaces this with a render registry: each specialist declares its render
function alongside its `META` and `build()`. `dash_plotter_html_complex.py`
becomes a pure dispatcher — it routes to the registered renderer without
knowing anything about layout-specific logic.

**What changes:**
- `dash_plotter_html_complex.py` — dispatch by registry lookup, not `if/elif`
- Each `*_dash.py` specialist — declares a `render()` function or a
  `RENDERER` reference alongside `META` and `build()`
- Adding a new dashboard no longer requires touching the plotter

**What does not change:**
- The neutral dict contract between specialist and plotter remains identical
- `dash_runner.py` — no changes; it calls `plotter.render()` as before
- Existing specialists — migrated mechanically, no logic changes

**Motivation:** v1.6 introduces a second Garmin source; v2.0 adds external
sources (Strava, Komoot). Each will bring new dashboard layouts. A growing
`if/elif` chain is not a sustainable dispatch pattern at that scale.
The registry closes this before v2.0 begins.

**Pre-condition:** `dash_plotter_html_complex.py` internal restructuring
(v1.4.8 pipeline hardening) must be complete — layout paths cleanly separated
before the registry is introduced.

---

## Under consideration — v2.0

These are ideas, not commitments. Some may never get built.

**`context_validator.py` — Context Pipeline Validation**

Structural validation of context archive files at read time — analogous to
`garmin_validator.py` for the Garmin pipeline. Would detect missing fields,
wrong types, or corrupt JSON in `context_data/` before `context_map.py`
passes data to dashboard specialists.

Not needed while context data is written exclusively by `context_writer.py`
under full project control. Becomes relevant when additional external sources
(SILAM, other APIs) are added — external API responses are structurally
unpredictable in the same way Garmin API responses are.

Prerequisite: v2.0 multi-source architecture stable.
Natural companion to `context_dataformat.json` (schema definition, analogous
to `garmin_dataformat.json`).

---

**Multi-Source Architecture**

Extension to support multiple data sources (Strava, Komoot, ...) alongside Garmin. Full concept in `CONCEPT_V2-0.md`.

**Directory structure:** Each source gets its own isolated folder (`garmin_data/`, `strava_data/`, ...) with its own `raw/`, `summary/`, `log/`. A central `master/master_index.json` serves as a pure routing layer — which sources have data for a given day, and where. No logic, no decisions.

**Architecture principle — plugin modules:** Global actors (`writer`, `normalizer`, `sync`, `security`) remain source-agnostic. Each source provides a `*_master.py` plugin that delivers source-specific details on demand — paths, formats, validation rules, token location. Adding a new source means writing a new plugin and its source-specific actors (`*_api.py`, `*_quality.py`). All global actors work without modification.

**Translation layer:** `field_map.py` is the single point of truth for mapping fields between sources and the common schema. Dashboard and export scripts have no knowledge of source details — they only query `field_map`. Adding a new source means extending `field_map` — all scripts work automatically.

---

**Multiple User accounts**
Currently one account per Windows user. Switching between accounts requires manually changing credentials in Settings. Multi-account support would allow profiles per user.

**External factors & correlations**
Import external data (weather, activity logs, custom notes) and correlate with health metrics. Did poor sleep correlate with high stress? Did training load predict HRV drops?

**Adaptive Baselines**
Extend the Analysis Dashboard beyond fixed 90-day baselines. Rolling windows (7-day, 30-day), seasonal patterns, and load vs. recovery phase detection. The raw data is already there — this is purely an analytical layer on top of `garmin_analysis_html.py`.

**AI health report PDF**
Generate a formatted PDF health summary using the local AI model — personal baseline, flagged days, trends. Fully local, no cloud.

**Route heatmap**
Generate a local heatmap of GPS routes from activity data. No third-party mapping services.

**Windows notifications**
Toast notifications for sync completion, failed days, or significant metric changes.

**Stats dashboard & session log analysis**
Local overview of archive health built from session logs — days synced vs failed over time, which API endpoints fail most often, Garmin API response patterns by time of day. Builds on the Archive Info Panel (v1.3.1) and the quality data in `quality_log.json`. No extra API calls needed.

**Activities dashboard**
Training load, activity volume and sport-specific metrics (swim/bike/run) visualised over time. Activity data is already collected — it just isn't used beyond the summary.

**Test suite & CI/CD**
Core pipeline is covered by five test suites (218 + 134 + 211 + 80 checks + 8 sections for build output). Build integrity is covered by `validate_scripts()` in both build scripts and `test_build_output.py` as post-build gate. Full CI/CD with GitHub Actions for automated builds and release packaging is intentionally deferred — no timeline, no commitment, but the intention is there.

---

## Not planned

> These items are explicitly out of scope for v1.x but may be revisited for v2.0. No timeline, no commitment — but the intention is there.

- Cloud sync or remote access
- Mobile app
- Automatic data sharing, cloud sync, or social comparison features
- GUI and EXE are Windows-only and will remain so. The collector scripts work on Linux and macOS but are untested and unsupported — use at your own risk.
- Code signing or automatic updates

---

*Built with Claude · [☕ buy me a coffee](https://ko-fi.com/wewoc)*
