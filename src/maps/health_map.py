#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
health_map.py

Single entry point for all local archive data requests from specialists.

Routing layer only — knows which *_map.py modules are registered,
but knows nothing about how any source stores its data.

In v1.4: only garmin_map is registered.
Interface is designed to accept a second source in v2.0 without modification.

Usage (from a specialist):
    from maps.health_map import get, list_fields, list_sources
    result = get("hrv_last_night", "2026-01-01", "2026-03-31")
    result = get("heart_rate_series", "2026-01-01", "2026-03-31",
                 resolution="intraday")

Return structure:
    {
        "garmin": {
            "values":            [...],
            "fallback":          bool,
            "source_resolution": str,
            "error":             str,   # optional — only present if source failed
        }
        # v2.0: additional source keys added here
    }
"""

from . import garmin_health_map

# ══════════════════════════════════════════════════════════════════════════════
#  Source registry — v1.4: garmin only
#
#  To add a source in v2.0:
#    1. Drop the *_map.py module into maps/
#    2. Import it here with a relative import
#    3. Add it to _SOURCES with its key name
# ══════════════════════════════════════════════════════════════════════════════

_SOURCES = {
    "garmin": garmin_health_map,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Request a field from all registered sources.

    Args:
        field:      Generic field name (dashboard-side).
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: "daily" or "intraday". Each source applies its own
                    fallback logic if the requested resolution is unavailable.

    Returns:
        Dict keyed by source name. Each value is the result from that
        source's *_map.get() call, or an error entry if the source failed.
        Sources that do not know the requested field are silently skipped.

    Example:
        {
            "garmin": {
                "values":            [...],
                "fallback":          False,
                "source_resolution": "daily",
            }
        }
    """
    result = {}
    for source_name, source_map in _SOURCES.items():
        try:
            result[source_name] = source_map.get(
                field, date_from, date_to, resolution
            )
        except KeyError:
            # This source does not know this field — skip silently
            pass
        except Exception as exc:
            # Source failed — degrade gracefully, never hard-stop
            result[source_name] = {
                "values":            [],
                "fallback":          False,
                "source_resolution": resolution,
                "error":             str(exc),
            }
    return result


def list_fields(source: str = "garmin", active_only: bool = False) -> list[str]:
    """
    Return all field names registered for a given source.
    Defaults to garmin. Returns empty list for unknown source.

    active_only: passed through to garmin_health_map.list_fields() only —
    excludes Capability-Scan candidate fields not enabled_by_user. Ignored
    for sources without a capability concept (context_map's sources).
    """
    source_map = _SOURCES.get(source)
    if source_map is None:
        return []
    if source == "garmin":
        return source_map.list_fields(active_only=active_only)
    return source_map.list_fields()


def list_sources() -> list[str]:
    """Return all registered source names."""
    return list(_SOURCES.keys())


def list_raw_fields(source: str = "garmin") -> list[str]:
    """
    Return all raw-passthrough field names registered for a given source.
    Unlike list_fields(), these are not interpreted — see
    garmin_health_map.get_raw() docstring. Only "garmin" currently
    supports raw-passthrough; other sources return an empty list.
    """
    source_map = _SOURCES.get(source)
    if source_map is None or source != "garmin":
        return []
    return source_map.list_raw_fields()


def get_raw(field: str, date_from: str, date_to: str,
            source: str = "garmin") -> dict:
    """
    Request a raw-passthrough field from a single source. Unlike get(),
    this is not multi-source fan-out — raw-passthrough is Garmin-specific
    for now, caller must pick a source explicitly.

    Raises:
        KeyError: if the source has no raw-passthrough support, or the
                  field is not registered for that source.
    """
    source_map = _SOURCES.get(source)
    if source_map is None or source != "garmin":
        raise KeyError(f"health_map: source '{source}' has no raw-passthrough support")
    return source_map.get_raw(field, date_from, date_to)
