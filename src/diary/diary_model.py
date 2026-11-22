#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/diary_model.py

DIARY v1.7.8 — REMOVABLE. Pure checks and helpers of the diary: no file access, no logging,
no clock. Standard library only (a Leaf Node in the sense of this package: it imports nothing
of the project).

What the diary stores (KONZEPT_tagebuch_V2.md):

  field       a thing the user keeps track of: a name, 1..n named values (label, type, unit) and
              the flag "with_time". Two sets: "garmin" (fixed catalogue, same shape as the Garmin
              field, entered by hand) and "user" (free). A definition never changes after it was
              made, except its display name (a changed unit or type is a new field with a new key).
  entry       one measurement of a field: the values by label and, for a field with time, the time
              ("HH:MM"). A field without time has at most one entry per day.
  key         "G001" (catalogue, fixed) or "U0001" (user, counted up, never reused).

The functions here answer questions with a list of error codes (empty list = fine) or with a
bool; they never raise for bad input. Error codes are short English words, not texts for the
user: the GUI words them itself.

Value types: "number" (int or float, not bool, finite), "yesno" (bool) and "text" (one line of free text,
at most MAX_TEXT_LEN characters). Nothing else in v1.7.8.

Alternatives: number values of a field can share a "group" name (the same value in two units, for example
steps and distance). Within one entry at most one value of a group is entered; the entry then carries only that
one. A group has at least two members and they stand next to each other in the definition.
"""

import copy
import math
import re
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

DIARY_DIR_NAME = "diary_data"
DAYS_DIR_NAME = "days"
FIELDS_FILE_NAME = "fields.json"
DAY_PREFIX = "diary_"
DAY_SUFFIX = ".json"

SET_GARMIN = "garmin"
SET_USER = "user"
SETS = (SET_GARMIN, SET_USER)

TYPE_NUMBER = "number"
TYPE_YESNO = "yesno"
TYPE_TEXT = "text"
VALUE_TYPES = (TYPE_NUMBER, TYPE_YESNO, TYPE_TEXT)

MAX_NAME_LEN = 80
MAX_LABEL_LEN = 40
MAX_UNIT_LEN = 20
MAX_TEXT_LEN = 200
MAX_VALUES = 12
MAX_NOTE_LEN = 100_000
MAX_ENTRIES_PER_FIELD = 500

# [0-9] and re.ASCII on purpose: \d would also match digits of other scripts.
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", re.ASCII)
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}", re.ASCII)
_GARMIN_KEY_RE = re.compile(r"G[0-9]{3}", re.ASCII)
_USER_KEY_RE = re.compile(r"U[0-9]{4,}", re.ASCII)

_DEFINITION_KEYS = {"name", "set", "values", "with_time", "maps_to"}
_VALUE_KEYS = {"label", "type", "unit", "group"}
_ENTRY_KEYS = {"time", "values"}
_FLAG_KEYS = ("favorite", "archived")
_MASTER_KEYS = {"schema_version", "next_id", "fields"}
_DAY_KEYS = {"schema_version", "date", "created", "note", "entries", "key_snapshot", "history"}
_HISTORY_KEYS = {"timestamp", "before"}
_BEFORE_KEYS = {"note", "entries"}


# ══════════════════════════════════════════════════════════════════════════════
#  Paths (pure: only builds Path objects)
# ══════════════════════════════════════════════════════════════════════════════

def diary_dir(base_dir):
    return Path(base_dir) / DIARY_DIR_NAME


def fields_path(base_dir):
    return diary_dir(base_dir) / FIELDS_FILE_NAME


def days_dir(base_dir):
    return diary_dir(base_dir) / DAYS_DIR_NAME


def day_path(base_dir, date_str):
    """Path of the day file, or None when date_str is not a real date."""
    if not valid_date(date_str):
        return None
    return days_dir(base_dir) / f"{DAY_PREFIX}{date_str}{DAY_SUFFIX}"


def date_of_day_file_name(name):
    """The date of a day file name 'diary_YYYY-MM-DD.json', or None for any other name."""
    if not isinstance(name, str):
        return None
    if not (name.startswith(DAY_PREFIX) and name.endswith(DAY_SUFFIX)):
        return None
    date_str = name[len(DAY_PREFIX):-len(DAY_SUFFIX)]
    return date_str if valid_date(date_str) else None


# ══════════════════════════════════════════════════════════════════════════════
#  Dates, times, keys
# ══════════════════════════════════════════════════════════════════════════════

def valid_date(value):
    """True for a real calendar date written 'YYYY-MM-DD' (no week dates, no other script digits)."""
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def valid_timestamp(value):
    """True for a local date and time written 'YYYY-MM-DDTHH:MM:SS' (the form of the time stamps of the history)."""
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def valid_time(value):
    """True for 'HH:MM' on the 24-hour clock ('00:00' to '23:59')."""
    return isinstance(value, str) and _TIME_RE.fullmatch(value) is not None


def is_garmin_key(key):
    return isinstance(key, str) and _GARMIN_KEY_RE.fullmatch(key) is not None


def is_user_key(key):
    return isinstance(key, str) and _USER_KEY_RE.fullmatch(key) is not None


def valid_key(key):
    return is_garmin_key(key) or is_user_key(key)


def format_user_key(number):
    """1 -> 'U0001'; the digits grow past 9999 instead of wrapping."""
    return f"U{number:04d}"


def user_key_number(key):
    """'U0007' -> 7, any other key -> None."""
    return int(key[1:]) if is_user_key(key) else None


def normalized_name(name):
    """The form names are compared in: spaces collapsed, case folded."""
    return " ".join(name.split()).casefold() if isinstance(name, str) else ""


def clean_name(name):
    """A name as it is stored: surrounding space removed, inner runs of space collapsed."""
    return " ".join(name.split()) if isinstance(name, str) else name


# ══════════════════════════════════════════════════════════════════════════════
#  Definitions
# ══════════════════════════════════════════════════════════════════════════════

def check_definition(defn):
    """
    Errors of a field definition: {"name", "set", "values", "with_time"} plus "maps_to" for a
    "garmin" field (and only for it). Unknown keys are an error: a definition has one shape.
    """
    if not isinstance(defn, dict):
        return ["definition_not_a_dict"]
    errors = []
    for extra in sorted(set(defn) - _DEFINITION_KEYS):
        errors.append(f"definition_unknown_key:{extra}")

    name = defn.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name_missing")
    elif name != clean_name(name):
        errors.append("name_not_clean")
    elif len(name) > MAX_NAME_LEN:
        errors.append("name_too_long")

    set_name = defn.get("set")
    if set_name not in SETS:
        errors.append("set_invalid")

    if not isinstance(defn.get("with_time"), bool):
        errors.append("with_time_not_bool")

    if set_name == SET_GARMIN:
        maps_to = defn.get("maps_to")
        if not isinstance(maps_to, str) or not maps_to.strip():
            errors.append("maps_to_missing")
    elif "maps_to" in defn:
        errors.append("maps_to_not_allowed")

    values = defn.get("values")
    if not isinstance(values, list) or not values:
        errors.append("values_missing")
    elif len(values) > MAX_VALUES:
        errors.append("values_too_many")
    else:
        seen = set()
        for index, value in enumerate(values):
            errors.extend(_check_value_definition(value, index, seen))
        errors.extend(_check_groups(values))
    return errors


def _check_groups(values):
    """Errors of the groups of alternatives: a group has at least two members and they stand together."""
    groups = [v.get("group") if isinstance(v, dict) and isinstance(v.get("group"), str) else None for v in values]
    errors = []
    for name in sorted({g for g in groups if g is not None}):
        positions = [i for i, g in enumerate(groups) if g == name]
        if len(positions) < 2:
            errors.append(f"group_single:{name}")
        elif positions[-1] - positions[0] + 1 != len(positions):
            errors.append(f"group_not_together:{name}")
    return errors


def _check_value_definition(value, index, seen):
    tag = f"value{index}"
    if not isinstance(value, dict):
        return [f"{tag}_not_a_dict"]
    errors = []
    for extra in sorted(set(value) - _VALUE_KEYS):
        errors.append(f"{tag}_unknown_key:{extra}")
    label = value.get("label")
    if not isinstance(label, str) or not label.strip():
        errors.append(f"{tag}_label_missing")
    elif label != clean_name(label):
        errors.append(f"{tag}_label_not_clean")
    elif len(label) > MAX_LABEL_LEN:
        errors.append(f"{tag}_label_too_long")
    else:
        folded = label.casefold()
        if folded in seen:
            errors.append(f"{tag}_label_duplicate")
        seen.add(folded)
    value_type = value.get("type")
    if value_type not in VALUE_TYPES:
        errors.append(f"{tag}_type_invalid")
    elif value_type == TYPE_NUMBER:
        unit = value.get("unit")
        if not isinstance(unit, str):
            errors.append(f"{tag}_unit_missing")
        elif len(unit) > MAX_UNIT_LEN:
            errors.append(f"{tag}_unit_too_long")
    elif "unit" in value:
        errors.append(f"{tag}_unit_not_allowed")
    if "group" in value:
        group = value["group"]
        if not isinstance(group, str) or not group.strip() or group != clean_name(group) or len(group) > MAX_LABEL_LEN:
            errors.append(f"{tag}_group_invalid")
        elif value_type != TYPE_NUMBER:
            errors.append(f"{tag}_group_not_allowed")
    return errors


def snapshot_of(defn):
    """The copy of a definition a day file keeps (no flags, no shared references)."""
    return copy.deepcopy({k: v for k, v in defn.items() if k in _DEFINITION_KEYS})


def definition_of(master_field):
    """The definition part of a field of the master file (the flags removed), as a copy."""
    return snapshot_of(master_field)


# ══════════════════════════════════════════════════════════════════════════════
#  Entries
# ══════════════════════════════════════════════════════════════════════════════

def check_entries(defn, entries):
    """
    Errors of the entries of one field on one day. defn is a valid definition.

    A field without time: at most one entry, no "time". A field with time: any number of entries,
    each with a valid "time". Every entry carries a non-empty "values" dict whose keys are labels
    of the definition (not every label has to be there) and whose values fit the label's type.
    """
    if not isinstance(entries, list):
        return ["entries_not_a_list"]
    if len(entries) > MAX_ENTRIES_PER_FIELD:
        return ["entries_too_many"]
    with_time = defn["with_time"]
    types = {v["label"]: v["type"] for v in defn["values"]}
    groups = {v["label"]: v["group"] for v in defn["values"] if "group" in v}
    errors = []
    if not with_time and len(entries) > 1:
        errors.append("entries_too_many_without_time")
    for index, entry in enumerate(entries):
        tag = f"entry{index}"
        if not isinstance(entry, dict):
            errors.append(f"{tag}_not_a_dict")
            continue
        for extra in sorted(set(entry) - _ENTRY_KEYS):
            errors.append(f"{tag}_unknown_key:{extra}")
        if with_time:
            if not valid_time(entry.get("time")):
                errors.append(f"{tag}_time_invalid")
        elif "time" in entry:
            errors.append(f"{tag}_time_not_allowed")
        values = entry.get("values")
        if not isinstance(values, dict) or not values:
            errors.append(f"{tag}_values_missing")
            continue
        used_groups = []
        for label, value in values.items():
            if label not in types:
                errors.append(f"{tag}_label_unknown")
                continue
            if label in groups:
                used_groups.append(groups[label])
            if types[label] == TYPE_NUMBER:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    errors.append(f"{tag}_value_not_a_number")
            elif types[label] == TYPE_TEXT:
                if not _is_text(value):
                    errors.append(f"{tag}_value_not_text")
            elif not isinstance(value, bool):
                errors.append(f"{tag}_value_not_yesno")
        if len(used_groups) != len(set(used_groups)):
            errors.append(f"{tag}_group_twice")
    return errors


def _is_text(value):
    """One line of free text: not empty (not only space), at most MAX_TEXT_LEN characters, no control characters."""
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT_LEN
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value))


# ══════════════════════════════════════════════════════════════════════════════
#  Whole files (what a reader checks before it trusts a file)
# ══════════════════════════════════════════════════════════════════════════════

def check_master(master):
    """Errors of the master file (fields.json) as read from disk."""
    if not isinstance(master, dict):
        return ["master_not_a_dict"]
    errors = []
    for extra in sorted(set(master) - _MASTER_KEYS):
        errors.append(f"master_unknown_key:{extra}")
    if master.get("schema_version") != SCHEMA_VERSION or isinstance(master.get("schema_version"), bool):
        errors.append("master_schema_version")
    next_id = master.get("next_id")
    if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < 1:
        errors.append("master_next_id")
        next_id = None
    fields = master.get("fields")
    if not isinstance(fields, dict):
        errors.append("master_fields_not_a_dict")
        return errors
    names = {}
    for key, field in fields.items():
        if not valid_key(key):
            errors.append(f"field_key_invalid:{key}")
            continue
        if not isinstance(field, dict):
            errors.append(f"field_not_a_dict:{key}")
            continue
        flags_ok = all(isinstance(field.get(flag), bool) for flag in _FLAG_KEYS)
        if not flags_ok:
            errors.append(f"field_flags:{key}")
        defn = {k: v for k, v in field.items() if k not in _FLAG_KEYS}
        errors.extend(f"{key}:{e}" for e in check_definition(defn))
        if defn.get("set") != (SET_GARMIN if is_garmin_key(key) else SET_USER):
            errors.append(f"field_set_mismatch:{key}")
        number = user_key_number(key)
        if number is not None and next_id is not None and number >= next_id:
            errors.append(f"field_key_beyond_next_id:{key}")
        folded = normalized_name(defn.get("name"))
        if folded:
            if folded in names:
                errors.append(f"field_name_duplicate:{key}")
            names[folded] = key
    return errors


def check_day(day, date_str):
    """Errors of a day file as read from disk; every entry is checked against the key_snapshot."""
    if not isinstance(day, dict):
        return ["day_not_a_dict"]
    errors = []
    for extra in sorted(set(day) - _DAY_KEYS):
        errors.append(f"day_unknown_key:{extra}")
    if day.get("schema_version") != SCHEMA_VERSION or isinstance(day.get("schema_version"), bool):
        errors.append("day_schema_version")
    if day.get("date") != date_str:
        errors.append("day_date_mismatch")
    created = day.get("created")
    try:
        datetime.fromisoformat(created)
        if not (isinstance(created, str) and valid_date(created[:10])):
            errors.append("day_created_invalid")
    except (TypeError, ValueError):
        errors.append("day_created_invalid")
    note = day.get("note")
    if not isinstance(note, str) or len(note) > MAX_NOTE_LEN:
        errors.append("day_note_invalid")
    snapshot = day.get("key_snapshot")
    entries = day.get("entries")
    if not isinstance(snapshot, dict):
        errors.append("day_snapshot_not_a_dict")
        snapshot = {}
    if not isinstance(entries, dict):
        errors.append("day_entries_not_a_dict")
        entries = {}
    for key, defn in snapshot.items():
        if not valid_key(key):
            errors.append(f"snapshot_key_invalid:{key}")
        else:
            errors.extend(f"snapshot:{key}:{e}" for e in check_definition(defn))
    for key, field_entries in entries.items():
        if key not in snapshot or check_definition(snapshot[key]):
            errors.append(f"entries_key_without_definition:{key}")
            continue
        errors.extend(f"entries:{key}:{e}" for e in check_entries(snapshot[key], field_entries))
    errors.extend(check_history(day.get("history"), snapshot))
    return errors


def check_history(history, snapshot):
    """
    Errors of the history of a day: a list of {"timestamp": 'YYYY-MM-DDTHH:MM:SS', "before": {"note", "entries"}},
    oldest first. "before" is the whole state the day had before a change; its entries are checked against the
    definitions the day keeps (the snapshot only gains keys, so a key of an old state is still there).
    """
    if not isinstance(history, list):
        return ["day_history_invalid"]
    errors = []
    for index, item in enumerate(history):
        tag = f"history{index}"
        if not isinstance(item, dict):
            errors.append(f"{tag}_not_a_dict")
            continue
        for extra in sorted(set(item) - _HISTORY_KEYS):
            errors.append(f"{tag}_unknown_key:{extra}")
        if not valid_timestamp(item.get("timestamp")):
            errors.append(f"{tag}_timestamp_invalid")
        before = item.get("before")
        if not isinstance(before, dict) or set(before) != _BEFORE_KEYS:
            errors.append(f"{tag}_before_invalid")
            continue
        note = before["note"]
        if not isinstance(note, str) or len(note) > MAX_NOTE_LEN:
            errors.append(f"{tag}_note_invalid")
        entries = before["entries"]
        if not isinstance(entries, dict):
            errors.append(f"{tag}_entries_not_a_dict")
            continue
        for key, field_entries in entries.items():
            if not isinstance(snapshot, dict) or key not in snapshot or check_definition(snapshot[key]):
                errors.append(f"{tag}_key_without_definition:{key}")
                continue
            errors.extend(f"{tag}:{key}:{e}" for e in check_entries(snapshot[key], field_entries))
    return errors


# ══════════════════════════════════════════════════════════════════════════════
#  Search in notes (pure; shared by diary_reader.search_notes and the MCP tool search_diary_notes, v1.7.8.1)
# ══════════════════════════════════════════════════════════════════════════════

MIN_QUERY_LEN = 2           # characters of all words together
MAX_QUERY_LEN = 200
SNIPPET_BEFORE = 40
SNIPPET_AFTER = 80


def parse_query(query):
    """
    (patterns, reason): the words of the query as case-insensitive literal patterns and reason None, or
    (None, "query_too_short" | "query_too_long") for a query that is not searched.
    """
    words = query.split() if isinstance(query, str) else []
    if sum(len(w) for w in words) < MIN_QUERY_LEN:
        return None, "query_too_short"
    if len(query) > MAX_QUERY_LEN:
        return None, "query_too_long"
    return [re.compile(re.escape(w), re.IGNORECASE) for w in words], None


def note_snippet(note, patterns):
    """
    None unless every word is in the note (spaces tidied); else a piece of the tidied note around the first
    word, with "…" where the note goes on.
    """
    text = " ".join(note.split())
    if not all(pattern.search(text) for pattern in patterns):
        return None
    match = patterns[0].search(text)
    start = max(0, match.start() - SNIPPET_BEFORE)
    end = min(len(text), match.end() + SNIPPET_AFTER)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
