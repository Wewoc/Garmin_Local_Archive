#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/diary_backup.py

DIARY v1.7.8 — REMOVABLE. Sole writer of <archive folder>/garmin_data/backup/diary/ (Baustein 5).

The diary is the only data of GLA that cannot be built again: it is typed by hand and has no source. This
module keeps a second copy of it. It is a thin shell over garmin_backup_common (the month-folder / monthly-ZIP
flow that raw/, source/ and the bulk store use; that module is not changed here, it is part of the hash that
other modules guard) and the one place where the diary package depends on a module of garmin/. Files that
this module writes itself (the copy of the field list) go through atomic_io, the shared atomic-write helper in
garmin/ that diary_writer uses as well.

  garmin_data/backup/diary/days/YYYY-MM/diary_YYYY-MM-DD.json   open month: the newest copy of a day
  garmin_data/backup/diary/days/diary_backup_YYYY-MM.zip        completed month
  garmin_data/backup/diary/master/fields.json                   the field list as it was last backed up
  garmin_data/backup/diary/master/fields.previous.json          the version before that one

Rules:
  - Only a file that passes its checks is copied (a damaged day or field list is never copied over a good
    copy, and a field list that cannot be read is not copied at all); the reason is logged.
  - A copy is never deleted: a day the user deleted stays in the backup (the backup is not a mirror).
  - Reads the diary read only (diary_reader); the restore is done by diary_writer (sole writer of diary_data/),
    which is handed the bytes of a copy and checks them again.
  - Nothing here raises: every function answers with a dict {"ok": bool, "status": ..., "reason": ...}; the log
    holds the date or the kind of an error, never a note, a value or a field name.
  - One lock covers everything here, so a backup after a save and the backup at the start do not overlap.

Public API (base_dir = the archive folder):
  backup_day(base_dir, date_str)    after a save: the copy of one day
  backup_master(base_dir)           after a change of the field list
  backup_all(base_dir)              at the start: master, missing and outdated days
  read_day_copy(base_dir, date_str) -> bytes | None
  read_master_copy(base_dir, previous=False) -> bytes | None
  read_valid_day_copy(base_dir, date_str)    -> bytes | None   only a copy that passes the checks of a day
  read_valid_master_copy(base_dir)           -> bytes | None   only a copy that passes the checks of a field list
  check(base_dir)                   -> dict, read only: what is damaged, what can be restored, what is not backed up
