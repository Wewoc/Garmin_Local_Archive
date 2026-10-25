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

# ══════════════════════════════════════════════════════════════════════════════
#  G2. garmin_silo_check — set arithmetic with overlapping silos, date parsing,
#      quality-log reading (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("G2. garmin_silo_check — overlapping silos, parsing, quality log")
from datetime import date as _date
from unittest.mock import patch as _patch
from gla_testenv import _isolated_log_env as _iso_env


class _ScLog:
    """Stands in for silo_check.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg % a if a else msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg % a if a else msg))

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg % a if a else msg))


def _sc_logged(fn, *args, **kwargs):
    real, rec = silo_check.log, _ScLog()
    silo_check.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        silo_check.log = real


# -- _extract_date -------------------------------------------------------------------------------------------
_xd = silo_check._extract_date
check("G2 _extract_date: a valid stem -> the date", _xd("garmin_raw_2025-08-01", "garmin_raw_") == _date(2025, 8, 1))
check("G2 _extract_date: the prefix is removed once only -> doubled prefix is no date",
      _xd("garmin_raw_garmin_raw_2025-08-01", "garmin_raw_") is None)
check("G2 _extract_date: text that is no date -> None", _xd("garmin_raw_junk", "garmin_raw_") is None)
check("G2 _extract_date: a value that is not text -> None, no crash", _xd(None, "garmin_raw_") is None)

# -- check_silos with overlapping silos ------------------------------------------------------------------------
with _iso_env("sc2_sets") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _dir in (cfg.RAW_DIR, cfg.SUMMARY_DIR, cfg.SOURCE_DIR):
        _dir.mkdir(parents=True, exist_ok=True)
    for _n in (1, 2, 3):
        (cfg.RAW_DIR / f"garmin_raw_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    for _n in (2, 4):
        (cfg.SUMMARY_DIR / f"garmin_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    (cfg.SUMMARY_DIR / "garmin_dataformat.json").write_text("{}", encoding="utf-8")   # not a day
    for _n in (2, 3, 5):
        (cfg.SOURCE_DIR / f"garmin_source_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"days": [
        {"date": "2025-08-02"}, {"date": "2025-08-03"}, {"date": "2025-08-06"},
        {"quality": "high"}]}), encoding="utf-8")
    _r = silo_check.check_silos()
    _d8 = lambda *ns: [_date(2025, 8, n) for n in ns]          # noqa: E731
    check("G2 check_silos: raw without quality = raw minus quality",
          _r["raw_without_quality"] == _d8(1))
    check("G2 check_silos: source without raw = source minus raw",
          _r["source_without_raw"] == _d8(5))
    check("G2 check_silos: summary without raw = summary minus raw",
          _r["summary_without_raw"] == _d8(4))
    check("G2 check_silos: raw without summary = raw minus summary",
          _r["raw_without_summary"] == _d8(1, 3))
    check("G2 check_silos: totals count files and quality entries (undated entry included)",
          _r["totals"] == {"raw": 3, "summary": 2, "source": 3, "aggregates": 0, "quality_days": 4})
    check("G2 check_silos: counts are the lengths of the lists (the bulk lists are empty without marks and without bulk day files)",
          _r["counts"] == {"raw_without_quality": 1, "source_without_raw": 1,
                           "summary_without_raw": 1, "raw_without_summary": 2,
                           "bulk_lost_intraday": 0, "bulk_lost_aggregates": 0, "bulk_originals_missing": 0,
                           "bulk_json_originals_missing": 0})

# -- _collect_quality_dates ----------------------------------------------------------------------------------------
with _iso_env("sc2_quality") as _b:
    check("G2 _collect_quality_dates: no file -> exactly (empty set, 0)",
          silo_check._collect_quality_dates() == (set(), 0))
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"days": [
        {"quality": "high"}, {"date": "2025-09-01"}, {"date": "not-a-date"}, {"date": "2025-09-02"}]}),
        encoding="utf-8")
    check("G2 _collect_quality_dates: undated and invalid entries are skipped, the rest still read, all counted",
          silo_check._collect_quality_dates() == ({_date(2025, 9, 1), _date(2025, 9, 2)}, 4))
    cfg.QUALITY_LOG_FILE.write_text("{broken", encoding="utf-8")
    _res, _c = _sc_logged(silo_check._collect_quality_dates)
    check("G2 _collect_quality_dates: broken JSON -> (empty set, 0) and a warning",
          _res == (set(), 0) and any(lv == "warning" and "could not read quality_log.json" in m
                                     for lv, m in _c))
    cfg.QUALITY_LOG_FILE.write_text("{}", encoding="utf-8")
    from pathlib import Path as _P
    with _patch.object(_P, "read_text", side_effect=OSError("denied")):
        _res, _c = _sc_logged(silo_check._collect_quality_dates)
    check("G2 _collect_quality_dates: unreadable file (OSError) -> (empty set, 0) and a warning",
          _res == (set(), 0) and any(lv == "warning" and "denied" in m for lv, m in _c))

# -- export data (aggregates, v1.7.6.1): a day with export data is neither an orphan nor fine without a summary ----
with _iso_env("sc3_aggregates") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _dir in (cfg.RAW_DIR, cfg.SUMMARY_DIR, cfg.BULK_AGG_DIR):
        _dir.mkdir(parents=True, exist_ok=True)
    check("G3 _collect_aggregate_dates: an empty folder -> empty set", silo_check._collect_aggregate_dates() == set())
    for _n in (1, 2, 3):
        (cfg.RAW_DIR / f"garmin_raw_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    for _n in (2, 4, 5, 6):
        (cfg.SUMMARY_DIR / f"garmin_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    for _n in (3, 4, 6, 7):
        (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    for _junk in (f"{cfg.BULK_AGG_FILE_PREFIX}junk.json", f"{cfg.BULK_AGG_FILE_PREFIX}2025-08-09.json.tmp",
                  f"{cfg.BULK_FILE_PREFIX}2025-08-08.json", "2025-08-08.json", "notes.txt"):
        (cfg.BULK_AGG_DIR / _junk).write_text("{}", encoding="utf-8")
    _files_before = sorted(str(f) for f in _b.rglob("*") if f.is_file())
    check("G3 _collect_aggregate_dates: the dates of the aggregates files by name; junk, a temporary file, an intraday file name and other files are no days",
          silo_check._collect_aggregate_dates() == {_date(2025, 8, n) for n in (3, 4, 6, 7)})
    _r = silo_check.check_silos()
    _d8 = lambda *ns: [_date(2025, 8, n) for n in ns]          # noqa: E731
    check("G3 check_silos: a summary of a day with export data is no orphan (#5 = summary minus raw minus export data)",
          _r["summary_without_raw"] == _d8(5))
    check("G3 check_silos: a day with export data and no summary is a finding #7, together with raw without summary",
          _r["raw_without_summary"] == _d8(1, 3, 7))
    check("G3 check_silos: a day with raw and export data and a summary is no finding at all (day 6 and 4 appear nowhere)",
          all(_date(2025, 8, n) not in _r["summary_without_raw"] + _r["raw_without_summary"] for n in (2, 4, 6)))
    check("G3 check_silos: totals count the aggregates files, the counts are the lengths of the lists",
          _r["totals"] == {"raw": 3, "summary": 4, "source": 0, "aggregates": 4, "quality_days": 0}
          and _r["counts"] == {"raw_without_quality": 3, "source_without_raw": 0, "summary_without_raw": 1, "raw_without_summary": 3,
                               "bulk_lost_intraday": 0, "bulk_lost_aggregates": 0, "bulk_originals_missing": 0,
                               "bulk_json_originals_missing": 0})
    check("G3 check_silos: the check only looks, no file is created, changed or removed",
          sorted(str(f) for f in _b.rglob("*") if f.is_file()) == _files_before)

with _iso_env("sc3_no_folder") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.SUMMARY_DIR / "garmin_2025-08-05.json").write_text("{}", encoding="utf-8")
    _r = silo_check.check_silos()
    check("G3 check_silos: without an aggregates folder nothing changes: the summary is an orphan, nothing is created",
          _r["summary_without_raw"] == [_date(2025, 8, 5)] and _r["totals"]["aggregates"] == 0 and not cfg.BULK_AGG_DIR.exists())

# -- bulk files lost (#8, v1.7.6.2): the quality log marks the day, the file is not in the store ----------------------------
section("G4. garmin_silo_check — bulk file lost (#8) and the summary of such a day (F-10)")
_AGGP, _DAYP = cfg.BULK_AGG_FILE_PREFIX, cfg.BULK_FILE_PREFIX


def _g4_log(entries):
    cfg.QUALITY_LOG_FILE.write_text(json.dumps({"days": entries}), encoding="utf-8")


with _iso_env("sc4_names") as _b:
    check("G4 _collect_bulk_day_dates: no folder -> empty set, nothing is created",
          silo_check._collect_bulk_day_dates() == set() and not cfg.BULK_RAW_DIR.exists())
    cfg.BULK_RAW_DIR.mkdir(parents=True)
    for _n in ("2025-08-01", "2025-08-02"):
        (cfg.BULK_RAW_DIR / f"{_DAYP}{_n}.json").write_text("{}", encoding="utf-8")
    for _junk in (f"{_DAYP}2025-08-03.json.tmp", f"{_AGGP}2025-08-04.json", f"{_DAYP}junk.json", "2025-08-05.json"):
        (cfg.BULK_RAW_DIR / _junk).write_text("{}", encoding="utf-8")
    check("G4 _collect_bulk_day_dates: the dates of the day files by name; a temporary file, an aggregates name, junk and other files are no days",
          silo_check._collect_bulk_day_dates() == {_date(2025, 8, 1), _date(2025, 8, 2)})

with _iso_env("sc4_marks") as _b:
    check("G4 _collect_bulk_marks: no quality log -> (empty, empty)", silo_check._collect_bulk_marks() == (set(), set()))
    _g4_log([
        {"date": "2025-09-01", "bulk": {"intraday": "2025-10-01"}},
        {"date": "2025-09-02", "bulk": {"aggregates": "2025-10-01"}},
        {"date": "2025-09-03", "bulk": {"intraday": "2025-10-01", "aggregates": "2025-10-01"}},
        {"date": "2025-09-04", "bulk": {"intraday": "", "aggregates": None}},      # empty values are no marks
        {"date": "2025-09-05", "bulk": "yes"},                                      # not a dict
        {"date": "2025-09-06"},                                                      # no bulk key
        {"date": "not-a-date", "bulk": {"intraday": "2025-10-01"}},                # invalid date
        {"bulk": {"intraday": "2025-10-01"}},                                       # no date
        "not an entry",
    ])
    check("G4 _collect_bulk_marks: non-empty values of bulk.intraday / bulk.aggregates are marks; empty values, other types, "
          "undated and invalid entries are skipped, the rest is still read",
          silo_check._collect_bulk_marks() == ({_date(2025, 9, 1), _date(2025, 9, 3)}, {_date(2025, 9, 2), _date(2025, 9, 3)}))
    cfg.QUALITY_LOG_FILE.write_text("{broken", encoding="utf-8")
    check("G4 _collect_bulk_marks: broken JSON -> (empty, empty), no exception", silo_check._collect_bulk_marks() == (set(), set()))
    cfg.QUALITY_LOG_FILE.write_text("[]", encoding="utf-8")
    check("G4 _collect_bulk_marks: a log that is no object -> (empty, empty)", silo_check._collect_bulk_marks() == (set(), set()))
    cfg.QUALITY_LOG_FILE.write_text("{}", encoding="utf-8")
    from pathlib import Path as _P4
    with _patch.object(_P4, "read_text", side_effect=OSError("denied")):
        check("G4 _collect_bulk_marks: unreadable file (OSError) -> (empty, empty)", silo_check._collect_bulk_marks() == (set(), set()))

with _iso_env("sc4_check") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    for _dir in (cfg.RAW_DIR, cfg.SUMMARY_DIR, cfg.BULK_RAW_DIR, cfg.BULK_AGG_DIR):
        _dir.mkdir(parents=True, exist_ok=True)
    _g4_log([
        {"date": "2025-08-01", "bulk": {"intraday": "x", "aggregates": "x"}},   # both files present -> fine
        {"date": "2025-08-02", "bulk": {"intraday": "x"}},                       # intraday file lost
        {"date": "2025-08-03", "bulk": {"aggregates": "x"}},                     # aggregates lost, summary there, no raw
        {"date": "2025-08-04", "bulk": {"aggregates": "x"}},                     # aggregates lost, summary lost too
        {"date": "2025-08-05", "bulk": {"intraday": "x", "aggregates": "x"}},   # both lost, raw present
        {"date": "2025-08-06"},                                                  # files present but no mark -> no finding
        {"date": "2025-08-07", "bulk": {"intraday": "x"}},                       # intraday file present, aggregates never existed -> fine
    ])
    for _n in ("2025-08-01", "2025-08-06", "2025-08-07"):
        (cfg.BULK_RAW_DIR / f"{_DAYP}{_n}.json").write_text("{}", encoding="utf-8")
    for _n in ("2025-08-01", "2025-08-06"):
        (cfg.BULK_AGG_DIR / f"{_AGGP}{_n}.json").write_text("{}", encoding="utf-8")
    (cfg.RAW_DIR / "garmin_raw_2025-08-05.json").write_text("{}", encoding="utf-8")
    for _n in (1, 3, 5, 6, 8):
        (cfg.SUMMARY_DIR / f"garmin_2025-08-0{_n}.json").write_text("{}", encoding="utf-8")
    _files_before = sorted(str(f) for f in _b.rglob("*") if f.is_file())
    _r = silo_check.check_silos()
    _d8 = lambda *ns: [_date(2025, 8, n) for n in ns]          # noqa: E731
    check("G4 check_silos: the marked intraday days whose file is missing are listed (#8)", _r["bulk_lost_intraday"] == _d8(2, 5))
    check("G4 check_silos: the marked aggregates days whose file is missing are listed (#8)", _r["bulk_lost_aggregates"] == _d8(3, 4, 5))
    check("G4 check_silos (F-10): the summary of a day with a lost aggregates file is no orphan — only the real orphan (day 8) is a #5",
          _r["summary_without_raw"] == _d8(8))
    check("G4 check_silos: a lost aggregates file with no summary is not a #7 (nothing to derive from; the repair restores the file)",
          _date(2025, 8, 4) not in _r["raw_without_summary"])
    check("G4 check_silos: the counts carry the two lists",
          _r["counts"]["bulk_lost_intraday"] == 2 and _r["counts"]["bulk_lost_aggregates"] == 3
          and sum(_r["counts"].values()) == 2 + 3 + len(_r["raw_without_quality"]) + len(_r["source_without_raw"])
          + len(_r["summary_without_raw"]) + len(_r["raw_without_summary"]))
    check("G4 check_silos: the check only looks, no file is created, changed or removed",
          sorted(str(f) for f in _b.rglob("*") if f.is_file()) == _files_before)
    # a day that is restored (file back) is no finding any more
    (cfg.BULK_AGG_DIR / f"{_AGGP}2025-08-03.json").write_text("{}", encoding="utf-8")
    _r2 = silo_check.check_silos()
    check("G4 check_silos: with the file back the day leaves #8 and its summary is a plain summary of a day with export data",
          _r2["bulk_lost_aggregates"] == _d8(4, 5) and _date(2025, 8, 3) not in _r2["summary_without_raw"])

with _iso_env("sc4_nolog") as _b:
    cfg.BULK_AGG_DIR.mkdir(parents=True)
    (cfg.BULK_AGG_DIR / f"{_AGGP}2025-08-01.json").write_text("{}", encoding="utf-8")
    _r = silo_check.check_silos()
    check("G4 check_silos: without a quality log there are no marks and no #8", _r["bulk_lost_intraday"] == [] and _r["bulk_lost_aggregates"] == [])

# -- original missing (#9, v1.7.6.2): an intraday day file names a FIT file the store does not hold ---------------------------
section("G5. garmin_silo_check — original missing (#9)")
_HA, _HB, _HC, _HD = "a1" * 32, "b2" * 32, "c3" * 32, "d4" * 32


def _g5_day(name, doc, folder=None):
    folder = folder or cfg.BULK_RAW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")


def _g5_fit(h, suffix=".fit", folder=None):
    d = cfg.BULK_SOURCE_DIR / (folder or h[:2])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{h}{suffix}").write_bytes(b"x")


with _iso_env("sc5_refs") as _b:
    check("G5 _collect_original_refs: no folder -> empty set, nothing is created",
          silo_check._collect_original_refs() == set() and not cfg.BULK_RAW_DIR.exists())
    _g5_day(f"{_DAYP}2025-08-01.json", {"source_files": [_HA, _HB]})
    _g5_day(f"{_DAYP}2025-08-02.json", {"source_files": [_HB, _HC]})                  # _HB again: one hash
    _g5_day(f"{_DAYP}2025-08-03.json", {"source_files": [_HD, "not-a-hash", 7, None, _HD.upper()]})   # only the valid lower-case hash
    _g5_day(f"{_DAYP}2025-08-04.json", "{broken")                                      # damaged: contributes nothing
    _g5_day(f"{_DAYP}2025-08-05.json", [1, 2])                                         # not an object
    _g5_day(f"{_DAYP}2025-08-06.json", {"no_source_files": True})                      # no key
    _g5_day(f"{_DAYP}2025-08-07.json", {"source_files": "a string"})                   # not a list
    _g5_day(f"{_AGGP}2025-08-08.json", {"source_files": ["e5" * 32]}, folder=cfg.BULK_AGG_DIR)   # aggregates: hashes of entries, not files
    check("G5 _collect_original_refs: the valid hashes of all readable intraday day files, each once; damaged, foreign, malformed and aggregates "
          "files contribute nothing",
          silo_check._collect_original_refs() == {_HA, _HB, _HC, _HD})

with _iso_env("sc5_names") as _b:
    check("G5 _collect_original_fit_hashes: no folder -> empty set, nothing is created",
          silo_check._collect_original_fit_hashes() == set() and not cfg.BULK_SOURCE_DIR.exists())
    _g5_fit(_HA)
    _g5_fit(_HB, ".json")                                   # a JSON original is not a FIT original
    _g5_fit(_HC, ".fit.tmp")                                # a temporary file
    _g5_fit(_HD, folder="00")                               # a name in the wrong folder
    (cfg.BULK_SOURCE_DIR / "stray.fit").write_bytes(b"x")   # a file straight in the folder
    (cfg.BULK_SOURCE_DIR / "ee").mkdir()
    (cfg.BULK_SOURCE_DIR / "ee" / "short.fit").write_bytes(b"x")
    check("G5 _collect_original_fit_hashes: only <sha256>.fit in the folder of its first two characters counts; JSON, temporary, misplaced and "
          "oddly named files do not",
          silo_check._collect_original_fit_hashes() == {_HA})

with _iso_env("sc5_check") as _b:
    _g5_day(f"{_DAYP}2025-08-01.json", {"source_files": [_HA, _HB]})
    _g5_day(f"{_DAYP}2025-08-02.json", {"source_files": [_HB, _HC]})
    _g5_fit(_HA)
    _g5_fit(_HB, ".json")                                   # only a JSON original: the FIT one is still missing
    _files_before = sorted(str(f) for f in _b.rglob("*") if f.is_file())
    _r = silo_check.check_silos()
    check("G5 check_silos: the hashes the intraday days name and the store lacks as FIT files are listed, sorted (#9)",
          _r["bulk_originals_missing"] == sorted([_HB, _HC]) and _r["counts"]["bulk_originals_missing"] == 2)
    check("G5 check_silos: the check only looks, no file is created, changed or removed",
          sorted(str(f) for f in _b.rglob("*") if f.is_file()) == _files_before)
    _g5_fit(_HB)
    _g5_fit(_HC)
    check("G5 check_silos: with all originals there nothing is left",
          silo_check.check_silos()["bulk_originals_missing"] == [])

with _iso_env("sc5_none") as _b:
    check("G5 check_silos: no bulk store at all -> no #9 and no folder is created",
          silo_check.check_silos()["bulk_originals_missing"] == [] and not cfg.BULK_DIR.exists())

# -- originals found by the backup (#9, v1.7.6.2.1): JSON originals, and FIT originals whose day file is lost too -----------
section("G6. garmin_silo_check — originals found by the backup (#9, v1.7.6.2.1)")
import zipfile as _g6_zip
_HJ1, _HJ2 = "e5" * 32, "f6" * 32


def _g6_zip_write(prefix, names, folder=None, name=None):
    folder = folder or cfg.BULK_SOURCE_BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    with _g6_zip.ZipFile(folder / (name or f"{prefix}.zip"), "w") as z:
        for n in names:
            z.writestr(n, b"x")


with _iso_env("sc6_json_names") as _b:
    check("G6 _collect_original_json_hashes: no folder -> empty set, nothing is created",
          silo_check._collect_original_json_hashes() == set() and not cfg.BULK_SOURCE_DIR.exists())
    _g5_fit(_HA, ".fit")                                    # a FIT original is not a JSON original
    _g5_fit(_HB, ".json")
    _g5_fit(_HC, ".json.tmp")                               # a temporary file
    _g5_fit(_HD, ".json", folder="00")                      # a name in the wrong folder
    check("G6 _collect_original_json_hashes: only <sha256>.json in the folder of its first two characters counts; FIT, temporary and "
          "misplaced files do not; the FIT collector is unchanged",
          silo_check._collect_original_json_hashes() == {_HB} and silo_check._collect_original_fit_hashes() == {_HA})

with _iso_env("sc6_backup_names") as _b:
    check("G6 _collect_backup_original_hashes: no backup folder -> (empty, empty), nothing is created",
          silo_check._collect_backup_original_hashes() == (set(), set()) and not cfg.BULK_BACKUP_DIR.exists())
    _g6_zip_write(_HA[:2], [f"{_HA}.fit", f"{_HA}.json", "notes.txt", f"{_HA}.fit.tmp", f"{_HA[:2]}/{_HD}.fit"])
    _g6_zip_write(_HB[:2], [f"{_HB}.json", f"{_HC}.fit"])    # _HC does not start with "b2": a misplaced entry
    _g6_zip_write("stray", [f"{_HD}.fit"], name="stray.zip")   # not a <xx>.zip
    _g6_zip_write("zz", [f"{_HD}.fit"], name="zz.zip")         # <xx> is not hex
    (cfg.BULK_SOURCE_BACKUP_DIR / _HC[:2]).mkdir()              # a folder in the place of a ZIP
    (cfg.BULK_SOURCE_BACKUP_DIR / f"{_HD[:2]}.zip").write_bytes(b"this is not a zip")   # damaged: skipped, the others still read
    _res, _c = _sc_logged(silo_check._collect_backup_original_hashes)
    check("G6 _collect_backup_original_hashes: the SHA-256 names of <xx>.zip entries with their folder's two characters, FIT and JSON "
          "apart; misplaced, temporary, nested and foreign entries and ZIPs count for nothing",
          _res == ({_HA}, {_HA, _HB}))
    check("G6 _collect_backup_original_hashes: a damaged ZIP is skipped without raising (debug line only, no warning)",
          [lv for lv, _ in _c] == ["debug"] and f"{_HD[:2]}.zip" in _c[0][1] and "BadZipFile" in _c[0][1])

with _iso_env("sc6_check") as _b:
    _g5_day(f"{_DAYP}2025-08-01.json", {"source_files": [_HA, _HB]})
    _g5_fit(_HA)                                             # in the store; _HB is named by the day and missing
    _g5_fit(_HJ2, ".json")                                   # in the store
    _g6_zip_write(_HJ1[:2], [f"{_HJ1}.json"])                # lost: the backup holds it, the store does not
    _g6_zip_write(_HJ2[:2], [f"{_HJ2}.json"])                # not lost
    _g6_zip_write(_HD[:2], [f"{_HD}.fit"])                   # a FIT original no day file names, lost
    _g6_zip_write(_HA[:2], [f"{_HA}.fit"])                   # not lost
    _files_before = sorted(str(f) for f in _b.rglob("*") if f.is_file())
    _r = silo_check.check_silos()
    check("G6 check_silos: a JSON original the backup holds and the store lacks is listed in bulk_json_originals_missing (sorted), "
          "one the store has is not",
          _r["bulk_json_originals_missing"] == [_HJ1] and _r["counts"]["bulk_json_originals_missing"] == 1)
    check("G6 check_silos: bulk_originals_missing now holds the FIT hashes the day files name and the store lacks together with the "
          "FIT originals the backup holds and the store lacks",
          _r["bulk_originals_missing"] == sorted([_HB, _HD]) and _r["counts"]["bulk_originals_missing"] == 2)
    check("G6 check_silos: the check only looks, no file is created, changed or removed",
          sorted(str(f) for f in _b.rglob("*") if f.is_file()) == _files_before)
    _g5_fit(_HJ1, ".json")
    _g5_fit(_HB)
    _g5_fit(_HD)
    _r = silo_check.check_silos()
    check("G6 check_silos: with everything back both lists are empty; files the store has and the backup lacks are no finding",
          _r["bulk_originals_missing"] == [] and _r["bulk_json_originals_missing"] == [])

with _iso_env("sc6_same_scan") as _b:
    # the day file and the original it names are both lost; the log marks the day, the backup holds the original
    _g4_log([{"date": "2025-08-01", "bulk": {"intraday": "2026-10-24"}}])
    _g6_zip_write(_HA[:2], [f"{_HA}.fit"])
    _r = silo_check.check_silos()
    check("G6 check_silos: a lost day file and its lost original are both found in one check (#8 and #9), where the day file's "
          "names alone would show the original only after the day file is back",
          _r["bulk_lost_intraday"] == [_date(2025, 8, 1)] and _r["bulk_originals_missing"] == [_HA])

with _iso_env("sc6_damaged") as _b:
    _g6_zip_write(_HA[:2], [f"{_HA}.fit"], name=f"{_HA[:2]}.zip")
    (cfg.BULK_SOURCE_BACKUP_DIR / f"{_HB[:2]}.zip").write_bytes(b"this is not a zip")
    _g6_zip_write(_HJ1[:2], [f"{_HJ1}.json"])
    _r = silo_check.check_silos()
    check("G6 check_silos: a damaged backup ZIP does not stop the check, the other ZIPs still count",
          _r["bulk_originals_missing"] == [_HA] and _r["bulk_json_originals_missing"] == [_HJ1])

with _iso_env("sc6_nobackup") as _b:
    _g5_fit(_HA)
    _g5_fit(_HJ1, ".json")
    _r = silo_check.check_silos()
    check("G6 check_silos: without a backup folder there is no finding from it and no folder is created",
          _r["bulk_originals_missing"] == [] and _r["bulk_json_originals_missing"] == [] and not cfg.BULK_BACKUP_DIR.exists())

with _iso_env("sc6_layout") as _b:
    # the names the check reads are the ones the backup writes (the layout belongs to garmin_backup_bulk)
    import garmin_backup_bulk as _g6_bb
    for _h, _s in ((_HA, ".fit"), (_HB, ".fit"), (_HJ1, ".json"), (_HJ2, ".json")):
        _g5_fit(_h, _s)
    _g6_res = _g6_bb.backup_originals()
    check("G6 layout: the real backup of the originals copies all four", _g6_res["copied"] == 4 and _g6_res["failed"] == 0)
    check("G6 layout: the check reads exactly the names the real backup wrote (FIT and JSON apart)",
          silo_check._collect_backup_original_hashes() == ({_HA, _HB}, {_HJ1, _HJ2}))
    for _h, _s in ((_HB, ".fit"), (_HJ1, ".json")):
        (cfg.BULK_SOURCE_DIR / _h[:2] / f"{_h}{_s}").unlink()
    _r = silo_check.check_silos()
    check("G6 layout: a FIT and a JSON original removed from the store after the real backup are both found",
          _r["bulk_originals_missing"] == [_HB] and _r["bulk_json_originals_missing"] == [_HJ1])


summary()
