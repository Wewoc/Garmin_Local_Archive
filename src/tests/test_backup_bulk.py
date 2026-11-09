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


def _day_work():
    """The day files with work to do, per part: files without a backup copy plus files whose copy differs
    (what backup_all() looks at first; from garmin_backup_common, which is also what it asks)."""
    return {which: common.check_backfill_needed(kind) + common.check_stale(kind) for which, kind in bb.day_kinds().items()}


def _originals_work():
    """(originals that are not in their prefix ZIP, prefix ZIPs that cannot be read), read from the ZIP directories:
    a view of what backup_originals() would do that does not use its code."""
    missing = damaged = 0
    for prefix, files in bb._original_groups().items():
        zip_path = cfg.BULK_SOURCE_BACKUP_DIR / f"{prefix}.zip"
        names = None
        if zip_path.exists():
            try:
                with zipfile.ZipFile(zip_path) as z:
                    names = set(z.namelist())
            except (zipfile.BadZipFile, OSError):
                damaged += 1
                missing += len(files)
                continue
        missing += sum(1 for f in files if names is None or f.name not in names)
    return missing, damaged


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

    check("B1 before the first backup everything is missing: 3 intraday files, 2 aggregates files, 3 originals, no backup folder",
          _day_work() == {"raw": 3, "aggregates": 2} and _originals_work() == (3, 0) and not cfg.BULK_BACKUP_DIR.exists())
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
    check("B4 after the backup nothing is left to do", _day_work() == {"raw": 0, "aggregates": 0} and _originals_work() == (0, 0))
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
    check("B7 a changed day file is counted as work", _day_work()["raw"] == 1)
    _r3 = bb.backup_all()
    check("B7 backup_all refreshes exactly that file",
          _r3["raw"]["refreshed"] == 1 and _r3["raw"]["copied"] == 0 and _r3["ok"] is True)
    check("B7 the ZIP entry holds the new version, the other entry is untouched",
          json.loads(_zip_entries(_bk / "raw" / "bulk_raw_backup_2024-08.zip")["garmin_bulk_2024-08-02.json"])["v"] == "r-changed"
          and json.loads(_zip_entries(_bk / "raw" / "bulk_raw_backup_2024-08.zip")["garmin_bulk_2024-08-01.json"])["v"] == "r")
    check("B7 afterwards nothing is needed", _day_work()["raw"] == 0)

    # -- new originals in an existing prefix ZIP and in a new one -----------------------------------
    _ab_before = _zip_entries(_bk / "source" / "ab.zip")
    _o4, _ = _original_with_prefix("ab", "m4")
    _o5, _ = _original_with_prefix("ef", "m5")
    check("B8 the two new originals are counted as work", _originals_work() == (2, 0))
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
    check("C1 a damaged prefix ZIP is counted, all files of the prefix are needed (2 of ab, 1 of cd)",
          _originals_work() == (3, 1))
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
    check("C5c ... and is still counted as work", _day_work()["raw"] == 1)

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
    check("C8 paths that cannot be read: backup_all and backup_originals return, nothing raised",
          _r["ok"] is False and _o["failed"] >= 1)
with _env("empty"):
    _r = bb.backup_all()
    check("C9 no bulk store at all: ok, all zeros, no backup folder is created",
          _r["ok"] is True and _r["raw"]["copied"] == 0 and _r["aggregates"]["copied"] == 0
          and _r["source"]["copied"] == 0 and not cfg.BULK_BACKUP_DIR.exists()
          and _day_work() == {"raw": 0, "aggregates": 0} and _originals_work() == (0, 0))

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


# ══════════════════════════════════════════════════════════════════════════════
section("E. garmin_backup_bulk — mutation round v1.7.6.12 (survivors of the Cosmic Ray run)")
# ══════════════════════════════════════════════════════════════════════════════

# -- E1 progress with a folder count that is not 10 (with 10 folders `10 * done // 10` is `done`, so changed
#       factors passed by chance); 25 folders give a line at 3, 5, 8, 10 ... 25 folders ---------------------------
with _env("e_progress"), _logged() as _calls:
    for _i in range(25):
        _original_with_prefix(f"{0x10 + _i:02x}", f"e1-{_i}")
    bb.backup_originals()
    _pl = _progress_lines(_calls)
    _got = [(int(m.split("originals ")[1].split(" %")[0]), int(m.rsplit("(", 1)[1].split(" of")[0])) for m in _pl]
    check("E1 25 folders: a line whenever the tenth step grows (12 % at 3 folders ... 100 % at 25)",
          _got == [(12, 3), (20, 5), (32, 8), (40, 10), (52, 13), (60, 15), (72, 18), (80, 20), (92, 23), (100, 25)])

