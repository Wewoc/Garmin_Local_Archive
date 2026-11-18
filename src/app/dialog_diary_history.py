#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_diary_history.py
Garmin Local Archive — "History" dialog of the diary

DIARY v1.7.8 — REMOVABLE.

DiaryHistoryDialog — modal dialog that lists the earlier states of one day (the history the writer keeps when a
day that is older than its free-edit window is changed), shows one state in full and puts a chosen state back.
Opened by app/panel_diary.py ("History"). The state that is replaced by a restore is kept in the history too, so a
restore can be undone by another restore.

The dialog has the user interface; it writes nothing. The restore is made by the function the panel hands in,
which calls diary_writer.restore_history; if that refuses, the reason is shown in the dialog.

describe_state(before, snapshot) turns a stored state into text: the note and, per field, one line per entry.

Rules:
  - DiaryHistoryDialog(parent, loader, restorer): parent is the panel (parent._app carries the theme colors)
  - loader() -> (history, snapshot): the history of the day as stored (oldest first) and the definitions of the day
  - restorer(index) -> result dict of diary_writer ("status", "reason"); index counts from the oldest state (0)
  - after exec(), restored is True when a state was put back
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from diary import diary_model as dm

_OK_STATUSES = ("written", "unchanged")
_PREVIEW_LEN = 40


def _format_value(value_def, value):
    if value_def["type"] == dm.TYPE_YESNO:
        return "yes" if value else "no"
    unit = value_def.get("unit")        # a text value has none
    return f"{value} {unit}" if unit else str(value)


def describe_state(before: dict, snapshot: dict) -> str:
    """The note and the entries of a stored state as text, one line per entry (fields by their name)."""
    lines = ["Note:", before["note"] if before["note"] else "(none)", "", "Entries:"]
    entries = before["entries"]
    if not any(entries.values()):
        lines.append("(none)")
    for key in sorted(entries):
        defn = snapshot.get(key)
        if defn is None or not entries[key]:
            continue
        lines.append(defn["name"])
        by_label = {v["label"]: v for v in defn["values"]}
        for entry in entries[key]:
            parts = [f"{label} {_format_value(by_label[label], value)}"
                     for label, value in entry["values"].items() if label in by_label]
            time = entry.get("time")
            lines.append("  " + (f"{time}  " if time else "") + ", ".join(parts))
    return "\n".join(lines)


def summarize_state(before: dict) -> str:
    """One short line for the list: the start of the note and the number of entries."""
    note = " ".join(before["note"].split())
    note = (note[:_PREVIEW_LEN] + "…") if len(note) > _PREVIEW_LEN else note
    count = sum(len(v) for v in before["entries"].values())
    return f"{note or '(no note)'} · {count} {'entry' if count == 1 else 'entries'}"


class DiaryHistoryDialog(QDialog):

    def __init__(self, parent, loader, restorer):
        super().__init__(parent)
        self._app = parent._app
        self._loader = loader
        self._restorer = restorer
        self.restored = False
        self._history = []
        self._snapshot = {}
        a = self._app
        self.setWindowTitle("History")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(f"background: {a.BG}; color: {a.TEXT};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        heading = QLabel("History")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {a.TEXT};")
        lay.addWidget(heading)
        intro = QLabel("Every time this day is changed after the day it was first saved, the state it had before is "
                       "kept here. Choose a state to see it, and put it back if you want. The state you replace is "
                       "kept too.")
        intro.setWordWrap(True)
        intro.setFont(QFont("Segoe UI", 8))
        intro.setStyleSheet(f"color: {a.TEXT2};")
        lay.addWidget(intro)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {a.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        self._list = QListWidget()
        self._list.setFont(QFont("Segoe UI", 9))
        self._list.setMinimumHeight(130)
        self._list.setStyleSheet(
            f"QListWidget {{ background: {a.BG3}; color: {a.TEXT}; border: none; }}"
            f"QListWidget::item:selected {{ background: {a.ACCENT2}; color: {a.TEXT}; }}")
        self._list.currentRowChanged.connect(self._on_row_changed)
        lay.addWidget(self._list)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setFont(QFont("Segoe UI", 9))
        self._view.setMinimumHeight(150)
        self._view.setStyleSheet(f"QPlainTextEdit {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px; }}")
        lay.addWidget(self._view)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setFont(QFont("Segoe UI", 9))
        self._error.setStyleSheet(f"color: {a.YELLOW}; background: transparent;")
        lay.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._restore_btn = self._button("Restore this state")
        self._restore_btn.setEnabled(False)
        self._restore_btn.setAutoDefault(False)
        self._restore_btn.clicked.connect(self._on_restore_clicked)
        buttons.addWidget(self._restore_btn)
        self._close_btn = self._button("Close")
        self._close_btn.setAutoDefault(False)
        self._close_btn.clicked.connect(self.accept)
        buttons.addWidget(self._close_btn)
        lay.addLayout(buttons)

        self._reload()

    def _button(self, text):
        a = self._app
        button = QPushButton(text)
        button.setFont(QFont("Segoe UI", 9))
        button.setStyleSheet(
            f"QPushButton {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {a.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {a.TEXT2}; }}")
        return button

    def error_text(self) -> str:
        return self._error.text()

    def _reload(self):
        """Reads the history again; the newest state is on top."""
        self._history, self._snapshot = self._loader()
        self._list.blockSignals(True)
        self._list.clear()
        for index in range(len(self._history) - 1, -1, -1):
            item = self._history[index]
            row = QListWidgetItem(f"{item['timestamp'].replace('T', ' ')}   ·   {summarize_state(item['before'])}")
            row.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(row)
        self._list.blockSignals(False)
        self._view.setPlainText("")
        self._restore_btn.setEnabled(False)
        if self._history:
            self._list.setCurrentRow(0)
        else:
            self._view.setPlainText("This day has no history.")

    def _chosen_index(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _on_row_changed(self, _row):
        index = self._chosen_index()
        if index is None:
            self._view.setPlainText("")
            self._restore_btn.setEnabled(False)
            return
        self._view.setPlainText(describe_state(self._history[index]["before"], self._snapshot))
        self._restore_btn.setEnabled(True)

    def _ask_restore(self, timestamp: str) -> bool:
        """True when the user confirms to put the state back (a test replaces this question)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restore this state")
        box.setText(f"Put the state from {timestamp.replace('T', ' ')} back?")
        box.setInformativeText("The state the day has now is kept in the history.")
        restore_btn = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        return box.clickedButton() is restore_btn

    def _on_restore_clicked(self):
        index = self._chosen_index()
        if index is None or not self._ask_restore(self._history[index]["timestamp"]):
            return
        result = self._restorer(index)
        if result.get("status") in _OK_STATUSES:
            self._error.setText("")
            self.restored = self.restored or result.get("status") == "written"
            self._reload()
        else:
            self._error.setText(f"The state could not be restored ({result.get('reason') or result.get('status', 'unknown')}).")
