#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
support-tools/docker-test/entrypoint.py
Docker-only launcher for clients/mcp_server.py — zero modifications to
mcp_server.py or garmin_config.py.

mcp_server.py hardcodes FastMCP(..., host="127.0.0.1", ...) — a
deliberate security boundary for the normal desktop app (never remotely
reachable). Inside a container that means unreachable even via published
ports, since 127.0.0.1 is the container's own loopback. Rather than
touch that hardcoded value (production code, used by every Windows
install), this script imports mcp_server unmodified and overrides the
already-constructed FastMCP instance's mutable settings.host attribute
before calling main() — the mcp SDK reads self.settings.host lazily at
run(), not at construction (verified against mcp==1.30.0's
run_streamable_http_async()), so this works without patching any file.

Expects to be copied into the image next to an sibling src/ tree (see
../../../Dockerfile's COPY layout) — src/clients/mcp_server.py resolves
relative to this script's own location, not to a hardcoded path.
"""

import os
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
_CLIENTS_DIR = _APP_ROOT / "src" / "clients"
if str(_CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENTS_DIR))

import mcp_server  # noqa: E402 — after sys.path setup above

_bind_host = os.environ.get("GARMIN_MCP_BIND_HOST")
if _bind_host:
    mcp_server.mcp.settings.host = _bind_host

if __name__ == "__main__":
    mcp_server.main()
