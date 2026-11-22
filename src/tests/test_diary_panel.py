#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_diary_panel.py
Garmin Local Archive — Diary panel (Tab "Diary")
DIARY v1.7.8 — removable (the panel is src/app/panel_diary.py).

Run with:
    pytest tests/test_diary_panel.py -v

Step 4a (layout, calendar) and 4b (the note of a day): the calendar picks a day and does not go into the
future, the day is loaded and saved through the diary package, the entries a day already has survive a
save of the note, a day that is older than its edit window is refused with a hint, a damaged day is left
alone, "Delete all" empties a day, dots mark the days with a file, leaving a day or the tab with an
unsaved note asks first, an empty or missing archive folder disables everything, and the tab sits behind
"MCP Server" in the real window. Panel-level tests use a MagicMock app (like TestPanelChat in
test_qt_app.py) and a temporary archive folder; the window-level test builds the real GarminApp once.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QDate, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QLabel, QLineEdit, QMessageBox, QScrollArea, QTabWidget, QWidget,
)

from app.dialog_diary_field import DiaryFieldDialog, describe_failure
from app.dialog_diary_history import DiaryHistoryDialog, describe_state, summarize_state
from app.dialog_diary_manage import DiaryManageDialog
from app.diary_entry_editor import clean_text, parse_number
from diary import diary_backup as bk
from diary import diary_reader as rd
from diary import diary_writer as wr

_SETTINGS = {
    "email": "", "password": "", "base_dir": "",
    "sync_mode": "recent", "sync_days": "90",
    "sync_from": "", "sync_to": "", "sync_auto_fallback": "",
    "date_from": "", "date_to": "", "age": "35", "sex": "male",
    "request_delay_min": "5.0", "request_delay_max": "20.0",
    "context_latitude": "0.0", "context_longitude": "0.0",
    "context_location": "", "mirror_dir": "",
    "timer_min_interval": "5", "timer_max_interval": "30",
    "timer_min_days": "3", "timer_max_days": "10",
    "backup_raw_backfill_asked": False,
}

TABLET = [{"label": "Anzahl", "type": "number", "unit": "Stück"}]


@pytest.fixture(autouse=True)
def _no_diary_switch(monkeypatch):
    """Hermetic (v1.7.8.1): the switch "Diary in MCP" never comes from the real ~/.garmin_mcp_server_config.json,
    and does not leak into other test files of the same pytest session (monkeypatch undoes it)."""
    monkeypatch.setenv("GARMIN_MCP_DIARY_ENABLED", "0")


def _iso(delta_days=0):
    return QDate.currentDate().addDays(delta_days).toString(Qt.DateFormat.ISODate)


def _pick(panel, iso):
    panel._diary_calendar.setSelectedDate(QDate.fromString(iso, Qt.DateFormat.ISODate))


def _write(base, iso, note, entries=None, now=None):
    res = wr.save_day(base, iso, note, entries or {}, now=now or datetime.now())
    assert res["status"] == "written", res
    return res


def _day_path(base, iso):
    return Path(base) / "diary_data" / "days" / f"diary_{iso}.json"


def _make_field(base):
    res = wr.create_user_field(base, "Schmerztablette", TABLET, True)
    assert res["status"] == "written", res
    return res["key"]


@pytest.fixture
def base(tmp_path):
    return tmp_path


@pytest.fixture
def app_mock(base):
    app = MagicMock()
    app.BG = "#12101f"
    app.BG2 = "#1a1729"
    app.BG3 = "#231f38"
    app.ACCENT = "#a259f7"
    app.ACCENT2 = "#6e3fcf"
    app.TEXT = "#eaeaea"
    app.TEXT2 = "#a0a0b0"
    app.YELLOW = "#f5a623"
    app._panel_settings._collect_settings.return_value = {"base_dir": str(base)}
    return app


@pytest.fixture
def raw_panel(qtbot, app_mock):
    from app.panel_diary import PanelDiary
    widget = PanelDiary(app_mock)
    qtbot.addWidget(widget)
    widget._diary_ask_history = lambda day: False       # no real question window in a test; 4f tests answer it themselves
    widget._diary_start_backup = lambda base: None       # no background thread in a test; the backup tests start it themselves
    return widget


@pytest.fixture
def panel(raw_panel):
    """A panel as it is after it was shown once: the archive folder is read, the day on the calendar loaded."""
    raw_panel._diary_refresh()
    return raw_panel


def _never(*args, **kwargs):
    raise AssertionError("the panel asked a question it should not have asked")


def _label_texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def _click_box_button_later(text, seen=None, delay=150):
    """Clicks the button 'text' of the next QMessageBox that opens; a watchdog closes it if that fails."""
    done = []

    def _click():
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                if seen is not None:
                    seen["title"], seen["text"], seen["info"] = (
                        widget.windowTitle(), widget.text(), widget.informativeText())
                for button in widget.buttons():
                    if button.text() == text:
                        done.append(True)
                        button.click()
                        return

    def _watchdog():
        if done:
            return          # the box was answered; a late watchdog must not close the box of a later test
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                widget.reject()

    QTimer.singleShot(delay, _click)
    QTimer.singleShot(4000, _watchdog)


# ══════════════════════════════════════════════════════════════════════════════
#  Layout and calendar (step 4a)
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelLayout:

    def test_panel_instantiates(self, raw_panel):
        assert raw_panel is not None

    def test_the_areas_of_the_sketch_exist(self, raw_panel):
        for attr in ("_diary_note", "_diary_save_btn", "_diary_delete_btn", "_diary_status", "_diary_favorites",
                     "_diary_field_combo", "_diary_create_btn", "_diary_calendar", "_diary_day_label",
                     "_diary_search"):
            assert hasattr(raw_panel, attr), f"missing: {attr}"

    def test_heading_and_captions(self, raw_panel):
        texts = _label_texts(raw_panel)
        for expected in ("Diary", "Note", "Favorites", "Search"):
            assert expected in texts, f"missing caption: {expected}"

    def test_the_dropdown_offers_add_field(self, raw_panel):
        assert raw_panel._diary_field_combo.count() == 1
        assert raw_panel._diary_field_combo.itemText(0) == "Add field …"

    def test_the_buttons_are_labelled(self, raw_panel):
        assert raw_panel._diary_create_btn.text() == "Create field"
        assert raw_panel._diary_save_btn.text() == "Save"
        assert raw_panel._diary_delete_btn.text() == "Delete all"

    def test_the_search_works_with_an_archive_folder(self, panel):
        assert panel._diary_search.isEnabled() and panel._diary_results.count() == 0

    def test_with_a_folder_the_field_controls_are_enabled(self, panel):
        for attr in ("_diary_field_combo", "_diary_create_btn", "_diary_all_garmin"):
            assert getattr(panel, attr).isEnabled(), f"{attr} must work with an archive folder"

    def test_the_calendar_starts_on_today(self, raw_panel):
        assert raw_panel.selected_date() == _iso()
        assert raw_panel._diary_day_label.text() == f"Selected day: {_iso()}"

    def test_the_label_follows_the_calendar(self, panel):
        _pick(panel, _iso(-3))
        assert panel.selected_date() == _iso(-3)
        assert panel._diary_day_label.text() == f"Selected day: {_iso(-3)}"

    def test_picking_a_day_emits_day_selected_with_the_date(self, qtbot, panel):
        with qtbot.waitSignal(panel._diary_calendar.day_selected, timeout=2000) as blocker:
            _pick(panel, _iso(-5))
        assert blocker.args == [_iso(-5)]

    def test_the_same_day_again_changes_nothing(self, panel):
        # The promise of the panel, not of Qt: whether QCalendarWidget sends selectionChanged for the day that is
        # already selected depends on the Qt patch release (CI with Qt 6.11.2 did, 6.11.1 does not), so the signal
        # is not asserted. What counts: no question about an unsaved note, no reload, the text stays.
        panel._diary_note.setPlainText("noch nicht gespeichert")
        panel._diary_ask_unsaved = _never
        panel._diary_calendar.setSelectedDate(panel._diary_calendar.selectedDate())
        assert panel.selected_date() == _iso() and panel._diary_day == _iso()
        assert panel._diary_note.toPlainText() == "noch nicht gespeichert"
        assert panel._diary_is_dirty()

    def test_a_leap_day_is_kept_as_iso(self, panel):
        panel._diary_calendar.setSelectedDate(QDate(2024, 2, 29))
        assert panel.selected_date() == "2024-02-29"

    def test_the_calendar_shows_english_day_names_from_monday_whatever_the_system_language(self, qtbot):
        # v1.7.8.1: the calendar derives from EnglishCalendar; the default locale is German here on purpose
        from PyQt6.QtCore import QLocale
        from PyQt6.QtWidgets import QCalendarWidget, QTableView
        from app.dialog_force_refetch import EnglishCalendar
        from app.panel_diary import DiaryCalendar
        before = QLocale()
        QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
        try:
            cal = DiaryCalendar()
            qtbot.addWidget(cal)
            cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
            model = cal.findChild(QTableView).model()
            header = [str(model.index(0, c).data()) for c in range(model.columnCount())]
        finally:
            QLocale.setDefault(before)
        assert issubclass(DiaryCalendar, EnglishCalendar)
        assert header == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        assert cal.firstDayOfWeek() == Qt.DayOfWeek.Monday

    def test_future_days_cannot_be_picked(self, panel):
        assert panel._diary_calendar.maximumDate() == QDate.currentDate()
        _pick(panel, _iso(3))
        assert panel.selected_date() <= _iso()

    def test_the_last_pickable_day_follows_the_date_when_the_tab_is_shown_again(self, panel):
        panel._diary_calendar.setMaximumDate(QDate.currentDate().addDays(-10))
        panel._diary_refresh()
        assert panel._diary_calendar.maximumDate() == QDate.currentDate()


# ══════════════════════════════════════════════════════════════════════════════
#  The archive folder
# ══════════════════════════════════════════════════════════════════════════════

class TestArchiveFolder:

    def test_building_the_panel_reads_nothing(self, raw_panel, app_mock, base):
        app_mock._panel_settings._collect_settings.assert_not_called()
        assert list(base.iterdir()) == []
        assert not raw_panel._diary_note.isEnabled()

    def test_showing_the_panel_reads_the_archive_folder(self, raw_panel, base):
        _write(base, _iso(), "heute")
        assert not raw_panel._diary_note.isEnabled()
        raw_panel.show()
        assert raw_panel._diary_note.isEnabled()
        assert raw_panel._diary_note.toPlainText() == "heute"
        assert raw_panel._diary_calendar.is_marked(_iso())

    def test_with_a_folder_the_note_is_enabled(self, panel):
        assert panel._diary_note.isEnabled() and panel._diary_save_btn.isEnabled()
        assert not panel._diary_delete_btn.isEnabled(), "nothing stored for the day yet"
        assert panel._diary_status.text() == ""

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_an_empty_folder_disables_everything(self, raw_panel, app_mock, value):
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": value}
        raw_panel._diary_refresh()
        assert not raw_panel._diary_note.isEnabled()
        assert not raw_panel._diary_save_btn.isEnabled()
        assert not raw_panel._diary_delete_btn.isEnabled()
        assert "Archive folder" in raw_panel._diary_status.text()

    def test_a_folder_that_does_not_exist_is_not_made(self, raw_panel, app_mock, base):
        missing = base / "no_such_archive"
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": str(missing)}
        raw_panel._diary_refresh()
        assert not raw_panel._diary_note.isEnabled()
        assert not missing.exists()

    def test_a_file_instead_of_a_folder_disables_everything(self, raw_panel, app_mock, base):
        a_file = base / "file.txt"
        a_file.write_text("x", encoding="utf-8")
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": str(a_file)}
        raw_panel._diary_refresh()
        assert not raw_panel._diary_note.isEnabled()

    def test_settings_that_cannot_be_read_disable_everything(self, raw_panel, app_mock):
        app_mock._panel_settings._collect_settings.side_effect = RuntimeError("not ready")
        raw_panel._diary_refresh()
        assert not raw_panel._diary_note.isEnabled()

    def test_loading_and_picking_days_writes_nothing(self, panel, base):
        for delta in (-1, -2, -3):
            _pick(panel, _iso(delta))
        panel._diary_refresh()
        assert not (base / "diary_data").exists()

    def test_a_new_folder_is_picked_up_when_the_panel_is_shown_again(self, panel, app_mock, tmp_path_factory):
        other = tmp_path_factory.mktemp("other_archive")
        _write(other, _iso(-1), "in the other archive")
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": str(other)}
        _pick(panel, _iso(-1))
        panel._diary_refresh()
        assert panel._diary_note.toPlainText() == "in the other archive"
        assert panel._diary_calendar.is_marked(_iso(-1))


# ══════════════════════════════════════════════════════════════════════════════
#  Load and save the note
# ══════════════════════════════════════════════════════════════════════════════

class TestNote:

    def test_a_day_with_no_file_has_an_empty_note(self, panel):
        assert panel._diary_note.toPlainText() == ""
        assert panel._diary_state == rd.MISSING

    def test_a_stored_note_is_loaded_when_the_day_is_picked(self, panel, base):
        _write(base, _iso(-2), "Hotelbett unbequem")
        panel._diary_refresh()
        _pick(panel, _iso(-2))
        assert panel._diary_note.toPlainText() == "Hotelbett unbequem"
        assert panel._diary_state == rd.OK
        assert panel._diary_delete_btn.isEnabled()

    def test_saving_a_new_note_writes_the_day(self, qtbot, panel, base):
        panel._diary_note.setPlainText("erste Notiz")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        state, day = rd.read_day(base, _iso())
        assert state == rd.OK and day["note"] == "erste Notiz"
        assert panel._diary_status.text().startswith("Saved ")
        assert not panel._diary_is_dirty()
        assert panel._diary_delete_btn.isEnabled()

    def test_the_created_time_comes_from_the_panel_clock(self, qtbot, panel, base):
        panel._diary_now = lambda: datetime(2026, 11, 18, 9, 30)
        _pick(panel, "2026-11-10")
        panel._diary_note.setPlainText("nachgetragen")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, "2026-11-10")[1]["created"] == "2026-11-18T09:30:00"
        assert "09:30" in panel._diary_status.text()

    def test_saving_again_without_a_change_says_so(self, qtbot, panel, base):
        _write(base, _iso(-1), "gleich")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        before = _day_path(base, _iso(-1)).read_bytes()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_status.text() == "Nothing to save."
        assert _day_path(base, _iso(-1)).read_bytes() == before

    def test_an_edit_of_a_stored_note_is_saved(self, qtbot, panel, base):
        _write(base, _iso(-1), "alt")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("neu")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso(-1))[1]["note"] == "neu"

    def test_the_entries_of_a_day_survive_a_save_of_the_note(self, qtbot, panel, base):
        key = _make_field(base)
        entries = {key: [{"time": "14:05", "values": {"Anzahl": 1}}]}
        _write(base, _iso(-1), "alt", entries)
        stored = rd.read_day(base, _iso(-1))[1]
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("neue Notiz")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        after = rd.read_day(base, _iso(-1))[1]
        assert after["note"] == "neue Notiz"
        assert after["entries"] == entries
        assert after["key_snapshot"] == stored["key_snapshot"]
        assert after["created"] == stored["created"]

    def test_emptying_a_note_only_day_removes_it(self, qtbot, panel, base):
        _write(base, _iso(-1), "nur Notiz")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert not _day_path(base, _iso(-1)).exists()
        assert panel._diary_state == rd.MISSING
        assert not panel._diary_calendar.is_marked(_iso(-1))
        assert "removed" in panel._diary_status.text()

    def test_emptying_the_note_of_a_day_with_entries_keeps_the_day(self, qtbot, panel, base):
        key = _make_field(base)
        entries = {key: [{"time": "14:05", "values": {"Anzahl": 1}}]}
        _write(base, _iso(-1), "Notiz", entries)
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        state, day = rd.read_day(base, _iso(-1))
        assert state == rd.OK and day["note"] == "" and day["entries"] == entries

    def test_a_day_saved_on_an_earlier_day_is_refused_with_a_hint(self, qtbot, panel, base):
        yesterday = datetime.now() - timedelta(days=1)
        _write(base, _iso(-1), "gestern gespeichert", now=yesterday)
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        stored = _day_path(base, _iso(-1)).read_bytes()
        panel._diary_note.setPlainText("heute geändert")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert "Not saved" in panel._diary_status.text()
        assert _day_path(base, _iso(-1)).read_bytes() == stored
        assert panel._diary_note.toPlainText() == "heute geändert", "the typed text must stay"
        assert panel._diary_is_dirty()

    def test_a_damaged_day_is_left_alone(self, panel, base):
        path = _day_path(base, _iso(-2))
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")
        _pick(panel, _iso(-2))
        assert not panel._diary_note.isEnabled() and not panel._diary_save_btn.isEnabled()
        assert "cannot be read" in panel._diary_status.text()
        assert path.read_text(encoding="utf-8") == "{ not json"

    def test_a_day_of_a_newer_version_is_left_alone(self, panel, base):
        path = _day_path(base, _iso(-2))
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        _pick(panel, _iso(-2))
        assert not panel._diary_note.isEnabled()
        assert "newer version" in panel._diary_status.text()

    def test_saving_a_day_that_cannot_be_saved_is_refused(self, panel):
        panel._diary_state = rd.DAMAGED
        assert panel._diary_save() is False

    def test_a_failed_write_keeps_the_text_and_says_so(self, qtbot, panel, base):
        panel._diary_note.setPlainText("wichtig")
        with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
            qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert "Could not save" in panel._diary_status.text()
        assert panel._diary_note.toPlainText() == "wichtig"
        assert not _day_path(base, _iso()).exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Marks in the calendar
# ══════════════════════════════════════════════════════════════════════════════

class TestMarks:

    def test_days_with_a_file_are_marked(self, panel, base):
        _write(base, _iso(-1), "a")
        _write(base, _iso(-4), "b")
        panel._diary_refresh()
        assert panel._diary_calendar.is_marked(_iso(-1)) and panel._diary_calendar.is_marked(_iso(-4))
        assert not panel._diary_calendar.is_marked(_iso(-2))

    def test_a_saved_day_gets_its_mark_at_once(self, qtbot, panel):
        assert not panel._diary_calendar.is_marked(_iso())
        panel._diary_note.setPlainText("x")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_calendar.is_marked(_iso())

    def test_the_marks_are_replaced_not_added_to(self, panel):
        panel._diary_calendar.set_marked_days(["2026-01-01"])
        panel._diary_calendar.set_marked_days(["2026-02-02"])
        assert not panel._diary_calendar.is_marked("2026-01-01") and panel._diary_calendar.is_marked("2026-02-02")

    def test_painting_a_marked_calendar_works(self, panel, base):
        _write(base, _iso(-1), "a")
        panel._diary_refresh()
        panel._diary_calendar.resize(320, 240)
        image = panel._diary_calendar.grab().toImage()
        assert not image.isNull()

    def test_a_marked_day_is_painted_differently(self, panel):
        panel._diary_calendar.resize(320, 240)
        plain = panel._diary_calendar.grab().toImage()
        panel._diary_calendar.set_marked_days([_iso()])
        marked = panel._diary_calendar.grab().toImage()
        assert plain != marked, "the dot must show"

    def test_without_a_folder_there_are_no_marks(self, raw_panel, app_mock):
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_calendar.set_marked_days([_iso(-1)])
        raw_panel._diary_refresh()
        assert not raw_panel._diary_calendar.is_marked(_iso(-1))


# ══════════════════════════════════════════════════════════════════════════════
#  Delete all
# ══════════════════════════════════════════════════════════════════════════════

