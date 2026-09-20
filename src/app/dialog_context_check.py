#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/dialog_context_check.py
Garmin Local Archive — Context-Archive Integrity Check Dialogs (v1.7.2.3)

Two dialogs for context_silo_check.check_context_archive()'s result:

  ContextCheckResultDialog — shows the read-only findings (missing days
    per source, bad coordinates, day/location list), each collapsible
    and collapsed by default. Missing days are informational only — a
    normal Sync Context run already re-fetches them, no repair action
    exists for that finding (see context_silo_check.py's module
    docstring). The one actionable finding is bad coordinates; its
    button opens ContextCoordinateFixDialog.

  ContextCoordinateFixDialog — checkbox list of bad_coordinates findings
    (pre-checked — all are real defects, not borderline cases), plus one
    shared optional Maps-link line: if a valid Google Maps URL is parsed,
    its coordinate overrides ALL checked findings; otherwise each
    finding's own "expected" coordinate (already computed by
    context_silo_check.py from local_config.csv or the GUI default) is
    used. Same URL regex/rounding as panel_settings.py::_set_location_from_maps()
    — a Maps link means the same thing here as it does there.

Rules (same as dialog_force_refetch.py):
  - No project-module imports besides PyQt6 — the check result / findings
    list is handed in by the caller (panel_outputs.py); these dialogs
    never touch context_silo_check.py or context_silo_repair.py
    themselves. No file I/O, no repair logic here — ContextCoordinateFixDialog
    only decides WHAT to write (get_fixes()), the caller calls
    context_silo_repair.fix_coordinates() with that list.
  - app instance passed as parent (parent._app for theme colors)
