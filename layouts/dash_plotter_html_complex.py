#!/usr/bin/env python3
"""
dash_plotter_html_complex.py

Complex HTML plotter — renders specialist data dicts with advanced layouts:
subplots, dual Y-axes, mixed chart types, date dropdowns.

Currently supports the "recovery_context" layout (Sleep & Recovery specialist).
Designed to be extended for future complex dashboards without modifying
dash_plotter_html.py.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Fetches all design assets from dash_layout and dash_layout_html.
- Receives neutral dict from dash_runner, writes output file.
- Layout type detected from data dict structure.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dash_layout      as layout
import dash_layout_html as layout_html


# ══════════════════════════════════════════════════════════════════════════════
#  Plotly — local cache (shared with dash_plotter_html)
# ══════════════════════════════════════════════════════════════════════════════

def _get_plotly_script(layouts_dir: Path) -> str:
    """
    Returns Plotly as an inline <script> tag.
    On first call: downloads from CDN and caches to layouts/plotly.min.js.
    On subsequent calls: reads from local cache — no internet required.
    Falls back to CDN <script src> tag if download fails.
    """
    local = layouts_dir / layout_html.get_plotly_local_filename()

    if not local.exists():
        try:
            url = layout_html.get_plotly_cdn()
            with urllib.request.urlopen(url, timeout=15) as resp:
                local.write_bytes(resp.read())
        except Exception:
            return f'<script src="{layout_html.get_plotly_cdn()}"></script>'

    js = local.read_text(encoding="utf-8")
    return f"<script>{js}</script>"


# ══════════════════════════════════════════════════════════════════════════════
#  Recovery Context layout — Tab 1 (daily overview)
# ══════════════════════════════════════════════════════════════════════════════

def _build_tab1(daily: dict) -> tuple[str, str]:
    """
    Build Tab 1: dual-Y line chart (Panel A) + stacked sleep phase bars (Panel B).
    Returns (div_html, js_code).
    """
    dates        = daily.get("dates", [])
    hrv          = daily.get("hrv", [])
    body_battery = daily.get("body_battery", [])
    sleep_h      = daily.get("sleep_h", [])
    temperature  = daily.get("temperature", [])
    pollen       = daily.get("pollen", [])
    phases       = daily.get("sleep_phases", [])

    # Null-safe JSON serialisation
    def _to_json(lst):
        return json.dumps([v if v is not None else None for v in lst])

    dates_json        = json.dumps(dates)
    hrv_json          = _to_json(hrv)
    bb_json           = _to_json(body_battery)
    sleep_json        = _to_json(sleep_h)
    temp_json         = _to_json(temperature)
    pollen_json       = _to_json(pollen)
    deep_json         = _to_json([p.get("deep")  for p in phases])
    light_json        = _to_json([p.get("light") for p in phases])
    rem_json          = _to_json([p.get("rem")   for p in phases])
    awake_json        = _to_json([p.get("awake") for p in phases])

    meta_hrv   = layout.get_metric_meta("hrv_last_night")
    meta_bb    = layout.get_metric_meta("body_battery_max")
    meta_sleep = layout.get_metric_meta("sleep_duration")
    meta_temp  = layout.get_metric_meta("temperature_max")
    meta_poll  = layout.get_metric_meta("pollen_birch") or {"label": "Pollen", "color": "#A0522D"}
    meta_deep  = layout.get_metric_meta("sleep_deep_pct")
    meta_light = layout.get_metric_meta("sleep_light_pct")
    meta_rem   = layout.get_metric_meta("sleep_rem_pct")
    meta_awake = layout.get_metric_meta("sleep_awake_pct")

    # Flagged day markers — per-point color/size based on status
    _COLOR_FLAG    = "#e05c5c"
    _COLOR_DEFAULT = meta_hrv.get("color", "#5B8DB8")
    _COLOR_BB      = meta_bb.get("color",  "#BA7517")
    _COLOR_SLEEP   = meta_sleep.get("color", "#7F77DD")

    hrv_status  = daily.get("hrv_status",          [None] * len(dates))
    bb_status   = daily.get("body_battery_status", [None] * len(dates))
    slp_status  = daily.get("sleep_status",        [None] * len(dates))

    def _marker_colors(statuses, base_color):
        return [_COLOR_FLAG if s in ("low", "high") else base_color for s in statuses]

    def _marker_sizes(statuses):
        return [8 if s in ("low", "high") else 4 for s in statuses]

    hrv_colors_json   = json.dumps(_marker_colors(hrv_status,  _COLOR_DEFAULT))
    hrv_sizes_json    = json.dumps(_marker_sizes(hrv_status))
    bb_colors_json    = json.dumps(_marker_colors(bb_status,   _COLOR_BB))
    bb_sizes_json     = json.dumps(_marker_sizes(bb_status))
    slp_colors_json   = json.dumps(_marker_colors(slp_status,  _COLOR_SLEEP))
    slp_sizes_json    = json.dumps(_marker_sizes(slp_status))

    div_html = '<div id="chart-tab1" class="chart-container"></div>\n'

    js = f"""
