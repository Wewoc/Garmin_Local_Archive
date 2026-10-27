#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_writer.py

Bulk store — Sole Owner of garmin_data/bulk/raw/, bulk/aggregates/ and bulk/source/ (v1.7.6).

  bulk/raw/garmin_bulk_YYYY-MM-DD.json   one JSON file per local day with named sections
                                         (the intraday series, v1.7.6)
  bulk/aggregates/garmin_bulk_agg_YYYY-MM-DD.json
                                         one JSON file per local day with the day values of the
                                         export (v1.7.6.1): a file of its own, so that a write
                                         of one kind never touches the other
  bulk/source/<xx>/<hash>.fit|.json      the unchanged export files; <hash> is the SHA-256
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

Aggregates file (schema_version 2, compact JSON, AGG_SCHEMA_VERSION; 1 = before v1.7.6.5, the
  training readiness "score" was not read): date, schema_version,
  generated_by, origin, imported_at, source_files (SHA-256 of every source entry of the export
  that went into the day — UDS, sleep, readiness, each activity; not of the JSON files kept in
  bulk/source, which hold many days; sorted), aggregates (the day's values as
  garmin_import.parse_day delivers them).
  The rules below apply to it in the same way (aggregates_status / write_aggregates); _compare()
  is the one place that decides unchanged / update / smaller / newer for both kinds.

Rules for a day (day_status / write_day)
  new        no readable file                                    -> written
  unchanged  same schema version, same set of files              -> nothing is written
  update     more files than stored, or same files, older schema -> written
  smaller    fewer files, or a set that is not a superset        -> kept: an import of
             part of an export (one inner ZIP, say) never replaces a fuller day
  newer      written by a newer schema version                   -> kept
  unreadable the file cannot be read for an I/O reason (a lock, no  -> failed: the day is
             access); it may be fine and fuller than the new stand     not touched
  A damaged file (not JSON, no source_files) counts as new: the new write is the repair.
  An unreadable one does not (register finding F-1, fixed in v1.7.6.1): it is never replaced
  by itself; a lock that goes away again is made good by running the import again, a file that
  stays unreadable has to be deleted by hand before the day can be imported again.

Writing: every file is written to <name>.tmp and moved with os.replace (tried up to
five times when the file is locked for a moment, see REPLACE_ATTEMPTS); the .tmp is
removed on failure; nothing here raises. Day files are flushed to disk (fsync on the
write handle); originals are not (they can be made again from the export, and fsync
would double the time of the whole import). An original that is already there with the
same size counts as present without reading it (a check of the content belongs to the
silo check).

A day or aggregates file of another archive (the mirror import, v1.7.6.2) is taken over by
import_day_file(): the bytes are checked against what the broker needs of such a file (a file
that fails the check is refused, it would only be ignored with a warning when read), the same
rules as above decide whether it replaces a stored one (never a smaller stand over a fuller
one; a schema version newer than this program knows is not stored), and what is written is the
bytes as they came, so the provenance of the other archive stays.

Depends on: garmin_config (imported inside the functions, like garmin_source_writer),
stdlib. No backup, no quality-log access: the backup of the bulk store is
garmin_backup_bulk.py's (v1.7.6.2).

Public API:
  write_day(plan_day, day_samples, imported_at=None) -> "written" | "unchanged" | "kept" | "failed"
  day_status(date_str, source_files) -> "new" | "unchanged" | "update" | "smaller" | "newer" | "unreadable"
  list_days() -> list[str]   (dates of the day files, from the file names only; looks, reads nothing)
  write_aggregates(date_str, aggregates, source_files, imported_at=None) -> "written" | "unchanged" | "kept" | "failed"
  aggregates_status(date_str, source_files) -> "new" | "unchanged" | "update" | "smaller" | "newer" | "unreadable"
  read_aggregates(date_str) -> dict | None
  load_aggregates(date_str) -> (state, dict | None)   state: "missing" | "damaged" | "unreadable" | "ok"
  list_aggregate_days() -> list[str]   (dates of the aggregates files, from the file names only)
  store_original(file_hash, data, suffix=".fit") -> "written" | "present" | "failed"
  store_original_json(file_hash, data) -> the same for a JSON file of the export
  original_present(file_hash, size, suffix=".fit") -> bool   (looks only, for a dry run)
  original_json_present(file_hash, size) -> bool
  import_day_file(kind, date_str, data) -> "written" | "unchanged" | "kept" | "failed"
      kind "intraday" (bulk/raw) or "aggregates"; data = the bytes of such a file from another archive (v1.7.6.2)
  describe_container_path(rel_path) -> ("intraday" | "aggregates", date) | ("original", hash, suffix) | None
      what a path like garmin_data/bulk/raw/garmin_bulk_2024-02-03.json inside a mirror container is (v1.7.6.2)
  list_originals() -> set[str]   (file names "<hash><suffix>" in bulk/source, from the names only; v1.7.6.2)
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
AGG_SCHEMA_VERSION = 2          # the aggregates day file (bulk/aggregates), counted on its own

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

