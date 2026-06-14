#!/usr/bin/env python3
"""
garmin_quality.py

State Owner — sole authority over quality_log.json.

Responsibilities:
  - Load and save quality_log.json (exclusively — no other module writes it)
  - Assess data quality from a raw dict (in-memory, no file IO)
  - Upsert day entries with attempts tracking (v1.5.7: high/standard/failed)
  - Backfill quality log from existing raw/ files (one-time, on first run)
  - Determine and persist first_day
  - Scan raw/ for newly discovered failed quality files
  - Clean archive before first_day (dry run + delete)
  - Manage device_rank_config (v1.5.7)

All other modules receive quality data as a plain dict parameter — they
never read or write quality_log.json directly.

Implementation is split across garmin/quality/ sub-modules:
  _io.py     — Load, Save, Checksum, Defective log
  _assess.py — assess_quality (high/standard/failed), assess_quality_fields
  _scan.py   — get_low_quality_dates, _backfill_quality_log
  _maint.py  — QUALITY_RANK, _upsert_quality, _set_first_day,
               cleanup_before_first_day, update_device_rank_config
  _stats.py  — get_archive_stats (incl. device_table)

This facade re-exports all public symbols — callers remain unchanged.
"""

import threading

# ── Re-exports from sub-modules ───────────────────────────────────────────────
# sys.path contains garmin/ directly, so quality/ is importable as a package
# with flat-style imports (same pattern as context/, maps/, dashboards/).

from quality._io import (
    _load_quality_log,
    _save_quality_log,
    save_device_table,
    _save_defective_log,
    _compute_checksum,
    _compute_checksum_legacy,
    _parse_device_date,
    _safe_get,
)

from quality._assess import (
    assess_quality,
    assess_quality_fields,
)

from quality._scan import (
    get_low_quality_dates,
    _backfill_quality_log,
)

from quality._maint import (
    QUALITY_RANK,
    _upsert_quality,
    _set_first_day,
    cleanup_before_first_day,
    record_attempt,
    set_unknown_device_name,
)

from quality._stats import (
    get_archive_stats,
)

# ── QUALITY_LOCK — defined here, not in sub-modules ──────────────────────────
# All callers (garmin_collector, garmin_app_controller) import this from
# garmin_quality directly. Sub-modules never acquire it — that is the
# orchestrator's responsibility.

QUALITY_LOCK = threading.Lock()
