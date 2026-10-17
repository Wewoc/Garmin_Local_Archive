#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_repair_resting_hr.py

RESTING-HR-REPAIR v1.7.5.7 — REMOVABLE.

One-time repair of the resting heart rate of days that were imported from the
Garmin GDPR export before v1.7.5.7. Until then garmin_import stored the export's
7-day average (`restingHeartRate`) as the resting heart rate of the day; the
value of the day is `currentDayRestingHeartRate` (fixed for new imports in
v1.7.5.7, Baustein 1). This module corrects the days that are already archived.

Detection (content only, no marker in the quality log):
  - raw/ `heart_rates` holds exactly the three keys the import writes
    (restingHeartRate, minHeartRate, maxHeartRate), and
  - raw/ `user_summary` does not contain `lastSevenDaysAvgRestingHeartRate`.
  A repaired day always carries that key (value or None), so a second run
  finds nothing.

Source of the corrected value (Weg A): the day's file in source/ — the
unmodified API response holds `heart_rates.restingHeartRate` (value of the
day) and `heart_rates.lastSevenDaysAvgRestingHeartRate`. A candidate without a
source/ file is reported and left unchanged (Weg B, the export as source, is
not part of this module).

What is changed per day — only these three places in raw/, the summary is
rebuilt from the patched raw:
  heart_rates.restingHeartRate               value of the day (key removed if
                                             source/ has no value)
  user_summary.restingHeartRate              the same value (None if missing)
  user_summary.lastSevenDaysAvgRestingHeartRate   the 7-day average / None
Everything else — min/max, intraday, quality label, source label — stays.

Delegation, nothing is written here directly (Sole-Write-Authority):
  raw/ + summary/ → garmin_writer.write_day (the raw backup follows, v1.7.5.6)
  quality log     → garmin_quality.touch_last_checked + _save_quality_log, under
                    one continuous QUALITY_LOCK hold; saved once after the loop
The caller must not hold QUALITY_LOCK (it is not re-entrant). No API call, no
login. A failing day never stops the loop.

Known limit: the per-field label `fields["heart_rates"]` in the quality log is
not recalculated. A day whose source/ file has no resting value would keep its
old label ("medium") although the value is now missing.

Public API:
  find_candidates(raw_dir=None, source_dir=None) -> dict
                                 — read-only: {"repairable": [...], "no_source": [...]}
  repair_resting_hr(dry_run=False, should_stop=None, quality_data=None) -> dict

REMOVAL LIST (everything that belongs to this repair carries the marker
"RESTING-HR-REPAIR v1.7.5.7" — grep for it):
  - this file and tests/test_repair_resting_hr.py
  - compiler/build_manifest.py: file list entry + SCRIPT_SIGNATURES_BASE entry
  - run_tests.ps1 and tests/conftest.py: the test file entry
  - garmin_collector.py: the section "Resting-HR repair" with
    _run_resting_hr_repair(), the step "3e" in main() (environment variable
    GARMIN_RESTING_HR_REPAIR), and its entry in the build_manifest.py
    signatures; the tests "4u main resting HR repair" in tests/test_collector.py
  - app/panel_archive.py: _check_resting_hr_repair() (popup)
  - app/outputs/sync.py: the three lines in run_collector() that set
    GARMIN_RESTING_HR_REPAIR after the popup
  - scheduler/daily_update.py: _check_resting_hr_repair() and step "4b" in main()
  - tests/test_qt_app.py: the class TestRestingHrRepairHooks
    (tests/test_repair_resting_hr.py sections 7 and 8 go with the file)
  - docs sections of this repair (REFERENCE_GARMIN, MAINTENANCE_GARMIN);
    CHANGELOG entries stay as history
  What stays: garmin_quality.touch_last_checked (generic) and the corrected
  mapping in garmin_import.
