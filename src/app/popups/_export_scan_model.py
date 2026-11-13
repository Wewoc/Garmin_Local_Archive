#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/_export_scan_model.py
Garmin Local Archive — what the Export Scan window shows

EXPORT-SCAN v1.7.7 — REMOVABLE (removal list: see garmin_export_scan.py).

Built from a result of garmin_export_scan.scan(): the tree of the export, the table of one item of the
tree and the chart of one item. Pure functions: no PyQt, no file access, no project imports except the pure data of its own units table
(_export_scan_units.py: the unit of a field, only where there is evidence) — the window
(export_scan.py) only draws what these return, so everything here is tested without a window.

Items of the tree ("nodes") are tuples (kind, key):
  ("summary", "")            the overview (file counts)
  ("group", "<group key>")   a group of families: the families with their files and rows
  ("family", "<key>")        one family: field by year
  ("unknown", "")            JSON files of no known family (folders)
  ("folders", "")            the folders at the top of the export
  ("fit", "")                the FIT files: type by year (only if the scan read FIT files: result["fit"])
  ("fit_type", "<type>")     one FIT type by year ("none": files without a readable type)

Years: a table or chart shows every year from the first to the last of its data (a year without any row is
a column of its own, 0 rows, and a gap in the heat map, not a 0 %), then "unknown". The scan result itself
holds only the years that have rows.

Table of an item: {"title", "note", "headers": [str], "rows": [[cell]]} with cell =
{"text": str, "tip": str | None, "value": int | None}. A cell with a value (0..100) is coloured by it.
In a family table the value is the share of rows that have a value: filled or 0 (a zero is a value);
the tooltip names the four states: filled / zero / empty / absent.

Chart of an item: a complete HTML page (family: heat map of that share, field by year; group: bars of
the rows per year and family; FIT files: bars of the files per year, stacked by type; one FIT type:
bars per year), or None if the item has no chart. The page carries Plotly inline, a
Content-Security-Policy that allows no network and nothing but the inline script, and every text of
the export (field paths, labels) is made safe twice: HTML special characters become entities (Plotly
shows a few HTML tags in labels, among them links) and the whole data is embedded as JSON with "<", ">"
and "&" escaped (a key such as "</script>" cannot end the script).

Public API:
  build_tree(result) -> [node dict]         {"id", "text", "status", "children": [...]}
  build_table(result, node) -> dict
  has_chart(result, node) -> bool
  build_chart_html(result, node, plotly_script, theme) -> str | None
        theme: {"bg", "bg2", "bg3", "text", "text2", "accent", "accent2", "green", "yellow", "red"} as
        "#rrggbb" from theme.py (the active theme); a value that is not such a colour is replaced by a
        neutral grey. Every colour of the page comes from it: background, text, grid, hover, tool bar,
        heat map scale and the series of the bars (series_colors).
  series_colors(theme, count) -> [str]      the colours of the series, derived from the theme
  build_field_table(detail, gran) -> dict   the detail of one field (garmin_export_scan.scan_field) by
  build_field_chart_html(detail, gran, plotly_script, theme) -> str | None   "month" or "year", no gaps
  has_field_chart(detail) -> bool
  has_values(values) -> bool                the values of one field (garmin_export_scan.read_values) or the heart
  build_values_table(values) -> dict          rate of one day (garmin_export_scan_day.read_day, a dict with a
                                              "state"): the only part that shows values; the page has none
  build_values_page(plotly_script, theme) -> str   (Plotly and an empty chart), the values reach it by
  build_values_js(values, mode, theme) -> str | None   glaRender(...), run in the web view; modes VALUES_MODES
  VALUES_HINT                               the hint of the view: a screenshot contains the values
  STATUS_TEXT, FIT_TYPE_NAMES, NODE_SUMMARY, NODE_UNKNOWN, NODE_FOLDERS, NODE_FIT
