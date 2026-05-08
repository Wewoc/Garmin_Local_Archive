#!/usr/bin/env python3
"""
daily_update.py
Garmin Local Archive — Automated Daily Sync

Thin entry point for headless daily operation via Windows Task Scheduler.
No GUI, no manual interaction. After initial setup in the desktop app,
this script becomes the only daily touchpoint with the system.

Workflow:
  1. Preconditions  — settings present, no migration required
  2. Version check  — GitHub API, non-blocking
  3. Gap detection  — quality_log.json → last known date → date range
  4. Garmin sync    — garmin_collector.main()
  5. Context sync   — context_collector.run()
  6. Dashboards     — dash_runner.build() for all specialists (if no API errors)
  7. Exit

Exit codes (Task Scheduler):
  0 = success
  1 = migration required (folder structure or schema) — open the app
  2 = settings missing — open the app
  3 = API error (Garmin and/or Context) — check log/daily/
  4 = dashboard error — check log/daily/
  5 = update available — open GitHub

Console behaviour:
  - All OK           → window closes automatically (sys.exit(0))
  - Error / Update   → window stays open, press Enter to close

Build targets:
  T1 — python daily_update.py
  T2 — daily_update.bat (calls python daily_update.py)
  T3 — daily_update.exe (standalone, no Python required)

All project module imports are lazy (after os.environ is set) because
garmin_config reads os.environ at import time — any earlier import would
silently use default paths instead of the user's settings.
"""

import json
import logging
import os
import shutil
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════════════════════

from version import APP_VERSION

SETTINGS_FILE   = Path.home() / ".garmin_archive_settings.json"
KEYRING_SERVICE = "GarminLocalArchive"
KEYRING_USER    = "garmin_password"

GAP_HARD_STOP_DAYS = 7    # gaps larger than this trigger a hard stop
LOG_DAILY_MAX      = 30   # rolling log file limit

DEFAULT_SETTINGS = {
    "email":             "",
    "base_dir":          str(Path.home() / "local_archive"),
    "sync_mode":         "recent",
    "sync_days":         "90",
    "sync_from":         "",
    "sync_to":           "",
    "age":               "35",
    "sex":               "male",
    "request_delay_min": "5.0",
    "request_delay_max": "20.0",
    "context_latitude":  "0.0",
    "context_longitude": "0.0",
}

# ══════════════════════════════════════════════════════════════════════════════
#  Logging setup — console + daily log file (added after settings are loaded)
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

_daily_fh: logging.FileHandler | None = None


def _start_daily_log(base_dir: Path) -> None:
    """Open a rolling log file in BASE_DIR/log/daily/."""
    global _daily_fh
    log_dir = base_dir / "garmin_data" / "log" / "daily"
    log_dir.mkdir(parents=True, exist_ok=True)

    ts       = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = log_dir / f"daily_{ts}.log"

    _daily_fh = logging.FileHandler(log_path, encoding="utf-8")
    _daily_fh.setLevel(logging.DEBUG)
    _daily_fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(_daily_fh)

    # Rolling: keep only LOG_DAILY_MAX files
    try:
        logs = sorted(log_dir.glob("daily_*.log"), key=lambda f: f.stat().st_mtime)
        for old in logs[:-LOG_DAILY_MAX]:
            old.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"  Could not rotate daily logs: {e}")


def _close_daily_log() -> None:
    global _daily_fh
    if _daily_fh:
        logging.getLogger().removeHandler(_daily_fh)
        _daily_fh.close()
        _daily_fh = None


# ══════════════════════════════════════════════════════════════════════════════
#  Settings + credentials
# ══════════════════════════════════════════════════════════════════════════════

def _load_settings() -> dict | None:
    """Load settings from ~/.garmin_archive_settings.json.
    Returns None if file is missing or unreadable."""
    if not SETTINGS_FILE.exists():
        return None
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        data.pop("password", None)
        return {**DEFAULT_SETTINGS, **data}
    except Exception as e:
        log.error(f"  Could not read settings: {e}")
        return None


def _load_password() -> str:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
#  Precondition checks
# ══════════════════════════════════════════════════════════════════════════════

def _check_folder_migration(base_dir: Path) -> bool:
    """Returns True if old folder structure detected (migration required)."""
    old_raw  = base_dir / "raw"
    new_dir  = base_dir / "garmin_data"
    return old_raw.exists() and not new_dir.exists()


