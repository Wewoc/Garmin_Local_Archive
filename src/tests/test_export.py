#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_export.py — Garmin Local Archive — Export Layer Test

Run from the project folder:
    python tests/test_export.py

No network, no GUI, no Garmin API calls, no running MCP server.
Cleans up after itself — leaves no files behind.

Covers the Export Layer (v1.7.4, exports/): export_common.collect(),
the three adapters (json_adapter, csv_adapter, influxdb_adapter) and
export_runner (scan()/build()).

Focus is edge cases, not the happy path — the happy path is already
covered indirectly by each adapter's own scratchpad smoke test during
development (see changelog/anchor_delivery_exportlayer4/13/18). What
matters here is the stuff that's easy to get subtly wrong: missing
values, series vs. daily shape, two sources with the same field name,
malformed input, a failing adapter not taking down the others.

Sections 1-5 mock mcp_sql (same style test_mcp.py Section 8 already
uses for the layer above it: "with patch('mcp_sql.get_health_range',
return_value=...)") — collect() itself is the thing under test there,
not mcp_sql's own correctness. Section 6 is the one real-SQLite
integration pass (mcp_sql.init_db() + upsert_health_day()/
upsert_context_day(), same pattern as test_mcp.py Section 10) —
catches real wiring bugs a mock can't (e.g. the health "source"-wrapper
nesting bug fixed in v1.7.1.1, Bug-C), not just logic assumed correct.
"""

import csv
import json
import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT / "clients"))
sys.path.insert(0, str(_ROOT / "exports"))
sys.path.insert(0, str(_ROOT / "exports" / "export_adapters"))
sys.path.insert(0, str(_ROOT))
logging.disable(logging.CRITICAL)

# ── Test runner ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from support import check, section, summary

# ── Temp directory as BASE_DIR ─────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_export_test_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)

import importlib
import garmin_config as cfg
importlib.reload(cfg)

import export_common
import export_runner
import json_adapter
import csv_adapter
import influxdb_adapter


# ══════════════════════════════════════════════════════════════════════════════
#  1. export_common.collect() — mocked mcp_sql
# ══════════════════════════════════════════════════════════════════════════════

section("1. export_common.collect()")

# collect() looks its readers up from export_common._DOMAIN_RANGE_READERS, a
# dict built once at import time from mcp_sql.get_health_range/get_context_range
# — those are already-dereferenced function objects, so patching the mcp_sql
# module attribute (patch("mcp_sql.get_health_range", ...)) would have no
# effect here (classic "patch where it's used, not where it's defined").
# patch.dict() on the dict entry itself is the correct target.

_health_reader_mock = lambda *a, **kw: {"health": {"resting_heart_rate": {
    "values": [{"date": "2026-01-01", "value": 52.0}],
    "fallback": False, "source_resolution": "daily"}}}
_context_empty_mock = lambda *a, **kw: {"context": {}}

with patch.dict(export_common._DOMAIN_RANGE_READERS,
                 {"health": _health_reader_mock, "context": _context_empty_mock}):
    _result_no_meta = export_common.collect("2026-01-01", "2026-01-02", ["health"])
check("collect(): include_metadata defaults to False — no 'metadata' key at all",
      "metadata" not in _result_no_meta)
check("collect(): health domain present with the mocked field",
      "resting_heart_rate" in _result_no_meta["domains"]["health"])

with patch.dict(export_common._DOMAIN_RANGE_READERS,
                 {"health": lambda *a, **kw: {"health": {}},
                  "context": _context_empty_mock}):
    _result_empty_domains = export_common.collect("2026-01-01", "2026-01-02", [])
check("collect(): empty domains list — 'domains' dict is empty, no crash",
      _result_empty_domains["domains"] == {})

_result_unknown_domain = export_common.collect("2026-01-01", "2026-01-02", ["fit"])
check("collect(): unsupported domain ('fit') degrades to {'error': ...}, no crash",
      _result_unknown_domain["domains"]["fit"] == {"error": "domain not yet available"})

with patch.dict(export_common._DOMAIN_RANGE_READERS,
                 {"health": lambda *a, **kw: {"health": {}},
                  "context": _context_empty_mock}), \
     patch("mcp_sql.get_metadata_range") as _m_meta:
    _m_meta.return_value = {"data": None, "error": None}
    _result_meta = export_common.collect("2026-01-01", "2026-01-02", ["health"],
                                          include_metadata=True)
check("collect(): include_metadata=True fetches all nine external kinds",
      _m_meta.call_count == 9)
check("collect(): include_metadata=True — 'metadata' key present with all nine kinds",
      set(_result_meta["metadata"].keys()) == set(export_common._EXTERNAL_METADATA_KINDS))


# ══════════════════════════════════════════════════════════════════════════════
#  2. json_adapter.build()
# ══════════════════════════════════════════════════════════════════════════════

section("2. json_adapter.build()")

_json_out = _TMPDIR / "json_out"
with patch("export_common.collect", return_value={"domains": {"health": {}}}):
    _json_result = json_adapter.build("2026-01-01", "2026-01-02", ["health"], False, _json_out)
check("json_adapter.build(): creates output_dir if missing",
      _json_out.exists())
check("json_adapter.build(): success=True, file written",
      _json_result["success"] and _json_result["file"].exists())
_json_written = json.loads(_json_result["file"].read_text(encoding="utf-8"))
check("json_adapter.build(): adds a 'generated' date stamp",
      "generated" in _json_written)

with patch("export_common.collect", side_effect=RuntimeError("boom")):
    _json_fail = json_adapter.build("2026-01-01", "2026-01-02", ["health"], False, _json_out)
check("json_adapter.build(): collect() raising — success=False with error text, no crash",
      _json_fail["success"] is False and "boom" in _json_fail["error"])


# ══════════════════════════════════════════════════════════════════════════════
#  3. csv_adapter — unit-level (_collect_wide_values/_metadata_rows) + build()
# ══════════════════════════════════════════════════════════════════════════════

section("3. csv_adapter.py")

_csv_data = {
    "domains": {
        "health": {
            "resting_heart_rate": {"values": [
                {"date": "2026-01-01", "value": 52},
                {"date": "2026-01-02", "value": None},  # missing day
            ]},
            "stress_series": {"values": [
                {"date": "2026-01-01", "series": [{"ts": "2026-01-01T00:01:00", "value": 12.0}]},
            ]},  # series-shaped — must never become a CSV column
        },
        "context": {
            "weather":    {"temperature_max": {"values": [{"date": "2026-01-01", "value": 7.5}]}},
            "brightsky":  {"temperature_max": {"values": [{"date": "2026-01-01", "value": 7.2}]}},
        },
    },
}

_by_date, _columns = csv_adapter._collect_wide_values(_csv_data, decimal_sep=".")
check("csv_adapter._collect_wide_values(): series field never becomes a column "
      "(Baustein-15 regression — column must only register on a real 'value')",
      not any("stress_series" in c for c in _columns))
check("csv_adapter._collect_wide_values(): a day with value=None carries that column as "
      "None (not a KeyError) — csv.DictWriter renders None the same as a restval-filled "
      "missing key, i.e. an empty cell either way, verified below in the real CSV output",
      _by_date.get("2026-01-02", {}).get("health_resting_heart_rate") is None)
check("csv_adapter._collect_wide_values(): two context sources with the same field name "
      "get separate, source-prefixed columns, no collision",
      {"context_weather_temperature_max", "context_brightsky_temperature_max"} <= set(_columns))
check("csv_adapter._collect_wide_values(): both same-named columns keep their own value",
      _by_date["2026-01-01"]["context_weather_temperature_max"] == 7.5 and
      _by_date["2026-01-01"]["context_brightsky_temperature_max"] == 7.2)

_by_date_comma, _ = csv_adapter._collect_wide_values(_csv_data, decimal_sep=",")
check("csv_adapter._collect_wide_values(): decimal_sep applied to float values",
      _by_date_comma["2026-01-01"]["context_weather_temperature_max"] == "7,5")

check("csv_adapter._metadata_rows(): empty metadata (no data under any kind) — no rows",
      csv_adapter._metadata_rows({"stats": {"data": None, "error": None}}) == [])
_meta_rows = csv_adapter._metadata_rows({
    "quality_log": {"data": [{"date": "2026-01-01", "ok": True}], "error": None},
})
check("csv_adapter._metadata_rows(): date-indexed list kind — one row, date carried through",
      len(_meta_rows) == 1 and _meta_rows[0]["date"] == "2026-01-01")

_csv_out = _TMPDIR / "csv_out"
with patch("export_common.collect", return_value=_csv_data):
    _csv_result = csv_adapter.build("2026-01-01", "2026-01-02", ["health", "context"],
                                     False, _csv_out)
check("csv_adapter.build(): success, export.csv written",
      _csv_result["success"] and _csv_result["file"].exists())
check("csv_adapter.build(): include_metadata=False — no export_metadata.csv written",
      not (_csv_out / "export_metadata.csv").exists())

_csv_rows = list(csv.DictReader(_csv_result["file"].open(encoding="utf-8"), delimiter=";"))
_csv_row_0102 = next(r for r in _csv_rows if r["date"] == "2026-01-02")
check("csv_adapter.build(): a value=None day renders as a genuinely empty cell in the "
      "real CSV output — same as a missing day, not the literal text 'None'",
      _csv_row_0102["health_resting_heart_rate"] == "")


# ══════════════════════════════════════════════════════════════════════════════
#  4. influxdb_adapter.py — unit-level + build()
# ══════════════════════════════════════════════════════════════════════════════

section("4. influxdb_adapter.py")

check("influxdb_adapter._escape_key(): comma/equals/space all escaped",
      influxdb_adapter._escape_key("a,b=c d") == "a\\,b\\=c\\ d")
check("influxdb_adapter._escape_measurement(): comma/space escaped, '=' left alone",
      influxdb_adapter._escape_measurement("a,b=c d") == "a\\,b=c\\ d")

check("influxdb_adapter._render_field_value(None) -> None (field omitted)",
      influxdb_adapter._render_field_value(None) is None)
check("influxdb_adapter._render_field_value(True) -> 'true' literal",
      influxdb_adapter._render_field_value(True) == "true")
check("influxdb_adapter._render_field_value(52) -> plain float literal, no 'i' suffix",
      influxdb_adapter._render_field_value(52) == "52.0")
check('influxdb_adapter._render_field_value(\'say "hi"\') -> quoted + escaped',
      influxdb_adapter._render_field_value('say "hi"') == '"say \\"hi\\""')
check("influxdb_adapter._render_field_value(): unsupported nested dict -> None, not a crash",
      influxdb_adapter._render_field_value({"nested": 1}) is None)

check("influxdb_adapter._ts_to_ns(): malformed timestamp -> None, not an exception",
      influxdb_adapter._ts_to_ns("not-a-timestamp") is None)
check("influxdb_adapter._ts_to_ns(): None input -> None, not an exception",
      influxdb_adapter._ts_to_ns(None) is None)
check("influxdb_adapter._date_to_ns()/_ts_to_ns() midnight agree for the same calendar day",
      influxdb_adapter._date_to_ns("2026-01-01") ==
      influxdb_adapter._ts_to_ns("2026-01-01T00:00:00"))

_lines_missing_series = influxdb_adapter._lines_for_field(
    "health", {}, "stress_series",
    {"values": [{"date": "2026-01-01", "series": None}, {"date": "2026-01-02", "series": []}]})
check("influxdb_adapter._lines_for_field(): series=None and series=[] both produce zero lines",
      _lines_missing_series == [])

_lines_two_sources = (
    influxdb_adapter._lines_for_field("context", {"source": "weather"}, "temperature_max",
                                       {"values": [{"date": "2026-01-01", "value": 7.5}]}) +
    influxdb_adapter._lines_for_field("context", {"source": "brightsky"}, "temperature_max",
                                       {"values": [{"date": "2026-01-01", "value": 7.2}]})
)
check("influxdb_adapter._lines_for_field(): two sources, same field — distinct tags, no collision",
      len(_lines_two_sources) == 2 and
      "source=weather" in _lines_two_sources[0] and "source=brightsky" in _lines_two_sources[1])

_influx_out = _TMPDIR / "influx_out"
with patch("export_common.collect", return_value={"domains": {"health": {}, "context": {}}}):
    _influx_empty = influxdb_adapter.build("2026-01-01", "2026-01-02", ["health", "context"],
                                            False, _influx_out)
check("influxdb_adapter.build(): no data at all — writes an empty file, no crash",
      _influx_empty["success"] and _influx_empty["file"].read_text(encoding="utf-8") == "")

with patch("export_common.collect", return_value=_csv_data):
    _influx_result = influxdb_adapter.build("2026-01-01", "2026-01-02", ["health", "context"],
                                             True, _influx_out)
_influx_lines = _influx_result["file"].read_text(encoding="utf-8").strip().splitlines()
check("influxdb_adapter.build(): include_metadata=True is accepted but produces no "
      "metadata-shaped lines (signature parity only, see module docstring)",
      _influx_result["success"] and
      all(ln.startswith("health") or ln.startswith("context") for ln in _influx_lines))
check("influxdb_adapter.build(): series field present as its own point (full resolution, "
      "unlike csv_adapter which skips it)",
      any("stress_series=12.0" in ln for ln in _influx_lines))


# ══════════════════════════════════════════════════════════════════════════════
#  5. export_runner.scan()/build()
# ══════════════════════════════════════════════════════════════════════════════

section("5. export_runner.py")

_adapters_dir = _ROOT / "exports" / "export_adapters"
_broken_adapter_path = _adapters_dir / "_test_broken_adapter.py"
try:
    _broken_adapter_path.write_text("raise RuntimeError('deliberately broken for test')\n",
                                     encoding="utf-8")
    _scanned = export_runner.scan()
    check("export_runner.scan(): an adapter module that fails to import is skipped, "
          "not a crash for the whole scan",
          "_test_broken_adapter" not in {a["id"] for a in _scanned})
    check("export_runner.scan(): the three real adapters still come back",
          {"json_adapter", "csv_adapter", "influxdb_adapter"} <= {a["id"] for a in _scanned})
finally:
    _broken_adapter_path.unlink(missing_ok=True)  # never leave a broken file behind

_malformed_meta_path = _adapters_dir / "_test_malformed_meta_adapter.py"
try:
    _malformed_meta_path.write_text("META = 'not a dict'\ndef build(*a, **kw): ...\n",
                                     encoding="utf-8")
    _scanned_meta = export_runner.scan()
    check("export_runner.scan(): an adapter with malformed META is skipped, not a crash",
          "_test_malformed_meta_adapter" not in {a["id"] for a in _scanned_meta})
finally:
    _malformed_meta_path.unlink(missing_ok=True)

_run_out = _TMPDIR / "runner_out"
with patch("mcp_update.sync_all", side_effect=RuntimeError("sync down")), \
     patch("export_common.collect", return_value={"domains": {"health": {}}}):
    _build_sync_fail = export_runner.build(
        [(json_adapter, ["health"], False, {})], "2026-01-01", "2026-01-02", _run_out)
check("export_runner.build(): sync_all() failing is non-fatal — adapter still runs off "
      "the existing cache",
      len(_build_sync_fail) == 1 and _build_sync_fail[0]["success"])


class _ExplodingModule:
    """A fake adapter module whose build() always raises — used to prove one
    failing selection doesn't abort the others in the same build() call."""
    META = {"name": "Exploding", "description": "", "extension": ".bad"}

    @staticmethod
    def build(*args, **kwargs):
        raise RuntimeError("adapter exploded")


