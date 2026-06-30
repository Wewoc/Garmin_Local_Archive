#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_app_settings.py
Garmin Local Archive — Settings, Keyring, Constants

Layer 1 — no tkinter, no threading, no pipeline imports.
Importable in any context including headless.

Owned by: app/garmin_app_settings.py
Callers:  garmin_app_base.py (via module import as _settings)
          garmin_app.py, garmin_app_standalone.py (direct import)
"""

import json
import os
from pathlib import Path


# ── Settings ───────────────────────────────────────────────────────────────────

SETTINGS_FILE = Path.home() / ".garmin_archive_settings.json"

DEFAULT_SETTINGS = {
    "email":              "",
    "base_dir":           str(Path.home() / "local_archive"),
    "sync_mode":          "recent",
    "sync_days":          "90",
    "sync_from":          "",
    "sync_to":            "",
    "date_from":          "",
    "date_to":            "",
    "age":                "35",
    "sex":                "male",
    "request_delay_min":  "5.0",
    "request_delay_max":  "20.0",
    "timer_min_interval": "5",
    "timer_max_interval": "30",
    "timer_min_days":     "3",
    "timer_max_days":     "10",
    "context_latitude":          "0.0",
    "context_longitude":         "0.0",
    "mirror_dir":                "",
    "backup_raw_backfill_asked": False,
}


def load_settings() -> dict:
    """Load settings from disk, merge with defaults. Never raises."""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            data.pop("password", None)
            return {**DEFAULT_SETTINGS, **data}
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(s: dict):
    """Persist settings to disk. Strips password. Raises OSError on failure.
    Caller (View) is responsible for catching OSError and showing a dialog.
    """
    safe = {k: v for k, v in s.items() if k != "password"}
    SETTINGS_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")


# ── Keyring helpers ────────────────────────────────────────────────────────────

KEYRING_SERVICE = "GarminLocalArchive"
KEYRING_USER    = "garmin_password"


def load_password() -> str:
    """Load password from Windows Credential Manager, fall back to empty."""
    try:
        import keyring
        pw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        return pw or ""
    except Exception:
        return ""


def save_password(pw: str):
    """Save password to Windows Credential Manager."""
    try:
        import keyring
        if pw:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, pw)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass
    except Exception:
        pass


def delete_password():
    """Remove password from Windows Credential Manager."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass


# ── URL helper ─────────────────────────────────────────────────────────────────

def _open_url(url: str):
    """Open a URL in the default browser."""
    try:
        import webbrowser
        if not webbrowser.open(url):
            os.startfile(url)
    except Exception:
        try:
            os.startfile(url)
        except Exception:
            pass
