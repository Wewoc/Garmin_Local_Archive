#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/diary_reader.py

DIARY v1.7.8 — REMOVABLE. Reads the diary: read only, never writes (diary_writer.py is the sole
writer of diary_data/). Imports only diary_model of this package and the standard library.

Every read answers with a state next to the data, nothing raises:

  "ok"           the file was read and passed its checks; the data is returned
  "missing"      there is no such file
  "damaged"      the file cannot be read, is not JSON, or fails its checks
  "unsupported"  the file is written by a newer version (schema_version above this one): never
                 interpreted, never overwritten (downgrade protection)
  "invalid_date" (read_day only) the date is not a real date

Public API:
  read_master(base_dir)        -> (state, master dict | None)
  read_day(base_dir, date_str) -> (state, day dict | None)
  list_days(base_dir)          -> sorted list of the dates that have a day file (file names only)
  search_notes(base_dir, query, limit=MAX_SEARCH_HITS) -> {"ok", "hits", "searched", "unreadable", "truncated"}

The search (Baustein 3) looks in the notes of the days only, not in the entries and not in the history. The words
of the query all have to be in a note (upper and lower case are the same, the characters of a word are taken
literally, no pattern); a hit is the date and a short piece of the note around the first word, newest day first.
A day that cannot be read is skipped and counted (unreadable), never silently left out. Nothing is written and
no line of the log carries a word of the query or a note.
"""

import json
import logging
import re

from . import diary_model as dm

log = logging.getLogger(__name__)

OK = "ok"
MISSING = "missing"
DAMAGED = "damaged"
UNSUPPORTED = "unsupported"
INVALID_DATE = "invalid_date"

MAX_SEARCH_HITS = 200
MIN_QUERY_LEN = 2           # characters of all words together
MAX_QUERY_LEN = 200
_SNIPPET_BEFORE = 40
_SNIPPET_AFTER = 80


def _load_json(path):
    """(state, data): OK with the parsed JSON, MISSING, or DAMAGED. Logs the kind of error only."""
    if not path.is_file():
        return MISSING, None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return OK, json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        # ValueError covers UnicodeDecodeError and JSONDecodeError. No content, no path of a
        # day in the line: the file holds health data.
        log.warning("diary: a file could not be read (%s)", type(exc).__name__)
        return DAMAGED, None


def _too_new(data):
    version = data.get("schema_version") if isinstance(data, dict) else None
    return isinstance(version, int) and not isinstance(version, bool) and version > dm.SCHEMA_VERSION


def read_master(base_dir):
    """The master file fields.json: (state, master)."""
    state, data = _load_json(dm.fields_path(base_dir))
    if state != OK:
        return state, None
    if _too_new(data):
        return UNSUPPORTED, None
    if dm.check_master(data):
        log.warning("diary: the field list failed its checks")
        return DAMAGED, None
    return OK, data


def read_day(base_dir, date_str):
    """The day file of one date: (state, day)."""
    path = dm.day_path(base_dir, date_str)
    if path is None:
        return INVALID_DATE, None
    state, data = _load_json(path)
    if state != OK:
        return state, None
    if _too_new(data):
        return UNSUPPORTED, None
    if dm.check_day(data, date_str):
        log.warning("diary: day %s failed its checks", date_str)
        return DAMAGED, None
    return OK, data


def list_days(base_dir):
    """
    The dates with a day file, sorted. Only the names are looked at (a file is not opened):
    names that are not exactly 'diary_YYYY-MM-DD.json' of a real date (a .tmp, a wrong date, a
    folder) are not days.
    """
    folder = dm.days_dir(base_dir)
    if not folder.is_dir():
        return []
    dates = []
    for entry in folder.iterdir():
        date_str = dm.date_of_day_file_name(entry.name)
        if date_str is not None and entry.is_file():
            dates.append(date_str)
    return sorted(dates)


def _snippet(text, match):
    """A piece of the (already tidied) note around a match, with "…" where the note goes on."""
    start = max(0, match.start() - _SNIPPET_BEFORE)
    end = min(len(text), match.end() + _SNIPPET_AFTER)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def search_notes(base_dir, query, limit=MAX_SEARCH_HITS):
    """
    The days whose note holds every word of the query, newest first (see the top of this file).

    {"ok": True, "hits": [{"date", "snippet"}, ...], "searched": days read, "unreadable": days skipped,
     "truncated": True when more than `limit` days match (the oldest are left out)}
    {"ok": False, "reason": "query_too_short" | "query_too_long", "hits": []}  for a query that is not searched
    """
    refused = {"ok": False, "hits": [], "searched": 0, "unreadable": 0, "truncated": False}
    words = query.split() if isinstance(query, str) else []
    if sum(len(w) for w in words) < MIN_QUERY_LEN:
        return {**refused, "reason": "query_too_short"}
    if len(query) > MAX_QUERY_LEN:
        return {**refused, "reason": "query_too_long"}
    patterns = [re.compile(re.escape(w), re.IGNORECASE) for w in words]
    hits, searched, unreadable, truncated = [], 0, 0, False
    for date_str in sorted(list_days(base_dir), reverse=True):
        state, day = read_day(base_dir, date_str)
        if state != OK:
            unreadable += 1
            continue
        searched += 1
        note = " ".join(day["note"].split())
        if not all(pattern.search(note) for pattern in patterns):
            continue
        if len(hits) >= limit:
            truncated = True
            break
        hits.append({"date": date_str, "snippet": _snippet(note, patterns[0].search(note))})
    return {"ok": True, "hits": hits, "searched": searched, "unreadable": unreadable, "truncated": truncated}
