#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/capability_scan.py
Garmin Local Archive — API Capability Scan popup

Extracted from app/panel_outputs.py (Codereview v1.7.0.1, Baustein 1.1)
— the "API Scan" button's chooser dialog (Start Scan / Edit Config /
Clear Config) and its three sub-dialogs, verbatim except self -> panel
(module-level functions taking the owning PanelOutputs instance as an
explicit parameter, instead of bound methods — same shape as every
other extracted popup in this package).

panel_outputs.py keeps a one-line delegating method
(_open_capability_scan_popup -> popups.capability_scan.open_popup(self))
so _build_ui()'s button wiring and any external caller needs zero
changes. Static import (app/panel_outputs.py imports this module by
name), not a dynamic plugin registry — Timo's decision, see
PROTOKOLL_experiment.md 2026-09-18 ("langfristig stabiler, nichts
laeuft unbemerkt aus dem Ruder").

Three sub-dialogs (Start Scan / Edit Config / Clear Config) stay
together in this one file, not split further — they are small and
tightly coupled around the same garmin_api_capability config, splitting
them individually would be finer-grained than useful.
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QFrame, QSizePolicy, QScrollArea, QCheckBox, QSpinBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


def open_popup(panel):
    """API Capability Scan — chooser dialog: Start Scan / Edit Config / Clear Config."""
    dlg = QDialog(panel._app)
    dlg.setWindowTitle("API Capability Scan")
    dlg.setModal(True)
    dlg.setFixedWidth(420)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    title = QLabel("API CAPABILITY SCAN")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep)

    body = QLabel(
        "Discovers which of 19 optional Garmin health endpoints return\n"
        "real data for this account. The 15 standard endpoints always\n"
        "run — this only adds extra fields you opt in to.")
    body.setFont(QFont("Segoe UI", 8))
    body.setStyleSheet(f"color: {panel._app.TEXT2};")
    body.setWordWrap(True)
    lay.addWidget(body)

    def _action(fn):
        dlg.accept()
        fn()

    start_btn = panel._action_btn(
        "▶  Start Scan", panel._app.ACCENT, panel._app.TEXT,
        lambda: _action(lambda: _start_scan_dialog(panel)))
    edit_btn = panel._action_btn(
        "☑  Edit Config", panel._app.BG3, panel._app.TEXT,
        lambda: _action(lambda: _edit_config_dialog(panel)))
    clear_btn = panel._action_btn(
        "🗑  Clear Config", panel._app.BG3, panel._app.TEXT2,
        lambda: _action(lambda: _clear_config_dialog(panel)))
    for b in (start_btn, edit_btn, clear_btn):
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(b)

    close_btn = QPushButton("Close")
    close_btn.setFont(QFont("Segoe UI", 9))
    close_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG3}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 6px 14px; }}")
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    close_btn.clicked.connect(dlg.reject)
    lay.addWidget(close_btn)

    dlg.exec()


def _start_scan_dialog(panel):
    """Scan-window input, then runs garmin_collector.py in Capability Scan
    mode via the same subprocess mechanism as Sync Garmin (panel._app._run)
    — no separate login/UI code needed here, garmin_collector.py's own
    '0b. Capability Scan mode' branch handles login independently."""
    dlg = QDialog(panel._app)
    dlg.setWindowTitle("Start Capability Scan")
    dlg.setModal(True)
    dlg.setFixedWidth(360)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    title = QLabel("START CAPABILITY SCAN")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)

    body = QLabel(
        "Probes each candidate endpoint over the last N days.\n"
        "Payload is discarded — only found/not found is kept.")
    body.setFont(QFont("Segoe UI", 8))
    body.setStyleSheet(f"color: {panel._app.TEXT2};")
    body.setWordWrap(True)
    lay.addWidget(body)

    win_row = QHBoxLayout()
    win_lbl = QLabel("Scan window (days):")
    win_lbl.setFont(QFont("Segoe UI", 9))
    win_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    win_row.addWidget(win_lbl)
    spin = QSpinBox()
    spin.setRange(1, 30)
    spin.setValue(7)
    spin.setStyleSheet(
        f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
        f"border: none; padding: 3px;")
    win_row.addWidget(spin)
    win_row.addStretch()
    lay.addLayout(win_row)

    def _start():
        window_days = spin.value()
        dlg.accept()
        panel._app._log(
            f"🔍  API Capability Scan starting — window {window_days} day(s) ...")

        def _on_done():
            panel._app._log(
                "✓ API Capability Scan finished — see console/log for per-endpoint results.")

        panel._app._run(
            "garmin_collector.py", enable_stop=True,
            env_overrides={
                "GARMIN_CAPABILITY_SCAN": "1",
                "GARMIN_CAPABILITY_WINDOW_DAYS": str(window_days),
            },
            on_done=_on_done,
        )

    run_btn = QPushButton("Run Scan")
    run_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    run_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.ACCENT}; color: {panel._app.TEXT}; "
        f"border: none; padding: 7px 16px; }}")
    run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    run_btn.clicked.connect(_start)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    cancel_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG3}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 7px 16px; }}")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel_btn.clicked.connect(dlg.reject)

    btn_row = QHBoxLayout()
    btn_row.addWidget(run_btn)
    btn_row.addWidget(cancel_btn)
    lay.addLayout(btn_row)

    dlg.exec()


