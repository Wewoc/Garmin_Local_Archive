# Garmin Local Archive — Dashboard Pipeline Maintenance Guide

Maintenance, extension, and debugging guide for the dashboard pipeline (`dashboards/`, `layouts/`).
For build and release process see `MAINTENANCE_GLOBAL.md`.
For complete interface reference see `REFERENCE_DASHBOARD.md`.

---

## Pipeline architecture

```
garmin_app.py (GUI)
  └── dash_runner.build()
        ├── specialist.build()     ← once per specialist
        │     ├── field_map.get()
        │     └── context_map.get()
        └── plotter.render()       ← once per format
```

### Module ownership

| Module | Responsibility |
|---|---|
| `dash_runner.py` | Discovery, orchestration, plotter registry |
| `*_dash.py` specialists | Data fetch via brokers, neutral dict assembly |
| `dash_plotter_*.py` plotters | Rendering only — no data knowledge |
| `dash_layout.py` | Passive: color tokens, metric metadata, disclaimer, footer |
| `dash_layout_html.py` | Passive: HTML CSS, Plotly CDN, template builders |
| `reference_ranges.py` | Passive: age/sex/fitness reference range calculations |

### Invariants

- `specialist.build()` called once per specialist — data fetched once, rendered N times
- Plotters import only from `dash_layout` and `dash_layout_html` — never from specialists or brokers
- `reference_ranges.py` has no imports beyond stdlib — safe to import anywhere
- `maps/` modules: no writes, no API calls, routing only

---

## Adding a new specialist

1. Create `dashboards/your_name_dash.py`
2. Define `META` with `name`, `description`, `source`, `formats`
3. Implement `build(date_from, date_to, settings) -> dict`
4. Use `field_map.get()` and/or `context_map.get()` — no direct file access
5. Return neutral dict — no rendering logic
6. Add to `build_manifest.py` → `SHARED_SCRIPTS`
7. Add test section in `tests/test_dashboard.py`
8. Update `REFERENCE_DASHBOARD.md` → specialist return dict section
9. Update `MAINTENANCE_GLOBAL.md` → project structure + test count

**Auto-discovery:** `dash_runner.scan()` picks up any `*_dash.py` file automatically — no registration needed in `dash_runner.py`.

**Using `html_complex` with Explorer layout:** set `"layout": "explorer"` in the specialist return dict. `dash_plotter_html_complex.render()` detects the key and dispatches to `_render_explorer()`. No changes to the plotter needed for additional Explorer-style specialists.

---

## Adding a new plotter

1. Create `layouts/dash_plotter_yourformat.py`
2. Implement `render(data, output_path, settings) -> None`
3. Raise `ValueError` for missing/empty data, `OSError` for write failures
4. Import only from `dash_layout` and `dash_layout_html` — not from specialists
5. Register format key in `dash_runner._load_plotters()` plotter map
6. If the format key needs a display alias, add it to `dash_runner.display_label()`
7. Add to `build_manifest.py` → `SHARED_SCRIPTS`
8. Add test coverage in `tests/test_dashboard.py`
9. Update `REFERENCE_DASHBOARD.md` → plotter registry table

---

## Adding a new format target to an existing specialist

1. Add entry to specialist `META["formats"]`: `"format_key": "output_filename"`
2. Ensure a plotter is registered for that format key in `dash_runner._load_plotters()`
3. If format key needs a display alias: update `dash_runner.display_label()`
4. Test via `dash_runner.build()` with the new format selected

---

## Adding a new metric to `dash_layout.py`

1. Add entry to `METRIC_META` dict: `"field_key": {"label": str, "unit": str, "color": str}`
2. Add entry to `EXCEL_ROW_COLORS` if the field appears in Excel output
3. No other changes needed — plotters call `get_metric_meta()` dynamically

---

## Extending reference ranges

`layouts/reference_ranges.py` covers: `hrv_last_night`, `resting_heart_rate`, `spo2_avg`, `sleep_duration`, `body_battery_max`, `stress_avg`.

To add a new field:
1. Add the field key and `(low, high)` tuple to the return dict in `reference_ranges()`
2. Both `health_garmin_html-json_dash` and `sleep_recovery_context_dash` import from here — check both after changes

---

## Plotly local cache

`layouts/plotly.min.js` is downloaded automatically on the first HTML dashboard build. Required for all HTML output. Internet connection needed once.

- To refresh: delete `layouts/plotly.min.js`, run any HTML dashboard build
- For EXE builds: listed in `build_manifest.py` → `REQUIRED_DATA_FILES` — must exist before building

---

## Test suite — `tests/test_dashboard.py`

```bash
python tests/test_dashboard.py
```

**Current count: 214 checks, 13 sections.**

Note: `explorer_garmin-context_html_dash` is discovered by `dash_runner.scan()` and covered by section 7 (auto-discovery). Dedicated specialist tests to be added in a later session.

| Section | Coverage |
|---|---|
| 1 | `garmin_map` intraday normalization |
| 2 | `field_map` routing |
| 3 | `dash_layout` design tokens |
| 4 | `dash_layout_html` HTML assets |
| 5 | `timeseries_garmin` specialist + plotter |
| 6 | `dash_plotter_html` render |
| 7 | `dash_runner` scan + build |
| 8 | `dash_plotter_excel` render |
| 9 | `dash_plotter_json` render |
| 10 | `health_garmin` specialist |
| 11 | `overview_garmin` specialist |
| 12 | `health_garmin-weather-pollen` specialist |
| 13 | `sleep_recovery_context` specialist + complex plotter |

Run after any change to: `garmin_map`, `field_map`, `context_map`, `dash_layout`, `dash_layout_html`, any `*_dash.py` specialist, any `dash_plotter_*`, `reference_ranges.py`.

---

## Diagnosing plotter load failures

In `_load_plotters()` the `except: pass` silently swallows load errors. To surface them:

```python
except Exception as _e:
    plotters[fmt] = None
    plotters[f"{fmt}_err"] = str(_e)
```

Then log `plotters` after `dash_runner._load_plotters()`. The `_err` key shows the exact error.

---

## Common issues

### New specialist not appearing in GUI popup

- Filename must end in `_dash.py`
- `META` must be a dict with `"formats"` key
- At least one format in `META["formats"]` must have a registered plotter in `_load_plotters()`
- File must be in `dashboards/` directory

### Dashboard builds successfully but output file is empty or malformed

- Check `plotter.render()` — `ValueError` is caught and logged as `success=False`
- Check specialist return dict structure against `REFERENCE_DASHBOARD.md`
- Verify `field_map.get()` returns expected structure for the date range

### `html_mobile` not appearing in GUI for Health Analysis

- Confirm `"html_mobile"` is in `META["formats"]` in `health_garmin_html-json_dash.py`
- Confirm `dash_plotter_html_mobile.py` exists in `layouts/`
- Confirm `"html_mobile"` is registered in `dash_runner._load_plotters()` plotter map

### Auto-size subtitle not showing

- Auto-size only triggers if actual data boundaries are narrower than the requested range
- Check that the specialist returns `"subtitle"` key in its dict
- Overview specialist: Excel plotter currently ignores `subtitle` — expected behaviour
