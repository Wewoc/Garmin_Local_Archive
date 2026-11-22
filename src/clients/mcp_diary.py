#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_diary.py
Garmin Local Archive — MCP diary tools (v1.7.8.1) — REMOVABLE

list_diary_fields() / query_diary() / search_diary_notes(): three MCP tools that read the diary from the cache
(mcp_sql.mcp_diary_days, filled by clients/mcp_update.py only while "Diary in MCP" is on). Same layout as
clients/mcp_stats.py: plain, undecorated functions; clients/mcp_server.py imports this module and registers them
with mcp.tool() — and only when the switch was on when the server started, so with the switch off this module is
not even imported and the tools do not exist.

What the tools hand out: what the user typed by hand — note, entries, field names — never the "history" of a day
(the cache does not hold it). No daily value, no merging with Garmin values: where a diary field and a Garmin
field share a topic (weight, blood pressure) they are two sources, and the model is told so.

Every call looks at the switch again (garmin_config.read_diary_optin(), read fresh): a switch turned off while the
server runs makes the tools answer "switched off" at once instead of serving the cache until the next sync.

Finding a field (the diary's fields are named by the user, so there is no alias table): exact key or name (case
does not matter) -> a part of a name that is in exactly one name -> difflib near-match, the shared _match_field
step of the other tools (one hit resolves, the substitution is marked in "_meta"; several hits or several names
are returned as did_you_mean) -> a name that is a Garmin field gets a pointer to query_health/query_context ->
otherwise an error with did_you_mean and the short list of the fields that exist. The other direction:
diary_pointer() gives the unknown-field errors of query_health/query_context a pointer to query_diary.
"""

import datetime

from diary import diary_model as dm
from garmin import garmin_config as cfg
import mcp_sql
from mcp_context import resolve_context_field
from mcp_health import resolve_health_field
from mcp_query_common import _match_field

TOOL_NAMES = ("list_diary_fields", "query_diary", "search_diary_notes")

MAX_QUERY_DAYS = 366          # query_diary: more than this in one call is refused, not cut
SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 200
FIELDS_IN_ERROR_MAX = 30      # the list of existing fields in an "unknown field" error

_SOURCE_NOTE = ("Typed by hand by the user, not measured: it exists only for days the user wrote something. "
                "Measured Garmin values are in query_health; weight and blood pressure can be in both and are "
                "separate sources, not merged.")


def _switched_off():
    """None while "Diary in MCP" is on, else the answer every tool gives."""
    if cfg.read_diary_optin()[0]:
        return None
    return {"error": "Diary in MCP is switched off: the diary is not available through the MCP server."}


def _fields() -> list:
    return mcp_sql.get_diary_fields()["fields"]


def diary_field_names() -> list:
    """The names of the diary's fields, sorted (for list_available_fields)."""
    return sorted(f["name"] for f in _fields())


# ── Finding a field ──────────────────────────────────────────────────────────

def _match_diary_field(raw_name: str, fields: list):
    """
    ("resolved", field, substituted) | ("ambiguous", [names]) | ("unknown", [near names]).
    substituted is False only when raw_name was the key or the name exactly as stored.
    """
    q = raw_name.strip()
    ql = q.lower()
    by_key = {f["key"].lower(): f for f in fields}
    by_name = {f["name"].lower(): f for f in fields}
    if ql in by_key:
        field = by_key[ql]
        return "resolved", field, q != field["key"]
    if ql in by_name:
        field = by_name[ql]
        return "resolved", field, q != field["name"]
    if len(ql) >= 3:
        hits = [f for f in fields if ql in f["name"].lower()]
        if len(hits) == 1:
            return "resolved", hits[0], True
        if len(hits) > 1:
            return "ambiguous", sorted(f["name"] for f in hits)
    near = _match_field(ql, q, set(by_name))
    if "resolved_field" in near:
        return "resolved", by_name[near["resolved_field"]], True
    return "unknown", [by_name[n]["name"] for n in near.get("did_you_mean", [])]


