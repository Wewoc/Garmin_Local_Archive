#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/openai_tool_schema.py
Garmin Local Archive — OpenAI-Style Tool Schema Translation

Leaf-Node, no project-internal imports (same rule as ollama_client.py).
Moved out of ollama_client.py (garmin_collector-3_experiment, Cloud +
MCP-Tool-Calling groundwork — see PROTOKOLL_experiment.md) once it
became clear the function was never actually Ollama-specific: Ollama's
own tool-calling schema is deliberately modeled on OpenAI's, and
OpenAI's Chat Completions API takes the exact same
{"type": "function", "function": {"name", "description", "parameters"}}
shape. A pure relocation, not a rewrite — same code, same behavior,
only the name/home changed (the function itself was renamed from
to_ollama_tools() to to_openai_style_tools() so its name describes the
schema it produces, not one specific product; see ollama_client.py's
own note at its former call site for the "why now, not just when
OpenAI needed it" reasoning).

Named after the schema shape ("OpenAI-style"), not after any one
consumer — clients/mcp_tool_chat.py's Ollama turn loop imports it, a
future cloud_llm_openai.py tool-calling path would too, and so would
any other OpenAI-compatible provider (Groq, Mistral, ...) without ever
depending on a file named after a completely different product.
"""


def to_openai_style_tools(mcp_tools: list[dict]) -> list[dict]:
    """Reshapes clients/mcp_client.py's list_tools() result (provider-
    neutral: {"name", "description", "inputSchema"} per tool) into the
    OpenAI-style tool-calling schema (a list of {"type": "function",
    "function": {"name", "description", "parameters"}} entries) that
    Ollama and OpenAI's Chat Completions API both consume unchanged.
    Anthropic's Messages API does not share this shape (tool_use/
    tool_result content blocks, "input_schema" instead of "parameters")
    — a future Anthropic tool-calling path owns its own translation in
    clients/cloud_llm_anthropic.py, not here."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"],
            },
        }
        for t in mcp_tools
    ]
