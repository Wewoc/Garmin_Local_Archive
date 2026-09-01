#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_force_refetch.py

Force-Refetch Snapshot — Sole Owner of garmin_data/backup/force_refetch/.

Snapshots the archived source/ file for a single day before a deliberate
Force-Refetch overwrite (v1.7.1.7), and can restore it if the new fetch
turns out worse than expected.

Motivation: Force-Refetch deliberately bypasses the freeze-when-present
guard (garmin_source_quality.compare_source(force=True)) that otherwise
protects source/ against downgrade. That guard exists for good reason —
this snapshot is the safety net for the one path that intentionally
overrides it.

Scope: source/ only, not raw/. For the "api" origin, raw/summary are
derived from source/ (garmin_normalizer._normalize_api() is a pass-through
— raw is structurally identical to source), so a source/ snapshot alone is
sufficient to reconstruct the day if a restore is ever needed.

Strategy: flat directory, one file per day — no monthly consolidation
(unlike garmin_backup_source.py). Force-Refetch is a rare, deliberate
maintenance action, not a high-volume daily path; ZIP consolidation would
add complexity without a corresponding benefit here.

Public API:
  snapshot_source(date_str)   → dict  — snapshot source/ file before overwrite
  restore_snapshot(date_str)  → bool  — restore a previously snapshotted file

No file IO beyond what these two functions require. No pipeline module
imports besides garmin_config.

Called by:
  garmin/garmin_collector.py — Force-Refetch orchestrator (Baustein 4,
  not yet built at the time this file was created)
"""

import logging

import garmin_config as cfg

log = logging.getLogger(__name__)

# Filename prefix for source files — must match garmin_source_writer.py
_SOURCE_PREFIX = "garmin_source_"


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def snapshot_source(date_str: str) -> dict:
    """
    Copies the current source/garmin_source_YYYY-MM-DD.json into
    backup/force_refetch/ before a Force-Refetch overwrite.

    Called immediately before _fetch_and_assess(force=True) — secures the
    pre-overwrite state so restore_snapshot() can undo the write if the new
    fetch turns out worse.

    If no source/ file exists for date_str (e.g. the day was previously
    "failed" and never written), there is nothing to snapshot — this is a
    valid, expected case for a Force-Refetch target, not an error.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    dict with keys:
      snapshotted    bool — True if a snapshot was written
      had_prior_data bool — True if a source/ file existed for this date
                             before the snapshot attempt
    """
    src = cfg.SOURCE_DIR / f"{_SOURCE_PREFIX}{date_str}.json"

    if not src.exists():
        log.info(f"  force_refetch.snapshot_source: no prior source/ file for {date_str}")
        return {"snapshotted": False, "had_prior_data": False}

    try:
        cfg.FORCE_REFETCH_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = cfg.FORCE_REFETCH_BACKUP_DIR / src.name
        dst.write_bytes(src.read_bytes())
        log.info(f"  force_refetch.snapshot_source: {date_str} → backup/force_refetch/")
        return {"snapshotted": True, "had_prior_data": True}

    except Exception as e:
        log.error(f"  force_refetch.snapshot_source: failed for {date_str}: {e}")
        return {"snapshotted": False, "had_prior_data": True}


def restore_snapshot(date_str: str) -> bool:
    """
    Restores source/garmin_source_YYYY-MM-DD.json from a previously
    written Force-Refetch snapshot, overwriting the current source/ file.

    No GUI entry point yet (v1.7.1.7) — deferred to a later session.
    Callable directly (CLI/future GUI) once a snapshot exists.

    Does not consult compare_source()/the freeze-when-present guard — a
    deliberate restore-to-known-good-state is, like Force-Refetch itself,
    an intentional exception to that guard, not a normal pipeline write.

    Parameters
    ----------
    date_str : str — date in YYYY-MM-DD format

    Returns
    -------
    bool — True on success, False if no snapshot exists or on any error
    """
    snap = cfg.FORCE_REFETCH_BACKUP_DIR / f"{_SOURCE_PREFIX}{date_str}.json"

    if not snap.exists():
        log.warning(f"  force_refetch.restore_snapshot: no snapshot found for {date_str}")
        return False

    try:
        cfg.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
        dst = cfg.SOURCE_DIR / snap.name
        dst.write_bytes(snap.read_bytes())
        log.info(f"  force_refetch.restore_snapshot: {date_str} ← backup/force_refetch/")
        return True

    except Exception as e:
        log.error(f"  force_refetch.restore_snapshot: failed for {date_str}: {e}")
        return False
