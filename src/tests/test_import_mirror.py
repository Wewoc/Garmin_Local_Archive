#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_import_mirror.py — garmin_import_mirror

Run from the project folder:
    python tests/test_import_mirror.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR, _isolated_log_env, _craft_container  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import json as _json
import types as _types4
import garmin_mirror as mirror
import garmin_normalizer as normalizer
import garmin_quality as quality

# ══════════════════════════════════════════════════════════════════════════════
#  4h. garmin_import_mirror — container import, delta rules, error paths,
#      legacy folder import (v1.7.4.0.2). Source containers are hand-built with
#      _craft_container() (Section 4g) from synthetic days.
# ══════════════════════════════════════════════════════════════════════════════
section("4h. garmin_import_mirror — container import, folder import, error paths")
# The import imports the 'context' package, whose folder (src/) is on the path in
# the app but not in this suite; added for this block only and removed at its end.
_SRC_ROOT_4H = str(Path(__file__).parent.parent)
_src_root_added = _SRC_ROOT_4H not in sys.path
if _src_root_added:
    sys.path.insert(0, _SRC_ROOT_4H)
import garmin_import_mirror as _im
from context import context_writer as _ctx_writer

# lock() and the version warning import version.APP_VERSION; see Section 4g.
_ver4h_added = "version" not in sys.modules
if _ver4h_added:
    _ver4h = _types4.ModuleType("version")
    _ver4h.APP_VERSION = "test"
    sys.modules["version"] = _ver4h

_M4H = _TMPDIR / "mir4h"
shutil.rmtree(_M4H, ignore_errors=True)
_M4H.mkdir()


def _day_raw(d, kind="high", device=None):
    raw = {"date": d}
    if kind == "high":
        raw["heart_rates"] = {"restingHeartRate": 55,
                              "heartRateValues": [[1740787200000, 58]]}
    else:
        raw["stats"] = {"totalSteps": 1000}
    if device:
        raw["training_status"] = {"mostRecentTrainingStatus": {
            "recordedDevices": [{"deviceId": device[0], "deviceName": device[1]}]}}
    return raw


def _jb(obj):
    return json.dumps(obj).encode("utf-8")


def _mirror_sections(days, raws=None, summaries=None, context=None, source=None,
                     device_table=None):
    """days = [(date, quality, source)]; raws/summaries = {date: object or bytes}."""
    sec = {"quality_log": {"garmin_data/log/quality_log.json": _jb(
        {"days": [{"date": d, "quality": q, "source": s} for d, q, s in days]})}}
    if device_table is not None:
        sec["quality_log"]["garmin_data/log/device_table.json"] = device_table
    sec["raw"] = {f"garmin_data/raw/garmin_raw_{d}.json": (v if isinstance(v, bytes) else _jb(v))
                  for d, v in (raws or {}).items()}
    sec["summary"] = {f"garmin_data/summary/garmin_{d}.json": (v if isinstance(v, bytes) else _jb(v))
                      for d, v in (summaries or {}).items()}
    sec["context"] = dict(context or {})
    sec["source"] = dict(source or {})
    return sec


_D1, _D2 = "2024-02-01", "2024-02-02"
_CTX1 = "context_data/weather/raw/2024-02-01.json"
_SRC1 = "garmin_data/source/garmin_source_2024-02-01.json"
_arch = _M4H / "archive.gla"
_craft_container(_arch, _mirror_sections(
    days=[(_D1, "high", "bulk"), (_D2, "standard", "api")],
    raws={_D1: _day_raw(_D1, "high", ("123", "Fenix 7")), _D2: _day_raw(_D2, "standard")},
    summaries={_D1: {"marker": "from-container", "date": _D1}},
    context={_CTX1: _jb({"temp": 5})},
    source={_SRC1: _jb({"heart_rates": {"x": 1}})},
    device_table=_jb([{"device_id": "123"}]),
))

# -- detect_source and unknown sources ------------------------------------------------
(_M4H / "folder_ok").mkdir()
(_M4H / "folder_ok" / "mirror_meta.json").write_text("{}", encoding="utf-8")
(_M4H / "folder_plain").mkdir()
check("detect_source: folder with mirror_meta.json -> 'folder'",
      _im.detect_source(_M4H / "folder_ok") == "folder")
check("detect_source: folder without mirror_meta.json -> 'unknown'",
      _im.detect_source(_M4H / "folder_plain") == "unknown")
check("detect_source: valid container -> 'container'", _im.detect_source(_arch) == "container")
_r = _im.run_import_mirror(_M4H / "folder_plain", _M4H, "pw")
check("run_import_mirror: unknown source -> ok False with the reason",
      _r["ok"] == False and _r["errors"] == 1 and "Not a recognised" in _r["error"])
_r = _im.run_import_mirror(_M4H / "folder_plain", _M4H, "pw", dry_run=True)
check("run_import_mirror: unknown source in dry run -> ok False, nothing to copy",
      _r["ok"] == False and _r["raw_to_copy"] == 0 and "Not a recognised" in _r["error"])

# -- helper functions ------------------------------------------------------------------
check("_extract_device: no training_status -> (None, '')",
      _im._extract_device({"date": "x"}) == (None, ""))
check("_extract_device: recorded device -> id and name as text",
      _im._extract_device(_day_raw(_D1, "high", (123, "Fenix 7"))) == ("123", "Fenix 7"))
check("_extract_device: device without a name -> empty name",
      _im._extract_device({"training_status": {"mostRecentTrainingStatus": {
          "recordedDevices": [{"deviceId": 7}]}}}) == ("7", ""))
