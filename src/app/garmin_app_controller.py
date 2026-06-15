#!/usr/bin/env python3
"""
garmin_app_controller.py
Garmin Local Archive — Application Controller

Layer 3 — no tkinter, no Qt, no GUI imports of any kind.
Owns application logic: ENV construction, migration checks,
archive stats, connection testing, timer calculations,
startup checks.

Callback contract (v1.5.3-ready):
    All communication with the View happens via callbacks passed
    in by the caller. Callbacks receive only Python base types
    (str, bool, dict, list). The controller never calls self.after(),
    messagebox, or any widget method.

    In v1.5.3 the View replaces lambda callbacks with pyqtSignal
    emitters — this module remains unchanged.
"""

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path


# ── ENV construction ───────────────────────────────────────────────────────────

def build_env_dict(s: dict, refresh_failed: bool = False) -> dict:
    """
    Build GARMIN_* environment variables as a pure dict.
    No side effects — caller decides how to apply (Popen env= or os.environ).
    """
    base = Path(s["base_dir"])
    env = {}
    env["PYTHONUTF8"]               = "1"
    env["GARMIN_EMAIL"]             = s["email"]
    env["GARMIN_PASSWORD"]          = s["password"]
    env["GARMIN_OUTPUT_DIR"]        = str(base)
    env["GARMIN_EXPORT_FILE"]       = str(base / "garmin_export.xlsx")
    env["GARMIN_TIMESERIES_FILE"]   = str(base / "garmin_timeseries.xlsx")
    env["GARMIN_DASHBOARD_FILE"]    = str(base / "garmin_dashboard.html")
    env["GARMIN_ANALYSIS_HTML"]     = str(base / "garmin_analysis.html")
    env["GARMIN_ANALYSIS_JSON"]     = str(base / "garmin_analysis.json")
    env["GARMIN_SYNC_MODE"]         = s["sync_mode"]
    env["GARMIN_DAYS_BACK"]         = s["sync_days"] or "90"
    env["GARMIN_SYNC_START"]        = s.get("sync_from", "")
    env["GARMIN_SYNC_END"]          = s.get("sync_to", "")
    env["GARMIN_SYNC_FALLBACK"]     = s.get("sync_auto_fallback", "")
    env["GARMIN_REQUEST_DELAY_MIN"] = s["request_delay_min"]
    env["GARMIN_REQUEST_DELAY_MAX"] = s["request_delay_max"]
    env["GARMIN_REFRESH_FAILED"]    = "1" if refresh_failed else "0"

    _today  = date.today()
    _d_from = s.get("date_from", "").strip()
    _d_to   = s.get("date_to",   "").strip()

    if not _d_from or not _d_to:
        _summary_dir = Path(s.get("base_dir", "")) / "garmin_data" / "summary"
        _dates = sorted(
            f.stem.replace("garmin_", "")
            for f in _summary_dir.glob("garmin_???-??-??.json")
        ) if _summary_dir.exists() else []

    env["GARMIN_DATE_FROM"] = _d_from or (
        _dates[0] if _dates else (_today - timedelta(days=90)).isoformat()
    )
    env["GARMIN_DATE_TO"] = _d_to or (
        _dates[-1] if _dates else _today.isoformat()
    )
    env["GARMIN_PROFILE_AGE"]         = s.get("age", "35")
    env["GARMIN_PROFILE_SEX"]         = s.get("sex", "male")
    env["GARMIN_LOG_LEVEL"]           = "DEBUG"
    env["GARMIN_SESSION_LOG_PREFIX"]  = "garmin"
    env["GARMIN_SYNC_DATES"]          = ""
    return env


# ── Migration ──────────────────────────────────────────────────────────────────

def check_migration_needed(base_dir: Path) -> bool:
    """
    Returns True if the old folder structure (raw/ at base_dir level)
    exists and has not yet been migrated to garmin_data/.
    No side effects.
    """
    old_raw = base_dir / "raw"
    new_dir = base_dir / "garmin_data"
    return old_raw.exists() and not new_dir.exists()


