#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/diary_writer.py

DIARY v1.7.8 — REMOVABLE. Sole write authority over diary_data/ (the master file fields.json and the
day files days/diary_YYYY-MM-DD.json). Nothing else writes there. Imports only the other modules of
this package and the standard library; the base folder comes in as a parameter (no garmin_config).

Everything is non-fatal: no function raises for bad input or a failed write. Each returns a dict

    {"status": "written" | "deleted" | "unchanged" | "rejected" | "failed", "reason": <short code>, ...}

"rejected" = checked and refused, nothing was written (the reason says why); "failed" = the write
itself failed (a .tmp is removed, a stored file is untouched); "deleted" = a day that was emptied
(no note, no entry) and has no history is removed (see save_day). A refusal is loud on purpose: a diary
that quietly drops or overwrites what the user typed is the failure this module is built against.

Writing: every file goes to <name>.tmp, is flushed to disk and moved with os.replace (tried again
for a moment when the file is locked, as in garmin_bulk_writer.py: a virus scanner or an indexer can
hold a file that was just written). One lock covers every read-modify-write here.

No line of the log carries a note, a value or a field name: the files hold health data. The log has
the date, the key and the kind of an error.

Rules of the data (KONZEPT_tagebuch_V2.md, Abschnitt 5):
  - A key is never reused. Set 2 keys are counted up from "next_id" in fields.json; if that file
    is missing while day files exist, nothing is created until recover_master() has rebuilt it.
  - A definition is immutable. Only the display name of a stored field can change (rename_field);
    the day files keep the name of the day they were made.
  - A day file carries a key_snapshot of the definitions it uses. The snapshot only gains keys (a
    field added on the same day); a stored definition in it is never rewritten.
  - A day is free to edit until the end of the calendar day of its first save ("created"). After
    that save_day refuses with "history_required" unless the caller says keep_history=True: then the whole
    state the day had before is appended to its "history" (oldest first, only ever appended) and the day is
    written. restore_history puts an earlier state back the same way (the state it replaces is kept too).
    A day that has no file yet can be written for any date; it has no history until it is changed later.

Public API:
  create_user_field(base_dir, name, values, with_time)
  activate_catalog_field(base_dir, key)
  set_flags(base_dir, key, favorite=None, archived=None)
  rename_field(base_dir, key, new_name)
  save_day(base_dir, date_str, note, entries, now=None, keep_history=False)
  restore_history(base_dir, date_str, index, now=None)
  recover_master(base_dir, overwrite=False)
  restore_day(base_dir, date_str, data)       the bytes of a backup copy (diary_backup) put back as a day
  restore_master(base_dir, data)              the bytes of a backup copy put back as the field list
"""

import copy
import json
import logging
import os
import threading
import time
from datetime import datetime

from . import diary_catalog as cat
from . import diary_model as dm
from . import diary_reader as rd

log = logging.getLogger(__name__)

WRITTEN = "written"
DELETED = "deleted"
UNCHANGED = "unchanged"
REJECTED = "rejected"
FAILED = "failed"

# On Windows a virus scanner or an indexer can hold a file that was just written for a moment;
# os.replace then fails with a sharing violation (PermissionError). Other errors are not retried.
REPLACE_ATTEMPTS = 5
REPLACE_PAUSE_S = 0.1

_LOCK = threading.RLock()


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _result(status, reason=None, **extra):
    out = {"status": status}
    if reason is not None:
        out["reason"] = reason
    out.update(extra)
    return out


def _cleanup(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _replace(tmp, dst):
    """os.replace that waits a moment and tries again when the file is locked (see REPLACE_ATTEMPTS)."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE_S * (attempt + 1))


def _write_atomic(dst, payload):
    """
    Writes payload (bytes) to dst through dst + '.tmp': written, flushed to disk (fsync, where the
    file system supports it) and moved with os.replace. Creates the folder. Raises on any failure;
    the .tmp is removed then and a stored dst is untouched.
    """
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # not supported on every file system
        _replace(tmp, dst)
    except Exception:
        _cleanup(tmp)
        raise


