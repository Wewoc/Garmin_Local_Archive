#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_security.py — garmin_security (crypto layer)

Run from the project folder:
    python tests/test_security.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import json
import shutil
from unittest.mock import MagicMock, patch

from gla_testenv import cfg  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  7. garmin_security (crypto layer only)
# ══════════════════════════════════════════════════════════════════════════════
section("7. garmin_security (crypto layer)")
import garmin_security as security

# _derive_aes_key
_test_salt = b"\x00" * 16
k1 = security._derive_aes_key("test_key",   _test_salt)
k2 = security._derive_aes_key("test_key",   _test_salt)
k3 = security._derive_aes_key("other_key",  _test_salt)
check("_derive_aes_key: 32 bytes",       len(k1) == 32)
check("_derive_aes_key: deterministic",  k1 == k2)
check("_derive_aes_key: unique per key", k1 != k3)

# get_enc_key_status — WCM success and failure, get_enc_key() wrapper unaffected
mock_kr_ok = MagicMock()
mock_kr_ok.get_password.return_value = "some_enc_key"
with patch.dict("sys.modules", {"keyring": mock_kr_ok}):
    status_val, status_err = security.get_enc_key_status()
    check("get_enc_key_status: success value",     status_val == "some_enc_key")
    check("get_enc_key_status: success no error",  status_err is None)
    check("get_enc_key: wrapper returns value",     security.get_enc_key() == "some_enc_key")

mock_kr_fail = MagicMock()
mock_kr_fail.get_password.side_effect = Exception("WCM read error")
with patch.dict("sys.modules", {"keyring": mock_kr_fail}):
    status_val, status_err = security.get_enc_key_status()
    check("get_enc_key_status: WCM failure → None",       status_val is None)
    check("get_enc_key_status: WCM failure → error text", status_err == "WCM read error")
    check("get_enc_key: wrapper still None on failure",   security.get_enc_key() is None)

# save_token + load_token round-trip
cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
TEST_KEY = "local_test_enc_key"
TEST_PAYLOAD = b'{"oauth1_token": "test", "oauth2_token": "test"}'

