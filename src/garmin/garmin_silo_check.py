#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin/garmin_silo_check.py
Garmin Local Archive — Silo-Reconciliation-Check

Read-only drift detection across the data silos.
Surfaces inconsistencies that the live pipeline does not catch on its own:
old drift (pre-existing gaps), manual file operations, interrupted runs,
import errors.

Principle: a missing silo is a defect only if it can be reconstructed from raw.
raw is the canonical truth.

Covered checks (reconstructability principle — KONZEPT §3):
  #1  raw without quality_log entry      (orphan — processed but not logged)
  #3  source without raw                 (raw rebuildable from existing source)
  #5  summary without raw or export data (orphan summary — source raw gone)
  #7  raw or export data without summary (derived file missing — rebuildable)
  #8  bulk file lost                     (v1.7.6.2: the quality log marks the day as one with
                                          bulk data — entry["bulk"]["intraday"] / ["aggregates"] —
                                          and the file is missing from the bulk store; restorable
                                          from the backup, not from raw)
  #9  original missing                   (v1.7.6.2: an intraday day file names a FIT file in its
                                          source_files that bulk/source does not hold; restorable
                                          from the backup)

"Export data" (v1.7.6.1): a day with a file in the bulk store's aggregates folder
(bulk/aggregates). Such a day may have no raw file at all — its summary is derived from
the export's values (garmin_writer.rebuild_summary) — so it is neither an orphan (#5) nor
fine without a summary (#7). The four categories keep their names and keys.

A day whose aggregates file is lost (#8) is not an orphan either (F-10, v1.7.6.2): its
summary is the last copy of the resolved export values and must not be removed (#5) — the
repair restores the file instead. The check looks at file names and at the marks of the
quality log only; a damaged file is not detected, and a day without a quality-log entry has
no mark.

#9 reads every intraday day file for its source_files (nothing else is read) and compares the
hashes with the names in bulk/source. It covers the FIT originals of the intraday days only:
the source_files of an aggregates file are hashes of single entries of the export's JSON files,
so a lost JSON original cannot be told from them.

Not covered:
  #2  quality_log entry without raw      — owned by garmin_backup.check_raw_integrity()
  #4  raw without source                 — source absence is never a defect (§2a)
  #6  source_api_log without source      — same logic, not actionable

Leaf-Node: imports only garmin_config + stdlib.
No writes. No imports of write modules. No API calls.

Public API:
  check_silos() -> dict
"""

import json
import logging
import re
from datetime import date, datetime, timezone

import garmin_config as cfg

log = logging.getLogger(__name__)

# Filename prefixes — must match garmin_config / garmin_writer conventions
_RAW_PREFIX     = "garmin_raw_"
_SUMMARY_PREFIX = "garmin_"
_SOURCE_PREFIX  = "garmin_source_"

_HASH_RE     = re.compile(r"[0-9a-f]{64}")
_FIT_NAME_RE = re.compile(r"[0-9a-f]{64}\.fit")


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _extract_date(stem: str, prefix: str) -> date | None:
    """
    Extracts a date from a file stem by stripping prefix.
    Returns None on any parse failure — no exception propagation.
    Inline implementation: garmin_silo_check is a Leaf-Node and cannot import
    garmin_utils. Logic mirrors garmin_utils.extract_date_from_filename().
    """
    try:
        return date.fromisoformat(stem.replace(prefix, "", 1))
    except (ValueError, AttributeError):
        return None


def _collect_raw_dates() -> set[date]:
    """Returns the set of dates with a garmin_raw_*.json file in RAW_DIR."""
    result: set[date] = set()
    if not cfg.RAW_DIR.exists():
        return result
    for f in cfg.RAW_DIR.glob(f"{_RAW_PREFIX}*.json"):
        d = _extract_date(f.stem, _RAW_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_summary_dates() -> set[date]:
    """Returns the set of dates with a garmin_*.json file in SUMMARY_DIR.
    Excludes non-date stems (e.g. garmin_dataformat.json) via ValueError on parse."""
    result: set[date] = set()
    if not cfg.SUMMARY_DIR.exists():
        return result
    for f in cfg.SUMMARY_DIR.glob(f"{_SUMMARY_PREFIX}*.json"):
        d = _extract_date(f.stem, _SUMMARY_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_dates_in(folder, prefix: str) -> set[date]:
    """Returns the set of dates of the <prefix><date>.json files in folder — file names only,
    nothing is read; an absent folder gives the empty set."""
    result: set[date] = set()
    if not folder.exists():
        return result
    for f in folder.glob(f"{prefix}*.json"):
        d = _extract_date(f.stem, prefix)
        if d is not None:
            result.add(d)
    return result


def _collect_aggregate_dates() -> set[date]:
    """Returns the set of dates with a file in the bulk store's aggregates folder (v1.7.6.1).
    Inline like the other collectors (Leaf Node: no import of garmin_bulk_writer); looks at
    the file names only, nothing is read."""
    return _collect_dates_in(cfg.BULK_AGG_DIR, cfg.BULK_AGG_FILE_PREFIX)


def _collect_bulk_day_dates() -> set[date]:
    """Returns the set of dates with a file in the bulk store's intraday folder (v1.7.6.2),
    from the file names only."""
    return _collect_dates_in(cfg.BULK_RAW_DIR, cfg.BULK_FILE_PREFIX)


def _collect_bulk_marks() -> tuple[set[date], set[date]]:
    """
    Returns (days marked with entry["bulk"]["intraday"], days marked with
    entry["bulk"]["aggregates"]) from quality_log.json (v1.7.6.2): the days the log says have
    bulk data in the store. A mark is any non-empty value, as in quality's unmarked_bulk_days.
    (empty, empty) if the log is missing or cannot be read — _collect_quality_dates() has
    warned about that already. Reads without QUALITY_LOCK, like it.
    """
    intraday: set[date] = set()
    aggregates: set[date] = set()
    if not cfg.QUALITY_LOG_FILE.exists():
        return intraday, aggregates
    try:
        days = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8")).get("days", [])
        for entry in days:
            bulk = entry.get("bulk") if isinstance(entry, dict) else None
            if not isinstance(bulk, dict):
                continue
            try:
                day = date.fromisoformat(entry.get("date"))
            except (TypeError, ValueError):
                continue
            if bulk.get("intraday"):
                intraday.add(day)
            if bulk.get("aggregates"):
                aggregates.add(day)
    except (OSError, ValueError, AttributeError) as e:
        log.debug("garmin_silo_check: could not read the bulk marks: %s", e)
        return set(), set()
    return intraday, aggregates


def _collect_original_refs() -> set[str]:
    """
    Returns the SHA-256 hashes named in `source_files` of the intraday day files (bulk/raw,
    v1.7.6.2): the FIT files each day was made from, which the store keeps as
    bulk/source/<xx>/<hash>.fit. Reads every day file, one at a time, and keeps only the hashes;
    a file that is damaged, unreadable or not an object contributes nothing, and an entry that
    is no SHA-256 is skipped.
    Not for the aggregates files: their source_files are hashes of single entries of the
    export's JSON files, not of the files kept in bulk/source.
    """
    refs: set[str] = set()
    folder = cfg.BULK_RAW_DIR
    if not folder.exists():
        return refs
    for f in folder.glob(f"{cfg.BULK_FILE_PREFIX}*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug("garmin_silo_check: could not read %s for its source files: %s", f.name, e)
            continue
        files = doc.get("source_files") if isinstance(doc, dict) else None
        if isinstance(files, list):
            refs.update(h for h in files if isinstance(h, str) and _HASH_RE.fullmatch(h))
    return refs


def _collect_original_fit_hashes() -> set[str]:
    """Returns the hashes of the originals kept as bulk/source/<xx>/<hash>.fit (v1.7.6.2), from
    the file names only: a name has to be a SHA-256 plus ".fit" and start with its folder's two
    characters (as the bulk writer's list_originals, which a Leaf Node cannot import)."""
    names: set[str] = set()
    folder = cfg.BULK_SOURCE_DIR
    if not folder.exists():
        return names
    for sub in folder.iterdir():
        if not sub.is_dir():
            continue
        for f in sub.iterdir():
            if _FIT_NAME_RE.fullmatch(f.name) and f.name[:2] == sub.name:
                names.add(f.name[:-len(".fit")])
    return names


def _collect_source_dates() -> set[date]:
    """Returns the set of dates with a garmin_source_*.json file in SOURCE_DIR."""
    result: set[date] = set()
    if not cfg.SOURCE_DIR.exists():
        return result
    for f in cfg.SOURCE_DIR.glob(f"{_SOURCE_PREFIX}*.json"):
        d = _extract_date(f.stem, _SOURCE_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_quality_dates() -> tuple[set[date], int]:
    """
    Reads quality_log.json and returns:
      - set of dates that have an entry (any quality label)
      - total count of entries (len(data["days"]))
    Returns (empty set, 0) if the file is missing or unreadable.
    Reads without acquiring QUALITY_LOCK — atomic writes (os.replace) guarantee
    a complete file is always visible to readers (§9a).
    """
    result: set[date] = set()
    count = 0
    if not cfg.QUALITY_LOG_FILE.exists():
        return result, count
    try:
        data = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        days = data.get("days", [])
        count = len(days)
        for entry in days:
            date_str = entry.get("date")
            if not date_str:
                continue
            try:
                result.add(date.fromisoformat(date_str))
            except ValueError:
                pass
    except (OSError, json.JSONDecodeError) as e:
        log.warning("garmin_silo_check: could not read quality_log.json: %s", e)
    return result, count


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def check_silos() -> dict:
    """
    Read-only drift detection across the data silos.

    Returns a dict with six finding lists, totals, counts, and a timestamp:

    {
      "raw_without_quality":  [date, ...],   # #1 — orphan raw, no quality_log entry
      "source_without_raw":   [date, ...],   # #3 — source file without matching raw
      "summary_without_raw":  [date, ...],   # #5 — orphan summary: no raw, no export data, and the
                                             #      log does not mark the day as having export data
      "raw_without_summary":  [date, ...],   # #7 — raw or export data exists, summary missing
      "bulk_lost_intraday":   [date, ...],   # #8 — marked bulk.intraday in the log, file missing
      "bulk_lost_aggregates": [date, ...],   # #8 — marked bulk.aggregates in the log, file missing
      "bulk_originals_missing": [str, ...],  # #9 — SHA-256 (sorted) named by an intraday day file, no .fit in bulk/source
      "checked_at":           "ISO-8601",
      "totals": {
        "raw":          int,   # count of garmin_raw_*.json files
        "summary":      int,   # count of garmin_*.json files in SUMMARY_DIR
        "source":       int,   # count of garmin_source_*.json files
        "aggregates":   int,   # count of garmin_bulk_agg_*.json files (v1.7.6.1)
        "quality_days": int,   # len(quality_log["days"])
      },
      "counts": {
        "raw_without_quality": int,
        "source_without_raw":  int,
        "summary_without_raw": int,
        "raw_without_summary": int,
        "bulk_lost_intraday":  int,
        "bulk_lost_aggregates": int,
        "bulk_originals_missing": int,
      },
    }

    Check #2 (quality_log entry without raw) is owned by
    garmin_backup.check_raw_integrity() and is not included here (Option C).
    """
    log.debug("garmin_silo_check: starting silo check")

    raw_dates     = _collect_raw_dates()
    summary_dates = _collect_summary_dates()
    source_dates  = _collect_source_dates()
    aggregate_dates = _collect_aggregate_dates()
    quality_dates, quality_count = _collect_quality_dates()

    # ── #1: raw without quality_log entry ─────────────────────────────────────
    raw_without_quality = sorted(raw_dates - quality_dates)

    # ── #3: source without raw ─────────────────────────────────────────────────
    source_without_raw = sorted(source_dates - raw_dates)

    # ── #8: bulk file lost — the log marks the day, the file is not in the store ──
    marked_intraday, marked_aggregates = _collect_bulk_marks()
    bulk_lost_intraday   = sorted(marked_intraday - _collect_bulk_day_dates())
    bulk_lost_aggregates = sorted(marked_aggregates - aggregate_dates)

    # ── #9: original missing — named by an intraday day file, not in bulk/source ──
    bulk_originals_missing = sorted(_collect_original_refs() - _collect_original_fit_hashes())

    # ── #5: summary without raw (and without export data) ──────────────────────
    # A day whose aggregates file is lost is not an orphan (F-10): its summary holds the
    # export values, and the repair restores the file (#8) instead of removing the summary.
    summary_without_raw = sorted(summary_dates - raw_dates - aggregate_dates - set(bulk_lost_aggregates))

    # ── #7: raw (or export data) without summary ───────────────────────────────
    raw_without_summary = sorted((raw_dates | aggregate_dates) - summary_dates)

    checked_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = {
        "raw_without_quality": raw_without_quality,
        "source_without_raw":  source_without_raw,
        "summary_without_raw": summary_without_raw,
        "raw_without_summary": raw_without_summary,
        "bulk_lost_intraday":   bulk_lost_intraday,
        "bulk_lost_aggregates": bulk_lost_aggregates,
        "bulk_originals_missing": bulk_originals_missing,
        "checked_at": checked_at,
        "totals": {
            "raw":          len(raw_dates),
            "summary":      len(summary_dates),
            "source":       len(source_dates),
            "aggregates":   len(aggregate_dates),
            "quality_days": quality_count,
        },
        "counts": {
            "raw_without_quality": len(raw_without_quality),
            "source_without_raw":  len(source_without_raw),
            "summary_without_raw": len(summary_without_raw),
            "raw_without_summary": len(raw_without_summary),
            "bulk_lost_intraday":   len(bulk_lost_intraday),
            "bulk_lost_aggregates": len(bulk_lost_aggregates),
            "bulk_originals_missing": len(bulk_originals_missing),
        },
    }

    total_findings = sum(result["counts"].values())
    log.debug(
        "garmin_silo_check: done — raw=%d, summary=%d, source=%d, "
        "quality_days=%d, findings=%d",
        len(raw_dates), len(summary_dates), len(source_dates),
        quality_count, total_findings,
    )

    return result
