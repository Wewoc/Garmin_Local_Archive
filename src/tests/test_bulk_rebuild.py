#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_rebuild.py — garmin_bulk_rebuild (v1.7.6.5)

Run from the project folder:
    python tests/test_bulk_rebuild.py

The rebuild of the bulk daily values from the JSON originals kept in bulk/source: an export is
imported first (garmin_bulk_json_import, which keeps the originals), bulk/aggregates is deleted, and the
rebuild must bring back the same days — without the export. The export is built here from scratch
(synthetic JSON files with the keys the content detection looks for).
"""

import ast
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

section("B7. garmin_bulk_rebuild (v1.7.6.5)")
import garmin_bulk_writer as bw
import garmin_bulk_json_import as jimp
import garmin_bulk_rebuild as rb

SECRET = "secret.name@example.invalid"
UDS_A = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2024-05-01_2024-05-31.json"
UDS_B = "DI_CONNECT/DI-Connect-Aggregator/UDSFile_2024-06-01_2024-06-30.json"
SLEEP = "DI_CONNECT/DI-Connect-Wellness/2024-05-01_2024-05-31_12345_sleepData.json"
READY = "DI_CONNECT/DI-Connect-Metrics/TrainingReadinessDTO_20240501_20240531_12345.json"
ACTS = f"DI_CONNECT/DI-Connect-Fitness/{SECRET}_1_summarizedActivities.json"


def _window(day):
    y, m, d = (int(x) for x in day.split("-"))
    from datetime import date, timedelta
    cur = date(y, m, d)
    prev, nxt = cur - timedelta(days=1), cur + timedelta(days=1)
    return {"wellnessStartTimeGmt": f"{prev}T22:00:00.0", "wellnessStartTimeLocal": f"{cur}T00:00:00.0",
            "wellnessEndTimeGmt": f"{cur}T22:00:00.0", "wellnessEndTimeLocal": f"{nxt}T00:00:00.0"}


def _uds(day, steps, **extra):
    return {"calendarDate": day, "uuid": "uuid-" + day, "totalSteps": steps, "dailyStepGoal": 10000, "restingHeartRate": 52,
            "currentDayRestingHeartRate": 54, **_window(day), **extra}


U0501 = _uds("2024-05-01", 8000, allDayStress={"aggregatorList": [{"averageStressLevel": 30, "maxStressLevel": 90}]})
U0502 = _uds("2024-05-02", 100)
U0601 = _uds("2024-06-01", 7)
S0501 = {"calendarDate": "2024-05-01", "sleepStartTimestampGMT": "x", "deepSleepSeconds": 5000, "lightSleepSeconds": 10000,
         "remSleepSeconds": 6000, "awakeSleepSeconds": 900}
S0503 = {"calendarDate": "2024-05-03", "sleepStartTimestampGMT": "x", "deepSleepSeconds": 1, "lightSleepSeconds": 1,
         "remSleepSeconds": 1}                                                             # sleep only: too little data
R0502_EARLY = {"calendarDate": "2024-05-02", "level": "HIGH", "score": 90, "acwrFactorPercent": 1, "timestamp": "2024-05-02T05:00:00.0",
               "feedbackLong": "long", "feedbackShort": "short"}
R0502_LATE = {"calendarDate": "2024-05-02", "level": "LOW", "score": 40, "acwrFactorPercent": 1, "timestamp": "2024-05-02T16:00:00.0",
              "feedbackLong": "long", "feedbackShort": "short"}
A1 = {"name": "Run", "activityType": "running", "duration": 1800, "distance": 5000, "avgHr": 140, "maxHr": 170,
      "calories": 300, "startTimeLocal": 1714564800000}
EXPORT = {
    UDS_A: [U0501, U0502], UDS_B: [U0601],
    SLEEP: [S0501, S0503],
    READY: [R0502_LATE, R0502_EARLY],
    ACTS: [{"summarizedActivitiesExport": [A1]}],
}
DAYS = ["2024-05-01", "2024-05-02", "2024-06-01"]            # S0503 stands alone: rejected for too little data


def _text(obj):
    return obj if isinstance(obj, str) else json.dumps(obj)


def _write_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for rel, obj in files.items():
            z.writestr(rel, _text(obj))
    return Path(path)


def _tree(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _stored_days():
    return {d: bw.read_aggregates(d) for d in bw.list_aggregate_days()}


def _content(doc):
    return {k: v for k, v in doc.items() if k != "imported_at"}


def _lines(lg):
    return [str(c.args[0]) for m in (lg.info, lg.warning, lg.error) for c in m.call_args_list]


def _put_original(raw):
    """Keeps raw as a JSON original the way the import does; returns its hash."""
    h = _sha(raw)
    bw.store_original_json(h, raw)
    return h


def _put_raw_file(name, raw):
    """Writes raw under an arbitrary <hash>.json name in bulk/source (to make a damaged original)."""
    p = cfg.BULK_SOURCE_DIR / name[:2] / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    return p


# ── The rebuild brings back what the import wrote ──────────────────────────────────────────────
with _isolated_log_env("bulk_rebuild_main") as base:
    zpath = _write_zip(base / "export.zip", EXPORT)
    imp = jimp.run_aggregates_import(zpath)
    imported = _stored_days()
    check("setup: the import wrote three days, rejected the sleep-only day, and kept the five JSON files as originals",
          imp["ok"] and sorted(imported) == DAYS and imp["insufficient_days"] == ["2024-05-03"]
          and len([n for n in bw.list_originals() if n.endswith(".json")]) == len(EXPORT))
    zpath.unlink()                                                          # the export is gone: only the originals remain
    shutil.rmtree(cfg.BULK_AGG_DIR)
    api_before = {d: _tree(d) for d in (cfg.RAW_DIR, cfg.SOURCE_DIR, cfg.SUMMARY_DIR) if d.exists()}
    store_before = _tree(cfg.BULK_DIR)
    source_before = _tree(cfg.BULK_SOURCE_DIR)

    with patch.object(rb, "log") as lg:
        pre = rb.run_aggregates_rebuild(dry_run=True)
    check("preview: ok, a preview, no error, nothing stopped", pre["ok"] and pre["dry_run"] is True and pre["error"] is None and not pre["stopped"])
    check("preview: three days would be new, the day with too little data is rejected and named, none is invalid",
          pre["days"] == {"new": 3, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and pre["rejected"] == {"invalid": 0, "insufficient": 1} and pre["insufficient_days"] == ["2024-05-03"])
    check("preview: five JSON files read, none damaged or unknown, four days found (one more than written: the rejected one)",
          (pre["files"], pre["originals"]["damaged"], pre["originals"]["unrecognised"], pre["days_found"]) == (5, 0, 0, 4))
    check("preview: nothing is written and not even the aggregates folder is created, nothing is reported as written",
          pre["written_days"] == [] and not cfg.BULK_AGG_DIR.exists() and _tree(cfg.BULK_DIR) == store_before)
    check("preview: the log says PREVIEW and that nothing is written",
          any("PREVIEW" in x and "nothing is written" in x for x in _lines(lg)))

    with patch.object(rb, "log") as lg:
        run = rb.run_aggregates_rebuild()
    check("run: ok, not a preview, three days written as new, reported sorted, as dates only",
          run["ok"] and run["dry_run"] is False and run["days"] == {"new": 3, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and run["written_days"] == DAYS)
    rebuilt = _stored_days()
    check("run: the rebuilt days are the days the import wrote — same values, same proof of origin, same window (but the time)",
          sorted(rebuilt) == DAYS and all(_content(rebuilt[d]) == _content(imported[d]) for d in DAYS))
    check("run: the proof of origin (source_files) is the same set as at the import",
          all(rebuilt[d]["source_files"] == imported[d]["source_files"] for d in DAYS))
    check("run: the day with two readiness entries took the later one (by its timestamp), as at the import",
          rebuilt["2024-05-02"]["aggregates"]["training_readiness"]["level"] == "LOW"
          and rebuilt["2024-05-02"]["aggregates"]["training_readiness"]["score"] == 40)
    check("run: the day window of the UDS entry is there again",
          rebuilt["2024-05-01"]["aggregates"]["day_window"] == _window("2024-05-01") and run["days_with_window"] == 3)
    check("run: raw/, source/ and summary/ stay untouched and the quality log is not created",
          all(_tree(d) == api_before[d] for d in api_before) and not cfg.QUALITY_LOG_FILE.exists())
    check("run: the originals are as they were (nothing added, nothing removed, not a byte or time changed)",
          _tree(cfg.BULK_SOURCE_DIR) == source_before)
    text = "\n".join(_lines(lg))
    check("run: the log names counts, dates and short hashes only — no entry name, no address",
          SECRET not in text and "@" not in text and "DI_CONNECT" not in text and "sleepData" not in text and "UDSFile" not in text)

    # again: nothing changes
    stored = _tree(cfg.BULK_DIR)
    again = rb.run_aggregates_rebuild()
    check("again: three days unchanged, nothing written, nothing reported as written",
          again["days"] == {"new": 0, "changed": 0, "unchanged": 3, "kept": 0, "failed": 0} and again["written_days"] == [])
    check("again: no name, size or modification time in the store has changed", _tree(cfg.BULK_DIR) == stored)
    pre2 = rb.run_aggregates_rebuild(dry_run=True)
    check("a preview after the run shows the same: unchanged", pre2["days"]["unchanged"] == 3 and pre2["days"]["new"] == 0)

    # an older schema number: the same files, so the day is rewritten (the purpose of the rebuild)
    for d in DAYS:
        f = cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{d}.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc["schema_version"] = 1
        doc["aggregates"].get("training_readiness", {}).pop("score", None)       # a day as the old parser wrote it
        f.write_text(json.dumps(doc), encoding="utf-8")
    pre3 = rb.run_aggregates_rebuild(dry_run=True)
    check("older schema: a preview shows the three days as changed and writes nothing",
          pre3["days"]["changed"] == 3 and pre3["written_days"] == [] and bw.read_aggregates("2024-05-02")["schema_version"] == 1)
    old3 = rb.run_aggregates_rebuild()
    after = _stored_days()
    check("older schema: the rebuild writes the three days again with the current number and the score is back",
          old3["days"]["changed"] == 3 and old3["written_days"] == DAYS
          and all(after[d]["schema_version"] == bw.AGG_SCHEMA_VERSION for d in DAYS)
          and after["2024-05-02"]["aggregates"]["training_readiness"]["score"] == 40
          and all(_content(after[d]) == _content(imported[d]) for d in DAYS))

# ── Originals that cannot be used ────────────────────────────────────────────────────────────────
with _isolated_log_env("bulk_rebuild_originals") as base:
    jimp.run_aggregates_import(_write_zip(base / "export.zip", EXPORT))
    good = _stored_days()
    shutil.rmtree(cfg.BULK_AGG_DIR)
    fit_hash = _sha(b"not a real fit file")
    bw.store_original(fit_hash, b"not a real fit file")                                          # a FIT original: not used
    _put_original(b'[{"nothing": "known"}]')                                                      # JSON of no known kind
    _put_original(b'{"a": 1}')                                                                    # JSON that is no list
    wrong_name = _sha(b"some other bytes")
    _put_raw_file(f"{wrong_name}.json", b'[{"totalSteps": 1, "uuid": "x", "calendarDate": "2024-07-01"}]')   # bytes do not match the name
    bad_json = b"{ not json"
    bad_json_hash = _sha(bad_json)
    _put_raw_file(f"{bad_json_hash}.json", bad_json)                                              # the hash is right, the content is no JSON
    unreadable_raw = json.dumps([_uds("2024-07-02", 5)]).encode("utf-8")
    unreadable_hash = _sha(unreadable_raw)
    unreadable = _put_raw_file(f"{unreadable_hash}.json", unreadable_raw)
    real_read = Path.read_bytes

    def _no_read(self, *a, **k):
        if self == unreadable:
            raise PermissionError("locked by another process")
        return real_read(self, *a, **k)

    with patch.object(Path, "read_bytes", _no_read), patch.object(rb, "log") as lg:
        res = rb.run_aggregates_rebuild()
    check("originals: the FIT file is counted and not used", res["originals"]["fit"] == 1)
    check("originals: two files of no known kind (a list with no rule, a JSON that is no list) are counted and named by a short hash",
          res["originals"]["unrecognised"] == 2 and len(res["unrecognised_files"]) == 2
          and all(len(h) == rb.SHORT_HASH for h in res["unrecognised_files"]))
    check("originals: wrong bytes for the name, no JSON and a file that cannot be read are three damaged originals, named by a short hash",
          res["originals"]["damaged"] == 3 and sorted(res["damaged_files"]) == sorted(h[:rb.SHORT_HASH] for h in (wrong_name, bad_json_hash, unreadable_hash)))
    check("originals: a damaged original makes the result not ok, but every good day is still rebuilt",
          res["ok"] is False and res["error"] is None and sorted(_stored_days()) == DAYS and res["written_days"] == DAYS
          and all(_content(_stored_days()[d]) == _content(good[d]) for d in DAYS))
    check("originals: nothing of the damaged or unknown files is stored as a day",
          "2024-07-01" not in bw.list_aggregate_days() and "2024-07-02" not in bw.list_aggregate_days())
    text = "\n".join(_lines(lg))
    check("originals: the log warns for each damaged and each unknown file by its short hash and says why",
          "does not match its name" in text and "is not JSON" in text and "cannot be read" in text and "no known kind" in text
          and all(h[:rb.SHORT_HASH] in text for h in (wrong_name, bad_json_hash, unreadable_hash)))
    check("originals: the log carries no full hash, no address and no name from the export",
          wrong_name not in text and SECRET not in text and "@" not in text)
    check("originals: the damaged files are left as they are (nothing is repaired or removed)",
          (cfg.BULK_SOURCE_DIR / wrong_name[:2] / f"{wrong_name}.json").exists() and unreadable.exists())

# ── Two different entries of one day ─────────────────────────────────────────────────────────────
with _isolated_log_env("bulk_rebuild_conflict") as base:
    raw_a = json.dumps([_uds("2024-08-01", 111)]).encode("utf-8")
    raw_b = json.dumps([_uds("2024-08-01", 222)]).encode("utf-8")
    _put_original(raw_a)
    _put_original(raw_b)
    later = raw_a if _sha(raw_a) > _sha(raw_b) else raw_b                       # the originals are read in the order of their hash
    with patch.object(rb, "log") as lg:
        res = rb.run_aggregates_rebuild()
    check("conflict: two different UDS entries of one date are counted once and warned about",
          res["conflicts"] == 1 and any("2024-08-01" in x and "uds" in x for x in _lines(lg)))
    check("conflict: the entry of the original with the larger hash (read later) is the day, the same at every run",
          bw.read_aggregates("2024-08-01")["aggregates"]["user_summary"]["totalSteps"] == json.loads(later)[0]["totalSteps"]
          and rb.run_aggregates_rebuild()["days"]["unchanged"] == 1)

# ── No originals, a stop, a failure, an unexpected error ───────────────────────────────────────
with _isolated_log_env("bulk_rebuild_empty") as base:
    for dry in (True, False):
        res = rb.run_aggregates_rebuild(dry_run=dry)
        check(f"no originals ({'preview' if dry else 'run'}): ok, nothing found, nothing created (not even bulk/)",
              res["ok"] and res["files"] == 0 and res["days_found"] == 0 and res["written_days"] == [] and not cfg.BULK_DIR.exists())

with _isolated_log_env("bulk_rebuild_stop") as base:
    jimp.run_aggregates_import(_write_zip(base / "export.zip", EXPORT))
    shutil.rmtree(cfg.BULK_AGG_DIR)
    stopped_early = rb.run_aggregates_rebuild(should_stop=lambda: True)
    check("stop while reading: stopped, nothing written, not even the aggregates folder",
          stopped_early["stopped"] is True and stopped_early["written_days"] == [] and not cfg.BULK_AGG_DIR.exists())
    calls = []

    def _after(n):
        def _s():
            calls.append(1)
            return len(calls) > n
        return _s

    mid = rb.run_aggregates_rebuild(should_stop=_after(len(EXPORT) + 1))         # five originals read, the first day passes, the second stops
    check("stop between days: the first day is written, the run says it stopped, and a rerun carries on",
          mid["stopped"] is True and mid["written_days"] == DAYS[:1] and bw.list_aggregate_days() == DAYS[:1])
    rest = rb.run_aggregates_rebuild()
    check("stop between days: the rerun writes the other two and leaves the first alone",
          rest["days"] == {"new": 2, "changed": 0, "unchanged": 1, "kept": 0, "failed": 0} and rest["written_days"] == DAYS[1:])

with _isolated_log_env("bulk_rebuild_fail") as base:
    jimp.run_aggregates_import(_write_zip(base / "export.zip", EXPORT))
    shutil.rmtree(cfg.BULK_AGG_DIR)
    with patch.object(jimp.bw, "write_aggregates", return_value=bw.FAILED):
        failed = rb.run_aggregates_rebuild()
    check("failure: a day that could not be written is counted as failed, not reported as written, the result is not ok",
          failed["days"]["failed"] == 3 and failed["written_days"] == [] and failed["ok"] is False)
    with patch.object(rb.bw, "list_originals", side_effect=RuntimeError(f"broken near {SECRET}")), patch.object(rb, "log") as lg:
        err = rb.run_aggregates_rebuild()
    check("unexpected error: reported by its type, never raised, the result is not ok, and the text of the error does not appear",
          err["ok"] is False and err["error"] == "unexpected error (RuntimeError)" and SECRET not in "\n".join(_lines(lg)))

# ── format_summary ─────────────────────────────────────────────────────────────────────────────
base_summary = rb._empty_summary(True)
lines = rb.format_summary(base_summary, dry_run=True)
check("format_summary: a preview says so, counts originals and days, and names no skipped files when there are none",
      lines[0].endswith("PREVIEW, nothing is written") and any(x.startswith("  originals:") for x in lines)
      and not any("skipped:" in x for x in lines) and not any("conflicts:" in x for x in lines))
lines = rb.format_summary({**base_summary, "originals": {"fit": 1, "damaged": 2, "unrecognised": 3, "bytes": 0}, "conflicts": 1, "stopped": True}, dry_run=False)
check("format_summary: damaged, unknown, conflicts and a stop are all said",
      any("2 damaged, 3 of no known kind" in x for x in lines) and any("conflicts:" in x for x in lines)
      and any("stopped before the end" in x for x in lines))
check("format_summary: an error is one line with the error", rb.format_summary({**base_summary, "error": "unexpected error (X)"}) ==
      ["Bulk daily values rebuild — error: unexpected error (X)"])

# ── Imports: standard library and the named project modules only ─────────────────────────────
_tree_ast = ast.parse(Path(rb.__file__).read_text(encoding="utf-8"))
_top = set()
for _n in _tree_ast.body:
    if isinstance(_n, ast.Import):
        _top |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _top.add(_n.module.split(".")[0])
_allowed_std = {"hashlib", "json", "logging", "datetime"}
_allowed_project = {"garmin_bulk_json_import", "garmin_bulk_writer", "garmin_import"}
check("module level: standard library (hashlib, json, logging, datetime) and the three named project modules only",
      _top <= _allowed_std | _allowed_project and _allowed_project <= _top)
check("garmin_config is imported only inside a function (like the writer), not at module level", "garmin_config" not in _top)
check("no print", not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree_ast)))

summary()
