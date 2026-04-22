#!/usr/bin/env python3
"""
dash_plotter_html.py

HTML plotter — renders a specialist data dict to a self-contained HTML file
with Plotly charts and tab navigation.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Fetches all design assets from dash_layout and dash_layout_html.
- Receives neutral dict from dash_runner, writes output file.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dash_layout      as layout
import dash_layout_html as layout_html

# ══════════════════════════════════════════════════════════════════════════════
#  Internal builders
# ══════════════════════════════════════════════════════════════════════════════

def _build_tabs(fields: list[dict]) -> str:
    tabs = ""
    for i, entry in enumerate(fields):
        field  = entry["field"]
        meta   = layout.get_metric_meta(field)
        label  = meta.get("label", field)
        active = "active" if i == 0 else ""
        tabs += (
            f'<button class="tab-btn {active}" '
            f'onclick="showTab(\'{field}\')" '
            f'id="btn-{field}">{label}</button>\n'
        )
    return tabs


def _build_charts(fields: list[dict]) -> tuple[str, str]:
    """
    Returns (chart_divs, js_data).
    Detects chart type from field entry:
    - "series" present → Timeseries chart (one trace, intraday timestamps)
    - "days"   present → Analysis chart (four traces: value, baseline, ref band)
    """
    chart_divs = ""
    js_data    = ""

    for i, entry in enumerate(fields):
        field   = entry["field"]
        meta    = layout.get_metric_meta(field)
        label   = entry.get("label") or meta.get("label", field)
        unit    = entry.get("unit")  or meta.get("unit", "")
        color   = meta.get("color", "#888888")
        display = "block" if i == 0 else "none"

        chart_divs += (
            f'<div id="chart-{field}" class="chart-container" '
            f'style="display:{display}">'
            f'<div id="plot-{field}" style="width:100%;height:500px"></div>'
            f'</div>\n'
        )

        if "days" in entry:
            # ── Analysis chart — 4 traces: ref band, baseline, value ──────────
            days      = entry["days"]
            dates     = [d["date"]              for d in days]
            values    = [d["value"]             for d in days]
            baselines = [d.get("baseline")      for d in days]
            ref_low   = entry.get("ref_low")
            ref_high  = entry.get("ref_high")
            has_ref      = ref_low is not None and ref_high is not None
            has_baseline = any(b is not None for b in baselines)
            ref_upper = [ref_high] * len(dates) if has_ref else []
            ref_lower = [ref_low]  * len(dates) if has_ref else []

            dates_json      = json.dumps(dates)
            values_json     = json.dumps(values)
            ref_upper_json  = json.dumps(ref_upper)
            ref_lower_json  = json.dumps(ref_lower)
            baselines_clean = [b if b is not None else "null" for b in baselines]

            # Per-point marker color and tooltip data
            _COLOR_FLAG = "#e05c5c"
            statuses    = [d.get("status") for d in days]
            marker_colors = [
                _COLOR_FLAG if s in ("low", "high") else color
                for s in statuses
            ]
            marker_sizes = [
                8 if s in ("low", "high") else 5
                for s in statuses
            ]
            # customdata: [status, ref_low, ref_high, baseline] per point
            customdata = [
                [
                    d.get("status") or "",
                    ref_low  if ref_low  is not None else "",
                    ref_high if ref_high is not None else "",
                    round(d.get("baseline"), 1) if d.get("baseline") is not None else "",
                ]
                for d in days
            ]
            marker_colors_json = json.dumps(marker_colors)
            marker_sizes_json  = json.dumps(marker_sizes)
            customdata_json    = json.dumps(customdata)

            # Build traces list conditionally
            _traces = ""
            if has_ref:
                _traces += f"""
    {{
      x: {dates_json}, y: {ref_upper_json},
      type: 'scatter', mode: 'lines', name: 'Norm high',
      line: {{width: 0}}, showlegend: false, hoverinfo: 'skip'
    }},
    {{
      x: {dates_json}, y: {ref_lower_json},
      type: 'scatter', mode: 'lines', name: 'Reference range',
      fill: 'tonexty', fillcolor: 'rgba(100,180,100,0.12)',
      line: {{width: 0}}, hoverinfo: 'skip'
    }},"""
            if has_baseline:
                _traces += f"""
    {{
      x: {dates_json}, y: {json.dumps(baselines_clean)},
      type: 'scatter', mode: 'lines', name: '90d baseline',
      line: {{color: '{color}', width: 1.5, dash: 'dash'}},
      hovertemplate: '%{{x}}<br>90d avg: %{{y:.1f}} {unit}<extra></extra>'
    }},"""
            _traces += f"""
    {{
      x: {dates_json}, y: {values_json},
      type: 'scatter', mode: 'lines+markers', name: '{label}',
      line: {{color: '{color}', width: 2}},
      marker: {{size: {marker_sizes_json}, color: {marker_colors_json}}},
      customdata: {customdata_json},
      hovertemplate: '%{{x}}<br>{label}: %{{y:.1f}} {unit}<br>%{{customdata[0]}}<extra></extra>'
    }}"""

            js_data += f"""
  Plotly.newPlot('plot-{field}', [{_traces}
  ], {{
    margin: {{t: 40, r: 20, b: 60, l: 60}},
    xaxis: {{
      title: 'Date', type: 'date',
      rangeslider: {{visible: true}},
      rangeselector: {{buttons: [
        {{count:7, label:'7d', step:'day', stepmode:'backward'}},
        {{count:1, label:'1m', step:'month', stepmode:'backward'}},
        {{step:'all', label:'All'}}
      ]}}
    }},
    yaxis: {{title: '{label} ({unit})'}},
    legend: {{orientation: 'h', y: -0.25}},
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor:  'rgba(0,0,0,0)',
    font: {{family: 'Arial, sans-serif', size: 12}}
  }}, {{responsive: true}});
