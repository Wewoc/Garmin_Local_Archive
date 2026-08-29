#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
metadata_map.py

Introspection broker — read-only access to archive-state artefacts that
do not belong to any of the other domain brokers (health, fit, context).
Catch-all by design: intended to stay open for future data that fits
none of the existing domains, not just today's nine functions.

Unlike health_map.py / context_map.py, this broker's data is NOT
time-series based — there is no field/resolution concept here (v1.7.0.4:
five of the nine functions gained an optional date_from/date_to RANGE
FILTER, which is not the same thing — see below). Each function answers
"what is the current state of X" (optionally narrowed to a date range),
not "give me a series of values with a chosen resolution". That is why
this broker has its own return shape and its own entry point in
gateway_map.py (get_metadata(), not get()) instead of reusing the
time-series contract.

Date-range filtering (v1.7.0.4): get_quality_log, get_source_api_log,
get_daily_logs, get_fail_logs, get_recent_logs accept optional
date_from/date_to (ISO "YYYY-MM-DD", inclusive on both ends). Added
after real-world MCP-proxy logs showed get_quality_log() returning a
2.8 MB unfiltered dump on every call (~2800 archive days, one entry per
day since archive start) — enough to blow past an 8k-12k TPM token
budget on cloud LLM providers (Groq/Gemini free tier) in a single call.
Neither a "resolution" concept nor mcp_map.py's "_meta" weekday table is
added here — this is a plain range filter over an already date-indexed
collection (JSON keys, or log filenames), not a time-series query.

Default when neither date_from nor date_to is given: last 30 days
(anchored on the latest available data, not on today's calendar date —
see _default_date_range() below), plus a "note" field in the return
value warning that a narrower or wider explicit range can be requested.
Deliberately not an error and not an unfiltered dump — a small, useful
answer beats forcing the caller to already know the right parameters.
Untouched: get_stats, get_device_table, get_capability_config,
get_token_log — these were already small/bounded and do not grow with
archive length, so no date concept was added to them (see NOTES_v1.7.0.4
_metadata_filter.md for the full reasoning).

Routing/read-only layer — knows which archive-state files exist and how
to reach them (via garmin_config.py path constants), but owns none of
them. All nine functions are Sole-Write-Authority-respecting: read only,
never write, never migrate, never interpret beyond raw passthrough.

Hard exclusion: GARMIN_TOKEN_FILE (garmin_token.enc) is never referenced
anywhere in this module. The encrypted token itself must never become
reachable through this broker, since this broker is designed to
eventually sit behind gateway_map.py and, later, an MCP server (v1.7).

Error behavior: consistent with health_map.py / context_map.py — never
raises. Read/parse failures are caught internally and returned as a
degraded {"data": None, "error": str} result, never as an exception
propagating to the caller.

Log sanitization: the three raw-log functions (get_daily_logs,
get_fail_logs, get_recent_logs) pass every line through _sanitize_line()
before returning it. Lines containing recognized secret/auth material
(JWT/Base64 token fragments, Authorization/Cookie headers, password
fields) are dropped entirely. Lines containing recognized PII (email,
IPv4, GPS coordinates) are masked, not dropped, so their diagnostic
value is preserved.

Usage (from a cross-domain consumer):
    from maps.metadata_map import get_stats, get_device_table
    result = get_stats()
    result = get_device_table()
    result = get_quality_log(date_from="2026-08-01", date_to="2026-08-27")

Return structure (all nine functions):
    {
        "data":  <dict | list[str] | None>,
        "error": <str | None>,
        # "note" (v1.7.0.4): only present, and only on the five
        # date-filterable functions, when the 30-day default range was
        # applied because neither date_from nor date_to was given.
        # Never carried in "error" — that field signals an actual
        # failure, and applying the default is not one.
    }
