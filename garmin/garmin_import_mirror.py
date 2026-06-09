#!/usr/bin/env python3
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

Sole-owner invariant:
  garmin_writer   — sole write authority for raw/ and summary/
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
      "errors":         int,   # errors encountered
      "ok":             bool,  # True if errors == 0
  }

Dry-run mode returns:
  {
      "raw_to_copy":      int,
      "context_to_copy":  int,
      "version_warning":  str,   # empty string if versions match
      "ok":               bool,
  }
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Quality rank for downgrade protection — mirrors quality._maint.QUALITY_RANK (v1.5.7)
_QUALITY_RANK = {"high": 2, "standard": 1, "failed": 0}

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
) -> dict:
    """
    Import data from a GLA container or folder into the local archive at base_dir.

    Parameters
    ----------
    mirror_path : Path — .gla container file or legacy folder
    base_dir    : Path — local archive root (BASE_DIR)
    password    : str  — container password (required for container source)
    dry_run     : bool — if True, analyse only, no writes

    Returns
    -------
    dict — see module docstring for key descriptions
    """
    mirror_path = Path(mirror_path)
    base_dir    = Path(base_dir)

    source_type = detect_source(mirror_path)
    if source_type == "unknown":
        log.error(f"  import_mirror: unrecognised source: {mirror_path}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

    if source_type == "folder":
        log.warning(
            "  import_mirror: folder source is deprecated — "
            "re-mirror from source device to create a .gla container"
        )
        return _run_import_folder(mirror_path, base_dir, dry_run)

    # ── Container path ─────────────────────────────────────────────────────────
    return _run_import_container(mirror_path, base_dir, password, dry_run)


def _run_import_container(
    container_path: Path,
    base_dir: Path,
    password: str,
    dry_run: bool,
) -> dict:
    import garmin_container as _container
    import garmin_quality as quality

    # ── 1. unlock_meta — verify HMAC + read quality_log ───────────────────────
    meta_result = _container.unlock_meta(container_path, password)
    if not meta_result["ok"]:
        log.error(f"  import_mirror: {meta_result['error']}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

    container_meta  = meta_result["container_meta"]
    quality_src     = meta_result["quality_log"]
    version_warning = _build_version_warning(container_meta)

    # ── 2. Context file list — header only, no decrypt ────────────────────────
    ctx_files_in_container = _container.list_files(container_path, "context")

    # ── 3. Delta analysis ─────────────────────────────────────────────────────
    with quality.QUALITY_LOCK:
        quality_dst = quality._load_quality_log()
        raw_order, raw_skip = _analyse_raw_delta(quality_src, quality_dst)
        ctx_order = _analyse_context_delta_container(
            ctx_files_in_container, base_dir
        )

        if dry_run:
            return {
                "raw_to_copy":     len(raw_order),
                "context_to_copy": len(ctx_order),
                "version_warning": version_warning,
                "ok":              True,
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
        order["quality_log"] = ["garmin_data/log/device_table.json"]

        fulfilled = _container.fulfill_order(container_path, password, order)

        # ── 5. Import raw (+ optional summary fast-path) ──────────────────────
        raw_copied, raw_skipped, errors = _import_raw_from_bytes(
            fulfilled, raw_order, raw_skip,
            quality_dst, quality,
            schema_match=schema_match,
        )

        # ── 6. Import context ─────────────────────────────────────────────────
        ctx_copied, ctx_errors = _import_context_from_bytes(
            fulfilled, ctx_order, base_dir
        )
        errors += ctx_errors

        # ── 7. Save quality log ───────────────────────────────────────────────
        quality._save_quality_log(quality_dst)

        # ── 8. Restore device_table.json if present in container ──────────────
        _restore_device_table(fulfilled, base_dir)

    log.info(
        f"  import_mirror done: {raw_copied} raw copied, "
        f"{raw_skipped} raw skipped, {ctx_copied} context copied, "
        f"{errors} errors"
    )
    return {
        "raw_copied":     raw_copied,
        "raw_skipped":    raw_skipped,
        "context_copied": ctx_copied,
        "errors":         errors,
        "ok":             errors == 0,
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


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — delta analysis
# ══════════════════════════════════════════════════════════════════════════════

def _analyse_raw_delta(quality_src: dict, quality_dst: dict) -> tuple[list, int]:
    """
    Compares source and destination quality logs.
    Returns (to_copy: list[dict], skipped: int).
    Each entry in to_copy is a quality_log day dict from source.
    """
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
        src_rank  = _QUALITY_RANK.get(src_label, 0)

        dst_entry = dst_by_date.get(date_str)
        if dst_entry is None:
            to_copy.append(entry)
        else:
            dst_label = dst_entry.get("quality", "failed")
            dst_rank  = _QUALITY_RANK.get(dst_label, 0)
            if src_rank > dst_rank:
                to_copy.append(entry)
            else:
                skipped += 1

    log.info(
        f"  import_mirror: raw delta — "
        f"{len(to_copy)} to import, {skipped} already equal/better"
    )
    return to_copy, skipped


def _analyse_context_delta_container(
    ctx_files_in_container: list[str],
    base_dir: Path,
) -> list[str]:
    """
    Container variant: compares container context file list against local disk.
    Source wins — all container context files are imported (overwrite allowed).
    Returns list of relative paths to request from fulfill_order().
    """
    order = []
    for rel_path in ctx_files_in_container:
        dst = base_dir / rel_path
        order.append(rel_path)
        if dst.exists():
            log.debug(f"  import_mirror: context overwrite — {rel_path}")
    log.info(f"  import_mirror: context delta — {len(order)} file(s) to import")
    return order


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
) -> tuple[int, int, int]:
    """
    Imports raw days from fulfilled bytes dict into local archive.
    If schema_match: uses summary bytes from container (fast-path).
    Otherwise: calls summarize() fresh on target.
    Returns (copied, skipped, errors).
    """
    import garmin_normalizer as normalizer
    import garmin_writer     as writer
    from datetime import date as _date

    copied = 0
    errors = 0

    for entry in raw_order:
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

            reason = f"Quality: {label} — mirror import"
            try:
                day = _date.fromisoformat(date_str)
            except ValueError:
                log.warning(f"  import_mirror: invalid date '{date_str}' — skipping")
                errors += 1
                continue

            device_id, device_name = _extract_device(raw_data)
            quality._upsert_quality(
                quality_dst, day, label, reason,
                written=written,
                source=entry.get("source", "api"),
                fields=fields,
                device_id=device_id,
                device_name=device_name,
            )
            copied += 1
            log.debug(f"  import_mirror: raw {date_str} — {label}")

        except Exception as e:
            log.error(f"  import_mirror: pipeline error for {date_str}: {e}")
            errors += 1

    log.info(
        f"  import_mirror: raw import done — "
        f"{copied} written, {raw_skip_count} skipped, {errors} errors"
    )
    return copied, raw_skip_count, errors


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
        try:
            data     = json.loads(data_bytes.decode("utf-8"))
            dst_path = base_dir / rel_path
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
        log.error(f"  import_mirror (folder): cannot read mirror_meta.json — {e}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

    # Load quality logs
    rel_path  = Path("garmin_data") / "log" / "quality_log.json"
    qlog_path = mirror_dir / rel_path
    try:
        quality_src = json.loads(qlog_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"  import_mirror (folder): cannot read mirror quality_log: {e}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": version_warning, "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

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
            raw_data = json.loads(raw_file.read_text(encoding="utf-8"))
            summary  = normalizer.summarize(raw_data)
            label    = quality.assess_quality(raw_data)
            fields   = quality.assess_quality_fields(raw_data)
            written  = writer.write_day(raw_data, summary, date_str)
            reason   = f"Quality: {label} — mirror import (folder)"
            day      = _date.fromisoformat(date_str)
            device_id, device_name = _extract_device(raw_data)
            quality._upsert_quality(
                quality_dst, day, label, reason,
                written=written,
                source=entry.get("source", "api"),
                fields=fields,
                device_id=device_id,
                device_name=device_name,
            )
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
