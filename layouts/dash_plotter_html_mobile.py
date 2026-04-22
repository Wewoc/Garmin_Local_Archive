#!/usr/bin/env python3
"""
dash_plotter_html_mobile.py

Mobile HTML plotter — renders Health Analysis specialist data dict
to a self-contained HTML file optimised for landscape phone viewing.

Layout:
- All metrics stacked vertically — no tabs.
- Charts sized for landscape (~700px wide, 280px tall).
- Global range dropdown (All / weeks / months) controls all charts at once.
- Zoom/drag disabled — range selection via dropdown only.
- Reference band, baseline, and flagged markers included.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Fetches all design assets from dash_layout and dash_layout_html.
- Receives neutral dict from dash_runner, writes output file.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dash_layout      as layout
import dash_layout_html as layout_html


# ══════════════════════════════════════════════════════════════════════════════
#  Plotly — local cache (shared with other html plotters)
# ══════════════════════════════════════════════════════════════════════════════

def _get_plotly_script(layouts_dir: Path) -> str:
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
#  Mobile CSS
# ══════════════════════════════════════════════════════════════════════════════

_MOBILE_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f5f5f5; color: #333; }
  header { background: #1F3864; color: #fff; padding: 12px 16px; }
  header h1 { font-size: 17px; font-weight: 600; }
  header p  { font-size: 11px; opacity: 0.75; margin-top: 3px; }
  .disclaimer { font-size: 10px; color: #888; padding: 6px 16px 4px; background: #fff; }
  .range-bar { background: #fff; padding: 8px 16px 10px;
               border-bottom: 1px solid #ddd; display: flex;
               align-items: center; gap: 8px; }
  .range-bar label { font-size: 12px; font-weight: 600; color: #1F3864; white-space: nowrap; }
  .range-bar select { font-size: 12px; padding: 4px 8px; border-radius: 4px;
                      border: 1px solid #ccc; flex: 1; max-width: 260px; }
  .metric-section { background: #fff; margin: 8px 0 0; padding: 10px 16px 16px; }
  .metric-title { font-size: 13px; font-weight: 600; color: #1F3864;
                  padding-bottom: 6px; border-bottom: 2px solid #1F3864;
                  margin-bottom: 8px; }
  footer { text-align: center; padding: 12px; font-size: 10px; color: #999; }
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Range options builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_range_options(all_dates: list[str]) -> list[dict]:
    """
    Build dropdown options from available dates.
    Returns list of {"label": str, "from": str, "to": str}.
    """
    if not all_dates:
        return []

    d_min = date.fromisoformat(min(all_dates))
    d_max = date.fromisoformat(max(all_dates))
    options = []

    # Fixed ranges — anchored to last available date
    options.append({"label": "All",         "from": d_min.isoformat(), "to": d_max.isoformat()})
    options.append({"label": "Last 7 days", "from": (d_max - timedelta(days=6)).isoformat(), "to": d_max.isoformat()})
    options.append({"label": "Last 30 days","from": (d_max - timedelta(days=29)).isoformat(), "to": d_max.isoformat()})
    options.append({"label": "Last 90 days","from": (d_max - timedelta(days=89)).isoformat(), "to": d_max.isoformat()})
    options.append({"label": "──────────", "from": "", "to": ""})  # separator

    # Calendar months — newest first
    months = set()
    for ds in all_dates:
        d = date.fromisoformat(ds)
        months.add((d.year, d.month))
    for year, month in sorted(months, reverse=True):
        first = date(year, month, 1)
        if month == 12:
            last = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last = date(year, month + 1, 1) - timedelta(days=1)
        last = min(last, d_max)
        first = max(first, d_min)
        label = first.strftime("%B %Y")
        options.append({"label": label, "from": first.isoformat(), "to": last.isoformat()})

    options.append({"label": "──────────", "from": "", "to": ""})  # separator

    # Calendar weeks — newest first
    weeks = set()
    for ds in all_dates:
        d = date.fromisoformat(ds)
        iso = d.isocalendar()
        weeks.add((iso[0], iso[1]))
    for iso_year, iso_week in sorted(weeks, reverse=True):
        monday = date.fromisocalendar(iso_year, iso_week, 1)
        sunday = monday + timedelta(days=6)
        monday = max(monday, d_min)
        sunday = min(sunday, d_max)
        label = f"KW {iso_week:02d} {iso_year}  ({monday.strftime('%d.%m')}–{sunday.strftime('%d.%m')})"
        options.append({"label": label, "from": monday.isoformat(), "to": sunday.isoformat()})

    return options


# ══════════════════════════════════════════════════════════════════════════════
#  Chart builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_charts(fields: list[dict]) -> tuple[str, str, list[str]]:
    """
    Returns (sections_html, js_data, plot_ids).
    One section per field — label header + chart div stacked vertically.
    Analysis fields only — series (intraday) fields are skipped.
    """
    sections_html = ""
    js_data       = ""
    plot_ids      = []

    for entry in fields:
        if "days" not in entry:
            continue

        field  = entry["field"]
        meta   = layout.get_metric_meta(field)
        label  = entry.get("label") or meta.get("label", field)
        unit   = entry.get("unit")  or meta.get("unit", "")
        color  = meta.get("color", "#888888")

        days      = entry["days"]
        dates     = [d["date"]         for d in days]
        values    = [d["value"]        for d in days]
        baselines = [d.get("baseline") for d in days]
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

        _COLOR_FLAG = "#e05c5c"
        statuses    = [d.get("status") for d in days]
        marker_colors = [_COLOR_FLAG if s in ("low", "high") else color for s in statuses]
        marker_sizes  = [7 if s in ("low", "high") else 4 for s in statuses]
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

        plot_id = f"plot-{field}"
        plot_ids.append(plot_id)

        sections_html += (
            f'<div class="metric-section">'
            f'<div class="metric-title">{label}</div>'
            f'<div id="{plot_id}" style="width:100%;height:280px"></div>'
            f'</div>\n'
        )

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
  Plotly.newPlot('{plot_id}', [{_traces}
  ], {{
    margin: {{t: 10, r: 16, b: 50, l: 50}},
    xaxis: {{type: 'date'}},
    yaxis: {{title: '{unit}'}},
    dragmode: false,
    legend: {{orientation: 'h', y: -0.28, font: {{size: 10}}}},
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor:  'rgba(0,0,0,0)',
    font: {{family: 'Arial, sans-serif', size: 11}}
  }}, {{responsive: true, displayModeBar: false}});
"""

    return sections_html, js_data, plot_ids


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to mobile-optimised HTML file.

    Args:
        data:        Dict from specialist.build() —
                     {"title": str, "subtitle": str, "fields": [...]}
        output_path: Full path for the output .html file.
        settings:    Settings dict from GUI (unused here, reserved).

    Raises:
        ValueError: if no fields with data.
        OSError:    if output file cannot be written.
    """
    title    = data.get("title", "Garmin Dashboard")
    subtitle = data.get("subtitle", "")
    fields   = [f for f in data.get("fields", []) if f.get("days")]

    if not fields:
        raise ValueError("render: no fields with data — nothing to render")

    # Collect all dates across fields for range dropdown
    all_dates = sorted(set(
        d["date"] for f in fields for d in f.get("days", [])
        if d.get("value") is not None
    ))
    range_options  = _build_range_options(all_dates)
    options_json   = json.dumps(range_options)

    # Build dropdown HTML
    dropdown_options_html = ""
    for i, opt in enumerate(range_options):
        if opt["from"] == "" :  # separator
            dropdown_options_html += f'<option disabled>──────────</option>\n'
        else:
            selected = "selected" if i == 0 else ""
            dropdown_options_html += (
                f'<option value="{i}" {selected}>{opt["label"]}</option>\n'
            )

    range_bar_html = f"""<div class="range-bar">
  <label>Range:</label>
  <select id="range-select" onchange="applyRange(this.value)">
{dropdown_options_html}  </select>
</div>
"""

    sections_html, js_data, plot_ids = _build_charts(fields)

    plot_ids_json = json.dumps(plot_ids)

    range_js = f"""
