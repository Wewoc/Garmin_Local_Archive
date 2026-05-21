# Garmin Local Archive — Global Maintenance Guide

Build process, test suite overview, release workflow, and session collaboration process.
For pipeline-specific maintenance see `MAINTENANCE_GARMIN.md` and `MAINTENANCE_CONTEXT.md`.

---

## System Architecture

![System Architecture v1.4.0](../screenshots/flowchart_garmin_v140.png)

> [!TIP]
> **Interactive version:** Open [../screenshots/flowchart_garmin_v140.html](../screenshots/flowchart_garmin_v140.html) in your browser for the full diagram with readable labels.

---

## Dashboard Pipeline

![Dashboard Pipeline v1.4.0](../screenshots/flowchart_dashboard_v140.png)

> [!TIP]
> **Interactive version:** Open [../screenshots/flowchart_dashboard_v140.html](../screenshots/flowchart_dashboard_v140.html) in your browser for the full diagram with readable labels.

---

## Three build targets

| Target | GUI entry point | Daily Sync entry point | Build script | Python on target |
|---|---|---|---|---|
| 1 — Dev | `garmin_app.py` | `python scheduler/daily_update.py` | — | Required |
| 2 — Standard EXE | `garmin_app.py` | `scheduler/daily_update.bat` | `compiler/build.py` | Required |
| 3.1 — Standalone GUI | `garmin_app_standalone.py` | — | `compiler/build_standalone.py` | Not required |
| 3.2 — Standalone headless | — | `daily_update.exe` | `compiler/build_standalone.py` | Not required |

`build_all.py` runs both targets sequentially, preceded by the full test suite.

---

## Building a release

**Target 2:**
```bash
python compiler/build.py
```
Produces `Garmin_Local_Archive.exe` and `Garmin_Local_Archive.zip`.

**Target 3 (T3.1 GUI + T3.2 Headless):**
```bash
python compiler/build_standalone.py
```
Produces `Garmin_Local_Archive_Standalone.exe`, `daily_update.exe`, and `Garmin_Local_Archive_Standalone.zip` (both EXEs combined).

**Both targets (with pre-build tests):**
```bash
python compiler/build_all.py
```

Upload `Garmin_Local_Archive.zip` and `Garmin_Local_Archive_Standalone.zip` to the GitHub release page.

**T2 ZIP layout (`Garmin_Local_Archive.zip`):**
Garmin_Local_Archive.exe
Starte_Daily_Sync.bat       ← user entry point for daily sync
scheduler/
daily_update.py
daily_update.bat
scripts/
garmin_app.py
garmin/ maps/ context/ dashboards/ layouts/
info/
README.md
daily_update_task.xml
`scheduler/` stays at ZIP root — `daily_update.py` uses `.parent.parent` to locate `scripts/`.
`Starte_Daily_Sync.bat` `cd`s into `scheduler/` before calling `daily_update.py`.
When adding new scheduler files: add to `validate_scripts()` in `build.py` **and** to Section 2 + Section 6 in `test_build_output.py`.

---

## Pre-build validation

Both build scripts run `validate_scripts()` before PyInstaller starts:

1. Every required script is present in its folder
2. Key scripts contain expected function/class signatures

| Script | Required signatures |
|---|---|
| `garmin_app.py` | `class GarminApp` |
| `garmin_app_standalone.py` | `class GarminApp` |
| `garmin_api.py` | `def login`, `def fetch_raw` |
| `garmin_collector.py` | `def main`, `def _fetch_and_assess`, `def run_import` |
| `garmin_import.py` | `def load_bulk`, `def parse_day` |
| `garmin_quality.py` | `def _upsert_quality` |
| `garmin_config.py` | `GARMIN_EMAIL` |
| `garmin_security.py` | `def load_token`, `def save_token` |
| `garmin_normalizer.py` | `def normalize`, `def summarize` |
| `garmin_validator.py` | `def validate`, `def reload_schema`, `def current_version` |
| `garmin_writer.py` | `def write_day`, `def read_raw` |
| `garmin_sync.py` | `def get_local_dates`, `def resolve_date_range` |
| `app/garmin_app_settings.py` | `def load_settings`, `def save_settings`, `def load_password`, `def save_password` |
| `app/garmin_app_controller.py` | `def build_env_dict`, `def check_connection`, `def timer_run_repair`, `def timer_run_fill` |

