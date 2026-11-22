#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
layouts/render/intraday_block.py

The intraday day view shared by the Sleep and the Explorer layout: a date dropdown, a Plotly chart with
four fixed traces (Heart Rate, Stress, Body Battery, Respiration) and, optionally, the diary of the
selected day below it. Taken out of render/sleep.py (v1.7.8.1) so that both renderers use one block.

Rules:
- No knowledge of Garmin internals, field names, or data sources: receives neutral dicts, returns HTML+JS.
- The ids and function names carry a prefix, so two blocks never collide: with prefix "sleep" the output
  is the one render/sleep.py always produced (ids sleep-explorer, sleep-intraday-select, sleep-intraday-chart,
  functions sleepUpdateIntraday and sleepJumpToDay).
- The diary part is built with textContent only (a note is never put into the page as HTML) and its data
  is embedded with json_for_script(), which keeps "</script>" in a note from ending the script.
- The caller includes the Plotly script; this module does not.

Public interface:
    build_block(intraday, prefix="sleep", diary=None, include_diary_days=False) -> str
    json_for_script(obj) -> str
"""

import json


def json_for_script(obj) -> str:
    """json.dumps for embedding in a <script> element: "<", ">" and "&" are written as \\uXXXX."""
    return (json.dumps(obj)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _diary_html(prefix: str) -> str:
    return f"""
  <div id="{prefix}-intraday-none"
       style="display:none;font-size:13px;color:#888;padding:12px 0;">No intraday data for this day.</div>
  <div id="{prefix}-diary"
       style="margin-top:12px;padding-top:12px;border-top:1px solid #e0e0e0;font-size:13px;color:#333;"></div>"""


def _diary_js(prefix: str, diary: dict) -> str:
    diary_json = json_for_script(diary.get("days") or {})
    unread = {"damaged": int(diary.get("damaged") or 0), "unsupported": int(diary.get("unsupported") or 0)}
    unread_json = json_for_script(unread)
    return f"""
  var _diary  = {diary_json};
  var _unread = {unread_json};

  function _showDiary(date) {{
    var box = document.getElementById('{prefix}-diary');
    if (!box) return;
    box.textContent = '';
    var h = document.createElement('h3');
    h.textContent = 'Diary';
    h.style.cssText = 'font-size:14px;font-weight:600;color:#1a2a3a;margin:0 0 8px;';
    box.appendChild(h);
    var d = _diary[date];
    if (!d) {{
      var none = document.createElement('p');
      none.textContent = 'No diary entry on this day.';
      none.style.cssText = 'margin:0;color:#888;';
      box.appendChild(none);
    }} else {{
      if (d.note) {{
        var note = document.createElement('p');
        note.textContent = d.note;
        note.style.cssText = 'margin:0 0 8px;white-space:pre-wrap;';
        box.appendChild(note);
      }}
      if (d.entries && d.entries.length) {{
        var list = document.createElement('ul');
        list.style.cssText = 'margin:0;padding-left:18px;';
        d.entries.forEach(function(e) {{
          var li = document.createElement('li');
          li.textContent = (e.time ? e.time + '  ' : '') + e.name + ' \\u2014 ' + e.text;
          list.appendChild(li);
        }});
        box.appendChild(list);
      }}
    }}
    if (_unread.damaged || _unread.unsupported) {{
      var warn = document.createElement('p');
      warn.textContent = 'Diary days that could not be read in this range: ' + _unread.damaged +
                         ' damaged, ' + _unread.unsupported + ' of a newer version.';
      warn.style.cssText = 'margin:8px 0 0;color:#a05a00;font-size:12px;';
      box.appendChild(warn);
    }}
  }}"""


def build_block(intraday: dict, prefix: str = "sleep", diary: dict = None,
                include_diary_days: bool = False) -> str:
    """
    Build the day view — date dropdown, Plotly chart and (optional) diary of the day.
    Returns an empty string if there is nothing to show.

    Args:
        intraday: {date: {"heart_rate": [...], "stress": [...], "body_battery": [...], "respiration": [...]}}
                  — series are lists of {"ts", "value"} or None.
        prefix:   prefix of every id and function name ("sleep", "explorer").
        diary:    None, or {"days": {date: {"note", "entries": [{"time", "name", "text"}]}},
                  "damaged": n, "unsupported": n}: the diary of the selected day is shown below the chart.
        include_diary_days: when True the days of the diary are in the dropdown too (a day without
                  intraday data then shows a note instead of the chart); when False only the days of
                  intraday are listed.
    """
    diary_days = (diary or {}).get("days") or {}
    date_set = set(intraday or {})
    if diary is not None and include_diary_days:
        date_set |= set(diary_days)
    if not date_set:
        return ""
    intraday = intraday or {}

    dates = sorted(date_set, reverse=True)  # newest first in dropdown

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

    # ── The diary part and the empty-day handling exist only with a diary ────
    diary_html = diary_vars = diary_call = ""
    react_js = f"Plotly.react('{prefix}-intraday-chart', traces, layout, {{responsive: true}});"
    if diary is not None:
        diary_html = _diary_html(prefix)
        diary_vars = _diary_js(prefix, diary)
        diary_call = "\n    _showDiary(date);"
        react_js = f"""var chartEl = document.getElementById('{prefix}-intraday-chart');
    var noneEl  = document.getElementById('{prefix}-intraday-none');
    var hasData = [hr, st, bb, resp].some(function(s) {{ return s.x.length > 0; }});
    if (hasData) {{
      chartEl.style.display = '';
      noneEl.style.display  = 'none';
      Plotly.react('{prefix}-intraday-chart', traces, layout, {{responsive: true}});
    }} else {{
      Plotly.purge(chartEl);
      chartEl.style.display = 'none';
      noneEl.style.display  = 'block';
    }}"""

    # ── Colors (fixed, matching dash_layout phase palette) ───────────────────
    COLOR_HR   = "#E85D24"
    COLOR_ST   = "#1D9E75"
    COLOR_BB   = "#185FA5"
    COLOR_RESP = "#9b7fc7"

    div = f"""
