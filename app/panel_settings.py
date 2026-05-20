#!/usr/bin/env python3
"""
app/panel_settings.py
Garmin Local Archive — Settings Panel Mixin

PanelSettingsMixin — tkinter UI for credentials, paths, sync config,
personal profile, advanced settings, and context location.

Rules:
  - No __init__ — all state lives on the GarminAppBase instance (self)
  - All widget references stored as self._xyz (never local to this module)
  - Panel-private helpers use _settings_* prefix (E-7)
  - _collect_settings() is the central settings reader — called by all panels
"""

import re
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import garmin_app_settings as _settings
from garmin_app_settings import load_password, save_password


class PanelSettingsMixin(object):

    def _build_settings_panel(self, parent):
        tk.Label(parent, text="Settings", font=self.FONT_HEAD,
                 bg=self.BG2, fg=self.TEXT).pack(anchor="w", padx=16, pady=(14, 0))

        s = self._section(parent, "Garmin Account")
        self.v_email    = tk.StringVar()
        self.v_password = tk.StringVar()
        self._field(s, "Email",    self.v_email)
        self._field(s, "Password", self.v_password, show="•")

        s2 = self._section(parent, "Storage")
        self.v_base_dir   = tk.StringVar()
        self.v_mirror_dir = tk.StringVar()
        row = tk.Frame(s2, bg=self.BG2)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text="Data folder", font=self.FONT_BODY, bg=self.BG2, fg=self.TEXT2,
                 width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.v_base_dir, font=self.FONT_BODY, bg=self.BG3, fg=self.TEXT,
                 insertbackground=self.TEXT, relief="flat", bd=4, width=18).pack(side="left", padx=(2, 2))
        tk.Button(row, text="…", font=self.FONT_BODY, bg=self.ACCENT2, fg=self.TEXT,
                  relief="flat", bd=0, padx=6,
                  command=self._browse_folder).pack(side="left")
        row_m = tk.Frame(s2, bg=self.BG2)
        row_m.pack(fill="x", padx=4, pady=2)
        tk.Label(row_m, text="Mirror folder", font=self.FONT_BODY, bg=self.BG2, fg=self.TEXT2,
                 width=14, anchor="w").pack(side="left")
        tk.Entry(row_m, textvariable=self.v_mirror_dir, font=self.FONT_BODY, bg=self.BG3, fg=self.TEXT,
                 insertbackground=self.TEXT, relief="flat", bd=4, width=18).pack(side="left", padx=(2, 2))
        tk.Button(row_m, text="…", font=self.FONT_BODY, bg=self.ACCENT2, fg=self.TEXT,
                  relief="flat", bd=0, padx=6,
                  command=self._browse_mirror_folder).pack(side="left")

        s3 = self._section(parent, "Sync Mode")
        self.v_sync_mode = tk.StringVar()
        row2 = tk.Frame(s3, bg=self.BG2)
        row2.pack(fill="x", padx=4, pady=2)
        tk.Label(row2, text="Mode", font=self.FONT_BODY, bg=self.BG2, fg=self.TEXT2,
                 width=14, anchor="w").pack(side="left")
        cb = ttk.Combobox(row2, textvariable=self.v_sync_mode,
                          values=["recent", "range", "auto"],
                          state="readonly", width=10, font=self.FONT_BODY)
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_sync_mode_change())
        self.v_sync_days     = tk.StringVar()
        self.v_sync_from     = tk.StringVar()
        self.v_sync_to       = tk.StringVar()
        self.v_sync_fallback = tk.StringVar()
        self._e_sync_days     = self._field(s3, "Days (recent)",   self.v_sync_days,     width=8)
        self._e_sync_from     = self._field(s3, "From (range)",    self.v_sync_from,     width=12)
        self._e_sync_to       = self._field(s3, "To (range)",      self.v_sync_to,       width=12)
        self._e_sync_fallback = self._field(s3, "Fallback (auto)", self.v_sync_fallback, width=12)

        s4 = self._section(parent, "Export Date Range")
        self.v_date_from = tk.StringVar()
        self.v_date_to   = tk.StringVar()
        self._field(s4, "From", self.v_date_from, width=12)
        self._field(s4, "To",   self.v_date_to,   width=12)
        tk.Label(s4, text="Leave empty for all available data",
                 font=("Segoe UI", 7), bg=self.BG2, fg=self.TEXT2).pack(anchor="w", padx=4)

        s5 = self._section(parent, "Personal Profile")
        self.v_age = tk.StringVar()
        self.v_sex = tk.StringVar()
        self._field(s5, "Age", self.v_age, width=6)
        row3 = tk.Frame(s5, bg=self.BG2)
        row3.pack(fill="x", padx=4, pady=2)
        tk.Label(row3, text="Sex", font=self.FONT_BODY, bg=self.BG2, fg=self.TEXT2,
                 width=14, anchor="w").pack(side="left")
        ttk.Combobox(row3, textvariable=self.v_sex,
                     values=["male", "female"], state="readonly",
                     width=10, font=self.FONT_BODY).pack(side="left", padx=2)

        s6 = self._section(parent, "Advanced")
        self.v_delay_min = tk.StringVar()
        self.v_delay_max = tk.StringVar()
        self._field(s6, "Delay min (s)", self.v_delay_min, width=6)
        self._field(s6, "Delay max (s)", self.v_delay_max, width=6)
        tk.Label(s6,
                 text="⚠  Low delay values (< 5s) increase the risk of IP bans (HTTP 429). "
                      "Recommended: min 5.0 / max 20.0",
                 font=("Segoe UI", 7), bg=self.BG2, fg=self.YELLOW, anchor="w",
                 wraplength=240, justify="left").pack(anchor="w", padx=16, pady=(2, 4))

        s7 = self._section(parent, "Context")
        self.v_maps_url = tk.StringVar()
        self._field(s7, "Maps URL", self.v_maps_url, width=18)
        ctx_btn_row = tk.Frame(s7, bg=self.BG2)
        ctx_btn_row.pack(fill="x", padx=4, pady=2)
        tk.Button(ctx_btn_row, text="📍  Set Location", font=self.FONT_BODY,
                  bg=self.BG3, fg=self.TEXT, relief="flat", bd=0, pady=4, padx=10,
                  cursor="hand2", command=self._set_location_from_maps).pack(side="left")
        self._ctx_coords_label = tk.Label(ctx_btn_row, text="",
                                          font=("Segoe UI", 7), bg=self.BG2, fg=self.TEXT2)
        self._ctx_coords_label.pack(side="left", padx=8)
        maps_hint = tk.Label(s7, text="→ Open Google Maps, find your location, copy the URL",
                             font=("Segoe UI", 7), bg=self.BG2, fg=self.ACCENT, cursor="hand2")
        maps_hint.pack(anchor="w", padx=16, pady=(0, 4))
        maps_hint.bind("<Button-1>", lambda e: _settings._open_url("https://maps.google.com"))

        tk.Frame(parent, bg=self.BG2, height=10).pack()
        tk.Button(parent, text="💾  Save Settings", font=self.FONT_BTN,
                  bg=self.ACCENT2, fg=self.TEXT, relief="flat", bd=0, pady=8, padx=12,
                  cursor="hand2", command=self._save).pack(fill="x", padx=12, pady=8)

        self._log_level = "INFO"
        log_frame = tk.Frame(parent, bg=self.BG2)
        log_frame.pack(fill="x", padx=12, pady=(0, 8))
        self._log_level_hint = tk.Label(
            log_frame, text="⚠  Takes effect on next sync",
            font=("Segoe UI", 7), bg=self.BG2, fg=self.YELLOW, anchor="w")
        self._log_level_btn = tk.Button(
            log_frame, text="📋  Log: Simple", font=self.FONT_BTN,
            bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0, pady=6, padx=12,
            cursor="hand2", command=self._toggle_log_level)
        self._log_level_btn.pack(fill="x")

    def _load_settings_to_ui(self):
        s = self.settings
        self.v_email.set(s.get("email", ""))
        self.v_password.set(load_password())
        self.v_base_dir.set(s.get("base_dir", str(Path.home() / "local_archive")))
        self.v_sync_mode.set(s.get("sync_mode", "recent"))
        self.v_sync_days.set(s.get("sync_days", "90"))
        self.v_sync_from.set(s.get("sync_from", ""))
        self.v_sync_to.set(s.get("sync_to", ""))
        self.v_sync_fallback.set(s.get("sync_auto_fallback", ""))
        self.v_date_from.set(s.get("date_from", ""))
        self.v_date_to.set(s.get("date_to", ""))
        self.v_age.set(s.get("age", "35"))
        self.v_sex.set(s.get("sex", "male"))
        self.v_delay_min.set(s.get("request_delay_min", "5.0"))
        self.v_delay_max.set(s.get("request_delay_max", "20.0"))
        self.v_timer_min_interval.set(s.get("timer_min_interval", "5"))
        self.v_timer_max_interval.set(s.get("timer_max_interval", "30"))
        self.v_timer_min_days.set(s.get("timer_min_days", "3"))
        self.v_timer_max_days.set(s.get("timer_max_days", "10"))
        self.v_mirror_dir.set(s.get("mirror_dir", ""))
        self.v_maps_url.set(s.get("context_location", ""))
        lat = s.get("context_latitude", "0.0")
        lon = s.get("context_longitude", "0.0")
        if float(lat) != 0.0 or float(lon) != 0.0:
            self._ctx_coords_label.config(text=f"lat {lat}  lon {lon}")
        self._on_sync_mode_change()

    def _on_sync_mode_change(self):
        mode = self.v_sync_mode.get()
        cfg = {
            "recent": {
                self._e_sync_days:     "normal",
                self._e_sync_from:     "disabled",
                self._e_sync_to:       "disabled",
                self._e_sync_fallback: "disabled",
            },
            "range": {
                self._e_sync_days:     "disabled",
                self._e_sync_from:     "normal",
                self._e_sync_to:       "normal",
                self._e_sync_fallback: "disabled",
            },
            "auto": {
                self._e_sync_days:     "disabled",
                self._e_sync_from:     "disabled",
                self._e_sync_to:       "disabled",
                self._e_sync_fallback: "normal",
            },
        }
        for widget, state in cfg.get(mode, {}).items():
            widget.config(
                state=state,
                bg=self.BG3 if state == "normal" else self.BG2,
                fg=self.TEXT if state == "normal" else self.TEXT2,
            )

    def _collect_settings(self) -> dict:
        return {
            "email":              self.v_email.get().strip(),
            "password":           self.v_password.get(),
            "base_dir":           self.v_base_dir.get().strip(),
            "sync_mode":          self.v_sync_mode.get(),
            "sync_days":          self.v_sync_days.get().strip(),
            "sync_from":          self.v_sync_from.get().strip(),
            "sync_to":            self.v_sync_to.get().strip(),
            "sync_auto_fallback": self.v_sync_fallback.get().strip(),
            "date_from":          self.v_date_from.get().strip(),
            "date_to":            self.v_date_to.get().strip(),
            "age":                self.v_age.get().strip(),
            "sex":                self.v_sex.get(),
            "request_delay_min":  self.v_delay_min.get().strip(),
            "request_delay_max":  self.v_delay_max.get().strip(),
            "timer_min_interval": self.v_timer_min_interval.get().strip(),
            "timer_max_interval": self.v_timer_max_interval.get().strip(),
            "timer_min_days":     self.v_timer_min_days.get().strip(),
            "timer_max_days":     self.v_timer_max_days.get().strip(),
            "context_location":   self.v_maps_url.get().strip(),
            "context_latitude":   self.settings.get("context_latitude", "0.0"),
            "context_longitude":  self.settings.get("context_longitude", "0.0"),
            "mirror_dir":                self.v_mirror_dir.get().strip(),
            "backup_raw_backfill_asked": self.settings.get("backup_raw_backfill_asked", False),
        }

    def _toggle_log_level(self):
        if self._log_level == "INFO":
            self._log_level = "DEBUG"
            self._log_level_btn.config(text="📋  Log: Detailed", fg=self.YELLOW)
        else:
            self._log_level = "INFO"
            self._log_level_btn.config(text="📋  Log: Simple", fg=self.TEXT2)
        if self._is_running():
            self._log("📋  Log level changed — takes effect on next sync.")
            self._log_level_hint.pack(fill="x", before=self._log_level_btn)
        else:
            self._log_level_hint.pack_forget()

    def _safe_save(self, s: dict = None):
        """Central wrapper for save_settings() — catches OSError and shows dialog."""
        try:
            _settings.save_settings(s if s is not None else self._collect_settings())
        except OSError as exc:
            messagebox.showerror("Settings", f"Could not save settings:\n{exc}")

    def _save(self):
        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        self._safe_save(self.settings)
        self._log("✓ Settings saved.")

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select data folder")
        if d:
            self.v_base_dir.set(d)

    def _browse_mirror_folder(self):
        d = filedialog.askdirectory(title="Select mirror folder")
        if d:
            self.v_mirror_dir.set(d)
            threading.Thread(target=self._startup_mirror_check, daemon=True).start()

    def _set_location_from_maps(self):
        """Extract lat/lon from a Google Maps URL and save as context location."""
        url = self.v_maps_url.get().strip()
        if not url:
            messagebox.showwarning("Location", "Please paste a Google Maps URL first.")
            return
        match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
        if not match:
            messagebox.showwarning(
                "Location",
                "No coordinates found in URL.\n\n"
                "Open Google Maps, right-click your location → 'What's here?'\n"
                "or search and copy the URL from the browser address bar."
            )
            return
        lat = str(round(float(match.group(1)), 4))
        lon = str(round(float(match.group(2)), 4))
        self.settings["context_latitude"]  = lat
        self.settings["context_longitude"] = lon
        self.settings["context_location"]  = url
        self._ctx_coords_label.config(text=f"lat {lat}  lon {lon}")
        self._safe_save(self.settings)
        self._log(f"Context location set — lat {lat}, lon {lon}")