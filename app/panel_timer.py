#!/usr/bin/env python3
"""
app/panel_timer.py
Garmin Local Archive — Background Timer Panel Mixin

PanelTimerMixin — timer UI (button + fields), toggle, resume-after-sync,
main timer loop, and controller delegates.

Rules:
  - No __init__ — all state lives on the GarminAppBase instance (self)
  - All widget references stored as self._xyz
  - Panel-private helpers use _timer_* prefix (E-7)
"""

import os
import threading
import tkinter as tk

import garmin_app_controller as _controller


class PanelTimerMixin(object):

    def _build_timer_panel(self, parent):
        ft = tk.Frame(parent, bg=self.BG, pady=4)
        ft.pack(fill="x", padx=20, pady=2)
        tk.Label(ft, text="BACKGROUND TIMER", font=("Segoe UI", 7, "bold"),
                 bg=self.BG, fg=self.ACCENT).pack(anchor="w")
        tk.Frame(ft, bg=self.ACCENT, height=1).pack(fill="x", pady=(2, 6))
        timer_row = tk.Frame(ft, bg=self.BG)
        timer_row.pack(fill="x", pady=2)
        self._timer_btn = tk.Button(
            timer_row, text="⏱  Timer: Off", font=self.FONT_BTN,
            bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
            pady=7, padx=14, width=16, cursor="hand2",
            command=self._toggle_timer)
        self._timer_btn.pack(side="left")

        fields_frame = tk.Frame(timer_row, bg=self.BG)
        fields_frame.pack(side="left", padx=(12, 0))
        self.v_timer_min_interval = tk.StringVar()
        self.v_timer_max_interval = tk.StringVar()
        self.v_timer_min_days     = tk.StringVar()
        self.v_timer_max_days     = tk.StringVar()

        def _timer_field(parent, label, var, row, col):
            tk.Label(parent, text=label, font=("Segoe UI", 8),
                     bg=self.BG, fg=self.TEXT2
                     ).grid(row=row, column=col * 2, sticky="e", padx=(8, 2), pady=1)
            tk.Entry(parent, textvariable=var, font=self.FONT_BODY,
                     bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                     relief="flat", bd=4, width=4
                     ).grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 4), pady=1)

        _timer_field(fields_frame, "Min. Interval (min)", self.v_timer_min_interval, 0, 0)
        _timer_field(fields_frame, "Max. Interval (min)", self.v_timer_max_interval, 1, 0)
        _timer_field(fields_frame, "Min. Days per Run",   self.v_timer_min_days,     0, 1)
        _timer_field(fields_frame, "Max. Days per Run",   self.v_timer_max_days,     1, 1)

    def _timer_update_btn(self):
        if not self._timer_btn:
            return
        if self._timer_active:
            self._timer_btn.config(bg=self.GREEN, fg="#0a0a1a")
        else:
            self._timer_btn.config(text="⏱  Timer: Off",
                                   bg=self.BG3, fg=self.TEXT2)

    def _toggle_timer(self):
        if self._timer_active:
            self._timer_generation += 1
            self._timer_stop.set()
            self._timer_active = False
            self._timer_update_btn()
            self._log("⏱  Background timer stopped.")
        else:
            s = self._collect_settings()
            if not s["email"] or not s["password"]:
                self._log("⏱  Background timer: email or password missing.")
                return
            self._timer_generation += 1
            self._timer_stop.clear()
            self._timer_active   = True
            self._timer_next_mode = "repair"
            self._timer_update_btn()
            self._log("⏱  Background timer started.")
            threading.Thread(
                target=self._timer_loop,
                args=(self._timer_generation,),
                daemon=True
            ).start()

    def _timer_resume_after_sync(self, was_active: bool):
        """Restart timer after a manual sync if it was active before."""
        if was_active and not self._timer_active:
            self._timer_generation += 1
            self._timer_stop.clear()
            self._timer_active    = True
            self._timer_next_mode = "repair"
            self._timer_update_btn()
            self._log("⏱  Background timer resumed.")
            threading.Thread(
                target=self._timer_loop,
                args=(self._timer_generation,),
                daemon=True
            ).start()

    def _timer_loop(self, generation: int):
        """
        Main timer loop — runs in a background thread.
        Alternates between repair / quality / fill / bulk-recheck modes.
        Each loop instance carries a generation ID — stale threads exit immediately.
        """
        import random

        def _stale():
            return generation != self._timer_generation or self._timer_stop.is_set()

        # ── Connection test (once per session) ────────────────────────────────
        if not self._connection_verified and not self._timer_conn_verified:
            self.after(0, self._log, "⏱  Background timer: testing connection ...")
            conn_result = threading.Event()
            conn_ok     = [False]

            def _test_conn():
                try:
                    s2 = self._collect_settings()
                    os.environ["GARMIN_OUTPUT_DIR"] = s2["base_dir"]
                    os.environ["GARMIN_EMAIL"]      = s2["email"]
                    os.environ["GARMIN_PASSWORD"]   = s2["password"]
                    import importlib
                    import garmin_config as cfg
                    importlib.reload(cfg)
                    import garmin_api
                    client = garmin_api.login(
                        on_key_required  = self._prompt_enc_key,
                        on_token_expired = self._prompt_token_expired,
                        on_mfa_required  = self._prompt_mfa,
                    )
                    if client is None:
                        raise Exception("Login cancelled")
                    conn_ok[0] = True
                except Exception as e:
                    self.after(0, self._log, f"⏱  Connection failed: {e}")
                finally:
                    conn_result.set()

            threading.Thread(target=_test_conn, daemon=True).start()
            conn_result.wait()

            if _stale():
                return
            if not conn_ok[0]:
                self.after(0, self._log,
                    "⏱  Background timer stopped — connection test failed.")
                self._timer_active = False
                self.after(0, self._timer_update_btn)
                return
            self._timer_conn_verified = True
            self._connection_verified = True
            self.after(0, lambda: [
                self._set_indicator("token", "ok"),
                self._set_indicator("login", "ok"),
                self._set_indicator("api",   "ok"),
                self._set_indicator("data",  "ok"),
            ])
            self.after(0, self._log, "⏱  Connection OK — background timer running.")

        _mode_cycle = ["repair", "quality", "fill"]

        while not _stale():
            s = self._collect_settings()
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
                mode = self._timer_next_mode
                if mode == "repair":
                    days = self._timer_run_repair(s)
                elif mode == "quality":
                    days = self._timer_run_quality(s)
                else:
                    days = self._timer_run_fill(s)
                skipped = days is None

            if not skipped:
                idx = _mode_cycle.index(mode)
                self._timer_next_mode = _mode_cycle[(idx + 1) % 3]
            else:
                remaining_modes = [m for m in _mode_cycle if m != mode]
                days = None
                for other_mode in remaining_modes:
                    if other_mode == "repair":
                        candidate = self._timer_run_repair(s)
                    elif other_mode == "quality":
                        candidate = self._timer_run_quality(s)
                    else:
                        candidate = self._timer_run_fill(s)
                    if candidate is not None:
                        days = candidate
                        mode = other_mode
                        idx  = _mode_cycle.index(mode)
                        self._timer_next_mode = _mode_cycle[(idx + 1) % 3]
                        break

                if days is None:
                    if not _stale():
                        self.after(0, self._log,
                            "⏱  Archive complete — background timer stopped.")
                        self._timer_active = False
                        self.after(0, self._timer_update_btn)
                    return

            n_days         = random.randint(min_days, max_days)
            days_pick      = days[:n_days] if mode == "bulk" \
                             else sorted(random.sample(days, min(n_days, len(days))))
            sync_dates_str = ",".join(d.isoformat() for d in days_pick)
            days_left      = len(days_pick)
            queue_total    = len(days)

            label = {"repair": "Repair", "quality": "Quality",
                     "fill": "Fill", "bulk": "Bulk Recheck"}.get(mode, mode)
            self.after(0, self._log,
                f"⏱  [{label}] Syncing {days_left} days ({queue_total} in queue)")

            while self._is_running():
                if _stale():
                    return
                self._timer_stop.wait(timeout=0.5)

            refresh       = (mode in ("repair", "quality", "bulk"))
            env_overrides = {
                "GARMIN_SYNC_DATES":         sync_dates_str,
                "GARMIN_REFRESH_FAILED":     "1" if refresh else "0",
                "GARMIN_SESSION_LOG_PREFIX": "garmin_background",
            }
            sync_done = threading.Event()

            def _on_done():
                sync_done.set()

            self.after(0, lambda eo=env_overrides, d=_on_done, dl=days_left: self._run(
                "garmin_collector.py",
                enable_stop=False,
                refresh_failed=refresh,
                log_prefix="garmin_background",
                env_overrides=eo,
                on_done=d,
                stop_event=self._timer_stop,
                days_left=dl,
            ))

            while not sync_done.is_set():
                if _stale():
                    return
                self._timer_stop.wait(timeout=0.5)

            if _stale():
                return

            wait_secs = random.randint(min_interval * 60, max_interval * 60)
            for remaining in range(wait_secs, 0, -1):
                if _stale():
                    return
                mins, secs = divmod(remaining, 60)
                self.after(0, lambda t=f"{mins:02d}:{secs:02d}": (
                    self._timer_btn and self._timer_btn.config(text=f"⏱  {t}")
                ) if self._timer_active else None)
                self._timer_stop.wait(timeout=1)

    def _timer_run_repair(self, s: dict):
        """Delegates to garmin_app_controller.timer_run_repair."""
        return _controller.timer_run_repair(s)

    def _timer_run_bulk_recheck(self, s: dict):
        """Delegates to garmin_app_controller.timer_run_bulk_recheck."""
        return _controller.timer_run_bulk_recheck(s)

    def _timer_run_quality(self, s: dict):
        """Delegates to garmin_app_controller.timer_run_quality."""
        return _controller.timer_run_quality(s)

    def _timer_run_fill(self, s: dict):
        """Delegates to garmin_app_controller.timer_run_fill."""
        return _controller.timer_run_fill(s)
