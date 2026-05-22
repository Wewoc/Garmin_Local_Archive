"""
tests/test_qt_app.py
Garmin Local Archive — PyQt6 App Layer Test Suite

Run with:
    pytest tests/test_qt_app.py -v

Scope: Qt-specific behaviour — Signals, Slots, Widget state,
       panel instantiation. Does NOT duplicate test_app_logic.py.

v1.5.4 — Panel-by-panel, built alongside the migration.
"""

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication


# ══════════════════════════════════════════════════════════════════════════════
#  1. Smoke — QApplication starts cleanly
# ══════════════════════════════════════════════════════════════════════════════

class TestQtSmoke:

    def test_qapplication_instance(self, qtbot):
        """QApplication must exist — pytest-qt creates it via qtbot fixture."""
        app = QApplication.instance()
        assert app is not None

    def test_pyqt6_importable(self):
        """Core PyQt6 modules must be importable."""
        from PyQt6.QtWidgets import QWidget, QMainWindow, QLabel
        from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject, Qt
        from PyQt6.QtGui import QFont
        assert True

    def test_settings_controller_still_gui_free(self, app_root):
        """garmin_app_settings and garmin_app_controller must stay tkinter/Qt-free.
        Mirrors Section 15 of test_app_logic.py — runs here too as regression guard."""
        import ast

        GUI_BLACKLIST = {
            "tkinter", "tkinter.ttk", "tkinter.messagebox",
            "tkinter.filedialog", "tkinter.scrolledtext",
            "PyQt6", "PyQt5", "PySide6", "PySide2",
        }

        def gui_imports(path: Path) -> list:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in GUI_BLACKLIST:
                            found.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod in GUI_BLACKLIST or mod.split(".")[0] in GUI_BLACKLIST:
                        found.append(mod)
            return found

        assert gui_imports(app_root / "app" / "garmin_app_settings.py") == []
        assert gui_imports(app_root / "app" / "garmin_app_controller.py") == []


# ══════════════════════════════════════════════════════════════════════════════
#  2. PanelSettings
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelSettings:

    @pytest.fixture
    def app_mock(self):
        """Minimal app stub — provides constants and settings PanelSettings needs."""
        from unittest.mock import MagicMock
        app = MagicMock()
        app.BG      = "#12101f"
        app.BG2     = "#1a1729"
        app.BG3     = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT    = "#eaeaea"
        app.TEXT2   = "#a0a0b0"
        app.YELLOW  = "#f5a623"
        app.settings = {
            "email": "test@example.com",
            "sync_mode": "recent",
            "sync_days": "90",
            "sync_from": "",
            "sync_to": "",
            "sync_auto_fallback": "",
            "date_from": "",
            "date_to": "",
            "age": "35",
            "sex": "male",
            "request_delay_min": "5.0",
            "request_delay_max": "20.0",
            "context_latitude": "0.0",
            "context_longitude": "0.0",
            "context_location": "",
            "mirror_dir": "",
            "timer_min_interval": "5",
            "timer_max_interval": "30",
            "timer_min_days": "3",
            "timer_max_days": "10",
            "backup_raw_backfill_asked": False,
        }
        app._is_running.return_value = False
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_password", return_value=""):
            from app.panel_settings import PanelSettings
            panel = PanelSettings(app_mock)
            qtbot.addWidget(panel)
        assert panel is not None

    def test_collect_settings_keys(self, qtbot, app_mock):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_password", return_value=""):
            from app.panel_settings import PanelSettings
            panel = PanelSettings(app_mock)
            qtbot.addWidget(panel)
        s = panel._collect_settings()
        required = [
            "email", "password", "base_dir", "sync_mode", "sync_days",
            "sync_from", "sync_to", "sync_auto_fallback", "date_from",
            "date_to", "age", "sex", "request_delay_min", "request_delay_max",
            "context_location", "context_latitude", "context_longitude",
            "mirror_dir", "backup_raw_backfill_asked",
        ]
        for key in required:
            assert key in s, f"missing key: {key}"

    def test_sync_mode_change_recent(self, qtbot, app_mock):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_password", return_value=""):
            from app.panel_settings import PanelSettings
            panel = PanelSettings(app_mock)
            qtbot.addWidget(panel)
        # Erst auf range wechseln damit recent ein echter Change ist
        panel._sync_mode.setCurrentText("range")
        panel._sync_mode.setCurrentText("recent")
        assert panel._sync_days.isEnabled()
        assert not panel._sync_from.isEnabled()
        assert not panel._sync_to.isEnabled()
        assert not panel._sync_fallback.isEnabled()

    def test_sync_mode_change_range(self, qtbot, app_mock):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_password", return_value=""):
            from app.panel_settings import PanelSettings
            panel = PanelSettings(app_mock)
            qtbot.addWidget(panel)
        panel._sync_mode.setCurrentText("range")
        assert not panel._sync_days.isEnabled()
        assert panel._sync_from.isEnabled()
        assert panel._sync_to.isEnabled()
        assert not panel._sync_fallback.isEnabled()

    def test_set_location_from_maps(self, qtbot, app_mock):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_password", return_value=""):
            from app.panel_settings import PanelSettings
            panel = PanelSettings(app_mock)
            qtbot.addWidget(panel)
        url = "https://www.google.com/maps/@52.1234,8.5678,15z"
        panel._maps_url.setText(url)
        with patch.object(panel, "_safe_save"):
            panel._set_location_from_maps()
        assert app_mock.settings["context_latitude"] == "52.1234"
        assert app_mock.settings["context_longitude"] == "8.5678"
        assert panel._ctx_coords_label.text() == "lat 52.1234  lon 8.5678"


