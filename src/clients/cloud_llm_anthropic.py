#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/cloud_llm_anthropic.py
Garmin Local Archive — Anthropic Cloud LLM Provider

Internal to the cloud_llm_* family (see cloud_llm_client.py's own
docstring for the naming/split reasoning) — never imported directly by
app/panel_chat.py, only by clients/cloud_llm_client.py, the dispatcher.

Wraps the official `anthropic` Python SDK (see requirements.txt's own
comment) rather than a hand-rolled requests client — deliberate choice,
see PROTOKOLL_experiment.md's Cloud-LLM-Connector Baustein entry: most
of Anthropic's own API-surface churn (endpoint paths, headers, request/
response shape) is then absorbed by SDK version bumps instead of
requiring a rewrite here; only a major SDK version jump would still
need this file touched.

chat() stays non-streaming ("one request/response cycle per message",
same scope as ollama_client.py's own chat()). chat_stream() (Baustein
20, Phase 1 Streaming) and chat_stream_with_tools() (Baustein 22,
Phase 2 Streaming) are the streaming exceptions — the latter exists
here and in cloud_llm_openai.py only, not ollama_client.py: Ollama's
own streaming+tool-calling combination is currently unreliable
upstream (confirmed against a High-severity open Ollama issue,
2026-09-15 — tool_calls arrive as one block with no accompanying text,
not a per-provider limitation here, an Ollama one), so
clients/mcp_tool_chat.py's converse() has no streaming counterpart by
deliberate choice, see clients/cloud_tool_chat.py's own module
docstring.

Not live-verified against the real Anthropic API in this session (no
API key available) — grounded against the installed SDK's own type
stubs (anthropic 1.5.0: Messages.create()'s signature, Message.content
block shapes, and for chat_with_tools() below: ToolParam,
ToolUseBlock/ToolUseBlockParam, ToolResultBlockParam, TextBlockParam,
MessageParam field shapes) instead of guessed. Please verify against a
real call before relying on this in production.

chat_with_tools() needs real two-way translation, unlike
cloud_llm_openai.py's version (which reuses clients/openai_tool_schema.py
unchanged): Anthropic's tool-calling shape genuinely differs from the
OpenAI-style one Ollama/OpenAI share — tool calls are content blocks
embedded inside an assistant message (not a separate "tool_calls" key),
tool results go back as a "tool_result" content block inside a *user*
message (not a separate "tool"-role message), and the tool schema
itself uses "input_schema" instead of "parameters". See
_history_to_anthropic() and to_anthropic_tools() below.
"""

import anthropic

# Anthropic requires an explicit cap, unlike Ollama's optional default —
# generous enough for a normal chat reply, not a runaway-cost guard
# (KONZEPT_v1.7.2 does not specify one; revisit if that becomes a concern).
MAX_TOKENS = 4096


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Anthropic's Messages API takes the system prompt as a separate
    top-level parameter, not as a role: "system" entry inside messages
    like Ollama's shape (the one app/panel_chat.py's self._history
    already uses) — this is the one required translation step for
    plain chat. Multiple system-role entries (should not normally
    happen — panel_chat.py only ever seeds one) are joined rather than
    only the first taken, so nothing is silently dropped if it ever
    does.

    Filters rather than rebuilding each dict (Cloud+MCP-Tool-Calling
    groundwork, garmin_collector-3_experiment) — chat()'s plain-chat
    messages only ever have "role"/"content" anyway, so this is
    behavior-preserving for that caller, but chat_with_tools() below
    needs the "tool_calls"/"tool_call_id" keys a role/content-only
    rebuild would have silently dropped."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    converted = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(system_parts), converted


def chat(model: str, api_key: str, messages: list[dict]) -> str:
    """messages: same shape as ollama_client.chat(). Returns the
    assistant's reply text — concatenates every text content block
    (Message.content is a list of typed blocks; a plain-chat reply is
    normally exactly one TextBlock, but this does not assume that).

    Lets every anthropic.* exception propagate as-is —
    cloud_llm_client.chat() wraps it into CloudLlmError, so no error
    handling needed here (same "duplicate nothing, let the dispatcher
    normalize" split as the rest of the cloud_llm_* family)."""
    system, converted = _split_system(messages)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=converted,
    )
    return "".join(
        block.text for block in response.content if block.type == "text")


