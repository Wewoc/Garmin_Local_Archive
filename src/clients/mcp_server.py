#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_server.py
Garmin Local Archive — MCP Server (v1.7.0.1 — HTTP transport)

Standalone MCP server process, streamable-http transport (v1.7.0.1,
replacing the original stdio transport from v1.7 Teilbauauftrag b).
Registers the six maps/mcp_map.py functions (query_health, query_context,
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

Transport (v1.7.0.1): mcp.run(transport="streamable-http"), host/port
set on the FastMCP constructor — host/port are constructor arguments for
this SDK, not run() arguments (verify against the installed mcp package
version with `pip show mcp` before relying on this if the SDK is ever
upgraded — see NOTES_v1.7.0.1vorbereitung.md, Eckpunkt 1). Host is
hardcoded "127.0.0.1", not configurable — a deliberate security boundary
(see garmin_config.py's MCP_HTTP_PORT comment). Port is
garmin_config.MCP_HTTP_PORT (ENV > config file > default 8756). stdout
is no longer a reserved protocol channel under HTTP — the "never
print()" rule from the stdio era is no longer a correctness requirement,
but all logging still goes to stderr regardless (no reason to change a
working, harmless convention).

Extra allowed hosts (v1.7.0.2): the DNS-rebinding allowed_hosts/
allowed_origins check below is a separate mechanism from the hardcoded
bind host above — it validates the incoming Host/Origin headers, not
which network interface this process listens on; 127.0.0.1 stays the
only bind address either way, unaffected by this. garmin_config.
MCP_EXTRA_ALLOWED_HOSTS_ENABLED (off by default, opt-in via
app/panel_mcp.py or clients/mcp_server_gui.py) adds garmin_config.
MCP_EXTRA_ALLOWED_HOSTS on top of the SDK's own 127.0.0.1/localhost/::1
defaults — added for Open WebUI running in Docker, reachable only via
host.docker.internal (not 127.0.0.1) from inside its container (real
"Invalid Host header: host.docker.internal:<port>" rejection observed
in clients/mcp_server_gui.py's log — see NOTES_v1.7.0.2.md). When the
flag is off, transport_security=None is passed unchanged, so the SDK's
own localhost-only default branch still applies exactly as before —
zero behaviour change for any install that never enables this. Origin-
header handling deliberately not extended alongside this (see
NOTES_v1.7.0.2.md) — Section 8's _validate_origin() passes any request
with no Origin header at all, which a server-to-server client like Open
WebUI's backend is not expected to send; revisit only if a real Origin
rejection shows up in the log, same evidence-first approach as this
whole fix.

Startup mode (v1.7.0.1 — corrected after an initial misreading of
Eckpunkt 6, see NOTES_v1.7.0.1vorbereitung.md): the window stays the
DEFAULT entry point, coupled to the server exactly as under v1.7
Teilbauauftrag f's "the window is the server" (window closed = process
closed) — Timo's explicit decision was to keep that coupling, only the
transport and the restart-health-check mechanism change. main() opens
clients/mcp_server_gui.py::run_gui(), which starts the HTTP server in a
daemon thread and blocks in Tkinter's mainloop() on this thread, unless
garmin_config.MCP_HEADLESS is true (new config field, ENV/config-file
driven, NOT a CLI flag) — in that case main() calls _run_headless()
below instead: no window at all, mcp.run() blocks directly on this
thread, analogous to scheduler/daily_update.py. MCP_HEADLESS is
settable from both app/panel_mcp.py (GLA-integrated case) and this
window itself (clients/mcp_server_gui.py — takes effect on the next
start, not the running instance; primarily for the standalone case,
mcp_server.exe with no GLA installation present).

No process-liveness lockfile anymore (v1.7.0.1 — garmin_config.
MCP_SERVER_LOCK_FILE removed). A second instance now fails naturally
with OSError when it cannot bind 127.0.0.1:MCP_HTTP_PORT — caught in
_run_headless() below (and inside run_gui()'s server thread for the
windowed case) and logged, no separate pre-flight check needed
(Eckpunkt 4a, Fall 1: "AddressInUse ersetzt Lockfile"). This also
replaces the mcp_server_gui.py restart-confirmation poll, which now
does a TCP-connect-ping loop against the port instead of watching a
lockfile for a new PID (Eckpunkt 4a, Fall 2).

Boot-log setup (_setup_boot_log()) runs before anything else in main(),
including before the cloud-config check below, so import-time failures
in garmin_config or the MCP SDK are still captured somewhere on disk.
The operational log (inside the archive, rotating —
_start_operational_log() below) replaces the boot log once
MCP_BASE_DIR is confirmed reachable — no permanent duplication between
the two, same "one active destination at a time" rule as before. This
function lives here (not in mcp_server_gui.py, unlike pre-v1.7.0.1)
because BOTH the headless and windowed paths need it now; it is passed
into run_gui() as a plain callable rather than imported back from
mcp_server_gui.py, to avoid a circular import (this module already
imports mcp_server_gui.py to call run_gui()).

Cloud LLM config (garmin_config.MCP_LLM_CONFIG_FILE) is checked
informationally when MCP_LLM_BACKEND="cloud" — an incomplete/missing file
is never a startup blocker, only a log line; Ollama remains the default
and stays available regardless.

Usage (T1, dev):
    python clients/mcp_server.py     # opens the window (default) or runs
                                      # headless, per garmin_config.MCP_HEADLESS
"""

import difflib
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

    clients/ added (v1.7 Teilbauauftrag f): main() imports mcp_server_gui
    (from mcp_server_gui import run_gui, lazily, in the non-headless
    branch — the default) — under T1/dev this resolves for free via
    Python's automatic sys.path[0] = script directory, which does not
    apply once frozen (sys.argv[0] points at the PyInstaller bootloader
    temp path, not the source tree). Same flat-import treatment as
    garmin_dir below — mcp_server_gui.py sits directly in
    scripts/clients/, not nested as its own package."""
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
# HTTP transport does not reserve stdout as a wire protocol channel the
# way stdio did (v1.7.0.1) — but logging stays on stderr regardless, a
# harmless, working convention with no reason to change. logging is
# configured before any other project import runs, in case an imported
# module logs at import time.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ── ENV setup — before garmin_config import (v1.7.0.3) ───────────────────
# garmin_config.BASE_DIR (and everything derived from it: LOG_DIR, RAW_DIR,
# SUMMARY_DIR, CONTEXT_DIR, ...) is resolved once at import time from
# GARMIN_OUTPUT_DIR alone — same caching-at-import-time behaviour
# scheduler/daily_update.py already documents and works around at its own
# Schritt 3 ("Gap detection needs garmin_quality which needs garmin_config
# which reads ENVs. Set a minimal ENV first so quality log path resolves
# correctly."). Without this, a standalone mcp_server.exe (no GLA process
# ahead of it to set GARMIN_OUTPUT_DIR) falls through to BASE_DIR's
# hardcoded default (~/local_archive) for every archive read — while
# garmin_config.MCP_BASE_DIR (used only for this module's own operational-
# log path and the GUI's Archive-path display, see mcp_server_gui.py)
# resolves correctly from the same config file, producing a silent
# divergence between what is shown and what is actually read
# (NOTES_v1.7.0.3.md — device_table read failure was the first symptom
# that surfaced this).
#
# Reads MCP_SERVER_CONFIG_FILE directly rather than importing garmin_config
# first and reading cfg.MCP_BASE_DIR — the whole point is to set the ENV
# var *before* that import, not after. This narrowly duplicates three
# lines of garmin_config._read_mcp_server_config()'s fallback shape;
# unavoidable, since garmin_config is not importable yet at this point.
# Guarded by "not already set" so an external GARMIN_OUTPUT_DIR (e.g. a
# future in-process/shared-environment scenario) always wins over the
# config file, same ENV > file > default precedence used everywhere else
# in this project.
if "GARMIN_OUTPUT_DIR" not in os.environ:
    _mcp_config_path = Path.home() / ".garmin_mcp_server_config.json"
    try:
        _saved_config = json.loads(_mcp_config_path.read_text(encoding="utf-8"))
        _saved_base_dir = _saved_config.get("base_dir")
        if _saved_base_dir:
            os.environ["GARMIN_OUTPUT_DIR"] = _saved_base_dir
    except (FileNotFoundError, ValueError):
        pass

import garmin_config as cfg  # noqa: E402 — after path/logging/ENV setup

from mcp.server.fastmcp import FastMCP  # noqa: E402 — after path/logging setup
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from maps import mcp_map  # noqa: E402 — after path/logging setup

# Absolute import, not "from . import mcp_update" (v1.7.1 fix) —
# mcp_server.py is invoked as a standalone script
# (python clients/mcp_server.py, or mcp_server.exe under T3.3), not
# imported as part of a package, so __package__ is empty at this point
# and a relative import raises "attempted relative import with no
# known parent package" (confirmed via test_all run, 2026-08-27). The
# clients/ directory is already reachable on sys.path — the same
# implicit sys.path[0] = script-directory mechanism the module
# docstring already documents for mcp_server_gui.py's own lazy import
# further down (see "Startup mode" in the module docstring above) —
# so a flat "import mcp_update" resolves the same way, no additional
# path setup needed.
import mcp_update  # noqa: E402 — after path/logging setup, v1.7.1

# Same flat-import treatment as mcp_update above — this module is
# invoked as a standalone script, and mcp_sql.py is itself only ever
# loaded via mcp_update.py's own flat "import mcp_sql" (see that
# module's docstring), so it is already resolvable on sys.path by the
# time this import runs. v1.7.1.1 — needed here for _route_query()'s
# SQLite-branch calls (get_health_range()/get_context_range()/
# get_raw_range()/get_metadata_range()) below.
import mcp_sql  # noqa: E402 — after path/logging setup, v1.7.1.1


def _setup_boot_log() -> logging.FileHandler:
    """Attaches a FileHandler next to MCP_SERVER_CONFIG_FILE
    (~/.garmin_mcp_server_boot.log) to the root logger — captures
    everything from process start until the operational log (inside the
    archive, once MCP_BASE_DIR/base_dir is confirmed reachable) takes
    over. No rotation: each run overwrites the previous boot attempt —
    only the most recent start matters for diagnosing a failed launch,
    unlike the operational log's rolling history. Returns the handler so
    the caller (main()) can remove it once the operational log is up —
    no permanent duplication between boot log and operational log, per
    session decision (v1.7 Teilbauauftrag f)."""
    boot_log_path = cfg.MCP_SERVER_CONFIG_FILE.parent / ".garmin_mcp_server_boot.log"
    handler = logging.FileHandler(boot_log_path, mode="w", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


LOG_MCP_MAX = 30  # rolling log file limit, same convention as
                  # garmin_config.LOG_RECENT_MAX / daily_update.LOG_DAILY_MAX

# ── Kategorie-Buendel fuer query_context() (v1.7.1.5) ────────────────────
#
# Ordnet einen Kategorienamen (z.B. "weather") einer PRIORISIERTEN LISTE
# von context_map-Quellennamen zu. Die Feldnamen jeder Quelle werden NICHT
# hier gepflegt -- sie werden zur Laufzeit ueber mcp_map.list_available_
# fields(domain="context") ermittelt (nicht direkt aus maps.context_map --
# clients/ spricht die Broker-Schicht ausschliesslich ueber mcp_map an,
# siehe NOTES_v1.7.1.5.md), damit neue Einzelfelder innerhalb einer bereits
# gelisteten Quelle automatisch im Buendel erscheinen, ohne dass diese
# Liste angefasst werden muss.
#
# REIHENFOLGE = PRIORITAET bei Namenskollision zwischen zwei Quellen
# desselben Buendels (aktuell nur "wind_speed_max" bei weather/brightsky,
# siehe context_map.py-Docstring): bei einer Kollision gewinnt fuer jeden
# Tag einzeln die ERSTE Quelle in dieser Liste, die fuer diesen Tag
# tatsaechlich einen Wert (nicht None) liefert -- liefert sie keinen,
# entscheidet die naechste Quelle in der Liste. Kollisionserkennung ist
# rein namensbasiert (gleicher Feldname in mehreren Quellen desselben
# Buendels) -- kein Mapping/keine Aehnlichkeitspruefung zwischen
# UNTERSCHIEDLICHEN Feldnamen (bewusst verworfen, siehe
# KONZEPT_query_context_kategorie_aufloesung.md, Abschnitt "Warum keine
# allgemeine Feld-Mapping-Tabelle").
#
# Neue Quelle hinzufuegen (z.B. ein US-Anbieter):
#   1. Quellennamen an der gewuenschten Prioritaets-Position eintragen.
#   2. Nur falls die neue Quelle ein bereits vorhandenes Feld dieses
#      Buendels unter demselben Namen fuehrt (echte Kollision): Position
#      in der Liste bestimmt automatisch die Prioritaet -- keine
#      zusaetzliche Regel noetig.
_CONTEXT_CATEGORY_BUNDLES = {
    "weather": ["brightsky", "weather"],  # Messstation vor Modell
    "pollen":  ["pollen"],
    "air":     ["airquality"],
}


def _start_operational_log(base_dir: Path) -> logging.FileHandler | None:
    """Creates <base_dir>/garmin_data/log/mcp/mcp_YYYY-MM-DD_HHMMSS.log,
    attaches a FileHandler to the root logger, and prunes older files
    beyond LOG_MCP_MAX — same rotation shape as daily_update.py's
    _start_daily_log(). Returns None (not an error) if base_dir is not
    writable — the boot log remains the only destination in that case;
    the caller decides whether to warn.

    Lives here rather than in mcp_server_gui.py (unlike pre-v1.7.0.1)
    because both the headless path (_run_headless() below) and the
    windowed path (mcp_server_gui.py::run_gui()) need it — passed into
    run_gui() as a plain callable to avoid a circular import (this
    module already imports mcp_server_gui.py to call run_gui())."""
    import datetime

    log_dir = base_dir / "garmin_data" / "log" / "mcp"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = log_dir / f"mcp_{timestamp}.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)

    # Prune — oldest first, same glob+mtime pattern as daily_update.py.
    logs = sorted(log_dir.glob("mcp_*.log"), key=lambda f: f.stat().st_mtime)
    for old in logs[:-LOG_MCP_MAX] if len(logs) > LOG_MCP_MAX else []:
        try:
            old.unlink()
        except OSError:
            pass

    return handler


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


def _run_startup_sync() -> None:
    """
    SQLite proxy boot sync (v1.7.1) — runs synchronously, blocking,
    before mcp.run() is reached on either startup path (headless or
    windowed). A single named function called once from main(), before
    the MCP_HEADLESS branch — both _run_headless() below and
    mcp_server_gui.py::run_gui() (called from the windowed branch) then
    proceed unchanged afterwards, so this logic lives in exactly one
    place rather than being duplicated into mcp_server_gui.py (Timo
    decision, NOTES_v1.7.1_session2.md).

    Result is logged only — the LLM is not connected yet at this point
    in either startup path (mcp.run() has not been reached). The same
    mcp_update.sync_all() mechanism, called again later via the
    refresh_cache() tool below, returns its result directly to the LLM
    instead — one shared sync mechanism, two callers that now pass a
    different is_boot value (2026-08-28 correction: the port-bind
    concurrency guard inside sync_all() only makes sense here, before
    mcp.run() has bound the port — see mcp_update.py's module docstring
    for the full diagnosis).

    A failure here is not caught — an unusable SQLite cache at boot is
    surfaced immediately in the boot log rather than silently starting
    an MCP server whose refresh_cache() tool would then also fail on
    first use.
    """
    logger.info("Starting SQLite proxy boot sync...")
    result = mcp_update.sync_all(is_boot=True)
    logger.info("Boot sync complete: %s", result)


# Same three localhost patterns the mcp SDK (mcp.server.fastmcp.server,
# verified against the installed mcp==1.29.0 source) builds automatically
# when transport_security=None and host is 127.0.0.1/localhost/::1 —
# passing an explicit TransportSecuritySettings below skips that
# automatic branch entirely, so these three are duplicated here
# deliberately (no SDK-exposed constant to import instead). Recheck
# against the SDK source if the installed mcp package version ever
# changes (see module docstring's existing "pip show mcp" note).
_DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_DEFAULT_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

# ══════════════════════════════════════════════════════════════════════════════
#  Field units (v1.7.1.6) — deliberate MCP-local stopgap, see KNOWN_ISSUES.md
#  Cluster F for the follow-up note.
# ══════════════════════════════════════════════════════════════════════════════
#
# Values transcribed from REFERENCE_BROKER.md's "Field index" table
# (health_map/garmin + context_map's four sources), verified against
# REFERENCE_GARMIN.md/REFERENCE_CONTEXT.md, 2026-08-31 (v1.7.1.6 Session 2).
# Every registered query_health()/query_context() field has an entry —
# no exceptions, including fields with no physical unit (e.g. "index",
# "text", "—") — a mixed state (some fields with unit, some without)
# would itself be a new, unpredictable source of LLM misinterpretation
# (Timo, Session 1 decision). Raw-passthrough fields (query_raw(), 13
# fields, no unit concept — see REFERENCE_GARMIN.md "Raw-passthrough
# fields") are deliberately NOT included here — out of this session's
# scope.
#
# Deliberately NOT placed in maps/health_map.py, maps/context_map.py,
# or maps/gateway_map.py: this session confirmed (DEPS-Scan v1716_02)
# that neither module currently holds a reusable unit/label structure,
# and _route_query()'s SQLite branch (currently the only branch ever
# taken, see _route_query() below) never touches maps/mcp_map.py at
# all — a unit lookup placed there would silently do nothing for every
# real request today. This dict and its two helper functions below are
# therefore intentionally kept MCP-local (clients/mcp_server.py), but
# isolated behind _get_field_unit()'s narrow signature so a future
# broker-level replacement (e.g. health_map.list_field_units()) only
# requires swapping that one function's body — no caller here or
# elsewhere needs to change. See NOTES_v1716_session2.md for the full
# reasoning trail (an mcp_map.py-based design was considered first and
# rejected for the same two reasons).
FIELD_UNITS: dict[str, str] = {
    # ── health_map -> garmin (25 fields, REFERENCE_BROKER.md) ────────────────
    "hrv_last_night":        "ms",
    "resting_heart_rate":    "bpm",
    "spo2_avg":              "%",
    "sleep_duration":        "hours",
    "body_battery_max":      "0–100",
    "stress_avg":            "0–100",
    "vo2max":                "—",
    "sleep_score":           "0–100",  # v1.7.1.6 — pre-existing REFERENCE_BROKER.md/
                                        # REFERENCE_GARMIN.md gap closed this session,
                                        # see doc anchor delivery for the table row.
    "sleep_score_feedback":  "text",
    "sleep_score_qualifier": "text",
    "sleep_deep_pct":        "%",
    "sleep_light_pct":       "%",
    "sleep_rem_pct":         "%",
    "sleep_awake_pct":       "%",
    "heart_rate_series":     "bpm",
    "stress_series":         "0–100",
    "spo2_series":           "%",
    "body_battery_series":   "0–100",
    "respiration_series":    "—",  # unit not fixed in source docs, see REFERENCE_GARMIN.md
    "steps_series":          "steps",
    "body_weight":           "grams",
    "calories_resting":      "kcal",
    "hydration_ml":          "ml",
    "endurance_score":       "index",
    "hill_score":            "index",
    "fitness_age":           "years",

    # ── context_map -> weather (6 fields) ─────────────────────────────────────
    "temperature_max":       "°C",
    "temperature_min":       "°C",
    "precipitation":         "mm",
    "wind_speed_max":        "km/h",  # also registered by brightsky, same unit —
                                        # see context_map.py's documented naming collision
    "uv_index_max":          "index",
    "sunshine_duration":     "seconds",

    # ── context_map -> pollen (6 fields) ──────────────────────────────────────
    "pollen_birch":          "grains/m³",
    "pollen_grass":          "grains/m³",
    "pollen_alder":          "grains/m³",
    "pollen_mugwort":        "grains/m³",
    "pollen_olive":          "grains/m³",
    "pollen_ragweed":        "grains/m³",

    # ── context_map -> brightsky (9 fields) ───────────────────────────────────
    "temperature_avg":       "°C",
    "humidity_avg":          "%",
    "precipitation_sum":     "mm",
    "sunshine_sum":          "min",
    "wind_gust_max":         "km/h",
    "cloud_cover_avg":       "%",
    "pressure_avg":          "hPa",
    "condition":             "text",

    # ── context_map -> airquality (5 fields) ──────────────────────────────────
    "airquality_pm2_5":             "μg/m³",
    "airquality_pm10":              "μg/m³",
    "airquality_european_aqi":      "index",
    "airquality_nitrogen_dioxide":  "μg/m³",
    "airquality_ozone":             "μg/m³",
}


def _get_field_unit(field: str) -> str:
    """Single lookup point for a field's display unit. Isolated on
    purpose (see FIELD_UNITS' module comment above) — the only place
    that needs to change when this stopgap is replaced by a broker-level
    unit registry. Unknown field (should not occur for a field that
    already passed query_health()/query_context()'s own field-validity
    checks) -> "—" rather than a KeyError, so a future new field that is
    not yet in FIELD_UNITS degrades to "no unit shown" instead of
    breaking the whole response."""
    return FIELD_UNITS.get(field, "—")


def _enrich_with_units(result: dict, domain: str) -> dict:
    """Adds a "unit" key to every per-field dict inside result[domain],
    in place, and returns result for call-site chaining. Handles both
    shapes query_health()/query_context() can produce under
    result[domain]:
      - {source: {field: {"values": ..., ...}}}   (normal per-source shape)
      - {field: {"values": ..., ...}}              (already-flattened
        shape, e.g. _resolve_context_bundle()'s output)
    A per-field dict is recognized by the presence of "values" — the one
    key REFERENCE_BROKER.md guarantees on every field-level dict
    regardless of domain or source, daily or intraday/live. Not
    recursive beyond one extra level, since no third shape currently
    exists in this codebase; see FIELD_UNITS' module comment for the
    planned replacement path if that ever changes."""
    domain_dict = result.get(domain)
    if not isinstance(domain_dict, dict):
        return result

    for key, value in domain_dict.items():
        if not isinstance(value, dict):
            continue
        if "values" in value:
            # Already-flattened shape: key IS the field name.
            value["unit"] = _get_field_unit(key)
        else:
            # Normal per-source shape: key is a source name, value's
            # own keys are field names.
            for field_name, field_dict in value.items():
                if isinstance(field_dict, dict) and "values" in field_dict:
                    field_dict["unit"] = _get_field_unit(field_name)

    return result


mcp = FastMCP(
    "Garmin Local Archive",
    host="127.0.0.1",
    port=cfg.MCP_HTTP_PORT,
    transport_security=(
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_DEFAULT_ALLOWED_HOSTS + cfg.MCP_EXTRA_ALLOWED_HOSTS,
            allowed_origins=_DEFAULT_ALLOWED_ORIGINS,
        )
        if cfg.MCP_EXTRA_ALLOWED_HOSTS_ENABLED
        else None
    ),
)

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

# ══════════════════════════════════════════════════════════════════════════════
#  Routing weiche (v1.7.1.1 Ziel 5) — placeholder, no real heuristic yet
# ══════════════════════════════════════════════════════════════════════════════
#
# TODO v1.7.x — real heuristic after a measurement tool compares SQLite
# vs. live cost/staleness (explicitly out of scope this session, see
# NOTES_v1.7.1.1_session2.md). Fixed return "sqlite" for every kind —
# analogous to gateway_map._DOMAIN_BROKERS['fit': None]'s "Stöpsel"
# precedent: the decision point exists and is called from every one of
# the six query tools below, but carries no actual logic yet, so a
# later heuristic only has to change this one function's body, never
# any call site.
#
# All six query tools route through this — refresh_cache() does NOT
# (Ziel 6, verified separately): it is a sync trigger, not a data
# query, so it is categorically not a routing candidate (Timo,
# NOTES_v1.7.1.1_session2.md — "refresh cache soll ja nicht auf die
# sql db gehen sondern mcp_delta triggern").
#
# query_fit_activities is included, not excluded (Timo, same NOTES
# section: "der fit teil soll wenn er da ist auch in die sql db... von
# daher würde ich das auch mit in die weiche nehmen") — its "sqlite"
# branch below calls mcp_map.query_fit_activities() directly rather
# than a not-yet-existing mcp_sql.get_fit_range(), i.e. it currently
# returns the identical degraded {"fit": {"error": "domain not yet
# available"}, ...} result on both branches of the if/else — the same
# "Stöpsel statt Vollintegration" principle KONZEPT_mcp_sqlite_proxy_V2.md
# already documents for FIT elsewhere in this project, applied here to
# the routing weiche's SQLite branch specifically. Once fit_map.py and
# mcp_sql.get_fit_range() exist (v1.8), only that one branch needs to
# change — the weiche itself, and every wrapper's call to it, stays
# unchanged.


# v1.7.1.9 Session 2 -- explicit short-form alias mapping for
# query_health(). See query_health()'s own docstring for the full
# rationale (structural difflib limitation, not a tuning gap) and
# NOTES_v1.7.1.9.md Session 2 for the per-candidate verification
# against the real, current health field registry. "spo2" deliberately
# excluded -- see the same notes for the collision analysis.
HEALTH_FIELD_ALIASES: dict[str, str] = {
    "steps": "steps_series",
    "hrv": "hrv_last_night",
    "hill": "hill_score",
}


# v1.7.1.12 -- fields where the requested short form does not reveal
# whether a daily value or a _series (timeseries) was meant, same
# principle as CONTEXT_FIELD_AMBIGUOUS (see that table's own comment
# for the full rationale -- reuse of the existing error/did_you_mean
# schema, no new response shape, no majority-default alias).
#
# Discovered this session (NOT part of the original v1.7.1.9 alias
# work): lowering cutoff to 0.65 (v1.7.1.11 Session 5) unintentionally
# undermined the v1.7.1.9 Session 2 decision to keep "spo2" unresolved
# -- at cutoff=0.8 the exclusion held implicitly (no match at all); at
# 0.65 "spo2" now matches exactly one candidate (spo2_avg), so the
# existing len(close_matches) == 1 auto-resolve branch silently fires
# for a case the architecture explicitly wanted left alone. A systematic
# scan of all 26 registered health fields at cutoff=0.65 (every prefix
# with an _avg/_series/_max/_pct sibling, existing HEALTH_FIELD_ALIASES
# short forms steps/hrv/hill excluded as already resolved) found one
# more case with the identical shape: "stress" matches uniquely to
# stress_avg, though stress_avg/stress_series are just as co-equal as
# spo2_avg/spo2_series. "respiration" was checked and deliberately NOT
# included -- only one target (respiration_series) exists for that
# prefix, no ambiguity, the existing auto-resolve there is correct and
# unaffected. "body_battery", "heart_rate", "sleep_deep", "sleep_rem"
# were also checked -- all already fall through correctly to the
# generic unknown-field error (2-3 close matches each, auto-resolve
# condition not met), no change needed for those.
HEALTH_FIELD_AMBIGUOUS: dict[str, list[str]] = {
    "spo2": ["spo2_avg", "spo2_series"],
    "stress": ["stress_avg", "stress_series"],
}


# v1.7.1.12 -- explicit alias mapping for query_context(), same pattern
# as HEALTH_FIELD_ALIASES above (structural difflib limitation, not a
# tuning gap -- see query_context()'s own docstring and NOTES_v1.7.1.12.md
# for the full analysis and Lauf 11/12/12b test-run background). All 36
# entries are requested->expected discrepancies actually observed in
# Lauf 11 (7 models, cutoff 0.8) and Lauf 12b (2 models, cutoff 0.65),
# individually re-verified against the current context field registry
# before inclusion -- not taken over 1:1 from the raw candidate list.
#
# Four candidates from the original 66-entry raw list were deliberately
# NOT included, kept as an open item rather than silently dropped (see
# NOTES_v1.7.1.12.md "Ziel 1" section for the per-case reasoning):
#   "ozone" (x3) -> would alias to airquality_ozone_series, but shares
#     the same daily/series ambiguity as the CONTEXT_FIELD_AMBIGUOUS
#     entries below -- inconsistent to resolve unilaterally here while
#     pm25/pm10/no2/etc. get a rückfrage instead.
#   "pollen_pollen_airborne" (x1) -> proposed target (pollen_mugwort_
#     series) is not recoverable from the requested name itself, same
#     failure mode as the 3 candidates already rejected in Lauf 11
#     Appendix A (ragweed/pollen_elm/pollen_series mis-mappings).
#   "air_quality_pm2_5" (x1) -> proposed _series target has no _series
#     signal in the requested name; pm2_5 itself is a known ambiguity
#     case (see CONTEXT_FIELD_AMBIGUOUS), no reason this variant should
#     resolve unambiguously where the bare form does not.
#   "weather_summary" (x1) -> proposed target (condition_series)
#     contradicts the word itself ("summary" suggests a daily aggregate,
#     not a timeseries).
#
# "temperature" and "sun" deliberately excluded (per Lauf 11 Appendix A
# and confirmed in this session): temperature has three co-equal daily
# targets (_min/_max/_avg), sun is too short/generic with collision risk.
CONTEXT_FIELD_ALIASES: dict[str, str] = {
    # -- Cutoff-0.65 auto-resolve mistakes, promoted to explicit aliases
    #    (v1.7.1.11 Session 5 / Lauf 12b, individually traced to
    #    _meta.field_resolved_from root cause, not estimated) --
    "humidity": "humidity_avg",
    "pressure": "pressure_avg",
    "air_pressure": "pressure_avg",
    "wind_speed": "wind_speed_max",

    # -- Multi-observation candidates (x9 down to x2), Lauf 11 Appendix A --
    "pollen_grass_hourly": "pollen_grass_series",
    "sunshine_total": "sunshine_sum",
    "european_aqi": "airquality_european_aqi",
    "min_temperature": "temperature_min",
    "pollen_alder_hourly": "pollen_alder_series",
    "olive_pollen": "pollen_olive",
    "ragweed_pollen": "pollen_ragweed",
    "max_wind_speed_dwd": "wind_speed_max",
    "pm25_series": "airquality_pm2_5_series",
    "pm10_series": "airquality_pm10_series",
    "max_wind_speed": "wind_speed_max",
    "grass_pollen": "pollen_grass",
    "airquality_o3_series": "airquality_ozone_series",
    "uv_max": "uv_index_max",
    "alder_pollen": "pollen_alder",
    "avg_cloud_cover": "cloud_cover_avg",
    "avg_pressure": "pressure_avg",
    "airquality_no2_series": "airquality_nitrogen_dioxide_series",
    "airquality_no2": "airquality_nitrogen_dioxide",
    "mugwort_pollen": "pollen_mugwort",
    "max_wind_gust": "wind_gust_max",
    "weather_condition": "condition",
    "max_temperature": "temperature_max",
    "pollen_birch_hourly": "pollen_birch_series",
    "european_aqi_series": "airquality_european_aqi_series",
    "pollen_olive_hourly": "pollen_olive_series",
    "pollen_ambrosia": "pollen_ragweed_series",
    "avg_humidity": "humidity_avg",
    "sunshine_minutes": "sunshine_sum",
    "avg_temperature": "temperature_avg",

    # -- x1 candidates, individually re-verified this session --
    "wind_max": "wind_speed_max",
    "rain_sum": "precipitation_sum",
    "air_pressure_series": "pressure_avg_series",
    "weather_series": "condition_series",
    "ozon": "airquality_ozone",  # deutsche Schreibweise ohne "e"
    "ozone_index": "airquality_ozone_series",
    "birkenpollen_belaestigung": "pollen_birch",
    "beifußpollenbelastung": "pollen_mugwort_series",
    "olivenpollenbelastung": "pollen_olive_series",
    "brightness_index": "cloud_cover_avg",
    "airpressure": "pressure_avg_series",
    "birch_pollen_concentration": "pollen_birch",
    "outdoor_humidity": "humidity_avg",
    "air_quality_humidity_series": "humidity_avg_series",
    "rainfall_max": "precipitation_sum_series",
    "sun_minutes": "sunshine_sum",
    "brightsky_percent": "sunshine_sum_series",
    "pm25_avg": "airquality_pm2_5",
    "air_quality_index_daily_max": "airquality_european_aqi",
    "no2_avg": "airquality_nitrogen_dioxide",
    "no2_max_time": "airquality_nitrogen_dioxide_series",
    "air_quality_o3_max": "airquality_ozone",
    "ozone_max": "airquality_ozone_series",
    "sun_hours": "sunshine_duration",
    "rain_intensity_series": "precipitation_sum_series",
    "ozone_avg": "airquality_ozone",
}


# v1.7.1.12 -- fields where the requested name itself does not reveal
# whether a daily value or a _series (timeseries) was meant, unlike
# CONTEXT_FIELD_ALIASES above where every observation points to the
# same target. A majority-default alias was considered and rejected
# (see NOTES_v1.7.1.12.md "Ziel 1"/"Ziel 3") -- it would silently
# return a wrong value in the minority of cases (20-50%, depending on
# field), exactly the failure mode this session is fixing elsewhere.
#
# Instead: reuse the existing error/did_you_mean schema (checked in
# query_context() below, BEFORE the generic unknown-field handling) --
# no new response shape, no new field on the result dict. Deliberately
# NOT a new "ambiguous": true marker -- weaker local models (see Lauf 11:
# mistral-nemo skips query_context in 74% of cases, command-r7b refuses
# tool calls entirely) already struggle with the existing schema; a new
# response concept would add reasoning burden precisely where models are
# already weakest, whereas did_you_mean is a shape every model already
# has to handle for typos. field_used/field_resolved_from are NOT set --
# nothing was resolved, the caller must re-ask with the exact name.
#
# Grouped by subject matter (all air quality: particulates + gases),
# not by candidate quality -- pm25/pm2_5/pm10/no2/air_quality_index all
# showed the identical daily/series split pattern in Lauf 11 Appendix A.
# "ozone" deliberately NOT included here (see CONTEXT_FIELD_ALIASES
# comment above) -- distinct decision, not yet resolved either way.
CONTEXT_FIELD_AMBIGUOUS: dict[str, list[str]] = {
    "pm25": ["airquality_pm2_5", "airquality_pm2_5_series"],
    "pm2_5": ["airquality_pm2_5", "airquality_pm2_5_series"],
    "pm10": ["airquality_pm10", "airquality_pm10_series"],
    "no2": ["airquality_nitrogen_dioxide", "airquality_nitrogen_dioxide_series"],
    "air_quality_index": ["airquality_european_aqi", "airquality_european_aqi_series"],
}


def _route_query(kind: str) -> str:
    """
    Decides whether a given query kind should be served from the
    SQLite cache or the live archive. Placeholder — always returns
    "sqlite" for every kind (see module comment above for the binding
    rationale and TODO). kind is one of "health"/"context"/"fit"/
    "raw"/"metadata" — a query-tool-family identifier, not an
    MCP-tool-name passthrough, since query_fit_activities and the
    (not yet existing) fit-domain query share one "fit" kind rather
    than each tool inventing its own key.
    """
    return "sqlite"


@mcp.tool()
def query_health(field: str, date_from: str, date_to: str,
                  resolution: str = "daily") -> dict:
    """Query Garmin health data (e.g. heart rate, sleep, stress, body
    battery) for a field over a date range. resolution is "daily" or
    "intraday" — most fields only support one of the two (e.g.
    resting_heart_rate is daily-only, heart_rate_series is
    intraday-only); pass the field name that matches what you want,
    see list_available_fields() for the full list. This parameter is
    accepted for forward compatibility but not currently used to pick
    between two resolutions of the same field, since no field in this
    archive currently offers both — each field's own stored resolution
    already determines whether the answer is a single daily value or
    a full timeseries.

    v1.7.1.1 field-filter fix (2026-08-28 session): field is now
    passed through to the SQLite branch — previously it was silently
    dropped, so every call returned all ~26 health fields regardless
    of what was asked for, including this archive's intraday *_series
    fields (full day-long timeseries), inflating a single-value
    answer to hundreds of KB and confusing small local LLMs
    summarizing the result.

    v1.7.1.6 unit field: every field in the returned result now
    carries a "unit" key alongside "values"/"fallback"/
    "source_resolution" — see FIELD_UNITS above. Applied AFTER the
    routing weiche below, so it covers both branches identically
    (today, only the SQLite branch is ever actually taken — see
    _route_query()'s docstring).

    v1.7.1.9 unknown-field detection (this session): mirrors
    query_context()'s v1.7.1.4 fix, applied here with a delayed
    session (see that function's docstring for the original rationale
    -- a valid-but-dataless field and an unregistered field previously
    returned the identical silent {"health": {}}, leaving the caller
    unable to tell the two apart). Checked BEFORE the _route_query()
    switch below, so it applies regardless of which branch (sqlite/
    live) ends up serving the request -- the field registry itself
    (mcp_map.list_available_fields) is unrelated to that routing
    decision.

    Three unknown-field outcomes, checked in this order:
      1. Unambiguous near-match against the known health field names
         (e.g. a typo) -> auto-resolved, field_used replaces the
         caller's input transparently, but the substitution is always
         visible via _meta.field_resolved_from / _meta.field_used —
         never a silent rewrite.
      2. The field IS registered, but under query_context's domain,
         not query_health's (e.g. "temperature_max") -> a
         domain-specific error naming query_context, no did_you_mean
         list (a health-domain suggestion would be wrong here).
      3. Neither of the above (no close match, and not a
         query_context field either) -> a generic "unknown field"
         error, with a did_you_mean suggestion list when difflib found
         any candidates, without one when it found none.

    A valid field's result (with or without data in range) is returned
    exactly as before this session — none of the above runs unless
    field is unrecognized.

    Deliberately NOT addressed here (see AKTIONSPLAN_v1.7.1.9_
    health_fallback.md Abschnitt 3/4 for the full analysis): a model
    that picks a completely unrelated but real, registered field
    instead of a near-match typo (verified empirically against the
    2026-09-05 test run's Hermes3 cases, e.g. resting_heart_rate
    returned for a steps question) is not a field-registry problem —
    no near-match exists for the fallback to catch, since the wrong
    field is itself a valid, unrelated field name. Tracked as a
    parking-lot item (query_health docstring example-field guidance),
    not pulled into this fix.

    v1.7.1.9 Session 2 -- sleep_score fan-out: "sleep_score" is itself
    an already-valid, registered field (unlike the alias candidates
    below), so it would never reach the unknown-field checks above --
    it always short-circuits straight to the normal valid-field path.
    Checked here, BEFORE the bundle check, precisely because it is
    valid and would otherwise never trigger any of the outcomes below.
    Fans out to the two closely related fields sleep_score_feedback
    and sleep_score_qualifier and returns all three together in the
    same {"garmin": {field: {...}}} shape a normal multi-field result
    already has -- no new result shape, _enrich_with_units() handles
    it unchanged. _meta.field_resolved_from is set to "sleep_score" so
    the fan-out is visible; no field_used, since all three delivered
    field names are already the dict's own keys, unlike the 1:1 alias
    case where the substitution would otherwise be invisible. A direct
    call to "sleep_score_feedback" or "sleep_score_qualifier" is NOT
    affected -- only the exact bare "sleep_score" triggers this.

    v1.7.1.9 Session 2 -- short-form alias mapping: three short-form
    field names (steps, hrv, hill) sit far enough below any workable
    difflib cutoff against their real target field names (steps_series,
    hrv_last_night, hill_score -- confirmed down to cutoff=0.7, see
    NOTES_v1.7.1.9.md Session 2) that no cutoff tuning can catch them
    without introducing new ambiguities elsewhere. HEALTH_FIELD_ALIASES
    below resolves these explicitly, checked before outcome 1's
    near-match logic (an alias hit is more certain than a near-match
    and should not have to pass through it). "spo2" was considered and
    explicitly excluded (real collision between spo2_avg and
    spo2_series, no reliable disambiguation signal available -- see
    NOTES_v1.7.1.9.md Session 2 for the full analysis)."""
    if field == "sleep_score":
        # Correction (v1.7.1.9 Session 2, post-Lauf-8): get_health_range()
        # already reads through the source-name layer itself (see its own
        # docstring, "v1.7.1.1 Bug-C correction") and returns
        # {"health": {field: {"values": ...}}} directly -- no "garmin" key
        # on this return value. The original version of this block wrongly
        # assumed an extra {"garmin": {...}} layer here (confusing this
        # call's return shape with health_map.get()'s own live-side shape,
        # which DOES nest under a source name), so every extraction silently
        # produced None and merged stayed empty on all 5 models / 29 calls
        # in the Lauf-8 test run. Fixed to read the field straight off
        # "health", and to build the same flattened shape
        # _resolve_context_bundle() already produces (which
        # _enrich_with_units() already recognizes as its documented
        # "already-flattened shape" case -- no third shape introduced).
        fan_out_fields = ["sleep_score", "sleep_score_feedback", "sleep_score_qualifier"]
        merged: dict = {}
        meta: dict = {}
        for fan_field in fan_out_fields:
            if _route_query("health") == "sqlite":
                fan_result = mcp_sql.get_health_range(date_from, date_to, field=fan_field)
            else:
                fan_result = mcp_map.query_health(fan_field, date_from, date_to, resolution)
            meta = fan_result.get("_meta", meta)
            field_value = fan_result.get("health", {}).get(fan_field)
            if field_value is not None:
                merged[fan_field] = field_value
        result = {"health": merged}
        result["_meta"] = meta if meta else {}
        result["_meta"]["field_resolved_from"] = "sleep_score"
        return _enrich_with_units(result, "health")

    if field in HEALTH_FIELD_ALIASES:
        resolved_field = HEALTH_FIELD_ALIASES[field]
        if _route_query("health") == "sqlite":
            result = mcp_sql.get_health_range(date_from, date_to, field=resolved_field)
        else:
            result = mcp_map.query_health(resolved_field, date_from, date_to, resolution)
        result.setdefault("_meta", {})
        result["_meta"]["field_resolved_from"] = field
        result["_meta"]["field_used"] = resolved_field
        return _enrich_with_units(result, "health")

    if field in HEALTH_FIELD_AMBIGUOUS:
        # v1.7.1.12 -- checked here, BEFORE the bundle/difflib logic
        # below, same ordering principle as HEALTH_FIELD_ALIASES above
        # (a known-ambiguous hit is more certain than letting it fall
        # through to whatever difflib happens to resolve at the current
        # cutoff). NOT resolved -- no field_used/field_resolved_from,
        # the caller must re-ask with the exact name. See
        # HEALTH_FIELD_AMBIGUOUS's own comment above for why "spo2" and
        # "stress" are here and "respiration" deliberately is not.
        candidates = HEALTH_FIELD_AMBIGUOUS[field]
        return {
            "health": {},
            "error": (
                f"field {field!r} is ambiguous between a daily value and "
                f"a time series -- please specify one of: "
                f"{', '.join(candidates)}"
            ),
            "did_you_mean": candidates,
            "_meta": {},
        }

    if field in _CONTEXT_CATEGORY_BUNDLES:
        # A bundle name (e.g. "weather") is a query_context-only
        # concept -- it is never itself a registered health field, so
        # without this check it would silently fall through to outcome
        # 3 below and likely produce a did_you_mean suggestion against
        # unrelated health fields. Routed to the same domain-confusion
        # error as outcome 2, since a bundle name IS something
        # query_context understands, just not under this tool.
        return {
            "health": {},
            "error": f"field {field!r} belongs to query_context, not query_health",
            "_meta": {},
        }

    known_health_fields = set(
        mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
    )

    # v1.7.1.12 -- Domain-Einordnung VOR dem Aehnlichkeitsvergleich
    # (Timo-Entscheidung, siehe NOTES_v1.7.1.12.md Ziel 5): known_
    # context_fields wird jetzt hier, VOR dem difflib-Block, berechnet
    # und geprueft -- vorher lief dieser Check erst NACH dem
    # len(close_matches)==1-Zweig, wodurch ein exaktes, registriertes
    # Context-Feld bei cutoff=0.65 regelmaessig faelschlich auf ein
    # aehnlich benanntes Health-Feld auto-resolved wurde, BEVOR die
    # Domain-Confusion-Pruefung ueberhaupt erreicht werden konnte
    # (z.B. "sunshine_duration" -> faelschlich "sleep_duration",
    # "pressure_avg"/"pressure_avg_series" -> faelschlich "stress_avg"/
    # "stress_series"). Ein Feld, das exakt in der anderen Domain
    # registriert ist, wird jetzt sofort korrekt eingeordnet, ohne dass
    # difflib je die Chance bekommt es zuerst der falschen Domain
    # zuzuordnen -- Einordnung vor Aehnlichkeitsvergleich, nicht danach.
    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)

    if field not in known_health_fields and field in known_context_fields:
        return {
            "health": {},
            "error": f"field {field!r} belongs to query_context, not query_health",
            "_meta": {},
        }

    if field not in known_health_fields:
        # v1.7.1.11 Session 5 (Testlauf, 2026-09-09) -- cutoff testweise
        # von 0.8 auf 0.65 gesenkt, um empirisch zu pruefen, ob sich
        # damit mehr echte Nahtreffer (z.B. steps -> steps_series,
        # Wortumstellungen wie min_temperature -> temperature_min)
        # zuverlaessig aufloesen lassen, ohne unerwuenschte
        # Fehltreffer bei kurzen/generischen Feldnamen zu erzeugen.
        # Kalibriert gegen die 25 haeufigsten requested/expected-
        # Diskrepanzen aus Lauf 11 (context-Domaene): 0.65 deckt ~52%
        # der gewichteten Faelle ab (0.80: ~5%), mit dem groessten
        # Einzelsprung gegenueber 0.70. Reiner Testwert fuer diese
        # Session -- KEINE endgueltige Entscheidung. Vor v1.7.1.10
        # wurde eine generelle Cutoff-Absenkung bereits einmal geprueft
        # und wegen Fehltreffer-Risiko bewusst verworfen -- dieser
        # Lauf soll das empirisch nachpruefen, nicht ueberschreiben.
        close_matches = difflib.get_close_matches(
            field, known_health_fields, n=3, cutoff=0.65
        )
        if len(close_matches) == 1:
            resolved_field = close_matches[0]
            if _route_query("health") == "sqlite":
                result = mcp_sql.get_health_range(date_from, date_to, field=resolved_field)
            else:
                result = mcp_map.query_health(resolved_field, date_from, date_to, resolution)
            result.setdefault("_meta", {})
            result["_meta"]["field_resolved_from"] = field
            result["_meta"]["field_used"] = resolved_field
            return _enrich_with_units(result, "health")

        error_result = {
            "health": {},
            "error": f"unknown field {field!r}",
            "_meta": {},
        }
        if close_matches:
            error_result["did_you_mean"] = close_matches
        return error_result

    if _route_query("health") == "sqlite":
        result = mcp_sql.get_health_range(date_from, date_to, field=field)
    else:
        result = mcp_map.query_health(field, date_from, date_to, resolution)
    return _enrich_with_units(result, "health")


def _resolve_context_bundle(bundle_name: str, date_from: str, date_to: str,
                             resolution: str) -> dict:
    """v1.7.1.5 -- resolves a _CONTEXT_CATEGORY_BUNDLES entry into a flat,
    single-value-per-field-name result. For each source in the bundle's
    priority list, gathers every field name that source registers (via
    mcp_map.list_available_fields(domain="context") -- clients/ never
    imports maps.context_map directly, mcp_map is the sole broker-facing
    surface, see NOTES_v1.7.1.5.md) and queries it through the same
    sqlite/live routing weiche query_context() itself uses for a plain
    field -- no separate/bypass data-access path.

    Flattening: field names are unique across sources except for a
    deliberate, known collision (e.g. "wind_speed_max" under both
    "weather" and "brightsky"). On a collision, the tie-break is decided
    PER DAY, not per whole field: for each date in range, the first
    source (in the bundle's priority-list order) with a non-None value
    for THAT day wins -- a field's final "values" array can therefore be
    stitched together from more than one source across the range (e.g.
    brightsky for most days, weather filling in a day brightsky has no
    data for). "_meta.field_sources" records the winning source for each
    day a collision was actually resolved (e.g. {"wind_speed_max":
    {"2026-03-01": "brightsky", "2026-03-02": "weather"}}) -- only for
    fields that had more than one candidate source in this bundle, never
    for a field copied through from a single source unchanged.

    v1.7.1.11 -- "_series" (intraday) fields are skipped during bundle
    resolution (see the source_field loop below). The bundle mechanism
    exists to answer a daily-value source-collision question (DWD vs.
    model, e.g. wind_speed_max); at intraday resolution the three
    affected sources never have more than one candidate, so the
    collision machinery has nothing to resolve. A _series field remains
    individually queryable via query_context()."""
    # source_values[field_name][source] = {date: value, ...}
    source_values: dict[str, dict[str, dict[str, object]]] = {}
    field_resolution: dict[str, dict] = {}  # first-seen values/fallback/
                                             # source_resolution shape per field
    meta: dict = {}

    # source -> [field_names] fuer alle context-Quellen. Ueber mcp_map
    # bezogen, nicht direkt aus maps.context_map -- clients/ spricht die
    # Broker-Schicht ausschliesslich ueber mcp_map an (Timo-Entscheidung,
    # NOTES_v1.7.1.5.md), context_map bleibt intern fuer maps/.
    _context_fields_by_source = mcp_map.list_available_fields(
        domain="context")["fields"]["context"]

    for source in _CONTEXT_CATEGORY_BUNDLES[bundle_name]:
        for source_field in _context_fields_by_source.get(source, []):
            if source_field.endswith("_series"):
                continue  # Bundle-Kollisionslogik ist nur für Tageswerte
                           # definiert — DWD-ja/nein-Frage betrifft Quellen,
                           # nicht Auflösungsstufen. Ein _series-Feld bleibt
                           # über query_context() einzeln abfragbar.
            if _route_query("context") == "sqlite":
                source_result = mcp_sql.get_context_range(
                    date_from, date_to, field=source_field
                )
            else:
                source_result = mcp_map.query_context(
                    source_field, date_from, date_to, resolution
                )
            meta = source_result.get("_meta", meta)

            per_source = source_result.get("context", {}).get(source, {})
            candidate = per_source.get(source_field)
            if candidate is None:
                continue

            by_date = {v["date"]: v.get("value") for v in candidate.get("values", [])}
            source_values.setdefault(source_field, {})[source] = by_date
            field_resolution.setdefault(source_field, {
                "fallback": candidate.get("fallback", False),
                "source_resolution": candidate.get("source_resolution", "daily"),
            })

    flat_values: dict[str, dict] = {}
    field_sources: dict[str, dict[str, str]] = {}

    for source_field, per_source_dates in source_values.items():
        sources_for_field = [
            s for s in _CONTEXT_CATEGORY_BUNDLES[bundle_name]
            if s in per_source_dates
        ]
        all_dates = sorted({
            d for by_date in per_source_dates.values() for d in by_date
        })

        merged_values = []
        day_winners: dict[str, str] = {}
        for day in all_dates:
            winning_value = None
            winning_source = None
            for source in sources_for_field:
                day_value = per_source_dates[source].get(day)
                if day_value is not None:
                    winning_value = day_value
                    winning_source = source
                    break
            merged_values.append({"date": day, "value": winning_value})
            if winning_source is not None:
                day_winners[day] = winning_source

        flat_values[source_field] = {
            **field_resolution[source_field],
            "values": merged_values,
        }
        # Only record a per-day source map when this field actually had
        # more than one candidate source in this bundle -- a single-
        # source field (the normal pollen/air case, and most weather
        # fields) needs no attribution.
        if len(sources_for_field) > 1:
            field_sources[source_field] = day_winners

    result: dict = {"context": flat_values}
    result["_meta"] = meta if meta else {}
    result["_meta"]["field_sources"] = field_sources
    # v1.7.1.6 unit field (this session): flat_values is keyed directly
    # by field name (no source level — see this function's own
    # docstring on flattening), so _enrich_with_units() takes the
    # already-flattened branch. Note this cannot be done earlier by
    # reusing "candidate"'s own unit (if any): the per-source calls
    # above go straight to mcp_sql.get_context_range()/
    # mcp_map.query_context() (Zeilen darueber), not through this
    # module's query_context() @mcp.tool() wrapper, so candidate never
    # carries a "unit" key to begin with -- this call is the first
    # point in this function's data flow where a unit can be attached.
    return _enrich_with_units(result, "context")


@mcp.tool()
def query_context(field: str, date_from: str, date_to: str,
                   resolution: str = "daily") -> dict:
    """Query external context data (weather, pollen, air quality) for a
    field over a date range. Fans out across all sources that recognize
    the field.

    v1.7.1.3 field-filter fix: field is now passed through to the
    SQLite branch — previously it was silently dropped (this call site
    never forwarded it at all), so every call returned all four
    context categories (weather/brightsky/airquality/pollen) regardless
    of what was asked for, inflating a single-value answer to hundreds
    of KB and confusing small local LLMs summarizing the result. Same
    fix as query_health()'s v1.7.1.1/v1.7.1.2 field-filter, applied
    here with a one-session delay.

    v1.7.1.4 unknown-field detection (this session): a field that is
    valid for query_context() but unregistered anywhere in the context
    domain previously returned the same silent {"context": {}} as a
    registered field with no data in the requested range — the caller
    (LLM or human) could not tell "field does not exist" apart from
    "field exists, no data here". This is checked BEFORE the
    _route_query() switch below, so the check applies regardless of
    which branch (sqlite/live) ends up serving the request — the field
    registry itself (mcp_map.list_available_fields) is unrelated to
    that routing decision.

    Three unknown-field outcomes, checked in this order:
      1. Unambiguous near-match against the known context field names
         (e.g. a typo) -> auto-resolved, field_used replaces the
         caller's input transparently, but the substitution is always
         visible via _meta.field_resolved_from / _meta.field_used —
         never a silent rewrite.
      2. The field IS registered, but under query_health's domain, not
         query_context's (e.g. "sleep") -> a domain-specific error
         naming query_health, no did_you_mean list (a context-domain
         suggestion would be wrong here).
      3. Neither of the above (e.g. a category name like "weather", or
         no close match at all) -> a generic "unknown field" error,
         with a did_you_mean suggestion list when difflib found any
         candidates, without one when it found none.

    A valid field's result (with or without data in range) is returned
    exactly as before this session — none of the above runs unless
    field is unrecognized.

    v1.7.1.5 category bundles (this session): a field value naming a
    known bundle key ("weather"/"pollen"/"air") is resolved BEFORE any
    of the three unknown-field outcomes above -- a bundle name is never
    a registered field itself, so without this check it would always
    fall through to the generic "unknown field" branch. Each bundle
    field is queried individually through the SAME sqlite/live routing
    weiche used everywhere else in this function -- the bundle path
    only adds collection, flattening, and collision tie-breaking on top,
    it does not bypass or duplicate the existing data-access path. See
    _CONTEXT_CATEGORY_BUNDLES above for the priority-list mechanics.

    v1.7.1.11 Session 4 -- resolution is decided by the field name
    itself, same principle as query_health(): a "_series" suffix always
    means intraday/timeseries data, a plain field name always means a
    single daily value -- no field in this archive offers both under
    one name, so the caller already knows which shape to expect before
    the query even runs. This holds regardless of which branch
    (sqlite/live) below ends up serving the request -- both branches
    return the same "values" contract (see mcp_sql.get_context_range()
    / clients/mcp_sql.py, and maps/_context_io.py's read_summary_field()/
    read_raw_field() for the underlying {"date","value"} vs.
    {"date","series"} shapes).

    v1.7.1.12 -- CONTEXT_FIELD_ALIASES / CONTEXT_FIELD_AMBIGUOUS checked
    here, BEFORE the bundle check, mirroring query_health()'s
    HEALTH_FIELD_ALIASES ordering (an alias hit is more certain than a
    near-match and should not have to pass through the bundle or
    difflib logic). Three outcomes now precede the pre-existing bundle/
    unknown-field handling below:
      1. CONTEXT_FIELD_ALIASES hit -> auto-resolved, field_used/
         field_resolved_from set, same as the alias path in
         query_health().
      2. CONTEXT_FIELD_AMBIGUOUS hit -> NOT resolved. Returns the
         existing error/did_you_mean shape with a field-specific error
         message and the known candidate list as did_you_mean -- no new
         response shape (see CONTEXT_FIELD_AMBIGUOUS's own comment for
         the rationale). field_used/field_resolved_from are NOT set.
      3. Neither -> falls through unchanged to the bundle check and the
         existing unknown-field difflib logic below.
    See NOTES_v1.7.1.12.md for the full candidate-by-candidate analysis
    behind both tables."""
    if field in CONTEXT_FIELD_ALIASES:
        resolved_field = CONTEXT_FIELD_ALIASES[field]
        if _route_query("context") == "sqlite":
            result = mcp_sql.get_context_range(date_from, date_to, field=resolved_field)
        else:
            result = mcp_map.query_context(resolved_field, date_from, date_to, resolution)
        result.setdefault("_meta", {})
        result["_meta"]["field_resolved_from"] = field
        result["_meta"]["field_used"] = resolved_field
        return _enrich_with_units(result, "context")

    if field in CONTEXT_FIELD_AMBIGUOUS:
        candidates = CONTEXT_FIELD_AMBIGUOUS[field]
        return {
            "context": {},
            "error": (
                f"field {field!r} is ambiguous between a daily value and "
                f"a time series -- please specify one of: "
                f"{', '.join(candidates)}"
            ),
            "did_you_mean": candidates,
            "_meta": {},
        }

    if field in _CONTEXT_CATEGORY_BUNDLES:
        return _resolve_context_bundle(field, date_from, date_to, resolution)

    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)

    # v1.7.1.12 -- Domain-Einordnung VOR dem Aehnlichkeitsvergleich,
    # spiegelbildlich zur selben Korrektur in query_health() oben (siehe
    # dortiger Kommentar fuer die volle Begruendung). known_health_fields
    # wird jetzt hier, VOR dem difflib-Block, berechnet und geprueft --
    # vorher fuehrte das bei cutoff=0.65 z.B. dazu, dass "sleep_duration"
    # faelschlich auf "sunshine_duration" auto-resolved wurde, BEVOR die
    # Domain-Confusion-Pruefung ueberhaupt erreicht werden konnte.
    known_health_fields = set(
        mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
    )

    if field not in known_context_fields and field in known_health_fields:
        return {
            "context": {},
            "error": f"field {field!r} belongs to query_health, not query_context",
            "_meta": {},
        }

    if field not in known_context_fields:
        # v1.7.1.11 Session 5 (Testlauf, 2026-09-09) -- cutoff testweise
        # von 0.8 auf 0.65 gesenkt, siehe identischer Kommentar im
        # query_health()-Block oben fuer Begruendung und Kalibrierung.
        close_matches = difflib.get_close_matches(
            field, known_context_fields, n=3, cutoff=0.65
        )
        if len(close_matches) == 1:
            resolved_field = close_matches[0]
            # v1.7.1.11 Session 4 -- Rueckbau: "_series" durchlaeuft
            # dieselbe Weiche wie jedes andere Feld, kein Sonderpfad mehr
            # (siehe Docstring-Zusatz oben, NOTES_v1.7.1.11.md Session 4).
            if _route_query("context") == "sqlite":
                result = mcp_sql.get_context_range(date_from, date_to, field=resolved_field)
            else:
                result = mcp_map.query_context(resolved_field, date_from, date_to, resolution)
            result.setdefault("_meta", {})
            result["_meta"]["field_resolved_from"] = field
            result["_meta"]["field_used"] = resolved_field
            return _enrich_with_units(result, "context")

        error_result = {
            "context": {},
            "error": f"unknown field {field!r}",
            "_meta": {},
        }
        if close_matches:
            error_result["did_you_mean"] = close_matches
        return error_result

    # v1.7.1.11 Session 4 -- Rueckbau: "_series" durchlaeuft dieselbe
    # Weiche wie jedes andere Feld, kein Sonderpfad mehr (siehe
    # Docstring-Zusatz oben, NOTES_v1.7.1.11.md Session 4).
    #
    # v1.7.1.12 -- wind_speed_max source collision (see NOTES_v1.7.1.12.md
    # "Ziel 2"): "weather" and "brightsky" both register a field called
    # "wind_speed_max" (deliberate, documented in REFERENCE_BROKER.md).
    # _resolve_context_bundle() above already tie-breaks this correctly
    # per day when the request goes through the "weather" bundle name --
    # but a direct field request (this path) bypassed that logic
    # entirely and returned both source values unresolved. Fixed here
    # with a plain value precedence, no fallback concept, no generic
    # collision table (Timo-Entscheidung, deliberately not building
    # _KNOWN_FIELD_COLLISIONS for a single confirmed case): brightsky
    # wins per day whenever it has a non-None value; days with no
    # brightsky value (confirmed to mean "location was outside Germany
    # that day" -- context_collector.py skips the brightsky fetch
    # entirely outside the DE bounding box, no file is ever written for
    # those dates) fall through to weather's value for that same day.
    # No location check needed here -- the fetch-time skip already
    # encodes the location decision into file presence, checking values
    # is equivalent and stays within this file's scope.
    #
    # Single call, not two: both mcp_sql.get_context_range(field=...) and
    # mcp_map.query_context(field=...) already fan out across every
    # source that registers the requested field name in one result (see
    # mcp_sql.get_context_range()'s own docstring, "field-filter fix" --
    # "the filter keeps every source that carries the requested field...
    # so a multi-source field still returns all of its sources"; same
    # fan-out principle on the live branch via gateway_map.get()). No
    # second query needed to reach the other source -- it is already in
    # the same response, keyed by source name under "context".
    if field == "wind_speed_max":
        if _route_query("context") == "sqlite":
            collision_result = mcp_sql.get_context_range(date_from, date_to, field=field)
        else:
            collision_result = mcp_map.query_context(field, date_from, date_to, resolution)

        by_source = collision_result.get("context", {})
        brightsky_candidate = by_source.get("brightsky", {}).get(field)
        weather_candidate = by_source.get("weather", {}).get(field)

        brightsky_by_date = {
            v["date"]: v.get("value")
            for v in (brightsky_candidate.get("values", []) if brightsky_candidate else [])
        }
        weather_by_date = {
            v["date"]: v.get("value")
            for v in (weather_candidate.get("values", []) if weather_candidate else [])
        }
        all_dates = sorted(set(brightsky_by_date) | set(weather_by_date))

        merged_values = []
        field_sources: dict[str, str] = {}
        for day in all_dates:
            day_value = brightsky_by_date.get(day)
            if day_value is not None:
                merged_values.append({"date": day, "value": day_value})
                field_sources[day] = "brightsky"
            else:
                day_value = weather_by_date.get(day)
                merged_values.append({"date": day, "value": day_value})
                if day_value is not None:
                    field_sources[day] = "weather"

        base_candidate = brightsky_candidate or weather_candidate or {}
        result = {
            "context": {
                field: {
                    "fallback": base_candidate.get("fallback", False),
                    "source_resolution": base_candidate.get("source_resolution", "daily"),
                    "values": merged_values,
                }
            },
        }
        result["_meta"] = collision_result.get("_meta", {})
        result["_meta"]["field_sources"] = {field: field_sources}
        return _enrich_with_units(result, "context")

    if _route_query("context") == "sqlite":
        result = mcp_sql.get_context_range(date_from, date_to, field=field)
    else:
        result = mcp_map.query_context(field, date_from, date_to, resolution)
    return _enrich_with_units(result, "context")


