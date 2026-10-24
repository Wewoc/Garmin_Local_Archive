#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_backup_bulk.py

Bulk store backup — Sole Owner of garmin_data/backup/bulk/ (v1.7.6.2).

Backs up the bulk store (garmin_data/bulk/, sole owner of the files: garmin_bulk_writer.py) the
same way raw/ is backed up, with one exception:

  bulk/raw/garmin_bulk_YYYY-MM-DD.json             backup/bulk/raw/YYYY-MM/ -> bulk_raw_backup_YYYY-MM.zip
  bulk/aggregates/garmin_bulk_agg_YYYY-MM-DD.json  backup/bulk/aggregates/YYYY-MM/ -> bulk_aggregates_backup_YYYY-MM.zip
      Day files: the month-folder / monthly-ZIP flow of garmin_backup_common (shared with raw/ and
      source/). A day file that changed (a fuller day, a newer schema) replaces its copy.
  bulk/source/<xx>/<sha256>.fit|.json              backup/bulk/source/<xx>.zip
      The unchanged export files. They have no date and never change (the name is the SHA-256 of
      the bytes), so there are no month folders: one ZIP per first two hash characters, entries
      <sha256>.fit / <sha256>.json, only ever added. Only names of exactly that form are backed up
      (a .tmp of the writer or anything else in the folder is ignored).

Safety rules of the originals' ZIPs (the weakness of "a" mode, register finding F-9, does not
apply here): a ZIP is never appended to. A prefix with new files gets a new ZIP written next to
the old one (<xx>.zip.tmp: the old entries copied, the new ones added), verified and swapped in
with os.replace; the old ZIP stays until then. A ZIP that cannot be read, or fails its check, is
not touched and not copied: it is reported (damaged_zips) and the files of its prefix count as
failed.

Reads the bulk store (read only) and writes only to backup/bulk/. Imports garmin_config lazily
(paths at call time) and garmin_backup_common (a leaf node); no pipeline module, no quality log.

Everything here is non-fatal: an error ends in the returned numbers (and ok=False) and the log,
nothing raises. backup_all() is for the caller to run after the import phases and at the sync
start; it does nothing, apart from looking, when the backup is complete.

Public API:
  backup_all(should_stop=None)            -> dict   copies what is missing, refreshes what changed
  check_needed()                          -> dict   counts what a backup_all() would do (copies nothing)
  backup_originals(should_stop=None)      -> dict   the originals only
  read_day_copy(which, date_str)          -> bytes | None   "raw" | "aggregates", from the backup
  read_original_copy(file_hash, suffix)   -> bytes | None   from the backup
  day_kinds()                             -> {"raw": BackupKind, "aggregates": BackupKind}
