#!/usr/bin/env python3
"""
test_app_logic.py — Garmin Local Archive — App Layer Logic Test

Run from the project folder:
    python tests/test_app_logic.py

No network, no GUI, no Garmin API calls.
Tests module-level functions in garmin_app.py and garmin_app_standalone.py.
Cleans up after itself — leaves no files behind.
"""

import json
import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
logging.disable(logging.CRITICAL)

# ── Suppress tkinter at import time ───────────────────────────────────────────
_tk_mock = MagicMock()
sys.modules.setdefault("tkinter", _tk_mock)
sys.modules.setdefault("tkinter.ttk", _tk_mock)
sys.modules.setdefault("tkinter.filedialog", _tk_mock)
sys.modules.setdefault("tkinter.scrolledtext", _tk_mock)
sys.modules.setdefault("tkinter.messagebox", _tk_mock)

import importlib
import garmin_app as app
import garmin_app_standalone as standalone

# ── Results tracking ───────────────────────────────────────────────────────────
_pass = 0
_fail = 0
_failures = []

def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✓  {name}")
    else:
        _fail += 1
        _failures.append(name)
        print(f"  ✗  {name}")

def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

# ── Temp dir ───────────────────────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_apptest_"))

# ══════════════════════════════════════════════════════════════════════════════
#  1. DEFAULT_SETTINGS — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("1. DEFAULT_SETTINGS — garmin_app")

REQUIRED_KEYS = [
    "email", "base_dir", "sync_mode", "sync_days",
    "sync_from", "sync_to", "date_from", "date_to",
    "age", "sex", "request_delay_min", "request_delay_max",
    "timer_min_interval", "timer_max_interval",
    "timer_min_days", "timer_max_days",
    "context_latitude", "context_longitude",
]

for key in REQUIRED_KEYS:
    check(f"DEFAULT_SETTINGS has '{key}'", key in app.DEFAULT_SETTINGS)

check("base_dir default is string",        isinstance(app.DEFAULT_SETTINGS["base_dir"], str))
check("sync_mode default = recent",        app.DEFAULT_SETTINGS["sync_mode"] == "recent")
check("sync_days default = 90",            app.DEFAULT_SETTINGS["sync_days"] == "90")
check("age default = 35",                  app.DEFAULT_SETTINGS["age"] == "35")
check("sex default = male",                app.DEFAULT_SETTINGS["sex"] == "male")

# ══════════════════════════════════════════════════════════════════════════════
#  2. DEFAULT_SETTINGS — garmin_app_standalone
# ══════════════════════════════════════════════════════════════════════════════
section("2. DEFAULT_SETTINGS — garmin_app_standalone")

REQUIRED_KEYS_SA = [
    "email", "base_dir", "sync_mode", "sync_days",
    "sync_from", "sync_to", "date_from", "date_to",
    "age", "sex", "request_delay_min", "request_delay_max",
    "timer_min_interval", "timer_max_interval",
    "timer_min_days", "timer_max_days",
]

for key in REQUIRED_KEYS_SA:
    check(f"DEFAULT_SETTINGS has '{key}'", key in standalone.DEFAULT_SETTINGS)

check("sync_mode default = recent",        standalone.DEFAULT_SETTINGS["sync_mode"] == "recent")
check("sync_days default = 90",            standalone.DEFAULT_SETTINGS["sync_days"] == "90")

# ══════════════════════════════════════════════════════════════════════════════
#  3. load_settings / save_settings — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("3. load_settings / save_settings — garmin_app")

_settings_file = _TMPDIR / ".garmin_archive_settings_test.json"

with patch.object(app, "SETTINGS_FILE", _settings_file):
    s = dict(app.DEFAULT_SETTINGS)
    s["email"] = "test@example.com"
    app.save_settings(s)
    loaded = app.load_settings()
    check("roundtrip: email preserved",        loaded["email"] == "test@example.com")
    check("roundtrip: sync_mode preserved",    loaded["sync_mode"] == "recent")
    check("roundtrip: password stripped",      "password" not in loaded)

with patch.object(app, "SETTINGS_FILE", _settings_file):
    s2 = dict(app.DEFAULT_SETTINGS)
    s2["password"] = "secret"
    app.save_settings(s2)
    raw = json.loads(_settings_file.read_text())
    check("save: password not written to file", "password" not in raw)

with patch.object(app, "SETTINGS_FILE", _settings_file):
    _settings_file.write_text(json.dumps({"email": "only@this.com"}))
    loaded2 = app.load_settings()
    check("missing keys filled with defaults",  loaded2["sync_mode"] == app.DEFAULT_SETTINGS["sync_mode"])
    check("provided key preserved",             loaded2["email"] == "only@this.com")

with patch.object(app, "SETTINGS_FILE", _settings_file):
    _settings_file.write_text("{not valid json")
    loaded3 = app.load_settings()
    check("corrupt JSON → returns defaults",    loaded3 == app.DEFAULT_SETTINGS)

_missing = _TMPDIR / ".garmin_notexist.json"
with patch.object(app, "SETTINGS_FILE", _missing):
    loaded4 = app.load_settings()
    check("missing file → returns defaults",    loaded4 == app.DEFAULT_SETTINGS)