"""

import colorsys
import json
import re

from . import _export_scan_units as units

NODE_SUMMARY = ("summary", "")
NODE_UNKNOWN = ("unknown", "")
NODE_FOLDERS = ("folders", "")
NODE_FIT = ("fit", "")

UNKNOWN_YEAR = "unknown"

# Working names of FIT file types, as REFERENCE_GARMIN_EXPORT.md (section 5) gives them: found from the
# content of the files, not Garmin terms. A type that is not listed shows its number only.
FIT_TYPE_NAMES = {"4": "activity", "32": "all-day monitoring", "44": "metrics", "49": "sleep",
                  "58": "1-minute records", "68": "HRV"}

# The same wording as garmin_export_scan._STATUS_TEXT (a test compares both).
STATUS_TEXT = {
    "read": "read by GLA",
    "kept": "kept by GLA, not read",
    "known": "known, not read by GLA",
}

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# The colours come from the active theme (theme.py, handed in by the window). Only a value that is no
# "#rrggbb" colour is replaced, by neutral greys that belong to no theme.
_DEFAULT_THEME = {"bg": "#202020", "bg2": "#2a2a2a", "bg3": "#3a3a3a", "text": "#e0e0e0", "text2": "#b0b0b0",
                  "accent": "#a0a0a0", "accent2": "#888888", "green": "#909090", "yellow": "#989898",
                  "red": "#808080"}

# The colours of the series of a chart, in this order: named colours of the theme first, then colours
# turned out of the accent colour (series_colors).
_SERIES_BASE = ("accent", "green", "yellow", "red", "accent2", "text2")
_GOLDEN_ANGLE = 0.61803398875
_TRANSPARENT = "rgba(0,0,0,0)"

_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data:; font-src data:")


# ══════════════════════════════════════════════════════════════════════════════
#  Small helpers
# ══════════════════════════════════════════════════════════════════════════════

def _pct(part: int, total: int) -> int:
    return round(100 * part / total) if total else 0


def _cell(text, tip=None, value=None) -> dict:
    return {"text": str(text), "tip": tip, "value": value}


def _year_range(years) -> list:
    """The years of some data without gaps: every year from the first to the last (a year without data
    is a column of its own, with 0 rows), then "unknown" if it is there."""
    years = set(years)
    numbers = sorted(int(y) for y in years if y != UNKNOWN_YEAR and y.isdigit())
    full = [str(n) for n in range(numbers[0], numbers[-1] + 1)] if numbers else []
    return full + ([UNKNOWN_YEAR] if UNKNOWN_YEAR in years else [])


def _years_of(families) -> list:
    years = set()
    for fam in families:
        years.update(fam["years"])
    return _year_range(years)


def _states_tip(counts: dict, rows: int) -> str:
    return (f"filled {counts['filled']}, zero {counts['zero']}, empty {counts['empty']}, "
            f"absent {counts['absent']} of {rows} rows")


def _group_of(result: dict, key: str):
    for group in result["groups"]:
        if group["key"] == key:
            return group
    return None


def _fit_type_label(key: str) -> str:
    """"Type 32 · all-day monitoring", "Type 41", "No type" (the key "none")."""
    if key == "none":
        return "No type"
    name = FIT_TYPE_NAMES.get(key)
    return f"Type {key} · {name}" if name else f"Type {key}"


def _fit_years(fit: dict) -> list:
    years = set()
    for entry in fit["types"].values():
        years.update(entry["years"])
    return _year_range(years)


def _fit_note(fit: dict) -> str:
    files = fit["files"]
    parts = [f"{files['read']} different files read ({files['seen']} seen, {files['duplicates']} again with the "
             f"same content, {sum(files['damaged'].values())} damaged)."]
    if fit["stopped"]:
        parts.append("The FIT scan was stopped before the end: the numbers are incomplete.")
    parts.append("The year is that of the creation time in the file; a file without a date counts for "
                 "\"unknown\". Type names are working names of the export reference, not Garmin terms.")
    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
#  Tree
# ══════════════════════════════════════════════════════════════════════════════

def build_tree(result: dict) -> list:
    """The tree: overview, one node per group that has families in this export (each with its
    families), the not recognised files and the top folders."""
    nodes = [{"id": NODE_SUMMARY, "text": "Overview", "status": None, "children": []}]
    families = result["families"]
    for group in result["groups"]:
        children = []
        for key in group["families"]:
            fam = families[key]
            if fam["files"]:
                children.append({"id": ("family", key), "text": f"{fam['label']}  ({fam['rows']} rows)",
                                 "status": fam["status"], "children": []})
        if children:
            nodes.append({"id": ("group", group["key"]), "text": group["label"], "status": None,
                          "children": children})
    fit = result.get("fit")
    if fit and fit["types"]:
        nodes.append({"id": NODE_FIT, "text": f"FIT files ({fit['files']['read']} files)", "status": None,
                      "children": [{"id": ("fit_type", key), "status": None, "children": [],
                                    "text": f"{_fit_type_label(key)}  ({entry['files']} files)"}
                                   for key, entry in fit["types"].items()]})
    nodes.append({"id": NODE_UNKNOWN, "text": f"Not recognised ({result['unknown']['files']} files)",
                  "status": None, "children": []})
    nodes.append({"id": NODE_FOLDERS, "text": "Folders", "status": None, "children": []})
    return nodes


# ══════════════════════════════════════════════════════════════════════════════
#  Tables
# ══════════════════════════════════════════════════════════════════════════════

def _empty_table(title: str, note: str = "") -> dict:
    return {"title": title, "note": note, "headers": [], "rows": []}


def _fit_rows(result: dict) -> list:
    """The FIT lines of the overview: what the FIT scan read, or (no FIT scan) what the JSON scan only counted."""
    fit = result.get("fit")
    if not fit:
        return [("Nested ZIPs (not opened)", result["files"]["nested_zips"]),
                ("FIT files in the outer level (not read)", result["files"]["fit"])]
    files = fit["files"]
    return [("FIT files seen", files["seen"]),
            ("  different files read", files["read"]),
            ("  again with the same content", files["duplicates"]),
            ("  damaged", sum(files["damaged"].values())),
            ("  not read (too large or unreadable)",
             files["oversize"] + files["unreadable_entries"] + files["zips_unreadable"])]


def _summary_table(result: dict) -> dict:
    files = result["files"]
    rows = [
        ("Source", result["source"]),
        ("JSON files", files["json_total"]),
        ("  read", files["json_read"]),
        ("  unreadable", files["unreadable"]),
        ("  too large", files["too_large"]),
        ("  of no known family", files["unknown_json"]),
        *_fit_rows(result),
        ("Other files", files["other"]),
    ]
    note = ("The scan was stopped before the end: the numbers are incomplete." if result["stopped"]
            else "Names and counts only: no values and no file names are shown or saved.")
    return {"title": "Overview", "note": note, "headers": ["Item", "Count"],
            "rows": [[_cell(name), _cell(count)] for name, count in rows]}


def _group_table(result: dict, key: str) -> dict:
    group = _group_of(result, key)
    if group is None:
        return _empty_table("Unknown item")
    families = [result["families"][k] for k in group["families"]]
    years = _years_of(families)
    rows = []
    for fam in families:
        row = [_cell(fam["label"]), _cell(STATUS_TEXT[fam["status"]]), _cell(fam["files"]), _cell(fam["rows"])]
        row += [_cell(fam["years"].get(year, "")) for year in years]
        rows.append(row)
    return {"title": group["label"],
            "note": "Rows per year. A family with 0 files is not in this export.",
            "headers": ["Family", "Status", "Files", "Rows"] + years, "rows": rows}


def _family_table(result: dict, key: str) -> dict:
    fam = result["families"].get(key)
    if fam is None:
        return _empty_table("Unknown item")
    title = f"{fam['label']}  ({STATUS_TEXT[fam['status']]})"
    parts = [f"{fam['files']} files, {fam['rows']} rows.",
             "Cells show the share of rows that have a value (filled or 0). Hover a cell for "
             "filled / zero / empty / absent."]
    if fam["unreadable"] or fam["too_large"] or fam["skipped_rows"]:
        parts.append(f"Unreadable files: {fam['unreadable']}, too large: {fam['too_large']}, "
                     f"rows that are not objects: {fam['skipped_rows']}.")
    if fam["truncated"]:
        parts.append("The list of fields was cut at the limit of fields per family.")
    note = " ".join(parts)
    years = _year_range(fam["years"])
    if not years:
        return {"title": title, "note": note, "headers": [], "rows": []}
    rows = [[_cell("Rows")] + [_cell(fam["years"].get(y, 0)) for y in years] + [_cell(fam["rows"])]]
    for path, per_year in fam["fields"].items():
        row = [_cell(path)]
        totals = {"filled": 0, "zero": 0, "empty": 0, "absent": 0}
        for year in years:
            n = fam["years"].get(year, 0)
            if n == 0:                                   # a year without any row: no share to show
                row.append(_cell("–", f"{path}, {year}: no rows in this year"))
                continue
            counts = per_year[year]
            value = _pct(counts["filled"] + counts["zero"], n)
            row.append(_cell(f"{value} %", f"{path}, {year}: {_states_tip(counts, n)}", value))
            for name in totals:
                totals[name] += counts[name]
        value = _pct(totals["filled"] + totals["zero"], fam["rows"])
        row.append(_cell(f"{value} %", f"{path}, all years: {_states_tip(totals, fam['rows'])}", value))
        rows.append(row)
    return {"title": title, "note": note, "headers": ["Field"] + years + ["All years"], "rows": rows}


def _unknown_table(result: dict) -> dict:
    unknown = result["unknown"]
    note = f"{unknown['files']} JSON files of no known family. Only their folders are named, never a file."
    if unknown["folders_truncated"]:
        note += " The list of folders was cut."
    return {"title": "Not recognised", "note": note, "headers": ["Folder"],
            "rows": [[_cell(folder)] for folder in unknown["folders"]]}


def _folders_table(result: dict) -> dict:
    return {"title": "Folders at the top of the export",
            "note": "All files of the export by their top folder (a folder named after the account is "
                    "shown as <hidden>).",
            "headers": ["Folder", "Files"],
            "rows": [[_cell(entry["folder"]), _cell(entry["files"])] for entry in result["folders"]]}


def _fit_table(result: dict) -> dict:
    fit = result.get("fit")
    if not fit:
        return _summary_table(result)
    years = _fit_years(fit)
    rows = [[_cell(_fit_type_label(key)), _cell(entry["files"])] + [_cell(entry["years"].get(y, "")) for y in years]
            for key, entry in fit["types"].items()]
    rows.append([_cell("All types"), _cell(fit["files"]["read"])] + [_cell(fit["years"].get(y, "")) for y in years])
    return {"title": "FIT files", "note": _fit_note(fit), "headers": ["Type", "Files"] + years, "rows": rows}


def _fit_type_table(result: dict, key: str) -> dict:
    fit = result.get("fit")
    entry = fit["types"].get(key) if fit else None
    if entry is None:
        return _empty_table("Unknown item")
    return {"title": _fit_type_label(key), "note": _fit_note(fit), "headers": ["Year", "Files"],
            "rows": [[_cell(year), _cell(entry["years"].get(year, 0))] for year in _year_range(entry["years"])]}


def build_table(result: dict, node) -> dict:
    """The table of a node of the tree (see the module docstring); the overview for any other node."""
    kind, key = node
    if kind == "fit":
        return _fit_table(result)
    if kind == "fit_type":
        return _fit_type_table(result, key)
    if kind == "family":
        return _family_table(result, key)
    if kind == "group":
        return _group_table(result, key)
    if kind == "unknown":
        return _unknown_table(result)
    if kind == "folders":
        return _folders_table(result)
    return _summary_table(result)


# ══════════════════════════════════════════════════════════════════════════════
#  Charts
# ══════════════════════════════════════════════════════════════════════════════

def has_chart(result: dict, node) -> bool:
    kind, key = node
    if kind == "fit":
        fit = result.get("fit")
        return bool(fit and fit["types"])
    if kind == "fit_type":
        fit = result.get("fit")
        return bool(fit and key in fit["types"])
    if kind == "family":
        fam = result["families"].get(key)
        return bool(fam and fam["fields"] and fam["years"])
    if kind == "group":
        group = _group_of(result, key)
        return bool(group and any(result["families"][k]["rows"] for k in group["families"]))
    return False


def _plot_text(text) -> str:
    """A text of the export as Plotly shows it: HTML special characters as entities, so that no tag
    (Plotly renders <a>, <b>, <br> ... in labels) can come out of the data."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_json(obj) -> str:
    """JSON that can sit inside a <script>: "<", ">" and "&" escaped (ensure_ascii covers U+2028/2029)."""
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _colors(theme) -> dict:
    theme = theme or {}
    return {name: (theme.get(name) if isinstance(theme.get(name), str) and _COLOR.match(theme.get(name))
                   else default) for name, default in _DEFAULT_THEME.items()}


