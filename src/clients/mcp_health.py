#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_health.py
Garmin Local Archive — MCP query_health tool

Extracted from clients/mcp_server.py (Codereview v1.7.0.1, Baustein 2.2)
— the query_health() MCP tool: SQLite-vs-live routing, field-alias
resolution, ambiguous-field detection, difflib fuzzy-match, sleep_score
fan-out. Body is verbatim from the former mcp_server.py::query_health()
— no self/panel rewrite needed here (was already a plain module-level
function, unlike the app/popups/ extractions in Baustein 1).

Deliberately undecorated here — no `@mcp.tool()` on this definition,
since the shared `mcp` FastMCP instance lives in mcp_server.py and
importing it here would recreate the exact circular import this split
is designed to avoid (see mcp_query_common.py's docstring). Instead,
mcp_server.py imports this plain function and applies the decorator
programmatically: `query_health = mcp.tool()(query_health)` — a
Python decorator is just `f = dec(f)` under the hood, so this is
behaviourally identical to `@mcp.tool()` at the definition site, and
mcp_server.query_health keeps resolving exactly as before (verified
against tests/test_mcp.py, which does `import mcp_server` +
`mcp_server.query_health(...)` — qualified module access, not
`from mcp_server import query_health` — so it needs zero changes).

_CONTEXT_CATEGORY_BUNDLES imported from mcp_field_registry.py (not from
a hypothetical mcp_context.py) — this health-domain function only needs
it for one negative check ("this field name belongs to a context
bundle, not health"), living in the neutral shared registry avoids a
direct dependency on the context-domain file.
"""

import difflib

from maps import mcp_map
import mcp_sql
from mcp_field_registry import (
    HEALTH_FIELD_ALIASES,
    HEALTH_FIELD_AMBIGUOUS,
    RAW_FIELD_COUNTERPARTS,
    _CONTEXT_CATEGORY_BUNDLES,
)
from mcp_query_common import _route_query, _enrich_with_units, _format_counterparts


def resolve_health_field(field: str) -> dict:
    """
    Resolves a caller-supplied health field name to its canonical
    registered name — the same alias/ambiguity/cross-domain/near-match
    decision order query_health() applies before dispatching a query
    (v1.7.1.9/.12, see that function's own docstring for the full
    history/rationale of each step). Extracted (2026-10-07, v1.7.5) so
    clients/mcp_stats.py's baselines()/anomalies() can resolve a field
    name the same way query_health() does, instead of requiring an
    exact canonical name — found necessary via a real LLM test run
    where most models naturally said "hrv"/"body_battery" rather than
    the canonical "hrv_last_night"/"body_battery_max", which those two
    tools previously could not resolve at all (PROTOKOLL.md, 2026-10-07,
    "Reihenfolge-Korrektur: Feldauflösungs-Extraktion vorgezogen").

    v1.7.5.5: a raw-passthrough field name (query_raw's fields, e.g.
    "floors", "lactate_threshold") is recognised after the cross-domain
    checks and before the near-match step and returns an error pointing to
    query_raw — with the processed counterpart as did_you_mean where one
    exists (RAW_FIELD_COUNTERPARTS in mcp_field_registry.py).

    Deliberately excludes two things query_health() itself still
    handles before/around this function, not inside it:
      - the "sleep_score" fan-out (not a field rename, a different
        multi-field merged response shape)
      - building the final response envelope ("health"/"_meta" keys) —
        this function is response-envelope-agnostic by design, so a
        caller with a different envelope (e.g. mcp_stats.py's
        baselines()/anomalies()) can use the same resolution logic.

    Returns one of:
      {"resolved_field": str, "field_resolved_from": str | None,
       "field_used": str | None} — field_resolved_from/field_used are
      both None when `field` was already the exact canonical name (no
      substitution happened); both set to the same pair query_health()
      already uses when an alias/near-match substitution happened.
      {"error": str, "did_you_mean": list[str] | None} — resolution
      failed; caller must not proceed to a data query. did_you_mean is
      only present when difflib found candidates.

    Case-insensitive (2026-10-07, same real LLM test run as the
    extraction itself): every registry/field name in this codebase is
    lowercase (verified, no exception), so the caller-supplied field is
    lowercased once, up front, for every lookup below — "HRV" now
    resolves exactly like "hrv". A case-only correction counts as a
    substitution (field_resolved_from/field_used set), same as an
    alias or near-match hit, since the caller's original input was not
    used verbatim.
    """
    original_field = field
    field = field.lower()

    if field in HEALTH_FIELD_ALIASES:
        resolved_field = HEALTH_FIELD_ALIASES[field]
        return {"resolved_field": resolved_field,
                "field_resolved_from": original_field, "field_used": resolved_field}

    if field in HEALTH_FIELD_AMBIGUOUS:
        candidates = HEALTH_FIELD_AMBIGUOUS[field]
        return {
            "error": (
                f"field {field!r} is ambiguous between a daily value and "
                f"a time series -- please specify one of: "
                f"{', '.join(candidates)}"
            ),
            "did_you_mean": candidates,
        }

    if field in _CONTEXT_CATEGORY_BUNDLES:
        return {"error": f"field {field!r} belongs to query_context, not query_health"}

    known_health_fields = set(
        mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
    )
    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)

    if field not in known_health_fields and field in known_context_fields:
        return {"error": f"field {field!r} belongs to query_context, not query_health"}

    # v1.7.5.5 -- a raw-passthrough field name is neither a health field nor
    # a near-match candidate: checked BEFORE difflib so it is never silently
    # resolved to a similar processed field (intensity_minutes_data ->
    # intensity_min_moderate) and never ends in a bare "unknown field"
    # dead end (lactate_threshold). Where a processed counterpart exists it
    # is named and returned as did_you_mean.
    if field not in known_health_fields and field in set(mcp_map.list_raw_fields("health")["health"]):
        counterparts = RAW_FIELD_COUNTERPARTS.get(field)
        if counterparts:
            return {
                "error": (
                    f"field {field!r} is a raw field -- use query_raw; the "
                    f"processed value is available as {_format_counterparts(counterparts)}"
                ),
                "did_you_mean": list(counterparts),
            }
        return {"error": f"field {field!r} is a raw field -- use query_raw"}

    if field not in known_health_fields:
        close_matches = difflib.get_close_matches(
            field, known_health_fields, n=3, cutoff=0.65
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


# ── query_health: session history (moved out of the docstring, v1.7.5.1) ──
# Not part of the MCP tool description — the docstring below is what
# mcp.tool() exposes to the calling LLM. Kept verbatim for future sessions.
# Note (v1.7.5.1): the text below is verbatim history. Where it names "steps"
# as an alias for steps_series (v1.7.1.9), that is superseded — since
# v1.7.1.12 "steps" is in HEALTH_FIELD_AMBIGUOUS (mcp_field_registry.py):
# steps_total / steps_series, returned as error + did_you_mean.
#
# Query Garmin health data (e.g. heart rate, sleep, stress, body
# battery) for a field over a date range. resolution is "daily" or
# "intraday" — most fields only support one of the two (e.g.
# resting_heart_rate is daily-only, heart_rate_series is
# intraday-only); pass the field name that matches what you want,
# see list_available_fields() for the full list. This parameter is
# accepted for forward compatibility but not currently used to pick
# between two resolutions of the same field, since no field in this
# archive currently offers both — each field's own stored resolution
# already determines whether the answer is a single daily value or
# a full timeseries.
#
# v1.7.1.1 field-filter fix (2026-08-28 session): field is now
# passed through to the SQLite branch — previously it was silently
# dropped, so every call returned all ~26 health fields regardless
# of what was asked for, including this archive's intraday *_series
# fields (full day-long timeseries), inflating a single-value
# answer to hundreds of KB and confusing small local LLMs
# summarizing the result.
#
# v1.7.1.6 unit field: every field in the returned result now
# carries a "unit" key alongside "values"/"fallback"/
# "source_resolution" — see FIELD_UNITS in mcp_field_registry.py. Applied AFTER the
# routing weiche below, so it covers both branches identically
# (today, only the SQLite branch is ever actually taken — see
# _route_query()'s docstring).
#
# v1.7.1.9 unknown-field detection (this session): mirrors
# query_context()'s v1.7.1.4 fix, applied here with a delayed
# session (see that function's docstring for the original rationale
# -- a valid-but-dataless field and an unregistered field previously
# returned the identical silent {"health": {}}, leaving the caller
# unable to tell the two apart). Checked BEFORE the _route_query()
# switch below, so it applies regardless of which branch (sqlite/
# live) ends up serving the request -- the field registry itself
# (mcp_map.list_available_fields) is unrelated to that routing
# decision.
#
# Three unknown-field outcomes, checked in this order:
#   1. Unambiguous near-match against the known health field names
#      (e.g. a typo) -> auto-resolved, field_used replaces the
#      caller's input transparently, but the substitution is always
#      visible via _meta.field_resolved_from / _meta.field_used —
#      never a silent rewrite.
#   2. The field IS registered, but under query_context's domain,
#      not query_health's (e.g. "temperature_max") -> a
#      domain-specific error naming query_context, no did_you_mean
#      list (a health-domain suggestion would be wrong here).
#   3. Neither of the above (no close match, and not a
#      query_context field either) -> a generic "unknown field"
#      error, with a did_you_mean suggestion list when difflib found
#      any candidates, without one when it found none.
#
# A valid field's result (with or without data in range) is returned
# exactly as before this session — none of the above runs unless
# field is unrecognized.
#
# Deliberately NOT addressed here (see AKTIONSPLAN_v1.7.1.9_
# health_fallback.md Abschnitt 3/4 for the full analysis): a model
# that picks a completely unrelated but real, registered field
# instead of a near-match typo (verified empirically against the
# 2026-09-05 test run's Hermes3 cases, e.g. resting_heart_rate
# returned for a steps question) is not a field-registry problem —
# no near-match exists for the fallback to catch, since the wrong
# field is itself a valid, unrelated field name. Tracked as a
# parking-lot item (query_health docstring example-field guidance),
# not pulled into this fix.
#
# v1.7.1.9 Session 2 -- sleep_score fan-out: "sleep_score" is itself
# an already-valid, registered field (unlike the alias candidates
# below), so it would never reach the unknown-field checks above --
# it always short-circuits straight to the normal valid-field path.
# Checked here, BEFORE the bundle check, precisely because it is
# valid and would otherwise never trigger any of the outcomes below.
# Fans out to the two closely related fields sleep_score_feedback
# and sleep_score_qualifier and returns all three together in the
# same {"garmin": {field: {...}}} shape a normal multi-field result
# already has -- no new result shape, _enrich_with_units() handles
# it unchanged. _meta.field_resolved_from is set to "sleep_score" so
# the fan-out is visible; no field_used, since all three delivered
# field names are already the dict's own keys, unlike the 1:1 alias
# case where the substitution would otherwise be invisible. A direct
# call to "sleep_score_feedback" or "sleep_score_qualifier" is NOT
# affected -- only the exact bare "sleep_score" triggers this.
#
# v1.7.1.9 Session 2 -- short-form alias mapping: three short-form
# field names (steps, hrv, hill) sit far enough below any workable
# difflib cutoff against their real target field names (steps_series,
# hrv_last_night, hill_score -- confirmed down to cutoff=0.7, see
# NOTES_v1.7.1.9.md Session 2) that no cutoff tuning can catch them
# without introducing new ambiguities elsewhere. HEALTH_FIELD_ALIASES
# below resolves these explicitly, checked before outcome 1's
# near-match logic (an alias hit is more certain than a near-match
# and should not have to pass through it). "spo2" was considered and
# explicitly excluded (real collision between spo2_avg and
# spo2_series, no reliable disambiguation signal available -- see
# NOTES_v1.7.1.9.md Session 2 for the full analysis).
# ────────────────────────────────────────────────────────────────────────
def query_health(field: str, date_from: str, date_to: str,
                  resolution: str = "daily") -> dict:
    """Query Garmin health data (e.g. heart rate, sleep, stress, body
    battery, steps) for one field over a date range. Use query_context
    instead for weather, pollen and air quality; call list_available_fields
    first if the exact field name is unknown.

    field: a health field name, e.g. "resting_heart_rate", "hrv_last_night",
    "body_battery_max", "steps_series". A "_series" suffix means intraday
    timeseries data; a plain name means one value per day. Pass the field
    that matches what you want — "sleep_score" returns three related
    fields together (sleep_score, sleep_score_feedback,
    sleep_score_qualifier). date_from/date_to: ISO "YYYY-MM-DD", inclusive.
    resolution is accepted but ignored — the field name alone decides the
    shape.

    Unknown or ambiguous field names return an "error", often with a
    "did_you_mean" list of candidates (e.g. "steps" or "stress" without
    suffix: choose the daily or the _series variant). A clear typo or alias
    is resolved automatically; _meta.field_resolved_from / field_used then
    show what was substituted. A field with no data in the range returns
    empty values, not an error. Every field carries a "unit"."""
    if field == "sleep_score":
        # Correction (v1.7.1.9 Session 2, post-Lauf-8): get_health_range()
        # already reads through the source-name layer itself (see its own
        # docstring, "v1.7.1.1 Bug-C correction") and returns
        # {"health": {field: {"values": ...}}} directly -- no "garmin" key
        # on this return value. The original version of this block wrongly
        # assumed an extra {"garmin": {...}} layer here (confusing this
        # call's return shape with health_map.get()'s own live-side shape,
        # which DOES nest under a source name), so every extraction silently
        # produced None and merged stayed empty on all 5 models / 29 calls
        # in the Lauf-8 test run. Fixed to read the field straight off
        # "health", and to build the same flattened shape
        # _resolve_context_bundle() already produces (which
        # _enrich_with_units() already recognizes as its documented
        # "already-flattened shape" case -- no third shape introduced).
        fan_out_fields = ["sleep_score", "sleep_score_feedback", "sleep_score_qualifier"]
        merged: dict = {}
        meta: dict = {}
        for fan_field in fan_out_fields:
            if _route_query("health") == "sqlite":
                fan_result = mcp_sql.get_health_range(date_from, date_to, field=fan_field)
            else:
                fan_result = mcp_map.query_health(fan_field, date_from, date_to, resolution)
            meta = fan_result.get("_meta", meta)
            field_value = fan_result.get("health", {}).get(fan_field)
            if field_value is not None:
                merged[fan_field] = field_value
        result = {"health": merged}
        result["_meta"] = meta if meta else {}
        result["_meta"]["field_resolved_from"] = "sleep_score"
        return _enrich_with_units(result, "health")

    # v1.7.5 -- resolution logic extracted to resolve_health_field()
    # (see that function's own docstring for why and for the exact
    # decision order, unchanged from before this extraction) so
    # clients/mcp_stats.py's baselines()/anomalies() can reuse it.
    resolution_result = resolve_health_field(field)
    if "error" in resolution_result:
        error_result = {
            "health": {},
            "error": resolution_result["error"],
            "_meta": {},
        }
        if "did_you_mean" in resolution_result:
            error_result["did_you_mean"] = resolution_result["did_you_mean"]
        return error_result

    resolved_field = resolution_result["resolved_field"]
    if _route_query("health") == "sqlite":
        result = mcp_sql.get_health_range(date_from, date_to, field=resolved_field)
    else:
        result = mcp_map.query_health(resolved_field, date_from, date_to, resolution)
    result.setdefault("_meta", {})
    if resolution_result["field_resolved_from"] is not None:
        result["_meta"]["field_resolved_from"] = resolution_result["field_resolved_from"]
        result["_meta"]["field_used"] = resolution_result["field_used"]
    return _enrich_with_units(result, "health")
