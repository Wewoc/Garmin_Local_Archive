# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_mcp_tool_chat.py
Garmin Local Archive — MCP Tool-Calling Turn Loop Test Suite

Run with:
    pytest tests/test_mcp_tool_chat.py -v

Scope: clients/mcp_tool_chat.py's converse() turn loop and
clients/openai_tool_schema.py's to_openai_style_tools() — plain
Python, no Qt, same "separate lightweight file" reasoning as
test_cloud_llm.py. Previously verified only live against the real
running stack (see PROTOKOLL_experiment.md, Bausteine 1-4) — this is
the first automated regression coverage for either module, added
alongside the to_ollama_tools() -> openai_tool_schema.py extraction so
the refactor has a real safety net going forward (the refactor itself
was additionally live-verified once against the real MCP server +
Ollama before this file existed — see PROTOKOLL_experiment.md).

ollama_client/mcp_client are imported by mcp_tool_chat.py as module-
level oc/mc aliases, not via a lazy loader like app/panel_chat.py uses
— patched as mcp_tool_chat.oc.*/mcp_tool_chat.mc.* accordingly.
mcp_base_url/mcp_timeout are passed explicitly in every converse() call
below rather than left at their defaults: those defaults
(mc.DEFAULT_MCP_URL/mc.CALL_TIMEOUT) are bound once, at function-
definition time, against the REAL mcp_client module — patching
mcp_tool_chat.mc later does not change them, so asserting against the
mock's own (auto-generated) attributes for an unpassed default would
silently compare against the wrong values.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import mcp_tool_chat
import openai_tool_schema

_URL = "http://test-mcp/mcp"
_TIMEOUT = 5.0


# ══════════════════════════════════════════════════════════════════════════════
#  openai_tool_schema.py
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenaiToolSchema:

    def test_reshapes_mcp_tool_list(self):
        mcp_tools = [
            {"name": "query_health", "description": "Query health data.",
             "inputSchema": {"type": "object",
                              "properties": {"field": {"type": "string"}}}},
        ]
        result = openai_tool_schema.to_openai_style_tools(mcp_tools)
        assert result == [{
            "type": "function",
            "function": {
                "name": "query_health",
                "description": "Query health data.",
                "parameters": {"type": "object",
                                "properties": {"field": {"type": "string"}}},
            },
        }]

    def test_empty_list(self):
        assert openai_tool_schema.to_openai_style_tools([]) == []

    def test_preserves_order_for_multiple_tools(self):
        mcp_tools = [
            {"name": "a", "description": "A", "inputSchema": {}},
            {"name": "b", "description": "B", "inputSchema": {}},
        ]
        result = openai_tool_schema.to_openai_style_tools(mcp_tools)
        assert [t["function"]["name"] for t in result] == ["a", "b"]


# ══════════════════════════════════════════════════════════════════════════════
#  mcp_tool_chat.py — converse()
# ══════════════════════════════════════════════════════════════════════════════

