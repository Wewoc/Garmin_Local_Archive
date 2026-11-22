#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_dash_diary.py — layouts/dash_intraday.py, layouts/dash_diary.py, layouts/render/intraday_block.py and the
diary parts of render/explorer.py and render/sleep.py
DIARY v1.7.8.1 — removable (together with src/diary/ and src/maps/diary_map.py).

Covers: the shaping of the intraday series (which days are kept), the text of a diary day (units, order, yes/no,
labels), the presence rows (Note first, names sorted, empty rows left out), the payload built from a real
diary_map on a temporary diary (range, damaged and unsupported days counted), the shared day view (the Sleep
output is exactly what it was before the block was taken out; a prefix changes the ids only; the note never ends
the script; days of the diary in the dropdown only when asked), the Explorer (the page without a diary and
without intraday is exactly what it was; the strip and the diary box only with a diary), and guards (the
helpers import no broker, no module of the diary writes).

The specialists (build() of the Sleep and the Explorer dashboard with a diary) are tested in test_dashboard.py.

Run from the project folder:
    python tests/test_dash_diary.py

Everything is built here in a temporary folder — no archive of the maintainer is needed or touched.
"""

import ast
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

_SRC = Path(__file__).parent.parent
for _p in (_SRC, _SRC / "layouts", _SRC / "app", _SRC / "garmin"):
    sys.path.insert(0, str(_p))

# render/ is a package of the plotter: the same stand-in the plotter registers
if "render" not in sys.modules:
    _pkg = types.ModuleType("render")
    _pkg.__path__ = [str(_SRC / "layouts" / "render")]
    _pkg.__package__ = "render"
    sys.modules["render"] = _pkg

from diary import diary_writer as wr  # noqa: E402
from layouts import dash_diary as dd  # noqa: E402
from layouts import dash_intraday as di  # noqa: E402
from maps import diary_map  # noqa: E402
from render import intraday_block as ib  # noqa: E402


def load_renderer(name):
    spec = importlib.util.spec_from_file_location(f"render.{name}", _SRC / "layouts" / "render" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ROOT = _TMPDIR / "dash_diary_tests"
shutil.rmtree(_ROOT, ignore_errors=True)
_ROOT.mkdir(parents=True)
_COUNTER = [0]


def new_base():
    _COUNTER[0] += 1
    path = _ROOT / f"b{_COUNTER[0]}"
    path.mkdir()
    return path


def at(day):
    return datetime.fromisoformat(f"{day}T09:00:00")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def script_free(html):
    """The page without its first script element (the Plotly bundle): the bundle is not what is tested."""
    start = html.index("<script>")
    return html[:start] + html[html.index("</script>", start) + len("</script>"):]


SERIES = [{"ts": f"2026-11-10T0{h}:00:00", "value": 50 + h} for h in range(6)]
INTRADAY = {
    "2026-11-11": {"heart_rate": SERIES, "stress": SERIES[:3], "body_battery": SERIES, "respiration": []},
    "2026-11-10": {"heart_rate": SERIES[:4], "stress": None, "body_battery": None, "respiration": SERIES[:2]},
}
REFS = {"hrv_last_night": (30, 80), "sleep_duration": (7.0, 9.0), "body_battery_max": (50, 100)}
# Hash of what render/sleep.py produced for INTRADAY before the block was taken out (v1.7.8.1): the old
# _build_intraday_explorer(INTRADAY, REFS).
SLEEP_BLOCK_BEFORE = "81754f026cc51e201847c983cc36b2caace1308e4b5263797157780e43389fbd"
# Hash of the page (without the Plotly bundle) that render/explorer.py produced for EXPLORER_DAILY before v1.7.8.1.
EXPLORER_PAGE_BEFORE = "7926b39d0a49a95ff8269d488d420494e93377b90a2c7b5f9543547c34c5798a"

EXPLORER_DAILY = {
    "dates": ["2026-11-10", "2026-11-11"],
    "field_options": [{"field": "hrv_last_night", "label": "HRV", "unit": "ms"},
                      {"field": "sleep_score", "label": "Sleep score", "unit": ""}],
    "series": {"hrv_last_night": [50, 55], "sleep_score": [70, 75]},
    "sleep_phases": [{"date": "2026-11-10", "deep": 20, "light": 50, "rem": 25, "awake": 5},
                     {"date": "2026-11-11", "deep": 18, "light": 52, "rem": 24, "awake": 6}],
    "sleep_scores": [{"date": "2026-11-10", "feedback": "POSITIVE_DEEP", "qualifier": "GOOD"},
                     {"date": "2026-11-11", "feedback": None, "qualifier": None}],
}

# ══════════════════════════════════════════════════════════════════════════════
section("1. dash_intraday")
# ══════════════════════════════════════════════════════════════════════════════

check("the four series of the day view, in this order",
      [f["key"] for f in di.INTRADAY_FIELDS] == ["heart_rate", "stress", "body_battery", "respiration"]
      and di.INTRADAY_KEYS == ("heart_rate", "stress", "body_battery", "respiration"))
check("each key belongs to a health_map series field", [f["field"] for f in di.INTRADAY_FIELDS] ==
      ["heart_rate_series", "stress_series", "body_battery_series", "respiration_series"])

result = {"garmin": {"values": [{"date": "2026-11-10", "series": [1, 2]}, {"date": "2026-11-11"}]}}
check("intraday_by_date: {date: series}, a missing series is None",
      di.intraday_by_date(result) == {"2026-11-10": [1, 2], "2026-11-11": None})
check("intraday_by_date: a result without a garmin source is empty", di.intraday_by_date({}) == {})

raw = {"heart_rate": {"2026-11-10": [1], "2026-11-11": None, "2026-11-12": []},
       "stress": {"2026-11-12": [2]}, "body_battery": {}, "respiration": {"2026-11-13": []}}
kept = di.build_intraday(raw, ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"])
check("build_intraday keeps the days with at least one non-empty series, in the order given", list(kept) == ["2026-11-10", "2026-11-12"])
check("build_intraday: a day holds all four keys as the broker gave them (an empty list stays, a missing day is None)",
      kept["2026-11-12"] == {"heart_rate": [], "stress": [2], "body_battery": None, "respiration": None})
check("build_intraday: no day gives an empty dict", di.build_intraday(raw, []) == {})

# ══════════════════════════════════════════════════════════════════════════════
section("2. dash_diary — the text of a day")
# ══════════════════════════════════════════════════════════════════════════════

BP = {"name": "Blood pressure", "set": "garmin", "with_time": True,
      "values": [{"label": "systolic", "type": "number", "unit": "mmHg"}, {"label": "diastolic", "type": "number", "unit": "mmHg"},
                 {"label": "Pulse", "type": "number", "unit": "bpm"}]}
YESNO = {"name": "Spazieren gegangen", "set": "user", "with_time": False, "values": [{"label": "Ja/Nein", "type": "yesno"}]}
TEXT = {"name": "Ort", "set": "user", "with_time": False, "values": [{"label": "Wo", "type": "text"}]}

check("an entry: time, field name, 'label: value unit' in the order of the definition",
      dd.format_entry(BP, {"time": "07:15", "values": {"Pulse": 61, "diastolic": 82, "systolic": 128}})
      == {"time": "07:15", "name": "Blood pressure", "text": "systolic: 128 mmHg, diastolic: 82 mmHg, Pulse: 61 bpm"})
check("an entry: a label that was not entered is left out", dd.format_entry(BP, {"time": "07:15", "values": {"Pulse": 61}})["text"] == "Pulse: 61 bpm")
check("an entry: a label the definition does not know is skipped", dd.format_entry(BP, {"time": "07:15", "values": {"x": 1, "Pulse": 61}})["text"] == "Pulse: 61 bpm")
check("an entry: a float that is a whole number loses its '.0', other floats keep their digits",
      dd.format_entry(BP, {"time": "07:15", "values": {"systolic": 128.0, "diastolic": 82.5}})["text"] == "systolic: 128 mmHg, diastolic: 82.5 mmHg")
# mutation round v1.7.8.1: a float is cut to ten digits, a whole float is never written in the e-form, an int keeps every digit
check("an entry: 0.1 + 0.2 is cut to ten digits, 1e20 is written out, a large int keeps all its digits",
      dd.format_entry(BP, {"values": {"systolic": 0.1 + 0.2, "diastolic": 1e20, "Pulse": 10 ** 12}})["text"]
      == "systolic: 0.3 mmHg, diastolic: 100000000000000000000 mmHg, Pulse: 1000000000000 bpm")
check("an entry: yes and no", dd.format_entry(YESNO, {"values": {"Ja/Nein": True}})["text"] == "Ja/Nein: yes"
      and dd.format_entry(YESNO, {"values": {"Ja/Nein": False}})["text"] == "Ja/Nein: no")
check("an entry: a text value and no time", dd.format_entry(TEXT, {"values": {"Wo": "Berlin"}}) == {"time": "", "name": "Ort", "text": "Wo: Berlin"})

DAY = {"state": "ok", "date": "2026-11-10", "note": "Notiz",
       "entries": {"U0002": [{"values": {"Ja/Nein": True}}], "G001": [{"time": "21:00", "values": {"Pulse": 70}}, {"time": "07:15", "values": {"Pulse": 61}}]},
       "definitions": {"U0002": YESNO, "G001": BP}}
formatted = dd.format_day(DAY)
check("a day: the note", formatted["note"] == "Notiz")
check("a day: entries in time order, an entry without a time first",
      [(e["time"], e["name"]) for e in formatted["entries"]] == [("", "Spazieren gegangen"), ("07:15", "Blood pressure"), ("21:00", "Blood pressure")])
check("a day: a note of spaces is no note", dd.format_day({**DAY, "note": "  \n "})["note"] == "")
check("a day with neither note nor entry gives None", dd.format_day({**DAY, "note": "", "entries": {}}) is None)
check("a day that is not ok gives None", dd.format_day({"state": "damaged", "date": "x"}) is None and dd.format_day(None) is None)
# mutation round v1.7.8.1: "not ok" is a comparison for equality, not an order of the words ("unsupported" sorts after "ok")
check("a day gives None for every state but ok, whatever the word sorts like",
      all(dd.format_day({"state": s, "date": "x"}) is None for s in ("damaged", "missing", "unsupported", "zzz")))
check("an entry whose definition is missing is skipped", len(dd.format_day({**DAY, "definitions": {"U0002": YESNO}})["entries"]) == 1)

# ══════════════════════════════════════════════════════════════════════════════
section("3. dash_diary — the presence rows")
# ══════════════════════════════════════════════════════════════════════════════

presence = {"state": "ok", "days": {"2026-11-10": {"note": True, "fields": ["U0001", "U0002"]},
                                    "2026-11-12": {"note": False, "fields": ["U0002"]},
                                    "2026-11-11": {"note": True, "fields": []}},
            "fields": {"U0002": "spazieren", "U0001": "Blutdruck"}}
rows = dd.presence_rows(presence)
check("presence rows: Note first, then the fields by name (case does not matter)", [r["name"] for r in rows] == ["Note", "Blutdruck", "spazieren"])
check("presence rows: the dates of each row, sorted",
      rows[0]["dates"] == ["2026-11-10", "2026-11-11"] and rows[1]["dates"] == ["2026-11-10"] and rows[2]["dates"] == ["2026-11-10", "2026-11-12"])
check("presence rows: no note anywhere, no row 'Note'", dd.presence_rows({**presence, "days": {"2026-11-12": {"note": False, "fields": ["U0002"]}}})[0]["name"] == "spazieren")
check("presence rows: a bad answer gives no rows", dd.presence_rows({"state": "invalid_range"}) == [] and dd.presence_rows(None) == [])
check("presence rows: no rows for every state but ok, whatever the word sorts like (mutation round v1.7.8.1)",
      all(dd.presence_rows({"state": s}) == [] for s in ("invalid_date", "unsupported", "zzz")))

# ══════════════════════════════════════════════════════════════════════════════
section("4. dash_diary — the payload from a real diary_map")
# ══════════════════════════════════════════════════════════════════════════════

base = new_base()
assert wr.create_user_field(base, "Schmerztablette", [{"label": "Anzahl", "type": "number", "unit": "Stück"}], True)["key"] == "U0001"
pill = [{"time": "07:15", "values": {"Anzahl": 2}}]
assert wr.save_day(base, "2026-11-10", "ein Tag", {"U0001": pill}, now=at("2026-11-10"))["status"] == "written"
assert wr.save_day(base, "2026-11-12", "", {"U0001": pill}, now=at("2026-11-12"))["status"] == "written"
assert wr.save_day(base, "2026-12-01", "ausserhalb", {}, now=at("2026-12-01"))["status"] == "written"
payload = dd.build_payload(diary_map, base, "2026-11-01", "2026-11-30")
check("payload: the days of the range with a note or an entry", sorted(payload["days"]) == ["2026-11-10", "2026-11-12"])
check("payload: a day holds note and formatted entries",
      payload["days"]["2026-11-10"] == {"note": "ein Tag", "entries": [{"time": "07:15", "name": "Schmerztablette", "text": "Anzahl: 2 Stück"}]})
check("payload: the presence rows", [r["name"] for r in payload["rows"]] == ["Note", "Schmerztablette"])
check("payload: nothing unreadable", payload["damaged"] == 0 and payload["unsupported"] == 0)
check("payload: exactly these keys", set(payload) == {"days", "rows", "damaged", "unsupported"})

bad = new_base()
assert wr.create_user_field(bad, "Schmerztablette", [{"label": "Anzahl", "type": "number", "unit": "Stück"}], True)["key"] == "U0001"
assert wr.save_day(bad, "2026-11-10", "gut", {}, now=at("2026-11-10"))["status"] == "written"
(bad / "diary_data" / "days" / "diary_2026-11-11.json").write_text("{not json", encoding="utf-8")
(bad / "diary_data" / "days" / "diary_2026-11-12.json").write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
pbad = dd.build_payload(diary_map, bad, "2026-11-01", "2026-11-30")
check("payload: a damaged day and a day of a newer version are counted, the readable day stays",
      pbad["damaged"] == 1 and pbad["unsupported"] == 1 and sorted(pbad["days"]) == ["2026-11-10"])

empty = {"days": {}, "rows": [], "damaged": 0, "unsupported": 0}
check("payload: no base folder gives the empty payload", dd.build_payload(diary_map, None, "2026-11-01", "2026-11-30") == empty
      and dd.build_payload(diary_map, "", "2026-11-01", "2026-11-30") == empty)
check("payload: a bad range gives the empty payload", dd.build_payload(diary_map, base, "2026-13-01", "2026-11-30") == empty
      and dd.build_payload(diary_map, base, "2026-11-30", "2026-11-01") == empty)
check("payload: a folder without a diary gives the empty payload", dd.build_payload(diary_map, new_base(), "2026-11-01", "2026-11-30") == empty)


# mutation round v1.7.8.1: the loop over the days with a broker that is handed in (the loop keeps going after a day
# without content and after a day that went bad between the two reads; that day is counted once)
class _Broker:
    def __init__(self, presence, days):
        self._presence, self._days = presence, days

    def get_presence(self, base_dir, date_from, date_to):
        return self._presence

    def get_day(self, base_dir, date_str):
        return self._days[date_str]


def _presence(days):
    return {"state": "ok", "date_from": "2026-11-01", "date_to": "2026-11-30", "days": days, "fields": {},
            "damaged": [], "unsupported": [], "master": "ok"}


_GOOD = {"state": "ok", "date": "2026-11-02", "note": "gut", "entries": {}, "definitions": {}}
for _state in ("unsupported", "zzz"):
    check(f"payload: a presence answer in the state '{_state}' gives the empty payload",
          dd.build_payload(_Broker({"state": _state}, {}), "x", "2026-11-01", "2026-11-30") == empty)
p_empty_first = dd.build_payload(_Broker(_presence({"2026-11-01": {"note": False, "fields": []}, "2026-11-02": {"note": True, "fields": []}}),
                                         {"2026-11-02": _GOOD}), "x", "2026-11-01", "2026-11-30")
check("payload: a day without a note and without a field is left out and the loop goes on",
      sorted(p_empty_first["days"]) == ["2026-11-02"] and p_empty_first["damaged"] == 0)
p_went_bad = dd.build_payload(_Broker(_presence({"2026-11-01": {"note": True, "fields": []}, "2026-11-02": {"note": True, "fields": []}}),
                                      {"2026-11-01": {"state": "damaged", "date": "2026-11-01"}, "2026-11-02": _GOOD}),
                              "x", "2026-11-01", "2026-11-30")
check("payload: a day that went bad between the two reads is counted once and the loop goes on",
      p_went_bad["damaged"] == 1 and sorted(p_went_bad["days"]) == ["2026-11-02"] and p_went_bad["unsupported"] == 0)

# the history of a day (earlier text) never reaches the payload
hbase = new_base()
assert wr.create_user_field(hbase, "Schmerztablette", [{"label": "Anzahl", "type": "number", "unit": "Stück"}], True)["key"] == "U0001"
assert wr.save_day(hbase, "2026-11-01", "GEHEIMWORT-frueher", {"U0001": pill}, now=at("2026-11-01"))["status"] == "written"
assert wr.save_day(hbase, "2026-11-01", "spaeter", {"U0001": pill}, now=at("2026-11-20"), keep_history=True)["status"] == "written"
check("payload: the earlier text of a day with a history is not in the payload",
      "GEHEIMWORT" not in json.dumps(dd.build_payload(diary_map, hbase, "2026-11-01", "2026-11-30")))

# ══════════════════════════════════════════════════════════════════════════════
section("5. intraday_block — the shared day view")
# ══════════════════════════════════════════════════════════════════════════════

block = ib.build_block(INTRADAY, prefix="sleep")
check("the Sleep block is exactly what render/sleep.py produced before the block was taken out", sha(block) == SLEEP_BLOCK_BEFORE)
check("Sleep ids and function names (prefix sleep)",
      all(s in block for s in ('id="sleep-explorer"', 'id="sleep-intraday-select"', 'id="sleep-intraday-chart"',
                               "sleepUpdateIntraday", "sleepJumpToDay")))
check("no diary box without a diary", 'id="sleep-diary"' not in block and "_showDiary" not in block)
check("nothing to show gives an empty string", ib.build_block({}, prefix="sleep") == "" and ib.build_block(None, prefix="sleep") == "")

eblock = ib.build_block(INTRADAY, prefix="explorer")
check("another prefix changes the ids and nothing else", eblock == block.replace("sleep", "explorer"))

DIARY = {"days": {"2026-11-09": {"note": "nur Tagebuch", "entries": []},
                  "2026-11-10": {"note": "Notiz </script><b>x</b> & Co", "entries": [{"time": "07:15", "name": "A", "text": "b: 1"}]}},
         "damaged": 2, "unsupported": 1}
dblock = ib.build_block(INTRADAY, prefix="explorer", diary=DIARY)
check("with a diary: the diary box, the 'no intraday' message and the function that fills the box",
      all(s in dblock for s in ('id="explorer-diary"', 'id="explorer-intraday-none"', "_showDiary(date)")))
check("with a diary: the note never ends the script and never stands as HTML",
      "</script><b>x</b>" not in dblock and "\\u003c/script\\u003e\\u003cb\\u003ex\\u003c/b\\u003e \\u0026 Co" in dblock)
check("with a diary: the box is filled with textContent, never with innerHTML", "textContent" in dblock and "innerHTML" not in dblock)
check("with a diary: the numbers of unreadable days are embedded", '{"damaged": 2, "unsupported": 1}' in dblock)
check("days of the diary are not in the dropdown unless asked", 'value="2026-11-09"' not in dblock)
ublock = ib.build_block(INTRADAY, prefix="explorer", diary=DIARY, include_diary_days=True)
check("days of the diary are in the dropdown when asked, newest first",
      re.findall(r'<option value="([0-9-]+)"', ublock) == ["2026-11-11", "2026-11-10", "2026-11-09"])
check("only the diary and no intraday: the block is still built when the diary days are asked for",
      ib.build_block({}, prefix="explorer", diary=DIARY, include_diary_days=True) != ""
      and ib.build_block({}, prefix="explorer", diary=DIARY) == "")
check("json_for_script writes < > & as \\uXXXX and stays valid JSON",
      ib.json_for_script({"a": "</script> & <b>"}) == '{"a": "\\u003c/script\\u003e \\u0026 \\u003cb\\u003e"}'
      and json.loads(ib.json_for_script({"a": "</script> & <b>"})) == {"a": "</script> & <b>"})

# ══════════════════════════════════════════════════════════════════════════════
section("6. The renderers")
# ══════════════════════════════════════════════════════════════════════════════

# A fresh checkout (CI) has no layouts/plotly.min.js — it is not in the repo, build_all.py fetches it, and
# get_plotly_script() raises instead of falling back to the CDN. Same stand-in as test_dashboard.py: only when the
# real bundle is absent, so a local run still renders with the real file.
import dash_layout_html as layout_html
if not (Path(layout_html.__file__).parent / layout_html.get_plotly_local_filename()).exists():
    def _plotly_stub(layouts_dir):
        return "<script>/* plotly stub (tests, no bundle in this checkout) */</script>"
    layout_html.get_plotly_script = _plotly_stub
    print("  (plotly.min.js not present — the pages render with a test stub)")

ex = load_renderer("explorer")
sl = load_renderer("sleep")

out = _ROOT / "explorer_plain.html"
ex.render({"layout": "explorer", "title": "Explorer", "subtitle": "s", "daily": EXPLORER_DAILY, "intraday": {}}, out)
plain = out.read_text(encoding="utf-8")
check("the Explorer page without intraday and without a diary is exactly what it was", sha(script_free(plain)) == EXPLORER_PAGE_BEFORE)
check("... and has neither the day view nor the strip", "explorer-intraday-select" not in plain and "explorer-diary" not in plain)

out = _ROOT / "explorer_intraday.html"
ex.render({"layout": "explorer", "title": "Explorer", "subtitle": "s", "daily": EXPLORER_DAILY, "intraday": INTRADAY}, out)
page = out.read_text(encoding="utf-8")
check("the Explorer with intraday: the day view, no diary box, no strip",
      'id="explorer-intraday-select"' in page and 'id="explorer-diary"' not in page and 'id="explorer-diary-strip"' not in page)
check("the Explorer with intraday: the click on a day of the chart is wired", "plotly_click" in page and "explorerJumpToDay" in page)

DIARY_ROWS = {**DIARY, "rows": [{"name": "Note", "dates": ["2026-11-09", "2026-11-10"]}, {"name": "A </b>", "dates": ["2026-11-10"]}]}
out = _ROOT / "explorer_diary.html"
ex.render({"layout": "explorer", "title": "Explorer", "subtitle": "s", "daily": EXPLORER_DAILY, "intraday": INTRADAY, "diary": DIARY_ROWS}, out)
page = out.read_text(encoding="utf-8")
check("the Explorer with a diary: the strip, the diary box and the day view",
      'id="explorer-diary-strip"' in page and 'id="explorer-diary"' in page and 'id="explorer-intraday-select"' in page)
check("the Explorer with a diary: the days of the diary are in the dropdown", 'value="2026-11-09"' in page)
check("the Explorer with a diary: the rows of the strip are embedded without raw '<'",
      "\\u003c/b\\u003e" in page and "A </b>" not in page)
check("the Explorer with a diary: no closing script tag from a note", "</script><b>x</b>" not in page)
check("the Explorer with a diary: the strip and the day view come before the footer", page.index("explorer-diary-strip") < page.index("<footer>"))

# a diary with rows but no intraday at all
out = _ROOT / "explorer_diary_only.html"
ex.render({"layout": "explorer", "title": "Explorer", "subtitle": "s", "daily": EXPLORER_DAILY, "intraday": {}, "diary": DIARY_ROWS}, out)
page = out.read_text(encoding="utf-8")
check("the Explorer with a diary and no intraday: the day view lists the days of the diary", 'value="2026-11-09"' in page and 'id="explorer-diary"' in page)

SLEEP_DATA = {"layout": "sleep", "title": "Sleep Dashboard", "subtitle": "s", "date_from": "2026-11-10", "date_to": "2026-11-11", "refs": REFS,
              "rows": [{"date": "2026-11-11", "deep": 20.0, "light": 50.0, "rem": 25.0, "awake": 5.0, "duration_h": 7.5, "score": 74,
                        "qualifier": "FAIR", "feedback": "POSITIVE_DEEP", "hrv": 62.0, "body_battery": 85.0, "hrv_7d_avg": 60.1}],
              "intraday": INTRADAY}
out = _ROOT / "sleep_plain.html"
sl.render(SLEEP_DATA, out)
check("the Sleep page without a diary has the block of before", block in out.read_text(encoding="utf-8"))
out = _ROOT / "sleep_diary.html"
sl.render({**SLEEP_DATA, "diary": DIARY}, out)
spage = out.read_text(encoding="utf-8")
check("the Sleep page with a diary: the diary box, the sleep ids, only the days of intraday in the dropdown",
      'id="sleep-diary"' in spage and "sleepUpdateIntraday" in spage and 'value="2026-11-09"' not in spage)

# ══════════════════════════════════════════════════════════════════════════════
section("7. Guards")
# ══════════════════════════════════════════════════════════════════════════════


def imports_of(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names


check("dash_intraday imports nothing", imports_of(_SRC / "layouts" / "dash_intraday.py") == set())
check("dash_diary imports nothing (the broker is handed in by the specialist)", imports_of(_SRC / "layouts" / "dash_diary.py") == set())
check("intraday_block imports only json", imports_of(_SRC / "layouts" / "render" / "intraday_block.py") == {"json"})
for name in ("sleep_garmin_html-xls_dash.py", "explorer_garmin-context_html_dash.py"):
    text = (_SRC / "dashboards" / name).read_text(encoding="utf-8")
    check(f"{name} reaches the diary through diary_map only (no diary_reader, no diary_writer, no file access)",
          "from maps import diary_map" in text and "diary_reader" not in text and "diary_writer" not in text and "open(" not in text)
check("the intraday fields of the Sleep dashboard are no longer a copy in the specialist",
      "_INTRADAY_FIELDS" not in (_SRC / "dashboards" / "sleep_garmin_html-xls_dash.py").read_text(encoding="utf-8"))
_recovery_text = (_SRC / "dashboards" / "sleep_recovery_context_dash.py").read_text(encoding="utf-8")
check("the Sleep & Recovery specialist has no own copy of the intraday fields or of intraday_by_date",
      "_INTRADAY_FIELDS" not in _recovery_text and "def _intraday_by_date" not in _recovery_text)
check("the Sleep & Recovery specialist takes fields, extraction and day filter from dash_intraday",
      "from layouts.dash_intraday import INTRADAY_FIELDS, intraday_by_date, build_intraday" in _recovery_text
      and "build_intraday(intraday_raw, all_dates)" in _recovery_text)

summary()