def _rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hex(rgb: tuple) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in rgb)


def series_colors(theme, count: int) -> list:
    """
    `count` colours for the series of a chart, all derived from the theme (theme.py): first its named
    colours (accent, green, yellow, red, accent2, text2), then more of the hue of the accent colour,
    turned by the golden angle each (the saturation and the lightness are kept in a range that shows
    on a dark background). A theme with other colours gives other series colours; nothing is fixed here.
    """
    colors = _colors(theme)
    out = [colors[name] for name in _SERIES_BASE][:count]
    hue, light, sat = colorsys.rgb_to_hls(*_rgb(colors["accent"]))
    light, sat = min(max(light, 0.45), 0.65), max(sat, 0.45)
    step = 1
    while len(out) < count:
        out.append(_hex(colorsys.hls_to_rgb((hue + _GOLDEN_ANGLE * step) % 1.0, light, sat)))
        step += 1
    return out


def _axis(colors: dict, title=None, **extra) -> dict:
    axis = {"gridcolor": colors["bg3"], "zerolinecolor": colors["bg3"], "linecolor": colors["bg3"],
            "tickfont": {"color": colors["text"]}}
    if title:
        axis["title"] = {"text": _plot_text(title), "font": {"color": colors["text"]}}
    axis.update(extra)
    return axis


