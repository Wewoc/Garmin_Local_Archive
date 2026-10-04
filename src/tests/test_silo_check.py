#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_silo_check.py — garmin_silo_check

Run from the project folder:
    python tests/test_silo_check.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import os
import shutil
from pathlib import Path

from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  G. garmin_silo_check (v1.6.0.4.7)
# ══════════════════════════════════════════════════════════════════════════════
section("G. garmin_silo_check (v1.6.0.4.7)")
import garmin_silo_check as silo_check
importlib.reload(silo_check)

# ── Result structure — clean archive (no findings) ────────────────────────────
# ── Result structure + clean-silo baseline (isolated tmpdir) ─────────────────
# Uses a fresh temp dir so no artefacts from earlier sections bleed in.
import tempfile as _sc_tempfile
_sc_iso_dir = Path(_sc_tempfile.mkdtemp(prefix="garmin_sc_"))
_sc_orig_env = os.environ.get("GARMIN_OUTPUT_DIR", "")
os.environ["GARMIN_OUTPUT_DIR"] = str(_sc_iso_dir)
importlib.reload(cfg)
importlib.reload(silo_check)

_sc_result = silo_check.check_silos()

check("silo_check: returns dict",
      isinstance(_sc_result, dict))
check("silo_check: key raw_without_quality present",
      "raw_without_quality" in _sc_result)
check("silo_check: key source_without_raw present",
      "source_without_raw" in _sc_result)
check("silo_check: key summary_without_raw present",
      "summary_without_raw" in _sc_result)
check("silo_check: key raw_without_summary present",
      "raw_without_summary" in _sc_result)
check("silo_check: key checked_at present",
      "checked_at" in _sc_result)
check("silo_check: key totals present",
      "totals" in _sc_result)
check("silo_check: key counts present",
      "counts" in _sc_result)

# totals sub-keys
_sc_totals = _sc_result["totals"]
check("silo_check: totals.raw present",
      "raw" in _sc_totals)
check("silo_check: totals.summary present",
      "summary" in _sc_totals)
check("silo_check: totals.source present",
      "source" in _sc_totals)
check("silo_check: totals.quality_days present",
      "quality_days" in _sc_totals)

# counts sub-keys
_sc_counts = _sc_result["counts"]
check("silo_check: counts.raw_without_quality present",
      "raw_without_quality" in _sc_counts)
check("silo_check: counts.source_without_raw present",
      "source_without_raw" in _sc_counts)
check("silo_check: counts.summary_without_raw present",
      "summary_without_raw" in _sc_counts)
check("silo_check: counts.raw_without_summary present",
      "raw_without_summary" in _sc_counts)

# checked_at format (ISO-8601 Z suffix)
check("silo_check: checked_at ends with Z",
      _sc_result["checked_at"].endswith("Z"))

# Clean silo baseline → no findings
check("silo_check: clean silo → raw_without_quality empty",
      _sc_result["raw_without_quality"] == [])
check("silo_check: clean silo → source_without_raw empty",
      _sc_result["source_without_raw"] == [])
check("silo_check: clean silo → summary_without_raw empty",
      _sc_result["summary_without_raw"] == [])
check("silo_check: clean silo → raw_without_summary empty",
      _sc_result["raw_without_summary"] == [])
check("silo_check: clean silo → all counts zero",
      all(v == 0 for v in _sc_counts.values()))

# restore original GARMIN_OUTPUT_DIR + cfg for subsequent checks
os.environ["GARMIN_OUTPUT_DIR"] = _sc_orig_env
importlib.reload(cfg)
importlib.reload(silo_check)
shutil.rmtree(_sc_iso_dir, ignore_errors=True)

# ── #1: raw without quality_log entry ─────────────────────────────────────────
_sc1_dir = _TMPDIR / "garmin_data" / "raw"
_sc1_dir.mkdir(parents=True, exist_ok=True)
_sc1_date = "2024-11-01"
(_sc1_dir / f"garmin_raw_{_sc1_date}.json").write_text('{"date": "2024-11-01"}',
                                                         encoding="utf-8")