def _remove(path):
    """
    Removes a file; a lock for a moment is tried again like in _replace. A file that is not there
    counts as removed. Raises on any other failure.
    """
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE_S * (attempt + 1))


def _json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _store(path, obj, what):
    """Writes obj as JSON; (True, None) or (False, result) with the 'failed' result."""
    try:
        _write_atomic(path, _json_bytes(obj))
    except Exception as exc:
        log.error("diary: writing %s failed (%s)", what, type(exc).__name__)
        return False, _result(FAILED, "write_failed")
    return True, None


def _empty_master():
    return {"schema_version": dm.SCHEMA_VERSION, "next_id": 1, "fields": {}}


def _master_for_write(base_dir):
    """
    (master, None) to go on with, or (None, rejected result). A missing master is a fresh one only
    when no day file exists yet: otherwise the keys of those days could be handed out again.
    """
    state, master = rd.read_master(base_dir)
    if state == rd.OK:
        return master, None
    if state == rd.MISSING:
        if rd.list_days(base_dir):
            return None, _result(REJECTED, "master_missing_days_exist")
        return _empty_master(), None
    return None, _result(REJECTED, f"master_{state}")


def _reserved_names(master, own_key=None):
    """Normalized names a field may not take: those of the other stored fields and of the catalogue."""
    taken = {dm.normalized_name(f["name"]) for k, f in master["fields"].items() if k != own_key}
    taken |= {dm.normalized_name(entry["name"]) for k, entry in cat.CATALOG.items() if k != own_key}
    return taken


# ══════════════════════════════════════════════════════════════════════════════
#  Fields
# ══════════════════════════════════════════════════════════════════════════════

def create_user_field(base_dir, name, values, with_time):
    """
    Makes a new Set 2 field. values = [{"label": ..., "type": "number"|"yesno", "unit": ...}, ...].
    Returns written with "key" ('U0001' ...); rejected for an invalid definition ("invalid_definition",
    "errors") or a name that is taken ("duplicate_name"), also by a catalogue field.
    """
    with _LOCK:
        master, refusal = _master_for_write(base_dir)
        if refusal is not None:
            return refusal
        defn = {"name": dm.clean_name(name), "set": dm.SET_USER,
                "values": copy.deepcopy(values), "with_time": with_time}
        errors = dm.check_definition(defn)
        if errors:
            return _result(REJECTED, "invalid_definition", errors=errors)
        if dm.normalized_name(defn["name"]) in _reserved_names(master):
            return _result(REJECTED, "duplicate_name")
        key = dm.format_user_key(master["next_id"])
        master["next_id"] += 1
        master["fields"][key] = {**defn, "favorite": False, "archived": False}
        ok, failure = _store(dm.fields_path(base_dir), master, "the field list")
        if not ok:
            return failure
        log.info("diary: field %s created", key)
        return _result(WRITTEN, key=key)


def activate_catalog_field(base_dir, key):
    """Takes a Set 1 field of the catalogue into the field list (once; a second call changes nothing)."""
    with _LOCK:
        definition = cat.definition(key)
        if definition is None:
            return _result(REJECTED, "unknown_catalog_key")
        master, refusal = _master_for_write(base_dir)
        if refusal is not None:
            return refusal
        if key in master["fields"]:
            return _result(UNCHANGED, key=key)
        if dm.normalized_name(definition["name"]) in _reserved_names(master, own_key=key):
            return _result(REJECTED, "duplicate_name")
        master["fields"][key] = {**definition, "favorite": False, "archived": False}
        ok, failure = _store(dm.fields_path(base_dir), master, "the field list")
        if not ok:
            return failure
        log.info("diary: catalogue field %s activated", key)
        return _result(WRITTEN, key=key)


