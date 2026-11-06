#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_catchup_predictions.py

PREDICTION-CATCHUP v1.7.6.11.2 — REMOVABLE.

Fills the race prediction of the days that hold none of their own date, from Garmin, with a few range calls.
Since v1.7.6.10 the fetch asks Garmin for a day WITH its date and the prediction repair puts a stored
prediction on the day it is dated with; what both leave behind are days with no `race_predictions` field at
all: the days the repair cleaned of a copy of another day's prediction, and days that were never fetched with
their date. Garmin answers a range ("daily", at most one year per call) with one entry per day, so a handful of
calls replace one call per day.

What it does (nothing is guessed, nothing is invented):
  - A candidate is a raw day that has an entry in the quality log, no `race_predictions` field (missing, empty
    or not a dict) and has not been given up for that field (entry["field_backfill_attempts"] below
    GIVE_UP_ATTEMPTS). Days that already hold a prediction — of their own date or of another day — are never
    touched: a prediction with the right date is not overwritten (when Garmin's value for such a day differs,
    the archive keeps its value; the day is only counted and its date logged), a copy of another day's is the
    business of the prediction repair, not of this module.
  - Basis: there must be at least one day in the archive that holds a prediction of its own date. An archive
    without one has no sign that Garmin delivers predictions for this account, and nothing is asked (an
    account without race predictions is never offered the catch-up).
  - The candidates are asked newest first, in ranges of at most MAX_RANGE_DAYS days (one call each, always
    from the oldest to the newest candidate of the range; a gap between candidates costs nothing). The start of
    what Garmin holds is found from the answers, not assumed: an answer without any entry in its range, after
    a newer range that had entries, means Garmin holds nothing earlier — the older candidates are marked and
    not asked. An empty answer without such proof is marked for its own range only and the walk goes on.
  - A day with an entry of its own date in the answer gets it: the dict of the entry, with `fromCalendarDate`
    and `toCalendarDate` set to the day (a range answer carries the bounds of the range there; the answer for
    one day carries the day — the stored form is the same either way). The label `fields["race_predictions"]`
    becomes "medium", `last_checked` is set (the MCP cache reads the day again).
  - A candidate day inside an answered range without an entry is marked "asked, answered empty": the counter
    entry["field_backfill_attempts"]["race_predictions"] is raised to GIVE_UP_ATTEMPTS (the give-up threshold of
    the field backfills), so the day is not offered or asked again. Nothing else of the day changes.
  - A call that fails (or a stop, or the rate limit) marks nothing for its range and the older ones: the days
    are asked again at the next run. A failed day never stops the loop.

Detection is by content (no field, no give-up mark); nothing is stored but the day's own field and the counter.
The candidates and the numbers come from raw/ and the quality log only (find_candidates, read-only, no API call).

Delegation, nothing is written here directly (Sole-Write-Authority):
  raw/ + summary/ → garmin_writer.write_day (the raw backup follows)
  source/         → garmin_source_writer.patch_source_field (additive: only when the day has a source file and its
                    field is empty; the entry as stored in raw/, so a day rebuilt from source/ keeps it)
  quality log     → garmin_quality.touch_last_checked + record_field_labels + record_field_given_up +
                    _save_quality_log, under one continuous QUALITY_LOCK hold, saved once. The caller's own
                    quality_data is used when it is passed (a copy loaded here would be overwritten by the caller's
                    next save).
  safety copy     → garmin_migration_snapshot.create_snapshot(stores=("raw", "quality_log"), or only the
                    quality log when nothing but marks are written) AFTER the calls and BEFORE the first write: no
                    copy, no write; nothing is copied when Garmin answered nothing to write. The way back is
                    restore_snapshot() of that ZIP.
The caller must not hold QUALITY_LOCK (it is not re-entrant). Needs a logged-in client (garminconnect).

Public API:
  find_candidates(raw_dir=None, quality_log_file=None, quality_data=None) -> dict
        — read-only: {"missing": [days], "calls": n, "kept": n, "foreign": [days], "given_up": n, "basis": bool}
  catch_up(client, dry_run=False, should_stop=None, quality_data=None) -> dict

