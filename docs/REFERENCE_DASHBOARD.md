# Garmin Local Archive — Dashboard Pipeline Reference

Technical reference for the dashboard pipeline (`dashboards/`, `layouts/`).
For shared paths, constants, and project structure see `REFERENCE_GLOBAL.md`.

---

## Pipeline overview

```
garmin_app.py (GUI)
  └── dash_runner.build()
        ├── specialist.build(date_from, date_to, settings)  ← data fetch, once per specialist
        │     ├── field_map.get()                           ← Garmin data via broker
        │     └── context_map.get()                        ← context data via broker (if needed)
        └── plotter.render(data, output_path, settings)     ← once per selected format
```

**Invariants:**
- `specialist.build()` is called once per specialist regardless of how many formats are selected
- Plotters have no knowledge of Garmin internals, field names, or data sources
- `maps/` modules are routing-only — no writes, no API calls
- `dash_layout.py` and `dash_layout_html.py` are passive resources — no logic, no file I/O
- `layouts/reference_ranges.py` is a passive resource — no file I/O, no imports beyond stdlib

---

## `dash_runner.py`

| Function | Purpose |
|---|---|
| `scan()` | Scans `dashboards/` for all `*_dash.py` files. Returns list of specialist descriptors. Specialists with missing or malformed `META` are skipped. Only formats with a registered plotter are exposed. |
| `build(selections, date_from, date_to, settings, output_dir, log)` | Orchestrates dashboard build. Calls `specialist.build()` once per specialist, then `plotter.render()` once per selected format. Returns list of result dicts. |
| `display_label(fmt)` | Returns human-readable format label for GUI. `html_complex` → `"html"`, `html_mobile` → `"mobile"`, others unchanged. |
| `_load_plotters()` | Imports registered plotters lazily from `layouts/`. Returns `{format_key: module}`. |

**Plotter registry** (`_load_plotters()`):

| Format key | Module |
|---|---|
| `html` | `dash_plotter_html` |
| `html_complex` | `dash_plotter_html_complex` |
| `html_mobile` | `dash_plotter_html_mobile` |
| `excel` | `dash_plotter_excel` |
| `json` | `dash_plotter_json` |

**Result dict** (one per format per specialist):
```python
{
    "name":    str,
    "format":  str,
    "file":    Path,      # only if success=True
    "success": bool,
    "error":   str,       # only if success=False
}
```

---

## Specialist interface

Every specialist in `dashboards/` must expose:

### `META` dict

```python
META = {
    "name":        str,   # display name in GUI popup
    "description": str,   # one-line description in GUI popup
    "source":      str,   # data source label (informational)
    "formats": {
        "html":         "filename.html",    # format key → output filename
        "excel":        "filename.xlsx",
        "json":         "filename.json",
        "html_complex": "filename.html",    # uses dash_plotter_html_complex
        "html_mobile":  "filename.html",    # uses dash_plotter_html_mobile
    },
}
```

Only formats with a registered plotter are shown in the GUI.

### `build(date_from, date_to, settings) -> dict`

| Arg | Type | Purpose |
|---|---|---|
| `date_from` | `str` | Start date ISO (`YYYY-MM-DD`), inclusive |
| `date_to` | `str` | End date ISO (`YYYY-MM-DD`), inclusive |
| `settings` | `dict` | GUI settings — reads `age`, `sex`, `base_dir` etc. |

Returns a neutral dict consumed by plotters. Structure varies by specialist — see per-specialist sections below.

**Rules:**
- No direct file access
- No Garmin-internal field names outside the specialist module
- Calls `field_map.get()` and/or `context_map.get()` only
- No rendering logic

---

## Specialist return dicts

### `health_garmin_html-json_dash` — Health Analysis

```python
{
    "title":           str,
    "subtitle":        str,       # includes auto-size note if range was adjusted
    "date_from":       str,       # original requested start date
    "date_to":         str,       # original requested end date
    "prompt_template": str,       # key for dash_prompt_templates
    "profile": {
        "age":     int,
        "sex":     str,
        "vo2max":  float | None,
        "fitness": str,           # "superior"|"excellent"|"good"|"fair"|"poor"|"average"
    },
    "baseline_note": str,
    "fields": [
        {
            "field":         str,
            "label":         str,
            "unit":          str,
            "higher_better": bool | None,
            "period_avg":    float | None,
            "baseline_avg":  float | None,
            "ref_low":       float,
            "ref_high":      float,
            "flagged_days":  int,
            "flagged_dates": [str, ...],    # last 5 flagged dates
            "days": [
                {
                    "date":     str,
                    "value":    float | None,
                    "baseline": float | None,
                    "status":   str | None,   # "low"|"high"|"ok"|None
                },
                ...
            ],
        },
        ...
    ],
}
```

### `timeseries_garmin_html-xls_dash` — Timeseries

```python
{
    "title":    str,
    "subtitle": str,
    "fields": [
        {
            "field":  str,
            "series": [{"ts": str, "value": float}, ...] | None,
        },
        ...
    ],
}
```

### `health_garmin-weather-pollen_html-xls_dash` — Health + Context

```python
{
    "title":    str,
    "subtitle": str,
    "date_from": str,
    "date_to":   str,
    "fields": [
        {
            "field": str,
            "label": str,
            "unit":  str,
            "group": str,    # "garmin" | "weather" | "pollen"
            "days":  [{"date": str, "value": float | None}, ...],
        },
        ...
    ],
}
```

### `overview_garmin_xls_dash` — Daily Overview

```python
{
    "title":    str,
    "subtitle": str,
    "date_from": str,
    "date_to":   str,
    "columns": [{"field": str, "label": str, "group": str}, ...],
    "rows":    [{"date": str, "values": {field: value}}, ...],
}
```