check("_extract_device: recordedDevices that is not a usable list -> (None, '')",
      _im._extract_device({"training_status": {"mostRecentTrainingStatus": {
          "recordedDevices": "nope"}}}) == (None, "")
      and _im._extract_device({"training_status": {"mostRecentTrainingStatus": {
          "recordedDevices": ["not a dict"]}}}) == (None, ""))
check("_extract_device: a value that is not a dict -> (None, ''), no crash",
      _im._extract_device(None) == (None, ""))

# -- delta rules -------------------------------------------------------------------------
_src_log = {"days": [
    {"date": "2024-03-01", "quality": "high"},        # not in the archive
    {"date": "2024-03-02", "quality": "high"},        # better than the archive
    {"date": "2024-03-03", "quality": "standard"},    # worse than the archive
    {"date": "2024-03-04", "quality": "high"},        # equal
    {"quality": "high"},                              # no date
    {"date": "2024-03-06", "quality": "weird"},       # unknown label, not in the archive
]}
_dst_log = {"days": [
    {"date": "2024-03-02", "quality": "standard"},
    {"date": "2024-03-03", "quality": "high"},
    {"date": "2024-03-04", "quality": "high"},
]}
_to_copy, _skipped = _im._analyse_raw_delta(_src_log, _dst_log)
check("delta: missing and better days are copied, equal/worse are skipped, no-date ignored",
      sorted(e["date"] for e in _to_copy) == ["2024-03-01", "2024-03-02", "2024-03-06"]
      and _skipped == 2)

# -- full container import ----------------------------------------------------------------
with _isolated_log_env("imp_full") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _r = _im.run_import_mirror(_arch, _b, "pw", dry_run=True)
    check("import dry run: counts what would be imported, writes nothing",
          _r["ok"] == True and _r["raw_to_copy"] == 2 and _r["context_to_copy"] == 1
          and _r["source_to_copy"] == 1 and not cfg.RAW_DIR.exists())
    check("import dry run: same version -> no version warning", _r["version_warning"] == "")

    sys.modules["version"].APP_VERSION = "9.9.9"
    _r = _im.run_import_mirror(_arch, _b, "pw", dry_run=True)
    check("import dry run: other GLA version -> warning names both versions",
          "test" in _r["version_warning"] and "9.9.9" in _r["version_warning"])
    sys.modules["version"].APP_VERSION = "test"

    _r = _im.run_import_mirror(_arch, _b, "pw")
    check("import: container into an empty archive succeeds",
          _r == {"raw_copied": 2, "raw_skipped": 0, "context_copied": 1,
                 "source_copied": 1, "errors": 0, "ok": True})
    _f1 = json.loads((cfg.RAW_DIR / f"garmin_raw_{_D1}.json").read_text(encoding="utf-8"))
    check("import: raw day is written unchanged", _f1 == _day_raw(_D1, "high", ("123", "Fenix 7")))
    check("import: matching schema -> the summary from the container is used (fast path)",
          json.loads((cfg.SUMMARY_DIR / f"garmin_{_D1}.json").read_text(encoding="utf-8"))
          == {"marker": "from-container", "date": _D1})
    check("import: a day without summary in the container gets a freshly computed one",
          json.loads((cfg.SUMMARY_DIR / f"garmin_{_D2}.json").read_text(encoding="utf-8"))
          .get("generated_by") == "garmin_normalizer.py")
    _ql = {e["date"]: e for e in quality._load_quality_log()["days"]}
    check("import: quality log entries carry quality, source and device",
          _ql[_D1]["quality"] == "high" and _ql[_D1]["source"] == "bulk"
          and _ql[_D1]["device_id"] == "123" and _ql[_D1]["device_name"] == "Fenix 7"
          and _ql[_D2]["quality"] == "standard" and _ql[_D2]["source"] == "api"
          and _ql[_D2]["device_id"] is None)
    check("import: context file is written below base_dir",
          json.loads((_b / _CTX1).read_text(encoding="utf-8")) == {"temp": 5})
    check("import: source file is written",
          (cfg.SOURCE_DIR / "garmin_source_2024-02-01.json").exists())
    check("import: device_table.json is restored from the container",
          json.loads((_b / "garmin_data" / "log" / "device_table.json")
                     .read_text(encoding="utf-8")) == [{"device_id": "123"}])

    _r = _im.run_import_mirror(_arch, _b, "pw")
    check("import: a second import skips the days that are already there",
          _r["raw_copied"] == 0 and _r["raw_skipped"] == 2 and _r["ok"] == True)

with _isolated_log_env("imp_schema") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(normalizer, "CURRENT_SCHEMA_VERSION", 999):
        _r = _im.run_import_mirror(_arch, _b, "pw")
    check("import: schema version differs -> container summary is not used, recomputed",
          _r["ok"] == True
          and json.loads((cfg.SUMMARY_DIR / f"garmin_{_D1}.json").read_text(encoding="utf-8"))
          .get("generated_by") == "garmin_normalizer.py")

