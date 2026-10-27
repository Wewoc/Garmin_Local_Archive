#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_json_import.py

Daily-values phase of the bulk import (v1.7.6.1): reads the JSON files of a Garmin GDPR export
(UDS day aggregates, sleep data, training readiness, activities) and puts the values of every
day into the bulk store, bulk/aggregates — not into raw/. Orchestrates; the work is done by

  garmin_import        reads the export and builds the day (load_bulk_with_entries, parse_day)
  garmin_validator     checks a day (a critical one is not stored)
  garmin_quality       assess_quality only (a day with nothing usable is not stored)
  garmin_bulk_writer   the only module that writes bulk/aggregates and bulk/source

store_day() is the step per day (checks, aggregates, proof of origin, write or preview); the import of an
export and the rebuild from the kept originals (v1.7.6.5) both call it, so a day is built one way only.

Entry point: run_aggregates_import(path, dry_run=False, should_stop=None). It is started by
garmin_collector.main() as the "json" phase, before the intraday phase. This module touches
neither the quality log, nor raw/, summary/ or the backup: it reports the days it wrote
(summary["written_days"]) and the days with too little data (summary["insufficient_days"]);
the caller makes the summary of the written days and the quality-log entries
(garmin_collector, _finish_aggregates).

What a run does
  1. Every JSON file the importer reads is hashed (SHA-256 of the bytes) and kept as an original
     in bulk/source/<xx>/<hash>.json (a preview only asks whether it is there). The names inside
     the export carry the e-mail address of the account: they are never stored nor logged.
  2. Every day of the export is built the way the old import built it (parse_day), then
       invalid (validator "critical")      -> counted as rejected, not stored
       too little data (quality "failed")  -> counted as rejected, reported in insufficient_days,
                                              not stored (the API may still deliver the day)
       otherwise                           -> written with write_aggregates
     Written is the day as parse_day built it, plus "day_window": the four fields of the UDS
     entry that describe the day (wellnessStart/End, GMT and local). They are the second source
     of the day boundaries for the heart-rate phase (garmin_bulk_import._load_windows) and are
     not an API "stats" object, so they cannot make a day look better than it is.
  3. The proof of origin of a day (source_files in the file) is the SHA-256 of every source
     entry that went into it (UDS entry, sleep entry, readiness entry, each activity): an export
     that has more entries for a day updates it, the same entries change nothing, fewer entries
     never replace a fuller day (garmin_bulk_writer decides). A JSON file of the export holds many
     days, so the hash of the file would tell nothing about one day.
  A rerun with the same export changes nothing.

Preview (dry_run=True): the same work, nothing is created or written — not even the folders.

Stop: should_stop is asked before every day. The originals read so far are stored, the days
written stay, a rerun carries on.

Result: a dict of numbers (and dates) — see empty_summary() — also written to the log by
format_summary(). No name from the export appears anywhere; only counts.
A rejected day (invalid, or with too little data) is reported in "rejected" and is no failure:
"ok" stays true and the run ends with exit code 0, because a rerun with the same export would
reject the same day again. "ok" is false only for what a rerun can mend (an error, a day or an
original that could not be written).