@mcp.tool()
def query_fit_activities(field: str, date_from: str, date_to: str,
                          resolution: str = "daily") -> dict:
    """Query FIT activity data for a field over a date range. Not yet
    available (FIT pipeline is v1.8) — returns a clean "not available"
    result until then, never an error."""
    if _route_query("fit") == "sqlite":
        # Stöpsel (see routing weiche comment above) — no
        # mcp_sql.get_fit_range() exists yet (FIT pipeline is v1.8),
        # so the SQLite branch calls the same live degraded-result
        # path query_fit_activities always used, rather than a
        # not-yet-existing cache function. Replace with
        # mcp_sql.get_fit_range(date_from, date_to) once that lands —
        # no other change needed here or at any call site.
        return mcp_map.query_fit_activities(field, date_from, date_to, resolution)
    return mcp_map.query_fit_activities(field, date_from, date_to, resolution)


@mcp.tool()
def query_raw(field: str, date_from: str, date_to: str,
              domain: str | None = None) -> dict:
    """Query raw, unprocessed archive data for a passthrough field over a
    date range. domain restricts the query to one domain ("health",
    "fit", "context") — omit to search all domains."""
    if _route_query("raw") == "sqlite":
        return mcp_sql.get_raw_range(date_from, date_to)
    return mcp_map.query_raw(field, date_from, date_to, domain=domain)


