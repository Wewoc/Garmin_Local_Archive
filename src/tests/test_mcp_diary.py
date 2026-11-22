#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_mcp_diary.py — the diary in the MCP cache (v1.7.8.1, layer 3)
DIARY — removable (together with src/diary/ and src/maps/diary_map.py).

Covers: mcp_sql (the table mcp_diary_days, hashes, replacing a row, the range read, clear_all that empties every
table and leaves no text behind in the file), gateway_map (the internal kind "diary_cache_feed" exists only while
"Diary in MCP" is on), mcp_update (the two diary steps: the whole cache is rebuilt when the MCP switch changes in
either direction or a cached day has no readable file, never for a changed or a new day, never for the export
switch; a changed day replaces its row; bad days are counted; errors do not clear anything; the order inside
sync_all and the result keys) and guards (nothing in garmin/, diary/, context/ imports the cache).

Real SQLite database and a real diary in a temporary folder; the switch is the ENV variable GARMIN_MCP_DIARY_ENABLED
(read fresh on every pass). No archive of the maintainer is needed or touched.

Run from the project folder:
    python tests/test_mcp_diary.py
"""

import ast
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "garmin"))
sys.path.insert(0, str(_ROOT / "clients"))
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
logging.disable(logging.CRITICAL)

from support import check, section, summary  # noqa: E402

_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_mcp_diary_test_"))
os.environ["GARMIN_OUTPUT_DIR"] = str(_TMPDIR)
os.environ["GARMIN_MCP_DIARY_ENABLED"] = "0"
os.environ["GARMIN_MCP_DIARY_EXPORT_ENABLED"] = "0"

import garmin_config as cfg  # noqa: E402,F401  (flat copy, as the app imports it)
from garmin import garmin_config as gcfg  # noqa: E402
from diary import diary_writer as wr  # noqa: E402
from maps import gateway_map, mcp_map  # noqa: E402
import mcp_sql  # noqa: E402
import mcp_update  # noqa: E402

BASE = gcfg.BASE_DIR
check("(setup) the cache and the diary use the temporary folder", Path(BASE) == _TMPDIR)

SECRET = "GEHEIMWORT-Rueckenschmerz"
PILL = [{"label": "Anzahl", "type": "number", "unit": "Stück"}]


def at(day):
    return datetime.fromisoformat(f"{day}T09:00:00")


def day_file(date_str):
    return _TMPDIR / "diary_data" / "days" / f"diary_{date_str}.json"


def set_switch(mcp=None, export=None):
    for name, value in (("GARMIN_MCP_DIARY_ENABLED", mcp), ("GARMIN_MCP_DIARY_EXPORT_ENABLED", export)):
        if value is not None:
            os.environ[name] = "1" if value else "0"


def health_rows():
    return mcp_sql.get_connection().execute("SELECT COUNT(*) AS n FROM mcp_health_days").fetchone()["n"]


def put_sentinel():
    mcp_sql.upsert_health_day("2026-03-01", {"hrv": 50}, "x")


# ══════════════════════════════════════════════════════════════════════════════
section("1. mcp_sql — the table, the hashes, the range, clear_all")
# ══════════════════════════════════════════════════════════════════════════════

mcp_sql.init_db()
tables = {r["name"] for r in mcp_sql.get_connection().execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
check("the table mcp_diary_days exists next to the eleven others", "mcp_diary_days" in tables and len([t for t in tables if t.startswith("mcp_")]) == 12)
check("no hash before the first day", mcp_sql.get_diary_hashes() == {})

mcp_sql.upsert_diary_day("2026-11-10", "h1", {"note": "eins", "entries": {}, "definitions": {}})
mcp_sql.upsert_diary_day("2026-11-12", "h2", {"note": "zwei", "entries": {"U0001": [{"values": {"Anzahl": 2}}]}, "definitions": {"U0001": {"name": "Tablette"}}})
check("a day is stored with its hash", mcp_sql.get_diary_hashes() == {"2026-11-10": "h1", "2026-11-12": "h2"})
mcp_sql.upsert_diary_day("2026-11-10", "h1b", {"note": "eins geaendert", "entries": {}, "definitions": {}})
check("a second upsert replaces the row (hash and payload)", mcp_sql.get_diary_hashes()["2026-11-10"] == "h1b"
      and mcp_sql.get_diary_range("2026-11-10", "2026-11-10")["diary"]["days"][0]["note"] == "eins geaendert")

mcp_sql.upsert_snapshot("diary_fields", {"state": "ok", "fields": [{"key": "U0001", "name": "Tablette"}]}, "2026-11-19T10:00:00")
rng = mcp_sql.get_diary_range("2026-11-01", "2026-11-30")
check("the range read: days in date order with note, entries, definitions", [d["date"] for d in rng["diary"]["days"]] == ["2026-11-10", "2026-11-12"]
      and rng["diary"]["days"][1]["entries"] == {"U0001": [{"values": {"Anzahl": 2}}]} and rng["diary"]["days"][1]["definitions"]["U0001"]["name"] == "Tablette")
check("the range read: the field list of the last sync and a _meta block", rng["diary"]["fields"] == [{"key": "U0001", "name": "Tablette"}] and "_meta" in rng)
check("the range read: a range without a day is empty", mcp_sql.get_diary_range("2025-01-01", "2025-01-31")["diary"]["days"] == [])
check("the range read: the bounds are inclusive and days outside are left out",
      [d["date"] for d in mcp_sql.get_diary_range("2026-11-12", "2026-11-12")["diary"]["days"]] == ["2026-11-12"])
mcp_sql.get_connection().execute("DELETE FROM mcp_snapshots WHERE kind = 'diary_fields'")
check("the range read: no field list yet gives an empty list", mcp_sql.get_diary_range("2026-11-01", "2026-11-30")["diary"]["fields"] == [])

# clear_all: every table, the tables stay, no text left in the files
mcp_sql.upsert_diary_day("2026-11-15", "h3", {"note": SECRET, "entries": {}, "definitions": {}})
mcp_sql.upsert_health_day("2026-03-01", {"hrv": 50}, "x")
mcp_sql.upsert_snapshot("stats", {"a": 1}, "2026-11-19T10:00:00")
mcp_sql.upsert_raw_day_hash("2026-03-01", "rawhash")
db_path = Path(mcp_sql.DB_PATH)
wal_path = Path(str(db_path) + "-wal")


def file_bytes():
    out = b""
    for p in (db_path, wal_path):
        if p.is_file():
            out += p.read_bytes()
    return out


check("(setup) the secret text is in the cache files before the reset", SECRET.encode("utf-8") in file_bytes())
mcp_sql.clear_all()
conn = mcp_sql.get_connection()
counts = {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in sorted(t for t in tables if t.startswith("mcp_"))}
check("clear_all empties every table of the cache", all(n == 0 for n in counts.values()))
check("clear_all leaves the tables themselves", {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()} >= tables)
check("clear_all leaves no text of the diary in the database file or its write-ahead log", SECRET.encode("utf-8") not in file_bytes())
check("the cache works after clear_all (a row can be written again)",
      (mcp_sql.upsert_diary_day("2026-11-10", "x", {"note": "n", "entries": {}, "definitions": {}}), mcp_sql.get_diary_hashes())[1] == {"2026-11-10": "x"})
mcp_sql.clear_all()

# ══════════════════════════════════════════════════════════════════════════════
section("2. gateway_map — the internal kind exists only with the MCP switch")
# ══════════════════════════════════════════════════════════════════════════════

assert wr.create_user_field(_TMPDIR, "Schmerztablette", PILL, True)["status"] == "written"
pill = [{"time": "07:15", "values": {"Anzahl": 2}}]
assert wr.save_day(_TMPDIR, "2026-11-10", "Tag eins", {"U0001": pill}, now=at("2026-11-10"))["status"] == "written"
assert wr.save_day(_TMPDIR, "2026-11-11", "", {"U0001": pill}, now=at("2026-11-11"))["status"] == "written"
assert wr.save_day(_TMPDIR, "2026-11-12", "Tag drei", {}, now=at("2026-11-12"))["status"] == "written"

set_switch(mcp=False, export=False)
check("switch off: the kind is not listed", "diary_cache_feed" not in gateway_map.list_metadata_kinds()
      and "diary_cache_feed" not in gateway_map.list_metadata_kinds(include_internal=False))
try:
    gateway_map.get_metadata("diary_cache_feed")
    off_raises = False
except ValueError:
    off_raises = True
check("switch off: get_metadata answers the kind like an unknown one (ValueError)", off_raises)
try:
    mcp_map.get_archive_metadata("diary_cache_feed")
    mcp_off_raises = False
except ValueError:
    mcp_off_raises = True
check("switch off: mcp_map.get_archive_metadata raises too", mcp_off_raises)

set_switch(mcp=False, export=True)
check("only the export switch on: the kind is still off (the export switch needs the MCP switch)",
      "diary_cache_feed" not in gateway_map.list_metadata_kinds())

set_switch(mcp=True, export=False)
check("switch on: the kind is listed, as an internal kind only", "diary_cache_feed" in gateway_map.list_metadata_kinds()
      and "diary_cache_feed" not in gateway_map.list_metadata_kinds(include_internal=False))
res = mcp_map.get_archive_metadata("diary_cache_feed")
check("switch on: the answer carries the feed of the diary of BASE_DIR", res["error"] is None and sorted(res["data"]["days"]) == ["2026-11-10", "2026-11-11", "2026-11-12"])
check("switch on: no history in the feed", "history" not in json.dumps(res["data"]))
with patch("maps.diary_map.get_cache_feed", side_effect=RuntimeError("kaputt")):
    bad = gateway_map.get_metadata("diary_cache_feed")
check("a failing feed is an error envelope, not an exception", bad["data"] is None and "kaputt" in bad["error"] and "RuntimeError" in bad["error"])
check("the other kinds are unchanged (stats is still there, the order of the list is the one of the registry)",
      "stats" in gateway_map.list_metadata_kinds() and gateway_map.list_metadata_kinds()[0] == "stats")

# ══════════════════════════════════════════════════════════════════════════════
section("3. mcp_update — the two diary steps")
# ══════════════════════════════════════════════════════════════════════════════

mcp_sql.init_db()
mcp_sql.clear_all()
set_switch(mcp=False, export=False)
put_sentinel()

# a. switch off, nothing noted: nothing happens, only the state is noted
with patch("maps.mcp_map.get_archive_metadata", side_effect=AssertionError("must not read the diary")):
    feed, info = mcp_update._diary_begin()
check("off, first pass: no feed, no rebuild, no error", feed is None and info == {"enabled": False, "rebuild": False, "error": None})
check("off: the state 'off' is noted", mcp_sql.get_snapshot("diary_optin") == {"enabled": False})
check("off: the other cache rows are untouched", health_rows() == 1 and mcp_sql.get_diary_hashes() == {})
check("off: the apply step does nothing", mcp_update._diary_apply(None) == (0, 0, 0))

# b. switch on: the whole cache is rebuilt
set_switch(mcp=True, export=False)
feed, info = mcp_update._diary_begin()
check("switched on: the whole cache is emptied first (the other rows are gone too)", info["rebuild"] is True and health_rows() == 0)
check("switched on: the feed is returned and the state 'on' is noted", sorted(feed["days"]) == ["2026-11-10", "2026-11-11", "2026-11-12"]
      and mcp_sql.get_snapshot("diary_optin") == {"enabled": True} and info["error"] is None and info["enabled"] is True)

# c. apply: the days go into the cache
check("apply: three days are put into the cache", mcp_update._diary_apply(feed) == (3, 0, 0))
check("apply: the hashes are those of the day files", set(mcp_sql.get_diary_hashes()) == {"2026-11-10", "2026-11-11", "2026-11-12"}
      and mcp_sql.get_diary_hashes()["2026-11-10"] == feed["days"]["2026-11-10"]["hash"])
check("apply: the field list is stored", mcp_sql.get_snapshot("diary_fields") == feed["fields"])
check("apply: the cache reads back the note and the entry of a day",
      mcp_sql.get_diary_range("2026-11-10", "2026-11-10")["diary"]["days"][0]["note"] == "Tag eins"
      and mcp_sql.get_diary_range("2026-11-10", "2026-11-10")["diary"]["days"][0]["entries"] == {"U0001": pill})

# d. nothing changed: nothing happens
feed, info = mcp_update._diary_begin()
check("unchanged: no rebuild", info["rebuild"] is False and info["error"] is None)
with patch("mcp_sql.upsert_snapshot") as snap, patch("mcp_sql.upsert_diary_day") as ud:
    again = mcp_update._diary_apply(feed)
check("unchanged: nothing is written (no row, no field list)", again == (0, 0, 0) and ud.call_count == 0 and snap.call_count == 0)

# e. a changed day replaces its row; text taken out is gone from the cache
assert wr.save_day(_TMPDIR, "2026-11-10", "Tag eins mit ganz anderem Text", {"U0001": pill}, now=at("2026-11-10"))["status"] == "written"
mcp_sql.upsert_health_day("2026-03-01", {"hrv": 50}, "x")
feed, info = mcp_update._diary_begin()
check("a changed day is no removal: no rebuild, the other rows stay", info["rebuild"] is False and health_rows() == 1)
check("a changed day: exactly its row is replaced", mcp_update._diary_apply(feed) == (1, 0, 0))
check("a changed day: the old text is gone from the cache, the new one is there",
      mcp_sql.get_diary_range("2026-11-10", "2026-11-10")["diary"]["days"][0]["note"] == "Tag eins mit ganz anderem Text")
assert wr.save_day(_TMPDIR, "2026-11-10", "Tag eins mit ganz anderem Text", {}, now=at("2026-11-10"))["status"] == "written"
feed, info = mcp_update._diary_begin()
mcp_update._diary_apply(feed)
check("entries taken out of a day are gone from the cache with the replaced row",
      mcp_sql.get_diary_range("2026-11-10", "2026-11-10")["diary"]["days"][0]["entries"] == {})

# f. a new day is added, no rebuild
assert wr.save_day(_TMPDIR, "2026-11-13", "Tag vier", {}, now=at("2026-11-13"))["status"] == "written"
feed, info = mcp_update._diary_begin()
check("a new day: no rebuild", info["rebuild"] is False and health_rows() == 1)
check("a new day: one row is added", mcp_update._diary_apply(feed) == (1, 0, 0) and len(mcp_sql.get_diary_hashes()) == 4)

# g. the export switch changes nothing in the cache
set_switch(export=True)
feed, info = mcp_update._diary_begin()
check("the export switch on: no rebuild", info["rebuild"] is False and info["enabled"] is True)
set_switch(export=False)
feed, info = mcp_update._diary_begin()
check("the export switch off again: no rebuild", info["rebuild"] is False)

# h. a day file is gone: removal -> the whole cache is rebuilt
day_file("2026-11-11").unlink()
feed, info = mcp_update._diary_begin()
check("a deleted day: the whole cache is rebuilt (the other rows are gone too)", info["rebuild"] is True and health_rows() == 0)
mcp_update._diary_apply(feed)
check("a deleted day: after the pass it is not in the cache, the others are",
      sorted(mcp_sql.get_diary_hashes()) == ["2026-11-10", "2026-11-12", "2026-11-13"])
feed, info = mcp_update._diary_begin()
check("after the rebuild the next pass changes nothing", info["rebuild"] is False and mcp_update._diary_apply(feed) == (0, 0, 0))

# i. a cached day that is damaged now counts as a removal (decision A13)
put_sentinel()
day_file("2026-11-12").write_text("{not json", encoding="utf-8")
feed, info = mcp_update._diary_begin()
check("a cached day that became damaged: the whole cache is rebuilt", info["rebuild"] is True and health_rows() == 0)
check("... and the damaged day is counted, not cached", mcp_update._diary_apply(feed) == (2, 0, 1)
      and sorted(mcp_sql.get_diary_hashes()) == ["2026-11-10", "2026-11-13"])
# j. a damaged day that was never cached: counted on every pass, no rebuild
feed, info = mcp_update._diary_begin()
check("a damaged day that is not in the cache: no rebuild, counted again", info["rebuild"] is False and mcp_update._diary_apply(feed) == (0, 0, 1))
# a day of a newer version, new
day_file("2026-11-14").write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
feed, info = mcp_update._diary_begin()
check("a day of a newer version: counted, not cached, no rebuild", info["rebuild"] is False and mcp_update._diary_apply(feed) == (0, 0, 2))

# k. switched off: the whole cache is rebuilt without the diary
put_sentinel()
set_switch(mcp=False, export=False)
with patch("maps.mcp_map.get_archive_metadata", side_effect=AssertionError("must not read the diary")):
    feed, info = mcp_update._diary_begin()
check("switched off: no feed, rebuild, the diary is out of the cache and so are the other rows",
      feed is None and info["rebuild"] is True and info["enabled"] is False and mcp_sql.get_diary_hashes() == {} and health_rows() == 0)
check("switched off: the state 'off' is noted", mcp_sql.get_snapshot("diary_optin") == {"enabled": False})
check("switched off: a range read finds no diary", mcp_sql.get_diary_range("2026-01-01", "2026-12-31")["diary"]["days"] == [])
feed, info = mcp_update._diary_begin()
check("off again: nothing happens", feed is None and info["rebuild"] is False)

# l. errors: the cache is left as it is, the state is not noted, the error is reported
put_sentinel()
set_switch(mcp=True)
with patch("maps.mcp_map.get_archive_metadata", return_value={"data": None, "error": "boom"}):
    feed, info = mcp_update._diary_begin()
check("a feed that cannot be read: no feed, an error that says why, nothing cleared, the state not noted",
      feed is None and "boom" in info["error"] and info["rebuild"] is False and health_rows() == 1
      and mcp_sql.get_snapshot("diary_optin") == {"enabled": False})
with patch("mcp_sql.clear_all", side_effect=OSError("locked")):
    feed, info = mcp_update._diary_begin()
check("a cache that cannot be emptied: an error, the state is not noted, so the next pass tries again",
      feed is None and "locked" in info["error"] and info["rebuild"] is False and mcp_sql.get_snapshot("diary_optin") == {"enabled": False})
feed, info = mcp_update._diary_begin()
check("the next pass then does the rebuild", info["rebuild"] is True and info["error"] is None and health_rows() == 0)

# m. a failing row is counted, the rest goes on
real_upsert = mcp_sql.upsert_diary_day


def flaky(day, hash_value, payload):
    if day == "2026-11-10":
        raise OSError("disk full")
    return real_upsert(day, hash_value, payload)


mcp_sql.clear_all()
with patch("mcp_sql.upsert_diary_day", side_effect=flaky):
    counts = mcp_update._diary_apply(feed)
check("a failing row is counted in days_failed and the other days are stored", counts[1] == 1 and counts[0] == 1
      and "2026-11-10" not in mcp_sql.get_diary_hashes() and "2026-11-13" in mcp_sql.get_diary_hashes())
with patch("mcp_sql.get_diary_hashes", side_effect=OSError("locked")):
    check("a cache that cannot be read in the apply step: failed 1, nothing raised", mcp_update._diary_apply(feed) == (0, 1, 0))

# ══════════════════════════════════════════════════════════════════════════════
section("4. sync_all — order and result keys")
# ══════════════════════════════════════════════════════════════════════════════

order = []


def step(name, ret):
    def _f(*a, **k):
        order.append(name)
        return ret
    return _f


def run_sync(diary_begin=(None, {"enabled": False, "rebuild": False, "error": None}), diary_apply=(0, 0, 0)):
    del order[:]
    with patch.multiple(mcp_update,
                        _start_update_log=step("log", None),
                        _diary_begin=step("diary_begin", diary_begin),
                        _diary_apply=step("diary_apply", diary_apply),
                        _apply_pending_context_resync=step("context_resync", []),
                        _reconcile_field_registry=step("field_registry", {}),
                        _reconcile_summary_schema=step("summary_schema", False),
                        _sync_health_days=step("health_days", (0, 0)),
                        _sync_health_baselines=step("baselines", (0, 0)),
                        _sync_context_days=step("context_days", (0, 0)),
                        _sync_raw_fields=step("raw_fields", (0, 0)),
                        _sync_structured_log=step("structured_log", (0, 0)),
                        _sync_recent_log_files=step("recent_logs", (0, 0))), \
         patch("mcp_sql.init_db"), patch("mcp_sql.upsert_snapshot"), \
         patch("maps.mcp_map.get_archive_metadata", return_value={"data": None, "error": None}):
        return mcp_update.sync_all()


res = run_sync()
check("sync_all: the first diary step comes before every other step (a rebuild empties the whole cache)",
      order.index("diary_begin") < order.index("context_resync") < order.index("health_days"))
check("sync_all: the second diary step comes after the raw fields and before the logs",
      order.index("raw_fields") < order.index("diary_apply") < order.index("structured_log"))
check("sync_all: the result carries the six diary keys, all quiet when the switch is off",
      (res["diary_enabled"], res["diary_rebuild"], res["diary_days_updated"], res["diary_days_failed"],
       res["diary_days_unreadable"], res["diary_error"]) == (False, False, 0, 0, 0, None))
res = run_sync(({"days": {}, "fields": {}}, {"enabled": True, "rebuild": True, "error": None}), (4, 1, 2))
check("sync_all: the result reports a rebuild and the counts of the diary pass",
      res["diary_enabled"] is True and res["diary_rebuild"] is True and (res["diary_days_updated"], res["diary_days_failed"],
                                                                         res["diary_days_unreadable"]) == (4, 1, 2))
res = run_sync((None, {"enabled": True, "rebuild": False, "error": "RuntimeError: boom"}))
check("sync_all: an error of the diary step is in the result and does not stop the pass",
      res["diary_error"] == "RuntimeError: boom" and "health_days" in order and "recent_logs" in order)

# the real chain once: the switch on, sync_all against the real cache with every other step stubbed
set_switch(mcp=True, export=False)
mcp_sql.clear_all()
mcp_update._diary_begin()           # notes 'on' (the cache holds no diary day yet)
with patch.multiple(mcp_update,
                    _start_update_log=step("log", None), _apply_pending_context_resync=step("x", []),
                    _reconcile_field_registry=step("x", {}), _reconcile_summary_schema=step("x", False),
                    _sync_health_days=step("x", (0, 0)), _sync_health_baselines=step("x", (0, 0)),
                    _sync_context_days=step("x", (0, 0)), _sync_raw_fields=step("x", (0, 0)),
                    _sync_structured_log=step("x", (0, 0)), _sync_recent_log_files=step("x", (0, 0))):
    real = mcp_update.sync_all()
check("sync_all on the real cache: the diary days are in it (the switch was noted as on before, so no rebuild)",
      real["diary_rebuild"] is False and real["diary_error"] is None and real["diary_days_updated"] == len(mcp_sql.get_diary_hashes()) and real["diary_days_updated"] >= 2)

# ══════════════════════════════════════════════════════════════════════════════
section("5. Export — the diary domain, the JSON adapter only, the switch")
# ══════════════════════════════════════════════════════════════════════════════

sys.path.insert(0, str(_ROOT / "exports"))
import export_common  # noqa: E402
import export_runner  # noqa: E402
from types import SimpleNamespace  # noqa: E402

check("the diary has a reader of its own in export_common", export_common._DOMAIN_RANGE_READERS.get("diary") is mcp_sql.get_diary_range)

# a filled cache with the switch on
set_switch(mcp=True, export=True)
mcp_sql.clear_all()
feed, info = mcp_update._diary_begin()
mcp_update._diary_apply(feed)
cached_days = sorted(mcp_sql.get_diary_hashes())
check("(setup) the cache holds the readable diary days (the deleted, damaged and newer-version ones are not in it)",
      cached_days == ["2026-11-10", "2026-11-13"])

set_switch(mcp=True, export=False)
res = export_common.collect("2026-11-01", "2026-11-30", ["health", "diary"])
check("export switch off: the diary domain is left out, no entry and no error; health is untouched",
      "diary" not in res["domains"] and "health" in res["domains"])
set_switch(mcp=False, export=True)
check("MCP switch off (export switch on): the diary domain is left out too",
      "diary" not in export_common.collect("2026-11-01", "2026-11-30", ["diary"])["domains"])

set_switch(mcp=True, export=True)
res = export_common.collect("2026-11-01", "2026-11-30", ["diary"])
diary = res["domains"]["diary"]
check("both switches on: the diary domain has the field list and the days of the cache",
      sorted(d["date"] for d in diary["days"]) == cached_days and isinstance(diary["fields"], list))
check("both switches on: a day carries note, entries and definitions, never a history",
      all({"date", "note", "entries", "definitions"} <= set(d) for d in diary["days"]) and "history" not in json.dumps(diary))
narrow = export_common.collect(cached_days[1], cached_days[1], ["diary"])["domains"]["diary"]
check("the range of the diary is widened to the first and last cached day (a note outside the Garmin range is exported too)",
      sorted(d["date"] for d in narrow["days"]) == cached_days)
check("an empty domain list still works", export_common.collect("2026-11-01", "2026-11-30", [])["domains"] == {})

# adapters: only JSON declares the diary
adapters = {a["id"]: a for a in export_runner.scan()}
check("scan(): the JSON adapter can write the diary, CSV and InfluxDB cannot",
      adapters["json_adapter"]["diary"] is True and adapters["csv_adapter"]["diary"] is False
      and adapters["influxdb_adapter"]["diary"] is False)

out_dir = _TMPDIR / "export_out"
set_switch(mcp=True, export=True)
r = adapters["json_adapter"]["module"].build("2026-11-01", "2026-11-30", ["diary"], False, out_dir)
written = json.loads((out_dir / "export.json").read_text(encoding="utf-8"))
check("the JSON adapter writes the diary into the file",
      r["success"] and sorted(d["date"] for d in written["domains"]["diary"]["days"]) == cached_days
      and any(d["note"] for d in written["domains"]["diary"]["days"]))
set_switch(mcp=True, export=False)
adapters["json_adapter"]["module"].build("2026-11-01", "2026-11-30", ["diary"], False, out_dir)
check("the same call with the export switch off writes no diary", "diary" not in json.loads((out_dir / "export.json").read_text(encoding="utf-8"))["domains"])

# the runner: the diary is left out with a line in the log, never an error
calls = []


def fake_adapter(name, diary):
    meta = {"name": name, "extension": ".x"}
    if diary:
        meta["diary"] = True

    def build(date_from, date_to, domains, include_metadata, output_dir, **options):
        calls.append((name, list(domains)))
        return {"name": name, "success": True, "file": Path(name)}
    return SimpleNamespace(META=meta, build=build, __name__=name)


def run_export(selections):
    del calls[:]
    lines = []
    with patch("mcp_update.sync_all", return_value={"duration_seconds": 0.0}):
        results = export_runner.build(selections, "2026-11-01", "2026-11-30", _TMPDIR / "x", log=lines.append)
    return results, lines


set_switch(mcp=True, export=True)
results, lines = run_export([(fake_adapter("JSONLIKE", True), ["health", "diary"], False, {}),
                             (fake_adapter("CSVLIKE", False), ["health", "diary"], False, {})])
check("runner, switch on: an adapter that can write it gets the diary, one that cannot does not (said in the log)",
      calls == [("JSONLIKE", ["health", "diary"]), ("CSVLIKE", ["health"])] and any("CSVLIKE" in line and "JSON only" in line for line in lines))
check("runner: leaving the diary out is no error of the export", all(r["success"] for r in results))
set_switch(mcp=True, export=False)
results, lines = run_export([(fake_adapter("JSONLIKE", True), ["health", "diary"], False, {})])
check("runner, switch off: a saved selection with the diary runs without it (said in the log, no error)",
      calls == [("JSONLIKE", ["health"])] and any("is off" in line for line in lines) and all(r["success"] for r in results))
results, lines = run_export([(fake_adapter("JSONLIKE", True), ["health"], False, {})])
check("runner: a selection without the diary says nothing about it", not any("Diary" in line for line in lines))

# ══════════════════════════════════════════════════════════════════════════════
section("6. The built MCP server — the package diary is registered next to maps")
# ══════════════════════════════════════════════════════════════════════════════

import types as _types  # noqa: E402
import mcp_server  # noqa: E402

frozen_root = _TMPDIR / "frozen_root"
for sub in ("scripts/maps", "scripts/diary", "scripts/garmin", "scripts/clients"):
    (frozen_root / sub).mkdir(parents=True, exist_ok=True)
saved_modules = {k: sys.modules.pop(k) for k in ("maps", "diary") if k in sys.modules}
saved_path = list(sys.path)
try:
    with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(frozen_root), create=True):
        mcp_server._register_embedded_packages()
    diary_pkg = sys.modules.get("diary")
    maps_pkg = sys.modules.get("maps")
    check("frozen: the package diary is registered with the path of scripts/diary",
          isinstance(diary_pkg, _types.ModuleType) and diary_pkg.__path__ == [str(frozen_root / "scripts" / "diary")]
          and diary_pkg.__package__ == "diary")
    check("frozen: maps is registered as before", isinstance(maps_pkg, _types.ModuleType)
          and maps_pkg.__path__ == [str(frozen_root / "scripts" / "maps")])
    sys.modules.pop("diary", None)
    sys.modules.pop("maps", None)
    shutil_dir = frozen_root / "scripts" / "diary"
    shutil_dir.rmdir()
    with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(frozen_root), create=True):
        mcp_server._register_embedded_packages()
    check("frozen without a diary folder in the build: nothing is registered for it (no error)", "diary" not in sys.modules)
finally:
    sys.modules.pop("diary", None)
    sys.modules.pop("maps", None)
    sys.modules.update(saved_modules)
    sys.path[:] = saved_path
check("not frozen: the call changes nothing", (lambda before: (mcp_server._register_embedded_packages(), set(sys.modules) == before)[1])(set(sys.modules)))

# ══════════════════════════════════════════════════════════════════════════════
section("7. The diary tools (list_diary_fields, query_diary, search_diary_notes)")
# ══════════════════════════════════════════════════════════════════════════════

import asyncio  # noqa: E402
import importlib  # noqa: E402
import mcp_diary  # noqa: E402
from diary import diary_reader as rd  # noqa: E402

# a diary for the tools: five fields, days with entries and notes (all days of December, away from the days above)
assert wr.create_user_field(_TMPDIR, "Spazieren gegangen", [{"label": "Ja/Nein", "type": "yesno"}], False)["status"] == "written"
assert wr.create_user_field(_TMPDIR, "Magnesiumtablette", [{"label": "Menge", "type": "number", "unit": "mg"}], True)["status"] == "written"
assert wr.activate_catalog_field(_TMPDIR, "G001")["status"] == "written"
SECRET2 = "GEHEIMWORT-fruehere-Fassung"
D = {"d1": "2026-12-01", "d2": "2026-12-02", "d3": "2026-12-03", "d4": "2026-12-04", "d5": "2026-12-05"}
assert wr.save_day(_TMPDIR, D["d1"], "TESTWORT Kopfweh am Morgen", {"U0001": [{"time": "21:30", "values": {"Anzahl": 1}}, {"time": "07:15", "values": {"Anzahl": 2}}]}, now=at(D["d1"]))["status"] == "written"
assert wr.save_day(_TMPDIR, D["d2"], "", {"U0002": [{"values": {"Ja/Nein": True}}]}, now=at(D["d2"]))["status"] == "written"
assert wr.save_day(_TMPDIR, D["d3"], "", {"G001": [{"time": "08:00", "values": {"systolic": 128, "diastolic": 82, "Pulse": 61}}]}, now=at(D["d3"]))["status"] == "written"
assert wr.save_day(_TMPDIR, D["d4"], "Nur eine Notiz zum Wetter", {}, now=at(D["d4"]))["status"] == "written"
assert wr.save_day(_TMPDIR, D["d5"], "Kopfweh wieder", {"U0001": [{"time": "07:00", "values": {"Anzahl": 3}}]}, now=at(D["d5"]))["status"] == "written"
assert wr.save_day(_TMPDIR, "2026-12-06", SECRET2, {}, now=at("2026-12-06"))["status"] == "written"
assert wr.save_day(_TMPDIR, "2026-12-06", "neuer Text ohne das alte Wort", {}, now=at("2026-12-20"), keep_history=True)["status"] == "written"

set_switch(mcp=True, export=False)
mcp_sql.clear_all()
feed, info = mcp_update._diary_begin()
mcp_update._diary_apply(feed)
check("(setup) the cache holds the December days", all(d in mcp_sql.get_diary_hashes() for d in list(D.values()) + ["2026-12-06"]))

# switch off: nothing is served
set_switch(mcp=False, export=False)
offs = [mcp_diary.list_diary_fields(), mcp_diary.query_diary(D["d1"], D["d5"]), mcp_diary.search_diary_notes("Kopfweh")]
check("switch off: all three tools answer 'switched off' and hand out nothing",
      all(set(o) == {"error"} and "switched off" in o["error"] for o in offs))
set_switch(mcp=True, export=False)

# list_diary_fields
listed = mcp_diary.list_diary_fields()["diary"]
by_key = {f["key"]: f for f in listed["fields"]}
check("list_diary_fields: every field with key, name, time flag, archived flag, values with unit",
      set(by_key) == {"U0001", "U0002", "U0003", "G001"} and by_key["U0001"]["name"] == "Schmerztablette" and by_key["U0001"]["with_time"] is True
      and by_key["U0001"]["values"] == [{"label": "Anzahl", "type": "number", "unit": "Stück"}]
      and by_key["U0002"]["values"] == [{"label": "Ja/Nein", "type": "yesno", "unit": None}] and by_key["U0002"]["archived"] is False)
check("list_diary_fields: the Garmin counterpart is named where there is one", by_key["G001"]["maps_to"] == "get_blood_pressure"
      and by_key["U0001"]["maps_to"] is None)
check("list_diary_fields: span and count of the days with content", listed["first_day"] == "2026-11-10" and listed["last_day"] == "2026-12-06"
      and listed["days_with_content"] == len(mcp_sql.get_diary_hashes()))
check("list_diary_fields: the answer says it is typed by hand and not merged", "by hand" in mcp_diary.list_diary_fields()["_meta"]["note"]
      and "not merged" in mcp_diary.list_diary_fields()["_meta"]["note"])

# query_diary
q = mcp_diary.query_diary(D["d1"], D["d5"])
rows = q["diary"]["entries"]
check("query_diary: entries in date and time order, each with date, time, field, key and values with units",
      [(r["date"], r["time"], r["field"]) for r in rows] ==
      [(D["d1"], "07:15", "Schmerztablette"), (D["d1"], "21:30", "Schmerztablette"), (D["d2"], None, "Spazieren gegangen"),
       (D["d3"], "08:00", "Blood pressure"), (D["d5"], "07:00", "Schmerztablette")])
check("query_diary: the values are as typed, with their units",
      rows[0]["values"] == [{"label": "Anzahl", "value": 2, "unit": "Stück"}]
      and rows[2]["values"] == [{"label": "Ja/Nein", "value": True, "unit": None}]
      and [v["label"] for v in rows[3]["values"]] == ["systolic", "diastolic", "Pulse"] and rows[3]["values"][0]["unit"] == "mmHg")
check("query_diary: no notes unless asked; _meta has the source note, the days with content and the weekday block of the range",
      "notes" not in q["diary"] and q["_meta"]["source"] == "diary" and "by hand" in q["_meta"]["note"]
      and q["_meta"]["days_with_content"] == 5 and q["_meta"]["weekdays"][D["d1"]] == "Tuesday"
      and q["_meta"]["date_from_iso"] == D["d1"] and q["_meta"]["date_to_iso"] == D["d5"])
qn = mcp_diary.query_diary(D["d1"], D["d5"], include_notes=True)["diary"]["notes"]
check("query_diary: include_notes gives the note of each day with its date", qn == [
    {"date": D["d1"], "note": "TESTWORT Kopfweh am Morgen"}, {"date": D["d4"], "note": "Nur eine Notiz zum Wetter"},
    {"date": D["d5"], "note": "Kopfweh wieder"}])
only = mcp_diary.query_diary(D["d1"], D["d5"], field="U0002")
check("query_diary: a field by key gives only its entries", [r["field"] for r in only["diary"]["entries"]] == ["Spazieren gegangen"]
      and "field_resolved_from" not in only["_meta"] and only["_meta"]["field_used"] == "Spazieren gegangen")
exact = mcp_diary.query_diary(D["d1"], D["d5"], field="schmerztablette")
check("query_diary: a name in another case is resolved and the substitution is marked",
      len(exact["diary"]["entries"]) == 3 and exact["_meta"]["field_resolved_from"] == "schmerztablette")
check("query_diary: the exact name is no substitution", "field_resolved_from" not in mcp_diary.query_diary(D["d1"], D["d5"], field="Schmerztablette")["_meta"])
part = mcp_diary.query_diary(D["d1"], D["d5"], field="schmerz")
check("query_diary: a part of a name that is in exactly one name is resolved (marked)",
      part["_meta"]["field_used"] == "Schmerztablette" and part["_meta"]["field_resolved_from"] == "schmerz")
amb = mcp_diary.query_diary(D["d1"], D["d5"], field="tablette")
check("query_diary: a part that is in two names is an error with both as did_you_mean",
      "several diary fields" in amb["error"] and amb["did_you_mean"] == ["Magnesiumtablette", "Schmerztablette"])
typo = mcp_diary.query_diary(D["d1"], D["d5"], field="Spazieren gegange")
check("query_diary: a near-match (one hit) is resolved by the shared step and marked",
      typo["_meta"]["field_used"] == "Spazieren gegangen" and typo["_meta"]["field_resolved_from"] == "Spazieren gegange")
unk = mcp_diary.query_diary(D["d1"], D["d5"], field="Alkohol")
check("query_diary: an unknown name is an error with the list of the fields that exist", "unknown diary field" in unk["error"]
      and unk["available_fields"] == ["Blood pressure", "Magnesiumtablette", "Schmerztablette", "Spazieren gegangen"])
garmin = mcp_diary.query_diary(D["d1"], D["d5"], field="resting_heart_rate")
check("query_diary: a Garmin field name gets a pointer to query_health", "query_health" in garmin["error"] and "Garmin" in garmin["error"])
with patch.object(mcp_diary, "resolve_health_field", return_value={"error": "unknown field 'x'"}), \
     patch.object(mcp_diary, "resolve_context_field", return_value={"resolved_field": "temperature_max"}):
    check("query_diary: a Garmin context field name gets a pointer to query_context",
          "query_context" in mcp_diary.query_diary(D["d1"], D["d5"], field="Alkohol2")["error"])
with patch.object(mcp_diary, "resolve_health_field", return_value={"error": "field 'steps' is ambiguous between a daily value and a time series -- please specify one of: a, b", "did_you_mean": ["a", "b"]}):
    check("query_diary: an ambiguous Garmin name is a pointer too (with their error text)",
          "query_health" in mcp_diary.query_diary(D["d1"], D["d5"], field="steps")["error"])
check("query_diary: an empty field name is refused", "error" in mcp_diary.query_diary(D["d1"], D["d5"], field="  "))
check("query_diary: bad dates", "real dates" in mcp_diary.query_diary("2026-13-01", D["d5"])["error"]
      and "real dates" in mcp_diary.query_diary(D["d1"], "morgen")["error"] and "real dates" in mcp_diary.query_diary(None, D["d5"])["error"])
check("query_diary: dates turned around", "after" in mcp_diary.query_diary(D["d5"], D["d1"])["error"])
check("query_diary: 366 days are fine, 367 are refused with a clear error (no cutting)",
      "error" not in mcp_diary.query_diary("2025-12-31", "2026-12-31")
      and "range too large" in mcp_diary.query_diary("2025-12-30", "2026-12-31")["error"])
empty = mcp_diary.query_diary("2025-01-01", "2025-01-31")
check("query_diary: an empty range is no error: no entries and a note saying so",
      "error" not in empty and empty["diary"]["entries"] == [] and "no diary entries" in empty["_meta"]["empty"])
everything = json.dumps([mcp_diary.list_diary_fields(), mcp_diary.query_diary("2026-01-01", "2026-12-31", include_notes=True),
                         mcp_diary.search_diary_notes("text")], ensure_ascii=False)
check("no tool hands out the earlier text of a day with a history", SECRET2 not in everything and "history" not in everything.lower()
      and "neuer Text ohne das alte Wort" in everything)

# search_diary_notes
hit = mcp_diary.search_diary_notes("kopfweh")["diary"]
check("search: case-insensitive, newest day first, date and snippet", [h["date"] for h in hit["hits"]] == [D["d5"], D["d1"]]
      and "Kopfweh" in hit["hits"][0]["snippet"] and hit["truncated"] is False)
check("search: every word has to be in the note", [h["date"] for h in mcp_diary.search_diary_notes("kopfweh morgen")["diary"]["hits"]] == [D["d1"]])
check("search: a query that is too short or too long is refused with a reason",
      "too short" in mcp_diary.search_diary_notes("a")["error"] and "too long" in mcp_diary.search_diary_notes("x" * 201)["error"]
      and "error" in mcp_diary.search_diary_notes(None))
one = mcp_diary.search_diary_notes("kopfweh", limit=1)["diary"]
check("search: the limit cuts the hits and says so", len(one["hits"]) == 1 and one["truncated"] is True and one["hits"][0]["date"] == D["d5"])
check("search: a limit that is not a positive number falls back to 50, a huge one is held to 200",
      len(mcp_diary.search_diary_notes("kopfweh", limit=0)["diary"]["hits"]) == 2 and len(mcp_diary.search_diary_notes("kopfweh", limit=True)["diary"]["hits"]) == 2
      and len(mcp_diary.search_diary_notes("kopfweh", limit=10**6)["diary"]["hits"]) == 2)
check("search: nothing found is an empty list, not an error", mcp_diary.search_diary_notes("gibtesnicht")["diary"]["hits"] == [])
fresh = [(h["date"], h["snippet"]) for h in rd.search_notes(_TMPDIR, "kopfweh")["hits"]]
cached = [(h["date"], h["snippet"]) for h in mcp_diary.search_diary_notes("kopfweh", limit=200)["diary"]["hits"]]
check("search: the tool finds exactly what the search of the Diary tab finds (same rules, same snippets)", fresh == cached and len(fresh) == 2)
check("search: the entries of the diary are not searched", mcp_diary.search_diary_notes("Magnesium")["diary"]["hits"] == [])

# ── mutation round v1.7.8.1: the gaps that the Cosmic Ray run found in clients/mcp_diary.py ────────────────────
# finding a field (crafted field lists: keys and names that sort before and after what is typed)
FIELDS = [{"key": "U1", "name": "walk"}, {"key": "k9", "name": "Spazieren gegangen"},
          {"key": "U3", "name": "Schmerztablette"}, {"key": "U5", "name": "Schmerztabletta"},
          {"key": "U4", "name": "Magnesiumtablette"}]
match = mcp_diary._match_diary_field
check("match: a key in another case is a substitution, the key as stored is none (keys of both cases)",
      match("u1", FIELDS)[2] is True and match("U1", FIELDS)[2] is False and match("K9", FIELDS)[2] is True and match("k9", FIELDS)[2] is False)
check("match: a name in another case is a substitution, the name as stored is none (typed before and after the name)",
      match("WALK", FIELDS)[2] is True and match("Walk", FIELDS)[2] is True and match("walk", FIELDS)[2] is False
      and match("spazieren gegangen", FIELDS)[2] is True and match("Spazieren gegangen", FIELDS)[2] is False)
check("match: a part of a name of three letters is found, one of two letters is not looked for in the names",
      match("gan", FIELDS)[:2] == ("resolved", FIELDS[1]) and match("ga", FIELDS) == ("unknown", []))
check("match: a part that is in several names is ambiguous (sorted), in one name it is resolved and marked",
      match("tablette", FIELDS) == ("ambiguous", ["Magnesiumtablette", "Schmerztablette"])
      and match("Magnesiumtabl", FIELDS)[1]["name"] == "Magnesiumtablette" and match("Magnesiumtabl", FIELDS)[2] is True)
near_one = match("Schmerztabltte", FIELDS[2:3] + FIELDS[4:])      # Schmerztablette and Magnesiumtablette only
check("match: a typo that one name is near to is resolved by the near-match and marked",
      near_one[0] == "resolved" and near_one[1]["name"] == "Schmerztablette" and near_one[2] is True)
check("match: a typo that two names are near to is unknown, the two names come as the near names",
      match("Schmerztabletxe", FIELDS) == ("unknown", ["Schmerztablette", "Schmerztabletta"]))
with patch.object(mcp_diary, "_fields", return_value=FIELDS):
    near_err = mcp_diary._resolve_field("Schmerztabletxe")[2]
    far_err = mcp_diary._resolve_field("zzzzqqqq")[2]
    blank_errors = [mcp_diary._resolve_field(v)[2]["error"] for v in ("", "   ", 5)]
check("resolve: an unknown name with near names has did_you_mean with them",
      near_err["did_you_mean"] == ["Schmerztablette", "Schmerztabletta"] and "unknown diary field" in near_err["error"])
check("resolve: an unknown name without near names has no did_you_mean at all", "did_you_mean" not in far_err and len(far_err["available_fields"]) == 5)
check("resolve: an empty or blank name and a number are refused with the clear text", all(e.startswith("field must be") for e in blank_errors))
many_fields = [{"key": f"K{i:02d}", "name": f"Feld {i:02d}"} for i in range(35)]
with patch.object(mcp_diary, "_fields", return_value=many_fields):
    long_err = mcp_diary._resolve_field("zzzzqqqq")[2]
check("resolve: the list of the fields in an unknown-field error is cut at 30 (alphabetical)",
      long_err["available_fields"] == sorted(f["name"] for f in many_fields)[:30])

# the rows of a day, the optional keys of a field, the range and the empty note
ROW_DAY = {"date": "2026-12-01", "entries": {"A": [{"values": {}}], "B": [{"time": "08:00", "values": {"x": 1}}]},
           "definitions": {"A": {"name": "a", "values": []}, "B": {"name": "b", "values": [{"label": "x", "type": "number"}]}}}
check("entry rows: a field filter that skips the first key still finds the second one",
      mcp_diary._entry_rows(ROW_DAY, "B") == [{"date": "2026-12-01", "time": "08:00", "field": "b", "key": "B",
                                              "values": [{"label": "x", "value": 1, "unit": None}]}]
      and len(mcp_diary._entry_rows(ROW_DAY, None)) == 2)
bare = {"fields": [{"key": "U9", "name": "Bare"}], "first_day": None, "last_day": None, "days": 0}
with patch.object(mcp_sql, "get_diary_fields", return_value=bare):
    bare_out = mcp_diary.list_diary_fields()["diary"]["fields"][0]
check("list_diary_fields: a field without the optional keys: no time, not archived, no counterpart, no values",
      bare_out == {"key": "U9", "name": "Bare", "with_time": False, "archived": False, "maps_to": None, "values": []})
same_day = mcp_diary.query_diary(D["d1"], D["d1"])
check("query_diary: a range of one day (from = to) is fine", "error" not in same_day and len(same_day["diary"]["entries"]) == 2)
check("query_diary: the error of a too long range names the real number of days (368)",
      "(368 days)" in mcp_diary.query_diary("2026-01-01", "2027-01-03")["error"])
check("query_diary: 'empty' is said only when there is neither an entry nor a note",
      "empty" not in mcp_diary.query_diary(D["d1"], D["d5"])["_meta"]
      and "empty" not in mcp_diary.query_diary(D["d4"], D["d4"], include_notes=True)["_meta"]
      and "empty" in mcp_diary.query_diary(D["d4"], D["d4"])["_meta"])
check("query_diary: a blank field name is refused with the clear text",
      mcp_diary.query_diary(D["d1"], D["d5"], field="  ")["error"].startswith("field must be"))

# many notes in the cache (days of 2030, removed again below): the default and the largest limit, what 'searched' counts
from datetime import date as _date, timedelta as _td  # noqa: E402

for i in range(205):
    mcp_sql.upsert_diary_day((_date(2030, 1, 1) + _td(days=i)).isoformat(), f"bulk{i}",
                             {"note": f"massennotiz {i}", "entries": {}, "definitions": {}})
n_notes = len(mcp_sql.get_diary_notes())
dflt = mcp_diary.search_diary_notes("massennotiz")["diary"]
check("search: without a limit 50 hits come back, cut and marked", len(dflt["hits"]) == 50 and dflt["truncated"] is True)
big = mcp_diary.search_diary_notes("massennotiz", limit=10**6)["diary"]
check("search: the largest limit is 200 (205 notes match)", len(big["hits"]) == 200 and big["truncated"] is True)
two = mcp_diary.search_diary_notes("massennotiz", limit=2)["diary"]
check("search: a limit of 2 gives two hits, and the loop stops at the third note ('searched' = 3)",
      len(two["hits"]) == 2 and two["truncated"] is True and two["searched"] == 3)
few = mcp_diary.search_diary_notes("wetter")["diary"]
check("search: without a cut every note is looked at, and 'searched' counts them", len(few["hits"]) == 1 and few["truncated"] is False
      and few["searched"] == n_notes)
mcp_sql.get_connection().execute("DELETE FROM mcp_diary_days WHERE date >= '2030-01-01'")
check("(cleanup) the days of 2030 are gone again", len(mcp_sql.get_diary_notes()) == n_notes - 205)

# the pointer from query_health / query_context
import mcp_query_common  # noqa: E402
from mcp_health import resolve_health_field  # noqa: E402
from mcp_context import resolve_context_field  # noqa: E402

with patch.object(mcp_diary.cfg, "MCP_DIARY_ENABLED", True):
    check("pointer: a name that is a diary field", "query_diary" in mcp_diary.diary_pointer("schmerztablette")
          and "Schmerztablette" in mcp_diary.diary_pointer("schmerz"))
    check("pointer: a name that matches two diary fields names both", "Magnesiumtablette" in mcp_diary.diary_pointer("tablette"))
    check("pointer: a name that is no diary field gives none", mcp_diary.diary_pointer("heart_rate") is None)
    with patch.object(mcp_diary, "_fields", side_effect=RuntimeError("boom")):
        check("pointer: an error inside (the cache cannot be read) never reaches the caller: none (mutation round v1.7.8.1)",
              mcp_diary.diary_pointer("schmerztablette") is None)
    check("pointer: the hint text for an unknown-field error", mcp_query_common.diary_hint("schmerztablette").startswith(" -- a diary field"))
    check("query_health's unknown-field error names query_diary", "query_diary" in resolve_health_field("schmerztablette")["error"]
          and resolve_health_field("schmerztablette")["error"].startswith("unknown field 'schmerztablette'"))
    check("query_context's unknown-field error names query_diary", "query_diary" in resolve_context_field("schmerztablette")["error"])
    check("a name that near-matches a Garmin field is still resolved there (the pointer comes only when it would fail)",
          "resolved_field" in resolve_health_field("resting_heart_rate"))
    set_switch(mcp=False)
    check("pointer: switch off: none", mcp_diary.diary_pointer("schmerztablette") is None)
    set_switch(mcp=True)
with patch.object(mcp_diary.cfg, "MCP_DIARY_ENABLED", False):
    check("pointer: the server started with the switch off: none (the tools do not exist)", mcp_diary.diary_pointer("schmerztablette") is None)
saved_module = sys.modules.pop("mcp_diary")
try:
    check("hint without the module (switch off at the start): the error text is the one it always was",
          mcp_query_common.diary_hint("schmerztablette") == ""
          and resolve_health_field("schmerztablette")["error"] == "unknown field 'schmerztablette'"
          and resolve_context_field("schmerztablette")["error"] == "unknown field 'schmerztablette'")
finally:
    sys.modules["mcp_diary"] = saved_module

# registration in the server: only when the switch was on at the start
saved_env = {k: os.environ.get(k) for k in ("GARMIN_MCP_DIARY_ENABLED", "GARMIN_MCP_DIARY_EXPORT_ENABLED")}
try:
    set_switch(mcp=True, export=False)
    importlib.reload(cfg)
    importlib.reload(mcp_server)
    on_names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    check("server started with the switch on: the three diary tools are registered next to the eleven others",
          len(on_names) == 14 and {"list_diary_fields", "query_diary", "search_diary_notes"} <= on_names)
    desc = {t.name: t.description for t in asyncio.run(mcp_server.mcp.list_tools())}
    check("the tool descriptions say it is typed by hand and point to query_health for measured values",
          all("by hand" in desc[n] for n in mcp_diary.TOOL_NAMES) and "query_health" in desc["query_diary"])
    avail = mcp_server.list_available_fields()
    check("list_available_fields (switch on): the diary field names and the diary tools are named, no unit entries for them",
          avail["fields"]["diary"] == ["Blood pressure", "Magnesiumtablette", "Schmerztablette", "Spazieren gegangen"]
          and avail["diary_tools"] == list(mcp_diary.TOOL_NAMES) and "Schmerztablette" not in avail["units"])
    check("list_available_fields (switch on): the domains are the same as always", avail["domains"] == ["health", "fit", "context"])
    set_switch(mcp=False)
    check("list_available_fields: the switch turned off while the server runs: nothing about the diary",
          "diary" not in mcp_server.list_available_fields()["fields"] and "diary_tools" not in mcp_server.list_available_fields())
    set_switch(mcp=False, export=False)
    importlib.reload(cfg)
    sys.modules.pop("mcp_diary", None)
    importlib.reload(mcp_server)
    off_names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    check("server started with the switch off: the eleven tools of always, no diary tool, the module is not imported",
          len(off_names) == 11 and not (off_names & set(mcp_diary.TOOL_NAMES)) and "mcp_diary" not in sys.modules)
    check("list_available_fields (switch off): no diary key", "diary" not in mcp_server.list_available_fields()["fields"]
          and "diary_tools" not in mcp_server.list_available_fields())
finally:
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    set_switch(mcp=False, export=False)
    importlib.reload(cfg)
    sys.modules["mcp_diary"] = saved_module

# ══════════════════════════════════════════════════════════════════════════════
section("8. Guards")
# ══════════════════════════════════════════════════════════════════════════════


def imported_modules(path):
    names = set()
    for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
    return names


offenders = []
for folder in ("garmin", "diary", "context"):
    for p in (_ROOT / folder).rglob("*.py"):
        if imported_modules(p) & {"mcp_sql", "mcp_update"}:
            offenders.append(f"{folder}/{p.name}")
check("no module in garmin/, diary/ or context/ imports the cache (nothing flows back from the cache into the archive)", offenders == [])

summary()