class TestConverse:

    def test_direct_answer_no_tool_call(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = []
            mock_oc.chat_with_tools.return_value = {
                "role": "assistant", "content": "Hello!", "tool_calls": []}
            mock_oc.parse_content_fallback_tool_call.return_value = None

            result = mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "Hello!"
        assert result["hit_max_turns"] is False
        mock_oc.chat_with_tools.assert_called_once()

    def test_one_tool_call_then_final_answer(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = [
                {"name": "query_health", "description": "d", "inputSchema": {}}]
            mock_mc.call_tool.return_value = "steps: 8000"
            mock_oc.chat_with_tools.side_effect = [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call_1", "function": {
                        "name": "query_health", "arguments": {"field": "steps"}}}]},
                {"role": "assistant", "content": "You took 8000 steps.",
                 "tool_calls": []},
            ]
            mock_oc.parse_content_fallback_tool_call.return_value = None

            result = mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "How many steps?"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "You took 8000 steps."
        assert result["hit_max_turns"] is False
        mock_mc.call_tool.assert_called_once_with(
            "query_health", {"field": "steps"}, base_url=_URL, timeout=_TIMEOUT)
        tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "steps: 8000"
        assert tool_msgs[0]["tool_call_id"] == "call_1"

    def test_hit_max_turns_when_model_never_finalizes(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.return_value = "ok"
            mock_oc.chat_with_tools.return_value = {
                "role": "assistant", "content": "still working on it",
                "tool_calls": [{"id": "call_x", "function": {
                    "name": "query_health", "arguments": {}}}]}
            mock_oc.parse_content_fallback_tool_call.return_value = None

            result = mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT, max_tool_turns=3)

        assert result["hit_max_turns"] is True
        assert result["content"] == "still working on it"
        assert mock_oc.chat_with_tools.call_count == 3

    def test_content_fallback_tool_call_used_when_native_empty(self):
        # Some models emit a tool call as JSON text in content instead of
        # the native tool_calls field — see
        # ollama_client.parse_content_fallback_tool_call()'s own
        # docstring for the real-world finding this covers.
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.return_value = "42"
            mock_oc.chat_with_tools.side_effect = [
                {"role": "assistant",
                 "content": '{"name": "query_health", "arguments": {"field": "steps"}}',
                 "tool_calls": []},
                {"role": "assistant", "content": "The answer is 42.",
                 "tool_calls": []},
            ]
            mock_oc.parse_content_fallback_tool_call.side_effect = [
                {"name": "query_health", "arguments": {"field": "steps"}},
                None,
            ]

            result = mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "The answer is 42."
        mock_mc.call_tool.assert_called_once_with(
            "query_health", {"field": "steps"}, base_url=_URL, timeout=_TIMEOUT)

    def test_tool_execution_failure_fed_back_not_raised(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.side_effect = mock_mc.McpClientError(
                "server unreachable")
            mock_oc.chat_with_tools.side_effect = [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call_1", "function": {
                        "name": "query_health", "arguments": {}}}]},
                {"role": "assistant", "content": "Sorry, that failed.",
                 "tool_calls": []},
            ]
            mock_oc.parse_content_fallback_tool_call.return_value = None

            result = mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "Sorry, that failed."
        tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
        assert "Tool error: server unreachable" in tool_msgs[0]["content"]

    def test_tool_list_fetch_failure_propagates(self):
        # Unlike an in-loop tool-execution failure, an unreachable server
        # BEFORE the loop even starts has no conversation to report into
        # — it must raise, per converse()'s own docstring.
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc"):
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.side_effect = mock_mc.McpClientError("unreachable")

            with pytest.raises(mock_mc.McpClientError):
                mcp_tool_chat.converse(
                    "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                    mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

    def test_system_prompt_injected_when_history_has_none(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = []
            mock_oc.chat_with_tools.return_value = {
                "role": "assistant", "content": "hi", "tool_calls": []}
            mock_oc.parse_content_fallback_tool_call.return_value = None

            mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="You are helpful.")

        sent_messages = mock_oc.chat_with_tools.call_args[0][1]
        assert sent_messages[0] == {"role": "system", "content": "You are helpful."}

    def test_system_prompt_not_injected_when_history_already_has_one(self):
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = []
            mock_oc.chat_with_tools.return_value = {
                "role": "assistant", "content": "hi", "tool_calls": []}
            mock_oc.parse_content_fallback_tool_call.return_value = None

            mcp_tool_chat.converse(
                "qwen3:1.7b",
                [{"role": "system", "content": "Existing prompt."},
                 {"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="Should be ignored.")

        sent_messages = mock_oc.chat_with_tools.call_args[0][1]
        assert sent_messages[0] == {"role": "system", "content": "Existing prompt."}

    def test_uses_openai_style_tool_schema(self):
        # converse() must translate the MCP tool list via
        # openai_tool_schema.to_openai_style_tools(), not build its own
        # ad-hoc shape — this is the regression check for the Baustein
        # 17 extraction (to_ollama_tools() moved out of ollama_client.py).
        with patch("mcp_tool_chat.mc") as mock_mc, \
             patch("mcp_tool_chat.oc") as mock_oc:
            mock_mc.list_tools.return_value = [
                {"name": "query_health", "description": "d", "inputSchema": {"a": 1}}]
            mock_oc.chat_with_tools.return_value = {
                "role": "assistant", "content": "hi", "tool_calls": []}
            mock_oc.parse_content_fallback_tool_call.return_value = None

            mcp_tool_chat.converse(
                "qwen3:1.7b", [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        sent_tools = mock_oc.chat_with_tools.call_args[0][2]
        assert sent_tools == [{
            "type": "function",
            "function": {"name": "query_health", "description": "d",
                          "parameters": {"a": 1}},
        }]