# -- E2 _zip_intact on its own: a ZIP that is garbage, missing, with a bad entry, and a good one ----------------------
_ew = _TMPDIR / "bb_e_zipintact"
shutil.rmtree(_ew, ignore_errors=True)
_ew.mkdir(parents=True)
with zipfile.ZipFile(_ew / "good.zip", "w", zipfile.ZIP_DEFLATED) as _z:
    _z.writestr("a.fit", b"hello" * 50)
with zipfile.ZipFile(_ew / "crc.zip", "w", zipfile.ZIP_STORED) as _z:
    _z.writestr("a.fit", b"hello" * 50)
_raw = bytearray((_ew / "crc.zip").read_bytes())
_raw[_raw.find(b"hello")] ^= 0xFF
(_ew / "crc.zip").write_bytes(bytes(_raw))
(_ew / "garbage.zip").write_bytes(b"not a zip " * 20)
check("E2 _zip_intact: a good ZIP -> (True, None)", bb._zip_intact(_ew / "good.zip") == (True, None))
_g = bb._zip_intact(_ew / "garbage.zip")
check("E2 _zip_intact: a file that is not a ZIP -> (False, 'BadZipFile: ...')",
      _g[0] is False and _g[1].startswith("BadZipFile: "))
_m = bb._zip_intact(_ew / "missing.zip")
check("E2 _zip_intact: a ZIP that is not there -> (False, 'FileNotFoundError: ...')",
      _m[0] is False and _m[1].startswith("FileNotFoundError: "))
check("E2 _zip_intact: an entry that fails its check -> (False, 'entry a.fit fails its check')",
      bb._zip_intact(_ew / "crc.zip") == (False, "entry a.fit fails its check"))

