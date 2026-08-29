#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
mcp_map.py

Protocol-mediator broker for MCP (Model Context Protocol) consumers.
Structural sibling of the existing broker consumers (dashboard
specialists etc.) — an LLM via mcp_server.py is on the receiving end
instead of a Qt widget, otherwise no special role. Thin delegation to
gateway_map.get()/get_raw()/get_metadata() throughout — this module
owns no data, no state, no SDK dependency, and is fully testable
without a running MCP server (see test_mcp_map.py).

Tool granularity: few, broad, domain-named functions rather than 1:1
technical wrappers around gateway_map parameters (NOTES_v1.7-
vorbereitung.md, Frage 3 — corrected after reference analysis of
eddmann/garmin-connect-mcp). One function per domain
(query_health/query_context/query_fit_activities) rather than a single
generic query(domain=...) — a domain typo becomes a caller error at
the Python level (wrong function name) instead of a silent runtime
string mismatch.

Error behavior: identical to gateway_map.py — never raises for
data-availability reasons. Degraded {"error": ...} results are passed
through unchanged. gateway_map.get()'s ValueError for a genuinely
unknown domain string cannot occur here, since domain is fixed per
function, not caller-supplied.

Timestamp redundancy (NOTES_v1.7-vorbereitung.md — LLMs are documented
to miscalculate weekdays from a bare ISO date): every function with a
date range attaches a "_meta" block with date_from/date_to (ISO +
human-readable) plus a per-calendar-day weekday table for the
requested range. This is deliberately NOT attached per data point —
at intraday resolution that would repeat the same weekday string
thousands of times. The underlying "values" list from gateway_map is
passed through unmodified.

