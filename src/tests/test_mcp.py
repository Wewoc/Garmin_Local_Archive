#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_mcp.py — Garmin Local Archive — MCP Layer Test

Run from the project folder:
    python tests/test_mcp.py

Collecting test for the whole MCP layer (v1.7), not just mcp_map.py —
named test_mcp.py rather than test_mcp_map.py deliberately, so later
sections for clients/mcp_server.py (v1.7) and the SQLite proxy (v1.7.1)
can be added here without the filename becoming misleading. Same
one-file-per-layer principle test_broker.py itself documents relative
to test_dashboard.py — MCP-server-process mocking and SQLite-cache
fixtures are a different concern from broker routing, so this stays
its own file rather than growing test_broker.py into two unrelated
responsibilities.

Section 1-7 below cover mcp_map.py only. No network, no GUI, no
Garmin API calls, no running MCP server — mcp_map.py is a plain Python
module, isolated and testable exactly like gateway_map.py itself (see
test_broker.py).

Does NOT re-verify gateway_map's own routing correctness (fan-out,
degraded results, ValueError on unknown keys) — that is already fully
covered by test_broker.py Section 2. This suite covers only what
mcp_map.py adds on top: correct delegation (same domain key, same
values), the "_meta" weekday-table construction, and that FIT stays on
the clean degraded path without any FIT-specific code.

Fixture setup is a reduced copy of test_broker.py's (only what
health_map/context_map need to exercise real routing through
gateway_map), not an import from it — keeps both test files
independently runnable, same principle test_broker.py itself
documents relative to test_dashboard.py.

