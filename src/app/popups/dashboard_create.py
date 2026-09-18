#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/dashboard_create.py
Garmin Local Archive — Create Reports popup

Extracted from app/panel_outputs.py (Codereview v1.7.0.1, Baustein 1.2)
— the "Create Reports" button's dashboard-selection grid dialog,
verbatim except self -> panel (module-level function taking the owning
PanelOutputs instance as an explicit parameter, same shape as
app/popups/capability_scan.py).

panel_outputs.py keeps a one-line delegating method
(_open_dashboard_popup -> popups.dashboard_create.open_popup(self)) so
_build_ui()'s button wiring needs zero changes.

Calls dashboard_build.run_dashboards(panel, dash_runner, selections) on
Create (Codereview v1.7.0.1, Baustein 1.5 follow-up) — that function
moved off PanelOutputs into the shared app/popups/_dashboard_build.py,
also used by custom_dashboard.py's non-encrypted branch. Originally
this called panel._run_dashboards(...) directly; updated when 1.5 moved
that method off PanelOutputs.
"""

import frozen_paths

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QFrame, QGridLayout, QScrollArea, QCheckBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from . import _dashboard_build as dashboard_build


def open_popup(panel):
    """Scan specialists, show selection dialog, build selected dashboards."""
    import importlib.util as _ilu

    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "dashboards", "layouts", "maps")

    try:
        runner_path = root / "dashboards" / "dash_runner.py"
        spec = _ilu.spec_from_file_location("dash_runner", runner_path)
        if spec is None:
            raise FileNotFoundError(
                f"dash_runner.py nicht gefunden: {runner_path}")
        dash_runner = _ilu.module_from_spec(spec)
        spec.loader.exec_module(dash_runner)
    except Exception as exc:
        panel._app._log(
            f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
        return

    try:
        specialists = dash_runner.scan()
    except Exception as exc:
        panel._app._log(f"✗ scan() fehlgeschlagen: {exc}")
        return
    if not specialists:
        QMessageBox.information(panel._app, "Create Reports",
                                "No dashboards found in dashboards/")
        return

    # ── Dialog ────────────────────────────────────────────────────────────
    dlg = QDialog(panel._app)
    dlg.setWindowTitle("Create Reports")
    dlg.setModal(True)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)

    title = QLabel("CREATE REPORTS")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep)

    all_formats = []
    for sp in specialists:
        for fmt in sp["formats"]:
            if fmt not in all_formats:
                all_formats.append(fmt)

    grid_widget = QWidget()
    # Bug fix: do NOT set background: transparent — in Qt6 on Windows this
    # causes the widget to fail hit-testing, making individual checkboxes
    # unresponsive while the parent dialog still receives click events.
    grid = QGridLayout(grid_widget)
    grid.setSpacing(4)

    # Header row
    hdr = QLabel("Dashboard")
    hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
    hdr.setStyleSheet(f"color: {panel._app.TEXT};")
    grid.addWidget(hdr, 0, 0)
    for col_idx, fmt in enumerate(all_formats, start=1):
        lbl = QLabel(dash_runner.display_label(fmt).upper())
        lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {panel._app.TEXT};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(lbl, 0, col_idx)

    check_vars = {}
    for row_idx, spec in enumerate(specialists, start=1):
        name_lbl = QLabel(
            f"{spec['name']} — {spec['description'][:45]}")
        name_lbl.setFont(QFont("Segoe UI", 8))
        name_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
        grid.addWidget(name_lbl, row_idx, 0)
        for col_idx, fmt in enumerate(all_formats, start=1):
            if fmt in spec["formats"]:
                cb = QCheckBox()
                # Full indicator stylesheet required — Qt6 on Windows disables
                # native hit-testing on checkboxes that inherit a background
                # from a styled QDialog parent. Explicit sizing + all states
                # restores click behaviour.
                cb.setStyleSheet(
                    f"QCheckBox {{ background: transparent; }}"
                    f"QCheckBox::indicator {{"
                    f"  width: 14px; height: 14px;"
                    f"  background: {panel._app.BG3};"
                    f"  border: 1px solid {panel._app.TEXT2};"
                    f"}}"
                    f"QCheckBox::indicator:checked {{"
                    f"  background: {panel._app.ACCENT};"
                    f"  border: 1px solid {panel._app.ACCENT};"
                    f"}}"
                    f"QCheckBox::indicator:hover {{"
                    f"  border: 1px solid {panel._app.TEXT};"
                    f"}}"
                )
                grid.addWidget(cb, row_idx, col_idx,
                               Qt.AlignmentFlag.AlignCenter)
                check_vars[(row_idx - 1, fmt)] = cb
            else:
                dash = QLabel("—")
                dash.setFont(QFont("Segoe UI", 8))
                dash.setStyleSheet("color: #555555;")
                dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(dash, row_idx, col_idx)

    scroll = QScrollArea()
    scroll.setWidget(grid_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"background: {panel._app.BG}; border: none;")
    scroll.setMaximumHeight(300)
    lay.addWidget(scroll)

    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep2)

    btn_row = QHBoxLayout()
    _all_selected = [False]

    toggle_btn = QPushButton("☐  Select All")
    toggle_btn.setFont(QFont("Segoe UI", 8))
    toggle_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG2}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 6px 8px; }}")
    toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _toggle_all():
        _all_selected[0] = not _all_selected[0]
        for cb in check_vars.values():
            cb.setChecked(_all_selected[0])
        toggle_btn.setText(
            "☑  Deselect All" if _all_selected[0] else "☐  Select All")

    toggle_btn.clicked.connect(_toggle_all)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    cancel_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG2}; color: {panel._app.TEXT}; "
        f"border: none; padding: 6px 14px; }}")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel_btn.clicked.connect(dlg.reject)

    create_btn = QPushButton("📊 Create")
    create_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    create_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.ACCENT2}; "
        f"color: {panel._app.TEXT}; border: none; padding: 6px 14px; }}")
    create_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _build():
        selections = []
        for (spec_idx, fmt), cb in check_vars.items():
            if cb.isChecked():
                selections.append((specialists[spec_idx]["module"], fmt))
        if not selections:
            QMessageBox.information(dlg, "Create Reports",
                                    "Please select at least one format.")
            return
        dlg.accept()
        dashboard_build.run_dashboards(panel, dash_runner, selections)

    create_btn.clicked.connect(_build)

    btn_row.addWidget(toggle_btn)
    btn_row.addStretch()
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(create_btn)
    lay.addLayout(btn_row)
    dlg.exec()
