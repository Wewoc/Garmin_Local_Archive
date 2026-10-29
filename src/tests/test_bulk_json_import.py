#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_json_import.py — garmin_bulk_json_import (v1.7.6.1)

Run from the project folder:
    python tests/test_bulk_json_import.py

The daily-values phase of the bulk import: garmin_import (load_bulk_with_entries) -> validator and
quality check -> garmin_bulk_writer (bulk/aggregates and the JSON originals in bulk/source). The
export is built here from scratch (a ZIP and an unpacked folder with synthetic JSON files). Names
inside the export carry a marker that stands for the e-mail address of the account; it must never
show up in the log or in the store.
"""

import ast
import hashlib
import json
import logging
import zipfile
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

section("B6. garmin_bulk_json_import (v1.7.6.1)")
import garmin_bulk_writer as bw
import garmin_import as gi
import garmin_bulk_json_import as jimp

SECRET = "secret.name@example.invalid"
UDS_A = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2024-05-01_2024-05-31.json"
UDS_B = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2024-06-01_2024-06-30.json"
UDS_JUNK = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_junk.json"
SLEEP = "DI_CONNECT/DI-Connect-Wellness/2024-05-01_2024-05-31_12345_sleepData.json"
READY = "DI_CONNECT/DI-Connect-Metrics/TrainingReadinessDTO_20240501_20240531_12345.json"
ACTS = f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_1_summarizedActivities.json"


def _window(day):
    """The day window fields of a UDS entry for a day in a +2 h zone."""
    y, m, d = (int(x) for x in day.split("-"))
    from datetime import date, timedelta
    cur = date(y, m, d)
    prev, nxt = cur - timedelta(days=1), cur + timedelta(days=1)
    return {"wellnessStartTimeGmt": f"{prev}T22:00:00.0", "wellnessStartTimeLocal": f"{cur}T00:00:00.0",
            "wellnessEndTimeGmt": f"{cur}T22:00:00.0", "wellnessEndTimeLocal": f"{nxt}T00:00:00.0"}


def _uds(day, steps, window=True, **extra):
    return {"calendarDate": day, "totalSteps": steps, "dailyStepGoal": 10000, "restingHeartRate": 52,
            "currentDayRestingHeartRate": 54, **(_window(day) if window else {}), **extra}


U0501 = _uds("2024-05-01", 8000, allDayStress={"aggregatorList": [{"averageStressLevel": 30, "maxStressLevel": 90}]})
U0502 = _uds("2024-05-02", 100)
U0506 = _uds("2024-05-06", 50, window=False)
U0601 = _uds("2024-06-01", 7)
S0501 = {"calendarDate": "2024-05-01", "deepSleepSeconds": 5000, "lightSleepSeconds": 10000,
         "remSleepSeconds": 6000, "awakeSleepSeconds": 900}
S0502 = {"calendarDate": "2024-05-02", "deepSleepSeconds": 4000, "lightSleepSeconds": 9000, "remSleepSeconds": 5000}
S0503 = {"calendarDate": "2024-05-03", "deepSleepSeconds": 1, "lightSleepSeconds": 1, "remSleepSeconds": 1}    # sleep only
R0502 = {"calendarDate": "2024-05-02", "level": "HIGH", "feedbackLong": "long", "feedbackShort": "short"}
R0504 = {"calendarDate": "2024-05-04", "level": "LOW"}                                                         # readiness only
A1 = {"name": "Run", "activityType": "running", "duration": 1800, "distance": 5000, "avgHr": 140, "maxHr": 170,
      "calories": 300, "startTimeLocal": 1714564800000}
A2 = {"name": "Walk", "startTimeLocal": 1714564800}


def _export(sleep_extra=(), uds_a_extra=()):
    return {
        UDS_A: [U0501, U0502, U0506, *uds_a_extra],
        UDS_B: [U0601],
        UDS_JUNK: {"a": 1},                                    # a file that is not a list: read, nothing found
        SLEEP: [S0501, S0503, *sleep_extra],
        READY: [R0502, R0504],
        ACTS: [{"summarizedActivitiesExport": [A1, A2]}],
    }


def _text(obj):
    return obj if isinstance(obj, str) else json.dumps(obj)


def _write_dir(root, files):
    for rel, obj in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_text(obj).encode("utf-8"))
    return Path(root)


def _write_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for rel, obj in files.items():
            z.writestr(rel, _text(obj))
    return Path(path)


def _tree(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


class _Log:
    """Captures what the module logs, including levels the suite switches off."""
    def __init__(self):
        self.lines = []

    def __enter__(self):
        self._logger = logging.getLogger("garmin_bulk_json_import")
        self._old = (self._logger.level, self._logger.propagate, logging.root.manager.disable)
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                outer.lines.append(record.getMessage())

        self._handler = _H()
        logging.disable(logging.NOTSET)
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *exc):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._old[0])
        self._logger.propagate = self._old[1]
        logging.disable(self._old[2])


def _canon_hash(kind, entry):
    text = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{kind}\0{text}".encode("utf-8")).hexdigest()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


# ── Helpers: entry hashes and the day window ──────────────────────────────────────────────────
H_UDS, H_SLEEP, H_ACT1, H_ACT2 = _canon_hash("uds", U0501), _canon_hash("sleep", S0501), _canon_hash("activity", A1), _canon_hash("activity", A2)
check("entry_hashes: one SHA-256 per source entry (uds, sleep, each activity), sorted, with the kind in front",
      jimp.entry_hashes({"uds": U0501, "sleep": S0501, "activities": [A1, A2]}) == sorted([H_UDS, H_SLEEP, H_ACT1, H_ACT2]))
check("entry_hashes: the order of the keys inside an entry does not matter",
      jimp.entry_hashes({"uds": dict(reversed(list(U0501.items())))}) == [H_UDS])
check("entry_hashes: the same content as another kind is another hash",
      _canon_hash("uds", S0501) != _canon_hash("sleep", S0501)
      and jimp.entry_hashes({"uds": S0501}) != jimp.entry_hashes({"sleep": S0501}))
check("entry_hashes: a day without entries, empty entries and entries that are no objects give no hash",
      jimp.entry_hashes({}) == [] and jimp.entry_hashes({"uds": {}, "activities": [{}, "x", None]}) == [])
check("entry_hashes: the same activity twice is one hash", jimp.entry_hashes({"activities": [A1, dict(A1)]}) == [H_ACT1])
check("day_window: the four fields of the UDS entry", jimp.day_window({"uds": U0501}) == _window("2024-05-01"))
check("day_window: a missing field, an empty or non-text value, no UDS entry -> None",
      jimp.day_window({"uds": U0506}) is None and jimp.day_window({"sleep": S0501}) is None and jimp.day_window({}) is None
      and jimp.day_window({"uds": {**_window("2024-05-01"), "wellnessEndTimeLocal": 5}}) is None
      and jimp.day_window({"uds": {**_window("2024-05-01"), "wellnessEndTimeLocal": ""}}) is None)

# ── Preview: nothing is written ───────────────────────────────────────────────────────────────
with _isolated_log_env("bulk_json") as base:
    exp = _write_zip(base / "export.zip", _export())
    api_before = {d: _tree(d) for d in (cfg.RAW_DIR, cfg.SOURCE_DIR, cfg.SUMMARY_DIR) if d.exists()}
    with _Log() as log:
        pre = jimp.run_aggregates_import(exp, dry_run=True)
    check("preview: ok, not stopped, no error", pre["ok"] and not pre["stopped"] and pre["error"] is None and pre["dry_run"] is True)
    check("preview: nothing is created in the bulk store (not even the folders)", not cfg.BULK_DIR.exists())
    check("preview: six JSON files read (the one that is not a list too), six days found",
          (pre["files"], pre["days_found"]) == (6, 6))
    check("preview: four days would be new, two are rejected for too little data (sleep only, readiness only), none invalid",
          pre["days"] == {"new": 4, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and pre["rejected"] == {"invalid": 0, "insufficient": 2} and pre["insufficient_days"] == ["2024-05-03", "2024-05-04"])
    check("preview: six originals would be new and the sizes are counted",
          (pre["originals"]["new"], pre["originals"]["present"], pre["originals"]["failed"]) == (6, 0, 0)
          and pre["originals"]["bytes"] == sum(len(_text(o).encode("utf-8")) for o in _export().values()))
    check("preview: no day is reported as written, three days carry a window (the fourth has none)",
          pre["written_days"] == [] and pre["days_with_window"] == 3)
    text = "\n".join(log.lines)
    check("preview: the log says PREVIEW and that nothing is written, names counts only (no entry name, no address)",
          "PREVIEW" in text and "nothing is written" in text and SECRET not in text and "@" not in text
          and "DI_CONNECT" not in text and "sleepData" not in text and "UDSFile" not in text)
    check("the API store is untouched by the preview", all(_tree(d) == api_before[d] for d in api_before))

    # ── The real run ──────────────────────────────────────────────────────────────────────────
    with _Log() as log:
        run = jimp.run_aggregates_import(exp)
    check("run: ok and not a preview", run["ok"] and run["dry_run"] is False and run["error"] is None)
    check("run: the two days with too little data are rejected and reported, and the run is still ok (a rejected day is no failure, v1.7.6.1)",
          run["rejected"] == {"invalid": 0, "insufficient": 2} and run["ok"] is True and run["days"]["failed"] == 0)
    check("run: four days written (new), the days written are reported sorted, as dates only",
          run["days"] == {"new": 4, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and run["written_days"] == ["2024-05-01", "2024-05-02", "2024-05-06", "2024-06-01"])
    check("run: the aggregates files are named by day in bulk/aggregates, none for the rejected days, no folder in bulk/raw",
          bw.list_aggregate_days() == ["2024-05-01", "2024-05-02", "2024-05-06", "2024-06-01"] and not cfg.BULK_RAW_DIR.exists())
    d1 = bw.read_aggregates("2024-05-01")
    check("run: the stored day is the day parse_day builds plus the day window",
          d1["aggregates"] == {**gi.parse_day({"uds": U0501, "sleep": S0501, "activities": [A1, A2]}, "2024-05-01"),
                               "day_window": _window("2024-05-01")})
    check("run: the proof of origin is the SHA-256 of every source entry of the day (uds, sleep, two activities)",
          d1["source_files"] == sorted([H_UDS, H_SLEEP, H_ACT1, H_ACT2]))
    d2 = bw.read_aggregates("2024-05-02")
    check("run: a day with uds and readiness holds both, its window is there",
          d2["source_files"] == sorted([_canon_hash("uds", U0502), _canon_hash("readiness", R0502)])
          and "training_readiness" in d2["aggregates"] and d2["aggregates"]["day_window"] == _window("2024-05-02"))
    check("run: a day whose UDS entry has no window fields has no day_window key",
          "day_window" not in bw.read_aggregates("2024-05-06")["aggregates"])
    check("run: every original is stored as <xx>/<hash>.json with the exact bytes",
          all((cfg.BULK_SOURCE_DIR / _sha(_text(o).encode("utf-8"))[:2] / f"{_sha(_text(o).encode('utf-8'))}.json").read_bytes() == _text(o).encode("utf-8")
              for o in _export().values()) and run["originals"]["new"] == 6)
    check("run: raw/, source/ and summary/ stay untouched, only aggregates and source appear in the bulk store",
          all(_tree(d) == api_before[d] for d in api_before) and sorted(p.name for p in cfg.BULK_DIR.iterdir()) == ["aggregates", "source"])
    text = "\n".join(log.lines)
    check("run: the log names counts only, no entry name or address", SECRET not in text and "@" not in text and "DI_CONNECT" not in text)
    check("run: nothing in the store carries a name from the export",
          all(p.name.startswith(cfg.BULK_AGG_FILE_PREFIX) or p.suffix == ".json" for p in cfg.BULK_DIR.rglob("*") if p.is_file())
          and not any(SECRET in p.name for p in cfg.BULK_DIR.rglob("*")))

    # ── Again: idempotent ─────────────────────────────────────────────────────────────────────
    stored = _tree(cfg.BULK_DIR)
    again = jimp.run_aggregates_import(exp)
    check("again: everything unchanged or present, nothing is written, nothing is reported as written",
          again["days"] == {"new": 0, "changed": 0, "unchanged": 4, "kept": 0, "failed": 0} and again["written_days"] == []
          and again["originals"]["new"] == 0 and again["originals"]["present"] == 6)
    check("again: not a name, size or modification time in the store has changed", _tree(cfg.BULK_DIR) == stored)
    pre2 = jimp.run_aggregates_import(exp, dry_run=True)
    check("a preview after the run shows the same: present and unchanged",
          pre2["originals"]["present"] == 6 and pre2["days"]["unchanged"] == 4 and pre2["days"]["new"] == 0)

    # ── A stored day that cannot be read is left alone: failed in the preview and in the run (F-1) ────
    agg1 = cfg.BULK_AGG_DIR / "garmin_bulk_agg_2024-05-01.json"
    real_rt = Path.read_text

    def _locked(self, *a, **k):
        if self == agg1:
            raise PermissionError("locked by another process")
        return real_rt(self, *a, **k)

    stored_before_lock = _tree(cfg.BULK_DIR)
    with patch.object(Path, "read_text", _locked):
        lock_pre = jimp.run_aggregates_import(exp, dry_run=True)
        lock_run = jimp.run_aggregates_import(exp)
    check("a stored day that cannot be read counts as failed in the preview (not as kept) and the preview is not ok",
          lock_pre["days"] == {"new": 0, "changed": 0, "unchanged": 3, "kept": 0, "failed": 1} and not lock_pre["ok"])
    check("... and in the run: failed, not ok, nothing written, the store is as it was",
          lock_run["days"] == {"new": 0, "changed": 0, "unchanged": 3, "kept": 0, "failed": 1} and not lock_run["ok"]
          and lock_run["written_days"] == [] and _tree(cfg.BULK_DIR) == stored_before_lock)

    # ── The same export as an unpacked folder gives the same store ───────────────────────────
    with _isolated_log_env("bulk_json_dir"):
        exp_dir = _write_dir(cfg.BULK_DIR.parent / "export", _export())
        run_dir = jimp.run_aggregates_import(exp_dir)
        check("an unpacked folder gives the same result as the ZIP",
              run_dir["days"] == run["days"] and run_dir["written_days"] == run["written_days"]
              and run_dir["originals"]["new"] == 6 and run_dir["insufficient_days"] == run["insufficient_days"]
              and bw.read_aggregates("2024-05-01")["aggregates"] == d1["aggregates"])

    # ── Only a part of the export: nothing gets smaller ───────────────────────────────────────
    with _isolated_log_env("bulk_json_part") as base2:
        full = jimp.run_aggregates_import(_write_zip(base2 / "full.zip", _export()))
        part = jimp.run_aggregates_import(_write_zip(base2 / "part.zip", {UDS_A: [U0501, U0502, U0506], UDS_B: [U0601]}))
        check("part of the export: a day that would get fewer entries is kept (05-01 without sleep and activities, 05-02 without readiness), the others unchanged",
              part["days"] == {"new": 0, "changed": 0, "unchanged": 2, "kept": 2, "failed": 0} and part["written_days"] == [])
        check("part of the export: the kept days are byte for byte as before",
              bw.read_aggregates("2024-05-01")["source_files"] == sorted([H_UDS, H_SLEEP, H_ACT1, H_ACT2]))

        # a later export: another sleep entry for 05-02, a changed sleep file; 05-01 has the same entries and stays
        later = jimp.run_aggregates_import(_write_zip(base2 / "later.zip", _export(sleep_extra=[S0502])))
        check("a later, fuller export: the day with one more entry is updated (changed), the day with the same entries stays although its file has other bytes",
              later["days"] == {"new": 0, "changed": 1, "unchanged": 3, "kept": 0, "failed": 0} and later["written_days"] == ["2024-05-02"]
              and "sleep" in bw.read_aggregates("2024-05-02")["aggregates"]
              and bw.read_aggregates("2024-05-02")["aggregates"]["sleep"]["dailySleepDTO"]["sleepTimeSeconds"] == 18000)
        check("a later export: the changed sleep file is kept as a new original next to the old one",
              later["originals"]["new"] == 1 and later["originals"]["present"] == 5)

        # a revised entry (other steps) does not replace the stored day
        revised = dict(U0506, totalSteps=51)
        rev = jimp.run_aggregates_import(_write_zip(base2 / "rev.zip", {**_export(), UDS_A: [U0501, U0502, revised]}))
        check("a revised entry of a stored day does not replace it (not a superset of the stored entries): kept",
              rev["days"]["kept"] >= 1 and bw.read_aggregates("2024-05-06")["aggregates"]["user_summary"]["totalSteps"] == 50)

    # ── Stop between two days ─────────────────────────────────────────────────────────────────
    with _isolated_log_env("bulk_json_stop") as base3:
        exp3 = _write_zip(base3 / "export.zip", _export())
        seen_day = lambda: any(cfg.BULK_AGG_DIR.glob("*.json")) if cfg.BULK_AGG_DIR.exists() else False   # noqa: E731
        s1 = jimp.run_aggregates_import(exp3, should_stop=seen_day)
        check("stop after the first day: stopped, exactly one day written, the originals read before are stored",
              s1["stopped"] and s1["days"]["new"] == 1 and len(s1["written_days"]) == 1 and s1["originals"]["new"] == 6)
        s2 = jimp.run_aggregates_import(exp3)
        check("a rerun after a stop completes the work: the first day is unchanged, the rest are new, the originals are present",
              not s2["stopped"] and s2["days"]["unchanged"] == 1 and s2["days"]["new"] == 3 and s2["originals"]["present"] == 6)

    # ── A day the validator rejects, writes and originals that fail ──────────────────────────
    with _isolated_log_env("bulk_json_fail") as base4:
        exp4 = _write_zip(base4 / "export.zip", _export())
        real_validate = jimp.validator.validate
        with patch.object(jimp.validator, "validate",
                          side_effect=lambda day: {"status": "critical", "issues": []} if day.get("date") == "2024-05-02" else real_validate(day)):
            inv = jimp.run_aggregates_import(exp4)
        check("a day the validator calls critical is rejected (counted as invalid), not stored, the others are written",
              inv["rejected"]["invalid"] == 1 and inv["days"]["new"] == 3 and "2024-05-02" not in bw.list_aggregate_days()
              and "2024-05-02" not in inv["insufficient_days"])
        check("a day the validator rejects does not make the run fail: ok stays true, no failed day (a rejected day is no failure, v1.7.6.1)",
              inv["ok"] is True and inv["days"]["failed"] == 0 and inv["error"] is None)
    with _isolated_log_env("bulk_json_fail2") as base5:
        exp5 = _write_zip(base5 / "export.zip", _export())
        with patch.object(jimp.bw, "write_aggregates", return_value=bw.FAILED):
            f1 = jimp.run_aggregates_import(exp5)
        check("days that cannot be written: counted as failed, the run is not ok, nothing is reported as written",
              f1["days"]["failed"] == 4 and not f1["ok"] and f1["written_days"] == [])
        with patch.object(jimp.bw, "store_original_json", return_value=bw.FAILED):
            f2 = jimp.run_aggregates_import(exp5)
        check("originals that cannot be stored: counted as failed, the run is not ok, the days are still written",
              f2["originals"]["failed"] == 6 and not f2["ok"] and f2["days"]["new"] == 4)

    # ── Other inputs ──────────────────────────────────────────────────────────────────────────
    with _isolated_log_env("bulk_json_other") as base6:
        missing = jimp.run_aggregates_import(base6 / "nothing_here.zip")
        check("a path that does not exist: an error in the summary, no exception, not ok, nothing created",
              missing["error"] == "export path does not exist" and not missing["ok"] and not cfg.BULK_DIR.exists())
        empty = base6 / "empty_dir"
        empty.mkdir()
        e = jimp.run_aggregates_import(empty)
        check("an empty folder: nothing found, ok, nothing created", e["ok"] and e["days_found"] == 0 and e["files"] == 0 and not cfg.BULK_DIR.exists())
        (base6 / "broken.zip").write_bytes(b"this is not a zip file")
        b = jimp.run_aggregates_import(base6 / "broken.zip")
        check("a corrupt ZIP: no day, no exception", b["days_found"] == 0 and b["error"] is None)
        with patch.object(jimp.importer, "load_bulk_with_entries", side_effect=RuntimeError(f"broken near {SECRET}")), _Log() as elog:
            unexpected = jimp.run_aggregates_import(_write_zip(base6 / "x.zip", _export()), dry_run=True)
        check("an unexpected error does not escape: it is in the summary, the run is not ok, and nothing names the entry",
              unexpected["error"] == "unexpected error (RuntimeError)" and not unexpected["ok"]
              and SECRET not in "\n".join(elog.lines) and SECRET not in json.dumps(unexpected))
        dup = {**_export(), "DI_CONNECT/DI-Connect-Aggregator/UDSFile_copy_of_b.json": _export()[UDS_B]}
        d = jimp.run_aggregates_import(_write_zip(base6 / "dup.zip", dup), dry_run=True)
        check("two files with the same content are one original (counted once)", d["files"] == 6 and d["originals"]["new"] == 6)

# ── The summary text ──────────────────────────────────────────────────────────────────────────
lines = jimp.format_summary(pre, dry_run=True)
joined = "\n".join(lines)
check("format_summary: a list of text lines with the numbers", isinstance(lines, list) and all(isinstance(x, str) for x in lines)
      and "6 JSON file(s) read" in joined and "4 new" in joined and "2 with too little data" in joined and "3 day(s) carry" in joined)
check("format_summary of a stopped run says so", any("stopped" in x for x in jimp.format_summary({**pre, "stopped": True}, dry_run=False)))
check("format_summary of a failed path says the error", any("does not exist" in x for x in jimp.format_summary(missing, dry_run=False)))
check("format_summary: no rejected line when nothing was rejected",
      not any("rejected" in x for x in jimp.format_summary({**pre, "rejected": {"invalid": 0, "insufficient": 0}}, dry_run=True)))

# ── store_day (v1.7.6.5, P2.4c): the step per day, shared by the import and the rebuild ────────
_SD_ENTRIES = {"uds": U0501, "sleep": S0501, "activities": [A1, A2]}
_SD_DAY = gi.parse_day(_SD_ENTRIES, "2024-05-01")
with _isolated_log_env("bulk_json_store_day") as base:
    _sd = jimp.empty_summary(False)
    jimp.store_day(_SD_DAY, _SD_ENTRIES, "2026-10-27T10:00:00", False, _sd)
    _stored = bw.read_aggregates("2024-05-01")
    check("store_day: a good day is written as the import writes it: new, reported, the day plus its window, the proof of origin",
          _sd["days"]["new"] == 1 and _sd["written_days"] == ["2024-05-01"] and _sd["days_with_window"] == 1
          and _stored["aggregates"] == {**_SD_DAY, "day_window": _window("2024-05-01")}
          and _stored["source_files"] == sorted([H_UDS, H_SLEEP, H_ACT1, H_ACT2]) and _stored["imported_at"] == "2026-10-27T10:00:00")
    _sd2 = jimp.empty_summary(False)
    jimp.store_day(_SD_DAY, _SD_ENTRIES, "2026-10-28T10:00:00", False, _sd2)
    check("store_day: the same day again is unchanged, nothing is written (not even the import time)",
          _sd2["days"]["unchanged"] == 1 and _sd2["written_days"] == []
          and bw.read_aggregates("2024-05-01")["imported_at"] == "2026-10-27T10:00:00")
    _sd_before = _tree(cfg.BULK_DIR)
    _sd_pre = jimp.empty_summary(True)
    jimp.store_day(gi.parse_day({"uds": U0502}, "2024-05-02"), {"uds": U0502}, "x", True, _sd_pre)
    check("store_day: a preview counts the day as new and writes nothing",
          _sd_pre["days"]["new"] == 1 and _sd_pre["written_days"] == [] and _tree(cfg.BULK_DIR) == _sd_before
          and "2024-05-02" not in bw.list_aggregate_days())
    _sd3 = jimp.empty_summary(False)
    jimp.store_day(gi.parse_day({"sleep": S0503}, "2024-05-03"), {"sleep": S0503}, "x", False, _sd3)
    check("store_day: a day with too little data is rejected and reported, not written",
          _sd3["rejected"] == {"invalid": 0, "insufficient": 1} and _sd3["insufficient_days"] == ["2024-05-03"]
          and "2024-05-03" not in bw.list_aggregate_days())
    _sd4 = jimp.empty_summary(False)
    with patch.object(jimp.validator, "validate", return_value={"status": "critical"}):
        jimp.store_day(gi.parse_day({"uds": U0502}, "2024-05-02"), {"uds": U0502}, "x", False, _sd4)
    check("store_day: an invalid day is rejected and not written",
          _sd4["rejected"] == {"invalid": 1, "insufficient": 0} and "2024-05-02" not in bw.list_aggregate_days())
    _sd5 = jimp.empty_summary(False)
    with patch.object(jimp.bw, "write_aggregates", return_value=bw.FAILED):
        jimp.store_day(gi.parse_day({"uds": U0502}, "2024-05-02"), {"uds": U0502}, "x", False, _sd5)
    check("store_day: a day that could not be written is counted as failed, not as written",
          _sd5["days"]["failed"] == 1 and _sd5["written_days"] == [])

with _isolated_log_env("bulk_json_store_day_import") as base_i:
    _exp_i = _write_dir(base_i / "exp", {UDS_A: [U0501], SLEEP: [S0501], ACTS: [{"summarizedActivitiesExport": [A1, A2]}]})
    jimp.run_aggregates_import(_exp_i)
    _via_import = bw.read_aggregates("2024-05-01")
with _isolated_log_env("bulk_json_store_day_direct") as base_d:
    jimp.store_day(_SD_DAY, _SD_ENTRIES, "2026-10-27T10:00:00", False, jimp.empty_summary(False))
    _via_store = bw.read_aggregates("2024-05-01")
check("store_day: the day it writes is the day the import of an export with the same entries writes (apart from the import time)",
      {k: v for k, v in _via_import.items() if k != "imported_at"} == {k: v for k, v in _via_store.items() if k != "imported_at"})

# ── v1.7.6.7 (P3): health status, pulse alert events, kept families, inventory ───────────────────
HEALTH = "DI_CONNECT/DI-Connect-Wellness/2024-05-01_2024-05-31_12345_healthStatusData.json"
ALERT = "DI_CONNECT/DI-Connect-Wellness/2024-05-01_2024-05-31_12345_AbnormalHrEvents.json"
GEAR = f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_gear.json"
PREC = f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_personalRecord.json"
COURSES = f"DI_CONNECT/DI-Connect-Routing/{SECRET}_courses_2024-01-01_2024-12-31.json"
ZONES = "DI_CONNECT/DI-Connect-Wellness/12345_heartRateZones.json"
WORKOUT = f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_workout.json"          # a family that is neither read nor kept


def _health(day, hrv=50.0):
    return {"calendarDate": day, "createTimestampUTC": day + "T04:00:00.0", "updateTimestampUTC": day + "T05:00:00.0",
            "outliersCount": 0, "metrics": [{"type": "HRV", "value": hrv, "status": "IN_RANGE", "feedbackKey": "k",
                                             "baselineLowerLimit": 40.0, "baselineUpperLimit": 60.0, "percentage": 50.0}]}


H0501, H0502, H0507 = _health("2024-05-01"), _health("2024-05-02", 55.0), _health("2024-05-07")      # 05-07: no other data
AL1 = {"calendarDate": "2024-05-01", "abnormalHrEventGMT": "2024-05-01T03:10:00.0", "abnormalHrThresholdValue": 120,
       "abnormalHrValue": 150, "deviceId": 1}
H_HEALTH, H_ALERT = _canon_hash("health_status", H0502), _canon_hash("alert_event", AL1)
check("entry_hashes (v1.7.6.7): a health status entry and each alert event get a hash, the alert event under its own kind name",
      jimp.entry_hashes({"health_status": H0502}) == [H_HEALTH] and jimp.entry_hashes({"alert_events": [AL1, dict(AL1)]}) == [H_ALERT]
      and jimp.entry_hashes({"uds": U0501, "health_status": H0502, "alert_events": [AL1]}) == sorted([H_UDS, H_HEALTH, H_ALERT]))
check("entry_hashes (v1.7.6.7): empty or malformed new entries give no hash; the same content under another kind is another hash",
      jimp.entry_hashes({"health_status": {}, "alert_events": [{}, "x", None]}) == []
      and _canon_hash("health_status", H0502) != _canon_hash("uds", H0502))


def _inv_lines(lines):
    return [x for x in lines if x.startswith("  inventory:")]


with _isolated_log_env("bulk_json_p3") as base:
    old_exp = _write_zip(base / "old.zip", _export())
    base_run = jimp.run_aggregates_import(old_exp)
    before = {d: (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{d}.json").read_bytes() for d in bw.list_aggregate_days()}
    files_new = {**_export(), HEALTH: [H0501, H0502, H0507], ALERT: [AL1], GEAR: [{"gearPk": 1}], PREC: [{"activityId": 7}],
                 COURSES: [{"courseId": 3}], ZONES: [{"zone1Floor": 100}], WORKOUT: [{"workoutId": 9}]}
    new_exp = _write_zip(base / "new.zip", files_new)
    tree_before = _tree(cfg.BULK_DIR)
    with _Log() as log_pre:
        pre = jimp.run_aggregates_import(new_exp, dry_run=True)
    check("P3 preview: the days with new entries would be changed (05-01, 05-02), the others unchanged; nothing is written",
          pre["ok"] and pre["days"] == {"new": 0, "changed": 2, "unchanged": 2, "kept": 0, "failed": 0}
          and pre["written_days"] == [] and _tree(cfg.BULK_DIR) == tree_before)
    check("P3 preview: a day with nothing but health status (05-07) is rejected for too little data, like a day with sleep only (pinned)",
          pre["rejected"] == {"invalid": 0, "insufficient": 3} and "2024-05-07" in pre["insufficient_days"])
    check("P3 preview: six new originals (health status, alert events, gear, records, courses, zones), six already stored; the workout file is not counted in",
          (pre["originals"]["new"], pre["originals"]["present"], pre["originals"]["failed"]) == (6, 6, 0) and pre["files"] == 12)
    with _Log() as log_imp:
        imp = jimp.run_aggregates_import(new_exp)
    check("P3 import: the same two days are written as changed, the others stay as they were",
          imp["ok"] and imp["days"] == {"new": 0, "changed": 2, "unchanged": 2, "kept": 0, "failed": 0}
          and imp["written_days"] == ["2024-05-01", "2024-05-02"] and imp["rejected"] == pre["rejected"])
    after = {d: (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{d}.json").read_bytes() for d in bw.list_aggregate_days()}
    check("P3 import: the aggregates files of the days without a new entry are byte-identical to before; the day of the insufficient health status was not created",
          after["2024-05-06"] == before["2024-05-06"] and after["2024-06-01"] == before["2024-06-01"]
          and "2024-05-07" not in after and set(after) == set(before))
    a0501, a0502 = bw.read_aggregates("2024-05-01"), bw.read_aggregates("2024-05-02")
    check("P3 import: the day gets its two sections as delivered and the hashes of the new entries in its proof of origin",
          a0501["aggregates"]["alert_events"] == [AL1] and a0501["aggregates"]["health_status"] == H0501
          and a0502["aggregates"]["health_status"] == H0502 and "alert_events" not in a0502["aggregates"]
          and _canon_hash("alert_event", AL1) in a0501["source_files"] and H_HEALTH in a0502["source_files"]
          and a0501["schema_version"] == bw.AGG_SCHEMA_VERSION)
    check("P3 import: the rest of the day is what it was (user summary of 05-01 unchanged)",
          a0501["aggregates"]["user_summary"] == bw.load_aggregates("2024-05-01")[1]["aggregates"]["user_summary"]
          and json.loads(before["2024-05-01"])["aggregates"]["user_summary"] == a0501["aggregates"]["user_summary"])
    check("P3 import: six originals written, six already there; the originals of the new families are in bulk/source, the workout file is not",
          (imp["originals"]["new"], imp["originals"]["present"]) == (6, 6)
          and all(bw.original_json_present(_sha(_text(files_new[n]).encode("utf-8")), len(_text(files_new[n]).encode("utf-8")))
                  for n in (HEALTH, ALERT, GEAR, PREC, COURSES, ZONES))
          and not bw.original_json_present(_sha(_text(files_new[WORKOUT]).encode("utf-8")), len(_text(files_new[WORKOUT]).encode("utf-8")))
          and len(bw.list_originals()) == 12)
    again = jimp.run_aggregates_import(new_exp)
    check("P3 rerun of the same export: every day unchanged, nothing written, every original already stored",
          again["days"] == {"new": 0, "changed": 0, "unchanged": 4, "kept": 0, "failed": 0} and again["written_days"] == []
          and (again["originals"]["new"], again["originals"]["present"]) == (0, 12))
    old_again = jimp.run_aggregates_import(old_exp)
    check("P3 the older export (without the new entries) now: every day 'kept' where the stored day is fuller, nothing replaced",
          old_again["days"]["kept"] == 2 and old_again["days"]["unchanged"] == 2 and old_again["written_days"] == []
          and bw.read_aggregates("2024-05-01") == a0501)

    # -- inventory: the same lines in the preview and in the import, counts only ------------------------------
    inv_pre, inv_imp = _inv_lines(jimp.format_summary(pre, True)), _inv_lines(jimp.format_summary(imp, False))
    check("P3 inventory: preview and import show the same lines (six kinds, four kept families, one line for what is not known)",
          inv_pre == inv_imp and len(inv_pre) == 11)
    joined = "\n".join(inv_imp)
    check("P3 inventory: every known kind has a line with its state and count, the kept families say 'kept only, not read'",
          "health status — read, 1 file(s)" in joined and "pulse alert events — read, 1 file(s)" in joined
          and "activities — read, 1 file(s)" in joined and "gear — kept only, not read, 1 file(s)" in joined
          and "zones — kept only, not read, 1 file(s)" in joined and "training readiness — read, 1 file(s)" in joined)
    check("P3 inventory: what is not known is one line with the number of files and folders, the folder is named, the file is not",
          "not recognised — 1 JSON file(s) in 1 folder(s): DI_CONNECT/DI-Connect-Fitness" in joined)
    log_text = "\n".join(log_pre.lines + log_imp.lines)
    check("P3 inventory: no file name and no address in the whole log of the preview and the import",
          SECRET not in log_text and "@" not in log_text and "workout" not in log_text and "gear" not in log_text.replace("gear — kept only", "")
          and "_courses_" not in log_text and "heartRateZones" not in log_text)
    check("P3 inventory: the summary keeps the inventory as numbers and folders", imp["inventory"]["kept"] == {"gear": 1, "personalRecord": 1, "courses": 1, "zones": 1}
          and imp["inventory"]["unknown"] == {"files": 1, "folders": ["DI_CONNECT/DI-Connect-Fitness"]})

    # -- the day is still usable downstream: validator, resolved summary, backup, mirror -------------------
    import garmin_writer as gw
    import garmin_backup_bulk as bb
    import garmin_container as gc
    resolved = gw._summarize_resolved({}, a0501["aggregates"])
    check("P3 downstream: the resolved summary of a day with the new sections is built without error and does not carry them",
          isinstance(resolved, dict) and "health_status" not in resolved and "alert_events" not in resolved)
    gear_hash = _sha(_text(files_new[GEAR]).encode("utf-8"))
    bb_res = bb.backup_all()
    check("P3 downstream: the bulk backup holds the original of a kept family, byte for byte",
          bb_res["ok"] and bb.read_original_copy(gear_hash, ".json") == _text(files_new[GEAR]).encode("utf-8"))
    check("P3 downstream: the mirror container takes the kept originals into the section bulk_source",
          gc._classify_file(("garmin_data", "bulk", "source", gear_hash[:2], gear_hash + ".json")) == "bulk_source"
          and bw.describe_container_path(f"garmin_data/bulk/source/{gear_hash[:2]}/{gear_hash}.json") == ("original", gear_hash, ".json"))

# -- the older log lines are still there, without an inventory the summary prints none ---------------------------
check("P3 format_summary: without an inventory (or an empty one) no inventory line, nothing else changes",
      _inv_lines(jimp.format_summary({**pre, "inventory": None}, True)) == [] and _inv_lines(jimp.format_summary({**pre, "inventory": {}}, True)) == []
      and jimp.inventory_lines(None) == [])
check("P3 format_summary: files that could not be used are named by count only, with the limit",
      any("2 file(s) not readable, 1 over the size limit (64 MB)" in x
          for x in jimp.inventory_lines({**pre["inventory"], "unreadable": 2, "too_large": 1})))
_many = {"read": {}, "kept": {}, "unknown": {"files": 25, "folders": [f"DI_CONNECT/f{i:02d}" for i in range(25)]}}
_many_line = [x for x in jimp.inventory_lines(_many) if "not recognised" in x][0]
check("P3 format_summary: of many unknown folders the first 20 are named, then an ellipsis; the count is the full one",
      "25 JSON file(s) in 25 folder(s)" in _many_line and "DI_CONNECT/f19" in _many_line and "DI_CONNECT/f20" not in _many_line
      and _many_line.endswith(", …"))
check("P3 empty_summary: a new key 'inventory', empty until the importer fills it", jimp.empty_summary(True)["inventory"] is None)

# ── v1.7.6.8 (P4): current state, pinned before the source comparison was built ───────────────────
# Without a function that reads raw/ the import runs as before: no comparison lines, the same numbers
# in a preview and in the run, the same numbers on a rerun.
with _isolated_log_env("bulk_json_p4_state") as base_p4:
    _p4_exp = _write_zip(base_p4 / "export.zip", _export())
    with _Log() as _p4_log:
        _p4_pre = jimp.run_aggregates_import(_p4_exp, dry_run=True)
        _p4_run = jimp.run_aggregates_import(_p4_exp)
        _p4_again = jimp.run_aggregates_import(_p4_exp)
    check("P4 current state: without a read function the log has no line about a comparison of sources",
          not any("compar" in x.lower() for x in _p4_log.lines)
          and not any("compar" in x.lower() for x in jimp.format_summary(_p4_run, False)))
    check("P4 current state: preview, run and rerun count the days of the export alike (4 days stored or to be stored, 2 rejected)",
          _p4_pre["days_found"] == _p4_run["days_found"] == _p4_again["days_found"] == 6
          and _p4_pre["rejected"] == _p4_run["rejected"] == _p4_again["rejected"] == {"invalid": 0, "insufficient": 2})

# ── v1.7.6.8 (P4): comparison of the sources — compare_day, one field after the other ─────────────
def _ud(**kw):
    return {"user_summary": kw}


def _slp(deep=None, light=None, rem=None, **kw):
    return {"sleep": {"dailySleepDTO": {"deepSleepSeconds": deep, "lightSleepSeconds": light, "remSleepSeconds": rem, **kw}}}


cd = jimp.compare_day
check("P4 compare_day: equal values -> equal; the fields are named by the keys of the table",
      cd(_ud(totalSteps=900), _ud(totalSteps=900)) == {"steps": "equal"}
      and [f[0] for f in jimp.COMPARE_FIELDS] == ["steps", "resting_hr", "min_hr", "max_hr", "stress_avg", "sleep", "floors"])
check("P4 compare_day: another value -> differ (no tolerance for steps and the pulse values)",
      cd(_ud(totalSteps=900), _ud(totalSteps=901)) == {"steps": "differ"}
      and cd(_ud(restingHeartRate=50), _ud(restingHeartRate=51)) == {"resting_hr": "differ"}
      and cd(_ud(minHeartRate=40), _ud(minHeartRate=41)) == {"min_hr": "differ"}
      and cd(_ud(maxHeartRate=150), _ud(maxHeartRate=149)) == {"max_hr": "differ"})
check("P4 compare_day: the API day has no value, the export has one -> added (a missing section, a missing key, None)",
      cd(_ud(totalSteps=900), {}) == {"steps": "added"} and cd(_ud(totalSteps=900), _ud(dailyStepGoal=5)) == {"steps": "added"}
      and cd(_ud(totalSteps=900), _ud(totalSteps=None)) == {"steps": "added"} and cd(_ud(totalSteps=900), "no dict") == {"steps": "added"})
check("P4 compare_day: the export has no value -> the field does not count (both empty, or only the API has one)",
      cd({}, {}) == {} and cd(_ud(totalSteps=None), _ud(totalSteps=None)) == {} and cd({}, _ud(totalSteps=900)) == {}
      and cd(_ud(totalSteps="900"), _ud(totalSteps=900)) == {})
check("P4 compare_day: 0 is a value, not a gap (0 against nothing: added; 0 against 0: equal; 5 against 0: differ)",
      cd(_ud(totalSteps=0), {}) == {"steps": "added"} and cd(_ud(totalSteps=0), _ud(totalSteps=0)) == {"steps": "equal"}
      and cd(_ud(totalSteps=5), _ud(totalSteps=0)) == {"steps": "differ"})
check("P4 compare_day: a boolean is no number",
      cd(_ud(totalSteps=True), _ud(totalSteps=1)) == {} and cd(_ud(totalSteps=1), _ud(totalSteps=True)) == {"steps": "added"})
check("P4 compare_day: floors, tolerance 1 (a difference of 1 is equal, of 2 differs, in both directions)",
      cd(_ud(floorsAscended=5), _ud(floorsAscended=6.0)) == {"floors": "equal"} and cd(_ud(floorsAscended=5), _ud(floorsAscended=4)) == {"floors": "equal"}
      and cd(_ud(floorsAscended=5), _ud(floorsAscended=7.0)) == {"floors": "differ"} and cd(_ud(floorsAscended=5), _ud(floorsAscended=3)) == {"floors": "differ"})
check("P4 compare_day: stress average — the export calls it averageStressLevel, the API day avgStressLevel",
      cd({"stress": {"averageStressLevel": 31}}, {"stress": {"avgStressLevel": 31}}) == {"stress_avg": "equal"}
      and cd({"stress": {"averageStressLevel": 31}}, {"stress": {"avgStressLevel": 33}}) == {"stress_avg": "differ"}
      and cd({"stress": {"averageStressLevel": 31}}, {"stress": {"averageStressLevel": 31}}) == {"stress_avg": "added"})
check("P4 compare_day: the heart-rate extremes of the API day are read in user_summary, not in heart_rates",
      cd(_ud(minHeartRate=50, maxHeartRate=140), {**_ud(minHeartRate=50, maxHeartRate=140), "heart_rates": {"minHeartRate": 99, "maxHeartRate": 99}})
      == {"min_hr": "equal", "max_hr": "equal"}
      and cd(_ud(minHeartRate=50), {"heart_rates": {"minHeartRate": 50}}) == {"min_hr": "added"})
check("P4 compare_day: sleep is the sum of deep, light and REM seconds, tolerance 60 s (60 equal, 61 differs)",
      cd(_slp(1000, 2000, 3000), _slp(1000, 2000, 3000)) == {"sleep": "equal"}
      and cd(_slp(1000, 2000, 3000), _slp(1030, 2000, 3030)) == {"sleep": "equal"}
      and cd(_slp(1000, 2000, 3000), _slp(1000, 2000, 2940)) == {"sleep": "equal"}
      and cd(_slp(1000, 2000, 3000), _slp(1000, 2000, 2939)) == {"sleep": "differ"}
      and cd(_slp(1000, 2000, 3000), _slp(1000, 2000, 3061)) == {"sleep": "differ"})
check("P4 compare_day: sleep ignores sleepTimeSeconds and the awake seconds, takes the parts that are numbers, none -> no value",
      cd(_slp(1000, 2000, 3000, sleepTimeSeconds=1, awakeSleepSeconds=7), _slp(1000, 2000, 3000, sleepTimeSeconds=999999, awakeSleepSeconds=0)) == {"sleep": "equal"}
      and cd(_slp(1000, None, 3000), _slp(1000, 9999, 3000)) == {"sleep": "differ"}
      and cd(_slp(), _slp(1, 1, 1)) == {} and cd(_slp(1000, 2000, 3000), _slp()) == {"sleep": "added"})
check("P4 compare_day: off-wrist night — 0 seconds in the export, no value in the API day -> added",
      cd(_slp(0, 0, 0), _slp()) == {"sleep": "added"} and cd(_slp(0, 0, 0), {}) == {"sleep": "added"})
check("P4 compare_day: several rows for one day (a list) count with their maximum, not the first or the last",
      cd(_ud(totalSteps=[5, 9, 7]), _ud(totalSteps=9)) == {"steps": "equal"} and cd(_ud(totalSteps=[5, 9, 7]), _ud(totalSteps=5)) == {"steps": "differ"}
      and cd(_ud(totalSteps=900), _ud(totalSteps=[3, 900, 4])) == {"steps": "equal"} and cd(_ud(totalSteps=[]), _ud(totalSteps=1)) == {}
      and cd(_ud(totalSteps=["x", None]), _ud(totalSteps=1)) == {} and cd(_ud(totalSteps=[True]), _ud(totalSteps=1)) == {})
check("P4 compare_day: all fields at once, each by its own rule",
      cd({**_ud(totalSteps=1, restingHeartRate=2, minHeartRate=3, maxHeartRate=4, floorsAscended=5), "stress": {"averageStressLevel": 6}, **_slp(7, 8, 9)},
         {**_ud(totalSteps=1, restingHeartRate=22, maxHeartRate=4, floorsAscended=3), "stress": {"avgStressLevel": 6}, **_slp(7, 8, 9)})
      == {"steps": "equal", "resting_hr": "differ", "min_hr": "added", "max_hr": "equal", "stress_avg": "equal", "sleep": "equal", "floors": "differ"})

# ── the counters: _compare_into, empty_comparison, comparison_lines ───────────────────────────────
_cmp = jimp.empty_comparison()
check("P4 empty_comparison: no day, a counter set per field of the table",
      _cmp["days_compared"] == 0 and _cmp["days_without_api"] == 0 and list(_cmp["fields"]) == [f[0] for f in jimp.COMPARE_FIELDS]
      and all(v == {"equal": 0, "added": 0, "differ": 0, "differ_days": []} for v in _cmp["fields"].values()))
for _d in ("2024-03-05", "2024-03-01", "2024-03-09", "2024-03-03", "2024-03-07"):
    jimp._compare_into(_cmp, _d, _ud(totalSteps=1), lambda _x: _ud(totalSteps=2))
check("P4 _compare_into: the first three differing days, in date order, whatever order the days came in; the count is the full one",
      _cmp["fields"]["steps"]["differ_days"] == ["2024-03-01", "2024-03-03", "2024-03-05"] and _cmp["fields"]["steps"]["differ"] == 5
      and _cmp["days_compared"] == 5)
for _reader in (lambda _x: {}, lambda _x: None, lambda _x: "text", lambda _x: [1]):
    _c2 = jimp.empty_comparison()
    jimp._compare_into(_c2, "2024-03-01", _ud(totalSteps=1), _reader)
    check("P4 _compare_into: an API day that is empty, None or no dict counts as a day without an API file", _c2["days_without_api"] == 1 and _c2["days_compared"] == 0
          and all(v["equal"] + v["added"] + v["differ"] == 0 for v in _c2["fields"].values()))


def _boom(_x):
    raise OSError(f"cannot read near {SECRET}")


_c3 = jimp.empty_comparison()
with _Log() as _l3:
    jimp._compare_into(_c3, "2024-03-01", _ud(totalSteps=1), _boom)
check("P4 _compare_into: a read function that raises counts as a day without an API file; nothing is raised, no name is logged",
      _c3["days_without_api"] == 1 and SECRET not in "\n".join(_l3.lines))
_lines3 = jimp.comparison_lines(_cmp)
check("P4 comparison_lines: a header and one line per field; more than three differing days end with an ellipsis, counts and dates only",
      len(_lines3) == 1 + len(jimp.COMPARE_FIELDS) and "5 day(s) compared, 0 without an API file" in _lines3[0] and "nothing is changed or stored" in _lines3[0]
      and _lines3[1] == "    steps: 0 equal, 0 added by the export, 5 differing (2024-03-01, 2024-03-03, 2024-03-05, …)")
_c4 = jimp.empty_comparison()
for _d in ("2024-03-02", "2024-03-01"):
    jimp._compare_into(_c4, _d, _ud(totalSteps=1), lambda _x: _ud(totalSteps=2))
jimp._compare_into(_c4, "2024-03-03", _ud(totalSteps=1), lambda _x: _ud(totalSteps=1))
check("P4 comparison_lines: up to three differing days are all named, without an ellipsis; the other fields show zeros",
      jimp.comparison_lines(_c4)[1] == "    steps: 1 equal, 0 added by the export, 2 differing (2024-03-01, 2024-03-02)"
      and jimp.comparison_lines(_c4)[2] == "    resting heart rate: 0 equal, 0 added by the export, 0 differing")

# ── v1.7.6.8 (P4): the comparison inside the import (preview and run alike) ────────────────────────
# Export days: 05-01 (steps 8000, resting 54, stress 30, sleep 21000 s), 05-02 (steps 100, resting 54), 05-06 (steps 50, no API day),
# 06-01 (steps 7, resting 54), 05-03 (sleep only, rejected), 05-04 (readiness only, rejected, no API day).
_API = {
    "2024-05-01": {**_ud(totalSteps=8000, restingHeartRate=54), "stress": {"avgStressLevel": 30}, **_slp(5000, 10000, 6000)},
    "2024-05-02": _ud(totalSteps=105),
    "2024-06-01": _ud(totalSteps=7),
    "2024-05-03": _slp(1, 1, 100),
}


class _Reader:
    def __init__(self, days):
        self.days, self.asked = days, []

    def __call__(self, date_str):
        self.asked.append(date_str)
        return self.days.get(date_str, {})


with _isolated_log_env("bulk_json_p4") as base_p4b:
    _p4_exp2 = _write_zip(base_p4b / "export.zip", _export())
    _rd_pre, _rd_run, _rd_again = _Reader(_API), _Reader(_API), _Reader(_API)
    with _Log() as _p4b_log:
        _pre4 = jimp.run_aggregates_import(_p4_exp2, dry_run=True, read_raw=_rd_pre)
        _store_after_pre = cfg.BULK_DIR.exists()
        _run4 = jimp.run_aggregates_import(_p4_exp2, read_raw=_rd_run)
        _again4 = jimp.run_aggregates_import(_p4_exp2, read_raw=_rd_again)
    _cmp4 = _run4["comparison"]
    _f = _cmp4["fields"]
    check("P4 import: every day of the export is asked for once, also the two the import rejects; the days without an API file are counted apart",
          sorted(_rd_run.asked) == ["2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-06", "2024-06-01"]
          and _cmp4["days_compared"] == 4 and _cmp4["days_without_api"] == 2)
    check("P4 import: steps — equal on 05-01 and 06-01, differing on 05-02; resting heart rate — equal once, added twice (the API day has none on 05-02 and 06-01)",
          (_f["steps"]["equal"], _f["steps"]["added"], _f["steps"]["differ"], _f["steps"]["differ_days"]) == (2, 0, 1, ["2024-05-02"])
          and (_f["resting_hr"]["equal"], _f["resting_hr"]["added"], _f["resting_hr"]["differ"]) == (1, 2, 0))
    check("P4 import: stress equal once; sleep equal on 05-01 and differing on the rejected day 05-03; the fields no day had in the export stay at zero",
          (_f["stress_avg"]["equal"], _f["stress_avg"]["added"], _f["stress_avg"]["differ"]) == (1, 0, 0)
          and (_f["sleep"]["equal"], _f["sleep"]["added"], _f["sleep"]["differ"], _f["sleep"]["differ_days"]) == (1, 0, 1, ["2024-05-03"])
          and all(_f[k]["equal"] + _f[k]["added"] + _f[k]["differ"] == 0 for k in ("min_hr", "max_hr", "floors")))
    check("P4 import: the preview shows the same numbers as the run, and so does a rerun of the same export",
          _pre4["comparison"] == _cmp4 == _again4["comparison"] and sorted(_rd_pre.asked) == sorted(_rd_run.asked) == sorted(_rd_again.asked))
    check("P4 import: nothing is stored for the comparison — the preview created no folder, the run stores the same days and no comparison number",
          _store_after_pre is False and _run4["days"] == {"new": 4, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and _again4["days"]["unchanged"] == 4 and _again4["written_days"] == []
          and not any(b"compar" in p.read_bytes() for p in cfg.BULK_DIR.rglob("*.json")))
    _txt4 = "\n".join(_p4b_log.lines)
    check("P4 import: the log carries the comparison lines in the preview and in the run, with counts and dates only (no name, no address)",
          _txt4.count("compare:   export against the API files in raw/") == 3 and "    steps: 2 equal, 0 added by the export, 1 differing (2024-05-02)" in _txt4
          and "4 day(s) compared, 2 without an API file (not compared)" in _txt4 and SECRET not in _txt4 and "@" not in _txt4 and "DI_CONNECT" not in _txt4)
    check("P4 import: the summary lines of a preview and of a run name the comparison", any("compare:" in x for x in jimp.format_summary(_pre4, True))
          and any("compare:" in x for x in jimp.format_summary(_run4, False)))

with _isolated_log_env("bulk_json_p4_plain") as base_p4c:
    _plain = jimp.run_aggregates_import(_write_zip(base_p4c / "export.zip", _export()))
    _plain_days = {d: bw.read_aggregates(d) for d in bw.list_aggregate_days()}
with _isolated_log_env("bulk_json_p4_with") as base_p4d:
    _with = jimp.run_aggregates_import(_write_zip(base_p4d / "export.zip", _export()), read_raw=_Reader(_API))
    _with_days = {d: bw.read_aggregates(d) for d in bw.list_aggregate_days()}
check("P4 import: without a read function the comparison is None, with one the stored days are the same, byte for byte apart from the import time",
      _plain["comparison"] is None and _with["comparison"] is not None and _plain["days"] == _with["days"]
      and {d: {k: v for k, v in e.items() if k != "imported_at"} for d, e in _plain_days.items()}
      == {d: {k: v for k, v in e.items() if k != "imported_at"} for d, e in _with_days.items()})
check("P4 empty_summary: a new key 'comparison', None until the import fills it", jimp.empty_summary(False)["comparison"] is None)

with _isolated_log_env("bulk_json_p4_edge") as base_p4e:
    _p4_exp3 = _write_zip(base_p4e / "export.zip", _export())
    _never = lambda _x: (_ for _ in ()).throw(RuntimeError("raw/ is not readable"))      # noqa: E731
    _boom_run = jimp.run_aggregates_import(_p4_exp3, read_raw=_never)
    check("P4 import: a read function that raises on every day does not stop the import: all six days count as without an API file, the days are stored",
          _boom_run["ok"] and _boom_run["comparison"]["days_without_api"] == 6 and _boom_run["comparison"]["days_compared"] == 0
          and _boom_run["days"]["new"] == 4)
with _isolated_log_env("bulk_json_p4_invalid") as base_p4f:
    _real_validate = jimp.validator.validate
    with patch.object(jimp.validator, "validate",
                      side_effect=lambda day: {"status": "critical", "issues": []} if day.get("date") == "2024-05-02" else _real_validate(day)):
        _inv4 = jimp.run_aggregates_import(_write_zip(base_p4f / "export.zip", _export()), read_raw=_Reader(_API))
    check("P4 import: a day the validator rejects is still compared (the comparison is about the sources, not about what is stored)",
          _inv4["rejected"]["invalid"] == 1 and _inv4["comparison"]["fields"]["steps"]["differ_days"] == ["2024-05-02"] and _inv4["comparison"]["days_compared"] == 4)
with _isolated_log_env("bulk_json_p4_stop") as base_p4g:
    _rd_stop = _Reader(_API)
    _first_day_done = lambda: any(cfg.BULK_AGG_DIR.glob("*.json")) if cfg.BULK_AGG_DIR.exists() else False      # noqa: E731
    _stop4 = jimp.run_aggregates_import(_write_zip(base_p4g / "export.zip", _export()), should_stop=_first_day_done, read_raw=_rd_stop)
    check("P4 import: a stopped run compares only the days it went through (no raw/ file is read after the stop)",
          _stop4["stopped"] and len(_stop4["written_days"]) == 1 and len(_rd_stop.asked) == 1
          and _stop4["comparison"]["days_compared"] + _stop4["comparison"]["days_without_api"] == 1)
check("P4 format_summary: an error summary names the error only, a summary without a comparison has no line about it",
      jimp.format_summary({**_pre4, "error": "x", "comparison": _cmp4}, True) == ["Bulk daily values import — error: x"]
      and not any("compare" in x for x in jimp.format_summary({**_pre4, "comparison": None}, True)))

# ── Imports: standard library and the named project modules only ─────────────────────────────
_tree_ast = ast.parse(Path(jimp.__file__).read_text(encoding="utf-8"))
_top = set()
for _n in _tree_ast.body:
    if isinstance(_n, ast.Import):
        _top |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _top.add(_n.module.split(".")[0])
_allowed_std = {"copy", "hashlib", "json", "logging", "datetime", "pathlib", "__future__"}
_allowed_project = {"garmin_bulk_writer", "garmin_import", "garmin_normalizer", "garmin_quality", "garmin_validator"}
check("module level: standard library and the five named project modules only",
      _top <= _allowed_std | _allowed_project and _allowed_project <= _top)
check("garmin_config is not imported at all (the writer reads the paths)",
      "garmin_config" not in {a.name.split(".")[0] for n in ast.walk(_tree_ast) if isinstance(n, ast.Import) for a in n.names}
      and "garmin_config" not in {n.module.split(".")[0] for n in ast.walk(_tree_ast) if isinstance(n, ast.ImportFrom) and n.module})
check("no print", not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree_ast)))

summary()