"""

import logging
import os
import re
import zipfile
from pathlib import Path

import garmin_backup_common as common

log = logging.getLogger(__name__)

LOG_PREFIX = "backup_bulk"

_PREFIX_RE = re.compile(r"[0-9a-f]{2}")
_ORIGINAL_RE = re.compile(r"[0-9a-f]{64}\.(?:fit|json)")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_SUFFIXES = (".fit", ".json")


def _cfg():
    import garmin_config as cfg
    return cfg


# ══════════════════════════════════════════════════════════════════════════════
#  The day files (month-folder / monthly-ZIP flow of garmin_backup_common)
# ══════════════════════════════════════════════════════════════════════════════

def day_kinds() -> dict:
    """The two kinds of day file of the bulk store, built from the paths of garmin_config now."""
    cfg = _cfg()
    return {
        "raw": common.BackupKind(
            area="bulk-raw", src_dir=cfg.BULK_RAW_DIR, backup_dir=cfg.BULK_RAW_BACKUP_DIR,
            prefix=cfg.BULK_FILE_PREFIX, zip_prefix="bulk_raw_backup_",
            is_valid=common.is_dated_object, log_prefix=LOG_PREFIX),
        "aggregates": common.BackupKind(
            area="bulk-aggregates", src_dir=cfg.BULK_AGG_DIR, backup_dir=cfg.BULK_AGG_BACKUP_DIR,
            prefix=cfg.BULK_AGG_FILE_PREFIX, zip_prefix="bulk_aggregates_backup_",
            is_valid=common.is_dated_object, log_prefix=LOG_PREFIX),
    }


def read_day_copy(which: str, date_str: str) -> bytes | None:
    """The backup copy of one day file ("raw" or "aggregates"); None if there is none."""
    kinds = day_kinds()
    if which not in kinds:
        raise ValueError(f"which must be one of {sorted(kinds)}, not {which!r}")
    kind = kinds[which]
    return common.read_copy(kind, f"{kind.prefix}{date_str}{kind.suffix}")


# ══════════════════════════════════════════════════════════════════════════════
#  The originals (one ZIP per hash prefix, only ever added to)
# ══════════════════════════════════════════════════════════════════════════════

def _original_groups() -> dict:
    """
    {prefix: [paths]} of the originals in bulk/source — only <xx>/<sha256>.fit|.json whose
    name starts with the folder's two characters. Nothing else is looked at; no file is read.
    """
    src = _cfg().BULK_SOURCE_DIR
    groups: dict = {}
    if not src.exists():
        return groups
    for sub in sorted(src.iterdir()):
        if not sub.is_dir() or not _PREFIX_RE.fullmatch(sub.name):
            continue
        files = [f for f in sorted(sub.iterdir())
                 if f.is_file() and _ORIGINAL_RE.fullmatch(f.name) and f.name[:2] == sub.name]
        if files:
            groups[sub.name] = files
    return groups


def _zip_names(zip_path: Path):
    """(names, None) read from the ZIP's directory only; (None, reason) if it cannot be read."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return set(zf.namelist()), None
    except (zipfile.BadZipFile, OSError) as e:
        return None, f"{type(e).__name__}: {e}"