# Prepare: write garmin_tokens.json as the library would
cfg.GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
(cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").write_bytes(TEST_PAYLOAD)

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    ok_save = security.save_token()
    check("save_token: returns True",        ok_save == True)
    check("save_token: enc file created",    cfg.GARMIN_TOKEN_FILE.exists())
    check("save_token: token dir cleaned",   not cfg.GARMIN_TOKEN_DIR.exists())

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    ok_load = security.load_token()
    check("load_token: returns True",        ok_load == True)
    check("load_token: json written",        (cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").exists())
    check("load_token: correct content",     (cfg.GARMIN_TOKEN_DIR / "garmin_tokens.json").read_bytes() == TEST_PAYLOAD)
    security._clear_token_dir()

with patch("garmin_security.get_enc_key", return_value="wrong_key"):
    check("load_token: wrong key → False",   security.load_token() == False)

with patch("garmin_security.get_enc_key", return_value=None):
    check("load_token: no key → False",      security.load_token() == False)

# clear_token
mock_kr = MagicMock()
with patch.dict("sys.modules", {"keyring": mock_kr}):
    ok_clear = security.clear_token()
check("clear_token: returns True",          ok_clear == True)
check("clear_token: enc file removed",      not cfg.GARMIN_TOKEN_FILE.exists())
check("clear_token: token dir removed",     not cfg.GARMIN_TOKEN_DIR.exists())

# clear_token — WCM delete fails → False (file/dir already clean from above)
mock_kr_clear_fail = MagicMock()
mock_kr_clear_fail.delete_password.side_effect = Exception("WCM delete error")
with patch.dict("sys.modules", {"keyring": mock_kr_clear_fail}):
    check("clear_token: WCM failure → False", security.clear_token() == False)

with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("load_token: no file → False",     security.load_token() == False)

# load_token — korrupte .enc Datei → False
cfg.GARMIN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
cfg.GARMIN_TOKEN_FILE.write_bytes(b"not_valid_encrypted_data")
with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("load_token: corrupt enc → False", security.load_token() == False)
cfg.GARMIN_TOKEN_FILE.unlink(missing_ok=True)

# save_token — garmin_tokens.json fehlt → False
cfg.GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
# token dir exists but garmin_tokens.json is absent
with patch("garmin_security.get_enc_key", return_value=TEST_KEY):
    check("save_token: no tokens.json → False", security.save_token() == False)
shutil.rmtree(cfg.GARMIN_TOKEN_DIR, ignore_errors=True)

# has_unresolved_mfa_block (v1.6.5.9)
_mfa_log_file = cfg.LOG_DIR / "garmin_token_log.json"
_mfa_log_file.unlink(missing_ok=True)

check("has_unresolved_mfa_block: no file → False",
      security.has_unresolved_mfa_block() == False)

_mfa_log_file.write_text(json.dumps({"events": [
    {"event": "created", "trigger": "sso_login"},
    {"event": "blocked", "trigger": "mfa_required_no_callback"},
]}))
check("has_unresolved_mfa_block: blocked last → True",
      security.has_unresolved_mfa_block() == True)

_mfa_log_file.write_text(json.dumps({"events": [
    {"event": "blocked", "trigger": "mfa_required_no_callback"},
    {"event": "created", "trigger": "sso_login"},
]}))
check("has_unresolved_mfa_block: cleared by later sso_login → False",
      security.has_unresolved_mfa_block() == False)

_mfa_log_file.write_text("not valid json{{{")
check("has_unresolved_mfa_block: corrupt file → False (fail-open)",
      security.has_unresolved_mfa_block() == False)

_mfa_log_file.unlink(missing_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  7b. garmin_security — key storage, key derivation, token folder clean-up,
#      save / load / clear token (v1.7.4.0.3, Group H2).
#      Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("7b. garmin_security — keys, derivation, token folder, save/load/clear")
import hashlib
from pathlib import Path

from gla_testenv import _TMPDIR, _cfg_values


class _Rec7:
    """Stands in for garmin_security.log and records (level, message)."""
    def __init__(self):
        self.calls = []
        for _lvl in ("debug", "info", "warning", "error"):
            setattr(self, _lvl, (lambda lv: lambda msg, *a, **k: self.calls.append((lv, msg)))(_lvl))

    def msgs(self, level):
        return [m for lv, m in self.calls if lv == level]


_OK7 = "✓"
_EM7 = "—"

# -- store_enc_key ----------------------------------------------------------------------------------------------------------
_kr = MagicMock()
_rec = _Rec7()
with patch.dict("sys.modules", {"keyring": _kr}), patch.object(security, "log", _rec):
    _ok = security.store_enc_key("k1")
check("7b store_enc_key: success -> True, the key goes to the credential manager under service and user, it is logged",
      _ok is True and _kr.set_password.call_args.args == ("GarminLocalArchive", "token_enc_key", "k1")
      and _rec.msgs("info") == [f"  {_OK7} Encryption key stored in Windows Credential Manager"])
_kr = MagicMock()
_kr.set_password.side_effect = Exception("wcm down")
_rec = _Rec7()
with patch.dict("sys.modules", {"keyring": _kr}), patch.object(security, "log", _rec):
    _ok = security.store_enc_key("k1")
check("7b store_enc_key: a failing credential manager -> False and an error line with the reason",
      _ok is False and _rec.msgs("error") == ["  Could not store enc_key in WCM: wcm down"])

# -- generate_enc_key ----------------------------------------------------------------------------------------------------
_keys = []
with patch.object(security, "store_enc_key", side_effect=lambda k: _keys.append(k) or True):
    _r1, _r2 = security.generate_enc_key(), security.generate_enc_key()
check("7b generate_enc_key: a 256-bit key as 64 hex characters, a new one on every call",
      _r1 is True and _r2 is True and len(_keys) == 2 and all(len(k) == 64 and int(k, 16) >= 0 for k in _keys)
      and _keys[0] != _keys[1])
with patch.object(security, "store_enc_key", return_value=False):
    check("7b generate_enc_key: the result of storing the key is passed on (False when it could not be stored)",
          security.generate_enc_key() is False)

# -- _derive_aes_key ---------------------------------------------------------------------------------------------------------
_salt = bytes(range(16))
_aes = security._derive_aes_key("some key", _salt)
check("7b _derive_aes_key: PBKDF2-HMAC-SHA256, 600 000 iterations, 32 bytes — equals an independent calculation",
      _aes == hashlib.pbkdf2_hmac("sha256", b"some key", _salt, 600_000, 32) and len(_aes) == 32)
check("7b _derive_aes_key: another salt or another key gives another AES key",
      _aes != security._derive_aes_key("some key", bytes(16)) and _aes != security._derive_aes_key("other key", _salt))

# -- _clear_token_dir: retries ----------------------------------------------------------------------------------------
_td = _TMPDIR / "sec7_tokdir"
_td.mkdir(parents=True, exist_ok=True)
with _cfg_values(GARMIN_TOKEN_DIR=_td):
    for _label, _effects, _exp_calls, _exp_sleeps in (
            ("first try works", [None], 1, 0),
            ("two failures, then it works", [OSError("boom"), OSError("boom"), None], 3, 2),
            ("every try fails", [OSError("boom")] * 5, 5, 4)):
        _rec = _Rec7()
        _sleeps = []
        with patch.object(security.shutil, "rmtree", side_effect=_effects) as _rm, \
                patch.object(security.time, "sleep", side_effect=_sleeps.append), patch.object(security, "log", _rec):
            _ret = security._clear_token_dir()
        _retry = [m for m in _rec.msgs("debug") if "retrying" in m]
        check(f"7b _clear_token_dir [{_label}]: tries {_exp_calls}x with {_exp_sleeps} pause(s) of exactly 1.0 s; "
              "retries are numbered from 1; returns nothing",
              _ret is None and _rm.call_count == _exp_calls and _sleeps == [1.0] * _exp_sleeps
              and _retry == [f"  Token dir removal attempt {i} failed {_EM7} retrying: boom" for i in range(1, _exp_sleeps + 1)])
        if _label == "first try works":
            check("7b _clear_token_dir: success is logged, no warning",
                  "  Token working dir removed" in _rec.msgs("debug") and _rec.msgs("warning") == [])
        if _label == "every try fails":
            check("7b _clear_token_dir: after the last failed try a warning (not a pause) and no crash",
                  _rec.msgs("warning") == ["  Could not remove token working dir: boom"])
shutil.rmtree(_td, ignore_errors=True)
with _cfg_values(GARMIN_TOKEN_DIR=_td):                                    # does not exist
    _rec = _Rec7()
    with patch.object(security.shutil, "rmtree") as _rm, patch.object(security, "log", _rec):
        security._clear_token_dir()
    check("7b _clear_token_dir: a token folder that does not exist -> nothing is removed, nothing is logged",
          not _rm.called and _rec.calls == [])

# -- save_token / load_token / clear_token --------------------------------------------------------------------------------
_b7 = _TMPDIR / "sec7_tokens"
shutil.rmtree(_b7, ignore_errors=True)
_PAY = b'{"oauth1_token": "a", "oauth2_token": "b"}'


def _tokdir7():
    d = _b7 / "work" / "tokdir"
    d.mkdir(parents=True, exist_ok=True)
    (d / "garmin_tokens.json").write_bytes(_PAY)
    return d


_logdir7 = _b7 / "p" / "q" / "log"
with _cfg_values(GARMIN_TOKEN_DIR=_b7 / "work" / "tokdir", LOG_DIR=_logdir7, GARMIN_TOKEN_FILE=_logdir7 / "garmin_token.enc"):
    _tokdir7()
    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value=None), patch.object(security, "log", _rec):
        _ok = security.save_token()
    check("7b save_token: no encryption key -> False and an error line", _ok is False
          and _rec.msgs("error") == [f"  Cannot save token {_EM7} encryption key not found in WCM"])

    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value="k"), patch.object(security, "log", _rec), \
            patch.object(security, "_derive_aes_key", side_effect=RuntimeError("kdf broke")):
        _ok = security.save_token()
    check("7b save_token: an error while encrypting -> False, an error line with the reason, the plaintext folder is still removed",
          _ok is False and _rec.msgs("error") == ["  Token save failed: kdf broke"]
          and not (_b7 / "work" / "tokdir").exists() and not cfg.GARMIN_TOKEN_FILE.exists())

    _tokdir7()
    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value="k"), patch.object(security, "log", _rec), \
            patch.object(security, "log_token_event") as _lte:
        _ok = security.save_token()
    _blob = cfg.GARMIN_TOKEN_FILE.read_bytes()
    check("7b save_token: a log folder with missing parent folders is created; the file is salt (16) + nonce (12) + "
          "ciphertext + tag (16); the 'created' event is recorded; the plaintext folder is gone",
          _ok is True and len(_blob) == 16 + 12 + len(_PAY) + 16 and _PAY not in _blob
          and _lte.call_args.args == ("created", "sso_login") and not (_b7 / "work" / "tokdir").exists()
          and f"  {_OK7} Token encrypted and saved" in _rec.msgs("info"))

    # load: a token folder whose parent does not exist yet, then again into an existing folder
    shutil.rmtree(_b7 / "work", ignore_errors=True)
    with patch.object(security, "get_enc_key", return_value="k"):
        _l1 = security.load_token()
        _created = (_b7 / "work" / "tokdir" / "garmin_tokens.json").read_bytes() if _l1 else None
        _l2 = security.load_token()                                   # the folder is still there
    check("7b load_token: a token folder with missing parent folders is created, the file holds the decrypted token; "
          "an already existing folder is no problem",
          _l1 is True and _created == _PAY and _l2 is True)
    shutil.rmtree(_b7 / "work", ignore_errors=True)

    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value="wrong"), patch.object(security, "log", _rec):
        _ok = security.load_token()
    check("7b load_token: wrong key -> False, an error line, the token folder is cleaned",
          _ok is False and len(_rec.msgs("error")) == 1 and _rec.msgs("error")[0].startswith("  Token decryption failed: ")
          and not (_b7 / "work" / "tokdir").exists())
    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value=None), patch.object(security, "log", _rec):
        _ok = security.load_token()
    check("7b load_token: no encryption key -> False and a warning",
          _ok is False and _rec.msgs("warning") == [f"  Encryption key not found in WCM {_EM7} re-entry required"])
    cfg.GARMIN_TOKEN_FILE.unlink()
    _rec = _Rec7()
    with patch.object(security, "get_enc_key", return_value="k"), patch.object(security, "log", _rec):
        _ok = security.load_token()
    check("7b load_token: no token file -> False and an info line", _ok is False and _rec.msgs("info") == ["  No saved token found"])

    # clear_token
    cfg.GARMIN_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg.GARMIN_TOKEN_FILE.write_bytes(b"x")
    _tokdir7()
    _kr = MagicMock()
    _rec = _Rec7()
    with patch.dict("sys.modules", {"keyring": _kr}), patch.object(security, "log", _rec), \
            patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        _ok = security.clear_token()
    check("7b clear_token: a token file that cannot be removed -> False and a warning; the folder is still cleaned and the key still deleted",
          _ok is False and _rec.msgs("warning") == ["  Could not remove token file: locked"]
          and not (_b7 / "work" / "tokdir").exists() and _kr.delete_password.call_count == 1
          and cfg.GARMIN_TOKEN_FILE.exists())
    _kr = MagicMock()
    _rec = _Rec7()
    with patch.dict("sys.modules", {"keyring": _kr}), patch.object(security, "log", _rec):
        _ok = security.clear_token()
    check("7b clear_token: everything removed -> True, the file and the key removal are logged",
          _ok is True and not cfg.GARMIN_TOKEN_FILE.exists() and _rec.msgs("warning") == []
          and "  Token file removed" in _rec.msgs("info") and "  Encryption key removed from WCM" in _rec.msgs("info")
          and _kr.delete_password.call_args.args == ("GarminLocalArchive", "token_enc_key"))