Signature list is defined in `build_manifest.py` as `SCRIPT_SIGNATURES_BASE`.

---

## Adding a new module

Add the filename with subfolder prefix to `SHARED_SCRIPTS` in `build_manifest.py`:
```python
"garmin/garmin_newmodule.py"
"context/new_plugin.py"
"maps/new_map.py"
```
Both builds pick it up automatically. No changes to `build.py` or `build_standalone.py`.

---

## Adding a hidden import

Dynamically loaded modules (via `importlib`) are not detected by PyInstaller automatically. If either build fails with `ImportError` at runtime, add the missing module as a hidden import.

**Target 2 (`build.py`):** add `"--hidden-import", "module_name"` to the `cmd` list in `build_exe()`.

**Target 3 (`build_standalone.py`):** add the missing module to the `hidden` list in `build_exe()`.

Known hidden imports:
- `openpyxl` — required by `dash_plotter_excel.py` (dynamically loaded by `dash_runner.py`)
- `openpyxl.cell._writer` — required by openpyxl internally
- `garminconnect` — T2 only; not auto-detected by PyInstaller (v1.5.4.3)
- `curl_cffi` — transitive dependency of garminconnect 0.3.0+; T2 only (v1.5.4.3)
- `curl_cffi.requests` — transitive dependency of garminconnect 0.3.0+; T2 only (v1.5.4.3)
- `ua_generator` — transitive dependency of garminconnect 0.3.0+; T2 only (v1.5.4.3)

Note: T3 already had these since v1.5.4.1. T2 was missing them — garminconnect showed as "not installed" at runtime despite being installed on the system.

**How to diagnose a missing hidden import:**
In `_load_plotters()` the `except: pass` silently swallows load errors. To surface them temporarily:
```python
except Exception as _e:
    plotters[fmt] = None
    plotters[f"{fmt}_err"] = str(_e)
```
Then log `plotters` via `self._log()` in `garmin_app.py` after `dash_runner._load_plotters()`. The `_err` key shows the exact missing module.

---

## Diagnosing frozen build issues (T2 / T3)

### T2 vs T3 — structural difference

| | T2 (Python required) | T3 (Standalone) |
|---|---|---|
| Scripts location | `scripts/` next to EXE | `sys._MEIPASS/scripts/` (temp, embedded) |
| `sys.frozen` | `True` | `True` |
| `sys._MEIPASS` | exists (temp, EXE only) | exists (temp, all scripts) |
| Distinguish via | `(_MEIPASS / "scripts" / "dashboards" / "dash_runner.py").exists()` → False | same check → True |

### Logging in frozen builds

`logging.warning()` is never visible in the GUI log. For frozen-build diagnostics always use:

- `raise RuntimeError("DIAG: ...")` — surfaces in the `except` block that calls `self._log()`
- `self._log(f"[DIAG] ...")` — direct, requires access to `self`

Never use `logging.warning()` for build-path diagnostics — it disappears silently.

### `__file__` in frozen builds

`Path(__file__).parent` inside a dynamically loaded module (via `importlib.spec_from_file_location`) reflects the path passed to `spec_from_file_location` — not `_MEIPASS`. Verify with `raise RuntimeError(f"DIAG: {__file__!r}")` if path resolution is unclear.

---

## Test suite

### `tests/test_local.py` — Garmin pipeline

```bash
python tests/test_local.py
```

**Current count: 227 checks, 14 sections.** No network, no GUI, no API calls. Cleans up after itself.

