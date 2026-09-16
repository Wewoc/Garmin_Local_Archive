#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin/ollama_client.py
Garmin Local Archive — Ollama Chat Client

Leaf-Node. Wraps the local Ollama HTTP API (http://localhost:11434) for the
In-App Chat Panel (app/panel_chat.py). chat()/chat_with_tools() stay
non-streaming ("stream": false) — one request/response cycle per message
(see KONZEPT_ollama_chat_panel.md §2). chat_stream() below is the exception
(garmin_collector-3_experiment, Baustein 20, Phase 1 Streaming) — plain chat
only.

chat_with_tools() has NO streaming counterpart, and none is planned —
not "not yet built" but a deliberate, permanent gap (Baustein 22,
2026-09-15 session decision, Timo): Ollama's own streaming+tool-calling
combination is currently unreliable upstream (confirmed against a
High-severity open Ollama GitHub issue — with stream=true and tools
both set, tool_calls arrive as one complete block with NO accompanying
explanatory text, even when the model would normally produce some;
established client libraries work around this by forcing stream=false
whenever tools are involved, which is effectively what this project
already does). clients/cloud_llm_anthropic.py/cloud_llm_openai.py DO
get a chat_stream_with_tools() (Baustein 22) — their platforms do not
have this limitation; clients/mcp_tool_chat.py's converse() (the
Ollama+MCP turn loop) stays entirely non-streaming, unchanged.