def _layout(colors: dict, title: str, height: int) -> dict:
    return {"title": {"text": _plot_text(title)}, "height": height,
            "paper_bgcolor": colors["bg"], "plot_bgcolor": colors["bg"],
            "font": {"color": colors["text"]}, "margin": {"l": 80, "r": 30, "t": 70, "b": 50},
            "legend": {"font": {"color": colors["text"]}, "bgcolor": _TRANSPARENT},
            "hoverlabel": {"bgcolor": colors["bg2"], "bordercolor": colors["accent"], "font": {"color": colors["text"]}},
            "modebar": {"bgcolor": _TRANSPARENT, "color": colors["text2"], "activecolor": colors["accent"]}}


def _heatmap(fam: dict, colors: dict):
    years = _year_range(fam["years"])
    paths = list(fam["fields"])
    z, text = [], []
    for path in paths:
        z_row, text_row = [], []
        for year in years:
            n = fam["years"].get(year, 0)
            if n == 0:                                   # a year without any row: a gap, not a 0 %
                z_row.append(None)
                text_row.append(_plot_text(path) + "<br>" + _plot_text(f"{year}: no rows in this year"))
                continue
            counts = fam["fields"][path][year]
            z_row.append(_pct(counts["filled"] + counts["zero"], n))
            text_row.append(_plot_text(path) + "<br>" + _plot_text(f"{year}: {_states_tip(counts, n)}"))
        z.append(z_row)
        text.append(text_row)
    data = [{"type": "heatmap", "x": [_plot_text(y) for y in years], "y": [_plot_text(p) for p in paths],
             "z": z, "text": text, "hoverinfo": "text", "zmin": 0, "zmax": 100, "xgap": 1, "ygap": 1,
             "colorscale": [[0, colors["bg3"]], [1, colors["accent"]]],
             "colorbar": {"title": {"text": "% with a value", "font": {"color": colors["text"]}},
                          "tickfont": {"color": colors["text2"]}, "outlinecolor": colors["bg3"]}}]
    layout = _layout(colors, f"{fam['label']}: share of rows with a value", max(320, 20 * len(paths) + 150))
    layout["xaxis"] = _axis(colors, type="category", side="top")
    layout["yaxis"] = _axis(colors, type="category", autorange="reversed", automargin=True)
    return data, layout


