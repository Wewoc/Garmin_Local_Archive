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

# ══════════════════════════════════════════════════════════════════════════════
#  M2c. Mutation round v1.7.6.12 — survivors of the Cosmic Ray run
# ══════════════════════════════════════════════════════════════════════════════
section("M2c. garmin_migration_snapshot - mutation round v1.7.6.12")
import datetime as _dt
import os as _os
import zlib as _zlib

_R = snap._FREE_SPACE_RESERVE
check("M2c the free-space reserve is 10 MB", _R == 10 * 1024 * 1024)
check("M2c _valid_date: a date -> True; the basic ISO form 20220304 (8 characters), text and None -> False",
      snap._valid_date("2022-03-01") is True and snap._valid_date("20220304") is False
      and snap._valid_date("abc") is False and snap._valid_date(None) is False)


def _zip_of(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as _z:
        for _n, _c in entries.items():
            _z.writestr(_n, _c)
    return path


_DR1, _DR2, _DS1 = "raw/garmin_raw_2022-03-01.json", "raw/garmin_raw_2022-03-02.json", "summary/garmin_2022-03-01.json"

# -- _cleanup never raises ------------------------------------------------------------------------------------------
with _isolated_log_env("m2c_cleanup") as _b:
    _p = _b / "x.tmp"
    _p.write_text("x", encoding="utf-8")
    snap._cleanup(_p)
    snap._cleanup(_b / "missing.tmp")
    _p2 = _b / "y.tmp"
    _p2.write_text("y", encoding="utf-8")
    with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        snap._cleanup(_p2)
    check("M2c _cleanup: removes a file, ignores a missing one and an OS error", not _p.exists() and _p2.exists())

# -- create_snapshot: refused store names, nothing to back up, free space, names, manifest, log line --------------------------
with _isolated_log_env("m2c_create") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        for _st in (("bogus",), ()):
            _r = snap.create_snapshot(stores=_st)
            check(f"M2c create_snapshot(stores={_st!r}): refused, every number zero, nothing written",
                  _r == {"ok": False, "path": None, "raw": 0, "summary": 0, "log": False, "bytes": 0,
                         "reason": f"unknown store in {sorted(map(str, set(_st)))}"} and not (_b / "migration").exists())
        check("M2c an archive with nothing to back up: ok, path None, every number zero",
              snap.create_snapshot() == {"ok": True, "path": None, "raw": 0, "summary": 0, "log": False, "bytes": 0,
                                         "reason": "nothing to back up"})

        for _size, _free, _txt in ((3 * 1048576, 5 * 1048576, "5 MB free, 3 MB of files to back up"),
                                   (3 * 1048575, 5 * 1048575, "4 MB free, 2 MB of files to back up")):
            _put(cfg.RAW_DIR / "garmin_raw_2022-03-01.json", b"x" * _size)
            with patch("shutil.disk_usage", return_value=SimpleNamespace(total=_free * 2, used=0, free=_free)):
                _r = snap.create_snapshot()
            check(f"M2c not enough free space: refused with the sizes in whole megabytes ({_txt})",
                  _r["ok"] is False and _r["path"] is None and _r["reason"] == f"not enough free space ({_txt})"
                  and (_r["raw"], _r["summary"], _r["log"], _r["bytes"]) == (1, 0, False, 0))
        _tot = 3 * 1048576 + 456
        _put(cfg.RAW_DIR / "garmin_raw_2022-03-01.json", b"x" * _tot)
        with patch("shutil.disk_usage", return_value=SimpleNamespace(total=0, used=0, free=_tot + _R - 1)):
            _just_short = snap.create_snapshot()
        with patch("shutil.disk_usage", return_value=SimpleNamespace(total=0, used=0, free=_tot + _R)):
            _just_enough = snap.create_snapshot()
        check("M2c free space exactly the size of the files plus the 10 MB reserve is enough, one byte less is not",
              _just_short["ok"] is False and "not enough free space" in _just_short["reason"]
              and _just_enough["ok"] is True and _just_enough["path"].exists())

with _isolated_log_env("m2c_names") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        with patch.object(snap, "datetime") as _dtm:
            _dtm.now.return_value = _dt.datetime(2025, 1, 2, 3, 4, 5)
            _names9 = [snap.create_snapshot()["path"].name for _ in range(3)]
        check("M2c three snapshots in the same second are named _, _2 and _3",
              _names9 == ["migration_2025-01-02_030405.zip", "migration_2025-01-02_030405_2.zip", "migration_2025-01-02_030405_3.zip"])
        with zipfile.ZipFile(snap.list_snapshots()[0]["path"]) as _zf:
            _mtext = _zf.read("MANIFEST.json").decode("utf-8")
        check("M2c the manifest is written with an indent of two", _mtext.startswith('{\n  "created"'))
        with patch.object(snap, "_check_zip", return_value=["p1", "p2", "p3", "p4", "p5"]):
            _fz = snap.create_snapshot()
        check("M2c a ZIP that fails its check: the first three problems are named, no file is kept",
              _fz["ok"] is False and _fz["reason"] == "the ZIP failed its check: p1; p2; p3"
              and len(snap.list_snapshots()) == 3 and not list((_b / "migration").glob(".*")))

with _isolated_log_env("m2c_logline") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        _put(cfg.RAW_DIR / "garmin_raw_2022-03-09.json", _os.urandom(2_621_440))          # incompressible: the ZIP is about 2.5 MB
        with patch.object(snap, "log") as _lg:
            _w = snap.create_snapshot()
            _wo = snap.create_snapshot(stores=("raw", "summary"))
        _msgs = [str(c.args[0]) for c in _lg.info.call_args_list]
        check("M2c the log line names the ZIP, the counts, the quality log when it is in, and the size in MB",
              _msgs[0] == f"  Migration snapshot: {_w['path'].name} — 4 raw, 3 summary file(s), quality log, {_w['bytes'] // 1048576} MB"
              and _w["bytes"] // 1048576 == 2)
        check("M2c without the quality log the line does not mention it",
              _msgs[1] == f"  Migration snapshot: {_wo['path'].name} — 4 raw, 3 summary file(s), {_wo['bytes'] // 1048576} MB")

# -- _check_zip and verify_snapshot -----------------------------------------------------------------------------------
with _isolated_log_env("m2c_check") as _b:
    _data = b'{"date": "2022-03-01"}'
    _crc = _zlib.crc32(_data)
    _zp = _zip_of(_b / "e.zip", {"MANIFEST.json": "{}", _DR1: _data})
    check("M2c _check_zip with the entries that were read: no problem",
          snap._check_zip(_zp, {_DR1: (len(_data), _crc)}) == [])
    check("M2c _check_zip: an expected entry that is not in the ZIP -> 'the entries differ'",
          snap._check_zip(_zp, {_DR1: (len(_data), _crc), _DR2: (1, 1)}) == ["the entries differ from the files that were read"])
    check("M2c _check_zip: an entry in the ZIP that was not expected -> 'the entries differ'",
          snap._check_zip(_zp, {}) == ["the entries differ from the files that were read"])
    for _what, _exp in (("size larger", (len(_data) + 1, _crc)), ("size smaller", (len(_data) - 1, _crc)),
                        ("crc larger", (len(_data), _crc + 1)), ("crc smaller", (len(_data), _crc - 1))):
        check(f"M2c _check_zip: the expected {_what} than the entry -> the entry differs",
              snap._check_zip(_zp, {_DR1: _exp}) == [f"{_DR1} differs from the file that was read"])

    def _man9(raw, summ, log, extra=None):
        return json.dumps({"raw": raw, "summary": summ, "quality_log": log, **(extra or {})})

    _ents = {_DR1: "{}", _DR2: "{}", _DS1: "{}", "log/quality_log.json": "{}"}
    check("M2c _check_zip without expected entries: a manifest that matches (2 raw, 1 summary, a log) is fine",
          snap._check_zip(_zip_of(_b / "m_ok.zip", {"MANIFEST.json": _man9(2, 1, True), **_ents})) == [])
    for _what, _m in (("raw too high", _man9(3, 1, True)), ("raw too low", _man9(1, 1, True)),
                      ("summary too high", _man9(2, 2, True)), ("summary too low", _man9(2, 0, True)),
                      ("a log claimed that is not there", _man9(2, 1, True)), ("a log not claimed that is there", _man9(2, 1, False))):
        _e2 = dict(_ents)
        if _what.startswith("a log claimed"):
            del _e2["log/quality_log.json"]
        _p9 = snap._check_zip(_zip_of(_b / "m_bad.zip", {"MANIFEST.json": _m, **_e2}))
        check(f"M2c _check_zip: manifest {_what} -> 'the manifest does not match the entries'",
              _p9 == ["the manifest does not match the entries"])
    for _txt, _what in (("{ not json", "no JSON"), ("[]", "a list"), ("null", "null")):
        check(f"M2c _check_zip: a manifest that is {_what} -> 'manifest unreadable'",
              snap._check_zip(_zip_of(_b / "m_un.zip", {"MANIFEST.json": _txt, _DR1: "{}"})) == ["manifest unreadable"])

    _v = snap.verify_snapshot(_zip_of(_b / "v.zip", {
        "MANIFEST.json": _man9(3, 2, False, {"created": "2025-01-01T00:00:00"}),
        **{f"raw/garmin_raw_2022-03-0{n}.json": "{}" for n in (1, 2, 3)},
        **{f"summary/garmin_2022-03-0{n}.json": "{}" for n in (1, 2)}}))
    check("M2c verify_snapshot counts raw and summary entries apart (3 and 2), reads the creation time, log False",
          _v == {"ok": True, "problems": [], "raw": 3, "summary": 2, "log": False, "created": "2025-01-01T00:00:00"})
    (_b / "garbage.zip").write_bytes(b"not a zip at all")
    _vg = snap.verify_snapshot(_b / "garbage.zip")
    check("M2c verify_snapshot of a file that is no ZIP: not ok, one problem, every number zero, no creation time",
          _vg["ok"] is False and len(_vg["problems"]) == 1 and (_vg["raw"], _vg["summary"], _vg["log"], _vg["created"]) == (0, 0, False, None))
    for _txt in ("{ not json", "[]"):
        _vm = snap.verify_snapshot(_zip_of(_b / "v_bad.zip", {"MANIFEST.json": _txt, _DR1: "{}"}))
        check(f"M2c verify_snapshot with a manifest that is {_txt!r}: not ok, nothing raised, the entries are counted, no creation time",
              _vm["ok"] is False and _vm["raw"] == 1 and _vm["created"] is None)
    _real_zf = zipfile.ZipFile
    for _exc in (OSError("gone"), zipfile.BadZipFile("gone")):
        _n9 = [0]

        def _second_fails(*a, **k):
            _n9[0] += 1
            if _n9[0] == 2:
                raise _exc
            return _real_zf(*a, **k)

        with patch.object(zipfile, "ZipFile", _second_fails):
            _vs = snap.verify_snapshot(_b / "v.zip")
        check(f"M2c verify_snapshot: the ZIP cannot be opened the second time ({type(_exc).__name__}): not raised, counts stay zero",
              _vs["ok"] is True and (_vs["raw"], _vs["summary"], _vs["created"]) == (0, 0, None))

# -- restore_snapshot -------------------------------------------------------------------------------------------------------
with _isolated_log_env("m2c_restore") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _ds = ["2022-03-01", "2022-03-02", "2022-03-03", "2022-03-04"]
        _mk_archive(_ds)
        _sp = snap.create_snapshot()["path"]
        _rj = snap.restore_snapshot(_b / "garbage.zip")
        check("M2c restore_snapshot of a refused ZIP: every counter zero, nothing failed, log_saved None, not stopped",
              _rj["reason"] == "snapshot_invalid" and (_rj["restored"], _rj["unchanged"], _rj["log_entries"]) == (0, 0, 0)
              and _rj["failed"] == [] and _rj["log_saved"] is None and _rj["stopped"] is False and _rj["ok"] is False)

        # everything is as it was in the snapshot: nothing is put back and the log is not touched
        _log_before = cfg.QUALITY_LOG_FILE.read_bytes()
        with patch.object(backup, "backup_raw"):
            _same = snap.restore_snapshot(_sp)
        check("M2c restore of an unchanged archive: 4 unchanged, 0 restored, the log is not saved (log_saved None) and not changed",
              (_same["restored"], _same["unchanged"], _same["log_entries"], _same["log_saved"], _same["ok"]) == (0, 4, 0, None, True)
              and cfg.QUALITY_LOG_FILE.read_bytes() == _log_before)

        for _d in _ds:
            writer.restore_day_files(_d, _raw_bytes(_d, "migrated"), _sum_bytes(_d, "migrated"))
        _asked = []
        with patch.object(backup, "backup_raw"):
            _once = snap.restore_snapshot(_sp, should_stop=lambda: (_asked.append(1) or len(_asked) == 2))
        check("M2c a stop at the second day ends the restore there: one day put back, the others (also those after it) are not",
              _once["stopped"] is True and _once["restored"] == 1 and len(_asked) == 2
              and (cfg.RAW_DIR / "garmin_raw_2022-03-01.json").read_bytes() == _raw_bytes("2022-03-01")
              and all((cfg.RAW_DIR / f"garmin_raw_{d}.json").read_bytes() == _raw_bytes(d, "migrated") for d in _ds[1:]))

        _real_zf = zipfile.ZipFile
        for _exc in (OSError("gone"), zipfile.BadZipFile("gone")):
            _n9 = [0]

            def _third_fails(*a, **k):
                _n9[0] += 1
                if _n9[0] == 3:
                    raise _exc
                return _real_zf(*a, **k)

            with patch.object(zipfile, "ZipFile", _third_fails):
                _un = snap.restore_snapshot(_sp)
            check(f"M2c a ZIP that cannot be opened for the restore ({type(_exc).__name__}): the reason carries the error, not ok",
                  _un["ok"] is False and _un["reason"] == f"{type(_exc).__name__}: gone")

with _isolated_log_env("m2c_nolog") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        cfg.QUALITY_LOG_FILE.unlink()
        _sp = snap.create_snapshot()["path"]
        writer.restore_day_files(_DAYS[0], _raw_bytes(_DAYS[0], "migrated"), _sum_bytes(_DAYS[0], "migrated"))
        with patch.object(backup, "backup_raw"):
            _nl = snap.restore_snapshot(_sp)
        check("M2c a snapshot without a log entry: the day is put back, nothing is read from a log that is not there "
              "(no entry comes back, the marks are still saved)",
              _nl["ok"] is True and _nl["restored"] == 1 and _nl["log_entries"] == 0 and _nl["log_saved"] is True)

with _isolated_log_env("m2c_badlog") as _b:
    _bad_log = _zip_of(_b / "badlog.zip", {"MANIFEST.json": json.dumps({"raw": 0, "summary": 0, "quality_log": True}),
                                           "log/quality_log.json": "{ not json"})
    _bl = snap.restore_snapshot(_bad_log)
    check("M2c a copy whose log is not JSON: not ok, the failure names the log, nothing raised",
          _bl["ok"] is False and _bl["failed"] == [("quality_log", "the log in the snapshot is unreadable")])

with _isolated_log_env("m2c_logonly") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "migration"):
        _mk_archive()
        with quality.QUALITY_LOCK:                              # the log as the program itself writes it (entries normalised)
            quality._save_quality_log(quality._load_quality_log(), skip_backup=True)
        _lp = snap.create_snapshot(stores=("quality_log",))["path"]
        _base_log = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        with patch.object(snap, "log") as _lg:
            _r0 = snap.restore_snapshot(_lp)
            _msg0 = str(_lg.info.call_args_list[-1].args[0])
        check("M2c log-only copy, nothing changed since: 0 entries, the line says 'entries'",
              _r0["log_entries"] == 0 and _msg0.endswith("0 log entries restored") and "(dry run)" not in _msg0)
        _chg = json.loads(json.dumps(_base_log))
        _chg["days"][0]["tag"] = "later"
        _put_log(_chg)
        with patch.object(snap, "log") as _lg:
            _rd = snap.restore_snapshot(_lp, dry_run=True)
            _msgd = str(_lg.info.call_args_list[-1].args[0])
        check("M2c log-only copy, dry run: counts the entry that would come back, writes nothing, the line says '(dry run)' and 'entry'",
              _rd["log_entries"] == 1 and "(dry run)" in _msgd and _msgd.endswith("1 log entry restored")
              and json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))["days"][0]["tag"] == "later")
        with patch.object(snap, "log") as _lg:
            _r1 = snap.restore_snapshot(_lp)
            _msg1 = str(_lg.info.call_args_list[-1].args[0])
        check("M2c log-only copy, one entry back: the line says '1 log entry restored'", _r1["log_entries"] == 1 and _msg1.endswith("1 log entry restored"))
        _chg["days"][0]["tag"] = "later"
        _chg["days"][1]["tag"] = "later"
        _put_log(_chg)
        with patch.object(snap, "log") as _lg:
            _r2 = snap.restore_snapshot(_lp)
            _msg2 = str(_lg.info.call_args_list[-1].args[0])
        check("M2c log-only copy, two entries back: the line says '2 log entries restored'", _r2["log_entries"] == 2 and _msg2.endswith("2 log entries restored"))