def run_migration(base_dir: Path) -> str:
    """
    Moves raw/, summary/, log/ into garmin_data/.
    Returns "ok" on success, "error" on failure.
    Never raises — caller (View) decides what to do with the result.
    """
    import shutil
    new_dir = base_dir / "garmin_data"
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
        for folder in ("raw", "summary", "log"):
            src = base_dir / folder
            dst = new_dir / folder
            if src.exists():
                shutil.move(str(src), str(dst))
        return "ok"
    except Exception:
        return "error"


# ── Archive stats ──────────────────────────────────────────────────────────────

def get_archive_stats(base_dir: str | Path) -> dict:
    """
    Returns the archive stats dict from garmin_quality.
    Encapsulates path resolution — View does not need to know
    the internal directory structure.
    Returns empty dict on any failure.
    """
    try:
        import garmin_quality as quality
        quality_log = Path(base_dir) / "garmin_data" / "log" / "quality_log.json"
        return quality.get_archive_stats(quality_log)
    except Exception:
        return {}


# ── Connection test ────────────────────────────────────────────────────────────

def check_connection(s: dict, callbacks: dict) -> None:
    """
    Tests Garmin Connect connectivity in a background thread.
    Communicates exclusively via callbacks — no GUI access, no self.after().

    callbacks dict (all optional — controller checks before calling):
        on_log(text: str)                   — status message for the log
        on_token(state: str)                — "ok" / "fail" / "reset" / "pending"
        on_login(state: str)                — "ok" / "fail" / "pending"
        on_api(state: str)                  — "ok" / "fail" / "pending"
        on_data(state: str)                 — "ok" / "fail" / "pending"
        on_success()                        — called when all checks pass
        on_enc_key(mode: str) -> str|None   — prompt for encryption key
        on_token_expired() -> bool          — prompt before SSO after expired token
        on_sso_required() -> bool           — prompt before SSO on first setup
        on_mfa() -> str|None                — prompt for MFA code

    v1.5.3 note: View replaces lambda callbacks with pyqtSignal emitters.
    This function remains unchanged.
    """
    def _cb(name, *args):
        fn = callbacks.get(name)
        if callable(fn):
            return fn(*args)
        return None

    def worker():
        # Apply ENV in thread scope — garmin_config reads from os.environ.
        # Behaviour identical to today; garmin_config is reloaded immediately
        # after to pick up new values.
        os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
        os.environ["GARMIN_EMAIL"]      = s["email"]
        os.environ["GARMIN_PASSWORD"]   = s["password"]

        import importlib
        import garmin_config as cfg
        importlib.reload(cfg)
        import garmin_security

        try:
            from garminconnect import Garmin  # noqa: F401 — import check only
        except ImportError:
            _cb("on_log", "✗ garminconnect not installed.")
            return

        token_file_exists = cfg.GARMIN_TOKEN_FILE.exists()
        enc_key_present   = garmin_security.get_enc_key() is not None

        if not token_file_exists:
            _cb("on_token", "reset")
        elif token_file_exists and not enc_key_present:
            _cb("on_token", "fail")
            _cb("on_log", "  ⚠ Encryption key missing — re-entry required")
        else:
            _cb("on_token", "pending")

        _cb("on_login", "pending")
        try:
            import garmin_api
            client = garmin_api.login(
                on_key_required  = lambda mode="setup": _cb("on_enc_key", mode),
                on_token_expired = lambda: _cb("on_token_expired"),
                on_mfa_required  = lambda: _cb("on_mfa"),
                on_sso_required  = lambda: _cb("on_sso_required"),
            )
            token_now = (cfg.GARMIN_TOKEN_FILE.exists() and
                         garmin_security.get_enc_key() is not None)
            _cb("on_token", "ok" if token_now else "reset")
            _cb("on_login", "ok")
            _cb("on_log", "  ✓ Login successful")
        except SystemExit:
            _cb("on_login", "fail")
            _cb("on_token", "fail")
            _cb("on_log", "  ✗ Login failed or cancelled")
            return
        except Exception as e:
            _cb("on_login", "fail")
            _cb("on_log", f"  ✗ Login failed: {e}")
            return

        _cb("on_api", "pending")
        try:
            client.get_user_profile()
            _cb("on_api", "ok")
            _cb("on_log", "  ✓ API access OK")
        except Exception as e:
            _cb("on_api", "fail")
            _cb("on_log", f"  ✗ API access failed: {e}")
            return

        _cb("on_data", "pending")
        try:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            client.get_stats(yesterday)
            _cb("on_data", "ok")
            _cb("on_log", "  ✓ Data access OK")
            _cb("on_success")
        except Exception as e:
            _cb("on_data", "fail")
            _cb("on_log", f"  ✗ Data access failed: {e}")

    threading.Thread(target=worker, daemon=True).start()