def chat_stream(model: str, api_key: str, messages: list[dict]):
    """Streaming counterpart to chat() above (Phase 1 Streaming,
    garmin_collector-3_experiment, Baustein 20) — same message shape
    and system-prompt split (_split_system()) as chat(). Yields each
    incremental text fragment (str) as the SDK's own text_stream
    delivers it (anthropic 1.5.0: MessageStream.text_stream, confirmed
    against the installed SDK's source —
    anthropic.lib.streaming._messages.MessageStream: a plain
    Iterator[str] that already filters the raw server-sent-event
    stream down to just the content_block_delta/text_delta pieces via
    its own __stream_text__()); the caller concatenates them itself if
    it needs the full text.

    A generator function — nothing below runs until the caller starts
    iterating, same reasoning as ollama_client.chat_stream()'s own
    docstring. Every anthropic.* exception raised during iteration
    propagates as-is — cloud_llm_client.chat_stream() wraps it into
    CloudLlmError, same split as chat()/chat_with_tools() above.

    No streaming counterpart for chat_with_tools() — see
    ollama_client.chat_stream()'s own docstring for why tool-calling
    streaming is a separate, harder, still-deferred problem."""
    system, converted = _split_system(messages)
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=converted,
    ) as stream:
        for text in stream.text_stream:
            yield text


