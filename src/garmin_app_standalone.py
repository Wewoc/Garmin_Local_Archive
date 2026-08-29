#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_app_standalone.py
Garmin Local Archive — Desktop GUI (Standalone Entry Point)

Target 3: no Python installation required on the target machine.

Differences from garmin_app.py:
  - script_dir()      → sys._MEIPASS/scripts/ (embedded data unpacked by PyInstaller)
  - _run()            → importlib instead of subprocess — scripts are imported
                        directly as modules and run in threads. stdout/stderr/logging
                        are redirected to the GUI log via a queue.
  - _stop_collector() → sets a threading.Event instead of killing a process
  - _log_bg()         → self._log_queue.put() instead of _dispatch(self._log)
  - _is_running()     → self._running instead of self._active_proc is not None
  - _poll_log_queue() → QTimer.singleShot(100, ...) instead of self.after(100, ...)

Built by: build_standalone.py
Note: Splash Screen removed in v1.5.6.2 — build_splash_pixmap() removed
      from garmin_app_base.py.
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
    sys.path.insert(0, str(_root / "app"))
    sys.path.insert(0, str(_root / "clients"))


def _register_embedded_packages():
    """Register embedded packages so relative imports work in frozen EXE."""
    if not getattr(sys, "frozen", False):
        return
    import types
    scripts   = Path(sys._MEIPASS) / "scripts"
    garmin_dir = scripts / "garmin"
    if garmin_dir.exists():
        sys.path.insert(0, str(garmin_dir))
    app_dir = scripts / "app"
    if app_dir.exists():
        sys.path.insert(0, str(app_dir))
    clients_dir = scripts / "clients"
    if clients_dir.exists():
        sys.path.insert(0, str(clients_dir))
    for pkg in ("context", "maps", "dashboards", "layouts"):
        pkg_dir = scripts / pkg
        if pkg_dir.exists() and pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__    = [str(pkg_dir)]
            mod.__package__ = pkg
            sys.modules[pkg] = mod


_register_embedded_packages()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore    import QTimer

from garmin_app_base import GarminApp as _GarminAppBase


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
    for sub in ("garmin", "maps", "dashboards", "layouts", "context"):
        candidate = base / sub / name
        if candidate.exists():
            return candidate
    return base / name


# ── Self-test (Netz 1 — Ladbarkeit) ─────────────────────────────────────────────