# -- error paths inside one import -------------------------------------------------------
_D3, _D4, _D5 = "2024-02-03", "2024-02-04", "2024-02-05"
_BAD_DATE = "2024-13-45"
_err_c = _M4H / "errors.gla"
_craft_container(_err_c, _mirror_sections(
    days=[(_D1, "high", "api"), (_D3, "high", "api"), (_D4, "high", "api"),
          (_D5, "high", "api"), (_BAD_DATE, "high", "api")],
    raws={_D1: _day_raw(_D1), _D4: b"{not json", _D5: _day_raw(_D5), _BAD_DATE: _day_raw(_BAD_DATE)},
    # _D3 is listed in the quality log but has no raw bytes in the container
    summaries={_D5: b"{not json"},
))
with _isolated_log_env("imp_errors") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _r = _im.run_import_mirror(_err_c, _b, "pw")
    check("import: good days are imported even when other days fail",
          _r["raw_copied"] == 2 and (cfg.RAW_DIR / f"garmin_raw_{_D1}.json").exists()
          and (cfg.RAW_DIR / f"garmin_raw_{_D5}.json").exists())
    check("import: missing raw bytes, unparseable raw and an invalid date count as errors",
          _r["errors"] == 3 and _r["ok"] == False)
    check("import: unparseable summary in the container -> summary is recomputed",
          json.loads((cfg.SUMMARY_DIR / f"garmin_{_D5}.json").read_text(encoding="utf-8"))
          .get("generated_by") == "garmin_normalizer.py")
    _ql = {e["date"] for e in quality._load_quality_log()["days"]}
    check("import: failed days get no quality log entry", _D3 not in _ql and _D4 not in _ql)
    # Ist-Stand: the date is validated only after write_day() (ROADMAP v1.7.4.3).
    check("Ist-Stand import: an invalid date still leaves a raw file behind",
          (cfg.RAW_DIR / f"garmin_raw_{_BAD_DATE}.json").exists())
    check("Ist-Stand import: ... and a summary file, but no quality log entry",
          (cfg.SUMMARY_DIR / f"garmin_{_BAD_DATE}.json").exists() and _BAD_DATE not in _ql)

# a wrong password in a dry run, and an unexpected error while writing one day
_r = _im.run_import_mirror(_arch, _M4H, "wrong password", dry_run=True)
check("import dry run: wrong password -> ok False with the reason, nothing to copy",
      _r["ok"] == False and _r["raw_to_copy"] == 0 and "HMAC" in _r["error"])
with _isolated_log_env("imp_pipeline") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(sys.modules["garmin_writer"], "write_day", side_effect=RuntimeError("disk exploded")):
        _r = _im.run_import_mirror(_arch, _b, "pw")
    check("import: an unexpected error while writing a day is counted, the import goes on",
          _r["raw_copied"] == 0 and _r["errors"] == 2 and _r["ok"] == False)
    check("import: days that failed unexpectedly get no quality log entry",
          quality._load_quality_log()["days"] == [])

# direct calls for the branches the full import cannot reach
with _isolated_log_env("imp_direct") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _c, _e = _im._import_context_from_bytes({}, ["context_data/x/raw/a.json"], _b)
    check("import context: bytes missing from the container -> counted as error",
          (_c, _e) == (0, 1))
    _c, _e = _im._import_context_from_bytes(
        {"context_data/x/raw/a.json": b"{not json"}, ["context_data/x/raw/a.json"], _b)
    check("import context: file that is not JSON -> counted as error", (_c, _e) == (0, 1))
    with patch.object(_ctx_writer, "write_file", return_value=False):
        _c, _e = _im._import_context_from_bytes(
            {"context_data/x/raw/a.json": b"{}"}, ["context_data/x/raw/a.json"], _b)
    check("import context: writer reporting failure -> counted as error", (_c, _e) == (0, 1))

    _c, _e = _im._import_source_from_bytes({}, [_SRC1], _b)
    check("import source: bytes missing from the container -> counted as error", (_c, _e) == (0, 1))
    _c, _e = _im._import_source_from_bytes({_SRC1: b"{not json"}, [_SRC1], _b)
    check("import source: file that is not JSON -> counted as error", (_c, _e) == (0, 1))
    _sw_mod = sys.modules["garmin_source_writer"]
    with patch.object(_sw_mod, "write_source", return_value=False):
        _c, _e = _im._import_source_from_bytes({_SRC1: b"{}"}, [_SRC1], _b)
    check("import source: writer reporting failure -> counted as error", (_c, _e) == (0, 1))

    _cp, _sk, _er = _im._import_raw_from_bytes({}, [{"quality": "high"}], 0, {"days": []}, quality, True)
    check("import raw: an order entry without a date -> counted as error",
          (_cp, _sk, _er) == (0, 0, 1))
    _cp, _sk, _er = _im._import_raw_folder(_b / "no_folder", _b, [{"quality": "high"}], 0,
                                           {"days": []}, quality)
    check("folder import raw: an order entry without a date -> counted as error",
          (_cp, _sk, _er) == (0, 0, 1))

    _im._restore_device_table({}, _b)
    check("restore device_table: not in the container -> nothing written, no crash",
          not (_b / "garmin_data" / "log" / "device_table.json").exists())
    with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
        _im._restore_device_table({"garmin_data/log/device_table.json": b"[]"}, _b)
    check("restore device_table: write failure -> no crash", True)

# -- Ist-Stand: a container path can lead out of base_dir (ROADMAP v1.7.4.3) -----------
_evil = _M4H / "evil.gla"
_craft_container(_evil, _mirror_sections(
    days=[], context={"context_data/../../escaped_probe.json": _jb({"x": 1})}))
with _isolated_log_env("imp_escape") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _archive = _b / "archive"
    _archive.mkdir()
    _r = _im.run_import_mirror(_evil, _archive, "pw")
    check("Ist-Stand import: a container path that climbs out of base_dir is not rejected",
          _r["ok"] == True and _r["context_copied"] == 1)
    check("Ist-Stand import: ... and the file is written outside base_dir",
          (_b / "escaped_probe.json").exists())