# -- E3 a file that cannot be added: the others of the prefix still go in (the failing one is the FIRST) -------------
with _env("e_addone"), _logged() as _calls:
    _a, _ = _original_with_prefix("ab", "e3a")
    _b, _ = _original_with_prefix("ab", "e3b")
    _first, _second = sorted([_a, _b])
    _orig_write = zipfile.ZipFile.write

    def _write_fail_first(self, filename, arcname=None, *args, **kwargs):
        if arcname == f"{_first}.fit":
            raise OSError("cannot read")
        return _orig_write(self, filename, arcname, *args, **kwargs)

    with patch.object(zipfile.ZipFile, "write", _write_fail_first):
        _r = bb.backup_originals()
    check("E3 the first of two files cannot be added: the second is in the ZIP, one copied, one failed",
          (_r["copied"], _r["failed"]) == (1, 1)
          and _zip_names(cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip") == [f"{_second}.fit"])
    check("E3 the log says which file could not be added to which ZIP",
          any(lv == "error" and f"{_first}.fit could not be added to ab.zip: OSError: cannot read" in m for lv, m in _calls))
    check("E3 no .tmp is left", _tmp_files(cfg.BULK_BACKUP_DIR) == [])

# -- E4 the swap fails and the temp ZIP cannot be removed either: the original error is reported, the cleanup only logged
with _env("e_cleanup"), _logged() as _calls:
    _original_with_prefix("ab", "e4")
    with patch("os.replace", side_effect=OSError("locked")), \
         patch.object(Path, "unlink", side_effect=OSError("cannot delete")):
        _r = bb.backup_originals()
    check("E4 swap and cleanup both fail: counted failed, nothing raised", _r["failed"] == 1 and _r["copied"] == 0)
    check("E4 the error names the swap error, not the cleanup error",
          any(lv == "error" and "ab/ could not be backed up: OSError: locked" in m for lv, m in _calls)
          and not any(lv == "error" and "cannot delete" in m for lv, m in _calls))
    check("E4 the failed cleanup is logged at debug level",
          any(lv == "debug" and "tmp zip cleanup failed for ab.zip: cannot delete" in m for lv, m in _calls))

# -- E5 what _original_groups() looks at: strays that sort before the prefix folders, a file named like a prefix,
#       a file of another prefix inside a folder -----------------------------------------------------------------
with _env("e_groups"):
    _h1, _ = _original_with_prefix("ab", "e5a")
    _hac, _ = _original_with_prefix("ac", "e5b")
    shutil.move(str(cfg.BULK_SOURCE_DIR / "ac" / f"{_hac}.fit"), str(cfg.BULK_SOURCE_DIR / "ab" / f"{_hac}.fit"))
    (cfg.BULK_SOURCE_DIR / "00").write_text("a file named like a prefix", encoding="utf-8")
    (cfg.BULK_SOURCE_DIR / "0stray").mkdir()
    _groups = {k: [p.name for p in v] for k, v in bb._original_groups().items()}
    check("E5 only the folder ab with its own file: strays before it do not end the listing, a file named '00' is no folder, "
          "a file whose name starts with another prefix is left out",
          _groups == {"ab": [f"{_h1}.fit"]})

# -- E6 originals that cannot be listed: exactly one failure, the rest zero ---------------------------------------
with _env("e_listfail"), _logged():
    with patch.object(bb, "_original_groups", side_effect=RuntimeError("cannot list")):
        _r = bb.backup_originals()
    check("E6 the listing raises: {copied 0, present 0, failed 1, damaged_zips 0, stopped False}",
          _r == {"copied": 0, "present": 0, "failed": 1, "damaged_zips": 0, "stopped": False})

# -- E7 present = files - missing with numbers whose XOR/difference differ (5 files, 2 new) -----------------------
with _env("e_present"):
    for _i in range(3):
        _original_with_prefix("ab", f"e7-old-{_i}")
    bb.backup_originals()
    for _i in range(2):
        _original_with_prefix("ab", f"e7-new-{_i}")
    _r = bb.backup_originals()
    check("E7 5 files in the prefix, 3 already in the ZIP: present 3, copied 2, failed 0",
          (_r["present"], _r["copied"], _r["failed"]) == (3, 2, 0))

# -- E8 failed = missing - added with 5 missing, 3 of them not addable (5 ^ 2, 5 % 2 and 5 >> 2 are not 3) -------
with _env("e_failcount"), _logged():
    _hs = [_original_with_prefix("ab", f"e8-{_i}")[0] for _i in range(5)]
    _bad = {f"{h}.fit" for h in sorted(_hs)[:3]}
    _orig_write8 = zipfile.ZipFile.write

    def _write_fail_three(self, filename, arcname=None, *args, **kwargs):
        if arcname in _bad:
            raise OSError("cannot read")
        return _orig_write8(self, filename, arcname, *args, **kwargs)

    with patch.object(zipfile.ZipFile, "write", _write_fail_three):
        _r = bb.backup_originals()
    check("E8 5 missing, 2 added: copied 2, failed 3", (_r["copied"], _r["failed"]) == (2, 3))

# -- E9 a ZIP entry named <hash>.txt is never handed out ------------------------------------------------------------
with _env("e_suffix"):
    _h, _ = _original_with_prefix("ab", "e9")
    bb.backup_originals()
    with zipfile.ZipFile(cfg.BULK_SOURCE_BACKUP_DIR / "ab.zip", "a") as _z:
        _z.writestr(f"{_h}.txt", b"secret")
    check("E9 read_original_copy: a valid hash with an entry of the wrong suffix in the ZIP -> None",
          bb.read_original_copy(_h, ".txt") is None and bb.read_original_copy(_h) is not None)

# -- E10 backup_all: paths that cannot be read -> the exact failure shape, not stopped --------------------------
with _env("e_cfgshape"), _logged():
    with patch.object(bb, "_cfg", side_effect=RuntimeError("no config")):
        _r = bb.backup_all()
    check("E10 paths that cannot be read: the three parts carry the error, ok False, stopped False",
          _r == {"raw": {"error": "no config"}, "aggregates": {"error": "no config"},
                 "source": {"error": "no config"}, "ok": False, "stopped": False})

# -- E11 backup_all: a part of its own that only refreshes has the exact counters ---------------------------------
with _env("e_refreshshape"), _logged():
    _put_day("2024-08-01")
    bb.backup_all()
    _put_day("2024-08-01", "changed")
    _r = bb.backup_all()
    check("E11 refresh only: {copied 0, skipped 0, failed 0, refreshed 1, unreadable 0, errors 0}",
          _r["raw"] == {"copied": 0, "skipped": 0, "failed": 0, "refreshed": 1, "unreadable": 0, "errors": 0})

# -- E12 backup_all: the stop check before a part that only has something to refresh -------------------------------
with _env("e_stoprefresh"):
    _put_day("2024-08-01")
    bb.backup_all()
    _put_day("2024-08-01", "changed")
    _r = bb.backup_all(should_stop=lambda: True)
    check("E12 only a changed day file (nothing missing): the stop is honoured, nothing refreshed, originals not started",
          _r["stopped"] is True and "source" not in _r and _day_work()["raw"] == 1)

# -- E13 backup_all: a stop before the first part ends the run there; day files only, no originals -------------
with _env("e_stopfirst"):
    _put_day("2024-08-01")
    _put_day("2024-08-01", agg=True)
    _asks = []

    def _stop_counting():
        _asks.append(1)
        return True

    _r = bb.backup_all(should_stop=_stop_counting)
    check("E13 stop answered at the first part: stopped True (also with no originals to ask about), asked once, "
          "the aggregates part is not looked at",
          _r["stopped"] is True and len(_asks) == 1 and "aggregates" not in _r and not cfg.BULK_BACKUP_DIR.exists())


# -- E14 backup_all: the info line and ok for every single counter of a part ----------------------------------------
def _part_run(missing, outdated, unreadable, backfill_ret, refresh_ret):
    with _env("e_partline"), _logged() as calls, \
         patch.object(common, "check_backfill_needed", return_value=missing), \
         patch.object(common, "find_outdated", return_value=(outdated, unreadable)), \
         patch.object(common, "backfill", return_value=backfill_ret), \
         patch.object(common, "refresh", return_value=refresh_ret):
        r = bb.backup_all()
    return r, [m for lv, m in calls if lv == "info" and "raw —" in m]


_bf0 = {"copied": 0, "skipped": 0, "failed": 0}
_rf0 = {"refreshed": 0, "unreadable": 0, "errors": 0}
_cases = [
    ("copied", 1, [], [], {"copied": 1, "skipped": 0, "failed": 0}, _rf0, "1 copied, 0 refreshed, 0 unreadable, 0 failed", True),
    ("refreshed", 0, [1], [], _bf0, {"refreshed": 1, "unreadable": 0, "errors": 0}, "0 copied, 1 refreshed, 0 unreadable, 0 failed", True),
    ("failed", 1, [], [], {"copied": 0, "skipped": 0, "failed": 1}, _rf0, "0 copied, 0 refreshed, 0 unreadable, 1 failed", False),
    ("errors", 0, [1], [], _bf0, {"refreshed": 0, "unreadable": 0, "errors": 1}, "0 copied, 0 refreshed, 0 unreadable, 1 failed", False),
    ("unreadable", 0, [], [1], _bf0, {"refreshed": 0, "unreadable": 1, "errors": 0}, "0 copied, 0 refreshed, 1 unreadable, 0 failed", True),
    ("failed 3 + errors 1", 1, [1], [], {"copied": 0, "skipped": 0, "failed": 3}, {"refreshed": 0, "unreadable": 0, "errors": 1},
     "0 copied, 0 refreshed, 0 unreadable, 4 failed", False),
]
for _name, _mi, _ou, _un, _bf, _rf, _text, _ok in _cases:
    _r, _lines = _part_run(_mi, _ou, _un, _bf, _rf)
    check(f"E14 only '{_name}' set: one info line '{_text}', ok {_ok}",
          len(_lines) == 1 and _lines[0].endswith(_text) and _r["ok"] is _ok)
_r, _lines = _part_run(0, [], [], _bf0, _rf0)
check("E14 nothing to do: no info line, ok True", _lines == [] and _r["ok"] is True)


# -- E15 backup_all: ok and the info line of the originals for each single counter -----------------------------------
def _src_run(src):
    with _env("e_srcline"), _logged() as calls, patch.object(bb, "backup_originals", return_value=src):
        r = bb.backup_all()
    return r, [m for lv, m in calls if lv == "info" and "originals —" in m]


_s0 = {"copied": 0, "present": 0, "failed": 0, "damaged_zips": 0, "stopped": False}
_r, _lines = _src_run(dict(_s0, failed=1))
check("E15 only 'failed' set: ok False and a line about the originals",
      _r["ok"] is False and len(_lines) == 1 and "0 copied, 0 present, 1 failed, 0 damaged ZIP(s)" in _lines[0])
_r, _lines = _src_run(dict(_s0, damaged_zips=1))
check("E15 only 'damaged_zips' set: ok False, no line (nothing copied, nothing failed)", _r["ok"] is False and _lines == [])
_r, _lines = _src_run(dict(_s0, copied=2, present=1))
check("E15 only 'copied' set: ok True and a line about the originals",
      _r["ok"] is True and len(_lines) == 1 and "2 copied, 1 present, 0 failed, 0 damaged ZIP(s)" in _lines[0])


summary()
