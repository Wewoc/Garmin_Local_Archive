#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
context/context_silo_repair.py

Coordinate-Repair — headless-callable core for the "bad_coordinates"
findings from context_silo_check.check_context_archive().

Not a Leaf-Node — context_silo_check.py is (detection only); this module
performs the actual repair and delegates to context_api.fetch()/
context_writer.write(), the same pair context_collector.run() itself
uses — same detection/repair split garmin_silo_check.py/
garmin_silo_repair.py already establish for the Garmin archive.

Real re-fetch, not a metadata patch (corrected design, 2026-09-20 —
see PROTOKOLL_experiment.md for the reasoning): a day only ever reaches
bad_coordinates if it is outside context_silo_check.py's tolerance
radius — small, harmless drift is already absorbed by that radius and
never becomes a finding. Every remaining finding is therefore a
genuinely wrong location, and context_api.fetch() was called with that
same wrong coordinate at write time — the measured values (temperature,
pollen, etc.), not just the latitude/longitude label, are wrong for the
day. Overwriting only the coordinate field (the original, since-replaced
version of this module) would have left incorrect data under a
now-"corrected" label. The only correct repair is a real API call with
the corrected coordinate, exactly like a normal Sync Context fetch,
scoped to one (day, source) at a time.

"Missing days" (the other class of finding from context_silo_check.py)
have no equivalent repair function here on purpose — they self-heal via
a normal Sync Context run (context_collector.run() re-fetches any day
not yet written), so no dedicated repair path is needed for them.

MCP resync marker (v1.7.2.3 Baustein 5 — see PROTOKOLL_experiment.md for
the full design/reasoning trail): a day this module re-fetches may
already be marked "complete" in the MCP SQLite cache (mcp_context_days)
from a previous sync_all() pass — that cache has no content-hash check
for context days (unlike raw fields), so it would not notice this
overwrite on its own. After every successful repair, this module appends
{date, source} to garmin_config.CONTEXT_RESYNC_PENDING_FILE (via
context_writer — the sole write authority for context_data/, unchanged
here) — clients/mcp_update.py::sync_all() reads that marker (via the
read-only maps/mcp_map.py -> gateway_map.py -> metadata_map.py chain,
never a direct import here) and force-resyncs exactly those (date,
source) pairs on its next pass. This module knows nothing about MCP
beyond writing this one marker file — no import of clients/ or maps/.

