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
- `layouts/dash_encryptor.py` is the Sole Owner of HTML encryption logic — Leaf-Node, no project-module imports

---

## `dash_runner.py`

| Function | Purpose |
|---|---|
| `scan(log=None)` | Scans `dashboards/` for all `*_dash.py` files. Returns list of specialist descriptors. Specialists that fail to load, have missing/malformed `META`, or have no formats with a registered plotter are skipped — visibly, not silently. Skip reason is passed to the optional `log` callable (same pattern as `build()`) and collected internally. Only formats with a registered plotter are exposed for specialists that load successfully. |
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

### `sleep_garmin_html-xls_dash` — Sleep Dashboard


```python
{
    "layout":    "sleep",
    "title":     str,
    "subtitle":  str,
    "date_from": str,
    "date_to":   str,
    "refs": {
        "hrv_last_night":   (low, high),
        "sleep_duration":   (low, high),
        "body_battery_max": (low, high),
    },
    "rows": [
        {
            "date":         str,
            "deep":         float | None,   # % of total sleep time
            "light":        float | None,
            "rem":          float | None,
            "awake":        float | None,
            "duration_h":   float | None,
            "score":        float | None,   # 0–100
            "qualifier":    str | None,     # "EXCELLENT"|"GOOD"|"FAIR"|"POOR"
            "feedback":     str | None,     # Garmin enum, e.g. "NEGATIVE_LONG_BUT_NOT_ENOUGH_REM"
            "hrv":          float | None,
            "body_battery": float | None,
            "hrv_7d_avg":   float | None,   # 7-day rolling average of nightly HRV (computed in build)
        },
        ...
    ],
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

### `custom_dash_builder` — Custom Dashboard Builder (v1.6.4)

Not a specialist file — `dashboards/custom_dash_builder.py` builds an
in-memory specialist at runtime from a user field selection (Daily Garmin +
Context fields only, no intraday). Deliberately not named `*_dash.py` so
`dash_runner.scan()`'s glob never discovers it; the Custom Dashboard dialog
in `panel_outputs.py` calls `build_ad_hoc_specialist()` directly and passes
the resulting `types.ModuleType` straight into `dash_runner.build()`.

```python
build_ad_hoc_specialist(name, description, garmin_fields, context_fields) -> types.ModuleType
```

Confirmed during v1.6.4 analysis: `dash_runner.build()` needs no changes to
accept this — it only requires `.META`, `.build(date_from, date_to, settings)`,
and `.__name__` on the passed object. The file-based assumptions in
`dash_runner.scan()` / `_load_specialist()` only apply to the auto-discovery
checkbox popup ("Create Reports"), which the ad-hoc module never goes
through.

The returned module's `.META["formats"]` always offers `html_mobile` +
`excel` — no `html_complex`, no new `_REGISTRY` layout key needed. `.build()`
returns:

```python
{
    "title":     str,
    "subtitle":  str,
    "date_from": str,
    "date_to":   str,
    "fields": [
        {
            "field": str,
            "label": str,
            "unit":  str,
            "group": str,    # "garmin" | context source name
            "days":  [{"date": str, "value": float | None}, ...],
        },
        ...
    ],
}
```

Identical shape to `health_garmin-weather-pollen_html-xls_dash` — renders
via the existing `dash_plotter_html_mobile` (one section per field with
`"days"`) and `dash_plotter_excel` (`fields`+`days` → Analysis sheet mode).
No new plotter, no plotter changes.

`list_available_fields()` mirrors Explorer's Daily-field enumeration — a
local copy of its exclusion set (`_EXCLUDE_FROM_DAILY`), since specialists
(and this ad-hoc builder) are standalone by design, no cross-specialist
imports.

**Presets:** `app/garmin_dashboard_presets.py` — `load_presets()` /
`save_preset()` / `delete_preset()`, file at
`~/.garmin_dashboard_presets.json`. Schema includes `"encrypt"` (bool) — the
password itself is never persisted, only the on/off preference.

---

## Broker interface

### `field_map.get()` — Garmin data

```python
from maps.field_map import get as field_get