def _edit_config_dialog(panel):
    """Checkbox list of confirmed ('found') candidates — toggle
    enabled_by_user, then save. Only endpoints already confirmed present
    for this account are shown; nothing here can enable an endpoint that
    was never confirmed (garmin_collector's double-gate — enabled_by_user
    AND status == 'found' — relies on that)."""
    try:
        s = panel._app._panel_settings._collect_settings()
        os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
        import importlib
        import garmin_config as _cfg
        importlib.reload(_cfg)
        import garmin_api_capability as capability
        config = capability.load_config()
    except Exception as exc:
        QMessageBox.critical(panel._app, "Edit Config", f"Could not read config:\n{exc}")
        return

    found = [
        ep for ep in capability.CANDIDATE_ENDPOINTS
        if config.get("endpoints", {}).get(ep, {}).get("status") == "found"
    ]

    dlg = QDialog(panel._app)
    dlg.setWindowTitle("Edit Capability Config")
    dlg.setModal(True)
    dlg.setFixedWidth(420)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)

    title = QLabel("EDIT CAPABILITY CONFIG")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep)

    if not found:
        empty = QLabel("No confirmed endpoints yet — run Start Scan first.")
        empty.setFont(QFont("Segoe UI", 9))
        empty.setStyleSheet(f"color: {panel._app.TEXT2};")
        empty.setWordWrap(True)
        lay.addWidget(empty)
        close_btn = QPushButton("Close")
        close_btn.setFont(QFont("Segoe UI", 9))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {panel._app.BG3}; color: {panel._app.TEXT2}; "
            f"border: none; padding: 6px 14px; }}")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dlg.reject)
        lay.addWidget(close_btn)
        dlg.exec()
        return

    check_vars = {}
    list_widget = QWidget()
    list_widget.setStyleSheet(f"background: {panel._app.BG};")
    list_lay = QVBoxLayout(list_widget)
    list_lay.setSpacing(4)
    for ep in found:
        row = QHBoxLayout()
        cb = QCheckBox()
        cb.setChecked(bool(config["endpoints"][ep].get("enabled_by_user")))
        cb.setStyleSheet(
            f"QCheckBox {{ background: transparent; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; "
            f"background: {panel._app.BG3}; border: 1px solid {panel._app.TEXT2}; }}"
            f"QCheckBox::indicator:checked {{ background: {panel._app.ACCENT}; "
            f"border: 1px solid {panel._app.ACCENT}; }}"
            f"QCheckBox::indicator:hover {{ border: 1px solid {panel._app.TEXT}; }}")
        lbl = QLabel(ep)
        lbl.setFont(QFont("Segoe UI", 8))
        lbl.setStyleSheet(f"color: {panel._app.TEXT};")
        row.addWidget(cb)
        row.addWidget(lbl)
        row.addStretch()
        list_lay.addLayout(row)
        check_vars[ep] = cb

    scroll = QScrollArea()
    scroll.setWidget(list_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"background: {panel._app.BG}; border: none;")
    scroll.setMaximumHeight(260)
    lay.addWidget(scroll)

    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep2)

    def _save():
        updated = config
        for ep, cb in check_vars.items():
            updated = capability.update_endpoint(
                updated, ep, "found", enabled_by_user=cb.isChecked())
        if capability.save_config(updated):
            enabled_count = sum(1 for cb in check_vars.values() if cb.isChecked())
            panel._app._log(
                f"✓ Capability config saved — {enabled_count} endpoint(s) enabled")
            dlg.accept()
        else:
            QMessageBox.critical(dlg, "Edit Config", "Could not save config — see log.")

    save_btn = QPushButton("Save")
    save_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    save_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.ACCENT}; color: {panel._app.TEXT}; "
        f"border: none; padding: 7px 16px; }}")
    save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    save_btn.clicked.connect(_save)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    cancel_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG3}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 7px 16px; }}")
    cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel_btn.clicked.connect(dlg.reject)

    btn_row = QHBoxLayout()
    btn_row.addWidget(save_btn)
    btn_row.addWidget(cancel_btn)
    lay.addLayout(btn_row)

    dlg.exec()


def _clear_config_dialog(panel):
    """Confirm, then reset the capability config to defaults. The 15
    baseline endpoints are never touched — this only clears optional-
    endpoint discovery data via garmin_api_capability.reset_config()."""
    answer = QMessageBox.question(
        panel._app, "Clear Capability Config",
        "This resets all 19 candidate endpoints to their default state\n"
        "(not observed, disabled). The 15 standard endpoints are never\n"
        "affected — this only clears optional-endpoint discovery data.\n\n"
        "Continue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    try:
        s = panel._app._panel_settings._collect_settings()
        os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
        import importlib
        import garmin_config as _cfg
        importlib.reload(_cfg)
        import garmin_api_capability as capability
        ok = capability.save_config(capability.reset_config())
    except Exception as exc:
        QMessageBox.critical(panel._app, "Clear Config", f"Could not reset config:\n{exc}")
        return

    if ok:
        panel._app._log("✓ Capability config cleared — all candidates reset to defaults")
    else:
        QMessageBox.critical(panel._app, "Clear Config", "Could not save config — see log.")
