#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/diary_entry_editor.py
Garmin Local Archive — entry editor of one diary field

DIARY v1.7.8 — REMOVABLE.

EntryEditor — the entries of ONE field on ONE day, as lines of input boxes (step 4d of the diary tab). Used by
DiaryFieldRow in app/panel_diary.py.

  - One line per entry. A field with a time has a time box in every line and a "+ Add entry" button; a field
    without a time has exactly one line.
  - A Number value is a text box (a decimal comma is fine, "7,5"); empty means "not entered", which is not 0.
    A Yes/No value is a box with the choices (empty), Yes, No: empty means "not entered".
    A Text value is a text box for one line of free text; empty means "not entered".
  - Number values of a group of alternatives (steps or distance) share a selector: only the chosen one is shown.
  - A line in which nothing was entered is not an entry (a new line starts with the time "now" and nothing else).
  - The editor knows the raw text of its boxes (raw_state / set_raw_state), so that the panel can rebuild its
    rows without losing what was typed and not saved.

parse_number(text) is the one place that turns typed text into a number, clean_text(text) the one that
turns typed text into the text that is stored.

Rules:
  - EntryEditor(app, defn, entries, default_time): app carries the theme colors, defn is the definition of the
    field (diary_model shape), entries the entries the day has for it, default_time() -> "HH:MM" for a new line
  - collect() -> (entries, errors): entries as diary_writer.save_day wants them; errors are the labels of the
    values that are not numbers (the boxes are marked); nothing is saved here
