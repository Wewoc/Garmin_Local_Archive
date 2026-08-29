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

Concurrency (NOTES_v1.7.1_session2.md, two distinct cases; case 1's
guard corrected 2026-08-28 — see KNOWN_ISSUES.md for the diagnosis):
  1. Two parallel mcp_server.py process starts, both mid boot-sync
     before either reaches mcp.run()'s own bind-based guard — closed
     by binding garmin_config.MCP_HTTP_PORT for the duration of
     sync_all(is_boot=True) only, released again before returning, so
     a second process attempting the same boot sync gets an immediate,
     clear OSError instead of an unpredictable "database is locked"
     error from SQLite midway through a sync. is_boot=False (the
     refresh_cache() path) skips this guard entirely — by the time
     refresh_cache() can be called at all, mcp.run() already legitimately
     holds this same port, so the original unconditional bind attempt
     here always failed after boot, making refresh_cache() permanently
     unusable at runtime (the actual bug this correction fixes).
  2. Two overlapping refresh_cache() calls after boot — guarded by
     _REFRESH_LOCK, a plain threading.Lock, analogous to
     garmin_quality.py's QUALITY_LOCK precedent. This was always the
     right guard for this case; the port-bind in case 1 was never
     meant to also cover it.

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

# How many days without a raw/ file, at the *end* of the archive's
# known date range, are still worth an unconditional recheck before a
# missing field is treated as "confirmed absent for this day" — same
# purpose as garmin_quality.py's INTRADAY_RETRY_WINDOW_DAYS, but a
# deliberately independent constant: raw-passthrough fields (weigh-ins,
# blood pressure, etc.) have no factual link to the Garmin device's
# intraday-availability window that constant governs (Timo confirmed,
# NOTES_v1.7.1.1_session2.md — no prev_high-style coupling for raw).
RAW_RETRY_WINDOW_DAYS = 14

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
    range to learn every day's current last_checked. A day is a sync
    candidate if last_checked differs from
    mcp_sql.get_health_compare_value()'s current answer for that day —
    covers both improvements and downgrades, no special case needed
    (NOTES_v1.7.1_session2.md, quality_log delta section).

    v1.7.1.1 diagnosis correction (session 2026-08-28): the original
    compare_value was last_attempt, which garmin_quality.py only sets
    on an actual recheck attempt — for an archive where days reach
    "high"/"standard" on first contact and never need a recheck,
    last_attempt stays null for effectively every day, so this
    function silently synced nothing. last_checked is written on
    every upsert (new day or recheck alike) and is therefore never
    null — see KNOWN_ISSUES.md for the full diagnosis chain.

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
        live_compare_value = entry.get("last_checked")
        if live_compare_value is None:
            continue  # entry has no last_checked at all — malformed, skip
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
    meaning is formspecific — last_checked for quality_log, max(fetched_at,
    backfilled_fields values) for source_api_log (NOTES_v1.7.1_session2.md
    correction — fetched_at alone misses additive backfills).

    v1.7.1.1 diagnosis correction (session 2026-08-28): quality_log's
    compare_value was originally last_attempt — see _sync_health_days()'s
    docstring for why that field is null for effectively every day in
    an archive with no recheck history, and why last_checked (written
    on every upsert, never null) replaces it here too.

    Returns (entries_updated, entries_failed) — see _sync_health_days()'s
    docstring for why the failure count is surfaced rather than absorbed.
    """
    result = mcp_map.get_archive_metadata(kind)
    if result["data"] is None:
        return 0, 0

    if kind == "quality_log":
        entries = {e["date"]: e for e in result["data"]["days"]}
        compare_values = {
            date_key: entry.get("last_checked")
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
    Form A, context: per-source completeness delta (v1.7.1.1 follow-up
    fix, replacing the original existence-only delta — see
    mcp_sql.get_context_day_state()'s docstring for the full
    rationale). A day is a sync candidate if any currently-registered
    context source is missing from its complete_sources set. Missing
    sources are re-queried; a source already in attempted_sources
    (queried once before, still without data) is queried exactly one
    more time and then either gains data (added to complete_sources)
    or is accepted as permanently empty for that day (Timo: "wenn der
    tag leer ist und nicht liefern kann als ok markieren" — no
    unbounded retry, no age-window needed the way raw-passthrough
    fields required, since a context source either answers with data
    or with a definitive "nothing here", unlike raw/health's
    possible-later-availability case). Uses the same date_min/date_max
    range as health so a long-idle archive's older, still-incomplete
    context days are not silently skipped by an implicit default range.

    Returns (days_touched, days_failed) — days_touched counts days
    where at least one source was (re-)queried, mirroring
    _sync_raw_fields()'s "touched" terminology rather than the old
    "added" (a day can now be legitimately revisited more than once,
    unlike the old existence-only model where "added" meant "written
    for the first and only time") — see _sync_health_days()'s
    docstring for why the failure count is surfaced rather than
    absorbed.
    """
    stats_result = mcp_map.get_archive_metadata("stats")
    date_min = stats_result["data"]["date_min"]
    date_max = stats_result["data"]["date_max"]
    if date_min is None or date_max is None:
        return 0, 0

    fields_result = mcp_map.list_available_fields(domain="context")
    context_sources = fields_result["fields"]["context"]
    all_source_names = set(context_sources.keys())

    touched = 0
    failed = 0
    current = datetime.date.fromisoformat(date_min)
    end = datetime.date.fromisoformat(date_max)
    while current <= end:
        day = current.isoformat()
        current += datetime.timedelta(days=1)
        try:
            existing = mcp_sql.get_context_day_state(day)
            payload = existing["payload"] if existing is not None else {}
            complete_sources = existing["complete_sources"] if existing is not None else set()
            attempted_sources = existing["attempted_sources"] if existing is not None else set()

            missing_sources = all_source_names - complete_sources
            # A source already attempted once without data gets exactly
            # one more try (this pass) — a source never attempted at all
            # gets its first try. Both cases query the same way below;
            # the distinction only matters for what happens on a repeat
            # empty result (see below).
            sources_to_query = missing_sources
            if not sources_to_query:
                continue  # day already complete — nothing to do

            day_had_activity = False
            for source in sources_to_query:
                field_names = context_sources[source]
                source_had_data = False
                for field in field_names:
                    field_result = mcp_map.query_context(field, day, day)
                    source_result = field_result["context"].get(source, {})
                    if source_result and "error" not in source_result:
                        payload.setdefault(source, {})[field] = source_result
                        source_had_data = True
                day_had_activity = True
                if source_had_data:
                    complete_sources.add(source)
                    attempted_sources.add(source)
                elif source in attempted_sources:
                    # Second empty result in a row for this source —
                    # accepted as permanently empty for this day (Timo,
                    # see docstring). Counted as "complete" too: an
                    # accepted-empty source must not keep re-triggering
                    # sources_to_query on every future sync pass, same
                    # "no dauer-resync" concern raw-passthrough already
                    # solved differently (age window) — here solved by
                    # folding "confirmed empty" into the same set as
                    # "confirmed has data", since both mean "settled,
                    # do not touch again".
                    complete_sources.add(source)
                else:
                    # First empty result — mark attempted, will get one
                    # more try on the next sync pass.
                    attempted_sources.add(source)

            if not day_had_activity:
                continue

            mcp_sql.upsert_context_day(day, payload, complete_sources, attempted_sources)
            if complete_sources == all_source_names:
                _update_day_status(day, context="yes")
            touched += 1
        except Exception as exc:
            logger.warning("Context day %s failed to sync, skipping: %s", day, exc)
            failed += 1
            continue

    return touched, failed


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


