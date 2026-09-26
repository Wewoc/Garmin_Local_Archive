#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
fetch_raw_days.py

Standalone diagnostic — fetches specific days directly via the Garmin API
(garmin_api.fetch_raw(), the same 15 baseline endpoints garmin_collector.py
uses) and saves the raw result as JSON in this tool's own downloads/
subfolder.

Analysis tool only. Does NOT touch the archive: no write to raw/,
source/, or quality_log.json, and does not go through garmin_collector.py
at all. Purely for comparing a fresh API pull against an existing
bulk-sourced garmin_raw_<date>.json side by side.

Reuses the existing GLA login (saved token via garmin_app_settings.py +
garmin_api.login()), same as support-tools/login-probe Block B — no
credentials live in this folder.

Usage:
    python fetch_raw_days.py 2023-12-31 2023-06-15 ...

Output:
    downloads/garmin_api_<date>.json  — one file per requested day
"""

import json
import os
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import api_raw_probe_config as pcfg  # noqa: E402

os.environ.setdefault("GARMIN_OUTPUT_DIR", pcfg.GARMIN_OUTPUT_DIR)

if pcfg.GARMIN_REPO_DIR:
    garmin_dir = Path(pcfg.GARMIN_REPO_DIR)
else:
    garmin_dir = _SCRIPT_DIR.parent.parent / "garmin"
sys.path.insert(0, str(garmin_dir))
app_dir = garmin_dir.parent / "app"
sys.path.insert(0, str(app_dir))

import logging  # noqa: E402
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DOWNLOADS_DIR = _SCRIPT_DIR / "downloads"


def _login():
    """Reuses the saved GLA token — same Block B pattern as login-probe."""
    if not app_dir.is_dir():
        print(f"ERROR: could not find 'app/' next to 'garmin/' (looked in {app_dir}). "
              f"Set GARMIN_REPO_DIR in api_raw_probe_config.py to your GLA "
              f"'src/garmin' folder, with 'app/' as its sibling.")
        sys.exit(1)

    import garmin_app_settings as _settings
    email = _settings.load_settings().get("email", "")
    password = _settings.load_password()
    if not email or not password:
        print("ERROR: no email/password found in GLA settings "
              "(~/.garmin_archive_settings.json + Windows Credential Manager). "
              "Save your credentials once via the GLA GUI's Settings tab first.")
        sys.exit(1)
    os.environ.setdefault("GARMIN_EMAIL", email)
    os.environ.setdefault("GARMIN_PASSWORD", password)

    import garmin_api
    try:
        client = garmin_api.login(
            on_sso_required=lambda: True,
            on_token_expired=lambda: True,
        )
    except garmin_api.GarminLoginError as e:
        print(f"ERROR: login failed: {e}")
        sys.exit(1)
    if client is None:
        print("ERROR: login cancelled")
        sys.exit(1)
    return client


def main(dates: list[str]) -> None:
    print("=" * 70)
    print("  fetch_raw_days.py")
    print(f"  Downloads dir : {DOWNLOADS_DIR}")
    print(f"  Days requested: {', '.join(dates)}")
    print("  NOTE: analysis tool only — the archive (raw/, source/,")
    print("  quality_log.json) is never touched by this script.")
    print("=" * 70)

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    import garmin_api
    client = _login()
    log.info("Login OK — fetching %d day(s) ...", len(dates))

    ok, failed = 0, 0
    for date_str in dates:
        log.info(f"  Fetching {date_str} ...")
        try:
            raw, failed_endpoints = garmin_api.fetch_raw(client, date_str)
        except Exception as e:
            log.error(f"    ERROR fetching {date_str}: {e}")
            failed += 1
            continue

        out_path = DOWNLOADS_DIR / f"garmin_api_{date_str}.json"
        out_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        size = out_path.stat().st_size
        ok += 1
        if failed_endpoints:
            log.info(f"    saved {out_path.name} ({size} bytes) — "
                      f"endpoints with no data: {', '.join(failed_endpoints)}")
        else:
            log.info(f"    saved {out_path.name} ({size} bytes) — all endpoints returned data")

    print()
    print("=" * 70)
    print(f"  Done. {ok} saved, {failed} errors.")
    print(f"  Files: {DOWNLOADS_DIR}")
    print("=" * 70)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_raw_days.py YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)
    main(sys.argv[1:])
