#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/export_scan.py
Garmin Local Archive — Export Scan window

EXPORT-SCAN v1.7.7 — REMOVABLE (removal list: see garmin_export_scan.py).

A non-modal window (like the documentation viewer) that shows what the user's own Garmin export holds:
  - top:    choose the export (ZIP file or unpacked folder), stop, progress
  - left:   the table of the chosen item, or a Plotly chart of it (switch "Table" / "Graph"). A double-click
            on a cell of a family table opens the detail of that field: its four states (filled / zero /
            empty / absent) by month or by year (switch "Month" / "Year"), read on demand with
            garmin_export_scan.scan_field; "Back" or another item of the tree leaves it. Only the table
            is clickable: the chart is a web page and has no way back to Python.
  - right:  the tree of the export, grouped by topic; the dot in front of a family is its status
            (app.GREEN: read by GLA, app.YELLOW: kept only, app.TEXT2: known but not read)
  - bottom: save the report (text and JSON, into garmin_data/log, replacing the last one), and "Help": the
            guide README_EXPORT_SCAN.md in the documentation viewer of the app

The scan (garmin_export_scan.scan) reads the export and writes nothing; after it the FIT files are
counted by type and year (garmin_export_scan_fit.scan_fit, about 30 s for 35,000 files on the
maintainer's export). Both run in a thread, the window is only touched through app._dispatch. What the window shows is built by _export_scan_model.py.
All colours are those of the app window (app.BG, app.ACCENT ... = theme.py, the active theme); the chart
gets them handed in, nothing is fixed here. Names and counts only: no value of the export and no file
name is shown, saved or logged; an error
shows a fixed sentence, never the text of an exception (it could hold a path).

The chart page can be larger than the 2 MB that QWebEngineView.setHtml takes (Plotly is inline), so
it is written to a temporary folder and loaded like the dashboards are; the folder is removed when
the window closes.

Usage
-----
    open_window(panel)          # the button of the Outputs panel: opens the window, or raises it
"""

import shutil
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QUrl
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

import frozen_paths
import qwebengine_hardening

from ..dialog_docs import DocViewerDialog
from . import _export_scan_model as model

_window = None          # the one open window (None: none)

# Status dot of a family -> the colour attribute of the app (theme.py, the active theme)
_STATUS_COLORS = {"read": "GREEN", "kept": "YELLOW", "known": "TEXT2"}

_MSG_START = "Choose the ZIP file of your Garmin export, or the folder it is unpacked in."
_MSG_NO_GRAPH = "This item has no graph."
_MSG_NO_PLOTLY = "The graph needs layouts/plotly.min.js, which was not found."
HELP_FILE = "README_EXPORT_SCAN.md"                # the guide of this window (src/docs/, info/ in a build)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _load_scanner():
    """The scan module (garmin/ is put on the path as the other popups do for their modules)."""
    frozen_paths.add_to_path(frozen_paths.scripts_root(), "garmin")
    import garmin_export_scan
    return garmin_export_scan


def _load_fit_scan():
    """The FIT side of the scan, garmin_export_scan_fit.scan_fit (it reads the FIT files with the modules of garmin/)."""
    frozen_paths.add_to_path(frozen_paths.scripts_root(), "garmin")
    import garmin_export_scan_fit
    return garmin_export_scan_fit.scan_fit


def _load_day_reader():
    """The heart rate of one day, garmin_export_scan_day (prepare() and read_day(); it uses the modules of the import)."""
    frozen_paths.add_to_path(frozen_paths.scripts_root(), "garmin")
    import garmin_export_scan_day
    return garmin_export_scan_day


def _plotly_script():
    """Plotly as an inline <script> tag from layouts/plotly.min.js (no network), None if it is not there."""
    try:
        root = frozen_paths.scripts_root()
        frozen_paths.add_to_path(root, "layouts")
        import dash_layout_html as layout_html
        return layout_html.get_plotly_script(root / "layouts")
    except Exception:
        return None


def _start_thread(fn):
    threading.Thread(target=fn, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  The window
# ══════════════════════════════════════════════════════════════════════════════

class ExportScanWindow(QDialog):
    """
    Parameters
    ----------
    app           : the app window (needs the colours BG, BG2, BG3, TEXT, TEXT2, ACCENT, ACCENT2, GREEN,
                    YELLOW, RED of theme.py, and _dispatch(fn, *args), _log(text), _panel_settings)
    scanner       : module with scan() and write_report() (default garmin_export_scan; tests hand in a fake)
    plotly_script : callable -> "<script>...</script>" | None (default: layouts/plotly.min.js)
    run_in_thread : callable(fn) that runs fn in the background (default: a daemon thread)
    report_dir    : callable -> Path | None, the folder of the report files (default: garmin_data/log)
    fit_scan      : callable(path, should_stop=, progress=, index=) -> dict | None, the FIT side that runs after
                    the JSON scan (default garmin_export_scan_fit.scan_fit; None as an answer: no FIT part);
                    index is a dict it may fill with the monitoring files (digest -> creation time)
    day_reader    : module with prepare(path, index, should_stop=) and read_day(path, prepared, day,
                    should_stop=) (default garmin_export_scan_day; tests hand in a fake)
    """

    def __init__(self, app, scanner=None, plotly_script=None, run_in_thread=None, report_dir=None, fit_scan=None,
                 day_reader=None):
        super().__init__(app)
        self._app = app
        self._scanner = scanner or _load_scanner()
        self._fit_scan = fit_scan or _load_fit_scan()
        self._day_reader = day_reader or _load_day_reader()
        self._plotly_fn = plotly_script or _plotly_script
        self._run = run_in_thread or _start_thread
        self._report_dir_fn = report_dir or self._default_report_dir
        self._result = None
        self._node = model.NODE_SUMMARY
        self._mode = "table"
        self._source_path = None            # what the last scan read: the detail of a field reads it again
        self._detail = None                 # the detail of one field (scan_field), None: the normal view
        self._gran = "month"                # the detail by "month" or "year"
        # The VALUES of the field of the detail (read_values). Kept ONLY here, in memory: never in
        # self._result, the report, the log, the status line or a file; dropped whenever the view is left.
        self._values = None                 # None: the counts view; a dict: the values view is shown
        self._vmode = "series"              # the values by "series" (over time) or "histogram" (distribution)
        self._pending_js = None             # the call that hands the values to the loaded page
        # The heart rate of ONE DAY (garmin_export_scan_day): what prepare() made after the FIT scan (the plan
        # of the days and the index of the monitoring files). Memory only, like the values; the samples of a
        # day are _values as well (a dict with a "state").
        self._days = None                   # None: no day view (no FIT scan yet, or nothing to show)
        self._web_kind = None              # which page the web view holds: "counts", "values" or None
        self._web_ready = False             # the values page is loaded and takes glaRender(...)
        self._stop = threading.Event()
        self._running = False
        self._alive = True
        self._plotly = None
        self._web = None
        self._tmpdir = None
        self._chart_n = 0

        self.setWindowTitle("Export Scan")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1120, 720)
        self.setStyleSheet(f"background: {app.BG}; color: {app.TEXT};")
        self._build_ui()
        self._show_message(_MSG_START)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _button(self, text, primary=False):
        app = self._app
        btn = QPushButton(text)
        btn.setFont(QFont("Segoe UI", 9))
        bg, fg = (app.ACCENT, app.TEXT) if primary else (app.BG3, app.TEXT2)
        btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {app.TEXT2}; background: {app.BG3}; }}"
            f"QPushButton:checked {{ background: {app.ACCENT}; color: {app.TEXT}; }}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _label(self, text="", bold=False, color=None, size=9):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
        lbl.setStyleSheet(f"color: {color or self._app.TEXT}; background: transparent;")
        lbl.setWordWrap(True)
        return lbl

    def _build_ui(self):
        app = self._app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(8)

        lay.addWidget(self._label("EXPORT SCAN", bold=True, color=app.ACCENT))
        lay.addWidget(self._label(
            "Looks into your own Garmin export and shows which data it holds and how complete it is. "
            "Reads only: nothing is written to the archive. Names and numbers only, no values.",
            color=app.TEXT2, size=8))

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._zip_btn = self._button("ZIP file ...", primary=True)
        self._zip_btn.clicked.connect(self._choose_zip)
        self._dir_btn = self._button("Folder ...")
        self._dir_btn.clicked.connect(self._choose_folder)
        self._stop_btn = self._button("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_scan)
        self._progress = self._label("", color=app.TEXT2, size=8)
        for widget in (self._zip_btn, self._dir_btn, self._stop_btn):
            bar.addWidget(widget)
        bar.addWidget(self._progress, 1)
        lay.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 8, 0)
        left_lay.setSpacing(6)
        head = QHBoxLayout()
        self._title = self._label("", bold=True)
        head.addWidget(self._title, 1)
        # the detail of one field (double-click on a cell of a family table): back, and month / year
        self._back_btn = self._button("← Back")
        self._back_btn.clicked.connect(self._leave_detail)
        self._month_btn = self._button("Month")
        self._month_btn.setCheckable(True)
        self._month_btn.clicked.connect(lambda: self._set_gran("month"))
        self._year_btn = self._button("Year")
        self._year_btn.setCheckable(True)
        self._year_btn.clicked.connect(lambda: self._set_gran("year"))
        # counts view or values view of the field; the values by time or as a distribution
        self._counts_btn = self._button("Counts")
        self._counts_btn.setCheckable(True)
        self._counts_btn.clicked.connect(self._leave_values)
        self._values_btn = self._button("Values")
        self._values_btn.setCheckable(True)
        self._values_btn.clicked.connect(self.start_values)
        self._series_btn = self._button("Over time")
        self._series_btn.setCheckable(True)
        self._series_btn.clicked.connect(lambda: self._set_vmode("series"))
        self._dist_btn = self._button("Distribution")
        self._dist_btn.setCheckable(True)
        self._dist_btn.clicked.connect(lambda: self._set_vmode("histogram"))
        for widget in (self._back_btn, self._counts_btn, self._values_btn, self._month_btn, self._year_btn,
                       self._series_btn, self._dist_btn):
            widget.setVisible(False)
            head.addWidget(widget)
        # the heart rate of one day (the FIT node): a day, the day before / after that has files, and show it
        self._day_prev = self._button("◀")
        self._day_prev.clicked.connect(lambda: self._step_day(-1))
        self._day_edit = QDateEdit()
        self._day_edit.setDisplayFormat("yyyy-MM-dd")
        self._day_edit.setCalendarPopup(True)
        self._day_edit.setStyleSheet(f"QDateEdit {{ background: {app.BG3}; color: {app.TEXT}; border: none; padding: 6px 8px; }}")
        self._day_next = self._button("▶")
        self._day_next.clicked.connect(lambda: self._step_day(1))
        self._day_btn = self._button("Heart rate of the day")
        self._day_btn.clicked.connect(self.start_day)
        self._day_widgets = (self._day_prev, self._day_edit, self._day_next, self._day_btn)
        for widget in self._day_widgets:
            widget.setVisible(False)
            head.addWidget(widget)
        self._table_btn = self._button("Table")
        self._table_btn.setCheckable(True)
        self._table_btn.setChecked(True)
        self._table_btn.clicked.connect(lambda: self._set_mode("table"))
        self._graph_btn = self._button("Graph")
        self._graph_btn.setCheckable(True)
        self._graph_btn.setEnabled(False)
        self._graph_btn.clicked.connect(lambda: self._set_mode("graph"))
        head.addWidget(self._table_btn)
        head.addWidget(self._graph_btn)
        left_lay.addLayout(head)
        self._note = self._label("", color=app.TEXT2, size=8)
        left_lay.addWidget(self._note)
        self._hint = self._label(model.VALUES_HINT, bold=True, color=app.YELLOW, size=8)
        self._hint.setVisible(False)
        left_lay.addWidget(self._hint)

        self._table = QTableWidget()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.cellDoubleClicked.connect(self._on_cell_double_click)
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {app.BG}; color: {app.TEXT}; border: none; gridline-color: {app.BG3}; }}"
            f"QHeaderView::section {{ background: {app.BG3}; color: {app.TEXT2}; border: none; padding: 4px 8px; }}")
        self._message = self._label("", color=app.TEXT2)
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._message)
        left_lay.addWidget(self._stack, 1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background: {app.BG}; color: {app.TEXT}; border: none; }}"
            f"QTreeWidget::item {{ padding: 3px 2px; }}"
            f"QTreeWidget::item:selected {{ background: {app.ACCENT2}; color: {app.TEXT}; }}")
        self._tree.currentItemChanged.connect(self._on_select)

        splitter.addWidget(left)
        splitter.addWidget(self._tree)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([780, 320])
        lay.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self._status = self._label("", color=app.TEXT2, size=8)
        bottom.addWidget(self._status, 1)
        self._save_btn = self._button("Save report")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_report)
        self._help_btn = self._button("Help")
        self._help_btn.clicked.connect(self._show_help)
        close_btn = self._button("Close")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(self._help_btn)
        bottom.addWidget(self._save_btn)
        bottom.addWidget(close_btn)
        lay.addLayout(bottom)

    # ── Scan ───────────────────────────────────────────────────────────────────

    def _choose_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Garmin Export ZIP", filter="ZIP files (*.zip);;All files (*.*)")
        if path:
            self.start_scan(path)

    def _choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select unpacked Garmin Export folder")
        if path:
            self.start_scan(path)

    def start_scan(self, path):
        """Starts a scan of path (a ZIP file or a folder) in the background. Ignored while one runs."""
        if self._running:
            return
        self._source_path = str(path)
        self._days = None                       # the day view comes back when this scan is done
        self._update_detail_controls()
        self._stop.clear()
        self._set_running(True)
        self._progress.setText("Scanning ...")
        self._status.setText("")
        scanner, fit_scan, day_reader, stop, app = self._scanner, self._fit_scan, self._day_reader, self._stop, self._app

        def progress(done, total):
            app._dispatch(self._on_progress, done, total)

        def fit_progress(done):
            app._dispatch(self._on_fit_progress, done)

        def worker():
            result, error, fit_failed, days = None, None, False, None
            index = {}                           # the monitoring files of the FIT scan: for the day view, memory only
            try:
                result = scanner.scan(str(path), should_stop=stop.is_set, progress=progress)
            except FileNotFoundError:
                error = "The path does not exist."
            except Exception:                    # never show the text of an exception: it may hold a path
                error = "The export could not be scanned."
            if result is not None and not result["stopped"] and result["source"] != "unreadable":
                try:
                    fit = fit_scan(str(path), should_stop=stop.is_set, progress=fit_progress, index=index)
                except Exception:                # the JSON side is shown anyway
                    fit, fit_failed = None, True
                if fit is not None:
                    result["fit"] = fit
                    result["stopped"] = fit["stopped"]
                    if not fit["stopped"]:
                        try:
                            days = day_reader.prepare(str(path), index, should_stop=stop.is_set)
                        except Exception:        # no day view then; the rest is shown anyway
                            days = None
            app._dispatch(self._on_done, result, error, fit_failed, days)

        self._run(worker)

    def _stop_scan(self):
        if self._running:
            self._stop.set()
            self._progress.setText("Stopping ...")

    def _set_running(self, running):
        self._running = running
        self._zip_btn.setEnabled(not running)
        self._dir_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        for widget in self._day_widgets:
            widget.setEnabled(not running)

    def _on_progress(self, done, total):
        if self._alive and self._running:
            self._progress.setText(f"Scanning ... {done} / {total} files")

    def _on_fit_progress(self, done):
        if self._alive and self._running:
            self._progress.setText(f"Reading FIT files ... {done}")

    def _on_done(self, result, error, fit_failed=False, days=None):
        if not self._alive:
            return
        self._set_running(False)
        self._progress.setText("")
        if error:
            self._status.setText(error)
            return
        self._result = result
        self._detail = None
        self._drop_values()
        self._days = days
        if days:                                 # the picker of the day view: from the first to the last day with files
            first, last = days["days"][0], days["days"][-1]
            self._day_edit.setDateRange(QDate.fromString(first, "yyyy-MM-dd"), QDate.fromString(last, "yyyy-MM-dd"))
            self._day_edit.setDate(QDate.fromString(last, "yyyy-MM-dd"))
        files = result["files"]
        fit = result.get("fit")
        self._status.setText(
            f"{files['json_read']} of {files['json_total']} JSON files read"
            + (f", {fit['files']['read']} FIT files read" if fit else "")
            + (", scan stopped (numbers incomplete)" if result["stopped"] else "")
            + (f", {files['unreadable']} unreadable" if files["unreadable"] else "")
            + (", the FIT files could not be read" if fit_failed else ""))
        self._app._log(f"🔍  Export scan: {files['json_read']} of {files['json_total']} JSON files read, "
                       f"{files['unknown_json']} of no known family"
                       + (f", {fit['files']['read']} FIT files read." if fit else "."))
        self._save_btn.setEnabled(True)
        self._fill_tree(result)

    # ── Tree ───────────────────────────────────────────────────────────────────

    def _status_color(self, status):
        return getattr(self._app, _STATUS_COLORS[status])

    def _fill_tree(self, result):
        self._tree.blockSignals(True)
        self._tree.clear()

        def add(parent, node):
            text = node["text"] if node["status"] is None else "● " + node["text"]
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, node["id"])
            if node["status"] is not None:
                item.setForeground(0, QBrush(QColor(self._status_color(node["status"]))))
            if parent is None:
                self._tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in node["children"]:
                add(item, child)

        for node in model.build_tree(result):
            add(None, node)
        self._tree.expandAll()
        self._tree.blockSignals(False)
        self._tree.setCurrentItem(self._tree.topLevelItem(0))        # fires _on_select

    def _on_select(self, item, _previous):
        if item is None or self._result is None:
            return
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(node, (tuple, list)) and len(node) == 2:
            self._node = tuple(node)
            self._detail = None                  # another item of the tree: back to the normal view
            self._drop_values()
            self._render()

    # ── Table and chart ────────────────────────────────────────────────────────

    def _chart_available(self):
        if self._values is not None:
            return model.has_values(self._values)
        if self._detail is not None:
            return model.has_field_chart(self._detail)
        return model.has_chart(self._result, self._node)

    def _render(self):
        table = model.build_table(self._result, self._node)
        self._title.setText(table["title"])
        self._note.setText(table["note"])
        self._fill_table(table)
        self._after_render()

    def _after_render(self):
        has_chart = self._chart_available()
        self._graph_btn.setEnabled(has_chart)
        if self._mode == "graph" and not has_chart:
            self._mode = "table"
        self._sync_mode_buttons()
        self._update_detail_controls()
        self._show_current()

    # ── The detail of one field ────────────────────────────────────────────────

    def _on_cell_double_click(self, row, _column):
        """Double-click on a cell of a family table: the detail of that field (row 0 is the 'Rows' line)."""
        if self._detail is not None or self._running or self._result is None or self._source_path is None:
            return
        kind, key = self._node
        item = self._table.item(row, 0)
        if kind == "family" and row >= 1 and item is not None:
            self.start_detail(key, item.text())

    def start_detail(self, family, field):
        """Reads the detail of one field of a family (by month) in the background. Ignored while a scan runs."""
        if self._running or self._source_path is None:
            return
        self._stop.clear()
        self._set_running(True)
        self._progress.setText("Reading the field ...")
        scanner, stop, app, path = self._scanner, self._stop, self._app, self._source_path

        def worker():
            detail, error = None, None
            try:
                detail = scanner.scan_field(path, family, field, should_stop=stop.is_set)
            except FileNotFoundError:
                error = "The path does not exist."
            except Exception:                    # never show the text of an exception: it may hold a path
                error = "The field could not be read."
            app._dispatch(self._on_detail_done, detail, error)

        self._run(worker)

    def _on_detail_done(self, detail, error):
        if not self._alive:
            return
        self._set_running(False)
        self._progress.setText("")
        if error:
            self._status.setText(error)
            return
        self._detail = detail
        self._gran = "month"
        self._drop_values()
        self._status.setText(f"{detail['field']}: {detail['rows']} rows read"
                             + (", read stopped (numbers incomplete)" if detail["stopped"] else ""))
        self._render_detail()

    def _render_detail(self):
        table = model.build_field_table(self._detail, self._gran)
        self._title.setText(table["title"])
        self._note.setText(table["note"])
        self._fill_table(table)
        self._after_render()

    def _leave_detail(self):
        self._detail = None
        self._drop_values()
        if self._result is not None:
            self._render()

    def _set_gran(self, gran):
        self._gran = gran
        if self._detail is not None:
            self._render_detail()

    def _update_detail_controls(self):
        in_detail = self._detail is not None
        in_values = self._values is not None                 # the values of a field, or the heart rate of a day
        in_field_values = in_detail and in_values
        for widget in (self._counts_btn, self._values_btn):
            widget.setVisible(in_detail)
        self._back_btn.setVisible(in_detail or in_values)
        for widget in (self._month_btn, self._year_btn):                 # the counts by month or year
            widget.setVisible(in_detail and not in_values)
        for widget in (self._series_btn, self._dist_btn, self._hint):    # the values over time or as a distribution
            widget.setVisible(in_values)
        for widget in self._day_widgets:                     # the heart rate of a day: at the FIT node, once it is ready
            widget.setVisible(self._days is not None and self._result is not None and self._node == model.NODE_FIT)
        self._month_btn.setChecked(self._gran == "month")
        self._year_btn.setChecked(self._gran == "year")
        self._counts_btn.setChecked(in_detail and not in_values)
        self._values_btn.setChecked(in_field_values)
        self._series_btn.setChecked(self._vmode == "series")
        self._dist_btn.setChecked(self._vmode == "histogram")

    # ── The values of the field (memory only) ──────────────────────────────────

    def _drop_values(self):
        """Forgets the values: the view, the call waiting for the page, and the page itself if it holds them."""
        self._values = None
        self._pending_js = None
        if self._web_kind == "values" and self._web is not None:
            self._web.setUrl(QUrl("about:blank"))
        if self._web_kind == "values":
            self._web_kind, self._web_ready = None, False

    def start_values(self):
        """Reads the VALUES of the field of the detail in the background. Ignored while a scan runs."""
        if self._running or self._detail is None or self._source_path is None:
            self._update_detail_controls()
            return
        self._stop.clear()
        self._set_running(True)
        self._progress.setText("Reading the values ...")
        scanner, stop, app, path = self._scanner, self._stop, self._app, self._source_path
        family, field = self._detail["family"], self._detail["field"]

        def worker():
            values, error = None, None
            try:
                values = scanner.read_values(path, family, field, should_stop=stop.is_set)
            except FileNotFoundError:
                error = "The path does not exist."
            except Exception:                    # never show the text of an exception: it may hold a path
                error = "The values could not be read."
            app._dispatch(self._on_values_done, values, error)

        self._run(worker)

    def _on_values_done(self, values, error):
        if not self._alive:
            return
        self._set_running(False)
        self._progress.setText("")
        if error:
            self._status.setText(error)
            self._update_detail_controls()
            return
        day = model.is_day(values)
        if day != (self._detail is None) or (day and self._node != model.NODE_FIT):
            self._update_detail_controls()       # the view was left while it was read: the answer belongs nowhere
            return
        self._values = values
        self._vmode = "series"
        count = values["stats"]["count"] if values["stats"] else 0
        # numbers only: the status line never shows a value
        self._status.setText(f"{values['field']}: {count} values read" if count else
                             f"{values['field']}: no numbers to show")
        table = model.build_values_table(values)
        self._title.setText(table["title"])
        self._note.setText(table["note"])
        self._fill_table(table)
        self._after_render()

    # ── The heart rate of one day (memory only, shown as values) ───────────────

    def _step_day(self, direction):
        """The day before (-1) or after (+1) the chosen one that has monitoring files; shows it."""
        if self._days is None or self._running:
            return
        days, current = self._days["days"], self._day_edit.date().toString("yyyy-MM-dd")
        if direction > 0:
            target = next((day for day in days if day > current), None)
        else:
            target = next((day for day in reversed(days) if day < current), None)
        if target is not None:
            self._day_edit.setDate(QDate.fromString(target, "yyyy-MM-dd"))
            self.start_day()

    def start_day(self):
        """Reads the heart rate of the chosen day in the background (about 3 s). Ignored while something runs."""
        if self._running or self._days is None or self._source_path is None:
            return
        day = self._day_edit.date().toString("yyyy-MM-dd")
        self._stop.clear()
        self._set_running(True)
        self._progress.setText("Reading the heart rate of the day ...")
        reader, prepared, stop, app, path = self._day_reader, self._days, self._stop, self._app, self._source_path

        def worker():
            values, error = None, None
            try:
                values = reader.read_day(path, prepared, day, should_stop=stop.is_set)
            except FileNotFoundError:
                error = "The path does not exist."
            except Exception:                    # never show the text of an exception: it may hold a path
                error = "The heart rate of the day could not be read."
            app._dispatch(self._on_values_done, values, error)

        self._run(worker)

    def _leave_values(self):
        """Back from the values to the counts of the field."""
        if self._detail is None:
            return
        self._drop_values()
        self._render_detail()

    def _set_vmode(self, mode):
        self._vmode = mode
        if self._values is not None:
            self._after_render()

    def _tint(self, value):
        """Background of a cell with a value 0..100: from the panel colour to the accent colour."""
        base, accent = QColor(self._app.BG3), QColor(self._app.ACCENT)
        t = max(0, min(100, value)) / 100 * 0.85
        return QColor(*(int(b + (a - b) * t) for b, a in
                        ((base.red(), accent.red()), (base.green(), accent.green()), (base.blue(), accent.blue()))))

    def _fill_table(self, table):
        self._table.clear()
        self._table.setColumnCount(len(table["headers"]))
        self._table.setRowCount(len(table["rows"]))
        self._table.setHorizontalHeaderLabels(table["headers"])
        for r, row in enumerate(table["rows"]):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(cell["text"])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if cell["tip"]:
                    item.setToolTip(cell["tip"])
                if cell["value"] is not None:
                    item.setBackground(QBrush(self._tint(cell["value"])))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(r, c, item)
        self._table.resizeColumnsToContents()
        if table["headers"] and self._table.columnWidth(0) > 380:
            self._table.setColumnWidth(0, 380)

    def _set_mode(self, mode):
        self._mode = mode
        self._sync_mode_buttons()
        self._show_current()

    def _sync_mode_buttons(self):
        self._table_btn.setChecked(self._mode == "table")
        self._graph_btn.setChecked(self._mode == "graph")

    def _show_message(self, text):
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)

    def _show_current(self):
        if self._result is None:
            self._show_message(_MSG_START)
        elif self._mode == "graph" and self._chart_available():
            if self._values is not None:
                self._show_values_chart()
            else:
                self._show_chart()
        else:
            self._stack.setCurrentWidget(self._table)

    def _get_plotly(self):
        if self._plotly is None:
            self._plotly = self._plotly_fn() or ""
        return self._plotly or None

    def _theme(self):
        app = self._app
        return {"bg": app.BG, "bg2": app.BG2, "bg3": app.BG3, "text": app.TEXT, "text2": app.TEXT2,
                "accent": app.ACCENT, "accent2": app.ACCENT2, "green": app.GREEN, "yellow": app.YELLOW,
                "red": app.RED}

    def _ensure_web(self):
        if self._web is None:
            self._web = QWebEngineView()
            qwebengine_hardening.harden(self._web)
            self._web.setStyleSheet(f"background: {self._app.BG};")
            self._web.loadFinished.connect(self._on_web_loaded)
            self._stack.addWidget(self._web)

    def _load_page(self, html, kind):
        """Writes a chart page into the temporary folder and loads it. kind: "counts" (the page holds counts
        and names only) or "values" (Plotly and an empty chart: the values come later, by glaRender)."""
        if self._tmpdir is None:
            self._tmpdir = tempfile.mkdtemp(prefix="gla_export_scan_")
        path = Path(self._tmpdir) / ("values.html" if kind == "values" else "chart.html")
        path.write_text(html, encoding="utf-8")
        self._ensure_web()
        self._web_kind, self._web_ready = kind, False
        self._chart_n += 1
        url = QUrl.fromLocalFile(str(path))
        url.setQuery(str(self._chart_n))
        self._web.setUrl(url)
        self._stack.setCurrentWidget(self._web)

    def _on_web_loaded(self, ok):
        """The values page is loaded: now the waiting call hands it the values (never written to a file)."""
        if self._web_kind == "values":
            self._web_ready = bool(ok)
            if ok and self._pending_js:
                js, self._pending_js = self._pending_js, None
                self._web.page().runJavaScript(js)

    def _show_chart(self):
        script = self._get_plotly()
        if not script:
            self._show_message(_MSG_NO_PLOTLY)
            return
        theme = self._theme()
        if self._detail is not None:
            html = model.build_field_chart_html(self._detail, self._gran, script, theme)
        else:
            html = model.build_chart_html(self._result, self._node, script, theme)
        if html is None:
            self._show_message(_MSG_NO_GRAPH)
            return
        self._load_page(html, "counts")

    def _show_values_chart(self):
        script = self._get_plotly()
        if not script:
            self._show_message(_MSG_NO_PLOTLY)
            return
        theme = self._theme()
        js = model.build_values_js(self._values, self._vmode, theme)
        if js is None:
            self._show_message(_MSG_NO_GRAPH)
            return
        if self._web_kind == "values" and self._web is not None:        # the page is there: only new data
            if self._web_ready:
                self._web.page().runJavaScript(js)
            else:
                self._pending_js = js
            self._stack.setCurrentWidget(self._web)
            return
        self._pending_js = js
        self._load_page(model.build_values_page(script, theme), "values")

    # ── Report ─────────────────────────────────────────────────────────────────

    def _default_report_dir(self):
        base_dir = self._app._panel_settings._collect_settings().get("base_dir", "")
        return Path(base_dir) / "garmin_data" / "log" if base_dir else None

    def _save_report(self):
        if self._result is None:
            return
        folder = self._report_dir_fn()
        if folder is None:
            self._status.setText("Set the data folder in the settings first.")
            return
        try:
            written = self._scanner.write_report(self._result, folder)
        except OSError:
            self._status.setText("The report could not be saved.")
            return
        self._status.setText(f"Report saved in {folder}: {written['text'].name}, {written['json'].name}")

    # ── Help ───────────────────────────────────────────────────────────────────

    def _show_help(self):
        """The guide of this window (README_EXPORT_SCAN.md) in the documentation viewer of the app."""
        path = frozen_paths.doc_path(HELP_FILE)
        if path is None:
            self._status.setText("The help file was not found.")
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            DocViewerDialog(self._app, "Export Scan — Help", text, markdown=True).show()
        except Exception:                        # never show the text of an exception: it may hold a path
            self._status.setText("The help file could not be opened.")

    # ── Close ──────────────────────────────────────────────────────────────────

    def _cleanup(self):
        """Stops a running scan, lets the late answers of its thread fall away, removes the chart folder."""
        self._alive = False
        self._stop.set()
        self._values = None
        self._days = None
        self._pending_js = None
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def done(self, result):                      # Esc / reject() hide the dialog without a close event
        self._cleanup()
        super().done(result)


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def open_window(panel):
    """Opens the Export Scan window, or brings the open one to the front."""
    global _window
    if _window is not None:
        try:
            if _window.isVisible():
                _window.raise_()
                _window.activateWindow()
                return
        except RuntimeError:                       # the window was deleted
            pass
        _window = None
    window = ExportScanWindow(panel._app)

    def _forget(*_args):
        global _window
        _window = None

    window.destroyed.connect(_forget)
    _window = window
    window.show()