# ── Timer calculations ─────────────────────────────────────────────────────────

def timer_run_repair(s: dict) -> list | None:
    """Returns list of date objects with quality='failed'. None if empty."""
    try:
        # INTENTIONAL DIRECT READ — read-only analytical fast-path.
        # No mutation, no ownership transfer, no QUALITY_LOCK required.
        # os.replace() atomicity guarantees reader sees either the old or the
        # new complete file — never a partial write.
        # garmin_quality provides no filtered-list API for these queries;
        # adding one would inflate the module into a query gateway.
        # Documented exception: see REFERENCE_GARMIN.md § Documented Exceptions.
        failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
        if not failed_file.exists():
            return None
        data    = json.loads(failed_file.read_text(encoding="utf-8"))
        entries = data.get("days", [])
        days = []
        for e in entries:
            q = e.get("quality", e.get("category", ""))
            if q == "failed" and e.get("recheck", True):
                try:
                    days.append(date.fromisoformat(e["date"]))
                except (ValueError, KeyError):
                    pass
        return days if days else None
    except Exception:
        return None


def timer_run_bulk_recheck(s: dict) -> list | None:
    """Returns bulk-source days within last 180 days, oldest first. None if empty."""
    try:
        # INTENTIONAL DIRECT READ — read-only analytical fast-path.
        # No mutation, no ownership transfer, no QUALITY_LOCK required.
        # os.replace() atomicity guarantees reader sees either the old or the
        # new complete file — never a partial write.
        # garmin_quality provides no filtered-list API for these queries;
        # adding one would inflate the module into a query gateway.
        # Documented exception: see REFERENCE_GARMIN.md § Documented Exceptions.
        log_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
        if not log_file.exists():
            return None
        data   = json.loads(log_file.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=180)
        days = []
        for e in data.get("days", []):
            if e.get("source") == "bulk" and e.get("recheck", False):
                try:
                    d = date.fromisoformat(e["date"])
                    if d >= cutoff:
                        days.append(d)
                except (ValueError, KeyError):
                    pass
        days.sort()
        return days if days else None
    except Exception:
        return None


def timer_run_quality(s: dict) -> list | None:
    """Returns standard-quality days with recheck=True (non-bulk, ≤180 days). None if empty.

    v1.5.7: 'low' label removed. standard + recheck=True is the equivalent:
    Garmin delivered no intraday on first fetch — retry window still open.
    bulk-sourced days are handled by timer_run_bulk_recheck (separate channel).
    """
    try:
        # INTENTIONAL DIRECT READ — read-only analytical fast-path.
        # No mutation, no ownership transfer, no QUALITY_LOCK required.
        # os.replace() atomicity guarantees reader sees either the old or the
        # new complete file — never a partial write.
        # garmin_quality provides no filtered-list API for these queries;
        # adding one would inflate the module into a query gateway.
        # Documented exception: see REFERENCE_GARMIN.md § Documented Exceptions.
        failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
        if not failed_file.exists():
            return None
        data    = json.loads(failed_file.read_text(encoding="utf-8"))
        entries = data.get("days", [])
        cutoff  = date.today() - timedelta(days=180)
        days = []
        for e in entries:
            q = e.get("quality", e.get("category", ""))
            if (q == "standard"
                    and e.get("recheck", False)
                    and e.get("source", "") != "bulk"):
                try:
                    d = date.fromisoformat(e["date"])
                    if d >= cutoff:
                        days.append(d)
                except (ValueError, KeyError):
                    pass
        days.sort()
        return days if days else None
    except Exception:
        return None