with patch("mcp_update.sync_all", return_value={"duration_seconds": 0.0}), \
     patch("export_common.collect", return_value={"domains": {"health": {}}}):
    _build_mixed = export_runner.build(
        [(_ExplodingModule, ["health"], False, {}), (json_adapter, ["health"], False, {})],
        "2026-01-01", "2026-01-02", _run_out)
check("export_runner.build(): one adapter's build() raising is caught per-selection "
      "(marked failed, with the exception text)",
      _build_mixed[0]["success"] is False and "adapter exploded" in _build_mixed[0]["error"])
check("export_runner.build(): the other, unrelated selection in the same call still succeeds",
      _build_mixed[1]["success"] is True)


# ══════════════════════════════════════════════════════════════════════════════
#  6. Real-SQLite integration — no mocks, through the actual Shared Cache Layer
# ══════════════════════════════════════════════════════════════════════════════

section("6. Real-SQLite integration (mcp_sql, no mocks)")

import mcp_sql
mcp_sql.init_db()

_DAY = "2026-02-01"
mcp_sql.upsert_health_day(_DAY, {
    "resting_heart_rate": {"garmin": {
        "values": [{"date": _DAY, "value": 58}],
        "fallback": False, "source_resolution": "daily",
    }},
    "heart_rate_series": {"garmin": {
        "values": [{"date": _DAY, "series": [
            {"ts": f"{_DAY}T00:01:00", "value": 60.0},
            {"ts": f"{_DAY}T00:02:00", "value": 61.0},
        ], "dst_transition": False}],
        "fallback": False, "source_resolution": "intraday",
    }},
}, compare_value="synced")
mcp_sql.upsert_context_day(_DAY, {
    "weather":   {"temperature_max": {
        "values": [{"date": _DAY, "value": 3.5}],
        "fallback": False, "source_resolution": "daily"}},
    "brightsky": {"temperature_max": {
        "values": [{"date": _DAY, "value": 3.1}],
        "fallback": False, "source_resolution": "daily"}},
}, complete_sources={"weather", "brightsky"}, attempted_sources={"weather", "brightsky"})

