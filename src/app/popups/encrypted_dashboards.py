#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/encrypted_dashboards.py
Garmin Local Archive — Encrypted Dashboards popup

Extracted from app/panel_outputs.py (Codereview v1.7.0.1, Baustein 1.4)
— the "Encrypted Dashboards" button's password dialog + full-specialist-
scan flow, verbatim except self -> panel, split into open_popup()
(GUI) and _run() (gathers dash_runner/selections/dates, then delegates
the actual build/encrypt/report work to the shared
app/popups/_dashboard_build.py::run_encrypted() — see that module's
docstring for why this split exists: custom_dashboard.py's encrypt
branch calls the same run_encrypted(), so neither popup file imports
the other, both depend only on the shared engine).

panel_outputs.py keeps a one-line delegating method
(_open_encrypted_dashboard_popup -> popups.encrypted_dashboards.open_popup(self))
so _build_ui()'s button wiring needs zero changes.
"""

from PyQt6.QtWidgets import QDialog

from ..dialogs import PasswordConfirmDialog
import frozen_paths
from . import _dashboard_build as dashboard_build


def open_popup(panel):
    """Password dialog → build all HTML dashboards → encrypt → basedir/encrypted/."""
    dlg = PasswordConfirmDialog(
        parent      = panel,
        title       = "Encrypted Dashboards",
        heading     = "🔒  Encrypted Dashboards",
        description = (
            "Builds all HTML dashboards and encrypts them with AES-256.\n"
            "Output folder: basedir/encrypted/\n"
            "Mobile variants are excluded."
        ),
    )
    if dlg.exec() != QDialog.DialogCode.Accepted or dlg.get_result() is None:
        return

    password = dlg.get_result()
    _run(panel, password)
    password = None  # Passwort sofort aus dem Speicher


def _run(panel, password: str):
    """Gather inputs (full specialist scan, HTML-only formats, date
    defaults), then delegate the build/encrypt/report work to the shared
    dashboard_build.run_encrypted()."""
    import importlib.util as _ilu

    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "dashboards", "layouts", "maps")

    try:
        runner_path = root / "dashboards" / "dash_runner.py"
        spec = _ilu.spec_from_file_location("dash_runner", runner_path)
        if spec is None:
            raise FileNotFoundError(
                f"dash_runner.py nicht gefunden: {runner_path}")
        dash_runner = _ilu.module_from_spec(spec)
        spec.loader.exec_module(dash_runner)
    except Exception as exc:
        panel._app._log(f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
        return

    try:
        specialists = dash_runner.scan()
    except Exception as exc:
        panel._app._log(f"✗ scan() fehlgeschlagen: {exc}")
        return
    if not specialists:
        panel._app._log("✗ Keine Dashboards gefunden.")
        return

    # Nur html + html_complex — html_mobile ausgeschlossen
    _ENCRYPT_FORMATS = {"html", "html_complex"}
    selections = [
        (spec["module"], fmt)
        for spec in specialists
        for fmt in spec["formats"]
        if fmt in _ENCRYPT_FORMATS
    ]
    if not selections:
        panel._app._log("✗ Keine HTML-Dashboards für Encrypted Export gefunden.")
        return

    s         = panel._app._panel_settings._collect_settings()
    date_from = s.get("date_from", "").strip()
    date_to   = s.get("date_to",   "").strip()
    if not date_from:
        from datetime import date as _date, timedelta
        date_from = (_date.today() - timedelta(days=30)).isoformat()
    if not date_to:
        from datetime import date as _date
        date_to = _date.today().isoformat()

    dashboard_build.run_encrypted(
        panel, dash_runner, selections, date_from, date_to, password,
        log_label="Encrypted Dashboards")
