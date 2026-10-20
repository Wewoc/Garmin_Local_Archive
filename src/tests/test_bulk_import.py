#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_import.py — garmin_bulk_import (v1.7.6)

Run from the project folder:
    python tests/test_bulk_import.py

The intraday phase of the bulk import: scanner -> reader -> normaliser -> writer. The export
is built here from scratch (a ZIP with two inner ZIPs and synthetic FIT files), the archive is
a few raw days that only carry the window pairs. Entry names carry a marker that stands for the
e-mail address in the names of a real export; it must never show up in the log.
"""

import ast
import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from gla_testenv import cfg, _isolated_log_env  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
import fit_builder as fb

section("B5. garmin_bulk_import (v1.7.6)")
import garmin_bulk_writer as bw
import garmin_bulk_import as imp

SECRET = "secret.name@example.invalid"


def _ts(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


def _zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _stats(day, off=1):
    m = datetime.strptime(day, "%Y-%m-%d")
    f = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.0")          # noqa: E731
    return {"wellnessStartTimeGmt": f(m - timedelta(hours=off)), "wellnessStartTimeLocal": f(m),
            "wellnessEndTimeGmt": f(m + timedelta(days=1) - timedelta(hours=off)), "wellnessEndTimeLocal": f(m + timedelta(days=1))}


def _sha(b):
    return hashlib.sha256(b).hexdigest()


class _Log:
    """Captures what the module logs, including levels the suite switches off."""
    def __init__(self):
        self.lines = []

    def __enter__(self):
        self._logger = logging.getLogger("garmin_bulk_import")
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


# ── The synthetic export ───────────────────────────────────────────────────────
T2, T3 = _ts(2024, 3, 2, 12), _ts(2024, 3, 3, 12)
mon1 = fb.monitoring_fit(T2, [(T2, 60), (T2 + 60, 62), (T2 + 120, 64)], serial=1)
mon2 = fb.monitoring_fit(T3, [(T3, 70), (T3 + 60, 72), (_ts(2024, 3, 3, 23, 30), 74)], serial=2)
mon4 = fb.monitoring_fit(_ts(2024, 3, 2, 13), [(T2 + 60, 99), (_ts(2024, 3, 2, 13), 80)], serial=4)
sleep = fb.simple_fit(49, T2, serial=5)
hrv = fb.simple_fit(68, T3, serial=6)
activity = fb.simple_fit(4, T2, serial=8)
other72 = fb.simple_fit(72, T2, serial=9)
garbage = b"this is not a FIT file at all"

part1 = _zip_bytes({f"{SECRET}_1.fit": mon1, f"{SECRET}_2.fit": mon2, f"{SECRET}_3.fit": sleep, f"{SECRET}_4.fit": activity,
                    f"{SECRET}_5.fit": garbage, "notes.txt": b"x"})
part2 = _zip_bytes({f"{SECRET}_6.fit": mon1, f"{SECRET}_7.fit": mon4, f"{SECRET}_8.fit": hrv, f"{SECRET}_9.fit": other72})
export = _zip_bytes({"DI/Up/UploadedFiles_0-_Part1.zip": part1, "DI/Up/UploadedFiles_0-_Part2.zip": part2, "customer.json": b"{}"})
KEPT = [mon1, mon2, mon4, sleep, hrv]


def _archive(days=("2024-03-01", "2024-03-02", "2024-03-03", "2024-03-04", "2024-03-05", "2024-03-06")):
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for d in days:
        (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{d}.json").write_text(json.dumps({"date": d, "stats": _stats(d)}), encoding="utf-8")


def _tree(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


with _isolated_log_env("bulk_import") as base:
    _archive()
    exp = base / "export.zip"
    exp.write_bytes(export)
    api_dirs = (cfg.RAW_DIR, cfg.SOURCE_DIR, cfg.SUMMARY_DIR)
    api_before = {d: _tree(d) for d in api_dirs if d.exists()}

    # ── Preview: nothing is written ────────────────────────────────────────────
    with _Log() as log:
        pre = imp.run_intraday_import(exp, dry_run=True)
    check("preview: ok, not stopped, no error", pre["ok"] and not pre["stopped"] and pre["error"] is None and pre["dry_run"] is True)
    check("preview: nothing is created in the bulk store (not even the folders)", not cfg.BULK_DIR.exists())
    check("preview: no day is reported as written", pre["written_days"] == [])
    check("preview: the files found: 9 FIT entries, one duplicate by content, two entries that are neither FIT nor ZIP, three ZIPs opened",
          (pre["scan"]["fit_seen"], pre["scan"]["duplicates"], pre["scan"]["ignored"], pre["scan"]["zips_opened"]) == (9, 1, 2, 3))
    check("preview: the file that is no FIT file is rejected and counted by reason", pre["rejected"] == {"not_fit": 1})
    check("preview: readable files by FIT type", pre["by_type"] == {32: 3, 49: 1, 68: 1, 4: 1, 72: 1})
    check("preview: types that are not kept (activity, other) are counted, not stored", pre["other_types"] == 2)
    check("preview: five originals would be written, none exists yet",
          (pre["originals"]["new"], pre["originals"]["present"], pre["originals"]["failed"]) == (5, 0, 0)
          and pre["originals"]["bytes"] == sum(len(b) for b in KEPT))
    check("preview: three days would be new", pre["days"] == {"new": 3, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0})
    check("preview: samples kept, none unassigned, one duplicate second with another value",
          (pre["samples"]["kept"], pre["samples"]["unassigned"], pre["samples"]["duplicates_conflict"], pre["samples"]["duplicates_same"],
           pre["samples"]["days_with_samples"]) == (8, 0, 1, 0, 3))
    check("preview: planned days, the day without a boundary and the planned days without samples",
          (pre["planned_days"], pre["unknown_days"], pre["planned_days_without_samples"])
          == (5, ["2024-03-01"], ["2024-03-05", "2024-03-06"]))
    text = "\n".join(log.lines)
    check("preview: the log says it is a preview and that nothing is written", "PREVIEW" in text and "nothing is written" in text)
    check("preview: the log names counts, no entry name", SECRET not in text and "garmin_bulk_" not in text and "@" not in text)
    check("the API store is untouched by the preview", all(_tree(d) == api_before[d] for d in api_before))

    # ── The real run ───────────────────────────────────────────────────────────
    with _Log() as log:
        run = imp.run_intraday_import(exp)
    check("run: ok and not a preview", run["ok"] and run["dry_run"] is False and run["error"] is None)
    check("run: five originals and three days written",
          run["originals"]["new"] == 5 and run["days"] == {"new": 3, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0})
    check("run: each kept original is stored under <xx>/<hash>.fit with the exact bytes",
          all((cfg.BULK_SOURCE_DIR / _sha(b)[:2] / f"{_sha(b)}.fit").read_bytes() == b for b in KEPT))
    check("run: activity, other type and the broken file are not stored",
          not any((cfg.BULK_SOURCE_DIR / _sha(b)[:2] / f"{_sha(b)}.fit").exists() for b in (activity, other72, garbage)))
    check("run: the days written are reported, sorted, as dates only", run["written_days"] == ["2024-03-02", "2024-03-03", "2024-03-04"])
    d2 = bw._load_day("2024-03-02")[1]
    check("run: day 2024-03-02 holds the samples of both overlapping files, the older file wins the conflicting second",
          [v[1] for v in d2["sections"]["intraday"]["heart_rate"]["values"]] == [60, 62, 64, 80]
          and d2["duplicates"] == {"same": 0, "conflict": 1} and d2["source_files"] == sorted([_sha(mon1), _sha(mon4)]))
    d4 = bw._load_day("2024-03-04")[1]
    check("run: a sample at 23:30Z belongs to the next local day (offset +1 h)",
          d4 is not None and d4["sections"]["intraday"]["heart_rate"]["count"] == 1 and bw._load_day("2024-03-03")[1]["sections"]["intraday"]["heart_rate"]["count"] == 2)
    check("run: no day for the days without samples and none for the day without a boundary",
          [bw._load_day(d)[1] for d in ("2024-03-01", "2024-03-05", "2024-03-06")] == [None, None, None])
    text = "\n".join(log.lines)
    check("run: the log is not marked as a preview and names no entry", "PREVIEW" not in text and SECRET not in text and "@" not in text)
    check("run: raw/, source/ and summary/ stay untouched", all(_tree(d) == api_before[d] for d in api_before))
    check("run: only bulk/raw and bulk/source appear in the bulk store",
          sorted(p.name for p in cfg.BULK_DIR.iterdir()) == ["raw", "source"])

    # ── Again: idempotent ──────────────────────────────────────────────────────
    stored = _tree(cfg.BULK_DIR)
    again = imp.run_intraday_import(exp)
    check("again: everything is present or unchanged, nothing is written",
          again["originals"]["new"] == 0 and again["originals"]["present"] == 5
          and again["days"] == {"new": 0, "changed": 0, "unchanged": 3, "kept": 0, "failed": 0})
    check("again: not a name, size or modification time in the store has changed", _tree(cfg.BULK_DIR) == stored)
    check("again: nothing is reported as written (unchanged days are not marked again)", again["written_days"] == [])
    pre2 = imp.run_intraday_import(exp, dry_run=True)
    check("a preview after the run shows the same: present and unchanged",
          pre2["originals"]["present"] == 5 and pre2["days"]["unchanged"] == 3 and pre2["days"]["new"] == 0)

    # ── Only a part of the export ──────────────────────────────────────────────
    p1 = base / "Part1.zip"
    p1.write_bytes(part1)
    part = imp.run_intraday_import(p1)
    check("part of the export: the day that would get fewer files is kept, the others stay unchanged",
          part["days"] == {"new": 0, "changed": 0, "unchanged": 2, "kept": 1, "failed": 0})
    check("part of the export: nothing in the store has changed", _tree(cfg.BULK_DIR) == stored)
    check("part of the export: a kept day is not reported as written", part["written_days"] == [])

    # ── Rebuilt from the stored originals ──────────────────────────────────────
    rebuilt = imp.run_intraday_import(cfg.BULK_SOURCE_DIR)
    check("rebuilt from the stored originals (a folder of loose files): the same days, nothing changed",
          rebuilt["days"] == {"new": 0, "changed": 0, "unchanged": 3, "kept": 0, "failed": 0} and _tree(cfg.BULK_DIR) == stored
          and rebuilt["originals"]["new"] == 0)

    # ── An older day is made fuller by a later import (changed) ──────────────
    only1 = base / "only_mon1.zip"
    only1.write_bytes(_zip_bytes({"a.fit": mon1}))
    part2_only = base / "Part2_only_mon4.zip"
    part2_only.write_bytes(_zip_bytes({"b.fit": mon4}))
    with _isolated_log_env("bulk_import_changed"):
        _archive()
        first = imp.run_intraday_import(only1)
        second = imp.run_intraday_import(exp)
    check("a later, fuller import changes the day: first the day is new, then changed",
          first["days"]["new"] == 1 and second["days"]["changed"] == 1 and second["days"]["new"] == 2)
    check("... new and changed days are both reported as written",
          first["written_days"] == ["2024-03-02"] and second["written_days"] == ["2024-03-02", "2024-03-03", "2024-03-04"])

# ── Stop ───────────────────────────────────────────────────────────────────────
with _isolated_log_env("bulk_import_stop"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)

    def _stop_after(n):
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > n
        return stop

    s1 = imp.run_intraday_import(exp, should_stop=_stop_after(3))
    check("stop while the files are read: stopped, no day written, the originals read so far are stored",
          s1["stopped"] and s1["days"] == {"new": 0, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and 0 < s1["originals"]["new"] < 5 and not (cfg.BULK_RAW_DIR.exists() and list(cfg.BULK_RAW_DIR.iterdir())))
    with _isolated_log_env("bulk_import_stop_once"):
        _archive()
        exp_once = cfg.BULK_DIR.parent / "export.zip"
        exp_once.write_bytes(export)
        seen = {"n": 0}

        def _stop_once():
            seen["n"] += 1
            return seen["n"] == 4            # says yes exactly once, then no again

        so = imp.run_intraday_import(exp_once, should_stop=_stop_once)
        check("stopped while the files are read: no day is written even if the stop request is not asked for again",
              so["stopped"] and so["days"] == {"new": 0, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
              and not (cfg.BULK_RAW_DIR.exists() and list(cfg.BULK_RAW_DIR.iterdir())) and seen["n"] == 4)
    check("stop while the files are read: no day is reported as written", s1["written_days"] == [])
    s2 = imp.run_intraday_import(exp)
    check("... a rerun completes the work (originals that exist are present)",
          not s2["stopped"] and s2["originals"]["present"] == s1["originals"]["new"] and s2["originals"]["new"] == 5 - s1["originals"]["new"]
          and s2["days"]["new"] == 3)
with _isolated_log_env("bulk_import_stop2"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    calls = {"n": 0}

    def _stop_in_days():
        calls["n"] += 1
        return calls["n"] > 9          # eight files are checked, then the first day, then the second day stops

    s3 = imp.run_intraday_import(exp, should_stop=_stop_in_days)
    check("stop between two days: the first day is written, the others are not", s3["stopped"] and s3["days"]["new"] == 1
          and len(list(cfg.BULK_RAW_DIR.glob("*.json"))) == 1)
    check("stop between two days: exactly the day that was written is reported",
          s3["written_days"] == sorted(p.stem[len(cfg.BULK_FILE_PREFIX):] for p in cfg.BULK_RAW_DIR.glob("*.json")) and len(s3["written_days"]) == 1)
    s4 = imp.run_intraday_import(exp)
    check("... the rerun reports the two days it wrote, not the first one again",
          len(s4["written_days"]) == 2 and s3["written_days"][0] not in s4["written_days"])
    check("... a rerun writes the rest and leaves the first day alone", s4["days"]["new"] == 2 and s4["days"]["unchanged"] == 1)

# ── Failures are counted, not hidden ───────────────────────────────────────────
with _isolated_log_env("bulk_import_fail"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    with patch.object(imp.bw, "store_original", return_value=bw.FAILED):
        f1 = imp.run_intraday_import(exp)
    check("originals that cannot be written: counted as failed, the run is not ok, days are still written",
          f1["originals"]["failed"] == 5 and not f1["ok"] and f1["days"]["new"] == 3)
with _isolated_log_env("bulk_import_fail2"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    with patch.object(imp.bw, "write_day", return_value=bw.FAILED):
        f2 = imp.run_intraday_import(exp)
    check("days that cannot be written: counted as failed, the run is not ok", f2["days"]["failed"] == 3 and not f2["ok"])
    check("days that cannot be written are not reported as written", f2["written_days"] == [])

    # ── Other inputs ───────────────────────────────────────────────────────────
    missing = imp.run_intraday_import(cfg.BULK_DIR.parent / "nothing_here.zip")
    check("a path that does not exist: an error in the summary, no exception, not ok",
          missing["error"] is not None and not missing["ok"] and missing["scan"]["fit_seen"] == 0)
    cut = cfg.BULK_DIR.parent / "cut.zip"
    cut.write_bytes(export[:-20])
    c = imp.run_intraday_import(cut, dry_run=True)
    check("a cut-off ZIP: counted as unreadable, no exception", c["scan"]["zips_unreadable"] == 1 and c["scan"]["fit_seen"] == 0)

with _isolated_log_env("bulk_import_empty"):
    _archive()
    empty = cfg.BULK_DIR.parent / "empty_dir"
    empty.mkdir()
    e = imp.run_intraday_import(empty)
    check("an empty folder: nothing found, ok, nothing written", e["ok"] and e["scan"]["fit_seen"] == 0 and not cfg.BULK_DIR.exists())
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    k = imp.run_intraday_import(exp, keep_types=frozenset({32}), dry_run=True)
    check("keep_types limits what is stored: only the monitoring files, the others count as other types",
          k["originals"]["new"] == 3 and k["other_types"] == 4)

# ── Register finding F-1 (fixed in v1.7.6.1): a stored day that cannot be read is neither replaced nor "kept" ──
with _isolated_log_env("bulk_import_f1"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    p1 = cfg.BULK_DIR.parent / "Part1.zip"
    p1.write_bytes(part1)
    imp.run_intraday_import(exp)
    _locked_day = cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}2024-03-02.json"
    _stored = _tree(cfg.BULK_DIR)
    _real_read_text = Path.read_text

    def _locked(self, *a, **k):
        if self == _locked_day:
            raise PermissionError("locked by another process")
        return _real_read_text(self, *a, **k)

    # Part 1 alone holds fewer files for 2024-03-02 than the stored day: without the fix that day was written smaller.
    with patch.object(Path, "read_text", _locked):
        fp = imp.run_intraday_import(p1, dry_run=True)
        check("F-1 preview: the day that cannot be read counts as failed (not as kept), the preview is not ok",
              fp["days"] == {"new": 0, "changed": 0, "unchanged": 2, "kept": 0, "failed": 1} and not fp["ok"])
        check("F-1 preview: nothing is written", _tree(cfg.BULK_DIR) == _stored)
        fr = imp.run_intraday_import(p1)
        check("F-1 run: the day that cannot be read is failed, the others stay unchanged, the run is not ok",
              fr["days"] == {"new": 0, "changed": 0, "unchanged": 2, "kept": 0, "failed": 1} and not fr["ok"] and fr["error"] is None)
        check("F-1 run: the day is not reported as written and its file is byte for byte as before",
              fr["written_days"] == [] and _tree(cfg.BULK_DIR) == _stored)
        fx = imp.run_intraday_import(exp)
        check("F-1 run: the whole export does not touch it either (failed, nothing written, no 'unexpected error')",
              fx["days"]["failed"] == 1 and fx["days"]["unchanged"] == 2 and fx["written_days"] == [] and fx["error"] is None
              and _tree(cfg.BULK_DIR) == _stored)
    fa = imp.run_intraday_import(p1)
    check("F-1: with the lock gone the same import is clean again: the smaller stand is kept, ok",
          fa["days"] == {"new": 0, "changed": 0, "unchanged": 2, "kept": 1, "failed": 0} and fa["ok"] and _tree(cfg.BULK_DIR) == _stored)

# ── A archive without the days the export covers ──────────────────────────────
with _isolated_log_env("bulk_import_noarchive"):
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    na = imp.run_intraday_import(exp)
    check("no day windows in the archive: no day can be planned, the samples are counted by UTC date, nothing is guessed",
          na["ok"] and na["planned_days"] == 0 and na["days"] == {"new": 0, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0}
          and na["samples"]["unassigned"] == 8 and set(na["samples"]["unassigned_by_date"]) == {"2024-03-02", "2024-03-03"})
    check("... but the originals are stored", na["originals"]["new"] == 5)

# ── Progress ───────────────────────────────────────────────────────────────────
with _isolated_log_env("bulk_import_progress"):
    _archive()
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    with patch.object(imp, "PROGRESS_EVERY", 2), _Log() as plog:
        imp.run_intraday_import(exp, dry_run=True)
    check("progress lines every PROGRESS_EVERY files, with the number read so far",
          [line.strip() for line in plog.lines if "files read" in line] ==
          [f"bulk intraday: {n} files read ..." for n in (2, 4, 6, 8)])

    with patch.object(imp.normalizer, "plan_days", side_effect=RuntimeError(f"broken near {SECRET}")), _Log() as elog:
        unexpected = imp.run_intraday_import(exp, dry_run=True)
    check("an unexpected error does not escape: it is in the summary, the run is not ok, and the message carries no name",
          unexpected["error"] == "unexpected error (RuntimeError)" and not unexpected["ok"]
          and SECRET not in "\n".join(elog.lines) and SECRET not in json.dumps(unexpected))

# ── The summary text ───────────────────────────────────────────────────────────
lines = imp.format_summary(pre, dry_run=True)
joined = "\n".join(lines)
check("format_summary: a list of text lines with the numbers", isinstance(lines, list) and all(isinstance(x, str) for x in lines)
      and "9 FIT files found" in joined and "5 new" in joined and "3 new" in joined)
check("format_summary: names the days without samples and without a boundary", "2024-03-05" in joined and "2024-03-01" in joined)
check("format_summary of a stopped run says so", any("stopped" in x for x in imp.format_summary({**pre, "stopped": True}, dry_run=False)))
check("format_summary of a failed path says the error", any("does not exist" in x for x in imp.format_summary(missing, dry_run=False)))

# ── Imports ────────────────────────────────────────────────────────────────────
_tree_ast = ast.parse(Path(imp.__file__).read_text(encoding="utf-8"))
_top = set()
for _n in _tree_ast.body:
    if isinstance(_n, ast.Import):
        _top |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _top.add(_n.module.split(".")[0])
_allowed_std = {"dataclasses", "logging", "datetime", "__future__"}
_allowed_project = {"garmin_bulk_export_scanner", "garmin_bulk_fit_reader", "garmin_bulk_normalizer", "garmin_bulk_writer", "garmin_writer"}
check("module level: standard library and the bulk modules only, garmin_config only inside functions",
      _top <= _allowed_std | _allowed_project and "garmin_config" not in _top)
_imported = set()
for _n in ast.walk(_tree_ast):
    if isinstance(_n, ast.Import):
        _imported |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _imported.add(_n.module.split(".")[0])
check("no print", not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree_ast)))
check("no access to the quality log, the backup or the collector (the caller marks the days, from written_days)",
      not ({"garmin_quality", "garmin_backup", "garmin_backup_source", "garmin_collector", "garmin_source_writer"} & _imported))
check("the kept FIT types are the seven decided ones", imp.KEEP_TYPES == frozenset({32, 49, 44, 68, 58, 79, 41}))

# ── The day windows: raw/stats first, the export's own window for a day without a usable one (v1.7.6.1) ───────────
_AG_H = "ab" * 32


def _agg_day(day, window=True, off=1, **extra):
    doc = {"date": day, "user_summary": {"totalSteps": 5}, **extra}
    if window:
        doc["day_window"] = _stats(day, off)
    assert bw.write_aggregates(day, doc, [_AG_H]) == bw.WRITTEN


with _isolated_log_env("bulk_import_windows"):
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}2024-03-02.json").write_text(json.dumps({"date": "2024-03-02", "stats": _stats("2024-03-02", 1)}), encoding="utf-8")
    (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}2024-03-03.json").write_text(json.dumps({"date": "2024-03-03"}), encoding="utf-8")                 # no stats
    (cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}2024-03-04.json").write_text(json.dumps({"date": "2024-03-04", "stats": {"wellnessStartTimeGmt": "x"}}), encoding="utf-8")   # unusable
    for d in ("2024-03-02", "2024-03-03", "2024-03-04", "2024-03-05"):
        _agg_day(d, off=2)                                           # the export's window says +2 h
    _agg_day("2024-03-06", window=False)                            # no window in the export
    (cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}2024-03-07.json").write_text("{ not json", encoding="utf-8")    # damaged
    w = imp._load_windows()
    check("windows: a usable raw/stats wins over the window of the export (+1 h from raw, not +2 h from the export)",
          w["2024-03-02"] == _stats("2024-03-02", 1))
    check("windows: a raw file without stats and one with an unusable stats take the window of the export",
          w["2024-03-03"] == _stats("2024-03-03", 2) and w["2024-03-04"] == _stats("2024-03-04", 2))
    check("windows: a day that has no raw file at all takes the window of the export", w["2024-03-05"] == _stats("2024-03-05", 2))
    check("windows: an aggregates file without a window, a damaged one and a day nobody knows add nothing",
          "2024-03-06" not in w and "2024-03-07" not in w and "2024-03-08" not in w)
    check("windows: the raw day without any usable window is listed with its (unusable) stats only when the export has none either",
          set(w) == {"2024-03-02", "2024-03-03", "2024-03-04", "2024-03-05"})

# a fresh archive: no raw files at all, only the daily values with their windows -> the heart-rate phase plans the days
with _isolated_log_env("bulk_import_fresh"):
    exp = cfg.BULK_DIR.parent / "export.zip"
    exp.write_bytes(export)
    for d in ("2024-03-01", "2024-03-02", "2024-03-03", "2024-03-04", "2024-03-05", "2024-03-06"):
        _agg_day(d)
    check("fresh archive: no raw/ folder at all", not cfg.RAW_DIR.exists())
    fresh = imp.run_intraday_import(exp)
    check("fresh archive: the heart-rate phase plans the days from the windows of the export and writes the three days with samples",
          fresh["ok"] and fresh["planned_days"] == 5 and fresh["days"]["new"] == 3 and fresh["unknown_days"] == ["2024-03-01"]
          and fresh["written_days"] == ["2024-03-02", "2024-03-03", "2024-03-04"])
    check("fresh archive: the series are the same as with the windows from raw/stats (day 2024-03-02 holds the samples of both overlapping files)",
          [v[1] for v in bw._load_day("2024-03-02")[1]["sections"]["intraday"]["heart_rate"]["values"]] == [60, 62, 64, 80]
          and bw._load_day("2024-03-04")[1]["sections"]["intraday"]["heart_rate"]["count"] == 1)

summary()
