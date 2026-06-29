#!/usr/bin/env python3
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
    QDialog, QCheckBox, QRadioButton, QButtonGroup, QLineEdit,
    QMessageBox, QFileDialog, QFrame, QGridLayout,
    QApplication, QSizePolicy, QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_settings as _settings
from .dialogs import PasswordConfirmDialog


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

        _exe_dir = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                    else Path(__file__).parent)
        _readme_candidates = [
            _exe_dir / "info" / "README_APP.md",
            Path(__file__).parent / "docs" / "README_APP.md",
        ]
        _readme = next((p for p in _readme_candidates if p.exists()), None)
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

        lay.addStretch()

    # ── Widget helpers ─────────────────────────────────────────────────────────

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
                if not getattr(sys, "frozen", False):
                    _root = Path(__file__).parent.parent
                elif (hasattr(sys, "_MEIPASS") and
                        (Path(sys._MEIPASS) / "scripts").exists()):
                    _root = Path(sys._MEIPASS) / "scripts"
                else:
                    _root = Path(sys.executable).parent / "scripts"
                if str(_root) not in sys.path:
                    sys.path.insert(0, str(_root))
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

    # ── Dashboard popup ────────────────────────────────────────────────────────

    def _open_dashboard_popup(self):
        """Scan specialists, show selection dialog, build selected dashboards."""
        import importlib.util as _ilu

        if not getattr(sys, "frozen", False):
            root = Path(__file__).parent.parent
        elif (hasattr(sys, "_MEIPASS") and
                (Path(sys._MEIPASS) / "scripts").exists()):
            root = Path(sys._MEIPASS) / "scripts"
        else:
            root = Path(sys.executable).parent / "scripts"
        for p in (root / "dashboards", root / "layouts", root / "maps"):
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)

        try:
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            if spec is None:
                raise FileNotFoundError(
                    f"dash_runner.py nicht gefunden: {runner_path}")
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)
        except Exception as exc:
            self._app._log(
                f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
            return

        try:
            specialists = dash_runner.scan()
        except Exception as exc:
            self._app._log(f"✗ scan() fehlgeschlagen: {exc}")
            return
        if not specialists:
            QMessageBox.information(self._app, "Create Reports",
                                    "No dashboards found in dashboards/")
            return

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = QDialog(self._app)
        dlg.setWindowTitle("Create Reports")
        dlg.setModal(True)
        dlg.setStyleSheet(f"background: {self._app.BG}; color: {self._app.TEXT};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        title = QLabel("CREATE REPORTS")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(title)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
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
        hdr.setStyleSheet(f"color: {self._app.TEXT};")
        grid.addWidget(hdr, 0, 0)
        for col_idx, fmt in enumerate(all_formats, start=1):
            lbl = QLabel(dash_runner.display_label(fmt).upper())
            lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {self._app.TEXT};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lbl, 0, col_idx)

        check_vars = {}
        for row_idx, spec in enumerate(specialists, start=1):
            name_lbl = QLabel(
                f"{spec['name']} — {spec['description'][:45]}")
            name_lbl.setFont(QFont("Segoe UI", 8))
            name_lbl.setStyleSheet(f"color: {self._app.TEXT};")
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
                        f"  background: {self._app.BG3};"
                        f"  border: 1px solid {self._app.TEXT2};"
                        f"}}"
                        f"QCheckBox::indicator:checked {{"
                        f"  background: {self._app.ACCENT};"
                        f"  border: 1px solid {self._app.ACCENT};"
                        f"}}"
                        f"QCheckBox::indicator:hover {{"
                        f"  border: 1px solid {self._app.TEXT};"
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
        scroll.setStyleSheet(f"background: {self._app.BG}; border: none;")
        scroll.setMaximumHeight(300)
        lay.addWidget(scroll)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(sep2)

        btn_row = QHBoxLayout()
        _all_selected = [False]

        toggle_btn = QPushButton("☐  Select All")
        toggle_btn.setFont(QFont("Segoe UI", 8))
        toggle_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG2}; color: {self._app.TEXT2}; "
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
            f"QPushButton {{ background: {self._app.BG2}; color: {self._app.TEXT}; "
            f"border: none; padding: 6px 14px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)

        create_btn = QPushButton("📊 Create")
        create_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        create_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT2}; "
            f"color: {self._app.TEXT}; border: none; padding: 6px 14px; }}")
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
            self._run_dashboards(dash_runner, selections)

        create_btn.clicked.connect(_build)

        btn_row.addWidget(toggle_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        lay.addLayout(btn_row)
        dlg.exec()

    # ── Encrypted Dashboards ───────────────────────────────────────────────────

    def _open_encrypted_dashboard_popup(self):
        """Password dialog → build all HTML dashboards → encrypt → basedir/encrypted/."""
        dlg = PasswordConfirmDialog(
            parent      = self,
            title       = "Encrypted Dashboards",
            heading     = "🔒  Encrypted Dashboards",
            description = (
                "Builds all HTML dashboards and encrypts them with AES-256.\n"
                "Output folder: basedir/encrypted/\n"
                "Mobile variants are excluded."
            ),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.get_result() is None:
            return

        password = dlg.get_result()
        self._run_encrypted_dashboards(password)
        password = None  # Passwort sofort aus dem Speicher

    def _run_encrypted_dashboards(self, password: str):
        """Build HTML dashboards (excl. mobile), encrypt, write to basedir/encrypted/."""
        import importlib.util as _ilu

        if not getattr(sys, "frozen", False):
            root = Path(__file__).parent.parent
        elif (hasattr(sys, "_MEIPASS") and
                (Path(sys._MEIPASS) / "scripts").exists()):
            root = Path(sys._MEIPASS) / "scripts"
        else:
            root = Path(sys.executable).parent / "scripts"
        for p in (root / "dashboards", root / "layouts", root / "maps"):
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)

        try:
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            if spec is None:
                raise FileNotFoundError(
                    f"dash_runner.py nicht gefunden: {runner_path}")
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)
        except Exception as exc:
            self._app._log(f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
            return

        try:
            specialists = dash_runner.scan()
        except Exception as exc:
            self._app._log(f"✗ scan() fehlgeschlagen: {exc}")
            return
        if not specialists:
            self._app._log("✗ Keine Dashboards gefunden.")
            return

        # Nur html + html_complex — html_mobile ausgeschlossen
        _ENCRYPT_FORMATS = {"html", "html_complex"}
        selections = [
            (spec["module"], fmt)
            for spec in specialists
            for fmt in spec["formats"]
            if fmt in _ENCRYPT_FORMATS
        ]
        if not selections:
            self._app._log("✗ Keine HTML-Dashboards für Encrypted Export gefunden.")
            return

        s         = self._app._panel_settings._collect_settings()
        date_from = s.get("date_from", "").strip()
        date_to   = s.get("date_to",   "").strip()
        if not date_from:
            from datetime import date as _date, timedelta
            date_from = (_date.today() - timedelta(days=30)).isoformat()
        if not date_to:
            from datetime import date as _date
            date_to = _date.today().isoformat()

        output_dir = Path(s["base_dir"]) / "encrypted"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._app._log("\n🔒  Encrypted Dashboards erstellen ...")
        self._app._log(f"   Output: {output_dir}")
        self._app._log(f"   Zeitraum: {date_from} → {date_to}")

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

                ok  = [r for r in results if r["success"]]
                err = [r for r in results if not r["success"]]

                if err:
                    def _log_err():
                        for r in err:
                            self._app._log(
                                f"  ✗ {r['name']} ({r['format']}): "
                                f"{r.get('error', '')}")
                    self._app._dispatch(_log_err)

                if not ok:
                    self._app._dispatch(
                        lambda: self._app._log("  ✗ Keine Dashboards gebaut."))
                    return

                # ── Encrypt-Pass ───────────────────────────────────────────────
                try:
                    encryptor_path = root / "layouts" / "dash_encryptor.py"
                    enc_spec = _ilu.spec_from_file_location(
                        "dash_encryptor", encryptor_path)
                    if enc_spec is None:
                        raise FileNotFoundError(
                            f"dash_encryptor.py nicht gefunden: {encryptor_path}")
                    dash_encryptor = _ilu.module_from_spec(enc_spec)
                    enc_spec.loader.exec_module(dash_encryptor)
                except Exception as exc:
                    self._app._dispatch(
                        lambda e=exc: self._app._log(
                            f"  ✗ dash_encryptor konnte nicht geladen werden: {e}"))
                    return

                encrypted_count = 0
                encrypt_errors  = []
                for r in ok:
                    html_path = r.get("file")
                    if not html_path or not html_path.exists():
                        continue
                    try:
                        stem     = html_path.stem
                        enc_name = f"{stem}_enc.html"
                        enc_path = output_dir / enc_name

                        html_content = html_path.read_text(encoding="utf-8")
                        encrypted    = dash_encryptor.encrypt_html(
                            html_content, password)

                        html_path.unlink()
                        enc_path.write_text(encrypted, encoding="utf-8")
                        encrypted_count += 1

                    except Exception as exc:
                        encrypt_errors.append(f"{html_path.name}: {exc}")

                def _finish():
                    self._app._log(
                        f"\n  ✓ {encrypted_count} Dashboard(s) verschlüsselt")
                    for e in encrypt_errors:
                        self._app._log(f"  ✗ Encrypt-Fehler: {e}")
                    self._app._log(f"  📁  {output_dir}")
                    os.startfile(str(output_dir))

                self._app._dispatch(_finish)

            except Exception as exc:
                self._app._dispatch(
                    lambda e=exc: self._app._log(f"  ✗ Fehler: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_dashboards(self, dash_runner, selections):
        """Run dashboard build in background thread, stream progress to log."""
        s         = self._app._panel_settings._collect_settings()
        date_from = s.get("date_from", "").strip()
        date_to   = s.get("date_to",   "").strip()
        if not date_from:
            date_from = (date.today() - timedelta(days=30)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()
        output_dir = Path(s["base_dir"]) / "dashboards"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._app._log("\n▶  Berichte erstellen ...")
        self._app._log(f"   Output: {output_dir}")
        self._app._log(f"   Zeitraum: {date_from} → {date_to}")

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

                def on_done():
                    ok  = [r for r in results if r["success"]]
                    err = [r for r in results if not r["success"]]
                    self._app._log(f"\n  ✓ {len(ok)} Bericht(e) erstellt")
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
                    # Regenerate mobile landing page with fresh dashboard content
                    try:
                        import garmin_mobile_landing as _landing
                        _landing.write_index_html(s["base_dir"])
                    except Exception:
                        pass
                    if ok:
                        os.startfile(str(output_dir))

                self._app._dispatch(on_done)
            except Exception as exc:
                self._app._dispatch(
                    lambda e=exc: self._app._log(f"  ✗ Fehler: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    # ── All-dashboards build (used by Daily Sync chain) ───────────────────────

    def _run_all_dashboards(self, *, on_done=None):
        """Build all specialists / all formats — no dialog, no date filter.

        Mirrors daily_update._run_dashboards(): scans all specialists, selects
        all formats, uses the full archive date range from summary/*.json.
        Fires on_done on the Main Thread when complete (success or error).
        """
        import importlib.util as _ilu

        if not getattr(sys, "frozen", False):
            root = Path(__file__).parent.parent
        elif (hasattr(sys, "_MEIPASS") and
                (Path(sys._MEIPASS) / "scripts").exists()):
            root = Path(sys._MEIPASS) / "scripts"
        else:
            root = Path(sys.executable).parent / "scripts"
        for p in (root / "dashboards", root / "layouts", root / "maps"):
            _s = str(p)
            if _s not in sys.path:
                sys.path.insert(0, _s)

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
        _candidates = [
            _exe_dir / "info" / "daily_update_task.xml",
            Path(__file__).parent.parent / "scheduler" / "daily_update_task.xml",
        ]
        template_path = next((p for p in _candidates if p.exists()), None)
        if template_path is None:
            QMessageBox.critical(
                self._app, "Task Scheduler XML",
                "Template file 'daily_update_task.xml' not found.\n"
                "Expected in docs/ (dev) or info/ (build).",
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
