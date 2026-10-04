#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_api.py — garmin_api

Run from the project folder:
    python tests/test_api.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import sys
import threading
from unittest.mock import MagicMock, patch

from gla_testenv import _TMPDIR, _cfg_values  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  4l. garmin_api — login paths, api_call, fetch_raw stop handling, get_devices
#      (v1.7.4.0.2). No network, no Windows Credential Manager: garminconnect
#      is replaced by a fake module and garmin_security's key/token functions
#      are mocked.
# ══════════════════════════════════════════════════════════════════════════════
section("4l. garmin_api — login paths, api_call, fetch_raw, get_devices")
import garmin_api as _api7
import garmin_security as _gs7
import types as _types7


class _FakeTooMany(Exception):
    pass


def _make_garmin(login_error=None, summary_error=None):
    created = []

    class _Garmin:
        def __init__(self, *a, **kw):
            self.args, self.kwargs = a, kw
            self._tokenstore_path = "set"
            created.append(self)

        def login(self, token_dir=None):
            if login_error is not None:
                raise login_error

        def get_user_summary(self, d):
            if summary_error is not None:
                raise summary_error

    return _Garmin, created


def _login(garmin_cls, *, token_file=False, enc_key="key", gen_key=True, store_key=True,
           load_token=False, unresolved_mfa=False, save_token=True, during=None, **callbacks):
    """Runs api.login() against the fake garminconnect. Returns (result, error, mocks).
    during: optional callable run while the mocks are still active (e.g. to call the
    MFA prompt); its outcome is stored in mocks["_during"] as ("ok", value) / ("error", exc)."""
    mocks = {
        "get_enc_key": MagicMock(return_value=enc_key),
        "generate_enc_key": MagicMock(return_value=gen_key),
        "store_enc_key": MagicMock(return_value=store_key),
        "load_token": MagicMock(return_value=load_token),
        "clear_token": MagicMock(),
        "_clear_token_dir": MagicMock(),
        "log_token_event": MagicMock(),
        "has_unresolved_mfa_block": MagicMock(return_value=unresolved_mfa),
        "save_token": MagicMock(return_value=save_token),
    }
    fake = _types7.ModuleType("garminconnect")
    fake.Garmin = garmin_cls
    fake.GarminConnectTooManyRequestsError = _FakeTooMany
    _tf = _TMPDIR / "api4l" / "token.enc"
    _tf.parent.mkdir(parents=True, exist_ok=True)
    _tf.unlink(missing_ok=True)
    if token_file:
        _tf.write_text("x", encoding="utf-8")
    result, error = None, None
    mocks["_during"] = None
    patched = {k: v for k, v in mocks.items() if k != "_during"}
    with patch.dict(sys.modules, {"garminconnect": fake}), \
         patch.multiple(_gs7, **patched), \
         _cfg_values(GARMIN_TOKEN_FILE=_tf, GARMIN_TOKEN_DIR=_tf.parent / "tokendir",
                     GARMIN_EMAIL="user@example.com", GARMIN_PASSWORD="pw"):
        try:
            result = _api7.login(**callbacks)
        except _api7.GarminLoginError as e:
            error = e
        if during is not None:
            try:
                mocks["_during"] = ("ok", during())
            except Exception as e:          # noqa: BLE001 - the test inspects it
                mocks["_during"] = ("error", e)
    return result, error, mocks


# -- garminconnect missing ---------------------------------------------------------------------
with patch.dict(sys.modules, {"garminconnect": None}):
    try:
        _api7.login()
        _err = None
    except _api7.GarminLoginError as e:
        _err = e
check("login: garminconnect not installed -> GarminLoginError says so",
      _err is not None and "not installed" in str(_err))

# -- saved token ----------------------------------------------------------------------------------
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, load_token=True)
check("login: a valid saved token logs in without SSO",
      _res is not None and _err is None and len(_created) == 1 and _created[0].args == ())
check("login: after a token login the plain token folder is removed again and the event is logged",
      _m["_clear_token_dir"].called and _m["log_token_event"].call_args.args == ("valid", "token_reused"))
check("login: the client does not keep a token store path", _res._tokenstore_path is None)