def timer_run_source_backfill(s: dict) -> list | None:
    """Returns API days within last 180 days that have no source/ file. None if empty.

    Called by the Background Timer source_backfill mode. Returns up to 30
    candidates, oldest first — the timer picks min_days..max_days from this list
    per cycle via random.sample (same as fill mode).

    INTENTIONAL DIRECT READ — read-only analytical fast-path.
    No mutation, no ownership transfer, no QUALITY_LOCK required.
    os.replace() atomicity guarantees reader sees either the old or the
    new complete file — never a partial write.
    garmin_quality provides no filtered-list API for these queries;
    adding one would inflate the module into a query gateway.
    Documented exception: see REFERENCE_GARMIN.md § Documented Exceptions.
    """
    try:
        log_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
        if not log_file.exists():
            return None
        source_dir = Path(s["base_dir"]) / "garmin_data" / "source"
        data   = json.loads(log_file.read_text(encoding="utf-8"))
        cutoff = date.today() - timedelta(days=180)
        days = []
        for e in data.get("days", []):
            if e.get("source") != "api":
                continue
            date_str = e.get("date")
            if not date_str:
                continue
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                continue
            if d < cutoff:
                continue
            src_file = source_dir / f"garmin_source_{date_str}.json"
            if not src_file.exists():
                days.append(d)
        days.sort()
        return days if days else None
    except Exception:
        return None


def timer_run_fill(s: dict) -> list | None:
    """Returns dates completely absent from raw/ between earliest known and yesterday."""
    try:
        raw_dir = Path(s["base_dir"]) / "garmin_data" / "raw"
        existing = set()
        if raw_dir.exists():
            for f in raw_dir.glob("garmin_raw_*.json"):
                try:
                    existing.add(date.fromisoformat(f.stem.replace("garmin_raw_", "")))
                except ValueError:
                    pass
        failed_file = Path(s["base_dir"]) / "garmin_data" / "log" / "quality_log.json"
        failed_dates = set()
        if failed_file.exists():
            try:
                data = json.loads(failed_file.read_text(encoding="utf-8"))
                for e in data.get("days", []):
                    try:
                        failed_dates.add(date.fromisoformat(e["date"]))
                    except (ValueError, KeyError):
                        pass
            except Exception:
                pass
        all_known = existing | failed_dates
        if not all_known:
            return None
        yesterday = date.today() - timedelta(days=1)
        earliest  = min(all_known)
        missing = []
        current = earliest
        while current <= yesterday:
            if current not in existing and current not in failed_dates:
                missing.append(current)
            current += timedelta(days=1)
        return missing if missing else None
    except Exception:
        return None


# ── Startup checks ─────────────────────────────────────────────────────────────

def check_integrity(s: dict) -> dict:
    """
    Runs garmin_backup.check_raw_integrity().
    Returns result dict with 'missing_days' and 'no_backup' keys.
    Returns empty lists on any failure.

    Sets GARMIN_OUTPUT_DIR from s["base_dir"] and reloads garmin_config
    before the check — garmin_backup uses cfg.RAW_DIR / cfg.RAW_BACKUP_DIR
    which are derived from GARMIN_OUTPUT_DIR at import time.
    Without this, the check runs against the default path (~/local_archive)
    instead of the user-configured data directory.
    """
    try:
        import importlib
        import os
        import garmin_config as cfg
        os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
        importlib.reload(cfg)
        import garmin_backup as _backup
        return _backup.check_raw_integrity()
    except Exception:
        return {"missing_days": [], "no_backup": []}


def check_mirror(s: dict) -> bool:
    """
    Returns True if the configured mirror_dir is reachable.
    Returns False on any failure or if mirror_dir is not set.
    """
    try:
        import garmin_mirror as _mirror
        mirror_dir = s.get("mirror_dir", "").strip()
        return _mirror.is_reachable(mirror_dir)
    except Exception:
        return False
