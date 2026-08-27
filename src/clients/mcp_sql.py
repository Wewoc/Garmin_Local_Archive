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
        payload_json TEXT NOT NULL
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


def context_day_exists(day: str) -> bool:
    """True if this day already has a context row — the entire delta
    signal for context (no downgrade concept, no compare_value column,
    see module docstring)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM mcp_context_days WHERE date = ?", (day,)
    ).fetchone()
    return row is not None


def upsert_context_day(day: str, payload: dict) -> None:
    """Inserts or replaces a single day's context payload. Called only
    for days where context_day_exists() was False — an existing row
    never needs overwriting (context has no downgrade path, Timo
    confirmed, NOTES_v1.7.1_session2.md)."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO mcp_context_days (date, payload_json)
        VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET payload_json = excluded.payload_json
        """,
        (day, json.dumps(payload)),
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


# ══════════════════════════════════════════════════════════════════════════════
#  Form C — mcp_recent_logs (daily_logs / fail_logs / recent_logs)
# ══════════════════════════════════════════════════════════════════════════════

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