// ── Tab 1: Recovery Context ───────────────────────────────────────────────
(function() {{
  var dates   = {dates_json};
  var hrv     = {hrv_json};
  var bb      = {bb_json};
  var sleep   = {sleep_json};
  var temp    = {temp_json};
  var pollen  = {pollen_json};
  var deep    = {deep_json};
  var light   = {light_json};
  var rem     = {rem_json};
  var awake   = {awake_json};

  var traces = [
    // Panel A — Y1 (0–100)
    {{
      x: dates, y: hrv, name: '{meta_hrv.get("label","HRV")}',
      type: 'scatter', mode: 'lines+markers',
      line: {{color: '{meta_hrv.get("color","#5B8DB8")}', width: 2}},
      marker: {{size: {hrv_sizes_json}, color: {hrv_colors_json}}},
      yaxis: 'y1', xaxis: 'x1',
      hovertemplate: '%{{x}}<br>HRV: %{{y:.0f}} ms<extra></extra>'
    }},
    {{
      x: dates, y: bb, name: '{meta_bb.get("label","Body Battery")}',
      type: 'scatter', mode: 'lines+markers',
      line: {{color: '{meta_bb.get("color","#BA7517")}', width: 2}},
      marker: {{size: {bb_sizes_json}, color: {bb_colors_json}}},
      yaxis: 'y1', xaxis: 'x1',
      hovertemplate: '%{{x}}<br>Body Battery: %{{y:.0f}}<extra></extra>'
    }},
    {{
      x: dates, y: sleep, name: '{meta_sleep.get("label","Sleep")}',
      type: 'scatter', mode: 'lines+markers',
      line: {{color: '{meta_sleep.get("color","#7F77DD")}', width: 2, dash: 'dash'}},
      marker: {{size: {slp_sizes_json}, color: {slp_colors_json}}},
      yaxis: 'y4', xaxis: 'x1',
      hovertemplate: '%{{x}}<br>Sleep: %{{y:.1f}} h<extra></extra>'
    }},
    // Panel A — Y2 right: Temperature
    {{
      x: dates, y: temp, name: '{meta_temp.get("label","Temp Max")}',
      type: 'scatter', mode: 'lines',
      line: {{color: '{meta_temp.get("color","#E85D24")}', width: 1.5}},
      yaxis: 'y2', xaxis: 'x1',
      hovertemplate: '%{{x}}<br>Temp: %{{y:.1f}} °C<extra></extra>'
    }},
    // Panel A — Y3 right: Pollen (own axis, scale 0–500+)
    {{
      x: dates, y: pollen, name: '{meta_poll.get("label","Pollen")}',
      type: 'scatter', mode: 'lines',
      line: {{color: '{meta_poll.get("color","#A0522D")}', width: 1.5, dash: 'dot'}},
      yaxis: 'y3', xaxis: 'x1',
      hovertemplate: '%{{x}}<br>Pollen: %{{y:.1f}}<extra></extra>'
    }},
    // Panel B — stacked sleep phase bars (Y5)
    {{
      x: dates, y: deep, name: '{meta_deep.get("label","Deep Sleep")}',
      type: 'bar',
      marker: {{color: '{meta_deep.get("color","#185FA5")}'}},
      yaxis: 'y5', xaxis: 'x2',
      hovertemplate: '%{{x}}<br>Deep: %{{y:.1f}} %<extra></extra>'
    }},
    {{
      x: dates, y: light, name: '{meta_light.get("label","Light Sleep")}',
      type: 'bar',
      marker: {{color: '{meta_light.get("color","#7F77DD")}'}},
      yaxis: 'y5', xaxis: 'x2',
      hovertemplate: '%{{x}}<br>Light: %{{y:.1f}} %<extra></extra>'
    }},
    {{
      x: dates, y: rem, name: '{meta_rem.get("label","REM")}',
      type: 'bar',
      marker: {{color: '{meta_rem.get("color","#1D9E75")}'}},
      yaxis: 'y5', xaxis: 'x2',
      hovertemplate: '%{{x}}<br>REM: %{{y:.1f}} %<extra></extra>'
    }},
    {{
      x: dates, y: awake, name: '{meta_awake.get("label","Awake")}',
      type: 'bar',
      marker: {{color: '{meta_awake.get("color","#BA7517")}'}},
      yaxis: 'y5', xaxis: 'x2',
      hovertemplate: '%{{x}}<br>Awake: %{{y:.1f}} %<extra></extra>'
    }}
  ];

  var layout = {{
    barmode: 'stack',
    grid: {{rows: 2, columns: 1, subplots: [['xy'], ['x2y5']], roworder: 'top to bottom'}},
    height: 700,
    margin: {{t: 20, r: 120, b: 40, l: 80}},
    legend: {{orientation: 'h', y: -0.08}},
    // Panel A axes
    xaxis: {{
      type: 'date',
      matches: 'x2',
      rangeslider: {{visible: true, thickness: 0.04}},
      rangeselector: {{buttons: [
        {{count: 7,  label: '7d', step: 'day',   stepmode: 'backward'}},
        {{count: 1,  label: '1m', step: 'month', stepmode: 'backward'}},
        {{step: 'all', label: 'All'}}
      ]}}
    }},
    // Y1 left — HRV + Body Battery (0–100)
    yaxis: {{
      title: 'HRV (ms) · Body Battery',
      range: [0, 110],
      side: 'left'
    }},
    // Y2 right — Temperature (°C)
    yaxis2: {{
      title: 'Temp (°C)',
      overlaying: 'y',
      side: 'right',
      showgrid: false
    }},
    // Y3 right — Pollen (0–500+), offset from Y2
    yaxis3: {{
      title: 'Pollen',
      overlaying: 'y',
      side: 'right',
      anchor: 'free',
      position: 0.88,
      showgrid: false
    }},
    // Y4 left — Sleep (h), offset from Y1
    yaxis4: {{
      title: 'Sleep (h)',
      overlaying: 'y',
      side: 'left',
      anchor: 'free',
      position: 0.08,
      showgrid: false,
      range: [0, 12]
    }},
    // Panel B axes
    xaxis2: {{
      type: 'date',
      matches: 'x'
    }},
    // Y5 — Sleep phases (%)
    yaxis5: {{
      title: 'Sleep phases (%)',
      range: [0, 100]
    }},
    paper_bgcolor: '#fff',
    plot_bgcolor:  '#fafafa'
  }};

  Plotly.newPlot('chart-tab1', traces, layout, {{responsive: true}});
}})();
"""
    return div_html, js


# ══════════════════════════════════════════════════════════════════════════════
#  Recovery Context layout — Tab 2 (intraday detail)
# ══════════════════════════════════════════════════════════════════════════════

def _build_tab2(intraday: dict) -> tuple[str, str]:
    """
    Build Tab 2: date dropdown + intraday line chart with dual Y-axes.
    Returns (div_html, js_code).
    """
    dates = sorted(intraday.keys())
    if not dates:
        return '<div id="chart-tab2" class="chart-container"><p style="padding:24px;color:#999;">No intraday data available.</p></div>\n', ""

    meta_hr   = layout.get_metric_meta("heart_rate_series")
    meta_bb   = layout.get_metric_meta("body_battery_series")
    meta_st   = layout.get_metric_meta("stress_series")
    meta_resp = layout.get_metric_meta("respiration_series")
    meta_temp = layout.get_metric_meta("temperature_max")
    meta_poll = layout.get_metric_meta("pollen_birch") or {"label": "Pollen", "color": "#A0522D"}

    # Embed all intraday data as JS object — dropdown swaps without server call
    intraday_js = {}
    for d, day in intraday.items():
        intraday_js[d] = {
            "heart_rate":   day.get("heart_rate")   or [],
            "stress":       day.get("stress")        or [],
            "body_battery": day.get("body_battery")  or [],
            "respiration":  day.get("respiration")   or [],
            "temperature":  day.get("temperature"),
            "pollen":       day.get("pollen"),
        }

    intraday_json = json.dumps(intraday_js)
    dates_json    = json.dumps(dates)
    first_date    = dates[0]

    options_html = "\n".join(
        f'<option value="{d}">{d}</option>' for d in dates
    )

    div_html = f"""
