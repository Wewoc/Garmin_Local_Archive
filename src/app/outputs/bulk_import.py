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

v1.7.6 (6b): after the path, a small dialog asks which parts to import (daily
values / heart-rate series) and offers a preview. The choice goes to
garmin_collector.main() in two more variables (GARMIN_BULK_PHASES,
GARMIN_BULK_DRYRUN) — BULK-IMPORT-PHASES, removable.

v1.7.6.1: both parts go to garmin_data/bulk (the daily values to bulk/aggregates, no
longer to raw/); both have a preview.
"""

import os

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

# Everything the import sets in os.environ. T3 runs main() in this process, so all of
# them are removed after the run (see _on_import_done).
TRIGGER_VARS = ("GARMIN_IMPORT_PATH", "GARMIN_BULK_PHASES", "GARMIN_BULK_DRYRUN")


def build_env(path, json_phase, intraday_phase, dry_run):
    """The env_overrides of the collector run. Phases in the order the collector uses."""
    phases = [name for name, on in (("json", json_phase), ("intraday", intraday_phase)) if on]
    env = {"GARMIN_IMPORT_PATH": str(path), "GARMIN_BULK_PHASES": ",".join(phases)}
    if dry_run:
        env["GARMIN_BULK_DRYRUN"] = "1"
    return env


class ImportOptionsDialog(QDialog):
    """Which parts of the export to import — or a preview. options() is None until Preview/Import."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Bulk Export")
        self._result = None

        self.json_box = QCheckBox("Daily values (JSON)")
        self.json_box.setChecked(True)
        self.intraday_box = QCheckBox("Heart-rate series (FIT files)")
        self.intraday_box.setChecked(True)
        hint = QLabel("The data of the export are stored in garmin_data/bulk, separate from the data of the Garmin API.")
        hint.setWordWrap(True)

        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setToolTip("Reads the export and reports what an import would do. Writes nothing.")
        self.import_btn = QPushButton("Import")
        self.cancel_btn = QPushButton("Cancel")
        self.preview_btn.clicked.connect(lambda: self._finish(True))
        self.import_btn.clicked.connect(lambda: self._finish(False))
        self.cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for btn in (self.preview_btn, self.import_btn, self.cancel_btn):
            buttons.addWidget(btn)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("What do you want to import?"))
        layout.addWidget(self.json_box)
        layout.addWidget(self.intraday_box)
        layout.addWidget(hint)
        layout.addLayout(buttons)

    def _finish(self, preview):
        self._result = {
            "json": self.json_box.isChecked(),
            "intraday": self.intraday_box.isChecked(),
            "preview": preview,
        }
        self.accept()

    def options(self):
        return self._result


def _ask_options(app):
    """Shows the dialog. Returns {"json", "intraday", "preview"} or None (cancelled)."""
    dlg = ImportOptionsDialog(app)
    dlg.exec()
    return dlg.options()


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

    options = _ask_options(app)
    if options is None:
        return
    json_phase, intraday_phase, preview = options["json"], options["intraday"], options["preview"]
    if not json_phase and not intraday_phase:
        QMessageBox.information(app, "Import Bulk Export", "Nothing selected — nothing to import.")
        return
    if not preview:
        confirm = QMessageBox.question(
            app, "Import Bulk Export",
            "The data of the export are stored in garmin_data/bulk.\n\n"
            "That folder is part of the backup and of the mirror: the new files are backed up "
            "right after the import. The export file stays your fallback — keep it.\n\nStart the import?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

    # A preview writes nothing, so it leaves the timer alone.
    timer_was_active = False
    if not preview:
        timer_was_active = app._timer_active
        if app._timer_active:
            app._log("⏱  Background timer paused for import.")
            app._timer_stop.set()
            app._timer_active = False
            app._dispatch(app._panel_timer._timer_update_btn)

    app._log(f"   Source: {path}")
    if preview:
        app._log("   Preview — nothing is written.")

    def _on_import_done():
        # T3: the trigger variables live in os.environ of the GUI process.
        # Pop them before the timer resumes — otherwise the next timer-triggered
        # _run() would re-enter the import path instead of the normal sync.
        for name in TRIGGER_VARS:
            os.environ.pop(name, None)
        app._panel_timer._timer_resume_after_sync(timer_was_active)
        app._panel_archive._refresh_archive_info()

    app._run(
        "garmin_collector.py",
        enable_stop=True,
        log_prefix="garmin_bulk",
        env_overrides=build_env(path, json_phase, intraday_phase, preview),
        on_done=_on_import_done,
    )
