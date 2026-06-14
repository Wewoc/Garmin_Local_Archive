#!/usr/bin/env python3
"""
garmin_source_writer.py

Source Archive — Sole Owner of garmin_data/source/ and source_api_log.json.

Stores unmodified API responses before any pipeline processing.
Called exclusively by garmin_collector._fetch_and_assess() — two call sites:
  1. write_source()  — before garmin_validator (raw data secured first)
  2. update_log()    — after garmin_validator  (validator_status known)

Both calls are non-fatal: exceptions are logged as warnings, pipeline continues.

Invariants:
  - source/ contains exclusively live API responses.
  - Bulk import never writes to source/ — not even during backfill.
  - Days without a source/ file after the 180-day window cannot be recovered
    (Garmin degrades intraday resolution permanently beyond that boundary).
  - No lock required — sequential, single owner, no concurrent access.

Leaf-Node: imports only garmin_config and stdlib. No pipeline module imports.

Called by:
  garmin/garmin_collector.py — _fetch_and_assess() (two call sites, lazy import)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

# garmin_config is imported lazily inside each function (not at module level).
# Reason: the test suite sets GARMIN_OUTPUT_DIR and calls importlib.reload(cfg)
# after this module is first imported — a module-level import would freeze the
# wrong path. Same pattern as garmin_security.py.

log = logging.getLogger(__name__)

# Current schema version for source_api_log.json entries.
# Increment when the log entry structure changes.
SOURCE_LOG_SCHEMA_VERSION = 1

# Filename prefix for source files
SOURCE_FILE_PREFIX = "garmin_source_"


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def write_source(raw_data: dict, date_str: str) -> bool:
    """
    Writes raw API response to garmin_data/source/garmin_source_YYYY-MM-DD.json.

    Called before garmin_validator — secures raw data even if validator crashes.
    Writes atomically: .tmp → fsync → os.replace.

    Parameters
    ----------
    raw_data : dict — unmodified API response from garmin_api.fetch_raw()
    date_str : str  — date in YYYY-MM-DD format

    Returns
    -------
    bool — True on success, False on any error (non-fatal)
    """
    try:
        import garmin_config as cfg

        if not isinstance(raw_data, dict):
            log.warning(f"  source_writer.write_source: non-dict input for {date_str} — skipped")
            return False

        cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)

        dst     = cfg.SOURCE_DIR / f"{SOURCE_FILE_PREFIX}{date_str}.json"
        tmp     = dst.with_suffix(".json.tmp")
        payload = json.dumps(raw_data, ensure_ascii=False, indent=None,
                             separators=(",", ":"))

        tmp.write_text(payload, encoding="utf-8")
        try:
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
        except OSError:
            pass  # fsync not supported on all platforms/filesystems (e.g. Windows)
        os.replace(tmp, dst)

        log.debug(f"  source_writer: {date_str} → source/")
        return True

    except Exception as e:
        log.warning(f"  source_writer.write_source failed for {date_str}: {e}")
        try:
            import garmin_config as _cfg
            _cleanup_tmp(_cfg.SOURCE_DIR / f"{SOURCE_FILE_PREFIX}{date_str}.json.tmp")
        except Exception:
            pass
        return False


def update_log(
    date_str: str,
    val_result: dict,
    endpoints_fetched: list,
    endpoints_failed: list,
    size_bytes: int,
) -> bool:
    """
    Writes or updates the entry for date_str in source_api_log.json.

    Called after garmin_validator — validator_status and issues are known.
    Reads existing log (if present), upserts the entry, writes atomically.

    Parameters
    ----------
    date_str          : str  — date in YYYY-MM-DD format
    val_result        : dict — validator result: {"status", "issues", ...}
    endpoints_fetched : list — endpoint labels that returned data
    endpoints_failed  : list — endpoint labels that returned no data
    size_bytes        : int  — approximate size of raw_data in bytes

    Returns
    -------
    bool — True on success, False on any error (non-fatal)
    """
    try:
        import garmin_config as cfg
        log_path = cfg.SOURCE_API_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing log
        existing: dict = {}
        if log_path.exists():
            try:
                existing = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"  source_writer.update_log: could not read log — {e}")
                existing = {}

        # Build entry
        entry = {
            "fetched_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source":            "api",
            "schema_version":    SOURCE_LOG_SCHEMA_VERSION,
            "validator_status":  val_result.get("status", "unknown"),
            "validator_issues":  [
                i.get("field", "") for i in val_result.get("issues", [])
                if i.get("type") not in ("missing_optional",)
            ],
            "endpoints_fetched": [k for k in endpoints_fetched if k != "date"],
            "endpoints_failed":  list(endpoints_failed),
            "size_bytes":        size_bytes,
        }

        existing[date_str] = entry

        # Write atomically
        tmp = log_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
        except OSError:
            pass  # fsync not supported on all platforms/filesystems (e.g. Windows)
        os.replace(tmp, log_path)

        log.debug(f"  source_writer: log updated for {date_str}")
        return True

    except Exception as e:
        log.warning(f"  source_writer.update_log failed for {date_str}: {e}")
        try:
            import garmin_config as _cfg
            _cleanup_tmp(_cfg.SOURCE_API_LOG.with_suffix(".json.tmp"))
        except Exception:
            pass
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_tmp(tmp_path: Path) -> None:
    """Removes a leftover .tmp file after a failed atomic write. Best-effort."""
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass