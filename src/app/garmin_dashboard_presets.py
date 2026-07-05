#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_dashboard_presets.py
Garmin Local Archive — Custom Dashboard Presets (v1.6.4)

Sole Owner of the Custom Dashboard preset file. Stores named field
selections for the Custom Dashboard Builder. Mirrors the persistence
pattern already established in app/garmin_app_settings.py
(SETTINGS_FILE = Path.home() / "...") — separate file, separate ownership,
no shared state with app settings.

Layer 1 — no tkinter, no threading, no pipeline imports.
Importable in any context including headless.
"""

import json
from pathlib import Path

PRESETS_FILE = Path.home() / ".garmin_dashboard_presets.json"


def load_presets() -> dict:
    """
    Load all presets from disk. Never raises.

    Returns:
        {preset_name: preset_dict, ...} — {} if file missing or corrupt.
    """
    if PRESETS_FILE.exists():
        try:
            return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_preset(name: str, preset: dict) -> None:
    """
    Save or overwrite a named preset. Raises OSError on failure.
    Caller (View) is responsible for catching OSError and showing a dialog.

    preset schema:
        {
            "garmin_fields":  [str, ...],
            "context_fields": [str, ...],
            "date_mode":      "fixed" | "relative",
            "date_from":      str,   # present if date_mode == "fixed"
            "date_to":        str,   # present if date_mode == "fixed"
            "days_back":      int,   # present if date_mode == "relative"
            "formats":        [str, ...],   # subset of ["html_mobile", "excel"]
            "encrypt":        bool,  # if True, "excel" is excluded from
                                     # formats and a password is prompted
                                     # again on every load — never persisted
        }
    """
    presets = load_presets()
    presets[name] = preset
    PRESETS_FILE.write_text(json.dumps(presets, indent=2), encoding="utf-8")


def delete_preset(name: str) -> None:
    """
    Remove a named preset. No-op if it doesn't exist.
    Raises OSError on write failure.
    """
    presets = load_presets()
    if name in presets:
        del presets[name]
        PRESETS_FILE.write_text(json.dumps(presets, indent=2), encoding="utf-8")
