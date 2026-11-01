#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_repair_predictions.py

PREDICTION-REPAIR v1.7.6.10 — REMOVABLE.

Puts the race predictions of the archive on the day they belong to. Until v1.7.6.10 the API answer of
get_race_predictions() (called without a date: the current prediction, dated with the day of the call)
was filed under the day that was asked for. A nightly fetch of day D brings a prediction dated D+1, a
catch-up fetch of an old day one dated that day: in the archive of the maintainer 2,874 raw days carried
a copy of only 128 different predictions, none of them dated as the day itself. From v1.7.6.10 on the
fetch keeps such an answer out of the day (garmin_normalizer.own_day_prediction); this module corrects what is
already stored.

What it does (nothing is guessed, nothing is invented):
  - A day whose `race_predictions` has `calendarDate` equal to the day itself is correct and stays.
  - A prediction dated D' that sits on another day is placed on the raw day D' (the dict as it is, not
    changed) when that day exists in raw/ and does not already hold a prediction of its own date.
  - The misdated copies are then removed. A day that gets a prediction of its own date has the
    misdated copy replaced by it; any other day loses the copy and keeps no field. What is removed
    stays in source/ (the unmodified API answer of the day) and in the safety copy.
  - Left untouched and reported, not removed: carriers of a date whose copies differ ("conflict" — which
    one is right is not known), carriers of a date that has no raw day yet ("waiting" — they are placed
    when the day exists, the next run finds them), and a prediction without a usable `calendarDate`
    ("undated"). One exception, always reported ("replaced"): such a carrier that is itself the target of
    another prediction gets that prediction (leaving it would lose the dated one); what it carried stays
    only in source/ and the safety copy.
  - The label `fields["race_predictions"]` of every changed day follows in the quality log: "medium"
    where a prediction of the day's own date is now stored, "failed" where the field is gone.
    `last_checked` of those days is set so that the MCP cache reads them again.

Detection is by content (the date inside the answer against the day); no marker is stored, a second run
finds nothing. Source of the values: the raw days themselves, no API call, no login, no export.

