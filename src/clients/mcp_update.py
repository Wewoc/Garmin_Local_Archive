#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
clients/mcp_update.py
Garmin Local Archive — SQLite Proxy, delta/sync logic (v1.7.1)

Compares mcp_sql.py's current cache state ("Ist") against maps/mcp_map.py's
live archive state ("Soll") and writes only the difference back through
mcp_sql.py. Owns no SQLite connection/schema logic itself (that is
mcp_sql.py's job) and no MCP-SDK dependency — this module is plain
Python, fully callable in isolation from mcp_server.py, exactly the
Single-Responsibility split KONZEPT_mcp_sqlite_proxy_V2.md specifies.

One mechanism, two callers (NOTES_v1.7.1_vorbereitung.md /
NOTES_v1.7.1_session2.md, binding): sync_all() runs identically whether
called from clients/mcp_server.py's boot sequence (before mcp.run(),
result only logged — LLM is not connected yet) or from the
refresh_cache() MCP tool (LLM-triggered, result returned as the tool's
answer). No second code path, no boot-specific or refresh-specific
branch anywhere in this module.

Broker access exclusively through maps/mcp_map.py — never a direct
import of maps/gateway_map.py, maps/metadata_map.py, or any domain
broker, and never direct filesystem access into garmin_data/ or
context_data/ (the diagram Timo provided this session is binding: the
only crossing point between the clients/ world and the broker layer is
mcp_map.py, even for the filename-only introspection functions
list_daily_log_filenames()/list_fail_log_filenames()/
list_recent_log_filenames() that exist solely for this module's own use
and are deliberately not registered as MCP tools in mcp_server.py — see
NOTES_v1.7.1_session2.md).

