#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_writer.py — garmin_writer

Run from the project folder:
    python tests/test_writer.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  5. garmin_writer
# ══════════════════════════════════════════════════════════════════════════════
section("5. garmin_writer")
import garmin_writer as writer
import garmin_normalizer as normalizer

norm_w   = {"date": "2024-04-01", "heart_rates": {"restingHeartRate": 55}}
summary_w = normalizer.summarize(norm_w)

ok = writer.write_day(norm_w, summary_w, "2024-04-01")
raw_p = cfg.RAW_DIR     / "garmin_raw_2024-04-01.json"
sum_p = cfg.SUMMARY_DIR / "garmin_2024-04-01.json"

check("write_day: returns True",           ok == True)
check("write_day: raw file created",       raw_p.exists())
check("write_day: summary file created",   sum_p.exists())
check("write_day: raw date correct",       json.loads(raw_p.read_text())["date"] == "2024-04-01")
check("write_day: generated_by normalizer",
      json.loads(sum_p.read_text()).get("generated_by") == "garmin_normalizer.py")

# read_summary — missing file → {}
check("read_summary: missing file → {}",   writer.read_summary("1900-01-01") == {})

# ══════════════════════════════════════════════════════════════════════════════
#  5b. garmin_writer — failure paths (v1.7.4.0.2)
# ══════════════════════════════════════════════════════════════════════════════
section("5b. garmin_writer — failure paths")


def _tmp_leftovers():
    return (list(cfg.RAW_DIR.glob("*.tmp")) + list(cfg.SUMMARY_DIR.glob("*.tmp")))


# -- failed write must leave the already archived day untouched ----------------
_D5B     = "2024-04-02"
_raw5b   = cfg.RAW_DIR     / f"garmin_raw_{_D5B}.json"
_sum5b   = cfg.SUMMARY_DIR / f"garmin_{_D5B}.json"
_good_raw = {"date": _D5B, "heart_rates": {"restingHeartRate": 50}}
_good_sum = normalizer.summarize(_good_raw)
check("5b setup: initial write_day succeeds",
      writer.write_day(_good_raw, _good_sum, _D5B) == True)
_raw_before = _raw5b.read_bytes()
_sum_before = _sum5b.read_bytes()

# summary that cannot be stored as JSON: the raw temp file already exists when
# the second write fails
_bad_summary = {"date": _D5B, "unserialisable": object()}
_new_raw     = {"date": _D5B, "heart_rates": {"restingHeartRate": 99}}
check("write_day: unserialisable summary -> returns False",
      writer.write_day(_new_raw, _bad_summary, _D5B) == False)
check("write_day: failed write leaves archived raw file byte-identical",
      _raw5b.read_bytes() == _raw_before)
check("write_day: failed write leaves archived summary file byte-identical",
      _sum5b.read_bytes() == _sum_before)
check("write_day: failed write leaves no .tmp file behind",
      _tmp_leftovers() == [])

# -- failed write for a day that was never archived ----------------------------
_D5C = "2024-04-03"
check("write_day: failed write of a new day -> returns False",
      writer.write_day(_new_raw, _bad_summary, _D5C) == False)
check("write_day: failed write of a new day creates neither raw nor summary",
      not (cfg.RAW_DIR / f"garmin_raw_{_D5C}.json").exists()
      and not (cfg.SUMMARY_DIR / f"garmin_{_D5C}.json").exists())
check("write_day: failed write of a new day leaves no .tmp file behind",
      _tmp_leftovers() == [])

# -- cleanup itself failing must not crash -------------------------------------
_D5D = "2024-04-04"
with patch.object(Path, "unlink", side_effect=OSError("cleanup blocked")):
    _ok_cleanup_fail = writer.write_day(_new_raw, _bad_summary, _D5D)
check("write_day: failing cleanup (OSError on unlink) -> no crash, returns False",
      _ok_cleanup_fail == False)
for _left in _tmp_leftovers():      # the blocked cleanup left the raw temp file
    _left.unlink()

# -- backup trigger failures are non-fatal --------------------------------------
import garmin_backup as _gb5b
_D5E = "2024-04-05"
with patch.object(_gb5b, "backup_raw", side_effect=RuntimeError("backup broke")):
    _ok_backup_err = writer.write_day(_good_raw, _good_sum, _D5E)
check("write_day: backup trigger raising -> still returns True",
      _ok_backup_err == True)
check("write_day: backup trigger raising -> raw and summary were written",
      (cfg.RAW_DIR / f"garmin_raw_{_D5E}.json").exists()
      and (cfg.SUMMARY_DIR / f"garmin_{_D5E}.json").exists())

_D5F = "2024-04-06"
with patch.dict(sys.modules, {"garmin_backup": None}):   # import raises ImportError
    _ok_no_backup = writer.write_day(_good_raw, _good_sum, _D5F)
check("write_day: backup module not importable -> still returns True",
      _ok_no_backup == True)
check("write_day: backup module not importable -> files written",
      (cfg.RAW_DIR / f"garmin_raw_{_D5F}.json").exists()
      and (cfg.SUMMARY_DIR / f"garmin_{_D5F}.json").exists())

# -- read_summary --------------------------------------------------------------
check("read_summary: valid file is returned as stored",
      writer.read_summary(_D5B) == json.loads(_sum5b.read_text(encoding="utf-8")))
_D5G = "2024-04-07"
(cfg.SUMMARY_DIR / f"garmin_{_D5G}.json").write_text("{not valid json", encoding="utf-8")
check("read_summary: corrupt file -> {} (no crash)",
      writer.read_summary(_D5G) == {})

# ══════════════════════════════════════════════════════════════════════════════
#  10. garmin_writer — read_raw
# ══════════════════════════════════════════════════════════════════════════════
section("10. garmin_writer — read_raw")

# Happy path — file written by write_day, read back by read_raw
raw_rr = {"date": "2024-05-01", "heart_rates": {"restingHeartRate": 60}}
writer.write_day(raw_rr, normalizer.summarize(raw_rr), "2024-05-01")
result_rr = writer.read_raw("2024-05-01")
check("read_raw: returns dict",           isinstance(result_rr, dict))
check("read_raw: date correct",           result_rr.get("date") == "2024-05-01")
check("read_raw: content preserved",      result_rr.get("heart_rates", {}).get("restingHeartRate") == 60)

# File not found → empty dict
result_missing = writer.read_raw("1900-01-01")
check("read_raw: missing → empty dict",   result_missing == {})

# Corrupt JSON → empty dict
corrupt_path = cfg.RAW_DIR / "garmin_raw_2024-05-02.json"
corrupt_path.write_text("{ not valid json }")
result_corrupt = writer.read_raw("2024-05-02")
check("read_raw: corrupt → empty dict",   result_corrupt == {})

# ══════════════════════════════════════════════════════════════════════════════
#  5c. garmin_writer — exact file contents and a summary folder with missing
#      parents (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("5c. garmin_writer — exact files, nested folder")
from gla_testenv import _isolated_log_env

_D5C = "2024-04-05"
_NORM5C = {"date": _D5C, "name": "Grüße", "nested": {"a": [1, 2]}}
_SUM5C = {"date": _D5C, "label": "Größe"}
with _isolated_log_env("w5c_fmt") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    check("5c write_day: returns True", writer.write_day(_NORM5C, _SUM5C, _D5C) is True)
    check("5c write_day: raw file is 2-space indented UTF-8 (umlauts not escaped), byte for byte (line ends normalised: write_text uses CRLF on Windows)",
          (cfg.RAW_DIR / f"garmin_raw_{_D5C}.json").read_bytes().replace(b"\r\n", b"\n")
          == ('{\n  "date": "2024-04-05",\n  "name": "Grüße",\n  "nested": {\n    "a": [\n'
              '      1,\n      2\n    ]\n  }\n}').encode("utf-8"))
    check("5c write_day: summary file is 2-space indented UTF-8, byte for byte",
          (cfg.SUMMARY_DIR / f"garmin_{_D5C}.json").read_bytes().replace(b"\r\n", b"\n")
          == '{\n  "date": "2024-04-05",\n  "label": "Größe"\n}'.encode("utf-8"))

with _isolated_log_env("w5c_deep") as _b:
    cfg.SUMMARY_DIR = _b / "a" / "b" / "summary"
    check("5c write_day: a summary folder with several missing parents is created",
          writer.write_day(_NORM5C, _SUM5C, _D5C) is True
          and (cfg.SUMMARY_DIR / f"garmin_{_D5C}.json").is_file())

# ══════════════════════════════════════════════════════════════════════════════
#  5d. garmin_writer — write_summary_only() (v1.7.4.5)
# ══════════════════════════════════════════════════════════════════════════════
section("5d. garmin_writer — write_summary_only()")

import garmin_backup as _gb5d

