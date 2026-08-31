#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    summarizing the result."""
    if _route_query("health") == "sqlite":
        return mcp_sql.get_health_range(date_from, date_to, field=field)
    return mcp_map.query_health(field, date_from, date_to, resolution)


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
    for a field copied through from a single source unchanged."""
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
    return result


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
    _CONTEXT_CATEGORY_BUNDLES above for the priority-list mechanics."""
    if field in _CONTEXT_CATEGORY_BUNDLES:
        return _resolve_context_bundle(field, date_from, date_to, resolution)

    known_context_fields: set[str] = set()
    for _source_fields in mcp_map.list_available_fields(domain="context")["fields"]["context"].values():
        known_context_fields.update(_source_fields)

    if field not in known_context_fields:
        close_matches = difflib.get_close_matches(
            field, known_context_fields, n=3, cutoff=0.8
        )
        if len(close_matches) == 1:
            resolved_field = close_matches[0]
            if _route_query("context") == "sqlite":
                result = mcp_sql.get_context_range(date_from, date_to, field=resolved_field)
            else:
                result = mcp_map.query_context(resolved_field, date_from, date_to, resolution)
            result.setdefault("_meta", {})
            result["_meta"]["field_resolved_from"] = field
            result["_meta"]["field_used"] = resolved_field
            return result

        known_health_fields = set(
            mcp_map.list_available_fields(domain="health")["fields"]["health"].get("garmin", [])
        )
        if field in known_health_fields:
            return {
                "context": {},
                "error": f"field {field!r} belongs to query_health, not query_context",
                "_meta": {},
            }

        error_result = {
            "context": {},
            "error": f"unknown field {field!r}",
            "_meta": {},
        }
        if close_matches:
            error_result["did_you_mean"] = close_matches
        return error_result

    if _route_query("context") == "sqlite":
        return mcp_sql.get_context_range(date_from, date_to, field=field)
    return mcp_map.query_context(field, date_from, date_to, resolution)


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
    full overview, or pass "health"/"context"/"fit" to narrow it."""
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
        return mcp_map.list_available_fields(domain)
    return mcp_map.list_available_fields(domain)


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
