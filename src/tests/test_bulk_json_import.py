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
