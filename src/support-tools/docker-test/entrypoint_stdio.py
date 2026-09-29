#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
support-tools/docker-test/entrypoint_stdio.py
stdio launcher for clients/mcp_server.py's MCP tools — for Glama's
mcp-proxy-based build/verification pipeline specifically. mcp-proxy
(https://github.com/punkpeye/mcp-proxy) makes a stdio MCP server
available over SSE; it spawns this script as its child process and
talks to it over stdin/stdout.

Zero modifications to mcp_server.py or garmin_config.py: imports the
module completely unmodified and runs its already-constructed FastMCP
instance with transport="stdio" instead of calling main() (which always
serves streamable-http — see entrypoint.py in this same folder for the
container-only override used for direct/non-proxied Docker testing).
mcp.run(transport="stdio") is a first-class option on the same FastMCP
instance (verified against mcp==1.30.0's own Literal["stdio", "sse",
"streamable-http"] signature) — this is not a hack, just a different
transport choice made outside of main()'s own dispatch.

Keeps the same SQLite boot sync main() performs (_run_startup_sync())
so refresh_cache()/query tools see a built cache; skips mcp_server.py's
own boot-log-file handling (_setup_boot_log()) — logging still reaches
stderr via the logging.basicConfig() call at mcp_server.py's module
level, which is all a short-lived sandboxed verification run needs.

Expects Glama's own clone layout: the whole repository at the build's
WORKDIR (not just src/, unlike entrypoint.py's Dockerfile-COPY layout)
— so src/clients is located relative to this file's own repo position,
not relative to a container root.
"""

import sys
from pathlib import Path

_SUPPORT_TOOLS_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _SUPPORT_TOOLS_DIR.parent
_CLIENTS_DIR = _SRC_DIR / "clients"
if str(_CLIENTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CLIENTS_DIR))

import mcp_server  # noqa: E402 — after sys.path setup above

if __name__ == "__main__":
    mcp_server._run_startup_sync()
    mcp_server.mcp.run(transport="stdio")