# quality_log does NOT get an entry for this date → orphan raw
_sc1_result = silo_check.check_silos()
from datetime import date as _sc_date_cls
check("silo_check: #1 raw without quality → detected",
      _sc_date_cls.fromisoformat(_sc1_date) in _sc1_result["raw_without_quality"])
check("silo_check: #1 count ≥ 1",
      _sc1_result["counts"]["raw_without_quality"] >= 1)
check("silo_check: #1 totals.raw ≥ 1",
      _sc1_result["totals"]["raw"] >= 1)

# cleanup
(_sc1_dir / f"garmin_raw_{_sc1_date}.json").unlink(missing_ok=True)

# ── #3: source without raw ────────────────────────────────────────────────────
_sc3_src_dir = _TMPDIR / "garmin_data" / "source"
_sc3_src_dir.mkdir(parents=True, exist_ok=True)
_sc3_date = "2024-11-02"
(_sc3_src_dir / f"garmin_source_{_sc3_date}.json").write_text(
    '{"date": "2024-11-02"}', encoding="utf-8")
# no matching raw file → source_without_raw
_sc3_result = silo_check.check_silos()
check("silo_check: #3 source without raw → detected",
      _sc_date_cls.fromisoformat(_sc3_date) in _sc3_result["source_without_raw"])
check("silo_check: #3 count ≥ 1",
      _sc3_result["counts"]["source_without_raw"] >= 1)
check("silo_check: #3 totals.source ≥ 1",
      _sc3_result["totals"]["source"] >= 1)

# cleanup
(_sc3_src_dir / f"garmin_source_{_sc3_date}.json").unlink(missing_ok=True)

# ── #5: summary without raw ───────────────────────────────────────────────────
_sc5_sum_dir = _TMPDIR / "garmin_data" / "summary"
_sc5_sum_dir.mkdir(parents=True, exist_ok=True)
_sc5_date = "2024-11-03"
(_sc5_sum_dir / f"garmin_{_sc5_date}.json").write_text(
    '{"date": "2024-11-03"}', encoding="utf-8")
# no matching raw file → summary_without_raw
_sc5_result = silo_check.check_silos()
check("silo_check: #5 summary without raw → detected",
      _sc_date_cls.fromisoformat(_sc5_date) in _sc5_result["summary_without_raw"])
check("silo_check: #5 count ≥ 1",
      _sc5_result["counts"]["summary_without_raw"] >= 1)
check("silo_check: #5 totals.summary ≥ 1",
      _sc5_result["totals"]["summary"] >= 1)

# cleanup
(_sc5_sum_dir / f"garmin_{_sc5_date}.json").unlink(missing_ok=True)

# ── #7: raw without summary ───────────────────────────────────────────────────
_sc7_raw_dir = _TMPDIR / "garmin_data" / "raw"
_sc7_raw_dir.mkdir(parents=True, exist_ok=True)
_sc7_date = "2024-11-04"
(_sc7_raw_dir / f"garmin_raw_{_sc7_date}.json").write_text(
    '{"date": "2024-11-04"}', encoding="utf-8")
# no matching summary file → raw_without_summary
_sc7_result = silo_check.check_silos()
check("silo_check: #7 raw without summary → detected",
      _sc_date_cls.fromisoformat(_sc7_date) in _sc7_result["raw_without_summary"])
check("silo_check: #7 count ≥ 1",
      _sc7_result["counts"]["raw_without_summary"] >= 1)

# cleanup
(_sc7_raw_dir / f"garmin_raw_{_sc7_date}.json").unlink(missing_ok=True)

# ── counts match len of lists ─────────────────────────────────────────────────
_sc_final = silo_check.check_silos()
check("silo_check: counts match list lengths",
      _sc_final["counts"]["raw_without_quality"]  == len(_sc_final["raw_without_quality"])
      and _sc_final["counts"]["source_without_raw"]   == len(_sc_final["source_without_raw"])
      and _sc_final["counts"]["summary_without_raw"]  == len(_sc_final["summary_without_raw"])
      and _sc_final["counts"]["raw_without_summary"]  == len(_sc_final["raw_without_summary"]))