# -- legacy folder import ----------------------------------------------------------------
def _mirror_folder(root, days, raw_for=(), context=(), meta=True, qlog=True):
    root.mkdir(parents=True)
    if meta:
        (root / "mirror_meta.json").write_text(json.dumps({"gla_version": "test"}), encoding="utf-8")
    if qlog:
        (root / "garmin_data" / "log").mkdir(parents=True)
        (root / "garmin_data" / "log" / "quality_log.json").write_text(
            json.dumps({"days": [{"date": d, "quality": q, "source": s} for d, q, s in days]}),
            encoding="utf-8")
    for d in raw_for:
        p = root / "garmin_data" / "raw" / d / f"garmin_raw_{d}.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(_day_raw(d, "high")), encoding="utf-8")
    for sub, name, data in context:
        p = root / "context_data" / sub / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")


with _isolated_log_env("imp_folder") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _no_meta = _M4H / "f_nometa"
    _mirror_folder(_no_meta, [], meta=False)
    _r = _im._run_import_folder(_no_meta, _b, dry_run=False)
    check("folder import: mirror_meta.json missing -> error says so",
          _r["ok"] == False and "mirror_meta.json" in _r["error"])
    _r = _im._run_import_folder(_no_meta, _b, dry_run=True)
    check("folder import: mirror_meta.json missing in dry run -> ok False",
          _r["ok"] == False and _r["raw_to_copy"] == 0)
    _no_q = _M4H / "f_noqlog"
    _mirror_folder(_no_q, [], qlog=False)
    _r = _im._run_import_folder(_no_q, _b, dry_run=False)
    check("folder import: quality_log missing -> error says so",
          _r["ok"] == False and "quality_log" in _r["error"])
    _r = _im._run_import_folder(_no_q, _b, dry_run=True)
    check("folder import: quality_log missing in dry run -> ok False", _r["ok"] == False)

    _fold = _M4H / "f_good"
    _mirror_folder(_fold,
                   days=[(_D1, "high", "api"), (_D2, "high", "bulk"), (_BAD_DATE, "high", "api")],
                   raw_for=[_D1, _BAD_DATE],     # _D2 has no raw file in the folder
                   context=[("weather/raw", "2024-02-01.json", {"temp": 7}),
                            ("pollen/raw", "2024-02-01.json", {"birch": 1})])
    _r = _im.run_import_mirror(_fold, _b, "", dry_run=True)
    check("folder import dry run: counts days and context files, writes nothing",
          _r["ok"] == True and _r["raw_to_copy"] == 3 and _r["context_to_copy"] == 2
          and not cfg.RAW_DIR.exists())
    _r = _im.run_import_mirror(_fold, _b, "")
    check("folder import: day with files is imported, context files are copied",
          _r["raw_copied"] == 1 and _r["context_copied"] == 2
          and (cfg.RAW_DIR / f"garmin_raw_{_D1}.json").exists()
          and json.loads((_b / "context_data" / "weather" / "raw" / "2024-02-01.json")
                         .read_text(encoding="utf-8")) == {"temp": 7})
    check("folder import: a day without raw file and an invalid date count as errors",
          _r["errors"] == 2 and _r["ok"] == False)
    # Ist-Stand: same as the container import, write_day() runs before the date check.
    check("Ist-Stand folder import: an invalid date still leaves a raw file behind",
          (cfg.RAW_DIR / f"garmin_raw_{_BAD_DATE}.json").exists()
          and _BAD_DATE not in {e["date"] for e in quality._load_quality_log()["days"]})

    check("folder import: context delta lists only existing sub folders",
          len(_im._analyse_context_delta(_fold, _b)) == 2)
    with patch.object(_ctx_writer, "write_file", return_value=False):
        _c, _e = _im._import_context_folder(_fold, _b, _im._analyse_context_delta(_fold, _b))
    check("folder import: context writer failing -> counted as errors", (_c, _e) == (0, 2))
    _bad_ctx = _M4H / "f_badctx"
    _mirror_folder(_bad_ctx, [], context=[])
    (_bad_ctx / "context_data" / "weather" / "raw").mkdir(parents=True)
    (_bad_ctx / "context_data" / "weather" / "raw" / "x.json").write_text("{not json", encoding="utf-8")
    _c, _e = _im._import_context_folder(_bad_ctx, _b, _im._analyse_context_delta(_bad_ctx, _b))
    check("folder import: context file that is not JSON -> counted as error", (_c, _e) == (0, 1))

    _warn_fold = _M4H / "f_version"
    _mirror_folder(_warn_fold, [])
    sys.modules["version"].APP_VERSION = "9.9.9"
    _r = _im.run_import_mirror(_warn_fold, _b, "", dry_run=True)
    sys.modules["version"].APP_VERSION = "test"
    check("folder import: other GLA version -> warning names both versions",
          "test" in _r["version_warning"] and "9.9.9" in _r["version_warning"])

# ══════════════════════════════════════════════════════════════════════════════
#  4h2. garmin_import_mirror — exact failure results, version and schema decisions,
#       loops that must go on after a bad entry, skip_backup, small helpers
#       (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4h2. garmin_import_mirror — exact results, decisions, loops")


