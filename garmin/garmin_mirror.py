#!/usr/bin/env python3
"""
garmin_mirror.py

Mirror — Sole Owner of the mirror operation.

Mirrors BASE_DIR to a user-configured target directory (e.g. NAS, USB,
OneDrive folder). Called exclusively by garmin_app_base.py.

Comparison criterion : filename + filesize (mtime excluded — unreliable on Windows)
Direction            : local BASE_DIR is master, target follows exactly
Excludes             : __pycache__, garmin_token (token must never leave local machine)

Logic adapted from backup_to_onedrive_V2.py (run_backup()).
Uses project logger — no own logging setup.
All paths from caller (garmin_app_base) — no garmin_config import needed.
"""

import random
import shutil
import zlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Directories excluded from mirroring (by name, any depth)
EXCLUDE_DIRS = {"__pycache__", "garmin_token"}


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_mirror(source_dir: Path, mirror_dir: Path) -> dict:
    """
    Mirrors source_dir → mirror_dir.

    Parameters
    ----------
    source_dir : Path — local BASE_DIR (master)
    mirror_dir : Path — target directory (follows master)

    Returns
    -------
    dict with keys:
      copied   int  — files copied or overwritten
      deleted  int  — files deleted from target (no longer in source)
      skipped  int  — files identical (name + size)
      errors   int  — copy/delete errors
      ok       bool — True if errors == 0
    """
    if not source_dir.exists() or not source_dir.is_dir():
        log.error(f"  mirror: source not found or not a directory: {source_dir}")
        return {"copied": 0, "deleted": 0, "skipped": 0, "errors": 1, "ok": False}

    if not mirror_dir.exists():
        try:
            mirror_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error(f"  mirror: could not create target directory: {e}")
            return {"copied": 0, "deleted": 0, "skipped": 0, "errors": 1, "ok": False}

    log.info(f"  mirror: {source_dir} → {mirror_dir}")

    source_files = _collect_files(source_dir)
    mirror_files = _collect_files(mirror_dir)

    to_copy   = []
    to_delete = []
    skipped   = 0

    # Phase 1 — what needs to be copied or overwritten?
    for rel, src_size in source_files.items():
        if rel in mirror_files and src_size == mirror_files[rel]:
            skipped += 1
        else:
            to_copy.append(rel)

    # Phase 2 — what exists only in mirror and must be deleted?
    for rel in mirror_files:
        if rel not in source_files:
            to_delete.append(rel)

    copied  = 0
    deleted = 0
    errors  = 0

    # Copy / overwrite
    for rel in to_copy:
        src = source_dir / rel
        dst = mirror_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log.debug(f"  mirror: copied {rel}")
            copied += 1
        except Exception as e:
            log.error(f"  mirror: copy failed for {rel}: {e}")
            errors += 1

    # Delete mirror-only files
    for rel in to_delete:
        dst = mirror_dir / rel
        try:
            dst.unlink(missing_ok=True)
            log.debug(f"  mirror: deleted {rel}")
            deleted += 1
        except Exception as e:
            log.error(f"  mirror: delete failed for {rel}: {e}")
            errors += 1

    # Remove empty directories from mirror (bottom-up)
    _remove_empty_dirs(mirror_dir)

    # Spot-check — CRC32 comparison of up to 10 random files (v1.5.5)
    spot_check = _run_spot_check(source_dir, mirror_dir, source_files)

    log.info(
        f"  mirror done: {copied} copied, {deleted} deleted, "
        f"{skipped} skipped, {errors} errors — "
        f"spot-check: {spot_check['sampled']} sampled, "
        f"{spot_check['mismatches']} mismatches"
    )
    return {
        "copied":     copied,
        "deleted":    deleted,
        "skipped":    skipped,
        "errors":     errors,
        "ok":         errors == 0,
        "spot_check": spot_check,
    }


def is_reachable(mirror_dir: str | Path) -> bool:
    """
    Returns True if mirror_dir is set and the path exists and is a directory.
    Used by garmin_app_base to determine Data Mirror button state at startup.
    """
    if not mirror_dir:
        return False
    try:
        p = Path(mirror_dir)
        return p.exists() and p.is_dir()
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _collect_files(root: Path) -> dict[Path, int]:
    """
    Returns {relative_path → file_size_bytes} for all files under root.
    Skips excluded directories.
    """
    result = {}
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        try:
            result[rel] = entry.stat().st_size
        except OSError as e:
            log.warning(f"  mirror: could not stat {entry}: {e}")
    return result


def _remove_empty_dirs(root: Path) -> None:
    """Removes empty subdirectories under root, bottom-up. Silent on error."""
    for folder in sorted(root.rglob("*"), reverse=True):
        if not folder.is_dir() or folder == root:
            continue
        if folder.name in EXCLUDE_DIRS:
            continue
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass


def _run_spot_check(
    source_dir: Path,
    mirror_dir: Path,
    source_files: dict,
) -> dict:
    """
    CRC32 spot-check: compares up to 10 randomly selected files
    between source and mirror. Called after run_mirror() copy phase.

    Returns dict:
      sampled    int — number of files checked
      mismatches int — files where CRC32 differed
    """
    keys = list(source_files.keys())
    sample = random.sample(keys, min(10, len(keys))) if keys else []
    mismatches = 0

    for rel in sample:
        src = source_dir / rel
        dst = mirror_dir / rel
        try:
            src_crc = zlib.crc32(src.read_bytes()) & 0xFFFFFFFF
            dst_crc = zlib.crc32(dst.read_bytes()) & 0xFFFFFFFF
            if src_crc != dst_crc:
                mismatches += 1
                log.warning(f"  mirror spot-check: CRC32 mismatch — {rel}")
        except Exception as e:
            log.warning(f"  mirror spot-check: could not read {rel}: {e}")
            mismatches += 1

    return {"sampled": len(sample), "mismatches": mismatches}