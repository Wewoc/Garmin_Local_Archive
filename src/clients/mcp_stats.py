#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_stats.py
Garmin Local Archive — MCP statistical support tools (v1.7.5)

baselines()/anomalies()/gaps() (Block A) — three MCP tools reading the
Baseline/Anomaly cache (mcp_sql.mcp_health_baselines, populated by
mcp_update.py::_sync_health_baselines(), pauschal recompute, see that
function's own docstring for the staleness-fix reasoning) and the
Gap-Detection read-time functions (mcp_sql.get_gaps_range()).
correlate() (Block B) is a fourth tool, added 2026-10-08 — lag
correlation between two arbitrary fields (health or context, any
combination), computed fresh per call via the existing query_health()/
query_context() data paths, no new cache/broker. Same "one new module
for the new statistical tools" grouping ROADMAP.md's v1.7.5 section
sketches.

Deliberately undecorated here — no `@mcp.tool()` on these definitions,
same reasoning as clients/mcp_health.py/mcp_context.py: the shared `mcp`
FastMCP instance lives in mcp_server.py, which imports these plain
functions and applies the decorator programmatically
(`baselines = mcp.tool()(baselines)`), avoiding the circular import that
defining them directly in mcp_server.py with `@mcp.tool()` would not
have had a problem with, but keeping this module import-clean relative
to mcp_server.py matches the established split.

anomalies()'s streak detection (maintainer, 2026-10-07: single-day outliers
alone miss a slow, several-day drift that never individually crosses the
+/-3-stdev threshold) needs the actual per-day values, not just the
stored anomaly_flag -- it reads both mcp_sql.get_health_baselines_range()
and mcp_sql.get_health_range() for the same range, same "no extra query
beyond what's already loaded" principle ROADMAP.md names for this tool.

