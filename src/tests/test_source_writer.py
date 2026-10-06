#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_source_writer.py — garmin_source_writer

Run from the project folder:
    python tests/test_source_writer.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
from pathlib import Path

from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  D. garmin_source_writer (v1.6.0.2)
# ══════════════════════════════════════════════════════════════════════════════
section("D. garmin_source_writer (v1.6.0.2)")
import garmin_source_writer as source_writer
importlib.reload(source_writer)

# ── cfg paths ─────────────────────────────────────────────────────────────────
check("SOURCE_DIR derived",
      cfg.SOURCE_DIR == _TMPDIR / "garmin_data" / "source")
check("SOURCE_API_LOG derived",
      cfg.SOURCE_API_LOG == _TMPDIR / "garmin_data" / "log" / "source_api_log.json")

# ── garmin_merge — additive field merge (v1.6.3 backfill foundation) ────────
import garmin_merge as _gm

_gm_raw_absent    = {"date": "2024-05-10", "heart_rates": {"restingHeartRate": 55}}
_gm_merged_absent = _gm.merge_field(_gm_raw_absent, "steps", [{"steps": 100}])
check("merge_field: absent field → added",        _gm_merged_absent.get("steps") == [{"steps": 100}])
check("merge_field: does not mutate input",       "steps" not in _gm_raw_absent)
check("merge_field: other fields preserved",      _gm_merged_absent["heart_rates"]["restingHeartRate"] == 55)

_gm_raw_present    = {"date": "2024-05-10", "steps": [{"steps": 999}]}
_gm_merged_present = _gm.merge_field(_gm_raw_present, "steps", [{"steps": 1}])
check("merge_field: existing non-empty → not overwritten",
      _gm_merged_present.get("steps") == [{"steps": 999}])

_gm_raw_empty    = {"date": "2024-05-10", "steps": []}
_gm_merged_empty = _gm.merge_field(_gm_raw_empty, "steps", [{"steps": 5}])
check("merge_field: existing empty list → overwritten",
      _gm_merged_empty.get("steps") == [{"steps": 5}])

check("merge_field: non-dict input → returned unchanged",
      _gm.merge_field(None, "steps", []) is None)

# ── patch_source_field — additive backfill into source/ + source_api_log.json ─
_psf_date = "2024-05-11"
_psf_raw  = {"date": _psf_date, "heart_rates": {"heartRateValues": [[0, 60]]}}
source_writer.write_source(_psf_raw, _psf_date)
source_writer.update_log(_psf_date, {"status": "ok", "issues": []}, ["heart_rates"], [], 100)

_psf_ok = source_writer.patch_source_field(_psf_date, "steps", [{"startGMT": "x", "steps": 42}])
check("patch_source_field: returns True",          _psf_ok is True)

_psf_file    = cfg.SOURCE_DIR / f"garmin_source_{_psf_date}.json"
_psf_content = json.loads(_psf_file.read_text(encoding="utf-8"))
check("patch_source_field: field merged into file", _psf_content.get("steps") == [{"startGMT": "x", "steps": 42}])
check("patch_source_field: original field preserved",
      _psf_content.get("heart_rates", {}).get("heartRateValues") == [[0, 60]])

_psf_log = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("patch_source_field: backfilled_fields recorded in log",
      "steps" in _psf_log.get(_psf_date, {}).get("backfilled_fields", {}))
check("patch_source_field: original log entry preserved",
      _psf_log.get(_psf_date, {}).get("validator_status") == "ok")

_psf_noop = source_writer.patch_source_field("1900-01-01", "steps", [])
check("patch_source_field: no source file → True (no-op)", _psf_noop is True)

# ── write_source: normal write ────────────────────────────────────────────────
_sw_date = "2024-05-01"
_sw_raw  = {"date": _sw_date, "heart_rates": {"restingHeartRate": 58}, "sleep": {}}
_sw_ok   = source_writer.write_source(_sw_raw, _sw_date)
import garmin_config as _sw_cfg
_sw_file = _sw_cfg.SOURCE_DIR / f"garmin_source_{_sw_date}.json"

