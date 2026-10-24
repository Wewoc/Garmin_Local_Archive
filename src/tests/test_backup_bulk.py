#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_backup_bulk.py — garmin_backup_bulk (v1.7.6.2)

Run from the project folder:
    python tests/test_backup_bulk.py

Synthetic bulk stores in fresh folders; garmin_config's paths are pointed at them for the
duration of each block. Nothing here touches a real archive.
"""

import ast
import contextlib
import hashlib
import json
import shutil
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_backup_bulk as bb
import garmin_backup_common as common

_CUR = date.today().strftime("%Y-%m")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _BLog:
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


@contextlib.contextmanager
def _env(name):
    """Fresh bulk store + backup folders; garmin_config's bulk paths point at them meanwhile."""
    base = _TMPDIR / f"bb_{name}"
    shutil.rmtree(base, ignore_errors=True)
    paths = {
        "BULK_DIR": base / "bulk",
        "BULK_RAW_DIR": base / "bulk" / "raw",
        "BULK_AGG_DIR": base / "bulk" / "aggregates",
        "BULK_SOURCE_DIR": base / "bulk" / "source",
        "BULK_BACKUP_DIR": base / "backup" / "bulk",
        "BULK_RAW_BACKUP_DIR": base / "backup" / "bulk" / "raw",
        "BULK_AGG_BACKUP_DIR": base / "backup" / "bulk" / "aggregates",
        "BULK_SOURCE_BACKUP_DIR": base / "backup" / "bulk" / "source",
    }
    with contextlib.ExitStack() as stack:
        for k, v in paths.items():
            stack.enter_context(patch.object(cfg, k, v))
        yield base


@contextlib.contextmanager
def _logged():
    rec = _BLog()
    saved = (bb.log, common.log)
    bb.log = common.log = rec
    try:
        yield rec.calls
    finally:
        bb.log, common.log = saved


def _dj(day, v):
    return json.dumps({"date": day, "v": v})


def _put_day(day, v="x", agg=False):
    d = cfg.BULK_AGG_DIR if agg else cfg.BULK_RAW_DIR
    pre = cfg.BULK_AGG_FILE_PREFIX if agg else cfg.BULK_FILE_PREFIX
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pre}{day}.json").write_text(_dj(day, v), encoding="utf-8")


def _put_original(data: bytes, suffix=".fit"):
    h = hashlib.sha256(data).hexdigest()
    d = cfg.BULK_SOURCE_DIR / h[:2]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{h}{suffix}").write_bytes(data)
    return h


def _original_with_prefix(prefix, tag, suffix=".fit"):
    """An original whose hash starts with `prefix` (content found by trying numbers)."""
    n = 0
    while True:
        data = f"{tag}-{n}".encode()
        if hashlib.sha256(data).hexdigest().startswith(prefix):
            return _put_original(data, suffix), data
        n += 1


def _zip_names(path):
    with zipfile.ZipFile(path) as z:
        return sorted(z.namelist())