class TestMcpHint:
    """v1.7.8.1: the hint that a change reaches the MCP cache only at its next update — shown only while the
    switch "Diary in MCP" is on (the switch is read fresh from the server-config file or the ENV)."""

    def test_the_hint_is_hidden_while_the_switch_is_off(self, panel):
        panel._diary_refresh()
        assert not panel._diary_mcp_hint.isVisibleTo(panel)

    def test_the_hint_shows_when_the_switch_is_on_and_goes_when_it_is_off_again(self, panel, monkeypatch):
        monkeypatch.setenv("GARMIN_MCP_DIARY_ENABLED", "1")
        panel._diary_refresh()
        assert panel._diary_mcp_hint.isVisibleTo(panel)
        assert "next server start, refresh or export" in panel._diary_mcp_hint.text()
        monkeypatch.setenv("GARMIN_MCP_DIARY_ENABLED", "0")
        panel._diary_refresh()
        assert not panel._diary_mcp_hint.isVisibleTo(panel)

    def test_deleting_with_the_switch_on_says_the_cache_still_has_the_day(self, qtbot, panel, base, monkeypatch):
        _write(base, _iso(-1), "Notiz")
        monkeypatch.setenv("GARMIN_MCP_DIARY_ENABLED", "1")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_status.text().startswith("Deleted.")
        assert "MCP cache still shows the day until its next update" in panel._diary_status.text()

    def test_deleting_with_the_switch_off_says_nothing_about_the_cache(self, qtbot, panel, base):
        _write(base, _iso(-1), "Notiz")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_status.text() == "Deleted."

    def test_the_delete_question_names_the_cache_only_with_the_switch_on(self, panel, monkeypatch):
        seen = []

        class _Box:
            Icon = QMessageBox.Icon
            ButtonRole = QMessageBox.ButtonRole

            def __init__(self, parent=None):
                self.buttons = []

            def setIcon(self, icon): pass
            def setWindowTitle(self, text): pass
            def setText(self, text): pass
            def setInformativeText(self, text): seen.append(text)
            def addButton(self, text, role):
                self.buttons.append(text)
                return text
            def setDefaultButton(self, button): pass
            def exec(self): pass
            def clickedButton(self): return "Cancel"

        with patch("app.panel_diary.QMessageBox", _Box):
            panel._diary_ask_delete("2026-11-01")
            monkeypatch.setenv("GARMIN_MCP_DIARY_ENABLED", "1")
            panel._diary_ask_delete("2026-11-01")
        assert "MCP cache" not in seen[0] and "MCP cache still shows the day" in seen[1]


class TestDeleteAll:

    def test_it_is_off_for_a_day_with_nothing_stored(self, panel):
        assert not panel._diary_delete_btn.isEnabled()

    def test_confirming_removes_the_day(self, qtbot, panel, base):
        key = _make_field(base)
        _write(base, _iso(-1), "Notiz", {key: [{"time": "14:05", "values": {"Anzahl": 2}}]})
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert not _day_path(base, _iso(-1)).exists()
        assert panel._diary_note.toPlainText() == "" and panel._diary_state == rd.MISSING
        assert not panel._diary_calendar.is_marked(_iso(-1))
        assert panel._diary_status.text() == "Deleted."
        assert not panel._diary_delete_btn.isEnabled()

    def test_the_question_names_the_day(self, qtbot, panel, base):
        _write(base, _iso(-1), "Notiz")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        asked = []
        panel._diary_ask_delete = lambda day: asked.append(day) or False
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert asked == [_iso(-1)]

    def test_declining_changes_nothing(self, qtbot, panel, base):
        _write(base, _iso(-1), "Notiz")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        stored = _day_path(base, _iso(-1)).read_bytes()
        panel._diary_ask_delete = lambda day: False
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert _day_path(base, _iso(-1)).read_bytes() == stored
        assert panel._diary_note.toPlainText() == "Notiz"

    def test_a_day_saved_on_an_earlier_day_is_not_deleted(self, qtbot, panel, base):
        _write(base, _iso(-1), "alt", now=datetime.now() - timedelta(days=1))
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert _day_path(base, _iso(-1)).is_file()
        assert "Not deleted" in panel._diary_status.text()

    def test_it_drops_an_unsaved_text_too(self, qtbot, panel, base):
        _write(base, _iso(-1), "Notiz")
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("noch nicht gespeichert")
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_note.toPlainText() == "" and not _day_path(base, _iso(-1)).exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Leaving a day or the tab with an unsaved note
# ══════════════════════════════════════════════════════════════════════════════

class TestUnsavedNote:

    def test_typing_makes_the_day_dirty_and_saving_clears_it(self, qtbot, panel):
        assert not panel._diary_is_dirty()
        panel._diary_note.setPlainText("x")
        assert panel._diary_is_dirty()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert not panel._diary_is_dirty()

    def test_nothing_is_asked_when_nothing_changed(self, panel):
        panel._diary_ask_unsaved = _never
        _pick(panel, _iso(-1))
        assert panel.selected_date() == _iso(-1)

    def test_cancel_stays_on_the_day_and_keeps_the_text(self, panel):
        panel._diary_note.setPlainText("nicht verlieren")
        panel._diary_ask_unsaved = lambda day: "cancel"
        _pick(panel, _iso(-1))
        assert panel.selected_date() == _iso() and panel._diary_day == _iso()
        assert panel._diary_note.toPlainText() == "nicht verlieren"
        assert panel._diary_day_label.text() == f"Selected day: {_iso()}"

    def test_discard_goes_to_the_other_day_and_drops_the_text(self, panel, base):
        _write(base, _iso(-1), "gestern")
        panel._diary_refresh()
        panel._diary_note.setPlainText("verwerfen")
        panel._diary_ask_unsaved = lambda day: "discard"
        _pick(panel, _iso(-1))
        assert panel._diary_note.toPlainText() == "gestern"
        assert not _day_path(base, _iso()).exists()

    def test_save_writes_the_day_and_goes_on(self, panel, base):
        panel._diary_note.setPlainText("sichern")
        panel._diary_ask_unsaved = lambda day: "save"
        _pick(panel, _iso(-1))
        assert rd.read_day(base, _iso())[1]["note"] == "sichern"
        assert panel.selected_date() == _iso(-1) and panel._diary_day == _iso(-1)
        assert panel._diary_note.toPlainText() == ""

    def test_the_question_names_the_day_that_is_left(self, panel):
        panel._diary_note.setPlainText("x")
        asked = []
        panel._diary_ask_unsaved = lambda day: asked.append(day) or "cancel"
        _pick(panel, _iso(-1))
        assert asked == [_iso()]

    def test_a_save_that_is_refused_keeps_the_user_on_the_day(self, panel, base):
        _write(base, _iso(-1), "alt", now=datetime.now() - timedelta(days=1))
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("geändert")
        panel._diary_ask_unsaved = lambda day: "save"
        _pick(panel, _iso(-2))
        assert panel.selected_date() == _iso(-1) and panel._diary_day == _iso(-1)
        assert panel._diary_note.toPlainText() == "geändert"
        assert "Not saved" in panel._diary_status.text()

    def test_showing_the_tab_again_keeps_an_unsaved_text(self, panel):
        panel._diary_note.setPlainText("bleibt")
        panel._diary_refresh()
        assert panel._diary_note.toPlainText() == "bleibt"

    def test_showing_the_tab_again_reloads_a_clean_day(self, panel, base):
        _write(base, _iso(), "von außen geändert")
        panel._diary_refresh()
        assert panel._diary_note.toPlainText() == "von außen geändert"

    @pytest.fixture
    def tabs(self, qtbot, panel):
        widget = QTabWidget()
        qtbot.addWidget(widget)
        widget.addTab(QWidget(), "Other")
        widget.addTab(panel, "Diary")
        widget.addTab(QWidget(), "Third")
        panel.attach_to_tabs(widget, 1)
        widget.setCurrentIndex(1)
        return widget

    def test_leaving_the_tab_with_a_clean_note_asks_nothing(self, tabs, panel):
        panel._diary_ask_unsaved = _never
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 0

    def test_cancel_brings_the_user_back_to_the_diary_tab(self, tabs, panel):
        panel._diary_note.setPlainText("nicht verlieren")
        panel._diary_ask_unsaved = lambda day: "cancel"
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 1
        assert panel._diary_note.toPlainText() == "nicht verlieren"

    def test_discard_leaves_and_drops_the_text(self, tabs, panel):
        panel._diary_note.setPlainText("weg damit")
        panel._diary_ask_unsaved = lambda day: "discard"
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 0
        assert panel._diary_note.toPlainText() == ""

    def test_save_leaves_after_writing(self, tabs, panel, base):
        panel._diary_note.setPlainText("sichern")
        panel._diary_ask_unsaved = lambda day: "save"
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 0
        assert rd.read_day(base, _iso())[1]["note"] == "sichern"

    def test_a_save_that_is_refused_keeps_the_user_in_the_diary_tab(self, tabs, panel, base):
        _write(base, _iso(-1), "alt", now=datetime.now() - timedelta(days=1))
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("geändert")
        panel._diary_ask_unsaved = lambda day: "save"
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 1
        assert panel._diary_note.toPlainText() == "geändert"

    def test_moving_between_other_tabs_asks_nothing(self, tabs, panel):
        tabs.setCurrentIndex(0)
        panel._diary_note.setPlainText("später")
        panel._diary_ask_unsaved = _never
        tabs.setCurrentIndex(2)
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 0

    def test_the_question_names_the_day_when_the_tab_is_left(self, tabs, panel):
        panel._diary_note.setPlainText("x")
        asked = []
        panel._diary_ask_unsaved = lambda day: asked.append(day) or "cancel"
        tabs.setCurrentIndex(0)
        assert asked == [_iso()]


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4c: the "Create field" dialog
# ══════════════════════════════════════════════════════════════════════════════

class TestDescribeFailure:

    @pytest.mark.parametrize("result,expected", [
        ({"reason": "duplicate_name"}, "already exists"),
        ({"reason": "invalid_definition", "errors": ["name_missing"]}, "Enter a name"),
        ({"reason": "invalid_definition", "errors": ["name_too_long"]}, "at most 80"),
        ({"reason": "invalid_definition", "errors": ["values_missing"]}, "at least one value"),
        ({"reason": "invalid_definition", "errors": ["values_too_many"]}, "at most 12 values"),
        ({"reason": "invalid_definition", "errors": ["value0_label_missing"]}, "needs a label"),
        ({"reason": "invalid_definition", "errors": ["value1_label_too_long"]}, "at most 40"),
        ({"reason": "invalid_definition", "errors": ["value1_label_duplicate"]}, "must be different"),
        ({"reason": "invalid_definition", "errors": ["value0_unit_too_long"]}, "at most 20"),
        ({"reason": "invalid_definition", "errors": ["something_new"]}, "something_new"),
        ({"reason": "master_damaged"}, "cannot be changed"),
        ({"reason": "master_unsupported"}, "cannot be changed"),
        ({"reason": "master_missing_days_exist"}, "rebuilt"),
        ({"reason": "write_failed"}, "could not be saved"),
        ({"reason": "mystery"}, "mystery"),
        ({"status": "failed"}, "failed"),
    ])
    def test_a_refusal_becomes_a_sentence(self, result, expected):
        assert expected in describe_failure(result)

    def test_the_sentence_names_what_was_tried(self):
        assert "could not be created (mystery)" in describe_failure({"reason": "mystery"})
        assert "could not be renamed (mystery)" in describe_failure({"reason": "mystery"}, "renamed")
        assert "could not be restored (mystery)" in describe_failure({"reason": "mystery"}, "restored")

    def test_typed_values_have_their_own_sentence(self):
        assert "Save or clear them first" in describe_failure({"reason": "typed_values"}, "archived")


class TestFieldDialog:

    @pytest.fixture
    def calls(self):
        return []

    @pytest.fixture
    def dialog(self, qtbot, panel, calls):
        def creator(name, values, with_time, favorite):
            calls.append((name, values, with_time, favorite))
            return {"status": "written", "key": "U0001"}
        widget = DiaryFieldDialog(panel, creator)
        qtbot.addWidget(widget)
        return widget

    def test_it_opens_with_one_value_and_a_favorite(self, dialog):
        assert len(dialog._rows) == 1
        assert dialog._favorite.isChecked() and not dialog._with_time.isChecked()
        assert dialog.created_key is None
        assert not dialog._rows[0].remove_btn.isEnabled(), "a field keeps at least one value"

    def test_values_can_be_added_up_to_the_limit(self, dialog):
        for _ in range(11):
            dialog._add_btn.click()
        assert len(dialog._rows) == 12
        assert not dialog._add_btn.isEnabled()
        assert dialog._add_row() is None, "no 13th value"

    def test_a_value_can_be_removed_but_not_the_last(self, dialog):
        dialog._add_btn.click()
        assert len(dialog._rows) == 2 and dialog._rows[0].remove_btn.isEnabled()
        dialog._rows[0].remove_btn.click()
        assert len(dialog._rows) == 1
        assert not dialog._rows[0].remove_btn.isEnabled()
        dialog._remove_row(dialog._rows[0])
        assert len(dialog._rows) == 1

    def test_a_yes_no_value_has_no_unit(self, dialog):
        row = dialog._rows[0]
        row.unit.setText("mmHg")
        row.kind.setCurrentIndex(1)
        assert not row.unit.isEnabled() and row.unit.text() == ""
        row.kind.setCurrentIndex(0)
        assert row.unit.isEnabled()

    def test_collect_cleans_what_was_typed(self, dialog):
        dialog._name.setText("  Schmerz   tablette ")
        dialog._with_time.setChecked(True)
        dialog._rows[0].label.setText("  Anzahl ")
        dialog._rows[0].unit.setText(" Stück ")
        dialog._add_btn.click()
        dialog._rows[1].label.setText("Stark")
        dialog._rows[1].kind.setCurrentIndex(1)
        dialog._favorite.setChecked(False)
        assert dialog.collect() == (
            "Schmerz tablette",
            [{"label": "Anzahl", "type": "number", "unit": "Stück"}, {"label": "Stark", "type": "yesno"}],
            True, False)

    def test_creating_calls_the_creator_and_closes(self, dialog, calls):
        dialog._name.setText("Temperatur")
        dialog._rows[0].label.setText("Wert")
        dialog._rows[0].unit.setText("°C")
        dialog._with_time.setChecked(True)
        dialog._create_btn.click()
        assert calls == [("Temperatur", [{"label": "Wert", "type": "number", "unit": "°C"}], True, True)]
        assert dialog.created_key == "U0001"
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_an_empty_name_is_refused_before_the_creator(self, dialog, calls):
        dialog._rows[0].label.setText("Wert")
        dialog._create_btn.click()
        assert calls == [] and "name" in dialog._error.text()
        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_an_empty_label_is_refused_before_the_creator(self, dialog, calls):
        dialog._name.setText("Neu")
        dialog._create_btn.click()
        assert calls == [] and "label" in dialog._error.text()

    def test_labels_that_only_differ_in_case_are_refused(self, dialog, calls):
        dialog._name.setText("Neu")
        dialog._rows[0].label.setText("Wert")
        dialog._add_btn.click()
        dialog._rows[1].label.setText("WERT")
        dialog._create_btn.click()
        assert calls == [] and "different" in dialog._error.text()

    def test_a_refusal_of_the_writer_is_shown_and_the_dialog_stays_open(self, qtbot, panel):
        def creator(*args):
            return {"status": "rejected", "reason": "duplicate_name"}
        widget = DiaryFieldDialog(panel, creator)
        qtbot.addWidget(widget)
        widget._name.setText("Neu")
        widget._rows[0].label.setText("Wert")
        widget._create_btn.click()
        assert "already exists" in widget._error.text()
        assert widget.created_key is None and widget.result() != QDialog.DialogCode.Accepted
        assert widget._name.text() == "Neu", "what the user typed stays"

    def test_cancel_closes_without_a_field(self, dialog, calls):
        dialog._cancel_btn.click()
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert calls == [] and dialog.created_key is None


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4c: the field list, the dropdown, favorites
# ══════════════════════════════════════════════════════════════════════════════

def _items(panel):
    combo = panel._diary_field_combo
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def _keys_in_dropdown(panel):
    """The field keys in the dropdown (the start templates, "tpl:...", are counted by _templates_in_dropdown)."""
    return [key for _text, key in _items(panel) if key and not key.startswith("tpl:")]


def _templates_in_dropdown(panel):
    return [text for text, key in _items(panel) if key and key.startswith("tpl:")]


def _choose(panel, key):
    combo = panel._diary_field_combo
    index = combo.findData(key)
    assert index > 0, f"{key} is not in the dropdown: {_items(panel)}"
    combo.activated.emit(index)


def _fill_and_create(name="Schmerztablette", favorite=True, with_time=True, label="Anzahl", unit="Stück"):
    """An exec() for the dialog that types a field and clicks Create, as a user would."""
    def fake_exec(self):
        self._name.setText(name)
        self._rows[0].label.setText(label)
        self._rows[0].unit.setText(unit)
        self._with_time.setChecked(with_time)
        self._favorite.setChecked(favorite)
        self._create_btn.click()
        return QDialog.DialogCode.Accepted if self.created_key else QDialog.DialogCode.Rejected
    return fake_exec


def _write_capability(base, endpoints):
    path = Path(base) / "garmin_data" / "log" / "garmin_api_capability_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"endpoints": endpoints}), encoding="utf-8")


