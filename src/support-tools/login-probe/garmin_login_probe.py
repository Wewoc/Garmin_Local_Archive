#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_login_probe.py

Standalone diagnostic — attempts exactly one Garmin Connect login and
reports LOGIN OK / LOGIN FAILED. No sync, no bulk data fetch.

All paths and credentials live in probe_config.py (same folder) — kept
separate so Windows paths with backslashes can be pasted from Explorer
without touching this file's code.

Two independent modes, chosen by probe_config.py:

  Block A — Test account (plaintext credentials, no token access)
    Used when GARMIN_TEST_EMAIL + GARMIN_TEST_PASSWORD are both set.
    Talks directly to the garminconnect library. Does NOT import
    garmin_security, does NOT read or write any token file, does NOT
    touch the main account's token. Nothing is persisted to disk.
    Intended for a disposable/second Garmin account used purely for
    login testing, so the real account is never put at risk.

  Block B — Standard account (existing token flow, WCM-backed)
    Used when Block A's credentials are empty. Runs the project's
    real garmin_api.login() Path 1/3 flow exactly as garmin_app.py
    would, reusing the saved encrypted token if valid, or attempting
    one SSO login if not. No changes to garmin_api.py, garmin_security.py,
    or garmin_config.py — this script only calls them.

    Email and password are never entered in this tool's config. They
    are read from the same place the GUI stores them (Windows
    Credential Manager + ~/.garmin_archive_settings.json) via
    app/garmin_app_settings.py — requires "app/" to sit next to
    "garmin/" under the same "src/" folder, the standard GLA layout.
"""

import os
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import probe_config as pcfg

os.environ.setdefault("GARMIN_OUTPUT_DIR", pcfg.GARMIN_OUTPUT_DIR)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Block A — Test account (no token, nothing persisted)
# ══════════════════════════════════════════════════════════════════════════════

def _probe_test_account() -> int:
    from garminconnect import Garmin

    email = pcfg.GARMIN_TEST_EMAIL
    password = pcfg.GARMIN_TEST_PASSWORD
    if not password:
        password = getpass(f"Password for test account ({email}): ")

    log.info(f"Connecting to Garmin Connect (test account: {email}) ...")
    try:
        client = Garmin(email, password)
        client.login()
        log.info("  \u2713 Login successful (test account, no token saved)")
    except Exception as e:
        print(f"\nLOGIN FAILED: {e}")
        return 1

    print("\nLOGIN OK")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Block B — Standard account (existing token flow via garmin_api.login())
# ══════════════════════════════════════════════════════════════════════════════

def _probe_standard_account() -> int:
    if pcfg.GARMIN_REPO_DIR:
        garmin_dir = Path(pcfg.GARMIN_REPO_DIR)
        sys.path.insert(0, str(garmin_dir))
        app_dir = garmin_dir.parent / "app"
    else:
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        app_dir = script_dir.parent / "app"

    if not app_dir.is_dir():
        print(f"\nLOGIN FAILED: could not find 'app/' next to 'garmin/' "
              f"(looked in {app_dir}). Set GARMIN_REPO_DIR in probe_config.py "
              f"to your GLA 'src/garmin' folder, with 'app/' as its sibling.")
        return 1
    sys.path.insert(0, str(app_dir))

    import garmin_app_settings as _settings

    email = _settings.load_settings().get("email", "")
    password = _settings.load_password()
    if not email or not password:
        print("\nLOGIN FAILED: no email/password found in GLA settings "
              "(~/.garmin_archive_settings.json + Windows Credential Manager). "
              "Save your credentials once via the GLA GUI's Settings tab first.")
        return 1
    os.environ.setdefault("GARMIN_EMAIL",    email)
    os.environ.setdefault("GARMIN_PASSWORD", password)

    import garmin_api

    try:
        client = garmin_api.login(
            on_sso_required=lambda: True,   # allow one SSO attempt if no token
            on_token_expired=lambda: True,  # allow falling through to SSO
        )
    except garmin_api.GarminLoginError as e:
        print(f"\nLOGIN FAILED: {e}")
        return 1

    if client is None:
        print("\nLOGIN CANCELLED")
        return 1

    print("\nLOGIN OK")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    if pcfg.GARMIN_TEST_EMAIL and pcfg.GARMIN_TEST_PASSWORD:
        return _probe_test_account()
    if pcfg.GARMIN_TEST_EMAIL and not pcfg.GARMIN_TEST_PASSWORD:
        # Email set but no password in config — still Block A, just prompt.
        return _probe_test_account()
    return _probe_standard_account()


if __name__ == "__main__":
    sys.exit(main())
