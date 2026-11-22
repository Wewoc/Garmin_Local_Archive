#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
dash_diary.py

DIARY v1.7.8.1 — REMOVABLE. Sole owner of the shaping of the diary for the dashboards: the
text of one day (note, entries as "HH:MM name: value unit") and the presence rows (one row per
field that has an entry in the range, plus the row "Note"). Shared by the Sleep and the
Explorer specialists.

Rules:
- Pure shaping. No file I/O and no import of a broker: the broker (maps/diary_map.py) is handed in by
  the specialist, which is the only caller of it (specialists read through brokers, layouts never).
- Called by specialists in dashboards/ — never by plotters.
- What leaves here is the note, the entries and the field names of the days in the range. The
  "history" of a day never reaches this module (diary_map does not return it).
- No log line (this module logs nothing).
"""


def _number_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(value, ".10g") if isinstance(value, float) else str(value)


def _value_text(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return _number_text(value)
    return str(value)


def format_entry(definition: dict, entry: dict) -> dict:
    """
    One entry as {"time": "HH:MM" or "", "name": field name, "text": "label: value unit, ..."}.
    The labels follow the order of the definition; a label the definition does not know is skipped.
    """
    units = {v["label"]: v.get("unit") for v in definition.get("values", [])}
    values = entry.get("values", {})
    parts = []
    for label in (v["label"] for v in definition.get("values", [])):
        if label not in values:
            continue
        unit = units.get(label)
        parts.append(f"{label}: {_value_text(values[label])}" + (f" {unit}" if unit else ""))
    return {"time": entry.get("time") or "", "name": definition.get("name", ""), "text": ", ".join(parts)}


def format_day(day: dict):
    """
    {"note": str, "entries": [{"time", "name", "text"}, ...]} for a diary_map.get_day() answer,
    entries in time order (an entry without a time first), or None when the day is not "ok" or has
    neither a note nor an entry.
    """
    if not isinstance(day, dict) or day.get("state") != "ok":
        return None
    entries = []
    for key in sorted(day["entries"]):
        definition = day["definitions"].get(key)
        if definition is None:
            continue
        entries.extend(format_entry(definition, e) for e in day["entries"][key])
    entries.sort(key=lambda e: (e["time"], e["name"].lower()))
    note = day["note"] if day["note"].strip() else ""
    if not note and not entries:
        return None
    return {"note": note, "entries": entries}


def presence_rows(presence: dict) -> list:
    """
    [{"name": "Note" | field name, "dates": [date, ...]}, ...] from a diary_map.get_presence() answer:
    "Note" first, then the fields by name; a row without a date is left out. Names are shown as they
    are (the broker gives the current name).
    """
    if not isinstance(presence, dict) or presence.get("state") != "ok":
        return []
    days = presence["days"]
    rows = []
    note_dates = sorted(d for d, info in days.items() if info["note"])
    if note_dates:
        rows.append({"name": "Note", "dates": note_dates})
    for key in sorted(presence["fields"], key=lambda k: (presence["fields"][k].lower(), k)):
        dates = sorted(d for d, info in days.items() if key in info["fields"])
        if dates:
            rows.append({"name": presence["fields"][key], "dates": dates})
    return rows


def build_payload(broker, base_dir, date_from: str, date_to: str) -> dict:
    """
    The diary of the range for a dashboard, from the broker handed in (maps/diary_map.py):

    {"days": {date: {"note", "entries"}}, "rows": [...presence rows...],
     "damaged": n, "unsupported": n}

    "days" holds the days that have a note or an entry. Days that cannot be read are counted
    (never left out silently): the renderer shows the numbers. An empty base_dir or a bad range gives
    the empty payload (no error: the dashboard simply has no diary part).
    """
    payload = {"days": {}, "rows": [], "damaged": 0, "unsupported": 0}
    if not base_dir:
        return payload
    presence = broker.get_presence(base_dir, date_from, date_to)
    if presence.get("state") != "ok":
        return payload
    payload["rows"] = presence_rows(presence)
    payload["damaged"] = len(presence["damaged"])
    payload["unsupported"] = len(presence["unsupported"])
    for date_str in sorted(presence["days"]):
        info = presence["days"][date_str]
        if not info["note"] and not info["fields"]:
            continue
        formatted = format_day(broker.get_day(base_dir, date_str))
        if formatted is None:
            payload["damaged"] += 1       # the file went bad between the two reads
            continue
        payload["days"][date_str] = formatted
    return payload
