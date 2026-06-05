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

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Directories excluded from mirroring (by name, any depth)
EXCLUDE_DIRS = {"__pycache__", "garmin_token"}


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_mirror(source_dir: Path, container_path: Path, password: str) -> dict:
    """
    Creates an encrypted mirror container from source_dir.

    Parameters
    ----------
    source_dir     : Path — local BASE_DIR (master)
    container_path : Path — target .gla file path
    password       : str  — container password

    Returns
    -------
    dict with keys:
      files_packed  int  — files added to container
      errors        int  — files that could not be read
      ok            bool — True if errors == 0
    """
    if not source_dir.exists() or not source_dir.is_dir():
        log.error(f"  mirror: source not found or not a directory: {source_dir}")
        return {"files_packed": 0, "errors": 1, "ok": False}

    log.info(f"  mirror: {source_dir} → {container_path}")

    import garmin_container as _container
    result = _container.lock(source_dir, container_path, password)

    log.info(
        f"  mirror done: {result.get('files_packed', 0)} files packed, "
        f"{result.get('errors', 0)} errors"
    )
    return result


def is_reachable(container_path: str | Path) -> bool:
    """
    Returns True if container_path is set and the parent directory exists.
    Used by garmin_app_base to determine Data Mirror button state at startup.
    The container file itself may not exist yet (first mirror).
    """
    if not container_path:
        return False
    try:
        p = Path(container_path)
        return p.parent.exists() and p.parent.is_dir()
    except Exception:
        return False




# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

# EXCLUDE_DIRS retained for reference — actual exclusion handled by garmin_container
EXCLUDE_DIRS = {"__pycache__", "garmin_token"}
