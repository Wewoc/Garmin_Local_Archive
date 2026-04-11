#!/usr/bin/env python3
"""
dash_plotter_excel.py

Excel plotter — renders a specialist data dict to an .xlsx file.
One data sheet + one chart sheet per field.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Fetches all design assets from dash_layout.
- Receives neutral dict from dash_runner, writes output file.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import LineChart, Reference
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
import dash_layout as layout

# ══════════════════════════════════════════════════════════════════════════════
#  Shared styles — built once from dash_layout tokens
# ══════════════════════════════════════════════════════════════════════════════

_HEADER_FILL = PatternFill("solid", start_color=layout.EXCEL_HEADER_COLOR)
_HEADER_FONT = Font(name="Arial", bold=True,  color=layout.EXCEL_HEADER_FONT, size=10)
_DATA_FONT   = Font(name="Arial", bold=False, color="000000",                 size=10)
_DATE_FONT   = Font(name="Arial", bold=True,  color="000000",                 size=10)
_BORDER_SIDE = Side(style="thin", color=layout.EXCEL_BORDER_COLOR)
_CELL_BORDER = Border(
    left=_BORDER_SIDE, right=_BORDER_SIDE,
    top=_BORDER_SIDE,  bottom=_BORDER_SIDE,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal builders
# ══════════════════════════════════════════════════════════════════════════════

def _write_field_sheets(wb: Workbook, entry: dict, date_from: str, date_to: str) -> None:
    """Write one data sheet + one chart sheet for a single field."""
    field  = entry["field"]
    series = entry.get("series") or []
    meta   = layout.get_metric_meta(field)
    label  = meta.get("label", field)
    unit   = meta.get("unit", "")
    color  = meta.get("color", "#888888").lstrip("#")
    fill   = layout.get_excel_row_color(field)

    data_title  = f"{label} - Data"
    chart_title = f"{label} - Chart"

    # ── Data sheet ────────────────────────────────────────────────────────────
    ws = wb.create_sheet(data_title)
    ws.freeze_panes = "A2"

    headers = ["Date", "Time", unit or "Value"]
    widths  = [12, 8, 10]

    for col, (h, w) in enumerate(zip(headers, widths), start=1):
        cell            = ws.cell(1, col, h)
        cell.font       = _HEADER_FONT
        cell.fill       = _HEADER_FILL
        cell.alignment  = Alignment(horizontal="center")
        cell.border     = _CELL_BORDER
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.row_dimensions[1].height = 24
    row_fill = PatternFill("solid", start_color=fill)

    for row_idx, point in enumerate(series, start=2):
        ts  = point.get("ts", "")
        val = point.get("value")

        # Split ISO timestamp into date + time parts
        if "T" in ts:
            day, time = ts[:10], ts[11:16]
        else:
            day, time = ts, ""

        ws.cell(row_idx, 1, day).font  = _DATE_FONT
        ws.cell(row_idx, 1).alignment  = Alignment(horizontal="center")
        ws.cell(row_idx, 1).border     = _CELL_BORDER
        ws.cell(row_idx, 2, time).font = _DATA_FONT
        ws.cell(row_idx, 2).alignment  = Alignment(horizontal="center")
        ws.cell(row_idx, 2).border     = _CELL_BORDER
        ws.cell(row_idx, 3, val).font  = _DATA_FONT
        ws.cell(row_idx, 3).fill       = row_fill
        ws.cell(row_idx, 3).alignment  = Alignment(horizontal="center")
        ws.cell(row_idx, 3).border     = _CELL_BORDER
        if isinstance(val, float):
            ws.cell(row_idx, 3).number_format = "0.0"

    # ── Chart sheet ───────────────────────────────────────────────────────────
    wc    = wb.create_sheet(chart_title)
    chart = LineChart()
    chart.title        = f"{label} ({date_from} – {date_to})"
    chart.style        = 10
    chart.y_axis.title = unit or "Value"
    chart.x_axis.title = "Measurement"
    chart.width        = 30
    chart.height       = 18

    n = len(series)
    if n > 0:
        data_ref = Reference(ws, min_col=3, min_row=1, max_row=n + 1)
        chart.add_data(data_ref, titles_from_data=True)
        chart.series[0].graphicalProperties.line.solidFill = color
        chart.series[0].graphicalProperties.line.width     = 15000  # 1.5pt EMU

    wc.add_chart(chart, "A1")


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

# ── Group colors for Overview mode ────────────────────────────────────────────
_GROUP_COLORS = {
    "sleep":     "DDEEFF",
    "heartrate": "FFE8CC",
    "stress":    "E8FFE8",
    "day":       "FFF8CC",
    "training":  "F0E8FF",
}


def _write_overview_sheet(wb: Workbook, data: dict) -> None:
    """Write broad daily overview table — one row per day, one col per field."""
    columns   = data.get("columns", [])
    rows      = data.get("rows", [])
    title     = data.get("title", "Overview")

    ws = wb.create_sheet(title[:31])  # sheet name max 31 chars
    ws.freeze_panes = "B2"

    # Header — Date + one col per field
    ws.cell(1, 1, "Date").font      = _HEADER_FONT
    ws.cell(1, 1).fill              = _HEADER_FILL
    ws.cell(1, 1).alignment         = Alignment(horizontal="center")
    ws.cell(1, 1).border            = _CELL_BORDER
    ws.column_dimensions["A"].width = 12

    for col_idx, col in enumerate(columns, start=2):
        cell = ws.cell(1, col_idx, col["label"])
        cell.font      = _HEADER_FONT
        cell.fill      = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        cell.border    = _CELL_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = max(10, min(len(col["label"]) + 2, 20))

    ws.row_dimensions[1].height = 36

    for row_idx, row in enumerate(rows, start=2):
        date_cell = ws.cell(row_idx, 1, row["date"])
        date_cell.font      = _DATE_FONT
        date_cell.alignment = Alignment(horizontal="center")
        date_cell.border    = _CELL_BORDER

        for col_idx, col in enumerate(columns, start=2):
            val   = row["values"].get(col["field"])
            color = _GROUP_COLORS.get(col.get("group", ""), "FFFFFF")
            cell  = ws.cell(row_idx, col_idx, val)
            cell.font      = _DATA_FONT
            cell.fill      = PatternFill("solid", start_color=color)
            cell.alignment = Alignment(horizontal="center")
            cell.border    = _CELL_BORDER
            if isinstance(val, float):
                cell.number_format = "0.00"
            elif isinstance(val, int):
                cell.number_format = "#,##0"


def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to Excel file.

    Detects output mode from dict structure:
    - "rows" present          → Overview: broad flat table
    - "fields" with "series"  → Timeseries: per-field data + chart sheets
    - "fields" with "days"    → Analysis: per-field data + chart sheets

    Args:
        data:        Dict from specialist.build().
        output_path: Full path for the output .xlsx file.
        settings:    Settings dict from GUI (reserved for future use).

    Raises:
        ValueError: if no usable data is present.
        OSError:    if output file cannot be written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)

    # ── Overview mode ─────────────────────────────────────────────────────────
    if "rows" in data:
        if not data.get("rows"):
            raise ValueError("render: no rows in data — nothing to render")
        _write_overview_sheet(wb, data)
        wb.save(output_path)
        return

    # ── Field mode (Timeseries or Analysis) ───────────────────────────────────
    fields = [f for f in data.get("fields", []) if f.get("series") or f.get("days")]
    if not fields:
        raise ValueError("render: no fields with data — nothing to render")

    date_from = data.get("date_from", "")
    date_to   = data.get("date_to", "")

    for entry in fields:
        # Normalise Analysis days → series-like list for _write_field_sheets
        if "days" in entry and "series" not in entry:
            entry = {
                **entry,
                "series": [
                    {"ts": d["date"], "value": d["value"]}
                    for d in entry["days"]
                    if d["value"] is not None
                ],
            }
        _write_field_sheets(wb, entry, date_from, date_to)

    wb.save(output_path)