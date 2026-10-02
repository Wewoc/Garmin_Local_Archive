#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/export_data.py
Garmin Local Archive — Export Data popup

"Export Data" button's adapter-selection grid dialog — same shape as
dashboard_create.py's "Create Dashboards" popup (rows = adapter modules
discovered by export_runner.scan()), but columns are the three data
categories to include (Health, Context, Metadata) instead of output
formats, since each export adapter module already is one fixed output
format (no separate plotter step, see ROADMAP.md v1.7.4).

Each (adapter, category) checkbox is independently togglable — one
adapter can export a different domain/metadata combination than
another in the same run (export_runner.build()'s
(module, domains, include_metadata) selections, mirroring dash_runner's
(specialist, format) pairs).

Calls _export_build.run_export(panel, export_runner, selections, output_path)
on Export.
"""

from pathlib import Path

import frozen_paths

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QDialog, QFrame, QGridLayout, QScrollArea, QCheckBox,
    QMessageBox, QFileDialog, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from . import _export_build as export_build

# Column order fixed here — later a fourth "fit" column is added once
# the FIT Pipeline (v1.8.0) registers a domain broker on gateway_map.
_CATEGORIES = [("health", "Health"), ("context", "Context"), ("metadata", "Metadata")]


def open_popup(panel):
    """Scan export adapters, show selection dialog, run selected export."""
    import importlib.util as _ilu

    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "exports", "maps")

    try:
        runner_path = root / "exports" / "export_runner.py"
        spec = _ilu.spec_from_file_location("export_runner", runner_path)
        if spec is None:
            raise FileNotFoundError(f"export_runner.py nicht gefunden: {runner_path}")
        export_runner = _ilu.module_from_spec(spec)
        spec.loader.exec_module(export_runner)
    except Exception as exc:
        panel._app._log(f"✗ Export runner konnte nicht geladen werden: {exc}")
        return

    try:
        adapters = export_runner.scan()
    except Exception as exc:
        panel._app._log(f"✗ scan() fehlgeschlagen: {exc}")
        return
    if not adapters:
        QMessageBox.information(panel._app, "Export Data",
                                "No export adapters found in exports/export_adapters/")
        return

    # v1.7.4 Baustein 25: read back the saved Daily Sync selection (if any)
    # so the popup reflects its own last-saved state on reopen instead of
    # always opening blank — previously nothing read export_auto_run back.
    saved_cfg = panel._app.settings.get("export_auto_run") or {}
    saved_by_id = {
        entry.get("adapter"): entry
        for entry in saved_cfg.get("selections", [])
    }

    # ── Dialog ────────────────────────────────────────────────────────────
    dlg = QDialog(panel._app)
    dlg.setWindowTitle("Export Data")
    dlg.setModal(True)
    dlg.setStyleSheet(f"background: {panel._app.BG}; color: {panel._app.TEXT};")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)

    title = QLabel("EXPORT DATA")
    title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    title.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(title)
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep)

    # ── Grid: rows = adapters, columns = health/context/metadata ──────────
    grid_widget = QWidget()
    # Bug fix note from dashboard_create.py applies here too — do NOT set
    # background: transparent, breaks checkbox hit-testing on Qt6/Windows.
    grid = QGridLayout(grid_widget)
    grid.setSpacing(4)

    hdr = QLabel("Format")
    hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
    hdr.setStyleSheet(f"color: {panel._app.TEXT};")
    grid.addWidget(hdr, 0, 0)
    for col_idx, (_, label) in enumerate(_CATEGORIES, start=1):
        lbl = QLabel(label.upper())
        lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {panel._app.TEXT};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(lbl, 0, col_idx)

    # Shared by the grid checkboxes and the Daily Sync enable checkbox
    # below (Baustein 25) — was duplicated inline per grid cell before.
    checkbox_style = (
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

    check_vars = {}
    for row_idx, adapter in enumerate(adapters, start=1):
        name_lbl = QLabel(f"{adapter['name']} — {adapter['description'][:45]}")
        name_lbl.setFont(QFont("Segoe UI", 8))
        name_lbl.setStyleSheet(f"color: {panel._app.TEXT};")
        grid.addWidget(name_lbl, row_idx, 0)
        saved_entry = saved_by_id.get(adapter["id"])
        for col_idx, (category_key, _) in enumerate(_CATEGORIES, start=1):
            cb = QCheckBox()
            cb.setStyleSheet(checkbox_style)
            if saved_entry:
                if category_key == "metadata":
                    cb.setChecked(bool(saved_entry.get("metadata")))
                else:
                    cb.setChecked(category_key in saved_entry.get("domains", []))
            grid.addWidget(cb, row_idx, col_idx, Qt.AlignmentFlag.AlignCenter)
            check_vars[(row_idx - 1, category_key)] = cb

    scroll = QScrollArea()
    scroll.setWidget(grid_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"background: {panel._app.BG}; border: none;")
    scroll.setMaximumHeight(220)
    lay.addWidget(scroll)

    sep2 = QFrame()
    sep2.setFrameShape(QFrame.Shape.HLine)
    sep2.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep2)

    # ── Output folder ───────────────────────────────────────────────────────
    path_row = QHBoxLayout()
    path_row.setSpacing(8)
    path_lbl = QLabel("Output folder")
    path_lbl.setFont(QFont("Segoe UI", 9))
    path_lbl.setStyleSheet(f"color: {panel._app.TEXT2};")
    path_lbl.setFixedWidth(90)

    s = panel._app._panel_settings._collect_settings()
    default_path = saved_cfg.get("path") or str(Path(s["base_dir"]) / "export")

    path_entry = QLineEdit(default_path)
    path_entry.setFont(QFont("Segoe UI", 9))
    path_entry.setStyleSheet(
        f"background: {panel._app.BG3}; color: {panel._app.TEXT}; "
        f"border: none; padding: 4px;")

    path_btn = QPushButton("…")
    path_btn.setFixedWidth(36)
    path_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.ACCENT2}; color: {panel._app.TEXT}; "
        f"border: none; padding: 2px 4px; }}"
        f"QPushButton:hover {{ background: {panel._app.ACCENT}; }}")
    path_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _browse():
        d = QFileDialog.getExistingDirectory(
            dlg, "Select export folder", path_entry.text())
        if d:
            path_entry.setText(d)
    path_btn.clicked.connect(_browse)

    path_row.addWidget(path_lbl)
    path_row.addWidget(path_entry)
    path_row.addWidget(path_btn)
    lay.addLayout(path_row)

    # ── CSV separator (v1.7.4, 2026-10-01 session) ─────────────────────────
    # Only csv_adapter reads this — a comma-separated file opens as one
    # unsplit column in a German-locale Excel (comma is the decimal
    # separator there), hence the "," vs ";" choice. Default ";" matches
    # German Excel; shown unconditionally rather than only when a CSV row
    # is checked, since that would mean rebuilding this row on every
    # checkbox toggle for a single-adapter special case.
    csv_sep_row = QHBoxLayout()
    csv_sep_row.setSpacing(8)
    csv_sep_lbl = QLabel("CSV separator")
    csv_sep_lbl.setFont(QFont("Segoe UI", 9))
    csv_sep_lbl.setStyleSheet(f"color: {panel._app.TEXT2};")
    csv_sep_lbl.setFixedWidth(90)

    csv_sep_group = QButtonGroup(dlg)
    semicolon_radio = QRadioButton("; (German Excel)")
    comma_radio = QRadioButton(", (RFC 4180)")
    for rb in (semicolon_radio, comma_radio):
        rb.setFont(QFont("Segoe UI", 9))
        rb.setStyleSheet(f"color: {panel._app.TEXT};")
        csv_sep_group.addButton(rb)
    saved_delimiter = (saved_by_id.get("csv_adapter") or {}).get("options", {}).get("delimiter")
    comma_radio.setChecked(saved_delimiter == ",")
    semicolon_radio.setChecked(saved_delimiter != ",")

    csv_sep_row.addWidget(csv_sep_lbl)
    csv_sep_row.addWidget(semicolon_radio)
    csv_sep_row.addWidget(comma_radio)
    csv_sep_row.addStretch()
    lay.addLayout(csv_sep_row)

    sep3 = QFrame()
    sep3.setFrameShape(QFrame.Shape.HLine)
    sep3.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep3)

    # ── Daily Sync (v1.7.4 Baustein 25) ─────────────────────────────────────
    # Replaces the old "Save & Add to Daily Sync" button — a real QCheckBox
    # (same widget/style as the grid above) shows the current enabled/
    # disabled state on reopen and can be switched back off, which the old
    # write-only button never allowed (it could only ever set enabled=True).
    sync_row = QHBoxLayout()
    sync_row.setSpacing(8)

    sync_cb = QCheckBox()
    sync_cb.setStyleSheet(checkbox_style)
    sync_cb.setChecked(bool(saved_cfg.get("enabled")))

    sync_lbl = QLabel("Add this selection to Daily Sync")
    sync_lbl.setFont(QFont("Segoe UI", 9))
    sync_lbl.setStyleSheet(f"color: {panel._app.TEXT2};")

    apply_btn = QPushButton("Apply")
    apply_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    apply_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.BG3}; "
        f"color: {panel._app.TEXT}; border: none; padding: 6px 14px; }}"
        f"QPushButton:hover {{ background: {panel._app.ACCENT2}; }}")
    apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    sync_row.addWidget(sync_cb)
    sync_row.addWidget(sync_lbl)
    sync_row.addStretch()
    sync_row.addWidget(apply_btn)
    lay.addLayout(sync_row)

    sep4 = QFrame()
    sep4.setFrameShape(QFrame.Shape.HLine)
    sep4.setStyleSheet(f"color: {panel._app.ACCENT};")
    lay.addWidget(sep4)

    def _gather_by_adapter() -> dict[int, dict]:
        """
        Collect (domains, include_metadata) per adapter row — only rows
        with at least one checked category are included. Shared by the
        Export button and the Daily Sync Apply button, which both need
        the same selection, just for a different action afterwards.
        """
        by_adapter: dict[int, dict] = {}
        for (row_idx, category_key), cb in check_vars.items():
            if not cb.isChecked():
                continue
            entry = by_adapter.setdefault(row_idx, {"domains": [], "metadata": False})
            if category_key == "metadata":
                entry["metadata"] = True
            else:
                entry["domains"].append(category_key)
        return by_adapter

    # ── Buttons ───────────────────────────────────────────────────────────
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

    export_btn = QPushButton("📤 Export")
    export_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    export_btn.setStyleSheet(
        f"QPushButton {{ background: {panel._app.ACCENT2}; "
        f"color: {panel._app.TEXT}; border: none; padding: 6px 14px; }}")
    export_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _adapter_options(row_idx: int) -> dict:
        """Per-adapter extra build() kwargs — only csv_adapter takes any
        today (its "delimiter", from the radio buttons above)."""
        if adapters[row_idx]["id"] == "csv_adapter":
            return {"delimiter": ";" if semicolon_radio.isChecked() else ","}
        return {}

    def _run():
        by_adapter = _gather_by_adapter()
        if not by_adapter:
            QMessageBox.information(
                dlg, "Export Data",
                "Please select at least one format and one category.")
            return

        selections = [
            (adapters[row_idx]["module"], entry["domains"], entry["metadata"],
             _adapter_options(row_idx))
            for row_idx, entry in by_adapter.items()
        ]
        output_path = Path(path_entry.text().strip())
        dlg.accept()
        export_build.run_export(panel, export_runner, selections, output_path)

    export_btn.clicked.connect(_run)

    def _apply_daily_sync():
        """Apply-button handler (v1.7.4 Baustein 25). Writes export_auto_run
        with "enabled" taken from sync_cb — unlike the old Save button this
        can also persist enabled=False, i.e. actually turn Daily Sync export
        back off. Leaves the dialog open (Timo's decision), so Export can
        still be used afterwards without reopening the popup. A selection is
        only required when switching ON — switching off keeps whatever
        selection was last saved, just flips the flag."""
        by_adapter = _gather_by_adapter()
        if sync_cb.isChecked() and not by_adapter:
            QMessageBox.information(
                dlg, "Export Data",
                "Please select at least one format and one category.")
            return

        selections_cfg = [
            {
                "adapter":  adapters[row_idx]["id"],
                "domains":  entry["domains"],
                "metadata": entry["metadata"],
                "options":  _adapter_options(row_idx),
            }
            for row_idx, entry in by_adapter.items()
        ] if by_adapter else saved_cfg.get("selections", [])
        panel._app.settings["export_auto_run"] = {
            "enabled":    sync_cb.isChecked(),
            "path":       path_entry.text().strip(),
            "selections": selections_cfg,
        }
        panel._app._panel_settings._safe_save(panel._app.settings)
        status = "enabled" if sync_cb.isChecked() else "disabled"
        panel._app._log(
            f"✓ Daily Sync export {status} — {len(selections_cfg)} adapter(s).")

    apply_btn.clicked.connect(_apply_daily_sync)

    btn_row.addWidget(toggle_btn)
    btn_row.addStretch()
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(export_btn)
    lay.addLayout(btn_row)

    dlg.resize(640, 420)
    dlg.exec()
