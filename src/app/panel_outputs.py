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
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QRadioButton, QButtonGroup, QLineEdit,
    QMessageBox, QFileDialog, QFrame,
    QApplication, QSizePolicy, QComboBox, QCheckBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_settings as _settings
import frozen_paths
import theme
from .dialog_force_refetch import (
    ForceRefetchDialog, ForceRefetchProgressDialog, ForceRefetchReviewDialog,
)
from .dialog_context_check import ContextCheckResultDialog, ContextCoordinateFixDialog
from .popups import (
    capability_scan, dashboard_create, custom_dashboard, encrypted_dashboards,
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

    # ── Sync actions ───────────────────────────────────────────────────────────

    def _check_raw_backfill_popup(self, s: dict) -> None:
        try:
            import importlib
            os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
            import garmin_backup as _backup
            import garmin_config as _cfg
            importlib.reload(_cfg)
            importlib.reload(_backup)
            count = _backup.check_raw_backfill_needed()
        except Exception:
            return

        if count == 0:
            self._app.settings["backup_raw_backfill_asked"] = True
            self._app._panel_settings._safe_save(self._app.settings)
            return

        answer = QMessageBox.question(
            self._app, "Raw Backup — New Feature",
            f"Garmin Local Archive v1.5.1 introduced automatic raw file backups.\n\n"
            f"{count} existing raw file(s) have no backup copy yet.\n\n"
            f"Create backups now? This runs in the background and does not\n"
            f"affect the sync. Completed months are stored as ZIP archives\n"
            f"in garmin_data/backup/raw/.\n\n"
            f"You can also skip this — new files will be backed up automatically\n"
            f"after every sync from now on.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def _do_backfill():
            try:
                result = _backup.backfill_raw()
                self._app._log_bg(
                    f"✓ Raw backup complete: {result['copied']} files backed up"
                    + (f", {result['errors']} errors" if result["errors"] else "")
                )
            except Exception as e:
                self._app._log_bg(f"✗ Raw backup failed: {e}")

        self._app.settings["backup_raw_backfill_asked"] = True
        self._app._panel_settings._safe_save(self._app.settings)
        threading.Thread(target=_do_backfill, daemon=True).start()
        self._app._log("🗄  Raw backup running in background …")

    def _run_collector(self, *, on_done=None):
        """Run connection test first (once per session), then start sync.

        on_done: optional callable, fired on the Main Thread after sync
                 completes (after _refresh_archive_info). Used by Daily Sync
                 chain in panel_home to sequence Context Sync afterwards.
        """
        s = self._app._panel_settings._collect_settings()
        if not s["email"] or not s["password"]:
            self._app._log("✗ Email or password missing.")
            return

        timer_was_active = self._app._timer_active
        if self._app._timer_active:
            self._app._log("⏱  Background timer paused for manual sync.")
            self._app._timer_stop.set()
            self._app._timer_active = False
            self._app._dispatch(
                self._app._panel_timer._timer_update_btn)

        if not self._app.settings.get("backup_raw_backfill_asked", False):
            self._check_raw_backfill_popup(s)

        refresh_failed = self._app._panel_archive._check_failed_days_popup(
            base_dir  = s["base_dir"],
            sync_mode = s["sync_mode"],
            sync_days = s["sync_days"],
            sync_from = s.get("sync_from", ""),
            sync_to   = s.get("sync_to", ""),
        )
        run_migration = self._app._panel_archive._check_schema_migration(
            base_dir=s["base_dir"])
        env_extra = {"GARMIN_SCHEMA_MIGRATE": "1"} if run_migration else {}

        def _internal_done():
            self._app._panel_timer._timer_resume_after_sync(timer_was_active)
            self._app._panel_archive._refresh_archive_info()
            self._run_live_fetch()
            if on_done:
                on_done()

        if self._app._connection_verified:
            self._app._run(
                "garmin_collector.py", enable_stop=True,
                refresh_failed=refresh_failed,
                env_overrides=env_extra,
                on_done=_internal_done,
            )
            return

        self._app._panel_connection._run_connection_test(
            on_success=lambda: self._app._run(
                "garmin_collector.py", enable_stop=True,
                refresh_failed=refresh_failed,
                env_overrides=env_extra,
                on_done=_internal_done,
            ))

    def _run_live_fetch(self):
        """Fetch + render Live Tracking in a background thread after Sync
        Garmin (GUI path only — daily_update.py/T3.2 deliberately excluded,
        a headless run has no one watching a "live" view).

        Fire-and-forget: any failure here (login unavailable, specialist
        missing, render error) is logged and swallowed — Live Tracking is a
        non-critical, best-effort feature and must never affect the rest of
        the Sync Garmin chain.
        """
        def worker():
            try:
                s = self._app._panel_settings._collect_settings()
                os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")

                root = frozen_paths.scripts_root()
                frozen_paths.add_to_path(
                    root, "garmin", "dashboards", "layouts", "maps")

                import importlib
                import garmin_config as _cfg
                importlib.reload(_cfg)
                import garmin_live_fetch
                importlib.reload(garmin_live_fetch)

                def _on_state(key, state):
                    pc = self._app._panel_connection
                    self._app._dispatch(lambda: pc._set_indicator(key, state))

                result = garmin_live_fetch.fetch_live(
                    progress=lambda msg: self._app._log_bg(f"  {msg}"),
                    state_cb=_on_state)

                if not result.get("ok"):
                    self._app._log_bg(
                        "\u2139  Live Tracking: fetch skipped (login unavailable)")
                    return

                import importlib.util as _ilu
                runner_path = root / "dashboards" / "dash_runner.py"
                spec = _ilu.spec_from_file_location("dash_runner", runner_path)
                dash_runner = _ilu.module_from_spec(spec)
                spec.loader.exec_module(dash_runner)

                specialists = dash_runner.scan()
                live_spec = next(
                    (sp for sp in specialists if sp["name"] == "Live Tracking"),
                    None)
                if live_spec is None:
                    self._app._log_bg(
                        "\u2139  Live Tracking: specialist not found")
                    return

                out_dir = Path(s["base_dir"]) / "dashboards"
                out_dir.mkdir(parents=True, exist_ok=True)

                results = dash_runner.build(
                    selections=[(live_spec["module"], "html")],
                    date_from="", date_to="",
                    settings=s, output_dir=out_dir,
                )
                ok_result = next((r for r in results if r.get("success")), None)
                if ok_result:
                    self._app._dispatch(
                        lambda: self._app._scan_dashboards(
                            auto_load=str(ok_result["file"])))
                    self._app._log_bg("\u2713 Live Tracking updated")
                else:
                    err = results[0].get("error", "unknown") if results else "no result"
                    self._app._log_bg(f"\u2139  Live Tracking render skipped: {err}")
            except Exception as exc:
                self._app._log_bg(f"\u2139  Live Tracking update skipped: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _on_force_refetch(self):
        """Opens the Force-Refetch calendar dialog (v1.7.1.7, Baustein 5).

        Only opens the dialog and reads the selection back — the dialog's
        own Start button is still a stub (see dialog_force_refetch.py),
        so exec() cannot yet return Accepted from a real confirmed run.
        Wiring run_force_refetch_preview() + the comparison/commit flow
        to this handler is a separate, later Bauauftrag step.
        """
        # ── Preconditions — same pattern as _on_mirror()/_on_silo_check() ──────
        if self._app._is_running():
            QMessageBox.warning(self._app, "Force Refetch",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._timer_active:
            QMessageBox.warning(self._app, "Force Refetch",
                "Background timer is active.\nStop the timer before running Force Refetch.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Force Refetch",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        s = self._app._panel_settings._collect_settings()
        quality_by_date = self._app._panel_archive._get_quality_by_date(
            base_dir=s["base_dir"])

        dlg = ForceRefetchDialog(parent=self, quality_by_date=quality_by_date)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected_dates = dlg.get_selected_dates()
        if not selected_dates:
            return

        # ── Timer pause — held for the whole interaction (preview + wait +
        # commit), same convention as documented in START_PROMPT/GLA_HANDBUCH
        # §10 for Background-Timer vs. manual actions on raw/+summary/. ──────
        timer_was_active = self._app._timer_active
        if self._app._timer_active:
            self._app._log("⏱  Background timer paused for Force Refetch.")
            self._app._timer_stop.set()
            self._app._timer_active = False
            self._app._dispatch(self._app._panel_timer._timer_update_btn)

        progress_dlg = ForceRefetchProgressDialog(parent=self, dates=selected_dates)
        stop_event = threading.Event()

        def _log_to_progress(text: str):
            self._app._dispatch(lambda t=text: progress_dlg.append_log(t))

        def _on_stop_clicked():
            stop_event.set()
        progress_dlg.stop_requested.connect(_on_stop_clicked)

        def _worker():
            # ── Root-logger redirect (same technique as garmin_app_standalone.py's
            # _QueueHandler/root_logger.handlers swap) — every log.info()/
            # log.warning() from garmin_collector, garmin_api, garmin_validator,
            # etc. during the preview run appears in the progress dialog, not
            # just our own two-line-per-day summary. RedactFilter is mandatory
            # here for the same reason it's mandatory there: an error message
            # could otherwise leak a credential value into the visible log. ──
            import logging as _logging
            import garmin_redact as _redact

            class _DialogLogHandler(_logging.Handler):
                def __init__(self, emit_fn):
                    super().__init__()
                    self._emit_fn = emit_fn
                def emit(self, record):
                    self._emit_fn(self.format(record))

            q_handler = _DialogLogHandler(_log_to_progress)
            q_handler.setFormatter(_logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            q_handler.addFilter(_redact.RedactFilter())
            root_logger  = _logging.getLogger()
            old_handlers = root_logger.handlers[:]
            old_level    = root_logger.level
            root_logger.handlers = [q_handler]
            # DEBUG (not INFO) — surfaces api_call()'s per-endpoint
            # "Fetching {label} ..." line (garmin_api.py, v1.7.1.7) so the
            # progress dialog shows real activity instead of going quiet
            # for the ~30-60s a day's fetch loop takes. Scoped to this
            # worker's own temporary handler only — the normal Sync Garmin
            # log elsewhere keeps whatever level panel_settings._log_level
            # is set to, unaffected by this.
            root_logger.setLevel(_logging.DEBUG)

            # File log — Force-Refetch's own rolling log on disk (v1.7.1.7),
            # same convention as every other GLA log (session/daily/mcp).
            # Added as a SECOND handler alongside q_handler above, not a
            # replacement — the dialog needs live text, the file needs a
            # permanent record, both from the exact same log calls.
            import garmin_collector as _collector_for_log
            _ffr_fh, _ffr_log_path = _collector_for_log._start_force_refetch_log()

            try:
                import garmin_config as _cfg
                os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
                os.environ["GARMIN_EMAIL"]      = s.get("email", "")
                os.environ["GARMIN_PASSWORD"]   = s.get("password", "")
                os.environ["GARMIN_SESSION_LOG_PREFIX"] = "force_refetch"
                import importlib
                importlib.reload(_cfg)

                import garmin_collector as _collector
                _collector.set_stop_event(stop_event)

                _log_to_progress("Logging in to Garmin Connect ...")
                import garmin_api
                pc = self._app._panel_connection
                try:
                    client = garmin_api.login(
                        on_key_required  = pc._prompt_enc_key,
                        on_token_expired = pc._prompt_token_expired,
                        on_mfa_required  = pc._prompt_mfa,
                    )
                except garmin_api.GarminLoginError as e:
                    _log_to_progress(f"✗ Login failed: {e}")
                    return
                if client is None:
                    _log_to_progress("✗ Login cancelled.")
                    return

                _log_to_progress(f"Fetching {len(selected_dates)} day(s) ...")
                results = _collector.run_force_refetch_preview(client, selected_dates)

                for entry in results:
                    if entry.get("error") is not None:
                        _log_to_progress(f"  ✗ {entry['date']}: {entry['error']}")
                    else:
                        _log_to_progress(
                            f"  {entry['date']}: {entry['quality_before']} → "
                            f"{entry['quality_after']} "
                            f"| {len(entry['fields_changed'])} field(s) changed")

                _log_to_progress("✓ Preview complete.")
                preview_results[:] = results

            except Exception as e:
                _log_to_progress(f"✗ Force Refetch failed: {e}")
            finally:
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)
                _collector_for_log._close_force_refetch_log(_ffr_fh)
                import garmin_collector as _collector
                _collector.set_stop_event(None)
                self._app._dispatch(lambda: (
                    progress_dlg.close(),
                    self._app._panel_timer._timer_resume_after_sync(timer_was_active),
                ))

        preview_results = []
        preview_thread = threading.Thread(target=_worker, daemon=True)
        preview_thread.start()
        progress_dlg.exec()
        preview_thread.join()

        if not preview_results:
            # Empty on Stop before the first day, or a top-level failure
            # already logged by _worker()'s except-block — nothing to review.
            return

        review_dlg = ForceRefetchReviewDialog(parent=self, results=preview_results)
        if review_dlg.exec() != QDialog.DialogCode.Accepted:
            self._app._log("  Force Refetch: review cancelled — no changes committed.")
            return
        confirmed_dates = review_dlg.get_confirmed_dates()

        import garmin_collector as _collector_for_commit
        import garmin_quality as _quality

        with _quality.QUALITY_LOCK:
            quality_data = _quality._load_quality_log()
            commit_results = _collector_for_commit.commit_force_refetch(
                preview_results, confirmed_dates, quality_data)
            _quality._save_quality_log(quality_data)

        for entry in commit_results:
            action = entry["action"]
            if action == "committed":
                self._app._log(f"  ✓ {entry['date']}: committed")
            elif action == "reverted":
                self._app._log(f"  ↺ {entry['date']}: reverted")
            else:
                self._app._log(f"  ✗ {entry['date']}: {entry.get('error', 'error')}")

        self._app._panel_archive._refresh_archive_info()

    # ── Context-Archive Check (v1.7.2.3 Baustein 4) ────────────────────────────

    def _on_context_check(self):
        """Runs context_silo_check.check_context_archive() in a background
        thread — a full pass reads every context_data/ file individually
        for the coordinate check (~35s on a multi-year archive), so this
        must never run on the Main Thread. Same precondition guards as
        _on_force_refetch() above."""
        if self._app._is_running():
            QMessageBox.warning(self._app, "Context-Check",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Context-Check",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        s = self._app._panel_settings._collect_settings()
        base_dir = s.get("base_dir", "")
        if not base_dir:
            self._app._log("✗ Context-Check: no data folder set.")
            return
        try:
            default_lat = float(s.get("context_latitude") or 0.0)
            default_lon = float(s.get("context_longitude") or 0.0)
        except (TypeError, ValueError):
            default_lat = default_lon = 0.0

        self._context_check_btn.setEnabled(False)
        self._context_check_btn.setText("🧭  Checking…")
        self._app._log("🧭  Context-Check started …")

        def _do_check():
            try:
                root = frozen_paths.scripts_root()
                frozen_paths.add_to_path(root)
                from context import context_silo_check
                result = context_silo_check.check_context_archive(
                    base_dir, default_lat=default_lat, default_lon=default_lon)
            except Exception as e:
                self._app._log_bg(f"✗ Context-Check failed: {e}")
                self._app._dispatch(self._reset_context_check_btn)
                return

            def _show_result():
                self._reset_context_check_btn()
                total_missing = sum(len(v) for v in result["missing_days"].values())
                self._app._log(
                    f"🧭  Context-Check complete — {total_missing} missing, "
                    f"{len(result['bad_coordinates'])} bad coordinate(s)")
                self._open_context_check_dialog(result, base_dir)

            self._app._dispatch(_show_result)

        threading.Thread(target=_do_check, daemon=True).start()

    def _reset_context_check_btn(self):
        """Main Thread only."""
        self._context_check_btn.setEnabled(True)
        self._context_check_btn.setText("🧭  Context-Check")

    def _open_context_check_dialog(self, result: dict, base_dir: str):
        """Main Thread only — opens the result dialog, and on "Koordinaten
        korrigieren" the follow-up fix dialog, chaining exec() calls the
        same way _on_force_refetch() chains its preview/review dialogs."""
        dlg = ContextCheckResultDialog(parent=self, result=result)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        fix_dlg = ContextCoordinateFixDialog(parent=self, findings=result["bad_coordinates"])
        if fix_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fixes = fix_dlg.get_fixes()
        if not fixes:
            return

        # Re-checked here, not just at _on_context_check()'s start — the
        # ~35s read-only scan plus two modal dialogs is a long enough
        # window for a Sync Context run to have started in the meantime.
        # context_data/ has exactly one writer (context_writer.py, used
        # by both context_collector.run() and context_silo_repair.py) —
        # the GUI's existing convention is one write operation at a time,
        # via the shared _ctx_running flag every other context-touching
        # action (_on_force_refetch, _on_silo_check, _on_mirror) already
        # checks. This fix keeps that convention rather than introducing
        # a second, parallel guard.
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Context-Check",
                "Context sync is running.\nPlease try the coordinate fix again afterwards.")
            return

        self._app._ctx_running = True
        self._context_check_btn.setEnabled(False)
        self._ctx_btn.setEnabled(False)

        def _do_fix():
            try:
                self._app._log_bg(
                    f"📍  Koordinaten-Korrektur gestartet — {len(fixes)} Tag(e) "
                    f"werden mit korrigierter Koordinate neu abgerufen …")
                root = frozen_paths.scripts_root()
                frozen_paths.add_to_path(root)
                from context import context_silo_repair
                repair_result = context_silo_repair.fix_coordinates(base_dir, fixes)
                for item in repair_result["items"]:
                    if item["status"] == "error":
                        self._app._log_bg(
                            f"    ✗ {item['date']} {item['source']}: {item['reason']}")
                self._app._log_bg(
                    f"📍  Koordinaten-Korrektur fertig: {repair_result['ok']} behoben, "
                    f"{repair_result['failed']} Fehler")
            finally:
                self._app._dispatch(self._reset_after_coordinate_fix)

        threading.Thread(target=_do_fix, daemon=True).start()

    def _reset_after_coordinate_fix(self):
        """Main Thread only."""
        self._app._ctx_running = False
        self._context_check_btn.setEnabled(True)
        self._ctx_btn.setEnabled(True)

    def _run_import(self):
        """Open file dialog and run bulk import."""
        answer = QMessageBox.question(
            self._app, "Import Bulk Export",
            "Select ZIP file?\n\nYes = ZIP file\nNo = unpacked folder",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            path, _ = QFileDialog.getOpenFileName(
                self._app, "Select Garmin Export ZIP",
                filter="ZIP files (*.zip);;All files (*.*)")
        else:
            path = QFileDialog.getExistingDirectory(
                self._app, "Select unpacked Garmin Export folder")
        if not path:
            return

        timer_was_active = self._app._timer_active
        if self._app._timer_active:
            self._app._log("⏱  Background timer paused for import.")
            self._app._timer_stop.set()
            self._app._timer_active = False
            self._app._dispatch(
                self._app._panel_timer._timer_update_btn)

        self._app._log(f"   Source: {path}")

        def _on_import_done():
            # T3: GARMIN_IMPORT_PATH lives in os.environ of the GUI process.
            # Pop it before the timer resumes — otherwise the next timer-triggered
            # _run() would re-enter the import path instead of the normal sync.
            os.environ.pop("GARMIN_IMPORT_PATH", None)
            self._app._panel_timer._timer_resume_after_sync(timer_was_active)
            self._app._panel_archive._refresh_archive_info()

        self._app._run(
            "garmin_collector.py",
            enable_stop=True,
            log_prefix="garmin_bulk",
            env_overrides={"GARMIN_IMPORT_PATH": path},
            on_done=_on_import_done,
        )

    # ── Context sync ───────────────────────────────────────────────────────────

    def _run_context_sync(self, *, on_done=None):
        """Run context collect (weather + pollen) in background thread.

        on_done: optional callable, fired on the Main Thread after context
                 sync completes. Used by Daily Sync chain in panel_home to
                 sequence dashboard build afterwards.
        """
        s = self._app._panel_settings._collect_settings()
        if (float(s.get("context_latitude",  "0.0")) == 0.0 and
                float(s.get("context_longitude", "0.0")) == 0.0):
            QMessageBox.warning(
                self._app, "Location not configured",
                "Please set a location in Settings before running Context Sync.\n"
                "Use the Settings panel to enter coordinates."
            )
            if on_done:
                on_done()
            return

        self._ctx_btn.setEnabled(False)
        self._ctx_stop_btn.setEnabled(True)
        self._app._context_stop_event = threading.Event()
        self._app._ctx_running        = True
        _chain_done = on_done

        def run():
            try:
                _root = frozen_paths.scripts_root()
                frozen_paths.add_to_path(_root)
                from context import context_collector
                result  = context_collector.run(
                    settings=s,
                    stop_event=self._app._context_stop_event,
                    log_callback=self._app._log_bg,
                )
                plugins = result.get("plugins", {})
                lines   = ["Context sync complete"]
                for name, stats in plugins.items():
                    lines.append(
                        f"{name.capitalize():<10}{stats.get('written', 0)} written")
                msg = "\n".join(lines)
                if result.get("error"):
                    msg = f"Error: {result['error']}"
                self._app._dispatch(lambda m=msg: self._app._log(m))
            except Exception as exc:
                self._app._dispatch(
                    lambda e=exc: self._app._log(f"Context sync error: {e}"))
            finally:
                def _finish():
                    self._on_context_sync_done()
                    if _chain_done:
                        _chain_done()
                self._app._dispatch(_finish)

        threading.Thread(target=run, daemon=True).start()

    def _stop_context_sync(self):
        self._app._context_stop_event.set()

    def _on_context_sync_done(self):
        self._ctx_btn.setEnabled(True)
        self._ctx_stop_btn.setEnabled(False)
        self._app._ctx_running = False

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

    # ── All-dashboards build (used by Daily Sync chain) ───────────────────────

    def _run_all_dashboards(self, *, on_done=None):
        """Build all specialists / all formats — no dialog, no date filter.

        Mirrors daily_update._run_dashboards(): scans all specialists, selects
        all formats, uses the full archive date range from summary/*.json.
        Fires on_done on the Main Thread when complete (success or error).
        """
        import importlib.util as _ilu

        root = frozen_paths.scripts_root()
        frozen_paths.add_to_path(root, "dashboards", "layouts", "maps")

        try:
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            if spec is None:
                raise FileNotFoundError(f"dash_runner.py not found: {runner_path}")
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)
        except Exception as exc:
            self._app._log(f"✗ Dashboard runner could not be loaded: {exc}")
            if on_done:
                on_done()
            return

        try:
            specialists = dash_runner.scan()
        except Exception as exc:
            self._app._log(f"✗ Dashboard scan failed: {exc}")
            if on_done:
                on_done()
            return

        if not specialists:
            self._app._log("ℹ  No dashboard specialists found — skipping.")
            if on_done:
                on_done()
            return

        selections = [
            (spec["module"], fmt)
            for spec in specialists
            for fmt in spec["formats"]
        ]

        # Full archive date range — same logic as daily_update
        s         = self._app._panel_settings._collect_settings()
        base      = Path(s["base_dir"])
        summary_dir = base / "garmin_data" / "summary"
        dates = sorted(
            f.stem.replace("garmin_", "")
            for f in summary_dir.glob("garmin_???-??-??.json")
        ) if summary_dir.exists() else []
        today     = date.today()
        date_from = dates[0]  if dates else (today - timedelta(days=90)).isoformat()
        date_to   = dates[-1] if dates else today.isoformat()

        output_dir = base / "dashboards"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._app._log("\n▶  Daily Sync — building dashboards ...")
        self._app._log(f"   Range: {date_from} → {date_to}")
        _chain_done = on_done

        def worker():
            try:
                import importlib
                os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
                import garmin_config as _cfg
                importlib.reload(_cfg)
                results = dash_runner.build(
                    selections=selections,
                    date_from=date_from,
                    date_to=date_to,
                    settings=s,
                    output_dir=output_dir,
                    log=lambda msg: self._app._dispatch(
                        lambda m=msg: self._app._log(f"   {m}")),
                )

                def _finish():
                    ok  = [r for r in results if r["success"]]
                    err = [r for r in results if not r["success"]]
                    self._app._log(f"\n  ✓ {len(ok)} dashboard(s) built")
                    for r in err:
                        self._app._log(
                            f"  ✗ {r['name']} ({r['format']}): "
                            f"{r.get('error', '')}")
                    if ok:
                        last_html = next(
                            (r.get("path") for r in ok
                             if r.get("format") == "html"), None)
                        if last_html:
                            self._app._last_html = str(last_html)
                        self._app._scan_dashboards(
                            auto_load=self._app._last_html)
                        self._app._scan_xlsx_files()
                    try:
                        import garmin_mobile_landing as _landing
                        _landing.write_index_html(s["base_dir"])
                    except Exception:
                        pass
                    if _chain_done:
                        _chain_done()

                self._app._dispatch(_finish)
            except Exception as exc:
                def _err(e=exc):
                    self._app._log(f"  ✗ Dashboard build error: {e}")
                    if _chain_done:
                        _chain_done()
                self._app._dispatch(_err)

        threading.Thread(target=worker, daemon=True).start()

    # ── Output helpers ─────────────────────────────────────────────────────────

    def _open_data_folder(self):
        folder = Path(self._app._panel_settings._collect_settings()["base_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _open_last_html(self):
        html = self._app._last_html
        if not html or not Path(html).exists():
            base  = Path(
                self._app._panel_settings._collect_settings()["base_dir"])
            files = list(base.glob("*.html"))
            if not files:
                self._app._log("✗ No HTML files found in data folder.")
                return
            html = str(max(files, key=lambda f: f.stat().st_mtime))
        os.startfile(html)

    def _copy_last_error_log(self):
        fail_dir = (
            Path(self._app._panel_settings._collect_settings()["base_dir"])
            / "garmin_data" / "log" / "fail"
        )
        if not fail_dir.exists():
            self._app._log("✗ No error logs found (log/fail/ does not exist).")
            return
        logs = sorted(fail_dir.glob("garmin_*.log"),
                      key=lambda f: f.stat().st_mtime)
        if not logs:
            self._app._log("✓ No error logs — no failed sessions recorded.")
            return
        latest = logs[-1]
        try:
            content = latest.read_text(encoding="utf-8")
            QApplication.clipboard().setText(content)
            self._app._log(
                f"✓ Error log copied to clipboard ({latest.name})")
        except Exception as e:
            self._app._log(f"✗ Could not read error log: {e}")

    def _open_local_config(self):
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

    def _create_task_scheduler_xml(self):
        """Generate a configured daily_update_task.xml for Windows Task Scheduler."""

        _exe_dir = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                    else Path(__file__).parent.parent)

        template_path = frozen_paths.doc_path("daily_update_task.xml")
        if template_path is None:
            QMessageBox.critical(
                self._app, "Task Scheduler XML",
                "Template file 'daily_update_task.xml' not found.\n"
                "Expected in scheduler/ (dev) or info/ (build).",
            )
            return

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = QDialog(self._app)
        dlg.setWindowTitle("Create Task Scheduler XML")
        dlg.setModal(True)
        dlg.setFixedWidth(480)
        dlg.setStyleSheet(f"background: {self._app.BG}; color: {self._app.TEXT};")
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
        body.setStyleSheet(f"color: {self._app.TEXT2};")
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
            rb.setStyleSheet(f"color: {self._app.TEXT};")
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
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
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
            f"QPushButton {{ background: {self._app.ACCENT2}; "
            f"color: {self._app.TEXT}; border: none; padding: 4px; }}")
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
        warn.setStyleSheet(f"color: {self._app.YELLOW};")
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
            f"QPushButton {{ background: {self._app.ACCENT}; "
            f"color: {self._app.TEXT}; border: none; padding: 7px 16px; }}")
        gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        gen_btn.clicked.connect(_generate)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT2}; border: none; padding: 7px 16px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)

        btn_row.addWidget(gen_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)
        dlg.exec()