"""

import json
import logging
from datetime import date

import garmin_config as cfg
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

log = logging.getLogger(__name__)

_IMPORT_HR_KEYS = frozenset({"restingHeartRate", "minHeartRate", "maxHeartRate"})
SEVEN_DAY_KEY   = "lastSevenDaysAvgRestingHeartRate"
_RAW_PREFIX     = "garmin_raw_"
_SOURCE_PREFIX  = "garmin_source_"


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _valid_date(date_str: str) -> bool:
    if len(date_str) != 10:
        return False
    try:
        date.fromisoformat(date_str)
        return True
    except ValueError:
        return False


def _is_import_shaped(raw) -> bool:
    """True for a day in the import form that has not been repaired yet."""
    if not isinstance(raw, dict):
        return False
    hr = raw.get("heart_rates")
    us = raw.get("user_summary")
    return (isinstance(hr, dict) and set(hr) == _IMPORT_HR_KEYS
            and isinstance(us, dict) and SEVEN_DAY_KEY not in us)


def _num(value):
    """A real number or None — booleans and text do not count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _source_path(date_str: str, source_dir=None):
    return (cfg.SOURCE_DIR if source_dir is None else source_dir) / f"{_SOURCE_PREFIX}{date_str}.json"


def _read_source_values(date_str: str) -> tuple:
    """(value of the day, 7-day average) from the day's source/ file. Raises on a
    missing, unreadable or unusable file."""
    src = json.loads(_source_path(date_str).read_text(encoding="utf-8"))
    hr = src.get("heart_rates") if isinstance(src, dict) else None
    if not isinstance(hr, dict):
        raise ValueError("source/ file has no heart_rates section")
    return _num(hr.get("restingHeartRate")), _num(hr.get(SEVEN_DAY_KEY))


def _patch(raw: dict, day_value, seven_day_avg):
    """Applies the three changes to the raw dict in place; returns the old value."""
    hr = raw["heart_rates"]
    us = raw["user_summary"]
    old = hr.get("restingHeartRate")
    if day_value is None:
        hr.pop("restingHeartRate", None)
    else:
        hr["restingHeartRate"] = day_value
    us["restingHeartRate"] = day_value
    us[SEVEN_DAY_KEY] = seven_day_avg
    return old


# ══════════════════════════════════════════════════════════════════════════════
#  Detection (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def find_candidates(raw_dir=None, source_dir=None) -> dict:
    """
    Scans raw/ for days in the unrepaired import form.

    Returns {"repairable": [...], "no_source": [...]} — ISO dates, sorted.
    "repairable" means a source/ file exists; its content is not read here
    (keeps the scan cheap), an unusable file shows up as an error in
    repair_resting_hr(). Unreadable raw files are skipped.

    raw_dir / source_dir (Path, optional): folders to scan instead of the
    configured ones. The GUI popup and the scheduler pass the archive of the
    current settings, so they neither depend on what garmin_config was
    imported with nor reload it. Without them the configured folders are used.
    """
    repairable = []
    no_source  = []
    if raw_dir is None:
        raw_dir = cfg.RAW_DIR
    if not raw_dir.exists():
        return {"repairable": repairable, "no_source": no_source}

    for f in sorted(raw_dir.glob(f"{_RAW_PREFIX}*.json")):
        date_str = f.stem[len(_RAW_PREFIX):]
        if not _valid_date(date_str):
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug(f"  Resting HR scan: {f.name} unreadable, skipped: {e}")
            continue
        if not _is_import_shaped(raw):
            continue
        if _source_path(date_str, source_dir).exists():
            repairable.append(date_str)
        else:
            no_source.append(date_str)
    return {"repairable": repairable, "no_source": no_source}


# ══════════════════════════════════════════════════════════════════════════════
#  Repair
# ══════════════════════════════════════════════════════════════════════════════

