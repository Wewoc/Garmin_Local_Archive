#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/context_check.py
Garmin Local Archive — Context-Archive Check (v1.7.2.3 Baustein 4)

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 4) — verbatim
except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps a one-line delegating method (_on_context_check ->
context_check.on_context_check(self)) so _build_ui()'s button wiring needs
zero changes. The other three functions here (_reset_context_check_btn,
_open_context_check_dialog, _reset_after_coordinate_fix) have no callers
outside this module (verified by Grep before this Baustein), so they stay
module-private — no delegate needed on PanelOutputs for them.
"""

import threading

from PyQt6.QtWidgets import QMessageBox, QDialog

import frozen_paths
from ..dialog_context_check import ContextCheckResultDialog, ContextCoordinateFixDialog


def on_context_check(panel):
    """Runs context_silo_check.check_context_archive() in a background
    thread — a full pass reads every context_data/ file individually
    for the coordinate check (~35s on a multi-year archive), so this
    must never run on the Main Thread. Same precondition guards as
    force_refetch.on_force_refetch() above."""
    app = panel._app

    if app._is_running():
        QMessageBox.warning(app, "Context-Check",
            "A Garmin sync is currently running.\nPlease wait until it finishes.")
        return
    if app._ctx_running:
        QMessageBox.warning(app, "Context-Check",
            "Context sync is running.\nPlease wait until it finishes.")
        return

    s = app._panel_settings._collect_settings()
    base_dir = s.get("base_dir", "")
    if not base_dir:
        app._log("✗ Context-Check: no data folder set.")
        return
    try:
        default_lat = float(s.get("context_latitude") or 0.0)
        default_lon = float(s.get("context_longitude") or 0.0)
    except (TypeError, ValueError):
        default_lat = default_lon = 0.0

    panel._context_check_btn.setEnabled(False)
    panel._context_check_btn.setText("🧭  Checking…")
    app._log("🧭  Context-Check started …")

    def _do_check():
        try:
            root = frozen_paths.scripts_root()
            frozen_paths.add_to_path(root)
            from context import context_silo_check
            result = context_silo_check.check_context_archive(
                base_dir, default_lat=default_lat, default_lon=default_lon)
        except Exception as e:
            app._log_bg(f"✗ Context-Check failed: {e}")
            app._dispatch(lambda: _reset_context_check_btn(panel))
            return

        def _show_result():
            _reset_context_check_btn(panel)
            total_missing = sum(len(v) for v in result["missing_days"].values())
            app._log(
                f"🧭  Context-Check complete — {total_missing} missing, "
                f"{len(result['bad_coordinates'])} bad coordinate(s)")
            _open_context_check_dialog(panel, result, base_dir)

        app._dispatch(_show_result)

    threading.Thread(target=_do_check, daemon=True).start()


def _reset_context_check_btn(panel):
    """Main Thread only."""
    panel._context_check_btn.setEnabled(True)
    panel._context_check_btn.setText("🧭  Context-Check")


def _open_context_check_dialog(panel, result: dict, base_dir: str):
    """Main Thread only — opens the result dialog, and on "Koordinaten
    korrigieren" the follow-up fix dialog, chaining exec() calls the
    same way force_refetch.on_force_refetch() chains its preview/review
    dialogs."""
    app = panel._app

    dlg = ContextCheckResultDialog(parent=panel, result=result)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    fix_dlg = ContextCoordinateFixDialog(parent=panel, findings=result["bad_coordinates"])
    if fix_dlg.exec() != QDialog.DialogCode.Accepted:
        return
    fixes = fix_dlg.get_fixes()
    if not fixes:
        return

    # Re-checked here, not just at on_context_check()'s start — the
    # ~35s read-only scan plus two modal dialogs is a long enough
    # window for a Sync Context run to have started in the meantime.
    # context_data/ has exactly one writer (context_writer.py, used
    # by both context_collector.run() and context_silo_repair.py) —
    # the GUI's existing convention is one write operation at a time,
    # via the shared _ctx_running flag every other context-touching
    # action (on_force_refetch, _on_silo_check, _on_mirror) already
    # checks. This fix keeps that convention rather than introducing
    # a second, parallel guard.
    if app._ctx_running:
        QMessageBox.warning(app, "Context-Check",
            "Context sync is running.\nPlease try the coordinate fix again afterwards.")
        return

    app._ctx_running = True
    panel._context_check_btn.setEnabled(False)
    panel._ctx_btn.setEnabled(False)

    def _do_fix():
        try:
            app._log_bg(
                f"📍  Koordinaten-Korrektur gestartet — {len(fixes)} Tag(e) "
                f"werden mit korrigierter Koordinate neu abgerufen …")
            root = frozen_paths.scripts_root()
            frozen_paths.add_to_path(root)
            from context import context_silo_repair
            repair_result = context_silo_repair.fix_coordinates(base_dir, fixes)
            for item in repair_result["items"]:
                if item["status"] == "error":
                    app._log_bg(
                        f"    ✗ {item['date']} {item['source']}: {item['reason']}")
            app._log_bg(
                f"📍  Koordinaten-Korrektur fertig: {repair_result['ok']} behoben, "
                f"{repair_result['failed']} Fehler")
        finally:
            app._dispatch(lambda: _reset_after_coordinate_fix(panel))

    threading.Thread(target=_do_fix, daemon=True).start()


def _reset_after_coordinate_fix(panel):
    """Main Thread only."""
    panel._app._ctx_running = False
    panel._context_check_btn.setEnabled(True)
    panel._ctx_btn.setEnabled(True)
