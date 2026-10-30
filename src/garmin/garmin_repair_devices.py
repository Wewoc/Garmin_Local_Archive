#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_repair_devices.py

DEVICE-REPAIR v1.7.6.9 — REMOVABLE.

Gives quality-log entries without a device_id the device that recorded the day, read from the FIT
originals the export import kept. Until now such days (all days of the Garmin export that the API never
delivered a training status for) stayed "unknown" in the device table.

Where the device comes from (E7): a day file in bulk/raw names in `source_files` the SHA-256 of every
FIT file that put a heart-rate sample on that day; the original of each lies in bulk/source/<xx>/<hash>.fit,
and the serial number in its first `file_id` message (field 3) is the recording device. The serial is
the same number as the account's `deviceId` (measured on one account: 1559 of 1562 days that have both
agree, the three others are overlap days). The day boundaries are those of the heart-rate series.

Rules (nothing is guessed):
  - only entries WITHOUT a device_id are looked at; an id that is there stays, whatever the FIT says
  - exactly one serial on the day and every original of the day readable → the id is set
  - two serials (worn in parallel / a change on that day) → "two", stays unknown, reported
  - no bulk day file, a damaged one, or an original that is missing / unreadable / without a serial →
    stays unknown, reported ("no_file" / "incomplete"); no reading across neighbouring days
  - the entry gets `device_id` (text), `device_name` "" and `device_source` "export_fit"; everything
    else, including `last_checked`, stays. The names of the devices are given in the app (naming by id).

