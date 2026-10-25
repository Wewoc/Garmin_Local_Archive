#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_docs.py
Garmin Local Archive — Documentation Viewer (v1.7.6.4)

Shows one documentation file inside the app instead of handing it to an external program
(app/panel_home.py's "Documentation" button). Read-only, no images, no search.

Rules (same as dialogs.py/dialog_chat_history.py):
  - No project-module imports, PyQt6 only. The text is handed in by the caller, which
    finds and reads the file (frozen_paths.doc_path); this file never touches the disk.
  - `parent` is the app window: its colour attributes (BG, TEXT, TEXT2, ACCENT) style
    the viewer, like the other dialogs of the app.
  - No QWebEngine, no JavaScript, no network. A link is followed only if it is http or
    https (default browser); "#anchor" links scroll inside the page; anything else
    (file:, javascript:, mailto:, ...) is ignored.

Usage
-----
    dlg = DocViewerDialog(self._app, "User Guide", text, markdown=False)
    dlg.show()          # not modal; the parent owns it, closing it deletes it
"""

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QPalette, QColor
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

_LINK_SCHEMES = ("http", "https")


class DocViewerDialog(QDialog):
    """
    Non-modal window with a read-only view of one document.

    Parameters
    ----------
    parent   : QWidget — the app window (needs BG, TEXT, TEXT2, ACCENT)
    title    : str     — window title
    text     : str     — the document
    markdown : bool    — True: rendered as Markdown (headings, lists, tables, code);
                         False: shown as it is, in a monospace font
    """

    def __init__(self, parent, title: str, text: str, markdown: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(860, 680)
        self.setStyleSheet(f"background: {parent.BG}; color: {parent.TEXT};")

        self._view = QTextBrowser()
        self._view.setOpenLinks(False)
        self._view.setOpenExternalLinks(False)
        self._view.setReadOnly(True)
        self._view.setStyleSheet(
            f"QTextBrowser {{ background: {parent.BG}; color: {parent.TEXT}; border: none; padding: 6px; }}")
        palette = self._view.palette()
        palette.setColor(QPalette.ColorRole.Link, QColor(parent.ACCENT))
        self._view.setPalette(palette)
        self._view.anchorClicked.connect(self._on_link)

        if markdown:
            self._view.setMarkdown(text)
        else:
            font = QFont("Consolas", 9)
            font.setStyleHint(QFont.StyleHint.Monospace)
            self._view.setFont(font)
            self._view.setPlainText(text)

        close_btn = QPushButton("Close")
        close_btn.setFont(QFont("Segoe UI", 9))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {parent.BG3}; color: {parent.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {parent.ACCENT2}; }}")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        self._close_btn = close_btn

        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 6, 10, 10)
        bottom.addStretch()
        bottom.addWidget(close_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._view, 1)
        lay.addLayout(bottom)

    def _on_link(self, url: QUrl):
        """http/https -> default browser; "#anchor" -> scroll in the page; anything else is ignored."""
        if url.scheme().lower() in _LINK_SCHEMES:
            QDesktopServices.openUrl(url)
        elif not url.scheme() and not url.path() and url.hasFragment():
            self._view.scrollToAnchor(url.fragment())