# -- happy path: only summary/ is written, raw/ and backup are never touched --
with _isolated_log_env("w5d_happy") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _D5H   = "2024-04-08"
    _sum5h = normalizer.summarize({"date": _D5H, "heart_rates": {"restingHeartRate": 58}})
    with patch.object(_gb5d, "backup_raw") as _br5h:
        _ok_5h = writer.write_summary_only(_sum5h, _D5H)
    check("write_summary_only: returns True", _ok_5h == True)
    check("write_summary_only: summary file created",
          (cfg.SUMMARY_DIR / f"garmin_{_D5H}.json").exists())
    check("write_summary_only: no raw file is created",
          not (cfg.RAW_DIR / f"garmin_raw_{_D5H}.json").exists())
    check("write_summary_only: backup_raw() is never called",
          not _br5h.called)

    # -- an already-archived raw file stays byte-identical ------------------------
    _D5I     = "2024-04-09"
    _raw5i   = {"date": _D5I, "heart_rates": {"restingHeartRate": 61}}
    _sum5i_1 = normalizer.summarize(_raw5i)
    check("5i setup: write_day archives raw + summary for comparison",
          writer.write_day(_raw5i, _sum5i_1, _D5I) == True)
    _raw5i_before = (cfg.RAW_DIR / f"garmin_raw_{_D5I}.json").read_bytes()

    _sum5i_2 = {**_sum5i_1, "schema_version": _sum5i_1.get("schema_version", 0) + 1}
    check("write_summary_only: rewriting the summary leaves the archived raw file byte-identical",
          writer.write_summary_only(_sum5i_2, _D5I) == True
          and (cfg.RAW_DIR / f"garmin_raw_{_D5I}.json").read_bytes() == _raw5i_before)
    check("write_summary_only: the summary file itself is updated",
          json.loads((cfg.SUMMARY_DIR / f"garmin_{_D5I}.json").read_text(encoding="utf-8"))["schema_version"]
          == _sum5i_2["schema_version"])

    # -- failure path: unserialisable summary -> False, no .tmp left behind -------
    _D5J        = "2024-04-10"
    _bad_sum_5j = {"date": _D5J, "unserialisable": object()}
    check("write_summary_only: unserialisable summary -> returns False",
          writer.write_summary_only(_bad_sum_5j, _D5J) == False)
    check("write_summary_only: failed write creates no summary file",
          not (cfg.SUMMARY_DIR / f"garmin_{_D5J}.json").exists())
    check("write_summary_only: failed write leaves no .tmp file behind",
          _tmp_leftovers() == [])

# ══════════════════════════════════════════════════════════════════════════════
#  5e. garmin_writer — resolved summary (v1.7.6.1)
# ══════════════════════════════════════════════════════════════════════════════
section("5e. garmin_writer — resolved summary: API data plus the export's values")

import copy as _copy5e
import garmin_bulk_writer as _bw5e
from gla_testenv import _isolated_log_env as _iso5e

_H5E = "ab" * 32
_D = "2024-05-10"
_API = {"date": _D,
        "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 28800, "deepSleepSeconds": 7200}},
        "heart_rates": {"restingHeartRate": 52, "heartRateValues": [[1715300000000, 60], [1715300060000, 70]]},
        "user_summary": {"totalSteps": 1000}}
_AGGS = {"date": _D,
         "user_summary": {"totalSteps": 9000, "restingHeartRate": 55, "totalKilocalories": 2500},
         "stress": {"averageStressLevel": 30, "maxStressLevel": 80},
         "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 20000}},
         "training_readiness": {"level": "HIGH"}}


def _paths(d):
    return cfg.RAW_DIR / f"garmin_raw_{d}.json", cfg.SUMMARY_DIR / f"garmin_{d}.json"


def _agg_put(d, aggs, files=(_H5E,)):
    assert _bw5e.write_aggregates(d, aggs, list(files)) == _bw5e.WRITTEN


def _expected(api, aggs):
    """What the day must come out as, built by hand: the API keys that are not empty stay, the export fills the
    rest; a section both sides hold as a dict is filled field by field (v1.7.6.3), activities as a whole only."""
    bulk = normalizer.normalize(_copy5e.deepcopy(aggs), source="bulk")
    out = dict(api)
    for k, v in bulk.items():
        if k != "activities" and isinstance(out.get(k), dict) and out[k] and isinstance(v, dict):
            out[k] = {**{f: x for f, x in v.items() if f not in out[k] or out[k][f] in (None, "", [], {})}, **{
                f: x for f, x in out[k].items() if x not in (None, "", [], {})}}
        elif not out.get(k):
            out[k] = v
    return normalizer.summarize(out)


