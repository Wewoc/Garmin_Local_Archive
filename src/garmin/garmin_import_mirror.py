#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_import_mirror.py

Mirror Import — Sole Owner of the mirror import operation.

Imports data from a GLA container file (created by garmin_mirror.py) into
the local archive. Supports multi-device workflows: primary device mirrors,
secondary device imports selectively.

Container source (v1.5.6.1+):
  unlock_meta()  — verifies HMAC, decrypts quality_log section only
  list_files()   — reads file list from header without decryption (no password)
  fulfill_order() — decrypts only requested sections

Folder fallback (v1.5.6 compatibility):
  detect_source() returns "folder" for directories containing mirror_meta.json.
  Folder path is supported for one version, then deprecated.

Pipeline entry point is summarize() — normalize() is skipped because raw
files in the mirror are already normalized (source="api" or "bulk" from
the originating device).

Summary fast-path: if schema_version matches, summary is taken directly
from the container. If schema_version differs or summary is absent,
summarize() is called fresh on the target device.

Conflict resolution:
  raw/     — quality rank comparison (high > medium > low > failed).
              Existing _upsert_quality() downgrade protection applies.
  context/ — source wins: missing files are imported, existing files are
              overwritten. Context data is an API snapshot without quality
              hierarchy — source is always authoritative.
  bulk/    — (v1.7.6.2) the bulk store of the other archive: day files (intraday
              series, daily values) are handed to garmin_bulk_writer.import_day_file(),
              which keeps the fuller of the two stands; originals are copied when
              the name is missing locally. A day that exists only as export data
              (quality log: write False, no raw file in the container) gets its
              summary made again (writer.rebuild_summary) and its quality-log entry
              — it is not an error that it has no raw file.

Sole-owner invariant:
  garmin_writer   — sole write authority for raw/ and summary/
  garmin_bulk_writer — sole write authority for the bulk store
  garmin_quality  — sole write authority for quality_log.json
  context_writer  — sole write authority for context_data/
  This module orchestrates — it never writes files directly.

Called by:
  app/panel_archive.py — _on_import_mirror() (background thread)

Returns (run_import_mirror):
  {
      "raw_copied":     int,   # days imported
      "raw_skipped":    int,   # days skipped (downgrade protection or equal)
      "context_copied": int,   # context files imported
      "bulk_copied":    int,   # bulk day files written (container only, v1.7.6.2)
      "bulk_skipped":   int,   # bulk day files already there or fuller locally
      "originals_copied": int, # originals taken over from the container
      "export_days":    int,   # days that exist only as export data, entry made
      "errors":         int,   # errors encountered
      "ok":             bool,  # True if errors == 0
      "error":          str,   # present only on early hard-stop failures
                                # (unrecognised source, unlock_meta failure,
                                # unreadable mirror_meta.json/quality_log) —
                                # names the specific cause. Absent when "ok"
                                # is False due to per-item errors during
                                # processing — those are individually logged,
                                # "errors" is their count, no single cause
                                # applies. (v1.6.5.7 — Netz 3 Kandidat 1)
  }

Dry-run mode returns:
  {
      "raw_to_copy":      int,
      "context_to_copy":  int,
      "bulk_to_copy":     int,   # bulk day files missing locally (container only)
      "originals_to_copy": int,  # originals missing locally (container only)
      "version_warning":  str,   # empty string if versions match
      "ok":               bool,
      "error":            str,   # present only on early hard-stop failures — see above
  }
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Context subdirectories to scan (relative to context_data/) — folder fallback
_CONTEXT_SUBDIRS = ["weather/raw", "pollen/raw", "brightsky/raw", "airquality/raw"]


