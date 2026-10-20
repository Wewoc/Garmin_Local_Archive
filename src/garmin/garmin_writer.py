#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_writer.py

Writer — sole owner of raw/ and summary/.

Responsibilities:
  - Write raw/garmin_raw_YYYY-MM-DD.json
  - Write summary/garmin_YYYY-MM-DD.json
  - Resolve the summary of a day from the API data (raw/) and the values of the Garmin export
    (bulk/aggregates, v1.7.6.1)

No other module writes to raw/ or summary/ directly.
No API logic, no quality log access, no date strategy logic.

Resolved summary (v1.7.6.1): summary/ is the one place that holds a single value per day for
readers that do not ask the broker. When a day has an aggregates file in the bulk store, the
summary is not taken as passed but derived from the API data plus the export's values: per top-level
key of the raw dict the API data win when they are not empty (garmin_merge.merge_field), the export
fills what is missing or empty, then summarize(). raw/ keeps only what was passed (API data) — it never
receives export values. A day without an aggregates file is written exactly as before.
State of the aggregates file:
  missing / damaged / written by a newer schema -> as if missing (damaged and newer with a warning)
  unreadable (lock, no access)                  -> nothing is written, False: a summary without the
                                                   export's values must not replace a complete one

Public functions:
  write_day(normalized, summary, date_str) -> bool
  write_summary_only(summary, date_str)    -> bool
  rebuild_summary(date_str)                -> bool   summary/ only, from raw/ (if any) and the aggregates
  read_raw(date_str)                       -> dict
  read_summary(date_str)                   -> dict
"""

import copy
import json
import logging
import os
from datetime import date as _date

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Resolved summary (v1.7.6.1) — the aggregates of the bulk store joined with the API data
# ══════════════════════════════════════════════════════════════════════════════

def _usable_aggregates(date_str: str):
    """
    ("none" | "ok" | "unreadable", aggregates dict | None) for a day.

    "none": no aggregates file, a damaged one, or one written by a newer schema than this
    program reads (the last two with a warning) — the day is treated as having none.
    "unreadable": the file cannot be read for an I/O reason; the caller must not write a summary
    that lacks the export's values. "ok": the dict of the day's export values.
    """
    import garmin_bulk_writer as bw
    state, doc = bw.load_aggregates(date_str)
    if state == "unreadable":
        return "unreadable", None
    if state != "ok":
        return "none", None           # missing; a damaged file was logged by the loader
    version, aggregates = doc.get("schema_version"), doc.get("aggregates")
    if (isinstance(version, bool) or not isinstance(version, int) or version > bw.AGG_SCHEMA_VERSION
            or not isinstance(aggregates, dict) or not aggregates):
        log.warning(f"  Writer: aggregates of {date_str} not used (schema_version {version!r} or content "
                    f"not usable) — summary derived from the API data only")
        return "none", None
    return "ok", aggregates


def _resolve(api_raw: dict, aggregates: dict) -> dict:
    """
    The day as one raw dict: the API data (api_raw, may be empty) plus the export's values
    (aggregates) in every top-level key where the API data have nothing (absent or empty).
    Neither argument is changed; the export values are normalised like an import day.
    """
    import garmin_merge as merge
    import garmin_normalizer as normalizer
    bulk = normalizer.normalize(copy.deepcopy(aggregates), source="bulk")
    resolved = api_raw if isinstance(api_raw, dict) else {}
    for key, value in bulk.items():
        resolved = merge.merge_field(resolved, key, value)
    return resolved


def _summarize_resolved(api_raw: dict, aggregates: dict) -> dict:
    """summarize() of the day resolved from the API data and the export's values."""
    import garmin_normalizer as normalizer
    return normalizer.summarize(_resolve(api_raw, aggregates))


def _raw_for_resolve(date_str: str):
    """(ok, raw): ok is False when a raw file exists but cannot be read (nothing may be derived then)."""
    if not (cfg.RAW_DIR / f"garmin_raw_{date_str}.json").exists():
        return True, {}
    raw = read_raw(date_str)
    return (True, raw) if raw else (False, {})


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def write_day(normalized: dict, summary: dict, date_str: str) -> bool:
    """
    Writes a single day to raw/ and summary/.

    Parameters
    ----------
    normalized : dict — normalised raw data as returned by garmin_normalizer.normalize()
    summary    : dict — compact daily summary as returned by garmin_normalizer.summarize()
    date_str   : str  — date in YYYY-MM-DD format

    Returns
    -------
    bool — True if both files were written successfully, False on any error
    """
    tmp_raw     = None
    tmp_summary = None
    try:
        # v1.7.6.1: a day with an aggregates file in the bulk store gets the resolved summary,
        # not the one passed in; raw/ gets what was passed in (see the module docstring).
        agg_state, aggregates = _usable_aggregates(date_str)
        if agg_state == "unreadable":
            log.error(f"  Writer: {date_str} not written — the aggregates file of the day cannot be read; "
                      f"raw/ and summary/ stay as they are")
            return False
        if agg_state == "ok":
            summary = _summarize_resolved(normalized, aggregates)

        cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

        raw_path     = cfg.RAW_DIR     / f"garmin_raw_{date_str}.json"
        summary_path = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"
        tmp_raw      = cfg.RAW_DIR     / f"garmin_raw_{date_str}.tmp"
        tmp_summary  = cfg.SUMMARY_DIR / f"garmin_{date_str}.tmp"

        tmp_raw.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        tmp_summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        os.replace(tmp_raw, raw_path)
        tmp_raw = None
        os.replace(tmp_summary, summary_path)
        tmp_summary = None

        log.debug(f"  Writer: raw + summary written for {date_str}")

        # Trigger incremental raw backup (B1) — lazy import, failure non-fatal
        try:
            import garmin_backup as _backup
            _backup.backup_raw(date_str)
        except ImportError:
            pass  # garmin_backup not yet available
        except Exception as e:
            log.error(f"  Writer: raw backup trigger failed for {date_str}: {e}")

        return True

    except Exception as e:
        log.error(f"  Writer: failed to write {date_str}: {e}")
        for tmp in (tmp_raw, tmp_summary):
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        return False