Delegation, nothing is written here directly (Sole-Write-Authority):
  raw/ + summary/ → garmin_writer.write_day (the raw backup follows)
  quality log     → garmin_quality.touch_last_checked + record_field_labels + _save_quality_log, under
                    one continuous QUALITY_LOCK hold, saved once. The caller's own quality_data is used
                    when it is passed (a copy loaded here would be overwritten by the caller's next save).
  safety copy     → garmin_migration_snapshot.create_snapshot(stores=("raw", "quality_log")) BEFORE the
                    lock: no copy, no write. The way back is restore_snapshot() of that ZIP.
The caller must not hold QUALITY_LOCK (it is not re-entrant). A failing day never stops the loop.

Public API:
  find_candidates(raw_dir=None) -> dict
        — read-only: {"set": {day: prediction}, "remove": [days], "kept": n,
                      "conflict": [dates], "waiting": [days], "undated": [days]}
  repair_predictions(dry_run=False, should_stop=None, quality_data=None) -> dict

REMOVAL LIST (everything that belongs to this repair carries the marker "PREDICTION-REPAIR v1.7.6.10"):
  - this file and sections P5 to P7 of tests/test_repair_predictions.py (P0 to P4 test what stays: the fetch, the rule in
    normalize(), the rating, record_field_labels — keep them, move them to test_api / test_normalizer / test_quality)
  - compiler/build_manifest.py: file list entry + SCRIPT_SIGNATURES_BASE entry
  - run_tests.ps1 and tests/conftest.py: the test file entry
  - garmin_collector.py: the section "Prediction repair" with _run_prediction_repair(), the step "3i" in
    main() (environment variable GARMIN_PREDICTION_REPAIR) and its entry in the build_manifest.py
    signatures; the tests "4u main prediction repair" in tests/test_collector.py
  - app/panel_archive.py: _check_prediction_repair() (popup)
  - app/outputs/sync.py: the three lines in run_collector() that set GARMIN_PREDICTION_REPAIR
  - scheduler/daily_update.py: _check_prediction_repair() and step "4e" in main()
  - tests/test_qt_app.py: the class TestPredictionRepairHooks and the lines
    `_check_prediction_repair.return_value = False`; tests/test_daily_update.py: the `prediction` hint
  - docs sections of this repair (REFERENCE_GARMIN, MAINTENANCE_GARMIN); CHANGELOG entries stay
  What stays: garmin_normalizer.own_day_prediction (a foreign prediction is kept out of the day), the
  rule in quality/_assess.py (a prediction counts only with the day's own date), garmin_quality.
  record_field_labels.
"""

import json
import logging
from datetime import date

import garmin_config as cfg
import garmin_migration_snapshot as snapshot
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

log = logging.getLogger(__name__)

FIELD = "race_predictions"
_RAW_PREFIX = "garmin_raw_"


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


def _canon(prediction: dict) -> str:
    """Canonical text of a prediction — two copies of the same answer have the same text."""
    return json.dumps(prediction, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _field_of(raw):
    """The race_predictions dict of a raw day, None when it is missing, empty or not a dict."""
    value = raw.get(FIELD) if isinstance(raw, dict) else None
    return value if isinstance(value, dict) and value else None


# ══════════════════════════════════════════════════════════════════════════════
#  Detection (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def find_candidates(raw_dir=None) -> dict:
    """
    Reads the race_predictions field of every raw day and works out what the repair would do (see the
    module docstring). Nothing is written.

    Returns:
      "set"      {day: prediction}  days that get the prediction dated with that day (replacing the
                                    misdated copy they carry, if any)
      "remove"   [days]             days that lose a misdated copy and keep no field
      "kept"     n                  days whose field already has their own date
      "conflict" [dates]            prediction dates whose carriers differ — carriers stay untouched
      "waiting"  [days]             carriers of a date without a raw day — stay untouched for now
      "undated"  [days]             days whose field has no usable calendarDate — stay untouched
      "replaced" [days]             days that carried one of the three kinds above and are themselves the
                                    target of another prediction: they get that one, what they carried
                                    stays only in source/ and the safety copy (listed, never silent)
    raw_dir (Path, optional): the folder to read instead of the configured one. The GUI popup and the
    scheduler pass the archive of the current settings, so they do not depend on what garmin_config was
    imported with. An unreadable raw file is skipped.
    """
    raw_dir = cfg.RAW_DIR if raw_dir is None else raw_dir
    out = {"set": {}, "remove": [], "kept": 0, "conflict": [], "waiting": [], "undated": [], "replaced": []}
    if not raw_dir.exists():
        return out

    field = {}                                        # day -> its race_predictions dict or None
    for f in sorted(raw_dir.glob(f"{_RAW_PREFIX}*.json")):
        day = f.stem[len(_RAW_PREFIX):]
        if not _valid_date(day):
            continue
        try:
            field[day] = _field_of(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            log.debug(f"  Prediction scan: {f.name} unreadable, skipped: {e}")

    own = {d for d, p in field.items() if p is not None and p.get("calendarDate") == d}
    out["kept"] = len(own)
    carriers = {}                                     # date of the prediction -> [(day, prediction)]
    for day, p in field.items():
        if p is None or day in own:
            continue
        target = p.get("calendarDate")
        if not _valid_date(target):
            out["undated"].append(day)
            continue
        carriers.setdefault(target, []).append((day, p))

    remove, unsettled = set(), set(out["undated"])    # unsettled: days that carry a prediction nobody can place
    for target, lst in sorted(carriers.items()):
        if len({_canon(p) for _, p in lst}) > 1:
            out["conflict"].append(target)
            unsettled.update(d for d, _ in lst)
            continue
        if target not in field:                       # no raw day of that date (yet)
            out["waiting"].extend(d for d, _ in lst)
            unsettled.update(d for d, _ in lst)
            continue
        if target not in own:
            out["set"][target] = lst[0][1]
        remove.update(d for d, _ in lst)
    out["remove"] = sorted(remove - set(out["set"]))
    # An unsettled carrier that is itself the target of another prediction gets that prediction (a day with
    # a prediction of its own date is worth more than a copy for a day that cannot take it); what it carried
    # is then gone from raw/ and stays only in source/ and the safety copy: reported, never silent.
    out["replaced"] = sorted(unsettled & set(out["set"]))
    out["undated"] = sorted(d for d in out["undated"] if d not in out["set"])
    out["waiting"] = sorted(d for d in out["waiting"] if d not in out["set"])
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Repair
# ══════════════════════════════════════════════════════════════════════════════

def repair_predictions(dry_run: bool = False, should_stop=None, quality_data=None) -> dict:
    """
    Places the predictions on their own day and removes the misdated copies (see the module docstring).
    Always scans anew — never acts on an earlier finding.

    dry_run      : True → nothing is written, no safety copy is made; the result lists what would change.
    should_stop  : optional callable; when it returns True before the write nothing is written, when it
                   returns True during the loop the loop ends after the current day (days already
                   written are still recorded).
    quality_data : the quality log dict of the caller (garmin_collector.main passes its own): the labels
                   are set on that very object and saved. Without it the log is loaded here.

    Returns a dict:
      set, removed int   — days that got a prediction of their own date / lost a misdated copy
                           (dry run: how many would)
      failed       int   — days that could not be written, or 1 when the safety copy / the log save failed
      kept         int   — days that were already correct
      conflict, waiting, undated — what stays untouched (see find_candidates)
      safety_copy  str | None — name of the ZIP in backup/migration
      reason       str   — set when nothing was written although days were repairable
      stopped      bool
    """
    found = find_candidates()
    plan_set, plan_remove = found["set"], found["remove"]
    res = {"set": len(plan_set), "removed": len(plan_remove), "failed": 0, "kept": found["kept"],
           "conflict": found["conflict"], "waiting": found["waiting"], "undated": found["undated"],
           "replaced": found["replaced"], "safety_copy": None, "stopped": False}

    for d in found["replaced"]:
        log.warning(f"  Prediction repair: {d} — carries a prediction that cannot be placed; it gets the "
                    f"prediction of its own date instead (the original answer stays in source/)")
    for target in found["conflict"]:
        log.warning(f"  Prediction repair: prediction dated {target} differs between its copies, left as it is")
    for d in found["undated"]:
        log.warning(f"  Prediction repair: {d} — prediction without a usable date, left as it is")
    if found["waiting"]:
        log.info(f"  Prediction repair: {len(found['waiting'])} day(s) carry a prediction of a day that has no "
                 f"raw file yet, left as they are")

    todo = sorted(set(plan_set) | set(plan_remove))
    if not todo:
        log.info("  Prediction repair: no day needs correction.")
        return res

    if dry_run:
        log.info(f"  Prediction repair (dry run): {len(plan_set)} day(s) would get their own prediction, "
                 f"{len(plan_remove)} day(s) would lose a copy of another day's")
        return res

    if should_stop is not None and should_stop():
        res["stopped"] = True
        return res

    copy = snapshot.create_snapshot(should_stop, stores=("raw", "quality_log"))
    if not copy.get("ok") or copy.get("path") is None:
        res["failed"] = 1
        res["reason"] = copy.get("reason") or "no safety copy was made"
        log.error(f"  Prediction repair: no safety copy ({res['reason']}) — nothing written")
        return res
    res["safety_copy"] = copy["path"].name
    log.info(f"  Prediction repair: safety copy {res['safety_copy']}")

    written_set, written_removed, failed = 0, 0, 0
    labels = {}
    total = len(todo)
    log.info(f"  Prediction repair: {total} day(s) will be corrected")
    with quality.QUALITY_LOCK:
        qdata = quality_data if quality_data is not None else quality._load_quality_log()
        try:
            for i, d in enumerate(todo, 1):
                if should_stop is not None and should_stop():
                    res["stopped"] = True
                    log.info(f"  Prediction repair: stopped after {i - 1} of {total} day(s).")
                    break
                try:
                    raw_path = cfg.RAW_DIR / f"{_RAW_PREFIX}{d}.json"
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    now = _field_of(raw)
                    if d in plan_set:
                        if now is not None and now.get("calendarDate") == d:
                            log.info(f"  [{i}/{total}] {d} — already has its own prediction, skipped")
                            continue
                        raw[FIELD] = dict(plan_set[d])
                        label = "medium"
                    else:
                        if now is None or now.get("calendarDate") == d:
                            log.info(f"  [{i}/{total}] {d} — no misdated copy any more, skipped")
                            continue
                        raw.pop(FIELD, None)
                        label = "failed"
                    if not writer.write_day(raw, normalizer.summarize(raw), d):
                        raise OSError("write_day reported a failure")
                    labels[d] = label
                    if d in plan_set:
                        written_set += 1
                    else:
                        written_removed += 1
                    log.info(f"  [{i}/{total}] {d} — {'own prediction set' if label == 'medium' else 'copy removed'} ok")
                except Exception as e:
                    failed += 1
                    log.error(f"  [{i}/{total}] {d} — error: {e}")
        finally:
            if labels:
                quality.touch_last_checked(qdata, labels)
                quality.record_field_labels(qdata, labels, FIELD)
                if quality._save_quality_log(qdata) is False:
                    failed += 1
                    res["reason"] = "the quality log could not be saved"
                    log.error("  Prediction repair: the quality log could not be saved")
    res["set"], res["removed"], res["failed"] = written_set, written_removed, failed
    log.info(f"  Prediction repair complete: {written_set} day(s) got their own prediction, {written_removed} "
             f"lost a copy of another day's, {failed} failed, {len(res['conflict'])} date(s) with differing "
             f"copies, {len(res['waiting'])} waiting, {len(res['undated'])} undated — left as they are.")
    return res
