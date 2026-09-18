#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_query_common.py
Garmin Local Archive — MCP query-serving shared helpers

Extracted from clients/mcp_server.py (Codereview v1.7.0.1, Baustein 2.2)
— three small, fully self-contained helpers with no dependency on
mcp/mcp_sql/mcp_map, used by mcp_server.py itself (query_fit_activities,
query_raw, get_archive_metadata, list_available_fields all call
_route_query(); list_available_fields() also calls _get_field_unit()
directly) AND by clients/mcp_health.py / clients/mcp_context.py (both
need _route_query()/_enrich_with_units()).

Living in this separate, lower-level module (rather than staying in
mcp_server.py) is what avoids a circular import: mcp_server.py imports
query_health/query_context from mcp_health.py/mcp_context.py, so those
two files cannot import anything back from mcp_server.py — including
these three helpers, which they also need. mcp_query_common.py has no
dependency on mcp_server.py at all, so everyone can import it safely.

_get_field_unit()/_enrich_with_units() need FIELD_UNITS from
clients/mcp_field_registry.py (Baustein 2.1).
"""

from mcp_field_registry import FIELD_UNITS


def _get_field_unit(field: str) -> str:
    """Single lookup point for a field's display unit. Isolated on
    purpose (see FIELD_UNITS' module comment in mcp_field_registry.py) —
    the only place that needs to change when this stopgap is replaced by a broker-level
    unit registry. Unknown field (should not occur for a field that
    already passed query_health()/query_context()'s own field-validity
    checks) -> "—" rather than a KeyError, so a future new field that is
    not yet in FIELD_UNITS degrades to "no unit shown" instead of
    breaking the whole response."""
    return FIELD_UNITS.get(field, "—")


def _enrich_with_units(result: dict, domain: str) -> dict:
    """Adds a "unit" key to every per-field dict inside result[domain],
    in place, and returns result for call-site chaining. Handles both
    shapes query_health()/query_context() can produce under
    result[domain]:
      - {source: {field: {"values": ..., ...}}}   (normal per-source shape)
      - {field: {"values": ..., ...}}              (already-flattened
        shape, e.g. _resolve_context_bundle()'s output)
    A per-field dict is recognized by the presence of "values" — the one
    key REFERENCE_BROKER.md guarantees on every field-level dict
    regardless of domain or source, daily or intraday/live. Not
    recursive beyond one extra level, since no third shape currently
    exists in this codebase; see FIELD_UNITS' module comment (mcp_field_registry.py) for the
    planned replacement path if that ever changes.

    v1.7.1.15 -- also sets _meta["has_data"] = False when the field was
    successfully resolved but every "values" array found is empty (or
    result[domain] itself is empty), so a resolved-but-no-data response
    is distinguishable from an in-progress/incomplete one. Reuses the
    same "values" presence check already needed for the unit lookup --
    no second pass, no new response shape."""
    domain_dict = result.get(domain)
    if not isinstance(domain_dict, dict):
        return result

    has_data = False
    for key, value in domain_dict.items():
        if not isinstance(value, dict):
            continue
        if "values" in value:
            # Already-flattened shape: key IS the field name.
            value["unit"] = _get_field_unit(key)
            if value["values"]:
                has_data = True
        else:
            # Normal per-source shape: key is a source name, value's
            # own keys are field names.
            for field_name, field_dict in value.items():
                if isinstance(field_dict, dict) and "values" in field_dict:
                    field_dict["unit"] = _get_field_unit(field_name)
                    if field_dict["values"]:
                        has_data = True

    if not has_data:
        result.setdefault("_meta", {})
        result["_meta"]["has_data"] = False

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Routing weiche (v1.7.1.1 Ziel 5) — placeholder, no real heuristic yet
# ══════════════════════════════════════════════════════════════════════════════
#
# TODO v1.7.x — real heuristic after a measurement tool compares SQLite
# vs. live cost/staleness (explicitly out of scope this session, see
# NOTES_v1.7.1.1_session2.md). Fixed return "sqlite" for every kind —
# analogous to gateway_map._DOMAIN_BROKERS['fit': None]'s "Stöpsel"
# precedent: the decision point exists and is called from all six query
# tools (four in mcp_server.py, two via mcp_health.py/mcp_context.py),
# but carries no actual logic yet, so a later heuristic only has to
# change this one function's body, never any call site.
#
# All six query tools route through this (call sites live in
# mcp_server.py, mcp_health.py, mcp_context.py) — refresh_cache() does NOT:
# it is a sync trigger, not a data query, so it is categorically not a
# routing candidate (see NOTES_v1.7.1.1_session2.md).
#
# query_fit_activities IS included, not excluded — once the FIT domain
# exists it should also go through the SQLite cache like every other
# domain (see NOTES_v1.7.1.1_session2.md). Its "sqlite" branch below
# calls mcp_map.query_fit_activities() directly rather
# than a not-yet-existing mcp_sql.get_fit_range(), i.e. it currently
# returns the identical degraded {"fit": {"error": "domain not yet
# available"}, ...} result on both branches of the if/else — the same
# "Stöpsel statt Vollintegration" principle KONZEPT_mcp_sqlite_proxy_V2.md
# already documents for FIT elsewhere in this project, applied here to
# the routing weiche's SQLite branch specifically. Once fit_map.py and
# mcp_sql.get_fit_range() exist (v1.8), only that one branch needs to
# change — the weiche itself, and every wrapper's call to it, stays
# unchanged.


def _route_query(kind: str) -> str:
    """
    Decides whether a given query kind should be served from the
    SQLite cache or the live archive. Placeholder — always returns
    "sqlite" for every kind (see module comment above for the binding
    rationale and TODO). kind is one of "health"/"context"/"fit"/
    "raw"/"metadata" — a query-tool-family identifier, not an
    MCP-tool-name passthrough, since query_fit_activities and the
    (not yet existing) fit-domain query share one "fit" kind rather
    than each tool inventing its own key.
    """
    return "sqlite"