# ══════════════════════════════════════════════════════════════════════════════
#  4. load_settings / save_settings — garmin_app_standalone
# ══════════════════════════════════════════════════════════════════════════════
section("4. load_settings / save_settings — garmin_app_standalone")

_settings_file_sa = _TMPDIR / ".garmin_archive_settings_sa_test.json"

with patch.object(standalone, "SETTINGS_FILE", _settings_file_sa):
    s = dict(standalone.DEFAULT_SETTINGS)
    s["email"] = "standalone@example.com"
    standalone.save_settings(s)
    loaded = standalone.load_settings()
    check("roundtrip: email preserved",        loaded["email"] == "standalone@example.com")
    check("roundtrip: password stripped",      "password" not in loaded)

with patch.object(standalone, "SETTINGS_FILE", _settings_file_sa):
    s2 = dict(standalone.DEFAULT_SETTINGS)
    s2["password"] = "secret"
    standalone.save_settings(s2)
    raw = json.loads(_settings_file_sa.read_text())
    check("save: password not written to file", "password" not in raw)

with patch.object(standalone, "SETTINGS_FILE", _settings_file_sa):
    _settings_file_sa.write_text("{bad json")
    loaded3 = standalone.load_settings()
    check("corrupt JSON → returns defaults",    loaded3 == standalone.DEFAULT_SETTINGS)

with patch.object(standalone, "SETTINGS_FILE", _TMPDIR / ".notexist_sa.json"):
    loaded4 = standalone.load_settings()
    check("missing file → returns defaults",    loaded4 == standalone.DEFAULT_SETTINGS)

# ══════════════════════════════════════════════════════════════════════════════
#  5. load_password / save_password — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("5. load_password / save_password — garmin_app")

_keyring_mock = MagicMock()
_keyring_mock.get_password.return_value = "mypassword"
with patch.dict(sys.modules, {"keyring": _keyring_mock}):
    importlib.reload(app)
    check("load_password: returns keyring value",    app.load_password() == "mypassword")

_keyring_none = MagicMock()
_keyring_none.get_password.return_value = None
with patch.dict(sys.modules, {"keyring": _keyring_none}):
    importlib.reload(app)
    check("load_password: None → empty string",      app.load_password() == "")

_keyring_fail = MagicMock()
_keyring_fail.get_password.side_effect = Exception("no keyring")
with patch.dict(sys.modules, {"keyring": _keyring_fail}):
    importlib.reload(app)
    check("load_password: exception → empty string", app.load_password() == "")

_keyring_save = MagicMock()
with patch.dict(sys.modules, {"keyring": _keyring_save}):
    importlib.reload(app)
    app.save_password("testpw")
    check("save_password: set_password called",      _keyring_save.set_password.called)

_keyring_save2 = MagicMock()
with patch.dict(sys.modules, {"keyring": _keyring_save2}):
    importlib.reload(app)
    app.save_password("")
    check("save_password empty: delete called",      _keyring_save2.delete_password.called)

_keyring_exc = MagicMock()
_keyring_exc.set_password.side_effect = Exception("fail")
with patch.dict(sys.modules, {"keyring": _keyring_exc}):
    importlib.reload(app)
    try:
        app.save_password("x")
        check("save_password exception: no crash",   True)
    except Exception:
        check("save_password exception: no crash",   False)

importlib.reload(app)

# ══════════════════════════════════════════════════════════════════════════════
#  6. script_dir / script_path — garmin_app dev-Modus
# ══════════════════════════════════════════════════════════════════════════════
section("6. script_dir / script_path — garmin_app dev-Modus")

importlib.reload(app)

sd = app.script_dir()
check("script_dir dev: returns Path",               isinstance(sd, Path))
check("script_dir dev: ends with 'garmin'",         sd.name == "garmin")
check("script_dir dev: is absolute",                sd.is_absolute())

# script_path resolves via Path(__file__) bound at import time — not mockable.
# Test against real project structure when available.
_real_garmin_config = _ROOT / "garmin" / "garmin_config.py"
if _real_garmin_config.exists():
    sp = app.script_path("garmin_config.py")
    check("script_path dev: finds garmin_config.py in garmin/ subdir",
          sp == _real_garmin_config)
else:
    sp = app.script_path("garmin_config.py")
    check("script_path dev: returns a Path",                isinstance(sp, Path))

sp2 = app.script_path("nonexistent_xyz.py")
check("script_path dev: nonexistent → fallback",            sp2.name == "nonexistent_xyz.py")

# ══════════════════════════════════════════════════════════════════════════════
#  7. script_dir / script_path — garmin_app frozen-Modus
# ══════════════════════════════════════════════════════════════════════════════
section("7. script_dir / script_path — garmin_app frozen-Modus")

_fake_exe_dir  = _TMPDIR / "frozen_t2"
_fake_scripts  = _fake_exe_dir / "scripts"
_fake_garmin   = _fake_scripts / "garmin"
_fake_garmin.mkdir(parents=True)
(_fake_garmin / "garmin_collector.py").write_text("# stub")

