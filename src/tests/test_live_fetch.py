#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_live_fetch.py — garmin_live_fetch

Run from the project folder:
    python tests/test_live_fetch.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import shutil
from unittest.mock import MagicMock, patch

from gla_testenv import cfg  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  H. garmin_live_fetch
# ══════════════════════════════════════════════════════════════════════════════
section("H. garmin_live_fetch")
import garmin_live_fetch as live_fetch
importlib.reload(live_fetch)

# ── _ENDPOINTS structure — 10 entries (8 baseline + 2 capability-gated,
#    v1.7.1.14 Issue #9), 3-tuple shape (method, key, capability_gate) ───────
check("live_fetch: _ENDPOINTS has 10 entries",
      len(live_fetch._ENDPOINTS) == 10)
check("live_fetch: _ENDPOINTS includes get_hrv_data/hrv",
      ("get_hrv_data", "hrv", None) in live_fetch._ENDPOINTS)
check("live_fetch: _ENDPOINTS includes get_sleep_data/sleep",
      ("get_sleep_data", "sleep", None) in live_fetch._ENDPOINTS)
check("live_fetch: _ENDPOINTS includes get_blood_pressure (capability-gated)",
      ("get_blood_pressure", "get_blood_pressure", "get_blood_pressure") in live_fetch._ENDPOINTS)
check("live_fetch: _ENDPOINTS includes get_body_composition (capability-gated)",
      ("get_body_composition", "get_body_composition", "get_body_composition") in live_fetch._ENDPOINTS)

# ── fetch_live — success path, client provided (no login) ────────────────────
_lf_mock_client = MagicMock()
_lf_call_log = []

def _lf_api_call_success(client, method, *args, label=""):
    _lf_call_log.append((method, args))
    return ({"stub": method}, True)

with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result = live_fetch.fetch_live(client=_lf_mock_client)

check("fetch_live success: ok=True",              _lf_result["ok"] == True)
check("fetch_live success: no failed endpoints",  _lf_result["failed_endpoints"] == [])
check("fetch_live success: 8 api_call invocations", len(_lf_call_log) == 8)
check("fetch_live success: hrv endpoint called",
      any(m == "get_hrv_data" for m, _ in _lf_call_log))

check("fetch_live success: LIVE_FILE created", cfg.LIVE_FILE.exists())
_lf_written = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
check("fetch_live success: date key present",     "date" in _lf_written)
check("fetch_live success: synced_at key present", "synced_at" in _lf_written)
check("fetch_live success: hrv section written",
      _lf_written.get("hrv") == {"stub": "get_hrv_data"})
check("fetch_live success: sleep section written",
      _lf_written.get("sleep") == {"stub": "get_sleep_data"})

# ── fetch_live — partial failure — one endpoint fails, no crash ──────────────
def _lf_api_call_partial(client, method, *args, label=""):
    if method == "get_spo2_data":
        return (None, False)
    return ({"stub": method}, True)

with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_partial):
    _lf_result2 = live_fetch.fetch_live(client=_lf_mock_client)

check("fetch_live partial: ok=True despite one failure", _lf_result2["ok"] == True)
check("fetch_live partial: spo2 in failed_endpoints",
      "spo2" in _lf_result2["failed_endpoints"])
check("fetch_live partial: only one failed endpoint",
      len(_lf_result2["failed_endpoints"]) == 1)

_lf_written2 = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
check("fetch_live partial: spo2 key absent from live.json",
      "spo2" not in _lf_written2)
check("fetch_live partial: other sections still written",
      _lf_written2.get("heart_rates") == {"stub": "get_heart_rates"})

# ── fetch_live — no client, login fails (GarminLoginError) ───────────────────
with patch.object(live_fetch.garmin_api, "login",
                  side_effect=live_fetch.garmin_api.GarminLoginError("boom")):
    _lf_result3 = live_fetch.fetch_live(client=None)
check("fetch_live login failure: ok=False",              _lf_result3["ok"] == False)
check("fetch_live login failure: empty failed_endpoints", _lf_result3["failed_endpoints"] == [])

# ── fetch_live — no client, login cancelled (returns None) ───────────────────
with patch.object(live_fetch.garmin_api, "login", return_value=None):
    _lf_result4 = live_fetch.fetch_live(client=None)
check("fetch_live login cancelled: ok=False", _lf_result4["ok"] == False)

# ── fetch_live — no client, login succeeds, reuses api_call path ─────────────
with patch.object(live_fetch.garmin_api, "login", return_value=_lf_mock_client), \
     patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result5 = live_fetch.fetch_live(client=None)
check("fetch_live own-login: ok=True", _lf_result5["ok"] == True)

