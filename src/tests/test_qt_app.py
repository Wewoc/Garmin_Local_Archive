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

import os
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

    def test_on_mirror_forwards_progress_lines_to_the_log(self, qtbot, app_mock, tmp_path, monkeypatch):
        """v1.7.6.2: the mirror runs minutes with the bulk store; the progress lines of run_mirror()
        reach the log (indented), before the closing line."""
        import sys
        import types
        from app import panel_archive as pa
        from app.panel_archive import PanelArchive

        app_mock._panel_settings._collect_settings.return_value = {
            "base_dir": str(tmp_path), "mirror_dir": str(tmp_path / "m.gla")}
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)

        class _Dialog:                                   # stands in for the password dialog
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return pa.QDialog.DialogCode.Accepted

            def get_result(self):
                return "pw"

        seen = {}

        def _fake_run_mirror(base_dir, path, password, progress=None):
            seen["progress"] = progress
            progress("  Mirror: packing raw (3 files, 1 MB) …")
            progress("  Mirror: raw packed in 1 s — 100 % of the data")
            return {"files_packed": 3, "errors": 0, "ok": True}

        fake = types.ModuleType("garmin_mirror")
        fake.run_mirror = _fake_run_mirror
        monkeypatch.setitem(sys.modules, "garmin_mirror", fake)
        monkeypatch.setattr(pa, "PasswordConfirmDialog", _Dialog)

        panel._on_mirror()
        qtbot.waitUntil(lambda: panel._mirror_running is False, timeout=5000)

        lines = [c.args[0] for c in app_mock._log_bg.call_args_list]
        assert callable(seen["progress"])
        assert lines[:2] == ["    Mirror: packing raw (3 files, 1 MB) …",
                             "    Mirror: raw packed in 1 s — 100 % of the data"]
        assert lines[-1].startswith("✓ Mirror complete: 3 files packed")

    def test_import_texts_name_the_bulk_files_only_when_there_are_some(self):
        """v1.7.6.2: the question before and the line after a mirror import mention the export data."""
        from app.panel_archive import _import_preview_text, _import_result_text
        assert _import_preview_text({"raw_to_copy": 2, "context_to_copy": 1}) == \
            "2 raw day(s) and 1 context file(s) will be imported."
        text = _import_preview_text({"raw_to_copy": 2, "context_to_copy": 1, "bulk_to_copy": 5, "originals_to_copy": 3})
        assert text.startswith("2 raw day(s) and 1 context file(s) will be imported.")
        assert "5 export day file(s)" in text and "3 original export file(s)" in text
        base = {"raw_copied": 2, "raw_skipped": 1, "context_copied": 0, "errors": 0, "ok": True}
        assert _import_result_text(base) == \
            "✓ Mirror import complete: 2 raw day(s) imported, 1 skipped, 0 context file(s) imported"
        full = _import_result_text({**base, "bulk_copied": 4, "originals_copied": 2, "export_days": 1,
                                    "errors": 3, "ok": False})
        assert full == ("⚠ Mirror import complete: 2 raw day(s) imported, 1 skipped, 0 context file(s) imported, "
                        "4 export day file(s), 2 original export file(s), 1 export-only day(s), 3 error(s)")

    def test_on_import_mirror_forwards_progress_lines_to_the_log(self, qtbot, app_mock, tmp_path, monkeypatch):
        """v1.7.6.2: the progress lines of the import reach the log (indented) before the closing line;
        the dry run before the question gets no callback."""
        import sys
        import types
        from PyQt6.QtWidgets import QFileDialog
        from app import panel_archive as pa
        from app.panel_archive import PanelArchive

        app_mock._panel_settings._collect_settings.return_value = {"base_dir": str(tmp_path)}
        app_mock._is_running.return_value = False
        app_mock._ctx_running = False
        app_mock._timer_active = False
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)

        class _Dialog:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return pa.QDialog.DialogCode.Accepted

            def get_result(self):
                return "pw"

        calls = []

        def _fake_run(mirror_path, base_dir, password="", dry_run=False, progress=None):
            calls.append((dry_run, progress))
            if dry_run:
                return {"ok": True, "raw_to_copy": 1, "context_to_copy": 0, "bulk_to_copy": 2,
                        "originals_to_copy": 1, "version_warning": ""}
            progress("  Import: raw days … 50 % (1 of 2)")
            return {"raw_copied": 1, "raw_skipped": 0, "context_copied": 0, "bulk_copied": 2,
                    "originals_copied": 1, "export_days": 0, "errors": 0, "ok": True}

        asked = []
        fake = types.ModuleType("garmin_import_mirror")
        fake.run_import_mirror = _fake_run
        monkeypatch.setitem(sys.modules, "garmin_import_mirror", fake)
        monkeypatch.setattr(pa, "PasswordConfirmDialog", _Dialog)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(tmp_path / "m.gla"), "")))
        monkeypatch.setattr(pa.QMessageBox, "question",
                            staticmethod(lambda parent, title, text, buttons: asked.append(text) or pa.QMessageBox.StandardButton.Yes))

        panel._on_import_mirror()
        qtbot.waitUntil(lambda: panel._mirror_running is False, timeout=5000)

        lines = [c.args[0] for c in app_mock._log_bg.call_args_list]
        assert calls[0][0] is True and calls[0][1] is None
        assert calls[1][0] is False and callable(calls[1][1])
        assert "2 export day file(s)" in asked[0]
        assert lines[0] == "    Import: raw days … 50 % (1 of 2)"
        assert lines[-1].startswith("✓ Mirror import complete: 1 raw day(s) imported")
        assert "2 export day file(s), 1 original export file(s)" in lines[-1]

    def _silo_panel(self, qtbot, app_mock):
        from app.panel_archive import PanelArchive
        app_mock._is_running.return_value = False
        app_mock._ctx_running = False
        app_mock._timer_active = False
        panel = PanelArchive(app_mock)
        qtbot.addWidget(panel)
        return panel

    def test_silo_check_names_the_lost_bulk_files(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2: finding #8 gets its line (five days named, the kind in brackets, then an ellipsis) and
        enables the repair; without it the check does not mention bulk files."""
        import sys
        import types
        from datetime import date
        panel = self._silo_panel(qtbot, app_mock)

        def _result(intraday, aggregates):
            counts = {"raw_without_quality": 0, "source_without_raw": 0, "summary_without_raw": 0,
                      "raw_without_summary": 0, "bulk_lost_intraday": len(intraday),
                      "bulk_lost_aggregates": len(aggregates)}
            return {"checked_at": "T", "totals": {"raw": 1, "summary": 1, "source": 0, "aggregates": 2, "quality_days": 3},
                    "counts": counts, "raw_without_quality": [], "source_without_raw": [],
                    "summary_without_raw": [], "raw_without_summary": [],
                    "bulk_lost_intraday": intraday, "bulk_lost_aggregates": aggregates}

        def _run(result):
            fake = types.ModuleType("garmin_silo_check")
            fake.check_silos = lambda: result
            monkeypatch.setitem(sys.modules, "garmin_silo_check", fake)
            app_mock._log_bg.reset_mock()
            panel._on_silo_check()
            qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
            return [c.args[0] for c in app_mock._log_bg.call_args_list]

        lines = _run(_result([date(2025, 8, 2)], [date(2025, 8, 3), date(2025, 8, 4)]))
        lost = [x for x in lines if "#8" in x]
        assert lost == ["    ⚠ #8 bulk files lost (marked in the quality log, missing in the store): "
                        "3 file(s) — 2025-08-02 (intraday), 2025-08-03 (daily values), 2025-08-04 (daily values)"]
        assert lines[-1].startswith("    → Use")
        lines = _run(_result([], [date(2025, 8, n) for n in range(1, 8)]))
        assert [x for x in lines if "#8" in x][0].endswith("2025-08-05 (daily values)…") and "7 file(s)" in lines[2]
        lines = _run(_result([], [date(2025, 8, n) for n in range(1, 6)]))
        assert [x for x in lines if "#8" in x][0].endswith("2025-08-05 (daily values)")          # exactly five: no ellipsis
        lines = _run(_result([], []))
        assert not any("#8" in x for x in lines) and "No inconsistencies" in lines[-1]

    def test_silo_repair_logs_the_restore_of_bulk_files(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2: every status of category 8 has its own log line."""
        import sys
        import types
        panel = self._silo_panel(qtbot, app_mock)
        fake_check = types.ModuleType("garmin_silo_check")
        fake_check.check_silos = lambda: {"fresh": True}
        fake_repair = types.ModuleType("garmin_silo_repair")
        seen = {}

        def _repair(fresh):
            seen["fresh"] = fresh
            return {"ok": 1, "failed": 3, "items": [
                {"category": "8", "date": "2025-08-01", "kind": "intraday", "status": "repaired"},
                {"category": "8", "date": "2025-08-02", "kind": "aggregates", "status": "present"},
                {"category": "8", "date": "2025-08-03", "kind": "aggregates", "status": "no_backup"},
                {"category": "8", "date": "2025-08-04", "kind": "intraday", "status": "error", "reason": "boom"}]}

        fake_repair.repair_silos = _repair
        monkeypatch.setitem(sys.modules, "garmin_silo_check", fake_check)
        monkeypatch.setitem(sys.modules, "garmin_silo_repair", fake_repair)
        panel._last_silo_result = {"anything": 1}
        panel._on_silo_repair()
        qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
        lines = [c.args[0] for c in app_mock._log_bg.call_args_list]
        assert seen["fresh"] == {"fresh": True}
        assert lines[:4] == ["  ✓ #8 restored from backup: 2025-08-01 (intraday)",
                             "  ~ #8 already back: 2025-08-02 (daily values)",
                             "  ✗ #8 no backup copy for 2025-08-03 (daily values) — import the export again",
                             "  ✗ #8 repair error 2025-08-04 (intraday): boom"]
        assert lines[-1] == "🔧  Silo-Repair complete — 1 fixed, 3 errors"

    def test_silo_check_names_the_missing_originals(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2: finding #9 gets its line (the first twelve characters of up to five hashes, then an ellipsis).
        v1.7.6.2.1: the FIT line says the backup is a second source, and JSON originals get a line of their own."""
        import sys
        import types
        panel = self._silo_panel(qtbot, app_mock)

        def _run(hashes, json_hashes=None):
            counts = {"raw_without_quality": 0, "source_without_raw": 0, "summary_without_raw": 0,
                      "raw_without_summary": 0, "bulk_originals_missing": len(hashes)}
            result = {"checked_at": "T", "totals": {"raw": 0, "summary": 0, "source": 0, "aggregates": 0, "quality_days": 0},
                      "counts": counts,
                      "raw_without_quality": [], "source_without_raw": [], "summary_without_raw": [],
                      "raw_without_summary": [], "bulk_originals_missing": hashes}
            if json_hashes is not None:
                counts["bulk_json_originals_missing"] = len(json_hashes)
                result["bulk_json_originals_missing"] = json_hashes
            fake = types.ModuleType("garmin_silo_check")
            fake.check_silos = lambda: result
            monkeypatch.setitem(sys.modules, "garmin_silo_check", fake)
            app_mock._log_bg.reset_mock()
            panel._on_silo_check()
            qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
            return [c.args[0] for c in app_mock._log_bg.call_args_list]

        hashes = [f"{n}{n}" * 32 for n in "abcdef"]
        lines = _run(hashes[:5])
        line = [x for x in lines if "#9" in x]
        assert line == ["    ⚠ #9 original export files missing (not in the store; named by an intraday day file or held "
                        "by the backup): 5 file(s) — aaaaaaaaaaaa, bbbbbbbbbbbb, cccccccccccc, dddddddddddd, eeeeeeeeeeee"]
        lines = _run(hashes)
        assert [x for x in lines if "#9" in x][0].endswith("eeeeeeeeeeee…") and "6 file(s)" in [x for x in lines if "#9" in x][0]
        assert not any("#9" in x for x in _run([]))
        # an older result without the JSON key (and one with an empty list) shows no JSON line
        assert not any("JSON" in x for x in _run(hashes[:2]))
        assert not any("JSON" in x for x in _run(hashes[:2], []))

    def test_silo_check_names_the_missing_json_originals(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2.1: a JSON original the backup holds and the store lacks gets its own #9 line, the same shape as the FIT one;
        it counts as a finding even when nothing else is wrong (the Repair button comes on)."""
        import sys
        import types
        panel = self._silo_panel(qtbot, app_mock)

        def _run(json_hashes):
            result = {"checked_at": "T", "totals": {"raw": 0, "summary": 0, "source": 0, "aggregates": 0, "quality_days": 0},
                      "counts": {"raw_without_quality": 0, "source_without_raw": 0, "summary_without_raw": 0,
                                 "raw_without_summary": 0, "bulk_originals_missing": 0,
                                 "bulk_json_originals_missing": len(json_hashes)},
                      "raw_without_quality": [], "source_without_raw": [], "summary_without_raw": [],
                      "raw_without_summary": [], "bulk_originals_missing": [],
                      "bulk_json_originals_missing": json_hashes}
            fake = types.ModuleType("garmin_silo_check")
            fake.check_silos = lambda: result
            monkeypatch.setitem(sys.modules, "garmin_silo_check", fake)
            app_mock._log_bg.reset_mock()
            panel._on_silo_check()
            qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
            return [c.args[0] for c in app_mock._log_bg.call_args_list]

        hashes = [f"{n}{n}" * 32 for n in "abcdef"]
        lines = _run(hashes[:5])
        assert [x for x in lines if "#9" in x] == [
            "    ⚠ #9 original export JSON files missing (held by the backup, not in the store): "
            "5 file(s) — aaaaaaaaaaaa, bbbbbbbbbbbb, cccccccccccc, dddddddddddd, eeeeeeeeeeee"]
        assert not any("No inconsistencies" in x for x in lines) and any("Repair" in x for x in lines)
        lines = _run(hashes)
        assert [x for x in lines if "#9" in x][0].endswith("eeeeeeeeeeee…") and "6 file(s)" in [x for x in lines if "#9" in x][0]
        assert not any("#9" in x for x in _run([]))

    def test_silo_repair_logs_the_restore_of_originals(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2: every status of category 9 has its own log line, the hash shortened to twelve characters."""
        import sys
        import types
        panel = self._silo_panel(qtbot, app_mock)
        fake_check = types.ModuleType("garmin_silo_check")
        fake_check.check_silos = lambda: {"fresh": True}
        fake_repair = types.ModuleType("garmin_silo_repair")
        fake_repair.repair_silos = lambda fresh: {"ok": 1, "failed": 2, "items": [
            {"category": "9", "date": None, "hash": "a1" * 32, "status": "repaired"},
            {"category": "9", "date": None, "hash": "b2" * 32, "status": "present"},
            {"category": "9", "date": None, "hash": "c3" * 32, "status": "no_backup"},
            {"category": "9", "date": None, "hash": "d4" * 32, "status": "error", "reason": "boom"}]}
        monkeypatch.setitem(sys.modules, "garmin_silo_check", fake_check)
        monkeypatch.setitem(sys.modules, "garmin_silo_repair", fake_repair)
        panel._last_silo_result = {"anything": 1}
        panel._on_silo_repair()
        qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
        lines = [c.args[0] for c in app_mock._log_bg.call_args_list]
        assert lines[:4] == ["  ✓ #9 original restored from backup: a1a1a1a1a1a1",
                             "  ~ #9 original already back: b2b2b2b2b2b2",
                             "  ✗ #9 no backup copy for original c3c3c3c3c3c3 — import the export again",
                             "  ✗ #9 repair error d4d4d4d4d4d4: boom"]

    def test_silo_repair_logs_the_restore_of_json_originals(self, qtbot, app_mock, monkeypatch):
        """v1.7.6.2.1: the items of a JSON original carry kind "json"; every status has its line, marked (JSON), next to the
        unmarked lines of a FIT original."""
        import sys
        import types
        panel = self._silo_panel(qtbot, app_mock)
        fake_check = types.ModuleType("garmin_silo_check")
        fake_check.check_silos = lambda: {"fresh": True}
        fake_repair = types.ModuleType("garmin_silo_repair")
        fake_repair.repair_silos = lambda fresh: {"ok": 2, "failed": 2, "items": [
            {"category": "9", "date": None, "hash": "a1" * 32, "status": "repaired"},
            {"category": "9", "date": None, "hash": "e5" * 32, "kind": "json", "status": "repaired"},
            {"category": "9", "date": None, "hash": "f6" * 32, "kind": "json", "status": "present"},
            {"category": "9", "date": None, "hash": "c3" * 32, "kind": "json", "status": "no_backup"},
            {"category": "9", "date": None, "hash": "d4" * 32, "kind": "json", "status": "error", "reason": "boom"}]}
        monkeypatch.setitem(sys.modules, "garmin_silo_check", fake_check)
        monkeypatch.setitem(sys.modules, "garmin_silo_repair", fake_repair)
        panel._last_silo_result = {"anything": 1}
        panel._on_silo_repair()
        qtbot.waitUntil(lambda: panel._silo_running is False, timeout=5000)
        lines = [c.args[0] for c in app_mock._log_bg.call_args_list]
        assert lines[:5] == ["  ✓ #9 original restored from backup: a1a1a1a1a1a1",
                             "  ✓ #9 original restored from backup: e5e5e5e5e5e5 (JSON)",
                             "  ~ #9 original already back: f6f6f6f6f6f6 (JSON)",
                             "  ✗ #9 no backup copy for original c3c3c3c3c3c3 (JSON) — import the export again",
                             "  ✗ #9 repair error d4d4d4d4d4d4 (JSON): boom"]

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

    def test_toggle_timer_starts_when_off(self, qtbot, app_mock, monkeypatch):
        """threading.Thread is mocked for this test only — _toggle_timer()
        otherwise spawns a real daemon thread that (via _timer_loop's
        one-time connection test) attempts a real garmin_api.login() import
        with the fixture's fake credentials. Nothing in this test previously
        stopped/joined that thread, so it kept running into later tests —
        harmless on its own, but colliding with a later test's own fresh
        module imports on Windows triggers a real access violation (found
        2026-09-21 while adding v1.7.2.4's process_status lock-file I/O to
        GarminApp.__init__/closeEvent, which shifted timing enough to newly
        expose this pre-existing race). The state flip under test doesn't
        need the real thread at all — mocking Thread removes the risk
        without changing what's being asserted."""
        from app.panel_timer import PanelTimer
        from unittest.mock import MagicMock
        monkeypatch.setattr("app.panel_timer.threading.Thread", MagicMock())
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

    def test_restore_button_disabled_by_default(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert not panel._restore_btn.isEnabled()

    def test_daily_update_auto_update_checkbox_defaults_unchecked(
            self, qtbot, app_mock):
        """v1.7.2.4 — opt-in, so an absent settings key must mean off,
        not on (safe default before the user has ever touched it)."""
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel._daily_update_auto_update.isChecked() is False

    def test_daily_update_auto_update_checkbox_reflects_saved_setting(
            self, qtbot, app_mock):
        app_mock.settings = {"daily_update_auto_update": True}
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel._daily_update_auto_update.isChecked() is True

    def test_daily_update_auto_update_toggle_persists_immediately(
            self, qtbot, app_mock):
        """Matches _on_theme_apply()'s behavior: a toggle here writes to
        self._app.settings and saves right away, not only on app close."""
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        panel._daily_update_auto_update.setChecked(True)
        assert app_mock.settings["daily_update_auto_update"] is True
        app_mock._panel_settings._safe_save.assert_called_with(app_mock.settings)

    def test_daily_update_auto_migrate_checkbox_defaults_unchecked(
            self, qtbot, app_mock):
        """v1.7.6.4 — opt-in, an absent settings key must mean off."""
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel._daily_update_auto_migrate.isChecked() is False

    def test_daily_update_auto_migrate_checkbox_reflects_saved_setting(
            self, qtbot, app_mock):
        app_mock.settings = {"daily_update_auto_migrate": True}
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        assert panel._daily_update_auto_migrate.isChecked() is True
        assert panel._daily_update_auto_update.isChecked() is False

    def test_daily_update_auto_migrate_toggle_persists_immediately(
            self, qtbot, app_mock):
        """A toggle writes only its own key and saves right away; the
        auto-update key is not touched."""
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        panel._daily_update_auto_migrate.setChecked(True)
        assert app_mock.settings["daily_update_auto_migrate"] is True
        assert "daily_update_auto_update" not in app_mock.settings
        app_mock._panel_settings._safe_save.assert_called_with(app_mock.settings)
        panel._daily_update_auto_migrate.setChecked(False)
        assert app_mock.settings["daily_update_auto_migrate"] is False

    def test_set_restore_button_state_enable(self, qtbot, app_mock):
        from app.panel_outputs import PanelOutputs
        panel = PanelOutputs(app_mock)
        qtbot.addWidget(panel)
        panel.set_restore_button_state(True, text="Restore Data")
        assert panel._restore_btn.isEnabled()

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
#  ContextCheckResultDialog / ContextCoordinateFixDialog (v1.7.2.3)
# ══════════════════════════════════════════════════════════════════════════════
# Same "call internal methods directly, never .exec()" pattern as
# TestPasswordConfirmDialog above — no automated way to drive a real
# modal event loop in this environment.

class TestDialogContextCheck:

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

    def _make_result(self, bad_coordinates=None, missing=None, day_location=None):
        return {
            "totals": {"days_in_range": 10, "weather": 10, "pollen": 10,
                       "brightsky": 10, "airquality": 10},
            "missing_days": missing or {"weather": [], "pollen": [],
                                         "brightsky": [], "airquality": []},
            "bad_coordinates": bad_coordinates or [],
            "day_location": day_location or [],
            "checked_at": "2026-09-20T10:00:00Z",
        }

    def _findings(self):
        return [
            {"date": "2026-01-05", "source": "weather", "reason": "drift",
             "stored": (52.10, 8.40), "expected": (52.1235, 8.6539), "distance_km": 17.3},
            {"date": "2026-01-06", "source": "pollen", "reason": "zero",
             "stored": (0.0, 0.0), "expected": (52.1235, 8.6539), "distance_km": None},
        ]

    # ── ContextCheckResultDialog ────────────────────────────────────────────────

    def test_result_dialog_fix_button_disabled_when_no_bad_coordinates(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCheckResultDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCheckResultDialog(parent=parent, result=self._make_result(bad_coordinates=[]))
        qtbot.addWidget(dlg)
        assert not dlg._fix_btn.isEnabled()

    def test_result_dialog_fix_button_enabled_with_bad_coordinates(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCheckResultDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCheckResultDialog(
            parent=parent, result=self._make_result(bad_coordinates=self._findings()))
        qtbot.addWidget(dlg)
        assert dlg._fix_btn.isEnabled()
        assert "2" in dlg._fix_btn.text()

    def test_result_dialog_handles_missing_days_present(self, qtbot, app_mock):
        """Missing-days section (informational, no button) renders without crashing."""
        from app.dialog_context_check import ContextCheckResultDialog
        parent = self._fake_parent(qtbot, app_mock)
        result = self._make_result(
            missing={"weather": [], "pollen": ["2026-01-01"],
                     "brightsky": [], "airquality": []})
        dlg = ContextCheckResultDialog(parent=parent, result=result)
        qtbot.addWidget(dlg)
        assert dlg is not None

    def test_result_dialog_handles_all_clean_result(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCheckResultDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCheckResultDialog(parent=parent, result=self._make_result())
        qtbot.addWidget(dlg)
        assert not dlg._fix_btn.isEnabled()

    # ── ContextCoordinateFixDialog ──────────────────────────────────────────────

    def test_fix_dialog_checkboxes_pre_checked(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        assert len(dlg._checkboxes) == 2
        assert all(cb.isChecked() for cb, _ in dlg._checkboxes)

    def test_fix_dialog_get_fixes_default_uses_expected_coordinate(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        assert dlg.get_fixes() == [
            {"date": "2026-01-05", "source": "weather", "lat": 52.1235, "lon": 8.6539},
            {"date": "2026-01-06", "source": "pollen", "lat": 52.1235, "lon": 8.6539},
        ]

    def test_fix_dialog_get_fixes_respects_unchecked(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        dlg._checkboxes[0][0].setChecked(False)
        fixes = dlg.get_fixes()
        assert len(fixes) == 1
        assert fixes[0]["date"] == "2026-01-06"

    def test_fix_dialog_maps_link_overrides_all_checked(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        dlg._maps_url.setText("https://www.google.com/maps/@52.5000,13.4000,15z")
        dlg._on_apply_link()
        fixes = dlg.get_fixes()
        assert all(f["lat"] == 52.5 and f["lon"] == 13.4 for f in fixes)

    def test_fix_dialog_invalid_link_falls_back_to_expected(self, qtbot, app_mock):
        """A URL with no @lat,lon pattern must not silently poison every fix
        with garbage coordinates — falls back to each finding's own expected value."""
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        dlg._maps_url.setText("https://www.google.com/maps/not-a-real-link")
        dlg._on_apply_link()
        assert dlg._link_lat is None
        fixes = dlg.get_fixes()
        assert fixes[0]["lat"] == 52.1235

    def test_fix_dialog_empty_link_field_does_not_set_link_coords(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=self._findings())
        qtbot.addWidget(dlg)
        dlg._on_apply_link()  # clicked with an empty field
        assert dlg._link_lat is None
        assert dlg.get_fixes()[0]["lat"] == 52.1235

    def test_fix_dialog_no_findings_builds_without_crashing(self, qtbot, app_mock):
        from app.dialog_context_check import ContextCoordinateFixDialog
        parent = self._fake_parent(qtbot, app_mock)
        dlg = ContextCoordinateFixDialog(parent=parent, findings=[])
        qtbot.addWidget(dlg)
        assert dlg.get_fixes() == []


# ══════════════════════════════════════════════════════════════════════════════
#  7. PanelChat
# ══════════════════════════════════════════════════════════════════════════════
# Smoke-level only — no real threading.Thread runs (would hit the real
# Ollama HTTP client). Worker-callback methods (_chat_on_stream_done/_chat_on_error/
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
        # garmin_collector-3_experiment, Baustein 30 — the maintainer, live: Stop
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

    def test_collect_settings_preserves_daily_update_auto_migrate(self, qtbot):
        """v1.7.6.4 — like active_theme, the opt-in has no Settings-panel
        widget; _collect_settings() must carry it over or closeEvent() drops
        it on every save. True is used so the value is not the default."""
        from unittest.mock import patch
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
            "daily_update_auto_migrate": True,
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        s = app._collect_settings()
        assert s.get("daily_update_auto_migrate") is True

    def test_collect_settings_daily_update_auto_migrate_absent_is_off(self):
        """v1.7.6.4 — a settings dict without the key must collect as off,
        never on (the opt-in has to be switched on by the user)."""
        from unittest.mock import MagicMock
        from garmin_app_base import GarminApp
        fake = MagicMock()
        fake.settings = {}
        fake._panel_settings._collect_settings.return_value = {}
        fake._panel_timer.get_timer_settings.return_value = {}
        fake._panel_mcp.get_mcp_settings.return_value = {}
        s = GarminApp._collect_settings(fake)
        assert s["daily_update_auto_migrate"] is False
        assert s["daily_update_auto_update"] is False

    # ── v1.7.2.4 — T3 self-update wiring (Bauauftrag Schritt 9) ─────────────

    def _make_test_app(self, qtbot):
        """Shared setup for the _start_update() tests below — same
        patch/subclass pattern as the other TestGarminAppBase tests."""
        from unittest.mock import patch
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
        }), patch("garmin_app_settings.load_password", return_value=""), \
            patch("garmin_app_controller.check_migration_needed",
                  return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def _startup_bg_checks(self): pass
                def closeEvent(self, event):
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        # _dispatch() normally queues onto the Qt event loop for
        # cross-thread safety — for this synchronous test, call straight
        # through instead so assertions don't race the event loop.
        app._dispatch = lambda fn, *a: fn(*a)
        return app

    def _release_json(self):
        import updater as _updater
        return {"assets": [
            {"name": _updater.T3_ZIP_ASSET_NAME,
             "browser_download_url": "https://example.com/fake.zip"},
            {"name": _updater.T3_ZIP_CHECKSUM_ASSET_NAME,
             "browser_download_url": "https://example.com/fake.zip.sha256"},
        ]}

    def _release_json_t2(self):
        """v1.7.2.4-Nacherweiterung — T2-Pendant zu _release_json()."""
        import updater as _updater
        return {"assets": [
            {"name": _updater.T2_ZIP_ASSET_NAME,
             "browser_download_url": "https://example.com/fake_t2.zip"},
            {"name": _updater.T2_ZIP_CHECKSUM_ASSET_NAME,
             "browser_download_url": "https://example.com/fake_t2.zip.sha256"},
        ]}

    def _simulate_frozen_t3(self, monkeypatch, tmp_path):
        """Setzt sys.frozen/sys.executable gegen ein echtes T3-Verzeichnis,
        damit frozen_paths.is_t3_standalone() real statt gemockt läuft."""
        import sys
        exe = tmp_path / "Garmin_Local_Archive_Standalone.exe"
        exe.write_text("x")
        (tmp_path / "daily_update.exe").write_text("x")
        (tmp_path / "mcp_server.exe").write_text("x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))

    def _simulate_frozen_t2(self, monkeypatch, tmp_path):
        """Setzt sys.frozen/sys.executable gegen ein echtes T2-Verzeichnis,
        damit is_t3_standalone()/is_t2_standard() real statt gemockt laufen."""
        import sys
        exe = tmp_path / "Garmin_Local_Archive.exe"
        exe.write_text("x")
        dash_dir = tmp_path / "scripts" / "dashboards"
        dash_dir.mkdir(parents=True)
        (dash_dir / "dash_runner.py").write_text("x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))

    def test_start_update_success_no_mcp(self, qtbot, monkeypatch, tmp_path):
        """No MCP running: helper gets -RestartGui but no -RestartMcpCmd,
        prepare_update() is called with the resolved asset URLs, and the
        app closes itself afterward so the helper can replace its files."""
        import sys
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)

        # v1.7.2.4-Nacherweiterung — _start_update() ermittelt das Target
        # jetzt selbst; echte T3-Verzeichnisstruktur statt gemockter
        # Funktion (B1, Testsuite-Rework 2026-09-25).
        self._simulate_frozen_t3(monkeypatch, tmp_path)

        prepare_calls = []
        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: (
                prepare_calls.append((exe_dir, zip_url, checksum_url)),
                tmp_path)[1])
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: False)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        closed = []
        monkeypatch.setattr(app, "close", lambda: closed.append(True))

        app._start_update("v9.9.9", self._release_json())

        assert len(prepare_calls) == 1
        assert prepare_calls[0][1] == "https://example.com/fake.zip"
        assert prepare_calls[0][2] == "https://example.com/fake.zip.sha256"
        assert len(popen_calls) == 1
        args = popen_calls[0]
        assert args[0] == "powershell.exe"
        assert str(Path(sys.executable).parent / "updater_helper.ps1") == \
            args[args.index("-File") + 1]
        assert "-RestartGui" in args
        assert args[args.index("-GuiExeName") + 1] == \
            "Garmin_Local_Archive_Standalone.exe"
        assert "-RestartMcpCmd" not in args
        assert closed == [True]
        # T3's GUI is --onedir (no bootloader/child split) - only this
        # process's own PID, not the parent, unlike T2's --onefile case.
        wait_pids = args[args.index("-WaitPids") + 1].split(",")
        assert wait_pids == [str(os.getpid())]

    def test_start_update_success_with_mcp_running(self, qtbot, monkeypatch, tmp_path):
        """MCP running: gets stopped before the helper launches, and the
        helper is told to restart it afterward (-RestartMcpCmd)."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)

        # v1.7.2.4-Nacherweiterung — Target + MCP-Kommando-Auflösung
        # jetzt explizit auf T3 festnageln; echte T3-Verzeichnisstruktur
        # statt gemockter Funktion (B1, Testsuite-Rework 2026-09-25).
        self._simulate_frozen_t3(monkeypatch, tmp_path)
        fake_mcp_exe = str(tmp_path / "mcp_server.exe")
        monkeypatch.setattr(
            "garmin_app_base._resolve_mcp_server_launch_command",
            lambda: [fake_mcp_exe])

        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: tmp_path)
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: True)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        mock_mcp_process = MagicMock()
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "mcp_process", mock_mcp_process)
        monkeypatch.setattr(
            "frozen_paths.scripts_root", lambda: tmp_path, raising=False)
        monkeypatch.setattr(
            "frozen_paths.add_to_path", lambda *a, **kw: None, raising=False)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        monkeypatch.setattr(app, "close", lambda: None)

        app._start_update("v9.9.9", self._release_json())

        mock_mcp_process.stop.assert_called_once()
        assert len(popen_calls) == 1
        args = popen_calls[0]
        assert "-RestartMcpCmd" in args
        assert args[args.index("-RestartMcpCmd") + 1] == fake_mcp_exe

    def test_start_update_no_t3_asset_logs_and_stops(self, qtbot, monkeypatch, tmp_path):
        """Release without a T3 ZIP asset: logs an error, never touches
        prepare_update()/Popen/close — matches the same "verify before
        anything destructive" spirit as prepare_update() itself."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t3(monkeypatch, tmp_path)
        prepare_calls = []
        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda *a, **kw: prepare_calls.append(1))
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda *a, **kw: popen_calls.append(1) or MagicMock())
        closed = []
        monkeypatch.setattr(app, "close", lambda: closed.append(True))

        app._start_update("v9.9.9", {"assets": []})

        assert prepare_calls == []
        assert popen_calls == []
        assert closed == []
        assert "release has no T3 ZIP asset" in app.log.toPlainText()

    def test_start_update_prepare_failure_logs_and_stops(self, qtbot, monkeypatch, tmp_path):
        """prepare_update() raising (network/checksum/zip failure): logs
        the error, never launches the helper or closes the app."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t3(monkeypatch, tmp_path)

        def _boom(*a, **kw):
            raise RuntimeError("checksum mismatch")
        monkeypatch.setattr("garmin_app_base.updater.prepare_update", _boom)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda *a, **kw: popen_calls.append(1) or MagicMock())
        closed = []
        monkeypatch.setattr(app, "close", lambda: closed.append(True))

        app._start_update("v9.9.9", self._release_json())

        assert popen_calls == []
        assert closed == []
        assert "checksum mismatch" in app.log.toPlainText()

    # ── v1.7.2.4-Nacherweiterung — T2-Zweig von _start_update() ──────────────

    def test_start_update_success_t2_no_mcp(self, qtbot, monkeypatch, tmp_path):
        """T2 (is_t3_standalone() False): T2-Asset-Namen werden aufgelöst,
        -GuiExeName ist Garmin_Local_Archive.exe (kein _Standalone-Suffix),
        kein -RestartMcpCmd wenn MCP nicht lief. v1.7.2.4.1 Variante A
        (2026-09-25): kein -RestartGui mehr für T2 (onefile-Extraktion
        crashte den automatischen Neustart auch mit Retry + Defender-
        Ausschluss weiterhin) - stattdessen ein Hinweis-Dialog vor dem
        Schließen, dass manuell neu gestartet werden muss."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t2(monkeypatch, tmp_path)

        prepare_calls = []
        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: (
                prepare_calls.append((exe_dir, zip_url, checksum_url)),
                tmp_path)[1])
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: False)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        closed = []
        monkeypatch.setattr(app, "close", lambda: closed.append(True))
        info_calls = []
        monkeypatch.setattr(
            "garmin_app_base.QMessageBox.information",
            lambda *a, **kw: info_calls.append(a) or None)

        app._start_update("v9.9.9", self._release_json_t2())

        assert len(prepare_calls) == 1
        assert prepare_calls[0][1] == "https://example.com/fake_t2.zip"
        assert prepare_calls[0][2] == "https://example.com/fake_t2.zip.sha256"
        assert len(popen_calls) == 1
        args = popen_calls[0]
        assert args[args.index("-GuiExeName") + 1] == "Garmin_Local_Archive.exe"
        assert "-RestartGui" not in args
        assert "-RestartMcpCmd" not in args
        assert closed == [True]
        # T2 gets no automatic restart (Variante A) - but a manual-restart
        # notice must still be shown before the app closes on its own.
        assert len(info_calls) == 1
        # T2's GUI is --onefile - the swap itself still must wait for the
        # bootloader parent process (os.getppid()), not just this child
        # (os.getpid()), even though there's no automatic restart anymore.
        wait_pids = args[args.index("-WaitPids") + 1].split(",")
        assert str(os.getpid()) in wait_pids
        assert str(os.getppid()) in wait_pids

    def test_start_update_success_t2_with_mcp_running(
            self, qtbot, monkeypatch, tmp_path):
        """T2 mit laufendem MCP: -RestartMcpCmd zeigt auf
        Starte_MCP_Server.bat (T2s MCP-Startweg), nicht auf mcp_server.exe
        (T3.3) — _resolve_mcp_server_launch_command() liefert das bereits
        korrekt, hier nur die Weiterleitung in die Popen-Argumente
        geprüft."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t2(monkeypatch, tmp_path)
        fake_bat = str(tmp_path / "Starte_MCP_Server.bat")
        monkeypatch.setattr(
            "garmin_app_base._resolve_mcp_server_launch_command",
            lambda: [fake_bat])

        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: tmp_path)
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: True)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        mock_mcp_process = MagicMock()
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "mcp_process", mock_mcp_process)
        monkeypatch.setattr(
            "frozen_paths.scripts_root", lambda: tmp_path, raising=False)
        monkeypatch.setattr(
            "frozen_paths.add_to_path", lambda *a, **kw: None, raising=False)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        monkeypatch.setattr(app, "close", lambda: None)
        monkeypatch.setattr(
            "garmin_app_base.QMessageBox.information", lambda *a, **kw: None)

        app._start_update("v9.9.9", self._release_json_t2())

        mock_mcp_process.stop.assert_called_once()
        assert len(popen_calls) == 1
        args = popen_calls[0]
        assert args[args.index("-GuiExeName") + 1] == "Garmin_Local_Archive.exe"
        assert "-RestartGui" not in args  # Variante A (2026-09-25)
        assert "-RestartMcpCmd" in args
        assert args[args.index("-RestartMcpCmd") + 1] == fake_bat

    def test_start_update_no_t2_asset_logs_and_stops(self, qtbot, monkeypatch, tmp_path):
        """T2, Release ohne T2-ZIP-Asset: loggt den T2-spezifischen
        Fehlertext, fasst prepare_update()/Popen/close nicht an."""
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t2(monkeypatch, tmp_path)
        prepare_calls = []
        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda *a, **kw: prepare_calls.append(1))
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda *a, **kw: popen_calls.append(1) or MagicMock())
        closed = []
        monkeypatch.setattr(app, "close", lambda: closed.append(True))

        app._start_update("v9.9.9", {"assets": []})

        assert prepare_calls == []
        assert popen_calls == []
        assert closed == []
        assert "release has no T2 ZIP asset" in app.log.toPlainText()

    def test_start_update_popen_flags_match_helper_ps1_params(
            self, qtbot, monkeypatch, tmp_path, app_root):
        """Contract check (B2, Testsuite-Rework 2026-09-25): jedes -Flag,
        das _start_update() an updater_helper.ps1 übergibt, muss dort ein
        echter Parameter sein — deckt Drift auf beiden Seiten auf, den die
        bestehenden Verhaltenstests (fester Popen-Mock) nicht sehen können,
        da sie nur gegen garmin_app_base.py's eigene Literale prüfen.
        Nutzt das reichste Szenario (T3 + laufendes MCP), damit alle sechs
        Flags, die _start_update() je erzeugen kann, in einem Aufruf stehen."""
        import re
        from unittest.mock import MagicMock

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t3(monkeypatch, tmp_path)
        fake_mcp_exe = str(tmp_path / "mcp_server.exe")
        monkeypatch.setattr(
            "garmin_app_base._resolve_mcp_server_launch_command",
            lambda: [fake_mcp_exe])

        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: tmp_path)
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: True)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        mock_mcp_process = MagicMock()
        import sys as _sys
        monkeypatch.setitem(_sys.modules, "mcp_process", mock_mcp_process)
        monkeypatch.setattr(
            "frozen_paths.scripts_root", lambda: tmp_path, raising=False)
        monkeypatch.setattr(
            "frozen_paths.add_to_path", lambda *a, **kw: None, raising=False)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        monkeypatch.setattr(app, "close", lambda: None)

        app._start_update("v9.9.9", self._release_json())

        assert len(popen_calls) == 1
        args = popen_calls[0]

        ps1_text = (app_root / "updater_helper.ps1").read_text(encoding="utf-8")
        param_block = re.search(r"param\((.*?)\n\)", ps1_text, re.DOTALL)
        assert param_block is not None, "updater_helper.ps1: param() block not found"
        ps1_param_names = set(re.findall(r"\]\$(\w+)", param_block.group(1)))
        assert ps1_param_names, "updater_helper.ps1: no parameters parsed"

        native_powershell_flags = {"-ExecutionPolicy", "-File"}
        flags_used = [a for a in args
                      if isinstance(a, str) and a.startswith("-")
                      and a not in native_powershell_flags]
        assert flags_used, "no -Flags found in Popen args — test setup drifted"
        for flag in flags_used:
            name = flag.lstrip("-")
            assert name in ps1_param_names, (
                f"garmin_app_base.py passes {flag!r} to updater_helper.ps1, "
                f"but its param() block has no matching parameter "
                f"(known: {sorted(ps1_param_names)})")

    def test_show_update_popup_offers_update_button_for_t2(
            self, qtbot, monkeypatch, tmp_path):
        """v1.7.2.4-Nacherweiterung — das Popup-Gate zeigt den dritten
        Button jetzt auch für T2 (is_t2_standard() True), nicht mehr nur
        für T3. QMessageBox.exec() wird übersprungen (kein Blocking-
        Dialog im Test), stattdessen wird direkt geprüft, wie viele
        AcceptRole-Buttons _show_update_popup() vor dem exec() angelegt
        hat."""
        from unittest.mock import MagicMock, patch

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t2(monkeypatch, tmp_path)

        with patch("garmin_app_base.QMessageBox") as mock_msgbox_cls:
            mock_dlg = MagicMock()
            mock_msgbox_cls.return_value = mock_dlg
            mock_msgbox_cls.ButtonRole.AcceptRole = "accept"
            mock_msgbox_cls.ButtonRole.RejectRole = "reject"
            added_labels = []
            mock_dlg.addButton.side_effect = (
                lambda label, role: added_labels.append(label))
            mock_dlg.clickedButton.return_value = None

            app._show_update_popup("v9.9.9", "v9.9.9", {"assets": []})

            assert "Update" in added_labels

    def test_show_update_popup_click_reaches_start_update(self, qtbot, monkeypatch, tmp_path):
        """Echter Klick-Test (B3, Testsuite-Rework 2026-09-25): schließt die
        Lücke, dass der Popup-Klick-Pfad und _start_update()s Internals bisher
        nie im selben Test zusammenkamen (der einzige Popup-Test mockt bislang
        die ganze QMessageBox, der Klick passiert nie wirklich). Nutzt einen
        echten QMessageBox.exec()-Aufruf, klickt via qtbot während der Dialog
        modal blockiert (QTimer.singleShot + activeModalWidget(), da exec()
        den aufrufenden Thread bis zum Klick blockiert), und lässt die Kette
        bis zum weiterhin gemockten Popen-Aufruf real durchlaufen."""
        from unittest.mock import MagicMock
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from PyQt6.QtCore import QTimer, Qt

        class _ImmediateThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
            def start(self):
                self._target()
        monkeypatch.setattr("garmin_app_base.threading.Thread", _ImmediateThread)

        app = self._make_test_app(qtbot)
        self._simulate_frozen_t3(monkeypatch, tmp_path)

        monkeypatch.setattr(
            "garmin_app_base.updater.prepare_update",
            lambda exe_dir, zip_url, checksum_url: tmp_path)
        monkeypatch.setattr(
            "garmin_app_base.process_status.is_mcp_running", lambda: False)
        monkeypatch.setattr(
            "garmin_app_base.process_status.get_pid", lambda name: None)
        popen_calls = []
        monkeypatch.setattr(
            "garmin_app_base.subprocess.Popen",
            lambda args, **kw: popen_calls.append(args) or MagicMock())
        monkeypatch.setattr(app, "close", lambda: None)

        def _click_update_button():
            modal = QApplication.activeModalWidget()
            assert isinstance(modal, QMessageBox), \
                f"kein modales QMessageBox aktiv (bekam {modal!r})"
            buttons = {b.text(): b for b in modal.buttons()}
            assert "Update" in buttons, \
                f"kein 'Update'-Button im Popup, vorhanden: {list(buttons)}"
            qtbot.mouseClick(buttons["Update"], Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, _click_update_button)
        app._show_update_popup("v9.9.9", "v9.9.9", self._release_json())

        assert len(popen_calls) == 1, (
            "Klick auf 'Update' hat nicht zu einem Popen-Aufruf geführt — "
            "die Verdrahtung zwischen Button und _start_update() ist unterbrochen")


# ══════════════════════════════════════════════════════════════════════════════
#  RESTING-HR-REPAIR v1.7.5.7 — removable
#  Popup of the resting-HR repair (panel_archive) and its trigger in sync.py
# ══════════════════════════════════════════════════════════════════════════════

class TestRestingHrRepairHooks:

    @staticmethod
    def _archive(base, with_source=True, extra_no_source=0):
        """A synthetic archive: one day in the unrepaired import form (+ optional extras)."""
        import json
        raw_dir = base / "garmin_data" / "raw"
        src_dir = base / "garmin_data" / "source"
        raw_dir.mkdir(parents=True)
        src_dir.mkdir(parents=True)

        def raw(d):
            return {"date": d, "user_summary": {"restingHeartRate": 60},
                    "heart_rates": {"restingHeartRate": 60, "minHeartRate": 45, "maxHeartRate": 150}}

        days = ["2025-07-10"] + [f"2025-07-2{n}" for n in range(extra_no_source)]
        for d in days:
            (raw_dir / f"garmin_raw_{d}.json").write_text(json.dumps(raw(d)), encoding="utf-8")
        if with_source:
            (src_dir / "garmin_source_2025-07-10.json").write_text("{}", encoding="utf-8")

    @staticmethod
    def _check(base):
        from unittest.mock import MagicMock
        from app.panel_archive import PanelArchive
        return PanelArchive._check_resting_hr_repair(MagicMock(), str(base))

    def test_no_raw_folder_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_no_correctable_day_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, with_source=False)          # the only import-form day has no original
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_confirmed_returns_true_and_names_the_count_and_the_backup(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes) as q:
            assert self._check(tmp_path) is True
        text = q.call_args.args[2]
        assert "1 day(s)" in text and "backup" in text.lower()
        assert "no archived original" not in text

    def test_declined_returns_false(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            assert self._check(tmp_path) is False

    def test_days_without_original_are_named(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, extra_no_source=2)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as q:
            self._check(tmp_path)
        assert "2 more day(s) have no archived original" in q.call_args.args[2]

    def test_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        with patch("garmin_repair_resting_hr.find_candidates", side_effect=RuntimeError("boom")), \
                patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    @pytest.mark.parametrize("migrate, repair, expected", [
        (True,  True,  {"GARMIN_SCHEMA_MIGRATE": "1", "GARMIN_RESTING_HR_REPAIR": "1"}),
        (False, True,  {"GARMIN_RESTING_HR_REPAIR": "1"}),
        (True,  False, {"GARMIN_SCHEMA_MIGRATE": "1"}),
        (False, False, {}),
    ])
    def test_sync_passes_the_trigger_only_after_a_yes(self, tmp_path, migrate, repair, expected):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = migrate
        app._panel_archive._check_resting_hr_repair.return_value = repair
        app._panel_archive._check_device_repair.return_value = False          # v1.7.6.9: not asked / declined
        app._panel_archive._check_prediction_repair.return_value = False      # v1.7.6.10: not asked / declined
        app._panel_archive._check_prediction_catchup.return_value = False      # v1.7.6.11.2: not asked / declined
        app._panel_archive._check_track_migration.return_value = None      # v1.7.6.3: not asked / declined
        app._panel_archive._check_bulk_rebuild.return_value = None         # v1.7.6.5: not asked / declined
        _sync.run_collector(panel)
        app._panel_archive._check_resting_hr_repair.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected


# ══════════════════════════════════════════════════════════════════════════════
#  TRACK-MIGRATION v1.7.6.3 — removable
#  Popup of the track migration (panel_archive) and its trigger in sync.py
# ══════════════════════════════════════════════════════════════════════════════

class TestTrackMigrationHooks:

    @staticmethod
    def _archive(base, ready=1, waiting=0, others=0):
        """A synthetic archive: `ready` days in the old import form with a source/ file and an aggregates file,
        `waiting` of them without the aggregates file, `others` plain API days."""
        import json
        gd = base / "garmin_data"
        for sub in ("raw", "source", "bulk/aggregates"):
            (gd / sub).mkdir(parents=True)

        def raw(d):
            return {"date": d, "user_summary": {"restingHeartRate": 60},
                    "heart_rates": {"restingHeartRate": 60, "minHeartRate": 45, "maxHeartRate": 150}}

        days = [f"2025-07-{n:02d}" for n in range(1, ready + waiting + 1)]
        for i, d in enumerate(days):
            (gd / "raw" / f"garmin_raw_{d}.json").write_text(json.dumps(raw(d)), encoding="utf-8")
            (gd / "source" / f"garmin_source_{d}.json").write_text("{}", encoding="utf-8")
            if i < ready:
                (gd / "bulk" / "aggregates" / f"garmin_bulk_agg_{d}.json").write_text("{}", encoding="utf-8")
        for n in range(others):
            d = f"2025-08-{n + 1:02d}"
            (gd / "raw" / f"garmin_raw_{d}.json").write_text(json.dumps({"date": d, "body_battery": [{"value": 1}]}), encoding="utf-8")

    @staticmethod
    def _check(base, answer="run"):
        """Runs the check with the three-button question replaced. Returns (result, the mock)."""
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        with patch("app.panel_archive._ask_track_migration", return_value=answer) as ask:
            return PanelArchive._check_track_migration(MagicMock(), str(base)), ask

    def test_no_raw_folder_asks_nothing(self, tmp_path):
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    def test_nothing_to_migrate_asks_nothing(self, tmp_path):
        self._archive(tmp_path, ready=0, others=3)
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    def test_days_that_wait_for_the_export_import_ask_nothing(self, tmp_path):
        self._archive(tmp_path, ready=0, waiting=2)
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    @pytest.mark.parametrize("answer, expected", [("run", "1"), ("preview", "preview"), ("", None)])
    def test_the_answer_becomes_the_value_of_the_trigger(self, tmp_path, answer, expected):
        self._archive(tmp_path)
        result, ask = self._check(tmp_path, answer)
        assert result == expected
        ask.assert_called_once()

    def test_the_question_names_the_count_the_safety_copy_and_the_backup(self, tmp_path):
        self._archive(tmp_path, ready=3)
        _, ask = self._check(tmp_path)
        text = ask.call_args.args[1]
        assert "3 day(s)" in text and "safety copy" in text.lower() and "backup" in text.lower()
        assert "wait for the export import" not in text

    def test_days_that_wait_are_named(self, tmp_path):
        self._archive(tmp_path, ready=1, waiting=2)
        _, ask = self._check(tmp_path)
        text = ask.call_args.args[1]
        assert "1 day(s)" in text and "2 more day(s) wait for the export import" in text

    def test_the_folders_come_from_the_given_base_dir(self, tmp_path):
        # the scan must not read the folders garmin_config was imported with
        from unittest.mock import patch
        import garmin_track_migration as tm
        self._archive(tmp_path)
        with patch.object(tm, "scan_archive", wraps=tm.scan_archive) as scan:
            self._check(tmp_path)
        kw = scan.call_args.kwargs
        gd = tmp_path / "garmin_data"
        assert (kw["raw_dir"], kw["source_dir"], kw["agg_dir"]) == (gd / "raw", gd / "source", gd / "bulk" / "aggregates")

    def test_an_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        self._archive(tmp_path)
        with patch("garmin_track_migration.scan_archive", side_effect=RuntimeError("boom")):
            result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    # ── the three-button question ─────────────────────────────────────────────
    @pytest.mark.parametrize("label, expected", [("Migrate", "run"), ("Preview only", "preview"), ("Not now", "")])
    def test_the_question_returns_what_was_clicked(self, qtbot, label, expected):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.panel_archive import _ask_track_migration
        seen = {}

        def click(box):
            seen["labels"] = [b.text() for b in box.buttons()]
            seen["text"] = box.text()
            next(b for b in box.buttons() if b.text() == label).click()
            return 0

        with patch.object(QMessageBox, "exec", click):          # a plain function: it is bound, gets the box
            assert _ask_track_migration(None, "some text") == expected
        assert sorted(seen["labels"]) == ["Migrate", "Not now", "Preview only"] and seen["text"] == "some text"   # the order is the platform's

    def test_closing_the_question_means_not_now(self, qtbot):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.panel_archive import _ask_track_migration
        with patch.object(QMessageBox, "exec", return_value=0):          # closed without a click
            assert _ask_track_migration(None, "t") == ""

    # ── the trigger in sync.py ────────────────────────────────────────────────
    @staticmethod
    def _sync(tmp_path, track, repair=False, migrate=False):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = migrate
        app._panel_archive._check_resting_hr_repair.return_value = repair
        app._panel_archive._check_device_repair.return_value = False          # v1.7.6.9: not asked / declined
        app._panel_archive._check_prediction_repair.return_value = False      # v1.7.6.10: not asked / declined
        app._panel_archive._check_prediction_catchup.return_value = False      # v1.7.6.11.2: not asked / declined
        app._panel_archive._check_track_migration.return_value = track
        app._panel_archive._check_bulk_rebuild.return_value = None         # v1.7.6.5: not asked / declined
        _sync.run_collector(panel)
        return panel, app

    @pytest.mark.parametrize("track, migrate, repair, expected", [
        ("1",       False, False, {"GARMIN_TRACK_MIGRATION": "1"}),
        ("preview", False, False, {"GARMIN_TRACK_MIGRATION": "preview"}),
        (None,      False, False, {}),
        ("1",       True,  True,  {"GARMIN_SCHEMA_MIGRATE": "1", "GARMIN_RESTING_HR_REPAIR": "1", "GARMIN_TRACK_MIGRATION": "1"}),
    ])
    def test_sync_passes_the_trigger_only_after_an_answer(self, tmp_path, track, migrate, repair, expected):
        _, app = self._sync(tmp_path, track, repair=repair, migrate=migrate)
        app._panel_archive._check_track_migration.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected

    @pytest.mark.parametrize("track, live_fetch", [(None, True), ("1", True), ("preview", False)])
    def test_a_preview_does_not_start_the_live_fetch(self, tmp_path, track, live_fetch):
        # a preview run ends before the login: the live fetch after the sync would log in on its own
        from unittest.mock import patch
        from app.outputs import sync as _sync
        panel, app = self._sync(tmp_path, track)
        with patch.object(_sync, "run_live_fetch") as live:
            app._run.call_args.kwargs["on_done"]()
        assert live.called is live_fetch
        app._panel_timer._timer_resume_after_sync.assert_called_once()
        app._panel_archive._refresh_archive_info.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
#  BULK-REBUILD v1.7.6.5 — removable
#  Popup of the rebuild of the daily values (panel_archive) and its trigger in sync.py
# ══════════════════════════════════════════════════════════════════════════════

class TestBulkRebuildHooks:
    HASH = "ab" + "c" * 62                                          # a SHA-256 name; the folder is its first two characters

    @classmethod
    def _store(cls, base, old=2, current=0, original=True):
        """A synthetic bulk store: `old` days with the schema number before the current one, `current` days
        with the current number, and (if `original`) one JSON original in bulk/source."""
        import json
        import garmin_bulk_writer as bw
        bulk = base / "garmin_data" / "bulk"
        (bulk / "aggregates").mkdir(parents=True)
        (bulk / "source").mkdir(parents=True)
        for i in range(old + current):
            version = bw.AGG_SCHEMA_VERSION - 1 if i < old else bw.AGG_SCHEMA_VERSION
            (bulk / "aggregates" / f"garmin_bulk_agg_2025-07-{i + 1:02d}.json").write_text(
                json.dumps({"date": f"2025-07-{i + 1:02d}", "schema_version": version}), encoding="utf-8")
        if original:
            (bulk / "source" / cls.HASH[:2]).mkdir()
            (bulk / "source" / cls.HASH[:2] / f"{cls.HASH}.json").write_text("[]", encoding="utf-8")
        return bulk

    @staticmethod
    def _check(base, answer="run"):
        """Runs the check with the three-button question replaced. Returns (result, the mock)."""
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        with patch("app.panel_archive._ask_bulk_rebuild", return_value=answer) as ask:
            return PanelArchive._check_bulk_rebuild(MagicMock(), str(base)), ask

    def test_no_bulk_folders_asks_nothing(self, tmp_path):
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    def test_days_with_the_current_number_ask_nothing(self, tmp_path):
        self._store(tmp_path, old=0, current=3)
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    def test_without_an_original_to_rebuild_from_nothing_is_asked(self, tmp_path):
        self._store(tmp_path, old=2, original=False)
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    def test_a_file_in_the_originals_folder_that_is_no_original_does_not_count(self, tmp_path):
        bulk = self._store(tmp_path, old=2, original=False)
        (bulk / "source" / "ab").mkdir()
        (bulk / "source" / "ab" / "notahash.json").write_text("[]", encoding="utf-8")
        (bulk / "source" / "ab" / f"{'c' * 64}.json").write_text("[]", encoding="utf-8")          # in the wrong folder
        (bulk / "source" / "ab" / f"{self.HASH}.json.tmp").write_text("[]", encoding="utf-8")
        result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    @pytest.mark.parametrize("answer, expected", [("run", "1"), ("preview", "preview"), ("", None)])
    def test_the_answer_becomes_the_value_of_the_trigger(self, tmp_path, answer, expected):
        self._store(tmp_path)
        result, ask = self._check(tmp_path, answer)
        assert result == expected
        ask.assert_called_once()

    def test_the_question_names_the_count_and_what_is_and_is_not_done(self, tmp_path):
        self._store(tmp_path, old=3, current=2)
        _, ask = self._check(tmp_path)
        text = ask.call_args.args[1]
        assert text.startswith("3 day(s)")
        assert "no export is needed" in text and "No safety copy is made" in text and "Preview only" in text

    def test_damaged_files_and_invalid_numbers_are_not_counted(self, tmp_path):
        import json
        bulk = self._store(tmp_path, old=1)
        agg = bulk / "aggregates"
        (agg / "garmin_bulk_agg_2025-08-01.json").write_text("{ not json", encoding="utf-8")
        (agg / "garmin_bulk_agg_2025-08-02.json").write_text(json.dumps({"schema_version": "1"}), encoding="utf-8")
        (agg / "garmin_bulk_agg_2025-08-03.json").write_text(json.dumps({"schema_version": True}), encoding="utf-8")
        (agg / "garmin_bulk_agg_2025-08-04.json").write_text(json.dumps([1, 2]), encoding="utf-8")
        (agg / "garmin_bulk_agg_2025-08-05.json").write_text(json.dumps({"date": "x"}), encoding="utf-8")
        _, ask = self._check(tmp_path)
        assert ask.call_args.args[1].startswith("1 day(s)")

    def test_the_folders_come_from_the_given_base_dir(self, tmp_path):
        # the scan must not read the folders garmin_config was imported with
        from unittest.mock import patch
        import garmin_config as cfg
        self._store(tmp_path)
        with patch.object(cfg, "BULK_AGG_DIR", tmp_path / "elsewhere"), patch.object(cfg, "BULK_SOURCE_DIR", tmp_path / "elsewhere"):
            result, ask = self._check(tmp_path)
        assert result == "1"
        ask.assert_called_once()

    def test_an_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from pathlib import Path
        self._store(tmp_path)
        with patch.object(Path, "iterdir", side_effect=OSError("boom")):
            result, ask = self._check(tmp_path)
        assert result is None
        ask.assert_not_called()

    # ── the three-button question ─────────────────────────────────────────────
    @pytest.mark.parametrize("label, expected", [("Rebuild", "run"), ("Preview only", "preview"), ("Not now", "")])
    def test_the_question_returns_what_was_clicked(self, qtbot, label, expected):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.panel_archive import _ask_bulk_rebuild
        seen = {}

        def click(box):
            seen["labels"] = [b.text() for b in box.buttons()]
            seen["text"] = box.text()
            next(b for b in box.buttons() if b.text() == label).click()
            return 0

        with patch.object(QMessageBox, "exec", click):          # a plain function: it is bound, gets the box
            assert _ask_bulk_rebuild(None, "some text") == expected
        assert sorted(seen["labels"]) == ["Not now", "Preview only", "Rebuild"] and seen["text"] == "some text"

    def test_closing_the_question_means_not_now(self, qtbot):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        from app.panel_archive import _ask_bulk_rebuild
        with patch.object(QMessageBox, "exec", return_value=0):          # closed without a click
            assert _ask_bulk_rebuild(None, "t") == ""

    # ── the trigger in sync.py ────────────────────────────────────────────────
    @staticmethod
    def _sync(tmp_path, rebuild, track=None, repair=False, migrate=False):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = migrate
        app._panel_archive._check_resting_hr_repair.return_value = repair
        app._panel_archive._check_device_repair.return_value = False          # v1.7.6.9: not asked / declined
        app._panel_archive._check_prediction_repair.return_value = False      # v1.7.6.10: not asked / declined
        app._panel_archive._check_prediction_catchup.return_value = False      # v1.7.6.11.2: not asked / declined
        app._panel_archive._check_track_migration.return_value = track
        app._panel_archive._check_bulk_rebuild.return_value = rebuild
        _sync.run_collector(panel)
        return panel, app

    @pytest.mark.parametrize("rebuild, track, migrate, repair, expected", [
        ("1",       None, False, False, {"GARMIN_BULK_REBUILD": "1"}),
        ("preview", None, False, False, {"GARMIN_BULK_REBUILD": "preview"}),
        (None,      None, False, False, {}),
        ("1",       "1",  True,  True,  {"GARMIN_SCHEMA_MIGRATE": "1", "GARMIN_RESTING_HR_REPAIR": "1",
                                         "GARMIN_TRACK_MIGRATION": "1", "GARMIN_BULK_REBUILD": "1"}),
    ])
    def test_sync_passes_the_trigger_only_after_an_answer(self, tmp_path, rebuild, track, migrate, repair, expected):
        _, app = self._sync(tmp_path, rebuild, track=track, repair=repair, migrate=migrate)
        app._panel_archive._check_bulk_rebuild.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected

    def test_after_the_preview_of_the_track_migration_the_rebuild_is_not_asked(self, tmp_path):
        # that run ends before the sync: a second question would lead nowhere
        _, app = self._sync(tmp_path, "1", track="preview")
        app._panel_archive._check_bulk_rebuild.assert_not_called()
        assert app._run.call_args.kwargs["env_overrides"] == {"GARMIN_TRACK_MIGRATION": "preview"}

    @pytest.mark.parametrize("rebuild, track, live_fetch", [
        (None, None, True), ("1", None, True), ("preview", None, False), (None, "preview", False)])
    def test_a_preview_does_not_start_the_live_fetch(self, tmp_path, rebuild, track, live_fetch):
        # a preview run ends before the login: the live fetch after the sync would log in on its own
        from unittest.mock import patch
        from app.outputs import sync as _sync
        panel, app = self._sync(tmp_path, rebuild, track=track)
        with patch.object(_sync, "run_live_fetch") as live:
            app._run.call_args.kwargs["on_done"]()
        assert live.called is live_fetch
        app._panel_timer._timer_resume_after_sync.assert_called_once()
        app._panel_archive._refresh_archive_info.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
#  Import Bulk Export — options dialog, preview, confirmation, trigger variables (v1.7.6, 6b)
# ══════════════════════════════════════════════════════════════════════════════

class TestBulkImportFlow:
    OPTIONS = {"json": True, "intraday": True, "preview": False}

    @staticmethod
    def _panel(timer_active=False):
        from unittest.mock import MagicMock
        panel = MagicMock()
        panel._app._timer_active = timer_active
        return panel

    @staticmethod
    def _go(panel, options, confirm=True, zip_file=True, path="C:/export.zip"):
        """Runs the button with the dialogs replaced. Returns (question mock, information mock)."""
        from unittest.mock import patch
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from app.outputs import bulk_import
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        answers = [yes if zip_file else no, yes if confirm else no]
        with patch.object(QMessageBox, "question", side_effect=answers) as q, \
                patch.object(QMessageBox, "information") as info, \
                patch.object(QFileDialog, "getOpenFileName", return_value=(path, "")), \
                patch.object(QFileDialog, "getExistingDirectory", return_value=path), \
                patch.object(bulk_import, "_ask_options", return_value=options):
            bulk_import.run_import(panel)
        return q, info

    # ── the variables ─────────────────────────────────────────────────────────
    @pytest.mark.parametrize("json_on, intraday_on, dry, expected", [
        (True, False, False, {"GARMIN_BULK_PHASES": "json"}),
        (False, True, False, {"GARMIN_BULK_PHASES": "intraday"}),
        (True, True, False, {"GARMIN_BULK_PHASES": "json,intraday"}),
        (False, True, True, {"GARMIN_BULK_PHASES": "intraday", "GARMIN_BULK_DRYRUN": "1"}),
        (True, True, True, {"GARMIN_BULK_PHASES": "json,intraday", "GARMIN_BULK_DRYRUN": "1"}),
    ])
    def test_build_env(self, json_on, intraday_on, dry, expected):
        from pathlib import Path
        from app.outputs import bulk_import
        env = bulk_import.build_env(Path("C:/export.zip"), json_on, intraday_on, dry)
        assert env == {"GARMIN_IMPORT_PATH": str(Path("C:/export.zip")), **expected}

    def test_the_variables_to_remove_are_the_three_triggers(self):
        from app.outputs import bulk_import
        assert set(bulk_import.TRIGGER_VARS) == {"GARMIN_IMPORT_PATH", "GARMIN_BULK_PHASES", "GARMIN_BULK_DRYRUN"}

    # ── the button ────────────────────────────────────────────────────────────
    def test_both_phases_after_a_yes(self):
        panel = self._panel()
        q, _ = self._go(panel, self.OPTIONS)
        app = panel._app
        assert app._run.call_count == 1
        assert app._run.call_args.args == ("garmin_collector.py",)
        assert app._run.call_args.kwargs["enable_stop"] is True
        assert app._run.call_args.kwargs["env_overrides"] == {
            "GARMIN_IMPORT_PATH": "C:/export.zip", "GARMIN_BULK_PHASES": "json,intraday"}
        assert q.call_count == 2                       # the selection and the confirmation

    def test_the_confirmation_names_the_new_folder_and_the_missing_protection(self):
        q, _ = self._go(self._panel(), self.OPTIONS)
        text = q.call_args_list[1].args[2]
        assert "garmin_data/bulk" in text and "backup" in text.lower() and "mirror" in text.lower() and "fallback" in text.lower()

    def test_a_no_to_the_confirmation_starts_nothing_and_pauses_nothing(self):
        panel = self._panel(timer_active=True)
        self._go(panel, self.OPTIONS, confirm=False)
        app = panel._app
        app._run.assert_not_called()
        app._timer_stop.set.assert_not_called()
        assert app._timer_active is True

    def test_json_only_is_confirmed_too(self):
        # v1.7.6.1: the daily values go to garmin_data/bulk as well, so the same confirmation applies
        panel = self._panel()
        q, _ = self._go(panel, {"json": True, "intraday": False, "preview": False})
        assert q.call_count == 2
        assert panel._app._run.call_args.kwargs["env_overrides"]["GARMIN_BULK_PHASES"] == "json"

    def test_intraday_only_is_confirmed_too(self):
        panel = self._panel()
        q, _ = self._go(panel, {"json": False, "intraday": True, "preview": False})
        assert q.call_count == 2
        assert panel._app._run.call_args.kwargs["env_overrides"]["GARMIN_BULK_PHASES"] == "intraday"

    def test_preview_runs_with_the_dry_run_variable_and_pauses_nothing(self):
        panel = self._panel(timer_active=True)
        q, _ = self._go(panel, {"json": True, "intraday": True, "preview": True})
        app = panel._app
        assert q.call_count == 1                       # only the selection
        env = app._run.call_args.kwargs["env_overrides"]
        assert env["GARMIN_BULK_DRYRUN"] == "1" and env["GARMIN_BULK_PHASES"] == "json,intraday"
        app._timer_stop.set.assert_not_called()
        assert app._timer_active is True
        assert any("nothing is written" in str(c.args[0]) for c in app._log.call_args_list)

    def test_preview_of_the_daily_values_alone_starts_a_preview(self):
        # v1.7.6.1: the daily values have a preview now, no explanation that there is none
        panel = self._panel(timer_active=True)
        q, info = self._go(panel, {"json": True, "intraday": False, "preview": True})
        app = panel._app
        assert q.call_count == 1 and info.call_count == 0
        env = app._run.call_args.kwargs["env_overrides"]
        assert env["GARMIN_BULK_PHASES"] == "json" and env["GARMIN_BULK_DRYRUN"] == "1"
        app._timer_stop.set.assert_not_called()
        assert app._timer_active is True

    def test_nothing_selected_explains_and_starts_nothing(self):
        panel = self._panel()
        _, info = self._go(panel, {"json": False, "intraday": False, "preview": False})
        panel._app._run.assert_not_called()
        assert info.call_count == 1

    def test_cancel_in_the_options_starts_nothing(self):
        panel = self._panel(timer_active=True)
        q, _ = self._go(panel, None)
        panel._app._run.assert_not_called()
        panel._app._timer_stop.set.assert_not_called()
        assert q.call_count == 1

    def test_no_path_chosen_starts_nothing(self):
        panel = self._panel()
        self._go(panel, self.OPTIONS, path="")
        panel._app._run.assert_not_called()

    def test_the_timer_is_paused_for_the_real_import(self):
        panel = self._panel(timer_active=True)
        self._go(panel, self.OPTIONS)
        app = panel._app
        app._timer_stop.set.assert_called_once()
        assert app._timer_active is False

    def test_the_folder_choice_is_still_offered(self):
        panel = self._panel()
        self._go(panel, self.OPTIONS, zip_file=False, path="C:/export_folder")
        assert panel._app._run.call_args.kwargs["env_overrides"]["GARMIN_IMPORT_PATH"] == "C:/export_folder"

    # ── after the run ─────────────────────────────────────────────────────────
    def test_on_done_removes_all_three_variables_and_resumes_the_timer(self):
        import os
        from unittest.mock import patch
        panel = self._panel(timer_active=True)
        self._go(panel, self.OPTIONS)
        app = panel._app
        on_done = app._run.call_args.kwargs["on_done"]
        with patch.dict(os.environ, {"GARMIN_IMPORT_PATH": "x", "GARMIN_BULK_PHASES": "json", "GARMIN_BULK_DRYRUN": "1"}):
            on_done()
            assert not any(k in os.environ for k in ("GARMIN_IMPORT_PATH", "GARMIN_BULK_PHASES", "GARMIN_BULK_DRYRUN"))
        app._panel_timer._timer_resume_after_sync.assert_called_once_with(True)
        app._panel_archive._refresh_archive_info.assert_called_once()

    def test_on_done_of_a_preview_resumes_nothing(self):
        panel = self._panel(timer_active=True)
        self._go(panel, {"json": False, "intraday": True, "preview": True})
        app = panel._app
        app._run.call_args.kwargs["on_done"]()
        app._panel_timer._timer_resume_after_sync.assert_called_once_with(False)

    # ── the dialog ────────────────────────────────────────────────────────────
    def test_dialog_offers_both_phases_checked_and_three_buttons(self, qtbot):
        from app.outputs.bulk_import import ImportOptionsDialog
        dlg = ImportOptionsDialog()
        qtbot.addWidget(dlg)
        assert dlg.json_box.isChecked() and dlg.intraday_box.isChecked()
        assert dlg.preview_btn.text() == "Preview" and dlg.import_btn.text() == "Import" and dlg.cancel_btn.text() == "Cancel"
        assert dlg.options() is None                   # nothing chosen yet

    def test_dialog_import_returns_the_checkboxes(self, qtbot):
        from app.outputs.bulk_import import ImportOptionsDialog
        dlg = ImportOptionsDialog()
        qtbot.addWidget(dlg)
        dlg.json_box.setChecked(False)
        dlg.import_btn.click()
        assert dlg.options() == {"json": False, "intraday": True, "preview": False}

    def test_dialog_preview_returns_the_preview_flag(self, qtbot):
        from app.outputs.bulk_import import ImportOptionsDialog
        dlg = ImportOptionsDialog()
        qtbot.addWidget(dlg)
        dlg.preview_btn.click()
        assert dlg.options() == {"json": True, "intraday": True, "preview": True}

    def test_dialog_cancel_returns_none(self, qtbot):
        from app.outputs.bulk_import import ImportOptionsDialog
        dlg = ImportOptionsDialog()
        qtbot.addWidget(dlg)
        dlg.cancel_btn.click()
        assert dlg.options() is None


# ══════════════════════════════════════════════════════════════════════════════
#  Documentation button — PanelHome._home_docs_dialog (v1.7.6.4, Bausteine B1 und B3)
# ══════════════════════════════════════════════════════════════════════════════

class TestHomeDocsDialog:
    """The Documentation button (PanelHome._home_docs_dialog). A chooser dialog with three entries;
    since v1.7.6.4 (B3) each opens in the viewer of the app (DocViewerDialog), and only if the file
    cannot be read or the viewer fails does it go to the default program (os.startfile) as before.
    B1 pinned the startfile behaviour first; the pins on the chooser, "file not found" and the
    error message stayed, the "opens with startfile" pins were turned. The method is called unbound
    with a QWidget as `_app` (it only needs the theme colours); QDialog.exec is replaced by a
    stand-in that "clicks" the wanted button."""

    FILES = [("Quickstart", "QUICKSTART.txt", "Quickstart", False),
             ("User Guide", "USER_GUIDE.txt", "User Guide", False),
             ("README App", "README_APP.md", "README App", True)]

    def _run(self, qtbot, click=None, doc_path=Path("C:/docs/the_file"), startfile_error=None,
             viewer="mock", viewer_error=None):
        """viewer "mock": DocViewerDialog replaced by a MagicMock (viewer_error: raised by the call);
        viewer "real": the real class, only the chooser is faked."""
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QDialog, QPushButton, QWidget
        import app.panel_home as ph

        parent = QWidget()
        for name, value in dict(BG="#12101f", BG3="#231f38", ACCENT="#a259f7", ACCENT2="#6e3fcf",
                                TEXT="#eaeaea", TEXT2="#a0a0b0").items():
            setattr(parent, name, value)
        qtbot.addWidget(parent)
        seen = {}

        class _Dlg(QDialog):
            def exec(self):
                seen["title"] = self.windowTitle()
                seen["modal"] = self.isModal()
                seen["fixed_width"] = (self.minimumWidth(), self.maximumWidth())
                buttons = self.findChildren(QPushButton)
                seen["buttons"] = [b.text() for b in buttons]
                if click is not None:
                    next(b for b in buttons if click in b.text()).click()
                seen["result"] = self.result()
                return self.result()

        doc_path_mock = MagicMock(return_value=doc_path)
        startfile_mock = MagicMock(side_effect=startfile_error)
        viewer_mock = MagicMock(side_effect=viewer_error)
        box = MagicMock()
        log_rec = MagicMock()
        patches = [patch.object(ph, "QDialog", _Dlg), patch.object(ph.frozen_paths, "doc_path", doc_path_mock),
                   patch.object(ph.os, "startfile", startfile_mock, create=True),
                   patch.object(ph, "QMessageBox", box), patch.object(ph, "log", log_rec)]
        if viewer == "mock":
            patches.append(patch.object(ph, "DocViewerDialog", viewer_mock))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            ph.PanelHome._home_docs_dialog(SimpleNamespace(_app=parent))
        return SimpleNamespace(seen=seen, doc_path=doc_path_mock, startfile=startfile_mock, box=box,
                               app=parent, viewer=viewer_mock, log=log_rec)

    @staticmethod
    def _doc(tmp_path, name, text="Hello\n", raw=None):
        path = tmp_path / name
        path.write_bytes(raw if raw is not None else text.encode("utf-8"))
        return path

    # ── the chooser (unchanged by the viewer) ─────────────────────────────────

    def test_dialog_lists_three_documents_and_cancel(self, qtbot):
        r = self._run(qtbot)
        assert r.seen["title"] == "Documentation"
        assert r.seen["buttons"] == ["\U0001F4CB  Quickstart", "\U0001F4D6  User Guide",
                                     "\U0001F4C4  README App", "Cancel"]

    def test_dialog_is_modal_and_has_a_fixed_width(self, qtbot):
        r = self._run(qtbot)
        assert r.seen["modal"] is True
        assert r.seen["fixed_width"] == (360, 360)

    def test_nothing_is_opened_until_a_button_is_clicked(self, qtbot):
        r = self._run(qtbot)
        assert r.doc_path.call_count == 0
        assert r.startfile.call_count == 0 and r.viewer.call_count == 0

    @pytest.mark.parametrize("label,filename,title,markdown", FILES)
    def test_click_closes_the_chooser_before_opening(self, qtbot, tmp_path, label, filename, title, markdown):
        from PyQt6.QtWidgets import QDialog
        r = self._run(qtbot, click=label, doc_path=self._doc(tmp_path, filename))
        assert r.seen["result"] == QDialog.DialogCode.Accepted

    def test_cancel_opens_nothing(self, qtbot):
        from PyQt6.QtWidgets import QDialog
        r = self._run(qtbot, click="Cancel")
        assert r.seen["result"] == QDialog.DialogCode.Rejected
        assert r.doc_path.call_count == 0 and r.startfile.call_count == 0 and r.viewer.call_count == 0

    # ── the viewer (B3) ───────────────────────────────────────────────────────

    @pytest.mark.parametrize("label,filename,title,markdown", FILES)
    def test_click_shows_the_file_in_the_viewer_not_in_another_program(self, qtbot, tmp_path, label, filename,
                                                                      title, markdown):
        path = self._doc(tmp_path, filename, text="Gr\u00fc\u00dfe \u2014 \u2550\u2550\u2550 line\n")
        r = self._run(qtbot, click=label, doc_path=path)
        r.doc_path.assert_called_once_with(filename)
        r.viewer.assert_called_once_with(r.app, title, "Gr\u00fc\u00dfe \u2014 \u2550\u2550\u2550 line\n",
                                         markdown=markdown)
        r.viewer.return_value.show.assert_called_once_with()
        assert r.startfile.call_count == 0
        assert r.box.warning.call_count == 0 and r.box.critical.call_count == 0
        assert r.log.warning.call_count == 0

    def test_only_the_md_file_is_rendered_as_markdown(self, qtbot, tmp_path):
        flags = {}
        for label, filename, _title, _md in self.FILES:
            r = self._run(qtbot, click=label, doc_path=self._doc(tmp_path, filename))
            flags[filename] = r.viewer.call_args.kwargs["markdown"]
        assert flags == {"QUICKSTART.txt": False, "USER_GUIDE.txt": False, "README_APP.md": True}

    def test_bytes_that_are_not_utf8_are_replaced_and_the_viewer_still_opens(self, qtbot, tmp_path):
        r = self._run(qtbot, click="User Guide", doc_path=self._doc(tmp_path, "USER_GUIDE.txt", raw=b"ab\xffcd\n"))
        assert r.viewer.call_args.args[2] == "ab\ufffdcd\n"
        assert r.startfile.call_count == 0

    # ── the fallback and the error messages ───────────────────────────────────

    def test_missing_file_warns_with_its_name_and_opens_nothing(self, qtbot):
        r = self._run(qtbot, click="User Guide", doc_path=None)
        r.box.warning.assert_called_once_with(r.app, "Documentation", "File not found: USER_GUIDE.txt")
        assert r.startfile.call_count == 0 and r.viewer.call_count == 0 and r.box.critical.call_count == 0

    def test_an_unreadable_file_goes_to_the_default_program(self, qtbot, tmp_path):
        path = tmp_path / "QUICKSTART.txt"                      # does not exist: reading fails
        r = self._run(qtbot, click="Quickstart", doc_path=path)
        assert r.viewer.call_count == 0
        r.startfile.assert_called_once_with(path)
        assert r.box.critical.call_count == 0 and r.box.warning.call_count == 0

    def test_a_failing_viewer_goes_to_the_default_program_and_is_logged(self, qtbot, tmp_path):
        path = self._doc(tmp_path, "README_APP.md")
        r = self._run(qtbot, click="README App", doc_path=path, viewer_error=RuntimeError("no viewer"))
        r.startfile.assert_called_once_with(path)
        assert r.log.warning.call_count == 1
        message = r.log.warning.call_args.args[0]
        assert "README_APP.md" in message and "RuntimeError: no viewer" in message
        assert r.box.critical.call_count == 0

    def test_a_viewer_that_was_shown_is_not_opened_a_second_time_by_the_fallback(self, qtbot, tmp_path):
        r = self._run(qtbot, click="User Guide", doc_path=self._doc(tmp_path, "USER_GUIDE.txt"))
        assert r.viewer.call_count == 1 and r.startfile.call_count == 0

    def test_startfile_error_after_a_failed_viewer_is_shown_not_raised(self, qtbot, tmp_path):
        r = self._run(qtbot, click="README App", doc_path=self._doc(tmp_path, "README_APP.md"),
                      viewer_error=RuntimeError("no viewer"), startfile_error=OSError("no program"))
        r.box.critical.assert_called_once_with(r.app, "Documentation", "Could not open file:\nno program")
        assert r.box.warning.call_count == 0

    def test_startfile_error_after_an_unreadable_file_is_shown_not_raised(self, qtbot, tmp_path):
        r = self._run(qtbot, click="Quickstart", doc_path=tmp_path / "QUICKSTART.txt",
                      startfile_error=OSError("no program"))
        r.box.critical.assert_called_once_with(r.app, "Documentation", "Could not open file:\nno program")

    # ── end to end with the real viewer and the real files ───────────────────

    @pytest.mark.parametrize("label,filename,title,markdown", FILES)
    def test_real_viewer_opens_the_real_document(self, qtbot, label, filename, title, markdown):
        import frozen_paths
        from app.dialog_docs import DocViewerDialog
        r = self._run(qtbot, click=label, doc_path=frozen_paths.doc_path(filename), viewer="real")
        viewers = r.app.findChildren(DocViewerDialog)
        try:
            assert len(viewers) == 1
            v = viewers[0]
            assert v.windowTitle() == title and v.isVisible() and v.isModal() is False
            assert v.parent() is r.app
            expected = frozen_paths.doc_path(filename).read_text(encoding="utf-8")
            if markdown:
                assert v._view.toHtml().count("<table") >= 6
            else:
                assert v._view.toPlainText() == expected
            assert r.startfile.call_count == 0
        finally:
            for v in viewers:
                v.close()

    def test_the_three_files_are_found_by_the_real_doc_path_in_the_dev_tree(self):
        import frozen_paths
        for _label, filename, _title, _md in self.FILES:
            found = frozen_paths.doc_path(filename)
            assert found is not None and found.name == filename and found.is_file()

# ══════════════════════════════════════════════════════════════════════════════
#  Documentation viewer — app/dialog_docs.py (v1.7.6.4, Baustein B2)
# ══════════════════════════════════════════════════════════════════════════════

class TestDocViewerDialog:

    MD = ("# Title\n\nSome **bold** text and a [site](https://example.org/x).\n\n"
          "| a | b |\n|---|---|\n| 1 | 2 |\n\n```\npip install thing\n```\n")

    def _parent(self, qtbot):
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        for name, value in dict(BG="#12101f", BG3="#231f38", ACCENT="#a259f7", ACCENT2="#6e3fcf",
                                TEXT="#eaeaea", TEXT2="#a0a0b0").items():
            setattr(parent, name, value)
        qtbot.addWidget(parent)
        self._keep = getattr(self, "_keep", []) + [parent]     # a parent that is collected takes its children with it
        return parent

    def _dlg(self, qtbot, text="plain", markdown=False, title="Doc"):
        from app.dialog_docs import DocViewerDialog
        parent = self._parent(qtbot)
        dlg = DocViewerDialog(parent, title, text, markdown=markdown)
        qtbot.addWidget(dlg)
        return dlg

    def test_window_is_titled_not_modal_and_deleted_on_close(self, qtbot):
        from PyQt6.QtCore import Qt
        dlg = self._dlg(qtbot, title="User Guide")
        assert dlg.windowTitle() == "User Guide"
        assert dlg.isModal() is False
        assert dlg.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def test_view_is_read_only_and_follows_no_link_by_itself(self, qtbot):
        dlg = self._dlg(qtbot)
        assert dlg._view.isReadOnly()
        assert dlg._view.openLinks() is False
        assert dlg._view.openExternalLinks() is False

    def test_plain_text_is_shown_as_it_is_in_a_monospace_font(self, qtbot):
        from PyQt6.QtGui import QFont
        text = "═══════\n  Title\n═══════\n\n  1. Setup\n# not a heading\n| not | a table |\n"
        dlg = self._dlg(qtbot, text=text, markdown=False)
        assert dlg._view.toPlainText() == text
        assert dlg._view.font().family() == "Consolas"
        assert dlg._view.font().styleHint() == QFont.StyleHint.Monospace

    def test_markdown_is_rendered_heading_table_and_code_stay(self, qtbot):
        dlg = self._dlg(qtbot, text=self.MD, markdown=True)
        html = dlg._view.toHtml()
        plain = dlg._view.toPlainText()
        assert html.count("<table") == 1
        assert "<h1" in html
        assert "# Title" not in plain and "|---|" not in plain and "**bold**" not in plain
        assert "pip install thing" in plain and "Some bold text" in plain

    def test_markdown_off_keeps_the_markup_literal(self, qtbot):
        dlg = self._dlg(qtbot, text=self.MD, markdown=False)
        assert "# Title" in dlg._view.toPlainText() and "<table" not in dlg._view.toHtml()

    def test_empty_text_is_fine(self, qtbot):
        assert self._dlg(qtbot, text="", markdown=False)._view.toPlainText() == ""
        assert self._dlg(qtbot, text="", markdown=True)._view.toPlainText() == ""

    @pytest.mark.parametrize("url", ["http://example.org/a", "https://example.org/a#b", "HTTPS://example.org/"])
    def test_http_and_https_links_open_in_the_default_browser(self, qtbot, url):
        from unittest.mock import patch
        from PyQt6.QtCore import QUrl
        dlg = self._dlg(qtbot)
        with patch("app.dialog_docs.QDesktopServices.openUrl") as opened:
            dlg._on_link(QUrl(url))
        assert opened.call_count == 1 and opened.call_args.args[0].toString() == QUrl(url).toString()

    @pytest.mark.parametrize("url", ["file:///C:/Windows/notepad.exe", "javascript:alert(1)", "mailto:a@b.c",
                                     "ftp://example.org/x", "ms-settings:network", "README_APP.md", "../x.txt", "javascript:#top", "README_APP.md#setup"])
    def test_every_other_link_is_ignored(self, qtbot, url):
        from unittest.mock import patch
        from PyQt6.QtCore import QUrl
        dlg = self._dlg(qtbot)
        with patch("app.dialog_docs.QDesktopServices.openUrl") as opened, \
                patch.object(dlg._view, "scrollToAnchor") as scrolled:
            dlg._on_link(QUrl(url))
        assert opened.call_count == 0 and scrolled.call_count == 0

    def test_an_anchor_link_scrolls_inside_the_page(self, qtbot):
        from unittest.mock import patch
        from PyQt6.QtCore import QUrl
        dlg = self._dlg(qtbot)
        with patch("app.dialog_docs.QDesktopServices.openUrl") as opened, \
                patch.object(dlg._view, "scrollToAnchor") as scrolled:
            dlg._on_link(QUrl("#first-time-setup"))
        scrolled.assert_called_once_with("first-time-setup")
        assert opened.call_count == 0

    def test_the_colours_of_the_app_are_used(self, qtbot):
        from PyQt6.QtGui import QPalette
        dlg = self._dlg(qtbot)
        assert "#12101f" in dlg.styleSheet() and "#eaeaea" in dlg.styleSheet()
        assert "#12101f" in dlg._view.styleSheet() and "#eaeaea" in dlg._view.styleSheet()
        assert dlg._view.palette().color(QPalette.ColorRole.Link).name() == "#a259f7"

    def test_close_button_closes_the_window(self, qtbot):
        dlg = self._dlg(qtbot)
        dlg.show()
        assert dlg.isVisible()
        dlg._close_btn.click()
        assert not dlg.isVisible()

    def test_the_module_imports_nothing_but_pyqt6(self, app_root):
        import ast
        tree = ast.parse((app_root / "app" / "dialog_docs.py").read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots.add((node.module or "").split(".")[0])
        assert roots == {"PyQt6"}

    def test_the_three_real_documents_render(self, qtbot):
        import frozen_paths
        quick = frozen_paths.doc_path("QUICKSTART.txt").read_text(encoding="utf-8")
        guide = frozen_paths.doc_path("USER_GUIDE.txt").read_text(encoding="utf-8")
        readme = frozen_paths.doc_path("README_APP.md").read_text(encoding="utf-8")
        d_quick = self._dlg(qtbot, text=quick, markdown=False)
        d_guide = self._dlg(qtbot, text=guide, markdown=False)
        d_readme = self._dlg(qtbot, text=readme, markdown=True)
        assert d_quick._view.toPlainText() == quick
        assert d_guide._view.toPlainText() == guide and d_guide._view.document().blockCount() > 1000
        assert d_readme._view.toHtml().count("<table") >= 6
        assert "pip install garminconnect" in d_readme._view.toPlainText()


# ══════════════════════════════════════════════════════════════════════════════
#  DEVICE-REPAIR v1.7.6.9 — removable
#  Popup of the device repair (panel_archive), its trigger in sync.py, naming by id
# ══════════════════════════════════════════════════════════════════════════════

class TestDeviceRepairHooks:

    @staticmethod
    def _archive(base, serials=(3966586101,), extra_unknown=0):
        """A synthetic archive: one entry per serial without a device_id, each with a bulk day file and a FIT
        original; extra_unknown entries have no bulk day file."""
        import hashlib
        import json
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import fit_builder as fb
        g = base / "garmin_data"
        (g / "log").mkdir(parents=True)
        entries = []
        for i, serial in enumerate(serials, 1):
            d = f"2025-06-{i:02d}"
            hashes = []
            for j, one in enumerate(serial if isinstance(serial, tuple) else (serial,)):     # a tuple = several devices on the day
                data = fb.simple_fit(32, 1_700_000_000 + 10 * i + j, serial=one)
                h = hashlib.sha256(data).hexdigest()
                (g / "bulk" / "source" / h[:2]).mkdir(parents=True, exist_ok=True)
                (g / "bulk" / "source" / h[:2] / f"{h}.fit").write_bytes(data)
                hashes.append(h)
            (g / "bulk" / "raw").mkdir(parents=True, exist_ok=True)
            (g / "bulk" / "raw" / f"garmin_bulk_{d}.json").write_text(
                json.dumps({"date": d, "schema_version": 1, "source_files": hashes}), encoding="utf-8")
            entries.append({"date": d, "device_id": None, "device_name": ""})
        for n in range(extra_unknown):
            entries.append({"date": f"2025-07-{n + 1:02d}", "device_id": None, "device_name": ""})
        (g / "log" / "quality_log.json").write_text(json.dumps({"days": entries}), encoding="utf-8")

    @staticmethod
    def _check(base):
        from unittest.mock import MagicMock
        from app.panel_archive import PanelArchive
        return PanelArchive._check_device_repair(MagicMock(), str(base))

    def test_no_log_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_no_assignable_day_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, serials=(), extra_unknown=2)       # only days without a bulk day file
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_a_day_with_two_devices_alone_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, serials=((3966586101, 3961663084),))
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_a_day_with_two_devices_is_named_as_staying_unknown(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, serials=(3966586101, (3966586101, 3961663084)))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as q:
            self._check(tmp_path)
        text = q.call_args.args[2]
        assert text.startswith("1 day(s) have no device") and "1 more day(s)" in text and "3966586101: 1 day(s)" in text

    def test_confirmed_returns_true_and_names_count_devices_and_backup(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, serials=(3966586101, 3966586101, 3961663084))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as q:
            assert self._check(tmp_path) is True
        text = q.call_args.args[2]
        assert "3 day(s)" in text and "3966586101: 2 day(s)" in text and "3961663084: 1 day(s)" in text
        assert "backup" in text.lower() and "quality_log_" in text
        assert "stay unknown" not in text

    def test_declined_returns_false(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            assert self._check(tmp_path) is False

    def test_days_that_stay_unknown_are_named(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, extra_unknown=2)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as q:
            self._check(tmp_path)
        assert "2 more day(s)" in q.call_args.args[2] and "stay unknown" in q.call_args.args[2]

    def test_the_check_writes_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self._check(tmp_path)
        assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before

    def test_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path)
        with patch("garmin_repair_devices.find_candidates", side_effect=RuntimeError("boom")), \
                patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    @pytest.mark.parametrize("repair, expected", [(True, {"GARMIN_DEVICE_REPAIR": "1"}), (False, {})])
    def test_sync_passes_the_trigger_only_after_a_yes(self, tmp_path, repair, expected):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = False
        app._panel_archive._check_resting_hr_repair.return_value = False
        app._panel_archive._check_device_repair.return_value = repair
        app._panel_archive._check_prediction_repair.return_value = False
        app._panel_archive._check_prediction_catchup.return_value = False      # v1.7.6.11.2: not asked / declined
        app._panel_archive._check_track_migration.return_value = None
        app._panel_archive._check_bulk_rebuild.return_value = None
        _sync.run_collector(panel)
        app._panel_archive._check_device_repair.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected


# ══════════════════════════════════════════════════════════════════════════════
#  PREDICTION-REPAIR v1.7.6.10 — removable
#  Popup of the prediction repair (panel_archive) and its trigger in sync.py
# ══════════════════════════════════════════════════════════════════════════════

class TestPredictionRepairHooks:

    @staticmethod
    def _archive(base, days):
        """days: {date: race_predictions dict or None}; written as raw days of a synthetic archive."""
        import json
        raw = base / "garmin_data" / "raw"
        raw.mkdir(parents=True)
        for d, field in days.items():
            day = {"date": d, **({"race_predictions": field} if field is not None else {})}
            (raw / f"garmin_raw_{d}.json").write_text(json.dumps(day), encoding="utf-8")

    @staticmethod
    def _check(base):
        from unittest.mock import MagicMock
        from app.panel_archive import PanelArchive
        return PanelArchive._check_prediction_repair(MagicMock(), str(base))

    @staticmethod
    def _pred(cd, t=1500):
        return {"calendarDate": cd, "time5K": t, "time10K": 2 * t + 5, "timeHalfMarathon": 4 * t + 9, "timeMarathon": 9 * t + 1}

    def test_no_raw_folder_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_nothing_to_correct_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None})
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_days_that_cannot_be_settled_alone_ask_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        # a copy of a day that has no raw file yet, and a field without a date
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-09"), "2025-06-02": {"time5K": 1500}})
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_confirmed_returns_true_and_names_both_numbers_and_the_safety_copy(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-03"), "2025-06-02": self._pred("2025-06-03"),
                                 "2025-06-03": None, "2025-06-04": self._pred("2025-06-08", 1700)})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as q:
            assert self._check(tmp_path) is True
        text = q.call_args.args[2]
        assert "1 day(s) get the prediction that carries their own date" in text
        assert "2 day(s) lose a copy" in text
        assert "backup" in text.lower() and "source/" in text and "more day(s)" in text      # 06-04 waits

    def test_declined_returns_false(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-02"), "2025-06-02": None})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            assert self._check(tmp_path) is False

    def test_the_check_writes_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-02"), "2025-06-02": None})
        before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self._check(tmp_path)
        assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before

    def test_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-02"), "2025-06-02": None})
        with patch("garmin_repair_predictions.find_candidates", side_effect=RuntimeError("boom")), \
                patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    @pytest.mark.parametrize("repair, expected", [(True, {"GARMIN_PREDICTION_REPAIR": "1"}), (False, {})])
    def test_sync_passes_the_trigger_only_after_a_yes(self, tmp_path, repair, expected):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = False
        app._panel_archive._check_resting_hr_repair.return_value = False
        app._panel_archive._check_device_repair.return_value = False
        app._panel_archive._check_prediction_repair.return_value = repair
        app._panel_archive._check_prediction_catchup.return_value = False      # v1.7.6.11.2: not asked / declined
        app._panel_archive._check_track_migration.return_value = None
        app._panel_archive._check_bulk_rebuild.return_value = None
        _sync.run_collector(panel)
        app._panel_archive._check_prediction_repair.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected


# ══════════════════════════════════════════════════════════════════════════════
#  PREDICTION-CATCHUP v1.7.6.11.2 — removable
#  Popup of the prediction catch-up (panel_archive) and its trigger in sync.py
# ══════════════════════════════════════════════════════════════════════════════

class TestPredictionCatchupHooks:

    @staticmethod
    def _archive(base, days, attempts=None):
        """days: {date: race_predictions dict or None}; written as raw days plus a quality log of a synthetic archive."""
        import json
        garmin = base / "garmin_data"
        raw = garmin / "raw"
        raw.mkdir(parents=True)
        (garmin / "log").mkdir(parents=True)
        for d, field in days.items():
            day = {"date": d, **({"race_predictions": field} if field is not None else {})}
            (raw / f"garmin_raw_{d}.json").write_text(json.dumps(day), encoding="utf-8")
        entries = [{"date": d, "quality": "standard", "source": "api", "write": True,
                    **({"field_backfill_attempts": {"race_predictions": attempts[d]}} if attempts and d in attempts else {})}
                   for d in days]
        (garmin / "log" / "quality_log.json").write_text(json.dumps({"days": entries}), encoding="utf-8")

    @staticmethod
    def _check(base):
        from unittest.mock import MagicMock
        from app.panel_archive import PanelArchive
        return PanelArchive._check_prediction_catchup(MagicMock(), str(base))

    @staticmethod
    def _pred(cd, t=1500):
        return {"calendarDate": cd, "time5K": t, "time10K": 2 * t + 5, "timeHalfMarathon": 4 * t + 9, "timeMarathon": 9 * t + 1}

    def test_no_raw_folder_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_nothing_missing_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": self._pred("2025-06-02")})
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_an_archive_without_any_prediction_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": None, "2025-06-02": None})
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_days_already_given_up_ask_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None}, attempts={"2025-06-02": 2})
        with patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    def test_confirmed_returns_true_and_names_the_number_the_calls_and_the_safety_copy(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None, "2025-06-03": None,
                                 "2024-01-05": None})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as q:
            assert self._check(tmp_path) is True
        text = q.call_args.args[2]
        assert "Up to 3 day(s)" in text and "at most 2 request(s)" in text
        assert "backup" in text.lower() and "never overwritten" in text and "login" in text

    def test_declined_returns_false(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None})
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            assert self._check(tmp_path) is False

    def test_the_check_writes_nothing_and_asks_garmin_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None})
        before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),                 patch("garmin_api.login") as login:
            self._check(tmp_path)
        assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
        login.assert_not_called()

    def test_error_in_the_scan_asks_nothing(self, tmp_path):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QMessageBox
        self._archive(tmp_path, {"2025-06-01": self._pred("2025-06-01"), "2025-06-02": None})
        with patch("garmin_catchup_predictions.find_candidates", side_effect=RuntimeError("boom")),                 patch.object(QMessageBox, "question") as q:
            assert self._check(tmp_path) is False
        q.assert_not_called()

    @pytest.mark.parametrize("catchup, expected", [(True, {"GARMIN_PREDICTION_CATCHUP": "1"}), (False, {})])
    def test_sync_passes_the_trigger_only_after_a_yes(self, tmp_path, catchup, expected):
        from unittest.mock import MagicMock
        from app.outputs import sync as _sync
        panel = MagicMock()
        app = panel._app
        app._timer_active = False
        app._connection_verified = True
        app.settings = {"backup_raw_backfill_asked": True}
        app._panel_settings._collect_settings.return_value = {
            "email": "a@b.c", "password": "x", "base_dir": str(tmp_path),
            "sync_mode": "recent", "sync_days": "90", "sync_from": "", "sync_to": ""}
        app._panel_archive._check_failed_days_popup.return_value = False
        app._panel_archive._check_schema_migration.return_value = False
        app._panel_archive._check_resting_hr_repair.return_value = False
        app._panel_archive._check_device_repair.return_value = False
        app._panel_archive._check_prediction_repair.return_value = False
        app._panel_archive._check_prediction_catchup.return_value = catchup
        app._panel_archive._check_track_migration.return_value = None
        app._panel_archive._check_bulk_rebuild.return_value = None
        _sync.run_collector(panel)
        app._panel_archive._check_prediction_catchup.assert_called_once_with(base_dir=str(tmp_path))
        assert app._run.call_args.kwargs["env_overrides"] == expected


class TestNamingById:
    """Doubleclick on a device row of the archive table (v1.7.6.9, DEVICE-REPAIR)."""

    @staticmethod
    def _click(device_id, text):
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        item = MagicMock()
        item.data.return_value = device_id
        item.text.return_value = text
        panel = MagicMock()
        panel._app._panel_home._info_device_table.item.return_value = item
        panel._app._panel_settings._collect_settings.return_value = {"base_dir": "x"}
        with patch("app.panel_archive.QInputDialog.getText", return_value=("Old", True)) as dlg, \
                patch("app.panel_archive._controller.rename_unknown_device", return_value={"updated": 5}) as ru, \
                patch("pathlib.Path.exists", return_value=True):
            PanelArchive._archive_on_device_name_click(panel, 0, 2)
        return dlg, ru, panel

    def test_numeric_id_goes_to_naming_by_id_not_to_the_unknown_group(self):
        dlg, ru, panel = self._click("3966586101", "3966586101")
        panel._archive_rename_device_by_id.assert_called_once_with("3966586101", "3966586101")
        assert not ru.called and not dlg.called

    def test_unknown_group_keeps_its_dialog_and_function(self):
        for device_id in (None, "__unknown__"):
            dlg, ru, panel = self._click(device_id, "unknown")
            assert dlg.called and ru.called and not panel._archive_rename_device_by_id.called

    def test_total_row_does_nothing(self):
        dlg, ru, panel = self._click("__total__", "Total")
        assert not dlg.called and not ru.called and not panel._archive_rename_device_by_id.called

    def test_rename_by_id_calls_the_controller_with_id_and_stripped_name(self):
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        panel = MagicMock()
        panel._app._panel_settings._collect_settings.return_value = {"base_dir": "x"}
        with patch("app.panel_archive.QInputDialog.getText", return_value=(" vivoactive 3 ", True)) as dlg, \
                patch("app.panel_archive._controller.rename_device", return_value={"updated": 3}) as rd, \
                patch("pathlib.Path.exists", return_value=True):
            PanelArchive._archive_rename_device_by_id(panel, "3966586101", "3966586101")
        assert rd.call_args.args[1:] == ("3966586101", "vivoactive 3")
        assert "3966586101" in dlg.call_args.args[2] and dlg.call_args.kwargs["text"] == ""
        panel._refresh_archive_info.assert_called_once()

    def test_the_dialog_starts_with_an_existing_name(self):
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        panel = MagicMock()
        with patch("app.panel_archive.QInputDialog.getText", return_value=("x", False)) as dlg:
            PanelArchive._archive_rename_device_by_id(panel, "1", "fenix 5x")
        assert dlg.call_args.kwargs["text"] == "fenix 5x"

    def test_cancel_or_empty_name_changes_nothing(self):
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        for answer in (("x", False), ("  ", True)):
            panel = MagicMock()
            with patch("app.panel_archive.QInputDialog.getText", return_value=answer), \
                    patch("app.panel_archive._controller.rename_device") as rd:
                PanelArchive._archive_rename_device_by_id(panel, "1", "1")
            assert not rd.called and not panel._refresh_archive_info.called

    def test_an_error_is_logged_and_the_table_is_not_refreshed(self):
        from unittest.mock import MagicMock, patch
        from app.panel_archive import PanelArchive
        panel = MagicMock()
        panel._app._panel_settings._collect_settings.return_value = {"base_dir": "x"}
        with patch("app.panel_archive.QInputDialog.getText", return_value=("N", True)), \
                patch("app.panel_archive._controller.rename_device", return_value={"updated": 0, "error": "boom"}), \
                patch("pathlib.Path.exists", return_value=True):
            PanelArchive._archive_rename_device_by_id(panel, "1", "x")
        assert "boom" in panel._app._log.call_args.args[0] and not panel._refresh_archive_info.called


# ══════════════════════════════════════════════════════════════════════════════
#  Export Scan window — EXPORT-SCAN v1.7.7 — removable
#  app/popups/_export_scan_model.py (what it shows, pure) and app/popups/export_scan.py (the window)
# ══════════════════════════════════════════════════════════════════════════════

_SCAN_SECRET = "secret.name@example.invalid"


def _scan_export_zip(tmp_path):
    """A small export: UDSFile (3 years), sleepData, a known family, an unknown JSON, a folder named after
    the account. Returns the path of the ZIP."""
    import json
    import zipfile
    uds = []
    for year in (2021, 2022, 2023):
        for day in range(1, 5):
            row = {"calendarDate": f"{year}-03-{day:02d}", "totalSteps": 0 if day == 4 else 1000 + day,
                   "stress": {} if day % 2 else {"avg": 20}}
            if year > 2021:
                row["restingHeartRate"] = 55
            uds.append(row)
    sleep = [{"calendarDate": f"2022-05-{d:02d}", "deepSleepSeconds": 3600 if d % 2 else None} for d in range(1, 7)]
    entries = {
        "DI_CONNECT/DI-Connect-Aggregator/UDSFile_a.json": json.dumps(uds),
        f"DI_CONNECT/DI-Connect-Wellness/{_SCAN_SECRET}_sleepData.json": json.dumps(sleep),
        "DI_CONNECT/DI-Connect-Metrics/MetricsMaxMetData_1.json": json.dumps([{"calendarDate": "2023-01-01", "vo2MaxValue": 50}]),
        "DI_CONNECT/DI-Connect-User/profile.json": json.dumps({"a": 1}),
        f"{_SCAN_SECRET}/notes.txt": "x",
    }
    path = tmp_path / "export_of_secret.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


class TestExportScanModel:
    """Pure functions: the tree, the tables and the chart page are built without a window."""

    @pytest.fixture
    def result(self, tmp_path):
        import garmin_export_scan as es
        return es.scan(_scan_export_zip(tmp_path))

    @pytest.fixture
    def model(self):
        from app.popups import _export_scan_model as m
        return m

    THEME = {"bg": "#101010", "bg2": "#181818", "bg3": "#202020", "text": "#f0f0f0", "text2": "#9a9ea3",
             "accent": "#c76a3f", "accent2": "#9c5330", "green": "#4ecca3", "yellow": "#f5c542", "red": "#e94560"}
    PLOTLY = "<script>/*plotly*/</script>"

    def test_status_wording_equals_the_scan_module(self, model):
        import garmin_export_scan as es
        assert model.STATUS_TEXT == es._STATUS_TEXT

    def test_tree_has_overview_groups_with_families_unknown_and_folders(self, model, result):
        nodes = model.build_tree(result)
        ids = [n["id"] for n in nodes]
        assert ids[0] == ("summary", "") and ids[-2:] == [("unknown", ""), ("folders", "")]
        assert ("group", "daily") in ids and ("group", "sleep_body") in ids and ("group", "training") in ids
        assert ("group", "activities") not in ids and ("group", "account") not in ids      # nothing of them in this export
        daily = next(n for n in nodes if n["id"] == ("group", "daily"))
        assert [c["id"] for c in daily["children"]] == [("family", "uds")]
        assert daily["children"][0]["status"] == "read" and "12 rows" in daily["children"][0]["text"]
        training = next(n for n in nodes if n["id"] == ("group", "training"))
        assert [c["status"] for c in training["children"]] == ["known"]
        assert "1 files" in nodes[-2]["text"]

    def test_family_table_shares_tooltips_and_zero_is_a_value(self, model, result):
        table = model.build_table(result, ("family", "uds"))
        assert table["headers"] == ["Field", "2021", "2022", "2023", "All years"]
        assert [c["text"] for c in table["rows"][0]] == ["Rows", "4", "4", "4", "12"]
        rows = {r[0]["text"]: r for r in table["rows"][1:]}
        steps = rows["totalSteps"]                     # 3 filled + 1 zero per year: a zero is a value
        assert [c["value"] for c in steps[1:]] == [100, 100, 100, 100]
        assert "filled 3, zero 1, empty 0, absent 0 of 4 rows" in steps[1]["tip"]
        hr = rows["restingHeartRate"]                  # only in 2022 and 2023
        assert [c["value"] for c in hr[1:]] == [0, 100, 100, 67]
        assert "absent 4 of 4 rows" in hr[1]["tip"] and hr[1]["text"] == "0 %"
        stress = rows["stress"]                        # {} in half of the rows: empty
        assert stress[1]["value"] == 0 and "empty 2" in stress[1]["tip"]
        assert table["rows"][0][1]["value"] is None    # the row counts are not coloured

    def test_group_table_lists_every_family_with_status_and_rows_per_year(self, model, result):
        table = model.build_table(result, ("group", "sleep_body"))
        assert table["headers"][:4] == ["Family", "Status", "Files", "Rows"] and table["headers"][4:] == ["2022"]
        by_label = {r[0]["text"]: [c["text"] for c in r] for r in table["rows"]}
        assert by_label["sleepData"] == ["sleepData", "read by GLA", "1", "6", "6"]
        zones = by_label["heartRateZones / powerZones"]  # a family of the group that this export does not hold
        assert zones[1:4] == ["kept by GLA, not read", "0", "0"]

    def test_unknown_folders_and_overview_tables(self, model, result):
        unknown = model.build_table(result, ("unknown", ""))
        assert [r[0]["text"] for r in unknown["rows"]] == ["DI_CONNECT/DI-Connect-User"]
        folders = model.build_table(result, ("folders", ""))
        assert "<hidden>" in [r[0]["text"] for r in folders["rows"]]
        overview = model.build_table(result, ("summary", ""))
        assert dict((r[0]["text"], r[1]["text"]) for r in overview["rows"])["JSON files"] == "4"
        assert model.build_table(result, ("nothing", "")) == overview            # any other node: the overview
        assert "stopped" in model.build_table({**result, "stopped": True}, ("summary", ""))["note"]

    def test_which_nodes_have_a_chart(self, model, result):
        assert model.has_chart(result, ("family", "uds")) and model.has_chart(result, ("group", "daily"))
        assert not any(model.has_chart(result, n) for n in
                       (("summary", ""), ("unknown", ""), ("folders", ""), ("family", "gear"), ("family", "nope"),
                        ("group", "account"), ("group", "nope")))
        assert model.build_chart_html(result, ("folders", ""), self.PLOTLY, self.THEME) is None

    @staticmethod
    def _plot_args(html):
        import json
        import re
        m = re.search(r'Plotly\.newPlot\("chart", (.*), (\{"title".*\}), (\{"responsive".*\})\);</script>', html)
        assert m, "the Plotly call is not in the page"
        return json.loads(m.group(1)), json.loads(m.group(2)), json.loads(m.group(3))

    def test_family_chart_is_a_heat_map_of_the_same_shares(self, model, result):
        html = model.build_chart_html(result, ("family", "uds"), self.PLOTLY, self.THEME)
        data, layout, config = self._plot_args(html)
        assert html.count(self.PLOTLY) == 1 and "Content-Security-Policy" in html and "default-src 'none'" in html
        heat = data[0]
        assert heat["type"] == "heatmap" and heat["x"] == ["2021", "2022", "2023"]
        assert heat["z"][heat["y"].index("totalSteps")] == [100, 100, 100]
        assert heat["z"][heat["y"].index("restingHeartRate")] == [0, 100, 100]
        assert heat["colorscale"] == [[0, "#202020"], [1, "#c76a3f"]]            # the colours handed in
        assert layout["paper_bgcolor"] == "#101010" and layout["font"]["color"] == "#f0f0f0"
        assert config["scrollZoom"] is True and config["displaylogo"] is False

    def test_group_chart_is_bars_of_the_rows_per_year(self, model, result):
        data, layout, _config = self._plot_args(model.build_chart_html(result, ("group", "sleep_body"), self.PLOTLY, self.THEME))
        assert [t["type"] for t in data] == ["bar"] and data[0]["name"] == "sleepData"
        assert data[0]["x"] == ["2022"] and data[0]["y"] == [6] and layout["barmode"] == "group"

    def test_a_colour_that_is_no_hex_colour_is_replaced_by_neutral_grey_not_a_theme(self, model, result):
        html = model.build_chart_html(result, ("family", "uds"), self.PLOTLY,
                                      {"bg": "red; background:url(x)", "bg3": None, "text": "#12", "accent": "#zzzzzz"})
        assert "url(x)" not in html and "red;" not in html
        data, layout, _c = self._plot_args(html)
        assert data[0]["colorscale"] == [[0, "#3a3a3a"], [1, "#a0a0a0"]] and layout["paper_bgcolor"] == "#202020"
        assert model.build_chart_html(result, ("family", "uds"), self.PLOTLY, None) is not None

    def test_texts_of_the_export_cannot_break_out_of_the_page_or_become_markup(self, model, result):
        import copy
        evil = "</script><script>alert(1)</script>"
        link = '<a href="https://evil.example">x</a>'
        hacked = copy.deepcopy(result)
        fam = hacked["families"]["uds"]
        fam["fields"][evil] = fam["fields"].pop("totalSteps")
        fam["fields"][link] = fam["fields"].pop("restingHeartRate")
        fam["label"] = "UDS & <b>label</b>"
        html = model.build_chart_html(hacked, ("family", "uds"), self.PLOTLY, self.THEME)
        assert html.count("</script>") == 2                       # Plotly's and ours, nothing from the data
        call = html[html.index("Plotly.newPlot("):html.index(");</script>")]
        assert "<" not in call and ">" not in call and "&" not in call       # the embedded data is script-safe
        assert "alert(1)</script>" not in html and "<a href" not in html and "<b>" not in html
        data, layout, _c = self._plot_args(html)
        assert "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in data[0]["y"]
        assert "&lt;a href=\"https://evil.example\"&gt;x&lt;/a&gt;" in data[0]["y"]
        assert "UDS &amp; &lt;b&gt;label&lt;/b&gt;" in layout["title"]["text"]
        # the table of the window shows plain text, so the texts stay as they are there
        assert evil in [r[0]["text"] for r in model.build_table(hacked, ("family", "uds"))["rows"]]

    FIT = {"schema": 1, "stopped": False,
           "files": {"seen": 10, "read": 7, "duplicates": 1, "oversize": 0, "unreadable_entries": 0, "zips_opened": 3,
                     "zips_unreadable": 0, "too_deep": 0, "damaged": {"crc": 1, "not_fit": 1}},
           "types": {"4": {"files": 1, "years": {"2019": 1}},
                     "32": {"files": 4, "years": {"2019": 2, "2020": 1, "2026": 1}},
                     "41": {"files": 1, "years": {"unknown": 1}},
                     "none": {"files": 1, "years": {"2022": 1}}},
           "years": {"2019": 3, "2020": 1, "2022": 1, "2026": 1, "unknown": 1}}

    def test_fit_node_in_the_tree_with_its_types_before_the_unknown_files(self, model, result):
        import copy
        plain_ids = [n["id"] for n in model.build_tree(result)]
        assert ("fit", "") not in plain_ids                                         # no FIT scan: no node
        nodes = model.build_tree({**copy.deepcopy(result), "fit": self.FIT})
        ids = [n["id"] for n in nodes]
        assert ids[-3:] == [("fit", ""), ("unknown", ""), ("folders", "")]
        fit = nodes[-3]
        assert fit["text"] == "FIT files (7 files)" and fit["status"] is None
        assert [c["id"] for c in fit["children"]] == [("fit_type", k) for k in ("4", "32", "41", "none")]
        assert [c["text"] for c in fit["children"]] == [
            "Type 4 · activity  (1 files)", "Type 32 · all-day monitoring  (4 files)", "Type 41  (1 files)",
            "No type  (1 files)"]
        empty = {**result, "fit": {**self.FIT, "types": {}}}
        assert ("fit", "") not in [n["id"] for n in model.build_tree(empty)]          # nothing read: no node

    def test_fit_table_type_by_year_with_a_total_row_and_the_note(self, model, result):
        table = model.build_table({**result, "fit": self.FIT}, ("fit", ""))
        assert table["title"] == "FIT files"
        assert table["headers"] == ["Type", "Files", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
                                    "unknown"]                                   # no gaps: 2021, 2023 to 2025 are columns too
        rows = [[c["text"] for c in r] for r in table["rows"]]
        assert rows[1] == ["Type 32 · all-day monitoring", "4", "2", "1", "", "", "", "", "", "1", ""]
        assert rows[2] == ["Type 41", "1"] + [""] * 8 + ["1"]
        assert rows[-1] == ["All types", "7", "3", "1", "", "1", "", "", "", "1", "1"]
        assert "7 different files read (10 seen, 1 again with the same content, 2 damaged)" in table["note"]
        assert "working names" in table["note"] and "not Garmin terms" in table["note"]
        stopped = model.build_table({**result, "fit": {**self.FIT, "stopped": True}}, ("fit", ""))
        assert "stopped" in stopped["note"]
        assert model.build_table(result, ("fit", "")) == model.build_table(result, ("summary", ""))   # no FIT scan

    def test_fit_type_table_years_and_unknown_type(self, model, result):
        table = model.build_table({**result, "fit": self.FIT}, ("fit_type", "32"))
        assert table["title"] == "Type 32 · all-day monitoring" and table["headers"] == ["Year", "Files"]
        assert [[c["text"] for c in r] for r in table["rows"]] == [
            ["2019", "2"], ["2020", "1"], ["2021", "0"], ["2022", "0"], ["2023", "0"], ["2024", "0"], ["2025", "0"],
            ["2026", "1"]]
        assert model.build_table({**result, "fit": self.FIT}, ("fit_type", "999"))["rows"] == []
        assert model.build_table(result, ("fit_type", "32"))["rows"] == []

    def test_overview_shows_what_the_fit_scan_read_or_what_the_json_scan_only_counted(self, model, result):
        plain = dict((r[0]["text"], r[1]["text"]) for r in model.build_table(result, ("summary", ""))["rows"])
        assert "FIT files in the outer level (not read)" in plain and "Nested ZIPs (not opened)" in plain
        with_fit = dict((r[0]["text"], r[1]["text"]) for r in
                        model.build_table({**result, "fit": self.FIT}, ("summary", ""))["rows"])
        assert with_fit["FIT files seen"] == "10" and with_fit["  different files read"] == "7"
        assert with_fit["  again with the same content"] == "1" and with_fit["  damaged"] == "2"
        assert "FIT files in the outer level (not read)" not in with_fit

    def test_fit_charts_stacked_by_type_and_one_type(self, model, result):
        withfit = {**result, "fit": self.FIT}
        assert model.has_chart(withfit, ("fit", "")) and model.has_chart(withfit, ("fit_type", "4"))
        assert not model.has_chart(result, ("fit", "")) and not model.has_chart(withfit, ("fit_type", "999"))
        assert not model.has_chart({**result, "fit": {**self.FIT, "types": {}}}, ("fit", ""))
        data, layout, _c = self._plot_args(model.build_chart_html(withfit, ("fit", ""), self.PLOTLY, self.THEME))
        assert layout["barmode"] == "stack" and [t["name"] for t in data][:2] == ["Type 4 · activity", "Type 32 · all-day monitoring"]
        t32 = next(t for t in data if t["name"].startswith("Type 32"))
        assert t32["x"] == ["2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026", "unknown"]
        assert t32["y"] == [2, 1, 0, 0, 0, 0, 0, 1, 0]
        one, layout1, _c = self._plot_args(model.build_chart_html(withfit, ("fit_type", "32"), self.PLOTLY, self.THEME))
        assert one[0]["x"] == ["2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
        assert one[0]["y"] == [2, 1, 0, 0, 0, 0, 0, 1] and layout1["barmode"] == "group"
        assert "files per year" in layout1["title"]["text"]

    @staticmethod
    def _gap_result():
        """A family with rows in 2022 and 2024 only (the year 2023 has none), as the screenshot of the activities."""
        def counts(filled=0, zero=0, empty=0, absent=0):
            return {"filled": filled, "zero": zero, "empty": empty, "absent": absent}
        fam = {"label": "Gap", "group": "daily", "status": "read", "files": 1, "unreadable": 0, "too_large": 0,
               "rows": 3, "skipped_rows": 0, "truncated": False, "years": {"2022": 1, "2024": 2},
               "fields": {"a": {"2022": counts(filled=1), "2024": counts(filled=1, empty=1)}}}
        return {"families": {"gap": fam}, "groups": [{"key": "daily", "label": "Daily values", "families": ["gap"]}]}

    def test_year_range_fills_gaps_and_keeps_unknown_last(self, model):
        assert model._year_range([]) == [] and model._year_range(["unknown"]) == ["unknown"]
        assert model._year_range(["2024", "2020"]) == ["2020", "2021", "2022", "2023", "2024"]
        assert model._year_range(["unknown", "2019", "2021"]) == ["2019", "2020", "2021", "unknown"]
        assert model._year_range(iter(["2022"])) == ["2022"]

    def test_a_year_without_rows_is_a_column_with_a_dash_not_a_zero_percent(self, model):
        res = self._gap_result()
        table = model.build_table(res, ("family", "gap"))
        assert table["headers"] == ["Field", "2022", "2023", "2024", "All years"]
        assert [c["text"] for c in table["rows"][0]] == ["Rows", "1", "0", "2", "3"]
        cells = table["rows"][1]
        assert [c["text"] for c in cells] == ["a", "100 %", "–", "50 %", "67 %"]
        assert cells[2]["value"] is None and "no rows in this year" in cells[2]["tip"]
        group = model.build_table(res, ("group", "daily"))
        assert group["headers"][4:] == ["2022", "2023", "2024"] and [c["text"] for c in group["rows"][0]][4:] == ["1", "", "2"]

    def test_charts_show_the_year_without_rows_as_a_gap_or_a_zero_bar(self, model):
        res = self._gap_result()
        heat = self._plot_args(model.build_chart_html(res, ("family", "gap"), self.PLOTLY, self.THEME))[0][0]
        assert heat["x"] == ["2022", "2023", "2024"] and heat["z"] == [[100, None, 50]]
        assert "no rows in this year" in heat["text"][0][1]
        bars = self._plot_args(model.build_chart_html(res, ("group", "daily"), self.PLOTLY, self.THEME))[0][0]
        assert bars["x"] == ["2022", "2023", "2024"] and bars["y"] == [1, 0, 2]

    def test_series_colours_come_from_the_theme_first_then_from_the_hue_of_the_accent(self, model):
        import re
        t = self.THEME
        base = [t["accent"], t["green"], t["yellow"], t["red"], t["accent2"], t["text2"]]
        colours = model.series_colors(t, 20)
        assert colours[:6] == base and model.series_colors(t, 3) == base[:3] and model.series_colors(t, 0) == []
        assert len(colours) == 20 and len(set(colours)) == 20
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in colours) and not set(colours[6:]) & set(base)
        assert colours == model.series_colors(t, 20)                                  # the same every time
        other = dict(t, accent="#3f6ac7", green="#cc4e4e")
        assert model.series_colors(other, 8)[:2] == ["#3f6ac7", "#cc4e4e"] and model.series_colors(other, 8) != colours[:8]
        grey = model.series_colors({"accent": "nonsense"}, 8)
        assert grey[0] == "#a0a0a0" and len(set(grey)) == 8                           # a bad theme: neutral greys, still distinct

    def test_every_colour_of_the_page_comes_from_the_theme(self, model, result):
        import copy
        import re
        t = self.THEME
        withfit = {**copy.deepcopy(result), "fit": self.FIT}
        allowed = {v.lower() for v in t.values()} | {c.lower() for c in model.series_colors(t, 20)}
        for node in (("family", "uds"), ("group", "daily"), ("fit", ""), ("fit_type", "32")):
            html = model.build_chart_html(withfit, node, self.PLOTLY, t)
            found = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", html)}
            assert found and found <= allowed, (node, found - allowed)
        data, layout, _c = self._plot_args(model.build_chart_html(withfit, ("fit", ""), self.PLOTLY, t))
        assert [tr["marker"]["color"] for tr in data] == model.series_colors(t, len(data))
        assert layout["xaxis"]["gridcolor"] == t["bg3"] and layout["yaxis"]["tickfont"]["color"] == t["text"]
        assert layout["hoverlabel"] == {"bgcolor": t["bg2"], "bordercolor": t["accent"], "font": {"color": t["text"]}}
        assert layout["modebar"]["color"] == t["text2"] and layout["modebar"]["activecolor"] == t["accent"]
        assert layout["legend"]["font"]["color"] == t["text"] and layout["yaxis"]["title"]["font"]["color"] == t["text"]
        heat, hl, _c = self._plot_args(model.build_chart_html(result, ("family", "uds"), self.PLOTLY, t))
        assert heat[0]["colorbar"]["outlinecolor"] == t["bg3"] and heat[0]["colorbar"]["tickfont"]["color"] == t["text2"]

    @staticmethod
    def _detail(**kw):
        """A field detail as garmin_export_scan.scan_field returns it: Jan, Apr 2023 and Feb 2024 and rows without a date."""
        def m(rows, filled=0, zero=0, empty=0, absent=0):
            return {"rows": rows, "filled": filled, "zero": zero, "empty": empty, "absent": absent}
        detail = {"schema": 1, "source": "zip", "family": "uds", "label": "UDSFile", "field": "totalSteps", "stopped": False,
                  "files": 3, "unreadable": 0, "too_large": 0, "rows": 14,
                  "months": {"2023-01": m(4, filled=3, zero=1), "2023-04": m(6, filled=2, empty=3, absent=1),
                             "2024-02": m(2, absent=2), "unknown": m(2, filled=1, zero=1)},
                  "first": "2023-01", "last": "2023-04"}
        detail.update(kw)
        return detail

    def test_month_range_has_no_gaps_across_years_and_keeps_unknown_last(self, model):
        assert model._month_range([]) == [] and model._month_range(["unknown"]) == ["unknown"]
        assert model._month_range(["2023-11", "2024-02"]) == ["2023-11", "2023-12", "2024-01", "2024-02"]
        assert model._month_range(["2023-05"]) == ["2023-05"]
        assert model._month_range(["unknown", "2022-12", "2023-01"]) == ["2022-12", "2023-01", "unknown"]

    def test_field_table_by_month_with_empty_months_totals_and_the_note(self, model):
        table = model.build_field_table(self._detail(), "month")
        assert table["title"] == "UDSFile › totalSteps"
        assert table["headers"] == ["Month", "Rows", "Filled", "Zero", "Empty", "Absent", "With a value"]
        rows = [[c["text"] for c in r] for r in table["rows"]]
        assert [r[0] for r in rows][:5] == ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"]
        assert rows[0] == ["2023-01", "4", "3", "1", "0", "0", "100 %"]
        assert rows[1] == ["2023-02", "0", "0", "0", "0", "0", "–"]                      # a month without a row
        assert rows[3] == ["2023-04", "6", "2", "0", "3", "1", "33 %"]
        assert rows[-2][0] == "unknown" and rows[-1] == ["All", "14", "6", "2", "3", "3", "57 %"]
        assert table["rows"][1][6]["value"] is None and table["rows"][0][6]["value"] == 100
        assert "filled 3, zero 1, empty 0, absent 0 of 4 rows" in table["rows"][0][6]["tip"]
        assert "14 rows in 3 files, by state per month" in table["note"]
        assert "First month with a value: 2023-01, last: 2023-04." in table["note"]

    def test_field_table_by_year_adds_the_months_up(self, model):
        table = model.build_field_table(self._detail(), "year")
        assert table["headers"][0] == "Year" and "by state per year" in table["note"]
        rows = [[c["text"] for c in r] for r in table["rows"]]
        assert rows == [["2023", "10", "5", "1", "3", "1", "60 %"], ["2024", "2", "0", "0", "0", "2", "0 %"],
                        ["unknown", "2", "1", "1", "0", "0", "100 %"], ["All", "14", "6", "2", "3", "3", "57 %"]]

    def test_field_table_notes_for_a_stopped_read_damaged_files_and_no_value_at_all(self, model):
        table = model.build_field_table(self._detail(stopped=True, unreadable=2, too_large=1, first=None, last=None), "month")
        assert "stopped before the end" in table["note"] and "Unreadable files: 2, too large: 1." in table["note"]
        assert "No row has a value." in table["note"] and "First month" not in table["note"]
        plain = model.build_field_table(self._detail(), "month")["note"]
        assert "stopped" not in plain and "Unreadable" not in plain

    def test_field_chart_stacks_the_four_states_in_theme_colours_by_month_or_year(self, model):
        t = self.THEME
        data, layout, _c = self._plot_args(model.build_field_chart_html(self._detail(), "month", self.PLOTLY, t))
        assert [tr["name"] for tr in data] == ["filled", "zero", "empty", "absent"] and layout["barmode"] == "stack"
        assert [tr["marker"]["color"] for tr in data] == [t["green"], t["accent"], t["yellow"], t["text2"]]
        assert data[0]["x"][:5] == ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"] and data[0]["x"][-1] == "unknown"
        assert data[0]["y"][:4] == [3, 0, 0, 2] and data[2]["y"][3] == 3 and data[3]["y"][3] == 1
        assert "rows by state per month" in layout["title"]["text"]
        yd, ylayout, _c = self._plot_args(model.build_field_chart_html(self._detail(), "year", self.PLOTLY, t))
        assert yd[0]["x"] == ["2023", "2024", "unknown"] and yd[0]["y"] == [5, 0, 1] and "per year" in ylayout["title"]["text"]
        assert layout["xaxis"]["gridcolor"] == t["bg3"] and layout["hoverlabel"]["bgcolor"] == t["bg2"]

    def test_field_chart_only_with_rows_and_texts_stay_markup_free(self, model):
        assert not model.has_field_chart(None) and not model.has_field_chart(self._detail(rows=0))
        assert model.build_field_chart_html(self._detail(rows=0), "month", self.PLOTLY, self.THEME) is None
        evil = self._detail(field='</script><a href="https://evil.example">x</a>', label="L & <b>")
        html = model.build_field_chart_html(evil, "month", self.PLOTLY, self.THEME)
        assert html.count("</script>") == 2 and "<a href" not in html and "<b>" not in html
        call = html[html.index("Plotly.newPlot("):html.index(");</script>")]
        assert "<" not in call and ">" not in call and "&" not in call
        assert "L &amp; &lt;b&gt;" in self._plot_args(html)[1]["title"]["text"]
        assert evil["field"] in model.build_field_table(evil)["title"]                   # the table shows plain text

    def test_every_colour_of_the_field_page_comes_from_the_theme(self, model):
        import re
        t = self.THEME
        html = model.build_field_chart_html(self._detail(), "month", self.PLOTLY, t)
        found = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", html)}
        assert found and found <= {v.lower() for v in t.values()}

    @staticmethod
    def _values(**kw):
        """The values of a field as garmin_export_scan.read_values returns them (five dated numbers)."""
        values = {"schema": 1, "source": "zip", "family": "uds", "label": "UDSFile", "field": "totalSteps",
                  "supported": True, "stopped": False, "files": 2, "unreadable": 0, "too_large": 0, "rows": 9,
                  "numeric": 6, "other": 1, "missing": 2, "undated": 1, "thinned": False,
                  "stats": {"count": 5, "min": 0, "max": 1500.5, "mean": 840.15, "median": 1000, "zeros": 1},
                  "histogram": {"edges": [0, 750.25, 1500.5], "counts": [2, 3]},
                  "points": [["2023-01-05", 0], ["2023-01-06", 1000], ["2023-01-06", 1000], ["2023-02-01", 1500.5],
                             ["2023-03-01", 700.25]]}
        values.update(kw)
        return values

    @staticmethod
    def _glarender(js):
        import json
        import re
        m = re.fullmatch(r'glaRender\((\[.*\}\]), (\{"title".*\})\);', js, re.S)
        assert m, "not a glaRender call"
        return json.loads(m.group(1)), json.loads(m.group(2))

    def test_values_table_points_statistics_and_the_notes(self, model):
        table = model.build_values_table(self._values())
        assert table["title"] == "UDSFile › totalSteps  (values)" and table["headers"] == ["Date", "Value (steps)"]
        assert [[c["text"] for c in r] for r in table["rows"]] == [
            ["2023-01-05", "0"], ["2023-01-06", "1000"], ["2023-01-06", "1000"], ["2023-02-01", "1500.5"], ["2023-03-01", "700.25"]]
        note = table["note"]
        assert "5 values, min 0, max 1500.5, mean 840.15, median 1000, 1 zeros, 2023-01-05 to 2023-03-01." in note
        assert "6 of 9 rows hold a number; not a number: 1, empty or absent: 2." in note
        assert "Unit: steps (garmin_normalizer.py: totalSteps -> steps (the day's step count)). Raw values, not converted." in note
        assert "1 numbers without a readable date are not shown." in note
        plain = model.build_values_table(self._values(undated=0))["note"]
        assert "without a readable date" not in plain and "Thinned" not in plain and "stopped" not in plain and "Unreadable" not in plain
        more = model.build_values_table(self._values(thinned=True, stopped=True, unreadable=2, too_large=1))["note"]
        assert "Thinned to 5 points for the view; the statistics use all values." in more
        assert "stopped before the end" in more and "Unreadable files: 2, too large: 1." in more

    def test_the_unit_of_a_field_only_with_evidence_and_always_with_its_origin(self):
        from app.popups import _export_scan_units as units
        names = {"deepSleepSeconds": "s", "durationInMilliseconds": "ms", "vigorousIntensityMinutes": "min",
                 "totalDistanceMeters": "m", "floorsAscendedInMeters": "m", "totalKilocalories": "kcal",
                 "acwrPercent": "%", "heatAcclimationPercentage": "%"}
        for field, unit in names.items():
            found = units.unit_of("uds", field)
            assert found == {"unit": unit, "origin": "name", "source": found["source"]} and "the field name ends with" in found["source"], field
        assert units.unit_of("uds", "allDayStress.x.durationInMilliseconds")["unit"] == "ms"        # the last word of the path counts
        for field in ("userIntensityMinutesGoal", "secondsToSleep", "metersPerStep", "avgSpeed", "totalSteps2", "version",
                      "userProfilePK", "averageSpo2Value", "", None, 5,
                      "durationMillisecondsMax", "sleepSecondsGoal", "totalMetersGoal", "totalKilocaloriesGoal", "acwrPercentGoal",
                      "acwrPercentageGoal"):
            assert units.unit_of("uds", field) is None, field                # a word in the middle, nothing known: no unit
        assert units.unit_of("uds", "restingHeartRate") == {"unit": "bpm", "origin": "GLA code", "source": units.EXPLICIT[("uds", "restingHeartRate")][1]}
        assert {k: v[0] for k, v in units.EXPLICIT.items()} == {("uds", "restingHeartRate"): "bpm", ("uds", "currentDayRestingHeartRate"): "bpm",
                                                                 ("uds", "minHeartRate"): "bpm", ("uds", "maxHeartRate"): "bpm", ("uds", "totalSteps"): "steps",
                                                                 ("fit_monitoring", "heartRate"): "bpm"}
        assert units.unit_of("fit_monitoring", "heartRate")["origin"] == "GLA code" and units.unit_of("uds", "heartRate") is None
        assert units.unit_of("sleep", "restingHeartRate") is None and units.unit_of("uds", "totalSteps")["unit"] == "steps"
        assert all(len(v[1]) > 20 for v in units.EXPLICIT.values())                          # every entry names its evidence
        assert units.with_unit("Value", units.unit_of("uds", "totalSteps")) == "Value (steps)" and units.with_unit("Value", None) == "Value"
        assert units.NOT_DOCUMENTED == "unit not documented, raw value as Garmin writes it"

    def test_the_gla_code_evidence_of_the_unit_table_is_still_in_the_code(self, app_root):
        """EXPLICIT says which code treats a field as that unit. If the mapping goes, the entry is no longer evidence."""
        import re
        normalizer = (app_root / "garmin" / "garmin_normalizer.py").read_text(encoding="utf-8")
        importer = (app_root / "garmin" / "garmin_import.py").read_text(encoding="utf-8")
        assert re.search(r'"resting_bpm":\s+safe_get\(hr_raw, "restingHeartRate"\)', normalizer)
        assert re.search(r'"max_bpm":\s+safe_get\(hr_raw, "maxHeartRate"\)', normalizer)
        assert re.search(r'"min_bpm":\s+safe_get\(hr_raw, "minHeartRate"\)', normalizer)
        assert re.search(r'"steps":\s+safe_get\(us, "totalSteps"\)', normalizer)
        bulk = (app_root / "garmin" / "garmin_bulk_normalizer.py").read_text(encoding="utf-8")
        assert "_FIELD_HEART_RATE = 253, 26, 27" in bulk and "values [[ms UTC, bpm], ...] ascending" in bulk
        assert re.search(r'"restingHeartRate":\s+uds\.get\("currentDayRestingHeartRate"\)', importer)

    def test_a_field_without_a_unit_says_so_and_a_name_unit_shows_where_it_comes_from(self, model):
        none = model.build_values_table(self._values(field="avgSpeed"))
        assert none["headers"] == ["Date", "Value"] and "Unit: unit not documented, raw value as Garmin writes it." in none["note"]
        named = model.build_values_table(self._values(field="deepSleepSeconds"))
        assert named["headers"] == ["Date", "Value (s)"]
        assert "Unit: s (the field name ends with the word for seconds). Raw values, not converted." in named["note"]
        series = self._glarender(model.build_values_js(self._values(field="deepSleepSeconds"), "series", self.THEME))[1]
        dist = self._glarender(model.build_values_js(self._values(field="deepSleepSeconds"), "histogram", self.THEME))[1]
        assert series["yaxis"]["title"]["text"] == "deepSleepSeconds (s)" and dist["xaxis"]["title"]["text"] == "deepSleepSeconds (s)"
        plain = self._glarender(model.build_values_js(self._values(field="avgSpeed"), "series", self.THEME))[1]
        assert plain["yaxis"]["title"]["text"] == "avgSpeed"
        assert [c["text"] for c in named["rows"][1]] == ["2023-01-06", "1000"]               # the values themselves are not converted
        millis = model.build_values_table(self._values(field="durationInMilliseconds"))
        assert millis["headers"] == ["Date", "Value (ms)"] and [c["text"] for c in millis["rows"][1]] == ["2023-01-06", "1000"]

    def test_values_table_for_a_field_that_cannot_be_shown_or_has_no_numbers(self, model):
        bad = model.build_values_table(self._values(supported=False, stats=None, points=[]))
        assert bad["rows"] == [] and bad["headers"] == [] and "cannot be shown as values" in bad["note"]
        empty = model.build_values_table(self._values(stats=None, histogram=None, points=[]))
        assert empty["rows"] == [] and empty["note"].startswith("No number with a date in this field. 6 of 9 rows")
        assert [model._num(v) for v in (0, 12, 0.5, 0.1 + 0.2, 1234567.891, -3)] == ["0", "12", "0.5", "0.3", "1.23457e+06", "-3"]

    def test_the_values_page_holds_no_value_the_call_brings_them_in(self, model):
        import inspect
        page = model.build_values_page(self.PLOTLY, self.THEME)
        assert page.count(self.PLOTLY) == 1 and "default-src 'none'" in page and "function glaRender(data, layout)" in page
        assert 'Plotly.newPlot("chart", [],' in page and "Plotly.react" in page
        assert list(inspect.signature(model.build_values_page).parameters) == ["plotly_script", "theme"]   # it cannot get a value
        assert page == model.build_values_page(self.PLOTLY, self.THEME) and page.count("glaRender") == 1
        import re
        assert {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", page)} <= {v.lower() for v in self.THEME.values()}

    def test_the_values_call_over_time_and_as_a_distribution(self, model):
        t = self.THEME
        data, layout = self._glarender(model.build_values_js(self._values(), "series", t))
        assert data[0]["type"] == "scatter" and data[0]["mode"] == "lines+markers"
        assert data[0]["x"] == ["2023-01-05", "2023-01-06", "2023-01-06", "2023-02-01", "2023-03-01"]
        assert data[0]["y"] == [0, 1000, 1000, 1500.5, 700.25] and data[0]["marker"]["color"] == t["accent"]
        assert layout["title"]["text"] == "UDSFile › totalSteps: values over time" and layout["xaxis"]["type"] == "date"
        assert layout["yaxis"]["title"]["text"] == "totalSteps (steps)" and layout["paper_bgcolor"] == t["bg"]
        hdata, hlayout = self._glarender(model.build_values_js(self._values(), "histogram", t))
        assert hdata[0]["type"] == "bar" and hdata[0]["x"] == [375.125, 1125.375] and hdata[0]["y"] == [2, 3]
        assert hdata[0]["width"] == [750.25, 750.25] and "distribution of the values" in hlayout["title"]["text"]
        assert hlayout["yaxis"]["title"]["text"] == "Number of values"
        one = self._glarender(model.build_values_js(self._values(histogram={"edges": [7, 7], "counts": [3]}), "histogram", t))[0]
        assert one[0]["x"] == [7] and one[0]["y"] == [3] and one[0]["width"] == [1]
        assert self._glarender(model.build_values_js(self._values(), "nonsense", t))[0][0]["type"] == "scatter"

    def test_no_call_without_numbers_and_the_call_is_markup_free(self, model):
        assert not model.has_values(None) and model.has_values(self._values())
        for values in (self._values(supported=False), self._values(stats=None, points=[])):
            assert not model.has_values(values) and model.build_values_js(values, "series", self.THEME) is None
        evil = self._values(field='</script><a href="https://evil.example">x</a>', label="L & <b>")
        js = model.build_values_js(evil, "series", self.THEME)
        assert "<" not in js and ">" not in js and "&" not in js
        layout = self._glarender(js)[1]
        assert "L &amp; &lt;b&gt;" in layout["title"]["text"] and "&lt;/script&gt;" in layout["title"]["text"]
        assert evil["field"] in model.build_values_table(evil)["title"]                  # the table shows plain text
        import re
        colours = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", model.build_values_js(self._values(), "series", self.THEME))}
        assert colours and colours <= {v.lower() for v in self.THEME.values()}

    @staticmethod
    def _day(**kw):
        """The heart rate of a day as garmin_export_scan_day.read_day returns it (four samples)."""
        day = {"schema": 1, "day": "2023-01-05", "state": "ok", "family": "fit_monitoring", "label": "FIT monitoring",
               "field": "heartRate", "supported": True, "stopped": False, "files": 2, "read": 2, "damaged": 0, "sources": 2,
               "offset_hours": 1.0, "dst_transition": False, "duplicates_same": 0, "duplicates_conflict": 0,
               "stats": {"count": 4, "min": 55, "max": 91, "mean": 70.5, "median": 68, "zeros": 0},
               "histogram": {"edges": [55, 73, 91], "counts": [3, 1]},
               "points": [["2023-01-05 00:00:00", 55], ["2023-01-05 00:01:00", 60], ["2023-01-05 23:59:00", 76],
                          ["2023-01-06 00:00:00", 91]], "thinned": False}
        day.update(kw)
        return day

    def test_the_day_table_shows_local_times_the_statistics_and_the_notes(self, model):
        assert model.is_day(self._day()) and not model.is_day(self._values())
        table = model.build_values_table(self._day())
        assert table["title"] == "Heart rate of 2023-01-05  (values)" and table["headers"] == ["Time (local)", "Heart rate (bpm)"]
        assert [[c["text"] for c in r] for r in table["rows"]] == [
            ["00:00:00", "55"], ["00:01:00", "60"], ["23:59:00", "76"], ["2023-01-06 00:00:00", "91"]]      # a date only off the day
        note = table["note"]
        assert "4 samples, min 55, max 91, mean 70.5, median 68, from 00:00:00 to 2023-01-06 00:00:00." in note
        assert "The samples come from 2 FIT files." in note
        assert "Unit: bpm (garmin_bulk_normalizer.py: FIT message 55 field 27 is kept as bpm" in note
        assert "The time of day is local: UTC+1 h, the offset at the start of the day." in note
        assert "clock change" not in note and "Seconds that more than one file holds" not in note and "Damaged" not in note
        more = model.build_values_table(self._day(dst_transition=True, duplicates_same=2, duplicates_conflict=10, damaged=1,
                                                  offset_hours=-3.5))["note"]
        assert "UTC-3.5 h" in more and "This day crosses a clock change; its times use the offset of the start of the day." in more
        assert "Seconds that more than one file holds: 12 (10 with a different value); the file created first wins." in more
        assert "Damaged files skipped: 1." in more

    def test_a_day_without_samples_says_why(self, model):
        texts = {}
        for state in ("unplanned", "no_files", "no_samples", "stopped"):
            table = model.build_values_table(self._day(state=state, stats=None, histogram=None, points=[]))
            assert table["rows"] == [] and table["headers"] == [] and table["title"] == "Heart rate of 2023-01-05  (values)"
            texts[state] = table["note"]
        assert len(set(texts.values())) == 4 and all(texts.values())
        assert "boundaries of this day are not known" in texts["unplanned"] and "Nothing is guessed" in texts["unplanned"]
        assert texts["no_files"] == "No monitoring file was created near this day."
        assert texts["no_samples"] == "The monitoring files near this day hold no heart-rate sample for it."
        assert "stopped before the end" in texts["stopped"]
        assert not model.has_values(self._day(state="no_files", stats=None, points=[]))
        assert model.build_values_js(self._day(state="no_files", stats=None, points=[]), "series", self.THEME) is None

    def test_the_day_chart_over_the_time_of_day_and_as_a_distribution(self, model):
        t = self.THEME
        data, layout = self._glarender(model.build_values_js(self._day(), "series", t))
        assert data[0]["x"] == ["2023-01-05 00:00:00", "2023-01-05 00:01:00", "2023-01-05 23:59:00", "2023-01-06 00:00:00"]
        assert data[0]["y"] == [55, 60, 76, 91] and layout["xaxis"]["type"] == "date"
        assert layout["title"]["text"] == "FIT monitoring 2023-01-05 › heartRate: values over time"
        assert layout["yaxis"]["title"]["text"] == "heartRate (bpm)"
        hdata, hlayout = self._glarender(model.build_values_js(self._day(), "histogram", t))
        assert hdata[0]["y"] == [3, 1] and hlayout["title"]["text"] == "FIT monitoring 2023-01-05 › heartRate: distribution of the values"
        assert hlayout["xaxis"]["title"]["text"] == "heartRate (bpm)"
        field = self._glarender(model.build_values_js(self._values(), "series", t))[1]
        assert field["title"]["text"] == "UDSFile › totalSteps: values over time"            # a field has no date in its title

    def test_no_colour_is_fixed_in_the_window_and_only_neutral_greys_in_the_model(self, app_root):
        """The colours are those of theme.py (the active theme), handed in by the app window."""
        import re
        import theme
        window = (app_root / "app" / "popups" / "export_scan.py").read_text(encoding="utf-8")
        model_src = (app_root / "app" / "popups" / "_export_scan_model.py").read_text(encoding="utf-8")
        hexes = re.compile(r"#[0-9a-fA-F]{6}\b")
        assert hexes.findall(window) == []
        greys = ["#202020", "#2a2a2a", "#3a3a3a", "#808080", "#888888", "#909090", "#989898", "#a0a0a0", "#b0b0b0", "#e0e0e0"]
        assert sorted(set(hexes.findall(model_src))) == greys
        palette = {v.lower() for t in theme._THEMES.values() for v in t.values() if isinstance(v, str)}
        assert not palette & set(greys)                                          # they belong to no theme


class TestExportScanWindow:

    @pytest.fixture
    def env(self, qtbot, tmp_path, monkeypatch):
        import types
        from unittest.mock import MagicMock
        from PyQt6.QtWidgets import QWidget
        import theme
        import app.popups.export_scan as win_mod

        from PyQt6.QtCore import pyqtSignal

        class _Page:
            def __init__(self):
                self.js = []                                  # what the window ran in the page (glaRender calls)

            def runJavaScript(self, code):
                self.js.append(code)

        class StubView(QWidget):
            """QtWebEngine is not started in the tests: the view remembers the URLs and the JavaScript it got,
            and a page is 'loaded' at once."""
            loadFinished = pyqtSignal(bool)

            def __init__(self):
                super().__init__()
                self.url = None
                self.urls = []
                self._page = _Page()

            def settings(self):
                return MagicMock()

            def page(self):
                return self._page

            def setUrl(self, url):
                self.url = url
                self.urls.append(url.toString())
                self.loadFinished.emit(True)

        monkeypatch.setattr(win_mod, "QWebEngineView", StubView)
        monkeypatch.setattr(win_mod, "_window", None)
        parent = QWidget()
        for name in ("BG", "BG2", "BG3", "ACCENT", "ACCENT2", "TEXT", "TEXT2", "GREEN", "YELLOW", "RED"):
            setattr(parent, name, getattr(theme, name))                  # the real theme, not a copy
        parent._dispatch = lambda fn, *args: fn(*args)
        parent._log = MagicMock()
        parent._panel_settings = MagicMock()
        parent._panel_settings._collect_settings.return_value = {"base_dir": str(tmp_path / "base")}
        qtbot.addWidget(parent)

        def make(**kw):
            kw.setdefault("run_in_thread", lambda fn: fn())
            kw.setdefault("plotly_script", lambda: "<script>/*plotly*/</script>")
            kw.setdefault("fit_scan", lambda path, should_stop=None, progress=None, index=None: None)     # no FIT part
            win = win_mod.ExportScanWindow(parent, **kw)
            qtbot.addWidget(win)
            return win

        return types.SimpleNamespace(parent=parent, make=make, mod=win_mod, zip=_scan_export_zip(tmp_path),
                                     theme=theme, tmp=tmp_path)

    @staticmethod
    def _item(win, text):
        from PyQt6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(win._tree)
        while it.value():
            if text in it.value().text(0):
                return it.value()
            it += 1
        raise AssertionError(f"no tree item with {text!r}")

    @staticmethod
    def _row(win, label):
        for r in range(win._table.rowCount()):
            if win._table.item(r, 0).text() == label:
                return r
        raise AssertionError(f"no table row {label!r}")

    def test_window_is_titled_not_modal_deleted_on_close_and_starts_empty(self, env):
        from PyQt6.QtCore import Qt
        win = env.make()
        assert win.windowTitle() == "Export Scan" and win.isModal() is False
        assert win.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        assert not win._save_btn.isEnabled() and not win._graph_btn.isEnabled() and not win._stop_btn.isEnabled()
        assert win._zip_btn.isEnabled() and "Choose the ZIP" in win._message.text()
        assert win._stack.currentWidget() is win._message and win._tree.topLevelItemCount() == 0

    def test_a_scan_fills_the_tree_and_shows_counts_only(self, env):
        win = env.make()
        win.start_scan(str(env.zip))
        names = [win._tree.topLevelItem(i).text(0) for i in range(win._tree.topLevelItemCount())]
        assert names[0] == "Overview" and "Daily values" in names and names[-1] == "Folders"
        assert win._save_btn.isEnabled() and win._zip_btn.isEnabled() and not win._stop_btn.isEnabled()
        assert win._status.text() == "3 of 4 JSON files read"
        env.parent._log.assert_called_once_with("🔍  Export scan: 3 of 4 JSON files read, 1 of no known family.")
        shown = " ".join([win._status.text(), win._title.text(), win._note.text(), env.parent._log.call_args.args[0]])
        assert "export_of_secret" not in shown and _SCAN_SECRET not in shown and "secret" not in shown
        assert win._title.text() == "Overview" and win._stack.currentWidget() is win._table

    def test_selecting_a_family_shows_its_table_with_tinted_cells_and_tooltips(self, env):
        from PyQt6.QtCore import Qt
        win = env.make()
        win.start_scan(str(env.zip))
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        assert win._title.text() == "UDSFile  (read by GLA)"
        assert [win._table.horizontalHeaderItem(c).text() for c in range(win._table.columnCount())] == \
            ["Field", "2021", "2022", "2023", "All years"]
        r = self._row(win, "restingHeartRate")
        assert win._table.item(r, 1).text() == "0 %" and win._table.item(r, 2).text() == "100 %"
        assert "absent 4 of 4 rows" in win._table.item(r, 1).toolTip()
        assert win._table.item(r, 2).background().style() == Qt.BrushStyle.SolidPattern
        assert win._table.item(self._row(win, "Rows"), 1).background().style() == Qt.BrushStyle.NoBrush
        full, empty = win._table.item(r, 2).background().color(), win._table.item(r, 1).background().color()
        assert full != empty                                      # more share, more accent colour

    def test_status_dots_and_tints_follow_the_theme(self, env):
        from PyQt6.QtGui import QColor
        theme = env.theme
        win = env.make()
        win.start_scan(str(env.zip))
        assert self._item(win, "UDSFile").foreground(0).color().name() == QColor(theme.GREEN).name()
        assert self._item(win, "MetricsMaxMetData").foreground(0).color().name() == QColor(theme.TEXT2).name()
        assert self._item(win, "UDSFile").text(0).startswith("● ") and win._tree.header().isHidden()
        assert theme.BG in win.styleSheet() and theme.ACCENT2 in win._tree.styleSheet()
        assert win._tint(100).name() != QColor(theme.BG3).name() and win._tint(0).name() == QColor(theme.BG3).name()

    def test_graph_writes_the_chart_page_and_shows_the_web_view(self, env):
        from pathlib import Path
        win = env.make()
        win.start_scan(str(env.zip))
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        assert win._graph_btn.isEnabled()
        win._graph_btn.click()
        assert win._mode == "graph" and win._stack.currentWidget() is win._web
        page = Path(win._tmpdir) / "chart.html"
        html = page.read_text(encoding="utf-8")
        assert "/*plotly*/" in html and env.theme.ACCENT in html and "Plotly.newPlot" in html
        assert env.theme.BG2 in html and env.theme.TEXT2 in html            # the whole theme reaches the page, not four colours
        assert win._web.url.toString().endswith("chart.html?1") and win._web.url.isLocalFile()
        win._tree.setCurrentItem(self._item(win, "Daily values"))                # a group has a chart as well
        assert win._mode == "graph" and win._web.url.toString().endswith("chart.html?2")
        win._tree.setCurrentItem(win._tree.topLevelItem(0))                      # the overview has none
        assert win._mode == "table" and not win._graph_btn.isEnabled() and win._stack.currentWidget() is win._table
        tmpdir = win._tmpdir
        win.close()
        assert not Path(tmpdir).exists() and win._tmpdir is None

    def test_a_missing_plotly_file_is_told_not_crashed_on(self, env):
        win = env.make(plotly_script=lambda: None)
        win.start_scan(str(env.zip))
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        win._graph_btn.click()
        assert win._stack.currentWidget() is win._message and "plotly.min.js" in win._message.text()
        assert win._web is None and win._tmpdir is None

    def test_rejecting_the_window_also_cleans_up(self, env):
        """Esc / reject() hide a dialog without a close event: the chart folder must go anyway."""
        from pathlib import Path
        win = env.make()
        win.start_scan(str(env.zip))
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        win._graph_btn.click()
        tmpdir = Path(win._tmpdir)
        assert tmpdir.exists()
        win.reject()
        assert not tmpdir.exists() and win._tmpdir is None and win._alive is False

    def test_errors_show_a_fixed_sentence_never_the_text_of_the_exception(self, env):
        import types

        def failing(exc):
            def scan(path, should_stop=None, progress=None):
                raise exc
            return types.SimpleNamespace(scan=scan, write_report=None)

        win = env.make(scanner=failing(FileNotFoundError("C:/Users/secret.name@example.invalid/export.zip")))
        win.start_scan("x")
        assert win._status.text() == "The path does not exist." and win._zip_btn.isEnabled() and not win._stop_btn.isEnabled()
        win2 = env.make(scanner=failing(PermissionError(13, "denied", "C:/Users/secret.name@example.invalid/export.zip")))
        win2.start_scan("x")
        assert win2._status.text() == "The export could not be scanned." and "secret" not in win2._status.text()
        assert win2._zip_btn.isEnabled() and not win2._save_btn.isEnabled() and win2._tree.topLevelItemCount() == 0

    def test_progress_stop_and_a_second_start_while_running(self, env):
        import types
        seen = {}

        def scan(path, should_stop=None, progress=None):
            progress(3, 7)
            seen["label"] = win._progress.text()
            seen["buttons"] = (win._zip_btn.isEnabled(), win._dir_btn.isEnabled(), win._stop_btn.isEnabled())
            win.start_scan("again")                                     # ignored: a scan is running
            seen["calls"] = seen.get("calls", 0) + 1
            win._stop_btn.click()
            seen["stopped"] = should_stop()
            seen["stop_label"] = win._progress.text()
            return {"files": {"json_total": 0, "json_read": 0, "unreadable": 0, "too_large": 0, "unknown_json": 0,
                              "nested_zips": 0, "fit": 0, "other": 0}, "stopped": True,
                    "groups": [], "families": {}, "unknown": {"files": 0, "folders": [], "folders_truncated": False},
                    "folders": [], "source": "zip"}

        win = env.make(scanner=types.SimpleNamespace(scan=scan, write_report=None))
        win.start_scan("x")
        assert seen["label"] == "Scanning ... 3 / 7 files" and seen["buttons"] == (False, False, True)
        assert seen["calls"] == 1 and seen["stopped"] is True and seen["stop_label"] == "Stopping ..."
        assert "stopped" in win._status.text() and win._progress.text() == "" and win._zip_btn.isEnabled()

    def test_save_report_writes_both_files_and_replaces_them(self, env):
        win = env.make()
        win.start_scan(str(env.zip))
        folder = env.tmp / "base" / "garmin_data" / "log"
        win._save_btn.click()
        assert sorted(p.name for p in folder.iterdir()) == ["export_scan_report.json", "export_scan_report.txt"]
        assert "Report saved" in win._status.text() and "export_of_secret" not in win._status.text()
        before = (folder / "export_scan_report.txt").read_text(encoding="utf-8")
        win._save_btn.click()
        assert (folder / "export_scan_report.txt").read_text(encoding="utf-8") == before
        assert _SCAN_SECRET not in before and "secret" not in before

    def test_save_report_without_a_data_folder_or_with_a_write_error(self, env):
        import types
        win = env.make()
        win.start_scan(str(env.zip))
        env.parent._panel_settings._collect_settings.return_value = {"base_dir": ""}
        win._save_btn.click()
        assert "Set the data folder" in win._status.text()
        win2 = env.make(scanner=types.SimpleNamespace(scan=win._scanner.scan,
                                                       write_report=lambda r, f: (_ for _ in ()).throw(OSError("C:/secret"))),
                        report_dir=lambda: env.tmp / "x")
        win2.start_scan(str(env.zip))
        win2._save_btn.click()
        assert win2._status.text() == "The report could not be saved."

    def test_an_answer_after_the_window_was_closed_is_ignored(self, env):
        win = env.make()
        result = win._scanner.scan(str(env.zip))
        win.close()
        win._on_done(result, None)
        win._on_progress(1, 2)
        assert win._tree.topLevelItemCount() == 0 and win._result is None

    def test_choosing_a_zip_or_a_folder_starts_the_scan(self, env):
        from unittest.mock import patch
        win = env.make()
        with patch.object(env.mod.QFileDialog, "getOpenFileName", return_value=("", "")), \
                patch.object(env.mod.QFileDialog, "getExistingDirectory", return_value=""):
            win._choose_zip()
            win._choose_folder()
        assert win._result is None
        with patch.object(env.mod.QFileDialog, "getOpenFileName", return_value=(str(env.zip), "")):
            win._choose_zip()
        assert win._result is not None and win._result["source"] == "zip"
        with patch.object(env.mod.QFileDialog, "getExistingDirectory", return_value=str(env.tmp)):
            win._choose_folder()
        assert win._result["source"] == "folder"

    def test_open_window_opens_one_window_and_raises_it_again(self, env, qtbot):
        from unittest.mock import MagicMock
        panel = MagicMock()
        panel._app = env.parent
        env.mod.open_window(panel)
        win = env.mod._window
        try:
            assert win is not None and win.isVisible()
            env.mod.open_window(panel)
            assert env.mod._window is win
        finally:
            win.close()
        qtbot.waitUntil(lambda: env.mod._window is None, timeout=3000)
        env.mod.open_window(panel)
        second = env.mod._window
        assert second is not None and second is not win
        second.close()
        qtbot.waitUntil(lambda: env.mod._window is None, timeout=3000)

    @staticmethod
    def _min_result(stopped=False, source="zip"):
        return {"files": {"json_total": 0, "json_read": 0, "unreadable": 0, "too_large": 0, "unknown_json": 0,
                          "nested_zips": 0, "fit": 0, "other": 0}, "stopped": stopped, "groups": [], "families": {},
                "unknown": {"files": 0, "folders": [], "folders_truncated": False}, "folders": [], "source": source}

    def test_the_fit_scan_follows_the_json_scan_and_adds_its_node(self, env):
        import copy
        seen = {}

        def fit_scan(path, should_stop=None, progress=None, index=None):
            seen["path"] = path
            seen["stop_is_callable"] = callable(should_stop)
            progress(500)
            seen["label"] = win._progress.text()
            return copy.deepcopy(TestExportScanModel.FIT)

        win = env.make(fit_scan=fit_scan)
        win.start_scan(str(env.zip))
        assert seen["path"] == str(env.zip) and seen["stop_is_callable"] and seen["label"] == "Reading FIT files ... 500"
        assert win._status.text() == "3 of 4 JSON files read, 7 FIT files read"
        env.parent._log.assert_called_once_with(
            "🔍  Export scan: 3 of 4 JSON files read, 1 of no known family, 7 FIT files read.")
        assert win._result["fit"]["files"]["read"] == 7 and win._progress.text() == ""
        win._tree.setCurrentItem(self._item(win, "FIT files"))
        assert win._title.text() == "FIT files" and win._graph_btn.isEnabled()
        assert [win._table.horizontalHeaderItem(c).text() for c in range(3)] == ["Type", "Files", "2019"]
        win._graph_btn.click()
        assert win._stack.currentWidget() is win._web and "Plotly.newPlot" in (
            __import__("pathlib").Path(win._tmpdir) / "chart.html").read_text(encoding="utf-8")
        win._tree.setCurrentItem(self._item(win, "Type 32"))
        assert win._title.text() == "Type 32 · all-day monitoring" and win._mode == "graph"
        assert win._table.rowCount() == 8 and win._web.url.toString().endswith("chart.html?2")      # 2019 to 2026

    def test_a_failing_fit_scan_keeps_the_json_view_and_shows_no_exception_text(self, env):
        def broken(path, should_stop=None, progress=None, index=None):
            raise RuntimeError("C:/Users/secret.name@example.invalid/export.zip")

        win = env.make(fit_scan=broken)
        win.start_scan(str(env.zip))
        assert win._status.text() == "3 of 4 JSON files read, the FIT files could not be read"
        assert "fit" not in win._result and win._tree.topLevelItemCount() > 3 and win._zip_btn.isEnabled()
        assert "secret" not in win._status.text() + " ".join(str(c) for c in env.parent._log.call_args_list)

    def test_a_stopped_fit_scan_marks_the_result_incomplete(self, env):
        import copy
        win = env.make(fit_scan=lambda path, should_stop=None, progress=None, index=None: {**copy.deepcopy(TestExportScanModel.FIT), "stopped": True})
        win.start_scan(str(env.zip))
        assert "scan stopped (numbers incomplete)" in win._status.text() and win._result["stopped"] is True
        assert win._result["fit"]["stopped"] is True

    def test_no_fit_scan_after_a_stopped_json_scan_or_an_unreadable_source(self, env):
        import types
        calls = []

        def fit_scan(path, should_stop=None, progress=None, index=None):
            calls.append(path)
            return None

        for stopped, source in ((True, "zip"), (False, "unreadable")):
            result = self._min_result(stopped=stopped, source=source)
            win = env.make(scanner=types.SimpleNamespace(scan=lambda p, should_stop=None, progress=None, r=result: r,
                                                          write_report=None), fit_scan=fit_scan)
            win.start_scan("x")
            assert win._result is result
        assert calls == []

    def test_the_real_fit_scan_counts_fit_files_of_an_export(self, env):
        import io
        import zipfile
        from datetime import datetime, timezone
        import fit_builder as fb

        def fit(ftype, year):
            return fb.simple_fit(ftype, int(datetime(year, 6, 1, tzinfo=timezone.utc).timestamp()))

        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("a.fit", fit(32, 2019))
            z.writestr("b.fit", fit(32, 2020))
            z.writestr("c.fit", fit(49, 2020))
            z.writestr("bad.fit", b"not a fit file")
        outer = env.tmp / "with_fit.zip"
        with zipfile.ZipFile(outer, "w") as z:
            z.writestr("DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_x_Part1.zip", inner.getvalue())
        win = env.make(fit_scan=env.mod._load_fit_scan())
        win.start_scan(str(outer))
        assert win._status.text() == "0 of 0 JSON files read, 3 FIT files read"
        win._tree.setCurrentItem(self._item(win, "FIT files"))
        rows = [[win._table.item(r, c).text() for c in range(win._table.columnCount())] for r in range(win._table.rowCount())]
        assert rows[0] == ["Type 32 · all-day monitoring", "2", "1", "1"] and rows[1] == ["Type 49 · sleep", "1", "", "1"]
        assert rows[-1] == ["All types", "3", "1", "2"]
        assert "1 damaged" in win._note.text()

    def _detail_env(self, env, zip_path=None, **fake):
        """A window whose scanner is the real one, with scan_field (and read_values) replaced by spies that
        record the call; `field=` / `values=` give a function that answers instead of the real one."""
        import types
        real = env.mod._load_scanner()
        calls, value_calls = [], []
        scan_field, read_values = fake.get("field"), fake.get("values")

        def spy(path, family, field, should_stop=None):
            calls.append((path, family, field, callable(should_stop)))
            return scan_field(path, family, field, should_stop) if scan_field else real.scan_field(path, family, field, should_stop)

        def spy_values(path, family, field, should_stop=None):
            value_calls.append((path, family, field, callable(should_stop)))
            return read_values(path, family, field, should_stop) if read_values else real.read_values(path, family, field, should_stop)

        win = env.make(scanner=types.SimpleNamespace(scan=real.scan, write_report=real.write_report, scan_field=spy,
                                                      read_values=spy_values))
        win._value_calls = value_calls
        win.start_scan(str(zip_path or env.zip))
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        return win, calls

    @staticmethod
    def _sentinel_zip(tmp):
        """An export whose UDSFile rows hold a numeric field with values found nowhere else (the sentinels)."""
        import json
        import zipfile
        rows = [{"calendarDate": "2023-01-05", "totalSteps": 1000, "secretMetric": 987654.321},
                {"calendarDate": "2023-01-06", "totalSteps": 2000, "secretMetric": 987655.5},
                {"calendarDate": "2023-02-01", "totalSteps": 3000, "secretMetric": 987656}]
        path = tmp / "sentinel_export.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("DI_CONNECT/DI-Connect-Aggregator/UDSFile_s.json", json.dumps(rows))
        return path

    def test_the_values_view_reads_the_field_and_shows_its_points_and_the_hint(self, env):
        win, _calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        assert win._values is None and not win._values_btn.isHidden() and not win._counts_btn.isHidden()
        assert win._series_btn.isHidden() and win._hint.isHidden()
        win._values_btn.click()
        assert win._value_calls == [(str(env.zip), "uds", "totalSteps", True)]
        assert win._values is not None and win._title.text() == "UDSFile › totalSteps  (values)"
        assert [win._table.horizontalHeaderItem(c).text() for c in range(2)] == ["Date", "Value (steps)"]
        assert win._table.rowCount() == 12 and win._table.item(0, 0).text() == "2021-03-01"
        assert "12 values, min 0, max 1003" in win._note.text() and "Unit: steps (garmin_normalizer.py" in win._note.text()
        assert win._status.text() == "totalSteps: 12 values read"                      # numbers only, no value
        assert not win._hint.isHidden() and win._hint.text() == "Values from your export are shown here. A screenshot of this view contains them."
        assert not win._series_btn.isHidden() and not win._dist_btn.isHidden() and win._series_btn.isChecked()
        assert win._month_btn.isHidden() and win._year_btn.isHidden() and win._values_btn.isChecked() and not win._counts_btn.isChecked()
        assert win._progress.text() == "" and win._zip_btn.isEnabled() and win._graph_btn.isEnabled()

    def test_the_values_page_has_no_values_they_reach_it_by_javascript_and_switch_without_a_reload(self, env):
        from pathlib import Path
        win, _calls = self._detail_env(env, zip_path=self._sentinel_zip(env.tmp))
        self._dbl(win, "secretMetric")
        win._values_btn.click()
        win._graph_btn.click()
        assert win._stack.currentWidget() is win._web and win._web_kind == "values" and win._web_ready is True
        assert win._web.url.toString().endswith("values.html?1")
        page = (Path(win._tmpdir) / "values.html").read_text(encoding="utf-8")
        assert "/*plotly*/" in page and "function glaRender" in page and 'Plotly.newPlot("chart", [],' in page
        assert "987654" not in page and "987655" not in page                          # no value in the file
        js = win._web.page().js
        assert len(js) == 1 and js[0].startswith("glaRender(") and "987654.321" in js[0] and '"type": "scatter"' in js[0]
        assert win._pending_js is None
        win._dist_btn.click()
        assert len(js) == 2 and '"type": "bar"' in js[1] and win._dist_btn.isChecked() and not win._series_btn.isChecked()
        win._series_btn.click()
        assert len(js) == 3 and '"type": "scatter"' in js[2] and win._web.urls == [win._web.urls[0]]   # one load, no reload
        for p in Path(win._tmpdir).iterdir():                                         # nothing else on disk holds a value
            assert "987654" not in p.read_text(encoding="utf-8")

    def test_back_to_the_counts_forgets_the_values_and_blanks_the_page(self, env):
        win, _calls = self._detail_env(env, zip_path=self._sentinel_zip(env.tmp))
        self._dbl(win, "secretMetric")
        win._values_btn.click()
        win._graph_btn.click()
        win._dist_btn.click()
        assert win._vmode == "histogram"
        win._counts_btn.click()
        assert win._values is None and win._pending_js is None
        assert "about:blank" in win._web.urls                                         # the page with the values was blanked
        assert win._web_kind == "counts" and win._web.urls[-1].endswith("chart.html?2")   # the graph mode shows the counts chart
        assert win._title.text() == "UDSFile › secretMetric"
        assert win._hint.isHidden() and not win._month_btn.isHidden() and win._counts_btn.isChecked()
        win._values_btn.click()                                                       # and again: read once more
        assert len(win._value_calls) == 2 and win._values is not None
        assert win._vmode == "series" and win._series_btn.isChecked() and not win._dist_btn.isChecked()   # new values: over time first

    def test_leaving_the_detail_the_item_or_a_new_scan_forgets_the_values(self, env):
        for how in ("back", "item", "scan", "close"):
            win, _calls = self._detail_env(env)
            self._dbl(win, "totalSteps")
            win._values_btn.click()
            win._graph_btn.click()
            assert win._values is not None
            if how == "back":
                win._back_btn.click()
            elif how == "item":
                win._tree.setCurrentItem(self._item(win, "MetricsMaxMetData"))
            elif how == "scan":
                win.start_scan(str(env.zip))
            else:
                win.close()
            assert win._values is None and win._pending_js is None, how
            if how != "close":
                assert win._web_kind != "values" and "about:blank" in win._web.urls, how      # the values page was blanked

    def test_no_value_gets_out_of_the_values_view_report_log_status_or_files(self, env):
        """The sentinels (numbers found nowhere else) may be in the table and in the chart call, nowhere else."""
        import json
        from pathlib import Path
        win, _calls = self._detail_env(env, zip_path=self._sentinel_zip(env.tmp))
        self._dbl(win, "secretMetric")
        win._values_btn.click()
        win._graph_btn.click()
        win._save_btn.click()
        base = Path(env.parent._panel_settings._collect_settings.return_value["base_dir"])
        reports = [p for p in base.rglob("*") if p.is_file()]
        assert {p.name for p in reports} == {"export_scan_report.json", "export_scan_report.txt"}
        assert all("987654" not in p.read_text(encoding="utf-8") and "987655" not in p.read_text(encoding="utf-8") for p in reports)
        logged = " ".join(str(c) for c in env.parent._log.call_args_list)
        assert "987654" not in logged and "987655" not in logged and "987656" not in logged
        assert all(s not in text for s in ("987654", "987655", "987656") for text in
                   (win._status.text(), win._progress.text(), json.dumps(win._result), json.dumps(win._detail)))
        for p in Path(win._tmpdir).iterdir():
            assert "987654" not in p.read_text(encoding="utf-8")
        assert "987654" in win._table.item(0, 1).text() and "987654.321" in win._web.page().js[0]   # in the view only

    def test_a_field_that_cannot_be_read_as_values_or_has_no_numbers_says_so(self, env):
        win, _calls = self._detail_env(env)
        win.start_detail("sleep", "napList[].a")
        win._values_btn.click()
        assert win._status.text() == "napList[].a: no numbers to show" and "cannot be shown as values" in win._note.text()
        assert win._table.rowCount() == 0 and not win._graph_btn.isEnabled() and not win._hint.isHidden()
        win2, _c = self._detail_env(env)
        win2.start_detail("uds", "stress")                                           # objects, no numbers with a date
        win2._values_btn.click()
        assert win2._status.text() == "stress: no numbers to show" and "No number with a date" in win2._note.text()

    def test_a_failing_values_read_shows_a_fixed_sentence_and_keeps_the_counts(self, env):
        def boom(path, family, field, should_stop):
            raise PermissionError(13, "denied", "C:/Users/secret.name@example.invalid/export.zip")

        win, _calls = self._detail_env(env, values=boom)
        self._dbl(win, "totalSteps")
        win._values_btn.click()
        assert win._status.text() == "The values could not be read." and win._values is None
        assert win._title.text() == "UDSFile › totalSteps" and win._zip_btn.isEnabled() and "secret" not in win._status.text()

        def missing(path, family, field, should_stop):
            raise FileNotFoundError("C:/secret")

        win2, _c = self._detail_env(env, values=missing)
        self._dbl(win2, "totalSteps")
        win2._values_btn.click()
        assert win2._status.text() == "The path does not exist."

    def test_stop_during_the_values_read_and_the_ignored_cases(self, env):
        real = env.mod._load_scanner()
        seen = {}

        def values(path, family, field_path, should_stop):
            win._stop_btn.click()
            seen["stopped"] = should_stop()
            seen["label"] = win._progress.text()
            return {**real.read_values(path, family, field_path, should_stop=lambda: False), "stopped": True}

        win, _calls = self._detail_env(env, values=values)
        self._dbl(win, "totalSteps")
        win._values_btn.click()
        assert seen == {"stopped": True, "label": "Stopping ..."} and "stopped before the end" in win._note.text()
        win._counts_btn.click()
        win._running = True
        win._values_btn.click()                                                      # a scan runs: ignored
        win._running = False
        assert len(win._value_calls) == 1
        win._back_btn.click()
        win.start_values()                                                           # no detail: ignored
        assert len(win._value_calls) == 1 and win._values is None
        win2, _c = self._detail_env(env)
        self._dbl(win2, "totalSteps")
        detail = win2._detail
        win2.close()
        win2._on_values_done(real.read_values(str(env.zip), "uds", "totalSteps"), None)   # after the close: ignored
        assert win2._values is None and detail is not None

    # ── Help: the guide of the window ──────────────────────────────────────────

    def test_the_help_button_shows_the_guide_in_the_viewer_of_the_app(self, env, monkeypatch):
        shown, asked = [], []

        class Viewer:
            def __init__(self, parent, title, text, markdown=False):
                shown.append((parent, title, text, markdown))

            def show(self):
                shown.append("show")

        guide = env.tmp / "guide.md"
        guide.write_bytes("# Guide\nçé".encode("utf-8"))
        monkeypatch.setattr(env.mod, "DocViewerDialog", Viewer)
        monkeypatch.setattr(env.mod.frozen_paths, "doc_path", lambda name: asked.append(name) or guide)
        win = env.make()
        assert win._help_btn.text() == "Help" and win._help_btn.isEnabled() and win._help_btn.parentWidget() is win   # in the bottom bar
        win._help_btn.click()
        assert asked == ["README_EXPORT_SCAN.md"] and env.mod.HELP_FILE == "README_EXPORT_SCAN.md"
        assert shown == [(env.parent, "Export Scan — Help", "# Guide\nçé", True), "show"]       # rendered as Markdown
        assert win._status.text() == ""

    def test_help_says_so_when_the_guide_is_missing_or_cannot_be_shown(self, env, monkeypatch):
        win = env.make()
        monkeypatch.setattr(env.mod.frozen_paths, "doc_path", lambda name: None)
        win._help_btn.click()
        assert win._status.text() == "The help file was not found."
        guide = env.tmp / "guide.md"
        guide.write_text("x", encoding="utf-8")

        class Broken:
            def __init__(self, *a, **k):
                raise RuntimeError("C:/Users/secret.name@example.invalid/guide.md")

        monkeypatch.setattr(env.mod.frozen_paths, "doc_path", lambda name: guide)
        monkeypatch.setattr(env.mod, "DocViewerDialog", Broken)
        win._help_btn.click()
        assert win._status.text() == "The help file could not be opened." and "secret" not in win._status.text()
        monkeypatch.setattr(env.mod.frozen_paths, "doc_path", lambda name: env.tmp / "gone" / "guide.md")      # found but unreadable
        monkeypatch.setattr(env.mod, "DocViewerDialog", lambda *a, **k: None)
        win._help_btn.click()
        assert win._status.text() == "The help file could not be opened."
        odd = env.tmp / "odd.md"
        odd.write_bytes(b"# Guide\xff\xfe end")                                 # not valid UTF-8: shown with replacement characters
        seen = []
        monkeypatch.setattr(env.mod.frozen_paths, "doc_path", lambda name: odd)
        monkeypatch.setattr(env.mod, "DocViewerDialog", lambda parent, title, text, markdown=False: seen.append(text) or env.parent)
        win._status.setText("")
        win._help_btn.click()
        assert seen == ["# Guide\ufffd\ufffd end"] and win._status.text() == ""

    def test_the_real_guide_is_found_and_opens_in_the_real_viewer(self, env, qtbot):
        from app.dialog_docs import DocViewerDialog
        win = env.make()
        win._help_btn.click()
        viewers = env.parent.findChildren(DocViewerDialog)
        assert len(viewers) == 1 and viewers[0].windowTitle() == "Export Scan — Help"
        qtbot.addWidget(viewers[0])
        text = viewers[0]._view.toPlainText()
        assert text.startswith("Export Scan — Guide") and "Privacy" in text and "Heart rate of the day" in text
        assert win._status.text() == ""

    def test_the_guide_matches_the_window_and_the_scan_modules(self, app_root):
        """The guide names what the window and the scan really have: buttons, report files, groups, limits, the build list."""
        import re
        import garmin_export_scan as scan
        import app.popups.export_scan as win_mod
        import compiler.build_manifest as manifest
        guide = (app_root / "docs" / win_mod.HELP_FILE).read_text(encoding="utf-8")
        window = (app_root / "app" / "popups" / "export_scan.py").read_text(encoding="utf-8")
        for label in ("ZIP file ...", "Folder ...", "Stop", "Table", "Graph", "Counts", "Values", "Month", "Year", "Over time",
                      "Distribution", "Save report", "Heart rate of the day", "← Back"):
            assert f'"{label}"' in window, label                                  # the button exists in the window
            assert label.replace("← ", "") in guide or label.replace(" ...", " ...") in guide, label
        assert scan.REPORT_TEXT in guide and scan.REPORT_JSON in guide
        assert all(label in guide for _key, label in scan.GROUPS)
        assert f"{scan.MAX_VALUE_POINTS:,}" in guide and f"{scan.MAX_PATHS_PER_FAMILY}" in guide
        assert f"{scan.MAX_JSON_BYTES // (1024 * 1024)} MB" in guide
        assert re.search(r"Data Collection.*Export Scan", guide, re.S) and "Export Scan" in (app_root / "app" / "panel_outputs.py").read_text(encoding="utf-8")
        assert win_mod.HELP_FILE in manifest.INFO_INCLUDE and (app_root / "docs" / win_mod.HELP_FILE).is_file()
        assert "@" not in re.sub(r"`<hidden>`|an `@`", "", guide)                  # no e-mail address in the guide

    # ── The heart rate of one day ──────────────────────────────────────────────

    SECRET_BPM = 98765.5                      # a "value" found nowhere else: it may be in the day view only

    def _day_env(self, env, days=("2023-01-05", "2023-01-06", "2023-01-09"), prepare=None, read_day=None, scanned=True):
        """A window with a fake FIT scan (it fills the index), a fake day reader that records its calls, and the scan done."""
        import copy
        import types
        calls = {"prepare": [], "read": []}
        prepared = {"days": list(days), "plan": object()}

        def fit_scan(path, should_stop=None, progress=None, index=None):
            index["a" * 64] = 1_000_000_000                       # the monitoring files the real scan puts in the index
            return copy.deepcopy(TestExportScanModel.FIT)

        def fake_prepare(path, index, should_stop=None):
            calls["prepare"].append((path, dict(index), callable(should_stop)))
            return prepare() if prepare else prepared

        def fake_read(path, prep, day, should_stop=None):
            calls["read"].append((path, prep, day, callable(should_stop)))
            if read_day:
                return read_day(path, prep, day, should_stop)
            points = [[f"{day} 00:00:00", self.SECRET_BPM], [f"{day} 00:01:00", 60], [f"{day} 00:02:00", 61]]
            return TestExportScanModel._day(day=day, points=points, stats={"count": 3, "min": 60, "max": self.SECRET_BPM,
                                                                            "mean": 1.0, "median": 61, "zeros": 0},
                                            histogram={"edges": [60, 49412.75, self.SECRET_BPM], "counts": [2, 1]})

        win = env.make(fit_scan=fit_scan, day_reader=types.SimpleNamespace(prepare=fake_prepare, read_day=fake_read))
        win._calls = calls
        win._prepared = prepared
        if scanned:
            win.start_scan(str(env.zip))
        return win

    def _fit_node(self, win):
        win._tree.setCurrentItem(self._item(win, "FIT files"))

    def test_the_day_view_comes_after_the_fit_scan_and_only_at_the_fit_node(self, env):
        win = self._day_env(env)
        assert win._calls["prepare"] == [(str(env.zip), {"a" * 64: 1_000_000_000}, True)]      # the index of the FIT scan, a stop function
        assert win._days is win._prepared and "index" not in win._result and "a" * 64 not in str(win._result)
        assert all(w.isHidden() for w in win._day_widgets)                         # the overview is shown first
        self._fit_node(win)
        assert not any(w.isHidden() for w in win._day_widgets) and win._day_btn.text() == "Heart rate of the day"
        assert win._day_edit.minimumDate().toString("yyyy-MM-dd") == "2023-01-05"
        assert win._day_edit.maximumDate().toString("yyyy-MM-dd") == "2023-01-09"
        assert win._day_edit.date().toString("yyyy-MM-dd") == "2023-01-09"          # the last day with files first
        win._tree.setCurrentItem(self._item(win, "Type 32"))
        assert all(w.isHidden() for w in win._day_widgets)
        assert win._calls["read"] == []                                             # nothing is read before the button

    def test_no_day_view_without_a_prepared_day_a_failed_prepare_or_an_incomplete_scan(self, env):
        for how in ("none", "boom"):
            def prepare(how=how):
                if how == "boom":
                    raise RuntimeError("C:/Users/secret.name@example.invalid/export.zip")
                return None
            win = self._day_env(env, prepare=prepare)
            assert win._days is None, how
            self._fit_node(win)
            assert all(w.isHidden() for w in win._day_widgets) and "secret" not in win._status.text(), how
            assert win._status.text() == "3 of 4 JSON files read, 7 FIT files read", how
        import copy
        import types
        calls = []
        stopped = types.SimpleNamespace(prepare=lambda *a, **k: calls.append(a),
                                        read_day=lambda *a, **k: None)
        win = env.make(fit_scan=lambda path, should_stop=None, progress=None, index=None: {**copy.deepcopy(TestExportScanModel.FIT), "stopped": True},
                       day_reader=stopped)
        win.start_scan(str(env.zip))
        none = env.make(day_reader=stopped)                                          # no FIT part at all
        none.start_scan(str(env.zip))
        assert calls == [] and win._days is None and none._days is None

    def test_the_day_button_reads_the_day_and_shows_it_as_values(self, env):
        win = self._day_env(env)
        self._fit_node(win)
        win._day_btn.click()
        assert win._calls["read"] == [(str(env.zip), win._prepared, "2023-01-09", True)]
        assert win._values is not None and win._title.text() == "Heart rate of 2023-01-09  (values)"
        assert [win._table.horizontalHeaderItem(c).text() for c in range(2)] == ["Time (local)", "Heart rate (bpm)"]
        assert win._table.rowCount() == 3 and win._table.item(1, 0).text() == "00:01:00" and win._table.item(1, 1).text() == "60"
        assert "3 samples" in win._note.text() and "Unit: bpm" in win._note.text()
        assert win._status.text() == "heartRate: 3 values read"                       # numbers only, no value
        assert not win._hint.isHidden() and not win._series_btn.isHidden() and not win._dist_btn.isHidden() and win._series_btn.isChecked()
        assert not win._back_btn.isHidden() and win._counts_btn.isHidden() and win._values_btn.isHidden()
        assert win._month_btn.isHidden() and win._year_btn.isHidden()
        assert not win._day_edit.isHidden() and win._day_btn.isEnabled() and win._progress.text() == ""
        assert win._graph_btn.isEnabled()
        win._graph_btn.click()
        js = win._web.page().js
        assert win._web_kind == "values" and len(js) == 1 and "glaRender(" in js[0] and "2023-01-09 00:01:00" in js[0]
        assert "FIT monitoring 2023-01-09" in js[0] and "heartRate (bpm)" in js[0]
        win._dist_btn.click()
        assert len(js) == 2 and '"type": "bar"' in js[1] and win._web.urls == [win._web.urls[0]]       # no reload

    def test_the_arrows_step_to_the_neighbouring_day_that_has_files(self, env):
        win = self._day_env(env)
        self._fit_node(win)
        read = win._calls["read"]
        win._day_prev.click()
        assert [c[2] for c in read] == ["2023-01-06"] and win._day_edit.date().toString("yyyy-MM-dd") == "2023-01-06"
        win._day_prev.click()
        win._day_prev.click()                                                       # no day before the first one: nothing happens
        assert [c[2] for c in read] == ["2023-01-06", "2023-01-05"] and win._day_edit.date().toString("yyyy-MM-dd") == "2023-01-05"
        win._day_next.click()
        win._day_next.click()
        win._day_next.click()                                                       # no day after the last one
        assert [c[2] for c in read] == ["2023-01-06", "2023-01-05", "2023-01-06", "2023-01-09"]
        from PyQt6.QtCore import QDate
        win._day_edit.setDate(QDate(2023, 1, 7))                                    # a day between two days with files
        win._day_prev.click()
        win._day_edit.setDate(QDate(2023, 1, 7))
        win._day_next.click()
        assert [c[2] for c in read][-2:] == ["2023-01-06", "2023-01-09"]
        assert win._title.text() == "Heart rate of 2023-01-09  (values)"

    def test_a_day_without_samples_shows_the_reason_and_no_graph(self, env):
        win = self._day_env(env, read_day=lambda path, prep, day, stop: TestExportScanModel._day(
            day=day, state="unplanned", stats=None, histogram=None, points=[]))
        self._fit_node(win)
        win._day_btn.click()
        assert win._status.text() == "heartRate: no numbers to show" and "boundaries of this day are not known" in win._note.text()
        assert win._table.rowCount() == 0 and not win._graph_btn.isEnabled() and not win._back_btn.isHidden()

    def test_back_the_item_a_new_scan_and_the_close_forget_the_day(self, env):
        for how in ("back", "item", "scan", "close"):
            win = self._day_env(env)
            self._fit_node(win)
            win._day_btn.click()
            win._graph_btn.click()
            assert win._values is not None, how
            if how == "back":
                win._back_btn.click()
                assert win._title.text() == "FIT files" and not win._day_edit.isHidden()      # the FIT table, the picker stays
            elif how == "item":
                win._tree.setCurrentItem(self._item(win, "Type 32"))
            elif how == "scan":
                win.start_scan(str(env.zip))
                assert len(win._calls["prepare"]) == 2
            else:
                win.close()
                assert win._days is None
            assert win._values is None and win._pending_js is None, how
            if how != "close":
                assert win._web_kind != "values" and "about:blank" in win._web.urls, how

    def test_a_new_scan_takes_the_day_view_away_until_it_is_done(self, env):
        win = self._day_env(env)
        self._fit_node(win)
        win._run = lambda fn: None                                                  # the scan starts but does not finish
        win.start_scan(str(env.zip))
        assert win._days is None and all(w.isHidden() for w in win._day_widgets)

    def test_a_failing_day_read_shows_a_fixed_sentence(self, env):
        def boom(path, prep, day, stop):
            raise PermissionError(13, "denied", "C:/Users/secret.name@example.invalid/export.zip")

        win = self._day_env(env, read_day=boom)
        self._fit_node(win)
        win._day_btn.click()
        assert win._status.text() == "The heart rate of the day could not be read." and win._values is None
        assert "secret" not in win._status.text() and win._zip_btn.isEnabled() and win._day_btn.isEnabled()

        def missing(path, prep, day, stop):
            raise FileNotFoundError("C:/secret")

        win2 = self._day_env(env, read_day=missing)
        self._fit_node(win2)
        win2._day_btn.click()
        assert win2._status.text() == "The path does not exist."

    def test_the_day_buttons_are_off_while_something_runs_and_the_late_answers_fall_away(self, env):
        win = self._day_env(env)
        self._fit_node(win)
        win._set_running(True)
        assert not any(w.isEnabled() for w in win._day_widgets)
        win.start_day()
        win._step_day(-1)
        assert win._calls["read"] == []
        win._set_running(False)
        assert all(w.isEnabled() for w in win._day_widgets)
        day = TestExportScanModel._day()
        win._tree.setCurrentItem(self._item(win, "Type 32"))                        # the view was left while the day was read
        win._on_values_done(day, None)
        assert win._values is None and win._series_btn.isHidden()
        self._fit_node(win)
        win._on_values_done(TestExportScanModel._values(), None)                    # a field's answer, but no field detail is open
        assert win._values is None
        win._on_values_done(day, None)                                              # the day's answer at the FIT node: shown
        assert win._values is day
        win._detail = {"family": "uds", "field": "x"}                                # a field detail is open: a day's answer is not for it
        win._values = None
        win._on_values_done(day, None)
        assert win._values is None
        win2 = self._day_env(env)
        self._fit_node(win2)
        win2.close()
        win2._on_values_done(day, None)
        win2.start_day()
        assert win2._values is None and win2._calls["read"] == []

    def test_no_sample_gets_out_of_the_day_view_report_log_status_or_files(self, env):
        import json
        from pathlib import Path
        win = self._day_env(env)
        self._fit_node(win)
        win._day_btn.click()
        win._graph_btn.click()
        win._save_btn.click()
        base = Path(env.parent._panel_settings._collect_settings.return_value["base_dir"])
        reports = [p for p in base.rglob("*") if p.is_file()]
        assert {p.name for p in reports} == {"export_scan_report.json", "export_scan_report.txt"}
        assert all("98765" not in p.read_text(encoding="utf-8") for p in reports)
        logged = " ".join(str(c) for c in env.parent._log.call_args_list)
        assert "98765" not in logged and "2023-01-09" not in logged
        assert all("98765" not in text for text in (win._status.text(), win._progress.text(), json.dumps(win._result)))
        for p in Path(win._tmpdir).iterdir():
            assert "98765" not in p.read_text(encoding="utf-8")
        assert "98765.5" in win._table.item(0, 1).text() and "98765.5" in win._web.page().js[0]       # in the view only
        assert "index" not in json.dumps(win._result) and "plan" not in json.dumps(win._result)

    def _dbl(self, win, label, column=2):
        win._table.cellDoubleClicked.emit(self._row(win, label), column)

    def test_double_click_on_a_field_opens_its_detail_by_month(self, env):
        win, calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        assert calls == [(str(env.zip), "uds", "totalSteps", True)]
        assert win._title.text() == "UDSFile › totalSteps" and win._status.text() == "totalSteps: 12 rows read"
        assert [win._table.horizontalHeaderItem(c).text() for c in range(win._table.columnCount())] == \
            ["Month", "Rows", "Filled", "Zero", "Empty", "Absent", "With a value"]
        # the export has 4 rows in March of 2021, 2022 and 2023: every month in between is a row of its own
        labels = [win._table.item(r, 0).text() for r in range(win._table.rowCount())]
        assert labels[0] == "2021-03" and labels[-2] == "2023-03" and labels[-1] == "All" and len(labels) == 26
        assert win._table.item(0, 1).text() == "4" and win._table.item(1, 1).text() == "0"
        assert win._table.item(win._table.rowCount() - 1, 1).text() == "12"
        assert not win._back_btn.isHidden() and not win._month_btn.isHidden() and not win._year_btn.isHidden()
        assert win._month_btn.isChecked() and not win._year_btn.isChecked() and win._graph_btn.isEnabled()
        assert win._zip_btn.isEnabled() and not win._stop_btn.isEnabled() and win._progress.text() == ""

    def test_the_detail_by_year_and_back_to_the_family_table(self, env):
        win, _calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        win._year_btn.click()
        assert win._gran == "year" and win._year_btn.isChecked() and not win._month_btn.isChecked()
        assert win._table.horizontalHeaderItem(0).text() == "Year" and win._table.item(0, 0).text() == "2021"
        assert win._table.item(0, 1).text() == "4" and win._table.rowCount() == 4              # 2021, 2022, 2023 and All
        win._month_btn.click()
        assert win._gran == "month" and win._table.horizontalHeaderItem(0).text() == "Month"
        win._year_btn.click()
        win._back_btn.click()
        assert win._detail is None and win._title.text() == "UDSFile  (read by GLA)"
        assert win._table.horizontalHeaderItem(0).text() == "Field"
        self._dbl(win, "totalSteps")                                      # the next detail starts by month again
        assert win._gran == "month" and win._month_btn.isChecked() and win._table.horizontalHeaderItem(0).text() == "Month"
        win._back_btn.click()
        assert win._back_btn.isHidden() and win._month_btn.isHidden() and win._year_btn.isHidden()

    def test_the_detail_graph_stacks_the_states_in_theme_colours(self, env):
        from pathlib import Path
        win, _calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        win._graph_btn.click()
        assert win._stack.currentWidget() is win._web
        html = (Path(win._tmpdir) / "chart.html").read_text(encoding="utf-8")
        assert '"name": "filled"' in html and env.theme.GREEN in html and env.theme.YELLOW in html and "rows by state per month" in html
        win._year_btn.click()
        assert "rows by state per year" in (Path(win._tmpdir) / "chart.html").read_text(encoding="utf-8")
        win._back_btn.click()
        assert win._mode == "graph" and "share of rows with a value" in (Path(win._tmpdir) / "chart.html").read_text(encoding="utf-8")

    def test_another_item_of_the_tree_leaves_the_detail(self, env):
        win, _calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        win._tree.setCurrentItem(self._item(win, "MetricsMaxMetData"))
        assert win._detail is None and win._back_btn.isHidden() and win._title.text().startswith("MetricsMaxMetData")

    def test_a_new_scan_ends_the_detail(self, env):
        win, _calls = self._detail_env(env)
        self._dbl(win, "totalSteps")
        win.start_scan(str(env.zip))
        assert win._detail is None and win._back_btn.isHidden() and win._title.text() == "Overview"

    def test_double_click_is_ignored_on_the_rows_line_other_items_while_running_and_before_a_scan(self, env):
        win, calls = self._detail_env(env)
        self._dbl(win, "Rows")
        win._tree.setCurrentItem(self._item(win, "Daily values"))
        win._table.cellDoubleClicked.emit(0, 1)
        win._table.cellDoubleClicked.emit(1, 1)                           # a row of the group table: not a field
        win._tree.setCurrentItem(self._item(win, "UDSFile"))
        win._running = True
        self._dbl(win, "totalSteps")
        win._running = False
        assert calls == [] and win._detail is None
        fresh = env.make()
        fresh._table.cellDoubleClicked.emit(0, 0)
        fresh.start_detail("uds", "totalSteps")                          # no scan yet: nothing to read
        assert fresh._detail is None
        self._dbl(win, "totalSteps")
        win._table.cellDoubleClicked.emit(1, 1)                           # in the detail: ignored
        assert len(calls) == 1

    def test_a_failing_field_read_shows_a_fixed_sentence_and_keeps_the_view(self, env):
        def boom(path, family, field, should_stop):
            raise PermissionError(13, "denied", "C:/Users/secret.name@example.invalid/export.zip")

        win, _calls = self._detail_env(env, field=boom)
        self._dbl(win, "totalSteps")
        assert win._status.text() == "The field could not be read." and win._detail is None
        assert win._title.text() == "UDSFile  (read by GLA)" and win._zip_btn.isEnabled() and "secret" not in win._status.text()

        def missing(path, family, field, should_stop):
            raise FileNotFoundError("C:/secret")

        win2, _c = self._detail_env(env, field=missing)
        self._dbl(win2, "totalSteps")
        assert win2._status.text() == "The path does not exist."

    def test_stop_during_the_field_read_and_an_answer_after_closing(self, env):
        real = env.mod._load_scanner()
        seen = {}

        def field(path, family, field_path, should_stop):
            win._stop_btn.click()
            seen["stopped"] = should_stop()
            seen["label"] = win._progress.text()
            result = real.scan_field(path, family, field_path, should_stop=lambda: False)
            return {**result, "stopped": True}

        win, _calls = self._detail_env(env, field=field)
        self._dbl(win, "totalSteps")
        assert seen == {"stopped": True, "label": "Stopping ..."}
        assert "read stopped (numbers incomplete)" in win._status.text() and "stopped before the end" in win._note.text()
        win2, _c = self._detail_env(env)
        detail = real.scan_field(str(env.zip), "uds", "totalSteps")
        win2.close()
        win2._on_detail_done(detail, None)
        assert win2._detail is None

    def test_the_outputs_panel_has_the_button_next_to_api_scan(self, qtbot):
        from unittest.mock import MagicMock, patch
        from PyQt6.QtWidgets import QPushButton
        from app.panel_outputs import PanelOutputs
        import theme
        app = MagicMock()
        for name in ("BG", "BG2", "BG3", "ACCENT", "ACCENT2", "TEXT", "TEXT2", "GREEN", "YELLOW"):
            setattr(app, name, getattr(theme, name))
        app.settings = {}
        app._panel_settings._collect_settings.return_value = {}
        panel = PanelOutputs(app)
        qtbot.addWidget(panel)
        texts = [b.text() for b in panel.findChildren(QPushButton)]
        assert any("API Scan" in t for t in texts) and any("Export Scan" in t for t in texts)
        button = next(b for b in panel.findChildren(QPushButton) if "Export Scan" in b.text())
        with patch("app.panel_outputs.export_scan.open_window") as opened:
            button.click()
        opened.assert_called_once_with(panel)