check("write_source: returns True",        _sw_ok == True)
check("write_source: file created",        _sw_file.exists())
check("write_source: content correct",
      json.loads(_sw_file.read_text(encoding="utf-8")).get("date") == _sw_date)
check("write_source: no .tmp leftover",
      not (_sw_file.with_suffix(".json.tmp")).exists())

# ── write_source: second write overwrites (idempotent) ───────────────────────
_sw_raw2  = {"date": _sw_date, "heart_rates": {"restingHeartRate": 62}}
_sw_ok2   = source_writer.write_source(_sw_raw2, _sw_date)
check("write_source: overwrite returns True",  _sw_ok2 == True)
check("write_source: overwrite content updated",
      json.loads(_sw_file.read_text(encoding="utf-8"))
      .get("heart_rates", {}).get("restingHeartRate") == 62)

# ── write_source: non-dict input → False, no crash ───────────────────────────
check("write_source: None input → False",  source_writer.write_source(None, _sw_date) == False)
check("write_source: str input → False",   source_writer.write_source("bad", _sw_date) == False)

# ── update_log: new entry ─────────────────────────────────────────────────────
_val_ok = {"status": "ok", "issues": [], "schema_version": "1.0"}
_ul_ok  = source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["sleep", "heart_rates", "stress"],
    endpoints_failed=[],
    size_bytes=1234,
)
check("update_log: returns True",          _ul_ok == True)
check("update_log: log file created",      _sw_cfg.SOURCE_API_LOG.exists())

_sw_log = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
_sw_entry = _sw_log.get(_sw_date, {})
check("update_log: date key present",      _sw_date in _sw_log)
check("update_log: fetched_at present",    bool(_sw_entry.get("fetched_at")))
check("update_log: source = api",          _sw_entry.get("source") == "api")
check("update_log: validator_status = ok", _sw_entry.get("validator_status") == "ok")
check("update_log: endpoints_fetched set",
      "sleep" in _sw_entry.get("endpoints_fetched", []))
check("update_log: size_bytes stored",     _sw_entry.get("size_bytes") == 1234)

# ── update_log: second call same date → overwrites, no duplicate ──────────────
_val_warn = {"status": "warning", "issues": [{"type": "out_of_range", "field": "heart_rates.restingHeartRate"}], "schema_version": "1.0"}
source_writer.update_log(
    _sw_date, _val_warn,
    endpoints_fetched=["sleep", "heart_rates"],
    endpoints_failed=["stress"],
    size_bytes=999,
)
_sw_log2  = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: no duplicate — still 1 entry for date",
      list(_sw_log2.keys()).count(_sw_date) == 1)
check("update_log: overwrite: validator_status updated",
      _sw_log2.get(_sw_date, {}).get("validator_status") == "warning")
check("update_log: overwrite: endpoints_failed updated",
      "stress" in _sw_log2.get(_sw_date, {}).get("endpoints_failed", []))

# ── update_log: second date → two entries in log ──────────────────────────────
_sw_date2 = "2024-05-02"
source_writer.update_log(
    _sw_date2, _val_ok,
    endpoints_fetched=["sleep"],
    endpoints_failed=[],
    size_bytes=500,
)
_sw_log3 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: two dates → two entries",
      _sw_date in _sw_log3 and _sw_date2 in _sw_log3)

# ── update_log: intraday_present stored when raw_data provided ────────────────
_sw_raw_intraday = {
    "date": _sw_date,
    "heart_rates": {"heartRateValues": [[0, 60], [60, 65]], "restingHeartRate": 58},
    "stress": {},
}
source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=512,
    raw_data=_sw_raw_intraday,
)
_sw_log_ip = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present=True when HR values present",
      _sw_log_ip.get(_sw_date, {}).get("intraday_present") == True)