<div id="chart-tab2" class="chart-container" style="display:none;">
  <div style="padding: 8px 0 16px;">
    <label for="intraday-date-select" style="font-size:13px;margin-right:8px;">Date:</label>
    <select id="intraday-date-select" onchange="updateIntradayChart(this.value)"
            style="font-size:13px;padding:4px 8px;border-radius:4px;border:1px solid #ccc;">
      {options_html}
    </select>
  </div>
  <div id="chart-tab2-plot"></div>
</div>
"""

    js = f"""
// ── Tab 2: Intraday Detail ────────────────────────────────────────────────
var _intradayData = {intraday_json};
var _intradayDates = {dates_json};

function _makeIntradaySeries(arr, tsKey, valKey) {{
  if (!arr || arr.length === 0) return {{x: [], y: []}};
  return {{
    x: arr.map(function(p) {{ return p[tsKey !== undefined ? tsKey : 'ts']; }}),
    y: arr.map(function(p) {{ return p[valKey !== undefined ? valKey : 'value']; }})
  }};
}}

function updateIntradayChart(selectedDate) {{
  var day = _intradayData[selectedDate];
  if (!day) return;

  var hr   = _makeIntradaySeries(day.heart_rate);
  var bb   = _makeIntradaySeries(day.body_battery);
  var st   = _makeIntradaySeries(day.stress);
  var resp = _makeIntradaySeries(day.respiration);

  var traces = [];

  if (hr.x.length > 0) traces.push({{
    x: hr.x, y: hr.y, name: '{meta_hr.get("label","Heart Rate")}',
    type: 'scatter', mode: 'lines',
    line: {{color: '{meta_hr.get("color","#E85D24")}', width: 2}},
    yaxis: 'y1',
    hovertemplate: '%{{x}}<br>HR: %{{y:.0f}} bpm<extra></extra>'
  }});

  if (bb.x.length > 0) traces.push({{
    x: bb.x, y: bb.y, name: '{meta_bb.get("label","Body Battery")}',
    type: 'scatter', mode: 'lines',
    line: {{color: '{meta_bb.get("color","#BA7517")}', width: 2}},
    yaxis: 'y1',
    hovertemplate: '%{{x}}<br>Body Battery: %{{y:.0f}}<extra></extra>'
  }});

  if (st.x.length > 0) traces.push({{
    x: st.x, y: st.y, name: '{meta_st.get("label","Stress")}',
    type: 'scatter', mode: 'lines',
    line: {{color: '{meta_st.get("color","#1D9E75")}', width: 2}},
    yaxis: 'y2',
    hovertemplate: '%{{x}}<br>Stress: %{{y:.0f}}<extra></extra>'
  }});

  if (resp.x.length > 0) traces.push({{
    x: resp.x, y: resp.y, name: '{meta_resp.get("label","Respiration")}',
    type: 'scatter', mode: 'lines',
    line: {{color: '{meta_resp.get("color","#7F77DD")}', width: 2}},
    yaxis: 'y2',
    hovertemplate: '%{{x}}<br>Resp: %{{y:.1f}} brpm<extra></extra>'
  }});

  // Context reference lines — horizontal shapes
  var shapes = [];
  var annotations = [];

  if (day.temperature !== null && day.temperature !== undefined) {{
    shapes.push({{
      type: 'line', xref: 'paper', yref: 'y2',
      x0: 0, x1: 1, y0: day.temperature, y1: day.temperature,
      line: {{color: '{meta_temp.get("color","#E85D24")}', width: 1, dash: 'dot'}}
    }});
    annotations.push({{
      xref: 'paper', yref: 'y2', x: 1.01, y: day.temperature,
      text: 'Temp ' + day.temperature.toFixed(1) + ' °C',
      showarrow: false, font: {{size: 10, color: '{meta_temp.get("color","#E85D24")}'}},
      xanchor: 'left'
    }});
  }}

  if (day.pollen !== null && day.pollen !== undefined) {{
    shapes.push({{
      type: 'line', xref: 'paper', yref: 'y2',
      x0: 0, x1: 1, y0: day.pollen, y1: day.pollen,
      line: {{color: '{meta_poll.get("color","#A0522D")}', width: 1, dash: 'dot'}}
    }});
    annotations.push({{
      xref: 'paper', yref: 'y2', x: 1.01, y: day.pollen,
      text: 'Pollen ' + day.pollen.toFixed(1),
      showarrow: false, font: {{size: 10, color: '{meta_poll.get("color","#A0522D")}'}},
      xanchor: 'left'
    }});
  }}

  var layout = {{
    height: 420,
    margin: {{t: 20, r: 120, b: 60, l: 60}},
    legend: {{orientation: 'h', y: -0.2}},
    xaxis: {{type: 'date', title: 'Time'}},
    yaxis:  {{title: 'HR (bpm) · Body Battery (0–100)', range: [0, 110]}},
    yaxis2: {{
      title: 'Stress · Respiration',
      overlaying: 'y', side: 'right',
      showgrid: false, range: [0, 110]
    }},
    shapes:      shapes,
    annotations: annotations,
    paper_bgcolor: '#fff',
    plot_bgcolor:  '#fafafa'
  }};

  if (traces.length === 0) {{
    document.getElementById('chart-tab2-plot').innerHTML =
      '<p style="padding:24px;color:#999;">No data for ' + selectedDate + '.</p>';
    return;
  }}

  Plotly.react('chart-tab2-plot', traces, layout, {{responsive: true}});
}}

