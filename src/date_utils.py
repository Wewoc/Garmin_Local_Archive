#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
date_utils.py

Leaf-Node. Shared date helper with no project-module dependency — same
category as log_utils.py/frozen_paths.py, living in this same src/-Root.

date_range() — used by maps/_context_io.py, maps/garmin_health_map.py,
context/context_api.py; previously three identical local copies (v1.7.3.2
dedup).
"""

from datetime import date, timedelta


def date_range(date_from: str, date_to: str) -> list[str]:
    """Returns a list of ISO date strings from date_from to date_to, inclusive."""
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out
