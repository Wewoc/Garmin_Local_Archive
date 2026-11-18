#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_diary_field.py
Garmin Local Archive — "Create field" dialog of the diary

DIARY v1.7.8 — REMOVABLE.

DiaryFieldDialog — modal dialog to make a new Set 2 field of the diary: a name, whether an entry has a time
(then it can be entered several times a day), one or more values (label, type Number, Yes/No or Text, unit for a
number; a number can be marked "Alt." = an alternative to the number above it: per entry only one of them is
entered, for example steps or distance) and whether the field is shown as a favorite. Opened by
app/panel_diary.py ("Create field").

The dialog has the user interface and the checks that need no files; it writes nothing. The field is made by
the function the panel hands in (creator), which calls diary_writer; if that refuses (a name that is taken, ...)
the reason is shown in the dialog and the dialog stays open with what the user typed.

describe_failure(result, verb) turns a refusal of the writer into a sentence for the user (verb: what was tried,
"created" for a new field; app/dialog_diary_manage.py uses it for "renamed" and "archived").

Rules:
  - DiaryFieldDialog(parent, creator): parent is the panel (parent._app carries the theme colors)
  - creator(name, values, with_time, favorite) -> the result dict of diary_writer ("status", "reason", "key", ...)
  - after exec(), created_key is the key of the new field, or None
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from diary import diary_model as dm

KIND_NUMBER = "number"
KIND_YESNO = "yesno"
KIND_TEXT = "text"


def describe_failure(result: dict, verb: str = "created") -> str:
    """A sentence for the user for a result of diary_writer that is not 'written'."""
    reason = result.get("reason", "")
    errors = result.get("errors") or []
    if reason == "duplicate_name":
        return "A field with this name already exists (names are compared without regard to upper and lower case)."
    if reason == "invalid_definition":
        for code in errors:
            if code.startswith("name_missing"):
                return "Enter a name for the field."
            if code.startswith("name_too_long"):
                return f"The name may have at most {dm.MAX_NAME_LEN} characters."
            if code.startswith("values_missing"):
                return "Add at least one value."
            if code.startswith("values_too_many"):
                return f"A field can have at most {dm.MAX_VALUES} values."
            if "_label_missing" in code:
                return "Every value needs a label."
            if "_label_too_long" in code:
                return f"A label may have at most {dm.MAX_LABEL_LEN} characters."
            if "_label_duplicate" in code:
                return "The labels of the values must be different."
            if "_unit_too_long" in code:
                return f"A unit may have at most {dm.MAX_UNIT_LEN} characters."
            if "_group_not_allowed" in code:
                return "Only number values can be alternatives to each other."
            if code.startswith("group_single"):
                return "An alternative needs at least two values."
            if code.startswith("group_not_together"):
                return "Values that are alternatives must stand next to each other."
        return f"The field is not valid ({', '.join(errors) or 'no detail'})."
    if reason in ("master_damaged", "master_unsupported"):
        return "The list of fields cannot be changed: its file cannot be read or is from a newer version."
    if reason == "master_missing_days_exist":
        return "The list of fields is missing while days exist. It has to be rebuilt first."
    if reason == "write_failed":
        return "The field could not be saved (the file could not be written)."
    if reason == "typed_values":
        return "This field has values you typed on the day shown. Save or clear them first."
    return f"The field could not be {verb} ({reason or result.get('status', 'unknown')})."


