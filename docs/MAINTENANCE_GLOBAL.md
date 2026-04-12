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

## Dashboard Pipeline

![Dashboard Pipeline v1.4.0](flowchart_dashboard_v140.png)

> [!TIP]
> **Interactive version:** Open [flowchart_dashboard_v140.html](flowchart_dashboard_v140.html) in your browser for the full diagram with readable labels.

---

## Three build targets

| Target | Entry point | Build script | Output | Python on target |
|---|---|---|---|---|
| 1 — Dev | `garmin_app.py` | — (run directly) | — | Required |
| 2 — Standard EXE | `garmin_app.py` | `build.py` | `Garmin_Local_Archive.exe` | Required |
| 3 — Standalone EXE | `garmin_app_standalone.py` | `build_standalone.py` | `Garmin_Local_Archive_Standalone.exe` | Not required |

`build_all.py` runs both targets sequentially, preceded by the full test suite.

---

## Building a release

**Target 2:**
```bash
python build.py
```
Produces `Garmin_Local_Archive.exe` and `Garmin_Local_Archive.zip`.

**Target 3:**
```bash
python build_standalone.py
```
Produces `Garmin_Local_Archive_Standalone.exe` and `Garmin_Local_Archive_Standalone.zip`.

**Both targets (with pre-build tests):**
```bash
python build_all.py
```

Upload both ZIPs to the GitHub release page.

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
| `garmin_collector.py` | `def main`, `def _process_day`, `def run_import` |
| `garmin_import.py` | `def load_bulk`, `def parse_day` |
| `garmin_quality.py` | `def _upsert_quality` |
| `garmin_config.py` | `GARMIN_EMAIL` |
| `garmin_security.py` | `def load_token`, `def save_token` |
| `garmin_normalizer.py` | `def normalize`, `def summarize` |
| `garmin_validator.py` | `def validate`, `def reload_schema`, `def current_version` |
| `garmin_writer.py` | `def write_day`, `def read_raw` |
| `garmin_sync.py` | `def get_local_dates`, `def resolve_date_range` |

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

**Current count: 199 checks, 13 sections.** No network, no GUI, no API calls. Cleans up after itself.

Run after any change to: `garmin_config`, `garmin_sync`, `garmin_normalizer`, `garmin_quality`, `garmin_writer`, `garmin_collector`, `garmin_security`, `garmin_utils`, `garmin_validator`.

### `tests/test_local_context.py` — context pipeline

```bash
python tests/test_local_context.py
```

**Current count: 123 checks, 11 sections.** No network — Open-Meteo API is mocked. Cleans up after itself.

Run after any change to: `context_collector`, `context_api`, `context_writer`, `weather_plugin`, `pollen_plugin`, `weather_map`, `pollen_map`, `context_map`.

### `tests/test_dashboard.py` — Dashboard pipeline

```bash
python tests/test_dashboard.py
```

**Current count: 166 checks, 12 sections.** No network, no GUI. Covers full pipeline: `garmin_map` intraday normalization → brokers → layout resources → all specialists → all plotters → runner.

Run after any change to: `garmin_map`, `field_map`, `context_map`, `dash_layout`, `dash_layout_html`, any `*_dash.py` specialist, any `dash_plotter_*`.

### Plotly local cache

`layouts/plotly.min.js` is downloaded automatically on the first dashboard build that produces HTML output. An internet connection is required for this one-time download. After that, all HTML dashboards are fully offline — no CDN dependency.

If the file needs to be refreshed (e.g. after a Plotly version update), delete `layouts/plotly.min.js` and run any HTML dashboard build once.

For EXE builds: `plotly.min.js` is listed in `REQUIRED_DATA_FILES` in `build_manifest.py` and is bundled automatically — provided it has been downloaded at least once before building.

### All suites together

`build_all.py` runs all three test suites before starting either build. If any fails, the build is aborted.

---

## Package structure

All source folders are Python packages with `__init__.py`:
- `garmin/` — Garmin pipeline
- `context/` — external API collect pipeline
- `maps/` — data brokers
- `dashboards/` — dashboard specialists (v1.4+)
- `layouts/` — format renderers (v1.4+)

**Import pattern:**
- Entry points (`garmin_app.py`, `tests/`) use `sys.path.insert` to reach `garmin/`
- Within packages, use relative imports (`from . import module`)
- `maps/` and `context/` modules that need `garmin_config` use `sys.path.insert` to bridge to `garmin/`

---

## Module path resolution

| Location | sys.path setup |
|---|---|
| `garmin_app.py` — Dev | all subfolders inserted: `garmin/`, `maps/`, `dashboards/`, `layouts/`, `context/` |
| `garmin_app.py` — T2 frozen | same subfolders from `scripts/` next to EXE |
| `garmin_app_standalone.py` — Dev | same subfolder loop |
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
- **Target 3 frozen:** `script_dir() / name` only — all scripts flat in `sys._MEIPASS/scripts/`
- **Dev (both):** iterates same subfolder list relative to `Path(__file__).parent`, fallback `script_dir() / name`

Note: Dashboard build (`dash_runner`) runs in-process — no `script_path()` involved. `dash_runner.py` is loaded via `importlib` directly from `dashboards/`.

⚠ When adding a new subfolder: add it to the iteration list in `script_path()` in **both** `garmin_app.py` and `garmin_app_standalone.py`.

---

## Session workflow

### Notes file

Create `NOTES_vX_Y_Z.md` at session start. Update after every delivery. Three blocks:

```markdown
## ✅ Umgesetzt
## ❌ Nicht umgesetzt (mit Begründung)
## 🔒 Entscheidungen & Begründungen
```

### Before every implementation — cross-dependency check

> **"Which modules, dialogs, or documentation sections implicitly assume the old behaviour — and which will be affected by the new behaviour?"**

- What assumes the *old* behaviour? → breaks silently
- What is affected by the *new* behaviour? → must be explicitly updated
- For every new behaviour: **"Which other threads access the same resource?"**

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
- [ ] All new modules in REFERENCE (own file)?
- [ ] All new modules in MAINTENANCE (project structure)?

**Documentation:**
- [ ] All new ENV variables in REFERENCE_GLOBAL?
- [ ] All changed function signatures in relevant REFERENCE file?
- [ ] Test count updated in MAINTENANCE_GLOBAL + ROADMAP?
- [ ] Stale "planned for vX.Y.Z" references removed?
- [ ] GUI text in README_APP + README_APP_Standalone current?
- [ ] Version number in README updated?

### Documentation closure order

CHANGELOG → ROADMAP → REFERENCE_GLOBAL → REFERENCE_GARMIN → REFERENCE_CONTEXT → MAINTENANCE_GLOBAL → MAINTENANCE_GARMIN → MAINTENANCE_CONTEXT → README → README_APP → README_APP_Standalone → START_PROMPT for next session

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
