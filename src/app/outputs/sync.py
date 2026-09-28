#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/sync.py
Garmin Local Archive — Sync Garmin + Live Fetch (highest external coupling)

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 7, last) —
verbatim except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps two delegating methods:
  - _run_collector(self, *, on_done=None) — SAME keyword signature, since
    panel_home.py's Daily Sync chain AND _build_ui()'s Sync-Garmin button
    both call it (confirmed by Grep).
  - _run_live_fetch(self) — called from panel_home.py (Update Live button)
    AND internally from run_collector()'s _internal_done (confirmed by Grep).
_check_raw_backfill_popup has no callers outside this module (only called
from run_collector itself), so it stays module-private — no delegate.

_stop_btn stays on PanelOutputs (E-7) — garmin_app.py and
garmin_app_standalone.py access panel._panel_outputs._stop_btn directly
(confirmed by Grep before Baustein 1), it is not touched by this module.
"""

import os
import threading
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

import frozen_paths


def _check_raw_backfill_popup(panel, s: dict) -> None:
    app = panel._app
    try:
        import importlib
        os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
        import garmin_backup as _backup
        import garmin_config as _cfg
        importlib.reload(_cfg)
        importlib.reload(_backup)
        count = _backup.check_raw_backfill_needed()
    except Exception:
        return

    if count == 0:
        app.settings["backup_raw_backfill_asked"] = True
        app._panel_settings._safe_save(app.settings)
        return

    answer = QMessageBox.question(
        app, "Raw Backup — New Feature",
        f"Garmin Local Archive v1.5.1 introduced automatic raw file backups.\n\n"
        f"{count} existing raw file(s) have no backup copy yet.\n\n"
        f"Create backups now? This runs in the background and does not\n"
        f"affect the sync. Completed months are stored as ZIP archives\n"
        f"in garmin_data/backup/raw/.\n\n"
        f"You can also skip this — new files will be backed up automatically\n"
        f"after every sync from now on.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    def _do_backfill():
        try:
            result = _backup.backfill_raw()
            app._log_bg(
                f"✓ Raw backup complete: {result['copied']} files backed up"
                + (f", {result['errors']} errors" if result["errors"] else "")
            )
        except Exception as e:
            app._log_bg(f"✗ Raw backup failed: {e}")

    app.settings["backup_raw_backfill_asked"] = True
    app._panel_settings._safe_save(app.settings)
    threading.Thread(target=_do_backfill, daemon=True).start()
    app._log("🗄  Raw backup running in background …")


def run_collector(panel, *, on_done=None):
    """Run connection test first (once per session), then start sync.

    on_done: optional callable, fired on the Main Thread after sync
             completes (after _refresh_archive_info). Used by Daily Sync
             chain in panel_home to sequence Context Sync afterwards.
    """
    app = panel._app

    s = app._panel_settings._collect_settings()
    if not s["email"] or not s["password"]:
        app._log("✗ Email or password missing.")
        return

    timer_was_active = app._timer_active
    if app._timer_active:
        app._log("⏱  Background timer paused for manual sync.")
        app._timer_stop.set()
        app._timer_active = False
        app._dispatch(
            app._panel_timer._timer_update_btn)

    if not app.settings.get("backup_raw_backfill_asked", False):
        _check_raw_backfill_popup(panel, s)

    refresh_failed = app._panel_archive._check_failed_days_popup(
        base_dir  = s["base_dir"],
        sync_mode = s["sync_mode"],
        sync_days = s["sync_days"],
        sync_from = s.get("sync_from", ""),
        sync_to   = s.get("sync_to", ""),
    )
    run_migration = app._panel_archive._check_schema_migration(
        base_dir=s["base_dir"])
    env_extra = {"GARMIN_SCHEMA_MIGRATE": "1"} if run_migration else {}

    def _internal_done():
        app._panel_timer._timer_resume_after_sync(timer_was_active)
        app._panel_archive._refresh_archive_info()
        run_live_fetch(panel)
        if on_done:
            on_done()

    if app._connection_verified:
        app._run(
            "garmin_collector.py", enable_stop=True,
            refresh_failed=refresh_failed,
            env_overrides=env_extra,
            on_done=_internal_done,
        )
        return

    app._panel_connection._run_connection_test(
        on_success=lambda: app._run(
            "garmin_collector.py", enable_stop=True,
            refresh_failed=refresh_failed,
            env_overrides=env_extra,
            on_done=_internal_done,
        ))


def run_live_fetch(panel):
    """Fetch + render Live Tracking in a background thread after Sync
    Garmin (GUI path only — daily_update.py/T3.2 deliberately excluded,
    a headless run has no one watching a "live" view).

    Fire-and-forget: any failure here (login unavailable, specialist
    missing, render error) is logged and swallowed — Live Tracking is a
    non-critical, best-effort feature and must never affect the rest of
    the Sync Garmin chain.
    """
    app = panel._app

    def worker():
        try:
            s = app._panel_settings._collect_settings()
            os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")

            root = frozen_paths.scripts_root()
            frozen_paths.add_to_path(
                root, "garmin", "dashboards", "layouts", "maps")

            import importlib
            import garmin_config as _cfg
            importlib.reload(_cfg)
            import garmin_live_fetch
            importlib.reload(garmin_live_fetch)

            def _on_state(key, state):
                pc = app._panel_connection
                app._dispatch(lambda: pc._set_indicator(key, state))

            result = garmin_live_fetch.fetch_live(
                progress=lambda msg: app._log_bg(f"  {msg}"),
                state_cb=_on_state)

            if not result.get("ok"):
                app._log_bg(
                    "ℹ  Live Tracking: fetch skipped (login unavailable)")
                return

            import importlib.util as _ilu
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)

            specialists = dash_runner.scan()
            live_spec = next(
                (sp for sp in specialists if sp["name"] == "Live Tracking"),
                None)
            if live_spec is None:
                app._log_bg(
                    "ℹ  Live Tracking: specialist not found")
                return

            out_dir = Path(s["base_dir"]) / "dashboards"
            out_dir.mkdir(parents=True, exist_ok=True)

            results = dash_runner.build(
                selections=[(live_spec["module"], "html")],
                date_from="", date_to="",
                settings=s, output_dir=out_dir,
            )
            ok_result = next((r for r in results if r.get("success")), None)
            if ok_result:
                app._dispatch(
                    lambda: app._scan_dashboards(
                        auto_load=str(ok_result["file"])))
                app._log_bg("✓ Live Tracking updated")
            else:
                err = results[0].get("error", "unknown") if results else "no result"
                app._log_bg(f"ℹ  Live Tracking render skipped: {err}")
        except Exception as exc:
            app._log_bg(f"ℹ  Live Tracking update skipped: {exc}")

    threading.Thread(target=worker, daemon=True).start()
