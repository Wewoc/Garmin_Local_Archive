#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_silo_repair.py

Silo-Repair — headless-callable core for the four repair paths that
garmin_silo_check.check_silos() detects.

Extracted from app/panel_archive.py::_on_silo_repair() (v1.6.5.7). The
repair logic previously lived as a Qt-bound closure with no entry point
callable without a live PanelArchive/QApplication instance — see
KONZEPT_fehlersichtbarkeit_v2.md, Reihenfolge-Schritt 5 ("Silo-Repair als
Blocker") and BESTANDSAUFNAHME_gui_aktionen.md, Auffälligkeit A ("Silo-
Repair hat keinen Kern"). This module is that extraction.
panel_archive.py now only formats the structured result for the GUI log
and dispatches UI state — no pipeline logic remains in the panel.

This supersedes the v1.6.0.4.7 decision documented in CHANGELOG ("Repair
stays in panel_archive and delegates to existing owners") — a deliberate
architecture change, not an oversight; that decision predates the T3.1
silent-failure investigation's headless-callable-core requirement.

Not a Leaf-Node — garmin_silo_check.py is (detection only); this module
performs the actual repairs and therefore imports the sole-write-authority
modules it delegates to. It never writes files directly itself — no new
Sole-Write-Authority assignment, same principle as garmin_import_mirror.py.

Delegation, unchanged in substance from the pre-extraction logic:
  #1 → garmin_quality._backfill_quality_log() under QUALITY_LOCK
  #3 → inline normalize()/summarize()/assess_quality() + write_day() +
       record_attempt() — replaces the former subprocess call to
       export/regenerate_raw.py (v1.6.5.7, sys.executable fix)
  #5 → Path.unlink() (orphan summary)
  #7 → inline summarize() + write_day()

Public API:
  repair_silos(fresh: dict) -> dict
"""

import json
import logging

import garmin_config as cfg
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_writer as writer

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def repair_silos(fresh: dict) -> dict:
    """
    Repairs the four silo-drift categories reported by
    garmin_silo_check.check_silos(). Caller must re-scan immediately
    before calling this — never act on stale findings (§9a).

    Parameters
    ----------
    fresh : dict — the return value of check_silos(), consumed as-is.
        Required keys: raw_without_quality, source_without_raw,
        summary_without_raw, raw_without_summary (each a list of
        date objects).

    Returns
    -------
    dict with keys:
      ok      int   — repairs completed (for #1, counts backfilled entries)
      failed  int   — repairs that raised or could not proceed
      items   list  — one dict per processed date/action:
        category : "1" | "3" | "5" | "7"
        date     : str (ISO) | None  — None only for #1 (log-wide, not per-day)
        status   : "repaired" | "skipped" | "gone" | "no_source" | "backfilled" | "error"
        ... category/status-specific extra keys (existing, new, label,
            count, reason)
    """
    ok = 0
    failed = 0
    items = []

    # ── #3: source without raw → regenerate in-process from source/ ───────────
    # In-process (no subprocess/sys.executable) — identical behavior in
    # T1/T2/T3. sys.executable is the EXE itself in frozen builds (T2) and
    # T3 has no guaranteed python.exe at all (v1.6.5.7). Mirrors
    # export/regenerate_raw.py's own pipeline steps, same style as #7.
    if fresh["source_without_raw"]:
        with quality.QUALITY_LOCK:
            qdata = quality._load_quality_log()

            for d in fresh["source_without_raw"]:
                date_str = d.isoformat()
                try:
                    src_file = cfg.SOURCE_DIR / f"garmin_source_{date_str}.json"
                    if not src_file.exists():
                        items.append({"category": "3", "date": date_str, "status": "no_source"})
                        failed += 1
                        continue
                    raw_source = json.loads(src_file.read_text(encoding="utf-8"))
                    normalized = normalizer.normalize(raw_source, source="api")
                    summary    = normalizer.summarize(normalized)
                    new_label  = quality.assess_quality(normalized)
                    fields     = quality.assess_quality_fields(normalized)

                    existing_entry = next(
                        (e for e in qdata.get("days", []) if e.get("date") == date_str),
                        None
                    )
                    existing_label = existing_entry.get("quality") if existing_entry else None
                    if quality.is_downgrade(new_label, existing_label):
                        items.append({"category": "3", "date": date_str, "status": "skipped",
                                      "existing": existing_label, "new": new_label})
                        continue

                    writer.write_day(normalized, summary, date_str)
                    # Single continuous QUALITY_LOCK hold for the whole
                    # load-modify-save cycle (v1.6.5.7 precondition finding).
                    # Matches the pattern already used everywhere else in the
                    # pipeline (main(), run_import(), _run_source_backfill(),
                    # _run_steps_backfill()) — previously the lock was released
                    # right after the initial load and only re-acquired per
                    # record_attempt() call; a concurrent quality_log writer
                    # during that window could have had its changes silently
                    # overwritten by this loop's stale in-memory qdata.
                    quality.record_attempt(
                        qdata, d, new_label,
                        f"Quality: {new_label} — silo repair replay",
                        written=True, source="api", fields=fields,
                    )
                    items.append({"category": "3", "date": date_str, "status": "repaired",
                                  "label": new_label})
                    ok += 1
                except Exception as e:
                    items.append({"category": "3", "date": date_str, "status": "error",
                                  "reason": str(e)})
                    failed += 1

    # ── #5: summary without raw → unlink orphan ────────────────────────────────
    for d in fresh["summary_without_raw"]:
        date_str = d.isoformat()
        try:
            orphan = cfg.SUMMARY_DIR / f"garmin_{date_str}.json"
            if orphan.exists():
                orphan.unlink()
                items.append({"category": "5", "date": date_str, "status": "repaired"})
                ok += 1
            else:
                items.append({"category": "5", "date": date_str, "status": "gone"})
        except Exception as e:
            items.append({"category": "5", "date": date_str, "status": "error",
                          "reason": str(e)})
            failed += 1

    # ── #7: raw without summary → inline summarize + write_day ─────────────────
    for d in fresh["raw_without_summary"]:
        date_str = d.isoformat()
        try:
            raw_file = cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
            if not raw_file.exists():
                items.append({"category": "7", "date": date_str, "status": "gone"})
                continue
            raw = json.loads(raw_file.read_text(encoding="utf-8"))
            summary = normalizer.summarize(raw)
            writer.write_day(raw, summary, date_str)
            items.append({"category": "7", "date": date_str, "status": "repaired"})
            ok += 1
        except Exception as e:
            items.append({"category": "7", "date": date_str, "status": "error",
                          "reason": str(e)})
            failed += 1

    # ── #1: raw without quality_log → _backfill_quality_log ────────────────────
    if fresh["raw_without_quality"]:
        try:
            with quality.QUALITY_LOCK:
                qdata = quality._load_quality_log()
                added = quality._backfill_quality_log(qdata)
                if added:
                    quality._save_quality_log(qdata)
            items.append({"category": "1", "date": None, "status": "backfilled",
                          "count": added})
            ok += added
        except Exception as e:
            items.append({"category": "1", "date": None, "status": "error",
                          "reason": str(e)})
            failed += 1

    log.info(f"  silo-repair done: {ok} fixed, {failed} errors")
    return {"ok": ok, "failed": failed, "items": items}