Run after any change to: `garmin_config`, `garmin_sync`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`, `garmin_collector`, `garmin_security`, `garmin_utils`, `garmin_validator`.

### `tests/test_local_context.py` — context pipeline

```bash
python tests/test_local_context.py
```

**Current count: 217 checks, 11 sections.** No network — Open-Meteo API is mocked. Cleans up after itself.

Run after any change to: `context_collector`, `context_api`, `context_writer`, `weather_plugin`, `pollen_plugin`, `weather_map`, `pollen_map`, `context_map`.

### `tests/test_dashboard.py` — Dashboard pipeline

```bash
python tests/test_dashboard.py
```

**Current count: 303 checks, 16 sections.** No network, no GUI. Covers full pipeline: `garmin_map` intraday normalization → brokers → layout resources → all specialists → all plotters → runner.

Run after any change to: `garmin_map`, `field_map`, `context_map`, `dash_layout`, `dash_layout_html`, `reference_ranges`, any `*_dash.py` specialist, any `dash_plotter_*`.

### Plotly local cache

`layouts/plotly.min.js` is downloaded automatically on the first dashboard build that produces HTML output. An internet connection is required for this one-time download. After that, all HTML dashboards are fully offline — no CDN dependency.

If the file needs to be refreshed (e.g. after a Plotly version update), delete `layouts/plotly.min.js` and run any HTML dashboard build once.

For EXE builds: `plotly.min.js` is listed in `REQUIRED_DATA_FILES` in `build_manifest.py` and is bundled automatically — provided it has been downloaded at least once before building.

### `tests/test_app_logic.py` — App layer

```bash
python tests/test_app_logic.py
```

**Current count: 128 checks, 18 sections.**

### `tests/test_qt_app.py` — PyQt6 App layer (v1.5.4+)

```bash
pytest tests/test_qt_app.py -v
# or via: tests/run_qt_tests.bat
```

**Current count: 41 checks, 6 classes.** Requires `pytest`, `pytest-qt`, `PyQt6` (all in `requirements.txt`). Tests Qt-specific behaviour — panel instantiation, Signal/Slot contracts, widget state, cross-thread dispatch patterns. Does NOT duplicate `test_app_logic.py` — that suite covers Settings/Controller logic which remains tkinter-free.

Classes:
- `TestQtSmoke` (3) — QApplication startup, PyQt6 importability, GUI-freedom regression for Settings/Controller
- `TestPanelSettings` (5) — instantiation, `_collect_settings()` keys, sync mode switching, location extraction
- `TestPanelConnection` (10) — instantiation, indicators, accessor methods, Signal class-level definition
- `TestPanelArchive` (5) — instantiation, mirror guard, archive info no-crash, failed-days popup
- `TestPanelTimer` (7) — instantiation, field load/read, toggle on/off, resume logic
- `TestPanelOutputs` (7) — instantiation, context sync state, stop event, no-crash helpers

Run after any change to: `app/panel_*.py`, `garmin_app_base.py` (Qt version). Built panel-by-panel alongside the v1.5.4 migration. No network, no GUI, no build required. Tests `app/garmin_app_settings.py` (settings persistence, keyring helpers, OSError handling), `app/garmin_app_controller.py` (build_env_dict, timer functions, check_integrity), `garmin_app_base.py` (hook implementation, delegation), `garmin_app.py` and `garmin_app_standalone.py` (script path resolution in dev and frozen mode, hook overrides), `app/panel_timer.py` (timer_run_bulk_recheck functional test). Includes v1.4.2 regression check for frozen path resolution. Section 14: `_timer_run_bulk_recheck` tested against `PanelTimerMixin` directly (v1.5.3). Section 15: AST-test verifies tkinter/Qt-freedom of app/garmin_app_settings.py and app/garmin_app_controller.py.

Run after any change to: `garmin_app_base.py`, `garmin_app.py`, `garmin_app_standalone.py` (module-level functions only). Not part of the automated pre-build gate — run manually.

### `tests/test_build_output.py` — Build output validation

```bash
python tests/test_build_output.py
```

**309 checks, 8 sections.** Sections 1–2 always run (no build required): `build_manifest` consistency + source integrity. Sections 3–8 run after a completed build: Target 2 EXE + `scripts/` structure + `py_compile` syntax check + ZIP contents; Target 3 EXE + ZIP; embed path reconstruction for Standalone (`--add-data` destination paths verified against manifest). `build_manifest` is imported from `compiler/`.

Run after: called automatically by `build_all.py` as post-build step. Can also be run standalone to verify source integrity without a build.

### All suites together

`compiler/build_all.py` runs all three pre-build test suites, then both builds, then `test_build_output.py` as post-build validation.

```bash
python compiler/build_all.py
# Pre-build:  test_local → test_local_context → test_dashboard
# Build:      Target 2 → Target 3
# Post-build: test_build_output → test_app_logic
```

`test_app_logic.py` runs automatically as the final post-build step in `build_all.py`, after `test_build_output.py`. Can also be run standalone after changes to the entry point files.

---

## Package structure

All source folders are Python packages with `__init__.py`:
- `garmin/` — Garmin pipeline
- `context/` — external API collect pipeline
- `maps/` — data brokers
- `dashboards/` — dashboard specialists (v1.4+)
- `layouts/` — format renderers (v1.4+)
- `app/` — GUI logic layer (v1.5.2+): settings, controller, panel Mixins (v1.5.3+)

**Import pattern:**
- Entry points (`garmin_app.py`, `tests/`) use `sys.path.insert` to reach `garmin/`
- Within packages, use relative imports (`from . import module`)
- `maps/` and `context/` modules that need `garmin_config` use `sys.path.insert` to bridge to `garmin/`

---

## Module path resolution

| Location | sys.path setup |
|---|---|
| `garmin_app.py` — Dev | all subfolders inserted: `garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/`, `app/` |
| `scheduler/daily_update.py` — Dev/T2 | sys.path root anchor at top (before `from version import`); same subfolder loop from `parent.parent`; `context` additionally registered as `types.ModuleType` in `sys.modules` |
| `daily_update.exe` — T3.2 frozen | `scripts/` + `scripts/garmin/` in `sys.path`; all package subdirs (`dashboards/`, `layouts/`, `maps/`, `context/`) registered in `sys.modules` **and** added to `sys.path` — required for flat imports (`import dash_runner`) |
| `garmin_app.py` — T2 frozen | same subfolders from `scripts/` next to EXE |
| `garmin_app_standalone.py` — Dev | same subfolder loop (incl. `app/`) |
| `garmin_app_standalone.py` — T3 frozen | `garmin/` via `sys.path.insert` in `_register_embedded_packages()`; others via package registration |
| `tests/test_local.py` | `sys.path.insert(0, .../garmin)` |
| `tests/test_local_context.py` | `sys.path.insert(0, .../garmin)` + `sys.path.insert(0, root)` |
| `maps/garmin_map.py` | `sys.path.insert(0, .../garmin)` — bridge between packages |
| `context/` plugins | `sys.path.insert(0, .../garmin)` — for `garmin_config` |
| All modules inside `garmin/` | None — `sys.path.insert` removed in v1.4 |

⚠ When adding a new subfolder: add it to the `sys.path` loop in both entry points **and** to `_register_embedded_packages()` in `garmin_app_standalone.py`.

---

## script_path() resolution (EXE targets)

- **Target 2 frozen:** iterates `scripts/garmin/`, `scripts/maps/`, `scripts/dashboards/`, `scripts/layouts/`, `scripts/context/`, `scripts/export/` — returns first match, fallback `scripts/name`
- **Target 3 frozen:** iterates `scripts/garmin/`, `scripts/maps/`, `scripts/dashboards/`, `scripts/layouts/`, `scripts/context/`, `scripts/export/` — returns first match, fallback `scripts/name`
- **Dev (both):** iterates same subfolder list relative to `Path(__file__).parent`, fallback `script_dir() / name`

Note: Dashboard build (`dash_runner`) runs in-process — no `script_path()` involved. `dash_runner.py` is loaded via `importlib` directly from `dashboards/`.

⚠ When adding a new subfolder: add it to the iteration list in `script_path()` in **both** `garmin_app.py` and `garmin_app_standalone.py`.

---

## Session workflow

### Task workflow — three mandatory steps

Every new task follows this sequence. No step is skipped.
No build order without prior analysis. No analysis without prior scope assessment.

```
Step 1 — Assess idea       → clarify scope, name risks, make decision
Step 2 — Analysis order    → research / review / pre-clarification
Step 3 — Build order       → implementation with complete specs
```

The full prompt patterns for each step are in `WORKFLOW_TEMPLATE.md`.

**Emergency brake:** If the data flow is no longer traceable or a dependency
is missing mid-implementation:

```
Stop — check [what seems off]
```

Two words. No further context needed. Resets the session to the last confirmed state.

---

### Notes file

Create `NOTES_vX_Y_Z.md` at session start. Update after every delivery. Three blocks:

```markdown
## ✅ Done
## ❌ Not done (with reason)
## 🔒 Decisions & rationale
```

### Before every implementation — cross-dependency check

> **"Which modules, dialogs, or documentation sections implicitly assume the old behaviour — and which will be affected by the new behaviour?"**

- What assumes the *old* behaviour? → breaks silently
- What is affected by the *new* behaviour? → must be explicitly updated
- For every new behaviour: **"Which other threads access the same resource?"**

These four questions map to universal engineering invariants:

| Question | Maps to | GLA implementation |
|---|---|---|
| Where does state live? | Ownership & truth | Sole-Write-Authority — `garmin_writer.py` owns raw/ + summary/, `garmin_quality.py` owns quality_log.json, `context_writer.py` owns context_data/. No overlap. |
| Where does feedback live? | Observability | `quality_log.json` + DEBUG logging through all pipeline layers |
| What breaks if I delete this? | Coupling & fragility | Cross-dependency check before every build — mandatory, not optional |
| When does timing work? | Async & ordering | Thread-lock check for every shared resource access — explicit question in pre-build checklist |

### During every implementation — dependency transparency (mandatory)

List all new or changed dependencies explicitly:
- **New imports** — which module imports what for the first time?
- **Changed return values** — type, structure, fields
- **Shifted responsibilities** — does a module suddenly write where it didn't before?
- **Changed call sites** — has the interface changed, who calls it?

### Closing checklist

**Code:**
- [ ] All new modules in `build_manifest.py` (`SHARED_SCRIPTS`)?
- [ ] All new modules in README script table?
- [ ] All new modules in REFERENCE_GLOBAL (project structure + App constants)?
- [ ] `APP_VERSION` updated in `version.py`?
- [ ] All new modules in MAINTENANCE_GLOBAL (test suite description)?

**Documentation:**
- [ ] All new ENV variables in REFERENCE_GLOBAL?
- [ ] All changed function signatures in relevant REFERENCE file?
- [ ] Test count updated in MAINTENANCE_GLOBAL + ROADMAP?
- [ ] Stale "planned for vX.Y.Z" references removed?
- [ ] GUI text in README_APP current?
- [ ] Version number in README updated?

### Documentation closure order

CHANGELOG → ROADMAP → REFERENCE_GLOBAL → REFERENCE_GARMIN → REFERENCE_CONTEXT →
MAINTENANCE_GLOBAL → MAINTENANCE_GARMIN → MAINTENANCE_CONTEXT →
README → README_APP → WORKFLOW_TEMPLATE (if process changed) →
START_PROMPT for next session

---

---

## AI Collaboration Workflow

This section documents how Garmin Local Archive was built and how the AI collaboration
is structured. It is intended for contributors and anyone who wants to understand the
development process — not just the code.

### Philosophy

Architecture is the developer's job. Implementation is the AI's job.

The developer defines what goes in, what comes out, what happens where — like designing
a material flow system. The AI translates that logic into code. Architectural mistakes
are always the developer's responsibility, regardless of who wrote the code.

This separation only works if the AI is kept on a short leash. Every session follows
the same structure: assess first, decide second, build third. Never the other way around.

### The three-document system

Every session loads three documents before any work begins:

| Document | Purpose |
|---|---|
| `START_PROMPT_base.md` | Stable project context — architecture, invariants, rules |
| `Session_Prompt_vX.Y.Z.md` | Version-specific scope and task list |
| `WORKFLOW_TEMPLATE.md` | Prompt patterns for assess / analyze / build |

Claude reads these before touching any code. Rules tell it how to work. Docs tell it
what exists. Both are required — neither replaces the other.

### Task workflow — assess → analyze → build

Every change follows three mandatory steps. No step is skipped.

NEU:
```markdown
**Step 1 — Assess**
```
Assess — [Title]
Bewerten — [Title]
Idea: [What should be built / changed]
Motivation: [Why]
Only assess, do not implement yet.
To clarify:

Does this fit the current scope or belong in a later version?
Which modules / files would be affected?
Are there dependencies or risks to clarify first?


**Step 2 — Analyze** (only when Step 1 recommends it)
Analyse — [Module / API / Feature]
Only review, do not change anything.
Scope: [Which files / areas to check]

NEU:
```markdown
**Step 3 — Build** (only after explicit confirmation from Step 1 or 2)
```
Build — [What is being built]
Bauauftrag — [What is being built]
Read project context: [list of files to read first]
TASK
[New files to create]
[Existing files to change]
SPECS
[Complete technical details — no assumptions]
RULES

Do not touch anything outside the stated scope
Assess first if an architecture decision is open
Cross-dependency check before delivery


### Emergency brake

If the data flow is no longer traceable or a dependency is missing mid-implementation:
Stop — check [what seems off]

Two words. No further context needed. Resets the session to the last confirmed state.
Used over 200 times across the project's development history.

### Multi-LLM review

Architecture decisions are reviewed across multiple models:

- **Claude** — primary implementation partner, reality-check
- **Gemini** — generative exploration, first-pass critique
- **ChatGPT / Copilot / Le Chat** — additional review passes

The intersection of findings across models is treated as signal. One model flagging
something is noise. Three models flagging the same thing is a real issue.

Tests are written by one model and reviewed by another without project context.
Regressions introduced by later model iterations are caught by the static test suite.

### Closing prompt — 11-step checklist

Every session ends with a defined documentation closure. The full checklist is in
`FINAL_DOKU_PROMPT.md`. In short:

1. `version.py` — update APP_VERSION
2. `CHANGELOG.md` — new entry at top
3. `ROADMAP.md` — mark released, add new notes
4. `build_manifest.py` — new / removed modules
5. `REFERENCE_*.md` — updated signatures, paths, invariants
6. `MAINTENANCE_*.md` — updated test counts, ownership
7. `README.md` — user-visible changes
8. `README_APP.md` — GUI changes, version number
9. Run all test suites — all green before closing
10. `NOTES_vX.Y.Z.md` — finalize decisions and rationale
11. `START_PROMPT` for next version

Docs are updated to current state, not extended. Stale entries do not survive session close.

### Key metrics (as of v1.5.x)

- Started: March 17, 2026
- Sessions: ~200+
- Scope-brake interventions ("Stop — check"): 200+
- Ratio of planning / architecture to implementation: approximately 1:1
- Test suite: 850+ checks across 4 suites
- Build targets: 3 (dev / standard EXE / standalone EXE)

### Further reading

| Document | Location |
|---|---|
| Base context and invariants | `docs/START_PROMPT_base.md` |
| Prompt patterns | `docs/WORKFLOW_TEMPLATE.md` |
| Session closing checklist | `docs/FINAL_DOKU_PROMPT.md` |
| Version-specific session notes | `docs/NOTES_vX_Y_Z.md` |

---

## Common issues

### Pylance / VS Code import warning

The `garminconnect` import warning is cosmetic. Click the interpreter selector (bottom right in VS Code) and match it to `where python` in the terminal.

### Data folder

`BASE_DIR/garmin_data/` and `BASE_DIR/context_data/` are never touched automatically — delete manually if no longer needed.

### Standalone EXE startup fails

Check that all modules in `build_manifest.py` `SHARED_SCRIPTS` are present in their correct subfolders. Run `validate_scripts()` manually via `python build.py` to get a clear error message.

### Archive Status shows `—` in EXE (T2 or T3)

Symptom: GUI shows `Days: —`, `high —` etc. after startup. No error in log.

Root cause: `_refresh_archive_info()` catches all exceptions silently (`except Exception: return`). Any `ImportError` on `garmin_quality` or a wrong `base_dir` path disappears without trace.

Checklist:
1. **T2:** Is `scripts/garmin/garmin_quality.py` present next to the EXE?
2. **T3:** Does `_register_embedded_packages()` insert `garmin/` into `sys.path`?
3. **Both:** Does the Data folder in Settings point to the correct path (must contain `garmin_data/log/quality_log.json`)?

To surface the actual error temporarily, change `_refresh_archive_info()`:
```python
except Exception as e:
    self._log(f"[DIAG] _refresh_archive_info: {e}")
    return
```
Remove the `[DIAG]` line after diagnosis.
