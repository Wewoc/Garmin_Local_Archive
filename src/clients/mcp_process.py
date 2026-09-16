#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_process.py
Garmin Local Archive — MCP Server Process Control

Leaf-Node, Windows-only (matches this project's existing Windows-only
process tooling — the pywin32 dependency, .bat launchers, T1/T2/T3
build targets). Shared by app/panel_mcp.py and app/panel_chat.py: both
need to start/check/stop the same clients/mcp_server.py process, and
per this project's convention there are no cross-panel imports in
app/ — shared logic like this lives in clients/ instead.

resolve_launch_command()/is_running() mirror app/panel_mcp.py's own
existing _resolve_mcp_server_launch_command()/_mcp_server_is_running()
— deliberately reimplemented here rather than refactoring panel_mcp.py
to import this module (session decision, garmin_collector-3_experiment
— see PROTOKOLL_experiment.md, "Baustein 8b"): panel_mcp.py's own Start
button is already working and tested; only its new Stop button (added
the same session) uses stop() below, so the rest of that panel stays
completely untouched.

stop() is the genuinely new capability — nothing in this project could
previously terminate the MCP server programmatically (flagged as a
known gap since the original NOTES_v1.7.2_chat_panel_konzept.md
analysis). No PID file exists anywhere for the server (mcp_server.py
never wrote one, and still doesn't — this module finds the process
without needing mcp_server.py to change at all): `netstat -ano` lists
every TCP socket with its owning PID, `taskkill /PID <pid> /F` ends it.

Locale pitfall found and fixed empirically (2026-09-14, this session,
against the real running server — see PROTOKOLL_experiment.md):
netstat's STATE column is localized ("ABHÖREN" on this German-locale
Windows install, not "LISTENING") — a state-text match would have
silently found nothing here. _find_listening_pid() below instead
matches on the FOREIGN address being "0.0.0.0:0", which identifies a
bound listening socket regardless of locale (an actual client
connection to the port — e.g. one of this project's own test probes
lingering in a wait state — has the server's address as ITS foreign
address instead, and is excluded by this same check). Verified:
correctly picked the real mcp_server.py PID out of two netstat rows
that both contained the port number, cross-checked independently via
tasklist.

Pragmatic stop, not ownership-based (KONZEPT_v1.7.2 decision): whoever
clicks Stop kills the server regardless of who started it or from
which panel — see NOTES_v1.7.2_chat_panel_konzept.md's "Stop"
reasoning, restated in both panels' own Stop handlers.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

# mcp_process.py lives in clients/ and needs garmin_config (MCP_HTTP_PORT
# default) — garmin/ is one level up (sibling package), same bridge
# maps/garmin_health_map.py uses between maps/ and garmin/. Added
# garmin_collector-3_experiment, post-Baustein-23 review: this module's
# only two importers (app/panel_chat.py::_load_mcp_process(),
# app/panel_mcp.py::_load_mcp_process()) each add only "clients" to
# sys.path via frozen_paths.add_to_path() — never "garmin" — so without
# this bridge the import below silently depended on garmin/ already
# being on sys.path from garmin_app_base.py's own app-wide startup
# setup, which happens to always be true today (both loaders only ever
# run from inside the fully-booted GUI app) but was never guaranteed by
# this module itself, unlike every sibling clients/ module that imports
# garmin_config (mcp_server.py, mcp_update.py, mcp_sql.py,
# mcp_server_gui.py all build or document their own bridge). Not
# frozen_paths.add_to_path() — that helper is GUI-context-bound (see
# clients/mcp_server.py's own docstring for why it avoids that helper
# too), and this module must not assume a GUI context is what always
# imports it.
if str(Path(__file__).parent.parent / "garmin") not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))

import garmin_config as cfg

CHECK_TIMEOUT = 0.3     # matches panel_mcp.py's own _mcp_server_is_running()
# 20s, not the original 5s "netstat/taskkill are local, near-instant"
# assumption (garmin_collector-3_experiment, Baustein 29) — wrong on Timo's
# machine: netstat/taskkill subprocess spawns were observed timing out at
# 5s, most likely Windows Defender behavior-monitoring overhead on process
# creation (RealTimeProtection/BehaviorMonitoring confirmed enabled this
# session, see PROTOKOLL_experiment.md Baustein 25) rather than netstat/
# taskkill themselves being slow. Only affects the fallback path below
# (_kill_pid_tree() for the common case has its own budget) — a generous
# ceiling here costs nothing when things are fast, only matters when they
# are not.
COMMAND_TIMEOUT = 20.0

_last_started_pid: int | None = None


def resolve_launch_command() -> list[str] | None:
    """Build-context-aware launch command, T1/T2/T3.3 — same three
    cases and reasoning as app/panel_mcp.py's own
    _resolve_mcp_server_launch_command() (see that function's own
    docstring for the full explanation); this copy's T1 path differs
    only in where it looks for mcp_server.py, since this module already
    lives in clients/ itself (panel_mcp.py lives in app/, one level up
    and back down into clients/)."""
    if not getattr(sys, "frozen", False):
        script = Path(__file__).resolve().parent / "mcp_server.py"
        if not script.exists():
            return None
        return [sys.executable, str(script)]

    exe_dir = Path(sys.executable).parent
    exe_path = exe_dir / "mcp_server.exe"
    if exe_path.exists():
        return [str(exe_path)]

    bat_path = exe_dir / "Starte_MCP_Server.bat"
    if bat_path.exists():
        return [str(bat_path)]

    return None


