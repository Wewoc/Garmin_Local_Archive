#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
layouts/render/explorer.py

Render function for the Explorer layout.
Free metric dropdowns, 4 user-selectable traces, sleep phase panel.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- All design assets from dash_layout and dash_layout_html.
- Receives neutral dict, writes output file.

Public interface:
    render(data: dict, output_path: Path) -> None
"""

import html as html_escape
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import dash_layout      as layout
import dash_layout_html as layout_html

_JS_ESCAPE_HTML_FN = """
function _escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
"""


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
            label_safe = html_escape.escape(label)
            desc_safe  = html_escape.escape(desc)
            desc_rows_html += (
                f'<tr><td style="padding:4px 12px 4px 0;font-weight:500;'
                f'white-space:nowrap;vertical-align:top;">{label_safe}</td>'
                f'<td style="padding:4px 0;color:#555;font-size:12px;">{desc_safe}</td></tr>'
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
            label_safe = html_escape.escape(label)
            desc_safe  = html_escape.escape(desc)
            desc_rows_html += (
                f'<tr><td style="padding:4px 12px 4px 0;font-weight:500;'
                f'white-space:nowrap;vertical-align:top;font-size:12px;">{label_safe}</td>'
                f'<td style="padding:4px 0;color:#555;font-size:12px;">{desc_safe}</td></tr>'
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
            f'<option value="{html_escape.escape(o["field"])}"'
            f'{" selected" if j == sel_idx else ""}>'
            f'{html_escape.escape(o["label"])}'
            f'{"  (" + html_escape.escape(o["unit"]) + ")" if o["unit"] else ""}'
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
      {{x: _dates, y: _deep,  name: {json.dumps(meta_deep.get("label","Deep"))},  type: 'bar',
        marker: {{color: '{meta_deep.get("color","#185FA5")}'}},  yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>Deep: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _light, name: {json.dumps(meta_light.get("label","Light"))}, type: 'bar',
        marker: {{color: '{meta_light.get("color","#7F77DD")}'}}, yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>Light: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _rem,   name: {json.dumps(meta_rem.get("label","REM"))},   type: 'bar',
        marker: {{color: '{meta_rem.get("color","#1D9E75")}'}},   yaxis: 'y5', xaxis: 'x2',
        hovertemplate: '%{{x}}<br>REM: %{{y:.1f}}%<extra></extra>'}},
      {{x: _dates, y: _awake, name: {json.dumps(meta_awake.get("label","Awake"))}, type: 'bar',
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
        + '<td style="padding:4px 12px 4px 0;white-space:nowrap;">' + _escapeHtml(s.date) + '</td>'
        + '<td style="padding:4px 12px 4px 0;">'
        +   '<span style="background:' + s.color + ';color:#fff;border-radius:3px;'
        +   'padding:1px 6px;font-size:11px;">' + _escapeHtml(s.qualifier || '') + '</span>'
        + '</td>'
        + '<td style="padding:4px 0;color:#555;">' + _escapeHtml(s.feedback_short || '') + '</td>'
        + '</tr>';
    }});
    tbody.innerHTML = rows || '<tr><td colspan="3" style="color:#999;padding:8px 0;">No sleep quality data available.</td></tr>';
  }})();
}})();
"""
    return div_html, js


#  Explorer render — full HTML assembly (single page, no Tab 2)
# ══════════════════════════════════════════════════════════════════════════════

def _render_explorer(data: dict, output_path: Path) -> None:
    """Render Explorer dashboard — free metric exploration, single page."""
    _raw_title = data.get("title", "Explorer")
    title      = f"🦄 GARMIN LOCAL ARCHIVE — {_raw_title}"
    subtitle   = data.get("subtitle", "")
    daily    = data.get("daily")

    if daily is None:
        raise ValueError("_render_explorer: data dict must contain 'daily' key")

    tab1_div, tab1_js = _build_explorer_tab1(daily)

    header_html     = layout_html.build_header(title, subtitle)
    disclaimer_html = layout_html.build_disclaimer(layout.get_disclaimer())
    footer_html     = layout_html.build_footer(layout.get_footer(html=True))
    css             = layout_html.get_css()
    plotly_cdn      = layout_html.get_plotly_script(Path(__file__).parent.parent)

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
{_JS_ESCAPE_HTML_FN}
{tab1_js}
</script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")



# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path) -> None:
    """Entry point — delegates to _render_explorer."""
    _render_explorer(data, output_path)
