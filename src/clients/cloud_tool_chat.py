#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/cloud_tool_chat.py
Garmin Local Archive — Cloud LLM + MCP Tool-Calling Turn Loop

Cloud counterpart to clients/mcp_tool_chat.py's converse() — same
"Agentic Loop" building block, same overall shape (turn cap, tool
execution via clients/mcp_client.py, hit_max_turns reporting), but
sits on top of clients/cloud_llm_client.py's chat_with_tools() instead
of clients/ollama_client.py's. A deliberately separate file, not a
converse() parameter/generalization: mcp_tool_chat.py's converse() is
already live-verified and now has its own automated test suite
(tests/test_mcp_tool_chat.py) — duplicating the small loop skeleton
here keeps that already-working function completely untouched, same
"duplicate rather than risk working code" precedent as
ollama_client.py's chat()/chat_with_tools() split (see that module's
own docstring, PROTOKOLL_experiment.md "Baustein 2").

Provider-agnostic by construction: this file never imports a
cloud_llm_<provider>.py module directly, only clients/cloud_llm_client.py
(the dispatcher) — same "chat sees only the connector, never the
provider" contract app/panel_chat.py's plain-chat cloud path already
has. mcp_tools (clients/mcp_client.py's list_tools() result) is passed
through unmodified every turn; each provider module owns its own
schema translation internally (see cloud_llm_client.chat_with_tools()'s
own docstring) — unlike mcp_tool_chat.py, which translates the tool
list once before the loop starts, because Ollama only ever needs one
fixed schema shape.

No ollama_client.parse_content_fallback_tool_call()-style fallback
here: that workaround covers a real, empirically observed Ollama
quirk (some local models emit a tool call as JSON text in content
instead of the native tool_calls field) — official cloud SDKs report
tool calls natively and reliably, so there is nothing to fall back to.

Not live-verified against a real cloud provider in this session (no
API key available — see clients/cloud_llm_anthropic.py's/
cloud_llm_openai.py's own docstrings for the same limitation). Covered
by tests/test_cloud_tool_chat.py with clients/cloud_llm_client.chat_with_tools()
mocked, same discipline as clients/mcp_tool_chat.py had before its own
API-independent test suite existed.

converse_stream() (Baustein 22, Phase 2 Streaming, same session):
streaming counterpart to converse() above — same turn-loop shape and
error contract (see converse_stream()'s own docstring for the small
differences: progress reported as a sequence of events instead of one
returned dict). Cloud-only, same as clients/cloud_llm_anthropic.py's/
cloud_llm_openai.py's own chat_stream_with_tools() — clients/
mcp_tool_chat.py's converse() (the Ollama+MCP turn loop) has no
streaming counterpart at all, deliberately: Ollama's own
streaming+tool-calling combination is currently unreliable upstream,
see clients/ollama_client.py's own module docstring for the sourced
reasoning.
"""

import cloud_llm_client as clc
import mcp_client as mc

# Same value as clients/mcp_tool_chat.py's MAX_TOOL_TURNS — duplicated,
# not imported from that module (see module docstring: the two loops
# are deliberately independent, not coupled to each other, only to
# their respective chat_with_tools() dispatcher).
MAX_TOOL_TURNS = 8

# Same wording as clients/mcp_tool_chat.py's DEFAULT_SYSTEM_PROMPT —
# duplicated for the same independence reason above. The flow-control
# problem it addresses (a model that keeps calling tools instead of
# closing the conversation once it has an answer) is a property of
# agentic tool-calling in general, not specific to Ollama, so the same
# wording applies here even though the empirical finding that produced
# it (GLA-NeedfulThings/mcp_test, 2026-08-29) was Ollama-specific.
DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant with access to tools. When you call a tool "
    "and receive its result, use that result to answer the user's "
    "question in natural language. Do not call the same tool again "
    "with the same arguments after you already have its result."
)


def converse(provider: str, model: str, api_key: str, messages: list[dict],
             mcp_base_url: str = mc.DEFAULT_MCP_URL,
             max_tool_turns: int = MAX_TOOL_TURNS,
             mcp_timeout: float = mc.CALL_TIMEOUT,
             system_prompt: str | None = None) -> dict:
    """Runs the tool-calling turn loop to completion (or until
    max_tool_turns is reached) against a cloud provider and returns:

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

    Same shape clients/mcp_tool_chat.py's converse() returns — the two
    are interchangeable from app/panel_chat.py's point of view (both
    feed into that panel's own _chat_on_mcp_reply()).

    A tool-execution failure (McpClientError from mcp_client.py — the
    server became unreachable mid-conversation, or a genuine
    McpToolError) is NOT raised here: it is fed back to the model as
    the tool result text, so the model can react to it in natural
    language, same contract as clients/mcp_tool_chat.py's converse()
    (see that function's own docstring). Only a failure fetching the
    tool list itself (before the loop even starts) propagates as a
    raised McpClientError. A cloud_llm_client.CloudLlmError from the
    chat call itself (the provider unreachable, bad credentials, ...)
    is also not caught here — it propagates to the caller, same as an
    OllamaError would from clients/mcp_tool_chat.py's converse().

    system_prompt: if given AND history has no existing system message
    (messages[0]["role"] == "system"), it is prepended as one — see
    DEFAULT_SYSTEM_PROMPT above for when to pass that constant here.
    """
    mcp_tools = mc.list_tools(base_url=mcp_base_url)
    history = list(messages)
    if system_prompt and not (history and history[0].get("role") == "system"):
        history.insert(0, {"role": "system", "content": system_prompt})
    last_content = ""

    for _ in range(max_tool_turns):
        assistant_msg = clc.chat_with_tools(
            provider, model, api_key, history, mcp_tools)
        tool_calls = assistant_msg.get("tool_calls") or []
        last_content = assistant_msg.get("content", "")

        history.append({
            "role": "assistant",
            "content": last_content,
            "tool_calls": tool_calls,
        })

        if not tool_calls:
            return {
                "content": last_content,
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


def converse_stream(provider: str, model: str, api_key: str, messages: list[dict],
                     mcp_base_url: str = mc.DEFAULT_MCP_URL,
                     max_tool_turns: int = MAX_TOOL_TURNS,
                     mcp_timeout: float = mc.CALL_TIMEOUT,
                     system_prompt: str | None = None):
    """Streaming counterpart to converse() above (Baustein 22, Phase 2
    Streaming — Cloud+MCP only, see module docstring for why Ollama
    has no equivalent). Same turn-loop shape and error contract as
    converse() (tool-execution failures are still fed back to the
    model as text, never raised — only the initial mc.list_tools()
    failure propagates; a cloud_llm_client.CloudLlmError from a chat
    call also propagates, uncaught, same as converse()'s own
    contract), but each LLM turn is consumed as it streams in, and
    progress is reported as a sequence of small events instead of one
    dict at the end:

      {"type": "text", "text": str}       — an incremental text
          fragment for the turn currently in progress (zero of these
          on a turn that only calls tools, with no text of its own)
      {"type": "tool_call", "name": str}  — one per tool call the turn
          that just finished requested, emitted right after that turn
          completes and before the next turn's own text begins —
          app/panel_chat.py uses this as the cue to end the current
          chat bubble, show a marker, and start a new one for the next
          turn (see that module's _chat_on_send() Cloud+MCP worker)
      {"type": "final", "messages": [...], "hit_max_turns": bool}  —
          exactly one, always the LAST event yielded; same "messages"/
          "hit_max_turns" converse() itself returns (no "content" key
          here — the caller already has the full text of the last turn
          from its own "text" events, see app/panel_chat.py's
          _chat_on_mcp_stream_done())

    A generator function — nothing below runs until the caller starts
    iterating, same reasoning as clients/ollama_client.chat_stream()'s
    own docstring; app/panel_chat.py's worker always starts iterating
    immediately after calling this, inside its own try/except, so
    mc.list_tools()'s eager failure still surfaces exactly where the
    caller expects it, just one line later than converse()'s."""
    mcp_tools = mc.list_tools(base_url=mcp_base_url)
    history = list(messages)
    if system_prompt and not (history and history[0].get("role") == "system"):
        history.insert(0, {"role": "system", "content": system_prompt})

    hit_max_turns = True
    for _ in range(max_tool_turns):
        content_parts = []
        tool_calls = []
        for event in clc.chat_stream_with_tools(provider, model, api_key, history, mcp_tools):
            if event["type"] == "text":
                content_parts.append(event["text"])
                yield {"type": "text", "text": event["text"]}
            else:  # "done"
                tool_calls = event.get("tool_calls") or []
        last_content = "".join(content_parts)

        history.append({
            "role": "assistant",
            "content": last_content,
            "tool_calls": tool_calls,
        })

        if not tool_calls:
            hit_max_turns = False
            break

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            arguments = fn.get("arguments", {})
            yield {"type": "tool_call", "name": name}
            try:
                result_text = mc.call_tool(
                    name, arguments, base_url=mcp_base_url, timeout=mcp_timeout)
            except mc.McpClientError as e:
                result_text = f"Tool error: {e}"
            history.append({
                "role": "tool",
                "content": result_text,
                "tool_call_id": call.get("id"),
            })

    yield {"type": "final", "messages": history, "hit_max_turns": hit_max_turns}
