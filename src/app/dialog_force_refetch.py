#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
app/dialog_force_refetch.py
Garmin Local Archive — Force-Refetch Calendar Dialog (v1.7.1.7, Baustein 5)

Lets the user pick one or more days for a deliberate Force-Refetch
(Settings/Data Collection → "⚠ Force Refetch" button in panel_outputs.py).

Two-widget split, deliberately separated:
  DateToggleCalendar — a plain, reusable calendar widget. Two independent
    color layers, deliberately kept apart:
      - Quality background: green/yellow/red per day, from a
        {date_str: quality_label} dict handed in at construction time
        (read-only lookup — see quality_by_date parameter below and
        panel_archive.py::_get_quality_by_date()). Purely informational,
        never changed by clicking.
      - Selection highlight: clicking a date toggles it in/out of an
        internal selection set, shown as a bold underline (not a solid
        fill) so it never visually collides with the quality background
        underneath — deliberately NOT red, since red is already the
        "failed" quality color and a red-selected failed day (the most
        common Force-Refetch target) would otherwise be indistinguishable
        from an unselected one.
    Still carries no Force-Refetch-specific business logic beyond reading
    the quality dict it's given — a future dialog needing "pick a set of
    dates by clicking a calendar, with a quality-style background" can
    reuse it directly.
  ForceRefetchDialog — the actual Force-Refetch dialog: hosts
    DateToggleCalendar, mirrors its selection into a QListWidget (clicking
    a list entry also removes it — a second way to deselect, matching the
    calendar's own toggle), and a Start button.

Scope of this step (per Bauauftrag, 2026-09-01): dialog UI + quality-status
coloring only. The Start button is currently a stub (self._on_start does
nothing but exists as the attachment point) — wiring it to
garmin_collector.run_force_refetch_preview() plus the comparison/commit
step (Phase 2) is a separate, later Bauauftrag step, once the preview/
comparison display exists.

Rules (same as dialogs.py):
  - No project-module imports besides PyQt6. The quality_by_date dict is
    handed in by the caller (panel_outputs.py, which reads it via
    panel_archive.py::_get_quality_by_date()) — this file never reads
    quality_log.json itself, keeping the read-only exception in the one
    place it is already documented.
  - No business logic beyond selection state + displaying the given
    quality dict — no file I/O, no quality assessment, no fetch calls.
  - app instance passed as parent (parent._app for theme colors)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCalendarWidget, QListWidget, QListWidgetItem, QFrame,
    QPlainTextEdit, QScrollArea, QWidget, QCheckBox,
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtGui import QFont, QTextCharFormat, QColor

# Quality → background color. Matches the traffic-light convention used
# elsewhere in the app (archive info table, dashboards) — green/yellow/red
# for high/standard/failed. Days with no quality_log.json entry at all
# (not in quality_by_date) get no background — visually neutral, not
# "failed", since "no entry" and "fetched and failed" are different things.
_QUALITY_COLORS = {
    "high":     "#2ecc71",
    "standard": "#e6c229",
    "failed":   "#e94560",
}


# ══════════════════════════════════════════════════════════════════════════════
#  DateToggleCalendar — reusable, no Force-Refetch-specific business logic
# ══════════════════════════════════════════════════════════════════════════════

class DateToggleCalendar(QCalendarWidget):
    """
    QCalendarWidget with two independent, non-colliding color layers:
      - an optional quality-status background per day (green/yellow/red),
        purely informational, set once at construction and never changed
        by interaction;
      - a selection highlight (bold + underline) toggled by clicking a
        date.

    Known limitation (accepted, not fixed — 2026-09-01): QCalendarWidget's
    setDateTextFormat() does not reliably keep every previously-set cell's
    format visible once another cell is set afterward — in practice, only
    the most recently clicked date's bold/underline shows fully, while
    earlier selections in the same session can visually revert. This is
    Qt's own text-format repaint behavior, not a bug in the selection
    logic itself (self._selected and get_selected_dates() are always
    correct — only the calendar's own highlight rendering is affected).
    Deliberately not worked around: the selected-days QListWidget in
    ForceRefetchDialog is the reliable source of truth for what is
    selected, so a calendar-only rendering quirk was judged not worth the
    added complexity of re-applying every cell's format on each click.

    Signal
    ------
    selection_changed() — emitted after every toggle (add or remove).
                           Connect to read get_selected_dates().

    Parameters
    ----------
    quality_by_date : dict[str, str] | None
        {date_str (YYYY-MM-DD): quality_label ("high"/"standard"/"failed")}.
        Purely a lookup table for coloring — this widget never reads
        quality_log.json or any other file itself. None/omitted — no
        quality backgrounds shown, calendar stays neutral (unchanged
        behavior from before this feature).
    selection_color : str
        Underline color for the selection highlight. Deliberately
        separate from the quality colors above (default: a theme accent,
        NOT red — see module docstring for why red is reserved for
        "failed").
    """

    selection_changed = pyqtSignal()

    def __init__(self, parent=None, quality_by_date: dict | None = None,
                 selection_color: str = "#6c5ce7"):
        super().__init__(parent)
        self._selected: set[str] = set()  # ISO date strings (YYYY-MM-DD)
        self._quality_by_date = quality_by_date or {}
        self._selection_color = selection_color

        self.clicked.connect(self._on_date_clicked)

        # Paint quality backgrounds once — informational only, never
        # touched again by selection toggling.
        for date_str, label in self._quality_by_date.items():
            color = _QUALITY_COLORS.get(label)
            if not color:
                continue
            try:
                y, m, d = (int(p) for p in date_str.split("-"))
            except ValueError:
                continue
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(color))
            self.setDateTextFormat(QDate(y, m, d), fmt)

    def _format_for(self, date_str: str) -> QTextCharFormat:
        """Builds the display format for a date: quality background (if
        any) is always preserved, selection underline is layered on top."""
        fmt = QTextCharFormat()
        label = self._quality_by_date.get(date_str)
        color = _QUALITY_COLORS.get(label) if label else None
        if color:
            fmt.setBackground(QColor(color))
        if date_str in self._selected:
            # Bold + underline only — never a solid fill — so it cannot
            # visually replace/collide with a quality background underneath.
            fmt.setFontWeight(QFont.Weight.Bold)
            fmt.setFontUnderline(True)
            fmt.setUnderlineColor(QColor(self._selection_color))
        return fmt

    def _on_date_clicked(self, qdate: QDate):
        date_str = qdate.toString("yyyy-MM-dd")
        if date_str in self._selected:
            self._selected.discard(date_str)
        else:
            self._selected.add(date_str)
        self.setDateTextFormat(qdate, self._format_for(date_str))
        self.selection_changed.emit()

    def get_selected_dates(self) -> list[str]:
        """Returns selected dates as sorted ISO strings (YYYY-MM-DD)."""
        return sorted(self._selected)

    def remove_date(self, date_str: str) -> None:
        """Removes a date from the selection (e.g. called from the list
        widget's own removal path). No-op if the date was not selected.
        Restores the quality-only format — never clears a quality
        background that was there before selection."""
        if date_str not in self._selected:
            return
        self._selected.discard(date_str)
        y, m, d = (int(p) for p in date_str.split("-"))
        self.setDateTextFormat(QDate(y, m, d), self._format_for(date_str))
        self.selection_changed.emit()


