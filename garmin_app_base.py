#!/usr/bin/env python3
"""
garmin_app_base.py
Garmin Local Archive — QMainWindow Base

GarminApp — PyQt6 QMainWindow assembler. Owns shared state, log widget,
_dispatch(), and startup sequence. All panel logic lives in app/panel_*.py.

Execution-model hooks (abstract — subclass implements):
  _run(script_name, ...)  — subprocess (App) or importlib (Standalone)
  _log_bg(text)           — thread-safe log dispatch
  _is_running() -> bool   — sync running state
  _stop_collector()       — stop running sync

Worker rule (D-5): workers never touch widgets.
  All UI updates via self._dispatch(fn) or self._dispatch(lambda: ...).

v1.5.4 — PyQt6 migration
  Panels are QWidget subclasses, composed via self._panel_*.
  Mixin inheritance replaced by composition (D-1).
  pyqtSignal replaces self.after() for cross-thread dispatch (D-2).
  threading.Thread retained — QThread not introduced (D-3).
  Shared state remains on GarminApp with Owner-Matrix (D-4).
"""

import sys
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QPlainTextEdit, QSplitter,
    QScrollArea, QFrame, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor

import garmin_app_settings as _settings
import garmin_app_controller as _controller

from app.panel_settings   import PanelSettings
from app.panel_connection import PanelConnection
from app.panel_archive    import PanelArchive
from app.panel_timer      import PanelTimer
from app.panel_outputs    import PanelOutputs

# ── Settings — re-exported for garmin_app.py / garmin_app_standalone.py ───────
SETTINGS_FILE    = _settings.SETTINGS_FILE
DEFAULT_SETTINGS = _settings.DEFAULT_SETTINGS
load_settings    = _settings.load_settings
save_password    = _settings.save_password
load_password    = _settings.load_password
delete_password  = _settings.delete_password
_open_url        = _settings._open_url

from version import APP_VERSION