def _check_schema_migration(base_dir: Path) -> bool:
    """Returns True if any summary file has an outdated schema_version."""
    # Lazy import — garmin_config reads ENVs at import time
    try:
        import garmin_normalizer as normalizer
        current = normalizer.CURRENT_SCHEMA_VERSION
    except Exception:
        return False

    summary_dir = base_dir / "garmin_data" / "summary"
    if not summary_dir.exists():
        return False

    for f in summary_dir.glob("garmin_???-??-??.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("schema_version", 0) < current:
                return True
        except Exception:
            continue
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  Version check
# ══════════════════════════════════════════════════════════════════════════════

def _check_version() -> str | None:
    """Check GitHub for a newer release. Returns latest tag if newer, else None."""
    url = "https://api.github.com/repos/Wewoc/Garmin_Local_Archive/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GarminLocalArchive"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        latest = data.get("tag_name", "").strip()
        if latest and latest.lstrip("vV") != APP_VERSION.lstrip("vV"):
            return latest
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Gap detection
# ══════════════════════════════════════════════════════════════════════════════

def _detect_gap(base_dir: Path) -> tuple[date | None, date | None, int]:
    """
    Read quality_log.json and determine the sync date range for today's run.

    Returns:
        (date_from, date_to, gap_days)
        date_from / date_to are None if the archive is empty (first run).
        gap_days is 0 if archive is up to date or empty.
    """
    # Lazy import after ENVs are set
    import garmin_quality as quality

    try:
        with quality.QUALITY_LOCK:
            quality_data = quality._load_quality_log()
    except Exception as e:
        log.warning(f"  Could not read quality log: {e}")
        return None, None, 0

    days = quality_data.get("days", [])
    if not days:
        # Empty archive — let collector decide the full range
        return None, None, 0

    # Find the latest date with a written summary
    written_dates = []
    for entry in days:
        if entry.get("write", False) or entry.get("written", False):
            try:
                written_dates.append(date.fromisoformat(entry["date"]))
            except (KeyError, ValueError):
                continue

    if not written_dates:
        return None, None, 0

    last_known = max(written_dates)
    yesterday  = date.today() - timedelta(days=1)
    gap_days   = (yesterday - last_known).days

    if gap_days <= 0:
        log.info("  Archive is up to date.")
        return None, None, 0

    date_from = last_known + timedelta(days=1)
    date_to   = yesterday
    return date_from, date_to, gap_days


# ══════════════════════════════════════════════════════════════════════════════
#  ENV builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_env(s: dict, password: str, date_from: date | None, date_to: date | None) -> dict:
    """Build GARMIN_* environment variables as a dict."""
    base = Path(s["base_dir"])
    yesterday = date.today() - timedelta(days=1)

    env = {}
    env["PYTHONUTF8"]               = "1"
    env["GARMIN_EMAIL"]             = s["email"]
    env["GARMIN_PASSWORD"]          = password
    env["GARMIN_OUTPUT_DIR"]        = str(base)
    env["GARMIN_EXPORT_FILE"]       = str(base / "garmin_export.xlsx")
    env["GARMIN_TIMESERIES_FILE"]   = str(base / "garmin_timeseries.xlsx")
    env["GARMIN_DASHBOARD_FILE"]    = str(base / "garmin_dashboard.html")
    env["GARMIN_ANALYSIS_HTML"]     = str(base / "garmin_analysis.html")
    env["GARMIN_ANALYSIS_JSON"]     = str(base / "garmin_analysis.json")
    env["GARMIN_REQUEST_DELAY_MIN"] = str(s.get("request_delay_min", "5.0"))
    env["GARMIN_REQUEST_DELAY_MAX"] = str(s.get("request_delay_max", "20.0"))
    env["GARMIN_REFRESH_FAILED"]    = "0"
    env["GARMIN_PROFILE_AGE"]       = str(s.get("age", "35"))
    env["GARMIN_PROFILE_SEX"]       = str(s.get("sex", "male"))
    env["GARMIN_LOG_LEVEL"]         = "INFO"
    env["GARMIN_SESSION_LOG_PREFIX"] = "daily"
    env["GARMIN_SYNC_DATES"]        = ""
    env["GARMIN_CONTEXT_LAT"]       = str(s.get("context_latitude",  "0.0"))
    env["GARMIN_CONTEXT_LON"]       = str(s.get("context_longitude", "0.0"))

    if date_from and date_to:
        env["GARMIN_SYNC_MODE"]  = "range"
        env["GARMIN_SYNC_START"] = date_from.isoformat()
        env["GARMIN_SYNC_END"]   = date_to.isoformat()
    else:
        # Empty archive or up to date — use range: today-1 → today-1
        env["GARMIN_SYNC_MODE"]  = "range"
        env["GARMIN_SYNC_START"] = yesterday.isoformat()
        env["GARMIN_SYNC_END"]   = yesterday.isoformat()

    env["GARMIN_DAYS_BACK"]  = str(s.get("sync_days", "90"))
    env["GARMIN_SYNC_FALLBACK"] = str(s.get("sync_auto_fallback", ""))

    return env


# ══════════════════════════════════════════════════════════════════════════════
#  Sync steps
# ══════════════════════════════════════════════════════════════════════════════

def _run_garmin_sync() -> bool:
    """Run garmin_collector.main(). Returns True on success."""
    log.info("=" * 60)
    log.info("STEP: Garmin Sync")
    log.info("=" * 60)
    try:
        import garmin_collector as collector
        collector.main()
        log.info("  ✓ Garmin sync complete")
        return True
    except SystemExit as e:
        success = e.code in (None, 0)
        if not success:
            log.error(f"  ✗ Garmin sync exited with code {e.code}")
        return success
    except Exception as e:
        log.error(f"  ✗ Garmin sync failed: {e}")
        return False


def _run_context_sync(s: dict) -> bool:
    """Run context_collector.run(). Returns True on success."""
    log.info("=" * 60)
    log.info("STEP: Context Sync")
    log.info("=" * 60)
    try:
        import importlib
        ctx = importlib.import_module("context.context_collector")
        result = ctx.run(settings=s)
        if result.get("error"):
            log.error(f"  ✗ Context sync error: {result['error']}")
            return False
        log.info(f"  ✓ Context sync complete — {result.get('segments', 0)} segments")
        return True
    except Exception as e:
        log.error(f"  ✗ Context sync failed: {e}")
        return False


def _run_dashboards(s: dict) -> bool:
    """Build all dashboards via dash_runner. Returns True on success."""
    log.info("=" * 60)
    log.info("STEP: Dashboards")
    log.info("=" * 60)
    try:
        import dash_runner

        specialists = dash_runner.scan()
        if not specialists:
            log.warning("  No dashboard specialists found — skipping")
            return True

        selections = [
            (spec["module"], fmt)
            for spec in specialists
            for fmt in spec["formats"]
        ]

        base     = Path(s["base_dir"])
        out_dir  = base / "garmin_data" / "dashboards"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Date range: full archive
        summary_dir = base / "garmin_data" / "summary"
        dates = sorted(
            f.stem.replace("garmin_", "")
            for f in summary_dir.glob("garmin_???-??-??.json")
        ) if summary_dir.exists() else []

        today = date.today()
        date_from = dates[0]  if dates else (today - timedelta(days=90)).isoformat()
        date_to   = dates[-1] if dates else today.isoformat()

        results = dash_runner.build(
            selections=selections,
            date_from=date_from,
            date_to=date_to,
            settings=s,
            output_dir=out_dir,
            log=lambda msg: log.info(f"  {msg}"),
        )

        failed = [r for r in results if not r.get("success")]
        if failed:
            for r in failed:
                log.error(f"  ✗ {r['name']} ({r['format']}): {r.get('error', 'unknown')}")
            return False

        log.info(f"  ✓ {len(results)} dashboard(s) built")
        return True

    except Exception as e:
        log.error(f"  ✗ Dashboard build failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  sys.path setup for T3 (frozen)
# ══════════════════════════════════════════════════════════════════════════════

def _setup_paths():
    """Ensure all project packages are importable."""
    if getattr(sys, "frozen", False):
        # T3: modules are in sys._MEIPASS/scripts/
        import types
        scripts = Path(sys._MEIPASS) / "scripts"
        # scripts/ itself — makes flat imports like 'import dash_runner' work
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        garmin_dir = scripts / "garmin"
        if garmin_dir.exists():
            sys.path.insert(0, str(garmin_dir))
        for pkg in ("context", "maps", "dashboards", "layouts"):
            pkg_dir = scripts / pkg
            if pkg_dir.exists() and pkg not in sys.modules:
                mod = types.ModuleType(pkg)
                mod.__path__ = [str(pkg_dir)]
                mod.__package__ = pkg
                sys.modules[pkg] = mod
            # Also add subdir to sys.path for flat imports within the package
            if pkg_dir.exists() and str(pkg_dir) not in sys.path:
                sys.path.append(str(pkg_dir))
    else:
        # T1/T2: subfolders next to daily_update.py
        import types
        _root = Path(__file__).parent
        for _sub in ("garmin", "maps", "dashboards", "layouts"):
            _p = str(_root / _sub)
            if _p not in sys.path:
                sys.path.insert(0, _p)
        # context must be registered as a package — it uses relative imports
        _ctx_dir = _root / "context"
        if _ctx_dir.exists() and "context" not in sys.modules:
            _ctx_mod = types.ModuleType("context")
            _ctx_mod.__path__ = [str(_ctx_dir)]
            _ctx_mod.__package__ = "context"
            sys.modules["context"] = _ctx_mod
        _p = str(_ctx_dir)
        if _p not in sys.path:
            sys.path.insert(0, _p)


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    _setup_paths()

    log.info("Garmin Local Archive — Daily Sync")
    log.info(f"Version: {APP_VERSION}")
    log.info(f"Date:    {date.today().isoformat()}")

    # ── 1. Settings ───────────────────────────────────────────────────────────
    s = _load_settings()
    if not s or not s.get("email") or not s.get("base_dir"):
        log.error("  Settings missing or incomplete.")
        log.error(f"  Expected: {SETTINGS_FILE}")
        log.error("  Please open the app and save your settings first.")
        return 2

    base_dir = Path(s["base_dir"]).expanduser()
    password = _load_password()

    # Start file logging now that we know base_dir
    _start_daily_log(base_dir)

    log.info(f"Archive:  {base_dir}")

    # ── 2. Migration check ────────────────────────────────────────────────────
    if _check_folder_migration(base_dir):
        log.error("  Old folder structure detected.")
        log.error("  Please open the app to run the migration first.")
        return 1

    # ── 3. ENV setup (before any project module import) ───────────────────────
    # Gap detection needs garmin_quality which needs garmin_config which reads ENVs.
    # Set a minimal ENV first so quality log path resolves correctly.
    os.environ["GARMIN_OUTPUT_DIR"] = str(base_dir)

    # ── 4. Schema migration check ─────────────────────────────────────────────
    if _check_schema_migration(base_dir):
        log.error("  Schema migration required.")
        log.error("  Please open the app to run the migration first.")
        return 1

    # ── 5. Version check (non-blocking) ───────────────────────────────────────
    update_available = _check_version()
    if update_available:
        log.warning(f"  A new version is available: {update_available}")
        log.warning(f"  You are running: {APP_VERSION}")
        log.warning("  https://github.com/Wewoc/Garmin_Local_Archive/releases/latest")

    # ── 6. Gap detection ──────────────────────────────────────────────────────
    date_from, date_to, gap_days = _detect_gap(base_dir)

    if gap_days > GAP_HARD_STOP_DAYS:
        log.error(f"  {gap_days} days missing in archive.")
        log.error("  Gap too large for automated sync — please open the app.")
        return 3

    if gap_days > 0:
        log.info(f"  Gap detected: {gap_days} day(s) — syncing {date_from} → {date_to}")
    elif gap_days == 0 and date_from is None:
        log.info("  Archive empty or up to date — running yesterday sync.")

    # ── 7. Full ENV setup ─────────────────────────────────────────────────────
    env = _build_env(s, password, date_from, date_to)
    for k, v in env.items():
        os.environ[k] = v

    # ── 8. Garmin sync ────────────────────────────────────────────────────────
    garmin_ok = _run_garmin_sync()

    # ── 9. Context sync ───────────────────────────────────────────────────────
    context_ok = _run_context_sync(s)

    # ── 10. Dashboards (only if both APIs clean) ──────────────────────────────
    dash_ok = True
    if garmin_ok and context_ok:
        dash_ok = _run_dashboards(s)
    else:
        log.warning("  API error(s) detected — skipping dashboards.")

    # ── 11. Exit ──────────────────────────────────────────────────────────────
    log.info("=" * 60)

    if not garmin_ok or not context_ok:
        log.error("  Daily sync completed with API errors. Check log/daily/.")
        _close_daily_log()
        return 3

    if not dash_ok:
        log.error("  Dashboard build failed. Check log/daily/.")
        _close_daily_log()
        return 4

    if update_available:
        log.warning("  All sync steps completed successfully.")
        log.warning(f"  Update available: {update_available}")
        _close_daily_log()
        return 5

    log.info("  ✓ Daily sync completed successfully.")
    _close_daily_log()
    return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code != 0:
        print()
        input("Press Enter to close ...")
    sys.exit(exit_code)
