#!/usr/bin/env python3
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
import garmin_sync as sync
import garmin_validator as validator
import garmin_writer as writer

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
#  Stop-event (injected by standalone GUI via module.__dict__)
# ══════════════════════════════════════════════════════════════════════════════

def _is_stopped() -> bool:
    """Returns True if the standalone GUI has requested a stop."""
    ev = globals().get("_STOP_EVENT")
    return ev is not None and ev.is_set()


# ══════════════════════════════════════════════════════════════════════════════
#  Decision + processing
# ══════════════════════════════════════════════════════════════════════════════

def _should_write(label: str) -> bool:
    """Returns True if the quality label is acceptable for writing to disk."""
    return label in ("high", "medium", "low")


def _fetch_and_assess(client, date_str: str) -> tuple:
    """
    Fetches and assesses a single day — no file writes.

    Returns
    -------
    tuple (label, normalized, summary, fields, val_result)
      label      — "high" | "medium" | "low" | "failed"
      normalized — normalized dict, or None on critical failure
      summary    — summary dict, or None on critical failure
      fields     — per-field quality dict
      val_result — validator result dict
    """
    raw_data, failed_endpoints = api.fetch_raw(client, date_str)
    if failed_endpoints:
        log.warning(f"    ⚠ {len(failed_endpoints)} endpoint(s) failed: {', '.join(failed_endpoints)}")

    val_result = validator.validate(raw_data)
    if val_result["status"] == "critical":
        log.warning(f"    ⚠ Validator critical — skipping {date_str}")
        return "failed", None, None, {}, val_result

    normalized = normalizer.normalize(raw_data, source="api")
    summary    = normalizer.summarize(normalized)
    label      = quality.assess_quality(normalized)
    fields     = quality.assess_quality_fields(normalized)

    return label, normalized, summary, fields, val_result


def _write_assessed(normalized, summary, date_str: str, label: str) -> bool:
    """
    Writes a pre-assessed day to disk. Returns True if written successfully.
    """
    if _should_write(label):
        return writer.write_day(normalized, summary, date_str)
    return False


def run_import(path, progress_callback=None) -> dict:
    """
    Imports a Garmin export ZIP or folder into the local archive.

    Iterates load_bulk() day by day — each day is normalised, assessed,
    and written before the next day is loaded (Option 2: read → build → write → repeat).

    Parameters
    ----------
    path              : str | Path — path to Garmin export ZIP or unpacked folder
    progress_callback : callable(current, total, date_str) | None
                        Called after each day. total is None (unknown upfront).

    Returns
    -------
    dict — {"ok": int, "skipped": int, "failed": int}
    """
    import garmin_import as importer

    ok, skipped, failed = 0, 0, 0

    with quality.QUALITY_LOCK:
        quality_data = quality._load_quality_log()
        known_dates  = {e["date"] for e in quality_data.get("days", []) if "date" in e}

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
            if existing and existing.get("quality") in ("high", "medium") and existing.get("source") == "api":
                log.debug(f"  import [{i}]: {date_str} — already high/medium from API, skipped")
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
                    entry["recheck"] = new_label in ("failed", "low")

            changed += 1

        if changed:
            quality._save_quality_log(quality_data)
            log.info(f"  Self-healing: {changed} day(s) updated")


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # ── 0. Import mode — delegated entry points ───────────────────────────────
    import_path = os.environ.get("GARMIN_IMPORT_PATH")
    if import_path:
        result = run_import(import_path)
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
            quality._upsert_quality(quality_data, day, q,
                                    f"Quality: {q} — insufficient data from Garmin API",
                                    written=True)

        quality._save_quality_log(quality_data)
        recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
        log.info(f"  Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")

        # ── bulk upgrade candidates ───────────────────────────────────────────
        cutoff = date.today() - timedelta(days=90)
        bulk_upgraded = 0
        for e in quality_data.get("days", []):
            if (e.get("source") == "bulk"
                    and e.get("quality") == "medium"
                    and not e.get("recheck", False)):
                try:
                    entry_date = date.fromisoformat(e["date"])
                except (ValueError, KeyError):
                    continue
                if entry_date >= cutoff:
                    e["recheck"] = True
                    bulk_upgraded += 1
        if bulk_upgraded:
            quality._save_quality_log(quality_data)
            log.info(f"  Bulk upgrade: {bulk_upgraded} day(s) flagged for API re-fetch (≤90 days, medium)")

    # ── 3b. Self-healing loop — schema version check ───────────────────────────
    _run_self_healing(quality_data)

    # ── 4. Login ──────────────────────────────────────────────────────────────
    try:
        client = api.login()
    except api.GarminLoginError as e:
        log.error(f"Login failed — aborting session: {e}")
        _close_session_log(_session_fh, _session_path, True, False)
        return

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
                _quality_rank = {"high": 3, "medium": 2, "low": 1, "failed": 0}
                existing_entry = next(
                    (e for e in quality_data.get("days", []) if e.get("date") == date_str),
                    None
                )
                existing_label  = existing_entry.get("quality", "failed") if existing_entry else "failed"
                existing_source = existing_entry.get("source", "api")     if existing_entry else "api"
                is_downgrade    = _quality_rank.get(label, 0) < _quality_rank.get(existing_label, 0)

                if is_downgrade:
                    log.warning(f"    ⚠ API result inferior ({label} < {existing_label}) — kept existing")
                    quality._upsert_quality(quality_data, day, existing_label,
                                            f"Quality: {existing_label} — API downgrade rejected",
                                            written=existing_entry.get("write", False),
                                            source=existing_source,
                                            fields=fields, validator_result=val_result)
                    quality._save_quality_log(quality_data)
                    ok += 1
                    continue

                written = _write_assessed(normalized, summary, date_str, label)
                reason  = (f"Quality: {label}" if label in ("high", "medium")
                           else f"Quality: {label} — insufficient data from Garmin API")
                quality._upsert_quality(quality_data, day, label, reason,
                                        written=written, source="api", fields=fields,
                                        validator_result=val_result)
                quality._save_quality_log(quality_data)
                if label in ("low", "failed"):
                    _session_had_incomplete = True
                    log.warning(f"    ⚠ Low data quality ({label}) — flagged for recheck")
                else:
                    log.info(f"    ✓ Quality: {label}")
                ok += 1
            except Exception as e:
                log.error(f"    Error on {day}: {e}")
                quality._upsert_quality(quality_data, day, "failed", str(e), written=False, source="api")
                quality._save_quality_log(quality_data)
                failed += 1
                _session_had_errors = True

        # ── 9. Save + close ───────────────────────────────────────────────────
        quality._save_quality_log(quality_data)

    log.info(f"Done. {ok} saved, {failed} errors.")
    recheck_count = sum(1 for e in quality_data.get("days", []) if e.get("recheck", False))
    log.info(f"Quality log: {len(quality_data['days'])} days tracked, {recheck_count} pending recheck")
    log.info(f"Raw data:    {cfg.RAW_DIR}")
    log.info(f"Summaries:   {cfg.SUMMARY_DIR}  ← point Open WebUI Knowledge Base here")

    _close_session_log(_session_fh, _session_path,
                       _session_had_errors, _session_had_incomplete)


if __name__ == "__main__":
    main()
