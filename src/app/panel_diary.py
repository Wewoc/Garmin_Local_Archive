#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/panel_diary.py
Garmin Local Archive — Diary Panel (Tagebuch)

DIARY v1.7.8 — REMOVABLE.

PanelDiary — PyQt6 QWidget, Tab 5 "Diary" in garmin_app_base.py's QTabWidget (behind "MCP Server").

Step 4a built the layout of the maintainer's sketch (KONZEPT_tagebuch_V2.md, Abschnitt 9), step 4b makes
the note of a day work:
  - the calendar picks the day; days that have a day file carry a dot; future days cannot be picked
  - the note of the day is loaded when the day is picked and saved with "Save"
  - "Delete all" removes the note and all entries of the day (after a question)
  - leaving the day or the tab with an unsaved note asks first: Save / Discard / Cancel, and says that
    the changes are lost otherwise
Steps 4c to 4d added the fields: favorite rows with entry boxes, the dropdown "Add field" (your fields, the
start templates, the Garmin fields), "Create field" and "Manage fields" (rename, archive, restore).
Step 4e (Baustein 3): the search box looks in the notes of all days (diary_reader.search_notes, read only): the
words typed, all of them in a note, newest day first; a click on a hit jumps to the day (the question about unsaved
changes comes first, as for any change of the day). The search runs a moment after the last key and again after
every change of the days.

Baustein 5 (backup): every save and every change of the field list is followed by a backup copy
(diary/diary_backup.py, a thin shell over garmin_backup_common); the first time the tab is shown for an archive
folder a background thread copies what is missing or outdated. A failed copy is told in the status line. A
day or a field list that cannot be read can be restored from its copy ("Restore from backup"); the damaged
file is kept next to it. Deleting a day does not delete its backup copy.

Step 4f (Baustein 2): a day that was first saved on an earlier calendar day can be changed too. The writer
refuses that with "history_required" unless the panel says keep_history; the panel asks once per day shown
("the previous state is kept in the history"), then writes. "History" lists the earlier states of the day and
puts one back (app/dialog_diary_history.py); what a restore replaces is kept in the history as well.

Everything is read and written through the diary package: diary_reader (read only) and diary_writer (the
sole writer of diary_data/). The panel hands the entries a day already has back unchanged on every save:
save_day replaces the WHOLE day, a panel that only knew the note would wipe them.
The archive folder is the "Archive folder" of the Settings; if it is empty or not a folder, everything is
disabled with a hint (an empty path would otherwise mean the current working folder).
Nothing is read when the panel is built (the settings are not loaded yet then), only when it is shown.

Layout:
  left   note · Save / Delete all / status · favorites · dropdown "Add field" + "Create field" + "Manage fields"
  right  calendar · selected day · search

Rules (same as the other panels):
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use the _diary_ prefix
  - Workers never touch widgets — use self._app._dispatch() (no worker here: the files are small and read on
    the main thread)