_G, _created = _make_garmin()
_res, _err, _m = _login(_G, token_file=True, enc_key=None, on_sso_required=lambda: False)
check("login: token file but no encryption key -> a new key is generated and the old token cleared",
      _m["generate_enc_key"].called and _m["clear_token"].called
      and ("invalidated", "enc_key_missing_wcm") in [c.args[:2] for c in _m["log_token_event"].call_args_list])

_G, _created = _make_garmin(summary_error=_FakeTooMany("slow down"))
_res, _err, _m = _login(_G, load_token=True)
check("login: rate limit while probing the token -> error, no fallback to SSO, token folder cleaned",
      _err is not None and "Token probe failed" in str(_err) and len(_created) == 1
      and _m["_clear_token_dir"].called and not _m["clear_token"].called)
check("login: rate limit is logged as 'blocked'",
      _m["log_token_event"].call_args.args[:2] == ("blocked", "rate_limited"))

_G, _created = _make_garmin(summary_error=RuntimeError("HTTP 403 forbidden"))
_res, _err, _m = _login(_G, load_token=True)
check("login: a 403 while probing the token is treated like a rate limit (no SSO)",
      _err is not None and len(_created) == 1)

_G, _created = _make_garmin(summary_error=RuntimeError("token rejected"))
_res, _err, _m = _login(_G, load_token=True, on_token_expired=lambda: False)
check("login: a rejected token is cleared; the user declines a new login -> None",
      _res is None and _err is None and _m["clear_token"].called
      and ("invalidated", "rejected_by_garmin") in [c.args[:2] for c in _m["log_token_event"].call_args_list])

_G, _created = _make_garmin(summary_error=RuntimeError("token rejected"))
_res, _err, _m = _login(_G, load_token=True, on_token_expired=lambda: True)
check("login: a rejected token, the user accepts -> new SSO login succeeds and the token is saved",
      _res is not None and len(_created) == 2 and _m["save_token"].called
      and _created[1].args == ("user@example.com", "pw"))

# -- SSO ---------------------------------------------------------------------------------------------
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, on_sso_required=lambda: False)
check("login: SSO declined by the user -> None, nothing is created", _res is None and _created == [])

_G, _created = _make_garmin()
_res, _err, _m = _login(_G, unresolved_mfa=True)
check("login: an unresolved MFA block without an MFA callback stops the SSO login",
      _err is not None and "unresolved MFA" in str(_err) and _created == [])
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, unresolved_mfa=True, on_mfa_required=lambda: "123456")
check("login: the same block with an MFA callback does not stop the login",
      _res is not None and _err is None)

_G, _created = _make_garmin()
_res, _err, _m = _login(_G, save_token=False)
check("login: SSO succeeds even when the token cannot be saved",
      _res is not None and _err is None and _m["save_token"].called)

_G, _created = _make_garmin()
_res, _err, _m = _login(_G, enc_key=None, gen_key=False, on_key_required=lambda: "typed-key")
check("login: automatic key generation failed -> the key typed by the user is stored",
      _m["store_enc_key"].call_args.args == ("typed-key",) and _res is not None)
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, enc_key=None, gen_key=False, store_key=False,
                        on_key_required=lambda: "typed-key")
check("login: a typed key that cannot be stored is only a warning", _res is not None)
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, enc_key=None, gen_key=False)
check("login: key generation failed and no callback -> the login still goes on",
      _res is not None and not _m["store_enc_key"].called)

# MFA prompt wrapper
_G, _created = _make_garmin()
_seen = []
_res, _err, _m = _login(_G, on_mfa_required=lambda: _seen.append("asked") or "123456",
                        during=lambda: _created[0].kwargs["prompt_mfa"]())
check("login: with an MFA callback the client gets a prompt that returns the code",
      _m["_during"] == ("ok", "123456") and _seen == ["asked"])
check("login: an answered MFA challenge is logged as solved",
      _m["log_token_event"].call_args.args[:2] == ("mfa", "challenge_presented")
      and _m["log_token_event"].call_args.kwargs == {"solved": "yes"})
_G, _created = _make_garmin()
_res, _err, _m = _login(_G, on_mfa_required=lambda: None,
                        during=lambda: _created[0].kwargs["prompt_mfa"]())