def set_flags(base_dir, key, favorite=None, archived=None):
    """
    Sets 'favorite' and/or 'archived' of a stored field (None = leave as it is). Archiving only
    hides a field: its key stays taken for good.
    """
    with _LOCK:
        for flag in (favorite, archived):
            if flag is not None and not isinstance(flag, bool):
                return _result(REJECTED, "flag_not_bool")
        master, refusal = _master_for_write(base_dir)
        if refusal is not None:
            return refusal
        field = master["fields"].get(key)
        if field is None:
            return _result(REJECTED, "unknown_field")
        changed = False
        for flag_name, flag in (("favorite", favorite), ("archived", archived)):
            if flag is not None and field[flag_name] != flag:
                field[flag_name] = flag
                changed = True
        if not changed:
            return _result(UNCHANGED, key=key)
        ok, failure = _store(dm.fields_path(base_dir), master, "the field list")
        if not ok:
            return failure
        log.info("diary: flags of %s changed", key)
        return _result(WRITTEN, key=key)


def rename_field(base_dir, key, new_name):
    """Changes the display name of a stored field (nothing else of a definition can change)."""
    with _LOCK:
        master, refusal = _master_for_write(base_dir)
        if refusal is not None:
            return refusal
        field = master["fields"].get(key)
        if field is None:
            return _result(REJECTED, "unknown_field")
        name = dm.clean_name(new_name)
        errors = dm.check_definition({**dm.definition_of(field), "name": name})
        if errors:
            return _result(REJECTED, "invalid_definition", errors=errors)
        if dm.normalized_name(name) in _reserved_names(master, own_key=key):
            return _result(REJECTED, "duplicate_name")
        if field["name"] == name:
            return _result(UNCHANGED, key=key)
        field["name"] = name
        ok, failure = _store(dm.fields_path(base_dir), master, "the field list")
        if not ok:
            return failure
        log.info("diary: field %s renamed", key)
        return _result(WRITTEN, key=key)


# ══════════════════════════════════════════════════════════════════════════════
#  Days
# ══════════════════════════════════════════════════════════════════════════════

def _history_item(now, state):
    """The history entry for a day that is about to change: the time stamp and the whole state it had."""
    return {"timestamp": now.isoformat(timespec="seconds"),
            "before": {"note": state["note"], "entries": copy.deepcopy(state["entries"])}}