@mcp.tool()
def get_archive_metadata(kind: str, date_from: str | None = None,
                          date_to: str | None = None) -> dict:
    """Request archive-state metadata. kind selects the artefact:
    "stats" (coverage/quality overview — use this for "how big/healthy
    is my archive" questions), "device_table", "quality_log",
    "source_api_log", "token_log", "capability_config", "daily_logs",
    "fail_logs", "recent_logs".

    date_from/date_to (ISO "YYYY-MM-DD", inclusive) optionally narrow
    "quality_log", "source_api_log", "daily_logs", "fail_logs", and
    "recent_logs" to a date range — ignored for the other four kinds.
    Omit both to get the last 30 days of that kind rather than the full
    archive history; the response then includes a "note" field saying
    so. Pass both explicitly for a specific or wider range."""
    if _route_query("metadata") == "sqlite":
        return mcp_sql.get_metadata_range(kind, date_from=date_from, date_to=date_to)
    return mcp_map.get_archive_metadata(kind, date_from=date_from, date_to=date_to)


@mcp.tool()
def list_available_fields(domain: str | None = None) -> dict:
    """List all queryable fields, grouped by domain and source. Use this
    first if the set of available fields is unknown — omit domain for a
    full overview, or pass "health"/"context"/"fit" to narrow it.

    v1.7.1.6 unit field (this session): the result gains a "units" key
    alongside the existing "fields" key — a flat {field_name: unit}
    dict covering every field returned under "fields" for the requested
    domain(s). Additive only: "fields" itself keeps its original shape
    unchanged (a nested {domain: {source: [field, ...]}} name list), so
    existing callers reading "fields" (e.g. _resolve_context_bundle()
    above, which iterates the plain name lists) are unaffected. See
    FIELD_UNITS above for the unit values and their source."""
    if _route_query("fields") == "sqlite":
        # Stöpsel, same principle as query_fit_activities' branch above —
        # list_available_fields() reflects the code's own field
        # registry (health_map/context_map's registered field names,
        # gateway_map's domain/metadata-kind lists), not archived data
        # that a sync could make stale — there is no cache benefit to
        # a SQLite-backed version, and no mcp_sql function exists for
        # it. Included in the weiche anyway (Timo, explicit: "bitte so
        # bauen wie es geplant ist" — the start prompt names "all seven
        # tool wrappers... without exception" for Ziel 5, and only
        # refresh_cache() is excluded by Ziel 6) rather than silently
        # left out — both branches call the identical live path, so
        # the routing decision is structurally present but has no
        # observable effect for this one tool, the same non-effect
        # query_fit_activities' branch currently has for a different
        # reason (no fit_map.py yet vs. no cache concept applicable at
        # all here).
        result = mcp_map.list_available_fields(domain)
    else:
        result = mcp_map.list_available_fields(domain)

    all_field_names: set[str] = set()
    for _domain_fields in result.get("fields", {}).values():
        if isinstance(_domain_fields, dict):
            for _source_fields in _domain_fields.values():
                all_field_names.update(_source_fields)
        elif isinstance(_domain_fields, list):
            all_field_names.update(_domain_fields)
    result["units"] = {name: _get_field_unit(name) for name in sorted(all_field_names)}
    return result