def _zip_entries(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _tree(root):
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = None if p.is_dir() else p.read_bytes()
    return out


def _tmp_files(root):
    return [p for p in root.rglob("*.tmp")] if root.exists() else []


# ══════════════════════════════════════════════════════════════════════════════
section("A. garmin_backup_bulk — module, kinds, listing")
# ══════════════════════════════════════════════════════════════════════════════

_text = Path(bb.__file__).read_text(encoding="utf-8")
_top_imports = set()
for _node in ast.parse(_text).body:
    if isinstance(_node, ast.Import):
        _top_imports |= {a.name.split(".")[0] for a in _node.names}
    elif isinstance(_node, ast.ImportFrom):
        _top_imports.add((_node.module or "").split(".")[0])
check("A1 imports at module level: stdlib and garmin_backup_common only (garmin_config is imported lazily)",
      _top_imports <= {"logging", "os", "re", "zipfile", "pathlib", "garmin_backup_common"}
      and "garmin_config" not in _top_imports and "garmin_backup_common" in _top_imports)

with _env("kinds"):
    _kinds = bb.day_kinds()
    check("A2 day_kinds: two kinds, built from the paths of garmin_config at call time",
          sorted(_kinds) == ["aggregates", "raw"]
          and _kinds["raw"].src_dir == cfg.BULK_RAW_DIR and _kinds["raw"].backup_dir == cfg.BULK_RAW_BACKUP_DIR
          and _kinds["aggregates"].src_dir == cfg.BULK_AGG_DIR
          and _kinds["aggregates"].backup_dir == cfg.BULK_AGG_BACKUP_DIR)
    check("A2 day_kinds: prefixes and ZIP names",
          _kinds["raw"].prefix == "garmin_bulk_" and _kinds["raw"].zip_path("2024-08").name == "bulk_raw_backup_2024-08.zip"
          and _kinds["aggregates"].prefix == "garmin_bulk_agg_"
          and _kinds["aggregates"].zip_path("2024-08").name == "bulk_aggregates_backup_2024-08.zip")

with _env("listing"):
    h1, _ = _original_with_prefix("ab", "one")
    h2, _ = _original_with_prefix("ab", "two", ".json")
    h3, _ = _original_with_prefix("cd", "three")
    _sd = cfg.BULK_SOURCE_DIR
    (_sd / "ab" / f"{h1}.fit.tmp").write_bytes(b"left over of the writer")
    (_sd / "ab" / ("a" * 63 + ".fit")).write_bytes(b"63 characters")
    (_sd / "ab" / (h1.upper() + ".fit")).write_bytes(b"upper case")
    (_sd / "ab" / "notes.txt").write_bytes(b"x")
    (_sd / "zz").mkdir()
    (_sd / "zz" / ("z" * 64 + ".fit")).write_bytes(b"folder is not a prefix")
    (_sd / "cd" / ("ab" + "0" * 62 + ".fit")).write_bytes(b"name does not start with its folder")
    (_sd / "stray.fit").write_bytes(b"file in the root")
    _g = bb._original_groups()
    check("A3 listing: only <xx>/<sha256>.fit|.json whose name starts with its folder, grouped by prefix",
          sorted(_g) == ["ab", "cd"] and sorted(p.name for p in _g["ab"]) == sorted([f"{h1}.fit", f"{h2}.json"])
          and [p.name for p in _g["cd"]] == [f"{h3}.fit"])
with _env("listing_none"):
    check("A3 listing: no bulk/source folder -> {}", bb._original_groups() == {})


# ══════════════════════════════════════════════════════════════════════════════
section("B. garmin_backup_bulk — backup_all on a mixed store")
# ══════════════════════════════════════════════════════════════════════════════

with _env("mixed"), _logged() as _calls:
    for _d in ("2024-08-01", "2024-08-02", f"{_CUR}-01"):
        _put_day(_d, "r")
    for _d in ("2024-08-01", f"{_CUR}-01"):
        _put_day(_d, "a", agg=True)
    _o1, _ = _original_with_prefix("ab", "m1")
    _o2, _ = _original_with_prefix("ab", "m2", ".json")
    _o3, _ = _original_with_prefix("cd", "m3")

    _need = bb.check_needed()
    check("B1 check_needed before the first backup: everything is missing",
          _need == {"raw": 3, "aggregates": 2, "source": 3, "damaged_zips": 0})
    _r = bb.backup_all()
    check("B2 backup_all: ok, not stopped", _r["ok"] is True and _r["stopped"] is False)
    check("B2 backup_all: day files copied (raw 3, aggregates 2), nothing refreshed or failed",
          (_r["raw"]["copied"], _r["raw"]["refreshed"], _r["raw"]["failed"], _r["raw"]["errors"]) == (3, 0, 0, 0)
          and (_r["aggregates"]["copied"], _r["aggregates"]["failed"]) == (2, 0))
    check("B2 backup_all: originals copied (3), none present before, none failed",
          _r["source"] == {"copied": 3, "present": 0, "failed": 0, "damaged_zips": 0, "stopped": False})
    _bk = cfg.BULK_BACKUP_DIR
    check("B3 raw day files: the completed month is a ZIP, the open month a folder",
          _zip_names(_bk / "raw" / "bulk_raw_backup_2024-08.zip") == ["garmin_bulk_2024-08-01.json", "garmin_bulk_2024-08-02.json"]
          and (_bk / "raw" / _CUR / f"garmin_bulk_{_CUR}-01.json").is_file()
          and not (_bk / "raw" / "2024-08").exists())
    check("B3 aggregates: their own folder, own ZIP name, own file prefix",
          _zip_names(_bk / "aggregates" / "bulk_aggregates_backup_2024-08.zip") == ["garmin_bulk_agg_2024-08-01.json"]
          and (_bk / "aggregates" / _CUR / f"garmin_bulk_agg_{_CUR}-01.json").is_file())
    check("B3 originals: one ZIP per hash prefix with the unchanged bytes, named <hash>.<suffix>",
          sorted(p.name for p in (_bk / "source").iterdir()) == ["ab.zip", "cd.zip"]
          and _zip_names(_bk / "source" / "ab.zip") == sorted([f"{_o1}.fit", f"{_o2}.json"])
          and _zip_entries(_bk / "source" / "cd.zip")[f"{_o3}.fit"]
          == (cfg.BULK_SOURCE_DIR / _o3[:2] / f"{_o3}.fit").read_bytes())
    check("B4 check_needed after the backup: nothing", bb.check_needed() == {"raw": 0, "aggregates": 0, "source": 0, "damaged_zips": 0})
    check("B4 no .tmp file is left", _tmp_files(_bk) == [])
    check("B5 the log reports what was done (one line per part with work)",
          sum(1 for lv, m in _calls if lv == "info" and m.startswith("  backup_bulk: ")) >= 3)

    # -- a second run changes nothing --------------------------------------------------------------
    _before = _tree(_bk)
    _calls.clear()
    _r2 = bb.backup_all()
    check("B6 a second run: ok, nothing copied, refreshed or failed",
          _r2["ok"] is True and (_r2["raw"]["copied"], _r2["raw"]["refreshed"]) == (0, 0)
          and (_r2["aggregates"]["copied"], _r2["aggregates"]["refreshed"]) == (0, 0)
          and _r2["source"]["copied"] == 0 and _r2["source"]["present"] == 3)
    check("B6 a second run: the backup folder is byte-identical", _tree(_bk) == _before)
    check("B6 a second run: nothing to report at info level", not [m for lv, m in _calls if lv == "info"])

    # -- a day file that changed -----------------------------------------------------------------
    _put_day("2024-08-02", "r-changed")
    check("B7 a changed day file is counted by check_needed", bb.check_needed()["raw"] == 1)
    _r3 = bb.backup_all()
    check("B7 backup_all refreshes exactly that file",
          _r3["raw"]["refreshed"] == 1 and _r3["raw"]["copied"] == 0 and _r3["ok"] is True)
    check("B7 the ZIP entry holds the new version, the other entry is untouched",
          json.loads(_zip_entries(_bk / "raw" / "bulk_raw_backup_2024-08.zip")["garmin_bulk_2024-08-02.json"])["v"] == "r-changed"
          and json.loads(_zip_entries(_bk / "raw" / "bulk_raw_backup_2024-08.zip")["garmin_bulk_2024-08-01.json"])["v"] == "r")
    check("B7 afterwards nothing is needed", bb.check_needed()["raw"] == 0)

    # -- new originals in an existing prefix ZIP and in a new one -----------------------------------
    _ab_before = _zip_entries(_bk / "source" / "ab.zip")
    _o4, _ = _original_with_prefix("ab", "m4")
    _o5, _ = _original_with_prefix("ef", "m5")
    check("B8 check_needed counts the two new originals", bb.check_needed()["source"] == 2)
    _r4 = bb.backup_originals()
    check("B8 backup_originals: 2 copied, 3 present",
          (_r4["copied"], _r4["present"], _r4["failed"]) == (2, 3, 0))
    _ab_after = _zip_entries(_bk / "source" / "ab.zip")
    check("B8 the existing prefix ZIP keeps its old entries byte for byte and gains the new one",
          all(_ab_after[k] == v for k, v in _ab_before.items()) and f"{_o4}.fit" in _ab_after and len(_ab_after) == 3)
    check("B8 a new prefix gets a new ZIP; no .tmp is left",
          _zip_names(_bk / "source" / "ef.zip") == [f"{_o5}.fit"] and _tmp_files(_bk) == [])


# ══════════════════════════════════════════════════════════════════════════════
section("C. garmin_backup_bulk — damaged ZIPs, failures, stop")
# ══════════════════════════════════════════════════════════════════════════════

# -- a ZIP of a prefix that is not a ZIP: not touched, reported, the other prefixes go on ------
with _env("damaged_garbage"), _logged() as _calls:
    _a, _ = _original_with_prefix("ab", "d1")
    _b, _ = _original_with_prefix("ab", "d2")
    _c, _ = _original_with_prefix("cd", "d3")
    (cfg.BULK_SOURCE_BACKUP_DIR).mkdir(parents=True)
    _garbage = b"this is not a zip " * 20
    (cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip").write_bytes(_garbage)
    check("C1 check_needed: a damaged prefix ZIP is counted, all files of the prefix are needed",
          bb.check_needed()["damaged_zips"] == 1 and bb.check_needed()["source"] == 3)
    _r = bb.backup_originals()
    check("C1 backup_originals: damaged_zips 1, the 2 files of the prefix failed, the other prefix is copied",
          (_r["damaged_zips"], _r["failed"], _r["copied"]) == (1, 2, 1))
    check("C1 the damaged ZIP is byte-identical afterwards (nothing appended, nothing replaced)",
          (cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip").read_bytes() == _garbage)
    check("C1 the other prefix has its ZIP", _zip_names(cfg.BULK_SOURCE_BACKUP_DIR / "cd.zip") == [f"{_c}.fit"])
    check("C1 the error names the ZIP, the prefix and the reason",
          any(lv == "error" and "ab.zip is damaged (BadZipFile" in m and "ab/" in m for lv, m in _calls))
    check("C1 backup_all reports ok False", bb.backup_all()["ok"] is False)
    check("C1 no .tmp is left", _tmp_files(cfg.BULK_BACKUP_DIR) == [])

# -- a truncated real ZIP (the case that loses entries silently with "a" mode) --------------------
with _env("damaged_truncated"):
    _a, _ = _original_with_prefix("ab", "t1")
    _b, _ = _original_with_prefix("ab", "t2")
    bb.backup_originals()
    _zp = cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip"
    _cut = _zp.read_bytes()[:-40]
    _zp.write_bytes(_cut)
    _c, _ = _original_with_prefix("ab", "t3")
    _r = bb.backup_originals()
    check("C2 truncated prefix ZIP + a new original: reported as damaged, not rewritten, nothing lost silently",
          _r["damaged_zips"] == 1 and _r["copied"] == 0 and _zp.read_bytes() == _cut)

# -- an entry that fails its check is found when the ZIP is about to be rewritten --------------------
with _env("damaged_crc"):
    _a, _da = _original_with_prefix("ab", "c1")
    bb.backup_originals()
    _zp = cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip"
    _raw = bytearray(_zp.read_bytes())
    # the entry is stored deflated; flip a byte in the middle of its data (the directory stays readable)
    _raw[len(_raw) // 3] ^= 0xFF
    _zp.write_bytes(bytes(_raw))
    _ok_dir = bb._zip_names(_zp)[0] is not None
    _c, _ = _original_with_prefix("ab", "c2")
    _r = bb.backup_originals()
    check("C3 an entry that fails its check, directory readable: found before rewriting, ZIP not touched",
          _ok_dir and _r["damaged_zips"] == 1 and _r["copied"] == 0 and _zp.read_bytes() == bytes(_raw))

# -- a failing swap leaves the old ZIP and no .tmp ----------------------------------------------
with _env("swapfail"), _logged() as _calls:
    _a, _ = _original_with_prefix("ab", "s1")
    bb.backup_originals()
    _zp = cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip"
    _old = _zp.read_bytes()
    _b, _ = _original_with_prefix("ab", "s2")
    with patch("os.replace", side_effect=OSError("locked")):
        _r = bb.backup_originals()
    check("C4 a failing swap: the old ZIP is byte-identical, the file counts as failed, nothing raised",
          _zp.read_bytes() == _old and _r["failed"] == 1 and _r["copied"] == 0)
    check("C4 the temp ZIP is removed", _tmp_files(cfg.BULK_BACKUP_DIR) == [])
    check("C4 the error names the prefix and the error type",
          any(lv == "error" and "ab/" in m and "OSError" in m for lv, m in _calls))
    _r = bb.backup_originals()
    check("C4 the next run makes it good", _r["copied"] == 1 and _r["failed"] == 0)

# -- a file that cannot be added is left out and counted; nothing at all can be added -> no empty ZIP
with _env("addfail"), _logged():
    _a, _ = _original_with_prefix("ab", "f1")
    with patch.object(zipfile.ZipFile, "write", side_effect=OSError("cannot read")):
        _r = bb.backup_originals()
    check("C5 no file can be added: counted failed, no ZIP and no .tmp is left behind",
          _r["failed"] == 1 and _r["copied"] == 0
          and not (cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip").exists() and _tmp_files(cfg.BULK_BACKUP_DIR) == [])
    check("C5 the next run backs it up", bb.backup_originals()["copied"] == 1)

# -- a new ZIP that fails its check is not swapped in -------------------------------------------
with _env("verifyfail"), _logged():
    _original_with_prefix("ab", "v1")
    with patch.object(zipfile.ZipFile, "testzip", return_value="bad.fit"):
        _r = bb.backup_originals()
    check("C5b a new ZIP that fails its check is not swapped in: failed, no ZIP and no .tmp left, nothing raised",
          _r["failed"] == 1 and _r["copied"] == 0 and not (cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip").exists()
          and _tmp_files(cfg.BULK_BACKUP_DIR) == [])

# -- failures of the day-file part make ok False ---------------------------------------------------------
with _env("dayfail"), _logged():
    _put_day("2024-08-01")
    with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
        _r = bb.backup_all()
    check("C5c a day file that cannot be copied: counted failed, ok False, nothing raised",
          _r["raw"]["failed"] == 1 and _r["raw"]["copied"] == 0 and _r["ok"] is False)
    _r = bb.backup_all()
    check("C5c the next run copies it and is ok again", _r["raw"]["copied"] == 1 and _r["ok"] is True)
    _put_day("2024-08-01", "changed")
    with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
        _r = bb.backup_all()
    check("C5c a changed day file whose copy cannot be refreshed counts as an error, ok False",
          _r["raw"]["errors"] == 1 and _r["raw"]["refreshed"] == 0 and _r["ok"] is False)
    check("C5c ... and is still reported as needed", bb.check_needed()["raw"] == 1)

# -- progress of the originals (v1.7.6.2): a line at every 10 % of the folders, only when something was copied --------
def _progress_lines(calls):
    return [m for lv, m in calls if lv == "info" and "originals " in m and " % (" in m]


with _env("progress"), _logged() as _calls:
    for _n in range(10):
        _original_with_prefix(f"a{_n}", f"progress{_n}")
    bb.backup_originals()
    _pl = _progress_lines(_calls)
    check("C12 10 folders with work: a line at 10, 20 ... 100 %",
          [int(m.split("originals ")[1].split(" %")[0]) for m in _pl] == list(range(10, 101, 10)))
    check("C12 ... and the lines name how far it is", _pl[0].endswith("(1 of 10 folders)") and _pl[-1].endswith("(10 of 10 folders)"))
    _calls.clear()
    bb.backup_originals()
    check("C12 a second run with nothing to do says nothing about progress", _progress_lines(_calls) == [])

with _env("progress_damaged"), _logged() as _calls:
    for _n in range(3):
        _original_with_prefix(f"b{_n}", f"progressd{_n}")
    (cfg.BULK_SOURCE_BACKUP_DIR).mkdir(parents=True)
    for _n in range(3):
        (cfg.BULK_SOURCE_BACKUP_DIR / f"b{_n}.zip").write_bytes(b"not a zip")
    _r = bb.backup_originals()
    check("C12 only damaged ZIPs (nothing copied): no progress lines, so a ZIP that fails at every start does not add noise",
          _r["copied"] == 0 and _r["damaged_zips"] == 3 and _progress_lines(_calls) == [])

with _env("progress_stop"), _logged() as _calls:
    for _n in range(10):
        _original_with_prefix(f"c{_n}", f"progresss{_n}")
    _asks = []

    def _stop_on_fourth():
        _asks.append(1)
        return len(_asks) > 3

    _r = bb.backup_originals(should_stop=_stop_on_fourth)
    _pl = _progress_lines(_calls)
    check("C12 stopped after 3 folders: lines up to 30 %, no 100 % line for a run that did not finish",
          _r["stopped"] is True and _r["copied"] == 3 and len(_pl) == 3 and _pl[-1].endswith("(3 of 10 folders)"))

# -- stop requests ---------------------------------------------------------------------------------
with _env("stop"):
    for _p in ("ab", "cd", "ef"):
        _original_with_prefix(_p, "stop")
    _put_day("2024-08-01")
    _r = bb.backup_all(should_stop=lambda: True)
    check("C6 a stop before anything: stopped, nothing written, not a failure",
          _r["stopped"] is True and _r["ok"] is True and not cfg.BULK_BACKUP_DIR.exists())
    _asks = []

    def _stop_after_first():
        _asks.append(1)
        return len(_asks) > 1        # backup_originals asks once per prefix: the first goes on, the second stops

    _r = bb.backup_originals(should_stop=_stop_after_first)
    check("C6 a stop between two prefixes: the first is done, the others are not started",
          _r["stopped"] is True and _r["copied"] == 1 and len(list((cfg.BULK_SOURCE_BACKUP_DIR).glob("*.zip"))) == 1)

# -- a part that raises does not stop the others; nothing raises ----------------------------------------
with _env("raises"), _logged() as _calls:
    _put_day("2024-08-01")
    _original_with_prefix("ab", "rz")
    with patch.object(common, "backfill", side_effect=RuntimeError("boom")):
        _r = bb.backup_all()
    check("C7 a day-file part that raises: reported with its error type, ok False, the originals still run",
          _r["ok"] is False and _r["raw"] == {"error": "RuntimeError: boom"} and _r["source"]["copied"] == 1)
    check("C7 a part with nothing to do is not run: it does not raise and counts zero",
          _r["aggregates"]["copied"] == 0 and "error" not in _r["aggregates"])
    check("C7 the log names the part and the error type",
          any(lv == "error" and "raw could not be backed up: RuntimeError: boom" in m for lv, m in _calls))
with _env("cfgfail"), _logged():
    with patch.object(bb, "_cfg", side_effect=RuntimeError("no config")):
        _r = bb.backup_all()
        _o = bb.backup_originals()
        _n = bb.check_needed()
    check("C8 paths that cannot be read: backup_all, backup_originals and check_needed return, nothing raised",
          _r["ok"] is False and _o["failed"] >= 1 and _n == {"raw": 0, "aggregates": 0, "source": 0, "damaged_zips": 0})
with _env("empty"):
    _r = bb.backup_all()
    check("C9 no bulk store at all: ok, all zeros, no backup folder is created",
          _r["ok"] is True and _r["raw"]["copied"] == 0 and _r["aggregates"]["copied"] == 0
          and _r["source"]["copied"] == 0 and not cfg.BULK_BACKUP_DIR.exists()
          and bb.check_needed() == {"raw": 0, "aggregates": 0, "source": 0, "damaged_zips": 0})

# -- the stop check is asked only when there is work (a start with nothing to do looks like no backup at all) ----
with _env("stopasks"):
    _asks = []

    def _count():
        _asks.append(1)
        return False

    bb.backup_all(should_stop=_count)
    check("C9b no bulk store: the stop check is never asked", _asks == [])
    _put_day("2024-08-01")
    _original_with_prefix("ab", "sa")
    bb.backup_all(should_stop=_count)
    _first = len(_asks)
    check("C9b work to do: asked once before each part that has work (raw, and the one prefix of the originals)", _first == 2)
    bb.backup_all(should_stop=_count)
    check("C9b everything backed up: the stop check is not asked at all", len(_asks) == _first)

# -- the bulk store is only read ----------------------------------------------------------------------
with _env("readonly"):
    _put_day("2024-08-01")
    _put_day("2024-08-01", agg=True)
    _original_with_prefix("ab", "ro")
    _before = _tree(cfg.BULK_DIR)
    bb.backup_all()
    bb.backup_all()
    check("C10 backup_all leaves the bulk store byte-identical (nothing created, changed or removed)",
          _tree(cfg.BULK_DIR) == _before)


# ══════════════════════════════════════════════════════════════════════════════
section("D. garmin_backup_bulk — reading from the backup")
# ══════════════════════════════════════════════════════════════════════════════

with _env("read"), _logged() as _calls:
    _put_day("2024-08-01", "zip-day")
    _put_day(f"{_CUR}-01", "folder-day")
    _put_day("2024-08-01", "agg-day", agg=True)
    _oa, _data_a = _original_with_prefix("ab", "read-fit")
    _ob, _data_b = _original_with_prefix("ab", "read-json", ".json")
    bb.backup_all()
    check("D1 read_day_copy raw: from the ZIP of a completed month",
          json.loads(bb.read_day_copy("raw", "2024-08-01"))["v"] == "zip-day")
    check("D1 read_day_copy raw: from the folder of the open month",
          json.loads(bb.read_day_copy("raw", f"{_CUR}-01"))["v"] == "folder-day")
    check("D1 read_day_copy aggregates: its own backup", json.loads(bb.read_day_copy("aggregates", "2024-08-01"))["v"] == "agg-day")
    check("D1 read_day_copy: no copy -> None; an unknown kind is a ValueError",
          bb.read_day_copy("raw", "2024-08-09") is None)
    try:
        bb.read_day_copy("nonsense", "2024-08-01")
        _raised = False
    except ValueError:
        _raised = True
    check("D1 read_day_copy: unknown kind raises ValueError", _raised)
    check("D2 read_original_copy: the unchanged bytes, .fit and .json",
          bb.read_original_copy(_oa) == _data_a and bb.read_original_copy(_ob, ".json") == _data_b)
    check("D2 read_original_copy: wrong suffix, unknown hash, not a hash, bad suffix, no ZIP -> None",
          bb.read_original_copy(_oa, ".json") is None and bb.read_original_copy("ab" + "0" * 62) is None
          and bb.read_original_copy("xyz") is None and bb.read_original_copy(_oa, ".txt") is None
          and bb.read_original_copy("cd" + "0" * 62) is None and bb.read_original_copy(None) is None)
    (cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip").write_bytes(b"damaged")
    _calls.clear()
    check("D3 read_original_copy: a damaged prefix ZIP -> None and one warning with the error type",
          bb.read_original_copy(_oa) is None
          and [lv for lv, _ in _calls] == ["warning"] and "BadZipFile" in _calls[0][1])


summary()