def save_day(base_dir, date_str, note, entries, now=None, keep_history=False):
    """
    Saves one day: the note and the entries by field key ({"U0001": [entry, ...], ...}). The whole
    day is replaced by what is handed in; a key with an empty list has no entry (it is left out).

    now (a datetime; default the local clock) fixes "today" for the free-edit window.
    keep_history says that the caller knows the day is older than its free-edit window and accepts that
    the state it had so far is kept in its history; without it such a change is refused. On a day that
    is still free (or has no file yet) the flag changes nothing: no history is written there.

    written    the day file was made or changed
    deleted    the day was emptied (no note, no entry) and has no history: its file is removed
    unchanged  nothing to store (a new day with no note and no entry) or the same content again
    rejected   nothing was written: "invalid_date", "invalid_note", "invalid_entries", "invalid_key",
               "unknown_field", "invalid_entries_of" (with "key" and "errors"), "history_required"
               (the day is older than its free-edit window), "day_damaged", "day_unsupported",
               "master_damaged", "master_unsupported"
    failed     the write failed
    """
    with _LOCK:
        if not dm.valid_date(date_str):
            return _result(REJECTED, "invalid_date")
        if not isinstance(note, str) or len(note) > dm.MAX_NOTE_LEN:
            return _result(REJECTED, "invalid_note")
        if not isinstance(entries, dict):
            return _result(REJECTED, "invalid_entries")
        if now is None:
            now = datetime.now()

        master_state, master = rd.read_master(base_dir)
        if master_state in (rd.DAMAGED, rd.UNSUPPORTED):
            return _result(REJECTED, f"master_{master_state}")

        day_state, existing = rd.read_day(base_dir, date_str)
        if day_state in (rd.DAMAGED, rd.UNSUPPORTED):
            return _result(REJECTED, f"day_{day_state}")

        snapshot = copy.deepcopy(existing["key_snapshot"]) if existing is not None else {}
        cleaned = {}
        for key, field_entries in entries.items():
            if not dm.valid_key(key):
                return _result(REJECTED, "invalid_key")
            if isinstance(field_entries, list) and not field_entries:
                continue
            field = master["fields"].get(key) if master is not None else None
            if field is None and key not in snapshot:
                return _result(REJECTED, "unknown_field", key=key)
            # An entry is checked against the definition the day already keeps, if it has one.
            defn = snapshot[key] if key in snapshot else dm.definition_of(field)
            errors = dm.check_entries(defn, field_entries)
            if errors:
                return _result(REJECTED, "invalid_entries_of", key=key, errors=errors)
            cleaned[key] = copy.deepcopy(field_entries)
            if key not in snapshot:
                snapshot[key] = dm.snapshot_of(dm.definition_of(field))

        if existing is None and not note and not cleaned:
            return _result(UNCHANGED, "empty_day")

        day = {
            "schema_version": dm.SCHEMA_VERSION,
            "date": date_str,
            "created": existing["created"] if existing is not None else now.isoformat(timespec="seconds"),
            "note": note,
            "entries": cleaned,
            "key_snapshot": snapshot,
            "history": existing["history"] if existing is not None else [],
        }
        if existing is not None:
            if existing == day:
                return _result(UNCHANGED, date=date_str)
            # The same content is no change; a different one on an older day needs the history.
            if existing["created"][:10] != now.date().isoformat():
                if not keep_history:
                    return _result(REJECTED, "history_required")
                day["history"] = existing["history"] + [_history_item(now, existing)]
            if not note and not cleaned and not day["history"]:
                # Everything was taken out of a day that has no history: a day with no content and
                # no history does not exist (the same as a new day that is saved empty).
                try:
                    _remove(dm.day_path(base_dir, date_str))
                except Exception as exc:
                    log.error("diary: removing day %s failed (%s)", date_str, type(exc).__name__)
                    return _result(FAILED, "remove_failed")
                log.info("diary: day %s removed (emptied)", date_str)
                return _result(DELETED, date=date_str)
        ok, failure = _store(dm.day_path(base_dir, date_str), day, f"day {date_str}")
        if not ok:
            return failure
        log.info("diary: day %s written (%d fields, %d history)", date_str, len(cleaned), len(day["history"]))
        return _result(WRITTEN, date=date_str)


def restore_history(base_dir, date_str, index, now=None):
    """
    Puts the state with the number index (0 = the oldest) of the history of a day back as the day's note and
    entries. The state it replaces is appended to the history first, so nothing is lost and a restore can be
    undone by a restore. The definitions of the day (key_snapshot) and "created" stay as they are.

    written    the day was changed
    unchanged  the state is the one the day has now
    rejected   nothing was written: "invalid_date", "invalid_index" (not an int, or no state with that number),
               "day_missing", "day_damaged", "day_unsupported", "state_invalid" (the stored state does not fit
               the definitions of the day)
    failed     the write failed
    """
    with _LOCK:
        if not dm.valid_date(date_str):
            return _result(REJECTED, "invalid_date")
        if isinstance(index, bool) or not isinstance(index, int):
            return _result(REJECTED, "invalid_index")
        if now is None:
            now = datetime.now()
        state, existing = rd.read_day(base_dir, date_str)
        if state == rd.MISSING:
            return _result(REJECTED, "day_missing")
        if state in (rd.DAMAGED, rd.UNSUPPORTED):
            return _result(REJECTED, f"day_{state}")
        if not 0 <= index < len(existing["history"]):
            return _result(REJECTED, "invalid_index")
        before = copy.deepcopy(existing["history"][index]["before"])
        day = {
            "schema_version": dm.SCHEMA_VERSION,
            "date": date_str,
            "created": existing["created"],
            "note": before["note"],
            "entries": before["entries"],
            "key_snapshot": copy.deepcopy(existing["key_snapshot"]),
            "history": existing["history"],
        }
        if day["note"] == existing["note"] and day["entries"] == existing["entries"]:
            return _result(UNCHANGED, date=date_str)
        day["history"] = existing["history"] + [_history_item(now, existing)]
        if dm.check_day(day, date_str):
            return _result(REJECTED, "state_invalid")
        ok, failure = _store(dm.day_path(base_dir, date_str), day, f"day {date_str}")
        if not ok:
            return failure
        log.info("diary: day %s restored to history state %d", date_str, index)
        return _result(WRITTEN, date=date_str)