Field resolution (v1.7.5, added after the real-archive LLM test run
2026-10-07 -- PROTOKOLL.md, "Reihenfolge-Korrektur: Feldauflösungs-
Extraktion vorgezogen"): baselines()/anomalies() originally required
the exact canonical field name (e.g. "hrv_last_night",
"body_battery_max"), unlike query_health(). A real test run against
three models showed this silently failing for the large majority of
HRV/Body-Battery requests, since models naturally said "hrv"/
"body_battery" -- the short, non-canonical forms query_health() has
always resolved via its alias/near-match logic. Both tools now call
mcp_health.resolve_health_field() first, the same resolution
clients/mcp_health.py::query_health() uses (extracted there for
exactly this reuse).
"""

import datetime
import statistics

import mcp_sql
from mcp_health import resolve_health_field
from mcp_context import resolve_context_field, _fetch_context_field
from mcp_query_common import _enrich_with_units

MIN_STREAK_DAYS = 5  # ROADMAP.md: ">=5 consecutive days on one side of the mean"
MAX_LAG_DAYS = 7  # ROADMAP.md: "lag support (-7 to +7 days)"


def baselines(field: str, date_from: str, date_to: str) -> dict:
    """Query the rolling 90-day baseline and statistical reference range
    (mean +/- 3 standard deviations) for one health field over a date
    range. Use this to see what "normal" has looked like for a field
    recently, or alongside query_health() to compare today's value
    against the person's own history rather than a fixed threshold."""
    resolution_result = resolve_health_field(field)
    if "error" in resolution_result:
        error_result = {
            "health_baselines": {},
            "error": resolution_result["error"],
            "_meta": {},
        }
        if "did_you_mean" in resolution_result:
            error_result["did_you_mean"] = resolution_result["did_you_mean"]
        return error_result

    resolved_field = resolution_result["resolved_field"]
    result = mcp_sql.get_health_baselines_range(date_from, date_to, field=resolved_field)
    if resolution_result["field_resolved_from"] is not None:
        result.setdefault("_meta", {})
        result["_meta"]["field_resolved_from"] = resolution_result["field_resolved_from"]
        result["_meta"]["field_used"] = resolution_result["field_used"]
    return _enrich_with_units(result, "health_baselines")


def anomalies(field: str, date_from: str, date_to: str) -> dict:
    """Find days where one health field broke from its own recent
    pattern. Returns two kinds of findings: "outliers" (single days far
    outside the normal range) and "streaks" (five or more consecutive
    days consistently above or below the baseline average, even if none
    of them individually qualifies as an outlier -- useful for catching
    a slow drift, e.g. a gradually rising resting heart rate)."""
    resolution_result = resolve_health_field(field)
    if "error" in resolution_result:
        error_result = {
            "field": field,
            "outliers": [],
            "streaks": [],
            "error": resolution_result["error"],
            "_meta": {},
        }
        if "did_you_mean" in resolution_result:
            error_result["did_you_mean"] = resolution_result["did_you_mean"]
        return error_result
    field = resolution_result["resolved_field"]

    baseline_result = mcp_sql.get_health_baselines_range(date_from, date_to, field=field)
    baseline_entries = baseline_result.get("health_baselines", {}).get(field, {}).get("values", [])
    meta = baseline_result.get("_meta", {})
    if resolution_result["field_resolved_from"] is not None:
        meta["field_resolved_from"] = resolution_result["field_resolved_from"]
        meta["field_used"] = resolution_result["field_used"]

    if not baseline_entries:
        return {"field": field, "outliers": [], "streaks": [], "_meta": meta}

    health_result = mcp_sql.get_health_range(date_from, date_to, field=field)
    health_entries = health_result.get("health", {}).get(field, {}).get("values", [])
    value_by_date = {e["date"]: e.get("value") for e in health_entries}

    baseline_by_date = {e["date"]: e for e in baseline_entries}
    sorted_dates = sorted(baseline_by_date)

    outliers = [d for d in sorted_dates if baseline_by_date[d].get("anomaly_flag")]

    streaks = []
    current_dates: list[str] = []
    current_side: str | None = None
    for day in sorted_dates:
        value = value_by_date.get(day)
        baseline_avg = baseline_by_date[day].get("baseline_avg")
        if value is None or baseline_avg is None or value == baseline_avg:
            side = None  # no data, no baseline yet, or exactly on the mean -- breaks any streak
        else:
            side = "above" if value > baseline_avg else "below"

        if side is not None and side == current_side:
            current_dates.append(day)
        else:
            if len(current_dates) >= MIN_STREAK_DAYS:
                streaks.append({"side": current_side, "dates": list(current_dates)})
            current_dates = [day] if side is not None else []
            current_side = side
    if len(current_dates) >= MIN_STREAK_DAYS:
        streaks.append({"side": current_side, "dates": current_dates})

    return {"field": field, "outliers": outliers, "streaks": streaks, "_meta": meta}


def gaps(domain: str, date_from: str, date_to: str) -> dict:
    """List days with no usable data over a date range. domain is
    "health", "context", or "fit" ("fit" always degrades to "domain not
    yet available" -- no FIT pipeline exists yet). A gap is a day that
    was never synced at all, or was synced but came back empty/failed."""
    return mcp_sql.get_gaps_range(domain, date_from, date_to)


def _extract_context_values(fetch_result: dict, field: str) -> list[dict]:
    """
    _fetch_context_field()'s own return shape is inconsistent by
    design (mirrors the same two shapes _enrich_with_units() already
    documents handling): the wind_speed_max collision-merge branch
    returns an already-flattened {"context": {field: {"values": ...}}},
    every other field falls through to mcp_sql.get_context_range()
    unchanged, which nests one level deeper by source:
    {"context": {source: {field: {"values": ...}}}}. Checks the
    flattened shape first, then falls back to scanning sources for the
    first one that actually carries `field` with real "values" --
    every context field in this archive except wind_speed_max has
    exactly one source, so "first source found" never has to choose
    between competing candidates in practice.
    """
    domain_dict = fetch_result.get("context", {})
    direct = domain_dict.get(field)
    if isinstance(direct, dict) and "values" in direct:
        return direct["values"]
    for source_fields in domain_dict.values():
        if not isinstance(source_fields, dict):
            continue
        field_entry = source_fields.get(field)
        if isinstance(field_entry, dict) and "values" in field_entry:
            return field_entry["values"]
    return []


def _resolve_and_fetch_field(field: str, date_from: str, date_to: str) -> dict:
    """
    Block B helper: resolves `field` as either a health or a context
    field (tried in that order -- arbitrary, neither domain takes
    priority in the ROADMAP.md spec, health first is simply a
    deterministic tie-break) via the same resolve_health_field()/
    resolve_context_field() correlate()'s siblings already use, then
    fetches its per-day numeric values.

    Health fetch goes straight through mcp_sql.get_health_range() (one
    source, "garmin", no merge needed). Context fetch goes through
    mcp_context._fetch_context_field() rather than mcp_sql.get_context_range()
    directly, so a field registered by more than one source (e.g.
    wind_speed_max under both weather and brightsky) gets the same
    per-day source-priority merge query_context() itself would apply --
    no second, simpler-but-wrong context merge invented here.

    Returns {"domain": "health" | "context", "field": str,
    "values": {date: float}, "field_resolved_from": str | None,
    "field_used": str | None} on success (values already filtered to
    numeric, non-bool entries only -- a categorical/text field
    resolves but contributes an empty values dict, same "no crash,
    just no usable data" degrade as _sync_health_baselines() uses for
    the same reason), or {"error": str, "did_you_mean": list[str] | None}
    if `field` resolves in neither domain.
    """
    health_resolution = resolve_health_field(field)
    if "resolved_field" in health_resolution:
        resolved = health_resolution["resolved_field"]
        fetch_result = mcp_sql.get_health_range(date_from, date_to, field=resolved)
        entries = fetch_result.get("health", {}).get(resolved, {}).get("values", [])
        values = {
            e["date"]: e["value"] for e in entries
            if e.get("value") is not None
            and isinstance(e["value"], (int, float)) and not isinstance(e["value"], bool)
        }
        return {
            "domain": "health", "field": resolved, "values": values,
            "field_resolved_from": health_resolution["field_resolved_from"],
            "field_used": health_resolution["field_used"],
        }

    context_resolution = resolve_context_field(field)
    if "resolved_field" in context_resolution:
        resolved = context_resolution["resolved_field"]
        fetch_result = _fetch_context_field(resolved, date_from, date_to, "daily")
        entries = _extract_context_values(fetch_result, resolved)
        values = {
            e["date"]: e["value"] for e in entries
            if e.get("value") is not None
            and isinstance(e["value"], (int, float)) and not isinstance(e["value"], bool)
        }
        return {
            "domain": "context", "field": resolved, "values": values,
            "field_resolved_from": context_resolution["field_resolved_from"],
            "field_used": context_resolution["field_used"],
        }

    # Neither domain resolved the field -- surface whichever error
    # carries more specific guidance: a cross-domain hint from either
    # side means the field IS known, just not where expected, so that
    # message is more useful than a generic "unknown field" from the
    # other side.
    if "did_you_mean" in context_resolution and "did_you_mean" not in health_resolution:
        return context_resolution
    return health_resolution


def _rank(values: list[float]) -> list[float]:
    """Spearman's rank transform, ties resolved to their shared average
    rank (standard convention -- e.g. two tied-lowest values both get
    rank 1.5, not 1 and 2) -- no scipy dependency, Python's own
    statistics.correlation() applied to these ranks reproduces
    Spearman's rho."""
    sorted_values = sorted(values)
    n = len(values)
    rank_of = {}
    i = 0
    while i < n:
        j = i
        while j < n and sorted_values[j] == sorted_values[i]:
            j += 1
        average_rank = (i + j + 1) / 2  # 1-indexed average rank over [i, j)
        for k in range(i, j):
            rank_of[sorted_values[k]] = average_rank
        i = j
    return [rank_of[v] for v in values]


def correlate(field_a: str, field_b: str, date_from: str, date_to: str,
              lag_days: int = 0) -> dict:
    """Measure how closely two fields (health or context, any
    combination) move together over a date range -- e.g. does stress
    correlate with pollen count, or resting heart rate with sleep
    duration. lag_days (-7 to +7) shifts field_b relative to field_a:
    a positive lag compares field_a on a given day against field_b
    `lag_days` days LATER (useful for "does X today predict Y a few
    days from now" questions); 0 (the default) compares same-day
    values. Returns both Pearson (linear relationship) and Spearman
    (monotonic relationship, more robust to outliers) correlation
    coefficients, each in [-1, 1], plus how many overlapping data
    points they were computed from."""
    if not -MAX_LAG_DAYS <= lag_days <= MAX_LAG_DAYS:
        return {"error": f"lag_days must be between -{MAX_LAG_DAYS} and {MAX_LAG_DAYS}, got {lag_days}"}

    field_a_result = _resolve_and_fetch_field(field_a, date_from, date_to)
    if "error" in field_a_result:
        return {"error": f"field_a: {field_a_result['error']}",
                **({"did_you_mean": field_a_result["did_you_mean"]}
                   if "did_you_mean" in field_a_result else {})}

    field_b_result = _resolve_and_fetch_field(field_b, date_from, date_to)
    if "error" in field_b_result:
        return {"error": f"field_b: {field_b_result['error']}",
                **({"did_you_mean": field_b_result["did_you_mean"]}
                   if "did_you_mean" in field_b_result else {})}

    values_a = field_a_result["values"]
    values_b = field_b_result["values"]
    shift = datetime.timedelta(days=lag_days)

    paired_a: list[float] = []
    paired_b: list[float] = []
    for date_str in sorted(values_a):
        shifted_date = (datetime.date.fromisoformat(date_str) + shift).isoformat()
        if shifted_date in values_b:
            paired_a.append(values_a[date_str])
            paired_b.append(values_b[shifted_date])

    result = {
        "field_a": field_a_result["field"],
        "field_b": field_b_result["field"],
        "lag_days": lag_days,
        "data_points": len(paired_a),
        "pearson": None,
        "spearman": None,
    }
    for source, target in ((field_a_result, "field_a"), (field_b_result, "field_b")):
        if source["field_resolved_from"] is not None:
            result.setdefault("_meta", {})[f"{target}_resolved_from"] = source["field_resolved_from"]
            result["_meta"][f"{target}_used"] = source["field_used"]

    if len(paired_a) < 2:
        result["note"] = "fewer than 2 overlapping data points -- correlation not computable"
        return result

    try:
        result["pearson"] = round(statistics.correlation(paired_a, paired_b), 4)
    except statistics.StatisticsError:
        result["note"] = "pearson not computable (zero variance in at least one field)"
    try:
        result["spearman"] = round(statistics.correlation(_rank(paired_a), _rank(paired_b)), 4)
    except statistics.StatisticsError:
        existing_note = result.get("note", "")
        result["note"] = (existing_note + "; " if existing_note else "") + \
            "spearman not computable (zero variance in at least one field)"

    return result
