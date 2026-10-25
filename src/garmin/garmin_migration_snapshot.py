#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_migration_snapshot.py

TRACK-MIGRATION v1.7.6.3 — safety copy of the archive before the migration, and the way back.
Sole owner of garmin_data/backup/migration/.

Why a copy of its own: the raw backup keeps only the newest version of a day (v1.7.5.6), so once the
migration has rewritten a day the old, mixed version is in no backup any more. The snapshot is a
ZIP of everything the migration may touch: raw/, summary/ and log/quality_log.json, as they were.

  create_snapshot()   one ZIP per call, named migration_YYYY-MM-DD_HHMMSS.zip. All or nothing: the
                      ZIP is written to a temp file, read back and checked (every entry's size and
                      CRC against what was read from the archive, testzip, the manifest) and only
                      then put in place. A file that cannot be read, a stop request or too little
                      free space leaves no ZIP. Nothing in raw/, summary/ or the log is changed.
  verify_snapshot()   checks a ZIP the same way (and that it holds nothing but the known names).
  list_snapshots()    the ZIPs in the folder, oldest first (the oldest is the original state).
  restore_snapshot()  the way back: puts the files of the ZIP back, byte for byte, where they differ
                      from the archive's current files; days that are not in the ZIP stay as they
                      are. The quality-log entries of the restored days come back from the ZIP, the
                      entries of all other days stay (merged, saved once); the restored days get a
                      new last_checked so the MCP cache reads them again. A dry run only counts.

Delegation, nothing is written here directly except the ZIPs (Sole-Write-Authority):
  raw/ + summary/ → garmin_writer.restore_day_files (exact bytes; the raw backup follows)
  quality log     → garmin_quality (_load/_save_quality_log, touch_last_checked), under QUALITY_LOCK

