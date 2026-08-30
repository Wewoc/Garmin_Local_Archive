#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
clients/mcp_sql.py
Garmin Local Archive — SQLite Proxy, data-access layer (v1.7.1)

Pure SQLite access — schema definition, connection, and typed read/write
functions for the MCP aggregation cache. Owns no sync/delta logic (that
lives in clients/mcp_update.py) and no MCP-SDK dependency. Single
Responsibility split, mirrored on clients/mcp_update.py: this module
answers "read/write the cache", mcp_update.py answers "what needs to be
read/written and when".

Consumer invariant (KONZEPT_mcp_sqlite_proxy_V2.md, unconditionally
binding): SQLite is a pure consumer, never a source. Every row in every
table here is reconstructible from the archive via the broker layer
(maps/mcp_map.py) — a lost or corrupt mcp_cache.db is not data loss, it
forces a full rebuild on the next sync, nothing more. garmin_backup.py /
garmin_mirror.py do not know this file exists and must not be made to.

Database location: BASE_DIR/sqlite/mcp_cache.db — a new top-level
sibling to garmin_data/ and context_data/, not nested inside either
(KONZEPT_mcp_sqlite_proxy_V2.md, "Speicherort der SQLite-Datei").

Error handling: every function in this module raises on failure — it
does not degrade internally, unlike the {"data":..., "error":...}
envelope used throughout maps/. The caller (clients/mcp_update.py) is
responsible for catching per-unit failures and logging them, so that
one bad row/file does not abort an entire sync pass (NOTES_v1.7.1_
session2.md, "Fehlerbehandlung" — mcp_sql.py throws, mcp_update.py
catches per unit). Keeping this module free of try/except keeps its
own logic easy to verify in isolation and avoids silently swallowing a
schema/connection problem that the caller actually needs to see.

