#!/usr/bin/env python3
"""
garmin_app_screenshot.py
Garmin Local Archive — Screenshot / Demo Mode

Inherits the complete UI from GarminApp without modification.
Overrides only:
  - Settings / password loading  → dummy data
  - All button commands          → no-ops
  - on_close                     → no save

Usage Powershell:
    python .\\garmin_app_screenshot.py

No credentials, no file I/O, no subprocesses.
Safe to run on any machine.
"""

import tkinter as tk
from garmin_app import GarminApp, apply_style, GREEN, TEXT2, YELLOW


# ── Dummy data ─────────────────────────────────────────────────────────────────
DEMO = {
    "email":              "demo@example.com",
    "password":           "MySecurePassword",    # shown as ●●● via show="•"
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
      __init__            — bypasses real settings/password load, fills demo data,
                            sets connection indicators green, writes demo log,
                            disables all buttons.
      _load_settings_to_ui— fills from DEMO dict instead of disk.
      _on_close           — destroys window without saving anything.

    Everything else (layout, colours, fonts, sections, widgets) is inherited
    directly from GarminApp and stays in sync automatically.
    """

    def __init__(self):
        # super().__init__() calls load_settings() which overwrites self.settings.
        # Our _load_settings_to_ui override reads from DEMO directly, so order is fine.
        super().__init__()

        # ── Post-init patches ──────────────────────────────────────────────────
        self._set_connection_indicators_green()
        self._write_demo_log()
        self._disable_all_buttons()

        # Window title hint
        self.title("Garmin Local Archive  [SCREENSHOT MODE]")

    # ── Override: fill fields from DEMO instead of disk ───────────────────────

    def _load_settings_to_ui(self):
        s = DEMO                   # always from DEMO, regardless of self.settings
        self.v_email.set(s["email"])
        self.v_password.set(s["password"])
        self.v_base_dir.set(s["base_dir"])
        self.v_sync_mode.set(s["sync_mode"])
        self.v_sync_days.set(s["sync_days"])
        self.v_sync_from.set(s["sync_from"])
        self.v_sync_to.set(s["sync_to"])
        self.v_sync_fallback.set(s["sync_auto_fallback"])
        self.v_date_from.set(s["date_from"])
        self.v_date_to.set(s["date_to"])
        self.v_age.set(s["age"])
        self.v_sex.set(s["sex"])
        self.v_delay_min.set(s["request_delay_min"])
        self.v_delay_max.set(s["request_delay_max"])
        self.v_timer_min_interval.set(s["timer_min_interval"])
        self.v_timer_max_interval.set(s["timer_max_interval"])
        self.v_timer_min_days.set(s["timer_min_days"])
        self.v_timer_max_days.set(s["timer_max_days"])
        self._on_sync_mode_change()

    # ── Override: close without saving ────────────────────────────────────────

    def _on_close(self):
        self._timer_generation += 1
        self._timer_stop.set()
        self.destroy()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_connection_indicators_green(self):
        """Set all four connection dots to green — looks like a successful test."""
        for dot in self._conn_indicators.values():
            dot.config(fg="#4ecca3")   # GREEN constant value

    def _write_demo_log(self):
        """Pre-fill the log widget with plausible demo output."""
        for line in DEMO_LOG:
            self._log(line)

    def _disable_all_buttons(self):
        """
        Walk every widget in the window and replace Button commands with a no-op.
        Works regardless of how many buttons GarminApp has — zero maintenance.
        """
        def _noop(*args, **kwargs):
            pass

        def _walk(widget):
            if isinstance(widget, tk.Button):
                widget.config(command=_noop, cursor="arrow")
            for child in widget.winfo_children():
                _walk(child)

        _walk(self)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ScreenshotApp()
    apply_style()
    app.mainloop()