_sw_raw_no_intraday = {"date": _sw_date, "heart_rates": {"restingHeartRate": 58}}
source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=100,
    raw_data=_sw_raw_no_intraday,
)
_sw_log_ip2 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present=False when no intraday arrays",
      _sw_log_ip2.get(_sw_date, {}).get("intraday_present") == False)

source_writer.update_log(
    _sw_date, _val_ok,
    endpoints_fetched=["heart_rates"],
    endpoints_failed=[],
    size_bytes=100,
)
_sw_log_ip3 = json.loads(_sw_cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))
check("update_log: intraday_present absent when raw_data=None",
      "intraday_present" not in _sw_log_ip3.get(_sw_date, {}))

# ── garmin_source_quality — assess_source ────────────────────────────────────
import garmin_source_quality as _sq
importlib.reload(_sq)

_sq_raw_hr   = {"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}
_sq_raw_str  = {"stress": {"stressValuesArray": [[0, 30]], "bodyBatteryValuesArray": [[0, 80]]}}
_sq_raw_none = {"heart_rates": {"restingHeartRate": 58}, "stress": {}}
_sq_raw_empty= {"heart_rates": {"heartRateValues": [], "restingHeartRate": 58}}

check("assess_source: HR values → present=True",
      _sq.assess_source(_sq_raw_hr)["intraday_present"] == True)
check("assess_source: stress/BB arrays → present=True",
      _sq.assess_source(_sq_raw_str)["intraday_present"] == True)
check("assess_source: no intraday arrays → present=False",
      _sq.assess_source(_sq_raw_none)["intraday_present"] == False)
check("assess_source: empty HR list → present=False",
      _sq.assess_source(_sq_raw_empty)["intraday_present"] == False)
check("assess_source: non-dict input → present=False",
      _sq.assess_source(None)["intraday_present"] == False)

# ── garmin_source_quality — compare_source (truth table) ─────────────────────
_sq_present = {"intraday_present": True}
_sq_absent  = {"intraday_present": False}

check("compare_source: no existing → write",
      _sq.compare_source(None, _sq_present) == "write")
check("compare_source: no existing, new absent → write",
      _sq.compare_source(None, _sq_absent) == "write")
check("compare_source: existing absent, new present → write",
      _sq.compare_source(_sq_absent, _sq_present) == "write")
check("compare_source: existing absent, new absent → write",
      _sq.compare_source(_sq_absent, _sq_absent) == "write")
check("compare_source: existing present, new present → skip",
      _sq.compare_source(_sq_present, _sq_present) == "skip")
check("compare_source: existing present, new absent → skip_warn",
      _sq.compare_source(_sq_present, _sq_absent) == "skip_warn")
check("compare_source: existing unreadable → skip_warn (F-4)",
      _sq.compare_source({"unreadable": True}, _sq_present) == "skip_warn")
check("compare_source: existing unreadable, new absent → skip_warn (F-4)",
      _sq.compare_source({"unreadable": True}, _sq_absent) == "skip_warn")

# ── garmin_source_quality — assess_source_from_file ──────────────────────────
_sq_file = cfg.SOURCE_DIR / "garmin_source_2024-05-03.json"
cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
_sq_file.write_text(
    json.dumps({"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}),
    encoding="utf-8",
)
_sq_from_file = _sq.assess_source_from_file(_sq_file)
check("assess_source_from_file: file with intraday → present=True",
      _sq_from_file is not None and _sq_from_file["intraday_present"] == True)
check("assess_source_from_file: missing file → None",
      _sq.assess_source_from_file(cfg.SOURCE_DIR / "garmin_source_9999-01-01.json") is None)
_sq_file.unlink()

# ── write_source() guard — skip and skip_warn behavior ───────────────────────
_sq_guard_date = "2024-05-04"
_sq_guard_file = cfg.SOURCE_DIR / f"garmin_source_{_sq_guard_date}.json"

# Write initial high-res file
_sq_raw_good = {"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}
source_writer.write_source(_sq_raw_good, _sq_guard_date)
check("guard setup: initial write → file exists",
      _sq_guard_file.exists())

# Attempt overwrite with degraded response → skip_warn → file unchanged
_sq_raw_degraded = {"heart_rates": {"restingHeartRate": 58}}
_sq_ok = source_writer.write_source(_sq_raw_degraded, _sq_guard_date)
_sq_content = json.loads(_sq_guard_file.read_text(encoding="utf-8"))
check("guard: skip_warn → returns True (non-fatal)",
      _sq_ok == True)
check("guard: skip_warn → existing intraday file preserved",
      _sq_content.get("heart_rates", {}).get("heartRateValues") is not None)

# Attempt overwrite with another high-res response → skip → file unchanged
_sq_raw_good2 = {"heart_rates": {"heartRateValues": [[0, 70]], "restingHeartRate": 62}}
_sq_ok2 = source_writer.write_source(_sq_raw_good2, _sq_guard_date)
_sq_content2 = json.loads(_sq_guard_file.read_text(encoding="utf-8"))
check("guard: skip (freeze-when-present) → returns True",
      _sq_ok2 == True)
check("guard: skip → original intraday values preserved (not 70)",
      _sq_content2.get("heart_rates", {}).get("heartRateValues", [[0, 0]])[0][1] == 60)

_sq_guard_file.unlink()

# ── Leaf-Node check — garmin_source_quality (new leaf) ───────────────────────
import ast as _ast
_sq_src = Path(__file__).parent.parent / "garmin" / "garmin_source_quality.py"
if _sq_src.exists():
    _sq_tree     = _ast.parse(_sq_src.read_text(encoding="utf-8"))
    _sq_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_config", "garmin_source_writer",
    }
    _sq_imports = set()
    for _node in _ast.walk(_sq_tree):
        if isinstance(_node, _ast.Import):
            for _alias in _node.names:
                _sq_imports.add(_alias.name.split(".")[0])
        elif isinstance(_node, _ast.ImportFrom):
            if _node.module:
                _sq_imports.add(_node.module.split(".")[0])
    _sq_violations = _sq_imports & _sq_forbidden
    check("source_quality leaf-node: no forbidden imports",
          len(_sq_violations) == 0)
else:
    check("source_quality leaf-node: file found for AST check", False)

# ══════════════════════════════════════════════════════════════════════════════
#  D2. garmin_source_writer, garmin_source_quality — decisions by value, exact
#      file formats, failure paths and their cleanup (v1.7.4.0.3).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("D2. garmin_source_writer, garmin_source_quality — formats, failures")
from unittest.mock import patch
from gla_testenv import _isolated_log_env, _cfg_values


class _SLog:
    """Stands in for a module logger and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)

    def error(self, msg, *a, **k):
        self._add("error", msg)


def _slogged(mod, fn, *args, **kwargs):
    real, rec = mod.log, _SLog()
    mod.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        mod.log = real


_VAL_OK = {"status": "ok", "issues": []}
_D = "2024-07-01"


def _env(name):
    """Isolated source dirs plus an own source_api_log.json path below the same base."""
    class _Ctx:
        def __enter__(self):
            self._a = _isolated_log_env(name)
            self.base = self._a.__enter__()
            self._b = _cfg_values(SOURCE_API_LOG=self.base / "log" / "source_api_log.json")
            self._b.__enter__()
            return self.base

        def __exit__(self, *exc):
            self._b.__exit__(*exc)
            return self._a.__exit__(*exc)
    return _Ctx()


# -- schema version of the log entries ----------------------------------------------------------------
with _env("sw2_schema") as _b:
    source_writer.update_log(_D, _VAL_OK, ["sleep"], [], 10)
    _e = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))[_D]
    check("D2 update_log: schema_version is 1 (identity of the log format, bump consciously)",
          source_writer.SOURCE_LOG_SCHEMA_VERSION == 1 and _e["schema_version"] == 1)

# -- decisions are compared by value, anything unknown means write ---------------------------------------
import sys
import garmin_source_quality as _sqm
for _dec, _expect_changed, _expect_warn in (
        ("".join(["sk", "ip"]), False, False),                  # equal to 'skip', not the same object
        ("".join(["skip", "_warn"]), False, True),              # equal to 'skip_warn'
        ("aaa", True, False),                                   # sorts before 'skip' -> still a write
        ("skip_a", True, False),                                # sorts between 'skip' and 'skip_warn'
        ("zzz", True, False)):
    with _env("sw2_dec") as _b:
        cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        _dst = cfg.SOURCE_DIR / f"garmin_source_{_D}.json"
        _dst.write_text('{"old": true}', encoding="utf-8")
        with patch.object(_sqm, "compare_source", return_value=_dec):
            _ok, _c = _slogged(source_writer, source_writer.write_source, {"new": True}, _D)
        _changed = json.loads(_dst.read_text(encoding="utf-8")) == {"new": True}
        check(f"D2 write_source: decision {_dec!r} -> {'written' if _expect_changed else 'file kept'}",
              _ok is True and _changed is _expect_changed
              and any("degraded response blocked" in m for lv, m in _c) is _expect_warn)

# -- exact file formats -----------------------------------------------------------------------------------
_UML = {"name": "Grüße", "n": [1, 2], "d": {"k": "ä"}}
with _env("sw2_fmt") as _b:
    source_writer.write_source(_UML, _D)
    _dst = cfg.SOURCE_DIR / f"garmin_source_{_D}.json"
    check("D2 write_source: compact JSON, umlauts as UTF-8 (not \\u escapes)",
          _dst.read_bytes() == '{"name":"Grüße","n":[1,2],"d":{"k":"ä"}}'.encode("utf-8"))
    source_writer.update_log(_D, {"status": "ok", "issues": [{"field": "Grüße"}]}, ["sleep"], [], 1)
    _txt = cfg.SOURCE_API_LOG.read_text(encoding="utf-8")
    check("D2 update_log: 2-space indent and umlauts as UTF-8",
          _txt.startswith('{\n  "2024-07-01": {\n    "fetched_at"') and "Grüße" in _txt
          and "\\u00fc" not in _txt)
    source_writer.patch_source_field(_D, "extra", {"s": "Grün"})
    check("D2 patch_source_field: compact JSON with the merged field, umlauts as UTF-8",
          _dst.read_bytes() == '{"name":"Grüße","n":[1,2],"d":{"k":"ä"},"extra":{"s":"Grün"}}'.encode("utf-8"))
    _txt2 = cfg.SOURCE_API_LOG.read_text(encoding="utf-8")
    check("D2 patch_source_field: the annotated log keeps 2-space indent and UTF-8",
          _txt2.startswith('{\n  "2024-07-01": {\n    "fetched_at"')
          and '"backfilled_fields": {\n      "extra"' in _txt2 and "Grüße" in _txt2)

# -- update_log details ------------------------------------------------------------------------------------
with _env("sw2_log") as _b:
    _dd = "".join(["da", "te"])                                  # 'date' as a new object
    source_writer.update_log(_D, _VAL_OK, ["activities", _dd, "sleep", "body_battery"], ["x"], 1)
    _e = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))[_D]
    check("D2 update_log: the key 'date' is dropped from endpoints_fetched, all others kept in order",
          _e["endpoints_fetched"] == ["activities", "sleep", "body_battery"]
          and _e["endpoints_failed"] == ["x"])
    check("D2 update_log: missing_optional issues are not listed, others by field name",
          (source_writer.update_log("2024-07-02", {"status": "warning", "issues": [
              {"type": "missing_optional", "field": "a"}, {"type": "out_of_range", "field": "b"},
              {"type": "type_mismatch"}]}, [], [], 1) is True)
          and json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))["2024-07-02"]["validator_issues"]
          == ["b", ""])

with _env("sw2_log_deep") as _b:
    with _cfg_values(SOURCE_API_LOG=_b / "a" / "b" / "c" / "source_api_log.json"):
        _ok = source_writer.update_log(_D, _VAL_OK, [], [], 1)
        check("D2 update_log: a log path with several missing folders is created",
              _ok is True and cfg.SOURCE_API_LOG.is_file())

with _env("sw2_log_bad") as _b:
    cfg.SOURCE_API_LOG.parent.mkdir(parents=True, exist_ok=True)
    cfg.SOURCE_API_LOG.write_text("{broken", encoding="utf-8")
    _ok, _c = _slogged(source_writer, source_writer.update_log, _D, _VAL_OK, [], [], 1)
    check("D2 update_log: unreadable existing log -> False, history left untouched, protective warning",
          _ok is False and cfg.SOURCE_API_LOG.read_text(encoding="utf-8") == "{broken"
          and any("skipping update to protect existing history" in m for lv, m in _c))

with _env("sw2_log_assess") as _b:
    with patch.object(_sqm, "assess_source", side_effect=RuntimeError("probe")):
        _ok, _c = _slogged(source_writer, source_writer.update_log, _D, _VAL_OK, [], [], 1, {"a": 1})
    _e = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))[_D]
    check("D2 update_log: failing intraday assessment is logged, the entry is written without it",
          _ok is True and "intraday_present" not in _e
          and any("assess_source failed" in m for lv, m in _c))

# -- failure paths: result, leftover .tmp, a failing cleanup must not escape -----------------------------------
def _fail_replace():
    return patch("os.replace", side_effect=OSError("locked"))


with _env("sw2_fail_write") as _b:
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    with _fail_replace():
        _ok, _c = _slogged(source_writer, source_writer.write_source, {"a": 1}, _D)
    check("D2 write_source: failing swap -> False, no .tmp left, warning names the day",
          _ok is False and not list(cfg.SOURCE_DIR.glob("*.tmp"))
          and any(lv == "warning" and f"write_source failed for {_D}" in m for lv, m in _c))
    with _fail_replace(), patch.object(source_writer, "_cleanup_tmp", side_effect=RuntimeError("x")):
        _ok = source_writer.write_source({"a": 1}, _D)
    check("D2 write_source: a failing cleanup does not escape -> False", _ok is False)
    with patch.object(sys.modules["garmin_backup_source"], "backup_source", side_effect=RuntimeError("bk")):
        _ok, _c = _slogged(source_writer, source_writer.write_source, {"a": 1}, _D)
    check("D2 write_source: failing backup is only a warning, the write still counts as success",
          _ok is True and (cfg.SOURCE_DIR / f"garmin_source_{_D}.json").exists()
          and any(lv == "warning" and f"backup_source failed for {_D}: bk" in m for lv, m in _c))

with _env("sw2_fail_log") as _b:
    with _fail_replace():
        _ok = source_writer.update_log(_D, _VAL_OK, [], [], 1)
    check("D2 update_log: failing swap -> False, no .tmp left",
          _ok is False and not list(cfg.SOURCE_API_LOG.parent.glob("*.tmp")))
    with _fail_replace(), patch.object(source_writer, "_cleanup_tmp", side_effect=RuntimeError("x")):
        _ok = source_writer.update_log(_D, _VAL_OK, [], [], 1)
    check("D2 update_log: a failing cleanup does not escape -> False", _ok is False)

with _env("sw2_fail_patch") as _b:
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    _dst = cfg.SOURCE_DIR / f"garmin_source_{_D}.json"
    _tmp = _dst.with_suffix(".json.tmp")
    _dst.write_text("{broken", encoding="utf-8")
    _tmp.write_text("leftover", encoding="utf-8")
    _ok, _c = _slogged(source_writer, source_writer.patch_source_field, _D, "steps", [1])
    check("D2 patch_source_field: unreadable source file -> False, leftover .tmp removed, warning",
          _ok is False and not _tmp.exists()
          and any(lv == "warning" and f"patch_source_field failed for {_D}" in m for lv, m in _c))
    with patch.object(source_writer, "_cleanup_tmp", side_effect=RuntimeError("x")):
        _ok = source_writer.patch_source_field(_D, "steps", [1])
    check("D2 patch_source_field: a failing cleanup does not escape -> False", _ok is False)
    _dst.write_text('{"date": "x"}', encoding="utf-8")
    with _fail_replace():
        _ok = source_writer.patch_source_field(_D, "steps", [1])
    check("D2 patch_source_field: failing swap -> False, source file unchanged, no .tmp",
          _ok is False and json.loads(_dst.read_text(encoding="utf-8")) == {"date": "x"}
          and not _tmp.exists())

with _env("sw2_patch_log") as _b:
    source_writer.write_source({"date": "x"}, _D)
    cfg.SOURCE_API_LOG.parent.mkdir(parents=True, exist_ok=True)
    cfg.SOURCE_API_LOG.write_text("{broken", encoding="utf-8")
    _ok, _c = _slogged(source_writer, source_writer.patch_source_field, _D, "steps", [1])
    check("D2 patch_source_field: broken log is only a warning, the patch itself still counts",
          _ok is True and json.loads((cfg.SOURCE_DIR / f"garmin_source_{_D}.json")
                                     .read_text(encoding="utf-8"))["steps"] == [1]
          and any(lv == "warning" and "log annotation failed" in m for lv, m in _c))
    cfg.SOURCE_API_LOG.unlink()                                  # start a fresh, readable log
    source_writer.update_log(_D, _VAL_OK, [], [], 1)
    source_writer.patch_source_field(_D, "steps", [2])
    source_writer.patch_source_field(_D, "floors", [3])
    _bf = json.loads(cfg.SOURCE_API_LOG.read_text(encoding="utf-8"))[_D]["backfilled_fields"]
    check("D2 patch_source_field: every patched field gets its own timestamp in the log",
          set(_bf) == {"steps", "floors"} and all(v.endswith("Z") for v in _bf.values()))

# -- _cleanup_tmp ------------------------------------------------------------------------------------------------
with _env("sw2_cleanup") as _b:
    _t = _b / "x.json.tmp"
    _t.write_text("x", encoding="utf-8")
    source_writer._cleanup_tmp(_t)
    source_writer._cleanup_tmp(_t)                               # already gone: no error
    check("D2 _cleanup_tmp: removes an existing file, a missing one is fine", not _t.exists())
    _t.write_text("x", encoding="utf-8")
    with patch.object(Path, "unlink", side_effect=OSError("locked")):
        source_writer._cleanup_tmp(_t)
    check("D2 _cleanup_tmp: a failing delete does not raise", _t.exists())

# -- garmin_source_quality: unreadable file, defaults ---------------------------------------------------------------
with _env("sw2_sq") as _b:
    cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    _bad = cfg.SOURCE_DIR / "garmin_source_2024-07-09.json"
    _bad.write_text("{broken", encoding="utf-8")
    _a, _c = _slogged(_sqm, _sqm.assess_source_from_file, _bad)
    check("D2 assess_source_from_file: unreadable file -> exactly {'unreadable': True}, warning names the file",
          _a == {"unreadable": True}
          and any(lv == "warning" and "could not read existing file garmin_source_2024-07-09.json" in m
                  for lv, m in _c))
check("D2 compare_source: a missing 'intraday_present' counts as False on both sides",
      _sqm.compare_source({}, {}) == "write"
      and _sqm.compare_source({}, {"intraday_present": True}) == "write"
      and _sqm.compare_source({"intraday_present": True}, {}) == "skip_warn"
      and _sqm.compare_source({"intraday_present": True}, {"intraday_present": True}) == "skip")
check("D2 compare_source: force always writes, whatever exists",
      all(_sqm.compare_source(e, n, force=True) == "write"
          for e in (None, {"unreadable": True}, {"intraday_present": True}, {"intraday_present": False})
          for n in ({"intraday_present": True}, {"intraday_present": False})))

# ── Cleanup ───────────────────────────────────────────────────────────────────
if _sw_file.exists():
    _sw_file.unlink()
if _sw_cfg.SOURCE_API_LOG.exists():
    _sw_cfg.SOURCE_API_LOG.unlink()

summary()