# ══════════════════════════════════════════════════════════════════════════════
#  3. PanelConnection
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelConnection:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        app = MagicMock()
        app.BG      = "#12101f"
        app.BG2     = "#1a1729"
        app.BG3     = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT    = "#eaeaea"
        app.TEXT2   = "#a0a0b0"
        app.GREEN   = "#4ecca3"
        app.YELLOW  = "#f5a623"
        app._dialog_open         = False
        app._connection_verified = False
        app._panel_archive       = MagicMock()
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_indicators_present(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        for key in ("token", "login", "api", "data"):
            assert key in panel._conn_indicators

    def test_set_indicator_ok(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("token", "ok")
        assert app_mock.GREEN in panel._conn_indicators["token"].styleSheet()

    def test_set_indicator_fail(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("login", "fail")
        assert "#e94560" in panel._conn_indicators["login"].styleSheet()

    def test_set_indicator_reset(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("api", "reset")
        assert app_mock.TEXT2 in panel._conn_indicators["api"].styleSheet()

    def test_mirror_button_disabled_by_default(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        assert not panel._mirror_btn.isEnabled()

    def test_restore_button_disabled_by_default(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        assert not panel._restore_btn.isEnabled()

    def test_set_mirror_button_state_enable(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel.set_mirror_button_state(True, text="🔁  Mirroring...")
        assert panel._mirror_btn.isEnabled()
        assert panel._mirror_btn.text() == "🔁  Mirroring..."

    def test_set_restore_button_state_enable(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel.set_restore_button_state(True, text="Restore Data")
        assert panel._restore_btn.isEnabled()

    def test_prompt_signal_defined_at_class_level(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        assert hasattr(PanelConnection, "_prompt_requested")


# ══════════════════════════════════════════════════════════════════════════════
#  4. PanelArchive
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelArchive:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        app = MagicMock()
        app.BG      = "#12101f"
        app.BG2     = "#1a1729"
        app.BG3     = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT    = "#eaeaea"
        app.TEXT2   = "#a0a0b0"
        app.GREEN   = "#4ecca3"
        app.YELLOW  = "#f5a623"
        app._timer_active = False
        app._ctx_running  = False
        app._is_running.return_value = False
        app._panel_settings._collect_settings.return_value = {
            "base_dir":   "",
            "mirror_dir": "",
            "sync_mode":  "recent",
            "sync_days":  "90",
            "sync_from":  "",
            "sync_to":    "",
        }
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_mirror_running_false_by_default(self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        assert panel._mirror_running is False

    def test_refresh_archive_info_no_crash_when_log_missing(self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        # base_dir is empty — log_path won't exist — must not raise
        panel._refresh_archive_info()

    def test_on_mirror_blocked_when_already_running(self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        panel._mirror_running = True
        # Must return immediately without calling set_mirror_button_state
        panel._on_mirror()
        app_mock._panel_connection.set_mirror_button_state.assert_not_called()

    def test_check_failed_days_popup_returns_false_when_log_missing(
            self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._check_failed_days_popup("", "recent", "90", "", "")
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
#  5. PanelTimer
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelTimer:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        import threading
        app = MagicMock()
        app.BG      = "#12101f"
        app.BG2     = "#1a1729"
        app.BG3     = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT    = "#eaeaea"
        app.TEXT2   = "#a0a0b0"
        app.GREEN   = "#4ecca3"
        app.YELLOW  = "#f5a623"
        app._timer_active        = False
        app._timer_generation    = 0
        app._timer_stop          = threading.Event()
        app._timer_next_mode     = "repair"
        app._timer_conn_verified = False
        app._connection_verified = False
        app._panel_settings._collect_settings.return_value = {
            "email":    "test@example.com",
            "password": "secret",
            "base_dir": "",
            "timer_min_interval": "5",
            "timer_max_interval": "30",
            "timer_min_days":     "3",
            "timer_max_days":     "10",
        }
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_timer_fields_present(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        assert panel._timer_min_interval is not None
        assert panel._timer_max_interval is not None
        assert panel._timer_min_days is not None
        assert panel._timer_max_days is not None

    def test_load_timer_settings(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        panel.load_timer_settings({
            "timer_min_interval": "10",
            "timer_max_interval": "60",
            "timer_min_days":     "5",
            "timer_max_days":     "20",
        })
        assert panel._timer_min_interval.text() == "10"
        assert panel._timer_max_interval.text() == "60"
        assert panel._timer_min_days.text()     == "5"
        assert panel._timer_max_days.text()     == "20"

    def test_toggle_timer_starts_when_off(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        panel._toggle_timer()
        assert app_mock._timer_active is True

    def test_toggle_timer_stops_when_on(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        app_mock._timer_active = True
        panel._toggle_timer()
        assert app_mock._timer_active is False

    def test_resume_does_nothing_when_was_not_active(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        panel._timer_resume_after_sync(was_active=False)
        assert app_mock._timer_active is False

    def test_get_timer_settings_returns_all_keys(self, qtbot, app_mock):
        from app.panel_timer import PanelTimer
        panel = PanelTimer(app_mock)
        qtbot.addWidget(panel)
        result = panel.get_timer_settings()
        for key in ("timer_min_interval", "timer_max_interval",
                    "timer_min_days", "timer_max_days"):
            assert key in result


# ══════════════════════════════════════════════════════════════════════════════
#  6. PanelOutputs
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelOutputs:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        import threading
        app = MagicMock()
        app.BG      = "#12101f"
        app.BG2     = "#1a1729"
        app.BG3     = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT    = "#eaeaea"
        app.TEXT2   = "#a0a0b0"
        app.GREEN   = "#4ecca3"
        app.YELLOW  = "#f5a623"
        app._timer_active        = False
        app._timer_stop          = threading.Event()
        app._ctx_running         = False
        app._context_stop_event  = threading.Event()
        app._last_html           = None
        app._connection_verified = False
        app.settings             = {"backup_raw_backfill_asked": False}
        app._panel_settings._collect_settings.return_value = {
            "email":             "test@example.com",
            "password":          "secret",
            "base_dir":          "",
            "sync_mode":         "recent",
            "sync_days":         "90",
            "sync_from":         "",
            "sync_to":           "",
            "date_from":         "",
            "date_to":           "",
            "context_latitude":  "0.0",
            "context_longitude": "0.0",
        }
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_ctx_btn_enabled_by_default(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel._ctx_btn.isEnabled()

    def test_ctx_stop_btn_disabled_by_default(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert not panel._ctx_stop_btn.isEnabled()

    def test_stop_context_sync_sets_event(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        panel._stop_context_sync()
        assert app_mock._context_stop_event.is_set()

    def test_on_context_sync_done_resets_state(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        # Simulate running state
        panel._ctx_btn.setEnabled(False)
        panel._ctx_stop_btn.setEnabled(True)
        app_mock._ctx_running = True
        panel._on_context_sync_done()
        assert panel._ctx_btn.isEnabled()
        assert not panel._ctx_stop_btn.isEnabled()
        assert app_mock._ctx_running is False

    def test_run_context_sync_blocked_when_no_coordinates(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        from unittest.mock import patch
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        # coordinates are 0.0 / 0.0 — should show warning, not start thread
        with patch("PyQt6.QtWidgets.QMessageBox.warning"):
            panel._run_context_sync()
        assert app_mock._ctx_running is False

    def test_copy_last_error_log_no_crash_when_folder_missing(
            self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        panel._copy_last_error_log()
        app_mock._log.assert_called()


# ══════════════════════════════════════════════════════════════════════════════
#  7. GarminApp (Base)
# ══════════════════════════════════════════════════════════════════════════════

class TestGarminAppBase:

    def test_app_instantiates(self, qtbot):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_settings", return_value={
            "email": "", "password": "", "base_dir": "",
            "sync_mode": "recent", "sync_days": "90",
            "sync_from": "", "sync_to": "", "sync_auto_fallback": "",
            "date_from": "", "date_to": "", "age": "35", "sex": "male",
            "request_delay_min": "5.0", "request_delay_max": "20.0",
            "context_latitude": "0.0", "context_longitude": "0.0",
            "context_location": "", "mirror_dir": "",
            "timer_min_interval": "5", "timer_max_interval": "30",
            "timer_min_days": "3", "timer_max_days": "10",
            "backup_raw_backfill_asked": False,
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    # Suppress settings save during pytest-qt teardown —
                    # prevents overwriting real settings file with empty test values.
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        assert app is not None

    def test_all_panels_created(self, qtbot):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_settings", return_value={
            "email": "", "password": "", "base_dir": "",
            "sync_mode": "recent", "sync_days": "90",
            "sync_from": "", "sync_to": "", "sync_auto_fallback": "",
            "date_from": "", "date_to": "", "age": "35", "sex": "male",
            "request_delay_min": "5.0", "request_delay_max": "20.0",
            "context_latitude": "0.0", "context_longitude": "0.0",
            "context_location": "", "mirror_dir": "",
            "timer_min_interval": "5", "timer_max_interval": "30",
            "timer_min_days": "3", "timer_max_days": "10",
            "backup_raw_backfill_asked": False,
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    # Suppress settings save during pytest-qt teardown —
                    # prevents overwriting real settings file with empty test values.
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        for attr in ("_panel_settings", "_panel_connection",
                     "_panel_archive", "_panel_timer", "_panel_outputs"):
            assert hasattr(app, attr), f"missing: {attr}"

    def test_log_writes_to_widget(self, qtbot):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_settings", return_value={
            "email": "", "password": "", "base_dir": "",
            "sync_mode": "recent", "sync_days": "90",
            "sync_from": "", "sync_to": "", "sync_auto_fallback": "",
            "date_from": "", "date_to": "", "age": "35", "sex": "male",
            "request_delay_min": "5.0", "request_delay_max": "20.0",
            "context_latitude": "0.0", "context_longitude": "0.0",
            "context_location": "", "mirror_dir": "",
            "timer_min_interval": "5", "timer_max_interval": "30",
            "timer_min_days": "3", "timer_max_days": "10",
            "backup_raw_backfill_asked": False,
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    # Suppress settings save during pytest-qt teardown —
                    # prevents overwriting real settings file with empty test values.
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        app._log("Hello test")
        assert "Hello test" in app.log.toPlainText()

    def test_collect_settings_returns_timer_fields(self, qtbot):
        from unittest.mock import patch
        with patch("garmin_app_settings.load_settings", return_value={
            "email": "", "password": "", "base_dir": "",
            "sync_mode": "recent", "sync_days": "90",
            "sync_from": "", "sync_to": "", "sync_auto_fallback": "",
            "date_from": "", "date_to": "", "age": "35", "sex": "male",
            "request_delay_min": "5.0", "request_delay_max": "20.0",
            "context_latitude": "0.0", "context_longitude": "0.0",
            "context_location": "", "mirror_dir": "",
            "timer_min_interval": "5", "timer_max_interval": "30",
            "timer_min_days": "3", "timer_max_days": "10",
            "backup_raw_backfill_asked": False,
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    # Suppress settings save during pytest-qt teardown —
                    # prevents overwriting real settings file with empty test values.
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        s = app._collect_settings()
        for key in ("timer_min_interval", "timer_max_interval",
                    "timer_min_days", "timer_max_days"):
            assert key in s