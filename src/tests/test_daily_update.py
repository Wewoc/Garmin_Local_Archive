#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_daily_update.py — scheduler/daily_update.py, the schema-migration step (v1.7.6.4)

What _check_schema_migration() counts, what step 4 of main() does, and (v1.7.6.4, opt-in
"daily_update_auto_migrate") how the daily run makes a safety copy and migrates the
summaries itself. D1/D2 were taken as Ist-Stand pins before the opt-in was built; with the
setting off they still hold.

Run from the project folder:
    python tests/test_daily_update.py

Archives are synthetic (a summary/ folder with schema_version only); everything main()
reaches after step 4 is replaced by stand-ins.
"""

import importlib.util
import json
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from gla_testenv import _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_normalizer as normalizer

_du_spec = importlib.util.spec_from_file_location(
    "daily_update_du", Path(__file__).resolve().parent.parent / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)

_CUR = normalizer.CURRENT_SCHEMA_VERSION


class _Rec:
    """Stand-in for the module logger — keeps the messages per level."""
    def __init__(self):
        self.m = {"debug": [], "info": [], "warning": [], "error": []}
        for lvl in self.m:
            setattr(self, lvl, (lambda lv: lambda s, *a, **k: self.m[lv].append(s))(lvl))


def _put_summary(arch, d, schema="__missing__", name=None):
    """A summary file of the archive; schema "__missing__" = no schema_version key at all."""
    folder = arch / "garmin_data" / "summary"
    folder.mkdir(parents=True, exist_ok=True)
    data = {"date": d} if schema == "__missing__" else {"date": d, "schema_version": schema}
    (folder / (name or f"garmin_{d}.json")).write_text(json.dumps(data), encoding="utf-8")


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ══════════════════════════════════════════════════════════════════════════════
#  D1. _check_schema_migration(base_dir) — what counts as outdated
# ══════════════════════════════════════════════════════════════════════════════
section("D1. daily_update._check_schema_migration")

with _isolated_log_env("du_check") as _b:
    _a = _b / "archive"
    check("D1 no summary folder -> False", _du._check_schema_migration(_a) is False)

    _put_summary(_a, "2025-01-01", _CUR)
    _put_summary(_a, "2025-01-02", _CUR + 1)
    check("D1 all summaries at the current schema or newer -> False", _du._check_schema_migration(_a) is False)

    _put_summary(_a, "2025-01-03", _CUR - 1)
    check("D1 one summary below the current schema -> True", _du._check_schema_migration(_a) is True)

with _isolated_log_env("du_check_missing") as _b:
    _a = _b / "archive"
    _put_summary(_a, "2025-01-01", _CUR)
    _put_summary(_a, "2025-01-02")
    check("D1 a summary without a schema_version counts as outdated (0 < current) -> True",
          _du._check_schema_migration(_a) is True)

with _isolated_log_env("du_check_noise") as _b:
    _a = _b / "archive"
    _put_summary(_a, "2025-01-01", _CUR)
    _put_summary(_a, "2025-01-02", 1, name="garmin_notes.json")         # not a day file
    _put_summary(_a, "2025-01-03", 1, name="garmin_2025-01-03.json.bak")  # other extension
    (_a / "garmin_data" / "summary" / "garmin_2025-01-04.json").write_text("{not json", encoding="utf-8")
    check("D1 only garmin_YYYY-MM-DD.json counts; a file that is not a day file or cannot be read is ignored -> False",
          _du._check_schema_migration(_a) is False)

with _isolated_log_env("du_check_nolog") as _b:
    _a = _b / "archive"
    _put_summary(_a, "2025-01-03", _CUR - 1)
    check("D1 the check looks at summary/ only: a day that is not in the quality log still counts "
          "(the collector's migration iterates over the quality log, so such a day stays outdated)",
          not (_a / "garmin_data" / "log").exists() and _du._check_schema_migration(_a) is True)

with _isolated_log_env("du_check_ro") as _b:
    _a = _b / "archive"
    _put_summary(_a, "2025-01-03", _CUR - 1)
    _before = _tree(_a)
    _du._check_schema_migration(_a)
    check("D1 the check only reads — no file of the archive changes", _tree(_a) == _before)

# ══════════════════════════════════════════════════════════════════════════════
#  D2. main() — step 4 today
# ══════════════════════════════════════════════════════════════════════════════
section("D2. daily_update.main(): step 4, schema migration")

_ENV_KEY = "GARMIN_SCHEMA_MIGRATE"


def _run_main(arch, outdated, settings_extra=None, gap=(None, None, 0), snapshot=True, left=0, gui=False):
    """Runs main() with everything outside step 4 and the unattended migration replaced. Returns
    (exit code, mocks, log recorder, environment as main() left it, order of the steps).
    snapshot: result of the safety copy (bool); left: summaries still
    outdated after the sync; gui: the app's lock is alive. m["sync_env"] holds GARMIN_SCHEMA_MIGRATE
    as the sync saw it."""
    s = {"email": "a@b.c", "base_dir": str(arch), **(settings_extra or {})}
    order = []
    sync_env = []

    def _snap():
        order.append("snapshot")
        return snapshot

    m = {
        "sync_env": sync_env,
        "close":   MagicMock(),
        "snapshot": MagicMock(side_effect=_snap),
        "count":   MagicMock(side_effect=lambda *_a, **_k: order.append("recheck") or left),
        "sync":    MagicMock(side_effect=lambda: order.append("sync") or sync_env.append(os.environ.get(_ENV_KEY)) or True),
        "context": MagicMock(side_effect=lambda *_: order.append("context") or True),
        "dash":    MagicMock(side_effect=lambda *_: order.append("dash") or True),
        "gap":     MagicMock(side_effect=lambda *_: order.append("gap") or gap),
        "rhr":     MagicMock(side_effect=lambda *_: order.append("hint_rhr") or 0),
        "track":   MagicMock(side_effect=lambda *_: order.append("hint_track") or 0),
        "version": MagicMock(side_effect=lambda: order.append("version") or (None, None)),
        "schema":  MagicMock(side_effect=lambda *_: order.append("schema_check") or outdated),
        "folder":  MagicMock(side_effect=lambda *_: order.append("folder_check") or False),
    }
    rec = _Rec()
    # one ExitStack, not one `with` of 21 managers: Python 3.11 refuses more than 20 nested blocks
    patches = [
        patch.dict(os.environ, {}, clear=False),
        patch.object(_du, "log", rec),
        patch.object(_du, "_setup_paths"),
        patch.object(_du, "_load_settings", return_value=s),
        patch.object(_du, "_load_password", return_value="pw"),
        patch.object(_du, "_start_daily_log"),
        patch.object(_du, "_close_daily_log", m["close"]),
        patch.object(_du, "_attach_redact_filter"),
        patch.object(_du, "_check_folder_migration", m["folder"]),
        patch.object(_du, "_check_schema_migration", m["schema"]),
        patch.object(_du, "_make_migration_snapshot", m["snapshot"]),
        patch.object(_du, "_count_outdated_summaries", m["count"]),
        patch.object(_du.process_status, "is_running", return_value=gui),
        patch.object(_du, "_check_resting_hr_repair", m["rhr"]),
        patch.object(_du, "_check_track_migration", m["track"]),
        patch.object(_du, "_check_version", m["version"]),
        patch.object(_du, "_detect_gap", m["gap"]),
        patch.object(_du, "_run_garmin_sync", m["sync"]),
        patch.object(_du, "_run_context_sync", m["context"]),
        patch.object(_du, "_run_dashboards", m["dash"]),
        patch.object(_du, "_run_export"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        os.environ.pop(_ENV_KEY, None)
        code = _du.main()
        env_after = dict(os.environ)
    return code, m, rec, env_after, order


with _isolated_log_env("du_main_ok") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=False)
    check("D2 summaries current: the run goes on and ends with exit code 0", _code == 0 and _m["sync"].call_count == 1)
    check("D2 order: folder check, schema check, the two hints, version check, gap, sync, context, dashboards",
          _order == ["folder_check", "schema_check", "hint_rhr", "hint_track", "version", "gap", "sync", "context", "dash"])
    check("D2 summaries current: nothing sets GARMIN_SCHEMA_MIGRATE for the collector", _ENV_KEY not in _env)

with _isolated_log_env("du_main_stop") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True)
    check("D2 summaries outdated: main() returns 1", _code == 1)
    check("D2 it stops with two error lines and nothing else",
          _rec.m["error"] == ["  Schema migration required.", "  Please open the app to run the migration first."])
    check("D2 order: only the folder check and the schema check ran", _order == ["folder_check", "schema_check"])
    check("D2 no hint, no version check, no gap detection, no sync, no context sync, no dashboards",
          all(_m[k].call_count == 0 for k in ("rhr", "track", "version", "gap", "sync", "context", "dash")))
    check("D2 GARMIN_SCHEMA_MIGRATE is not set", _ENV_KEY not in _env)

with _isolated_log_env("du_main_setting_off") as _b:
    for _val in (False, None, 0):
        _code, _m, _rec, _env, _order = _run_main(
            _b / "archive", outdated=True, settings_extra={"daily_update_auto_migrate": _val})
        check(f"D2 the opt-in off ({_val!r}): outdated summaries still stop the run with 1, no safety copy, no sync",
              _code == 1 and _m["sync"].call_count == 0 and _m["snapshot"].call_count == 0 and _ENV_KEY not in _env)

with _isolated_log_env("du_main_gap") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, gap=(None, None, 99))
    check("D2 the schema check comes before the gap check: outdated summaries and a huge gap -> 1, gap detection never ran",
          _code == 1 and _m["gap"].call_count == 0)

with _isolated_log_env("du_main_gap_ok") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=False, gap=(None, None, 99))
    check("D2 current summaries and a gap above the hard stop -> 3, no sync (the gap check is after step 4)",
          _code == 3 and _m["sync"].call_count == 0 and _m["gap"].call_count == 1)

with _isolated_log_env("du_main_real") as _b:
    # the real _check_schema_migration, not the stand-in: an outdated summary stops the run
    _a = _b / "archive"
    _put_summary(_a, "2025-02-01", _CUR - 1)
    _s = {"email": "a@b.c", "base_dir": str(_a)}
    _rec = _Rec()
    _sync = MagicMock(return_value=True)
    with patch.dict(os.environ, {}, clear=False), patch.object(_du, "log", _rec), \
            patch.object(_du, "_setup_paths"), patch.object(_du, "_load_settings", return_value=_s), \
            patch.object(_du, "_load_password", return_value="pw"), patch.object(_du, "_start_daily_log"), \
            patch.object(_du, "_close_daily_log"), patch.object(_du, "_attach_redact_filter"), \
            patch.object(_du, "_run_garmin_sync", _sync):
        _code_real = _du.main()
    check("D2 end to end with a real archive: one outdated summary -> exit code 1, the sync is not started",
          _code_real == 1 and _sync.call_count == 0)

# ══════════════════════════════════════════════════════════════════════════════
#  D3. main() — the opt-in "daily_update_auto_migrate" (v1.7.6.4, Baustein A3)
# ══════════════════════════════════════════════════════════════════════════════
section("D3. daily_update.main(): unattended schema migration (opt-in)")

_ON = {"daily_update_auto_migrate": True}
_FULL_ORDER = ["folder_check", "schema_check", "hint_rhr", "hint_track", "version", "gap",
               "snapshot", "sync", "recheck", "context", "dash"]

with _isolated_log_env("du_on") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, settings_extra=_ON)
    check("D3 opt-in on and summaries outdated: the run goes on and ends with 0", _code == 0)
    check("D3 order: gap check, then the safety copy, then the sync, then the re-check, then context and dashboards",
          _order == _FULL_ORDER)
    check("D3 the sync sees GARMIN_SCHEMA_MIGRATE=1 (exactly once, one sync)", _m["sync_env"] == ["1"])
    check("D3 the variable is removed after the sync", _ENV_KEY not in _env)
    check("D3 a clean run logs no error and no warning", _rec.m["error"] == [] and _rec.m["warning"] == [])

with _isolated_log_env("du_on_left") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, settings_extra=_ON, left=3)
    check("D3 summaries still outdated after the sync: a warning with the number, the exit code stays 0",
          _code == 0 and _rec.m["warning"] == [
              "  3 summary file(s) are still on an outdated schema after the migration.",
              "  See the schema migration lines above; open the app and run Sync Garmin once to migrate them."]
          and _rec.m["error"] == [])

with _isolated_log_env("du_on_fail") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, settings_extra=_ON, snapshot=False)
    check("D3 no safety copy: exit 1, nothing else runs (no sync, no re-check, no context, no dashboards)",
          _code == 1 and _order == ["folder_check", "schema_check", "hint_rhr", "hint_track", "version", "gap", "snapshot"])
    check("D3 no safety copy: GARMIN_SCHEMA_MIGRATE was never set", _m["sync_env"] == [] and _ENV_KEY not in _env)
    check("D3 no safety copy: the daily log is closed before the run returns", _m["close"].call_count == 1)
    check("D3 no safety copy: the error lines say that nothing was changed",
          _rec.m["error"] == ["  Schema migration not started, nothing was changed.",
                              "  Please open the app to run the migration first."])

with _isolated_log_env("du_on_gap") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, settings_extra=_ON, gap=(None, None, 99))
    check("D3 a gap above the hard stop ends the run with 3 before any safety copy is made",
          _code == 3 and _m["snapshot"].call_count == 0 and _m["sync"].call_count == 0 and _ENV_KEY not in _env)

with _isolated_log_env("du_on_current") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=False, settings_extra=_ON)
    check("D3 opt-in on but summaries current: no safety copy, no variable, no re-check",
          _code == 0 and _m["snapshot"].call_count == 0 and _m["count"].call_count == 0 and _m["sync_env"] == [None])

with _isolated_log_env("du_on_gui") as _b:
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=True, settings_extra=_ON, gui=True)
    check("D3 the app is open: a warning, the migration goes on (E8)",
          _code == 0 and _order == _FULL_ORDER and _m["sync_env"] == ["1"]
          and _rec.m["warning"] == ["  The app is open. The migration goes on; close the app if you see errors."])
    _code, _m, _rec, _env, _order = _run_main(_b / "archive", outdated=False, settings_extra=_ON, gui=True)
    check("D3 the app is open but nothing is migrated: no warning about it", _code == 0 and _rec.m["warning"] == [])

# ══════════════════════════════════════════════════════════════════════════════
#  D4. _make_migration_snapshot — what counts as a safety copy
# ══════════════════════════════════════════════════════════════════════════════
section("D4. daily_update._make_migration_snapshot")
import garmin_migration_snapshot as _snap

_GOOD = {"ok": True, "path": Path("backup") / "migration" / "migration_2026-10-26_040000.zip",
         "raw": 12, "summary": 12, "log": True, "bytes": 5 * 1048576 + 17}

_rec = _Rec()
with patch.object(_du, "log", _rec), patch.object(_snap, "create_snapshot", return_value=dict(_GOOD)) as _cs:
    _ok = _du._make_migration_snapshot()
check("D4 a checked copy: True, create_snapshot called once, without a stop callback", _ok is True and _cs.call_count == 1
      and _cs.call_args == ((), {}))
check("D4 the log names the copy with its numbers and the way back, no error",
      any("migration_2026-10-26_040000.zip" in m and "12 raw, 12 summary file(s), 5 MB" in m for m in _rec.m["info"])
      and any("restore_migration_snapshot.py migration_2026-10-26_040000.zip" in m for m in _rec.m["info"])
      and _rec.m["error"] == [])

for _label, _res, _text in (
        ("not ok", {**_GOOD, "ok": False, "path": None, "reason": "not enough free space (3 MB free, 40 MB of files to back up)"},
         "  Safety copy failed: not enough free space (3 MB free, 40 MB of files to back up)"),
        ("ok but no file", {**_GOOD, "path": None}, "  Safety copy failed: no copy was made"),
        ("not ok although a path is named", {**_GOOD, "ok": False, "reason": "the ZIP failed its check: x"},
         "  Safety copy failed: the ZIP failed its check: x"),
        ("not ok without reason", {"ok": False, "path": None}, "  Safety copy failed: no copy was made")):
    _rec = _Rec()
    with patch.object(_du, "log", _rec), patch.object(_snap, "create_snapshot", return_value=_res):
        _ok = _du._make_migration_snapshot()
    check(f"D4 {_label}: False and the reason in an error line, nothing about a copy in the info lines",
          _ok is False and _rec.m["error"] == [_text] and not any("Safety copy:" in m for m in _rec.m["info"]))

_rec = _Rec()
with patch.object(_du, "log", _rec), patch.object(_snap, "create_snapshot", side_effect=RuntimeError("boom")):
    _ok = _du._make_migration_snapshot()
check("D4 an exception in create_snapshot: False, type and message in the error line, nothing raised",
      _ok is False and _rec.m["error"] == ["  Safety copy failed: RuntimeError: boom"])

# ══════════════════════════════════════════════════════════════════════════════
#  D5. _count_outdated_summaries
# ══════════════════════════════════════════════════════════════════════════════
section("D5. daily_update._count_outdated_summaries")

with _isolated_log_env("du_count") as _b:
    _a = _b / "archive"
    check("D5 no summary folder -> 0", _du._count_outdated_summaries(_a) == 0)
    _put_summary(_a, "2025-03-01", _CUR)
    _put_summary(_a, "2025-03-02", _CUR - 1)
    _put_summary(_a, "2025-03-03", _CUR - 2)
    _put_summary(_a, "2025-03-04")
    _put_summary(_a, "2025-03-05", 1, name="garmin_notes.json")
    (_a / "garmin_data" / "summary" / "garmin_2025-03-06.json").write_text("{not json", encoding="utf-8")
    check("D5 counts every outdated day file (older schema, no schema_version), not the current one, a foreign name or a broken file",
          _du._count_outdated_summaries(_a) == 3)
    check("D5 first_only stops at one", _du._count_outdated_summaries(_a, first_only=True) == 1)
    check("D5 _check_schema_migration is the same count turned into a bool", _du._check_schema_migration(_a) is True)

# ══════════════════════════════════════════════════════════════════════════════
#  D6. End to end — real archive, real safety copy, real migration, real way back
# ══════════════════════════════════════════════════════════════════════════════
section("D6. Unattended migration end to end (real archive, copy, migration, restore)")
import garmin_backup as _backup
import garmin_collector as _collector
import garmin_quality as _quality
import garmin_writer as _writer
from gla_testenv import _cfg_values, _day_raw, _put_log, cfg

_DAYS6 = ["2025-04-01", "2025-04-02", "2025-04-03"]

with _isolated_log_env("du_e2e") as _b:
    _gd = _b / "garmin_data"
    with _cfg_values(RAW_DIR=_gd / "raw", SUMMARY_DIR=_gd / "summary", LOG_DIR=_gd / "log",
                     QUALITY_LOG_FILE=_gd / "log" / "quality_log.json",
                     MIGRATION_BACKUP_DIR=_gd / "backup" / "migration"):
        cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with patch.object(_backup, "backup_raw"):
            for _d in _DAYS6:
                _norm = normalizer.normalize(_day_raw(_d), source="api")
                _writer.write_day(_norm, normalizer.summarize(_norm), _d)
        _old = {}
        for _d in _DAYS6:                                  # the summaries as an older version wrote them
            _p = cfg.SUMMARY_DIR / f"garmin_{_d}.json"
            _s = json.loads(_p.read_text(encoding="utf-8"))
            _s["schema_version"] = _CUR - 1
            _p.write_text(json.dumps(_s, indent=2), encoding="utf-8")
            _old[_d] = _p.read_bytes()
        _put_log({"first_day": _DAYS6[0], "devices": [],
                  "days": [{"date": _d, "quality": "standard", "source": "api", "write": True, "recheck": False,
                            "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None, "fields": {}}
                           for _d in _DAYS6]})
        _seen = {}

        def _sync_like_collector():
            """Stand-in for garmin_collector.main(): its step 3c, on the quality log of the run."""
            _seen["zips"] = sorted(p.name for p in cfg.MIGRATION_BACKUP_DIR.glob("migration_*.zip"))
            _seen["env"] = os.environ.get(_ENV_KEY)
            if os.environ.get(_ENV_KEY) == "1":
                _collector._run_schema_migration(_quality._load_quality_log())
            return True

        _rec = _Rec()
        _s6 = {"email": "a@b.c", "base_dir": str(_b), **_ON}
        with patch.dict(os.environ, {}, clear=False), patch.object(_du, "log", _rec), \
                patch.object(_du, "_setup_paths"), patch.object(_du, "_load_settings", return_value=_s6), \
                patch.object(_du, "_load_password", return_value="pw"), patch.object(_du, "_start_daily_log"), \
                patch.object(_du, "_close_daily_log"), patch.object(_du, "_attach_redact_filter"), \
                patch.object(_du, "_check_resting_hr_repair"), patch.object(_du, "_check_track_migration"), \
                patch.object(_du, "_check_version", return_value=(None, None)), \
                patch.object(_du, "_detect_gap", return_value=(None, None, 0)), \
                patch.object(_du, "_run_garmin_sync", _sync_like_collector), \
                patch.object(_du, "_run_context_sync", return_value=True), \
                patch.object(_du, "_run_dashboards", return_value=True), patch.object(_du, "_run_export"), \
                patch.object(_du.process_status, "is_running", return_value=False):
            os.environ.pop(_ENV_KEY, None)
            _code6 = _du.main()
            _env6 = os.environ.get(_ENV_KEY)
        _zips = sorted(cfg.MIGRATION_BACKUP_DIR.glob("migration_*.zip"))
        check("D6 the run ends with 0 and leaves no variable behind", _code6 == 0 and _env6 is None)
        check("D6 the safety copy existed before the sync started, and the sync saw the variable",
              len(_seen["zips"]) == 1 and _seen["env"] == "1" and len(_zips) == 1)
        check("D6 the copy is a checked snapshot with the 3 raw, the 3 summary files and the log",
              _snap.verify_snapshot(_zips[0])["ok"]
              and (_snap.verify_snapshot(_zips[0])["raw"], _snap.verify_snapshot(_zips[0])["summary"],
                   _snap.verify_snapshot(_zips[0])["log"]) == (3, 3, True))
        check("D6 the migration rewrote all summaries to the current schema; the check finds nothing any more",
              all(json.loads((cfg.SUMMARY_DIR / f"garmin_{_d}.json").read_text(encoding="utf-8"))["schema_version"] == _CUR
                  for _d in _DAYS6) and _du._check_schema_migration(_b) is False)
        check("D6 no warning about leftovers, no error", _rec.m["warning"] == [] and _rec.m["error"] == [])
        _res6 = _snap.restore_snapshot(_zips[0])
        check("D6 the way back: restore puts the old summaries back byte for byte",
              _res6["ok"] and _res6["restored"] == 3
              and all((cfg.SUMMARY_DIR / f"garmin_{_d}.json").read_bytes() == _old[_d] for _d in _DAYS6)
              and _du._check_schema_migration(_b) is True)

summary()
