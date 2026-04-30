#!/usr/bin/env python3
"""
garmin_app_standalone.py
Garmin Local Archive — Desktop GUI (Standalone Entry Point)

Target 3: no Python installation required on the target machine.

Differences from garmin_app.py:
  - script_dir()   → sys._MEIPASS/scripts/ (embedded data unpacked by PyInstaller)
  - _run()         → importlib instead of subprocess — scripts are imported
                     directly as modules and run in threads. stdout/stderr/logging
                     are redirected to the GUI log via a queue.
  - _stop_collector() → sets a threading.Event instead of killing a process
  - _log_bg()      → self._log_queue.put() instead of self.after(0, self._log)
  - _is_running()  → self._running instead of self._active_proc is not None

Built by: build_standalone.py
"""

import importlib.util
import io
import logging
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

if getattr(sys, "frozen", False):
    # T3: Scripts liegen in sys._MEIPASS — PyInstaller macht sie direkt importierbar
    pass
else:
    # Dev: Unterordner liegen im Root neben garmin_app_standalone.py
    _root = Path(__file__).parent
    for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        sys.path.insert(0, str(_root / _sub))


def _register_embedded_packages():
    """Register embedded packages so relative imports work in frozen EXE."""
    if not getattr(sys, "frozen", False):
        return
    import types
    scripts = Path(sys._MEIPASS) / "scripts"
    garmin_dir = scripts / "garmin"
    if garmin_dir.exists():
        sys.path.insert(0, str(garmin_dir))
    for pkg in ("context", "maps", "dashboards", "layouts"):
        pkg_dir = scripts / pkg
        if pkg_dir.exists() and pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__ = [str(pkg_dir)]
            mod.__package__ = pkg
            sys.modules[pkg] = mod


_register_embedded_packages()

from garmin_app_base import (
    GarminAppBase, load_password, save_password, apply_style,
    APP_VERSION, BG, BG2, BG3, ACCENT, ACCENT2, TEXT, TEXT2,
    GREEN, YELLOW, FONT_HEAD, FONT_BODY, FONT_MONO, FONT_BTN, FONT_LOG,
)
import tkinter as tk
from tkinter import messagebox


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


# ── Script paths ───────────────────────────────────────────────────────────────

def script_dir() -> Path:
    """
    Standalone: PyInstaller unpacks --add-data to sys._MEIPASS.
    Scripts land in sys._MEIPASS/scripts/.
    Dev fallback: folder of this file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "scripts"
    return Path(__file__).parent / "garmin"


def script_path(name: str) -> Path:
    base = script_dir()
    for sub in ("garmin", "maps", "dashboards", "layouts", "context", "export"):
        candidate = base / sub / name
        if candidate.exists():
            return candidate
    return base / name


# ── Main application ───────────────────────────────────────────────────────────

class GarminApp(GarminAppBase):
    def __init__(self):
        self._stop_event = threading.Event()
        self._running    = False
        self._log_queue  = queue.Queue()
        super().__init__()
        self._poll_log_queue()

    # ── Execution-model hooks ──────────────────────────────────────────────────

    def _run(self, script_name: str, enable_stop: bool = False,
             on_success=None, refresh_failed: bool = False,
             on_done=None, log_prefix: str = "garmin",
             env_overrides: dict = None, stop_event: threading.Event = None,
             days_left: int = None):
        """
        importlib implementation of the _run hook.

        Loads the script as a module and calls its main() in a background thread.
        stdout, stderr, and the root logger are redirected to _log_queue.
        Original streams are restored after the module finishes.
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

            if days_left is not None and self._timer_btn:
                self.after(0, lambda dl=days_left: self._timer_btn and
                    self._timer_btn.config(text=f"⏱  Syncing · {dl}/{dl}"))

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
                # Build env dict and apply to os.environ before module load
                env_dict = self._build_env_dict(s, refresh_failed=refresh_failed)
                env_dict["GARMIN_SESSION_LOG_PREFIX"] = log_prefix
                if env_overrides:
                    env_dict.update(env_overrides)
                for k, v in env_dict.items():
                    os.environ[k] = v

                spec   = importlib.util.spec_from_file_location(
                    script_name.replace(".py", ""), path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                effective_stop = stop_event if stop_event is not None else (
                    self._stop_event if enable_stop else None
                )
                if effective_stop is not None:
                    module.__dict__["_STOP_EVENT"] = effective_stop
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
                    q.put("✓ Done. — please update context")
                    if on_success:
                        self.after(0, on_success)

                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _log_bg(self, text: str):
        """Thread-safe log: put into queue for _poll_log_queue."""
        self._log_queue.put(text)

    def _is_running(self) -> bool:
        return self._running

    def _stop_collector(self):
        """Signal the running module thread to stop at its next opportunity."""
        if self._running:
            self._stop_event.set()
            self._log("⏹  Stop requested — waiting for current operation ...")

    def _poll_log_queue(self):
        """Drain the log queue into the GUI log widget. Reschedules itself."""
        try:
            while True:
                line = self._log_queue.get_nowait()
                self._log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)


if __name__ == "__main__":
    app = GarminApp()
    apply_style()
    app.mainloop()
