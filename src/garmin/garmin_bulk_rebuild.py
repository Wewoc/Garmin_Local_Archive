#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_rebuild.py

Rebuild of the bulk daily values (v1.7.6.5): builds the days in bulk/aggregates again from the JSON
originals kept in bulk/source — without the export. The import of an export (garmin_bulk_json_import)
keeps every JSON file it reads there; this module reads them back, so a change of the parser or of
the schema (AGG_SCHEMA_VERSION) reaches the days that were imported earlier, also when the export
ZIP has long been deleted.

It builds a day the way the import does, because it calls the same steps:

  garmin_import            days_from_originals — the kind of each file from its content (detect_kind),
                           the entries by date, the day (parse_day)
  garmin_bulk_json_import  store_day — validator, quality check, the day plus its day window, the proof
                           of origin (entry_hashes), write or preview
  garmin_bulk_writer       the only module that writes bulk/aggregates; a day with the same files and the
                           same schema is "unchanged", an older schema "changed", a fuller stored day is
                           "kept"

Entry point: run_aggregates_rebuild(dry_run=False, should_stop=None). Like the import it touches
neither the quality log, nor raw/, summary/ or the backup: it reports the days it wrote
(summary["written_days"]) and the days with too little data (summary["insufficient_days"]).

What a run does
  1. The JSON originals are read in the order of their hash (a fixed order, so two runs read the same
     way). A file is used only if its bytes are the SHA-256 in its name and it is JSON; any other is
     "damaged": counted, reported by the first 12 characters of its hash, skipped.
  2. FIT originals are not used (they belong to the intraday phase) and only counted.
  3. A file whose kind is not recognised by its content is counted, named by a short hash in the result
     and skipped, never guessed. Since v1.7.6.7 it is not warned about one by one: the kept originals of
     gear, personal records, courses and zones are among them (their layout is not known, so no rule
     recognises them) and would be warned about at every run.
  4. Where two originals hold different UDS or sleep entries of one date, the one read later wins and
     the day is counted in "conflicts" (none was found in the maintainer's export); readiness is chosen
     by its timestamp, not by the order.
  A rerun with nothing changed changes nothing.

Preview (dry_run=True): the same work, nothing is created or written — not even the folders.

Stop: should_stop is asked before every original and before every day. A stop while reading writes
nothing; a stop between days leaves the days written so far, a rerun carries on.

Result: a dict of numbers (and dates), see _empty_summary() — also written to the log by
format_summary(). Only counts, dates and the first 12 characters of a hash appear: the originals carry
no name from the export. "ok" is False for an error, a day that could not be written or a damaged
original; a rejected day (invalid, too little data) or a file of no known kind is no failure.

Depends on: the modules above, stdlib.
"""

import hashlib
import json
import logging
from datetime import datetime

import garmin_bulk_json_import as jimp
import garmin_bulk_writer as bw
import garmin_import as importer

log = logging.getLogger(__name__)

SHORT_HASH = 12           # characters of a hash that appear in the log and in the result


def _empty_summary(dry_run):
    summary = jimp.empty_summary(dry_run)
    summary["originals"] = {"fit": 0, "damaged": 0, "unrecognised": 0, "bytes": 0}
    summary["conflicts"] = 0
    summary["damaged_files"] = []
    summary["unrecognised_files"] = []
    return summary


def _source_dir():
    import garmin_config as cfg
    return cfg.BULK_SOURCE_DIR


def run_aggregates_rebuild(dry_run=False, should_stop=None) -> dict:
    """
    Rebuilds (or previews) the daily values from the kept JSON originals. See the module docstring.

    Parameters
    ----------
    dry_run     : bool — only compare and count, create and write nothing
    should_stop : callable() -> bool | None — asked before every original and every day

    Returns
    -------
    dict — numbers, see _empty_summary(); "ok" is False on an error, a failed day or a damaged original
    """
    summary = _empty_summary(dry_run)
    try:
        _work(dry_run, should_stop, summary)
    except Exception as e:                     # noqa: BLE001 - reported, never raised (the caller owns the run)
        summary["error"] = f"unexpected error ({type(e).__name__})"
        log.debug("  bulk rebuild: unexpected error", exc_info=True)
    summary["ok"] = (summary["error"] is None and summary["originals"]["damaged"] == 0 and summary["days"]["failed"] == 0)
    for line in format_summary(summary, dry_run):
        log.info(line)
    return summary


def _work(dry_run, should_stop, summary):
    originals = summary["originals"]
    names = sorted(bw.list_originals())
    originals["fit"] = sum(1 for n in names if n.endswith(".fit"))
    json_names = [n for n in names if n.endswith(".json")]
    source = _source_dir()

    def _damaged(short, why):
        originals["damaged"] += 1
        summary["damaged_files"].append(short)
        log.warning(f"  bulk rebuild: original {short} {why}, skipped")

    def _read_all():
        """The JSON originals as (short hash, parsed content), in the order of their hash; damaged ones are skipped."""
        for name in json_names:
            if should_stop is not None and should_stop():
                summary["stopped"] = True
                return
            short = name[:SHORT_HASH]
            try:
                raw = (source / name[:2] / name).read_bytes()
            except OSError:
                _damaged(short, "cannot be read")
                continue
            if hashlib.sha256(raw).hexdigest() != name[:-len(".json")]:
                _damaged(short, "does not match its name")
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                _damaged(short, "is not JSON")
                continue
            summary["files"] += 1
            originals["bytes"] += len(raw)
            yield short, data

    def _unrecognised(short):
        originals["unrecognised"] += 1
        summary["unrecognised_files"].append(short)
        log.debug(f"  bulk rebuild: original {short} is of no known kind, skipped")

    def _conflict(kind, date_str):
        summary["conflicts"] += 1
        log.warning(f"  bulk rebuild: {date_str} — two different {kind} entries for the day, the one read later wins "
                    f"(the originals are read in the order of their hash)")

    imported_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for day, entries in importer.days_from_originals(_read_all(), on_unrecognised=_unrecognised, on_conflict=_conflict):
        summary["days_found"] += 1
        if should_stop is not None and should_stop():
            summary["stopped"] = True
        if summary["stopped"]:
            break
        jimp.store_day(day, entries, imported_at, dry_run, summary)


def format_summary(summary, dry_run=False):
    """The summary as text lines for the log (counts and dates only, never a name from the export)."""
    if summary.get("error"):
        return [f"Bulk daily values rebuild — error: {summary['error']}"]
    orig, days, rej = summary["originals"], summary["days"], summary["rejected"]
    lines = ["Bulk daily values rebuild — PREVIEW, nothing is written" if dry_run else "Bulk daily values rebuild"]
    if summary["stopped"]:
        lines.append("  stopped before the end — a rerun carries on, nothing is done twice")
    lines.append(f"  originals: {summary['files']} JSON file(s) read ({orig['bytes'] / 1e6:.1f} MB), "
                 f"{orig['fit']} FIT file(s) not used, {summary['days_found']} day(s) found")
    if orig["damaged"] or orig["unrecognised"]:
        lines.append(f"  skipped:   {orig['damaged']} damaged, {orig['unrecognised']} of no known kind "
                     f"(this includes the kept originals of gear, records, courses and zones, which are not read)")
    lines.append(f"  days:      {days['new']} new, {days['changed']} changed, {days['unchanged']} unchanged, "
                 f"{days['kept']} kept (the stored day is fuller), {days['failed']} failed")
    if rej["invalid"] or rej["insufficient"]:
        lines.append(f"  rejected:  {rej['invalid']} invalid, {rej['insufficient']} with too little data (not stored)")
    if summary["conflicts"]:
        lines.append(f"  conflicts: {summary['conflicts']} entry(ies) replaced a different one of the same day "
                     f"(the one read later wins)")
    lines.append(f"  window:    {summary['days_with_window']} day(s) carry the export's day window")
    return lines