def _garmin_pointer(name: str):
    """An error text when name is a Garmin field (so it belongs to query_health/query_context), else None."""
    health = resolve_health_field(name.lower())
    if "resolved_field" in health:
        return f"{name!r} is a Garmin field (measured), not a diary field -- use query_health"
    if "ambiguous" in health.get("error", "") or "raw field" in health.get("error", ""):
        return f"{name!r} is a Garmin field (measured), not a diary field -- use query_health ({health['error']})"
    context = resolve_context_field(name.lower())
    if "resolved_field" in context:
        return f"{name!r} is a Garmin context field, not a diary field -- use query_context"
    return None


def _resolve_field(field):
    """(field dict, substituted, None) or (None, False, error dict)."""
    fields = _fields()
    if not isinstance(field, str) or not field.strip():
        return None, False, {"error": "field must be a diary field name or key (see list_diary_fields)"}
    if not fields:
        return None, False, {"error": "the diary has no fields yet"}
    kind, *rest = _match_diary_field(field, fields)
    if kind == "resolved":
        return rest[0], rest[1], None
    if kind == "ambiguous":
        return None, False, {
            "error": f"field {field!r} matches several diary fields -- please specify one of: {', '.join(rest[0])}",
            "did_you_mean": rest[0],
        }
    pointer = _garmin_pointer(field)
    if pointer is not None:
        return None, False, {"error": pointer}
    error = {"error": f"unknown diary field {field!r}",
             "available_fields": sorted(f["name"] for f in fields)[:FIELDS_IN_ERROR_MAX]}
    if rest[0]:
        error["did_you_mean"] = rest[0]
    return None, False, error


def diary_pointer(field):
    """
    For the unknown-field errors of query_health/query_context (via mcp_query_common.diary_hint): a pointer text
    when `field` is (or matches) a diary field, else None. None while the switch is off, and never raises.
    """
    try:
        if not (cfg.MCP_DIARY_ENABLED and cfg.read_diary_optin()[0]):
            return None
        kind, *rest = _match_diary_field(field, _fields())
        if kind == "resolved":
            return f"a diary field {rest[0]['name']!r} exists (typed by hand) -- use query_diary"
        if kind == "ambiguous":
            return f"several diary fields match ({', '.join(rest[0])}) -- use query_diary"
    except Exception:
        return None
    return None


# ── Tools ────────────────────────────────────────────────────────────────────

def list_diary_fields() -> dict:
    """List the fields of the user's hand-typed diary (medication, alcohol, blood pressure, a walk, ... whatever the
    user chose to write down) with their value labels, units and whether an entry carries a time of day, plus how
    many days have content. Call this first when you do not know a diary field name for query_diary. The diary is
    typed by hand and not measured: it has content only for days the user wrote something. "maps_to" names the
    Garmin counterpart where there is one (weight, blood pressure); the two are separate sources and are not
    merged."""
    off = _switched_off()
    if off is not None:
        return off
    info = mcp_sql.get_diary_fields()
    fields = [
        {
            "key": f["key"], "name": f["name"], "with_time": f.get("with_time", False),
            "archived": bool(f.get("archived", False)), "maps_to": f.get("maps_to"),
            "values": [{"label": v["label"], "type": v["type"], "unit": v.get("unit") or None}
                       for v in f.get("values", [])],
        }
        for f in sorted(info["fields"], key=lambda f: f["key"])
    ]
    return {"diary": {"fields": fields, "first_day": info["first_day"], "last_day": info["last_day"],
                      "days_with_content": info["days"]},
            "_meta": {"source": "diary", "note": _SOURCE_NOTE}}


def _entry_rows(day: dict, key_filter) -> list:
    rows = []
    for key, entries in day["entries"].items():
        if key_filter is not None and key != key_filter:
            continue
        definition = day["definitions"].get(key, {})
        units = {v["label"]: v.get("unit") for v in definition.get("values", [])}
        labels = [v["label"] for v in definition.get("values", [])]
        for entry in entries:
            values = [{"label": label, "value": entry["values"][label], "unit": units.get(label) or None}
                      for label in labels if label in entry["values"]]
            rows.append({"date": day["date"], "time": entry.get("time"), "field": definition.get("name", key),
                         "key": key, "values": values})
    return rows


