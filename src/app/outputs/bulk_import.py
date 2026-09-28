#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/bulk_import.py
Garmin Local Archive — Import Bulk Export

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 2) — verbatim
except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps a one-line delegating method (_run_import ->
bulk_import.run_import(self)) so _build_ui()'s button wiring needs zero
changes.
"""

import os

from PyQt6.QtWidgets import QMessageBox, QFileDialog


def run_import(panel):
    """Open file dialog and run bulk import."""
    app = panel._app

    answer = QMessageBox.question(
        app, "Import Bulk Export",
        "Select ZIP file?\n\nYes = ZIP file\nNo = unpacked folder",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if answer == QMessageBox.StandardButton.Yes:
        path, _ = QFileDialog.getOpenFileName(
            app, "Select Garmin Export ZIP",
            filter="ZIP files (*.zip);;All files (*.*)")
    else:
        path = QFileDialog.getExistingDirectory(
            app, "Select unpacked Garmin Export folder")
    if not path:
        return

    timer_was_active = app._timer_active
    if app._timer_active:
        app._log("⏱  Background timer paused for import.")
        app._timer_stop.set()
        app._timer_active = False
        app._dispatch(app._panel_timer._timer_update_btn)

    app._log(f"   Source: {path}")

    def _on_import_done():
        # T3: GARMIN_IMPORT_PATH lives in os.environ of the GUI process.
        # Pop it before the timer resumes — otherwise the next timer-triggered
        # _run() would re-enter the import path instead of the normal sync.
        os.environ.pop("GARMIN_IMPORT_PATH", None)
        app._panel_timer._timer_resume_after_sync(timer_was_active)
        app._panel_archive._refresh_archive_info()

    app._run(
        "garmin_collector.py",
        enable_stop=True,
        log_prefix="garmin_bulk",
        env_overrides={"GARMIN_IMPORT_PATH": path},
        on_done=_on_import_done,
    )
