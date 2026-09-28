#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/context_sync.py
Garmin Local Archive — Context Sync (weather + pollen)

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 6) — verbatim
except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps three one-line delegating methods:
  - _run_context_sync(self, *, on_done=None) — SAME keyword signature,
    since panel_home.py's Daily Sync chain calls this from outside
    panel_outputs.py with on_done=... (confirmed by Grep).
  - _stop_context_sync(self) / _on_context_sync_done(self) — both called
    directly as panel._method() in tests/test_qt_app.py::TestPanelOutputs
    (confirmed by Grep), so both need delegates too, unlike the
    module-private helpers in context_check.py (Baustein 4).
"""

import threading

from PyQt6.QtWidgets import QMessageBox

import frozen_paths


def run_context_sync(panel, *, on_done=None):
    """Run context collect (weather + pollen) in background thread.

    on_done: optional callable, fired on the Main Thread after context
             sync completes. Used by Daily Sync chain in panel_home to
             sequence dashboard build afterwards.
    """
    app = panel._app

    s = app._panel_settings._collect_settings()
    if (float(s.get("context_latitude",  "0.0")) == 0.0 and
            float(s.get("context_longitude", "0.0")) == 0.0):
        QMessageBox.warning(
            app, "Location not configured",
            "Please set a location in Settings before running Context Sync.\n"
            "Use the Settings panel to enter coordinates."
        )
        if on_done:
            on_done()
        return

    panel._ctx_btn.setEnabled(False)
    panel._ctx_stop_btn.setEnabled(True)
    app._context_stop_event = threading.Event()
    app._ctx_running        = True
    _chain_done = on_done

    def run():
        try:
            _root = frozen_paths.scripts_root()
            frozen_paths.add_to_path(_root)
            from context import context_collector
            result  = context_collector.run(
                settings=s,
                stop_event=app._context_stop_event,
                log_callback=app._log_bg,
            )
            plugins = result.get("plugins", {})
            lines   = ["Context sync complete"]
            for name, stats in plugins.items():
                lines.append(
                    f"{name.capitalize():<10}{stats.get('written', 0)} written")
            msg = "\n".join(lines)
            if result.get("error"):
                msg = f"Error: {result['error']}"
            app._dispatch(lambda m=msg: app._log(m))
        except Exception as exc:
            app._dispatch(
                lambda e=exc: app._log(f"Context sync error: {e}"))
        finally:
            def _finish():
                on_context_sync_done(panel)
                if _chain_done:
                    _chain_done()
            app._dispatch(_finish)

    threading.Thread(target=run, daemon=True).start()


def stop_context_sync(panel):
    panel._app._context_stop_event.set()


def on_context_sync_done(panel):
    panel._ctx_btn.setEnabled(True)
    panel._ctx_stop_btn.setEnabled(False)
    panel._app._ctx_running = False