with patch.object(sys, "frozen", True, create=True), \
     patch.object(sys, "executable", str(_fake_exe_dir / "Garmin_Local_Archive.exe")):
    importlib.reload(app)
    sd_frozen = app.script_dir()
    check("script_dir frozen: points to scripts/",              sd_frozen == _fake_scripts)

    sp_frozen = app.script_path("garmin_collector.py")
    check("script_path frozen: finds in garmin/ subdir",        sp_frozen == _fake_garmin / "garmin_collector.py")

    sp_missing = app.script_path("not_there.py")
    check("script_path frozen: missing → fallback under scripts/", sp_missing == _fake_scripts / "not_there.py")

importlib.reload(app)

# ══════════════════════════════════════════════════════════════════════════════
#  8. script_dir / script_path — garmin_app_standalone dev-Modus
# ══════════════════════════════════════════════════════════════════════════════
section("8. script_dir / script_path — garmin_app_standalone dev-Modus")

importlib.reload(standalone)

sd_sa = standalone.script_dir()
check("script_dir dev: returns Path",               isinstance(sd_sa, Path))
check("script_dir dev: ends with 'garmin'",         sd_sa.name == "garmin")
check("script_dir dev: is absolute",                sd_sa.is_absolute())

_real_garmin_config_sa = _ROOT / "garmin" / "garmin_config.py"
if _real_garmin_config_sa.exists():
    sp_sa = standalone.script_path("garmin_config.py")
    check("script_path dev: finds garmin_config.py in garmin/ subdir",
          sp_sa == _real_garmin_config_sa)
else:
    sp_sa = standalone.script_path("garmin_config.py")
    check("script_path dev: returns a Path",                isinstance(sp_sa, Path))

sp_sa2 = standalone.script_path("nonexistent_xyz.py")
check("script_path dev: nonexistent → fallback",            sp_sa2.name == "nonexistent_xyz.py")

# ══════════════════════════════════════════════════════════════════════════════
#  9. script_dir / script_path — garmin_app_standalone frozen-Modus
# ══════════════════════════════════════════════════════════════════════════════
section("9. script_dir / script_path — garmin_app_standalone frozen-Modus")

_fake_meipass    = _TMPDIR / "fake_meipass"
_fake_sa_scripts = _fake_meipass / "scripts"
_fake_sa_garmin  = _fake_sa_scripts / "garmin"
_fake_sa_garmin.mkdir(parents=True)
(_fake_sa_garmin / "garmin_collector.py").write_text("# stub")

with patch.object(sys, "frozen", True, create=True), \
     patch.object(sys, "_MEIPASS", str(_fake_meipass), create=True):
    importlib.reload(standalone)
    sd_sa_frozen = standalone.script_dir()
    check("script_dir frozen: points to _MEIPASS/scripts/",         sd_sa_frozen == _fake_sa_scripts)

    sp_sa_frozen = standalone.script_path("garmin_collector.py")
    check("script_path frozen: finds in garmin/ subdir",             sp_sa_frozen == _fake_sa_garmin / "garmin_collector.py")

    # Kerntest: v1.4.2-Bug-Klasse
    # Script liegt direkt unter scripts/ statt scripts/garmin/ → Unterordner-Suche schlägt fehl
    (_fake_sa_scripts / "garmin_collector.py").write_text("# wrong location stub")
    (_fake_sa_garmin / "garmin_collector.py").unlink()
    sp_wrong = standalone.script_path("garmin_collector.py")
    check("v1.4.2 regression: wrong-location file not returned as garmin/ path",
          sp_wrong != _fake_sa_garmin / "garmin_collector.py")

    sp_missing_sa = standalone.script_path("not_there.py")
    check("script_path frozen: missing → fallback under scripts/",   sp_missing_sa == _fake_sa_scripts / "not_there.py")

importlib.reload(standalone)

# ══════════════════════════════════════════════════════════════════════════════
#  10. _find_python — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("10. _find_python — garmin_app")

importlib.reload(app)

fp = app._find_python()
check("_find_python dev: returns Path",          isinstance(fp, Path))
check("_find_python dev: equals sys.executable", fp == Path(sys.executable))

_fake_python = str(_TMPDIR / "python.exe")
with patch.object(sys, "frozen", True, create=True), \
     patch.object(sys, "executable", str(_TMPDIR / "fake.exe")), \
     patch("shutil.which", return_value=_fake_python):
    importlib.reload(app)
    fp_frozen = app._find_python()
    check("_find_python frozen: returns which() result", fp_frozen == Path(_fake_python))

importlib.reload(app)

# ── Cleanup ────────────────────────────────────────────────────────────────────
shutil.rmtree(_TMPDIR, ignore_errors=True)

# ── Summary ───────────────────────────────────────────────────────────────────
total = _pass + _fail
print(f"\n{'═' * 55}")
print(f"  Result: {_pass}/{total} checks passed", end="")
if _fail:
    print(f"  ({_fail} failed)")
    print(f"\n  Failed checks:")
    for f in _failures:
        print(f"    ✗  {f}")
else:
    print("  ✓")
print(f"{'═' * 55}")

sys.exit(0 if _fail == 0 else 1)