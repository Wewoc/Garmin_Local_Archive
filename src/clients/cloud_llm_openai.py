#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/cloud_llm_openai.py
Garmin Local Archive — OpenAI Cloud LLM Provider

Internal to the cloud_llm_* family (see cloud_llm_client.py's own
docstring for the naming/split reasoning) — never imported directly by
app/panel_chat.py, only by clients/cloud_llm_client.py, the dispatcher.

Wraps the official `openai` Python SDK, same rationale as
cloud_llm_anthropic.py (see that file's own docstring and
requirements.txt's comment) — SDK version bumps absorb most of
OpenAI's own API-surface churn instead of requiring a rewrite here.

Unlike cloud_llm_anthropic.py, no message-shape translation is needed:
OpenAI's Chat Completions API already takes role: "system"/"user"/
"assistant" messages in one list — the same shape
app/panel_chat.py's self._history already uses (and the same shape
ollama_client.chat() consumes) — messages is passed straight through.
Its tool-calling shape is the same story: chat_with_tools() below
reuses clients/openai_tool_schema.py's to_openai_style_tools()
unchanged (see that module's own docstring — Ollama's schema was
modeled on OpenAI's) rather than defining its own translator.

chat() stays non-streaming ("one request/response cycle per message",
same scope as ollama_client.py/cloud_llm_anthropic.py's own chat()).
chat_stream() (Baustein 20, Phase 1 Streaming) and
chat_stream_with_tools() (Baustein 22, Phase 2 Streaming) are the
streaming exceptions — see cloud_llm_anthropic.py's own module
docstring for why this pair exists here and there, but not in
ollama_client.py (Ollama's own streaming+tool-calling combination is
currently unreliable upstream, not a limitation of this project).

Not live-verified against the real OpenAI API in this session (no API
key available, same limitation as cloud_llm_anthropic.py — see that
file's own docstring) — grounded against the installed SDK's own type
stubs (openai 3.14.0: Completions.create()'s signature, ChatCompletion/
Choice/ChatCompletionMessage field shapes, ChatCompletionMessage
ToolCall/Function field shapes for chat_with_tools()) instead of
guessed. Please verify against a real call before relying on this in
production.
"""

import json

import openai
import openai_tool_schema


def chat(model: str, api_key: str, messages: list[dict]) -> str:
    """messages: same shape as ollama_client.chat() — passed straight
    through, no translation needed (see module docstring). Returns the
    assistant's reply text from the first choice; falls back to "" if
    the model returned no text content (e.g. a refusal-only or
    tool-call-only response — chat() never passes tools=, but the SDK
    does not guarantee content is always set).

    Lets every openai.* exception propagate as-is —
    cloud_llm_client.chat() wraps it into CloudLlmError, so no error
    handling needed here (same "duplicate nothing, let the dispatcher
    normalize" split as the rest of the cloud_llm_* family)."""
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return response.choices[0].message.content or ""


def chat_stream(model: str, api_key: str, messages: list[dict]):
    """Streaming counterpart to chat() above (Phase 1 Streaming,
    garmin_collector-3_experiment, Baustein 20) — same message shape,
    no translation needed. Yields each incremental text fragment
    (str) from the SDK's own stream (openai 3.14.0:
    ChatCompletionChunk.choices[0].delta.content, confirmed against
    the installed SDK's own type stubs — ChoiceDelta.content is
    Optional[str], e.g. the very first chunk of a real stream
    typically carries only role="assistant", no content yet); the
    caller concatenates the yielded fragments itself if it needs the
    full text. A None/empty delta is skipped, not yielded.

    A generator function — nothing below runs until the caller starts
    iterating, same reasoning as ollama_client.chat_stream()'s own
    docstring. Every openai.* exception raised during iteration
    propagates as-is — cloud_llm_client.chat_stream() wraps it into
    CloudLlmError, same split as chat()/chat_with_tools() above.

    No streaming counterpart for chat_with_tools() — see
    ollama_client.chat_stream()'s own docstring for why tool-calling
    streaming is a separate, harder, still-deferred problem."""
    client = openai.OpenAI(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def chat_with_tools(model: str, api_key: str, messages: list[dict],
                     mcp_tools: list[dict]) -> dict:
    """messages: same shape as chat_with_tools()'s callers everywhere
    else in this project — [{"role": ..., "content": ...}, ...], with
    "tool_calls" on assistant turns and "tool_call_id" on tool turns
    (the shape clients/mcp_tool_chat.py's converse() already builds up
    turn by turn) — passed straight through unchanged, same as chat()
    above (see module docstring). mcp_tools: clients/mcp_client.py's
    list_tools() result, provider-neutral — translated here via
    openai_tool_schema.to_openai_style_tools(), not pre-translated by
    the caller (clients/cloud_tool_chat.py stays 100% provider-agnostic
    this way — every provider module owns its own translation, cloud_
    llm_anthropic.py's tool schema is a completely different shape).

    Returns the same normalized shape ollama_client.chat_with_tools()
    already returns: {"content": str, "tool_calls":
    [{"id": str, "function": {"name": str, "arguments": dict}}, ...]}
    — "tool_calls" is [] when the model answered without calling one.
    OpenAI's own tool_calls carry .function.arguments as a JSON string,
    not a dict (confirmed against the installed SDK's own
    ChatCompletionMessageFunctionToolCall/Function models) — parsed
    here so callers never need to know that detail.

    Lets every openai.*/json.JSONDecodeError exception propagate as-is
    — cloud_llm_client.chat_with_tools() wraps it into CloudLlmError."""
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=openai_tool_schema.to_openai_style_tools(mcp_tools),
    )
    message = response.choices[0].message
    tool_calls = [
        {
            "id": call.id,
            "function": {
                "name": call.function.name,
                "arguments": json.loads(call.function.arguments),
            },
        }
        for call in (message.tool_calls or [])
    ]
    return {"content": message.content or "", "tool_calls": tool_calls}


def chat_stream_with_tools(model: str, api_key: str, messages: list[dict],
                            mcp_tools: list[dict]):
    """Streaming counterpart to chat_with_tools() above (Baustein 22,
    Phase 2 Streaming — Cloud+MCP only, see module docstring for why
    Ollama has no equivalent). Yields the same small-event sequence
    clients/cloud_llm_anthropic.chat_stream_with_tools() does — see
    that function's own docstring for the shared {"type": "text", ...}
    / {"type": "done", ...} contract.

    Unlike Anthropic's SDK (see that file's own docstring), OpenAI's
    streaming tool_calls arrive genuinely fragmented and must be
    assembled by hand: each chunk's delta.tool_calls is a list of
    ChoiceDeltaToolCall entries keyed by "index" (confirmed against
    the installed SDK's own type stubs, openai 3.14.0) — a tool call's
    .id/.function.name typically arrive complete in its first chunk,
    while .function.arguments arrives as a JSON string split across
    many chunks and must be concatenated (not parsed) until the turn
    ends; only the fully concatenated string is valid JSON. Accumulated
    here in a dict keyed by index (name/arguments built with += for
    both — safe whether a field arrives whole in one chunk or split
    across several), finalized (json.loads() of the concatenated
    arguments) only in the "done" event below.

    A generator function — nothing below runs until the caller starts
    iterating, same reasoning as ollama_client.chat_stream()'s own
    docstring. Every openai.*/json.JSONDecodeError exception raised
    during iteration propagates as-is — cloud_llm_client.
    chat_stream_with_tools() wraps it into CloudLlmError."""
    client = openai.OpenAI(api_key=api_key)
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=openai_tool_schema.to_openai_style_tools(mcp_tools),
        stream=True,
    )
    content_parts = []
    calls_by_index: dict[int, dict] = {}
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            content_parts.append(delta.content)
            yield {"type": "text", "text": delta.content}
        for tc_delta in (delta.tool_calls or []):
            entry = calls_by_index.setdefault(
                tc_delta.index, {"id": None, "name": "", "arguments": ""})
            if tc_delta.id:
                entry["id"] = tc_delta.id
            if tc_delta.function:
                if tc_delta.function.name:
                    entry["name"] += tc_delta.function.name
                if tc_delta.function.arguments:
                    entry["arguments"] += tc_delta.function.arguments

    tool_calls = [
        {
            "id": entry["id"],
            "function": {
                "name": entry["name"],
                "arguments": json.loads(entry["arguments"]) if entry["arguments"] else {},
            },
        }
        for entry in calls_by_index.values()
    ]
    yield {"type": "done", "content": "".join(content_parts), "tool_calls": tool_calls}