def detect_source(path) -> str:
    """
    Returns "container", "folder", or "unknown".
    Container: valid .gla file (magic bytes GLA1).
    Folder: directory containing mirror_meta.json (v1.5.6 compatibility).
    """
    try:
        import garmin_container as _container
        if _container.is_container(path):
            return "container"
    except Exception:
        pass
    try:
        p = Path(path)
        if p.is_dir() and (p / "mirror_meta.json").exists():
            return "folder"
    except Exception:
        pass
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_import_mirror(
    mirror_path,
    base_dir: Path,
    password: str = "",
    dry_run: bool = False,
    progress=None,
) -> dict:
    """
    Import data from a GLA container or folder into the local archive at base_dir.

    Parameters
    ----------
    mirror_path : Path — .gla container file or legacy folder
    base_dir    : Path — local archive root (BASE_DIR)
    password    : str  — container password (required for container source)
    dry_run     : bool — if True, analyse only, no writes
    progress    : callable(text) | None — (v1.7.6.2) gets a line for every section that is
                  decrypted and for every tenth of the days, day files and originals imported;
                  None = no lines. A callback that raises never fails the import. The folder
                  fallback gives no lines.

    Returns
    -------
    dict — see module docstring for key descriptions
    """
    mirror_path = Path(mirror_path)
    base_dir    = Path(base_dir)

    source_type = detect_source(mirror_path)
    if source_type == "unknown":
        error_msg = f"Not a recognised mirror source: {mirror_path}"
        log.error(f"  import_mirror: {error_msg}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False, "error": error_msg}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False, "error": error_msg}

    if source_type == "folder":
        log.warning(
            "  import_mirror: folder source is deprecated — "
            "re-mirror from source device to create a .gla container"
        )
        return _run_import_folder(mirror_path, base_dir, dry_run)

    # ── Container path ─────────────────────────────────────────────────────────
    return _run_import_container(mirror_path, base_dir, password, dry_run, progress)


def _run_import_container(
    container_path: Path,
    base_dir: Path,
    password: str,
    dry_run: bool,
    progress=None,
) -> dict:
    import garmin_container as _container
    import garmin_quality as quality

    # ── 1. unlock_meta — verify HMAC + read quality_log ───────────────────────
    meta_result = _container.unlock_meta(container_path, password)
    if not meta_result["ok"]:
        log.error(f"  import_mirror: {meta_result['error']}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False,
                    "error": meta_result["error"]}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False, "error": meta_result["error"]}

    container_meta  = meta_result["container_meta"]
    quality_src     = meta_result["quality_log"]
    version_warning = _build_version_warning(container_meta)

    # ── 2. File lists from header — no decrypt required ───────────────────────
    ctx_files_in_container = _container.list_files(container_path, "context")
    src_files_in_container = _container.list_files(container_path, "source")
    raw_files_in_container = _container.list_files(container_path, "raw")
    bulk_files_in_container = _container.list_files(container_path, "bulk")
    bulk_src_files_in_container = _container.list_files(container_path, "bulk_source")

    # ── 3. Delta analysis ─────────────────────────────────────────────────────
    with quality.QUALITY_LOCK:
        quality_dst = quality._load_quality_log()
        raw_order, raw_skip = _analyse_raw_delta(quality_src, quality_dst)
        # v1.7.6.2 (F-8): a day that exists only as export data has no raw file in the container
        raw_order, export_only = _split_export_only(raw_order, raw_files_in_container)
        day_order, orig_order = _analyse_bulk_delta(bulk_files_in_container, bulk_src_files_in_container)
        try:
            ctx_order = _analyse_context_delta_container(
                ctx_files_in_container, base_dir
            )
            src_order = _analyse_source_delta_container(
                src_files_in_container, base_dir
            )
        except _PathTraversalError as e:
            # Fall 1 (ROADMAP v1.7.4.3): abort the whole import, nothing is
            # written — caught here, before fulfill_order()/any write.
            error_msg = f"rejected container path (escapes base_dir): {e.rel_path}"
            log.error(f"  import_mirror: {error_msg}")
            if dry_run:
                return {"raw_to_copy": 0, "context_to_copy": 0,
                        "version_warning": version_warning, "ok": False,
                        "error": error_msg}
            return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                    "errors": 1, "ok": False, "error": error_msg}

        if dry_run:
            return {
                "raw_to_copy":       len(raw_order),
                "context_to_copy":   len(ctx_order),
                "source_to_copy":    len(src_order),
                "bulk_to_copy":      _count_missing_day_files(day_order),
                "originals_to_copy": len(orig_order),
                "version_warning":   version_warning,
                "ok":                True,
            }

        # ── 4. Build order and fulfill ────────────────────────────────────────
        src_schema = container_meta.get("schema_version")
        try:
            from garmin_normalizer import CURRENT_SCHEMA_VERSION
            schema_match = (src_schema == CURRENT_SCHEMA_VERSION)
        except Exception:
            schema_match = False

        raw_rel_paths = [
            f"garmin_data/raw/garmin_raw_{e['date']}.json"
            for e in raw_order if e.get("date")
        ]
        summary_rel_paths = []
        if schema_match and raw_rel_paths:
            summary_rel_paths = [
                p.replace("garmin_data/raw/garmin_raw_", "garmin_data/summary/garmin_")
                for p in raw_rel_paths
            ]

        order = {}
        if raw_rel_paths:
            order["raw"] = raw_rel_paths
        if summary_rel_paths:
            order["summary"] = summary_rel_paths
        if ctx_order:
            order["context"] = ctx_order
        if src_order:
            order["source"] = src_order
        if day_order:
            order["bulk"] = [rel for rel, _kind, _day in day_order]
        if orig_order:
            order["bulk_source"] = [rel for rel, _hash, _suffix in orig_order]
        order["quality_log"] = ["garmin_data/log/device_table.json"]

        if progress is None:
            fulfilled = _container.fulfill_order(container_path, password, order)
        else:
            fulfilled = _container.fulfill_order(container_path, password, order, progress=progress)

        # ── 4b. Import the bulk store (before raw: write_day() resolves with the daily values)
        bulk_copied, bulk_skipped, originals_copied, errors, agg_written = _import_bulk_from_bytes(
            fulfilled, day_order, orig_order, progress,
        )

        # ── 5. Import raw (+ optional summary fast-path) ──────────────────────
        raw_done = set()
        raw_copied, raw_skipped, raw_errors = _import_raw_from_bytes(
            fulfilled, raw_order, raw_skip,
            quality_dst, quality,
            schema_match=schema_match,
            done_days=raw_done, progress=progress,
        )
        errors += raw_errors

        # ── 5b. Days that exist only as export data (F-8) ─────────────────────
        export_days, export_errors = _import_export_days(
            export_only, [d for d in agg_written if d not in raw_done], quality_dst, quality,
        )
        errors += export_errors
        if bulk_copied or export_days:
            # a mark that is missing for a day of the store (the importer is the writer of the files now)
            import garmin_bulk_writer as _bw
            quality.catch_up_bulk_intraday(quality_dst, _bw.list_days())
            quality.catch_up_bulk_aggregates(quality_dst, _bw.list_aggregate_days())

        # ── 6. Import context ─────────────────────────────────────────────────
        ctx_copied, ctx_errors = _import_context_from_bytes(
            fulfilled, ctx_order, base_dir
        )
        errors += ctx_errors

        # ── 6b. Import source ─────────────────────────────────────────────────
        src_copied, src_errors = _import_source_from_bytes(
            fulfilled, src_order, base_dir
        )
        errors += src_errors

        # ── 7. Save quality log ───────────────────────────────────────────────
        quality._save_quality_log(quality_dst)

        # ── 8. Restore device_table.json if present in container ──────────────
        _restore_device_table(fulfilled, base_dir)

    log.info(
        f"  import_mirror done: {raw_copied} raw copied, "
        f"{raw_skipped} raw skipped, {ctx_copied} context copied, "
        f"{src_copied} source copied, {bulk_copied} bulk day files, "
        f"{originals_copied} originals, {export_days} export-only days, {errors} errors"
    )
    return {
        "raw_copied":       raw_copied,
        "raw_skipped":      raw_skipped,
        "context_copied":   ctx_copied,
        "source_copied":    src_copied,
        "bulk_copied":      bulk_copied,
        "bulk_skipped":     bulk_skipped,
        "originals_copied": originals_copied,
        "export_days":      export_days,
        "errors":           errors,
        "ok":               errors == 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — meta + version
# ══════════════════════════════════════════════════════════════════════════════

def _build_version_warning(container_meta: dict) -> str:
    """Builds a version warning string if gla_version differs. Empty if identical."""
    try:
        from version import APP_VERSION
        src_ver = container_meta.get("gla_version", "unknown")
        if src_ver != APP_VERSION:
            return (
                f"Mirror was created with GLA v{src_ver}, "
                f"local version is v{APP_VERSION}. Import will proceed."
            )
    except Exception:
        pass
    return ""


class _PathTraversalError(Exception):
    """A container-supplied relative path resolves outside base_dir."""
    def __init__(self, rel_path: str):
        self.rel_path = rel_path
        super().__init__(f"container path escapes base_dir: {rel_path}")


def _safe_container_path(base_dir: Path, rel_path: str) -> Path | None:
    """
    Resolves base_dir / rel_path and returns it only if the result stays
    inside base_dir. Returns None (reject) for any path that climbs out,
    e.g. via '../' segments (ROADMAP v1.7.4.3, Fall 1).
    """
    try:
        base_resolved = base_dir.resolve()
        candidate = (base_dir / rel_path).resolve()
        candidate.relative_to(base_resolved)
        return base_dir / rel_path
    except (ValueError, OSError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — delta analysis
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_raw_delta(quality_src: dict, quality_dst: dict) -> tuple[list, int]:
    """
    Compares source and destination quality logs.
    Returns (to_copy: list[dict], skipped: int).
    Each entry in to_copy is a quality_log day dict from source.
    """
    import garmin_quality as quality

    dst_by_date = {
        e["date"]: e
        for e in quality_dst.get("days", [])
        if "date" in e
    }

    to_copy = []
    skipped = 0

    for entry in quality_src.get("days", []):
        date_str = entry.get("date")
        if not date_str:
            continue

        src_label = entry.get("quality", "failed")
        src_rank  = quality.QUALITY_RANK.get(src_label, 0)

        dst_entry = dst_by_date.get(date_str)
        if dst_entry is None:
            to_copy.append(entry)
        else:
            dst_label = dst_entry.get("quality", "failed")
            dst_rank  = quality.QUALITY_RANK.get(dst_label, 0)
            if src_rank > dst_rank:
                to_copy.append(entry)
            else:
                skipped += 1

    log.info(
        f"  import_mirror: raw delta — "
        f"{len(to_copy)} to import, {skipped} already equal/better"
    )
    return to_copy, skipped


def _split_export_only(raw_order: list, raw_files_in_container: list) -> tuple[list, list]:
    """
    Splits the days of the raw delta (v1.7.6.2, F-8) into (to_import_as_raw, export_only).
    export_only: the quality-log entry says write False (nothing written to raw/ — a day that
    comes from the export) and the container holds no raw file for it. Such a day is no error:
    its data are in the bulk section. An entry with write True, or without the key, whose raw
    file is missing from the container stays in the first list (and is counted as an error when
    the import finds no bytes); an entry with write False and a raw file in the container is
    imported as a raw day as before.
    """
    present = set(raw_files_in_container)
    raw_days, export_only = [], []
    for entry in raw_order:
        date_str = entry.get("date")
        raw_rel = f"garmin_data/raw/garmin_raw_{date_str}.json"
        if entry.get("write") is False and raw_rel not in present:
            export_only.append(entry)
        else:
            raw_days.append(entry)
    if export_only:
        log.info(f"  import_mirror: {len(export_only)} day(s) exist only as export data (no raw file)")
    return raw_days, export_only


def _analyse_bulk_delta(bulk_files: list, bulk_source_files: list) -> tuple[list, list]:
    """
    Sorts the files of the container's bulk sections (v1.7.6.2) by what the bulk writer says
    they are (garmin_bulk_writer.describe_container_path — from the name alone).

    Returns (day_files, originals):
      day_files  [(rel_path, kind, date)]        every day file ("intraday"/"aggregates") — the
                                                 writer decides, a fuller stored file stays
      originals  [(rel_path, hash, suffix)]      only those whose name is missing locally
    A name that is none of these is logged and left out (never an error: a newer container may
    hold things this version does not know).
    """
    import garmin_bulk_writer as _bw

    day_files, originals = [], []
    local_originals = _bw.list_originals()
    for rel_path in list(bulk_files) + list(bulk_source_files):
        info = _bw.describe_container_path(rel_path)
        if info is None:
            log.warning(f"  import_mirror: unknown file in the bulk section skipped: {rel_path}")
        elif info[0] == "original":
            if f"{info[1]}{info[2]}" not in local_originals:
                originals.append((rel_path, info[1], info[2]))
        else:
            day_files.append((rel_path, info[0], info[1]))
    log.info(
        f"  import_mirror: bulk delta — {len(day_files)} day file(s) to hand over, "
        f"{len(originals)} original(s) missing locally"
    )
    return day_files, originals


def _count_missing_day_files(day_files: list) -> int:
    """Dry run: how many of the day files have no file of that kind and day locally (by name)."""
    import garmin_bulk_writer as _bw
    local = {"intraday": set(_bw.list_days()), "aggregates": set(_bw.list_aggregate_days())}
    return sum(1 for _rel, kind, day in day_files if day not in local[kind])


def _analyse_context_delta_container(
    ctx_files_in_container: list[str],
    base_dir: Path,
) -> list[str]:
    """
    Container variant: compares container context file list against local disk.
    Source wins — all container context files are imported (overwrite allowed).
    Returns list of relative paths to request from fulfill_order().

    Raises _PathTraversalError if any path resolves outside base_dir — the
    caller aborts the whole import without writing anything (ROADMAP
    v1.7.4.3, Fall 1: a rejected path is a security signal, not an ordinary
    data error — fail closed, not skip-and-continue).
    """
    order = []
    for rel_path in ctx_files_in_container:
        dst = _safe_container_path(base_dir, rel_path)
        if dst is None:
            raise _PathTraversalError(rel_path)
        order.append(rel_path)
        if dst.exists():
            log.debug(f"  import_mirror: context overwrite — {rel_path}")
    log.info(f"  import_mirror: context delta — {len(order)} file(s) to import")
    return order


def _analyse_source_delta_container(
    src_files_in_container: list[str],
    base_dir: Path,
) -> list[str]:
    """
    Compares container source file list against local garmin_data/source/.
    Returns all container source paths for processing by _import_source_from_bytes().
    The actual write decision (overwrite vs. skip vs. skip_warn) is made by
    garmin_source_writer.write_source() via the Conservative guard — existing
    high-resolution source files are never overwritten by degraded responses.
    Returns list of relative paths to request from fulfill_order().

    Raises _PathTraversalError on the same rule as
    _analyse_context_delta_container() (ROADMAP v1.7.4.3, Fall 1).
    write_source() itself only ever uses the filename's date part, so this
    is defense-in-depth here rather than today's actual exploit path — the
    roadmap asks for the same check on every container path regardless.
    """
    order = []
    for rel_path in src_files_in_container:
        if _safe_container_path(base_dir, rel_path) is None:
            raise _PathTraversalError(rel_path)
        order.append(rel_path)
    log.info(f"  import_mirror: source delta — {len(order)} file(s) to process")
    return order


def _import_source_from_bytes(
    fulfilled: dict,
    src_order: list[str],
    base_dir: Path,
) -> tuple[int, int]:
    """
    Writes source files from fulfilled bytes dict to garmin_data/source/.
    Delegates to garmin_source_writer.write_source() — Sole-Write-Authority
    for source/ is consolidated here (Option 1, v1.6.0.4.6).
    The Conservative guard in write_source() protects existing high-resolution
    files from being overwritten by degraded mirror responses.
    Returns (copied, errors).
    """
    import garmin_source_writer as _sw

    copied = 0
    errors = 0

    for rel_path in src_order:
        data_bytes = fulfilled.get(rel_path)
        if data_bytes is None:
            log.warning(f"  import_mirror: source bytes not found: {rel_path}")
            errors += 1
            continue

        # Extract date from filename: garmin_data/source/garmin_source_YYYY-MM-DD.json
        try:
            filename = rel_path.split("/")[-1]               # garmin_source_YYYY-MM-DD.json
            date_str = filename.replace("garmin_source_", "").replace(".json", "")
        except Exception as e:
            log.error(f"  import_mirror: source filename parse error {rel_path}: {e}")
            errors += 1
            continue

        try:
            raw_data = json.loads(data_bytes.decode("utf-8"))
        except Exception as e:
            log.error(f"  import_mirror: source JSON decode error {rel_path}: {e}")
            errors += 1
            continue

        ok = _sw.write_source(raw_data, date_str)
        if ok:
            copied += 1
            log.debug(f"  import_mirror: source {rel_path}")
        else:
            log.error(f"  import_mirror: source write_source failed for {date_str}")
            errors += 1

    if src_order:
        log.info(
            f"  import_mirror: source import done — {copied} written, {errors} errors"
        )
    return copied, errors


def _extract_device(raw: dict) -> tuple[str | None, str]:
    """
    Extracts device_id and device_name from a raw dict.
    Source: training_status → mostRecentTrainingStatus → recordedDevices[0].
    Returns (device_id, device_name) — (None, "") if absent.
    Mirrors garmin_collector device lookup logic — no Keys fallback.
    """
    try:
        ts          = raw.get("training_status") or {}
        most_recent = ts.get("mostRecentTrainingStatus") or {}
        recorded    = most_recent.get("recordedDevices")
        if isinstance(recorded, list) and recorded:
            first = recorded[0]
            if isinstance(first, dict):
                device_id   = str(first["deviceId"])   if first.get("deviceId")   else None
                device_name = str(first["deviceName"]) if first.get("deviceName") else ""
                return device_id, device_name
    except Exception:
        pass
    return None, ""


def _analyse_context_delta(mirror_dir: Path, base_dir: Path) -> list[tuple[Path, Path]]:
    """
    Folder fallback variant: scans context subdirectories in the mirror folder.
    Returns list of (src_path, dst_path) for all context files.
    Source wins: existing destination files are overwritten.
    """
    order = []
    mirror_ctx = mirror_dir / "context_data"

    for subdir in _CONTEXT_SUBDIRS:
        src_dir = mirror_ctx / subdir
        dst_dir = base_dir / "context_data" / subdir
        if not src_dir.exists():
            continue
        for src_file in src_dir.glob("*.json"):
            dst_file = dst_dir / src_file.name
            order.append((src_file, dst_file))

    log.info(f"  import_mirror: context delta (folder) — {len(order)} file(s) to import")
    return order


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — import (container)
# ══════════════════════════════════════════════════════════════════════════════

def _import_raw_from_bytes(
    fulfilled: dict,
    raw_order: list,
    raw_skip_count: int,
    quality_dst: dict,
    quality,
    schema_match: bool,
    *,
    done_days=None,
    progress=None,
) -> tuple[int, int, int]:
    """
    Imports raw days from fulfilled bytes dict into local archive.
    If schema_match: uses summary bytes from container (fast-path).
    Otherwise: calls summarize() fresh on target.
    done_days (v1.7.6.2): a set that gets the date of every day written; progress: a callback
    that gets a line for every tenth of the days.
    Returns (copied, skipped, errors).
    """
    import garmin_normalizer as normalizer
    import garmin_writer     as writer
    from datetime import date as _date

    copied = 0
    errors = 0

    for i, entry in enumerate(raw_order, 1):
        _report_tenth(progress, "raw days", i, len(raw_order))
        date_str = entry.get("date")
        if not date_str:
            errors += 1
            continue

        raw_rel = f"garmin_data/raw/garmin_raw_{date_str}.json"
        raw_bytes = fulfilled.get(raw_rel)
        if raw_bytes is None:
            log.warning(f"  import_mirror: raw bytes not found for {date_str} — skipping")
            errors += 1
            continue

        try:
            raw_data = json.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            log.error(f"  import_mirror: cannot parse raw {date_str}: {e}")
            errors += 1
            continue

        try:
            day = _date.fromisoformat(date_str)
        except ValueError:
            log.warning(f"  import_mirror: invalid date '{date_str}' — skipping")
            errors += 1
            continue

        try:
            # normalize() skipped — raw is already normalized
            if schema_match:
                sum_rel   = f"garmin_data/summary/garmin_{date_str}.json"
                sum_bytes = fulfilled.get(sum_rel)
                if sum_bytes is not None:
                    try:
                        summary = json.loads(sum_bytes.decode("utf-8"))
                        log.debug(f"  import_mirror: summary fast-path {date_str}")
                    except Exception:
                        summary = normalizer.summarize(raw_data)
                else:
                    summary = normalizer.summarize(raw_data)
            else:
                summary = normalizer.summarize(raw_data)

            label   = quality.assess_quality(raw_data)
            fields  = quality.assess_quality_fields(raw_data)
            written = writer.write_day(raw_data, summary, date_str)
            if not written:
                # v1.7.6.1 (F-6): False = nothing written (unreadable aggregates or disk error)
                raise RuntimeError("raw/ and summary/ could not be written (see the log)")

            reason = f"Quality: {label} — mirror import"
            device_id, device_name = _extract_device(raw_data)
            quality._upsert_quality(
                quality_dst, day, label, reason,
                written=written,
                source=entry.get("source", "api"),
                fields=fields,
                device_id=device_id,
                device_name=device_name,
            )

            # GP-2 crash-resilience: persist quality_log after each day so a
            # hard abort cannot leave a raw file without a quality_log entry.
            # skip_backup=True — backup triggered once after the full import
            # (see _save_quality_log() call in the caller), not per day.
            quality._save_quality_log(quality_dst, skip_backup=True)

            copied += 1
            if done_days is not None:
                done_days.add(date_str)
            log.debug(f"  import_mirror: raw {date_str} — {label}")

        except Exception as e:
            log.error(f"  import_mirror: pipeline error for {date_str}: {e}")
            errors += 1

    log.info(
        f"  import_mirror: raw import done — "
        f"{copied} written, {raw_skip_count} skipped, {errors} errors"
    )
    return copied, raw_skip_count, errors


def _report_tenth(progress, what: str, done: int, total: int) -> None:
    """
    Passes a progress line when item `done` of `total` is the first to reach a new tenth
    (10 %, 20 %, … — not the last item, the summary line follows anyway). The line says what
    has been done so far, so an hour-long import shows that it lives.
    """
    if progress is None or total <= 0 or done >= total:
        return
    if 100 * (done - 1) // total // 10 < 100 * done // total // 10:
        import garmin_container as _container
        _container.report_progress(
            progress, f"  Import: {what} … {100 * done // total} % ({done} of {total})")


def _import_bulk_from_bytes(
    fulfilled: dict,
    day_order: list,
    orig_order: list,
    progress=None,
) -> tuple[int, int, int, int, list]:
    """
    Hands the bulk files of the container to the bulk writer (v1.7.6.2): originals first
    (store_original checks the hash against the name), then the day files
    (import_day_file: the writer decides — fuller wins, invalid is refused). Every file is
    taken out of `fulfilled` once handled, so the memory of the originals is freed early.

    Returns (day files written, day files skipped (unchanged or fuller locally), originals
    written, errors, dates of the aggregates files written).
    """
    import garmin_bulk_writer as _bw

    written = skipped = originals = errors = 0
    agg_written = []

    for i, (rel_path, file_hash, suffix) in enumerate(orig_order, 1):
        _report_tenth(progress, "originals", i, len(orig_order))
        data = fulfilled.pop(rel_path, None)
        if data is None:
            log.warning(f"  import_mirror: bulk original bytes not found: {rel_path}")
            errors += 1
            continue
        result = _bw.store_original(file_hash, data, suffix)
        if result == "written":
            originals += 1
        elif result != "present":
            errors += 1

    for i, (rel_path, kind, day) in enumerate(day_order, 1):
        _report_tenth(progress, "bulk day files", i, len(day_order))
        data = fulfilled.pop(rel_path, None)
        if data is None:
            log.warning(f"  import_mirror: bulk bytes not found: {rel_path}")
            errors += 1
            continue
        result = _bw.import_day_file(kind, day, data)
        if result == "written":
            written += 1
            if kind == "aggregates":
                agg_written.append(day)
        elif result in ("unchanged", "kept"):
            skipped += 1
        else:
            errors += 1

    if day_order or orig_order:
        log.info(
            f"  import_mirror: bulk import done — {written} day files written, {skipped} skipped, "
            f"{originals} originals written, {errors} errors"
        )
    return written, skipped, originals, errors, agg_written


def _import_export_days(
    export_only: list,
    summary_days: list,
    quality_dst: dict,
    quality,
) -> tuple[int, int]:
    """
    The part of the import that follows the bulk files (v1.7.6.2, F-8), under the quality lock:

      * summary_days — days whose aggregates file was written in this import and that were not
        imported as raw days: summary/ is made again from the stored data (writer.rebuild_summary,
        which resolves a raw file of the day with the export's values). False -> an error.
      * export_only — the days that exist only as export data: a quality-log entry (the label,
        the fields and the source of the other archive's entry, written=False — there is no raw
        file, so the start-up check must not call it missing), provided the day's aggregates
        file is in the store now. An entry that stays without aggregates is left out (the local
        sync finds the day again); a label this version does not know is an error.

    Returns (entries made, errors). Does not save the quality log.
    """
    import garmin_bulk_writer as _bw
    import garmin_writer     as writer
    from datetime import date as _date

    errors = 0
    for day in summary_days:
        if not writer.rebuild_summary(day):
            log.warning(f"  import_mirror: {day} — the summary could not be made from the export data")
            errors += 1

    local_aggregates = set(_bw.list_aggregate_days()) if export_only else set()
    made = 0
    for entry in export_only:
        date_str = entry.get("date")
        label = entry.get("quality")
        if label not in quality.QUALITY_RANK:
            log.warning(f"  import_mirror: {date_str} — unknown quality label {label!r}, entry not made")
            errors += 1
            continue
        if date_str not in local_aggregates:
            log.info(f"  import_mirror: {date_str} — export day without daily values here, entry not made")
            continue
        try:
            fields = entry.get("fields")
            quality._upsert_quality(
                quality_dst, _date.fromisoformat(date_str), label,
                f"Quality: {label} — mirror import (export data)",
                written=False, source=entry.get("source", "bulk"),
                fields=dict(fields) if isinstance(fields, dict) else None,
                device_id=entry.get("device_id"), device_name=entry.get("device_name"),
                device_source=entry.get("device_source"),
            )
            made += 1
        except Exception as e:
            log.error(f"  import_mirror: {date_str} — quality entry for an export day failed: {e}")
            errors += 1
    return made, errors


def _restore_device_table(fulfilled: dict, base_dir: Path) -> None:
    """
    Writes device_table.json from the quality_log section to disk if present.
    Silent on absence — device_table.json may not exist in older containers.
    """
    dt_key   = "garmin_data/log/device_table.json"
    dt_bytes = fulfilled.get(dt_key)
    if dt_bytes is None:
        log.debug("  import_mirror: device_table.json not in container — skipped")
        return
    try:
        dst = base_dir / "garmin_data" / "log" / "device_table.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(dt_bytes)
        log.info("  import_mirror: device_table.json restored")
    except Exception as e:
        log.warning(f"  import_mirror: device_table.json restore failed: {e}")


def _import_context_from_bytes(
    fulfilled: dict,
    ctx_order: list[str],
    base_dir: Path,
) -> tuple[int, int]:
    """
    Writes context files from fulfilled bytes dict via context_writer.
    Returns (copied, errors).
    """
    from context import context_writer

    copied = 0
    errors = 0

    for rel_path in ctx_order:
        data_bytes = fulfilled.get(rel_path)
        if data_bytes is None:
            log.warning(f"  import_mirror: context bytes not found: {rel_path}")
            errors += 1
            continue
        dst_path = _safe_container_path(base_dir, rel_path)
        if dst_path is None:
            # Should be unreachable — _analyse_context_delta_container()
            # already aborts the whole import on this (Fall 1).
            log.error(f"  import_mirror: rejected path at write time: {rel_path}")
            errors += 1
            continue
        try:
            data     = json.loads(data_bytes.decode("utf-8"))
            success  = context_writer.write_file(dst_path, data)
            if success:
                copied += 1
                log.debug(f"  import_mirror: context {rel_path}")
            else:
                errors += 1
        except Exception as e:
            log.error(f"  import_mirror: context error {rel_path}: {e}")
            errors += 1

    log.info(f"  import_mirror: context import done — {copied} written, {errors} errors")
    return copied, errors


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — folder fallback (v1.5.6 compatibility)
# ══════════════════════════════════════════════════════════════════════════════

def _run_import_folder(
    mirror_dir: Path,
    base_dir: Path,
    dry_run: bool,
) -> dict:
    """
    Legacy folder import (v1.5.6 compatibility).
    Reads mirror_meta.json, quality_log from disk, imports via file reads.
    Deprecated — will be removed in a future version.
    """
    import garmin_quality as quality

    # Read mirror_meta.json
    meta_path = mirror_dir / "mirror_meta.json"
    version_warning = ""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            from version import APP_VERSION
            src_ver = meta.get("gla_version", "unknown")
            if src_ver != APP_VERSION:
                version_warning = (
                    f"Mirror was created with GLA v{src_ver}, "
                    f"local version is v{APP_VERSION}. Import will proceed."
                )
                log.warning(f"  import_mirror (folder): {version_warning}")
        except Exception:
            pass
    except Exception as e:
        error_msg = f"cannot read mirror_meta.json — {e}"
        log.error(f"  import_mirror (folder): {error_msg}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False, "error": error_msg}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False, "error": error_msg}

    # Load quality logs
    rel_path  = Path("garmin_data") / "log" / "quality_log.json"
    qlog_path = mirror_dir / rel_path
    try:
        quality_src = json.loads(qlog_path.read_text(encoding="utf-8"))
    except Exception as e:
        error_msg = f"cannot read mirror quality_log: {e}"
        log.error(f"  import_mirror (folder): {error_msg}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": version_warning, "ok": False,
                    "error": error_msg}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False, "error": error_msg}

    with quality.QUALITY_LOCK:
        quality_dst = quality._load_quality_log()
        raw_order, raw_skip = _analyse_raw_delta(quality_src, quality_dst)
        ctx_order = _analyse_context_delta(mirror_dir, base_dir)

        if dry_run:
            return {
                "raw_to_copy":     len(raw_order),
                "context_to_copy": len(ctx_order),
                "version_warning": version_warning,
                "ok":              True,
            }

        raw_copied, raw_skipped, errors = _import_raw_folder(
            mirror_dir, base_dir, raw_order, raw_skip, quality_dst, quality,
        )
        ctx_copied, ctx_errors = _import_context_folder(
            mirror_dir, base_dir, ctx_order,
        )
        errors += ctx_errors
        quality._save_quality_log(quality_dst)

    log.info(
        f"  import_mirror (folder) done: {raw_copied} raw copied, "
        f"{raw_skipped} raw skipped, {ctx_copied} context copied, {errors} errors"
    )
    return {
        "raw_copied":     raw_copied,
        "raw_skipped":    raw_skipped,
        "context_copied": ctx_copied,
        "errors":         errors,
        "ok":             errors == 0,
    }


def _import_raw_folder(
    mirror_dir: Path,
    base_dir: Path,
    raw_order: list,
    raw_skip_count: int,
    quality_dst: dict,
    quality,
) -> tuple[int, int, int]:
    """Folder fallback raw import — reads files directly from disk."""
    import garmin_normalizer as normalizer
    import garmin_writer     as writer
    from datetime import date as _date

    mirror_raw_dir = mirror_dir / "garmin_data" / "raw"
    copied = 0
    errors = 0

    for entry in raw_order:
        date_str = entry.get("date")
        if not date_str:
            errors += 1
            continue
        raw_file = mirror_raw_dir / date_str / f"garmin_raw_{date_str}.json"
        if not raw_file.exists():
            log.warning(f"  import_mirror (folder): raw not found for {date_str}")
            errors += 1
            continue
        try:
            day = _date.fromisoformat(date_str)
        except ValueError:
            log.warning(f"  import_mirror (folder): invalid date '{date_str}' — skipping")
            errors += 1
            continue

        try:
            raw_data = json.loads(raw_file.read_text(encoding="utf-8"))
            summary  = normalizer.summarize(raw_data)
            label    = quality.assess_quality(raw_data)
            fields   = quality.assess_quality_fields(raw_data)
            written  = writer.write_day(raw_data, summary, date_str)
            if not written:
                # v1.7.6.1 (F-6): False = nothing written (unreadable aggregates or disk error)
                raise RuntimeError("raw/ and summary/ could not be written (see the log)")
            reason   = f"Quality: {label} — mirror import (folder)"
            device_id, device_name = _extract_device(raw_data)
            quality._upsert_quality(
                quality_dst, day, label, reason,
                written=written,
                source=entry.get("source", "api"),
                fields=fields,
                device_id=device_id,
                device_name=device_name,
            )

            # GP-2 crash-resilience: persist quality_log after each day so a
            # hard abort cannot leave a raw file without a quality_log entry.
            # skip_backup=True — backup triggered once after the full import
            # (see _save_quality_log() call in the caller), not per day.
            quality._save_quality_log(quality_dst, skip_backup=True)

            copied += 1
        except Exception as e:
            log.error(f"  import_mirror (folder): pipeline error {date_str}: {e}")
            errors += 1

    return copied, raw_skip_count, errors


def _import_context_folder(
    mirror_dir: Path,
    base_dir: Path,
    ctx_order: list[tuple[Path, Path]],
) -> tuple[int, int]:
    """Folder fallback context import — reads files directly from disk."""
    from context import context_writer
    copied = 0
    errors = 0
    for src_path, dst_path in ctx_order:
        try:
            data    = json.loads(src_path.read_text(encoding="utf-8"))
            success = context_writer.write_file(dst_path, data)
            if success:
                copied += 1
            else:
                errors += 1
        except Exception as e:
            log.error(f"  import_mirror (folder): context error {src_path.name}: {e}")
            errors += 1
    return copied, errors
