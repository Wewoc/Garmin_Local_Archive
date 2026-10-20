#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_import.py

Intraday phase of the bulk import (v1.7.6): reads the FIT files of a Garmin GDPR export and
puts the heart-rate series into the bulk store. Orchestrates; the work is done by

  garmin_bulk_export_scanner   finds the .fit files (ZIP in ZIP or folder), hashes them
  garmin_bulk_fit_reader       turns the bytes of one file into messages
  garmin_bulk_normalizer       day boundaries, 16-bit timestamps, samples per day
  garmin_bulk_writer           the only module that writes bulk/raw/ and bulk/source/

Entry point: run_intraday_import(path, dry_run=False, should_stop=None, keep_types=KEEP_TYPES).
It is started by garmin_collector.main() after the JSON phase (the day windows come from
raw/stats of the archive and, for a day without a usable one, from the window the JSON phase
stored with the day's values in bulk/aggregates); the caller pauses the
timer. This module does not touch the quality log, the backup or the API store. It reports
the days it wrote (summary["written_days"], dates only); the caller marks them in the quality
log (garmin_collector, record_bulk_intraday).

What a run does
  1. Day windows from raw/stats of the archive, or, for a day without a usable one, from the
     export's own window (bulk/aggregates, stored by the daily-values phase) -> the local days
     (garmin_bulk_normalizer).
  2. Every .fit file of the export, once per content: read; an unreadable file is counted by
     reason and goes no further. A readable file of a kept type is stored as an original; a
     monitoring file (type 32) also puts its heart-rate samples on the days.
  3. Then every day with samples is written. A day is replaced only by a fuller one; a
     day with the same files stays as it is (see garmin_bulk_writer).
  A rerun with the same export changes nothing; a part of an export never shrinks a day.

Preview (dry_run=True): the same work, but nothing is created or written — not even the
folders. Originals and days are only compared with what is stored.

Stop: should_stop is asked once for every file and once before every day. Stopped while
the files are read: no day is written, the originals read so far are stored. Stopped between
two days: the days written stay. A rerun carries on, nothing is done twice.

Result: a dict of numbers (and dates of days without data or written) — see _empty_summary(). It is
also written to the log by format_summary(). No entry name of the export appears anywhere
(they carry the e-mail address of the account); only counts.

The kept FIT types are the seven the maintainer decided on (E26): monitoring 32, sleep 49,
44, HRV 68, 58, 79, 41. Activities (4, FIT pipeline v1.8) and the single files of other types
are counted and not stored.

Depends on: the four bulk modules above, garmin_writer (read_raw, to read the day windows),
garmin_config (inside the functions), stdlib.
"""

import dataclasses
import logging
from datetime import datetime

import garmin_bulk_export_scanner as scanner
import garmin_bulk_fit_reader as reader
import garmin_bulk_normalizer as normalizer
import garmin_bulk_writer as bw
import garmin_writer as writer

log = logging.getLogger(__name__)

KEEP_TYPES = frozenset({32, 49, 44, 68, 58, 79, 41})
PROGRESS_EVERY = 2000


def _empty_summary(dry_run):
    return {
        "ok": False, "error": None, "dry_run": dry_run, "stopped": False,
        "scan": dataclasses.asdict(scanner.ScanStats()), "rejected": {}, "by_type": {}, "other_types": 0,
        "originals": {"new": 0, "present": 0, "failed": 0, "bytes": 0},
        "days": {"new": 0, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0},
        "samples": {"kept": 0, "unassigned": 0, "unassigned_by_date": {}, "duplicates_same": 0,
                    "duplicates_conflict": 0, "days_with_samples": 0},
        "planned_days": 0, "unknown_days": [], "planned_days_without_samples": [],
        "written_days": [],
    }


def _load_windows():
    """
    {date: window} of every day the archive knows (the day windows): the raw/stats of the days
    that have a raw file; a day whose raw file has no usable window — or that has no raw file at
    all — gets the window the daily-values phase took from the export (bulk/aggregates,
    "day_window", v1.7.6.1). The API's window always wins where it is usable.
    """
    import garmin_config as cfg
    windows = {}
    if cfg.RAW_DIR.exists():
        prefix = cfg.RAW_FILE_PREFIX
        for path in cfg.RAW_DIR.glob(f"{prefix}*.json"):
            date_str = path.stem[len(prefix):]
            windows[date_str] = writer.read_raw(date_str).get("stats")
    for date_str in bw.list_aggregate_days():
        if normalizer.has_window(windows.get(date_str)):
            continue
        doc = bw.read_aggregates(date_str)
        window = ((doc or {}).get("aggregates") or {}).get("day_window")
        if isinstance(window, dict):
            windows[date_str] = window
    return windows


def run_intraday_import(path, dry_run=False, should_stop=None, keep_types=KEEP_TYPES) -> dict:
    """
    Imports (or previews) the heart-rate series of a GDPR export. See the module docstring.

    Parameters
    ----------
    path        : str | Path — the export: the whole ZIP, a folder, one inner ZIP or a single .fit file
    dry_run     : bool — only compare and count, create and write nothing
    should_stop : callable() -> bool | None — asked once per file and once per day
    keep_types  : set of FIT file types whose originals are stored

    Returns
    -------
    dict — numbers, see _empty_summary(); "ok" is False on an error or when a write failed
    """
    summary = _empty_summary(dry_run)
    try:
        _work(path, dry_run, should_stop, keep_types, summary)
    except FileNotFoundError:
        summary["error"] = "export path does not exist"
    except Exception as e:                     # noqa: BLE001 - reported, never raised (the caller owns the run)
        summary["error"] = f"unexpected error ({type(e).__name__})"
        log.debug("  bulk intraday: unexpected error", exc_info=True)
    summary["ok"] = (summary["error"] is None and summary["originals"]["failed"] == 0 and summary["days"]["failed"] == 0)
    for line in format_summary(summary, dry_run):
        log.info(line)
    return summary


def _work(path, dry_run, should_stop, keep_types, summary):
    plan = normalizer.plan_days(_load_windows())
    summary["planned_days"] = len(plan.days)
    summary["unknown_days"] = list(plan.unknown)
    collector = normalizer.SampleCollector(plan)
    scan_stats = scanner.ScanStats()
    files = scanner.iter_fit_files(path, scan_stats)          # raises FileNotFoundError for a missing path

    originals, rejected, by_type = summary["originals"], summary["rejected"], summary["by_type"]
    read = 0
    for digest, data in files:
        if should_stop is not None and should_stop():
            summary["stopped"] = True
            break
        read += 1
        if read % PROGRESS_EVERY == 0:
            log.info(f"  bulk intraday: {read} files read ...")
        try:
            fit = reader.parse_fit(data, {55})
        except reader.FitFormatError as e:
            rejected[e.reason] = rejected.get(e.reason, 0) + 1
            continue
        by_type[fit.file_type] = by_type.get(fit.file_type, 0) + 1
        if fit.file_type == 32:
            collector.add_file(digest, fit.time_created, fit.messages.get(55, []))
        if fit.file_type not in keep_types:
            summary["other_types"] += 1
            continue
        originals["bytes"] += len(data)
        if dry_run:
            originals["present" if bw.original_present(digest, len(data)) else "new"] += 1
        else:
            result = bw.store_original(digest, data)
            originals[{bw.WRITTEN: "new", bw.PRESENT: "present"}.get(result, "failed")] += 1
    summary["scan"] = dataclasses.asdict(scan_stats)

    if not summary["stopped"]:
        imported_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for day in collector.iter_days():
            if should_stop is not None and should_stop():
                summary["stopped"] = True
                break
            status = bw.day_status(day.date, day.source_files)
            if dry_run:
                key = {"new": "new", "update": "changed", "unchanged": "unchanged", "unreadable": "failed"}.get(status, "kept")
            else:
                result = bw.write_day(plan.days[day.date], day, imported_at=imported_at)
                if result == bw.WRITTEN:
                    key = "new" if status == "new" else "changed"
                    summary["written_days"].append(day.date)
                else:
                    key = {bw.UNCHANGED: "unchanged", bw.KEPT: "kept"}.get(result, "failed")
            summary["days"][key] += 1

    stats = collector.stats()
    summary["samples"] = {"kept": stats.samples_kept, "unassigned": stats.unassigned,
                          "unassigned_by_date": stats.unassigned_by_date, "duplicates_same": stats.duplicates_same,
                          "duplicates_conflict": stats.duplicates_conflict, "days_with_samples": stats.days_with_samples}
    summary["planned_days_without_samples"] = stats.planned_days_without_samples


def _dates(dates, limit=5):
    shown = ", ".join(dates[:limit])
    return shown + (f", ... ({len(dates)} in all)" if len(dates) > limit else "")


def format_summary(summary, dry_run=False):
    """The summary as text lines for the log (counts only, never a file name)."""
    if summary.get("error"):
        return [f"Bulk intraday import — error: {summary['error']}"]
    scan, orig, days, smp = summary["scan"], summary["originals"], summary["days"], summary["samples"]
    lines = ["Bulk intraday import — PREVIEW, nothing is written" if dry_run else "Bulk intraday import"]
    if summary["stopped"]:
        lines.append("  stopped before the end — a rerun carries on, nothing is done twice")
    rejected = sum(summary["rejected"].values())
    reasons = ", ".join(f"{k}: {v}" for k, v in sorted(summary["rejected"].items()))
    lines.append(f"  files:     {scan.get('fit_seen', 0)} FIT files found, {scan.get('duplicates', 0)} duplicate content, "
                 f"{rejected} unreadable" + (f" ({reasons})" if rejected else "")
                 + f", {summary['other_types']} of other types (not stored)")
    if scan.get("zips_unreadable") or scan.get("oversize") or scan.get("unreadable_entries") or scan.get("too_deep"):
        lines.append(f"  skipped:   {scan.get('zips_unreadable', 0)} unreadable ZIP(s), {scan.get('unreadable_entries', 0)} damaged entries, "
                     f"{scan.get('oversize', 0)} too large, {scan.get('too_deep', 0)} nested too deep")
    lines.append(f"  originals: {orig['new']} new, {orig['present']} already stored, {orig['failed']} failed "
                 f"({orig['bytes'] / 1e6:.1f} MB kept in all)")
    lines.append(f"  days:      {days['new']} new, {days['changed']} changed, {days['unchanged']} unchanged, "
                 f"{days['kept']} kept (the stored day is fuller), {days['failed']} failed")
    lines.append(f"  samples:   {smp['kept']} heart-rate samples, {smp['unassigned']} not assigned to a day, "
                 f"{smp['duplicates_conflict']} duplicate second(s) with another value, {smp['duplicates_same']} with the same value")
    if summary["unknown_days"]:
        lines.append(f"  note:      {len(summary['unknown_days'])} day(s) without a known day boundary, no samples for them: "
                     f"{_dates(summary['unknown_days'])}")
    if smp["unassigned"]:
        lines.append(f"  note:      samples without a day on: {_dates(sorted(smp['unassigned_by_date']))}")
    if summary["planned_days_without_samples"]:
        lines.append(f"  note:      {len(summary['planned_days_without_samples'])} day(s) of the archive without samples in this export: "
                     f"{_dates(summary['planned_days_without_samples'])}")
    return lines
