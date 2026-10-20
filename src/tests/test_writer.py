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
    """What the day must come out as, built by hand: the API keys that are not empty stay, the export fills the rest."""
    bulk = normalizer.normalize(_copy5e.deepcopy(aggs), source="bulk")
    out = dict(api)
    for k, v in bulk.items():
        if not out.get(k):
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

    # -- _resolve itself: pure, the API wins per top-level key, the export fills the rest ---
    _a0, _g0 = _copy5e.deepcopy(_API), _copy5e.deepcopy(_AGGS)
    _res = writer._resolve(_API, _AGGS)
    check("5e _resolve: neither the API dict nor the aggregates dict is changed (the import remap works on a copy)",
          _API == _a0 and _AGGS == _g0 and "heart_rates" not in _AGGS)
    check("5e _resolve: API keys stay as they are, missing keys come from the export, the heart_rates remap does not displace the API series",
          _res["user_summary"] == _API["user_summary"] and _res["heart_rates"] == _API["heart_rates"] and _res["sleep"] == _API["sleep"]
          and _res["stress"] == _AGGS["stress"] and _res["training_readiness"] == _AGGS["training_readiness"])
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

summary()
