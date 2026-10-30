#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_repair_devices.py — garmin_repair_devices and what it stands on
DEVICE-REPAIR v1.7.6.9 — removable (see the module's removal list).

Covers: find_candidates / repair_devices (synthetic FIT originals and bulk day files), the quality
functions record_device_from_files / set_device_name and the device_source rule in _upsert_quality,
create_snapshot(stores=...) with the way back of a log-only copy, the mirror import passing
device_source on, the scheduler hint and the controller function behind "naming by id".

Run from the project folder:
    python tests/test_repair_devices.py

All data is synthetic; shared setup lives in gla_testenv.py, FIT bytes come from fit_builder.py.
"""

import copy
import hashlib
import importlib.util
import json
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _cfg_values, _isolated_log_env, _put_log  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
import fit_builder as fb

import garmin_bulk_writer as bw
import garmin_migration_snapshot as snap
import garmin_quality as quality

section("D. garmin_repair_devices (v1.7.6.9)")
import garmin_repair_devices as rd

_TODAY = date.today().isoformat()
_T0 = 1_700_000_000


class _Rec:
    """Stand-in for a module logger — keeps the messages per level."""
    def __init__(self):
        self.m = {"debug": [], "info": [], "warning": [], "error": []}

    def debug(self, s, *a, **k):
        self.m["debug"].append(s)

    def info(self, s, *a, **k):
        self.m["info"].append(s)

    def warning(self, s, *a, **k):
        self.m["warning"].append(s)

    def error(self, s, *a, **k):
        self.m["error"].append(s)


def _qe(d, **kw):
    return {"date": d, "quality": "standard", "source": "api", "write": True, "recheck": False,
            "attempts": 0, "last_checked": "2024-01-01", "last_attempt": None,
            "fields": {"heart_rates": "medium"}, "device_id": None, "device_name": "", **kw}


def _fit_original(base, serial, tag=0):
    """Writes a FIT original (file_id with this serial) into bulk/source and returns its SHA-256."""
    data = fb.simple_fit(32, _T0 + tag, serial=serial)
    h = hashlib.sha256(data).hexdigest()
    p = base / "bulk" / "source" / h[:2] / f"{h}.fit"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return h


def _day_file(base, d, hashes):
    p = base / "bulk" / "raw" / f"garmin_bulk_{d}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"date": d, "schema_version": 1, "source_files": sorted(hashes)}), encoding="utf-8")


def _log(*entries):
    return {"first_day": "2025-06-01", "devices": [], "days": list(entries)}


def _snap_dir(base):
    return base / "backup" / "migration"


def _zips(base):
    f = _snap_dir(base)
    return sorted(p.name for p in f.glob("*.zip")) if f.exists() else []


def _logbytes():
    return cfg.QUALITY_LOG_FILE.read_bytes()


def _no_lc(e):
    return {k: v for k, v in e.items() if k != "last_checked"}


# ══════════════════════════════════════════════════════════════════════════════
#  0. Ist-Stand — what is pinned before the change (stays true after it)
# ══════════════════════════════════════════════════════════════════════════════
section("D0. Ist-Stand: device_id handling that the repair builds on")
with _isolated_log_env("rd_ist") as _b:
    _d = date(2025, 6, 1)
    _data = _log(_qe("2025-06-01", device_id="111", device_name="Old"), _qe("2025-06-02"))
    quality._upsert_quality(_data, _d, "standard", "r", written=True, source="api")
    _e = _data["days"][0]
    check("D0 a call without a device_id leaves device_id and device_name of the entry alone",
          (_e["device_id"], _e["device_name"]) == ("111", "Old"))
    quality._upsert_quality(_data, _d, "standard", "r", written=True, source="api", device_id="222", device_name="New")
    check("D0 a call WITH a device_id replaces id and name (the account's own data wins)",
          (_e["device_id"], _e["device_name"]) == ("222", "New"))
    _put_log(_log(_qe("2025-06-01", device_id="111", device_source="export_fit", extra_unknown=[1])))
    with quality.QUALITY_LOCK:
        _l = quality._load_quality_log()
        quality._save_quality_log(_l)
    _e = quality._load_quality_log()["days"][0]
    check("D0 the log passes device_source and an unknown key through load and save",
          _e.get("device_source") == "export_fit" and _e.get("extra_unknown") == [1])
    _u = _log(_qe("2025-06-01", device_id="111", device_name="A"), _qe("2025-06-02"))
    quality.set_unknown_device_name(_u, "Unk")
    check("D0 set_unknown_device_name touches only entries without a device_id",
          (_u["days"][0]["device_name"], _u["days"][1]["device_name"]) == ("A", "Unk"))

# ══════════════════════════════════════════════════════════════════════════════
#  1. device_source rule in _upsert_quality / record_attempt
# ══════════════════════════════════════════════════════════════════════════════
section("D1. device_source belongs to the device_id of the same entry")
with _isolated_log_env("rd_src") as _b:
    _day = date(2025, 6, 1)
    _data = _log(_qe("2025-06-01", device_id="111", device_source="export_fit"))
    _e = _data["days"][0]
    quality._upsert_quality(_data, _day, "standard", "r", written=True, source="api")
    check("D1 a call without a device_id keeps device_id and device_source",
          (_e["device_id"], _e["device_source"]) == ("111", "export_fit"))
    quality._upsert_quality(_data, _day, "standard", "r", written=True, source="api", device_id="222", device_name="N")
    check("D1 an id from the account's data replaces the id and removes the stale device_source",
          _e["device_id"] == "222" and "device_source" not in _e)
    quality._upsert_quality(_data, _day, "standard", "r", written=True, source="api",
                            device_id="333", device_name="", device_source="export_fit")
    check("D1 a device_source passed together with the id is stored", (_e["device_id"], _e["device_source"]) == ("333", "export_fit"))
    _data = _log()
    quality._upsert_quality(_data, date(2025, 6, 5), "standard", "r", written=True, source="bulk",
                            device_id="444", device_source="export_fit")
    quality._upsert_quality(_data, date(2025, 6, 6), "standard", "r", written=True, source="api", device_id="555")
    quality._upsert_quality(_data, date(2025, 6, 7), "standard", "r", written=True, source="api")
    _by = {e["date"]: e for e in _data["days"]}
    check("D1 new entries: device_source only when given together with an id; no key otherwise",
          _by["2025-06-05"]["device_source"] == "export_fit" and "device_source" not in _by["2025-06-06"]
          and "device_source" not in _by["2025-06-07"] and _by["2025-06-07"]["device_id"] is None)
    _data = _log(_qe("2025-06-01", device_id="111", device_source="export_fit"))
    with patch("quality._io._save_quality_log") as _sv:
        quality.record_attempt(_data, _day, "standard", "r", written=True, source="api", device_id="999", device_name="X")
    check("D1 record_attempt hands the rule on (new id from the API: no device_source) and saves once",
          "device_source" not in _data["days"][0] and _sv.call_count == 1)
    with patch("quality._io._save_quality_log"):
        quality.record_attempt(_data, _day, "standard", "r", written=True, source="api",
                               device_id="998", device_source="export_fit")
    check("D1 record_attempt passes a device_source on", _data["days"][0]["device_source"] == "export_fit")

# ══════════════════════════════════════════════════════════════════════════════
#  2. quality.record_device_from_files / set_device_name
# ══════════════════════════════════════════════════════════════════════════════
section("D2. record_device_from_files and set_device_name")
_data = _log(_qe("2025-06-01"), _qe("2025-06-02", device_id="111", device_name="Keep"),
             _qe("2025-06-03", device_name="Unknown group name"), _qe("2025-06-04"))
_before = copy.deepcopy(_data)
_r = quality.record_device_from_files(
    _data, {"2025-06-01": 3966586101, "2025-06-02": "999", "2025-06-03": "222", "2025-06-04": "",
            "2025-06-09": "5", date(2025, 6, 1): "3966586101"}, "export_fit")
_by = {e["date"]: e for e in _data["days"]}
check("D2 assigned: the id as text, device_source set, name empty; the entry otherwise untouched (last_checked too)",
      (_by["2025-06-01"]["device_id"], _by["2025-06-01"]["device_source"], _by["2025-06-01"]["device_name"])
      == ("3966586101", "export_fit", "")
      and _no_lc(_by["2025-06-01"]) == {**_no_lc(_before["days"][0]), "device_id": "3966586101", "device_source": "export_fit"}
      and _by["2025-06-01"]["last_checked"] == "2024-01-01")
check("D2 an entry that already has a device_id is never overwritten (id, name, no device_source added)",
      _by["2025-06-02"] == _before["days"][1])
check("D2 the name of the unknown group is dropped on assignment and counted",
      _by["2025-06-03"]["device_id"] == "222" and _by["2025-06-03"]["device_name"] == "" and _r["names_dropped"] == 1)
check("D2 an empty id is skipped, a day without an entry is skipped and not created",
      _by["2025-06-04"] == _before["days"][3] and "2025-06-09" not in _by)
check("D2 the counts add up (a date object and its ISO text are the same day; the second hit finds an id)",
      _r == {"assigned": 2, "skipped_has_id": 2, "skipped_empty_id": 1, "skipped_no_entry": 1, "names_dropped": 1})
check("D2 the log checksum fields (date/quality/source/write) are unchanged",
      quality._compute_checksum(_data) == quality._compute_checksum(_before))

_data = _log(_qe("2025-06-01", device_id="111", device_name="A", device_source="export_fit"),
             _qe("2025-06-02", device_id="111"), _qe("2025-06-03", device_id="222", device_name="B"), _qe("2025-06-04"))
_before = copy.deepcopy(_data)
check("D2 set_device_name: names all entries of that id and nothing else",
      quality.set_device_name(_data, "111", "  Fenix  ") == 2
      and [e["device_name"] for e in _data["days"]] == ["Fenix", "Fenix", "B", ""]
      and [e["device_id"] for e in _data["days"]] == ["111", "111", "222", None]
      and _data["days"][0]["device_source"] == "export_fit")
check("D2 set_device_name: an id given as number matches; an empty name, an empty id or an unknown id change nothing",
      quality.set_device_name(_data, 222, "C") == 1 and _data["days"][2]["device_name"] == "C"
      and quality.set_device_name(_data, "111", "  ") == 0 and quality.set_device_name(_data, "", "X") == 0
      and quality.set_device_name(_data, "777", "X") == 0 and _data["days"][0]["device_name"] == "Fenix")

# ══════════════════════════════════════════════════════════════════════════════
#  3. find_candidates
# ══════════════════════════════════════════════════════════════════════════════
section("D3. find_candidates")
with _isolated_log_env("rd_find") as _b:
    check("D3 no log file -> nothing found", rd.find_candidates() == {"one": {}, "two": {}, "no_file": [], "incomplete": []})
    _hA1, _hA2 = _fit_original(_b, 3966586101, 1), _fit_original(_b, 3966586101, 2)      # one device, two files
    _hB, _hC = _fit_original(_b, 3961663084, 3), _fit_original(_b, 3978475675, 4)        # a change on the day
    _hZ = _fit_original(_b, 0, 5)                                                          # no serial (uint32z 0)
    _hMissing = "ab" * 32                                                                   # not in bulk/source
    _hBad = hashlib.sha256(b"x").hexdigest()
    (_b / "bulk" / "source" / _hBad[:2]).mkdir(parents=True, exist_ok=True)
    (_b / "bulk" / "source" / _hBad[:2] / f"{_hBad}.fit").write_bytes(b"not a fit file")
    _day_file(_b, "2025-06-01", [_hA1, _hA2])                    # one
    _day_file(_b, "2025-06-02", [_hB, _hC])                      # two
    _day_file(_b, "2025-06-03", [_hA1, _hMissing])               # one original missing -> incomplete
    _day_file(_b, "2025-06-04", [_hZ])                           # file without a serial -> incomplete
    _day_file(_b, "2025-06-05", [_hBad])                         # damaged FIT -> incomplete
    (_b / "bulk" / "raw" / "garmin_bulk_2025-06-06.json").write_text("{broken", encoding="utf-8")   # damaged day file
    _day_file(_b, "2025-06-07", [])                              # no originals listed -> incomplete
    _day_file(_b, "2025-06-08", ["../../etc/passwd"])            # not a SHA-256 -> incomplete, no path is built from it
    _day_file(_b, "2025-06-10", [_hA1])                          # has a device_id already
    _day_file(_b, "2025-06-11", [_hB, _hC, _hMissing])           # two serials AND a missing original -> still "two"
    _put_log(_log(*[_qe(f"2025-06-{n:02d}") for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11)],
                  _qe("2025-06-10", device_id="111")))
    _f = rd.find_candidates()
    check("D3 one device on the day (two originals of the same serial) -> 'one' with the serial as text",
          _f["one"] == {"2025-06-01": "3966586101"})
    check("D3 two serials -> 'two' (sorted), also when an original of the day is missing",
          _f["two"] == {"2025-06-02": ["3961663084", "3978475675"], "2025-06-11": ["3961663084", "3978475675"]})
    check("D3 no bulk day file -> 'no_file'", _f["no_file"] == ["2025-06-09"])
    check("D3 missing original, no serial, damaged FIT, damaged or empty day file, a non-hash name -> 'incomplete'",
          _f["incomplete"] == ["2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06", "2025-06-07", "2025-06-08"])
    check("D3 an entry that has a device_id is not looked at at all",
          "2025-06-10" not in _f["one"] and "2025-06-10" not in list(_f["two"]) + _f["no_file"] + _f["incomplete"])
    _b4 = _logbytes()
    rd.find_candidates()
    check("D3 it only looks: the log is byte-identical, no safety copy, no device table", _logbytes() == _b4
          and _zips(_b) == [] and not cfg.DEVICE_TABLE_FILE.exists())
    _obj = _log(_qe("2025-06-01"), _qe("2025-06-02", device_id="1"))
    check("D3 with the caller's quality_data the file is not read", rd.find_candidates(quality_data=_obj)["one"]
          == {"2025-06-01": "3966586101"})
    with patch.object(rd.fit_reader, "parse_fit", wraps=rd.fit_reader.parse_fit) as _pf:
        rd.find_candidates(quality_data=_log(_qe("2025-06-01"), _qe("2025-06-03")))
    check("D3 every original that exists is parsed once even if several days name it (the missing one is not parsed)",
          _pf.call_count == 2)
    _other = _b / "other"
    _fh = _fit_original(_other, 3425438179, 9)
    _day_file(_other, "2025-07-01", [_fh])
    (_other / "log").mkdir(parents=True)
    (_other / "log" / "quality_log.json").write_text(json.dumps(_log(_qe("2025-07-01"))), encoding="utf-8")
    # a name that is no SHA-256 must not be followed, even where a file of that name exists
    _fit_short = fb.simple_fit(32, _T0 + 50, serial=3966586101)
    (_b / "bulk" / "source" / "ab").mkdir(parents=True, exist_ok=True)
    (_b / "bulk" / "source" / "ab" / "abcd.fit").write_bytes(_fit_short)
    _day_file(_b, "2025-06-12", ["abcd"])
    check("D3 a source_files name that is no SHA-256 is not followed, although a file of that name exists: 'incomplete'",
          rd.find_candidates(quality_data=_log(_qe("2025-06-12"))) == {"one": {}, "two": {}, "no_file": [], "incomplete": ["2025-06-12"]})
    check("D3 explicit folders: the given archive is looked at, not the configured one",
          rd.find_candidates(quality_log_file=_other / "log" / "quality_log.json",
                             bulk_raw_dir=_other / "bulk" / "raw", bulk_source_dir=_other / "bulk" / "source")["one"]
          == {"2025-07-01": "3425438179"})
    check("D3 explicit folders: missing folders find nothing and do not fail",
          rd.find_candidates(quality_log_file=_b / "nowhere.json", bulk_raw_dir=_b / "nowhere", bulk_source_dir=_b / "nowhere")
          == {"one": {}, "two": {}, "no_file": [], "incomplete": []})

# ══════════════════════════════════════════════════════════════════════════════
#  4. repair_devices
# ══════════════════════════════════════════════════════════════════════════════
section("D4. repair_devices")


def _archive(base, with_log=True):
    """Two repairable days, one with two devices, one with an id, one without a day file."""
    h1, h2, h3 = _fit_original(base, 3966586101, 1), _fit_original(base, 3961663084, 2), _fit_original(base, 3978475675, 3)
    _day_file(base, "2025-06-01", [h1])
    _day_file(base, "2025-06-02", [h1])
    _day_file(base, "2025-06-03", [h2, h3])
    _day_file(base, "2025-06-04", [h2])
    entries = [_qe("2025-06-01"), _qe("2025-06-02", device_name="Group"), _qe("2025-06-03"),
               _qe("2025-06-04", device_id="3425438179", device_name="fenix 7X"), _qe("2025-06-05")]
    if with_log:
        _put_log(_log(*entries))
    return entries


with _isolated_log_env("rd_run") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _archive(_b)
        _b4 = _logbytes()
        _r = rd.repair_devices(dry_run=True)
        check("D4 dry run: reports what would happen, writes nothing (log byte-identical, no safety copy, no device table)",
              _r["ok"] == 2 and _r["failed"] == 0 and _r["per_device"] == {"3966586101": 2}
              and _logbytes() == _b4 and _zips(_b) == [] and not cfg.DEVICE_TABLE_FILE.exists())
        check("D4 the days that stay unknown are reported: two devices, no day file",
              list(_r["two"]) == ["2025-06-03"] and _r["no_file"] == ["2025-06-05"] and _r["incomplete"] == [])

        _rec = _Rec()
        with patch.object(rd, "log", _rec):
            _r = rd.repair_devices()
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("D4 the real run: two days get the id from the file and device_source export_fit, name empty",
              _r["ok"] == 2 and _r["failed"] == 0
              and all((_by[d]["device_id"], _by[d]["device_source"], _by[d]["device_name"]) == ("3966586101", "export_fit", "")
                      for d in ("2025-06-01", "2025-06-02")))
        check("D4 an existing device_id (and its name) stays; two-device day and day without file stay unknown",
              (_by["2025-06-04"]["device_id"], _by["2025-06-04"]["device_name"]) == ("3425438179", "fenix 7X")
              and "device_source" not in _by["2025-06-04"]
              and _by["2025-06-03"]["device_id"] is None and _by["2025-06-05"]["device_id"] is None)
        check("D4 nothing else on the entries changed (quality, source, write, last_checked, fields)",
              _by["2025-06-01"]["last_checked"] == "2024-01-01" and _by["2025-06-01"]["fields"] == {"heart_rates": "medium"}
              and _by["2025-06-01"]["quality"] == "standard" and _by["2025-06-01"]["write"] is True)
        check("D4 the unknown days are warned about, the dropped group name is logged",
              any("2025-06-03" in m and "two devices" in m for m in _rec.m["warning"])
              and any("1 name(s) of the unknown group dropped" in m for m in _rec.m["info"]))
        _tbl = json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))
        check("D4 device_table.json is rewritten: the new id has its 2 days, the unknown row keeps the 2 left",
              {r["device_id"]: r["days_total"] for r in _tbl}.get("3966586101") is not None
              and next(r for r in _tbl if r["device_id"] == "__unknown__")["date_from"] == "2025-06-03")
        check("D4 one safety copy of the quality log, a valid quality_log_*.zip",
              len(_zips(_b)) == 1 and _zips(_b)[0].startswith("quality_log_")
              and snap.verify_snapshot(_snap_dir(_b) / _zips(_b)[0])["ok"])
        with zipfile.ZipFile(_snap_dir(_b) / _zips(_b)[0]) as _zf:
            _names = sorted(_zf.namelist())
            _old = json.loads(_zf.read("log/quality_log.json"))
        check("D4 the copy holds only MANIFEST.json and log/quality_log.json, and in the log nobody has a device_source yet",
              _names == ["MANIFEST.json", "log/quality_log.json"] and not any("device_source" in e for e in _old["days"])
              and _r["safety_copy"] == _zips(_b)[0])
        _after = _logbytes()
        _r2 = rd.repair_devices()
        check("D4 a second run changes nothing: ok 0, log byte-identical, no second safety copy",
              _r2["ok"] == 0 and _r2["failed"] == 0 and _logbytes() == _after and len(_zips(_b)) == 1)

        # the way back of the log-only copy
        _res = snap.restore_snapshot(_snap_dir(_b) / _zips(_b)[0], dry_run=True)
        check("D4 way back, dry run: counts the entries that would come back, writes nothing",
              _res["ok"] is True and _res["restored"] == 2 and _logbytes() == _after)
        _res = snap.restore_snapshot(_snap_dir(_b) / _zips(_b)[0])
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("D4 way back: the two entries are as before the repair; the other entries stay as they are",
              _res["ok"] is True and _res["restored"] == 2 and _res["log_saved"] is True
              and _by["2025-06-01"]["device_id"] is None and "device_source" not in _by["2025-06-01"]
              and _by["2025-06-02"]["device_name"] == "Group" and _by["2025-06-04"]["device_id"] == "3425438179")
        check("D4 after the way back the repair can run again (nothing was lost)", rd.repair_devices()["ok"] == 2)

with _isolated_log_env("rd_shared") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _archive(_b)
        _shared = quality._load_quality_log()
        with patch.object(quality, "_load_quality_log", wraps=quality._load_quality_log) as _ld, \
                patch.object(quality, "_save_quality_log", wraps=quality._save_quality_log) as _sv:
            _r = rd.repair_devices(quality_data=_shared)
        check("D4 shared quality log: the caller's object gets the ids, it is not loaded again and exactly that object is saved once",
              _r["ok"] == 2 and _ld.call_count == 0 and _sv.call_count == 1 and _sv.call_args.args[0] is _shared
              and {e["date"]: e["device_id"] for e in _shared["days"]}["2025-06-01"] == "3966586101")

with _isolated_log_env("rd_fail") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _archive(_b)
        _b4 = _logbytes()
        _rec = _Rec()
        with patch.object(rd, "log", _rec), patch.object(snap, "create_snapshot",
                                                         return_value={"ok": False, "path": None, "reason": "disk full"}):
            _r = rd.repair_devices()
        check("D4 no safety copy, no write: failed 1 with the reason, the log is byte-identical, an error is logged",
              _r["failed"] == 1 and _r["ok"] == 0 and _r["reason"] == "disk full" and _logbytes() == _b4
              and any("nothing written" in m for m in _rec.m["error"]))
        with patch.object(snap, "create_snapshot", return_value={"ok": True, "path": None, "reason": "nothing to back up"}):
            _r = rd.repair_devices()
        check("D4 'ok' without a ZIP is not a safety copy either: nothing written", _r["failed"] == 1 and _logbytes() == _b4)
        _r = rd.repair_devices(should_stop=lambda: True)
        check("D4 a stop request before the write: nothing written, no safety copy, stopped",
              _r["stopped"] is True and _r["ok"] == 0 and _logbytes() == _b4 and _zips(_b) == [])
        with patch.object(quality, "_save_quality_log", return_value=False):
            _r = rd.repair_devices()
        check("D4 a log that cannot be saved: failed 1 with the reason (the safety copy exists)",
              _r["failed"] == 1 and _r["ok"] == 0 and "saved" in _r["reason"] and len(_zips(_b)) == 1)

with _isolated_log_env("rd_none") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _put_log(_log(_qe("2025-06-01", device_id="1"), _qe("2025-06-02")))
        _b4 = _logbytes()
        _r = rd.repair_devices()
        check("D4 nothing repairable: ok 0, nothing written, no safety copy",
              (_r["ok"], _r["failed"]) == (0, 0) and _logbytes() == _b4 and _zips(_b) == [])

# ══════════════════════════════════════════════════════════════════════════════
#  5. create_snapshot(stores=...) and list_snapshots
# ══════════════════════════════════════════════════════════════════════════════
section("D5. Backup by change list: create_snapshot(stores=...)")
with _isolated_log_env("rd_snap") as _b:
    with _cfg_values(MIGRATION_BACKUP_DIR=_snap_dir(_b)):
        _rawf = cfg.RAW_DIR / "garmin_raw_2025-06-01.json"
        _rawf.parent.mkdir(parents=True, exist_ok=True)
        _rawf.write_text("{}", encoding="utf-8")
        _put_log(_log(_qe("2025-06-01")))
        _full = snap.create_snapshot()
        _only = snap.create_snapshot(stores=("quality_log",))
        check("D5 default: all stores, migration_*.zip as before; stores=('quality_log',): quality_log_*.zip with the log only",
              _full["ok"] and _full["path"].name.startswith("migration_") and (_full["raw"], _full["log"]) == (1, True)
              and _only["ok"] and _only["path"].name.startswith("quality_log_") and (_only["raw"], _only["summary"], _only["log"]) == (0, 0, True))
        with zipfile.ZipFile(_only["path"]) as _zf:
            _man = json.loads(_zf.read("MANIFEST.json"))
        check("D5 the manifest names the stores; both ZIPs pass verify_snapshot",
              _man["stores"] == ["quality_log"] and snap.verify_snapshot(_only["path"])["ok"] and snap.verify_snapshot(_full["path"])["ok"])
        check("D5 list_snapshots lists both kinds, oldest name first",
              [s["name"][:9] for s in snap.list_snapshots()] == ["migration", "quality_l"])
        for _bad in (("nonsense",), ("raw", "x"), ()):
            _x = snap.create_snapshot(stores=_bad)
            check(f"D5 unknown or empty stores {_bad!r}: refused, nothing written", _x["ok"] is False and _x["path"] is None
                  and len(snap.list_snapshots()) == 2)
        _l = snap.create_snapshot(stores=("quality_log",))
        check("D5 a second copy in the same second gets its own name", _l["ok"] and _l["path"] != _only["path"] and _l["path"].exists())
        cfg.QUALITY_LOG_FILE.unlink()
        _nolog = snap.create_snapshot(stores=("quality_log",))
        check("D5 without a log there is nothing to back up: ok, no path", _nolog["ok"] is True and _nolog["path"] is None)

# ══════════════════════════════════════════════════════════════════════════════
#  6. Mirror import passes device_source on
# ══════════════════════════════════════════════════════════════════════════════
section("D6. Mirror import: device_source travels with device_id")
import garmin_import_mirror as mirror
with _isolated_log_env("rd_mirror") as _b:
    for _d in ("2025-06-01", "2025-06-02"):
        bw.write_aggregates(_d, {"date": _d, "user_summary": {"totalSteps": 5}}, ["cd" * 32])
    _dst = _log()
    _entries = [_qe("2025-06-01", quality="standard", source="bulk", device_id="3966586101", device_source="export_fit"),
                _qe("2025-06-02", quality="standard", source="bulk", device_id="3966586101")]
    _made, _err = mirror._import_export_days(_entries, [], _dst, quality)
    _by = {e["date"]: e for e in _dst["days"]}
    check("D6 the entry made from the other archive keeps device_source; an entry without one gets none",
          (_made, _err) == (2, 0) and _by["2025-06-01"]["device_source"] == "export_fit"
          and "device_source" not in _by["2025-06-02"] and _by["2025-06-02"]["device_id"] == "3966586101")

# ══════════════════════════════════════════════════════════════════════════════
#  7. Scheduler hint — scheduler/daily_update.py::_check_device_repair
# ══════════════════════════════════════════════════════════════════════════════
section("D7. Scheduler hint")
_du_spec = importlib.util.spec_from_file_location(
    "daily_update_rd", Path(__file__).resolve().parent.parent / "scheduler" / "daily_update.py")
_du = importlib.util.module_from_spec(_du_spec)
_du_spec.loader.exec_module(_du)

with _isolated_log_env("rd_sched") as _b:
    _arch = _b / "archive"
    _g = _arch / "garmin_data"
    _hh = _fit_original(_g, 3966586101, 1)
    _hh2, _hh3 = _fit_original(_g, 3961663084, 2), _fit_original(_g, 3978475675, 3)
    _day_file(_g, "2025-06-01", [_hh])
    _day_file(_g, "2025-06-02", [_hh2, _hh3])          # two devices: not counted
    (_g / "log").mkdir(parents=True)
    (_g / "log" / "quality_log.json").write_text(json.dumps(_log(_qe("2025-06-01"), _qe("2025-06-02"), _qe("2025-06-03"))),
                                                 encoding="utf-8")
    _before = {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()}
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n = _du._check_device_repair(_arch)
    check("D7 counts only the days that can get a device and warns with the number, nothing else",
          _n == 1 and _rec.m["warning"] == [
              "  1 day(s) have no device in the quality log, but the kept export files name one.",
              "  Open the app and run Sync Garmin once to assign them (a safety copy is made first)."]
          and not _rec.m["error"])
    check("D7 it only looks: no file of the archive changes, none is added",
          {p.relative_to(_arch): p.read_bytes() for p in _arch.rglob("*") if p.is_file()} == _before)
    _rec = _Rec()
    with patch.object(_du, "log", _rec):
        _n_none = _du._check_device_repair(_b / "no_archive_here")
    check("D7 no archive folder -> 0 and no warning", _n_none == 0 and not _rec.m["warning"])
    _rec = _Rec()
    with patch.object(_du, "log", _rec), patch.object(rd, "find_candidates", side_effect=RuntimeError("boom")):
        _n_err = _du._check_device_repair(_arch)
    check("D7 an error in the scan never stops the run: 0, no warning, no error", _n_err == 0 and not _rec.m["warning"] and not _rec.m["error"])

# ══════════════════════════════════════════════════════════════════════════════
#  8. Naming by id — controller.rename_device
# ══════════════════════════════════════════════════════════════════════════════
section("D8. Naming by id (controller)")
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import garmin_app_controller as ctl

with _isolated_log_env("rd_name") as _b:
    _arch = _b / "archive"
    (_arch / "garmin_data" / "log").mkdir(parents=True)
    _lf = _arch / "garmin_data" / "log" / "quality_log.json"
    _lf.write_text(json.dumps(_log(
        _qe("2025-06-01", device_id="3966586101", device_source="export_fit"), _qe("2025-06-02", device_id="3966586101"),
        _qe("2025-06-03", device_id="222", device_name="Other"), _qe("2025-06-04"))), encoding="utf-8")
    with _cfg_values(QUALITY_LOG_FILE=_lf, DEVICE_TABLE_FILE=_arch / "garmin_data" / "log" / "device_table.json"):
        _res = ctl.rename_device({"base_dir": str(_arch)}, "3966586101", "vivoactive 3")
        _by = {e["date"]: e for e in quality._load_quality_log()["days"]}
        check("D8 names all entries of the id, saves the log and rewrites the device table; nothing else changes",
              _res == {"updated": 2} and _by["2025-06-01"]["device_name"] == "vivoactive 3" == _by["2025-06-02"]["device_name"]
              and _by["2025-06-01"]["device_source"] == "export_fit"
              and (_by["2025-06-03"]["device_name"], _by["2025-06-04"]["device_id"]) == ("Other", None)
              and any(r["device_id"] == "3966586101" and r["name"] == "vivoactive 3"
                      for r in json.loads(cfg.DEVICE_TABLE_FILE.read_text(encoding="utf-8"))))
        check("D8 an unknown id or an empty name: {'updated': 0} and the log is not written",
              ctl.rename_device({"base_dir": str(_arch)}, "999", "X") == {"updated": 0}
              and ctl.rename_device({"base_dir": str(_arch)}, "222", " ") == {"updated": 0})
    check("D8 no log file: {'updated': 0}", ctl.rename_device({"base_dir": str(_b / "nowhere")}, "1", "X") == {"updated": 0})
    with patch.object(quality, "set_device_name", side_effect=RuntimeError("boom")), \
            _cfg_values(QUALITY_LOG_FILE=_lf):
        _res = ctl.rename_device({"base_dir": str(_arch)}, "222", "X")
    check("D8 an error is returned as 'error', never raised, and the lock is free again",
          _res.get("updated") == 0 and "boom" in _res.get("error", "") and quality.QUALITY_LOCK.acquire(False) and not quality.QUALITY_LOCK.release())

summary()
