#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_diary_map.py — maps/diary_map.py (the read-only broker of the diary)
DIARY v1.7.8 — removable (together with src/diary/ and src/maps/diary_map.py).

Covers: list_fields (sorted, copies, flags, damaged/unsupported/missing master), list_days, get_day (content,
definitions from the key_snapshot, no history and no deleted text in the answer, copies, every state),
get_presence (range inclusive, note row, sorted keys, names: master first, snapshot as fallback, newest day wins,
damaged and unsupported days counted and named, bad range), read-only behaviour (the folder is byte-identical
after every call), no content in the log, and guards (imports only the diary package and the standard
library; not registered in gateway_map and not known to mcp_map).

Run from the project folder:
    python tests/test_diary_map.py

Everything is built here in a temporary folder — no archive of the maintainer is needed or touched.
"""

import ast
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

_SRC = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC))

from diary import diary_model as dm  # noqa: E402
from diary import diary_writer as wr  # noqa: E402
from maps import diary_map as dmap  # noqa: E402

_ROOT = _TMPDIR / "diary_map_tests"
shutil.rmtree(_ROOT, ignore_errors=True)
_ROOT.mkdir(parents=True)
_COUNTER = [0]

TABLET = [{"label": "Anzahl", "type": "number", "unit": "Stück"}]
YESNO = [{"label": "Ja/Nein", "type": "yesno"}]
SECRET = "GEHEIMWORT-Rückenschmerz"


def new_base():
    _COUNTER[0] += 1
    path = _ROOT / f"b{_COUNTER[0]}"
    path.mkdir()
    return path


def at(day, hour=9):
    """A clock on the given day: the day is 'today' for the free-edit window of save_day."""
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_raw(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def tree_bytes(base):
    """Every file of the diary folder with its bytes: what a read-only module must leave untouched."""
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(Path(base).rglob("*")) if p.is_file()}


def prepared_base():
    """U0001 Schmerztablette (with time), U0002 Spazieren (yes/no), G001 Blood pressure; four days."""
    base = new_base()
    assert wr.create_user_field(base, "Schmerztablette", TABLET, True)["key"] == "U0001"
    assert wr.create_user_field(base, "Spazieren gegangen", YESNO, False)["key"] == "U0002"
    assert wr.activate_catalog_field(base, "G001")["status"] == "written"
    pill = [{"time": "07:15", "values": {"Anzahl": 2}}]
    walk = [{"values": {"Ja/Nein": True}}]
    assert wr.save_day(base, "2026-11-10", "ein Tag mit Notiz", {"U0001": pill, "U0002": walk}, now=at("2026-11-10"))["status"] == "written"
    assert wr.save_day(base, "2026-11-12", "nur Notiz", {}, now=at("2026-11-12"))["status"] == "written"
    assert wr.save_day(base, "2026-11-14", "", {"U0002": walk}, now=at("2026-11-14"))["status"] == "written"
    assert wr.save_day(base, "2026-11-16", "Ende", {"U0001": pill}, now=at("2026-11-16"))["status"] == "written"
    return base


# ══════════════════════════════════════════════════════════════════════════════
section("1. list_fields")
# ══════════════════════════════════════════════════════════════════════════════

empty = new_base()
check("no diary folder: state missing and no fields", dmap.list_fields(empty) == {"state": "missing", "fields": []})
check("no base folder at all: state missing", dmap.list_fields(None) == {"state": "missing", "fields": []})

base = prepared_base()
res = dmap.list_fields(base)
check("a readable master: state ok", res["state"] == "ok")
check("the fields are sorted by key", [f["key"] for f in res["fields"]] == ["G001", "U0001", "U0002"])
first = res["fields"][1]
check("a field carries its name, set, time flag, values and both flags",
      first["name"] == "Schmerztablette" and first["set"] == "user" and first["with_time"] is True
      and first["values"] == [{"label": "Anzahl", "type": "number", "unit": "Stück"}]
      and first["favorite"] is False and first["archived"] is False)
check("a catalogue field carries maps_to", res["fields"][0]["maps_to"] == "get_blood_pressure")

wr.set_flags(base, "U0002", favorite=True, archived=True)
flags = {f["key"]: (f["favorite"], f["archived"]) for f in dmap.list_fields(base)["fields"]}
check("an archived field is still listed, its flags are shown", flags["U0002"] == (True, True) and flags["U0001"] == (False, False))

res["fields"][1]["name"] = "verändert"
res["fields"][1]["values"].append({"label": "x"})
again = dmap.list_fields(base)["fields"][1]
check("the answer holds copies: changing it changes nothing in the next read",
      again["name"] == "Schmerztablette" and len(again["values"]) == 1)

damaged = new_base()
write_raw(dm.fields_path(damaged), "{not json")
check("a damaged master: state damaged, no fields", dmap.list_fields(damaged) == {"state": "damaged", "fields": []})
newer = new_base()
write_json(dm.fields_path(newer), {"schema_version": 99})
check("a master of a newer version: state unsupported, no fields", dmap.list_fields(newer) == {"state": "unsupported", "fields": []})

# ══════════════════════════════════════════════════════════════════════════════
section("2. list_days")
# ══════════════════════════════════════════════════════════════════════════════

check("the dates of the day files, sorted", dmap.list_days(base) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])
check("no diary folder: an empty list", dmap.list_days(empty) == [])
check("no base folder: an empty list", dmap.list_days(None) == [])

# ══════════════════════════════════════════════════════════════════════════════
section("3. get_day")
# ══════════════════════════════════════════════════════════════════════════════

day = dmap.get_day(base, "2026-11-10")
check("a day: state ok, date, note", day["state"] == "ok" and day["date"] == "2026-11-10" and day["note"] == "ein Tag mit Notiz")
check("a day: the entries by key", day["entries"] == {"U0001": [{"time": "07:15", "values": {"Anzahl": 2}}],
                                                       "U0002": [{"values": {"Ja/Nein": True}}]})
check("a day: the definitions are the key_snapshot of the day",
      set(day["definitions"]) == {"U0001", "U0002"} and day["definitions"]["U0001"]["name"] == "Schmerztablette"
      and day["definitions"]["U0001"]["values"] == TABLET + [] and day["definitions"]["U0001"]["with_time"] is True)
check("a day: exactly these keys and no history", set(day) == {"state", "date", "note", "entries", "definitions"})

day["entries"]["U0001"][0]["values"]["Anzahl"] = 99
day["definitions"]["U0001"]["name"] = "verändert"
again = dmap.get_day(base, "2026-11-10")
check("the answer holds copies: changing it changes nothing in the next read",
      again["entries"]["U0001"][0]["values"]["Anzahl"] == 2 and again["definitions"]["U0001"]["name"] == "Schmerztablette")

check("a date without a file: state missing", dmap.get_day(base, "2026-11-11") == {"state": "missing", "date": "2026-11-11"})
check("a date that is not a date: state invalid_date", dmap.get_day(base, "2026-02-30") == {"state": "invalid_date", "date": "2026-02-30"})
check("a week date is not a date either", dmap.get_day(base, "2026-W46-1")["state"] == "invalid_date")
check("no base folder: state missing", dmap.get_day(None, "2026-11-10") == {"state": "missing", "date": "2026-11-10"})

# a day with a history: the deleted text stays in the day file and never leaves the diary
hbase = new_base()
assert wr.create_user_field(hbase, "Schmerztablette", TABLET, True)["key"] == "U0001"
pill = [{"time": "07:15", "values": {"Anzahl": 2}}]
assert wr.save_day(hbase, "2026-11-01", SECRET, {"U0001": pill}, now=at("2026-11-01"))["status"] == "written"
assert wr.save_day(hbase, "2026-11-01", "ein anderer Text", {"U0001": pill}, now=at("2026-11-20"), keep_history=True)["status"] == "written"
stored = load(dm.day_path(hbase, "2026-11-01"))
check("(setup) the day file holds the earlier text in its history", len(stored["history"]) == 1 and SECRET in json.dumps(stored["history"], ensure_ascii=False))
hday = dmap.get_day(hbase, "2026-11-01")
hpres = dmap.get_presence(hbase, "2026-11-01", "2026-11-30")
check("the earlier text is nowhere in get_day", SECRET not in json.dumps(hday, ensure_ascii=False) and hday["note"] == "ein anderer Text")
check("the earlier text is nowhere in get_presence", SECRET not in json.dumps(hpres, ensure_ascii=False))

bad = new_base()
write_raw(dm.day_path(bad, "2026-11-05"), "{not json")
check("a damaged day file: state damaged", dmap.get_day(bad, "2026-11-05") == {"state": "damaged", "date": "2026-11-05"})
write_json(dm.day_path(bad, "2026-11-06"), {"schema_version": 99})
check("a day file of a newer version: state unsupported", dmap.get_day(bad, "2026-11-06") == {"state": "unsupported", "date": "2026-11-06"})
write_json(dm.day_path(bad, "2026-11-07"), {"schema_version": 1, "date": "2026-11-08", "note": "x"})
check("a day file that fails its checks: state damaged", dmap.get_day(bad, "2026-11-07")["state"] == "damaged")

# ══════════════════════════════════════════════════════════════════════════════
section("4. get_presence")
# ══════════════════════════════════════════════════════════════════════════════

pres = dmap.get_presence(base, "2026-11-01", "2026-11-30")
check("presence: state ok and the range is echoed", pres["state"] == "ok" and pres["date_from"] == "2026-11-01" and pres["date_to"] == "2026-11-30")
check("presence: one entry per day file in the range", sorted(pres["days"]) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])
check("presence: note and the keys with an entry", pres["days"]["2026-11-10"] == {"note": True, "fields": ["U0001", "U0002"]})
check("presence: a day with a note and no entry", pres["days"]["2026-11-12"] == {"note": True, "fields": []})
check("presence: a day with an entry and no note", pres["days"]["2026-11-14"] == {"note": False, "fields": ["U0002"]})
check("presence: names of the fields that have entries, and only those",
      pres["fields"] == {"U0001": "Schmerztablette", "U0002": "Spazieren gegangen"})
check("presence: nothing damaged, nothing unsupported, master ok",
      pres["damaged"] == [] and pres["unsupported"] == [] and pres["master"] == "ok")

edge = dmap.get_presence(base, "2026-11-10", "2026-11-16")
check("both ends of the range are inclusive", sorted(edge["days"]) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])
inner = dmap.get_presence(base, "2026-11-11", "2026-11-15")
check("days outside the range are left out", sorted(inner["days"]) == ["2026-11-12", "2026-11-14"])
check("a key that has no entry in the range is not named", inner["fields"] == {"U0002": "Spazieren gegangen"})
one = dmap.get_presence(base, "2026-11-12", "2026-11-12")
check("a range of one day", sorted(one["days"]) == ["2026-11-12"] and one["fields"] == {})
none = dmap.get_presence(base, "2026-10-01", "2026-10-31")
check("a range without days: ok, empty", none["state"] == "ok" and none["days"] == {} and none["fields"] == {})

# a note of spaces is not a note; a field of the day without entries is not present
sbase = new_base()
assert wr.create_user_field(sbase, "Spazieren gegangen", YESNO, False)["key"] == "U0001"
assert wr.save_day(sbase, "2026-11-03", "   ", {"U0001": [{"values": {"Ja/Nein": False}}]}, now=at("2026-11-03"))["status"] == "written"
sp = dmap.get_presence(sbase, "2026-11-01", "2026-11-30")
check("a note of spaces is no note, a 'no' entry is an entry", sp["days"]["2026-11-03"] == {"note": False, "fields": ["U0001"]})

# names: master first, snapshot as fallback, the newest day wins
wr.rename_field(base, "U0001", "Tablette neu")
renamed = dmap.get_presence(base, "2026-11-01", "2026-11-30")
check("the current name of the master is shown", renamed["fields"]["U0001"] == "Tablette neu")
check("the day keeps the name of its own snapshot", dmap.get_day(base, "2026-11-10")["definitions"]["U0001"]["name"] == "Schmerztablette")

nbase = prepared_base()
older = load(dm.day_path(nbase, "2026-11-10"))
older["key_snapshot"]["U0002"]["name"] = "Älterer Name"
write_json(dm.day_path(nbase, "2026-11-10"), older)
newest = load(dm.day_path(nbase, "2026-11-14"))
newest["key_snapshot"]["U0002"]["name"] = "Neuerer Name"
write_json(dm.day_path(nbase, "2026-11-14"), newest)
master = load(dm.fields_path(nbase))
del master["fields"]["U0002"]
write_json(dm.fields_path(nbase), master)
fb = dmap.get_presence(nbase, "2026-11-01", "2026-11-30")
check("a key that the master no longer holds: the name of the newest day that has it", fb["fields"]["U0002"] == "Neuerer Name")
check("a key the master still holds: the master's name", fb["fields"]["U0001"] == "Schmerztablette")

write_raw(dm.fields_path(nbase), "{not json")
nm = dmap.get_presence(nbase, "2026-11-01", "2026-11-30")
check("a damaged master: the state is named and the names come from the days",
      nm["master"] == "damaged" and nm["fields"]["U0001"] == "Schmerztablette" and nm["fields"]["U0002"] == "Neuerer Name")
check("a damaged master does not hide the days", sorted(nm["days"]) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])

# a field list of a newer version is named "unsupported" and, like a damaged one, does not stop the names from the days
# (mutation round v1.7.8.1: the master state must be compared for "ok" exactly, not ordered against it)
write_json(dm.fields_path(nbase), {"schema_version": 99})
nu = dmap.get_presence(nbase, "2026-11-01", "2026-11-30")
check("a field list of a newer version: the state is named and the names come from the days (no error)",
      nu["master"] == "unsupported" and nu["fields"]["U0001"] == "Schmerztablette" and nu["fields"]["U0002"] == "Neuerer Name")
check("a field list of a newer version does not hide the days", sorted(nu["days"]) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])

# damaged and unsupported days are counted and named, never left out silently
write_raw(dm.day_path(base, "2026-11-13"), "{not json")
write_json(dm.day_path(base, "2026-11-15"), {"schema_version": 99})
write_raw(dm.day_path(base, "2026-12-24"), "{not json")          # outside the range below
cnt = dmap.get_presence(base, "2026-11-01", "2026-11-30")
check("a damaged day is named in 'damaged' and is not in 'days'", cnt["damaged"] == ["2026-11-13"] and "2026-11-13" not in cnt["days"])
check("a day of a newer version is named in 'unsupported' and is not in 'days'", cnt["unsupported"] == ["2026-11-15"] and "2026-11-15" not in cnt["days"])
check("the readable days are all still there", sorted(cnt["days"]) == ["2026-11-10", "2026-11-12", "2026-11-14", "2026-11-16"])
check("a bad day outside the range is not counted", dmap.get_presence(base, "2026-11-01", "2026-11-30")["damaged"] == ["2026-11-13"])

check("a range that is not a date: invalid_date", dmap.get_presence(base, "2026-13-01", "2026-11-30") == {"state": "invalid_date"})
check("a range whose end is not a date: invalid_date", dmap.get_presence(base, "2026-11-01", "bald") == {"state": "invalid_date"})
check("a range turned around: invalid_range", dmap.get_presence(base, "2026-11-30", "2026-11-01") == {"state": "invalid_range"})
nb = dmap.get_presence(None, "2026-11-01", "2026-11-30")
check("no base folder: ok, no days, master missing", nb["state"] == "ok" and nb["days"] == {} and nb["master"] == "missing")
eb = dmap.get_presence(empty, "2026-11-01", "2026-11-30")
check("a base folder without a diary: ok, no days, master missing", eb["state"] == "ok" and eb["days"] == {} and eb["master"] == "missing")

# ══════════════════════════════════════════════════════════════════════════════
section("4b. get_cache_feed (MCP cache sync)")
# ══════════════════════════════════════════════════════════════════════════════

import hashlib  # noqa: E402

fbase = prepared_base()
write_raw(dm.day_path(fbase, "2026-11-13"), "{not json")
write_json(dm.day_path(fbase, "2026-11-15"), {"schema_version": 99})
feed = dmap.get_cache_feed(fbase)
check("feed: every day file is listed, bad ones too",
      sorted(feed["days"]) == ["2026-11-10", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16"])
check("feed: the fields are the answer of list_fields", feed["fields"] == dmap.list_fields(fbase))
good = feed["days"]["2026-11-10"]
check("feed: an ok day has state, hash and payload",
      good["state"] == "ok" and good["payload"] is not None and set(good["payload"]) == {"note", "entries", "definitions"})
check("feed: the payload is the one of get_day (note, entries, definitions)",
      good["payload"] == {k: v for k, v in dmap.get_day(fbase, "2026-11-10").items() if k in ("note", "entries", "definitions")})
check("feed: the hash is the SHA-256 of the bytes of the file",
      good["hash"] == hashlib.sha256(Path(dm.day_path(fbase, "2026-11-10")).read_bytes()).hexdigest())
check("feed: a damaged day has state, hash and no payload",
      feed["days"]["2026-11-13"]["state"] == "damaged" and feed["days"]["2026-11-13"]["payload"] is None
      and feed["days"]["2026-11-13"]["hash"] == hashlib.sha256(b"{not json").hexdigest())
check("feed: a day of a newer version has state unsupported, a hash and no payload",
      feed["days"]["2026-11-15"]["state"] == "unsupported" and feed["days"]["2026-11-15"]["payload"] is None
      and feed["days"]["2026-11-15"]["hash"] is not None)
check("feed: the same bytes give the same hash, changed bytes another",
      dmap.get_cache_feed(fbase)["days"]["2026-11-10"]["hash"] == good["hash"]
      and (wr.save_day(fbase, "2026-11-10", "ein Tag mit anderer Notiz", {}, now=at("2026-11-10"))["status"] == "written")
      and dmap.get_cache_feed(fbase)["days"]["2026-11-10"]["hash"] != good["hash"])
check("feed: no history in any payload", "history" not in json.dumps(feed))
hfeed_base = new_base()
assert wr.create_user_field(hfeed_base, "Schmerztablette", TABLET, True)["key"] == "U0001"
assert wr.save_day(hfeed_base, "2026-11-01", SECRET, {"U0001": [{"time": "07:15", "values": {"Anzahl": 2}}]}, now=at("2026-11-01"))["status"] == "written"
assert wr.save_day(hfeed_base, "2026-11-01", "spaeter", {"U0001": [{"time": "07:15", "values": {"Anzahl": 2}}]}, now=at("2026-11-20"), keep_history=True)["status"] == "written"
check("feed: the earlier text of a day with a history is not in the feed",
      SECRET not in json.dumps(dmap.get_cache_feed(hfeed_base), ensure_ascii=False))
check("feed: the payload is a copy", (lambda f: (f["days"]["2026-11-12"]["payload"].update(note="x"), dmap.get_cache_feed(fbase)["days"]["2026-11-12"]["payload"]["note"])[1])(feed) == "nur Notiz")
check("feed: no base folder gives no days", dmap.get_cache_feed(None) == {"fields": {"state": "missing", "fields": []}, "days": {}})
check("feed: a base folder without a diary gives no days and a missing master",
      dmap.get_cache_feed(empty) == {"fields": {"state": "missing", "fields": []}, "days": {}})

# ══════════════════════════════════════════════════════════════════════════════
section("5. Read only, and nothing of the content in the log")
# ══════════════════════════════════════════════════════════════════════════════

rbase = new_base()
assert wr.create_user_field(rbase, "Schmerztablette", TABLET, True)["key"] == "U0001"
assert wr.save_day(rbase, "2026-11-02", SECRET, {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=at("2026-11-02"))["status"] == "written"
write_raw(dm.day_path(rbase, "2026-11-03"), "{not json")
before = tree_bytes(rbase)


class _Catcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


catcher = _Catcher()
root_logger = logging.getLogger()
old_level = root_logger.level
old_disable = logging.root.manager.disable      # gla_testenv switches logging off for the whole run
root_logger.addHandler(catcher)
root_logger.setLevel(logging.DEBUG)
logging.disable(logging.NOTSET)
try:
    dmap.list_fields(rbase)
    dmap.list_days(rbase)
    dmap.get_day(rbase, "2026-11-02")
    dmap.get_day(rbase, "2026-11-03")
    dmap.get_presence(rbase, "2026-11-01", "2026-11-30")
finally:
    logging.disable(old_disable)
    root_logger.removeHandler(catcher)
    root_logger.setLevel(old_level)

check("every call left the diary folder byte-identical", tree_bytes(rbase) == before)
check("(setup) a damaged day made the reader log a line", any("failed its checks" in line or "could not be read" in line for line in catcher.lines))
check("no line of the log carries the note or a field name",
      not any(SECRET in line or "Schmerztablette" in line or "Anzahl" in line for line in catcher.lines))

# ══════════════════════════════════════════════════════════════════════════════
section("6. Guards")
# ══════════════════════════════════════════════════════════════════════════════

source = (_SRC / "maps" / "diary_map.py").read_text(encoding="utf-8")
tree = ast.parse(source)
imported = set()
from_diary = set()
calls = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported.update(alias.name.split(".")[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        imported.add((node.module or "").split(".")[0] if node.level == 0 else "." + (node.module or ""))
        if node.module == "diary":
            from_diary.update(alias.name for alias in node.names)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        calls.add(node.func.id)
check("diary_map imports only the diary package and the standard library", imported == {"copy", "diary"})
check("diary_map takes only the model and the reader of the diary (never the writer or the backup)",
      from_diary == {"diary_model", "diary_reader"})
check("diary_map opens no file itself", "open" not in calls)
check("diary_map is marked removable", "DIARY v1.7.8 — REMOVABLE" in source)

for name in ("health_map.py", "context_map.py", "metadata_map.py"):
    check(f"{name} does not know the diary (the broker is not a source of the other brokers)",
          "diary" not in (_SRC / "maps" / name).read_text(encoding="utf-8").lower())
# Which modules of clients/ and maps/ may mention the diary at all is guarded in test_diary.py (opt-in side, v1.7.8.1).

summary()
