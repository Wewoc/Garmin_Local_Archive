# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

# version.py
# Garmin Local Archive — Single source of truth for APP_VERSION
# Imported by garmin_app_base.py and daily_update.py.
# No third-party imports, no tkinter — safe for all build targets.

APP_VERSION = "1.7.3"


def is_newer(latest: str, current: str) -> bool:
    """True only if `latest` is a well-formed, strictly higher version than
    `current`. Replaces a plain string-inequality check (any deviation,
    including a differently-tagged or custom/dev build, used to count as
    "update available") — harmless for a dismissible popup, but risky once
    an update can auto-apply without a human looking at it first (v1.7.2.4).
    Unparseable input is treated as "not newer", never as "newer"."""
    try:
        latest_tuple  = tuple(int(p) for p in latest.lstrip("vV").split("."))
        current_tuple = tuple(int(p) for p in current.lstrip("vV").split("."))
    except ValueError:
        return False
    return latest_tuple > current_tuple