def to_anthropic_tools(mcp_tools: list[dict]) -> list[dict]:
    """Reshapes clients/mcp_client.py's list_tools() result into
    Anthropic's own tool schema: {"name", "description", "input_schema"}
    per tool (confirmed against the installed SDK's ToolParam type —
    "input_schema", not "parameters" like the OpenAI-style shape
    clients/openai_tool_schema.py produces). Anthropic-specific,
    deliberately not added to that shared module — see this file's own
    module docstring for why Anthropic does not share that shape."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]


def _history_to_anthropic(messages: list[dict]) -> list[dict]:
    """Translates the common tool-calling history shape clients/
    cloud_tool_chat.py's turn loop builds up (same shape
    clients/mcp_tool_chat.py's converse() already uses: role "user"/
    "assistant"/"tool", assistant turns carry "tool_calls", tool turns
    carry "tool_call_id") into Anthropic's own MessageParam list —
    the other half of the two-way translation this file's module
    docstring describes. system-role entries must already be removed
    (via _split_system() above) before this is called.

    - "user" -> passed through as a plain-string-content message
    - "assistant" with no tool_calls -> a single text content block
    - "assistant" with tool_calls -> a text block (if any content) plus
      one "tool_use" block per call, carrying that call's own id/name/
      arguments (input) — Anthropic needs the id again on the matching
      tool_result below, same role clients/mcp_tool_chat.py's own
      "tool_call_id" already plays
    - "tool" -> Anthropic has no separate tool-result role: it must be
      a "tool_result" content block inside a *user* message. Multiple
      tool turns in a row (one assistant turn called more than one
      tool) are merged into a SINGLE user message with multiple
      tool_result blocks, not one user message per result — sending
      them as separate consecutive user messages is not a shape the
      API accepts for multi-tool-call turns.
    """
    result: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "user":
            result.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            blocks = []
            content = m.get("content", "")
            if content:
                blocks.append({"type": "text", "text": content})
            for call in (m.get("tool_calls") or []):
                fn = call.get("function", {})
                blocks.append({
                    "type": "tool_use",
                    "id": call.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": fn.get("arguments", {}),
                })
            result.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            }
            if (result and result[-1]["role"] == "user"
                    and isinstance(result[-1]["content"], list)):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})
    return result


def chat_with_tools(model: str, api_key: str, messages: list[dict],
                     mcp_tools: list[dict]) -> dict:
    """messages: same shape as clients/ollama_client.py's
    chat_with_tools() and clients/cloud_llm_openai.py's chat_with_tools()
    — see _history_to_anthropic()'s own docstring for the full shape
    and how it maps onto Anthropic's Messages API. mcp_tools:
    clients/mcp_client.py's list_tools() result, provider-neutral —
    translated here via to_anthropic_tools() above, not pre-translated
    by the caller (clients/cloud_tool_chat.py stays 100%
    provider-agnostic this way, same split as cloud_llm_openai.py's own
    chat_with_tools()).

    Returns the same normalized shape ollama_client.chat_with_tools()/
    cloud_llm_openai.chat_with_tools() already return: {"content": str,
    "tool_calls": [{"id": str, "function": {"name": str,
    "arguments": dict}}, ...]} — "tool_calls" is [] when the model
    answered without calling one. response.content can hold several
    tool_use blocks (a model may request more than one tool per turn)
    plus at most one text block in practice; every block is handled,
    not just the first.

    Lets every anthropic.* exception propagate as-is —
    cloud_llm_client.chat_with_tools() wraps it into CloudLlmError."""
    system, converted = _split_system(messages)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=_history_to_anthropic(converted),
        tools=to_anthropic_tools(mcp_tools),
    )

    content_parts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            content_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "function": {"name": block.name, "arguments": block.input},
            })

    return {"content": "".join(content_parts), "tool_calls": tool_calls}


def chat_stream_with_tools(model: str, api_key: str, messages: list[dict],
                            mcp_tools: list[dict]):
    """Streaming counterpart to chat_with_tools() above (Baustein 22,
    Phase 2 Streaming — Cloud+MCP only, see module docstring for why
    Ollama has no equivalent). Yields a sequence of small events
    instead of returning one dict at the end:

      {"type": "text", "text": str}   — a text delta, in arrival order
      {"type": "done", "content": str, "tool_calls": [...]}   —
          exactly one, always last; "content" is the concatenation of
          every "text" event's own text (handed back here too, so a
          caller that only wants the final shape need not accumulate
          it itself); "tool_calls" is the same normalized shape
          chat_with_tools() above already returns.

    Anthropic's own streaming event union
    (anthropic.lib.streaming._types.MessageStreamEvent, confirmed
    against the installed SDK's source, same "confirmed not guessed"
    discipline as ollama_client.chat_stream()'s own docstring) already
    does almost all the accumulation work: TextEvent carries both the
    delta (.text) and the running total (.snapshot) for its content
    block; ContentBlockStopEvent carries the fully finished
    content_block (text or tool_use) once that block closes. Iterated
    here directly (`for event in stream`), NOT via stream.text_stream
    (chat_stream()'s own approach) — that helper only surfaces
    TextEvents' .text and silently discards tool_use blocks entirely,
    which chat_stream() can afford but this function cannot.

    A generator function — nothing below runs until the caller starts
    iterating, same reasoning as ollama_client.chat_stream()'s own
    docstring. Every anthropic.* exception raised during iteration
    propagates as-is — cloud_llm_client.chat_stream_with_tools() wraps
    it into CloudLlmError."""
    system, converted = _split_system(messages)
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=_history_to_anthropic(converted),
        tools=to_anthropic_tools(mcp_tools),
    ) as stream:
        content_parts = []
        tool_calls = []
        for event in stream:
            if event.type == "text":
                content_parts.append(event.text)
                yield {"type": "text", "text": event.text}
            elif event.type == "content_block_stop":
                block = event.content_block
                if block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "function": {"name": block.name, "arguments": block.input},
                    })
        yield {"type": "done", "content": "".join(content_parts), "tool_calls": tool_calls}
