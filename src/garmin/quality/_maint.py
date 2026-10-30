#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin/quality/_maint.py

Maintenance sub-module for garmin_quality.
Upsert, first_day detection, archive cleanup.

Internal — import only via garmin_quality (facade).
"""

import logging
from datetime import date, datetime

import garmin_config as cfg

log = logging.getLogger(__name__)

# Quality rank — defined here, re-exported via facade (without leading underscore)
# Used for downgrade protection in _upsert_quality and in garmin_collector.
QUALITY_RANK = {"high": 2, "standard": 1, "failed": 0}


def is_downgrade(new_label: str | None, existing_label: str | None) -> bool:
    """
    Returns True if new_label ranks lower than existing_label — writing
    new_label would downgrade already-stored data. Missing/unknown labels
    rank as lowest (matches the QUALITY_RANK.get(..., 0) fallback used
    throughout this module).

    Canonical downgrade-rank comparison — v1.6.5.7 sibling-sweep finding.
    Previously duplicated in garmin_collector.py::_check_downgrade() and
    export/regenerate_raw.py::_rank()/_existing_label(); both now call this.
    """
    return QUALITY_RANK.get(new_label, 0) < QUALITY_RANK.get(existing_label, 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Upsert
# ══════════════════════════════════════════════════════════════════════════════

def _upsert_quality(data: dict, day: date, quality: str, reason: str,
                    written: bool = None, source: str = "legacy",
                    fields: dict = None,
                    validator_result: dict = None,
                    device_id: str | None = None,
                    device_name: str | None = None,
                    prev_high: bool = False,
                    backfilled_fields: dict = None,
                    device_source: str | None = None) -> None:
    """
    Adds or updates a day entry in the quality log.
      - 'failed':   increments attempts, sets recheck=True
      - 'standard': sets recheck based on prev_high + age window (v1.5.7)
      - 'high':     sets recheck=False (intraday present — no retry needed)

    written : bool | None
      True  — writer wrote both files successfully
      False — label was 'failed', writer failed, or write was skipped
      None  — unknown (backfill, scan, or pre-v1.2.1 entry)

    source : str
      Origin of the data: "api" | "bulk" | "csv" | "manual" | "legacy"
      Always overwrites the existing value — the most recent write wins.

    device_id : str | None
      Numeric device ID string from training_status → latestTrainingStatusData.
      None = training_status absent or no devices found.

    device_name : str | None
      Human-readable device name — stored alongside device_id.

    device_source : str | None
      Origin of device_id when it did not come from the account's own
      data (v1.7.6.9, e.g. "export_fit"). `entry["device_source"]` always
      describes the `device_id` of the same entry: whoever writes a
      device_id here replaces the key with this value or, with None,
      removes it. A call without a device_id leaves both untouched.

    prev_high : bool
      True if the previous calendar day has quality == "high".
      Used to determine whether a 'standard' day warrants a recheck.
      Lookup is done by the caller (garmin_collector) — not here.

    validator_result : dict | None
      Complete result object from garmin_validator.validate().
      Three fields are extracted and stored per day entry:
        validator_result       — "ok" | "warning" | "critical"
        validator_issues       — list of structured issue dicts (empty if ok)
        validator_schema_version — schema version used for validation
      None = validator was not run (legacy entries, backfill).

    backfilled_fields : dict | None
      Marks which optional fields were added to an already-archived day via
      a dedicated backfill pass (e.g. {"steps": "<ISO date>"}). Merged
      additively into any existing backfilled_fields on the entry — never
      overwrites a prior marker. None = no field was backfilled this call
      (the normal case for every regular sync day).
    """
    day_str   = day.isoformat()
    today_str = date.today().isoformat()
    now_str   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Extract validator fields from result object
    v_status  = validator_result.get("status")         if validator_result else None
    v_issues  = validator_result.get("issues", [])     if validator_result else None
    v_version = validator_result.get("schema_version") if validator_result else None

    for entry in data["days"]:
        if entry.get("date") == day_str:
            existing_rank = QUALITY_RANK.get(entry.get("quality", "failed"), 0)
            new_rank      = QUALITY_RANK.get(quality, 0)
            if new_rank < existing_rank:
                log.info(f"    ℹ {day}: quality downgrade blocked ({entry['quality']} → {quality})")
                return
            entry["quality"]      = quality
            entry["reason"]       = reason
            entry["write"]        = written
            entry["source"]       = source
            entry["last_checked"] = today_str
            if device_id is not None:
                entry["device_id"]   = device_id
                entry["device_name"] = device_name or ""
                if device_source is not None:
                    entry["device_source"] = device_source
                else:
                    entry.pop("device_source", None)
            if fields is not None:
                _downgrades = fields.pop("_downgrade_reasons", None)
                entry["fields"]   = fields
                if _downgrades:
                    entry["field_downgrades"] = _downgrades
                elif "field_downgrades" in entry:
                    del entry["field_downgrades"]  # re-assessed clean — drop stale marker
            if backfilled_fields is not None:
                entry["backfilled_fields"] = {**entry.get("backfilled_fields", {}), **backfilled_fields}
            if validator_result is not None:
                entry["validator_result"]         = v_status
                entry["validator_issues"]         = v_issues
                entry["validator_schema_version"] = v_version
            if quality == "failed":
                entry["attempts"]     = entry.get("attempts", 0) + 1
                entry["last_attempt"] = now_str
                entry["recheck"]      = True
            elif quality == "standard":
                day_age = (date.today() - day).days
                entry["recheck"]      = (day_age < cfg.INTRADAY_RETRY_WINDOW_DAYS and prev_high)
                entry["last_attempt"] = now_str
            else:  # "high"
                entry["recheck"]      = False
                entry["last_attempt"] = now_str
            return

    # New entry
    attempts = 1 if quality == "failed" else 0
    if quality == "failed":
        recheck_new = True
    elif quality == "standard":
        day_age = (date.today() - day).days
        recheck_new = (day_age < cfg.INTRADAY_RETRY_WINDOW_DAYS and prev_high)
    else:  # "high"
        recheck_new = False
    entry = {
        "date":         day_str,
        "quality":      quality,
        "reason":       reason,
        "write":        written,
        "source":       source,
        "recheck":      recheck_new,
        "attempts":     attempts,
        "last_checked": today_str,
        "last_attempt": now_str if quality == "failed" else None,
        "device_id":    device_id,
        "device_name":  device_name or "",
    }
    if device_id is not None and device_source is not None:
        entry["device_source"] = device_source
    if fields is not None:
        _downgrades = fields.pop("_downgrade_reasons", None)
        entry["fields"] = fields
        if _downgrades:
            entry["field_downgrades"] = _downgrades
    if backfilled_fields is not None:
        entry["backfilled_fields"] = backfilled_fields
    if validator_result is not None:
        entry["validator_result"]         = v_status
        entry["validator_issues"]         = v_issues
        entry["validator_schema_version"] = v_version
    data["days"].append(entry)


# ══════════════════════════════════════════════════════════════════════════════
#  Public Transaction API
# ══════════════════════════════════════════════════════════════════════════════

def set_unknown_device_name(data: dict, name: str) -> int:
    """
    Sets device_name on all entries where device_id is None.
    Returns the number of entries updated.
    Caller is responsible for saving quality_log.json and device_table.json.
    """
    name = name.strip()
    count = 0
    for entry in data.get("days", []):
        if entry.get("device_id") is None:
            entry["device_name"] = name
            count += 1
    log.info(f"  set_unknown_device_name: {count} entries updated → '{name}'")
    return count


def set_device_name(data: dict, device_id: str, name: str) -> int:
    """
    Sets device_name on all entries whose device_id is `device_id` (v1.7.6.9,
    naming by ID). Only the name changes — never a device_id, device_source
    or any other key; entries of other devices and entries without a
    device_id are not touched. An empty id or an empty name changes nothing.
    Returns the number of entries updated.
    Caller is responsible for saving quality_log.json and device_table.json
    (same contract as set_unknown_device_name).
    """
    device_id = str(device_id or "").strip()
    name = (name or "").strip()
    if not device_id or not name:
        return 0
    count = 0
    for entry in data.get("days", []):
        if str(entry.get("device_id") or "") == device_id:
            entry["device_name"] = name
            count += 1
    log.info(f"  set_device_name: {count} entries of device {device_id} updated → '{name}'")
    return count


def record_device_from_files(data: dict, assignments: dict, source: str) -> dict:
    """
    Gives days that have no device_id the id found in the kept files of the day
    (v1.7.6.9, DEVICE-REPAIR). `assignments` is {ISO date: device id}; the id is
    stored as text. Per entry only `device_id`, `device_name` ("") and
    `device_source` (= `source`) change; a name the entry carried for the
    unknown group belongs to that group, not to this id, and is dropped.

    Never overwrites: an entry that already has a device_id (any non-empty
    value) is skipped, a day without an entry is skipped and never created, an
    empty id is skipped. `last_checked`, `quality`, `source`, `write` and the
    log checksum stay as they are (the id is not part of a day's content).

    Returns {"assigned": n, "skipped_has_id": n, "skipped_empty_id": n,
    "skipped_no_entry": n, "names_dropped": n}. Does NOT save — the caller holds QUALITY_LOCK from load
    to save and saves once (same contract as touch_last_checked).
    """
    by_date = {e.get("date"): e for e in data.get("days", []) if isinstance(e, dict)}
    res = {"assigned": 0, "skipped_has_id": 0, "skipped_empty_id": 0, "skipped_no_entry": 0,
           "names_dropped": 0}
    for day, dev in assignments.items():
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        dev_id = str(dev if dev is not None else "").strip()
        entry = by_date.get(key)
        if entry is None:
            res["skipped_no_entry"] += 1
            continue
        if not dev_id:
            res["skipped_empty_id"] += 1
            continue
        if entry.get("device_id"):
            res["skipped_has_id"] += 1
            continue
        if entry.get("device_name"):
            res["names_dropped"] += 1
        entry["device_id"]     = dev_id
        entry["device_name"]   = ""
        entry["device_source"] = source
        res["assigned"] += 1
    return res


def touch_last_checked(data: dict, days) -> int:
    """
    Sets `last_checked` to today on the entries of the given days — nothing
    else. `quality`, `source`, `recheck`, `write`, `attempts` and `fields`
    stay as they are, so the log checksum (date/quality/source/write) does
    not change either.

    Purpose: a day whose raw/summary content was corrected in place (repair
    or migration paths) has to be re-read by the MCP cache, which re-reads a
    day when its `last_checked` differs from the value it cached
    (mcp_update._sync_health_days). Rotation and recheck do not use
    `last_checked`.

    Generic by design — usable by any repair that rewrites archived days,
    not specific to one repair.

    `days`: iterable of date objects or ISO strings (YYYY-MM-DD). A day
    without an entry in the log is skipped, never created.
    Returns the number of entries touched. Does NOT save — the caller holds
    QUALITY_LOCK from load to save and saves once after the loop (same
    contract as set_unknown_device_name; avoids one log write plus backup
    snapshot per day).
    """
    today_str = date.today().isoformat()
    wanted = {d.isoformat() if hasattr(d, "isoformat") else str(d) for d in days}
    count = 0
    for entry in data.get("days", []):
        if entry.get("date") in wanted:
            entry["last_checked"] = today_str
            count += 1
    return count


def record_bulk_intraday(data: dict, days) -> int:
    """
    Marks days whose heart-rate series are in the bulk store (garmin_data/bulk,
    v1.7.6): `entry["bulk"]["intraday"]` = today's date (the import date) and
    `last_checked` = today. Nothing else on the entry changes — `quality`,
    `source`, `recheck`, `write`, `attempts` and `fields` stay, so the log
    checksum (date/quality/source/write) does not change either.

    `last_checked` is what makes the MCP cache read the day again
    (mcp_update._sync_health_days); without it a day imported into an
    archive the cache already knows would never show its series.

    `entry["bulk"]` is a dict of its own so later imports can add keys
    ("aggregates") without touching "intraday". A `bulk` value that is not a
    dict is replaced. Not to be confused with `source == "bulk"`, which marks
    days of the older JSON import.

    `days`: iterable of date objects or ISO strings (YYYY-MM-DD). A day
    without an entry in the log is skipped, never created.
    Returns the number of entries marked. Does NOT save — the caller holds
    QUALITY_LOCK from load to save and saves once (same contract as
    touch_last_checked).
    """
    return _record_bulk_mark(data, days, "intraday")


def record_bulk_aggregates(data: dict, days) -> int:
    """
    Marks days whose daily values (the JSON part of the export) are in the bulk store
    (garmin_data/bulk/aggregates, v1.7.6.1): `entry["bulk"]["aggregates"]` = today's date and
    `last_checked` = today — the same contract as record_bulk_intraday(), in the key of its own
    inside `entry["bulk"]`. Nothing else on the entry changes, the log checksum stays. A day
    without an entry is skipped, never created. Returns the number of entries marked.
    Does NOT save — the caller holds QUALITY_LOCK from load to save and saves once.
    """
    return _record_bulk_mark(data, days, "aggregates")


def _record_bulk_mark(data: dict, days, key: str) -> int:
    """The common part of record_bulk_intraday() and record_bulk_aggregates()."""
    today_str = date.today().isoformat()
    wanted = {d.isoformat() if hasattr(d, "isoformat") else str(d) for d in days}
    count = 0
    for entry in data.get("days", []):
        if entry.get("date") in wanted:
            bulk = entry.get("bulk")
            entry["bulk"] = {**bulk, key: today_str} if isinstance(bulk, dict) else {key: today_str}
            entry["last_checked"] = today_str
            count += 1
    return count


def unmarked_bulk_days(data: dict, days, key: str = "intraday") -> list:
    """
    The days of `days` that have an entry in the log but no
    `entry["bulk"][key]` mark (v1.7.6.1, F-3; `key` is "intraday" (default) or "aggregates"): the
    days whose data are in the bulk store but which the MCP cache would never read again. Only
    looks, changes nothing. A day without an entry is not listed (entries are
    never created here); a `bulk` value that is not a dict, or one without
    the key, counts as unmarked.

    `days`: iterable of date objects or ISO strings (YYYY-MM-DD).
    Returns the dates as sorted ISO strings.
    """
    wanted = {d.isoformat() if hasattr(d, "isoformat") else str(d) for d in days}
    unmarked = []
    for entry in data.get("days", []):
        if entry.get("date") in wanted:
            bulk = entry.get("bulk")
            if not (isinstance(bulk, dict) and bulk.get(key)):
                unmarked.append(entry["date"])
    return sorted(unmarked)


def catch_up_bulk_intraday(data: dict, days) -> int:
    """
    Marks the days of `days` that are still unmarked (`unmarked_bulk_days`) with
    `record_bulk_intraday` (v1.7.6.1, F-3): makes good a mark that failed or
    could not be made when the series were written. Days that already carry
    the mark are left alone, so their `last_checked` stays. Returns the number
    of entries marked. Does NOT save — same contract as record_bulk_intraday.
    """
    return record_bulk_intraday(data, unmarked_bulk_days(data, days))


def catch_up_bulk_aggregates(data: dict, days) -> int:
    """
    catch_up_bulk_intraday() for the daily values: marks the days of `days` that carry no
    `entry["bulk"]["aggregates"]` yet with record_bulk_aggregates(). Days that already carry the
    mark keep it and their `last_checked`. Returns the number of entries marked. Does NOT save.
    """
    return record_bulk_aggregates(data, unmarked_bulk_days(data, days, "aggregates"))


def record_field_backfill_failure(data: dict, day: date, field: str) -> int:
    """
    Increments the failed-attempt counter for one field's backfill pass
    (`entry["field_backfill_attempts"][field]` in quality_log.json).
    Returns the new count. Persists immediately (own `_save_quality_log`
    call) — same "record and persist right away" contract as
    `record_attempt()`.

    Separate from `attempts` / `_upsert_quality()`'s day-level failed-
    quality counter — this tracks failed attempts of a single per-field
    backfill pass (e.g. steps_backfill's get_steps_data call returning no
    data), independent of the day's overall quality label. Generic by
    design — usable by any per-field backfill mode (steps_backfill today,
    intended for the planned bulk structural backfill too), not steps-
    specific.

    Give-up threshold (mirrors bulk_recheck's "attempts >= 2 →
    recheck=False" pattern) is enforced by the caller (the relevant
    timer_run_*_backfill candidate filter), not here — this function only
    counts and persists.

    No-op (returns 0) if no entry exists for `day` — a field-backfill pass
    only ever patches an already-archived day, never creates one.
    """
    from quality._io import _save_quality_log
    day_str = day.isoformat()
    for entry in data.get("days", []):
        if entry.get("date") == day_str:
            attempts = entry.get("field_backfill_attempts") or {}
            attempts[field] = attempts.get(field, 0) + 1
            entry["field_backfill_attempts"] = attempts
            _save_quality_log(data)
            return attempts[field]
    return 0


def record_field_backfill_failures(data: dict, day: date, fields: list) -> dict:
    """
    Batched sibling of record_field_backfill_failure() — increments the
    failed-attempt counter for several fields' backfill passes on the
    same day in one call, persisting (_save_quality_log(), including its
    backup_quality_log() snapshot + year-consolidation scan) exactly
    once instead of once per field.

    Added after a live run showed _run_bulk_field_backfill() calling the
    singular function once per still-failing BULK_GAP_FIELDS entry — up
    to 7 per day — triggering 7 redundant full quality_log.json writes
    and backup snapshots for a single day processed. steps_backfill only
    ever tracks one field ("steps"), so it keeps using the singular
    function; this one is for callers that may need several fields at
    once.

    Returns {field: new_count} for every field in `fields`, or {} (no
    call to _save_quality_log()) if no entry exists for `day` — same
    "day must already be archived" contract as the singular function.
    """
    from quality._io import _save_quality_log
    day_str = day.isoformat()
    for entry in data.get("days", []):
        if entry.get("date") == day_str:
            attempts = entry.get("field_backfill_attempts") or {}
            result = {}
            for field in fields:
                attempts[field] = attempts.get(field, 0) + 1
                result[field] = attempts[field]
            entry["field_backfill_attempts"] = attempts
            _save_quality_log(data)
            return result
    return {}


def record_attempt(data: dict, day, label: str, reason: str,
                   written: bool = None, source: str = "api",
                   fields: dict = None,
                   validator_result: dict = None,
                   device_id: str | None = None,
                   device_name: str | None = None,
                   prev_high: bool = False,
                   backfilled_fields: dict = None,
                   device_source: str | None = None) -> None:
    """
    Public API — atomically upserts a quality entry and persists the log.
    Caller must already hold QUALITY_LOCK.
    Replaces the _upsert_quality + _save_quality_log call pattern.

    device_id         : numeric device ID string from training_status, or None.
    device_name       : human-readable device name, or None.
    prev_high         : True if the previous calendar day has quality == "high".
                        Used for 'standard' recheck logic — lookup done by caller.
    backfilled_fields : marks fields added via a backfill pass, e.g.
                        {"steps": "<ISO date>"}. None = no backfill this call.
    """
    from quality._io import _save_quality_log
    _upsert_quality(data, day, label, reason,
                    written=written, source=source,
                    fields=fields, validator_result=validator_result,
                    device_id=device_id, device_name=device_name,
                    prev_high=prev_high, backfilled_fields=backfilled_fields,
                    device_source=device_source)
    _save_quality_log(data)




# ══════════════════════════════════════════════════════════════════════════════
#  first_day
# ══════════════════════════════════════════════════════════════════════════════

def _set_first_day(data: dict, client) -> None:
    """
    Determines and persists first_day in quality_log.json.
    Only runs when first_day is not yet set.
    Resolution order: devices → account profile → SYNC_AUTO_FALLBACK → oldest local file.
    Does not overwrite an existing first_day value.
    client is passed as a parameter — this module does not import garmin API directly.
    """
    if data.get("first_day"):
        return  # Already set — never overwrite

    log.info("  first_day not set — detecting from account ...")
    first_day = None

    # 1. Try devices — only a value that parses as a real date is accepted; a
    # malformed first_used (hand-edited device_table, API glitch) is skipped with
    # a warning and falls through to the next source instead of becoming
    # first_day and later crashing a sync-mode-"auto" run's date.fromisoformat()
    # (ROADMAP v1.7.4.4 point 4). "unknown" is still skipped, as before.
    devices = data.get("devices") or []
    first_dates = []
    for d in devices:
        fu = d.get("first_used")
        if not fu or fu == "unknown":
            continue
        try:
            date.fromisoformat(fu)
        except (ValueError, TypeError):
            log.warning(f"  Ignoring malformed device first_used: {fu!r}")
            continue
        first_dates.append(fu)
    if first_dates:
        first_day = min(first_dates)
        log.info(f"  first_day from devices: {first_day}")

    # 2. Try account profile
    if not first_day and client:
        try:
            from quality._io import _safe_get
            profile = client.get_user_profile()
            reg = _safe_get(profile, "userInfo", "registrationDate")
            if reg:
                first_day = str(reg)[:10]
                log.info(f"  first_day from account profile: {first_day}")
        except Exception:
            pass

    # 3. Manual fallback from config
    if not first_day and cfg.SYNC_AUTO_FALLBACK:
        first_day = cfg.SYNC_AUTO_FALLBACK
        log.info(f"  first_day from SYNC_AUTO_FALLBACK: {first_day}")

    # 4. Oldest local file in raw/
    if not first_day and data.get("days"):
        known_dates = sorted(e["date"] for e in data["days"] if "date" in e)
        if known_dates:
            first_day = known_dates[0]
            log.info(f"  first_day from oldest local file: {first_day}")

    if first_day:
        data["first_day"] = first_day
        log.info(f"  ✓ first_day set to {first_day}")
    else:
        log.warning("  Could not determine first_day — will retry on next run.")