with _iso5e("w5e_resolve") as _b:
    cfg.SUMMARY_DIR = _b / "summary"

    # -- without an aggregates file nothing changes ---------------------------------
    _own = {"date": _D, "marker": "the summary that was passed in"}
    with patch.object(_gb5d, "backup_raw") as _br:
        check("5e no aggregates: write_day writes the passed summary and the passed raw, backup is triggered once",
              writer.write_day(_API, _own, _D) is True and _br.call_count == 1 and _br.call_args.args == (_D,))
    _rp, _sp = _paths(_D)
    check("5e no aggregates: summary is exactly the one passed in, raw is exactly the passed dict",
          json.loads(_sp.read_text(encoding="utf-8")) == _own and json.loads(_rp.read_text(encoding="utf-8")) == _API)

    # -- with an aggregates file: the summary is resolved, raw/ stays pure API -----
    _agg_put(_D, _AGGS)
    _api_before, _agg_bytes = _copy5e.deepcopy(_API), (cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_D}.json").read_bytes()
    with patch.object(_gb5d, "backup_raw") as _br:
        check("5e aggregates: write_day returns True and triggers the backup once",
              writer.write_day(_API, _own, _D) is True and _br.call_count == 1)
    _summary = json.loads(_sp.read_text(encoding="utf-8"))
    check("5e aggregates: the summary is the resolved one, not the one passed in", _summary == _expected(_API, _AGGS) and "marker" not in _summary)
    check("5e aggregates: the API keys that are not empty win (steps 1000, sleep 28800 s, API heart rate series and resting 52)",
          _summary["day"]["steps"] == 1000 and _summary["sleep"]["duration_h"] == 8.0 and _summary["heartrate"]["resting_bpm"] == 52
          and _summary["heartrate"]["avg_bpm"] == 65.0)
    check("5e aggregates: what the API lacks comes from the export (stress average 30 and maximum 80)",
          _summary["stress"]["stress_avg"] == 30 and _summary["stress"]["stress_max"] == 80)
    check("5e aggregates: raw/ keeps only what was passed in, none of the export's keys",
          json.loads(_rp.read_text(encoding="utf-8")) == _API and "stress" not in json.loads(_rp.read_text(encoding="utf-8")))
    check("5e aggregates: neither the passed dict nor the stored aggregates file is changed",
          _API == _api_before and (cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_D}.json").read_bytes() == _agg_bytes)
    check("5e aggregates: the summary has the current schema version", _summary["schema_version"] == normalizer.CURRENT_SCHEMA_VERSION)
    _first = _sp.read_bytes()
    writer.write_day(_API, _own, _D)
    check("5e aggregates: writing the same day again gives the same bytes (idempotent)", _sp.read_bytes() == _first)

    # -- an empty API key is filled, the heart-rate remap of an import day applies ---
    _D2 = "2024-05-11"
    _api2 = {"date": _D2, "stress": {}, "user_summary": {"totalSteps": 500}}
    _agg_put(_D2, {**_AGGS, "date": _D2})
    writer.write_day(_api2, {"date": _D2}, _D2)
    _s2 = json.loads(_paths(_D2)[1].read_text(encoding="utf-8"))
    check("5e aggregates: an empty API key (stress {}) is filled from the export",
          _s2["stress"]["stress_avg"] == 30 and _s2["day"]["steps"] == 500)
    check("5e aggregates: an API day without heart_rates gets the resting heart rate through the import remap (55)",
          _s2["heartrate"]["resting_bpm"] == 55 and _s2 == _expected(_api2, {**_AGGS, "date": _D2}))

    # -- write_summary_only resolves as well (the API data come from raw/) ----------
    with patch.object(_gb5d, "backup_raw") as _br:
        check("5e write_summary_only: returns True, no backup, the resolved summary replaces the passed one",
              writer.write_summary_only(_own, _D) is True and not _br.called
              and json.loads(_sp.read_text(encoding="utf-8")) == _expected(_API, _AGGS))
    _D3 = "2024-05-12"
    check("5e write_summary_only: a day without aggregates writes exactly the passed summary",
          writer.write_summary_only({"date": _D3, "marker": 1}, _D3) is True
          and json.loads(_paths(_D3)[1].read_text(encoding="utf-8")) == {"date": _D3, "marker": 1})

    # -- _resolve itself: pure, the API wins per field (v1.7.6.3; before: per top-level key), the export fills the rest ---
    _a0, _g0 = _copy5e.deepcopy(_API), _copy5e.deepcopy(_AGGS)
    _res = writer._resolve(_API, _AGGS)
    check("5e _resolve: neither the API dict nor the aggregates dict is changed (the import remap works on a copy)",
          _API == _a0 and _AGGS == _g0 and "heart_rates" not in _AGGS)
    check("5e _resolve: API fields stay as they are (steps 1000), fields the API lacks come from the export (v1.7.6.3), the heart_rates remap does not displace the API series",
          _res["user_summary"] == {"totalSteps": 1000, "restingHeartRate": 55, "totalKilocalories": 2500}
          and _res["heart_rates"] == _API["heart_rates"] and _res["sleep"] == _API["sleep"])
    check("5e _resolve: keys the API does not have come from the export as a whole",
          _res["stress"] == _AGGS["stress"] and _res["training_readiness"] == _AGGS["training_readiness"])
    check("5e _resolve: no API data at all -> the normalised export values (heart_rates remap included)",
          writer._resolve({}, _AGGS)["heart_rates"] == {"restingHeartRate": 55}
          and writer._resolve(None, _AGGS)["user_summary"] == _AGGS["user_summary"])

    # -- rebuild_summary ---------------------------------------------------------------
    _D4 = "2024-05-13"
    _agg_put(_D4, {**_AGGS, "date": _D4})
    with patch.object(_gb5d, "backup_raw") as _br:
        check("5e rebuild_summary: a day without a raw file is derived from the aggregates alone",
              writer.rebuild_summary(_D4) is True and not _br.called and not _paths(_D4)[0].exists()
              and json.loads(_paths(_D4)[1].read_text(encoding="utf-8"))
              == normalizer.summarize(normalizer.normalize(_copy5e.deepcopy({**_AGGS, "date": _D4}), source="bulk")))
    check("5e rebuild_summary: a day with raw and aggregates is derived from both, raw stays byte-identical",
          (lambda before: writer.rebuild_summary(_D) is True and _rp.read_bytes() == before
           and json.loads(_sp.read_text(encoding="utf-8")) == _expected(_API, _AGGS))(_rp.read_bytes()))
    _D5 = "2024-05-14"
    writer.write_day(_API | {"date": _D5}, {"date": _D5}, _D5)
    os_summary = _paths(_D5)[1]
    os_summary.unlink()
    check("5e rebuild_summary: a day with a raw file and no aggregates is derived from raw alone",
          writer.rebuild_summary(_D5) is True and json.loads(os_summary.read_text(encoding="utf-8")) == normalizer.summarize(_API | {"date": _D5}))
    check("5e rebuild_summary: nothing to derive from (no raw, no aggregates) -> False, no file",
          writer.rebuild_summary("2024-05-15") is False and not _paths("2024-05-15")[1].exists())
    check("5e rebuild_summary: a date that is no date -> False, nothing created",
          all(writer.rebuild_summary(d) is False for d in ("../../x", "2024-13-40", "", None, "20240515")))

    # -- unreadable aggregates: nothing is written, the stored files stay ------------
    _agg_file = cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_D}.json"
    _real_rt = Path.read_text

    def _locked(self, *a, **k):
        if self == _agg_file:
            raise PermissionError("locked by another process")
        return _real_rt(self, *a, **k)

    _raw_b, _sum_b = _rp.read_bytes(), _sp.read_bytes()
    with patch.object(Path, "read_text", _locked):
        check("5e unreadable aggregates: write_day writes nothing and returns False",
              writer.write_day({**_API, "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 1}}}, _own, _D) is False
              and _rp.read_bytes() == _raw_b and _sp.read_bytes() == _sum_b and _tmp_leftovers() == [])
        check("5e unreadable aggregates: write_summary_only and rebuild_summary write nothing and return False",
              writer.write_summary_only(_own, _D) is False and writer.rebuild_summary(_D) is False and _sp.read_bytes() == _sum_b)
    check("5e unreadable aggregates: with the lock gone the day is written again", writer.write_day(_API, _own, _D) is True)

    # -- damaged aggregates, a newer schema, unusable content: as if there were none, with a warning
    for _label, _content in (("damaged (not JSON)", "{ not json"),
                             ("a newer schema", json.dumps({"date": _D, "schema_version": _bw5e.AGG_SCHEMA_VERSION + 1, "source_files": [_H5E], "aggregates": _AGGS})),
                             ("an empty aggregates dict", json.dumps({"date": _D, "schema_version": 1, "source_files": [_H5E], "aggregates": {}})),
                             ("aggregates that are no dict", json.dumps({"date": _D, "schema_version": 1, "source_files": [_H5E], "aggregates": [1]})),
                             ("no schema_version", json.dumps({"date": _D, "source_files": [_H5E], "aggregates": _AGGS}))):
        _agg_file.write_text(_content, encoding="utf-8")
        with patch.object(writer.log, "warning") as _w, patch.object(_bw5e.log, "warning") as _wb:
            _ok = writer.write_day(_API, {"date": _D, "marker": "passed"}, _D)
        check(f"5e {_label}: treated as missing, the passed summary is written, a warning is logged (by the writer or the loader)",
              _ok is True and json.loads(_sp.read_text(encoding="utf-8")) == {"date": _D, "marker": "passed"} and (_w.called or _wb.called))
        check(f"5e {_label}: rebuild_summary derives from raw alone",
              writer.rebuild_summary(_D) is True and json.loads(_sp.read_text(encoding="utf-8")) == normalizer.summarize(_API))
    _agg_file.unlink()

    # -- a raw file that exists but cannot be read: no summary is derived -------------
    _agg_put(_D, _AGGS)
    _rp.write_text("{ not json", encoding="utf-8")
    _sum_c = _sp.read_bytes()
    check("5e unreadable raw with aggregates: write_summary_only and rebuild_summary write nothing and return False",
          writer.write_summary_only(_own, _D) is False and writer.rebuild_summary(_D) is False and _sp.read_bytes() == _sum_c)

# ══════════════════════════════════════════════════════════════════════════════
#  5f. support-tools/archive-maintenance/regenerate_summaries.py (v1.7.6.1)
# ══════════════════════════════════════════════════════════════════════════════
section("5f. regenerate_summaries.py — summaries from raw/ and the export data, through the writer")

import importlib.util as _ilu5f
import io as _io5f
from contextlib import redirect_stdout as _redir5f

_rs_path = Path(__file__).parent.parent / "support-tools" / "archive-maintenance" / "regenerate_summaries.py"
_rs_spec = _ilu5f.spec_from_file_location("regenerate_summaries_under_test", _rs_path)
_rs = _ilu5f.module_from_spec(_rs_spec)
_rs_spec.loader.exec_module(_rs)


def _run_rs():
    buf = _io5f.StringIO()
    code = None
    with _redir5f(buf):
        try:
            _rs.main()
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


with _iso5e("w5f_regen") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _R1, _R2, _R3, _R4 = "2024-06-01", "2024-06-02", "2024-06-03", "2024-06-04"
    cfg.RAW_DIR.mkdir(parents=True)
    _raw1 = {"date": _R1, "heart_rates": {"restingHeartRate": 50}}
    _raw2 = {"date": _R2, "user_summary": {"totalSteps": 222}}
    for _d, _r in ((_R1, _raw1), (_R2, _raw2)):
        (cfg.RAW_DIR / f"garmin_raw_{_d}.json").write_text(json.dumps(_r), encoding="utf-8")
    (cfg.RAW_DIR / f"garmin_raw_{_R4}.json").write_text("{ not json", encoding="utf-8")           # a broken raw file
    (cfg.RAW_DIR / "garmin_raw_junk.json").write_text("{}", encoding="utf-8")                      # no day
    for _d in (_R2, _R3):
        _agg_put(_d, {**_AGGS, "date": _d})
    _orphan = cfg.SUMMARY_DIR / "garmin_2024-06-30.json"
    cfg.SUMMARY_DIR.mkdir(parents=True)
    _orphan.write_text('{"date": "2024-06-30", "old": true}', encoding="utf-8")
    _raw_bytes = {f.name: f.read_bytes() for f in cfg.RAW_DIR.iterdir()}
    _code, _out = _run_rs()
    _ss = lambda d: json.loads((cfg.SUMMARY_DIR / f"garmin_{d}.json").read_text(encoding="utf-8"))   # noqa: E731
    check("5f regenerate_summaries: a day with a raw file gets summarize(raw)", _ss(_R1) == normalizer.summarize(_raw1))
    check("5f regenerate_summaries: a day with raw and export data gets the resolved summary (API 222 steps win, export stress 30 fills)",
          _ss(_R2) == _expected(_raw2, {**_AGGS, "date": _R2}) and _ss(_R2)["day"]["steps"] == 222 and _ss(_R2)["stress"]["stress_avg"] == 30)
    check("5f regenerate_summaries: a day with export data only gets its summary, no raw file is created",
          _ss(_R3) == normalizer.summarize(normalizer.normalize(_copy5e.deepcopy({**_AGGS, "date": _R3}), source="bulk"))
          and not (cfg.RAW_DIR / f"garmin_raw_{_R3}.json").exists())
    check("5f regenerate_summaries: a broken raw file is one failure, the other days are still done; a name that is no day is ignored",
          not (cfg.SUMMARY_DIR / f"garmin_{_R4}.json").exists() and "Done. 3 regenerated, 1 errors." in _out
          and f"✗ {_R4}" in _out and "junk" not in _out)
    check("5f regenerate_summaries: the run says how many days come from raw files and from export data",
          "Regenerating summaries for 4 days (3 with raw files, 2 with export data)" in _out)
    check("5f regenerate_summaries: raw files are byte-identical, a summary of a day with neither is left alone, exit without error",
          {f.name: f.read_bytes() for f in cfg.RAW_DIR.iterdir()} == _raw_bytes
          and _orphan.read_text(encoding="utf-8") == '{"date": "2024-06-30", "old": true}' and _code is None)

with _iso5e("w5f_none") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _code, _out = _run_rs()
    check("5f regenerate_summaries: neither a raw folder nor export data -> an error message and exit code 1, nothing created",
          _code == 1 and "Raw folder not found" in _out and not cfg.SUMMARY_DIR.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  5g. garmin_writer — resolved summary, empty fields inside an API section (v1.7.6.3)
# ══════════════════════════════════════════════════════════════════════════════
section("5g. garmin_writer — resolved summary: an API section with empty fields (register finding F-11, fixed in v1.7.6.3)")

# For an old day Garmin answers with sections that exist but whose fields are null (heart_rates: min and
# max null; stress: no intraday array; user_summary: some fields null). Until v1.7.6.3 the resolution worked
# per top-level key (garmin_merge.merge_field), so such a section counted as "not empty" and the export's
# values for the same day never reached summary/ (step 0a pinned that as "Ist-Stand F-11"). Since step 0b the
# section is filled field by field, one level deep; the checks marked "F-11" were turned around, the others
# held before and after. The shapes follow a real day of the archive (2018-12-19); the numbers are made up.
_D7 = "2024-07-10"
_API7 = {"date": _D7,
         "heart_rates": {"userProfilePK": 1, "calendarDate": _D7, "maxHeartRate": None, "minHeartRate": None,
                         "restingHeartRate": 64, "heartRateValues": None},
         "stress": {"calendarDate": _D7, "avgStressLevel": 28, "maxStressLevel": 99, "stressValuesArray": None},
         "user_summary": {"totalSteps": 3126, "floorsAscended": 0.69554, "activeKilocalories": None},
         "activities": {"ActivitiesForDay": {"statusCode": 200, "payload": []}}}
_AGGS7 = {"date": _D7,
          "user_summary": {"totalSteps": 3000, "floorsAscended": 1, "activeKilocalories": 223,
                           "restingHeartRate": 60, "minHeartRate": 59, "maxHeartRate": 154},
          "stress": {"averageStressLevel": 27, "maxStressLevel": 90},
          "activities": [{"activityName": "Walk", "duration": 809835.0, "distance": 107463.0}]}

with _iso5e("w5g_fields") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _agg_put(_D7, _AGGS7)
    _api7_before, _aggs7_before = _copy5e.deepcopy(_API7), _copy5e.deepcopy(_AGGS7)
    _agg7_bytes = (cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_D7}.json").read_bytes()
    with patch.object(_gb5d, "backup_raw"):
        _ok7 = writer.write_day(_API7, {"date": _D7, "marker": "passed"}, _D7)
    _rp7, _sp7 = _paths(_D7)
    _s7 = json.loads(_sp7.read_text(encoding="utf-8"))

    check("5g write_day with an aggregates file: True, the summary is the resolved one", _ok7 is True and "marker" not in _s7)
    # -- F-11: the export's values fill the empty fields of an API section --------------------------------
    check("5g F-11: heart rate min and max come from the export (59 and 154) although the API heart_rates section is not empty; resting stays the API's 64",
          _s7["heartrate"]["min_bpm"] == 59 and _s7["heartrate"]["max_bpm"] == 154 and _s7["heartrate"]["resting_bpm"] == 64)
    check("5g F-11: the stress average comes from the export (27) where the API stress section has no intraday array; the API maximum 99 stays",
          _s7["stress"]["stress_avg"] == 27 and _s7["stress"]["stress_max"] == 99)
    check("5g F-11: active calories come from the export (223) where the user_summary field is null in the API; the API steps stay",
          _s7["day"]["calories_active"] == 223 and _s7["day"]["steps"] == 3126)
    _res7 = writer._resolve(_API7, _AGGS7)
    check("5g F-11: _resolve fills the missing fields inside the API sections and keeps every API value that is there",
          _res7["heart_rates"] == {**_API7["heart_rates"], "minHeartRate": 59, "maxHeartRate": 154}
          and _res7["stress"] == {**_API7["stress"], "averageStressLevel": 27}
          and _res7["user_summary"] == {**_API7["user_summary"], "activeKilocalories": 223, "restingHeartRate": 60,
                                         "minHeartRate": 59, "maxHeartRate": 154})
    # -- holds before and after the fix ----------------------------------------------------------------
    check("5g the API values that are there win: resting 64, steps 3126, floors 0.69554, stress maximum 99",
          _s7["heartrate"]["resting_bpm"] == 64 and _s7["day"]["steps"] == 3126
          and _s7["day"]["floors_climbed"] == 0.69554 and _s7["stress"]["stress_max"] == 99)
    check("5g activities: the API holds an endpoint dict, the summary has no activities; the export's list is not used (left out on purpose)",
          _s7["activities"] == [])
    check("5g raw/ keeps exactly what was passed in, the passed dicts and the stored aggregates file are not changed",
          json.loads(_rp7.read_text(encoding="utf-8")) == _api7_before and _API7 == _api7_before
          and _AGGS7 == _aggs7_before and (cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_D7}.json").read_bytes() == _agg7_bytes)
    _first7 = _sp7.read_bytes()
    with patch.object(_gb5d, "backup_raw"):
        writer.write_day(_API7, {"date": _D7}, _D7)
    check("5g writing the same day again gives the same bytes (idempotent)", _sp7.read_bytes() == _first7)

    # -- the other write paths resolve the same way ---------------------------------------------------
    with patch.object(_gb5d, "backup_raw") as _br:
        check("5g write_summary_only and rebuild_summary give the same resolved summary as write_day (no backup)",
              writer.write_summary_only({"date": _D7}, _D7) is True and _sp7.read_bytes() == _first7
              and writer.rebuild_summary(_D7) is True and _sp7.read_bytes() == _first7 and not _br.called)

    # -- an API section that is complete: nothing from the export enters it ---------------------------
    _D8 = "2024-07-11"
    _api8 = {"date": _D8,
             "heart_rates": {"maxHeartRate": 130, "minHeartRate": 50, "restingHeartRate": 55},
             "stress": {"avgStressLevel": 30, "maxStressLevel": 80, "stressValuesArray": [[1, 20], [2, 40]]},
             "user_summary": {"totalSteps": 500, "floorsAscended": 2, "activeKilocalories": 100}}
    _agg_put(_D8, {**_AGGS7, "date": _D8})
    with patch.object(_gb5d, "backup_raw"):
        writer.write_day(_api8, {"date": _D8}, _D8)
    _s8 = json.loads(_paths(_D8)[1].read_text(encoding="utf-8"))
    check("5g a complete API day: min 50, max 130, stress average 30 (from the series), calories 100 - the export's 59, 154, 27 and 223 stay out",
          _s8["heartrate"]["min_bpm"] == 50 and _s8["heartrate"]["max_bpm"] == 130
          and _s8["stress"]["stress_avg"] == 30.0 and _s8["day"]["calories_active"] == 100)

    # -- the rule itself, one level deep -----------------------------------------------------------------
    _api9 = {"date": "2024-07-12",
             "user_summary": {"floorsAscended": 0, "flag": False, "items": [], "nested": {}, "keep": {"a": 1}, "gone": ""},
             "heart_rates": {}, "training_readiness": [{"score": 5}], "activities": {"env": None}, "max_metrics": {"v": 1}}
    _agg9 = {"date": "2024-07-12",
             "user_summary": {"floorsAscended": 5, "flag": True, "items": [1], "nested": {"b": 2}, "keep": {"a": 9, "c": 3},
                              "gone": "x", "restingHeartRate": 55},
             "training_readiness": {"level": "HIGH"}, "activities": {"env": 1}, "max_metrics": [{"v": 2}]}
    _api9_before, _agg9_before = _copy5e.deepcopy(_api9), _copy5e.deepcopy(_agg9)
    _res9 = writer._resolve(_api9, _agg9)
    check("5g rule: 0 and False are values and stay; None, empty string, empty list and empty dict are filled from the export",
          _res9["user_summary"]["floorsAscended"] == 0 and _res9["user_summary"]["flag"] is False
          and _res9["user_summary"]["items"] == [1] and _res9["user_summary"]["nested"] == {"b": 2} and _res9["user_summary"]["gone"] == "x")
    check("5g rule: one level deep - a field the API holds as a non-empty dict stays as it is, the export adds nothing inside it",
          _res9["user_summary"]["keep"] == {"a": 1})
    check("5g rule: fields only the export has are added (resting heart rate)", _res9["user_summary"]["restingHeartRate"] == 55)
    check("5g rule: an empty API section is taken from the export as a whole (heart_rates through the import remap)",
          _res9["heart_rates"] == {"restingHeartRate": 55})
    check("5g rule: sections of different types are not mixed - the non-empty API list stays, a non-empty API dict against an export list stays too (no error)",
          _res9["training_readiness"] == [{"score": 5}] and _res9["max_metrics"] == {"v": 1})
    check("5g rule: activities keep the whole-key rule - even two dicts are not filled field by field",
          _res9["activities"] == {"env": None})
    check("5g rule: neither argument is changed", _api9 == _api9_before and _agg9 == _agg9_before)

# ══════════════════════════════════════════════════════════════════════════════
#  5h. garmin_writer — resolve_preview (v1.7.6.3, read-only preview of the resolution)
# ══════════════════════════════════════════════════════════════════════════════
section("5h. garmin_writer — resolve_preview: what the resolution would give, nothing written")

with _iso5e("w5h_preview") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _DP = "2024-08-01"
    _apiP = {**_copy5e.deepcopy(_API7), "date": _DP}
    _aggP = {**_copy5e.deepcopy(_AGGS7), "date": _DP}
    _apiP_before = _copy5e.deepcopy(_apiP)

    _pn = writer.resolve_preview(_apiP, _DP)
    check("5h no aggregates file: state 'none', no export values, the summary is summarize() of the API data alone",
          _pn["state"] == "none" and _pn["export"] is None and _pn["summary"] == normalizer.summarize(_apiP))
    _agg_put(_DP, _aggP)
    _pk = writer.resolve_preview(_apiP, _DP)
    check("5h usable aggregates: state 'ok', export values normalised like an import day, resolved summary (min/max from the export)",
          _pk["state"] == "ok" and _pk["export"] == normalizer.normalize(_copy5e.deepcopy(_aggP), source="bulk")
          and _pk["summary"]["heartrate"]["min_bpm"] == 59 and _pk["summary"]["heartrate"]["max_bpm"] == 154)
    check("5h nothing is written by the preview and the passed dict is not changed",
          not _paths(_DP)[0].exists() and not _paths(_DP)[1].exists() and _apiP == _apiP_before)
    with patch.object(_gb5d, "backup_raw"):
        writer.write_day(_apiP, {"date": _DP}, _DP)
    check("5h the previewed summary is exactly what write_day() writes",
          json.loads(_paths(_DP)[1].read_text(encoding="utf-8")) == _pk["summary"])
    check("5h no API data at all (None or {}): the export alone, no error",
          writer.resolve_preview(None, _DP)["state"] == "ok" and writer.resolve_preview({}, _DP)["summary"] is not None
          and writer.resolve_preview(None, "2024-08-02")["summary"] == normalizer.summarize({}))

    _agg_file_p = cfg.BULK_AGG_DIR / f"garmin_bulk_agg_{_DP}.json"
    _real_rt_p = Path.read_text

    def _locked_p(self, *a, **k):
        if self == _agg_file_p:
            raise PermissionError("locked by another process")
        return _real_rt_p(self, *a, **k)

    with patch.object(Path, "read_text", _locked_p):
        _pu = writer.resolve_preview(_apiP, _DP)
    check("5h unreadable aggregates: state 'unreadable', no export, no summary (write_day() would write nothing)",
          _pu == {"state": "unreadable", "export": None, "summary": None})
    _agg_file_p.write_text("{ not json", encoding="utf-8")
    check("5h damaged aggregates: state 'none' (as write_day() treats them)", writer.resolve_preview(_apiP, _DP)["state"] == "none")

summary()