check("login: a cancelled MFA challenge is logged as not solved",
      _m["log_token_event"].call_args.kwargs == {"solved": "no"})


def _mfa_callback_crashes():
    raise RuntimeError("dialog crashed")


_G, _created = _make_garmin()
_res, _err, _m = _login(_G, on_mfa_required=_mfa_callback_crashes,
                        during=lambda: _created[0].kwargs["prompt_mfa"]())
check("login: a crashing MFA callback is still logged as a presented challenge, error passes on",
      _m["_during"][0] == "error" and isinstance(_m["_during"][1], RuntimeError)
      and _m["log_token_event"].call_args.kwargs == {"solved": "no"})
_G, _created = _make_garmin()
_res, _err, _m = _login(_G)
check("login: without an MFA callback the client gets no MFA prompt",
      _created[0].kwargs["prompt_mfa"] is None)

# SSO failures
_G, _created = _make_garmin(login_error=RuntimeError("bad credentials"))
_res, _err, _m = _login(_G)
check("login: an SSO failure becomes GarminLoginError with the reason",
      _err is not None and "Login failed: bad credentials" in str(_err))
_G, _created = _make_garmin(login_error=RuntimeError("MFA Required but no prompt_mfa mechanism supplied"))
_res, _err, _m = _login(_G)
check("login: MFA required but no callback -> specific error and a 'blocked' event",
      _err is not None and "MFA required" in str(_err)
      and ("blocked", "mfa_required_no_callback") in [c.args[:2] for c in _m["log_token_event"].call_args_list])
_G, _created = _make_garmin(login_error=_api7.GarminLoginError("already a login error"))
_res, _err, _m = _login(_G)
check("login: a GarminLoginError from inside is passed on unchanged",
      _err is not None and str(_err) == "already a login error")

# -- api_call ----------------------------------------------------------------------------------------------
class _Client:
    def __init__(self, **methods):
        for k, v in methods.items():
            setattr(self, k, v)


_ev7 = threading.Event()
with patch("garmin_api.time.sleep"):
    _d, _ok = _api7.api_call(_Client(get_x=lambda d: {"v": d}), "get_x", "2024-05-01", label="x")
check("api_call: success returns the data and True", (_d, _ok) == ({"v": "2024-05-01"}, True))

# a stop request before the call
_api7.set_stop_event(_ev7)
_ev7.set()
_calls = []
with patch("garmin_api.time.sleep"):
    _d, _ok = _api7.api_call(_Client(get_x=lambda d: _calls.append(d)), "get_x", "2024-05-01")
check("api_call: a set stop event -> no call at all, (None, False)",
      (_d, _ok) == (None, False) and _calls == [])
_api7.set_stop_event(None)


def _raises(exc):
    def _f(*a):
        raise exc
    return _f


_ev7 = threading.Event()
_api7.set_stop_event(_ev7)
_fake_gc7 = _types7.ModuleType("garminconnect")
_fake_gc7.GarminConnectTooManyRequestsError = _FakeTooMany
with patch("garmin_api.time.sleep"), patch.dict(sys.modules, {"garminconnect": _fake_gc7}):
    _d, _ok = _api7.api_call(_Client(get_x=_raises(RuntimeError("HTTP 429 Too Many Requests"))), "get_x")
check("api_call: a 429 error sets the stop event and returns (None, False)",
      (_d, _ok) == (None, False) and _ev7.is_set())
_ev7.clear()
with patch("garmin_api.time.sleep"), patch.dict(sys.modules, {"garminconnect": _fake_gc7}):
    _d, _ok = _api7.api_call(_Client(get_x=_raises(_FakeTooMany("rate"))), "get_x")
check("api_call: the library's too-many-requests error also sets the stop event",
      (_d, _ok) == (None, False) and _ev7.is_set())
_api7.set_stop_event(None)
with patch("garmin_api.time.sleep"), patch.dict(sys.modules, {"garminconnect": _fake_gc7}):
    _d, _ok = _api7.api_call(_Client(get_x=_raises(RuntimeError("HTTP 500"))), "get_x")
check("api_call: another error -> (None, False), no stop event", (_d, _ok) == (None, False))