@mcp.tool()
def refresh_cache() -> dict:
    """Manually trigger a SQLite cache sync against the archive — use
    this if recent archive changes (a sync just run, a backfill/recheck
    just completed) might not yet be reflected in query results. Runs
    the same sync the server already performs automatically at startup.
    May take a while on a large pending delta (long idle period since
    the last sync) — this call blocks until the sync finishes."""
    return mcp_update.sync_all()


def _run_headless(boot_handler: logging.FileHandler) -> None:
    """garmin_config.MCP_HEADLESS=true path (v1.7.0.1) — no Tkinter
    window at all, the server runs directly on this thread. Analogous
    to scheduler/daily_update.py's headless model. Split out of main()
    so the windowed branch there stays a two-line dispatch — both
    branches need the same operational-log handoff and the same
    OSError-on-bind handling; this function does it for the headless
    case, mcp_server_gui.py::run_gui() does the equivalent for the
    windowed case (same _start_operational_log() callable, passed in
    there instead of called directly, see that function's docstring)."""
    op_handler = _start_operational_log(cfg.MCP_BASE_DIR)
    if op_handler is not None:
        logging.getLogger().removeHandler(boot_handler)
        boot_handler.close()
        logger.info("Operational log started under %s — boot log closed",
                    cfg.MCP_BASE_DIR)
    else:
        logger.warning(
            "Could not start operational log under %s — boot log stays "
            "active for this session", cfg.MCP_BASE_DIR)

    logger.info("Starting Garmin Local Archive MCP server (headless) on "
                "http://127.0.0.1:%d", cfg.MCP_HTTP_PORT)
    try:
        mcp.run(transport="streamable-http")
    except OSError as exc:
        logger.error(
            "Could not start MCP server on 127.0.0.1:%d — port already in "
            "use (a second instance already running?) or not permitted: "
            "%s", cfg.MCP_HTTP_PORT, exc)
        sys.exit(1)


