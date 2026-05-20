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

v1.5.3 — Panel Decomposition
  GarminAppBase is now a pure assembler. All panel logic lives in:
    app/panel_settings.py    — PanelSettingsMixin
    app/panel_connection.py  — PanelConnectionMixin
    app/panel_archive.py     — PanelArchiveMixin
    app/panel_timer.py       — PanelTimerMixin
    app/panel_outputs.py     — PanelOutputsMixin
"""

import sys
import threading
import tkinter as tk
from tkinter import scrolledtext

import garmin_app_settings as _settings
import garmin_app_controller as _controller

from panel_settings    import PanelSettingsMixin
from panel_connection  import PanelConnectionMixin
from panel_archive     import PanelArchiveMixin
from panel_timer       import PanelTimerMixin
from panel_outputs     import PanelOutputsMixin

# ── Settings — re-exported from garmin_app_settings ───────────────────────────
# garmin_app.py and garmin_app_standalone.py import these names from this module.

SETTINGS_FILE    = _settings.SETTINGS_FILE
DEFAULT_SETTINGS = _settings.DEFAULT_SETTINGS
load_settings    = _settings.load_settings
save_password    = _settings.save_password
load_password    = _settings.load_password
delete_password  = _settings.delete_password
_open_url        = _settings._open_url

# ── Colors & fonts ─────────────────────────────────────────────────────────────
# Defined as class attributes on GarminAppBase — see class body below.

from version import APP_VERSION


# ── Style ──────────────────────────────────────────────────────────────────────

def apply_style():
    from tkinter import ttk
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox",
        fieldbackground=GarminAppBase.BG3, background=GarminAppBase.BG3,
        foreground=GarminAppBase.TEXT, selectbackground=GarminAppBase.ACCENT2,
        selectforeground=GarminAppBase.TEXT, arrowcolor=GarminAppBase.TEXT2,
        borderwidth=0, relief="flat",
    )
    style.map("TCombobox",
        fieldbackground=[("readonly", GarminAppBase.BG3)],
        foreground=[("readonly", GarminAppBase.TEXT)],
    )


# ── Base application ───────────────────────────────────────────────────────────

class GarminAppBase(
    PanelSettingsMixin,
    PanelConnectionMixin,
    PanelArchiveMixin,
    PanelTimerMixin,
    PanelOutputsMixin,
    tk.Tk,
):
    # ── Colors & fonts (class attributes — inherited by all panel mixins) ───────
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

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.title("Garmin Local Archive")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(920, 950)
        self.geometry("1100x980")

        # ── Shared State ────────────────────────────────────────────────────────
        # Owner and thread rules documented for Qt migration preparation (v1.5.3.1)
        self._stop_btn            = None    # Owner: panel_outputs  | Thread: Main
        self._last_html           = None    # Owner: panel_outputs  | Thread: Main
        self._stopped_by_user     = False   # Owner: panel_outputs  | Thread: Main
        self._connection_verified = False   # Owner: panel_connection | Thread: Main
        self._timer_conn_verified = False   # Owner: panel_timer    | Thread: Main
        self._timer_active        = False   # Owner: panel_timer    | Thread: Main
        self._timer_stop          = threading.Event()  # Owner: panel_timer | cross-thread
        self._timer_btn           = None    # Owner: panel_timer    | Thread: Main
        self._timer_next_mode     = "repair"  # Owner: panel_timer  | Thread: Main
        self._timer_generation    = 0       # Owner: panel_timer    | Thread: Main
        self._mirror_running      = False   # Owner: panel_archive  | Thread: BG-write (GIL-safe bool) + Main-read
        self._ctx_running         = False   # Owner: panel_outputs  | Thread: BG-write (GIL-safe bool) + Main-read
        self._context_stop_event  = threading.Event()  # Owner: panel_outputs | cross-thread; neues Objekt pro _run_context_sync()-Aufruf

        self._build_ui()
        self._load_settings_to_ui()
        self.v_sync_mode.set("recent")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(0, self._check_migration)
        threading.Thread(target=self._check_version,          daemon=True).start()
        threading.Thread(target=self._startup_integrity_check, daemon=True).start()
        threading.Thread(target=self._startup_mirror_check,   daemon=True).start()

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

    def _stop_collector(self):
        """Abstract hook — implemented in subclass (garmin_app.py / garmin_app_standalone.py)."""
        raise NotImplementedError

    # ── ENV builder ────────────────────────────────────────────────────────────

    def _build_env_dict(self, s: dict, refresh_failed: bool = False) -> dict:
        """Delegates to garmin_app_controller.build_env_dict."""
        return _controller.build_env_dict(s, refresh_failed)

    # ── Migration ──────────────────────────────────────────────────────────────

    def _check_migration(self):
        """Migration check — logic in controller, dialogs and destroy here."""
        s        = self._collect_settings()
        base_dir = __import__("pathlib").Path(s.get("base_dir", "")).expanduser()

        if not _controller.check_migration_needed(base_dir):
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

        result = _controller.run_migration(base_dir)
        if result == "ok":
            tk.messagebox.showinfo(
                "Migration complete",
                f"Folders successfully moved to:\n{base_dir / 'garmin_data'}",
            )
        else:
            tk.messagebox.showerror(
                "Migration error",
                "Error moving folders.\n\n"
                "Please migrate manually and restart the app.",
            )
            self.destroy()

    # ── UI builder ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=BG3, pady=10)
        header.pack(fill="x")
        _unicorn = tk.Label(header, text="🦄  GARMIN LOCAL ARCHIVE",
                            font=("Segoe UI", 13, "bold"), bg=BG3, fg=TEXT,
                            cursor="arrow")
        _unicorn.pack(side="left", padx=20)
        _unicorn.bind("<Button-1>", lambda e: self._run_extended_analysis())
        tk.Label(header, text=APP_VERSION,
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT2).pack(
                 side="left", padx=(0, 8))
        tk.Label(header, text="local · private · yours",
                 font=("Segoe UI", 9), bg=BG3, fg=TEXT).pack(side="left", padx=4)
        tk.Label(header, text="GNU GPL v3",
                 font=("Segoe UI", 8), bg=BG3, fg=TEXT2).pack(side="right", padx=8)
        link = tk.Label(header,
                        text="www.github.com/Wewoc/Garmin_Local_Archive",
                        font=("Segoe UI", 8, "underline"), bg=BG3,
                        fg="#6ab0f5", cursor="hand2")
        link.pack(side="right", padx=4)
        link.bind("<Button-1>",
                  lambda e: _open_url(
                      "https://www.github.com/Wewoc/Garmin_Local_Archive"))

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
        self._build_connection_panel(right_inner)
        self._build_timer_panel(right_inner)
        self._build_outputs_panel(right_inner)
        self.after(200, self._refresh_archive_info)

        log_frame = tk.Frame(self, bg=BG, pady=0)
        log_frame.pack(fill="both", expand=False, padx=0)
        self._build_log(log_frame)

    def _make_scrollable_panel(self, parent, bg):
        canvas    = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical",
                                  command=canvas.yview,
                                  bg=bg, troughcolor=bg,
                                  relief="flat", bd=0, width=6)
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

    # ── Log helpers ────────────────────────────────────────────────────────────

    def _log(self, text: str):
        """Write to log widget — must be called from Main thread."""
        if not hasattr(self, "log"):
            return
        self.log.config(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.config(state="disabled")

    # ── Version check ──────────────────────────────────────────────────────────

    def _check_version(self):
        import urllib.request
        import json as _json
        url = "https://api.github.com/repos/Wewoc/Garmin_Local_Archive/releases/latest"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "GarminLocalArchive"})
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
                 text=f"A new version is available: {latest}\n"
                      f"You are running: {APP_VERSION}",
                 font=FONT_BODY, bg=BG, fg=TEXT2, justify="left").pack(**pad)

        def _open():
            webbrowser.open(
                "https://github.com/Wewoc/Garmin_Local_Archive/releases/latest")
            popup.destroy()

        btn_row = tk.Frame(popup, bg=BG)
        btn_row.pack(pady=12)
        tk.Button(btn_row, text="Open GitHub", font=FONT_BTN,
                  bg=ACCENT, fg=TEXT, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=_open).pack(side="left", padx=4)
        tk.Button(btn_row, text="Dismiss", font=FONT_BTN,
                  bg=BG3, fg=TEXT2, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=popup.destroy).pack(side="left", padx=4)

    # ── Extended Analysis ──────────────────────────────────────────────────────

    def _run_extended_analysis(self):
        """Launches garmin_extended_anaysis.py in a new console window.
        Subclass (garmin_app.py) overrides this with _find_python() access."""
        pass

    def _find_script(self, name: str):
        """Locates a script file — checks scripts/ next to exe, then project root."""
        from pathlib import Path
        candidates = [
            Path(sys.executable).parent / "scripts" / name,
            Path(__file__).parent / "garmin" / name,
            Path(__file__).parent / name,
        ]
        return next((p for p in candidates if p.exists()), None)

    # ── Close ──────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._timer_generation += 1
        self._timer_stop.set()
        self._context_stop_event.set()
        self.settings = self._collect_settings()
        save_password(self.settings.get("password", ""))
        self._safe_save(self.settings)
        self.destroy()


# ── Module-level aliases — backwards-compatible imports from garmin_app.py ──────
BG        = GarminAppBase.BG
BG2       = GarminAppBase.BG2
BG3       = GarminAppBase.BG3
ACCENT    = GarminAppBase.ACCENT
ACCENT2   = GarminAppBase.ACCENT2
TEXT      = GarminAppBase.TEXT
TEXT2     = GarminAppBase.TEXT2
GREEN     = GarminAppBase.GREEN
YELLOW    = GarminAppBase.YELLOW
FONT_HEAD = GarminAppBase.FONT_HEAD
FONT_BODY = GarminAppBase.FONT_BODY
FONT_MONO = GarminAppBase.FONT_MONO
FONT_BTN  = GarminAppBase.FONT_BTN
FONT_LOG  = GarminAppBase.FONT_LOG