class _ValueRow(QWidget):
    """One value of the field: label, type, unit and a button to remove the row."""

    remove_requested = pyqtSignal(object)
    kind_changed = pyqtSignal()

    def __init__(self, app, label="", kind=KIND_NUMBER, unit=""):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        field_style = (f"QLineEdit {{ background: {app.BG3}; color: {app.TEXT}; border: none; padding: 5px 10px; }}"
                       f"QLineEdit:disabled {{ color: {app.TEXT2}; }}")
        self.label = QLineEdit(label)
        self.label.setPlaceholderText("Label, e.g. systolic")
        self.label.setFont(QFont("Segoe UI", 9))
        self.label.setStyleSheet(field_style)
        lay.addWidget(self.label, stretch=3)

        self.kind = QComboBox()
        self.kind.addItem("Number", KIND_NUMBER)
        self.kind.addItem("Yes/No", KIND_YESNO)
        self.kind.addItem("Text", KIND_TEXT)
        self.kind.setFont(QFont("Segoe UI", 9))
        self.kind.setStyleSheet(
            f"QComboBox {{ background: {app.BG3}; color: {app.TEXT}; border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {app.BG3}; color: {app.TEXT}; "
            f"selection-background-color: {app.ACCENT2}; }}")
        lay.addWidget(self.kind, stretch=2)
        # ▼ fallback label — Qt6/Windows suppresses the native drop-down arrow once a QComboBox has a
        # stylesheet (same fix as app/panel_mcp.py and app/panel_chat.py).
        arrow = QLabel("▼")
        arrow.setFont(QFont("Segoe UI", 7))
        arrow.setStyleSheet(f"color: {app.TEXT2}; background: {app.BG3}; padding: 0px 6px 0px 0px;")
        arrow.setFixedWidth(16)
        lay.addWidget(arrow)

        self.unit = QLineEdit(unit)
        self.unit.setPlaceholderText("Unit, e.g. mmHg")
        self.unit.setFont(QFont("Segoe UI", 9))
        self.unit.setStyleSheet(field_style)
        lay.addWidget(self.unit, stretch=2)

        self.alt = QCheckBox("Alt.")
        self.alt.setFont(QFont("Segoe UI", 8))
        self.alt.setToolTip("Alternative to the number above: per entry only one of the two is entered "
                            "(for example steps or distance).")
        self.alt.setStyleSheet(f"color: {app.TEXT2}; background: transparent;")
        lay.addWidget(self.alt)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(30)
        self.remove_btn.setFont(QFont("Segoe UI", 9))
        self.remove_btn.setToolTip("Remove this value")
        self.remove_btn.setStyleSheet(
            f"QPushButton {{ background: {app.BG3}; color: {app.TEXT2}; border: none; padding: 5px 0px; }}"
            f"QPushButton:hover {{ background: {app.ACCENT2}; color: {app.TEXT}; }}"
            f"QPushButton:disabled {{ color: {app.BG3}; }}")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(self.remove_btn)

        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        self._on_kind_changed()
        if kind != KIND_NUMBER:
            self.kind.setCurrentIndex(self.kind.findData(kind))

    def kind_value(self) -> str:
        return self.kind.currentData()

    def _on_kind_changed(self, *_):
        is_number = self.kind_value() == KIND_NUMBER
        self.unit.setEnabled(is_number)
        if not is_number:
            self.unit.clear()
        self.kind_changed.emit()

    def value_definition(self) -> dict:
        label = dm.clean_name(self.label.text())
        if self.kind_value() == KIND_YESNO:
            return {"label": label, "type": dm.TYPE_YESNO}
        if self.kind_value() == KIND_TEXT:
            return {"label": label, "type": dm.TYPE_TEXT}
        return {"label": label, "type": dm.TYPE_NUMBER, "unit": self.unit.text().strip()}