_ORIGINAL_SUFFIXES = (".fit", ".json")      # what an original may be called: FIT files and JSON files of the export
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_ORIGINAL_NAME_RE = re.compile(r"([0-9a-f]{64})(\.fit|\.json)")       # <hash><suffix>, the name of an original
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


def _write_atomic(dst, payload):
    """
    Writes payload to dst through dst + ".tmp": written, flushed to disk (fsync, where the file
    system supports it) and moved with os.replace (tried again while the file is locked for a
    moment, see _replace). Creates the folder. Raises on any failure; the .tmp is removed then
    and a stored dst is untouched. The one writing flow of the day files and aggregates files.
    """
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # not supported on every file system
        _replace(tmp, dst)
    except Exception:
        _cleanup(tmp)
        raise


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _compare(stored_files, stored_version, new_files, current_version):
    """
    How a stored file (its source files and schema version) compares with a new one built from
    `new_files`, under the current schema version: "unchanged", "update", "smaller" or "newer".
    The one rule for both kinds of day file (intraday and aggregates); the caller has checked
    that `stored_files` is a list and `stored_version` an integer.
    """
    if stored_version > current_version:
        return "newer"
    new, old = set(new_files), set(stored_files)
    if new == old:
        return "unchanged" if stored_version == current_version else "update"
    if new > old:
        return "update"
    return "smaller"


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
    return _values_problem(getattr(day_samples, "values", None))


def _values_problem(values):
    """What is wrong with a list of [ms, bpm] samples, None if nothing is (the rule of a day's values)."""
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

def _load_day(date_str):
    """
    (state, doc) of the stored day. state is "missing" (no file, or a date that is no date),
    "damaged" (not JSON, not an object), "unreadable" (an OSError on the way to the content: the
    file may be fine) or "ok"; doc is the dict for "ok" and None otherwise. The only place that
    tells a damaged day from an unreadable one (F-1).
    """
    path = _day_path(date_str)
    if path is None:
        return "missing", None
    try:
        if not path.exists():
            return "missing", None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        log.warning(f"  bulk_writer: could not read the day file of {date_str} (I/O error): {e}")
        return "unreadable", None
    except ValueError as e:
        log.warning(f"  bulk_writer: could not read the day file of {date_str} (damaged): {e}")
        return "damaged", None
    return ("ok", doc) if isinstance(doc, dict) else ("damaged", None)


def list_days():
    """
    The dates (sorted ISO strings) of the day files in bulk/raw, taken from the file names only:
    nothing is read, so a damaged or unreadable file is listed as well, and no folder is created.
    [] if there is no folder or it cannot be listed (a warning in that case). Looks only; the
    caller uses it to see which days the store holds (v1.7.6.1, F-3).
    """
    try:
        import garmin_config as cfg
        prefix, suffix = cfg.BULK_FILE_PREFIX, ".json"
        names = [p.name for p in cfg.BULK_RAW_DIR.glob(f"{prefix}*{suffix}")]
    except OSError as e:
        log.warning(f"  bulk_writer: could not list the day files: {e}")
        return []
    return sorted(d for d in (n[len(prefix):-len(suffix)] for n in names) if _valid_date(d))