def _sync_one_raw_field(day: str, field: str) -> bool:
    """
    Queries a single (day, field) raw-passthrough value through
    mcp_map.query_raw() and upserts the result — recheck/attempts/
    last_attempt computed per the module's own convention (Timo's
    explicit reference to garmin_quality.py's recheck/attempts pattern,
    reimplemented independently rather than imported — see
    mcp_sql.upsert_raw_field()'s docstring for why).

    Exception during the query -> caught here (not propagated),
    recheck=1, attempts incremented, logged (mirrors "failed" in
    garmin/quality/_maint.py) — returns False. No exception, value
    present -> recheck=0 (resolved) — returns True. No exception,
    value absent (payload["raw"] is None) -> recheck depends on
    day_age against RAW_RETRY_WINDOW_DAYS: still within the window ->
    recheck=1 (too early to call this "confirmed absent"), outside
    the window -> recheck=0 (accepted as final, same "high forever"
    spirit as garmin/quality/_maint.py's high-quality entries, applied
    here to "no value" instead of "quality assessed") — returns True
    either way (a successfully-determined absence is not a failure).

    Never raises — the caller (_sync_raw_fields()) only needs the
    returned bool for its fields_failed count, same
    "mcp_sql.py throws, callers catch per unit" split used everywhere
    else in this module, just localized one level lower here since a
    single field's exception must not also block its sibling fields
    on the same day from being attempted.
    """
    attempts_before = mcp_sql.get_raw_field_attempts(day, field)
    now_str = datetime.datetime.now().isoformat()

    try:
        result = mcp_map.query_raw(field, day, day, domain="health")
        field_result = result["health"].get(field, {})
        values = field_result.get("values", [])
        raw_value = values[0]["raw"] if values else None
    except Exception as exc:
        logger.warning("Raw field %s/%s failed to sync, skipping: %s",
                        day, field, exc)
        mcp_sql.upsert_raw_field(day, field, None, recheck=True,
                                  attempts=attempts_before + 1, last_attempt=now_str)
        return False

    if raw_value is not None:
        mcp_sql.upsert_raw_field(day, field, {"raw": raw_value}, recheck=False,
                                  attempts=attempts_before, last_attempt=now_str)
        return True

    day_age = (datetime.date.today() - datetime.date.fromisoformat(day)).days
    still_pending = day_age < RAW_RETRY_WINDOW_DAYS
    mcp_sql.upsert_raw_field(day, field, None, recheck=still_pending,
                              attempts=attempts_before, last_attempt=now_str)
    return True


