#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_force_refetch.py — Force-Refetch (v1.7.1.7)

Run from the project folder:
    python tests/test_force_refetch.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import logging
import os
import shutil
import threading
from unittest.mock import MagicMock, patch

from gla_testenv import cfg, mock_client  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_api as api
import garmin_collector as collector
import garmin_quality as quality
import garmin_source_quality as _sq
import garmin_source_writer as source_writer

# ══════════════════════════════════════════════════════════════════════════════
#  L. Force-Refetch (v1.7.1.7) — Gruppe A-D
# ══════════════════════════════════════════════════════════════════════════════
section("L. Force-Refetch (v1.7.1.7)")

# ── A. quality/_fieldhash.py — compare_source_fields() ───────────────────────
# compare_source_fields is exposed via the garmin_quality facade — `quality`
# is already imported above (section 4).

_ffh_a = {"heart_rates": {"restingHeartRate": 55}, "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 100}}}
_ffh_b = {"heart_rates": {"restingHeartRate": 55}, "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 100}}}
check("compare_source_fields: identical dicts → []",
      quality.compare_source_fields(_ffh_a, _ffh_b) == [])

_ffh_c = {"heart_rates": {"restingHeartRate": 55}}
_ffh_d = {"heart_rates": {"restingHeartRate": 62}}
check("compare_source_fields: one field differs → only that field",
      quality.compare_source_fields(_ffh_c, _ffh_d) == ["heart_rates"])

_ffh_missing_old = {}
_ffh_missing_new = {"steps": [{"steps": 100}]}
check("compare_source_fields: field absent on one side → counted as difference",
      "steps" in quality.compare_source_fields(_ffh_missing_old, _ffh_missing_new))

_ffh_order_a = {"stats": {"totalSteps": 100, "restingHeartRate": 50}}
_ffh_order_b = {"stats": {"restingHeartRate": 50, "totalSteps": 100}}
check("compare_source_fields: nested key order irrelevant (sort_keys=True)",
      quality.compare_source_fields(_ffh_order_a, _ffh_order_b) == [])

_ffh_unserializable_old = {"hrv": {"lastNight": 42}}
_ffh_unserializable_new = {"hrv": {"lastNight": {1, 2, 3}}}
try:
    _ffh_unserializable_result = quality.compare_source_fields(_ffh_unserializable_old, _ffh_unserializable_new)
    check("compare_source_fields: unserializable value → no crash (repr fallback)",
          "hrv" in _ffh_unserializable_result)
except Exception:
    check("compare_source_fields: unserializable value → no crash (repr fallback)", False)

try:
    _ffh_none_result = quality.compare_source_fields(None, None)
    check("compare_source_fields: None/None → no crash, treated as {}",
          _ffh_none_result == [])
except Exception:
    check("compare_source_fields: None/None → no crash, treated as {}", False)

# ── B. garmin_source_quality.compare_source() — force parameter ─────────────
_ffr_present = {"intraday_present": True}
_ffr_absent  = {"intraday_present": False}

check("compare_source: force=True + existing None → write",
      _sq.compare_source(None, _ffr_present, force=True) == "write")
check("compare_source: force=True + existing present, new absent → write",
      _sq.compare_source(_ffr_present, _ffr_absent, force=True) == "write")
check("compare_source: force=True + existing unreadable → write",
      _sq.compare_source({"unreadable": True}, _ffr_present, force=True) == "write")
check("compare_source: force=True + both absent → write",
      _sq.compare_source(_ffr_absent, _ffr_absent, force=True) == "write")
# Regression — force=False (default) leaves the existing truth table untouched
check("compare_source: force=False (default) unchanged — existing present, new absent → skip_warn",
      _sq.compare_source(_ffr_present, _ffr_absent) == "skip_warn")
check("compare_source: force=False (default) unchanged — existing present, new present → skip",
      _sq.compare_source(_ffr_present, _ffr_present) == "skip")

# ── C. garmin_source_writer.write_source(force=True) ─────────────────────────
_ffw_date = "2024-07-01"
_ffw_file = cfg.SOURCE_DIR / f"garmin_source_{_ffw_date}.json"

_ffw_raw_good = {"heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 58}}
source_writer.write_source(_ffw_raw_good, _ffw_date)
check("force write setup: initial high-res file exists", _ffw_file.exists())

_ffw_raw_degraded = {"heart_rates": {"restingHeartRate": 58}}
_ffw_ok_force = source_writer.write_source(_ffw_raw_degraded, _ffw_date, force=True)
_ffw_content_force = json.loads(_ffw_file.read_text(encoding="utf-8"))
check("write_source: force=True returns True",
      _ffw_ok_force == True)
check("write_source: force=True bypasses freeze-when-present guard",
      _ffw_content_force.get("heart_rates", {}).get("heartRateValues") is None)

# Regression — force=False (default) still respects the guard
source_writer.write_source(_ffw_raw_good, _ffw_date)  # restore high-res
_ffw_ok_noforce = source_writer.write_source(_ffw_raw_degraded, _ffw_date)
_ffw_content_noforce = json.loads(_ffw_file.read_text(encoding="utf-8"))
check("write_source: force=False (default) still guarded — intraday preserved",
      _ffw_content_noforce.get("heart_rates", {}).get("heartRateValues") is not None)

_ffw_file.unlink(missing_ok=True)

# ── D. garmin_force_refetch.py — snapshot_source() / restore_snapshot() ──────
import garmin_force_refetch as force_refetch
importlib.reload(force_refetch)

check("force_refetch: FORCE_REFETCH_BACKUP_DIR derived",
      cfg.FORCE_REFETCH_BACKUP_DIR == cfg.BACKUP_DIR / "force_refetch")

_ffr_snap_date = "2024-07-05"
_ffr_snap_src  = cfg.SOURCE_DIR / f"garmin_source_{_ffr_snap_date}.json"
cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
_ffr_snap_src.write_text(json.dumps({"date": _ffr_snap_date, "marker": "original"}), encoding="utf-8")

_ffr_snap_result = force_refetch.snapshot_source(_ffr_snap_date)
check("snapshot_source: file exists → snapshotted=True",
      _ffr_snap_result.get("snapshotted") == True)
check("snapshot_source: file exists → had_prior_data=True",
      _ffr_snap_result.get("had_prior_data") == True)

_ffr_snap_backup_file = cfg.FORCE_REFETCH_BACKUP_DIR / f"garmin_source_{_ffr_snap_date}.json"
check("snapshot_source: copy exists under FORCE_REFETCH_BACKUP_DIR",
      _ffr_snap_backup_file.exists())
check("snapshot_source: copy content matches original",
      json.loads(_ffr_snap_backup_file.read_text(encoding="utf-8")).get("marker") == "original")

# snapshot_source — no prior file → had_prior_data=False, no crash
_ffr_nofile_date = "2024-07-06"
_ffr_nofile_result = force_refetch.snapshot_source(_ffr_nofile_date)
check("snapshot_source: no prior file → snapshotted=False",
      _ffr_nofile_result.get("snapshotted") == False)
check("snapshot_source: no prior file → had_prior_data=False",
      _ffr_nofile_result.get("had_prior_data") == False)
check("snapshot_source: no prior file → no backup copy created",
      not (cfg.FORCE_REFETCH_BACKUP_DIR / f"garmin_source_{_ffr_nofile_date}.json").exists())

# restore_snapshot — snapshot exists → overwrites source/, returns True
_ffr_snap_src.write_text(json.dumps({"date": _ffr_snap_date, "marker": "overwritten"}), encoding="utf-8")
_ffr_restore_ok = force_refetch.restore_snapshot(_ffr_snap_date)
check("restore_snapshot: snapshot exists → returns True",
      _ffr_restore_ok == True)
check("restore_snapshot: source/ content restored to pre-overwrite state",
      json.loads(_ffr_snap_src.read_text(encoding="utf-8")).get("marker") == "original")

# Documented current behavior (not a fix — see NOTES_v17117.md): restore_snapshot()
# does not delete the snapshot file it restores from. A stale snapshot remains
# available for a repeat restore. This check exists so a future intentional change
# to that behavior is a visible, deliberate diff here — not a silent regression.
check("restore_snapshot: snapshot file itself is NOT deleted after restore (documented, not a bug)",
      _ffr_snap_backup_file.exists())

# restore_snapshot — no snapshot exists → False, no crash
_ffr_norestore_date = "2024-07-07"
_ffr_norestore_ok = force_refetch.restore_snapshot(_ffr_norestore_date)
check("restore_snapshot: no snapshot → returns False",
      _ffr_norestore_ok == False)

# cleanup
_ffr_snap_src.unlink(missing_ok=True)
shutil.rmtree(cfg.FORCE_REFETCH_BACKUP_DIR, ignore_errors=True)

# ── E. garmin_collector.run_force_refetch_preview() ──────────────────────────
_ffp_raw = {
    "date": "2024-08-01",
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 28800}},
    "heart_rates": {"restingHeartRate": 52, "heartRateValues": [[0, 52], [60, 55]]},
    "user_summary": {"totalSteps": 8500},
}

# no prior source/ file → had_prior_data=False, quality_before=failed, no field compare attempted
with patch("garmin_collector.api.fetch_raw", return_value=(_ffp_raw, [])):
    _ffp_res_new = collector.run_force_refetch_preview(mock_client, ["2024-08-01"])
check("run_force_refetch_preview: no prior file → had_prior_data=False",
      _ffp_res_new[0]["had_prior_data"] == False)
check("run_force_refetch_preview: no prior file → quality_before=failed",
      _ffp_res_new[0]["quality_before"] == "failed")
check("run_force_refetch_preview: no prior file → fields_changed empty",
      _ffp_res_new[0]["fields_changed"] == [])

# prior source/ file with a real field difference → fields_changed non-empty
_ffp_date2 = "2024-08-02"
(cfg.SOURCE_DIR / f"garmin_source_{_ffp_date2}.json").write_text(
    json.dumps({"date": _ffp_date2, "heart_rates": {"restingHeartRate": 40}}), encoding="utf-8")
with patch("garmin_collector.api.fetch_raw", return_value=(_ffp_raw, [])):
    _ffp_res_diff = collector.run_force_refetch_preview(mock_client, [_ffp_date2])
check("run_force_refetch_preview: prior file → fields_changed non-empty on real diff",
      len(_ffp_res_diff[0]["fields_changed"]) > 0)
check("run_force_refetch_preview: quality_before/after both set",
      _ffp_res_diff[0]["quality_before"] in ("high", "standard", "failed") and
      _ffp_res_diff[0]["quality_after"]  in ("high", "standard", "failed"))

# one day raises during fetch → recorded as error, remaining days still processed
def _ffp_fetch_side_effect(client, date_str, extra_endpoints=None):
    if date_str == "2024-08-10":
        raise RuntimeError("boom")
    return _ffp_raw, []
with patch("garmin_collector.api.fetch_raw", side_effect=_ffp_fetch_side_effect):
    _ffp_res_multi = collector.run_force_refetch_preview(
        mock_client, ["2024-08-09", "2024-08-10", "2024-08-11"])
check("run_force_refetch_preview: per-day exception → error entry recorded",
      _ffp_res_multi[1]["date"] == "2024-08-10" and _ffp_res_multi[1].get("error") is not None)
check("run_force_refetch_preview: per-day exception → other days still processed",
      len(_ffp_res_multi) == 3 and
      _ffp_res_multi[0].get("error") is None and
      _ffp_res_multi[2].get("error") is None)

# stop event set mid-list → abort, fewer results than requested days
_ffp_ev = threading.Event()
def _ffp_fetch_stop(client, date_str, extra_endpoints=None):
    if date_str == "2024-08-20":
        _ffp_ev.set()
    return _ffp_raw, []
collector.set_stop_event(_ffp_ev)
with patch("garmin_collector.api.fetch_raw", side_effect=_ffp_fetch_stop):
    _ffp_res_stop = collector.run_force_refetch_preview(
        mock_client, ["2024-08-20", "2024-08-21", "2024-08-22"])
check("run_force_refetch_preview: stop event → fewer results than requested days",
      len(_ffp_res_stop) < 3)
collector.set_stop_event(None)

# ── F. garmin_collector.commit_force_refetch() ───────────────────────────────

# confirmed date, quality_after="high" → committed, write_day + backups (force=True) called
_fcf_date_a = "2024-08-30"
_qd_fcf_a = {"first_day": None, "devices": [], "days": []}
_preview_fcf_a = [{
    "date": _fcf_date_a, "error": None, "had_prior_data": False,
    "quality_before": "failed", "quality_after": "high", "fields_changed": [],
    "_normalized": {"date": _fcf_date_a}, "_summary": {"date": _fcf_date_a},
    "_fields": {}, "_val_result": {"status": "ok", "issues": []},
}]
with patch("garmin_collector.writer.write_day") as _mock_write_a, \
     patch("garmin_backup.backup_raw") as _mock_bkp_raw_a, \
     patch("garmin_backup_source.backup_source") as _mock_bkp_src_a:
    _commit_a = collector.commit_force_refetch(_preview_fcf_a, {_fcf_date_a}, _qd_fcf_a)
check("commit_force_refetch: confirmed + high → action=committed",
      _commit_a[0]["action"] == "committed")
check("commit_force_refetch: confirmed + high → write_day called",
      _mock_write_a.called)
check("commit_force_refetch: confirmed + high → record_attempt wrote quality_log entry",
      any(e.get("date") == _fcf_date_a for e in _qd_fcf_a["days"]))
check("commit_force_refetch: confirmed + high → backup_raw called with force=True",
      _mock_bkp_raw_a.call_args.kwargs.get("force") == True)
check("commit_force_refetch: confirmed + high → backup_source called with force=True",
      _mock_bkp_src_a.call_args.kwargs.get("force") == True)

# confirmed date, quality_after="failed" → no write, but still recorded (no write guard blocks it)
_fcf_date_b = "2024-08-31"
_qd_fcf_b = {"first_day": None, "devices": [], "days": []}
_preview_fcf_b = [{
    "date": _fcf_date_b, "error": None, "had_prior_data": True,
    "quality_before": "standard", "quality_after": "failed", "fields_changed": [],
    "_normalized": None, "_summary": None,
    "_fields": {}, "_val_result": {"status": "critical", "issues": []},
}]
with patch("garmin_collector.writer.write_day") as _mock_write_b, \
     patch("garmin_backup.backup_raw") as _mock_bkp_raw_b, \
     patch("garmin_backup_source.backup_source"):
    _commit_b = collector.commit_force_refetch(_preview_fcf_b, {_fcf_date_b}, _qd_fcf_b)
check("commit_force_refetch: confirmed + failed → action still committed",
      _commit_b[0]["action"] == "committed")
check("commit_force_refetch: confirmed + failed → write_day NOT called",
      not _mock_write_b.called)
check("commit_force_refetch: confirmed + failed → backup_raw NOT called (nothing written)",
      not _mock_bkp_raw_b.called)
check("commit_force_refetch: confirmed + failed → record_attempt still wrote entry",
      any(e.get("date") == _fcf_date_b for e in _qd_fcf_b["days"]))

# rejected date (not in confirmed_dates), snapshot exists → reverted, source/ restored
_fcf_date_c = "2024-08-05"
_fcf_src_c  = cfg.SOURCE_DIR / f"garmin_source_{_fcf_date_c}.json"
_fcf_src_c.write_text(json.dumps({"date": _fcf_date_c, "marker": "pre-fetch"}), encoding="utf-8")
force_refetch.snapshot_source(_fcf_date_c)  # snapshot the pre-fetch state, as the real preview phase would
_fcf_src_c.write_text(json.dumps({"date": _fcf_date_c, "marker": "post-fetch"}), encoding="utf-8")

_qd_fcf_c = {"first_day": None, "devices": [], "days": []}
_preview_fcf_c = [{
    "date": _fcf_date_c, "error": None, "had_prior_data": True,
    "quality_before": "standard", "quality_after": "high", "fields_changed": ["heart_rates"],
    "_normalized": {}, "_summary": {}, "_fields": {}, "_val_result": {"status": "ok", "issues": []},
}]
_commit_c = collector.commit_force_refetch(_preview_fcf_c, set(), _qd_fcf_c)  # confirmed_dates empty → rejected
check("commit_force_refetch: rejected date → action=reverted",
      _commit_c[0]["action"] == "reverted")
check("commit_force_refetch: rejected date → source/ restored to pre-fetch content",
      json.loads(_fcf_src_c.read_text(encoding="utf-8")).get("marker") == "pre-fetch")
check("commit_force_refetch: rejected date → no quality_log entry written",
      not any(e.get("date") == _fcf_date_c for e in _qd_fcf_c["days"]))
_fcf_src_c.unlink(missing_ok=True)

# rejected date, no snapshot exists → error message set, no crash
_fcf_date_d = "2024-08-06"
_qd_fcf_d = {"first_day": None, "devices": [], "days": []}
_preview_fcf_d = [{
    "date": _fcf_date_d, "error": None, "had_prior_data": False,
    "quality_before": "failed", "quality_after": "high", "fields_changed": [],
    "_normalized": {}, "_summary": {}, "_fields": {}, "_val_result": {"status": "ok", "issues": []},
}]
_commit_d = collector.commit_force_refetch(_preview_fcf_d, set(), _qd_fcf_d)
check("commit_force_refetch: rejected + no snapshot → action still reverted",
      _commit_d[0]["action"] == "reverted")
check("commit_force_refetch: rejected + no snapshot → error='no snapshot to restore'",
      _commit_d[0]["error"] == "no snapshot to restore")

# preview entry already had an error → skipped_error, no crash on missing keys
_qd_fcf_e = {"first_day": None, "devices": [], "days": []}
_preview_fcf_e = [{"date": "2024-08-07", "error": "fetch failed: 429"}]
_commit_e = collector.commit_force_refetch(_preview_fcf_e, {"2024-08-07"}, _qd_fcf_e)
check("commit_force_refetch: preview had error → skipped_error, no crash on missing keys",
      _commit_e[0]["action"] == "skipped_error" and _commit_e[0]["error"] == "fetch failed: 429")

# exception during commit of one day → skipped_error for that day, other days still commit
_fcf_date_f1 = "2024-08-08"
_fcf_date_f2 = "2024-08-09"
_qd_fcf_f = {"first_day": None, "devices": [], "days": []}
_preview_fcf_f = [
    {"date": _fcf_date_f1, "error": None, "had_prior_data": False,
     "quality_before": "failed", "quality_after": "high", "fields_changed": [],
     "_normalized": {"date": _fcf_date_f1}, "_summary": {"date": _fcf_date_f1},
     "_fields": {}, "_val_result": {"status": "ok", "issues": []}},
    {"date": _fcf_date_f2, "error": None, "had_prior_data": False,
     "quality_before": "failed", "quality_after": "high", "fields_changed": [],
     "_normalized": {"date": _fcf_date_f2}, "_summary": {"date": _fcf_date_f2},
     "_fields": {}, "_val_result": {"status": "ok", "issues": []}},
]
def _ffp_write_day_raise_once(normalized, summary_data, date_str):
    if date_str == _fcf_date_f1:
        raise RuntimeError("disk full")
    return True
with patch("garmin_collector.writer.write_day", side_effect=_ffp_write_day_raise_once), \
     patch("garmin_backup.backup_raw"), patch("garmin_backup_source.backup_source"):
    _commit_f = collector.commit_force_refetch(
        _preview_fcf_f, {_fcf_date_f1, _fcf_date_f2}, _qd_fcf_f)
check("commit_force_refetch: exception on one day → skipped_error for that day",
      _commit_f[0]["action"] == "skipped_error")
check("commit_force_refetch: exception on one day → other day still committed",
      _commit_f[1]["action"] == "committed")

# _check_downgrade is never called for confirmed days (deliberate bypass, see NOTES_v17117.md)
with patch("garmin_collector._check_downgrade") as _mock_downgrade, \
     patch("garmin_collector.writer.write_day"), \
     patch("garmin_backup.backup_raw"), patch("garmin_backup_source.backup_source"):
    _qd_fcf_g = {"first_day": None, "devices": [], "days": []}
    _preview_fcf_g = [{
        "date": "2024-08-15", "error": None, "had_prior_data": False,
        "quality_before": "failed", "quality_after": "high", "fields_changed": [],
        "_normalized": {"date": "2024-08-15"}, "_summary": {"date": "2024-08-15"},
        "_fields": {}, "_val_result": {"status": "ok", "issues": []},
    }]
    collector.commit_force_refetch(_preview_fcf_g, {"2024-08-15"}, _qd_fcf_g)
    check("commit_force_refetch: _check_downgrade never called for confirmed days",
          not _mock_downgrade.called)

# cleanup
for _f in cfg.SOURCE_DIR.glob("garmin_source_2024-08-*.json"):
    _f.unlink(missing_ok=True)
shutil.rmtree(cfg.FORCE_REFETCH_BACKUP_DIR, ignore_errors=True)

# ── H. garmin_api.api_call() — label="" fallback (v1.7.1.7 debug log line) ───
_h_mock_client = MagicMock()
_h_mock_client.get_stats = MagicMock(return_value={"ok": True})
with patch("garmin_api.time.sleep"):
    _h_data, _h_ok = api.api_call(_h_mock_client, "get_stats", "2024-01-01", label="")
check("api_call: label='' → no crash, falls back to method name in log",
      _h_ok == True and _h_data == {"ok": True})

_h_mock_client2 = MagicMock()
_h_mock_client2.get_stats = MagicMock(side_effect=RuntimeError("network error"))
with patch("garmin_api.time.sleep"):
    _h_data2, _h_ok2 = api.api_call(_h_mock_client2, "get_stats", "2024-01-01", label="")
check("api_call: label='' + exception → no crash, ok=False",
      _h_ok2 == False and _h_data2 is None)

# ── G. garmin_collector._start_force_refetch_log() / _close_force_refetch_log() ──
# The root logger level is raised to DEBUG by the GUI worker (panel_outputs.py,
# anchor_delivery_17117-25), not by _start_force_refetch_log() itself — the
# file handler's own DEBUG level is a ceiling, not a floor: it still needs the
# root logger's effective level to be DEBUG or the records never reach it.
# Additionally, this test file disables all logging below CRITICAL at the top
# (logging.disable(logging.CRITICAL), line ~30) — that global cutoff overrides
# any per-logger/per-handler level and must be lifted too, or the DEBUG record
# never reaches the handler regardless of level settings. Reproduce both parts
# of that caller contract here, and restore both afterwards.
_ffl_orig_root_level = logging.getLogger().level
logging.disable(logging.NOTSET)
logging.getLogger().setLevel(logging.DEBUG)

_ffl_fh, _ffl_log_path = collector._start_force_refetch_log()
check("_start_force_refetch_log: file created under LOG_FORCE_REFETCH_DIR",
      _ffl_log_path.parent == cfg.LOG_FORCE_REFETCH_DIR and _ffl_log_path.exists())
check("_start_force_refetch_log: handler level is DEBUG",
      _ffl_fh.level == logging.DEBUG)
check("_start_force_refetch_log: handler attached to root logger",
      _ffl_fh in logging.getLogger().handlers)

logging.getLogger("garmin_collector").debug("test debug line for force refetch log")
collector._close_force_refetch_log(_ffl_fh)
check("_close_force_refetch_log: handler removed from root logger",
      _ffl_fh not in logging.getLogger().handlers)
check("_close_force_refetch_log: log file still readable after close",
      _ffl_log_path.exists() and "test debug line" in _ffl_log_path.read_text(encoding="utf-8"))

# Rolling limit — _start_force_refetch_log()'s filename has second-resolution
# (strftime %H%M%S), so calling it in a tight loop collides on the same
# filename within one second. Test the pruning logic in _close_force_refetch_log()
# directly instead: pre-create LOG_FORCE_REFETCH_MAX+3 distinct files with
# distinct mtimes, then trigger one real close to invoke the prune step.
import time as _ffl_time
for _f in cfg.LOG_FORCE_REFETCH_DIR.glob("force_refetch_*.log"):
    _f.unlink()

_ffl_created = []
for _i in range(cfg.LOG_FORCE_REFETCH_MAX + 3):
    _p = cfg.LOG_FORCE_REFETCH_DIR / f"force_refetch_fake_{_i:03d}.log"
    _p.write_text("x", encoding="utf-8")
    os.utime(_p, (_ffl_time.time() + _i, _ffl_time.time() + _i))
    _ffl_created.append(_p)

_ffl_fh_prune, _ = collector._start_force_refetch_log()
collector._close_force_refetch_log(_ffl_fh_prune)

_ffl_remaining = list(cfg.LOG_FORCE_REFETCH_DIR.glob("force_refetch_*.log"))
check("rolling limit: exactly LOG_FORCE_REFETCH_MAX files remain",
      len(_ffl_remaining) == cfg.LOG_FORCE_REFETCH_MAX)
check("rolling limit: oldest file(s) were pruned",
      not _ffl_created[0].exists())
check("rolling limit: newest fake file still present",
      _ffl_created[-1].exists())

# cleanup
logging.disable(logging.CRITICAL)
logging.getLogger().setLevel(_ffl_orig_root_level)
shutil.rmtree(cfg.LOG_FORCE_REFETCH_DIR, ignore_errors=True)

summary()
