#!/usr/bin/env python3
"""
garmin_config.py

Central configuration for Garmin Local Archive.
Reads all GARMIN_* environment variables, sets defaults, and derives paths.

No logic, no functions, no dependencies on other project modules.
All other modules import this module — no module reads os.environ directly.

Standalone note: _apply_env() in garmin_app_standalone.py sets os.environ
before _run_module() loads garmin_collector.py. garmin_collector.py imports
garmin_config at module level — so _apply_env() always runs first.
No special load-order handling needed.
"""

import os
from pathlib import Path

import garmin_utils as _utils

# ══════════════════════════════════════════════════════════════════════════════
#  Credentials
# ══════════════════════════════════════════════════════════════════════════════

GARMIN_EMAIL    = os.environ.get("GARMIN_EMAIL",    "your@email.com")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD", "yourpassword")

# ══════════════════════════════════════════════════════════════════════════════
#  Paths
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR    = Path(os.environ.get("GARMIN_OUTPUT_DIR") or "~/garmin_data").expanduser()
RAW_DIR     = BASE_DIR / "raw"
SUMMARY_DIR = BASE_DIR / "summary"
LOG_DIR     = BASE_DIR / "log"

# Session log sub-directories
LOG_RECENT_DIR = LOG_DIR / "recent"
LOG_FAIL_DIR   = LOG_DIR / "fail"

# Quality log
QUALITY_LOG_FILE = LOG_DIR / "quality_log.json"

# Token (AES-256-GCM encrypted — managed exclusively by garmin_security.py)
GARMIN_TOKEN_DIR  = LOG_DIR / "garmin_token"        # temp working dir for library
GARMIN_TOKEN_FILE = LOG_DIR / "garmin_token.enc"    # encrypted token — permanent

# ══════════════════════════════════════════════════════════════════════════════
#  Sync mode
# ══════════════════════════════════════════════════════════════════════════════

# "recent" → check last SYNC_DAYS days
# "range"  → check SYNC_FROM to SYNC_TO
# "auto"   → check from oldest registered device to today
SYNC_MODE = os.environ.get("GARMIN_SYNC_MODE", "recent")

# Used when SYNC_MODE = "recent"
SYNC_DAYS = int(os.environ.get("GARMIN_DAYS_BACK", "90"))

# Used when SYNC_MODE = "range"
SYNC_FROM = os.environ.get("GARMIN_SYNC_START", "2024-01-01")
SYNC_TO   = os.environ.get("GARMIN_SYNC_END",   "2024-12-31")

# Used when SYNC_MODE = "auto" and device detection fails
SYNC_AUTO_FALLBACK = os.environ.get("GARMIN_SYNC_FALLBACK") or None

# Comma-separated list of specific dates (YYYY-MM-DD) — overrides SYNC_MODE if set
SYNC_DATES = _utils.parse_sync_dates(os.environ.get("GARMIN_SYNC_DATES", ""))

# ══════════════════════════════════════════════════════════════════════════════
#  API & request behaviour
# ══════════════════════════════════════════════════════════════════════════════

# Delay between API requests — random float between min and max (seconds)
# Breaks the fixed request pattern to reduce Garmin rate-limit risk
REQUEST_DELAY_MIN = float(os.environ.get("GARMIN_REQUEST_DELAY_MIN", "5.0"))
REQUEST_DELAY_MAX = float(os.environ.get("GARMIN_REQUEST_DELAY_MAX", "20.0"))

# If True: days with recheck=True are excluded from get_local_dates() → re-fetched
REFRESH_FAILED = os.environ.get("GARMIN_REFRESH_FAILED", "0") == "1"

# Max re-download attempts for 'low' quality days before giving up
LOW_QUALITY_MAX_ATTEMPTS = int(os.environ.get("GARMIN_LOW_QUALITY_MAX_ATTEMPTS", "3"))

# ══════════════════════════════════════════════════════════════════════════════
#  Session & logging
# ══════════════════════════════════════════════════════════════════════════════

# Prefix for session log filenames — background timer sets "garmin_background"
SESSION_LOG_PREFIX = os.environ.get("GARMIN_SESSION_LOG_PREFIX", "garmin")

# Maximum number of session logs kept in log/recent/ (rolling)
LOG_RECENT_MAX = 30

# Log level for the root logger
LOG_LEVEL = os.environ.get("GARMIN_LOG_LEVEL", "INFO")

# ══════════════════════════════════════════════════════════════════════════════
#  Collector limits
# ══════════════════════════════════════════════════════════════════════════════

# Maximum days fetched per session (placeholder — used from v1.2.1 onwards)
MAX_DAYS_PER_SESSION = int(os.environ.get("GARMIN_MAX_DAYS_PER_SESSION", "30"))

# Days processed per chunk before quality_log.json is flushed to disk
# 0 = no chunking (single pass). Default: 10
SYNC_CHUNK_SIZE = int(os.environ.get("GARMIN_SYNC_CHUNK_SIZE", "10"))