class GarminApp(QMainWindow):
    """
    QMainWindow assembler for Garmin Local Archive.

    Worker rule (D-5): no panel or worker may read or write widgets
    from a background thread. All UI updates must go through _dispatch().

    State ownership (D-4):
      _ctx_running         → PanelOutputs (write) / others read
      _context_stop_event  → PanelOutputs (write) / cross-thread .set()
      _mirror_running      → PanelArchive (write) / others read
      _connection_verified → PanelConnection (write) / others read
      _timer_active        → PanelTimer (write) / others read
      _timer_stop          → PanelTimer (write) / cross-thread .set()
      _timer_generation    → PanelTimer (write) / others read
      _stopped_by_user     → PanelOutputs (write) / others read
      _last_html           → PanelOutputs (write) / others read
    """

    # ── Colors (class attributes — available to all panels via self._app.*) ────
    BG      = "#12101f"
    BG2     = "#1a1729"
    BG3     = "#231f38"
    ACCENT  = "#a259f7"
    ACCENT2 = "#6e3fcf"
    TEXT    = "#eaeaea"
    TEXT2   = "#a0a0b0"
    GREEN   = "#4ecca3"
    YELLOW  = "#f5a623"

    # ── Thread-safe dispatch signal (D-2) ──────────────────────────────────────
    # Defined at class level — emitting from any thread queues execution
    # on the Main Thread automatically (Qt queued connection).
    _dispatch_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.settings = load_settings()

        # Connect dispatch signal to slot — Qt routes cross-thread emissions
        # via queued connection automatically.
        self._dispatch_signal.connect(self._dispatch_slot)

        # ── Shared State (D-4) ─────────────────────────────────────────────────
        self._last_html           = None
        self._stopped_by_user     = False
        self._connection_verified = False
        self._timer_conn_verified = False
        self._timer_active        = False
        self._timer_stop          = threading.Event()
        self._timer_next_mode     = "repair"
        self._timer_generation    = 0
        self._ctx_running         = False
        self._context_stop_event  = threading.Event()
        self._dialog_open         = False

        # ── Window ────────────────────────────────────────────────────────────
        self.setWindowTitle("Garmin Local Archive")
        self.setMinimumSize(920, 760)
        self.resize(1100, 900)
        self.setStyleSheet(f"background: {self.BG}; color: {self.TEXT};")

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── Load settings into panels ─────────────────────────────────────────
        self._panel_settings.load_settings_to_ui()
        self._panel_timer.load_timer_settings(self.settings)

        # ── Startup ───────────────────────────────────────────────────────────
        QTimer.singleShot(0,   self._check_migration)
        QTimer.singleShot(200, self._panel_archive._refresh_archive_info)
        QTimer.singleShot(500, self._startup_bg_checks)

    @pyqtSlot(object)
    def _dispatch_slot(self, fn):
        """Receives callables from _dispatch_signal and executes on Main Thread."""
        fn()

    def _startup_bg_checks(self):
        """Deferred startup — ensures all panels are fully constructed."""
        threading.Thread(
            target=self._check_version, daemon=True).start()
        threading.Thread(
            target=self._panel_archive._startup_integrity_check,
            daemon=True).start()
        threading.Thread(
            target=self._panel_archive._startup_mirror_check,
            daemon=True).start()

    # ── UI builder ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background: {self.BG};")
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(f"background: {self.BG3};")
        header.setFixedHeight(46)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)
        h_lay.setSpacing(8)

        unicorn = QLabel("🦄  GARMIN LOCAL ARCHIVE")
        unicorn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        unicorn.setStyleSheet(f"color: {self.TEXT}; background: transparent;")
        unicorn.setCursor(Qt.CursorShape.PointingHandCursor)
        unicorn.mousePressEvent = lambda e: self._run_extended_analysis()

        ver_lbl = QLabel(APP_VERSION)
        ver_lbl.setFont(QFont("Segoe UI", 9))
        ver_lbl.setStyleSheet(f"color: {self.TEXT2}; background: transparent;")

        tagline = QLabel("local · private · yours")
        tagline.setFont(QFont("Segoe UI", 9))
        tagline.setStyleSheet(f"color: {self.TEXT}; background: transparent;")

        link = QLabel("www.github.com/Wewoc/Garmin_Local_Archive")
        link.setFont(QFont("Segoe UI", 8))
        link.setStyleSheet(
            "color: #6ab0f5; text-decoration: underline; background: transparent;")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.mousePressEvent = lambda e: _open_url(
            "https://www.github.com/Wewoc/Garmin_Local_Archive")

        gpl = QLabel("GNU GPL v3")
        gpl.setFont(QFont("Segoe UI", 8))
        gpl.setStyleSheet(f"color: {self.TEXT2}; background: transparent;")

        h_lay.addWidget(unicorn)
        h_lay.addWidget(ver_lbl)
        h_lay.addWidget(tagline)
        h_lay.addStretch()
        h_lay.addWidget(link)
        h_lay.addWidget(gpl)
        root_lay.addWidget(header)

        # ── Main area — left (Settings) + right (Actions) ─────────────────────
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {self.BG3}; width: 2px; }}")

        # Left — Settings panel in scroll area
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(310)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setStyleSheet(f"background: {self.BG2};")
        self._panel_settings = PanelSettings(self)
        left_scroll.setWidget(self._panel_settings)
        main_splitter.addWidget(left_scroll)

        # Right — Connection + Timer + Outputs in scroll area
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setStyleSheet(f"background: {self.BG};")

        right_widget = QWidget()
        right_widget.setStyleSheet(f"background: {self.BG};")
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._panel_connection = PanelConnection(self)
        self._panel_timer      = PanelTimer(self)
        self._panel_outputs    = PanelOutputs(self)
        self._panel_archive    = PanelArchive(self)

        right_lay.addWidget(self._panel_connection)
        right_lay.addWidget(self._panel_timer)
        right_lay.addWidget(self._panel_outputs)
        right_lay.addStretch()
        right_scroll.setWidget(right_widget)
        main_splitter.addWidget(right_scroll)

        main_splitter.setSizes([310, 790])
        root_lay.addWidget(main_splitter, stretch=1)

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = QWidget()
        log_frame.setStyleSheet(f"background: {self.BG};")
        log_lay = QVBoxLayout(log_frame)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(0)

        log_bar = QWidget()
        log_bar.setStyleSheet(f"background: {self.BG3};")
        log_bar.setFixedHeight(28)
        log_bar_lay = QHBoxLayout(log_bar)
        log_bar_lay.setContentsMargins(12, 0, 12, 0)
        log_hdr = QLabel("LOG")
        log_hdr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        log_hdr.setStyleSheet(f"color: {self.ACCENT}; background: transparent;")
        clear_btn = QPushButton("Clear")
        clear_btn.setFont(QFont("Segoe UI", 7))
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {self.TEXT2}; "
            f"border: none; padding: 2px 6px; }}"
            f"QPushButton:hover {{ color: {self.TEXT}; }}")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_log)
        log_bar_lay.addWidget(log_hdr)
        log_bar_lay.addStretch()
        log_bar_lay.addWidget(clear_btn)
        log_lay.addWidget(log_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 8))
        self.log.setStyleSheet(
            f"QPlainTextEdit {{ background: #0a0a1a; color: {self.GREEN}; "
            f"border: none; padding: 4px; }}")
        self.log.setFixedHeight(180)
        log_lay.addWidget(self.log)
        root_lay.addWidget(log_frame)

    # ── Dispatch — thread-safe UI update via pyqtSignal ───────────────────────

    def _dispatch(self, fn, *args):
        """Schedule fn(*args) on the Main Thread. Safe to call from any thread.
        Qt routes the signal emission via queued connection automatically."""
        if args:
            self._dispatch_signal.emit(lambda: fn(*args))
        else:
            self._dispatch_signal.emit(fn)

    # ── Log helpers ────────────────────────────────────────────────────────────

    def _log(self, text: str):
        """Write to log widget. Main Thread only."""
        if not hasattr(self, "log"):
            return
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _log_bg(self, text: str):
        """Thread-safe log write — dispatches to Main Thread."""
        self._dispatch(self._log, text)

    def _clear_log(self):
        self.log.clear()

    # ── Settings passthrough ───────────────────────────────────────────────────

    def _collect_settings(self) -> dict:
        """Central settings reader — delegates to PanelSettings.
        Timer fields are merged from PanelTimer. Called by Controller and panels."""
        s = self._panel_settings._collect_settings()
        s.update(self._panel_timer.get_timer_settings())
        return s

    def _safe_save(self, s: dict = None):
        self._panel_settings._safe_save(s)

    # ── Execution-model hooks (abstract) ───────────────────────────────────────

    def _run(self, script_name: str, enable_stop: bool = False,
             on_success=None, refresh_failed: bool = False,
             on_done=None, log_prefix: str = "garmin",
             env_overrides: dict = None, stop_event: threading.Event = None,
             days_left: int = None):
        """Subclass implements: subprocess (App) or importlib (Standalone)."""
        raise NotImplementedError

    def _is_running(self) -> bool:
        """Returns True if a sync is currently running. Subclass implements."""
        raise NotImplementedError

    def _stop_collector(self):
        """Stop running sync. Subclass implements."""
        raise NotImplementedError

    # ── ENV builder ────────────────────────────────────────────────────────────

    def _build_env_dict(self, s: dict, refresh_failed: bool = False) -> dict:
        return _controller.build_env_dict(s, refresh_failed)

    # ── Migration ──────────────────────────────────────────────────────────────

    def _check_migration(self):
        s        = self._collect_settings()
        base_dir = Path(s.get("base_dir", "")).expanduser()
        if not _controller.check_migration_needed(base_dir):
            return

        answer = QMessageBox.question(
            self, "Structure migration required",
            f"Old folder structure detected in:\n{base_dir}\n\n"
            f"The folders raw/, summary/ and log/ will be moved to\n"
            f"garmin_data/.\n\n"
            f"⚠ Recommendation: Create a manual backup of:\n"
            f"{base_dir}\n\n"
            f"Migrate now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            QMessageBox.information(
                self, "App blocked",
                "The app cannot be used without migration.\n"
                "Please restart the app after creating a manual backup.",
            )
            self.close()
            return

        result = _controller.run_migration(base_dir)
        if result == "ok":
            QMessageBox.information(
                self, "Migration complete",
                f"Folders successfully moved to:\n{base_dir / 'garmin_data'}",
            )
        else:
            QMessageBox.critical(
                self, "Migration error",
                "Error moving folders.\n\n"
                "Please migrate manually and restart the app.",
            )
            self.close()

    # ── Version check ──────────────────────────────────────────────────────────

    def _check_version(self):
        import urllib.request
        import json as _json
        url = ("https://api.github.com/repos/Wewoc/"
               "Garmin_Local_Archive/releases/latest")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "GarminLocalArchive"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            latest = data.get("tag_name", "").strip()
            if latest and latest.lstrip("vV") != APP_VERSION.lstrip("vV"):
                self._dispatch(self._show_update_popup, latest)
        except Exception:
            pass

    def _show_update_popup(self, latest: str):
        import webbrowser
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Update Available")
        dlg.setText(
            f"A new version is available: {latest}\n"
            f"You are running: {APP_VERSION}"
        )
        dlg.setStyleSheet(f"background: {self.BG}; color: {self.TEXT};")
        open_btn  = dlg.addButton("Open GitHub",
                                   QMessageBox.ButtonRole.AcceptRole)
        dlg.addButton("Dismiss", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        if dlg.clickedButton() == open_btn:
            webbrowser.open(
                "https://github.com/Wewoc/Garmin_Local_Archive/releases/latest")

    # ── Extended Analysis (Easter Egg) ─────────────────────────────────────────

    def _run_extended_analysis(self):
        """Subclass (garmin_app.py) overrides with _find_python() access."""
        pass

    def _find_script(self, name: str):
        candidates = [
            Path(sys.executable).parent / "scripts" / name,
            Path(__file__).parent / "garmin" / name,
            Path(__file__).parent / name,
        ]
        return next((p for p in candidates if p.exists()), None)

    # ── Close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """D-9: set all stop events, join threads with timeout, save settings."""
        self._timer_generation += 1
        self._timer_stop.set()
        self._context_stop_event.set()

        for t in threading.enumerate():
            if t.daemon and t != threading.main_thread():
                t.join(timeout=2.0)

        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        self._safe_save(self.settings)
        super().closeEvent(event)