No project-internal imports — stdlib + requests only. Raises typed exceptions
on every known failure mode; the caller (panel_chat.py) decides how each one
is presented in the UI. Never logs, never touches Qt.
"""

import json

import requests

OLLAMA_URL = "http://localhost:11434"

# Generous timeout — local models can take 15-60+ seconds, large models
# several minutes on modest hardware. Not a fixed small number (e.g. 120s) —
# that would abort legitimate large-model responses. Analog to ADA's own
# proxy timeout of up to 20 minutes (KONZEPT_ollama_chat_panel.md §2).
DEFAULT_TIMEOUT = 1200  # 20 minutes
PING_TIMEOUT    = 3.0
TAGS_TIMEOUT    = 5.0


class OllamaError(Exception):
    """Base class for all ollama_client errors."""


class OllamaUnreachable(OllamaError):
    """Ollama is not running / not reachable at OLLAMA_URL."""


class OllamaTimeout(OllamaError):
    """Request exceeded the timeout without a response."""


class OllamaModelNotFound(OllamaError):
    """Requested model is not installed / not returned by /api/tags."""


class OllamaContextLimitExceeded(OllamaError):
    """Ollama rejected the request — context window exceeded."""


def is_reachable(timeout: float = PING_TIMEOUT) -> bool:
    """Lightweight reachability check — GET /api/tags, response discarded.
    Used for the tab-open ping (KONZEPT §5) — no active chat prep here."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def list_models(timeout: float = TAGS_TIMEOUT) -> list[str]:
    """GET /api/tags — returns installed model names.
    Raises OllamaUnreachable if Ollama is not running. An empty list is a
    valid, non-error result — caller decides how to present "no models"."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise OllamaUnreachable(f"Ollama not reachable at {OLLAMA_URL}") from e

    data = resp.json()
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


def chat(model: str, messages: list[dict], timeout: float = DEFAULT_TIMEOUT) -> str:
    """POST /api/chat, non-streaming (KONZEPT §2).

    messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
    Returns the assistant's reply text. Raises a typed OllamaError subclass
    on every known failure mode — caller decides UI presentation.
    """
    payload = {"model": model, "messages": messages, "stream": False}

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise OllamaTimeout(f"Request to '{model}' timed out after {timeout:.0f}s") from e
    except requests.exceptions.RequestException as e:
        raise OllamaUnreachable(f"Ollama not reachable at {OLLAMA_URL}") from e

    if resp.status_code == 404:
        raise OllamaModelNotFound(f"Model not found: {model}")

    if resp.status_code == 400:
        # NOTE (flagged for review, not silently applied): Ollama's context-
        # limit error surfaces as a generic HTTP 400 with a free-text message
        # — there is no dedicated status code or typed field to key off of.
        # This substring check on the response body is the same class of
        # fragile string-classification the project's own DEPS-scan catalog
        # (K1) flags as a smell elsewhere. Kept narrow (only this one string
        # check, only to pick an error subclass — never used for control
        # flow beyond that) and isolated to this single call site so it is
        # easy to find and reconsider if Ollama's error format changes.
        body = ""
        try:
            body = str(resp.json().get("error", ""))
        except ValueError:
            body = resp.text
        if "context" in body.lower() or "too long" in body.lower():
            raise OllamaContextLimitExceeded(body or "Context limit exceeded")
        raise OllamaError(body or f"Ollama returned HTTP 400 for model '{model}'")

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"Ollama HTTP error {resp.status_code}: {resp.text}") from e

    data = resp.json()
    return data.get("message", {}).get("content", "")


def chat_stream(model: str, messages: list[dict], timeout: float = DEFAULT_TIMEOUT):
    """POST /api/chat, streaming ("stream": true) — Phase 1 Streaming
    (garmin_collector-3_experiment, Baustein 20). Same endpoint,
    payload shape, and typed-exception contract as chat() above; the
    body arrives as newline-delimited JSON objects instead of one
    combined response. Yields each incremental content fragment (str)
    as it arrives — the caller (app/panel_chat.py) concatenates them
    itself if it needs the full text.

    A generator function: none of the code below (including the
    request itself) runs until the caller starts iterating
    (`for chunk in chat_stream(...)`). This delays exactly when a
    failure surfaces (first `next()` instead of call time) but not
    whether it does — app/panel_chat.py's worker always starts
    iterating immediately after calling this, inside its own
    try/except, so the exception still lands exactly where the caller
    expects it.

    Deliberately a separate function from chat(), same "duplicate
    rather than touch already-tested code" precedent as
    chat_with_tools() above (see that function's own docstring). No
    streaming counterpart for chat_with_tools() — a tool call must be
    fully assembled (name + arguments) before it can be executed, so
    only the plain-text portion of a turn could ever stream; that is a
    separate, harder problem, deliberately deferred (see
    PROTOKOLL_experiment.md, Baustein 20)."""
    payload = {"model": model, "messages": messages, "stream": True}

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload,
                              timeout=timeout, stream=True)
    except requests.exceptions.Timeout as e:
        raise OllamaTimeout(f"Request to '{model}' timed out after {timeout:.0f}s") from e
    except requests.exceptions.RequestException as e:
        raise OllamaUnreachable(f"Ollama not reachable at {OLLAMA_URL}") from e

    if resp.status_code == 404:
        raise OllamaModelNotFound(f"Model not found: {model}")

    if resp.status_code == 400:
        # Same fragile-but-isolated substring check as chat() above —
        # see that function's own comment for the full reasoning.
        body = ""
        try:
            body = str(resp.json().get("error", ""))
        except ValueError:
            body = resp.text
        if "context" in body.lower() or "too long" in body.lower():
            raise OllamaContextLimitExceeded(body or "Context limit exceeded")
        raise OllamaError(body or f"Ollama returned HTTP 400 for model '{model}'")

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"Ollama HTTP error {resp.status_code}: {resp.text}") from e

    try:
        for line in resp.iter_lines():
            if not line:
                # Ollama's NDJSON stream can include blank keep-alive
                # lines between real chunks — skipped, not an error.
                continue
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
            if data.get("done"):
                break
    except requests.exceptions.RequestException as e:
        raise OllamaError(f"Streaming connection lost: {e}") from e
    finally:
        resp.close()


def parse_content_fallback_tool_call(content: str) -> dict | None:
    """Some models (confirmed: qwen2.5-coder:14b without a system
    prompt, GLA-NeedfulThings/mcp_test finding 2026-08-29) emit an
    otherwise-correct tool call not in Ollama's native
    message.tool_calls field, but as plain JSON text in message.content
    ('{"name": ..., "arguments": {...}}'). Open WebUI apparently
    tolerates/parses this itself; chat_with_tools() above does not —
    without this fallback, the call would be lost as an empty final
    answer. Ported near-verbatim from that project's
    mcp_llm_test_runner.py::_parse_content_fallback_tool_call(), which
    validated this exact shape against real model output across
    several thousand test questions — not a new guess.

    Deliberately strict: only when content, after strip(), parses as
    one complete JSON object with EXACTLY the keys "name" (str) and
    "arguments" (dict) is it treated as a tool-call candidate. Any
    deviation (not JSON, extra surrounding prose, missing/extra keys)
    returns None — a normal text answer that happens to contain a
    JSON-shaped fragment must never be misread as a tool call."""
    if not content or not content.strip():
        return None
    try:
        parsed = json.loads(content.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if set(parsed.keys()) != {"name", "arguments"}:
        return None
    if not isinstance(parsed["name"], str) or not isinstance(parsed["arguments"], dict):
        return None
    return parsed


def chat_with_tools(model: str, messages: list[dict], tools: list[dict],
                     timeout: float = DEFAULT_TIMEOUT) -> dict:
    """POST /api/chat with tools=..., non-streaming — same wire format
    and error handling as chat() above, but returns the raw assistant
    message dict instead of just its content string: a tool-calling
    turn needs to inspect message.get("tool_calls") to decide whether
    to call a tool or treat the turn as final, information chat()'s
    plain string return discards.

    Deliberately a separate function rather than an added tools=None
    parameter on chat() — chat() is exercised by test_app_logic.py
    Section 21 and used by the existing json-datasource chat path
    (KONZEPT_v1.7.2), neither of which ever needs tool-calling.
    Duplicating the small error-handling block here keeps that
    already-tested, already-working function completely untouched
    (session decision, garmin_collector-3_experiment — see
    PROTOKOLL_experiment.md, "Baustein 2").

    messages: same shape as chat(). tools: OpenAI-style tool-schema
    list, see clients/openai_tool_schema.py::to_openai_style_tools()
    (moved there from this file, garmin_collector-3_experiment —
    Ollama's tool-calling schema was never actually Ollama-specific,
    see that module's own docstring). Returns the raw {"role": ...,
    "content": ..., "tool_calls": [...]} dict — "tool_calls" is only
    present when the model actually requested one.
    """
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise OllamaTimeout(f"Request to '{model}' timed out after {timeout:.0f}s") from e
    except requests.exceptions.RequestException as e:
        raise OllamaUnreachable(f"Ollama not reachable at {OLLAMA_URL}") from e

    if resp.status_code == 404:
        raise OllamaModelNotFound(f"Model not found: {model}")

    if resp.status_code == 400:
        # Same fragile-but-isolated substring check as chat() above —
        # see that function's own comment for the full reasoning.
        # Deliberately duplicated, not imported/shared, for the same
        # "keep chat() untouched" reason as the rest of this function.
        body = ""
        try:
            body = str(resp.json().get("error", ""))
        except ValueError:
            body = resp.text
        if "context" in body.lower() or "too long" in body.lower():
            raise OllamaContextLimitExceeded(body or "Context limit exceeded")
        raise OllamaError(body or f"Ollama returned HTTP 400 for model '{model}'")

    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise OllamaError(f"Ollama HTTP error {resp.status_code}: {resp.text}") from e

    data = resp.json()
    return data.get("message", {})
