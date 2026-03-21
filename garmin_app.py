#!/usr/bin/env python3
"""
garmin_app.py
Garmin Local Archive — Desktop GUI
"""

import json
import os
import sys
import threading
import subprocess
from pathlib import Path
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

# ── Settings file ──────────────────────────────────────────────────────────────
SETTINGS_FILE = Path.home() / ".garmin_archive_settings.json"

DEFAULT_SETTINGS = {
    "email":       "",
    "base_dir":    "C:\\garmin",
    "sync_mode":   "recent",
    "sync_days":   "90",
    "sync_from":   "",
    "sync_to":     "",
    "date_from":   "",
    "date_to":     "",
    "age":         "35",
    "sex":         "male",
    "request_delay": "1.5",
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            data.pop("password", None)   # migrate: remove plaintext password if present
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

# ── Resolve script paths ───────────────────────────────────────────────────────
def _find_python() -> Path:
    """Find the real python.exe — needed when running as a PyInstaller .exe."""
    if not getattr(sys, "frozen", False):
        return Path(sys.executable)

    # Search in PATH
    import shutil
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return Path(found)

    # Search common Windows install locations
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for pattern in [
        local / "Programs" / "Python" / "Python3*" / "python.exe",
        Path("C:/Python3*/python.exe"),
        Path("C:/Program Files/Python3*/python.exe"),
    ]:
        import glob
        matches = glob.glob(str(pattern))
        if matches:
            return Path(sorted(matches)[-1])  # newest version

    # Last resort: hope python is in PATH
    return Path("python.exe")


def script_dir() -> Path:
    """
    Returns the folder containing the Python scripts.
    - Frozen (.exe): scripts/ subfolder next to the .exe
    - Dev (.py directly): folder of this file
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "scripts"
    return Path(__file__).parent

def script_path(name: str) -> Path:
    return script_dir() / name

def _open_url(url: str):
    """Open a URL — works both in dev and as frozen .exe."""
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
FONT_MONO = ("Consolas", 9)
FONT_BTN  = ("Segoe UI", 9, "bold")
FONT_LOG  = ("Consolas", 8)

# ── Main application ───────────────────────────────────────────────────────────
class GarminApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title("Garmin Local Archive")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(920, 950)
        self.geometry("1100x980")
        self._active_proc         = None
        self._stop_btn            = None
        self._last_html           = None
        self._stopped_by_user     = False
        self._connection_verified = False  # skips test after first successful check
        self._build_ui()
        self._load_settings_to_ui()
        self.v_sync_mode.set("recent")   # always start with recent — range requires explicit setup
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI builder ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=BG3, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="⌚  GARMIN LOCAL ARCHIVE",
                 font=("Segoe UI", 13, "bold"), bg=BG3, fg=TEXT).pack(side="left", padx=20)
        tk.Label(header, text="v1.0.1",
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

        # Left panel
        left = tk.Frame(main, bg=BG2, width=300)
        left.pack(side="left", fill="y", padx=0, pady=0)
        left.pack_propagate(False)
        self._build_settings_panel(left)

        # Right panel
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_actions_panel(right)

        # Log
        log_frame = tk.Frame(self, bg=BG, pady=0)
        log_frame.pack(fill="both", expand=False, padx=0)
        self._build_log(log_frame)

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG2)
        f.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG2, fg=ACCENT).pack(anchor="w", pady=(4,2))
        sep = tk.Frame(f, bg=ACCENT, height=1)
        sep.pack(fill="x", pady=(0,6))
        return f

    def _field(self, parent, label, var, show=None, width=28):
        row = tk.Frame(parent, bg=BG2)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text=label, font=FONT_BODY, bg=BG2, fg=TEXT2, width=14, anchor="w").pack(side="left")
        kwargs = dict(textvariable=var, font=FONT_BODY, bg=BG3, fg=TEXT,
                      insertbackground=TEXT, relief="flat", bd=4, width=width)
        if show:
            kwargs["show"] = show
        e = tk.Entry(row, **kwargs)
        e.pack(side="left", padx=(2,0))
        return e

    def _build_settings_panel(self, parent):
        tk.Label(parent, text="Settings", font=FONT_HEAD,
                 bg=BG2, fg=TEXT).pack(anchor="w", padx=16, pady=(14,0))

        # Account
        s = self._section(parent, "Garmin Account")
        self.v_email    = tk.StringVar()
        self.v_password = tk.StringVar()
        self._field(s, "Email", self.v_email)
        self._field(s, "Password", self.v_password, show="•")

        # Storage
        s2 = self._section(parent, "Storage")
        self.v_base_dir = tk.StringVar()
        row = tk.Frame(s2, bg=BG2)
        row.pack(fill="x", padx=4, pady=2)
        tk.Label(row, text="Data folder", font=FONT_BODY, bg=BG2, fg=TEXT2, width=14, anchor="w").pack(side="left")
        tk.Entry(row, textvariable=self.v_base_dir, font=FONT_BODY, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, relief="flat", bd=4, width=18).pack(side="left", padx=(2,2))
        tk.Button(row, text="…", font=FONT_BODY, bg=ACCENT2, fg=TEXT,
                  relief="flat", bd=0, padx=6,
                  command=self._browse_folder).pack(side="left")

        # Sync
        s3 = self._section(parent, "Sync Mode")
        self.v_sync_mode = tk.StringVar()
        row2 = tk.Frame(s3, bg=BG2)
        row2.pack(fill="x", padx=4, pady=2)
        tk.Label(row2, text="Mode", font=FONT_BODY, bg=BG2, fg=TEXT2, width=14, anchor="w").pack(side="left")
        cb = ttk.Combobox(row2, textvariable=self.v_sync_mode,
                          values=["recent", "range", "auto"],
                          state="readonly", width=10, font=FONT_BODY)
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_sync_mode_change())
        self.v_sync_days = tk.StringVar()
        self.v_sync_from = tk.StringVar()
        self.v_sync_to   = tk.StringVar()
        self._e_sync_days     = self._field(s3, "Days (recent)", self.v_sync_days, width=8)
        self._e_sync_from     = self._field(s3, "From (range)",  self.v_sync_from, width=12)
        self._e_sync_to       = self._field(s3, "To (range)",    self.v_sync_to,   width=12)
        self.v_sync_fallback  = tk.StringVar()
        self._e_sync_fallback = self._field(s3, "Fallback (auto)", self.v_sync_fallback, width=12)

        # Export range
        s4 = self._section(parent, "Export Date Range")
        self.v_date_from = tk.StringVar()
        self.v_date_to   = tk.StringVar()
        self._field(s4, "From", self.v_date_from, width=12)
        self._field(s4, "To",   self.v_date_to,   width=12)
        tk.Label(s4, text="Leave empty for all available data",
                 font=("Segoe UI", 7), bg=BG2, fg=TEXT2).pack(anchor="w", padx=4)

        # Profile
        s5 = self._section(parent, "Personal Profile")
        self.v_age = tk.StringVar()
        self.v_sex = tk.StringVar()
        self._field(s5, "Age", self.v_age, width=6)
        row3 = tk.Frame(s5, bg=BG2)
        row3.pack(fill="x", padx=4, pady=2)
        tk.Label(row3, text="Sex", font=FONT_BODY, bg=BG2, fg=TEXT2, width=14, anchor="w").pack(side="left")
        ttk.Combobox(row3, textvariable=self.v_sex,
                     values=["male", "female"], state="readonly",
                     width=10, font=FONT_BODY).pack(side="left", padx=2)

        # Advanced
        s6 = self._section(parent, "Advanced")
        self.v_delay = tk.StringVar()
        self._field(s6, "Request delay (s)", self.v_delay, width=6)

        # Save button
        tk.Frame(parent, bg=BG2, height=10).pack()
        tk.Button(parent, text="💾  Save Settings", font=FONT_BTN,
                  bg=ACCENT2, fg=TEXT, relief="flat", bd=0, pady=8, padx=12,
                  cursor="hand2", command=self._save).pack(fill="x", padx=12, pady=8)
        self._log_level = "INFO"
        self._log_level_btn = tk.Button(
            parent, text="📋  Log: Simple", font=FONT_BTN,
            bg=BG3, fg=TEXT2, relief="flat", bd=0, pady=6, padx=12,
            cursor="hand2", command=self._toggle_log_level)
        self._log_level_btn.pack(fill="x", padx=12, pady=(0, 8))

    def _build_actions_panel(self, parent):
        tk.Label(parent, text="Actions", font=FONT_HEAD,
                 bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14,0))

        # ── Connection test ────────────────────────────────────────────────────
        fc = tk.Frame(parent, bg=BG, pady=4)
        fc.pack(fill="x", padx=20, pady=2)
        tk.Label(fc, text="CONNECTION", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(fc, bg=ACCENT, height=1).pack(fill="x", pady=(2, 6))
        conn_row = tk.Frame(fc, bg=BG)
        conn_row.pack(fill="x", pady=2)
        self._test_btn = tk.Button(conn_row, text="🔌  Test Connection", font=FONT_BTN,
                                   bg=BG3, fg=TEXT, relief="flat", bd=0,
                                   pady=7, padx=14, cursor="hand2",
                                   command=self._run_connection_test)
        self._test_btn.pack(side="left")

        # Status indicators — Login / API Access / Data
        status_row = tk.Frame(fc, bg=BG)
        status_row.pack(fill="x", pady=(4, 2))
        self._conn_indicators = {}
        for key, label in [("login", "Login"), ("api", "API Access"), ("data", "Data")]:
            cell = tk.Frame(status_row, bg=BG)
            cell.pack(side="left", padx=(0, 16))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 10),
                           bg=BG, fg=TEXT2)
            dot.pack(side="left")
            tk.Label(cell, text=label, font=FONT_BODY,
                     bg=BG, fg=TEXT2).pack(side="left", padx=(3, 0))
            self._conn_indicators[key] = dot

        # Sync — custom row with stop button
        f = tk.Frame(parent, bg=BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text="DATA COLLECTION", font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(2,6))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", pady=2)
        sync_btn = tk.Button(row, text="▶  Sync Data", font=FONT_BTN,
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

        # Exports
        self._action_section(parent, "Export", [
            ("📊  Daily Overview",       BG3,    self._run_excel_overview,
             "Summary spreadsheet — one row per day"),
            ("📈  Timeseries Excel",     BG3,    self._run_excel_timeseries,
             "Intraday data + charts per metric"),
            ("🌐  Timeseries Dashboard", BG3,    self._run_html_timeseries,
             "Interactive browser dashboard"),
            ("🔍  Analysis Dashboard",   ACCENT2, self._run_html_analysis,
             "Values vs baseline vs reference ranges + JSON for Ollama"),
        ])

        # Open
        self._action_section(parent, "Output", [
            ("📁  Open Data Folder",   BG3, self._open_data_folder,
             "Open garmin_data/ in Explorer"),
            ("📄  Open Last HTML",     BG3, self._open_last_html,
             "Open the last generated HTML file in browser"),
        ])

    def _action_section(self, parent, title, buttons):
        f = tk.Frame(parent, bg=BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text=title.upper(), font=("Segoe UI", 7, "bold"),
                 bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Frame(f, bg=ACCENT, height=1).pack(fill="x", pady=(2,6))
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
            relief="flat", bd=0, wrap="word",
            state="disabled"
        )
        self.log.pack(fill="both", expand=True)

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
        self.v_delay.set(s.get("request_delay", "1.5"))
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
            "request_delay":      self.v_delay.get().strip(),
        }

    def _toggle_log_level(self):
        if self._log_level == "INFO":
            self._log_level = "DEBUG"
            self._log_level_btn.config(text="📋  Log: Detailed", fg=YELLOW)
        else:
            self._log_level = "INFO"
            self._log_level_btn.config(text="📋  Log: Simple", fg=TEXT2)

        # If sync is running: stop and restart with new log level
        if self._active_proc and self._active_proc.poll() is None:
            self._log("📋  Log level changed — restarting sync ...")
            self._stopped_by_user = True
            self._active_proc.terminate()
            try:
                self._active_proc.wait(timeout=5)
            except Exception:
                self._active_proc.kill()
            self._active_proc = None
            self.after(500, self._run_collector)

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

    def _stop_collector(self):
        """Terminate the running collector subprocess."""
        proc = self._active_proc
        if proc and proc.poll() is None:
            self._stopped_by_user = True
            self._log("⏹  Stopping sync ...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            self._log("✗ Sync stopped by user.")
        self._active_proc = None
        if self._stop_btn:
            self._stop_btn.config(state="disabled", bg=BG3, fg=TEXT2)

    # ── Script runner ──────────────────────────────────────────────────────────

    def _build_env(self, s: dict) -> dict:
        """
        Build the environment dict for a subprocess.
        All configuration is passed via environment variables — no source patching.
        The password is passed via GARMIN_PASSWORD and never written to any file.
        """
        base = Path(s["base_dir"])
        env  = os.environ.copy()
        env["PYTHONUTF8"]           = "1"

        # ── Identity & auth ──
        env["GARMIN_EMAIL"]         = s["email"]
        env["GARMIN_PASSWORD"]      = s["password"]

        # ── Paths ──
        env["GARMIN_OUTPUT_DIR"]    = str(base)
        env["GARMIN_EXPORT_FILE"]   = str(base / "garmin_export.xlsx")
        env["GARMIN_TIMESERIES_FILE"] = str(base / "garmin_timeseries.xlsx")
        env["GARMIN_DASHBOARD_FILE"]  = str(base / "garmin_dashboard.html")
        env["GARMIN_ANALYSIS_HTML"]   = str(base / "garmin_analysis.html")
        env["GARMIN_ANALYSIS_JSON"]   = str(base / "garmin_analysis.json")

        # ── Sync ──
        env["GARMIN_SYNC_MODE"]     = s["sync_mode"]
        env["GARMIN_DAYS_BACK"]     = s["sync_days"] or "90"
        env["GARMIN_SYNC_START"]    = s.get("sync_from", "")
        env["GARMIN_SYNC_END"]      = s.get("sync_to", "")
        env["GARMIN_SYNC_FALLBACK"] = s.get("sync_auto_fallback", "")
        env["GARMIN_REQUEST_DELAY"] = s["request_delay"]

        # ── Date range (for export scripts) ──
        _today  = date.today()
        _d_from = s.get("date_from", "").strip()
        _d_to   = s.get("date_to",   "").strip()
        env["GARMIN_DATE_FROM"] = _d_from or (_today - timedelta(days=90)).isoformat()
        env["GARMIN_DATE_TO"]   = _d_to   or _today.isoformat()

        # ── Profile (for analysis script) ──
        env["GARMIN_PROFILE_AGE"]   = s.get("age", "35")
        env["GARMIN_PROFILE_SEX"]   = s.get("sex", "male")

        # ── Log level ──
        env["GARMIN_LOG_LEVEL"]     = getattr(self, "_log_level", "INFO")

        return env

    def _run_script(self, script_name: str, enable_stop: bool = False,
                    on_success: callable = None):
        """
        Run a script in a background thread, stream stdout+stderr to the log.

        All configuration is passed via environment variables built by _build_env().
        No source-code patching, no tmp files.

        On non-zero exit: logs exit code + which ENV vars were set (excluding password).
        on_success: optional callable executed on the main thread after a clean exit.
        """
        path = script_path(script_name)
        if not path.exists():
            self._log(f"✗ Script not found: {path}")
            return

        s   = self._collect_settings()
        env = self._build_env(s)

        python_exe = _find_python()
        self._log(f"\n▶  Running {script_name} ...")
        self._log(f"   Python:  {python_exe}")
        self._log(f"   Data:    {s['base_dir']}")

        def worker():
            proc = None
            self._stopped_by_user = False
            try:
                creation_flags = 0x08000000 if sys.platform == "win32" else 0
                proc = subprocess.Popen(
                    [str(python_exe), "-X", "utf8", str(path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    cwd=str(script_dir()),
                    creationflags=creation_flags,
                )

                if enable_stop:
                    self._active_proc = proc
                    self.after(0, lambda: self._stop_btn.config(
                        state="normal", bg=ACCENT, fg=TEXT))

                for line in proc.stdout:
                    self.after(0, self._log, line.rstrip())

                proc.wait()

                if proc.returncode == 0:
                    self.after(0, self._log, "✓ Done.")
                    if on_success:
                        self.after(0, on_success)
                elif not self._stopped_by_user:
                    self.after(0, self._log,
                               f"✗ Exit code {proc.returncode} — check output above.")
                    # Log which ENV vars were active (debug aid, no password)
                    safe_env = {
                        k: v for k, v in env.items()
                        if k.startswith("GARMIN_") and k != "GARMIN_PASSWORD"
                    }
                    self.after(0, self._log,
                               "   ENV snapshot: " + ", ".join(
                                   f"{k}={v!r}" for k, v in sorted(safe_env.items())
                               ))

            except Exception as e:
                self.after(0, self._log, f"✗ Error launching {script_name}: {e}")
            finally:
                self._active_proc = None
                if enable_stop and self._stop_btn:
                    self.after(0, lambda: self._stop_btn.config(
                        state="disabled", bg=BG3, fg=TEXT2))

        threading.Thread(target=worker, daemon=True).start()

    # ── Actions ────────────────────────────────────────────────────────────────

    def _set_indicator(self, key: str, state: str):
        """Set a connection indicator: 'pending' | 'ok' | 'fail' | 'reset'."""
        colors = {"pending": "#f5a623", "ok": "#4ecca3", "fail": "#e94560", "reset": TEXT2}
        self._conn_indicators[key].config(fg=colors.get(state, TEXT2))

    def _run_connection_test(self):
        """Test Login → API Access → Data in a background thread."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Connection test: email or password missing.")
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._test_btn.config(state="disabled", bg=BG3, fg=TEXT2)
        self._log("\n🔌  Testing connection ...")

        def worker():
            try:
                from garminconnect import Garmin
            except ImportError:
                self.after(0, self._log, "✗ garminconnect not installed.")
                self.after(0, lambda: self._test_btn.config(state="normal", bg=BG3, fg=TEXT))
                return

            # 1 — Login
            self.after(0, self._set_indicator, "login", "pending")
            try:
                client = Garmin(s["email"], s["password"])
                client.login()
                self.after(0, self._set_indicator, "login", "ok")
                self.after(0, self._log, "  ✓ Login successful")
            except Exception as e:
                self.after(0, self._set_indicator, "login", "fail")
                self.after(0, self._log, f"  ✗ Login failed: {e}")
                self.after(0, lambda: self._test_btn.config(
                    state="normal", bg="#e94560", fg=TEXT))
                return

            # 2 — API Access
            self.after(0, self._set_indicator, "api", "pending")
            try:
                client.get_user_profile()
                self.after(0, self._set_indicator, "api", "ok")
                self.after(0, self._log, "  ✓ API access OK")
            except Exception as e:
                self.after(0, self._set_indicator, "api", "fail")
                self.after(0, self._log, f"  ✗ API access failed: {e}")
                self.after(0, lambda: self._test_btn.config(
                    state="normal", bg="#e94560", fg=TEXT))
                return

            # 3 — Data
            self.after(0, self._set_indicator, "data", "pending")
            try:
                from datetime import date, timedelta
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                client.get_stats(yesterday)
                self.after(0, self._set_indicator, "data", "ok")
                self.after(0, self._log, "  ✓ Data access OK")
                self.after(0, lambda: self._test_btn.config(
                    state="normal", bg="#4ecca3", fg="#0a0a1a"))
            except Exception as e:
                self.after(0, self._set_indicator, "data", "fail")
                self.after(0, self._log, f"  ✗ Data access failed: {e}")
                self.after(0, lambda: self._test_btn.config(
                    state="normal", bg="#e94560", fg=TEXT))

        threading.Thread(target=worker, daemon=True).start()

    def _run_collector(self):
        """Run connection test first (once per session), then start sync."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Email or password missing.")
            return

        if self._connection_verified:
            self._run_script("garmin_collector.py", enable_stop=True)
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._test_btn.config(state="disabled", bg=BG3, fg=TEXT2)
        self._log("\n🔌  Testing connection ...")

        def test_then_sync():
            try:
                from garminconnect import Garmin
            except ImportError:
                self.after(0, self._log, "✗ garminconnect not installed.")
                self.after(0, lambda: self._test_btn.config(state="normal", bg=BG3, fg=TEXT))
                return

            # 1 — Login
            self.after(0, self._set_indicator, "login", "pending")
            try:
                client = Garmin(s["email"], s["password"])
                client.login()
                self.after(0, self._set_indicator, "login", "ok")
                self.after(0, self._log, "  ✓ Login successful")
            except Exception as e:
                self.after(0, self._set_indicator, "login", "fail")
                self.after(0, self._log, f"  ✗ Login failed: {e}")
                self.after(0, lambda: self._test_btn.config(state="normal", bg="#e94560", fg=TEXT))
                return

            # 2 — API Access
            self.after(0, self._set_indicator, "api", "pending")
            try:
                client.get_user_profile()
                self.after(0, self._set_indicator, "api", "ok")
                self.after(0, self._log, "  ✓ API access OK")
            except Exception as e:
                self.after(0, self._set_indicator, "api", "fail")
                self.after(0, self._log, f"  ✗ API access failed: {e}")
                self.after(0, lambda: self._test_btn.config(state="normal", bg="#e94560", fg=TEXT))
                return

            # 3 — Data
            self.after(0, self._set_indicator, "data", "pending")
            try:
                from datetime import date, timedelta
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                client.get_stats(yesterday)
                self.after(0, self._set_indicator, "data", "ok")
                self.after(0, self._log, "  ✓ Data access OK — starting sync ...")
                self.after(0, lambda: self._test_btn.config(state="normal", bg="#4ecca3", fg="#0a0a1a"))
                self._connection_verified = True
                self.after(0, lambda: self._run_script("garmin_collector.py", enable_stop=True))
            except Exception as e:
                self.after(0, self._set_indicator, "data", "fail")
                self.after(0, self._log, f"  ✗ Data access failed: {e}")
                self.after(0, lambda: self._test_btn.config(state="normal", bg="#e94560", fg=TEXT))

        threading.Thread(target=test_then_sync, daemon=True).start()

    def _run_excel_overview(self):
        self._run_script("garmin_to_excel.py")

    def _run_excel_timeseries(self):
        self._run_script("garmin_timeseries_excel.py")

    def _run_html_timeseries(self):
        s = self._collect_settings()
        html_path = str(Path(s["base_dir"]) / "garmin_dashboard.html")
        self._run_script(
            "garmin_timeseries_html.py",
            on_success=lambda: setattr(self, "_last_html", html_path),
        )

    def _run_html_analysis(self):
        s = self._collect_settings()
        html_path = str(Path(s["base_dir"]) / "garmin_analysis.html")
        self._run_script(
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
            # find most recent html in base_dir
            base  = Path(self._collect_settings()["base_dir"])
            files = list(base.glob("*.html"))
            if not files:
                self._log("✗ No HTML files found in data folder.")
                return
            html = str(max(files, key=lambda f: f.stat().st_mtime))
        os.startfile(html)

    def _on_close(self):
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
