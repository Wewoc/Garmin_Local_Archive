#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin/ollama_client.py
Garmin Local Archive — Ollama Chat Client

Leaf-Node. Wraps the local Ollama HTTP API (http://localhost:11434) for the
In-App Chat Panel (app/panel_chat.py). Non-streaming only ("stream": false) —
one request/response cycle per message, no token-by-token handling (see
KONZEPT_ollama_chat_panel.md §2).

No project-internal imports — stdlib + requests only. Raises typed exceptions
on every known failure mode; the caller (panel_chat.py) decides how each one
is presented in the UI. Never logs, never touches Qt.
"""

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
