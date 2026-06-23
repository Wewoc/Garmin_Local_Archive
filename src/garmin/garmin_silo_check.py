#!/usr/bin/env python3
"""
garmin/garmin_silo_check.py
Garmin Local Archive — Silo-Reconciliation-Check

Read-only drift detection across the data silos.
Surfaces inconsistencies that the live pipeline does not catch on its own:
old drift (pre-existing gaps), manual file operations, interrupted runs,
import errors.

Principle: a missing silo is a defect only if it can be reconstructed from raw.
raw is the canonical truth.

Covered checks (reconstructability principle — KONZEPT §3):
  #1  raw without quality_log entry      (orphan — processed but not logged)
  #3  source without raw                 (raw rebuildable from existing source)
  #5  summary without raw                (orphan summary — source raw gone)
  #7  raw without summary                (derived file missing — rebuildable)

Not covered:
  #2  quality_log entry without raw      — owned by garmin_backup.check_raw_integrity()
  #4  raw without source                 — source absence is never a defect (§2a)
  #6  source_api_log without source      — same logic, not actionable

Leaf-Node: imports only garmin_config + stdlib.
No writes. No imports of write modules. No API calls.

Public API:
  check_silos() -> dict
"""

import json
import logging
from datetime import date, datetime, timezone

import garmin_config as cfg

log = logging.getLogger(__name__)

# Filename prefixes — must match garmin_config / garmin_writer conventions
_RAW_PREFIX     = "garmin_raw_"
_SUMMARY_PREFIX = "garmin_"
_SOURCE_PREFIX  = "garmin_source_"


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _extract_date(stem: str, prefix: str) -> date | None:
    """
    Extracts a date from a file stem by stripping prefix.
    Returns None on any parse failure — no exception propagation.
    Inline implementation: garmin_silo_check is a Leaf-Node and cannot import
    garmin_utils. Logic mirrors garmin_utils.extract_date_from_filename().
    """
    try:
        return date.fromisoformat(stem.replace(prefix, "", 1))
    except (ValueError, AttributeError):
        return None


def _collect_raw_dates() -> set[date]:
    """Returns the set of dates with a garmin_raw_*.json file in RAW_DIR."""
    result: set[date] = set()
    if not cfg.RAW_DIR.exists():
        return result
    for f in cfg.RAW_DIR.glob(f"{_RAW_PREFIX}*.json"):
        d = _extract_date(f.stem, _RAW_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_summary_dates() -> set[date]:
    """Returns the set of dates with a garmin_*.json file in SUMMARY_DIR.
    Excludes non-date stems (e.g. garmin_dataformat.json) via ValueError on parse."""
    result: set[date] = set()
    if not cfg.SUMMARY_DIR.exists():
        return result
    for f in cfg.SUMMARY_DIR.glob(f"{_SUMMARY_PREFIX}*.json"):
        d = _extract_date(f.stem, _SUMMARY_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_source_dates() -> set[date]:
    """Returns the set of dates with a garmin_source_*.json file in SOURCE_DIR."""
    result: set[date] = set()
    if not cfg.SOURCE_DIR.exists():
        return result
    for f in cfg.SOURCE_DIR.glob(f"{_SOURCE_PREFIX}*.json"):
        d = _extract_date(f.stem, _SOURCE_PREFIX)
        if d is not None:
            result.add(d)
    return result


def _collect_quality_dates() -> tuple[set[date], int]:
    """
    Reads quality_log.json and returns:
      - set of dates that have an entry (any quality label)
      - total count of entries (len(data["days"]))
    Returns (empty set, 0) if the file is missing or unreadable.
    Reads without acquiring QUALITY_LOCK — atomic writes (os.replace) guarantee
    a complete file is always visible to readers (§9a).
    """
    result: set[date] = set()
    count = 0
    if not cfg.QUALITY_LOG_FILE.exists():
        return result, count
    try:
        data = json.loads(cfg.QUALITY_LOG_FILE.read_text(encoding="utf-8"))
        days = data.get("days", [])
        count = len(days)
        for entry in days:
            date_str = entry.get("date")
            if not date_str:
                continue
            try:
                result.add(date.fromisoformat(date_str))
            except ValueError:
                pass
    except (OSError, json.JSONDecodeError) as e:
        log.warning("garmin_silo_check: could not read quality_log.json: %s", e)
    return result, count


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def check_silos() -> dict:
    """
    Read-only drift detection across the data silos.

    Returns a dict with four finding lists, totals, counts, and a timestamp:

    {
      "raw_without_quality":  [date, ...],   # #1 — orphan raw, no quality_log entry
      "source_without_raw":   [date, ...],   # #3 — source file without matching raw
      "summary_without_raw":  [date, ...],   # #5 — orphan summary, source raw gone
      "raw_without_summary":  [date, ...],   # #7 — raw exists, summary missing
      "checked_at":           "ISO-8601",
      "totals": {
        "raw":          int,   # count of garmin_raw_*.json files
        "summary":      int,   # count of garmin_*.json files in SUMMARY_DIR
        "source":       int,   # count of garmin_source_*.json files
        "quality_days": int,   # len(quality_log["days"])
      },
      "counts": {
        "raw_without_quality": int,
        "source_without_raw":  int,
        "summary_without_raw": int,
        "raw_without_summary": int,
      },
    }

    Check #2 (quality_log entry without raw) is owned by
    garmin_backup.check_raw_integrity() and is not included here (Option C).
    """
    log.debug("garmin_silo_check: starting silo check")

    raw_dates     = _collect_raw_dates()
    summary_dates = _collect_summary_dates()
    source_dates  = _collect_source_dates()
    quality_dates, quality_count = _collect_quality_dates()

    # ── #1: raw without quality_log entry ─────────────────────────────────────
    raw_without_quality = sorted(raw_dates - quality_dates)

    # ── #3: source without raw ─────────────────────────────────────────────────
    source_without_raw = sorted(source_dates - raw_dates)

    # ── #5: summary without raw ────────────────────────────────────────────────
    summary_without_raw = sorted(summary_dates - raw_dates)

    # ── #7: raw without summary ────────────────────────────────────────────────
    raw_without_summary = sorted(raw_dates - summary_dates)

    checked_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = {
        "raw_without_quality": raw_without_quality,
        "source_without_raw":  source_without_raw,
        "summary_without_raw": summary_without_raw,
        "raw_without_summary": raw_without_summary,
        "checked_at": checked_at,
        "totals": {
            "raw":          len(raw_dates),
            "summary":      len(summary_dates),
            "source":       len(source_dates),
            "quality_days": quality_count,
        },
        "counts": {
            "raw_without_quality": len(raw_without_quality),
            "source_without_raw":  len(source_without_raw),
            "summary_without_raw": len(summary_without_raw),
            "raw_without_summary": len(raw_without_summary),
        },
    }

    total_findings = sum(result["counts"].values())
    log.debug(
        "garmin_silo_check: done — raw=%d, summary=%d, source=%d, "
        "quality_days=%d, findings=%d",
        len(raw_dates), len(summary_dates), len(source_dates),
        quality_count, total_findings,
    )

    return result
