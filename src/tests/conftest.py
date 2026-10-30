# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/conftest.py
Garmin Local Archive — pytest configuration

Provides shared fixtures for pytest-qt tests (test_qt_app.py).
The existing test_app_logic.py is a standalone script and does not use pytest.
"""

import sys
from pathlib import Path

import pytest

# ── sys.path — mirrors the structure of test_app_logic.py ─────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "app"))
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT / "context"))
sys.path.insert(0, str(_ROOT / "maps"))
sys.path.insert(0, str(_ROOT / "dashboards"))
sys.path.insert(0, str(_ROOT / "layouts"))

# ── Script-style test files (support.py's check()/summary(), not pytest) ──────
# summary() calls sys.exit() at import time — a bare `pytest` run here would
# crash mid-collection. Run these via `python tests/test_X.py` or run_tests.ps1.
collect_ignore = [
    "test_local.py",
    "test_basics.py",
    "test_security.py",
    "test_redact.py",
    "test_api_capability.py",
    "test_normalizer.py",
    "test_validator.py",
    "test_writer.py",
    "test_quality.py",
    "test_backup.py",
    "test_backup_common.py",
    "test_backup_bulk.py",
    "test_source_writer.py",
    "test_container_mirror.py",
    "test_import_mirror.py",
    "test_collector.py",
    "test_garmin_import.py",
    "test_bulk_fit_reader.py",
    "test_bulk_export_scanner.py",
    "test_bulk_normalizer.py",
    "test_bulk_writer.py",
    "test_bulk_import.py",
    "test_bulk_json_import.py",
    "test_bulk_rebuild.py",
    "test_api.py",
    "test_live_fetch.py",
    "test_silo_check.py",
    "test_silo_repair.py",
    "test_repair_resting_hr.py",  # RESTING-HR-REPAIR v1.7.5.7 — removable
    "test_repair_devices.py",     # DEVICE-REPAIR v1.7.6.9 — removable
    "test_track_migration.py",    # TRACK-MIGRATION v1.7.6.3
    "test_migration_snapshot.py", # TRACK-MIGRATION v1.7.6.3
    "test_daily_update.py",       # v1.7.6.4
    "test_force_refetch.py",
    "test_local_context.py",
    "test_dashboard.py",
    "test_broker.py",
    "test_mcp.py",
    "test_app_logic.py",
    "test_updater.py",
    "test_static.py",
    "test_build_output.py",
]


@pytest.fixture(scope="session")
def qapp_cls():
    """Use QApplication — required by pytest-qt.
    AA_ShareOpenGLContexts must be set before QApplication is created —
    required by QtWebEngineWidgets (v1.5.4.2+)."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    return QApplication


@pytest.fixture(scope="session")
def app_root():
    """Project root as Path — for file existence checks."""
    return _ROOT


@pytest.fixture(autouse=True)
def _no_browser_no_update_check(request, monkeypatch):
    """Keeps pytest tests from reaching outside the process: no real browser
    (webbrowser.open) and, for GarminApp tests (qtbot), no startup thread that
    calls GitHub's releases/latest. GarminApp.__init__ schedules
    _startup_bg_checks after 500 ms; only one _TestApp variant overrode it, the
    others hit the network whenever the event loop ran long enough. The fixture
    runs before qtbot creates the QApplication (autouse fixtures come first),
    so importing garmin_app_base here happens before any QApplication exists."""
    monkeypatch.setattr("webbrowser.open", lambda *a, **kw: True)
    if "qtbot" in request.fixturenames:
        import garmin_app_base
        monkeypatch.setattr(garmin_app_base.GarminApp, "_startup_bg_checks",
                            lambda self: None)