FIT handling: query_fit_activities() delegates to gateway_map.get(...,
domain="fit") like the other two query functions. Until garmin_fit_map
lands (v1.8), "fit" already returns a clean degraded result via
gateway_map's existing unregistered-domain handling — no FIT-specific
code path needed here (see KONZEPT_mcp_sqlite_proxy_V2.md, "FIT-
Anbindung: Stöpsel statt Vollintegration").

Usage (from mcp_server.py, once the MCP SDK registers these as tools):
    from maps.mcp_map import query_health, query_context, \
        query_fit_activities, query_raw, get_archive_metadata, \
        list_available_fields
"""

from datetime import date, datetime, timedelta

from . import gateway_map

_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_meta(date_from: str, date_to: str) -> dict:
    """
    Builds the timestamp-redundancy block attached to every date-ranged
    query response. Contains ISO + human-readable date_from/date_to, plus
    a per-calendar-day weekday table covering the full requested range —
    one entry per day, not per data point, so the LLM can look up any
    day's weekday without having to compute it itself.
    """
    start = _parse_iso_date(date_from)
    end = _parse_iso_date(date_to)

    weekdays = {}
    current = start
    while current <= end:
        weekdays[current.isoformat()] = _WEEKDAY_NAMES[current.weekday()]
        current += timedelta(days=1)

    return {
        "date_from_iso": start.isoformat(),
        "date_from_readable": start.strftime("%B %d, %Y"),
        "date_to_iso": end.isoformat(),
        "date_to_readable": end.strftime("%B %d, %Y"),
        "weekdays": weekdays,
    }


def query_health(field: str, date_from: str, date_to: str,
                  resolution: str = "daily") -> dict:
    """
    Query the health domain (currently: garmin). Thin delegation to
    gateway_map.get(..., domain="health") — see that function's own
    docstring for the returned per-source shape. Adds "_meta" (see
    _build_meta) alongside the unmodified gateway_map result.
    """
    result = gateway_map.get(field, date_from, date_to, resolution, domain="health")
    return {"health": result["health"], "_meta": _build_meta(date_from, date_to)}


def query_context(field: str, date_from: str, date_to: str,
                   resolution: str = "daily") -> dict:
    """
    Query the context domain (weather/pollen/brightsky/airquality — fan-out
    across all registered sources that know the requested field). Thin
    delegation to gateway_map.get(..., domain="context").
    """
    result = gateway_map.get(field, date_from, date_to, resolution, domain="context")
    return {"context": result["context"], "_meta": _build_meta(date_from, date_to)}


def query_fit_activities(field: str, date_from: str, date_to: str,
                          resolution: str = "daily") -> dict:
    """
    Query the fit domain. Until garmin_fit_map.py lands (v1.8), this
    delegates to gateway_map.get(..., domain="fit"), which returns a
    clean degraded result ({"error": "domain not yet available"}) via
    gateway_map's existing unregistered-domain handling — no FIT-specific
    logic here, deliberately, per the "Stöpsel" principle.
    """
    result = gateway_map.get(field, date_from, date_to, resolution, domain="fit")
    return {"fit": result["fit"], "_meta": _build_meta(date_from, date_to)}


def query_raw(field: str, date_from: str, date_to: str,
              domain: str | None = None) -> dict:
    """
    Query raw-passthrough data. Thin delegation to gateway_map.get_raw().
    domain=None fans out across all registered domains, same as
    gateway_map.get_raw()'s own default. Adds "_meta".

    Raises:
        ValueError: if domain is set to a string that is not a known
                    domain key — passed through unchanged from
                    gateway_map.get_raw().
    """
    result = gateway_map.get_raw(field, date_from, date_to, domain=domain)
    result["_meta"] = _build_meta(date_from, date_to)
    return result


def get_archive_metadata(kind: str, date_from: str | None = None,
                          date_to: str | None = None) -> dict:
    """
    Request an archive-state metadata artefact (coverage stats, device
    table, quality log, raw logs, etc.). Thin delegation to
    gateway_map.get_metadata(kind, date_from, date_to). No "_meta"
    timestamp/weekday block here — that block is built for time-series
    query results (query_health/query_context/query_fit_activities/
    query_raw), which is a different concept from the plain date-range
    filter five of the nine metadata kinds gained in v1.7.0.4 (see
    gateway_map.get_metadata()'s docstring).

    Use "stats" for a quick overview of archive coverage/quality
    (total/high/standard/failed counts, date range, coverage percentage)
    — "quality_log" returns the full per-day register instead, which
    even filtered to a date range is the wrong tool for a "how big is
    my archive" or "how healthy is my data overall" question.

    Args:
        kind:       One of gateway_map.list_metadata_kinds().
        date_from:  Optional ISO "YYYY-MM-DD", inclusive. Only affects
                    "quality_log", "source_api_log", "daily_logs",
                    "fail_logs", "recent_logs" — silently ignored for
                    the other four kinds. Omitting both date_from and
                    date_to on one of the five date-filterable kinds
                    returns the last 30 days plus a "note" field, not
                    the full unfiltered archive.
        date_to:    Optional ISO "YYYY-MM-DD", inclusive. Same rule as
                    date_from.

    Raises:
        ValueError: if kind is not a known metadata kind — passed
                    through unchanged from gateway_map.get_metadata().
    """
    return gateway_map.get_metadata(kind, date_from=date_from, date_to=date_to)


def list_daily_log_filenames(date_from: str | None = None,
                              date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of daily-sync log files —
    internal sync bookkeeping (v1.7.1), NOT registered as an MCP tool
    in clients/mcp_server.py. Thin delegation to
    gateway_map.get_metadata("daily_log_filenames", date_from, date_to).
    Same no-"_meta" reasoning as get_archive_metadata() above — a plain
    date-range filter, not a time-series query.

    Used exclusively by clients/mcp_update.py's SQLite proxy sync to
    learn which log files exist in garmin_data/log/daily/ without
    reading their content, so it can diff its own cache's known
    filenames against the archive's actual ones — see
    metadata_map.py's list_daily_log_filenames() for the full
    rationale (get_daily_logs() alone returns a flat sanitized line
    list with no per-file attribution, insufficient for this purpose).

    Args:
        date_from:  Optional ISO "YYYY-MM-DD", inclusive. Omitting both
                    date_from and date_to returns the last 30 days plus
                    a "note" field, not the full archive history.
        date_to:    Optional ISO "YYYY-MM-DD", inclusive. Same rule as
                    date_from.

    Raises:
        ValueError: passed through unchanged from
                    gateway_map.get_metadata() — not expected in
                    practice since "daily_log_filenames" is always a
                    known kind.
    """
    return gateway_map.get_metadata("daily_log_filenames", date_from=date_from, date_to=date_to)


def list_fail_log_filenames(date_from: str | None = None,
                             date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of fail-log files — internal
    sync bookkeeping (v1.7.1), NOT registered as an MCP tool. Same
    rationale and shape as list_daily_log_filenames() above, only
    dir_path differs (garmin_data/log/fail/). Thin delegation to
    gateway_map.get_metadata("fail_log_filenames", date_from, date_to).
    """
    return gateway_map.get_metadata("fail_log_filenames", date_from=date_from, date_to=date_to)


def list_recent_log_filenames(date_from: str | None = None,
                               date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of recent-log files — internal
    sync use (v1.7.1), NOT registered as an MCP tool. Same rationale
    and shape as list_daily_log_filenames() above, only dir_path
    differs (garmin_data/log/recent/). Thin delegation to
    gateway_map.get_metadata("recent_log_filenames", date_from, date_to).
    """
    return gateway_map.get_metadata("recent_log_filenames", date_from=date_from, date_to=date_to)


def get_raw_file_hashes(date_from: str, date_to: str) -> dict:
    """
    SHA-256 content hash of the raw/ file for each day in the given
    range — internal sync bookkeeping (v1.7.1.1), NOT registered as an
    MCP tool in clients/mcp_server.py. Thin delegation to
    gateway_map.get_metadata("raw_file_hashes", date_from, date_to).

    Used exclusively by clients/mcp_update.py's SQLite proxy sync to
    detect genuine content changes to a day's raw/ file (including
    nachtraegliche Datenlieferung for an already-closed recheck
    window) without re-reading every raw-passthrough field value on
    every sync pass — see metadata_map.py's get_raw_file_hashes() for
    the full rationale, including why mtime is deliberately not used.

    Unlike the other internal sync-only functions above, date_from and
    date_to are both required, not optional — see
    metadata_map.get_raw_file_hashes()'s own docstring for why a
    silent default range is not offered here.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.

    Raises:
        ValueError: passed through unchanged from
                    gateway_map.get_metadata() — not expected in
                    practice since "raw_file_hashes" is always a known
                    kind.
    """
    return gateway_map.get_metadata("raw_file_hashes", date_from=date_from, date_to=date_to)


def list_raw_fields(domain: str | None = None) -> dict:
    """
    List raw-passthrough field names per domain — internal sync use
    (v1.7.1.1), NOT registered as an MCP tool. Thin delegation to
    gateway_map.list_raw_fields(domain). Distinct from
    list_available_fields() above: that function's "fields" key only
    covers health/context/fit's interpreted (get()-reachable) fields,
    never the raw-passthrough registry (see that function's own
    docstring, "fit" always returns an empty list — raw-passthrough is
    a structurally separate registry, not folded into the same
    envelope).

    Used exclusively by clients/mcp_update.py's SQLite proxy sync to
    read the current raw-passthrough field registry fresh on every
    sync pass — deliberately never hard-coded to today's field count,
    since the registry is documented as "open for community feedback"
    and can grow or shrink (see REFERENCE_GARMIN.md, "Raw-passthrough
    fields").

    Args:
        domain: None -> query all registered domain keys. Set to one
                of those -> query only that domain. Only "health"
                currently returns a non-empty list (see
                gateway_map.get_raw()'s own docstring).

    Returns:
        Dict keyed by domain name, each value a list[str] of raw
        field names (empty list for a domain without raw-passthrough
        support) — same shape gateway_map.list_raw_fields() already
        returns, passed through unchanged.
    """
    return gateway_map.list_raw_fields(domain=domain)


def list_available_fields(domain: str | None = None) -> dict:
    """
    Convenience overview for an MCP consumer that does not yet know
    which fields exist — combines list_domains(), list_metadata_kinds(),
    and per-domain list_fields() into a single response, so the LLM does
    not need several separate calls just to discover the field surface.

    Args:
        domain: None -> fields for all registered domains (health via
                garmin_health_map's list_fields, context via each of its
                four sources). Set to "health" or "context" -> only that
                domain's fields. "fit" always returns an empty list
                (broker not yet registered).

    Returns:
        {
            "domains": [...],            # gateway_map.list_domains()
            "metadata_kinds": [...],     # gateway_map.list_metadata_kinds()
            "fields": {
                "health": {"garmin": [...]},
                "context": {"weather": [...], "pollen": [...], ...},
                "fit": [],
            }
        }
    """
    from . import health_map, context_map

    domains = gateway_map.list_domains()
    fields: dict = {}

    if domain is None or domain == "health":
        fields["health"] = {
            source: health_map.list_fields(source=source)
            for source in health_map.list_sources()
        }
    if domain is None or domain == "context":
        fields["context"] = {
            source: context_map.list_fields(source=source)
            for source in context_map.list_sources()
        }
    if domain is None or domain == "fit":
        fields["fit"] = []

    return {
        "domains": domains,
        "metadata_kinds": gateway_map.list_metadata_kinds(),
        "fields": fields,
    }
