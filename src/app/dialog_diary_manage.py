#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_diary_manage.py
Garmin Local Archive — "Manage fields" dialog of the diary

DIARY v1.7.8 — REMOVABLE.

DiaryManageDialog — modal dialog that lists every field of the field list and lets the user rename a field and
archive or restore it. Opened by app/panel_diary.py ("Manage fields"). Archiving only hides a field (its entries
stay on the days, its key stays taken); restoring brings it back. Nothing else of a field can be changed: the
definition is fixed once the field exists (Konzept V2).

The dialog has the user interface; it writes nothing. The changes are made by the functions the panel hands in,
which call diary_writer; if one refuses, the reason is shown in the dialog and the dialog stays open.

Rules:
  - DiaryManageDialog(parent, lister, renamer, archiver): parent is the panel (parent._app carries the colors)
  - lister() -> {key: field} of the field list as it is now (read again after every change)
  - renamer(key, new_name) -> result dict of diary_writer ("status", "reason", "errors")
  - archiver(key, archived) -> result dict; archived is True to hide, False to restore
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from diary import diary_model as dm

from .dialog_diary_field import describe_failure

_OK_STATUSES = ("written", "unchanged")


class _FieldRow(QWidget):
    """One field: its name (editable), what kind of field it is, and the buttons Rename and Archive/Restore."""

    rename_requested = pyqtSignal(str, str)
    archive_requested = pyqtSignal(str, bool)

    def __init__(self, app, key, field):
        super().__init__()
        self.key = key
        self._archived = bool(field["archived"])
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)

        self.name = QLineEdit(field["name"])
        self.name.setFont(QFont("Segoe UI", 9))
        self.name.setStyleSheet(
            f"QLineEdit {{ background: {app.BG3}; color: {app.TEXT2 if self._archived else app.TEXT}; "
            f"border: none; padding: 5px 10px; }}")
        self.name.returnPressed.connect(self._on_rename)
        lay.addWidget(self.name, stretch=3)

        kind = "Garmin field" if dm.is_garmin_key(key) else "Your field"
        self.kind = QLabel(f"{kind}, archived" if self._archived else kind)
        self.kind.setFont(QFont("Segoe UI", 8))
        self.kind.setStyleSheet(f"color: {app.TEXT2}; background: transparent;")
        lay.addWidget(self.kind, stretch=2)

        button_style = (f"QPushButton {{ background: {app.BG3}; color: {app.TEXT}; border: none; padding: 5px 12px; }}"
                        f"QPushButton:hover {{ background: {app.ACCENT2}; }}")
        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setFont(QFont("Segoe UI", 9))
        self.rename_btn.setStyleSheet(button_style)
        self.rename_btn.clicked.connect(self._on_rename)
        lay.addWidget(self.rename_btn)

        self.archive_btn = QPushButton("Restore" if self._archived else "Archive")
        self.archive_btn.setFont(QFont("Segoe UI", 9))
        self.archive_btn.setStyleSheet(button_style)
        self.archive_btn.setFixedWidth(80)
        self.archive_btn.setToolTip("Show the field in the lists again" if self._archived
                                    else "Hide the field. Its entries stay on the days.")
        self.archive_btn.clicked.connect(lambda: self.archive_requested.emit(self.key, not self._archived))
        lay.addWidget(self.archive_btn)

    def _on_rename(self):
        self.rename_requested.emit(self.key, self.name.text())


class DiaryManageDialog(QDialog):

    def __init__(self, parent, lister, renamer, archiver):
        super().__init__(parent)
        self._app = parent._app
        self._lister = lister
        self._renamer = renamer
        self._archiver = archiver
        self.rows = {}
        a = self._app
        self.setWindowTitle("Manage fields")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(f"background: {a.BG}; color: {a.TEXT};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        heading = QLabel("Manage fields")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {a.TEXT};")
        lay.addWidget(heading)
        intro = QLabel("Rename a field or archive it. An archived field is hidden from the lists; its entries stay "
                       "on the days. Values, units and the time of a field cannot be changed afterwards.")
        intro.setWordWrap(True)
        intro.setFont(QFont("Segoe UI", 8))
        intro.setStyleSheet(f"color: {a.TEXT2};")
        lay.addWidget(intro)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {a.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setMinimumHeight(220)
        self._scroll.setStyleSheet(f"background: {a.BG};")
        self._list_host = QWidget()
        self._list_host.setStyleSheet(f"background: {a.BG};")
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(2)
        self._empty = QLabel("There are no fields yet.")
        self._empty.setFont(QFont("Segoe UI", 9))
        self._empty.setStyleSheet(f"color: {a.TEXT2}; background: transparent;")
        self._list_lay.addWidget(self._empty)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list_host)
        lay.addWidget(self._scroll)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setFont(QFont("Segoe UI", 9))
        self._error.setStyleSheet(f"color: {a.YELLOW}; background: transparent;")
        lay.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.setFont(QFont("Segoe UI", 9))
        self._close_btn.setStyleSheet(
            f"QPushButton {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {a.ACCENT2}; }}")
        self._close_btn.setDefault(False)
        self._close_btn.setAutoDefault(False)
        self._close_btn.clicked.connect(self.accept)
        buttons.addWidget(self._close_btn)
        lay.addLayout(buttons)

        self._rebuild()

    def error_text(self) -> str:
        return self._error.text()

    def _rebuild(self):
        for row in list(self.rows.values()):
            self._list_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = {}
        fields = self._lister()
        ordered = sorted(fields, key=lambda k: (bool(fields[k]["archived"]), k))
        for index, key in enumerate(ordered):
            row = _FieldRow(self._app, key, fields[key])
            row.rename_requested.connect(self._on_rename)
            row.archive_requested.connect(self._on_archive)
            self._list_lay.insertWidget(index, row)
            self.rows[key] = row
        self._empty.setVisible(not self.rows)

    def _on_rename(self, key, new_name):
        result = self._renamer(key, new_name)
        if result.get("status") in _OK_STATUSES:
            self._error.setText("")
            self._rebuild()
        else:
            self._error.setText(describe_failure(result, "renamed"))

    def _on_archive(self, key, archived):
        result = self._archiver(key, archived)
        if result.get("status") in _OK_STATUSES:
            self._error.setText("")
            self._rebuild()
        else:
            self._error.setText(describe_failure(result, "archived" if archived else "restored"))