"""
        else:
            # ── Timeseries chart — single trace, intraday timestamps ──────────
            series     = entry.get("series") or []
            timestamps = [p["ts"]    for p in series]
            values     = [p["value"] for p in series]
            ts_json    = json.dumps(timestamps)
            val_json   = json.dumps(values)

            js_data += f"""
  Plotly.newPlot('plot-{field}', [{{
    x: {ts_json},
    y: {val_json},
    type: 'scatter',
    mode: 'lines',
    name: '{label}',
    line: {{ color: '{color}', width: 1.5 }},
    hovertemplate: '%{{x}}<br>{label}: %{{y}} {unit}<extra></extra>'
  }}], {{
    margin: {{ t: 40, r: 20, b: 60, l: 60 }},
    xaxis: {{
      title: 'Time',
      type: 'date',
      rangeslider: {{ visible: true }},
      rangeselector: {{
        buttons: [
          {{ count: 1,  label: '1d', step: 'day',  stepmode: 'backward' }},
          {{ count: 7,  label: '7d', step: 'day',  stepmode: 'backward' }},
          {{ count: 1,  label: '1m', step: 'month',stepmode: 'backward' }},
          {{ step: 'all', label: 'All' }}
        ]
      }}
    }},
    yaxis: {{ title: '{label} ({unit})' }},
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor:  'rgba(0,0,0,0)',
    font: {{ family: 'Arial, sans-serif', size: 12 }}
  }}, {{ responsive: true, displayModeBar: true }});
"""

    return chart_divs, js_data


# ══════════════════════════════════════════════════════════════════════════════
#  Plotly — local cache
# ══════════════════════════════════════════════════════════════════════════════

def _get_plotly_script(layouts_dir: Path) -> str:
    """
    Returns Plotly as an inline <script> tag.
    On first call: downloads from CDN and caches to layouts/plotly.min.js.
    On subsequent calls: reads from local cache — no internet required.

    Falls back to CDN <script src> tag if download fails.
    """
    import urllib.request

    local = layouts_dir / layout_html.get_plotly_local_filename()

    if not local.exists():
        try:
            url = layout_html.get_plotly_cdn()
            with urllib.request.urlopen(url, timeout=15) as resp:
                local.write_bytes(resp.read())
        except Exception:
            # Download failed — fall back to CDN tag
            return f'<script src="{layout_html.get_plotly_cdn()}"></script>'

    js = local.read_text(encoding="utf-8")
    return f"<script>{js}</script>"


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to HTML file.

    Args:
        data:        Dict from specialist.build() —
                     {"title": str, "subtitle": str, "fields": [...]}
        output_path: Full path for the output .html file.
        settings:    Settings dict from GUI (unused here, reserved for future use).

    Raises:
        OSError: if output file cannot be written.
    """
    title    = data.get("title", "Garmin Dashboard")
    subtitle = data.get("subtitle", "")
    fields   = [f for f in data.get("fields", []) if f.get("series") or f.get("days")]

    if not fields:
        raise ValueError("render: no fields with data — nothing to render")

    tabs             = _build_tabs(fields)
    chart_divs, js   = _build_charts(fields)
    header_html      = layout_html.build_header(title, subtitle)
    disclaimer_text  = layout.get_disclaimer()
    baseline_note    = data.get("baseline_note")
    if baseline_note:
        disclaimer_text = f"{disclaimer_text} {baseline_note}"
    disclaimer_html  = layout_html.build_disclaimer(disclaimer_text)
    footer_html      = layout_html.build_footer(layout.get_footer(html=True))
    css              = layout_html.get_css()
    plotly_cdn       = _get_plotly_script(Path(__file__).parent)

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
{tabs}</div>
{chart_divs}{footer_html}<script>
function showTab(field) {{
  document.querySelectorAll('.chart-container').forEach(d => d.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('chart-' + field).style.display = 'block';
  document.getElementById('btn-'   + field).classList.add('active');
  var plotDiv = document.getElementById('plot-' + field);
  if (plotDiv && plotDiv.data) {{ Plotly.relayout(plotDiv, {{autosize: true}}); }}
}}
{js}
</script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")