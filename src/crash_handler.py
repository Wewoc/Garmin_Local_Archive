#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
crash_handler.py
Garmin Local Archive — Global Crash / Uncaught-Exception Capture

Leaf-Node: no project imports (stdlib only). PyQt6 is imported lazily and
optionally inside install(), so this module is safe to use from headless
entry points (daily_update.py) as well as from the GUI. The caller passes
app_version — this module never imports version.py.

Capture surfaces (see NOTES v1.6.0.4.3 / decision D-6):
  (a) sys.excepthook         — uncaught exceptions on the main thread
  (b) threading.excepthook   — uncaught exceptions in threading.Thread workers
  (d) qInstallMessageHandler — Qt-native fatal/critical messages (optional)
QThread (c) is intentionally NOT covered — GLA uses threading.Thread only (D-3).
A true native segfault stays outside Python's reach — acknowledged limit.

Crash logs are written to a FIXED LOCAL path, deliberately NOT under the
configurable base_dir/garmin_data/log/ tree: a crash may itself be caused by
base_dir being unwritable/unreachable, so the crash logger must not depend on it.

Behaviour:
  main thread   → write crash log, flush, best-effort visible message, exit(1)
  worker thread → write crash log (file only — D-5: never touch widgets), let die
"""

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

APP_NAME      = "GarminLocalArchive"
CRASH_LOG_MAX = 30          # rolling cap — analogous to LOG_RECENT_MAX / LOG_DAILY_MAX

_state = {
    "dir":          None,
    "version":      "unknown",
    "exit_on_main": True,
    "installed":    False,
}


def _resolve_crash_dir(explicit=None):
    """Fixed local crash dir. LOCALAPPDATA (per-user, always writable) → TEMP → cwd."""
    if explicit:
        d = Path(explicit)
    else:
        base = os.environ.get("LOCALAPPDATA")
        if base:
            d = Path(base) / APP_NAME / "crash"
        else:
            base = os.environ.get("TEMP") or os.environ.get("TMP")
            d = (Path(base) / APP_NAME / "crash") if base else (Path.cwd() / "crash")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path.cwd()
    return d


def _prune(d):
    """Keep at most CRASH_LOG_MAX crash logs — oldest removed first."""
    try:
        logs = sorted(d.glob("crash_*.log"))
        for old in logs[:-CRASH_LOG_MAX]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _write(header, body):
    d = _state["dir"] or _resolve_crash_dir()
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    path = d / f"crash_{ts}.log"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== Garmin Local Archive — crash log ===\n")
            f.write(f"time     : {datetime.now().isoformat(timespec='seconds')}\n")
            f.write(f"version  : {_state['version']}\n")
            f.write(f"{header}\n")
            f.write("-" * 60 + "\n")
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        return None
    _prune(d)
    return path


def _notify_best_effort(path):
    """Best-effort visible message on the main thread. Never raises.
    The file log is the guarantee; this dialog is optional."""
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Garmin Local Archive",
                "An unexpected error occurred and the application must close.\n\n"
                f"Crash log:\n{path}",
            )
    except Exception:
        pass


def _sys_hook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    path = _write("thread   : MainThread (sys.excepthook)", tb)
    try:
        sys.stderr.write(tb)
        sys.stderr.flush()
    except Exception:
        pass
    _notify_best_effort(path)
    if _state["exit_on_main"]:
        os._exit(1)


def _thread_hook(args):
    if issubclass(args.exc_type, SystemExit):
        return
    tb = "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback))
    tname = args.thread.name if args.thread else "unknown"
    _write(f"thread   : {tname} (threading.excepthook)", tb)
    try:
        sys.stderr.write(tb)
        sys.stderr.flush()
    except Exception:
        pass
    # worker thread: file only, no widgets (D-5). GUI stays alive.


def _qt_message_handler(mode, context, message):
    try:
        from PyQt6.QtCore import QtMsgType
        if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
            _write(f"source   : Qt ({mode})", str(message))
    except Exception:
        pass


def install(log_dir=None, app_version="unknown",
            exit_on_main=True, install_qt_handler=True):
    """Install global crash capture. Idempotent. Call once, early, before QApplication."""
    if _state["installed"]:
        return
    _state["dir"]          = _resolve_crash_dir(log_dir)
    _state["version"]      = app_version
    _state["exit_on_main"] = exit_on_main

    sys.excepthook       = _sys_hook
    threading.excepthook = _thread_hook

    if install_qt_handler:
        try:
            from PyQt6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(_qt_message_handler)
        except Exception:
            pass

    _state["installed"] = True