Delegation, nothing is written here directly (Sole-Write-Authority):
  quality log → garmin_quality.record_device_from_files + _save_quality_log + save_device_table, under
                one continuous QUALITY_LOCK hold, saved once. The caller's own quality_data is used
                when it is passed (a copy loaded here would be overwritten by the caller's next save).
  safety copy → garmin_migration_snapshot.create_snapshot(stores=("quality_log",)) BEFORE the lock:
                no copy, no write. The way back is restore_snapshot() of that ZIP.
The caller must not hold QUALITY_LOCK (it is not re-entrant). No API call, no login. bulk/ is only read.

Public API:
  find_candidates(quality_data=None, quality_log_file=None, bulk_raw_dir=None, bulk_source_dir=None) -> dict
        — read-only: {"one": {date: id}, "two": {date: [ids]}, "no_file": [...], "incomplete": [...]}
  repair_devices(dry_run=False, should_stop=None, quality_data=None) -> dict

REMOVAL LIST (everything that belongs to this repair carries the marker "DEVICE-REPAIR v1.7.6.9"):
  - this file and tests/test_repair_devices.py
  - compiler/build_manifest.py: file list entry + SCRIPT_SIGNATURES_BASE entry
  - run_tests.ps1 and tests/conftest.py: the test file entry
  - garmin_collector.py: the section "Device repair" with _run_device_repair(), the step "3h" in main()
    (environment variable GARMIN_DEVICE_REPAIR) and its entry in the build_manifest.py signatures;
    the tests "4u main device repair" in tests/test_collector.py
  - app/panel_archive.py: _check_device_repair() (popup)
  - app/outputs/sync.py: the three lines in run_collector() that set GARMIN_DEVICE_REPAIR
  - scheduler/daily_update.py: _check_device_repair() and step "4d" in main()
  - tests/test_qt_app.py: the class TestDeviceRepairHooks
  - docs sections of this repair (REFERENCE_GARMIN, MAINTENANCE_GARMIN); CHANGELOG entries stay
  What stays: garmin_quality.record_device_from_files / set_device_name, the `device_source` rule in
  _upsert_quality, `stores=` in garmin_migration_snapshot.create_snapshot, naming by id in the app.
"""

import json
import logging
import re
from datetime import date

import garmin_bulk_fit_reader as fit_reader
import garmin_config as cfg
import garmin_migration_snapshot as snapshot
import garmin_quality as quality

log = logging.getLogger(__name__)

DEVICE_SOURCE = "export_fit"
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_FILE_ID = 0          # global message number of file_id
_SERIAL  = 3          # field number of serial_number in file_id


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


def _serial_of(file_hash: str, source_dir):
    """The serial number (text) in the first file_id of one original, or None when the original is
    missing, not a readable FIT file or has no serial."""
    path = source_dir / file_hash[:2] / f"{file_hash}.fit"
    try:
        fit = fit_reader.parse_fit(path.read_bytes(), wanted={_FILE_ID})
    except (OSError, fit_reader.FitFormatError):
        return None
    records = fit.messages.get(_FILE_ID) or []
    serial = records[0].get(_SERIAL) if records else None
    if isinstance(serial, bool) or not isinstance(serial, int) or serial <= 0:
        return None
    return str(serial)


def _entries_without_id(quality_data, quality_log_file) -> list:
    """ISO dates of the entries that have no device_id, sorted. From the caller's object, or read from the
    log file (a plain read, nothing is migrated or saved)."""
    if quality_data is None:
        path = cfg.QUALITY_LOG_FILE if quality_log_file is None else quality_log_file
        try:
            quality_data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    days = quality_data.get("days") if isinstance(quality_data, dict) else None
    if not isinstance(days, list):
        return []
    return sorted({e["date"] for e in days
                   if isinstance(e, dict) and _valid_date(e.get("date")) and not e.get("device_id")})


# ══════════════════════════════════════════════════════════════════════════════
#  Detection (read-only)
# ══════════════════════════════════════════════════════════════════════════════

def find_candidates(quality_data=None, quality_log_file=None, bulk_raw_dir=None, bulk_source_dir=None) -> dict:
    """
    Looks at every quality-log entry without a device_id and sorts it (see the module docstring):
      "one"        {date: id}      exactly one serial, every original readable — can be repaired
      "two"        {date: [ids]}   two or more serials — stays unknown
      "no_file"    [dates]         no bulk day file — stays unknown
      "incomplete" [dates]         day file damaged, or an original missing / unreadable / without a
                                   serial (and not two serials already) — stays unknown
    Nothing is written. The originals are read in full (the FIT reader checks the CRC of the whole
    file): the first run over an archive of 1,300 such days takes a few seconds, later runs only look at
    the days that stayed unknown.

    quality_data      : the caller's quality log; without it the log file is read.
    quality_log_file / bulk_raw_dir / bulk_source_dir (Path, optional): folders to look at instead of the
    configured ones. The GUI popup and the scheduler pass the archive of the current settings, so they
    do not depend on what garmin_config was imported with.
    """
    raw_dir    = cfg.BULK_RAW_DIR    if bulk_raw_dir    is None else bulk_raw_dir
    source_dir = cfg.BULK_SOURCE_DIR if bulk_source_dir is None else bulk_source_dir
    out = {"one": {}, "two": {}, "no_file": [], "incomplete": []}
    cache = {}                                   # hash -> serial | None, one read per original

    for d in _entries_without_id(quality_data, quality_log_file):
        path = raw_dir / f"{cfg.BULK_FILE_PREFIX}{d}.json"
        if not path.exists():
            out["no_file"].append(d)
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            hashes = doc.get("source_files") if isinstance(doc, dict) else None
        except (OSError, ValueError):
            hashes = None
        if (not isinstance(hashes, list) or not hashes
                or not all(isinstance(h, str) and _HASH_RE.fullmatch(h) for h in hashes)):
            out["incomplete"].append(d)
            continue
        serials, complete = set(), True
        for h in hashes:
            if h not in cache:
                cache[h] = _serial_of(h, source_dir)
            if cache[h] is None:
                complete = False
            else:
                serials.add(cache[h])
        if len(serials) > 1:
            out["two"][d] = sorted(serials)
        elif complete and len(serials) == 1:
            out["one"][d] = next(iter(serials))
        else:
            out["incomplete"].append(d)
    return out


def days_per_device(assign: dict) -> dict:
    """{id: number of days}, most days first. `assign` is the "one" part of find_candidates()."""
    counts = {}
    for dev in assign.values():
        counts[dev] = counts.get(dev, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# ══════════════════════════════════════════════════════════════════════════════
#  Repair
# ══════════════════════════════════════════════════════════════════════════════

def repair_devices(dry_run: bool = False, should_stop=None, quality_data=None) -> dict:
    """
    Sets device_id / device_source on the entries that find_candidates() puts under "one" (see the
    module docstring). Always scans anew — never acts on an earlier finding.

    dry_run      : True → nothing is written, no safety copy is made; the result lists what would change.
    should_stop  : optional callable; when it returns True before the write, nothing is written.
    quality_data : the quality log dict of the caller (garmin_collector.main passes its own): the
                   assignment is made on that very object and saved. Without it the log is loaded here.

    Returns a dict:
      ok          int   — days that got a device (dry run: days that would)
      failed      int   — 1 when the write or its safety copy failed, else 0
      per_device  dict  — {id: days}
      two, no_file, incomplete — the days that stay unknown (see find_candidates)
      safety_copy str | None — name of the ZIP in backup/migration
      reason      str   — set when nothing was written although days were repairable
      stopped     bool
    """
    found = find_candidates(quality_data=quality_data)
    one = found["one"]
    res = {"ok": 0, "failed": 0, "per_device": days_per_device(one), "two": found["two"],
           "no_file": found["no_file"], "incomplete": found["incomplete"],
           "safety_copy": None, "stopped": False}

    for d, ids in found["two"].items():
        log.warning(f"  Device repair: {d} — two devices {', '.join(ids)}, left unknown")
    for d in found["incomplete"]:
        log.warning(f"  Device repair: {d} — originals of the day incomplete, left unknown")
    if found["no_file"]:
        log.info(f"  Device repair: {len(found['no_file'])} day(s) without a bulk day file, left unknown")

    if not one:
        log.info("  Device repair: no day can be given a device.")
        return res

    if dry_run:
        log.info(f"  Device repair (dry run): {len(one)} day(s) would get a device "
                 f"({len(res['per_device'])} device(s))")
        res["ok"] = len(one)
        return res

    if should_stop is not None and should_stop():
        res["stopped"] = True
        return res

    copy = snapshot.create_snapshot(should_stop, stores=("quality_log",))
    if not copy.get("ok") or copy.get("path") is None:
        res["failed"] = 1
        res["reason"] = copy.get("reason") or "no safety copy was made"
        log.error(f"  Device repair: no safety copy of the quality log ({res['reason']}) — nothing written")
        return res
    res["safety_copy"] = copy["path"].name
    log.info(f"  Device repair: safety copy {res['safety_copy']}")

    with quality.QUALITY_LOCK:
        qdata = quality_data if quality_data is not None else quality._load_quality_log()
        done = quality.record_device_from_files(qdata, one, DEVICE_SOURCE)
        if done["assigned"]:
            saved = quality._save_quality_log(qdata)
            if saved is False:
                res["failed"] = 1
                res["reason"] = "the quality log could not be saved"
                log.error("  Device repair: the quality log could not be saved")
                return res
            quality.save_device_table(qdata)
    res["ok"] = done["assigned"]
    if done["names_dropped"]:
        log.info(f"  Device repair: {done['names_dropped']} name(s) of the unknown group dropped "
                 f"(a name belongs to a device id, give them in the app)")
    log.info(f"  Device repair complete: {res['ok']} day(s) got a device, {len(res['two'])} with two devices, "
             f"{len(res['no_file'])} without bulk day file, {len(res['incomplete'])} incomplete — left unknown.")
    return res
