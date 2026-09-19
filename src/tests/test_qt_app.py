# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

    # ── _get_quality_by_date() (v1.7.1.7, Force-Refetch calendar lookup) ──────
    # Pure data function — no dialog, no widget access, no side effect (see its
    # own docstring). Same category as _check_failed_days_popup() above, not
    # the general "GUI not automated" exclusion in MAINTENANCE_GARMIN.md.

    def test_get_quality_by_date_missing_file_returns_empty(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {}

    def test_get_quality_by_date_returns_date_to_label_map(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        import json
        log_dir = tmp_path / "garmin_data" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "quality_log.json").write_text(json.dumps({
            "days": [
                {"date": "2024-08-01", "quality": "high"},
                {"date": "2024-08-02", "quality": "standard"},
                {"date": "2024-08-03", "quality": "failed"},
            ]
        }), encoding="utf-8")
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {
            "2024-08-01": "high",
            "2024-08-02": "standard",
            "2024-08-03": "failed",
        }

    def test_get_quality_by_date_falls_back_to_category_key(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        import json
        log_dir = tmp_path / "garmin_data" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "quality_log.json").write_text(json.dumps({
            "days": [{"date": "2024-08-01", "category": "high"}]
        }), encoding="utf-8")
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {"2024-08-01": "high"}

    def test_get_quality_by_date_missing_date_key_skipped(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        import json
        log_dir = tmp_path / "garmin_data" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "quality_log.json").write_text(json.dumps({
            "days": [
                {"quality": "high"},
                {"date": "2024-08-02", "quality": "standard"},
            ]
        }), encoding="utf-8")
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {"2024-08-02": "standard"}

    def test_get_quality_by_date_corrupt_json_returns_empty_no_crash(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        log_dir = tmp_path / "garmin_data" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "quality_log.json").write_text("{not valid json", encoding="utf-8")
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {}

    def test_get_quality_by_date_no_days_key_returns_empty(
            self, qtbot, app_mock, tmp_path):
        from app.panel_archive import PanelArchive
        import json
        log_dir = tmp_path / "garmin_data" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "quality_log.json").write_text(json.dumps({}), encoding="utf-8")
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        result = panel._get_quality_by_date(str(tmp_path))
        assert result == {}


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
#  ChatHistoryDialog (Baustein 21, garmin_collector-3_experiment)
# ══════════════════════════════════════════════════════════════════════════════
# Same "call internal methods directly, never .exec()" pattern as
# TestPasswordConfirmDialog above — no automated way to drive a real
# modal event loop in this environment.

