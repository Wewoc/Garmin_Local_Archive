#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
qwebengine_hardening.py

Leaf-Node — shared QWebEngineSettings hardening for embedded WebEngine views.

Garmin Local Archive uses QWebEngineView in two places to display content
generated entirely by this project (HTML dashboards, an XLSX preview) —
never third-party or remote content. This module disables WebEngine
capabilities that are not needed for that use case, reducing the attack
surface of the embedded Chromium engine without affecting functionality.

JavaScript itself stays enabled — Plotly dashboards require it to render.

Rules:
- No project-module imports — PyQt6 only.
- harden() is idempotent — safe to call multiple times on the same view.

Public interface:
    harden(view) -> None
"""

from PyQt6.QtWebEngineCore import QWebEngineSettings


def harden(view) -> None:
    """
    Applies conservative security settings to a QWebEngineView instance.

    Disables capabilities not needed for displaying locally-generated,
    trusted HTML/XLSX content: file URL access, remote URL access from
    local content, JS-triggered popups, plugins, and clipboard access via
    JavaScript. JavaScript execution itself remains enabled.

    Parameters
    ----------
    view : QWebEngineView — the view instance to harden. Must already be
           constructed (settings() requires an initialised view).
    """
    settings = view.settings()
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.PluginsEnabled, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)