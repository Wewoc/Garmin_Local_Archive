#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/_dashboard_build.py
Garmin Local Archive — shared dashboard build engine

Extracted from app/panel_outputs.py (Codereview v1.7.0.1, Baustein 1.5)
— NOT a popup itself (no open_popup()), but the shared background-thread
build backend that app/popups/dashboard_create.py, custom_dashboard.py
and encrypted_dashboards.py call into, so none of those three popup
files needs to import another one directly (Timo's decision: split
Encrypted into "direct GUI call" + "the function separately, callable
by Encrypted itself and Custom Dashboard etc" — see PROTOKOLL_experiment.md
2026-09-18).

run_dashboards(): moved verbatim from panel_outputs.py's former
_run_dashboards() (self -> panel), used by both the plain "Create
Reports" popup and Custom Dashboard's non-encrypted branch. No
duplication existed here — only one implementation, this is a pure
relocation for symmetry with run_encrypted() below.

run_encrypted(): UNIFIES what were two separate, ~86-lines-identical
methods (former _run_encrypted_dashboards() and
_run_custom_dashboard_encrypted()) into one function, parameterized by
dash_runner/selections/date_from/date_to/password/log_label. Verified
via a line-level diff before merging (see
changelog/anchor_delivery_v1701-popup-custom-encrypted-dashboards.md) —
the two originals were byte-identical from "build output_dir" onward, only
differing in how dash_runner/selections/date_from/date_to were gathered
(full specialist scan + 30-day default vs. a single caller-supplied
ad-hoc module + caller-supplied dates) and in one log-label word. Both
callers keep gathering their own inputs in their own popup file; only
the identical build/encrypt/report tail lives here now.
"""

import os
import threading
from pathlib import Path
from datetime import date, timedelta

import frozen_paths


def run_dashboards(panel, dash_runner, selections, date_from=None, date_to=None):
    """Run dashboard build in background thread, stream progress to log.

    date_from/date_to: optional override (YYYY-MM-DD) — used by the
    Custom Dashboard Builder, which has its own date range control
    independent of the global Settings date range. Falls back to
    Settings when omitted — existing Create Reports flow unaffected.
    """
    s = panel._app._panel_settings._collect_settings()
    if date_from is None:
        date_from = s.get("date_from", "").strip()
        if not date_from:
            date_from = (date.today() - timedelta(days=30)).isoformat()
    if date_to is None:
        date_to = s.get("date_to", "").strip()
        if not date_to:
            date_to = date.today().isoformat()
    output_dir = Path(s["base_dir"]) / "dashboards"
    output_dir.mkdir(parents=True, exist_ok=True)

    panel._app._log("\n▶  Berichte erstellen ...")
    panel._app._log(f"   Output: {output_dir}")
    panel._app._log(f"   Zeitraum: {date_from} → {date_to}")

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
                log=lambda msg: panel._app._dispatch(
                    lambda m=msg: panel._app._log(f"   {m}")),
            )

            def on_done():
                ok  = [r for r in results if r["success"]]
                err = [r for r in results if not r["success"]]
                panel._app._log(f"\n  ✓ {len(ok)} Bericht(e) erstellt")
                for r in err:
                    panel._app._log(
                        f"  ✗ {r['name']} ({r['format']}): "
                        f"{r.get('error', '')}")
                if ok:
                    last_html = next(
                        (r.get("path") for r in ok
                         if r.get("format") == "html"), None)
                    if last_html:
                        panel._app._last_html = str(last_html)
                    panel._app._scan_dashboards(
                        auto_load=panel._app._last_html)
                    panel._app._scan_xlsx_files()
                # Regenerate mobile landing page with fresh dashboard content
                try:
                    import garmin_mobile_landing as _landing
                    _landing.write_index_html(s["base_dir"])
                except Exception:
                    pass
                if ok:
                    os.startfile(str(output_dir))

            panel._app._dispatch(on_done)
        except Exception as exc:
            panel._app._dispatch(
                lambda e=exc: panel._app._log(f"  ✗ Fehler: {e}"))

    threading.Thread(target=worker, daemon=True).start()


def run_encrypted(panel, dash_runner, selections, date_from, date_to,
                   password, log_label="Encrypted Dashboards"):
    """Build the given selections as HTML, encrypt with AES-256, write to
    basedir/encrypted/. Shared by encrypted_dashboards.py's open_popup()
    (full specialist scan) and custom_dashboard.py's encrypt branch
    (single ad-hoc module) — identical build/encrypt/report logic from
    here on; each caller gathers its own dash_runner/selections/
    date_from/date_to/password before calling this.
    """
    import importlib.util as _ilu

    root = frozen_paths.scripts_root()
    s = panel._app._panel_settings._collect_settings()

    output_dir = Path(s["base_dir"]) / "encrypted"
    output_dir.mkdir(parents=True, exist_ok=True)

    panel._app._log(f"\n🔒  {log_label} erstellen ...")
    panel._app._log(f"   Output: {output_dir}")
    panel._app._log(f"   Zeitraum: {date_from} → {date_to}")

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
                log=lambda msg: panel._app._dispatch(
                    lambda m=msg: panel._app._log(f"   {m}")),
            )

            ok  = [r for r in results if r["success"]]
            err = [r for r in results if not r["success"]]

            if err:
                def _log_err():
                    for r in err:
                        panel._app._log(
                            f"  ✗ {r['name']} ({r['format']}): "
                            f"{r.get('error', '')}")
                panel._app._dispatch(_log_err)

            if not ok:
                panel._app._dispatch(
                    lambda: panel._app._log("  ✗ Keine Dashboards gebaut."))
                return

            # ── Encrypt-Pass ───────────────────────────────────────────────
            try:
                encryptor_path = root / "layouts" / "dash_encryptor.py"
                enc_spec = _ilu.spec_from_file_location(
                    "dash_encryptor", encryptor_path)
                if enc_spec is None:
                    raise FileNotFoundError(
                        f"dash_encryptor.py nicht gefunden: {encryptor_path}")
                dash_encryptor = _ilu.module_from_spec(enc_spec)
                enc_spec.loader.exec_module(dash_encryptor)
            except Exception as exc:
                panel._app._dispatch(
                    lambda e=exc: panel._app._log(
                        f"  ✗ dash_encryptor konnte nicht geladen werden: {e}"))
                return

            encrypted_count = 0
            encrypt_errors  = []
            for r in ok:
                html_path = r.get("file")
                if not html_path or not html_path.exists():
                    continue
                try:
                    stem     = html_path.stem
                    enc_name = f"{stem}_enc.html"
                    enc_path = output_dir / enc_name

                    html_content = html_path.read_text(encoding="utf-8")
                    encrypted    = dash_encryptor.encrypt_html(
                        html_content, password,
                        bg=panel._app.BG, bg2=panel._app.BG2,
                        accent=panel._app.ACCENT, accent2=panel._app.ACCENT2,
                        text=panel._app.TEXT, text2=panel._app.TEXT2,
                        red=panel._app.RED)

                    html_path.unlink()
                    enc_path.write_text(encrypted, encoding="utf-8")
                    encrypted_count += 1

                except Exception as exc:
                    encrypt_errors.append(f"{html_path.name}: {exc}")

            def _finish():
                panel._app._log(
                    f"\n  ✓ {encrypted_count} Dashboard(s) verschlüsselt")
                for e in encrypt_errors:
                    panel._app._log(f"  ✗ Encrypt-Fehler: {e}")
                panel._app._log(f"  📁  {output_dir}")
                os.startfile(str(output_dir))

            panel._app._dispatch(_finish)

        except Exception as exc:
            panel._app._dispatch(
                lambda e=exc: panel._app._log(f"  ✗ Fehler: {e}"))

    threading.Thread(target=worker, daemon=True).start()
