# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
tests/test_qt_app.py
Garmin Local Archive — PyQt6 App Layer Test Suite

Run with:
    pytest tests/test_qt_app.py -v

Scope: Qt-specific behaviour — Signals, Slots, Widget state,
       panel instantiation. Does NOT duplicate test_app_logic.py.

v1.5.4 — Panel-by-panel, built alongside the migration.
"""

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

    def test_daily_update_gui_free(self, app_root):
        """scheduler/daily_update.py must never import any GUI framework.
        Headless entry point — GUI imports would break T3.2 (standalone headless)."""
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

        assert gui_imports(app_root / "scheduler" / "daily_update.py") == []


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
        from PyQt6.QtWidgets import QLabel
        from PyQt6.QtGui import QFont
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
        # _conn_indicators lives in panel_home — provide real QLabel dict
        # so _set_indicator() can call setStyleSheet() on real widgets.
        _indicators = {}
        for key in ("token", "login", "api", "data"):
            dot = QLabel("●")
            dot.setFont(QFont("Segoe UI", 10))
            dot.setStyleSheet(f"color: {app.TEXT2};")
            _indicators[key] = dot
        app._panel_home._conn_indicators = _indicators
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
        # _conn_indicators lives in panel_home since v1.6
        for key in ("token", "login", "api", "data"):
            assert key in app_mock._panel_home._conn_indicators

    def test_set_indicator_ok(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("token", "ok")
        assert app_mock.GREEN in app_mock._panel_home._conn_indicators["token"].styleSheet()

    def test_set_indicator_fail(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("login", "fail")
        assert "#e94560" in app_mock._panel_home._conn_indicators["login"].styleSheet()

    def test_set_indicator_reset(self, qtbot, app_mock):
        from app.panel_connection import PanelConnection
        panel = PanelConnection(app_mock)
        qtbot.addWidget(panel)
        panel._set_indicator("api", "reset")
        assert app_mock.TEXT2 in app_mock._panel_home._conn_indicators["api"].styleSheet()

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
#  PasswordConfirmDialog — setup vs. unlock mode
# ══════════════════════════════════════════════════════════════════════════════

class TestPasswordConfirmDialog:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        app = MagicMock()
        app.BG     = "#12101f"
        app.BG3    = "#231f38"
        app.TEXT   = "#eaeaea"
        app.TEXT2  = "#a0a0b0"
        app.ACCENT = "#a259f7"
        return app

    def _fake_parent(self, qtbot, app_mock):
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        parent._app = app_mock
        qtbot.addWidget(parent)
        return parent

    def test_default_mode_is_setup_with_confirm_field(self, qtbot, app_mock):
        from app.dialogs import PasswordConfirmDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = PasswordConfirmDialog(parent, "T", "H", "D")
        qtbot.addWidget(dlg)
        assert dlg._pw2 is not None

    def test_setup_mode_has_confirm_field(self, qtbot, app_mock):
        from app.dialogs import PasswordConfirmDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = PasswordConfirmDialog(parent, "T", "H", "D", mode="setup")
        qtbot.addWidget(dlg)
        assert dlg._pw2 is not None

    def test_unlock_mode_has_no_confirm_field(self, qtbot, app_mock):
        from app.dialogs import PasswordConfirmDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = PasswordConfirmDialog(parent, "T", "H", "D", mode="unlock")
        qtbot.addWidget(dlg)
        assert dlg._pw2 is None

    def test_unlock_mode_accepts_single_password(self, qtbot, app_mock):
        from app.dialogs import PasswordConfirmDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = PasswordConfirmDialog(parent, "T", "H", "D", mode="unlock")
        qtbot.addWidget(dlg)
        dlg._pw1.setText("mypassword")
        dlg._on_ok()
        assert dlg.get_result() == "mypassword"


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
#  7. PanelChat
# ══════════════════════════════════════════════════════════════════════════════
# Smoke-level only — no real threading.Thread runs (would hit the real
# Ollama HTTP client). Worker-callback methods (_chat_on_reply/_chat_on_error/
# etc.) are called directly instead of via the background thread, mirroring
# the pattern already used for TestPanelOutputs/TestPanelTimer.

class TestPanelChat:

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
        app.YELLOW  = "#f5a623"
        app._panel_settings._collect_settings.return_value = {
            "base_dir": "",
        }
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_input_and_send_disabled_before_start(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert not panel._input.isEnabled()
        assert not panel._send_btn.isEnabled()
        assert not panel._model_combo.isEnabled()
        assert not panel._new_chat_btn.isEnabled()

    def test_send_noop_on_empty_input(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._input.setText("   ")
        panel._chat_on_send()
        assert panel._history == []
        assert panel._request_running is False

    def test_send_noop_while_request_running(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._input.setText("hello")
        panel._chat_on_send()
        assert panel._history == []

    def test_chat_on_reply_resets_state_and_appends_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._send_btn.setEnabled(False)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_reply("hello back")
        assert panel._request_running is False
        assert panel._send_btn.isEnabled()
        assert panel._history[-1] == {"role": "assistant", "content": "hello back"}

    def test_chat_on_error_pops_trailing_user_message(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_error(Exception("boom"))
        assert panel._request_running is False
        assert panel._history == []

    def test_chat_on_error_no_pop_when_history_not_ending_in_user(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "system", "content": "sys"},
                           {"role": "assistant", "content": "ok"}]
        panel._chat_on_error(Exception("boom"))
        assert panel._history == [{"role": "system", "content": "sys"},
                                   {"role": "assistant", "content": "ok"}]

    def test_chat_on_error_no_crash_on_empty_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = []
        panel._chat_on_error(Exception("boom"))
        assert panel._history == []

    def test_refresh_age_display_file_missing(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_refresh_age_display()
        assert "not found" in panel._age_label.text()

    def test_refresh_age_display_no_crash_on_corrupt_json(self, qtbot, app_mock, tmp_path):
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)
        }
        dash_dir = tmp_path / "dashboards"
        dash_dir.mkdir()
        (dash_dir / "health_garmin.json").write_text("{not valid json", encoding="utf-8")
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_refresh_age_display()
        assert "age unknown" in panel._age_label.text()

    def test_new_chat_resets_history_and_clears_view(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._system_prompt = "You are helpful."
        panel._history = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        panel._chat_on_new_chat()
        assert panel._history == [{"role": "system", "content": "You are helpful."}]

    def test_new_chat_no_system_prompt(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._system_prompt = None
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_new_chat()
        assert panel._history == []

    def test_model_changed_triggers_new_chat_only_when_enabled(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._model_combo.setEnabled(False)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]

        panel._model_combo.setEnabled(True)
        panel._chat_on_model_changed(0)
        assert panel._history == []


# ══════════════════════════════════════════════════════════════════════════════
#  8. PanelMcp
# ══════════════════════════════════════════════════════════════════════════════
# Smoke-level only — no real threading.Thread runs (would hit the real
# Ollama HTTP client). Worker-callback methods (_mcp_on_ollama_models_loaded)
# are called directly instead of via the background thread, mirroring the
# pattern already used for TestPanelChat. Cloud config file I/O uses
# tmp_path + a patched garmin_config.MCP_LLM_CONFIG_FILE instead of the
# real ~/.garmin_mcp_llm_config.json.

class TestPanelMcp:

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
        app.YELLOW  = "#f5a623"
        app.GREEN   = "#4ecca3"
        return app

    def test_panel_instantiates(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        assert panel is not None

    def test_default_backend_is_ollama_box_visible(self, qtbot, app_mock):
        # Korrektur: isVisible() checks the entire parent chain up to a
        # shown top-level window — panel.show() is never called here, so
        # even a correctly-set-visible child reports False. isVisibleTo()
        # checks visibility relative to a given ancestor instead, which is
        # what setVisible()'s own flag actually controls.
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_on_backend_changed()
        assert panel._mcp_ollama_box.isVisibleTo(panel)
        assert not panel._mcp_cloud_box.isVisibleTo(panel)

    def test_backend_switch_to_cloud_swaps_visible_box(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_backend.setCurrentText("cloud")
        assert panel._mcp_cloud_box.isVisibleTo(panel)
        assert not panel._mcp_ollama_box.isVisibleTo(panel)

    def test_get_mcp_settings_reflects_checkbox_and_backend(self, qtbot, app_mock):
        # "checkbox" in the test name is now historical — the Enable MCP
        # server checkbox was removed in v1.7 Teilbauauftrag g (had no
        # functional effect once main() stopped gating on it). Name kept
        # unchanged to avoid pure cosmetic churn; the test still covers
        # get_mcp_settings()'s remaining backend/model behaviour.
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_backend.setCurrentText("cloud")
        s = panel.get_mcp_settings()
        # mcp_ollama_model added in v1.7 Teilbauauftrag f — empty string
        # here since the combo box starts empty until "Refresh" is
        # clicked (see module docstring: no automatic Ollama call on
        # tab-open).
        assert s == {
            "mcp_llm_backend":  "cloud",
            "mcp_ollama_model": "",
        }

    def test_load_mcp_settings_populates_fields(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel.load_mcp_settings({"mcp_llm_backend": "cloud"})
        assert panel._mcp_backend.currentText() == "cloud"
        assert panel._mcp_cloud_box.isVisibleTo(panel)

    def test_load_mcp_settings_defaults_when_keys_missing(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel.load_mcp_settings({})
        assert panel._mcp_backend.currentText() == "ollama"

    def test_ollama_models_loaded_populates_combo(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_on_ollama_models_loaded(["qwen3:14b", "phi4:14b"], None)
        items = [panel._mcp_ollama_model.itemText(i)
                 for i in range(panel._mcp_ollama_model.count())]
        assert items == ["qwen3:14b", "phi4:14b"]
        assert "2 model(s) found" in panel._mcp_ollama_status.text()

    def test_ollama_models_loaded_error_shows_message_no_crash(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_on_ollama_models_loaded([], "not reachable")
        assert "not reachable" in panel._mcp_ollama_status.text()

    def test_ollama_models_loaded_empty_no_error_shows_hint(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_on_ollama_models_loaded([], None)
        assert "ollama pull" in panel._mcp_ollama_status.text()

    def test_cloud_config_status_no_file(self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", tmp_path / "missing.json"):
            panel._mcp_refresh_cloud_key_status()
        assert "No cloud config file" in panel._mcp_cloud_key_status.text()

    def test_save_cloud_config_writes_file_and_clears_key_field(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        panel._mcp_cloud_provider.setText("anthropic")
        panel._mcp_cloud_key.setText("sk-test-123")
        panel._mcp_cloud_model.setText("claude-sonnet-4-6")
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file):
            panel._mcp_save_cloud_config()
        import json
        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved == {
            "provider": "anthropic",
            "api_key": "sk-test-123",
            "model": "claude-sonnet-4-6",
        }
        assert panel._mcp_cloud_key.text() == ""

    def test_save_cloud_config_empty_key_keeps_existing(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        import json
        cfg_file.write_text(json.dumps({
            "provider": "anthropic", "api_key": "existing-key",
            "model": "old-model",
        }), encoding="utf-8")
        panel._mcp_cloud_provider.setText("anthropic")
        panel._mcp_cloud_key.setText("")  # leave empty — keep existing
        panel._mcp_cloud_model.setText("new-model")
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file):
            panel._mcp_save_cloud_config()
        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved["api_key"] == "existing-key"
        assert saved["model"] == "new-model"

    def test_save_cloud_config_missing_required_field_warns_no_write(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        panel._mcp_cloud_provider.setText("")  # missing
        panel._mcp_cloud_key.setText("sk-test")
        panel._mcp_cloud_model.setText("some-model")
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("PyQt6.QtWidgets.QMessageBox.warning") as mock_warn:
            panel._mcp_save_cloud_config()
        mock_warn.assert_called_once()
        assert not cfg_file.exists()


# ══════════════════════════════════════════════════════════════════════════════
#  9. GarminApp (Base)
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
                     "_panel_archive", "_panel_timer", "_panel_outputs",
                     "_xlsx_combo", "_xlsx_view"):
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