Import style: flat "import mcp_sql", not "from . import mcp_sql" — this
module is loaded via mcp_server.py's own flat "import mcp_update"
(v1.7.1 fix, see that module's docstring), which means mcp_update.py
itself carries no package context at import time; a relative import
here would raise the same "attempted relative import with no known
parent package" error mcp_server.py's own import of this module did
before that fix. clients/ is already on sys.path by the time this
module loads (mcp_server.py's sys.path root anchor runs first), so the
flat import resolves the same way mcp_map/garmin_config already do.

Concurrency (NOTES_v1.7.1_session2.md, two distinct cases):
  1. Two parallel mcp_server.py process starts, both mid boot-sync
     before either reaches mcp.run()'s own bind-based guard — closed
     here by binding garmin_config.MCP_HTTP_PORT for the duration of
     sync_all() itself, released again before returning, so a second
     process attempting the same sync gets an immediate, clear OSError
     instead of an unpredictable "database is locked" error from
     SQLite midway through a sync.
  2. Two overlapping refresh_cache() calls after boot — not covered by
     the port-bind above (the port is legitimately held by mcp.run()
     itself by then). Guarded by _REFRESH_LOCK, a plain threading.Lock,
     analogous to garmin_quality.py's QUALITY_LOCK precedent.

Per-unit error handling (NOTES_v1.7.1_session2.md, Multi-LLM-Review-Gate
finding): a single failing day/file/entry is caught, logged, and
skipped — it never aborts the whole sync_all() pass. Consistent with
the archive's own established "skip one bad file, keep the loop going"
principle (maps/metadata_map.py's _read_filtered_log_dir()).

Health field discovery: rather than maintaining a second, separately-
kept list of health field names in this module, sync_all() asks
maps/mcp_map.py's list_available_fields() for the current field set on
every run — one call per changed day, but the field list itself always
tracks health_map.py automatically, no manual sync needed when a new
field is added there.

Logging: own operational log under
<base_dir>/garmin_data/log/mcp/update/mcp_update_<timestamp>.log,
same naming/rotation convention as mcp_server.py's
_start_operational_log() (NOTES_v1.7.1_vorbereitung.md). The same
timestamp string used in this log file's name is also written as a
marker field on every line of this log, mcp_sql.py's log, and
mcp_server.py's own operational log for the same sync pass —
correlation across all three without a separate marker mechanism.
"""

import datetime
import logging
import socket
import threading
from pathlib import Path

from garmin import garmin_config as cfg
from maps import mcp_map

import mcp_sql

logger = logging.getLogger(__name__)

_REFRESH_LOCK = threading.Lock()

LOG_MCP_UPDATE_MAX = 30  # same rolling-log convention as mcp_server.py's LOG_MCP_MAX

_FORM_B_KINDS = ["stats", "device_table", "token_log", "capability_config"]
_RECENT_LOG_KINDS = ["daily_logs", "fail_logs", "recent_logs"]

# Maps each of the three recent-log kinds to the matching filename-only
# introspection function and the matching content-reading function on
# maps/mcp_map.py — kept as one explicit table here rather than three
# near-identical if/elif branches in sync_all() itself.
_RECENT_LOG_FUNCTIONS = {
    "daily_logs": {
        "list_filenames": mcp_map.list_daily_log_filenames,
        "get_lines": mcp_map.get_archive_metadata,
    },
    "fail_logs": {
        "list_filenames": mcp_map.list_fail_log_filenames,
        "get_lines": mcp_map.get_archive_metadata,
    },
    "recent_logs": {
        "list_filenames": mcp_map.list_recent_log_filenames,
        "get_lines": mcp_map.get_archive_metadata,
    },
}


def _start_update_log(base_dir: Path, timestamp: str) -> logging.FileHandler | None:
    """
    Creates <base_dir>/garmin_data/log/mcp/update/mcp_update_<timestamp>.log,
    attaches a FileHandler to this module's logger, and prunes older
    files beyond LOG_MCP_UPDATE_MAX — same rotation shape as
    mcp_server.py's _start_operational_log(). Returns None (not an
    error) if base_dir is not writable — sync_all() continues without a
    dedicated file log in that case, same "never a startup blocker"
    principle as the server's own log setup.
    """
    log_dir = base_dir / "garmin_data" / "log" / "mcp" / "update"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    log_path = log_dir / f"mcp_update_{timestamp}.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(
        logging.Formatter(f"%(asctime)s %(levelname)s [{timestamp}] %(message)s"))
    logger.addHandler(handler)

    logs = sorted(log_dir.glob("mcp_update_*.log"), key=lambda f: f.stat().st_mtime)
    for old in logs[:-LOG_MCP_UPDATE_MAX] if len(logs) > LOG_MCP_UPDATE_MAX else []:
        try:
            old.unlink()
        except OSError:
            pass

    return handler


def _sync_health_days() -> tuple[int, int]:
    """
    Form A, health: get_stats() for the archive's real date_min/date_max
    (never a hardcoded or guessed range, never the 30-day default —
    NOTES_v1.7.1_session2.md), then get_quality_log() over that full
    range to learn every day's current last_attempt. A day is a sync
    candidate if last_attempt is not null AND differs from
    mcp_sql.get_health_compare_value()'s current answer for that day —
    covers both improvements and downgrades, no special case needed
    (NOTES_v1.7.1_session2.md, quality_log delta section).

    Returns (days_updated, days_failed) — days_failed lets sync_all()'s
    result surface a partial-failure count instead of silently absorbing
    it into "not updated" (build_dep_map.py flagged the per-day
    try/except below as risk="silent" — the exception was already
    logged, but the caller had no way to learn a failure occurred at
    all, same pattern KNOWN_ISSUES.md's Cluster G already names for
    context/context_api.py — fixed here rather than left as a second
    instance of the same gap).
    """
    stats_result = mcp_map.get_archive_metadata("stats")
    date_min = stats_result["data"]["date_min"]
    date_max = stats_result["data"]["date_max"]
    if date_min is None or date_max is None:
        return 0, 0  # empty archive — nothing to sync

    quality_result = mcp_map.get_archive_metadata(
        "quality_log", date_from=date_min, date_to=date_max)
    days = quality_result["data"]["days"]

    fields_result = mcp_map.list_available_fields(domain="health")
    field_names = fields_result["fields"]["health"].get("garmin", [])

    updated = 0
    failed = 0
    for entry in days:
        day = entry["date"]
        live_compare_value = entry.get("last_attempt")
        if live_compare_value is None:
            continue  # never touched since creation — nothing to sync
        try:
            cached_compare_value = mcp_sql.get_health_compare_value(day)
            if live_compare_value == cached_compare_value:
                continue

            payload = {}
            for field in field_names:
                field_result = mcp_map.query_health(field, day, day)
                payload[field] = field_result["health"]

            mcp_sql.upsert_health_day(day, payload, live_compare_value)
            _update_day_status(day, quality=entry.get("quality"))
            updated += 1
        except Exception as exc:
            logger.warning("Health day %s failed to sync, skipping: %s", day, exc)
            failed += 1
            continue

    return updated, failed


def _sync_structured_log(kind: str) -> tuple[int, int]:
    """
    Form C, structured logs (quality_log/source_api_log): per-entry
    compare_value diff against mcp_sql's cached value. compare_value's
    meaning is formspecific — last_attempt for quality_log, max(fetched_at,
    backfilled_fields values) for source_api_log (NOTES_v1.7.1_session2.md
    correction — fetched_at alone misses additive backfills).

    Returns (entries_updated, entries_failed) — see _sync_health_days()'s
    docstring for why the failure count is surfaced rather than absorbed.
    """
    result = mcp_map.get_archive_metadata(kind)
    if result["data"] is None:
        return 0, 0

    if kind == "quality_log":
        entries = {e["date"]: e for e in result["data"]["days"]}
        compare_values = {
            date_key: entry.get("last_attempt")
            for date_key, entry in entries.items()
        }
    else:  # source_api_log
        entries = result["data"]
        compare_values = {}
        for date_key, entry in entries.items():
            candidates = [entry.get("fetched_at")]
            candidates.extend(entry.get("backfilled_fields", {}).values())
            compare_values[date_key] = max(c for c in candidates if c is not None)

    updated = 0
    failed = 0
    for date_key, entry in entries.items():
        live_compare_value = compare_values.get(date_key)
        if live_compare_value is None:
            continue
        try:
            cached_compare_value = mcp_sql.get_structured_log_compare_value(kind, date_key)
            if live_compare_value == cached_compare_value:
                continue
            mcp_sql.upsert_structured_log_entry(kind, date_key, entry, live_compare_value)
            updated += 1
        except Exception as exc:
            logger.warning("%s entry %s failed to sync, skipping: %s", kind, date_key, exc)
            failed += 1
            continue

    return updated, failed


def _sync_recent_log_files(kind: str) -> tuple[int, int]:
    """
    Form C, log files (daily_logs/fail_logs/recent_logs): full filename
    diff on every sync, no delta trigger via mcp_health_days — a log
    file's filename-date is the sync timestamp, not necessarily the
    archived day it reports on (NOTES_v1.7.1_session2.md, mcp_recent_logs
    correction). list_filenames() covers the full archive range implicitly
    via the same wide date_from/date_to used for health, passed in by the
    caller — see sync_all().

    Returns (files_added, files_failed) — see _sync_health_days()'s
    docstring for why the failure count is surfaced rather than absorbed.
    """
    funcs = _RECENT_LOG_FUNCTIONS[kind]
    known_filenames = mcp_sql.get_known_recent_log_filenames(kind)

    filenames_result = funcs["list_filenames"]()
    entries = filenames_result["data"] or []

    added = 0
    failed = 0
    for entry in entries:
        filename = entry["filename"]
        if filename in known_filenames:
            continue
        try:
            log_date = entry["log_date"]
            lines_result = funcs["get_lines"](kind, date_from=log_date, date_to=log_date)
            lines = lines_result["data"] or []
            mcp_sql.upsert_recent_log_file(kind, filename, log_date, lines)
            added += 1
        except Exception as exc:
            logger.warning("%s file %s failed to sync, skipping: %s", kind, filename, exc)
            failed += 1
            continue

    return added, failed


def _sync_context_days() -> tuple[int, int]:
    """
    Form A, context: existence-only delta, no compare_value — a context
    day, once complete, never needs re-fetching (Timo confirmed, no
    downgrade concept, NOTES_v1.7.1_session2.md). Uses the same
    date_min/date_max range as health so a long-idle archive's older,
    still-missing context days are not silently skipped by an implicit
    default range.

    Returns (days_added, days_failed) — see _sync_health_days()'s
    docstring for why the failure count is surfaced rather than absorbed.
    """
    stats_result = mcp_map.get_archive_metadata("stats")
    date_min = stats_result["data"]["date_min"]
    date_max = stats_result["data"]["date_max"]
    if date_min is None or date_max is None:
        return 0, 0

    fields_result = mcp_map.list_available_fields(domain="context")
    context_sources = fields_result["fields"]["context"]

    added = 0
    failed = 0
    current = datetime.date.fromisoformat(date_min)
    end = datetime.date.fromisoformat(date_max)
    while current <= end:
        day = current.isoformat()
        current += datetime.timedelta(days=1)
        try:
            if mcp_sql.context_day_exists(day):
                continue

            payload = {}
            has_any_data = False
            for source, field_names in context_sources.items():
                for field in field_names:
                    field_result = mcp_map.query_context(field, day, day)
                    source_result = field_result["context"].get(source, {})
                    if source_result and "error" not in source_result:
                        payload.setdefault(source, {})[field] = source_result
                        has_any_data = True

            if not has_any_data:
                continue  # day genuinely not written yet — nothing to cache

            mcp_sql.upsert_context_day(day, payload)
            _update_day_status(day, context="yes")
            added += 1
        except Exception as exc:
            logger.warning("Context day %s failed to sync, skipping: %s", day, exc)
            failed += 1
            continue

    return added, failed


def _update_day_status(day: str, quality: str | None = None,
                        context: str | None = None, fit: str | None = None) -> None:
    """Read-modify-write helper for mcp_day_status — preserves whichever
    of the three columns the caller did not pass, rather than
    clobbering them with None."""
    existing = mcp_sql.get_day_status(day) or {"quality": None, "context": None, "fit": None}
    mcp_sql.upsert_day_status(
        day,
        quality=quality if quality is not None else existing["quality"],
        context=context if context is not None else existing["context"],
        fit=fit if fit is not None else existing["fit"],
    )


def sync_all() -> dict:
    """
    Runs a full sync pass — all three forms, all data sources, both
    boot-sync and refresh_cache() call this identically (see module
    docstring). Guarded by _REFRESH_LOCK against overlapping calls
    (case 2 in the module docstring's concurrency section); a second
    call arriving while one is already running blocks until the first
    completes rather than running concurrently.

    Returns a result dict — used for the boot-log entry as well as the
    refresh_cache() MCP tool's direct answer to the LLM:
        {
            "health_days_updated": int,
            "health_days_failed": int,
            "context_days_updated": int,
            "context_days_failed": int,
            "fit_days_updated": int,          # always 0 — FIT stub
            "snapshots_refreshed": list[str], # which Form-B kinds were re-fetched
            "log_files_added": int,           # Form-C file count, all three kinds combined
            "log_files_failed": int,
            "structured_log_entries_updated": int,  # quality_log + source_api_log combined
            "structured_log_entries_failed": int,
            "duration_seconds": float,
            "marker": str,                    # shared sync marker, see module docstring
        }

    The *_failed counters (v1.7.1, added after build_dep_map.py flagged
    the per-unit except blocks below as risk="silent" — logged, but the
    caller previously had no way to learn a failure occurred) are not
    just diagnostics: a non-zero count here is the only way the LLM (via
    refresh_cache()) or the boot log can tell "sync ran clean" apart
    from "sync ran but silently dropped some units" — see
    _sync_health_days()'s docstring for the same reasoning per
    sync function.
    """
    with _REFRESH_LOCK:
        marker = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        handler = _start_update_log(cfg.BASE_DIR, marker)
        start = datetime.datetime.now()

        # Concurrency guard, case 1 (module docstring) — held only for
        # the duration of this sync pass, released before returning so
        # mcp.run() can bind the same port normally afterwards.
        guard_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            guard_socket.bind(("127.0.0.1", cfg.MCP_HTTP_PORT))
        except OSError as exc:
            logger.error(
                "Could not start sync — port %d already in use, "
                "another sync is likely already running: %s",
                cfg.MCP_HTTP_PORT, exc)
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()
            raise

        try:
            mcp_sql.init_db()

            health_days_updated, health_days_failed = _sync_health_days()
            context_days_updated, context_days_failed = _sync_context_days()

            structured_entries_updated = 0
            structured_entries_failed = 0
            for kind in ("quality_log", "source_api_log"):
                _updated, _failed = _sync_structured_log(kind)
                structured_entries_updated += _updated
                structured_entries_failed += _failed

            snapshots_refreshed = []
            for kind in _FORM_B_KINDS:
                snapshot_result = mcp_map.get_archive_metadata(kind)
                if snapshot_result["data"] is not None:
                    mcp_sql.upsert_snapshot(
                        kind, snapshot_result["data"],
                        datetime.datetime.now().isoformat())
                    snapshots_refreshed.append(kind)

            log_files_added = 0
            log_files_failed = 0
            for kind in _RECENT_LOG_KINDS:
                _added, _failed = _sync_recent_log_files(kind)
                log_files_added += _added
                log_files_failed += _failed

            duration = (datetime.datetime.now() - start).total_seconds()
            result = {
                "health_days_updated": health_days_updated,
                "health_days_failed": health_days_failed,
                "context_days_updated": context_days_updated,
                "context_days_failed": context_days_failed,
                "fit_days_updated": 0,
                "snapshots_refreshed": snapshots_refreshed,
                "log_files_added": log_files_added,
                "log_files_failed": log_files_failed,
                "structured_log_entries_updated": structured_entries_updated,
                "structured_log_entries_failed": structured_entries_failed,
                "duration_seconds": duration,
                "marker": marker,
            }
            logger.info("Sync complete: %s", result)
            return result
        finally:
            guard_socket.close()
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()