<div id="{prefix}-explorer" style="background:#fff;margin:0;padding:16px 24px 24px;">
  <h2 style="font-size:15px;font-weight:600;color:#1a2a3a;margin-bottom:12px;">
    Intraday Detail
  </h2>
  <div style="padding-bottom:12px;">
    <label for="{prefix}-intraday-select"
           style="font-size:13px;margin-right:8px;color:#555;">Date:</label>
    <select id="{prefix}-intraday-select"
            onchange="{prefix}UpdateIntraday(this.value)"
            style="font-size:13px;padding:4px 8px;border-radius:4px;border:1px solid #ccc;">
{options_html}
    </select>
  </div>
  <div id="{prefix}-intraday-chart" style="width:100%;height:320px;"></div>{diary_html}
</div>
<script>
(function() {{
  var _intraday = {intraday_json};
  var _dates    = {dates_json};{diary_vars}

  function _makeSeries(arr) {{
    if (!arr || arr.length === 0) return {{x: [], y: []}};
    return {{
      x: arr.map(function(p) {{ return p.ts; }}),
      y: arr.map(function(p) {{ return p.value; }})
    }};
  }}

  window.{prefix}UpdateIntraday = function(date) {{
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

    {react_js}{diary_call}
  }};

  if (_dates.length > 0) {{
    {prefix}UpdateIntraday('{first_date}');
  }}

  window.{prefix}JumpToDay = function(date) {{
    var sel      = document.getElementById('{prefix}-intraday-select');
    var explorer = document.getElementById('{prefix}-explorer');
    if (!sel || !explorer) return;
    if (sel.value !== date) {{
      sel.value = date;
      {prefix}UpdateIntraday(date);
    }}
    explorer.scrollIntoView({{behavior: 'smooth', block: 'start'}});
  }};
}})();
</script>"""

    return div