# ══════════════════════════════════════════════════════════════════════════════
#  Recovery of the master file
# ══════════════════════════════════════════════════════════════════════════════

def recover_master(base_dir, overwrite=False):
    """
    Rebuilds fields.json from the key_snapshots of the day files: the newest day wins for a key
    (a definition only ever differs in the display name). Flags start as favorite=False,
    archived=False. 'next_id' is the highest Set 2 number seen plus one; a key that was made and
    never used in a day file cannot be found again, which is harmless as no day points to it.

    refused (rejected): "master_ok" (nothing to recover), "master_damaged" / "master_unsupported"
    (a file is there: it is only replaced with overwrite=True, and kept as fields.json.damaged).
    unchanged "no_days": nothing to rebuild from. Days that cannot be read are skipped and counted.
    """
    with _LOCK:
        state, _master = rd.read_master(base_dir)
        if state == rd.OK:
            return _result(REJECTED, "master_ok")
        if state in (rd.DAMAGED, rd.UNSUPPORTED) and not overwrite:
            return _result(REJECTED, f"master_{state}")
        dates = rd.list_days(base_dir)
        if not dates and state == rd.MISSING:
            return _result(UNCHANGED, "no_days")

        snapshots = {}
        skipped = 0
        for date_str in dates:
            day_state, day = rd.read_day(base_dir, date_str)
            if day_state != rd.OK:
                skipped += 1
                continue
            for key, snap in day["key_snapshot"].items():
                snapshots[key] = snap
        fields = {}
        seen_names = set()
        for key in sorted(snapshots):
            defn = cat.definition(key) if dm.is_garmin_key(key) else None
            if defn is None:
                defn = dm.definition_of(snapshots[key])
            folded = dm.normalized_name(defn["name"])
            if folded in seen_names:
                # Two keys that once carried the same name (one was renamed later): keep both,
                # told apart by their key.
                defn["name"] = f"{defn['name']} [{key}]"
            seen_names.add(dm.normalized_name(defn["name"]))
            fields[key] = {**defn, "favorite": False, "archived": False}
        numbers = [dm.user_key_number(k) for k in fields if dm.is_user_key(k)]
        master = {"schema_version": dm.SCHEMA_VERSION,
                  "next_id": (max(numbers) + 1) if numbers else 1,
                  "fields": fields}
        errors = dm.check_master(master)
        if errors:
            log.error("diary: the recovered field list failed its checks")
            return _result(REJECTED, "recovered_master_invalid", errors=errors)

        path = dm.fields_path(base_dir)
        if state in (rd.DAMAGED, rd.UNSUPPORTED):
            try:
                _replace(path, path.with_name(path.name + ".damaged"))
            except OSError as exc:
                log.error("diary: the old field list could not be set aside (%s)", type(exc).__name__)
                return _result(FAILED, "set_aside_failed")
        ok, failure = _store(path, master, "the recovered field list")
        if not ok:
            return failure
        log.info("diary: field list rebuilt from %d days (%d fields, %d days skipped)",
                 len(dates), len(fields), skipped)
        return _result(WRITTEN, fields=len(fields), skipped=skipped)