# -- _restore_log_entries and _merge_log on their own ---------------------------------------------------------------------
with _isolated_log_env("m2c_entries") as _b:
    _put_log({"first_day": "2018-12-19", "devices": [], "days": [_entry("2022-03-01", tag="current"), _entry("2022-03-02", tag="same")]})
    _cur = quality._load_quality_log()["days"]
    _same_e = copy.deepcopy(_cur[1])
    _old_e, _new_e = copy.deepcopy(_cur[0]), _entry("2022-03-05", tag="new")
    _old_e["tag"] = "old"
    _snap_log = {"days": ["junk", {"no": "date"}, {"date": 20220301}, _same_e, _old_e, _new_e]}
    _file_before = cfg.QUALITY_LOG_FILE.read_bytes()
    check("M2c _restore_log_entries, dry run: counts the entry that differs and the one that is new, saves nothing (None), the file is as before",
          snap._restore_log_entries(_snap_log, True) == (2, None) and cfg.QUALITY_LOG_FILE.read_bytes() == _file_before)
    check("M2c _restore_log_entries: nothing differs -> (0, None) and the file is not rewritten",
          snap._restore_log_entries({"days": [_same_e]}, False) == (0, None) and cfg.QUALITY_LOG_FILE.read_bytes() == _file_before)
    check("M2c _restore_log_entries: junk entries in front do not end the loop; the differing day is replaced, the new day appended, the same day stays",
          snap._restore_log_entries(_snap_log, False) == (2, True)
          and {d: e["tag"] for d, e in _qdays().items()} == {"2022-03-01": "old", "2022-03-02": "same", "2022-03-05": "new"})
    for _ret, _want in ((0, True), (None, True), (False, False)):
        _put_log({"first_day": "2018-12-19", "devices": [], "days": [_entry("2022-03-01", tag="current")]})
        with patch.object(quality, "_save_quality_log", return_value=_ret):
            _got = snap._restore_log_entries({"days": [_old_e]}, False)
        check(f"M2c _restore_log_entries: a save that answers {_ret!r} counts as saved={_want}", _got == (1, _want))

    _put_log({"first_day": "2018-12-19", "devices": [], "days": [_entry("2022-03-01", tag="a"), _entry("2022-03-02", tag="b"),
                                                                  {"x": "no date"}]})
    check("M2c _merge_log: no log in the snapshot -> nothing taken (0), saved True",
          snap._merge_log(None, {"2022-03-01"}) == (0, True))
    _slog = {"days": [_entry("2022-03-01", tag="from-snap"), _entry("2022-03-02", tag="from-snap"), _entry("2022-03-09", tag="not restored")]}
    check("M2c _merge_log: two restored days are taken from the snapshot's log (2), a day that was not restored is not",
          snap._merge_log(_slog, {"2022-03-01", "2022-03-02"}) == (2, True)
          and {d: e["tag"] for d, e in _qdays().items()} == {"2022-03-01": "from-snap", "2022-03-02": "from-snap"})
    for _ret, _want in ((0, True), (None, True), (False, False)):
        with patch.object(quality, "_save_quality_log", return_value=_ret):
            _got = snap._merge_log(_slog, {"2022-03-01"})
        check(f"M2c _merge_log: a save that answers {_ret!r} counts as saved={_want}", _got == (1, _want))