"""

import json
import logging
import threading
from pathlib import Path

import atomic_io as aio
import garmin_backup_common as common

from . import diary_model as dm
from . import diary_reader as rd

log = logging.getLogger(__name__)

LOG_PREFIX = "backup_diary"
MASTER_COPY_NAME = "fields.json"
MASTER_PREVIOUS_NAME = "fields.previous.json"

_LOCK = threading.RLock()


def _result(ok, status, reason=None, **extra):
    out = {"ok": ok, "status": status}
    if reason is not None:
        out["reason"] = reason
    out.update(extra)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Paths and the kind of file
# ══════════════════════════════════════════════════════════════════════════════

def backup_dir(base_dir):
    return Path(base_dir) / "garmin_data" / "backup" / "diary"


def master_dir(base_dir):
    return backup_dir(base_dir) / "master"


def _is_valid_day(data, date_str):
    """May these bytes be a backup copy of the day date_str: valid JSON that passes the checks of a day file."""
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return False
    return isinstance(obj, dict) and dm.check_day(obj, date_str) == []


def days_kind(base_dir):
    """The kind of file of garmin_backup_common for the day files of this archive folder."""
    return common.BackupKind(
        area="diary", src_dir=dm.days_dir(base_dir), backup_dir=backup_dir(base_dir) / "days",
        prefix=dm.DAY_PREFIX, zip_prefix="diary_backup_", is_valid=_is_valid_day,
        log_prefix=LOG_PREFIX, suffix=dm.DAY_SUFFIX, log=log)


def _write_atomic(dst, payload):
    """
    tmp + os.replace through atomic_io.write_atomic, the same call as diary_writer's: fsync where the file system
    supports it, a file locked for a moment is tried again (aio.REPLACE_ATTEMPTS times in all). Raises on any
    failure; the .tmp is removed then.
    """
    aio.write_atomic(dst, payload, fsync=aio.FSYNC_SOFT, attempts=aio.REPLACE_ATTEMPTS, pause_s=aio.REPLACE_PAUSE_S)


# ══════════════════════════════════════════════════════════════════════════════
#  Backing up
# ══════════════════════════════════════════════════════════════════════════════

def backup_day(base_dir, date_str):
    """
    The backup copy of one day, made after a save. A day that has no file (it was deleted) has nothing to back
    up (status "nothing"); a day file that is damaged is not copied (status "skipped", ok False).
    """
    with _LOCK:
        try:
            if not dm.valid_date(date_str):
                return _result(False, "skipped", "invalid_date")
            state, _day = rd.read_day(base_dir, date_str)
            if state == rd.MISSING:
                return _result(True, "nothing", "day_missing")
            if state != rd.OK:
                log.warning("%s: day %s is %s: not copied", LOG_PREFIX, date_str, state)
                return _result(False, "skipped", f"day_{state}")
            if common.backup_file(days_kind(base_dir), date_str):
                return _result(True, "backed_up")
            return _result(False, "failed", "copy_failed")
        except Exception as exc:
            log.error("%s: day %s failed (%s)", LOG_PREFIX, date_str, type(exc).__name__)
            return _result(False, "failed", "exception")


def backup_master(base_dir):
    """
    The backup copy of the field list. The copy that was there is kept once as fields.previous.json (a wrong
    click on a flag can be undone by hand). A field list that cannot be read is not copied.
    """
    with _LOCK:
        try:
            state, _master = rd.read_master(base_dir)
            if state == rd.MISSING:
                return _result(True, "nothing", "master_missing")
            if state != rd.OK:
                log.warning("%s: the field list is %s: not copied", LOG_PREFIX, state)
                return _result(False, "skipped", f"master_{state}")
            data = dm.fields_path(base_dir).read_bytes()
            folder = master_dir(base_dir)
            current = folder / MASTER_COPY_NAME
            if current.is_file():
                old = current.read_bytes()
                if old == data:
                    return _result(True, "unchanged")
                _write_atomic(folder / MASTER_PREVIOUS_NAME, old)
            _write_atomic(current, data)
            log.info("%s: field list copied", LOG_PREFIX)
            return _result(True, "backed_up")
        except Exception as exc:
            log.error("%s: field list failed (%s)", LOG_PREFIX, type(exc).__name__)
            return _result(False, "failed", "exception")


def backup_all(base_dir):
    """
    The backup at the start: the field list, every day that has no copy yet, every day whose copy is older than
    the file. Idempotent; a second run copies nothing. ok is False when something could not be copied; damaged
    lists the days that cannot be read (garmin_backup_common copies a day that has no copy yet as it is, the copy
    is checked again before it is ever restored).
    """
    with _LOCK:
        try:
            master = backup_master(base_dir)
            kind = days_kind(base_dir)
            damaged = [d for d in rd.list_days(base_dir) if rd.read_day(base_dir, d)[0] in (rd.DAMAGED, rd.UNSUPPORTED)]
            filled = common.backfill(kind)
            refreshed = common.refresh(kind)
            ok = master["ok"] and filled["failed"] == 0 and refreshed["errors"] == 0
            log.info("%s: start: %d copied, %d refreshed, %d failed, %d damaged days",
                     LOG_PREFIX, filled["copied"], refreshed["refreshed"], filled["failed"] + refreshed["errors"], len(damaged))
            return _result(ok, "done", master=master["status"], copied=filled["copied"], refreshed=refreshed["refreshed"],
                           failed=filled["failed"] + refreshed["errors"], damaged=damaged)
        except Exception as exc:
            log.error("%s: start failed (%s)", LOG_PREFIX, type(exc).__name__)
            return _result(False, "failed", "exception")


# ══════════════════════════════════════════════════════════════════════════════
#  Reading the copies and the check
# ══════════════════════════════════════════════════════════════════════════════

def read_day_copy(base_dir, date_str):
    """The bytes of the backup copy of a day, or None (also for a date that is not a date)."""
    if not dm.valid_date(date_str):
        return None
    kind = days_kind(base_dir)
    try:
        return common.read_copy(kind, f"{kind.prefix}{date_str}{kind.suffix}")
    except Exception as exc:
        log.error("%s: reading the copy of day %s failed (%s)", LOG_PREFIX, date_str, type(exc).__name__)
        return None


def read_master_copy(base_dir, previous=False):
    """The bytes of the backup copy of the field list (the one before the last with previous=True), or None."""
    path = master_dir(base_dir) / (MASTER_PREVIOUS_NAME if previous else MASTER_COPY_NAME)
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError as exc:
        log.error("%s: reading the copy of the field list failed (%s)", LOG_PREFIX, type(exc).__name__)
        return None


def _is_valid_master(data):
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return False
    return dm.check_master(obj) == []


def read_valid_day_copy(base_dir, date_str):
    """The bytes of the backup copy of a day if they pass the checks of a day file, else None."""
    data = read_day_copy(base_dir, date_str)
    return data if data is not None and _is_valid_day(data, date_str) else None


def read_valid_master_copy(base_dir):
    """The bytes of the backup copy of the field list if they pass its checks, else None."""
    data = read_master_copy(base_dir)
    return data if data is not None and _is_valid_master(data) else None


def _backup_dates(base_dir):
    """The dates that have a backup copy, in a month folder or in a monthly ZIP."""
    kind = days_kind(base_dir)
    dates = set()
    folder = kind.backup_dir
    if not folder.is_dir():
        return dates
    for entry in folder.iterdir():
        if entry.is_dir():
            names = [f.name for f in entry.iterdir() if f.is_file()]
        elif entry.suffix == ".zip":
            names = list(common.zip_index(entry, log))
        else:
            continue
        for name in names:
            date_str = dm.date_of_day_file_name(name)
            if date_str is not None:
                dates.add(date_str)
    return dates


def check(base_dir):
    """
    Read only. {"master": state of fields.json, "master_copy": "ok" | "missing" | "damaged",
    "days": number of day files, "damaged": [dates], "unsupported": [dates],
    "restorable": [damaged dates that have a valid copy], "missing_in_data": [dates that have a copy and no file],
    "not_backed_up": number of day files without a copy, "outdated": number of day files whose copy differs}.
    Nothing is repaired here: a repair is done by diary_writer, with the bytes of a copy.
    """
    with _LOCK:
        try:
            master_state, _master = rd.read_master(base_dir)
            copy = read_master_copy(base_dir)
            master_copy = "missing" if copy is None else ("ok" if _is_valid_master(copy) else "damaged")
            dates = rd.list_days(base_dir)
            damaged, unsupported = [], []
            for date_str in dates:
                state, _day = rd.read_day(base_dir, date_str)
                if state == rd.DAMAGED:
                    damaged.append(date_str)
                elif state == rd.UNSUPPORTED:
                    unsupported.append(date_str)
            restorable = []
            for date_str in damaged:
                data = read_day_copy(base_dir, date_str)
                if data is not None and _is_valid_day(data, date_str):
                    restorable.append(date_str)
            kind = days_kind(base_dir)
            return {"ok": True, "master": master_state, "master_copy": master_copy, "days": len(dates),
                    "damaged": damaged, "unsupported": unsupported, "restorable": restorable,
                    "missing_in_data": sorted(_backup_dates(base_dir) - set(dates)),
                    "not_backed_up": common.check_backfill_needed(kind), "outdated": common.check_stale(kind)}
        except Exception as exc:
            log.error("%s: check failed (%s)", LOG_PREFIX, type(exc).__name__)
            return _result(False, "failed", "exception")