"""

import copy
import json
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QCalendarWidget, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

import garmin_config as _gcfg   # v1.7.8.1: only to read the switch "Diary in MCP" (the hint, see _diary_mcp_on)

from diary import diary_backup as bk
from diary import diary_catalog as cat
from diary import diary_model as dm
from diary import diary_reader as rd
from diary import diary_writer as wr

from .dialog_diary_field import DiaryFieldDialog, describe_failure
from .dialog_diary_history import DiaryHistoryDialog
from .dialog_diary_manage import DiaryManageDialog
from .dialog_force_refetch import EnglishCalendar
from .diary_entry_editor import EntryEditor

_NO_BASE = "nobase"
_TEMPLATE_PREFIX = "tpl:"             # item data of a start template in the dropdown: "tpl:" + its name

_TEXT_NO_BASE = "Archive folder not set or not found. Set it in Settings."
_TEXT_DAMAGED = "The file of this day cannot be read. It is left untouched."
_TEXT_UNSUPPORTED = "The file of this day was written by a newer version. It is left untouched."
_TEXT_NOT_SAVED = "Not saved. Your changes are still in the boxes."
_TEXT_BACKUP_FAILED = "The backup copy could not be made (see the log)."
# v1.7.8.1: shown only while "Diary in MCP" is on (the MCP cache is a copy that is brought up to date by the next
# server start, "refresh_cache" or export — nothing in this tab pushes a change to it)
_TEXT_MCP_HINT = ("Diary in MCP is on: a change reaches the MCP cache at the next server start, refresh or export.")
_TEXT_MCP_DELETED = " The MCP cache still shows the day until its next update (server start, refresh or export)."
_SEARCH_DELAY_MS = 300


class DiaryCalendar(EnglishCalendar):
    """
    Calendar to pick one day (English day and month names, week from Monday: the base class EnglishCalendar). day_selected(str) carries 'YYYY-MM-DD' after every change of the
    selected day (a click or the keys). Days handed to set_marked_days() carry a small dot, drawn in
    paintCell (setDateTextFormat does not keep earlier cell formats reliably, see the note in
    app/dialog_force_refetch.py). A third small calendar class next to the two of that module on
    purpose: DateToggleCalendar toggles a set of days and SelectionOnlyCalendar blocks every click,
    neither picks one day.
    """

    day_selected = pyqtSignal(str)

    def __init__(self, parent=None, mark_color="#a259f7"):
        super().__init__(parent)
        self._marked = set()
        self._mark_color = QColor(mark_color)
        self.selectionChanged.connect(self._on_selection_changed)

    def selected_date_str(self) -> str:
        """The selected day as 'YYYY-MM-DD' (ISO format, digits of the Latin script whatever the locale)."""
        return self.selectedDate().toString(Qt.DateFormat.ISODate)

    def set_marked_days(self, dates):
        """The days (ISO strings) that carry a dot; replaces the set before."""
        self._marked = set(dates)
        self.updateCells()

    def is_marked(self, date_str: str) -> bool:
        return date_str in self._marked

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        if date.toString(Qt.DateFormat.ISODate) in self._marked:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._mark_color)
            painter.drawEllipse(rect.right() - 10, rect.bottom() - 10, 6, 6)
            painter.restore()

    def _on_selection_changed(self):
        self.day_selected.emit(self.selected_date_str())


class DiaryFieldRow(QFrame):
    """
    One row of the field list: a star (favorite on or off), the name, what the field holds, and a button
    that takes a field that is not a favorite out of the list again. Below the header sits the EntryEditor
    with the entry boxes of the day (step 4d); a row made without a definition has no editor.
    """

    favorite_toggled = pyqtSignal(str)
    remove_requested = pyqtSignal(str)

    def __init__(self, app, key, name, hint, favorite, can_toggle, can_remove,
                 defn=None, entries=None, default_time=None):
        super().__init__()
        self.key = key
        self.favorite = favorite
        self.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        outer.addLayout(lay)

        self.star = QPushButton("★" if favorite else "☆")
        self.star.setFixedWidth(30)
        self.star.setFont(QFont("Segoe UI", 11))
        self.star.setToolTip("Remove from favorites" if favorite else "Add to favorites")
        self.star.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {app.ACCENT if favorite else app.TEXT2}; border: none; }}"
            f"QPushButton:hover {{ color: {app.TEXT}; }}"
            f"QPushButton:disabled {{ color: {app.TEXT2}; }}")
        self.star.setEnabled(can_toggle)
        self.star.clicked.connect(lambda: self.favorite_toggled.emit(self.key))
        lay.addWidget(self.star)

        self.name_label = QLabel(name)
        self.name_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.name_label.setStyleSheet(f"color: {app.TEXT}; background: transparent;")
        lay.addWidget(self.name_label)
        self.hint_label = QLabel(hint)
        self.hint_label.setFont(QFont("Segoe UI", 8))
        self.hint_label.setStyleSheet(f"color: {app.TEXT2}; background: transparent;")
        lay.addWidget(self.hint_label)
        lay.addStretch()

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setFixedWidth(30)
        self.remove_btn.setFont(QFont("Segoe UI", 9))
        self.remove_btn.setToolTip("Take this field out of the list")
        self.remove_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {app.TEXT2}; border: none; }}"
            f"QPushButton:hover {{ color: {app.TEXT}; }}")
        self.remove_btn.setVisible(can_remove)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.key))
        lay.addWidget(self.remove_btn)

        self.editor = None
        if defn is not None:
            self.editor = EntryEditor(app, defn, entries or [], default_time or (lambda: "00:00"))
            outer.addWidget(self.editor)


class PanelDiary(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._diary_now = datetime.now      # the clock; a test replaces it
        self._diary_base = None             # Path of the archive folder, or None
        self._diary_day = None              # 'YYYY-MM-DD' of the day shown
        self._diary_state = _NO_BASE        # state of the day shown (rd.OK, rd.MISSING, ... or _NO_BASE)
        self._diary_loaded_note = ""        # the note as stored; the text box differs from it = unsaved
        self._diary_entries = {}            # the entries the day has; handed back unchanged on every save
        self._diary_tabs = None             # the QTabWidget this panel sits in (attach_to_tabs)
        self._diary_tab_index = None
        self._diary_on_tab = False          # True while the diary tab is the shown one
        self._diary_reverting = False       # True while the calendar is put back (no question then)
        self._diary_master = None           # the field list (fields.json) as read, or None
        self._diary_master_state = _NO_BASE
        self._diary_snapshot = {}           # the definitions the loaded day keeps (names of fields no longer listed)
        self._diary_added = []              # keys added from the dropdown for the day shown
        self._diary_rows = {}               # key -> DiaryFieldRow of the field list
        self._diary_backup_base = None      # the archive folder the backup at the start was started for
        self._diary_history_ok = False      # True once the user agreed that the day shown keeps a history
        self._diary_history_count = 0       # number of earlier states the day shown has
        self._diary_drafts = {}             # key -> what was typed in the entry boxes and not saved (raw)
        self._build_ui()
        self._diary_load_day()              # no file access without a base folder

    # ── Build ───────────────────────────────────────

    def _build_ui(self):
        a = self._app
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 10)
        outer.setSpacing(0)

        heading = QLabel("Diary")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {a.TEXT};")
        outer.addWidget(heading)
        outer.addSpacing(10)

        header = QLabel("DIARY")
        header.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {a.ACCENT};")
        outer.addWidget(header)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {a.ACCENT};")
        sep.setFixedHeight(1)
        outer.addWidget(sep)
        outer.addSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(self._diary_build_left(), stretch=1)
        body.addLayout(self._diary_build_right())
        outer.addLayout(body)

        outer.addSpacing(10)
        hint = QLabel("The note and the entries are saved per day. A copy of every day is kept in the backup.")
        hint.setWordWrap(True)
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet(f"color: {a.TEXT2};")
        outer.addWidget(hint)
        outer.addStretch()

    def _diary_caption(self, text):
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 8))
        label.setStyleSheet(f"color: {self._app.TEXT2};")
        return label

    def _diary_button(self, text):
        a = self._app
        button = QPushButton(text)
        button.setFont(QFont("Segoe UI", 9))
        button.setStyleSheet(
            f"QPushButton {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {a.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {a.TEXT2}; }}")
        return button

    def _diary_build_left(self):
        a = self._app
        lay = QVBoxLayout()
        lay.setSpacing(6)

        lay.addWidget(self._diary_caption("Note"))
        self._diary_note = QPlainTextEdit()
        self._diary_note.setPlaceholderText("Free text for the day")
        self._diary_note.setMinimumHeight(140)
        self._diary_note.setFont(QFont("Segoe UI", 9))
        self._diary_note.setStyleSheet(
            f"QPlainTextEdit {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 6px; }}"
            f"QPlainTextEdit:disabled {{ color: {a.TEXT2}; }}")
        self._diary_note.setEnabled(False)
        lay.addWidget(self._diary_note)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._diary_save_btn = self._diary_button("Save")
        self._diary_save_btn.setEnabled(False)
        self._diary_save_btn.clicked.connect(self._diary_on_save_clicked)
        action_row.addWidget(self._diary_save_btn)
        self._diary_delete_btn = self._diary_button("Delete all")
        self._diary_delete_btn.setEnabled(False)
        self._diary_delete_btn.clicked.connect(self._diary_on_delete_clicked)
        action_row.addWidget(self._diary_delete_btn)
        self._diary_status = QLabel()
        self._diary_status.setFont(QFont("Segoe UI", 8))
        self._diary_status.setWordWrap(True)
        self._diary_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        action_row.addWidget(self._diary_status, stretch=1)
        lay.addLayout(action_row)
        self._diary_mcp_hint = QLabel(_TEXT_MCP_HINT)
        self._diary_mcp_hint.setFont(QFont("Segoe UI", 8))
        self._diary_mcp_hint.setStyleSheet(f"color: {a.TEXT2};")
        self._diary_mcp_hint.setWordWrap(True)
        self._diary_mcp_hint.setVisible(False)      # shown by _diary_refresh() when the switch is on
        lay.addWidget(self._diary_mcp_hint)
        lay.addSpacing(6)

        lay.addWidget(self._diary_caption("Favorites"))
        self._diary_favorites = QFrame()
        self._diary_favorites.setStyleSheet(f"background: {a.BG3};")
        self._diary_fav_lay = QVBoxLayout(self._diary_favorites)
        self._diary_fav_lay.setContentsMargins(10, 10, 10, 10)
        self._diary_fav_lay.setSpacing(2)
        self._diary_favorites_hint = QLabel()
        self._diary_favorites_hint.setFont(QFont("Segoe UI", 9))
        self._diary_favorites_hint.setStyleSheet(f"color: {a.TEXT2}; background: transparent;")
        self._diary_favorites_hint.setWordWrap(True)
        self._diary_fav_lay.addWidget(self._diary_favorites_hint)
        self._diary_favorites.setMinimumHeight(110)
        lay.addWidget(self._diary_favorites)
        lay.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._diary_field_combo = QComboBox()
        self._diary_field_combo.addItem("Add field …")
        self._diary_field_combo.setFont(QFont("Segoe UI", 9))
        self._diary_field_combo.setMinimumWidth(220)
        self._diary_field_combo.setStyleSheet(
            f"QComboBox {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 5px 10px; }}"
            f"QComboBox:disabled {{ color: {a.TEXT2}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {a.BG3}; color: {a.TEXT}; "
            f"selection-background-color: {a.ACCENT2}; }}")
        self._diary_field_combo.setEnabled(False)
        self._diary_field_combo.activated.connect(self._diary_on_field_chosen)
        row.addWidget(self._diary_field_combo)
        # ▼ fallback label — Qt6/Windows suppresses the native drop-down arrow once a QComboBox has
        # a stylesheet (same fix as app/panel_mcp.py and app/panel_chat.py).
        arrow = QLabel("▼")
        arrow.setFont(QFont("Segoe UI", 7))
        arrow.setStyleSheet(f"color: {a.TEXT2}; background: {a.BG3}; padding: 0px 6px 0px 0px;")
        arrow.setFixedWidth(16)
        row.addWidget(arrow)
        row.addSpacing(8)
        self._diary_create_btn = self._diary_button("Create field")
        self._diary_create_btn.setEnabled(False)
        self._diary_create_btn.clicked.connect(self._diary_on_create_clicked)
        row.addWidget(self._diary_create_btn)
        self._diary_manage_btn = self._diary_button("Manage fields")
        self._diary_manage_btn.setEnabled(False)
        self._diary_manage_btn.clicked.connect(self._diary_on_manage_clicked)
        row.addWidget(self._diary_manage_btn)
        row.addStretch()
        lay.addLayout(row)
        self._diary_all_garmin = QCheckBox("Also show the Garmin fields that Garmin already delivers")
        self._diary_all_garmin.setFont(QFont("Segoe UI", 8))
        self._diary_all_garmin.setStyleSheet(f"color: {a.TEXT2};")
        self._diary_all_garmin.setEnabled(False)
        self._diary_all_garmin.toggled.connect(lambda _checked: self._diary_fill_dropdown())
        lay.addWidget(self._diary_all_garmin)
        lay.addStretch()
        return lay

    def _diary_build_right(self):
        a = self._app
        lay = QVBoxLayout()
        lay.setSpacing(6)

        self._diary_calendar = DiaryCalendar(mark_color=a.ACCENT)
        self._diary_calendar.setGridVisible(True)
        self._diary_calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._diary_calendar.setStyleSheet(
            f"QCalendarWidget {{ background: {a.BG3}; color: {a.TEXT}; }}"
            f"QCalendarWidget QToolButton {{ color: {a.TEXT}; background: {a.BG3}; }}"
            f"QCalendarWidget QAbstractItemView:enabled {{ background: {a.BG3}; color: {a.TEXT}; }}")
        self._diary_calendar.setMinimumWidth(300)
        self._diary_calendar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay.addWidget(self._diary_calendar)

        self._diary_day_label = QLabel()
        self._diary_day_label.setFont(QFont("Segoe UI", 9))
        self._diary_day_label.setStyleSheet(f"color: {a.TEXT};")
        lay.addWidget(self._diary_day_label)
        self._diary_set_day_label(self._diary_calendar.selected_date_str())
        self._diary_calendar.day_selected.connect(self._diary_on_day_selected)
        history_row = QHBoxLayout()
        self._diary_history_btn = self._diary_button("History")
        self._diary_history_btn.setEnabled(False)
        self._diary_history_btn.setToolTip("The earlier states of this day, when it was changed after the day it was "
                                           "first saved.")
        self._diary_history_btn.clicked.connect(self._diary_on_history_clicked)
        history_row.addWidget(self._diary_history_btn)
        history_row.addStretch()
        lay.addLayout(history_row)
        restore_row = QHBoxLayout()
        self._diary_restore_btn = self._diary_button("Restore from backup")
        self._diary_restore_btn.setEnabled(False)
        self._diary_restore_btn.setToolTip("Put a day or the list of fields back from its backup copy when the "
                                           "file cannot be read.")
        self._diary_restore_btn.clicked.connect(self._diary_on_restore_clicked)
        restore_row.addWidget(self._diary_restore_btn)
        restore_row.addStretch()
        lay.addLayout(restore_row)
        lay.addSpacing(6)

        lay.addWidget(self._diary_caption("Search"))
        self._diary_search = QLineEdit()
        self._diary_search.setPlaceholderText("Search notes …")
        self._diary_search.setFont(QFont("Segoe UI", 9))
        self._diary_search.setStyleSheet(
            f"QLineEdit {{ background: {a.BG3}; color: {a.TEXT}; border: none; padding: 5px 10px; }}"
            f"QLineEdit:disabled {{ color: {a.TEXT2}; }}")
        self._diary_search.setEnabled(False)
        self._diary_search_timer = QTimer(self)
        self._diary_search_timer.setSingleShot(True)
        self._diary_search_timer.setInterval(_SEARCH_DELAY_MS)
        self._diary_search_timer.timeout.connect(self._diary_run_search)
        self._diary_search.textChanged.connect(lambda _text: self._diary_search_timer.start())
        lay.addWidget(self._diary_search)
        self._diary_search_hint = QLabel()
        self._diary_search_hint.setFont(QFont("Segoe UI", 8))
        self._diary_search_hint.setStyleSheet(f"color: {a.TEXT2};")
        self._diary_search_hint.setWordWrap(True)
        lay.addWidget(self._diary_search_hint)
        self._diary_results = QListWidget()
        self._diary_results.setFont(QFont("Segoe UI", 9))
        self._diary_results.setMinimumHeight(140)
        self._diary_results.setWordWrap(True)
        self._diary_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._diary_results.setStyleSheet(
            f"QListWidget {{ background: {a.BG3}; color: {a.TEXT}; border: none; }}"
            f"QListWidget::item:hover {{ background: {a.ACCENT2}; }}")
        self._diary_results.itemClicked.connect(self._diary_on_result_clicked)
        lay.addWidget(self._diary_results)
        lay.addStretch()
        return lay

    # ── Tabs ────────────────────────────────────────

    def attach_to_tabs(self, tabs, index: int):
        """
        Called once by garmin_app_base after the tab is added. The panel watches the tab bar so that it
        can ask before the user leaves the diary tab with an unsaved note.
        """
        self._diary_tabs = tabs
        self._diary_tab_index = index
        self._diary_on_tab = tabs.currentIndex() == index
        tabs.currentChanged.connect(self._diary_on_tab_changed)

    def _diary_on_tab_changed(self, index: int):
        if index == self._diary_tab_index:
            self._diary_on_tab = True
            return
        if not self._diary_on_tab:
            return
        self._diary_on_tab = False
        if not self._diary_is_dirty():
            return
        choice = self._diary_ask_unsaved(self._diary_day)
        if choice == "discard":
            self._diary_load_day()
            return
        if choice == "save" and self._diary_save():
            return
        # Cancel, or the save did not work: stay in the diary tab with the text untouched.
        self._diary_show_tab()

    def _diary_show_tab(self):
        if self._diary_tabs is not None:
            self._diary_tabs.setCurrentIndex(self._diary_tab_index)

    def confirm_close(self) -> bool:
        """
        Called by the main window before it closes. True when it may close: nothing unsaved, or the user
        chose Save (and it worked) or Discard. False (the window stays open) on Cancel or when the save
        did not work; the diary tab is shown then, so the note and the hint are in sight.
        """
        if not self._diary_is_dirty():
            return True
        choice = self._diary_ask_unsaved(self._diary_day)
        if choice == "discard":
            return True
        if choice == "save" and self._diary_save():
            return True
        self._diary_show_tab()
        return False

    # ── Base folder, refresh ────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._diary_refresh()

    def _diary_resolve_base(self):
        """The archive folder of the Settings as a Path, or None when it is empty or not a folder."""
        try:
            settings = self._app._panel_settings._collect_settings()
            raw = str(settings.get("base_dir", "") or "").strip()
        except Exception:
            return None
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_dir() else None

    def _diary_refresh(self):
        """On every show: the archive folder, the last pickable day and the dots; the day is read again
        unless it holds an unsaved note."""
        base = self._diary_resolve_base()
        self._diary_calendar.setMaximumDate(QDate.currentDate())
        self._diary_search.setEnabled(base is not None)
        if base is not None and base != self._diary_backup_base:
            self._diary_backup_base = base
            self._diary_start_backup(base)
        if base != self._diary_base:
            self._diary_base = base
            self._diary_load_day()
        elif base is not None and not self._diary_is_dirty():
            self._diary_load_day()
        else:
            self._diary_reload_master()
            self._diary_render()
        self._diary_refresh_marks()
        self._diary_mcp_hint.setVisible(self._diary_mcp_on())

    def _diary_mcp_on(self) -> bool:
        """True while "Diary in MCP" is on — read fresh from the server-config file at every call, so a change
        made in the MCP tab counts when this tab is shown again."""
        try:
            return bool(_gcfg.read_diary_optin()[0])
        except Exception:
            return False

    def _diary_refresh_marks(self):
        days = rd.list_days(self._diary_base) if self._diary_base is not None else []
        self._diary_calendar.set_marked_days(days)
        self._diary_run_search()

    # ── Search in the notes (4e) ────────────────────

    def _diary_run_search(self):
        """The search of the box, shown in the list under it. Nothing is searched for an empty box."""
        self._diary_results.clear()
        query = self._diary_search.text()
        if self._diary_base is None or not query.strip():
            self._diary_search_hint.setText("")
            return
        res = rd.search_notes(self._diary_base, query)
        if not res["ok"]:
            self._diary_search_hint.setText("Type at least two characters." if res["reason"] == "query_too_short"
                                            else "The search text is too long.")
            return
        for hit in res["hits"]:
            item = QListWidgetItem(f"{hit['date']}   {hit['snippet']}")
            item.setData(Qt.ItemDataRole.UserRole, hit["date"])
            item.setToolTip(hit["snippet"])
            self._diary_results.addItem(item)
        count = len(res["hits"])
        if not count:
            text = f"Nothing found in {res['searched']} days."
        elif res["truncated"]:
            text = f"The newest {count} days are shown."
        else:
            text = f"{count} {'day' if count == 1 else 'days'} found."
        if res["unreadable"]:
            text += f" {res['unreadable']} days could not be read and were skipped."
        self._diary_search_hint.setText(text)

    def _diary_on_result_clicked(self, item):
        """A click on a hit goes to its day (the question about unsaved changes comes first)."""
        date_str = item.data(Qt.ItemDataRole.UserRole)
        self._diary_calendar.setSelectedDate(QDate.fromString(date_str, Qt.DateFormat.ISODate))

    # ── Day ─────────────────────────────────────────

    def selected_date(self) -> str:
        """The day chosen in the calendar, 'YYYY-MM-DD'."""
        return self._diary_calendar.selected_date_str()

    def _diary_set_day_label(self, date_str: str):
        self._diary_day_label.setText(f"Selected day: {date_str}")

    def _diary_set_status(self, text: str, warn: bool = False):
        color = self._app.YELLOW if warn else self._app.TEXT2
        self._diary_status.setStyleSheet(f"color: {color};")
        self._diary_status.setText(text)

    def _diary_collect_entries(self):
        """
        (entries, errors): the entries of the day as the entry boxes hold them. Entries of a field that has no
        row (its definition is not known) stay as they were loaded, so that nothing is lost; errors are the
        labels of the values that are not numbers.
        """
        entries = copy.deepcopy(self._diary_entries)
        errors = []
        for key, row in self._diary_rows.items():
            if row.editor is None:
                continue
            field_entries, bad = row.editor.collect()
            errors.extend(bad)
            if field_entries:
                entries[key] = field_entries
            else:
                entries.pop(key, None)
        return entries, errors

    def _diary_is_dirty(self) -> bool:
        """True while the note or an entry box holds something other than what is stored (and can be saved)."""
        if self._diary_state not in (rd.OK, rd.MISSING):
            return False
        if self._diary_note.toPlainText() != self._diary_loaded_note:
            return True
        entries, errors = self._diary_collect_entries()
        return bool(errors) or entries != self._diary_entries

    def _diary_apply_enabled(self):
        editable = self._diary_state in (rd.OK, rd.MISSING)
        self._diary_note.setEnabled(editable)
        self._diary_save_btn.setEnabled(editable)
        self._diary_delete_btn.setEnabled(self._diary_state == rd.OK)
        has_history = self._diary_state == rd.OK and self._diary_history_count > 0
        self._diary_history_btn.setEnabled(has_history)
        self._diary_history_btn.setText(f"History ({self._diary_history_count})" if has_history else "History")
        for row in self._diary_rows.values():
            if row.editor is not None:
                row.editor.set_editable(editable)

    def _diary_load_day(self):
        """Reads the day on the calendar into the widgets (a note that was typed and not saved is dropped)."""
        day = self._diary_calendar.selected_date_str()
        self._diary_day = day
        self._diary_set_day_label(day)
        self._diary_entries = {}
        self._diary_snapshot = {}
        self._diary_added = []
        self._diary_drafts = {}
        self._diary_history_ok = False
        self._diary_history_count = 0
        self._diary_loaded_note = ""
        note, status, warn = "", "", False
        if self._diary_base is None:
            self._diary_state = _NO_BASE
            status, warn = _TEXT_NO_BASE, True
        else:
            state, data = rd.read_day(self._diary_base, day)
            self._diary_state = state
            if state == rd.OK:
                note = data["note"]
                self._diary_loaded_note = note
                self._diary_entries = copy.deepcopy(data["entries"])
                self._diary_snapshot = copy.deepcopy(data["key_snapshot"])
                self._diary_history_count = len(data["history"])
            elif state == rd.DAMAGED:
                status, warn = _TEXT_DAMAGED, True
            elif state == rd.UNSUPPORTED:
                status, warn = _TEXT_UNSUPPORTED, True
        self._diary_note.setPlainText(note)
        self._diary_apply_enabled()
        self._diary_set_status(status, warn)
        self._diary_reload_master()
        self._diary_render(keep_typed=False)

    def _diary_on_day_selected(self, date_str: str):
        if self._diary_reverting or date_str == self._diary_day:
            return
        if self._diary_is_dirty():
            choice = self._diary_ask_unsaved(self._diary_day)
            if choice == "cancel" or (choice == "save" and not self._diary_save()):
                self._diary_revert_calendar()
                return
        self._diary_load_day()

    def _diary_revert_calendar(self):
        """Puts the calendar back on the day shown (after Cancel, or a save that did not work)."""
        self._diary_reverting = True
        try:
            self._diary_calendar.setSelectedDate(QDate.fromString(self._diary_day, Qt.DateFormat.ISODate))
        finally:
            self._diary_reverting = False
        self._diary_set_day_label(self._diary_day)

    # ── Save, Delete all ────────────────────────────

    def _diary_on_save_clicked(self):
        self._diary_save()

    def _diary_save(self) -> bool:
        """
        Saves the note and the entries of the day shown. True when nothing is lost (saved, nothing to save,
        or the day became empty and was removed); False when a value is not a number, the day was refused or
        the write failed (everything typed stays where it is, the status says why).
        """
        if self._diary_state not in (rd.OK, rd.MISSING):
            return False
        entries, errors = self._diary_collect_entries()
        if errors:
            self._diary_set_status(
                "Some values are not numbers (marked in red). Numbers only; a decimal comma is fine.", warn=True)
            return False
        now = self._diary_now()
        text = self._diary_note.toPlainText()
        history_before = self._diary_history_count
        res = self._diary_write_day(text, copy.deepcopy(entries), now)
        status = res["status"]
        if status == wr.WRITTEN:
            self._diary_state, self._diary_loaded_note, self._diary_entries = rd.OK, text, copy.deepcopy(entries)
            self._diary_after_save()
            kept = " The previous state is in the history." if self._diary_history_count > history_before else ""
            self._diary_set_status(f"Saved {now:%H:%M}.{kept}")
            self._diary_note_backup(bk.backup_day(self._diary_base, self._diary_day))
        elif status == wr.DELETED:
            self._diary_state, self._diary_loaded_note, self._diary_entries = rd.MISSING, "", {}
            self._diary_after_save()
            self._diary_set_status("Nothing is left on this day: it was removed.")
        elif status == wr.UNCHANGED:
            self._diary_set_status("Nothing to save.")
        elif res.get("reason") == "history_required":
            self._diary_set_status(_TEXT_NOT_SAVED, warn=True)
            return False
        else:
            self._diary_set_status(f"Could not save ({res.get('reason', status)}). The text is still in the box.",
                                   warn=True)
            return False
        self._diary_apply_enabled()
        self._diary_refresh_marks()
        return True

    def _diary_write_day(self, text, entries, now):
        """
        Writes the day shown. A day first saved on an earlier calendar day is refused by the writer unless the
        history is kept: the user is asked once for the day shown (a "no" leaves everything as it is).
        """
        args = (self._diary_base, self._diary_day, text, entries)
        res = wr.save_day(*args, now=now, keep_history=self._diary_history_ok)
        if res.get("reason") == "history_required" and self._diary_ask_history(self._diary_day):
            self._diary_history_ok = True
            res = wr.save_day(*args, now=now, keep_history=True)
        return res

    def _diary_on_history_clicked(self):
        if self._diary_state != rd.OK or self._diary_history_count == 0:
            return
        if self._diary_is_dirty():
            self._diary_set_status("Save or discard your changes first, then open the history.", warn=True)
            return
        dialog = DiaryHistoryDialog(self, self._diary_history_loader, self._diary_restore_state)
        dialog.exec()       # a restore is shown by _diary_restore_state, which loads the day again

    def _diary_history_loader(self):
        """What the history dialog reads: the earlier states of the day shown and the definitions it keeps."""
        state, data = rd.read_day(self._diary_base, self._diary_day)
        if state != rd.OK:
            return [], {}
        return copy.deepcopy(data["history"]), copy.deepcopy(data["key_snapshot"])

    def _diary_restore_state(self, index):
        """What the history dialog calls to put a state back; the day is loaded again when it was changed."""
        res = wr.restore_history(self._diary_base, self._diary_day, index, now=self._diary_now())
        if res["status"] == wr.WRITTEN:
            self._diary_load_day()
            self._diary_set_status("Restored. The state it replaced is in the history.")
            self._diary_refresh_marks()
            self._diary_note_backup(bk.backup_day(self._diary_base, self._diary_day))
        return res

    def _diary_after_save(self):
        """What was typed is stored now: the drafts go, the definitions the day keeps are read again and
        the rows are rebuilt from what is stored."""
        self._diary_drafts = {}
        state, data = rd.read_day(self._diary_base, self._diary_day)
        self._diary_snapshot = copy.deepcopy(data["key_snapshot"]) if state == rd.OK else {}
        self._diary_history_count = len(data["history"]) if state == rd.OK else 0
        self._diary_render(keep_typed=False)

    def _diary_on_delete_clicked(self):
        if self._diary_state != rd.OK or not self._diary_ask_delete(self._diary_day):
            return
        res = self._diary_write_day("", {}, self._diary_now())
        if res["status"] in (wr.WRITTEN, wr.DELETED):
            self._diary_load_day()
            self._diary_set_status(("Deleted." if res["status"] == wr.DELETED
                                    else "Deleted. The day keeps its history.")
                                   + (_TEXT_MCP_DELETED if self._diary_mcp_on() else ""))
            self._diary_refresh_marks()
            if res["status"] == wr.WRITTEN:
                self._diary_note_backup(bk.backup_day(self._diary_base, self._diary_day))
        elif res.get("reason") == "history_required":
            self._diary_set_status("Not deleted. The day is left as it is.", warn=True)
        else:
            self._diary_set_status(f"Could not delete ({res.get('reason', res['status'])}).", warn=True)

    # ── Fields (4c): the list, the dropdown, create, favorite ──────────────────

    def _diary_reload_master(self):
        if self._diary_base is None:
            self._diary_master_state, self._diary_master = _NO_BASE, None
        else:
            self._diary_master_state, self._diary_master = rd.read_master(self._diary_base)
        self._diary_update_restore_btn()

    # ── Backup (Baustein 5) ─────────────────────────

    def _diary_start_backup(self, base):
        """The backup at the start: a background thread copies what is missing or outdated (see diary_backup)."""
        def work():
            res = bk.backup_all(base)
            if not res["ok"]:
                self._app._dispatch(self._diary_backup_failed_at_start)
        threading.Thread(target=work, name="diary-backup", daemon=True).start()

    def _diary_backup_failed_at_start(self):
        self._diary_set_status(_TEXT_BACKUP_FAILED, warn=True)

    def _diary_note_backup(self, res):
        """A backup copy that could not be made is told after the text of the step it followed."""
        if not res["ok"]:
            self._diary_set_status(f"{self._diary_status.text()} {_TEXT_BACKUP_FAILED}".strip(), warn=True)

    def _diary_backup_master(self):
        self._diary_note_backup(bk.backup_master(self._diary_base))

    def _diary_restore_target(self):
        """What the restore button would put back: ("day", date), ("master", None) or None. A day that cannot be
        read comes first, then a field list that cannot be read or is missing; only with a valid copy."""
        if self._diary_base is None:
            return None
        if self._diary_state == rd.DAMAGED:
            if bk.read_valid_day_copy(self._diary_base, self._diary_day) is not None:
                return ("day", self._diary_day)
        if self._diary_master_state in (rd.DAMAGED, rd.MISSING):
            if bk.read_valid_master_copy(self._diary_base) is not None:
                return ("master", None)
        return None

    def _diary_update_restore_btn(self):
        self._diary_restore_btn.setEnabled(self._diary_restore_target() is not None)

    def _diary_on_restore_clicked(self):
        target = self._diary_restore_target()
        if target is None:
            return
        kind, day = target
        if not self._diary_ask_restore_copy(day if kind == "day" else None):
            return
        if kind == "day":
            res = wr.restore_day(self._diary_base, day, bk.read_valid_day_copy(self._diary_base, day))
        else:
            res = wr.restore_master(self._diary_base, bk.read_valid_master_copy(self._diary_base))
        if res["status"] == wr.WRITTEN:
            if kind == "day":
                self._diary_load_day()
                self._diary_refresh_marks()
            else:
                self._diary_reload_master()
                self._diary_render()
            self._diary_set_status("Restored from the backup copy. The file that could not be read is kept next to it.")
        else:
            self._diary_set_status(f"Could not restore ({res.get('reason', res['status'])}).", warn=True)

    def _diary_fields_usable(self) -> bool:
        """True when fields can be made and listed: an archive folder and a field list that is fine or not there yet."""
        return self._diary_base is not None and self._diary_master_state in (rd.OK, rd.MISSING)

    def _diary_fields(self) -> dict:
        return self._diary_master["fields"] if self._diary_master is not None else {}

    def _diary_definition_of(self, key):
        """What to show for a key: the field list first, then the snapshot of the loaded day, then the catalogue."""
        field = self._diary_fields().get(key)
        if field is not None:
            return field
        if key in self._diary_snapshot:
            return self._diary_snapshot[key]
        return cat.CATALOG.get(key)

    def _diary_shown_keys(self) -> list:
        """The fields of the list for the day shown: the favorites, the fields added from the dropdown, and the
        fields the day already has entries for."""
        shown = [key for key, field in self._diary_fields().items() if field["favorite"] and not field["archived"]]
        for key in list(self._diary_added) + list(self._diary_entries):
            if key not in shown:
                shown.append(key)
        return shown

    @staticmethod
    def _diary_value_hint(value: dict) -> str:
        if value["type"] == dm.TYPE_YESNO:
            return f"{value['label']} (yes/no)"
        if value["type"] == dm.TYPE_TEXT:
            return f"{value['label']} (text)"
        if value.get("unit"):
            return f"{value['label']} ({value['unit']})"
        return value["label"]

    @staticmethod
    def _diary_hint(defn: dict) -> str:
        """The values of a field in one line; the members of a group of alternatives are joined with "or"."""
        parts, done = [], set()
        for value in defn["values"]:
            group = value.get("group")
            if group is None:
                parts.append(PanelDiary._diary_value_hint(value))
            elif group not in done:
                done.add(group)
                members = [v for v in defn["values"] if v.get("group") == group]
                parts.append(" or ".join(PanelDiary._diary_value_hint(v) for v in members))
        return ", ".join(parts) + (" · with time" if defn["with_time"] else "")

    def _diary_render(self, keep_typed=True):
        self._diary_render_rows(keep_typed)
        self._diary_fill_dropdown()

    def _diary_default_time(self) -> str:
        """The time a new entry line starts with: now, from the panel clock."""
        return self._diary_now().strftime("%H:%M")

    def _diary_render_rows(self, keep_typed=True):
        # What was typed and not saved survives the rebuild of the rows. keep_typed=False is for a day that
        # was loaded or saved: the boxes show what is stored, and the caller has already dropped the drafts.
        if keep_typed:
            for key, row in self._diary_rows.items():
                if row.editor is not None:
                    self._diary_drafts[key] = row.editor.raw_state()
        for row in list(self._diary_rows.values()):
            self._diary_fav_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._diary_rows = {}
        editable = self._diary_state in (rd.OK, rd.MISSING)
        for key in self._diary_shown_keys():
            defn = self._diary_definition_of(key)
            if defn is None:
                continue
            field = self._diary_fields().get(key)
            favorite = bool(field and field["favorite"])
            row = DiaryFieldRow(self._app, key, defn["name"], self._diary_hint(defn), favorite,
                                can_toggle=field is not None and self._diary_fields_usable(),
                                can_remove=not favorite and key not in self._diary_entries,
                                defn=defn, entries=self._diary_entries.get(key, []),
                                default_time=self._diary_default_time)
            if key in self._diary_drafts:
                row.editor.set_raw_state(self._diary_drafts[key])
            row.editor.set_editable(editable)
            row.favorite_toggled.connect(self._diary_on_favorite_toggled)
            row.remove_requested.connect(self._diary_on_row_remove)
            self._diary_fav_lay.addWidget(row)
            self._diary_rows[key] = row
        if self._diary_base is None:
            hint = "Set the archive folder in Settings to use fields."
        elif self._diary_master_state in (rd.DAMAGED, rd.UNSUPPORTED):
            hint = "The list of fields cannot be read. It is left untouched."
        elif not self._diary_rows:
            hint = "Your favorite fields appear here, one row per field. Create a field or add one from the list."
        else:
            hint = ""
        self._diary_favorites_hint.setText(hint)
        self._diary_favorites_hint.setVisible(bool(hint))

    def _diary_delivered_endpoints(self) -> set:
        """
        The Garmin endpoints the sync already delivers for this archive: found by the capability scan and
        switched on by the user (the same double gate as the sync, garmin_api_capability.get_enabled_candidates).
        An empty set when the file is missing or cannot be read: every Garmin field is offered then.
        """
        if self._diary_base is None:
            return set()
        path = self._diary_base / "garmin_data" / "log" / "garmin_api_capability_config.json"
        try:
            import garmin_api_capability as capability
            config = json.loads(path.read_text(encoding="utf-8"))
            return set(capability.get_enabled_candidates(config))
        except Exception:
            return set()

    def _diary_fill_dropdown(self):
        """
        'Add field …', then 'Your fields' (Set 2 fields of the list that are not shown) and 'Garmin fields' (the
        Set 1 catalogue). A Garmin field that Garmin already delivers is left out unless the checkbox asks for
        all of them.
        """
        combo = self._diary_field_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Add field …")
        usable = self._diary_fields_usable()
        if usable:
            shown = set(self._diary_shown_keys())
            own = [(k, f["name"]) for k, f in self._diary_fields().items()
                   if dm.is_user_key(k) and not f["archived"] and k not in shown]
            if own:
                self._diary_add_header("Your fields")
                for key, name in own:
                    combo.addItem(name, key)
            taken = {dm.normalized_name(f["name"]) for f in self._diary_fields().values()}
            templates = [t for t in cat.templates() if dm.normalized_name(t["name"]) not in taken]
            if templates:
                self._diary_add_header("Start templates")
                for template in templates:
                    combo.addItem(template["name"], _TEMPLATE_PREFIX + template["name"])
            delivered = self._diary_delivered_endpoints()
            show_all = self._diary_all_garmin.isChecked()
            garmin = []
            for key in cat.keys():
                field = self._diary_fields().get(key)
                if key in shown or (field is not None and field["archived"]):
                    continue
                is_delivered = cat.CATALOG[key]["maps_to"] in delivered
                if is_delivered and not show_all:
                    continue
                name = field["name"] if field is not None else cat.CATALOG[key]["name"]
                garmin.append((key, name + (" (Garmin delivers this)" if is_delivered else "")))
            if garmin:
                self._diary_add_header("Garmin fields")
                for key, label in garmin:
                    combo.addItem(label, key)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        combo.setEnabled(usable)
        self._diary_all_garmin.setEnabled(usable)
        self._diary_create_btn.setEnabled(usable)
        self._diary_manage_btn.setEnabled(usable)

    def _diary_add_header(self, text: str):
        combo = self._diary_field_combo
        combo.addItem(f"— {text} —")
        combo.model().item(combo.count() - 1).setEnabled(False)

    def _diary_on_field_chosen(self, index: int):
        key = self._diary_field_combo.itemData(index)
        if not key:
            return
        if key.startswith(_TEMPLATE_PREFIX):
            self._diary_create_from_template(key[len(_TEMPLATE_PREFIX):])
            return
        if dm.is_garmin_key(key) and key not in self._diary_fields():
            res = wr.activate_catalog_field(self._diary_base, key)
            if res["status"] not in (wr.WRITTEN, wr.UNCHANGED):
                self._diary_set_status(f"Could not add the field ({res.get('reason', res['status'])}).", warn=True)
                self._diary_fill_dropdown()
                return
            self._diary_reload_master()
            self._diary_backup_master()
        if key not in self._diary_added:
            self._diary_added.append(key)
        self._diary_render()

    def _diary_row_has_content(self, key: str) -> bool:
        row = self._diary_rows.get(key)
        return row is not None and row.editor is not None and row.editor.has_content()

    def _diary_on_row_remove(self, key: str):
        if self._diary_row_has_content(key):
            self._diary_set_status("This field has values you typed. Take them out first.", warn=True)
            return
        if key in self._diary_added:
            self._diary_added.remove(key)
        self._diary_drafts.pop(key, None)
        self._diary_render()

    def _diary_on_favorite_toggled(self, key: str):
        field = self._diary_fields().get(key)
        if field is None or not self._diary_fields_usable():
            return
        res = wr.set_flags(self._diary_base, key, favorite=not field["favorite"])
        if res["status"] not in (wr.WRITTEN, wr.UNCHANGED):
            self._diary_set_status(f"Could not change the favorite ({res.get('reason', res['status'])}).", warn=True)
            return
        if self._diary_row_has_content(key) and key not in self._diary_added:
            self._diary_added.append(key)       # the row stays: values were typed in it
        self._diary_reload_master()
        self._diary_render()
        self._diary_backup_master()

    def _diary_on_create_clicked(self):
        if not self._diary_fields_usable():
            return
        dialog = DiaryFieldDialog(self, self._diary_create_field)
        dialog.exec()
        if dialog.created_key:
            self._diary_reload_master()
            if dialog.created_key not in self._diary_added:
                self._diary_added.append(dialog.created_key)
            self._diary_render()
            self._diary_set_status("Field created.")

    def _diary_create_from_template(self, name):
        """A start template was chosen: makes a normal user field from it and shows it for the day."""
        template = next((t for t in cat.templates() if t["name"] == name), None)
        if template is None:
            return
        res = wr.create_user_field(self._diary_base, template["name"], template["values"], template["with_time"])
        if res["status"] != wr.WRITTEN:
            self._diary_set_status(describe_failure(res), warn=True)
            self._diary_reload_master()
            self._diary_render()
            return
        self._diary_reload_master()
        if res["key"] not in self._diary_added:
            self._diary_added.append(res["key"])
        self._diary_render()
        self._diary_set_status(f"Field {template['name']} created from the template.")
        self._diary_backup_master()

    def _diary_on_manage_clicked(self):
        if not self._diary_fields_usable():
            return
        dialog = DiaryManageDialog(self, self._diary_fields, self._diary_rename_field, self._diary_archive_field)
        dialog.exec()       # every change is shown by the functions handed in (rename, archive)

    def _diary_rename_field(self, key, new_name):
        """What the manage dialog calls to rename: through the writer, then the rows show the new name."""
        res = wr.rename_field(self._diary_base, key, new_name)
        if res["status"] == wr.WRITTEN:
            self._diary_reload_master()
            self._diary_render()
            self._diary_backup_master()
        return res

    def _diary_archive_field(self, key, archived):
        """What the manage dialog calls to archive or restore. A field with values typed and not saved on the
        day shown is not archived (its row would disappear with the typed values)."""
        if archived and self._diary_row_has_content(key):
            return {"status": wr.REJECTED, "reason": "typed_values"}
        res = wr.set_flags(self._diary_base, key, archived=archived)
        if res["status"] == wr.WRITTEN:
            if archived:
                if key in self._diary_added:
                    self._diary_added.remove(key)
            self._diary_reload_master()
            self._diary_render()
            self._diary_backup_master()
        return res

    def _diary_create_field(self, name, values, with_time, favorite):
        """What the dialog calls: makes the field through the writer and, if asked, a favorite."""
        res = wr.create_user_field(self._diary_base, name, values, with_time)
        if res["status"] == wr.WRITTEN and favorite:
            wr.set_flags(self._diary_base, res["key"], favorite=True)
        if res["status"] == wr.WRITTEN:
            self._diary_backup_master()
        return res

    # ── Questions (a test replaces them) ────────────

    def _diary_ask_unsaved(self, day: str) -> str:
        """'save', 'discard' or 'cancel'. Says that the changes are lost if the user does not save."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"The note of {day} has not been saved.")
        box.setInformativeText("If you leave without saving, the changes are lost.")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            return "save"
        if clicked is discard_btn:
            return "discard"
        return "cancel"

    def _diary_ask_history(self, day: str) -> bool:
        """True when the user agrees that the day, which was first saved on an earlier day, keeps its history."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Change an earlier day")
        box.setText(f"{day} was first saved on an earlier day.")
        box.setInformativeText("If you save, the state it has now is kept in its history and can be put back.")
        save_btn = box.addButton("Save and keep history", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()
        return box.clickedButton() is save_btn

    def _diary_ask_restore_copy(self, day) -> bool:
        """True when the user agrees to put a day (or, with day None, the list of fields) back from its backup copy."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Restore from backup")
        box.setText(f"Restore {'the day ' + day if day else 'the list of fields'} from its backup copy?")
        box.setInformativeText("The file that cannot be read is kept next to it (.damaged).")
        restore_btn = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore_btn)
        box.exec()
        return box.clickedButton() is restore_btn

    def _diary_ask_delete(self, day: str) -> bool:
        """True when the user confirms to delete the note and all entries of the day."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete all")
        box.setText(f"Delete the note and all entries of {day}?")
        box.setInformativeText("This cannot be undone. A copy of the day in the backup is kept."
                               + (_TEXT_MCP_DELETED if self._diary_mcp_on() else ""))
        delete_btn = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        return box.clickedButton() is delete_btn
