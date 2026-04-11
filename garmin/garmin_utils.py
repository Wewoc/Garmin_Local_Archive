#!/usr/bin/env python3
"""
garmin_utils.py

Shared utilities used by multiple modules.

No file IO beyond what helpers require, no API calls, no GUI logic.
No imports from other project modules — this module is a leaf node.
"""

from datetime import date, datetime


# ══════════════════════════════════════════════════════════════════════════════
#  Date helpers
# ══════════════════════════════════════════════════════════════════════════════

def parse_device_date(val) -> str | None:
    """Converts a device date value to YYYY-MM-DD.
    Handles ISO strings, millisecond timestamps, and second timestamps."""
    if not val:
        return None
    s = str(val).strip()
    # Already ISO date (YYYY-MM-DD...)
    if len(s) >= 10 and s[4:5] == "-":
        return s[:10]
    # Unix timestamp (seconds ~10 digits, milliseconds ~13 digits)
    try:
        ts = int(s)
        if ts > 1e11:   # milliseconds → convert to seconds
            ts //= 1000
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Config helpers
# ══════════════════════════════════════════════════════════════════════════════

def parse_sync_dates(raw: str) -> list | None:
    """
    Parses a comma-separated string of YYYY-MM-DD dates.
    Returns a sorted list of date objects, or None if input is empty or invalid.
    """
    raw = raw.strip()
    if not raw:
        return None
    parsed = []
    for d in raw.split(","):
        try:
            parsed.append(date.fromisoformat(d.strip()))
        except ValueError:
            pass
    return sorted(parsed) if parsed else None