def _zip_intact(zip_path: Path):
    """(True, None) if every entry passes its check; (False, reason) otherwise."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
    except (zipfile.BadZipFile, OSError) as e:
        return False, f"{type(e).__name__}: {e}"
    return (True, None) if bad is None else (False, f"entry {bad} fails its check")


def _write_prefix_zip(zip_path: Path, files: list, keep_existing: bool) -> int:
    """
    Writes zip_path anew through zip_path + ".tmp": the old entries (if keep_existing), then the
    files; the new ZIP is verified before os.replace swaps it in. A file that cannot be opened is
    left out (logged). Returns the number of files added. Raises on any other error; the .tmp is
    removed then and the old ZIP is untouched.
    """
    tmp = zip_path.with_name(zip_path.name + ".tmp")
    added = 0
    try:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            if keep_existing:
                with zipfile.ZipFile(zip_path, "r") as old:
                    for item in old.infolist():
                        dst.writestr(item, old.read(item.filename))
            for f in files:
                try:
                    dst.write(f, f.name)
                except OSError as e:
                    log.error(f"  {LOG_PREFIX}: {f.name} could not be added to {zip_path.name}: {type(e).__name__}: {e}")
                    continue
                added += 1
        if added == 0:
            tmp.unlink()                  # nothing could be added: leave everything as it was
            return 0
        with zipfile.ZipFile(tmp, "r") as check:
            if check.testzip() is not None:
                raise RuntimeError("ZIP integrity check failed")
        os.replace(tmp, zip_path)
        return added
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception as cleanup_error:
            log.debug(f"  {LOG_PREFIX}: tmp zip cleanup failed for {zip_path.name}: {cleanup_error}")
        raise


def backup_originals(should_stop=None) -> dict:
    """
    Backs up the originals of bulk/source that are not in the backup yet.

    Returns {"copied", "present", "failed", "damaged_zips", "stopped"}:
      copied        originals added to a ZIP now
      present       originals that were in their ZIP already
      failed        originals that could not be backed up (a prefix whose ZIP is damaged counts all
                    its files; a file that could not be added counts one)
      damaged_zips  prefix ZIPs that were not touched because they cannot be read or fail their check
      stopped       should_stop() answered True; the prefixes not reached are not counted
    Never raises.
    """
    result = {"copied": 0, "present": 0, "failed": 0, "damaged_zips": 0, "stopped": False}
    try:
        groups = _original_groups()
        out_dir = _cfg().BULK_SOURCE_BACKUP_DIR
    except Exception as e:
        log.error(f"  {LOG_PREFIX}: originals could not be listed: {type(e).__name__}: {e}")
        result["failed"] += 1
        return result

    total_prefixes = len(groups)
    last_step      = 0

    def _progress(done):
        # A first backup of the originals takes minutes: a line at every 10 % of the folders. Only
        # when this run has copied something, so a routine start with nothing to do stays quiet (and
        # a damaged ZIP, which fails again at every start, does not add ten lines each time).
        nonlocal last_step
        if not result["copied"] or not total_prefixes:
            return
        if 10 * done // total_prefixes > last_step:
            last_step = 10 * done // total_prefixes
            log.info(f"  {LOG_PREFIX}: originals {100 * done // total_prefixes} % "
                     f"({done} of {total_prefixes} folders)")

    for done_before, (prefix, files) in enumerate(groups.items()):
        _progress(done_before)
        zip_path = out_dir / f"{prefix}.zip"
        missing = files                   # until it is known which of them the ZIP lacks
        try:
            existing = zip_path.exists()
            names = set()
            if existing:
                names, reason = _zip_names(zip_path)
                if names is not None:
                    intact, reason = _zip_intact(zip_path) if any(f.name not in names for f in files) else (True, None)
                    if not intact:
                        names = None
                if names is None:
                    log.error(f"  {LOG_PREFIX}: {zip_path.name} is damaged ({reason}) — not touched; "
                              f"{len(files)} original(s) of {prefix}/ are not backed up")
                    result["damaged_zips"] += 1
                    result["failed"] += len(files)
                    continue
            missing = [f for f in files if f.name not in names]
            result["present"] += len(files) - len(missing)
            if not missing:
                continue
            # asked only when there is work: a start with a complete backup (or none at all) must
            # not look any different from outside, also to a stop check that counts its calls
            if should_stop is not None and should_stop():
                result["stopped"] = True
                break
            added = _write_prefix_zip(zip_path, missing, keep_existing=existing)
            result["copied"] += added
            result["failed"] += len(missing) - added
        except Exception as e:
            log.error(f"  {LOG_PREFIX}: originals {prefix}/ could not be backed up: {type(e).__name__}: {e}")
            result["failed"] += len(missing)
    if not result["stopped"]:
        _progress(total_prefixes)
    return result


def read_original_copy(file_hash: str, suffix: str = ".fit") -> bytes | None:
    """The backup copy of one original (SHA-256 name, ".fit" or ".json"); None if there is none."""
    if not isinstance(file_hash, str) or not _HASH_RE.fullmatch(file_hash) or suffix not in _SUFFIXES:
        return None
    zip_path = _cfg().BULK_SOURCE_BACKUP_DIR / f"{file_hash[:2]}.zip"
    name = f"{file_hash}{suffix}"
    try:
        if not zip_path.exists():
            return None
        with zipfile.ZipFile(zip_path, "r") as zf:
            if name in zf.namelist():
                return zf.read(name)
        return None
    except Exception as e:
        log.warning(f"  {LOG_PREFIX}: could not read the backup copy of {name}: {type(e).__name__}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  All of it
# ══════════════════════════════════════════════════════════════════════════════

def _stopped(should_stop) -> bool:
    return should_stop is not None and should_stop()


def backup_all(should_stop=None) -> dict:
    """
    Brings the backup of the whole bulk store up to date: copies what has no backup, refreshes
    the day files that changed, adds the originals that are missing.

    Returns {"raw": {...}, "aggregates": {...}, "source": {...}, "ok": bool, "stopped": bool}:
      raw / aggregates  {"copied", "skipped", "failed", "refreshed", "unreadable", "errors"}
                        (the results of backfill and refresh of garmin_backup_common; a step that
                        had nothing to do is not run and counts zero, so "skipped" is only filled
                        when a backfill ran), or {"error": text} when the part itself failed
      source            the result of backup_originals()
      ok                nothing failed anywhere (no failed file, no error, no damaged ZIP, no part
                        that raised); a stop is not a failure
      stopped           should_stop() answered True; later parts were not started. It is asked only
                        before a part that has work, never when everything is backed up
    Never raises.
    """
    out: dict = {"ok": True, "stopped": False}
    try:
        kinds = day_kinds()
    except Exception as e:
        log.error(f"  {LOG_PREFIX}: the paths of the bulk store could not be read: {type(e).__name__}: {e}")
        return {"raw": {"error": str(e)}, "aggregates": {"error": str(e)}, "source": {"error": str(e)},
                "ok": False, "stopped": False}

    for which, kind in kinds.items():
        try:
            # Look first, work only when there is something to do: backfill and refresh log a line
            # at info level every time they run, which would be four lines of noise at each sync start.
            # The stop request is asked only when there is work, so a complete backup (or no bulk store
            # at all) leaves a start exactly as it was, also for a stop check that counts its calls.
            part = {"copied": 0, "skipped": 0, "failed": 0, "refreshed": 0, "unreadable": 0, "errors": 0}
            missing = common.check_backfill_needed(kind)
            outdated, unreadable = common.find_outdated(kind)
            if (missing or outdated or unreadable) and _stopped(should_stop):
                out["stopped"] = True
                break
            if missing:
                part.update(common.backfill(kind))
            if outdated or unreadable:
                part.update(common.refresh(kind))
        except Exception as e:
            log.error(f"  {LOG_PREFIX}: {which} could not be backed up: {type(e).__name__}: {e}")
            out[which] = {"error": f"{type(e).__name__}: {e}"}
            out["ok"] = False
            continue
        out[which] = part
        if part["failed"] or part["errors"]:
            out["ok"] = False
        if part["copied"] or part["refreshed"] or part["failed"] or part["errors"] or part["unreadable"]:
            log.info(f"  {LOG_PREFIX}: {which} — {part['copied']} copied, {part['refreshed']} refreshed, "
                     f"{part['unreadable']} unreadable, {part['failed'] + part['errors']} failed")

    if not out["stopped"]:
        src = backup_originals(should_stop)
        out["source"] = src
        out["stopped"] = src["stopped"]
        if src["failed"] or src["damaged_zips"]:
            out["ok"] = False
        if src["copied"] or src["failed"]:
            log.info(f"  {LOG_PREFIX}: originals — {src['copied']} copied, {src['present']} present, "
                     f"{src['failed']} failed, {src['damaged_zips']} damaged ZIP(s)")
    return out


def check_needed() -> dict:
    """
    Counts what backup_all() would do, copying nothing: {"raw", "aggregates", "source", "damaged_zips"}.
    raw / aggregates: files without a backup copy plus files whose copy differs; source: originals
    that are not in their ZIP (all files of a prefix whose ZIP cannot be read); damaged_zips: the
    prefix ZIPs that cannot be read. The day files are read (they are small) and compared with their
    copies; the ZIPs are only looked at in their directories (no entry is unpacked); the originals are
    not read at all. An error counts as nothing found for that part (a warning).
    """
    out = {"raw": 0, "aggregates": 0, "source": 0, "damaged_zips": 0}
    try:
        for which, kind in day_kinds().items():
            try:
                out[which] = common.check_backfill_needed(kind) + common.check_stale(kind)
            except Exception as e:
                log.warning(f"  {LOG_PREFIX}: check of {which} failed: {type(e).__name__}: {e}")
        out_dir = _cfg().BULK_SOURCE_BACKUP_DIR
        for prefix, files in _original_groups().items():
            zip_path = out_dir / f"{prefix}.zip"
            if not zip_path.exists():
                out["source"] += len(files)
                continue
            names, _reason = _zip_names(zip_path)
            if names is None:
                out["damaged_zips"] += 1
                out["source"] += len(files)
                continue
            out["source"] += sum(1 for f in files if f.name not in names)
    except Exception as e:
        log.warning(f"  {LOG_PREFIX}: check failed: {type(e).__name__}: {e}")
    return out
