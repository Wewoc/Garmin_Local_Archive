# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
cve_whitelist.py — Garmin Local Archive
Known-used functions per package, for A1 CVE relevance filtering.

Purpose: pip-audit reports vulnerabilities at the package level, not the
function level. A CVSS "high" finding may describe a code path GLA never
calls. This whitelist lets check_cve_whitelist.py distinguish "this package
has a known vulnerability" from "the vulnerable function is actually part
of our call graph" — without claiming certainty either way (see verdict
rules in check_cve_whitelist.py).

Edit this file whenever GLA starts or stops using a specific package
function. Keep entries narrow — list the actual functions/classes called,
not the whole package surface.

Plotly is deliberately excluded — covered by its own hash-pinning +
check_deps.py monitoring mechanism (A2, v1.6.0.4.4), not by this list.
"""

CVE_WHITELIST = {
    "cryptography": {
        "used_functions": [
            "AESGCM",
            "AESGCM.encrypt",
            "AESGCM.decrypt",
        ],
        "note": "AES-256-GCM token encryption — garmin_security.py",
    },
    "garminconnect": {
        "used_functions": [
            "Garmin.login",
            "Garmin.get_stats",
            "Garmin.get_sleep_data",
        ],
        "note": "Login + data retrieval — garmin_api.py. PLACEHOLDER: full "
                "method surface used by garmin_api.py not yet enumerated — "
                "verify against actual call sites before relying on this "
                "entry.",
    },
    "curl_cffi": {
        "used_functions": [
            "requests.Session",
            "requests.get",
            "requests.post",
        ],
        "note": "TLS impersonation for Garmin API calls — transitive via "
                "garminconnect, not a direct requirements.txt entry "
                "(confirmed — see MAINTENANCE_GLOBAL.md hidden-import list).",
    },
    "keyring": {
        "used_functions": [
            "set_password",
            "get_password",
            "delete_password",
        ],
        "note": "Windows Credential Manager — garmin_security.py, "
                "app/garmin_app_settings.py",
    },
    "PyQt6": {
        "used_functions": [
            "QWebEngineView",
            "QWebEngineSettings",
        ],
        "note": "Dashboard/XLSX viewer — garmin_app_base.py, panel_home.py. "
                "PLACEHOLDER: PyQt6 surface used across app/ is broad — this "
                "entry only covers the WebEngine-related classes relevant "
                "to A5 (QWebEngineSettings hardening). Widen if needed.",
    },
    "openpyxl": {
        "used_functions": [
            "Workbook",
            "load_workbook",
            "PatternFill",
        ],
        "note": "Excel dashboard export — dash_plotter_excel.py",
    },

    # ─── MCP chain + Cloud-LLM connector (v1.7) ─────────────────────────────
    # Added 2026-09-28 — whitelist had never been updated since the MCP
    # feature landed, so every finding for these packages was silently
    # falling into "not_relevant" ("package not in whitelist"), even for
    # the ones GLA calls directly. See requirements.txt's own "MCP server
    # (v1.7)" comment block for the exact-pin rationale of the 13
    # runtime-only entries below.

    "mcp": {
        "used_functions": [
            "ClientSession",
            "streamablehttp_client",
            "FastMCP",
            "TransportSecuritySettings",
        ],
        "note": "MCP client + server core — clients/mcp_client.py "
                "(ClientSession, streamablehttp_client), clients/"
                "mcp_server.py (FastMCP, TransportSecuritySettings).",
    },
    "httpx": {
        "used_functions": [
            "ConnectError",
            "ConnectTimeout",
            "TimeoutException",
            "HTTPError",
        ],
        "note": "Transport error classification for MCP client retries — "
                "clients/mcp_client.py.",
    },
    "anthropic": {
        "used_functions": [
            "Anthropic",
        ],
        "note": "Cloud-LLM connector (Anthropic SDK) — "
                "clients/cloud_llm_anthropic.py.",
    },
    "openai": {
        "used_functions": [
            "OpenAI",
        ],
        "note": "Cloud-LLM connector (OpenAI SDK) — "
                "clients/cloud_llm_openai.py.",
    },

    # The 13 entries below are NOT called directly anywhere in src/ (no
    # import found repo-wide) — they are FastMCP's own dependency chain
    # that backs clients/mcp_server.py's `mcp.run(transport=
    # "streamable-http")` call, i.e. the ASGI/HTTP server actually bound
    # on localhost (see docs/REFERENCE_MCP.md). used_functions is left
    # empty on purpose: no verified GLA call site exists to list, and an
    # unverified guess would violate this repo's "no assumption without
    # evidence" rule. The empty entry still fixes the classification —
    # classify_finding() finds no keyword match, falls through to the
    # Ollama check, and (Ollama absent/unreachable) settles on "unsure"
    # instead of the previous, misleading "not_relevant".
    "starlette":           {"used_functions": [], "note": "ASGI framework actually serving mcp_server.py's streamable-http transport."},
    "uvicorn":             {"used_functions": [], "note": "ASGI server process behind mcp.run(transport=\"streamable-http\")."},
    "anyio":                {"used_functions": [], "note": "Async I/O layer under starlette/mcp — MCP server runtime dependency."},
    "pydantic":            {"used_functions": [], "note": "Data validation used by the mcp SDK / FastMCP tool schemas."},
    "pydantic-settings":   {"used_functions": [], "note": "Settings management used by the mcp SDK — MCP server runtime dependency."},
    "PyJWT":               {"used_functions": [], "note": "JWT handling — part of the mcp SDK's dependency chain per requirements.txt."},
    "jsonschema":          {"used_functions": [], "note": "Schema validation used by the mcp SDK / FastMCP tool argument schemas."},
    "python-multipart":    {"used_functions": [], "note": "Multipart form parsing — starlette dependency, MCP server runtime."},
    "pywin32":             {"used_functions": [], "note": "Windows integration — part of the mcp SDK's dependency chain per requirements.txt."},
    "sse-starlette":       {"used_functions": [], "note": "Server-sent-events support for the streamable-http transport."},
    "httpx-sse":           {"used_functions": [], "note": "SSE client support paired with sse-starlette for the streamable-http transport."},
    "typing-extensions":   {"used_functions": [], "note": "Typing backport used by pydantic/mcp — MCP server runtime dependency."},
    "typing-inspection":   {"used_functions": [], "note": "Typing introspection helper used by pydantic — MCP server runtime dependency."},
}