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

    js_content = local.read_text(encoding="utf-8")
    return f"<script>{js_content}</script>"


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
#  Explorer layout — Tab 1 (daily, 4 free dropdowns + sleep block)
# ══════════════════════════════════════════════════════════════════════════════

def _build_explorer_tab1(daily: dict) -> tuple[str, str]:
    """
    Build Explorer Tab 1:
    - 4 metric dropdowns → line traces on shared X-axis, each with own Y-axis
    - Fixed lower panel: stacked sleep phase bars + sleep score text trace
    Returns (div_html, js_code).
    """
    dates         = daily.get("dates", [])
    field_options = daily.get("field_options", [])
    series_data   = daily.get("series", {})
    phases        = daily.get("sleep_phases", [])
    sleep_scores  = daily.get("sleep_scores", [])

    def _to_json(lst):
        return json.dumps([v if v is not None else None for v in lst])

    dates_json   = json.dumps(dates)
    series_json  = json.dumps({f: [v if v is not None else None for v in vals]
                               for f, vals in series_data.items()})
    options_json = json.dumps(field_options)

    deep_json  = _to_json([p.get("deep")  for p in phases])
    light_json = _to_json([p.get("light") for p in phases])
    rem_json   = _to_json([p.get("rem")   for p in phases])
    awake_json = _to_json([p.get("awake") for p in phases])

    meta_deep  = layout.get_metric_meta("sleep_deep_pct")
    meta_light = layout.get_metric_meta("sleep_light_pct")
    meta_rem   = layout.get_metric_meta("sleep_rem_pct")
    meta_awake = layout.get_metric_meta("sleep_awake_pct")

    _QUALIFIER_COLORS = {
        "EXCELLENT": "#1D9E75",
        "GOOD":      "#5B8DB8",
        "FAIR":      "#BA7517",
        "POOR":      "#e05c5c",
        "no_data":   "#cccccc",
    }
    _FEEDBACK_SHORT = {
        "POSITIVE_DEEP":                    "Deep+",
        "POSITIVE_CONTINUOUS":              "Continuous+",
        "POSITIVE_LONG_AND_DEEP":           "Long+Deep",
        "POSITIVE_LONG_AND_CONTINUOUS":     "Long+Cont.",
        "POSITIVE_LONG_AND_REFRESHING":     "Long+Fresh",
        "POSITIVE_LONG_AND_RECOVERING":     "Long+Rec.",
        "POSITIVE_REFRESHING":              "Refreshing",
        "POSITIVE_RECOVERING":              "Recovering",
        "POSITIVE_HIGHLY_RECOVERING":       "High Rec.",
        "POSITIVE_SHORT_BUT_DEEP":          "Short+Deep",
        "POSITIVE_SHORT_BUT_REFRESHING":    "Short+Fresh",
        "POSITIVE_SHORT_BUT_CONTINUOUS":    "Short+Cont.",
        "POSITIVE_CALM":                    "Calm",
        "POSITIVE_OPTIMAL_STRUCTURE":       "Optimal",
        "NEGATIVE_NOT_RESTORATIVE":         "Not Rest.",
        "NEGATIVE_NOT_ENOUGH_REM":          "Low REM",
        "NEGATIVE_SHORT_AND_NONRECOVERING": "Short-Rec.",
        "NEGATIVE_SHORT_AND_POOR_QUALITY":  "Short-Qual.",
        "NEGATIVE_SHORT_AND_POOR_STRUCTURE":"Short-Struct.",
        "NEGATIVE_LONG_BUT_NOT_RESTORATIVE":"Long-Rest.",
        "NEGATIVE_LONG_BUT_NOT_ENOUGH_REM": "Long-REM",
        "NEGATIVE_LONG_BUT_POOR_QUALITY":   "Long-Qual.",
        "NEGATIVE_LONG_BUT_DISCONTINUOUS":  "Long-Cont.",
        "NEGATIVE_DISCONTINUOUS":           "Discontin.",
        "NEGATIVE_POOR_STRUCTURE":          "Poor Struct.",
        "NEGATIVE_LIGHT":                   "Light-",
    }
    _FIELD_DESCRIPTIONS = {
        # Air quality
        "airquality_pm2_5":            "PM2.5 — Fine particulate matter ≤2.5 µm. Main source: combustion, traffic. WHO guideline: 15 µg/m³ daily mean.",
        "airquality_pm10":             "PM10 — Coarse particulate matter ≤10 µm. Sources: dust, pollen, construction. WHO guideline: 45 µg/m³ daily mean.",
        "airquality_european_aqi":     "European Air Quality Index (0–500). 0–20 = Good, 20–40 = Fair, 40–60 = Moderate, 60–80 = Poor, 80–100 = Very Poor, >100 = Extremely Poor.",
        "airquality_nitrogen_dioxide": "NO₂ — Nitrogen dioxide. Indicator for traffic pollution. Elevated levels can affect respiratory health.",
        "airquality_ozone":            "O₃ — Ground-level ozone. Formed by sunlight reacting with pollutants. Higher in summer. Can irritate airways.",
        # Pollen
        "pollen_birch":   "Birch pollen — peak season: March–May. Strong allergen.",
        "pollen_grass":   "Grass pollen — peak season: May–July. Most common allergen.",
        "pollen_alder":   "Alder pollen — early season: January–March.",
        "pollen_mugwort": "Mugwort pollen — late season: July–September.",
        "pollen_olive":   "Olive pollen — Mediterranean regions, April–June.",
        "pollen_ragweed": "Ragweed pollen — late summer: August–October. Strong allergen.",
        # Brightsky weather
        "temperature_avg":      "Average temperature across the day (°C).",
        "precipitation_sum":    "Total precipitation for the day (mm). Rain + snow combined.",
        "sunshine_sum":         "Total sunshine duration (minutes).",
        "wind_speed_max":       "Maximum wind speed recorded during the day (km/h).",
        "wind_gust_max":        "Maximum wind gust recorded during the day (km/h).",
        "cloud_cover_avg":      "Average cloud cover (%). 0 = clear sky, 100 = fully overcast.",
        "pressure_avg":         "Average atmospheric pressure (hPa). Low pressure often indicates unsettled weather.",
        "condition":            "Predominant weather condition for the day (e.g. sunny, rain, snow).",
        # HRV
        "hrv_last_night":       "HRV — Heart Rate Variability measured during sleep. Higher = better recovery. Varies significantly between individuals.",
        "hrv_weekly_avg":       "7-day rolling average HRV. Smooths out single-night variation.",
        # Sleep
        "sleep_duration":       "Total sleep duration (hours). Recommended: 7–9h for adults.",
        "sleep_score":          "Garmin sleep score (0–100). Combines duration, phases, and HRV.",
        "sleep_deep_pct":       "Percentage of sleep spent in deep (slow-wave) sleep. Typically 15–25%.",
        "sleep_rem_pct":        "Percentage of sleep in REM phase. Important for memory and mood. Typically 20–25%.",
        "sleep_light_pct":      "Percentage of sleep in light sleep.",
        "sleep_awake_pct":      "Percentage of time awake during the sleep window.",
        # Body
        "body_battery_max":     "Peak Body Battery level of the day (0–100). Reflects recovery state.",
        "body_battery_min":     "Lowest Body Battery level of the day. High drain may indicate stress or activity.",
        "stress_avg":           "Average stress level (0–100). Derived from HRV variability throughout the day.",
        "resting_heart_rate":   "Resting heart rate (bpm). Lower generally indicates better cardiovascular fitness.",
        "spo2_avg":             "Average blood oxygen saturation (%). Normal: 95–100%. Values below 90% are concerning.",
    }

    # Build descriptions HTML for the collapsible block
    desc_rows_html = ""
    for opt in field_options:
        desc = _FIELD_DESCRIPTIONS.get(opt["field"], "")
        if desc:
            label = opt["label"] + (f" ({opt['unit']})" if opt["unit"] else "")
            desc_rows_html += (
                f'<tr><td style="padding:4px 12px 4px 0;font-weight:500;'
                f'white-space:nowrap;vertical-align:top;">{label}</td>'
                f'<td style="padding:4px 0;color:#555;font-size:12px;">{desc}</td></tr>'
            )

    _FIELD_DESCRIPTIONS = {
        # Air quality
        "airquality_pm2_5":            "PM2.5 — Fine particulate matter ≤2.5 µm. Sources: traffic, combustion, industry. WHO guideline: 15 µg/m³ daily mean. Penetrates deep into lungs — relevant for respiratory and cardiovascular health.",
        "airquality_pm10":             "PM10 — Coarse particulate matter ≤10 µm. Sources: dust, pollen, construction. WHO guideline: 45 µg/m³ daily mean. Less deep penetration than PM2.5 but still affects airways.",
        "airquality_european_aqi":     "European Air Quality Index (0–100+). Combines multiple pollutants into one score. 0–20 Good · 20–40 Fair · 40–60 Moderate · 60–80 Poor · 80–100 Very Poor · >100 Extremely Poor.",
        "airquality_nitrogen_dioxide": "NO₂ — Nitrogen dioxide. Mainly from traffic and heating. Irritates airways, worsens asthma. Elevated on busy roads, in cold weather, and during temperature inversions.",
        "airquality_ozone":            "O₃ — Ground-level ozone. Formed by sunlight reacting with traffic pollutants. Peaks on hot sunny days. Can cause chest tightness and reduced lung function during exercise.",
        # Pollen
        "pollen_birch":   "Birch pollen — peak season: March–May. Strong allergen, cross-reactive with many foods.",
        "pollen_grass":   "Grass pollen — peak season: May–July. Most common allergen in Central Europe.",
        "pollen_alder":   "Alder pollen — early season: January–March. Often the first significant pollen of the year.",
        "pollen_mugwort": "Mugwort pollen — late season: July–September. Cross-reactive with celery, carrots, spices.",
        "pollen_olive":   "Olive pollen — Mediterranean regions, April–June.",
        "pollen_ragweed": "Ragweed pollen — late summer: August–October. Strong allergen, spreading northward in Europe.",
        # Weather
        "temperature_avg":      "Average temperature across the day (°C).",
        "precipitation_sum":    "Total precipitation for the day (mm). Rain + snow combined.",
        "sunshine_sum":         "Total sunshine duration (minutes).",
        "wind_speed_max":       "Maximum wind speed recorded during the day (km/h).",
        "wind_gust_max":        "Maximum wind gust recorded during the day (km/h).",
        "cloud_cover_avg":      "Average cloud cover (%). 0 = clear sky, 100 = fully overcast.",
        "pressure_avg":         "Average atmospheric pressure (hPa). Low pressure often indicates unsettled weather.",
        "condition":            "Predominant weather condition for the day (e.g. sunny, rain, snow).",
        # Garmin health
        "hrv_last_night":       "HRV — Heart Rate Variability measured during sleep. Higher = better recovery. Highly individual — trends matter more than absolute values.",
        "hrv_weekly_avg":       "7-day rolling average HRV. Smooths out single-night variation.",
        "sleep_duration":       "Total sleep duration (hours). Recommended: 7–9h for adults.",
        "sleep_score":          "Garmin sleep score (0–100). Combines duration, phases, and HRV.",
        "body_battery_max":     "Peak Body Battery level of the day (0–100). Reflects recovery state at best point of day.",
        "body_battery_min":     "Lowest Body Battery level of the day. High drain may indicate stress or intense activity.",
        "stress_avg":           "Average stress level (0–100). Derived from HRV variability throughout the day.",
        "resting_heart_rate":   "Resting heart rate (bpm). Lower generally indicates better cardiovascular fitness.",
        "spo2_avg":             "Average blood oxygen saturation (%). Normal: 95–100%.",
    }

    # Field descriptions table — only fields with a description entry
    desc_rows_html = ""
    for opt in field_options:
        desc = _FIELD_DESCRIPTIONS.get(opt["field"], "")
        if desc:
            label = opt["label"] + (f" ({opt['unit']})" if opt["unit"] else "")
            desc_rows_html += (
                f'<tr><td style="padding:4px 12px 4px 0;font-weight:500;'
                f'white-space:nowrap;vertical-align:top;font-size:12px;">{label}</td>'
                f'<td style="padding:4px 0;color:#555;font-size:12px;">{desc}</td></tr>'
            )

    # Air Quality Guide — only shown when airquality fields are in the dataset
    has_airquality = any(o["field"].startswith("airquality_") for o in field_options)

    scores_json = json.dumps([
        {
            "date":           s.get("date"),
            "feedback_short": _FEEDBACK_SHORT.get(s.get("feedback") or "", s.get("feedback") or ""),
            "feedback_full":  s.get("feedback") or "",
            "qualifier":      s.get("qualifier") or "no_data",
            "color":          _QUALIFIER_COLORS.get(s.get("qualifier") or "no_data", "#cccccc"),
        }
        for s in sleep_scores
    ])

    n = len(field_options)
    defaults = [0, min(1, n-1), min(2, n-1), min(3, n-1)] if n > 0 else [0, 0, 0, 0]

    dropdowns_html = ""
    for i in range(4):
        sel_idx = defaults[i] if field_options else 0
        options_html = "\n".join(
            f'<option value="{o["field"]}"'
            f'{" selected" if j == sel_idx else ""}>'
            f'{o["label"]}'
            f'{"  (" + o["unit"] + ")" if o["unit"] else ""}'
            f'</option>'
            for j, o in enumerate(field_options)
        )
        empty = '<option value="">— none —</option>\n' if i > 0 else ""
        dropdowns_html += f"""
  <div style="display:inline-block;margin-right:16px;margin-bottom:8px;">
    <label style="font-size:12px;color:#666;display:block;margin-bottom:2px;">Metric {i+1}</label>
    <select id="explorer-dd-{i}" onchange="explorerUpdatePage1()"
            style="font-size:12px;padding:3px 6px;border-radius:4px;border:1px solid #ccc;min-width:160px;">
      {empty}{options_html}
    </select>
  </div>"""

    _aq_guide = ""
    if has_airquality:
        _aq_guide = """
  <details style="margin-top:8px;border:1px solid #e0e0e0;border-radius:4px;padding:8px 12px;">
    <summary style="cursor:pointer;font-size:13px;font-weight:500;color:#444;user-select:none;">
      Air Quality — How to read the values
    </summary>
    <div style="margin-top:10px;font-size:12px;color:#444;line-height:1.6;">
      <p style="margin:0 0 10px;"><strong>European AQI</strong> — single index combining all pollutants:</p>
      <table style="border-collapse:collapse;margin-bottom:14px;">
        <tr><td style="padding:2px 10px 2px 0;"><span style="background:#1D9E75;color:#fff;padding:1px 8px;border-radius:3px;">0–20</span></td><td>Good — no restrictions</td></tr>
        <tr><td style="padding:2px 10px 2px 0;"><span style="background:#5B8DB8;color:#fff;padding:1px 8px;border-radius:3px;">20–40</span></td><td>Fair — sensitive individuals may notice effects</td></tr>
        <tr><td style="padding:2px 10px 2px 0;"><span style="background:#BA7517;color:#fff;padding:1px 8px;border-radius:3px;">40–60</span></td><td>Moderate — reduce prolonged outdoor exertion</td></tr>
        <tr><td style="padding:2px 10px 2px 0;"><span style="background:#e05c5c;color:#fff;padding:1px 8px;border-radius:3px;">60–80</span></td><td>Poor — avoid outdoor exercise, especially near traffic</td></tr>
        <tr><td style="padding:2px 10px 2px 0;"><span style="background:#7B2D2D;color:#fff;padding:1px 8px;border-radius:3px;">&gt;80</span></td><td>Very Poor / Extremely Poor — stay indoors if possible</td></tr>
      </table>
      <p style="margin:0 0 6px;"><strong>PM2.5</strong> — Fine particles (µg/m³):</p>
      <ul style="margin:0 0 12px;padding-left:18px;">
        <li>WHO guideline: ≤15 µg/m³ daily mean</li>
        <li>Typical urban background: 5–20 µg/m³</li>
        <li>High traffic or heating season: 30–60 µg/m³</li>
        <li>Correlation tip: compare with HRV and resting HR on high-PM days</li>
      </ul>
      <p style="margin:0 0 6px;"><strong>PM10</strong> — Coarse particles (µg/m³):</p>
      <ul style="margin:0 0 12px;padding-left:18px;">
        <li>WHO guideline: ≤45 µg/m³ daily mean</li>
        <li>Elevated after dry windy days, construction, saharan dust</li>
      </ul>
      <p style="margin:0 0 6px;"><strong>NO₂</strong> — Nitrogen dioxide (µg/m³):</p>
      <ul style="margin:0 0 12px;padding-left:18px;">
        <li>EU annual limit: 40 µg/m³ — daily peaks much higher near roads</li>
        <li>Highest in cold, calm weather and rush hours</li>
        <li>Relevant for: asthma, recovery after intense training</li>
      </ul>
      <p style="margin:0 0 6px;"><strong>Ozone</strong> (µg/m³):</p>
      <ul style="margin:0 0 12px;padding-left:18px;">
        <li>EU target: 120 µg/m³ max 8h average</li>
        <li>Peaks on hot sunny afternoons — lowest at night</li>
        <li>Reduces lung capacity during exercise — relevant if you train outdoors</li>
      </ul>
      <p style="margin:0;color:#888;font-size:11px;">
        Sources: WHO Air Quality Guidelines 2021, European Environment Agency.
        Values are daily means from Open-Meteo Air Quality API (CAMS dataset).
      </p>
    </div>
  </details>"""

    div_html = f"""
<div id="chart-explorer-tab1" class="chart-container">
  <div style="padding:8px 0 4px;">{dropdowns_html}
  </div>
  <div id="explorer-page1-chart"></div>

  <details style="margin-top:12px;border:1px solid #e0e0e0;border-radius:4px;padding:8px 12px;">
    <summary style="cursor:pointer;font-size:13px;font-weight:500;color:#444;user-select:none;">
      Sleep Quality Log
    </summary>
    <div id="explorer-sleep-log" style="margin-top:8px;max-height:300px;overflow-y:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="border-bottom:1px solid #e0e0e0;">
            <th style="text-align:left;padding:4px 12px 4px 0;color:#888;font-weight:500;">Date</th>
            <th style="text-align:left;padding:4px 12px 4px 0;color:#888;font-weight:500;">Quality</th>
            <th style="text-align:left;padding:4px 0;color:#888;font-weight:500;">Feedback</th>
          </tr>
        </thead>
        <tbody id="explorer-sleep-log-body"></tbody>
      </table>
    </div>
  </details>

  <details style="margin-top:8px;border:1px solid #e0e0e0;border-radius:4px;padding:8px 12px;">
    <summary style="cursor:pointer;font-size:13px;font-weight:500;color:#444;user-select:none;">
      Field Descriptions
    </summary>
    <div style="margin-top:8px;max-height:300px;overflow-y:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        {desc_rows_html if desc_rows_html else '<tr><td style="color:#999;">No descriptions available for the selected fields.</td></tr>'}
      </table>
    </div>
  </details>
{_aq_guide}
</div>
"""

    js = f"""
// ── Explorer Tab 1 ────────────────────────────────────────────────────────────
(function() {{
  var _dates   = {dates_json};
  var _series  = {series_json};
  var _options = {options_json};
  var _deep    = {deep_json};
  var _light   = {light_json};
  var _rem     = {rem_json};
  var _awake   = {awake_json};
  var _scores  = {scores_json};

  var _YAXIS_SIDES = ['left', 'right', 'left', 'right'];
  var _YAXIS_POS   = [null, null, 0.06, 0.94];
  var _LINE_COLORS = ['#5B8DB8', '#E85D24', '#1D9E75', '#BA7517'];

  function _getOptionMeta(fieldName) {{
    for (var i = 0; i < _options.length; i++) {{
      if (_options[i].field === fieldName) return _options[i];
    }}
    return null;
  }}

  window.explorerUpdatePage1 = function() {{
    var traces  = [];
    var layouts = {{
      barmode: 'stack',
      grid:    {{rows: 2, columns: 1, subplots: [['xy'], ['x2y5']], roworder: 'top to bottom'}},
      height:  700,
      margin:  {{t: 20, r: 100, b: 40, l: 80}},
      legend:  {{orientation: 'h', y: -0.08}},
      xaxis: {{
        type: 'date', matches: 'x2',
        rangeslider: {{visible: true, thickness: 0.04}},
        rangeselector: {{buttons: [
          {{count: 7,  label: '7d', step: 'day',   stepmode: 'backward'}},
          {{count: 1,  label: '1m', step: 'month', stepmode: 'backward'}},
          {{step: 'all', label: 'All'}}
        ]}}
      }},
      xaxis2:       {{type: 'date', matches: 'x'}},
      yaxis5:       {{title: 'Sleep phases (%)', range: [0, 100]}},
      paper_bgcolor: '#fff',
      plot_bgcolor:  '#fafafa'
    }};

    var activeAxes = 0;
    for (var i = 0; i < 4; i++) {{
      var sel = document.getElementById('explorer-dd-' + i);
      if (!sel) continue;
      var fieldName = sel.value;
      if (!fieldName) continue;
      var meta = _getOptionMeta(fieldName);
      if (!meta) continue;
      var vals = _series[fieldName];
      if (!vals) continue;

      var axisKey  = activeAxes === 0 ? 'y' : ('y' + (activeAxes + 1));
      var color    = _LINE_COLORS[activeAxes % _LINE_COLORS.length];
      var side     = _YAXIS_SIDES[activeAxes % _YAXIS_SIDES.length];
      var axDef    = {{
        title:    meta.label + (meta.unit ? ' (' + meta.unit + ')' : ''),
        side:     side,
        showgrid: activeAxes === 0
      }};
      if (_YAXIS_POS[activeAxes] !== null) {{
        axDef.overlaying = 'y';
        axDef.anchor     = 'free';
        axDef.position   = _YAXIS_POS[activeAxes];
      }} else if (activeAxes > 0) {{
        axDef.overlaying = 'y';
      }}
      var layoutKey = activeAxes === 0 ? 'yaxis' : ('yaxis' + (activeAxes + 1));
      layouts[layoutKey] = axDef;

      traces.push({{
        x:    _dates,
        y:    vals,
        name: meta.label,
        type: 'scatter', mode: 'lines+markers',
        line:   {{color: color, width: 2}},
        marker: {{size: 3, color: color}},
        yaxis:  axisKey, xaxis: 'x',
        hovertemplate: '%{{x}}<br>' + meta.label + ': %{{y:.2f}}' +
                       (meta.unit ? ' ' + meta.unit : '') + '<extra></extra>'
      }});
      activeAxes++;
    }}

    // Sleep phase stacked bars
    traces.push(
      {{x: _dates, y: _deep,  name: '{meta_deep.get("label","Deep")}',  type: 'bar',
        marker: {{color: '{meta_deep.get("color","#185FA5")}'}},  yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>Deep: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _light, name: '{meta_light.get("label","Light")}', type: 'bar',
        marker: {{color: '{meta_light.get("color","#7F77DD")}'}}, yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>Light: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _rem,   name: '{meta_rem.get("label","REM")}',   type: 'bar',
        marker: {{color: '{meta_rem.get("color","#1D9E75")}'}},   yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>REM: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _awake, name: '{meta_awake.get("label","Awake")}', type: 'bar',
        marker: {{color: '{meta_awake.get("color","#BA7517")}'}}, yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>Awake: %{{y:.1f}}%<extra></extra>'}}
    );

    Plotly.react('explorer-page1-chart', traces, layouts, {{responsive: true}});
  }};

  explorerUpdatePage1();

  // ── Sleep Quality Log ─────────────────────────────────────────────────────
  (function() {{
    var tbody = document.getElementById('explorer-sleep-log-body');
    if (!tbody) return;
    var rows = '';
    var sorted = _scores.slice().reverse();  // newest first
    sorted.forEach(function(s) {{
      if (s.qualifier === 'no_data' && !s.feedback_full) return;
      var bg = s.color + '22';  // 13% opacity background
      rows += '<tr style="border-bottom:1px solid #f0f0f0;">'
        + '<td style="padding:4px 12px 4px 0;white-space:nowrap;">' + s.date + '</td>'
        + '<td style="padding:4px 12px 4px 0;">'
        +   '<span style="background:' + s.color + ';color:#fff;border-radius:3px;'
        +   'padding:1px 6px;font-size:11px;">' + (s.qualifier || '') + '</span>'
        + '</td>'
        + '<td style="padding:4px 0;color:#555;">' + (s.feedback_short || '') + '</td>'
        + '</tr>';
    }});
    tbody.innerHTML = rows || '<tr><td colspan="3" style="color:#999;padding:8px 0;">No sleep quality data available.</td></tr>';
  }})();
}})();
"""
    return div_html, js


