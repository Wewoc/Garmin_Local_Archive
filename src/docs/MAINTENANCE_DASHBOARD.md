# Garmin Local Archive — Dashboard Pipeline Maintenance Guide

Maintenance, extension, and debugging guide for the dashboard pipeline (`dashboards/`, `layouts/`).
For build and release process see `MAINTENANCE_GLOBAL.md`.
For the specialist/plotter interface reference see `REFERENCE_DASHBOARD.md`.
For the broker request/response contract see `REFERENCE_BROKER.md`.

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
| `dash_encryptor.py` | Sole Owner: HTML encryption for Encrypted Dashboard Export (v1.6.1+) |

### Invariants

- `specialist.build()` called once per specialist — data fetched once, rendered N times
- Plotters import only from `dash_layout` and `dash_layout_html` — never from specialists or brokers
- `reference_ranges.py` has no imports beyond stdlib — safe to import anywhere
- `maps/` modules: no writes, no API calls, routing only

---

## Known pitfalls

### Plotly load order in inline renderers
When embedding Plotly inline in a renderer (`layouts/render/*.py`), the
`plotly_script` block **must appear before** any `<script>` block that calls
`Plotly.react()` or `Plotly.newPlot()`. The explorer script executes
immediately on page load — if Plotly is not yet defined at that point, the
call fails silently and the chart never renders. No error in the console, no
visual feedback.

Correct order in the HTML assembly f-string:
2. Define `META` with `name`, `description`, `source`, `formats`
3. Implement `build(date_from, date_to, settings) -> dict`
4. Use `field_map.get()` and/or `context_map.get()` — no direct file access
5. Return neutral dict — no rendering logic
6. Add to `build_manifest.py` → `SHARED_SCRIPTS`
7. Add test section in `tests/test_dashboard.py`
8. Update `REFERENCE_DASHBOARD.md` → specialist return dict section
9. Update `MAINTENANCE_GLOBAL.md` → project structure + test count

**Auto-discovery:** `dash_runner.scan()` picks up any `*_dash.py` file automatically — no registration needed in `dash_runner.py`.

**Using `html_complex` with a new layout:** set `"layout": "<key>"` in the specialist return dict.
Add one entry to `_REGISTRY` in `dash_plotter_html_complex.py` and create `layouts/render/<key>.py`
with `render(data, output_path) -> None`. No changes to the plotter's `render()` function needed.
Existing specialists (`"explorer"`, `"sleep"`, `None`) are unchanged.

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

**Output safety (v1.6.0.4.4, A5):** any specialist-sourced text field
(label, unit, date, qualifier, feedback, etc.) must never be interpolated
raw into an HTML tag or a JS string literal. For HTML context, use
`html.escape()`. For JS string literals inside generated `<script>` blocks
(e.g. Plotly `name`/`hovertemplate`), use `json.dumps()` instead of direct
f-string interpolation — this also produces the correct surrounding quotes.
For HTML assembled at JS runtime via `innerHTML` (not via Python f-strings),
use a JS-side escape helper instead — see `_escapeHtml()` in
`dash_plotter_html_complex.py` for the existing pattern. Avoid naming a
Python variable `html` in any module that also `import html` — naming
collisions with the stdlib module raise `UnboundLocalError` (see A5 fix,
CHANGELOG v1.6.0.4.4).

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

**Current count: 445 checks, 21 sections.**

| Section | Coverage |
|---|---|
| 1 | `garmin_map` intraday normalization |
| 2 | `field_map` routing |
| 3 | `dash_layout` design tokens |
| 4 | `dash_layout_html` HTML assets |
| 5 | `timeseries_garmin` specialist + plotter |
| 6 | `dash_plotter_html` render |
| 7 | `dash_runner` scan + build — incl. 3 visible-skip paths (load error, bad/missing META, no matching formats) |
| 8 | `dash_plotter_excel` render |
| 9 | `dash_plotter_json` render |
| 10 | `health_garmin` specialist |
| 11 | `overview_garmin` specialist |
| 12 | `health_garmin-weather-pollen` specialist |
| 13 | `sleep_recovery_context` specialist + complex plotter (facade + render registry v1.6.0.5) |
| 14 | `sleep_garmin` specialist + html + excel render — rows carry `hrv_7d_avg` (computed in build, rendered in both plotters). Phase bar cells carry letter labels (D/L/R/A) in contrast color (v1.5.8+) |
| 15 | `garmin_map` broker contract — incl. `live`/`live_pct`/`live_nested` routes (v1.6.5): percentage math, nested lookup + HRV fallback chain + divisor, missing-file behaviour for both types, field-without-live-route negative case |
| 15b | `layouts/render/live.py` — Live Tracking renderer (v1.6.5): structure (DOCTYPE, title, disclaimer, footer), no-Plotly check, integer formatting (no stray `.0`), qualifier badge, feedback label, phase-bar legend, dark-theme token, archive-fallback note, `ValueError` on missing `today`/`last_night` |
| 16 | Specialist return contract — alle 7 specialists |
| 17 | `dash_encryptor` — `encrypt_html()` output structure, ValueError guards |
| 18 | `heatmap_garmin` specialist + complex plotter — six metrics pivoted to date×hour matrices, tab navigation, ValueError guard (v1.6.3.1) |
| 19 | `custom_dash_builder` — `list_available_fields()` exclusions, ad-hoc module contract (`.META`/`.build`/`.__name__`), integration with `dash_runner.build()` using no file on disk (v1.6.4) |
| 20 | `garmin_dashboard_presets` — `load_presets()`/`save_preset()`/`delete_preset()` round-trip, missing-file default, no-op delete (v1.6.4) |

**Broker contract (section 15):** `garmin_map.get()` gibt immer `values` (list), `fallback` (bool), `source_resolution` (str) zurück. Unbekanntes Feld → `KeyError`. Ungültige Resolution → `ValueError`. Gilt analog für `weather_map` und `pollen_map` — getestet in `test_local_context.py`.

**Specialist return contract (section 16):** Jeder `build()`-Call wird mit synthetischen Daten ausgeführt. Pflicht-Keys pro Specialist: siehe REFERENCE_DASHBOARD.md → Specialist return dicts.

Run after any change to: `garmin_map`, `field_map`, `context_map`, `dash_layout`, `dash_layout_html`, any `*_dash.py` specialist, any `dash_plotter_*`, any `layouts/render/*.py`, `reference_ranges.py`, `garmin_live_fetch.py` (via the live-route sections above).

---

## Diagnosing plotter load failures

If a plotter fails to load, `_load_plotters()` stores the error string under
`plotters["{fmt}_err"]` instead of raising. The format key itself (`"html"`, `"excel"`)
remains absent — `scan()` silently skips the format, `build()` returns a result with
`success=False` and the exact import error in the `"error"` field.

To inspect errors during development, log `plotters` after `_load_plotters()`:
any key ending in `_err` signals a load failure for that format.

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