class _IMLog:
    """Stands in for _im.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def error(self, msg, *a, **k):
        self._add("error", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)


def _im_logged(fn, *args, **kwargs):
    real, rec = _im.log, _IMLog()
    _im.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        _im.log = real


def _no_error(res):
    return {k: v for k, v in res.items() if k != "error"}


_FAIL_RAW = {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0, "errors": 1, "ok": False}
_FAIL_DRY = {"raw_to_copy": 0, "context_to_copy": 0, "version_warning": "", "ok": False}

# -- 1. exact failure results --------------------------------------------------------------------
_unk = _M4H / "folder_plain"
_r = _im.run_import_mirror(_unk, _M4H, "pw")
check("4h2 unknown source: exact result",
      _r == {**_FAIL_RAW, "error": f"Not a recognised mirror source: {_unk}"})
_r = _im.run_import_mirror(_unk, _M4H, "pw", dry_run=True)
check("4h2 unknown source, dry run: exact result",
      _r == {**_FAIL_DRY, "error": f"Not a recognised mirror source: {_unk}"})
_r = _im.run_import_mirror(_arch, _M4H, "wrong password")
check("4h2 wrong password: exact result, reason names the HMAC",
      _no_error(_r) == _FAIL_RAW and "HMAC" in _r["error"])
_r = _im.run_import_mirror(_arch, _M4H, "wrong password", dry_run=True)
check("4h2 wrong password, dry run: exact result",
      _no_error(_r) == _FAIL_DRY and "HMAC" in _r["error"])

with _isolated_log_env("imp2_fail") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _nm = _M4H / "f2_nometa"
    _mirror_folder(_nm, [], meta=False)
    _r = _im._run_import_folder(_nm, _b, dry_run=False)
    check("4h2 folder without mirror_meta.json: exact result",
          _no_error(_r) == _FAIL_RAW and _r["error"].startswith("cannot read mirror_meta.json"))
    _r = _im._run_import_folder(_nm, _b, dry_run=True)
    check("4h2 folder without mirror_meta.json, dry run: exact result",
          _no_error(_r) == _FAIL_DRY and _r["error"].startswith("cannot read mirror_meta.json"))
    _nq = _M4H / "f2_noqlog"
    _mirror_folder(_nq, [], qlog=False)
    (_nq / "mirror_meta.json").write_text(json.dumps({"gla_version": "old"}), encoding="utf-8")
    _r = _im.run_import_mirror(_nq, _b, "")
    check("4h2 folder without quality_log: exact result",
          _no_error(_r) == _FAIL_RAW and _r["error"].startswith("cannot read mirror quality_log"))
    _r = _im.run_import_mirror(_nq, _b, "", dry_run=True)
    check("4h2 folder without quality_log, dry run: version warning is carried along",
          _no_error(_r) == {**_FAIL_DRY, "version_warning":
                            "Mirror was created with GLA vold, local version is vtest. Import will proceed."}
          and _r["error"].startswith("cannot read mirror quality_log"))

    # -- 2. a clean folder import ----------------------------------------------------------------
    _cl = _M4H / "f2_clean"
    _mirror_folder(_cl, [(_D1, "high", "api")], raw_for=[_D1],
                   context=[("weather/raw", "a.json", {"t": 1})])
    _r = _im.run_import_mirror(_cl, _b, "")
    check("4h2 clean folder import: exact result, ok True",
          _r == {"raw_copied": 1, "raw_skipped": 0, "context_copied": 1, "errors": 0, "ok": True})

# -- 3. version warning ------------------------------------------------------------------------------
check("4h2 version warning: same version -> empty, exact text otherwise",
      _im._build_version_warning({"gla_version": "test"}) == ""
      and _im._build_version_warning({"gla_version": "1.2.3"})
      == "Mirror was created with GLA v1.2.3, local version is vtest. Import will proceed."
      and _im._build_version_warning({})
      == "Mirror was created with GLA vunknown, local version is vtest. Import will proceed.")
_vf = _M4H / "f2_ver"


def _folder_with_version(root, ver):
    shutil.rmtree(root, ignore_errors=True)
    _mirror_folder(root, [])
    (root / "mirror_meta.json").write_text(json.dumps({"gla_version": ver}), encoding="utf-8")


with _isolated_log_env("imp2_ver") as _b:
    _folder_with_version(_vf, "test")
    check("4h2 folder: equal version (read from JSON) -> no warning",
          _im.run_import_mirror(_vf, _b, "", dry_run=True)["version_warning"] == "")
    sys.modules["version"].APP_VERSION = "zzz"
    _folder_with_version(_vf, "aaa")
    check("4h2 folder: mirror version lower than local -> warning with exact text",
          _im.run_import_mirror(_vf, _b, "", dry_run=True)["version_warning"]
          == "Mirror was created with GLA vaaa, local version is vzzz. Import will proceed.")
    sys.modules["version"].APP_VERSION = "test"
    _real_version = sys.modules["version"]
    sys.modules["version"] = _types4.ModuleType("version")     # no APP_VERSION at all
    try:
        _folder_with_version(_vf, "aaa")
        _rf = _im.run_import_mirror(_vf, _b, "", dry_run=True)
        _rc = _im.run_import_mirror(_arch, _b, "pw", dry_run=True)
        _bw = _im._build_version_warning({"gla_version": "x"})
    finally:
        sys.modules["version"] = _real_version
    check("4h2 version module without APP_VERSION: no warning, no crash (folder and container)",
          _rf["ok"] is True and _rf["version_warning"] == ""
          and _rc["ok"] is True and _rc["version_warning"] == "" and _bw == "")

# -- 4. schema decision ----------------------------------------------------------------------------------
_FASTPATH_D1 = {"marker": "from-container", "date": _D1}


def _summary_d1(_b):
    return json.loads((cfg.SUMMARY_DIR / f"garmin_{_D1}.json").read_text(encoding="utf-8"))


with _isolated_log_env("imp2_schema_low") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(normalizer, "CURRENT_SCHEMA_VERSION", 1):
        _r = _im.run_import_mirror(_arch, _b, "pw")
    check("4h2 schema: container schema newer than local -> summary recomputed, not taken",
          _r["ok"] is True and _summary_d1(_b) != _FASTPATH_D1
          and _summary_d1(_b).get("generated_by") == "garmin_normalizer.py")
with _isolated_log_env("imp2_schema_missing") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _stub_norm = _types4.ModuleType("garmin_normalizer")        # has no CURRENT_SCHEMA_VERSION
    _stub_norm.summarize = normalizer.summarize
    with patch.dict(sys.modules, {"garmin_normalizer": _stub_norm}):
        _r = _im.run_import_mirror(_arch, _b, "pw")
    check("4h2 schema: local schema version cannot be read -> summary recomputed",
          _r["ok"] is True and _summary_d1(_b) != _FASTPATH_D1)
with _isolated_log_env("imp2_schema_order") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    import garmin_container as _gcx
    with patch.object(_gcx, "fulfill_order", wraps=_gcx.fulfill_order) as _spy:
        _im.run_import_mirror(_arch, _b, "pw")
    _order_ok = _spy.call_args[0][2]
with _isolated_log_env("imp2_schema_order2") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(_gcx, "fulfill_order", wraps=_gcx.fulfill_order) as _spy2, \
         patch.object(normalizer, "CURRENT_SCHEMA_VERSION", 999):
        _im.run_import_mirror(_arch, _b, "pw")
    _order_bad = _spy2.call_args[0][2]
check("4h2 order: matching schema asks for raw, summary, context, source, device table",
      set(_order_ok) == {"raw", "summary", "context", "source", "quality_log"}
      and _order_ok["summary"] == [f"garmin_data/summary/garmin_{d}.json" for d in (_D1, _D2)]
      and _order_ok["quality_log"] == ["garmin_data/log/device_table.json"])
check("4h2 order: other schema -> no summary is requested",
      set(_order_bad) == {"raw", "context", "source", "quality_log"})

# -- 5. detect_source -----------------------------------------------------------------------------------------
with patch.object(_gcx, "is_container", side_effect=RuntimeError("probe failed")):
    check("4h2 detect_source: failing container check -> falls back to the folder check",
          _im.detect_source(_M4H / "folder_ok") == "folder"
          and _im.detect_source(_M4H / "folder_plain") == "unknown")
check("4h2 detect_source: a path that is not a path -> 'unknown', no crash",
      _im.detect_source(12345) == "unknown" and _im.detect_source(None) == "unknown")

# -- 6. delta rules: unknown quality labels rank lowest -----------------------------------------------------------
def _delta(src_q, dst_q):
    s = {"days": [{"date": "2024-05-01", **({"quality": src_q} if src_q else {})}]}
    d = {"days": [{"date": "2024-05-01", **({"quality": dst_q} if dst_q else {})}]}
    c, k = _im._analyse_raw_delta(s, d)
    return len(c), k


check("4h2 delta: unknown vs failed -> skipped (equal rank)", _delta("weird", "failed") == (0, 1))
check("4h2 delta: failed vs unknown -> skipped (equal rank)", _delta("failed", "weird") == (0, 1))
check("4h2 delta: standard vs unknown -> copied", _delta("standard", "weird") == (1, 0))
check("4h2 delta: unknown vs standard -> skipped", _delta("weird", "standard") == (0, 1))
check("4h2 delta: no quality label on either side counts as failed -> skipped",
      _delta(None, None) == (0, 1))
check("4h2 delta: high vs missing label -> copied", _delta("high", None) == (1, 0))

with _isolated_log_env("imp2_ctxdelta") as _b:
    (_b / "context_data" / "weather" / "raw").mkdir(parents=True)
    (_b / "context_data" / "weather" / "raw" / "there.json").write_text("{}", encoding="utf-8")
    _paths = ["context_data/weather/raw/there.json", "context_data/weather/raw/new.json"]
    _o, _c = _im_logged(_im._analyse_context_delta_container, _paths, _b)
    check("4h2 context delta (container): all files are ordered, only an existing one is logged as overwrite",
          _o == _paths
          and ("debug", "  import_mirror: context overwrite — context_data/weather/raw/there.json") in _c
          and not any("new.json" in m for _, m in _c if "overwrite" in m))

# -- 7. loops go on after a bad entry -------------------------------------------------------------------------------
_GOOD_SRC = b'{"heart_rates": {"x": 1}}'
with _isolated_log_env("imp2_loops") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _SRC_A = "garmin_data/source/garmin_source_2024-06-01.json"
    _SRC_B = "garmin_data/source/garmin_source_2024-06-02.json"
    _res, _calls = _im_logged(_im._import_source_from_bytes,
                              {_SRC_B: b"{not json", _SRC1: _GOOD_SRC}, [_SRC_A, _SRC_B, _SRC1], _b)
    check("4h2 source import: missing bytes and bad JSON do not stop the next file",
          _res == (1, 2) and (cfg.SOURCE_DIR / "garmin_source_2024-02-01.json").exists())
    check("4h2 source import: summary line with the counts is logged",
          ("info", "  import_mirror: source import done — 1 written, 2 errors") in _calls)
    _res, _calls = _im_logged(_im._import_source_from_bytes, {}, [], _b)
    check("4h2 source import: nothing to import -> (0, 0), no summary line",
          _res == (0, 0) and not any("source import done" in m for _, m in _calls))
    _res = _im._import_source_from_bytes({5: b"{}", _SRC1: _GOOD_SRC}, [5, _SRC1], _b)
    check("4h2 source import: an entry that is not a file name is one error, the next one still goes through",
          _res == (1, 1))

    _CT_OK = "context_data/x/raw/ok.json"
    _res = _im._import_context_from_bytes({_CT_OK: b'{"a": 1}'}, ["context_data/x/raw/missing.json", _CT_OK], _b)
    check("4h2 context import: missing bytes do not stop the next file",
          _res == (1, 1) and json.loads((_b / _CT_OK).read_text(encoding="utf-8")) == {"a": 1})

    _fl = {f"garmin_data/raw/garmin_raw_{_D1}.json": _jb(_day_raw(_D1)),
           f"garmin_data/raw/garmin_raw_{_BAD_DATE}.json": _jb(_day_raw(_BAD_DATE))}
    _res = _im._import_raw_from_bytes(_fl, [{"quality": "high"}, {"date": _D1, "quality": "high"}],
                                      0, {"days": []}, quality, True)
    check("4h2 raw import: an entry without a date does not stop the next day", _res == (1, 0, 1))
    _res, _calls = _im_logged(_im._import_raw_from_bytes, _fl,
                              [{"date": _BAD_DATE, "quality": "high"}, {"date": _D1, "quality": "high"}],
                              3, {"days": []}, quality, True)
    check("4h2 raw import: an invalid date is one error, the next day goes through, skipped count passed on",
          _res == (1, 3, 1))
    check("4h2 raw import: invalid date is logged as such, not as a pipeline error",
          any(lv == "warning" and "invalid date '2024-13-45'" in m for lv, m in _calls)
          and not any("pipeline error" in m for _, m in _calls))

    _fold2 = _M4H / "f2_loop"
    shutil.rmtree(_fold2, ignore_errors=True)
    _mirror_folder(_fold2, [], raw_for=[_D2])
    _res = _im._import_raw_folder(_fold2, _b, [{"quality": "high"}, {"date": _D2, "quality": "high"}],
                                  4, {"days": []}, quality)
    check("4h2 folder raw import: an entry without a date does not stop the next day, skipped passed on",
          _res == (1, 4, 1))
    _only_pollen = _M4H / "f2_pollen"
    shutil.rmtree(_only_pollen, ignore_errors=True)
    _mirror_folder(_only_pollen, [], context=[("pollen/raw", "a.json", {"x": 1})])
    _o = _im._analyse_context_delta(_only_pollen, _b)
    check("4h2 folder context delta: a missing first sub folder does not hide the later ones",
          len(_o) == 1 and _o[0][0].name == "a.json" and "pollen" in str(_o[0][1]))

# -- 9. skip_backup: per day without backup, one backup at the end -------------------------------------------------------
with _isolated_log_env("imp2_skip") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
        _im.run_import_mirror(_arch, _b, "pw")
    _kw = [c.kwargs for c in _sv.call_args_list]
    check("4h2 skip_backup (container): every day saved with skip_backup=True, final save without",
          _kw == [{"skip_backup": True}, {"skip_backup": True}, {}])
with _isolated_log_env("imp2_skip_f") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _fs = _M4H / "f2_skip"
    shutil.rmtree(_fs, ignore_errors=True)
    _mirror_folder(_fs, [(_D1, "high", "api"), (_D2, "high", "api")], raw_for=[_D1, _D2])
    with patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
        _im.run_import_mirror(_fs, _b, "")
    _kw = [c.kwargs for c in _sv.call_args_list]
    check("4h2 skip_backup (folder): every day saved with skip_backup=True, final save without",
          _kw == [{"skip_backup": True}, {"skip_backup": True}, {}])

# -- 10. device table restore, 11. device extraction ------------------------------------------------------------------------
with _isolated_log_env("imp2_dt") as _b:
    _DT = "garmin_data/log/device_table.json"
    _, _c1 = _im_logged(_im._restore_device_table, {_DT: b"[1]"}, _b)
    _, _c2 = _im_logged(_im._restore_device_table, {_DT: b"[2]"}, _b)
    check("4h2 restore device_table: a second restore into the existing folder replaces the file",
          (_b / "garmin_data" / "log" / "device_table.json").read_bytes() == b"[2]")
    check("4h2 restore device_table: success is logged, absence is logged as skipped",
          ("info", "  import_mirror: device_table.json restored") in _c1
          and ("info", "  import_mirror: device_table.json restored") in _c2
          and ("debug", "  import_mirror: device_table.json not in container — skipped")
          in _im_logged(_im._restore_device_table, {}, _b)[1])
check("4h2 _extract_device: with two recorded devices the first one wins",
      _im._extract_device({"training_status": {"mostRecentTrainingStatus": {"recordedDevices": [
          {"deviceId": 1, "deviceName": "A"}, {"deviceId": 2, "deviceName": "B"}]}}}) == ("1", "A"))

if _ver4h_added:
    del sys.modules["version"]
if _src_root_added:
    sys.path.remove(_SRC_ROOT_4H)

# lock() and the version warning import version.APP_VERSION, which is not on the
# test path; this section registers its own stub, as Section C does in
# test_container_mirror.py (setdefault, stays until the process ends).
_ver_stub = _types4.ModuleType("version")
_ver_stub.APP_VERSION = "test"
sys.modules.setdefault("version", _ver_stub)

# ══════════════════════════════════════════════════════════════════════════════
#  C4. garmin_import_mirror — detect_source
# ══════════════════════════════════════════════════════════════════════════════
section("C4. garmin_import_mirror — detect_source")
import garmin_import_mirror as _import_mirror
importlib.reload(_import_mirror)

# C4a — Valider Container → "container"
_c4_parent = Path(tempfile.mkdtemp(prefix="garmin_c4_"))
_c4_gla    = _c4_parent / "mirror_c4.gla"
_c4_src    = Path(tempfile.mkdtemp(prefix="garmin_c4_src_"))
(_c4_src / "garmin_data" / "log").mkdir(parents=True)
(_c4_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": []}), encoding="utf-8"
)
mirror.run_mirror(_c4_src, _c4_gla, "pw")
check("detect_source: valid .gla → 'container'",
      _import_mirror.detect_source(_c4_gla) == "container")

# C4b — Nicht-existenter Pfad → "unknown"
check("detect_source: nonexistent path → 'unknown'",
      _import_mirror.detect_source(_c4_parent / "ghost.gla") == "unknown")

# C4c — Normaler Ordner ohne mirror_meta.json → "unknown"
_c4_plain_dir = Path(tempfile.mkdtemp(prefix="garmin_c4_plain_"))
check("detect_source: plain dir without mirror_meta → 'unknown'",
      _import_mirror.detect_source(_c4_plain_dir) == "unknown")

# C4d — run_import_mirror: falsches Passwort → "error"-Feld (v1.6.5.7,
# Netz 3 Kandidat 1 — der belegte Fall, der die Untersuchung ausgelöst hat)
_c4_base = Path(tempfile.mkdtemp(prefix="garmin_c4_base_"))
_c4_wrongpw = _import_mirror.run_import_mirror(
    mirror_path=_c4_gla, base_dir=_c4_base, password="wrong-pw", dry_run=True,
)
check("run_import_mirror: wrong password → ok=False",
      _c4_wrongpw["ok"] == False)
check("run_import_mirror: wrong password → error field present",
      bool(_c4_wrongpw.get("error")))
check("run_import_mirror: wrong password → error is not the old generic text",
      _c4_wrongpw.get("error") != "Could not read mirror data.")

# C4e — run_import_mirror: unbekannte Quelle → "error"-Feld
_c4_unknown = _import_mirror.run_import_mirror(
    mirror_path=_c4_parent / "ghost.gla", base_dir=_c4_base,
    password="pw", dry_run=True,
)
check("run_import_mirror: unknown source → ok=False",
      _c4_unknown["ok"] == False)
check("run_import_mirror: unknown source → error field present",
      bool(_c4_unknown.get("error")))
check("run_import_mirror: unknown source → error mentions path",
      str(_c4_parent / "ghost.gla") in _c4_unknown.get("error", ""))

shutil.rmtree(_c4_base, ignore_errors=True)

# C4f — run_import_mirror: gla_version im Container weicht von APP_VERSION
# ab → version_warning enthält beide Versionsnummern, ok bleibt
# unbeeinflusst (v1.6.5.8, Netz 2 Priorität 1 — Mirror-Versions-Ergänzung).
# Container wird mit einer abweichenden gestubten APP_VERSION gepackt,
# dann vor dem Import auf den regulären Stub-Wert zurückgesetzt — der
# Mismatch muss aus dem Container kommen, nicht aus einer noch gepatchten
# lokalen Version.
_c4f_orig_version = _ver_stub.APP_VERSION
_ver_stub.APP_VERSION = "9.9.9"

_c4f_parent = Path(tempfile.mkdtemp(prefix="garmin_c4f_"))
_c4f_gla    = _c4f_parent / "mirror_c4f.gla"
_c4f_src    = Path(tempfile.mkdtemp(prefix="garmin_c4f_src_"))
(_c4f_src / "garmin_data" / "log").mkdir(parents=True)
(_c4f_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": []}), encoding="utf-8"
)
mirror.run_mirror(_c4f_src, _c4f_gla, "pw")

_ver_stub.APP_VERSION = _c4f_orig_version

_c4f_base = Path(tempfile.mkdtemp(prefix="garmin_c4f_base_"))
_c4f_result = _import_mirror.run_import_mirror(
    mirror_path=_c4f_gla, base_dir=_c4f_base, password="pw", dry_run=True,
)
check("run_import_mirror: version mismatch → ok=True (import proceeds anyway)",
      _c4f_result["ok"] == True)
check("run_import_mirror: version mismatch → version_warning present",
      bool(_c4f_result.get("version_warning")))
check("run_import_mirror: version mismatch → warning contains container version",
      "9.9.9" in _c4f_result.get("version_warning", ""))
check("run_import_mirror: version mismatch → warning contains local version",
      _c4f_orig_version in _c4f_result.get("version_warning", ""))

shutil.rmtree(_c4f_src,    ignore_errors=True)
shutil.rmtree(_c4f_parent, ignore_errors=True)
shutil.rmtree(_c4f_base,   ignore_errors=True)

# Aufräumen C4
shutil.rmtree(_c4_src,       ignore_errors=True)
shutil.rmtree(_c4_parent,    ignore_errors=True)
shutil.rmtree(_c4_plain_dir, ignore_errors=True)

summary()