class TestFields:

    def test_without_fields_the_hint_asks_to_create_one(self, panel):
        assert panel._diary_rows == {}
        assert "Create a field" in panel._diary_favorites_hint.text()
        assert not panel._diary_favorites_hint.isHidden()

    def test_without_a_folder_the_hint_points_to_the_settings(self, raw_panel):
        assert "archive folder" in raw_panel._diary_favorites_hint.text()
        assert not raw_panel._diary_create_btn.isEnabled() and not raw_panel._diary_field_combo.isEnabled()

    def test_the_dropdown_starts_with_the_placeholder_and_the_garmin_fields(self, panel):
        texts = [text for text, _key in _items(panel)]
        assert texts[0] == "Add field …"
        assert "— Garmin fields —" in texts
        assert _keys_in_dropdown(panel) == ["G001", "G002", "G003"]
        assert "— Your fields —" not in texts, "no field of the user yet"

    def test_the_group_headers_cannot_be_chosen(self, panel):
        combo = panel._diary_field_combo
        header = combo.findText("— Garmin fields —")
        assert not combo.model().item(header).isEnabled()
        combo.activated.emit(header)
        assert panel._diary_rows == {} and panel._diary_added == []

    # ── Create ──────────────────────────────────────

    def test_creating_a_field_makes_a_favorite_row(self, qtbot, panel, base):
        with patch.object(DiaryFieldDialog, "exec", _fill_and_create()):
            qtbot.mouseClick(panel._diary_create_btn, Qt.MouseButton.LeftButton)
        state, master = rd.read_master(base)
        assert state == rd.OK and master["fields"]["U0001"]["name"] == "Schmerztablette"
        assert master["fields"]["U0001"]["favorite"] is True
        row = panel._diary_rows["U0001"]
        assert row.favorite and row.star.text() == "★"
        assert row.name_label.text() == "Schmerztablette"
        assert row.hint_label.text() == "Anzahl (Stück) · with time"
        assert panel._diary_favorites_hint.isHidden()
        assert panel._diary_status.text() == "Field created."
        assert "U0001" not in _keys_in_dropdown(panel), "a shown field is not offered again"

    def test_a_field_that_is_not_a_favorite_is_shown_for_the_day_and_offered_later(self, qtbot, panel, base):
        with patch.object(DiaryFieldDialog, "exec", _fill_and_create(favorite=False)):
            qtbot.mouseClick(panel._diary_create_btn, Qt.MouseButton.LeftButton)
        assert rd.read_master(base)[1]["fields"]["U0001"]["favorite"] is False
        assert panel._diary_rows["U0001"].star.text() == "☆"
        _pick(panel, _iso(-1))
        assert "U0001" not in panel._diary_rows, "the row was only for the day it was made on"
        assert "U0001" in _keys_in_dropdown(panel) and "— Your fields —" in [t for t, _k in _items(panel)]

    def test_a_refused_field_leaves_the_list_alone(self, qtbot, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        before = (base / "diary_data" / "fields.json").read_bytes()
        with patch.object(DiaryFieldDialog, "exec", _fill_and_create(name="schmerztablette")):
            qtbot.mouseClick(panel._diary_create_btn, Qt.MouseButton.LeftButton)
        assert (base / "diary_data" / "fields.json").read_bytes() == before
        assert panel._diary_status.text() != "Field created."

    def test_the_value_types_survive_the_dialog(self, qtbot, panel, base):
        def fake_exec(self):
            self._name.setText("Spazieren")
            self._rows[0].label.setText("Ja/Nein")
            self._rows[0].kind.setCurrentIndex(1)
            self._create_btn.click()
            return QDialog.DialogCode.Accepted
        with patch.object(DiaryFieldDialog, "exec", fake_exec):
            qtbot.mouseClick(panel._diary_create_btn, Qt.MouseButton.LeftButton)
        field = rd.read_master(base)[1]["fields"]["U0001"]
        assert field["values"] == [{"label": "Ja/Nein", "type": "yesno"}] and field["with_time"] is False
        assert panel._diary_rows["U0001"].hint_label.text() == "Ja/Nein (yes/no)"

    def test_creating_writes_only_the_field_list(self, qtbot, panel, base):
        with patch.object(DiaryFieldDialog, "exec", _fill_and_create()):
            qtbot.mouseClick(panel._diary_create_btn, Qt.MouseButton.LeftButton)
        assert [p.name for p in (base / "diary_data").rglob("*") if p.is_file()] == ["fields.json"]

    def test_the_create_button_asks_nothing_without_a_folder(self, raw_panel):
        with patch.object(DiaryFieldDialog, "exec", side_effect=AssertionError("the dialog must not open")):
            raw_panel._diary_on_create_clicked()

    # ── Dropdown ────────────────────────────────────

    def test_choosing_a_field_of_the_user_shows_a_row(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        assert "U0001" in _keys_in_dropdown(panel)
        _choose(panel, "U0001")
        row = panel._diary_rows["U0001"]
        assert not row.favorite and not row.remove_btn.isHidden(), "a field added for the day can be taken out again"
        assert "U0001" not in _keys_in_dropdown(panel)
        assert panel._diary_field_combo.currentIndex() == 0, "the dropdown goes back to its title"

    def test_choosing_a_garmin_field_adds_it_to_the_list_of_fields(self, panel, base):
        _choose(panel, "G001")
        field = rd.read_master(base)[1]["fields"]["G001"]
        assert field["name"] == "Blood pressure" and field["favorite"] is False and field["archived"] is False
        assert panel._diary_rows["G001"].hint_label.text() == "systolic (mmHg), diastolic (mmHg), Pulse (bpm) · with time"

    def test_choosing_a_garmin_field_twice_is_harmless(self, panel, base):
        _choose(panel, "G003")
        panel._diary_added.clear()
        panel._diary_render()
        _choose(panel, "G003")
        assert list(rd.read_master(base)[1]["fields"]) == ["G003"]

    def test_a_row_that_was_added_can_be_taken_out_again(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _choose(panel, "U0001")
        panel._diary_rows["U0001"].remove_btn.click()
        assert "U0001" not in panel._diary_rows and "U0001" in _keys_in_dropdown(panel)

    def test_a_favorite_has_no_remove_button(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        wr.set_flags(base, "U0001", favorite=True)
        panel._diary_refresh()
        assert panel._diary_rows["U0001"].remove_btn.isHidden()

    def test_archived_fields_are_not_offered_and_not_shown(self, panel, base):
        wr.create_user_field(base, "Alt", TABLET, True)
        wr.set_flags(base, "U0001", favorite=True, archived=True)
        wr.activate_catalog_field(base, "G002")
        wr.set_flags(base, "G002", archived=True)
        panel._diary_refresh()
        assert "U0001" not in panel._diary_rows
        assert "U0001" not in _keys_in_dropdown(panel) and "G002" not in _keys_in_dropdown(panel)

    # ── Which Garmin fields are offered ─────────────

    def test_a_garmin_field_that_garmin_delivers_is_left_out(self, panel, base):
        _write_capability(base, {"get_blood_pressure": {"status": "found", "enabled_by_user": True}})
        panel._diary_refresh()
        assert _keys_in_dropdown(panel) == ["G002", "G003"]

    def test_the_checkbox_offers_them_all_and_says_which_ones_are_delivered(self, panel, base):
        _write_capability(base, {"get_blood_pressure": {"status": "found", "enabled_by_user": True}})
        panel._diary_refresh()
        panel._diary_all_garmin.setChecked(True)
        assert _keys_in_dropdown(panel) == ["G001", "G002", "G003"]
        assert "Blood pressure (Garmin delivers this)" in [t for t, _k in _items(panel)]
        panel._diary_all_garmin.setChecked(False)
        assert _keys_in_dropdown(panel) == ["G002", "G003"]

    @pytest.mark.parametrize("endpoints", [
        {"get_blood_pressure": {"status": "found", "enabled_by_user": False}},
        {"get_blood_pressure": {"status": "not_observed", "enabled_by_user": True}},
        {"get_blood_pressure": {"status": "error", "enabled_by_user": True}},
        {},
    ])
    def test_a_garmin_field_is_offered_unless_both_gates_are_open(self, panel, base, endpoints):
        _write_capability(base, endpoints)
        panel._diary_refresh()
        assert _keys_in_dropdown(panel) == ["G001", "G002", "G003"]

    def test_a_damaged_capability_file_offers_every_garmin_field(self, panel, base):
        path = base / "garmin_data" / "log" / "garmin_api_capability_config.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        assert _keys_in_dropdown(panel) == ["G001", "G002", "G003"]

    def test_an_activated_garmin_field_that_garmin_delivers_stays_findable_with_the_checkbox(self, panel, base):
        _choose(panel, "G002")
        panel._diary_added.clear()
        _write_capability(base, {"get_hydration_data": {"status": "found", "enabled_by_user": True}})
        panel._diary_refresh()
        assert "G002" not in _keys_in_dropdown(panel)
        panel._diary_all_garmin.setChecked(True)
        assert "G002" in _keys_in_dropdown(panel)

    # ── Favorites ───────────────────────────────────

    def test_the_star_makes_a_favorite_and_takes_it_back(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _choose(panel, "U0001")
        panel._diary_rows["U0001"].star.click()
        assert rd.read_master(base)[1]["fields"]["U0001"]["favorite"] is True
        assert panel._diary_rows["U0001"].star.text() == "★"
        panel._diary_rows["U0001"].star.click()
        assert rd.read_master(base)[1]["fields"]["U0001"]["favorite"] is False
        assert panel._diary_rows["U0001"].star.text() == "☆", "still shown: it was added for this day"

    def test_a_favorite_that_is_switched_off_leaves_the_list(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        wr.set_flags(base, "U0001", favorite=True)
        panel._diary_refresh()
        panel._diary_rows["U0001"].star.click()
        assert "U0001" not in panel._diary_rows
        assert "U0001" in _keys_in_dropdown(panel)

    def test_a_favorite_is_there_on_every_day(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        wr.set_flags(base, "U0001", favorite=True)
        panel._diary_refresh()
        _pick(panel, _iso(-4))
        assert "U0001" in panel._diary_rows

    def test_the_favorites_come_in_the_order_of_the_list(self, panel, base):
        for name in ("Erstes", "Zweites", "Drittes"):
            key = wr.create_user_field(base, name, TABLET, True)["key"]
            wr.set_flags(base, key, favorite=True)
        panel._diary_refresh()
        assert list(panel._diary_rows) == ["U0001", "U0002", "U0003"]

    def test_a_failed_write_of_the_star_says_so(self, panel, base):
        wr.create_user_field(base, "Schmerztablette", TABLET, True)
        wr.set_flags(base, "U0001", favorite=True)
        panel._diary_refresh()
        with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
            panel._diary_rows["U0001"].star.click()
        assert "Could not change" in panel._diary_status.text()
        assert rd.read_master(base)[1]["fields"]["U0001"]["favorite"] is True

    # ── Fields a day already has, and a field list that is not fine ──────────

    def test_a_field_the_day_has_entries_for_is_shown_without_being_a_favorite(self, panel, base):
        key = _make_field(base)
        _write(base, _iso(-1), "Notiz", {key: [{"time": "14:05", "values": {"Anzahl": 1}}]})
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        row = panel._diary_rows[key]
        assert not row.favorite and row.remove_btn.isHidden(), "it has entries: it cannot be taken out"
        _pick(panel, _iso(-2))
        assert key not in panel._diary_rows

    def test_without_the_field_list_the_name_comes_from_the_day(self, panel, base):
        key = _make_field(base)
        _write(base, _iso(-1), "Notiz", {key: [{"time": "14:05", "values": {"Anzahl": 1}}]})
        (base / "diary_data" / "fields.json").unlink()
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        row = panel._diary_rows[key]
        assert row.name_label.text() == "Schmerztablette"
        assert not row.star.isEnabled(), "no field list: no favorite to change"

    def test_a_damaged_field_list_is_left_alone_and_nothing_can_be_made(self, panel, base):
        path = base / "diary_data" / "fields.json"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        assert "cannot be read" in panel._diary_favorites_hint.text()
        assert not panel._diary_create_btn.isEnabled() and not panel._diary_field_combo.isEnabled()
        assert [t for t, _k in _items(panel)] == ["Add field …"]
        assert path.read_text(encoding="utf-8") == "{ not json"

    def test_a_field_made_elsewhere_shows_up_when_the_panel_is_shown_again(self, panel, base):
        wr.create_user_field(base, "Von außen", TABLET, True)
        assert "U0001" not in _keys_in_dropdown(panel)
        panel._diary_refresh()
        assert "U0001" in _keys_in_dropdown(panel)

    def test_the_rows_do_not_touch_an_unsaved_note(self, panel, base):
        panel._diary_note.setPlainText("bleibt")
        wr.create_user_field(base, "Neu", TABLET, True)
        panel._diary_refresh()
        assert panel._diary_note.toPlainText() == "bleibt" and "U0001" in _keys_in_dropdown(panel)


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4d: the entry boxes
# ══════════════════════════════════════════════════════════════════════════════

class TestParseNumber:

    @pytest.mark.parametrize("text,expected", [
        ("", (True, None)), ("   ", (True, None)),
        ("80", (True, 80)), ("-5", (True, -5)), ("+5", (True, 5)), ("0", (True, 0)), ("-0", (True, 0)),
        ("7,5", (True, 7.5)), ("7.5", (True, 7.5)), (" 7,5 ", (True, 7.5)), (".5", (True, 0.5)), ("5.", (True, 5.0)),
        ("1e3", (True, 1000.0)), ("1E-2", (True, 0.01)), ("80.0", (True, 80.0)), ("1e300", (True, 1e300)),
    ])
    def test_what_is_a_number(self, text, expected):
        assert parse_number(text) == expected

    @pytest.mark.parametrize("text", [
        "abc", "1.000,5", "1,000.5", "nan", "inf", "-inf", "1_0", "1e999", "1e301", "5 5", "--5", "0x10", "1,2,3",
        "٣", "5%", "e5", ",", ".", "+", "١٢",
    ])
    def test_what_is_not_a_number(self, text):
        assert parse_number(text) == (False, None)

    def test_a_whole_number_is_an_int_and_a_decimal_is_a_float(self):
        assert type(parse_number("80")[1]) is int
        assert type(parse_number("80.0")[1]) is float
        assert type(parse_number("7,5")[1]) is float

    def test_zero_is_a_value_and_empty_is_not(self):
        assert parse_number("0")[1] == 0 and parse_number("0")[1] is not None
        assert parse_number("")[1] is None


@pytest.fixture
def colors():
    from types import SimpleNamespace
    return SimpleNamespace(BG="#12101f", BG2="#1a1729", BG3="#231f38", ACCENT="#a259f7", ACCENT2="#6e3fcf",
                           TEXT="#eaeaea", TEXT2="#a0a0b0", YELLOW="#f5a623")


def _editor(qtbot, colors, defn, entries=(), default_time=lambda: "09:30"):
    from app.diary_entry_editor import EntryEditor
    widget = EntryEditor(colors, defn, list(entries), default_time)
    qtbot.addWidget(widget)
    return widget


class TestEntryEditor:

    BP = {"name": "Blood pressure", "set": "garmin", "maps_to": "x", "with_time": True,
          "values": [{"label": "systolic", "type": "number", "unit": "mmHg"},
                     {"label": "diastolic", "type": "number", "unit": "mmHg"},
                     {"label": "Pulse", "type": "number", "unit": "bpm"}]}
    WEIGHT = {"name": "Weight", "set": "garmin", "maps_to": "x", "with_time": False,
              "values": [{"label": "Weight", "type": "number", "unit": "kg"}]}
    WALK = {"name": "Walk", "set": "user", "with_time": False, "values": [{"label": "Done", "type": "yesno"}]}

    def test_a_new_field_has_one_empty_line_with_the_time_now(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        assert len(editor.lines) == 1
        assert editor.lines[0].time_text() == "09:30"
        assert editor.collect() == ([], [])
        assert not editor.has_content()

    def test_the_default_time_is_asked_when_a_line_is_made(self, qtbot, colors):
        times = iter(["09:30", "10:45"])
        editor = _editor(qtbot, colors, self.BP, default_time=lambda: next(times))
        editor.add_btn.click()
        assert [line.time_text() for line in editor.lines] == ["09:30", "10:45"]

    def test_stored_entries_are_shown_one_line_each(self, qtbot, colors):
        entries = [{"time": "07:15", "values": {"systolic": 128, "diastolic": 82, "Pulse": 61}},
                   {"time": "19:40", "values": {"systolic": 124}}]
        editor = _editor(qtbot, colors, self.BP, entries)
        assert len(editor.lines) == 2
        assert editor.lines[0].time_text() == "07:15" and editor.lines[1].time_text() == "19:40"
        assert editor.lines[0].inputs["systolic"].text() == "128" and editor.lines[1].inputs["diastolic"].text() == ""
        assert editor.collect() == (entries, [])

    def test_typed_values_become_an_entry(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        line = editor.lines[0]
        line.inputs["systolic"].setText("128")
        line.inputs["Pulse"].setText("61,5")
        assert editor.collect() == ([{"time": "09:30", "values": {"systolic": 128, "Pulse": 61.5}}], [])

    def test_the_time_can_be_changed(self, qtbot, colors):
        from PyQt6.QtCore import QTime
        editor = _editor(qtbot, colors, self.BP)
        editor.lines[0].time.setTime(QTime(7, 5))
        editor.lines[0].inputs["Pulse"].setText("60")
        assert editor.collect()[0] == [{"time": "07:05", "values": {"Pulse": 60}}]

    def test_a_line_where_only_the_time_changed_is_no_entry(self, qtbot, colors):
        from PyQt6.QtCore import QTime
        editor = _editor(qtbot, colors, self.BP)
        editor.lines[0].time.setTime(QTime(7, 5))
        assert editor.collect() == ([], [])

    def test_zero_is_an_entry_and_empty_is_not(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        editor.lines[0].inputs["Pulse"].setText("0")
        assert editor.collect()[0] == [{"time": "09:30", "values": {"Pulse": 0}}]
        editor.lines[0].inputs["Pulse"].setText("")
        assert editor.collect() == ([], [])

    def test_a_value_that_is_not_a_number_is_reported_and_marked(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        line = editor.lines[0]
        line.inputs["systolic"].setText("12o")
        line.inputs["Pulse"].setText("61")
        entries, errors = editor.collect()
        assert entries == [] and errors == ["systolic"]
        assert "e05555" in line.inputs["systolic"].styleSheet(), "the box is marked"
        assert "e05555" not in line.inputs["Pulse"].styleSheet()
        line.inputs["systolic"].setText("120")
        editor.collect()
        assert "e05555" not in line.inputs["systolic"].styleSheet(), "the mark goes when the value is fine"

    def test_yes_no_has_three_states(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.WALK)
        box = editor.lines[0].inputs["Done"]
        assert [box.itemText(i) for i in range(box.count())] == ["", "Yes", "No"]
        assert editor.collect() == ([], []), "empty is not an answer"
        box.setCurrentIndex(1)
        assert editor.collect()[0] == [{"values": {"Done": True}}]
        box.setCurrentIndex(2)
        assert editor.collect()[0] == [{"values": {"Done": False}}], "No is an entry, not a blank"

    def test_stored_yes_and_no_are_shown(self, qtbot, colors):
        yes = _editor(qtbot, colors, self.WALK, [{"values": {"Done": True}}])
        no = _editor(qtbot, colors, self.WALK, [{"values": {"Done": False}}])
        assert yes.lines[0].inputs["Done"].currentIndex() == 1 and no.lines[0].inputs["Done"].currentIndex() == 2

    def test_a_field_without_a_time_has_one_line_and_no_time(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.WEIGHT)
        assert len(editor.lines) == 1 and editor.lines[0].time is None and editor.add_btn is None
        assert editor.lines[0].remove_btn.isHidden()
        editor.lines[0].inputs["Weight"].setText("80,5")
        assert editor.collect()[0] == [{"values": {"Weight": 80.5}}]

    def test_more_lines_for_a_field_with_a_time(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        editor.lines[0].inputs["Pulse"].setText("60")
        editor.add_btn.click()
        editor.lines[1].inputs["Pulse"].setText("70")
        assert [e["values"]["Pulse"] for e in editor.collect()[0]] == [60, 70], "in the order of the lines"

    def test_a_line_can_be_taken_out_and_the_last_is_only_emptied(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        editor.add_btn.click()
        editor.lines[0].inputs["Pulse"].setText("60")
        editor.lines[1].inputs["Pulse"].setText("70")
        editor.lines[0].remove_btn.click()
        assert len(editor.lines) == 1 and editor.collect()[0][0]["values"]["Pulse"] == 70
        editor.lines[0].remove_btn.click()
        assert len(editor.lines) == 1 and editor.collect() == ([], []), "the last line stays, empty"

    def test_has_content(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        assert not editor.has_content()
        editor.lines[0].inputs["Pulse"].setText("   ")
        assert not editor.has_content(), "space is no content"
        editor.lines[0].inputs["Pulse"].setText("0")
        assert editor.has_content(), "0 is content"
        walk = _editor(qtbot, colors, self.WALK)
        walk.lines[0].inputs["Done"].setCurrentIndex(2)
        assert walk.has_content()

    def test_raw_state_round_trips_even_for_text_that_is_not_a_number(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        editor.add_btn.click()
        editor.lines[0].inputs["systolic"].setText("12o")
        editor.lines[1].inputs["Pulse"].setText("61")
        state = editor.raw_state()
        other = _editor(qtbot, colors, self.BP)
        other.set_raw_state(state)
        assert len(other.lines) == 2
        assert other.lines[0].inputs["systolic"].text() == "12o" and other.lines[1].inputs["Pulse"].text() == "61"
        assert other.raw_state() == state

    def test_raw_state_keeps_yes_no_and_times(self, qtbot, colors):
        walk = _editor(qtbot, colors, self.WALK)
        walk.lines[0].inputs["Done"].setCurrentIndex(2)
        other = _editor(qtbot, colors, self.WALK)
        other.set_raw_state(walk.raw_state())
        assert other.lines[0].inputs["Done"].currentIndex() == 2
        bp = _editor(qtbot, colors, self.BP, [{"time": "07:15", "values": {"Pulse": 60}}])
        other = _editor(qtbot, colors, self.BP)
        other.set_raw_state(bp.raw_state())
        assert other.lines[0].time_text() == "07:15"

    def test_it_can_be_switched_off(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP)
        editor.set_editable(False)
        line = editor.lines[0]
        assert not line.time.isEnabled() and not line.inputs["Pulse"].isEnabled() and not editor.add_btn.isEnabled()
        editor.add_line()
        assert not editor.lines[1].inputs["Pulse"].isEnabled(), "a line added later is switched off too"
        editor.set_editable(True)
        assert line.inputs["Pulse"].isEnabled() and editor.add_btn.isEnabled()

    def test_a_stored_time_that_is_not_valid_falls_back_to_midnight(self, qtbot, colors):
        editor = _editor(qtbot, colors, self.BP, [{"time": "99:99", "values": {"Pulse": 60}}])
        assert editor.lines[0].time_text() == "00:00"


def _field(base, name, values, with_time, favorite=True):
    key = wr.create_user_field(base, name, values, with_time)["key"]
    if favorite:
        wr.set_flags(base, key, favorite=True)
    return key


def _line(panel, key, index=0):
    return panel._diary_rows[key].editor.lines[index]


YESNO_VALUES = [{"label": "Done", "type": "yesno"}]


class TestEntriesInThePanel:

    def test_a_favorite_has_an_empty_line_for_today(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_now = lambda: datetime(2026, 11, 18, 9, 30)
        panel._diary_refresh()
        line = _line(panel, key)
        assert line.time_text() == "09:30" and line.inputs["Anzahl"].text() == ""
        assert not panel._diary_is_dirty(), "an empty line is nothing typed"

    def test_typing_a_value_makes_the_day_dirty(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("1")
        assert panel._diary_is_dirty()

    def test_saving_writes_the_entry_with_the_time_of_the_line(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_now = lambda: datetime(2026, 11, 18, 14, 5)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("2")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        day = rd.read_day(base, _iso())[1]
        assert day["entries"] == {key: [{"time": "14:05", "values": {"Anzahl": 2}}]}
        assert day["key_snapshot"][key]["name"] == "Schmerztablette"
        assert panel._diary_status.text().startswith("Saved ") and not panel._diary_is_dirty()

    def test_after_a_save_the_rows_show_what_is_stored(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("2")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert _line(panel, key).inputs["Anzahl"].text() == "2"
        assert panel._diary_drafts == {}

    def test_a_decimal_comma_is_saved_as_a_number(self, qtbot, panel, base):
        key = _field(base, "Gewicht heute", [{"label": "Wert", "type": "number", "unit": "kg"}], False)
        panel._diary_refresh()
        _line(panel, key).inputs["Wert"].setText("80,5")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {key: [{"values": {"Wert": 80.5}}]}
        assert _line(panel, key).inputs["Wert"].text() == "80.5"

    def test_a_value_that_is_not_a_number_stops_the_save_and_keeps_the_text(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("zwei")
        panel._diary_note.setPlainText("Notiz")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert "not numbers" in panel._diary_status.text()
        assert not _day_path(base, _iso()).exists(), "nothing was written, not even the note"
        assert _line(panel, key).inputs["Anzahl"].text() == "zwei" and panel._diary_note.toPlainText() == "Notiz"
        assert panel._diary_is_dirty()

    def test_yes_no_is_saved_and_can_be_taken_back(self, qtbot, panel, base):
        key = _field(base, "Walk", YESNO_VALUES, False)
        panel._diary_refresh()
        _line(panel, key).inputs["Done"].setCurrentIndex(2)
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {key: [{"values": {"Done": False}}]}
        assert _line(panel, key).inputs["Done"].currentIndex() == 2
        _line(panel, key).inputs["Done"].setCurrentIndex(0)
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert not _day_path(base, _iso()).exists(), "the day had only that entry: it is removed"

    def test_stored_entries_are_shown_when_the_day_is_picked(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        _write(base, _iso(-1), "Notiz", {key: [{"time": "08:00", "values": {"Anzahl": 1}},
                                              {"time": "20:30", "values": {"Anzahl": 2}}]})
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        lines = panel._diary_rows[key].editor.lines
        assert [(ln.time_text(), ln.inputs["Anzahl"].text()) for ln in lines] == [("08:00", "1"), ("20:30", "2")]
        assert not panel._diary_is_dirty()

    def test_a_second_entry_is_added_and_saved(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("1")
        panel._diary_rows[key].editor.add_btn.click()
        _line(panel, key, 1).inputs["Anzahl"].setText("2")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert [e["values"]["Anzahl"] for e in rd.read_day(base, _iso())[1]["entries"][key]] == [1, 2]
        assert len(panel._diary_rows[key].editor.lines) == 2

    def test_an_entry_can_be_taken_out_and_saved(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        _write(base, _iso(), "Notiz", {key: [{"time": "08:00", "values": {"Anzahl": 1}},
                                             {"time": "20:30", "values": {"Anzahl": 2}}]})
        panel._diary_refresh()
        _line(panel, key, 0).remove_btn.click()
        assert panel._diary_is_dirty()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"][key] == [{"time": "20:30", "values": {"Anzahl": 2}}]

    def test_a_field_without_a_time_has_no_time_in_the_entry(self, qtbot, panel, base):
        wr.activate_catalog_field(base, "G003")
        wr.set_flags(base, "G003", favorite=True)
        panel._diary_refresh()
        _line(panel, "G003").inputs["Weight"].setText("81")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {"G003": [{"values": {"Weight": 81}}]}

    def test_a_note_alone_leaves_empty_lines_out(self, qtbot, panel, base):
        _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        panel._diary_note.setPlainText("nur Notiz")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {}

    def test_entries_of_other_fields_are_not_touched(self, qtbot, panel, base):
        a = _field(base, "Erstes", TABLET, True)
        b = _field(base, "Zweites", TABLET, True)
        _write(base, _iso(), "Notiz", {a: [{"time": "08:00", "values": {"Anzahl": 1}}]})
        panel._diary_refresh()
        _line(panel, b).inputs["Anzahl"].setText("5")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        entries = rd.read_day(base, _iso())[1]["entries"]
        assert entries[a] == [{"time": "08:00", "values": {"Anzahl": 1}}] and entries[b][0]["values"] == {"Anzahl": 5}

    def test_entries_of_a_field_without_a_row_stay_as_loaded(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        panel._diary_entries = {"U0099": [{"time": "08:00", "values": {"Anzahl": 3}}]}
        entries, errors = panel._diary_collect_entries()
        assert entries == {"U0099": [{"time": "08:00", "values": {"Anzahl": 3}}]} and errors == []
        assert key in panel._diary_rows

    def test_without_the_field_list_the_entries_survive_a_save_of_the_note(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        entries = {key: [{"time": "14:05", "values": {"Anzahl": 1}}]}
        _write(base, _iso(), "alt", entries)
        (base / "diary_data" / "fields.json").unlink()
        panel._diary_refresh()
        panel._diary_note.setPlainText("neu")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == entries

    # ── What was typed is not lost ──────────────────

    def test_typed_values_survive_a_rebuild_of_the_rows(self, panel, base):
        a = _field(base, "Erstes", TABLET, True)
        b = _field(base, "Zweites", TABLET, True)
        panel._diary_refresh()
        _line(panel, a).inputs["Anzahl"].setText("3")
        panel._diary_rows[b].star.click()
        assert _line(panel, a).inputs["Anzahl"].text() == "3"
        assert panel._diary_is_dirty()

    def test_typed_values_survive_adding_a_field(self, panel, base):
        a = _field(base, "Erstes", TABLET, True)
        _field(base, "Zweites", TABLET, True, favorite=False)
        panel._diary_refresh()
        _line(panel, a).inputs["Anzahl"].setText("3")
        _choose(panel, "U0002")
        assert _line(panel, a).inputs["Anzahl"].text() == "3" and "U0002" in panel._diary_rows

    def test_a_field_with_typed_values_cannot_be_taken_out(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True, favorite=False)
        panel._diary_refresh()
        _choose(panel, key)
        _line(panel, key).inputs["Anzahl"].setText("1")
        panel._diary_rows[key].remove_btn.click()
        assert key in panel._diary_rows and "typed" in panel._diary_status.text()
        _line(panel, key).inputs["Anzahl"].setText("")
        panel._diary_rows[key].remove_btn.click()
        assert key not in panel._diary_rows

    def test_a_favorite_with_typed_values_stays_when_the_star_goes_off(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("1")
        panel._diary_rows[key].star.click()
        assert key in panel._diary_rows and not panel._diary_rows[key].favorite
        assert _line(panel, key).inputs["Anzahl"].text() == "1"

    def test_a_favorite_without_typed_values_leaves_when_the_star_goes_off(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        panel._diary_rows[key].star.click()
        assert key not in panel._diary_rows

    def test_the_drafts_go_when_the_day_changes(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("9")
        panel._diary_ask_unsaved = lambda day: "discard"
        _pick(panel, _iso(-1))
        assert _line(panel, key).inputs["Anzahl"].text() == "" and panel._diary_drafts == {}

    def test_changing_the_day_with_a_typed_value_asks(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("9")
        asked = []
        panel._diary_ask_unsaved = lambda day: asked.append(day) or "cancel"
        _pick(panel, _iso(-1))
        assert asked == [_iso()] and panel.selected_date() == _iso()
        assert _line(panel, key).inputs["Anzahl"].text() == "9"

    def test_closing_with_a_typed_value_asks(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("9")
        panel._diary_ask_unsaved = lambda day: "cancel"
        assert panel.confirm_close() is False

    def test_a_value_that_is_not_a_number_counts_as_unsaved(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("x")
        assert panel._diary_is_dirty()

    def test_showing_the_panel_again_keeps_typed_values(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("4")
        panel._diary_refresh()
        assert _line(panel, key).inputs["Anzahl"].text() == "4"

    # ── Switched off, deleted ───────────────────────

    def test_the_boxes_are_switched_off_for_a_day_that_cannot_be_saved(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        path = _day_path(base, _iso(-2))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        assert _line(panel, key).inputs["Anzahl"].isEnabled()
        _pick(panel, _iso(-2))
        assert not _line(panel, key).inputs["Anzahl"].isEnabled()
        _pick(panel, _iso(-1))
        assert _line(panel, key).inputs["Anzahl"].isEnabled()

    def test_delete_all_empties_the_entry_boxes(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        _write(base, _iso(-1), "Notiz", {key: [{"time": "08:00", "values": {"Anzahl": 1}}]})
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_ask_delete = lambda day: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert _line(panel, key).inputs["Anzahl"].text() == "" and not _day_path(base, _iso(-1)).exists()

    def test_a_day_saved_on_an_earlier_day_keeps_the_typed_values_and_says_why(self, qtbot, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        _write(base, _iso(-1), "alt", now=datetime.now() - timedelta(days=1))
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        _line(panel, key).inputs["Anzahl"].setText("3")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert "Not saved" in panel._diary_status.text()
        assert _line(panel, key).inputs["Anzahl"].text() == "3" and panel._diary_is_dirty()


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4c2: start templates, "Manage fields"
# ══════════════════════════════════════════════════════════════════════════════

TEMPLATE_NAMES = ["Cycle", "Pregnancy", "Calorie intake", "Alcohol", "Caffeine", "Walk"]


def _choose_template(panel, name):
    combo = panel._diary_field_combo
    index = combo.findData("tpl:" + name)
    assert index > 0, f"{name} is not offered: {_items(panel)}"
    combo.activated.emit(index)


class TestStartTemplates:

    def test_the_six_templates_are_offered_between_your_fields_and_the_garmin_fields(self, panel, base):
        wr.create_user_field(base, "Mine", TABLET, True)
        panel._diary_refresh()
        texts = [text for text, _key in _items(panel)]
        assert _templates_in_dropdown(panel) == TEMPLATE_NAMES
        assert texts.index("— Your fields —") < texts.index("— Start templates —") < texts.index("— Garmin fields —")
        assert texts.index("— Start templates —") + 1 == texts.index("Cycle")
        assert not panel._diary_field_combo.model().item(texts.index("— Start templates —")).isEnabled()

    def test_choosing_one_makes_a_normal_user_field_from_it(self, panel, base):
        _choose_template(panel, "Cycle")
        state, master = rd.read_master(base)
        assert state == rd.OK and list(master["fields"]) == ["U0001"]
        field = master["fields"]["U0001"]
        assert field == {"name": "Cycle", "set": "user", "with_time": False,
                         "values": [{"label": "Period", "type": "yesno"},
                                    {"label": "Day of cycle", "type": "number", "unit": "day"}],
                         "favorite": False, "archived": False}

    def test_the_field_is_shown_for_the_day_with_its_entry_boxes(self, panel, base):
        _choose_template(panel, "Cycle")
        assert list(panel._diary_rows) == ["U0001"]
        line = _line(panel, "U0001")
        assert set(line.inputs) == {"Period", "Day of cycle"}
        assert "Cycle" in panel._diary_status.text() and "template" in panel._diary_status.text()

    def test_a_used_template_is_not_offered_again(self, panel, base):
        _choose_template(panel, "Walk")
        assert "Walk" not in _templates_in_dropdown(panel)
        assert _templates_in_dropdown(panel) == [n for n in TEMPLATE_NAMES if n != "Walk"]

    def test_the_field_is_added_for_the_day_shown_only_and_is_not_a_favorite(self, panel, base):
        _choose_template(panel, "Walk")
        _pick(panel, _iso(-1))
        assert "U0001" not in panel._diary_rows, "added for the day shown only, like any field from the list"
        assert "U0001" in _keys_in_dropdown(panel)

    def test_a_template_whose_name_a_field_already_has_is_not_offered(self, panel, base):
        wr.create_user_field(base, "alcohol", TABLET, True)
        panel._diary_refresh()
        assert "Alcohol" not in _templates_in_dropdown(panel)

    def test_a_template_whose_name_an_archived_field_has_is_not_offered(self, panel, base):
        key = wr.create_user_field(base, "Caffeine", TABLET, True)["key"]
        wr.set_flags(base, key, archived=True)
        panel._diary_refresh()
        assert "Caffeine" not in _templates_in_dropdown(panel)

    def test_all_six_can_be_made_and_then_none_is_offered(self, panel, base):
        for name in TEMPLATE_NAMES:
            _choose_template(panel, name)
        state, master = rd.read_master(base)
        assert state == rd.OK
        assert [f["name"] for f in master["fields"].values()] == TEMPLATE_NAMES
        assert list(master["fields"]) == [f"U000{i}" for i in range(1, 7)]
        assert _templates_in_dropdown(panel) == []
        assert "— Start templates —" not in [text for text, _key in _items(panel)]

    def test_alcohol_and_caffeine_have_a_time_and_the_others_have_none(self, panel, base):
        for name in TEMPLATE_NAMES:
            _choose_template(panel, name)
        with_time = {f["name"] for f in rd.read_master(base)[1]["fields"].values() if f["with_time"]}
        assert with_time == {"Alcohol", "Caffeine"}

    def test_a_value_entered_in_a_template_field_is_saved(self, qtbot, panel, base):
        _choose_template(panel, "Cycle")
        line = _line(panel, "U0001")
        line.inputs["Period"].setCurrentIndex(1)
        line.inputs["Day of cycle"].setText("12")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        entries = rd.read_day(base, _iso())[1]["entries"]
        assert entries == {"U0001": [{"values": {"Period": True, "Day of cycle": 12}}]}

    def test_a_refused_creation_says_why_and_shows_no_row(self, panel, base, monkeypatch):
        monkeypatch.setattr(wr, "create_user_field", lambda *a, **k: {"status": "rejected", "reason": "duplicate_name"})
        _choose_template(panel, "Walk")
        assert panel._diary_rows == {} and "already exists" in panel._diary_status.text()

    def test_a_failed_write_says_so(self, panel, base, monkeypatch):
        monkeypatch.setattr(wr, "create_user_field", lambda *a, **k: {"status": "failed", "reason": "write_failed"})
        _choose_template(panel, "Walk")
        assert "could not be saved" in panel._diary_status.text() and panel._diary_rows == {}

    def test_without_an_archive_folder_no_template_is_offered(self, raw_panel, app_mock):
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_refresh()
        assert _templates_in_dropdown(raw_panel) == [] and not raw_panel._diary_field_combo.isEnabled()

    def test_a_damaged_field_list_offers_nothing(self, panel, base):
        wr.create_user_field(base, "Mine", TABLET, True)
        (base / "diary_data" / "fields.json").write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        assert _templates_in_dropdown(panel) == []

    def test_a_template_that_was_made_is_gone_from_the_dropdown_at_once(self, panel, base):
        _choose_template(panel, "Walk")
        assert panel._diary_field_combo.findData("tpl:Walk") == -1, "the second click has nothing to click"
        assert len(rd.read_master(base)[1]["fields"]) == 1

    def test_choosing_a_template_keeps_typed_values(self, panel, base):
        key = _field(base, "Schmerztablette", TABLET, True)
        panel._diary_refresh()
        _line(panel, key).inputs["Anzahl"].setText("3")
        _choose_template(panel, "Walk")
        assert _line(panel, key).inputs["Anzahl"].text() == "3"


def _manage(panel, qtbot, monkeypatch, script):
    """Runs the panel's Manage fields button with exec() replaced by script(dialog); returns what script returned."""
    seen = {}

    def fake_exec(self):
        qtbot.addWidget(self)
        seen["result"] = script(self)
        return 0
    monkeypatch.setattr(DiaryManageDialog, "exec", fake_exec)
    qtbot.mouseClick(panel._diary_manage_btn, Qt.MouseButton.LeftButton)
    return seen.get("result")


@pytest.fixture
def managed(qtbot, panel, base):
    """A manage dialog over the real writer, with fields: Garmin Hydration, your Painkiller (favorite), Walk."""
    wr.activate_catalog_field(base, "G002")
    painkiller = wr.create_user_field(base, "Painkiller", TABLET, True)["key"]
    wr.set_flags(base, painkiller, favorite=True)
    wr.create_user_field(base, "Walk", YESNO_VALUES, False)
    panel._diary_refresh()
    dialog = DiaryManageDialog(panel, panel._diary_fields, panel._diary_rename_field, panel._diary_archive_field)
    qtbot.addWidget(dialog)
    return dialog


def _dialog_with(qtbot, panel, fields, renamer=None, archiver=None):
    dialog = DiaryManageDialog(panel, lambda: fields, renamer or (lambda *a: {}), archiver or (lambda *a: {}))
    qtbot.addWidget(dialog)
    return dialog


class TestManageDialog:

    def test_it_lists_every_field_with_its_kind(self, managed):
        assert list(managed.rows) == ["G002", "U0001", "U0002"]
        assert managed.rows["G002"].name.text() == "Hydration" and managed.rows["G002"].kind.text() == "Garmin field"
        assert managed.rows["U0001"].kind.text() == "Your field"

    def test_without_fields_it_says_so(self, qtbot, panel):
        dialog = _dialog_with(qtbot, panel, {})
        assert dialog.rows == {} and not dialog._empty.isHidden()

    def test_with_fields_the_empty_hint_is_hidden(self, managed):
        assert managed._empty.isHidden()

    def test_rename_changes_the_name_in_the_list_and_keeps_the_key(self, managed, base):
        managed.rows["U0001"].name.setText("Tablet")
        managed.rows["U0001"].rename_btn.click()
        master = rd.read_master(base)[1]
        assert master["fields"]["U0001"]["name"] == "Tablet" and list(master["fields"]) == ["G002", "U0001", "U0002"]
        assert managed.rows["U0001"].name.text() == "Tablet" and managed.error_text() == ""

    def test_enter_in_the_name_box_renames_too(self, managed, base):
        managed.rows["U0002"].name.setText("Stroll")
        managed.rows["U0002"].name.returnPressed.emit()
        assert rd.read_master(base)[1]["fields"]["U0002"]["name"] == "Stroll"

    def test_a_garmin_field_can_be_renamed_and_keeps_its_definition(self, managed, base):
        managed.rows["G002"].name.setText("Water")
        managed.rows["G002"].rename_btn.click()
        field = rd.read_master(base)[1]["fields"]["G002"]
        assert field["name"] == "Water" and field["maps_to"] == "get_hydration_data"
        assert field["values"] == [{"label": "Amount", "type": "number", "unit": "ml"}]

    def test_the_rename_changes_nothing_but_the_name(self, managed, base):
        before = rd.read_master(base)[1]["fields"]["U0001"]
        managed.rows["U0001"].name.setText("Tablet")
        managed.rows["U0001"].rename_btn.click()
        after = rd.read_master(base)[1]["fields"]["U0001"]
        assert {k: v for k, v in after.items() if k != "name"} == {k: v for k, v in before.items() if k != "name"}

    def test_a_name_that_is_taken_is_refused_with_a_reason_and_the_text_stays(self, managed, base):
        managed.rows["U0001"].name.setText("walk")
        managed.rows["U0001"].rename_btn.click()
        assert "already exists" in managed.error_text()
        assert rd.read_master(base)[1]["fields"]["U0001"]["name"] == "Painkiller"
        assert managed.rows["U0001"].name.text() == "walk", "what was typed stays so that it can be corrected"

    def test_the_name_of_a_catalogue_field_is_refused(self, managed, base):
        managed.rows["U0001"].name.setText("Blood pressure")
        managed.rows["U0001"].rename_btn.click()
        assert "already exists" in managed.error_text()

    def test_an_empty_name_is_refused(self, managed, base):
        managed.rows["U0001"].name.setText("   ")
        managed.rows["U0001"].rename_btn.click()
        assert "Enter a name" in managed.error_text()
        assert rd.read_master(base)[1]["fields"]["U0001"]["name"] == "Painkiller"

    def test_the_same_name_again_is_no_error(self, managed, base):
        managed.rows["U0001"].rename_btn.click()
        assert managed.error_text() == ""

    def test_the_error_goes_after_the_next_good_change(self, managed, base):
        managed.rows["U0001"].name.setText("walk")
        managed.rows["U0001"].rename_btn.click()
        managed.rows["U0001"].name.setText("Tablet")
        managed.rows["U0001"].rename_btn.click()
        assert managed.error_text() == ""

    def test_archiving_hides_the_field_and_puts_it_last(self, managed, base):
        managed.rows["G002"].archive_btn.click()
        assert rd.read_master(base)[1]["fields"]["G002"]["archived"] is True
        assert list(managed.rows) == ["U0001", "U0002", "G002"], "archived fields come after the active ones"
        assert managed.rows["G002"].archive_btn.text() == "Restore" and "archived" in managed.rows["G002"].kind.text()

    def test_restoring_shows_it_again(self, managed, base):
        managed.rows["U0002"].archive_btn.click()
        managed.rows["U0002"].archive_btn.click()
        assert rd.read_master(base)[1]["fields"]["U0002"]["archived"] is False
        assert managed.rows["U0002"].archive_btn.text() == "Archive"

    def test_a_refusal_of_the_archiver_is_shown(self, qtbot, panel):
        fields = {"U0001": {"name": "A", "archived": False}}
        dialog = _dialog_with(qtbot, panel, fields, archiver=lambda *a: {"status": "rejected", "reason": "typed_values"})
        dialog.rows["U0001"].archive_btn.click()
        assert "typed" in dialog.error_text() and dialog.rows["U0001"].archive_btn.text() == "Archive"

    def test_a_failed_write_of_the_renamer_is_shown(self, qtbot, panel):
        fields = {"U0001": {"name": "A", "archived": False}}
        dialog = _dialog_with(qtbot, panel, fields, renamer=lambda *a: {"status": "failed", "reason": "write_failed"})
        dialog.rows["U0001"].rename_btn.click()
        assert "could not be saved" in dialog.error_text()

    def test_an_unknown_refusal_names_the_action(self, qtbot, panel):
        fields = {"U0001": {"name": "A", "archived": False}}
        dialog = _dialog_with(qtbot, panel, fields,
                              renamer=lambda *a: {"status": "rejected", "reason": "x1"},
                              archiver=lambda *a: {"status": "rejected", "reason": "x2"})
        dialog.rows["U0001"].rename_btn.click()
        assert "renamed" in dialog.error_text() and "x1" in dialog.error_text()
        dialog.rows["U0001"].archive_btn.click()
        assert "archived" in dialog.error_text()
        fields["U0001"]["archived"] = True
        dialog._rebuild()
        dialog.rows["U0001"].archive_btn.click()
        assert "restored" in dialog.error_text()

    def test_close_is_no_default_button(self, managed):
        assert not managed._close_btn.autoDefault() and not managed._close_btn.isDefault()


class TestManageFieldsInThePanel:

    def test_the_button_is_off_without_an_archive_folder_and_on_with_one(self, raw_panel, app_mock):
        assert not raw_panel._diary_manage_btn.isEnabled()
        raw_panel._diary_refresh()
        assert raw_panel._diary_manage_btn.isEnabled()
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_refresh()
        assert not raw_panel._diary_manage_btn.isEnabled()

    def test_the_button_is_off_while_the_field_list_is_damaged(self, panel, base):
        wr.create_user_field(base, "Mine", TABLET, True)
        (base / "diary_data" / "fields.json").write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        assert not panel._diary_manage_btn.isEnabled()

    def test_the_dialog_gets_the_fields_of_the_list(self, qtbot, panel, base, monkeypatch):
        wr.create_user_field(base, "Walk", YESNO_VALUES, False)
        panel._diary_refresh()
        assert _manage(panel, qtbot, monkeypatch, lambda d: list(d.rows)) == ["U0001"]

    def test_a_rename_shows_in_the_row_and_in_the_dropdown(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        other = _field(base, "Walk", YESNO_VALUES, False, favorite=False)
        panel._diary_refresh()

        def script(dialog):
            dialog.rows[fav].name.setText("Tablet")
            dialog.rows[fav].rename_btn.click()
            dialog.rows[other].name.setText("Stroll")
            dialog.rows[other].rename_btn.click()
        _manage(panel, qtbot, monkeypatch, script)
        assert panel._diary_rows[fav].name_label.text() == "Tablet"
        assert ("Stroll", other) in _items(panel)

    def test_a_rename_does_not_touch_the_day_file(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        _write(base, _iso(), "Note", {fav: [{"time": "08:00", "values": {"Anzahl": 1}}]})
        panel._diary_refresh()
        before = _day_path(base, _iso()).read_bytes()

        def script(dialog):
            dialog.rows[fav].name.setText("Tablet")
            dialog.rows[fav].rename_btn.click()
        _manage(panel, qtbot, monkeypatch, script)
        assert _day_path(base, _iso()).read_bytes() == before
        assert not panel._diary_is_dirty()

    def test_typed_values_survive_a_rename(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        _line(panel, fav).inputs["Anzahl"].setText("4")

        def script(dialog):
            dialog.rows[fav].name.setText("Tablet")
            dialog.rows[fav].rename_btn.click()
        _manage(panel, qtbot, monkeypatch, script)
        assert _line(panel, fav).inputs["Anzahl"].text() == "4" and panel._diary_is_dirty()

    def test_an_archived_favorite_leaves_the_list_and_the_dropdown(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        _manage(panel, qtbot, monkeypatch, lambda d: d.rows[fav].archive_btn.click())
        assert fav not in panel._diary_rows and fav not in _keys_in_dropdown(panel)
        assert rd.read_master(base)[1]["fields"][fav]["archived"] is True

    def test_a_restored_favorite_is_a_favorite_row_again(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()

        def script(dialog):
            dialog.rows[fav].archive_btn.click()
            dialog.rows[fav].archive_btn.click()
        _manage(panel, qtbot, monkeypatch, script)
        assert fav in panel._diary_rows and panel._diary_rows[fav].favorite

    def test_an_archived_field_added_for_the_day_leaves_with_it(self, qtbot, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True, favorite=False)
        panel._diary_refresh()
        _choose(panel, key)
        assert key in panel._diary_rows
        _manage(panel, qtbot, monkeypatch, lambda d: d.rows[key].archive_btn.click())
        assert key not in panel._diary_rows and key not in panel._diary_added

    def test_a_restored_field_is_offered_again(self, qtbot, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True, favorite=False)
        panel._diary_refresh()

        def script(dialog):
            dialog.rows[key].archive_btn.click()
            assert key not in _keys_in_dropdown(panel)
            dialog.rows[key].archive_btn.click()
        _manage(panel, qtbot, monkeypatch, script)
        assert key in _keys_in_dropdown(panel)

    def test_a_field_with_typed_values_is_not_archived(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        _line(panel, fav).inputs["Anzahl"].setText("2")

        def script(dialog):
            dialog.rows[fav].archive_btn.click()
            return dialog.error_text()
        error = _manage(panel, qtbot, monkeypatch, script)
        assert "typed" in error
        assert fav in panel._diary_rows and _line(panel, fav).inputs["Anzahl"].text() == "2"
        assert rd.read_master(base)[1]["fields"][fav]["archived"] is False

    def test_a_field_with_entries_on_the_day_stays_visible_when_archived(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        _write(base, _iso(), "Note", {fav: [{"time": "08:00", "values": {"Anzahl": 1}}]})
        panel._diary_refresh()
        _manage(panel, qtbot, monkeypatch, lambda d: d.rows[fav].archive_btn.click())
        assert fav in panel._diary_rows, "the day has entries for it: they must stay visible and editable"
        assert _line(panel, fav).inputs["Anzahl"].text() == "1"
        assert fav not in _keys_in_dropdown(panel)

    def test_an_archived_field_is_gone_on_another_day_without_entries(self, qtbot, panel, base, monkeypatch):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        _manage(panel, qtbot, monkeypatch, lambda d: d.rows[fav].archive_btn.click())
        _pick(panel, _iso(-1))
        assert fav not in panel._diary_rows

    def test_the_panel_archive_function_refuses_on_its_own_too(self, panel, base):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        _line(panel, fav).inputs["Anzahl"].setText("2")
        result = panel._diary_archive_field(fav, True)
        assert result == {"status": "rejected", "reason": "typed_values"}
        assert panel._diary_archive_field(fav, False)["status"] == "unchanged", "restoring is never refused"

    def test_a_rename_refused_by_the_writer_leaves_the_rows_alone(self, panel, base):
        fav = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        result = panel._diary_rename_field(fav, "Blood pressure")
        assert result["status"] == "rejected" and panel._diary_rows[fav].name_label.text() == "Painkiller"

    def test_opening_it_without_a_usable_list_does_nothing(self, panel, base, monkeypatch):
        wr.create_user_field(base, "Mine", TABLET, True)
        (base / "diary_data" / "fields.json").write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        monkeypatch.setattr(DiaryManageDialog, "exec", lambda self: pytest.fail("the dialog must not open"))
        panel._diary_on_manage_clicked()


# ══════════════════════════════════════════════════════════════════════════════
#  Text values and groups of alternatives (steps or distance)
# ══════════════════════════════════════════════════════════════════════════════

class TestCleanText:

    @pytest.mark.parametrize("text,expected", [
        ("", ""), ("   ", ""), ("red wine", "red wine"), ("  red   wine ", "red wine"),
        ("a\tb", "a b"), ("a\nb", "a b"), ("a\r\nb", "a b"), ("a\x00b", "a b"), ("a\x7fb", "a b"), ("\n\t", ""),
        ("Bier – 0,5 l ☺ 啤酒", "Bier – 0,5 l ☺ 啤酒"),
    ])
    def test_what_is_stored(self, text, expected):
        assert clean_text(text) == expected

    def test_the_result_is_always_accepted_by_the_model(self):
        from diary import diary_model as model
        for text in ("a\tb", "x\x00y", "  z  ", "line1\nline2"):
            assert model._is_text(clean_text(text))


ALCOHOL = {"name": "Alcohol", "set": "user", "with_time": True,
           "values": [{"label": "Drinks", "type": "number", "unit": "units"}, {"label": "Type", "type": "text"}]}
WALK_DEF = {"name": "Walk", "set": "user", "with_time": False,
            "values": [{"label": "Done", "type": "yesno"},
                       {"label": "Steps", "type": "number", "unit": "steps", "group": "amount"},
                       {"label": "Distance", "type": "number", "unit": "km", "group": "amount"}]}
TWO_GROUPS = {"name": "Two", "set": "user", "with_time": False,
              "values": [{"label": "a", "type": "number", "unit": "u", "group": "g1"},
                         {"label": "b", "type": "number", "unit": "v", "group": "g1"},
                         {"label": "c", "type": "number", "unit": "w", "group": "g2"},
                         {"label": "d", "type": "number", "unit": "z", "group": "g2"}]}


class TestTextValueInTheEditor:

    def test_a_text_box_has_a_length_limit_and_no_unit(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        box = editor.lines[0].inputs["Type"]
        assert box.maxLength() == 200 and isinstance(box, QLineEdit)
        unit_labels = [lb.text() for lb in editor.lines[0].findChildren(QLabel)]
        assert "units" in unit_labels and unit_labels.count("units") == 1

    def test_a_typed_text_becomes_a_clean_entry(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("  red   wine ")
        assert editor.collect() == ([{"time": "09:30", "values": {"Type": "red wine"}}], [])

    def test_a_text_alone_is_an_entry_and_a_number_with_it_too(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Drinks"].setText("2")
        editor.lines[0].inputs["Type"].setText("beer")
        assert editor.collect()[0] == [{"time": "09:30", "values": {"Drinks": 2, "Type": "beer"}}]

    def test_a_text_of_only_space_is_no_entry(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("    ")
        assert editor.collect() == ([], []) and not editor.has_content()

    def test_a_text_is_content(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("x")
        assert editor.has_content()

    def test_a_text_is_never_marked_red_or_called_a_bad_number(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("not a number at all")
        entries, errors = editor.collect()
        assert errors == [] and len(entries) == 1
        assert "e05555" not in editor.lines[0].inputs["Type"].styleSheet()

    def test_a_stored_text_is_shown(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL, [{"time": "20:15", "values": {"Drinks": 1, "Type": "whisky"}}])
        assert editor.lines[0].inputs["Type"].text() == "whisky" and editor.lines[0].inputs["Drinks"].text() == "1"

    def test_a_text_survives_the_raw_state(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("gin")
        other = _editor(qtbot, colors, ALCOHOL)
        other.set_raw_state(editor.raw_state())
        assert other.lines[0].inputs["Type"].text() == "gin"

    def test_a_text_that_has_a_line_break_pasted_in_is_stored_on_one_line(self, qtbot, colors):
        editor = _editor(qtbot, colors, ALCOHOL)
        editor.lines[0].inputs["Type"].setText("a\nb")
        assert editor.collect()[0][0]["values"]["Type"] == "a b"


class TestAlternativesInTheEditor:

    def test_a_selector_chooses_between_the_members_and_only_one_box_is_shown(self, qtbot, colors):
        line = _editor(qtbot, colors, WALK_DEF).lines[0]
        selector = line.group_selectors["amount"]
        assert [selector.itemText(i) for i in range(selector.count())] == ["Steps", "Distance"]
        assert not line.inputs["Steps"].isHidden() and line.inputs["Distance"].isHidden()

    def test_the_unit_goes_with_its_box(self, qtbot, colors):
        line = _editor(qtbot, colors, WALK_DEF).lines[0]
        units = {lb.text(): lb for lb in line.findChildren(QLabel) if lb.text() in ("steps", "km")}
        assert not units["steps"].isHidden() and units["km"].isHidden()
        line.group_selectors["amount"].setCurrentIndex(1)
        assert units["steps"].isHidden() and not units["km"].isHidden()

    def test_the_members_have_no_caption_of_their_own(self, qtbot, colors):
        line = _editor(qtbot, colors, WALK_DEF).lines[0]
        captions = [lb.text() for lb in line.findChildren(QLabel)]
        assert "Done" in captions and "Steps" not in captions and "Distance" not in captions

    def test_choosing_the_other_member_shows_it_and_hides_the_first(self, qtbot, colors):
        line = _editor(qtbot, colors, WALK_DEF).lines[0]
        line.group_selectors["amount"].setCurrentIndex(1)
        assert line.inputs["Steps"].isHidden() and not line.inputs["Distance"].isHidden()

    def test_choosing_the_other_member_empties_the_box_that_was_shown(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.inputs["Steps"].setText("5000")
        line.group_selectors["amount"].setCurrentIndex(1)
        assert line.inputs["Steps"].text() == ""
        assert editor.collect() == ([], []) and not editor.has_content()

    def test_a_red_mark_goes_with_the_emptied_box(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.inputs["Steps"].setText("many")
        editor.collect()
        assert "e05555" in line.inputs["Steps"].styleSheet()
        line.group_selectors["amount"].setCurrentIndex(1)
        assert "e05555" not in line.inputs["Steps"].styleSheet()
        assert editor.collect() == ([], [])

    def test_only_the_chosen_member_is_stored(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.group_selectors["amount"].setCurrentIndex(1)
        line.inputs["Distance"].setText("3,5")
        line.inputs["Done"].setCurrentIndex(1)
        assert editor.collect()[0] == [{"values": {"Done": True, "Distance": 3.5}}]

    def test_text_left_in_a_hidden_box_is_ignored(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.inputs["Distance"].setText("9")       # hidden: Steps is chosen
        assert editor.collect() == ([], []) and not editor.has_content()

    def test_a_bad_number_in_a_hidden_box_is_no_error(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.inputs["Distance"].setText("abc")
        line.inputs["Steps"].setText("100")
        assert editor.collect() == ([{"values": {"Steps": 100}}], [])

    def test_a_bad_number_in_the_chosen_box_is_an_error(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        editor.lines[0].inputs["Steps"].setText("abc")
        assert editor.collect() == ([], ["Steps"])

    def test_a_stored_entry_with_the_second_member_chooses_it(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF, [{"values": {"Distance": 4.2}}])
        line = editor.lines[0]
        assert line.group_selectors["amount"].currentIndex() == 1
        assert line.inputs["Distance"].text() == "4.2" and not line.inputs["Distance"].isHidden()
        assert line.inputs["Steps"].isHidden()
        assert editor.collect()[0] == [{"values": {"Distance": 4.2}}]

    def test_a_stored_entry_without_a_member_starts_on_the_first(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF, [{"values": {"Done": True}}])
        assert editor.lines[0].group_selectors["amount"].currentIndex() == 0

    def test_two_groups_work_independently(self, qtbot, colors):
        editor = _editor(qtbot, colors, TWO_GROUPS)
        line = editor.lines[0]
        assert set(line.group_selectors) == {"g1", "g2"}
        line.group_selectors["g2"].setCurrentIndex(1)
        line.inputs["a"].setText("1")
        line.inputs["d"].setText("2")
        assert editor.collect()[0] == [{"values": {"a": 1, "d": 2}}]
        assert line.inputs["b"].isHidden() and line.inputs["c"].isHidden()

    def test_the_choice_survives_the_raw_state_without_emptying_the_boxes(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.group_selectors["amount"].setCurrentIndex(1)
        line.inputs["Distance"].setText("7")
        other = _editor(qtbot, colors, WALK_DEF)
        other.set_raw_state(editor.raw_state())
        assert other.lines[0].group_selectors["amount"].currentIndex() == 1
        assert other.lines[0].inputs["Distance"].text() == "7" and not other.lines[0].inputs["Distance"].isHidden()
        assert other.lines[0].inputs["Steps"].isHidden()
        assert other.raw_state() == editor.raw_state()

    def test_the_selector_is_switched_off_with_the_rest(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        editor.set_editable(False)
        assert not editor.lines[0].group_selectors["amount"].isEnabled()
        editor.set_editable(True)
        assert editor.lines[0].group_selectors["amount"].isEnabled()

    def test_a_field_with_time_has_a_selector_in_every_line(self, qtbot, colors):
        defn = {**WALK_DEF, "with_time": True}
        editor = _editor(qtbot, colors, defn)
        editor.add_btn.click()
        assert all("amount" in line.group_selectors for line in editor.lines)
        editor.lines[1].group_selectors["amount"].setCurrentIndex(1)
        assert editor.lines[0].group_selectors["amount"].currentIndex() == 0, "lines choose on their own"

    def test_clear_values_leaves_the_choice(self, qtbot, colors):
        editor = _editor(qtbot, colors, WALK_DEF)
        line = editor.lines[0]
        line.group_selectors["amount"].setCurrentIndex(1)
        line.inputs["Distance"].setText("2")
        line.clear_values()
        assert line.inputs["Distance"].text() == "" and line.group_selectors["amount"].currentIndex() == 1


class TestAlternativesInTheDialog:

    @pytest.fixture
    def calls(self):
        return []

    @pytest.fixture
    def dialog(self, qtbot, panel, calls):
        def creator(name, values, with_time, favorite):
            calls.append((name, values, with_time, favorite))
            return {"status": "written", "key": "U0001"}
        widget = DiaryFieldDialog(panel, creator)
        qtbot.addWidget(widget)
        widget._name.setText("Walk")
        return widget

    @staticmethod
    def _rows(dialog, *labels):
        for index, label in enumerate(labels):
            if index > 0:
                dialog._add_btn.click()
            dialog._rows[index].label.setText(label)

    def test_a_text_value_has_no_unit_and_is_collected_as_text(self, dialog):
        dialog._rows[0].label.setText("Type")
        dialog._rows[0].unit.setText("x")
        dialog._rows[0].kind.setCurrentIndex(dialog._rows[0].kind.findData("text"))
        assert not dialog._rows[0].unit.isEnabled() and dialog._rows[0].unit.text() == ""
        assert dialog.collect()[1] == [{"label": "Type", "type": "text"}]

    def test_the_kind_list_has_number_yes_no_and_text(self, dialog):
        kind = dialog._rows[0].kind
        assert [kind.itemText(i) for i in range(kind.count())] == ["Number", "Yes/No", "Text"]

    def test_the_first_row_cannot_be_an_alternative(self, dialog):
        assert not dialog._rows[0].alt.isEnabled() and not dialog._rows[0].alt.isChecked()

    def test_a_number_below_a_number_can_be_an_alternative(self, dialog):
        self._rows(dialog, "Steps", "Distance")
        assert dialog._rows[1].alt.isEnabled()

    def test_a_number_below_a_yes_no_cannot(self, dialog):
        self._rows(dialog, "Done", "Steps")
        dialog._rows[0].kind.setCurrentIndex(1)
        assert not dialog._rows[1].alt.isEnabled()

    def test_a_yes_no_or_text_cannot_be_an_alternative(self, dialog):
        self._rows(dialog, "Steps", "Other")
        dialog._rows[1].kind.setCurrentIndex(1)
        assert not dialog._rows[1].alt.isEnabled()
        dialog._rows[1].kind.setCurrentIndex(2)
        assert not dialog._rows[1].alt.isEnabled()

    def test_changing_the_kind_takes_the_mark_away(self, dialog):
        self._rows(dialog, "Steps", "Distance")
        dialog._rows[1].alt.setChecked(True)
        dialog._rows[1].kind.setCurrentIndex(2)
        assert not dialog._rows[1].alt.isChecked()

    def test_changing_the_row_above_takes_the_mark_away(self, dialog):
        self._rows(dialog, "Steps", "Distance")
        dialog._rows[1].alt.setChecked(True)
        dialog._rows[0].kind.setCurrentIndex(1)
        assert not dialog._rows[1].alt.isChecked() and not dialog._rows[1].alt.isEnabled()

    def test_removing_the_row_above_takes_the_mark_away(self, dialog):
        self._rows(dialog, "Steps", "Distance")
        dialog._rows[1].alt.setChecked(True)
        dialog._rows[0].remove_btn.click()
        assert len(dialog._rows) == 1 and not dialog._rows[0].alt.isChecked()
        assert "group" not in dialog.collect()[1][0]

    def test_two_rows_marked_become_one_group(self, dialog):
        self._rows(dialog, "Steps", "Distance")
        dialog._rows[0].unit.setText("steps")
        dialog._rows[1].unit.setText("km")
        dialog._rows[1].alt.setChecked(True)
        assert dialog.collect()[1] == [{"label": "Steps", "type": "number", "unit": "steps", "group": "alt1"},
                                       {"label": "Distance", "type": "number", "unit": "km", "group": "alt1"}]

    def test_three_in_a_row_are_one_group(self, dialog):
        self._rows(dialog, "a", "b", "c")
        dialog._rows[1].alt.setChecked(True)
        dialog._rows[2].alt.setChecked(True)
        assert {v["group"] for v in dialog.collect()[1]} == {"alt1"}

    def test_separate_pairs_are_separate_groups(self, dialog):
        self._rows(dialog, "a", "b", "c", "d")
        dialog._rows[1].alt.setChecked(True)
        dialog._rows[3].alt.setChecked(True)
        assert [v.get("group") for v in dialog.collect()[1]] == ["alt1", "alt1", "alt2", "alt2"]

    def test_a_row_that_is_not_marked_has_no_group(self, dialog):
        self._rows(dialog, "a", "b", "c")
        dialog._rows[1].alt.setChecked(True)
        assert [v.get("group") for v in dialog.collect()[1]] == ["alt1", "alt1", None]

    def test_collecting_twice_gives_the_same_names(self, dialog):
        self._rows(dialog, "a", "b")
        dialog._rows[1].alt.setChecked(True)
        assert dialog.collect() == dialog.collect()

    def test_the_creator_gets_the_groups(self, dialog, calls):
        self._rows(dialog, "Steps", "Distance")
        dialog._rows[1].alt.setChecked(True)
        dialog._create_btn.click()
        assert calls[0][1][0]["group"] == "alt1" and calls[0][1][1]["group"] == "alt1"

    @pytest.mark.parametrize("code,expected", [
        ("value1_group_not_allowed", "Only number values"),
        ("group_single:alt1", "at least two values"),
        ("group_not_together:alt1", "next to each other"),
    ])
    def test_the_refusals_about_groups_become_sentences(self, code, expected):
        assert expected in describe_failure({"reason": "invalid_definition", "errors": [code]})

    def test_the_writer_accepts_what_the_dialog_collects(self, qtbot, panel, base):
        def creator(name, values, with_time, favorite):
            return wr.create_user_field(base, name, values, with_time)
        widget = DiaryFieldDialog(panel, creator)
        qtbot.addWidget(widget)
        widget._name.setText("Walk")
        self._rows(widget, "Steps", "Distance", "Note")
        widget._rows[1].alt.setChecked(True)
        widget._rows[2].kind.setCurrentIndex(2)
        widget._create_btn.click()
        assert widget.created_key == "U0001"
        assert rd.read_master(base)[1]["fields"]["U0001"]["values"][1]["group"] == "alt1"


class TestTextAndAlternativesInThePanel:

    def test_the_hint_names_the_alternatives_and_the_text(self, panel):
        assert panel._diary_hint(WALK_DEF) == "Done (yes/no), Steps (steps) or Distance (km)"
        assert panel._diary_hint(ALCOHOL) == "Drinks (units), Type (text) · with time"
        assert panel._diary_hint(TWO_GROUPS) == "a (u) or b (v), c (w) or d (z)"

    def test_a_group_without_a_unit_shows_the_bare_label(self, panel):
        defn = {"name": "N", "set": "user", "with_time": False,
                "values": [{"label": "x", "type": "number", "unit": "", "group": "g"},
                           {"label": "y", "type": "number", "unit": "", "group": "g"}]}
        assert panel._diary_hint(defn) == "x or y"

    def test_the_walk_template_has_done_and_the_alternatives(self, panel, base):
        _choose_template(panel, "Walk")
        field = rd.read_master(base)[1]["fields"]["U0001"]
        assert field["values"] == WALK_DEF["values"] and field["with_time"] is False
        line = _line(panel, "U0001")
        assert set(line.group_selectors) == {"amount"}
        assert panel._diary_rows["U0001"].hint_label.text() == "Done (yes/no), Steps (steps) or Distance (km)"

    def test_the_alcohol_template_has_a_text_value(self, panel, base):
        _choose_template(panel, "Alcohol")
        field = rd.read_master(base)[1]["fields"]["U0001"]
        assert field["values"] == ALCOHOL["values"] and field["with_time"] is True

    def test_steps_are_saved_without_the_distance(self, qtbot, panel, base):
        _choose_template(panel, "Walk")
        line = _line(panel, "U0001")
        line.inputs["Done"].setCurrentIndex(1)
        line.inputs["Steps"].setText("8000")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {"U0001": [{"values": {"Done": True, "Steps": 8000}}]}

    def test_a_distance_is_saved_and_shown_again_with_its_box(self, qtbot, panel, base):
        _choose_template(panel, "Walk")
        line = _line(panel, "U0001")
        line.group_selectors["amount"].setCurrentIndex(1)
        line.inputs["Distance"].setText("5,2")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"] == {"U0001": [{"values": {"Distance": 5.2}}]}
        line = _line(panel, "U0001")
        assert line.group_selectors["amount"].currentIndex() == 1 and line.inputs["Distance"].text() == "5.2"
        assert not panel._diary_is_dirty()

    def test_a_stored_distance_is_shown_when_the_day_is_picked(self, panel, base):
        _choose_template(panel, "Walk")
        wr.save_day(base, _iso(-1), "", {"U0001": [{"values": {"Distance": 3}}]}, now=datetime.now())
        _pick(panel, _iso(-1))
        line = _line(panel, "U0001")
        assert line.group_selectors["amount"].currentIndex() == 1 and line.inputs["Distance"].text() == "3"

    def test_the_choice_and_the_typed_value_survive_a_rebuild_of_the_rows(self, panel, base):
        _choose_template(panel, "Walk")
        line = _line(panel, "U0001")
        line.group_selectors["amount"].setCurrentIndex(1)
        line.inputs["Distance"].setText("2")
        _choose_template(panel, "Alcohol")
        line = _line(panel, "U0001")
        assert line.group_selectors["amount"].currentIndex() == 1 and line.inputs["Distance"].text() == "2"
        assert panel._diary_is_dirty()

    def test_a_typed_text_makes_the_day_dirty_and_is_saved_with_the_time(self, qtbot, panel, base):
        _choose_template(panel, "Alcohol")
        panel._diary_now = lambda: datetime(2026, 11, 18, 21, 45)
        _line(panel, "U0001").inputs["Type"].setText("red wine")
        assert panel._diary_is_dirty()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        entries = rd.read_day(base, _iso())[1]["entries"]["U0001"]
        assert len(entries) == 1 and entries[0]["values"] == {"Type": "red wine"} and "time" in entries[0]

    def test_drinks_and_type_are_saved_together(self, qtbot, panel, base):
        _choose_template(panel, "Alcohol")
        line = _line(panel, "U0001")
        line.inputs["Drinks"].setText("2")
        line.inputs["Type"].setText("beer")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, _iso())[1]["entries"]["U0001"][0]["values"] == {"Drinks": 2, "Type": "beer"}

    def test_a_field_with_a_group_can_be_made_in_the_create_dialog_flow(self, panel, base):
        res = panel._diary_create_field("Walk2", WALK_DEF["values"], False, True)
        assert res["status"] == "written"
        panel._diary_refresh()
        assert set(_line(panel, res["key"]).group_selectors) == {"amount"}


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4f: changing an earlier day, the history
# ══════════════════════════════════════════════════════════════════════════════

YESTERDAY = datetime.now() - timedelta(days=1)

SNAPSHOT = {
    "U0001": {"name": "Painkiller", "set": "user", "with_time": True,
              "values": [{"label": "Count", "type": "number", "unit": "pcs"}, {"label": "Type", "type": "text"}]},
    "U0002": {"name": "Walk", "set": "user", "with_time": False,
              "values": [{"label": "Done", "type": "yesno"}, {"label": "Steps", "type": "number", "unit": ""}]},
}


class TestDescribeState:

    def test_note_and_entries_are_listed_by_field_name(self):
        before = {"note": "slept badly", "entries": {"U0001": [{"time": "08:00", "values": {"Count": 2, "Type": "aspirin"}}],
                                                     "U0002": [{"values": {"Done": True, "Steps": 5000}}]}}
        assert describe_state(before, SNAPSHOT).split("\n") == [
            "Note:", "slept badly", "", "Entries:",
            "Painkiller", "  08:00  Count 2 pcs, Type aspirin",
            "Walk", "  Done yes, Steps 5000"]

    def test_a_no_is_shown_as_no(self):
        assert "Done no" in describe_state({"note": "", "entries": {"U0002": [{"values": {"Done": False}}]}}, SNAPSHOT)

    def test_an_empty_state_says_none_twice(self):
        assert describe_state({"note": "", "entries": {}}, SNAPSHOT).split("\n") == ["Note:", "(none)", "", "Entries:", "(none)"]

    def test_a_key_without_a_definition_or_an_unknown_label_is_skipped(self):
        before = {"note": "x", "entries": {"U0009": [{"values": {"a": 1}}], "U0002": [{"values": {"Done": True, "zzz": 5}}]}}
        text = describe_state(before, SNAPSHOT)
        assert "U0009" not in text and "zzz" not in text and "Done yes" in text

    def test_a_field_with_an_empty_list_is_left_out(self):
        text = describe_state({"note": "", "entries": {"U0001": []}}, SNAPSHOT)
        assert "Painkiller" not in text and text.endswith("(none)")

    def test_several_entries_are_one_line_each_in_order(self):
        before = {"note": "", "entries": {"U0001": [{"time": "08:00", "values": {"Count": 1}},
                                                     {"time": "20:30", "values": {"Count": 2}}]}}
        lines = describe_state(before, SNAPSHOT).split("\n")
        assert lines[-2:] == ["  08:00  Count 1 pcs", "  20:30  Count 2 pcs"]

    def test_a_number_without_a_unit_has_no_trailing_space(self):
        text = describe_state({"note": "", "entries": {"U0002": [{"values": {"Steps": 7}}]}}, SNAPSHOT)
        assert "  Steps 7" in text and "Steps 7 " not in text


class TestSummarizeState:

    @pytest.mark.parametrize("before,expected", [
        ({"note": "", "entries": {}}, "(no note) · 0 entries"),
        ({"note": "short", "entries": {"U0001": [{}]}}, "short · 1 entry"),
        ({"note": "a\n  b\tc", "entries": {"U0001": [{}, {}], "U0002": [{}]}}, "a b c · 3 entries"),
        ({"note": "x" * 40, "entries": {}}, "x" * 40 + " · 0 entries"),
        ({"note": "x" * 41, "entries": {}}, "x" * 40 + "… · 0 entries"),
    ])
    def test_one_line(self, before, expected):
        assert summarize_state(before) == expected


def _past_day(base, key, note="old note", count=1, delta=-1):
    """A day that was first saved on an earlier calendar day: changing it needs the history."""
    when = datetime.now() - timedelta(days=1)
    _write(base, _iso(delta), note, {key: [{"time": "08:00", "values": {"Anzahl": count}}]}, now=when)
    return _iso(delta)


def _with_history(base, key):
    """A past day with two earlier states in its history; the day holds 'three'."""
    day = _past_day(base, key, "one", 1)
    wr.save_day(base, day, "two", {key: [{"time": "08:00", "values": {"Anzahl": 2}}]}, now=datetime.now(), keep_history=True)
    wr.save_day(base, day, "three", {key: [{"time": "08:00", "values": {"Anzahl": 3}}]}, now=datetime.now(), keep_history=True)
    return day


class TestChangingAnEarlierDay:

    @pytest.fixture
    def asked(self, panel):
        calls = []
        panel._diary_ask_history = lambda day: calls.append(day) or True
        return calls

    def test_a_changed_earlier_day_asks_and_keeps_the_old_state(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("new note")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert asked == [day]
        stored = rd.read_day(base, day)[1]
        assert stored["note"] == "new note" and len(stored["history"]) == 1
        assert stored["history"][0]["before"]["note"] == "old note"
        assert "previous state is in the history" in panel._diary_status.text()

    def test_the_second_save_of_the_same_day_does_not_ask_again(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("two")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        panel._diary_note.setPlainText("three")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert asked == [day]
        assert [h["before"]["note"] for h in rd.read_day(base, day)[1]["history"]] == ["old note", "two"]

    def test_the_agreement_is_for_the_day_shown_only(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day1 = _past_day(base, key, delta=-1)
        day2 = _past_day(base, key, delta=-2)
        panel._diary_refresh()
        _pick(panel, day1)
        panel._diary_note.setPlainText("a")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        _pick(panel, day2)
        panel._diary_note.setPlainText("b")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert asked == [day1, day2]

    def test_declining_saves_nothing_and_keeps_what_was_typed(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("new note")
        _line(panel, key).inputs["Anzahl"].setText("9")
        before = _day_path(base, day).read_bytes()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)     # the fixture answers No
        assert _day_path(base, day).read_bytes() == before
        assert "Not saved" in panel._diary_status.text() and panel._diary_is_dirty()
        assert panel._diary_note.toPlainText() == "new note" and _line(panel, key).inputs["Anzahl"].text() == "9"

    def test_declining_once_does_not_mean_yes_later(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("x")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_history_ok is False
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert rd.read_day(base, day)[1]["history"] == []

    def test_a_day_that_is_still_free_does_not_ask(self, qtbot, panel, base, asked):
        panel._diary_note.setPlainText("today")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        panel._diary_note.setPlainText("today, changed")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert asked == [] and rd.read_day(base, _iso())[1]["history"] == []
        assert "history" not in panel._diary_status.text()

    def test_an_earlier_day_without_a_file_does_not_ask(self, qtbot, panel, base, asked):
        panel._diary_refresh()
        _pick(panel, _iso(-3))
        panel._diary_note.setPlainText("written afterwards")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert asked == [] and rd.read_day(base, _iso(-3))[1]["note"] == "written afterwards"
        assert rd.read_day(base, _iso(-3))[1]["history"] == []

    def test_a_changed_value_on_an_earlier_day_keeps_the_old_entries(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key, count=1)
        panel._diary_refresh()
        _pick(panel, day)
        _line(panel, key).inputs["Anzahl"].setText("5")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        stored = rd.read_day(base, day)[1]
        assert stored["entries"][key][0]["values"] == {"Anzahl": 5}
        assert stored["history"][0]["before"]["entries"][key][0]["values"] == {"Anzahl": 1}

    def test_an_entry_taken_out_of_an_earlier_day_stays_in_the_history(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key, count=4)
        panel._diary_refresh()
        _pick(panel, day)
        _line(panel, key).remove_btn.click()
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        stored = rd.read_day(base, day)[1]
        assert stored["entries"] == {} and stored["history"][0]["before"]["entries"][key][0]["values"] == {"Anzahl": 4}

    def test_changing_the_day_asks_to_save_and_then_the_history_question(self, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("edited")
        panel._diary_ask_unsaved = lambda d: "save"
        _pick(panel, _iso(-3))
        assert asked == [day] and rd.read_day(base, day)[1]["note"] == "edited"
        assert panel.selected_date() == _iso(-3)

    def test_declining_the_history_question_when_leaving_keeps_the_day_shown(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("edited")
        panel._diary_ask_unsaved = lambda d: "save"
        _pick(panel, _iso(-3))
        assert panel.selected_date() == day and panel._diary_note.toPlainText() == "edited"

    def test_the_history_count_is_shown_on_the_button(self, qtbot, panel, base, asked):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        assert not panel._diary_history_btn.isEnabled() and panel._diary_history_btn.text() == "History"
        panel._diary_note.setPlainText("two")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_history_btn.isEnabled() and panel._diary_history_btn.text() == "History (1)"

    def test_the_question_names_the_day_and_the_history(self, panel):
        seen = {}
        _click_box_button_later("Save and keep history", seen)
        assert type(panel)._diary_ask_history(panel, "2026-11-10") is True
        assert "2026-11-10" in seen["text"] and "history" in seen["info"]

    def test_cancel_in_the_question_is_a_no(self, panel):
        _click_box_button_later("Cancel")
        assert type(panel)._diary_ask_history(panel, "2026-11-10") is False


class TestDeletingAnEarlierDay:

    def test_deleting_an_earlier_day_keeps_it_empty_with_its_history(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        asked = []
        panel._diary_ask_history = lambda d: asked.append(d) or True
        panel._diary_ask_delete = lambda d: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        stored = rd.read_day(base, day)[1]
        assert asked == [day] and stored["note"] == "" and stored["entries"] == {}
        assert stored["history"][0]["before"]["note"] == "old note"
        assert "keeps its history" in panel._diary_status.text()

    def test_declining_the_history_question_deletes_nothing(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_ask_delete = lambda d: True
        before = _day_path(base, day).read_bytes()
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert _day_path(base, day).read_bytes() == before and "Not deleted" in panel._diary_status.text()

    def test_declining_the_delete_question_does_not_ask_about_history(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_ask_delete = lambda d: False
        panel._diary_ask_history = _never
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)


class TestHistoryButtonAndDialog:

    def test_the_button_is_off_for_a_day_without_history(self, panel, base):
        assert not panel._diary_history_btn.isEnabled()
        panel._diary_note.setPlainText("today")
        panel._diary_save_btn.click()
        assert not panel._diary_history_btn.isEnabled()

    def test_the_button_is_on_for_a_day_with_history(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        assert panel._diary_history_btn.isEnabled() and panel._diary_history_btn.text() == "History (2)"

    def test_the_button_is_off_for_a_damaged_day(self, panel, base):
        path = _day_path(base, _iso(-2))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        _pick(panel, _iso(-2))
        assert not panel._diary_history_btn.isEnabled()

    def test_the_count_goes_when_the_day_changes(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        _pick(panel, _iso(-5))
        assert not panel._diary_history_btn.isEnabled() and panel._diary_history_count == 0

    def test_opening_it_with_unsaved_changes_is_refused_with_a_hint(self, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("typed")
        monkeypatch.setattr(DiaryHistoryDialog, "exec", lambda self: pytest.fail("the dialog must not open"))
        panel._diary_history_btn.click()
        assert "Save or discard" in panel._diary_status.text()

    def test_opening_it_without_history_does_nothing(self, panel, base, monkeypatch):
        monkeypatch.setattr(DiaryHistoryDialog, "exec", lambda self: pytest.fail("the dialog must not open"))
        panel._diary_on_history_clicked()

    def test_the_loader_gives_copies_of_the_history_and_the_snapshot(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        history, snapshot = panel._diary_history_loader()
        assert [h["before"]["note"] for h in history] == ["one", "two"] and key in snapshot

    def test_the_loader_of_a_day_that_cannot_be_read_is_empty(self, panel, base):
        path = _day_path(base, _iso(-2))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        panel._diary_refresh()
        _pick(panel, _iso(-2))
        assert panel._diary_history_loader() == ([], {})

    @pytest.fixture
    def dialog(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        widget = DiaryHistoryDialog(panel, panel._diary_history_loader, panel._diary_restore_state)
        qtbot.addWidget(widget)
        widget._ask_restore = lambda ts: True
        widget.day = day
        widget.key = key
        return widget

    def test_the_newest_state_is_on_top_and_shown(self, dialog):
        assert dialog._list.count() == 2
        assert dialog._list.item(0).data(Qt.ItemDataRole.UserRole) == 1
        assert dialog._list.item(1).data(Qt.ItemDataRole.UserRole) == 0
        assert dialog._list.currentRow() == 0
        assert "two" in dialog._view.toPlainText() and "Anzahl 2" in dialog._view.toPlainText()

    def test_the_list_shows_the_time_stamp_with_a_space_and_the_summary(self, dialog):
        text = dialog._list.item(0).text()
        assert "T" not in text.split("·")[0] and "two · 1 entry" in text

    def test_choosing_the_other_state_shows_it(self, dialog):
        dialog._list.setCurrentRow(1)
        assert "one" in dialog._view.toPlainText() and "Anzahl 1" in dialog._view.toPlainText()

    def test_the_view_cannot_be_edited(self, dialog):
        assert dialog._view.isReadOnly()

    def test_restore_is_possible_with_a_state_chosen(self, dialog):
        assert dialog._restore_btn.isEnabled()

    def test_restoring_puts_the_state_back_and_keeps_the_replaced_one(self, dialog, panel, base):
        dialog._list.setCurrentRow(1)                       # the oldest: "one"
        dialog._restore_btn.click()
        stored = rd.read_day(base, dialog.day)[1]
        assert stored["note"] == "one" and stored["entries"][dialog.key][0]["values"] == {"Anzahl": 1}
        assert [h["before"]["note"] for h in stored["history"]] == ["one", "two", "three"]
        assert dialog.restored is True and dialog._list.count() == 3 and dialog.error_text() == ""

    def test_the_panel_shows_the_restored_day(self, dialog, panel, base):
        dialog._list.setCurrentRow(1)
        dialog._restore_btn.click()
        assert panel._diary_note.toPlainText() == "one"
        assert _line(panel, dialog.key).inputs["Anzahl"].text() == "1"
        assert "Restored" in panel._diary_status.text() and panel._diary_history_btn.text() == "History (3)"
        assert not panel._diary_is_dirty()

    def test_a_restore_can_be_undone(self, dialog, panel, base):
        dialog._list.setCurrentRow(1)
        dialog._restore_btn.click()
        dialog._list.setCurrentRow(0)                       # the newest item is the state "three" that was replaced
        dialog._restore_btn.click()
        assert rd.read_day(base, dialog.day)[1]["note"] == "three"

    def test_declining_the_question_restores_nothing(self, dialog, panel, base):
        dialog._ask_restore = lambda ts: False
        before = _day_path(base, dialog.day).read_bytes()
        dialog._restore_btn.click()
        assert _day_path(base, dialog.day).read_bytes() == before and dialog.restored is False

    def test_the_question_names_the_time_and_says_the_state_is_kept(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        widget = DiaryHistoryDialog(panel, panel._diary_history_loader, panel._diary_restore_state)
        qtbot.addWidget(widget)
        seen = {}
        _click_box_button_later("Restore", seen)
        assert widget._ask_restore("2026-11-19T08:00:00") is True
        assert "2026-11-19 08:00:00" in seen["text"] and "kept in the history" in seen["info"]
        _click_box_button_later("Cancel")
        assert widget._ask_restore("2026-11-19T08:00:00") is False

    def test_a_refusal_of_the_writer_is_shown(self, qtbot, panel):
        history = [{"timestamp": "2026-11-19T08:00:00", "before": {"note": "a", "entries": {}}}]
        widget = DiaryHistoryDialog(panel, lambda: (history, {}), lambda i: {"status": "rejected", "reason": "day_damaged"})
        qtbot.addWidget(widget)
        widget._ask_restore = lambda ts: True
        widget._restore_btn.click()
        assert "day_damaged" in widget.error_text() and widget.restored is False

    def test_the_error_goes_after_the_next_good_restore(self, qtbot, panel):
        history = [{"timestamp": "2026-11-19T08:00:00", "before": {"note": "a", "entries": {}}}]
        answers = iter([{"status": "rejected", "reason": "day_damaged"}, {"status": "written"}])
        widget = DiaryHistoryDialog(panel, lambda: (history, {}), lambda i: next(answers))
        qtbot.addWidget(widget)
        widget._ask_restore = lambda ts: True
        widget._restore_btn.click()
        assert widget.error_text() != ""
        widget._list.setCurrentRow(0)
        widget._restore_btn.click()
        assert widget.error_text() == "" and widget.restored is True

    def test_an_unchanged_answer_is_no_error_and_no_restore(self, qtbot, panel):
        history = [{"timestamp": "2026-11-19T08:00:00", "before": {"note": "a", "entries": {}}}]
        widget = DiaryHistoryDialog(panel, lambda: (history, {}), lambda i: {"status": "unchanged"})
        qtbot.addWidget(widget)
        widget._ask_restore = lambda ts: True
        widget._restore_btn.click()
        assert widget.error_text() == "" and widget.restored is False

    def test_the_index_goes_to_the_restorer_counted_from_the_oldest(self, qtbot, panel):
        history = [{"timestamp": f"2026-11-1{i}T08:00:00", "before": {"note": str(i), "entries": {}}} for i in range(3)]
        got = []
        widget = DiaryHistoryDialog(panel, lambda: (history, {}), lambda i: got.append(i) or {"status": "unchanged"})
        qtbot.addWidget(widget)
        widget._ask_restore = lambda ts: True
        widget._list.setCurrentRow(0)
        widget._restore_btn.click()
        widget._list.setCurrentRow(2)
        widget._restore_btn.click()
        assert got == [2, 0]

    def test_without_history_there_is_a_message_and_no_restore(self, qtbot, panel):
        widget = DiaryHistoryDialog(panel, lambda: ([], {}), lambda i: {})
        qtbot.addWidget(widget)
        assert widget._list.count() == 0 and "no history" in widget._view.toPlainText()
        assert not widget._restore_btn.isEnabled()

    def test_the_buttons_are_no_default_button(self, dialog):
        assert not dialog._restore_btn.autoDefault() and not dialog._close_btn.autoDefault()

    def test_the_panel_restore_function_does_not_reload_on_a_refusal(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_note.setPlainText("typed after")
        res = panel._diary_restore_state(99)
        assert res["status"] == "rejected" and panel._diary_note.toPlainText() == "typed after"


# ══════════════════════════════════════════════════════════════════════════════
#  Baustein 5: backup copies and the restore from them
# ══════════════════════════════════════════════════════════════════════════════

class _SyncThread:
    """A stand-in for threading.Thread that runs its target at once, in the test thread."""

    created = []

    def __init__(self, target=None, name=None, daemon=None, **kwargs):
        self.target, self.name, self.daemon = target, name, daemon
        _SyncThread.created.append(self)

    def start(self):
        self.target()


class TestBackupAfterChanges:

    def test_a_saved_day_has_a_backup_copy(self, qtbot, panel, base):
        panel._diary_note.setPlainText("for the backup")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert bk.read_day_copy(base, _iso()) == _day_path(base, _iso()).read_bytes()

    def test_a_changed_day_replaces_its_copy(self, qtbot, panel, base):
        panel._diary_note.setPlainText("one")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        panel._diary_note.setPlainText("two")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert b'"two"' in bk.read_day_copy(base, _iso())
        assert bk.read_day_copy(base, _iso()) == _day_path(base, _iso()).read_bytes()

    def test_nothing_to_save_makes_no_copy_and_no_message(self, qtbot, panel, base, monkeypatch):
        monkeypatch.setattr(bk, "backup_day", lambda *a: pytest.fail("no backup for nothing"))
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert "backup" not in panel._diary_status.text()

    def test_an_emptied_day_is_removed_but_its_copy_stays(self, qtbot, panel, base):
        panel._diary_note.setPlainText("gone soon")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        panel._diary_ask_delete = lambda d: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert not _day_path(base, _iso()).exists()
        assert bk.read_day_copy(base, _iso()) is not None

    def test_deleting_an_earlier_day_updates_the_copy_to_the_empty_state(self, qtbot, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_ask_history = lambda d: True
        panel._diary_ask_delete = lambda d: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert bk.read_day_copy(base, day) == _day_path(base, day).read_bytes()

    def test_a_restored_state_is_copied(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_restore_state(0)
        assert bk.read_day_copy(base, day) == _day_path(base, day).read_bytes()

    def test_a_failed_copy_is_told_after_the_saved_message(self, qtbot, panel, base, monkeypatch):
        monkeypatch.setattr(bk, "backup_day", lambda *a: {"ok": False, "status": "failed", "reason": "copy_failed"})
        panel._diary_note.setPlainText("saved anyway")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        text = panel._diary_status.text()
        assert text.startswith("Saved ") and "backup copy could not be made" in text
        assert rd.read_day(base, _iso())[1]["note"] == "saved anyway"
        assert panel._app.YELLOW in panel._diary_status.styleSheet()

    def test_a_failed_copy_after_deleting_an_earlier_day_is_told(self, qtbot, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True)
        day = _past_day(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_ask_history = lambda d: True
        panel._diary_ask_delete = lambda d: True
        monkeypatch.setattr(bk, "backup_day", lambda *a: {"ok": False, "status": "failed", "reason": "copy_failed"})
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert "backup copy could not be made" in panel._diary_status.text() and "Deleted" in panel._diary_status.text()

    def test_a_failed_copy_after_a_restore_of_a_state_is_told(self, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        monkeypatch.setattr(bk, "backup_day", lambda *a: {"ok": False, "status": "failed", "reason": "copy_failed"})
        panel._diary_restore_state(0)
        assert "backup copy could not be made" in panel._diary_status.text()

    def test_the_delete_question_says_that_the_copy_stays(self, panel):
        seen = {}
        _click_box_button_later("Cancel", seen)
        type(panel)._diary_ask_delete(panel, "2026-11-10")
        assert "backup" in seen["info"] and "cannot be undone" in seen["info"]


class TestBackupOfTheFieldList:

    def _copy_is_the_file(self, base):
        return bk.read_master_copy(base) == (base / "diary_data" / "fields.json").read_bytes()

    def test_a_created_field_is_copied(self, panel, base):
        assert panel._diary_create_field("Painkiller", TABLET, True, True)["status"] == "written"
        assert self._copy_is_the_file(base)

    def test_a_field_from_a_template_is_copied(self, panel, base):
        _choose_template(panel, "Walk")
        assert self._copy_is_the_file(base)

    def test_a_catalogue_field_that_was_added_is_copied(self, panel, base):
        _choose(panel, "G003")
        assert self._copy_is_the_file(base)

    def test_a_rename_is_copied(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        panel._diary_rename_field(key, "Tablet")
        assert self._copy_is_the_file(base) and b"Tablet" in bk.read_master_copy(base)

    def test_an_archived_field_is_copied(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        panel._diary_archive_field(key, True)
        assert self._copy_is_the_file(base)

    def test_a_favorite_flag_is_copied(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        panel._diary_rows[key].star.click()
        assert self._copy_is_the_file(base)

    def test_a_refused_change_makes_no_copy(self, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        monkeypatch.setattr(bk, "backup_master", lambda *a: pytest.fail("nothing changed, nothing to copy"))
        assert panel._diary_rename_field(key, "Blood pressure")["status"] == "rejected"

    def test_a_failed_copy_of_the_list_is_told(self, panel, base, monkeypatch):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        monkeypatch.setattr(bk, "backup_master", lambda *a: {"ok": False, "status": "failed", "reason": "exception"})
        panel._diary_rename_field(key, "Tablet")
        assert "backup copy could not be made" in panel._diary_status.text()

    def test_a_failed_copy_after_a_template_keeps_the_created_message(self, panel, base, monkeypatch):
        monkeypatch.setattr(bk, "backup_master", lambda *a: {"ok": False, "status": "failed", "reason": "exception"})
        _choose_template(panel, "Walk")
        text = panel._diary_status.text()
        assert "created from the template" in text and "backup copy could not be made" in text


class TestBackupAtTheStart:

    @pytest.fixture
    def threads(self, monkeypatch, app_mock):
        import app.panel_diary as module
        _SyncThread.created = []
        monkeypatch.setattr(module.threading, "Thread", _SyncThread)
        app_mock._dispatch.side_effect = lambda fn, *a: fn(*a)
        return _SyncThread.created

    def test_the_first_show_starts_the_backup_in_a_background_thread(self, raw_panel, base, threads):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        wr.save_day(base, _iso(-1), "old", {}, now=datetime.now())
        raw_panel._diary_refresh()
        assert len(threads) == 1 and threads[0].daemon is True and threads[0].name == "diary-backup"
        assert bk.read_day_copy(base, _iso(-1)) is not None

    def test_it_runs_once_for_an_archive_folder(self, raw_panel, base, threads):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        raw_panel._diary_refresh()
        raw_panel._diary_refresh()
        raw_panel._diary_refresh()
        assert len(threads) == 1

    def test_another_folder_starts_it_again(self, raw_panel, app_mock, base, threads, tmp_path_factory):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        raw_panel._diary_refresh()
        other = tmp_path_factory.mktemp("other")
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": str(other)}
        raw_panel._diary_refresh()
        assert len(threads) == 2

    def test_without_a_folder_nothing_starts(self, raw_panel, app_mock, threads):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_refresh()
        assert threads == []

    def test_a_backup_that_could_not_copy_everything_is_told(self, raw_panel, app_mock, base, threads, monkeypatch):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        monkeypatch.setattr(bk, "backup_all", lambda b: {"ok": False, "status": "done"})
        later = []
        app_mock._dispatch.side_effect = lambda fn, *a: later.append(fn)      # arrives after the refresh, as it does for real
        raw_panel._diary_refresh()
        assert raw_panel._diary_status.text() == ""
        for fn in later:
            fn()
        assert "backup copy could not be made" in raw_panel._diary_status.text()

    def test_a_good_backup_says_nothing(self, raw_panel, base, threads, monkeypatch):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        monkeypatch.setattr(bk, "backup_all", lambda b: {"ok": True, "status": "done"})
        raw_panel._diary_refresh()
        assert "backup" not in raw_panel._diary_status.text()

    def test_the_thread_gets_the_archive_folder(self, raw_panel, base, threads, monkeypatch):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        got = []
        monkeypatch.setattr(bk, "backup_all", lambda b: got.append(b) or {"ok": True, "status": "done"})
        raw_panel._diary_refresh()
        assert got == [base]

    def test_the_thread_never_touches_a_widget_directly(self, raw_panel, base, app_mock, threads, monkeypatch):
        raw_panel._diary_start_backup = type(raw_panel)._diary_start_backup.__get__(raw_panel)
        monkeypatch.setattr(bk, "backup_all", lambda b: {"ok": False, "status": "done"})
        seen = []
        app_mock._dispatch.side_effect = lambda fn, *a: seen.append(fn)
        raw_panel._diary_refresh()
        assert seen == [raw_panel._diary_backup_failed_at_start] and "backup" not in raw_panel._diary_status.text()


class TestRestoreFromBackup:

    @pytest.fixture
    def damaged_day(self, panel, base):
        """A day that was saved and backed up, then damaged on disk; the panel shows it."""
        panel._diary_note.setPlainText("precious")
        panel._diary_save_btn.click()
        day = _iso()
        original = _day_path(base, day).read_bytes()
        _day_path(base, day).write_text("{ half written", encoding="utf-8")
        panel._diary_refresh()
        panel._diary_load_day()
        return day, original

    def test_the_button_is_off_when_nothing_is_damaged(self, panel):
        assert not panel._diary_restore_btn.isEnabled()

    def test_a_damaged_day_with_a_valid_copy_enables_it(self, panel, damaged_day):
        assert panel._diary_restore_btn.isEnabled() and panel._diary_restore_target() == ("day", damaged_day[0])

    def test_restoring_puts_the_day_back_and_keeps_the_damaged_file(self, panel, base, damaged_day):
        day, original = damaged_day
        panel._diary_ask_restore_copy = lambda d: True
        panel._diary_restore_btn.click()
        assert rd.read_day(base, day)[1]["note"] == "precious" and panel._diary_note.toPlainText() == "precious"
        assert (_day_path(base, day).with_name(_day_path(base, day).name + ".damaged")).read_text(encoding="utf-8") == "{ half written"
        assert "Restored from the backup copy" in panel._diary_status.text() and not panel._diary_restore_btn.isEnabled()
        assert panel._diary_calendar.is_marked(day)

    def test_declining_restores_nothing(self, panel, base, damaged_day):
        day, _original = damaged_day
        panel._diary_ask_restore_copy = lambda d: False
        panel._diary_restore_btn.click()
        assert _day_path(base, day).read_text(encoding="utf-8") == "{ half written"

    def test_the_question_names_the_day(self, panel, damaged_day):
        seen = {}
        _click_box_button_later("Restore", seen)
        assert type(panel)._diary_ask_restore_copy(panel, "2026-11-10") is True
        assert "the day 2026-11-10" in seen["text"] and ".damaged" in seen["info"]

    def test_the_question_names_the_list_of_fields(self, panel):
        seen = {}
        _click_box_button_later("Cancel", seen)
        assert type(panel)._diary_ask_restore_copy(panel, None) is False
        assert "the list of fields" in seen["text"]

    def test_a_day_that_was_deleted_is_not_offered_for_restore(self, panel, base):
        panel._diary_note.setPlainText("gone")
        panel._diary_save_btn.click()
        panel._diary_ask_delete = lambda d: True
        panel._diary_delete_btn.click()
        assert not _day_path(base, _iso()).exists() and bk.read_day_copy(base, _iso()) is not None
        assert panel._diary_restore_target() is None and not panel._diary_restore_btn.isEnabled()

    def test_a_damaged_day_without_a_copy_cannot_be_restored(self, panel, base):
        day = _iso(-2)
        path = _day_path(base, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ broken", encoding="utf-8")
        panel._diary_refresh()
        _pick(panel, day)
        assert not panel._diary_restore_btn.isEnabled() and panel._diary_restore_target() is None

    def test_a_copy_that_is_not_valid_does_not_count(self, panel, base, damaged_day):
        day, _original = damaged_day
        copy_path = next((base / "garmin_data" / "backup" / "diary" / "days").rglob(f"diary_{day}.json"))
        copy_path.write_text('{"date": "x"}', encoding="utf-8")
        panel._diary_load_day()
        assert not panel._diary_restore_btn.isEnabled()

    def test_a_refusal_is_shown(self, panel, damaged_day, monkeypatch):
        panel._diary_ask_restore_copy = lambda d: True
        monkeypatch.setattr(wr, "restore_day", lambda *a: {"status": "rejected", "reason": "day_exists"})
        panel._diary_restore_btn.click()
        assert "Could not restore (day_exists)" in panel._diary_status.text()

    def test_a_failed_write_is_shown(self, panel, damaged_day, monkeypatch):
        panel._diary_ask_restore_copy = lambda d: True
        monkeypatch.setattr(wr, "restore_day", lambda *a: {"status": "failed", "reason": "write_failed"})
        panel._diary_restore_btn.click()
        assert "write_failed" in panel._diary_status.text()

    def test_the_function_does_nothing_without_a_target(self, panel, monkeypatch):
        monkeypatch.setattr(wr, "restore_day", lambda *a: pytest.fail("nothing to restore"))
        monkeypatch.setattr(wr, "restore_master", lambda *a: pytest.fail("nothing to restore"))
        panel._diary_on_restore_clicked()

    # ── the list of fields ──

    @pytest.fixture
    def damaged_list(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        panel._diary_refresh()
        panel._diary_create_field("Second", TABLET, False, True)      # a change that is copied
        original = (base / "diary_data" / "fields.json").read_bytes()
        (base / "diary_data" / "fields.json").write_text("{ broken", encoding="utf-8")
        panel._diary_refresh()
        return key, original

    def test_a_damaged_list_with_a_valid_copy_enables_it(self, panel, damaged_list):
        assert panel._diary_restore_btn.isEnabled() and panel._diary_restore_target() == ("master", None)

    def test_restoring_the_list_puts_it_back(self, panel, base, damaged_list):
        key, original = damaged_list
        panel._diary_ask_restore_copy = lambda d: d is None
        panel._diary_restore_btn.click()
        assert (base / "diary_data" / "fields.json").read_bytes() != b"{ broken"
        assert rd.read_master(base)[0] == "ok" and key in panel._diary_rows
        assert (base / "diary_data" / "fields.json.damaged").read_text(encoding="utf-8") == "{ broken"
        assert "Restored from the backup copy" in panel._diary_status.text() and not panel._diary_restore_btn.isEnabled()
        assert panel._diary_manage_btn.isEnabled() and panel._diary_field_combo.isEnabled()

    def test_a_missing_list_with_a_valid_copy_enables_it(self, panel, base, damaged_list):
        (base / "diary_data" / "fields.json").unlink()
        panel._diary_refresh()
        assert panel._diary_restore_target() == ("master", None)

    def test_a_missing_list_without_a_copy_is_the_normal_start(self, panel, base):
        assert panel._diary_master_state == rd.MISSING and not panel._diary_restore_btn.isEnabled()

    def test_a_copy_of_the_list_that_is_no_field_list_does_not_count(self, panel, base, damaged_list):
        (base / "garmin_data" / "backup" / "diary" / "master" / "fields.json").write_text('{"hello": 1}', encoding="utf-8")
        panel._diary_refresh()
        assert panel._diary_restore_target() is None and not panel._diary_restore_btn.isEnabled()

    def test_a_damaged_list_without_a_copy_cannot_be_restored(self, panel, base):
        wr.create_user_field(base, "Mine", TABLET, True)
        (base / "diary_data" / "fields.json").write_text("{ broken", encoding="utf-8")
        panel._diary_refresh()
        assert not panel._diary_restore_btn.isEnabled()

    def test_a_damaged_day_comes_before_the_list(self, panel, base):
        day = _iso()
        panel._diary_create_field("Painkiller", TABLET, False, True)         # the field list is copied
        panel._diary_note.setPlainText("x")
        panel._diary_save_btn.click()                                        # the day is saved and copied
        _day_path(base, day).write_text("{ broken", encoding="utf-8")
        (base / "diary_data" / "fields.json").write_text("{ broken", encoding="utf-8")
        panel._diary_refresh()
        panel._diary_load_day()
        assert panel._diary_restore_target() == ("day", day)

    def test_the_list_is_refused_when_a_day_cannot_be_read(self, panel, base, damaged_list):
        panel._diary_ask_restore_copy = lambda d: True
        path = _day_path(base, _iso(-4))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ broken", encoding="utf-8")
        panel._diary_restore_btn.click()
        assert "days_unreadable" in panel._diary_status.text()

    def test_without_an_archive_folder_there_is_nothing_to_restore(self, raw_panel, app_mock):
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_refresh()
        assert raw_panel._diary_restore_target() is None and not raw_panel._diary_restore_btn.isEnabled()


# ══════════════════════════════════════════════════════════════════════════════
#  Step 4e: search in the notes
# ══════════════════════════════════════════════════════════════════════════════

def _notes(base, mapping):
    for date_str, note in mapping.items():
        wr.save_day(base, date_str, note, {}, now=datetime.fromisoformat(date_str + "T09:00:00"))


def _result_dates(panel):
    return [panel._diary_results.item(i).data(Qt.ItemDataRole.UserRole) for i in range(panel._diary_results.count())]


class TestSearchBox:

    def test_it_is_on_with_an_archive_folder_and_off_without(self, raw_panel, app_mock):
        assert not raw_panel._diary_search.isEnabled()
        raw_panel._diary_refresh()
        assert raw_panel._diary_search.isEnabled()
        app_mock._panel_settings._collect_settings.return_value = {"base_dir": ""}
        raw_panel._diary_refresh()
        assert not raw_panel._diary_search.isEnabled()

    def test_the_hits_are_listed_newest_first_with_date_and_piece_of_the_note(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub am Meer", "2026-04-02": "noch mehr Urlaub", "2026-05-03": "Arbeit"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        assert _result_dates(panel) == ["2026-04-02", "2026-03-01"]
        assert panel._diary_results.item(0).text() == "2026-04-02   noch mehr Urlaub"
        assert panel._diary_results.item(1).toolTip() == "Urlaub am Meer"

    def test_the_hint_counts_the_days(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub", "2026-04-02": "Urlaub zwei"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        assert panel._diary_search_hint.text() == "2 days found."
        panel._diary_search.setText("zwei")
        panel._diary_run_search()
        assert panel._diary_search_hint.text() == "1 day found."

    def test_nothing_found_says_how_many_days_were_searched(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub", "2026-04-02": "Reise"})
        panel._diary_search.setText("Fieber")
        panel._diary_run_search()
        assert panel._diary_results.count() == 0 and panel._diary_search_hint.text() == "Nothing found in 2 days."

    def test_one_character_is_too_short(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        panel._diary_search.setText("u")
        panel._diary_run_search()
        assert panel._diary_results.count() == 0 and "at least two characters" in panel._diary_search_hint.text()

    def test_a_very_long_text_is_refused_with_a_hint(self, panel, base):
        panel._diary_search.setText("x" * 201)
        panel._diary_run_search()
        assert "too long" in panel._diary_search_hint.text()

    def test_an_empty_or_blank_box_searches_nothing_and_clears(self, panel, base, monkeypatch):
        _notes(base, {"2026-03-01": "Urlaub"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        assert panel._diary_results.count() == 1
        monkeypatch.setattr(rd, "search_notes", lambda *a, **k: pytest.fail("an empty box is not searched"))
        panel._diary_search.setText("   ")
        panel._diary_run_search()
        assert panel._diary_results.count() == 0 and panel._diary_search_hint.text() == ""
        panel._diary_search.setText("")
        panel._diary_run_search()
        assert panel._diary_search_hint.text() == ""

    def test_days_that_cannot_be_read_are_told(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        path = _day_path(base, "2026-03-02")
        path.write_text("{ broken", encoding="utf-8")
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        assert "1 day found." in panel._diary_search_hint.text() and "1 days could not be read" in panel._diary_search_hint.text()

    def test_a_cut_list_is_told(self, panel, base, monkeypatch):
        hits = [{"date": f"2026-03-0{i}", "snippet": "x"} for i in range(1, 4)]
        monkeypatch.setattr(rd, "search_notes", lambda *a, **k: {"ok": True, "hits": hits, "searched": 9, "unreadable": 0, "truncated": True})
        panel._diary_search.setText("x y")
        panel._diary_run_search()
        assert panel._diary_search_hint.text() == "The newest 3 days are shown." and panel._diary_results.count() == 3

    def test_nothing_is_searched_without_an_archive_folder(self, raw_panel, monkeypatch):
        monkeypatch.setattr(rd, "search_notes", lambda *a, **k: pytest.fail("no folder, no search"))
        raw_panel._diary_search.setText("urlaub")
        raw_panel._diary_run_search()
        assert raw_panel._diary_results.count() == 0

    def test_a_long_hit_wraps_instead_of_getting_a_scroll_bar(self, panel):
        assert panel._diary_results.wordWrap() is True
        assert panel._diary_results.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff

    def test_the_footer_does_not_call_the_tab_a_preview_any_more(self, panel):
        texts = _label_texts(panel)
        assert not any("Preview" in text for text in texts)
        assert any("copy of every day is kept in the backup" in text for text in texts)

    def test_a_new_list_replaces_the_old_one(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub", "2026-04-02": "Reise"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_search.setText("reise")
        panel._diary_run_search()
        assert _result_dates(panel) == ["2026-04-02"]

    # ── typing ──

    def test_typing_starts_a_short_timer_and_the_list_follows(self, qtbot, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        panel._diary_search.setText("urlaub")
        assert panel._diary_search_timer.isActive() and panel._diary_search_timer.interval() == 300
        qtbot.waitUntil(lambda: panel._diary_results.count() == 1, timeout=3000)

    def test_quick_typing_is_one_search(self, qtbot, panel, base, monkeypatch):
        calls = []
        real = rd.search_notes
        monkeypatch.setattr(rd, "search_notes", lambda *a, **k: calls.append(a) or real(*a, **k))
        for text in ("ur", "url", "urla", "urlau"):
            panel._diary_search.setText(text)
        qtbot.waitUntil(lambda: not panel._diary_search_timer.isActive(), timeout=3000)
        assert len(calls) == 1 and calls[0][1] == "urlau"

    # ── the click ──

    def test_a_click_jumps_to_the_day(self, qtbot, panel, base):
        _notes(base, {"2026-03-01": "Urlaub am Meer"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_on_result_clicked(panel._diary_results.item(0))
        assert panel.selected_date() == "2026-03-01" and panel._diary_note.toPlainText() == "Urlaub am Meer"

    def test_the_real_click_signal_does_the_same(self, qtbot, panel, base):
        _notes(base, {"2026-03-01": "Urlaub am Meer"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_results.itemClicked.emit(panel._diary_results.item(0))
        assert panel.selected_date() == "2026-03-01"

    def test_the_list_stays_after_the_jump(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub", "2026-04-02": "Urlaub zwei"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_on_result_clicked(panel._diary_results.item(1))
        assert panel._diary_results.count() == 2

    def test_a_click_with_unsaved_changes_asks_first(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_note.setPlainText("typed, not saved")
        asked = []
        panel._diary_ask_unsaved = lambda day: asked.append(day) or "cancel"
        panel._diary_on_result_clicked(panel._diary_results.item(0))
        assert asked == [_iso()] and panel.selected_date() == _iso()
        assert panel._diary_note.toPlainText() == "typed, not saved"

    def test_saving_in_that_question_saves_and_then_jumps(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_note.setPlainText("typed")
        panel._diary_ask_unsaved = lambda day: "save"
        panel._diary_on_result_clicked(panel._diary_results.item(0))
        assert panel.selected_date() == "2026-03-01" and rd.read_day(base, _iso())[1]["note"] == "typed"

    # ── the list follows the days ──

    def test_a_saved_note_shows_up_in_an_open_search(self, qtbot, panel, base):
        panel._diary_search.setText("alpha")
        panel._diary_run_search()
        assert panel._diary_results.count() == 0
        panel._diary_note.setPlainText("alpha und beta")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        assert _result_dates(panel) == [_iso()]

    def test_a_deleted_day_goes_from_an_open_search(self, qtbot, panel, base):
        panel._diary_note.setPlainText("alpha")
        qtbot.mouseClick(panel._diary_save_btn, Qt.MouseButton.LeftButton)
        panel._diary_search.setText("alpha")
        panel._diary_run_search()
        assert _result_dates(panel) == [_iso()]
        panel._diary_ask_delete = lambda d: True
        qtbot.mouseClick(panel._diary_delete_btn, Qt.MouseButton.LeftButton)
        assert panel._diary_results.count() == 0

    def test_showing_the_tab_again_searches_again(self, panel, base):
        panel._diary_search.setText("alpha")
        panel._diary_run_search()
        wr.save_day(base, _iso(-1), "alpha outside the panel", {}, now=datetime.now())
        panel._diary_refresh()
        assert _result_dates(panel) == [_iso(-1)]

    def test_a_restored_note_changes_the_list(self, panel, base):
        key = _field(base, "Painkiller", TABLET, True)
        day = _with_history(base, key)
        panel._diary_refresh()
        _pick(panel, day)
        panel._diary_search.setText("three")
        panel._diary_run_search()
        assert _result_dates(panel) == [day]
        panel._diary_restore_state(0)
        assert panel._diary_results.count() == 0

    def test_the_search_leaves_the_diary_files_alone(self, panel, base):
        _notes(base, {"2026-03-01": "Urlaub"})
        before = sorted((p.name, p.read_bytes()) for p in (base / "diary_data").rglob("*") if p.is_file())
        panel._diary_search.setText("urlaub")
        panel._diary_run_search()
        panel._diary_on_result_clicked(panel._diary_results.item(0))
        after = sorted((p.name, p.read_bytes()) for p in (base / "diary_data").rglob("*") if p.is_file())
        assert before == after


# ══════════════════════════════════════════════════════════════════════════════
#  Closing the window
# ══════════════════════════════════════════════════════════════════════════════

class TestClose:

    def test_a_clean_note_lets_the_window_close_without_a_question(self, panel):
        panel._diary_ask_unsaved = _never
        assert panel.confirm_close() is True

    def test_a_window_without_a_folder_closes_without_a_question(self, raw_panel):
        raw_panel._diary_ask_unsaved = _never
        raw_panel._diary_note.setPlainText("kein Archiv")
        assert raw_panel.confirm_close() is True, "nothing can be saved or lost without an archive folder"

    def test_cancel_keeps_the_window_open_and_the_text(self, panel):
        panel._diary_note.setPlainText("nicht verlieren")
        panel._diary_ask_unsaved = lambda day: "cancel"
        assert panel.confirm_close() is False
        assert panel._diary_note.toPlainText() == "nicht verlieren"

    def test_discard_lets_the_window_close(self, panel, base):
        panel._diary_note.setPlainText("weg damit")
        panel._diary_ask_unsaved = lambda day: "discard"
        assert panel.confirm_close() is True
        assert not _day_path(base, _iso()).exists()

    def test_save_writes_and_lets_the_window_close(self, panel, base):
        panel._diary_note.setPlainText("sichern")
        panel._diary_ask_unsaved = lambda day: "save"
        assert panel.confirm_close() is True
        assert rd.read_day(base, _iso())[1]["note"] == "sichern"

    def test_a_refused_save_keeps_the_window_open(self, panel, base):
        _write(base, _iso(-1), "alt", now=datetime.now() - timedelta(days=1))
        panel._diary_refresh()
        _pick(panel, _iso(-1))
        panel._diary_note.setPlainText("geändert")
        panel._diary_ask_unsaved = lambda day: "save"
        assert panel.confirm_close() is False
        assert "Not saved" in panel._diary_status.text()

    def test_the_question_names_the_day(self, panel):
        panel._diary_note.setPlainText("x")
        asked = []
        panel._diary_ask_unsaved = lambda day: asked.append(day) or "cancel"
        panel.confirm_close()
        assert asked == [_iso()]

    def test_staying_open_shows_the_diary_tab(self, qtbot, panel):
        tabs = QTabWidget()
        qtbot.addWidget(tabs)
        tabs.addTab(QWidget(), "Other")
        tabs.addTab(panel, "Diary")
        panel.attach_to_tabs(tabs, 1)
        tabs.setCurrentIndex(1)
        panel._diary_note.setPlainText("x")
        panel._diary_ask_unsaved = lambda day: "cancel"
        tabs.blockSignals(True)          # as if another part of the app had moved to a different tab
        tabs.setCurrentIndex(0)
        tabs.blockSignals(False)
        assert panel.confirm_close() is False
        assert tabs.currentIndex() == 1

    def test_without_a_tab_bar_it_still_answers(self, panel):
        panel._diary_note.setPlainText("x")
        panel._diary_ask_unsaved = lambda day: "cancel"
        assert panel._diary_tabs is None
        assert panel.confirm_close() is False


# ══════════════════════════════════════════════════════════════════════════════
#  The real questions (QMessageBox)
# ══════════════════════════════════════════════════════════════════════════════

class TestQuestions:

    @pytest.mark.parametrize("button,expected", [("Save", "save"), ("Discard", "discard"), ("Cancel", "cancel")])
    def test_the_unsaved_question_returns_the_button(self, panel, button, expected):
        seen = {}
        _click_box_button_later(button, seen)
        assert panel._diary_ask_unsaved("2026-11-10") == expected
        assert "2026-11-10" in seen["text"]
        assert "lost" in seen["info"], "it must say that the changes are lost"

    def test_closing_the_unsaved_question_counts_as_cancel(self, panel):
        def _close():
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QMessageBox) and widget.isVisible():
                    widget.reject()
        QTimer.singleShot(150, _close)
        assert panel._diary_ask_unsaved("2026-11-10") == "cancel"

    @pytest.mark.parametrize("button,expected", [("Delete", True), ("Cancel", False)])
    def test_the_delete_question_returns_the_button(self, panel, button, expected):
        seen = {}
        _click_box_button_later(button, seen)
        assert panel._diary_ask_delete("2026-11-10") is expected
        assert "2026-11-10" in seen["text"]
        assert "cannot be undone" in seen["info"]


# ══════════════════════════════════════════════════════════════════════════════
#  The tab in the real window
# ══════════════════════════════════════════════════════════════════════════════

class TestDiaryTabInWindow:

    def _window(self, qtbot):
        with patch("garmin_app_settings.load_settings", return_value=dict(_SETTINGS)), \
                patch("garmin_app_settings.load_password", return_value=""), \
                patch("garmin_app_controller.check_migration_needed", return_value=False):
            from garmin_app_base import GarminApp

            class _TestApp(GarminApp):
                def _run(self, *a, **kw): pass
                def _is_running(self): return False
                def _stop_collector(self): pass
                def closeEvent(self, event):
                    # No settings save during teardown: never overwrite the real settings file.
                    event.accept()

            app = _TestApp()
            qtbot.addWidget(app)
        return app

    # One window in one test on purpose: several real GarminApp windows (each with a QWebEngineView)
    # in one process end with a crash while the interpreter exits in this environment (also seen with
    # a few window tests of test_qt_app.py selected on their own; the whole file ends clean). The
    # suite's exit code would then read "failed" although every test passed.
    def test_the_diary_tab_in_the_real_window(self, qtbot, tmp_path):
        from PyQt6.QtGui import QCloseEvent
        from app.panel_diary import PanelDiary
        import garmin_app_base
        app = self._window(qtbot)
        tabs = app._right_tabs
        names = [tabs.tabText(i) for i in range(tabs.count())]
        assert names == ["Dashboard", "Files", "Settings", "Chat", "MCP Server", "Diary"], "Diary is last"
        assert isinstance(app._panel_diary, PanelDiary)
        holder = tabs.widget(tabs.count() - 1)
        assert isinstance(holder, QScrollArea) and holder.widget() is app._panel_diary, "scroll wrapper"
        assert tabs.widget(3) is app._panel_chat, "the tabs before it keep their places"
        assert app._panel_diary._diary_tabs is tabs and app._panel_diary._diary_tab_index == 5, "attached to the tab bar"
        tabs.setCurrentIndex(5)
        assert tabs.currentIndex() == 5, "switching to the Diary tab"
        assert not app._panel_diary._diary_note.isEnabled(), "no archive folder in the settings: disabled"
        tabs.setCurrentIndex(0)
        assert tabs.currentIndex() == 0

        # Closing the real window: GarminApp.closeEvent is called directly (the test class overrides it
        # so that nothing is saved) with everything it touches outside the window replaced: the lock
        # file of a running program, the settings file and the password.
        panel = app._panel_diary
        panel._diary_base = tmp_path
        panel._diary_load_day()
        panel._diary_note.setPlainText("ungespeichert")
        with patch.object(garmin_app_base, "process_status") as status, \
                patch.object(garmin_app_base.GarminApp, "_safe_save"), \
                patch.object(garmin_app_base, "save_password"):
            panel._diary_ask_unsaved = lambda day: "cancel"
            event = QCloseEvent()
            garmin_app_base.GarminApp.closeEvent(app, event)
            assert not event.isAccepted(), "Cancel keeps the window open"
            status.clear_lock.assert_not_called()
            assert not app._timer_stop.is_set(), "nothing is shut down before the user decided"
            assert tabs.currentIndex() == 5, "the diary tab is shown"
            assert panel._diary_note.toPlainText() == "ungespeichert"
            panel._diary_ask_unsaved = lambda day: "discard"
            event = QCloseEvent()
            garmin_app_base.GarminApp.closeEvent(app, event)
            assert event.isAccepted(), "Discard lets the window close"
            status.clear_lock.assert_called_once_with("gui")
