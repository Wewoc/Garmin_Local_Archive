#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/panel_outputs.py
Garmin Local Archive — Outputs Panel

PanelOutputs — PyQt6 QWidget for data collection buttons (sync, import,
context sync), dashboard popup, output buttons (folder, error log,
task scheduler XML), and all related callbacks.

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _outputs_* prefix (E-7)
  - Owned state: _ctx_running, _context_stop_event, _stopped_by_user,
                 _last_html (all on self._app, D-4)
  - Workers never touch widgets — use self._app._dispatch()
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QFrame,
    QSizePolicy, QComboBox, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_settings as _settings
import frozen_paths
import theme
from .popups import (
    capability_scan, dashboard_create, custom_dashboard, encrypted_dashboards,
)
from .outputs import (
    output_helpers, bulk_import, force_refetch, context_check, dashboards,
    context_sync, sync,
)


class PanelOutputs(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Data Collection ────────────────────────────────────────────────────
        lay.addWidget(self._section_widget("Data Collection"))

        # Sync row
        sync_row = QHBoxLayout()
        sync_row.setContentsMargins(20, 2, 20, 2)
        sync_row.setSpacing(4)
        self._sync_btn = self._action_btn("▶  Sync Garmin", self._app.ACCENT,
                                          self._app.TEXT, self._run_collector)
        self._sync_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        self._stop_btn = self._action_btn("⏹  Stop", self._app.BG3,
                                          self._app.TEXT2, self._app._stop_collector)
        self._stop_btn.setEnabled(False)
        sync_row.addWidget(self._sync_btn)
        sync_row.addWidget(self._stop_btn)
        sync_row.addWidget(self._tip("Fetch missing days from Garmin Connect"))
        lay.addLayout(sync_row)

        # Import row
        imp_row = QHBoxLayout()
        imp_row.setContentsMargins(20, 2, 20, 2)
        imp_row.setSpacing(4)
        imp_btn = self._action_btn("📥  Import Bulk Export", self._app.BG3,
                                   self._app.TEXT, self._run_import)
        imp_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
        imp_row.addWidget(imp_btn)
        imp_row.addWidget(
            self._tip("Import Garmin GDPR export ZIP or folder (recommended for history)"))
        lay.addLayout(imp_row)

        # Import links row
        _EXPORT_URL = "https://www.garmin.com/en-US/account/datamanagement/exportdata/"
        link_row = QHBoxLayout()
        link_row.setContentsMargins(20, 0, 20, 4)
        link_row.setSpacing(14)
        exp_link = QLabel("→ Request export at garmin.com")
        exp_link.setFont(QFont("Segoe UI", 8))
        exp_link.setStyleSheet(
            f"color: {self._app.ACCENT}; text-decoration: underline;")
        exp_link.setCursor(Qt.CursorShape.PointingHandCursor)
        exp_link.mousePressEvent = lambda e: _settings._open_url(_EXPORT_URL)

        _readme = frozen_paths.doc_path("README_APP.md")
        readme_link = QLabel("→ Open README")
        readme_link.setFont(QFont("Segoe UI", 8))
        readme_link.setStyleSheet(
            f"color: {self._app.ACCENT}; text-decoration: underline;")
        readme_link.setCursor(Qt.CursorShape.PointingHandCursor)
        readme_link.mousePressEvent = (
            lambda e: os.startfile(_readme) if _readme else None)

        link_row.addWidget(exp_link)
        link_row.addWidget(readme_link)
        link_row.addStretch()
        lay.addLayout(link_row)

        # Context sync row
        ctx_row = QHBoxLayout()
        ctx_row.setContentsMargins(20, 2, 20, 2)
        ctx_row.setSpacing(4)
        self._ctx_btn = self._action_btn("🌍  Sync Context", self._app.BG3,
                                          self._app.TEXT2, self._run_context_sync)
        self._ctx_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        self._ctx_stop_btn = self._action_btn("⏹  Stop", self._app.BG3,
                                               self._app.TEXT2,
                                               self._stop_context_sync)
        self._ctx_stop_btn.setEnabled(False)
        self._ctx_csv_btn = self._action_btn("📄  CSV", self._app.BG3,
                                              self._app.TEXT2,
                                              self._open_local_config)
        ctx_row.addWidget(self._ctx_btn)
        ctx_row.addWidget(self._ctx_stop_btn)
        ctx_row.addWidget(self._ctx_csv_btn)
        ctx_row.addWidget(self._tip("Fetch weather & pollen from Open-Meteo"))
        lay.addLayout(ctx_row)

        # API Scan row
        scan_row = QHBoxLayout()
        scan_row.setContentsMargins(20, 2, 20, 2)
        scan_row.setSpacing(4)
        scan_btn = self._action_btn("🔍  API Scan", self._app.BG3,
                                    self._app.TEXT2, self._open_capability_scan_popup)
        scan_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
        scan_row.addWidget(scan_btn)
        scan_row.addWidget(
            self._tip("Discover optional Garmin API endpoints for your account"))
        lay.addLayout(scan_row)

        # ── Data Management ─────────────────────────────────────────────────────
        # Moved from panel_connection.py (v1.7.2.3 Baustein 3) — Restore Data /
        # Silo-Check / Repair, plus Force Refetch (moved down from Data
        # Collection above) now live together here.
        lay.addWidget(self._section_widget("Data Management"))

        restore_row = QHBoxLayout()
        restore_row.setContentsMargins(20, 2, 20, 2)
        restore_row.setSpacing(4)
        self._restore_btn = self._action_btn(
            "Restore Data", self._app.BG3, self._app.TEXT2,
            lambda: self._app._panel_archive._on_restore_data())
        self._restore_btn.setEnabled(False)
        self._restore_btn.setToolTip(
            "Restore raw data from the backup folder.\n"
            "Enabled after a Silo-Check detects recoverable files.")
        self._restore_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Fixed)
        restore_row.addWidget(self._restore_btn)
        restore_row.addWidget(
            self._tip("Restore missing raw files from local backup"))
        lay.addLayout(restore_row)

        silo_row = QHBoxLayout()
        silo_row.setContentsMargins(20, 2, 20, 2)
        silo_row.setSpacing(4)
        self._silo_check_btn = self._action_btn(
            "🔍  Silo-Check", self._app.BG3, self._app.TEXT2,
            lambda: self._app._panel_archive._on_silo_check())
        self._silo_check_btn.setEnabled(True)
        self._silo_check_btn.setToolTip(
            "Check raw/, summary/ and source/ for consistency.\n"
            "Detects missing or mismatched files across silos.")
        self._silo_repair_btn = self._action_btn(
            "🔧  Repair", self._app.BG3, self._app.TEXT2,
            lambda: self._app._panel_archive._on_silo_repair())
        self._silo_repair_btn.setEnabled(False)
        self._silo_repair_btn.setToolTip(
            "Repair silo inconsistencies found by Silo-Check.\n"
            "Enabled after a completed check with findings.")
        silo_row.addWidget(self._silo_check_btn)
        silo_row.addWidget(self._silo_repair_btn)
        silo_row.addWidget(
            self._tip("Check raw/summary/source consistency across the archive"))
        lay.addLayout(silo_row)

        # Force-Refetch row (v1.7.1.7, Baustein 5 Schritt 1 — button only,
        # calendar dialog + comparison/commit flow follow in later steps;
        # moved here from Data Collection, v1.7.2.3 Baustein 3)
        force_refetch_row = QHBoxLayout()
        force_refetch_row.setContentsMargins(20, 2, 20, 2)
        force_refetch_row.setSpacing(4)
        force_refetch_btn = self._action_btn(
            "⚠  Force Refetch", self._app.BG3, self._app.TEXT2,
            self._on_force_refetch)
        force_refetch_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Fixed)
        force_refetch_row.addWidget(force_refetch_btn)
        force_refetch_row.addWidget(
            self._tip("Re-fetch a specific day, bypassing quality protection"))
        lay.addLayout(force_refetch_row)

        # Context-Check row (v1.7.2.3 Baustein 4 — new function)
        context_check_row = QHBoxLayout()
        context_check_row.setContentsMargins(20, 2, 20, 2)
        context_check_row.setSpacing(4)
        self._context_check_btn = self._action_btn(
            "🧭  Context-Check", self._app.BG3, self._app.TEXT2,
            self._on_context_check)
        self._context_check_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                              QSizePolicy.Policy.Fixed)
        context_check_row.addWidget(self._context_check_btn)
        context_check_row.addWidget(
            self._tip("Check context_data/ for missing days and bad coordinates"))
        lay.addLayout(context_check_row)

        # ── Export ────────────────────────────────────────────────────────────
        lay.addWidget(self._section_widget("Export"))
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(20, 2, 20, 2)
        exp_row.setSpacing(4)
        rep_btn = self._action_btn("📊  Create Reports", self._app.BG3,
                                   self._app.TEXT, self._open_dashboard_popup)
        rep_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
        exp_row.addWidget(rep_btn)
        exp_row.addWidget(
            self._tip("Select dashboards and create as HTML, Excel or JSON"))
        lay.addLayout(exp_row)

        enc_row = QHBoxLayout()
        enc_row.setContentsMargins(20, 2, 20, 2)
        enc_row.setSpacing(4)
        enc_btn = self._action_btn("🔒  Encrypted Dashboards", self._app.BG3,
                                   self._app.TEXT, self._open_encrypted_dashboard_popup)
        enc_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
        enc_btn.setToolTip(
            "Build all HTML dashboards and encrypt them with a password.\n"
            "Output: basedir/encrypted/ — for transport on USB drives.\n"
            "Not included in Daily Sync.")
        enc_row.addWidget(enc_btn)
        enc_row.addWidget(
            self._tip("Password-protected HTML dashboards for USB transport"))
        lay.addLayout(enc_row)

        cust_row = QHBoxLayout()
        cust_row.setContentsMargins(20, 2, 20, 2)
        cust_row.setSpacing(4)
        cust_btn = self._action_btn("🎛  Custom Dashboard", self._app.BG3,
                                    self._app.TEXT, self._open_custom_dashboard_popup)
        cust_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
        cust_row.addWidget(cust_btn)
        cust_row.addWidget(
            self._tip("Pick any Garmin + Context fields, build a one-off dashboard"))
        lay.addLayout(cust_row)

        # ── Output ───────────────────────────────────────────────────────────
        lay.addWidget(self._section_widget("Output"))
        for label, cmd, tip in [
            ("📁  Open Data Folder",
             self._open_data_folder,
             "Open garmin_data/ in Explorer"),
            ("📋  Copy Last Error Log",
             self._copy_last_error_log,
             "Copy most recent error log to clipboard"),
            ("🗓  Create Task Scheduler XML",
             self._create_task_scheduler_xml,
             "Generate daily_update_task.xml for Windows Task Scheduler"),
        ]:
            out_row = QHBoxLayout()
            out_row.setContentsMargins(20, 2, 20, 2)
            out_row.setSpacing(4)
            btn = self._action_btn(label, self._app.BG3,
                                   self._app.TEXT, cmd)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            out_row.addWidget(btn)
            out_row.addWidget(self._tip(tip))
            lay.addLayout(out_row)

        # ── Daily Sync ───────────────────────────────────────────────────────
        # v1.7.2.4 — T3-only unattended self-update opt-in, own section
        # (not folded into Output — a persistent Daily Sync behavior
        # toggle, not a one-shot output action). Value lives directly on
        # self._app.settings, carried over by GarminApp._collect_settings()
        # — same pattern already used for active_theme below, since this
        # panel has no get_*_settings() method of its own the way
        # PanelTimer/PanelMcp do.
        lay.addWidget(self._section_widget("Daily Sync"))
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(20, 2, 20, 2)
        auto_row.setSpacing(4)
        self._daily_update_auto_update = QCheckBox(
            "Auto-apply updates in Daily Sync")
        self._daily_update_auto_update.setFont(QFont("Segoe UI", 9))
        self._daily_update_auto_update.setStyleSheet(f"color: {self._app.TEXT};")
        self._daily_update_auto_update.setChecked(
            bool(self._app.settings.get("daily_update_auto_update", False)))
        self._daily_update_auto_update.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._daily_update_auto_update.toggled.connect(
            self._on_daily_update_auto_update_toggled)
        auto_row.addWidget(self._daily_update_auto_update)
        auto_row.addWidget(self._tip(
            "T3 only: daily_update.exe applies a new version by itself, "
            "unattended, instead of just notifying"))
        lay.addLayout(auto_row)

        # ── Design ───────────────────────────────────────────────────────────
        lay.addWidget(self._section_widget("Design"))
        design_row = QHBoxLayout()
        design_row.setContentsMargins(20, 2, 20, 2)
        design_row.setSpacing(4)

        self._theme_combo = QComboBox()
        self._theme_combo.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 4px; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}"
        )
        for num, t in theme._THEMES.items():
            self._theme_combo.addItem(t["name"], userData=num)
        current_theme = self._app.settings.get("active_theme", 1)
        idx = self._theme_combo.findData(current_theme)
        self._theme_combo.setCurrentIndex(max(0, idx))

        apply_btn = QPushButton("Apply")
        apply_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT}; "
            f"color: {self._app.TEXT}; border: none; padding: 6px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.clicked.connect(self._on_theme_apply)

        design_row.addWidget(self._theme_combo)
        design_row.addWidget(apply_btn)
        design_row.addWidget(self._tip("restart to apply"))
        lay.addLayout(design_row)

        lay.addStretch()

    # ── Widget helpers ─────────────────────────────────────────────────────────
    # Codereview v1.7.0.1: panel_home.py has its own, independent copy of an
    # _action_btn-style helper — not shared across panels. Deliberately left
    # as-is — outside scope of this round, see TODO_codereview_v1.7.0.1.md.

    def _section_widget(self, title: str) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(w)
        vl.setContentsMargins(20, 6, 20, 2)
        vl.setSpacing(2)
        lbl = QLabel(title.upper())
        lbl.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {self._app.ACCENT};")
        vl.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        vl.addWidget(sep)
        return w

    def _action_btn(self, text: str, bg: str, fg: str, cmd) -> QPushButton:
        btn = QPushButton(text)
        btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; "
            f"border: none; padding: 7px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
            f"background: {self._app.BG3}; }}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(cmd)
        return btn

    def _tip(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 8))
        lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        lbl.setFixedWidth(300)
        return lbl

    # ── Accessors — sole authorised write-path for restore/silo buttons ────────
    # Moved from panel_connection.py (v1.7.2.3 Baustein 3) together with the
    # Data Management row itself — called from PanelArchive.

    def set_silo_check_button_state(self, enabled: bool, text: str = None):
        """Called from PanelArchive — Main Thread only."""
        self._silo_check_btn.setEnabled(enabled)
        if text is not None:
            self._silo_check_btn.setText(text)
        fg = self._app.TEXT if enabled else self._app.TEXT2
        self._silo_check_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {fg}; "
            f"border: none; padding: 7px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
            f"background: {self._app.BG3}; }}")
        self._silo_check_btn.style().unpolish(self._silo_check_btn)
        self._silo_check_btn.style().polish(self._silo_check_btn)
        self._silo_check_btn.update()

    def set_silo_repair_button_state(self, enabled: bool, text: str = None):
        """Called from PanelArchive — Main Thread only."""
        self._silo_repair_btn.setEnabled(enabled)
        if text is not None:
            self._silo_repair_btn.setText(text)
        fg = self._app.TEXT if enabled else self._app.TEXT2
        self._silo_repair_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {fg}; "
            f"border: none; padding: 7px 14px; text-align: left; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
            f"background: {self._app.BG3}; }}")
        self._silo_repair_btn.style().unpolish(self._silo_repair_btn)
        self._silo_repair_btn.style().polish(self._silo_repair_btn)
        self._silo_repair_btn.update()

    def set_restore_button_state(self, enabled: bool,
                                 text: str = None, color: str = None,
                                 command=None):
        """Called from PanelArchive — Main Thread only."""
        self._restore_btn.setEnabled(enabled)
        if text is not None:
            self._restore_btn.setText(text)
        if command is not None:
            try:
                self._restore_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._restore_btn.clicked.connect(command)

    def _on_daily_update_auto_update_toggled(self, checked: bool):
        """Persist immediately (v1.7.2.4) — same reasoning as
        _on_theme_apply() below: a checkbox toggle should stick right
        away, not depend on the app being closed cleanly afterward to
        actually save."""
        self._app.settings["daily_update_auto_update"] = checked
        self._app._panel_settings._safe_save(self._app.settings)

    def _on_theme_apply(self):
        """Save the selected theme number to settings. Does not restart the
        app — new colors take effect on next launch (see NEU comment in
        theme.py: ACTIVE_THEME is read from settings at import time)."""
        selected = self._theme_combo.currentData()
        self._app.settings["active_theme"] = selected
        self._app._panel_settings._safe_save(self._app.settings)
        QMessageBox.information(
            self._app, "Design",
            "Theme saved — restart Garmin Local Archive to apply.",
        )

    # v1.7.3.1 Baustein 7 (last): moved to app/outputs/sync.py. Both
    # delegates keep their exact signatures — _run_collector is called
    # from _build_ui()'s Sync-Garmin button AND panel_home.py's Daily
    # Sync chain with on_done=...; _run_live_fetch is called from
    # panel_home.py's Update-Live button AND internally from
    # run_collector()'s _internal_done (all confirmed by Grep).
    # _check_raw_backfill_popup moved with it, module-private, no
    # external callers.
    def _run_collector(self, *, on_done=None):
        return sync.run_collector(self, on_done=on_done)

    def _run_live_fetch(self):
        return sync.run_live_fetch(self)

    # v1.7.3.1 Baustein 3: moved to app/outputs/force_refetch.py — thin
    # delegate kept here so _build_ui()'s button wiring needs zero changes.
    def _on_force_refetch(self):
        return force_refetch.on_force_refetch(self)

    # v1.7.3.1 Baustein 4: moved to app/outputs/context_check.py — thin
    # delegate kept here so _build_ui()'s button wiring needs zero changes.
    # _reset_context_check_btn/_open_context_check_dialog/
    # _reset_after_coordinate_fix moved with it, no external callers
    # (verified by Grep), so no delegates needed for those three.
    def _on_context_check(self):
        return context_check.on_context_check(self)

    # v1.7.3.1 Baustein 2: moved to app/outputs/bulk_import.py — thin
    # delegate kept here so _build_ui()'s button wiring needs zero changes.
    def _run_import(self):
        return bulk_import.run_import(self)

    # v1.7.3.1 Baustein 6: moved to app/outputs/context_sync.py. All three
    # delegates kept — _run_context_sync needs the same keyword signature
    # (panel_home.py's Daily Sync chain calls it with on_done=... from
    # outside panel_outputs.py); _stop_context_sync/_on_context_sync_done
    # are called directly as panel._method() in
    # tests/test_qt_app.py::TestPanelOutputs (confirmed by Grep).
    def _run_context_sync(self, *, on_done=None):
        return context_sync.run_context_sync(self, on_done=on_done)

    def _stop_context_sync(self):
        return context_sync.stop_context_sync(self)

    def _on_context_sync_done(self):
        return context_sync.on_context_sync_done(self)

    # ── Capability Scan popup (v1.6.8) ──────────────────────────────────────────
    # Codereview v1.7.0.1, Baustein 1.1: moved to app/popups/capability_scan.py
    # (open_popup + 3 sub-dialogs) — thin delegate kept here so _build_ui()'s
    # button wiring (self._action_btn(..., self._open_capability_scan_popup))
    # needs zero changes.

    def _open_capability_scan_popup(self):
        capability_scan.open_popup(self)

    # ── Dashboard popup ────────────────────────────────────────────────────────
    # Codereview v1.7.0.1, Baustein 1.2: moved to app/popups/dashboard_create.py
    # — thin delegate kept here so _build_ui()'s button wiring
    # (self._action_btn(..., self._open_dashboard_popup)) needs zero changes.

    def _open_dashboard_popup(self):
        dashboard_create.open_popup(self)

    # ── Custom Dashboard Builder (v1.6.4) ──────────────────────────────────────
    # Codereview v1.7.0.1, Baustein 1.3: moved to app/popups/custom_dashboard.py
    # — thin delegate kept here so _build_ui()'s button wiring
    # (self._action_btn(..., self._open_custom_dashboard_popup)) needs zero
    # changes. The former _run_custom_dashboard_encrypted() and _run_dashboards()
    # helper methods are gone too — moved to the shared
    # app/popups/_dashboard_build.py (Baustein 1.5), used directly by
    # custom_dashboard.py, dashboard_create.py and encrypted_dashboards.py.

    def _open_custom_dashboard_popup(self):
        custom_dashboard.open_popup(self)

    # ── Encrypted Dashboards ───────────────────────────────────────────────────
    # Codereview v1.7.0.1, Baustein 1.4: moved to app/popups/encrypted_dashboards.py
    # — thin delegate kept here so _build_ui()'s button wiring
    # (self._action_btn(..., self._open_encrypted_dashboard_popup)) needs zero
    # changes.

    def _open_encrypted_dashboard_popup(self):
        encrypted_dashboards.open_popup(self)

    # v1.7.3.1 Baustein 5: moved to app/outputs/dashboards.py — thin
    # delegate kept here with the SAME keyword signature, since
    # panel_home.py's Daily Sync chain calls this from outside
    # panel_outputs.py (confirmed by Grep before this Baustein).
    def _run_all_dashboards(self, *, on_done=None):
        return dashboards.run_all_dashboards(self, on_done=on_done)

    # ── Output helpers ─────────────────────────────────────────────────────────
    # v1.7.3.1 Baustein 1: moved to app/outputs/output_helpers.py — thin
    # delegates kept here so _build_ui()'s button wiring and the direct
    # panel._method() calls in tests/test_qt_app.py need zero changes.

    def _open_data_folder(self):
        return output_helpers.open_data_folder(self)

    def _copy_last_error_log(self):
        return output_helpers.copy_last_error_log(self)

    def _open_local_config(self):
        return output_helpers.open_local_config(self)

    def _create_task_scheduler_xml(self):
        return output_helpers.create_task_scheduler_xml(self)
