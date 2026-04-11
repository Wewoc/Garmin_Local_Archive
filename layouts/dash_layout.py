#!/usr/bin/env python3
"""
dash_layout.py

Passive resource — no active coordination.
Provides shared design tokens, metric metadata, disclaimer, and footer
used by all plotters regardless of output format.

Rules:
- No logic, no file I/O, no imports beyond stdlib.
- Called exclusively by plotters in layouts/ — never by specialists.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  Metric metadata — label, unit, and color tokens per field
#  Colors are format-neutral hex values — plotters apply them as needed.
# ══════════════════════════════════════════════════════════════════════════════

METRIC_META = {
    "heart_rate_series":   {"label": "Heart Rate",   "unit": "bpm",   "color": "#E85D24"},
    "stress_series":       {"label": "Stress",        "unit": "level", "color": "#1D9E75"},
    "spo2_series":         {"label": "SpO2",          "unit": "%",     "color": "#185FA5"},
    "body_battery_series": {"label": "Body Battery",  "unit": "level", "color": "#BA7517"},
    "respiration_series":  {"label": "Respiration",   "unit": "brpm",  "color": "#7F77DD"},
    # daily fields
    "hrv_last_night":      {"label": "HRV Last Night","unit": "ms",   "color": "#5B8DB8"},
    "resting_heart_rate":  {"label": "Resting HR",    "unit": "bpm",  "color": "#E85D24"},
    "spo2_avg":            {"label": "SpO2 Avg",      "unit": "%",    "color": "#185FA5"},
    "sleep_duration":      {"label": "Sleep",         "unit": "h",    "color": "#7F77DD"},
    "body_battery_max":    {"label": "Body Battery",  "unit": "level","color": "#BA7517"},
    "stress_avg":          {"label": "Stress Avg",    "unit": "level","color": "#1D9E75"},
    "vo2max":              {"label": "VO2max",        "unit": "",     "color": "#2E8B57"},
    # context fields
    "temperature_max":     {"label": "Temp Max",      "unit": "°C",   "color": "#E85D24"},
    "temperature_min":     {"label": "Temp Min",      "unit": "°C",   "color": "#185FA5"},
    "precipitation":       {"label": "Precipitation", "unit": "mm",   "color": "#5B8DB8"},
    "wind_speed_max":      {"label": "Wind Max",      "unit": "km/h", "color": "#1D9E75"},
    "uv_index_max":        {"label": "UV Index",      "unit": "",     "color": "#BA7517"},
    "sunshine_duration":   {"label": "Sunshine",      "unit": "h",    "color": "#F5A623"},
}

# ══════════════════════════════════════════════════════════════════════════════
#  Excel color tokens — stripped hex (no #) for openpyxl
# ══════════════════════════════════════════════════════════════════════════════

EXCEL_HEADER_COLOR  = "1F3864"   # dark navy — header fill
EXCEL_HEADER_FONT   = "FFFFFF"   # white — header font
EXCEL_BORDER_COLOR  = "D0D0D0"   # light grey — cell border

# Per-metric row fill colors (light tints, openpyxl format)
EXCEL_ROW_COLORS = {
    "heart_rate_series":   "FFE8CC",
    "stress_series":       "E8FFE8",
    "spo2_series":         "DDEEFF",
    "body_battery_series": "FFF8CC",
    "respiration_series":  "F0E8FF",
}

# ══════════════════════════════════════════════════════════════════════════════
#  Shared text
# ══════════════════════════════════════════════════════════════════════════════

DISCLAIMER = (
    "This report is generated from locally archived Garmin Connect data. "
    "Values are for personal reference only and do not constitute medical advice."
)

FOOTER = (
    "Generated locally · No data sent externally · "
    "<a href='https://github.com/Wewoc/Garmin_Local_Archive' "
    "style='color:#6ab0f5;text-decoration:none;'>"
    "github.com/Wewoc/Garmin_Local_Archive</a> · GNU GPL v3"
)

FOOTER_PLAIN = (
    "Generated locally · No data sent externally · "
    "github.com/Wewoc/Garmin_Local_Archive · GNU GPL v3"
)


# ══════════════════════════════════════════════════════════════════════════════
#  Public getters
# ══════════════════════════════════════════════════════════════════════════════

def get_metric_meta(field: str) -> dict:
    """Return label, unit, color for a field. Empty dict if unknown."""
    return METRIC_META.get(field, {})


def get_excel_row_color(field: str) -> str:
    """Return openpyxl hex row fill color for a field. White if unknown."""
    return EXCEL_ROW_COLORS.get(field, "FFFFFF")


def get_disclaimer() -> str:
    return DISCLAIMER


def get_footer(html: bool = True) -> str:
    """Return footer text. html=True includes anchor tag, html=False plain text."""
    return FOOTER if html else FOOTER_PLAIN