# ══════════════════════════════════════════════════════════════════════════════
#  ForceRefetchDialog
# ══════════════════════════════════════════════════════════════════════════════

class ForceRefetchDialog(QDialog):
    """
    Force-Refetch day picker — calendar on top (colored by quality status),
    selection list below, Start button at the bottom.

    Usage
    -----
        dlg = ForceRefetchDialog(parent=self, quality_by_date=quality_map)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected_dates = dlg.get_selected_dates()  # list[str], ISO format

    Parameters
    ----------
    parent          : QWidget — must have ._app with theme colors
    quality_by_date : dict[str, str] | None — see DateToggleCalendar above.
                      Caller (panel_outputs.py) is responsible for reading
                      this via panel_archive.py::_get_quality_by_date() —
                      this dialog never touches quality_log.json itself.

    Note: exec() only returns Accepted once the Start button actually
    closes the dialog with accept() — currently a stub (see module
    docstring), so this dialog does not yet produce a usable Accepted
    result. Left in place as the attachment point for the next step.
    """

    def __init__(self, parent, quality_by_date: dict | None = None):
        super().__init__(parent)
        self._app = parent._app
        self.setWindowTitle("Force Refetch")
        self.setModal(True)
        self.setFixedWidth(360)

        bg   = self._app.BG
        bg3  = self._app.BG3
        text = self._app.TEXT
        t2   = self._app.TEXT2
        acc  = self._app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Force Refetch")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {text};")
        lay.addWidget(heading)

        desc = QLabel(
            "Select one or more days to re-fetch, bypassing quality "
            "protection. Click a day again to deselect it."
        )
        desc.setFont(QFont("Segoe UI", 9))
        desc.setStyleSheet(f"color: {t2};")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # ── Quality legend ────────────────────────────────────────────────────
        legend_row = QHBoxLayout()
        legend_row.setSpacing(14)
        for label, color in (("High", _QUALITY_COLORS["high"]),
                              ("Standard", _QUALITY_COLORS["standard"]),
                              ("Failed", _QUALITY_COLORS["failed"])):
            chip = QLabel(f"⬤ {label}")
            chip.setFont(QFont("Segoe UI", 8))
            chip.setStyleSheet(f"color: {color};")
            legend_row.addWidget(chip)
        legend_row.addStretch()
        lay.addLayout(legend_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        # ── Calendar ──────────────────────────────────────────────────────────
        self._calendar = DateToggleCalendar(
            self, quality_by_date=quality_by_date, selection_color=acc)
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setStyleSheet(
            f"QCalendarWidget {{ background: {bg3}; color: {text}; }}"
            f"QCalendarWidget QToolButton {{ color: {text}; background: {bg3}; }}"
            f"QCalendarWidget QAbstractItemView:enabled "
            f"{{ background: {bg3}; color: {text}; "
            f"selection-background-color: {acc}; }}"
        )
        self._calendar.selection_changed.connect(self._on_calendar_changed)
        lay.addWidget(self._calendar)

        # ── Selected-days list ────────────────────────────────────────────────
        list_lbl = QLabel("Selected days")
        list_lbl.setFont(QFont("Segoe UI", 8))
        list_lbl.setStyleSheet(f"color: {t2};")
        lay.addWidget(list_lbl)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"background: {bg3}; color: {text}; "
            f"border: none; font-family: Consolas; font-size: 8pt;")
        self._list.setFixedHeight(120)
        self._list.itemClicked.connect(self._on_list_item_clicked)
        lay.addWidget(self._list)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}")
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.setDefault(False)
        self._start_btn.setAutoDefault(False)
        self._start_btn.setEnabled(False)  # no days selected yet
        self._start_btn.clicked.connect(self._on_start)

        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._start_btn)
        lay.addLayout(btn_row)

    # ── Selection sync ───────────────────────────────────────────────────────

    def _on_calendar_changed(self):
        """Rebuilds the list widget from the calendar's current selection."""
        self._list.clear()
        selected = self._calendar.get_selected_dates()
        for date_str in selected:
            self._list.addItem(QListWidgetItem(date_str))
        self._start_btn.setEnabled(bool(selected))

    def _on_list_item_clicked(self, item: QListWidgetItem):
        """Clicking a list entry removes that date — mirrors the calendar's
        own toggle-to-deselect behavior."""
        self._calendar.remove_date(item.text())

    # ── Start (stub — wiring follows in a later Bauauftrag step) ─────────────

    def _on_start(self):
        """Closes the dialog with Accepted — the caller (panel_outputs.py)
        reads get_selected_dates() and takes over from there (timer pause,
        progress dialog, run_force_refetch_preview()). This dialog's own
        job ends here — it only ever hands back a date selection."""
        self.accept()

    # ── Result ───────────────────────────────────────────────────────────────

    def get_selected_dates(self) -> list[str]:
        """Returns the currently selected dates as sorted ISO strings."""
        return self._calendar.get_selected_dates()


