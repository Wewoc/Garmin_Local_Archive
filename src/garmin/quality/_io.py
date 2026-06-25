#!/usr/bin/env python3
"""
garmin/quality/_io.py

Load / Save / Checksum sub-module for garmin_quality.
Sole file-IO authority within the quality package.

Internal — import only via garmin_quality (facade).
"""

import hashlib
import json
import logging
import zipfile
from datetime import date, datetime

import garmin_config as cfg
import garmin_utils as utils

log = logging.getLogger(__name__)

# Alias — kept here so _load_quality_log can call it without importing _assess
# (avoids circular: _assess imports _safe_get from here)
_parse_device_date = utils.parse_device_date


# ── Internal helpers ───────────────────────────────────────────────────────────

def _safe_get(d, *keys, default=None):
    """Traverses nested dicts safely. Returns default if any key is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


# ══════════════════════════════════════════════════════════════════════════════
#  Checksum
# ══════════════════════════════════════════════════════════════════════════════

def _compute_checksum(data: dict) -> str:
    """
    Computes SHA-256 hash over stable core fields of each day entry:
    date, write, quality, source — always present after a save, never added by migration.
    Extended in v1.5.5 to include quality + source (previously only date + write).
    Migration bridge: _compute_checksum_legacy() detects pre-v1.5.5 checksums on first load.
    """
    stable = [
        {
            "date":    e.get("date"),
            "quality": e.get("quality"),
            "source":  e.get("source"),
            "write":   e.get("write"),
        }
        for e in sorted(data.get("days", []), key=lambda e: e.get("date", ""))
    ]
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# TODO: remove after v1.6 — migration bridge for pre-v1.5.5 checksums (date + write only)
def _compute_checksum_legacy(data: dict) -> str:
    """
    Replicates the pre-v1.5.5 checksum algorithm (date + write only).
    Used once on load to detect planned algorithm upgrade — never for new saves.
    """
    stable = [
        {
            "date":  e.get("date"),
            "write": e.get("write"),
        }
        for e in sorted(data.get("days", []), key=lambda e: e.get("date", ""))
    ]
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
#  Load
# ══════════════════════════════════════════════════════════════════════════════

def _load_quality_log() -> dict:
    """
    Loads quality_log.json. Returns empty structure if missing or corrupt.
    Applies migrations:
      - From failed_days.json (old name) → quality_log.json
      - From 'failed' list schema → 'days' list schema
      - 'category' field → 'quality' field
      - old 'error' → 'failed', old 'incomplete' → 'low'
      - Adds missing fields: recheck, last_checked

    Integrity check (A6/A7):
      - Verifies stored checksum against recomputed hash after load
      - On mismatch: attempts auto-restore from latest backup ZIP
      - Returns integrity_warnings: list[str] in the result dict
        (empty list = all OK). App-layer reads this key and displays
        a yellow label in the Archive Info Panel via self.after().
    """
    old_file = cfg.LOG_DIR / "failed_days.json"

    # Try quality_log.json first, fall back to failed_days.json migration
    source = None
    if cfg.QUALITY_LOG_FILE.exists():
        source = cfg.QUALITY_LOG_FILE
    elif old_file.exists():
        source = old_file
        log.info("  Migrating failed_days.json → quality_log.json ...")

    if source is None:
        return {"first_day": None, "devices": [], "days": []}

    try:
        with open(source, encoding="utf-8") as f:
            data = json.load(f)

        # Migrate old 'failed' key → 'days'
        if "failed" in data and "days" not in data:
            data["days"] = data.pop("failed")

        if "days" not in data or not isinstance(data["days"], list):
            return {"first_day": None, "devices": [], "days": []}

        # Ensure new root fields exist (migration from older schema)
        if "first_day" not in data:
            data["first_day"] = None
        if "devices" not in data:
            data["devices"] = []

        # Migrate first_day if stored as Unix timestamp instead of YYYY-MM-DD
        if data.get("first_day"):
            fixed = _parse_device_date(data["first_day"])
            if fixed and fixed != data["first_day"]:
                log.info(f"  Migrating first_day: {data['first_day']} -> {fixed}")
                data["first_day"] = fixed

        # Migrate devices.first_used / last_used if stored as Unix timestamps
        for dev in data.get("devices", []):
            for field in ("first_used", "last_used"):
                val = dev.get(field)
                if val and val != "unknown":
                    fixed = _parse_device_date(val)
                    if fixed and fixed != val:
                        dev[field] = fixed

        today_str = date.today().isoformat()
        for entry in data["days"]:
            # v1.5.7: device_id — replaces device_rank (v1.5.7 rev)
            if "device_rank" in entry and "device_id" not in entry:
                entry["device_id"]   = None
                entry["device_name"] = ""
                del entry["device_rank"]
            elif "device_id" not in entry:
                entry["device_id"]   = None
                entry["device_name"] = ""
            # Migrate 'category' → 'quality'
            if "category" in entry and "quality" not in entry:
                old = entry.pop("category")
                entry["quality"] = "failed" if old == "error" else "low"

            # Ensure all new fields exist
            if "recheck" not in entry:
                q = entry.get("quality", "failed")
                entry["recheck"] = q in ("failed", "low")
            if "last_checked" not in entry:
                entry["last_checked"] = entry.get("last_attempt", today_str) or today_str
            if "attempts" not in entry:
                entry["attempts"] = 0
            if "last_attempt" not in entry:
                entry["last_attempt"] = None

            # Migrate: add 'write' field if missing (entries before v1.2.1)
            if "write" not in entry:
                entry["write"] = None  # unknown — written before this field existed

            # Migrate: add 'source' field if missing (entries before v1.2.2)
            if "source" not in entry:
                entry["source"] = "legacy"

            # Migrate: add 'fields' dict if missing (entries before v1.3.0)
            if "fields" not in entry:
                entry["fields"] = {}

            # Reset attempts for low entries (Garmin archived data, not real failures)
            if entry.get("quality") == "low":
                entry["attempts"] = 0

        # Save to new location if migrated from old file
        if source == old_file:
            _save_quality_log(data, skip_backup=True)
            try:
                old_file.unlink()
                log.info("  Migration complete — failed_days.json removed.")
            except Exception:
                pass
        # No re-save needed: _compute_checksum uses only stable core fields
        # (date, quality, write) that are always present at save time.
        # Field migrations (fields, source, recheck) do not affect the checksum.

        # ── Integrity check (A6/A7) — nach allen Migrationen ─────────────────
        integrity_warnings = []
        stored_checksum = data.get("_checksum")
        if stored_checksum and source == cfg.QUALITY_LOG_FILE:
            recomputed = _compute_checksum(data)
            if recomputed != stored_checksum:
                if _compute_checksum_legacy(data) == stored_checksum:
                    log.info(
                        "  quality_log.json checksum algorithm upgraded (v1.5.5) — "
                        "new checksum will be written on next save."
                    )
                else:
                    years_affected = sorted({
                        e["date"][:4] for e in data.get("days", [])
                        if "date" in e
                    })
                    for yr in years_affected:
                        integrity_warnings.append(f"log mismatch {yr}")
                    log.warning(
                        f"  quality_log.json checksum mismatch — affected years: "
                        f"{', '.join(years_affected)}"
                    )
                    # Auto-restore from latest backup (A7)
                    try:
                        import garmin_backup as _backup
                        restored = _backup.restore_quality_log()
                        if restored is not None:
                            _save_defective_log(data)
                            data = restored
                            data["integrity_warnings"] = integrity_warnings
                            log.info("  quality_log.json restored from backup.")
                        else:
                            log.warning(
                                "  Auto-restore failed — no valid backup found. "
                                "App continues with current (possibly corrupt) log."
                            )
                    except ImportError:
                        log.warning(
                            "  garmin_backup not available — skipping auto-restore."
                        )

        data["integrity_warnings"] = integrity_warnings
        return data

    except Exception as e:
        log.warning(f"  Could not read quality log: {e} — starting fresh.")
        return {"first_day": None, "devices": [], "days": [], "integrity_warnings": []}


# ══════════════════════════════════════════════════════════════════════════════
#  Save
# ══════════════════════════════════════════════════════════════════════════════

def save_device_table(quality_data: dict) -> None:
    """
    Builds and writes device_table.json from quality_data.
    Called by garmin_collector after each sync.
    Sole write authority: garmin_quality (this module).

    Matching algorithm: group entries by device_id (str).
    device_id is set per entry by garmin_collector from training_status.
    Entries with device_id=None are excluded from named device rows.
    Device name is taken from the entry's device_name field.
    New devices are detected automatically — no manual config required.

    Sorted: newest date_to first (most recently used device at top).

    Format: list of dicts with keys:
      device_id, name, date_from, date_to, days_high, days_standard, days_total
    Plus a summary row with device_id="__total__".
    """
    days = quality_data.get("days", [])

    # Accumulate per-device stats
    # Entries with device_id=None are grouped under "__unknown__"
    stats = {}  # device_id → {name, dates, days_high, days_standard}
    unknown = {"dates": [], "days_high": 0, "days_standard": 0, "_names": set()}
    for entry in days:
        dev_id = entry.get("device_id")
        if not dev_id:
            # Count under unknown
            d = entry.get("date")
            if d:
                unknown["dates"].append(d)
            q = entry.get("quality", "")
            if q == "high":
                unknown["days_high"] += 1
            elif q == "standard":
                unknown["days_standard"] += 1
            n = (entry.get("device_name") or "").strip()
            if n:
                unknown["_names"].add(n)
            continue
        if dev_id not in stats:
            stats[dev_id] = {
                "name":          entry.get("device_name") or dev_id,
                "dates":         [],
                "days_high":     0,
                "days_standard": 0,
            }
        # Update name if available (most recent wins)
        if entry.get("device_name"):
            stats[dev_id]["name"] = entry["device_name"]
        d = entry.get("date")
        if d:
            stats[dev_id]["dates"].append(d)
        q = entry.get("quality", "")
        if q == "high":
            stats[dev_id]["days_high"] += 1
        elif q == "standard":
            stats[dev_id]["days_standard"] += 1

    # Build table rows
    rows = []
    total_high = total_std = total_all = 0
    for dev_id, s in stats.items():
        dh  = s["days_high"]
        dst = s["days_standard"]
        dt  = dh + dst
        rows.append({
            "device_id":     dev_id,
            "name":          s["name"],
            "date_from":     min(s["dates"]) if s["dates"] else None,
            "date_to":       max(s["dates"]) if s["dates"] else None,
            "days_high":     dh,
            "days_standard": dst,
            "days_total":    dt,
        })
        total_high += dh
        total_std  += dst
        total_all  += dt

    # Sort: newest date_to first
    rows.sort(key=lambda r: r["date_to"] or "", reverse=True)

    # Unknown device row — appended after named devices, before total
    if unknown["dates"]:
        dh  = unknown["days_high"]
        dst = unknown["days_standard"]
        _names = unknown["_names"]
        _display_name = next(iter(_names)) if len(_names) == 1 else "unknown"
        rows.append({
            "device_id":     "__unknown__",
            "name":          _display_name,
            "date_from":     min(unknown["dates"]),
            "date_to":       max(unknown["dates"]),
            "days_high":     dh,
            "days_standard": dst,
            "days_total":    dh + dst,
        })
        total_high += dh
        total_std  += dst
        total_all  += dh + dst

    # Summary row
    rows.append({
        "device_id":     "__total__",
        "name":          "Total",
        "date_from":     None,
        "date_to":       None,
        "days_high":     total_high,
        "days_standard": total_std,
        "days_total":    total_all,
    })

    try:
        cfg.DEVICE_TABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = cfg.DEVICE_TABLE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(cfg.DEVICE_TABLE_FILE)
        log.info(f"  device_table.json written ({len(rows) - 1} device(s))")
    except Exception as e:
        log.warning(f"  Could not write device_table.json: {e}")


def _save_quality_log(data: dict, skip_backup: bool = False) -> None:
    """
    Writes quality_log.json atomically via temp file.

    skip_backup=True: suppresses backup trigger (used for filename-migration
      where content is unchanged — no backup needed).
    skip_backup=False (default): triggers garmin_backup after successful write
      for monthly snapshot and yearly consolidation (A2, A4).

    Before writing:
      - sorts data['days'] by 'date' ascending (A3)
      - computes and stores SHA-256 checksum of entries (A3)
    """
    try:
        data["days"] = sorted(data.get("days", []), key=lambda e: e.get("date", ""))
    except Exception:
        pass

    data["_checksum"] = _compute_checksum(data)

    tmp = cfg.QUALITY_LOG_FILE.with_suffix(".tmp")
    try:
        cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(cfg.QUALITY_LOG_FILE)
    except Exception as e:
        log.warning(f"  Could not write quality_log.json: {e}")
        return

    if skip_backup:
        return

    try:
        import garmin_backup as _backup
        _backup.backup_quality_log()
    except ImportError:
        pass  # garmin_backup not yet available (component B not built)
    except Exception as e:
        log.warning(f"  quality_log backup trigger failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Defective log
# ══════════════════════════════════════════════════════════════════════════════

def _save_defective_log(data: dict) -> None:
    """
    Saves a copy of the defective quality_log state to AUTORESTORE_DIR
    before auto-restore overwrites it. Filename: auto-restore-YYYY-MM-DD.zip
    Silently skips on any error — defective state preservation is best-effort.
    """
    try:
        cfg.AUTORESTORE_DIR.mkdir(parents=True, exist_ok=True)
        ts       = datetime.now().strftime("%Y-%m-%d")
        zip_path = cfg.AUTORESTORE_DIR / f"auto-restore-{ts}.zip"
        payload  = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("quality_log_defective.json", payload)
        log.info(f"  Defective log saved to: {zip_path.name}")
    except Exception as e:
        log.warning(f"  Could not save defective log: {e}")
