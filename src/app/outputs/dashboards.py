#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/outputs/dashboards.py
Garmin Local Archive — All-dashboards build (used by Daily Sync chain)

Extracted from app/panel_outputs.py (v1.7.3.1, Baustein 5) — verbatim
except self -> panel, same shape as app/outputs/output_helpers.py.

panel_outputs.py keeps a one-line delegating method with the SAME keyword
signature (_run_all_dashboards(self, *, on_done=None) ->
dashboards.run_all_dashboards(self, on_done=on_done)) — required here,
unlike the earlier Bausteine, because panel_home.py's Daily Sync chain
calls panel._run_all_dashboards(on_done=...) directly from outside
panel_outputs.py (confirmed by Grep before this Baustein).
"""

import os
import threading
from datetime import date, timedelta
from pathlib import Path

import frozen_paths


def run_all_dashboards(panel, *, on_done=None):
    """Build all specialists / all formats — no dialog, no date filter.

    Mirrors daily_update._run_dashboards(): scans all specialists, selects
    all formats, uses the full archive date range from summary/*.json.
    Fires on_done on the Main Thread when complete (success or error).
    """
    import importlib.util as _ilu

    app = panel._app

    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "dashboards", "layouts", "maps")

    try:
        runner_path = root / "dashboards" / "dash_runner.py"
        spec = _ilu.spec_from_file_location("dash_runner", runner_path)
        if spec is None:
            raise FileNotFoundError(f"dash_runner.py not found: {runner_path}")
        dash_runner = _ilu.module_from_spec(spec)
        spec.loader.exec_module(dash_runner)
    except Exception as exc:
        app._log(f"✗ Dashboard runner could not be loaded: {exc}")
        if on_done:
            on_done()
        return

    try:
        specialists = dash_runner.scan()
    except Exception as exc:
        app._log(f"✗ Dashboard scan failed: {exc}")
        if on_done:
            on_done()
        return

    if not specialists:
        app._log("ℹ  No dashboard specialists found — skipping.")
        if on_done:
            on_done()
        return

    selections = [
        (spec["module"], fmt)
        for spec in specialists
        for fmt in spec["formats"]
    ]

    # Full archive date range — same logic as daily_update
    s         = app._panel_settings._collect_settings()
    base      = Path(s["base_dir"])
    summary_dir = base / "garmin_data" / "summary"
    dates = sorted(
        f.stem.replace("garmin_", "")
        for f in summary_dir.glob("garmin_???-??-??.json")
    ) if summary_dir.exists() else []
    today     = date.today()
    date_from = dates[0]  if dates else (today - timedelta(days=90)).isoformat()
    date_to   = dates[-1] if dates else today.isoformat()

    output_dir = base / "dashboards"
    output_dir.mkdir(parents=True, exist_ok=True)

    app._log("\n▶  Daily Sync — building dashboards ...")
    app._log(f"   Range: {date_from} → {date_to}")
    _chain_done = on_done

    def worker():
        try:
            import importlib
            os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
            import garmin_config as _cfg
            importlib.reload(_cfg)
            results = dash_runner.build(
                selections=selections,
                date_from=date_from,
                date_to=date_to,
                settings=s,
                output_dir=output_dir,
                log=lambda msg: app._dispatch(
                    lambda m=msg: app._log(f"   {m}")),
            )

            def _finish():
                ok  = [r for r in results if r["success"]]
                err = [r for r in results if not r["success"]]
                app._log(f"\n  ✓ {len(ok)} dashboard(s) built")
                for r in err:
                    app._log(
                        f"  ✗ {r['name']} ({r['format']}): "
                        f"{r.get('error', '')}")
                if ok:
                    last_html = next(
                        (r.get("path") for r in ok
                         if r.get("format") == "html"), None)
                    if last_html:
                        app._last_html = str(last_html)
                    app._scan_dashboards(
                        auto_load=app._last_html)
                    app._scan_xlsx_files()
                try:
                    import garmin_mobile_landing as _landing
                    _landing.write_index_html(s["base_dir"])
                except Exception:
                    pass
                if _chain_done:
                    _chain_done()

            app._dispatch(_finish)
        except Exception as exc:
            def _err(e=exc):
                app._log(f"  ✗ Dashboard build error: {e}")
                if _chain_done:
                    _chain_done()
            app._dispatch(_err)

    threading.Thread(target=worker, daemon=True).start()
