#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/cloud_llm_client.py
Garmin Local Archive — Cloud LLM Dispatcher

Leaf-Node. The single entry point app/panel_chat.py imports for
backend "cloud" — mirrors ollama_client.py's role for backend "ollama".
Never speaks to a provider API directly; looks up and delegates to the
matching cloud_llm_<provider>.py module, and normalizes both the reply
shape (plain str, same as ollama_client.chat()) and error handling
(one CloudLlmError type) so panel_chat.py never needs to know or care
which provider is actually configured.

Adding a new provider = adding a new cloud_llm_<name>.py module with a
chat(model, api_key, messages) -> str function (for MCP tool-calling, a
chat_with_tools(model, api_key, messages, mcp_tools) -> dict function;
for Phase 1 Streaming, a chat_stream(model, api_key, messages)
generator — see those functions below), and one line in _PROVIDERS
below. No change to panel_chat.py needed — this is the whole point of
the dispatcher split (garmin_collector-3_experiment, Cloud-LLM-Connector
Baustein, see PROTOKOLL_experiment.md).

Naming: cloud_llm_<provider>.py modules share this file's "cloud_llm_"
prefix deliberately, not just for readability — sorted alphabetically
in a file browser, the whole family clusters together as one visible
block (session decision, PROTOKOLL_experiment.md). Only this file
carries the "_client" suffix, mirroring the mcp_*.py family in this
same directory (mcp_client.py is the one of them app/panel_chat.py
imports directly; mcp_server.py/mcp_sql.py/etc. do not carry that
suffix, despite belonging to the same family) — the suffix marks "the
one callers outside this family import", not every member of it.
"""

import importlib

import frozen_paths

_PROVIDERS = {
    "anthropic": "cloud_llm_anthropic",
    "openai": "cloud_llm_openai",
}


class CloudLlmError(Exception):
    """Base class for all cloud_llm_client errors — the only exception
    type app/panel_chat.py needs to catch, regardless of provider."""


class CloudLlmConfigError(CloudLlmError):
    """Unknown/unsupported provider name (including a typo in the
    MCP-tab's free-text Provider field — see app/panel_mcp.py's
    _mcp_cloud_provider), or a missing model/API key."""


def _load_provider(provider: str):
    module_name = _PROVIDERS.get(provider)
    if module_name is None:
        known = ", ".join(sorted(_PROVIDERS)) or "(none)"
        raise CloudLlmConfigError(
            f"Unknown cloud provider '{provider}' — supported: {known}")
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    return importlib.import_module(module_name)


def chat(provider: str, model: str, api_key: str, messages: list[dict]) -> str:
    """Dispatches to the matching provider module's chat(), returns the
    assistant's plain-text reply.

    provider: free text as saved by app/panel_mcp.py's Cloud
        Credentials block — normalized (stripped, lower-cased) here so
        "Anthropic"/"ANTHROPIC "/"anthropic" all resolve the same way.
    messages: same shape as ollama_client.chat() —
        [{"role": "system"|"user"|"assistant", "content": str}, ...].
        Provider-specific translation (e.g. Anthropic's separate
        top-level system parameter instead of a role: "system" message)
        is each provider module's own responsibility, not this
        dispatcher's — see cloud_llm_anthropic.py's _split_system().

    Raises CloudLlmConfigError for an unknown provider or missing
    model/API key. Wraps every other failure (network, auth, a
    provider SDK's own exception type) into CloudLlmError, so the
    caller never needs a provider-specific except clause — same
    "caller decides UI presentation, this module only classifies"
    contract as ollama_client.py's typed exceptions.
    """
    provider = (provider or "").strip().lower()
    if not model or not api_key:
        raise CloudLlmConfigError("Missing model or API key")

    module = _load_provider(provider)
    try:
        return module.chat(model, api_key, messages)
    except CloudLlmError:
        raise
    except Exception as exc:
        raise CloudLlmError(f"{provider}: {exc}") from exc


def chat_with_tools(provider: str, model: str, api_key: str, messages: list[dict],
                     mcp_tools: list[dict]) -> dict:
    """Cloud+MCP-Tool-Calling counterpart to chat() above — same
    provider normalization/error-wrapping contract, dispatches to the
    matching module's chat_with_tools() instead. mcp_tools:
    clients/mcp_client.py's list_tools() result, provider-neutral —
    passed straight through unmodified; each provider module owns its
    own schema translation (cloud_llm_openai.py reuses
    clients/openai_tool_schema.py, cloud_llm_anthropic.py has its own
    to_anthropic_tools(), see that file's module docstring for why the
    two cannot share one) — this dispatcher stays as unopinionated
    about tool-schema shape as it already is about chat message shape.

    Returns the same normalized shape ollama_client.chat_with_tools()
    returns: {"content": str, "tool_calls": [{"id": str, "function":
    {"name": str, "arguments": dict}}, ...]} — clients/cloud_tool_chat.py's
    turn loop (mirrors clients/mcp_tool_chat.py's converse(), see that
    module's own docstring for why a parallel file rather than a
    generalized converse()) consumes this the same way regardless of
    which provider actually answered.
    """
    provider = (provider or "").strip().lower()
    if not model or not api_key:
        raise CloudLlmConfigError("Missing model or API key")

    module = _load_provider(provider)
    try:
        return module.chat_with_tools(model, api_key, messages, mcp_tools)
    except CloudLlmError:
        raise
    except Exception as exc:
        raise CloudLlmError(f"{provider}: {exc}") from exc


def chat_stream(provider: str, model: str, api_key: str, messages: list[dict]):
    """Streaming counterpart to chat() above (Phase 1 Streaming,
    garmin_collector-3_experiment, Baustein 20) — same provider
    normalization contract, dispatches to the matching module's own
    chat_stream() and yields its chunks through unchanged.

    A generator function: the provider/config validation below and the
    module lookup do NOT run until the caller starts iterating —
    unlike chat()/chat_with_tools() above, which raise immediately when
    called. Harmless in practice: app/panel_chat.py's worker always
    starts iterating right after calling this, inside its own
    try/except, so the exception still surfaces exactly where the
    caller expects it, just one line later than chat()'s.

    Wraps every failure raised during iteration into CloudLlmError,
    same as chat()/chat_with_tools() — but the try/except here must
    wrap the `for` loop itself, not just the call that creates the
    generator (module.chat_stream(...) returns immediately without
    raising, same generator-deferral as this function itself — see
    e.g. cloud_llm_openai.chat_stream()'s own docstring), or a failure
    raised mid-stream would never be caught.

    No streaming counterpart for chat_with_tools() — see
    chat_stream_with_tools() below (Baustein 22, Phase 2 Streaming)."""
    provider = (provider or "").strip().lower()
    if not model or not api_key:
        raise CloudLlmConfigError("Missing model or API key")

    module = _load_provider(provider)
    try:
        for chunk in module.chat_stream(model, api_key, messages):
            yield chunk
    except CloudLlmError:
        raise
    except Exception as exc:
        raise CloudLlmError(f"{provider}: {exc}") from exc


def chat_stream_with_tools(provider: str, model: str, api_key: str,
                            messages: list[dict], mcp_tools: list[dict]):
    """Streaming counterpart to chat_with_tools() above (Baustein 22,
    Phase 2 Streaming — Cloud+MCP only, see clients/ollama_client.py's
    module docstring for why Ollama has no equivalent). Same provider
    normalization contract and generator-deferral/exception-wrapping
    caveats as chat_stream() above (see that function's own docstring
    for both) — dispatches to the matching module's own
    chat_stream_with_tools() and yields its events through unchanged.
    mcp_tools: passed straight through unmodified, same as
    chat_with_tools() above."""
    provider = (provider or "").strip().lower()
    if not model or not api_key:
        raise CloudLlmConfigError("Missing model or API key")

    module = _load_provider(provider)
    try:
        for event in module.chat_stream_with_tools(model, api_key, messages, mcp_tools):
            yield event
    except CloudLlmError:
        raise
    except Exception as exc:
        raise CloudLlmError(f"{provider}: {exc}") from exc
