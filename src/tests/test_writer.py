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

summary()
