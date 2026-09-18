#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/custom_dashboard.py
Garmin Local Archive — Custom Dashboard Builder popup

Extracted from app/panel_outputs.py (Codereview v1.7.0.1, Baustein 1.3)
— the "Custom Dashboard" button's field-picker + date-range + format +
presets dialog, verbatim except self -> panel and two call sites:

- Non-encrypted Create -> dashboard_build.run_dashboards(...) (shared
  with dashboard_create.py's plain "Create Reports" popup — no
  duplication existed here, just relocated for symmetry).
- Encrypted Create -> dashboard_build.run_encrypted(panel, dash_runner,
  [(custom_mod, "html_mobile")], ..., log_label="Encrypted Custom
  Dashboard") — shared with encrypted_dashboards.py's own flow. Both
  popups depend only on app/popups/_dashboard_build.py, neither imports
  the other (Timo's decision, see PROTOKOLL_experiment.md 2026-09-18).

panel_outputs.py keeps a one-line delegating method
(_open_custom_dashboard_popup -> popups.custom_dashboard.open_popup(self))
so _build_ui()'s button wiring needs zero changes.
"""

from datetime import date, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QFrame, QCheckBox, QComboBox, QLineEdit, QRadioButton,
    QButtonGroup, QSpinBox, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import frozen_paths
import garmin_dashboard_presets as _presets
from ..dialogs import PasswordConfirmDialog
from . import _dashboard_build as dashboard_build


def open_popup(panel):
    """Field picker + date range + format + presets → ad-hoc dashboard.

    Builds an in-memory specialist via custom_dash_builder — no file is
    written to disk, no change to dash_runner.py needed (build() only
    requires .META / .build() / .__name__, verified against an ad-hoc
    types.ModuleType). Reuses dashboard_build.run_dashboards() exactly
    like Create Reports, with an explicit date range override.
    """
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
        import custom_dash_builder
    except Exception as exc:
        panel._app._log(
            f"✗ Custom Dashboard Builder konnte nicht geladen werden: {exc}")
        return

    try:
        available = custom_dash_builder.list_available_fields()
    except Exception as exc:
        panel._app._log(f"✗ Feldliste konnte nicht geladen werden: {exc}")
        return

    s = panel._app._panel_settings._collect_settings()

    # ── Dialog ────────────────────────────────────────────────────────────
    dlg = QDialog(panel._app)
    dlg.setWindowTitle("Custom Dashboard")
    dlg.setModal(True)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)

    title = QLabel("CUSTOM DASHBOARD")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep)

    # ── Preset row ────────────────────────────────────────────────────────
    preset_row = QHBoxLayout()
    preset_lbl = QLabel("Preset:")
    preset_lbl.setFont(QFont("Segoe UI", 8))
    preset_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    preset_combo = QComboBox()
    preset_combo.setFont(QFont("Segoe UI", 8))
    preset_combo.setStyleSheet(
        f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
        f"border: none; padding: 4px;")

    def _refresh_presets(select: str = ""):
        preset_combo.clear()
        preset_combo.addItem("— select preset —")
        for pname in sorted(_presets.load_presets().keys()):
            preset_combo.addItem(pname)
        if select:
            idx = preset_combo.findText(select)
            if idx >= 0:
                preset_combo.setCurrentIndex(idx)

    _refresh_presets()

    load_btn = QPushButton("Load")
    load_btn.setFont(QFont("Segoe UI", 8))
    load_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG2}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 5px 10px; }}")
    load_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    del_btn = QPushButton("Delete")
    del_btn.setFont(QFont("Segoe UI", 8))
    del_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG2}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 5px 10px; }}")
    del_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    preset_row.addWidget(preset_lbl)
    preset_row.addWidget(preset_combo)
    preset_row.addWidget(load_btn)
    preset_row.addWidget(del_btn)
    lay.addLayout(preset_row)

    sep_p = QFrame()
    sep_p.setFrameShape(QFrame.Shape.HLine)
    sep_p.setStyleSheet(f"color: {panel._app.BG3};")
    lay.addWidget(sep_p)

    # ── Field picker ──────────────────────────────────────────────────────
    def _field_checkbox(text: str) -> QCheckBox:
        cb = QCheckBox(text)
        cb.setFont(QFont("Segoe UI", 8))
        cb.setStyleSheet(
            f"QCheckBox {{ background: transparent; color: {panel._app.TEXT}; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; "
            f"background: {panel._app.BG3}; border: 1px solid {panel._app.TEXT2}; }}"
            f"QCheckBox::indicator:checked {{ background: {panel._app.ACCENT}; "
            f"border: 1px solid {panel._app.ACCENT}; }}"
            f"QCheckBox::indicator:hover {{ border: 1px solid {panel._app.TEXT}; }}"
        )
        return cb

    picker_widget = QWidget()
    picker_lay = QHBoxLayout(picker_widget)

    garmin_col = QVBoxLayout()
    garmin_hdr = QLabel("Garmin")
    garmin_hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
    garmin_hdr.setStyleSheet(f"color: {panel._app.TEXT};")
    garmin_col.addWidget(garmin_hdr)
    garmin_checks = {}
    for f in available["garmin"]:
        cb = _field_checkbox(f)
        garmin_col.addWidget(cb)
        garmin_checks[f] = cb
    garmin_col.addStretch()
    garmin_wrap = QWidget()
    garmin_wrap.setLayout(garmin_col)

    context_col = QVBoxLayout()
    context_hdr = QLabel("Context")
    context_hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
    context_hdr.setStyleSheet(f"color: {panel._app.TEXT};")
    context_col.addWidget(context_hdr)
    context_checks = {}
    for f in available["context"]:
        cb = _field_checkbox(f)
        context_col.addWidget(cb)
        context_checks[f] = cb
    context_col.addStretch()
    context_wrap = QWidget()
    context_wrap.setLayout(context_col)

    picker_lay.addWidget(garmin_wrap)
    picker_lay.addWidget(context_wrap)

    scroll = QScrollArea()
    scroll.setWidget(picker_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"background: {panel._app.BG}; border: none;")
    scroll.setMaximumHeight(240)
    lay.addWidget(scroll)

    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet(f"color: {panel._app.BG3};")
    lay.addWidget(sep2)

    # ── Name ──────────────────────────────────────────────────────────────
    name_row = QHBoxLayout()
    name_lbl = QLabel("Name:")
    name_lbl.setFont(QFont("Segoe UI", 8))
    name_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    name_edit = QLineEdit("Custom Dashboard")
    name_edit.setFont(QFont("Segoe UI", 9))
    name_edit.setStyleSheet(
        f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
        f"border: none; padding: 4px;")
    name_row.addWidget(name_lbl)
    name_row.addWidget(name_edit)
    lay.addLayout(name_row)

    # ── Date range ────────────────────────────────────────────────────────
    date_group     = QButtonGroup(dlg)
    radio_fixed    = QRadioButton("Fixed range")
    radio_relative = QRadioButton("Relative (days back)")
    radio_relative.setChecked(True)
    for rb in (radio_fixed, radio_relative):
        rb.setFont(QFont("Segoe UI", 8))
        rb.setStyleSheet(f"color: {panel._app.TEXT};")
        date_group.addButton(rb)
    date_radio_row = QHBoxLayout()
    date_radio_row.addWidget(radio_fixed)
    date_radio_row.addWidget(radio_relative)
    lay.addLayout(date_radio_row)

    fixed_row  = QHBoxLayout()
    from_lbl   = QLabel("From:")
    to_lbl     = QLabel("To:")
    from_edit  = QLineEdit(s.get("date_from", ""))
    from_edit.setPlaceholderText("YYYY-MM-DD")
    to_edit    = QLineEdit(s.get("date_to", ""))
    to_edit.setPlaceholderText("YYYY-MM-DD")
    for lbl in (from_lbl, to_lbl):
        lbl.setFont(QFont("Segoe UI", 8))
        lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    for e in (from_edit, to_edit):
        e.setFont(QFont("Segoe UI", 8))
        e.setStyleSheet(
            f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
            f"border: none; padding: 4px;")
    fixed_row.addWidget(from_lbl)
    fixed_row.addWidget(from_edit)
    fixed_row.addWidget(to_lbl)
    fixed_row.addWidget(to_edit)
    lay.addLayout(fixed_row)

    relative_row = QHBoxLayout()
    days_lbl = QLabel("Days back:")
    days_lbl.setFont(QFont("Segoe UI", 8))
    days_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    days_spin = QSpinBox()
    days_spin.setRange(1, 3650)
    days_spin.setValue(30)
    days_spin.setStyleSheet(
        f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
        f"border: none; padding: 4px;")
    relative_row.addWidget(days_lbl)
    relative_row.addWidget(days_spin)
    relative_row.addStretch()
    lay.addLayout(relative_row)

    def _on_date_mode_change():
        fixed_on = radio_fixed.isChecked()
        for w in (from_edit, to_edit):
            w.setEnabled(fixed_on)
        days_spin.setEnabled(not fixed_on)

    radio_fixed.toggled.connect(lambda _: _on_date_mode_change())
    _on_date_mode_change()

    # ── Formats ───────────────────────────────────────────────────────────
    fmt_row  = QHBoxLayout()
    fmt_lbl  = QLabel("Formats:")
    fmt_lbl.setFont(QFont("Segoe UI", 8))
    fmt_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
    html_cb    = QCheckBox("HTML")
    excel_cb   = QCheckBox("Excel")
    encrypt_cb = QCheckBox("🔒 Encrypt")
    html_cb.setChecked(True)
    excel_cb.setChecked(True)
    for cb in (html_cb, excel_cb, encrypt_cb):
        cb.setFont(QFont("Segoe UI", 8))
        cb.setStyleSheet(f"color: {panel._app.TEXT};")

    def _on_encrypt_toggled(checked):
        if checked:
            excel_cb.setChecked(False)
        excel_cb.setEnabled(not checked)

    encrypt_cb.toggled.connect(_on_encrypt_toggled)

    fmt_row.addWidget(fmt_lbl)
    fmt_row.addWidget(html_cb)
    fmt_row.addWidget(excel_cb)
    fmt_row.addWidget(encrypt_cb)
    fmt_row.addStretch()
    lay.addLayout(fmt_row)

    # ── Preset load / delete ──────────────────────────────────────────────

    def _load_selected_preset():
        pname = preset_combo.currentText()
        preset = _presets.load_presets().get(pname)
        if not preset:
            return
        for f, cb in garmin_checks.items():
            cb.setChecked(f in preset.get("garmin_fields", []))
        for f, cb in context_checks.items():
            cb.setChecked(f in preset.get("context_fields", []))
        name_edit.setText(pname)
        if preset.get("date_mode") == "fixed":
            radio_fixed.setChecked(True)
            from_edit.setText(preset.get("date_from", ""))
            to_edit.setText(preset.get("date_to", ""))
        else:
            radio_relative.setChecked(True)
            days_spin.setValue(preset.get("days_back", 30))
        _on_date_mode_change()
        encrypt_cb.setChecked(preset.get("encrypt", False))
        fmts = preset.get("formats", ["html_mobile", "excel"])
        html_cb.setChecked("html_mobile" in fmts)
        excel_cb.setChecked("excel" in fmts and not preset.get("encrypt", False))

    load_btn.clicked.connect(_load_selected_preset)

    def _delete_selected_preset():
        pname = preset_combo.currentText()
        if pname == "— select preset —":
            return
        answer = QMessageBox.question(
            dlg, "Delete Preset", f"Delete preset '{pname}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            _presets.delete_preset(pname)
            _refresh_presets()
        except OSError as exc:
            QMessageBox.critical(dlg, "Delete Preset", f"Could not delete: {exc}")

    del_btn.clicked.connect(_delete_selected_preset)

    # ── Bottom buttons ────────────────────────────────────────────────────
    sep3 = QFrame()
    sep3.setFrameShape(QFrame.Shape.HLine)
    sep3.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep3)

    btn_row = QHBoxLayout()

    def _collect_state():
        selected_garmin  = [f for f, cb in garmin_checks.items() if cb.isChecked()]
        selected_context = [f for f, cb in context_checks.items() if cb.isChecked()]
        formats = []
        if html_cb.isChecked():
            formats.append("html_mobile")
        if excel_cb.isChecked() and excel_cb.isEnabled():
            formats.append("excel")
        preset = {
            "garmin_fields":  selected_garmin,
            "context_fields": selected_context,
            "formats":        formats,
            "encrypt":        encrypt_cb.isChecked(),
        }
        if radio_fixed.isChecked():
            preset["date_mode"] = "fixed"
            preset["date_from"] = from_edit.text().strip()
            preset["date_to"]   = to_edit.text().strip()
        else:
            preset["date_mode"] = "relative"
            preset["days_back"] = days_spin.value()
        return preset

    def _save_preset():
        pname = name_edit.text().strip()
        if not pname:
            QMessageBox.information(dlg, "Save Preset", "Please enter a name.")
            return
        try:
            _presets.save_preset(pname, _collect_state())
            _refresh_presets(select=pname)
            panel._app._log(f"✓ Preset saved: {pname}")
        except OSError as exc:
            QMessageBox.critical(dlg, "Save Preset", f"Could not save: {exc}")

    save_btn = QPushButton("💾  Save Preset")
    save_btn.setFont(QFont("Segoe UI", 8))
    save_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG2}; color: {panel._app.TEXT2}; "
        f"border: none; padding: 6px 10px; }}")
    save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    save_btn.clicked.connect(_save_preset)

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
        state = _collect_state()
        if not state["garmin_fields"] and not state["context_fields"]:
            QMessageBox.information(dlg, "Custom Dashboard",
                                    "Please select at least one field.")
            return
        if not state["formats"]:
            QMessageBox.information(dlg, "Custom Dashboard",
                                    "Please select at least one format.")
            return
        name = name_edit.text().strip() or "Custom Dashboard"

        if state["date_mode"] == "fixed":
            custom_date_from = state["date_from"]
            custom_date_to   = state["date_to"]
            if not custom_date_from or not custom_date_to:
                QMessageBox.information(dlg, "Custom Dashboard",
                                        "Please enter both dates.")
                return
        else:
            custom_date_to   = date.today().isoformat()
            custom_date_from = (date.today() -
                                timedelta(days=state["days_back"])).isoformat()

        custom_mod = custom_dash_builder.build_ad_hoc_specialist(
            name        = name,
            description = f"{len(state['garmin_fields']) + len(state['context_fields'])} field(s) selected",
            garmin_fields  = state["garmin_fields"],
            context_fields = state["context_fields"],
        )

        if state["encrypt"]:
            pw_dlg = PasswordConfirmDialog(
                parent      = panel,
                title       = "Custom Dashboard — Encrypt",
                heading     = "🔒  Encrypted Custom Dashboard",
                description = (
                    "Builds this dashboard as HTML and encrypts it with AES-256.\n"
                    "Output folder: basedir/encrypted/"
                ),
            )
            if (pw_dlg.exec() != QDialog.DialogCode.Accepted
                    or pw_dlg.get_result() is None):
                return
            password = pw_dlg.get_result()
            dlg.accept()
            dashboard_build.run_encrypted(
                panel, dash_runner, [(custom_mod, "html_mobile")],
                custom_date_from, custom_date_to, password,
                log_label="Encrypted Custom Dashboard")
            password = None  # Passwort sofort aus dem Speicher
            return

        selections = [(custom_mod, fmt) for fmt in state["formats"]]

        dlg.accept()
        dashboard_build.run_dashboards(
            panel, dash_runner, selections,
            date_from=custom_date_from, date_to=custom_date_to)

    create_btn.clicked.connect(_build)

    btn_row.addWidget(save_btn)
    btn_row.addStretch()
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(create_btn)
    lay.addLayout(btn_row)
    dlg.exec()