def main() -> None:
    boot_handler = _setup_boot_log()
    logger.info("mcp_server.exe starting — boot log at %s",
                cfg.MCP_SERVER_CONFIG_FILE.parent / ".garmin_mcp_server_boot.log")

    if cfg.MCP_LLM_BACKEND == "cloud" and not _cloud_llm_config_available():
        logger.warning(
            "MCP_LLM_BACKEND=cloud but %s is missing or incomplete — "
            "cloud backend not usable, Ollama remains the fallback",
            cfg.MCP_LLM_CONFIG_FILE,
        )

    # v1.7.1 — SQLite proxy boot sync. Runs before either startup path
    # below (headless or windowed) reaches mcp.run() — see
    # _run_startup_sync()'s own docstring for why this sits here rather
    # than inside _run_headless() or mcp_server_gui.py::run_gui().
    _run_startup_sync()

    if cfg.MCP_HEADLESS:
        _run_headless(boot_handler)
        return

    # Windowed (default, session decision — NOTES_v1.7.0.1vorbereitung.md
    # Eckpunkt 6): the window owns the server the same way it did under
    # the stdio-era "the window is the server" model. Lazy import —
    # mcp_server_gui.py needs this module's sys.path setup (T1 anchor /
    # _register_embedded_packages()) to already have run, same reasoning
    # as garmin_config/mcp/maps imports above being deferred past the
    # logging setup.
    from mcp_server_gui import run_gui
    run_gui(mcp, logger, boot_handler, _start_operational_log)


if __name__ == "__main__":
    main()
