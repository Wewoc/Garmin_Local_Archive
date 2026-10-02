#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/_export_build.py
Garmin Local Archive — shared export build engine

Background-thread build backend for export_data.py, same shape as
_dashboard_build.py's run_dashboards() — not a popup itself (no
open_popup()), just the worker-thread + logging tail the popup calls
into once the dialog is confirmed.
"""

import os
import threading
from datetime import date, timedelta
from pathlib import Path


def run_export(panel, export_runner, selections, output_path):
    """
    Run export build in a background thread, stream progress to the log.

    Args:
        panel:          Owning PanelOutputs instance.
        export_runner:  Loaded exports/export_runner.py module.
        selections:     List of (adapter_module, domains, include_metadata,
                        options) tuples — see export_data.py / export_runner.build().
        output_path:    Directory to write output files into (from the
                        popup's path field, defaults to base_dir/export).
    """
    s = panel._app._panel_settings._collect_settings()

    # Export Data always covers the full archive — deliberately NOT the
    # Settings tab's "Export Dashboard Range" field (date_from/date_to),
    # which is scoped to Excel/dashboard export and defaults to a 30-day
    # window. Same full-archive detection as daily_update.py::_run_export().
    base = Path(s["base_dir"])
    summary_dir = base / "garmin_data" / "summary"
    dates = sorted(
        f.stem.replace("garmin_", "")
        for f in summary_dir.glob("garmin_????-??-??.json")
    ) if summary_dir.exists() else []

    today = date.today()
    date_from = dates[0]  if dates else (today - timedelta(days=90)).isoformat()
    date_to   = dates[-1] if dates else today.isoformat()

    output_path.mkdir(parents=True, exist_ok=True)

    panel._app._log("\n▶  Export Data ...")
    panel._app._log(f"   Output: {output_path}")
    panel._app._log(f"   Zeitraum: {date_from} → {date_to}")

    def worker():
        try:
            import importlib
            os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
            import garmin_config as _cfg
            importlib.reload(_cfg)
            results = export_runner.build(
                selections=selections,
                date_from=date_from,
                date_to=date_to,
                output_dir=output_path,
                log=lambda msg: panel._app._dispatch(
                    lambda m=msg: panel._app._log(f"   {m}")),
            )

            def on_done():
                ok  = [r for r in results if r["success"]]
                err = [r for r in results if not r["success"]]
                panel._app._log(f"\n  ✓ {len(ok)} Export(s) erstellt")
                for r in err:
                    panel._app._log(f"  ✗ {r['name']}: {r.get('error', '')}")
                if ok:
                    os.startfile(str(output_path))

            panel._app._dispatch(on_done)
        except Exception as exc:
            panel._app._dispatch(
                lambda e=exc: panel._app._log(f"  ✗ Fehler: {e}"))

    threading.Thread(target=worker, daemon=True).start()
