#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_track_migration.py

TRACK-MIGRATION v1.7.6.3 — migration of the mixed archive into two tracks.

Until v1.7.6 the Garmin export was imported into raw/ (garmin_import), and the
bulk field backfill then merged API fields into those files. Since v1.7.6.1 the
export goes to the bulk store (bulk/aggregates, bulk/raw) and raw/ is meant to
hold API data only. This module finds the days of the old kind (scan_archive,
plan_migration: read-only) and moves them to the new layout (run_migration).

Detection (content only, no marker in the quality log; `source` in the quality log
cannot be used, the backfill sets it to "api"): a section of raw/ is in *import
form* when its keys are a subset of what garmin_import.parse_day() writes for it
(the key sets below are pinned by tests/test_track_migration.py). A day with at
least one section in import form is an import day:

  migrate     import day with a source/ file: raw/ is made again from source/ (API data)
  convert     import day without source/ and no other non-empty section (a pure import
              day): becomes an export-only day when the bulk store covers it
  unresolved  import day without source/ with API sections beside the import ones: cannot
              be separated exactly; left as it is and reported
  (api only)  every other day: not touched, only counted

Coverage (checked in the preview, per day, before anything may be written): every
section in import form must be held by the bulk store for the day (normalised like an
import day: every non-empty field of the raw section with the same value, the store may
have more), and for a "migrate" day every other non-empty section must equal the same
section of source/. A day that fails is blocked and named with the keys — so
the migration never removes data that exists nowhere else. A day without a usable
aggregates file is blocked ("no_aggregates": import the export first).

Refresh: days with an aggregates file whose resolved summary differs from the file in
summary/ (for instance the minimum/maximum heart rate the API leaves empty on old days,
F-11) are listed as "refresh" — summary/ only, raw/ stays.

Migration (run_migration): the ready "migrate" days get raw/ made again from source/ (the API data,
through garmin_writer.write_day, which also makes the resolved summary), the "refresh" days get
summary/ made again (garmin_writer.rebuild_summary, raw/ stays). Before the first write a snapshot of
raw/, summary/ and the quality log is made and checked (garmin_migration_snapshot; no snapshot, no
write). Day by day, year by year, a stop request ends the run after the current day; a day is
checked again right before it is written; a written raw file is read back and compared. A rerun finds
what is left (the detection is at the content). Blocked, unresolved and "convert" days are not touched.
The quality log is handled on the caller's quality_data (like the repairs): only last_checked of the
written days changes (so the MCP cache reads them again); label and fields of an entry are not
recalculated — a day whose recalculated label or fields would differ is only reported.

Public API:
  import_sections(raw) -> list            sections of a raw dict that are in import form
  classify_day(raw, has_source) -> str    "migrate" | "convert" | "unresolved" | "api"
  scan_archive(raw_dir=None, source_dir=None, agg_dir=None) -> dict
                                          cheap scan for the popup and the scheduler hint (read-only)
  pending(found) -> dict                  {"ready": [...], "waiting": [...]}: what the popup / the hint offers
  plan_migration(should_stop=None) -> dict
                                          full preview with coverage and summary changes (read-only)
  format_plan(plan) -> list[str]          log lines for the preview
  run_migration(dry_run, should_stop, quality_data) -> dict
                                          the migration; the only function that writes
  format_result(result) -> list[str]      log lines for the result