The caller of restore_snapshot() must not hold QUALITY_LOCK (it is not re-entrant) and must make sure
nothing else writes to raw/ and summary/ meanwhile (timer paused, no sync running). No API call.
"""

import json
import logging
import os
import re
import shutil
import zipfile
import zlib
from datetime import date, datetime
from pathlib import Path

import garmin_config as cfg
import garmin_quality as quality
import garmin_writer as writer

log = logging.getLogger(__name__)

MANIFEST = "MANIFEST.json"
LOG_ENTRY = "log/quality_log.json"
_RAW_RE     = re.compile(r"raw/garmin_raw_(\d{4}-\d{2}-\d{2})\.json")
_SUMMARY_RE = re.compile(r"summary/garmin_(\d{4}-\d{2}-\d{2})\.json")
_NAME_RE    = re.compile(r"migration_\d{4}-\d{2}-\d{2}_\d{6}(_\d+)?\.zip")
_RAW_PREFIX, _SUMMARY_PREFIX = "garmin_raw_", "garmin_"
_FREE_SPACE_RESERVE = 10 * 1024 * 1024


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return len(value) == 10
    except (TypeError, ValueError):
        return False


def _day_files(folder: Path, prefix: str) -> list:
    """The day files of a folder as (date, path), sorted; names that are no day are ignored."""
    if not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob(f"{prefix}*.json")):
        d = f.stem[len(prefix):]
        if _valid_date(d):
            out.append((d, f))
    return out


def _entry_date(name: str):
    """(kind, date) for a snapshot entry name, kind in "raw" | "summary"; None for any other name."""
    for kind, rx in (("raw", _RAW_RE), ("summary", _SUMMARY_RE)):
        m = rx.fullmatch(name)
        if m and _valid_date(m.group(1)):
            return kind, m.group(1)
    return None


def _app_version() -> str:
    try:
        import version
        return str(version.APP_VERSION)
    except Exception:
        return "unknown"


def _cleanup(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  Create
# ══════════════════════════════════════════════════════════════════════════════

def create_snapshot(should_stop=None) -> dict:
    """
    Writes a ZIP of raw/, summary/ and log/quality_log.json to backup/migration/ (see the module
    docstring). Returns {"ok": bool, "path": Path | None, "raw": n, "summary": n, "log": bool,
    "bytes": size of the ZIP, "reason": text when not ok}. An archive with none of these files:
    ok, path None (nothing to back up).
    """
    sources = [(f"raw/{p.name}", p) for _, p in _day_files(cfg.RAW_DIR, _RAW_PREFIX)]
    n_raw = len(sources)
    sources += [(f"summary/{p.name}", p) for _, p in _day_files(cfg.SUMMARY_DIR, _SUMMARY_PREFIX)]
    n_summary = len(sources) - n_raw
    has_log = cfg.QUALITY_LOG_FILE.exists()
    if has_log:
        sources.append((LOG_ENTRY, cfg.QUALITY_LOG_FILE))
    result = {"ok": False, "path": None, "raw": n_raw, "summary": n_summary, "log": has_log, "bytes": 0}
    if not sources:
        return {**result, "ok": True, "reason": "nothing to back up"}

    folder = cfg.MIGRATION_BACKUP_DIR
    tmp = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        total = sum(p.stat().st_size for _, p in sources)
        free = shutil.disk_usage(folder).free
        if free < total + _FREE_SPACE_RESERVE:
            return {**result, "reason": f"not enough free space ({free // 1048576} MB free, "
                                        f"{total // 1048576} MB of files to back up)"}

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        final, n = folder / f"migration_{stamp}.zip", 1
        while final.exists():
            n += 1
            final = folder / f"migration_{stamp}_{n}.zip"
        tmp = folder / f".{final.name}.tmp"

        expected = {}
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for arc, path in sources:
                if should_stop is not None and should_stop():
                    zf.close()
                    _cleanup(tmp)
                    return {**result, "reason": "stopped"}
                data = path.read_bytes()
                expected[arc] = (len(data), zlib.crc32(data))
                zf.writestr(arc, data)
            manifest = {"created": datetime.now().isoformat(timespec="seconds"), "app_version": _app_version(),
                        "raw": n_raw, "summary": n_summary, "quality_log": has_log}
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2))

        problems = _check_zip(tmp, expected)
        if problems:
            _cleanup(tmp)
            return {**result, "reason": "the ZIP failed its check: " + "; ".join(problems[:3])}
        os.replace(tmp, final)
        tmp = None
        size = final.stat().st_size
        log.info(f"  Migration snapshot: {final.name} — {n_raw} raw, {n_summary} summary file(s)"
                 f"{', quality log' if has_log else ''}, {size // 1048576} MB")
        return {**result, "ok": True, "path": final, "bytes": size}
    except Exception as e:
        log.error(f"  Migration snapshot failed: {type(e).__name__}: {e}")
        if tmp is not None:
            _cleanup(tmp)
        return {**result, "reason": f"{type(e).__name__}: {e}"}


def _check_zip(path: Path, expected=None) -> list:
    """Problems of a snapshot ZIP (empty list = fine). With expected {name: (size, crc)} every entry is
    compared with what was read from the archive; without it only the structure and the CRCs are."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = {i.filename: i for i in zf.infolist()}
            bad = zf.testzip()
            problems = [f"damaged entry {bad}"] if bad else []
            if MANIFEST not in infos:
                problems.append("manifest missing")
            for name, info in infos.items():
                if name == MANIFEST or name == LOG_ENTRY or _entry_date(name):
                    continue
                problems.append(f"unexpected entry {name!r}")
            if expected is not None:
                if set(expected) | {MANIFEST} != set(infos):
                    problems.append("the entries differ from the files that were read")
                for name, (size, crc) in expected.items():
                    info = infos.get(name)
                    if info is not None and (info.file_size != size or info.CRC != crc):
                        problems.append(f"{name} differs from the file that was read")
            elif MANIFEST in infos:
                try:
                    man = json.loads(zf.read(MANIFEST))
                    n_raw = sum(1 for n in infos if (_entry_date(n) or ("", ""))[0] == "raw")
                    n_sum = sum(1 for n in infos if (_entry_date(n) or ("", ""))[0] == "summary")
                    if (man.get("raw"), man.get("summary"), bool(man.get("quality_log"))) != (n_raw, n_sum, LOG_ENTRY in infos):
                        problems.append("the manifest does not match the entries")
                except (ValueError, TypeError, AttributeError):
                    problems.append("manifest unreadable")
            return problems
    except (OSError, zipfile.BadZipFile) as e:
        return [f"not a readable ZIP ({type(e).__name__})"]


def verify_snapshot(path) -> dict:
    """Checks a snapshot ZIP: {"ok", "problems", "raw", "summary", "log", "created"}. Read-only."""
    path = Path(path)
    problems = _check_zip(path)
    out = {"ok": not problems, "problems": problems, "raw": 0, "summary": 0, "log": False, "created": None}
    if any(p.startswith("not a readable ZIP") for p in problems):
        return out
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            out["raw"] = sum(1 for n in names if (_entry_date(n) or ("", ""))[0] == "raw")
            out["summary"] = sum(1 for n in names if (_entry_date(n) or ("", ""))[0] == "summary")
            out["log"] = LOG_ENTRY in names
            if MANIFEST in names:
                out["created"] = json.loads(zf.read(MANIFEST)).get("created")
    except (OSError, zipfile.BadZipFile, ValueError, AttributeError):
        pass
    return out


