#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_writer.py

Bulk store — Sole Owner of garmin_data/bulk/raw/ and garmin_data/bulk/source/ (v1.7.6).

  bulk/raw/garmin_bulk_YYYY-MM-DD.json   one JSON file per local day with named sections
  bulk/source/<xx>/<hash>.fit            the unchanged export files; <hash> is the SHA-256
                                         of the bytes in 64 lower-case hex characters,
                                         <xx> its first two characters

The store holds data from the GDPR export, apart from the API store: raw/, source/
and summary/ are never written here, and the API sync never writes here. Nothing in
a file name comes from the export's own names (those carry the e-mail address of the
account).

Mechanism, not policy: the writer stores what it is given and decides only whether
a day may be replaced. Which FIT types are kept, which days are written, and the
Dry-Run are the import's business.

Day format (schema_version 1, compact JSON):
  date, schema_version, generated_by, origin ("gdpr_export"), imported_at (local
  time, no zone), utc_offset_hours (offset at the start of the day — the one the
  series is shown with, as the broker does for API days, A6), utc_offset_end_hours,
  dst_transition, offset_source ("prev_day_end" | "neighbours"), source_files (full
  SHA-256 of every file that put a sample on the day, sorted), duplicates
  ({"same", "conflict"}), sections.intraday.heart_rate {count, values [[ms UTC, bpm]]}.
  Raise BULK_SCHEMA_VERSION when the format or the normalising rules change: the
  days are then written again from the originals.

Rules for a day (day_status / write_day)
  new        no readable file                                    -> written
  unchanged  same schema version, same set of files              -> nothing is written
  update     more files than stored, or same files, older schema -> written
  smaller    fewer files, or a set that is not a superset        -> kept: an import of
             part of an export (one inner ZIP, say) never replaces a fuller day
  newer      written by a newer schema version                   -> kept
  A damaged file (not JSON, no source_files) counts as new.

Writing: every file is written to <name>.tmp and moved with os.replace (tried up to
five times when the file is locked for a moment, see REPLACE_ATTEMPTS); the .tmp is
removed on failure; nothing here raises. Day files are flushed to disk (fsync on the
write handle); originals are not (they can be made again from the export, and fsync
would double the time of the whole import). An original that is already there with the
same size counts as present without reading it (a check of the content belongs to the
silo check).

Depends on: garmin_config (imported inside the functions, like garmin_source_writer),
stdlib. No backup, no quality-log access: the protection of the bulk store follows in
v1.7.6.2.

Public API:
  write_day(plan_day, day_samples, imported_at=None) -> "written" | "unchanged" | "kept" | "failed"
  day_status(date_str, source_files) -> "new" | "unchanged" | "update" | "smaller" | "newer"
  read_day(date_str) -> dict | None
  store_original(file_hash, data) -> "written" | "present" | "failed"
  original_present(file_hash, size) -> bool   (looks only, for a dry run)
  plan_day / day_samples are the DayPlan and DaySamples of garmin_bulk_normalizer (read by attribute).
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime

log = logging.getLogger(__name__)

BULK_SCHEMA_VERSION = 1

# On Windows a virus scanner or an indexer can hold a file that was just written for a moment;
# os.replace then fails with a sharing violation (PermissionError). It happened once in 34,384
# originals of the maintainer's export. Other errors (disk full, ...) are not retried.
REPLACE_ATTEMPTS = 5
REPLACE_PAUSE_S = 0.1
GENERATED_BY = "garmin_bulk_writer"
ORIGIN = "gdpr_export"

WRITTEN = "written"
UNCHANGED = "unchanged"
KEPT = "kept"
FAILED = "failed"
PRESENT = "present"

