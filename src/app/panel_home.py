#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
app/panel_home.py
Garmin Local Archive — Home Panel

PanelHome — PyQt6 QWidget owning the fixed top area (Connection & Archive
Status + Daily Actions) and the Tab 0 Dashboard content (Dashboard view +
collapsible Activity Log).

Layout injected by garmin_app_base._build_ui():
  - self._panel_home added to root_layout above the QTabWidget (fixed top)
  - self._panel_home.tab_widget added as Tab 0 "Dashboard"

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _home_* prefix (E-7)
  - Workers never touch widgets — use self._app._dispatch()
  - _detect_gap() is read-only — no QUALITY_LOCK required
  - Daily Sync orchestrates via existing panel methods — never duplicates logic
  - Mirror dialogs check mirror_dir via _collect_settings() at click time
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QTableWidget,
    QHeaderView, QDialog, QLineEdit, QFileDialog, QMessageBox,
    QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWebEngineWidgets import QWebEngineView


class PanelHome(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Build fixed top area + Tab 1 content widget."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Fixed top ─────────────────────────────────────────────────────────
        top = QWidget()
        top.setStyleSheet(f"background: {self._app.BG};")
        top.setAutoFillBackground(True)
        top_outer = QVBoxLayout(top)
        top_outer.setContentsMargins(20, 6, 20, 4)
        top_outer.setSpacing(0)

        # Section header
        hdr = QLabel("CONNECTION & ARCHIVE STATUS")
        hdr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {self._app.ACCENT};")
        top_outer.addWidget(hdr)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        top_outer.addWidget(sep)
        top_outer.addSpacing(5)

        # ── Two-column layout: left=Status+Table  right=Daily Actions ─────────
        cols = QHBoxLayout()
        cols.setSpacing(16)
        cols.setContentsMargins(0, 0, 0, 0)

        # ── Left column ───────────────────────────────────────────────────────
        left_widget = QWidget()
        left_widget.setStyleSheet(f"background: {self._app.BG};")
        left_widget.setAutoFillBackground(True)
        left = QVBoxLayout(left_widget)
        left.setSpacing(0)
        left.setContentsMargins(0, 0, 0, 0)

        # Connection indicators
        ind_row = QHBoxLayout()
        ind_row.setSpacing(0)
        self._conn_indicators = {}
        for key, label in [("token", "Token"), ("login", "Login"),
                            ("api", "API Access"), ("data", "Data")]:
            dot = QLabel("●")
            dot.setFont(QFont("Segoe UI", 10))
            dot.setStyleSheet(f"color: {self._app.TEXT2};")
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            ind_row.addWidget(dot)
            ind_row.addSpacing(3)
            ind_row.addWidget(lbl)
            ind_row.addSpacing(14)
            self._conn_indicators[key] = dot
        ind_row.addStretch()
        left.addLayout(ind_row)
        left.addSpacing(3)

        # Archive info row 1: fail + recheck + missing
        row1 = QHBoxLayout()
        row1.setSpacing(0)
        self._info_qdots = {}
        dot = QLabel("●")
        dot.setFont(QFont("Segoe UI", 9))
        dot.setStyleSheet(f"color: {self._app.ACCENT};")
        lbl_fail = QLabel("fail —")
        lbl_fail.setFont(QFont("Segoe UI", 8))
        lbl_fail.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(dot)
        row1.addSpacing(2)
        row1.addWidget(lbl_fail)
        row1.addSpacing(10)
        self._info_qdots["failed"] = lbl_fail

        self._info_recheck = QLabel("Recheck: —")
        self._info_recheck.setFont(QFont("Segoe UI", 8))
        self._info_recheck.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_recheck)
        row1.addSpacing(10)

        self._info_missing = QLabel("Missing: —")
        self._info_missing.setFont(QFont("Segoe UI", 8))
        self._info_missing.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_missing)
        row1.addSpacing(10)

        sep_src = QLabel("||")
        sep_src.setFont(QFont("Segoe UI", 8))
        sep_src.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(sep_src)
        row1.addSpacing(10)

        self._info_source = QLabel("Source: —")
        self._info_source.setFont(QFont("Segoe UI", 8))
        self._info_source.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_source)
        row1.addStretch()
        left.addLayout(row1)

        # Archive info row 2: range + coverage + last api + last bulk
        row2 = QHBoxLayout()
        row2.setSpacing(0)
        for attr, text in [
            ("_info_range",    "Range: —"),
            ("_info_coverage", "Coverage: —"),
            ("_info_last_api", "Last API: —"),
            ("_info_last_bulk", "Last Bulk: —"),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            setattr(self, attr, lbl)
            row2.addWidget(lbl)
            row2.addSpacing(14)
        row2.addStretch()
        left.addLayout(row2)
        left.addSpacing(2)

        # Integrity warning
        self._integrity_warning_lbl = QLabel("")
        self._integrity_warning_lbl.setFont(QFont("Segoe UI", 8))
        self._integrity_warning_lbl.setStyleSheet(f"color: {self._app.ACCENT};")
        left.addWidget(self._integrity_warning_lbl)
        left.addSpacing(2)

        # Device table — grid on, alternating colors, no scrollbars
        _HDR = ["From", "To", "Device", "High", "Std", "Total"]
        self._info_device_table = QTableWidget(0, len(_HDR))
        self._info_device_table.setHorizontalHeaderLabels(_HDR)
        for col in range(len(_HDR)):
            self._info_device_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._info_device_table.horizontalHeader().setStretchLastSection(False)
        self._info_device_table.verticalHeader().setVisible(False)
        self._info_device_table.setShowGrid(True)
        self._info_device_table.setAlternatingRowColors(True)
        self._info_device_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        # Qt6/Windows: cellDoubleClicked does not fire with NoSelection.
        # SingleSelection enables the signal; selection highlight is hidden
        # via stylesheet ::item:selected so the table appears non-interactive.
        self._info_device_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self._info_device_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._info_device_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._info_device_table.setFrameShape(QFrame.Shape.NoFrame)
        self._info_device_table.setSizeAdjustPolicy(
            QTableWidget.SizeAdjustPolicy.AdjustToContents)
        self._info_device_table.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._info_device_table.setStyleSheet(
            f"QTableWidget {{ background: {self._app.BG2}; "
            f"alternate-background-color: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"gridline-color: {self._app.BG3}; "
            f"border: none; font-family: 'Segoe UI'; font-size: 8pt; }}"
            f"QTableWidget::item:selected {{ background: transparent; "
            f"color: {self._app.TEXT}; }}"
            f"QAbstractScrollArea {{ background: {self._app.BG2}; }}"
            f"QHeaderView::section {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT2}; border: none; padding: 2px 4px; "
            f"font-size: 8pt; }}")
        self._info_device_table.viewport().setStyleSheet(
            f"background: {self._app.BG2};")
        left.addWidget(self._info_device_table)
        left.addStretch()

        cols.addWidget(left_widget, stretch=0)

        # ── Right column: Daily Actions ───────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(6)
        right.setContentsMargins(0, 0, 0, 0)

        act_hdr = QLabel("DAILY ACTIONS")
        act_hdr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        act_hdr.setStyleSheet(f"color: {self._app.ACCENT};")
        right.addWidget(act_hdr)
        act_sep = QFrame()
        act_sep.setFrameShape(QFrame.Shape.HLine)
        act_sep.setStyleSheet(f"color: {self._app.ACCENT};")
        act_sep.setFixedHeight(1)
        right.addWidget(act_sep)
        right.addSpacing(2)

        def _action_btn(text, accent=False):
            b = QPushButton(text)
            b.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            bg = self._app.ACCENT if accent else self._app.BG3
            fg = self._app.TEXT
            b.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; "
                f"border: none; padding: 7px 14px; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
                f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
                f"background: {self._app.BG3}; }}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return b

        self._daily_sync_btn = _action_btn("▶  Daily Sync", accent=True)
        self._daily_sync_btn.setToolTip(
            "Download missing days from Garmin Connect.\n"
            "Includes intraday data, daily summaries, weather and pollen.")
        self._daily_sync_btn.clicked.connect(self._on_daily_sync)
        right.addWidget(self._daily_sync_btn)

        self._mirror_btn = _action_btn("⬡  Mirror")
        self._mirror_btn.setToolTip(
            "Create an encrypted backup of the archive (.gla container).\n"
            "Also allows importing data from an existing mirror.")
        self._mirror_btn.clicked.connect(self._on_mirror)
        right.addWidget(self._mirror_btn)

        self._timer_btn = _action_btn("⏱  Timer: Off")
        self._timer_btn.setToolTip(
            "Start the background timer.\n"
            "Automatically syncs missing days at the configured interval\n"
            "while the app is open.")
        self._timer_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        self._timer_btn.clicked.connect(
            lambda: self._app._panel_timer._toggle_timer())
        right.addWidget(self._timer_btn)

        self._docs_btn = _action_btn("📖  Documentation")
        self._docs_btn.setToolTip(
            "Open Quickstart, User Guide or README.")
        self._docs_btn.clicked.connect(self._home_docs_dialog)
        right.addWidget(self._docs_btn)

        right.addStretch()
        cols.addLayout(right, stretch=1)

        top_outer.addLayout(cols)
        top_outer.addSpacing(4)
        root.addWidget(top)

        # ── Tab 1 content widget (returned via .tab_widget) ───────────────────
        self.tab_widget = QWidget()
        self.tab_widget.setStyleSheet(f"background: {self._app.BG};")
        tab_lay = QVBoxLayout(self.tab_widget)
        tab_lay.setContentsMargins(12, 8, 12, 8)
        tab_lay.setSpacing(6)

        # Dashboard section header
        dash_hdr = QLabel("DASHBOARD")
        dash_hdr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        dash_hdr.setStyleSheet(f"color: {self._app.ACCENT};")
        tab_lay.addWidget(dash_hdr)
        dash_sep = QFrame()
        dash_sep.setFrameShape(QFrame.Shape.HLine)
        dash_sep.setStyleSheet(f"color: {self._app.ACCENT};")
        dash_sep.setFixedHeight(1)
        tab_lay.addWidget(dash_sep)

        # Dashboard combo row — combo + ▼ label (Qt6/Windows suppresses native
        # drop-down arrow when any stylesheet is set; QLabel is reliable fallback)
        dash_combo_row = QHBoxLayout()
        dash_combo_row.setSpacing(0)
        self._dash_combo = QComboBox()
        self._dash_combo.setFont(QFont("Segoe UI", 9))
        self._dash_combo.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._dash_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dash_combo.setToolTip("Click to select a dashboard.")
        self._dash_combo.currentIndexChanged.connect(
            self._app._load_selected_dashboard)
        dash_arrow = QLabel("▼")
        dash_arrow.setFont(QFont("Segoe UI", 7))
        dash_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        dash_arrow.setFixedWidth(16)
        dash_combo_row.addWidget(self._dash_combo)
        dash_combo_row.addWidget(dash_arrow)
        tab_lay.addLayout(dash_combo_row)

        self._dash_view = QWebEngineView()
        self._dash_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._dash_view.setStyleSheet(f"background: {self._app.BG};")
        tab_lay.addWidget(self._dash_view)

        # Activity Log removed in v1.6 — quality info covered in fixed top area.
        # Reserved for v1.7 FIT Pipeline.

    # ── Indicator ──────────────────────────────────────────────────────────────

    def _set_indicator(self, key: str, state: str):
        """Update connection indicator dot color. Main Thread only."""
        dot = self._conn_indicators.get(key)
        if not dot:
            return
        colors = {
            "ok":    self._app.GREEN,
            "fail":  "#e94560",
            "reset": self._app.TEXT2,
        }
        dot.setStyleSheet(f"color: {colors.get(state, self._app.TEXT2)};")

    # Activity log methods removed in v1.6.

    # ── Gap detection ──────────────────────────────────────────────────────────

    def _detect_gap(self) -> int:
        """Return days since last sync. Read-only — no QUALITY_LOCK needed."""
        try:
            s = self._app._panel_settings._collect_settings()
            base_dir = Path(s.get("base_dir", "")).expanduser()
            log_path = base_dir / "garmin_data" / "log" / "quality_log.json"
            if not log_path.exists():
                return 0
            data = json.loads(log_path.read_text(encoding="utf-8"))
            last_api = data.get("last_api")
            if not last_api:
                return 0
            last_date = date.fromisoformat(last_api)
            return (date.today() - last_date).days
        except Exception:
            return 0

    # ── Daily Sync ─────────────────────────────────────────────────────────────

    def _on_daily_sync(self):
        """Daily Sync button handler. Main Thread only.
        Gap check → optional dialog → Garmin Sync → Context Sync → Create All."""
        gap = self._detect_gap()
        if gap > 7:
            dlg = QDialog(self._app)
            dlg.setWindowTitle("Daily Sync")
            dlg.setModal(True)
            dlg.setFixedWidth(420)
            dlg.setStyleSheet(
                f"background: {self._app.BG}; color: {self._app.TEXT};")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(20, 16, 20, 16)
            lay.setSpacing(8)

            title = QLabel(f"Large gap detected — {gap} days since last sync")
            title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            title.setStyleSheet(f"color: {self._app.TEXT};")
            lay.addWidget(title)

            body = QLabel(
                "Intraday data is only available via API.\n"
                "For large gaps the background timer is more efficient.")
            body.setFont(QFont("Segoe UI", 9))
            body.setStyleSheet(f"color: {self._app.TEXT2};")
            body.setWordWrap(True)
            lay.addWidget(body)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {self._app.BG3};")
            lay.addWidget(sep)

            btn_row = QHBoxLayout()
            sync_btn = QPushButton("▶  Sync now")
            sync_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            sync_btn.setStyleSheet(
                f"QPushButton {{ background: {self._app.ACCENT}; "
                f"color: {self._app.TEXT}; border: none; padding: 7px 14px; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
            sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sync_btn.clicked.connect(dlg.accept)

            cancel_btn = QPushButton("Cancel")
            cancel_btn.setFont(QFont("Segoe UI", 9))
            cancel_btn.setStyleSheet(
                f"QPushButton {{ background: {self._app.BG3}; "
                f"color: {self._app.TEXT2}; border: none; padding: 7px 14px; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.clicked.connect(dlg.reject)

            btn_row.addStretch()
            btn_row.addWidget(cancel_btn)
            btn_row.addWidget(sync_btn)
            lay.addLayout(btn_row)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

        self._daily_sync_btn.setEnabled(False)

        def _on_all_done():
            self._daily_sync_btn.setEnabled(True)

        def _on_context_done():
            self._app._panel_outputs._run_all_dashboards(
                on_done=_on_all_done)

        def _on_garmin_done():
            self._app._panel_outputs._run_context_sync(
                on_done=_on_context_done)

        self._app._panel_outputs._run_collector(on_done=_on_garmin_done)

    # ── Mirror ─────────────────────────────────────────────────────────────────

    def _home_docs_dialog(self):
        """Documentation button handler — opens Quickstart, User Guide or README."""
        def _open(filename: str):
            # Dev: src/docs/  |  Build T2/T3: info/ next to EXE
            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent / "info"
            else:
                base = Path(__file__).parent.parent / "docs"
            path = base / filename
            if not path.exists():
                QMessageBox.warning(
                    self._app, "Documentation",
                    f"File not found:\n{path}")
                return
            try:
                os.startfile(path)
            except Exception as e:
                QMessageBox.critical(
                    self._app, "Documentation",
                    f"Could not open file:\n{e}")

        dlg = QDialog(self._app)
        dlg.setWindowTitle("Documentation")
        dlg.setModal(True)
        dlg.setFixedWidth(360)
        dlg.setStyleSheet(
            f"background: {self._app.BG}; color: {self._app.TEXT};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        title = QLabel("Documentation")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {self._app.TEXT};")
        lay.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        for label, filename in [
            ("📋  Quickstart",  "QUICKSTART.txt"),
            ("📖  User Guide",  "USER_GUIDE.txt"),
            ("📄  README App",  "README_APP.md"),
        ]:
            btn = QPushButton(label)
            btn.setFont(QFont("Segoe UI", 9))
            btn.setStyleSheet(
                f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
                f"border: none; padding: 8px 14px; text-align: left; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _fn = filename
            btn.clicked.connect(lambda checked, fn=_fn: [dlg.accept(), _open(fn)])
            lay.addWidget(btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {self._app.BG3};")
        lay.addWidget(sep2)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)
        lay.addWidget(cancel_btn)

        dlg.exec()

    def _on_mirror(self):
        """Mirror button handler. Main Thread only."""
        s = self._app._panel_settings._collect_settings()
        mirror_dir = s.get("mirror_dir", "").strip()
        if not mirror_dir:
            self._home_mirror_dialog_no_target()
        else:
            self._home_mirror_dialog_with_target(mirror_dir)

    def _home_mirror_dialog_no_target(self):
        """Dialog shown when no mirror target is configured."""
        dlg = QDialog(self._app)
        dlg.setWindowTitle("Export to Mirror")
        dlg.setModal(True)
        dlg.setFixedWidth(460)
        dlg.setStyleSheet(
            f"background: {self._app.BG}; color: {self._app.TEXT};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        title = QLabel("Mirror target not configured")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {self._app.TEXT};")
        lay.addWidget(title)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"color: {self._app.ACCENT};")
        sep1.setFixedHeight(1)
        lay.addWidget(sep1)

        lbl = QLabel("Enter a folder path or browse:")
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        lay.addWidget(lbl)

        path_row = QHBoxLayout()
        path_entry = QLineEdit()
        path_entry.setFont(QFont("Segoe UI", 9))
        path_entry.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 8px;")
        path_row.addWidget(path_entry)

        browse_btn = QPushButton("Browse")
        browse_btn.setFont(QFont("Segoe UI", 9))
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _browse():
            folder = QFileDialog.getExistingDirectory(
                self._app, "Select Mirror Folder")
            if folder:
                path_entry.setText(folder)

        browse_btn.clicked.connect(_browse)
        path_row.addWidget(browse_btn)
        lay.addLayout(path_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {self._app.BG3};")
        lay.addWidget(sep2)

        import_btn = QPushButton("📥  Import from Mirror")
        import_btn.setFont(QFont("Segoe UI", 9))
        import_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 7px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(
            lambda: [dlg.reject(),
                     self._app._panel_archive._on_import_mirror()])
        lay.addWidget(import_btn)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {self._app.BG3};")
        lay.addWidget(sep3)

        footer_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)

        save_btn = QPushButton("Save & Continue")
        save_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT}; color: {self._app.TEXT}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _save_and_continue():
            folder = path_entry.text().strip()
            if not folder:
                QMessageBox.warning(dlg, "Mirror", "Please enter a folder path.")
                return
            s = self._app._panel_settings._collect_settings()
            s["mirror_dir"] = folder
            self._app._panel_settings._safe_save(s)
            self._app._log(f"✓ Mirror target saved: {folder}")
            dlg.accept()
            self._home_mirror_dialog_with_target(folder)

        save_btn.clicked.connect(_save_and_continue)
        footer_row.addWidget(cancel_btn)
        footer_row.addStretch()
        footer_row.addWidget(save_btn)
        lay.addLayout(footer_row)

        dlg.exec()

    def _home_mirror_dialog_with_target(self, mirror_dir: str):
        """Dialog shown when mirror target is already configured."""
        dlg = QDialog(self._app)
        dlg.setWindowTitle("Export to Mirror")
        dlg.setModal(True)
        dlg.setFixedWidth(380)
        dlg.setStyleSheet(
            f"background: {self._app.BG}; color: {self._app.TEXT};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        title = QLabel("Export to Mirror")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {self._app.TEXT};")
        lay.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        export_btn = QPushButton("📤  Export to Mirror")
        export_btn.setFont(QFont("Segoe UI", 9))
        export_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 8px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(
            lambda: [dlg.accept(),
                     self._app._panel_archive._on_mirror()])
        lay.addWidget(export_btn)

        import_btn = QPushButton("📥  Import from Mirror")
        import_btn.setFont(QFont("Segoe UI", 9))
        import_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 8px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(
            lambda: [dlg.accept(),
                     self._app._panel_archive._on_import_mirror()])
        lay.addWidget(import_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {self._app.BG3};")
        lay.addWidget(sep2)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)
        lay.addWidget(cancel_btn)

        dlg.exec()