def repair_resting_hr(dry_run: bool = False, should_stop=None, quality_data=None) -> dict:
    """
    Corrects the resting heart rate of all repairable days (see module docstring).

    dry_run      : True → nothing is written, the result lists what would change.
    should_stop  : optional callable; when it returns True the loop ends after
                   the current day (days already written are still recorded).
    quality_data : the quality log dict of the caller. A caller that keeps the
                   log in memory for the rest of its run (garmin_collector.main)
                   must pass it: the repair then marks the days on that very
                   object and saves it. A copy loaded here would be overwritten
                   by the caller's next save and the marks would be lost (the
                   MCP cache would never re-read the corrected days, found on
                   the real archive in v1.7.5.7). Without it the log is loaded
                   here, as before.

    Always scans anew — never acts on an earlier finding.

    Returns a dict:
      ok         int   — days corrected (dry run: days that would be corrected)
      failed     int   — days that could not be corrected
      no_source  list  — ISO dates without a source/ file, left unchanged
      items      list  — one dict per day: date, status, and old/new/avg where known
        status : "repaired" | "would_repair" | "error" | "skipped"
                 ("skipped" = the day is no longer in the import form)
        error items carry a "reason"
    """
    found     = find_candidates()
    todo      = found["repairable"]
    no_source = found["no_source"]
    items     = []
    ok        = 0
    failed    = 0
    total     = len(todo)

    for d in no_source:
        log.warning(f"  Resting HR repair: {d} — no source/ file, left unchanged")

    if total == 0:
        log.info("  Resting HR repair: no day needs correction.")
        return {"ok": 0, "failed": 0, "no_source": no_source, "items": items}

    if dry_run:
        log.info(f"  Resting HR repair (dry run): {total} day(s) can be corrected from source/")
        for d in todo:
            try:
                day_value, avg = _read_source_values(d)
                raw = json.loads((cfg.RAW_DIR / f"{_RAW_PREFIX}{d}.json").read_text(encoding="utf-8"))
                items.append({"date": d, "status": "would_repair",
                              "old": raw["heart_rates"].get("restingHeartRate"),
                              "new": day_value, "avg": avg})
                ok += 1
            except Exception as e:
                items.append({"date": d, "status": "error", "reason": str(e)})
                failed += 1
        return {"ok": ok, "failed": failed, "no_source": no_source, "items": items}

    log.info(f"  Resting HR repair: {total} day(s) will be corrected from source/")
    touched = []
    with quality.QUALITY_LOCK:
        qdata = quality_data if quality_data is not None else quality._load_quality_log()
        try:
            for i, d in enumerate(todo, 1):
                if should_stop is not None and should_stop():
                    log.info(f"  Resting HR repair: stopped after {i - 1} of {total} day(s).")
                    break
                try:
                    raw_path = cfg.RAW_DIR / f"{_RAW_PREFIX}{d}.json"
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    if not _is_import_shaped(raw):
                        items.append({"date": d, "status": "skipped"})
                        log.info(f"  [{i}/{total}] {d} — no longer in the import form, skipped")
                        continue
                    day_value, avg = _read_source_values(d)
                    old = _patch(raw, day_value, avg)
                    summary = normalizer.summarize(raw)
                    if not writer.write_day(raw, summary, d):
                        raise OSError("write_day reported a failure")
                    touched.append(d)
                    items.append({"date": d, "status": "repaired",
                                  "old": old, "new": day_value, "avg": avg})
                    log.info(f"  [{i}/{total}] {d} — {old} → {day_value} ok")
                    ok += 1
                except Exception as e:
                    items.append({"date": d, "status": "error", "reason": str(e)})
                    log.error(f"  [{i}/{total}] {d} — error: {e}")
                    failed += 1
        finally:
            if touched:
                quality.touch_last_checked(qdata, touched)
                quality._save_quality_log(qdata)

    log.info(f"  Resting HR repair complete: {ok} corrected, {failed} failed, "
             f"{len(no_source)} without source/.")
    return {"ok": ok, "failed": failed, "no_source": no_source, "items": items}
