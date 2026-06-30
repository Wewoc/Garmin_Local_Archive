#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
app/panel_settings.py
Garmin Local Archive — Settings Panel

PanelSettings — PyQt6 QWidget for credentials, paths, sync config,
personal profile, advanced settings, and context location.

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - All widget references stored as self._xyz
  - Panel-private helpers use _settings_* prefix (E-7)
  - _collect_settings() is the central settings reader — called by all panels
"""

import re
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFileDialog, QMessageBox, QScrollArea,
    QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_settings as _settings
from garmin_app_settings import load_password, save_password


class PanelSettings(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._log_level = "INFO"
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet(f"background: {self._app.BG2};")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(12, 14, 12, 12)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel("Settings")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {self._app.TEXT};")
        self._layout.addWidget(heading)

        # Garmin Account
        s = self._section("Garmin Account")
        self._email    = self._field(s, "Email")
        self._email.setToolTip("Your Garmin Connect login email address.")
        self._password = self._field(s, "Password", password=True)
        self._password.setToolTip(
            "Your Garmin Connect password.\n"
            "Stored securely in Windows Credential Manager.")

        # Storage
        s2 = self._section("Storage")
        self._base_dir   = self._field_browse(s2, "Data folder",   self._browse_folder)
        self._base_dir.setToolTip(
            "Root folder where the archive is stored.\n"
            "Subfolders (garmin_data/, context_data/) are created automatically.")
        self._mirror_dir = self._field_browse(s2, "Mirror target", self._browse_mirror_file)
        self._mirror_dir.setToolTip(
            "Path to the .gla container file for encrypted backup.\n"
            "Use Export to Mirror to create or update the backup.")

        # Sync Mode
        s3 = self._section("Sync Mode")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        lbl = QLabel("Mode")
        lbl.setFixedWidth(110)
        lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        lbl.setFont(QFont("Segoe UI", 9))
        self._sync_mode = QComboBox()
        self._sync_mode.addItems(["recent", "range", "auto"])
        self._sync_mode.setFixedWidth(120)
        self._sync_mode.setStyleSheet(self._combobox_style())
        self._sync_mode.setToolTip(
            "recent — sync the last N days (set Days below)\n"
            "range  — sync a fixed date range\n"
            "auto   — sync from fallback date to today")
        self._sync_mode.currentTextChanged.connect(self._on_sync_mode_change)
        mode_row.addWidget(lbl)
        mode_row.addWidget(self._sync_mode)
        mode_row.addStretch()
        s3.addLayout(mode_row)

        self._sync_days     = self._field(s3, "Days (recent)",   width=80)
        self._sync_days.setToolTip(
            "Number of recent days to check on each sync.\n"
            "Active in 'recent' mode only.")
        self._sync_from     = self._field(s3, "From (range)",    width=100)
        self._sync_from.setToolTip("Start date for range sync (YYYY-MM-DD).")
        self._sync_to       = self._field(s3, "To (range)",      width=100)
        self._sync_to.setToolTip("End date for range sync (YYYY-MM-DD).")
        self._sync_fallback = self._field(s3, "Fallback (auto)", width=100)
        self._sync_fallback.setToolTip(
            "Earliest date for auto sync (YYYY-MM-DD).\n"
            "Syncs from this date to today if no recent data exists.")

        # Export Date Range
        s4 = self._section("Export Date Range")
        self._date_from = self._field(s4, "From", width=100)
        self._date_from.setToolTip(
            "Start date for Excel/dashboard export (YYYY-MM-DD).\n"
            "Leave empty — default: 30 days back from today.")
        self._date_to   = self._field(s4, "To",   width=100)
        self._date_to.setToolTip(
            "End date for Excel/dashboard export (YYYY-MM-DD).\n"
            "Leave empty — default: today.")
        hint = QLabel("Leave empty for all available data")
        hint.setFont(QFont("Segoe UI", 7))
        hint.setStyleSheet(f"color: {self._app.TEXT2};")
        s4.addWidget(hint)

        # Personal Profile
        s5 = self._section("Personal Profile")
        self._age = self._field(s5, "Age", width=60)
        self._age.setToolTip(
            "Your age in years.\n"
            "Used to calculate HRV reference values in dashboards.")
        sex_row = QHBoxLayout()
        sex_row.setSpacing(8)
        sex_lbl = QLabel("Sex")
        sex_lbl.setFixedWidth(110)
        sex_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        sex_lbl.setFont(QFont("Segoe UI", 9))
        self._sex = QComboBox()
        self._sex.addItems(["male", "female"])
        self._sex.setFixedWidth(120)
        self._sex.setStyleSheet(self._combobox_style())
        self._sex.setToolTip(
            "Used to calculate HRV reference values in dashboards.")
        sex_row.addWidget(sex_lbl)
        sex_row.addWidget(self._sex)
        sex_row.addStretch()
        s5.addLayout(sex_row)

        # Advanced
        s6 = self._section("Advanced")
        self._delay_min = self._field(s6, "Delay min (s)", width=60)
        self._delay_min.setToolTip(
            "Minimum delay between API requests in seconds.\n"
            "Recommended: 5.0 or higher to avoid rate limiting (HTTP 429).")
        self._delay_max = self._field(s6, "Delay max (s)", width=60)
        self._delay_max.setToolTip(
            "Maximum delay between API requests in seconds.\n"
            "Recommended: 20.0. A random value between min and max is used.")
        warn = QLabel(
            "⚠  Low delay values (< 5s) increase the risk of IP bans (HTTP 429). "
            "Recommended: min 5.0 / max 20.0"
        )
        warn.setFont(QFont("Segoe UI", 7))
        warn.setStyleSheet(f"color: {self._app.YELLOW};")
        warn.setWordWrap(True)
        s6.addWidget(warn)

        # Context
        s7 = self._section("Context")
        self._maps_url = self._field(s7, "Maps URL", width=200)
        self._maps_url.setToolTip(
            "Paste a Google Maps URL of your location.\n"
            "Click 'Set Location' to extract latitude and longitude.")
        ctx_row = QHBoxLayout()
        ctx_row.setSpacing(8)
        loc_btn = QPushButton("📍  Set Location")
        loc_btn.setFont(QFont("Segoe UI", 9))
        loc_btn.setStyleSheet(self._btn_style(self._app.BG3, self._app.TEXT))
        loc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        loc_btn.setToolTip(
            "Extract latitude and longitude from the Maps URL above\n"
            "and save them as your context location.")
        loc_btn.clicked.connect(self._set_location_from_maps)
        self._ctx_coords_label = QLabel("")
        self._ctx_coords_label.setFont(QFont("Segoe UI", 7))
        self._ctx_coords_label.setStyleSheet(f"color: {self._app.TEXT2};")
        ctx_row.addWidget(loc_btn)
        ctx_row.addWidget(self._ctx_coords_label)
        ctx_row.addStretch()
        s7.addLayout(ctx_row)
        maps_hint = QLabel("→ Open Google Maps, find your location, copy the URL")
        maps_hint.setFont(QFont("Segoe UI", 7))
        maps_hint.setStyleSheet(
            f"color: {self._app.ACCENT}; text-decoration: underline;")
        maps_hint.setCursor(Qt.CursorShape.PointingHandCursor)
        maps_hint.mousePressEvent = lambda e: _settings._open_url(
            "https://maps.google.com")
        s7.addWidget(maps_hint)

        # Save
        self._layout.addSpacing(10)
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        save_btn.setStyleSheet(self._btn_style(self._app.ACCENT2, self._app.TEXT, pady=8))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setToolTip("Save all settings to disk.")
        save_btn.clicked.connect(self._save)
        self._layout.addWidget(save_btn)

        # Log level toggle
        self._log_level_hint = QLabel("⚠  Takes effect on next sync")
        self._log_level_hint.setFont(QFont("Segoe UI", 7))
        self._log_level_hint.setStyleSheet(f"color: {self._app.YELLOW};")
        self._log_level_hint.hide()
        self._layout.addWidget(self._log_level_hint)

        self._log_level_btn = QPushButton("📋  Log: Simple")
        self._log_level_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._log_level_btn.setStyleSheet(
            self._btn_style(self._app.BG3, self._app.TEXT2, pady=6))
        self._log_level_btn.setToolTip(
            "Toggle between Simple (INFO) and Detailed (DEBUG) log output.\n"
            "Takes effect on the next sync.")
        self._log_level_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_level_btn.clicked.connect(self._toggle_log_level)
        self._layout.addWidget(self._log_level_btn)

        self._layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _section(self, title: str) -> QVBoxLayout:
        """Creates a titled section and returns its inner QVBoxLayout."""
        self._layout.addSpacing(10)
        header = QLabel(title.upper())
        header.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {self._app.ACCENT};")
        self._layout.addWidget(header)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {self._app.ACCENT};")
        line.setFixedHeight(1)
        self._layout.addWidget(line)
        inner = QVBoxLayout()
        inner.setSpacing(4)
        inner.setContentsMargins(4, 4, 4, 4)
        self._layout.addLayout(inner)
        return inner

    def _field(self, parent: QVBoxLayout, label: str,
               password: bool = False, width: int = 200) -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        entry = QLineEdit()
        entry.setFixedWidth(width)
        entry.setFont(QFont("Segoe UI", 9))
        entry.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 4px;")
        if password:
            entry.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(lbl)
        row.addWidget(entry)
        row.addStretch()
        parent.addLayout(row)
        return entry

    def _field_browse(self, parent: QVBoxLayout, label: str,
                      callback) -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFixedWidth(110)
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        entry = QLineEdit()
        entry.setFixedWidth(130)
        entry.setFont(QFont("Segoe UI", 9))
        entry.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 4px;")
        btn = QPushButton("…")
        btn.setFixedWidth(36)
        btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT2}; color: {self._app.TEXT}; "
            f"border: none; padding: 2px 4px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT}; }}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(callback)
        row.addWidget(lbl)
        row.addWidget(entry)
        row.addWidget(btn)
        row.addStretch()
        parent.addLayout(row)
        return entry

    def _btn_style(self, bg: str, fg: str, pady: int = 4) -> str:
        return (
            f"QPushButton {{ background: {bg}; color: {fg}; border: none; "
            f"padding: {pady}px 12px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
        )

    def _combobox_style(self) -> str:
        return (
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 4px; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; selection-background-color: {self._app.ACCENT2}; }}"
        )

    # ── Logic ──────────────────────────────────────────────────────────────────

    def load_settings_to_ui(self):
        """Called by GarminApp after construction. Populates all fields."""
        s = self._app.settings
        self._email.setText(s.get("email", ""))
        self._password.setText(load_password())
        self._base_dir.setText(s.get("base_dir", str(Path.home() / "local_archive")))
        self._mirror_dir.setText(s.get("mirror_dir", ""))
        idx = self._sync_mode.findText(s.get("sync_mode", "recent"))
        self._sync_mode.setCurrentIndex(max(0, idx))
        self._sync_days.setText(s.get("sync_days", "90"))
        self._sync_from.setText(s.get("sync_from", ""))
        self._sync_to.setText(s.get("sync_to", ""))
        self._sync_fallback.setText(s.get("sync_auto_fallback", ""))
        self._date_from.setText(s.get("date_from", ""))
        self._date_to.setText(s.get("date_to", ""))
        self._age.setText(s.get("age", "35"))
        idx_sex = self._sex.findText(s.get("sex", "male"))
        self._sex.setCurrentIndex(max(0, idx_sex))
        self._delay_min.setText(s.get("request_delay_min", "5.0"))
        self._delay_max.setText(s.get("request_delay_max", "20.0"))
        self._maps_url.setText(s.get("context_location", ""))
        lat = s.get("context_latitude", "0.0")
        lon = s.get("context_longitude", "0.0")
        if float(lat) != 0.0 or float(lon) != 0.0:
            self._ctx_coords_label.setText(f"lat {lat}  lon {lon}")
        self._on_sync_mode_change()

    def _on_sync_mode_change(self):
        mode = self._sync_mode.currentText()
        active = {
            "recent": [self._sync_days],
            "range":  [self._sync_from, self._sync_to],
            "auto":   [self._sync_fallback],
        }.get(mode, [])
        for field in [self._sync_days, self._sync_from,
                      self._sync_to, self._sync_fallback]:
            enabled = field in active
            field.setEnabled(enabled)
            field.setStyleSheet(
                f"background: {self._app.BG3 if enabled else self._app.BG2}; "
                f"color: {self._app.TEXT if enabled else self._app.TEXT2}; "
                f"border: none; padding: 4px;"
            )

    def _collect_settings(self) -> dict:
        return {
            "email":              self._email.text().strip(),
            "password":           self._password.text(),
            "base_dir":           self._base_dir.text().strip(),
            "sync_mode":          self._sync_mode.currentText(),
            "sync_days":          self._sync_days.text().strip(),
            "sync_from":          self._sync_from.text().strip(),
            "sync_to":            self._sync_to.text().strip(),
            "sync_auto_fallback": self._sync_fallback.text().strip(),
            "date_from":          self._date_from.text().strip(),
            "date_to":            self._date_to.text().strip(),
            "age":                self._age.text().strip(),
            "sex":                self._sex.currentText(),
            "request_delay_min":  self._delay_min.text().strip(),
            "request_delay_max":  self._delay_max.text().strip(),
            "context_location":   self._maps_url.text().strip(),
            "context_latitude":   self._app.settings.get("context_latitude", "0.0"),
            "context_longitude":  self._app.settings.get("context_longitude", "0.0"),
            "mirror_dir":                self._mirror_dir.text().strip(),
            "backup_raw_backfill_asked": self._app.settings.get(
                "backup_raw_backfill_asked", False),
            # Timer settings owned by PanelTimer — forwarded from app.settings
            "timer_min_interval": self._app.settings.get("timer_min_interval", "5"),
            "timer_max_interval": self._app.settings.get("timer_max_interval", "30"),
            "timer_min_days":     self._app.settings.get("timer_min_days", "3"),
            "timer_max_days":     self._app.settings.get("timer_max_days", "10"),
        }

    def _toggle_log_level(self):
        if self._log_level == "INFO":
            self._log_level = "DEBUG"
            self._log_level_btn.setText("📋  Log: Detailed")
            self._log_level_btn.setStyleSheet(
                self._btn_style(self._app.BG3, self._app.YELLOW, pady=6))
        else:
            self._log_level = "INFO"
            self._log_level_btn.setText("📋  Log: Simple")
            self._log_level_btn.setStyleSheet(
                self._btn_style(self._app.BG3, self._app.TEXT2, pady=6))
        if self._app._is_running():
            self._app._log("📋  Log level changed — takes effect on next sync.")
            self._log_level_hint.show()
        else:
            self._log_level_hint.hide()

    def _safe_save(self, s: dict = None):
        try:
            _settings.save_settings(s if s is not None else self._collect_settings())
        except OSError as exc:
            QMessageBox.critical(self, "Settings", f"Could not save settings:\n{exc}")

    def _save(self):
        self._app.settings = self._collect_settings()
        save_password(self._app.settings.get("password", ""))
        self._safe_save(self._app.settings)
        self._app._log("✓ Settings saved.")

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select data folder")
        if d:
            self._base_dir.setText(d)

    def _browse_mirror_file(self):
        current = self._mirror_dir.text().strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select mirror container location",
            start_dir + "/archive.gla",
            "GLA Container (*.gla);;All files (*)",
        )
        if path:
            if not path.endswith(".gla"):
                path += ".gla"
            self._mirror_dir.setText(path)
            threading.Thread(
                target=self._app._panel_archive._startup_mirror_check,
                daemon=True).start()

    def _set_location_from_maps(self):
        url = self._maps_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Location",
                                "Please paste a Google Maps URL first.")
            return
        match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
        if not match:
            QMessageBox.warning(
                self, "Location",
                "No coordinates found in URL.\n\n"
                "Open Google Maps, right-click your location → 'What's here?'\n"
                "or search and copy the URL from the browser address bar."
            )
            return
        lat = str(round(float(match.group(1)), 4))
        lon = str(round(float(match.group(2)), 4))
        self._app.settings["context_latitude"]  = lat
        self._app.settings["context_longitude"] = lon
        self._app.settings["context_location"]  = url
        self._ctx_coords_label.setText(f"lat {lat}  lon {lon}")
        self._safe_save(self._app.settings)
        self._app._log(f"Context location set — lat {lat}, lon {lon}")