# ══════════════════════════════════════════════════════════════════════════════
#  Restore from a backup copy
# ══════════════════════════════════════════════════════════════════════════════

def _parse_copy(data):
    """The JSON object of the bytes of a backup copy, or None."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    try:
        obj = json.loads(bytes(data).decode("utf-8"))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _set_aside(path):
    """Moves a damaged file next to itself as <name>.damaged (numbered when that exists); True if it worked."""
    target = path.with_name(path.name + ".damaged")
    number = 2
    while target.exists():
        target = path.with_name(f"{path.name}.damaged{number}")
        number += 1
    try:
        _replace(path, target)
    except OSError as exc:
        log.error("diary: a damaged file could not be set aside (%s)", type(exc).__name__)
        return False
    return True


def restore_day(base_dir, date_str, data):
    """
    Puts a day back from the bytes of its backup copy (diary_backup.read_day_copy). The copy is checked again
    here. Only a day that has no file or whose file is damaged is restored; a damaged file is kept next to it as
    <name>.damaged. A readable day is never replaced, and a file of a newer version never.

    written    the day was restored
    rejected   "invalid_date", "copy_invalid" (not JSON, or it fails the checks of a day), "day_exists" (the day
               is readable), "day_unsupported" (the file is of a newer version)
    failed     "set_aside_failed" or the write failed
    """
    with _LOCK:
        if not dm.valid_date(date_str):
            return _result(REJECTED, "invalid_date")
        obj = _parse_copy(data)
        if obj is None or dm.check_day(obj, date_str):
            return _result(REJECTED, "copy_invalid")
        state, _existing = rd.read_day(base_dir, date_str)
        if state == rd.OK:
            return _result(REJECTED, "day_exists")
        if state == rd.UNSUPPORTED:
            return _result(REJECTED, "day_unsupported")
        path = dm.day_path(base_dir, date_str)
        if state == rd.DAMAGED and not _set_aside(path):
            return _result(FAILED, "set_aside_failed")
        ok, failure = _store(path, obj, f"day {date_str}")
        if not ok:
            return failure
        log.info("diary: day %s restored from its backup copy", date_str)
        return _result(WRITTEN, date=date_str)


def restore_master(base_dir, data):
    """
    Puts the field list back from the bytes of its backup copy (diary_backup.read_master_copy). Only a missing or
    damaged field list is restored (a damaged one is kept as fields.json.damaged). The copy has to fit the days:
    it must know every key the days use (its counter is above the keys it knows: that is part of its checks),
    otherwise a key could be handed out twice. recover_master is the way when it does not fit.

    written    the field list was restored
    rejected   "copy_invalid", "master_ok" (the field list is readable), "master_unsupported",
               "days_unreadable" (a day cannot be read: its keys are not known), "copy_behind" (the copy lacks a
               key that a day uses)
    failed     "set_aside_failed" or the write failed
    """
    with _LOCK:
        obj = _parse_copy(data)
        if obj is None or dm.check_master(obj):
            return _result(REJECTED, "copy_invalid")
        state, _master = rd.read_master(base_dir)
        if state == rd.OK:
            return _result(REJECTED, "master_ok")
        if state == rd.UNSUPPORTED:
            return _result(REJECTED, "master_unsupported")
        used = set()
        for date_str in rd.list_days(base_dir):
            day_state, day = rd.read_day(base_dir, date_str)
            if day_state != rd.OK:
                return _result(REJECTED, "days_unreadable")
            used |= set(day["key_snapshot"])
        if used - set(obj["fields"]):
            return _result(REJECTED, "copy_behind")
        path = dm.fields_path(base_dir)
        if state == rd.DAMAGED and not _set_aside(path):
            return _result(FAILED, "set_aside_failed")
        ok, failure = _store(path, obj, "the restored field list")
        if not ok:
            return failure
        log.info("diary: field list restored from its backup copy (%d fields)", len(obj["fields"]))
        return _result(WRITTEN, fields=len(obj["fields"]))
