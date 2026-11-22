#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
maps/diary_map.py

DIARY v1.7.8 — REMOVABLE. The read-only broker of the diary: the one place where the diary is
offered to the rest of the program (dashboards now, the MCP cache later). It reads through
diary/diary_reader.py only, never writes (diary_writer.py is the sole writer of diary_data/), and has
no source fan-out and no field registry of its own: the field list is the master file of the diary.

NOT registered in gateway_map and not known to mcp_map: the diary reaches the MCP only through an
opt-in, which is a later step (see KONZEPT_tagebuch_anbindung.md, layer 3).

Public API (base_dir is the archive folder that holds diary_data/; every answer but list_days carries
a "state", and nothing raises):

  list_fields(base_dir)                       -> {"state", "fields": [...]}
  list_days(base_dir)                         -> sorted list of the dates that have a day file
  get_day(base_dir, date_str)                 -> {"state", "date", "note", "entries", "definitions"}
  get_presence(base_dir, date_from, date_to)  -> {"state", "days", "fields", "damaged", "unsupported", ...}
  get_cache_feed(base_dir)                    -> {"fields", "days": {date: {"state", "hash", "payload"}}} (MCP cache sync)

States are the ones of the reader ("ok", "missing", "damaged", "unsupported", "invalid_date") plus
"invalid_range" (date_from after date_to). A day that cannot be read is counted and named by its
date in get_presence, never silently left out.

What leaves this module: the note, the entries and the definitions of the day (key_snapshot). The
"history" of a day holds earlier states, including text the user deleted: it never leaves the diary
package. No line of the log carries a note, an entry or a field name (this module logs nothing).
"""

import copy

from diary import diary_model as dm
from diary import diary_reader as rd

def list_fields(base_dir):
    """
    The fields of the diary: {"state": <state of the master file>, "fields": [...]}.

    A field is {"key", "name", "set", "with_time", "values", "maps_to"?, "favorite", "archived"}, sorted
    by key. Archived fields are listed (their old days still hold entries); the flag tells them apart.
    The fields are copies. Anything but "ok" gives an empty list.
    """
    if not base_dir:
        return {"state": rd.MISSING, "fields": []}
    state, master = rd.read_master(base_dir)
    if state != rd.OK:
        return {"state": state, "fields": []}
    fields = []
    for key in sorted(master["fields"]):
        field = copy.deepcopy(master["fields"][key])
        field["key"] = key
        fields.append(field)
    return {"state": rd.OK, "fields": fields}


def list_days(base_dir):
    """The dates that have a day file, sorted. Only file names are looked at (nothing is opened)."""
    if not base_dir:
        return []
    return rd.list_days(base_dir)


def get_day(base_dir, date_str):
    """
    One day: {"state", "date"} when it cannot be read, else
    {"state": "ok", "date", "note", "entries", "definitions"}.

    "entries" is {key: [{"time"?, "values": {label: value}}, ...]}, "definitions" is the key_snapshot of the
    day ({key: definition}). Both are copies. There is no "history" in the answer.
    """
    if not base_dir:
        return {"state": rd.MISSING, "date": date_str}
    state, day = rd.read_day(base_dir, date_str)
    if state != rd.OK:
        return {"state": state, "date": date_str}
    return {
        "state": rd.OK,
        "date": date_str,
        "note": day["note"],
        "entries": copy.deepcopy(day["entries"]),
        "definitions": copy.deepcopy(day["key_snapshot"]),
    }


def get_cache_feed(base_dir):
    """
    Everything the MCP cache needs from the diary, read in one pass (v1.7.8.1; the only caller is the cache sync,
    and only with the opt-in on):

    {"fields": <list_fields() answer>,
     "days":   {date: {"state": <reader state>, "hash": SHA-256 of the file's bytes | None,
                       "payload": {"note", "entries", "definitions"} | None}}}

    Every day file is listed. The payload (the same as get_day()'s, copies, no "history") is there only for a day
    that is "ok"; a damaged day or a day of a newer version comes with its state and hash and no payload, so the
    cache can count it instead of silently missing it. No base folder gives no days.
    """
    if not base_dir:
        return {"fields": {"state": rd.MISSING, "fields": []}, "days": {}}
    days = {}
    for date_str in rd.list_days(base_dir):
        state, day, digest = rd.read_day_hashed(base_dir, date_str)
        payload = None
        if state == rd.OK:
            payload = {
                "note": day["note"],
                "entries": copy.deepcopy(day["entries"]),
                "definitions": copy.deepcopy(day["key_snapshot"]),
            }
        days[date_str] = {"state": state, "hash": digest, "payload": payload}
    return {"fields": list_fields(base_dir), "days": days}


def get_presence(base_dir, date_from, date_to):
    """
    Which fields have an entry, and whether there is a note, on each day of the range (both dates inclusive).

    {
      "state":       "ok",
      "date_from", "date_to",
      "days":        {date: {"note": bool, "fields": [key, ...]}},   # days that were read, "fields" sorted
      "fields":      {key: name},                                    # every key seen, plus the name to show
      "damaged":     [date, ...],                                    # day files that cannot be read
      "unsupported": [date, ...],                                    # day files of a newer version
      "master":      state of the master file,
    }
    A day file without a note and without entries is a day in "days" with note False and no fields. Names come
    from the master file when it is readable (the current name), else from the newest day that holds the key.
    A bad range gives {"state": "invalid_date" | "invalid_range"} and nothing else.
    """
    if not (dm.valid_date(date_from) and dm.valid_date(date_to)):
        return {"state": rd.INVALID_DATE}
    if date_from > date_to:
        return {"state": "invalid_range"}
    result = {
        "state": rd.OK, "date_from": date_from, "date_to": date_to,
        "days": {}, "fields": {}, "damaged": [], "unsupported": [], "master": rd.MISSING,
    }
    if not base_dir:
        return result
    names = {}
    for date_str in rd.list_days(base_dir):
        if not date_from <= date_str <= date_to:
            continue
        state, day = rd.read_day(base_dir, date_str)
        if state == rd.UNSUPPORTED:
            result["unsupported"].append(date_str)
            continue
        if state != rd.OK:
            result["damaged"].append(date_str)       # "missing" here means the file vanished while we read
            continue
        keys = sorted(key for key, entries in day["entries"].items() if entries)
        result["days"][date_str] = {"note": bool(day["note"].strip()), "fields": keys}
        for key in keys:
            names[key] = day["key_snapshot"][key]["name"]     # days come oldest first: the newest name wins
    master_state, master = rd.read_master(base_dir)
    result["master"] = master_state
    if master_state == rd.OK:
        for key in names:
            if key in master["fields"]:
                names[key] = master["fields"][key]["name"]
    result["fields"] = names
    return result