# ══════════════════════════════════════════════════════════════════════════════
#  SelectionOnlyCalendar — read-only progress display
# ══════════════════════════════════════════════════════════════════════════════

class SelectionOnlyCalendar(QCalendarWidget):
    """
    Read-only calendar: highlights a fixed, pre-given set of dates and has
    no click interaction at all — no toggling, no signal.

    Deliberately a separate class from DateToggleCalendar rather than a
    read_only flag on it (Nutzer-Entscheidung, 2026-09-01): each class has
    exactly one job. Also drops the quality-status background entirely —
    during Force-Refetch's progress phase, the days being processed are
    the ones just about to get a NEW quality label; showing their old
    label here would be confusing, not informative.

    Parameters
    ----------
    dates : list[str] — ISO date strings (YYYY-MM-DD) to highlight.
                         Fixed at construction — this widget never changes
                         its own highlighted set afterward.
    highlight_color : str — background color for the given dates.
    """

    def __init__(self, parent=None, dates: list[str] | None = None,
                 highlight_color: str = "#6c5ce7"):
        super().__init__(parent)
        self.setEnabled(True)  # stays visually normal, just non-interactive
        self.clicked.disconnect() if self.receivers(self.clicked) else None

        fmt = QTextCharFormat()
        fmt.setBackground(QColor(highlight_color))
        fmt.setForeground(QColor("#eaeaea"))
        for date_str in (dates or []):
            try:
                y, m, d = (int(p) for p in date_str.split("-"))
            except ValueError:
                continue
            self.setDateTextFormat(QDate(y, m, d), fmt)

    def mousePressEvent(self, event):
        """Swallow all clicks — display only, no selection changes possible."""
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
#  ForceRefetchProgressDialog
# ══════════════════════════════════════════════════════════════════════════════