### `sleep_recovery_context_dash` — Sleep & Recovery

```python
{
    "title":    str,
    "subtitle": str,
    "date_from": str,
    "date_to":   str,
    "daily": {
        "dates":               [str, ...],
        "hrv":                 [float | None, ...],
        "body_battery":        [float | None, ...],
        "sleep_h":             [float | None, ...],
        "temperature":         [float | None, ...],
        "pollen":              [float | None, ...],
        "hrv_status":          [str | None, ...],    # "low"|"ok"|None
        "body_battery_status": [str | None, ...],
        "sleep_status":        [str | None, ...],    # "low"|"high"|"ok"|None
        "sleep_phases": [
            {"date": str, "deep": float|None, "light": float|None,
             "rem": float|None, "awake": float|None},
            ...
        ],
    },
    "intraday": {
        "YYYY-MM-DD": {
            "heart_rate":   [{"ts": str, "value": float}, ...] | None,
            "stress":       [{"ts": str, "value": float}, ...] | None,
            "body_battery": [{"ts": str, "value": float}, ...] | None,
            "respiration":  [{"ts": str, "value": float}, ...] | None,
            "temperature":  float | None,
            "pollen":       float | None,
        },
        ...
    },
}
```

### `explorer_garmin-context_html_dash` — Explorer

```python
{
    "layout":   "explorer",          # signals dash_plotter_html_complex to use Explorer layout
    "title":    str,
    "subtitle": str,
    "date_from": str,
    "date_to":   str,
    "daily": {
        "dates":         [str, ...],
        "field_options": [{"field": str, "label": str, "unit": str}, ...],
        "series":        {field: [value | None, ...]},   # all daily fields, aligned to dates
        "sleep_phases":  [
            {"date": str, "deep": float|None, "light": float|None,
             "rem": float|None, "awake": float|None},
            ...
        ],
        "sleep_scores":  [
            {"date": str, "feedback": str|None, "qualifier": str|None},
            ...
        ],
    },
    "intraday":  {},   # reserved, unused
}
```

`field_options` covers all Garmin daily fields (excluding categorical and phase fields) plus all context fields (weather, pollen, air quality). Sleep score labels are rendered as a vertical Plotly text trace inside the sleep phase panel — one label per day at the position of its bar.

---

## Plotter interface

Every plotter in `layouts/` must expose:

### `render(data, output_path, settings) -> None`

| Arg | Type | Purpose |
|---|---|---|
| `data` | `dict` | Neutral dict from `specialist.build()` |
| `output_path` | `Path` | Full output file path |
| `settings` | `dict` | GUI settings (reserved, mostly unused) |

Raises `ValueError` if required data is missing or empty.
Raises `OSError` if output file cannot be written.

`dash_plotter_html_complex` supports two layout types, detected via `data.get("layout")`:
- `"explorer"` → Explorer layout (`_render_explorer`)
- `None` / any other → Recovery Context layout (`_render_recovery_context`)

---

## Layout resources

### `dash_layout.py`

| Function | Returns |
|---|---|
| `get_metric_meta(field)` | `{"label": str, "unit": str, "color": str}` — or `{}` if unknown |
| `get_excel_row_color(field)` | Hex color string for Excel row shading |
| `get_disclaimer()` | Shared disclaimer string (plain text) |
| `get_footer(html)` | Footer string — HTML anchor if `html=True`, plain text otherwise |

### `dash_layout_html.py`

| Function | Returns |
|---|---|
| `get_css()` | Shared CSS string |
| `get_plotly_cdn()` | Plotly CDN URL string |
| `get_plotly_local_filename()` | Local cache filename (`"plotly.min.js"`) |
| `build_header(title, subtitle)` | HTML `<header>` block |
| `build_disclaimer(text)` | HTML disclaimer `<div>` |
| `build_footer(text)` | HTML `<footer>` block |

### `layouts/reference_ranges.py`

Shared age/sex/fitness-adjusted reference range logic. Used by specialists — never by plotters.

| Function | Returns |
|---|---|
| `fitness_level(age, sex, vo2max)` | `str` — `"superior"/"excellent"/"good"/"fair"/"poor"` |
| `reference_ranges(age, sex, fitness)` | `dict` — `{field_key: (low, high), ...}` |

**Fields covered:** `hrv_last_night`, `resting_heart_rate`, `spo2_avg`, `sleep_duration`, `body_battery_max`, `stress_avg`.

---

## Auto-size behaviour

All specialists implement auto-size: if the requested date range exceeds available data, the display range is adjusted to actual data boundaries. The subtitle shows the adjusted range and the original request.

- Garmin-only specialists: boundaries from all loaded fields
- Multi-source specialists (`health-weather-pollen`, `sleep_recovery_context`): boundaries from Garmin fields only — context data is excluded to avoid narrowing the range unnecessarily

`date_from` / `date_to` in the return dict always reflect the **original request** — not the adjusted range.

---

## Flagged day markers

Specialists that compute per-day status (`low`/`high`/`ok`) pass it in the return dict. Plotters render flagged points as red markers (color `#e05c5c`), larger size.

| Specialist | Status fields |
|---|---|
| `health_garmin_html-json_dash` | Per `days` entry: `"status"` key |
| `sleep_recovery_context_dash` | Top-level lists: `hrv_status`, `body_battery_status`, `sleep_status` |
| `explorer_garmin-context_html_dash` | Sleep score vertical text labels in sleep phase panel — colour from `qualifier` field |

Plotters that support flagged markers: `dash_plotter_html`, `dash_plotter_html_complex`, `dash_plotter_html_mobile`.