"""

import re

from PyQt6.QtCore import QTime
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTimeEdit, QVBoxLayout, QWidget,
)

from diary import diary_model as dm

YESNO_CHOICES = ("", "Yes", "No")

_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)
_INTEGER_RE = re.compile(r"[+-]?[0-9]+", re.ASCII)
_MAX_ABS = 1e300
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def parse_number(text):
    """
    (ok, value) for typed text: '' -> (True, None) (not entered); '80' -> (True, 80); '7,5' -> (True, 7.5);
    '1e3' -> (True, 1000.0); anything else ('abc', '1.000,5', 'nan', 'inf', '1_0', a number beyond 1e300) ->
    (False, None). A comma is read as the decimal point; no thousands separators.
    """
    cleaned = text.strip().replace(",", ".")
    if not cleaned:
        return True, None
    if not _NUMBER_RE.fullmatch(cleaned):
        return False, None
    value = int(cleaned) if _INTEGER_RE.fullmatch(cleaned) else float(cleaned)
    if abs(value) > _MAX_ABS:
        return False, None
    return True, value


def clean_text(text):
    """A typed text as it is stored: control characters (tab, line break, ...) become a space, runs of space
    become one, the ends are cut. '' means "not entered"."""
    return " ".join(_CONTROL_RE.sub(" ", text).split())


class EntryLine(QWidget):
    """
    One entry: the time (for a field with a time), the boxes of the values, and a button to take the line out.
    Values of a group of alternatives (dm "group") share one selector: only the box of the chosen member is
    shown, the others are hidden and empty (choosing another member empties the one that was shown).
    """

    def __init__(self, app, defn, entry, time_text, can_remove):
        super().__init__()
        self._defn = defn
        self._app = app
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._normal_style = (f"QLineEdit {{ background: {app.BG}; color: {app.TEXT}; border: none; padding: 4px 8px; }}"
                              f"QLineEdit:disabled {{ color: {app.TEXT2}; }}")
        self._invalid_style = (f"QLineEdit {{ background: {app.BG}; color: {app.TEXT}; border: 1px solid #e05555; "
                               f"padding: 3px 7px; }}")

        self.time = None
        if defn["with_time"]:
            self.time = QTimeEdit()
            self.time.setDisplayFormat("HH:mm")
            self.time.setFont(QFont("Segoe UI", 9))
            self.time.setStyleSheet(
                f"QTimeEdit {{ background: {app.BG}; color: {app.TEXT}; border: none; padding: 4px 6px; }}"
                f"QTimeEdit:disabled {{ color: {app.TEXT2}; }}")
            self.time.setFixedWidth(70)
            self.time.setTime(self._qtime(entry["time"] if entry else time_text))
            lay.addWidget(self.time)

        self.inputs = {}
        self.group_selectors = {}           # group name -> QComboBox that chooses the member shown
        self._group_labels = {}             # group name -> the labels of its members, in order
        self._member_widgets = {}           # label of a grouped value -> the widgets that show or hide with it
        values = (entry or {}).get("values", {})
        for value in defn["values"]:
            label = value["label"]
            group = value.get("group")
            if group is not None and group not in self.group_selectors:
                self._add_selector(lay, group, values)
            if group is None:
                caption = QLabel(label)
                caption.setFont(QFont("Segoe UI", 8))
                caption.setStyleSheet(f"color: {app.TEXT2}; background: transparent;")
                lay.addWidget(caption)
            shown_with = []
            if value["type"] == dm.TYPE_YESNO:
                box = QComboBox()
                box.addItems(YESNO_CHOICES)
                box.setFont(QFont("Segoe UI", 9))
                box.setStyleSheet(self._combo_style())
                box.setMinimumWidth(80)
                if label in values:
                    box.setCurrentIndex(1 if values[label] else 2)
                lay.addWidget(box)
                lay.addWidget(self._arrow())
            elif value["type"] == dm.TYPE_TEXT:
                box = QLineEdit(str(values[label]) if label in values else "")
                box.setFont(QFont("Segoe UI", 9))
                box.setStyleSheet(self._normal_style)
                box.setMaxLength(dm.MAX_TEXT_LEN)
                box.setMinimumWidth(140)
                box.setMaximumWidth(260)
                lay.addWidget(box)
            else:
                box = QLineEdit(str(values[label]) if label in values else "")
                box.setFont(QFont("Segoe UI", 9))
                box.setStyleSheet(self._normal_style)
                box.setMinimumWidth(70)
                box.setMaximumWidth(110)
                lay.addWidget(box)
                shown_with.append(box)
                if value.get("unit"):
                    unit = QLabel(value["unit"])
                    unit.setFont(QFont("Segoe UI", 8))
                    unit.setStyleSheet(f"color: {app.TEXT2}; background: transparent;")
                    lay.addWidget(unit)
                    shown_with.append(unit)
            self.inputs[label] = box
            if group is not None:
                self._member_widgets[label] = shown_with
        for group in self.group_selectors:
            self._apply_group(group)
        lay.addStretch()

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(26)
        self.remove_btn.setFont(QFont("Segoe UI", 9))
        self.remove_btn.setToolTip("Take this entry out")
        self.remove_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {app.TEXT2}; border: none; }}"
            f"QPushButton:hover {{ color: {app.TEXT}; }}"
            f"QPushButton:disabled {{ color: {app.BG3}; }}")
        self.remove_btn.setVisible(can_remove)
        lay.addWidget(self.remove_btn)

    def _combo_style(self):
        app = self._app
        return (f"QComboBox {{ background: {app.BG}; color: {app.TEXT}; border: none; padding: 4px 8px; }}"
                f"QComboBox:disabled {{ color: {app.TEXT2}; }}"
                f"QComboBox::drop-down {{ border: none; }}"
                f"QComboBox QAbstractItemView {{ background: {app.BG3}; color: {app.TEXT}; "
                f"selection-background-color: {app.ACCENT2}; }}")

    def _arrow(self):
        # ▼ fallback label — Qt6/Windows suppresses the native drop-down arrow once a QComboBox has a
        # stylesheet (same fix as app/panel_mcp.py and app/panel_chat.py).
        arrow = QLabel("▼")
        arrow.setFont(QFont("Segoe UI", 7))
        arrow.setStyleSheet(f"color: {self._app.TEXT2}; background: {self._app.BG}; padding: 0px 6px 0px 0px;")
        arrow.setFixedWidth(16)
        return arrow

    def _add_selector(self, lay, group, values):
        """The selector of a group of alternatives, with the member present in the entry (else the first) chosen."""
        members = [v["label"] for v in self._defn["values"] if v.get("group") == group]
        selector = QComboBox()
        selector.addItems(members)
        selector.setFont(QFont("Segoe UI", 9))
        selector.setStyleSheet(self._combo_style())
        selector.setMinimumWidth(90)
        present = [i for i, label in enumerate(members) if label in values]
        if present:
            selector.setCurrentIndex(present[0])
        selector.currentIndexChanged.connect(lambda _index, g=group: self._on_group_changed(g))
        lay.addWidget(selector)
        lay.addWidget(self._arrow())
        self.group_selectors[group] = selector
        self._group_labels[group] = members

    def _apply_group(self, group):
        chosen = self.group_selectors[group].currentIndex()
        for position, label in enumerate(self._group_labels[group]):
            for widget in self._member_widgets[label]:
                widget.setVisible(position == chosen)

    def _on_group_changed(self, group):
        """The user chose another member: its box is shown, the others are hidden and emptied."""
        self._apply_group(group)
        chosen = self.group_selectors[group].currentIndex()
        for position, label in enumerate(self._group_labels[group]):
            if position != chosen:
                self.inputs[label].clear()
                self.inputs[label].setStyleSheet(self._normal_style)

    def _is_chosen(self, label):
        """False for a value of a group of alternatives that is not the chosen one."""
        for group, members in self._group_labels.items():
            if label in members:
                return members.index(label) == self.group_selectors[group].currentIndex()
        return True

    @staticmethod
    def _qtime(text):
        parsed = QTime.fromString(text or "", "HH:mm")
        return parsed if parsed.isValid() else QTime(0, 0)

    def time_text(self):
        """The time of the line as 'HH:MM', or None for a field without a time."""
        if self.time is None:
            return None
        t = self.time.time()
        return f"{t.hour():02d}:{t.minute():02d}"

    def raw_value(self, label):
        """What is in the box of a value: the text of a text box, the index (0, 1, 2) of a Yes/No box."""
        box = self.inputs[label]
        return box.currentIndex() if isinstance(box, QComboBox) else box.text()

    def has_content(self) -> bool:
        """True when something was entered in a box (text other than space, or Yes/No chosen)."""
        for label in self.inputs:
            if not self._is_chosen(label):
                continue
            raw = self.raw_value(label)
            if (raw.strip() if isinstance(raw, str) else raw):
                return True
        return False

    def raw_state(self) -> dict:
        return {"time": self.time_text(),
                "values": {label: self.raw_value(label) for label in self.inputs},
                "groups": {group: selector.currentIndex() for group, selector in self.group_selectors.items()}}

    def set_raw_state(self, state: dict):
        if self.time is not None and state.get("time"):
            self.time.setTime(self._qtime(state["time"]))
        for group, index in state.get("groups", {}).items():
            selector = self.group_selectors.get(group)
            if selector is None:
                continue
            selector.blockSignals(True)
            selector.setCurrentIndex(int(index))
            selector.blockSignals(False)
            self._apply_group(group)
        for label, raw in state.get("values", {}).items():
            box = self.inputs.get(label)
            if box is None:
                continue
            if isinstance(box, QComboBox):
                box.setCurrentIndex(int(raw))
            else:
                box.setText(str(raw))

    def set_editable(self, editable: bool):
        if self.time is not None:
            self.time.setEnabled(editable)
        for box in self.inputs.values():
            box.setEnabled(editable)
        for selector in self.group_selectors.values():
            selector.setEnabled(editable)
        self.remove_btn.setEnabled(editable)

    def clear_values(self):
        for box in self.inputs.values():
            if isinstance(box, QComboBox):
                box.setCurrentIndex(0)
            else:
                box.clear()
                box.setStyleSheet(self._normal_style)

    def collect(self):
        """(entry or None, labels of the values that are not numbers). A line with nothing entered is no entry."""
        values, bad = {}, []
        for value in self._defn["values"]:
            label = value["label"]
            if not self._is_chosen(label):
                continue
            box = self.inputs[label]
            if isinstance(box, QComboBox):
                if box.currentIndex() == 1:
                    values[label] = True
                elif box.currentIndex() == 2:
                    values[label] = False
                continue
            if value["type"] == dm.TYPE_TEXT:
                text = clean_text(box.text())
                if text:
                    values[label] = text
                continue
            ok, number = parse_number(box.text())
            box.setStyleSheet(self._normal_style if ok else self._invalid_style)
            if not ok:
                bad.append(label)
            elif number is not None:
                values[label] = number
        if bad or not values:
            return None, bad
        entry = {"values": values}
        if self.time is not None:
            entry = {"time": self.time_text(), "values": values}
        return entry, bad


class EntryEditor(QWidget):
    """The lines of one field on one day. With a time: any number of lines and "+ Add entry"; without: one line."""

    def __init__(self, app, defn, entries, default_time):
        super().__init__()
        self._app = app
        self._defn = defn
        self._default_time = default_time
        self._editable = True
        self._lines = []
        self.setStyleSheet("background: transparent;")
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(38, 0, 0, 4)
        self._box.setSpacing(4)
        self.add_btn = None
        if defn["with_time"]:
            self.add_btn = QPushButton("+ Add entry")
            self.add_btn.setFont(QFont("Segoe UI", 8))
            self.add_btn.setFixedWidth(100)
            self.add_btn.setStyleSheet(
                f"QPushButton {{ background: {app.BG}; color: {app.TEXT2}; border: none; padding: 3px 8px; }}"
                f"QPushButton:hover {{ color: {app.TEXT}; background: {app.ACCENT2}; }}"
                f"QPushButton:disabled {{ color: {app.BG3}; }}")
            self.add_btn.clicked.connect(lambda: self.add_line())
        for entry in entries:
            self.add_line(entry)
        if not self._lines:
            self.add_line()
        if self.add_btn is not None:
            self._box.addWidget(self.add_btn)

    @property
    def lines(self):
        return list(self._lines)

    def add_line(self, entry=None):
        line = EntryLine(self._app, self._defn, entry, self._default_time(),
                         can_remove=self._defn["with_time"])
        line.remove_btn.clicked.connect(lambda: self.remove_line(line))
        line.set_editable(self._editable)
        self._lines.append(line)
        self._box.insertWidget(len(self._lines) - 1, line)
        return line

    def remove_line(self, line):
        """Takes a line out; the last line is emptied instead (a field keeps one line)."""
        if len(self._lines) <= 1:
            line.clear_values()
            return
        self._lines.remove(line)
        self._box.removeWidget(line)
        line.setParent(None)
        line.deleteLater()

    def has_content(self) -> bool:
        return any(line.has_content() for line in self._lines)

    def collect(self):
        """(entries, errors): the lines in which something was entered, and the labels that are not numbers."""
        entries, errors = [], []
        for line in self._lines:
            entry, bad = line.collect()
            errors.extend(bad)
            if entry is not None:
                entries.append(entry)
        return entries, errors

    def raw_state(self) -> list:
        return [line.raw_state() for line in self._lines]

    def set_raw_state(self, state: list):
        while len(self._lines) < len(state):
            self.add_line()
        for line, raw in zip(self._lines, state):
            line.set_raw_state(raw)

    def set_editable(self, editable: bool):
        self._editable = editable
        for line in self._lines:
            line.set_editable(editable)
        if self.add_btn is not None:
            self.add_btn.setEnabled(editable)