# -- fetch_raw: stop handling -----------------------------------------------------------------------------------
_ev7 = threading.Event()
_ev7.set()
_api7.set_stop_event(_ev7)
_sleeps = []
with patch("garmin_api.time.sleep", side_effect=lambda s: _sleeps.append(s)):
    _raw7, _failed7 = _api7.fetch_raw(MagicMock(), "2024-05-01")
_api7.set_stop_event(None)
check("fetch_raw: a stop event that is already set -> only the date, no failures, no pause",
      _raw7 == {"date": "2024-05-01"} and _failed7 == [] and _sleeps == [])

_ev7 = threading.Event()
_api7.set_stop_event(_ev7)
_cl = MagicMock()
_cl.get_sleep_data.side_effect = RuntimeError("HTTP 429 Too Many Requests")
with patch("garmin_api.time.sleep"):
    _raw7, _failed7 = _api7.fetch_raw(_cl, "2024-05-01")
_api7.set_stop_event(None)
check("fetch_raw: a 429 on one endpoint stops the remaining endpoints",
      _ev7.is_set() and not _cl.get_stress_data.called)

# -- get_devices ---------------------------------------------------------------------------------------------------
_cl = MagicMock()
_cl.get_devices.return_value = [
    {"productDisplayName": "Fenix 7", "deviceId": 1,
     "registeredDate": "2022-05-01T10:00:00", "lastUsed": "2024-05-01"},
    {"deviceTypeName": "Edge", "unitId": 2, "firstSyncTime": 1600000000000},
    "garbage",
    {"deviceId": 3},
]
_dev = _api7.get_devices(_cl)
check("get_devices: non-object entries are skipped", len(_dev) == 3)
check("get_devices: the name falls back to the type name, then to 'Unknown'",
      sorted(d["name"] for d in _dev) == ["Edge", "Fenix 7", "Unknown"])
check("get_devices: the id falls back to the unit id",
      {d["name"]: d["id"] for d in _dev} == {"Fenix 7": 1, "Edge": 2, "Unknown": 3})
check("get_devices: first_used comes from the first usable date field, last_used defaults to 'unknown'",
      {d["name"]: (d["first_used"], d["last_used"]) for d in _dev}
      == {"Fenix 7": ("2022-05-01", "2024-05-01"),
          "Edge": ("2020-09-13", "unknown"),
          "Unknown": (None, "unknown")})
check("get_devices: sorted by first use, devices without a date last",
      [d["name"] for d in _dev] == ["Edge", "Fenix 7", "Unknown"])
_cl = MagicMock()
_cl.get_devices.return_value = {"not": "a list"}
check("get_devices: an answer that is not a list -> []", _api7.get_devices(_cl) == [])
_cl = MagicMock()
_cl.get_devices.side_effect = RuntimeError("devices endpoint down")
check("get_devices: an error -> [], no crash", _api7.get_devices(_cl) == [])

# ══════════════════════════════════════════════════════════════════════════════
#  J. garmin_api (pure helpers + fetch_raw() extra_endpoints — no live Garmin
#     Connect credentials required, api_call() is mocked throughout; the
#     rest of garmin_api.py — login(), the 15-baseline api_call() path
#     itself — remains untested, see MAINTENANCE_GARMIN.md)
# ══════════════════════════════════════════════════════════════════════════════
section("J. garmin_api (pure helpers)")
import garmin_api as api

# _is_mfa_no_callback_error
check("_is_mfa_no_callback_error: exact library message → True",
      api._is_mfa_no_callback_error(
          Exception("MFA Required but no prompt_mfa mechanism supplied")) == True)
check("_is_mfa_no_callback_error: unrelated message → False",
      api._is_mfa_no_callback_error(Exception("Some other login failure")) == False)
check("_is_mfa_no_callback_error: empty message → False",
      api._is_mfa_no_callback_error(Exception("")) == False)

# _cause_fields
_no_cause = Exception("plain error")
check("_cause_fields: no __cause__ → empty dict",
      api._cause_fields(_no_cause) == {})

try:
    try:
        raise ValueError("original network timeout")
    except ValueError as _root:
        raise RuntimeError("wrapper message") from _root