class TestChatHistoryDialog:

    @pytest.fixture
    def app_mock(self):
        from unittest.mock import MagicMock
        app = MagicMock()
        app.BG     = "#12101f"
        app.BG2    = "#1a1729"
        app.BG3    = "#231f38"
        app.ACCENT  = "#a259f7"
        app.ACCENT2 = "#6e3fcf"
        app.TEXT   = "#eaeaea"
        app.TEXT2  = "#a0a0b0"
        return app

    def _fake_parent(self, qtbot, app_mock):
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        parent._app = app_mock
        qtbot.addWidget(parent)
        return parent

    def _sessions(self):
        return [
            {"path": "/base/chats/chat_2026-09-15_143205_ollama_json.json",
             "created_at": "2026-09-15T14:32:05", "backend": "ollama",
             "datasource": "json", "model": "qwen3:14b", "provider": "",
             "preview": "how many steps yesterday?"},
            {"path": "/base/chats/chat_2026-09-14_090000_cloud_mcp.json",
             "created_at": "2026-09-14T09:00:00", "backend": "cloud",
             "datasource": "mcp", "model": "claude-sonnet-4-6",
             "provider": "anthropic", "preview": ""},
        ]

    def test_lists_every_session(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        assert dlg._list.count() == 2

    def test_empty_list_shows_placeholder_no_crash(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, [])
        qtbot.addWidget(dlg)
        assert dlg._list.count() == 0

    def test_load_and_delete_disabled_without_selection(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        assert not dlg._load_btn.isEnabled()
        assert not dlg._delete_btn.isEnabled()

    def test_selecting_a_row_enables_load_and_delete(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        dlg._list.setCurrentRow(0)
        assert dlg._load_btn.isEnabled()
        assert dlg._delete_btn.isEnabled()

    def test_multi_select_dims_load_keeps_delete_enabled(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        dlg._list.item(0).setSelected(True)
        dlg._list.item(1).setSelected(True)
        assert not dlg._load_btn.isEnabled()
        assert dlg._delete_btn.isEnabled()

    def test_on_load_sets_result_and_accepts(self, qtbot, app_mock):
        from PyQt6.QtWidgets import QDialog
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        dlg._list.setCurrentRow(1)
        dlg._on_load()
        assert dlg.get_result() == (
            "load", "/base/chats/chat_2026-09-14_090000_cloud_mcp.json")
        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_on_delete_confirmed_sets_result(self, qtbot, app_mock):
        # Not qtbot.addWidget(dlg) here, deliberately — mocking
        # QMessageBox.question (a PyQt6 static method) while a dialog is
        # registered with qtbot triggers a benign teardown-only
        # "wrapped C/C++ object already deleted" error from qtbot's own
        # widget-closing pass (reproduced outside pytest-qt without this
        # issue — a pytest-qt/mock-patch interaction, not a bug in this
        # dialog). dlg is never shown, so plain Python GC reclaims it
        # once the test returns; nothing here needs qtbot's cleanup.
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        dlg._list.setCurrentRow(0)
        with patch.object(QMessageBox, "question",
                           return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        assert dlg.get_result() == (
            "delete", ["/base/chats/chat_2026-09-15_143205_ollama_json.json"])

    def test_on_delete_confirmed_multi_select_returns_all_paths(self, qtbot, app_mock):
        # Same qtbot.addWidget() omission as test_on_delete_confirmed_sets_result, same reason.
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        dlg._list.item(0).setSelected(True)
        dlg._list.item(1).setSelected(True)
        with patch.object(QMessageBox, "question",
                           return_value=QMessageBox.StandardButton.Yes):
            dlg._on_delete()
        action, paths = dlg.get_result()
        assert action == "delete"
        assert set(paths) == {
            "/base/chats/chat_2026-09-15_143205_ollama_json.json",
            "/base/chats/chat_2026-09-14_090000_cloud_mcp.json",
        }

    def test_on_delete_declined_keeps_dialog_open_no_result(self, qtbot, app_mock):
        # Same qtbot.addWidget() omission as the test above, same reason.
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        dlg._list.setCurrentRow(0)
        with patch.object(QMessageBox, "question",
                           return_value=QMessageBox.StandardButton.No):
            dlg._on_delete()
        assert dlg.get_result() is None

    def test_double_click_loads(self, qtbot, app_mock):
        from app.dialog_chat_history import ChatHistoryDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ChatHistoryDialog(parent, self._sessions())
        qtbot.addWidget(dlg)
        dlg._list.setCurrentRow(0)
        dlg._list.itemDoubleClicked.emit(dlg._list.item(0))
        assert dlg.get_result()[0] == "load"


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

    # ── Phase 1 Streaming (Baustein 20) ──────────────────────────────────

    def test_start_stream_line_shows_speaker_label(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_start_stream_line("Assistant")
        assert "Assistant:" in panel._chat_view.toPlainText()

    def test_append_stream_chunk_continues_same_line(self, qtbot, app_mock):
        # The whole point of _chat_append_stream_chunk() over
        # _chat_append_line()/QTextEdit.append(): chunks land inline,
        # no extra paragraph break is introduced between them.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_start_stream_line("Assistant")
        panel._chat_append_stream_chunk("Hel")
        panel._chat_append_stream_chunk("lo")
        assert panel._chat_view.toPlainText().strip() == "Assistant: Hello"

    def test_chat_on_stream_done_resets_state_and_appends_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._send_btn.setEnabled(False)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_stream_done("hello back")
        assert panel._request_running is False
        assert panel._send_btn.isEnabled()
        assert panel._history[-1] == {"role": "assistant", "content": "hello back"}

    def test_chat_on_stream_error_pops_trailing_user_message(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_stream_error("", Exception("boom"))
        assert panel._request_running is False
        assert panel._history == []

    def test_chat_on_stream_error_with_partial_text_marks_interrupted(self, qtbot, app_mock):
        # Unlike the total-failure case above, some text already
        # streamed into the view before the connection dropped — it
        # must stay visible, with a follow-up note marking it
        # interrupted, and still not be written into history.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_start_stream_line("Assistant")
        panel._chat_append_stream_chunk("Hel")
        panel._chat_on_stream_error("Hel", Exception("connection lost"))
        assert panel._history == []
        view_text = panel._chat_view.toPlainText()
        assert "Assistant: Hel" in view_text
        assert "interrupted" in view_text.lower()

    # ── Chat-Session-Logging/Resume (Baustein 21) ────────────────────────

    def test_chat_history_button_exists_and_enabled_before_start(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert panel._chat_history_btn.isEnabled()

    def test_render_history_skips_system_and_content_less_assistant(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "how many steps?"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "content": "8000", "tool_call_id": "c1"},
            {"role": "assistant", "content": "You took 8000 steps."},
        ]
        panel._chat_render_history()
        text = panel._chat_view.toPlainText()
        assert "sys prompt" not in text
        assert "how many steps?" in text
        assert "You took 8000 steps." in text
        assert "8000\n" not in text or "tool" not in text.lower()

    def test_save_session_calls_store_and_updates_path(self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        fake_store = MagicMock()
        fake_path = tmp_path / "chats" / "chat_x_ollama_json.json"
        fake_store.save_session.return_value = fake_path
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store):
            panel._chat_save_session()
        fake_store.save_session.assert_called_once()
        args, kwargs = fake_store.save_session.call_args
        assert args[0] == str(tmp_path)
        assert args[1] is None  # first save, no path yet
        session_data = args[2]
        assert session_data["backend"] == "ollama"
        assert session_data["datasource"] == "json"
        assert session_data["messages"] == panel._history
        assert panel._chat_session_path == fake_path

    def test_save_session_noop_without_base_dir(self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store):
            panel._chat_save_session()
        fake_store.save_session.assert_not_called()

    def test_reply_handlers_trigger_auto_save(self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        with patch.object(panel, "_chat_save_session") as save:
            panel._chat_on_reply("hello back")
        save.assert_called_once()

        panel._history = [{"role": "user", "content": "hi"}]
        with patch.object(panel, "_chat_save_session") as save:
            panel._chat_on_stream_done("hello back")
        save.assert_called_once()

        with patch.object(panel, "_chat_save_session") as save:
            panel._chat_on_mcp_reply(
                {"content": "answer", "messages": [], "hit_max_turns": False})
        save.assert_called_once()

    def test_stop_resets_session_path(self, qtbot, app_mock):
        from pathlib import Path as _Path
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_session_path = _Path("/base/chats/x.json")
        panel._chat_session_created_at = "2026-09-15T14:00:00"
        panel._chat_on_stop()
        assert panel._chat_session_path is None
        assert panel._chat_session_created_at is None

    def test_new_chat_resets_session_path(self, qtbot, app_mock):
        from pathlib import Path as _Path
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_session_path = _Path("/base/chats/x.json")
        panel._chat_session_created_at = "2026-09-15T14:00:00"
        panel._chat_loaded_model = "qwen3:14b"
        panel._chat_on_new_chat()
        assert panel._chat_session_path is None
        assert panel._chat_session_created_at is None
        assert panel._chat_loaded_model is None

    def test_new_chat_reopens_combos_when_loaded_not_started(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setEnabled(False)
        panel._datasource_combo.setEnabled(False)
        panel._chat_loaded_not_started = True
        panel._chat_on_new_chat()
        assert panel._backend_combo.isEnabled()
        assert panel._datasource_combo.isEnabled()
        assert panel._chat_loaded_not_started is False

    def test_new_chat_leaves_combos_locked_for_a_running_session(self, qtbot, app_mock):
        # The normal, pre-Baustein-21 case: combos locked by a genuine
        # Start, New Chat mid-session must NOT unlock them.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setEnabled(False)
        panel._datasource_combo.setEnabled(False)
        panel._chat_loaded_not_started = False
        panel._chat_on_new_chat()
        assert not panel._backend_combo.isEnabled()
        assert not panel._datasource_combo.isEnabled()

    def test_start_clears_loaded_not_started_flag(self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_loaded_not_started = True
        with patch("app.panel_chat._load_ollama_client"):
            panel._chat_on_start()
        assert panel._chat_loaded_not_started is False

    def test_resume_pending_skips_history_reset_once(self, qtbot, app_mock, tmp_path):
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        loaded_history = [{"role": "user", "content": "loaded turn"}]
        panel._history = loaded_history
        panel._chat_resume_pending = True
        panel._chat_load_system_prompt()
        assert panel._history == loaded_history
        assert panel._chat_resume_pending is False

        # A later, non-resume call still resets normally.
        panel._history = [{"role": "user", "content": "stale"}]
        panel._chat_load_system_prompt()
        assert panel._history == []

    def test_open_history_load_delegates_to_load_session(self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QDialog
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.list_sessions.return_value = []
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.DialogCode.Accepted
        fake_dialog.get_result.return_value = ("load", "/base/chats/x.json")
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store), \
             patch("app.panel_chat.ChatHistoryDialog", return_value=fake_dialog), \
             patch.object(panel, "_chat_on_load_session") as load_session:
            panel._chat_on_open_history()
        load_session.assert_called_once_with(fake_store, "/base/chats/x.json")

    def test_open_history_delete_calls_store_delete(self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QDialog
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.list_sessions.return_value = []
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.DialogCode.Accepted
        fake_dialog.get_result.return_value = ("delete", ["/base/chats/x.json"])
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store), \
             patch("app.panel_chat.ChatHistoryDialog", return_value=fake_dialog):
            panel._chat_on_open_history()
        fake_store.delete_session.assert_called_once_with("/base/chats/x.json")

    def test_open_history_delete_multi_select_calls_store_delete_for_each(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QDialog
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.list_sessions.return_value = []
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.DialogCode.Accepted
        fake_dialog.get_result.return_value = (
            "delete", ["/base/chats/x.json", "/base/chats/y.json"])
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store), \
             patch("app.panel_chat.ChatHistoryDialog", return_value=fake_dialog):
            panel._chat_on_open_history()
        assert fake_store.delete_session.call_count == 2
        fake_store.delete_session.assert_any_call("/base/chats/x.json")
        fake_store.delete_session.assert_any_call("/base/chats/y.json")

    def test_open_history_rejected_dialog_does_nothing(self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QDialog
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.list_sessions.return_value = []
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.DialogCode.Rejected
        with patch("app.panel_chat._load_chat_session_store", return_value=fake_store), \
             patch("app.panel_chat.ChatHistoryDialog", return_value=fake_dialog):
            panel._chat_on_open_history()
        fake_store.delete_session.assert_not_called()

    def test_load_session_resumable_mcp_locks_combos_and_enables_start(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.load_session.return_value = {
            "created_at": "2026-09-15T14:00:00", "backend": "ollama",
            "datasource": "mcp", "model": "qwen3:14b", "provider": "",
            "messages": [{"role": "user", "content": "hi"}],
        }
        fake_store.is_resumable.return_value = True
        panel._chat_on_load_session(fake_store, "/base/chats/x.json")
        assert panel._backend_combo.currentText() == "ollama"
        assert panel._datasource_combo.currentText() == "mcp"
        assert not panel._backend_combo.isEnabled()
        assert not panel._datasource_combo.isEnabled()
        assert panel._start_btn.isEnabled()
        assert panel._new_chat_btn.isEnabled()
        assert panel._chat_resume_pending is True
        assert panel._chat_loaded_not_started is True
        assert "hi" in panel._chat_view.toPlainText()

    def test_load_session_non_resumable_json_disables_start_shows_warning(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.load_session.return_value = {
            "created_at": "2026-09-15T14:00:00", "backend": "ollama",
            "datasource": "json", "model": "qwen3:14b", "provider": "",
            "source_hash": "deadbeef",
            "messages": [{"role": "user", "content": "hi"}],
        }
        fake_store.is_resumable.return_value = False
        panel._chat_on_load_session(fake_store, "/base/chats/x.json")
        assert not panel._start_btn.isEnabled()
        assert "read-only" in panel._chat_view.toPlainText().lower()

    def test_load_session_cloud_shows_session_level_label(self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock
        from app.panel_chat import PanelChat
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()
        fake_store.load_session.return_value = {
            "created_at": "2026-09-15T14:32:05", "backend": "cloud",
            "datasource": "mcp", "model": "claude-sonnet-4-6",
            "provider": "anthropic", "messages": [],
        }
        fake_store.is_resumable.return_value = True
        panel._chat_on_load_session(fake_store, "/base/chats/x.json")
        text = panel._chat_view.toPlainText()
        assert "cloud" in text.lower()
        assert "anthropic" in text
        assert "claude-sonnet-4-6" in text

    def test_load_session_read_error_shows_system_message(self, qtbot, app_mock):
        from unittest.mock import MagicMock
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        fake_store = MagicMock()

        class _FakeError(Exception):
            pass
        fake_store.ChatSessionError = _FakeError
        fake_store.load_session.side_effect = _FakeError("boom")
        panel._chat_on_load_session(fake_store, "/base/chats/x.json")
        assert "Could not load session" in panel._chat_view.toPlainText()

    def test_models_loaded_preselects_loaded_model(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_loaded_model = "qwen3:14b"
        panel._chat_on_models_loaded(["phi4:14b", "qwen3:14b"], None)
        assert panel._model_combo.currentText() == "qwen3:14b"
        assert panel._chat_loaded_model is None

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

    def test_model_changed_does_not_reset_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._model_combo.setEnabled(False)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]

        panel._model_combo.setEnabled(True)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]

    # ── Backend/Datenquelle dropdowns (garmin_collector-3_experiment
    # addendum, replaces an earlier "Use MCP tools" checkbox — session
    # feedback: "das war im Konzept anders beschrieben") ────────────────

    def test_backend_and_datasource_combos_enabled_from_the_start(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        # Unlike model_combo/input/send_btn (gated behind Start), these two
        # must be choosable before Start — Start's own behavior depends on
        # the selected backend.
        assert panel._backend_combo.isEnabled()
        assert panel._datasource_combo.isEnabled()
        assert panel._backend_combo.currentText() == "ollama"
        assert panel._datasource_combo.currentText() == "json"
        # isVisible() checks the whole parent chain up to a shown
        # top-level window — panel.show() is never called here, so even a
        # correctly-set-visible child reports False. isVisibleTo(panel)
        # checks visibility relative to panel instead, which is what
        # setVisible()'s own flag actually controls (same fix already
        # applied in TestPanelMcp below for the analogous cloud-box case).
        assert panel._model_combo.isVisibleTo(panel)
        assert not panel._cloud_info_label.isVisibleTo(panel)

    def test_backend_changed_to_cloud_swaps_visible_widget(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        assert not panel._model_combo.isVisibleTo(panel)
        assert panel._cloud_info_label.isVisibleTo(panel)

    def test_backend_changed_resets_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._backend_combo.setCurrentText("cloud")
        assert panel._history == []

    def test_datasource_changed_resets_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._datasource_combo.setCurrentText("mcp")
        assert panel._history == []

    def test_new_chat_skips_system_prompt_when_datasource_mcp(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        panel._system_prompt = "You are helpful."
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_new_chat()
        # Unlike test_new_chat_resets_history_and_clears_view above
        # (datasource "json"), datasource "mcp" must NOT seed the
        # JSON-snapshot system prompt — mcp_tool_chat.converse() injects
        # its own instead.
        assert panel._history == []

    def test_send_with_cloud_backend_and_incomplete_config_shows_guard_message(
            self, qtbot, app_mock):
        # Cloud-LLM-Connector Baustein — self._cloud_provider/_model/
        # _api_key are only populated by _chat_on_cloud_config_loaded()
        # (i.e. after a real Start); here they are still the empty-string
        # __init__ defaults, so Send must refuse before ever attempting a
        # call that could only fail.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._input.setText("hello")
        panel._chat_on_send()
        # No request was ever attempted — input/history untouched, unlike
        # a real failed turn (_chat_on_error() pops history, clears input).
        assert panel._history == []
        assert panel._input.text() == "hello"
        assert "No usable cloud configuration" in panel._chat_view.toPlainText()

    def test_cloud_config_loaded_no_file(self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", tmp_path / "missing.json"):
            panel._chat_on_cloud_config_loaded()
        assert "No cloud configuration saved" in panel._cloud_info_label.text()
        assert panel._send_btn.isEnabled()

    def test_cloud_config_loaded_warns_on_missing_key(self, qtbot, app_mock, tmp_path):
        # Baustein 23: no key in WCM for this provider — mocked here
        # rather than relying on the real Credential Manager being
        # empty for "anthropic" on whatever machine runs this test.
        import json
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        cfg_file.write_text(
            json.dumps({"provider": "anthropic", "model": "claude-sonnet-4-6"}),
            encoding="utf-8")
        fake_store = MagicMock()
        fake_store.get_api_key.return_value = None
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_chat._load_cloud_credential_store", return_value=fake_store):
            panel._chat_on_cloud_config_loaded()
        text = panel._cloud_info_label.text()
        assert "anthropic / claude-sonnet-4-6" in text
        assert "no API key saved" in text

    # ── Cloud LLM connector (garmin_collector-3_experiment, Baustein 14) ────

    def test_cloud_config_loaded_stores_provider_model_key_normalized(
            self, qtbot, app_mock, tmp_path):
        # Provider field is free text on the MCP tab (app/panel_mcp.py's
        # _mcp_cloud_provider) — "  Anthropic " must resolve the same way
        # as "anthropic" once stored, matching cloud_llm_client.chat()'s
        # own normalization.
        # Baustein 23: the API key itself comes from Windows Credential
        # Manager (clients/cloud_credential_store.py), not the JSON file
        # — mocked here via _load_cloud_credential_store().
        import json
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        cfg_file.write_text(
            json.dumps({"provider": "  Anthropic ", "model": "claude-sonnet-4-6"}),
            encoding="utf-8")
        fake_store = MagicMock()
        fake_store.get_api_key.return_value = "sk-test"
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_chat._load_cloud_credential_store", return_value=fake_store):
            panel._chat_on_cloud_config_loaded()
        assert panel._cloud_provider == "anthropic"
        assert panel._cloud_model == "claude-sonnet-4-6"
        assert panel._cloud_api_key == "sk-test"
        fake_store.get_api_key.assert_called_once_with("anthropic")

    def test_send_with_cloud_and_mcp_and_incomplete_config_shows_guard_message(
            self, qtbot, app_mock):
        # Baustein 18 — Cloud + MCP tool-calling is built now, but the
        # same "no usable cloud configuration" guard from the plain-cloud
        # path still applies regardless of datasource.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._datasource_combo.setCurrentText("mcp")
        panel._input.setText("hello")
        panel._chat_on_send()
        assert panel._history == []
        assert panel._input.text() == "hello"
        assert "No usable cloud configuration" in panel._chat_view.toPlainText()

    def test_send_with_cloud_and_mcp_and_complete_config_starts_request(
            self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._datasource_combo.setCurrentText("mcp")
        panel._cloud_provider = "anthropic"
        panel._cloud_model = "claude-sonnet-4-6"
        panel._cloud_api_key = "sk-test"
        panel._input.setText("hello")
        with patch("app.panel_chat._load_cloud_tool_chat"), \
             patch("app.panel_chat._load_cloud_llm_client"), \
             patch("app.panel_chat._load_mcp_client"):
            panel._chat_on_send()
        assert panel._history == [{"role": "user", "content": "hello"}]
        assert panel._input.text() == ""
        assert not panel._send_btn.isEnabled()
        assert panel._request_running is True

    def test_send_with_cloud_and_complete_config_starts_request(self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._cloud_provider = "anthropic"
        panel._cloud_model = "claude-sonnet-4-6"
        panel._cloud_api_key = "sk-test"
        panel._input.setText("hello")
        with patch("app.panel_chat._load_cloud_llm_client"):
            panel._chat_on_send()
        assert panel._history == [{"role": "user", "content": "hello"}]
        assert panel._input.text() == ""
        assert not panel._send_btn.isEnabled()
        assert panel._request_running is True

    class _SyncThread:
        """Test-only stand-in for threading.Thread that runs target()
        synchronously inside start() instead of spawning a real OS
        thread — lets a test exercise a real worker() closure's own
        exception handling (garmin_collector-3_experiment, post-v1.7.2
        review: a lazy-import failure inside worker() used to run
        unguarded ahead of any try block, silently killing the
        background thread with zero _app._dispatch() call — the UI
        stayed on "Waiting for response" forever, no error, no log)
        without violating this suite's own "no real threading.Thread"
        rule (see the class-level comment above — a real thread would
        hit the live Ollama/MCP HTTP clients). _app._dispatch() itself
        stays a MagicMock (as in every other test here) — it records
        the call instead of running the lambda, so the tests below
        invoke the captured lambda manually to observe its effect."""

        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    def test_send_ollama_mcp_import_failure_dispatches_error_not_silent_hang(
            self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("ollama")
        panel._datasource_combo.setCurrentText("mcp")
        panel._input.setText("hello")
        with patch("threading.Thread", self._SyncThread), \
             patch("app.panel_chat._load_ollama_client",
                   side_effect=RuntimeError("boom")):
            panel._chat_on_send()
        assert app_mock._dispatch.called
        app_mock._dispatch.call_args[0][0]()  # run the dispatched callback
        assert panel._request_running is False
        assert panel._send_btn.isEnabled()
        assert panel._history == []
        assert "boom" in panel._chat_view.toPlainText()

    def test_send_ollama_mcp_unclassified_exception_dispatches_error(
            self, qtbot, app_mock):
        # Distinct from the import-failure test above: this one fails
        # inside converse() itself (imports succeed), with an exception
        # type that is neither McpClientError nor OllamaError — the new
        # generic `except Exception` fallback net, not the import guard.
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("ollama")
        panel._datasource_combo.setCurrentText("mcp")
        panel._input.setText("hello")
        fake_mcp_tool_chat = MagicMock()
        fake_mcp_tool_chat.converse.side_effect = ValueError("unexpected")
        # McpClientError/OllamaError must be real exception classes for
        # the worker's `except mcp_client.McpClientError`/`except
        # ollama_client.OllamaError` clauses to even evaluate — a bare
        # MagicMock() attribute there raises its own TypeError
        # ("catching classes that do not inherit from BaseException")
        # while Python is still trying to match the ValueError below.
        fake_mcp_client = MagicMock()
        fake_mcp_client.McpClientError = type("FakeMcpClientError", (Exception,), {})
        fake_ollama_client = MagicMock()
        fake_ollama_client.OllamaError = type("FakeOllamaError", (Exception,), {})
        with patch("threading.Thread", self._SyncThread), \
             patch("app.panel_chat._load_ollama_client", return_value=fake_ollama_client), \
             patch("app.panel_chat._load_mcp_tool_chat", return_value=fake_mcp_tool_chat), \
             patch("app.panel_chat._load_mcp_client", return_value=fake_mcp_client):
            panel._chat_on_send()
        assert app_mock._dispatch.called
        app_mock._dispatch.call_args[0][0]()
        assert panel._request_running is False
        assert "unexpected" in panel._chat_view.toPlainText()

    def test_send_cloud_mcp_import_failure_dispatches_error_not_silent_hang(
            self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._datasource_combo.setCurrentText("mcp")
        panel._cloud_provider = "anthropic"
        panel._cloud_model = "claude-sonnet-4-6"
        panel._cloud_api_key = "sk-test"
        panel._input.setText("hello")
        with patch("threading.Thread", self._SyncThread), \
             patch("app.panel_chat._load_cloud_tool_chat",
                   side_effect=RuntimeError("boom")):
            panel._chat_on_send()
        assert app_mock._dispatch.called
        app_mock._dispatch.call_args[0][0]()
        assert panel._request_running is False
        assert panel._history == []
        assert "boom" in panel._chat_view.toPlainText()

    def test_send_cloud_only_import_failure_dispatches_stream_error_not_silent_hang(
            self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setCurrentText("cloud")
        panel._cloud_provider = "anthropic"
        panel._cloud_model = "claude-sonnet-4-6"
        panel._cloud_api_key = "sk-test"
        panel._input.setText("hello")
        with patch("threading.Thread", self._SyncThread), \
             patch("app.panel_chat._load_cloud_llm_client",
                   side_effect=RuntimeError("boom")):
            panel._chat_on_send()
        assert app_mock._dispatch.called
        app_mock._dispatch.call_args[0][0]()
        assert panel._request_running is False
        assert panel._history == []
        assert "boom" in panel._chat_view.toPlainText()

    def test_send_ollama_only_import_failure_dispatches_stream_error_not_silent_hang(
            self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._input.setText("hello")
        with patch("threading.Thread", self._SyncThread), \
             patch("app.panel_chat._load_ollama_client",
                   side_effect=RuntimeError("boom")):
            panel._chat_on_send()
        assert app_mock._dispatch.called
        app_mock._dispatch.call_args[0][0]()
        assert panel._request_running is False
        assert panel._history == []
        assert "boom" in panel._chat_view.toPlainText()

    def test_chat_on_mcp_reply_replaces_history_and_resets_state(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._send_btn.setEnabled(False)
        panel._history = [{"role": "user", "content": "steps?"}]
        result = {
            "content": "4,024 steps.",
            "messages": [
                {"role": "user", "content": "steps?"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
                {"role": "tool", "content": "{...}", "tool_call_id": "1"},
                {"role": "assistant", "content": "4,024 steps.", "tool_calls": []},
            ],
            "hit_max_turns": False,
        }
        panel._chat_on_mcp_reply(result)
        assert panel._request_running is False
        assert panel._send_btn.isEnabled()
        assert panel._history == result["messages"]
        assert "4,024 steps." in panel._chat_view.toPlainText()

    def test_chat_on_mcp_reply_flags_max_turns(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        result = {"content": "partial", "messages": [], "hit_max_turns": True}
        panel._chat_on_mcp_reply(result)
        assert "turn limit" in panel._chat_view.toPlainText()

    # ── Cloud+MCP Streaming (Baustein 22, Phase 2 Streaming) ─────────────

    def test_chat_on_mcp_stream_done_resets_state_and_replaces_history(
            self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._send_btn.setEnabled(False)
        panel._history = [{"role": "user", "content": "steps?"}]
        event = {
            "messages": [
                {"role": "user", "content": "steps?"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
                {"role": "tool", "content": "{...}", "tool_call_id": "1"},
                {"role": "assistant", "content": "4,024 steps.", "tool_calls": []},
            ],
            "hit_max_turns": False,
        }
        panel._chat_on_mcp_stream_done(event)
        assert panel._request_running is False
        assert panel._send_btn.isEnabled()
        assert panel._history == event["messages"]

    def test_chat_on_mcp_stream_done_flags_max_turns(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        event = {"messages": [], "hit_max_turns": True}
        panel._chat_on_mcp_stream_done(event)
        assert "turn limit" in panel._chat_view.toPlainText()

    def test_cloud_mcp_worker_routes_text_events_to_new_bubble_per_turn(
            self, qtbot, app_mock):
        # Verifies the event-dispatch logic inside _chat_on_send()'s
        # Cloud+MCP worker directly (mirrors how streaming chunk
        # dispatch was tested in Baustein 20 — no real background
        # thread, no real converse_stream(), just the same
        # started/_chat_start_stream_line/_chat_append_stream_chunk
        # wiring the worker itself uses).
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)

        events = [
            {"type": "text", "text": "Let"},
            {"type": "text", "text": " me check."},
            {"type": "tool_call", "name": "query_health"},
            {"type": "text", "text": "You took 8000 steps."},
            {"type": "final", "messages": [
                {"role": "assistant", "content": "You took 8000 steps.",
                 "tool_calls": []}],
             "hit_max_turns": False},
        ]

        started = False
        for event in events:
            etype = event["type"]
            if etype == "text":
                if not started:
                    panel._chat_start_stream_line("Assistant")
                    started = True
                panel._chat_append_stream_chunk(event["text"])
            elif etype == "tool_call":
                started = False
                panel._chat_append_system(f"🔧 Calling {event['name']}…")
            elif etype == "final":
                panel._chat_on_mcp_stream_done(event)

        text = panel._chat_view.toPlainText()
        assert "Let me check." in text
        assert "Calling query_health" in text
        assert "You took 8000 steps." in text
        # Two separate "Assistant:" bubbles — one per turn — not one
        # combined block.
        assert text.count("Assistant:") == 2
        assert panel._history == events[-1]["messages"]

    def test_chat_on_mcp_unreachable_pops_trailing_user_message(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._request_running = True
        panel._history = [{"role": "user", "content": "hi"}]
        panel._chat_on_mcp_unreachable(Exception("MCP server not reachable"))
        assert panel._request_running is False
        assert panel._history == []
        assert "MCP Server tab" in panel._chat_view.toPlainText()

    # ── Start/Stop button pair (garmin_collector-3_experiment, Baustein 8b) ─

    def test_stop_button_disabled_before_start(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert not panel._stop_btn.isEnabled()

    def test_start_with_datasource_json_does_not_touch_mcp_process(
            self, qtbot, app_mock):
        # The mcp_process.start() gate and the ollama-model-loading worker
        # it may precede run on different threads/timings — asserting on
        # mcp_process itself only needs the synchronous part _chat_on_
        # start() runs before ever spawning that worker thread, so this
        # deliberately does not wait for or assert on the async model-
        # loading outcome (already covered by test_chat_on_models_loaded-
        # style tests above without going through _chat_on_start() at all).
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        mcp_process = MagicMock()
        with patch("app.panel_chat._load_mcp_process", return_value=mcp_process), \
             patch("app.panel_chat._load_ollama_client"):
            panel._chat_on_start()
        mcp_process.start.assert_not_called()

    def test_start_with_datasource_mcp_starts_server_first(self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        mcp_process = MagicMock()
        mcp_process.start.return_value = (True, "MCP server already running.")
        with patch("app.panel_chat._load_mcp_process", return_value=mcp_process), \
             patch("app.panel_chat._load_ollama_client"):
            panel._chat_on_start()
        mcp_process.start.assert_called_once()

    def test_start_with_datasource_mcp_aborts_if_server_start_fails(
            self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        mcp_process = MagicMock()
        mcp_process.start.return_value = (False, "Could not find mcp_server.py.")
        with patch("app.panel_chat._load_mcp_process", return_value=mcp_process), \
             patch("app.panel_chat._load_ollama_client") as load_ollama:
            panel._chat_on_start()
        # Never even reaches the ollama model-loading step.
        load_ollama.assert_not_called()
        assert panel._start_btn.isEnabled()
        assert not panel._stop_btn.isEnabled()
        assert "Could not find mcp_server.py" in panel._chat_view.toPlainText()

    def test_stop_resets_ui_state_and_reenables_start(self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_on_models_loaded(["qwen3:1.7b"], None)
        assert panel._stop_btn.isEnabled()

        with patch("app.panel_chat._load_mcp_process") as load_mcp_process:
            panel._chat_on_stop()
        # datasource is "json" by default — mcp_process is never touched.
        load_mcp_process.assert_not_called()
        assert not panel._stop_btn.isEnabled()
        assert not panel._input.isEnabled()
        assert not panel._send_btn.isEnabled()
        assert panel._start_btn.isEnabled()

    def test_stop_with_datasource_mcp_stops_the_server(self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        panel._chat_on_models_loaded(["qwen3:1.7b"], None)
        mcp_process = MagicMock()
        mcp_process.stop.return_value = (True, "MCP server stopped (PID 1234).")
        with patch("app.panel_chat._load_mcp_process", return_value=mcp_process):
            panel._chat_on_stop()
        mcp_process.stop.assert_called_once()
        assert "MCP server stopped (PID 1234)." in panel._chat_view.toPlainText()

    def test_start_after_stop_clears_old_chat_view(self, qtbot, app_mock):
        # garmin_collector-3_experiment, Baustein 30 — Timo, live: Stop
        # then Start again left the old conversation visible on screen,
        # even though _chat_load_system_prompt() already resets
        # self._history (the model-facing data). Found: only
        # _chat_on_new_chat() ever cleared _chat_view, not the plain
        # Stop-then-Start path.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_on_models_loaded(["qwen3:1.7b"], None)
        panel._chat_view.append("You: old question\nAssistant: old answer")
        assert "old question" in panel._chat_view.toPlainText()

        # A later Start (no intervening "Neuer Chat" click) must clear
        # the view the same way _chat_on_new_chat() already does.
        panel._chat_on_models_loaded(["qwen3:1.7b"], None)
        assert "old question" not in panel._chat_view.toPlainText()

    # ── Backend/Datenquelle locked while running (Baustein 12) ──────────────
    # Session feedback: switching either dropdown mid-chat used to only
    # reset history without actually locking anything, letting a live
    # mcp-backed conversation be silently mixed with a json one.

    def test_backend_and_datasource_locked_after_start_click(self, qtbot, app_mock):
        from unittest.mock import patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        with patch("app.panel_chat._load_ollama_client"):
            panel._chat_on_start()
        assert not panel._backend_combo.isEnabled()
        assert not panel._datasource_combo.isEnabled()

    def test_backend_and_datasource_reenabled_after_mcp_start_failure(
            self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        mcp_process = MagicMock()
        mcp_process.start.return_value = (False, "Could not find mcp_server.py.")
        with patch("app.panel_chat._load_mcp_process", return_value=mcp_process), \
             patch("app.panel_chat._load_ollama_client"):
            panel._chat_on_start()
        assert panel._backend_combo.isEnabled()
        assert panel._datasource_combo.isEnabled()

    def test_backend_and_datasource_reenabled_after_ollama_unreachable(
            self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setEnabled(False)
        panel._datasource_combo.setEnabled(False)
        panel._chat_on_models_loaded([], "connection refused")
        assert panel._backend_combo.isEnabled()
        assert panel._datasource_combo.isEnabled()

    def test_backend_and_datasource_reenabled_after_stop(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._backend_combo.setEnabled(False)
        panel._datasource_combo.setEnabled(False)
        panel._chat_on_stop()
        assert panel._backend_combo.isEnabled()
        assert panel._datasource_combo.isEnabled()

    # ── MCP log split-view (garmin_collector-3_experiment, Baustein 9) ──────

    def test_log_container_hidden_by_default(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert not panel._log_container.isVisibleTo(panel)
        assert not panel._log_tail_timer.isActive()

    def test_datasource_mcp_shows_log_and_starts_timer(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        assert panel._log_container.isVisibleTo(panel)
        assert panel._log_tail_timer.isActive()

    def test_datasource_back_to_json_hides_log_and_stops_timer(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        panel._datasource_combo.setCurrentText("json")
        assert not panel._log_container.isVisibleTo(panel)
        assert not panel._log_tail_timer.isActive()

    def test_tail_mcp_log_no_directory_is_noop(self, qtbot, app_mock, tmp_path):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        panel._chat_tail_mcp_log()  # garmin_data/log/mcp/ does not exist
        assert panel._log_view.toPlainText() == ""

    def test_tail_mcp_log_reads_new_content_incrementally(
            self, qtbot, app_mock, tmp_path):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        log_dir = tmp_path / "garmin_data" / "log" / "mcp"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "mcp_2026-09-14_120000.log"
        log_file.write_text("line one\n", encoding="utf-8")

        panel._chat_tail_mcp_log()
        assert panel._log_view.toPlainText().strip() == "line one"

        # A second tick with no new content must not duplicate what is
        # already shown — this is what the tracked file position is for.
        panel._chat_tail_mcp_log()
        assert panel._log_view.toPlainText().count("line one") == 1

        with log_file.open("a", encoding="utf-8") as f:
            f.write("line two\n")
        panel._chat_tail_mcp_log()
        text = panel._log_view.toPlainText()
        assert "line one" in text and "line two" in text

    def test_tail_mcp_log_switches_to_newest_file_and_resets_view(
            self, qtbot, app_mock, tmp_path):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path)}
        log_dir = tmp_path / "garmin_data" / "log" / "mcp"
        log_dir.mkdir(parents=True)
        old_file = log_dir / "mcp_2026-09-14_090000.log"
        old_file.write_text("old server run\n", encoding="utf-8")
        panel._chat_tail_mcp_log()
        assert "old server run" in panel._log_view.toPlainText()

        # A later server start writes a lexicographically newer filename —
        # the next tick must switch to it and drop the old content, not
        # append the new file's lines onto the stale view.
        new_file = log_dir / "mcp_2026-09-14_150000.log"
        new_file.write_text("new server run\n", encoding="utf-8")
        panel._chat_tail_mcp_log()
        text = panel._log_view.toPlainText()
        assert "new server run" in text
        assert "old server run" not in text

    # ── Model hint + sorting, Start/Stop row merge (Baustein 10) ────────────

    def test_mcp_model_hint_hidden_by_default(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert not panel._mcp_model_hint.isVisibleTo(panel)

    def test_mcp_model_hint_shown_for_datasource_mcp(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._datasource_combo.setCurrentText("mcp")
        assert panel._mcp_model_hint.isVisibleTo(panel)
        panel._datasource_combo.setCurrentText("json")
        assert not panel._mcp_model_hint.isVisibleTo(panel)

    def test_sort_models_qwen_first(self, qtbot, app_mock):
        from app.panel_chat import _sort_models_qwen_first
        models = ["phi4:14b", "qwen3:14b", "mistral-nemo:latest",
                  "qwen2.5-coder:7b", "Hermes3:latest", "qwen3:1.7b"]
        assert _sort_models_qwen_first(models) == [
            "qwen2.5-coder:7b", "qwen3:1.7b", "qwen3:14b",
            "Hermes3:latest", "mistral-nemo:latest", "phi4:14b",
        ]

    def test_sort_models_qwen_first_no_qwen_models(self, qtbot, app_mock):
        from app.panel_chat import _sort_models_qwen_first
        assert _sort_models_qwen_first(["phi4:14b", "gemma3:4b"]) == [
            "gemma3:4b", "phi4:14b"]

    def test_models_loaded_populates_combo_qwen_first(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._chat_on_models_loaded(
            ["phi4:14b", "qwen3:14b", "qwen2.5-coder:7b"], None)
        items = [panel._model_combo.itemText(i)
                 for i in range(panel._model_combo.count())]
        assert items == ["qwen2.5-coder:7b", "qwen3:14b", "phi4:14b"]

    def test_start_stop_buttons_exist_and_still_gate_correctly(self, qtbot, app_mock):
        # Baustein 10, session feedback: "start/stop verschieben damit
        # mehr platz für den chat ist" — Start/Stop moved onto the
        # Backend/Datenquelle row (see _build_ui()'s "Config row"
        # comment). A headless test without panel.show() cannot
        # meaningfully assert pixel position/row membership (every
        # widget added via addLayout() on a layout with no wrapping
        # QWidget shares the same parentWidget() regardless of which
        # row it visually renders on) — this instead re-confirms the
        # behavioral contract that actually matters survived the move:
        # Stop starts disabled, Start does not.
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        assert panel._start_btn.isEnabled()
        assert not panel._stop_btn.isEnabled()


# ══════════════════════════════════════════════════════════════════════════════
#  8. PanelMcp
# ══════════════════════════════════════════════════════════════════════════════
# Smoke-level only. The Ollama model dropdown/Refresh worker-callback tests
# (_mcp_on_ollama_models_loaded) were removed in v1.7.0.1 along with the
# feature itself (MCP_OLLAMA_MODEL removal, Zusatzpunkt) — this class now
# covers backend-box visibility, get_mcp_settings()/load_mcp_settings()
# passthrough, and the cloud credentials flow. Cloud config file I/O uses
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

    def test_mcp_stop_server_logs_success(self, qtbot, app_mock):
        # garmin_collector-3_experiment, Baustein 8b — symmetric Stop
        # button, shares clients/mcp_process.py with the Chat panel's own
        # Start/Stop pair.
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        mcp_process = MagicMock()
        mcp_process.stop.return_value = (True, "MCP server stopped (PID 1234).")
        with patch("app.panel_mcp._load_mcp_process", return_value=mcp_process):
            panel._mcp_stop_server()
        mcp_process.stop.assert_called_once()
        app_mock._log.assert_called_once()
        assert "MCP server stopped (PID 1234)." in app_mock._log.call_args[0][0]

    def test_mcp_stop_server_logs_failure(self, qtbot, app_mock):
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        mcp_process = MagicMock()
        mcp_process.stop.return_value = (False, "MCP server is not running.")
        with patch("app.panel_mcp._load_mcp_process", return_value=mcp_process):
            panel._mcp_stop_server()
        assert "MCP server is not running." in app_mock._log.call_args[0][0]

    def test_default_backend_is_ollama_box_visible(self, qtbot, app_mock):
        # Korrektur: isVisible() checks the entire parent chain up to a
        # shown top-level window — panel.show() is never called here, so
        # even a correctly-set-visible child reports False. isVisibleTo()
        # checks visibility relative to a given ancestor instead, which is
        # what setVisible()'s own flag actually controls.
        #
        # "ollama box" in the test name is now historical — the Ollama
        # model dropdown + Refresh button (and their containing box) were
        # removed in v1.7.0.1 (MCP_OLLAMA_MODEL removal, Zusatzpunkt).
        # Only the cloud credentials box still toggles by backend; this
        # test now just confirms it stays hidden on the ollama default.
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_on_backend_changed()
        assert not panel._mcp_cloud_box.isVisibleTo(panel)

    def test_backend_switch_to_cloud_swaps_visible_box(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_backend.setCurrentText("cloud")
        assert panel._mcp_cloud_box.isVisibleTo(panel)

    def test_get_mcp_settings_reflects_checkbox_and_backend(self, qtbot, app_mock):
        # "checkbox" in the test name is now historical — the Enable MCP
        # server checkbox was removed in v1.7 Teilbauauftrag g (had no
        # functional effect once main() stopped gating on it). Name kept
        # unchanged to avoid pure cosmetic churn; the test still covers
        # get_mcp_settings()'s remaining backend/port/headless behaviour.
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_backend.setCurrentText("cloud")
        s = panel.get_mcp_settings()
        # mcp_ollama_model (v1.7 Teilbauauftrag f) was removed in
        # v1.7.0.1 and replaced by mcp_http_port/mcp_headless — both
        # empty/False here since the panel never received
        # load_mcp_settings() input (Port QLineEdit starts empty,
        # Headless QCheckBox starts unchecked). mcp_extra_hosts_enabled/
        # mcp_extra_hosts (v1.7.0.2) are False/empty for the same reason —
        # the pre-filled default only appears via load_mcp_settings().
        assert s == {
            "mcp_llm_backend": "cloud",
            "mcp_http_port":   "",
            "mcp_headless":    False,
            "mcp_extra_hosts_enabled": False,
            "mcp_extra_hosts":         "",
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
        # v1.7.0.2 — extra-allowed-hosts defaults: checkbox off, field
        # disabled but pre-filled with the real default (garmin_config.
        # MCP_EXTRA_ALLOWED_HOSTS_RAW), preview reflects the disabled state.
        import garmin_config as cfg
        assert panel._mcp_extra_hosts_enabled.isChecked() is False
        assert panel._mcp_extra_hosts_field.isEnabled() is False
        assert panel._mcp_extra_hosts_field.text() == cfg.MCP_EXTRA_ALLOWED_HOSTS_RAW
        assert "Disabled" in panel._mcp_extra_hosts_preview.text()

    def test_extra_hosts_checkbox_enables_field(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        assert panel._mcp_extra_hosts_field.isEnabled() is False
        panel._mcp_extra_hosts_enabled.setChecked(True)
        assert panel._mcp_extra_hosts_field.isEnabled() is True

    def test_extra_hosts_preview_reflects_parsed_hosts(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_extra_hosts_enabled.setChecked(True)
        panel._mcp_extra_hosts_field.setText("host.docker.internal, myhost:9000")
        assert panel._mcp_extra_hosts_preview.text() == \
            "Recognized: host.docker.internal:*, myhost:9000"

    def test_extra_hosts_preview_shows_disabled_message_when_unchecked(
            self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_extra_hosts_field.setText("host.docker.internal")
        assert "Disabled" in panel._mcp_extra_hosts_preview.text()

    def test_get_mcp_settings_includes_extra_hosts_fields(self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        panel._mcp_extra_hosts_enabled.setChecked(True)
        panel._mcp_extra_hosts_field.setText("host.docker.internal")
        s = panel.get_mcp_settings()
        assert s["mcp_extra_hosts_enabled"] is True
        assert s["mcp_extra_hosts"] == "host.docker.internal"

    def test_cloud_config_status_no_file(self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", tmp_path / "missing.json"):
            panel._mcp_refresh_cloud_key_status()
        assert "No cloud config file" in panel._mcp_cloud_key_status.text()
        # Provider-Dropdown (garmin_collector-3_experiment) — no accidental
        # default selection when there is nothing on disk yet.
        assert panel._mcp_cloud_provider.currentIndex() == -1

    # ── Provider dropdown (garmin_collector-3_experiment) ───────────────────

    def test_cloud_provider_dropdown_populated_from_cloud_llm_client(
            self, qtbot, app_mock):
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        items = [panel._mcp_cloud_provider.itemText(i)
                 for i in range(panel._mcp_cloud_provider.count())]
        assert items == ["anthropic", "openai"]

    def test_cloud_config_status_selects_known_provider(
            self, qtbot, app_mock, tmp_path):
        # _load_cloud_credential_store() mocked so the key-status label
        # refresh this now triggers does not depend on whatever the real
        # Windows Credential Manager happens to hold on the test machine.
        import json
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        cfg_file.write_text(json.dumps(
            {"provider": "openai", "model": "gpt-4.1"}),
            encoding="utf-8")
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_mcp._load_cloud_credential_store",
                   return_value=MagicMock()):
            panel._mcp_refresh_cloud_key_status()
        assert panel._mcp_cloud_provider.currentText() == "openai"

    def test_cloud_config_status_preserves_unknown_legacy_provider(
            self, qtbot, app_mock, tmp_path):
        # A value saved before this dropdown existed (or a typo from the
        # old free-text field) must not be silently dropped on load.
        # _load_cloud_credential_store() mocked, same reason as the test
        # above.
        import json
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        cfg_file.write_text(json.dumps(
            {"provider": "gemini", "model": "some-model"}),
            encoding="utf-8")
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_mcp._load_cloud_credential_store",
                   return_value=MagicMock()):
            panel._mcp_refresh_cloud_key_status()
        assert panel._mcp_cloud_provider.currentText() == "gemini"

    def test_save_cloud_config_writes_file_and_clears_key_field(
            self, qtbot, app_mock, tmp_path):
        # Baustein 23: the API key goes to Windows Credential Manager
        # (mocked via _load_cloud_credential_store()), not the JSON file
        # — only provider/model are written there now.
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        panel._mcp_cloud_provider.setCurrentText("anthropic")
        panel._mcp_cloud_key.setText("sk-test-123")
        panel._mcp_cloud_model.setText("claude-sonnet-4-6")
        fake_store = MagicMock()
        fake_store.get_api_key.return_value = None
        fake_store.store_api_key.return_value = True
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_mcp._load_cloud_credential_store", return_value=fake_store):
            panel._mcp_save_cloud_config()
        import json
        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved == {"provider": "anthropic", "model": "claude-sonnet-4-6"}
        assert panel._mcp_cloud_key.text() == ""
        fake_store.store_api_key.assert_called_once_with("anthropic", "sk-test-123")

    def test_save_cloud_config_empty_key_keeps_existing(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        import json
        cfg_file.write_text(json.dumps({
            "provider": "anthropic", "model": "old-model",
        }), encoding="utf-8")
        panel._mcp_cloud_provider.setCurrentText("anthropic")
        panel._mcp_cloud_key.setText("")  # leave empty — keep existing
        panel._mcp_cloud_model.setText("new-model")
        fake_store = MagicMock()
        fake_store.get_api_key.return_value = "existing-key"
        with patch("garmin_config.MCP_LLM_CONFIG_FILE", cfg_file), \
             patch("app.panel_mcp._load_cloud_credential_store", return_value=fake_store):
            panel._mcp_save_cloud_config()
        saved = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved["model"] == "new-model"
        assert "api_key" not in saved
        # Empty key field must not overwrite the existing WCM entry.
        fake_store.store_api_key.assert_not_called()

    def test_save_cloud_config_missing_required_field_warns_no_write(
            self, qtbot, app_mock, tmp_path):
        from unittest.mock import patch
        from app.panel_mcp import PanelMcp
        panel = PanelMcp(app_mock)
        qtbot.addWidget(panel)
        cfg_file = tmp_path / "cloud.json"
        panel._mcp_cloud_provider.setCurrentIndex(-1)  # missing
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

    def test_collect_settings_preserves_active_theme(self, qtbot):
        """Regression test — active_theme is not bound to any Settings-panel
        widget, so _collect_settings() must carry it over from self.settings
        explicitly. Previously the key was silently dropped on app close
        because it was absent from all three panel sources it merges from.
        active_theme=3 (not the default 1) is used so the assertion actually
        proves the value was passed through, not just coincidentally equal
        to the default."""
        from unittest.mock import patch
        # NOTE: patch garmin_app_base.load_settings, not
        # garmin_app_settings.load_settings — garmin_app_base.py does
        # `load_settings = _settings.load_settings` at import time (a
        # re-export), so GarminApp.__init__()'s `self.settings =
        # load_settings()` call resolves the name already bound in
        # garmin_app_base's own namespace. Patching the origin module
        # (garmin_app_settings) does not reach that already-bound name.
        with patch("garmin_app_base.load_settings", return_value={
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
            "active_theme": 3,
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
        assert s.get("active_theme") == 3