var _rangeOptions = {options_json};
var _plotIds = {plot_ids_json};

function applyRange(idx) {{
  var opt = _rangeOptions[parseInt(idx)];
  if (!opt || opt.from === '') return;
  _plotIds.forEach(function(pid) {{
    var el = document.getElementById(pid);
    if (el && el.data) {{
      Plotly.relayout(el, {{'xaxis.range': [opt.from, opt.to]}});
    }}
  }});
}}

// Apply "All" on load
window.addEventListener('load', function() {{ applyRange(0); }});
"""

    disclaimer_text = layout.get_disclaimer()
    baseline_note   = data.get("baseline_note")
    if baseline_note:
        disclaimer_text = f"{disclaimer_text} {baseline_note}"

    header_html     = layout_html.build_header(title, subtitle)
    disclaimer_html = layout_html.build_disclaimer(disclaimer_text)
    footer_html     = layout_html.build_footer(layout.get_footer(html=True))
    plotly_cdn      = _get_plotly_script(Path(__file__).parent)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, orientation=landscape">
<title>{title}</title>
{plotly_cdn}
<style>{_MOBILE_CSS}</style>
</head>
<body>
{header_html}{disclaimer_html}{range_bar_html}{sections_html}{footer_html}<script>
{js_data}
{range_js}
</script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")