def day_status(date_str, source_files):
    """How the stored day compares with a day built from `source_files` (see the module docstring)."""
    state, existing = _load_day(date_str)
    if state == "unreadable":
        return "unreadable"
    if existing is None:
        return "new"
    stored, version = existing.get("source_files"), existing.get("schema_version")
    if not isinstance(stored, list) or not _is_int(version):
        return "new"
    return _compare(stored, version, source_files, BULK_SCHEMA_VERSION)


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
    "written", "unchanged" (nothing touched), "kept" (smaller or newer day stays) or "failed" (non-fatal,
    logged; also for a stored day that cannot be read, which is left as it is)
    """
    try:
        problem = _problem(plan_day, day_samples)
        if problem:
            log.warning(f"  bulk_writer.write_day: refused ({problem})")
            return FAILED
        date_str = day_samples.date
        status = day_status(date_str, day_samples.source_files)
        if status == "unreadable":
            log.warning(f"  bulk_writer: {date_str} not written — the stored day file cannot be read (see the line above); "
                        f"it is left as it is. Run the import again; if it stays unreadable, delete the file "
                        f"{_day_path(date_str).name} in bulk/raw/ by hand and import again")
            return FAILED
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

        _write_atomic(_day_path(date_str), payload)
        log.debug(f"  bulk_writer: {date_str} written ({len(day_samples.values)} values)")
        return WRITTEN
    except Exception as e:
        log.warning(f"  bulk_writer.write_day failed: {e}")
        return FAILED


# ══════════════════════════════════════════════════════════════════════════════
#  Aggregates (v1.7.6.1) — one JSON file per local day in bulk/aggregates, apart from the
#  intraday day files in bulk/raw. Same rules, own schema version. Nothing above is used
#  by it except the small helpers and _compare().
# ══════════════════════════════════════════════════════════════════════════════

def _agg_path(date_str):
    import garmin_config as cfg
    if not _valid_date(date_str):
        return None
    return cfg.BULK_AGG_DIR / f"{cfg.BULK_AGG_FILE_PREFIX}{date_str}.json"


def _load_agg(date_str):
    """
    (state, doc) of the stored aggregates file, the states of _load_day: "missing", "damaged"
    (not JSON, not an object), "unreadable" (an OSError on the way to the content: the file may
    be fine) or "ok" (doc is the dict). Same semantics as _load_day (F-1) — a test pins both.
    """
    path = _agg_path(date_str)
    if path is None:
        return "missing", None
    try:
        if not path.exists():
            return "missing", None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        log.warning(f"  bulk_writer: could not read the aggregates file of {date_str} (I/O error): {e}")
        return "unreadable", None
    except ValueError as e:
        log.warning(f"  bulk_writer: could not read the aggregates file of {date_str} (damaged): {e}")
        return "damaged", None
    return ("ok", doc) if isinstance(doc, dict) else ("damaged", None)


def read_aggregates(date_str):
    """The stored aggregates file of a day as a dict, None if there is none or it cannot be read."""
    return _load_agg(date_str)[1]


def load_aggregates(date_str):
    """
    (state, doc) of the stored aggregates file: state "missing", "damaged", "unreadable" or "ok" (doc
    is the dict then, None otherwise). For a caller that must tell an unreadable file (a lock: leave
    everything as it is) from a damaged or missing one — the summary resolution in garmin_writer.
    """
    return _load_agg(date_str)


def list_aggregate_days():
    """
    The dates (sorted ISO strings) of the files in bulk/aggregates, from the file names only:
    nothing is read, no folder is created. [] if there is no folder or it cannot be listed
    (a warning in that case).
    """
    try:
        import garmin_config as cfg
        prefix, suffix = cfg.BULK_AGG_FILE_PREFIX, ".json"
        names = [p.name for p in cfg.BULK_AGG_DIR.glob(f"{prefix}*{suffix}")]
    except OSError as e:
        log.warning(f"  bulk_writer: could not list the aggregates files: {e}")
        return []
    return sorted(d for d in (n[len(prefix):-len(suffix)] for n in names) if _valid_date(d))


def aggregates_status(date_str, source_files):
    """
    How the stored aggregates file compares with one built from `source_files`: "new", "unchanged",
    "update", "smaller", "newer" or "unreadable" — the rules of day_status (module docstring).
    """
    state, existing = _load_agg(date_str)
    if state == "unreadable":
        return "unreadable"
    if existing is None:
        return "new"
    stored, version = existing.get("source_files"), existing.get("schema_version")
    if not isinstance(stored, list) or not _is_int(version):
        return "new"
    return _compare(stored, version, source_files, AGG_SCHEMA_VERSION)


def _agg_problem(date_str, aggregates, source_files):
    """What is wrong with the aggregates of a day, None if nothing is."""
    if not _valid_date(date_str):
        return "date is not a date"
    if not isinstance(aggregates, dict) or not aggregates:
        return "aggregates is not a dict with entries"
    if "date" in aggregates and aggregates["date"] != date_str:
        return "date of the aggregates differs"
    if not isinstance(source_files, (list, tuple)) or not source_files:
        return "source_files is not a list with entries"
    if not all(isinstance(h, str) and _HASH_RE.fullmatch(h) for h in source_files):
        return "source_files holds something that is not a SHA-256"
    return None


def write_aggregates(date_str, aggregates, source_files, imported_at=None):
    """
    Writes the aggregates of one local day (what garmin_import.parse_day delivers: user summary,
    stats, sleep, readiness, ...) to bulk/aggregates unless the stored file must stay as it is.

    Parameters
    ----------
    date_str     : str — the day, YYYY-MM-DD
    aggregates   : dict — the day's values, stored as they are
    source_files : list[str] — SHA-256 of every source entry of the export that went into the day
                   (garmin_bulk_json_import.entry_hashes), not of the files in bulk/source
    imported_at  : str | None — local time "YYYY-MM-DDTHH:MM:SS"; now if None

    Returns
    -------
    "written", "unchanged" (nothing touched), "kept" (smaller or newer file stays) or "failed"
    (non-fatal, logged; also for a stored file that cannot be read, which is left as it is).
    A damaged file counts as new, like a damaged day file.
    """
    try:
        problem = _agg_problem(date_str, aggregates, source_files)
        if problem:
            log.warning(f"  bulk_writer.write_aggregates: refused ({problem})")
            return FAILED
        status = aggregates_status(date_str, source_files)
        if status == "unreadable":
            log.warning(f"  bulk_writer: {date_str} aggregates not written — the stored file cannot be read "
                        f"(see the line above); it is left as it is. Run the import again; if it stays "
                        f"unreadable, delete the file {_agg_path(date_str).name} in bulk/aggregates/ by hand "
                        f"and import again")
            return FAILED
        if status == "unchanged":
            return UNCHANGED
        if status in ("smaller", "newer"):
            log.info(f"  bulk_writer: {date_str} aggregates kept ({status} than the stored file)")
            return KEPT

        doc = {
            "date": date_str,
            "schema_version": AGG_SCHEMA_VERSION,
            "generated_by": GENERATED_BY,
            "origin": ORIGIN,
            "imported_at": imported_at or datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source_files": sorted(source_files),
            "aggregates": aggregates,
        }
        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        _write_atomic(_agg_path(date_str), payload)
        log.debug(f"  bulk_writer: {date_str} aggregates written")
        return WRITTEN
    except Exception as e:
        log.warning(f"  bulk_writer.write_aggregates failed: {e}")
        return FAILED


# ══════════════════════════════════════════════════════════════════════════════
#  A day or aggregates file of another archive (v1.7.6.2) — the mirror import
# ══════════════════════════════════════════════════════════════════════════════

def _foreign_problem(kind, date_str, doc):
    """
    What is wrong with a day or aggregates file that comes from another archive, None if nothing
    is. It asks for what the broker needs of such a file (garmin_health_map reads the files directly
    and ignores one that does not fit, with a warning): a refused file is better than an ignored one.
    """
    if not _valid_date(date_str):
        return "date is not a date"
    if doc.get("date") != date_str:
        return "date of the file differs from its name"
    if doc.get("origin") != ORIGIN:
        return "origin is not the export"
    version = doc.get("schema_version")
    if not _is_int(version) or version < 1:
        return "schema_version is not a positive integer"
    files = doc.get("source_files")
    if not isinstance(files, list) or not files:
        return "source_files is not a list with entries"
    if not all(isinstance(h, str) and _HASH_RE.fullmatch(h) for h in files):
        return "source_files holds something that is not a SHA-256"
    if kind == "aggregates":
        return _agg_problem(date_str, doc.get("aggregates"), files)
    offset = doc.get("utc_offset_hours")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        return "utc_offset_hours is not a number"
    node = doc.get("sections")
    for key in ("intraday", "heart_rate"):
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        return "no sections.intraday.heart_rate"
    return _values_problem(node.get("values"))


def import_day_file(kind, date_str, data):
    """
    Takes over one day file (kind "intraday", bulk/raw) or aggregates file (kind "aggregates",
    bulk/aggregates) of another archive from its bytes.

    The bytes must pass _foreign_problem(); a file that does not is refused ("failed", the reason
    in the log, nothing written). A file with a schema version newer than this program knows is
    not stored ("kept"). Otherwise the stored file decides, with the rules of the module:
    missing or damaged -> written; cannot be read -> "failed", left as it is (a lock that goes
    away is made good by the next import); readable -> the same comparison as write_day() and
    write_aggregates(): the same set of files and version "unchanged", more files or a newer
    version written, fewer files or an older version "kept" (a smaller stand never replaces a
    fuller one).

    What is written is data, unchanged (the import time and the rest of the other archive's head
    stay), atomic as every file here. Returns "written", "unchanged", "kept" or "failed"; never raises.
    """
    try:
        if kind not in ("intraday", "aggregates"):
            log.warning(f"  bulk_writer.import_day_file: refused (kind {kind!r} is neither intraday nor aggregates)")
            return FAILED
        if not isinstance(data, (bytes, bytearray)):
            log.warning("  bulk_writer.import_day_file: refused (data is not bytes)")
            return FAILED
        data = bytes(data)
        try:
            doc = json.loads(data.decode("utf-8"))
        except ValueError:
            log.warning(f"  bulk_writer.import_day_file: {date_str} {kind} refused (not JSON)")
            return FAILED
        if not isinstance(doc, dict):
            log.warning(f"  bulk_writer.import_day_file: {date_str} {kind} refused (not a JSON object)")
            return FAILED
        problem = _foreign_problem(kind, date_str, doc)
        if problem:
            log.warning(f"  bulk_writer.import_day_file: {date_str} {kind} refused ({problem})")
            return FAILED

        version, files = doc["schema_version"], doc["source_files"]
        known = BULK_SCHEMA_VERSION if kind == "intraday" else AGG_SCHEMA_VERSION
        if version > known:
            log.info(f"  bulk_writer: {date_str} {kind} kept in the container (schema version {version}, "
                     f"this program knows up to {known})")
            return KEPT
        state, existing = (_load_day if kind == "intraday" else _load_agg)(date_str)
        if state == "unreadable":
            log.warning(f"  bulk_writer: {date_str} {kind} not imported — the stored file cannot be read "
                        f"(see the line above); it is left as it is. Run the import again")
            return FAILED
        if state == "ok":
            stored, stored_version = existing.get("source_files"), existing.get("schema_version")
            if isinstance(stored, list) and _is_int(stored_version):
                status = _compare(stored, stored_version, files, version)
                if status == "unchanged":
                    return UNCHANGED
                if status in ("smaller", "newer"):
                    log.info(f"  bulk_writer: {date_str} {kind} kept ({status} than the stored file)")
                    return KEPT
        _write_atomic((_day_path if kind == "intraday" else _agg_path)(date_str), data)
        log.debug(f"  bulk_writer: {date_str} {kind} imported")
        return WRITTEN
    except Exception as e:
        log.warning(f"  bulk_writer.import_day_file failed: {e}")
        return FAILED


def describe_container_path(rel_path):
    """
    What a path inside a mirror container is, from its name alone (nothing is read or looked up):
    ("intraday", date) for garmin_data/bulk/raw/<prefix><date>.json, ("aggregates", date) for
    garmin_data/bulk/aggregates/<prefix><date>.json, ("original", hash, suffix) for
    garmin_data/bulk/source/<xx>/<sha256><.fit|.json> with <xx> the first two characters of the
    hash; None for anything else (another folder, another name, a date that is no date, a path
    with more or fewer parts). Container keys use forward slashes.
    """
    if not isinstance(rel_path, str):
        return None
    parts = rel_path.split("/")
    if len(parts) < 4 or parts[0] != "garmin_data" or parts[1] != "bulk":
        return None
    area, name = parts[2], parts[-1]
    if area in ("raw", "aggregates") and len(parts) == 4:
        import garmin_config as cfg
        prefix = cfg.BULK_FILE_PREFIX if area == "raw" else cfg.BULK_AGG_FILE_PREFIX
        if name.startswith(prefix) and name.endswith(".json") and _valid_date(name[len(prefix):-len(".json")]):
            return ("intraday" if area == "raw" else "aggregates", name[len(prefix):-len(".json")])
        return None
    if area == "source" and len(parts) == 5:
        m = _ORIGINAL_NAME_RE.fullmatch(name)
        if m and parts[3] == m.group(1)[:2]:
            return ("original", m.group(1), m.group(2))
    return None


def list_originals():
    """
    The file names ("<hash><suffix>") of the originals in bulk/source, taken from the names only:
    nothing is read, no folder is created. A folder or file that does not look like an original
    (a .tmp, another name, a name that does not start with its folder) is not listed. An empty set
    if there is no bulk/source or it cannot be listed (a warning in the second case).
    """
    names = set()
    try:
        import garmin_config as cfg
        if not cfg.BULK_SOURCE_DIR.exists():
            return names
        for sub in cfg.BULK_SOURCE_DIR.iterdir():
            if not sub.is_dir():
                continue
            for f in sub.iterdir():
                if _ORIGINAL_NAME_RE.fullmatch(f.name) and f.name[:2] == sub.name:
                    names.add(f.name)
    except OSError as e:
        log.warning(f"  bulk_writer: could not list the originals: {e}")
    return names


# ══════════════════════════════════════════════════════════════════════════════
#  Originals
# ══════════════════════════════════════════════════════════════════════════════

def original_present(file_hash, size, suffix=".fit"):
    """True if bulk/source holds the original with this hash, this size and this suffix (".fit" or
    ".json"). Only looks (a dry run uses it): no folder and no file is created; a name that is not a
    SHA-256, or another suffix, is simply not present."""
    try:
        import garmin_config as cfg
        if not isinstance(file_hash, str) or not _HASH_RE.fullmatch(file_hash) or suffix not in _ORIGINAL_SUFFIXES:
            return False
        return (cfg.BULK_SOURCE_DIR / file_hash[:2] / f"{file_hash}{suffix}").stat().st_size == size
    except OSError:
        return False


def original_json_present(file_hash, size):
    """original_present() for a JSON file of the export (bulk/source/<xx>/<hash>.json)."""
    return original_present(file_hash, size, ".json")


def store_original_json(file_hash, data):
    """store_original() for a JSON file of the export (bulk/source/<xx>/<hash>.json)."""
    return store_original(file_hash, data, ".json")


def store_original(file_hash, data, suffix=".fit"):
    """
    Stores one export file as bulk/source/<first two characters>/<hash><suffix>, the suffix being
    ".fit" (default) or ".json".

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
        if suffix not in _ORIGINAL_SUFFIXES:
            log.warning("  bulk_writer.store_original: refused (suffix is neither .fit nor .json)")
            return FAILED
        if not isinstance(data, (bytes, bytearray)):
            log.warning("  bulk_writer.store_original: refused (data is not bytes)")
            return FAILED
        data = bytes(data)
        if hashlib.sha256(data).hexdigest() != file_hash:
            log.warning(f"  bulk_writer.store_original: refused (bytes do not match {file_hash[:12]})")
            return FAILED
        if original_present(file_hash, len(data), suffix):
            return PRESENT
        dst = cfg.BULK_SOURCE_DIR / file_hash[:2] / f"{file_hash}{suffix}"
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