def _bar_traces(names: list, years: list, columns: list, colors: dict) -> list:
    """One bar trace per name, in the series colours of the theme; columns[i] = the counts per year."""
    palette = series_colors(colors, len(names))
    return [{"type": "bar", "name": _plot_text(name), "x": [_plot_text(y) for y in years], "y": column,
             "marker": {"color": color}} for name, column, color in zip(names, columns, palette)]


def _bars(result: dict, key: str, colors: dict):
    group = _group_of(result, key)
    families = [result["families"][k] for k in group["families"] if result["families"][k]["rows"]]
    years = _years_of(families)
    data = _bar_traces([fam["label"] for fam in families], years,
                       [[fam["years"].get(year, 0) for year in years] for fam in families], colors)
    layout = _layout(colors, f"{group['label']}: rows per year", 420)
    layout["barmode"] = "group"
    layout["xaxis"] = _axis(colors, type="category")
    layout["yaxis"] = _axis(colors, title="Rows")
    return data, layout


def _fit_bars(fit: dict, key, colors: dict):
    """Bars of the FIT files per year: all types stacked (key None) or one type."""
    if key is None:
        years = _year_range(fit["years"])
        types = list(fit["types"].items())
        data = _bar_traces([_fit_type_label(k) for k, _entry in types], years,
                           [[entry["years"].get(year, 0) for year in years] for _k, entry in types], colors)
        layout = _layout(colors, "FIT files per year and type", 420)
        layout["barmode"] = "stack"
    else:
        entry = fit["types"][key]
        years = _year_range(entry["years"])
        data = _bar_traces([_fit_type_label(key)], years, [[entry["years"].get(year, 0) for year in years]], colors)
        layout = _layout(colors, f"{_fit_type_label(key)}: files per year", 420)
        layout["barmode"] = "group"
    layout["xaxis"] = _axis(colors, type="category")
    layout["yaxis"] = _axis(colors, title="Files")
    return data, layout