The log carries day names and counts only, never a value of a prediction (health data; CodeQL alert #18).

REMOVAL LIST (everything that belongs to this catch-up carries the marker "PREDICTION-CATCHUP v1.7.6.11.2"):
  - this file and tests/test_catchup_predictions.py
  - compiler/build_manifest.py: file list entry + SCRIPT_SIGNATURES_BASE entry
  - run_tests.ps1 and tests/conftest.py: the test file entry
  - garmin_collector.py: the section "Prediction catch-up" with _run_prediction_catchup(), the steps "3j" and "5f" in
    main() (environment variable GARMIN_PREDICTION_CATCHUP) and its entry in the build_manifest.py signatures;
    the tests "4u main prediction catch-up" in tests/test_collector.py
  - app/panel_archive.py: _check_prediction_catchup() (popup)
  - app/outputs/sync.py: the three lines in run_collector() that set GARMIN_PREDICTION_CATCHUP
  - scheduler/daily_update.py: _check_prediction_catchup() and step "4f" in main()
  - tests/test_qt_app.py: the class TestPredictionCatchupHooks and the lines
    `_check_prediction_catchup.return_value = False`; tests/test_daily_update.py: the `catchup` hint
  - docs sections of this catch-up (REFERENCE_GARMIN, MAINTENANCE_GARMIN); CHANGELOG entries stay
  What stays: garmin_quality.record_field_given_up (generic; its tests in tests/test_quality.py).
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import garmin_api as api
import garmin_config as cfg
import garmin_migration_snapshot as snapshot
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_source_writer as source_writer
import garmin_writer as writer

log = logging.getLogger(__name__)

FIELD = "race_predictions"
_RAW_PREFIX = "garmin_raw_"

# One call covers at most this many days (the library allows 366; one year is the upper bound the maintainer set,
# 365 keeps a leap year inside it).
MAX_RANGE_DAYS = 365

# A day asked and answered empty is marked with this attempt count. Mirrors FIELD_BACKFILL_ATTEMPT_LIMIT of
# app/garmin_app_controller.py (the give-up threshold of the field backfills); a test pins both to the same value.
GIVE_UP_ATTEMPTS = 2

_VALUE_KEYS = ("time5K", "time10K", "timeHalfMarathon", "timeMarathon")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _valid_date(value) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _field_of(raw):
    """The race_predictions dict of a raw day, None when it is missing, empty or not a dict."""
    value = raw.get(FIELD) if isinstance(raw, dict) else None
    return value if isinstance(value, dict) and value else None


def _scan(raw_dir) -> dict:
    """{day: its race_predictions dict or None} for every readable raw day. An unreadable file is skipped."""
    out = {}
    if not raw_dir.exists():
        return out
    for f in sorted(raw_dir.glob(f"{_RAW_PREFIX}*.json")):
        day = f.stem[len(_RAW_PREFIX):]
        if not _valid_date(day):
            continue
        try:
            out[day] = _field_of(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.debug(f"  Prediction catch-up scan: {f.name} unreadable, skipped: {e}")
    return out


def _attempts(quality_data, quality_log_file) -> dict:
    """{day: attempts of race_predictions} for every day with an entry in the quality log. Nothing readable: {}."""
    data = quality_data
    if data is None:
        try:
            data = json.loads(Path(quality_log_file).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
    out = {}
    for e in (data.get("days", []) if isinstance(data, dict) else []):
        if isinstance(e, dict) and _valid_date(e.get("date")):
            att = e.get("field_backfill_attempts")
            n = att.get(FIELD, 0) if isinstance(att, dict) else 0
            out[e["date"]] = n if isinstance(n, int) and not isinstance(n, bool) else 0
    return out


def _ranges(days: list) -> list:
    """
    Splits the sorted candidate days into ranges of at most MAX_RANGE_DAYS days, newest first. A range runs from
    its oldest to its newest candidate: [(start, end, [days of the range])].
    """
    out, rest = [], list(days)
    while rest:
        floor = (date.fromisoformat(rest[-1]) - timedelta(days=MAX_RANGE_DAYS - 1)).isoformat()
        inside = [d for d in rest if d >= floor]
        rest = rest[:len(rest) - len(inside)]
        out.append((inside[0], inside[-1], inside))
    return out


def _plan(field_map: dict, attempts: dict) -> dict:
    own = {d for d, p in field_map.items() if p is not None and p.get("calendarDate") == d}
    foreign = sorted(d for d, p in field_map.items() if p is not None and d not in own)
    empty = [d for d, p in field_map.items() if p is None and d in attempts]
    missing = sorted(d for d in empty if attempts[d] < GIVE_UP_ATTEMPTS) if own else []
    return {"missing": missing, "calls": len(_ranges(missing)), "kept": len(own), "foreign": foreign,
            "given_up": sum(1 for d in empty if attempts[d] >= GIVE_UP_ATTEMPTS), "basis": bool(own)}


# ══════════════════════════════════════════════════════════════════════════════
#  Detection (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def find_candidates(raw_dir=None, quality_log_file=None, quality_data=None) -> dict:
    """
    Reads the race_predictions field of every raw day and the give-up counters of the quality log and works out
    what the catch-up would ask for (see the module docstring). Nothing is written, nothing is asked.

    Returns:
      "missing"   [days]  candidates: no field, an entry in the quality log, not given up; empty without basis
      "calls"     n       range calls needed at most (the walk may end earlier, at the start of Garmin's history)
      "kept"      n       days that already hold a prediction of their own date
      "foreign"   [days]  days that hold a prediction of another day: not touched, the prediction repair's business
      "given_up"  n       days that were asked before and answered empty: not asked again
      "basis"     bool    at least one day holds a prediction of its own date
    raw_dir (Path, optional): the folder to read instead of the configured one; quality_log_file (Path,
    optional): the log to read instead of the configured one; quality_data (dict, optional): the run's own log,
    read instead of a file. The GUI popup and the scheduler pass the archive of the current settings, so they do
    not depend on what garmin_config was imported with.
    """
    raw_dir = cfg.RAW_DIR if raw_dir is None else raw_dir
    quality_log_file = cfg.QUALITY_LOG_FILE if quality_log_file is None else quality_log_file
    return _plan(_scan(raw_dir), _attempts(quality_data, quality_log_file))


# ══════════════════════════════════════════════════════════════════════════════
#  Catch-up
# ══════════════════════════════════════════════════════════════════════════════

def _entries(answer, start: str, end: str) -> dict:
    """{day: entry} of the dict entries of a range answer whose calendarDate lies in [start, end]; the first one per day."""
    out = {}
    if isinstance(answer, list):
        for item in answer:
            if isinstance(item, dict) and item:
                cd = item.get("calendarDate")
                if _valid_date(cd) and start <= cd <= end:
                    out.setdefault(cd, item)
    return out


def _day_entry(item: dict, day: str) -> dict:
    """The entry as the archive stores a day's prediction: bounds of the range replaced by the day."""
    entry = dict(item)
    entry["fromCalendarDate"] = day
    entry["toCalendarDate"] = day
    return entry


def catch_up(client, dry_run: bool = False, should_stop=None, quality_data=None) -> dict:
    """
    Asks Garmin for the race predictions of the candidate days and stores them (see the module docstring).
    Always scans anew — never acts on an earlier finding.

    client       : logged-in garminconnect client (garmin_api.login()).
    dry_run      : True → nothing is asked, nothing is written; the result lists what would be asked.
    should_stop  : optional callable; when it returns True before a call or before the write nothing more is
                   asked and nothing is written, when it returns True during the loop the loop ends after the
                   current day (days already written are still recorded).
    quality_data : the quality log dict of the caller (garmin_collector.main passes its own): labels and marks
                   are set on that very object and saved. Without it the log is loaded here.

    Returns a dict:
      filled       int   — days that got a prediction of their own date (dry run: 0)
      given_up     int   — days marked as asked and answered empty
      calls        int   — range calls made (dry run: how many would be made at most)
      failed       int   — days that could not be written, calls that failed, or 1 when the safety copy / the log
                           save failed
      source_failed int  — filled days whose source/ file could not be patched (raw/ and summary/ are written; only set
                           when the write phase ran)
      missing      int   — candidates at the start
      kept, foreign [days], given_up_before — see find_candidates
      differs      [days]— days with a prediction of their own date whose values differ from Garmin's: kept as they are
      safety_copy  str | None — name of the ZIP in backup/migration
      reason       str   — set when something went wrong or nothing was written although days were candidates
      stopped      bool
    """
    field_map = _scan(cfg.RAW_DIR)
    plan = _plan(field_map, _attempts(quality_data, cfg.QUALITY_LOG_FILE))
    res = {"filled": 0, "given_up": 0, "calls": 0, "failed": 0, "missing": len(plan["missing"]),
           "kept": plan["kept"], "foreign": plan["foreign"], "given_up_before": plan["given_up"], "differs": [],
           "safety_copy": None, "stopped": False}

    if not plan["missing"]:
        log.info("  Prediction catch-up: no day needs a prediction from Garmin.")
        return res
    ranges = _ranges(plan["missing"])
    if dry_run:
        res["calls"] = len(ranges)
        log.info(f"  Prediction catch-up (dry run): {len(plan['missing'])} day(s) hold no prediction, at most "
                 f"{len(ranges)} range call(s) to Garmin")
        return res

    # ── ask Garmin (read-only for the archive) ─────────────────────────────────
    fill, give_up = {}, set()
    proven = False                                    # a newer range had entries: Garmin's history is known to exist
    for start, end, days in ranges:
        if should_stop is not None and should_stop():
            res["stopped"] = True
            return res
        answer, ok = api.api_call(client, "get_race_predictions", start, end, "daily", label="race_predictions")
        res["calls"] += 1
        if not ok or not isinstance(answer, list):
            res["failed"] += 1
            res["reason"] = "a call to Garmin failed — the days of this range and older ones stay for the next run"
            log.warning(f"  Prediction catch-up: the call for {start} to {end} failed — "
                        f"nothing is marked for these days, they are asked again at the next run")
            break
        found = _entries(answer, start, end)
        if not found:
            if proven:
                older = [d for d in plan["missing"] if d <= end]
                give_up.update(older)
                log.info(f"  Prediction catch-up: Garmin holds no prediction up to {end} — {len(older)} older day(s) marked")
                break
            give_up.update(days)
            log.info(f"  Prediction catch-up: no prediction in {start} to {end} — {len(days)} day(s) marked")
            continue
        proven = True
        for d in days:
            if d in found:
                fill[d] = _day_entry(found[d], d)
            else:
                give_up.add(d)
        for d, entry in found.items():                # a day that already holds its own date is never overwritten
            mine = field_map.get(d)
            if mine is not None and mine.get("calendarDate") == d and any(mine.get(k) != entry.get(k) for k in _VALUE_KEYS):
                res["differs"].append(d)
        log.info(f"  Prediction catch-up: {start} to {end} — {len([d for d in days if d in fill])} of {len(days)} day(s) answered")
    res["differs"] = sorted(res["differs"])
    for d in res["differs"]:
        log.info(f"  Prediction catch-up: {d} — Garmin's prediction differs from the stored one, the stored one stays")

    if not fill and not give_up:
        res.setdefault("reason", "Garmin answered nothing to store")
        return res
    if should_stop is not None and should_stop():
        res["stopped"] = True
        return res

    # ── safety copy, then write ────────────────────────────────────────────────
    stores = ("raw", "quality_log") if fill else ("quality_log",)
    copy = snapshot.create_snapshot(should_stop, stores=stores)
    if not copy.get("ok") or copy.get("path") is None:
        res["failed"] += 1
        res["reason"] = copy.get("reason") or "no safety copy was made"
        log.error(f"  Prediction catch-up: no safety copy ({res['reason']}) — nothing written")
        return res
    res["safety_copy"] = copy["path"].name
    log.info(f"  Prediction catch-up: safety copy {res['safety_copy']}")

    written, failed, source_failed = [], 0, 0
    total = len(fill)
    log.info(f"  Prediction catch-up: {total} day(s) will get a prediction, {len(give_up)} marked as empty")
    with quality.QUALITY_LOCK:
        qdata = quality_data if quality_data is not None else quality._load_quality_log()
        try:
            for i, d in enumerate(sorted(fill), 1):
                if should_stop is not None and should_stop():
                    res["stopped"] = True
                    log.info(f"  Prediction catch-up: stopped after {i - 1} of {total} day(s).")
                    break
                try:
                    raw_path = cfg.RAW_DIR / f"{_RAW_PREFIX}{d}.json"
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    if _field_of(raw) is not None:
                        log.info(f"  [{i}/{total}] {d} — holds a prediction now, left as it is")
                        continue
                    raw[FIELD] = fill[d]
                    if not writer.write_day(raw, normalizer.summarize(raw), d):
                        raise OSError("write_day reported a failure")
                    written.append(d)
                    if not source_writer.patch_source_field(d, FIELD, fill[d]):
                        source_failed += 1
                        log.warning(f"  [{i}/{total}] {d} — source/ could not be patched (raw/ and summary/ are written)")
                    log.info(f"  [{i}/{total}] {d} — prediction set ok")
                except Exception as e:
                    failed += 1
                    log.error(f"  [{i}/{total}] {d} — error: {e}")
        finally:
            marks = give_up if not res["stopped"] else set()
            if written or marks:
                if written:
                    quality.touch_last_checked(qdata, written)
                    quality.record_field_labels(qdata, {d: "medium" for d in written}, FIELD)
                n_marked = quality.record_field_given_up(qdata, sorted(marks), FIELD, GIVE_UP_ATTEMPTS) if marks else 0
                if quality._save_quality_log(qdata) is False:
                    failed += 1
                    res["reason"] = "the quality log could not be saved"
                    log.error("  Prediction catch-up: the quality log could not be saved")
                else:
                    res["given_up"] = n_marked
    res["filled"] = len(written)
    res["failed"] += failed
    res["source_failed"] = source_failed
    log.info(f"  Prediction catch-up complete: {len(written)} day(s) got a prediction, {res['given_up']} marked as "
             f"empty, {res['failed']} failed, {len(res['differs'])} differ from Garmin (kept), {res['calls']} call(s).")
    return res