def query_diary(date_from: str, date_to: str, field: str | None = None, include_notes: bool = False) -> dict:
    """Read what the user typed by hand into the diary for a date range (both dates inclusive, YYYY-MM-DD, at most
    366 days): the entries exactly as typed, each with date, time of day (null for a field without a time), the
    field name and its values with units. This is NOT measured data: there are entries only for days the user wrote
    something. Use query_health for measured Garmin values; weight and blood pressure can exist in both and are
    separate sources, not merged. field: a diary field name or key (see list_diary_fields; near matches and parts
    of a name are resolved, a Garmin field name is answered with a pointer to query_health); omit it for all
    fields. include_notes=true also returns the free-text note of each day in the range (otherwise use
    search_diary_notes to find notes). Result: "diary" with "entries" (and "notes" when asked) and "_meta"."""
    off = _switched_off()
    if off is not None:
        return off
    if not (isinstance(date_from, str) and isinstance(date_to, str) and dm.valid_date(date_from) and dm.valid_date(date_to)):
        return {"error": "date_from and date_to must be real dates in the form YYYY-MM-DD"}
    if date_from > date_to:
        return {"error": "date_from is after date_to"}
    span = (datetime.date.fromisoformat(date_to) - datetime.date.fromisoformat(date_from)).days + 1
    if span > MAX_QUERY_DAYS:
        return {"error": f"range too large ({span} days): at most {MAX_QUERY_DAYS} days per call -- narrow the range"}

    key_filter, substituted, field_name = None, False, None
    if field is not None:
        resolved, substituted, error = _resolve_field(field)
        if error is not None:
            return error
        key_filter, field_name = resolved["key"], resolved["name"]

    rng = mcp_sql.get_diary_range(date_from, date_to)
    days = rng["diary"]["days"]
    entries, notes = [], []
    for day in days:
        entries.extend(_entry_rows(day, key_filter))
        if include_notes and isinstance(day.get("note"), str) and day["note"].strip():
            notes.append({"date": day["date"], "note": day["note"]})
    entries.sort(key=lambda e: (e["date"], e["time"] or "", e["field"].lower()))

    diary = {"entries": entries}
    if include_notes:
        diary["notes"] = notes
    meta = {**rng["_meta"], "source": "diary", "note": _SOURCE_NOTE, "days_with_content": len(days)}
    if field_name is not None:
        meta["field_used"] = field_name
        if substituted:
            meta["field_resolved_from"] = field
    if not entries and not notes:
        meta["empty"] = "no diary entries in this range"
    return {"diary": diary, "_meta": meta}


def search_diary_notes(query: str, limit: int = SEARCH_DEFAULT_LIMIT) -> dict:
    """Search the free-text notes the user typed into the diary by hand. Every word of the query has to be in the
    note (upper and lower case do not matter, the words are taken literally, no pattern); a hit is the date and a
    short piece of the note around the first word, newest day first. At most `limit` hits (default 50, largest
    200). Only the notes are searched, not the entries (use query_diary for those). The diary is typed by hand and
    not measured. Result: "diary" with "hits", "searched" (days with a note) and "truncated"."""
    off = _switched_off()
    if off is not None:
        return off
    patterns, reason = dm.parse_query(query)
    if reason == "query_too_short":
        return {"error": f"query too short: at least {dm.MIN_QUERY_LEN} characters"}
    if reason == "query_too_long":
        return {"error": f"query too long: at most {dm.MAX_QUERY_LEN} characters"}
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        limit = SEARCH_DEFAULT_LIMIT
    limit = min(limit, SEARCH_MAX_LIMIT)
    hits, searched, truncated = [], 0, False
    for date_str, note in mcp_sql.get_diary_notes():
        searched += 1
        snippet = dm.note_snippet(note, patterns)
        if snippet is None:
            continue
        if len(hits) >= limit:
            truncated = True
            break
        hits.append({"date": date_str, "snippet": snippet})
    return {"diary": {"hits": hits, "searched": searched, "truncated": truncated},
            "_meta": {"source": "diary", "note": _SOURCE_NOTE}}
