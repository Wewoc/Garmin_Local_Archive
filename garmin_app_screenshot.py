#!/usr/bin/env python3
"""
garmin_app_screenshot.py
Garmin Local Archive — Screenshot / Demo Mode

Inherits the complete UI from GarminApp without modification.
Overrides only:
  - Settings / password loading  → dummy data
  - All button commands          → no-ops
  - closeEvent                   → no save

Usage PowerShell:
    python .\\garmin_app_screenshot.py

No credentials, no file I/O, no subprocesses.
Safe to run on any machine.
"""

import sys
from pathlib import Path

# sys.path setup — identical to garmin_app.py
_root = Path(__file__).parent
for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
    sys.path.insert(0, str(_root / _sub))
sys.path.insert(0, str(_root / "app"))

from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import Qt

from garmin_app import GarminApp


# ── Dummy data ─────────────────────────────────────────────────────────────────

DEMO = {
    "email":              "demo@example.com",
    "password":           "MySecurePassword",
    "base_dir":           r"C:\Users\Demo\garmin_data",
    "sync_mode":          "recent",
    "sync_days":          "90",
    "sync_from":          "2023-01-01",
    "sync_to":            "2023-12-31",
    "sync_auto_fallback": "365",
    "date_from":          "",
    "date_to":            "",
    "age":                "35",
    "sex":                "male",
    "request_delay_min":  "5.0",
    "request_delay_max":  "20.0",
    "timer_min_interval": "5",
    "timer_max_interval": "30",
    "timer_min_days":     "3",
    "timer_max_days":     "10",
    "context_latitude":   "0.0",
    "context_longitude":  "0.0",
    "context_location":   "",
    "mirror_dir":         "",
    "backup_raw_backfill_asked": False,
}

DEMO_LOG = [
    "✓ Settings loaded.",
    "✓ Connection verified — Garmin Connect reachable.",
    "▶  Sync started  [recent · 90 days]",
    "  → 2024-03-15  high   ✓",
    "  → 2024-03-14  high   ✓",
    "  → 2024-03-13  medium ✓",
    "  → 2024-03-12  high   ✓",
    "  → 2024-03-11  high   ✓",
    "✓ Sync complete — 5 days processed.",
]


class ScreenshotApp(GarminApp):
    """
    GarminApp subclass for screenshots and documentation.

    What is overridden:
      __init__         — bypasses real settings/password load, fills demo data,
                         sets connection indicators green, writes demo log,
                         disables all buttons.
      closeEvent       — destroys window without saving anything.
      _refresh_archive_info — static demo values.

    Everything else (layout, colours, fonts, sections, widgets) is inherited
    directly from GarminApp and stays in sync automatically.
    """

    def __init__(self):
        super().__init__()
        self._load_demo_settings()
        self._set_connection_indicators_green()
        self._refresh_archive_info()
        self._write_demo_log()
        self._disable_all_buttons()
        self.setWindowTitle("Garmin Local Archive  [SCREENSHOT MODE]")

    # ── Demo settings ──────────────────────────────────────────────────────────

    def _load_demo_settings(self):
        ps = self._panel_settings
        ps._email.setText(DEMO["email"])
        ps._password.setText(DEMO["password"])
        ps._base_dir.setText(DEMO["base_dir"])
        ps._mirror_dir.setText(DEMO["mirror_dir"])
        idx = ps._sync_mode.findText(DEMO["sync_mode"])
        ps._sync_mode.setCurrentIndex(max(0, idx))
        ps._sync_days.setText(DEMO["sync_days"])
        ps._sync_from.setText(DEMO["sync_from"])
        ps._sync_to.setText(DEMO["sync_to"])
        ps._sync_fallback.setText(DEMO["sync_auto_fallback"])
        ps._date_from.setText(DEMO["date_from"])
        ps._date_to.setText(DEMO["date_to"])
        ps._age.setText(DEMO["age"])
        idx_sex = ps._sex.findText(DEMO["sex"])
        ps._sex.setCurrentIndex(max(0, idx_sex))
        ps._delay_min.setText(DEMO["request_delay_min"])
        ps._delay_max.setText(DEMO["request_delay_max"])
        pt = self._panel_timer
        pt._timer_min_interval.setText(DEMO["timer_min_interval"])
        pt._timer_max_interval.setText(DEMO["timer_max_interval"])
        pt._timer_min_days.setText(DEMO["timer_min_days"])
        pt._timer_max_days.setText(DEMO["timer_max_days"])
        ps._on_sync_mode_change()

    # ── Override: close without saving ────────────────────────────────────────

    def closeEvent(self, event):
        self._timer_generation += 1
        self._timer_stop.set()
        event.accept()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_connection_indicators_green(self):
        for dot in self._panel_connection._conn_indicators.values():
            dot.setStyleSheet(f"color: {self.GREEN};")

    def _refresh_archive_info(self):
        pc = self._panel_connection
        pc._info_total.setText("Days: 1825")
        for q, label, val in [
            ("high",   "high", 892),
            ("medium", "med",  876),
            ("low",    "low",  48),
            ("failed", "fail", 9),
        ]:
            pc._info_qdots[q].setText(f"{label} {val}")
        pc._info_recheck.setText("Recheck: 12")
        pc._info_missing.setText("Missing: 37")
        pc._info_range.setText("Range: 2019-03-15 → 2024-03-14")
        pc._info_coverage.setText("Coverage: 98%")
        pc._info_last_api.setText("Last API: 2024-03-14")
        pc._info_last_bulk.setText("Last Bulk: 2022-11-30")

    def _write_demo_log(self):
        for line in DEMO_LOG:
            self._log(line)

    def _disable_all_buttons(self):
        """Walk every QPushButton and replace command with no-op."""
        def _walk(widget):
            if isinstance(widget, QPushButton):
                try:
                    widget.clicked.disconnect()
                except RuntimeError:
                    pass
                widget.setCursor(Qt.CursorShape.ArrowCursor)
            for child in widget.findChildren(type(widget).__mro__[0]):
                pass  # findChildren handles recursion
        # Use Qt's own recursive widget walk
        for btn in self.findChildren(QPushButton):
            try:
                btn.clicked.disconnect()
            except RuntimeError:
                pass
            btn.setCursor(Qt.CursorShape.ArrowCursor)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")
    window = ScreenshotApp()
    window.show()
    sys.exit(qapp.exec())