#!/usr/bin/env python3
"""
garmin_app_standalone.py
Garmin Local Archive — Desktop GUI (Standalone Entry Point)

Target 3: no Python installation required on the target machine.

Differences from garmin_app.py:
  - script_dir()   → sys._MEIPASS/scripts/ (embedded data unpacked by PyInstaller)
  - _run_module()  → replaces _run_script() — no subprocess, scripts are imported
                     directly as modules and run in threads. stdout/stderr/logging
                     are redirected to the GUI log via a queue.
  - _stop_collector() → sets a threading.Event instead of killing a process

Built by: build_standalone.py
"""

import importlib.util
import io
import json
import logging
import os
import queue
import re
import sys
import threading
import traceback
from pathlib import Path
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox

# ── Settings file ──────────────────────────────────────────────────────────────
SETTINGS_FILE = Path.home() / ".garmin_archive_settings.json"

DEFAULT_SETTINGS = {
    "email":              "",
    "base_dir":           str(Path.home() / "garmin_data"),
    "sync_mode":          "recent",
    "sync_days":          "90",
    "sync_from":          "",
    "sync_to":            "",
    "date_from":          "",
    "date_to":            "",
    "age":                "35",
    "sex":                "male",
    "request_delay_min": "5.0",
    "request_delay_max": "20.0",
    "timer_min_interval": "5",
    "timer_max_interval": "30",
    "timer_min_days":     "3",
    "timer_max_days":     "10",
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
    SETTINGS_FILE.write_text(json.dumps(safe, indent=2))


# ── Keyring helpers ────────────────────────────────────────────────────────────
KEYRING_SERVICE = "GarminLocalArchive"
KEYRING_USER    = "garmin_password"

def load_password() -> str:
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        return pw or ""
    except Exception:
        return ""

def save_password(pw: str):
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
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


# ── Script paths ───────────────────────────────────────────────────────────────
def script_dir() -> Path:
    """
    Standalone: PyInstaller unpacks --add-data to sys._MEIPASS.
    Scripts land in sys._MEIPASS/scripts/.
    Dev fallback: folder of this file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "scripts"
    return Path(__file__).parent

def script_path(name: str) -> Path:
    return script_dir() / name

def _open_url(url: str):
    try:
        import webbrowser
        if not webbrowser.open(url):
            os.startfile(url)
    except Exception:
        try:
            os.startfile(url)
        except Exception:
            pass


# ── Queue-based output capture ─────────────────────────────────────────────────

class _QueueWriter(io.TextIOBase):
    """Redirects write() calls into a queue for the GUI log."""
    def __init__(self, q: queue.Queue):
        self._q   = q
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(line)
        return len(text)

    def flush(self):
        if self._buf:
            self._q.put(self._buf)
            self._buf = ""


class _QueueHandler(logging.Handler):
    """Redirects logging records into a queue for the GUI log."""
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record):
        self._q.put(self.format(record))


# ── Colors & fonts ─────────────────────────────────────────────────────────────
APP_VERSION = "v1.3.4"

BG        = "#1a1a2e"
BG2       = "#16213e"
BG3       = "#0f3460"
ACCENT    = "#e94560"
ACCENT2   = "#533483"
TEXT      = "#eaeaea"
TEXT2     = "#a0a0b0"
GREEN     = "#4ecca3"
YELLOW    = "#f5a623"
FONT_HEAD = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 9)
FONT_BTN  = ("Segoe UI", 9, "bold")
FONT_LOG  = ("Consolas", 8)


# ── Main application ───────────────────────────────────────────────────────────
class GarminApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings    = load_settings()
        self.title("Garmin Local Archive")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(920, 950)
        self.geometry("1100x980")
        self._stop_event          = threading.Event()
        self._running             = False
        self._stop_btn            = None
        self._last_html           = None
        self._log_queue           = queue.Queue()
        self._connection_verified = False
        self._timer_conn_verified = False
        self._timer_active        = False
        self._timer_stop          = threading.Event()
        self._timer_btn           = None
        self._timer_next_mode     = "repair"  # cycles: "repair" | "quality" | "fill"
        self._timer_generation    = 0
        self._build_ui()
        self._load_settings_to_ui()
        self.v_sync_mode.set("recent")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._check_version, daemon=True).start()
        self._poll_log_queue()                # start queue → log pump

    # ── Queue → log pump ───────────────────────────────────────────────────────

    def _poll_log_queue(self):
        """Drain the log queue every 50 ms and write lines to the GUI log."""
        _day_pat = re.compile(r"\[(\d+)/(\d+)\]")
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._log(line)
                # Update timer button countdown from [X/Y] log lines
                if self._timer_active and self._timer_btn:
                    m = _day_pat.search(line)
                    if m:
                        current   = int(m.group(1))
                        total     = int(m.group(2))
                        remaining = total - current + 1
                        self._timer_btn.config(text=f"⏱  Syncing · {remaining}/{total}")
        except queue.Empty:
            pass
        self.after(50, self._poll_log_queue)

    # ── UI builder ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        header = tk.Frame(self, bg=BG3, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="⌚  GARMIN LOCAL ARCHIVE",
                 font=("Segoe UI", 13, "bold"), bg=BG3, fg=TEXT).pack(side="left", padx=20)
        tk.Label(header, text=APP_VERSION,
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT2).pack(side="left", padx=(0, 8))
        tk.Label(header, text="local · private · yours · StandAlone",
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT).pack(side="left", padx=4)
        tk.Label(header, text="GNU GPL v3",
                 font=("Segoe UI", 8), bg=BG3, fg=TEXT2).pack(side="right", padx=8)
        link = tk.Label(header, text="www.github.com/Wewoc/Garmin_Local_Archive",
                 font=("Segoe UI", 8, "underline"), bg=BG3, fg="#6ab0f5", cursor="hand2")
        link.pack(side="right", padx=4)
        link.bind("<Button-1>",
                  lambda e: _open_url("https://www.github.com/Wewoc/Garmin_Local_Archive"))

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)
        left = tk.Frame(main, bg=BG2, width=300)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._build_settings_panel(left)
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_actions_panel(right)
        self.after(200, self._refresh_archive_info)

        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(fill="both", expand=False)
        self._build_log(log_frame)

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
                 insertbackground=TEXT, relief="flat", bd=4,
                 width=18).pack(side="left", padx=(2, 2))
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
                     state="readonly", width=10,
                     font=FONT_BODY)
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
                 font=("Segoe UI", 7), bg=BG2, fg=YELLOW, anchor="w", wraplength=240, justify="left"
                 ).pack(anchor="w", padx=16, pady=(2, 4))

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
        # Note: not packed initially — shown via pack/pack_forget in _toggle_log_level
        self._log_level_btn = tk.Button(
            log_frame, text="📋  Log: Simple", font=FONT_BTN,
            bg=BG3, fg=TEXT2, relief="flat", bd=0, pady=6, padx=12,
            cursor="hand2", command=self._toggle_log_level)
        self._log_level_btn.pack(fill="x")

    def _build_actions_panel(self, parent):
        tk.Label(parent, text="Actions", font=FONT_HEAD,
                 bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14, 0))

        # ── Connection test ────────────────────────────────────────────────────
        fc = tk.Frame(parent, bg=BG, pady=4)
        fc.pack(fill="x", padx=20, pady=2)
        tk.Label(fc, text="CONNECTION & ARCHIVE STATUS", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(fc, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        conn_row = tk.Frame(fc, bg=BG)
        conn_row.pack(fill="x", pady=2)

        # Status indicators
        self._conn_indicators = {}
        ind_frame = tk.Frame(conn_row, bg=BG)
        ind_frame.pack(side="left", padx=(0, 0))
        for key, label in [("token", "Token"), ("login", "Login"), ("api", "API Access"), ("data", "Data")]:
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
        for q, label in [("high", "high"), ("medium", "med"), ("low", "low"), ("failed", "fail")]:
            cell = tk.Frame(row1, bg=BG)
            cell.pack(side="left", padx=(0, 10))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 9),
                           bg=BG, fg=_QCOLORS[q])
            dot.pack(side="left")
            lbl = tk.Label(cell, text=f"{label} —", font=("Segoe UI", 8),
                           bg=BG, fg=TEXT2)
            lbl.pack(side="left", padx=(2, 0))
            self._info_qdots[q] = lbl

        self._info_recheck = tk.Label(row1, text="Recheck: —", font=("Segoe UI", 8),
                                      bg=BG, fg=TEXT2)
        self._info_recheck.pack(side="left", padx=(10, 0))

        row2 = tk.Frame(info_frame, bg=BG)
        row2.pack(fill="x", pady=(3, 0))

        self._info_range = tk.Label(row2, text="Range: —", font=("Segoe UI", 8),
                                    bg=BG, fg=TEXT2)
        self._info_range.pack(side="left", padx=(0, 14))

        self._info_coverage = tk.Label(row2, text="Coverage: —", font=("Segoe UI", 8),
                                       bg=BG, fg=TEXT2)
        self._info_coverage.pack(side="left", padx=(0, 14))

        self._info_last_api = tk.Label(row2, text="Last API: —", font=("Segoe UI", 8),
                                       bg=BG, fg=TEXT2)
        self._info_last_api.pack(side="left", padx=(0, 14))

        self._info_last_bulk = tk.Label(row2, text="Last Bulk: —", font=("Segoe UI", 8),
                                        bg=BG, fg=TEXT2)
        self._info_last_bulk.pack(side="left")

        f = tk.Frame(parent, bg=BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text="DATA COLLECTION", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Button(row, text="▶  Sync Data", font=FONT_BTN,
                  bg=ACCENT, fg=TEXT, relief="flat", bd=0,
                  pady=7, padx=14, anchor="w", cursor="hand2",
                  command=self._run_collector).pack(side="left", fill="x", expand=True)
        self._stop_btn = tk.Button(row, text="⏹  Stop", font=FONT_BTN,
                                   bg=BG3, fg=TEXT2, relief="flat", bd=0,
                                   pady=7, padx=14, cursor="hand2",
                                   state="disabled",
                                   command=self._stop_collector)
        self._stop_btn.pack(side="left", padx=(4, 0))
        tk.Label(row, text="Fetch missing days from Garmin Connect",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(side="left", padx=10)

        # Import row
        imp_row = tk.Frame(f, bg=BG)
        imp_row.pack(fill="x", pady=2)
        tk.Button(imp_row, text="📥  Import Bulk Export", font=FONT_BTN,
                  bg=BG3, fg=TEXT, relief="flat", bd=0,
                  pady=7, padx=14, anchor="w", cursor="hand2",
                  command=self._run_import).pack(side="left", fill="x", expand=True)
        tk.Label(imp_row, text="Import Garmin GDPR export ZIP or folder (recommended for history)",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(side="left", padx=10)

        # Export link row
        _EXPORT_URL = "https://www.garmin.com/en-US/account/datamanagement/exportdata/"
        imp_link_row = tk.Frame(f, bg=BG)
        imp_link_row.pack(fill="x", pady=(0, 2))
        imp_link = tk.Label(imp_link_row, text="→ Request export at garmin.com",
                            font=("Segoe UI", 8), bg=BG, fg=ACCENT, cursor="hand2")
        imp_link.pack(side="left", padx=14)
        imp_link.bind("<Button-1>", lambda e: _open_url(_EXPORT_URL))
        _exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
        _readme_candidates = [
            _exe_dir / "info" / "README_APP_Standalone.md",
            Path(__file__).parent / "README_APP_Standalone.md",
        ]
        _readme = next((p for p in _readme_candidates if p.exists()), None)
        readme_link = tk.Label(imp_link_row, text="→ Open README",
                               font=("Segoe UI", 8), bg=BG, fg=ACCENT, cursor="hand2")
        readme_link.pack(side="left", padx=14)
        readme_link.bind("<Button-1>", lambda e: os.startfile(_readme) if _readme else None)

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
                     ).grid(row=row, column=col*2, sticky="e", padx=(8, 2), pady=1)
            tk.Entry(parent, textvariable=var, font=FONT_BODY,
                     bg=BG3, fg=TEXT, insertbackground=TEXT,
                     relief="flat", bd=4, width=4
                     ).grid(row=row, column=col*2+1, sticky="w", padx=(0, 4), pady=1)

        _timer_field(fields_frame, "Min. Interval (min)", self.v_timer_min_interval, 0, 0)
        _timer_field(fields_frame, "Max. Interval (min)", self.v_timer_max_interval, 1, 0)
        _timer_field(fields_frame, "Min. Days per Run",   self.v_timer_min_days,     0, 1)
        _timer_field(fields_frame, "Max. Days per Run",   self.v_timer_max_days,     1, 1)

        self._action_section(parent, "Export", [
            ("📊  Daily Overview",       BG3,     self._run_excel_overview,
             "Summary spreadsheet — one row per day"),
            ("📈  Timeseries Excel",     BG3,     self._run_excel_timeseries,
             "Intraday data + charts per metric"),
            ("🌐  Timeseries Dashboard", BG3,     self._run_html_timeseries,
             "Interactive browser dashboard"),
            ("🔍  Analysis Dashboard",   ACCENT2, self._run_html_analysis,
             "Values vs baseline vs reference ranges + JSON for Ollama"),
        ])
        self._action_section(parent, "Output", [
            ("📁  Open Data Folder", BG3, self._open_data_folder,
             "Open garmin_data/ in Explorer"),
            ("📄  Open Last HTML",   BG3, self._open_last_html,
             "Open the last generated HTML file in browser"),
            ("📋  Copy Last Error Log", BG3, self._copy_last_error_log,
             "Copy most recent error log to clipboard"),
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
            tk.Button(row, text=label, font=FONT_BTN,
                      bg=color, fg=TEXT, relief="flat", bd=0,
                      pady=7, padx=14, anchor="w", cursor="hand2",
                      command=cmd).pack(side="left", fill="x", expand=True)
            tk.Label(row, text=tooltip, font=("Segoe UI", 8),
                     bg=BG, fg=TEXT2).pack(side="left", padx=10)

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
            relief="flat", bd=0, wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True)

    # ── Version check ──────────────────────────────────────────────────────────

    def _check_version(self):
        """Background thread: compares APP_VERSION against latest GitHub release.
        Shows update popup if a newer version is available. Silent on error or no update.
        """
        import urllib.request
        import json
        url = "https://api.github.com/repos/Wewoc/Garmin_Local_Archive/releases/latest"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GarminLocalArchive"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            latest = data.get("tag_name", "").strip()
            if latest and latest.lstrip("vV") != APP_VERSION.lstrip("vV"):
                self.after(0, self._show_update_popup, latest)
        except Exception:
            pass  # no internet, timeout, API error — all silent

    def _show_update_popup(self, latest: str):
        """Non-blocking popup informing the user that a new version is available."""
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
        self.v_base_dir.set(s.get("base_dir", "C:\\garmin"))
        self.v_sync_mode.set(s.get("sync_mode", "recent"))
        self.v_sync_days.set(s.get("sync_days", "90"))
        self.v_sync_from.set(s.get("sync_from", ""))
        self.v_sync_to.set(s.get("sync_to", ""))
        self.v_sync_fallback.set(s.get("sync_auto_fallback", ""))
        self.v_date_from.set(s.get("date_from", ""))
        self.v_date_to.set(s.get("date_to", ""))
        self.v_age.set(s.get("age", "35"))
        self.v_sex.set(s.get("sex", "male"))
        self.v_delay_min.set(s.get("request_delay_min", "1.0"))
        self.v_delay_max.set(s.get("request_delay_max", "3.0"))
        self.v_timer_min_interval.set(s.get("timer_min_interval", "5"))
        self.v_timer_max_interval.set(s.get("timer_max_interval", "30"))
        self.v_timer_min_days.set(s.get("timer_min_days", "3"))
        self.v_timer_max_days.set(s.get("timer_max_days", "10"))
        self._on_sync_mode_change()

    def _on_sync_mode_change(self):
        """Dim/enable sync fields based on selected mode."""
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
        }

    def _toggle_log_level(self):
        if self._log_level == "INFO":
            self._log_level = "DEBUG"
            self._log_level_btn.config(text="📋  Log: Detailed", fg=YELLOW)
        else:
            self._log_level = "INFO"
            self._log_level_btn.config(text="📋  Log: Simple", fg=TEXT2)

        # Show hint if sync is currently running
        if self._running:
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

    # ── Stop ───────────────────────────────────────────────────────────────────

    def _stop_collector(self):
        """Signal the running module thread to stop at its next opportunity."""
        if self._running:
            self._stop_event.set()
            self._log("⏹  Stop requested — waiting for current operation ...")

    # ── Failed days popup ──────────────────────────────────────────────────────

    def _check_failed_days_popup(self, base_dir: str, sync_mode: str,
                                  sync_days: str, sync_from: str, sync_to: str) -> bool:
        """
        Reads log/quality_log.json and counts entries within the current sync range.
        If any found: shows a popup asking whether to re-fetch them.
        Returns True if sync should treat incomplete days as missing (re-fetch),
        Returns False if sync should skip them (normal behaviour).
        If no failed days in range: returns False silently.
        """
        failed_file = Path(base_dir) / "log" / "quality_log.json"
        if not failed_file.exists():
            return False

        try:
            data    = json.loads(failed_file.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            if not entries:
                return False

            # Determine sync date range for counting
            today     = date.today()
            yesterday = today - timedelta(days=1)
            try:
                if sync_mode == "recent":
                    start = today - timedelta(days=int(sync_days or 90))
                    end   = yesterday
                elif sync_mode == "range":
                    start = date.fromisoformat(sync_from) if sync_from else today - timedelta(days=90)
                    end   = date.fromisoformat(sync_to)   if sync_to   else yesterday
                else:  # auto
                    start = date.fromisoformat(entries[0]["date"]) if entries else today - timedelta(days=90)
                    end   = yesterday
            except (ValueError, KeyError):
                return False

            # Count failed/low quality days within range
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

    # ── Module runner ──────────────────────────────────────────────────────────

    def _apply_env(self, s: dict, refresh_failed: bool = False):
        """
        Write GARMIN_* settings into os.environ.
        Must run before the module is imported — scripts read os.environ.get()
        at module level when they are loaded.
        """
        base = Path(s["base_dir"])
        os.environ["PYTHONUTF8"]             = "1"
        os.environ["GARMIN_EMAIL"]           = s["email"]
        os.environ["GARMIN_PASSWORD"]        = s["password"]
        os.environ["GARMIN_OUTPUT_DIR"]      = str(base)
        os.environ["GARMIN_EXPORT_FILE"]     = str(base / "garmin_export.xlsx")
        os.environ["GARMIN_TIMESERIES_FILE"] = str(base / "garmin_timeseries.xlsx")
        os.environ["GARMIN_DASHBOARD_FILE"]  = str(base / "garmin_dashboard.html")
        os.environ["GARMIN_ANALYSIS_HTML"]   = str(base / "garmin_analysis.html")
        os.environ["GARMIN_ANALYSIS_JSON"]   = str(base / "garmin_analysis.json")
        os.environ["GARMIN_SYNC_MODE"]       = s["sync_mode"]
        os.environ["GARMIN_DAYS_BACK"]       = s["sync_days"] or "90"
        os.environ["GARMIN_SYNC_START"]      = s.get("sync_from", "")
        os.environ["GARMIN_SYNC_END"]        = s.get("sync_to", "")
        os.environ["GARMIN_SYNC_FALLBACK"]   = s.get("sync_auto_fallback", "")
        os.environ["GARMIN_REQUEST_DELAY_MIN"] = s["request_delay_min"]
        os.environ["GARMIN_REQUEST_DELAY_MAX"] = s["request_delay_max"]
        os.environ["GARMIN_REFRESH_FAILED"]  = "1" if refresh_failed else "0"
        _today  = date.today()
        _d_from = s.get("date_from", "").strip()
        _d_to   = s.get("date_to",   "").strip()

        if not _d_from or not _d_to:
            _summary_dir = Path(s.get("base_dir", "")) / "summary"
            _dates = sorted(
                f.stem.replace("garmin_", "")
                for f in _summary_dir.glob("garmin_???-??-??.json")
            ) if _summary_dir.exists() else []

        os.environ["GARMIN_DATE_FROM"] = _d_from or (
            _dates[0] if _dates else (_today - timedelta(days=90)).isoformat()
        )
        os.environ["GARMIN_DATE_TO"] = _d_to or (
            _dates[-1] if _dates else _today.isoformat()
        )
        os.environ["GARMIN_PROFILE_AGE"]          = s.get("age", "35")
        os.environ["GARMIN_PROFILE_SEX"]          = s.get("sex", "male")
        os.environ["GARMIN_LOG_LEVEL"]            = getattr(self, "_log_level", "INFO")
        os.environ["GARMIN_SESSION_LOG_PREFIX"]   = "garmin"
        os.environ["GARMIN_SYNC_DATES"]           = ""  # cleared by default; timer sets this

    def _apply_env_overrides(self, overrides: dict):
        """Apply a dict of ENV overrides on top of what _apply_env() set."""
        for k, v in overrides.items():
            os.environ[k] = v

    def _run_module(self, script_name: str, enable_stop: bool = False,
                    on_success: callable = None, refresh_failed: bool = False,
                    on_done: callable = None, log_prefix: str = "garmin",
                    env_overrides: dict = None, stop_event: threading.Event = None,
                    days_left: int = None):
        """
        Load a script as a module and call its main() in a background thread.

        stdout, stderr, and the root logger are redirected to _log_queue so
        all script output appears in the GUI log. Original streams are restored
        after the module finishes.

        enable_stop:   activates the Stop button; _stop_event is set by
                       _stop_collector() and checked by the collector via
                       the monkey-patched _STOP_EVENT module attribute.
        on_success:    called on the main thread after a clean exit.
        on_done:       called on the main thread after any exit (success or fail).
        log_prefix:    passed as GARMIN_SESSION_LOG_PREFIX.
        env_overrides: optional dict applied on top of _apply_env() output.
        stop_event:    optional Event — if set mid-run, signals the module to stop
                       via _STOP_EVENT (same mechanism as enable_stop).
        days_left:     shown in timer button while sync runs.
        """
        path = script_path(script_name)
        if not path.exists():
            self._log(f"✗ Script not found: {path}")
            return

        if self._running:
            self._log("✗ Another operation is already running — please wait.")
            return

        s = self._collect_settings()
        self._log(f"\n▶  Running {script_name} ...")
        self._log(f"   Data: {s['base_dir']}")
        self._log_level_hint.pack_forget()

        def worker():
            self._running = True
            self._stop_event.clear()

            if enable_stop:
                self.after(0, lambda: self._stop_btn.config(
                    state="normal", bg=ACCENT, fg=TEXT))

            # Show "Syncing · N offen" in timer button while download runs
            if days_left is not None and self._timer_btn:
                self.after(0, lambda dl=days_left: self._timer_btn and
                    self._timer_btn.config(text=f"⏱  Syncing · {dl}/{dl}"))

            # ── Redirect output to the GUI log queue ──
            q          = self._log_queue
            q_writer   = _QueueWriter(q)
            q_handler  = _QueueHandler(q)
            q_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            old_stdout   = sys.stdout
            old_stderr   = sys.stderr
            root_logger  = logging.getLogger()
            old_handlers = root_logger.handlers[:]
            old_level    = root_logger.level

            sys.stdout = q_writer
            sys.stderr = q_writer
            root_logger.handlers = [q_handler]
            root_logger.setLevel(getattr(logging, self._log_level, logging.INFO))

            success = False
            try:
                # Apply ENV before loading — module-level os.environ.get() calls
                # pick up the values at import time.
                self._apply_env(s, refresh_failed=refresh_failed)
                os.environ["GARMIN_SESSION_LOG_PREFIX"] = log_prefix
                if env_overrides:
                    self._apply_env_overrides(env_overrides)

                # Load fresh each run (force re-exec of module-level code)
                spec   = importlib.util.spec_from_file_location(
                    script_name.replace(".py", ""), path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Expose stop event to collector and api module so they can exit cleanly.
                # Timer sync uses _timer_stop via stop_event parameter.
                effective_stop = stop_event if stop_event is not None else (
                    self._stop_event if enable_stop else None
                )
                if effective_stop is not None:
                    module.__dict__["_STOP_EVENT"] = effective_stop
                    # Also inject into garmin_api if it was imported by the module
                    _garmin_api = module.__dict__.get("garmin_api") or \
                        sys.modules.get("garmin_api")
                    if _garmin_api is not None:
                        _garmin_api.__dict__["_STOP_EVENT"] = effective_stop

                module.main()
                success = not (effective_stop is not None and effective_stop.is_set())

            except SystemExit as e:
                success = e.code in (None, 0)
                if not success and not (stop_event is not None and stop_event.is_set()):
                    q.put(f"✗ Script exited with code {e.code}")
            except Exception as e:
                q.put(f"✗ Error in {script_name}: {e}")
                q.put(traceback.format_exc())
            finally:
                q_writer.flush()
                sys.stdout        = old_stdout
                sys.stderr        = old_stderr
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)

                self._running = False
                if enable_stop and self._stop_btn:
                    self.after(0, lambda: self._stop_btn.config(
                        state="disabled", bg=BG3, fg=TEXT2))

                stopped = (stop_event is not None and stop_event.is_set()) or \
                          self._stop_event.is_set()
                if stopped:
                    q.put("✗ Stopped by user.")
                elif success:
                    q.put("✓ Done.")
                    if on_success:
                        self.after(0, on_success)

                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    # ── Actions ────────────────────────────────────────────────────────────────

    def _set_indicator(self, key: str, state: str):
        """Set a connection indicator: 'pending' | 'ok' | 'fail' | 'reset'."""
        colors = {"pending": "#f5a623", "ok": "#4ecca3", "fail": "#e94560", "reset": TEXT2}
        self._conn_indicators[key].config(fg=colors.get(state, TEXT2))

    def _refresh_archive_info(self):
        """Reads quality_log.json and updates the Archive Info Panel labels."""
        try:
            import garmin_quality as quality
            from pathlib import Path
            s = self._collect_settings()
            base_dir = Path(s.get("base_dir") or "~/garmin_data").expanduser()
            quality_log = base_dir / "log" / "quality_log.json"
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
        """Test Token → Login → API Access → Data in a background thread.
        Token check runs first — if token is valid, Login lamp turns green without SSO.
        Only called internally (Sync / Background Timer), not triggered by button click.
        on_success: optional callable, invoked on the main thread when all checks pass.
        """
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Connection test: email or password missing.")
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._log("\n🔌  Testing connection ...")

        def worker():
            import garmin_security
            import garmin_config as cfg

            try:
                from garminconnect import Garmin
            except ImportError:
                self._log_queue.put("✗ garminconnect not installed.")
                return

            # 0 — Token check
            token_file_exists = cfg.GARMIN_TOKEN_FILE.exists()
            enc_key_present   = garmin_security.get_enc_key() is not None

            if not token_file_exists:
                self.after(0, self._set_indicator, "token", "reset")
            elif token_file_exists and not enc_key_present:
                self.after(0, self._set_indicator, "token", "fail")
                self._log_queue.put("  ⚠ Encryption key missing — re-entry required")
            else:
                self.after(0, self._set_indicator, "token", "pending")

            # 1 — Login (via garmin_api, which handles token internally)
            self.after(0, self._set_indicator, "login", "pending")
            try:
                import garmin_api
                client = garmin_api.login(
                    on_key_required  = self._prompt_enc_key,
                    on_token_expired = self._prompt_token_expired,
                    on_mfa_required  = self._prompt_mfa,
                )
                token_used = token_file_exists and enc_key_present
                self.after(0, self._set_indicator, "token", "ok" if token_used else "reset")
                self.after(0, self._set_indicator, "login", "ok")
                self._log_queue.put("  ✓ Login successful")
            except SystemExit:
                self.after(0, self._set_indicator, "login", "fail")
                self.after(0, self._set_indicator, "token", "fail")
                self._log_queue.put("  ✗ Login failed or cancelled")
                return
            except Exception as e:
                self.after(0, self._set_indicator, "login", "fail")
                self._log_queue.put(f"  ✗ Login failed: {e}")
                return

            # 2 — API Access
            self.after(0, self._set_indicator, "api", "pending")
            try:
                client.get_user_profile()
                self.after(0, self._set_indicator, "api", "ok")
                self._log_queue.put("  ✓ API access OK")
            except Exception as e:
                self.after(0, self._set_indicator, "api", "fail")
                self._log_queue.put(f"  ✗ API access failed: {e}")
                return

            # 3 — Data
            self.after(0, self._set_indicator, "data", "pending")
            try:
                from datetime import date, timedelta
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                client.get_stats(yesterday)
                self.after(0, self._set_indicator, "data", "ok")
                self._log_queue.put("  ✓ Data access OK")
                self._connection_verified = True
                if on_success:
                    self.after(0, on_success)
            except Exception as e:
                self.after(0, self._set_indicator, "data", "fail")
                self._log_queue.put(f"  ✗ Data access failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_enc_key(self, mode="setup") -> str | None:
        """Popup to collect the encryption key from the user.
        mode='setup'    — first time setup: two fields (key + confirm) + hint text.
        mode='recovery' — WCM lost after Windows update: single field + explanation.
        Returns the entered key string, or None if cancelled.
        Blocks the calling thread until the user responds (uses threading.Event).
        """
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
        """Popup warning about 429 risk when token has expired.
        Returns True if user clicks Proceed, False if Cancel.
        Blocks the calling thread until the user responds.
        """
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
        """Popup to collect the MFA code from the user.
        Returns the entered code string, or None if cancelled.
        Blocks the calling thread until the user responds.
        """
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
        """Clear encrypted token file and WCM enc_key entry."""
        import garmin_security
        garmin_security.clear_token()
        self._set_indicator("token", "reset")
        self._connection_verified = False
        self._log("🔑  Token reset — next sync will require a new login.")

    def _clean_archive(self):
        """Opens Clean Archive popup — shows preview, then deletes on confirm."""
        import json as _json
        from pathlib import Path as _Path
        from datetime import date as _date

        s = self._collect_settings()
        base_dir = _Path(s["base_dir"]).expanduser() if s["base_dir"] else None
        if not base_dir:
            self._log("✗ Clean Archive: no data folder set.")
            return

        quality_log = base_dir / "log" / "quality_log.json"
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
            cutoff = _date.fromisoformat(first_day_str)
        except ValueError:
            self._log(f"✗ Clean Archive: invalid first_day value '{first_day_str}'.")
            return

        # Collect files to delete
        to_delete = []
        raw_dir     = base_dir / "raw"
        summary_dir = base_dir / "summary"
        for folder, pattern, prefix in [
            (raw_dir,     "garmin_raw_*.json", "garmin_raw_"),
            (summary_dir, "garmin_*.json",     "garmin_"),
        ]:
            if not folder.exists():
                continue
            for f in sorted(folder.glob(pattern)):
                try:
                    d = _date.fromisoformat(f.stem.replace(prefix, ""))
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

        # ── Build popup ────────────────────────────────────────────────────────
        popup = tk.Toplevel(self)
        popup.title("Clean Archive")
        popup.configure(bg=BG)
        popup.resizable(False, False)
        popup.grab_set()

        # Header
        tk.Label(popup, text="🗑  Clean Archive",
                 font=("Segoe UI", 12, "bold"), bg=BG, fg=TEXT,
                 padx=20, pady=14).pack(anchor="w")
        tk.Frame(popup, bg=ACCENT, height=1).pack(fill="x", padx=20)

        # Info
        info_frame = tk.Frame(popup, bg=BG, padx=20, pady=10)
        info_frame.pack(fill="x")
        tk.Label(info_frame,
                 text=f"first_day:  {first_day_str}",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Label(info_frame,
                 text="The following files will be permanently deleted:",
                 font=FONT_BODY, bg=BG, fg=TEXT2, pady=6).pack(anchor="w")

        # Scrollable file list
        list_frame = tk.Frame(popup, bg=BG, padx=20)
        list_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame,
                             yscrollcommand=scrollbar.set,
                             bg=BG3, fg=TEXT2, font=("Consolas", 8),
                             relief="flat", bd=0, height=12,
                             selectbackground=BG3, activestyle="none")
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)

        for f in to_delete:
            listbox.insert("end", f"  {f.relative_to(base_dir)}")

        # Summary line
        summary_frame = tk.Frame(popup, bg=BG, padx=20, pady=8)
        summary_frame.pack(fill="x")
        tk.Label(summary_frame,
                 text=f"{len(to_delete)} file(s)  ·  {len(entries_to_remove)} quality log entry/entries",
                 font=("Segoe UI", 8), bg=BG, fg=TEXT2).pack(anchor="w")

        tk.Frame(popup, bg=ACCENT, height=1).pack(fill="x", padx=20)

        # Buttons
        btn_frame = tk.Frame(popup, bg=BG, padx=20, pady=14)
        btn_frame.pack(fill="x")

        def do_delete():
            deleted = 0
            for f in to_delete:
                try:
                    f.unlink(missing_ok=True)
                    deleted += 1
                except Exception as e:
                    self._log(f"  ✗ Could not delete {f.name}: {e}")
            # Remove entries from quality log
            data["days"] = [
                e for e in data.get("days", [])
                if e.get("date", "9999") >= first_day_str
            ]
            try:
                tmp = quality_log.with_suffix(".tmp")
                tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(quality_log)
            except Exception as e:
                self._log(f"  ✗ Could not update quality_log.json: {e}")
            popup.destroy()
            self._log(f"✓ Clean Archive: {deleted} file(s) deleted, "
                      f"{len(entries_to_remove)} log entry/entries removed.")

        tk.Button(btn_frame, text="Abbrechen", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=popup.destroy).pack(side="left")
        tk.Button(btn_frame, text="🗑  Löschen", font=FONT_BTN,
                  bg="#e94560", fg=TEXT, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=do_delete).pack(side="right")

    def _run_collector(self):
        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for manual sync.")
            self._timer_generation += 1
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        # ── Failed days popup ──
        refresh_failed = self._check_failed_days_popup(
            base_dir  = s["base_dir"],
            sync_mode = s["sync_mode"],
            sync_days = s["sync_days"],
            sync_from = s.get("sync_from", ""),
            sync_to   = s.get("sync_to", ""),
        )

        if self._connection_verified:
            self._run_module("garmin_collector.py", enable_stop=True,
                             refresh_failed=refresh_failed,
                             on_done=lambda: (
                                 self._timer_resume_after_sync(timer_was_active),
                                 self._refresh_archive_info(),
                             ))
            return

        self._run_connection_test(
            on_success=lambda: self._run_module(
                "garmin_collector.py", enable_stop=True,
                refresh_failed=refresh_failed,
                on_done=lambda: (
                    self._timer_resume_after_sync(timer_was_active),
                    self._refresh_archive_info(),
                )))

    def _run_import(self):
        """Open file dialog and run bulk import via _run_module — same pattern as _run_collector."""
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

        # Pause background timer if active
        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for import.")
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        self._log(f"   Source: {path}")
        self._run_module(
            "garmin_collector.py",
            enable_stop=True,
            log_prefix="garmin_bulk",
            env_overrides={"GARMIN_IMPORT_PATH": path},
            on_done=lambda: (
                self._timer_resume_after_sync(timer_was_active),
                self._refresh_archive_info(),
            ),
        )

    def _run_excel_overview(self):
        self._run_module("garmin_to_excel.py")

    def _run_excel_timeseries(self):
        self._run_module("garmin_timeseries_excel.py")

    def _run_html_timeseries(self):
        s = self._collect_settings()
        html_path = str(Path(s["base_dir"]) / "garmin_dashboard.html")
        self._run_module(
            "garmin_timeseries_html.py",
            on_success=lambda: setattr(self, "_last_html", html_path),
        )

    def _run_html_analysis(self):
        s = self._collect_settings()
        html_path = str(Path(s["base_dir"]) / "garmin_analysis.html")
        self._run_module(
            "garmin_analysis_html.py",
            on_success=lambda: setattr(self, "_last_html", html_path),
        )

    def _open_data_folder(self):
        folder = Path(self._collect_settings()["base_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

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
        fail_dir = Path(self._collect_settings()["base_dir"]) / "log" / "fail"
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
                    from garminconnect import Garmin
                    s2 = self._collect_settings()
                    client = Garmin(s2["email"], s2["password"])
                    client.login()
                    client.get_user_profile()
                    from datetime import date, timedelta
                    yesterday = (date.today() - timedelta(days=1)).isoformat()
                    client.get_stats(yesterday)
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
                remaining = [m for m in _mode_cycle if m != mode]
                days = None
                for other_mode in remaining:
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
                        self.after(0, self._log, "⏱  Archive complete — background timer stopped.")
                        self._timer_active = False
                        self.after(0, self._timer_update_btn)
                    return

            n_days         = random.randint(min_days, max_days)
            days_pick      = sorted(random.sample(days, min(n_days, len(days))))
            sync_dates_str = ",".join(d.isoformat() for d in days_pick)
            days_left      = len(days_pick)
            queue_total    = len(days)

            label = {"repair": "Repair", "quality": "Quality", "fill": "Fill"}.get(mode, mode)
            self.after(0, self._log,
                f"⏱  [{label}] Syncing {days_left} days ({queue_total} in queue)")

            # Wait for any running module to finish
            while self._running:
                if _stale():
                    return
                self._timer_stop.wait(timeout=0.5)

            # ── Run the sync ──
            refresh = (mode in ("repair", "quality"))
            env_overrides = {
                "GARMIN_SYNC_DATES":         sync_dates_str,
                "GARMIN_REFRESH_FAILED":     "1" if refresh else "0",
                "GARMIN_SESSION_LOG_PREFIX": "garmin_background",
            }
            sync_done = threading.Event()

            def _on_done():
                sync_done.set()

            self.after(0, lambda eo=env_overrides, d=_on_done, dl=days_left: self._run_module(
                "garmin_collector.py",
                enable_stop=False,
                refresh_failed=refresh,
                log_prefix="garmin_background",
                env_overrides=eo,
                stop_event=self._timer_stop,
                days_left=dl,
                on_done=d,
            ))

            while not sync_done.is_set():
                if _stale():
                    return
                self._timer_stop.wait(timeout=0.5)

            if _stale():
                return

            # ── Countdown ──
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
        """
        Returns list of date objects with quality='failed' and recheck=True.
        Returns None if queue is empty.
        """
        try:
            failed_file = Path(s["base_dir"]) / "log" / "quality_log.json"
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

    def _timer_run_quality(self, s: dict):
        """
        Returns list of date objects with quality='low' and recheck=True.
        Returns None if queue is empty.
        """
        try:
            failed_file = Path(s["base_dir"]) / "log" / "quality_log.json"
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
        """
        Returns list of date objects that are completely absent from raw/
        (no file at all, not even incomplete). Compares all dates from
        earliest quality_log.json entry (or earliest local file) to yesterday.
        Returns None if no truly missing days exist.
        """
        try:
            raw_dir = Path(s["base_dir"]) / "raw"

            existing = set()
            if raw_dir.exists():
                for f in raw_dir.glob("garmin_raw_*.json"):
                    try:
                        existing.add(date.fromisoformat(f.stem.replace("garmin_raw_", "")))
                    except ValueError:
                        pass

            failed_file = Path(s["base_dir"]) / "log" / "quality_log.json"
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

    def _on_close(self):
        self._timer_generation += 1
        self._timer_stop.set()
        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        save_settings(self.settings)
        self.destroy()


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


if __name__ == "__main__":
    app = GarminApp()
    apply_style()
    app.mainloop()
