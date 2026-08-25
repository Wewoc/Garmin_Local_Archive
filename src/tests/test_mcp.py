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

check("mcp_server: exactly six tools registered", len(_registered_tools) == 6)
check("mcp_server: registered tool names match mcp_map.py 1:1",
      _registered_names == {
          "query_health", "query_context", "query_fit_activities",
          "query_raw", "get_archive_metadata", "list_available_fields",
      })

# ── 8b. Delegation — each wrapper calls the matching mcp_map function ─────────
#
# The @mcp.tool()-decorated functions in mcp_server.py stay directly callable
# from Python (confirmed against mcp.server.fastmcp.FastMCP, v1.x — unlike
# the unrelated standalone "fastmcp" package's v2/v3 line, which wraps the
# decorated function in a non-callable Tool object). No ".fn" access needed.
# Each wrapper is patched at its call site (maps.mcp_map.<name>, the module
# mcp_server.py imports as a whole via "from maps import mcp_map") to verify
# it forwards arguments unchanged, without exercising the real broker chain
# a second time — that correctness is already covered by Sections 1-6 above.
from unittest.mock import patch

with patch("maps.mcp_map.query_health", return_value={"health": {}, "_meta": {}}) as _m:
    mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
    _m.assert_called_once_with("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("mcp_server.query_health: delegates to mcp_map.query_health unchanged", True)

with patch("maps.mcp_map.query_context", return_value={"context": {}, "_meta": {}}) as _m:
    mcp_server.query_context("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
    _m.assert_called_once_with("temperature_max", _TEST_DATE, _TEST_DATE, "daily")
check("mcp_server.query_context: delegates to mcp_map.query_context unchanged", True)

with patch("maps.mcp_map.query_fit_activities", return_value={"fit": {}, "_meta": {}}) as _m:
    mcp_server.query_fit_activities("some_field", _TEST_DATE, _TEST_DATE, "daily")
    _m.assert_called_once_with("some_field", _TEST_DATE, _TEST_DATE, "daily")
check("mcp_server.query_fit_activities: delegates to mcp_map.query_fit_activities unchanged", True)

with patch("maps.mcp_map.query_raw", return_value={"health": {}, "_meta": {}}) as _m:
    mcp_server.query_raw("floors", "2000-01-01", "2000-01-01", domain="health")
    _m.assert_called_once_with("floors", "2000-01-01", "2000-01-01", domain="health")
check("mcp_server.query_raw: delegates to mcp_map.query_raw unchanged", True)

with patch("maps.mcp_map.get_archive_metadata", return_value={"data": {}, "error": None}) as _m:
    mcp_server.get_archive_metadata("stats")
    _m.assert_called_once_with("stats")
check("mcp_server.get_archive_metadata: delegates to mcp_map.get_archive_metadata unchanged", True)

with patch("maps.mcp_map.list_available_fields", return_value={"domains": [], "metadata_kinds": [], "fields": {}}) as _m:
    mcp_server.list_available_fields(domain="health")
    _m.assert_called_once_with("health")
check("mcp_server.list_available_fields: delegates to mcp_map.list_available_fields unchanged", True)

# ── 8c. Return value pass-through — wrapper returns exactly what mcp_map returns ──
_dummy_result = {"health": {"garmin": {"values": [], "fallback": False, "source_resolution": "daily"}}, "_meta": {}}
with patch("maps.mcp_map.query_health", return_value=_dummy_result):
    _wrapper_result = mcp_server.query_health("hrv_last_night", _TEST_DATE, _TEST_DATE, "daily")
check("mcp_server.query_health: return value passed through unchanged",
      _wrapper_result == _dummy_result)


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
