#!/usr/bin/env python3
"""
test_app_logic.py — Garmin Local Archive — App Layer Logic Test

Run from the project folder:
    python tests/test_app_logic.py

No network, no GUI, no Garmin API calls.
Tests module-level functions in garmin_app_base.py, garmin_app.py,
and garmin_app_standalone.py.
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
sys.path.insert(0, str(_ROOT / "maps"))
sys.path.insert(0, str(_ROOT / "dashboards"))
sys.path.insert(0, str(_ROOT / "layouts"))
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT / "context"))
logging.disable(logging.CRITICAL)

# ── Suppress tkinter at import time ───────────────────────────────────────────
_tk_mock = MagicMock()
sys.modules.setdefault("tkinter", _tk_mock)
sys.modules.setdefault("tkinter.ttk", _tk_mock)
sys.modules.setdefault("tkinter.filedialog", _tk_mock)
sys.modules.setdefault("tkinter.scrolledtext", _tk_mock)
sys.modules.setdefault("tkinter.messagebox", _tk_mock)

import importlib
import garmin_app_base as base
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
#  1. DEFAULT_SETTINGS — garmin_app_base (unified source)
# ══════════════════════════════════════════════════════════════════════════════
section("1. DEFAULT_SETTINGS — garmin_app_base")

REQUIRED_KEYS = [
    "email", "base_dir", "sync_mode", "sync_days",
    "sync_from", "sync_to", "date_from", "date_to",
    "age", "sex", "request_delay_min", "request_delay_max",
    "timer_min_interval", "timer_max_interval",
    "timer_min_days", "timer_max_days",
    "context_latitude", "context_longitude",
]

for key in REQUIRED_KEYS:
    check(f"DEFAULT_SETTINGS has '{key}'", key in base.DEFAULT_SETTINGS)

check("base_dir default is string",        isinstance(base.DEFAULT_SETTINGS["base_dir"], str))
check("sync_mode default = recent",        base.DEFAULT_SETTINGS["sync_mode"] == "recent")
check("sync_days default = 90",            base.DEFAULT_SETTINGS["sync_days"] == "90")
check("age default = 35",                  base.DEFAULT_SETTINGS["age"] == "35")
check("sex default = male",                base.DEFAULT_SETTINGS["sex"] == "male")
check("context_latitude present",          "context_latitude" in base.DEFAULT_SETTINGS)
check("context_longitude present",         "context_longitude" in base.DEFAULT_SETTINGS)

# ══════════════════════════════════════════════════════════════════════════════
#  2. DEFAULT_SETTINGS — garmin_app and standalone re-export base
# ══════════════════════════════════════════════════════════════════════════════
section("2. DEFAULT_SETTINGS — app and standalone use base")

check("base.DEFAULT_SETTINGS has all required keys",
      all(k in base.DEFAULT_SETTINGS for k in REQUIRED_KEYS))
check("app does not shadow DEFAULT_SETTINGS",
      not hasattr(app, "DEFAULT_SETTINGS"))
check("standalone does not shadow DEFAULT_SETTINGS",
      not hasattr(standalone, "DEFAULT_SETTINGS"))

# ══════════════════════════════════════════════════════════════════════════════
#  3. load_settings / save_settings — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("3. load_settings / save_settings — garmin_app_base")

_settings_file = _TMPDIR / ".garmin_archive_settings_test.json"

with patch.object(base, "SETTINGS_FILE", _settings_file):
    s = dict(base.DEFAULT_SETTINGS)
    s["email"] = "test@example.com"
    base.save_settings(s)
    loaded = base.load_settings()
    check("roundtrip: email preserved",        loaded["email"] == "test@example.com")
    check("roundtrip: sync_mode preserved",    loaded["sync_mode"] == "recent")
    check("roundtrip: password stripped",      "password" not in loaded)

with patch.object(base, "SETTINGS_FILE", _settings_file):
    s2 = dict(base.DEFAULT_SETTINGS)
    s2["password"] = "secret"
    base.save_settings(s2)
    raw = json.loads(_settings_file.read_text())
    check("save: password not written to file", "password" not in raw)

with patch.object(base, "SETTINGS_FILE", _settings_file):
    _settings_file.write_text(json.dumps({"email": "only@this.com"}))
    loaded2 = base.load_settings()
    check("missing keys filled with defaults",  loaded2["sync_mode"] == base.DEFAULT_SETTINGS["sync_mode"])
    check("provided key preserved",             loaded2["email"] == "only@this.com")

with patch.object(base, "SETTINGS_FILE", _settings_file):
    _settings_file.write_text("{not valid json")
    loaded3 = base.load_settings()
    check("corrupt JSON → returns defaults",    loaded3 == base.DEFAULT_SETTINGS)

_missing = _TMPDIR / ".garmin_notexist.json"
with patch.object(base, "SETTINGS_FILE", _missing):
    loaded4 = base.load_settings()
    check("missing file → returns defaults",    loaded4 == base.DEFAULT_SETTINGS)

# ══════════════════════════════════════════════════════════════════════════════
#  4. load_settings / save_settings — garmin_app_standalone
# ══════════════════════════════════════════════════════════════════════════════
section("4. load_settings / save_settings — shared via base (smoke test)")

# Settings functions live in base — full tests in section 3.
# Here: confirm app and standalone do not shadow base functions.
check("base.load_settings callable",           callable(base.load_settings))
check("base.save_settings callable",           callable(base.save_settings))
check("app does not shadow load_settings",     not hasattr(app, "load_settings"))
check("app does not shadow save_settings",     not hasattr(app, "save_settings"))
check("standalone does not shadow load_settings",
      not hasattr(standalone, "load_settings"))
check("standalone does not shadow save_settings",
      not hasattr(standalone, "save_settings"))

# ══════════════════════════════════════════════════════════════════════════════
#  5. load_password / save_password — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("5. load_password / save_password — garmin_app_base")

_keyring_mock = MagicMock()
_keyring_mock.get_password.return_value = "mypassword"
with patch.dict(sys.modules, {"keyring": _keyring_mock}):
    importlib.reload(base)
    check("load_password: returns keyring value",    base.load_password() == "mypassword")

_keyring_none = MagicMock()
_keyring_none.get_password.return_value = None
with patch.dict(sys.modules, {"keyring": _keyring_none}):
    importlib.reload(base)
    check("load_password: None → empty string",      base.load_password() == "")

_keyring_fail = MagicMock()
_keyring_fail.get_password.side_effect = Exception("no keyring")
with patch.dict(sys.modules, {"keyring": _keyring_fail}):
    importlib.reload(base)
    check("load_password: exception → empty string", base.load_password() == "")

_keyring_save = MagicMock()
with patch.dict(sys.modules, {"keyring": _keyring_save}):
    importlib.reload(base)
    base.save_password("testpw")
    check("save_password: set_password called",      _keyring_save.set_password.called)

_keyring_save2 = MagicMock()
with patch.dict(sys.modules, {"keyring": _keyring_save2}):
    importlib.reload(base)
    base.save_password("")
    check("save_password empty: delete called",      _keyring_save2.delete_password.called)

_keyring_exc = MagicMock()
_keyring_exc.set_password.side_effect = Exception("fail")
with patch.dict(sys.modules, {"keyring": _keyring_exc}):
    importlib.reload(base)
    try:
        base.save_password("x")
        check("save_password exception: no crash",   True)
    except Exception:
        check("save_password exception: no crash",   False)

importlib.reload(base)
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

# ══════════════════════════════════════════════════════════════════════════════
#  11. save_settings — OSError handling — garmin_app
# ══════════════════════════════════════════════════════════════════════════════
section("11. save_settings — OSError handling — garmin_app_base")

importlib.reload(base)

_readonly_dir = _TMPDIR / "readonly_dir"
_readonly_dir.mkdir(exist_ok=True)
_bad_settings_file = _readonly_dir / "sub" / "settings.json"  # non-existent parent

_showerror_calls = []
with patch.object(base, "SETTINGS_FILE", _bad_settings_file), \
     patch("garmin_app_base.messagebox.showerror", side_effect=lambda *a, **k: _showerror_calls.append(a)):
    base.save_settings({"email": "x@y.com"})
    check("OSError: showerror called",       len(_showerror_calls) == 1)
    check("OSError: title is 'Settings'",    _showerror_calls[0][0] == "Settings")
    check("OSError: file not created",       not _bad_settings_file.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  12. save_settings — OSError handling — garmin_app_standalone
# ══════════════════════════════════════════════════════════════════════════════
section("12. Hook implementation — _run / _log_bg / _is_running")

# Source-text checks — GarminApp is not instantiable without real tkinter.
import inspect as _inspect

_base_src = _inspect.getsource(base)
_app_src   = Path(_ROOT / "garmin_app.py").read_text(encoding="utf-8")
_sa_src    = Path(_ROOT / "garmin_app_standalone.py").read_text(encoding="utf-8")

check("base: _run raises NotImplementedError",
      "def _run(" in _base_src and "raise NotImplementedError" in _base_src)
check("base: _log_bg raises NotImplementedError",
      "def _log_bg(" in _base_src and "raise NotImplementedError" in _base_src)
check("base: _is_running raises NotImplementedError",
      "def _is_running(" in _base_src and "raise NotImplementedError" in _base_src)

check("app: _run defined in GarminApp",      "def _run(" in _app_src)
check("app: _log_bg defined in GarminApp",   "def _log_bg(" in _app_src)
check("app: _is_running defined",            "def _is_running(" in _app_src)
check("app: _stop_collector defined",        "def _stop_collector(" in _app_src)
check("app: no NotImplementedError in _run", "raise NotImplementedError" not in _app_src)

check("standalone: _run defined",            "def _run(" in _sa_src)
check("standalone: _log_bg defined",         "def _log_bg(" in _sa_src)
check("standalone: _is_running defined",     "def _is_running(" in _sa_src)
check("standalone: _stop_collector defined", "def _stop_collector(" in _sa_src)
check("standalone: no NotImplementedError",  "raise NotImplementedError" not in _sa_src)

# _build_env_dict — load base without tkinter mock to access real class
import importlib as _il_base
import types as _types
_real_tk = _types.ModuleType("tkinter")
_real_tk.Tk = object  # minimal stub so class definition works
_base_spec = _il_base.util.spec_from_file_location(
    "garmin_app_base_real", _ROOT / "garmin_app_base.py")
_base_real_mod = _il_base.util.module_from_spec(_base_spec)
_base_real_mod.__dict__["tkinter"] = _real_tk
import sys as _sys
_sys.modules["garmin_app_base_real"] = _base_real_mod
with patch.dict(_sys.modules, {"tkinter": _real_tk,
                                "tkinter.ttk": MagicMock(),
                                "tkinter.filedialog": MagicMock(),
                                "tkinter.scrolledtext": MagicMock(),
                                "tkinter.messagebox": MagicMock()}):
    _base_spec.loader.exec_module(_base_real_mod)

_mock_self = MagicMock()
_mock_self._log_level = "INFO"
_test_s = {
    "email": "t@t.com", "password": "pw",
    "base_dir": str(_TMPDIR), "sync_mode": "recent",
    "sync_days": "90", "sync_from": "", "sync_to": "",
    "date_from": "", "date_to": "",
    "age": "35", "sex": "male",
    "request_delay_min": "5.0", "request_delay_max": "20.0",
    "sync_auto_fallback": "",
}
_env = _base_real_mod.GarminAppBase._build_env_dict(_mock_self, _test_s, refresh_failed=False)
check("_build_env_dict: returns dict",              isinstance(_env, dict))
check("_build_env_dict: GARMIN_EMAIL present",      "GARMIN_EMAIL" in _env)
check("_build_env_dict: GARMIN_PASSWORD present",   "GARMIN_PASSWORD" in _env)
check("_build_env_dict: GARMIN_OUTPUT_DIR present", "GARMIN_OUTPUT_DIR" in _env)
check("_build_env_dict: GARMIN_REFRESH_FAILED=0",   _env.get("GARMIN_REFRESH_FAILED") == "0")
_env_r = _base_real_mod.GarminAppBase._build_env_dict(_mock_self, _test_s, refresh_failed=True)
check("_build_env_dict: GARMIN_REFRESH_FAILED=1",   _env_r.get("GARMIN_REFRESH_FAILED") == "1")
check("_build_env_dict: no os.environ side-effect",
      os.environ.get("GARMIN_EMAIL") != "t@t.com")

# ══════════════════════════════════════════════════════════════════════════════
#  13. age-Cast — robust float handling — dash specialists
# ══════════════════════════════════════════════════════════════════════════════
section("13. age-Cast — robust float handling — dash specialists")

_dashboards_dir = _ROOT / "dashboards"

for _dash_name in [
    "sleep_recovery_context_dash.py",
    "health_garmin_html-json_dash.py",
]:
    _src_text = (_dashboards_dir / _dash_name).read_text(encoding="utf-8")
    check(f"{_dash_name}: age uses int(float(...))",
          "int(float(settings.get" in _src_text)
    check(f"{_dash_name}: age has TypeError/ValueError guard",
          "TypeError, ValueError" in _src_text)

# ══════════════════════════════════════════════════════════════════════════════
#  14. _timer_run_bulk_recheck — method exists, returns None without log file
# ══════════════════════════════════════════════════════════════════════════════
section("14. _timer_run_bulk_recheck — structural + None-return")

# Method lives in base — source-text check for app and standalone
_base_src_text = Path(_ROOT / "garmin_app_base.py").read_text(encoding="utf-8")
check("base: _timer_run_bulk_recheck defined",
      "def _timer_run_bulk_recheck(" in _base_src_text)
check("app: does not shadow _timer_run_bulk_recheck",
      "def _timer_run_bulk_recheck(" not in _app_src)
check("standalone: does not shadow _timer_run_bulk_recheck",
      "def _timer_run_bulk_recheck(" not in _sa_src)

# Functional test via _base_real_mod (loaded without tkinter mock in section 12)
import datetime as _dt
_mock_inst       = MagicMock()
_no_log_settings = {"base_dir": str(_TMPDIR / "no_such_dir")}

_result_none = _base_real_mod.GarminAppBase._timer_run_bulk_recheck(
    _mock_inst, _no_log_settings)
check("returns None when no quality_log.json", _result_none is None)

_bulk_log_dir  = _TMPDIR / "bulk_test" / "garmin_data" / "log"
_bulk_log_dir.mkdir(parents=True, exist_ok=True)
_bulk_log_file = _bulk_log_dir / "quality_log.json"
_recent_date   = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
_old_date      = (_dt.date.today() - _dt.timedelta(days=200)).isoformat()
_bulk_log_file.write_text(json.dumps({"days": [
    {"date": _recent_date, "source": "bulk", "quality": "medium", "recheck": True},
    {"date": _old_date,    "source": "bulk", "quality": "low",    "recheck": True},
    {"date": _recent_date, "source": "api",  "quality": "high",   "recheck": False},
]}), encoding="utf-8")

_bulk_settings = {"base_dir": str(_TMPDIR / "bulk_test")}
_result_bulk   = _base_real_mod.GarminAppBase._timer_run_bulk_recheck(
    _mock_inst, _bulk_settings)
check("returns list when bulk+recheck candidates exist",
      isinstance(_result_bulk, list) and len(_result_bulk) == 1)
check("excludes entries older than 180 days",
      all(d >= _dt.date.today() - _dt.timedelta(days=180) for d in (_result_bulk or [])))
check("excludes api-sourced entries",
      len(_result_bulk or []) == 1)

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