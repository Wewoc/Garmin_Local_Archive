#!/usr/bin/env python3
"""
garmin_app_base.py
Garmin Local Archive — Shared GUI Base Class

Contains all shared logic for garmin_app.py (T1/T2) and
garmin_app_standalone.py (T3). Entry-point files subclass GarminAppBase
and implement three execution-model hooks:

  _run(script_name, ...)  — subprocess (App) or importlib (Standalone)
  _log_bg(text)           — thread-safe log: after(0,_log) vs queue.put
  _is_running() -> bool   — _active_proc is not None vs self._running

No entry-point logic here. No script_dir(), no _find_python(),
no _register_embedded_packages().
"""

import json
import os
import re
import sys
import threading
from pathlib import Path
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox


# ── Settings ───────────────────────────────────────────────────────────────────

SETTINGS_FILE = Path.home() / ".garmin_archive_settings.json"

DEFAULT_SETTINGS = {
    "email":              "",
    "base_dir":           str(Path.home() / "local_archive"),
    "sync_mode":          "recent",
    "sync_days":          "90",
    "sync_from":          "",
    "sync_to":            "",
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
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            data.pop("password", None)
            return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(s: dict):
    safe = {k: v for k, v in s.items() if k != "password"}
    try:
        SETTINGS_FILE.write_text(json.dumps(safe, indent=2))
    except OSError as exc:
        messagebox.showerror("Settings", f"Could not save settings:\n{exc}")


# ── Keyring helpers ────────────────────────────────────────────────────────────

KEYRING_SERVICE = "GarminLocalArchive"
KEYRING_USER    = "garmin_password"

def load_password() -> str:
    """Load password from Windows Credential Manager, fall back to empty."""
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        return pw or ""
    except Exception:
        return ""

def save_password(pw: str):
    """Save password to Windows Credential Manager."""
    try:
        import keyring
        if pw:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, pw)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass
    except Exception:
        pass