# ── fetch_live — progress callback receives messages ──────────────────────────
_lf_progress_msgs = []
with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result6 = live_fetch.fetch_live(
        client=_lf_mock_client,
        progress=lambda msg: _lf_progress_msgs.append(msg))

check("fetch_live progress: callback received messages",
      len(_lf_progress_msgs) > 0)
# v1.7.1.14, Issue #9: 3-tuple unpack. Capability config is deleted at
# this point in the test run (see line ~725), so both gated endpoints
# (get_blood_pressure, get_body_composition) are enabled_by_user=False
# and never attempted — the progress-message check is scoped to the
# baseline (ungated) endpoints only, matching what fetch_live() actually
# calls in this scenario.
check("fetch_live progress: mentions every attempted endpoint",
      all(any(key in m for m in _lf_progress_msgs)
          for _, key, gate in live_fetch._ENDPOINTS if gate is None))
check("fetch_live progress: mentions completion",
      any("complete" in m for m in _lf_progress_msgs))
check("fetch_live progress: fetch itself still succeeds",
      _lf_result6["ok"] == True)

# ── fetch_live — progress defaults to no-op (backward compatible) ────────────
with patch.object(live_fetch.garmin_api, "api_call", side_effect=_lf_api_call_success):
    _lf_result7 = live_fetch.fetch_live(client=_lf_mock_client)  # no progress kwarg
check("fetch_live: works without progress arg (backward compatible)",
      _lf_result7["ok"] == True)

# ── _write_live — creates LIVE_DIR if missing ─────────────────────────────────
shutil.rmtree(cfg.LIVE_DIR, ignore_errors=True)
check("live_fetch: LIVE_DIR removed for test", not cfg.LIVE_DIR.exists())
live_fetch._write_live({"date": "2026-07-07", "synced_at": "2026-07-07T12:00:00Z"})
check("_write_live: creates LIVE_DIR",  cfg.LIVE_DIR.exists())
check("_write_live: creates LIVE_FILE", cfg.LIVE_FILE.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  H2. garmin_live_fetch — exact file, probes, endpoint counting, messages
#      (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("H2. garmin_live_fetch — file format, probes, counters, messages")
import sys as _sys10
from pathlib import Path as _P10


class _Rec10:
    """Stands in for garmin_live_fetch.log and records (level, message)."""
    def __init__(self):
        self.calls = []
        for _lvl in ("debug", "info", "warning", "error"):
            setattr(self, _lvl, (lambda lv: lambda msg, *a, **k: self.calls.append((lv, msg)))(_lvl))

    def msgs(self, level):
        return [m for lv, m in self.calls if lv == level]


def _ok10(client, method, *args, label=""):
    return ({"stub": method}, True)


def _run10(api_call=_ok10, gates=None, client=None):
    """fetch_live with a stub api_call and a capability config in which `gates`
    maps endpoint name -> enabled_by_user. Returns (result, progress, states, log, live.json)."""
    progress, states, rec = [], [], _Rec10()
    conf = {"endpoints": {k: {"status": "found", "enabled_by_user": v} for k, v in (gates or {}).items()}}
    with patch.object(live_fetch.garmin_api, "api_call", side_effect=api_call), \
            patch.object(live_fetch.capability, "load_config", return_value=conf), \
            patch.object(live_fetch, "log", rec):
        res = live_fetch.fetch_live(client=client or MagicMock(), progress=progress.append,
                                    state_cb=lambda k, s: states.append((k, s)))
    return res, progress, states, rec, json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))


_OK = "✓"
_BAD = "✗"

# -- _write_live: exact bytes ---------------------------------------------------------------------------------------
live_fetch._write_live({"a": {"b": [1, 2]}})
check("H2 _write_live: 2-space indented JSON, byte for byte (line ends normalised)",
      cfg.LIVE_FILE.read_bytes().replace(b"\r\n", b"\n")
      == b'{\n  "a": {\n    "b": [\n      1,\n      2\n    ]\n  }\n}')

# -- probes -------------------------------------------------------------------------------------------------------------
_res, _prog, _states, _rec, _live = _run10()
check("H2 fetch_live: with a given client the states are token, login, api, data - all ok",
      _states == [("token", "ok"), ("login", "ok"), ("api", "ok"), ("data", "ok")])

_cl = MagicMock()
_cl.get_user_profile.side_effect = RuntimeError("profile down")
_res, _prog, _states, _rec, _live = _run10(client=_cl)
check("H2 fetch_live: a failing api probe -> state api=fail, warning, the fetch goes on",
      ("api", "fail") in _states and ("data", "ok") in _states and _res["ok"] is True
      and "  Live fetch: api probe failed — profile down" in _rec.msgs("warning")
      and _live.get("sleep") == {"stub": "get_sleep_data"})