def _page(colors: dict, plotly_script: str, data: list, layout: dict, hook: bool = False) -> str:
    """The complete chart page: the Content-Security-Policy, Plotly inline, the data as script-safe JSON.
    hook: also define glaRender(data, layout), by which the window hands new data to the loaded page."""
    config = {"responsive": True, "displaylogo": False, "scrollZoom": True}
    render = (f"<script>var GLA_CONFIG = {_safe_json(config)};"
              "function glaRender(data, layout) { Plotly.react(\"chart\", data, layout, GLA_CONFIG); }</script>"
              if hook else "")
    return ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{_CSP}\">"
            f"<style>html,body{{margin:0;background:{colors['bg']};}}</style></head><body>"
            "<div id=\"chart\" style=\"width:100%;\"></div>"
            f"{plotly_script}"
            f"<script>Plotly.newPlot(\"chart\", {_safe_json(data)}, {_safe_json(layout)}, {_safe_json(config)});</script>"
            f"{render}</body></html>")


# ══════════════════════════════════════════════════════════════════════════════
#  The values of one field (garmin_export_scan.read_values): a table and two charts
#
#  The only part that shows VALUES of the export. The chart page of the values view is built WITHOUT any
#  value (build_values_page: Plotly and an empty chart); the values reach the loaded page as a call of
#  glaRender (build_values_js), which the window runs in the web view, so they are never in a file.
# ══════════════════════════════════════════════════════════════════════════════

VALUES_HINT = "Values from your export are shown here. A screenshot of this view contains them."
VALUES_MODES = ("series", "histogram")


def has_values(values) -> bool:
    return bool(values and values["supported"] and values["stats"])


def _num(value) -> str:
    """A number as text: an integer as it is, a float with 6 significant digits."""
    return str(value) if isinstance(value, int) else f"{value:.6g}"


_DAY_STATE_TEXT = {
    "unplanned": "The boundaries of this day are not known (the wellness windows around it are missing or disagree), "
                 "so no samples are placed on it. Nothing is guessed.",
    "no_files": "No monitoring file was created near this day.",
    "no_samples": "The monitoring files near this day hold no heart-rate sample for it.",
    "stopped": "The read was stopped before the end: no samples are shown.",
}


def is_day(values: dict) -> bool:
    """True for the heart rate of one day (garmin_export_scan_day.read_day), False for a field (read_values)."""
    return "state" in values


def _values_name(values: dict) -> str:
    """What the values are of, for the titles: the label of the family, with the date for a day."""
    return f"{values['label']} {values['day']}" if is_day(values) else values["label"]


def _clock(day: str, local: str) -> str:
    """The time of day of a local date-time text; with its date if it is not on the day itself."""
    return local[11:] if local[:10] == day else local


def _day_table(values: dict) -> dict:
    """The table of the heart rate of one day: one row per sample (local time, value), the statistics in the note."""
    title = f"Heart rate of {values['day']}  (values)"
    if values["state"] != "ok":
        return {"title": title, "headers": [], "rows": [], "note": _DAY_STATE_TEXT.get(values["state"], "")}
    s, day = values["stats"], values["day"]
    found = units.unit_of(values["family"], values["field"])
    unit_note = (f"Unit: {found['unit']} ({found['source']}). Raw values, not converted." if found
                 else f"Unit: {units.NOT_DOCUMENTED}.")
    parts = [f"{s['count']} samples, min {_num(s['min'])}, max {_num(s['max'])}, mean {_num(s['mean'])}, "
             f"median {_num(s['median'])}, from {_clock(day, values['points'][0][0])} to "
             f"{_clock(day, values['points'][-1][0])}.",
             f"The samples come from {values['sources']} FIT files.", unit_note,
             f"The time of day is local: UTC{values['offset_hours']:+g} h, the offset at the start of the day."]
    if values["dst_transition"]:
        parts.append("This day crosses a clock change; its times use the offset of the start of the day.")
    if values["duplicates_same"] or values["duplicates_conflict"]:
        parts.append(f"Seconds that more than one file holds: {values['duplicates_same'] + values['duplicates_conflict']} "
                     f"({values['duplicates_conflict']} with a different value); the file created first wins.")
    if values["damaged"]:
        parts.append(f"Damaged files skipped: {values['damaged']}.")
    return {"title": title, "note": " ".join(parts), "headers": ["Time (local)", units.with_unit("Heart rate", found)],
            "rows": [[_cell(_clock(day, local)), _cell(_num(bpm))] for local, bpm in values["points"]]}