class ForceRefetchProgressDialog(QDialog):
    """
    Force-Refetch progress display — read-only calendar (selected days
    highlighted) on top, live log below, Stop button at the bottom.

    Pure UI + a thread-safe append_log() — no business logic. The caller
    (panel_outputs.py) owns starting the background fetch thread, wiring
    its stop button to the collector's stop event, and closing this dialog
    once run_force_refetch_preview() returns (then opening
    ForceRefetchReviewDialog with the result — a separate step).

    Parameters
    ----------
    parent : QWidget — must have ._app with theme colors
    dates  : list[str] — the dates being processed, for the calendar display

    Usage
    -----
        dlg = ForceRefetchProgressDialog(parent=self, dates=selected_dates)
        dlg.show()
        # caller starts its own background thread, calls
        # dlg.append_log(...) via self._app._dispatch() for thread safety,
        # and calls dlg.close() when done.
        # stop_requested signal fires when the user clicks Stop.
    """

    stop_requested = pyqtSignal()

    def __init__(self, parent, dates: list[str]):
        super().__init__(parent)
        self._app = parent._app
        self.setWindowTitle("Force Refetch — Running")
        self.setModal(True)
        self.setFixedWidth(360)

        bg   = self._app.BG
        bg3  = self._app.BG3
        text = self._app.TEXT
        t2   = self._app.TEXT2
        acc  = self._app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Force Refetch — Running")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {text};")
        lay.addWidget(heading)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        self._calendar = SelectionOnlyCalendar(
            self, dates=dates, highlight_color=acc)
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self._calendar.setStyleSheet(
            f"QCalendarWidget {{ background: {bg3}; color: {text}; }}"
            f"QCalendarWidget QToolButton {{ color: {text}; background: {bg3}; }}"
            f"QCalendarWidget QAbstractItemView:enabled "
            f"{{ background: {bg3}; color: {text}; }}"
        )
        lay.addWidget(self._calendar)

        log_lbl = QLabel("Progress")
        log_lbl.setFont(QFont("Segoe UI", 8))
        log_lbl.setStyleSheet(f"color: {t2};")
        lay.addWidget(log_lbl)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(
            f"background: {bg3}; color: {text}; "
            f"border: none; font-family: Consolas; font-size: 8pt;")
        self._log.setFixedHeight(120)
        lay.addWidget(self._log)

        btn_row = QHBoxLayout()
        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._stop_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setDefault(False)
        self._stop_btn.setAutoDefault(False)
        self._stop_btn.clicked.connect(self._on_stop)

        btn_row.addStretch()
        btn_row.addWidget(self._stop_btn)
        lay.addLayout(btn_row)

    def _on_stop(self):
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("⏹  Stopping …")
        self.stop_requested.emit()

    def append_log(self, text: str) -> None:
        """Appends a line to the progress log. Main Thread only — caller
        is responsible for using self._app._dispatch() when calling this
        from a background thread (same convention as GarminApp._log_bg())."""
        self._log.appendPlainText(text)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum())