Delegation, nothing is written here directly (Sole-Write-Authority): raw/ + summary/ through
garmin_writer, the quality log through garmin_quality under one continuous QUALITY_LOCK hold (the
caller must not hold it), the safety copy through garmin_migration_snapshot. No API call, no login.
"""

import copy
import json
import logging
from collections import Counter
from datetime import date

import garmin_bulk_writer as bw
import garmin_config as cfg
import garmin_migration_snapshot as snapshot
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

log = logging.getLogger(__name__)

KIND_MIGRATE    = "migrate"
KIND_CONVERT    = "convert"
KIND_UNRESOLVED = "unresolved"
KIND_API        = "api"
KIND_REFRESH    = "refresh"

_RAW_PREFIX    = "garmin_raw_"
_SOURCE_PREFIX = "garmin_source_"
_SUMMARY_PREFIX = "garmin_"
_IGNORED_SUMMARY_KEYS = frozenset({"schema_version", "generated_by"})

# Key sets of the import form — what garmin_import.parse_day() writes (pinned in tests)
IMPORT_USER_SUMMARY = frozenset({
    "totalSteps", "dailyStepGoal", "totalKilocalories", "activeKilocalories", "totalDistanceMeters",
    "moderateIntensityMinutes", "vigorousIntensityMinutes", "floorsAscended", "restingHeartRate",
    "lastSevenDaysAvgRestingHeartRate", "minHeartRate", "maxHeartRate"})
IMPORT_STRESS = frozenset({
    "averageStressLevel", "maxStressLevel", "stressDuration", "restDuration", "lowDuration",
    "mediumDuration", "highDuration"})
IMPORT_SLEEP_DTO = frozenset({
    "sleepTimeSeconds", "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds"})
IMPORT_READINESS = frozenset({"level", "feedbackLong", "feedbackShort", "score"})
IMPORT_ACTIVITY = frozenset({
    "activityName", "activityType", "duration", "distance", "averageHR", "maxHR", "calories",
    "aerobicTrainingEffect", "anaerobicTrainingEffect"})
IMPORT_HEART_RATES = frozenset({"restingHeartRate", "minHeartRate", "maxHeartRate"})


# ══════════════════════════════════════════════════════════════════════════════
#  Form of a section
# ══════════════════════════════════════════════════════════════════════════════

def _is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _dict_within(value, keys) -> bool:
    return isinstance(value, dict) and bool(value) and set(value) <= keys


def _sleep_in_import_form(value) -> bool:
    return (isinstance(value, dict) and set(value) == {"dailySleepDTO"}
            and _dict_within(value["dailySleepDTO"], IMPORT_SLEEP_DTO))


def _activities_in_import_form(value) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(_dict_within(a, IMPORT_ACTIVITY) for a in value))


_IMPORT_FORM = {
    "heart_rates":        lambda v: _dict_within(v, IMPORT_HEART_RATES),
    "stress":             lambda v: _dict_within(v, IMPORT_STRESS),
    "user_summary":       lambda v: _dict_within(v, IMPORT_USER_SUMMARY),
    "sleep":              _sleep_in_import_form,
    "training_readiness": lambda v: _dict_within(v, IMPORT_READINESS),
    "activities":         _activities_in_import_form,
}


def import_sections(raw) -> list:
    """The sections of a raw dict that are in import form (sorted). A raw that is no dict: []."""
    if not isinstance(raw, dict):
        return []
    return sorted(k for k, in_form in _IMPORT_FORM.items() if k in raw and in_form(raw[k]))


def classify_day(raw, has_source: bool) -> str:
    """"migrate", "convert", "unresolved" or "api" (see the module docstring)."""
    imp = import_sections(raw)
    if not imp:
        return KIND_API
    if has_source:
        return KIND_MIGRATE
    others = [k for k, v in raw.items() if k != "date" and k not in imp and not _is_empty(v)]
    return KIND_UNRESOLVED if others else KIND_CONVERT


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


def _covers(export_value, raw_value) -> bool:
    """True when the export's section holds everything the raw section holds: for dicts every non-empty
    field of the raw section with the same value (the export may have more fields, a newer parse adds
    some), for lists the same entries in any order (the store may hold them sorted differently; an
    entry that occurs twice must occur twice), for everything else equality."""
    if isinstance(raw_value, dict) and isinstance(export_value, dict):
        return all(_is_empty(v) or export_value.get(k) == v for k, v in raw_value.items())
    if isinstance(raw_value, list) and isinstance(export_value, list):
        return _entries(export_value) == _entries(raw_value)
    return export_value == raw_value


def _entries(items: list) -> list:
    """The entries of a list as sorted JSON strings (an order-free comparison that counts duplicates)."""
    return sorted(json.dumps(i, sort_keys=True, ensure_ascii=True, default=str) for i in items)


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _flat(value, prefix="") -> dict:
    out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, dict):
                out.update(_flat(v, f"{prefix}{k}."))
            else:
                out[f"{prefix}{k}"] = v
    return out


def _summary_changes(old: dict, new: dict) -> list:
    """The dotted fields in which two summaries differ (schema_version and generated_by do not count)."""
    fo, fn = _flat(old), _flat(new)
    return sorted(k for k in set(fo) | set(fn)
                  if fo.get(k) != fn.get(k) and k.split(".")[0] not in _IGNORED_SUMMARY_KEYS)


def _old_summary(date_str: str) -> dict:
    try:
        data = _read_json(cfg.SUMMARY_DIR / f"{_SUMMARY_PREFIX}{date_str}.json")
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ══════════════════════════════════════════════════════════════════════════════
#  Scan (cheap)
# ══════════════════════════════════════════════════════════════════════════════

def scan_archive(raw_dir=None, source_dir=None, agg_dir=None) -> dict:
    """
    Reads raw/ and looks at the file names in source/ and bulk/aggregates; for the popup and the
    scheduler hint. Nothing is written. A raw file that cannot be read is listed, not guessed.

    Returns {"migrate": [...], "convert": [...], "unresolved": [...], "unreadable": [...],
             "no_aggregates": [...], "api_only": int} — ISO dates, sorted. "no_aggregates" are the
    migrate/convert days without an aggregates file (blocked until the export is imported).

    raw_dir / source_dir / agg_dir (Path, optional): folders to scan instead of the configured ones
    (the GUI passes the archive of the current settings).
    """
    raw_dir    = cfg.RAW_DIR if raw_dir is None else raw_dir
    source_dir = cfg.SOURCE_DIR if source_dir is None else source_dir
    agg_dir    = cfg.BULK_AGG_DIR if agg_dir is None else agg_dir
    found = {KIND_MIGRATE: [], KIND_CONVERT: [], KIND_UNRESOLVED: [], "unreadable": [],
             "no_aggregates": [], "api_only": 0}
    if not raw_dir.exists():
        return found

    for f in sorted(raw_dir.glob(f"{_RAW_PREFIX}*.json")):
        date_str = f.stem[len(_RAW_PREFIX):]
        if not _valid_date(date_str):
            continue
        try:
            raw = _read_json(f)
        except (OSError, ValueError) as e:
            log.debug(f"  Track migration scan: {f.name} unreadable: {e}")
            found["unreadable"].append(date_str)
            continue
        if not isinstance(raw, dict):
            found["unreadable"].append(date_str)
            continue
        kind = classify_day(raw, (source_dir / f"{_SOURCE_PREFIX}{date_str}.json").exists())
        if kind == KIND_API:
            found["api_only"] += 1
            continue
        found[kind].append(date_str)
        if kind in (KIND_MIGRATE, KIND_CONVERT) and not (agg_dir / f"{cfg.BULK_AGG_FILE_PREFIX}{date_str}.json").exists():
            found["no_aggregates"].append(date_str)
    return found


def pending(found: dict) -> dict:
    """
    What a hook (the popup of the app, the hint of the scheduler) offers, from a scan_archive() result:
    {"ready": [...], "waiting": [...]} - the migrate days with an aggregates file, and those that wait for the
    export import. Convert days are not offered (a later step), nor mixed days without source/. The scan cannot
    know the coverage: a day the full preview blocks as not covered is still "ready" here.
    """
    no_agg = set(found["no_aggregates"])
    return {"ready": [d for d in found[KIND_MIGRATE] if d not in no_agg],
            "waiting": [d for d in found[KIND_MIGRATE] if d in no_agg]}


# ══════════════════════════════════════════════════════════════════════════════
#  Preview (full)
# ══════════════════════════════════════════════════════════════════════════════

def _blocked(date_str, kind, reason, keys=None):
    item = {"date": date_str, "kind": kind, "status": "blocked", "reason": reason}
    if keys:
        item["keys"] = sorted(keys)
    return item


def _plan_import_day(date_str: str, kind: str) -> dict:
    """The plan for one migrate/convert day: ready with the summary changes, or blocked with the reason."""
    try:
        raw = _read_json(cfg.RAW_DIR / f"{_RAW_PREFIX}{date_str}.json")
        if not isinstance(raw, dict):
            raise ValueError("raw is no dict")
    except (OSError, ValueError):
        return _blocked(date_str, kind, "raw_unreadable")

    new_api = {}
    if kind == KIND_MIGRATE:
        try:
            src = _read_json(cfg.SOURCE_DIR / f"{_SOURCE_PREFIX}{date_str}.json")
            if not isinstance(src, dict) or not src:
                raise ValueError("source is empty or no dict")
            new_api = normalizer.normalize(copy.deepcopy(src), source="api")
        except (OSError, ValueError):
            return _blocked(date_str, kind, "source_unreadable")

    prev = writer.resolve_preview(new_api, date_str)
    if prev["state"] == "unreadable":
        return _blocked(date_str, kind, "aggregates_unreadable")
    if prev["state"] != "ok":
        return _blocked(date_str, kind, "no_aggregates")

    export = prev["export"]
    imp = set(import_sections(raw))
    uncovered = []
    for key, value in raw.items():
        if key == "date" or _is_empty(value):
            continue
        if key in imp:
            if not _covers(export.get(key), value):
                uncovered.append(key)
        elif kind != KIND_MIGRATE or new_api.get(key) != value:
            uncovered.append(key)
    if uncovered:
        return _blocked(date_str, kind, "not_covered", uncovered)

    return {"date": date_str, "kind": kind, "status": "ready",
            "import_sections": sorted(imp),
            "changes": _summary_changes(_old_summary(date_str), prev["summary"])}


def _plan_refresh(date_str: str):
    """A refresh item for a day with an aggregates file whose resolved summary differs from summary/, else None."""
    raw_path = cfg.RAW_DIR / f"{_RAW_PREFIX}{date_str}.json"
    api_raw = {}
    if raw_path.exists():
        try:
            api_raw = _read_json(raw_path)
            if not isinstance(api_raw, dict):
                raise ValueError("raw is no dict")
        except (OSError, ValueError):
            return _blocked(date_str, KIND_REFRESH, "raw_unreadable")
    prev = writer.resolve_preview(api_raw, date_str)
    if prev["state"] != "ok":
        return None
    old = _old_summary(date_str)
    changes = _summary_changes(old, prev["summary"]) if old else ["(summary missing)"]
    if not changes:
        return None
    return {"date": date_str, "kind": KIND_REFRESH, "status": "ready", "changes": changes}


def plan_migration(should_stop=None) -> dict:
    """
    The full preview, read-only (configured folders; runs in the collector process).

    should_stop : optional callable; when it returns True the preview ends after the current day
                  ("stopped" is True in the result).

    Returns:
      counts   {"migrate_ready", "migrate_blocked", "convert_ready", "convert_blocked", "unresolved",
                "unreadable", "refresh", "refresh_blocked", "api_only"}
      years    {"2019": {"migrate": n, "convert": n, "refresh": n, "blocked": n}, ...}
      items    one dict per day: date, kind, status ("ready" | "blocked" | "left"), and
               reason / keys (blocked, left) or changes (ready: the dotted summary fields that differ)
      field_changes   {kind: {field: number of days}} over the ready days
      stopped  bool
    """
    found = scan_archive()
    items = []
    for d in found[KIND_UNRESOLVED]:
        items.append({"date": d, "kind": KIND_UNRESOLVED, "status": "left", "reason": "mixed_without_source"})
    for d in found["unreadable"]:
        items.append({"date": d, "kind": KIND_API, "status": "left", "reason": "raw_unreadable"})

    stopped = False
    handled = set(found[KIND_MIGRATE]) | set(found[KIND_CONVERT]) | set(found[KIND_UNRESOLVED]) | set(found["unreadable"])
    work = sorted([(d, KIND_MIGRATE) for d in found[KIND_MIGRATE]] + [(d, KIND_CONVERT) for d in found[KIND_CONVERT]])
    for d, kind in work:
        if should_stop is not None and should_stop():
            stopped = True
            break
        items.append(_plan_import_day(d, kind))

    if not stopped:
        for d in sorted(bw.list_aggregate_days()):
            if d in handled:
                continue
            if should_stop is not None and should_stop():
                stopped = True
                break
            item = _plan_refresh(d)
            if item is not None:
                items.append(item)

    items.sort(key=lambda i: (i["date"], i["kind"]))
    counts = {
        "migrate_ready":   sum(1 for i in items if i["kind"] == KIND_MIGRATE and i["status"] == "ready"),
        "migrate_blocked": sum(1 for i in items if i["kind"] == KIND_MIGRATE and i["status"] == "blocked"),
        "convert_ready":   sum(1 for i in items if i["kind"] == KIND_CONVERT and i["status"] == "ready"),
        "convert_blocked": sum(1 for i in items if i["kind"] == KIND_CONVERT and i["status"] == "blocked"),
        "unresolved":      len(found[KIND_UNRESOLVED]),
        "unreadable":      len(found["unreadable"]),
        "refresh":         sum(1 for i in items if i["kind"] == KIND_REFRESH and i["status"] == "ready"),
        "refresh_blocked": sum(1 for i in items if i["kind"] == KIND_REFRESH and i["status"] == "blocked"),
        "api_only":        found["api_only"],
    }
    years = {}
    for i in items:
        if i["kind"] in (KIND_MIGRATE, KIND_CONVERT, KIND_REFRESH):
            y = years.setdefault(i["date"][:4], {"migrate": 0, "convert": 0, "refresh": 0, "blocked": 0})
            y["blocked" if i["status"] == "blocked" else i["kind"]] += 1
    field_changes = {k: Counter() for k in (KIND_MIGRATE, KIND_CONVERT, KIND_REFRESH)}
    for i in items:
        if i["status"] == "ready" and i["kind"] in field_changes:
            field_changes[i["kind"]].update(i["changes"])
    return {"counts": counts, "years": dict(sorted(years.items())), "items": items,
            "field_changes": {k: dict(v.most_common()) for k, v in field_changes.items()},
            "stopped": stopped}


_REASON_TEXT = {
    "no_aggregates":         "no usable aggregates file - import the Garmin export first",
    "aggregates_unreadable": "aggregates file cannot be read",
    "source_unreadable":     "source/ file missing or unusable",
    "raw_unreadable":        "raw file cannot be read",
    "not_covered":           "raw/ holds data that the bulk store / source/ does not reproduce",
    "mixed_without_source":  "import and API sections mixed, no source/ file",
}


def format_plan(plan: dict, max_dates: int = 5) -> list:
    """Log lines for the preview: counts, years, blocked days by reason, summary changes by field."""
    c = plan["counts"]
    lines = [
        "Track migration preview (nothing is written):",
        f"  days to rebuild from source/ (migrate): {c['migrate_ready']} ready, {c['migrate_blocked']} blocked",
        f"  pure import days to turn into export-only days (convert): {c['convert_ready']} ready, {c['convert_blocked']} blocked",
        f"  summaries to refresh (summary/ only, raw/ stays): {c['refresh']}"
        + (f", {c['refresh_blocked']} blocked" if c["refresh_blocked"] else ""),
        f"  left as they are: {c['unresolved']} mixed without source/, {c['unreadable']} unreadable, "
        f"{c['api_only']} API days not touched",
    ]
    for year, y in plan["years"].items():
        lines.append(f"  {year}: migrate {y['migrate']}, convert {y['convert']}, refresh {y['refresh']}, blocked {y['blocked']}")
    reasons = {}
    for i in plan["items"]:
        if "reason" in i:
            reasons.setdefault(i["reason"], []).append(i)
    for reason, group in sorted(reasons.items()):
        sample = ", ".join(i["date"] for i in group[:max_dates]) + (" ..." if len(group) > max_dates else "")
        lines.append(f"  {len(group)} day(s): {_REASON_TEXT.get(reason, reason)} ({sample})")
    for kind, fields in plan["field_changes"].items():
        if fields:
            lines.append(f"  summary fields that change ({kind}): "
                         + ", ".join(f"{f} {n}" for f, n in list(fields.items())[:10]))
    if plan["field_changes"][KIND_MIGRATE].get("activities") or plan["field_changes"][KIND_CONVERT].get("activities"):
        lines.append("  note: the activity lists of the old import (duration and distance in the wrong units) "
                     "become empty; the export's activities are not used for the summary yet")
    if plan["stopped"]:
        lines.append("  (stopped - the preview is incomplete)")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
#  Migration (the only part that writes)
# ══════════════════════════════════════════════════════════════════════════════

def _migrate_day(date_str: str, by_date: dict, result: dict) -> str:
    """
    Makes raw/ of one migrate day again from source/ (write_day also makes the resolved summary) and
    reads the file back. The day is checked again right before it is written. Returns "migrated" or
    "blocked"; an error raises.
    """
    item = _plan_import_day(date_str, KIND_MIGRATE)
    if item["status"] != "ready":
        result["blocked"].append((date_str, item["reason"]))
        return "blocked"
    src = _read_json(cfg.SOURCE_DIR / f"{_SOURCE_PREFIX}{date_str}.json")
    new_api = normalizer.normalize(copy.deepcopy(src), source="api")
    expected = json.loads(json.dumps(new_api, ensure_ascii=False))
    entry = by_date.get(date_str)
    if entry is not None and (quality.assess_quality(new_api) != entry.get("quality")
                              or quality.assess_quality_fields(new_api) != entry.get("fields")):
        result["label_differs"].append(date_str)
    if not writer.write_day(new_api, normalizer.summarize(new_api), date_str):
        raise RuntimeError("write_day reported a failure (see the log)")
    if writer.read_raw(date_str) != expected:
        raise RuntimeError("the raw file written differs from the data of source/")
    return "migrated"


def run_migration(dry_run: bool = False, should_stop=None, quality_data=None) -> dict:
    """
    Migrates the archive (see the module docstring). Always starts with a fresh preview, never acts on an
    earlier finding.

    dry_run      : nothing is written (the result lists what would be done; "snapshot" stays None).
    should_stop  : optional callable; True ends the run after the current day (days written are recorded).
    quality_data : the quality log dict of the caller. A caller that keeps the log in memory for the rest
                   of its run (garmin_collector.main) must pass it: the marks are made on that object and
                   it is saved; a copy loaded here would be overwritten by the caller's next save.
                   Without it the log is loaded here. The caller must not hold QUALITY_LOCK.

    Returns a dict:
      ok              bool  — no day failed, not stopped, the safety copy and the log are fine
      migrated        int   — days made again from source/ (dry run: the days that would be)
      refreshed       int   — summaries made again (dry run: the days that would be)
      failed          list  — (date, reason) of days that raised an error
      blocked         list  — (date, reason) of days not covered (not touched, reported)
      unresolved      int   — mixed days without source/ (not touched)
      convert_pending int   — pure import days (a later step)
      label_differs   list  — migrated days whose recalculated label or fields differ from the entry (unchanged)
      years           dict  — {"2019": {"migrated": n, "refreshed": n, "failed": n}, ...}
      snapshot        str | None — name of the safety copy made for this run
      log_saved       bool | None
      stopped         bool
      reason          str   — set when the run did not start ("snapshot_failed", "preview_stopped")
    """
    result = {"ok": False, "migrated": 0, "refreshed": 0, "failed": [], "blocked": [], "unresolved": 0,
              "convert_pending": 0, "label_differs": [], "years": {}, "snapshot": None, "log_saved": None,
              "stopped": False}
    plan = plan_migration(should_stop)
    if plan["stopped"]:
        return {**result, "stopped": True, "reason": "preview_stopped"}

    migrate_days = [i["date"] for i in plan["items"] if i["kind"] == KIND_MIGRATE and i["status"] == "ready"]
    refresh_days = [i["date"] for i in plan["items"] if i["kind"] == KIND_REFRESH and i["status"] == "ready"]
    result["blocked"] = [(i["date"], i["reason"]) for i in plan["items"]
                         if i["kind"] in (KIND_MIGRATE, KIND_CONVERT, KIND_REFRESH) and i["status"] == "blocked"]
    result["unresolved"] = plan["counts"]["unresolved"]
    result["convert_pending"] = plan["counts"]["convert_ready"] + plan["counts"]["convert_blocked"]

    if dry_run:
        result["migrated"], result["refreshed"] = len(migrate_days), len(refresh_days)
        return {**result, "ok": True}
    if not migrate_days and not refresh_days:
        log.info("  Track migration: nothing to migrate or refresh.")
        return {**result, "ok": True}

    copy_made = snapshot.create_snapshot(should_stop)
    if not copy_made["ok"]:
        log.error(f"  Track migration: no safety copy ({copy_made['reason']}) - nothing was written.")
        return {**result, "stopped": copy_made["reason"] == "stopped", "reason": "snapshot_failed",
                "snapshot_reason": copy_made["reason"]}
    result["snapshot"] = copy_made["path"].name if copy_made["path"] else None
    log.info(f"  Track migration: safety copy {result['snapshot']}; {len(migrate_days)} day(s) to rebuild from source/, "
             f"{len(refresh_days)} summary(ies) to refresh")

    work = sorted([(d, KIND_MIGRATE) for d in migrate_days] + [(d, KIND_REFRESH) for d in refresh_days])
    touched = []
    with quality.QUALITY_LOCK:
        qdata = quality_data if quality_data is not None else quality._load_quality_log()
        by_date = {e.get("date"): e for e in qdata.get("days", []) if isinstance(e, dict)}
        try:
            for i, (d, kind) in enumerate(work, 1):
                if should_stop is not None and should_stop():
                    result["stopped"] = True
                    log.info(f"  Track migration: stopped after {i - 1} of {len(work)} day(s).")
                    break
                year = result["years"].setdefault(d[:4], {"migrated": 0, "refreshed": 0, "failed": 0})
                try:
                    if kind == KIND_MIGRATE:
                        if _migrate_day(d, by_date, result) == "migrated":
                            result["migrated"] += 1
                            year["migrated"] += 1
                            touched.append(d)
                            log.info(f"  [{i}/{len(work)}] {d} - rebuilt from source/")
                        else:
                            log.warning(f"  [{i}/{len(work)}] {d} - not covered any more, left as it is")
                    else:
                        if not writer.rebuild_summary(d):
                            raise RuntimeError("rebuild_summary reported a failure (see the log)")
                        result["refreshed"] += 1
                        year["refreshed"] += 1
                        touched.append(d)
                        log.info(f"  [{i}/{len(work)}] {d} - summary refreshed")
                except Exception as e:
                    result["failed"].append((d, f"{type(e).__name__}: {e}"))
                    year["failed"] += 1
                    log.error(f"  [{i}/{len(work)}] {d} - error: {type(e).__name__}: {e}")
        finally:
            if touched:
                quality.touch_last_checked(qdata, touched)
                result["log_saved"] = quality._save_quality_log(qdata) is not False
                if not result["log_saved"]:
                    result["failed"].append(("quality_log", "the quality log could not be saved"))

    result["ok"] = not result["failed"] and not result["stopped"]
    log.info(f"  Track migration complete: {result['migrated']} rebuilt, {result['refreshed']} refreshed, "
             f"{len(result['failed'])} failed, {len(result['blocked'])} blocked.")
    return result


def format_result(result: dict) -> list:
    """Log lines for the result of run_migration()."""
    if result.get("reason") == "snapshot_failed":
        return [f"Track migration NOT started - the safety copy failed: {result.get('snapshot_reason')}. Nothing was written."]
    if result.get("reason") == "preview_stopped":
        return ["Track migration stopped before it started. Nothing was written."]
    lines = [f"Track migration: {result['migrated']} day(s) rebuilt from source/, {result['refreshed']} summary(ies) refreshed, "
             f"{len(result['failed'])} failed."]
    if result["snapshot"]:
        lines.append(f"  Safety copy: {result['snapshot']} (backup/migration; the oldest copy is the original state)")
    for year, y in sorted(result["years"].items()):
        lines.append(f"  {year}: {y['migrated']} rebuilt, {y['refreshed']} refreshed, {y['failed']} failed")
    if result["blocked"]:
        reasons = Counter(r for _, r in result["blocked"])
        lines.append("  Not touched, not covered: " + ", ".join(f"{n} x {_REASON_TEXT.get(r, r)}" for r, n in reasons.items()))
    if result["unresolved"]:
        lines.append(f"  Not touched: {result['unresolved']} mixed day(s) without source/")
    if result["convert_pending"]:
        lines.append(f"  Not touched: {result['convert_pending']} pure import day(s) (a later step)")
    if result["label_differs"]:
        lines.append(f"  {len(result['label_differs'])} migrated day(s) would get another label or fields; the entries are unchanged")
    for d, why in result["failed"][:5]:
        lines.append(f"  FAILED {d}: {why}")
    if result["stopped"]:
        lines.append("  Stopped - run it again to go on.")
    return lines
