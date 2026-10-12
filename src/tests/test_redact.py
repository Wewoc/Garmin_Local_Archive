#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_redact.py — garmin_redact (secret redaction for log output)

Run from the project folder:
    python tests/test_redact.py

New in v1.7.4.0.3 (mutation test round: the module had no test file).
Shared setup and helpers live in gla_testenv.py.
"""

import logging

from gla_testenv import cfg, _TMPDIR, _cfg_values  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  R. garmin_redact
# ══════════════════════════════════════════════════════════════════════════════
section("R. garmin_redact")
import garmin_redact as redact

_PW = "Geheim1"
_MAIL = "tester@example.org"
_PH_PW = "[GARMIN_PASSWORD]"
_PH_MAIL = "[GARMIN_EMAIL]"


def _rec(msg, args=None):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


with _cfg_values(GARMIN_EMAIL=_MAIL, GARMIN_PASSWORD=_PW):
    # -- redact(): what is replaced ------------------------------------------------------------------------------
    check("redact: the password becomes [GARMIN_PASSWORD]", redact.redact(f"pw={_PW}") == f"pw={_PH_PW}")
    check("redact: the e-mail address becomes [GARMIN_EMAIL]", redact.redact(f"user {_MAIL}") == f"user {_PH_MAIL}")
    check("redact: every occurrence is replaced, both kinds in one text",
          redact.redact(f"{_MAIL} / {_PW} / {_PW} / {_MAIL}") == f"{_PH_MAIL} / {_PH_PW} / {_PH_PW} / {_PH_MAIL}")
    check("redact: only the exact value is replaced (case and partial values stay)",
          redact.redact("geheim1 Geheim tester@example.com") == "geheim1 Geheim tester@example.com")
    check("redact: a text without secrets is returned unchanged", redact.redact("nothing to hide") == "nothing to hide")
    check("redact: an empty text stays empty", redact.redact("") == "")

    # -- non-text input is passed through ----------------------------------------------------------------------
    _obj = {"pw": _PW}
    check("redact: input that is not text is returned as it is (same object)",
          redact.redact(None) is None and redact.redact(5) == 5 and redact.redact(_obj) is _obj
          and redact.redact(_PW.encode()) == _PW.encode())

    # -- values are read fresh on every call -----------------------------------------------------------------------
    with _cfg_values(GARMIN_PASSWORD="Neu-9"):
        check("redact: a changed password is picked up on the next call (no caching)",
              redact.redact(f"{_PW} Neu-9") == f"{_PW} {_PH_PW}")

# -- empty / missing credentials replace nothing --------------------------------------------------------------------
with _cfg_values(GARMIN_EMAIL="", GARMIN_PASSWORD=""):
    check("redact: empty credentials replace nothing", redact.redact("abc def") == "abc def")
with _cfg_values(GARMIN_EMAIL=None, GARMIN_PASSWORD=None):
    check("redact: credentials that are None replace nothing", redact.redact("abc None") == "abc None")
with _cfg_values(GARMIN_EMAIL="", GARMIN_PASSWORD=_PW):
    check("redact: an empty e-mail does not stop the password from being replaced",
          redact.redact(f"x{_PW}x") == f"x{_PH_PW}x")
with _cfg_values(GARMIN_EMAIL=_MAIL, GARMIN_PASSWORD=""):
    check("redact: an empty password does not stop the e-mail from being replaced",
          redact.redact(f"x{_MAIL}x") == f"x{_PH_MAIL}x")
_saved = (cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD)
del cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD
try:
    check("redact: credentials missing in the config at all replace nothing", redact.redact("abc") == "abc")
finally:
    cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD = _saved

# Ist-Stand: the password is replaced first. A password that is part of the e-mail address leaves the rest
# of the address (here the domain) readable, the e-mail itself is then no longer found.
with _cfg_values(GARMIN_EMAIL="geheim@example.org", GARMIN_PASSWORD="geheim"):
    check("Ist-Stand redact: the password is replaced before the e-mail address",
          redact.redact("user geheim@example.org") == f"user {_PH_PW}@example.org")

# -- RedactFilter ------------------------------------------------------------------------------------------------------
with _cfg_values(GARMIN_EMAIL=_MAIL, GARMIN_PASSWORD=_PW):
    _f = redact.RedactFilter()
    _r = _rec(f"login {_MAIL} pw={_PW}")
    check("RedactFilter: the record text is redacted and the record is always let through",
          _f.filter(_r) is True and _r.msg == f"login {_PH_MAIL} pw={_PH_PW}")
    _r = _rec("nothing here")
    check("RedactFilter: a record without secrets passes unchanged and is let through",
          _f.filter(_r) is True and _r.msg == "nothing here")
    _r = _rec("%s %s %s", (_PW, 42, None))
    _f.filter(_r)
    check("RedactFilter: text arguments of a tuple are redacted, other arguments stay",
          _r.args == (_PH_PW, 42, None) and isinstance(_r.args, tuple))
    _r = _rec("%(a)s %(b)s", ({"a": _MAIL, "b": 7},))
    _f.filter(_r)
    check("RedactFilter: a single dict argument stays a dict; text values are redacted, others stay",
          isinstance(_r.args, dict) and _r.args == {"a": _PH_MAIL, "b": 7})
    _r = _rec("plain", ())
    _r2 = _rec("plain", None)
    _f.filter(_r)
    _f.filter(_r2)
    check("RedactFilter: empty or missing arguments are left alone", _r.args == () and _r2.args is None)
    _exc = ValueError(_PW)
    _r = _rec(_exc)
    check("RedactFilter: a message that is not text (an exception object) is not touched",
          _f.filter(_r) is True and _r.msg is _exc)

    # -- end to end: a real logger with a file handler -----------------------------------------------------------------
    _path = _TMPDIR / "redact_e2e.log"
    _path.unlink(missing_ok=True)
    _logger = logging.getLogger("gla_redact_e2e")
    _fh = logging.FileHandler(_path, encoding="utf-8")
    _fh.addFilter(redact.RedactFilter())
    _fh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _logger.addHandler(_fh)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    _disabled = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        _logger.warning(f"direct pw={_PW}")
        _logger.warning("format %s failed with %s", _MAIL, _PW)
        _logger.error("dict %(k)s", {"k": _PW})
        _logger.info("clean line")
    finally:
        logging.disable(_disabled)
        _logger.removeHandler(_fh)
        _fh.close()
    _text = _path.read_text(encoding="utf-8")
    check("redact end to end: neither the password nor the e-mail address reach the file",
          _PW not in _text and _MAIL not in _text)
    check("redact end to end: the lines carry the placeholders (text, % arguments, dict argument) and untouched lines stay",
          _text.splitlines() == [f"WARNING direct pw={_PH_PW}", f"WARNING format {_PH_MAIL} failed with {_PH_PW}",
                                 f"ERROR dict {_PH_PW}", "INFO clean line"])

summary()
