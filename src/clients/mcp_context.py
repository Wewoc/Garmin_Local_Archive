#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_context.py
Garmin Local Archive — MCP query_context tool

Extracted from clients/mcp_server.py (Codereview v1.7.0.1, Baustein 2.2)
— the query_context() MCP tool plus its two private helpers,
_resolve_context_bundle() (category-bundle flattening + per-day source
priority merge) and _fetch_context_field() (the wind_speed_max
brightsky/weather collision merge, shared across the direct-request/
alias/near-match call paths). All three bodies are verbatim from the
former mcp_server.py — no self/panel rewrite needed, these were already
plain module-level functions.

query_context() is deliberately undecorated here (no `@mcp.tool()`) —
same reasoning as clients/mcp_health.py: the shared `mcp` FastMCP
instance stays in mcp_server.py, which imports this plain function and
applies the decorator programmatically
(`query_context = mcp.tool()(query_context)`), avoiding a circular
import while keeping mcp_server.query_context resolving exactly as
before for tests/test_mcp.py's `import mcp_server` +
`mcp_server.query_context(...)` calls.

_CONTEXT_CATEGORY_BUNDLES imported from mcp_field_registry.py (moved
there in this same Baustein) rather than defined here — kept in the
neutral shared registry so clients/mcp_health.py's one negative check
against it doesn't need to depend on this file.
"""

import difflib

from maps import mcp_map
import mcp_sql
from mcp_field_registry import (
    CONTEXT_FIELD_ALIASES,
    CONTEXT_FIELD_AMBIGUOUS,
    _CONTEXT_CATEGORY_BUNDLES,
)
from mcp_query_common import _route_query, _enrich_with_units


def _resolve_context_bundle(bundle_name: str, date_from: str, date_to: str,
                             resolution: str) -> dict:
    """v1.7.1.5 -- resolves a _CONTEXT_CATEGORY_BUNDLES entry into a flat,
    single-value-per-field-name result. For each source in the bundle's
    priority list, gathers every field name that source registers (via
    mcp_map.list_available_fields(domain="context") -- clients/ never
    imports maps.context_map directly, mcp_map is the sole broker-facing
    surface, see NOTES_v1.7.1.5.md) and queries it through the same
    sqlite/live routing weiche query_context() itself uses for a plain
    field -- no separate/bypass data-access path.

    Flattening: field names are unique across sources except for a
    deliberate, known collision (e.g. "wind_speed_max" under both
    "weather" and "brightsky"). On a collision, the tie-break is decided
    PER DAY, not per whole field: for each date in range, the first
    source (in the bundle's priority-list order) with a non-None value
    for THAT day wins -- a field's final "values" array can therefore be
    stitched together from more than one source across the range (e.g.
    brightsky for most days, weather filling in a day brightsky has no
    data for). "_meta.field_sources" records the winning source for each
    day a collision was actually resolved (e.g. {"wind_speed_max":
    {"2026-03-01": "brightsky", "2026-03-02": "weather"}}) -- only for
    fields that had more than one candidate source in this bundle, never
    for a field copied through from a single source unchanged.

    v1.7.1.11 -- "_series" (intraday) fields are skipped during bundle
    resolution (see the source_field loop below). The bundle mechanism
    exists to answer a daily-value source-collision question (DWD vs.
    model, e.g. wind_speed_max); at intraday resolution the three
    affected sources never have more than one candidate, so the
    collision machinery has nothing to resolve. A _series field remains
    individually queryable via query_context()."""
    # source_values[field_name][source] = {date: value, ...}
    source_values: dict[str, dict[str, dict[str, object]]] = {}
    field_resolution: dict[str, dict] = {}  # first-seen values/fallback/
                                             # source_resolution shape per field
    meta: dict = {}

    # source -> [field_names] fuer alle context-Quellen. Ueber mcp_map
    # bezogen, nicht direkt aus maps.context_map -- clients/ spricht die
    # Broker-Schicht ausschliesslich ueber mcp_map an (Maintainer-Entscheidung,
    # NOTES_v1.7.1.5.md), context_map bleibt intern fuer maps/.
    _context_fields_by_source = mcp_map.list_available_fields(
        domain="context")["fields"]["context"]

    for source in _CONTEXT_CATEGORY_BUNDLES[bundle_name]:
        for source_field in _context_fields_by_source.get(source, []):
            if source_field.endswith("_series"):
                continue  # Bundle-Kollisionslogik ist nur für Tageswerte
                           # definiert — DWD-ja/nein-Frage betrifft Quellen,
                           # nicht Auflösungsstufen. Ein _series-Feld bleibt
                           # über query_context() einzeln abfragbar.
            if _route_query("context") == "sqlite":
                source_result = mcp_sql.get_context_range(
                    date_from, date_to, field=source_field
                )
            else:
                source_result = mcp_map.query_context(
                    source_field, date_from, date_to, resolution
                )
            meta = source_result.get("_meta", meta)

            per_source = source_result.get("context", {}).get(source, {})
            candidate = per_source.get(source_field)
            if candidate is None:
                continue

            by_date = {v["date"]: v.get("value") for v in candidate.get("values", [])}
            source_values.setdefault(source_field, {})[source] = by_date
            field_resolution.setdefault(source_field, {
                "fallback": candidate.get("fallback", False),
                "source_resolution": candidate.get("source_resolution", "daily"),
            })

    flat_values: dict[str, dict] = {}
    field_sources: dict[str, dict[str, str]] = {}

    for source_field, per_source_dates in source_values.items():
        sources_for_field = [
            s for s in _CONTEXT_CATEGORY_BUNDLES[bundle_name]
            if s in per_source_dates
        ]
        all_dates = sorted({
            d for by_date in per_source_dates.values() for d in by_date
        })

        merged_values = []
        day_winners: dict[str, str] = {}
        for day in all_dates:
            winning_value = None
            winning_source = None
            for source in sources_for_field:
                day_value = per_source_dates[source].get(day)
                if day_value is not None:
                    winning_value = day_value
                    winning_source = source
                    break
            merged_values.append({"date": day, "value": winning_value})
            if winning_source is not None:
                day_winners[day] = winning_source

        flat_values[source_field] = {
            **field_resolution[source_field],
            "values": merged_values,
        }
        # Only record a per-day source map when this field actually had
        # more than one candidate source in this bundle -- a single-
        # source field (the normal pollen/air case, and most weather
        # fields) needs no attribution.
        if len(sources_for_field) > 1:
            field_sources[source_field] = day_winners

    result: dict = {"context": flat_values}
    result["_meta"] = meta if meta else {}
    result["_meta"]["field_sources"] = field_sources
    # v1.7.1.6 unit field (this session): flat_values is keyed directly
    # by field name (no source level — see this function's own
    # docstring on flattening), so _enrich_with_units() takes the
    # already-flattened branch. Note this cannot be done earlier by
    # reusing "candidate"'s own unit (if any): the per-source calls
    # above go straight to mcp_sql.get_context_range()/
    # mcp_map.query_context() (Zeilen darueber), not through this
    # module's query_context() @mcp.tool() wrapper, so candidate never
    # carries a "unit" key to begin with -- this call is the first
    # point in this function's data flow where a unit can be attached.
    return _enrich_with_units(result, "context")


# v1.7.1.16 -- extracted out of query_context() so the brightsky/DWD-vs-
# weather/Open-Meteo source-priority merge for "wind_speed_max" (see the
# comment on the "field == 'wind_speed_max'" branch below) applies no
# matter how the caller reached that field name: a direct, exact request,
# a CONTEXT_FIELD_ALIASES hit (e.g. "max_wind_speed", "wind_speed",
# "max_wind_speed_dwd", "wind_max" -- all four alias to "wind_speed_max"),
# or a difflib near-match auto-resolve. Before this fix only the direct-
# request path applied the merge; both alias/near-match paths returned
# right after fetching, with the two sources' conflicting raw values
# still separated by source key under result["context"] instead of one
# prioritized value -- reproduced live via "query_context max_wind_speed
# ...", see NOTES_v1.7.1.16.md for the repro and MCP-side symptom.
#
# Returns the same {"context": ..., "_meta": ...} shape query_context()'s
# call sites already expect, pre-unit-enrichment -- callers still run the
# result through _enrich_with_units() themselves so field_resolved_from/
# field_used (set by the alias/near-match callers, not here) end up in
# the same "_meta" dict that carries "field_sources" for the merge case.
def _fetch_context_field(field: str, date_from: str, date_to: str,
                          resolution: str) -> dict:
    # v1.7.1.12 -- wind_speed_max source collision (see NOTES_v1.7.1.12.md
    # "Ziel 2"): "weather" and "brightsky" both register a field called
    # "wind_speed_max" (deliberate, documented in REFERENCE_BROKER.md).
    # _resolve_context_bundle() above already tie-breaks this correctly
    # per day when the request goes through the "weather" bundle name --
    # this handles the same tie-break for every other way of reaching the
    # field (direct request, alias, near-match -- see this function's own
    # docstring above). Fixed here with a plain value precedence, no
    # generic collision table (Maintainer-Entscheidung, deliberately not
    # building _KNOWN_FIELD_COLLISIONS for a single confirmed case):
    # brightsky wins per day whenever it has a non-None value; days with
    # no brightsky value (confirmed to mean "location was outside Germany
    # that day" -- context_collector.py skips the brightsky fetch
    # entirely outside the DE bounding box, no file is ever written for
    # those dates) fall through to weather's value for that same day.
    # No location check needed here -- the fetch-time skip already
    # encodes the location decision into file presence, checking values
    # is equivalent and stays within this function's scope.
    #
    # Single call, not two: both mcp_sql.get_context_range(field=...) and
    # mcp_map.query_context(field=...) already fan out across every
    # source that registers the requested field name in one result (see
    # mcp_sql.get_context_range()'s own docstring, "field-filter fix" --
    # "the filter keeps every source that carries the requested field...
    # so a multi-source field still returns all of its sources"; same
    # fan-out principle on the live branch via gateway_map.get()). No
    # second query needed to reach the other source -- it is already in
    # the same response, keyed by source name under "context".
    if field == "wind_speed_max":
        if _route_query("context") == "sqlite":
            collision_result = mcp_sql.get_context_range(date_from, date_to, field=field)
        else:
            collision_result = mcp_map.query_context(field, date_from, date_to, resolution)

        by_source = collision_result.get("context", {})
        brightsky_candidate = by_source.get("brightsky", {}).get(field)
        weather_candidate = by_source.get("weather", {}).get(field)

        brightsky_by_date = {
            v["date"]: v.get("value")
            for v in (brightsky_candidate.get("values", []) if brightsky_candidate else [])
        }
        weather_by_date = {
            v["date"]: v.get("value")
            for v in (weather_candidate.get("values", []) if weather_candidate else [])
        }
        all_dates = sorted(set(brightsky_by_date) | set(weather_by_date))

        merged_values = []
        field_sources: dict[str, str] = {}
        for day in all_dates:
            day_value = brightsky_by_date.get(day)
            if day_value is not None:
                merged_values.append({"date": day, "value": day_value})
                field_sources[day] = "brightsky"
            else:
                day_value = weather_by_date.get(day)
                merged_values.append({"date": day, "value": day_value})
                if day_value is not None:
                    field_sources[day] = "weather"

        base_candidate = brightsky_candidate or weather_candidate or {}
        result = {
            "context": {
                field: {
                    "fallback": base_candidate.get("fallback", False),
                    "source_resolution": base_candidate.get("source_resolution", "daily"),
                    "values": merged_values,
                }
            },
        }
        result["_meta"] = collision_result.get("_meta", {})
        result["_meta"]["field_sources"] = {field: field_sources}
        return result

    if _route_query("context") == "sqlite":
        return mcp_sql.get_context_range(date_from, date_to, field=field)
    return mcp_map.query_context(field, date_from, date_to, resolution)


def resolve_context_field(field: str) -> dict:
    """
    Resolves a caller-supplied context field name to its canonical
    registered name — the same alias/ambiguity/cross-domain/near-match
    decision order query_context() applies before dispatching a query
    (v1.7.1.4/.12, see that function's own docstring for the full
    history/rationale of each step). Extracted (2026-10-07, v1.7.5),
    same reasoning and same sibling function as
    clients/mcp_health.py::resolve_health_field() — see that
    function's docstring for the real-world finding that motivated
    this.

    Deliberately excludes two things query_context() itself still
    handles before/around this function, not inside it:
      - category-bundle names ("weather"/"pollen"/"air") — not a field
        rename, a different multi-field merged response shape produced
        by _resolve_context_bundle()
      - building the final response envelope ("context"/"_meta" keys)
        — this function is response-envelope-agnostic by design

    Returns one of:
      {"resolved_field": str, "field_resolved_from": str | None,
       "field_used": str | None} — field_resolved_from/field_used are
      both None when `field` was already the exact canonical name (no
      substitution happened); both set to the same pair query_context()
      already uses when an alias/near-match substitution happened.
      {"error": str, "did_you_mean": list[str] | None} — resolution
      failed; caller must not proceed to a data query. did_you_mean is
      only present when difflib found candidates.

    Case-insensitive (2026-10-07) — same reasoning and same approach
    as resolve_health_field()'s sibling docstring note: every registry
    name in this codebase is lowercase, so the input is lowercased
    once, up front. A case-only correction counts as a substitution.
    """
    original_field = field
    field = field.lower()

    if field in CONTEXT_FIELD_ALIASES:
        resolved_field = CONTEXT_FIELD_ALIASES[field]
        return {"resolved_field": resolved_field,
                "field_resolved_from": original_field, "field_used": resolved_field}

    if field in CONTEXT_FIELD_AMBIGUOUS:
        candidates = CONTEXT_FIELD_AMBIGUOUS[field]
        return {
            "error": (
                f"field {field!r} is ambiguous between a daily value and "
                f"a time series -- please specify one of: "
                f"{', '.join(candidates)}"
            ),
            "did_you_mean": candidates,
        }

    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)
    known_health_fields = set(
        mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
    )

    if field not in known_context_fields and field in known_health_fields:
        return {"error": f"field {field!r} belongs to query_health, not query_context"}

    if field not in known_context_fields:
        close_matches = difflib.get_close_matches(
            field, known_context_fields, n=3, cutoff=0.65
        )
        if len(close_matches) == 1:
            resolved_field = close_matches[0]
            return {"resolved_field": resolved_field,
                    "field_resolved_from": original_field, "field_used": resolved_field}

        result = {"error": f"unknown field {field!r}"}
        if close_matches:
            result["did_you_mean"] = close_matches
        return result

    if field != original_field:
        return {"resolved_field": field, "field_resolved_from": original_field, "field_used": field}
    return {"resolved_field": field, "field_resolved_from": None, "field_used": None}


# ── query_context: session history (moved out of the docstring, v1.7.5.1) ──
# Not part of the MCP tool description — the docstring below is what
# mcp.tool() exposes to the calling LLM. Kept verbatim for future sessions.
#
# Query external context data (weather, pollen, air quality) for a
# field over a date range. Fans out across all sources that recognize
# the field.
#
# v1.7.1.3 field-filter fix: field is now passed through to the
# SQLite branch — previously it was silently dropped (this call site
# never forwarded it at all), so every call returned all four
# context categories (weather/brightsky/airquality/pollen) regardless
# of what was asked for, inflating a single-value answer to hundreds
# of KB and confusing small local LLMs summarizing the result. Same
# fix as query_health()'s v1.7.1.1/v1.7.1.2 field-filter, applied
# here with a one-session delay.
#
# v1.7.1.4 unknown-field detection (this session): a field that is
# valid for query_context() but unregistered anywhere in the context
# domain previously returned the same silent {"context": {}} as a
# registered field with no data in the requested range — the caller
# (LLM or human) could not tell "field does not exist" apart from
# "field exists, no data here". This is checked BEFORE the
# _route_query() switch below, so the check applies regardless of
# which branch (sqlite/live) ends up serving the request — the field
# registry itself (mcp_map.list_available_fields) is unrelated to
# that routing decision.
#
# Three unknown-field outcomes, checked in this order:
#   1. Unambiguous near-match against the known context field names
#      (e.g. a typo) -> auto-resolved, field_used replaces the
#      caller's input transparently, but the substitution is always
#      visible via _meta.field_resolved_from / _meta.field_used —
#      never a silent rewrite.
#   2. The field IS registered, but under query_health's domain, not
#      query_context's (e.g. "sleep") -> a domain-specific error
#      naming query_health, no did_you_mean list (a context-domain
#      suggestion would be wrong here).
#   3. Neither of the above (e.g. a category name like "weather", or
#      no close match at all) -> a generic "unknown field" error,
#      with a did_you_mean suggestion list when difflib found any
#      candidates, without one when it found none.
#
# A valid field's result (with or without data in range) is returned
# exactly as before this session — none of the above runs unless
# field is unrecognized.
#
# v1.7.1.5 category bundles (this session): a field value naming a
# known bundle key ("weather"/"pollen"/"air") is resolved BEFORE any
# of the three unknown-field outcomes above -- a bundle name is never
# a registered field itself, so without this check it would always
# fall through to the generic "unknown field" branch. Each bundle
# field is queried individually through the SAME sqlite/live routing
# weiche used everywhere else in this function -- the bundle path
# only adds collection, flattening, and collision tie-breaking on top,
# it does not bypass or duplicate the existing data-access path. See
# _CONTEXT_CATEGORY_BUNDLES above for the priority-list mechanics.
#
# v1.7.1.11 Session 4 -- resolution is decided by the field name
# itself, same principle as query_health(): a "_series" suffix always
# means intraday/timeseries data, a plain field name always means a
# single daily value -- no field in this archive offers both under
# one name, so the caller already knows which shape to expect before
# the query even runs. This holds regardless of which branch
# (sqlite/live) below ends up serving the request -- both branches
# return the same "values" contract (see mcp_sql.get_context_range()
# / clients/mcp_sql.py, and maps/_context_io.py's read_summary_field()/
# read_raw_field() for the underlying {"date","value"} vs.
# {"date","series"} shapes).
#
# v1.7.1.12 -- CONTEXT_FIELD_ALIASES / CONTEXT_FIELD_AMBIGUOUS checked
# here, BEFORE the bundle check, mirroring query_health()'s
# HEALTH_FIELD_ALIASES ordering (an alias hit is more certain than a
# near-match and should not have to pass through the bundle or
# difflib logic). Three outcomes now precede the pre-existing bundle/
# unknown-field handling below:
#   1. CONTEXT_FIELD_ALIASES hit -> auto-resolved, field_used/
#      field_resolved_from set, same as the alias path in
#      query_health().
#   2. CONTEXT_FIELD_AMBIGUOUS hit -> NOT resolved. Returns the
#      existing error/did_you_mean shape with a field-specific error
#      message and the known candidate list as did_you_mean -- no new
#      response shape (see CONTEXT_FIELD_AMBIGUOUS's own comment for
#      the rationale). field_used/field_resolved_from are NOT set.
#   3. Neither -> falls through unchanged to the bundle check and the
#      existing unknown-field difflib logic below.
# See NOTES_v1.7.1.12.md for the full candidate-by-candidate analysis
# behind both tables.
# ────────────────────────────────────────────────────────────────────────
def query_context(field: str, date_from: str, date_to: str,
                   resolution: str = "daily") -> dict:
    """Query external context data (weather, pollen, air quality) for one
    field over a date range. Use query_health for Garmin body data (heart
    rate, sleep, stress, ...) instead; call list_available_fields first if
    the exact field name is unknown.

    field: a context field name (e.g. "temperature_max",
    "pollen_grass_series"), or a category name — "weather", "pollen" or
    "air" — to get the main fields of that category at once. A "_series"
    suffix means intraday timeseries data; a plain name means one value per
    day. date_from/date_to: ISO "YYYY-MM-DD", inclusive. resolution is
    accepted but ignored — the field name alone decides the shape.

    Unknown or ambiguous field names return an "error", often with a
    "did_you_mean" list of candidates. A clear typo or alias is resolved
    automatically; _meta.field_resolved_from / field_used then show what was
    substituted. A field with no data in the range returns empty values, not
    an error."""
    if field in _CONTEXT_CATEGORY_BUNDLES:
        return _resolve_context_bundle(field, date_from, date_to, resolution)

    # v1.7.5 -- resolution logic extracted to resolve_context_field()
    # (see that function's own docstring for why and for the exact
    # decision order, unchanged from before this extraction) so
    # clients/mcp_stats.py can reuse it. Routed through
    # _fetch_context_field() rather than mcp_sql/mcp_map directly
    # (v1.7.1.16) so a resolved field landing on "wind_speed_max" still
    # gets the brightsky/DWD-vs-weather/Open-Meteo priority merge.
    resolution_result = resolve_context_field(field)
    if "error" in resolution_result:
        error_result = {
            "context": {},
            "error": resolution_result["error"],
            "_meta": {},
        }
        if "did_you_mean" in resolution_result:
            error_result["did_you_mean"] = resolution_result["did_you_mean"]
        return error_result

    resolved_field = resolution_result["resolved_field"]
    result = _fetch_context_field(resolved_field, date_from, date_to, resolution)
    result.setdefault("_meta", {})
    if resolution_result["field_resolved_from"] is not None:
        result["_meta"]["field_resolved_from"] = resolution_result["field_resolved_from"]
        result["_meta"]["field_used"] = resolution_result["field_used"]
    return _enrich_with_units(result, "context")