result = field_get(field, date_from, date_to, resolution="daily")
# result["garmin"] contains the broker return dict
```

`result["garmin"]` contract:

```python
{
    "values":            list,   # [{"date": str, "value": any}, ...]  — daily
                                 # [{"date": str, "series": list|None}, ...]  — intraday
    "fallback":          bool,   # True if requested resolution was unavailable, downgraded
    "source_resolution": str,    # actual resolution used: "daily" or "intraday"
}
```

Raises `KeyError` if field is not registered in `garmin_map._FIELD_MAP`.
Raises `ValueError` if resolution is not `"daily"` or `"intraday"`.

### `context_map.get()` — external context data

```python
from maps.context_map import get as context_get

result = context_get(field, date_from, date_to, resolution="daily")
# result is keyed by source name
```

`result[source_name]` contract — same structure as `field_map` broker return:

```python
{
    "values":            list,
    "fallback":          bool,
    "source_resolution": str,
    "error":             str,    # optional — only present if source failed
}
```

Sources that do not know the requested field are silently skipped (`KeyError` caught internally).
Unknown field with no matching source → empty dict `{}`.

`weather_map.get()` and `pollen_map.get()` follow the same contract as `garmin_map.get()` but raise only `KeyError` (no `ValueError` — resolution is always treated as daily with `fallback=True` for intraday requests). 

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

`dash_plotter_html_complex` is a facade — it routes to `layouts/render/` via `_REGISTRY`:
- `"explorer"` → `layouts/render/explorer.py` (`_render_explorer`)
- `"sleep"`    → `layouts/render/sleep.py` (`_render_sleep`) — HTML/CSS table + inline Plotly intraday explorer (v1.6.2+)
- `"heatmap"`  → `layouts/render/heatmap.py` (`_render_heatmap`) — six Plotly heatmap panels, tab navigation (v1.6.3.1+)
- `None` / any other → `layouts/render/recovery_context.py` (`_render_recovery_context`)

Adding a new layout: create `layouts/render/<name>.py` with `render(data, output_path) -> None`,
add one entry to `_REGISTRY` in `dash_plotter_html_complex.py`, add to `build_manifest.py`.

`dash_plotter_excel` dispatch order: `layout == "sleep"` checked before `"rows" in data` to avoid collision with Overview mode. Sleep phase bar: each of the 20 cells carries a letter label (D=Deep, L=Light, R=REM, A=Awake) in contrast color. Column width 1.0. (v1.5.8+)

---

## `garmin_mobile_landing.py`

Generates `BASE_DIR/dashboards/index.html` with archive status and device
table embedded inline as `window.__GLA_STATUS__` — no `fetch()`, works with
`file://` protocol.

| Function | Purpose |
|---|---|
| `write_index_html(base_dir)` | Reads `quality_log.json` + `device_table.json`, writes `index.html`. Always overwrites. Called after every sync. |
| `ensure_index_html(base_dir)` | Calls `write_index_html()` only if `index.html` is absent. Called at app start. |

**Sole write authority:** `BASE_DIR/dashboards/index.html`
**Read-only access:** `quality_log.json`, `device_table.json` (no QUALITY_LOCK needed)
**Dashboard links:** `health_garmin_mobile.html`, `sleep_garmin_html-xls_dash.html`

---

## `dash_encryptor.py`

Sole Owner of HTML encryption logic for the Encrypted Dashboard Export.
Leaf-Node — stdlib + cryptography only, no project-module imports.

| Function | Purpose |
|---|---|
| `encrypt_html(html_content, password)` | Takes a finished HTML string, returns a self-decrypting HTML. AES-256-GCM, PBKDF2-HMAC-SHA256 (100,000 iterations), random salt + IV. Decrypt dialog and Web Crypto API JS are inline — no external assets. |

**Output:** self-contained HTML with embedded ciphertext + browser-side decryption.
**Raises:** `ValueError` on empty input or password. `RuntimeError` on encryption failure or missing cryptography library.
**Called by:** `panel_outputs._run_encrypted_dashboards()` — never by plotters or specialists.

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
