#!/usr/bin/env python3
"""
garmin_app.py
Garmin Local Archive — Desktop GUI (Target 1 + Target 2)

Entry point for Dev (T1) and Standard EXE (T2).
Execution model: subprocess via Popen.
Subclasses GarminAppBase from garmin_app_base.py.
"""

import os
import re
import sys
import subprocess
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    # EXE: scripts/ liegt neben der EXE, alle Unterordner eintragen
    _scripts = Path(sys.executable).parent / "scripts"
    for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        sys.path.insert(0, str(_scripts / _sub))
    sys.path.insert(0, str(_scripts))
else:
    # Dev: Unterordner liegen im Root neben garmin_app.py
    _root = Path(__file__).parent
    for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        sys.path.insert(0, str(_root / _sub))

from garmin_app_base import (
    GarminAppBase, load_password, save_password, apply_style,
    APP_VERSION, BG, BG2, BG3, ACCENT, ACCENT2, TEXT, TEXT2,
    GREEN, YELLOW, FONT_HEAD, FONT_BODY, FONT_MONO, FONT_BTN, FONT_LOG,
)
import tkinter as tk
from tkinter import messagebox


# ── Resolve script paths ───────────────────────────────────────────────────────

def _find_python() -> Path:
    """Find the real python.exe — needed when running as a PyInstaller .exe."""
    if not getattr(sys, "frozen", False):
        return Path(sys.executable)

    import shutil
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return Path(found)

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    for pattern in [
        local / "Programs" / "Python" / "Python3*" / "python.exe",
        Path("C:/Python3*/python.exe"),
        Path("C:/Program Files/Python3*/python.exe"),
    ]:
        import glob
        matches = glob.glob(str(pattern))
        if matches:
            return Path(sorted(matches)[-1])

    return Path("python.exe")


def script_dir() -> Path:
    """
    Returns the folder containing the Python scripts.
    - Frozen (.exe): scripts/ subfolder next to the .exe
    - Dev (.py directly): folder of this file
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "scripts"
    return Path(__file__).parent / "garmin"


def script_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = script_dir()
        for sub in ("garmin", "maps", "dashboards", "layouts", "context", "export"):
            candidate = base / sub / name
            if candidate.exists():
                return candidate
        return base / name
    for sub in ("garmin", "maps", "dashboards", "layouts", "context", "export"):
        candidate = Path(__file__).parent / sub / name
        if candidate.exists():
            return candidate
    return script_dir() / name


# ── Main application ───────────────────────────────────────────────────────────

class GarminApp(GarminAppBase):
    def __init__(self):
        self._active_proc = None   # must exist before super().__init__ builds UI
        super().__init__()

    # ── Execution-model hooks ──────────────────────────────────────────────────

    def _run(self, script_name: str, enable_stop: bool = False,
             on_success=None, refresh_failed: bool = False,
             on_done=None, log_prefix: str = "garmin",
             env_overrides: dict = None, stop_event: threading.Event = None,
             days_left: int = None):
        """Subprocess implementation of the _run hook."""
        path = script_path(script_name)
        if not path.exists():
            self._log(f"✗ Script not found: {path}")
            return

        s   = self._collect_settings()
        env = {**os.environ, **self._build_env_dict(s, refresh_failed=refresh_failed)}
        env["GARMIN_SESSION_LOG_PREFIX"] = log_prefix
        if env_overrides:
            env.update(env_overrides)

        python_exe = _find_python()
        self._log(f"\n▶  Running {script_name} ...")
        self._log(f"   Python:  {python_exe}")
        self._log(f"   Data:    {s['base_dir']}")
        self._log_level_hint.pack_forget()

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

                if days_left is not None and self._timer_btn:
                    self.after(0, lambda dl=days_left: self._timer_btn and
                        self._timer_btn.config(text=f"⏱  Syncing · {dl}/{dl}"))

                _day_pattern = re.compile(r"\[(\d+)/(\d+)\]")

                for line in proc.stdout:
                    self.after(0, self._log, line.rstrip())
                    if days_left is not None and self._timer_btn:
                        m = _day_pattern.search(line)
                        if m:
                            current   = int(m.group(1))
                            total     = int(m.group(2))
                            remaining = total - current + 1
                            self.after(0, lambda r=remaining, t=total:
                                self._timer_btn and
                                self._timer_btn.config(text=f"⏱  Syncing · {r}/{t}"))
                    if stop_event is not None and stop_event.is_set():
                        self._stopped_by_user = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except Exception:
                            proc.kill()
                        break

                proc.wait()

                if proc.returncode == 0:
                    self.after(0, self._log, "✓ Done. — please update context")
                    if on_success:
                        self.after(0, on_success)
                elif not self._stopped_by_user:
                    self.after(0, self._log,
                               f"✗ Exit code {proc.returncode} — check output above.")
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
                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _log_bg(self, text: str):
        """Thread-safe log: schedule on main thread via after()."""
        self.after(0, self._log, text)

    def _is_running(self) -> bool:
        return self._active_proc is not None

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


if __name__ == "__main__":
    app = GarminApp()
    apply_style()
    app.mainloop()
