#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
support-tools/mcp-call-logger/logger_config.py

Configuration for the MCP Call Logger — a standalone diagnostic proxy,
not part of the GLA package tree (see this tool's own README.md for the
full explanation of what it does and why it's isolated).

Nothing in this file imports garmin_config or any other GLA module. This
tool reads the same ~/.garmin_mcp_server_config.json file mcp_server.py
itself reads only for base_dir (log location) — never for the port, see
below.

Port model (revised — see README.md "How the ports work"): Open WebUI's
tool-server URL is configured once, points at PROXY_PORT, and is never
touched again regardless of whether logging is active. To make that
true, this proxy always owns PROXY_PORT — mcp_server.py itself must be
started on a different, internal port (INTERNAL_MCP_PORT below) whenever
logging is wanted, via the GARMIN_MCP_HTTP_PORT environment variable
(garmin_config.py's own documented ENV > file > default precedence —
see that module's MCP_HTTP_PORT block). run_mcp_with_logger.bat sets
that ENV var and starts mcp_server.py + this proxy together — neither
process's own code changes, only the port each is told to use.

The normal, logging-free path (starting mcp_server.py the usual way —
GUI, Start Menu, whatever you already do) is completely unaffected:
GARMIN_MCP_HTTP_PORT is unset, mcp_server.py falls back to its own
config-file/default port (8756) exactly as before. This proxy is only
ever in the picture when you deliberately start it via
run_mcp_with_logger.bat.
"""

from pathlib import Path

# ── Proxy's own listening port ───────────────────────────────────────────
# This is the port Open WebUI's tool-server URL should point at,
# permanently — it never changes whether or not logging is active. Set
# this to whatever port mcp_server.py would normally use (its own
# default/configured port — 8756 unless you changed it in the GUI).
PROXY_PORT = 8756

# ── Proxy's own bind address ─────────────────────────────────────────────
# Default "127.0.0.1" — same loopback-only boundary mcp_server.py itself
# uses. A client running inside Docker (e.g. Open WebUI in a container)
# reaches the host via host.docker.internal, which resolves to the host's
# real IP, not 127.0.0.1 — a proxy bound to 127.0.0.1 alone is physically
# unreachable from inside the container, no URL change on the client side
# can work around that.
#
# Set to "0.0.0.0" to bind on all interfaces so host.docker.internal (and
# any other machine on the local network) can reach this proxy. This is
# the same trade-off mcp_server.py's own MCP_EXTRA_ALLOWED_HOSTS_ENABLED
# setting already accepts for the Docker case — the proxy only forwards
# to a target (mcp_server.py) that is itself already reachable the same
# way once that flag is on, so this does not add a new exposure beyond
# what's already been accepted there.
PROXY_BIND_HOST = "127.0.0.1"  # "127.0.0.1" | "0.0.0.0"

# ── Target — mcp_server.py's internal port while logging is active ───────
# run_mcp_with_logger.bat sets GARMIN_MCP_HTTP_PORT to exactly this value
# before starting mcp_server.py, so this proxy and mcp_server.py always
# agree on the internal port without needing to read it from anywhere at
# runtime. Change this value here AND in run_mcp_with_logger.bat together
# if you ever need a different internal port (e.g. because it collides
# with something else on your machine).
TARGET_HOST = "127.0.0.1"
INTERNAL_MCP_PORT = 8758

# ── Logging depth ─────────────────────────────────────────────────────────
# "full"     — logs the complete request and response payload, including
#              full intraday series. Useful for exact reproduction of what
#              the LLM saw, but log files grow quickly with heavy intraday
#              use.
# "metadata" — logs only field name, date range, resolution, response size
#              in bytes, and (for list-shaped payloads) point count — no
#              actual values. Enough to judge "too little / too much data",
#              much smaller on disk.
LOG_DEPTH = "full"  # "full" | "metadata"

# ── Log file location ─────────────────────────────────────────────────────
# Read from ~/.garmin_mcp_server_config.json's "base_dir" field (this one
# value is still read from that shared file — duplicated three lines, not
# imported, see module docstring). Logs land under
# <base_dir>/garmin_data/log/mcp_proxy/, mirroring mcp_server.py's own
# <base_dir>/garmin_data/log/mcp/ convention. If base_dir cannot be
# determined (config file missing, no "base_dir" key), LOG_DIR_FALLBACK is
# used instead — always writable, always local to this tool.
LOG_DIR_FALLBACK = Path(__file__).parent / "log"

# Same rotation convention as mcp_server.py's LOG_MCP_MAX /
# garmin_config's LOG_RECENT_MAX.
LOG_PROXY_MAX = 30

# ── MCP server config file — read-only, shared with mcp_server.py ────────
# Used only for base_dir (log location) now — never for the port, see
# module docstring.
MCP_SERVER_CONFIG_FILE = Path.home() / ".garmin_mcp_server_config.json"