Calendar dates used in Section 7 verified against a real calendar:
2026-03-01 is a Sunday, 2026-03-02 is a Monday.
"""

import datetime
import json
import os
import sys
import shutil
import tempfile
import logging
import difflib
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT))
logging.disable(logging.CRITICAL)

# ── Test runner ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from support import check, section, summary

# ── Temp directory as BASE_DIR ─────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_mcp_map_test_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)

import importlib
import garmin_config as cfg
importlib.reload(cfg)

# ── Synthetic raw data (reduced — only what query_health/query_context need) ───

_TEST_DATE = "2026-03-01"

_RAW = {
    "date": _TEST_DATE,
    "heart_rates": {
        "heartRateValues": [
            [1740787200000, 58],
            [1740787260000, 60],
        ]
    },
}

def _write_raw(base_dir: Path):
    raw_dir = base_dir / "garmin_data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f = raw_dir / f"garmin_raw_{_TEST_DATE}.json"
    f.write_text(json.dumps(_RAW), encoding="utf-8")

_write_raw(_TMPDIR)
importlib.reload(cfg)

# v1.7.1.11 — renamed from CONTEXT_WEATHER_DIR (now points at summary/).
_CONTEXT_FIXTURE_DIR = cfg.CONTEXT_WEATHER_SUMMARY_DIR
_CONTEXT_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
(_CONTEXT_FIXTURE_DIR / f"weather_{_TEST_DATE}.json").write_text(
    json.dumps({"date": _TEST_DATE, "fields": {"temperature_2m_max": 25.0}}),
    encoding="utf-8",
)

from maps import mcp_map, gateway_map


# ══════════════════════════════════════════════════════════════════════════════
#  1. query_health() — delegation + _meta
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 1. query_health() — delegation + _meta")

_qh = mcp_map.query_health("heart_rate_series", _TEST_DATE, _TEST_DATE, resolution="intraday")

check("query_health: health key present", "health" in _qh)
check("query_health: _meta key present", "_meta" in _qh)
check("query_health: delegates unchanged to gateway_map",
      _qh["health"] == gateway_map.get(
          "heart_rate_series", _TEST_DATE, _TEST_DATE, "intraday", domain="health"
      )["health"])
check("query_health: does not include context/fit keys",
      "context" not in _qh and "fit" not in _qh)


# ══════════════════════════════════════════════════════════════════════════════
#  2. query_context() — delegation + _meta
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 2. query_context() — delegation + _meta")

_qc = mcp_map.query_context("temperature_max", _TEST_DATE, _TEST_DATE)

check("query_context: context key present", "context" in _qc)
check("query_context: _meta key present", "_meta" in _qc)
check("query_context: delegates unchanged to gateway_map",
      _qc["context"] == gateway_map.get(
          "temperature_max", _TEST_DATE, _TEST_DATE, "daily", domain="context"
      )["context"])


# ══════════════════════════════════════════════════════════════════════════════
#  3. query_fit_activities() — clean degraded path, no FIT-specific code
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 3. query_fit_activities() — degraded path")

_qf = mcp_map.query_fit_activities("some_field", _TEST_DATE, _TEST_DATE)

check("query_fit_activities: fit key present", "fit" in _qf)
check("query_fit_activities: degraded result, domain not yet available",
      _qf["fit"] == {"error": "domain not yet available"})
check("query_fit_activities: _meta still attached even on degraded path",
      "_meta" in _qf)


# ══════════════════════════════════════════════════════════════════════════════
#  4. query_raw() — delegation + _meta
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 4. query_raw() — delegation + _meta")

_qr = mcp_map.query_raw("floors", "2000-01-01", "2000-01-01", domain="health")

check("query_raw: health key present", "health" in _qr)
check("query_raw: _meta key present", "_meta" in _qr)
check("query_raw: delegates unchanged to gateway_map.get_raw()",
      _qr["health"] == gateway_map.get_raw(
          "floors", "2000-01-01", "2000-01-01", domain="health"
      )["health"])

try:
    mcp_map.query_raw("floors", "2000-01-01", "2000-01-01", domain="banana")
    check("query_raw: unknown domain raises ValueError", False)
except ValueError:
    check("query_raw: unknown domain raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  5. get_archive_metadata() — delegation, no _meta block
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 5. get_archive_metadata() — delegation")

_gam = mcp_map.get_archive_metadata("stats")
check("get_archive_metadata: returns data/error envelope",
      isinstance(_gam, dict) and "data" in _gam and "error" in _gam)
check("get_archive_metadata: no _meta block (not date-ranged)",
      "_meta" not in _gam)
check("get_archive_metadata: delegates unchanged to gateway_map",
      _gam == gateway_map.get_metadata("stats"))

try:
    mcp_map.get_archive_metadata("banana")
    check("get_archive_metadata: unknown kind raises ValueError", False)
except ValueError:
    check("get_archive_metadata: unknown kind raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  6. list_available_fields() — overview
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 6. list_available_fields() — overview")

_laf_all = mcp_map.list_available_fields()
check("list_available_fields: domains key present", "domains" in _laf_all)
check("list_available_fields: metadata_kinds key present", "metadata_kinds" in _laf_all)

# v1.7.5.1 Schritt 5 (Fund 2026-10-12): the overview used to advertise all
# registered kinds, including five registered for the SQLite proxy's
# internal sync only — get_archive_metadata() rejects those with a
# ValueError on the SQLite path (the only active one), so an LLM following
# the overview hit an error. The overview now lists the nine LLM-facing
# kinds only; gateway_map.list_metadata_kinds() itself keeps its full
# default (test_broker.py pins that side).
_INTERNAL_KINDS = {
    "daily_log_filenames", "fail_log_filenames", "recent_log_filenames",
    "raw_file_hashes", "context_resync_pending",
}
check("list_available_fields: metadata_kinds omits the internal-sync-only kinds",
      not (set(_laf_all["metadata_kinds"]) & _INTERNAL_KINDS))
check("list_available_fields: metadata_kinds is exactly the nine LLM-facing kinds",
      set(_laf_all["metadata_kinds"]) ==
      set(gateway_map.list_metadata_kinds()) - _INTERNAL_KINDS
      and len(_laf_all["metadata_kinds"]) == len(set(_laf_all["metadata_kinds"])))
check("list_available_fields: fields.health present with garmin source",
      "garmin" in _laf_all["fields"]["health"])
check("list_available_fields: fields.context present with four sources",
      set(_laf_all["fields"]["context"].keys()) ==
      {"weather", "pollen", "brightsky", "airquality"})
check("list_available_fields: fields.fit is empty (not registered)",
      _laf_all["fields"]["fit"] == [])

_laf_health = mcp_map.list_available_fields(domain="health")
check("list_available_fields domain=health: only health key in fields",
      list(_laf_health["fields"].keys()) == ["health"])


# ══════════════════════════════════════════════════════════════════════════════
#  6b. list_*_log_filenames() — v1.7.1, internal sync use only
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 6b. list_*_log_filenames() — delegation, not registered as tools")

# These three exist solely for clients/mcp_update.py's internal sync
# bookkeeping (see metadata_map.py's own docstring) and are deliberately
# NOT registered as MCP tools in clients/mcp_server.py (verified
# separately in Section 8a's exact-seven-tools check) — this section
# only confirms mcp_map.py's own thin-wrapper delegation, same pattern
# as Section 5's get_archive_metadata() coverage above.

check("list_daily_log_filenames: returns data/error envelope",
      isinstance(mcp_map.list_daily_log_filenames(), dict) and
      "data" in mcp_map.list_daily_log_filenames() and
      "error" in mcp_map.list_daily_log_filenames())
check("list_daily_log_filenames: delegates unchanged to gateway_map",
      mcp_map.list_daily_log_filenames() ==
      gateway_map.get_metadata("daily_log_filenames"))
check("list_fail_log_filenames: delegates unchanged to gateway_map",
      mcp_map.list_fail_log_filenames() ==
      gateway_map.get_metadata("fail_log_filenames"))
check("list_recent_log_filenames: delegates unchanged to gateway_map",
      mcp_map.list_recent_log_filenames() ==
      gateway_map.get_metadata("recent_log_filenames"))
check("list_daily_log_filenames: date_from/date_to forwarded",
      mcp_map.list_daily_log_filenames(date_from="2026-06-15", date_to="2026-06-16") ==
      gateway_map.get_metadata("daily_log_filenames", date_from="2026-06-15", date_to="2026-06-16"))


# ══════════════════════════════════════════════════════════════════════════════
#  7. _build_meta() — weekday table correctness
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_map 7. _build_meta() — weekday table correctness")

# 2026-03-01 is a Sunday, 2026-03-02 a Monday — verified against a real
# calendar (dayoftheweek.org / howlongagogo.com, checked 2026-08-23).
_meta = mcp_map._build_meta("2026-03-01", "2026-03-02")

check("_build_meta: date_from_iso correct", _meta["date_from_iso"] == "2026-03-01")
check("_build_meta: date_to_iso correct", _meta["date_to_iso"] == "2026-03-02")
check("_build_meta: date_from_readable is human text",
      _meta["date_from_readable"] == "March 01, 2026")
check("_build_meta: weekdays has one entry per calendar day",
      len(_meta["weekdays"]) == 2)
check("_build_meta: 2026-03-01 weekday correct",
      _meta["weekdays"]["2026-03-01"] == "Sunday")
check("_build_meta: 2026-03-02 weekday correct",
      _meta["weekdays"]["2026-03-02"] == "Monday")

# Single-day range — still produces a one-entry table, not a bare string
_meta_single = mcp_map._build_meta(_TEST_DATE, _TEST_DATE)
check("_build_meta: single-day range → one weekday entry",
      len(_meta_single["weekdays"]) == 1)


# ══════════════════════════════════════════════════════════════════════════════
#  8. clients/mcp_server.py — tool registration + delegation (v1.7 Teilbauauftrag b)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_server 8. clients/mcp_server.py — registration + delegation")

# clients/ is added to sys.path the same way app/panel_chat.py's lazy-import
# helper does it (frozen_paths.add_to_path pattern), but mcp_server.py's own
# sys.path root anchor (Path(__file__).resolve().parent.parent) makes it
# importable directly once "clients" itself is on sys.path — no GUI context
# needed, matching its standalone-subprocess design (NOTES_v1.7_teilb.md).
sys.path.insert(0, str(_ROOT / "clients"))
import mcp_server

# ── 8a. Tool registration — exactly the six expected names, no more/less ──────
#
# FastMCP.list_tools() is a coroutine (mcp.server.fastmcp.FastMCP, v1.x) —
# this is the only asyncio call in this otherwise synchronous test file,
# wrapped in asyncio.run() since there is no running event loop here.
import asyncio

_registered_tools = asyncio.run(mcp_server.mcp.list_tools())
_registered_names = {t.name for t in _registered_tools}

# v1.7.1 — refresh_cache() added as a seventh tool (SQLite proxy manual
# sync trigger). list_daily_log_filenames()/list_fail_log_filenames()/
# list_recent_log_filenames() are deliberately NOT registered here —
# internal sync-only functions, see NOTES_v1.7.1_session2.md.
#
# v1.7.5 Block A — baselines()/anomalies()/gaps() added as three more
# tools (clients/mcp_stats.py), ten total. v1.7.5 Block B — correlate()
# added as an eleventh.
check("mcp_server: exactly eleven tools registered", len(_registered_tools) == 11)
check("mcp_server: registered tool names match mcp_map.py 1:1, plus refresh_cache/baselines/anomalies/gaps/correlate",
      _registered_names == {
          "query_health", "query_context", "query_fit_activities",
          "query_raw", "get_archive_metadata", "list_available_fields",
          "refresh_cache", "baselines", "anomalies", "gaps", "correlate",
      })

# ── 8a-ter. Tool descriptions (v1.7.5.1) ─────────────────────────────────────
#
# What the MCP SDK exposes as each tool's `description` is its docstring,
# and an LLM client picks and calls tools from that text alone. Glama's
# TDQS review (Sep 2026) rated query_context/query_health/query_raw down
# for session-changelog noise and missing usage guidance, so these checks
# pin the cleaned-up state (history lives in #-comment blocks above the
# functions instead). The loop covers every registered tool, so a future
# twelfth tool is checked automatically.
#
# The reference patterns are a heuristic list, not a proof: add a pattern
# here when a new kind of internal reference shows up in a description.
# The 2000-character cap sits above today's longest description (about
# 1400) but well below the pre-cleanup size (about 5000).
import re as _re

_INTERNAL_REF = _re.compile(
    r"NOTES_|KONZEPT_|AKTIONSPLAN|\bv\d+\.\d+\.\d+|\.py\b|\.md\b|this session"
    r"|_route_query|mcp_sql|mcp_map|gateway_map|metadata_map"
)
_tool_desc = {t.name: (t.description or "") for t in _registered_tools}
for _tn in sorted(_tool_desc):
    check(f"description of {_tn}: not empty and at most 2000 characters",
          0 < len(_tool_desc[_tn]) <= 2000)
    check(f"description of {_tn}: no internal references (notes files, versions, module names)",
          _INTERNAL_REF.search(_tool_desc[_tn]) is None)

# query_raw: the field names are not discoverable via list_available_fields,
# so the description is the agent's only source for them — it must name
# exactly the registered raw-passthrough fields. The names are parsed from
# the text between "listed by list_available_fields):" and "date_from/date_to";
# if that wording changes this check goes red on purpose — adjust text and
# pattern together.
_raw_desc = _tool_desc["query_raw"]
_raw_block = _re.search(r"listed by list_available_fields\):(.*?)date_from/date_to",
                        _raw_desc, _re.S)
_raw_named = ({n.strip().rstrip(".") for n in _raw_block.group(1).replace("\n", " ").split(",")}
              if _raw_block else set())
check("description of query_raw: names exactly the registered raw fields",
      _raw_named == set(mcp_map.list_raw_fields("health")["health"]))
check("description of query_raw: does not call the data 'unprocessed' or 'normalized'",
      "unprocessed" not in _raw_desc and "normalized" not in _raw_desc)

# get_archive_metadata: the nine kinds the SQLite path accepts are named in
# quotes; the five internal-sync-only kinds are not.
_meta_desc = _tool_desc["get_archive_metadata"]
_nine_kinds = (mcp_server.mcp_sql._SNAPSHOT_KINDS
               | mcp_server.mcp_sql._STRUCTURED_LOG_KINDS
               | mcp_server.mcp_sql._RECENT_LOG_KINDS)
check("description of get_archive_metadata: names all nine accepted kinds",
      all(f'"{k}"' in _meta_desc for k in _nine_kinds))
check("description of get_archive_metadata: names none of the internal-sync-only kinds",
      not any(k in _meta_desc for k in (
          "daily_log_filenames", "fail_log_filenames", "recent_log_filenames",
          "raw_file_hashes", "context_resync_pending")))

# Usage guidance between sibling tools (the Glama "Usage Guidelines" gap).
check("description of query_health: points to query_context and list_available_fields",
      "query_context" in _tool_desc["query_health"]
      and "list_available_fields" in _tool_desc["query_health"])
check("description of query_context: points to query_health and list_available_fields",
      "query_health" in _tool_desc["query_context"]
      and "list_available_fields" in _tool_desc["query_context"])
check("description of query_raw: points to query_health",
      "query_health" in _raw_desc)

# v1.7.5.5: the counterpart sentence sits outside the parsed field-name block
# (checked above) and must stay in step with RAW_FIELD_COUNTERPARTS — every
# raw field and every processed counterpart in that table is named.
from mcp_field_registry import RAW_FIELD_COUNTERPARTS as _RFC_DESC
_raw_intro = _raw_desc.split("field: one of the raw field names")[0]
check("description of query_raw: names every raw field that has a processed counterpart, before the field list",
      all(_k in _raw_intro for _k in _RFC_DESC))
check("description of query_raw: names every processed counterpart, before the field list",
      all(_c in _raw_intro for _cs in _RFC_DESC.values() for _c in _cs))
check("description of query_raw: counterpart sentence does not disturb the parsed field-name block",
      _raw_block is not None and "floors_climbed" not in _raw_block.group(1))
# v1.7.5.5: an archived day with no stored value comes back as "raw": null
# (mcp_sql.get_raw_fields_for_day keeps None payloads); only a day that is
# not in the archive has no entry. The description used to claim "no entry"
# for both.
check("description of query_raw: says an archived day without a stored value returns \"raw\": null",
      '"raw": null' in _raw_desc and "not in the archive" in _raw_desc)
check("description of query_raw: no longer claims a day with no stored data has no entry",
      "A day with no stored data has no entry" not in _raw_desc)

# ── 8a-bis. unit field (v1.7.1.6) — mcp_server.list_available_fields() ───────
#
# Deliberately calling mcp_server.list_available_fields() here, not
# mcp_map.list_available_fields() (already covered in section 6 above)
# — the "units" key is added in the mcp_server.py wrapper only, per this
# session's scope decision (FIELD_UNITS stays MCP-local, mcp_map.py is
# untouched this session).
_laf_units = mcp_server.list_available_fields()
check("mcp_server.list_available_fields: units key present",
      "units" in _laf_units)
check("mcp_server.list_available_fields: fields key unchanged (additive, not replaced)",
      "garmin" in _laf_units["fields"]["health"])
check("mcp_server.list_available_fields: units covers a known health field",
      _laf_units["units"].get("hrv_last_night") == "ms")
check("mcp_server.list_available_fields: units covers a known context field",
      _laf_units["units"].get("temperature_max") == "°C")

# ── 8b. Routing weiche (v1.7.1.1 Ziel 5) — placeholder always returns "sqlite" ─
#
# _route_query() itself: fixed "sqlite" for every kind, no real heuristic
# yet (see clients/mcp_server.py's own module comment on the weiche for
# the binding rationale). Verified once here per kind rather than
# per-wrapper, since every wrapper's SQLite-branch test below already
# exercises _route_query() indirectly — this section pins down the
# placeholder's own contract independent of any wrapper.
from unittest.mock import patch

for _kind in ("health", "context", "fit", "raw", "metadata", "fields"):
    check(f"_route_query({_kind!r}): placeholder returns 'sqlite'",
          mcp_server._route_query(_kind) == "sqlite")

# ── 8c. Delegation, SQLite branch (current default — _route_query() always
#        returns "sqlite") — each wrapper calls the matching mcp_sql
#        function, NOT mcp_map, when routed to SQLite. This replaces the
#        pre-Ziel-5 assumption that every wrapper always calls mcp_map
#        directly — that assumption broke the moment the weiche was wired
#        in (v1.7.1.1), which is exactly what this suite failed to catch
#        before this rewrite (NOTES_v1.7.1.1_session2.md, Ziel 7 test-gap
#        finding — Maintainer: "ich glaube der ist nur so gut weil wir viel neu
#        gebaut haben aber wenig bestehendes angepasst haben").
#
# The @mcp.tool()-decorated functions in mcp_server.py stay directly callable
# from Python (confirmed against mcp.server.fastmcp.FastMCP, v1.x — unlike
# the unrelated standalone "fastmcp" package's v2/v3 line, which wraps the
# decorated function in a non-callable Tool object). No ".fn" access needed.

with patch("mcp_sql.get_health_range", return_value={"health": {}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_health") as _m_live:
    mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    # v1.7.1.2 field-filter fix: field is now forwarded as a keyword
    # argument (anchor_delivery_1711-04) — this assertion previously
    # expected the pre-fix call shape without field, which the fix
    # correctly broke. See the dedicated 8g-bis regression guard further
    # down in this file for the forwarding behaviour itself; this check
    # stays focused on its original purpose — confirming the SQLite
    # branch, not mcp_map, handles the call — and simply needs to match
    # the call shape that branch now actually produces.
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="hrv_last_night")
    _m_live.assert_not_called()
check("mcp_server.query_health: SQLite branch calls mcp_sql.get_health_range, not mcp_map", True)

# ── 8c-quater. unit field (v1.7.1.6) — query_health() ────────────────────────
#
# Not reusing the empty-dict mock above (nothing to enrich there) — a
# fresh mock with a real field-value shape is needed to verify
# _enrich_with_units() actually attaches "unit" alongside "values"/
# "fallback"/"source_resolution", on the SQLite branch (the only branch
# _route_query() currently ever selects).
_HEALTH_UNIT_MOCK = {"health": {"garmin": {"hrv_last_night": {
    "values": [{"date": _TEST_DATE, "value": 45}],
    "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_HEALTH_UNIT_MOCK):
    _qh_unit = mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unit field: hrv_last_night carries its documented unit",
      _qh_unit["health"]["garmin"]["hrv_last_night"]["unit"] == "ms")

# Field with no physical unit (REFERENCE_BROKER.md: "vo2max | — | ...") —
# verifies the "no exceptions" rule (Session 1 decision): every field
# gets a "unit" key, including ones without a real physical unit.
_HEALTH_UNIT_MOCK_VO2 = {"health": {"garmin": {"vo2max": {
    "values": [{"date": _TEST_DATE, "value": 48}],
    "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_HEALTH_UNIT_MOCK_VO2):
    _qh_unit_vo2 = mcp_server.query_health("vo2max", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unit field: vo2max (no physical unit) still carries a unit key",
      _qh_unit_vo2["health"]["garmin"]["vo2max"]["unit"] == "—")

with patch("mcp_sql.get_context_range", return_value={"context": {}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    # v1.7.1.3 field-filter fix: field is now forwarded as a keyword
    # argument, mirroring query_health's v1.7.1.2 fix above — this
    # assertion previously expected the pre-fix call shape without
    # field, which the fix correctly broke.
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="temperature_max")
    _m_live.assert_not_called()
check("mcp_server.query_context: SQLite branch calls mcp_sql.get_context_range, not mcp_map", True)

# ── 8c-quinquies. unit field (v1.7.1.6) — query_context() direct field ───────
_CONTEXT_UNIT_MOCK = {"context": {"weather": {"temperature_max": {
    "values": [{"date": _TEST_DATE, "value": 21.5}],
    "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_context_range", return_value=_CONTEXT_UNIT_MOCK):
    _qc_unit = mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
check("query_context unit field: temperature_max carries its documented unit",
      _qc_unit["context"]["weather"]["temperature_max"]["unit"] == "°C")

# ── 8c-sexies. has_data signal (v1.7.1.15) — _enrich_with_units() ───────────
#
# A field can be successfully resolved (no error, no ambiguity, no
# domain confusion) but still carry no data for the requested range —
# structurally identical to an in-progress/incomplete response
# ("context": {}) unless explicitly marked. _enrich_with_units() sets
# _meta["has_data"] = False whenever every "values" array it finds is
# empty; it is left unset (not "True") on the ordinary success path,
# matching the existing convention for field_resolved_from/field_used
# (only present when something notable happened).
_HEALTH_EMPTY_MOCK = {"health": {"garmin": {"hrv_last_night": {
    "values": [], "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_HEALTH_EMPTY_MOCK):
    _qh_empty = mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("query_health has_data: empty values array sets _meta.has_data to False",
      _qh_empty.get("_meta", {}).get("has_data") is False)
check("query_health has_data: valid field WITH data has no has_data key",
      "has_data" not in _qh_unit.get("_meta", {}))

_CONTEXT_EMPTY_MOCK = {"context": {"weather": {"temperature_max": {
    "values": [], "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_context_range", return_value=_CONTEXT_EMPTY_MOCK):
    _qc_empty = mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
check("query_context has_data: empty values array sets _meta.has_data to False",
      _qc_empty.get("_meta", {}).get("has_data") is False)
check("query_context has_data: valid field WITH data has no has_data key",
      "has_data" not in _qc_unit.get("_meta", {}))

# Fall A — field resolved but no cache rows at all for the range
# (mcp_sql.get_*_range's own "no cache row" case: "context"/"health" stays
# a completely empty dict, not a field entry with an empty values list).
# Same has_data signal must fire here too — the two shapes are handled by
# the same domain_dict.items() loop in _enrich_with_units().
with patch("mcp_sql.get_context_range", return_value={"context": {}, "_meta": {}}):
    _qc_empty_a = mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
check("query_context has_data: empty context dict (Fall A) also sets has_data to False",
      _qc_empty_a.get("_meta", {}).get("has_data") is False)

# ── 8c-bis-health. query_health() unknown-field detection (v1.7.1.9) ────────
#
# Mirrors Section 8c-bis below for query_context() (v1.7.1.4): an
# unregistered field used to fall through silently to {"health": {}},
# identical to a registered field with no data in range. These checks
# exercise the new validation in mcp_server.py::query_health(), which
# runs BEFORE the _route_query() switch — so it applies regardless of
# which branch (sqlite/live) is active, and none of these calls should
# ever reach mcp_sql or mcp_map.
#
# Confirmed against a real 390-case test run (health_fallback_questions.py,
# 78 questions x 5 local models, before/after comparison 2026-09-05):
# silent wrong answers (empty result + model denies/hallucinates) fell
# from 35.9% to 8.4%, field_correct rose from 26.4% to 33.6%, no
# regressions in previously-correct cases. See REFERENCE_BROKER.md
# v1.7.1.9 entry for the full comparison and the two known, unaddressed
# gaps (short-prefix aliasing, e.g. "steps" vs "steps_series" — see
# v1.7.1.9 Session 2 note there).
#
# Deliberately NOT mocking mcp_map.list_available_fields() here — same
# reasoning as 8c-bis: if a future session renames or removes one of
# the field names used below, THIS is the section that breaks — not
# because the v1.7.1.9 logic itself regressed, but because the fixture
# data drifted out of sync with the real registry. Check the current
# field names in list_available_fields() first before assuming the
# unknown-field detection itself is broken.

section("mcp_server 8c-bis-health. query_health() unknown-field detection (v1.7.1.9)")

_qh_known_fields = set(
    mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
)
check("test fixture: 'hrv_last_night' still a registered health field",
      "hrv_last_night" in _qh_known_fields)

# 1. Unambiguous near-match (typo) -> auto-resolved, transparently marked
#
# Verify the chosen typo's uniqueness against the REAL, full health
# registry before trusting it — same lesson as 8c-bis, where two
# earlier typo candidates each collided with a second real field once
# checked against the full registry rather than a hand-picked subset.
_qh_typo_candidates = difflib.get_close_matches(
    "hrv_last_nigth", _qh_known_fields, n=3, cutoff=0.8
)
check("test fixture: 'hrv_last_nigth' resolves to exactly one health field",
      len(_qh_typo_candidates) == 1 and _qh_typo_candidates[0] == "hrv_last_night")

with patch("mcp_sql.get_health_range", return_value={
    "health": {"hrv_last_night": {
        "values": [{"date": _TEST_DATE, "value": 45}],
        "fallback": False, "source_resolution": "daily",
    }}, "_meta": {},
}) as _m_sql:
    _qh_typo = mcp_server.query_health("hrv_last_nigth", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="hrv_last_night")
check("query_health unknown-field: typo auto-resolves to the intended field", True)
check("query_health unknown-field: _meta.field_resolved_from set to caller's original input",
      _qh_typo.get("_meta", {}).get("field_resolved_from") == "hrv_last_nigth")
check("query_health unknown-field: _meta.field_used set to the resolved field",
      _qh_typo.get("_meta", {}).get("field_used") == "hrv_last_night")

# 2. Domain confusion — field exists, but under query_context, not query_health
with patch("mcp_sql.get_context_range") as _m_sql_ctx, \
     patch("mcp_sql.get_health_range") as _m_sql_health, \
     patch("maps.mcp_map.query_health") as _m_live:
    _qh_domain = mcp_server.query_health("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql_ctx.assert_not_called()
    _m_sql_health.assert_not_called()
    _m_live.assert_not_called()
check("query_health unknown-field: domain-confused field never reaches mcp_sql/mcp_map", True)
check("query_health unknown-field: domain-confused field names query_context in the error",
      "query_context" in _qh_domain.get("error", ""))
check("query_health unknown-field: domain-confused field has no did_you_mean list",
      "did_you_mean" not in _qh_domain)
check("query_health unknown-field: health key stays an empty dict on domain-confusion error",
      _qh_domain.get("health") == {})

# 2b. Bundle name (query_context-only concept) reaching query_health —
#     same domain-confusion outcome as a plain context field above,
#     checked first (before the registry lookup), mirroring
#     query_context()'s own bundle-check-before-unknown-field ordering.
with patch("mcp_sql.get_health_range") as _m_sql_bundle, \
     patch("maps.mcp_map.query_health") as _m_live_bundle:
    _qh_bundle = mcp_server.query_health("weather", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql_bundle.assert_not_called()
    _m_live_bundle.assert_not_called()
check("query_health unknown-field: bundle name never reaches mcp_sql/mcp_map", True)
check("query_health unknown-field: bundle name names query_context in the error",
      "query_context" in _qh_bundle.get("error", ""))
check("query_health unknown-field: bundle name has no did_you_mean list",
      "did_you_mean" not in _qh_bundle)

# 3. No usable near-match at all, and not a query_context field either —
#    generic error, no false suggestion
with patch("mcp_sql.get_health_range") as _m_sql, \
     patch("maps.mcp_map.query_health") as _m_live:
    _qh_unknown = mcp_server.query_health("definitely_unknown_health_field", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
    _m_live.assert_not_called()
check("query_health unknown-field: unrecognized value never reaches mcp_sql/mcp_map", True)
check("query_health unknown-field: unrecognized value yields generic 'unknown field' error",
      "unknown field" in _qh_unknown.get("error", ""))
check("query_health unknown-field: health key stays an empty dict on error",
      _qh_unknown.get("health") == {})

# 3b. steps short-form is ambiguous, not an alias (v1.7.1.17 correction
#     of the v1.7.1.9 Session 2 alias). "steps" was a real, common
#     short-form for "steps_series" when that alias was added — but
#     v1.7.1.16 registered "steps_total" (the daily aggregate) in the
#     same _FIELD_MAP without updating this alias, so "steps" kept
#     silently resolving to steps_series only. Live test run 19
#     (mcp_test/results/lauf_19_20260914_v17116/) surfaced several
#     models answering "Wie viele Schritte bin ich insgesamt gegangen?"
#     with the wrong (steps_series) value. Moved to HEALTH_FIELD_AMBIGUOUS,
#     same shape/mechanism as the pre-existing spo2/stress entries (3d
#     below) — error + did_you_mean with both real candidates, no
#     auto-resolve.
with patch("mcp_sql.get_health_range") as _m_sql_steps, \
     patch("maps.mcp_map.query_health") as _m_live_steps:
    _qh_steps = mcp_server.query_health("steps", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unknown-field: 'steps' is ambiguous, not a generic unknown-field error",
      "ambiguous" in _qh_steps.get("error", ""))
check("query_health unknown-field: 'steps' did_you_mean lists both real candidates",
      _qh_steps.get("did_you_mean") == ["steps_total", "steps_series"])
check("query_health unknown-field: 'steps' never reaches mcp_sql/mcp_map",
      not _m_sql_steps.called and not _m_live_steps.called)
check("query_health unknown-field: 'steps' has no field_used (nothing resolved)",
      "field_used" not in _qh_steps.get("_meta", {}))

# 3b-bis. v1.7.1.16 correction — "steps_total" (the actual registered
#         daily-total field) must NOT be caught by the "steps" ambiguous
#         entry above (different string, HEALTH_FIELD_AMBIGUOUS has no
#         entry for "steps_total") and must resolve directly via
#         _FIELD_MAP, no field_resolved_from/field_used. Regression
#         guard for the live-discovered "steps" naming collision
#         (NOTES_v1_7_1_16.md).
_HEALTH_STEPS_TOTAL_MOCK = {"health": {"garmin": {"steps_total": {
    "values": [{"date": _TEST_DATE, "value": 8500}],
    "fallback": False, "source_resolution": "daily",
}}}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_HEALTH_STEPS_TOTAL_MOCK):
    _qh_steps_total = mcp_server.query_health("steps_total", _TEST_DATE, _TEST_DATE, "daily")
check("query_health 'steps_total': resolves directly, not via the 'steps' alias",
      "field_resolved_from" not in _qh_steps_total.get("_meta", {}))
check("query_health 'steps_total': value present",
      _qh_steps_total["health"]["garmin"]["steps_total"]["values"][0]["value"] == 8500)

# 3c. Remaining alias candidates (hrv, hill) — same mechanism, lighter
#     check (mock target only, not full result shape, since 3b already
#     covers the shared code path in detail).
for _alias_input, _alias_target in [("hrv", "hrv_last_night"), ("hill", "hill_score"),
                                    ("stress_index", "stress_avg")]:
    _alias_mock = {"health": {"garmin": {_alias_target: {
        "values": [{"date": _TEST_DATE, "value": 42}],
        "fallback": False, "source_resolution": "daily",
    }}}, "_meta": {}}
    with patch("mcp_sql.get_health_range", return_value=_alias_mock) as _m_sql_a:
        _qh_a = mcp_server.query_health(_alias_input, _TEST_DATE, _TEST_DATE, "daily")
    check(f"query_health unknown-field: {_alias_input!r} alias resolves to {_alias_target!r}",
          _qh_a.get("_meta", {}).get("field_used") == _alias_target)
    check(f"query_health unknown-field: {_alias_input!r} alias — no error key",
          "error" not in _qh_a)

# 3d. spo2/stress explicitly excluded from alias mapping (v1.7.1.9
#     Session 2 decision for spo2 -- real collision between
#     spo2_avg/spo2_series, see NOTES_v1.7.1.9.md Session 2; stress
#     added v1.7.1.12 after the cutoff=0.65 change was found to
#     silently auto-resolve both -- see HEALTH_FIELD_AMBIGUOUS's own
#     comment in mcp_server.py). Both must land in the new ambiguous-
#     field response (error + did_you_mean with both real candidates),
#     NOT the generic "unknown field" text this test originally
#     expected pre-v1.7.1.12, and NOT an auto-resolved value.
with patch("mcp_sql.get_health_range") as _m_sql_spo2, \
     patch("maps.mcp_map.query_health") as _m_live_spo2:
    _qh_spo2 = mcp_server.query_health("spo2", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unknown-field: 'spo2' is ambiguous, not a generic unknown-field error",
      "ambiguous" in _qh_spo2.get("error", ""))
check("query_health unknown-field: 'spo2' did_you_mean lists both real candidates",
      _qh_spo2.get("did_you_mean") == ["spo2_avg", "spo2_series"])
check("query_health unknown-field: 'spo2' never reaches mcp_sql/mcp_map",
      not _m_sql_spo2.called and not _m_live_spo2.called)
check("query_health unknown-field: 'spo2' has no field_used (nothing resolved)",
      "field_used" not in _qh_spo2.get("_meta", {}))

with patch("mcp_sql.get_health_range") as _m_sql_stress, \
     patch("maps.mcp_map.query_health") as _m_live_stress:
    _qh_stress = mcp_server.query_health("stress", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unknown-field: 'stress' is ambiguous (v1.7.1.12 new case)",
      "ambiguous" in _qh_stress.get("error", ""))
check("query_health unknown-field: 'stress' did_you_mean lists both real candidates",
      _qh_stress.get("did_you_mean") == ["stress_avg", "stress_series"])
check("query_health unknown-field: 'stress' never reaches mcp_sql/mcp_map",
      not _m_sql_stress.called and not _m_live_stress.called)

# 3d-bis. "ozone" ambiguous on the query_context side (v1.7.1.15) — same
#     mechanism as spo2/stress above, but CONTEXT_FIELD_AMBIGUOUS rather
#     than HEALTH_FIELD_AMBIGUOUS. Previously "ozone" itself was in
#     neither the alias nor the ambiguous table (only decorated variants
#     like "ozone_max"/"ozon" were registered aliases), so the bare word
#     fell through to the generic difflib unknown-field path — the
#     inconsistent behaviour this fix resolves.
with patch("mcp_sql.get_context_range") as _m_sql_ozone, \
     patch("maps.mcp_map.query_context") as _m_live_ozone:
    _qc_ozone = mcp_server.query_context("ozone", _TEST_DATE, _TEST_DATE, "daily")
check("query_context unknown-field: 'ozone' is ambiguous (v1.7.1.15 new case)",
      "ambiguous" in _qc_ozone.get("error", ""))
check("query_context unknown-field: 'ozone' did_you_mean lists both real candidates",
      _qc_ozone.get("did_you_mean") == ["airquality_ozone", "airquality_ozone_series"])
check("query_context unknown-field: 'ozone' never reaches mcp_sql/mcp_map",
      not _m_sql_ozone.called and not _m_live_ozone.called)
check("query_context unknown-field: 'ozone' has no field_used (nothing resolved)",
      "field_used" not in _qc_ozone.get("_meta", {}))

# 3e. sleep_score fan-out (v1.7.1.9 Session 2) — bare "sleep_score" is
#     itself already a valid, registered field (unlike the alias
#     candidates above), so it bypasses the unknown-field checks
#     entirely and is resolved by its own dedicated branch, checked
#     even earlier than the alias mapping. Fans out to
#     sleep_score_feedback/sleep_score_qualifier and returns all three
#     in the same {field: {...}} flattened shape _resolve_context_
#     bundle() already produces — matching get_health_range()'s own
#     real return shape (field directly under "health", no "garmin"
#     layer — see mcp_sql.get_health_range()'s docstring: it already
#     reads through that layer itself before returning).
_SLEEP_SCORE_MOCKS = {
    "sleep_score": {"health": {"sleep_score": {
        "values": [{"date": _TEST_DATE, "value": 78}],
        "fallback": False, "source_resolution": "daily",
    }}, "_meta": {"date_from_iso": _TEST_DATE}},
    "sleep_score_feedback": {"health": {"sleep_score_feedback": {
        "values": [{"date": _TEST_DATE, "value": "POSITIVE_DEEP"}],
        "fallback": False, "source_resolution": "daily",
    }}, "_meta": {}},
    "sleep_score_qualifier": {"health": {"sleep_score_qualifier": {
        "values": [{"date": _TEST_DATE, "value": "FAIR"}],
        "fallback": False, "source_resolution": "daily",
    }}, "_meta": {}},
}

def _sleep_score_side_effect(date_from, date_to, field=None):
    return _SLEEP_SCORE_MOCKS[field]

with patch("mcp_sql.get_health_range", side_effect=_sleep_score_side_effect) as _m_sql_ss:
    _qh_ss = mcp_server.query_health("sleep_score", _TEST_DATE, _TEST_DATE, "daily")
check("sleep_score fan-out: all three fields present in result",
      set(_qh_ss.get("health", {}).keys()) ==
      {"sleep_score", "sleep_score_feedback", "sleep_score_qualifier"})
check("sleep_score fan-out: three separate calls made (one per field)",
      _m_sql_ss.call_count == 3)
check("sleep_score fan-out: _meta.field_resolved_from set to 'sleep_score'",
      _qh_ss.get("_meta", {}).get("field_resolved_from") == "sleep_score")
check("sleep_score fan-out: no field_used key (all three names already visible as dict keys)",
      "field_used" not in _qh_ss.get("_meta", {}))
check("sleep_score fan-out: sleep_score value correct",
      _qh_ss["health"]["sleep_score"]["values"][0]["value"] == 78)
check("sleep_score fan-out: sleep_score_feedback value correct",
      _qh_ss["health"]["sleep_score_feedback"]["values"][0]["value"] == "POSITIVE_DEEP")
check("sleep_score fan-out: sleep_score_qualifier value correct",
      _qh_ss["health"]["sleep_score_qualifier"]["values"][0]["value"] == "FAIR")

# 3f. Targeted feedback/qualifier calls unaffected — only the bare
#     "sleep_score" triggers fan-out, a direct call to either companion
#     field must return exactly that one field, unchanged from
#     pre-Session-2 behavior.
_SLEEP_FEEDBACK_ONLY_MOCK = {"health": {"sleep_score_feedback": {
    "values": [{"date": _TEST_DATE, "value": "POSITIVE_DEEP"}],
    "fallback": False, "source_resolution": "daily",
}}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_SLEEP_FEEDBACK_ONLY_MOCK) as _m_sql_fb:
    _qh_fb = mcp_server.query_health("sleep_score_feedback", _TEST_DATE, _TEST_DATE, "daily")
check("sleep_score_feedback targeted call: only one field in result, no fan-out",
      set(_qh_fb.get("health", {}).keys()) == {"sleep_score_feedback"})
check("sleep_score_feedback targeted call: single mcp_sql call, not three",
      _m_sql_fb.call_count == 1)
check("sleep_score_feedback targeted call: no field_resolved_from (not a fan-out or alias hit)",
      "field_resolved_from" not in _qh_fb.get("_meta", {}))

# 4. Success-path byte-identity guard — a VALID field must show none of the
#    new v1.7.1.9 keys (error/did_you_mean/_meta.field_resolved_from), so
#    a future change to the unknown-field branch cannot silently leak into
#    the existing, already-covered success path.
with patch("mcp_sql.get_health_range", return_value={
    "health": {"hrv_last_night": {
        "values": [{"date": _TEST_DATE, "value": 45}],
        "fallback": False, "source_resolution": "daily",
    }}, "_meta": {},
}):
    _qh_valid = mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("query_health unknown-field: valid field has no 'error' key",
      "error" not in _qh_valid)
check("query_health unknown-field: valid field has no 'did_you_mean' key",
      "did_you_mean" not in _qh_valid)
check("query_health unknown-field: valid field has no 'field_resolved_from' in _meta",
      "field_resolved_from" not in _qh_valid.get("_meta", {}))


# ── 8c-bis. query_context() unknown-field detection (v1.7.1.4) ──────────────
#
# Regression guard for the v1.7.1.4 fix: an unregistered field used to
# fall through silently to {"context": {}}, identical to a registered
# field with no data in range. These checks exercise the new validation
# in mcp_server.py::query_context(), which runs BEFORE the _route_query()
# switch — so it applies regardless of which branch (sqlite/live) is
# active, and none of these calls should ever reach mcp_sql or mcp_map.
#
# Deliberately NOT mocking mcp_map.list_available_fields() here — these
# checks run against the real, live context/health field registries.
# That means: if a future session renames or removes one of the four
# field names used below (temperature_max/temperature_min plus a typo'd
# variant, or "sleep" moving out of health_map's registry), THIS is the
# section that breaks — not because the v1.7.1.4 logic itself regressed,
# but because the fixture data drifted out of sync with the real
# registry. Check the current field names in list_available_fields()
# first before assuming the unknown-field detection itself is broken.

_qc_known_fields = set()
for _src_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
    _qc_known_fields.update(_src_fields)
check("test fixture: 'temperature_max' still a registered context field",
      "temperature_max" in _qc_known_fields)

# 1. Unambiguous near-match (typo) -> auto-resolved, transparently marked
#
# v1.7.1.12 -- "sunshine_duratio" (the original candidate, chosen under
# cutoff=0.8) stopped being unique once cutoff was lowered to 0.65
# (v1.7.1.11 Session 5, deliberate/confirmed): at 0.65 it now matches
# THREE candidates (sunshine_duration, sunshine_sum, sunshine_sum_series)
# instead of one, so the len(close_matches) == 1 auto-resolve branch no
# longer fires for it -- not a regression in the unknown-field logic
# itself, the fixture just predates the cutoff change. Replaced with
# "condiiton" (missing second "i"), re-verified unique at cutoff=0.65
# against the full, current field registry (see FIELD_UNITS in
# mcp_server.py / REFERENCE_BROKER.md): "condition" is the only string
# field in the entire context registry, so it has no _avg/_max/_sum
# sibling that could collide with it the way sunshine_duration now
# collides with sunshine_sum/sunshine_sum_series.
with patch("mcp_sql.get_context_range", return_value={"context": {"weather": {}}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    _qc_typo = mcp_server.query_context("condiiton", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="condition")
    _m_live.assert_not_called()
check("query_context unknown-field: typo auto-resolved to registered field", True)
check("query_context unknown-field: _meta.field_resolved_from set to caller's original input",
      _qc_typo.get("_meta", {}).get("field_resolved_from") == "condiiton")
check("query_context unknown-field: _meta.field_used set to the resolved field",
      _qc_typo.get("_meta", {}).get("field_used") == "condition")

# 2. Domain confusion — field exists, but under query_health, not query_context
#
# "sleep" (the category name an LLM sent in the real MCP-LLM test run
# that originally surfaced this whole gap, question 14) turned out to
# NOT be a registered field itself — garmin_health_map.py only
# registers "sleep_duration", "sleep_score", "sleep_deep_pct", etc.,
# never the bare word "sleep". Using "sleep" here made this check land
# in the generic unknown-field branch instead of the domain-confusion
# branch it is meant to exercise — caught by this check failing during
# the v1.7.1.4 session. "sleep_duration" is a real, currently
# registered health/garmin field with no counterpart anywhere in the
# context registry, so it is unambiguous domain confusion.
with patch("mcp_sql.get_context_range") as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    _qc_domain = mcp_server.query_context("sleep_duration", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
    _m_live.assert_not_called()
check("query_context unknown-field: domain-confused field never reaches mcp_sql/mcp_map", True)
check("query_context unknown-field: domain-confused field names query_health in the error",
      "query_health" in _qc_domain.get("error", ""))
check("query_context unknown-field: domain-confused field has no did_you_mean list",
      "did_you_mean" not in _qc_domain)

# 3. No usable near-match at all — generic error, no false suggestion
#
# v1.7.1.5 note: "weather" USED to be this test's example (a category
# name with no near-match under the pre-v1.7.1.5 field-only registry).
# It no longer fits here -- "weather" is now a registered bundle name
# (_CONTEXT_CATEGORY_BUNDLES), so mcp_server.query_context("weather", ...)
# deliberately DOES reach mcp_sql/mcp_map now (see Section 8c-ter below,
# where that new behaviour is the thing under test). This check keeps
# its original purpose -- a string that is neither a field, a bundle
# name, nor a near-match to either -- using a value with no realistic
# resemblance to anything in the registry.
with patch("mcp_sql.get_context_range") as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    _qc_category = mcp_server.query_context("definitely_unknown_category", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
    _m_live.assert_not_called()
check("query_context unknown-field: unrecognized value never reaches mcp_sql/mcp_map", True)
check("query_context unknown-field: unrecognized value yields generic 'unknown field' error",
      "unknown field" in _qc_category.get("error", ""))
check("query_context unknown-field: context key stays an empty dict on error",
      _qc_category.get("context") == {})

# 4. Success-path byte-identity guard — a VALID field must show none of the
#    new v1.7.1.4 keys (error/did_you_mean/_meta.field_resolved_from), so
#    a future change to the unknown-field branch cannot silently leak into
#    the existing, already-covered success path above.
with patch("mcp_sql.get_context_range", return_value={"context": {"weather": {}}, "_meta": {}}):
    _qc_valid = mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
check("query_context unknown-field: valid field has no 'error' key",
      "error" not in _qc_valid)
check("query_context unknown-field: valid field has no 'did_you_mean' key",
      "did_you_mean" not in _qc_valid)
check("query_context unknown-field: valid field has no 'field_resolved_from' in _meta",
      "field_resolved_from" not in _qc_valid.get("_meta", {}))

with patch("mcp_sql.get_raw_range", return_value={"health": {}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_raw") as _m_live:
    mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain="health")
    _m_sql.assert_called_once_with("2000-01-01", "2000-01-01", field="floors")
    _m_live.assert_not_called()
check("mcp_server.query_raw: SQLite branch calls mcp_sql.get_raw_range (field forwarded), not mcp_map", True)

# v1.7.5.2: query_raw() now resolves `field` (shared _match_field), forwards
# it to get_raw_range(), and rejects a domain other than "health". Replaces
# the v1.7.5.1 Ist-Stand check that pinned "field/domain are ignored".
_qr_real_fields = set(mcp_map.list_raw_fields("health")["health"])
_qr_ok = {"health": {"floors": {"values": [{"date": "2000-01-01", "raw": [1]}],
                                "source_resolution": "raw"}}, "_meta": {}}


def _qr_fresh(*_args, **_kwargs):
    import copy
    return copy.deepcopy(_qr_ok)  # query_raw() writes into _meta; no shared state between checks


with patch("mcp_sql.get_raw_range", side_effect=_qr_fresh) as _m_sql:
    _qr_exact = mcp_server.query_raw("floors", "2000-01-01", "2000-01-01")
    _qr_exact_call = _m_sql.call_args
check("query_raw: exact field forwarded to get_raw_range as field='floors'",
      _qr_exact_call.kwargs.get("field") == "floors")
check("query_raw: exact field -> no field_resolved_from marker in _meta",
      "field_resolved_from" not in _qr_exact["_meta"])

_qr_typo_matches = difflib.get_close_matches("floor", _qr_real_fields, n=3, cutoff=0.65)
check("test fixture: 'floor' near-matches exactly one real raw field ('floors')",
      _qr_typo_matches == ["floors"])
with patch("mcp_sql.get_raw_range", side_effect=_qr_fresh) as _m_sql:
    _qr_typo = mcp_server.query_raw("floor", "2000-01-01", "2000-01-01")
    _qr_typo_call = _m_sql.call_args
check("query_raw: near-match 'floor' auto-resolved, get_raw_range called with 'floors'",
      _qr_typo_call.kwargs.get("field") == "floors")
check("query_raw: near-match marked in _meta (field_resolved_from/field_used)",
      _qr_typo["_meta"].get("field_resolved_from") == "floor"
      and _qr_typo["_meta"].get("field_used") == "floors")

with patch("mcp_sql.get_raw_range", side_effect=_qr_fresh) as _m_sql:
    _qr_upper = mcp_server.query_raw("FLOORS", "2000-01-01", "2000-01-01")
    _qr_upper_call = _m_sql.call_args
check("query_raw: 'FLOORS' (case only) resolved to 'floors' and marked",
      _qr_upper_call.kwargs.get("field") == "floors"
      and _qr_upper["_meta"].get("field_resolved_from") == "FLOORS")

with patch("mcp_sql.get_raw_range") as _m_sql:
    _qr_unknown = mcp_server.query_raw("zzzzzz", "2000-01-01", "2000-01-01")
    _qr_unknown_called = _m_sql.called
check("query_raw: unknown field -> error dict, nothing queried",
      "error" in _qr_unknown and _qr_unknown["health"] == {} and not _qr_unknown_called)
check("query_raw: unknown field without near-match -> no did_you_mean",
      "did_you_mean" not in _qr_unknown)

with patch("mcp_sql.get_raw_range") as _m_sql:
    _qr_multi = mcp_server.query_raw("nutrition_daily", "2000-01-01", "2000-01-01")
    _qr_multi_called = _m_sql.called
check("query_raw: several near-matches -> error + did_you_mean (real raw fields only), nothing queried",
      "error" in _qr_multi and not _qr_multi_called
      and len(_qr_multi.get("did_you_mean", [])) >= 2
      and set(_qr_multi["did_you_mean"]) <= _qr_real_fields)

for _qr_bad_domain in ("context", "fit", "nonsense"):
    with patch("mcp_sql.get_raw_range") as _m_sql:
        _qr_dom = mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain=_qr_bad_domain)
        _qr_dom_called = _m_sql.called
    check(f"query_raw: domain={_qr_bad_domain!r} -> error dict, nothing queried",
          "error" in _qr_dom and _qr_dom["health"] == {} and not _qr_dom_called)

for _qr_good_domain in (None, "health", "Health"):
    with patch("mcp_sql.get_raw_range", side_effect=_qr_fresh) as _m_sql:
        _qr_dom_ok = mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain=_qr_good_domain)
    check(f"query_raw: domain={_qr_good_domain!r} accepted, data returned",
          "error" not in _qr_dom_ok and "floors" in _qr_dom_ok["health"])

with patch("mcp_sql.get_metadata_range", return_value={"data": {}, "error": None}) as _m_sql, \
     patch("maps.mcp_map.get_archive_metadata") as _m_live:
    mcp_server.get_archive_metadata("stats")
    _m_sql.assert_called_once_with("stats", date_from=None, date_to=None)
    _m_live.assert_not_called()
check("mcp_server.get_archive_metadata: SQLite branch calls mcp_sql.get_metadata_range, not mcp_map", True)

with patch("mcp_sql.get_metadata_range", return_value={"data": [], "error": None}) as _m_sql, \
     patch("maps.mcp_map.get_archive_metadata") as _m_live:
    mcp_server.get_archive_metadata("quality_log", date_from="2026-06-01", date_to="2026-06-30")
    _m_sql.assert_called_once_with("quality_log", date_from="2026-06-01", date_to="2026-06-30")
    _m_live.assert_not_called()
check("mcp_server.get_archive_metadata: SQLite branch forwards explicit date_from/date_to", True)

# v1.7.5.1 Schritt 5: every kind the overview advertises must be one the
# SQLite path (the only active one) actually accepts — no ValueError.
#   Compared against mcp_sql's own kind sets (what get_metadata_range()
#   dispatches on) instead of calling it, so no SQLite access is needed.
_sqlite_accepted = (mcp_server.mcp_sql._SNAPSHOT_KINDS
                    | mcp_server.mcp_sql._STRUCTURED_LOG_KINDS
                    | mcp_server.mcp_sql._RECENT_LOG_KINDS)
check("list_available_fields: every advertised metadata kind is accepted by the SQLite path",
      set(mcp_map.list_available_fields()["metadata_kinds"]) == _sqlite_accepted)

# ── 8d. Delegation, live branch — forcing _route_query() to "live" must
#        route every wrapper to mcp_map instead, with mcp_sql untouched.
#        This is the branch the placeholder never actually returns today,
#        but the weiche's whole purpose (per the module comment) is that
#        a future real heuristic only changes _route_query()'s body, never
#        any call site — this section is what proves that promise holds
#        structurally, not just in the comment.

with patch("mcp_health._route_query", return_value="live"), \
     patch("maps.mcp_map.query_health", return_value={"health": {}, "_meta": {}}) as _m_live, \
     patch("mcp_sql.get_health_range") as _m_sql:
    mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m_live.assert_called_once_with("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
check("mcp_server.query_health: live branch calls mcp_map.query_health, not mcp_sql", True)

with patch("mcp_context._route_query", return_value="live"), \
     patch("maps.mcp_map.query_context", return_value={"context": {}, "_meta": {}}) as _m_live, \
     patch("mcp_sql.get_context_range") as _m_sql:
    mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m_live.assert_called_once_with("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
check("mcp_server.query_context: live branch calls mcp_map.query_context, not mcp_sql", True)

# ── 8d-bis. query_context() "_series" fields — SQLite-Rueckbau (v1.7.1.11
#            Session 4) ──────────────────────────────────────────────────
#
# Session 3 gave "_series" fields a hardcoded live-only bypass in
# query_context() (two spots: direct field path, typo-resolution path),
# reasoning that they were excluded from the proactive SQLite sync and
# would silently return empty from mcp_sql. Session 4 established (maintainer,
# NOTES_v1.7.1.11.md Session 4) that ALL context data — daily and
# "_series" alike — must flow through the same sqlite/live routing
# weiche as every other field, same as query_health()'s steps_series
# already does. This section is the missing coverage for that specific
# behaviour: Session 3 never added a dedicated test for its own
# "_series" bypass (the only two "_series"-suffix checks in this file,
# in Section 8c-ter below, exercise _resolve_context_bundle()'s
# separate and unrelated bundle-collision skip, not this path) — so
# there was nothing here to break when the bypass was removed, and
# nothing here to prove the removal actually took effect either. These
# checks close that gap.
#
# Deliberately NOT mocking mcp_map.list_available_fields() here — same
# reasoning as 8c-bis: pulls a real "_series" field name from the live
# registry, so a future rename/removal breaks THIS section for that
# reason, not silently drifts out of sync.

section("mcp_server 8d-bis. query_context() \"_series\" fields — SQLite-Rueckbau (v1.7.1.11 S4)")

_qc_series_fields = set()
for _src_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
    _qc_series_fields.update(f for f in _src_fields if f.endswith("_series"))
check("test fixture: at least one '_series' context field is registered",
      len(_qc_series_fields) > 0)
_a_series_field = sorted(_qc_series_fields)[0] if _qc_series_fields else None

# 1. Happy path — direct field path, SQLite branch (today's placeholder
#    default): a "_series" field must now call mcp_sql.get_context_range,
#    exactly like any daily field already does.
if _a_series_field is not None:
    with patch("mcp_sql.get_context_range",
               return_value={"context": {"weather": {}}, "_meta": {}}) as _m_sql, \
         patch("maps.mcp_map.query_context") as _m_live:
        mcp_server.query_context(_a_series_field, _TEST_DATE, _TEST_DATE, "intraday")
        _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field=_a_series_field)
    check("query_context '_series' direct field: SQLite branch calls mcp_sql.get_context_range",
          True)
    # 4. Regression guard — must NOT fall back to the old live-only bypass.
    check("query_context '_series' direct field: SQLite branch never touches mcp_map.query_context",
          not _m_live.called)

# 2. Live branch — forcing _route_query() to "live" must route a
#    "_series" field to mcp_map exactly like a daily field (8d above),
#    proving the weiche now applies uniformly, no field-name branching
#    left in front of it.
if _a_series_field is not None:
    with patch("mcp_context._route_query", return_value="live"), \
         patch("maps.mcp_map.query_context",
               return_value={"context": {}, "_meta": {}}) as _m_live, \
         patch("mcp_sql.get_context_range") as _m_sql:
        mcp_server.query_context(_a_series_field, _TEST_DATE, _TEST_DATE, "intraday")
        _m_live.assert_called_once_with(_a_series_field, _TEST_DATE, _TEST_DATE, "intraday")
        _m_sql.assert_not_called()
    check("query_context '_series' direct field: live branch calls mcp_map.query_context, not mcp_sql",
          True)

# 3. Typo resolution landing on a "_series" field — the second removed
#    bypass. A close-match typo of a real "_series" field name must now
#    also reach the SQLite branch (placeholder default), not be forced
#    live.
#
# Correction (Session 4, post-Anchor-3 diagnosis, debug_series_typo.py
# run): the original approach here derived the typo by dropping a
# character INSIDE "_series" itself (e.g. "_series" -> "_seris") from
# whichever field sorted(_qc_series_fields)[0] happened to pick. Every
# "_series" field in this registry has a same-named daily counterpart
# minus the suffix (X / X_series) — a typo landing inside "_series"
# leaves the X-prefix almost untouched, so difflib often rates BOTH "X"
# and "X_series" above cutoff=0.8 for that typo (confirmed for the
# then-picked "airquality_european_aqi_series": ratio 0.9831 against
# itself, 0.8846 against "airquality_european_aqi" — both clear
# cutoff=0.8), failing the "exactly one candidate" assumption. Not a
# registry problem, an artifact of where the typo lands. Fixed two ways
# (maintainer, Session 4): a real, pre-verified single-candidate case (this
# check) placing the typo INSIDE the prefix instead, plus a separate
# check (3b, below) that keeps the original collision case as
# documented, expected behaviour rather than discarding it.
#
# "pollen_birch_series" hardcoded rather than derived from
# sorted(_qc_series_fields) for the same reason 8c-bis hardcodes
# "sunshine_duratio": a stable, pre-verified typo, not a runtime pick
# that can land on an unrelated field with different collision
# behaviour on a future registry change.
#
# v1.7.1.12 -- REFRAMED from "resolves to exactly one candidate" to a
# second documented collision case (same shape as 3b below). At
# cutoff=0.65 (current production value, v1.7.1.11 Session 5) this typo
# no longer matches uniquely -- a systematic check of all 19 registered
# "_series" fields found NONE stay unique under this "drop one prefix-
# internal underscore" typo pattern at 0.65; most collide with their own
# daily counterpart (e.g. "pollenbirch_series" now also matches
# "pollen_olive_series"/"pollen_grass_series" alongside the intended
# "pollen_birch_series"). This is a structural property of cutoff=0.65
# against the X/X_series naming scheme, not a fluke of this one field --
# no replacement typo that still resolves uniquely exists in the current
# registry (verified against a second typo pattern too, same result).
# See NOTES_v1.7.1.12.md "Ziel 6" for the full analysis. Deliberately
# NOT fixed via a new alias or a cutoff change this session (maintainer) --
# this test now documents the collision as expected behaviour, same
# principle as 3b's pre-existing "_series"-internal-typo case.
_series_typo_field = "pollen_birch_series"
if _series_typo_field in _qc_series_fields:
    _series_typo = "pollenbirch_series"  # missing "_" between prefix and "birch"
    _all_known_context_fields = set()
    for _src_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        _all_known_context_fields.update(_src_fields)
    _typo_matches = difflib.get_close_matches(
        _series_typo, _all_known_context_fields, n=3, cutoff=0.65
    )
    check("test fixture: '_series' typo (mid-prefix) is a documented "
          "collision at cutoff=0.65 (>=2 candidates, no auto-resolution)",
          len(_typo_matches) >= 2 and _series_typo_field in _typo_matches)

# 3b. Documented collision case — a typo placed INSIDE "_series" itself
#     (e.g. "_series" -> "_seris", the pattern that motivated the
#     correction above) legitimately matches BOTH a "_series" field and
#     its daily counterpart for names with a short "_series"-relative
#     prefix (e.g. "airquality_european_aqi_series"). This is not a bug
#     in the rollback — same "no unique match, fall through" behaviour
#     8c-bis's own "definitely_unknown_category" case exercises for a
#     different reason — but it IS a real, reproducible property of this
#     field naming convention worth keeping a check on, so a future
#     session changing the alias/typo-resolution cutoff notices if it
#     starts silently picking one of the two candidates instead of
#     correctly falling through to ambiguous/unresolved.
_collision_field = "airquality_european_aqi_series"
if _collision_field in _qc_series_fields:
    _collision_typo = "airquality_european_aqi_seris"  # missing "e" in "_series"
    _all_known_context_fields = set()
    for _src_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        _all_known_context_fields.update(_src_fields)
    _collision_matches = difflib.get_close_matches(
        _collision_typo, _all_known_context_fields, n=3, cutoff=0.8
    )
    check("test fixture: '_series'-suffix typo on a short-prefix field stays a documented "
          "X/X_series collision (>=2 candidates, no auto-resolution)",
          len(_collision_matches) >= 2
          and _collision_field in _collision_matches)

# 5. Regression guard for 8c-bis's own typo test — the pre-existing
#    NON-"_series" typo path must stay on the SQLite branch. v1.7.1.12:
#    "sunshine_duratio" replaced with "condiiton" -> "condition" for the
#    same reason as the first occurrence above (cutoff=0.65 makes
#    "sunshine_duratio" match 3 candidates instead of 1) -- nothing in
#    this rollback should affect a plain field's typo resolution.
with patch("mcp_sql.get_context_range",
           return_value={"context": {"weather": {}}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    mcp_server.query_context("condiiton", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="condition")
    _m_live.assert_not_called()
check("query_context non-'_series' typo path: unaffected by the '_series' rollback (regression guard)",
      True)

# ── 8c-ter. query_context() category bundles (v1.7.1.5) ─────────────────────
#
# _CONTEXT_CATEGORY_BUNDLES resolution runs BEFORE the v1.7.1.4
# unknown-field check above (a bundle name is never itself a registered
# field, see mcp_server.py module comment) and BEFORE the _route_query()
# switch, but each bundle field still goes through that same switch --
# these checks stay on the SQLite branch (the placeholder's current
# default, per 8b) to match the rest of this section's style, and mock
# mcp_sql.get_context_range per bundle field rather than hitting real
# files, same style as 8c-bis above. list_available_fields() itself is
# NOT mocked (same reasoning as 8c-bis: if a future session renames a
# field, this section should fail for that reason, not silently drift).

section("mcp_server 8c-ter. query_context() category bundles (v1.7.1.5)")

# 1. "pollen" — single-source bundle, no collision possible. Confirms a
#    bundle with only one source in its priority list still flattens
#    correctly and never adds "_meta.field_sources" entries (nothing to
#    attribute — see _resolve_context_bundle()'s docstring).
_pollen_fields = mcp_map.list_available_fields(domain="context")["fields"]["context"]["pollen"]

# v1.7.1.11 — pollen's field registry now also contains "_series" (intraday)
# entries (Anchor 4.1), but _resolve_context_bundle() deliberately skips
# them (Anchor 6.1) — the bundle mechanism answers a daily-value source-
# collision question that has no intraday equivalent among these sources.
# _pollen_fields therefore no longer equals the set of fields actually
# queried/flattened here; _pollen_daily_fields does.
_pollen_daily_fields = [f for f in _pollen_fields if not f.endswith("_series")]
check("test fixture: pollen registry contains _series entries (sanity check)",
      len(_pollen_fields) > len(_pollen_daily_fields))

def _fake_pollen_range(date_from, date_to, field=None):
    return {"context": {"pollen": {field: {
        "values": [{"date": _TEST_DATE, "value": 12.5}],
        "fallback": False, "source_resolution": "daily",
    }}}, "_meta": {"weekday_table": {}}}

with patch("mcp_sql.get_context_range", side_effect=_fake_pollen_range) as _m_sql:
    _qc_pollen = mcp_server.query_context("pollen", _TEST_DATE, _TEST_DATE, "daily")
    check("query_context bundle 'pollen': mcp_sql called once per registered daily field, _series skipped",
          _m_sql.call_count == len(_pollen_daily_fields))
check("query_context bundle 'pollen': every daily field present in flat result",
      set(_qc_pollen["context"].keys()) == set(_pollen_daily_fields))
check("query_context bundle 'pollen': no _series field leaked into flat result",
      not any(f.endswith("_series") for f in _qc_pollen["context"]))
check("query_context bundle 'pollen': a field's value is unwrapped correctly",
      _qc_pollen["context"]["pollen_birch"]["values"][0]["value"] == 12.5)
check("query_context bundle 'pollen': no field_sources entries (single-source bundle)",
      _qc_pollen["_meta"]["field_sources"] == {})
check("query_context bundle 'pollen': unit field (v1.7.1.6) — flattened field carries its unit",
      _qc_pollen["context"]["pollen_birch"]["unit"] == "grains/m³")

# 2. "weather" — the real, documented collision. Both "weather" and
#    "brightsky" register "wind_speed_max" (see context_map.py
#    docstring / KONZEPT_query_context_kategorie_aufloesung.md). Priority
#    list is ["brightsky", "weather"] (Messstation vor Modell) — a day
#    with data from both sources must show brightsky's value; a day
#    where brightsky has none must fall back to weather's value for
#    that SAME day (per-day tie-break, not whole-field).

_DAY_1, _DAY_2 = "2026-03-01", "2026-03-02"

def _fake_weather_bundle_range(date_from, date_to, field=None):
    if field == "wind_speed_max":
        return {"context": {"weather": {"wind_speed_max": {
            "values": [{"date": _DAY_1, "value": 18.5},
                       {"date": _DAY_2, "value": 21.0}],
            "fallback": False, "source_resolution": "daily",
        }}}, "_meta": {}}
    # every other weather-only field: arbitrary distinct value, present
    # both days, no collision partner
    return {"context": {"weather": {field: {
        "values": [{"date": _DAY_1, "value": 1.0},
                   {"date": _DAY_2, "value": 2.0}],
        "fallback": False, "source_resolution": "daily",
    }}}, "_meta": {}}

def _fake_brightsky_bundle_range(date_from, date_to, field=None):
    if field == "wind_speed_max":
        # Day 1: brightsky has data (should win). Day 2: brightsky has
        # no data for this field (value None) — weather must win instead.
        return {"context": {"brightsky": {"wind_speed_max": {
            "values": [{"date": _DAY_1, "value": 22.0},
                       {"date": _DAY_2, "value": None}],
            "fallback": False, "source_resolution": "daily",
        }}}, "_meta": {}}
    return {"context": {"brightsky": {field: {
        "values": [{"date": _DAY_1, "value": 3.0},
                   {"date": _DAY_2, "value": 4.0}],
        "fallback": False, "source_resolution": "daily",
    }}}, "_meta": {}}

def _fake_weather_bundle_dispatch(date_from, date_to, field=None):
    # _resolve_context_bundle() queries per (source, field) via the same
    # mcp_sql.get_context_range() entry point for every source in the
    # bundle -- but that function signature carries no "source" argument
    # (matches the real mcp_sql.get_context_range() contract), so for a
    # colliding field name ("wind_speed_max", present in BOTH sources)
    # the mock cannot tell which source is being queried from "field"
    # alone -- both calls arrive with the identical field name. Dispatch
    # therefore follows _CONTEXT_CATEGORY_BUNDLES["weather"]'s own fixed
    # iteration order (["brightsky", "weather"]) instead: for any field
    # name that exists in both sources, the FIRST call reaching this mock
    # is brightsky's (bundle iterates brightsky before weather), the
    # SECOND is weather's. Fields unique to one source need no counting
    # -- they only ever come from that source.
    #
    # v1.7.1.5 correction (this anchor): the earlier version of this mock
    # dispatched purely on "is field in brightsky's field list" — wrong
    # for "wind_speed_max", which is in BOTH lists, so both the
    # weather-side and brightsky-side call were misrouted to the
    # brightsky fake, and the production code's weather-side lookup
    # under result["context"]["weather"]["wind_speed_max"] then found
    # nothing, silently dropping "weather" as a candidate source and
    # making the day-2 fallback check fail. Root cause was in this mock,
    # not in _resolve_context_bundle() itself — verified by reproducing
    # the real collection loop locally against both mock versions.
    _brightsky_only = set(mcp_map.list_available_fields(
        domain="context")["fields"]["context"]["brightsky"]) - {"wind_speed_max"}
    _weather_only = set(mcp_map.list_available_fields(
        domain="context")["fields"]["context"]["weather"]) - {"wind_speed_max"}

    if field in _brightsky_only:
        return _fake_brightsky_bundle_range(date_from, date_to, field=field)
    if field in _weather_only:
        return _fake_weather_bundle_range(date_from, date_to, field=field)

    # field == "wind_speed_max" -- the collision. Count calls to
    # distinguish brightsky's (first, per bundle order) from weather's
    # (second).
    _fake_weather_bundle_dispatch._wind_speed_max_calls = getattr(
        _fake_weather_bundle_dispatch, "_wind_speed_max_calls", 0) + 1
    if _fake_weather_bundle_dispatch._wind_speed_max_calls == 1:
        return _fake_brightsky_bundle_range(date_from, date_to, field=field)
    return _fake_weather_bundle_range(date_from, date_to, field=field)

with patch("mcp_sql.get_context_range", side_effect=_fake_weather_bundle_dispatch):
    _qc_weather = mcp_server.query_context("weather", _DAY_1, _DAY_2, "daily")

check("query_context bundle 'weather': wind_speed_max day 1 = brightsky's value",
      _qc_weather["context"]["wind_speed_max"]["values"][0] ==
      {"date": _DAY_1, "value": 22.0})
check("query_context bundle 'weather': wind_speed_max day 2 falls back to weather's value",
      _qc_weather["context"]["wind_speed_max"]["values"][1] ==
      {"date": _DAY_2, "value": 21.0})
check("query_context bundle 'weather': field_sources records the per-day winner",
      _qc_weather["_meta"]["field_sources"]["wind_speed_max"] ==
      {_DAY_1: "brightsky", _DAY_2: "weather"})
check("query_context bundle 'weather': non-colliding brightsky-only field has no field_sources entry",
      "temperature_avg" not in _qc_weather["_meta"]["field_sources"])
check("query_context bundle 'weather': non-colliding weather-only field has no field_sources entry",
      "temperature_max" not in _qc_weather["_meta"]["field_sources"])
check("query_context bundle 'weather': result includes fields from both sources",
      "temperature_avg" in _qc_weather["context"] and
      "temperature_max" in _qc_weather["context"])
check("query_context bundle 'weather': unit field (v1.7.1.6) — colliding "
      "wind_speed_max keeps one consistent unit across the source switch",
      _qc_weather["context"]["wind_speed_max"]["unit"] == "km/h")
check("query_context bundle 'weather': unit field (v1.7.1.6) — non-colliding "
      "fields from each source also carry their unit",
      _qc_weather["context"]["temperature_avg"]["unit"] == "°C" and
      _qc_weather["context"]["temperature_max"]["unit"] == "°C")

# 3. v1.7.1.16 -- direct field request (not via a bundle name) for the
#    same colliding field. Regression test: this path (mcp_server's
#    "field == 'wind_speed_max'" special case, now inside the shared
#    _fetch_context_field() helper) already existed and worked before
#    the fix -- must keep producing the identical merged result.

def _fake_direct_collision_range(date_from, date_to, field=None):
    assert field == "wind_speed_max"
    return {
        "context": {
            "brightsky": {"wind_speed_max": {
                "values": [{"date": _DAY_1, "value": 22.0},
                           {"date": _DAY_2, "value": None}],
                "fallback": False, "source_resolution": "daily",
            }},
            "weather": {"wind_speed_max": {
                "values": [{"date": _DAY_1, "value": 18.5},
                           {"date": _DAY_2, "value": 21.0}],
                "fallback": False, "source_resolution": "daily",
            }},
        },
        "_meta": {},
    }

with patch("mcp_sql.get_context_range", side_effect=_fake_direct_collision_range):
    _qc_direct = mcp_server.query_context("wind_speed_max", _DAY_1, _DAY_2, "daily")

check("query_context direct 'wind_speed_max': day 1 = brightsky's value",
      _qc_direct["context"]["wind_speed_max"]["values"][0] ==
      {"date": _DAY_1, "value": 22.0})
check("query_context direct 'wind_speed_max': day 2 falls back to weather's value",
      _qc_direct["context"]["wind_speed_max"]["values"][1] ==
      {"date": _DAY_2, "value": 21.0})
check("query_context direct 'wind_speed_max': field_sources records the per-day winner",
      _qc_direct["_meta"]["field_sources"]["wind_speed_max"] ==
      {_DAY_1: "brightsky", _DAY_2: "weather"})
check("query_context direct 'wind_speed_max': no field_resolved_from (exact field name, no alias)",
      "field_resolved_from" not in _qc_direct["_meta"])

# 4. v1.7.1.16 fix -- an ALIAS resolving to "wind_speed_max" (e.g.
#    "max_wind_speed", CONTEXT_FIELD_ALIASES) must ALSO get the
#    brightsky/weather priority merge, not the raw, unmerged two-source
#    fan-out. Before this fix the alias branch returned right after
#    fetching -- above/before ever reaching the "field == 'wind_speed_max'"
#    block -- with both sources' conflicting values still separated by
#    source key. Live-server repro: "query_context max_wind_speed ..."
#    returned brightsky's and weather's values side by side instead of
#    one prioritized value (see NOTES_v1.7.1.16.md).

with patch("mcp_sql.get_context_range", side_effect=_fake_direct_collision_range):
    _qc_alias = mcp_server.query_context("max_wind_speed", _DAY_1, _DAY_2, "daily")

check("query_context alias 'max_wind_speed': resolves to wind_speed_max with the "
      "merge applied, not raw per-source values",
      _qc_alias["context"]["wind_speed_max"]["values"][0] ==
      {"date": _DAY_1, "value": 22.0} and
      _qc_alias["context"]["wind_speed_max"]["values"][1] ==
      {"date": _DAY_2, "value": 21.0})
check("query_context alias 'max_wind_speed': field_sources still populated after merge",
      _qc_alias["_meta"]["field_sources"]["wind_speed_max"] ==
      {_DAY_1: "brightsky", _DAY_2: "weather"})
check("query_context alias 'max_wind_speed': field_resolved_from/field_used set on top of the merge",
      _qc_alias["_meta"]["field_resolved_from"] == "max_wind_speed" and
      _qc_alias["_meta"]["field_used"] == "wind_speed_max")

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.query_raw", return_value={"health": {}, "_meta": {}}) as _m_live, \
     patch("mcp_sql.get_raw_range") as _m_sql:
    mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain="health")
    _m_live.assert_called_once_with("floors", "2000-01-01", "2000-01-01", domain="health")
    _m_sql.assert_not_called()
check("mcp_server.query_raw: live branch calls mcp_map.query_raw, not mcp_sql", True)

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.get_archive_metadata", return_value={"data": {}, "error": None}) as _m_live, \
     patch("mcp_sql.get_metadata_range") as _m_sql:
    mcp_server.get_archive_metadata("stats")
    _m_live.assert_called_once_with("stats", date_from=None, date_to=None)
    _m_sql.assert_not_called()
check("mcp_server.get_archive_metadata: live branch calls mcp_map.get_archive_metadata, not mcp_sql", True)

# ── 8e. Stöpsel edge cases — query_fit_activities and list_available_fields
#        both branches (SQLite AND live per _route_query()'s current
#        "sqlite" placeholder, and forced "live") call the identical
#        mcp_map function, since neither has a real SQLite counterpart yet
#        (query_fit_activities: no fit_map.py/mcp_sql.get_fit_range() until
#        v1.8; list_available_fields: reflects the code's own field
#        registry, not archived data, no cache benefit at all — see both
#        wrappers' own comments in clients/mcp_server.py for the full
#        rationale). This is the one place where "SQLite branch" and
#        "live branch" are expected to be indistinguishable by design —
#        tested explicitly so a future accidental divergence (e.g. someone
#        wiring a real mcp_sql.get_fit_range() into only one branch) shows
#        up as a single, clearly-labelled failure rather than silently
#        passing either way.

with patch("maps.mcp_map.query_fit_activities", return_value={"fit": {"error": "domain not yet available"}, "_meta": {}}) as _m:
    mcp_server.query_fit_activities("some_field", _TEST_DATE, _TEST_DATE, "daily")
    check("mcp_server.query_fit_activities: SQLite branch (placeholder) calls mcp_map (Stöpsel)",
          _m.call_count == 1)
    _m.assert_called_once_with("some_field", _TEST_DATE, _TEST_DATE, "daily")

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.query_fit_activities", return_value={"fit": {"error": "domain not yet available"}, "_meta": {}}) as _m:
    mcp_server.query_fit_activities("some_field", _TEST_DATE, _TEST_DATE, "daily")
    check("mcp_server.query_fit_activities: live branch also calls mcp_map (Stöpsel, identical)",
          _m.call_count == 1)

with patch("maps.mcp_map.list_available_fields", return_value={"domains": [], "metadata_kinds": [], "fields": {}}) as _m:
    mcp_server.list_available_fields(domain="health")
    _m.assert_called_once_with("health")
check("mcp_server.list_available_fields: SQLite branch (placeholder) calls mcp_map (Stöpsel)", True)

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.list_available_fields", return_value={"domains": [], "metadata_kinds": [], "fields": {}}) as _m:
    mcp_server.list_available_fields(domain="health")
    _m.assert_called_once_with("health")
check("mcp_server.list_available_fields: live branch also calls mcp_map (Stöpsel, identical)", True)

# ── 8f. refresh_cache() — unaffected by the weiche, verified explicitly ──────
#
# v1.7.1 — refresh_cache() delegates to mcp_update.sync_all(), mocked
# here rather than exercised for real: a real call would open a live
# SQLite connection and bind garmin_config.MCP_HTTP_PORT
# (clients/mcp_sql.py / clients/mcp_update.py's own concern, out of
# scope for this delegation-only test — see NOTES_v1.7.1_session2.md's
# "mcp_sql.py throws, mcp_update.py catches" split for where that
# behaviour is actually tested). _route_query is patched to a sentinel
# that would raise if called, so a future accidental wiring of
# refresh_cache() into the weiche (Ziel 6 regression) fails loudly here
# rather than silently — see clients/mcp_server.py's module comment on
# the weiche for the binding "refresh_cache does NOT route" decision.
def _route_query_should_not_be_called(kind):
    raise AssertionError(f"_route_query() called with {kind!r} — refresh_cache() must not route")

with patch("mcp_server._route_query", side_effect=_route_query_should_not_be_called), \
     patch("mcp_update.sync_all", return_value={"health_days_updated": 3}) as _m:
    _result = mcp_server.refresh_cache()
    _m.assert_called_once_with()
check("mcp_server.refresh_cache: delegates to mcp_update.sync_all unchanged, never routes",
      _result == {"health_days_updated": 3})

# ── 8g. Return value pass-through — wrapper returns exactly what the
#        chosen branch's function returns (SQLite branch, current default) ──
_dummy_result = {"health": {"values": [], "fallback": False, "source_resolution": "daily"}, "_meta": {}}
with patch("mcp_sql.get_health_range", return_value=_dummy_result):
    _wrapper_result = mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("mcp_server.query_health: return value passed through unchanged",
      _wrapper_result == _dummy_result)

# ── 8g-bis. field is actually forwarded to get_health_range() (v1.7.1.2
#           field-filter fix regression guard) ──
#
# The pass-through check above only verifies the return value survives
# unchanged — it never asserted WHICH arguments query_health() passes to
# get_health_range(). That gap is exactly why the original v1.7.1.1 bug
# (field silently dropped, every call returning all ~26 health fields
# instead of the one requested) went unnoticed by this suite. Same
# assert_called_once_with() pattern as the list_available_fields() checks
# above (Zeile 441-450) — a future regression that drops field again, or
# passes it positionally in a way that breaks get_health_range()'s
# keyword-only expectation, fails loudly here.
with patch("mcp_sql.get_health_range", return_value=_dummy_result) as _m:
    mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="hrv_last_night")
check("mcp_server.query_health: field is forwarded to get_health_range() (v1.7.1.2 field-filter fix)", True)


# ══════════════════════════════════════════════════════════════════════════════
#  8d. garmin_config.py — MCP_HTTP_PORT (v1.7.0.1, replaces stdio transport)
# ══════════════════════════════════════════════════════════════════════════════

# Default — no ENV override set.
os.environ.pop("GARMIN_MCP_HTTP_PORT", None)
importlib.reload(cfg)
check("garmin_config: MCP_HTTP_PORT is an int", isinstance(cfg.MCP_HTTP_PORT, int))
check("garmin_config: MCP_HTTP_PORT default is 8756", cfg.MCP_HTTP_PORT == 8756)

# ENV override wins over the default — same precedence pattern already
# exercised for GARMIN_OUTPUT_DIR/MCP_LLM_BACKEND elsewhere in this file.
# Deliberately NOT testing the MCP_SERVER_CONFIG_FILE (file-layer)
# precedence step here — that file lives at a fixed Path.home() location,
# not inside _TMPDIR/GARMIN_OUTPUT_DIR's sandbox, and no existing test in
# this file writes to it either (same scoping choice already made for
# mcp_llm_backend's file-layer precedence — ENV-only coverage).
os.environ["GARMIN_MCP_HTTP_PORT"] = "9999"
importlib.reload(cfg)
check("garmin_config: MCP_HTTP_PORT — ENV overrides default",
      cfg.MCP_HTTP_PORT == 9999)
os.environ.pop("GARMIN_MCP_HTTP_PORT", None)
importlib.reload(cfg)

# Regression guards — v1.7.0.1 removed these two fields outright (the
# stdio-era PID-lockfile liveness check and the Ollama-model config-file
# field); a reappearance here would mean a stale merge or a reverted
# anchor.
check("garmin_config: MCP_SERVER_LOCK_FILE no longer exists",
      not hasattr(cfg, "MCP_SERVER_LOCK_FILE"))
check("garmin_config: MCP_OLLAMA_MODEL no longer exists",
      not hasattr(cfg, "MCP_OLLAMA_MODEL"))


# ══════════════════════════════════════════════════════════════════════════════
#  8e. garmin_config.py — MCP_HEADLESS (v1.7.0.1, Eckpunkt 6)
# ══════════════════════════════════════════════════════════════════════════════

# Default — no ENV override, no config-file key set. Session decision
# (NOTES_v1.7.0.1vorbereitung.md): the window stays the default, so this
# must default to False, not True — a regression here would silently
# flip every existing standalone/GLA install to headless-by-default on
# next start.
os.environ.pop("GARMIN_MCP_HEADLESS", None)
importlib.reload(cfg)
check("garmin_config: MCP_HEADLESS is a bool", isinstance(cfg.MCP_HEADLESS, bool))
check("garmin_config: MCP_HEADLESS default is False", cfg.MCP_HEADLESS is False)

# ENV override wins over the default — same "1"/"true"/"yes"
# case-insensitive parsing the implementation uses, checked from both
# directions (a truthy string flips it, an unrelated string does not).
os.environ["GARMIN_MCP_HEADLESS"] = "true"
importlib.reload(cfg)
check("garmin_config: MCP_HEADLESS — ENV 'true' overrides default",
      cfg.MCP_HEADLESS is True)
os.environ["GARMIN_MCP_HEADLESS"] = "0"
importlib.reload(cfg)
check("garmin_config: MCP_HEADLESS — ENV '0' resolves to False",
      cfg.MCP_HEADLESS is False)
os.environ.pop("GARMIN_MCP_HEADLESS", None)
importlib.reload(cfg)


# ══════════════════════════════════════════════════════════════════════════════
#  8f. garmin_config.py — MCP_EXTRA_ALLOWED_HOSTS(_ENABLED) (v1.7.0.2)
# ══════════════════════════════════════════════════════════════════════════════

# _parse_extra_hosts() — pure parsing, no ENV/config-file involvement.
check("garmin_config: _parse_extra_hosts — single host gets :* appended",
      cfg._parse_extra_hosts("host.docker.internal") == ["host.docker.internal:*"])
check("garmin_config: _parse_extra_hosts — explicit port kept as-is",
      cfg._parse_extra_hosts("myhost:9000") == ["myhost:9000"])
check("garmin_config: _parse_extra_hosts — comma-separated, whitespace stripped",
      cfg._parse_extra_hosts(" host.docker.internal , myhost:9000 ") ==
      ["host.docker.internal:*", "myhost:9000"])
check("garmin_config: _parse_extra_hosts — empty entries dropped",
      cfg._parse_extra_hosts("host.docker.internal,,  ,") == ["host.docker.internal:*"])
check("garmin_config: _parse_extra_hosts — empty string yields empty list",
      cfg._parse_extra_hosts("") == [])

# MCP_EXTRA_ALLOWED_HOSTS_ENABLED — default False, ENV overrides.
# The "default" assertion needs Path.home() isolated to _TMPDIR for its
# reload: unlike MCP_HTTP_PORT above (deliberately untested at the file
# layer), this field is meant to be toggled and saved for real via the
# GUI checkbox — the real ~/.garmin_mcp_server_config.json can already
# carry mcp_extra_hosts_enabled=true from an earlier manual session
# (exactly what happened here after live-testing against Open WebUI this
# session), which would make this assertion depend on machine state
# instead of code behaviour. ENV-override below is unaffected either way
# — ENV always wins regardless of what the file holds.
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED", None)
with patch("pathlib.Path.home", return_value=_TMPDIR):
    importlib.reload(cfg)
    check("garmin_config: MCP_EXTRA_ALLOWED_HOSTS_ENABLED default is False",
          cfg.MCP_EXTRA_ALLOWED_HOSTS_ENABLED is False)
importlib.reload(cfg)
os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED"] = "true"
importlib.reload(cfg)
check("garmin_config: MCP_EXTRA_ALLOWED_HOSTS_ENABLED — ENV 'true' overrides default",
      cfg.MCP_EXTRA_ALLOWED_HOSTS_ENABLED is True)
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED", None)
importlib.reload(cfg)

# MCP_EXTRA_ALLOWED_HOSTS — real default is "host.docker.internal", not empty.
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS", None)
importlib.reload(cfg)
check("garmin_config: MCP_EXTRA_ALLOWED_HOSTS_RAW default is host.docker.internal",
      cfg.MCP_EXTRA_ALLOWED_HOSTS_RAW == "host.docker.internal")
check("garmin_config: MCP_EXTRA_ALLOWED_HOSTS default is parsed to one wildcard entry",
      cfg.MCP_EXTRA_ALLOWED_HOSTS == ["host.docker.internal:*"])

# ENV override wins over the default — same precedence pattern as MCP_HTTP_PORT.
os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS"] = "other-host:1234"
importlib.reload(cfg)
check("garmin_config: MCP_EXTRA_ALLOWED_HOSTS — ENV overrides default",
      cfg.MCP_EXTRA_ALLOWED_HOSTS == ["other-host:1234"])
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS", None)
importlib.reload(cfg)


# ══════════════════════════════════════════════════════════════════════════════
#  8g. clients/mcp_server.py — transport_security wiring (v1.7.0.2)
# ══════════════════════════════════════════════════════════════════════════════

# Disabled (default) — transport_security is still the SDK's own
# localhost-only default (None passed through unchanged), no extra host.
# Same Path.home() isolation as the MCP_EXTRA_ALLOWED_HOSTS_ENABLED
# default check above, and for the same reason — the real config file
# can carry the checkbox saved as on from a previous manual session.
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED", None)
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS", None)
with patch("pathlib.Path.home", return_value=_TMPDIR):
    importlib.reload(cfg)
    importlib.reload(mcp_server)
    _ts_off = mcp_server.mcp.settings.transport_security
    check("mcp_server: transport_security present (SDK default) when disabled",
          _ts_off is not None)
    check("mcp_server: no extra host present when disabled",
          "host.docker.internal:*" not in _ts_off.allowed_hosts)
importlib.reload(cfg)
importlib.reload(mcp_server)

# Enabled — extra host present, three SDK-default hosts still present too.
os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED"] = "true"
os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS"] = "host.docker.internal"
importlib.reload(cfg)
importlib.reload(mcp_server)
_ts_on = mcp_server.mcp.settings.transport_security
check("mcp_server: transport_security includes extra host when enabled",
      "host.docker.internal:*" in _ts_on.allowed_hosts)
check("mcp_server: transport_security still includes the three SDK-default hosts",
      {"127.0.0.1:*", "localhost:*", "[::1]:*"}.issubset(set(_ts_on.allowed_hosts)))
check("mcp_server: transport_security still includes the three SDK-default origins",
      {"http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"}.issubset(
          set(_ts_on.allowed_origins)))

os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED", None)
os.environ.pop("GARMIN_MCP_EXTRA_ALLOWED_HOSTS", None)
importlib.reload(cfg)
importlib.reload(mcp_server)


# ══════════════════════════════════════════════════════════════════════════════
#  9. clients/mcp_update.py — _reconcile_field_registry() (v1.7.1.17)
# ══════════════════════════════════════════════════════════════════════════════
#
# The field-registry mechanism itself (mcp_sql.mcp_field_registry +
# get_registered_fields()/set_registered_fields()/reset_health_sync_state()/
# reset_context_source()) has no dedicated real-DB test file in this
# project (test_mcp_sql.py/test_mcp_update.py do not exist — only this
# file covers the MCP layer, and it mocks mcp_sql throughout rather than
# exercising a real SQLite connection, same scoping choice section 8f's
# own comment already flags for sync_all()). This section covers
# _reconcile_field_registry()'s own decision logic (seed vs. reset) via
# the same mock style as the rest of this file, not the underlying SQL —
# mcp_sql.py's four new functions themselves remain untested against a
# real DB, a gap worth closing separately if this mechanism proves
# fragile in practice.

section("mcp_update 9. _reconcile_field_registry() — field-growth detection")

import mcp_update

_LAF_HEALTH_SEED = {"fields": {"health": {"garmin": ["field_a", "field_b"]}}}
_LAF_CONTEXT_SEED = {"fields": {"context": {"weather": ["temperature_max"]}}}

def _laf_side_effect(domain=None):
    return _LAF_HEALTH_SEED if domain == "health" else _LAF_CONTEXT_SEED

# ── 9a. First-ever run (stored is None) — seeds the registry, no reset ────────
with patch("maps.mcp_map.list_available_fields", side_effect=_laf_side_effect), \
     patch("mcp_sql.get_registered_fields", return_value=None), \
     patch("mcp_sql.set_registered_fields") as _m_set_seed, \
     patch("mcp_sql.reset_health_sync_state") as _m_reset_health_seed, \
     patch("mcp_sql.reset_context_source") as _m_reset_context_seed:
    _resets_seed = mcp_update._reconcile_field_registry()
check("_reconcile_field_registry: first run (stored=None) reports no resets",
      _resets_seed == {})
check("_reconcile_field_registry: first run never calls reset_health_sync_state",
      not _m_reset_health_seed.called)
check("_reconcile_field_registry: first run never calls reset_context_source",
      not _m_reset_context_seed.called)
check("_reconcile_field_registry: first run still seeds the health registry",
      _m_set_seed.call_args_list[0].args == ("health", {"field_a", "field_b"}))

# ── 9b. Health domain gained a field since last sync — triggers reset ─────────
def _grf_health_grown(domain):
    return {"field_a"} if domain == "health" else {"temperature_max"}

with patch("maps.mcp_map.list_available_fields", side_effect=_laf_side_effect), \
     patch("mcp_sql.get_registered_fields", side_effect=_grf_health_grown), \
     patch("mcp_sql.set_registered_fields") as _m_set_health, \
     patch("mcp_sql.reset_health_sync_state") as _m_reset_health, \
     patch("mcp_sql.reset_context_source") as _m_reset_context_unaffected:
    _resets_health = mcp_update._reconcile_field_registry()
check("_reconcile_field_registry: health field growth ('field_b' new) is reported as reset",
      _resets_health.get("health") is True)
check("_reconcile_field_registry: health growth calls reset_health_sync_state exactly once",
      _m_reset_health.call_count == 1)
check("_reconcile_field_registry: unchanged context source is not reported as reset",
      "context:weather" not in _resets_health)
check("_reconcile_field_registry: unchanged context source never calls reset_context_source",
      not _m_reset_context_unaffected.called)
check("_reconcile_field_registry: registry re-written to the new live field set after reset",
      _m_set_health.call_args_list[0].args == ("health", {"field_a", "field_b"}))

# ── 9c. Context source gained a field — triggers reset for that source only ───
def _grf_context_grown(domain):
    return {"field_a", "field_b"} if domain == "health" else set()

with patch("maps.mcp_map.list_available_fields", side_effect=_laf_side_effect), \
     patch("mcp_sql.get_registered_fields", side_effect=_grf_context_grown), \
     patch("mcp_sql.set_registered_fields"), \
     patch("mcp_sql.reset_health_sync_state") as _m_reset_health_unaffected, \
     patch("mcp_sql.reset_context_source") as _m_reset_context:
    _resets_context = mcp_update._reconcile_field_registry()
check("_reconcile_field_registry: context source growth is reported as reset",
      _resets_context.get("context:weather") is True)
check("_reconcile_field_registry: context growth calls reset_context_source('weather') exactly once",
      _m_reset_context.call_args.args == ("weather",))
check("_reconcile_field_registry: unaffected health domain is not reported as reset",
      "health" not in _resets_context)
check("_reconcile_field_registry: unaffected health domain never calls reset_health_sync_state",
      not _m_reset_health_unaffected.called)


# ══════════════════════════════════════════════════════════════════════════════
#  10. clients/mcp_sql.py — invalidate_context_day() (v1.7.2.3)
# ══════════════════════════════════════════════════════════════════════════════
#
# Real SQLite DB, not mocked — closes exactly the gap section 9's own
# comment flags (mcp_sql.py's functions untested against a real DB).
# invalidate_context_day() is a pure DB primitive (SELECT + set
# difference + UPDATE), cheap and deterministic to exercise for real.

section("mcp_sql 10. invalidate_context_day() — real DB")

import mcp_sql
mcp_sql.init_db()

mcp_sql.upsert_context_day(
    "2026-03-05", {"weather": {"temp": 20}, "pollen": {"birch": 1.0}},
    {"weather", "pollen", "brightsky"}, {"weather", "pollen", "brightsky"})
mcp_sql.invalidate_context_day("2026-03-05", {"weather"})
_state_after_one = mcp_sql.get_context_day_state("2026-03-05")
check("invalidate_context_day: removes the given source from complete_sources",
      "weather" not in _state_after_one["complete_sources"])
check("invalidate_context_day: removes the given source from attempted_sources",
      "weather" not in _state_after_one["attempted_sources"])
check("invalidate_context_day: leaves other sources' complete_sources untouched",
      {"pollen", "brightsky"} <= _state_after_one["complete_sources"])
check("invalidate_context_day: leaves other sources' attempted_sources untouched",
      {"pollen", "brightsky"} <= _state_after_one["attempted_sources"])
# v1.7.2.3 correction (2026-09-20, maintainer): payload must be deleted too —
# get_context_range() (what the live LLM-facing query_context() tool
# actually reads, _route_query() is hard-pinned to "sqlite") reads
# payload_json directly and knows nothing about complete_sources. Leaving
# the old payload in place would silently serve stale data as if current.
check("invalidate_context_day: DELETES the invalidated source's payload "
      "(not just bookkeeping — a live query must see 'no data', not stale data)",
      "weather" not in _state_after_one["payload"])
check("invalidate_context_day: leaves other sources' payload untouched",
      _state_after_one["payload"].get("pollen") == {"birch": 1.0})

mcp_sql.upsert_context_day(
    "2026-03-06", {"weather": {"temp": 1}, "pollen": {"birch": 1},
                   "brightsky": {"temp": 2}, "airquality": {"pm": 3}},
    {"weather", "pollen", "brightsky", "airquality"},
    {"weather", "pollen", "brightsky", "airquality"})
mcp_sql.invalidate_context_day("2026-03-06", {"weather", "pollen"})
_state_multi = mcp_sql.get_context_day_state("2026-03-06")
check("invalidate_context_day: removes multiple sources in one call",
      _state_multi["complete_sources"] == {"brightsky", "airquality"})
check("invalidate_context_day: removes multiple sources' payload in one call",
      "weather" not in _state_multi["payload"] and "pollen" not in _state_multi["payload"])
check("invalidate_context_day: multi-source call leaves untouched sources' payload intact",
      _state_multi["payload"].get("brightsky") == {"temp": 2} and
      _state_multi["payload"].get("airquality") == {"pm": 3})

try:
    mcp_sql.invalidate_context_day("2099-01-01", {"weather"})
    _noop_no_row_ok = True
except Exception:
    _noop_no_row_ok = False
check("invalidate_context_day: day with no row at all — no-op, no exception",
      _noop_no_row_ok)

mcp_sql.upsert_context_day("2026-03-07", {}, {"pollen"}, {"pollen"})
mcp_sql.invalidate_context_day("2026-03-07", {"weather"})
_state_absent_source = mcp_sql.get_context_day_state("2026-03-07")
check("invalidate_context_day: removing a source that was never present — no-op, no crash",
      _state_absent_source["complete_sources"] == {"pollen"})


# ══════════════════════════════════════════════════════════════════════════════
#  11. clients/mcp_update.py — context-resync marker consumption (v1.7.2.3)
# ══════════════════════════════════════════════════════════════════════════════
#
# Same mock style as section 9 — mcp_sql.invalidate_context_day is
# mocked here (its own correctness against a real DB is section 10's
# job). This section covers _apply_pending_context_resync()'s own
# decision logic: the Soll/Ist check against the ack (the maintainer's explicit
# requirement — sync_all() runs at every MCP boot, so an already-acked
# entry must never be re-invalidated), per-entry error handling (a
# failing entry must not be acked, so it is retried later), the ack
# file read/write round-trip including corrupt-file handling, and
# (11g) the real bug found via a live-archive round-trip on 2026-09-20:
# a SECOND real repair of the same (date, source) must still be applied,
# not silently swallowed by the first repair's ack entry.

section("mcp_update 11. context-resync marker consumption")

_CRA_BASE = _TMPDIR / "resync_test"
_CRA_BASE.mkdir(parents=True, exist_ok=True)
_ack_file = lambda base: base / "garmin_data" / "log" / "mcp" / "context_resync_ack.json"

# ── 11a. No pending markers at all ─────────────────────────────────────────────
with patch("maps.mcp_map.get_archive_metadata", return_value={"data": [], "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_none:
    _applied_none = mcp_update._apply_pending_context_resync(_CRA_BASE)
check("_apply_pending_context_resync: empty pending returns an empty list",
      _applied_none == [])
check("_apply_pending_context_resync: empty pending never calls invalidate_context_day",
      not _m_inv_none.called)
check("_apply_pending_context_resync: no ack file written when nothing was pending",
      not _ack_file(_CRA_BASE).exists())

# ── 11b. Fresh pending, nothing acked yet ──────────────────────────────────────
_pending_fresh = [{"date": "2026-03-05", "source": "weather", "marked_at": "T1"},
                   {"date": "2026-03-06", "source": "pollen", "marked_at": "T1"}]
with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_fresh, "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_fresh:
    _applied_fresh = mcp_update._apply_pending_context_resync(_CRA_BASE)
check("_apply_pending_context_resync: fresh pending — both entries applied",
      _applied_fresh == _pending_fresh)
check("_apply_pending_context_resync: fresh pending — invalidate_context_day called twice",
      _m_inv_fresh.call_count == 2)
check("_apply_pending_context_resync: invalidate_context_day called with (date, {source})",
      _m_inv_fresh.call_args_list[0].args == ("2026-03-05", {"weather"}))
_ack_after_fresh = json.loads(_ack_file(_CRA_BASE).read_text(encoding="utf-8"))
check("_apply_pending_context_resync: ack file written with both entries (incl. marked_at)",
      {(e["date"], e["source"], e["marked_at"]) for e in _ack_after_fresh["acked"]}
      == {("2026-03-05", "weather", "T1"), ("2026-03-06", "pollen", "T1")})

# ── 11c. Soll/Ist check — same pending again, already acked ───────────────────
with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_fresh, "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_repeat:
    _applied_repeat = mcp_update._apply_pending_context_resync(_CRA_BASE)
check("_apply_pending_context_resync: already-acked pending — applied list is empty",
      _applied_repeat == [])
check("_apply_pending_context_resync: already-acked pending — invalidate_context_day "
      "never called (Soll/Ist check — this is the core requirement)",
      not _m_inv_repeat.called)

# ── 11d. Mixed — one already acked, one genuinely new ──────────────────────────
_pending_mixed = _pending_fresh + [{"date": "2026-03-07", "source": "brightsky", "marked_at": "T1"}]
with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_mixed, "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_mixed:
    _applied_mixed = mcp_update._apply_pending_context_resync(_CRA_BASE)
check("_apply_pending_context_resync: mixed pending — only the new entry is applied",
      _applied_mixed == [{"date": "2026-03-07", "source": "brightsky", "marked_at": "T1"}])
check("_apply_pending_context_resync: mixed pending — invalidate_context_day called once",
      _m_inv_mixed.call_count == 1)

# ── 11e. A failing entry is skipped, not acked (retried on the next pass) ─────
_CRA_BASE2 = _TMPDIR / "resync_test_errors"
_CRA_BASE2.mkdir(parents=True, exist_ok=True)
_pending_err = [{"date": "2026-04-01", "source": "weather", "marked_at": "T1"},
                {"date": "2026-04-02", "source": "pollen", "marked_at": "T1"}]

def _inv_side_effect(day, sources):
    if day == "2026-04-01":
        raise RuntimeError("simulated DB error")

with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_err, "error": None}), \
     patch("mcp_sql.invalidate_context_day", side_effect=_inv_side_effect):
    _applied_err = mcp_update._apply_pending_context_resync(_CRA_BASE2)
check("_apply_pending_context_resync: a failing entry is excluded from the applied list",
      _applied_err == [{"date": "2026-04-02", "source": "pollen", "marked_at": "T1"}])
_ack_after_err = json.loads(_ack_file(_CRA_BASE2).read_text(encoding="utf-8"))
_ack_keys_err = {(e["date"], e["source"], e["marked_at"]) for e in _ack_after_err["acked"]}
check("_apply_pending_context_resync: the failing entry is NOT written to the ack "
      "(must be retried, not silently lost)",
      ("2026-04-01", "weather", "T1") not in _ack_keys_err)
check("_apply_pending_context_resync: the succeeding entry IS written to the ack",
      ("2026-04-02", "pollen", "T1") in _ack_keys_err)

# ── 11f. Ack file read/write round-trip + corrupt-file handling ───────────────
_ack_rt_base = _TMPDIR / "ack_roundtrip"
mcp_update._write_context_resync_ack(_ack_rt_base, {("2026-01-01", "weather", "T1")})
check("_write_context_resync_ack / _read_context_resync_ack: round-trip preserves the set",
      mcp_update._read_context_resync_ack(_ack_rt_base) == {("2026-01-01", "weather", "T1")})
check("_read_context_resync_ack: missing file returns an empty set, no exception",
      mcp_update._read_context_resync_ack(_TMPDIR / "ack_missing") == set())

_ack_file(_ack_rt_base).write_text("{ not valid json", encoding="utf-8")
check("_read_context_resync_ack: corrupt JSON degrades to an empty set, no exception",
      mcp_update._read_context_resync_ack(_ack_rt_base) == set())

# ── 11g. Regression: a SECOND real repair of the same (date, source) must ─────
#         still be applied — the exact bug found via a live-archive round-trip
#         (New York -> back to Herford) on 2026-09-20. Matching on (date,
#         source) alone made the second repair's identical key look
#         "already acked" from the first, silently dropping it.
_CRA_BASE3 = _TMPDIR / "resync_test_repeat"
_CRA_BASE3.mkdir(parents=True, exist_ok=True)
_pending_t1 = [{"date": "2026-05-01", "source": "weather", "marked_at": "T1"}]
with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_t1, "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_t1:
    _applied_t1 = mcp_update._apply_pending_context_resync(_CRA_BASE3)
check("_apply_pending_context_resync (11g): first repair (T1) is applied",
      _applied_t1 == _pending_t1 and _m_inv_t1.call_count == 1)

# context_silo_repair.py would now REPLACE the pending entry with a fresh
# marked_at (T2) — simulated here directly, same as _mark_pending_resync()
# does on a second real repair of the same (date, source).
_pending_t2 = [{"date": "2026-05-01", "source": "weather", "marked_at": "T2"}]
with patch("maps.mcp_map.get_archive_metadata",
           return_value={"data": _pending_t2, "error": None}), \
     patch("mcp_sql.invalidate_context_day") as _m_inv_t2:
    _applied_t2 = mcp_update._apply_pending_context_resync(_CRA_BASE3)
check("_apply_pending_context_resync (11g): second repair (T2, same date/source) "
      "is ALSO applied, not silently dropped as 'already acked'",
      _applied_t2 == _pending_t2 and _m_inv_t2.call_count == 1)

# The stale T1 ack entry must be pruned once T2 is the only thing pending —
# keeps the ack file from growing without bound.
_ack_after_t2 = json.loads(_ack_file(_CRA_BASE3).read_text(encoding="utf-8"))
_ack_keys_t2 = {(e["date"], e["source"], e["marked_at"]) for e in _ack_after_t2["acked"]}
check("_apply_pending_context_resync (11g): stale T1 ack entry pruned once "
      "superseded by T2 (ack does not grow without bound)",
      _ack_keys_t2 == {("2026-05-01", "weather", "T2")})


# ══════════════════════════════════════════════════════════════════════════════
#  12. clients/mcp_sql.py — get_gaps_range() edge cases (v1.7.5 Block A)
# ══════════════════════════════════════════════════════════════════════════════
#
# Real SQLite DB (same shared connection sections 10-11 already use),
# not mocked — these are pure DB-read primitives, cheap and
# deterministic to exercise for real.

section("mcp_sql 12. get_gaps_range() — health/context edge cases")

# "standard" quality must NOT count as a gap — only None (no entry at
# all) or "failed" do (see _compute_health_gaps()'s own docstring).
mcp_sql.upsert_structured_log_entry(
    "quality_log", "2026-04-01", {"date": "2026-04-01", "quality": "standard"}, "q1")
mcp_sql.upsert_structured_log_entry(
    "quality_log", "2026-04-02", {"date": "2026-04-02", "quality": "failed"}, "q2")
# 2026-04-03 intentionally left with no quality_log row at all.
_health_gaps = mcp_sql.get_gaps_range("health", "2026-04-01", "2026-04-03")
check("get_gaps_range health: 'standard' quality is NOT a gap",
      "2026-04-01" not in _health_gaps["gaps"])
check("get_gaps_range health: 'failed' quality IS a gap",
      "2026-04-02" in _health_gaps["gaps"])
check("get_gaps_range health: a day with no quality_log row at all IS a gap",
      "2026-04-03" in _health_gaps["gaps"])

# Context: attempted-but-not-complete (one source tried, nothing
# delivered) must NOT count as a gap — only an empty attempted_sources
# set (or no row at all) does (see _compute_context_gaps()'s docstring).
mcp_sql.upsert_context_day("2026-04-01", {}, complete_sources=set(),
                            attempted_sources={"weather"})
mcp_sql.upsert_context_day("2026-04-02", {}, complete_sources=set(),
                            attempted_sources=set())
_context_gaps = mcp_sql.get_gaps_range("context", "2026-04-01", "2026-04-03")
check("get_gaps_range context: attempted-but-empty-result is NOT a gap",
      "2026-04-01" not in _context_gaps["gaps"])
check("get_gaps_range context: empty attempted_sources IS a gap",
      "2026-04-02" in _context_gaps["gaps"])
check("get_gaps_range context: a day with no row at all IS a gap",
      "2026-04-03" in _context_gaps["gaps"])

_fit_gaps = mcp_sql.get_gaps_range("fit", "2026-04-01", "2026-04-03")
check("get_gaps_range fit: degrades to empty gaps + explicit error",
      _fit_gaps["gaps"] == [] and _fit_gaps["error"] == "domain not yet available")

try:
    mcp_sql.get_gaps_range("banana", "2026-04-01", "2026-04-03")
    check("get_gaps_range: unknown domain raises ValueError", False)
except ValueError:
    check("get_gaps_range: unknown domain raises ValueError", True)


# ══════════════════════════════════════════════════════════════════════════════
#  13. clients/mcp_sql.py — baseline CRUD edge cases (v1.7.5 Block A)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_sql 13. upsert_health_baseline()/get_health_baselines_range() — edge cases")

mcp_sql.upsert_health_baseline("2026-04-10", "hrv_last_night", 55.0, 45.0, 65.0, False)
mcp_sql.upsert_health_baseline("2026-04-10", "resting_heart_rate", 60.0, 50.0, 70.0, True)
mcp_sql.upsert_health_baseline("2026-04-11", "hrv_last_night", 56.0, None, None, None)

_filtered = mcp_sql.get_health_baselines_range("2026-04-10", "2026-04-11", field="hrv_last_night")
check("get_health_baselines_range: field filter excludes other fields",
      "resting_heart_rate" not in _filtered["health_baselines"])
check("get_health_baselines_range: field filter keeps the requested field",
      "hrv_last_night" in _filtered["health_baselines"])

_entries_by_date = {
    v["date"]: v for v in _filtered["health_baselines"]["hrv_last_night"]["values"]
}
check("upsert_health_baseline: anomaly_flag False round-trips as False (not None/0)",
      _entries_by_date["2026-04-10"]["anomaly_flag"] is False)
check("upsert_health_baseline: anomaly_flag None round-trips as None (not-enough-data, "
      "distinct from 'judged normal')",
      _entries_by_date["2026-04-11"]["anomaly_flag"] is None)
check("upsert_health_baseline: ref_low/ref_high None round-trip as None",
      _entries_by_date["2026-04-11"]["ref_low"] is None and
      _entries_by_date["2026-04-11"]["ref_high"] is None)

_unfiltered = mcp_sql.get_health_baselines_range("2026-04-10", "2026-04-10")
check("get_health_baselines_range: no field filter returns every field for the day",
      {"hrv_last_night", "resting_heart_rate"} <= set(_unfiltered["health_baselines"]))


# ══════════════════════════════════════════════════════════════════════════════
#  14. clients/mcp_update.py — _sync_health_baselines() edge cases (v1.7.5 Block A)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_update 14. _sync_health_baselines() — edge cases")

with patch("mcp_update.mcp_map.get_archive_metadata", return_value={"data": {"date_max": None}}):
    _empty_updated, _empty_failed = mcp_update._sync_health_baselines()
check("_sync_health_baselines: empty archive (date_max=None) returns (0, 0)",
      _empty_updated == 0 and _empty_failed == 0)

_anchor = "2026-04-20"
with patch("mcp_update.mcp_map.get_archive_metadata",
           return_value={"data": {"date_max": _anchor}}), \
     patch("mcp_update.mcp_map.list_available_fields",
           return_value={"fields": {"health": {"garmin": [
               "hrv_last_night", "heart_rate_series"]}}}), \
     patch("mcp_update.mcp_sql.get_health_range",
           return_value={"health": {}}):  # no cached values for any field at all
    _calls_no_data = []
    with patch("mcp_update.mcp_sql.upsert_health_baseline",
               side_effect=lambda *a: _calls_no_data.append(a)):
        _nodata_updated, _nodata_failed = mcp_update._sync_health_baselines()
_anchor_call = [c for c in _calls_no_data if c[0] == _anchor and c[1] == "hrv_last_night"][0]
check("_sync_health_baselines: field with zero data in window -> baseline_avg None",
      _anchor_call[2] is None)
check("_sync_health_baselines: field with zero data in window -> ref_low/ref_high/"
      "anomaly_flag all None",
      _anchor_call[3] is None and _anchor_call[4] is None and _anchor_call[5] is None)
check("_sync_health_baselines: *_series fields are skipped entirely",
      all(c[1] != "heart_rate_series" for c in _calls_no_data))
check("_sync_health_baselines: no failures when every upsert succeeds",
      _nodata_failed == 0)

# One specific (day, field) upsert raises -> must be logged/counted, must NOT
# abort the rest of the pass (same per-unit principle every other _sync_*
# function in this module already has test coverage for).
_fake_values = {_anchor: 50.0}
with patch("mcp_update.mcp_map.get_archive_metadata",
           return_value={"data": {"date_max": _anchor}}), \
     patch("mcp_update.mcp_map.list_available_fields",
           return_value={"fields": {"health": {"garmin": ["hrv_last_night"]}}}), \
     patch("mcp_update.mcp_sql.get_health_range",
           return_value={"health": {"hrv_last_night": {
               "values": [{"date": _anchor, "value": 50.0}]}}}):
    def _raise_for_anchor(day, field, *a):
        if day == _anchor:
            raise RuntimeError("simulated failure")
    with patch("mcp_update.mcp_sql.upsert_health_baseline", side_effect=_raise_for_anchor):
        _partial_updated, _partial_failed = mcp_update._sync_health_baselines()
check("_sync_health_baselines: one failing (day, field) is counted as failed",
      _partial_failed == 1)
check("_sync_health_baselines: the rest of the pass still completes (doesn't abort)",
      _partial_updated == mcp_update.BASELINE_RECOMPUTE_DAYS - 1)

# Regression guard (found 2026-10-07 via a real-archive run): several
# health fields are categorical/text, not numeric (sleep_score_feedback,
# sleep_score_qualifier, hrv_status, hrv_feedback, confirmed via real
# boot-log output) -- statistics.mean()/stdev() raise on a non-numeric
# value, which made every single day for every one of these fields fail
# on every sync, forever (not a one-off error, a permanent log-spam
# source). Fixed by filtering non-numeric/bool values out of
# values_by_field at read time, once, rather than guarding every later
# read site separately.
with patch("mcp_update.mcp_map.get_archive_metadata",
           return_value={"data": {"date_max": _anchor}}), \
     patch("mcp_update.mcp_map.list_available_fields",
           return_value={"fields": {"health": {"garmin": ["sleep_score_feedback"]}}}), \
     patch("mcp_update.mcp_sql.get_health_range",
           return_value={"health": {"sleep_score_feedback": {"values": [
               {"date": _anchor, "value": "POSITIVE_DEEP"}]}}}):
    _calls_categorical = []
    with patch("mcp_update.mcp_sql.upsert_health_baseline",
               side_effect=lambda *a: _calls_categorical.append(a)):
        _cat_updated, _cat_failed = mcp_update._sync_health_baselines()
check("_sync_health_baselines: a categorical/text field (e.g. "
      "sleep_score_feedback) does NOT fail",
      _cat_failed == 0)
_cat_anchor_call = [c for c in _calls_categorical if c[0] == _anchor][0]
check("_sync_health_baselines: a categorical field's baseline_avg stays "
      "None (not computed, not crashed)",
      _cat_anchor_call[2] is None)


# ══════════════════════════════════════════════════════════════════════════════
#  15. clients/mcp_stats.py — anomalies() streak edge cases (v1.7.5 Block A)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_stats 15. anomalies() — streak detection edge cases")

import mcp_stats

_UNKNOWN_FIELD_RESULT = mcp_stats.anomalies("nonexistent_field", "2026-05-01", "2026-05-10")
check("anomalies: unresolvable field name -> empty outliers/streaks + error, no crash",
      _UNKNOWN_FIELD_RESULT["outliers"] == [] and _UNKNOWN_FIELD_RESULT["streaks"] == []
      and "error" in _UNKNOWN_FIELD_RESULT)

_NO_DATA_RESULT = mcp_stats.anomalies("spo2_avg", "2026-05-01", "2026-05-10")
check("anomalies: valid, registered field with no baseline entries yet -> "
      "empty outliers/streaks, no error, no crash",
      _NO_DATA_RESULT["outliers"] == [] and _NO_DATA_RESULT["streaks"] == []
      and "error" not in _NO_DATA_RESULT)

_STREAK_FIELD = "resting_heart_rate"
_STREAK_BASE = datetime.date(2026, 5, 1)


def _seed_day(offset, value, baseline_avg=50.0, flag=False):
    day = (_STREAK_BASE + datetime.timedelta(days=offset)).isoformat()
    mcp_sql.upsert_health_baseline(day, _STREAK_FIELD, baseline_avg, 40.0, 60.0, flag)
    mcp_sql.upsert_health_day(day, {
        _STREAK_FIELD: {"garmin": {
            "values": [{"date": day, "value": value}],
            "fallback": False, "source_resolution": "daily"}}}, f"cv{offset}")
    return day


# Exactly 4 consecutive "above" days — must NOT count (threshold is >=5).
for i in range(4):
    _seed_day(i, 60.0)
_seed_day(4, 50.0)  # back on the mean, breaks the run
_four_day_result = mcp_stats.anomalies(_STREAK_FIELD, _STREAK_BASE.isoformat(),
                                        (_STREAK_BASE + datetime.timedelta(days=4)).isoformat())
check("anomalies: a 4-day run does NOT count as a streak (threshold is >=5)",
      _four_day_result["streaks"] == [])

# A 6-day "below" run, interrupted by one day with a missing value in the
# middle — must NOT be stitched across the gap into one streak.
_STREAK_FIELD_2 = "sleep_duration"
for i in range(3):
    _seed_day_name = (_STREAK_BASE + datetime.timedelta(days=10 + i)).isoformat()
    mcp_sql.upsert_health_baseline(_seed_day_name, _STREAK_FIELD_2, 50.0, 40.0, 60.0, False)
    mcp_sql.upsert_health_day(_seed_day_name, {
        _STREAK_FIELD_2: {"garmin": {
            "values": [{"date": _seed_day_name, "value": 40.0}],
            "fallback": False, "source_resolution": "daily"}}}, f"g{i}")
_gap_day = (_STREAK_BASE + datetime.timedelta(days=13)).isoformat()
mcp_sql.upsert_health_baseline(_gap_day, _STREAK_FIELD_2, 50.0, 40.0, 60.0, False)
# No upsert_health_day for _gap_day — this day has a baseline but no value.
for i in range(3):
    _seed_day_name = (_STREAK_BASE + datetime.timedelta(days=14 + i)).isoformat()
    mcp_sql.upsert_health_baseline(_seed_day_name, _STREAK_FIELD_2, 50.0, 40.0, 60.0, False)
    mcp_sql.upsert_health_day(_seed_day_name, {
        _STREAK_FIELD_2: {"garmin": {
            "values": [{"date": _seed_day_name, "value": 40.0}],
            "fallback": False, "source_resolution": "daily"}}}, f"g{4 + i}")
_gap_split_result = mcp_stats.anomalies(
    _STREAK_FIELD_2, (_STREAK_BASE + datetime.timedelta(days=10)).isoformat(),
    (_STREAK_BASE + datetime.timedelta(days=16)).isoformat())
check("anomalies: a missing-value day splits a run into two shorter pieces "
      "(3+3), neither reaching the 5-day threshold",
      _gap_split_result["streaks"] == [])

# A streak that runs all the way to the last day in the requested range —
# still counted (open-ended at the query boundary, not excluded).
_STREAK_FIELD_3 = "body_battery_max"
for i in range(5):
    _seed_day_name = (_STREAK_BASE + datetime.timedelta(days=20 + i)).isoformat()
    mcp_sql.upsert_health_baseline(_seed_day_name, _STREAK_FIELD_3, 50.0, 40.0, 60.0, False)
    mcp_sql.upsert_health_day(_seed_day_name, {
        _STREAK_FIELD_3: {"garmin": {
            "values": [{"date": _seed_day_name, "value": 60.0}],
            "fallback": False, "source_resolution": "daily"}}}, f"h{i}")
_open_ended_result = mcp_stats.anomalies(
    _STREAK_FIELD_3, (_STREAK_BASE + datetime.timedelta(days=20)).isoformat(),
    (_STREAK_BASE + datetime.timedelta(days=24)).isoformat())
check("anomalies: a 5-day streak reaching the end of the query range is still counted",
      len(_open_ended_result["streaks"]) == 1 and
      len(_open_ended_result["streaks"][0]["dates"]) == 5)

# A value exactly equal to baseline_avg breaks any streak (side=None).
_STREAK_FIELD_4 = "stress_avg"
for i in range(3):
    _seed_day_name = (_STREAK_BASE + datetime.timedelta(days=30 + i)).isoformat()
    mcp_sql.upsert_health_baseline(_seed_day_name, _STREAK_FIELD_4, 50.0, 40.0, 60.0, False)
    mcp_sql.upsert_health_day(_seed_day_name, {
        _STREAK_FIELD_4: {"garmin": {
            "values": [{"date": _seed_day_name, "value": 60.0}],
            "fallback": False, "source_resolution": "daily"}}}, f"e{i}")
_equal_day = (_STREAK_BASE + datetime.timedelta(days=33)).isoformat()
mcp_sql.upsert_health_baseline(_equal_day, _STREAK_FIELD_4, 50.0, 40.0, 60.0, False)
mcp_sql.upsert_health_day(_equal_day, {
    _STREAK_FIELD_4: {"garmin": {
        "values": [{"date": _equal_day, "value": 50.0}],  # exactly == baseline_avg
        "fallback": False, "source_resolution": "daily"}}}, "e-equal")
for i in range(3):
    _seed_day_name = (_STREAK_BASE + datetime.timedelta(days=34 + i)).isoformat()
    mcp_sql.upsert_health_baseline(_seed_day_name, _STREAK_FIELD_4, 50.0, 40.0, 60.0, False)
    mcp_sql.upsert_health_day(_seed_day_name, {
        _STREAK_FIELD_4: {"garmin": {
            "values": [{"date": _seed_day_name, "value": 60.0}],
            "fallback": False, "source_resolution": "daily"}}}, f"e{4 + i}")
_equal_split_result = mcp_stats.anomalies(
    _STREAK_FIELD_4, (_STREAK_BASE + datetime.timedelta(days=30)).isoformat(),
    (_STREAK_BASE + datetime.timedelta(days=36)).isoformat())
check("anomalies: a value exactly equal to baseline_avg breaks a streak (3+3, "
      "neither half reaches 5)",
      _equal_split_result["streaks"] == [])


# ══════════════════════════════════════════════════════════════════════════════
#  16. clients/mcp_server.py — baselines()/anomalies()/gaps() registration
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_server 16. baselines()/anomalies()/gaps() — registered tool call")

mcp_sql.upsert_health_baseline("2026-06-01", "hrv_last_night", 55.0, 45.0, 65.0, False)
_ms_baselines = mcp_server.baselines("hrv_last_night", "2026-06-01", "2026-06-01")
check("mcp_server.baselines: resolves and returns the seeded entry",
      _ms_baselines["health_baselines"]["hrv_last_night"]["values"][0]["baseline_avg"] == 55.0)

_ms_anomalies = mcp_server.anomalies("hrv_last_night", "2026-06-01", "2026-06-01")
check("mcp_server.anomalies: resolves without error, returns the expected shape",
      "outliers" in _ms_anomalies and "streaks" in _ms_anomalies)

mcp_sql.upsert_structured_log_entry(
    "quality_log", "2026-06-01", {"date": "2026-06-01", "quality": "high"}, "z1")
_ms_gaps = mcp_server.gaps("health", "2026-06-01", "2026-06-01")
check("mcp_server.gaps: resolves and correctly excludes a 'high'-quality day",
      "2026-06-01" not in _ms_gaps["gaps"])


# ══════════════════════════════════════════════════════════════════════════════
#  17. clients/mcp_stats.py — correlate() (v1.7.5 Block B)
# ══════════════════════════════════════════════════════════════════════════════
#
# Real SQLite DB (same shared connection as sections 10-16), not mocked
# -- lag/Pearson/Spearman arithmetic is exactly the kind of logic a
# mock would hide bugs in (see Baustein 14's own real-archive-run
# precedent for correlate()'s sibling tools).

section("mcp_stats 17. correlate() — lag, Pearson/Spearman, cross-domain")

import math

_CORR_BASE = datetime.date(2026, 7, 1)

# A linear ramp is perfectly correlated at ANY lag (an additive shift
# doesn't change linear correlation) -- not a useful lag-discrimination
# signal. An oscillating signal is: only the lag actually used to
# construct the data should come out near-perfect.
_signal = [math.sin(i * 0.7) * 10 for i in range(30)]
for i in range(30):
    _d = (_CORR_BASE + datetime.timedelta(days=i)).isoformat()
    _payload = {"sleep_duration": {"garmin": {
        "values": [{"date": _d, "value": _signal[i]}],
        "fallback": False, "source_resolution": "daily"}}}
    if i - 3 >= 0:
        _payload["stress_avg"] = {"garmin": {
            "values": [{"date": _d, "value": _signal[i - 3]}],
            "fallback": False, "source_resolution": "daily"}}
    mcp_sql.upsert_health_day(_d, _payload, f"corr{i}")

_corr_from = _CORR_BASE.isoformat()
_corr_to = (_CORR_BASE + datetime.timedelta(days=29)).isoformat()

_r_true_lag = mcp_stats.correlate("sleep_duration", "stress_avg", _corr_from, _corr_to, lag_days=3)
check("correlate: the lag actually used to construct the data (3) is near-perfect",
      abs(_r_true_lag["pearson"] - 1.0) < 0.0001)
check("correlate: data_points reflects the real overlap after the shift (27, not 30)",
      _r_true_lag["data_points"] == 27)

_r_wrong_lag = mcp_stats.correlate("sleep_duration", "stress_avg", _corr_from, _corr_to, lag_days=0)
check("correlate: an incorrect lag (0) on an oscillating signal is clearly NOT near-perfect",
      _r_wrong_lag["pearson"] < 0.9)

# Monotonic but non-linear (x -> x^3): Spearman must be perfect (rank
# order preserved), Pearson must NOT be (the relationship isn't
# linear) -- the one check that actually distinguishes the two
# coefficients from each other, not just "both compute a number".
for i in range(1, 15):
    _d = (_CORR_BASE + datetime.timedelta(days=40 + i)).isoformat()
    mcp_sql.upsert_health_day(_d, {"resting_heart_rate": {"garmin": {
        "values": [{"date": _d, "value": float(i)}],
        "fallback": False, "source_resolution": "daily"}}}, f"nl{i}")
    mcp_sql.upsert_context_day(
        _d, {"weather": {"temperature_max": {
            "values": [{"date": _d, "value": float(i) ** 3}],
            "fallback": False, "source_resolution": "daily"}}},
        complete_sources={"weather"}, attempted_sources={"weather"})

_nl_from = (_CORR_BASE + datetime.timedelta(days=41)).isoformat()
_nl_to = (_CORR_BASE + datetime.timedelta(days=54)).isoformat()
_r_nonlinear = mcp_stats.correlate("resting_heart_rate", "temperature_max", _nl_from, _nl_to)
check("correlate: cross-domain (health field_a + context field_b) resolves correctly, no explicit domain arg",
      _r_nonlinear["data_points"] == 14)
check("correlate: Spearman is perfect for a monotonic-but-nonlinear relationship (x -> x^3)",
      _r_nonlinear["spearman"] == 1.0)
check("correlate: Pearson is NOT perfect for the same nonlinear relationship "
      "(the whole point of offering both)",
      _r_nonlinear["pearson"] < 1.0)

# wind_speed_max: the one context field with a documented multi-source
# collision -- _fetch_context_field() returns an already-flattened
# shape for it, every other context field returns one source-nested
# level deeper. correlate() must handle both, not just the common case.
for i in range(10):
    _d = (_CORR_BASE + datetime.timedelta(days=60 + i)).isoformat()
    mcp_sql.upsert_context_day(
        _d, {"brightsky": {"wind_speed_max": {
            "values": [{"date": _d, "value": float(i)}],
            "fallback": False, "source_resolution": "daily"}}},
        complete_sources={"brightsky"}, attempted_sources={"brightsky"})
    mcp_sql.upsert_health_day(_d, {"resting_heart_rate": {"garmin": {
        "values": [{"date": _d, "value": float(i)}],
        "fallback": False, "source_resolution": "daily"}}}, f"ws{i}")
_r_collision = mcp_stats.correlate(
    "resting_heart_rate", "wind_speed_max",
    (_CORR_BASE + datetime.timedelta(days=60)).isoformat(),
    (_CORR_BASE + datetime.timedelta(days=69)).isoformat())
check("correlate: wind_speed_max's flattened context shape is read correctly "
      "(not just the normal per-source-nested shape)",
      _r_collision["data_points"] == 10 and abs(_r_collision["pearson"] - 1.0) < 0.0001)

# Error paths.
_r_unknown = mcp_stats.correlate("totally_made_up_field_xyz", "resting_heart_rate",
                                  _corr_from, _corr_to)
check("correlate: an unresolvable field_a produces a field_a-prefixed error, no crash",
      "error" in _r_unknown and _r_unknown["error"].startswith("field_a:"))

for _i in range(5):
    _d = (_CORR_BASE + datetime.timedelta(days=80 + _i)).isoformat()
    mcp_sql.upsert_health_day(_d, {
        "spo2_avg": {"garmin": {
            "values": [{"date": _d, "value": 97.0}],  # constant -- zero variance
            "fallback": False, "source_resolution": "daily"}},
        "body_battery_max": {"garmin": {
            "values": [{"date": _d, "value": float(50 + _i)}],
            "fallback": False, "source_resolution": "daily"}},
    }, f"zv{_i}")
_r_zero_var = mcp_stats.correlate(
    "spo2_avg", "body_battery_max",
    (_CORR_BASE + datetime.timedelta(days=80)).isoformat(),
    (_CORR_BASE + datetime.timedelta(days=84)).isoformat())
check("correlate: zero-variance field degrades to pearson/spearman=None + a note, no crash",
      _r_zero_var["pearson"] is None and _r_zero_var["spearman"] is None
      and "not computable" in _r_zero_var.get("note", ""))

_r_bad_lag = mcp_stats.correlate("resting_heart_rate", "resting_heart_rate",
                                  _corr_from, _corr_to, lag_days=99)
check("correlate: lag_days outside [-7, 7] is rejected with an error, not silently clamped",
      "error" in _r_bad_lag)


# ══════════════════════════════════════════════════════════════════════════════
#  18. clients/mcp_server.py — correlate() registration (v1.7.5 Block B)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_server 18. correlate() — registered tool call")

_ms_correlate = mcp_server.correlate("sleep_duration", "stress_avg", _corr_from, _corr_to, lag_days=3)
check("mcp_server.correlate: resolves and returns the expected shape",
      "pearson" in _ms_correlate and "spearman" in _ms_correlate
      and abs(_ms_correlate["pearson"] - 1.0) < 0.0001)


# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════

shutil.rmtree(_TMPDIR, ignore_errors=True)

section("mcp_query_common 19. _match_field() — shared near-match step (v1.7.5.2)")

from mcp_query_common import _match_field
import mcp_health

_mf_cands = {"floors", "body_battery_events", "running_tolerance"}

check("_match_field: exact hit, input verbatim -> no substitution marker",
      _match_field("floors", "floors", _mf_cands) ==
      {"resolved_field": "floors", "field_resolved_from": None, "field_used": None})
check("_match_field: exact hit after lower-casing -> marked as substitution",
      _match_field("floors", "FLOORS", _mf_cands) ==
      {"resolved_field": "floors", "field_resolved_from": "FLOORS", "field_used": "floors"})
check("_match_field: exactly one near-match -> auto-resolved and marked",
      _match_field("floor", "floor", _mf_cands) ==
      {"resolved_field": "floors", "field_resolved_from": "floor", "field_used": "floors"})

_mf_multi = _match_field("stress_xyz", "stress_xyz", {"stress_avg", "stress_max"})
check("_match_field: several near-matches -> error + did_you_mean with all of them",
      "error" in _mf_multi and sorted(_mf_multi.get("did_you_mean", [])) == ["stress_avg", "stress_max"])
_mf_none = _match_field("zzzzzz", "zzzzzz", _mf_cands)
check("_match_field: no near-match -> error, no did_you_mean key",
      "error" in _mf_none and "did_you_mean" not in _mf_none)

# Parity with the resolver whose tail this was extracted from: for inputs that
# touch neither an alias nor an ambiguity entry, the results must be identical.
_mf_health = set(
    mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
)
for _mf_in in ["hrv_last_night", "hrv_last_nigth", "HRV_LAST_NIGHT", "zzzzzz"]:
    check(f"_match_field parity with resolve_health_field: {_mf_in!r}",
          _match_field(_mf_in.lower(), _mf_in, _mf_health) ==
          mcp_health.resolve_health_field(_mf_in))

section("mcp_sql 20. get_raw_range() — field filter (v1.7.5.2)")

import mcp_sql as _mcp_sql_raw

_grr_days = {
    "2000-01-01": {"floors": {"raw": [1]}, "daily_weigh_ins": {"raw": [2]}},
    "2000-01-02": {"floors": {"raw": [3]}},
}
with patch("mcp_sql.get_raw_fields_for_day", side_effect=lambda d: _grr_days.get(d, {})):
    _grr_all = _mcp_sql_raw.get_raw_range("2000-01-01", "2000-01-02")
    _grr_one = _mcp_sql_raw.get_raw_range("2000-01-01", "2000-01-02", field="floors")
    _grr_other = _mcp_sql_raw.get_raw_range("2000-01-01", "2000-01-02", field="daily_weigh_ins")
    _grr_none = _mcp_sql_raw.get_raw_range("2000-01-01", "2000-01-02", field="running_tolerance")

check("get_raw_range: field=None returns every cached raw field (unchanged default)",
      set(_grr_all["health"]) == {"floors", "daily_weigh_ins"})
check("get_raw_range: field='floors' returns only that field, all its days",
      set(_grr_one["health"]) == {"floors"} and
      [v["date"] for v in _grr_one["health"]["floors"]["values"]] == ["2000-01-01", "2000-01-02"])
check("get_raw_range: field='daily_weigh_ins' returns only its single day",
      set(_grr_other["health"]) == {"daily_weigh_ins"} and
      len(_grr_other["health"]["daily_weigh_ins"]["values"]) == 1)
check("get_raw_range: field with no cached data -> empty health dict, _meta still present",
      _grr_none["health"] == {} and "_meta" in _grr_none)
check("get_raw_range: filtered values keep the unwrapped raw payload",
      _grr_one["health"]["floors"]["values"][0]["raw"] == [1])

section("mcp_health 21. resolve_health_field() — raw-field pointer (v1.7.5.5)")

from mcp_field_registry import RAW_FIELD_COUNTERPARTS as _RFC

_rf_raw = set(mcp_map.list_raw_fields("health")["health"])
_rf_health = set(mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", []))
_rf_context = set()
for _rf_src in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
    _rf_context.update(_rf_src)

# Guards: the raw check sits before the near-match step, so it must never
# shadow a real health/context field, and the counterpart table must not
# drift from the registered fields.
check("raw fields: none is also a health field (raw check cannot shadow one)",
      _rf_raw.isdisjoint(_rf_health))
check("raw fields: none is also a context field",
      _rf_raw.isdisjoint(_rf_context))
check("RAW_FIELD_COUNTERPARTS: every key is a registered raw field",
      set(_RFC) <= _rf_raw)
check("RAW_FIELD_COUNTERPARTS: every counterpart is a registered health field",
      all(c in _rf_health for _cs in _RFC.values() for c in _cs))

for _rf_name in sorted(_rf_raw):
    _rf_res = mcp_health.resolve_health_field(_rf_name)
    check(f"resolve_health_field({_rf_name!r}): raw field -> error naming query_raw, no resolution",
          "query_raw" in _rf_res.get("error", "") and "resolved_field" not in _rf_res)

for _rf_name, _rf_cps in _RFC.items():
    _rf_res = mcp_health.resolve_health_field(_rf_name)
    check(f"resolve_health_field({_rf_name!r}): did_you_mean is exactly the processed counterpart(s)",
          _rf_res.get("did_you_mean") == _rf_cps)
    check(f"resolve_health_field({_rf_name!r}): error names every counterpart",
          all(repr(c) in _rf_res["error"] for c in _rf_cps))

_rf_nocp = mcp_health.resolve_health_field("lactate_threshold")
check("resolve_health_field('lactate_threshold'): no counterpart -> no did_you_mean key",
      "did_you_mean" not in _rf_nocp)
_rf_bbe = mcp_health.resolve_health_field("body_battery_events")
check("resolve_health_field('body_battery_events'): raw pointer, not the three body_battery_* near-matches",
      "query_raw" in _rf_bbe.get("error", "") and "did_you_mean" not in _rf_bbe)
check("resolve_health_field('intensity_minutes_data'): no longer silently resolved to intensity_min_moderate",
      "resolved_field" not in mcp_health.resolve_health_field("intensity_minutes_data"))

# Unchanged behaviour next to the new check
check("resolve_health_field: exact health field still resolves untouched",
      mcp_health.resolve_health_field("floors_climbed") ==
      {"resolved_field": "floors_climbed", "field_resolved_from": None, "field_used": None})
check("resolve_health_field: unrelated unknown name still gets the generic 'unknown field' error",
      mcp_health.resolve_health_field("zzzzzz").get("error") == "unknown field 'zzzzzz'")

# The pointer reaches every caller of the resolver
with patch("mcp_sql.get_health_range") as _rf_m_sql:
    _rf_qh = mcp_server.query_health("floors", _TEST_DATE, _TEST_DATE, "daily")
    _rf_m_sql.assert_not_called()
check("query_health('floors'): error with pointer + did_you_mean, health stays empty, nothing queried",
      _rf_qh.get("health") == {} and "query_raw" in _rf_qh.get("error", "")
      and _rf_qh.get("did_you_mean") == ["floors_climbed"])
_rf_bl = mcp_stats.baselines("floors", _TEST_DATE, _TEST_DATE)
check("baselines('floors'): same pointer reaches the stats tool",
      "query_raw" in _rf_bl.get("error", "") and _rf_bl.get("did_you_mean") == ["floors_climbed"])
_rf_an = mcp_stats.anomalies("lactate_threshold", _TEST_DATE, _TEST_DATE)
check("anomalies('lactate_threshold'): same pointer reaches the stats tool",
      "query_raw" in _rf_an.get("error", ""))
_rf_cor = mcp_stats._resolve_and_fetch_field("daily_weigh_ins", _TEST_DATE, _TEST_DATE)
check("_resolve_and_fetch_field('daily_weigh_ins'): health-side pointer wins over the context 'unknown field'",
      "query_raw" in _rf_cor.get("error", "") and _rf_cor.get("did_you_mean") == ["body_weight"])

section("mcp_server 22. query_raw() — processed-counterpart hint in _meta (v1.7.5.5)")

from mcp_query_common import _format_counterparts

check("_format_counterparts: quotes and joins every name",
      _format_counterparts(["a", "b"]) == "'a', 'b'" and _format_counterparts(["a"]) == "'a'")


def _qr22(raw_result, field="floors", **kwargs):
    import copy
    with patch("mcp_sql.get_raw_range", return_value=copy.deepcopy(raw_result)):
        return mcp_server.query_raw(field, "2000-01-01", "2000-01-01", **kwargs)


_qr22_values = {"health": {"x": {"values": [{"date": "2000-01-01", "raw": [1]}],
                                 "source_resolution": "raw"}}, "_meta": {}}
_qr22_empty = {"health": {}, "_meta": {}}

for _qr22_field, _qr22_cps in _RFC.items():
    for _qr22_label, _qr22_raw in (("with values", _qr22_values), ("without values", _qr22_empty)):
        _qr22_res = _qr22(_qr22_raw, field=_qr22_field)
        _qr22_hint = _qr22_res["_meta"].get("hint", "")
        check(f"query_raw({_qr22_field!r}) {_qr22_label}: hint names every counterpart and query_health",
              all(repr(c) in _qr22_hint for c in _qr22_cps) and "query_health" in _qr22_hint)
    check(f"query_raw({_qr22_field!r}): hint uses the same counterpart wording as the resolver error",
          _format_counterparts(_qr22_cps) in _qr22_res["_meta"]["hint"]
          and _format_counterparts(_qr22_cps) in mcp_health.resolve_health_field(_qr22_field)["error"])

_qr22_nocp = _qr22(_qr22_values, field="lactate_threshold")
check("query_raw: raw field without a counterpart -> no hint",
      "hint" not in _qr22_nocp["_meta"])
check("query_raw: every raw field outside RAW_FIELD_COUNTERPARTS gets no hint",
      all("hint" not in _qr22(_qr22_values, field=_n)["_meta"] for _n in sorted(_rf_raw - set(_RFC))))

_qr22_typo = _qr22(_qr22_values, field="floor")
check("query_raw: near-match 'floor' -> hint for the resolved field, resolution marker kept",
      "floors_climbed" in _qr22_typo["_meta"].get("hint", "")
      and _qr22_typo["_meta"].get("field_resolved_from") == "floor")
check("query_raw: 'FLOORS' (case only) -> hint present",
      "floors_climbed" in _qr22(_qr22_values, field="FLOORS")["_meta"].get("hint", ""))

_qr22_meta_in = {"health": {}, "_meta": {"date_from_iso": "2000-01-01", "weekdays": {"2000-01-01": "Saturday"}}}
_qr22_kept = _qr22(_qr22_meta_in)["_meta"]
check("query_raw: hint is added next to the existing _meta keys, not instead of them",
      _qr22_kept.get("date_from_iso") == "2000-01-01" and _qr22_kept.get("weekdays") and "hint" in _qr22_kept)

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.query_raw", return_value={"health": {}, "_meta": {}}), \
     patch("mcp_sql.get_raw_range"):
    _qr22_live = mcp_server.query_raw("daily_weigh_ins", "2000-01-01", "2000-01-01", domain="health")
check("query_raw: live branch carries the same hint",
      "body_weight" in _qr22_live["_meta"].get("hint", ""))

with patch("mcp_sql.get_raw_range") as _m_sql:
    _qr22_err_unknown = mcp_server.query_raw("zzzzzz", "2000-01-01", "2000-01-01")
    _qr22_err_domain = mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain="context")
check("query_raw: error answers (unknown field, wrong domain) carry no hint",
      "hint" not in _qr22_err_unknown["_meta"] and "hint" not in _qr22_err_domain["_meta"])

section("mcp_server 23. raw-field pointer, hint and description — edge cases (v1.7.5.5)")

import mcp_field_registry as _mfr23

# Guard: the raw check sits after alias/ambiguity/bundle handling, so a raw name
# that ever appeared in one of those tables would be answered by that table first.
_e23_tables = (set(_mfr23.HEALTH_FIELD_ALIASES) | set(_mfr23.HEALTH_FIELD_AMBIGUOUS)
               | set(_mfr23.CONTEXT_FIELD_ALIASES) | set(_mfr23.CONTEXT_FIELD_AMBIGUOUS)
               | set(_mfr23._CONTEXT_CATEGORY_BUNDLES))
check("edge: no raw field name is also an alias/ambiguity/bundle key (those would pre-empt the raw check)",
      _rf_raw.isdisjoint(_e23_tables))
check("edge: every processed counterpart still resolves untouched as an exact health field",
      all(mcp_health.resolve_health_field(_c) ==
          {"resolved_field": _c, "field_resolved_from": None, "field_used": None}
          for _cs in _RFC.values() for _c in _cs))

# Case handling: the resolver lower-cases once, so the pointer names the canonical raw name.
for _e23_in in ("FLOORS", "Floors", "fLoOrS"):
    _e23_res = mcp_health.resolve_health_field(_e23_in)
    check(f"edge: resolve_health_field({_e23_in!r}) -> same raw pointer as 'floors', canonical name in the text",
          _e23_res == mcp_health.resolve_health_field("floors") and "'floors'" in _e23_res["error"])

# Empty / whitespace / padded names: no crash, no raw pointer. Ist-Stand pin: the
# resolver does not strip, so a padded raw name is a plain unknown field.
for _e23_in in ("", " ", " floors ", "floors\n", "\tfloors"):
    _e23_res = mcp_health.resolve_health_field(_e23_in)
    check(f"edge: resolve_health_field({_e23_in!r}) -> generic unknown field, no raw pointer, no crash",
          _e23_res.get("error", "").startswith("unknown field") and "query_raw" not in _e23_res["error"])

# Ist-Stand pin (ROADMAP candidate): singular/typo of a raw name is below the
# near-match cutoff against the HEALTH fields and is not an exact raw name, so
# the raw pointer does not fire.
for _e23_in in ("floor", "daily_weigh_in", "lactate_threshhold"):
    _e23_res = mcp_health.resolve_health_field(_e23_in)
    check(f"edge: resolve_health_field({_e23_in!r}) (typo/singular) -> still the generic unknown field",
          _e23_res.get("error", "").startswith("unknown field") and "query_raw" not in _e23_res["error"])

# Runtime drift of the raw list: the pointer disappears cleanly, nothing breaks.
for _e23_label, _e23_list in (("raw list empty", []),
                              ("'floors' no longer registered", sorted(_rf_raw - {"floors"}))):
    with patch("maps.mcp_map.list_raw_fields", return_value={"health": _e23_list}):
        _e23_res = mcp_health.resolve_health_field("floors")
        _e23_qr = _qr22(_qr22_values, field="floors")
    check(f"edge: {_e23_label} -> resolve_health_field('floors') is the generic unknown field",
          _e23_res.get("error", "").startswith("unknown field") and "query_raw" not in _e23_res["error"])
    check(f"edge: {_e23_label} -> query_raw('floors') is an unknown-field error with no hint, nothing queried",
          "error" in _e23_qr and _e23_qr["health"] == {} and "hint" not in _e23_qr["_meta"])

# query_raw with odd names
_e23_empty = _qr22(_qr22_values, field="")
check("edge: query_raw('') -> unknown-field error, health empty, no hint",
      "error" in _e23_empty and _e23_empty["health"] == {} and "hint" not in _e23_empty["_meta"])
_e23_pad = _qr22(_qr22_values, field=" floors")
check("edge: query_raw(' floors') (padded) -> auto-resolved to 'floors', marked, hint present",
      _e23_pad["_meta"].get("field_resolved_from") == " floors"
      and _e23_pad["_meta"].get("field_used") == "floors" and "hint" in _e23_pad["_meta"])
_e23_dom = _qr22(_qr22_values, field="floors", domain="HEALTH")
check("edge: query_raw(domain='HEALTH') -> hint present",
      "hint" in _e23_dom["_meta"])

# Ist-Stand pin (ROADMAP candidate): the reverse direction. A processed name given
# to query_raw is a plain unknown field with no pointer to query_health, except
# where it happens to be a single near-match of a raw name.
for _e23_in in ("floors_climbed", "body_weight"):
    _e23_res = _qr22(_qr22_values, field=_e23_in)
    check(f"edge: query_raw({_e23_in!r}) (processed name) -> unknown-field error, no hint, nothing returned",
          "error" in _e23_res and _e23_res["health"] == {} and "hint" not in _e23_res["_meta"])
_e23_im = _qr22(_qr22_values, field="intensity_min_moderate")
check("edge: query_raw('intensity_min_moderate') -> resolved to the raw field, marked, hint names the processed fields",
      _e23_im["_meta"].get("field_used") == "intensity_minutes_data"
      and "'intensity_min_moderate'" in _e23_im["_meta"].get("hint", ""))

# correlate: a raw name on either side returns the error naming that side. field_a
# is resolved and read before field_b is looked at (Ist-Stand), so a raw name in
# field_b errors only after field_a's data was fetched; a raw name in field_a
# errors before anything is read.
with patch("mcp_sql.get_health_range") as _e23_m_sql:
    _e23_cor_a = mcp_stats.correlate("floors", "steps_total", _TEST_DATE, _TEST_DATE)
    _e23_called_a = _e23_m_sql.called
check("edge: correlate('floors', 'steps_total') -> error names field_a and the raw pointer, no data read",
      _e23_cor_a.get("error", "").startswith("field_a:") and "query_raw" in _e23_cor_a["error"]
      and "'floors'" in _e23_cor_a["error"] and not _e23_called_a)
with patch("mcp_sql.get_health_range", return_value={"health": {"steps_total": {"values": []}}}):
    _e23_cor_b = mcp_stats.correlate("steps_total", "lactate_threshold", _TEST_DATE, _TEST_DATE)
check("edge: correlate('steps_total', 'lactate_threshold') -> error names field_b and the raw pointer",
      _e23_cor_b.get("error", "").startswith("field_b:") and "query_raw" in _e23_cor_b["error"]
      and "'lactate_threshold'" in _e23_cor_b["error"])
check("edge: correlate with a raw name that has a counterpart -> did_you_mean carries it",
      mcp_stats.correlate("daily_weigh_ins", "steps_total", _TEST_DATE, _TEST_DATE).get("did_you_mean")
      == ["body_weight"])

# description: the hint wording is not part of the parsed field-name block and the
# wrong-claim sentence is gone (checked in 8a-ter); the live description stays within limits
check("edge: query_raw description still within the 2000-character cap after the additions",
      len(_tool_desc["query_raw"]) <= 2000)


# ══════════════════════════════════════════════════════════════════════════════
#  15. clients/mcp_update.py — a bulk-only day reaches the cache with its series (v1.7.6)
# ══════════════════════════════════════════════════════════════════════════════

section("mcp_update 15. _sync_health_days() — heart-rate series from the bulk store")

_BD = "2026-06-10"
_BT = int(datetime.datetime(2026, 6, 9, 22, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)
cfg.BULK_RAW_DIR.mkdir(parents=True, exist_ok=True)
(cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{_BD}.json").write_text(json.dumps({
    "date": _BD, "schema_version": 1, "utc_offset_hours": 2.0, "utc_offset_end_hours": 2.0, "dst_transition": False,
    "sections": {"intraday": {"heart_rate": {"count": 2, "values": [[_BT, 61], [_BT + 60000, 63]]}}}}), encoding="utf-8")

_sync_log = {"data": {"days": [{"date": _BD, "quality": "standard", "last_checked": "2026-10-17"}]}}


def _sync_meta(kind, date_from=None, date_to=None):
    return {"stats": {"data": {"date_min": _BD, "date_max": _BD}}, "quality_log": _sync_log}[kind]


with patch("mcp_update.mcp_map.get_archive_metadata", side_effect=_sync_meta), \
     patch("mcp_update.mcp_map.list_available_fields", return_value={"fields": {"health": {"garmin": ["heart_rate_series"]}}}), \
     patch("mcp_update._update_day_status"):
    _bulk_sync = mcp_update._sync_health_days()
_cached = mcp_sql.get_health_range(_BD, _BD, field="heart_rate_series")["health"]["heart_rate_series"]["values"]
check("sync: a day that only the bulk store has is cached with its series and series_source 'bulk'",
      _bulk_sync == (1, 0) and len(_cached) == 1 and _cached[0]["series_source"] == "bulk"
      and [p["value"] for p in _cached[0]["series"]] == [61.0, 63.0]
      and _cached[0]["series"][0]["ts"] == "2026-06-10T00:00:00")
with patch("mcp_update.mcp_map.get_archive_metadata", side_effect=_sync_meta), \
     patch("mcp_update.mcp_map.list_available_fields", return_value={"fields": {"health": {"garmin": ["heart_rate_series"]}}}), \
     patch("mcp_update._update_day_status"):
    _again_sync = mcp_update._sync_health_days()
check("sync: the same last_checked again -> nothing is read again", _again_sync == (0, 0))
_sync_log["data"]["days"][0]["last_checked"] = "2026-10-18"
with patch("mcp_update.mcp_map.get_archive_metadata", side_effect=_sync_meta), \
     patch("mcp_update.mcp_map.list_available_fields", return_value={"fields": {"health": {"garmin": ["heart_rate_series"]}}}), \
     patch("mcp_update._update_day_status"):
    _marked_sync = mcp_update._sync_health_days()
check("sync: a new last_checked (what the bulk import sets) makes the cache read the day again", _marked_sync == (1, 0))

summary()
