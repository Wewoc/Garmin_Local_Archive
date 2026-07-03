#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
app/dialogs.py
Garmin Local Archive — Shared GUI Dialogs

Gemeinsame Dialog-Klassen für den App-Layer.
Importiert von panel_archive.py und panel_outputs.py.

Rules:
  - Keine Projekt-Modul-Imports außer PyQt6
  - Keine Geschäftslogik — nur Dialog-UI und Ergebnis-Rückgabe
  - app-Instanz wird als parent übergeben (parent._app für Theme-Farben)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class PasswordConfirmDialog(QDialog):
    """
    Modaler Dialog mit Passwort-Eingabe — optional mit Bestätigungsfeld.

    Verwendet von:
      - panel_archive.py  — Mirror Container Password
        (Export: mode="setup", Import: mode="unlock")
      - panel_outputs.py  — Encrypted Dashboards (mode="setup")

    Parameters
    ----------
    parent      : QWidget — parent widget (muss _app mit Theme-Farben haben)
    title       : str     — Fenstertitel
    heading     : str     — Fett gedruckte Überschrift im Dialog
    description : str     — Beschreibungstext unter der Überschrift
    mode        : str     — "setup" (Standard): zwei Felder, Match-Check —
                             für neu vergebene Passwörter.
                             "unlock": ein Feld, kein Confirm — für bereits
                             existierende Passwörter (z. B. Mirror Import,
                             wo unlock_meta() das Passwort ohnehin prüft).

    Usage
    -----
        dlg = PasswordConfirmDialog(
            parent      = self,
            title       = "Mirror Password",
            heading     = "Mirror Container Password",
            description = "Enter the password for the mirror container.\n"
                          "This password protects data in transit.",
            mode        = "unlock",
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            password = dlg.get_result()
    """

    def __init__(self, parent, title: str, heading: str, description: str,
                 mode: str = "setup"):
        super().__init__(parent)
        self._result = None
        self._mode = mode
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(420)

        app  = parent._app
        bg   = app.BG
        bg3  = app.BG3
        text = app.TEXT
        t2   = app.TEXT2
        acc  = app.ACCENT

        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        # Überschrift
        heading_lbl = QLabel(heading)
        heading_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading_lbl.setStyleSheet(f"color: {text};")
        lay.addWidget(heading_lbl)

        # Beschreibung
        desc_lbl = QLabel(description)
        desc_lbl.setFont(QFont("Segoe UI", 9))
        desc_lbl.setStyleSheet(f"color: {t2};")
        desc_lbl.setWordWrap(True)
        lay.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {bg3};")
        lay.addWidget(sep)

        # Passwort-Felder
        def _pw_field(placeholder):
            f = QLineEdit()
            f.setEchoMode(QLineEdit.EchoMode.Password)
            f.setPlaceholderText(placeholder)
            f.setFont(QFont("Segoe UI", 9))
            f.setStyleSheet(
                f"background: {bg3}; color: {text}; "
                f"border: 1px solid {bg3}; padding: 6px 8px;")
            return f

        pw1_lbl = QLabel("Password")
        pw1_lbl.setFont(QFont("Segoe UI", 8))
        pw1_lbl.setStyleSheet(f"color: {t2};")
        lay.addWidget(pw1_lbl)
        self._pw1 = _pw_field("Enter password")
        lay.addWidget(self._pw1)

        self._pw2 = None
        if self._mode == "setup":
            pw2_lbl = QLabel("Confirm password")
            pw2_lbl.setFont(QFont("Segoe UI", 8))
            pw2_lbl.setStyleSheet(f"color: {t2};")
            lay.addWidget(pw2_lbl)
            self._pw2 = _pw_field("Repeat password")
            lay.addWidget(self._pw2)

        # Fehleranzeige
        self._err = QLabel("")
        self._err.setStyleSheet("color: #e94560;")
        self._err.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._err)

        # Buttons
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setDefault(False)
        ok_btn.setAutoDefault(False)
        ok_btn.clicked.connect(self._on_ok)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setDefault(False)
        cancel_btn.setAutoDefault(False)
        cancel_btn.clicked.connect(self.reject)

        # Enter-Handling: pw1 → pw2 (falls vorhanden) → _on_ok
        if self._pw2 is not None:
            self._pw1.returnPressed.connect(lambda: self._pw2.setFocus())
            self._pw2.returnPressed.connect(self._on_ok)
        else:
            self._pw1.returnPressed.connect(self._on_ok)

        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    def _on_ok(self):
        p1 = self._pw1.text()
        if not p1:
            QMessageBox.warning(self, self.windowTitle(),
                                "Please enter a password.")
            self._pw1.setFocus()
            return
        if self._pw2 is not None:
            p2 = self._pw2.text()
            if not p2:
                QMessageBox.warning(self, self.windowTitle(),
                                    "Please confirm your password.")
                self._pw2.setFocus()
                return
            if p1 != p2:
                QMessageBox.warning(self, self.windowTitle(),
                                    "Passwords do not match.\nPlease try again.")
                self._pw2.clear()
                self._pw2.setFocus()
                return
        self._result = p1
        self.accept()

    def get_result(self) -> str | None:
        return self._result