def _sync_raw_fields() -> tuple[int, int]:
    """
    Form A variant, raw-passthrough: field-granular, hash-gated delta —
    structurally distinct from _sync_health_days()/_sync_context_days()
    because a single existence/compare_value check per day is not
    enough here (KONZEPT clarified across several rounds with Timo,
    NOTES_v1.7.1.1_session2.md — see "Sync-Reichweite pro Lauf" /
    "mtime-Idee" / "Speicherort des Tages-Hash" sections for the full
    reasoning trail):

      1. list_raw_fields() is read fresh on every call (live field
         registry, never hard-coded — the 13-field count is today's
         state, not a permanent one, per Timo's original query about
         garmin_api_capability.py's role here).
      2. get_stats() gives the archive's real date_min/date_max, same
         as every other _sync_*() function — never a hardcoded range.
      3. metadata_map.get_raw_file_hashes() (via mcp_map) is read once
         for the whole range, compared per day against
         mcp_sql.get_raw_day_hash(): unchanged day -> only that day's
         currently-pending fields (mcp_sql.get_pending_raw_fields())
         are re-queried; changed or new day -> every currently
         registered field is (re-)queried, covering both a brand-new
         day and nachtraegliche Datenlieferung to an old, previously
         "resolved" day alike, without a separate manual-reset code
         path.
      3b. Content hash, not mtime — a mirror/restore rewriting the same
          bytes must not look like a change (Timo's explicit challenge,
          confirmed against metadata_map.py's own pre-existing mtime
          warning for log filenames).

    Returns (days_touched, fields_failed) — days_touched counts days
    where at least one field was queried (new or hash-changed or had
    pending fields), fields_failed counts individual field-query
    exceptions, same "surface partial failure, never silently absorb
    it" principle as every other _sync_*() function's docstring.
    """
    stats_result = mcp_map.get_archive_metadata("stats")
    date_min = stats_result["data"]["date_min"]
    date_max = stats_result["data"]["date_max"]
    if date_min is None or date_max is None:
        return 0, 0

    fields_result = mcp_map.list_raw_fields(domain="health")
    raw_field_names = fields_result.get("health", [])

    hashes_result = mcp_map.get_raw_file_hashes(date_min, date_max)
    live_hashes = hashes_result["data"] or {}

    days_touched = 0
    fields_failed = 0
    current = datetime.date.fromisoformat(date_min)
    end = datetime.date.fromisoformat(date_max)
    while current <= end:
        day = current.isoformat()
        current += datetime.timedelta(days=1)

        live_hash = live_hashes.get(day)
        if live_hash is None:
            continue  # no raw/ file for this day at all — nothing to sync

        cached_hash = mcp_sql.get_raw_day_hash(day)
        if live_hash == cached_hash:
            fields_to_sync = mcp_sql.get_pending_raw_fields(day)
        else:
            fields_to_sync = set(raw_field_names)

        if not fields_to_sync:
            continue

        day_had_activity = False
        for field in fields_to_sync:
            ok = _sync_one_raw_field(day, field)
            day_had_activity = True
            if not ok:
                fields_failed += 1

        if day_had_activity:
            mcp_sql.upsert_raw_day_hash(day, live_hash)
            days_touched += 1

    return days_touched, fields_failed


def sync_all(is_boot: bool = False) -> dict:
    """
    Runs a full sync pass — all three forms, all data sources, both
    boot-sync and refresh_cache() call this (see module docstring).
    Guarded by _REFRESH_LOCK against overlapping calls (case 2 in the
    module docstring's concurrency section); a second call arriving
    while one is already running blocks until the first completes
    rather than running concurrently.

    is_boot : bool
      True  — called from mcp_server.py's startup sequence, before
              mcp.run() has bound the port. The port-bind guard (case 1)
              runs, protecting against two parallel process starts.
      False — called from the refresh_cache() MCP tool while the server
              is already running and legitimately holds the port. The
              port-bind guard is skipped — attempting it here always
              failed (the port is never free at this point), which
              made refresh_cache() unconditionally error out at runtime
              until this correction (2026-08-28 diagnosis session).

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
        guard_socket = None
        if is_boot:
            guard_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                guard_socket.bind(("127.0.0.1", cfg.MCP_HTTP_PORT))
            except OSError as exc:
                logger.error(
                    "Could not start boot sync — port %d already in use, "
                    "another instance is likely already starting: %s",
                    cfg.MCP_HTTP_PORT, exc)
                if handler is not None:
                    logger.removeHandler(handler)
                    handler.close()
                raise

        try:
            mcp_sql.init_db()

            health_days_updated, health_days_failed = _sync_health_days()
            context_days_updated, context_days_failed = _sync_context_days()
            raw_days_touched, raw_fields_failed = _sync_raw_fields()

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
                "raw_days_touched": raw_days_touched,
                "raw_fields_failed": raw_fields_failed,
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
            if guard_socket is not None:
                guard_socket.close()
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()