# ── finding lists contain date objects ───────────────────────────────────────
# Create one finding to verify type
_sc_type_dir = _TMPDIR / "garmin_data" / "raw"
_sc_type_dir.mkdir(parents=True, exist_ok=True)
_sc_type_date = "2024-11-05"
(_sc_type_dir / f"garmin_raw_{_sc_type_date}.json").write_text(
    '{"date": "2024-11-05"}', encoding="utf-8")
_sc_type_result = silo_check.check_silos()
check("silo_check: finding list contains date objects",
      len(_sc_type_result["raw_without_summary"]) >= 1
      and isinstance(_sc_type_result["raw_without_summary"][0], _sc_date_cls))
# cleanup
(_sc_type_dir / f"garmin_raw_{_sc_type_date}.json").unlink(missing_ok=True)

# ── quality_log.json present: entries are read, bad entries are skipped ──────
# (v1.7.4.0.2) The log feeds check #1 and totals.quality_days. The older tests
# above run without a log; the old single test file only reached this path through
# a log that earlier sections happened to leave behind.
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
cfg.QUALITY_LOG_FILE.write_text(json.dumps({"days": [
    {"date": "2024-11-06", "quality": "high"},
    {"date": "2024-11-07", "quality": "standard"},
    {"quality": "high"},                                  # entry without a date
    {"date": "not-a-date", "quality": "high"},            # date that does not parse
]}), encoding="utf-8")
_sc_qdates, _sc_qcount = silo_check._collect_quality_dates()
check("silo_check: quality log: valid dates are returned, bad entries skipped",
      _sc_qdates == {_sc_date_cls(2024, 11, 6), _sc_date_cls(2024, 11, 7)})
check("silo_check: quality log: count is the number of all entries (4)",
      _sc_qcount == 4)

(_TMPDIR / "garmin_data" / "raw").mkdir(parents=True, exist_ok=True)
for _sc_d in ("2024-11-06", "2024-11-08"):
    (_TMPDIR / "garmin_data" / "raw" / f"garmin_raw_{_sc_d}.json").write_text(
        '{"date": "%s"}' % _sc_d, encoding="utf-8")
_sc_ql_result = silo_check.check_silos()
check("silo_check: raw day that is in the quality log is not reported",
      _sc_date_cls(2024, 11, 6) not in _sc_ql_result["raw_without_quality"])
check("silo_check: raw day that is not in the quality log is reported",
      _sc_date_cls(2024, 11, 8) in _sc_ql_result["raw_without_quality"])
check("silo_check: totals.quality_days counts the log entries",
      _sc_ql_result["totals"]["quality_days"] == 4)
# cleanup
for _sc_d in ("2024-11-06", "2024-11-08"):
    (_TMPDIR / "garmin_data" / "raw" / f"garmin_raw_{_sc_d}.json").unlink(missing_ok=True)
cfg.QUALITY_LOG_FILE.unlink(missing_ok=True)

# ── Leaf-Node AST check — only garmin_config + stdlib ────────────────────────
import ast as _sc_ast
_sc_py = Path(__file__).parent.parent / "garmin" / "garmin_silo_check.py"
if _sc_py.exists():
    _sc_tree = _sc_ast.parse(_sc_py.read_text(encoding="utf-8"))
    _sc_forbidden = {
        "garmin_collector", "garmin_quality", "garmin_normalizer",
        "garmin_writer", "garmin_validator", "garmin_sync", "garmin_api",
        "garmin_source_writer", "garmin_backup", "garmin_utils",
        "garmin_import_mirror", "garmin_mirror",
    }
    _sc_imports = set()
    for _n in _sc_ast.walk(_sc_tree):
        if isinstance(_n, _sc_ast.Import):
            for _a in _n.names:
                _sc_imports.add(_a.name.split(".")[0])
        elif isinstance(_n, _sc_ast.ImportFrom):
            if _n.module:
                _sc_imports.add(_n.module.split(".")[0])
    check("silo_check: Leaf-Node — no forbidden pipeline imports",
          _sc_imports.isdisjoint(_sc_forbidden))
else:
    check("silo_check: Leaf-Node — garmin_silo_check.py found", False)

summary()
