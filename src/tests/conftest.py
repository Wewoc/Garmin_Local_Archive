# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
