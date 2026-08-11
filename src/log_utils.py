#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
log_utils.py

Leaf-Node. Shared logging helper with no project-module dependency — same
category as frozen_paths.py, crash_handler.py, qwebengine_hardening.py,
all living in this same src/-Root.

Currently one function: with_timestamp() — prefixes messages passed
through a log callback with a timestamp, matching the format
logging.Formatter uses everywhere else in the project
("%Y-%m-%d %H:%M:%S"). Introduced in v1.6.6.1 to fix inconsistent console
output between the Garmin page (logging module, timestamped
automatically) and the Context/Dashboard pipeline (log_callback(str), no
timestamp) — see ROADMAP.md v1.6.6.1 Punkt 3.
"""

from datetime import datetime


def with_timestamp(log_fn):
    """
    Wraps a log callback so every message gets a timestamp prefix,
    matching logging.Formatter's "%Y-%m-%d %H:%M:%S" used elsewhere.

    Pass-through: if log_fn is None (no callback registered — e.g.
    headless), returns None unchanged. Callers keep their existing
    `if log is None: ...` guards without extra None-checks here.
    """
    if log_fn is None:
        return None

    def _wrapped(msg: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_fn(f"{ts}  {msg}")

    return _wrapped