# -- the name of a log-only copy, a backup folder whose parents do not exist, restore failures through restore_snapshot ------------
with _isolated_log_env("m2c_more") as _b:
    cfg.SUMMARY_DIR = _b / "summary"
    with _cfg_values(MIGRATION_BACKUP_DIR=_b / "no" / "such" / "folders" / "migration"):
        _mk_archive()
        with quality.QUALITY_LOCK:
            quality._save_quality_log(quality._load_quality_log(), skip_backup=True)
        _lo = snap.create_snapshot(stores=("quality_log",))
        _full = snap.create_snapshot()
        check("M2c a copy of the quality log only is named quality_log_..., the full one migration_...; the backup folder is made with its parents",
              _lo["ok"] is True and _lo["path"].name.startswith("quality_log_") and _full["ok"] is True
              and _full["path"].name.startswith("migration_") and _full["path"].parent == _b / "no" / "such" / "folders" / "migration")
        _lp = _lo["path"]
        _base_log = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        _chg = json.loads(json.dumps(_base_log))
        _chg["days"][0]["tag"] = "later"
        _put_log(_chg)
        with patch.object(quality, "_save_quality_log", return_value=False):
            _lf = snap.restore_snapshot(_lp)
        check("M2c a log-only restore whose save fails: the failure names the quality log, not ok, log_saved False",
              _lf["log_saved"] is False and _lf["ok"] is False and _lf["failed"] == [("quality_log", "the quality log could not be saved")])
        _put_log(_chg)
        _ls = snap.restore_snapshot(_lp)
        check("M2c a log-only restore whose save works: no failure, ok, log_saved True",
              _ls["log_saved"] is True and _ls["ok"] is True and _ls["failed"] == [])
        _sp = _full["path"]
        writer.restore_day_files(_DAYS[0], _raw_bytes(_DAYS[0], "migrated"), _sum_bytes(_DAYS[0], "migrated"))
        with patch.object(backup, "backup_raw"), patch.object(quality, "_save_quality_log", return_value=False):
            _mf = snap.restore_snapshot(_sp)
        check("M2c a restore of days whose log save fails: the failure names the quality log, not ok",
              _mf["log_saved"] is False and _mf["ok"] is False and ("quality_log", "the quality log could not be saved") in _mf["failed"])
        writer.restore_day_files(_DAYS[0], _raw_bytes(_DAYS[0], "migrated"), _sum_bytes(_DAYS[0], "migrated"))
        with patch.object(backup, "backup_raw"):
            _mo = snap.restore_snapshot(_sp)
        check("M2c a restore of days whose log save works: no failure", _mo["log_saved"] is True and _mo["ok"] is True and _mo["failed"] == [])

# -- the entries of the CURRENT log that are no entries (a string, a dict with a date that is no string) are left alone ------------------
with _isolated_log_env("m2c_junk") as _b:
    _cur_data = {"first_day": "2018-12-19", "devices": [], "days": ["junk", {"date": 5}, _entry("2022-03-01", tag="current")]}
    with patch.object(quality, "_load_quality_log", return_value=_cur_data), patch.object(quality, "_save_quality_log", return_value=True):
        _res = snap._restore_log_entries({"days": [_entry("2022-03-01", tag="old")]}, False)
    check("M2c _restore_log_entries: junk entries in the current log do not stop it; the day is replaced, the junk stays",
          _res == (1, True) and _cur_data["days"][0] == "junk" and _cur_data["days"][1] == {"date": 5}
          and _cur_data["days"][2]["tag"] == "old" and len(_cur_data["days"]) == 3)

summary()
