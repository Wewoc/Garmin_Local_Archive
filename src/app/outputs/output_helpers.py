#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/output_helpers.py
Garmin Local Archive — Output Panel: folder/log/task-scheduler helpers

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 1) — verbatim
except self -> panel (module-level functions taking the owning
PanelOutputs instance as an explicit parameter), same shape as
app/popups/*.py.

panel_outputs.py keeps one-line delegating methods so _build_ui()'s
button wiring and the direct panel._method() calls in test_qt_app.py
need zero changes.
"""

import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QLineEdit, QMessageBox, QFileDialog,
    QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import frozen_paths


def open_data_folder(panel):
    folder = Path(panel._app._panel_settings._collect_settings()["base_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder))


def copy_last_error_log(panel):
    fail_dir = (
        Path(panel._app._panel_settings._collect_settings()["base_dir"])
        / "garmin_data" / "log" / "fail"
    )
    if not fail_dir.exists():
        panel._app._log("✗ No error logs found (log/fail/ does not exist).")
        return
    logs = sorted(fail_dir.glob("garmin_*.log"),
                  key=lambda f: f.stat().st_mtime)
    if not logs:
        panel._app._log("✓ No error logs — no failed sessions recorded.")
        return
    latest = logs[-1]
    try:
        content = latest.read_text(encoding="utf-8")
        QApplication.clipboard().setText(content)
        panel._app._log(
            f"✓ Error log copied to clipboard ({latest.name})")
    except Exception as e:
        panel._app._log(f"✗ Could not read error log: {e}")


def open_local_config(panel):
    """Open local_config.csv in default editor. Create if missing."""
    import garmin_config as cfg
    csv_path = cfg.LOCAL_CONFIG_FILE
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "date_from;date_to;country;place;latitude;longitude\n",
            encoding="utf-8"
        )
        readme_path = csv_path.parent / "local_config_README.txt"
        if not readme_path.exists():
            readme_path.write_text(
                "Garmin Local Archive — Location Config\n"
                "======================================\n\n"
                "Edit local_config.csv to define your location per time period.\n\n"
                "Columns:\n"
                "  date_from   : YYYY-MM-DD — start of period\n"
                "  date_to     : YYYY-MM-DD — end of period\n"
                "  country     : English name (e.g. Germany, Spain, France)\n"
                "  place       : City or town name (e.g. Herford, Palma de Mallorca)\n"
                "  latitude    : Filled automatically — leave empty\n"
                "  longitude   : Filled automatically — leave empty\n\n"
                "Example row:\n"
                "  2025-07-14,2025-07-21,Spain,Palma de Mallorca,,\n\n"
                "Leave latitude and longitude empty.\n"
                "The app fills them automatically on next Context Sync.\n"
                "If no entry matches a date, the app uses the location from Settings.\n",
                encoding="utf-8"
            )
    os.startfile(csv_path)


def create_task_scheduler_xml(panel):
    """Generate a configured daily_update_task.xml for Windows Task Scheduler."""
    app = panel._app

    # NOTE: this file lives one level deeper than the original
    # (app/outputs/output_helpers.py vs. app/panel_outputs.py), so the
    # dev-path fallback needs an extra .parent to reach the same repo
    # root (scripts_root/src) the original reached with .parent.parent.
    _exe_dir = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                else Path(__file__).parent.parent.parent)

    template_path = frozen_paths.doc_path("daily_update_task.xml")
    if template_path is None:
        QMessageBox.critical(
            app, "Task Scheduler XML",
            "Template file 'daily_update_task.xml' not found.\n"
            "Expected in scheduler/ (dev) or info/ (build).",
        )
        return

    # ── Dialog ────────────────────────────────────────────────────────────
    dlg = QDialog(app)
    dlg.setWindowTitle("Create Task Scheduler XML")
    dlg.setModal(True)
    dlg.setFixedWidth(480)
    dlg.setStyleSheet(f"background: {app.BG}; color: {app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(20, 16, 20, 16)
    lay.setSpacing(8)

    title = QLabel("Create Task Scheduler XML")
    title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
    lay.addWidget(title)
    body = QLabel(
        "Select your build target and entry point path.\n"
        "The XML will be saved ready to import into Windows Task Scheduler."
    )
    body.setFont(QFont("Segoe UI", 9))
    body.setStyleSheet(f"color: {app.TEXT2};")
    body.setWordWrap(True)
    lay.addWidget(body)

    lay.addWidget(QLabel("Build target:", font=QFont("Segoe UI", 9)))

    btn_group = QButtonGroup(dlg)
    radio_T2  = QRadioButton("T2 — Standard EXE  (daily_update.bat)")
    radio_T3  = QRadioButton("T3 — Standalone EXE  (daily_update.exe)")
    radio_T1  = QRadioButton("T1 — Dev  (python daily_update.py)")
    radio_T2.setChecked(True)
    for rb in (radio_T2, radio_T3, radio_T1):
        rb.setFont(QFont("Segoe UI", 9))
        rb.setStyleSheet(f"color: {app.TEXT};")
        btn_group.addButton(rb)
        lay.addWidget(rb)

    def _default_path(target: str) -> str:
        if target == "T2":
            p = _exe_dir / "scheduler" / "daily_update.bat"
        elif target == "T3":
            p = _exe_dir / "daily_update.exe"
        else:
            return ""
        return str(p) if p.exists() else ""

    lay.addWidget(QLabel("Entry point path:", font=QFont("Segoe UI", 9)))
    path_row = QHBoxLayout()
    path_entry = QLineEdit(_default_path("T2"))
    path_entry.setFont(QFont("Segoe UI", 9))
    path_entry.setStyleSheet(
        f"background: {app.BG3}; color: {app.TEXT}; "
        f"border: none; padding: 4px;")
    path_row.addWidget(path_entry)

    def _on_target_change():
        if radio_T2.isChecked():
            path_entry.setText(_default_path("T2"))
        elif radio_T3.isChecked():
            path_entry.setText(_default_path("T3"))
        else:
            path_entry.setText("")

    for rb in (radio_T2, radio_T3, radio_T1):
        rb.toggled.connect(lambda _: _on_target_change())

    browse_btn = QPushButton("…")
    browse_btn.setFixedWidth(28)
    browse_btn.setStyleSheet(
        f"QPushButton {{ background: {app.ACCENT2}; "
        f"color: {app.TEXT}; border: none; padding: 4px; }}")
    browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _browse():
        if radio_T2.isChecked():
            ft = "Batch files (*.bat);;All files (*.*)"
        elif radio_T3.isChecked():
            ft = "Executable (*.exe);;All files (*.*)"
        else:
            ft = "Python files (*.py);;All files (*.*)"
        p, _ = QFileDialog.getOpenFileName(
            dlg, "Select entry point", filter=ft)
        if p:
            path_entry.setText(p)

    browse_btn.clicked.connect(_browse)
    path_row.addWidget(browse_btn)
    lay.addLayout(path_row)

    warn = QLabel(
        "⚠  For T1 (Dev): enter the full path to python.exe followed by\n"
        "   the full path to daily_update.py, separated by a space."
    )
    warn.setFont(QFont("Segoe UI", 7))
    warn.setStyleSheet(f"color: {app.YELLOW};")
    lay.addWidget(warn)

    btn_row = QHBoxLayout()

    def _generate():
        entry = path_entry.text().strip()
        if not entry:
            QMessageBox.warning(dlg, "Task Scheduler XML",
                                "Please enter the entry point path.")
            return
        try:
            xml = template_path.read_text(encoding="utf-16")
        except UnicodeError:
            xml = template_path.read_text(encoding="utf-8")

        working_dir = str(Path(entry.split()[0]).parent)
        xml = xml.replace("{ENTRY_POINT_PATH}", entry)
        xml = xml.replace("<WorkingDirectory></WorkingDirectory>",
                          f"<WorkingDirectory>{working_dir}</WorkingDirectory>")

        save_path, _ = QFileDialog.getSaveFileName(
            dlg, "Save Task Scheduler XML",
            "daily_update_task.xml",
            "XML files (*.xml);;All files (*.*)",
        )
        if not save_path:
            return
        try:
            Path(save_path).write_text(xml, encoding="utf-16")
            QMessageBox.information(
                dlg, "Task Scheduler XML",
                f"Saved to:\n{save_path}\n\n"
                "Import via Task Scheduler → Action → Import Task…",
            )
            dlg.accept()
        except OSError as exc:
            QMessageBox.critical(dlg, "Task Scheduler XML",
                                 f"Could not write file:\n{exc}")

    gen_btn = QPushButton("Generate & Save")
    gen_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    gen_btn.setStyleSheet(
        f"QPushButton {{ background: {app.ACCENT}; "
        f"color: {app.TEXT}; border: none; padding: 7px 16px; }}")
    gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    gen_btn.clicked.connect(_generate)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    cancel_btn.setStyleSheet(
        f"QPushButton {{ background: {app.BG3}; "
        f"color: {app.TEXT2}; border: none; padding: 7px 16px; }}")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel_btn.clicked.connect(dlg.reject)

    btn_row.addWidget(gen_btn)
    btn_row.addWidget(cancel_btn)
    lay.addLayout(btn_row)
    dlg.exec()