Public API:
  fix_coordinates(base_dir, fixes) -> dict
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Same self-contained sys.path insert every context/*_plugin.py already
# does before its own "import garmin_config" — not relying on import
# order of the plugin imports below to have done it first.
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

from . import airquality_plugin
from . import brightsky_plugin
from . import context_api
from . import context_writer
from . import pollen_plugin
from . import weather_plugin

log = logging.getLogger(__name__)

_PLUGIN_BY_SOURCE = {
    "weather":    weather_plugin,
    "pollen":     pollen_plugin,
    "brightsky":  brightsky_plugin,
    "airquality": airquality_plugin,
}


def _mark_pending_resync(base: Path, entries: list[tuple[str, str]]) -> None:
    """Writes (date, source) pairs to the pending-resync marker, each
    stamped with a fresh "marked_at" — read-modify-write, via
    context_writer.write_file() (sole write authority for
    context_data/). No-op for an empty entries list (no unnecessary
    write when nothing was actually repaired).

    v1.7.2.3 correction (2026-09-20, found via a real archive round-trip
    — see PROTOKOLL_experiment.md): an existing entry for the same
    (date, source) is REPLACED, not skipped. The original version
    skipped a duplicate key outright — harmless the first time, but a
    second real repair of the same (date, source) (e.g. correcting a
    coordinate, then correcting it again before mcp_update.py's ack had
    ever been cleared by a Sync Context run) silently vanished: the
    pending file already had that key, so nothing was written, and
    mcp_update.py's ack — keyed on (date, source) alone at the time —
    already considered it handled from the first repair. Stamping each
    write with "marked_at" and matching on the full (date, source,
    marked_at) triple downstream (mcp_update._apply_pending_context_resync())
    makes every real repair event distinguishable, while a still-open,
    not-yet-processed entry (same marked_at, seen again on a later MCP
    boot before anything cleared it) is still correctly treated as the
    same occurrence, not reprocessed twice."""
    if not entries:
        return
    path = base / "context_data" / cfg.CONTEXT_RESYNC_PENDING_FILE.name
    pending = []
    if path.exists():
        try:
            pending = json.loads(path.read_text(encoding="utf-8")).get("pending", [])
        except (OSError, json.JSONDecodeError):
            pending = []
    by_key = {(e.get("date"), e.get("source")): e for e in pending}
    # Microsecond precision, not just seconds — two repairs of the same
    # (date, source) issued in quick succession (e.g. a batch "apply" over
    # several checked findings) must still get distinguishable marked_at
    # values; second-level precision risked two repairs landing in the same
    # second and colliding.
    now = datetime.now(timezone.utc).isoformat()
    for date_str, source in entries:
        by_key[(date_str, source)] = {"date": date_str, "source": source, "marked_at": now}
    context_writer.write_file(path, {"pending": list(by_key.values())})


def _set_output_dirs(base: Path) -> None:
    """Points every plugin's OUTPUT_DIR/RAW_OUTPUT_DIR at base_dir —
    same override context_collector.run() applies before fetching (the
    plugin modules' own defaults come from garmin_config and are only
    correct for the default archive location)."""
    weather_plugin.OUTPUT_DIR         = base / "context_data" / "weather"    / "summary"
    pollen_plugin.OUTPUT_DIR          = base / "context_data" / "pollen"     / "summary"
    pollen_plugin.RAW_OUTPUT_DIR      = base / "context_data" / "pollen"     / "raw"
    brightsky_plugin.OUTPUT_DIR       = base / "context_data" / "brightsky"  / "summary"
    brightsky_plugin.RAW_OUTPUT_DIR   = base / "context_data" / "brightsky"  / "raw"
    airquality_plugin.OUTPUT_DIR      = base / "context_data" / "airquality" / "summary"
    airquality_plugin.RAW_OUTPUT_DIR  = base / "context_data" / "airquality" / "raw"


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def fix_coordinates(base_dir: str, fixes: list[dict]) -> dict:
    """
    Re-fetches a set of (date, source) findings with a corrected
    coordinate, overwriting the existing file entirely (metadata AND
    measured values) — see module docstring for why a metadata-only
    patch is not correct here.

    Parameters
    ----------
    base_dir : str
    fixes : list[dict] — each {"date": str, "source": str,
            "lat": float, "lon": float}. lat/lon are the corrected
            coordinate to fetch WITH — the caller
            (dialog_context_check.py) has already decided whether that
            is a finding's own "expected" value or a user-supplied
            Maps-link override.

    Returns
    -------
    dict with keys:
      ok      int  — days successfully re-fetched and written
      failed  int  — unknown source, or the API call returned no data
      items   list — one dict per processed finding:
        date, source, status ("repaired" | "error"), reason (on error)

    Makes real API calls (one per finding) — same network/rate-limit
    conditions as a normal Sync Context run. Caller must run this in a
    background thread, never on the Main Thread.

    Side effect: every successfully repaired (date, source) pair is also
    appended to garmin_config.CONTEXT_RESYNC_PENDING_FILE — see module
    docstring.
    """
    base = Path(base_dir)
    _set_output_dirs(base)

    ok = 0
    failed = 0
    items = []
    repaired: list[tuple[str, str]] = []

    for fix in fixes:
        date_str = fix["date"]
        source   = fix["source"]
        lat, lon = fix["lat"], fix["lon"]

        plugin = _PLUGIN_BY_SOURCE.get(source)
        if plugin is None:
            items.append({"date": date_str, "source": source, "status": "error",
                          "reason": f"unknown source '{source}'"})
            failed += 1
            continue

        try:
            data = context_api.fetch(plugin, date_str, date_str, lat, lon,
                                      skip_dates=set())
            write_result = context_writer.write(plugin, data, lat, lon)
            if write_result["written"] == 0:
                items.append({"date": date_str, "source": source, "status": "error",
                              "reason": "fetch returned no data"})
                failed += 1
            else:
                items.append({"date": date_str, "source": source, "status": "repaired"})
                repaired.append((date_str, source))
                ok += 1
        except Exception as e:
            items.append({"date": date_str, "source": source, "status": "error",
                          "reason": str(e)})
            failed += 1

    _mark_pending_resync(base, repaired)

    log.info(f"  context-coordinate-repair done: {ok} fixed, {failed} errors")
    return {"ok": ok, "failed": failed, "items": items}