_HASH_RE = re.compile(r"[0-9a-f]{64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _valid_date(value):
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _day_path(date_str):
    import garmin_config as cfg
    if not _valid_date(date_str):
        return None
    return cfg.BULK_RAW_DIR / f"{cfg.BULK_FILE_PREFIX}{date_str}.json"


def _cleanup(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _replace(tmp, dst):
    """os.replace that waits a moment and tries again when the file is locked (see REPLACE_ATTEMPTS)."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE_S * (attempt + 1))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _problem(plan_day, day_samples):
    """What is wrong with the day, None if nothing is."""
    date_str = getattr(day_samples, "date", None)
    if not _valid_date(date_str):
        return "date is not a date"
    if getattr(plan_day, "date", None) != date_str:
        return "date of the plan and of the samples differ"
    files = getattr(day_samples, "source_files", None)
    if not isinstance(files, (list, tuple)) or not files:
        return "source_files is not a list with entries"
    if not all(isinstance(h, str) and _HASH_RE.fullmatch(h) for h in files):
        return "source_files holds something that is not a SHA-256"
    values = getattr(day_samples, "values", None)
    if not isinstance(values, list) or not values:
        return "no values"
    previous = None
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not _is_int(item[0]) or not _is_int(item[1]):
            return "a value is not an [ms, bpm] pair of integers"
        if item[0] <= 0 or not 1 <= item[1] <= 254:
            return "a value is out of range"
        if previous is not None and item[0] <= previous:
            return "values are not strictly ascending"
        previous = item[0]
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Days
# ══════════════════════════════════════════════════════════════════════════════

def read_day(date_str):
    """The stored day as a dict, None if there is none or it cannot be read (a damaged file is logged)."""
    path = _day_path(date_str)
    if path is None or not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning(f"  bulk_writer: could not read the day file of {date_str}: {e}")
        return None
    return doc if isinstance(doc, dict) else None


def day_status(date_str, source_files):
    """How the stored day compares with a day built from `source_files` (see the module docstring)."""
    existing = read_day(date_str)
    if existing is None:
        return "new"
    stored, version = existing.get("source_files"), existing.get("schema_version")
    if not isinstance(stored, list) or not _is_int(version):
        return "new"
    if version > BULK_SCHEMA_VERSION:
        return "newer"
    new, old = set(source_files), set(stored)
    if new == old:
        return "unchanged" if version == BULK_SCHEMA_VERSION else "update"
    if new > old:
        return "update"
    return "smaller"


def write_day(plan_day, day_samples, imported_at=None):
    """
    Writes one day unless the stored day must stay as it is.

    Parameters
    ----------
    plan_day    : DayPlan of garmin_bulk_normalizer — offsets, transition flag, source of the offset
    day_samples : DaySamples of garmin_bulk_normalizer — values, source files, duplicate counters
    imported_at : str | None — local time "YYYY-MM-DDTHH:MM:SS"; now if None

    Returns
    -------
    "written", "unchanged" (nothing touched), "kept" (smaller or newer day stays) or "failed" (non-fatal, logged)
    """
    tmp = None
    try:
        problem = _problem(plan_day, day_samples)
        if problem:
            log.warning(f"  bulk_writer.write_day: refused ({problem})")
            return FAILED
        date_str = day_samples.date
        status = day_status(date_str, day_samples.source_files)
        if status == "unchanged":
            return UNCHANGED
        if status in ("smaller", "newer"):
            log.info(f"  bulk_writer: {date_str} kept ({status} than the stored day)")
            return KEPT

        doc = {
            "date": date_str,
            "schema_version": BULK_SCHEMA_VERSION,
            "generated_by": GENERATED_BY,
            "origin": ORIGIN,
            "imported_at": imported_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "utc_offset_hours": plan_day.offset_start_hours,
            "utc_offset_end_hours": plan_day.offset_end_hours,
            "dst_transition": bool(plan_day.dst_transition),
            "offset_source": plan_day.offset_source,
            "source_files": sorted(day_samples.source_files),
            "duplicates": {"same": day_samples.duplicates_same, "conflict": day_samples.duplicates_conflict},
            "sections": {"intraday": {"heart_rate": {"count": len(day_samples.values), "values": day_samples.values}}},
        }
        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        dst = _day_path(date_str)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # not supported on every file system
        _replace(tmp, dst)
        tmp = None
        log.debug(f"  bulk_writer: {date_str} written ({len(day_samples.values)} values)")
        return WRITTEN
    except Exception as e:
        log.warning(f"  bulk_writer.write_day failed: {e}")
        if tmp is not None:
            _cleanup(tmp)
        return FAILED


# ══════════════════════════════════════════════════════════════════════════════
#  Originals
# ══════════════════════════════════════════════════════════════════════════════

def original_present(file_hash, size):
    """True if bulk/source holds the original with this hash and this size. Only looks (a dry run
    uses it): no folder and no file is created; a name that is not a SHA-256 is simply not present."""
    try:
        import garmin_config as cfg
        if not isinstance(file_hash, str) or not _HASH_RE.fullmatch(file_hash):
            return False
        return (cfg.BULK_SOURCE_DIR / file_hash[:2] / f"{file_hash}.fit").stat().st_size == size
    except OSError:
        return False


def store_original(file_hash, data):
    """
    Stores one export file as bulk/source/<first two characters>/<hash>.fit.

    The name must be the SHA-256 of the bytes in 64 lower-case hex characters (so
    it can neither be a path nor a wrong name). A file that is already there with
    the same size is present and is not read or rewritten.

    Returns
    -------
    "written", "present" or "failed" (non-fatal, logged)
    """
    tmp = None
    try:
        import garmin_config as cfg
        if not isinstance(file_hash, str) or not _HASH_RE.fullmatch(file_hash):
            log.warning("  bulk_writer.store_original: refused (name is not a SHA-256)")
            return FAILED
        if not isinstance(data, (bytes, bytearray)):
            log.warning("  bulk_writer.store_original: refused (data is not bytes)")
            return FAILED
        data = bytes(data)
        if hashlib.sha256(data).hexdigest() != file_hash:
            log.warning(f"  bulk_writer.store_original: refused (bytes do not match {file_hash[:12]})")
            return FAILED
        if original_present(file_hash, len(data)):
            return PRESENT
        dst = cfg.BULK_SOURCE_DIR / file_hash[:2] / f"{file_hash}.fit"
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_bytes(data)
        _replace(tmp, dst)
        tmp = None
        return WRITTEN
    except Exception as e:
        log.warning(f"  bulk_writer.store_original failed: {e}")
        if tmp is not None:
            _cleanup(tmp)
        return FAILED
