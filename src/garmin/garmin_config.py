#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_config.py

Central configuration for Garmin Local Archive.
Reads all GARMIN_* environment variables, sets defaults, and derives paths.

No business logic. A small number of narrowly-scoped parsing helpers exist
where the same fallback shape is needed in multiple places below (see
_read_mcp_server_config(), _parse_extra_hosts()) — deliberate, documented
exceptions, not a precedent for broader logic in this file. One
project-internal import exists: garmin_utils, used only for SYNC_DATES
(_utils.parse_sync_dates()).
All other modules import this module — no module reads os.environ directly.

Standalone note: _apply_env() in garmin_app_standalone.py sets os.environ
before _run_module() loads garmin_collector.py. garmin_collector.py imports
garmin_config at module level — so _apply_env() always runs first.
No special load-order handling needed.
"""

import json
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

BASE_DIR    = Path(os.environ.get("GARMIN_OUTPUT_DIR") or "~/local_archive").expanduser()
GARMIN_DIR  = BASE_DIR / "garmin_data"
RAW_DIR     = GARMIN_DIR / "raw"
SUMMARY_DIR = GARMIN_DIR / "summary"
LOG_DIR     = GARMIN_DIR / "log"

# Session log sub-directories
LOG_RECENT_DIR = LOG_DIR / "recent"
LOG_FAIL_DIR   = LOG_DIR / "fail"
LOG_DAILY_DIR  = LOG_DIR / "daily"

# Quality log
QUALITY_LOG_FILE  = LOG_DIR / "quality_log.json"
DEVICE_TABLE_FILE = LOG_DIR / "device_table.json"

# API Capability Scan config (sole owner: garmin_api_capability.py)
CAPABILITY_CONFIG_FILE = LOG_DIR / "garmin_api_capability_config.json"

# Backup directories (sole owner: garmin_backup.py)
BACKUP_DIR       = GARMIN_DIR / "backup"
LOG_BACKUP_DIR   = BACKUP_DIR / "log"    # quality_log ZIPs (monatlich + jährlich)
RAW_BACKUP_DIR   = BACKUP_DIR / "raw"    # Raw-Verzeichnisse / ZIPs
AUTORESTORE_DIR  = BACKUP_DIR / "autorestore"  # defekte Stände vor Auto-Restore

# Source archive (sole owner: garmin_source_writer.py)
# Contains unmodified API responses before any pipeline processing.
# Bulk import never writes here — only live API fetches.
SOURCE_DIR        = GARMIN_DIR / "source"
SOURCE_API_LOG    = LOG_DIR / "source_api_log.json"
# Source backup (sole owner: garmin_backup_source.py)
SOURCE_BACKUP_DIR = BACKUP_DIR / "source"

# Live snapshot (sole owner: garmin_live_fetch.py, planned v1.6.5)
# Single-file snapshot of the current day — no per-day history, overwritten
# on every fetch. Not part of the raw/summary archive.
LIVE_DIR  = GARMIN_DIR / "live"
LIVE_FILE = LIVE_DIR / "live.json"

# Schema definition for garmin_validator.py
DATAFORMAT_FILE = Path(__file__).parent / "garmin_dataformat.json"

# File name prefixes — used by garmin_health_map.py to locate daily and raw files
SUMMARY_FILE_PREFIX = "garmin_"
RAW_FILE_PREFIX     = "garmin_raw_"

# Location config file — user-managed, lives next to garmin_data/
LOCAL_CONFIG_FILE = BASE_DIR / "local_config.csv"

# ══════════════════════════════════════════════════════════════════════════════
#  Context data (external API — weather, pollen, brightsky)
# ══════════════════════════════════════════════════════════════════════════════

CONTEXT_DIR           = BASE_DIR / "context_data"
CONTEXT_WEATHER_DIR   = CONTEXT_DIR / "weather"   / "raw"
CONTEXT_POLLEN_DIR    = CONTEXT_DIR / "pollen"    / "raw"
CONTEXT_BRIGHTSKY_DIR  = CONTEXT_DIR / "brightsky"  / "raw"
CONTEXT_AIRQUALITY_DIR = CONTEXT_DIR / "airquality" / "raw"

# Location for external API calls — set via GUI (geocoded from place name)
# Falls back to ENV for headless/testing use
CONTEXT_LATITUDE  = float(os.environ.get("GARMIN_CONTEXT_LAT",  "0.0"))
CONTEXT_LONGITUDE = float(os.environ.get("GARMIN_CONTEXT_LON",  "0.0"))


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


# Intraday data retention window — Garmin degrades intraday after ~180 days.
# Used by:
#   - _upsert_quality(): recheck logic for 'standard' days (Schritt 5)
#   - garmin_collector: bulk recheck cutoff (Schritt 8)
INTRADAY_RETRY_WINDOW_DAYS = int(os.environ.get("GARMIN_INTRADAY_RETRY_WINDOW_DAYS", "180"))

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

# ══════════════════════════════════════════════════════════════════════════════
#  MCP (v1.7)
# ══════════════════════════════════════════════════════════════════════════════

# Enabled-flag for clients/mcp_server.py — pattern analogous to REFRESH_FAILED.
# ENV name keeps the GARMIN_ namespace prefix for consistency with every
# other ENV variable in this file, even though MCP itself is not
# Garmin-specific — deliberately not special-cased here, revisit as a whole
# if a v2.0 naming restructure ever happens (see NOTES_v1.7_teilc.md).
# Server-config file (v1.7 Teilbauauftrag f) — mcp_enabled, mcp_llm_backend,
# base_dir (mirrored). Enables clients/mcp_server.py to run fully standalone,
# without a GLA installation — see clients/mcp_server_gui.py, the Tkinter
# window that reads/writes this file directly for that case. Two writers
# exist for this file by design, not by oversight: app/panel_mcp.py (GLA
# context — mirrors the live GUI values on every MCP settings save) and
# clients/mcp_server_gui.py (standalone context — direct user input, no
# GLA instance to mirror from). The two never run against the same file
# at the same time in practice (a machine either runs GLA or runs the
# server standalone against a config written elsewhere), so this is not
# treated as a Sole-Write-Authority violation — but it is a deliberate,
# documented exception to that pattern, not an oversight.
MCP_SERVER_CONFIG_FILE = Path.home() / ".garmin_mcp_server_config.json"


def _read_mcp_server_config() -> dict:
    """Reads MCP_SERVER_CONFIG_FILE, returns {} if missing/empty/corrupt —
    never raises. Deliberate, narrow exception to this module's "no logic,
    no functions" rule: MCP_ENABLED/MCP_LLM_BACKEND/MCP_BASE_DIR below all
    need the same three-way fallback (ENV > file > default), and repeating
    a try/except json.load inline three times would be worse than one
    small, obviously-scoped helper. Does not become a precedent for
    broader logic in this file — this function does nothing but read and
    return a dict."""
    try:
        return json.loads(MCP_SERVER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


_mcp_server_config = _read_mcp_server_config()

# MCP_ENABLED removed (v1.7 Teilbauauftrag g) — the "Enable MCP server"
# checkbox and this flag it fed had no functional effect: main() in
# clients/mcp_server.py stopped reading it back in Teil (f) ("the window
# is the server" — no on/off gate exists anymore). Since Teil (g)
# introduced a real "Start MCP Server" button that launches the process
# directly, keeping a checkbox and a config field that influenced
# nothing would only mislead — full removal instead of leaving a dead
# constant with the appearance of live configuration. The
# "mcp_enabled" key may still linger in old, previously-written
# ~/.garmin_mcp_server_config.json files on disk — harmless, simply
# ignored, no migration needed (see _read_mcp_server_config() above,
# unchanged: unknown keys are never validated against a schema).

# Backend for MCP tool-calling (v1.7.2) — "ollama" (default) or "cloud".
# No validation here, same as SYNC_MODE — an unrecognized value is a
# consumer-side concern, not garmin_config.py's. Same ENV > file > default
# precedence as MCP_ENABLED above.
if "GARMIN_MCP_LLM_BACKEND" in os.environ:
    MCP_LLM_BACKEND = os.environ["GARMIN_MCP_LLM_BACKEND"]
else:
    MCP_LLM_BACKEND = _mcp_server_config.get("mcp_llm_backend", "ollama")

# HTTP port for the MCP server's streamable-http transport (v1.7.0.1).
# Host is deliberately NOT configurable here or anywhere — always
# 127.0.0.1, hardcoded at the FastMCP() call site in clients/mcp_server.py.
# Only the port varies. Same ENV > file > default precedence as
# MCP_LLM_BACKEND above; "mcp_http_port" key in MCP_SERVER_CONFIG_FILE,
# written by app/panel_mcp.py (mirror-on-save) and
# clients/mcp_server_gui.py (standalone context) — same dual-writer
# exception documented above MCP_SERVER_CONFIG_FILE.
if "GARMIN_MCP_HTTP_PORT" in os.environ:
    MCP_HTTP_PORT = int(os.environ["GARMIN_MCP_HTTP_PORT"])
else:
    try:
        MCP_HTTP_PORT = int(_mcp_server_config.get("mcp_http_port") or 8756)
    except (TypeError, ValueError):
        # Corrupt/non-numeric value in the config file — fail open to the
        # default rather than crashing this module's import (an explicit
        # bad ENV override above is NOT caught the same way: that's a
        # deliberate user action, a crash there is the right diagnostic).
        MCP_HTTP_PORT = 8756

# Headless mode (v1.7.0.1) — when true, clients/mcp_server.py::main()
# skips the Tkinter window entirely and runs the HTTP server directly
# on the calling thread, analogous to scheduler/daily_update.py.
# Default false: a normal start still opens the window, which owns the
# server exactly as it did under the stdio transport (window closed =
# process closed, "the window is the server") — only the transport and
# the restart-health-check mechanism changed (see MCP_HTTP_PORT above),
# not this coupling (session decision, NOTES_v1.7.0.1vorbereitung.md
# Eckpunkt 6). Settable from both app/panel_mcp.py and
# clients/mcp_server_gui.py (the latter takes effect on the next start,
# not the running instance). Same ENV > file > default precedence as
# the fields above.
if "GARMIN_MCP_HEADLESS" in os.environ:
    MCP_HEADLESS = os.environ["GARMIN_MCP_HEADLESS"].strip().lower() in ("1", "true", "yes")
else:
    MCP_HEADLESS = bool(_mcp_server_config.get("mcp_headless", False))


def _parse_extra_hosts(raw: str) -> list[str]:
    """Splits a comma-separated host list into transport_security
    allowed_hosts-style entries — each becomes '<host>:*' (any port)
    unless it already has an explicit ':port' suffix. Empty/whitespace-
    only entries are dropped. Pure parsing, no I/O — deliberate, narrow
    exception to this module's "no business logic" rule, same reasoning
    as _read_mcp_server_config() above. Shared by this module (building
    MCP_EXTRA_ALLOWED_HOSTS below) and both MCP settings UIs
    (app/panel_mcp.py, clients/mcp_server_gui.py), which call it directly
    for a live preview — guarantees the preview always matches exactly
    what gets applied, never a diverging reimplementation."""
    hosts = []
    for part in raw.split(","):
        host = part.strip()
        if not host:
            continue
        if ":" not in host:
            host = f"{host}:*"
        hosts.append(host)
    return hosts


# Extra allowed hosts for the MCP server's transport_security check
# (v1.7.0.2) — opt-in escape hatch for the SDK's built-in DNS-rebinding
# protection, which by default only allows Host headers of
# 127.0.0.1/localhost/::1 (see clients/mcp_server.py's FastMCP(...) call).
# Lets a reverse-proxied or containerized MCP client (e.g. Open WebUI
# running in Docker, connecting via host.docker.internal) reach the
# server. Off by default — zero behaviour change for every install that
# never touches this. Same ENV > file > default precedence as
# MCP_HEADLESS above.
if "GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED" in os.environ:
    MCP_EXTRA_ALLOWED_HOSTS_ENABLED = os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS_ENABLED"].strip().lower() in ("1", "true", "yes")
else:
    MCP_EXTRA_ALLOWED_HOSTS_ENABLED = bool(_mcp_server_config.get("mcp_extra_hosts_enabled", False))

# Raw comma-separated host list — real default "host.docker.internal"
# (Timo's own Open-WebUI-in-Docker use case), same ENV > file > default
# precedence as MCP_HTTP_PORT above; "mcp_extra_hosts" key in
# MCP_SERVER_CONFIG_FILE, same dual-writer exception documented above
# MCP_SERVER_CONFIG_FILE. Only actually applied when
# MCP_EXTRA_ALLOWED_HOSTS_ENABLED is True — see clients/mcp_server.py.
if "GARMIN_MCP_EXTRA_ALLOWED_HOSTS" in os.environ:
    MCP_EXTRA_ALLOWED_HOSTS_RAW = os.environ["GARMIN_MCP_EXTRA_ALLOWED_HOSTS"]
else:
    MCP_EXTRA_ALLOWED_HOSTS_RAW = _mcp_server_config.get("mcp_extra_hosts") or "host.docker.internal"

MCP_EXTRA_ALLOWED_HOSTS = _parse_extra_hosts(MCP_EXTRA_ALLOWED_HOSTS_RAW)

# Server-owned archive path (v1.7 Teilbauauftrag f) — deliberately NOT the
# same constant as BASE_DIR above. BASE_DIR remains the pipeline's sole
# archive-path source, unchanged by this session, and is resolved once at
# module import from GARMIN_OUTPUT_DIR alone. MCP_BASE_DIR exists only for
# clients/mcp_server.py's own use when it runs without a GLA process ahead
# of it setting that ENV var — reuses the SAME "GARMIN_OUTPUT_DIR" ENV name
# as BASE_DIR (deliberate: when GLA and the MCP server share an environment,
# they should agree on one archive by default; a separate ENV for "point
# MCP at a different archive than GLA" was considered and deferred — no
# real request for it yet, and it can be added later without breaking this
# fallback chain). Falls back to MCP_SERVER_CONFIG_FILE's "base_dir" key
# (written either by panel_mcp.py's mirror-on-save, or entered directly in
# clients/mcp_server_gui.py's standalone window). Same ultimate default as
# BASE_DIR if neither ENV nor file provides a value.
if "GARMIN_OUTPUT_DIR" in os.environ:
    MCP_BASE_DIR = Path(os.environ["GARMIN_OUTPUT_DIR"]).expanduser()
else:
    MCP_BASE_DIR = Path(
        _mcp_server_config.get("base_dir") or "~/local_archive"
    ).expanduser()

# Separate plaintext config file for cloud LLM credentials (MCP_LLM_BACKEND
# = "cloud"). Path.home()-based like SETTINGS_FILE (app/garmin_app_settings.py)
# — credentials are machine-bound, not archive-bound, so BASE_DIR would be
# the wrong anchor. Deliberately separate from LOCAL_CONFIG_FILE (that is
# the context-plugin location/time-window CSV, an unrelated mechanism
# despite the similar name). Missing or empty file = cloud backend simply
# not usable, not an error — no forced setup. Plaintext with an explicit
# warning (Option B, v1.7) — WCM/AES encryption deliberately deferred to a
# later v1.7.x roadmap item, see NOTES_v1.7-vorbereitung.md.
# Existence/completeness check itself lives in clients/mcp_server.py, not
# here — this file defines paths and reads ENV only, no logic.
MCP_LLM_CONFIG_FILE = Path.home() / ".garmin_mcp_llm_config.json"
