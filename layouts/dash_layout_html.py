#!/usr/bin/env python3
"""
dash_layout_html.py

Passive resource — HTML-specific layout assets.
Provides CSS, header template, and tab structure for HTML plotters.

Rules:
- No logic, no file I/O, no imports.
- Called exclusively by HTML plotters in layouts/.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════════════════════

CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f5f5f5; color: #333; }
  header { background: #1F3864; color: #fff; padding: 16px 24px; }
  header h1 { font-size: 20px; font-weight: 600; }
  header p  { font-size: 13px; opacity: 0.75; margin-top: 4px; }
  .disclaimer { font-size: 11px; color: #888; padding: 8px 24px 0; background: #fff; }
  .tabs { display: flex; gap: 4px; padding: 12px 24px 0; background: #fff;
          border-bottom: 1px solid #ddd; flex-wrap: wrap; }
  .tab-btn {
    padding: 8px 18px; border: none; border-radius: 6px 6px 0 0;
    background: #eee; cursor: pointer; font-size: 13px;
    font-family: Arial, sans-serif; border-bottom: 3px solid transparent;
    transition: background 0.15s;
  }
  .tab-btn:hover  { background: #ddd; }
  .tab-btn.active { background: #fff; border-bottom: 3px solid #1F3864; font-weight: 600; }
  .chart-container { background: #fff; margin: 0; padding: 16px 24px 24px; }
  footer { text-align: center; padding: 16px; font-size: 11px; color: #999; }
"""

PLOTLY_CDN     = "https://cdn.plot.ly/plotly-2.27.0.min.js"
PLOTLY_VERSION = "2.27.0"
PLOTLY_LOCAL   = "plotly.min.js"   # filename only — plotter resolves full path


def get_plotly_cdn() -> str:
    return PLOTLY_CDN


def get_plotly_version() -> str:
    return PLOTLY_VERSION


def get_plotly_local_filename() -> str:
    return PLOTLY_LOCAL

# ══════════════════════════════════════════════════════════════════════════════
#  Template builders
# ══════════════════════════════════════════════════════════════════════════════

def build_header(title: str, subtitle: str) -> str:
    return (
        f"<header>\n"
        f"  <h1>{title}</h1>\n"
        f"  <p>{subtitle}</p>\n"
        f"</header>\n"
    )


def build_disclaimer(text: str) -> str:
    return f'<div class="disclaimer">{text}</div>\n'


def build_footer(text: str) -> str:
    return f"<footer>{text}</footer>\n"


def get_css() -> str:
    return CSS


def get_plotly_cdn() -> str:
    return PLOTLY_CDN