def _run_self_test() -> int:
    """
    Netz 1 — Ladbarkeit. Loads every module listed in
    build_manifest.SHARED_SCRIPTS directly from disk via
    importlib.util.spec_from_file_location() — the same technique already
    used by dash_runner._load_specialist() / dash_plotter_html_complex.
    _load_renderer(). Only the entry load bypasses normal import statements;
    any import *inside* a loaded module (e.g. 'from quality._maint import
    QUALITY_LOCK') still resolves via the real sys.path that
    _register_embedded_packages() sets up above — this exercises the actual
    runtime import machinery, not a parallel one.

    Called via '--self-test' before any GUI initialization. T3.1 is a
    --windowed build — sys.stdout may be unavailable; output is best-effort
    and never raises.

    Returns 0 if every module loaded, 1 on any failure (including if
    build_manifest.py itself cannot be loaded).
    """
    def _out(text: str) -> None:
        if sys.stdout is not None:
            try:
                print(text)
            except Exception:
                pass
        try:
            import garmin.garmin_config as _cfg
            _log_path = _cfg.LOG_DIR / "selftest_result.log"
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(text + "\n")
        except Exception:
            pass

    if getattr(sys, "frozen", False):
        base          = Path(sys._MEIPASS) / "scripts"
        manifest_path = base / "build_manifest.py"
    else:
        base          = Path(__file__).parent
        manifest_path = base / "compiler" / "build_manifest.py"

    try:
        _spec     = importlib.util.spec_from_file_location(
            "build_manifest", manifest_path)
        _manifest = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_manifest)
    except Exception as e:
        _out(f"✗ Self-test: cannot load build_manifest.py ({manifest_path}) — {e}")
        return 1

    def _import_family_submodule(rel_path: str):
        """
        Imports a real submodule of app/, context/, maps/, dashboards/, or
        layouts/ the way production code actually reaches it. Two import
        conventions coexist for files in these folders: most are imported
        flat by garmin_app_base.py (e.g. 'import garmin_app_settings'),
        but the six panel_*.py modules and dialogs.py are imported
        package-qualified ('from app.panel_archive import PanelArchive')
        because they use relative imports internally and need real
        __package__ context to resolve them.

        Tries flat first — matches most files in these folders — and
        falls back to the dotted '<folder>.<name>' form only if flat
        import fails. This adapts per file automatically instead of
        hardcoding which of the two conventions each specific file needs
        (that hardcoded assumption — 'everything under app/ is dotted' —
        was tried first and was wrong for exactly two files: found via a
        real --self-test run, not guessed).
        """
        parts       = rel_path[:-3].split("/")
        flat_name   = parts[-1]
        dotted_name = ".".join(parts)
        try:
            importlib.import_module(flat_name)
        except Exception as flat_err:
            try:
                importlib.import_module(dotted_name)
            except Exception as dotted_err:
                raise ImportError(
                    f"flat '{flat_name}' failed ({type(flat_err).__name__}: "
                    f"{flat_err}); dotted '{dotted_name}' failed "
                    f"({type(dotted_err).__name__}: {dotted_err})"
                ) from dotted_err

    failures = []
    for rel_path in _manifest.SHARED_SCRIPTS:
        parts   = rel_path[:-3].split("/")
        is_init = parts[-1] == "__init__"
        top     = parts[0]
        try:
            if not is_init and top in ("app", "context", "maps", "dashboards", "layouts"):
                # __init__.py stays on the file-path path deliberately —
                # the four virtual packages already have near-empty
                # stand-ins in sys.modules via _register_embedded_packages()
                # above; importing them by name would only hit that cache
                # and never execute their real file content.
                _import_family_submodule(rel_path)
            else:
                file_path = base / rel_path
                mod_name  = "_selftest_" + rel_path.replace("/", "_").replace(
                    "-", "_").replace(".py", "")
                spec = importlib.util.spec_from_file_location(mod_name, file_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"no loader for {file_path}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
        except Exception as e:
            tb = traceback.format_exc()
            failures.append(f"{rel_path}: {type(e).__name__}: {e}\n{tb}")

    if failures:
        _out(f"✗ Self-test: {len(failures)}/{len(_manifest.SHARED_SCRIPTS)} "
             f"module(s) failed to load:")
        for f in failures:
            _out(f"    {f}")
        return 1

    _out(f"✓ Self-test: all {len(_manifest.SHARED_SCRIPTS)} modules loaded successfully.")
    return 0


# ── Main application ───────────────────────────────────────────────────────────

class GarminApp(_GarminAppBase):

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

        def worker():
            self._running = True
            self._stop_event.clear()

            if enable_stop:
                self._dispatch(
                    lambda: self._panel_outputs._stop_btn.setEnabled(True))

            if days_left is not None:
                self._dispatch(
                    lambda dl=days_left:
                        self._panel_home._timer_btn.setText(
                            f"⏱  Syncing · {dl}/{dl}"))

            q          = self._log_queue
            q_writer   = _QueueWriter(q)
            q_handler  = _QueueHandler(q)
            q_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            import garmin_redact as _redact
            q_handler.addFilter(_redact.RedactFilter())
            old_stdout  = sys.stdout
            old_stderr  = sys.stderr
            root_logger = logging.getLogger()
            old_handlers = root_logger.handlers[:]
            old_level    = root_logger.level

            sys.stdout = q_writer
            sys.stderr = q_writer
            root_logger.handlers = [q_handler]
            root_logger.setLevel(
                getattr(logging,
                        self._panel_settings._log_level,
                        logging.INFO))

            success = False
            try:
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
                # Collector is the stop orchestrator — main() registers the
                # event with itself and garmin_api. No module.__dict__ injection.
                module.main(stop_event=effective_stop)
                success = not (
                    effective_stop is not None and effective_stop.is_set())

            except SystemExit as e:
                success = e.code in (None, 0)
                if not success and not (
                        stop_event is not None and stop_event.is_set()):
                    q.put(f"✗ Script exited with code {e.code}")
            except Exception as e:
                q.put(f"✗ Error in {script_name}: {e}")
                q.put(traceback.format_exc())
            finally:
                q_writer.flush()
                sys.stdout           = old_stdout
                sys.stderr           = old_stderr
                root_logger.handlers = old_handlers
                root_logger.setLevel(old_level)

                self._running = False
                if enable_stop:
                    self._dispatch(
                        lambda: self._panel_outputs._stop_btn.setEnabled(False))

                stopped = (
                    (stop_event is not None and stop_event.is_set()) or
                    self._stop_event.is_set()
                )
                if stopped:
                    q.put("✗ Stopped by user.")
                elif success:
                    q.put("✓ Done. — please update context")
                    if on_success:
                        q.put(on_success)

                if on_done:
                    q.put(on_done)

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
        """Drain the log queue into the GUI log widget. Reschedules itself.

        Queue items are either log-line strings or zero-arg callables
        (on_done/on_success from _run()). Callables are queued instead of
        dispatched directly so they run after any log lines already ahead
        of them — otherwise a callable dispatched via self._dispatch()
        (Qt queued signal, near-immediate) could overtake log lines still
        waiting on this 100ms poll, showing e.g. a "finished" callback
        message before the log lines that logically precede it.
        """
        try:
            while True:
                item = self._log_queue.get_nowait()
                if callable(item):
                    item()
                else:
                    self._log(item)
        except queue.Empty:
            pass
        QTimer.singleShot(100, self._poll_log_queue)


if __name__ == "__main__":
    # ── Netz 1 — Ladbarkeit: Selbsttest vor jeder GUI-Initialisierung ────────
    if "--self-test" in sys.argv:
        sys.exit(_run_self_test())

    import crash_handler
    from version import APP_VERSION
    crash_handler.install(app_version=APP_VERSION, exit_on_main=True)

    # ── Single instance guard ─────────────────────────────────────────────────
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    _INSTANCE_KEY = "GarminLocalArchive_Instance"
    _ping = QLocalSocket()
    _ping.connectToServer(_INSTANCE_KEY)
    if _ping.waitForConnected(300):
        _ping.disconnectFromServer()
        _qapp_check = QApplication(sys.argv)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(
            None,
            "Garmin Local Archive",
            "Garmin Local Archive is already running.\n\n"
            "Only one instance can run at a time.",
        )
        sys.exit(0)
    _ping = None

    _instance_server = QLocalServer()
    QLocalServer.removeServer(_INSTANCE_KEY)
    _instance_server.listen(_INSTANCE_KEY)
    # ── End single instance guard ─────────────────────────────────────────────

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")

    window = GarminApp()
    window.show()
    sys.exit(qapp.exec())