# ══════════════════════════════════════════════════════════════════════════════
#  ForceRefetchReviewDialog
# ══════════════════════════════════════════════════════════════════════════════

class ForceRefetchReviewDialog(QDialog):
    """
    Force-Refetch review — one row per date from run_force_refetch_preview()'s
    result, each showing quality-before → quality-after, the count of
    changed fields (with the field names themselves visible — Nutzer-
    Entscheidung 2026-09-01: this is the one real decision point in the
    whole flow, worth the detail), and a checkbox the user must explicitly
    check to confirm that day. Days with a fetch error are shown for
    information only, with no checkbox — commit_force_refetch() already
    treats any date not in confirmed_dates as rejected, and an errored day
    has nothing usable to confirm.

    Pure UI — does not call commit_force_refetch() itself. The caller
    (panel_outputs.py) reads get_confirmed_dates() after exec() returns
    Accepted and passes that set straight through.

    Parameters
    ----------
    parent  : QWidget — must have ._app with theme colors
    results : list[dict] — the unmodified return value of
              garmin_collector.run_force_refetch_preview()

    Usage
    -----
        dlg = ForceRefetchReviewDialog(parent=self, results=preview_results)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            confirmed = dlg.get_confirmed_dates()  # set[str]
            # caller calls commit_force_refetch(preview_results, confirmed, ...)
    """

    def __init__(self, parent, results: list[dict]):
        super().__init__(parent)
        self._app = parent._app
        self._results = results
        self._checkboxes: dict[str, QCheckBox] = {}  # date_str -> checkbox

        self.setWindowTitle("Force Refetch — Review")
        self.setModal(True)
        self.setFixedWidth(420)

        bg   = self._app.BG
        bg3  = self._app.BG3
        text = self._app.TEXT
        t2   = self._app.TEXT2
        acc  = self._app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Force Refetch — Review")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {text};")
        lay.addWidget(heading)

        desc = QLabel(
            "Check the days you want to keep. Unchecked days are reverted "
            "to their previous state — nothing else in the archive has "
            "been touched yet."
        )
        desc.setFont(QFont("Segoe UI", 9))
        desc.setStyleSheet(f"color: {t2};")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        # ── Scrollable list of per-day rows ──────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(240)
        scroll.setStyleSheet(f"background: {bg3}; border: none;")

        rows_widget = QWidget()
        rows_lay = QVBoxLayout(rows_widget)
        rows_lay.setSpacing(6)
        rows_lay.setContentsMargins(8, 8, 8, 8)

        for entry in results:
            rows_lay.addWidget(self._build_row(entry, bg3, text, t2, acc))
        rows_lay.addStretch()

        scroll.setWidget(rows_widget)
        lay.addWidget(scroll)

        # ── Select-all / none ─────────────────────────────────────────────────
        bulk_row = QHBoxLayout()
        confirm_all_btn = QPushButton("Confirm all")
        confirm_all_btn.setFont(QFont("Segoe UI", 8))
        confirm_all_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 4px 12px; }}")
        confirm_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_all_btn.clicked.connect(lambda: self._set_all(True))

        reject_all_btn = QPushButton("Reject all")
        reject_all_btn.setFont(QFont("Segoe UI", 8))
        reject_all_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 4px 12px; }}")
        reject_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reject_all_btn.clicked.connect(lambda: self._set_all(False))

        bulk_row.addWidget(confirm_all_btn)
        bulk_row.addWidget(reject_all_btn)
        bulk_row.addStretch()
        lay.addLayout(bulk_row)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)

        self._commit_btn = QPushButton("✓  Apply")
        self._commit_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._commit_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}")
        self._commit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._commit_btn.setDefault(False)
        self._commit_btn.setAutoDefault(False)
        self._commit_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._commit_btn)
        lay.addLayout(btn_row)

    def _build_row(self, entry: dict, bg3: str, text: str, t2: str, acc: str) -> QWidget:
        """Builds one row widget for a single preview result entry.
        Error entries get an informational row with no checkbox — nothing
        to confirm, commit_force_refetch() already treats them as
        skipped_error regardless of confirmed_dates."""
        row = QWidget()
        row.setStyleSheet(f"background: {bg3};")
        row_lay = QVBoxLayout(row)
        row_lay.setContentsMargins(8, 6, 8, 6)
        row_lay.setSpacing(2)

        date_str = entry["date"]

        if entry.get("error") is not None:
            header = QLabel(f"✗  {date_str} — fetch failed")
            header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            header.setStyleSheet("color: #e94560;")
            row_lay.addWidget(header)

            detail = QLabel(str(entry["error"]))
            detail.setFont(QFont("Segoe UI", 8))
            detail.setStyleSheet(f"color: {t2};")
            detail.setWordWrap(True)
            row_lay.addWidget(detail)
            return row

        fields_changed = entry.get("fields_changed", [])
        cb = QCheckBox(
            f"{date_str}:  {entry['quality_before']} → {entry['quality_after']}"
            f"  |  {len(fields_changed)} field(s) changed"
        )
        cb.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cb.setStyleSheet(f"color: {text};")
        cb.setChecked(False)  # explicit opt-in required — Nutzer-Entscheidung 2026-09-01
        self._checkboxes[date_str] = cb
        row_lay.addWidget(cb)

        if fields_changed:
            names = QLabel("   " + ", ".join(fields_changed))
            names.setFont(QFont("Segoe UI", 8))
            names.setStyleSheet(f"color: {t2};")
            names.setWordWrap(True)
            row_lay.addWidget(names)

        if not entry.get("had_prior_data", True):
            note = QLabel("   (no previous data — day was not archived before)")
            note.setFont(QFont("Segoe UI", 8))
            note.setStyleSheet(f"color: {acc};")
            row_lay.addWidget(note)

        return row

    def _set_all(self, checked: bool) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(checked)

    # ── Result ───────────────────────────────────────────────────────────────

    def get_confirmed_dates(self) -> set[str]:
        """Returns the set of dates the user explicitly checked. Any
        preview_results date not in this set is treated as rejected by
        commit_force_refetch() — including error entries, which never
        get a checkbox in the first place."""
        return {d for d, cb in self._checkboxes.items() if cb.isChecked()}
