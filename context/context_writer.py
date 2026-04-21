#!/usr/bin/env python3
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

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def write(plugin, data: dict[str, dict],
          lat: float, lon: float) -> dict:
    """
    Write fetched data to context_data/ based on plugin metadata.

    Args:
        plugin:  Plugin module (weather_plugin or pollen_plugin).
        data:    {date_str: {field: value}} from context_api.fetch().
        lat:     Latitude used for this fetch segment.
        lon:     Longitude used for this fetch segment.

    Returns:
        {"written": int, "failed": int}
    """
    written = failed = 0
    fetched_at  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    aggregation = getattr(plugin, "AGGREGATION", None)

    try:
        plugin.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning(f"  context_writer: could not create dir {plugin.OUTPUT_DIR} — {exc}")
        return {"written": 0, "failed": len(data)}

    for ds, fields in data.items():
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

    log.info(f"  context_writer [{plugin.NAME}]: written={written} failed={failed}")
    return {"written": written, "failed": failed}


def already_written(plugin, date_str: str) -> bool:
    """Return True if the file for this plugin + date already exists."""
    return (plugin.OUTPUT_DIR / f"{plugin.FILE_PREFIX}{date_str}.json").exists()
