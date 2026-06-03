#!/usr/bin/env python3
"""
garmin_import_mirror.py

Mirror Import — Sole Owner of the mirror import operation.

Imports data from a local mirror folder (created by garmin_mirror.py) into
the local archive. Supports multi-device workflows: primary device mirrors,
secondary device imports selectively.

Reads mirror_meta.json for version checks, performs a quality-log-based
delta analysis, and imports only raw days that are missing or have better
quality than the local archive. Context files are imported if they are
missing on the target device (source wins).

Pipeline entry point is summarize() — normalize() is skipped because raw
files in the mirror are already normalized (source="api" or "bulk" from
the originating device). Summary is always regenerated locally from raw,
which eliminates schema version conflicts structurally.

Conflict resolution:
  raw/     — quality rank comparison (high > medium > low > failed).
              Existing _upsert_quality() downgrade protection applies.
  context/ — source wins: missing files are copied, existing files are
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

# Quality rank for downgrade protection — mirrors garmin_collector._QUALITY_RANK
_QUALITY_RANK = {"high": 3, "medium": 2, "low": 1, "failed": 0}

# Context subdirectories to scan (relative to context_data/)
_CONTEXT_SUBDIRS = ["weather/raw", "pollen/raw", "brightsky/raw", "airquality/raw"]


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_import_mirror(
    mirror_dir: Path,
    base_dir: Path,
    dry_run: bool = False,
) -> dict:
    """
    Import data from mirror_dir into the local archive at base_dir.

    Parameters
    ----------
    mirror_dir : Path — mirror folder (must contain mirror_meta.json)
    base_dir   : Path — local archive root (BASE_DIR)
    dry_run    : bool — if True, analyse only, no writes

    Returns
    -------
    dict — see module docstring for key descriptions
    """
    mirror_dir = Path(mirror_dir)
    base_dir   = Path(base_dir)

    # ── 1. Read and validate mirror_meta.json ─────────────────────────────────
    meta_result = _read_meta(mirror_dir)
    if not meta_result["ok"]:
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": "", "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

    version_warning = meta_result["version_warning"]

    # ── 2. Load quality logs ───────────────────────────────────────────────────
    import garmin_quality as quality

    try:
        quality_src = _load_mirror_quality(mirror_dir)
    except Exception as e:
        log.error(f"  import_mirror: cannot read mirror quality_log: {e}")
        if dry_run:
            return {"raw_to_copy": 0, "context_to_copy": 0,
                    "version_warning": version_warning, "ok": False}
        return {"raw_copied": 0, "raw_skipped": 0, "context_copied": 0,
                "errors": 1, "ok": False}

    with quality.QUALITY_LOCK:
        quality_dst = quality._load_quality_log()

        # ── 3. Delta analysis — raw ────────────────────────────────────────────
        raw_order, raw_skip = _analyse_raw_delta(quality_src, quality_dst)

        # ── 4. Delta analysis — context ───────────────────────────────────────
        ctx_order = _analyse_context_delta(mirror_dir, base_dir)

        if dry_run:
            return {
                "raw_to_copy":     len(raw_order),
                "context_to_copy": len(ctx_order),
                "version_warning": version_warning,
                "ok":              True,
            }

        # ── 5. Import raw days ─────────────────────────────────────────────────
        raw_copied, raw_skipped, errors = _import_raw(
            mirror_dir, base_dir, raw_order, raw_skip,
            quality_dst, quality,
        )

        # ── 6. Import context files ────────────────────────────────────────────
        ctx_copied, ctx_errors = _import_context(mirror_dir, base_dir, ctx_order)
        errors += ctx_errors

        # ── 7. Final quality log save ──────────────────────────────────────────
        quality._save_quality_log(quality_dst)

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
#  Internal — meta
# ══════════════════════════════════════════════════════════════════════════════

def _read_meta(mirror_dir: Path) -> dict:
    """
    Reads and validates mirror_meta.json.
    Returns {"ok": bool, "meta": dict, "version_warning": str}.
    """
    meta_path = mirror_dir / "mirror_meta.json"
    if not meta_path.exists():
        log.error(f"  import_mirror: mirror_meta.json not found in {mirror_dir}")
        return {"ok": False, "meta": {}, "version_warning": ""}

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error(f"  import_mirror: cannot read mirror_meta.json — {e}")
        return {"ok": False, "meta": {}, "version_warning": ""}

    # Version check — warning only, never blocking
    version_warning = ""
    try:
        from version import APP_VERSION
        from garmin_normalizer import CURRENT_SCHEMA_VERSION

        src_ver    = meta.get("gla_version", "unknown")
        src_schema = meta.get("schema_version", "unknown")

        if src_ver != APP_VERSION:
            version_warning = (
                f"Mirror was created with GLA v{src_ver}, "
                f"local version is v{APP_VERSION}. Import will proceed."
            )
            log.warning(f"  import_mirror: {version_warning}")

        if src_schema != CURRENT_SCHEMA_VERSION:
            log.info(
                f"  import_mirror: schema version mismatch "
                f"(mirror={src_schema}, local={CURRENT_SCHEMA_VERSION}) "
                f"— summary will be regenerated, no action needed"
            )
    except Exception as e:
        log.warning(f"  import_mirror: version check failed — {e}")

    log.info(
        f"  import_mirror: meta OK — "
        f"mirrored_at={meta.get('mirrored_at', '?')}, "
        f"gla_version={meta.get('gla_version', '?')}"
    )
    return {"ok": True, "meta": meta, "version_warning": version_warning}


def _load_mirror_quality(mirror_dir: Path) -> dict:
    """
    Reads the quality_log.json from the mirror folder.
    Returns the parsed dict. Raises on failure.
    """
    import garmin_config as cfg
    # Mirror replicates BASE_DIR structure — quality_log lives at:
    # garmin_data/log/quality_log.json
    rel_path = Path("garmin_data") / "log" / "quality_log.json"
    qlog_path = mirror_dir / rel_path

    if not qlog_path.exists():
        raise FileNotFoundError(f"quality_log.json not found in mirror: {qlog_path}")

    try:
        return json.loads(qlog_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Cannot parse mirror quality_log.json: {e}") from e


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
            # Date missing locally — import
            to_copy.append(entry)
        else:
            dst_label = dst_entry.get("quality", "failed")
            dst_rank  = _QUALITY_RANK.get(dst_label, 0)
            if src_rank > dst_rank:
                # Source has better quality — import
                to_copy.append(entry)
            else:
                skipped += 1

    log.info(
        f"  import_mirror: raw delta — "
        f"{len(to_copy)} to import, {skipped} already equal/better"
    )
    return to_copy, skipped


def _analyse_context_delta(mirror_dir: Path, base_dir: Path) -> list[tuple[Path, Path]]:
    """
    Scans context subdirectories in the mirror.
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

    log.info(f"  import_mirror: context delta — {len(order)} file(s) to import")
    return order


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — import
# ══════════════════════════════════════════════════════════════════════════════