def is_running(timeout: float = CHECK_TIMEOUT) -> bool:
    """TCP-connect probe against 127.0.0.1:MCP_HTTP_PORT — same
    liveness signal as panel_mcp.py's own _mcp_server_is_running()."""
    try:
        with socket.create_connection(
                ("127.0.0.1", cfg.MCP_HTTP_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def start() -> tuple[bool, str]:
    """Launches the MCP server headless (GARMIN_MCP_HEADLESS=1) —
    Chat-Panel-Start runs headless whenever MCP is involved, per
    KONZEPT_v1.7.2 (a separate decision from app/panel_mcp.py's own
    headless CHECKBOX, which stays that panel's own user-controlled
    setting for its own Start button — unaffected by this). Fire-and-
    forget, no health check after Popen, same "start it yourself, e.g.
    from a terminal" spirit panel_mcp.py's own _mcp_start_server()
    already documents. Refuses to start a second instance if one is
    already reachable — returns success in that case too, since the
    caller's actual goal ("a server is running") is already met.

    Remembers the launched process's own PID in _last_started_pid
    (garmin_collector-3_experiment, Baustein 29) so stop() can skip the
    netstat scan entirely in the common case (this GLA instance started
    the server itself) — see stop()/_kill_pid_tree()'s own docstrings
    for why that needs a tree-kill, not a direct PID match."""
    global _last_started_pid
    if is_running():
        return True, "MCP server already running."

    cmd = resolve_launch_command()
    if cmd is None:
        return False, ("Could not find clients/mcp_server.py, "
                        "mcp_server.exe, or Starte_MCP_Server.bat.")

    env = dict(os.environ)
    env["GARMIN_MCP_HEADLESS"] = "1"
    try:
        proc = subprocess.Popen(cmd, env=env)
    except OSError as exc:
        return False, f"Could not start the MCP server: {exc}"
    _last_started_pid = proc.pid
    return True, f"MCP server starting ({' '.join(cmd)})."


def _find_listening_pid(netstat_output: str, port: int) -> int | None:
    """Locale-independent: matches on the foreign address being
    "0.0.0.0:0" (a bound listening socket) rather than the localized
    STATE column text — see module docstring for how this was found
    and verified against the real server."""
    needle = f":{port}"
    for line in netstat_output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP":
            continue
        local_addr, foreign_addr, pid = parts[1], parts[2], parts[4]
        if local_addr.endswith(needle) and foreign_addr == "0.0.0.0:0":
            try:
                return int(pid)
            except ValueError:
                continue
    return None


def _kill_pid_tree(pid: int, timeout: float) -> bool:
    """taskkill with /T (process tree), not a direct PID match — the PID
    start() remembers is not always the actual listener
    (garmin_collector-3_experiment, Baustein 29): a T2 launch goes
    through Starte_MCP_Server.bat (Popen's .pid is the cmd.exe/bat host,
    not the python.exe it spawns), and a T3.3 --onefile mcp_server.exe
    always runs as two processes, a bootloader plus the real worker it
    launches as its own child (see PROTOKOLL_experiment.md, Baustein 28
    — the "two mcp_server.exe in Task Manager" finding). Killing only
    the remembered PID without /T would in both cases leave the actual
    server running and the port still occupied, while taskkill itself
    reports success. Returns True on success, False on any failure —
    caller falls back to the netstat-based lookup below."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, text=True, timeout=timeout, check=True)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def stop(port: int | None = None, timeout: float = COMMAND_TIMEOUT) -> tuple[bool, str]:
    """Finds and kills the process listening on the MCP server's port —
    pragmatic, not ownership-based (see module docstring). Returns
    (success, message); never raises for an ordinary "nothing to stop"
    or "could not find/kill it" outcome — the caller decides how to
    present it (in-chat text, a log line, ...).

    Tries the PID start() remembered first (garmin_collector-3_experiment,
    Baustein 29, _kill_pid_tree() above) — skips the netstat scan
    entirely in the common case. Falls back to the netstat-based lookup
    below if no PID was remembered (server started externally — a
    manual .bat launch, or a previous GLA session) or the remembered
    PID is already stale/foreign."""
    global _last_started_pid
    port = port if port is not None else cfg.MCP_HTTP_PORT
    if not is_running():
        return False, "MCP server is not running."

    if _last_started_pid is not None:
        pid = _last_started_pid
        _last_started_pid = None
        if _kill_pid_tree(pid, timeout):
            return True, f"MCP server stopped (PID {pid})."
        # stale/foreign PID (e.g. server already restarted since) — fall
        # through to the netstat-based lookup instead of giving up here.

    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            timeout=timeout, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"Could not determine the server's process: {e}"

    pid = _find_listening_pid(result.stdout, port)
    if pid is None:
        return False, f"Could not find a process listening on port {port}."

    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"], capture_output=True,
            text=True, timeout=timeout, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return False, f"Could not stop the process (PID {pid}): {e}"

    return True, f"MCP server stopped (PID {pid})."