Depends on: the modules above, stdlib.
"""

import copy
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

import garmin_bulk_writer as bw
import garmin_import as importer
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_validator as validator

log = logging.getLogger(__name__)

WINDOW_FIELDS = ("wellnessStartTimeGmt", "wellnessStartTimeLocal", "wellnessEndTimeGmt", "wellnessEndTimeLocal")
WINDOW_KEY = "day_window"

_STATUS_TO_KEY = {"new": "new", "update": "changed", "unchanged": "unchanged", "unreadable": "failed"}


def empty_summary(dry_run):
    return {
        "ok": False, "error": None, "dry_run": dry_run, "stopped": False,
        "files": 0, "days_found": 0,
        "originals": {"new": 0, "present": 0, "failed": 0, "bytes": 0},
        "days": {"new": 0, "changed": 0, "unchanged": 0, "kept": 0, "failed": 0},
        "rejected": {"invalid": 0, "insufficient": 0},
        "days_with_window": 0,
        "written_days": [], "insufficient_days": [],
    }


def _entry_hash(kind, entry):
    """SHA-256 of one source entry (canonical JSON, with its kind in front)."""
    text = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{kind}\0{text}".encode("utf-8")).hexdigest()


def entry_hashes(entries):
    """The sorted SHA-256 of every source entry of a day (see the module docstring)."""
    hashes = set()
    for kind in ("uds", "sleep", "readiness"):
        entry = entries.get(kind)
        if isinstance(entry, dict) and entry:
            hashes.add(_entry_hash(kind, entry))
    for activity in entries.get("activities") or []:
        if isinstance(activity, dict) and activity:
            hashes.add(_entry_hash("activity", activity))
    return sorted(hashes)


def day_window(entries):
    """The four window fields of the UDS entry as a dict, None unless all four are text."""
    uds = entries.get("uds")
    if not isinstance(uds, dict):
        return None
    window = {k: uds.get(k) for k in WINDOW_FIELDS}
    return window if all(isinstance(v, str) and v for v in window.values()) else None


def run_aggregates_import(path, dry_run=False, should_stop=None) -> dict:
    """
    Imports (or previews) the daily values of a GDPR export. See the module docstring.

    Parameters
    ----------
    path        : str | Path — the export: the ZIP or the unpacked folder
    dry_run     : bool — only compare and count, create and write nothing
    should_stop : callable() -> bool | None — asked before every day

    Returns
    -------
    dict — numbers, see empty_summary(); "ok" is False on an error or when a write failed
    """
    summary = empty_summary(dry_run)
    try:
        _work(path, dry_run, should_stop, summary)
    except FileNotFoundError:
        summary["error"] = "export path does not exist"
    except Exception as e:                     # noqa: BLE001 - reported, never raised (the caller owns the run)
        summary["error"] = f"unexpected error ({type(e).__name__})"
        log.debug("  bulk daily values: unexpected error", exc_info=True)
    summary["ok"] = (summary["error"] is None and summary["originals"]["failed"] == 0 and summary["days"]["failed"] == 0)
    for line in format_summary(summary, dry_run):
        log.info(line)
    return summary


def _work(path, dry_run, should_stop, summary):
    if not Path(path).exists():
        raise FileNotFoundError(str(path))
    originals = summary["originals"]
    seen = set()

    def _on_file(_name, data):
        """Every JSON file the importer reads: hash it, keep it (once per content). Never raises."""
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        summary["files"] += 1
        originals["bytes"] += len(data)
        if should_stop is not None and should_stop():
            summary["stopped"] = True
        if summary["stopped"]:
            return
        if dry_run:
            originals["present" if bw.original_json_present(digest, len(data)) else "new"] += 1
        else:
            result = bw.store_original_json(digest, data)
            originals[{bw.WRITTEN: "new", bw.PRESENT: "present"}.get(result, "failed")] += 1

    imported_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for day, entries in importer.load_bulk_with_entries(path, _on_file):
        summary["days_found"] += 1
        if should_stop is not None and should_stop():
            summary["stopped"] = True
        if summary["stopped"]:
            break
        store_day(day, entries, imported_at, dry_run, summary)


def store_day(day, entries, imported_at, dry_run, summary):
    """
    The step per day, shared by the import of an export and the rebuild from the kept originals:
    checks the day (validator, quality), builds its aggregates (the day plus "day_window") and the
    proof of origin (entry_hashes), then writes it with write_aggregates, or only compares in a
    preview. Counts into `summary` (see empty_summary()); never raises on a rejected day.
    """
    days, rejected = summary["days"], summary["rejected"]
    date_str = day.get("date")

    if validator.validate(day)["status"] == "critical":
        rejected["invalid"] += 1
        return
    if quality.assess_quality(normalizer.normalize(copy.deepcopy(day), source="bulk")) == "failed":
        rejected["insufficient"] += 1
        summary["insufficient_days"].append(date_str)
        return

    aggregates = dict(day)
    window = day_window(entries)
    if window is not None:
        aggregates[WINDOW_KEY] = window
        summary["days_with_window"] += 1
    source_files = entry_hashes(entries)

    status = bw.aggregates_status(date_str, source_files)
    if dry_run:
        days[_STATUS_TO_KEY.get(status, "kept")] += 1
        return
    result = bw.write_aggregates(date_str, aggregates, source_files, imported_at=imported_at)
    if result == bw.WRITTEN:
        days["new" if status == "new" else "changed"] += 1
        summary["written_days"].append(date_str)
    else:
        days[{bw.UNCHANGED: "unchanged", bw.KEPT: "kept"}.get(result, "failed")] += 1


def format_summary(summary, dry_run=False):
    """The summary as text lines for the log (counts only, never a file name)."""
    if summary.get("error"):
        return [f"Bulk daily values import — error: {summary['error']}"]
    orig, days, rej = summary["originals"], summary["days"], summary["rejected"]
    lines = ["Bulk daily values import — PREVIEW, nothing is written" if dry_run else "Bulk daily values import"]
    if summary["stopped"]:
        lines.append("  stopped before the end — a rerun carries on, nothing is done twice")
    lines.append(f"  files:     {summary['files']} JSON file(s) read, {summary['days_found']} day(s) found")
    lines.append(f"  originals: {orig['new']} new, {orig['present']} already stored, {orig['failed']} failed "
                 f"({orig['bytes'] / 1e6:.1f} MB kept in all)")
    lines.append(f"  days:      {days['new']} new, {days['changed']} changed, {days['unchanged']} unchanged, "
                 f"{days['kept']} kept (the stored day is fuller), {days['failed']} failed")
    if rej["invalid"] or rej["insufficient"]:
        lines.append(f"  rejected:  {rej['invalid']} invalid, {rej['insufficient']} with too little data "
                     f"(not stored; the API may still deliver them)")
    lines.append(f"  window:    {summary['days_with_window']} day(s) carry the export's day window")
    return lines