"""

import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QScrollArea, QWidget, QFrame, QLineEdit, QToolButton,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

_MAPS_URL_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")


# ══════════════════════════════════════════════════════════════════════════════
#  Collapsible section — small local helper, no state beyond expand/collapse
# ══════════════════════════════════════════════════════════════════════════════

class _CollapsibleSection(QWidget):
    """A toggle-button header + a content widget, collapsed by default.
    No project-specific logic — a generic building block for this
    dialog's three findings lists."""

    def __init__(self, title: str, content: QWidget, app, expanded: bool = False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._toggle = QToolButton()
        self._toggle.setStyleSheet(
            f"QToolButton {{ background: transparent; color: {app.TEXT}; "
            f"border: none; font-weight: bold; }}")
        self._toggle.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._toggle.setText(title)
        self._toggle.clicked.connect(self._on_toggle)
        lay.addWidget(self._toggle)

        self._content = content
        self._content.setVisible(expanded)
        lay.addWidget(self._content)

    def _on_toggle(self):
        expanded = not self._content.isVisible()
        self._content.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


# ══════════════════════════════════════════════════════════════════════════════
#  ContextCheckResultDialog
# ══════════════════════════════════════════════════════════════════════════════

class ContextCheckResultDialog(QDialog):
    """
    Shows the result of context_silo_check.check_context_archive().

    Usage
    -----
        dlg = ContextCheckResultDialog(parent=self, result=result)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # user clicked "Koordinaten korrigieren" — bad_coordinates
            # is guaranteed non-empty here (button is disabled otherwise)
            fix_dlg = ContextCoordinateFixDialog(parent=self, findings=result["bad_coordinates"])
            ...

    Parameters
    ----------
    parent : QWidget — must have ._app with theme colors
    result : dict — the unmodified return value of check_context_archive()
    """

    def __init__(self, parent, result: dict):
        super().__init__(parent)
        self._app = parent._app
        self.setWindowTitle("Context-Archive Check")
        self.setModal(True)
        self.setFixedWidth(460)

        bg, bg3 = self._app.BG, self._app.BG3
        text, t2, acc = self._app.TEXT, self._app.TEXT2, self._app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Context-Archive Check")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(heading)

        totals = result.get("totals", {})
        days_in_range = totals.get("days_in_range", 0)
        missing = result.get("missing_days", {})
        bad_coords = result.get("bad_coordinates", [])
        total_missing = sum(len(v) for v in missing.values())

        summary = QLabel(
            f"{days_in_range} Tag(e) im Bereich  ·  "
            f"{total_missing} fehlend  ·  {len(bad_coords)} Koordinate(n) auffällig"
        )
        summary.setFont(QFont("Segoe UI", 9))
        summary.setStyleSheet(f"color: {t2};")
        summary.setWordWrap(True)
        lay.addWidget(summary)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        # ── Missing days — informational only, no repair action ────────────────
        missing_content = QWidget()
        mc_lay = QVBoxLayout(missing_content)
        mc_lay.setContentsMargins(16, 4, 0, 4)
        mc_lay.setSpacing(2)
        if total_missing == 0:
            mc_lay.addWidget(self._info_label("✓ Keine fehlenden Tage.", t2))
        else:
            hint = QLabel(
                "Fehlende Tage werden beim nächsten \"Sync Context\"-Lauf "
                "automatisch nachgeholt — keine Aktion nötig."
            )
            hint.setFont(QFont("Segoe UI", 8))
            hint.setStyleSheet(f"color: {t2};")
            hint.setWordWrap(True)
            mc_lay.addWidget(hint)
            for source, dates in missing.items():
                if not dates:
                    continue
                mc_lay.addWidget(self._info_label(
                    f"{source}: {len(dates)} Tag(e), z. B. "
                    + ", ".join(dates[:3]) + ("…" if len(dates) > 3 else ""),
                    text))
        lay.addWidget(_CollapsibleSection(
            f"▸ Fehlende Tage ({total_missing})", missing_content, self._app))

        # ── Bad coordinates ──────────────────────────────────────────────────────
        coords_content = QWidget()
        cc_lay = QVBoxLayout(coords_content)
        cc_lay.setContentsMargins(16, 4, 0, 4)
        cc_lay.setSpacing(2)
        if not bad_coords:
            cc_lay.addWidget(self._info_label("✓ Keine auffälligen Koordinaten.", t2))
        else:
            for f in bad_coords[:50]:
                dist = f" ({f['distance_km']} km)" if f.get("distance_km") is not None else ""
                cc_lay.addWidget(self._info_label(
                    f"{f['date']}  {f['source']}  {f['reason']}{dist}", text))
            if len(bad_coords) > 50:
                cc_lay.addWidget(self._info_label(
                    f"… und {len(bad_coords) - 50} weitere", t2))
        lay.addWidget(_CollapsibleSection(
            f"▸ Auffällige Koordinaten ({len(bad_coords)})", coords_content, self._app))

        # ── Day / location list ──────────────────────────────────────────────────
        day_location = result.get("day_location", [])
        loc_content = QWidget()
        lc_lay = QVBoxLayout(loc_content)
        lc_lay.setContentsMargins(16, 4, 0, 4)
        lc_lay.setSpacing(2)
        lc_scroll = QScrollArea()
        lc_scroll.setWidgetResizable(True)
        lc_scroll.setFixedHeight(160)
        lc_scroll.setStyleSheet(f"background: {bg3}; border: none;")
        lc_rows = QWidget()
        lc_rows_lay = QVBoxLayout(lc_rows)
        lc_rows_lay.setContentsMargins(8, 6, 8, 6)
        lc_rows_lay.setSpacing(1)
        for e in day_location:
            place = f"{e['place']}, {e['country']}" if e.get("place") else "—"
            lc_rows_lay.addWidget(self._info_label(
                f"{e['date']}   {e['lat']:.4f}, {e['lon']:.4f}   {place}", text, mono=True))
        lc_rows_lay.addStretch()
        lc_scroll.setWidget(lc_rows)
        lc_lay.addWidget(lc_scroll)
        lay.addWidget(_CollapsibleSection(
            f"▸ Tag / Ort ({len(day_location)})", loc_content, self._app))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        close_btn = QPushButton("Schließen")
        close_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)

        self._fix_btn = QPushButton(f"📍  Koordinaten korrigieren ({len(bad_coords)})")
        self._fix_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._fix_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}"
            f"QPushButton:disabled {{ color: {t2}; background: {bg3}; }}")
        self._fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fix_btn.setEnabled(bool(bad_coords))
        self._fix_btn.clicked.connect(self.accept)

        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._fix_btn)
        lay.addLayout(btn_row)

    def _info_label(self, text: str, color: str, mono: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Consolas" if mono else "Segoe UI", 8))
        lbl.setStyleSheet(f"color: {color};")
        lbl.setWordWrap(True)
        return lbl


# ══════════════════════════════════════════════════════════════════════════════
#  ContextCoordinateFixDialog
# ══════════════════════════════════════════════════════════════════════════════

class ContextCoordinateFixDialog(QDialog):
    """
    Checkbox list of bad_coordinates findings, plus one shared optional
    Maps-link override. Pure UI — does not call context_silo_repair
    itself. The caller (panel_outputs.py) reads get_fixes() after exec()
    returns Accepted and passes that list straight to
    context_silo_repair.fix_coordinates().

    Parameters
    ----------
    parent   : QWidget — must have ._app with theme colors
    findings : list[dict] — result["bad_coordinates"] from
               check_context_archive(), unmodified.
    """

    def __init__(self, parent, findings: list[dict]):
        super().__init__(parent)
        self._app = parent._app
        self._findings = findings
        self._checkboxes: list[tuple[QCheckBox, dict]] = []
        self._link_lat: float | None = None
        self._link_lon: float | None = None

        self.setWindowTitle("Koordinaten korrigieren")
        self.setModal(True)
        self.setFixedWidth(440)

        bg, bg3 = self._app.BG, self._app.BG3
        text, t2, acc = self._app.TEXT, self._app.TEXT2, self._app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        heading = QLabel("Koordinaten korrigieren")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(heading)

        desc = QLabel(
            "Ohne Maps-Link wird für jeden ausgewählten Tag die erwartete "
            "Koordinate übernommen (aus local_config.csv oder dem GUI-Standort). "
            "Jeder Tag wird mit der korrigierten Koordinate neu von der API "
            "abgerufen — das braucht eine Internetverbindung und kann je nach "
            "Anzahl der Tage einen Moment dauern."
        )
        desc.setFont(QFont("Segoe UI", 9))
        desc.setStyleSheet(f"color: {t2};")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        # ── Findings list ─────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(220)
        scroll.setStyleSheet(f"background: {bg3}; border: none;")

        rows_widget = QWidget()
        rows_lay = QVBoxLayout(rows_widget)
        rows_lay.setSpacing(4)
        rows_lay.setContentsMargins(8, 8, 8, 8)

        for f in findings:
            dist = f" — {f['distance_km']} km" if f.get("distance_km") is not None else ""
            elat, elon = f["expected"]
            cb = QCheckBox(
                f"{f['date']}  {f['source']}  ({f['reason']}{dist})\n"
                f"   gespeichert {f['stored'][0]:.4f}, {f['stored'][1]:.4f}  →  "
                f"erwartet {elat:.4f}, {elon:.4f}"
            )
            cb.setFont(QFont("Consolas", 8))
            cb.setStyleSheet(f"color: {text};")
            cb.setChecked(True)   # pre-checked — every entry here is a real defect
            rows_lay.addWidget(cb)
            self._checkboxes.append((cb, f))

        rows_lay.addStretch()
        scroll.setWidget(rows_widget)
        lay.addWidget(scroll)

        # ── Maps-link override ───────────────────────────────────────────────────
        link_lbl = QLabel(
            "Maps-Link (optional — überschreibt die erwartete Koordinate "
            "für ALLE ausgewählten Tage):")
        link_lbl.setFont(QFont("Segoe UI", 8))
        link_lbl.setStyleSheet(f"color: {t2};")
        link_lbl.setWordWrap(True)
        lay.addWidget(link_lbl)

        link_row = QHBoxLayout()
        self._maps_url = QLineEdit()
        self._maps_url.setFont(QFont("Segoe UI", 9))
        self._maps_url.setStyleSheet(
            f"background: {bg3}; color: {text}; border: none; padding: 5px 8px;")
        link_row.addWidget(self._maps_url)

        apply_link_btn = QPushButton("Übernehmen")
        apply_link_btn.setFont(QFont("Segoe UI", 9))
        apply_link_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {text}; "
            f"border: none; padding: 5px 12px; }}")
        apply_link_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_link_btn.clicked.connect(self._on_apply_link)
        link_row.addWidget(apply_link_btn)
        lay.addLayout(link_row)

        self._link_result_lbl = QLabel("")
        self._link_result_lbl.setFont(QFont("Segoe UI", 8))
        self._link_result_lbl.setStyleSheet(f"color: {acc};")
        lay.addWidget(self._link_result_lbl)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        self._apply_btn = QPushButton("✓  Anwenden")
        self._apply_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._apply_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}")
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._apply_btn)
        lay.addLayout(btn_row)

    # ── Maps-link parsing — same regex/rounding as
    #    panel_settings.py::_set_location_from_maps() ──────────────────────────

    def _on_apply_link(self):
        url = self._maps_url.text().strip()
        match = _MAPS_URL_RE.search(url) if url else None
        if not match:
            self._link_lat = self._link_lon = None
            self._link_result_lbl.setText(
                "Keine Koordinate im Link gefunden." if url else "")
            return
        self._link_lat = round(float(match.group(1)), 4)
        self._link_lon = round(float(match.group(2)), 4)
        self._link_result_lbl.setText(
            f"lat {self._link_lat}  lon {self._link_lon} — wird für alle "
            f"ausgewählten Tage verwendet.")

    # ── Result ───────────────────────────────────────────────────────────────

    def get_fixes(self) -> list[dict]:
        """Returns [{"date", "source", "lat", "lon"}, ...] for every
        checked finding — link coordinate if one was parsed, otherwise
        that finding's own "expected" value."""
        fixes = []
        for cb, f in self._checkboxes:
            if not cb.isChecked():
                continue
            if self._link_lat is not None:
                lat, lon = self._link_lat, self._link_lon
            else:
                lat, lon = f["expected"]
            fixes.append({"date": f["date"], "source": f["source"], "lat": lat, "lon": lon})
        return fixes
