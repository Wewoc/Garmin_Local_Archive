#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/force_refetch.py
Garmin Local Archive — Force Refetch (calendar dialog + preview/review/commit)

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 3) — verbatim
except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps a one-line delegating method (_on_force_refetch ->
force_refetch.on_force_refetch(self)) so _build_ui()'s button wiring needs
zero changes.
"""

import os
import threading

from PyQt6.QtWidgets import QMessageBox, QDialog

from ..dialog_force_refetch import (
    ForceRefetchDialog, ForceRefetchProgressDialog, ForceRefetchReviewDialog,
)


def on_force_refetch(panel):
    """Opens the Force-Refetch calendar dialog (v1.7.1.7, Baustein 5).

    Only opens the dialog and reads the selection back — the dialog's
    own Start button is still a stub (see dialog_force_refetch.py),
    so exec() cannot yet return Accepted from a real confirmed run.
    Wiring run_force_refetch_preview() + the comparison/commit flow
    to this handler is a separate, later Bauauftrag step.
    """
    app = panel._app

    # ── Preconditions — same pattern as _on_mirror()/_on_silo_check() ──────
    if app._is_running():
        QMessageBox.warning(app, "Force Refetch",
            "A Garmin sync is currently running.\nPlease wait until it finishes.")
        return
    if app._timer_active:
        QMessageBox.warning(app, "Force Refetch",
            "Background timer is active.\nStop the timer before running Force Refetch.")
        return
    if app._ctx_running:
        QMessageBox.warning(app, "Force Refetch",
            "Context sync is running.\nPlease wait until it finishes.")
        return

    s = app._panel_settings._collect_settings()
    quality_by_date = app._panel_archive._get_quality_by_date(
        base_dir=s["base_dir"])

    dlg = ForceRefetchDialog(parent=panel, quality_by_date=quality_by_date)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    selected_dates = dlg.get_selected_dates()
    if not selected_dates:
        return

    # ── Timer pause — held for the whole interaction (preview + wait +
    # commit), same convention as documented in START_PROMPT/GLA_HANDBUCH
    # §10 for Background-Timer vs. manual actions on raw/+summary/. ──────
    timer_was_active = app._timer_active
    if app._timer_active:
        app._log("⏱  Background timer paused for Force Refetch.")
        app._timer_stop.set()
        app._timer_active = False
        app._dispatch(app._panel_timer._timer_update_btn)

    progress_dlg = ForceRefetchProgressDialog(parent=panel, dates=selected_dates)
    stop_event = threading.Event()

    def _log_to_progress(text: str):
        app._dispatch(lambda t=text: progress_dlg.append_log(t))

    def _on_stop_clicked():
        stop_event.set()
    progress_dlg.stop_requested.connect(_on_stop_clicked)

    def _worker():
        # ── Root-logger redirect (same technique as garmin_app_standalone.py's
        # _QueueHandler/root_logger.handlers swap) — every log.info()/
        # log.warning() from garmin_collector, garmin_api, garmin_validator,
        # etc. during the preview run appears in the progress dialog, not
        # just our own two-line-per-day summary. RedactFilter is mandatory
        # here for the same reason it's mandatory there: an error message
        # could otherwise leak a credential value into the visible log. ──
        import logging as _logging
        import garmin_redact as _redact

        class _DialogLogHandler(_logging.Handler):
            def __init__(self, emit_fn):
                super().__init__()
                self._emit_fn = emit_fn
            def emit(self, record):
                self._emit_fn(self.format(record))

        q_handler = _DialogLogHandler(_log_to_progress)
        q_handler.setFormatter(_logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        q_handler.addFilter(_redact.RedactFilter())
        root_logger  = _logging.getLogger()
        old_handlers = root_logger.handlers[:]
        old_level    = root_logger.level
        root_logger.handlers = [q_handler]
        # DEBUG (not INFO) — surfaces api_call()'s per-endpoint
        # "Fetching {label} ..." line (garmin_api.py, v1.7.1.7) so the
        # progress dialog shows real activity instead of going quiet
        # for the ~30-60s a day's fetch loop takes. Scoped to this
        # worker's own temporary handler only — the normal Sync Garmin
        # log elsewhere keeps whatever level panel_settings._log_level
        # is set to, unaffected by this.
        root_logger.setLevel(_logging.DEBUG)

        # File log — Force-Refetch's own rolling log on disk (v1.7.1.7),
        # same convention as every other GLA log (session/daily/mcp).
        # Added as a SECOND handler alongside q_handler above, not a
        # replacement — the dialog needs live text, the file needs a
        # permanent record, both from the exact same log calls.
        import garmin_collector as _collector_for_log
        _ffr_fh, _ffr_log_path = _collector_for_log._start_force_refetch_log()

        try:
            import garmin_config as _cfg
            os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
            os.environ["GARMIN_EMAIL"]      = s.get("email", "")
            os.environ["GARMIN_PASSWORD"]   = s.get("password", "")
            os.environ["GARMIN_SESSION_LOG_PREFIX"] = "force_refetch"
            import importlib
            importlib.reload(_cfg)

            import garmin_collector as _collector
            _collector.set_stop_event(stop_event)

            _log_to_progress("Logging in to Garmin Connect ...")
            import garmin_api
            pc = app._panel_connection
            try:
                client = garmin_api.login(
                    on_key_required  = pc._prompt_enc_key,
                    on_token_expired = pc._prompt_token_expired,
                    on_mfa_required  = pc._prompt_mfa,
                )
            except garmin_api.GarminLoginError as e:
                _log_to_progress(f"✗ Login failed: {e}")
                return
            if client is None:
                _log_to_progress("✗ Login cancelled.")
                return

            _log_to_progress(f"Fetching {len(selected_dates)} day(s) ...")
            results = _collector.run_force_refetch_preview(client, selected_dates)

            for entry in results:
                if entry.get("error") is not None:
                    _log_to_progress(f"  ✗ {entry['date']}: {entry['error']}")
                else:
                    _log_to_progress(
                        f"  {entry['date']}: {entry['quality_before']} → "
                        f"{entry['quality_after']} "
                        f"| {len(entry['fields_changed'])} field(s) changed")

            _log_to_progress("✓ Preview complete.")
            preview_results[:] = results

        except Exception as e:
            _log_to_progress(f"✗ Force Refetch failed: {e}")
        finally:
            root_logger.handlers = old_handlers
            root_logger.setLevel(old_level)
            _collector_for_log._close_force_refetch_log(_ffr_fh)
            import garmin_collector as _collector
            _collector.set_stop_event(None)
            app._dispatch(lambda: (
                progress_dlg.close(),
                app._panel_timer._timer_resume_after_sync(timer_was_active),
            ))

    preview_results = []
    preview_thread = threading.Thread(target=_worker, daemon=True)
    preview_thread.start()
    progress_dlg.exec()
    preview_thread.join()

    if not preview_results:
        # Empty on Stop before the first day, or a top-level failure
        # already logged by _worker()'s except-block — nothing to review.
        return

    review_dlg = ForceRefetchReviewDialog(parent=panel, results=preview_results)
    if review_dlg.exec() != QDialog.DialogCode.Accepted:
        app._log("  Force Refetch: review cancelled — no changes committed.")
        return
    confirmed_dates = review_dlg.get_confirmed_dates()

    import garmin_collector as _collector_for_commit
    import garmin_quality as _quality

    with _quality.QUALITY_LOCK:
        quality_data = _quality._load_quality_log()
        commit_results = _collector_for_commit.commit_force_refetch(
            preview_results, confirmed_dates, quality_data)
        _quality._save_quality_log(quality_data)

    for entry in commit_results:
        action = entry["action"]
        if action == "committed":
            app._log(f"  ✓ {entry['date']}: committed")
        elif action == "reverted":
            app._log(f"  ↺ {entry['date']}: reverted")
        else:
            app._log(f"  ✗ {entry['date']}: {entry.get('error', 'error')}")

    app._panel_archive._refresh_archive_info()
