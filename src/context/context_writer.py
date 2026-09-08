#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
context_writer.py

Writes fetched context data to the local archive based on plugin metadata.

Reads plugin definitions (OUTPUT_DIR, FILE_PREFIX, SOURCE_TAG, AGGREGATION)
and writes one JSON file per day into the appropriate context_data/ subfolder.

Rules:
- Never fetches data — that is context_api.py's responsibility.
- Sole write authority for context_data/ — no other module writes there.
- Never knows what a dashboard looks like.
- Only called by context_collector.py.

File structure per day:
{
    "date":        "YYYY-MM-DD",
    "source":      str,           ← plugin.SOURCE_TAG
    "fetched_at":  "YYYY-MM-DDTHH:MM:SS",
    "latitude":    float,
    "longitude":   float,
    "aggregation": str | None,    ← plugin.AGGREGATION if defined
    "fields":      {field: value, ...}
}
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def write(plugin, data: dict,
          lat: float, lon: float) -> dict:
    """
    Write fetched data to context_data/ based on plugin metadata.

    Args:
        plugin:  Plugin module (weather_plugin, pollen_plugin, brightsky_plugin,
                 airquality_plugin).
        data:    {"summary": {date: {field: value}}, "raw": {date: {field:
                 [{"ts": str, "value": ...}, ...]}}} from context_api.fetch()
                 (v1.7.1.11).
        lat:     Latitude used for this fetch segment.
        lon:     Longitude used for this fetch segment.

    Returns:
        {"written": int, "failed": int} — counts summary/ writes only,
        consistent with the pre-v1.7.1.11 contract. raw/ writes are
        best-effort alongside and not separately counted.
    """
    written = failed = 0
    fetched_at     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    aggregation    = getattr(plugin, "AGGREGATION", None)
    raw_output_dir = getattr(plugin, "RAW_OUTPUT_DIR", None)
    summary_data   = data.get("summary", {})
    raw_data       = data.get("raw", {})

    try:
        plugin.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if raw_output_dir is not None:
            raw_output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning(f"  context_writer: could not create dir for {plugin.NAME} — {exc}")
        return {"written": 0, "failed": len(summary_data)}

    for ds, fields in summary_data.items():
        tmp = None
        try:
            out = {
                "date":       ds,
                "source":     plugin.SOURCE_TAG,
                "fetched_at": fetched_at,
                "latitude":   lat,
                "longitude":  lon,
                "fields":     fields,
            }
            if aggregation:
                out["aggregation"] = aggregation

            path = plugin.OUTPUT_DIR / f"{plugin.FILE_PREFIX}{ds}.json"
            tmp  = plugin.OUTPUT_DIR / f"{plugin.FILE_PREFIX}{ds}.tmp"
            tmp.write_text(
                json.dumps(out, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            os.replace(tmp, path)
            tmp = None
            written += 1
        except OSError as exc:
            log.warning(f"  context_writer: write failed {ds} — {exc}")
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            failed += 1

    # v1.7.1.11 — raw/ (hourly, timestamped) write, only for plugins that
    # declare RAW_OUTPUT_DIR (pollen/brightsky/airquality — not weather).
    # Best-effort: a raw write failure is logged but does not affect the
    # written/failed counts above, which stay scoped to summary/ as before.
    if raw_output_dir is not None:
        for ds, fields in raw_data.items():
            tmp = None
            try:
                out = {
                    "date":       ds,
                    "source":     plugin.SOURCE_TAG,
                    "fetched_at": fetched_at,
                    "latitude":   lat,
                    "longitude":  lon,
                    "fields":     fields,   # {field: [{"ts": str, "value": ...}, ...]}
                }
                path = raw_output_dir / f"{plugin.FILE_PREFIX}{ds}.json"
                tmp  = raw_output_dir / f"{plugin.FILE_PREFIX}{ds}.tmp"
                tmp.write_text(
                    json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                os.replace(tmp, path)
                tmp = None
            except OSError as exc:
                log.warning(f"  context_writer: raw write failed {ds} — {exc}")
                if tmp is not None:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass

    log.info(f"  context_writer [{plugin.NAME}]: written={written} failed={failed}")
    return {"written": written, "failed": failed}


def already_written(plugin, date_str: str) -> bool:
    """Return True if the file for this plugin + date already exists.

    v1.7.1.11 — two-stage check: a day counts as complete only if the
    summary/ file exists AND, for plugins that declare RAW_OUTPUT_DIR,
    the raw/ file also exists. Without this, a day that has summary/
    but not yet raw/ (e.g. right after the migration wipe-check updates
    a plugin's OUTPUT_DIR) would be silently skipped and raw/ would
    never backfill for existing days. weather has no RAW_OUTPUT_DIR —
    the second condition is skipped for it automatically.
    """
    summary_ok = (plugin.OUTPUT_DIR / f"{plugin.FILE_PREFIX}{date_str}.json").exists()
    raw_output_dir = getattr(plugin, "RAW_OUTPUT_DIR", None)
    if raw_output_dir is None:
        return summary_ok
    raw_ok = (raw_output_dir / f"{plugin.FILE_PREFIX}{date_str}.json").exists()
    return summary_ok and raw_ok


def write_file(dest_path: Path, data: dict) -> bool:
    """
    Writes a pre-built context dict atomically to dest_path.
    Used by garmin_import_mirror — sole write authority for context_data/
    is preserved: all writes go through context_writer.

    Parameters
    ----------
    dest_path : Path — full destination path (including filename)
    data      : dict — content to write (already validated by caller)

    Returns
    -------
    bool — True on success, False on OSError
    """
    tmp = dest_path.with_suffix(".tmp")
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, dest_path)
        return True
    except OSError as exc:
        log.warning(f"  context_writer.write_file: failed {dest_path.name} — {exc}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
