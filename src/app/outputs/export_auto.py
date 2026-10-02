#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/export_auto.py
Garmin Local Archive — Export Data auto-run (used by Daily Sync chain)

Runs the saved Export Data selection (v1.7.4 "export_auto_run" setting,
set via the Export Data popup's "Save & Add to Daily Sync" button) from
the GUI's "Daily Sync" button chain — same role as daily_update.py's
_run_export() plays for the headless Task Scheduler entry point, kept
as a separate module since the GUI path needs threading/_dispatch()
instead of a blocking call (same split as dashboards.py vs.
daily_update.py's _run_dashboards()).

panel_outputs.py keeps a one-line delegating method with the SAME
keyword signature (_run_export_auto(self, *, on_done=None)), since
panel_home.py's Daily Sync chain calls this from outside
panel_outputs.py (same pattern as _run_all_dashboards).
"""

import os
import threading
from datetime import date, timedelta
from pathlib import Path

import frozen_paths


def run_export_auto(panel, *, on_done=None):
    """Run the saved Export Data selection, if any. No-op if the
    "Save & Add to Daily Sync" button was never used (export_auto_run
    not enabled) — fires on_done immediately, no log output.

    Never raises into the Daily Sync chain: like daily_update.py's
    _run_export(), a failure here is logged but does not stop the
    chain, since Export Data is an optional convenience, not a core
    archive step.
    """
    app = panel._app
    s = app._panel_settings._collect_settings()
    cfg = s.get("export_auto_run") or {}

    if not cfg.get("enabled"):
        if on_done:
            on_done()
        return

    import importlib.util as _ilu

    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "exports", "maps")

    try:
        runner_path = root / "exports" / "export_runner.py"
        spec = _ilu.spec_from_file_location("export_runner", runner_path)
        if spec is None:
            raise FileNotFoundError(f"export_runner.py not found: {runner_path}")
        export_runner = _ilu.module_from_spec(spec)
        spec.loader.exec_module(export_runner)
    except Exception as exc:
        app._log(f"✗ Export runner could not be loaded: {exc}")
        if on_done:
            on_done()
        return

    try:
        by_id = {a["id"]: a["module"] for a in export_runner.scan()}
    except Exception as exc:
        app._log(f"✗ Export scan failed: {exc}")
        if on_done:
            on_done()
        return

    selections = []
    for entry in cfg.get("selections", []):
        adapter_id = entry.get("adapter")
        mod = by_id.get(adapter_id)
        if mod is None:
            app._log(f"  Adapter '{adapter_id}' not found — skipping "
                      f"(saved selection may reference a removed adapter)")
            continue
        selections.append((mod, entry.get("domains", []), entry.get("metadata", False),
                           entry.get("options", {})))

    if not selections:
        app._log("ℹ  No valid adapters in saved Export Data selection — skipping.")
        if on_done:
            on_done()
        return

    output_dir = Path(cfg.get("path") or (Path(s["base_dir"]) / "export"))

    base = Path(s["base_dir"])
    summary_dir = base / "garmin_data" / "summary"
    dates = sorted(
        f.stem.replace("garmin_", "")
        for f in summary_dir.glob("garmin_????-??-??.json")
    ) if summary_dir.exists() else []
    today     = date.today()
    date_from = dates[0]  if dates else (today - timedelta(days=90)).isoformat()
    date_to   = dates[-1] if dates else today.isoformat()

    app._log("\n▶  Daily Sync — running Export Data ...")
    app._log(f"   Output: {output_dir}")
    _chain_done = on_done

    def worker():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            import importlib
            os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
            import garmin_config as _cfg
            importlib.reload(_cfg)
            results = export_runner.build(
                selections=selections,
                date_from=date_from,
                date_to=date_to,
                output_dir=output_dir,
                log=lambda msg: app._dispatch(
                    lambda m=msg: app._log(f"   {m}")),
            )

            def _finish():
                ok  = [r for r in results if r.get("success")]
                err = [r for r in results if not r.get("success")]
                app._log(f"\n  ✓ {len(ok)}/{len(results)} export(s) built")
                for r in err:
                    app._log(f"  ✗ {r['name']}: {r.get('error', 'unknown')}")
                if _chain_done:
                    _chain_done()

            app._dispatch(_finish)
        except Exception as exc:
            def _err(e=exc):
                app._log(f"  ✗ Export Data build error: {e}")
                if _chain_done:
                    _chain_done()
            app._dispatch(_err)

    threading.Thread(target=worker, daemon=True).start()
