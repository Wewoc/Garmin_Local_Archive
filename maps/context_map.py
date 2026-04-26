#!/usr/bin/env python3
"""
context_map.py

Single entry point for all context archive data requests from specialists.

Structurally identical to field_map.py — same broker principle, different domain.
Knows which *_map.py modules are registered for context sources,
but knows nothing about how any source stores its data.

Registered sources: weather_map, pollen_map, brightsky_map, airquality_map.
Interface is designed to accept additional sources without modification.

Usage (from a specialist):
    from maps.context_map import get, list_fields, list_sources
    result = get("temperature_max", "2026-01-01", "2026-03-31")
    result = get("pollen_birch",    "2026-01-01", "2026-03-31")
    result = get("temperature_avg", "2026-01-01", "2026-03-31")

Return structure:
    {
        "weather": {
            "values":            [{"date": str, "value": float|None}, ...],
            "fallback":          bool,
            "source_resolution": str,
            "error":             str,   # optional — only present if source failed
        },
        "pollen": {
            "values":            [{"date": str, "value": float|None}, ...],
            "fallback":          bool,
            "source_resolution": str,
            "error":             str,   # optional — only present if source failed
        },
        "brightsky": {
            "values":            [{"date": str, "value": float|str|None}, ...],
            "fallback":          bool,
            "source_resolution": str,
            "error":             str,   # optional — only present if source failed
        }
    }

Note: External data must be collected before dashboard build.
context_map reads local files — never calls live APIs at build time.
The collect step is triggered by the "API Sync" button in the GUI.
"""

from . import weather_map
from . import pollen_map
from . import brightsky_map
from . import airquality_map

# ══════════════════════════════════════════════════════════════════════════════
#  Source registry — weather + pollen + brightsky
#
#  To add a source:
#    1. Drop the *_map.py module into maps/
#    2. Import it here with a relative import
#    3. Add it to _SOURCES with its key name
# ══════════════════════════════════════════════════════════════════════════════

_SOURCES = {
    "weather":    weather_map,
    "pollen":     pollen_map,
    "brightsky":  brightsky_map,
    "airquality": airquality_map,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Request a field from all registered external API sources.

    Args:
        field:      Generic field name (dashboard-side).
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: "daily" or "intraday". External sources are always daily —
                    "intraday" triggers fallback=True in the source result.

    Returns:
        Dict keyed by source name. Sources that do not know the requested
        field are silently skipped. Error entries include an "error" key.

    Example:
        {
            "weather": {
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
            pass
        except Exception as exc:
            result[source_name] = {
                "values":            [],
                "fallback":          False,
                "source_resolution": resolution,
                "error":             str(exc),
            }
    return result


def list_fields(source: str = "weather") -> list[str]:
    """
    Return all field names registered for a given source.
    Defaults to weather. Returns empty list for unknown source.
    """
    source_map = _SOURCES.get(source)
    if source_map is None:
        return []
    return source_map.list_fields()


def list_sources() -> list[str]:
    """Return all registered source names."""
    return list(_SOURCES.keys())
