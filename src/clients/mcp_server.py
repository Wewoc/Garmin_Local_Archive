#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
clients/mcp_server.py
Garmin Local Archive — MCP Server (v1.7 Teilbauauftrag b)

Standalone MCP server process, stdio transport. Registers the six
maps/mcp_map.py functions (query_health, query_context,
query_fit_activities, query_raw, get_archive_metadata,
list_available_fields) as MCP tools via the official mcp SDK
(mcp>=1.28,<2, verified against mcp==1.29.0).

No broker/delegation logic of its own — that lives entirely in
mcp_map.py (v1.7 Teilbauauftrag a). This module is pure MCP protocol
exposition: thin @mcp.tool() wrappers with 1:1 signatures, nothing else.

Error handling: deliberately no translation code. mcp_map.py's degraded
results ({"error": ...} inside an otherwise normal return dict) pass
through unchanged as ordinary tool payloads (isError stays False — the
LLM sees a normal result with an "error" field, exactly as designed in
Teilbauauftrag a). Genuine exceptions (ValueError from query_raw/
get_archive_metadata on an unknown domain/kind) are left unhandled here
by design — the mcp SDK automatically converts any uncaught exception
raised inside a @mcp.tool()-decorated function into
CallToolResult(isError=True, ...) with str(exception) as the message.
Wrapping these calls in try/except here would just re-implement
behaviour the SDK already provides.

Process model: standalone subprocess, analogous to
scheduler/daily_update.py — NOT an in-process thread off
garmin_app_base.py. Runs independently of the main GUI (Broker Layer
needs only the Python import path, no Qt). Uses the same sys.path
root-anchor pattern as daily_update.py, not the
frozen_paths.add_to_path() lazy-import helper from app/panel_chat.py —
that pattern is GUI-context-bound (mounts clients/ into a running Qt
process) and does not apply to a standalone script invocation.

stdio note: stdout is the protocol channel for stdio transport — never
print() here, never let a dependency write to stdout. All logging goes
to stderr.

Standalone GUI (v1.7 Teilbauauftrag f): main() always opens a Tkinter
window (clients/mcp_server_gui.py::run_gui()) — there is no headless/
console mode anymore and no enabled/disabled startup gate. Session
decision, Timo's framing: "the window is the server" — starting
mcp_server.exe means the server runs, full stop, no separate on/off
process state to reason about. garmin_config.MCP_ENABLED itself was
removed in Teil (g) once the "Start MCP Server" button replaced the
manual-start workflow the flag used to describe — no longer even a
dead config-file field, fully gone.
Boot-log setup (_setup_boot_log()) runs before anything else in main(),
including before the cloud-config check below, so import-time failures
in garmin_config or the MCP SDK are still captured somewhere on disk even
if the Tkinter window itself never manages to open.

Cloud LLM config (garmin_config.MCP_LLM_CONFIG_FILE) is checked
informationally when MCP_LLM_BACKEND="cloud" — an incomplete/missing file
is never a startup blocker, only a log line; Ollama remains the default
and stays available regardless.

Usage (T1, dev):
    python clients/mcp_server.py
