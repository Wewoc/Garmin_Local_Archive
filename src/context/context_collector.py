#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
context_collector.py

Orchestrator for the context data pipeline.

Responsibilities:
- Reads date range from local Garmin archive (first_day → newest day)
- Reads location config from local_config.csv (with GUI-setting fallback)
- Creates local_config.csv on first run if not present
- Splits date range into segments per location
- Calls context_api.fetch() and context_writer.write() per plugin per segment
- Passes stop_event to allow GUI cancellation

Called by the GUI via the "API Sync" button — runs in a background thread.

Plugin registry: add new plugins by importing and adding to _PLUGINS list.
"""

import csv
import json
import logging
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
sys.path.insert(0, str(Path(__file__).parent.parent))
import garmin_config as cfg
import garmin_quality as quality
import log_utils

from . import context_api
from . import context_writer
from . import weather_plugin
from . import pollen_plugin
from . import brightsky_plugin
from . import airquality_plugin

log = logging.getLogger(__name__)

# ── Plugin registry ────────────────────────────────────────────────────────────

_PLUGINS = [
    weather_plugin,
    pollen_plugin,
    brightsky_plugin,
    airquality_plugin,
]

# ── CSV config ─────────────────────────────────────────────────────────────────

_CSV_FILE = cfg.LOCAL_CONFIG_FILE

_CSV_HEADER_COMMENT = """\
# Garmin Local Archive — Location Config
# date_from, date_to: YYYY-MM-DD
# country: country name in English (e.g. Germany, Spain, France)
# place: city or town name (e.g. Berlin, Palma de Mallorca)
# latitude, longitude: filled automatically by the app after geocoding
#   Leave empty — the app fills them on next API Sync setup.
#   Example row:
#   2025-01-01;2025-12-31;Germany;Berlin;52.470933;13.365109
"""

_CSV_COLUMNS = ["date_from", "date_to", "country", "place", "latitude", "longitude"]


# ══════════════════════════════════════════════════════════════════════════════
#  CSV helpers
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_csv() -> None:
    """Create local_config.csv with header if it does not exist."""
    if _CSV_FILE.exists():
        return
    try:
        _CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = _CSV_HEADER_COMMENT + ";".join(_CSV_COLUMNS) + "\n"
        _CSV_FILE.write_text(lines, encoding="utf-8-sig")
        log.info(f"  context_collector: created {_CSV_FILE}")
    except OSError as exc:
        log.warning(f"  context_collector: could not create CSV — {exc}")


def _load_csv() -> list[dict]:
    """
    Load location entries from local_config.csv.
    Skips comment lines and rows with missing/invalid coordinates.
    Returns list of dicts with keys: date_from, date_to, lat, lon.
    """
    entries = []
    if not _CSV_FILE.exists():
        return entries
    try:
        with open(_CSV_FILE, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("date_from"):
                    continue   # header row
                parts = next(csv.reader([line], delimiter=";"))
                if len(parts) < 6:
                    continue
                try:
                    entries.append({
                        "date_from": parts[0].strip(),
                        "date_to":   parts[1].strip(),
                        "lat":       float(parts[4].strip()),
                        "lon":       float(parts[5].strip()),
                    })
                except (ValueError, IndexError):
                    continue   # skip rows with missing/invalid coordinates
    except OSError as exc:
        log.warning(f"  context_collector: could not read CSV — {exc}")
    return entries


def _build_location_map(date_from: str, date_to: str,
                        csv_entries: list[dict],
                        default_lat: float,
                        default_lon: float) -> dict[str, tuple[float, float]]:
    """
    Build {date_str: (lat, lon)} for every date in range.
    CSV entries take priority. Dates not covered by CSV use default.
    """
    location_map = {}
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    while d <= end:
        ds  = d.isoformat()
        lat = default_lat
        lon = default_lon
        for entry in csv_entries:
            if entry["date_from"] <= ds <= entry["date_to"]:
                lat = entry["lat"]
                lon = entry["lon"]
                break
        location_map[ds] = (lat, lon)
        d += timedelta(days=1)
    return location_map


def _split_into_segments(location_map: dict[str, tuple]) -> list[dict]:
    """
    Split location_map into contiguous segments with identical coordinates.
    Returns list of {"date_from", "date_to", "lat", "lon"}.
    """
    if not location_map:
        return []

    dates    = sorted(location_map.keys())
    segments = []
    seg_start = dates[0]
    seg_lat, seg_lon = location_map[seg_start]
    prev_ds = dates[0]

    for ds in dates[1:]:
        lat, lon = location_map[ds]
        if (lat, lon) != (seg_lat, seg_lon):
            segments.append({"date_from": seg_start, "date_to": prev_ds,
                              "lat": seg_lat, "lon": seg_lon})
            seg_start = ds
            seg_lat, seg_lon = lat, lon
        prev_ds = ds

    segments.append({"date_from": seg_start, "date_to": dates[-1],
                     "lat": seg_lat, "lon": seg_lon})
    return segments


# ══════════════════════════════════════════════════════════════════════════════
#  Archive date range
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_date_range(base_dir: str = None) -> tuple[str, str] | tuple[None, None]:
    """Determine collect range from local Garmin archive."""
    try:
        qlog_path = None
        if base_dir:
            qlog_path = str(Path(base_dir) / "garmin_data" / "log" / "quality_log.json")
        stats = quality.get_archive_stats(quality_log_path=qlog_path)
    except Exception as exc:
        log.warning(f"  context_collector: could not read archive stats — {exc}")
        return None, None

    date_from  = stats.get("date_min")
    candidates = [stats.get("last_api"), stats.get("last_bulk"), stats.get("date_max")]
    date_to    = max((d for d in candidates if d), default=None)

    if not date_from or not date_to:
        log.warning("  context_collector: archive empty — no date range available")
        return None, None

    date_to = min(date_to, date.today().isoformat())
    log.info(f"  context_collector: date range {date_from} → {date_to}")
    return date_from, date_to


# ══════════════════════════════════════════════════════════════════════════════
#  MCP resync-marker cleanup (v1.7.2.3 — see PROTOKOLL_experiment.md,
#  Baustein 5, for the full cross-module design/reasoning trail)
# ══════════════════════════════════════════════════════════════════════════════

def _consume_context_resync_ack(base: Path) -> None:
    """
    Reads clients/mcp_update.py's context-resync ack record — a file it
    owns under garmin_data/log/mcp/, never context_data/ — and removes
    the acknowledged entries from context_silo_repair.py's pending-resync
    marker via context_writer.write_file(). context_writer remains sole
    write authority for context_data/; this function only ever READS the
    foreign ack file, it never writes there, so no write-authority
    conflict either direction.

    Idempotent: a second read of the same ack content removes nothing
    further, since the matching pending entries are already gone. Runs
    unconditionally at the start of every Sync Context call — both files
    are typically tiny (a handful of repaired days at most), so the
    extra read is negligible; a missing ack or pending file is the
    normal case (no coordinate repair has run yet) and is a silent no-op.

    v1.7.2.3 correction (2026-09-20): matching uses the full
    (date, source, marked_at) triple, not just (date, source) — see
    context_silo_repair.py's _mark_pending_resync() docstring for why
    marked_at exists. Matching on (date, source) alone would remove a
    pending entry that was re-marked (a second real repair) AFTER
    mcp_update.py acked an earlier occurrence of the same (date,
    source), discarding a not-yet-synced correction.
    """
    ack_path     = base / "garmin_data" / "log" / "mcp" / "context_resync_ack.json"
    pending_path = base / "context_data" / "_mcp_resync_pending.json"
    if not ack_path.exists() or not pending_path.exists():
        return
    try:
        acked = json.loads(ack_path.read_text(encoding="utf-8")).get("acked", [])
    except (OSError, json.JSONDecodeError):
        return
    if not acked:
        return
    acked_keys = {(e.get("date"), e.get("source"), e.get("marked_at")) for e in acked}
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8")).get("pending", [])
    except (OSError, json.JSONDecodeError):
        return
    remaining = [e for e in pending
                 if (e.get("date"), e.get("source"), e.get("marked_at")) not in acked_keys]
    if len(remaining) == len(pending):
        return  # nothing acknowledged yet was actually pending — no-op
    context_writer.write_file(pending_path, {"pending": remaining})
    log.info(
        f"  context_collector: cleared {len(pending) - len(remaining)} "
        f"acknowledged context-resync marker(s)"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def run(settings: dict = None, stop_event=None,
        log_callback=None) -> dict:
    """
    Run all registered plugins for the full archive date range.

    Args:
        settings:     Dict from GUI. Must contain "context_latitude" and
                      "context_longitude" as default location fallback.
        stop_event:   Optional threading.Event — checked between segments.
        log_callback: Optional callable(str) — called with progress messages
                      every PROGRESS_LOG_INTERVAL days written. None = headless.
    """
    log.info("context_collector: starting API sync")
    log_callback = log_utils.with_timestamp(log_callback)
    _PROGRESS_LOG_INTERVAL = 25
    global _CSV_FILE
    if settings and settings.get("base_dir"):
        base = Path(settings["base_dir"])
        _CSV_FILE = base / "local_config.csv"
        # Override plugin output dirs to use correct base_dir
        # v1.7.1.11 — summary/ (daily, old "raw" meaning) + raw/ (hourly,
        # new) for the three hourly sources. weather stays summary-only.
        weather_plugin.OUTPUT_DIR         = base / "context_data" / "weather"    / "summary"
        pollen_plugin.OUTPUT_DIR          = base / "context_data" / "pollen"     / "summary"
        pollen_plugin.RAW_OUTPUT_DIR      = base / "context_data" / "pollen"     / "raw"
        brightsky_plugin.OUTPUT_DIR       = base / "context_data" / "brightsky"  / "summary"
        brightsky_plugin.RAW_OUTPUT_DIR   = base / "context_data" / "brightsky"  / "raw"
        airquality_plugin.OUTPUT_DIR      = base / "context_data" / "airquality" / "summary"
        airquality_plugin.RAW_OUTPUT_DIR  = base / "context_data" / "airquality" / "raw"

        # v1.7.1.11 — one-time migration check. If a source's summary/
        # does not exist yet, it predates the raw/summary split (the old
        # code only ever knew a "raw/" folder with daily meaning) — wipe
        # everything under that source so the next sync re-fetches from
        # the API with both summary/ and raw/ populated. Idempotent: a
        # source that already has summary/ is left untouched, so an
        # accidental second run is a no-op. weather gets no special case
        # — it simply has no RAW_OUTPUT_DIR, the wipe still applies to
        # its own summary/ folder like any other source.
        for _plugin in _PLUGINS:
            if not _plugin.OUTPUT_DIR.exists():
                log.info(
                    f"  context_collector: {_plugin.NAME} — summary/ missing, "
                    f"wiping for v1.7.1.11 migration"
                )
                _source_root = _plugin.OUTPUT_DIR.parent
                if _source_root.exists():
                    shutil.rmtree(_source_root, ignore_errors=True)

        _consume_context_resync_ack(base)
    _ensure_csv()

    # Default location from GUI settings
    try:
        default_lat = float((settings or {}).get("context_latitude")  or cfg.CONTEXT_LATITUDE)
        default_lon = float((settings or {}).get("context_longitude") or cfg.CONTEXT_LONGITUDE)
    except (TypeError, ValueError):
        default_lat = cfg.CONTEXT_LATITUDE
        default_lon = cfg.CONTEXT_LONGITUDE

    if default_lat == 0.0 and default_lon == 0.0:
        log.warning("  context_collector: location not configured — aborting")
        return {"date_from": None, "date_to": None, "segments": 0,
                "plugins": {}, "stopped": False,
                "error": "Location not configured. Set location in GUI settings first."}

    # Date range
    date_from, date_to = _resolve_date_range(base_dir=settings.get("base_dir") if settings else None)
    if not date_from:
        return {"date_from": None, "date_to": None, "segments": 0,
                "plugins": {}, "stopped": False,
                "error": "Archive empty — run Garmin sync first."}

    # Build location map + segments
    csv_entries  = _load_csv()
    location_map = _build_location_map(date_from, date_to, csv_entries,
                                       default_lat, default_lon)
    segments     = _split_into_segments(location_map)

    results  = {p.NAME: {"written": 0, "skipped": 0, "failed": 0} for p in _PLUGINS}
    stopped  = False

    for segment in segments:
        if stop_event and stop_event.is_set():
            stopped = True
            break

        seg_from = segment["date_from"]
        seg_to   = segment["date_to"]
        lat      = segment["lat"]
        lon      = segment["lon"]

        log.info(f"  context_collector: segment {seg_from}→{seg_to} "
                 f"lat={lat} lon={lon}")

        for plugin in _PLUGINS:
            if stop_event and stop_event.is_set():
                stopped = True
                break

            name = plugin.NAME

            # Brightsky covers Germany only — skip outside bounding box
            if plugin is brightsky_plugin:
                if not (47.2 <= lat <= 55.1 and 5.8 <= lon <= 15.1):
                    log.info(
                        f"  context_collector: skipping brightsky — "
                        f"location ({lat}, {lon}) outside Germany"
                    )
                    continue

            # Skip dates already written
            d   = date.fromisoformat(seg_from)
            end = date.fromisoformat(seg_to)
            skip  = set()
            fetch_from = None
            while d <= end:
                ds = d.isoformat()
                if context_writer.already_written(plugin, ds):
                    skip.add(ds)
                elif fetch_from is None:
                    fetch_from = ds
                d += timedelta(days=1)

            results[name]["skipped"] += len(skip)

            if fetch_from is None:
                continue   # all dates already present

            try:
                data = context_api.fetch(plugin, fetch_from, seg_to,
                                         lat, lon, skip_dates=skip)
                write_result = context_writer.write(plugin, data, lat, lon)
                results[name]["written"] += write_result["written"]
                results[name]["failed"]  += write_result["failed"]
                if log_callback and results[name]["written"] % _PROGRESS_LOG_INTERVAL == 0 \
                        and results[name]["written"] > 0:
                    log_callback(
                        f"  Context sync: {name} — "
                        f"{results[name]['written']} days written"
                    )
            except Exception as exc:
                log.warning(f"  context_collector: plugin '{name}' failed — {exc}")
                results[name]["failed"] += 1

    log.info(f"  context_collector: done — stopped={stopped}")
    return {
        "date_from": date_from,
        "date_to":   date_to,
        "segments":  len(segments),
        "plugins":   results,
        "stopped":   stopped,
    }
