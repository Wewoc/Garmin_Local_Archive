#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_client.py
Garmin Local Archive — MCP Tool-Calling Client

Leaf-Node. Wraps the official `mcp` SDK's streamable-http client against
this project's own MCP server (clients/mcp_server.py) — the piece the
in-app tool-calling chat (app/panel_chat.py, not yet built) needs to
discover and call the seven existing MCP tools. Sibling to
ollama_client.py: same leaf-node contract (no project-internal imports,
stdlib + the `mcp`/`httpx` packages only, typed exceptions, never logs,
never touches Qt) — talks MCP protocol instead of the Ollama HTTP API.

One asyncio.run() per call, a fresh MCP session each time (initialize()
+ the operation + teardown) — no persistent session kept across calls.
Simpler to reason about and matches ollama_client.py's own "one
request/response cycle" simplicity; every tool call in this project is
a local SQLite-cache read today (see mcp_server.py's _route_query(),
always "sqlite"), so the extra handshake round-trip per call is not a
practical cost. Revisit only if a future caller needs many tool calls
in tight sequence and the handshake overhead becomes measurable.

Exception shape verified empirically against a real running
mcp_server.py instance, not guessed (2026-09-14, garmin_collector-3_
experiment — see PROTOKOLL_experiment.md): anyio's TaskGroup wraps every
low-level transport failure in an ExceptionGroup — httpx.ConnectError
for "nothing listening", the httpx.TimeoutException family for a
slow/hung server. _classify() below walks .exceptions recursively
(ExceptionGroup can nest) for the first httpx exception and picks the
matching typed error, so callers never have to know about anyio's
wrapping.

An unknown tool name is NOT a transport-level error — confirmed against
the real server, it returns a normal CallToolResult with isError=True
and a text message ("Unknown tool: ..."), consistent with
REFERENCE_MCP.md's documented isError convention (any uncaught
exception inside a @mcp.tool()-decorated function becomes
CallToolResult(isError=True, ...)). call_tool() below raises
McpToolError in that case, so a caller has one place to distinguish
"the tool ran but failed" (McpToolError) from "could not reach the
tool at all" (McpUnreachable/McpTimeout).
"""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_MCP_URL = "http://127.0.0.1:8756/mcp"

# Tool calls in this project are SQLite-cache reads (see mcp_server.py's
# _route_query(), always "sqlite" today) — fast. Not the same generous
# multi-minute budget ollama_client.DEFAULT_TIMEOUT needs for local LLM
# generation; this is a local HTTP round-trip against a cache.
CONNECT_TIMEOUT = 5.0
CALL_TIMEOUT = 30.0


class McpClientError(Exception):
    """Base class for all mcp_client errors."""


class McpUnreachable(McpClientError):
    """MCP server is not running / not reachable at the given URL."""


class McpTimeout(McpClientError):
    """Request exceeded the timeout without a response."""


class McpToolError(McpClientError):
    """The MCP server accepted the call but the tool itself reported an
    error (CallToolResult.isError=True) — e.g. an unknown tool name, or
    a query_* validation error passed through from mcp_map.py."""


def _classify(exc: BaseException, base_url: str, timeout: float) -> McpClientError:
    """Walks a (possibly nested) ExceptionGroup for the first httpx
    exception and returns the matching typed error — see module
    docstring for how this shape was confirmed against the real server.

    ConnectError/ConnectTimeout are checked before the broader
    TimeoutException family on purpose: empirically (2026-09-14, same
    experiment session) a plain "nothing is listening on this port"
    case surfaced as httpx.ConnectError on one run and httpx.
    ConnectTimeout on another — both mean "could not reach a server at
    all" and should read as McpUnreachable, not McpTimeout. McpTimeout
    is reserved for a connection that succeeded but got no response in
    time (ReadTimeout/WriteTimeout/PoolTimeout) — a server that is up
    but slow/hung, a materially different situation for the caller.

    Message includes base_url rather than relying on str(exc) alone —
    a bare ConnectError/ConnectTimeout can stringify to "" (observed
    during the same verification run), which would otherwise produce an
    empty, useless error message for the caller."""
    pending = [exc]
    while pending:
        current = pending.pop()
        if isinstance(current, (httpx.ConnectError, httpx.ConnectTimeout)):
            return McpUnreachable(f"MCP server not reachable at {base_url}")
        if isinstance(current, httpx.TimeoutException):
            return McpTimeout(f"MCP server at {base_url} did not respond "
                               f"within {timeout:.0f}s")
        if isinstance(current, httpx.HTTPError):
            return McpUnreachable(f"MCP server not reachable at {base_url}: {current}")
        pending.extend(getattr(current, "exceptions", ()))
    return McpClientError(str(exc) or f"Unclassified error calling {base_url}")


async def _list_tools_async(base_url: str, timeout: float) -> list[dict]:
    async with streamablehttp_client(base_url, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema,
                }
                for t in result.tools
            ]


async def _call_tool_async(base_url: str, name: str, arguments: dict,
                            timeout: float) -> tuple[str, bool]:
    # Returns (text, is_error) instead of raising McpToolError directly —
    # anyio's TaskGroup re-wraps any exception raised while a
    # streamablehttp_client/ClientSession async-with block is still
    # unwinding into a fresh ExceptionGroup (confirmed empirically,
    # 2026-09-14: raising here made McpToolError arrive at call_tool()'s
    # except McpClientError as an untyped ExceptionGroup instead, losing
    # both the type and the message). call_tool() raises McpToolError
    # itself once asyncio.run() has returned cleanly, outside any anyio
    # context — see module docstring.
    async with streamablehttp_client(base_url, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            text = "\n".join(
                block.text for block in result.content if hasattr(block, "text"))
            return text, result.isError


def is_reachable(base_url: str = DEFAULT_MCP_URL,
                  timeout: float = CONNECT_TIMEOUT) -> bool:
    """Lightweight reachability check — list_tools(), result discarded.
    Mirrors ollama_client.is_reachable()'s role for a future chat-panel
    tab-open ping."""
    try:
        asyncio.run(_list_tools_async(base_url, timeout))
        return True
    except BaseException:
        return False


def list_tools(base_url: str = DEFAULT_MCP_URL,
                timeout: float = CONNECT_TIMEOUT) -> list[dict]:
    """Returns the server's tool list in a plain, provider-neutral shape
    ({"name", "description", "inputSchema"} per tool). Reshaping into a
    specific backend's own tool-calling format (Ollama, a future cloud
    connector) is that backend's job, not this leaf node's — kept out on
    purpose so this module has no opinion about which LLM backend calls
    it."""
    try:
        return asyncio.run(_list_tools_async(base_url, timeout))
    except McpClientError:
        raise
    except BaseException as e:
        raise _classify(e, base_url, timeout) from e


def call_tool(name: str, arguments: dict, base_url: str = DEFAULT_MCP_URL,
              timeout: float = CALL_TIMEOUT) -> str:
    """Calls one MCP tool, returns its text content (joined if the
    result carries more than one text block — not observed against this
    project's own tools, which all return a single JSON text block, but
    the MCP content model allows more than one). Raises McpToolError if
    the tool itself reported isError=True — see module docstring."""
    try:
        text, is_error = asyncio.run(
            _call_tool_async(base_url, name, arguments, timeout))
    except McpClientError:
        raise
    except BaseException as e:
        raise _classify(e, base_url, timeout) from e

    if is_error:
        raise McpToolError(text or f"Tool '{name}' reported an error")
    return text