"""

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from garmin import garmin_config as cfg
from garmin.quality import _stats

# Matches a "YYYY-MM-DD_HHMMSS.log" date/time stamp anywhere before the
# extension, regardless of filename prefix. Prefixes vary and some
# themselves contain underscores (garmin_, garmin_background_,
# test_connection_, daily_) — anchoring on the digit pattern itself,
# not on a fixed number of leading underscore-separated segments, is
# what keeps this correct across all of them (v1.7.0.4).
_LOG_FILENAME_DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})_\d{6}\.log$')

_DEFAULT_RANGE_DAYS = 30

# ══════════════════════════════════════════════════════════════════════════════
#  Log sanitization — secret material dropped, PII masked
# ══════════════════════════════════════════════════════════════════════════════

_SECRET_LINE_PATTERNS = [
    re.compile(r'eyJ[A-Za-z0-9_-]{10,}', re.IGNORECASE),           # JWT / Base64 token fragments
    re.compile(r'(?:bearer|authorization)\s*[:=]', re.IGNORECASE),  # Auth headers
    re.compile(r'(?:refresh|access|id)[_-]?token', re.IGNORECASE),  # Token keywords
    re.compile(r'password\s*[:=]', re.IGNORECASE),                  # Password fragments
    re.compile(r'cookie\s*[:=]', re.IGNORECASE),                    # Session cookies
]

_PII_MASK_PATTERNS = [
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[EMAIL]'),
    (re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b'), '[IP]'),
    (re.compile(r'\blat[=:]\s*-?\d+\.\d+', re.IGNORECASE), 'lat=[COORD]'),
    (re.compile(r'\blon[=:]\s*-?\d+\.\d+', re.IGNORECASE), 'lon=[COORD]'),
]


def _sanitize_line(line: str) -> str | None:
    """
    Returns None if the line should be dropped entirely (recognized secret
    material), otherwise the line with recognized PII masked.
    """
    for pat in _SECRET_LINE_PATTERNS:
        if pat.search(line):
            return None
    for pat, repl in _PII_MASK_PATTERNS:
        line = pat.sub(repl, line)
    return line


# _read_log_dir() removed (v1.7.0.4) — after get_daily_logs/get_fail_logs/
# get_recent_logs were rewired to _read_filtered_log_dir() below, this
# function had no remaining callers. Removed rather than left as dead
# code (Cluster-D principle — unused parallel implementations are not
# kept "just in case").

def _read_json_file(file_path: Path) -> dict:
    """Reads and parses a JSON file. Raises on missing/corrupt file —
    callers are responsible for catching and degrading."""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _default_date_range(latest: str | None) -> tuple[str, str]:
    """
    Builds the fallback (date_from, date_to) pair used whenever a
    date-filterable function is called with neither parameter set.
    Anchored on the latest date actually present in the data (not on
    today's calendar date) so the default window still returns
    something useful for an archive whose most recent entry is a few
    days old (e.g. a sync that has not run today yet). Falls back to
    today if no data-derived latest date is available (empty archive).
    """
    end = _parse_iso_date(latest) if latest else date.today()
    start = end - timedelta(days=_DEFAULT_RANGE_DAYS - 1)
    return start.isoformat(), end.isoformat()


def _default_range_note(date_from: str, date_to: str) -> str:
    return (
        f"No date_from/date_to given — showing the last {_DEFAULT_RANGE_DAYS} "
        f"days ({date_from} to {date_to}). Pass date_from/date_to explicitly "
        f"for a different or wider range."
    )


def _filter_dict_by_date(data: dict, key_getter, date_from: str | None,
                          date_to: str | None) -> tuple[dict, str | None]:
    """
    Shared range-filter core for the two JSON-backed functions
    (get_quality_log, get_source_api_log). key_getter extracts the ISO
    date string for a single entry — the two callers differ in where
    that date lives (a "date" field inside each item of a "days" list,
    vs. the dict's own top-level keys), so the actual filtering loop is
    shared but the entry/date extraction is not.

    Returns (filtered_data, note) — note is None unless the 30-day
    default was applied.
    """
    all_dates = sorted(key_getter(data))
    note = None
    if date_from is None and date_to is None:
        latest = all_dates[-1] if all_dates else None
        date_from, date_to = _default_date_range(latest)
        note = _default_range_note(date_from, date_to)
    lo = _parse_iso_date(date_from) if date_from else None
    hi = _parse_iso_date(date_to) if date_to else None

    def in_range(d: str) -> bool:
        parsed = _parse_iso_date(d)
        if lo is not None and parsed < lo:
            return False
        if hi is not None and parsed > hi:
            return False
        return True

    return in_range, note


def _filter_log_files(dir_path: Path, date_from: str | None,
                       date_to: str | None) -> tuple[list[Path], str | None]:
    """
    Filters *.log files in dir_path by the date encoded in their
    filename (see _LOG_FILENAME_DATE_RE) — a session-per-file model, so
    filtering happens on the file list before any file is opened, never
    line-by-line inside a file. Files whose name does not match the
    expected pattern are skipped silently (same "degrade, never raise"
    principle as the rest of this module) rather than included
    unfiltered or raising.

    Returns (matching_files, note) — note is None unless the 30-day
    default was applied. matching_files is sorted by filename.
    """
    all_files = sorted(dir_path.glob("*.log")) if dir_path.is_dir() else []
    dated_files = []
    for f in all_files:
        m = _LOG_FILENAME_DATE_RE.search(f.name)
        if m:
            dated_files.append((m.group(1), f))

    note = None
    if date_from is None and date_to is None:
        latest = max((d for d, _ in dated_files), default=None)
        date_from, date_to = _default_date_range(latest)
        note = _default_range_note(date_from, date_to)
    lo = _parse_iso_date(date_from) if date_from else None
    hi = _parse_iso_date(date_to) if date_to else None

    result = []
    for d, f in dated_files:
        parsed = _parse_iso_date(d)
        if lo is not None and parsed < lo:
            continue
        if hi is not None and parsed > hi:
            continue
        result.append(f)
    return result, note


def _list_filtered_log_filenames(dir_path: Path, date_from: str | None,
                                  date_to: str | None) -> tuple[list[dict], str | None]:
    """
    Shared implementation for list_daily_log_filenames/
    list_fail_log_filenames/list_recent_log_filenames (v1.7.1) — sibling
    to _read_filtered_log_dir() below, same _filter_log_files() filtering
    core, but returns filenames + their parsed filename-date instead of
    reading and sanitizing file contents. Intended for internal sync
    bookkeeping (clients/mcp_update.py's SQLite proxy), which needs to
    know which log files exist without paying the cost of reading and
    sanitizing every line of every file on each sync pass.

    Returns (entries, note) — note is None unless the 30-day default
    was applied (see _filter_log_files()). entries is a list of
    {"filename": str, "log_date": str} dicts, one per matching file,
    in the same filename-sorted order _filter_log_files() already
    produces — log_date is the filename-encoded date already extracted
    by _filter_log_files() internally, not the file's mtime (mtime could
    be altered by a mirror/restore operation; the filename-encoded date
    cannot).
    """
    files, note = _filter_log_files(dir_path, date_from, date_to)
    entries = [
        {"filename": f.name, "log_date": _LOG_FILENAME_DATE_RE.search(f.name).group(1)}
        for f in files
    ]
    return entries, note


def _read_filtered_log_dir(dir_path: Path, date_from: str | None,
                            date_to: str | None) -> tuple[list[str], str | None]:
    """
    Shared implementation for get_daily_logs/get_fail_logs/
    get_recent_logs (v1.7.0.4) — all three read the same way, filter
    the same way, and sanitize the same way; only dir_path differs
    between them. Filters the directory's *.log files by filename date
    (see _filter_log_files), then reads and sanitizes each selected
    file's lines (same per-line _sanitize_line() pass _read_log_dir()
    already used, kept identical here so filtered and unfiltered reads
    degrade the same way on an unreadable file).

    Returns (sanitized_lines, note) — note is None unless the 30-day
    default was applied.
    """
    files, note = _filter_log_files(dir_path, date_from, date_to)
    lines: list[str] = []
    for log_file in files:
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    sanitized = _sanitize_line(raw_line.rstrip("\n"))
                    if sanitized is not None:
                        lines.append(sanitized)
        except OSError:
            # Single unreadable file — skip it, keep collecting the rest,
            # same as _read_log_dir()'s existing degrade behaviour.
            continue
    return lines, note


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — nine named functions, one per archive-state artefact
# ══════════════════════════════════════════════════════════════════════════════

def get_stats() -> dict:
    """
    Archive coverage/status summary — passthrough of
    quality.get_archive_stats() (total/high/standard/failed/recheck/
    missing/date_min/date_max/coverage_pct/last_api/last_bulk/
    integrity_warnings).
    """
    try:
        return {"data": _stats.get_archive_stats(cfg.QUALITY_LOG_FILE), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_device_table() -> dict:
    """Device breakdown — raw content of device_table.json."""
    try:
        return {"data": _read_json_file(cfg.DEVICE_TABLE_FILE), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_quality_log(date_from: str | None = None,
                     date_to: str | None = None) -> dict:
    """
    Content of quality_log.json, optionally narrowed to a date range
    (v1.7.0.4). date_from/date_to are ISO "YYYY-MM-DD", inclusive on
    both ends. With neither given, defaults to the last 30 days
    (anchored on the latest tracked day) and adds a "note" field to the
    result explaining that — see module docstring. quality_log.json's
    own shape ({"days": [...], "integrity_warnings": [...]}) is
    preserved; only the "days" list is filtered, "integrity_warnings"
    is passed through unfiltered (it is not date-indexed).
    """
    try:
        full = _read_json_file(cfg.QUALITY_LOG_FILE)
        days = full.get("days", [])
        in_range, note = _filter_dict_by_date(
            full, lambda d: [entry["date"] for entry in d.get("days", [])],
            date_from, date_to,
        )
        filtered = {
            **full,
            "days": [entry for entry in days if in_range(entry["date"])],
        }
        result = {"data": filtered, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_source_api_log(date_from: str | None = None,
                        date_to: str | None = None) -> dict:
    """
    Content of source_api_log.json, optionally narrowed to a date range
    (v1.7.0.4). date_from/date_to are ISO "YYYY-MM-DD", inclusive on
    both ends. With neither given, defaults to the last 30 days
    (anchored on the latest logged day) and adds a "note" field — see
    module docstring. Unlike quality_log.json, this file's top-level
    keys already are the ISO dates themselves, so filtering is a direct
    key selection rather than filtering a nested list.
    """
    try:
        full = _read_json_file(cfg.SOURCE_API_LOG)
        in_range, note = _filter_dict_by_date(
            full, lambda d: list(d.keys()), date_from, date_to,
        )
        filtered = {k: v for k, v in full.items() if in_range(k)}
        result = {"data": filtered, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_token_log() -> dict:
    """
    Token event log — created/invalidated/blocked/valid events only,
    never token content. Path is built locally (no central constant for
    this file in garmin_config.py, consistent with garmin_security.py's
    existing pattern).
    """
    try:
        return {"data": _read_json_file(cfg.LOG_DIR / "garmin_token_log.json"), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_capability_config() -> dict:
    """Raw content of garmin_api_capability_config.json."""
    try:
        return {"data": _read_json_file(cfg.CAPABILITY_CONFIG_FILE), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_daily_logs(date_from: str | None = None,
                    date_to: str | None = None) -> dict:
    """
    Sanitized lines from *.log files in garmin_data/log/daily/,
    optionally narrowed to a date range (v1.7.0.4) — filtering happens
    per FILE (one log file = one sync session), by the date encoded in
    the filename, not per line. date_from/date_to are ISO "YYYY-MM-DD",
    inclusive on both ends. With neither given, defaults to the last 30
    days (anchored on the latest matching file) and adds a "note" field
    — see module docstring and _read_filtered_log_dir().
    """
    try:
        data, note = _read_filtered_log_dir(cfg.LOG_DAILY_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_fail_logs(date_from: str | None = None,
                   date_to: str | None = None) -> dict:
    """
    Sanitized lines from *.log files in garmin_data/log/fail/,
    optionally narrowed to a date range (v1.7.0.4) — same file-level
    filtering as get_daily_logs(), see _read_filtered_log_dir().
    date_from/date_to are ISO "YYYY-MM-DD", inclusive on both ends.
    With neither given, defaults to the last 30 days and adds a "note"
    field — see module docstring.
    """
    try:
        data, note = _read_filtered_log_dir(cfg.LOG_FAIL_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_recent_logs(date_from: str | None = None,
                     date_to: str | None = None) -> dict:
    """
    Sanitized lines from *.log files in garmin_data/log/recent/,
    optionally narrowed to a date range (v1.7.0.4) — same file-level
    filtering as get_daily_logs(), see _read_filtered_log_dir().
    date_from/date_to are ISO "YYYY-MM-DD", inclusive on both ends.
    With neither given, defaults to the last 30 days and adds a "note"
    field — see module docstring.
    """
    try:
        data, note = _read_filtered_log_dir(cfg.LOG_RECENT_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
#  Filename-only introspection — internal sync use (v1.7.1), not part of
#  the nine LLM-facing functions above. NOT registered as an MCP tool —
#  clients/mcp_update.py (SQLite proxy sync) calls these via
#  maps/mcp_map.py as plain Python functions to learn which log files
#  exist without reading their content, so it can diff its own SQLite
#  cache's known filenames against the archive's actual ones. See
#  KONZEPT_mcp_sqlite_proxy_V2.md / NOTES_v1.7.1_session2.md for the
#  full rationale (get_daily_logs() etc. return a flat sanitized line
#  list with no per-file attribution, which is not enough to populate a
#  filename-keyed SQLite table).
# ══════════════════════════════════════════════════════════════════════════════

def list_daily_log_filenames(date_from: str | None = None,
                              date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of *.log files in
    garmin_data/log/daily/, optionally narrowed to a date range — same
    file-level filtering as get_daily_logs(), see
    _list_filtered_log_filenames(). date_from/date_to are ISO
    "YYYY-MM-DD", inclusive on both ends. With neither given, defaults
    to the last 30 days and adds a "note" field — see module docstring.
    Content-free by design: use get_daily_logs() to read the actual
    sanitized lines once a relevant filename has been identified.
    """
    try:
        data, note = _list_filtered_log_filenames(cfg.LOG_DAILY_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def list_fail_log_filenames(date_from: str | None = None,
                             date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of *.log files in
    garmin_data/log/fail/, optionally narrowed to a date range — same
    file-level filtering as get_fail_logs(), see
    _list_filtered_log_filenames(). date_from/date_to are ISO
    "YYYY-MM-DD", inclusive on both ends. With neither given, defaults
    to the last 30 days and adds a "note" field — see module docstring.
    """
    try:
        data, note = _list_filtered_log_filenames(cfg.LOG_FAIL_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def list_recent_log_filenames(date_from: str | None = None,
                               date_to: str | None = None) -> dict:
    """
    Filenames (+ filename-encoded date) of *.log files in
    garmin_data/log/recent/, optionally narrowed to a date range — same
    file-level filtering as get_recent_logs(), see
    _list_filtered_log_filenames(). date_from/date_to are ISO
    "YYYY-MM-DD", inclusive on both ends. With neither given, defaults
    to the last 30 days and adds a "note" field — see module docstring.
    """
    try:
        data, note = _list_filtered_log_filenames(cfg.LOG_RECENT_DIR, date_from, date_to)
        result = {"data": data, "error": None}
        if note is not None:
            result["note"] = note
        return result
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_raw_file_hashes(date_from: str, date_to: str) -> dict:
    """
    SHA-256 content hash of the raw/ file for each day in the given
    range — internal sync use (v1.7.1.1), NOT registered as an MCP
    tool. Content-only signal, deliberately not the file's mtime: a
    mirror/restore operation can rewrite garmin_raw_{date}.json with
    byte-identical content, which would change mtime but must not be
    read as "this day's raw data changed" — same reasoning
    list_daily_log_filenames() etc. already apply to log filenames
    (see that function's docstring), applied here to raw/ file content
    instead of a filename-encoded date.

    Used exclusively by clients/mcp_update.py's SQLite proxy sync
    (mcp_raw_day_hashes table) to detect genuine content changes to a
    day's raw/ file — including nachtraegliche Datenlieferung (GDPR
    bulk import, silo repair) for a day whose recheck window had
    already closed — without re-reading and re-comparing every one of
    that day's raw-passthrough field values on every sync pass.

    Unlike the nine LLM-facing functions above, both date_from and
    date_to are required (no 30-day default, no "note" field) — the
    caller always knows the exact range it needs (typically the full
    archive date_min/date_max from get_stats(), same pattern
    _sync_health_days()/_sync_context_days() already use), and a
    silent default range here would risk the caller believing a
    broader range was hashed than it actually was.

    Args:
        date_from: Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:   End date ISO string (YYYY-MM-DD), inclusive.

    Returns:
        {"data": {date_str: hash_hex | None, ...}, "error": str | None}
        hash_hex is None for a day whose raw/ file does not exist
        (nothing written yet for that day — not an error). One entry
        per calendar day in the requested range, same "every day
        present, missing data represented as None" principle
        health_map.get()'s "values" list already uses.
    """
    try:
        result: dict[str, str | None] = {}
        current = _parse_iso_date(date_from)
        end = _parse_iso_date(date_to)
        while current <= end:
            day_str = current.isoformat()
            raw_path = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{day_str}.json"
            if raw_path.is_file():
                result[day_str] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            else:
                result[day_str] = None
            current += timedelta(days=1)
        return {"data": result, "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}