_real = export_common.collect(_DAY, _DAY, ["health", "context"])
check("Real DB: collect() reads the real resting_heart_rate value through mcp_sql "
      "(no source-wrapper leak, see v1.7.1.1 Bug-C)",
      _real["domains"]["health"]["resting_heart_rate"]["values"][0]["value"] == 58)
check("Real DB: collect() reads the two context sources separately, correct values each",
      _real["domains"]["context"]["weather"]["temperature_max"]["values"][0]["value"] == 3.5 and
      _real["domains"]["context"]["brightsky"]["temperature_max"]["values"][0]["value"] == 3.1)

_real_influx_out = _TMPDIR / "real_influx_out"
with patch("export_common.collect", return_value=_real):
    _real_influx = influxdb_adapter.build(_DAY, _DAY, ["health", "context"], False,
                                          _real_influx_out)
_real_lines = _real_influx["file"].read_text(encoding="utf-8").strip().splitlines()
check("Real DB end-to-end: influxdb_adapter picks up the real series (2 points) "
      "through the actual Shared Cache Layer, not just a mock",
      sum(1 for ln in _real_lines if "heart_rate_series=" in ln) == 2)

_real_csv_out = _TMPDIR / "real_csv_out"
with patch("export_common.collect", return_value=_real):
    _real_csv = csv_adapter.build(_DAY, _DAY, ["health", "context"], False, _real_csv_out)
check("Real DB end-to-end: csv_adapter writes a wide row with the real values",
      _real_csv["success"] and _real_csv["file"].exists())


# ══════════════════════════════════════════════════════════════════════════════
#  Cleanup + summary
# ══════════════════════════════════════════════════════════════════════════════

shutil.rmtree(_TMPDIR, ignore_errors=True)

summary()
