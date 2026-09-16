#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_chat_history.py
Garmin Local Archive — Chat History Dialog (Baustein 21, garmin_collector-3_experiment)

Lists saved chat sessions (app/panel_chat.py's "Chat History" button,
next to Start/Stop) and lets the user pick one to load or delete.

Rules (same as dialogs.py/dialog_force_refetch.py):
  - No project-module imports besides PyQt6. `sessions` is handed in
    by the caller (panel_chat.py, via clients/chat_session_store.py's
    list_sessions()) — this file never reads/writes any file itself,
    and never imports clients/chat_session_store.py.
  - No business logic beyond selection state + reporting which action
    the user chose — actually deleting a file on disk is the caller's
    job (chat_session_store.delete_session()), once this dialog
    returns ("delete", path). The confirmation prompt below only
    guards against an accidental click; it never touches the
    filesystem itself.
  - app instance passed as parent (parent._app for theme colors)

Usage
-----
    dlg = ChatHistoryDialog(self, sessions)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        action, path = dlg.get_result()   # action: "load" | "delete"
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ChatHistoryDialog(QDialog):
    """
    Modal dialog listing saved chat sessions, newest first (the order
    `sessions` already arrives in — this dialog does not re-sort).
    Load and Delete act on the currently selected row; both start
    disabled until a row is selected. Delete asks for confirmation
    (QMessageBox.question, same pattern as panel_archive.py's/
    panel_outputs.py's own destructive actions) before returning —
    still only reports the choice, see module docstring.

    Parameters
    ----------
    parent   : QWidget — parent widget (needs _app with theme colors)
    sessions : list[dict] — clients/chat_session_store.py's
        list_sessions() result: {"path", "created_at", "backend",
        "datasource", "model", "provider", "preview"} per entry.
    """

    def __init__(self, parent, sessions: list[dict]):
        super().__init__(parent)
        self._result = None  # (action, path) | None, see get_result()

        app = parent._app
        bg, bg2, bg3 = app.BG, app.BG2, app.BG3
        text, t2, acc, acc2 = app.TEXT, app.TEXT2, app.ACCENT, app.ACCENT2

        self.setWindowTitle("Chat History")
        self.setModal(True)
        self.setMinimumSize(520, 380)
        self.setStyleSheet(f"background: {bg}; color: {text};")

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Saved Chats")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {text};")
        lay.addWidget(heading)

        self._list = QListWidget()
        self._list.setFont(QFont("Segoe UI", 9))
        self._list.setStyleSheet(
            f"QListWidget {{ background: {bg2}; color: {text}; border: none; }}"
            f"QListWidget::item {{ padding: 6px 4px; }}"
            f"QListWidget::item:selected {{ background: {acc2}; }}")
        for s in sessions:
            model_or_provider = s.get("provider") or s.get("model") or ""
            label = (f"{s.get('created_at', '?')}  —  "
                      f"{s.get('backend', '?')} / {s.get('datasource', '?')}")
            if model_or_provider:
                label += f"  ({model_or_provider})"
            if s.get("preview"):
                label += f"\n{s['preview']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(s["path"]))
            self._list.addItem(item)
        self._list.itemSelectionChanged.connect(self._update_button_state)
        self._list.itemDoubleClicked.connect(self._on_load)
        lay.addWidget(self._list, stretch=1)

        if not sessions:
            empty_lbl = QLabel("No saved chats yet.")
            empty_lbl.setFont(QFont("Segoe UI", 9))
            empty_lbl.setStyleSheet(f"color: {t2};")
            lay.addWidget(empty_lbl)

        btn_row = QHBoxLayout()

        self._load_btn = QPushButton("Load")
        self._load_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._load_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: white; border: none; "
            f"padding: 6px 18px; }}"
            f"QPushButton:disabled {{ background: {bg3}; color: {t2}; }}")
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.setEnabled(False)
        self._load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(self._load_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFont(QFont("Segoe UI", 9))
        self._delete_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {text}; border: none; "
            f"padding: 6px 18px; }}"
            f"QPushButton:disabled {{ color: {t2}; }}")
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFont(QFont("Segoe UI", 9))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; border: none; "
            f"padding: 6px 18px; }}")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        lay.addLayout(btn_row)

    def _update_button_state(self):
        has_selection = bool(self._list.selectedItems())
        self._load_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _selected_path(self) -> str | None:
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _on_load(self):
        path = self._selected_path()
        if path is None:
            return
        self._result = ("load", path)
        self.accept()

    def _on_delete(self):
        path = self._selected_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self, "Delete Chat",
            "Delete this saved chat? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._result = ("delete", path)
        self.accept()

    def get_result(self):
        """Returns (action, path) — action is "load" or "delete",
        path is the string path of the selected session — or None if
        the dialog was closed without choosing either (Close button,
        Esc, or a declined delete confirmation followed by Close)."""
        return self._result
