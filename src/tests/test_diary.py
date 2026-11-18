#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_diary.py — diary/ (catalogue, model, reader, writer)
DIARY v1.7.8 — removable (the package is src/diary/).

Covers: the Set 1 catalogue, dates/times/keys (week dates and other-script digits are refused),
the definition and entry checks (type, finiteness, time rules), the master file (create, duplicate
names, keys never reused, flags, rename, damaged/unsupported/missing), save_day (snapshot, the free-edit
window, nothing written on a refusal, atomic write, the retry on a locked file), recover_master,
the reader (states, file names), the privacy rule of the log, and guards: the package imports only the
standard library, every module is in the build manifest, no module of clients/ or maps/ mentions the diary.

Run from the project folder:
    python tests/test_diary.py

Everything is built here in a temporary folder — no archive of the maintainer is needed or touched.
"""

import ast
import copy
import importlib.util
import json
import logging
import math
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

_SRC = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_SRC / "garmin"))      # diary_backup is the one module that uses garmin_backup_common

from diary import diary_catalog as cat  # noqa: E402
from diary import diary_model as dm  # noqa: E402
from diary import diary_reader as rd  # noqa: E402
from diary import diary_writer as wr  # noqa: E402

_ROOT = _TMPDIR / "diary_tests"
shutil.rmtree(_ROOT, ignore_errors=True)
_ROOT.mkdir(parents=True)
_COUNTER = [0]

T0 = datetime(2026, 11, 18, 9, 30)
T0_LATER = datetime(2026, 11, 18, 21, 5)
T1 = datetime(2026, 11, 19, 8, 0)

TABLET = [{"label": "Anzahl", "type": "number", "unit": "Stück"}]
YESNO = [{"label": "Ja/Nein", "type": "yesno"}]
BP_ENTRY = {"time": "07:15", "values": {"systolic": 128, "diastolic": 82, "Pulse": 61}}


def new_base():
    _COUNTER[0] += 1
    path = _ROOT / f"b{_COUNTER[0]}"
    path.mkdir()
    return path


def has(errors, code):
    return any(e == code or e.startswith(code + ":") for e in errors)


def user_def(**changes):
    out = {"name": "Test", "set": "user", "with_time": True,
           "values": [{"label": "A", "type": "number", "unit": "x"}]}
    out.update(changes)
    return out


def prepared_base():
    """A base with U0001 Schmerztablette (with time), U0002 Spazieren (yes/no), G001 and G003 activated."""
    base = new_base()
    assert wr.create_user_field(base, "Schmerztablette", TABLET, True)["key"] == "U0001"
    assert wr.create_user_field(base, "Spazieren gegangen", YESNO, False)["key"] == "U0002"
    assert wr.activate_catalog_field(base, "G001")["status"] == "written"
    assert wr.activate_catalog_field(base, "G003")["status"] == "written"
    return base


def read_bytes(path):
    return Path(path).read_bytes()


def write_raw(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def day_file(base, date_str):
    return dm.day_path(base, date_str)


def tmp_files(base):
    return [p for p in Path(base).rglob("*.tmp")]


# ══════════════════════════════════════════════════════════════════════════════
section("1. Catalogue (Set 1)")
# ══════════════════════════════════════════════════════════════════════════════

check("catalogue keys are G001, G002, G003", cat.keys() == ["G001", "G002", "G003"])
check("every catalogue definition passes check_definition",
      all(dm.check_definition(cat.CATALOG[k]) == [] for k in cat.keys()))
check("every catalogue key has the Garmin key format", all(dm.is_garmin_key(k) for k in cat.keys()))
check("every catalogue definition is of the set garmin", all(cat.CATALOG[k]["set"] == "garmin" for k in cat.keys()))
check("every catalogue field names its Garmin endpoint",
      [cat.CATALOG[k]["maps_to"] for k in cat.keys()] ==
      ["get_blood_pressure", "get_hydration_data", "get_body_composition"])
check("catalogue names are unique", len(set(cat.names())) == 3)
bp = cat.definition("G001")
check("blood pressure: with time, three values (systolic, diastolic, Pulse)",
      bp["with_time"] is True and [v["label"] for v in bp["values"]] == ["systolic", "diastolic", "Pulse"])
check("blood pressure units: mmHg, mmHg, bpm", [v["unit"] for v in bp["values"]] == ["mmHg", "mmHg", "bpm"])
check("hydration: with time, one value in ml",
      cat.CATALOG["G002"]["with_time"] is True and cat.CATALOG["G002"]["values"][0]["unit"] == "ml")
check("weight: without time, one value in kg",
      cat.CATALOG["G003"]["with_time"] is False and cat.CATALOG["G003"]["values"][0]["unit"] == "kg")
bp["values"][0]["label"] = "changed"
bp["name"] = "changed"
check("definition() returns a copy: changing it leaves the catalogue alone",
      cat.CATALOG["G001"]["name"] == "Blood pressure" and cat.CATALOG["G001"]["values"][0]["label"] == "systolic")
check("definition() of an unknown key is None", cat.definition("G999") is None and cat.definition("U0001") is None)

tpl = cat.templates()
check("start templates: Cycle, Pregnancy, Calorie intake, Alcohol, Caffeine, Walk, in that order",
      [x["name"] for x in tpl] == ["Cycle", "Pregnancy", "Calorie intake", "Alcohol", "Caffeine", "Walk"])
check("every start template passes check_definition as a user field",
      all(dm.check_definition({**x, "set": dm.SET_USER}) == [] for x in tpl))
check("start template names are unique, also compared without regard to case",
      len({dm.normalized_name(x["name"]) for x in tpl}) == len(tpl))
check("no start template takes the name of a catalogue field",
      not ({dm.normalized_name(x["name"]) for x in tpl} & {dm.normalized_name(n) for n in cat.names()}))
check("start templates have no Garmin endpoint and no key of their own",
      all(set(x) == {"name", "with_time", "values"} for x in tpl))
check("start templates: Alcohol and Caffeine have a time, the others have none",
      {x["name"] for x in tpl if x["with_time"]} == {"Alcohol", "Caffeine"})
check("start template Cycle: Period (yes/no) and Day of cycle (number, day)",
      tpl[0]["values"] == [{"label": "Period", "type": "yesno"}, {"label": "Day of cycle", "type": "number", "unit": "day"}])
check("start template units: week, kcal, units, cups",
      [tpl[i]["values"][0]["unit"] for i in (1, 2, 3, 4)] == ["week", "kcal", "units", "cups"])
tpl[0]["name"] = "changed"
tpl[0]["values"].append({"label": "x", "type": "yesno"})
check("templates() returns copies: changing them leaves the templates alone",
      cat.TEMPLATES[0]["name"] == "Cycle" and len(cat.TEMPLATES[0]["values"]) == 2)

# ══════════════════════════════════════════════════════════════════════════════
section("2. Model — dates, times, keys, names")
# ══════════════════════════════════════════════════════════════════════════════

check("valid dates", all(dm.valid_date(d) for d in ("2026-11-18", "2024-02-29", "2000-01-01", "2026-12-31")))
for bad in ("2026-02-29", "2026-13-01", "2026-00-10", "2026-11-31", "2026-W20-1", "20261118", "2026-8-2",
            "2026-11-18 ", " 2026-11-18", "", "2026-11-18T00:00",
            "\u0662\u0660\u0662\u0666-\u0661\u0661-\u0661\u0668", None, 20261118, ["2026-11-18"]):
    check(f"invalid date refused: {bad!r}", dm.valid_date(bad) is False)
check("valid times", all(dm.valid_time(t) for t in ("00:00", "07:15", "12:00", "23:59")))
for bad in ("24:00", "7:15", "07:5", "07:15:00", "", "07-15", "12:60", "\u0660\u0667:\u0661\u0665", None, 715):
    check(f"invalid time refused: {bad!r}", dm.valid_time(bad) is False)
check("keys: G001, U0001 and U10000 are valid", all(dm.valid_key(k) for k in ("G001", "U0001", "U10000")))
for bad in ("g001", "G01", "G0001", "U001", "", "U0001 ", "X0001", None, 1):
    check(f"invalid key refused: {bad!r}", dm.valid_key(bad) is False)
check("format_user_key: 1 -> U0001, 12345 -> U12345",
      dm.format_user_key(1) == "U0001" and dm.format_user_key(12345) == "U12345")
check("user_key_number: U0007 -> 7, G001 -> None", dm.user_key_number("U0007") == 7 and dm.user_key_number("G001") is None)
check("normalized_name collapses space and folds case", dm.normalized_name("  Schmerz   TABLETTE ") == "schmerz tablette")
check("clean_name strips and collapses", dm.clean_name("  a   b ") == "a b")
check("clean_name leaves a non-string alone", dm.clean_name(5) == 5)
base0 = Path("X:/archive")
check("paths: fields.json and the day file",
      dm.fields_path(base0) == base0 / "diary_data" / "fields.json" and
      dm.day_path(base0, "2026-11-18") == base0 / "diary_data" / "days" / "diary_2026-11-18.json")
check("day_path of a bad date is None", dm.day_path(base0, "2026-02-30") is None)
check("date_of_day_file_name: a day file name -> its date", dm.date_of_day_file_name("diary_2026-11-18.json") == "2026-11-18")
for bad in ("diary_2026-13-01.json", "diary_x.json", "diary_2026-11-18.json.tmp", "notes.json", "2026-11-18.json", None):
    check(f"date_of_day_file_name refuses {bad!r}", dm.date_of_day_file_name(bad) is None)

# ══════════════════════════════════════════════════════════════════════════════
section("3. Model — definitions")
# ══════════════════════════════════════════════════════════════════════════════

check("a valid user definition has no errors", dm.check_definition(user_def()) == [])
check("a definition with a yes/no value (no unit) is valid",
      dm.check_definition(user_def(values=YESNO, with_time=False)) == [])
check("a number value may have an empty unit", dm.check_definition(user_def(values=[{"label": "n", "type": "number", "unit": ""}])) == [])
check("not a dict", dm.check_definition("x") == ["definition_not_a_dict"])
check("unknown key refused", has(dm.check_definition(user_def(extra=1)), "definition_unknown_key"))
check("name missing", has(dm.check_definition(user_def(name="")), "name_missing"))
check("name only space", has(dm.check_definition(user_def(name="   ")), "name_missing"))
check("name not clean", has(dm.check_definition(user_def(name=" a ")), "name_not_clean"))
check("name too long", has(dm.check_definition(user_def(name="x" * 81)), "name_too_long"))
check("name of 80 is fine", dm.check_definition(user_def(name="x" * 80)) == [])
check("set invalid", has(dm.check_definition(user_def(set="other")), "set_invalid"))
check("with_time must be a bool (1 is refused)", has(dm.check_definition(user_def(with_time=1)), "with_time_not_bool"))
check("a garmin definition needs maps_to", has(dm.check_definition(user_def(set="garmin")), "maps_to_missing"))
check("a garmin definition with maps_to is valid", dm.check_definition(user_def(set="garmin", maps_to="get_x")) == [])
check("a user definition may not have maps_to", has(dm.check_definition(user_def(maps_to="get_x")), "maps_to_not_allowed"))
check("values missing", has(dm.check_definition(user_def(values=[])), "values_missing"))
check("values not a list", has(dm.check_definition(user_def(values="a")), "values_missing"))
check("too many values", has(dm.check_definition(user_def(
    values=[{"label": f"l{i}", "type": "number", "unit": ""} for i in range(13)])), "values_too_many"))
check("a value that is not a dict", has(dm.check_definition(user_def(values=["a"])), "value0_not_a_dict"))
check("label missing", has(dm.check_definition(user_def(values=[{"type": "number", "unit": ""}])), "value0_label_missing"))
check("label not clean", has(dm.check_definition(user_def(values=[{"label": " a", "type": "number", "unit": ""}])), "value0_label_not_clean"))
check("label too long", has(dm.check_definition(user_def(values=[{"label": "l" * 41, "type": "number", "unit": ""}])), "value0_label_too_long"))
check("duplicate labels (case folded)", has(dm.check_definition(user_def(values=[
    {"label": "A", "type": "number", "unit": ""}, {"label": "a", "type": "number", "unit": ""}])), "value1_label_duplicate"))
check("value type invalid", has(dm.check_definition(user_def(values=[{"label": "a", "type": "date", "unit": ""}])), "value0_type_invalid"))
check("a number value needs a unit key", has(dm.check_definition(user_def(values=[{"label": "a", "type": "number"}])), "value0_unit_missing"))
check("unit too long", has(dm.check_definition(user_def(values=[{"label": "a", "type": "number", "unit": "u" * 21}])), "value0_unit_too_long"))
check("a yes/no value may not have a unit", has(dm.check_definition(user_def(values=[{"label": "a", "type": "yesno", "unit": "x"}])), "value0_unit_not_allowed"))
check("a value with an unknown key", has(dm.check_definition(user_def(values=[{"label": "a", "type": "yesno", "x": 1}])), "value0_unknown_key"))
snap = dm.snapshot_of({**cat.definition("G001"), "favorite": True, "archived": False})
check("snapshot_of drops the flags", "favorite" not in snap and "archived" not in snap and snap["name"] == "Blood pressure")
snap["values"][0]["label"] = "changed"
check("snapshot_of shares nothing with the catalogue", cat.CATALOG["G001"]["values"][0]["label"] == "systolic")

# ══════════════════════════════════════════════════════════════════════════════
section("4. Model — entries")
# ══════════════════════════════════════════════════════════════════════════════

BP = cat.definition("G001")
WEIGHT = cat.definition("G003")
YN = user_def(name="JN", values=YESNO, with_time=False)
check("blood pressure: one full entry is valid", dm.check_entries(BP, [BP_ENTRY]) == [])
check("blood pressure: several entries on one day are valid", dm.check_entries(BP, [BP_ENTRY, {**BP_ENTRY, "time": "19:40"}]) == [])
check("a partial entry (not every label) is valid", dm.check_entries(BP, [{"time": "07:15", "values": {"systolic": 120}}]) == [])
check("an empty list has no errors (the caller leaves the field out)", dm.check_entries(BP, []) == [])
check("zero, a negative number and a float are numbers",
      dm.check_entries(BP, [{"time": "07:15", "values": {"systolic": 0, "diastolic": -5, "Pulse": 61.5}}]) == [])
check("a very large finite number is fine", dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": 1e308}}]) == [])
check("time missing", has(dm.check_entries(BP, [{"values": {"Pulse": 60}}]), "entry0_time_invalid"))
check("time 24:00 refused", has(dm.check_entries(BP, [{"time": "24:00", "values": {"Pulse": 60}}]), "entry0_time_invalid"))
check("unknown label refused", has(dm.check_entries(BP, [{"time": "07:15", "values": {"x": 1}}]), "entry0_label_unknown"))
check("a label is matched exactly (case)", has(dm.check_entries(BP, [{"time": "07:15", "values": {"pulse": 1}}]), "entry0_label_unknown"))
check("a bool is not a number", has(dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": True}}]), "entry0_value_not_a_number"))
check("NaN is not a number", has(dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": math.nan}}]), "entry0_value_not_a_number"))
check("infinity is not a number", has(dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": math.inf}}]), "entry0_value_not_a_number"))
check("a string is not a number", has(dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": "61"}}]), "entry0_value_not_a_number"))
check("None is not a number", has(dm.check_entries(BP, [{"time": "07:15", "values": {"Pulse": None}}]), "entry0_value_not_a_number"))
check("values missing", has(dm.check_entries(BP, [{"time": "07:15"}]), "entry0_values_missing"))
check("values empty", has(dm.check_entries(BP, [{"time": "07:15", "values": {}}]), "entry0_values_missing"))
check("an unknown key in an entry", has(dm.check_entries(BP, [{**BP_ENTRY, "x": 1}]), "entry0_unknown_key"))
check("entries not a list", dm.check_entries(BP, {"a": 1}) == ["entries_not_a_list"])
check("an entry that is not a dict", has(dm.check_entries(BP, ["x"]), "entry0_not_a_dict"))
check("too many entries", dm.check_entries(BP, [BP_ENTRY] * 501) == ["entries_too_many"])
check("500 entries are fine", dm.check_entries(BP, [BP_ENTRY] * 500) == [])
check("without time: one entry is valid", dm.check_entries(WEIGHT, [{"values": {"Weight": 80.5}}]) == [])
check("without time: two entries refused", has(dm.check_entries(WEIGHT, [{"values": {"Weight": 80}}, {"values": {"Weight": 81}}]), "entries_too_many_without_time"))
check("without time: a time key is refused", has(dm.check_entries(WEIGHT, [{"time": "07:00", "values": {"Weight": 80}}]), "entry0_time_not_allowed"))
check("yes/no: True and False are valid", dm.check_entries(YN, [{"values": {"Ja/Nein": True}}]) == [] and
      dm.check_entries(YN, [{"values": {"Ja/Nein": False}}]) == [])
check("yes/no: 1 is refused", has(dm.check_entries(YN, [{"values": {"Ja/Nein": 1}}]), "entry0_value_not_yesno"))
check("yes/no: a string is refused", has(dm.check_entries(YN, [{"values": {"Ja/Nein": "ja"}}]), "entry0_value_not_yesno"))

# ══════════════════════════════════════════════════════════════════════════════
section("4b. Model — text values and groups of alternatives")
# ══════════════════════════════════════════════════════════════════════════════

def num(label, unit="x", **extra):
    return {"label": label, "type": "number", "unit": unit, **extra}


TXT = {"label": "Type", "type": "text"}
check("text is a value type", dm.TYPE_TEXT == "text" and "text" in dm.VALUE_TYPES)
check("a text value is valid (no unit)", dm.check_definition(user_def(values=[num("Drinks"), TXT])) == [])
check("a text value may not have a unit",
      has(dm.check_definition(user_def(values=[{**TXT, "unit": "x"}])), "value0_unit_not_allowed"))
WALK = user_def(name="Walk", with_time=False,
                values=[{"label": "Done", "type": "yesno"}, num("Steps", "steps", group="amount"),
                        num("Distance", "km", group="amount")])
check("two numbers with the same group are valid", dm.check_definition(WALK) == [])
check("two separate groups are valid",
      dm.check_definition(user_def(values=[num("a", group="g1"), num("b", group="g1"),
                                           num("c", group="g2"), num("d", group="g2")])) == [])
check("three members are valid",
      dm.check_definition(user_def(values=[num("a", group="g"), num("b", group="g"), num("c", group="g")])) == [])
check("a group of one is refused",
      has(dm.check_definition(user_def(values=[num("a", group="g"), num("b")])), "group_single"))
check("members must stand together",
      has(dm.check_definition(user_def(values=[num("a", group="g"), num("b"), num("c", group="g")])), "group_not_together"))
check("group names differ in case: each is alone",
      has(dm.check_definition(user_def(values=[num("a", group="G"), num("b", group="g")])), "group_single"))
check("a yes/no value cannot be in a group",
      has(dm.check_definition(user_def(values=[{"label": "a", "type": "yesno", "group": "g"}, num("b", group="g")])),
          "value0_group_not_allowed"))
check("a text value cannot be in a group", has(dm.check_definition(user_def(values=[{**TXT, "group": "g"}])), "value0_group_not_allowed"))
for bad_group in ("", "   ", " g", "g ", 5, None, True, "g" * 41):
    check(f"group name {bad_group!r} is refused",
          has(dm.check_definition(user_def(values=[num("a", group=bad_group), num("b", group="g")])), "value0_group_invalid"))
check("a group name of 40 characters is fine",
      dm.check_definition(user_def(values=[num("a", group="g" * 40), num("b", group="g" * 40)])) == [])
check("the group is kept by snapshot_of and definition_of",
      dm.snapshot_of(WALK)["values"][1]["group"] == "amount"
      and dm.definition_of({**WALK, "favorite": False, "archived": False})["values"][2]["group"] == "amount")

OH = user_def(name="Alcohol", values=[num("Drinks", "units"), TXT])
check("text: a normal text is valid", dm.check_entries(OH, [{"time": "20:00", "values": {"Type": "red wine"}}]) == [])
check("text: number and text together are valid",
      dm.check_entries(OH, [{"time": "20:00", "values": {"Drinks": 2, "Type": "beer"}}]) == [])
check("text: 200 characters are fine", dm.check_entries(OH, [{"time": "20:00", "values": {"Type": "x" * 200}}]) == [])
check("text: 201 characters are refused",
      has(dm.check_entries(OH, [{"time": "20:00", "values": {"Type": "x" * 201}}]), "entry0_value_not_text"))
for bad_text in ("", "   ", "a\nb", "a\tb", "a\x00b", "a\x7fb", 5, None, True, ["a"]):
    check(f"text: {bad_text!r} is refused",
          has(dm.check_entries(OH, [{"time": "20:00", "values": {"Type": bad_text}}]), "entry0_value_not_text"))
check("text: other scripts and symbols are fine",
      dm.check_entries(OH, [{"time": "20:00", "values": {"Type": "Bier – 0,5 l ☺ 啤酒"}}]) == [])
W = WALK
check("group: one member alone is valid", dm.check_entries(W, [{"values": {"Steps": 5000}}]) == [])
check("group: the other member alone is valid", dm.check_entries(W, [{"values": {"Distance": 3.5}}]) == [])
check("group: neither member is valid (another value carries the entry)", dm.check_entries(W, [{"values": {"Done": True}}]) == [])
check("group: both members in one entry are refused",
      has(dm.check_entries(W, [{"values": {"Steps": 5000, "Distance": 3.5}}]), "entry0_group_twice"))
check("group: a member and another value are valid", dm.check_entries(W, [{"values": {"Done": True, "Steps": 5000}}]) == [])
W_TIME = {**W, "with_time": True}
check("group: each entry may use another member",
      dm.check_entries(W_TIME, [{"time": "08:00", "values": {"Steps": 4000}}, {"time": "18:00", "values": {"Distance": 2}}]) == [])
check("group: a member of a group still has to be a number",
      has(dm.check_entries(W, [{"values": {"Steps": "many"}}]), "entry0_value_not_a_number"))

# ══════════════════════════════════════════════════════════════════════════════
section("5. Writer — fields")
# ══════════════════════════════════════════════════════════════════════════════

base = new_base()
check("no master yet: the reader says missing", rd.read_master(base) == ("missing", None))
res = wr.create_user_field(base, "Schmerztablette", TABLET, True)
check("first user field: written with key U0001", res["status"] == "written" and res["key"] == "U0001")
state, master = rd.read_master(base)
check("the master file is read back ok", state == "ok" and master["next_id"] == 2)
check("the stored field has the definition and the flags",
      master["fields"]["U0001"] == {"name": "Schmerztablette", "set": "user", "with_time": True,
                                    "values": TABLET, "favorite": False, "archived": False})
res = wr.create_user_field(base, "Spazieren gegangen", YESNO, False)
check("second user field: U0002", res["key"] == "U0002" and rd.read_master(base)[1]["next_id"] == 3)
res = wr.create_user_field(base, "  SCHMERZTABLETTE ", TABLET, True)
check("a name that only differs in case and outer space is refused", res["status"] == "rejected" and res["reason"] == "duplicate_name")
check("a name that only differs in the runs of inner space is refused",
      wr.create_user_field(base, "spazieren    GEGANGEN", TABLET, True)["reason"] == "duplicate_name")
check("a catalogue name is refused for a user field",
      wr.create_user_field(base, "blood PRESSURE", TABLET, True)["reason"] == "duplicate_name")
res = wr.create_user_field(base, "", TABLET, True)
check("an invalid definition is refused with its errors", res["reason"] == "invalid_definition" and has(res["errors"], "name_missing"))
check("a non-string name is refused", wr.create_user_field(base, None, TABLET, True)["reason"] == "invalid_definition")
check("with_time not a bool is refused", wr.create_user_field(base, "Neu", TABLET, "yes")["reason"] == "invalid_definition")
check("nothing changed after the refusals", rd.read_master(base)[1]["next_id"] == 3 and len(rd.read_master(base)[1]["fields"]) == 2)
values_in = copy.deepcopy(TABLET)
wr.create_user_field(base, "Kopie", values_in, True)
values_in[0]["label"] = "changed"
check("the definition handed in is copied, not kept", rd.read_master(base)[1]["fields"]["U0003"]["values"][0]["label"] == "Anzahl")

check("archiving a field: written", wr.set_flags(base, "U0003", archived=True)["status"] == "written")
check("the same flag again: unchanged", wr.set_flags(base, "U0003", archived=True)["status"] == "unchanged")
res = wr.create_user_field(base, "Nach dem Archivieren", TABLET, True)
check("an archived key is never handed out again: the next field is U0004", res["key"] == "U0004")
check("favorite on", wr.set_flags(base, "U0001", favorite=True)["status"] == "written" and
      rd.read_master(base)[1]["fields"]["U0001"]["favorite"] is True)
check("both flags in one call", wr.set_flags(base, "U0002", favorite=True, archived=True)["status"] == "written")
check("a flag that is not a bool is refused", wr.set_flags(base, "U0001", favorite=1)["reason"] == "flag_not_bool")
check("flags of an unknown key are refused", wr.set_flags(base, "U0099", favorite=True)["reason"] == "unknown_field")
check("set_flags with nothing to set: unchanged", wr.set_flags(base, "U0001")["status"] == "unchanged")

res = wr.rename_field(base, "U0001", "Schmerzmittel")
check("rename: written, the key stays", res["status"] == "written" and rd.read_master(base)[1]["fields"]["U0001"]["name"] == "Schmerzmittel")
check("rename: only the name changed", rd.read_master(base)[1]["fields"]["U0001"]["values"] == TABLET and
      rd.read_master(base)[1]["fields"]["U0001"]["with_time"] is True)
check("rename to the same name: unchanged", wr.rename_field(base, "U0001", "Schmerzmittel")["status"] == "unchanged")
check("rename to a taken name is refused", wr.rename_field(base, "U0001", "spazieren GEGANGEN")["reason"] == "duplicate_name")
check("rename to a catalogue name is refused", wr.rename_field(base, "U0001", "Weight")["reason"] == "duplicate_name")
check("rename to an empty name is refused", wr.rename_field(base, "U0001", "  ")["reason"] == "invalid_definition")
check("rename of an unknown key is refused", wr.rename_field(base, "U0099", "x")["reason"] == "unknown_field")
check("rename of a field that was renamed back to its old name is fine", wr.rename_field(base, "U0001", "Schmerztablette")["status"] == "written")

check("catalogue field: activated", wr.activate_catalog_field(base, "G001")["status"] == "written")
master = rd.read_master(base)[1]
check("an activated catalogue field is stored with its definition and flags off",
      master["fields"]["G001"] == {**cat.CATALOG["G001"], "favorite": False, "archived": False})
check("activating twice: unchanged", wr.activate_catalog_field(base, "G001")["status"] == "unchanged")
check("an unknown catalogue key is refused", wr.activate_catalog_field(base, "G099")["reason"] == "unknown_catalog_key")
check("a user key is not a catalogue key", wr.activate_catalog_field(base, "U0001")["reason"] == "unknown_catalog_key")

# a damaged / newer / missing master
base_d = new_base()
write_raw(dm.fields_path(base_d), "{ this is not json")
before = read_bytes(dm.fields_path(base_d))
check("a damaged master: the reader says damaged", rd.read_master(base_d) == ("damaged", None))
check("a damaged master: creating a field is refused", wr.create_user_field(base_d, "A", TABLET, True)["reason"] == "master_damaged")
check("a damaged master is left as it is", read_bytes(dm.fields_path(base_d)) == before)
check("a damaged master: activating is refused", wr.activate_catalog_field(base_d, "G001")["reason"] == "master_damaged")
check("a damaged master: flags are refused", wr.set_flags(base_d, "U0001", favorite=True)["reason"] == "master_damaged")
base_n = new_base()
write_raw(dm.fields_path(base_n), json.dumps({"schema_version": 99, "next_id": 1, "fields": {}}))
check("a master of a newer version: unsupported", rd.read_master(base_n) == ("unsupported", None))
check("a master of a newer version: no write", wr.create_user_field(base_n, "A", TABLET, True)["reason"] == "master_unsupported")
base_m = new_base()
write_raw(dm.day_path(base_m, "2026-11-10"), "{}")
check("master missing while a day file exists: no key is handed out",
      wr.create_user_field(base_m, "A", TABLET, True)["reason"] == "master_missing_days_exist")
check("master missing while a day file exists: no master file made", not dm.fields_path(base_m).exists())

# ── Text and groups through the writer and the reader ──────────────────────
base = new_base()
res = wr.create_user_field(base, "Walk", WALK["values"], False)
check("writer: a field with a group of alternatives is created", res["status"] == "written" and res["key"] == "U0001")
check("writer: the group is stored in the field list",
      rd.read_master(base)[1]["fields"]["U0001"]["values"][1]["group"] == "amount")
res = wr.create_user_field(base, "Alcohol", OH["values"], True)
check("writer: a field with a text value is created", res["status"] == "written" and res["key"] == "U0002")
res = wr.create_user_field(base, "Lonely", [num("a", group="g"), num("b")], False)
check("writer: a group of one is refused", res["reason"] == "invalid_definition" and has(res["errors"], "group_single"))
res = wr.save_day(base, "2026-11-18", "", {"U0001": [{"values": {"Done": True, "Steps": 6500}}],
                                          "U0002": [{"time": "20:15", "values": {"Drinks": 2, "Type": "red wine"}}]},
                  now=datetime(2026, 11, 18, 21, 0))
check("writer: a day with a group member and a text is saved", res["status"] == "written")
state, day = rd.read_day(base, "2026-11-18")
check("reader: the day is read back ok with both entries",
      state == "ok" and day["entries"]["U0001"][0]["values"]["Steps"] == 6500
      and day["entries"]["U0002"][0]["values"]["Type"] == "red wine")
check("reader: the snapshot of the day keeps the group", day["key_snapshot"]["U0001"]["values"][1]["group"] == "amount")
res = wr.save_day(base, "2026-11-18", "", {"U0001": [{"values": {"Steps": 1, "Distance": 2}}]},
                  now=datetime(2026, 11, 18, 21, 5))
check("writer: both members of a group in one entry are refused",
      res["status"] == "rejected" and res["reason"] == "invalid_entries_of" and has(res["errors"], "entry0_group_twice"))
res = wr.save_day(base, "2026-11-18", "", {"U0002": [{"time": "20:15", "values": {"Type": "  "}}]},
                  now=datetime(2026, 11, 18, 21, 6))
check("writer: an empty text is refused", res["status"] == "rejected" and res["reason"] == "invalid_entries_of")
check("writer: the refused saves left the day as it was",
      rd.read_day(base, "2026-11-18")[1]["entries"]["U0001"][0]["values"]["Steps"] == 6500)
res = wr.rename_field(base, "U0001", "Walking")
check("writer: a field with a group can be renamed", res["status"] == "written")
check("writer: renaming left the group alone", rd.read_master(base)[1]["fields"]["U0001"]["values"][2]["group"] == "amount")


# ══════════════════════════════════════════════════════════════════════════════
section("6. Writer — save_day")
# ══════════════════════════════════════════════════════════════════════════════

base = prepared_base()
ENT = {"U0001": [{"time": "14:05", "values": {"Anzahl": 1}}],
       "U0002": [{"values": {"Ja/Nein": True}}],
       "G001": [BP_ENTRY, {"time": "19:40", "values": {"systolic": 124, "diastolic": 80, "Pulse": 66}}],
       "G003": [{"values": {"Weight": 80.5}}]}
res = wr.save_day(base, "2026-11-18", "Hotelbett unbequem", ENT, now=T0)
check("a new day: written", res["status"] == "written" and res["date"] == "2026-11-18")
path = day_file(base, "2026-11-18")
check("the day file is at days/diary_2026-11-18.json", path.is_file())
state, day = rd.read_day(base, "2026-11-18")
check("the day reads back ok", state == "ok")
check("the day holds the note and the entries", day["note"] == "Hotelbett unbequem" and day["entries"] == ENT)
check("created is the local time of the first save", day["created"] == "2026-11-18T09:30:00")
check("history is an empty list", day["history"] == [])
check("the schema version and the date are stored", day["schema_version"] == 1 and day["date"] == "2026-11-18")
check("the snapshot holds the used keys", sorted(day["key_snapshot"]) == ["G001", "G003", "U0001", "U0002"])
check("a snapshot entry is the definition without flags",
      day["key_snapshot"]["G001"] == cat.CATALOG["G001"] and "favorite" not in day["key_snapshot"]["U0001"])
check("the file is UTF-8 with the umlaut written out, not escaped", "Stück".encode("utf-8") in read_bytes(path))
check("the file ends with a newline", read_bytes(path).endswith(b"\n"))
check("no .tmp is left", tmp_files(base) == [])
bytes_1 = read_bytes(path)
check("the same save again: unchanged", wr.save_day(base, "2026-11-18", "Hotelbett unbequem", ENT, now=T0_LATER)["status"] == "unchanged")
check("unchanged leaves the file byte for byte as it was", read_bytes(path) == bytes_1)
check("list_days finds the day", rd.list_days(base) == ["2026-11-18"])

# the input is not changed and not kept
ent_in = copy.deepcopy(ENT)
wr.save_day(base, "2026-11-18", "Hotelbett unbequem", ent_in, now=T0_LATER)
check("save_day leaves the entries handed in as they were", ent_in == ENT)
ent_edit = copy.deepcopy(ENT)
ent_edit["G001"][0]["values"]["Pulse"] = 99
wr.save_day(base, "2026-11-18", "Hotelbett unbequem", ent_edit, now=T0_LATER)
ent_edit["G001"][0]["values"]["Pulse"] = 11
check("what is stored does not change when the list handed in is changed later",
      rd.read_day(base, "2026-11-18")[1]["entries"]["G001"][0]["values"]["Pulse"] == 99)

# the same day: free to edit
wr.save_day(base, "2026-11-18", "Hotelbett unbequem", ENT, now=T0_LATER)
res = wr.save_day(base, "2026-11-18", "Hotelbett sehr unbequem", ENT, now=T0_LATER)
check("the same calendar day: a changed note is written", res["status"] == "written")
state, day = rd.read_day(base, "2026-11-18")
check("the note changed, created stayed", day["note"] == "Hotelbett sehr unbequem" and day["created"] == "2026-11-18T09:30:00")
check("history is still empty on a free edit", day["history"] == [])

# a field removed with an empty list; the snapshot only grows
ent_less = {k: v for k, v in ENT.items() if k != "G003"}
ent_less["U0001"] = []
wr.save_day(base, "2026-11-18", "Hotelbett sehr unbequem", ent_less, now=T0_LATER)
state, day = rd.read_day(base, "2026-11-18")
check("an empty list leaves the field out", "U0001" not in day["entries"] and "G003" not in day["entries"])
check("the snapshot keeps the keys it had (it only gains)", sorted(day["key_snapshot"]) == ["G001", "G003", "U0001", "U0002"])
snap_before = copy.deepcopy(day["key_snapshot"])
wr.rename_field(base, "U0001", "Schmerzmittel")
wr.save_day(base, "2026-11-18", "Hotelbett sehr unbequem", ENT, now=T0_LATER)
state, day = rd.read_day(base, "2026-11-18")
check("a rename later is not written into the snapshot of the day", day["key_snapshot"]["U0001"]["name"] == "Schmerztablette")
check("the other snapshot entries are untouched", all(day["key_snapshot"][k] == snap_before[k] for k in ("G001", "G003", "U0002")))
check("the master has the new name", rd.read_master(base)[1]["fields"]["U0001"]["name"] == "Schmerzmittel")
base_s = new_base()
wr.create_user_field(base_s, "Erste", TABLET, True)
wr.save_day(base_s, "2026-11-18", "", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=T0)
wr.create_user_field(base_s, "Zweite", YESNO, False)
wr.save_day(base_s, "2026-11-18", "", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}],
                                       "U0002": [{"values": {"Ja/Nein": False}}]}, now=T0_LATER)
check("a field added on the same day joins the snapshot", sorted(rd.read_day(base_s, "2026-11-18")[1]["key_snapshot"]) == ["U0001", "U0002"])

# the next calendar day: history needed
bytes_2 = read_bytes(path)
res = wr.save_day(base, "2026-11-18", "changed on the next day", ENT, now=T1)
check("the next calendar day: a changed day is refused with history_required",
      res["status"] == "rejected" and res["reason"] == "history_required")
check("the refused day is left byte for byte as it was", read_bytes(path) == bytes_2)
check("the next day, the same content: unchanged, not an error", wr.save_day(base, "2026-11-18", "Hotelbett sehr unbequem", ENT, now=T1)["status"] == "unchanged")

# a day entered afterwards (a past date): the window counts from the first save
res = wr.save_day(base, "2026-11-10", "nachgetragen", {"U0002": [{"values": {"Ja/Nein": False}}]}, now=T0)
check("a past date can be entered: written", res["status"] == "written")
check("its created is the day of the first save", rd.read_day(base, "2026-11-10")[1]["created"].startswith("2026-11-18"))
check("...and it can be corrected that same calendar day",
      wr.save_day(base, "2026-11-10", "nachgetragen, korrigiert", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0_LATER)["status"] == "written")
check("...but not on the day after",
      wr.save_day(base, "2026-11-10", "zu spaet", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T1)["reason"] == "history_required")
check("list_days is sorted", rd.list_days(base) == ["2026-11-10", "2026-11-18"])

# refusals write nothing
base_r = prepared_base()
check("an invalid date is refused", wr.save_day(base_r, "2026-W20-1", "x", {}, now=T0)["reason"] == "invalid_date")
check("a note that is not a string is refused", wr.save_day(base_r, "2026-11-18", None, {}, now=T0)["reason"] == "invalid_note")
check("a note that is too long is refused", wr.save_day(base_r, "2026-11-18", "x" * 100_001, {}, now=T0)["reason"] == "invalid_note")
check("entries that are not a dict are refused", wr.save_day(base_r, "2026-11-18", "x", [], now=T0)["reason"] == "invalid_entries")
check("an invalid key is refused", wr.save_day(base_r, "2026-11-18", "x", {"u0001": []}, now=T0)["reason"] == "invalid_key")
res = wr.save_day(base_r, "2026-11-18", "x", {"U0042": [{"values": {"Anzahl": 1}}]}, now=T0)
check("an unknown field is refused and named", res["reason"] == "unknown_field" and res["key"] == "U0042")
res = wr.save_day(base_r, "2026-11-18", "x", {"G003": [{"values": {"Weight": 80}}, {"values": {"Weight": 81}}]}, now=T0)
check("two entries for a field without time are refused", res["reason"] == "invalid_entries_of" and res["key"] == "G003")
res = wr.save_day(base_r, "2026-11-18", "x", {"G001": [BP_ENTRY], "U0001": [{"time": "25:00", "values": {"Anzahl": 1}}]}, now=T0)
check("one bad field refuses the whole day", res["reason"] == "invalid_entries_of" and res["key"] == "U0001")
check("a refused day leaves no file", not day_file(base_r, "2026-11-18").exists() and tmp_files(base_r) == [])
check("a new day with no note and no entry: unchanged, no file",
      wr.save_day(base_r, "2026-11-18", "", {}, now=T0)["status"] == "unchanged" and not day_file(base_r, "2026-11-18").exists())
check("a new day with only empty lists: unchanged", wr.save_day(base_r, "2026-11-18", "", {"U0001": []}, now=T0)["status"] == "unchanged")
check("a note alone is a day", wr.save_day(base_r, "2026-11-19", "nur Notiz", {}, now=T1)["status"] == "written")
base_x = new_base()
check("no master: a note alone can be saved", wr.save_day(base_x, "2026-11-18", "nur Notiz", {}, now=T0)["status"] == "written")
res = wr.save_day(base_x, "2026-11-19", "x", {"U0001": [{"values": {"Anzahl": 1}}]}, now=T0)
check("no master: an entry for a field is refused (unknown field)", res["reason"] == "unknown_field")
check("a master that is damaged blocks the save", wr.save_day(base_d, "2026-11-18", "x", {}, now=T0)["reason"] == "master_damaged")

# a day with the master gone: the snapshot still serves
base_g = prepared_base()
wr.save_day(base_g, "2026-11-18", "a", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=T0)
dm.fields_path(base_g).unlink()
res = wr.save_day(base_g, "2026-11-18", "b", {"U0001": [{"time": "08:00", "values": {"Anzahl": 2}}]}, now=T0_LATER)
check("the master gone: an entry of a field the day already has is still saved (snapshot)", res["status"] == "written")

# damaged and newer day files
base_k = prepared_base()
wr.save_day(base_k, "2026-11-18", "a", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=T0)
write_raw(day_file(base_k, "2026-11-18"), "not json at all")
junk = read_bytes(day_file(base_k, "2026-11-18"))
res = wr.save_day(base_k, "2026-11-18", "b", {}, now=T0)
check("a damaged day file is never overwritten", res["reason"] == "day_damaged" and read_bytes(day_file(base_k, "2026-11-18")) == junk)
write_raw(day_file(base_k, "2026-11-19"), json.dumps({"schema_version": 2}))
check("a day file of a newer version is left alone", wr.save_day(base_k, "2026-11-19", "b", {}, now=T1)["reason"] == "day_unsupported")

# atomic writing
base_a = prepared_base()
wr.save_day(base_a, "2026-11-18", "erste", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0)
stored = read_bytes(day_file(base_a, "2026-11-18"))
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.save_day(base_a, "2026-11-18", "zweite", {"U0002": [{"values": {"Ja/Nein": False}}]}, now=T0_LATER)
check("a failed move is reported as failed", res["status"] == "failed" and res["reason"] == "write_failed")
check("a stored day stays as it was when the write fails", read_bytes(day_file(base_a, "2026-11-18")) == stored)
check("the .tmp is removed when the write fails", tmp_files(base_a) == [])
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.save_day(base_a, "2026-11-20", "neu", {}, now=T0)
check("a new day whose write fails leaves no file and no .tmp",
      res["status"] == "failed" and not day_file(base_a, "2026-11-20").exists() and tmp_files(base_a) == [])
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.create_user_field(base_a, "Neues Feld", TABLET, True)
check("a field whose write fails: failed, and the counter did not move",
      res["status"] == "failed" and rd.read_master(base_a)[1]["next_id"] == 3)
calls = {"n": 0}
real_replace = os.replace


def flaky_replace(src, dst):
    calls["n"] += 1
    if calls["n"] <= 2:
        raise PermissionError("locked for a moment")
    return real_replace(src, dst)


with patch.object(wr.os, "replace", flaky_replace), patch.object(wr.time, "sleep", lambda s: None):
    res = wr.save_day(base_a, "2026-11-21", "gesperrt", {}, now=T0)
check("a file locked for a moment is tried again and then written", res["status"] == "written" and calls["n"] == 3)
calls["n"] = -100
with patch.object(wr.os, "replace", flaky_replace), patch.object(wr.time, "sleep", lambda s: None):
    res = wr.save_day(base_a, "2026-11-22", "dauerhaft gesperrt", {}, now=T0)
check("a file that stays locked: failed after five tries, no file, no .tmp",
      res["status"] == "failed" and calls["n"] == -95 and not day_file(base_a, "2026-11-22").exists() and tmp_files(base_a) == [])
with patch.object(wr, "_json_bytes", side_effect=ValueError("not serialisable")):
    res = wr.save_day(base_a, "2026-11-23", "x", {}, now=T0)
check("a failure while serialising is a failed write, not an exception", res["status"] == "failed")
res = wr.save_day(base_a, "2026-11-24", "lone \ud800 surrogate", {}, now=T0)
check("a note the UTF-8 encoder cannot take fails cleanly", res["status"] == "failed" and not day_file(base_a, "2026-11-24").exists())

# ══════════════════════════════════════════════════════════════════════════════
section("6b. Writer — a day that is emptied is removed")
# ══════════════════════════════════════════════════════════════════════════════

base_e = prepared_base()
wr.save_day(base_e, "2026-11-18", "nur Notiz", {}, now=T0)
check("a note-only day exists", day_file(base_e, "2026-11-18").is_file())
res = wr.save_day(base_e, "2026-11-18", "", {}, now=T0_LATER)
check("emptied on the day it was made: deleted", res["status"] == "deleted" and res["date"] == "2026-11-18")
check("the file is gone and the day is not listed", not day_file(base_e, "2026-11-18").exists() and rd.list_days(base_e) == [])
check("the reader says missing", rd.read_day(base_e, "2026-11-18") == ("missing", None))
check("no .tmp is left after the removal", tmp_files(base_e) == [])
check("the day can be made again", wr.save_day(base_e, "2026-11-18", "neu", {}, now=T1)["status"] == "written")
check("the day made again has a new created", rd.read_day(base_e, "2026-11-18")[1]["created"].startswith("2026-11-19"))

wr.save_day(base_e, "2026-11-20", "", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0)
res = wr.save_day(base_e, "2026-11-20", "", {"U0002": []}, now=T0_LATER)
check("a day with only entries, all taken out: deleted", res["status"] == "deleted" and not day_file(base_e, "2026-11-20").exists())
wr.save_day(base_e, "2026-11-21", "Notiz", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0)
res = wr.save_day(base_e, "2026-11-21", "", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0_LATER)
check("the note taken out but an entry left: written, not deleted", res["status"] == "written" and day_file(base_e, "2026-11-21").is_file())
res = wr.save_day(base_e, "2026-11-21", "Notiz", {}, now=T0_LATER)
check("the entries taken out but a note left: written, not deleted", res["status"] == "written" and day_file(base_e, "2026-11-21").is_file())

wr.save_day(base_e, "2026-11-22", "Notiz", {}, now=T0)
with_history = load(day_file(base_e, "2026-11-22"))
with_history["history"] = [{"timestamp": "2026-11-18T08:00:00", "before": {"note": "alt", "entries": {}}}]
write_raw(day_file(base_e, "2026-11-22"), json.dumps(with_history))
res = wr.save_day(base_e, "2026-11-22", "", {}, now=T0_LATER)
check("a day with history is kept when it is emptied: written", res["status"] == "written" and day_file(base_e, "2026-11-22").is_file())
kept = rd.read_day(base_e, "2026-11-22")[1]
check("...empty, with its history untouched", kept["note"] == "" and kept["entries"] == {} and kept["history"] == with_history["history"])

wr.save_day(base_e, "2026-11-23", "Notiz", {}, now=T0)
res = wr.save_day(base_e, "2026-11-23", "", {}, now=T1)
check("emptying an older day needs the history: refused, the file stays",
      res["reason"] == "history_required" and day_file(base_e, "2026-11-23").is_file())

wr.save_day(base_e, "2026-11-24", "Notiz", {}, now=T0)
with patch.object(wr.os, "unlink", side_effect=OSError("disk gone")):
    res = wr.save_day(base_e, "2026-11-24", "", {}, now=T0_LATER)
check("a failed removal: failed, the day stays", res["status"] == "failed" and res["reason"] == "remove_failed" and
      day_file(base_e, "2026-11-24").is_file())
unlink_calls = {"n": 0}
real_unlink = os.unlink


def flaky_unlink(path):
    unlink_calls["n"] += 1
    if unlink_calls["n"] <= 2:
        raise PermissionError("locked for a moment")
    return real_unlink(path)


with patch.object(wr.os, "unlink", flaky_unlink), patch.object(wr.time, "sleep", lambda s: None):
    res = wr.save_day(base_e, "2026-11-24", "", {}, now=T0_LATER)
check("a file locked for a moment is tried again and then removed",
      res["status"] == "deleted" and unlink_calls["n"] == 3 and not day_file(base_e, "2026-11-24").exists())
wr.save_day(base_e, "2026-11-25", "Notiz", {}, now=T0)
unlink_calls["n"] = -100
with patch.object(wr.os, "unlink", flaky_unlink), patch.object(wr.time, "sleep", lambda s: None):
    res = wr.save_day(base_e, "2026-11-25", "", {}, now=T0_LATER)
check("a file that stays locked: failed after five tries, the day stays",
      res["status"] == "failed" and unlink_calls["n"] == -95 and day_file(base_e, "2026-11-25").is_file())
check("a new empty day is still unchanged, not deleted",
      wr.save_day(base_e, "2026-12-01", "", {}, now=T0)["status"] == "unchanged")

# ══════════════════════════════════════════════════════════════════════════════
section("6c. Model — time stamps and the history of a day")
# ══════════════════════════════════════════════════════════════════════════════

check("a time stamp is YYYY-MM-DDTHH:MM:SS", dm.valid_timestamp("2026-11-18T09:30:00"))
for bad_stamp in ("2026-11-18", "2026-11-18 09:30:00", "2026-11-18T09:30", "2026-11-18T24:00:00", "2026-13-18T09:30:00",
                  "2026-02-30T09:30:00", "2026-11-18T09:30:00Z", "2026-11-18T09:30:00.5", "", None, 5, "２０２６-11-18T09:30:00"):
    check(f"time stamp {bad_stamp!r} is refused", not dm.valid_timestamp(bad_stamp))

SNAP = {"U0001": user_def(name="Pill", values=TABLET)}
HIST_OK = [{"timestamp": "2026-11-18T09:30:00", "before": {"note": "alt", "entries": {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}}}]
check("an empty history is valid", dm.check_history([], SNAP) == [])
check("a history with one valid state is valid", dm.check_history(HIST_OK, SNAP) == [])
check("a history that is not a list is refused", dm.check_history({}, SNAP) == ["day_history_invalid"])
check("an item that is not a dict is refused", has(dm.check_history(["x"], SNAP), "history0_not_a_dict"))
check("an unknown key in an item is refused",
      has(dm.check_history([{**HIST_OK[0], "extra": 1}], SNAP), "history0_unknown_key"))
check("a bad time stamp is refused", has(dm.check_history([{**HIST_OK[0], "timestamp": "gestern"}], SNAP), "history0_timestamp_invalid"))
check("a missing time stamp is refused",
      has(dm.check_history([{"before": HIST_OK[0]["before"]}], SNAP), "history0_timestamp_invalid"))
check("a state without 'before' is refused", has(dm.check_history([{"timestamp": "2026-11-18T09:30:00"}], SNAP), "history0_before_invalid"))
check("a state without entries is refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": "alt"}}], SNAP), "history0_before_invalid"))
check("a state with an extra key is refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": "a", "entries": {}, "x": 1}}], SNAP), "history0_before_invalid"))
check("a note that is not a string is refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": 5, "entries": {}}}], SNAP), "history0_note_invalid"))
check("a note that is too long is refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": "x" * (dm.MAX_NOTE_LEN + 1), "entries": {}}}], SNAP), "history0_note_invalid"))
check("entries that are not a dict are refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": "", "entries": []}}], SNAP), "history0_entries_not_a_dict"))
check("an entry key without a definition in the snapshot is refused",
      has(dm.check_history(HIST_OK, {}), "history0_key_without_definition"))
check("an entry that does not fit its definition is refused",
      has(dm.check_history([{**HIST_OK[0], "before": {"note": "", "entries": {"U0001": [{"time": "08:00", "values": {"Anzahl": "x"}}]}}}], SNAP),
          "history0:U0001"))
check("the second item is named by its number",
      has(dm.check_history([HIST_OK[0], {"timestamp": "x", "before": HIST_OK[0]["before"]}], SNAP), "history1_timestamp_invalid"))
check("a snapshot that is not a dict does not crash the check", has(dm.check_history(HIST_OK, None), "history0_key_without_definition"))

# ══════════════════════════════════════════════════════════════════════════════
section("6d. Writer — changing an older day keeps its history")
# ══════════════════════════════════════════════════════════════════════════════

T2 = datetime(2026, 11, 20, 10, 0)
T3 = datetime(2026, 11, 21, 12, 30, 15)
base_h = prepared_base()
E1 = {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}
E2 = {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}, {"time": "20:00", "values": {"Anzahl": 2}}]}
wr.save_day(base_h, "2026-11-18", "erste", E1, now=T0)
check("history: the call stays refused without the flag", wr.save_day(base_h, "2026-11-18", "zweite", E2, now=T1)["reason"] == "history_required")
check("history: the refused call changed nothing", load(day_file(base_h, "2026-11-18"))["note"] == "erste")
res = wr.save_day(base_h, "2026-11-18", "zweite", E2, now=T1, keep_history=True)
check("history: with the flag an older day is written", res["status"] == "written")
day = load(day_file(base_h, "2026-11-18"))
check("history: the new content is stored", day["note"] == "zweite" and day["entries"] == E2)
check("history: the old state is the first history item",
      day["history"] == [{"timestamp": "2026-11-19T08:00:00", "before": {"note": "erste", "entries": E1}}])
check("history: 'created' is not touched", day["created"] == "2026-11-18T09:30:00")
check("history: the day file is read back ok and valid", rd.read_day(base_h, "2026-11-18")[0] == "ok")
res = wr.save_day(base_h, "2026-11-18", "dritte", E1, now=T2, keep_history=True)
day = load(day_file(base_h, "2026-11-18"))
check("history: a second change appends, oldest first",
      [h["before"]["note"] for h in day["history"]] == ["erste", "zweite"]
      and [h["timestamp"] for h in day["history"]] == ["2026-11-19T08:00:00", "2026-11-20T10:00:00"])
check("history: the first item stayed as it was", day["history"][0]["before"]["entries"] == E1)
check("history: the second item holds the whole earlier state", day["history"][1]["before"]["entries"] == E2)
before_bytes = read_bytes(day_file(base_h, "2026-11-18"))
res = wr.save_day(base_h, "2026-11-18", "dritte", E1, now=T3, keep_history=True)
check("history: the same content is no change, no history item", res["status"] == "unchanged"
      and read_bytes(day_file(base_h, "2026-11-18")) == before_bytes)
res = wr.save_day(base_h, "2026-11-18", "dritte", E1, now=T3)
check("history: the same content without the flag is unchanged too", res["status"] == "unchanged")

base_f = prepared_base()
wr.save_day(base_f, "2026-11-18", "erste", E1, now=T0)
res = wr.save_day(base_f, "2026-11-18", "frei", E2, now=T0_LATER, keep_history=True)
check("history: on a free day the flag writes no history", res["status"] == "written"
      and load(day_file(base_f, "2026-11-18"))["history"] == [])

base_n = prepared_base()
res = wr.save_day(base_n, "2026-11-05", "nachgetragen", E1, now=T1, keep_history=True)
check("history: a past day without a file is written (the flag is not needed)", res["status"] == "written"
      and load(day_file(base_n, "2026-11-05"))["history"] == [])
check("history: such a day has 'created' of the first save, not the date of the day",
      load(day_file(base_n, "2026-11-05"))["created"] == "2026-11-19T08:00:00")
res = wr.save_day(base_n, "2026-11-06", "nachgetragen", E1, now=T1)
check("history: a past day without a file needs no flag", res["status"] == "written")

# deleting through the history
base_e = prepared_base()
wr.save_day(base_e, "2026-11-18", "x", E1, now=T0)
res = wr.save_day(base_e, "2026-11-18", "", {}, now=T1)
check("history: emptying an older day is refused without the flag", res["reason"] == "history_required")
res = wr.save_day(base_e, "2026-11-18", "", {}, now=T1, keep_history=True)
day = load(day_file(base_e, "2026-11-18"))
check("history: emptying an older day with the flag keeps the day and its history",
      res["status"] == "written" and day["note"] == "" and day["entries"] == {} and len(day["history"]) == 1
      and day["history"][0]["before"] == {"note": "x", "entries": E1})
check("history: the empty day with history is read back ok", rd.read_day(base_e, "2026-11-18")[0] == "ok")
res = wr.save_day(base_e, "2026-11-18", "", {}, now=T2, keep_history=True)
check("history: an empty day saved empty again is unchanged", res["status"] == "unchanged")

# a key of the snapshot and a field added later on an older day
base_s = prepared_base()
wr.save_day(base_s, "2026-11-18", "a", E1, now=T0)
res = wr.save_day(base_s, "2026-11-18", "a", {**E1, "U0002": [{"values": {"Ja/Nein": True}}]}, now=T1, keep_history=True)
day = load(day_file(base_s, "2026-11-18"))
check("history: a field that was not in the day is added to the snapshot, the old state does not hold it",
      res["status"] == "written" and "U0002" in day["key_snapshot"] and "U0002" not in day["history"][0]["before"]["entries"])
check("history: such a day is valid", rd.read_day(base_s, "2026-11-18")[0] == "ok")

# a failed write
base_w = prepared_base()
wr.save_day(base_w, "2026-11-18", "a", E1, now=T0)
stored = read_bytes(day_file(base_w, "2026-11-18"))
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.save_day(base_w, "2026-11-18", "b", E2, now=T1, keep_history=True)
check("history: a failed write is reported and the day is untouched", res["status"] == "failed"
      and read_bytes(day_file(base_w, "2026-11-18")) == stored and tmp_files(base_w) == [])

# a damaged day is never overwritten, flag or not
base_dm = prepared_base()
write_raw(day_file(base_dm, "2026-11-18"), "not json")
res = wr.save_day(base_dm, "2026-11-18", "b", {}, now=T1, keep_history=True)
check("history: a damaged day is refused even with the flag", res["reason"] == "day_damaged")

# the history that exists is valid and a day with a broken history is refused when read
broken = load(day_file(base_h, "2026-11-18"))
broken["history"][0]["before"].pop("entries")
write_raw(day_file(base_h, "2026-11-18"), json.dumps(broken))
check("history: a day with a broken history item is read as damaged", rd.read_day(base_h, "2026-11-18")[0] == "damaged")
check("history: a day with a broken history is never overwritten",
      wr.save_day(base_h, "2026-11-18", "x", {}, now=T3, keep_history=True)["reason"] == "day_damaged")

# ══════════════════════════════════════════════════════════════════════════════
section("6e. Writer — restore_history")
# ══════════════════════════════════════════════════════════════════════════════

base_r2 = prepared_base()
wr.save_day(base_r2, "2026-11-18", "eins", E1, now=T0)
wr.save_day(base_r2, "2026-11-18", "zwei", E2, now=T1, keep_history=True)
wr.save_day(base_r2, "2026-11-18", "drei", {}, now=T2, keep_history=True)
check("restore: the day has two history states", len(load(day_file(base_r2, "2026-11-18"))["history"]) == 2)
res = wr.restore_history(base_r2, "2026-11-18", 0, now=T3)
day = load(day_file(base_r2, "2026-11-18"))
check("restore: the oldest state is back", res["status"] == "written" and day["note"] == "eins" and day["entries"] == E1)
check("restore: the state it replaced was appended, nothing is lost",
      len(day["history"]) == 3 and day["history"][2] == {"timestamp": "2026-11-21T12:30:15", "before": {"note": "drei", "entries": {}}})
check("restore: the older items are untouched", [h["before"]["note"] for h in day["history"][:2]] == ["eins", "zwei"])
check("restore: 'created' and the snapshot stay", day["created"] == "2026-11-18T09:30:00" and "U0001" in day["key_snapshot"])
check("restore: the day is valid", rd.read_day(base_r2, "2026-11-18")[0] == "ok")
res = wr.restore_history(base_r2, "2026-11-18", 2, now=T3)
day = load(day_file(base_r2, "2026-11-18"))
check("restore: a restore can be undone by a restore", res["status"] == "written" and day["note"] == "drei" and day["entries"] == {})
check("restore: the empty day stays (it has a history)", day_file(base_r2, "2026-11-18").is_file() and len(day["history"]) == 4)
base_r4 = prepared_base()
wr.save_day(base_r4, "2026-11-18", "eins", E1, now=T0)
wr.save_day(base_r4, "2026-11-18", "zwei", E1, now=T1, keep_history=True)
res = wr.restore_history(base_r4, "2026-11-18", 0, now=T2)
check("restore: a state with the same entries but another note is a change", res["status"] == "written")
before_restore = read_bytes(day_file(base_r4, "2026-11-18"))
res = wr.restore_history(base_r4, "2026-11-18", 0, now=T3)
check("restore: restoring the state that is already there is unchanged", res["status"] == "unchanged"
      and read_bytes(day_file(base_r4, "2026-11-18")) == before_restore)
for bad_index in (-1, 99, True, 1.0, "0", None):
    check(f"restore: index {bad_index!r} is refused", wr.restore_history(base_r2, "2026-11-18", bad_index, now=T3)["reason"] == "invalid_index")
check("restore: a day without a file is refused", wr.restore_history(base_r2, "2026-10-01", 0, now=T3)["reason"] == "day_missing")
check("restore: a day without history has no state to restore",
      wr.restore_history(base_f, "2026-11-18", 0, now=T3)["reason"] == "invalid_index")
check("restore: an invalid date is refused", wr.restore_history(base_r2, "2026-13-01", 0, now=T3)["reason"] == "invalid_date")
write_raw(day_file(base_dm, "2026-11-19"), "not json")
check("restore: a damaged day is refused", wr.restore_history(base_dm, "2026-11-19", 0, now=T3)["reason"] == "day_damaged")
write_raw(day_file(base_dm, "2026-11-20"), json.dumps({"schema_version": 2}))
check("restore: a day of a newer version is refused", wr.restore_history(base_dm, "2026-11-20", 0, now=T3)["reason"] == "day_unsupported")
stored = read_bytes(day_file(base_r2, "2026-11-18"))
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.restore_history(base_r2, "2026-11-18", 0, now=T3)
check("restore: a failed write is reported and the day is untouched",
      res["status"] == "failed" and read_bytes(day_file(base_r2, "2026-11-18")) == stored and tmp_files(base_r2) == [])
tampered = load(day_file(base_r2, "2026-11-18"))
tampered["history"][0]["before"]["entries"] = {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}
tampered["key_snapshot"].pop("U0001")
write_raw(day_file(base_r2, "2026-11-19"), json.dumps({**tampered, "date": "2026-11-19"}))
check("restore: a day whose history does not fit its snapshot is refused (damaged)",
      wr.restore_history(base_r2, "2026-11-19", 0, now=T3)["reason"] == "day_damaged")

# the real clock has microseconds: the time stamp of the history must still be valid
T_MICRO = datetime(2026, 11, 22, 7, 8, 9, 123456)
base_mu = prepared_base()
wr.save_day(base_mu, "2026-11-18", "eins", E1, now=T0)
wr.save_day(base_mu, "2026-11-18", "zwei", E2, now=T_MICRO, keep_history=True)
check("history: the time stamp has no fraction of a second", load(day_file(base_mu, "2026-11-18"))["history"][0]["timestamp"] == "2026-11-22T07:08:09")
check("history: a day written at a time with microseconds is valid", rd.read_day(base_mu, "2026-11-18")[0] == "ok")
wr.restore_history(base_mu, "2026-11-18", 0, now=T_MICRO)
check("restore: the time stamp has no fraction of a second either",
      load(day_file(base_mu, "2026-11-18"))["history"][1]["timestamp"] == "2026-11-22T07:08:09"
      and rd.read_day(base_mu, "2026-11-18")[0] == "ok")
# the stored state is checked once more before it is written
base_si = prepared_base()
wr.save_day(base_si, "2026-11-18", "eins", E1, now=T0)
wr.save_day(base_si, "2026-11-18", "zwei", E2, now=T1, keep_history=True)
stored = read_bytes(day_file(base_si, "2026-11-18"))
with patch.object(dm, "check_day", side_effect=[[], ["something"]]):    # the reader passes it, the writer's own check does not
    res = wr.restore_history(base_si, "2026-11-18", 0, now=T2)
check("restore: a state that does not pass the check is refused and nothing is written",
      res["reason"] == "state_invalid" and read_bytes(day_file(base_si, "2026-11-18")) == stored)


# ══════════════════════════════════════════════════════════════════════════════
section("7. Writer — recover_master")
# ══════════════════════════════════════════════════════════════════════════════

base_c = prepared_base()
wr.create_user_field(base_c, "Nie benutzt", TABLET, True)  # U0003: no day will use it
wr.save_day(base_c, "2026-11-17", "a", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}],
                                        "G001": [BP_ENTRY]}, now=T0)
wr.save_day(base_c, "2026-11-18", "b", {"U0002": [{"values": {"Ja/Nein": True}}], "G003": [{"values": {"Weight": 80}}]}, now=T0)
master_before = rd.read_master(base_c)[1]
check("recover with a master that is fine: refused", wr.recover_master(base_c)["reason"] == "master_ok")
dm.fields_path(base_c).unlink()
res = wr.recover_master(base_c)
check("recover: written with the number of fields", res["status"] == "written" and res["fields"] == 4 and res["skipped"] == 0)
state, rec = rd.read_master(base_c)
check("the recovered master is valid", state == "ok")
check("the fields that days use are back, with their definitions",
      all(rec["fields"][k][d] == master_before["fields"][k][d] for k in ("U0001", "U0002", "G001", "G003")
          for d in ("name", "set", "values", "with_time")))
check("recovered flags start off", all(f["favorite"] is False and f["archived"] is False for f in rec["fields"].values()))
check("a key no day uses is not recovered", "U0003" not in rec["fields"])
check("next_id is the highest user key seen plus one", rec["next_id"] == 3)
check("a recovered Set 1 field has the catalogue definition", rec["fields"]["G001"]["name"] == "Blood pressure" and
      rec["fields"]["G001"]["maps_to"] == "get_blood_pressure")
check("days still save after the recovery", wr.save_day(base_c, "2026-11-18", "c", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=T0_LATER)["status"] == "written")
check("recovery of a missing master with no days: unchanged", wr.recover_master(new_base())["reason"] == "no_days")
base_c2 = prepared_base()
wr.save_day(base_c2, "2026-11-17", "a", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=T0)
write_raw(dm.fields_path(base_c2), "garbage")
check("recovery with a damaged master: refused without overwrite", wr.recover_master(base_c2)["reason"] == "master_damaged")
check("...and the damaged file is still there", read_bytes(dm.fields_path(base_c2)) == b"garbage")
res = wr.recover_master(base_c2, overwrite=True)
check("recovery with overwrite: written", res["status"] == "written")
check("the damaged file is kept next to the new one", read_bytes(dm.fields_path(base_c2).with_name("fields.json.damaged")) == b"garbage")
check("the new master is valid", rd.read_master(base_c2)[0] == "ok")
# skipped days and two keys that once had the same name
base_c3 = new_base()
wr.create_user_field(base_c3, "Alt", TABLET, True)
wr.save_day(base_c3, "2026-11-10", "", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=datetime(2026, 11, 10, 9, 0))
wr.rename_field(base_c3, "U0001", "Neu")
wr.create_user_field(base_c3, "Alt", TABLET, True)  # the name is free again: U0002
wr.save_day(base_c3, "2026-11-12", "", {"U0002": [{"time": "08:00", "values": {"Anzahl": 2}}]}, now=datetime(2026, 11, 12, 9, 0))
write_raw(day_file(base_c3, "2026-11-14"), "{ broken")
dm.fields_path(base_c3).unlink()
res = wr.recover_master(base_c3)
check("a day that cannot be read is skipped and counted", res["status"] == "written" and res["skipped"] == 1)
names = [f["name"] for f in rd.read_master(base_c3)[1]["fields"].values()]
check("two keys that once had the same name both come back, told apart",
      len(set(n.casefold() for n in names)) == 2 and any("[U0002]" in n for n in names) and rd.read_master(base_c3)[0] == "ok")
check("the first of the two keeps the plain name", sorted(names) == ["Alt", "Alt [U0002]"])

# ══════════════════════════════════════════════════════════════════════════════
section("8. Reader — states and names")
# ══════════════════════════════════════════════════════════════════════════════

base_l = new_base()
check("list_days of a base with no diary_data: empty", rd.list_days(base_l) == [])
folder = dm.days_dir(base_l)
for name in ("diary_2026-11-18.json", "diary_2026-11-17.json", "diary_2026-13-01.json", "diary_x.json",
             "diary_2026-11-18.json.tmp", "notes.json", "2026-11-16.json"):
    write_raw(folder / name, "{}")
(folder / "diary_2026-11-19.json").mkdir()
check("list_days: only real day file names, sorted, folders ignored", rd.list_days(base_l) == ["2026-11-17", "2026-11-18"])
check("read_day of a bad date: invalid_date", rd.read_day(base_l, "2026-02-30") == ("invalid_date", None))
check("read_day of a day with no file: missing", rd.read_day(base_l, "2026-11-01") == ("missing", None))
check("read_day of a file that is {}: damaged", rd.read_day(base_l, "2026-11-18") == ("damaged", None))
day_file(base_l, "2026-11-16").write_bytes(b"\xff\xfe\x00")
check("read_day of bytes that are not valid UTF-8 JSON: damaged", rd.read_day(base_l, "2026-11-16") == ("damaged", None))

base_v = prepared_base()
wr.save_day(base_v, "2026-11-18", "ok", {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]}, now=T0)
good = load(day_file(base_v, "2026-11-18"))


def mutated_day(change):
    day = copy.deepcopy(good)
    change(day)
    write_raw(day_file(base_v, "2026-11-18"), json.dumps(day))
    return rd.read_day(base_v, "2026-11-18")[0]


check("the day as written is ok", mutated_day(lambda d: None) == "ok")
check("a day whose date differs from its file: damaged", mutated_day(lambda d: d.update(date="2026-11-17")) == "damaged")
check("an extra key: damaged", mutated_day(lambda d: d.update(extra=1)) == "damaged")
check("created malformed: damaged", mutated_day(lambda d: d.update(created="yesterday")) == "damaged")
check("created as a week date: damaged", mutated_day(lambda d: d.update(created="2026-W20-1T10:00:00")) == "damaged")
check("created missing: damaged", mutated_day(lambda d: d.pop("created")) == "damaged")
check("note not a string: damaged", mutated_day(lambda d: d.update(note=5)) == "damaged")
check("history not a list: damaged", mutated_day(lambda d: d.update(history={})) == "damaged")
check("history with a non-dict item: damaged", mutated_day(lambda d: d.update(history=["x"])) == "damaged")
check("an entry key with no snapshot: damaged", mutated_day(lambda d: d["entries"].update(U0002=[{"values": {"Ja/Nein": True}}])) == "damaged")
check("an entry that fails its definition: damaged", mutated_day(lambda d: d["entries"]["U0001"][0]["values"].update(Anzahl="x")) == "damaged")
check("a snapshot definition that is invalid: damaged", mutated_day(lambda d: d["key_snapshot"]["U0001"].update(with_time="yes")) == "damaged")
check("schema_version True: damaged (not read as 1)", mutated_day(lambda d: d.update(schema_version=True)) == "damaged")
check("schema_version 2: unsupported", mutated_day(lambda d: d.update(schema_version=2)) == "unsupported")
check("an entries dict that is a list: damaged", mutated_day(lambda d: d.update(entries=[])) == "damaged")

good_master = rd.read_master(base_v)[1]


def mutated_master(change):
    master = copy.deepcopy(good_master)
    change(master)
    write_raw(dm.fields_path(base_v), json.dumps(master))
    return rd.read_master(base_v)[0]


check("the master as written is ok", mutated_master(lambda m: None) == "ok")
check("master: next_id 0: damaged", mutated_master(lambda m: m.update(next_id=0)) == "damaged")
check("master: next_id a bool: damaged", mutated_master(lambda m: m.update(next_id=True)) == "damaged")
check("master: a user key beyond next_id: damaged", mutated_master(lambda m: m.update(next_id=2)) == "damaged")
check("master: flags missing: damaged", mutated_master(lambda m: m["fields"]["U0001"].pop("favorite")) == "damaged")
check("master: a G key with set user: damaged", mutated_master(lambda m: m["fields"]["G001"].update(set="user")) == "damaged")
check("master: two fields with the same name: damaged",
      mutated_master(lambda m: m["fields"]["U0002"].update(name="schmerztablette")) == "damaged")
check("master: an unknown key at top level: damaged", mutated_master(lambda m: m.update(x=1)) == "damaged")
check("master: an invalid field key: damaged", mutated_master(lambda m: m["fields"].update(bad=m["fields"]["U0001"])) == "damaged")
check("master: schema_version 2: unsupported", mutated_master(lambda m: m.update(schema_version=2)) == "unsupported")

# ══════════════════════════════════════════════════════════════════════════════
section("9. Privacy — the log holds no note, no value, no field name")
# ══════════════════════════════════════════════════════════════════════════════


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


SECRET_NOTE = "GEHEIM-Notiz-4711"
SECRET_NAME = "Schwangerschaft-Geheim"
SECRET_VALUE = 123.456
capture = _Capture()
diary_logger = logging.getLogger("diary")
old_level = diary_logger.level
diary_logger.addHandler(capture)
diary_logger.setLevel(logging.DEBUG)
logging.disable(logging.NOTSET)
try:
    base_p = new_base()
    key = wr.create_user_field(base_p, SECRET_NAME, [{"label": "Wert", "type": "number", "unit": "u"}], True)["key"]
    wr.save_day(base_p, "2026-11-18", SECRET_NOTE, {key: [{"time": "08:00", "values": {"Wert": SECRET_VALUE}}]}, now=T0)
    wr.save_day(base_p, "2026-11-18", SECRET_NOTE + "-neu", {key: [{"time": "08:00", "values": {"Wert": 7.654}}]}, now=T1,
                keep_history=True)
    wr.restore_history(base_p, "2026-11-18", 0, now=T1)
    wr.rename_field(base_p, key, SECRET_NAME + "2")
    wr.set_flags(base_p, key, favorite=True)
    with patch.object(wr, "_replace", side_effect=OSError(SECRET_NOTE + " " + SECRET_NAME)):
        wr.save_day(base_p, "2026-11-19", SECRET_NOTE, {}, now=T0)
    write_raw(day_file(base_p, "2026-11-20"), SECRET_NOTE + " not json")
    rd.read_day(base_p, "2026-11-20")
    dm.fields_path(base_p).unlink()
    wr.recover_master(base_p)
finally:
    logging.disable(logging.CRITICAL)
    diary_logger.removeHandler(capture)
    diary_logger.setLevel(old_level)
log_text = "\n".join(capture.records)
check("the log did get lines (the check below is not empty)", len(capture.records) >= 6 and key in log_text)
check("the log holds no note", SECRET_NOTE not in log_text)
check("the log holds no field name", SECRET_NAME not in log_text and "Schwangerschaft" not in log_text)
check("the log holds no value", "123.456" not in log_text and "123" not in log_text.replace("2026", ""))
check("the log holds no value of the history either", "7.654" not in log_text and "-neu" not in log_text)
check("the log tells that a history was kept and a state restored", "history" in log_text and "restored" in log_text)
check("an error is logged by its kind, not by its message", "OSError" in log_text)

# ══════════════════════════════════════════════════════════════════════════════
section("9b. Backup — diary_backup")
# ══════════════════════════════════════════════════════════════════════════════

import json as _json
import logging as _logging

from diary import diary_backup as bk  # noqa: E402
import garmin_backup_common as _common  # noqa: E402


def backup_tree(base):
    """The files below garmin_data/backup/diary/ as relative names."""
    root = bk.backup_dir(base)
    return sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*") if p.is_file()) if root.is_dir() else []


def tree_outside(base):
    """Every file of the archive folder that is not in diary_data/ and not in the diary backup folder."""
    out = []
    for p in Path(base).rglob("*"):
        rel = p.relative_to(base)
        if p.is_file() and rel.parts[0] != "diary_data" and not str(rel).replace(os.sep, "/").startswith("garmin_data/backup/diary/"):
            out.append(str(rel))
    return out


TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
OLD_DAY = "2026-01-15"
OLD_NOW = datetime(2026, 1, 15, 9, 0)

check("backup folder: garmin_data/backup/diary below the archive folder",
      bk.backup_dir("X") == Path("X") / "garmin_data" / "backup" / "diary")

# the field list
base_b = prepared_base()
res = bk.backup_master(base_b)
check("backup_master: first copy is made", res == {"ok": True, "status": "backed_up"})
check("backup_master: the copy is the file, byte for byte",
      bk.read_master_copy(base_b) == read_bytes(dm.fields_path(base_b)))
check("backup_master: nothing else yet in the master folder", backup_tree(base_b) == ["master/fields.json"])
res = bk.backup_master(base_b)
check("backup_master: the same list again is unchanged", res["status"] == "unchanged" and res["ok"])
old_master_bytes = read_bytes(dm.fields_path(base_b))
wr.set_flags(base_b, "U0001", favorite=True)
res = bk.backup_master(base_b)
check("backup_master: a changed list is copied", res["status"] == "backed_up")
check("backup_master: the version before is kept once", bk.read_master_copy(base_b, previous=True) == old_master_bytes)
check("backup_master: the newest copy is the file again", bk.read_master_copy(base_b) == read_bytes(dm.fields_path(base_b)))
good_copy = bk.read_master_copy(base_b)
write_raw(dm.fields_path(base_b), "{ not json")
res = bk.backup_master(base_b)
check("backup_master: a damaged list is not copied (skipped, not ok)", res["status"] == "skipped" and res["ok"] is False
      and res["reason"] == "master_damaged")
check("backup_master: the good copy stays", bk.read_master_copy(base_b) == good_copy)
check("backup_master: no .tmp is left", not [n for n in backup_tree(base_b) if n.endswith(".tmp")])
base_nm = new_base()
check("backup_master: no list, nothing to copy (ok)", bk.backup_master(base_nm) == {"ok": True, "status": "nothing", "reason": "master_missing"})
check("backup_master: nothing was created for it", backup_tree(base_nm) == [])
write_raw(dm.fields_path(base_nm), _json.dumps({"schema_version": 2}))
check("backup_master: a list of a newer version is not copied", bk.backup_master(base_nm)["reason"] == "master_unsupported")

# one day
base_d2 = prepared_base()
wr.save_day(base_d2, TODAY_STR, "heute", E1, now=TODAY)
res = bk.backup_day(base_d2, TODAY_STR)
check("backup_day: the copy is made", res == {"ok": True, "status": "backed_up"})
check("backup_day: it is in the folder of its month", f"days/{TODAY_STR[:7]}/diary_{TODAY_STR}.json" in backup_tree(base_d2))
check("backup_day: the copy is the file, byte for byte", bk.read_day_copy(base_d2, TODAY_STR) == read_bytes(day_file(base_d2, TODAY_STR)))
wr.save_day(base_d2, TODAY_STR, "heute, geaendert", E2, now=TODAY)
bk.backup_day(base_d2, TODAY_STR)
check("backup_day: a changed day replaces its copy", bk.read_day_copy(base_d2, TODAY_STR) == read_bytes(day_file(base_d2, TODAY_STR)))
check("backup_day: an invalid date is skipped", bk.backup_day(base_d2, "2026-13-01") == {"ok": False, "status": "skipped", "reason": "invalid_date"})
check("backup_day: a day without a file has nothing to copy (ok)",
      bk.backup_day(base_d2, "2026-01-01") == {"ok": True, "status": "nothing", "reason": "day_missing"})
good_bytes = read_bytes(day_file(base_d2, TODAY_STR))
write_raw(day_file(base_d2, TODAY_STR), "{ not json")
res = bk.backup_day(base_d2, TODAY_STR)
check("backup_day: a damaged day is not copied over the good copy",
      res["status"] == "skipped" and res["ok"] is False and bk.read_day_copy(base_d2, TODAY_STR) == good_bytes)
write_raw(day_file(base_d2, TODAY_STR), _json.dumps({"schema_version": 2}))
check("backup_day: a day of a newer version is not copied", bk.backup_day(base_d2, TODAY_STR)["reason"] == "day_unsupported")
check("backup_day: a copy of a date that has none is None", bk.read_day_copy(base_d2, "2026-01-01") is None)
check("backup_day: a copy of an invalid date is None", bk.read_day_copy(base_d2, "nonsense") is None)

# an old month goes into a ZIP, a changed day replaces its entry
base_z = prepared_base()
wr.save_day(base_z, OLD_DAY, "alt", E1, now=OLD_NOW)
bk.backup_day(base_z, OLD_DAY)
check("backup_day: a completed month is packed into a monthly ZIP",
      "days/diary_backup_2026-01.zip" in backup_tree(base_z) and not any(n.startswith("days/2026-01/") for n in backup_tree(base_z)))
check("backup_day: the copy is read from the ZIP", bk.read_day_copy(base_z, OLD_DAY) == read_bytes(day_file(base_z, OLD_DAY)))
wr.save_day(base_z, OLD_DAY, "alt, am selben Tag geaendert", E2, now=OLD_NOW)
bk.backup_day(base_z, OLD_DAY)
check("backup_day: a changed day replaces its ZIP entry", bk.read_day_copy(base_z, OLD_DAY) == read_bytes(day_file(base_z, OLD_DAY)))
check("backup_day: still one ZIP", [n for n in backup_tree(base_z) if n.endswith(".zip")] == ["days/diary_backup_2026-01.zip"])

# a day that is deleted keeps its copy
base_k2 = prepared_base()
wr.save_day(base_k2, TODAY_STR, "weg damit", E1, now=TODAY)
bk.backup_day(base_k2, TODAY_STR)
wr.save_day(base_k2, TODAY_STR, "", {}, now=TODAY)
check("backup: the writer removed the emptied day", not day_file(base_k2, TODAY_STR).exists())
check("backup: its copy is still there (the backup is not a mirror)", bk.read_day_copy(base_k2, TODAY_STR) is not None)
check("backup: a day without a file and with a copy has nothing new to back up", bk.backup_day(base_k2, TODAY_STR)["status"] == "nothing")

# the start
base_s2 = prepared_base()
wr.save_day(base_s2, OLD_DAY, "a", E1, now=OLD_NOW)
wr.save_day(base_s2, TODAY_STR, "b", E1, now=TODAY)
res = bk.backup_all(base_s2)
check("backup_all: master and both days are copied", res["ok"] and res["copied"] == 2 and res["master"] == "backed_up" and res["failed"] == 0)
check("backup_all: both days can be read back", all(bk.read_day_copy(base_s2, d) == read_bytes(day_file(base_s2, d)) for d in (OLD_DAY, TODAY_STR)))
res = bk.backup_all(base_s2)
check("backup_all: a second run copies nothing", res["ok"] and res["copied"] == 0 and res["refreshed"] == 0 and res["master"] == "unchanged")
wr.save_day(base_s2, TODAY_STR, "b, changed", E2, now=TODAY)
res = bk.backup_all(base_s2)
check("backup_all: a changed day is refreshed", res["ok"] and res["refreshed"] == 1 and res["copied"] == 0)
check("backup_all: the refreshed copy is the file", bk.read_day_copy(base_s2, TODAY_STR) == read_bytes(day_file(base_s2, TODAY_STR)))
good_old = bk.read_day_copy(base_s2, OLD_DAY)
write_raw(day_file(base_s2, OLD_DAY), "{ not json")
res = bk.backup_all(base_s2)
check("backup_all: a damaged day is reported and does not make the run fail", res["ok"] and res["damaged"] == [OLD_DAY])
check("backup_all: the good copy of the damaged day is not overwritten", good_old is not None and bk.read_day_copy(base_s2, OLD_DAY) == good_old)
base_e2 = new_base()
res = bk.backup_all(base_e2)
check("backup_all: an empty archive: ok, nothing copied", res["ok"] and res["copied"] == 0 and backup_tree(base_e2) == [])
with patch.object(_common, "backfill", return_value={"copied": 0, "skipped": 0, "failed": 2}):
    res = bk.backup_all(base_s2)
check("backup_all: a failed copy makes the run not ok", res["ok"] is False and res["failed"] == 2)
with patch.object(_common, "refresh", return_value={"refreshed": 0, "unreadable": 0, "errors": 3}):
    res = bk.backup_all(base_s2)
check("backup_all: an error of the refresh makes the run not ok", res["ok"] is False and res["failed"] == 3)
with patch.object(_common, "backfill", side_effect=RuntimeError("boom")):
    res = bk.backup_all(base_s2)
check("backup_all: an exception does not escape", res["ok"] is False and res["status"] == "failed")
with patch.object(_common, "backup_file", side_effect=RuntimeError("boom")):
    res = bk.backup_day(base_s2, TODAY_STR)
check("backup_day: an exception does not escape", res["ok"] is False and res["status"] == "failed")
with patch.object(_common, "backup_file", return_value=False):
    res = bk.backup_day(base_s2, TODAY_STR)
check("backup_day: a copy that failed is reported", res == {"ok": False, "status": "failed", "reason": "copy_failed"})
check("backup: nothing is written outside diary_data/ and the diary backup folder", tree_outside(base_s2) == [])
base_aw = prepared_base()
wr.save_day(base_aw, TODAY_STR, "x", E1, now=TODAY)
with patch.object(os, "replace", side_effect=OSError("disk gone")):
    res = bk.backup_master(base_aw)
check("backup_master: a failed move is reported and leaves no .tmp",
      res["ok"] is False and res["status"] == "failed" and not [n for n in backup_tree(base_aw) if n.endswith(".tmp")])

# the check
base_c = prepared_base()
for d, now in ((OLD_DAY, OLD_NOW), (TODAY_STR, TODAY), ("2026-02-02", datetime(2026, 2, 2, 9))):
    wr.save_day(base_c, d, "x" + d, E1, now=now)
rep = bk.check(base_c)
check("check: before any backup everything is not backed up", rep["ok"] and rep["days"] == 3 and rep["not_backed_up"] == 3
      and rep["master_copy"] == "missing" and rep["master"] == "ok" and rep["damaged"] == [] and rep["outdated"] == 0)
bk.backup_all(base_c)
rep = bk.check(base_c)
check("check: after the backup nothing is open", rep["not_backed_up"] == 0 and rep["outdated"] == 0 and rep["master_copy"] == "ok"
      and rep["restorable"] == [] and rep["missing_in_data"] == [])
wr.save_day(base_c, TODAY_STR, "geaendert", E2, now=TODAY)
check("check: a changed day is outdated", bk.check(base_c)["outdated"] == 1)
bk.backup_all(base_c)
write_raw(day_file(base_c, OLD_DAY), "{ not json")
write_raw(day_file(base_c, "2026-02-02"), "{ not json")
bk.backup_day(base_c, "2026-02-02")
rep = bk.check(base_c)
check("check: damaged days are listed", rep["damaged"] == [OLD_DAY, "2026-02-02"])
check("check: a damaged day with a valid copy is restorable", rep["restorable"] == [OLD_DAY, "2026-02-02"])
day_file(base_c, "2026-02-02").unlink()
rep = bk.check(base_c)
check("check: a day that is gone but has a copy is listed", "2026-02-02" in rep["missing_in_data"])
check("check: the checks only read: the copies are untouched", bk.read_day_copy(base_c, OLD_DAY) is not None)
write_raw(bk.master_dir(base_c) / bk.MASTER_COPY_NAME, "{ not json")
check("check: a damaged master copy is told", bk.check(base_c)["master_copy"] == "damaged")
write_raw(dm.fields_path(base_c), "{ not json")
check("check: the state of the field list is told", bk.check(base_c)["master"] == "damaged")
write_raw(day_file(base_c, "2026-03-03"), _json.dumps({"schema_version": 2}))
check("check: a day of a newer version is told apart", bk.check(base_c)["unsupported"] == ["2026-03-03"])
with patch.object(_common, "check_stale", side_effect=RuntimeError("boom")):
    res = bk.check(base_c)
check("check: an exception does not escape", res["ok"] is False and res["status"] == "failed")
base_bd = prepared_base()
wr.save_day(base_bd, OLD_DAY, "a", E1, now=OLD_NOW)
bk.backup_all(base_bd)
write_raw(day_file(base_bd, OLD_DAY), "{ not json")
zip_path = bk.backup_dir(base_bd) / "days" / "diary_backup_2026-01.zip"
bad_zip_bytes = b"not a zip"
zip_path.write_bytes(bad_zip_bytes)
rep = bk.check(base_bd)
check("check: a damaged ZIP does not stop the check and the day is not restorable", rep["ok"] and rep["restorable"] == [])

# edges found while designing the mutants
base_x1 = prepared_base()
wr.save_day(base_x1, TODAY_STR, "x", E1, now=TODAY)
write_raw(dm.fields_path(base_x1), "{ not json")
res = bk.backup_all(base_x1)
check("backup_all: a field list that cannot be copied makes the run not ok", res["ok"] is False and res["master"] == "skipped" and res["copied"] == 1)
base_x2 = prepared_base()
wr.save_day(base_x2, TODAY_STR, "x", E1, now=TODAY)
write_raw(day_file(base_x2, "2026-03-03"), _json.dumps({"schema_version": 2}))
check("backup_all: a day of a newer version is listed with the damaged ones", bk.backup_all(base_x2)["damaged"] == ["2026-03-03"])
bk.backup_master(base_x2)
write_raw(bk.master_dir(base_x2) / bk.MASTER_COPY_NAME, _json.dumps({"hello": 1}))
check("check: a master copy that is JSON but no field list is damaged", bk.check(base_x2)["master_copy"] == "damaged")
base_x3 = prepared_base()
wr.save_day(base_x3, TODAY_STR, "x", E1, now=TODAY)
bk.backup_day(base_x3, TODAY_STR)
write_raw(day_file(base_x3, TODAY_STR), "{ broken")
write_raw(bk.backup_dir(base_x3) / "days" / TODAY_STR[:7] / f"diary_{TODAY_STR}.json", "{ broken too")
rep = bk.check(base_x3)
check("check: a damaged day whose copy is damaged too is not restorable", rep["damaged"] == [TODAY_STR] and rep["restorable"] == [])
write_raw(bk.backup_dir(base_x3) / "days" / TODAY_STR[:7] / f"diary_{TODAY_STR}.json", _json.dumps({"date": TODAY_STR}))
check("check: a copy that is JSON but no valid day is not restorable", bk.check(base_x3)["restorable"] == []
      and bk.read_valid_day_copy(base_x3, TODAY_STR) is None and bk.read_day_copy(base_x3, TODAY_STR) is not None)
check("backup: the previous copy of the field list is the other file",
      bk.read_master_copy(base_b, previous=True) != bk.read_master_copy(base_b))

# privacy
SECRET = "GEHEIM-Tagebuch-9001"
capture2 = _Capture()
diary_logger = _logging.getLogger("diary")
old_level2 = diary_logger.level
diary_logger.addHandler(capture2)
diary_logger.setLevel(_logging.DEBUG)
_logging.disable(_logging.NOTSET)
try:
    base_pv = new_base()
    kk = wr.create_user_field(base_pv, "Feld-" + SECRET, [{"label": "Wert", "type": "number", "unit": "u"}], True)["key"]
    wr.save_day(base_pv, OLD_DAY, SECRET, {kk: [{"time": "08:00", "values": {"Wert": 4.2468}}]}, now=OLD_NOW)
    bk.backup_all(base_pv)
    write_raw(day_file(base_pv, OLD_DAY), SECRET + " not json")
    bk.backup_day(base_pv, OLD_DAY)
    bk.backup_master(base_pv)
    write_raw(dm.fields_path(base_pv), SECRET)
    bk.backup_master(base_pv)
    bk.check(base_pv)
    with patch.object(os, "replace", side_effect=OSError(SECRET)):
        bk.backup_master(base_pv)
finally:
    _logging.disable(_logging.CRITICAL)
    diary_logger.removeHandler(capture2)
    diary_logger.setLevel(old_level2)
log_text2 = "\n".join(capture2.records)
check("backup log: it did get lines", len(capture2.records) >= 3 and "backup_diary" in log_text2)
check("backup log: no note, no value, no field name", SECRET not in log_text2 and "4.2468" not in log_text2)

# ══════════════════════════════════════════════════════════════════════════════
section("9c. Restore from a backup copy — restore_day, restore_master")
# ══════════════════════════════════════════════════════════════════════════════

base_rs = prepared_base()
wr.save_day(base_rs, OLD_DAY, "ein Tag", E1, now=OLD_NOW)
wr.save_day(base_rs, "2026-02-02", "zwei Tage", E2, now=datetime(2026, 2, 2, 9))
bk.backup_all(base_rs)
copy_a = bk.read_day_copy(base_rs, OLD_DAY)
original_a = load(day_file(base_rs, OLD_DAY))
day_file(base_rs, OLD_DAY).unlink()
res = wr.restore_day(base_rs, OLD_DAY, copy_a)
check("restore_day: a day that is gone is restored", res["status"] == "written" and res["date"] == OLD_DAY)
check("restore_day: it is the same day again", load(day_file(base_rs, OLD_DAY)) == original_a)
check("restore_day: and it is read back ok", rd.read_day(base_rs, OLD_DAY)[0] == "ok")
check("restore_day: no .tmp is left", tmp_files(base_rs) == [])
res = wr.restore_day(base_rs, OLD_DAY, copy_a)
check("restore_day: a readable day is never replaced", res["reason"] == "day_exists")
write_raw(day_file(base_rs, OLD_DAY), "{ damaged once")
res = wr.restore_day(base_rs, OLD_DAY, copy_a)
check("restore_day: a damaged day is restored", res["status"] == "written" and load(day_file(base_rs, OLD_DAY)) == original_a)
aside = day_file(base_rs, OLD_DAY).with_name(day_file(base_rs, OLD_DAY).name + ".damaged")
check("restore_day: the damaged file is kept next to it", aside.is_file() and aside.read_text(encoding="utf-8") == "{ damaged once")
check("restore_day: the set-aside file is no day", OLD_DAY in rd.list_days(base_rs) and len(rd.list_days(base_rs)) == 2)
write_raw(day_file(base_rs, OLD_DAY), "{ damaged twice")
res = wr.restore_day(base_rs, OLD_DAY, copy_a)
aside2 = day_file(base_rs, OLD_DAY).with_name(day_file(base_rs, OLD_DAY).name + ".damaged2")
check("restore_day: a second damaged file is kept too, numbered", res["status"] == "written" and aside2.read_text(encoding="utf-8") == "{ damaged twice"
      and aside.read_text(encoding="utf-8") == "{ damaged once")
write_raw(day_file(base_rs, "2026-02-02"), _json.dumps({"schema_version": 2}))
check("restore_day: a file of a newer version is never replaced",
      wr.restore_day(base_rs, "2026-02-02", bk.read_day_copy(base_rs, "2026-02-02"))["reason"] == "day_unsupported")
check("restore_day: it is left as it was", load(day_file(base_rs, "2026-02-02")) == {"schema_version": 2})
for label, data in (("None", None), ("a string", "text"), ("garbage", b"nonsense"), ("a list", b"[]"), ("empty", b""),
                    ("the copy of another day", bk.read_day_copy(base_rs, "2026-02-02"))):
    check(f"restore_day: {label} is refused (copy_invalid)", wr.restore_day(base_rs, "2026-03-03", data)["reason"] == "copy_invalid")
tampered = _json.loads(copy_a.decode("utf-8"))
tampered["entries"] = {"U0001": [{"time": "08:00", "values": {"Anzahl": "x"}}]}
check("restore_day: a copy that fails the checks is refused",
      wr.restore_day(base_rs, "2026-03-03", _json.dumps({**tampered, "date": "2026-03-03"}).encode("utf-8"))["reason"] == "copy_invalid")
check("restore_day: an invalid date is refused", wr.restore_day(base_rs, "2026-13-03", copy_a)["reason"] == "invalid_date")
check("restore_day: nothing was written by the refused calls", not day_file(base_rs, "2026-03-03").exists())
base_fl = prepared_base()
wr.save_day(base_fl, OLD_DAY, "x", E1, now=OLD_NOW)
bk.backup_all(base_fl)
cp = bk.read_day_copy(base_fl, OLD_DAY)
day_file(base_fl, OLD_DAY).unlink()
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.restore_day(base_fl, OLD_DAY, cp)
check("restore_day: a failed write is reported and leaves no file and no .tmp",
      res["status"] == "failed" and not day_file(base_fl, OLD_DAY).exists() and tmp_files(base_fl) == [])
write_raw(day_file(base_fl, OLD_DAY), "{ broken")
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.restore_day(base_fl, OLD_DAY, cp)
check("restore_day: when the damaged file cannot be set aside nothing is changed",
      res["reason"] == "set_aside_failed" and day_file(base_fl, OLD_DAY).read_text(encoding="utf-8") == "{ broken")

# the field list
base_m = prepared_base()
wr.set_flags(base_m, "U0001", favorite=True)
wr.save_day(base_m, TODAY_STR, "x", E1, now=TODAY)
bk.backup_all(base_m)
master_copy = bk.read_master_copy(base_m)
master_before = load(dm.fields_path(base_m))
dm.fields_path(base_m).unlink()
res = wr.restore_master(base_m, master_copy)
check("restore_master: a missing list is restored", res["status"] == "written" and res["fields"] == 4)
check("restore_master: with its flags", load(dm.fields_path(base_m)) == master_before and rd.read_master(base_m)[0] == "ok")
check("restore_master: the counter goes on after the restore",
      wr.create_user_field(base_m, "Nach dem Restore", TABLET, True)["key"] == "U0003")
check("restore_master: a readable list is never replaced", wr.restore_master(base_m, master_copy)["reason"] == "master_ok")
write_raw(dm.fields_path(base_m), "{ broken")
res = wr.restore_master(base_m, master_copy)
check("restore_master: a damaged list is restored", res["status"] == "written" and rd.read_master(base_m)[0] == "ok")
check("restore_master: the damaged one is kept as fields.json.damaged",
      dm.fields_path(base_m).with_name("fields.json.damaged").read_text(encoding="utf-8") == "{ broken")
write_raw(dm.fields_path(base_m), _json.dumps({"schema_version": 2}))
check("restore_master: a list of a newer version is never replaced", wr.restore_master(base_m, master_copy)["reason"] == "master_unsupported")
dm.fields_path(base_m).unlink()
for label, data in (("None", None), ("garbage", b"nonsense"), ("a list", b"[]"), ("a field list that fails its checks", b'{"schema_version": 1}')):
    check(f"restore_master: {label} is refused (copy_invalid)", wr.restore_master(base_m, data)["reason"] == "copy_invalid")
check("restore_master: nothing was written by the refused calls", not dm.fields_path(base_m).exists())
behind = _json.loads(master_copy.decode("utf-8"))
behind["next_id"] = 1
check("restore_master: a counter that is not above its own keys is refused (copy_invalid)",
      wr.restore_master(base_m, _json.dumps(behind).encode("utf-8"))["reason"] == "copy_invalid")
lacking = _json.loads(master_copy.decode("utf-8"))
lacking["fields"].pop("U0001")
check("restore_master: a copy that lacks a key a day uses is refused",
      wr.restore_master(base_m, _json.dumps(lacking).encode("utf-8"))["reason"] == "copy_behind")
write_raw(day_file(base_m, "2026-05-05"), "{ broken")
check("restore_master: with a day that cannot be read the keys are not known: refused",
      wr.restore_master(base_m, master_copy)["reason"] == "days_unreadable")
day_file(base_m, "2026-05-05").unlink()
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.restore_master(base_m, master_copy)
check("restore_master: a failed write is reported and leaves no file and no .tmp",
      res["status"] == "failed" and not dm.fields_path(base_m).exists() and tmp_files(base_m) == [])
write_raw(dm.fields_path(base_m), "{ broken")
with patch.object(wr, "_replace", side_effect=OSError("disk gone")):
    res = wr.restore_master(base_m, master_copy)
check("restore_master: when the damaged list cannot be set aside nothing is changed",
      res["reason"] == "set_aside_failed" and dm.fields_path(base_m).read_text(encoding="utf-8") == "{ broken")

# the way a user goes: backup, damage, check, restore
base_w = prepared_base()
wr.save_day(base_w, OLD_DAY, "wichtig", E2, now=OLD_NOW)
bk.backup_all(base_w)
good = load(day_file(base_w, OLD_DAY))
write_raw(day_file(base_w, OLD_DAY), "{ half written")
rep = bk.check(base_w)
check("restore flow: the check finds the damaged day and can restore it", rep["damaged"] == [OLD_DAY] and rep["restorable"] == [OLD_DAY])
res = wr.restore_day(base_w, OLD_DAY, bk.read_day_copy(base_w, OLD_DAY))
check("restore flow: the day is back as it was", res["status"] == "written" and load(day_file(base_w, OLD_DAY)) == good)
check("restore flow: the check is clean again", bk.check(base_w)["damaged"] == [])
capture3 = _Capture()
diary_logger.addHandler(capture3)
diary_logger.setLevel(_logging.DEBUG)
_logging.disable(_logging.NOTSET)
try:
    write_raw(day_file(base_w, OLD_DAY), SECRET + " broken")
    wr.restore_day(base_w, OLD_DAY, bk.read_day_copy(base_w, OLD_DAY))
    dm.fields_path(base_w).unlink()
    wr.restore_master(base_w, bk.read_master_copy(base_w))
finally:
    _logging.disable(_logging.CRITICAL)
    diary_logger.removeHandler(capture3)
    diary_logger.setLevel(old_level2)
log_text3 = "\n".join(capture3.records)
check("restore log: it tells what was restored and holds no note", "restored" in log_text3 and SECRET not in log_text3 and "wichtig" not in log_text3)

# ══════════════════════════════════════════════════════════════════════════════
section("8b. Reader — search in the notes")
# ══════════════════════════════════════════════════════════════════════════════

base_q = new_base()
NOTES = {
    "2026-03-01": "Urlaub am Meer, sehr erholsam.",
    "2026-03-05": "Fieber seit dem Morgen, Tee getrunken.",
    "2026-03-09": "Zahnarzt und danach Einkaufen",
    "2026-04-02": "Reise nach Wien, Urlaub verlängert, kein Fieber mehr.",
    "2026-05-11": "Übelkeit nach dem Essen",
}
for d, n in NOTES.items():
    wr.save_day(base_q, d, n, {}, now=datetime.fromisoformat(d + "T09:00:00"))
before_tree = sorted(str(p.relative_to(base_q)) for p in base_q.rglob("*"))

res = rd.search_notes(base_q, "urlaub")
check("search: a word is found in two days, newest first", res["ok"] and [h["date"] for h in res["hits"]] == ["2026-04-02", "2026-03-01"])
check("search: the day counts are told", res["searched"] == 5 and res["unreadable"] == 0 and res["truncated"] is False)
check("search: upper and lower case are the same", [h["date"] for h in rd.search_notes(base_q, "URLAUB")["hits"]] == ["2026-04-02", "2026-03-01"])
check("search: umlauts work in either case", [h["date"] for h in rd.search_notes(base_q, "ÜBELKEIT")["hits"]] == ["2026-05-11"]
      and [h["date"] for h in rd.search_notes(base_q, "übelkeit")["hits"]] == ["2026-05-11"])
check("search: every word has to be there", [h["date"] for h in rd.search_notes(base_q, "urlaub fieber")["hits"]] == ["2026-04-02"])
check("search: the order of the words does not matter", [h["date"] for h in rd.search_notes(base_q, "fieber urlaub")["hits"]] == ["2026-04-02"])
check("search: a word that is only a part of a word is found", [h["date"] for h in rd.search_notes(base_q, "ahnarz")["hits"]] == ["2026-03-09"])
check("search: nothing found is an empty list, ok", rd.search_notes(base_q, "Weltraum") == {
    "ok": True, "hits": [], "searched": 5, "unreadable": 0, "truncated": False})
check("search: the same words twice are no problem", len(rd.search_notes(base_q, "urlaub urlaub")["hits"]) == 2)
check("search: extra space and line breaks in the query do not matter", len(rd.search_notes(base_q, "  urlaub \n\t fieber ")["hits"]) == 1)
check("search: a short note is the whole snippet", rd.search_notes(base_q, "zahnarzt")["hits"][0]["snippet"] == "Zahnarzt und danach Einkaufen")

# characters are taken literally
base_l = new_base()
wr.save_day(base_l, "2026-03-01", "Preis 5.50 (brutto) [ok]", {}, now=datetime(2026, 3, 1, 9))
wr.save_day(base_l, "2026-03-02", "Preis 5x50 brutto", {}, now=datetime(2026, 3, 2, 9))
check("search: a dot is a dot, not any character", [h["date"] for h in rd.search_notes(base_l, "5.50")["hits"]] == ["2026-03-01"])
check("search: brackets are taken literally", [h["date"] for h in rd.search_notes(base_l, "(brutto)")["hits"]] == ["2026-03-01"])
check("search: a pattern that would not compile is just text", rd.search_notes(base_l, "[ok")["hits"][0]["date"] == "2026-03-01")
check("search: a backslash is just text", rd.search_notes(base_l, "\\d+")["hits"] == [])
check("search: .* matches nothing special", rd.search_notes(base_l, ".*")["hits"] == [])

# the piece of the note
base_s = new_base()
long_note = "A" * 100 + " Zielwort " + "B" * 200
wr.save_day(base_s, "2026-03-01", long_note, {}, now=datetime(2026, 3, 1, 9))
snippet = rd.search_notes(base_s, "zielwort")["hits"][0]["snippet"]
check("snippet: a long note is cut on both sides", snippet.startswith("…") and snippet.endswith("…"))
check("snippet: it holds the word", "Zielwort" in snippet)
inner = snippet.strip("…")
check("snippet: length is before + word + after", len(inner) == 40 + len("zielwort") + 80)
wr.save_day(base_s, "2026-03-02", "Zielwort " + "C" * 200, {}, now=datetime(2026, 3, 2, 9))
head = rd.search_notes(base_s, "zielwort")["hits"][0]["snippet"]
check("snippet: a word at the start has no ellipsis in front", not head.startswith("…") and head.endswith("…"))
wr.save_day(base_s, "2026-03-03", "D" * 200 + " Zielwort", {}, now=datetime(2026, 3, 3, 9))
tail = rd.search_notes(base_s, "zielwort")["hits"][0]["snippet"]
check("snippet: a word at the end has no ellipsis behind", tail.startswith("…") and not tail.endswith("…"))
wr.save_day(base_s, "2026-03-04", "Zeile eins\n\n  Zeile\tzwei Zielwort\r\nZeile drei", {}, now=datetime(2026, 3, 4, 9))
check("snippet: line breaks and runs of space become one space",
      rd.search_notes(base_s, "zielwort")["hits"][0]["snippet"] == "Zeile eins Zeile zwei Zielwort Zeile drei")
wr.save_day(base_s, "2026-03-05", "alpha beta gamma", {}, now=datetime(2026, 3, 5, 9))
check("snippet: it is cut around the first word of the query", rd.search_notes(base_s, "gamma alpha")["hits"][0]["snippet"] == "alpha beta gamma")
wr.save_day(base_s, "2026-03-06", "erst " + "X" * 300 + " zuletzt", {}, now=datetime(2026, 3, 6, 9))
far = rd.search_notes(base_s, "zuletzt erst")["hits"][0]["snippet"]
check("snippet: it is cut around the first word of the query, not the first in the note", far.startswith("…") and "zuletzt" in far and "erst" not in far.replace("zuletzt", ""))
far2 = rd.search_notes(base_s, "erst zuletzt")["hits"][0]["snippet"]
check("snippet: the other order cuts around the other word", far2.endswith("…") and far2.startswith("erst") and "zuletzt" not in far2)

# a query that is not searched
for bad_query in ("", " ", "\n", "a", " b ", None, 5, ["urlaub"]):
    r = rd.search_notes(base_q, bad_query)
    check(f"query {bad_query!r} is refused: too short, nothing searched",
          r["ok"] is False and r["reason"] == "query_too_short" and r["hits"] == [] and r["searched"] == 0)
check("a query of two characters is searched", rd.search_notes(base_q, "ei")["ok"] is True)
check("two words of one character are enough together", rd.search_notes(base_q, "a b")["ok"] is True)
check("a query of 200 characters is searched, 201 is refused",
      rd.search_notes(base_q, "x" * 200)["ok"] is True and rd.search_notes(base_q, "x" * 201)["reason"] == "query_too_long")

# the limit
base_m2 = new_base()
for i in range(1, 8):
    wr.save_day(base_m2, f"2026-03-0{i}", "Treffer", {}, now=datetime(2026, 3, i, 9))
res = rd.search_notes(base_m2, "treffer", limit=3)
check("limit: only the newest days are returned, and it is told", [h["date"] for h in res["hits"]] == ["2026-03-07", "2026-03-06", "2026-03-05"]
      and res["truncated"] is True)
res = rd.search_notes(base_m2, "treffer", limit=7)
check("limit: exactly as many hits as the limit is not truncated", len(res["hits"]) == 7 and res["truncated"] is False)
check("limit: the default is 200", rd.MAX_SEARCH_HITS == 200)

# days that cannot be read
base_u = new_base()
wr.save_day(base_u, "2026-03-01", "Urlaub", {}, now=datetime(2026, 3, 1, 9))
write_raw(day_file(base_u, "2026-03-02"), "{ Urlaub not json")
write_raw(day_file(base_u, "2026-03-03"), json.dumps({"schema_version": 2, "note": "Urlaub"}))
res = rd.search_notes(base_u, "urlaub")
check("unreadable: a damaged day and a day of a newer version are skipped and counted",
      [h["date"] for h in res["hits"]] == ["2026-03-01"] and res["unreadable"] == 2 and res["searched"] == 1)

# only the notes
base_n = prepared_base()
wr.save_day(base_n, "2026-03-01", "ohne Wort", E1, now=datetime(2026, 3, 1, 9))
wr.save_day(base_n, "2026-03-01", "ohne Wort, geaendert", E1, now=datetime(2026, 3, 2, 9), keep_history=True)
check("search: only the note, not the history of a day", rd.search_notes(base_n, "ohne Wort,")["hits"] != []
      and rd.search_notes(base_n, "Anzahl")["hits"] == [])
wr.save_day(base_n, "2026-03-05", "Notiz", {"U0001": [{"time": "08:00", "values": {"Anzahl": 7}}]}, now=datetime(2026, 3, 5, 9))
check("search: the entries of a day are not searched", rd.search_notes(base_n, "Schmerztablette")["hits"] == [])
old_note_state = rd.search_notes(base_n, "ohne Wort")
check("search: the note of today's state is what is found (not an older note of the history)",
      [h["snippet"] for h in old_note_state["hits"]] == ["ohne Wort, geaendert"])
base_h2 = new_base()
wr.save_day(base_h2, "2026-03-01", "erster Stand", {}, now=datetime(2026, 3, 1, 9))
wr.save_day(base_h2, "2026-03-01", "zweiter Stand", {}, now=datetime(2026, 3, 2, 9), keep_history=True)
check("search: a note that is only in the history is not found", rd.search_notes(base_h2, "erster")["hits"] == []
      and len(rd.search_notes(base_h2, "zweiter")["hits"]) == 1)
check("search: an archive without days: ok, nothing", rd.search_notes(new_base(), "irgendwas") == {
    "ok": True, "hits": [], "searched": 0, "unreadable": 0, "truncated": False})
check("search: the folder was not changed", before_tree == sorted(str(p.relative_to(base_q)) for p in base_q.rglob("*")))

# privacy
capture4 = _Capture()
diary_logger.addHandler(capture4)
diary_logger.setLevel(_logging.DEBUG)
_logging.disable(_logging.NOTSET)
try:
    base_pq = new_base()
    wr.save_day(base_pq, "2026-03-01", SECRET + " Notiz", {}, now=datetime(2026, 3, 1, 9))
    write_raw(day_file(base_pq, "2026-03-02"), SECRET + " broken")
    rd.search_notes(base_pq, SECRET)
    rd.search_notes(base_pq, "Gesucht-" + SECRET)
finally:
    _logging.disable(_logging.CRITICAL)
    diary_logger.removeHandler(capture4)
    diary_logger.setLevel(old_level2)
check("search: neither the query nor a note is in the log", SECRET not in "\n".join(capture4.records) and "Gesucht" not in "\n".join(capture4.records))

# ══════════════════════════════════════════════════════════════════════════════
section("10. Guards — imports, build manifest, no way to the MCP")
# ══════════════════════════════════════════════════════════════════════════════

diary_files = sorted((_SRC / "diary").glob("*.py"))
check("the package has __init__.py and the five modules",
      [p.name for p in diary_files] == ["__init__.py", "diary_backup.py", "diary_catalog.py", "diary_model.py", "diary_reader.py", "diary_writer.py"])
module_names = {p.stem for p in diary_files}
stdlib = set(sys.stdlib_module_names)
bad_imports = []
own_imports = {}
for p in diary_files:
    tree = ast.parse(p.read_text(encoding="utf-8"))
    own_imports[p.name] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in stdlib and not (p.name == "diary_backup.py" and alias.name == "garmin_backup_common"):
                    bad_imports.append((p.name, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if (node.module or "").split(".")[0] not in stdlib:
                    bad_imports.append((p.name, node.module))
            else:
                if node.module is None:
                    own_imports[p.name].update(a.name for a in node.names)
                    if any(a.name not in module_names for a in node.names):
                        bad_imports.append((p.name, "relative"))
                else:
                    bad_imports.append((p.name, "relative with a module"))
check("the package imports only the standard library and its own modules (the backup also garmin_backup_common)", bad_imports == [])
check("the model and the catalogue import nothing of the package",
      own_imports["diary_model.py"] == set() and own_imports["diary_catalog.py"] == set())
check("the reader imports only the model", own_imports["diary_reader.py"] == {"diary_model"})
check("the backup imports the model and the reader", own_imports["diary_backup.py"] == {"diary_model", "diary_reader"})
check("the writer imports the catalogue, the model and the reader",
      own_imports["diary_writer.py"] == {"diary_catalog", "diary_model", "diary_reader"})

spec = importlib.util.spec_from_file_location("build_manifest", _SRC / "compiler" / "build_manifest.py")
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)
listed = {s for s in manifest.SHARED_SCRIPTS if s.startswith("diary/")}
on_disk = {"diary/" + p.name for p in diary_files}
check("every module of diary/ is in SHARED_SCRIPTS and nothing else is", listed == on_disk)
sigs = {k: v for k, v in manifest.SCRIPT_SIGNATURES_BASE.items() if k.startswith("diary/")}
check("every module with logic has a signature entry in the manifest", set(sigs) == on_disk - {"diary/__init__.py"})
check("every signature text stands in its file",
      all(text in (_SRC / key).read_text(encoding="utf-8") for key, texts in sigs.items() for text in texts))

mentions = []
for folder_name in ("clients", "maps"):
    for p in (_SRC / folder_name).glob("*.py"):
        if "diary" in p.read_text(encoding="utf-8", errors="replace").lower():
            mentions.append(p.name)
check("no module of clients/ or maps/ mentions the diary (no way to the MCP in v1.7.8)", mentions == [])

# ══════════════════════════════════════════════════════════════════════════════
section("11. Gaps found by the mutation round (v1.7.8)")
# ══════════════════════════════════════════════════════════════════════════════

# ── writer: the retry on a locked file, the pauses, the cleanup ──────────────
tries = {"n": 0}
pauses = []


def always_locked_replace(src, dst):
    tries["n"] += 1
    raise PermissionError("locked")


base_r1 = new_base()
with patch.object(wr.os, "replace", always_locked_replace), patch.object(wr.time, "sleep", pauses.append):
    res = wr.save_day(base_r1, "2026-11-21", "x", {}, now=T0)
check("writer: a locked file gets five tries", res["status"] == "failed" and tries["n"] == 5)
check("writer: the pauses grow, 0.1 0.2 0.3 0.4 seconds", [round(p, 3) for p in pauses] == [0.1, 0.2, 0.3, 0.4])

base_r2 = new_base()
wr.save_day(base_r2, "2026-11-21", "Notiz", {}, now=T0)
unlinks = {"n": 0}
pauses.clear()


def always_locked_unlink(path):
    unlinks["n"] += 1
    raise PermissionError("locked")


with patch.object(wr.os, "unlink", always_locked_unlink), patch.object(wr.time, "sleep", pauses.append):
    res = wr.save_day(base_r2, "2026-11-21", "", {}, now=T0_LATER)
check("writer: a locked file is removed with five tries and the same pauses",
      res["status"] == "failed" and unlinks["n"] == 5 and [round(p, 3) for p in pauses] == [0.1, 0.2, 0.3, 0.4])

check("writer: the file is written as JSON with two spaces of indent and a final line break",
      wr._json_bytes({"a": 1}) == b'{\n  "a": 1\n}\n')
try:
    wr._json_bytes({"a": float("nan")})
    nan_refused = False
except ValueError:
    nan_refused = True
check("writer: NaN is not written (a failure, not 'NaN' in a file)", nan_refused)

base_r3 = new_base()
with patch.object(wr.os, "fsync", side_effect=OSError("not supported")):
    res = wr.save_day(base_r3, "2026-11-21", "ohne fsync", {}, now=T0)
check("writer: a file system without fsync still takes the write", res["status"] == "written")

# the error of a failed write is not replaced by one of the cleanup
dst_r = new_base() / "x.json"
with patch.object(wr.os, "replace", always_locked_replace), patch.object(wr.time, "sleep", lambda s: None), \
        patch.object(Path, "unlink", side_effect=OSError("cleanup failed too")):
    try:
        wr._write_atomic(dst_r, b"{}")
        raised = None
    except Exception as exc:  # noqa: BLE001 — the type is what is looked at
        raised = type(exc)
check("writer: a failed cleanup of the .tmp does not hide the original error", raised is PermissionError)

# ── writer: boundaries and loops ─────────────────────────────────────────────
base_s = prepared_base()
check("save_day: a note of exactly the largest size is written",
      wr.save_day(base_s, "2026-11-25", "a" * 100000, {}, now=T0)["status"] == "written")
check("save_day: one character more is refused",
      wr.save_day(base_s, "2026-11-26", "a" * 100001, {}, now=T0) == {"status": "rejected", "reason": "invalid_note"})
res = wr.save_day(base_s, "2026-11-27", "Tag", {"U0001": [], "U0002": [{"values": {"Ja/Nein": True}}]}, now=T0)
check("save_day: an empty list of one field does not stop the others",
      res["status"] == "written" and list(rd.read_day(base_s, "2026-11-27")[1]["entries"]) == ["U0002"])

wr.save_day(base_s, "2026-12-02", "erst am 2.", {}, now=datetime(2026, 12, 2, 9, 0))
res = wr.save_day(base_s, "2026-12-02", "geaendert", {}, now=datetime(2026, 12, 1, 9, 0))
check("save_day: a save dated before the day that made the file needs the history as well",
      res["status"] == "rejected" and res["reason"] == "history_required")

# set_flags in both directions
base_f = prepared_base()
wr.set_flags(base_f, "U0001", favorite=True, archived=True)
res = wr.set_flags(base_f, "U0001", favorite=False)
check("set_flags: a favorite can be taken off again", res["status"] == "written" and rd.read_master(base_f)[1]["fields"]["U0001"]["favorite"] is False)
res = wr.set_flags(base_f, "U0001", archived=False)
check("set_flags: an archived field can be brought back",
      res["status"] == "written" and rd.read_master(base_f)[1]["fields"]["U0001"]["archived"] is False)
check("set_flags: the same flags again are unchanged", wr.set_flags(base_f, "U0001", favorite=False, archived=False)["status"] == "unchanged")

# a catalogue field can be renamed to a spelling of its own name (the key is not the same object as the catalogue key)
base_c = new_base()
wr.activate_catalog_field(base_c, "G003")
runtime_key = "G00" + str(3)
res = wr.rename_field(base_c, runtime_key, cat.CATALOG["G003"]["name"].upper())
check("rename_field: the own catalogue name in other capitals is no duplicate", res["status"] == "written")

# restore_history
base_h = new_base()
wr.save_day(base_h, "2026-11-18", "zeta", {}, now=T0)
wr.save_day(base_h, "2026-11-19", "tag", {}, now=T0)
wr.save_day(base_h, "2026-11-18", "alpha", {}, now=T1, keep_history=True)
res = wr.restore_history(base_h, "2026-11-18", 0, now=T1)
check("restore_history: an older note that sorts higher than the present one is put back",
      res["status"] == "written" and rd.read_day(base_h, "2026-11-18")[1]["note"] == "zeta")
wr.save_day(base_h, "2026-11-20", "a", {}, now=T0)
wr.save_day(base_h, "2026-11-20", "b", {}, now=T1, keep_history=True)
wr.save_day(base_h, "2026-11-20", "a", {}, now=T1, keep_history=True)
before_bytes = read_bytes(day_file(base_h, "2026-11-20"))
res = wr.restore_history(base_h, "2026-11-20", 0, now=T1)
check("restore_history: a state equal to the present one is unchanged and nothing is written",
      res["status"] == "unchanged" and read_bytes(day_file(base_h, "2026-11-20")) == before_bytes)

base_h2 = prepared_base()
wr.save_day(base_h2, "2026-11-21", "n", E1, now=T0)
wr.save_day(base_h2, "2026-11-21", "n", E2, now=T1, keep_history=True)
res = wr.restore_history(base_h2, "2026-11-21", 0, now=T1)
check("restore_history: a state that differs only in its entries is put back",
      res["status"] == "written" and rd.read_day(base_h2, "2026-11-21")[1]["entries"] == E1)

# recover_master
base_u = prepared_base()
wr.save_day(base_u, "2026-11-18", "n", E1, now=T0)
master_good = load(dm.fields_path(base_u))
write_raw(dm.fields_path(base_u), json.dumps({**master_good, "schema_version": 2}))
res = wr.recover_master(base_u)
check("recover_master: a list of a newer version is refused as unsupported (not as ok)",
      res == {"status": "rejected", "reason": "master_unsupported"})
res = wr.recover_master(base_u, overwrite=True)
check("recover_master: with overwrite a list of a newer version is replaced, the old one kept",
      res["status"] == "written" and Path(str(dm.fields_path(base_u)) + ".damaged").is_file())

base_n = new_base()
write_raw(dm.fields_path(base_n), "{ not json")
res = wr.recover_master(base_n, overwrite=True)
check("recover_master: a damaged list and no days with overwrite: rebuilt empty",
      res["status"] == "written" and res["fields"] == 0 and rd.read_master(base_n)[0] == "ok"
      and rd.read_master(base_n)[1]["next_id"] == 1)
base_n2 = new_base()
write_raw(dm.fields_path(base_n2), json.dumps({"schema_version": 2}))
res = wr.recover_master(base_n2, overwrite=True)
check("recover_master: a newer list and no days with overwrite: rebuilt empty", res["status"] == "written" and res["fields"] == 0)

base_w = prepared_base()
wr.save_day(base_w, "2026-11-16", "a", E1, now=T0)
wr.save_day(base_w, "2026-11-17", "b", E1, now=T0)
wr.save_day(base_w, "2026-11-18", "c", E1, now=T0)
d16 = load(day_file(base_w, "2026-11-16"))
d16["schema_version"] = 2
write_raw(day_file(base_w, "2026-11-16"), json.dumps(d16))
write_raw(day_file(base_w, "2026-11-17"), "{ not json")
dm_path = dm.fields_path(base_w)
dm_path.unlink()
res = wr.recover_master(base_w)
check("recover_master: a day of a newer version and a damaged day are skipped, the later day is still read",
      res["status"] == "written" and res["skipped"] == 2 and res["fields"] == 1)

# restore_master with a day of a newer version: its keys are not known
base_rm = prepared_base()
wr.save_day(base_rm, "2026-11-18", "n", E1, now=T0)
copy_bytes = read_bytes(dm.fields_path(base_rm))
d_new = load(day_file(base_rm, "2026-11-18"))
d_new["schema_version"] = 2
write_raw(day_file(base_rm, "2026-11-18"), json.dumps(d_new))
dm.fields_path(base_rm).unlink()
res = wr.restore_master(base_rm, copy_bytes)
check("restore_master: a day of a newer version is 'days_unreadable', the list is not put back",
      res == {"status": "rejected", "reason": "days_unreadable"} and not dm.fields_path(base_rm).exists())

# only catalogue keys: next_id starts at 1
base_g = new_base()
wr.activate_catalog_field(base_g, "G001")
wr.save_day(base_g, "2026-11-18", "", {"G001": [{"time": "07:00", "values": {"systolic": 120}}]}, now=T0)
g_day = load(day_file(base_g, "2026-11-18"))
g_day["key_snapshot"]["G001"]["name"] = "Old name of the field"
write_raw(day_file(base_g, "2026-11-18"), json.dumps(g_day))
dm.fields_path(base_g).unlink()
res = wr.recover_master(base_g)
rebuilt = rd.read_master(base_g)
check("recover_master: only catalogue keys: next_id is 1", res["status"] == "written" and rebuilt[0] == "ok" and rebuilt[1]["next_id"] == 1)
check("recover_master: a catalogue field is taken from the catalogue, not from the day's older name",
      rebuilt[1]["fields"]["G001"]["name"] == cat.CATALOG["G001"]["name"])

base_sa = new_base()
write_raw(dm.fields_path(base_sa), "{ not json")
with patch.object(wr, "_replace", side_effect=OSError("cannot move")):
    res = wr.recover_master(base_sa, overwrite=True)
check("recover_master: a damaged list that cannot be set aside: failed, nothing replaced",
      res["status"] == "failed" and res["reason"] == "set_aside_failed" and read_bytes(dm.fields_path(base_sa)) == b"{ not json")

# the numbering of files that are set aside
base_na = new_base()
aside = base_na / "x.json"
names_made = []
for _ in range(4):
    aside.write_text("damaged", encoding="utf-8")
    assert wr._set_aside(aside)
    names_made.append(sorted(p.name for p in base_na.iterdir()))
check("_set_aside: .damaged, .damaged2, .damaged3, .damaged4 in turn",
      names_made[-1] == ["x.json.damaged", "x.json.damaged2", "x.json.damaged3", "x.json.damaged4"])

# ── reader ───────────────────────────────────────────────────────────────────
base_rv = prepared_base()
wr.save_day(base_rv, "2026-11-18", "n", E1, now=T0)
d0 = load(day_file(base_rv, "2026-11-18"))
d0["schema_version"] = 0
write_raw(day_file(base_rv, "2026-11-18"), json.dumps(d0))
check("reader: schema_version 0 is damaged, not 'a newer version'", rd.read_day(base_rv, "2026-11-18") == ("damaged", None))
d0["schema_version"] = -3
write_raw(day_file(base_rv, "2026-11-18"), json.dumps(d0))
check("reader: a negative schema_version is damaged as well", rd.read_day(base_rv, "2026-11-18") == ("damaged", None))

base_sn = new_base()
wr.save_day(base_sn, "2026-11-01", "x" * 40 + "needle " + "y" * 10, {}, now=T0)
wr.save_day(base_sn, "2026-11-02", "x" * 41 + "needle " + "y" * 10, {}, now=T0)
wr.save_day(base_sn, "2026-11-03", "z" * 300 + "needle", {}, now=T0)
hits = {h["date"]: h["snippet"] for h in rd.search_notes(base_sn, "needle")["hits"]}
check("search: a match 40 characters in has nothing cut off at the start", hits["2026-11-01"] == "x" * 40 + "needle " + "y" * 10)
check("search: a match 41 characters in starts with the dots", hits["2026-11-02"] == "…" + "x" * 40 + "needle " + "y" * 10)
check("search: a long note that ends with the match has no dots at the end", hits["2026-11-03"].endswith("needle") and not hits["2026-11-03"].endswith("…"))
check("search: the refused answers are whole",
      rd.search_notes(base_sn, "a") == {"ok": False, "hits": [], "searched": 0, "unreadable": 0, "truncated": False, "reason": "query_too_short"}
      and rd.search_notes(base_sn, "a" * (rd.MAX_QUERY_LEN + 1)) == {"ok": False, "hits": [], "searched": 0, "unreadable": 0,
                                                                     "truncated": False, "reason": "query_too_long"})
base_lm = new_base()
for i in range(1, 5):
    wr.save_day(base_lm, f"2026-11-0{i}", "alles passt", {}, now=T0)
res = rd.search_notes(base_lm, "passt", limit=2)
check("search: at the limit the search stops: two hits, three days read, truncated",
      len(res["hits"]) == 2 and res["truncated"] is True and res["searched"] == 3)

# ── model ────────────────────────────────────────────────────────────────────
check("a day file name that starts right but ends wrong is no day", dm.date_of_day_file_name("diary_2026-01-01.jsoX") is None)
check("a day file name that ends right but starts wrong is no day", dm.date_of_day_file_name("xxxxxx2026-01-01.json") is None)
check("user_key_number reads all the digits", dm.user_key_number("U1234") == 1234 and dm.user_key_number("U0007") == 7
      and dm.user_key_number("G001") is None)

check("definition: a unit of the largest size is fine, one more is too long",
      dm.check_definition(user_def(values=[num("A", unit="u" * 20)])) == []
      and has(dm.check_definition(user_def(values=[num("A", unit="u" * 21)])), "value0_unit_too_long"))
check("definition: the largest number of values is fine, one more is too many",
      dm.check_definition(user_def(values=[num(f"L{i}") for i in range(12)])) == []
      and has(dm.check_definition(user_def(values=[num(f"L{i}") for i in range(13)])), "values_too_many"))
check("definition: a label of the largest size is fine, one more is too long",
      dm.check_definition(user_def(values=[num("l" * 40)])) == []
      and has(dm.check_definition(user_def(values=[num("l" * 41)])), "value0_label_too_long"))
check("definition: a name, a label and a group with a space at the end are not clean",
      has(dm.check_definition(user_def(name="Test ")), "name_not_clean")
      and has(dm.check_definition(user_def(values=[num("A ")])), "value0_label_not_clean")
      and has(dm.check_definition(user_def(values=[num("A", group="g "), num("B", group="g ")])), "value0_group_invalid"))
check("definition: a group of several words is fine",
      dm.check_definition(user_def(values=[num("A", group="Daily amount"), num("B", group="Daily amount")])) == [])
check("definition: an invalid set is only that one error",
      dm.check_definition({"name": "T", "set": "a", "with_time": True, "values": [num("A")]}) == ["set_invalid"]
      and dm.check_definition({"name": "T", "set": "", "with_time": True, "values": [num("A")]}) == ["set_invalid"])
check("definition: a group on a value of an invalid type is told as well",
      has(dm.check_definition(user_def(values=[{"label": "A", "type": "apple", "group": "g"}])), "value0_group_not_allowed"))

defn_t = user_def(with_time=True, values=[num("A"), {"label": "T", "type": "text"}])
errs = dm.check_entries(defn_t, [5, {"time": "07:00"}, {"time": "07:00", "values": {"X": 1, "A": "no"}},
                                 {"time": "07:00", "values": {"A": "x", "T": ""}}])
check("entries: every problem of every entry is told, not only the first",
      errs == ["entry0_not_a_dict", "entry1_values_missing", "entry2_label_unknown", "entry2_value_not_a_number",
               "entry3_value_not_a_number", "entry3_value_not_text"])
check("entries: an empty list is fine for a field without time", dm.check_entries(user_def(with_time=False), []) == [])
check("text: character 31 is a control character, 32 (space) inside is fine",
      has(dm.check_entries(defn_t, [{"time": "07:00", "values": {"T": "a\x1fb"}}]), "entry0_value_not_text")
      and dm.check_entries(defn_t, [{"time": "07:00", "values": {"T": "a b"}}]) == [])

ok_master = {"schema_version": 1, "next_id": 1, "fields": {}}
check("master: an empty list with next_id 1 is fine", dm.check_master(ok_master) == [])
check("master: next_id 0 is not", dm.check_master({**ok_master, "next_id": 0}) == ["master_next_id"])
check("master: a wrong schema_version is told", dm.check_master({**ok_master, "schema_version": 2}) == ["master_schema_version"])
check("master: a missing key is told once, not as an unknown key",
      dm.check_master({"schema_version": 1, "next_id": 1}) == ["master_fields_not_a_dict"])
field_ok = {**user_def(name="A"), "favorite": False, "archived": False}
errs = dm.check_master({**ok_master, "next_id": 9, "fields": {"x": 1, "U0001": 5, "U0002": {**field_ok, "favorite": "no"}}})
check("master: bad keys and bad fields are all told, not only the first",
      errs == ["field_key_invalid:x", "field_not_a_dict:U0001", "field_flags:U0002"])
check("master: a catalogue key with set user and a user key with set garmin are both told",
      has(dm.check_master({**ok_master, "fields": {"G001": field_ok}}), "field_set_mismatch")
      and has(dm.check_master({**ok_master, "fields": {"U0001": {**cat.definition("G001"), "favorite": False, "archived": False}}}),
              "field_set_mismatch"))
check("master: a key at next_id or beyond it is told",
      has(dm.check_master({**ok_master, "next_id": 3, "fields": {"U0003": field_ok}}), "field_key_beyond_next_id")
      and has(dm.check_master({**ok_master, "next_id": 3, "fields": {"U0005": field_ok}}), "field_key_beyond_next_id")
      and dm.check_master({**ok_master, "next_id": 3, "fields": {"U0002": field_ok}}) == [])

day_ok = {"schema_version": 1, "date": "2026-01-01", "created": "2026-01-01T10:00:00", "note": "", "key_snapshot": {},
          "entries": {}, "history": []}
check("day: a clean day has no errors", dm.check_day(day_ok, "2026-01-01") == [])
day_no_hist = {k: v for k, v in day_ok.items() if k != "history"}
check("day: a missing key is told once, not as an unknown key", dm.check_day(day_no_hist, "2026-01-01") == ["day_history_invalid"])
check("day: a note of the largest size is fine, one more is not",
      dm.check_day({**day_ok, "note": "a" * 100000}, "2026-01-01") == []
      and dm.check_day({**day_ok, "note": "a" * 100001}, "2026-01-01") == ["day_note_invalid"])
check("day: an invalid definition in the snapshot that no entry uses is told",
      has(dm.check_day({**day_ok, "key_snapshot": {"U0001": {"name": ""}, "bad": user_def()}}, "2026-01-01"), "snapshot:U0001")
      and has(dm.check_day({**day_ok, "key_snapshot": {"bad": user_def()}}, "2026-01-01"), "snapshot_key_invalid"))
check("day: every entry key without a definition is told",
      dm.check_day({**day_ok, "entries": {"U0001": [{"values": {"A": 1}}], "U0002": [{"values": {"A": 1}}]}}, "2026-01-01")
      == ["entries_key_without_definition:U0001", "entries_key_without_definition:U0002"])

good_ts = "2026-01-01T10:00:00"
history = [5,
           {"timestamp": good_ts, "before": "x"},
           {"timestamp": good_ts, "before": {"note": "n", "entries": "x"}},
           {"timestamp": good_ts, "before": {"note": "n", "entries": {"U0001": [], "U0002": []}}},
           {"timestamp": good_ts, "before": {"note": "n", "entries": {}}, "extra": 1},
           {"before": {"note": "n", "entries": {}}},
           {"timestamp": good_ts, "before": {"note": "a" * 100000, "entries": {}}},
           {"timestamp": good_ts, "before": {"note": "a" * 100001, "entries": {}}}]
check("history: every problem of every item is told, the sizes are exact",
      dm.check_history(history, {}) == ["history0_not_a_dict", "history1_before_invalid", "history2_entries_not_a_dict",
                                        "history3_key_without_definition:U0001", "history3_key_without_definition:U0002",
                                        "history4_unknown_key:extra", "history5_timestamp_invalid", "history7_note_invalid"])

# ── backup ───────────────────────────────────────────────────────────────────
bk_tries = {"n": 0}
bk_pauses = []


def bk_locked_replace(src, dst):
    bk_tries["n"] += 1
    raise PermissionError("locked")


base_bw = new_base()
target_bw = base_bw / "x" / "copy.json"
with patch.object(bk.os, "replace", bk_locked_replace), patch.object(bk.time, "sleep", bk_pauses.append):
    try:
        bk._write_atomic(target_bw, b"{}")
        bk_raised = None
    except Exception as exc:  # noqa: BLE001 — the type is what is looked at
        bk_raised = type(exc)
check("backup: a locked copy gets five tries, 0.1 s apart, then the error",
      bk_raised is PermissionError and bk_tries["n"] == 5 and bk_pauses == [0.1, 0.1, 0.1, 0.1])
check("backup: no .tmp is left after it", not list((base_bw / "x").glob("*.tmp")))
bk_tries["n"] = 0
_real_os_replace = os.replace


def bk_flaky_replace(src, dst):
    bk_tries["n"] += 1
    if bk_tries["n"] <= 4:
        raise PermissionError("locked")
    return _real_os_replace(src, dst)


with patch.object(bk.os, "replace", bk_flaky_replace), patch.object(bk.time, "sleep", lambda s: None):
    bk._write_atomic(target_bw, b"{}")
check("backup: a copy that is free at the fifth try is written", target_bw.read_bytes() == b"{}" and bk_tries["n"] == 5)
with patch.object(bk.os, "replace", bk_locked_replace), patch.object(bk.time, "sleep", lambda s: None), \
        patch.object(Path, "unlink", side_effect=OSError("cleanup failed too")):
    try:
        bk._write_atomic(base_bw / "y" / "copy.json", b"{}")
        bk_raised = None
    except Exception as exc:  # noqa: BLE001
        bk_raised = type(exc)
check("backup: a failed cleanup of the .tmp does not hide the original error", bk_raised is PermissionError)

base_bm = prepared_base()
bk.backup_master(base_bm)
master_copy_path = bk.master_dir(base_bm) / bk.MASTER_COPY_NAME
master_copy_path.write_bytes(read_bytes(dm.fields_path(base_bm)) + b" ")
check("backup_master: a copy that differs only by being longer is replaced", bk.backup_master(base_bm)["status"] == "backed_up"
      and master_copy_path.read_bytes() == read_bytes(dm.fields_path(base_bm)))

check("read_valid_master_copy: a valid copy is given back, a bad one and no copy are None",
      bk.read_valid_master_copy(base_bm) == read_bytes(dm.fields_path(base_bm)))
master_copy_path.write_bytes(b"{}")
check("read_valid_master_copy: a copy that fails the checks is None", bk.read_valid_master_copy(base_bm) is None)
master_copy_path.unlink()
check("read_valid_master_copy: no copy is None", bk.read_valid_master_copy(base_bm) is None)

base_bd2 = prepared_base()
wr.save_day(base_bd2, TODAY_STR, "heute", E1, now=TODAY)
bk.backup_day(base_bd2, TODAY_STR)
check("read_valid_day_copy: a valid copy is given back", bk.read_valid_day_copy(base_bd2, TODAY_STR) == read_bytes(day_file(base_bd2, TODAY_STR)))
check("read_valid_day_copy: no copy is None", bk.read_valid_day_copy(base_bd2, "2026-01-01") is None)
(bk.backup_dir(base_bd2) / "days" / TODAY_STR[:7] / f"diary_{TODAY_STR}.json").write_bytes(b"{}")
check("read_valid_day_copy: a copy that fails the checks is None", bk.read_valid_day_copy(base_bd2, TODAY_STR) is None)

with patch.object(bk.common, "read_copy", side_effect=RuntimeError("x")):
    check("read_day_copy: a failure while reading is None, not an exception", bk.read_day_copy(base_bd2, TODAY_STR) is None)
bk.backup_master(base_bd2)
with patch.object(Path, "read_bytes", side_effect=OSError("x")):
    check("read_master_copy: a failure while reading is None, not an exception", bk.read_master_copy(base_bd2) is None)

with patch.object(bk.common, "backfill", return_value={"copied": 0, "skipped": 0, "failed": 1}), \
        patch.object(bk.common, "refresh", return_value={"refreshed": 0, "unreadable": 0, "errors": 1}):
    res = bk.backup_all(base_bd2)
check("backup_all: the failed copies and the failed refreshes are added up", res["failed"] == 2 and res["ok"] is False)

# check: copies in a ZIP, a stray file, a day without a copy
base_ck = prepared_base()
wr.save_day(base_ck, OLD_DAY, "alt", E1, now=OLD_NOW)
bk.backup_day(base_ck, OLD_DAY)
day_file(base_ck, OLD_DAY).unlink()
(bk.backup_dir(base_ck) / "days" / "0stray.txt").write_text("not a backup", encoding="utf-8")
rep = bk.check(base_ck)
check("check: the day that is gone is found in the monthly ZIP, a stray file in the folder does not stop the search",
      rep["missing_in_data"] == [OLD_DAY])
wr.save_day(base_ck, "2026-02-03", "ohne Kopie", E1, now=datetime(2026, 2, 3, 9, 0))
rep = bk.check(base_ck)
check("check: a day that has a file and no copy is not listed as 'missing in data'", rep["missing_in_data"] == [OLD_DAY])

summary()