"""

import json
import logging
import os
import sys
from pathlib import Path

# ── sys.path root anchor — before any project-internal import ───────────
# This script can be invoked directly (python clients/mcp_server.py) from
# any working directory, so the src/ root must be added to sys.path before
# "from maps.mcp_map import ..." can resolve — maps/ is a real package,
# reachable via src/ alone.
#
# Correction (Teilbauauftrag c): garmin_config (added this session) is a
# flat import ("import garmin_config", not "import garmin.garmin_config"),
# same style as garmin_utils/garmin_validator/etc. — it needs src/garmin/
# itself on sys.path, not just src/. The original docstring claim "same
# anchor pattern as daily_update.py" was inaccurate: daily_update.py's
# _setup_paths() adds five subfolders (garmin, maps, dashboards, layouts,
# app) individually, not just the src/ root — that's what makes its flat
# imports resolve. Adding only garmin/ here (not all five) — this module
# has no need for dashboards/layouts/app, unlike the GUI-facing daily
# sync script.
#
# Correction (Teilbauauftrag e): the above covers T1/dev only — __file__
# does not point at a real on-disk src/ tree once this script is frozen
# (T3.3, PyInstaller --onefile). Confirmed at runtime (T3.3 manual test):
# "ModuleNotFoundError: No module named 'garmin_config'". The T1 branch
# above is kept unchanged (still correct for T1); a frozen branch is
# added for T3, following garmin_app_standalone.py's
# _register_embedded_packages() pattern — the closest existing precedent,
# since it already solves the same two-part problem this module has
# (a flat single-file import for garmin_config, plus a real package
# import for maps.mcp_map). Deliberately a standalone copy, not a shared
# import: mcp_server.exe must stay runnable on its own, independent of
# garmin_app_standalone.exe/T3.1's --onedir folder layout (explicit
# requirement — MCP must work without GLA present at all). frozen_paths.
# scripts_root()/add_to_path() were considered instead but not used here:
# despite the docstring calling it "central", no existing entry point
# (daily_update.py, garmin_app_standalone.py) actually uses it for its
# own bootstrap — introducing it here would add a fourth distinct
# bootstrap pattern to the project instead of reusing one of the three
# that already exist. daily_update.py's simpler root+scripts/ pattern was
# not used either: it never imports a maps.* submodule, so it never had
# to solve the package-with-subfolder problem this module has.
_SRC_ROOT   = Path(__file__).resolve().parent.parent
_GARMIN_DIR = _SRC_ROOT / "garmin"
for _p in (_SRC_ROOT, _GARMIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _register_embedded_packages() -> None:
    """T3 only — no-op under T1/dev. Mirrors
    garmin_app_standalone.py::_register_embedded_packages(), narrowed to
    what this module actually imports (garmin_config flat, maps as a
    real package, clients/ flat for mcp_server_gui) — no app/, context/,
    dashboards/, layouts/, none of which mcp_server.py touches. A
    standalone copy, not a shared import — see comment above.

    clients/ added (v1.7 Teilbauauftrag f): main() now imports
    mcp_server_gui (from mcp_server_gui import run_gui) — under T1/dev
    this resolves for free via Python's automatic sys.path[0] = script
    directory, which does not apply once frozen (sys.argv[0] points at
    the PyInstaller bootloader temp path, not the source tree). Same
    flat-import treatment as garmin_dir below — mcp_server_gui.py sits
    directly in scripts/clients/, not nested as its own package."""
    if not getattr(sys, "frozen", False):
        return
    import types
    scripts = Path(sys._MEIPASS) / "scripts"
    garmin_dir = scripts / "garmin"
    if garmin_dir.exists() and str(garmin_dir) not in sys.path:
        sys.path.insert(0, str(garmin_dir))
    clients_dir = scripts / "clients"
    if clients_dir.exists() and str(clients_dir) not in sys.path:
        sys.path.insert(0, str(clients_dir))
    maps_dir = scripts / "maps"
    if maps_dir.exists() and "maps" not in sys.modules:
        mod = types.ModuleType("maps")
        mod.__path__    = [str(maps_dir)]
        mod.__package__ = "maps"
        sys.modules["maps"] = mod


_register_embedded_packages()

# ── Logging — stderr only ────────────────────────────────────────────────
# stdio transport uses stdout as the wire protocol channel. Any stray
# print() or stdout-bound log line corrupts the MCP message stream from
# the client's perspective. logging is configured to stderr before any
# other project import runs, in case an imported module logs at import
# time.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

import garmin_config as cfg  # noqa: E402 — after path/logging setup

from mcp.server.fastmcp import FastMCP  # noqa: E402 — after path/logging setup

from maps import mcp_map  # noqa: E402 — after path/logging setup


def _setup_boot_log() -> logging.FileHandler:
    """Attaches a FileHandler next to MCP_SERVER_CONFIG_FILE
    (~/.garmin_mcp_server_boot.log) to the root logger — captures
    everything from process start until the operational log (inside the
    archive, once MCP_BASE_DIR/base_dir is confirmed reachable) takes
    over. No rotation: each run overwrites the previous boot attempt —
    only the most recent start matters for diagnosing a failed launch,
    unlike the operational log's rolling history. Returns the handler so
    the caller (main(), then later mcp_server_gui.py once the operational
    log is up) can remove it — no permanent duplication between boot log
    and operational log, per session decision (v1.7 Teilbauauftrag f)."""
    boot_log_path = cfg.MCP_SERVER_CONFIG_FILE.parent / ".garmin_mcp_server_boot.log"
    handler = logging.FileHandler(boot_log_path, mode="w", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def _write_lock_file() -> None:
    """Writes this process's PID to garmin_config.MCP_SERVER_LOCK_FILE —
    lets app/panel_mcp.py's "Start MCP Server" button check whether an
    instance is already running before launching a new one (v1.7
    Teilbauauftrag g). Deliberately no exception handling beyond a log
    line: a failed write here means the liveness check on the
    panel_mcp.py side will simply find no lock file and allow a start —
    the same fail-open behaviour as a missing file for any other reason
    (first run, file manually deleted). Not a security boundary, just a
    best-effort convenience check — see module note in garmin_config.py
    for why this is a plain PID file rather than a Qt-based guard."""
    try:
        cfg.MCP_SERVER_LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write lock file %s: %s",
                        cfg.MCP_SERVER_LOCK_FILE, exc)


def _cloud_llm_config_available() -> bool:
    """True if MCP_LLM_CONFIG_FILE exists and has non-empty required values
    (provider, api_key, model). False (not an error) if missing, empty, or
    incomplete — Option 2 (cloud LLM backend) simply isn't usable; Ollama
    remains available regardless."""
    try:
        data = json.loads(cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return bool(data.get("provider")) and bool(data.get("api_key")) \
        and bool(data.get("model"))


mcp = FastMCP("Garmin Local Archive")

# Tool names are aliased 1:1 to mcp_map.py's function names (no "_tool"
# suffix, no technical wrapper naming) — the MCP tool name is what the LLM
# sees and reasons about, so it should read as a domain question
# ("query_health"), not an implementation detail. Matches the naming
# convention observed across the MCP ecosystem (e.g. eddmann/garmin-
# connect-mcp, official SDK examples) and the "fachlich benannte Tools"
# decision from NOTES_v1.7-vorbereitung.md. The module-qualified
# mcp_map.query_health(...) call inside each wrapper avoids the name
# collision that a direct `from maps.mcp_map import query_health` plus a
# same-named @mcp.tool() def in this module would otherwise cause.


@mcp.tool()
def query_health(field: str, date_from: str, date_to: str,
                  resolution: str = "daily") -> dict:
    """Query Garmin health data (e.g. heart rate, sleep, stress, body
    battery) for a field over a date range. resolution is "daily" or
    "intraday"."""
    return mcp_map.query_health(field, date_from, date_to, resolution)


@mcp.tool()
def query_context(field: str, date_from: str, date_to: str,
                   resolution: str = "daily") -> dict:
    """Query external context data (weather, pollen, air quality) for a
    field over a date range. Fans out across all sources that recognize
    the field."""
    return mcp_map.query_context(field, date_from, date_to, resolution)


@mcp.tool()
def query_fit_activities(field: str, date_from: str, date_to: str,
                          resolution: str = "daily") -> dict:
    """Query FIT activity data for a field over a date range. Not yet
    available (FIT pipeline is v1.8) — returns a clean "not available"
    result until then, never an error."""
    return mcp_map.query_fit_activities(field, date_from, date_to, resolution)


@mcp.tool()
def query_raw(field: str, date_from: str, date_to: str,
              domain: str | None = None) -> dict:
    """Query raw, unprocessed archive data for a passthrough field over a
    date range. domain restricts the query to one domain ("health",
    "fit", "context") — omit to search all domains."""
    return mcp_map.query_raw(field, date_from, date_to, domain=domain)


@mcp.tool()
def get_archive_metadata(kind: str) -> dict:
    """Request archive-state metadata — not a time series. kind selects
    the artefact (e.g. coverage stats, device table, quality log)."""
    return mcp_map.get_archive_metadata(kind)


@mcp.tool()
def list_available_fields(domain: str | None = None) -> dict:
    """List all queryable fields, grouped by domain and source. Use this
    first if the set of available fields is unknown — omit domain for a
    full overview, or pass "health"/"context"/"fit" to narrow it."""
    return mcp_map.list_available_fields(domain)


def main() -> None:
    boot_handler = _setup_boot_log()
    logger.info("mcp_server.exe starting — boot log at %s",
                cfg.MCP_SERVER_CONFIG_FILE.parent / ".garmin_mcp_server_boot.log")

    _write_lock_file()

    if cfg.MCP_LLM_BACKEND == "cloud" and not _cloud_llm_config_available():
        logger.warning(
            "MCP_LLM_BACKEND=cloud but %s is missing or incomplete — "
            "cloud backend not usable, Ollama remains the fallback",
            cfg.MCP_LLM_CONFIG_FILE,
        )

    # Lazy import — mcp_server_gui.py needs this module's sys.path setup
    # (T1 anchor / _register_embedded_packages()) to already have run,
    # same reasoning as garmin_config/mcp/maps imports above being
    # deferred past the logging setup.
    from mcp_server_gui import run_gui
    run_gui(mcp, logger, boot_handler)


if __name__ == "__main__":
    main()
