#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
gateway_map.py

Single entry point for cross-domain / external consumers that do not know
in advance which domain broker (health_map, fit_map, context_map) owns a
given field. This is a local API boundary — an in-process Python interface,
not a network endpoint. Network exposure happens separately and exclusively
via mcp_server.py (v1.7).

Not a replacement for direct domain-broker imports. Named specialists with
a fixed domain need (dashboards) continue to import health_map/fit_map/
context_map directly — that keeps them coupled to only what they actually
use, per the broker pattern. gateway_map exists for consumers that decide
at runtime which domain(s) they need (mcp_map v1.7, potentially an export
adapter in v1.7.3).

Routing layer only — knows which domain brokers are registered, but knows
nothing about how any source within a domain stores its data. Pass-through
by design: gateway_map does not reshape or unwrap what a domain broker
returns. Each domain broker already returns a dict keyed by source name
(e.g. health_map.get() -> {"garmin": {...}}), and gateway_map preserves
that shape rather than flattening it — flattening would silently change
form the moment a domain gains a second source (v2.0), which is exactly
the kind of hidden breakage this module is designed to avoid.

Domain registry, v1.6.7:
    "health"  -> health_map    (registered)
    "fit"     -> not yet built (garmin_fit_map.py, v1.7) — key exists now
                 so the contract does not change shape when it lands
    "context" -> context_map   (registered)

Metadata registry, v1.6.9.1 — separate from the domain registry above.
get_metadata(kind) routes to metadata_map.py, an introspection broker for
archive-state artefacts (coverage stats, device table, quality log, raw
logs, token event log, capability config) that do not fit the
time-series get()/domain concept. See metadata_map.py's own docstring
for the full rationale. Nine kinds currently registered — see
_METADATA_KINDS.

Date-range filtering (v1.7.0.4): five of the nine kinds (quality_log,
source_api_log, daily_logs, fail_logs, recent_logs) accept optional
date_from/date_to, passed through to the corresponding metadata_map
function. The other four (stats, device_table, token_log,
capability_config) do not — see _DATE_FILTERABLE_KINDS below, which
get_metadata() consults to decide whether to pass the date arguments
through or call the function the original, parameterless way. This
keeps the four unaffected functions' call signature completely
untouched rather than giving every metadata_map function a date_from/
date_to parameter it would silently ignore.

Usage (from a cross-domain consumer):
    from maps.gateway_map import get as gateway_get
    result = gateway_get("hrv_last_night", "2026-01-01", "2026-03-31")
    result = gateway_get("temperature_max", "2026-01-01", "2026-03-31",
                          domain="context")

Return structure (domain=None — all registered domains queried):
    {
        "health": {
            "garmin": {
                "values":            [...],
                "fallback":          bool,
                "source_resolution": str,
                "error":             str,   # optional
            }
            # v2.0: additional source keys added here by health_map itself
        },
        "fit": {
            "error": "domain not yet available",   # until garmin_fit_map (v1.7)
        },
        "context": {
            "weather":    {"values": [...], "fallback": bool, "source_resolution": str},
            "pollen":     {...},
            "brightsky":  {...},
            "airquality": {...},
        },
    }

Return structure (domain="health" — single domain, same shape, one key):
    {
        "health": {
            "garmin": {...},
        }
    }

Error behavior:
    - Unknown domain string (not one of "health"/"fit"/"context") -> ValueError.
      This is a caller error, not a data-availability problem.
    - Known domain whose broker is not yet registered (currently "fit") ->
      degraded result, {"error": "domain not yet available"} under that
      domain key. No hard-fail.
    - Registered domain broker raises unexpectedly -> degraded result,
      {"error": str(exc)} under that domain key. No hard-fail — same
      degraded-mode principle used by health_map/context_map for their
      own sources.
    - Unknown field in a domain: silently absent from that domain's result
      (each domain broker already handles this itself).