shutil.rmtree(_b7, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  7c. garmin_security — token event log: exact file text, appending, folders,
#      version / caller fallbacks, error paths, MFA block detection
#      (v1.7.4.0.3, Group H3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("7c. garmin_security — token event log and MFA block")
import os
import sys
import types
from datetime import datetime as _dt7, timezone as _tz7


class _FixedDT7:
    """Stands in for `datetime` inside garmin_security: now() is a fixed moment."""
    @staticmethod
    def now(tz=None):
        return _dt7(2026, 1, 2, 3, 4, 5, tzinfo=_tz7.utc)


_ver7 = types.ModuleType("version")
_ver7.APP_VERSION = "9.9.9"
_TS7 = "2026-01-02T03:04:05Z"
_logroot7 = _TMPDIR / "sec7c"
shutil.rmtree(_logroot7, ignore_errors=True)
_nested7 = _logroot7 / "a" / "b" / "log"
_file7 = _nested7 / "garmin_token_log.json"


def _text7():
    return _file7.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


_CREATED7 = ('{\n      "ts": "' + _TS7 + '",\n      "event": "created",\n      "trigger": "sso_login",\n'
             '      "app_version": "9.9.9",\n      "caller": "t_caller",\n      "k": "v"\n    }')
_VALID7 = ('{"ts":"' + _TS7 + '","event":"valid","trigger":"token_reused","app_version":"9.9.9","caller":"t_caller"}')
_BLOCKED7 = ('{\n      "ts": "' + _TS7 + '",\n      "event": "blocked",\n      "trigger": "rate_limited",\n'
             '      "app_version": "9.9.9",\n      "caller": "t_caller",\n      "detail": "429"\n    }')


def _file_of7(*blocks):
    return '{\n  "events": [\n    ' + ",\n    ".join(blocks) + '\n  ]\n}'


with _cfg_values(LOG_DIR=_nested7), patch.object(security, "datetime", _FixedDT7), \
        patch.dict(sys.modules, {"version": _ver7}), patch.dict(os.environ, {"GARMIN_SESSION_LOG_PREFIX": "t_caller"}):
    security.log_token_event("created", "sso_login", k="v")
    check("7c log_token_event: a log folder with missing parent folders is created; the file garmin_token_log.json holds exactly one "
          "multi-line event (time, event, trigger, version, caller, extra field), 2-space indented inside {\"events\": [...]}",
          _text7() == _file_of7(_CREATED7))
    security.log_token_event("valid", "token_reused")
    check("7c log_token_event: a second event is appended to the existing file (existing folder is fine); a 'valid' event is one compact line",
          _text7() == _file_of7(_CREATED7, _VALID7))
    security.log_token_event("blocked", "rate_limited", detail="429")
    check("7c log_token_event: a third event is appended again; every event except 'valid' is a multi-line block, separated by commas",
          _text7() == _file_of7(_CREATED7, _VALID7, _BLOCKED7))

    # an unreadable log: no crash, a warning, the file stays as it is
    _file7.write_text("{broken", encoding="utf-8")
    _rec = _Rec7()
    with patch.object(security, "log", _rec):
        _ret = security.log_token_event("created", "sso_login")
    check("7c log_token_event: a corrupt existing log -> no crash (returns nothing), a warning, the file is left as it was",
          _ret is None and _text7() == "{broken" and len(_rec.msgs("warning")) == 1
          and _rec.msgs("warning")[0].startswith("  Token event log write failed: "))

# only the exact event name 'valid' is written compactly (a name sorting after it is not)
_file7.unlink()
with _cfg_values(LOG_DIR=_nested7), patch.object(security, "datetime", _FixedDT7), \
        patch.dict(sys.modules, {"version": _ver7}), patch.dict(os.environ, {"GARMIN_SESSION_LOG_PREFIX": "t_caller"}):
    security.log_token_event("zzz_event", "t")
    check("7c log_token_event: an event name sorting after 'valid' is still a multi-line block, not a compact line",
          '      "event": "zzz_event",' in _text7() and '{"ts"' not in _text7())

# version.py not importable, caller from the environment or the fallback
_file7.unlink()
with _cfg_values(LOG_DIR=_nested7), patch.object(security, "datetime", _FixedDT7), patch.dict(sys.modules, {"version": None}):
    _env = {k: v for k, v in os.environ.items() if k != "GARMIN_SESSION_LOG_PREFIX"}
    _rec = _Rec7()
    with patch.dict(os.environ, _env, clear=True), patch.object(security, "log", _rec):
        security.log_token_event("created", "sso_login")
    _entry = json.loads(_text7())["events"][0]
    check("7c log_token_event: version.py not importable -> app_version 'unknown' and a debug line; no GARMIN_SESSION_LOG_PREFIX -> caller 'unknown'",
          _entry["app_version"] == "unknown" and _entry["caller"] == "unknown"
          and len(_rec.msgs("debug")) == 1
          and _rec.msgs("debug")[0].startswith("  Could not read app_version from version.py: "))
shutil.rmtree(_logroot7, ignore_errors=True)

# -- has_unresolved_mfa_block --------------------------------------------------------------------------------------------
_MFA = {"event": "blocked", "trigger": "mfa_required_no_callback"}
_SSO = {"event": "created", "trigger": "sso_login"}
_cases7 = [
    ("empty log", [], False),
    ("an MFA block", [_MFA], True),
    ("block, then a later SSO login clears it", [_MFA, _SSO], False),
    ("SSO login, then a later block", [_SSO, _MFA], True),
    ("block, then 'created' with another trigger (manual_reset) does not clear it",
     [_MFA, {"event": "created", "trigger": "manual_reset"}], True),
    ("block, then 'created' with a trigger sorting after sso_login does not clear it",
     [_MFA, {"event": "created", "trigger": "zzz_trigger"}], True),
    ("block, then another event with trigger sso_login (valid) does not clear it",
     [_MFA, {"event": "valid", "trigger": "sso_login"}], True),
    ("block, then 'blocked' with trigger sso_login does not clear it",
     [_MFA, {"event": "blocked", "trigger": "sso_login"}], True),
    ("block, then an event sorting before 'created' with trigger sso_login does not clear it",
     [_MFA, {"event": "azz", "trigger": "sso_login"}], True),
    ("'blocked' with another trigger (rate_limited) is no MFA block",
     [{"event": "blocked", "trigger": "rate_limited"}], False),
    ("'blocked' with a trigger sorting before the MFA trigger is no MFA block",
     [{"event": "blocked", "trigger": "aaa"}], False),
    ("another event with the MFA trigger (valid) is no MFA block",
     [{"event": "valid", "trigger": "mfa_required_no_callback"}], False),
    ("an event sorting before 'blocked' with the MFA trigger is no MFA block",
     [{"event": "azz", "trigger": "mfa_required_no_callback"}], False),
    ("only unrelated events", [{"event": "created", "trigger": "manual_reset"}, {"event": "valid", "trigger": "token_reused"}], False),
    ("newest first: events after the block that are neither SSO login nor block are ignored",
     [_SSO, {"event": "valid", "trigger": "x"}, _MFA, {"event": "valid", "trigger": "y"}], True),
    ("newest first: the SSO login is newer than the block, later events do not matter",
     [_MFA, {"event": "valid", "trigger": "x"}, _SSO, {"event": "valid", "trigger": "y"}], False),
    ("entries without keys are ignored", [{}, _MFA, {}], True),
]
_b7c = _TMPDIR / "sec7c_mfa"
shutil.rmtree(_b7c, ignore_errors=True)
_b7c.mkdir(parents=True)
_got7 = {}
with _cfg_values(LOG_DIR=_b7c):
    for _label, _events, _expect in _cases7:
        (_b7c / "garmin_token_log.json").write_text(json.dumps({"events": _events}), encoding="utf-8")
        _got7[_label] = (security.has_unresolved_mfa_block(), _expect)
    check("7c has_unresolved_mfa_block: the table of event sequences (what blocks, what clears, what is ignored, newest first)",
          all(g == e for g, e in _got7.values()))
    _bad7 = [lbl for lbl, (g, e) in _got7.items() if g != e]
    check("7c has_unresolved_mfa_block: every single row of the table gives its expected result", _bad7 == [])
    (_b7c / "garmin_token_log.json").write_text(json.dumps({"other": 1}), encoding="utf-8")
    check("7c has_unresolved_mfa_block: a log without an 'events' list -> False", security.has_unresolved_mfa_block() is False)
    (_b7c / "garmin_token_log.json").write_text("{broken", encoding="utf-8")
    _rec = _Rec7()
    with patch.object(security, "log", _rec):
        _res = security.has_unresolved_mfa_block()
    check("7c has_unresolved_mfa_block: a corrupt log -> False (fail-open) with a warning",
          _res is False and len(_rec.msgs("warning")) == 1
          and _rec.msgs("warning")[0].startswith("  Token event log read failed — treating as no block: "))
    (_b7c / "garmin_token_log.json").unlink()
    check("7c has_unresolved_mfa_block: no log file -> False", security.has_unresolved_mfa_block() is False)
shutil.rmtree(_b7c, ignore_errors=True)

summary()
