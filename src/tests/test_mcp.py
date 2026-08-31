#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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

import json
import os
import sys
import shutil
import tempfile
import logging
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

_CONTEXT_FIXTURE_DIR = cfg.CONTEXT_WEATHER_DIR
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
check("mcp_server: exactly seven tools registered", len(_registered_tools) == 7)
check("mcp_server: registered tool names match mcp_map.py 1:1, plus refresh_cache",
      _registered_names == {
          "query_health", "query_context", "query_fit_activities",
          "query_raw", "get_archive_metadata", "list_available_fields",
          "refresh_cache",
      })

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
#        finding — Timo: "ich glaube der ist nur so gut weil wir viel neu
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
# "sunshine_duratio" (missing trailing "n") was chosen after TWO earlier
# candidates both failed this same check during the v1.7.1.4 session,
# for the same underlying reason — verify a typo's uniqueness against
# the REAL, full field registry (25 fields across all four context
# sources) before trusting it, not against a small hand-picked subset:
#   - "temperatur_max" matched both temperature_max and temperature_min
#     (shared long prefix).
#   - "precipitaton" matched both precipitation (weather) and
#     precipitation_sum (brightsky) — two sources register
#     similarly-named fields for the same real-world quantity.
# "sunshine_duratio" has no similarly-named sibling anywhere in the
# registry (sunshine_sum exists under brightsky, but is not a close
# character-level match to this specific typo), so it resolves to
# exactly one candidate at cutoff=0.8.
with patch("mcp_sql.get_context_range", return_value={"context": {"weather": {}}, "_meta": {}}) as _m_sql, \
     patch("maps.mcp_map.query_context") as _m_live:
    _qc_typo = mcp_server.query_context("sunshine_duratio", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_called_once_with(_TEST_DATE, _TEST_DATE, field="sunshine_duration")
    _m_live.assert_not_called()
check("query_context unknown-field: typo auto-resolved to registered field", True)
check("query_context unknown-field: _meta.field_resolved_from set to caller's original input",
      _qc_typo.get("_meta", {}).get("field_resolved_from") == "sunshine_duratio")
check("query_context unknown-field: _meta.field_used set to the resolved field",
      _qc_typo.get("_meta", {}).get("field_used") == "sunshine_duration")

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
    _m_sql.assert_called_once_with("2000-01-01", "2000-01-01")
    _m_live.assert_not_called()
check("mcp_server.query_raw: SQLite branch calls mcp_sql.get_raw_range, not mcp_map", True)

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

# ── 8d. Delegation, live branch — forcing _route_query() to "live" must
#        route every wrapper to mcp_map instead, with mcp_sql untouched.
#        This is the branch the placeholder never actually returns today,
#        but the weiche's whole purpose (per the module comment) is that
#        a future real heuristic only changes _route_query()'s body, never
#        any call site — this section is what proves that promise holds
#        structurally, not just in the comment.

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.query_health", return_value={"health": {}, "_meta": {}}) as _m_live, \
     patch("mcp_sql.get_health_range") as _m_sql:
    mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m_live.assert_called_once_with("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
check("mcp_server.query_health: live branch calls mcp_map.query_health, not mcp_sql", True)

with patch("mcp_server._route_query", return_value="live"), \
     patch("maps.mcp_map.query_context", return_value={"context": {}, "_meta": {}}) as _m_live, \
     patch("mcp_sql.get_context_range") as _m_sql:
    mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m_live.assert_called_once_with("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m_sql.assert_not_called()
check("mcp_server.query_context: live branch calls mcp_map.query_context, not mcp_sql", True)

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

def _fake_pollen_range(date_from, date_to, field=None):
    return {"context": {"pollen": {field: {
        "values": [{"date": _TEST_DATE, "value": 12.5}],
        "fallback": False, "source_resolution": "daily",
    }}}, "_meta": {"weekday_table": {}}}

with patch("mcp_sql.get_context_range", side_effect=_fake_pollen_range) as _m_sql:
    _qc_pollen = mcp_server.query_context("pollen", _TEST_DATE, _TEST_DATE, "daily")
    check("query_context bundle 'pollen': mcp_sql called once per registered field",
          _m_sql.call_count == len(_pollen_fields))
check("query_context bundle 'pollen': every field present in flat result",
      set(_qc_pollen["context"].keys()) == set(_pollen_fields))
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
#  Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════

shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