// Initial render
updateIntradayChart('{first_date}');
"""
    return div_html, js


# ══════════════════════════════════════════════════════════════════════════════
#  Tab navigation
# ══════════════════════════════════════════════════════════════════════════════

_TAB_DEFINITIONS = [
    ("tab1", "Overview"),
    ("tab2", "Day Detail"),
]

def _build_tab_buttons() -> str:
    buttons = ""
    for i, (tab_id, label) in enumerate(_TAB_DEFINITIONS):
        active = "active" if i == 0 else ""
        buttons += (
            f'<button class="tab-btn {active}" '
            f'onclick="showComplexTab(\'{tab_id}\')" '
            f'id="btn-{tab_id}">{label}</button>\n'
        )
    return buttons


_TAB_SWITCH_JS = """
function showComplexTab(tabId) {
  document.querySelectorAll('.chart-container').forEach(function(d) {
    d.style.display = 'none';
  });
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  document.getElementById('chart-' + tabId).style.display = 'block';
  document.getElementById('btn-'   + tabId).classList.add('active');
}
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to a complex HTML file.

    Expects data dict with keys:
        "title", "subtitle", "daily" (dict), "intraday" (dict)

    Raises:
        ValueError: if required keys are missing.
        OSError:    if output file cannot be written.
    """
    title    = data.get("title", "Dashboard")
    subtitle = data.get("subtitle", "")
    daily    = data.get("daily")
    intraday = data.get("intraday")

    if daily is None or intraday is None:
        raise ValueError("render: data dict must contain 'daily' and 'intraday' keys")

    disclaimer_text = layout.get_disclaimer()
    baseline_note   = data.get("baseline_note")
    if baseline_note:
        disclaimer_text = f"{disclaimer_text} {baseline_note}"

    tab1_div, tab1_js = _build_tab1(daily)
    tab2_div, tab2_js = _build_tab2(intraday)

    tab_buttons  = _build_tab_buttons()
    header_html  = layout_html.build_header(title, subtitle)
    disclaimer_html = layout_html.build_disclaimer(disclaimer_text)
    footer_html  = layout_html.build_footer(layout.get_footer(html=True))
    css          = layout_html.get_css()
    plotly_cdn   = _get_plotly_script(Path(__file__).parent)

    # Tab 1 visible by default, Tab 2 hidden
    tab1_div = tab1_div.replace('class="chart-container"', 'class="chart-container" id="chart-tab1"', 1)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{plotly_cdn}
<style>{css}</style>
</head>
<body>
{header_html}{disclaimer_html}<div class="tabs">
{tab_buttons}</div>
{tab1_div}{tab2_div}{footer_html}<script>
{_TAB_SWITCH_JS}
{tab1_js}
{tab2_js}
</script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
