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
- `layouts/dash_autosize.py` is a passive resource — no file I/O, no imports beyond stdlib
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
    "intraday": {date: {"heart_rate": [...]|None, "stress": [...]|None,
                        "body_battery": [...]|None, "respiration": [...]|None}},   # days with at least one series
    "diary":    {"days": {date: {"note": str, "entries": [{"time", "name", "text"}]}},
                 "damaged": int, "unsupported": int},   # v1.7.8.1; key only present when there is a diary
}
```

The intraday series come from `layouts/dash_intraday.py` (`INTRADAY_FIELDS`, `intraday_by_date`, `build_intraday`),
shared with the Explorer and with the Sleep & Recovery specialist. The `diary` key is built from `maps/diary_map` through `layouts/dash_diary.py`, only when
`settings["base_dir"]` is set and the range holds a diary day (or an unreadable one); the HTML shows the diary of
the selected day below the intraday chart (days with an intraday view only). No opt-in: the HTML files are private
and local. See "Diary in the dashboards" below.

### `explorer_garmin-context_html_dash` — Explorer (day view and diary, v1.7.8.1)

Since v1.7.8.1 the Explorer fills `"intraday"` (same four series and same helper as the Sleep dashboard, no cap on
the range: it comes from the Settings, "Export Dashboard Range", 30 days when empty) and, with a diary, `"diary"`:

```python
{
    ...,                         # layout, title, subtitle, daily as before
    "intraday": {date: {"heart_rate": [...]|None, "stress": ..., "body_battery": ..., "respiration": ...}},
    "diary":    {"days": {date: {"note": str, "entries": [{"time", "name", "text"}]}},
                 "rows": [{"name": "Note" | field name, "dates": [str, ...]}],   # presence strip
                 "damaged": int, "unsupported": int},   # key only present when there is a diary
}
```

The page shows: a **presence strip** above the chart (one row per field with an entry in the range, plus the row
"Note"; follows the zoom and the range slider of the chart through `plotly_relayout`), the main chart (unchanged),
and below it the **day view** (`layouts/render/intraday_block.py`, prefix `explorer`): a dropdown of the days that
have intraday data or a diary entry, the four intraday curves and the diary of the day. A click on a day of the chart
or of the strip selects the day (`plotly_click`). Without intraday and without a diary the page is the one of
before. A day with a diary entry and no intraday data shows a note instead of the chart.

### `heatmap_garmin_html_dash` — Activity & Physiology Heatmaps

Six intraday metrics pivoted to an hour-of-day × date matrix: Heart Rate,
Steps, Stress, Body Battery, SpO2, Respiration. Hour is read directly from
each sample's ISO timestamp (`ts[11:13]`), not recomputed via datetime
parsing — since v1.6.5.6 that timestamp is already shifted to the
recording device's local time (see `REFERENCE_GARMIN.md` → `garmin_map.py`
→ "Timestamp handling"), so the hour shown is local, not GMT. A missing
day still gets a full 24-value row of `None` — same shape as a day with
data, so the renderer never special-cases row length.

**Aggregation per hourly bin:** mean for continuous values (Heart Rate,
Stress, Body Battery, SpO2, Respiration); sum for Steps (a count metric —
summing 15-minute bins per hour is more meaningful than averaging them).

**Auto-size (v1.6.5.11):** `_dates_with_data(metric) -> set` filters a
metric's padded `dates` list down to only the dates whose matrix row has
at least one non-`None` value — the raw `dates` list itself always spans
the full requested range regardless of data presence, so it can't be fed
to `compute_autosize_bounds()` directly. The six metrics' "has data" sets
are pooled (union) into `garmin_dates` before the bounds call — a date
counts if *any* metric has a real sample that hour.

````python
{
    "layout":    "heatmap",
    "title":     str,
    "subtitle":  str,
    "date_from": str,
    "date_to":   str,
    "metrics": {
        "heart_rate":   {"dates": [str, ...], "hours": [0..23], "matrix": [[float | None, ...], ...]},
        "steps":        {...},   # same shape, agg: sum
        "stress":       {...},
        "body_battery": {...},
        "spo2":         {...},
        "respiration":  {...},
    },
}
````

Each metric dict's `matrix` is `dates x hours` — one row per date in
`metrics[key]["dates"]`, 24 columns (`hours: [0..23]`). Source fields via
`field_map.get(..., resolution="intraday")`: `heart_rate_series`,
`steps_series`, `stress_series`, `body_battery_series`, `spo2_series`,
`respiration_series`.

### `live_tracking_html_dash` — Live Tracking (v1.6.5)


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

**Auto-size (v1.6.5.11):** bounds computed from Garmin fields only (daily
fields + sleep phases + sleep score feedback/qualifier) — context fields
excluded, same rationale as the other multi-source specialists
(`health-weather-pollen`, `sleep_recovery_context`): context coverage can
be narrower than Garmin's and would needlessly shrink the display range.
`build()` returns data for all fields regardless of the 4-field dropdown
selection (selection happens client-side), so bounds cannot be scoped to
"selected fields" at build time — this matches the existing precedent for
multi-source specialists, which also don't scope bounds per-selection.

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

Routing, request/response contract, and error behaviour for `health_map.get()`
and `context_map.get()` are documented in `REFERENCE_BROKER.md` — the broker
contract is shared by other consumers as well (MCP Server, and the future
Export Layer), not just the dashboard pipeline.

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
- `"explorer"` → `layouts/render/explorer.py` (`_render_explorer`) — since v1.7.8.1 with the shared day view, the diary presence strip and the click on a day
- `"sleep"`    → `layouts/render/sleep.py` (`_render_sleep`) — HTML/CSS table + inline Plotly intraday explorer (v1.6.2+; the day view is `layouts/render/intraday_block.py` since v1.7.8.1, output unchanged without a diary)
- `"heatmap"`  → `layouts/render/heatmap.py` (`_render_heatmap`) — six Plotly heatmap panels, tab navigation (v1.6.3.1+)
- `"live"`     → `layouts/render/live.py` (`render`) — today's progression + last night, dark theme matching the app's own palette (not the shared light-theme dashboard CSS), inline SVG sparklines instead of Plotly (v1.6.5+)
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
**Dashboard links:** `health_garmin_mobile.html`, `sleep_dashboard.html`

---

## `dash_encryptor.py`

Sole Owner of HTML encryption logic for the Encrypted Dashboard Export.
Leaf-Node — stdlib + cryptography only, no project-module imports.

| Function | Purpose |
|---|---|
| `encrypt_html(html_content, password, *, bg=…, bg2=…, accent=…, accent2=…, text=…, text2=…, red=…)` | Takes a finished HTML string, returns a self-decrypting HTML. AES-256-GCM, PBKDF2-HMAC-SHA256 (100,000 iterations), random salt + IV. Decrypt dialog and Web Crypto API JS are inline — no external assets. Theme colors are plain keyword-only strings (default: the original fixed Violet-Legacy palette) — the caller passes its own `self._app.*` theme colors; no `theme.py` import here, this file stays a Leaf-Node. |

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
| `get_time_basis_note()` | Static intraday time-basis note (v1.6.5.6) — plain text, no markup |

### `dash_layout_html.py`

| Function | Returns |
|---|---|
| `get_css()` | Shared CSS string |
| `get_plotly_cdn()` | Plotly CDN URL string |
| `get_plotly_local_filename()` | Local cache filename (`"plotly.min.js"`) |
| `build_header(title, subtitle, time_basis_note=None)` | HTML `<header>` block — optional third line (`<p class="time-basis">`) when `time_basis_note` is given (v1.6.5.6). `None`/omitted → unchanged from pre-v1.6.5.6 output |
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

### `layouts/dash_autosize.py` (v1.6.5.10)

Sole owner of the auto-size boundary calculation shared by dashboard
specialists. Used by all eight specialists (v1.6.5.11 — `explorer_garmin-context_html_dash.py`
and `heatmap_garmin_html_dash.py` were the last two, rollout complete).
Used by specialists — never by plotters. Function signatures unchanged by
the rollout — both new call sites feed it a pre-filtered `set` of dates,
same contract as the original six.

| Function | Returns |
|---|---|
| `compute_autosize_bounds(dates, date_from, date_to)` | `dict` — `{"actual_first": str\|None, "actual_last": str\|None, "adjusted_from": str\|None, "adjusted_to": str\|None}`. `adjusted_from`/`adjusted_to` set only if the actual data boundary is narrower than the requested range on that end. |
| `autosize_note(bounds, date_from, date_to)` | `str` — the recurring subtitle fragment `" · adjusted to available data (requested: X → Y)"`, or `""` if no adjustment occurred. Takes the return value of `compute_autosize_bounds()`. |

**Called by:** `health_garmin-weather-pollen_html-xls_dash.py`, `health_garmin_html-json_dash.py`,
`overview_garmin_xls_dash.py`, `sleep_garmin_html-xls_dash.py`, `sleep_recovery_context_dash.py`,
`timeseries_garmin_html-xls_dash.py`, `explorer_garmin-context_html_dash.py` (v1.6.5.11),
`heatmap_garmin_html_dash.py` (v1.6.5.11, via `_dates_with_data()` pre-filter — see
"Auto-size" note in that specialist's section above). `health_garmin_html-json_dash.py` uses only
`compute_autosize_bounds()` — its subtitle has its own prefix text and is
assembled independently via `autosize_note()`'s fragment appended at the end.

**Known gap (not fixed, v1.6.5.11):** `overview_garmin_xls_dash.py`'s
`all_dates` set is populated unconditionally from every `field_get()`
entry, without an `is not None` filter (unlike the other seven call
sites). Since `field_get(resolution="daily")` pads every requested day
with an entry regardless of data presence, `all_dates` there always equals
the full requested range — `compute_autosize_bounds()` never returns an
adjusted boundary for this specialist. Latent, harmless (no crash, no
wrong data — just an auto-size that silently never triggers). Flagged
during the v1.6.5.11 DEPS-Scan review, not in scope for that session.

---

### `layouts/dash_intraday.py`, `layouts/dash_diary.py`, `layouts/render/intraday_block.py` (v1.7.8.1)

The day view and the diary of the dashboards. The two helpers are pure shaping (no file I/O, no broker call, no
import); like `dash_autosize.py` they are called by specialists, never by plotters. The block is a renderer module.

| Module | Content |
|---|---|
| `dash_intraday.py` | `INTRADAY_FIELDS` (health_map field → key for the four series), `INTRADAY_KEYS`, `intraday_by_date(result)` → `{date: series}`, `build_intraday(raw_by_key, dates)` → `{date: {key: series}}` for the days with at least one non-empty series |
| `dash_diary.py` *(removable)* | `format_entry`, `format_day` (entries as `{"time", "name", "text"}`, text `label: value unit`, yes/no as `yes`/`no`, time order), `presence_rows` (row "Note" first, then fields by name), `build_payload(broker, base_dir, date_from, date_to)` → `{"days", "rows", "damaged", "unsupported"}`; the broker (`maps/diary_map`) is handed in by the specialist |
| `render/intraday_block.py` | `build_block(intraday, prefix="sleep", diary=None, include_diary_days=False)` → HTML+JS of the day view (dropdown, chart with four traces, optional diary box); ids and function names carry the prefix (`sleep-explorer`, `sleepUpdateIntraday`, `sleepJumpToDay`, ... or `explorer-...`); `json_for_script(obj)` |

### Diary in the dashboards (v1.7.8.1)

- Specialists read the diary through `maps/diary_map` only (read-only, called directly with `settings["base_dir"]`;
  not through `gateway_map`). Without a `base_dir` in the settings, or without a diary day in the range, there is no
  `diary` key and the page is the one of before.
- No opt-in for the dashboards (the HTML files are private and local); the opt-in of the MCP and the data export
  (later layer) does not apply here.
- The HTML carries the note, the entries and the field names of the days in the range, **never** the `history` of a
  day (`diary_map` does not return it). Specialists with the `json` format (prompt templates for a language model)
  never get diary fields.
- The note is shown with `textContent` (never as HTML) and its data is embedded with `json_for_script()` (`<`, `>`,
  `&` as `\uXXXX`), so a note with `</script>` cannot break or inject into the page.
- Days that cannot be read (damaged, newer version) are counted and shown as a line in the diary box, not left out
  silently.
- The encrypted dashboard export (`dash_encryptor`) encrypts the finished HTML as a whole; the diary content is in
  it like the rest.
- The third intraday view (`recovery_context.py` `_build_tab2`, Tab 2 of Sleep & Recovery) is not part of this: it
  keeps its own rendering (two Y axes, temperature and pollen lines, no diary box). Its specialist
  `sleep_recovery_context_dash.py` takes the series list, `intraday_by_date` and the day filter from
  `layouts/dash_intraday.py` like the other two, and adds `temperature` and `pollen` to each day afterwards.

---

### `dash_prompt_templates.py`

Passive resource — Markdown prompt templates for JSON plotter output. No
file I/O, no imports beyond stdlib string formatting. One template function
per specialist type, called exclusively by `dash_plotter_json.py`.

| Function | Purpose |
|---|---|
| `get(template_key)` | Returns the template function for `template_key`. Raises `KeyError` if not registered. |
| `health_analysis(data)` | Template for `health_garmin_*_dash.py` specialists — profile, metric summary table, flagged-days block, assistant instructions. Returns a ready-to-use Markdown string for Open WebUI / Ollama context. |

**Registry:** `TEMPLATES = {"health_analysis": health_analysis, ...}` — extended with one entry per template as new specialist types are added.

---

## Auto-size behaviour

All eight specialists implement auto-size (rollout completed v1.6.5.11): if the requested date range exceeds available data, the display range is adjusted to actual data boundaries. The subtitle shows the adjusted range and the original request. (Exception: `overview_garmin_xls_dash.py` has the call site but a filtering gap makes it a no-op in practice — see "Known gap" under `dash_autosize.py` above.)

- Garmin-only specialists: boundaries from all loaded fields. `heatmap_garmin_html_dash.py` (v1.6.5.11) is a variant of this: "loaded" means a matrix row with at least one non-`None` value, not just an entry in the padded per-day list — see its "Auto-size" note above.
- Multi-source specialists (`health-weather-pollen`, `sleep_recovery_context`, `explorer_garmin-context_html_dash` since v1.6.5.11): boundaries from Garmin fields only — context data is excluded to avoid narrowing the range unnecessarily

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
