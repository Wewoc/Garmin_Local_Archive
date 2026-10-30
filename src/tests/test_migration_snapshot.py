#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_migration_snapshot.py — safety copy of the archive before the migration (v1.7.6.3)
TRACK-MIGRATION v1.7.6.3

Run from the project folder:
    python tests/test_migration_snapshot.py

Part M2a: Ist-Stand. Pins why the migration needs a copy of its own and what the way back can
rely on, before the module exists: the raw backup keeps only the newest version of a day, a
rewrite through write_day() cannot put back a stored summary byte for byte, and the quality log
passes unknown fields and the marks through load and save. All days are synthetic; shared setup
and helpers live in gla_testenv.py.
"""

import copy
import json
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_backup as backup
import garmin_backup_common as bcommon
import garmin_bulk_writer as bw
import garmin_quality as quality
import garmin_writer as writer

_D = "2022-03-04"
_OLD_RAW = {"date": _D, "heart_rates": {"restingHeartRate": 52, "minHeartRate": 44, "maxHeartRate": 150},
            "user_summary": {"totalSteps": 7000, "floorsAscended": 10},
            "stress": {"averageStressLevel": 28, "maxStressLevel": 90},
            "body_battery": [{"value": 40}]}
_NEW_RAW = {"date": _D, "heart_rates": {"calendarDate": _D, "restingHeartRate": 64, "minHeartRate": None,
                                        "maxHeartRate": None, "heartRateValues": None},
            "user_summary": {"totalSteps": 7000, "floorsAscended": 0.5},
            "body_battery": [{"value": 40}]}

section("M2a. Ist-Stand: the raw backup keeps only the newest version of a day")
with _isolated_log_env("m2a_backup") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    check("M2a the first write puts the day into the raw backup",
          writer.write_day(_OLD_RAW, {"date": _D}, _D) is True
          and bcommon.read_copy(backup._kind(), f"garmin_raw_{_D}.json") == (cfg.RAW_DIR / f"garmin_raw_{_D}.json").read_bytes())
    _old_bytes = (cfg.RAW_DIR / f"garmin_raw_{_D}.json").read_bytes()
    check("M2a the second write (the migration rewrites a day like this) replaces the copy in the backup: the old version is in no backup any more",
          writer.write_day(_NEW_RAW, {"date": _D}, _D) is True
          and bcommon.read_copy(backup._kind(), f"garmin_raw_{_D}.json") == (cfg.RAW_DIR / f"garmin_raw_{_D}.json").read_bytes()
          and bcommon.read_copy(backup._kind(), f"garmin_raw_{_D}.json") != _old_bytes)

section("M2a. Ist-Stand: write_day() makes the summary of a day with export data itself - it cannot put back a stored one")
with _isolated_log_env("m2a_resolve") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    assert bw.write_aggregates(_D, {"date": _D, "user_summary": {"totalSteps": 9000, "activeKilocalories": 223}},
                               ["ab" * 32]) == bw.WRITTEN
    _stored_summary = {"date": _D, "generated_by": "an earlier state", "marker": "the summary of the snapshot"}
    with patch.object(backup, "backup_raw"):
        writer.write_day(copy.deepcopy(_OLD_RAW), _stored_summary, _D)
    _written = json.loads((cfg.SUMMARY_DIR / f"garmin_{_D}.json").read_text(encoding="utf-8"))
    check("M2a a day with an aggregates file gets the resolved summary, not the one passed in - so a restore needs its own way to put bytes back",
          _written != _stored_summary and "marker" not in _written)

section("M2a. Ist-Stand: the quality log passes unknown fields and the marks through load and save; touch_last_checked marks days")
with _isolated_log_env("m2a_log") as _b:
    _entry = {"date": _D, "quality": "standard", "source": "api", "write": True, "recheck": False, "attempts": 0,
              "last_checked": "2024-01-01", "last_attempt": None, "fields": {"heart_rates": "medium"},
              "bulk": {"intraday": "2026-10-17", "aggregates": "2026-10-18"}, "somethingnew": [1, 2]}
    _put_log({"first_day": "2018-12-19", "devices": [], "days": [copy.deepcopy(_entry)]})
    with quality.QUALITY_LOCK:
        _data = quality._load_quality_log()
        quality.touch_last_checked(_data, [_D])
        _saved = quality._save_quality_log(_data)
    _after = {e["date"]: e for e in quality._load_quality_log()["days"]}[_D]
    check("M2a the log is saved (True) and the day keeps its bulk marks and an unknown field",
          _saved is True and _after["bulk"] == _entry["bulk"] and _after["somethingnew"] == [1, 2])
    check("M2a touch_last_checked sets last_checked of the day to today and leaves the rest of the entry alone",
          _after["last_checked"] != "2024-01-01" and _after["fields"] == _entry["fields"] and _after["quality"] == "standard")

# ══════════════════════════════════════════════════════════════════════════════
#  M2b. garmin_migration_snapshot — create, verify, list
# ══════════════════════════════════════════════════════════════════════════════
section("M2b. garmin_migration_snapshot - create_snapshot, verify_snapshot, list_snapshots")
import contextlib
import importlib.util
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

from gla_testenv import _cfg_values, _flip_byte, _qdays

import garmin_migration_snapshot as snap

_DAYS = ["2022-03-01", "2022-03-02", "2022-03-03"]


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _raw_bytes(d, tag="mixed"):
    return json.dumps({"date": d, "tag": tag, "stress": {"averageStressLevel": 28}}).encode("utf-8")


def _sum_bytes(d, tag="mixed"):
    return json.dumps({"date": d, "tag": tag, "stress": {"stress_avg": 28}}, indent=2).encode("utf-8")


def _entry(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False, "attempts": 0,
            "last_checked": "2024-01-01", "last_attempt": None, "fields": {"stress": "medium"}, "bulk": {"aggregates": "2026-10-18"}, **kw}


def _mk_archive(days=_DAYS, tag="mixed"):
    for d in days:
        _put(cfg.RAW_DIR / f"garmin_raw_{d}.json", _raw_bytes(d, tag))
        _put(cfg.SUMMARY_DIR / f"garmin_{d}.json", _sum_bytes(d, tag))
    _put_log({"first_day": "2018-12-19", "devices": [{"id": "1"}], "days": [_entry(d, tag=tag) for d in days]})


def _tree(base, skip=()):
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(Path(base).rglob("*"))
            if p.is_file() and not any(s in p.parts for s in skip)}


with _isolated_log_env("m2b_create") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        check("M2b a folder that does not exist: list_snapshots gives an empty list", snap.list_snapshots() == [])
        _e = snap.create_snapshot()
        check("M2b an archive without raw/, summary/ and log: ok, no ZIP, nothing created",
              _e["ok"] is True and _e["path"] is None and not (_b / "migration").exists())
        _mk_archive()
        _before = _tree(_b, skip=("migration",))
        _r = snap.create_snapshot()
        check("M2b create_snapshot: ok, a ZIP named migration_<date>_<time>.zip in backup/migration, counts and size",
              _r["ok"] is True and _r["path"].parent == _b / "migration" and snap._NAME_RE.fullmatch(_r["path"].name)
              and (_r["raw"], _r["summary"], _r["log"]) == (3, 3, True) and _r["bytes"] == _r["path"].stat().st_size > 0)
        with zipfile.ZipFile(_r["path"]) as _zf:
            _names = sorted(_zf.namelist())
            _man = json.loads(_zf.read("MANIFEST.json"))
            _same = all(_zf.read(f"raw/garmin_raw_{d}.json") == _raw_bytes(d) and _zf.read(f"summary/garmin_{d}.json") == _sum_bytes(d) for d in _DAYS)
            _log_in = json.loads(_zf.read("log/quality_log.json"))
        check("M2b the ZIP holds every raw file, every summary file, the quality log and a manifest - byte for byte",
              _names == sorted(["MANIFEST.json", "log/quality_log.json"] + [f"raw/garmin_raw_{d}.json" for d in _DAYS]
                               + [f"summary/garmin_{d}.json" for d in _DAYS]) and _same and len(_log_in["days"]) == 3)
        check("M2b the manifest names the counts and the program version",
              (_man["raw"], _man["summary"], _man["quality_log"]) == (3, 3, True) and isinstance(_man["app_version"], str) and _man["created"])
        check("M2b nothing in raw/, summary/ or the log is changed, no temp file is left",
              _tree(_b, skip=("migration",)) == _before and not list((_b / "migration").glob(".*")))
        _r2 = snap.create_snapshot()
        check("M2b a second call in the same second gets a name of its own (nothing is overwritten); the list shows both, oldest first",
              _r2["ok"] is True and _r2["path"] != _r["path"] and [s["name"] for s in snap.list_snapshots()] == sorted([_r["path"].name, _r2["path"].name]))
        _put(_b / "migration" / "readme.txt", "x")
        _put(_b / "migration" / ".migration_2026-01-01_000000.zip.tmp", "x")
        check("M2b list_snapshots ignores files that are no snapshot (temp files, other names)", len(snap.list_snapshots()) == 2)

        _v = snap.verify_snapshot(_r["path"])
        check("M2b verify_snapshot: a good snapshot is ok with its counts and creation time",
              _v["ok"] is True and (_v["raw"], _v["summary"], _v["log"]) == (3, 3, True) and _v["created"] == _man["created"])
        _bad = _b / "bad.zip"
        _flip_byte(_r["path"], _bad, 200)
        check("M2b verify_snapshot: a damaged ZIP is not ok", snap.verify_snapshot(_bad)["ok"] is False)
        _put(_b / "notzip.zip", "this is not a zip")
        check("M2b verify_snapshot: a file that is no ZIP is not ok, a missing file too",
              snap.verify_snapshot(_b / "notzip.zip")["ok"] is False and snap.verify_snapshot(_b / "nowhere.zip")["ok"] is False)
        _evil = _b / "evil.zip"
        with zipfile.ZipFile(_evil, "w") as _zf:
            _zf.writestr("MANIFEST.json", json.dumps({"raw": 0, "summary": 0, "quality_log": False}))
            _zf.writestr("../evil.json", "{}")
            _zf.writestr("raw/garmin_raw_2022-13-45.json", "{}")
        check("M2b verify_snapshot: entries outside the known names (path tricks, a date that is no date) are refused",
              snap.verify_snapshot(_evil)["ok"] is False
              and sorted(snap.verify_snapshot(_evil)["problems"]) == ["unexpected entry '../evil.json'",
                                                                       "unexpected entry 'raw/garmin_raw_2022-13-45.json'"])
        _short = _b / "short.zip"
        with zipfile.ZipFile(_short, "w") as _zf:
            _zf.writestr("MANIFEST.json", json.dumps({"raw": 2, "summary": 0, "quality_log": False}))
            _zf.writestr(f"raw/garmin_raw_{_DAYS[0]}.json", "{}")
        check("M2b verify_snapshot: a manifest that does not match the entries (a file lost) is refused",
              snap.verify_snapshot(_short)["ok"] is False and "manifest does not match" in snap.verify_snapshot(_short)["problems"][0])

with _isolated_log_env("m2b_fail") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        _before = _tree(_b)
        _real_rb = Path.read_bytes

        def _unreadable(self):
            if self.name == f"garmin_raw_{_DAYS[1]}.json":
                raise PermissionError("locked")
            return _real_rb(self)

        with patch.object(Path, "read_bytes", _unreadable):
            _f1 = snap.create_snapshot()
        check("M2b a file that cannot be read: not ok, the reason names the error, no ZIP and no temp file, the archive is untouched",
              _f1["ok"] is False and "PermissionError" in _f1["reason"] and snap.list_snapshots() == []
              and not list((_b / "migration").glob(".*")) and _tree(_b) == _before)
        with patch.object(snap.shutil, "disk_usage", return_value=SimpleNamespace(total=1000, used=999, free=1)):
            _f2 = snap.create_snapshot()
        check("M2b too little free space: not ok with the reason, no ZIP", _f2["ok"] is False and "free space" in _f2["reason"] and snap.list_snapshots() == [])
        _f3 = snap.create_snapshot(should_stop=lambda: True)
        check("M2b a stop request: not ok ('stopped'), no ZIP and no temp file", _f3["ok"] is False and _f3["reason"] == "stopped"
              and snap.list_snapshots() == [] and not list((_b / "migration").glob(".*")))
        with patch.object(snap, "_check_zip", return_value=["an entry differs"]):
            _f4 = snap.create_snapshot()
        check("M2b a ZIP that fails the read-back check is thrown away: not ok, no ZIP, no temp file",
              _f4["ok"] is False and "failed its check" in _f4["reason"] and snap.list_snapshots() == []
              and not list((_b / "migration").glob(".*")))
        _orig_ws = zipfile.ZipFile.writestr

        def _bad_writestr(self, name, data, *a, **k):
            if name == f"raw/garmin_raw_{_DAYS[1]}.json":
                data = b"altered on the way"          # a consistent CRC for wrong content: testzip alone would not see it
            return _orig_ws(self, name, data, *a, **k)

        with patch.object(zipfile.ZipFile, "writestr", _bad_writestr):
            _f6 = snap.create_snapshot()
        check("M2b an entry whose content is not what was read from the archive is found by the read-back check (not only damaged CRCs)",
              _f6["ok"] is False and "differs" in _f6["reason"] and snap.list_snapshots() == [] and not list((_b / "migration").glob(".*")))
        with patch.object(snap.os, "replace", side_effect=OSError("disk error")):
            _f5 = snap.create_snapshot()
        check("M2b an error while putting the ZIP in place: not ok, no ZIP and no temp file left",
              _f5["ok"] is False and "OSError" in _f5["reason"] and snap.list_snapshots() == [] and not list((_b / "migration").glob(".*")))
        check("M2b after all these failures a normal call still works", snap.create_snapshot()["ok"] is True)

# ══════════════════════════════════════════════════════════════════════════════
#  M2b. writer.restore_day_files and restore_snapshot - the way back
# ══════════════════════════════════════════════════════════════════════════════
section("M2b. garmin_writer.restore_day_files and garmin_migration_snapshot.restore_snapshot - the way back")

with _isolated_log_env("m2b_writer") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    _D = "2022-03-01"
    with patch.object(backup, "backup_raw") as _br:
        check("M2b restore_day_files: the exact bytes of both files are written (also bytes that are no JSON), the raw backup is triggered once",
              writer.restore_day_files(_D, b"\xff not json \x00", b"{ summary") is True
              and (cfg.RAW_DIR / f"garmin_raw_{_D}.json").read_bytes() == b"\xff not json \x00"
              and (cfg.SUMMARY_DIR / f"garmin_{_D}.json").read_bytes() == b"{ summary" and _br.call_count == 1)
    with patch.object(backup, "backup_raw") as _br:
        check("M2b restore_day_files: None leaves that file alone; a summary alone triggers no backup",
              writer.restore_day_files(_D, None, b"{ new summary") is True and (cfg.RAW_DIR / f"garmin_raw_{_D}.json").read_bytes() == b"\xff not json \x00"
              and (cfg.SUMMARY_DIR / f"garmin_{_D}.json").read_bytes() == b"{ new summary" and not _br.called)
    check("M2b restore_day_files: a date that is no date writes nothing and answers False",
          all(writer.restore_day_files(x, b"{}", b"{}") is False for x in ("../x", "2022-13-45", "", None))
          and sorted(p.name for p in cfg.RAW_DIR.iterdir()) == [f"garmin_raw_{_D}.json"])
    with patch.object(writer.os, "replace", side_effect=OSError("disk error")):
        check("M2b restore_day_files: a write error answers False and leaves no temp file",
              writer.restore_day_files("2022-03-05", b"{}", b"{}") is False and not list(cfg.RAW_DIR.glob("*.tmp")) and not list(cfg.SUMMARY_DIR.glob("*.tmp")))

with _isolated_log_env("m2b_restore") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        _log0 = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        _snap = snap.create_snapshot()["path"]
        # the "migration": day 1 rewritten (raw, summary, log entry), day 2 raw removed (converted), a new day 9 comes in
        _D1, _D2, _D3 = _DAYS
        _D9 = "2022-03-09"
        writer.restore_day_files(_D1, _raw_bytes(_D1, "migrated"), _sum_bytes(_D1, "migrated"))
        (cfg.RAW_DIR / f"garmin_raw_{_D2}.json").unlink()
        _put(cfg.RAW_DIR / f"garmin_raw_{_D9}.json", _raw_bytes(_D9, "new"))
        _put(cfg.SUMMARY_DIR / f"garmin_{_D9}.json", _sum_bytes(_D9, "new"))
        _put_log({"first_day": "2018-12-19", "devices": [{"id": "1"}, {"id": "2"}],
                  "days": [_entry(_D1, tag="migrated", last_checked="2025-12-31"), _entry(_D2, tag="converted", write=False, source="bulk"),
                           _entry(_D3, tag="mixed", last_checked="2025-05-05"), _entry(_D9, tag="new"), {"x": "an entry without a date"}]})
        _cur = _tree(_b, skip=("migration",))

        _d = snap.restore_snapshot(_snap, dry_run=True)
        check("M2b restore dry run: counts the days that would be put back (day 1 changed, day 2 missing; day 3 is the same), writes nothing",
              _d["ok"] is True and (_d["restored"], _d["unchanged"]) == (2, 1) and _tree(_b, skip=("migration",)) == _cur)

        with patch.object(backup, "backup_raw") as _brr:
            _res = snap.restore_snapshot(_snap)
        _r1 = (cfg.RAW_DIR / f"garmin_raw_{_D1}.json").read_bytes()
        check("M2b restore: ok, two days put back, one unchanged, the log saved, nothing failed",
              _res["ok"] is True and (_res["restored"], _res["unchanged"], _res["failed"], _res["log_saved"]) == (2, 1, [], True))
        check("M2b restore: raw and summary of the changed day are the snapshot's bytes again, the removed raw file is back",
              _r1 == _raw_bytes(_D1) and (cfg.SUMMARY_DIR / f"garmin_{_D1}.json").read_bytes() == _sum_bytes(_D1)
              and (cfg.RAW_DIR / f"garmin_raw_{_D2}.json").read_bytes() == _raw_bytes(_D2))
        check("M2b restore: the raw backup is triggered for both restored raw files (it follows the restored version)", _brr.call_count == 2)
        check("M2b restore: a day that is not in the snapshot (a day that came in later) is left as it is",
              (cfg.RAW_DIR / f"garmin_raw_{_D9}.json").read_bytes() == _raw_bytes(_D9, "new") and (cfg.SUMMARY_DIR / f"garmin_{_D9}.json").exists())
        _q = _qdays()
        _logf = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        check("M2b restore: the log entries of the restored days come back from the snapshot (day 1 tag mixed, day 2 write true, source api); last_checked is new",
              _q[_D1]["tag"] == "mixed" and _q[_D2]["write"] is True and _q[_D2]["source"] == "api"
              and _q[_D1]["last_checked"] != "2025-12-31" and _q[_D1]["last_checked"] == _q[_D2]["last_checked"] != "2024-01-01")
        check("M2b restore: the entry of the unchanged day and of the later day stay, devices and first_day stay, an entry without a date stays",
              _q[_D3]["last_checked"] == "2025-05-05" and _q[_D9]["tag"] == "new" and _logf["devices"] == [{"id": "1"}, {"id": "2"}]
              and _logf["first_day"] == "2018-12-19" and any(e.get("x") == "an entry without a date" for e in _logf["days"]))
        check("M2b restore: the bulk marks of the restored entries are those of the snapshot", _q[_D1]["bulk"] == _log0["days"][0]["bulk"])
        with patch.object(backup, "backup_raw"):
            _res2 = snap.restore_snapshot(_snap)
        check("M2b restore twice: the second time everything is unchanged and nothing is restored (idempotent)",
              (_res2["restored"], _res2["unchanged"], _res2["ok"]) == (0, 3, True))

        # a refused snapshot changes nothing
        _cur2 = _tree(_b, skip=("migration",))
        _bad = _b / "migration" / "migration_2026-01-01_000000.zip"
        _flip_byte(_snap, _bad, 300)
        _rb = snap.restore_snapshot(_bad)
        check("M2b restore of a damaged snapshot: refused ('snapshot_invalid', with the problems), nothing changed",
              _rb["ok"] is False and _rb["reason"] == "snapshot_invalid" and _rb["problems"] and _tree(_b, skip=("migration",)) == _cur2)
        check("M2b restore of a file that does not exist: refused", snap.restore_snapshot(_b / "nowhere.zip")["reason"] == "snapshot_invalid")

with _isolated_log_env("m2b_restore_fail") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        _snap = snap.create_snapshot()["path"]
        _D1, _D2, _D3 = _DAYS
        for _d in (_D1, _D2):
            writer.restore_day_files(_d, _raw_bytes(_d, "migrated"), _sum_bytes(_d, "migrated"))
        _put_log({"first_day": "2018-12-19", "devices": [], "days": [_entry(_d, tag="migrated") for _d in _DAYS]})

        _real_restore = writer.restore_day_files

        def _fail_d1(d, raw_b=None, sum_b=None):
            return False if d == _D1 else _real_restore(d, raw_b, sum_b)

        with patch.object(writer, "restore_day_files", _fail_d1), patch.object(backup, "backup_raw"):
            _rf = snap.restore_snapshot(_snap)
        check("M2b restore with one day that cannot be written: not ok, the day is named, the other day is put back",
              _rf["ok"] is False and [d for d, _ in _rf["failed"]] == [_D1] and _rf["restored"] == 1
              and (cfg.RAW_DIR / f"garmin_raw_{_D2}.json").read_bytes() == _raw_bytes(_D2))
        check("M2b restore: the log entry of the failed day stays as it is (migrated), the restored day's entry comes back",
              _qdays()[_D1]["tag"] == "migrated" and _qdays()[_D2]["tag"] == "mixed")
        with patch.object(backup, "backup_raw"):
            _rs = snap.restore_snapshot(_snap, should_stop=lambda: True)
        check("M2b restore with a stop request: nothing is put back, 'stopped' is set, not ok", _rs["stopped"] is True and _rs["ok"] is False and _rs["restored"] == 0)
        with patch.object(backup, "backup_raw"):
            _rr = snap.restore_snapshot(_snap)
        check("M2b a restore that was interrupted or failed can simply be run again: the rest is put back",
              _rr["ok"] is True and _rr["restored"] == 1 and _qdays()[_D1]["tag"] == "mixed")

# ── the command line tool ───────────────────────────────────────────────────────────
section("M2b. support-tools/archive-maintenance/restore_migration_snapshot.py")
_cli_path = Path(__file__).parent.parent / "support-tools" / "archive-maintenance" / "restore_migration_snapshot.py"
_spec = importlib.util.spec_from_file_location("restore_migration_snapshot_under_test", _cli_path)
_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cli)


def _run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = _cli.main(list(argv))
    return code, buf.getvalue()


with _isolated_log_env("m2b_cli") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _code, _out = _run_cli("--list")
        check("M2b CLI --list without copies: says so, exit 0", _code == 0 and "No copies" in _out)
        _mk_archive()
        _snap = snap.create_snapshot()["path"]
        writer.restore_day_files(_DAYS[0], _raw_bytes(_DAYS[0], "migrated"), _sum_bytes(_DAYS[0], "migrated"))
        _code, _out = _run_cli("--list")
        check("M2b CLI --list: names the copy with its counts and its state", _code == 0 and _snap.name in _out and "3 raw, 3 summary" in _out and "[ok]" in _out)
        _cur = _tree(_b, skip=("migration",))
        _code, _out = _run_cli(_snap.name, "--dry-run")
        check("M2b CLI --dry-run: counts what would be put back, exit 0, writes nothing",
              _code == 0 and "[DRY RUN]" in _out and "1 day(s) would be put back" in _out and _tree(_b, skip=("migration",)) == _cur)
        with patch.object(backup, "backup_raw"):
            _code, _out = _run_cli(_snap.name)
        check("M2b CLI restore by name: puts the day back, exit 0", _code == 0 and "1 day(s) put back" in _out
              and (cfg.RAW_DIR / f"garmin_raw_{_DAYS[0]}.json").read_bytes() == _raw_bytes(_DAYS[0]))
        check("M2b CLI: an unknown name gives an error and exit 1", _run_cli("nowhere.zip")[0] == 1)
        _flip_byte(_snap, _b / "migration" / "migration_2026-01-01_000000.zip", 300)
        _code, _out = _run_cli("migration_2026-01-01_000000.zip")
        check("M2b CLI: a damaged copy is refused with the problems and exit 1", _code == 1 and "refused" in _out)

summary()