def build_values_table(values: dict) -> dict:
    """The table of the values of a field: one row per point (date, value), the statistics in the note.
    The heart rate of one day (garmin_export_scan_day.read_day) has its own table."""
    if is_day(values):
        return _day_table(values)
    title = f"{values['label']} › {values['field']}  (values)"
    if not values["supported"]:
        return {"title": title, "headers": [], "rows": [],
                "note": "This field cannot be shown as values: its path has a list or a key that is masked (an id)."}
    counts = (f"{values['numeric']} of {values['rows']} rows hold a number; not a number: {values['other']}, "
              f"empty or absent: {values['missing']}.")
    if not values["stats"]:
        return {"title": title, "headers": [], "rows": [], "note": f"No number with a date in this field. {counts}"}
    s = values["stats"]
    found = units.unit_of(values["family"], values["field"])
    unit_note = (f"Unit: {found['unit']} ({found['source']}). Raw values, not converted." if found
                 else f"Unit: {units.NOT_DOCUMENTED}.")
    parts = [f"{s['count']} values, min {_num(s['min'])}, max {_num(s['max'])}, mean {_num(s['mean'])}, "
             f"median {_num(s['median'])}, {s['zeros']} zeros, {values['points'][0][0]} to {values['points'][-1][0]}.",
             counts, unit_note]
    if values["undated"]:
        parts.append(f"{values['undated']} numbers without a readable date are not shown.")
    if values["thinned"]:
        parts.append(f"Thinned to {len(values['points'])} points for the view; the statistics use all values.")
    if values["stopped"]:
        parts.append("The read was stopped before the end: the numbers are incomplete.")
    if values["unreadable"] or values["too_large"]:
        parts.append(f"Unreadable files: {values['unreadable']}, too large: {values['too_large']}.")
    return {"title": title, "note": " ".join(parts), "headers": ["Date", units.with_unit("Value", found)],
            "rows": [[_cell(day), _cell(_num(number))] for day, number in values["points"]]}


def build_values_page(plotly_script: str, theme=None) -> str:
    """The chart page of the values view: Plotly and an empty chart, NO value in it. The values come with
    build_values_js, by glaRender, into the loaded page."""
    colors = _colors(theme)
    return _page(colors, plotly_script, [], _layout(colors, "", 420), hook=True)


def _values_series(values: dict, colors: dict):
    xs = [day for day, _number in values["points"]]
    ys = [number for _day, number in values["points"]]
    data = [{"type": "scatter", "mode": "lines+markers", "x": xs, "y": ys, "line": {"color": colors["accent"], "width": 1},
             "marker": {"size": 4, "color": colors["accent"]}, "hovertemplate": "%{x}: %{y}<extra></extra>"}]
    layout = _layout(colors, f"{_values_name(values)} › {values['field']}: values over time", 420)
    layout["xaxis"] = _axis(colors, type="date")
    layout["yaxis"] = _axis(colors, title=units.with_unit(values["field"], units.unit_of(values["family"], values["field"])))
    return data, layout


def _values_histogram(values: dict, colors: dict):
    edges, counts = values["histogram"]["edges"], values["histogram"]["counts"]
    if len(counts) == 1 and edges[0] == edges[1]:            # all values are equal: one bar around the value
        centers, widths = [edges[0]], [1]
    else:
        centers = [(edges[i] + edges[i + 1]) / 2 for i in range(len(counts))]
        widths = [edges[i + 1] - edges[i] for i in range(len(counts))]
    data = [{"type": "bar", "x": centers, "y": counts, "width": widths, "marker": {"color": colors["accent"]},
             "hovertemplate": "%{x}: %{y}<extra></extra>"}]
    layout = _layout(colors, f"{_values_name(values)} › {values['field']}: distribution of the values", 420)
    layout["xaxis"] = _axis(colors, title=units.with_unit(values["field"], units.unit_of(values["family"], values["field"])))
    layout["yaxis"] = _axis(colors, title="Number of values")
    return data, layout


def build_values_js(values: dict, mode: str, theme=None):
    """The call that hands the values to the loaded values page: glaRender(data, layout); None if there are
    no values to draw. mode: "series" (over time) or "histogram" (distribution). Everything of the export in
    it (the field name, the numbers) is made safe like on the other chart pages."""
    if not has_values(values):
        return None
    colors = _colors(theme)
    mode = mode if mode in VALUES_MODES else VALUES_MODES[0]            # an unknown mode shows the series
    data, layout = _values_histogram(values, colors) if mode == "histogram" else _values_series(values, colors)
    return f"glaRender({_safe_json(data)}, {_safe_json(layout)});"


# ══════════════════════════════════════════════════════════════════════════════
#  The detail of one field (garmin_export_scan.scan_field): the four states by year or by month
# ══════════════════════════════════════════════════════════════════════════════

# The states of a field in a row, in this order, and the theme colour of each in the chart.
STATE_ORDER = ("filled", "zero", "empty", "absent")
_STATE_COLOR = {"filled": "green", "zero": "accent", "empty": "yellow", "absent": "text2"}
_NO_ROWS = {"rows": 0, "filled": 0, "zero": 0, "empty": 0, "absent": 0}


