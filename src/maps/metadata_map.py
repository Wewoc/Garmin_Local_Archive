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
time-series based — there is no field/date_from/date_to/resolution
concept here. Each function answers "what is the current state of X",
not "give me a series of values over a date range". That is why this
broker has its own return shape and its own entry point in
gateway_map.py (get_metadata(), not get()) instead of reusing the
time-series contract.

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

Return structure (all nine functions):
    {
        "data":  <dict | list[str] | None>,
        "error": <str | None>,
    }
"""

import json
import re
from pathlib import Path

from garmin import garmin_config as cfg
from garmin.quality import _stats

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


def _read_log_dir(dir_path: Path) -> list[str]:
    """
    Reads every *.log file in dir_path, sanitizes each line, returns the
    combined, filtered list. Missing directory returns an empty list
    (not an error — a fresh archive may not have this folder yet).
    """
    if not dir_path.is_dir():
        return []
    lines: list[str] = []
    for log_file in sorted(dir_path.glob("*.log")):
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    sanitized = _sanitize_line(raw_line.rstrip("\n"))
                    if sanitized is not None:
                        lines.append(sanitized)
        except OSError:
            # Single unreadable file — skip it, keep collecting the rest.
            continue
    return lines


def _read_json_file(file_path: Path) -> dict:
    """Reads and parses a JSON file. Raises on missing/corrupt file —
    callers are responsible for catching and degrading."""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


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


def get_quality_log() -> dict:
    """Raw content of quality_log.json."""
    try:
        return {"data": _read_json_file(cfg.QUALITY_LOG_FILE), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_source_api_log() -> dict:
    """Raw content of source_api_log.json."""
    try:
        return {"data": _read_json_file(cfg.SOURCE_API_LOG), "error": None}
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


def get_daily_logs() -> dict:
    """Sanitized lines from all *.log files in garmin_data/log/daily/."""
    try:
        return {"data": _read_log_dir(cfg.LOG_DAILY_DIR), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_fail_logs() -> dict:
    """Sanitized lines from all *.log files in garmin_data/log/fail/."""
    try:
        return {"data": _read_log_dir(cfg.LOG_FAIL_DIR), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}


def get_recent_logs() -> dict:
    """Sanitized lines from all *.log files in garmin_data/log/recent/."""
    try:
        return {"data": _read_log_dir(cfg.LOG_RECENT_DIR), "error": None}
    except Exception as exc:
        return {"data": None, "error": str(exc)}