def list_snapshots() -> list:
    """The snapshot ZIPs in backup/migration/, oldest first: [{"name", "path", "bytes"}]. Not checked."""
    folder = cfg.MIGRATION_BACKUP_DIR
    if not folder.exists():
        return []
    return [{"name": p.name, "path": p, "bytes": p.stat().st_size}
            for p in sorted(folder.glob("migration_*.zip")) if _NAME_RE.fullmatch(p.name)]


# ══════════════════════════════════════════════════════════════════════════════
#  Restore (the way back)
# ══════════════════════════════════════════════════════════════════════════════

def restore_snapshot(path, dry_run: bool = False, should_stop=None) -> dict:
    """
    Puts the files of a snapshot back (see the module docstring). The ZIP is checked first; a ZIP that
    fails its check changes nothing.

    Returns {"ok", "restored", "unchanged", "failed": [(date, what)], "log_entries", "log_saved",
    "stopped", "reason" (when the ZIP is refused), "problems"}. dry_run: nothing is written, "restored"
    counts the files that would be put back.
    """
    path = Path(path)
    res = {"ok": False, "restored": 0, "unchanged": 0, "failed": [], "log_entries": 0, "log_saved": None,
           "stopped": False}
    v = verify_snapshot(path)
    if not v["ok"]:
        return {**res, "reason": "snapshot_invalid", "problems": v["problems"]}

    restored_days = set()
    try:
        with zipfile.ZipFile(path) as zf:
            by_day = {}
            for name in zf.namelist():
                parsed = _entry_date(name)
                if parsed:
                    by_day.setdefault(parsed[1], {})[parsed[0]] = name
            for d in sorted(by_day):
                if should_stop is not None and should_stop():
                    res["stopped"] = True
                    break
                files = by_day[d]
                raw_b = zf.read(files["raw"]) if "raw" in files else None
                sum_b = zf.read(files["summary"]) if "summary" in files else None
                cur_raw = cfg.RAW_DIR / f"{_RAW_PREFIX}{d}.json"
                cur_sum = cfg.SUMMARY_DIR / f"{_SUMMARY_PREFIX}{d}.json"
                same_raw = raw_b is None or (cur_raw.exists() and cur_raw.read_bytes() == raw_b)
                same_sum = sum_b is None or (cur_sum.exists() and cur_sum.read_bytes() == sum_b)
                if same_raw and same_sum:
                    res["unchanged"] += 1
                    continue
                if dry_run:
                    res["restored"] += 1
                    continue
                if writer.restore_day_files(d, None if same_raw else raw_b, None if same_sum else sum_b):
                    res["restored"] += 1
                    restored_days.add(d)
                else:
                    res["failed"].append((d, "the files could not be written"))
            snap_log = None
            if LOG_ENTRY in zf.namelist() and not dry_run:
                try:
                    snap_log = json.loads(zf.read(LOG_ENTRY))
                except ValueError:
                    res["failed"].append(("quality_log", "the log in the snapshot is unreadable"))
    except (OSError, zipfile.BadZipFile) as e:
        return {**res, "reason": f"{type(e).__name__}: {e}"}

    if not dry_run and restored_days:
        res["log_entries"], res["log_saved"] = _merge_log(snap_log, restored_days)
        if res["log_saved"] is False:
            res["failed"].append(("quality_log", "the quality log could not be saved"))
    res["ok"] = not res["failed"] and not res["stopped"]
    log.info(f"  Migration snapshot restore{' (dry run)' if dry_run else ''}: {res['restored']} day(s) put back, "
             f"{res['unchanged']} unchanged, {len(res['failed'])} failed, {res['log_entries']} log entr"
             f"{'y' if res['log_entries'] == 1 else 'ies'} restored")
    return res


def _merge_log(snap_log, restored_days) -> tuple:
    """Entries of the restored days come back from the snapshot's log, all other entries stay; the restored
    days get a new last_checked. Returns (entries restored, saved: bool | None when there was nothing to do)."""
    with quality.QUALITY_LOCK:
        data = quality._load_quality_log()
        days, others = {}, []
        for e in data.get("days", []):
            if isinstance(e, dict) and isinstance(e.get("date"), str):
                days[e["date"]] = e
            else:
                others.append(e)          # an entry without a usable date is not ours to touch
        taken = 0
        if isinstance(snap_log, dict):
            for e in snap_log.get("days", []):
                if isinstance(e, dict) and e.get("date") in restored_days:
                    days[e["date"]] = e
                    taken += 1
        data["days"] = list(days.values()) + others
        quality.touch_last_checked(data, [d for d in restored_days if d in days])
        saved = quality._save_quality_log(data)
    return taken, saved is not False
