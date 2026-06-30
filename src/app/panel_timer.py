#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
app/panel_timer.py
Garmin Local Archive — Background Timer Panel

PanelTimer — PyQt6 QWidget for timer button + interval fields,
toggle, resume-after-sync, main timer loop, and controller delegates.

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _timer_* prefix (E-7)
  - Owned state: _timer_active, _timer_stop, _timer_generation,
                 _timer_next_mode, _timer_conn_verified (all on self._app, D-4)
  - Workers never touch widgets — use self._app._dispatch()
  - Prompt delegates go via self._app._panel_connection
"""

import os
import threading

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_controller as _controller


class PanelTimer(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 4, 20, 4)
        lay.setSpacing(0)

        header = QLabel("BACKGROUND TIMER")
        header.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        lay.addWidget(sep)
        lay.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(0)

        self._timer_btn = QPushButton("⏱  Timer: Off")
        self._timer_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._timer_btn.setFixedWidth(160)
        self._timer_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        self._timer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer_btn.clicked.connect(self._toggle_timer)
        row.addWidget(self._timer_btn)
        row.addSpacing(12)

        # 4 interval fields in a 2×2 grid
        fields_widget = QWidget()
        fields_widget.setStyleSheet("background: transparent;")
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout(fields_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)

        def _field(label: str, row: int, col: int) -> QLineEdit:
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            entry = QLineEdit()
            entry.setFixedWidth(40)
            entry.setFont(QFont("Segoe UI", 9))
            entry.setStyleSheet(
                f"background: {self._app.BG3}; color: {self._app.TEXT}; "
                f"border: none; padding: 3px;")
            grid.addWidget(lbl,   row, col * 2)
            grid.addWidget(entry, row, col * 2 + 1)
            return entry

        self._timer_min_interval = _field("Min. Interval (min)", 0, 0)
        self._timer_max_interval = _field("Max. Interval (min)", 1, 0)
        self._timer_min_days     = _field("Min. Days per Run",   0, 1)
        self._timer_max_days     = _field("Max. Days per Run",   1, 1)

        row.addWidget(fields_widget)
        row.addStretch()
        lay.addLayout(row)

    # ── Settings passthrough ───────────────────────────────────────────────────

    def get_timer_settings(self) -> dict:
        """Returns current timer field values. Called by _collect_settings."""
        return {
            "timer_min_interval": self._timer_min_interval.text().strip(),
            "timer_max_interval": self._timer_max_interval.text().strip(),
            "timer_min_days":     self._timer_min_days.text().strip(),
            "timer_max_days":     self._timer_max_days.text().strip(),
        }

    def load_timer_settings(self, s: dict):
        """Populates timer fields from settings dict. Called by GarminApp after construction."""
        self._timer_min_interval.setText(s.get("timer_min_interval", "5"))
        self._timer_max_interval.setText(s.get("timer_max_interval", "30"))
        self._timer_min_days.setText(s.get("timer_min_days", "3"))
        self._timer_max_days.setText(s.get("timer_max_days", "10"))

    # ── Button state ───────────────────────────────────────────────────────────

    def _timer_update_btn(self):
        """Updates timer button appearance (panel_home). Main Thread only."""
        btn = self._app._panel_home._timer_btn
        if self._app._timer_active:
            btn.setText("⏱  Timer: On")
            btn.setStyleSheet(
                f"QPushButton {{ background: {self._app.GREEN}; color: #0a0a1a; "
                f"border: none; padding: 7px 14px; }}")
        else:
            btn.setText("⏱  Timer: Off")
            btn.setStyleSheet(
                f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
                f"border: none; padding: 7px 14px; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")

    # ── Toggle ─────────────────────────────────────────────────────────────────

    def _toggle_timer(self):
        """Toggle timer on/off. Main Thread only."""
        if self._app._timer_active:
            self._app._timer_generation += 1
            self._app._timer_stop.set()
            self._app._timer_active = False
            self._timer_update_btn()
            self._app._log("⏱  Background timer stopped.")
        else:
            s = self._app._panel_settings._collect_settings()
            if not s["email"] or not s["password"]:
                self._app._log("⏱  Background timer: email or password missing.")
                return
            self._app._timer_generation += 1
            self._app._timer_stop.clear()
            self._app._timer_active    = True
            self._app._timer_next_mode = "repair"
            self._timer_update_btn()
            self._app._log("⏱  Background timer started.")
            threading.Thread(
                target=self._timer_loop,
                args=(self._app._timer_generation,),
                daemon=True,
            ).start()

    def _timer_resume_after_sync(self, was_active: bool):
        """Restart timer after a manual sync if it was active before."""
        if was_active and not self._app._timer_active:
            self._app._timer_generation += 1
            self._app._timer_stop.clear()
            self._app._timer_active    = True
            self._app._timer_next_mode = "repair"
            self._timer_update_btn()
            self._app._log("⏱  Background timer resumed.")
            threading.Thread(
                target=self._timer_loop,
                args=(self._app._timer_generation,),
                daemon=True,
            ).start()

    # ── Timer loop (Worker Thread) ─────────────────────────────────────────────

    def _timer_loop(self, generation: int):
        """
        Main timer loop — runs in a background thread.
        Alternates between repair / quality / fill / bulk-recheck modes.
        Each loop instance carries a generation ID — stale threads exit immediately.

        Worker rule (D-5): no widget access. All UI updates via _app._dispatch().
        """
        import random

        def _stale():
            return (generation != self._app._timer_generation
                    or self._app._timer_stop.is_set())

        # ── Connection test (once per session) ────────────────────────────────
        if not self._app._connection_verified and not self._app._timer_conn_verified:
            self._app._dispatch(self._app._log,
                                "⏱  Background timer: testing connection ...")
            conn_result = threading.Event()
            conn_ok     = [False]

            def _test_conn():
                try:
                    s2 = self._app._panel_settings._collect_settings()
                    os.environ["GARMIN_OUTPUT_DIR"] = s2["base_dir"]
                    os.environ["GARMIN_EMAIL"]      = s2["email"]
                    os.environ["GARMIN_PASSWORD"]   = s2["password"]
                    import importlib
                    import garmin_config as cfg
                    importlib.reload(cfg)
                    import garmin_api
                    client = garmin_api.login(
                        on_key_required  = self._app._panel_connection._prompt_enc_key,
                        on_token_expired = self._app._panel_connection._prompt_token_expired,
                        on_mfa_required  = self._app._panel_connection._prompt_mfa,
                    )
                    if client is None:
                        raise Exception("Login cancelled")
                    conn_ok[0] = True
                except Exception as e:
                    self._app._dispatch(self._app._log,
                                        f"⏱  Connection failed: {e}")
                finally:
                    conn_result.set()

            threading.Thread(target=_test_conn, daemon=True).start()
            conn_result.wait()

            if _stale():
                return
            if not conn_ok[0]:
                self._app._dispatch(self._app._log,
                    "⏱  Background timer stopped — connection test failed.")
                self._app._timer_active = False
                self._app._dispatch(self._timer_update_btn)
                return
            self._app._timer_conn_verified = True
            self._app._connection_verified = True
            pc = self._app._panel_connection
            self._app._dispatch(lambda: [
                pc._set_indicator("token", "ok"),
                pc._set_indicator("login", "ok"),
                pc._set_indicator("api",   "ok"),
                pc._set_indicator("data",  "ok"),
            ])
            self._app._dispatch(self._app._log,
                                "⏱  Connection OK — background timer running.")

        _mode_cycle = ["repair", "quality", "fill", "source_backfill"]

        while not _stale():
            s = self._app._panel_settings._collect_settings()
            try:
                min_interval = max(1, int(s.get("timer_min_interval", "5")))
                max_interval = max(min_interval, int(s.get("timer_max_interval", "30")))
                min_days     = max(1, int(s.get("timer_min_days", "3")))
                max_days     = max(min_days, int(s.get("timer_max_days", "10")))
            except ValueError:
                min_interval, max_interval = 5, 30
                min_days,     max_days     = 3, 10

            bulk_days = self._timer_run_bulk_recheck(s)
            if bulk_days is not None:
                days    = bulk_days
                mode    = "bulk"
                skipped = False
            else:
                mode = self._app._timer_next_mode
                if mode == "repair":
                    days = self._timer_run_repair(s)
                elif mode == "quality":
                    days = self._timer_run_quality(s)
                elif mode == "source_backfill":
                    days = self._timer_run_source_backfill(s)
                else:
                    days = self._timer_run_fill(s)
                skipped = days is None

            if not skipped:
                idx = _mode_cycle.index(mode)
                self._app._timer_next_mode = _mode_cycle[(idx + 1) % 4]
            else:
                remaining_modes = [m for m in _mode_cycle if m != mode]
                days = None
                for other_mode in remaining_modes:
                    if other_mode == "repair":
                        candidate = self._timer_run_repair(s)
                    elif other_mode == "quality":
                        candidate = self._timer_run_quality(s)
                    elif other_mode == "source_backfill":
                        candidate = self._timer_run_source_backfill(s)
                    else:
                        candidate = self._timer_run_fill(s)
                    if candidate is not None:
                        days = candidate
                        mode = other_mode
                        idx  = _mode_cycle.index(mode)
                        self._app._timer_next_mode = _mode_cycle[(idx + 1) % 4]
                        break

                if days is None:
                    if not _stale():
                        self._app._dispatch(self._app._log,
                            "⏱  Archive complete — background timer stopped.")
                        self._app._timer_active = False
                        self._app._dispatch(self._timer_update_btn)
                    return

            n_days         = random.randint(min_days, max_days)
            days_pick      = (days[:n_days] if mode in ("bulk", "source_backfill")
                              else sorted(random.sample(days, min(n_days, len(days)))))
            sync_dates_str = ",".join(d.isoformat() for d in days_pick)
            days_left      = len(days_pick)
            queue_total    = len(days)

            label = {"repair": "Repair", "quality": "Quality",
                     "fill": "Fill", "bulk": "Bulk Recheck",
                     "source_backfill": "Source Backfill"}.get(mode, mode)
            self._app._dispatch(self._app._log,
                f"⏱  [{label}] Syncing {days_left} days ({queue_total} in queue)")
            self._app._dispatch(
                lambda dl=days_left: (
                    self._app._panel_home._timer_btn.setText(f"⏱  Syncing · {dl}")
                    if self._app._timer_active else None
                ))

            while self._app._is_running():
                if _stale():
                    return
                self._app._timer_stop.wait(timeout=0.5)

            refresh       = mode in ("repair", "quality", "bulk")
            env_overrides = {
                "GARMIN_SYNC_DATES":         sync_dates_str,
                "GARMIN_REFRESH_FAILED":     "1" if refresh else "0",
                "GARMIN_SESSION_LOG_PREFIX": "garmin_background",
                "GARMIN_SOURCE_BACKFILL":    "1" if mode == "source_backfill" else "0",
            }
            sync_done = threading.Event()

            def _on_done():
                sync_done.set()

            self._app._dispatch(
                lambda eo=env_overrides, d=_on_done, dl=days_left: self._app._run(
                    "garmin_collector.py",
                    enable_stop=False,
                    refresh_failed=refresh,
                    log_prefix="garmin_background",
                    env_overrides=eo,
                    on_done=d,
                    stop_event=self._app._timer_stop,
                    days_left=dl,
                ))

            while not sync_done.is_set():
                if _stale():
                    return
                self._app._timer_stop.wait(timeout=0.5)

            if _stale():
                return

            wait_secs = random.randint(min_interval * 60, max_interval * 60)
            for remaining in range(wait_secs, 0, -1):
                if _stale():
                    return
                mins, secs = divmod(remaining, 60)
                self._app._dispatch(
                    lambda t=f"{mins:02d}:{secs:02d}": (
                        self._app._panel_home._timer_btn.setText(f"⏱  {t}")
                        if self._app._timer_active else None
                    ))
                self._app._timer_stop.wait(timeout=1)

    # ── Controller delegates ───────────────────────────────────────────────────

    def _timer_run_repair(self, s: dict):
        return _controller.timer_run_repair(s)

    def _timer_run_bulk_recheck(self, s: dict):
        return _controller.timer_run_bulk_recheck(s)

    def _timer_run_quality(self, s: dict):
        return _controller.timer_run_quality(s)

    def _timer_run_fill(self, s: dict):
        return _controller.timer_run_fill(s)

    def _timer_run_source_backfill(self, s: dict):
        return _controller.timer_run_source_backfill(s)