def write_summary_only(summary: dict, date_str: str) -> bool:
    """
    Writes only the summary file for a single day. raw/ and its backup
    are never touched — unlike write_day(), no raw_path/tmp_raw is
    computed and backup_raw() is never triggered.

    Used by the schema-migration loop in garmin_collector.py
    (_run_schema_migration()), which only recomputes summary/ from an
    already-archived, frozen raw/ file. raw/ must stay byte-for-byte
    untouched even if a future normalize() change would produce a
    different result than what is already on disk.

    Parameters
    ----------
    summary  : dict — compact daily summary as returned by garmin_normalizer.summarize()
    date_str : str  — date in YYYY-MM-DD format

    v1.7.6.1: a day with an aggregates file in the bulk store gets the resolved summary (API data
    read from raw/, plus the export's values), not the one passed in; an aggregates file that cannot
    be read, or a raw file that exists and cannot be read, writes nothing (False).

    Returns
    -------
    bool — True if the summary file was written successfully, False on any error
    """
    try:
        agg_state, aggregates = _usable_aggregates(date_str)
        if agg_state == "unreadable":
            log.error(f"  Writer: summary of {date_str} not written — the aggregates file of the day "
                      f"cannot be read; summary/ stays as it is")
            return False
        if agg_state == "ok":
            raw_ok, api_raw = _raw_for_resolve(date_str)
            if not raw_ok:
                log.error(f"  Writer: summary of {date_str} not written — raw/ cannot be read")
                return False
            summary = _summarize_resolved(api_raw, aggregates)
    except Exception as e:
        log.error(f"  Writer: failed to resolve the summary for {date_str}: {e}")
        return False
    return _write_summary_file(summary, date_str)


def rebuild_summary(date_str: str) -> bool:
    """
    Derives summary/ of a day from what the archive holds and writes only summary/: the API data
    from raw/ (if the day has a raw file) and the export's values from the bulk store (if the day
    has an aggregates file), resolved as in write_day(). raw/ and its backup are never touched.

    This is the way to a summary for a day without a raw file (an imported export day) and to a
    summary that has to be made again (schema migration, repair). Nothing to derive from (neither a
    raw file nor usable aggregates), an aggregates or raw file that cannot be read, or a write
    error: False (logged). A date that is no date: False.
    """
    try:
        _date.fromisoformat(date_str)
    except (TypeError, ValueError):
        log.error(f"  Writer.rebuild_summary: '{date_str}' is not a date")
        return False
    try:
        agg_state, aggregates = _usable_aggregates(date_str)
        if agg_state == "unreadable":
            log.error(f"  Writer: summary of {date_str} not rebuilt — the aggregates file of the day cannot be read")
            return False
        raw_ok, api_raw = _raw_for_resolve(date_str)
        if not raw_ok:
            log.error(f"  Writer: summary of {date_str} not rebuilt — raw/ cannot be read")
            return False
        if agg_state != "ok" and not api_raw:
            log.debug(f"  Writer.rebuild_summary: nothing to derive a summary from for {date_str}")
            return False
        if agg_state == "ok":
            summary = _summarize_resolved(api_raw, aggregates)
        else:
            import garmin_normalizer as normalizer
            summary = normalizer.summarize(api_raw)
    except Exception as e:
        log.error(f"  Writer: failed to rebuild the summary for {date_str}: {e}")
        return False
    return _write_summary_file(summary, date_str)


def _write_summary_file(summary: dict, date_str: str) -> bool:
    """Writes summary/garmin_<date>.json atomically (the file part of write_summary_only; no resolution)."""
    tmp_summary = None
    try:
        cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

        summary_path = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"
        tmp_summary  = cfg.SUMMARY_DIR / f"garmin_{date_str}.tmp"

        tmp_summary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        os.replace(tmp_summary, summary_path)
        tmp_summary = None

        log.debug(f"  Writer: summary written for {date_str} (raw/ untouched)")
        return True

    except Exception as e:
        log.error(f"  Writer: failed to write summary for {date_str}: {e}")
        if tmp_summary is not None:
            try:
                tmp_summary.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def read_raw(date_str: str) -> dict:
    """
    Reads and returns the raw file for a given date.

    Used exclusively by the self-healing loop in garmin_collector.py —
    no API call, no re-download. Returns empty dict on any error.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    dict — parsed raw data, or {} if file is missing or corrupt
    """
    raw_path = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"

    if not raw_path.exists():
        log.warning(f"  Writer.read_raw: file not found for {date_str}")
        return {}

    try:
        with open(raw_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"  Writer.read_raw: failed to read {date_str}: {e}")
        return {}


def read_summary(date_str: str) -> dict:
    """
    Reads and returns the summary file for a given date.

    Used by the schema-migration loop in garmin_collector.py to check
    the stored schema_version before deciding whether to rewrite.
    Returns empty dict if file is missing or corrupt.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    dict — parsed summary data, or {} if file is missing or corrupt
    """
    summary_path = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"

    if not summary_path.exists():
        log.debug(f"  Writer.read_summary: file not found for {date_str}")
        return {}

    try:
        with open(summary_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"  Writer.read_summary: failed to read {date_str}: {e}")
        return {}
