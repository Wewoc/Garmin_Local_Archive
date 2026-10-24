#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_backup_common.py — garmin_backup_common (v1.7.6.2)

Run from the project folder:
    python tests/test_backup_common.py

Part A pins the module itself on folders it is handed. Part B is the proof that the
shared mechanics behave like the two modules they were taken from: the same scenario
runs once through garmin_backup / garmin_backup_source and once through
garmin_backup_common, in two identical fresh folders; the return values, the resulting
folder trees (ZIP files compared entry by entry) and the log lines must be equal.
"""

import ast
import contextlib
import dataclasses
import json
import shutil
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_backup as _old_raw
import garmin_backup_source as _old_src
import garmin_backup_common as common

_CUR = date.today().strftime("%Y-%m")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _BLog:
    """Stands in for a module logger and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def error(self, msg, *a, **k):
        self._add("error", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)


def _zip_write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)


def _zip_read(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def _dj(day, v):
    """Content of a valid day file: a JSON object whose "date" is the day."""
    return json.dumps({"date": day, "v": v})


def _tree(root):
    """{relative path: bytes} of every file under root, a ZIP as {entry: bytes}; folders as None."""
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            out[rel + "/"] = None
        elif p.suffix == ".zip" or p.name.endswith(".zip.tmp"):
            # a leftover .zip.tmp is compared entry by entry too: its bytes carry the file times of
            # the entries, which differ between two runs a few seconds apart
            try:
                with zipfile.ZipFile(p) as z:
                    out[rel] = {n: z.read(n) for n in z.namelist()}
            except Exception:
                out[rel] = p.read_bytes()
        else:
            out[rel] = p.read_bytes()
    return out


def _fresh(name):
    base = _TMPDIR / f"bc_{name}"
    shutil.rmtree(base, ignore_errors=True)
    (base / "src").mkdir(parents=True)
    (base / "bk").mkdir(parents=True)
    return base / "src", base / "bk"


def _mkind(src, bk, **kw):
    args = dict(area="raw", src_dir=src, backup_dir=bk, prefix="garmin_raw_",
                zip_prefix="raw_backup_", is_valid=common.is_dated_object)
    args.update(kw)
    return common.BackupKind(**args)


def _put(src, prefix, day, content="{}"):
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{prefix}{day}.json").write_text(content, encoding="utf-8")


def _month(bk, prefix, month, days, content="x"):
    d = bk / month
    d.mkdir(parents=True, exist_ok=True)
    for day in days:
        (d / f"{prefix}{month}-{day}.json").write_text(content, encoding="utf-8")
    return d


def _logged(fn, *args, **kwargs):
    real, rec = common.log, _BLog()
    common.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        common.log = real


# ══════════════════════════════════════════════════════════════════════════════
#  Part A. The module itself
# ══════════════════════════════════════════════════════════════════════════════
section("A. garmin_backup_common — the module on folders it is handed")

# -- A1. Leaf Node: stdlib only, no project import ---------------------------------------
_text = Path(common.__file__).read_text(encoding="utf-8")
_tree_ast = ast.parse(_text)
_imported = set()
for _node in ast.walk(_tree_ast):
    if isinstance(_node, ast.Import):
        _imported |= {a.name.split(".")[0] for a in _node.names}
    elif isinstance(_node, ast.ImportFrom):
        _imported.add((_node.module or "").split(".")[0])
_STDLIB = {"json", "logging", "os", "shutil", "zipfile", "zlib", "dataclasses", "datetime", "pathlib", "typing"}
check("A1 leaf node: only standard-library imports", _imported <= _STDLIB)
check("A1 leaf node: garmin_config is not imported", "garmin_config" not in _imported)
check("A1 leaf node: the module has no cfg attribute", not hasattr(common, "cfg"))

# -- A2. BackupKind --------------------------------------------------------------------------
_s, _b = _fresh("kind")
_kd = _mkind(_s, _b)
check("A2 BackupKind: pattern is built from prefix and suffix", _kd.pattern == "garmin_raw_*.json")
check("A2 BackupKind: zip_path is backup_dir / zip_prefix + month + .zip",
      _kd.zip_path("2024-08") == _b / "raw_backup_2024-08.zip")
check("A2 BackupKind: date_of takes the date out of a file name",
      _kd.date_of(_s / "garmin_raw_2024-08-27.json") == "2024-08-27")
try:
    _kd.area = "x"
    _frozen = False
except dataclasses.FrozenInstanceError:
    _frozen = True
check("A2 BackupKind: is frozen", _frozen)

# -- A3. ready-made validity checks ------------------------------------------------------------
check("A3 is_dated_object: object with the matching date -> True",
      common.is_dated_object(_dj("2024-08-27", 1).encode(), "2024-08-27") is True)
check("A3 is_dated_object: other date, no date, list, broken JSON, non-UTF-8 -> False",
      common.is_dated_object(_dj("2024-08-26", 1).encode(), "2024-08-27") is False
      and common.is_dated_object(b'{"v": 1}', "2024-08-27") is False
      and common.is_dated_object(b"[1]", "2024-08-27") is False
      and common.is_dated_object(b"{broken", "2024-08-27") is False
      and common.is_dated_object(b"\xff\xfe", "2024-08-27") is False)
check("A3 is_json_object: any object -> True, whatever its date",
      common.is_json_object(b'{"date": "other"}', "2024-08-27") is True
      and common.is_json_object(b"{}", "2024-08-27") is True)
check("A3 is_json_object: list, broken JSON, non-UTF-8 -> False",
      common.is_json_object(b"[1]", "2024-08-27") is False
      and common.is_json_object(b"{broken", "2024-08-27") is False
      and common.is_json_object(b"\xff\xfe", "2024-08-27") is False)

# -- A4. the consolidate hook ----------------------------------------------------------------
_s, _b = _fresh("hook")
_kd = _mkind(_s, _b)
_put(_s, "garmin_raw_", "2024-08-27")
_calls = []
_ok1 = common.backup_file(_kd, "2024-08-27", consolidate=lambda **kw: _calls.append(kw))
_ok2 = common.backup_file(_kd, "2024-08-27", force=True, consolidate=lambda **kw: _calls.append(kw))
check("A4 backup_file: calls the given consolidation with today's real month, only force names the file",
      _ok1 is True and _ok2 is True
      and _calls == [{"current_month": _CUR, "force_filenames": None},
                     {"current_month": _CUR, "force_filenames": {"garmin_raw_2024-08-27.json"}}])

_s, _b = _fresh("hook_bf")
_kd = _mkind(_s, _b)
_put(_s, "garmin_raw_", "2024-05-01")
_put(_s, "garmin_raw_", "2024-06-01")
_calls = []
_r = common.backfill(_kd, consolidate=lambda **kw: _calls.append(kw))
check("A4 backfill: several old months touched -> the given consolidation is called once, with today's month",
      _r == {"copied": 2, "skipped": 0, "failed": 0} and _calls == [{"current_month": _CUR}])

_s, _b = _fresh("hook_bf_cur")
_kd = _mkind(_s, _b)
_put(_s, "garmin_raw_", f"{_CUR}-15")
_calls = []
common.backfill(_kd, consolidate=lambda **kw: _calls.append(kw))
check("A4 backfill: only the current month touched -> no consolidation", _calls == [])

_s, _b = _fresh("hook_rf")
_kd = _mkind(_s, _b)
_zip_write(_b / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-27.json": _dj("2024-08-27", "old")})
_put(_s, "garmin_raw_", "2024-08-27", _dj("2024-08-27", "new"))
_calls = []
_r = common.refresh(_kd, consolidate=lambda **kw: _calls.append(kw))
check("A4 refresh: something refreshed -> the given consolidation is called once, with today's month",
      _r["refreshed"] == 1 and _calls == [{"current_month": _CUR}])
_calls = []
common.refresh(_kd, consolidate=lambda **kw: _calls.append(kw))
check("A4 refresh: nothing outdated any more -> no consolidation", _calls == [])

# -- A5. the ZIP helpers -----------------------------------------------------------------------
_s, _b = _fresh("zip")
_zip_write(_b / "z.zip", {"a.json": "1"})
(_b / "notzip.zip").write_bytes(b"this is not a zip")
check("A5 zip_contains: present -> True, absent -> False, corrupt -> False, missing ZIP -> False",
      common.zip_contains(_b / "z.zip", "a.json") is True and common.zip_contains(_b / "z.zip", "b.json") is False
      and common.zip_contains(_b / "notzip.zip", "a.json") is False
      and common.zip_contains(_b / "nothing.zip", "a.json") is False)
_idx = common.zip_index(_b / "z.zip")
check("A5 zip_index: {name: (crc32, size)} from the ZIP directory",
      list(_idx) == ["a.json"] and _idx["a.json"][1] == 1)
_res, _c = _logged(common.zip_index, _b / "notzip.zip")
check("A5 zip_index: a ZIP that cannot be read -> {} and one warning",
      _res == {} and [lv for lv, _ in _c] == ["warning"] and "cannot read notzip.zip" in _c[0][1])

# -- A6. check_backfill_needed: a failing probe is logged per file -------------------------
_s, _b = _fresh("needed")
_kd = _mkind(_s, _b)
_put(_s, "garmin_raw_", "2024-08-05")
_zip_write(_b / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-01.json": "{}"})
check("A6 check_backfill_needed: ZIP exists but lacks the file -> counted",
      common.check_backfill_needed(_kd) == 1)
with patch.object(common, "zip_contains", side_effect=RuntimeError("probe")):
    _n, _c = _logged(common.check_backfill_needed, _kd)
check("A6 check_backfill_needed: a failing probe is a warning naming kind and file, nothing counted",
      _n == 0 and any(lv == "warning" and "check_raw_backfill_needed: failed for garmin_raw_2024-08-05.json" in m
                      for lv, m in _c))
check("A6 check_backfill_needed: no source folder -> 0",
      common.check_backfill_needed(_mkind(_s / "nothing", _b)) == 0)

# -- A7. another kind of file works the same (the reason for the module) ---------------------
_s, _b = _fresh("other_kind")
_ak = _mkind(_s, _b, area="bulk-aggregates", prefix="garmin_bulk_agg_", zip_prefix="bulk_aggregates_backup_",
             log_prefix="backup_bulk")
_put(_s, "garmin_bulk_agg_", "2024-08-27", _dj("2024-08-27", "one"))
check("A7 another kind: a day in a completed month is backed up and packed into its own ZIP name",
      common.backup_file(_ak, "2024-08-27") is True
      and _zip_read(_b / "bulk_aggregates_backup_2024-08.zip") == {"garmin_bulk_agg_2024-08-27.json": _dj("2024-08-27", "one")}
      and not (_b / "2024-08").exists())
_put(_s, "garmin_bulk_agg_", "2024-08-27", _dj("2024-08-27", "two"))
common.backup_file(_ak, "2024-08-27")
check("A7 another kind: the rewritten day replaces its ZIP entry",
      _zip_read(_b / "bulk_aggregates_backup_2024-08.zip") == {"garmin_bulk_agg_2024-08-27.json": _dj("2024-08-27", "two")})
_res, _c = _logged(common.backup_file, _ak, "2024-08-28")
check("A7 another kind: a missing source file is False and the warning names the kind",
      _res is False and _c == [("warning", "  backup_bulk-aggregates: source file not found for 2024-08-28")])

# -- A8. find_outdated: the month folder is the newest copy ---------------------------------
_s, _b = _fresh("precedence")
_kd = _mkind(_s, _b)
_zip_write(_b / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-27.json": _dj("2024-08-27", "zip-old")})
_month(_b, "garmin_raw_", "2024-08", ["27"], content=_dj("2024-08-27", "same"))
_put(_s, "garmin_raw_", "2024-08-27", _dj("2024-08-27", "same"))
check("A8 find_outdated: the folder copy equals the file -> not outdated, even if the ZIP entry differs",
      common.find_outdated(_kd) == ([], []) and common.check_stale(_kd) == 0)

# -- A9. the source folder is only read ----------------------------------------------------------
_s, _b = _fresh("readonly")
_kd = _mkind(_s, _b)
_zip_write(_b / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-27.json": _dj("2024-08-27", "old"),
                                           "garmin_raw_2024-08-28.json": _dj("2024-08-28", "old")})
_put(_s, "garmin_raw_", "2024-08-27", _dj("2024-08-27", "new"))
_put(_s, "garmin_raw_", "2024-08-28", '{"date": "2024-08-99"}')          # not valid: date does not match
_before = _tree(_s)
_r = common.refresh(_kd)
common.backfill(_kd)
common.backup_file(_kd, "2024-08-27")
check("A9 refresh: the valid changed file is refreshed, the invalid one is reported and not copied",
      _r == {"refreshed": 1, "unreadable": 1, "errors": 0}
      and json.loads(_zip_read(_b / "raw_backup_2024-08.zip")["garmin_raw_2024-08-28.json"])["v"] == "old")
check("A9 refresh, backfill, backup_file: nothing in the source folder is created, changed or removed",
      _tree(_s) == _before)

# -- A10. read_copy (v1.7.6.2) -----------------------------------------------------------------
_s, _b = _fresh("readcopy")
_kd = _mkind(_s, _b)
_zip_write(_b / "raw_backup_2024-08.zip", {"garmin_raw_2024-08-01.json": "zip-01", "garmin_raw_2024-08-02.json": "zip-02"})
_month(_b, "garmin_raw_", "2024-08", ["02"], content="dir-02")
_before = _tree(_b)
check("A10 read_copy: the month folder first, otherwise the entry in the monthly ZIP",
      common.read_copy(_kd, "garmin_raw_2024-08-02.json") == b"dir-02"
      and common.read_copy(_kd, "garmin_raw_2024-08-01.json") == b"zip-01")
_v1, _c1 = _logged(common.read_copy, _kd, "garmin_raw_2024-08-03.json")
_v2, _c2 = _logged(common.read_copy, _kd, "garmin_raw_2024-09-01.json")
check("A10 read_copy: no copy (name not in the ZIP, no ZIP for the month) -> None, and no warning (it is not an error)",
      _v1 is None and _v2 is None and _c1 == [] and _c2 == [])
with patch.object(Path, "read_bytes", side_effect=OSError("locked")):
    _v, _c = _logged(common.read_copy, _kd, "garmin_raw_2024-08-02.json")
check("A10 read_copy: a month folder copy that cannot be read falls back to the ZIP entry, with a warning",
      _v == b"zip-02" and [lv for lv, _ in _c] == ["warning"] and "month folder copy" in _c[0][1])
(_b / "raw_backup_2024-07.zip").write_bytes(b"this is not a zip")
_v, _c = _logged(common.read_copy, _kd, "garmin_raw_2024-07-01.json")
check("A10 read_copy: a ZIP that cannot be read -> None and one warning naming the file",
      _v is None and [lv for lv, _ in _c] == ["warning"] and "garmin_raw_2024-07-01.json" in _c[0][1])
check("A10 read_copy: reads only (the backup folder is unchanged apart from the garbage ZIP made above)",
      {k: v for k, v in _tree(_b).items() if k != "raw_backup_2024-07.zip"} == _before)


# ══════════════════════════════════════════════════════════════════════════════
#  Part B. The same scenario through the old module and through the common module
# ══════════════════════════════════════════════════════════════════════════════
section("B. garmin_backup_common — same behaviour as garmin_backup and garmin_backup_source")

_KINDS = [
    {"name": "raw", "mod": _old_raw, "log": _old_raw,
     "cons": "_consolidate_raw_months", "backup": "backup_raw",
     "backfill": "backfill_raw", "bf_err": "errors", "needed": "check_raw_backfill_needed",
     "stale": "check_raw_stale_backups", "refresh": "refresh_raw_backups",
     "src_dir": "RAW_DIR", "bk_dir": "RAW_BACKUP_DIR", "prefix": "garmin_raw_", "zip_prefix": "raw_backup_",
     "valid": common.is_dated_object, "log_prefix": "backup"},
    {"name": "source", "mod": _old_src, "log": _old_src,
     "cons": "_consolidate_source_months", "backup": "backup_source",
     "backfill": "backfill_source", "bf_err": "failed", "needed": "check_source_backfill_needed",
     "stale": "check_source_stale_backups", "refresh": "refresh_source_backups",
     "src_dir": "SOURCE_DIR", "bk_dir": "SOURCE_BACKUP_DIR", "prefix": "garmin_source_", "zip_prefix": "source_backup_",
     "valid": common.is_json_object, "log_prefix": "backup_source"},
]


def _src(k):
    return getattr(cfg, k["src_dir"])


def _bkd(k):
    return getattr(cfg, k["bk_dir"])


def _fn(k, day):
    return f"{k['prefix']}{day}.json"


def _kind(k):
    return common.BackupKind(area=k["name"], src_dir=_src(k), backup_dir=_bkd(k), prefix=k["prefix"],
                             zip_prefix=k["zip_prefix"], is_valid=k["valid"], log_prefix=k["log_prefix"])


def _run(k, tag, which, setup, op, patches=()):
    """Runs op in a fresh isolated archive; returns (result, backup tree, source tree, non-debug log)."""
    with _isolated_log_env(f"bc_{tag}_{k['name']}_{which}"):
        setup(k)
        holder = k["log"] if which == "old" else common
        real, rec = holder.log, _BLog()
        holder.log = rec
        try:
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p())
                result = op(k)
        finally:
            holder.log = real
        return (result, _tree(_bkd(k)), _tree(_src(k)), [c for c in rec.calls if c[0] != "debug"])


def _same(label, k, tag, setup, old_op, new_op, patches=(), logs=True):
    old = _run(k, tag, "old", setup, old_op, patches)
    new = _run(k, tag, "new", setup, new_op, patches)
    check(f"B {k['name']} {label}: same return value", old[0] == new[0])
    check(f"B {k['name']} {label}: same backup folder (ZIPs compared entry by entry)", old[1] == new[1])
    check(f"B {k['name']} {label}: source folder unchanged and equal", old[2] == new[2])
    if logs:
        check(f"B {k['name']} {label}: same log lines (without debug)", old[3] == new[3])
    return old, new


# -- setups ----------------------------------------------------------------------------------
def _setup_old_zip_new_dir(k):
    _bkd(k).mkdir(parents=True, exist_ok=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-26"): "old-26", _fn(k, "2024-08-27"): "old-27"})
    md = _bkd(k) / "2024-08"
    md.mkdir()
    (md / _fn(k, "2024-08-27")).write_text("new-27", encoding="utf-8")
    (md / _fn(k, "2024-08-28")).write_text("new-28", encoding="utf-8")


def _setup_force_scope(k):
    """Month 2024-08: the folder holds one file identical to its ZIP entry and one changed file."""
    _bkd(k).mkdir(parents=True, exist_ok=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-26"): "same-26", _fn(k, "2024-08-27"): "old-27"})
    md = _bkd(k) / "2024-08"
    md.mkdir()
    (md / _fn(k, "2024-08-26")).write_text("same-26", encoding="utf-8")
    (md / _fn(k, "2024-08-27")).write_text("new-27", encoding="utf-8")


def _setup_new_month(k):
    _month(_bkd(k), k["prefix"], "2024-07", ["01", "02"], content="seven")


def _setup_edges(k):
    _bkd(k).mkdir(parents=True)
    (_bkd(k) / "2024-07").mkdir()
    _month(_bkd(k), k["prefix"], "2024-09", ["01"], content="cur")
    _month(_bkd(k), k["prefix"], "2024-10", ["01"], content="later")
    (_bkd(k) / "stray.txt").write_text("not a month folder", encoding="utf-8")


def _setup_two_months(k):
    _bkd(k).mkdir(parents=True)
    for m in ("2024-05", "2024-06"):
        _zip_write(_bkd(k) / f"{k['zip_prefix']}{m}.zip", {_fn(k, f"{m}-01"): "old"})
        _month(_bkd(k), k["prefix"], m, ["02"])


def _setup_force_two_months(k):
    _bkd(k).mkdir(parents=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-05.zip", {_fn(k, "2024-05-26"): "old-26", _fn(k, "2024-05-27"): "old-27"})
    _month(_bkd(k), k["prefix"], "2024-05", ["27"], content="new-27")
    _month(_bkd(k), k["prefix"], "2024-06", ["01"])


def _setup_rewritten_day(k):
    _bkd(k).mkdir(parents=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-27"): "old-27"})
    _put(_src(k), k["prefix"], "2024-08-27", "new-27")


def _setup_same_day(k):
    _bkd(k).mkdir(parents=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-27"): "same-27"})
    _put(_src(k), k["prefix"], "2024-08-27", "same-27")


def _setup_open_month(k):
    _put(_src(k), k["prefix"], f"{_CUR}-01", "today")


def _setup_no_source(k):
    _src(k).mkdir(parents=True)


def _setup_backfill(k):
    for d in ("2024-03-01", "2024-03-02", "2024-03-03", "2024-08-05", f"{_CUR}-15"):
        _put(_src(k), k["prefix"], d)
    _month(_bkd(k), k["prefix"], "2024-03", ["01"])                       # in a month folder
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-03.zip", {_fn(k, "2024-03-02"): "x"})   # in a ZIP
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-01"): "other day"})


def _setup_refresh(k):
    d27, d28, d29, d30 = "2024-08-27", "2024-08-28", "2024-08-29", "2024-08-30"
    _bkd(k).mkdir(parents=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, d27): _dj(d27, "old"), _fn(k, d28): _dj(d28, "same"),
                                                          _fn(k, d29): _dj(d29, "old")})
    _put(_src(k), k["prefix"], d27, _dj(d27, "new"))
    _put(_src(k), k["prefix"], d28, _dj(d28, "same"))
    # not valid for raw/ (the date does not match its name), still a JSON object for source/:
    _put(_src(k), k["prefix"], d29, json.dumps({"date": "2024-08-99", "v": "new"}))
    _put(_src(k), k["prefix"], d30, _dj(d30, "no backup at all"))
    cur = f"{_CUR}-01"
    _month(_bkd(k), k["prefix"], _CUR, ["01"], content=_dj(cur, "old"))
    _put(_src(k), k["prefix"], cur, _dj(cur, "new"))


def _setup_refresh_invalid_json(k):
    d27 = "2024-08-27"
    _bkd(k).mkdir(parents=True)
    _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, d27): _dj(d27, "old")})
    _put(_src(k), k["prefix"], d27, "{broken")


def _setup_refresh_badzip(k):
    _bkd(k).mkdir(parents=True)
    (_bkd(k) / f"{k['zip_prefix']}2024-08.zip").write_bytes(b"this is not a zip")
    _put(_src(k), k["prefix"], "2024-08-27", _dj("2024-08-27", "x"))


_X27 = "2024-08-27"

for _k in _KINDS:
    _f27 = lambda k: {_fn(k, _X27)}                                          # noqa: E731

    # consolidation ---------------------------------------------------------------------------
    for _label, _force in (("consolidate, forced file", True), ("consolidate, no force", False)):
        _same(_label, _k, f"cons_{_force}", _setup_old_zip_new_dir,
              lambda k, f=_force: (getattr(k["mod"], k["cons"])(current_month="2024-09", force_filenames=_f27(k) if f else None)),
              lambda k, f=_force: common.consolidate_months(_kind(k), current_month="2024-09",
                                                            force_filenames=_f27(k) if f else None))
    for _label, _force in (("force names one file, an identical file of the month is not rewritten", True),
                           ("no force, only the changed file is replaced", False)):
        _o, _n = _same(f"consolidate, {_label}", _k, f"scope_{_force}", _setup_force_scope,
                       lambda k, f=_force: getattr(k["mod"], k["cons"])(
                           current_month="2024-09", force_filenames={_fn(k, "2024-08-27")} if f else None),
                       lambda k, f=_force: common.consolidate_months(
                           _kind(k), current_month="2024-09", force_filenames={_fn(k, "2024-08-27")} if f else None))
        check(f"B {_k['name']} consolidate scope ({'force' if _force else 'no force'}): exactly one file is replaced",
              any("1 file(s) replaced" in m for _lv, m in _n[3]) and not any("2 file(s) replaced" in m for _lv, m in _n[3]))
    _same("consolidate, failing swap", _k, "swapfail", _setup_old_zip_new_dir,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09", force_filenames=_f27(k)),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09", force_filenames=_f27(k)),
          patches=(lambda: patch("os.replace", side_effect=OSError("locked")),))
    _same("consolidate, failing swap and failing cleanup", _k, "cleanupfail", _setup_old_zip_new_dir,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09", force_filenames=_f27(k)),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09", force_filenames=_f27(k)),
          patches=(lambda: patch("os.replace", side_effect=OSError("locked")),
                   lambda: patch.object(Path, "unlink", side_effect=OSError("also locked"))))
    _same("consolidate, rebuilt ZIP fails its check", _k, "badrebuild", _setup_old_zip_new_dir,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09", force_filenames=_f27(k)),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09", force_filenames=_f27(k)),
          patches=(lambda: patch.object(zipfile.ZipFile, "testzip", side_effect=[None, "broken.json"]),))
    _same("consolidate, ZIP fails its check after appending", _k, "badappend", _setup_old_zip_new_dir,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"),
          patches=(lambda: patch.object(zipfile.ZipFile, "testzip", return_value="broken.json"),))
    _same("consolidate, new month becomes a ZIP", _k, "newzip", _setup_new_month,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"))
    _same("consolidate, new ZIP fails its check", _k, "badnew", _setup_new_month,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"),
          patches=(lambda: patch.object(zipfile.ZipFile, "testzip", return_value="broken.json"),))
    _same("consolidate, edge cases (empty month, current and later month, stray file)", _k, "edges", _setup_edges,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"))
    _same("consolidate, no backup folder at all", _k, "nofolder", lambda k: None,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"))
    _same("consolidate, integrity failure in two months", _k, "twomonths", _setup_two_months,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09"),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09"),
          patches=(lambda: patch.object(zipfile.ZipFile, "testzip", return_value="bad"),))
    _same("consolidate, failing force-replace does not stop the next month", _k, "forcetwo", _setup_force_two_months,
          lambda k: getattr(k["mod"], k["cons"])(current_month="2024-09", force_filenames={_fn(k, "2024-05-27")}),
          lambda k: common.consolidate_months(_kind(k), current_month="2024-09", force_filenames={_fn(k, "2024-05-27")}),
          patches=(lambda: patch("os.replace", side_effect=OSError("locked")),))

    # backup of one day -----------------------------------------------------------------------
    _same("backup of a rewritten day in a completed month", _k, "bk_rewritten", _setup_rewritten_day,
          lambda k: getattr(k["mod"], k["backup"])("2024-08-27"),
          lambda k: common.backup_file(_kind(k), "2024-08-27"))
    _same("backup with force, unchanged content", _k, "bk_force", _setup_same_day,
          lambda k: getattr(k["mod"], k["backup"])("2024-08-27", force=True),
          lambda k: common.backup_file(_kind(k), "2024-08-27", force=True))
    _same("backup of a day in the open current month", _k, "bk_open", _setup_open_month,
          lambda k: getattr(k["mod"], k["backup"])(f"{_CUR}-01"),
          lambda k: common.backup_file(_kind(k), f"{_CUR}-01"))
    _same("backup of a day, write failure", _k, "bk_writefail", _setup_open_month,
          lambda k: getattr(k["mod"], k["backup"])(f"{_CUR}-01"),
          lambda k: common.backup_file(_kind(k), f"{_CUR}-01"),
          patches=(lambda: patch.object(Path, "write_bytes", side_effect=OSError("disk full")),))
    # the message for a missing source file is worded the same for both kinds in the common module
    _same("backup of a day, source file missing (result and trees)", _k, "bk_missing", _setup_no_source,
          lambda k: getattr(k["mod"], k["backup"])("2024-08-27"),
          lambda k: common.backup_file(_kind(k), "2024-08-27"), logs=False)

    # backfill and the counters -----------------------------------------------------------------
    def _old_bf(k):
        r = getattr(k["mod"], k["backfill"])()
        return {"copied": r["copied"], "skipped": r["skipped"], "failed": r[k["bf_err"]],
                "needed": getattr(k["mod"], k["needed"])()}

    def _new_bf(k):
        r = common.backfill(_kind(k))
        return dict(r, needed=common.check_backfill_needed(_kind(k)))

    _same("backfill, mixed state (month folder, ZIP, missing, other ZIP, current month)", _k, "bf_mixed",
          _setup_backfill, _old_bf, _new_bf, logs=False)
    _same("backfill, copy failures", _k, "bf_fail", _setup_backfill,
          lambda k: getattr(k["mod"], k["backfill"])()[k["bf_err"]],
          lambda k: common.backfill(_kind(k))["failed"],
          patches=(lambda: patch.object(Path, "write_bytes", side_effect=OSError("disk full")),), logs=False)
    _same("backfill, no source folder", _k, "bf_none", lambda k: None,
          lambda k: (lambda r: (r["copied"], r["skipped"], r[k["bf_err"]]))(getattr(k["mod"], k["backfill"])()),
          lambda k: (lambda r: (r["copied"], r["skipped"], r["failed"]))(common.backfill(_kind(k))), logs=False)
    _same("check of files without a backup", _k, "needed", _setup_backfill,
          lambda k: getattr(k["mod"], k["needed"])(),
          lambda k: common.check_backfill_needed(_kind(k)))

    # refresh -------------------------------------------------------------------------------------
    def _old_rf(k):
        return {"stale_before": getattr(k["mod"], k["stale"])(), "result": getattr(k["mod"], k["refresh"])(),
                "stale_after": getattr(k["mod"], k["stale"])()}

    def _new_rf(k):
        return {"stale_before": common.check_stale(_kind(k)), "result": common.refresh(_kind(k)),
                "stale_after": common.check_stale(_kind(k))}

    _same("refresh, changed / unchanged / date mismatch / no backup / open month", _k, "rf", _setup_refresh,
          _old_rf, _new_rf)
    _same("refresh, a file that is not JSON is never copied over its backup", _k, "rf_json", _setup_refresh_invalid_json,
          _old_rf, _new_rf)
    _same("refresh, a ZIP that cannot be read counts as no backup", _k, "rf_badzip", _setup_refresh_badzip,
          _old_rf, _new_rf)
    _same("refresh, copy failures are counted", _k, "rf_fail", _setup_refresh,
          lambda k: getattr(k["mod"], k["refresh"])(),
          lambda k: common.refresh(_kind(k)),
          patches=(lambda: patch.object(Path, "write_bytes", side_effect=OSError("disk full")),))

    # read_copy gives what the restore of garmin_backup writes back (raw only: source has no restore) --
    if _k["name"] == "raw":
        def _setup_restore(k):
            _bkd(k).mkdir(parents=True)
            _zip_write(_bkd(k) / f"{k['zip_prefix']}2024-08.zip", {_fn(k, "2024-08-02"): "zip-02", _fn(k, "2024-08-03"): "zip-03-old"})
            _month(_bkd(k), k["prefix"], "2024-08", ["01", "03"], content="dir")
            (_bkd(k) / "2024-08" / _fn(k, "2024-08-03")).write_text("dir-03-new", encoding="utf-8")

        with _isolated_log_env("bc_restore_raw"):
            _setup_restore(_k)
            _res = _old_raw.restore_raw_days(["2024-08-01", "2024-08-02", "2024-08-03", "2024-08-04"])
            _restored = {d: (_src(_k) / _fn(_k, d)).read_bytes() for d in _res["restored"]}
            _copies = {d: common.read_copy(_kind(_k), _fn(_k, d)) for d in ("2024-08-01", "2024-08-02", "2024-08-03", "2024-08-04")}
        check("B raw read_copy: the same bytes garmin_backup.restore_raw_days writes back, month folder before ZIP",
              sorted(_restored) == ["2024-08-01", "2024-08-02", "2024-08-03"]
              and all(_copies[d] == b for d, b in _restored.items()) and _restored["2024-08-03"] == b"dir-03-new")
        check("B raw read_copy: a day restore_raw_days reports as failed has no copy", _copies["2024-08-04"] is None and _res["failed"] == ["2024-08-04"])

    # the one difference that is wanted: the validity check of the kind -------------------------
    _o = _run(_k, "valid", "old", _setup_refresh, lambda k: getattr(k["mod"], k["refresh"])())
    check(f"B {_k['name']} refresh: the number of unreadable files comes from the kind's own validity check",
          _o[0]["unreadable"] == (1 if _k["name"] == "raw" else 0))


summary()
