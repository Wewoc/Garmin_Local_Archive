#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
layouts/render/heatmap.py

Render function for the Heatmap layout.
Six Plotly Heatmap panels (Heart Rate, Steps, Stress, Body Battery, SpO2,
Respiration), one per tab — X = hour of day, Y = date, color = metric value.

Rules:
- No knowledge of Garmin internals or file sources — only the metric-key to
  METRIC_META-field mapping needed for display labels/units.
- All design assets from dash_layout and dash_layout_html.
- Receives neutral dict, writes output file.

Public interface:
    render(data: dict, output_path: Path) -> None
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import dash_layout      as layout
import dash_layout_html as layout_html

# ── Tab definitions — (metric key, tab label) ─────────────────────────────────

_TAB_DEFINITIONS = [
    ("heart_rate",   "Heart Rate"),
    ("steps",        "Steps"),
    ("stress",       "Stress"),
    ("body_battery", "Body Battery"),
    ("spo2",         "SpO2"),
    ("respiration",  "Respiration"),
]

# ── Metric key -> dash_layout.METRIC_META field (for label/unit lookup) ───────

_FIELD_FOR_KEY = {
    "heart_rate":   "heart_rate_series",
    "steps":        "steps_series",
    "stress":       "stress_series",
    "body_battery": "body_battery_series",
    "spo2":         "spo2_series",
    "respiration":  "respiration_series",
}

# ── Colorscales per metric ─────────────────────────────────────────────────────
# HR / Steps / Body Battery use Plotly.js named scales. Stress uses a custom
# scale built from its own brand color (dash_layout.METRIC_META["stress_series"])
# for visual consistency with every other Stress display in the app, rather
# than a generic library scale unrelated to the rest of the UI.

_COLORSCALES = {
    "heart_rate":   {"colorscale": "RdYlBu", "reversescale": True},
    "steps":        {"colorscale": "Viridis", "reversescale": False},
    "stress":       {"colorscale": [[0, "#f2faf7"], [0.5, "#7dcbab"], [1, "#1D9E75"]],
                      "reversescale": False},
    "body_battery": {"colorscale": "RdYlGn", "reversescale": False},
    "spo2":         {"colorscale": [[0, "#eef5fb"], [0.5, "#7fb3dd"], [1, "#185FA5"]],
                      "reversescale": False},
    "respiration":  {"colorscale": [[0, "#f5f4fd"], [0.5, "#bcb8ee"], [1, "#7F77DD"]],
                      "reversescale": False},
}


# ══════════════════════════════════════════════════════════════════════════════
#  Tab navigation
# ══════════════════════════════════════════════════════════════════════════════

def _build_tab_buttons() -> str:
    buttons = ""
    for i, (key, label) in enumerate(_TAB_DEFINITIONS):
        active = "active" if i == 0 else ""
        buttons += (
            f'<button class="tab-btn {active}" '
            f'onclick="showComplexTab(\'chart-{key}\')" '
            f'id="btn-chart-{key}">{label}</button>\n'
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
#  Panel building
# ══════════════════════════════════════════════════════════════════════════════

def _build_metric_panel(key: str, label: str, metric_data: dict, first: bool):
    """
    Builds one heatmap panel — a chart-container div (display toggled by
    the tab switcher) plus the Plotly.newPlot() call for it.
    Returns (div_html, js_code).
    """
    dates  = metric_data.get("dates", [])
    hours  = metric_data.get("hours", list(range(24)))
    matrix = metric_data.get("matrix", [])

    meta        = layout.get_metric_meta(_FIELD_FOR_KEY[key])
    unit        = meta.get("unit", "")
    unit_suffix = f" {unit}" if unit else ""

    scale = _COLORSCALES[key]

    dates_json        = json.dumps(dates)
    hours_json        = json.dumps(hours)
    matrix_json       = json.dumps(matrix)
    colorscale_json   = json.dumps(scale["colorscale"])
    reversescale_json = json.dumps(scale["reversescale"])

    display = "block" if first else "none"
    div_html = (
        f'<div class="chart-container" id="chart-{key}" style="display:{display};">'
        f'<div id="heatmap-{key}" style="width:100%;height:520px"></div>'
        f'</div>\n'
    )

    js = f"""
Plotly.newPlot('heatmap-{key}', [{{
  x: {hours_json},
  y: {dates_json},
  z: {matrix_json},
  type: 'heatmap',
  colorscale: {colorscale_json},
  reversescale: {reversescale_json},
  hoverongaps: false,
  hovertemplate: 'Date: %{{y}}<br>Hour: %{{x}}:00<br>{label}: %{{z}}{unit_suffix}<extra></extra>'
}}], {{
  margin: {{t: 20, r: 20, b: 50, l: 90}},
  xaxis: {{title: 'Hour of day', dtick: 2, range: [-0.5, 23.5]}},
  yaxis: {{title: 'Date', autorange: 'reversed'}},
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor:  'rgba(0,0,0,0)',
  font: {{family: 'Arial, sans-serif', size: 12}}
}}, {{responsive: true}});
"""
    return div_html, js


# ══════════════════════════════════════════════════════════════════════════════
#  Full render
# ══════════════════════════════════════════════════════════════════════════════

def _render_heatmap(data: dict, output_path: Path) -> None:
    """Render Heatmap dashboard — one Plotly heatmap panel per metric, tab
    navigation between them (analogous to Recovery Context's tabs)."""
    _raw_title = data.get("title", "Heatmap")
    title      = f"🦄 GARMIN LOCAL ARCHIVE — {_raw_title}"
    subtitle   = data.get("subtitle", "")
    metrics    = data.get("metrics")

    if metrics is None:
        raise ValueError("_render_heatmap: data dict must contain 'metrics' key")

    tab_buttons = _build_tab_buttons()
    tabs_html   = f'<div class="tabs">\n{tab_buttons}</div>\n'

    panels_html = ""
    js_blocks   = ""
    for i, (key, label) in enumerate(_TAB_DEFINITIONS):
        metric_data = metrics.get(key, {"dates": [], "hours": list(range(24)), "matrix": []})
        div_html, js = _build_metric_panel(key, label, metric_data, first=(i == 0))
        panels_html += div_html
        js_blocks   += js

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
{header_html}{disclaimer_html}{tabs_html}{panels_html}{footer_html}<script>
{_TAB_SWITCH_JS}
{js_blocks}
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
    """Entry point — delegates to _render_heatmap."""
    _render_heatmap(data, output_path)