_cl = MagicMock()
_cl.get_stats.side_effect = ValueError("stats down")
_res, _prog, _states, _rec, _live = _run10(client=_cl)
check("H2 fetch_live: a failing data probe -> state data=fail, warning, the fetch goes on",
      ("data", "fail") in _states and ("api", "ok") in _states and _res["ok"] is True
      and "  Live fetch: data probe failed — stats down" in _rec.msgs("warning")
      and _live.get("sleep") == {"stub": "get_sleep_data"})

# -- counters and messages ------------------------------------------------------------------------------------------
_BP, _BC = "get_blood_pressure", "get_body_composition"
_res, _prog, _states, _rec, _live = _run10(gates={_BP: False, _BC: False})
check("H2 fetch_live: both gated endpoints disabled -> 8/8, nothing failed, no 'Failed endpoints' line",
      _res == {"ok": True, "failed_endpoints": []}
      and _rec.msgs("info") == [f"  {_OK} Live fetch complete (8/8 endpoints)"]
      and _rec.msgs("warning") == []
      and _prog[-1] == f"{_OK} Live fetch complete (8/8 endpoints)"
      and _BP not in _live and _BC not in _live)

_res, _prog, _states, _rec, _live = _run10(gates={_BP: False, _BC: True})
check("H2 fetch_live: first gated endpoint disabled, second enabled -> the second is still fetched (9/9)",
      _rec.msgs("info") == [f"  {_OK} Live fetch complete (9/9 endpoints)"]
      and _live.get(_BC) == {"stub": _BC} and _BP not in _live)
_res, _prog, _states, _rec, _live = _run10(gates={_BP: True, _BC: False})
check("H2 fetch_live: first gated endpoint enabled, second disabled -> 9/9",
      _rec.msgs("info") == [f"  {_OK} Live fetch complete (9/9 endpoints)"]
      and _live.get(_BP) == {"stub": _BP} and _BC not in _live)
_res, _prog, _states, _rec, _live = _run10(gates={})
check("H2 fetch_live: gated endpoints missing from the capability config count as disabled (8/8)",
      _rec.msgs("info") == [f"  {_OK} Live fetch complete (8/8 endpoints)"])


def _two_fail10(client, method, *args, label=""):
    if method in ("get_spo2_data", _BC):
        return (None, False)
    return ({"stub": method}, True)


_res, _prog, _states, _rec, _live = _run10(_two_fail10, gates={_BP: True, _BC: True})
check("H2 fetch_live: 2 of 10 endpoints fail -> 8/10, both named in order, progress shows each failure",
      _res == {"ok": True, "failed_endpoints": ["spo2", _BC]}
      and _rec.msgs("info") == [f"  {_OK} Live fetch complete (8/10 endpoints)"]
      and _rec.msgs("warning") == [f"    Failed endpoints: spo2, {_BC}"]
      and f"{_BAD} spo2 failed" in _prog and f"{_BAD} {_BC} failed" in _prog
      and _prog[-1] == f"{_OK} Live fetch complete (8/10 endpoints)")
check("H2 fetch_live: the file holds every endpoint that returned data and nothing else",
      set(_live) == {"date", "synced_at", "sleep", "hrv", "heart_rates", "stress", "body_battery",
                     "steps", "respiration", _BP})


def _one_fail10(client, method, *args, label=""):
    return (None, False) if method == "get_spo2_data" else ({"stub": method}, True)


_res, _prog, _states, _rec, _live = _run10(_one_fail10)
check("H2 fetch_live: 1 of 8 endpoints fails -> 7/8 (a different failure count than the 2-of-10 case)",
      _rec.msgs("info") == [f"  {_OK} Live fetch complete (7/8 endpoints)"]
      and _rec.msgs("warning") == ["    Failed endpoints: spo2"]
      and _prog[-1] == f"{_OK} Live fetch complete (7/8 endpoints)")
def _none_ok10(client, method, *args, label=""):
    return (None, True)


_res, _prog, _states, _rec, _live = _run10(_none_ok10)
check("H2 fetch_live: an endpoint that answers with no data but without an error is not a failure",
      _res == {"ok": True, "failed_endpoints": []}
      and _rec.msgs("info") == [f"  {_OK} Live fetch complete (8/8 endpoints)"] and "sleep" not in _live)

# -- the module directory is put in front of sys.path on import (last test: it reloads the module) ------
_sp_saved = list(_sys10.path)
try:
    _sys10.path.insert(0, "gla_sentinel_path")
    importlib.reload(live_fetch)
    _front = _sys10.path[0]
    _sentinel_at = _sys10.path.index("gla_sentinel_path")
finally:
    _sys10.path[:] = _sp_saved
check("H2 garmin_live_fetch import: its own folder is inserted at position 0 of sys.path",
      _front == str(_P10(live_fetch.__file__).parent) and _sentinel_at == 1)

summary()