class DiaryFieldDialog(QDialog):

    def __init__(self, parent, creator):
        super().__init__(parent)
        self._app = parent._app
        self._creator = creator
        self.created_key = None
        self._rows = []
        a = self._app
        self.setWindowTitle("Create field")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(f"background: {a.BG}; color: {a.TEXT};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        heading = QLabel("Create field")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {a.TEXT};")
        lay.addWidget(heading)
        intro = QLabel("A field is something you keep track of: a name and one or more values. With a time, "
                       "you can enter it several times a day.")
        intro.setWordWrap(True)
        intro.setFont(QFont("Segoe UI", 8))
        intro.setStyleSheet(f"color: {a.TEXT2};")
        lay.addWidget(intro)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {a.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)

        lay.addWidget(self._caption("Name"))
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. Painkiller")
        self._name.setFont(QFont("Segoe UI", 9))
        self._name.setStyleSheet(
            f"QLineEdit {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 5px 10px; }}")
        lay.addWidget(self._name)

        self._with_time = QCheckBox("Entries have a time (can be entered several times a day)")
        self._with_time.setFont(QFont("Segoe UI", 9))
        self._with_time.setStyleSheet(f"color: {a.TEXT}; background: transparent;")
        lay.addWidget(self._with_time)

        lay.addWidget(self._caption("Values"))
        self._values_box = QVBoxLayout()
        self._values_box.setSpacing(6)
        lay.addLayout(self._values_box)
        self._add_btn = self._button("+ Add value")
        self._add_btn.clicked.connect(lambda: self._add_row())
        add_row = QHBoxLayout()
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        lay.addLayout(add_row)

        self._favorite = QCheckBox("Show as favorite")
        self._favorite.setFont(QFont("Segoe UI", 9))
        self._favorite.setStyleSheet(f"color: {a.TEXT}; background: transparent;")
        self._favorite.setChecked(True)
        lay.addWidget(self._favorite)

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setFont(QFont("Segoe UI", 9))
        self._error.setStyleSheet(f"color: {a.YELLOW}; background: transparent;")
        lay.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._create_btn = self._button("Create")
        self._create_btn.setDefault(True)
        self._create_btn.clicked.connect(self._on_create_clicked)
        buttons.addWidget(self._create_btn)
        self._cancel_btn = self._button("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_btn)
        lay.addLayout(buttons)

        self._add_row()

    # ── Build helpers ───────────────────────────────

    def _caption(self, text):
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 8))
        label.setStyleSheet(f"color: {self._app.TEXT2}; background: transparent;")
        return label

    def _button(self, text):
        a = self._app
        button = QPushButton(text)
        button.setFont(QFont("Segoe UI", 9))
        button.setStyleSheet(
            f"QPushButton {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {a.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {a.TEXT2}; }}")
        return button

    # ── Value rows ──────────────────────────────────

    def _add_row(self, label="", kind=KIND_NUMBER, unit=""):
        if len(self._rows) >= dm.MAX_VALUES:
            return None
        row = _ValueRow(self._app, label, kind, unit)
        row.remove_requested.connect(self._remove_row)
        row.kind_changed.connect(self._refresh_row_buttons)
        self._rows.append(row)
        self._values_box.addWidget(row)
        self._refresh_row_buttons()
        return row

    def _remove_row(self, row):
        if len(self._rows) <= 1 or row not in self._rows:
            return
        self._rows.remove(row)
        self._values_box.removeWidget(row)
        row.deleteLater()
        self._refresh_row_buttons()

    def _refresh_row_buttons(self):
        """A field keeps at least one value; it cannot have more than the limit. "Alt." is possible for a
        number that stands below another number."""
        for index, row in enumerate(self._rows):
            row.remove_btn.setEnabled(len(self._rows) > 1)
            allowed = (index > 0 and row.kind_value() == KIND_NUMBER
                       and self._rows[index - 1].kind_value() == KIND_NUMBER)
            if not allowed:
                row.alt.setChecked(False)
            row.alt.setEnabled(allowed)
        self._add_btn.setEnabled(len(self._rows) < dm.MAX_VALUES)

    # ── Collect, create ─────────────────────────────

    def collect(self):
        """(name, values, with_time, favorite) as typed, with surrounding space removed."""
        name = dm.clean_name(self._name.text())
        values = [row.value_definition() for row in self._rows]
        groups = 0
        for index, row in enumerate(self._rows):
            if index > 0 and row.alt.isChecked():
                if "group" not in values[index - 1]:
                    groups += 1
                    values[index - 1]["group"] = f"alt{groups}"
                values[index]["group"] = values[index - 1]["group"]
        return name, values, self._with_time.isChecked(), self._favorite.isChecked()

    def _show_error(self, text: str):
        self._error.setText(text)

    def _on_create_clicked(self):
        name, values, with_time, favorite = self.collect()
        if not name:
            self._show_error("Enter a name for the field.")
            return
        if any(not value["label"] for value in values):
            self._show_error("Every value needs a label.")
            return
        labels = [value["label"].casefold() for value in values]
        if len(set(labels)) != len(labels):
            self._show_error("The labels of the values must be different.")
            return
        result = self._creator(name, values, with_time, favorite)
        if result.get("status") == "written":
            self.created_key = result.get("key")
            self.accept()
            return
        self._show_error(describe_failure(result))
