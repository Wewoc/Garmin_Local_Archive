#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_collector.py

Conductor — thin orchestrator for the Garmin Local Archive pipeline.

Coordinates the specialised modules. Contains no API logic, no quality log
logic, no date strategy logic, no file write logic.

Pipeline:
  garmin_config      — all environment variables and paths
  garmin_api         — login, fetch_raw, get_devices
  garmin_validator   — structural validation against garmin_dataformat.json
  garmin_normalizer  — normalize raw dict, summarize
  garmin_quality     — load/save/assess/upsert quality_log.json
  garmin_sync        — resolve date range, get local dates, date_range generator
  garmin_writer      — sole owner of raw/ and summary/

Configuration via environment variables — see garmin_config.py for full list.
"""

import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import garmin_config as cfg
import garmin_api as api
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_redact as redact
import garmin_sync as sync
import garmin_validator as validator
import garmin_writer as writer
from garmin_quality import QUALITY_RANK

# ══════════════════════════════════════════════════════════════════════════════
#  Logging setup
# ══════════════════════════════════════════════════════════════════════════════

_log_level = getattr(logging, cfg.LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Stop-event (registered via set_stop_event — distributed to garmin_api)
# ══════════════════════════════════════════════════════════════════════════════

_stop_event = None   # threading.Event | None


def set_stop_event(ev) -> None:
    """Registers the stop event for collector + garmin_api. Pass None to clear.
    The collector is the stop orchestrator — it owns distribution to the API
    module so callers (GUI, scheduler) only ever talk to the collector."""
    global _stop_event
    _stop_event = ev
    api.set_stop_event(ev)


def _is_stopped() -> bool:
    """Returns True if a stop event is registered and set."""
    return _stop_event is not None and _stop_event.is_set()


# ══════════════════════════════════════════════════════════════════════════════
#  Decision + processing
# ══════════════════════════════════════════════════════════════════════════════

def _should_write(label: str) -> bool:
    """Returns True if the quality label is acceptable for writing to disk."""
    return label in ("high", "standard")


def _fetch_and_assess(client, date_str: str) -> tuple:
    """
    Fetches and assesses a single day — no file writes.

    Returns
    -------
    tuple (label, normalized, summary, fields, val_result)
      label      — "high" | "standard" | "failed"
      normalized — normalized dict, or None on critical failure
      summary    — summary dict, or None on critical failure
      fields     — per-field quality dict
      val_result — validator result dict
    """
    raw_data, failed_endpoints = api.fetch_raw(client, date_str)
    if failed_endpoints:
        log.warning(f"    ⚠ {len(failed_endpoints)} endpoint(s) failed: {', '.join(failed_endpoints)}")

    # ── Source archive (non-fatal) ────────────────────────────────────────────
    # write_source() before validator — secures raw data even if validator crashes.
    try:
        import garmin_source_writer as _sw
        if not _sw.write_source(raw_data, date_str):
            log.error(f"    source_writer.write_source failed for {date_str}")
    except Exception as _e:
        log.error(f"    source_writer.write_source failed for {date_str}: {_e}")

    val_result = validator.validate(raw_data)
    if val_result["status"] == "critical":
        log.warning(f"    ⚠ Validator critical — skipping {date_str}")
        # update_log even on critical — validator_status recorded for audit trail
        try:
            import garmin_source_writer as _sw
            import json as _json
            _sw.update_log(
                date_str, val_result,
                endpoints_fetched=list(raw_data.keys()) if isinstance(raw_data, dict) else [],
                endpoints_failed=failed_endpoints,
                size_bytes=len(_json.dumps(raw_data).encode()) if isinstance(raw_data, dict) else 0,
                raw_data=raw_data if isinstance(raw_data, dict) else None,
            )
        except Exception as _e:
            log.warning(f"    source_writer.update_log failed for {date_str}: {_e}")
        return "failed", None, None, {}, val_result

    # ── Source log update (non-fatal) ─────────────────────────────────────────
    # update_log() after validator — validator_status and issues are now known.
    try:
        import garmin_source_writer as _sw
        import json as _json
        _sw.update_log(
            date_str, val_result,
            endpoints_fetched=list(raw_data.keys()),
            endpoints_failed=failed_endpoints,
            size_bytes=len(_json.dumps(raw_data).encode()),
            raw_data=raw_data,
        )
    except Exception as _e:
        log.warning(f"    source_writer.update_log failed for {date_str}: {_e}")

    normalized = normalizer.normalize(raw_data, source="api")
    summary    = normalizer.summarize(normalized)
    label      = quality.assess_quality(normalized)
    fields     = quality.assess_quality_fields(normalized)

    # ── Range-warning downgrade ───────────────────────────────────────────────
    # If validator found more than 3 out_of_range warnings, cap label at "standard".
    # assess_quality() stays pure — downgrade decision lives here.
    out_of_range_count = sum(
        1 for i in val_result.get("issues", [])
        if i.get("type") == "out_of_range"
    )
    if out_of_range_count > 3 and label == "high":
        log.warning(
            f"    ⚠ {out_of_range_count} out_of_range warnings — "
            f"quality downgraded: {label} → standard"
        )
        label = "standard"

    return label, normalized, summary, fields, val_result


# ══════════════════════════════════════════════════════════════════════════════
#  Downgrade guard
# ══════════════════════════════════════════════════════════════════════════════

def _check_downgrade(new_label: str, existing_entry: dict | None) -> tuple:
    """
    Compares a freshly fetched quality label against the stored entry.

    Returns
    -------
    tuple (is_downgrade, existing_label, existing_source)
      is_downgrade    — True if new_label is worse than stored label
      existing_label  — stored quality label, or "failed" if no entry
      existing_source — stored source, or "api" if no entry
    """
    if existing_entry is None:
        return False, "failed", "api"

    existing_label  = existing_entry.get("quality", "failed")
    existing_source = existing_entry.get("source", "api")
    is_downgrade    = QUALITY_RANK.get(new_label, 0) < QUALITY_RANK.get(existing_label, 0)
    return is_downgrade, existing_label, existing_source

def _write_assessed(normalized, summary, date_str: str, label: str) -> bool:
    """
    Writes a pre-assessed day to disk. Returns True if written successfully.
    """
    if _should_write(label):
        return writer.write_day(normalized, summary, date_str)
    return False


def run_import(path, progress_callback=None, stop_event=None) -> dict:
    """
    Imports a Garmin export ZIP or folder into the local archive.

    Iterates load_bulk() day by day — each day is normalised, assessed,
    and written before the next day is loaded (Option 2: read → build → write → repeat).

    Parameters
    ----------
    path              : str | Path — path to Garmin export ZIP or unpacked folder
    progress_callback : callable(current, total, date_str) | None
                        Called after each day. total is None (unknown upfront).
    stop_event        : threading.Event | None — registered so the bulk loop
                        can abort via _is_stopped(). Bulk uses no API, so the
                        stop is checked only in this loop.

    Returns
    -------
    dict — {"ok": int, "skipped": int, "failed": int}
    """
    if stop_event is not None:
        set_stop_event(stop_event)

    import garmin_import as importer

    ok, skipped, failed = 0, 0, 0

    with quality.QUALITY_LOCK:
        quality_data = quality._load_quality_log()

        for i, raw_data in enumerate(importer.load_bulk(path), 1):
            date_str = raw_data.get("date")
            if not date_str:
                log.warning(f"  import [{i}]: missing date — skipped")
                failed += 1
                continue

            # Skip days already present with high/medium quality from API
            existing = next(
                (e for e in quality_data.get("days", []) if e.get("date") == date_str),
                None
            )
            if existing and existing.get("quality") in ("high", "standard") and existing.get("source") == "api":
                log.debug(f"  import [{i}]: {date_str} — already high/standard from API, skipped")
                skipped += 1
                if progress_callback:
                    progress_callback(i, None, date_str)
                continue

            try:
                val_result = validator.validate(raw_data)
                if val_result["status"] == "critical":
                    log.warning(f"  import [{i}]: {date_str} — validator critical, skipped")
                    failed += 1
                    if progress_callback:
                        progress_callback(i, None, date_str)
                    continue

                normalized = normalizer.normalize(raw_data, source="bulk")
                summary    = normalizer.summarize(normalized)
                label      = quality.assess_quality(normalized)
                fields     = quality.assess_quality_fields(normalized)

                if _should_write(label):
                    written = writer.write_day(normalized, summary, date_str)
                else:
                    written = False

                reason = (f"Quality: {label} — bulk import" if label in ("high", "medium")
                          else f"Quality: {label} — insufficient data in bulk export")

                try:
                    day = date.fromisoformat(date_str)
                except ValueError:
                    log.warning(f"  import [{i}]: invalid date '{date_str}' — skipped")
                    failed += 1
                    continue

                quality._upsert_quality(quality_data, day, label, reason,
                                        written=written, source="bulk", fields=fields,
                                        validator_result=val_result)
                ok += 1
                log.info(f"  import [{i}]: {date_str} — {label}")

            except Exception as e:
                log.error(f"  import [{i}]: {date_str} — error: {e}")
                failed += 1

            if progress_callback:
                progress_callback(i, None, date_str)

        # ── first_day update after bulk import ────────────────────────────────
        # GDPR exports may predate the oldest registered device — first_day from
        # the device API can therefore be too late. If the earliest imported day
        # is earlier than the stored first_day, overwrite it.
        # Guard: only when at least one day was written successfully.
        if ok > 0:
            imported_dates = []
            for e in quality_data.get("days", []):
                if e.get("source") == "bulk":
                    try:
                        imported_dates.append(date.fromisoformat(e["date"]))
                    except (ValueError, KeyError):
                        pass
            if imported_dates:
                earliest = min(imported_dates)
                old_first = quality_data.get("first_day")
                if not old_first or earliest < date.fromisoformat(old_first):
                    new_first = earliest.isoformat()
                    quality_data["first_day"] = new_first
                    log.info(
                        f"  Archive: first_day updated from {old_first} to {new_first} "
                        f"(GDPR export predates device history)"
                    )

        quality._save_quality_log(quality_data)

    log.info(f"  Import done: {ok} written, {skipped} skipped, {failed} failed")
    return {"ok": ok, "skipped": skipped, "failed": failed}


# ══════════════════════════════════════════════════════════════════════════════
#  Session logging
# ══════════════════════════════════════════════════════════════════════════════

def _start_session_log() -> tuple:
    """
    Creates a new session log file in log/recent/ at DEBUG level.
    Returns (file_handler, log_path) so main() can close and evaluate it.
    """
    cfg.LOG_RECENT_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOG_FAIL_DIR.mkdir(parents=True, exist_ok=True)

    ts       = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = cfg.LOG_RECENT_DIR / f"{cfg.SESSION_LOG_PREFIX}_{ts}.log"

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    fh.addFilter(redact.RedactFilter())
    logging.getLogger().addHandler(fh)
    return fh, log_path


def _close_session_log(fh: logging.FileHandler, log_path: Path,
                        had_errors: bool, had_incomplete: bool) -> None:
    """
    Closes the session log file handler.
    Copies to log/fail/ if the session had errors or incomplete days.
    Enforces LOG_RECENT_MAX rolling limit on log/recent/.
    """
    logging.getLogger().removeHandler(fh)
    fh.close()

    if had_errors or had_incomplete:
        import shutil
        try:
            shutil.copy2(log_path, cfg.LOG_FAIL_DIR / log_path.name)
        except Exception as e:
            log.warning(f"  Could not copy to log/fail/: {e}")

    try:
        logs = sorted(cfg.LOG_RECENT_DIR.glob("garmin_*.log"), key=lambda f: f.stat().st_mtime)
        for old in logs[:-cfg.LOG_RECENT_MAX]:
            old.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"  Could not rotate session logs: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Self-healing
# ══════════════════════════════════════════════════════════════════════════════

def _run_self_healing(quality_data: dict) -> None:
    """
    Revalidates days with validator issues when the schema version has changed.

    Runs at every process start — before login, no API call required.
    Only triggers when both conditions are true:
      1. A day has validator_result != "ok"
      2. The stored validator_schema_version differs from the current schema

    Quality is only re-evaluated if the validator result actually changes.
    """
    current_version = validator.current_version()
    if current_version == "unknown":
        log.debug("  Self-healing: schema not loaded — skipping")
        return

    candidates = [
        e for e in quality_data.get("days", [])
        if e.get("validator_result") not in (None, "ok")
        and e.get("validator_schema_version") != current_version
    ]

    if not candidates:
        log.debug("  Self-healing: no candidates — schema versions match")
        return

    log.info(f"  Self-healing: {len(candidates)} day(s) to revalidate "
             f"(schema {current_version})")

    changed = 0
    with quality.QUALITY_LOCK:
        for entry in candidates:
            date_str = entry.get("date")
            if not date_str:
                continue

            raw = writer.read_raw(date_str)
            if not raw:
                log.warning(f"  Self-healing: no raw file for {date_str} — skipped")
                continue

            new_result = validator.validate(raw)

            # Only update if result actually changed
            if new_result["status"] == entry.get("validator_result"):
                entry["validator_schema_version"] = current_version
                continue

            log.info(f"  Self-healing: {date_str} — "
                     f"{entry.get('validator_result')} → {new_result['status']}")

            entry["validator_result"]         = new_result["status"]
            entry["validator_issues"]         = new_result["issues"]
            entry["validator_schema_version"] = current_version

            # Re-evaluate quality only if validator result improved
            if new_result["status"] == "ok":
                raw_full = writer.read_raw(date_str)
                if raw_full:
                    normalized = normalizer.normalize(raw_full, source="api")
                    new_label  = quality.assess_quality(normalized)
                    new_fields = quality.assess_quality_fields(normalized)
                    entry["quality"] = new_label
                    entry["fields"]  = new_fields
                    entry["recheck"] = new_label == "failed"

            changed += 1

        if changed:
            quality._save_quality_log(quality_data)
            log.info(f"  Self-healing: {changed} day(s) updated")


# ══════════════════════════════════════════════════════════════════════════════
#  Source backfill
# ══════════════════════════════════════════════════════════════════════════════

def _run_source_backfill(client, quality_data: dict) -> None:
    """
    Re-fetches API days that have no source/ file — closes the gap between
    days fetched before v1.6.0.2 (which introduced source/) and the current
    archive state.

    Runs in the Background Timer source_backfill mode only — triggered by
    GARMIN_SOURCE_BACKFILL=1 + GARMIN_SYNC_DATES (the timer picks candidates
    via timer_run_source_backfill() and passes them as GARMIN_SYNC_DATES).

    Each day is re-fetched via _fetch_and_assess() and written via the normal
    pipeline (_write_assessed + record_attempt). No new fields introduced.
    Non-fatal: any per-day failure is logged as a warning; the loop continues.
    Becomes a no-op once source/ is complete for the 180-day window.
    """
    if not cfg.SYNC_DATES:
        log.info("  Source backfill: no GARMIN_SYNC_DATES — nothing to do.")
        return

    candidates = [d.isoformat() for d in sorted(cfg.SYNC_DATES)]
    log.info(f"  Source backfill: {len(candidates)} day(s) to re-fetch")

    ok     = 0
    failed = 0
    total  = len(candidates)

    with quality.QUALITY_LOCK:
        for i, date_str in enumerate(candidates, 1):
            if _is_stopped():
                log.info(f"  Source backfill: stopped after {ok} days.")
                break
            existing = next(
                (e for e in quality_data.get("days", [])
                 if e.get("date") == date_str),
                None,
            )
            try:
                label, normalized, summary, fields, val_result = \
                    _fetch_and_assess(client, date_str)

                is_downgrade, _, _ = _check_downgrade(label, existing)

                if not is_downgrade:
                    _write_assessed(normalized, summary, date_str, label)

                quality.record_attempt(
                    quality_data, date.fromisoformat(date_str), label,
                    f"Source backfill: {label}",
                    written=not is_downgrade and _should_write(label),
                    source="api",
                    fields=fields,
                    validator_result=val_result,
                )
                log.info(f"  Source backfill [{i}/{total}]: {date_str} — {label}")
                ok += 1

            except Exception as e:
                log.warning(f"  Source backfill [{i}/{total}]: {date_str} — error: {e}")
                failed += 1

    log.info(f"  Source backfill complete: {ok} fetched, {failed} failed.")


def _run_steps_backfill(client, quality_data: dict) -> None:
    """
    Runs in the Background Timer steps_backfill mode only — triggered by
    GARMIN_STEPS_BACKFILL=1 + GARMIN_SYNC_DATES (the timer picks candidates
    via timer_run_steps_backfill() and passes them as GARMIN_SYNC_DATES).

    Unlike _run_source_backfill(), this does NOT re-fetch the full day via
    _fetch_and_assess() — only the single 'steps' endpoint is called, via
    api.api_call() directly. Reduces the backlog cost from 14 API calls per
    day to 1. The result is merged additively into the existing raw/ file
    (garmin_merge.merge_field) and patched into source/ if present
    (garmin_source_writer.patch_source_field) — never a full day re-fetch,
    never a downgrade risk (additive by construction, nothing is replaced).

    Per day: read_raw() → api_call("get_steps_data") → merge_field() →
    normalize() + summarize() → write_day() (summary/ rewritten too —
    accepted redundancy, steps does not feed summarize() so the rewrite is
    byte-identical in substance) → record_attempt() with backfilled_fields
    → patch_source_field().

    Non-fatal: any per-day failure is logged as a warning; the loop continues.
    Becomes a no-op once no day in the window is missing 'steps' anymore —
    the candidate filter in timer_run_steps_backfill() is self-terminating.
    """
    if not cfg.SYNC_DATES:
        log.info("  Steps backfill: no GARMIN_SYNC_DATES — nothing to do.")
        return

    import garmin_merge as merge
    import garmin_source_writer as source_writer

    candidates = [d.isoformat() for d in sorted(cfg.SYNC_DATES)]
    log.info(f"  Steps backfill: {len(candidates)} day(s) to enrich")

    ok                  = 0
    failed              = 0
    source_patch_failed = 0
    total               = len(candidates)

    with quality.QUALITY_LOCK:
        for i, date_str in enumerate(candidates, 1):
            if _is_stopped():
                log.info(f"  Steps backfill: stopped after {ok} days.")
                break
            try:
                existing_raw = writer.read_raw(date_str)
                if not existing_raw:
                    log.warning(f"  Steps backfill [{i}/{total}]: {date_str} — no raw/ file, skipped")
                    failed += 1
                    continue

                steps_data, success = api.api_call(client, "get_steps_data", date_str, label="steps")
                if not success or steps_data is None:
                    log.warning(f"  Steps backfill [{i}/{total}]: {date_str} — get_steps_data failed")
                    failed += 1
                    continue

                merged_raw = merge.merge_field(existing_raw, "steps", steps_data)
                normalized = normalizer.normalize(merged_raw, source="api")
                summary    = normalizer.summarize(normalized)

                if not writer.write_day(normalized, summary, date_str):
                    log.warning(f"  Steps backfill [{i}/{total}]: {date_str} — write_day failed")
                    failed += 1
                    continue

                fields        = quality.assess_quality_fields(normalized)
                backfilled_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                quality.record_attempt(
                    quality_data, date.fromisoformat(date_str),
                    quality.assess_quality(normalized),
                    "Steps backfill: field added",
                    written=True, source="api",
                    fields=fields,
                    backfilled_fields={"steps": backfilled_at},
                )

                if not source_writer.patch_source_field(date_str, "steps", steps_data):
                    log.warning(f"  Steps backfill [{i}/{total}]: {date_str} — "
                                f"source/ patch failed (raw/summary already written, no data lost)")
                    source_patch_failed += 1

                log.info(f"  Steps backfill [{i}/{total}]: {date_str} — steps added")
                ok += 1

            except Exception as e:
                log.warning(f"  Steps backfill [{i}/{total}]: {date_str} — error: {e}")
                failed += 1

    log.info(f"  Steps backfill complete: {ok} enriched, {failed} failed, "
             f"{source_patch_failed} source/ patch(es) failed.")


# ══════════════════════════════════════════════════════════════════════════════
#  Schema migration — re-summarize outdated summaries
# ══════════════════════════════════════════════════════════════════════════════

def _run_schema_migration(quality_data: dict) -> None:
    """
    Rewrites summary files whose schema_version is below CURRENT_SCHEMA_VERSION.

    Runs after the user confirms the backup popup in garmin_app.py.
    Iterates over quality_data["days"] only — days not in the quality log
    are not touched.

    Raw files are read-only. Only summary/ files are overwritten.
    No API call, no login required.

    Logs every day individually so the user can follow progress in the GUI.
    """
    current = normalizer.CURRENT_SCHEMA_VERSION

    candidates = []
    for e in quality_data.get("days", []):
        date_str = e.get("date")
        if not date_str:
            continue
        summary = writer.read_summary(date_str)
        if not summary:
            continue
        if summary.get("schema_version", 0) < current:
            candidates.append(date_str)

    if not candidates:
        log.info("  Schema migration: all summaries up to date — nothing to do.")
        return

    log.info(
        f"  Schema migration: {len(candidates)} summary file(s) will be rewritten "
        f"(schema version → {current})"
    )
    log.info("  Raw files are not modified.")

    ok = 0
    failed = 0
    total = len(candidates)

    with quality.QUALITY_LOCK:
        for i, date_str in enumerate(candidates, 1):
            raw = writer.read_raw(date_str)
            if not raw:
                log.warning(f"  [{i}/{total}] {date_str} — no raw file, skipped")
                failed += 1
                continue
            try:
                normalized = normalizer.normalize(raw, source="api")
                summary    = normalizer.summarize(normalized)
                writer.write_day(normalized, summary, date_str)
                log.info(f"  [{i}/{total}] {date_str} — ok")
                ok += 1
            except Exception as e:
                log.error(f"  [{i}/{total}] {date_str} — error: {e}")
                failed += 1

    log.info(f"  Schema migration complete: {ok} rewritten, {failed} skipped/failed.")

def main(stop_event=None):
    # Register the stop event with collector + garmin_api before anything runs.
    # subprocess mode (T1/T2) passes None — stop handled via process terminate.
    if stop_event is not None:
        set_stop_event(stop_event)

    # ── 0. Import mode — delegated entry points ───────────────────────────────
    import_path = os.environ.get("GARMIN_IMPORT_PATH")
    if import_path:
        result = run_import(import_path, stop_event=stop_event)
        sys.exit(0 if result["failed"] == 0 else 1)

    # (v2.0) strava_path = os.environ.get("STRAVA_IMPORT_PATH")
    # (v2.0) if strava_path:
    # (v2.0)     result = run_strava_import(strava_path)
    # (v2.0)     sys.exit(0 if result["failed"] == 0 else 1)

    # ── 1. Dirs ───────────────────────────────────────────────────────────────
    cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── 2. Session log ────────────────────────────────────────────────────────
    _session_fh, _session_path = _start_session_log()
    _session_had_errors     = False
    _session_had_incomplete = False

    # ── 3. Load quality log + backfill ────────────────────────────────────────
    with quality.QUALITY_LOCK:
        quality_data = quality._load_quality_log()

        if not quality_data.get("first_day"):
            log.info("  Running one-time quality log backfill ...")
            quality._backfill_quality_log(quality_data)
            quality._save_quality_log(quality_data)

        known_dates = {
            date.fromisoformat(e["date"])
            for e in quality_data.get("days", [])
            if "date" in e
        }

        new_low = quality.get_low_quality_dates(cfg.RAW_DIR, known_dates=known_dates)
        for day, q in new_low.items():
            quality.record_attempt(quality_data, day, q,
                                   f"Quality: {q} — insufficient data from Garmin API",
                                   written=True)

        quality._save_quality_log(quality_data)
        recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
        log.info(f"  Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")

        # ── bulk upgrade candidates ───────────────────────────────────────────
        # All bulk-sourced days within the high-resolution window (~180 days)
        # are flagged for API re-fetch — quality is irrelevant, source is the trigger.
        # After 180 days Garmin degrades intraday data permanently; the local raw
        # copy is then the only high-resolution source.
        cutoff = date.today() - timedelta(days=cfg.INTRADAY_RETRY_WINDOW_DAYS)
        bulk_upgraded = 0
        for e in quality_data.get("days", []):
            if e.get("source") == "bulk" and not e.get("recheck", False):
                try:
                    entry_date = date.fromisoformat(e["date"])
                except (ValueError, KeyError):
                    continue
                if entry_date >= cutoff:
                    e["recheck"] = True
                    bulk_upgraded += 1
        if bulk_upgraded:
            quality._save_quality_log(quality_data)
            log.info(f"  Bulk recheck: {bulk_upgraded} day(s) flagged for API re-fetch (≤{cfg.INTRADAY_RETRY_WINDOW_DAYS} days, source=bulk)")

    # ── 3b. Self-healing loop — schema version check ───────────────────────────
    _run_self_healing(quality_data)

    # ── 3c. Schema migration — rewrite outdated summaries if triggered ─────────
    if os.environ.get("GARMIN_SCHEMA_MIGRATE") == "1":
        _run_schema_migration(quality_data)

    # ── 4. Login ──────────────────────────────────────────────────────────────
    try:
        client = api.login()
    except api.GarminLoginError as e:
        log.error(f"Login failed — aborting session: {e}")
        _close_session_log(_session_fh, _session_path, True, False)
        sys.exit(1)

    if client is None:
        log.info("Login cancelled by user — aborting session.")
        _close_session_log(_session_fh, _session_path, False, False)
        return

    # ── 5. Update device history ──────────────────────────────────────────────
    try:
        devices = api.get_devices(client)
        if devices:
            quality_data["devices"] = devices
            log.info(f"  Device history updated ({len(devices)} devices)")
    except Exception as e:
        log.warning(f"  Could not update device history: {e}")

    # ── 5b. device_id backfill ────────────────────────────────────────────────
    # Einmalig: Einträge ohne device_id aus den raw-Files befüllen.
    # Erkennung: mindestens ein Eintrag hat device_id=None.
    # Nach dem Backfill werden nur neue Tage iterativ ergänzt (im Fetch-Loop).
    _entries_without_device_id = [
        e for e in quality_data.get("days", [])
        if e.get("device_id") is None and e.get("source") in ("api", "bulk", "legacy")
    ]
    if _entries_without_device_id:
        log.info(f"  device_id backfill: {len(_entries_without_device_id)} entries to process ...")
        _backfill_count = 0
        for _entry in _entries_without_device_id:
            _date_str = _entry.get("date")
            if not _date_str:
                continue
            try:
                _raw = writer.read_raw(_date_str)
                if not _raw:
                    continue
                _ts   = _raw.get("training_status") or {}
                _mrts = _ts.get("mostRecentTrainingStatus") if isinstance(_ts, dict) else None
                if not isinstance(_mrts, dict):
                    continue
                # Primary: recordedDevices — contains deviceId + deviceName
                _recorded = _mrts.get("recordedDevices") or []
                if _recorded and isinstance(_recorded, list):
                    _dev      = _recorded[0]
                    _dev_id   = str(_dev.get("deviceId", "")) or None
                    _dev_name = _dev.get("deviceName", "")
                else:
                    # Fallback: latestTrainingStatusData keys
                    _lts    = _mrts.get("latestTrainingStatusData")
                    _dev_id = str(next(iter(_lts))) if isinstance(_lts, dict) and _lts else None
                    _dev_name = ""
                if _dev_id:
                    _entry["device_id"]   = _dev_id
                    _entry["device_name"] = _dev_name
                    _backfill_count += 1
            except Exception:
                continue
        if _backfill_count:
            with quality.QUALITY_LOCK:
                quality._save_quality_log(quality_data)
            log.info(f"  device_id backfill: {_backfill_count} entries updated")
            quality.save_device_table(quality_data)
        else:
            log.info("  device_id backfill: no raw files with training_status found")

    # ── 5c. Source backfill — re-fetch API days without source/ file ──────────
    if os.environ.get("GARMIN_SOURCE_BACKFILL") == "1":
        _run_source_backfill(client, quality_data)

    # ── 5d. Steps backfill — enrich already-archived days with steps field ────
    if os.environ.get("GARMIN_STEPS_BACKFILL") == "1":
        _run_steps_backfill(client, quality_data)

    # ── 6. Set first_day ──────────────────────────────────────────────────────
    with quality.QUALITY_LOCK:
        if not quality_data.get("first_day"):
            quality._set_first_day(quality_data, client)

        quality._save_quality_log(quality_data)

    # ── 7. Resolve date list ──────────────────────────────────────────────────
    recheck_dates = {
        date.fromisoformat(e["date"])
        for e in quality_data.get("days", [])
        if e.get("recheck", False)
    }

    # bulk upgrade candidates — always excluded from local, regardless of REFRESH_FAILED
    bulk_upgrade_dates = {
        date.fromisoformat(e["date"])
        for e in quality_data.get("days", [])
        if e.get("recheck", False) and e.get("source") == "bulk"
    }
    if bulk_upgrade_dates:
        log.info(f"  Bulk upgrade: {len(bulk_upgrade_dates)} day(s) queued for API re-fetch")

    if cfg.SYNC_DATES:
        local   = sync.get_local_dates(cfg.RAW_DIR)
        missing = sorted(d for d in cfg.SYNC_DATES if d not in local or cfg.REFRESH_FAILED)
        log.info(f"  SYNC_DATES mode: {len(cfg.SYNC_DATES)} requested, {len(missing)} to fetch")
    else:
        exclude = (recheck_dates if cfg.REFRESH_FAILED else set()) | bulk_upgrade_dates
        local   = sync.get_local_dates(cfg.RAW_DIR, exclude if exclude else None)
        start, end = sync.resolve_date_range(quality_data.get("first_day"))
        missing    = sorted(set(sync.date_range(start, end)) - local)

    if not missing:
        log.info("All days already present — nothing to do.")
        _close_session_log(_session_fh, _session_path,
                           _session_had_errors, _session_had_incomplete)
        return

    log.info(f"Local: {len(local)} days  |  Missing: {len(missing)} days")
    if cfg.SYNC_DATES:
        log.info(f"Fetching {len(missing)} specific days ...")
    else:
        log.info(f"Fetching {missing[0]} to {missing[-1]} ...")

    # ── 8. Fetch loop ─────────────────────────────────────────────────────────
    # MAX_DAYS_PER_SESSION: 0 = unlimited, >0 = cap per run
    batch = missing if cfg.MAX_DAYS_PER_SESSION == 0 else missing[:cfg.MAX_DAYS_PER_SESSION]
    if cfg.MAX_DAYS_PER_SESSION > 0 and len(missing) > cfg.MAX_DAYS_PER_SESSION:
        log.info(f"  Session limit: processing {len(batch)} of {len(missing)} missing days "
                 f"(MAX_DAYS_PER_SESSION={cfg.MAX_DAYS_PER_SESSION})")

    ok, failed = 0, 0

    with quality.QUALITY_LOCK:
        for i, day in enumerate(batch, 1):
            if _is_stopped():
                log.info(f"  Stopped after {ok} days saved.")
                break
            log.info(f"  [{i}/{len(batch)}] {day}")
            date_str = day.isoformat()
            try:
                label, normalized, summary, fields, val_result = _fetch_and_assess(client, date_str)

                # ── downgrade protection ──────────────────────────────────────
                existing_entry = next(
                    (e for e in quality_data.get("days", []) if e.get("date") == date_str),
                    None
                )
                is_downgrade, existing_label, existing_source = _check_downgrade(label, existing_entry)

                if is_downgrade:
                    log.warning(f"    ⚠ API result inferior ({label} < {existing_label}) — kept existing")
                    # Bulk recheck: increment attempts, disable recheck after 2 tries.
                    # One transient failure is acceptable; a second downgrade means the
                    # API permanently delivers less than the bulk export for this day.
                    bulk_attempts = existing_entry.get("attempts", 0) + 1 if existing_source == "bulk" else existing_entry.get("attempts", 0)
                    bulk_recheck  = (existing_source == "bulk" and bulk_attempts < 2)
                    # INTENTIONAL DIRECT CALL — record_attempt cannot be used here:
                    # recheck + attempts are manually patched after upsert (bulk downgrade logic).
                    quality._upsert_quality(quality_data, day, existing_label,
                                            f"Quality: {existing_label} — API downgrade rejected ({bulk_attempts} attempts)" if existing_source == "bulk" else f"Quality: {existing_label} — API downgrade rejected",
                                            written=existing_entry.get("write", False),
                                            source=existing_source,
                                            fields=fields, validator_result=val_result)
                    if existing_source == "bulk":
                        # Manually patch recheck + attempts — _upsert_quality resets these
                        patched = next((e for e in quality_data["days"] if e.get("date") == date_str), None)
                        if patched:
                            patched["attempts"] = bulk_attempts
                            patched["recheck"]  = bulk_recheck
                            if not bulk_recheck:
                                log.info(f"    ℹ {date_str}: bulk recheck exhausted after {bulk_attempts} attempts — accepted")
                    quality._save_quality_log(quality_data)
                    ok += 1
                    continue

                written = _write_assessed(normalized, summary, date_str, label)
                reason  = f"Quality: {label}"

                # prev_high lookup — check if previous calendar day has quality == "high"
                prev_date_str = (day - timedelta(days=1)).isoformat()
                prev_entry    = next(
                    (e for e in quality_data["days"] if e.get("date") == prev_date_str),
                    None
                )
                prev_high = prev_entry is not None and prev_entry.get("quality") == "high"

                # device_id lookup via training_status
                # latestTrainingStatusData is a dict keyed by deviceId (str)
                # first key = recording device ID for this day
                device_id   = None
                device_name = None
                if normalized:
                    ts   = normalized.get("training_status") or {}
                    mrts = ts.get("mostRecentTrainingStatus") if isinstance(ts, dict) else None
                    lts  = mrts.get("latestTrainingStatusData") if isinstance(mrts, dict) else None
                    if isinstance(lts, dict) and lts:
                        device_id = str(next(iter(lts)))
                        # Resolve name from devices list
                        for dev in quality_data.get("devices", []):
                            if str(dev.get("id", "")) == device_id:
                                device_name = dev.get("name", "")
                                break

                quality.record_attempt(quality_data, day, label, reason,
                                       written=written, source="api", fields=fields,
                                       validator_result=val_result,
                                       device_id=device_id, device_name=device_name,
                                       prev_high=prev_high)
                if label == "failed":
                    _session_had_incomplete = True
                    log.warning(f"    ⚠ Fetch failed ({label}) — flagged for recheck")
                else:
                    log.info(f"    ✓ Quality: {label}"
                             + (f" [device={device_name or device_id}]" if device_id else ""))
                ok += 1

                # GP-2 crash-resilience: persist quality_log after each day so a
                # hard abort (power loss, kill) cannot leave a raw file without a
                # quality_log entry. skip_backup=True — backup triggered once in
                # Step 9 after the full batch, not per day.
                try:
                    quality._save_quality_log(quality_data, skip_backup=True)
                except Exception as _save_err:
                    log.error(f"    quality_log save failed after {day}: {_save_err}")
                    _session_had_errors = True
                    raise

            except Exception as e:
                log.error(f"    Error on {day}: {e}")
                quality.record_attempt(quality_data, day, "failed", str(e), written=False, source="api")
                failed += 1
                _session_had_errors = True

        # ── 9. Save + close ───────────────────────────────────────────────────
        quality._save_quality_log(quality_data)
        quality.save_device_table(quality_data)

    log.info(f"Done. {ok} saved, {failed} errors.")
    recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
    log.info(f"Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")
    log.info(f"Raw data:    {cfg.RAW_DIR}")
    log.info(f"Summaries:   {cfg.SUMMARY_DIR}  ← point Open WebUI Knowledge Base here")

    # ── 9b. Source backup backfill ────────────────────────────────────────────
    # Runs after the normal backup cycle (Step 9) is complete.
    # Guard: only in normal sync mode — not during source backfill re-fetch
    # (GARMIN_SOURCE_BACKFILL=1) and only when at least one day was processed.
    if ok > 0 and os.environ.get("GARMIN_SOURCE_BACKFILL") != "1":
        try:
            import garmin_backup_source as _bsrc
            _bsrc_needed = _bsrc.check_source_backfill_needed()
            if _bsrc_needed > 0:
                log.info(f"  Source backup backfill: {_bsrc_needed} file(s) without backup — running ...")
                _bsrc_result = _bsrc.backfill_source()
                log.info(
                    f"  Source backup backfill done: "
                    f"{_bsrc_result['copied']} copied, "
                    f"{_bsrc_result['skipped']} skipped, "
                    f"{_bsrc_result['failed']} failed."
                )
        except Exception as _bsrc_err:
            log.warning(f"  Source backup backfill failed: {_bsrc_err}")

    _close_session_log(_session_fh, _session_path,
                       _session_had_errors, _session_had_incomplete)


if __name__ == "__main__":
    main()
