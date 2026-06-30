#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
layouts/render/sleep.py

Render function for the Sleep Dashboard layout.
Pure HTML/CSS table — one row per night, no Plotly dependency.

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

_LAYOUTS_DIR = Path(__file__).parent.parent


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path) -> None:
    """Entry point — delegates to _render_sleep."""
    _render_sleep(data, output_path)


def _render_sleep(data: dict, output_path: Path) -> None:
    """Sleep Dashboard render — one row per night, HTML/CSS table + intraday Plotly explorer."""
    _raw_title = data.get("title", "Sleep Dashboard")
    title      = f"🦄 GARMIN LOCAL ARCHIVE — {_raw_title}"
    subtitle   = data.get("subtitle", "")
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
            f'{html_escape.escape(qualifier)}</span>'
        )

    def _feedback_text(feedback):
        if not feedback:
            return '<span style="color:#888;">—</span>'
        # Convert NEGATIVE_LONG_BUT_NOT_ENOUGH_REM → Long / Not Enough REM
        cleaned = feedback.replace("NEGATIVE_", "").replace("POSITIVE_", "")
        parts   = [p.capitalize().replace("_", " ") for p in cleaned.split("_AND_")]
        return f'<span style="color:#aaa;font-size:12px;">{html_escape.escape(" · ".join(parts))}</span>'

    # ── Build table rows ──────────────────────────────────────────────────────

    row_html = ""
    for row in rows:
        date        = html_escape.escape(str(row.get("date", "")))
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

        hrv_7d     = row.get("hrv_7d_avg")
        hrv_7d_color = _hsl_color(hrv_7d, ref_hrv_low, ref_hrv_high, higher_better=True)
        hrv_7d_str = f"{hrv_7d:.1f}" if hrv_7d is not None else "—"

        row_html += f"""
<tr onclick="sleepJumpToDay('{date}')" title="Click to jump to intraday view"
    style="cursor:pointer;">
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">{date}</td>
  <td style="padding:6px 10px;min-width:140px;">{_phase_bar(row)}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{dur_color};">{dur_str}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{score_color};">{score_str}</td>
  <td style="padding:6px 10px;text-align:center;">{_qualifier_badge(row.get("qualifier"))}</td>
  <td style="padding:6px 10px;">{_feedback_text(row.get("feedback"))}</td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid #333;font-weight:700;color:{hrv_color};">{hrv_str}</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:{bb_color};">{bb_str}</td>
  <td style="padding:6px 10px;text-align:center;color:{hrv_7d_color};font-size:12px;">{hrv_7d_str}</td>
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
  <th>HRV 7d Ø</th>
</tr>
</thead>
<tbody>
{row_html}
</tbody>
</table>"""


    # ── Intraday explorer block ───────────────────────────────────────────────
    intraday     = data.get("intraday") or {}
    explorer_div = _build_intraday_explorer(intraday, refs)

    # ── Plotly (only if intraday data present) ────────────────────────────────
    if intraday:
        plotly_script = layout_html.get_plotly_script(_LAYOUTS_DIR)
    else:
        plotly_script = ""

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
{plotly_script}
{explorer_div}
{footer_html}
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _build_intraday_explorer(intraday: dict, refs: dict) -> str:
    """
    Build the intraday explorer section — date dropdown + Plotly chart.
    Returns empty string if no intraday data is available.
    Four fixed traces: Heart Rate, Stress, Body Battery, Respiration.
    """
    if not intraday:
        return ""

    dates = sorted(intraday.keys(), reverse=True)  # newest first in dropdown

    # ── Embed intraday data as JSON ───────────────────────────────────────────
    intraday_js = {}
    for d, day in intraday.items():
        intraday_js[d] = {
            "heart_rate":   day.get("heart_rate")   or [],
            "stress":       day.get("stress")        or [],
            "body_battery": day.get("body_battery")  or [],
            "respiration":  day.get("respiration")   or [],
        }

    intraday_json = json.dumps(intraday_js)
    dates_json    = json.dumps(dates)
    first_date    = dates[0] if dates else ""

    options_html = "\n".join(
        f'        <option value="{d}">{d}</option>' for d in dates
    )

    # ── Colors (fixed, matching dash_layout phase palette) ───────────────────
    COLOR_HR   = "#E85D24"
    COLOR_ST   = "#1D9E75"
    COLOR_BB   = "#185FA5"
    COLOR_RESP = "#9b7fc7"

    div = f"""
<div id="sleep-explorer" style="background:#fff;margin:0;padding:16px 24px 24px;">
  <h2 style="font-size:15px;font-weight:600;color:#1a2a3a;margin-bottom:12px;">
    Intraday Detail
  </h2>
  <div style="padding-bottom:12px;">
    <label for="sleep-intraday-select"
           style="font-size:13px;margin-right:8px;color:#555;">Date:</label>
    <select id="sleep-intraday-select"
            onchange="sleepUpdateIntraday(this.value)"
            style="font-size:13px;padding:4px 8px;border-radius:4px;border:1px solid #ccc;">
{options_html}
    </select>
  </div>
  <div id="sleep-intraday-chart" style="width:100%;height:320px;"></div>
</div>
<script>
(function() {{
  var _intraday = {intraday_json};
  var _dates    = {dates_json};

  function _makeSeries(arr) {{
    if (!arr || arr.length === 0) return {{x: [], y: []}};
    return {{
      x: arr.map(function(p) {{ return p.ts; }}),
      y: arr.map(function(p) {{ return p.value; }})
    }};
  }}

  window.sleepUpdateIntraday = function(date) {{
    var day = _intraday[date] || {{}};
    var hr   = _makeSeries(day.heart_rate);
    var st   = _makeSeries(day.stress);
    var bb   = _makeSeries(day.body_battery);
    var resp = _makeSeries(day.respiration);

    var traces = [
      {{ x: hr.x,   y: hr.y,   name: 'Heart Rate',   type: 'scatter', mode: 'lines',
         line: {{color: '{COLOR_HR}',   width: 1.5}},
         yaxis: 'y1',
         hovertemplate: '%{{x}}<br>HR: %{{y:.0f}} bpm<extra></extra>' }},
      {{ x: st.x,   y: st.y,   name: 'Stress',       type: 'scatter', mode: 'lines',
         line: {{color: '{COLOR_ST}',   width: 1.5}},
         yaxis: 'y2',
         hovertemplate: '%{{x}}<br>Stress: %{{y:.0f}}<extra></extra>' }},
      {{ x: bb.x,   y: bb.y,   name: 'Body Battery', type: 'scatter', mode: 'lines',
         line: {{color: '{COLOR_BB}',   width: 1.5}},
         yaxis: 'y3',
         hovertemplate: '%{{x}}<br>Body Battery: %{{y:.0f}}<extra></extra>' }},
      {{ x: resp.x, y: resp.y, name: 'Respiration',  type: 'scatter', mode: 'lines',
         line: {{color: '{COLOR_RESP}', width: 1.5, dash: 'dot'}},
         yaxis: 'y4',
         hovertemplate: '%{{x}}<br>Respiration: %{{y:.1f}} brpm<extra></extra>' }}
    ];

    var layout = {{
      margin:     {{t: 20, b: 60, l: 50, r: 50}},
      height:     320,
      paper_bgcolor: '#fff',
      plot_bgcolor:  '#f9f9fb',
      showlegend: true,
      legend:     {{orientation: 'h', y: -0.18, font: {{size: 11}}}},
      xaxis:  {{type: 'date', showgrid: true, gridcolor: '#eee'}},
      yaxis:  {{title: 'HR (bpm)',  titlefont: {{size: 11, color: '{COLOR_HR}'}},
                showgrid: false, overlaying: false, side: 'left'}},
      yaxis2: {{title: 'Stress',    titlefont: {{size: 11, color: '{COLOR_ST}'}},
                showgrid: false, overlaying: 'y', side: 'right', anchor: 'x'}},
      yaxis3: {{title: 'Batt.',     titlefont: {{size: 11, color: '{COLOR_BB}'}},
                showgrid: false, overlaying: 'y', side: 'left',  anchor: 'free', position: 0.0}},
      yaxis4: {{title: 'Resp.',     titlefont: {{size: 11, color: '{COLOR_RESP}'}},
                showgrid: false, overlaying: 'y', side: 'right', anchor: 'free', position: 1.0}}
    }};

    Plotly.react('sleep-intraday-chart', traces, layout, {{responsive: true}});
  }};

  if (_dates.length > 0) {{
    sleepUpdateIntraday('{first_date}');
  }}

  window.sleepJumpToDay = function(date) {{
    var sel      = document.getElementById('sleep-intraday-select');
    var explorer = document.getElementById('sleep-explorer');
    if (!sel || !explorer) return;
    if (sel.value !== date) {{
      sel.value = date;
      sleepUpdateIntraday(date);
    }}
    explorer.scrollIntoView({{behavior: 'smooth', block: 'start'}});
  }};
}})();
</script>"""

    return div