# ══════════════════════════════════════════════════════════════════════════════
#  Explorer render — full HTML assembly (single page, no Tab 2)
# ══════════════════════════════════════════════════════════════════════════════

def _render_explorer(data: dict, output_path: Path) -> None:
    """Render Explorer dashboard — free metric exploration, single page."""
    title    = data.get("title", "Explorer")
    subtitle = data.get("subtitle", "")
    daily    = data.get("daily")

    if daily is None:
        raise ValueError("_render_explorer: data dict must contain 'daily' key")

    tab1_div, tab1_js = _build_explorer_tab1(daily)

    header_html     = layout_html.build_header(title, subtitle)
    disclaimer_html = layout_html.build_disclaimer(layout.get_disclaimer())
    footer_html     = layout_html.build_footer(layout.get_footer(html=True))
    css             = layout_html.get_css()
    plotly_cdn      = _get_plotly_script(Path(__file__).parent)

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
{header_html}{disclaimer_html}{tab1_div}{footer_html}<script>
{tab1_js}
</script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Tab navigation (Recovery Context only)
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
            f'onclick="showComplexTab(\'chart-{tab_id}\')" '
            f'id="btn-chart-{tab_id}">{label}</button>\n'
        )
    return buttons


_TAB_SWITCH_JS = """
function showComplexTab(elementId) {
  document.querySelectorAll('.chart-container').forEach(function(d) {
    d.style.display = 'none';
  });
  document.querySelectorAll('.tab-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  document.getElementById(elementId).style.display = 'block';
  document.getElementById('btn-' + elementId).classList.add('active');
}
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to a complex HTML file.

    Layout type is determined by data.get("layout"):
        "explorer"       → Explorer dashboard (free metric dropdowns)
        None / any other → Recovery Context dashboard (fixed metrics)

    Raises:
        ValueError: if required keys are missing.
        OSError:    if output file cannot be written.
    """
    if data.get("layout") == "explorer":
        _render_explorer(data, output_path)
    elif data.get("layout") == "sleep":
        _render_sleep(data, output_path)
    else:
        _render_recovery_context(data, output_path)


