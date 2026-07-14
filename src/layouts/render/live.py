#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
layouts/render/live.py

Render function for the Live Tracking layout.

Deliberately different from every other renderer in layouts/render/:
- Dark theme matching the app's own palette (garmin_app_base.py BG/ACCENT/...),
  not the shared light-theme CSS in dash_layout_html.py. Live Tracking is
  meant to feel like an extension of the app itself, not a standalone
  report — confirmed against a mockup before this file was built.
- No Plotly dependency — four small sparklines don't justify loading the
  full Plotly bundle. Inline SVG only. Mirrors the "lightweight live
  fetch" principle of the feature itself.
- Header/disclaimer/footer are NOT built via dash_layout_html.build_header()/
  build_disclaimer()/build_footer() — those emit markup tied to the shared
  light-theme CSS (.disclaimer background:#fff, etc.), which would clash
  with the dark body background here. Disclaimer/footer TEXT is still
  sourced from dash_layout.get_disclaimer()/get_footer() (plain string
  getters, no markup coupling) — the disclaimer itself is never skipped,
  only its wrapper markup is local to this module.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Receives neutral dict, writes output file.

Public interface:
    render(data: dict, output_path: Path) -> None
"""

import html as html_escape
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import dash_layout as layout

# ── Design tokens — mirrors garmin_app_base.py's own dark theme ──────────────
_BG      = "#12101f"
_BG2     = "#1a1729"
_BG3     = "#231f38"
_ACCENT  = "#a259f7"
_TEXT    = "#eaeaea"
_TEXT2   = "#a0a0b0"

_METRIC_COLORS = {
    "body_battery": "#BA7517",
    "heart_rate":   "#E85D24",
    "steps":        "#4A90D9",
    "stress":       "#1D9E75",
}
_METRIC_LABELS = {
    "body_battery": ("Body Battery", ""),
    "heart_rate":   ("Heart Rate", "bpm"),
    "steps":        ("Steps", ""),
    "stress":       ("Stress", ""),
}

_PHASE_COLORS = {
    "deep":  "#185FA5",
    "light": "#7F77DD",
    "rem":   "#1D9E75",
    "awake": "#BA7517",
}
_PHASE_TEXT_COLORS = {
    "deep":  "#e6f1fb",
    "light": "#26215c",
    "rem":   "#04342c",
    "awake": "#412402",
}
_PHASE_LABELS = {"deep": "Deep", "light": "Light", "rem": "REM", "awake": "Awake"}

_QUALIFIER_COLORS = {
    "EXCELLENT": "#1D9E75",
    "GOOD":      "#5B8DB8",
    "FAIR":      "#BA7517",
    "POOR":      "#e05c5c",
}

_FEEDBACK_LABELS = {
    "POSITIVE_DEEP":                     "Deep sleep",
    "POSITIVE_CONTINUOUS":               "Continuous sleep",
    "POSITIVE_LONG_AND_DEEP":            "Long and deep",
    "POSITIVE_LONG_AND_CONTINUOUS":      "Long and continuous",
    "POSITIVE_LONG_AND_REFRESHING":      "Long and refreshing",
    "POSITIVE_LONG_AND_RECOVERING":      "Long and recovering",
    "NEGATIVE_LONG_BUT_NOT_ENOUGH_DEEP": "Long but not enough deep",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _sparkline_svg(series: list, color: str) -> str:
    """
    Minimal inline SVG line sparkline from [{"ts": str, "value": float}, ...].
    No axes, no labels — a single trend line.
    Missing/empty series → dashed flat placeholder, no crash, no gap.
    """
    values = [p["value"] for p in (series or []) if p.get("value") is not None]
    if not values:
        return (f'<svg viewBox="0 0 160 36" width="100%" height="36">'
                f'<line x1="0" y1="18" x2="160" y2="18" stroke="{color}" '
                f'stroke-width="1" stroke-dasharray="3,3" opacity="0.4"/></svg>')

    lo, hi = min(values), max(values)
    span   = (hi - lo) or 1
    n      = len(values)
    step   = 160 / max(n - 1, 1)
    points = " ".join(
        f"{i * step:.1f},{34 - ((v - lo) / span) * 30:.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg viewBox="0 0 160 36" width="100%" height="36" preserveAspectRatio="none">'
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/></svg>')


def _steps_bars_svg(series: list, color: str) -> str:
    """Bar-style sparkline for steps — count metric, bars read better than a line."""
    values = [p["value"] for p in (series or []) if p.get("value") is not None]
    if not values:
        return _sparkline_svg([], color)
    hi   = max(values) or 1
    n    = len(values)
    w    = 160 / n
    bars = "".join(
        f'<rect x="{i * w:.1f}" y="{36 - (v / hi) * 32:.1f}" '
        f'width="{w * 0.7:.1f}" height="{(v / hi) * 32:.1f}" fill="{color}"/>'
        for i, v in enumerate(values)
    )
    return f'<svg viewBox="0 0 160 36" width="100%" height="36" preserveAspectRatio="none">{bars}</svg>'


def _metric_card(key: str, metric: dict) -> str:
    label, unit = _METRIC_LABELS[key]
    color       = _METRIC_COLORS[key]
    current     = metric.get("current")
    series      = metric.get("series") or []
    value_str   = f"{current:,.0f}".replace(",", " ") if current is not None else "—"
    unit_html   = (f' <span style="font-size:11px;font-weight:400;color:{_TEXT2};">'
                   f'{html_escape.escape(unit)}</span>') if unit else ""
    chart = _steps_bars_svg(series, color) if key == "steps" else _sparkline_svg(series, color)
    return f"""
<div style="background:{_BG2};border-radius:8px;padding:12px 14px;">
  <div style="font-size:12px;color:{_TEXT2};">{html_escape.escape(label)}</div>
  <div style="font-size:22px;font-weight:600;color:{_TEXT};margin:2px 0 6px;">{value_str}{unit_html}</div>
  {chart}
</div>"""


def _phase_bar_html(phases: dict) -> str:
    segments, legend = "", ""
    for key in ("deep", "light", "rem", "awake"):
        pct    = phases.get(key) or 0
        color  = _PHASE_COLORS[key]
        text_c = _PHASE_TEXT_COLORS[key]
        letter = key[0].upper()
        segments += (
            f'<div style="width:{pct}%;background:{color};display:flex;'
            f'align-items:center;justify-content:center;">'
            f'<span style="font-size:11px;font-weight:600;color:{text_c};">{letter}</span></div>'
        )
        legend += (
            f'<span><span style="display:inline-block;width:8px;height:8px;'
            f'background:{color};border-radius:2px;margin-right:4px;"></span>'
            f'{_PHASE_LABELS[key]} {pct}%</span>'
        )
    return (
        f'<div style="display:flex;height:26px;border-radius:5px;overflow:hidden;">{segments}</div>'
        f'<div style="display:flex;gap:14px;margin-top:8px;font-size:11px;color:{_TEXT2};flex-wrap:wrap;">{legend}</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path) -> None:
    """Entry point — Live Tracking page render."""
    today      = data.get("today")
    last_night = data.get("last_night")

    if not today or not last_night:
        raise ValueError("render: data dict must contain non-empty 'today' and 'last_night'")

    _raw_title = data.get("title", "Live Tracking")
    title      = f"🦄 GARMIN LOCAL ARCHIVE — {_raw_title}"
    subtitle   = data.get("subtitle", "")

    today_cards = "".join(
        _metric_card(k, today[k]) for k in ("body_battery", "heart_rate", "steps", "stress")
        if k in today
    )

    qualifier        = last_night.get("qualifier") or "no_data"
    qualifier_color  = _QUALIFIER_COLORS.get(qualifier, "#888888")
    score            = last_night.get("score")
    score_str        = str(score) if score is not None else "—"
    duration_h       = last_night.get("duration_h")
    duration_str     = f"{duration_h}h" if duration_h is not None else "—"
    hrv              = last_night.get("hrv")
    hrv_str          = f"{hrv} ms" if hrv is not None else "— ms"
    hrv_7d           = last_night.get("hrv_7d_avg")
    hrv_7d_str       = f"7d Ø {hrv_7d} ms" if hrv_7d is not None else "7d Ø —"
    feedback_key     = last_night.get("feedback")
    feedback_str     = _FEEDBACK_LABELS.get(feedback_key, feedback_key or "—")
    phases           = last_night.get("phases") or {}

    archive_note = ""
    if last_night.get("source") == "archive":
        archive_note = (
            f'<div style="font-size:11px;color:{_TEXT2};margin-top:8px;">'
            f'No live snapshot for last night yet — showing archived data.</div>'
        )

    header_html = f"""
<div style="background:{_BG3};padding:16px 20px;">
  <div style="font-size:16px;font-weight:600;color:{_TEXT};">{html_escape.escape(title)}</div>
  <div style="font-size:12px;color:{_TEXT2};margin-top:2px;">{html_escape.escape(subtitle)}</div>
</div>"""

    disclaimer_html = (
        f'<div style="font-size:11px;color:{_TEXT2};padding:10px 20px 0;">'
        f'{html_escape.escape(layout.get_disclaimer())}</div>'
    )

    footer_html = (
        f'<div style="text-align:center;padding:16px;font-size:11px;color:{_TEXT2};">'
        f'{layout.get_footer(html=True)}</div>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="margin:0;background:{_BG};font-family:Arial,sans-serif;color:{_TEXT};">
{header_html}{disclaimer_html}
<div style="padding:18px 20px 8px;">
  <div style="font-size:11px;font-weight:600;letter-spacing:0.5px;color:{_ACCENT};text-transform:uppercase;margin-bottom:10px;">Today</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;">
    {today_cards}
  </div>
</div>
<div style="padding:18px 20px 20px;">
  <div style="font-size:11px;font-weight:600;letter-spacing:0.5px;color:{_ACCENT};text-transform:uppercase;margin-bottom:10px;">Last night</div>
  <div style="background:{_BG2};border-radius:8px;padding:14px 16px;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;">
      <span style="font-size:20px;font-weight:600;">{score_str}</span>
      <span style="background:{qualifier_color};color:{_BG};font-size:11px;font-weight:600;padding:3px 10px;border-radius:12px;">{html_escape.escape(qualifier)}</span>
      <span style="color:{_TEXT2};font-size:12px;">{duration_str}</span>
      <span style="color:{_TEXT2};font-size:12px;">·</span>
      <span style="color:{_TEXT2};font-size:12px;">HRV {hrv_str}</span>
      <span style="color:{_TEXT2};font-size:12px;">·</span>
      <span style="color:{_TEXT2};font-size:12px;">{hrv_7d_str}</span>
    </div>
    {_phase_bar_html(phases)}
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid {_BG3};">
      <div style="font-size:11px;color:{_TEXT2};margin-bottom:3px;">Feedback</div>
      <div style="font-size:13px;color:{_TEXT};">{html_escape.escape(feedback_str)}</div>
    </div>
    {archive_note}
  </div>
</div>
{footer_html}
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