"""

from . import health_map
from . import context_map
from . import metadata_map

# ══════════════════════════════════════════════════════════════════════════════
#  Domain registry — health + fit + context
#
#  "fit" is registered with None on purpose ahead of v1.7 (garmin_fit_map.py)
#  so the domain key and the get()/list_domains() contract are stable before
#  the broker exists. When garmin_fit_map.py lands, replace None with the
#  import — no other change needed here.
#
#  To add a domain:
#    1. Build the domain broker (own *_map.py, own _SOURCES registry)
#    2. Import it here with a relative import
#    3. Add it to _DOMAIN_BROKERS with its key name
# ══════════════════════════════════════════════════════════════════════════════

_DOMAIN_BROKERS = {
    "health":  health_map,
    "fit":     None,          # garmin_fit_map.py, v1.7
    "context": context_map,
}


# ══════════════════════════════════════════════════════════════════════════════
#  Metadata registry — archive-state introspection, v1.6.9.1
#
#  Separate from _DOMAIN_BROKERS on purpose: metadata_map's nine functions
#  are not time-series based (no field/date_from/date_to/resolution), so
#  they cannot be dispatched through get()'s domain-broker fan-out. Each
#  key maps directly to one metadata_map function.
#
#  To add a metadata kind:
#    1. Add the function to metadata_map.py
#    2. Add it here with its key name
# ══════════════════════════════════════════════════════════════════════════════

_METADATA_KINDS = {
    "stats":              metadata_map.get_stats,
    "device_table":       metadata_map.get_device_table,
    "quality_log":        metadata_map.get_quality_log,
    "source_api_log":     metadata_map.get_source_api_log,
    "token_log":          metadata_map.get_token_log,
    "capability_config":  metadata_map.get_capability_config,
    "daily_logs":         metadata_map.get_daily_logs,
    "fail_logs":          metadata_map.get_fail_logs,
    "recent_logs":        metadata_map.get_recent_logs,
}

# Kinds whose metadata_map function accepts date_from/date_to (v1.7.0.4).
# Kept as an explicit set here, rather than giving all nine functions the
# same parameter, so the four unaffected functions (stats, device_table,
# token_log, capability_config) keep their original, parameterless
# signature exactly as-is — see module docstring.
_DATE_FILTERABLE_KINDS = {
    "quality_log", "source_api_log", "daily_logs", "fail_logs", "recent_logs",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily", domain: str | None = None) -> dict:
    """
    Request a field from one or all registered domain brokers.

    Args:
        field:      Generic field name (consumer-side).
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        resolution: "daily" or "intraday". Passed through unchanged to
                    each domain broker, which applies its own fallback
                    logic if the requested resolution is unavailable.
        domain:     None -> query all registered domain keys ("health",
                    "fit", "context"). Set to one of those three -> query
                    only that domain.

    Returns:
        Dict keyed by domain name. Each value is exactly what that
        domain's *_map.get() returned (dict keyed by source name) —
        gateway_map does not reshape it. A domain whose broker is not
        yet registered (currently "fit") returns a degraded single-entry
        dict under that key instead.

    Raises:
        ValueError: if domain is set to a string that is not a known
                    domain key. This is a caller error, distinct from a
                    domain being known but not yet available.
    """
    if domain is not None and domain not in _DOMAIN_BROKERS:
        raise ValueError(
            f"Unknown domain {domain!r} — expected one of "
            f"{sorted(_DOMAIN_BROKERS)} or None"
        )

    domains_to_query = [domain] if domain is not None else list(_DOMAIN_BROKERS)

    result = {}
    for domain_name in domains_to_query:
        broker = _DOMAIN_BROKERS[domain_name]
        if broker is None:
            result[domain_name] = {"error": "domain not yet available"}
            continue
        try:
            result[domain_name] = broker.get(field, date_from, date_to, resolution)
        except Exception as exc:
            # Domain broker failed unexpectedly — degrade gracefully,
            # never hard-stop the whole gateway request.
            result[domain_name] = {"error": str(exc)}
    return result


def list_domains() -> list[str]:
    """Return all known domain keys, whether their broker is registered yet or not."""
    return list(_DOMAIN_BROKERS.keys())


def get_metadata(kind: str, date_from: str | None = None,
                  date_to: str | None = None) -> dict:
    """
    Request an archive-state metadata artefact from metadata_map.

    Separate entry point from get() because metadata_map's data is not
    time-series based — there is no field/resolution concept for
    archive-state snapshots (coverage stats, device table, raw logs,
    etc.). Five kinds do support an optional date_from/date_to RANGE
    FILTER (v1.7.0.4) — see _DATE_FILTERABLE_KINDS — which is a
    different thing from the time-series "resolution" concept get()
    uses; no "_meta" weekday block is built here either way.

    Args:
        kind:       One of the registered metadata kinds — see
                    _METADATA_KINDS.
        date_from:  Optional ISO "YYYY-MM-DD", inclusive. Only used if
                    kind is in _DATE_FILTERABLE_KINDS — silently ignored
                    otherwise (same as passing it to a function that
                    never asked for it would be, just made explicit
                    here instead of raising a TypeError from a mismatched
                    call).
        date_to:    Optional ISO "YYYY-MM-DD", inclusive. Same rule as
                    date_from.

    Returns:
        Whatever the corresponding metadata_map function returned:
        {"data": ..., "error": str | None} — plus an optional "note"
        key on the five date-filterable kinds when neither date_from
        nor date_to was given (the 30-day default range was applied).
        metadata_map never raises — read/parse failures are already
        degraded into this shape before they reach gateway_map.

    Raises:
        ValueError: if kind is not a known metadata kind. This is a
                    caller error, same principle as get()'s domain
                    validation.
    """
    if kind not in _METADATA_KINDS:
        raise ValueError(
            f"Unknown metadata kind {kind!r} — expected one of "
            f"{sorted(_METADATA_KINDS)}"
        )
    if kind in _DATE_FILTERABLE_KINDS:
        return _METADATA_KINDS[kind](date_from=date_from, date_to=date_to)
    return _METADATA_KINDS[kind]()


def list_metadata_kinds() -> list[str]:
    """Return all known metadata kind keys."""
    return list(_METADATA_KINDS.keys())


def get_raw(field: str, date_from: str, date_to: str,
            domain: str | None = None) -> dict:
    """
    Request a raw-passthrough field from one or all registered domain
    brokers. Same fan-out shape as get(), but for unprocessed data — see
    garmin_health_map.get_raw() for the rationale (v1.6.8). Only "health"
    currently supports raw-passthrough; other domains degrade gracefully
    rather than hard-failing, same principle as get()'s "fit" handling.

    Args:
        field:      Generic raw-field name (consumer-side).
        date_from:  Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:    End date ISO string (YYYY-MM-DD), inclusive.
        domain:     None -> query all registered domain keys. Set to one
                    of those -> query only that domain.

    Returns:
        Dict keyed by domain name. Each value is exactly what that
        domain's *_map.get_raw() returned, or a degraded {"error": ...}
        entry if the domain's broker is not yet registered or has no
        raw-passthrough support.

    Raises:
        ValueError: if domain is set to a string that is not a known
                    domain key.
    """
    if domain is not None and domain not in _DOMAIN_BROKERS:
        raise ValueError(
            f"Unknown domain {domain!r} — expected one of "
            f"{sorted(_DOMAIN_BROKERS)} or None"
        )

    domains_to_query = [domain] if domain is not None else list(_DOMAIN_BROKERS)

    result = {}
    for domain_name in domains_to_query:
        broker = _DOMAIN_BROKERS[domain_name]
        if broker is None:
            result[domain_name] = {"error": "domain not yet available"}
            continue
        try:
            result[domain_name] = broker.get_raw(field, date_from, date_to)
        except AttributeError:
            result[domain_name] = {"error": "domain has no raw-passthrough support"}
        except Exception as exc:
            # Domain broker failed unexpectedly — degrade gracefully,
            # never hard-stop the whole gateway request.
            result[domain_name] = {"error": str(exc)}
    return result


def list_raw_fields(domain: str | None = None) -> dict[str, list[str]]:
    """
    Return raw-passthrough field names per domain. Unlike list_domains(),
    keyed by domain — domains without raw-passthrough support (or not yet
    registered) return an empty list under their key rather than being
    omitted, so the shape is stable regardless of which domains support it.

    Args:
        domain: None -> all registered domain keys. Set to one -> only
                that domain's raw fields.

    Raises:
        ValueError: if domain is set to a string that is not a known
                    domain key.
    """
    if domain is not None and domain not in _DOMAIN_BROKERS:
        raise ValueError(
            f"Unknown domain {domain!r} — expected one of "
            f"{sorted(_DOMAIN_BROKERS)} or None"
        )

    domains_to_query = [domain] if domain is not None else list(_DOMAIN_BROKERS)

    result = {}
    for domain_name in domains_to_query:
        broker = _DOMAIN_BROKERS[domain_name]
        if broker is None:
            result[domain_name] = []
            continue
        try:
            result[domain_name] = broker.list_raw_fields()
        except AttributeError:
            result[domain_name] = []
    return result