def _import_raw(
    mirror_dir: Path,
    base_dir: Path,
    raw_order: list,
    raw_skip_count: int,
    quality_dst: dict,
    quality,
) -> tuple[int, int, int]:
    """
    Imports raw days listed in raw_order from mirror into local archive.
    Returns (copied, skipped, errors).
    Skips normalize() — raw in mirror is already normalized.
    """
    import garmin_normalizer as normalizer
    import garmin_writer     as writer

    from datetime import date as _date

    # Mirror raw dir structure: garmin_data/raw/YYYY-MM-DD/garmin_raw_YYYY-MM-DD.json
    mirror_raw_dir = mirror_dir / "garmin_data" / "raw"

    copied = 0
    errors = 0

    for entry in raw_order:
        date_str = entry.get("date")
        if not date_str:
            errors += 1
            continue

        # Locate raw file in mirror
        raw_file = mirror_raw_dir / date_str / f"garmin_raw_{date_str}.json"
        if not raw_file.exists():
            log.warning(f"  import_mirror: raw file not found for {date_str} — skipping")
            errors += 1
            continue

        try:
            raw_data = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.error(f"  import_mirror: cannot read raw {date_str}: {e}")
            errors += 1
            continue

        try:
            # normalize() skipped — raw is already normalized
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

            quality._upsert_quality(
                quality_dst, day, label, reason,
                written=written,
                source=entry.get("source", "api"),
                fields=fields,
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


def _import_context(
    mirror_dir: Path,
    base_dir: Path,
    ctx_order: list[tuple[Path, Path]],
) -> tuple[int, int]:
    """
    Copies context files from mirror to local archive via context_writer.write_file().
    Source wins — existing files are overwritten.
    Returns (copied, errors).
    """
    from context import context_writer

    copied = 0
    errors = 0

    for src_path, dst_path in ctx_order:
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
            success = context_writer.write_file(dst_path, data)
            if success:
                copied += 1
                log.debug(f"  import_mirror: context {dst_path.name}")
            else:
                errors += 1
        except Exception as e:
            log.error(f"  import_mirror: context error {src_path.name}: {e}")
            errors += 1

    log.info(f"  import_mirror: context import done — {copied} written, {errors} errors")
    return copied, errors
