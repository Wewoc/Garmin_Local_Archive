#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
exports/export_common.py

Shared data-collection helper for all export adapters (json_adapter.py,
later csv_adapter.py, influxdb_adapter.py, parquet_adapter.py). Fetches
via the Shared Cache Layer (clients/mcp_sql.py) — v1.7.4 Export Layer
session, "Shared Cache Layer" Baustein: export_runner.build() already
triggers clients/mcp_update.py::sync_all() once per export run before
any adapter's build() (and therefore collect()) is called, so the cache
read here is never more than one run's cache-refresh behind the live
archive. Reading through the cache's per-day payloads also removes the
need for a separate field-enumeration step (gateway_map.list_fields())
— each cached day already carries every field for that domain.

Each adapter calls collect() independently and gets its own copy of the
result — no shared state between adapters (ROADMAP.md: "no shared state
between adapters"). This module exists only to avoid writing the same
cache-read logic once per adapter; it has no format-specific logic and
writes nothing to disk.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Flat import, relying on the caller (GUI / daily_update.py) having
# already added clients/ to sys.path at process startup — same
# assumption export_runner.py's own "import mcp_update" makes.
import mcp_sql

# DIARY v1.7.8.1 — REMOVABLE: the "Diary in data export" switch, read fresh on every collect() (the app and the
# standalone window change the file while the process runs; see garmin_config.read_diary_optin()).
from garmin import garmin_config as _gcfg

# ══════════════════════════════════════════════════════════════════════════════
#  Metadata kinds exposed to external export consumers
#
#  Excludes the three internal-only filename kinds (daily_log_filenames/
#  fail_log_filenames/recent_log_filenames) — metadata_map.py's own
#  docstrings mark those "NOT registered as an MCP tool", used only by
#  clients/mcp_update.py's internal sync bookkeeping. Same exclusion
#  applies one layer further out, for the Export Layer.
# ══════════════════════════════════════════════════════════════════════════════

_EXTERNAL_METADATA_KINDS = [
    "stats", "device_table", "quality_log", "source_api_log",
    "token_log", "capability_config", "daily_logs", "fail_logs",
    "recent_logs",
]


_DOMAIN_RANGE_READERS = {
    "health":  mcp_sql.get_health_range,
    "context": mcp_sql.get_context_range,
    # v1.7.8.1 — DIARY, REMOVABLE: read from the cache like the others, but only while "Diary in data export"
    # is on (collect() leaves the domain out otherwise) and only by adapters that declare META["diary"].
    "diary":   mcp_sql.get_diary_range,
}


def _diary_range(date_from: str, date_to: str) -> tuple[str, str]:
    """The range the diary is read for: the export range, widened to the first and the last cached diary day.
    The export range comes from the Garmin summaries, but a diary day can lie before the first or after the
    last of them (a note for today, before today's sync) and belongs to the archive all the same."""
    days = mcp_sql.get_diary_hashes()
    if not days:
        return date_from, date_to
    return min(date_from, min(days)), max(date_to, max(days))


def collect(date_from: str, date_to: str, domains: list[str],
            include_metadata: bool = False) -> dict:
    """
    Fetch archive data via the Shared Cache Layer (clients/mcp_sql.py)
    for the given domains and date range, optionally including the
    externally-exposed metadata kinds. No format logic — callers
    (adapters) decide how to serialize this.

    Args:
        date_from:        Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:           End date ISO string (YYYY-MM-DD), inclusive.
        domains:           Domain keys to include, e.g. ["health", "context"].
        include_metadata:  If True, also fetch the nine external metadata kinds.

    Returns:
        {
            "date_from": str,
            "date_to":   str,
            "domains": {
                "health":  {"hrv_last_night": {...}, ...},   # mcp_sql.get_health_range()'s
                                                               # "health" value, one level
                                                               # shallower than the old
                                                               # gateway_map shape (no
                                                               # per-source wrapper — see
                                                               # mcp_sql.get_health_range()'s
                                                               # own Bug-C docstring note)
                "context": {"weather": {"temperature_max": {...}, ...}, ...},  # source-major,
                                                               # mcp_sql.get_context_range()'s
                                                               # own grouping
            },
            "metadata": {"quality_log": {...}, ...},  # only if include_metadata,
                                                        # mcp_sql.get_metadata_range()'s
                                                        # envelope per kind
        }

    "fit" (or any future domain not yet backed by a Shared Cache range
    reader) degrades to {"error": "domain not yet available"} under its
    key, same degrade-gracefully principle gateway_map.get() already
    uses — never a hard failure for an unsupported domain.
    """
    result = {
        "date_from": date_from,
        "date_to":   date_to,
        "domains":   {},
    }

    diary_export_on = None
    for domain in domains:
        if domain == "diary":
            if diary_export_on is None:
                diary_export_on = bool(_gcfg.read_diary_optin()[1])
            if not diary_export_on:
                continue     # "Diary in data export" is off: the domain is left out, no entry and no error
        reader = _DOMAIN_RANGE_READERS.get(domain)
        if reader is None:
            result["domains"][domain] = {"error": "domain not yet available"}
            continue
        range_result = reader(*(_diary_range(date_from, date_to) if domain == "diary" else (date_from, date_to)))
        result["domains"][domain] = range_result[domain]

    if include_metadata:
        result["metadata"] = {
            kind: mcp_sql.get_metadata_range(kind, date_from=date_from, date_to=date_to)
            for kind in _EXTERNAL_METADATA_KINDS
        }

    return result
