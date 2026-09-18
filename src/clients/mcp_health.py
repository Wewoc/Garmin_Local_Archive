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
    _CONTEXT_CATEGORY_BUNDLES,
)
from mcp_query_common import _route_query, _enrich_with_units


def query_health(field: str, date_from: str, date_to: str,
                  resolution: str = "daily") -> dict:
    """Query Garmin health data (e.g. heart rate, sleep, stress, body
    battery) for a field over a date range. resolution is "daily" or
    "intraday" — most fields only support one of the two (e.g.
    resting_heart_rate is daily-only, heart_rate_series is
    intraday-only); pass the field name that matches what you want,
    see list_available_fields() for the full list. This parameter is
    accepted for forward compatibility but not currently used to pick
    between two resolutions of the same field, since no field in this
    archive currently offers both — each field's own stored resolution
    already determines whether the answer is a single daily value or
    a full timeseries.

    v1.7.1.1 field-filter fix (2026-08-28 session): field is now
    passed through to the SQLite branch — previously it was silently
    dropped, so every call returned all ~26 health fields regardless
    of what was asked for, including this archive's intraday *_series
    fields (full day-long timeseries), inflating a single-value
    answer to hundreds of KB and confusing small local LLMs
    summarizing the result.

    v1.7.1.6 unit field: every field in the returned result now
    carries a "unit" key alongside "values"/"fallback"/
    "source_resolution" — see FIELD_UNITS in mcp_field_registry.py. Applied AFTER the
    routing weiche below, so it covers both branches identically
    (today, only the SQLite branch is ever actually taken — see
    _route_query()'s docstring).

    v1.7.1.9 unknown-field detection (this session): mirrors
    query_context()'s v1.7.1.4 fix, applied here with a delayed
    session (see that function's docstring for the original rationale
    -- a valid-but-dataless field and an unregistered field previously
    returned the identical silent {"health": {}}, leaving the caller
    unable to tell the two apart). Checked BEFORE the _route_query()
    switch below, so it applies regardless of which branch (sqlite/
    live) ends up serving the request -- the field registry itself
    (mcp_map.list_available_fields) is unrelated to that routing
    decision.

    Three unknown-field outcomes, checked in this order:
      1. Unambiguous near-match against the known health field names
         (e.g. a typo) -> auto-resolved, field_used replaces the
         caller's input transparently, but the substitution is always
         visible via _meta.field_resolved_from / _meta.field_used —
         never a silent rewrite.
      2. The field IS registered, but under query_context's domain,
         not query_health's (e.g. "temperature_max") -> a
         domain-specific error naming query_context, no did_you_mean
         list (a health-domain suggestion would be wrong here).
      3. Neither of the above (no close match, and not a
         query_context field either) -> a generic "unknown field"
         error, with a did_you_mean suggestion list when difflib found
         any candidates, without one when it found none.

    A valid field's result (with or without data in range) is returned
    exactly as before this session — none of the above runs unless
    field is unrecognized.

    Deliberately NOT addressed here (see AKTIONSPLAN_v1.7.1.9_
    health_fallback.md Abschnitt 3/4 for the full analysis): a model
    that picks a completely unrelated but real, registered field
    instead of a near-match typo (verified empirically against the
    2026-09-05 test run's Hermes3 cases, e.g. resting_heart_rate
    returned for a steps question) is not a field-registry problem —
    no near-match exists for the fallback to catch, since the wrong
    field is itself a valid, unrelated field name. Tracked as a
    parking-lot item (query_health docstring example-field guidance),
    not pulled into this fix.

    v1.7.1.9 Session 2 -- sleep_score fan-out: "sleep_score" is itself
    an already-valid, registered field (unlike the alias candidates
    below), so it would never reach the unknown-field checks above --
    it always short-circuits straight to the normal valid-field path.
    Checked here, BEFORE the bundle check, precisely because it is
    valid and would otherwise never trigger any of the outcomes below.
    Fans out to the two closely related fields sleep_score_feedback
    and sleep_score_qualifier and returns all three together in the
    same {"garmin": {field: {...}}} shape a normal multi-field result
    already has -- no new result shape, _enrich_with_units() handles
    it unchanged. _meta.field_resolved_from is set to "sleep_score" so
    the fan-out is visible; no field_used, since all three delivered
    field names are already the dict's own keys, unlike the 1:1 alias
    case where the substitution would otherwise be invisible. A direct
    call to "sleep_score_feedback" or "sleep_score_qualifier" is NOT
    affected -- only the exact bare "sleep_score" triggers this.

    v1.7.1.9 Session 2 -- short-form alias mapping: three short-form
    field names (steps, hrv, hill) sit far enough below any workable
    difflib cutoff against their real target field names (steps_series,
    hrv_last_night, hill_score -- confirmed down to cutoff=0.7, see
    NOTES_v1.7.1.9.md Session 2) that no cutoff tuning can catch them
    without introducing new ambiguities elsewhere. HEALTH_FIELD_ALIASES
    below resolves these explicitly, checked before outcome 1's
    near-match logic (an alias hit is more certain than a near-match
    and should not have to pass through it). "spo2" was considered and
    explicitly excluded (real collision between spo2_avg and
    spo2_series, no reliable disambiguation signal available -- see
    NOTES_v1.7.1.9.md Session 2 for the full analysis)."""
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

    if field in HEALTH_FIELD_ALIASES:
        resolved_field = HEALTH_FIELD_ALIASES[field]
        if _route_query("health") == "sqlite":
            result = mcp_sql.get_health_range(date_from, date_to, field=resolved_field)
        else:
            result = mcp_map.query_health(resolved_field, date_from, date_to, resolution)
        result.setdefault("_meta", {})
        result["_meta"]["field_resolved_from"] = field
        result["_meta"]["field_used"] = resolved_field
        return _enrich_with_units(result, "health")

    if field in HEALTH_FIELD_AMBIGUOUS:
        # v1.7.1.12 -- checked here, BEFORE the bundle/difflib logic
        # below, same ordering principle as HEALTH_FIELD_ALIASES above
        # (a known-ambiguous hit is more certain than letting it fall
        # through to whatever difflib happens to resolve at the current
        # cutoff). NOT resolved -- no field_used/field_resolved_from,
        # the caller must re-ask with the exact name. See
        # HEALTH_FIELD_AMBIGUOUS's own comment above for why "spo2" and
        # "stress" are here and "respiration" deliberately is not.
        candidates = HEALTH_FIELD_AMBIGUOUS[field]
        return {
            "health": {},
            "error": (
                f"field {field!r} is ambiguous between a daily value and "
                f"a time series -- please specify one of: "
                f"{', '.join(candidates)}"
            ),
            "did_you_mean": candidates,
            "_meta": {},
        }

    if field in _CONTEXT_CATEGORY_BUNDLES:
        # A bundle name (e.g. "weather") is a query_context-only
        # concept -- it is never itself a registered health field, so
        # without this check it would silently fall through to outcome
        # 3 below and likely produce a did_you_mean suggestion against
        # unrelated health fields. Routed to the same domain-confusion
        # error as outcome 2, since a bundle name IS something
        # query_context understands, just not under this tool.
        return {
            "health": {},
            "error": f"field {field!r} belongs to query_context, not query_health",
            "_meta": {},
        }

    known_health_fields = set(
        mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
    )

    # v1.7.1.12 -- Domain-Einordnung VOR dem Aehnlichkeitsvergleich
    # (Timo-Entscheidung, siehe NOTES_v1.7.1.12.md Ziel 5): known_
    # context_fields wird jetzt hier, VOR dem difflib-Block, berechnet
    # und geprueft -- vorher lief dieser Check erst NACH dem
    # len(close_matches)==1-Zweig, wodurch ein exaktes, registriertes
    # Context-Feld bei cutoff=0.65 regelmaessig faelschlich auf ein
    # aehnlich benanntes Health-Feld auto-resolved wurde, BEVOR die
    # Domain-Confusion-Pruefung ueberhaupt erreicht werden konnte
    # (z.B. "sunshine_duration" -> faelschlich "sleep_duration",
    # "pressure_avg"/"pressure_avg_series" -> faelschlich "stress_avg"/
    # "stress_series"). Ein Feld, das exakt in der anderen Domain
    # registriert ist, wird jetzt sofort korrekt eingeordnet, ohne dass
    # difflib je die Chance bekommt es zuerst der falschen Domain
    # zuzuordnen -- Einordnung vor Aehnlichkeitsvergleich, nicht danach.
    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)

    if field not in known_health_fields and field in known_context_fields:
        return {
            "health": {},
            "error": f"field {field!r} belongs to query_context, not query_health",
            "_meta": {},
        }

    if field not in known_health_fields:
        # v1.7.1.11 Session 5 (Testlauf, 2026-09-09) -- cutoff testweise
        # von 0.8 auf 0.65 gesenkt, um empirisch zu pruefen, ob sich
        # damit mehr echte Nahtreffer (z.B. steps -> steps_series,
        # Wortumstellungen wie min_temperature -> temperature_min)
        # zuverlaessig aufloesen lassen, ohne unerwuenschte
        # Fehltreffer bei kurzen/generischen Feldnamen zu erzeugen.
        # Kalibriert gegen die 25 haeufigsten requested/expected-
        # Diskrepanzen aus Lauf 11 (context-Domaene): 0.65 deckt ~52%
        # der gewichteten Faelle ab (0.80: ~5%), mit dem groessten
        # Einzelsprung gegenueber 0.70. Reiner Testwert fuer diese
        # Session -- KEINE endgueltige Entscheidung. Vor v1.7.1.10
        # wurde eine generelle Cutoff-Absenkung bereits einmal geprueft
        # und wegen Fehltreffer-Risiko bewusst verworfen -- dieser
        # Lauf soll das empirisch nachpruefen, nicht ueberschreiben.
        close_matches = difflib.get_close_matches(
            field, known_health_fields, n=3, cutoff=0.65
        )
        if len(close_matches) == 1:
            resolved_field = close_matches[0]
            if _route_query("health") == "sqlite":
                result = mcp_sql.get_health_range(date_from, date_to, field=resolved_field)
            else:
                result = mcp_map.query_health(resolved_field, date_from, date_to, resolution)
            result.setdefault("_meta", {})
            result["_meta"]["field_resolved_from"] = field
            result["_meta"]["field_used"] = resolved_field
            return _enrich_with_units(result, "health")

        error_result = {
            "health": {},
            "error": f"unknown field {field!r}",
            "_meta": {},
        }
        if close_matches:
            error_result["did_you_mean"] = close_matches
        return error_result

    if _route_query("health") == "sqlite":
        result = mcp_sql.get_health_range(date_from, date_to, field=field)
    else:
        result = mcp_map.query_health(field, date_from, date_to, resolution)
    return _enrich_with_units(result, "health")