def _month_range(months) -> list:
    """Every month ("YYYY-MM") from the first to the last of the data, a month without a row included,
    then "unknown" if it is there."""
    months = list(months)
    dated = sorted(m for m in months if m != UNKNOWN_YEAR)
    out = []
    if dated:
        year, month = (int(part) for part in dated[0].split("-"))
        last = tuple(int(part) for part in dated[-1].split("-"))
        while (year, month) <= last:
            out.append(f"{year}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out + ([UNKNOWN_YEAR] if UNKNOWN_YEAR in months else [])


def _field_periods(detail: dict, gran: str) -> list:
    """[(label, counts)] of a field detail by month (default) or by year, without gaps."""
    months = detail["months"]
    if gran == "year":
        counts = {}
        for key, c in months.items():
            total = counts.setdefault(key if key == UNKNOWN_YEAR else key[:4], dict(_NO_ROWS))
            for name in total:
                total[name] += c[name]
        labels = _year_range(counts)
    else:
        counts, labels = months, _month_range(months)
    return [(label, counts.get(label, _NO_ROWS)) for label in labels]


def has_field_chart(detail) -> bool:
    return bool(detail and detail["rows"])


def build_field_table(detail: dict, gran: str = "month") -> dict:
    """The table of a field detail: one row per month or year with the rows and the four states."""
    unit = "year" if gran == "year" else "month"
    parts = [f"{detail['rows']} rows in {detail['files']} files, by state per {unit}: filled, zero (a 0 is a value), "
             "empty (null, \"\", [] or {}) or absent (the key is not in the row)."]
    parts.append(f"First month with a value: {detail['first']}, last: {detail['last']}." if detail["first"]
                 else "No row has a value.")
    if detail["stopped"]:
        parts.append("The read was stopped before the end: the numbers are incomplete.")
    if detail["unreadable"] or detail["too_large"]:
        parts.append(f"Unreadable files: {detail['unreadable']}, too large: {detail['too_large']}.")
    rows = []
    total = dict(_NO_ROWS)
    for label, c in _field_periods(detail, gran):
        n = c["rows"]
        value = _pct(c["filled"] + c["zero"], n) if n else None
        share = _cell(f"{value} %", f"{label}: {_states_tip(c, n)}", value) if n else _cell("–", f"{label}: no rows")
        rows.append([_cell(label), _cell(n)] + [_cell(c[name]) for name in STATE_ORDER] + [share])
        for name in total:
            total[name] += c[name]
    value = _pct(total["filled"] + total["zero"], total["rows"])
    rows.append([_cell("All"), _cell(total["rows"])] + [_cell(total[name]) for name in STATE_ORDER]
                + [_cell(f"{value} %", f"all: {_states_tip(total, total['rows'])}", value)])
    return {"title": f"{detail['label']} › {detail['field']}", "note": " ".join(parts),
            "headers": [unit.capitalize(), "Rows", "Filled", "Zero", "Empty", "Absent", "With a value"], "rows": rows}


def build_field_chart_html(detail: dict, gran: str, plotly_script: str, theme=None):
    """The chart page of a field detail (bars of the rows by state, stacked, per month or year), or None
    if the field has no rows. The colours are those of the theme: filled green, zero accent, empty yellow,
    absent text2."""
    if not has_field_chart(detail):
        return None
    colors = _colors(theme)
    periods = _field_periods(detail, gran)
    x = [_plot_text(label) for label, _c in periods]
    data = [{"type": "bar", "name": name, "x": x, "y": [c[name] for _label, c in periods],
             "marker": {"color": colors[_STATE_COLOR[name]]}} for name in STATE_ORDER]
    unit = "year" if gran == "year" else "month"
    layout = _layout(colors, f"{detail['label']} › {detail['field']}: rows by state per {unit}", 420)
    layout["barmode"] = "stack"
    layout["xaxis"] = _axis(colors, type="category")
    layout["yaxis"] = _axis(colors, title="Rows")
    return _page(colors, plotly_script, data, layout)


def build_chart_html(result: dict, node, plotly_script: str, theme=None):
    """The chart page of a node, or None if the node has no chart. plotly_script is the <script> tag
    with Plotly (inline); theme: see the module docstring."""
    if not has_chart(result, node):
        return None
    colors = _colors(theme)
    kind, key = node
    if kind == "family":
        data, layout = _heatmap(result["families"][key], colors)
    elif kind == "group":
        data, layout = _bars(result, key, colors)
    else:
        data, layout = _fit_bars(result["fit"], key if kind == "fit_type" else None, colors)
    return _page(colors, plotly_script, data, layout)
