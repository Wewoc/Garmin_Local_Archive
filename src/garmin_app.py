#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
garmin_app.py
Garmin Local Archive — Desktop GUI (Target 1 + Target 2)

Entry point for Dev (T1) and Standard EXE (T2).
Execution model: subprocess via Popen.
Subclasses GarminApp from garmin_app_base.py.
"""

import os
import re
import sys
import subprocess
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    _scripts = Path(sys.executable).parent / "scripts"
    for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        sys.path.insert(0, str(_scripts / _sub))
    sys.path.insert(0, str(_scripts / "app"))
    sys.path.insert(0, str(_scripts))
else:
    _root = Path(__file__).parent
    for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        sys.path.insert(0, str(_root / _sub))
    sys.path.insert(0, str(_root / "app"))

from PyQt6.QtWidgets import QApplication

from garmin_app_base import GarminApp as _GarminAppBase


# ── Script path helpers ────────────────────────────────────────────────────────

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
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "scripts"
    return Path(__file__).parent / "garmin"


def script_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = script_dir()
        for sub in ("garmin", "maps", "dashboards", "layouts", "context"):
            candidate = base / sub / name
            if candidate.exists():
                return candidate
        return base / name
    for sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        candidate = Path(__file__).parent / sub / name
        if candidate.exists():
            return candidate
    return script_dir() / name


# ── Main application ───────────────────────────────────────────────────────────

class GarminApp(_GarminAppBase):

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
                    self._dispatch(
                        lambda: self._panel_outputs._stop_btn.setEnabled(True))

                if days_left is not None:
                    self._dispatch(
                        lambda dl=days_left:
                            self._panel_timer._timer_btn.setText(
                                f"⏱  Syncing · {dl}/{dl}"))

                _day_pattern = re.compile(r"\[(\d+)/(\d+)\]")

                for line in proc.stdout:
                    self._dispatch(self._log, line.rstrip())
                    if days_left is not None:
                        m = _day_pattern.search(line)
                        if m:
                            current   = int(m.group(1))
                            total     = int(m.group(2))
                            remaining = total - current + 1
                            self._dispatch(
                                lambda r=remaining, t=total:
                                    self._panel_timer._timer_btn.setText(
                                        f"⏱  Syncing · {r}/{t}"))
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
                    self._dispatch(self._log, "✓ Done. — please update context")
                    if on_success:
                        self._dispatch(on_success)
                elif not self._stopped_by_user:
                    self._dispatch(self._log,
                        f"✗ Exit code {proc.returncode} — check output above.")
                    safe_env = {
                        k: v for k, v in env.items()
                        if k.startswith("GARMIN_") and k != "GARMIN_PASSWORD"
                    }
                    self._dispatch(self._log,
                        "   ENV snapshot: " + ", ".join(
                            f"{k}={v!r}" for k, v in sorted(safe_env.items())
                        ))

            except Exception as e:
                self._dispatch(self._log,
                               f"✗ Error launching {script_name}: {e}")
            finally:
                self._active_proc = None
                if enable_stop:
                    self._dispatch(
                        lambda: self._panel_outputs._stop_btn.setEnabled(False))
                if on_done:
                    self._dispatch(on_done)

        threading.Thread(target=worker, daemon=True).start()

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
        self._panel_outputs._stop_btn.setEnabled(False)

    def _run_extended_analysis(self):
        """Launches garmin_extended_anaysis.py in a new console window."""
        s = self._collect_settings()
        try:
            script = script_path("garmin_extended_anaysis.py")
            if not script.exists():
                return
            env = self._build_env_dict(s)
            env["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
            subprocess.Popen(
                [str(_find_python()), str(script)],
                env={**os.environ, **env},
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                cwd=str(script.parent),
            )
        except Exception:
            pass  # Easter egg — fails silently


if __name__ == "__main__":
    import crash_handler
    from version import APP_VERSION
    crash_handler.install(app_version=APP_VERSION, exit_on_main=True)

    # ── Single instance guard ─────────────────────────────────────────────────
    # Ping the named local socket. If a response arrives, another GLA instance
    # is already running — show a warning and exit. If no response, become the
    # server so subsequent launches detect us.
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    _INSTANCE_KEY = "GarminLocalArchive_Instance"
    _ping = QLocalSocket()
    _ping.connectToServer(_INSTANCE_KEY)
    if _ping.waitForConnected(300):
        _ping.disconnectFromServer()
        # Need QApplication for QMessageBox
        _qapp_check = QApplication(sys.argv)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None,
            "Garmin Local Archive",
            "Garmin Local Archive is already running.\n\n"
            "Only one instance can run at a time.",
        )
        sys.exit(0)
    _ping = None  # release socket

    _instance_server = QLocalServer()
    QLocalServer.removeServer(_INSTANCE_KEY)   # clean up any stale socket
    _instance_server.listen(_INSTANCE_KEY)
    # ── End single instance guard ─────────────────────────────────────────────

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")

    window = GarminApp()
    window.show()
    sys.exit(qapp.exec())