def delete_password():
    """Remove password from Windows Credential Manager."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


# ── URL helper ─────────────────────────────────────────────────────────────────

def _open_url(url: str):
    """Open a URL in the default browser."""
    try:
        import webbrowser
        if not webbrowser.open(url):
            os.startfile(url)
    except Exception:
        try:
            os.startfile(url)
        except Exception:
            pass


# ── Colors & fonts ─────────────────────────────────────────────────────────────

from version import APP_VERSION

BG        = "#12101f"
BG2       = "#1a1729"
BG3       = "#231f38"
ACCENT    = "#a259f7"
ACCENT2   = "#6e3fcf"
TEXT      = "#eaeaea"
TEXT2     = "#a0a0b0"
GREEN     = "#4ecca3"
YELLOW    = "#f5a623"
FONT_HEAD = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 9)
FONT_BTN  = ("Segoe UI", 9, "bold")
FONT_LOG  = ("Consolas", 8)


# ── Style ──────────────────────────────────────────────────────────────────────

def apply_style():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox",
        fieldbackground=BG3, background=BG3,
        foreground=TEXT, selectbackground=ACCENT2,
        selectforeground=TEXT, arrowcolor=TEXT2,
        borderwidth=0, relief="flat",
    )
    style.map("TCombobox",
        fieldbackground=[("readonly", BG3)],
        foreground=[("readonly", TEXT)],
    )


# ── Base application ───────────────────────────────────────────────────────────

class GarminAppBase(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title("Garmin Local Archive")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(920, 950)
        self.geometry("1100x980")
        # shared state
        self._stop_btn            = None
        self._last_html           = None
        self._stopped_by_user     = False
        self._connection_verified = False
        self._timer_conn_verified = False
        self._timer_active        = False
        self._timer_stop          = threading.Event()
        self._timer_btn           = None
        self._timer_next_mode     = "repair"
        self._timer_generation    = 0
        self._build_ui()
        self._load_settings_to_ui()
        self.v_sync_mode.set("recent")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(0, self._check_migration)
        threading.Thread(target=self._check_version, daemon=True).start()

    # ── Execution-model hooks ──────────────────────────────────────────────────

    def _run(self, script_name: str, enable_stop: bool = False,
             on_success=None, refresh_failed: bool = False,
             on_done=None, log_prefix: str = "garmin",
             env_overrides: dict = None, stop_event: threading.Event = None,
             days_left: int = None):
        """Subclass implements: subprocess (App) or importlib (Standalone)."""
        raise NotImplementedError

    def _log_bg(self, text: str):
        """Thread-safe log write. Subclass implements per execution model."""
        raise NotImplementedError

    def _is_running(self) -> bool:
        """Returns True if a sync is currently running."""
        raise NotImplementedError

    # ── ENV builder ────────────────────────────────────────────────────────────

    def _build_env_dict(self, s: dict, refresh_failed: bool = False) -> dict:
        """
        Build GARMIN_* environment variables as a pure dict.
        No side effects — callers decide how to apply (Popen env= or os.environ).
        """
        base = Path(s["base_dir"])
        env = {}
        env["PYTHONUTF8"]               = "1"
        env["GARMIN_EMAIL"]             = s["email"]
        env["GARMIN_PASSWORD"]          = s["password"]
        env["GARMIN_OUTPUT_DIR"]        = str(base)
        env["GARMIN_EXPORT_FILE"]       = str(base / "garmin_export.xlsx")
        env["GARMIN_TIMESERIES_FILE"]   = str(base / "garmin_timeseries.xlsx")
        env["GARMIN_DASHBOARD_FILE"]    = str(base / "garmin_dashboard.html")
        env["GARMIN_ANALYSIS_HTML"]     = str(base / "garmin_analysis.html")
        env["GARMIN_ANALYSIS_JSON"]     = str(base / "garmin_analysis.json")
        env["GARMIN_SYNC_MODE"]         = s["sync_mode"]
        env["GARMIN_DAYS_BACK"]         = s["sync_days"] or "90"
        env["GARMIN_SYNC_START"]        = s.get("sync_from", "")
        env["GARMIN_SYNC_END"]          = s.get("sync_to", "")
        env["GARMIN_SYNC_FALLBACK"]     = s.get("sync_auto_fallback", "")
        env["GARMIN_REQUEST_DELAY_MIN"] = s["request_delay_min"]
        env["GARMIN_REQUEST_DELAY_MAX"] = s["request_delay_max"]
        env["GARMIN_REFRESH_FAILED"]    = "1" if refresh_failed else "0"

        _today  = date.today()
        _d_from = s.get("date_from", "").strip()
        _d_to   = s.get("date_to",   "").strip()

        if not _d_from or not _d_to:
            _summary_dir = Path(s.get("base_dir", "")) / "garmin_data" / "summary"
            _dates = sorted(
                f.stem.replace("garmin_", "")
                for f in _summary_dir.glob("garmin_???-??-??.json")
            ) if _summary_dir.exists() else []

        env["GARMIN_DATE_FROM"] = _d_from or (
            _dates[0] if _dates else (_today - timedelta(days=90)).isoformat()
        )
        env["GARMIN_DATE_TO"] = _d_to or (
            _dates[-1] if _dates else _today.isoformat()
        )
        env["GARMIN_PROFILE_AGE"]         = s.get("age", "35")
        env["GARMIN_PROFILE_SEX"]         = s.get("sex", "male")
        env["GARMIN_LOG_LEVEL"]           = getattr(self, "_log_level", "INFO")
        env["GARMIN_SESSION_LOG_PREFIX"]  = "garmin"
        env["GARMIN_SYNC_DATES"]          = ""
        return env

    # ── Migration ──────────────────────────────────────────────────────────────

    def _check_migration(self):
        import shutil
        s        = self._collect_settings()
        base_dir = Path(s.get("base_dir", "")).expanduser()
        old_raw  = base_dir / "raw"
        new_dir  = base_dir / "garmin_data"

        if not old_raw.exists() or new_dir.exists():
            return

        msg = (
            f"Old folder structure detected in:\n{base_dir}\n\n"
            f"The folders raw/, summary/ and log/ will be moved to\n"
            f"garmin_data/.\n\n"
            f"⚠ Recommendation: Create a manual backup of:\n"
            f"{base_dir}\n\n"
            f"Migrate now?"
        )
        confirmed = tk.messagebox.askyesno(
            "Structure migration required", msg,
            icon="warning", default="no",
        )
        if not confirmed:
            tk.messagebox.showinfo(
                "App blocked",
                "The app cannot be used without migration.\n"
                "Please restart the app after creating a manual backup.",
            )
            self.destroy()
            return

        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            for folder in ("raw", "summary", "log"):
                src = base_dir / folder
                dst = new_dir / folder
                if src.exists():
                    shutil.move(str(src), str(dst))
            tk.messagebox.showinfo(
                "Migration complete",
                f"Folders successfully moved to:\n{new_dir}",
            )
        except Exception as e:
            tk.messagebox.showerror(
                "Migration error",
                f"Error moving folders:\n{e}\n\n"
                "Please migrate manually and restart the app.",
            )
            self.destroy()

    # ── UI builder ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=BG3, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="🦄  GARMIN LOCAL ARCHIVE",
                 font=("Segoe UI", 13, "bold"), bg=BG3, fg=TEXT).pack(side="left", padx=20)
        tk.Label(header, text=APP_VERSION,
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT2).pack(side="left", padx=(0, 8))
        tk.Label(header, text="local · private · yours",
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT).pack(side="left", padx=4)
        tk.Label(header, text="GNU GPL v3",
                 font=("Segoe UI", 8), bg=BG3, fg=TEXT2).pack(side="right", padx=8)
        link = tk.Label(header, text="www.github.com/Wewoc/Garmin_Local_Archive",
                        font=("Segoe UI", 8, "underline"), bg=BG3, fg="#6ab0f5", cursor="hand2")
        link.pack(side="right", padx=4)
        link.bind("<Button-1>", lambda e: _open_url("https://www.github.com/Wewoc/Garmin_Local_Archive"))

        # ── Main area ──
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        left_outer = tk.Frame(main, bg=BG2, width=300)
        left_outer.pack(side="left", fill="y", padx=0, pady=0)
        left_outer.pack_propagate(False)
        left_inner = self._make_scrollable_panel(left_outer, bg=BG2)
        self._build_settings_panel(left_inner)

        right_outer = tk.Frame(main, bg=BG)
        right_outer.pack(side="left", fill="both", expand=True)
        right_inner = self._make_scrollable_panel(right_outer, bg=BG)
        self._build_actions_panel(right_inner)
        self.after(200, self._refresh_archive_info)

        log_frame = tk.Frame(self, bg=BG, pady=0)
        log_frame.pack(fill="both", expand=False, padx=0)
        self._build_log(log_frame)

    def _make_scrollable_panel(self, parent, bg):
        canvas   = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview,
                                  bg=bg, troughcolor=bg, relief="flat", bd=0, width=6)
        inner    = tk.Frame(canvas, bg=bg)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _on_enter(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _on_leave(event):
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        return inner

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG2)
        f.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG2, fg=ACCENT).pack(anchor="w", pady=(4, 2))
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(0, 6))
        return f

    def _field(self, parent, label, var, show=None, width=28):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=label, font=FONT_BODY, bg=BG2, fg=TEXT2,
                 width=14, anchor="w").pack(side="left")
        kwargs = dict(textvariable=var, font=FONT_BODY, bg=BG3, fg=TEXT,
                      insertbackground=TEXT, relief="flat", bd=4, width=width)
        if show:
            kwargs["show"] = show
        e = tk.Entry(row, **kwargs)
        e.pack(side="left", padx=(2, 0))
        return e

    def _build_settings_panel(self, parent):
        tk.Label(parent, text="Settings", font=FONT_HEAD,
                 bg=BG2, fg=TEXT).pack(anchor="w", padx=16, pady=(14, 0))

        s = self._section(parent, "Garmin Account")
        self.v_email    = tk.StringVar()
        self.v_password = tk.StringVar()
        self._field(s, "Email",    self.v_email)
        self._field(s, "Password", self.v_password, show="•")

        s2 = self._section(parent, "Storage")
        self.v_base_dir = tk.StringVar()
        row = tk.Frame(s2, bg=BG2)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text="Data folder", font=FONT_BODY, bg=BG2, fg=TEXT2,
                 width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.v_base_dir, font=FONT_BODY, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat", bd=4, width=18).pack(side="left", padx=(2, 2))
        tk.Button(row, text="…", font=FONT_BODY, bg=ACCENT2, fg=TEXT,
                  relief="flat", bd=0, padx=6,
                  command=self._browse_folder).pack(side="left")

        s3 = self._section(parent, "Sync Mode")
        self.v_sync_mode = tk.StringVar()
        row2 = tk.Frame(s3, bg=BG2)
        row2.pack(fill="x", padx=4, pady=2)
        tk.Label(row2, text="Mode", font=FONT_BODY, bg=BG2, fg=TEXT2,
                 width=14, anchor="w").pack(side="left")
        cb = ttk.Combobox(row2, textvariable=self.v_sync_mode,
                          values=["recent", "range", "auto"],
                          state="readonly", width=10, font=FONT_BODY)
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
                 font=("Segoe UI", 7), bg=BG2, fg=TEXT2).pack(anchor="w", padx=4)

        s5 = self._section(parent, "Personal Profile")
        self.v_age = tk.StringVar()
        self.v_sex = tk.StringVar()
        self._field(s5, "Age", self.v_age, width=6)
        row3 = tk.Frame(s5, bg=BG2)
        row3.pack(fill="x", padx=4, pady=2)
        tk.Label(row3, text="Sex", font=FONT_BODY, bg=BG2, fg=TEXT2,
                 width=14, anchor="w").pack(side="left")
        ttk.Combobox(row3, textvariable=self.v_sex,
                     values=["male", "female"], state="readonly",
                     width=10, font=FONT_BODY).pack(side="left", padx=2)

        s6 = self._section(parent, "Advanced")
        self.v_delay_min = tk.StringVar()
        self.v_delay_max = tk.StringVar()
        self._field(s6, "Delay min (s)", self.v_delay_min, width=6)
        self._field(s6, "Delay max (s)", self.v_delay_max, width=6)
        tk.Label(s6, text="⚠  Low delay values (< 5s) increase the risk of IP bans (HTTP 429). Recommended: min 5.0 / max 20.0",
                 font=("Segoe UI", 7), bg=BG2, fg=YELLOW, anchor="w",
                 wraplength=240, justify="left").pack(anchor="w", padx=16, pady=(2, 4))

        s7 = self._section(parent, "Context")
        self.v_maps_url = tk.StringVar()
        self._field(s7, "Maps URL", self.v_maps_url, width=18)
        ctx_btn_row = tk.Frame(s7, bg=BG2)
        ctx_btn_row.pack(fill="x", padx=4, pady=2)
        tk.Button(ctx_btn_row, text="📍  Set Location", font=FONT_BODY,
                  bg=BG3, fg=TEXT, relief="flat", bd=0, pady=4, padx=10,
                  cursor="hand2", command=self._set_location_from_maps).pack(side="left")
        self._ctx_coords_label = tk.Label(ctx_btn_row, text="",
                                          font=("Segoe UI", 7), bg=BG2, fg=TEXT2)
        self._ctx_coords_label.pack(side="left", padx=8)
        maps_hint = tk.Label(s7, text="→ Open Google Maps, find your location, copy the URL",
                             font=("Segoe UI", 7), bg=BG2, fg=ACCENT, cursor="hand2")
        maps_hint.pack(anchor="w", padx=16, pady=(0, 4))
        maps_hint.bind("<Button-1>", lambda e: _open_url("https://maps.google.com"))

        tk.Frame(parent, bg=BG2, height=10).pack()
        tk.Button(parent, text="💾  Save Settings", font=FONT_BTN,
                  bg=ACCENT2, fg=TEXT, relief="flat", bd=0, pady=8, padx=12,
                  cursor="hand2", command=self._save).pack(fill="x", padx=12, pady=8)

        self._log_level = "INFO"
        log_frame = tk.Frame(parent, bg=BG2)
        log_frame.pack(fill="x", padx=12, pady=(0, 8))
        self._log_level_hint = tk.Label(
            log_frame, text="⚠  Takes effect on next sync",
            font=("Segoe UI", 7), bg=BG2, fg=YELLOW, anchor="w")
        self._log_level_btn = tk.Button(
            log_frame, text="📋  Log: Simple", font=FONT_BTN,
            bg=BG3, fg=TEXT2, relief="flat", bd=0, pady=6, padx=12,
            cursor="hand2", command=self._toggle_log_level)
        self._log_level_btn.pack(fill="x")

    def _build_actions_panel(self, parent):
        tk.Label(parent, text="Actions", font=FONT_HEAD,
                 bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14, 0))

        # ── Connection & Archive Status ────────────────────────────────────────
        fc = tk.Frame(parent, bg=BG, pady=4)
        fc.pack(fill="x", padx=20, pady=2)
        tk.Label(fc, text="CONNECTION & ARCHIVE STATUS", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(fc, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        conn_row = tk.Frame(fc, bg=BG)
        conn_row.pack(fill="x", pady=2)

        self._conn_indicators = {}
        ind_frame = tk.Frame(conn_row, bg=BG)
        ind_frame.pack(side="left", padx=(0, 0))
        for key, label in [("token", "Token"), ("login", "Login"),
                            ("api", "API Access"), ("data", "Data")]:
            cell = tk.Frame(ind_frame, bg=BG)
            cell.pack(side="left", padx=(0, 14))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 10), bg=BG, fg=TEXT2)
            dot.pack(side="left")
            tk.Label(cell, text=label, font=FONT_BODY,
                     bg=BG, fg=TEXT2).pack(side="left", padx=(3, 0))
            self._conn_indicators[key] = dot

        tk.Button(conn_row, text="🗑  Clean Archive", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=7, padx=14, cursor="hand2",
                  command=self._clean_archive).pack(side="right")
        tk.Button(conn_row, text="🔑  Reset Token", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=7, padx=14, cursor="hand2",
                  command=self._reset_token).pack(side="right", padx=(0, 4))

        # ── Archive Info Panel ─────────────────────────────────────────────────
        info_frame = tk.Frame(fc, bg=BG)
        info_frame.pack(fill="x", pady=(6, 2))
        _QCOLORS = {"high": GREEN, "medium": YELLOW, "low": TEXT2, "failed": ACCENT}

        row1 = tk.Frame(info_frame, bg=BG)
        row1.pack(fill="x")
        self._info_total = tk.Label(row1, text="Days: —", font=FONT_BODY, bg=BG, fg=TEXT2)
        self._info_total.pack(side="left", padx=(0, 14))

        self._info_qdots = {}
        for q, label in [("high", "high"), ("medium", "med"),
                          ("low", "low"), ("failed", "fail")]:
            cell = tk.Frame(row1, bg=BG)
            cell.pack(side="left", padx=(0, 10))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 9),
                           bg=BG, fg=_QCOLORS[q])
            dot.pack(side="left")
            lbl = tk.Label(cell, text=f"{label} —", font=("Segoe UI", 8),
                           bg=BG, fg=TEXT2)
            lbl.pack(side="left", padx=(2, 0))
            self._info_qdots[q] = lbl

        self._info_recheck = tk.Label(row1, text="Recheck: —",
                                       font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_recheck.pack(side="left", padx=(10, 0))

        self._info_missing = tk.Label(row1, text="Missing: —",
                                       font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_missing.pack(side="left", padx=(10, 0))

        row2 = tk.Frame(info_frame, bg=BG)
        row2.pack(fill="x", pady=(3, 0))
        self._info_range = tk.Label(row2, text="Range: —",
                                     font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_range.pack(side="left", padx=(0, 14))
        self._info_coverage = tk.Label(row2, text="Coverage: —",
                                        font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_coverage.pack(side="left", padx=(0, 14))
        self._info_last_api = tk.Label(row2, text="Last API: —",
                                        font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_last_api.pack(side="left", padx=(0, 14))
        self._info_last_bulk = tk.Label(row2, text="Last Bulk: —",
                                         font=("Segoe UI", 8), bg=BG, fg=TEXT2)
        self._info_last_bulk.pack(side="left")

        # ── Data Collection ────────────────────────────────────────────────────
        f = tk.Frame(parent, bg=BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text="DATA COLLECTION", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=2)
        sync_btn = tk.Button(row, text="▶  Sync Garmin", font=FONT_BTN,
                             bg=ACCENT, fg=TEXT, relief="flat", bd=0,
                             pady=7, padx=14, anchor="w", cursor="hand2",
                             command=self._run_collector)
        sync_btn.pack(side="left", fill="x", expand=True)
        self._stop_btn = tk.Button(row, text="⏹  Stop", font=FONT_BTN,
                                   bg=BG3, fg=TEXT2, relief="flat", bd=0,
                                   pady=7, padx=14, cursor="hand2",
                                   state="disabled",
                                   command=self._stop_collector)
        self._stop_btn.pack(side="left", padx=(4, 0))
        tk.Label(row, text="Fetch missing days from Garmin Connect",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(side="left", padx=10)

        imp_row = tk.Frame(f, bg=BG)
        imp_row.pack(fill="x", pady=2)
        tk.Button(imp_row, text="📥  Import Bulk Export", font=FONT_BTN,
                  bg=BG3, fg=TEXT, relief="flat", bd=0,
                  pady=7, padx=14, anchor="w", cursor="hand2",
                  command=self._run_import).pack(side="left", fill="x", expand=True)
        tk.Label(imp_row,
                 text="Import Garmin GDPR export ZIP or folder (recommended for history)",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(side="left", padx=10)

        _EXPORT_URL = "https://www.garmin.com/en-US/account/datamanagement/exportdata/"
        imp_link_row = tk.Frame(f, bg=BG)
        imp_link_row.pack(fill="x", pady=(0, 2))
        imp_link = tk.Label(imp_link_row, text="→ Request export at garmin.com",
                            font=("Segoe UI", 8), bg=BG, fg=ACCENT, cursor="hand2")
        imp_link.pack(side="left", padx=14)
        imp_link.bind("<Button-1>", lambda e: _open_url(_EXPORT_URL))

        # README — search for README_APP.md in both known locations
        _exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) \
                   else Path(__file__).parent
        _readme_candidates = [
            _exe_dir / "info" / "README_APP.md",
            Path(__file__).parent / "docs" / "README_APP.md",
        ]
        _readme = next((p for p in _readme_candidates if p.exists()), None)
        readme_link = tk.Label(imp_link_row, text="→ Open README",
                               font=("Segoe UI", 8), bg=BG, fg=ACCENT, cursor="hand2")
        readme_link.pack(side="left", padx=14)
        readme_link.bind("<Button-1>", lambda e: os.startfile(_readme) if _readme else None)

        ctx_row = tk.Frame(f, bg=BG)
        ctx_row.pack(fill="x", pady=2)
        self._ctx_btn = tk.Button(ctx_row, text="🌍  Sync Context", font=FONT_BTN,
                                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                                  pady=7, padx=14, anchor="w", cursor="hand2",
                                  command=self._run_context_sync)
        self._ctx_btn.pack(side="left", fill="x", expand=True)
        self._ctx_stop_btn = tk.Button(ctx_row, text="⏹  Stop", font=FONT_BTN,
                                       bg=BG3, fg=TEXT2, relief="flat", bd=0,
                                       pady=7, padx=14, cursor="hand2",
                                       state="disabled",
                                       command=self._stop_context_sync)
        self._ctx_stop_btn.pack(side="left", padx=(4, 0))
        self._ctx_csv_btn = tk.Button(ctx_row, text="📄  CSV", font=FONT_BTN,
                                      bg=BG3, fg=TEXT2, relief="flat", bd=0,
                                      pady=7, padx=14, cursor="hand2",
                                      command=self._open_local_config)
        self._ctx_csv_btn.pack(side="left", padx=(4, 0))
        tk.Label(ctx_row, text="Fetch weather & pollen from Open-Meteo",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(side="left", padx=10)

        # ── Background Timer ───────────────────────────────────────────────────
        ft = tk.Frame(parent, bg=BG, pady=4)
        ft.pack(fill="x", padx=20, pady=2)
        tk.Label(ft, text="BACKGROUND TIMER", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(ft, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        timer_row = tk.Frame(ft, bg=BG)
        timer_row.pack(fill="x", pady=2)
        self._timer_btn = tk.Button(
            timer_row, text="⏱  Timer: Off", font=FONT_BTN,
            bg=BG3, fg=TEXT2, relief="flat", bd=0,
            pady=7, padx=14, width=16, cursor="hand2",
            command=self._toggle_timer)
        self._timer_btn.pack(side="left")

        fields_frame = tk.Frame(timer_row, bg=BG)
        fields_frame.pack(side="left", padx=(12, 0))
        self.v_timer_min_interval = tk.StringVar()
        self.v_timer_max_interval = tk.StringVar()
        self.v_timer_min_days     = tk.StringVar()
        self.v_timer_max_days     = tk.StringVar()

        def _timer_field(parent, label, var, row, col):
            tk.Label(parent, text=label, font=("Segoe UI", 8), bg=BG, fg=TEXT2
                     ).grid(row=row, column=col * 2, sticky="e", padx=(8, 2), pady=1)
            tk.Entry(parent, textvariable=var, font=FONT_BODY,
                     bg=BG3, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=4, width=4
                     ).grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 4), pady=1)

        _timer_field(fields_frame, "Min. Interval (min)", self.v_timer_min_interval, 0, 0)
        _timer_field(fields_frame, "Max. Interval (min)", self.v_timer_max_interval, 1, 0)
        _timer_field(fields_frame, "Min. Days per Run",   self.v_timer_min_days,     0, 1)
        _timer_field(fields_frame, "Max. Days per Run",   self.v_timer_max_days,     1, 1)

        self._action_section(parent, "Export", [
            ("📊  Create Reports", BG3, self._open_dashboard_popup,
             "Select dashboards and create as HTML, Excel or JSON"),
        ])
        self._action_section(parent, "Output", [
            ("📁  Open Data Folder",   BG3, self._open_data_folder,
             "Open garmin_data/ in Explorer"),
            ("📋  Copy Last Error Log", BG3, self._copy_last_error_log,
             "Copy most recent error log to clipboard"),
            ("🗓  Create Task Scheduler XML", BG3, self._create_task_scheduler_xml,
             "Generate daily_update_task.xml for Windows Task Scheduler"),
        ])

    def _action_section(self, parent, title, buttons):
        f = tk.Frame(parent, bg=BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        for label, color, cmd, tooltip in buttons:
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", pady=2)
            btn = tk.Button(row, text=label, font=FONT_BTN,
                            bg=color, fg=TEXT, relief="flat", bd=0,
                            pady=7, padx=14, anchor="w", cursor="hand2",
                            command=cmd)
            btn.pack(side="left", fill="x", expand=True)
            tk.Label(row, text=tooltip, font=("Segoe UI", 8),
                     bg=BG, fg=TEXT2).pack(side="left", padx=10)

    def _create_task_scheduler_xml(self):
        """Generate a configured daily_update_task.xml for Windows Task Scheduler."""
        import shutil as _shutil

        # Locate template — same pattern as README_APP.md
        _exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) \
                   else Path(__file__).parent
        _candidates = [
            _exe_dir / "info" / "daily_update_task.xml",
            Path(__file__).parent / "docs" / "daily_update_task.xml",
        ]
        template_path = next((p for p in _candidates if p.exists()), None)
        if template_path is None:
            messagebox.showerror(
                "Task Scheduler XML",
                "Template file 'daily_update_task.xml' not found.\n"
                "Expected in docs/ (dev) or info/ (build).",
            )
            return

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = tk.Toplevel(self)
        dlg.title("Create Task Scheduler XML")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Create Task Scheduler XML",
                 font=FONT_HEAD, bg=BG, fg=TEXT).pack(padx=20, pady=(16, 4))
        tk.Label(dlg,
                 text="Select your build target and entry point path.\n"
                      "The XML will be saved ready to import into Windows Task Scheduler.",
                 font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(padx=20, pady=(0, 10))

        # Target selection
        target_frame = tk.Frame(dlg, bg=BG)
        target_frame.pack(fill="x", padx=20, pady=4)
        tk.Label(target_frame, text="Build target:", font=FONT_BODY,
                 bg=BG, fg=TEXT2).pack(anchor="w")

        v_target = tk.StringVar(value="T2")

        def _default_path(target: str) -> str:
            if target == "T2":
                p = _exe_dir / "daily_update.bat"
            elif target == "T3":
                p = _exe_dir / "daily_update.exe"
            else:
                return ""
            return str(p) if p.exists() else ""

        def _on_target_change(*_):
            v_path.set(_default_path(v_target.get()))

        _targets = [
            ("T2 — Standard EXE  (daily_update.bat)",  "T2"),
            ("T3 — Standalone EXE  (daily_update.exe)", "T3"),
            ("T1 — Dev  (python daily_update.py)",      "T1"),
        ]
        for label, val in _targets:
            tk.Radiobutton(target_frame, text=label, variable=v_target, value=val,
                           font=FONT_BODY, bg=BG, fg=TEXT, selectcolor=BG3,
                           activebackground=BG, activeforeground=TEXT,
                           command=_on_target_change).pack(anchor="w")

        # Entry point path
        path_frame = tk.Frame(dlg, bg=BG)
        path_frame.pack(fill="x", padx=20, pady=(8, 4))
        tk.Label(path_frame, text="Entry point path:", font=FONT_BODY,
                 bg=BG, fg=TEXT2).pack(anchor="w")
        v_path = tk.StringVar(value=_default_path("T2"))
        path_row = tk.Frame(path_frame, bg=BG)
        path_row.pack(fill="x")
        tk.Entry(path_row, textvariable=v_path, font=FONT_BODY,
                 bg=BG3, fg=TEXT, insertbackground=TEXT,
                 relief="flat", bd=4, width=44).pack(side="left", fill="x", expand=True)

        def _browse():
            t = v_target.get()
            if t == "T2":
                ft = [("Batch files", "*.bat"), ("All files", "*.*")]
            elif t == "T3":
                ft = [("Executable", "*.exe"), ("All files", "*.*")]
            else:
                ft = [("Python files", "*.py"), ("All files", "*.*")]
            p = filedialog.askopenfilename(title="Select entry point", filetypes=ft)
            if p:
                v_path.set(p)

        tk.Button(path_row, text="…", font=FONT_BODY, bg=ACCENT2, fg=TEXT,
                  relief="flat", bd=0, padx=6, command=_browse).pack(side="left", padx=(4, 0))

        tk.Label(dlg,
                 text="⚠  For T1 (Dev): enter the full path to python.exe followed by\n"
                      "   the full path to daily_update.py, separated by a space.",
                 font=("Segoe UI", 7), bg=BG, fg=YELLOW, justify="left").pack(padx=20, pady=(0, 8))

        # ── Buttons ───────────────────────────────────────────────────────────
        def _generate():
            entry = v_path.get().strip()
            if not entry:
                messagebox.showwarning("Task Scheduler XML",
                                       "Please enter the entry point path.", parent=dlg)
                return
            try:
                xml = template_path.read_text(encoding="utf-16")
            except UnicodeError:
                # Fallback: template may not yet be UTF-16 encoded on disk
                xml = template_path.read_text(encoding="utf-8")

            working_dir = str(Path(entry.split()[0]).parent)
            xml = xml.replace("{ENTRY_POINT_PATH}", entry)
            xml = xml.replace("<WorkingDirectory></WorkingDirectory>",
                              f"<WorkingDirectory>{working_dir}</WorkingDirectory>")

            save_path = filedialog.asksaveasfilename(
                parent=dlg,
                title="Save Task Scheduler XML",
                initialfile="daily_update_task.xml",
                defaultextension=".xml",
                filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            )
            if not save_path:
                return
            try:
                Path(save_path).write_text(xml, encoding="utf-16")
                messagebox.showinfo(
                    "Task Scheduler XML",
                    f"Saved to:\n{save_path}\n\n"
                    "Import via Task Scheduler → Action → Import Task…",
                    parent=dlg,
                )
                dlg.destroy()
            except OSError as exc:
                messagebox.showerror("Task Scheduler XML",
                                     f"Could not write file:\n{exc}", parent=dlg)

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(pady=(4, 16))
        tk.Button(btn_row, text="Generate & Save", font=FONT_BTN,
                  bg=ACCENT, fg=TEXT, relief="flat", bd=0,
                  pady=7, padx=16, cursor="hand2",
                  command=_generate).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=7, padx=16, cursor="hand2",
                  command=dlg.destroy).pack(side="left", padx=4)

    def _build_log(self, parent):
        bar = tk.Frame(parent, bg=BG3, pady=4)
        bar.pack(fill="x")
        tk.Label(bar, text="LOG", font=("Segoe UI", 7, "bold"),
                 bg=BG3, fg=ACCENT).pack(side="left", padx=12)
        tk.Button(bar, text="Clear", font=("Segoe UI", 7),
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  command=self._clear_log).pack(side="right", padx=12)
        self.log = scrolledtext.ScrolledText(
            parent, height=10, font=FONT_LOG,
            bg="#0a0a1a", fg=GREEN, insertbackground=GREEN,
            relief="flat", bd=0, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

    # ── Version check ──────────────────────────────────────────────────────────

    def _check_version(self):
        import urllib.request
        import json as _json
        url = "https://api.github.com/repos/Wewoc/Garmin_Local_Archive/releases/latest"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GarminLocalArchive"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode())
            latest = data.get("tag_name", "").strip()
            if latest and latest.lstrip("vV") != APP_VERSION.lstrip("vV"):
                self.after(0, self._show_update_popup, latest)
        except Exception:
            pass

    def _show_update_popup(self, latest: str):
        import webbrowser
        popup = tk.Toplevel(self)
        popup.title("Update Available")
        popup.resizable(False, False)
        popup.configure(bg=BG)
        pad = {"padx": 20, "pady": 8}
        tk.Label(popup, text="Update Available",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(**pad)
        tk.Label(popup,
                 text=f"A new version is available: {latest}\nYou are running: {APP_VERSION}",
                 font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(**pad)

        def _open():
            webbrowser.open("https://github.com/Wewoc/Garmin_Local_Archive/releases/latest")
            popup.destroy()

        btn_row = tk.Frame(popup, bg=BG)
        btn_row.pack(pady=12)
        tk.Button(btn_row, text="Open GitHub", font=FONT_BTN, bg=ACCENT, fg=TEXT,
                  relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                  command=_open).pack(side="left", padx=4)
        tk.Button(btn_row, text="Dismiss", font=FONT_BTN, bg=BG3, fg=TEXT2,
                  relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                  command=popup.destroy).pack(side="left", padx=4)

    # ── Settings ───────────────────────────────────────────────────────────────

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
                bg=BG3 if state == "normal" else BG2,
                fg=TEXT if state == "normal" else TEXT2,
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
        }

    def _toggle_log_level(self):
        if self._log_level == "INFO":
            self._log_level = "DEBUG"
            self._log_level_btn.config(text="📋  Log: Detailed", fg=YELLOW)
        else:
            self._log_level = "INFO"
            self._log_level_btn.config(text="📋  Log: Simple", fg=TEXT2)
        if self._is_running():
            self._log("📋  Log level changed — takes effect on next sync.")
            self._log_level_hint.pack(fill="x", before=self._log_level_btn)
        else:
            self._log_level_hint.pack_forget()

    def _save(self):
        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        save_settings(self.settings)
        self._log("✓ Settings saved.")

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select data folder")
        if d:
            self.v_base_dir.set(d)

    # ── Log ────────────────────────────────────────────────────────────────────

    def _log(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ── Actions ────────────────────────────────────────────────────────────────

    def _set_indicator(self, key: str, state: str):
        colors = {"pending": "#f5a623", "ok": "#4ecca3", "fail": "#e94560", "reset": TEXT2}
        self._conn_indicators[key].config(fg=colors.get(state, TEXT2))

    def _refresh_archive_info(self):
        """Reads quality_log.json and updates the Archive Info Panel labels."""
        try:
            import garmin_quality as quality
            s = self._collect_settings()
            base_dir = Path(s.get("base_dir") or "~/local_archive").expanduser()
            quality_log = base_dir / "garmin_data" / "log" / "quality_log.json"
            stats = quality.get_archive_stats(quality_log)
        except Exception:
            return

        def _apply():
            try:
                self._info_total.config(text=f"Days: {stats['total']}")
                for q, lbl_text in [("high", "high"), ("medium", "med"),
                                     ("low", "low"), ("failed", "fail")]:
                    self._info_qdots[q].config(text=f"{lbl_text} {stats[q]}")
                self._info_recheck.config(text=f"Recheck: {stats['recheck']}")
                m = stats.get("missing")
                self._info_missing.config(
                    text=f"Missing: {m}" if m is not None else "Missing: —")
                if stats["date_min"] and stats["date_max"]:
                    self._info_range.config(
                        text=f"Range: {stats['date_min']} → {stats['date_max']}")
                else:
                    self._info_range.config(text="Range: —")
                cov = stats["coverage_pct"]
                self._info_coverage.config(
                    text=f"Coverage: {cov}%" if cov is not None else "Coverage: —")
                self._info_last_api.config(
                    text=f"Last API: {stats['last_api']}" if stats["last_api"] else "Last API: —")
                self._info_last_bulk.config(
                    text=f"Last Bulk: {stats['last_bulk']}" if stats["last_bulk"] else "Last Bulk: —")
            except Exception:
                pass

        self.after(0, _apply)

    def _run_connection_test(self, on_success=None):
        """Test Token → Login → API Access → Data in a background thread."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Connection test: email or password missing.")
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._log("\n🔌  Testing connection ...")

        def worker():
            s_inner = self._collect_settings()
            os.environ["GARMIN_OUTPUT_DIR"] = s_inner["base_dir"]
            os.environ["GARMIN_EMAIL"]      = s_inner["email"]
            os.environ["GARMIN_PASSWORD"]   = s_inner["password"]
            import importlib
            import garmin_config as cfg
            importlib.reload(cfg)
            import garmin_security

            try:
                from garminconnect import Garmin
            except ImportError:
                self._log_bg("✗ garminconnect not installed.")
                return

            token_file_exists = cfg.GARMIN_TOKEN_FILE.exists()
            enc_key_present   = garmin_security.get_enc_key() is not None

            if not token_file_exists:
                self.after(0, self._set_indicator, "token", "reset")
            elif token_file_exists and not enc_key_present:
                self.after(0, self._set_indicator, "token", "fail")
                self._log_bg("  ⚠ Encryption key missing — re-entry required")
            else:
                self.after(0, self._set_indicator, "token", "pending")

            self.after(0, self._set_indicator, "login", "pending")
            try:
                import garmin_api
                client = garmin_api.login(
                    on_key_required  = self._prompt_enc_key,
                    on_token_expired = self._prompt_token_expired,
                    on_mfa_required  = self._prompt_mfa,
                )
                token_now = cfg.GARMIN_TOKEN_FILE.exists() and \
                            garmin_security.get_enc_key() is not None
                self.after(0, self._set_indicator, "token", "ok" if token_now else "reset")
                self.after(0, self._set_indicator, "login", "ok")
                self._log_bg("  ✓ Login successful")
            except SystemExit:
                self.after(0, self._set_indicator, "login", "fail")
                self.after(0, self._set_indicator, "token", "fail")
                self._log_bg("  ✗ Login failed or cancelled")
                return
            except Exception as e:
                self.after(0, self._set_indicator, "login", "fail")
                self._log_bg(f"  ✗ Login failed: {e}")
                return

            self.after(0, self._set_indicator, "api", "pending")
            try:
                client.get_user_profile()
                self.after(0, self._set_indicator, "api", "ok")
                self._log_bg("  ✓ API access OK")
            except Exception as e:
                self.after(0, self._set_indicator, "api", "fail")
                self._log_bg(f"  ✗ API access failed: {e}")
                return

            self.after(0, self._set_indicator, "data", "pending")
            try:
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                client.get_stats(yesterday)
                self.after(0, self._set_indicator, "data", "ok")
                self._log_bg("  ✓ Data access OK")
                self._connection_verified = True
                if on_success:
                    self.after(0, on_success)
            except Exception as e:
                self.after(0, self._set_indicator, "data", "fail")
                self._log_bg(f"  ✗ Data access failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_enc_key(self, mode="setup") -> str | None:
        import threading as _threading
        result   = [None]
        done_evt = _threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Encryption Key")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=BG)
            pad = {"padx": 20, "pady": 8}
            if mode == "setup":
                tk.Label(popup, text="Set Encryption Key",
                         font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(**pad)
                tk.Label(popup,
                         text="This key protects your saved login.\nStore it somewhere safe — e.g. your password manager.",
                         font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(**pad)
            else:
                tk.Label(popup, text="Encryption Key Required",
                         font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(**pad)
                tk.Label(popup,
                         text="Your encryption key was not found in Windows Credential Manager.\nPlease re-enter it — you will then be prompted to log in again.",
                         font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(**pad)
            tk.Label(popup, text="Key:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(anchor="w", padx=20)
            v_key = tk.StringVar()
            tk.Entry(popup, textvariable=v_key, show="*", font=FONT_BODY,
                     bg=BG3, fg=TEXT, insertbackground=TEXT, width=36).pack(padx=20, pady=(0, 8))
            v_confirm = None
            if mode == "setup":
                tk.Label(popup, text="Confirm Key:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(anchor="w", padx=20)
                v_confirm = tk.StringVar()
                tk.Entry(popup, textvariable=v_confirm, show="*", font=FONT_BODY,
                         bg=BG3, fg=TEXT, insertbackground=TEXT, width=36).pack(padx=20, pady=(0, 8))
            err_label = tk.Label(popup, text="", font=FONT_BODY, bg=BG, fg="#e94560")
            err_label.pack(padx=20)

            def _ok():
                key = v_key.get().strip()
                if not key:
                    err_label.config(text="Key cannot be empty.")
                    return
                if mode == "setup" and v_confirm is not None:
                    if key != v_confirm.get().strip():
                        err_label.config(text="Keys do not match.")
                        return
                result[0] = key
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="OK", font=FONT_BTN, bg=ACCENT, fg=TEXT,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_ok).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=FONT_BTN, bg=BG3, fg=TEXT2,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _prompt_token_expired(self) -> bool:
        import threading as _threading
        result   = [False]
        done_evt = _threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Token Expired")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=BG)
            tk.Label(popup, text="Saved Token Expired",
                     font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(padx=20, pady=(16, 8))
            tk.Label(popup,
                     text="A full SSO login is required to generate a new token.\nThis may trigger rate limiting or MFA on Garmin's side.\nProceed?",
                     font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(padx=20, pady=(0, 12))

            def _proceed():
                result[0] = True
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="Proceed", font=FONT_BTN, bg=ACCENT, fg=TEXT,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_proceed).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=FONT_BTN, bg=BG3, fg=TEXT2,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _prompt_mfa(self) -> str | None:
        import threading as _threading
        result   = [None]
        done_evt = _threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Two-Factor Authentication")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=BG)
            pad = {"padx": 20, "pady": 8}
            tk.Label(popup, text="MFA Code Required",
                     font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(**pad)
            tk.Label(popup,
                     text="Garmin requires a verification code.\nCheck your Garmin app or authenticator.",
                     font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(**pad)
            tk.Label(popup, text="Code:", font=FONT_BODY, bg=BG, fg=TEXT2).pack(anchor="w", padx=20)
            v_code = tk.StringVar()
            tk.Entry(popup, textvariable=v_code, font=FONT_BODY,
                     bg=BG3, fg=TEXT, insertbackground=TEXT, width=20).pack(padx=20, pady=(0, 8))
            err_label = tk.Label(popup, text="", font=FONT_BODY, bg=BG, fg="#e94560")
            err_label.pack(padx=20)

            def _ok():
                code = v_code.get().strip()
                if not code:
                    err_label.config(text="Code cannot be empty.")
                    return
                result[0] = code
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="OK", font=FONT_BTN, bg=ACCENT, fg=TEXT,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_ok).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=FONT_BTN, bg=BG3, fg=TEXT2,
                      relief="flat", bd=0, pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _reset_token(self):
        import garmin_security
        garmin_security.clear_token()
        self._set_indicator("token", "reset")
        self._connection_verified = False
        self._log("🔑  Token reset — next sync will require a new login.")

    def _clean_archive(self):
        import json as _json
        s = self._collect_settings()
        base_dir = Path(s["base_dir"]).expanduser() if s["base_dir"] else None
        if not base_dir:
            self._log("✗ Clean Archive: no data folder set.")
            return
        quality_log = base_dir / "garmin_data" / "log" / "quality_log.json"
        if not quality_log.exists():
            self._log("✗ Clean Archive: quality_log.json not found.")
            return
        try:
            data = _json.loads(quality_log.read_text(encoding="utf-8"))
        except Exception as e:
            self._log(f"✗ Clean Archive: could not read quality_log.json: {e}")
            return
        first_day_str = data.get("first_day")
        if not first_day_str:
            self._log("✗ Clean Archive: first_day not set in quality_log.json.")
            return
        try:
            cutoff = date.fromisoformat(first_day_str)
        except ValueError:
            self._log(f"✗ Clean Archive: invalid first_day value '{first_day_str}'.")
            return

        to_delete = []
        raw_dir     = base_dir / "garmin_data" / "raw"
        summary_dir = base_dir / "garmin_data" / "summary"
        for folder, pattern, prefix in [
            (raw_dir,     "garmin_raw_*.json", "garmin_raw_"),
            (summary_dir, "garmin_*.json",     "garmin_"),
        ]:
            if not folder.exists():
                continue
            for f in sorted(folder.glob(pattern)):
                try:
                    d = date.fromisoformat(f.stem.replace(prefix, ""))
                    if d < cutoff:
                        to_delete.append(f)
                except ValueError:
                    pass

        entries_to_remove = [
            e for e in data.get("days", [])
            if e.get("date", "9999") < first_day_str
        ]

        if not to_delete and not entries_to_remove:
            self._log(f"✓ Clean Archive: nothing to clean before {first_day_str}.")
            return

        popup = tk.Toplevel(self)
        popup.title("Clean Archive")
        popup.configure(bg=BG)
        popup.resizable(False, False)
        popup.grab_set()
        tk.Label(popup, text="🗑  Clean Archive",
                 font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT,
                 padx=20, pady=14).pack(anchor="w")
        tk.Frame(popup, bg=ACCENT, height=1).pack(fill="x", padx=20)
        info_frame = tk.Frame(popup, bg=BG, padx=20, pady=10)
        info_frame.pack(fill="x")
        tk.Label(info_frame, text=f"first_day:  {first_day_str}",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Label(info_frame, text="The following files will be permanently deleted:",
                 font=FONT_BODY, bg=BG, fg=TEXT2, pady=6).pack(anchor="w")
        list_frame = tk.Frame(popup, bg=BG, padx=20)
        list_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                             bg=BG3, fg=TEXT2, font=("Consolas", 8),
                             relief="flat", bd=0, height=12,
                             selectbackground=BG3, activestyle="none")
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)
        for f in to_delete:
            listbox.insert("end", f"  {f.relative_to(base_dir)}")
        summary_frame = tk.Frame(popup, bg=BG, padx=20, pady=8)
        summary_frame.pack(fill="x")
        tk.Label(summary_frame,
                 text=f"{len(to_delete)} file(s)  ·  {len(entries_to_remove)} quality log entry/entries",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(anchor="w")
        tk.Frame(popup, bg=ACCENT, height=1).pack(fill="x", padx=20)
        btn_frame = tk.Frame(popup, bg=BG, padx=20, pady=14)
        btn_frame.pack(fill="x")

        def do_delete():
            import garmin_quality as _quality
            stats = _quality.cleanup_before_first_day(data, dry_run=False)
            popup.destroy()
            self._log(f"✓ Clean Archive: {stats['files_deleted']} file(s) deleted, "
                      f"{stats['entries_removed']} log entry/entries removed.")

        tk.Button(btn_frame, text="Abbrechen", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=popup.destroy).pack(side="left")
        tk.Button(btn_frame, text="🗑  Löschen", font=FONT_BTN,
                  bg="#e94560", fg=TEXT, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=do_delete).pack(side="right")

    # ── Schema / failed days popups ────────────────────────────────────────────

    def _check_schema_migration(self, base_dir: str) -> bool:
        summary_dir = Path(base_dir) / "garmin_data" / "summary"
        if not summary_dir.exists():
            return False
        try:
            import garmin_normalizer as normalizer
            current_version = normalizer.CURRENT_SCHEMA_VERSION
        except Exception:
            return False
        outdated = 0
        for f in summary_dir.glob("garmin_*.json"):
            try:
                import json as _json
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("schema_version", 0) < current_version:
                    outdated += 1
            except Exception:
                continue
        if outdated == 0:
            return False
        answer = messagebox.askyesno(
            "Data Migration — Backup Required",
            f"A schema update requires rewriting {outdated} summary file(s).\n\n"
            f"Raw data files will NOT be modified.\n"
            f"Summary files will be regenerated from raw data.\n\n"
            f"Please make a backup of your data directory before continuing.\n\n"
            f"I have a backup — continue with migration?",
            icon="warning",
        )
        return answer

    def _check_failed_days_popup(self, base_dir: str, sync_mode: str,
                                  sync_days: str, sync_from: str, sync_to: str) -> bool:
        failed_file = Path(base_dir) / "garmin_data" / "log" / "quality_log.json"
        if not failed_file.exists():
            return False
        try:
            data    = json.loads(failed_file.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            if not entries:
                return False
            today     = date.today()
            yesterday = today - timedelta(days=1)
            try:
                if sync_mode == "recent":
                    start = today - timedelta(days=int(sync_days or 90))
                    end   = yesterday
                elif sync_mode == "range":
                    start = date.fromisoformat(sync_from) if sync_from else today - timedelta(days=90)
                    end   = date.fromisoformat(sync_to)   if sync_to   else yesterday
                else:
                    start = date.fromisoformat(entries[0]["date"]) if entries else today - timedelta(days=90)
                    end   = yesterday
            except (ValueError, KeyError):
                return False
            count = sum(
                1 for e in entries
                if e.get("quality", e.get("category", "")) in ("failed", "low")
                and start <= date.fromisoformat(e["date"]) <= end
            )
            if count == 0:
                return False
            answer = messagebox.askyesno(
                "Incomplete records found",
                f"There are incomplete records:\n\n"
                f"  {count} days in the selected range\n\n"
                f"Refresh now?",
                icon="warning",
            )
            return answer
        except Exception:
            return False

    # ── Sync actions ───────────────────────────────────────────────────────────

    def _run_collector(self):
        """Run connection test first (once per session), then start sync."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Email or password missing.")
            return

        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for manual sync.")
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        refresh_failed = self._check_failed_days_popup(
            base_dir  = s["base_dir"],
            sync_mode = s["sync_mode"],
            sync_days = s["sync_days"],
            sync_from = s.get("sync_from", ""),
            sync_to   = s.get("sync_to", ""),
        )
        run_migration = self._check_schema_migration(base_dir=s["base_dir"])
        env_extra = {"GARMIN_SCHEMA_MIGRATE": "1"} if run_migration else {}

        if self._connection_verified:
            self._run("garmin_collector.py", enable_stop=True,
                      refresh_failed=refresh_failed,
                      env_overrides=env_extra,
                      on_done=lambda: (
                          self._timer_resume_after_sync(timer_was_active),
                          self._refresh_archive_info(),
                      ))
            return

        self._run_connection_test(
            on_success=lambda: self._run(
                "garmin_collector.py", enable_stop=True,
                refresh_failed=refresh_failed,
                env_overrides=env_extra,
                on_done=lambda: (
                    self._timer_resume_after_sync(timer_was_active),
                    self._refresh_archive_info(),
                )))

    def _run_import(self):
        """Open file dialog and run bulk import."""
        choice = messagebox.askquestion(
            "Import Bulk Export",
            "Select ZIP file?\n\nYes = ZIP file\nNo = unpacked folder",
            icon="question",
        )
        if choice == "yes":
            path = filedialog.askopenfilename(
                title="Select Garmin Export ZIP",
                filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(title="Select unpacked Garmin Export folder")
        if not path:
            return

        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for import.")
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        self._log(f"   Source: {path}")
        self._run(
            "garmin_collector.py",
            enable_stop=True,
            log_prefix="garmin_bulk",
            env_overrides={"GARMIN_IMPORT_PATH": path},
            on_done=lambda: (
                self._timer_resume_after_sync(timer_was_active),
                self._refresh_archive_info(),
            ),
        )

    def _open_dashboard_popup(self):
        """Scan specialists, show selection popup, build selected dashboards."""
        import importlib.util as _ilu
        from pathlib import Path as _Path

        if not getattr(sys, "frozen", False):
            root = _Path(__file__).parent
        elif hasattr(sys, "_MEIPASS") and (_Path(sys._MEIPASS) / "scripts").exists():
            root = _Path(sys._MEIPASS) / "scripts"              # T3 Standalone
        else:
            root = _Path(sys.executable).parent / "scripts"     # T2 Standard EXE
        for p in (root / "dashboards", root / "layouts", root / "maps"):
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)

        try:
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            if spec is None:
                raise FileNotFoundError(f"dash_runner.py nicht gefunden: {runner_path}")
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)
        except Exception as exc:
            self._log(f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
            return

        try:
            specialists = dash_runner.scan()
        except Exception as exc:
            self._log(f"✗ scan() fehlgeschlagen: {exc}")
            return
        if not specialists:
            messagebox.showinfo("Create Reports", "No dashboards found in dashboards/")
            return

        popup = tk.Toplevel(self)
        popup.title("Create Reports")
        popup.configure(bg=BG)
        popup.resizable(False, False)
        popup.grab_set()

        tk.Label(popup, text="CREATE REPORTS", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=ACCENT).grid(row=0, column=0, columnspan=10,
                 sticky="w", padx=16, pady=(14, 4))
        tk.Frame(popup, bg=ACCENT, height=1).grid(row=1, column=0,
                 columnspan=10, sticky="ew", padx=16, pady=(0, 8))

        all_formats = []
        for s in specialists:
            for fmt in s["formats"]:
                if fmt not in all_formats:
                    all_formats.append(fmt)

        tk.Label(popup, text="Dashboard", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=TEXT, width=28, anchor="w").grid(
                 row=2, column=0, padx=(16, 4), pady=2)
        for col_idx, fmt in enumerate(all_formats, start=1):
            tk.Label(popup, text=dash_runner.display_label(fmt).upper(),
                     font=("Segoe UI", 8, "bold"), bg=BG, fg=TEXT,
                     width=7, anchor="center").grid(row=2, column=col_idx, padx=4, pady=2)

        check_vars = {}
        for row_idx, spec in enumerate(specialists, start=3):
            tk.Label(popup,
                     text=f"{spec['name']} — {spec['description'][:45]}",
                     font=("Segoe UI", 8), bg=BG, fg=TEXT,
                     width=46, anchor="w").grid(row=row_idx, column=0, padx=(16, 4), pady=3)
            for col_idx, fmt in enumerate(all_formats, start=1):
                if fmt in spec["formats"]:
                    var = tk.BooleanVar(value=False)
                    check_vars[(row_idx - 3, fmt)] = var
                    tk.Checkbutton(popup, variable=var, bg=BG,
                                   activebackground=BG,
                                   selectcolor="white").grid(row=row_idx, column=col_idx, padx=4)
                else:
                    tk.Label(popup, text="—", font=("Segoe UI", 8),
                             bg=BG, fg="#555555").grid(row=row_idx, column=col_idx, padx=4)

        last_row = 3 + len(specialists)
        tk.Frame(popup, bg=ACCENT, height=1).grid(row=last_row, column=0,
                 columnspan=10, sticky="ew", padx=16, pady=(8, 4))

        def _build():
            selections = []
            for (spec_idx, fmt), var in check_vars.items():
                if var.get():
                    selections.append((specialists[spec_idx]["module"], fmt))
            if not selections:
                messagebox.showinfo("Create Reports", "Please select at least one format.")
                return
            popup.destroy()
            self._run_dashboards(dash_runner, selections)

        btn_frame = tk.Frame(popup, bg=BG)
        btn_frame.grid(row=last_row + 1, column=0, columnspan=10,
                       pady=(4, 14), padx=16, sticky="ew")

        _all_selected = [False]

        def _toggle_all():
            _all_selected[0] = not _all_selected[0]
            for var in check_vars.values():
                var.set(_all_selected[0])
            toggle_btn.config(text="☑  Deselect All" if _all_selected[0] else "☐  Select All")

        toggle_btn = tk.Button(btn_frame, text="☐  Select All",
                               font=("Segoe UI", 8), bg=BG2, fg=TEXT2,
                               relief="flat", bd=0, padx=8, pady=6,
                               cursor="hand2", command=_toggle_all)
        toggle_btn.pack(side="left")

        tk.Button(btn_frame, text="Abbrechen", font=FONT_BTN,
                  bg=BG2, fg=TEXT, relief="flat", bd=0,
                  pady=6, padx=14, cursor="hand2",
                  command=popup.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btn_frame, text="📊 Create", font=FONT_BTN,
                  bg=ACCENT2, fg=TEXT, relief="flat", bd=0,
                  pady=6, padx=14, cursor="hand2",
                  command=_build).pack(side="right")

    def _run_dashboards(self, dash_runner, selections):
        """Run dashboard build in background thread, stream progress to log."""
        s         = self._collect_settings()
        date_from = s.get("date_from", "").strip()
        date_to   = s.get("date_to",   "").strip()
        if not date_from:
            date_from = (date.today() - timedelta(days=30)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()
        output_dir = Path(s["base_dir"]) / "dashboards"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"\n▶  Berichte erstellen ...")
        self._log(f"   Output: {output_dir}")
        self._log(f"   Zeitraum: {date_from} → {date_to}")

        def worker():
            try:
                import importlib
                os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
                import garmin_config as _cfg
                importlib.reload(_cfg)
                results = dash_runner.build(
                    selections=selections,
                    date_from=date_from,
                    date_to=date_to,
                    settings=s,
                    output_dir=output_dir,
                    log=lambda msg: self.after(0, lambda m=msg: self._log(f"   {m}")),
                )
                def on_done():
                    ok  = [r for r in results if r["success"]]
                    err = [r for r in results if not r["success"]]
                    self._log(f"\n  ✓ {len(ok)} Bericht(e) erstellt")
                    for r in err:
                        self._log(f"  ✗ {r['name']} ({r['format']}): {r.get('error', '')}")
                    if ok:
                        os.startfile(str(output_dir))
                self.after(0, on_done)
            except Exception as exc:
                self.after(0, lambda: self._log(f"  ✗ Fehler: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _open_data_folder(self):
        folder = Path(self._collect_settings()["base_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

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
        save_settings(self.settings)
        self._log(f"Context location set — lat {lat}, lon {lon}")

    def _run_context_sync(self):
        """Run context collect (weather + pollen) in background thread."""
        s = self._collect_settings()
        if float(s.get("context_latitude", "0.0")) == 0.0 and \
           float(s.get("context_longitude", "0.0")) == 0.0:
            messagebox.showwarning(
                "Location not configured",
                "Please set a location in Settings before running Context Sync.\n"
                "Use the Settings panel to enter coordinates."
            )
            return
        self._ctx_btn.config(state="disabled")
        self._ctx_stop_btn.config(state="normal")
        self._context_stop_event = threading.Event()

        def run():
            try:
                # script_dir() returns garmin/ in dev, scripts/garmin/ in EXE.
                # Parent gives the correct root for context/ package import.
                from garmin_app_base import _open_url as _  # noqa: ensure base imported
                if not getattr(sys, "frozen", False):
                    _root = Path(__file__).parent
                elif hasattr(sys, "_MEIPASS") and (Path(sys._MEIPASS) / "scripts").exists():
                    _root = Path(sys._MEIPASS) / "scripts"
                else:
                    _root = Path(sys.executable).parent / "scripts"
                if str(_root) not in sys.path:
                    sys.path.insert(0, str(_root))
                from context import context_collector
                result = context_collector.run(
                    settings=s,
                    stop_event=self._context_stop_event
                )
                plugins = result.get("plugins", {})
                lines = ["Context sync complete"]
                for name, stats in plugins.items():
                    lines.append(f"{name.capitalize():<10}{stats.get('written', 0)} written")
                msg = "\n".join(lines)
                if result.get("error"):
                    msg = f"Error: {result['error']}"
                self.after(0, lambda: self._log(msg))
            except Exception as exc:
                self.after(0, lambda: self._log(f"Context sync error: {exc}"))
            finally:
                self.after(0, self._on_context_sync_done)

        threading.Thread(target=run, daemon=True).start()

    def _stop_context_sync(self):
        if hasattr(self, "_context_stop_event"):
            self._context_stop_event.set()

    def _on_context_sync_done(self):
        self._ctx_btn.config(state="normal")
        self._ctx_stop_btn.config(state="disabled")

    def _open_local_config(self):
        """Open local_config.csv in default editor. Create if missing."""
        import garmin_config as cfg
        csv_path = cfg.LOCAL_CONFIG_FILE
        if not csv_path.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "date_from;date_to;country;place;latitude;longitude\n",
                encoding="utf-8"
            )
            readme_path = csv_path.parent / "local_config_README.txt"
            if not readme_path.exists():
                readme_path.write_text(
                    "Garmin Local Archive — Location Config\n"
                    "======================================\n\n"
                    "Edit local_config.csv to define your location per time period.\n\n"
                    "Columns:\n"
                    "  date_from   : YYYY-MM-DD — start of period\n"
                    "  date_to     : YYYY-MM-DD — end of period\n"
                    "  country     : English name (e.g. Germany, Spain, France)\n"
                    "  place       : City or town name (e.g. Herford, Palma de Mallorca)\n"
                    "  latitude    : Filled automatically — leave empty\n"
                    "  longitude   : Filled automatically — leave empty\n\n"
                    "Example row:\n"
                    "  2025-07-14,2025-07-21,Spain,Palma de Mallorca,,\n\n"
                    "Leave latitude and longitude empty.\n"
                    "The app fills them automatically on next Context Sync.\n"
                    "If no entry matches a date, the app uses the location from Settings.\n",
                    encoding="utf-8"
                )
        os.startfile(csv_path)

    def _open_last_html(self):
        html = self._last_html
        if not html or not Path(html).exists():
            base  = Path(self._collect_settings()["base_dir"])
            files = list(base.glob("*.html"))
            if not files:
                self._log("✗ No HTML files found in data folder.")
                return
            html = str(max(files, key=lambda f: f.stat().st_mtime))
        os.startfile(html)

    def _copy_last_error_log(self):
        fail_dir = Path(self._collect_settings()["base_dir"]) / "garmin_data" / "log" / "fail"
        if not fail_dir.exists():
            self._log("✗ No error logs found (log/fail/ does not exist).")
            return
        logs = sorted(fail_dir.glob("garmin_*.log"), key=lambda f: f.stat().st_mtime)
        if not logs:
            self._log("✓ No error logs — no failed sessions recorded.")
            return
        latest = logs[-1]
        try:
            content = latest.read_text(encoding="utf-8")
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()
            self._log(f"✓ Error log copied to clipboard ({latest.name})")
        except Exception as e:
            self._log(f"✗ Could not read error log: {e}")

    # ── Background Timer ───────────────────────────────────────────────────────

    def _timer_update_btn(self):
        if not self._timer_btn:
            return
        if self._timer_active:
            self._timer_btn.config(bg=GREEN, fg="#0a0a1a")
        else:
            self._timer_btn.config(text="⏱  Timer: Off", bg=BG3, fg=TEXT2)

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
            self._timer_active = True
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
            self._timer_active = True
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

            # Bulk recheck has priority
            bulk_days = self._timer_run_bulk_recheck(s)
            if bulk_days is not None:
                days    = bulk_days
                mode    = "bulk"
                skipped = False
            else:
                _mode_cycle = ["repair", "quality", "fill"]
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

            n_days = random.randint(min_days, max_days)
            if mode == "bulk":
                days_pick = days[:n_days]
            else:
                days_pick = sorted(random.sample(days, min(n_days, len(days))))
            sync_dates_str = ",".join(d.isoformat() for d in days_pick)
            days_left      = len(days_pick)
            queue_total    = len(days)

            label = {"repair": "Repair", "quality": "Quality",
                     "fill": "Fill", "bulk": "Bulk Recheck"}.get(mode, mode)
            self.after(0, self._log,
                f"⏱  [{label}] Syncing {days_left} days ({queue_total} in queue)")

            # Wait for any running sync to finish
            while self._is_running():
                if _stale():
                    return
                self._timer_stop.wait(timeout=0.5)

            refresh = (mode in ("repair", "quality", "bulk"))
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
        """Returns list of date objects with quality='failed'. None if empty."""
        try:
            failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
            if not failed_file.exists():
                return None
            data    = json.loads(failed_file.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            days = []
            for e in entries:
                q = e.get("quality", e.get("category", ""))
                if q == "failed" and e.get("recheck", True):
                    try:
                        days.append(date.fromisoformat(e["date"]))
                    except (ValueError, KeyError):
                        pass
            return days if days else None
        except Exception:
            return None

    def _timer_run_bulk_recheck(self, s: dict):
        """Returns bulk-source days within last 180 days, oldest first. None if empty."""
        try:
            log_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
            if not log_file.exists():
                return None
            data   = json.loads(log_file.read_text(encoding="utf-8"))
            cutoff = date.today() - timedelta(days=180)
            days = []
            for e in data.get("days", []):
                if e.get("source") == "bulk" and e.get("recheck", False):
                    try:
                        d = date.fromisoformat(e["date"])
                        if d >= cutoff:
                            days.append(d)
                    except (ValueError, KeyError):
                        pass
            days.sort()
            return days if days else None
        except Exception:
            return None

    def _timer_run_quality(self, s: dict):
        """Returns list of date objects with quality='low'. None if empty."""
        try:
            failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
            if not failed_file.exists():
                return None
            data    = json.loads(failed_file.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            days = []
            for e in entries:
                q = e.get("quality", e.get("category", ""))
                if q == "low" and e.get("recheck", True):
                    try:
                        days.append(date.fromisoformat(e["date"]))
                    except (ValueError, KeyError):
                        pass
            return days if days else None
        except Exception:
            return None

    def _timer_run_fill(self, s: dict):
        """Returns dates completely absent from raw/ between earliest known and yesterday."""
        try:
            raw_dir = Path(s["base_dir"]) / "garmin_data" / "raw"
            existing = set()
            if raw_dir.exists():
                for f in raw_dir.glob("garmin_raw_*.json"):
                    try:
                        existing.add(date.fromisoformat(f.stem.replace("garmin_raw_", "")))
                    except ValueError:
                        pass
            failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
            failed_dates = set()
            if failed_file.exists():
                try:
                    data = json.loads(failed_file.read_text(encoding="utf-8"))
                    for e in data.get("days", []):
                        try:
                            failed_dates.add(date.fromisoformat(e["date"]))
                        except (ValueError, KeyError):
                            pass
                except Exception:
                    pass
            all_known = existing | failed_dates
            if not all_known:
                return None
            yesterday = date.today() - timedelta(days=1)
            earliest  = min(all_known)
            missing = []
            current = earliest
            while current <= yesterday:
                if current not in existing and current not in failed_dates:
                    missing.append(current)
                current += timedelta(days=1)
            return missing if missing else None
        except Exception:
            return None

    # ── Close ──────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._timer_generation += 1
        self._timer_stop.set()
        if hasattr(self, "_context_stop_event"):
            self._context_stop_event.set()
        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        save_settings(self.settings)
        self.destroy()