Connection model: a single, module-level, long-lived connection —
correct for this process model, since only clients/mcp_server.py (one
process) ever opens this database (NOTES_v1.7.1_session2.md,
Connection-Handling: "aktuell kann ja nur der mcp server auf die
datenbank zugreifen"). WAL (write-ahead logging) journal mode is
enabled at connect time so that a concurrent read (an in-flight MCP
tool call) and a concurrent write (a refresh_cache() sync running in
another thread inside the same process) do not block each other or
raise "database is locked" under normal operation — this is the
technical implementation of the "offene Verbindung, aber
Thread-sicher" decision from the same NOTES section, not a new
architectural decision. check_same_thread=False is required for the
same reason: FastMCP may service tool calls on a different thread than
the one that opened this connection.

Schema — three data shapes, matching maps/metadata_map.py's/
maps/gateway_map.py's own Form A/B/C classification
(NOTES_v1.7.1_session2.md):

  Form A (daily time series):
    mcp_health_days    — one row per day, health payload + last_attempt
                         compare value (delta via quality_log.json's
                         last_attempt, see module docstring below)
    mcp_context_days   — one row per day, context payload, no compare
                         value (delta = row existence, context has no
                         downgrade concept)
    mcp_fit_days       — placeholder, stub pattern mirroring
                         gateway_map._DOMAIN_BROKERS['fit': None];
                         created but never written until fit_map.py
                         lands (v1.8)
    mcp_day_status     — shared status table (date, quality, context,
                         fit) from KONZEPT_mcp_sqlite_proxy_V2.md's
                         "Gemeinsame Statustabelle" — itself the
                         rework-candidate query surface, not just a
                         byproduct

  Form B (point-in-time snapshots, no delta concept):
    mcp_snapshots      — one row per kind (stats/device_table/
                         token_log/capability_config), always fully
                         re-fetched on every sync

  Form C (structured logs / log files):
    mcp_structured_logs — one row per (kind, date_key) for quality_log/
                         source_api_log, compare_value formspecific:
                         last_attempt for quality_log, max(fetched_at,
                         backfilled_fields values) for source_api_log
                         (NOTES_v1.7.1_session2.md — corrected from an
                         earlier, wrong fetched_at-only assumption)
    mcp_recent_logs    — one row per (kind, source_filename) for
                         daily_logs/fail_logs/recent_logs. Primary key
                         is the filename, not (kind, date_key) — a
                         calendar day can have more than one sync log
                         (Timo correction, NOTES_v1.7.1_session2.md).
                         No delta trigger via mcp_health_days — a log's
                         filename-date is the sync timestamp, not
                         necessarily the archived day it reports on
                         (a recheck on 2026-08-27 for an archived day
                         from 2026-07-15 produces a log file dated
                         2026-08-27) — handled like Form B instead,
                         full filename diff on every sync via
                         maps/mcp_map.py's list_*_log_filenames().

All timestamps stored as the ISO strings the archive itself already
uses (quality_log.json's last_attempt, source_api_log.json's
fetched_at) — no reformatting, so a stored compare_value can be
string-compared directly against a freshly-read one without a parse
step on either side.
"""

import json
import sqlite3

from garmin import garmin_config as cfg

DB_PATH = cfg.BASE_DIR / "sqlite" / "mcp_cache.db"

_connection: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    """
    Opens (creating the parent directory and file if needed) and
    returns the module-level connection, creating it on first use.
    WAL journal mode + check_same_thread=False — see module docstring,
    "Connection model". Callers should use get_connection() rather than
    calling this directly, so the module-level singleton is respected.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection:
    """Returns the shared module-level connection, opening it on first
    call. Safe to call repeatedly — subsequent calls return the same
    connection object."""
    global _connection
    if _connection is None:
        _connection = _connect()
    return _connection


# ══════════════════════════════════════════════════════════════════════════════
#  Schema — CREATE TABLE IF NOT EXISTS for all seven tables
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS mcp_health_days (
        date TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        last_attempt_synced TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_context_days (
        date TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        complete_sources_json TEXT NOT NULL DEFAULT '[]',
        attempted_sources_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_fit_days (
        date TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_day_status (
        date TEXT PRIMARY KEY,
        quality TEXT,
        context TEXT,
        fit TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_snapshots (
        kind TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        synced_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_structured_logs (
        kind TEXT NOT NULL,
        date_key TEXT NOT NULL,
        entry_json TEXT NOT NULL,
        compare_value TEXT,
        PRIMARY KEY (kind, date_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_recent_logs (
        kind TEXT NOT NULL,
        source_filename TEXT NOT NULL,
        date_key TEXT,
        lines_json TEXT NOT NULL,
        PRIMARY KEY (kind, source_filename)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_raw_fields (
        date TEXT NOT NULL,
        field TEXT NOT NULL,
        payload_json TEXT,
        recheck INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_attempt TEXT,
        PRIMARY KEY (date, field)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_raw_day_hashes (
        date TEXT PRIMARY KEY,
        hash TEXT NOT NULL
    )
    """,
]


def init_db() -> None:
    """
    Creates all seven tables if they do not already exist. Idempotent —
    safe to call on every mcp_server.py boot, not just the first ever
    run. Does not populate any table; that is sync_all()'s job
    (clients/mcp_update.py).
    """
    conn = get_connection()
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Form A — mcp_health_days / mcp_context_days / mcp_fit_days / mcp_day_status
# ══════════════════════════════════════════════════════════════════════════════

def get_health_compare_value(day: str) -> str | None:
    """Returns the last_attempt value stored for this day at the last
    sync, or None if the day is not yet in the cache at all (which is
    itself a valid, distinct case from "cached with a null compare
    value" — a day whose archive last_attempt is null, see
    NOTES_v1.7.1_session2.md's quality_log delta section)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT last_attempt_synced FROM mcp_health_days WHERE date = ?", (day,)
    ).fetchone()
    return row["last_attempt_synced"] if row is not None else None


def upsert_health_day(day: str, payload: dict, compare_value: str | None) -> None:
    """Inserts or replaces a single day's health payload + compare
    value. One call per changed day — clients/mcp_update.py is
    responsible for calling this only for days whose last_attempt
    actually differs from get_health_compare_value()'s current
    answer."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_health_days (date, payload_json, last_attempt_synced)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            payload_json = excluded.payload_json,
            last_attempt_synced = excluded.last_attempt_synced
        """,
        (day, json.dumps(payload), compare_value),
    )
    conn.commit()


def get_context_day_state(day: str) -> dict | None:
    """
    Returns {"payload": dict, "complete_sources": set[str],
    "attempted_sources": set[str]} for one day, or None if the day has
    no row at all yet. Replaces the old binary context_day_exists()
    (v1.7.1.1 follow-up fix — "Context-Vollständigkeitslücke", see
    NOTES_v1.7.1.1_session2.md): a row's mere existence used to mean
    "done, never touch again", even when only some of the four context
    sources (weather/pollen/brightsky/airquality) had actually
    delivered data for that day — a source outage on sync day
    permanently froze the gap. This function exposes which sources are
    "complete" (delivered real data — Timo's stricter definition:
    "vollständig = alle vier Quellen haben Daten geliefert") versus
    merely "attempted" (queried at least once, whether or not it
    returned data) — the distinction _sync_context_days() needs to
    decide, per missing source, whether this is the first retry
    (worth trying again) or the second (accept as permanently empty,
    see clients/mcp_update.py::_sync_context_days()'s own docstring
    for the one-retry-then-accept reasoning Timo confirmed).
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT payload_json, complete_sources_json, attempted_sources_json
        FROM mcp_context_days WHERE date = ?
        """,
        (day,),
    ).fetchone()
    if row is None:
        return None
    return {
        "payload": json.loads(row["payload_json"]),
        "complete_sources": set(json.loads(row["complete_sources_json"])),
        "attempted_sources": set(json.loads(row["attempted_sources_json"])),
    }


def upsert_context_day(day: str, payload: dict, complete_sources: set[str],
                        attempted_sources: set[str]) -> None:
    """
    Inserts or replaces a single day's context payload plus its
    completeness bookkeeping (v1.7.1.1 follow-up fix, see
    get_context_day_state()'s docstring for the rationale).
    payload is merged by the caller (clients/mcp_update.py) before
    this call — this function always overwrites the full row, it does
    not itself merge old and new payload/source-set state; a caller
    resyncing only the still-missing sources for a partially-complete
    day is responsible for combining them with the day's existing
    get_context_day_state() result first.

    Args:
        day:               ISO date string.
        payload:            Full context payload for this day, one
                            {source: {field: result}} nesting, same
                            shape as before this fix.
        complete_sources:   Set of source names that delivered real
                            data as of this call.
        attempted_sources:  Set of source names queried at least once
                            as of this call — always a superset of
                            complete_sources.
    """
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_context_days
            (date, payload_json, complete_sources_json, attempted_sources_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            payload_json = excluded.payload_json,
            complete_sources_json = excluded.complete_sources_json,
            attempted_sources_json = excluded.attempted_sources_json
        """,
        (day, json.dumps(payload), json.dumps(sorted(complete_sources)),
         json.dumps(sorted(attempted_sources))),
    )
    conn.commit()


def upsert_day_status(day: str, quality: str | None, context: str | None,
                       fit: str | None) -> None:
    """Inserts or replaces one day's row in the shared status table
    (KONZEPT_mcp_sqlite_proxy_V2.md's "Gemeinsame Statustabelle").
    Any of quality/context/fit may be None — a caller updating only
    one column still needs to pass all three; use get_day_status() to
    read the current row first if a partial update is needed."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_day_status (date, quality, context, fit)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            quality = excluded.quality,
            context = excluded.context,
            fit = excluded.fit
        """,
        (day, quality, context, fit),
    )
    conn.commit()


def get_day_status(day: str) -> dict | None:
    """Returns {"quality":..., "context":..., "fit":...} for one day,
    or None if the day has no status row yet. Intended for
    clients/mcp_update.py to read-modify-write a single column without
    clobbering the other two."""
    conn = get_connection()
    row = conn.execute(
        "SELECT quality, context, fit FROM mcp_day_status WHERE date = ?", (day,)
    ).fetchone()
    if row is None:
        return None
    return {"quality": row["quality"], "context": row["context"], "fit": row["fit"]}


# Shared by get_health_range()/get_context_range() (v1.7.1.1, Ziel 1/2) —
# same weekday-table construction as maps/mcp_map.py's private
# _build_meta(), deliberately reimplemented here rather than imported
# (clients/ must not reach into maps/'s internals — see
# get_raw_range()'s docstring for the identical reasoning, applied
# there first). Factored out once here rather than duplicated a second
# time inside each of the two functions below, since both need the
# byte-identical construction and neither is domain-specific.
def _build_range_meta(date_from: str, date_to: str) -> dict:
    import datetime as _dt

    _weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                       "Friday", "Saturday", "Sunday"]
    start = _dt.date.fromisoformat(date_from)
    stop = _dt.date.fromisoformat(date_to)
    weekdays = {}
    cur = start
    while cur <= stop:
        weekdays[cur.isoformat()] = _weekday_names[cur.weekday()]
        cur += _dt.timedelta(days=1)
    return {
        "date_from_iso": start.isoformat(),
        "date_from_readable": start.strftime("%B %d, %Y"),
        "date_to_iso": stop.isoformat(),
        "date_to_readable": stop.strftime("%B %d, %Y"),
        "weekdays": weekdays,
    }


def get_health_range(date_from: str, date_to: str, field: str | None = None) -> dict:
    """
    Reads mcp_health_days for every day in [date_from, date_to] and
    reassembles a query_health()-compatible result:
    {"health": {field: {"values": [...], "fallback": bool,
    "source_resolution": str}, ...}, "_meta": {...}}.

    Each cached day's payload_json already holds one entry per health
    field (see clients/mcp_update.py::_sync_health_days()'s
    "payload[field] = field_result['health']" construction) — this
    function's job is purely the inverse regrouping: from "one row per
    day, all fields inside" (the cache's storage/delta unit) to "one
    values-list per field, one entry per day" (query_health()'s actual
    read shape), same day-to-field transposition get_raw_range()
    already performs for the raw-passthrough cache, generalized here
    to fields whose per-day value carries "values"/"fallback"/
    "source_resolution" (a health_map.get() result) rather than raw's
    flatter {"raw": ...} shape.

    v1.7.1.1 Bug-C correction (2026-08-28): each field's cached value
    carries one more nesting level than the paragraph above states —
    a source-name key (currently always "garmin") sits between the
    field and its "values"/"fallback"/"source_resolution" — mirrored
    from health_map.get()'s own return shape. This function now reads
    through that layer (taking whichever single source is present,
    not hard-coding "garmin"), rather than reading "values" etc.
    directly off field_result as it incorrectly did before this fix —
    that earlier version silently returned an empty values list for
    every field on every day, regardless of what the cache actually
    held.

    A day with no cache row at all (never synced, or synced but with
    an empty archive so nothing was ever written — see
    _sync_health_days()'s early-return for an empty archive)
    contributes no data for that day to any field's "values" list —
    same "day genuinely not written yet, not an error" principle
    get_raw_range() already documents. This is a deliberate difference
    from health_map.get()'s own live contract, where every requested
    day gets an entry (missing data represented as "value": None) —
    the SQLite cache's delta unit is "day present in mcp_health_days
    at all", coarser than a per-field per-day guarantee, so a caller
    needing the live day-completeness guarantee should go through
    mcp_map.query_health() directly rather than this cache read.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        field:     v1.7.1.1 addition (2026-08-28 session, "field-filter"
                   fix) — when given, only this one field is assembled
                   and returned, instead of every field in the cached
                   day payload. Without this, a single-field request
                   (e.g. "resting_heart_rate") silently pulled back
                   every other health field too, including this
                   archive's six *_series intraday fields — full
                   day-long minute-by-minute timeseries the caller
                   never asked for, ballooning a single-value answer
                   to hundreds of KB and confusing small local LLMs
                   trying to summarize it (observed: a fabricated
                   value in the model's own summary of an otherwise
                   correct 266KB response). None (the default) keeps
                   the original "all fields" behavior for callers that
                   genuinely want an overview.

                   No separate handling is needed for intraday vs.
                   daily fields here — each field already carries its
                   own source_resolution from the cache, so a caller
                   asking for "resting_heart_rate" gets a single daily
                   value and a caller asking for "heart_rate_series"
                   gets the full timeseries, purely based on which
                   field name was requested — no resolution-based
                   branching required.

    Returns:
        {"health": {field: <health_map.get() per-source result>, ...},
         "_meta": {...}} — "_meta" always present, matching
        query_health()'s own contract. When field is given, "health"
        contains at most that one key (absent entirely if the field
        was never cached for any day in range, same as the no-field
        case would omit any field with zero matching values).
    """
    by_field: dict[str, dict] = {}
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, payload_json FROM mcp_health_days WHERE date BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchall()
    for row in rows:
        day_str = row["date"]
        day_payload = json.loads(row["payload_json"])
        for field_name, field_result in day_payload.items():
            if field is not None and field_name != field:
                continue
            # v1.7.1.1 Bug-C fix (2026-08-28 diagnosis session): field_result
            # carries an extra source-name layer (e.g. {"garmin": {"values":
            # ..., "fallback": ..., "source_resolution": ...}}) — this comes
            # straight from health_map.get()'s own result shape, mirrored
            # unchanged into the cache by _sync_health_days()'s
            # "payload[field] = field_result['health']" write. Reading
            # field_result directly (as before this fix) always missed
            # "values"/"fallback"/"source_resolution", since those live one
            # level deeper, under whichever source key is present — every
            # field for every day silently produced an empty values list,
            # regardless of whether the cache row itself held real data.
            # Option A (chosen over hard-coding "garmin"): take whichever
            # single source is present, so this keeps working unchanged if a
            # second source is ever added upstream, without needing another
            # correction here.
            source_result = field_result
            if isinstance(field_result, dict) and field_result:
                first_source_value = next(iter(field_result.values()))
                if isinstance(first_source_value, dict):
                    source_result = first_source_value

            entry = by_field.setdefault(field_name, {
                "values": [],
                "fallback": source_result.get("fallback", False)
                            if isinstance(source_result, dict) else False,
                "source_resolution": source_result.get("source_resolution", "daily")
                                     if isinstance(source_result, dict) else "daily",
            })
            if isinstance(source_result, dict) and "values" in source_result:
                entry["values"].extend(
                    v for v in source_result["values"] if v.get("date") == day_str
                )

    return {
        "health": by_field,
        "_meta": _build_range_meta(date_from, date_to),
    }


def get_context_range(date_from: str, date_to: str,
                       field: str | None = None) -> dict:
    """
    Reads mcp_context_days for every day in [date_from, date_to] and
    reassembles a query_context()-compatible result:
    {"context": {source: {field: {"values": [...], "fallback": bool,
    "source_resolution": str}, ...}, ...}, "_meta": {...}}.

    Each cached day's payload_json holds a nested {source: {field:
    result}} structure (see clients/mcp_update.py::_sync_context_days()'s
    "payload.setdefault(source, {})[field] = source_result"
    construction) — one extra nesting level deeper than
    get_health_range() (context fans out across four sources: weather/
    pollen/brightsky/airquality), otherwise the identical day-to-field
    transposition principle.

    A day with no cache row at all contributes no data for that day —
    same "day genuinely not written yet" principle as get_health_range()/
    get_raw_range() (context additionally has no downgrade concept at
    all, module docstring — once a day's row exists it is considered
    permanently complete, so a missing row here always means "not yet
    synced", never "synced but incomplete").

    v1.7.1.3 field-filter fix: field is now an optional parameter,
    mirroring get_health_range()'s v1.7.1.2 fix — previously
    mcp_server.py's query_context() call site never forwarded its own
    field argument here at all (a distinct bug from get_health_range()'s
    v1.7.1.1 gap, since this function's signature never even accepted
    the argument in the first place), so every call returned all four
    context categories/every field regardless of what was asked for.
    Filtering happens at FIELD level, not source level: a field name
    can legitimately be registered by more than one source at once
    (e.g. "wind_speed_max" under both "weather" and "brightsky", see
    context_map.py's naming-collision note) — the filter keeps every
    source that carries the requested field and drops only the other
    fields, so a multi-source field still returns all of its sources.
    field=None preserves the pre-fix behaviour (every field of every
    source) for any internal caller that may rely on the unfiltered
    shape.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.
        field:     Optional field name to filter to. When given, only
                   entries whose field name matches are kept — across
                   every source that registers that field. None keeps
                   the unfiltered pre-fix behaviour.

    Returns:
        {"context": {source: {field: <context_map.get() per-source
         result>, ...}, ...}, "_meta": {...}} — "_meta" always present,
        matching query_context()'s own contract.
    """
    by_source: dict[str, dict[str, dict]] = {}
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, payload_json FROM mcp_context_days WHERE date BETWEEN ? AND ?",
        (date_from, date_to),
    ).fetchall()
    for row in rows:
        day_str = row["date"]
        day_payload = json.loads(row["payload_json"])
        for source, field_map in day_payload.items():
            for field_name, field_result in field_map.items():
                if field is not None and field_name != field:
                    continue
                source_entry = by_source.setdefault(source, {})
                entry = source_entry.setdefault(field_name, {
                    "values": [],
                    "fallback": field_result.get("fallback", False)
                                if isinstance(field_result, dict) else False,
                    "source_resolution": field_result.get("source_resolution", "daily")
                                         if isinstance(field_result, dict) else "daily",
                })
                if isinstance(field_result, dict) and "values" in field_result:
                    entry["values"].extend(
                        v for v in field_result["values"] if v.get("date") == day_str
                    )

    return {
        "context": by_source,
        "_meta": _build_range_meta(date_from, date_to),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Form B — mcp_snapshots
# ══════════════════════════════════════════════════════════════════════════════

def upsert_snapshot(kind: str, payload: dict, synced_at: str) -> None:
    """Inserts or replaces the single row for one Form-B kind (stats/
    device_table/token_log/capability_config). Always called
    unconditionally on every sync — Form B has no delta concept, see
    module docstring."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_snapshots (kind, payload_json, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(kind) DO UPDATE SET
            payload_json = excluded.payload_json,
            synced_at = excluded.synced_at
        """,
        (kind, json.dumps(payload), synced_at),
    )
    conn.commit()


def get_snapshot(kind: str) -> dict | None:
    """Returns the cached payload for one Form-B kind, or None if never
    synced yet."""
    conn = get_connection()
    row = conn.execute(
        "SELECT payload_json FROM mcp_snapshots WHERE kind = ?", (kind,)
    ).fetchone()
    return json.loads(row["payload_json"]) if row is not None else None


def get_snapshot_metadata(kind: str) -> dict:
    """
    query_get_archive_metadata()-compatible read for one of the four
    Form-B kinds ("stats"/"device_table"/"token_log"/
    "capability_config") — thin wrapper around the already-existing
    get_snapshot(kind), added (v1.7.1.1 Ziel 2b) purely for a uniform
    envelope: get_snapshot() itself returns the bare payload or None,
    while every mcp_map.py-facing read in this module returns
    {"data": ..., "error": None} (matching gateway_map.get_metadata()'s
    own contract), so get_metadata_range() below can treat both
    Form-B and Form-C reads identically without a shape difference the
    caller would otherwise have to paper over.

    Args:
        kind: One of the four Form-B kinds — caller (get_metadata_range())
              is responsible for only calling this for a kind actually
              in _SNAPSHOT_KINDS below; this function does not itself
              validate kind.

    Returns:
        {"data": <cached payload> | None, "error": None} — "error" is
        always None here (this module raises rather than degrading, see
        module docstring; a missing snapshot is not an error, it is a
        "not yet synced" data state, same as every other cache-miss
        case in this module).
    """
    return {"data": get_snapshot(kind), "error": None}


# ══════════════════════════════════════════════════════════════════════════════
#  Form C — mcp_structured_logs (quality_log / source_api_log)
# ══════════════════════════════════════════════════════════════════════════════

def get_structured_log_compare_value(kind: str, date_key: str) -> str | None:
    """Returns the compare_value stored for one (kind, date_key) entry,
    or None if not yet cached. kind is "quality_log" or
    "source_api_log" — see module docstring for what compare_value
    holds for each."""
    conn = get_connection()
    row = conn.execute(
        "SELECT compare_value FROM mcp_structured_logs WHERE kind = ? AND date_key = ?",
        (kind, date_key),
    ).fetchone()
    return row["compare_value"] if row is not None else None


def upsert_structured_log_entry(kind: str, date_key: str, entry: dict,
                                 compare_value: str) -> None:
    """Inserts or replaces one day's structured-log entry. One call per
    changed date_key — clients/mcp_update.py is responsible for calling
    this only when the freshly-read compare_value differs from
    get_structured_log_compare_value()'s current answer."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_structured_logs (kind, date_key, entry_json, compare_value)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(kind, date_key) DO UPDATE SET
            entry_json = excluded.entry_json,
            compare_value = excluded.compare_value
        """,
        (kind, date_key, json.dumps(entry), compare_value),
    )
    conn.commit()


def get_structured_log_range(kind: str, date_from: str, date_to: str) -> list[dict]:
    """
    Reads mcp_structured_logs for one kind ("quality_log"/
    "source_api_log") over a date_key range — the shared read half of
    the write path get_structured_log_compare_value()/
    upsert_structured_log_entry() already implement, added here (v1.7.1.1
    Ziel 2b) because until now this table had a delta-compare read but
    no range read at all.

    Args:
        kind:      "quality_log" or "source_api_log".
        date_from: Start date_key ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date_key ISO string (YYYY-MM-DD), inclusive.

    Returns:
        list[dict] — each cached entry_json, already json.loads()'d,
        in date_key order. Empty list if nothing cached in range yet
        (not an error — same "not yet synced" principle as every other
        read in this module).
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT entry_json FROM mcp_structured_logs
        WHERE kind = ? AND date_key BETWEEN ? AND ?
        ORDER BY date_key
        """,
        (kind, date_from, date_to),
    ).fetchall()
    return [json.loads(row["entry_json"]) for row in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  Form C — mcp_recent_logs (daily_logs / fail_logs / recent_logs)
# ══════════════════════════════════════════════════════════════════════════════

def get_recent_log_range(kind: str, date_from: str, date_to: str) -> list[dict]:
    """
    Reads mcp_recent_logs for one kind ("daily_logs"/"fail_logs"/
    "recent_logs") over a date_key range — added (v1.7.1.1 Ziel 2b)
    alongside get_structured_log_range() above; this table previously
    had only get_known_recent_log_filenames()/upsert_recent_log_file()
    (sync-diff use, keyed by source_filename, no date-range read).

    date_key can be NULL for a given row (module docstring — a log
    file's filename-encoded date is the sync timestamp, not necessarily
    the archived day it reports on; some call sites may not have a
    parseable date_key at all) — rows with a NULL date_key are excluded
    from a range query by SQL's own BETWEEN semantics (NULL compares
    false against any bound), which is the correct behaviour here: a
    row with no known date cannot be placed inside any specific range,
    so it is simply absent from every ranged read rather than
    ambiguously included in all of them.

    Args:
        kind:      "daily_logs", "fail_logs", or "recent_logs".
        date_from: Start date_key ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date_key ISO string (YYYY-MM-DD), inclusive.

    Returns:
        list[dict] — one {"source_filename": str, "lines": list[str]}
        per matching row, ordered by source_filename. Empty list if
        nothing cached in range yet.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT source_filename, lines_json FROM mcp_recent_logs
        WHERE kind = ? AND date_key BETWEEN ? AND ?
        ORDER BY source_filename
        """,
        (kind, date_from, date_to),
    ).fetchall()
    return [
        {"source_filename": row["source_filename"], "lines": json.loads(row["lines_json"])}
        for row in rows
    ]


# Kind-to-cache-form routing table (v1.7.1.1 Ziel 2b) — single source
# of truth for which of the two metadata read functions a given kind
# goes through, mirroring gateway_map.py's own _DATE_FILTERABLE_KINDS
# split (same nine kinds, same grouping) rather than re-deriving it
# independently — Timo, on the drift risk of two independent copies of
# the same classification: "man müsste vorher nur sauber unterscheiden
# welche der beiden man für die anfrage nutzen will", resolved by
# keeping exactly one such table here instead of letting
# get_metadata_range() infer it inline.
_SNAPSHOT_KINDS = {"stats", "device_table", "token_log", "capability_config"}
_STRUCTURED_LOG_KINDS = {"quality_log", "source_api_log"}
_RECENT_LOG_KINDS = {"daily_logs", "fail_logs", "recent_logs"}


def get_metadata_range(kind: str, date_from: str | None = None,
                        date_to: str | None = None) -> dict:
    """
    Single entry point for a query_get_archive_metadata()-compatible
    SQLite read, regardless of which of the two cache forms the
    requested kind actually lives in (v1.7.1.1 Ziel 2b) — a routing
    function one level below clients/mcp_server.py's own upcoming
    _route_query() (Ziel 5), same "weiche" principle applied to the
    cache-form choice instead of the SQLite-vs-live choice, so that
    caller (Ziel 5) needs exactly one call site for all nine kinds
    instead of knowing the Form B/Form C split itself.

    Args:
        kind:      One of the nine get_archive_metadata() kinds.
        date_from: Required for the five date-filterable kinds
                   (quality_log/source_api_log/daily_logs/fail_logs/
                   recent_logs) — ignored for the four Form-B kinds,
                   same silent-ignore convention gateway_map.get_metadata()
                   already uses for its own live equivalent. None is
                   accepted here but yields an empty result for a
                   date-filterable kind (no 30-day-default fallback in
                   this cache read — that convenience lives on the live
                   path via mcp_map.get_archive_metadata() only).
        date_to:   Same rule as date_from.

    Returns:
        {"data": ..., "error": None} for a Form-B kind (get_snapshot_metadata()'s
        own envelope, unchanged) or {"data": list[dict], "error": None}
        for a Form-C kind (get_structured_log_range()/
        get_recent_log_range()'s list wrapped in the same envelope for
        a uniform contract across all nine kinds).

    Raises:
        ValueError: if kind is not one of the nine known kinds — same
                    caller-error principle as gateway_map.get_metadata().
    """
    if kind in _SNAPSHOT_KINDS:
        return get_snapshot_metadata(kind)
    if kind in _STRUCTURED_LOG_KINDS:
        if date_from is None or date_to is None:
            return {"data": [], "error": None}
        return {"data": get_structured_log_range(kind, date_from, date_to), "error": None}
    if kind in _RECENT_LOG_KINDS:
        if date_from is None or date_to is None:
            return {"data": [], "error": None}
        return {"data": get_recent_log_range(kind, date_from, date_to), "error": None}
    raise ValueError(
        f"Unknown metadata kind {kind!r} — expected one of "
        f"{sorted(_SNAPSHOT_KINDS | _STRUCTURED_LOG_KINDS | _RECENT_LOG_KINDS)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Raw-passthrough — mcp_raw_fields / mcp_raw_day_hashes (v1.7.1.1)
# ══════════════════════════════════════════════════════════════════════════════

def get_raw_day_hash(day: str) -> str | None:
    """Returns the cached content hash for this day's raw/ file, or
    None if no hash is cached yet for this day (distinct from a day
    whose raw/ file does not exist — that case never reaches this
    table at all, since clients/mcp_update.py only upserts a hash for
    a day it has actually seen a value for from
    metadata_map.get_raw_file_hashes())."""
    conn = get_connection()
    row = conn.execute(
        "SELECT hash FROM mcp_raw_day_hashes WHERE date = ?", (day,)
    ).fetchone()
    return row["hash"] if row is not None else None


def upsert_raw_day_hash(day: str, hash_value: str) -> None:
    """Inserts or replaces the cached content hash for one day's raw/
    file. One call per day whose hash changed since the last sync —
    clients/mcp_update.py is responsible for calling this only when
    the freshly-read hash differs from get_raw_day_hash()'s current
    answer, same delta principle as upsert_health_day()."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_raw_day_hashes (date, hash)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET hash = excluded.hash
        """,
        (day, hash_value),
    )
    conn.commit()


def get_pending_raw_fields(day: str) -> set[str]:
    """Returns every field name for this day currently marked
    recheck=1 in mcp_raw_fields — the exact set clients/mcp_update.py
    must re-query on a sync pass where this day's content hash has
    NOT changed (day otherwise considered stable). Empty set if the
    day has no pending fields (either fully resolved, or not yet
    synced at all — the caller distinguishes those via
    get_raw_day_hash())."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT field FROM mcp_raw_fields WHERE date = ? AND recheck = 1", (day,)
    ).fetchall()
    return {row["field"] for row in rows}


def get_raw_field_attempts(day: str, field: str) -> int:
    """Returns the current attempts count for one (day, field) entry,
    or 0 if not yet cached — clients/mcp_update.py reads this before
    a re-query so a failed attempt increments from the true prior
    count rather than resetting to 0/1 on every retry."""
    conn = get_connection()
    row = conn.execute(
        "SELECT attempts FROM mcp_raw_fields WHERE date = ? AND field = ?", (day, field)
    ).fetchone()
    return row["attempts"] if row is not None else 0


def upsert_raw_field(day: str, field: str, payload: dict | None,
                      recheck: bool, attempts: int,
                      last_attempt: str | None) -> None:
    """Inserts or replaces a single (day, field) raw-passthrough
    entry. payload is None when the field genuinely has no value for
    this day (not an error — see garmin_health_map.get_raw()'s own
    "raw is None" convention). recheck/attempts/last_attempt follow
    the same naming convention as garmin_quality.py's quality_log
    entries (Timo's explicit reference point, NOTES_v1.7.1.1_session2.md)
    — deliberately reimplemented here rather than imported, since
    clients/ must not gain a dependency on garmin/quality/ (bindable
    architecture decision, same session)."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_raw_fields (date, field, payload_json, recheck, attempts, last_attempt)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, field) DO UPDATE SET
            payload_json = excluded.payload_json,
            recheck = excluded.recheck,
            attempts = excluded.attempts,
            last_attempt = excluded.last_attempt
        """,
        (day, field, json.dumps(payload) if payload is not None else None,
         1 if recheck else 0, attempts, last_attempt),
    )
    conn.commit()


def get_raw_fields_for_day(day: str) -> dict[str, dict | None]:
    """Returns {field: payload, ...} for every field cached for this
    day, payload already json.loads()'d — None entries preserved as
    None (field genuinely has no value), not silently dropped. Used by
    get_raw_range() to assemble query_raw()-compatible output."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT field, payload_json FROM mcp_raw_fields WHERE date = ?", (day,)
    ).fetchall()
    return {
        row["field"]: json.loads(row["payload_json"]) if row["payload_json"] is not None else None
        for row in rows
    }


def get_raw_range(date_from: str, date_to: str) -> dict:
    """
    Reads mcp_raw_fields + mcp_raw_day_hashes for every day in
    [date_from, date_to] and reassembles a query_raw()-compatible
    result: {"health": {field: {"values": [...], "source_resolution":
    "raw"}, ...}, "_meta": {...}}. One "values" entry per calendar day
    per field, matching garmin_health_map.get_raw()'s own
    {"values": [{"date": str, "raw": ...}], "source_resolution": "raw"}
    shape per field — reconstructed here from the feld-granular cache
    rows rather than stored pre-assembled, since the cache's delta unit
    (day, field) does not match the read shape's grouping (field, then
    all its days) 1:1.

    Days never synced at all (get_raw_day_hash() returns None) contribute
    no field data for that day, same "day genuinely not written yet"
    principle _sync_context_days() already uses — not an error, not a
    forced early return, callers see a "values" list that simply has no
    entry for that date (mirrors query_raw()'s own degrade-gracefully
    contract, since gateway_map/health_map never raise for a missing
    day either).

    Only the "health" domain is populated (mcp_raw_fields has no domain
    column — the only domain with raw-passthrough support currently,
    see module docstring's Form A section) — "_meta" is always present,
    matching query_raw()'s own contract. Uses the shared
    _build_range_meta() helper (defined above get_health_range(),
    v1.7.1.1 Ziel 1/2) rather than its own local copy — unified here
    (v1.7.1.1 Ziel 1/2 follow-up, Timo: "wenn man das sicher
    vereinheitlichen kann sollte man das machen sonst driftet das
    später auseinander") after get_health_range()/get_context_range()
    introduced a byte-identical construction; both call sites need the
    same weekday-table shape and neither is domain-specific, so a
    single copy at module level replaces what was briefly two nearly-
    identical local functions — the exact drift risk KNOWN_ISSUES.md's
    Cluster F already names for other "verstreute lokale Konstanten-
    Kopien" cases in this project. Still not imported from
    maps/mcp_map.py's private _build_meta() — clients/ must not reach
    into maps/'s internals (same architecture boundary that already
    keeps this module's recheck/attempts convention independent of
    garmin/quality/'s, see upsert_raw_field()'s docstring).
    """
    import datetime as _dt

    fields_by_date: dict[str, dict[str, dict | None]] = {}
    current = _dt.date.fromisoformat(date_from)
    end = _dt.date.fromisoformat(date_to)
    while current <= end:
        day_str = current.isoformat()
        day_fields = get_raw_fields_for_day(day_str)
        if day_fields:
            fields_by_date[day_str] = day_fields
        current += _dt.timedelta(days=1)

    by_field: dict[str, dict] = {}
    for day_str, day_fields in fields_by_date.items():
        for field, payload in day_fields.items():
            by_field.setdefault(field, {"values": [], "source_resolution": "raw"})
            raw_value = payload["raw"] if isinstance(payload, dict) and "raw" in payload else payload
            by_field[field]["values"].append({"date": day_str, "raw": raw_value})

    return {
        "health": by_field,
        "_meta": _build_range_meta(date_from, date_to),
    }


def get_known_recent_log_filenames(kind: str) -> set[str]:
    """Returns every source_filename already cached for this kind
    ("daily_logs"/"fail_logs"/"recent_logs") — the diff base
    clients/mcp_update.py needs against
    maps/mcp_map.py's list_*_log_filenames() output to find genuinely
    new files."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT source_filename FROM mcp_recent_logs WHERE kind = ?", (kind,)
    ).fetchall()
    return {row["source_filename"] for row in rows}


def upsert_recent_log_file(kind: str, source_filename: str, date_key: str | None,
                            lines: list[str]) -> None:
    """Inserts one new log file's sanitized lines. Never called for a
    filename already present (get_known_recent_log_filenames() already
    excludes it) — log files are write-once per the archive's own
    session-per-file model (NOTES_v1.7.1_session2.md), so this is
    always a fresh INSERT in practice; ON CONFLICT is included only as
    a defensive no-op, not an expected path."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_recent_logs (kind, source_filename, date_key, lines_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(kind, source_filename) DO UPDATE SET
            date_key = excluded.date_key,
            lines_json = excluded.lines_json
        """,
        (kind, source_filename, date_key, json.dumps(lines)),
    )
    conn.commit()
