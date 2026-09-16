#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_tool_chat.py
Garmin Local Archive — Ollama + MCP Tool-Calling Turn Loop

Orchestration layer sitting on top of clients/ollama_client.py's
chat_with_tools(), clients/openai_tool_schema.py's
to_openai_style_tools() (moved out of ollama_client.py,
garmin_collector-3_experiment — never actually Ollama-specific, see
that module's own docstring), and clients/mcp_client.py's
list_tools()/call_tool() — the "Agentic Loop" building block from
NOTES_v1.7.2_chat_panel_konzept.md's cost analysis. None of the three
client modules knows about the others; this module is where they get
wired together, kept separate so they stay single-purpose leaf nodes.

converse() does NOT touch Qt, does not log, does not read GLA settings
— base_url/model/messages are all caller-supplied. A future
app/panel_chat.py integration calls this from its own worker thread,
same pattern the panel already uses for plain chat() (see
_chat_on_send() there).

Verified against a real running stack (2026-09-14,
garmin_collector-3_experiment — see PROTOKOLL_experiment.md, "Baustein
2"/"Baustein 3"): qwen3:14b + the real MCP server (real archive data,
read-only). Confirmed the mechanism correctly drives a real multi-turn
correction — asked for field "steps", the server's v1.7.1.12 ambiguity
check declined it ("ambiguous between a daily value and a time
series"), and the model re-called with "steps_total" on the next turn
without any special-casing needed here — converse() only had to keep
feeding tool results back, the ambiguity handling itself lives entirely
in mcp_server.py and needed no awareness from this module.
"""

import ollama_client as oc
import mcp_client as mc
import openai_tool_schema as ots

# Ceiling on tool-calling round trips per converse() call, not a
# performance budget — SQLite-cache tool calls are fast (see
# mcp_client.py's own CALL_TIMEOUT reasoning), the real risk is a model
# that never converges (repeats the same wrong field, or keeps calling
# tools without ever answering). 8 gives headroom for a couple of
# realistic multi-step corrections in the same turn (e.g. an ambiguity
# retry AND a domain-confusion retry) without letting a genuinely stuck
# model spin unbounded — chosen as a starting value, not empirically
# tuned against many models/questions yet (that tuning is what
# question_catalog-style test runs are for, out of scope here).
MAX_TOOL_TURNS = 8

# Ported verbatim from GLA-NeedfulThings/mcp_test/config.py's
# SYSTEM_PROMPT (2026-08-29 finding): without ANY system prompt,
# qwen2.5-coder:14b repeatedly looped on an identical tool call instead
# of giving a final answer after already having the result — tool
# MATCHING was already correct, only conversation closure was missing.
# Deliberately pure flow-control, no tool-selection/parameter/data
# hints (that would contaminate a question catalog's own tool-matching
# test signal in that project — not a concern for converse() itself,
# but the wording is kept identical since it was empirically verified
# against thousands of real questions there). Not applied automatically
# — see the system_prompt parameter below; a caller with its own system
# message (e.g. the JSON-snapshot chat path's health_garmin_prompt.md)
# should not have it silently overridden.
DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant with access to tools. When you call a tool "
    "and receive its result, use that result to answer the user's "
    "question in natural language. Do not call the same tool again "
    "with the same arguments after you already have its result."
)


def converse(model: str, messages: list[dict],
             mcp_base_url: str = mc.DEFAULT_MCP_URL,
             max_tool_turns: int = MAX_TOOL_TURNS,
             ollama_timeout: float = oc.DEFAULT_TIMEOUT,
             mcp_timeout: float = mc.CALL_TIMEOUT,
             system_prompt: str | None = None) -> dict:
    """Runs the tool-calling turn loop to completion (or until
    max_tool_turns is reached) and returns:

        {
            "content": str,          # final assistant text (may be ""
                                      # if max_tool_turns was hit before
                                      # a text-only reply)
            "messages": list[dict],  # full updated history, including
                                      # every assistant/tool turn along
                                      # the way — caller's own messages
                                      # list is never mutated in place
            "hit_max_turns": bool,   # True if the loop stopped because
                                      # of the turn cap, not because the
                                      # model produced a final answer
        }

    A tool-execution failure (McpClientError from mcp_client.py — the
    server became unreachable mid-conversation, or a genuine
    McpToolError) is NOT raised here: it is fed back to the model as
    the tool result text (same shape mcp_server.py already uses for a
    degraded-but-successful result), so the model can react to it in
    natural language ("the archive query failed, ...") the same way
    real MCP clients (Open WebUI, Claude Desktop) already have to
    handle a tool error today. Only a failure fetching the tool list
    itself (before the loop even starts — the server was never
    reachable at all) propagates as a raised McpClientError, since
    there is no conversation yet to report it into.

    system_prompt: if given AND history has no existing system message
    (messages[0]["role"] == "system"), it is prepended as one — see
    DEFAULT_SYSTEM_PROMPT above for when to pass that constant here.
    Never overrides a caller-supplied system message; None (the
    default) injects nothing, matching converse()'s existing "caller
    controls messages" contract from before this parameter existed.

    A tool_calls-empty turn is not immediately treated as final: it is
    first checked against ollama_client.parse_content_fallback_tool_call()
    for a model that emitted its tool call as JSON text in content
    instead of natively — see that function's docstring. Only when
    that also finds nothing is the turn treated as the final answer.
    """
    tools = ots.to_openai_style_tools(mc.list_tools(base_url=mcp_base_url))
    history = list(messages)
    if system_prompt and not (history and history[0].get("role") == "system"):
        history.insert(0, {"role": "system", "content": system_prompt})
    last_content = ""

    for _ in range(max_tool_turns):
        assistant_msg = oc.chat_with_tools(
            model, history, tools, timeout=ollama_timeout)
        tool_calls = assistant_msg.get("tool_calls") or []
        last_content = assistant_msg.get("content", "")

        if not tool_calls:
            fallback = oc.parse_content_fallback_tool_call(last_content)
            if fallback is not None:
                tool_calls = [{"function": fallback}]

        history.append({
            "role": "assistant",
            "content": last_content,
            "tool_calls": tool_calls,
        })

        if not tool_calls:
            return {
                "content": assistant_msg.get("content", ""),
                "messages": history,
                "hit_max_turns": False,
            }

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            arguments = fn.get("arguments", {})
            try:
                result_text = mc.call_tool(
                    name, arguments, base_url=mcp_base_url, timeout=mcp_timeout)
            except mc.McpClientError as e:
                # Fed back as a normal tool result, not raised — see
                # docstring. The model treats "Tool error: ..." as any
                # other tool_result text; it commonly retries or
                # explains the failure to the user in its next turn.
                result_text = f"Tool error: {e}"
            history.append({
                "role": "tool",
                "content": result_text,
                "tool_call_id": call.get("id"),
            })

    return {
        "content": last_content,
        "messages": history,
        "hit_max_turns": True,
    }