except RuntimeError as _chained:
    _fields = api._cause_fields(_chained)
    check("_cause_fields: cause_type captured",
      _fields.get("cause_type") == "ValueError")
check("_cause_fields: cause_detail captured",
      _fields.get("cause_detail") == "original network timeout")

# ── fetch_raw() — extra_endpoints construction (v1.6.8) ──────────────────────
# api.api_call() mocked throughout — no live Garmin Connect credentials
# needed. time.sleep() also patched — fetch_raw()'s end-of-loop sleep
# (random.uniform(10, 20)) would otherwise stall the test suite for real.

with patch("garmin_api.api_call", return_value=(None, True)) as _mock_api_call_baseline, \
     patch("garmin_api.time.sleep"):
    api.fetch_raw(MagicMock(), "2024-01-01")
check("fetch_raw: extra_endpoints=None → 15 baseline calls only",
      _mock_api_call_baseline.call_count == 15)

with patch("garmin_api.api_call", return_value=(None, True)) as _mock_api_call_extra, \
     patch("garmin_api.time.sleep"):
    api.fetch_raw(MagicMock(), "2024-01-01",
                   extra_endpoints=[("get_body_composition", ("2024-01-01",), "body_weight_raw")])
check("fetch_raw: extra_endpoints appended → 16 calls total",
      _mock_api_call_extra.call_count == 16)
_fr_last_call = _mock_api_call_extra.call_args_list[-1]
check("fetch_raw: extra endpoint called with correct method",
      _fr_last_call.args[1] == "get_body_composition")
check("fetch_raw: extra endpoint called with correct date arg",
      _fr_last_call.args[2] == "2024-01-01")
check("fetch_raw: extra endpoint called with correct label",
      _fr_last_call.kwargs.get("label") == "body_weight_raw")

_fr_methods_seen = [c.args[1] for c in _mock_api_call_extra.call_args_list]
check("fetch_raw: baseline endpoint still called alongside extra",
      "get_sleep_data" in _fr_methods_seen)

# config-blind — zero-arg extra endpoint tuple accepted without special-casing
with patch("garmin_api.api_call", return_value=({"x": 1}, True)) as _mock_api_call_blind, \
     patch("garmin_api.time.sleep"):
    api.fetch_raw(MagicMock(), "2024-01-01",
                   extra_endpoints=[("get_pregnancy_summary", (), "get_pregnancy_summary")])
_fr_blind_last = _mock_api_call_blind.call_args_list[-1]
check("fetch_raw: config-blind — zero-arg extra endpoint, no date appended",
      len(_fr_blind_last.args) == 2 and _fr_blind_last.args[1] == "get_pregnancy_summary")

# extra endpoint data lands in raw dict under its own key
def _fr_data_side_effect(client_arg, method, *args, label=""):
    if method == "get_body_composition":
        return ({"weight": 70000}, True)
    return (None, True)

with patch("garmin_api.api_call", side_effect=_fr_data_side_effect), \
     patch("garmin_api.time.sleep"):
    _fr_raw, _fr_failed = api.fetch_raw(
        MagicMock(), "2024-01-01",
        extra_endpoints=[("get_body_composition", ("2024-01-01",), "get_body_composition")])
check("fetch_raw: extra endpoint data lands in raw dict under its key",
      _fr_raw.get("get_body_composition") == {"weight": 70000})
check("fetch_raw: return type — raw is dict", isinstance(_fr_raw, dict))
check("fetch_raw: return type — failed_endpoints is list", isinstance(_fr_failed, list))

# failed extra endpoint tracked in failed_endpoints, same as baseline
def _fr_fail_side_effect(client_arg, method, *args, label=""):
    if method == "get_hydration_data":
        return (None, False)
    return (None, True)

with patch("garmin_api.api_call", side_effect=_fr_fail_side_effect), \
     patch("garmin_api.time.sleep"):
    _fr_raw_fail, _fr_failed_list = api.fetch_raw(
        MagicMock(), "2024-01-01",
        extra_endpoints=[("get_hydration_data", ("2024-01-01",), "get_hydration_data")])
check("fetch_raw: failed extra endpoint tracked in failed_endpoints",
      "get_hydration_data" in _fr_failed_list)

summary()