def _render_sleep(data: dict, output_path: Path) -> None:
    """Sleep Dashboard render — one row per night, HTML/CSS table, no Plotly."""
    title    = data.get("title", "Sleep Dashboard")
    subtitle = data.get("subtitle", "")
    rows     = data.get("rows")
    refs     = data.get("refs", {})

    if not rows:
        raise ValueError("_render_sleep: data dict must contain non-empty 'rows'")

    ref_hrv_low,  ref_hrv_high  = refs.get("hrv_last_night",   (30, 80))
    ref_slp_low,  ref_slp_high  = refs.get("sleep_duration",   (7.0, 9.0))
    ref_bb_low,   ref_bb_high   = refs.get("body_battery_max", (50, 100))

    # ── Color helpers ─────────────────────────────────────────────────────────

    def _hsl_color(value, low, high, higher_better=True):
        """Map value to HSL color string. 0°=red, 120°=green."""
        if value is None or high <= low:
            return "#888888"
        norm = max(0.0, min(1.0, (value - low) / (high - low)))
        if not higher_better:
            norm = 1.0 - norm
        hue = int(norm * 120)
        return f"hsl({hue}, 65%, 45%)"

    _QUALIFIER_COLORS = {
        "EXCELLENT": ("#1a7a4a", "#d4f5e5"),
        "GOOD":      ("#1a6a6a", "#d4f0f0"),
        "FAIR":      ("#8a6a00", "#fff3cc"),
        "POOR":      ("#8a2000", "#ffe0d0"),
    }

    _PHASE_COLORS = {
        "deep":  "#2d6a9f",
        "light": "#7eb8d4",
        "rem":   "#9b7fc7",
        "awake": "#d4c5a9",
    }

    def _phase_bar(row):
        """Build segmented CSS flex bar from phase percentages."""
        phases = [
            ("deep",  row.get("deep")),
            ("light", row.get("light")),
            ("rem",   row.get("rem")),
            ("awake", row.get("awake")),
        ]
        total = sum(v for _, v in phases if v is not None)
        if total <= 0:
            return '<div style="width:100%;height:18px;background:#333;border-radius:3px;"></div>'
        segments = ""
        for key, val in phases:
            if val is None or val <= 0:
                continue
            pct   = val / total * 100
            color = _PHASE_COLORS[key]
            label = key.upper()[0]
            segments += (
                f'<div style="flex:{pct:.1f};background:{color};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:9px;color:#fff;overflow:hidden;" '
                f'title="{key.capitalize()}: {val:.1f}%">{label}</div>'
            )
        return f'<div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">{segments}</div>'

    def _qualifier_badge(qualifier):
        if not qualifier:
            return '<span style="color:#888;">—</span>'
        fg, bg = _QUALIFIER_COLORS.get(qualifier, ("#555", "#eee"))
        return (
            f'<span style="background:{bg};color:{fg};padding:2px 7px;'
            f'border-radius:10px;font-size:11px;font-weight:600;">'
            f'{qualifier}</span>'
        )

    def _feedback_text(feedback):
        if not feedback:
            return '<span style="color:#888;">—</span>'
        # Convert NEGATIVE_LONG_BUT_NOT_ENOUGH_REM → Long / Not Enough REM
        cleaned = feedback.replace("NEGATIVE_", "").replace("POSITIVE_", "")
        parts   = [p.capitalize().replace("_", " ") for p in cleaned.split("_AND_")]
        return f'<span style="color:#aaa;font-size:12px;">{" · ".join(parts)}</span>'

    # ── Build table rows ──────────────────────────────────────────────────────

    row_html = ""
    for row in rows:
        date        = row.get("date", "")
        duration    = row.get("duration_h")
        score       = row.get("score")
        hrv         = row.get("hrv")
        bb          = row.get("body_battery")

        dur_color  = _hsl_color(duration, ref_slp_low,  ref_slp_high,  higher_better=True)
        score_color= _hsl_color(score,    30,            100,            higher_better=True)
        hrv_color  = _hsl_color(hrv,      ref_hrv_low,   ref_hrv_high,  higher_better=True)
        bb_color   = _hsl_color(bb,       ref_bb_low,    ref_bb_high,   higher_better=True)

        dur_str   = f"{duration:.1f}h"   if duration   is not None else "—"
        score_str = f"{score:.0f}"        if score      is not None else "—"
        hrv_str   = f"{hrv:.0f}"          if hrv        is not None else "—"
        bb_str    = f"{bb:.0f}"           if bb         is not None else "—"

        row_html += f"""
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">{date}</td>
  <td style="padding:6px 10px;min-width:140px;">{_phase_bar(row)}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{dur_color};">{dur_str}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{score_color};">{score_str}</td>
  <td style="padding:6px 10px;text-align:center;">{_qualifier_badge(row.get("qualifier"))}</td>
  <td style="padding:6px 10px;">{_feedback_text(row.get("feedback"))}</td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid #333;font-weight:700;color:{hrv_color};">{hrv_str}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{bb_color};">{bb_str}</td>
</tr>"""

    # ── Assemble page ─────────────────────────────────────────────────────────

    header_html     = layout_html.build_header(title, subtitle)
    disclaimer_html = layout_html.build_disclaimer(layout.get_disclaimer())
    footer_html     = layout_html.build_footer(layout.get_footer(html=True))
    css             = layout_html.get_css()

    table_css = """
<style>
.sleep-table { width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:13px; }
.sleep-table th { background:#1a2a3a; color:#aac; padding:8px 10px; text-align:left; font-size:12px; font-weight:600; border-bottom:2px solid #2d6a9f; }
.sleep-table tr:nth-child(even) { background:#111c26; }
.sleep-table tr:nth-child(odd)  { background:#0d1720; }
.sleep-table tr:hover           { background:#1a2d40; }
</style>"""

    html_body = f"""
<table class="sleep-table">
<thead>
<tr>
  <th>Date</th>
  <th>Sleep Phases</th>
  <th>Duration</th>
  <th>Score</th>
  <th>Quality</th>
  <th>Feedback</th>
  <th style="border-left:2px solid #2d6a9f;">HRV</th>
  <th>Body Battery</th>
</tr>
</thead>
<tbody>
{row_html}
</tbody>
</table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{css}</style>
{table_css}
</head>
<body>
{header_html}{disclaimer_html}
<div style="padding:16px 24px;">
{html_body}
</div>
{footer_html}
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _render_recovery_context(data: dict, output_path: Path) -> None:
    """Original recovery context render — unchanged."""
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
