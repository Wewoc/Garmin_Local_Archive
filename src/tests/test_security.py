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

summary()
