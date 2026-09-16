# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_cloud_tool_chat.py
Garmin Local Archive — Cloud LLM + MCP Tool-Calling Turn Loop Test Suite

Run with:
    pytest tests/test_cloud_tool_chat.py -v

Scope: clients/cloud_tool_chat.py's converse() — the cloud counterpart
to clients/mcp_tool_chat.py's own converse(), see that module's own
docstring for why the two are separate files rather than one
generalized loop. Same "separate lightweight file, no live API call"
reasoning as test_mcp_tool_chat.py/test_cloud_llm.py — no Anthropic/
OpenAI API key available in this session, so clients/cloud_llm_client.py
(clc) and clients/mcp_client.py (mc) are mocked throughout, same
module-level-alias patching approach test_mcp_tool_chat.py already
uses for oc/mc (converse() imports both as module-level aliases, not
via a lazy loader).

mcp_base_url/mcp_timeout are passed explicitly in every converse() call
below for the same reason as test_mcp_tool_chat.py: those defaults are
bound once, at function-definition time, against the REAL mcp_client
module — patching clients/cloud_tool_chat.py's mc later does not
change them.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import cloud_tool_chat

_URL = "http://test-mcp/mcp"
_TIMEOUT = 5.0


class TestConverse:

    def test_direct_answer_no_tool_call(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_with_tools.return_value = {
                "content": "Hello!", "tool_calls": []}

            result = cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "Hello!"
        assert result["hit_max_turns"] is False
        mock_clc.chat_with_tools.assert_called_once()

    def test_one_tool_call_then_final_answer(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = [
                {"name": "query_health", "description": "d", "inputSchema": {}}]
            mock_mc.call_tool.return_value = "steps: 8000"
            mock_clc.chat_with_tools.side_effect = [
                {"content": "", "tool_calls": [
                    {"id": "call_1", "function": {
                        "name": "query_health", "arguments": {"field": "steps"}}}]},
                {"content": "You took 8000 steps.", "tool_calls": []},
            ]

            result = cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "How many steps?"}],
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
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.return_value = "ok"
            mock_clc.chat_with_tools.return_value = {
                "content": "still working on it",
                "tool_calls": [{"id": "call_x", "function": {
                    "name": "query_health", "arguments": {}}}]}

            result = cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT, max_tool_turns=3)

        assert result["hit_max_turns"] is True
        assert result["content"] == "still working on it"
        assert mock_clc.chat_with_tools.call_count == 3

    def test_tool_execution_failure_fed_back_not_raised(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.side_effect = mock_mc.McpClientError(
                "server unreachable")
            mock_clc.chat_with_tools.side_effect = [
                {"content": "", "tool_calls": [
                    {"id": "call_1", "function": {
                        "name": "query_health", "arguments": {}}}]},
                {"content": "Sorry, that failed.", "tool_calls": []},
            ]

            result = cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        assert result["content"] == "Sorry, that failed."
        tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
        assert "Tool error: server unreachable" in tool_msgs[0]["content"]

    def test_tool_list_fetch_failure_propagates(self):
        # Unlike an in-loop tool-execution failure, an unreachable server
        # BEFORE the loop even starts has no conversation to report into
        # — it must raise, per converse()'s own docstring (same contract
        # as clients/mcp_tool_chat.py's converse()).
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc"):
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.side_effect = mock_mc.McpClientError("unreachable")

            with pytest.raises(mock_mc.McpClientError):
                cloud_tool_chat.converse(
                    "anthropic", "claude-sonnet-4-6", "sk-test",
                    [{"role": "user", "content": "hi"}],
                    mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

    def test_cloud_llm_error_from_chat_propagates(self):
        # The provider itself being unreachable/misconfigured is not a
        # tool-execution failure — it must propagate, same as an
        # OllamaError would from clients/mcp_tool_chat.py's converse()
        # (never caught inside that loop either).
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_clc.CloudLlmError = type("CloudLlmError", (Exception,), {})
            mock_mc.list_tools.return_value = []
            mock_clc.chat_with_tools.side_effect = mock_clc.CloudLlmError("bad key")

            with pytest.raises(mock_clc.CloudLlmError):
                cloud_tool_chat.converse(
                    "anthropic", "claude-sonnet-4-6", "sk-test",
                    [{"role": "user", "content": "hi"}],
                    mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

    def test_system_prompt_injected_when_history_has_none(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_with_tools.return_value = {
                "content": "hi", "tool_calls": []}

            cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="You are helpful.")

        sent_messages = mock_clc.chat_with_tools.call_args[0][3]
        assert sent_messages[0] == {"role": "system", "content": "You are helpful."}

    def test_system_prompt_not_injected_when_history_already_has_one(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_with_tools.return_value = {
                "content": "hi", "tool_calls": []}

            cloud_tool_chat.converse(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "system", "content": "Existing prompt."},
                 {"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="Should be ignored.")

        sent_messages = mock_clc.chat_with_tools.call_args[0][3]
        assert sent_messages[0] == {"role": "system", "content": "Existing prompt."}

    def test_passes_provider_and_raw_mcp_tools_through_unmodified(self):
        # cloud_tool_chat.py stays 100% provider-agnostic — mcp_tools
        # must reach cloud_llm_client.chat_with_tools() in their raw,
        # provider-neutral form; translation is each provider module's
        # own job (see cloud_tool_chat.py's own module docstring).
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            raw_tools = [{"name": "query_health", "description": "d",
                          "inputSchema": {"a": 1}}]
            mock_mc.list_tools.return_value = raw_tools
            mock_clc.chat_with_tools.return_value = {
                "content": "hi", "tool_calls": []}

            cloud_tool_chat.converse(
                "openai", "gpt-4.1", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT)

        args = mock_clc.chat_with_tools.call_args[0]
        assert args[0] == "openai"
        assert args[1] == "gpt-4.1"
        assert args[2] == "sk-test"
        assert args[4] == raw_tools


# ══════════════════════════════════════════════════════════════════════════════
#  converse_stream() (Baustein 22, Phase 2 Streaming — Cloud+MCP only)
# ══════════════════════════════════════════════════════════════════════════════

class TestConverseStream:

    def test_direct_answer_yields_text_then_final(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_stream_with_tools.return_value = iter([
                {"type": "text", "text": "Hel"},
                {"type": "text", "text": "lo!"},
                {"type": "done", "content": "Hello!", "tool_calls": []},
            ])

            events = list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

        text_events = [e for e in events if e["type"] == "text"]
        assert [e["text"] for e in text_events] == ["Hel", "lo!"]
        final = events[-1]
        assert final["type"] == "final"
        assert final["hit_max_turns"] is False
        assert final["messages"][-1] == {
            "role": "assistant", "content": "Hello!", "tool_calls": []}

    def test_tool_call_then_final_answer_two_turns(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = [
                {"name": "query_health", "description": "d", "inputSchema": {}}]
            mock_mc.call_tool.return_value = "steps: 8000"
            mock_clc.chat_stream_with_tools.side_effect = [
                iter([
                    {"type": "done", "content": "", "tool_calls": [
                        {"id": "call_1", "function": {
                            "name": "query_health", "arguments": {"field": "steps"}}}]},
                ]),
                iter([
                    {"type": "text", "text": "You took 8000 steps."},
                    {"type": "done", "content": "You took 8000 steps.", "tool_calls": []},
                ]),
            ]

            events = list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "How many steps?"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

        tool_call_events = [e for e in events if e["type"] == "tool_call"]
        assert tool_call_events == [{"type": "tool_call", "name": "query_health"}]
        # The tool_call event must be emitted BEFORE the second turn's text.
        tc_idx = events.index(tool_call_events[0])
        text_idx = next(i for i, e in enumerate(events) if e["type"] == "text")
        assert tc_idx < text_idx

        mock_mc.call_tool.assert_called_once_with(
            "query_health", {"field": "steps"}, base_url=_URL, timeout=_TIMEOUT)
        final = events[-1]
        assert final["type"] == "final"
        assert final["hit_max_turns"] is False
        tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
        assert tool_msgs[0]["content"] == "steps: 8000"
        assert tool_msgs[0]["tool_call_id"] == "call_1"

    def test_hit_max_turns_when_model_never_finalizes(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.return_value = "ok"
            # side_effect (a callable, not a fixed list) needs a fresh
            # iterator per call — a plain return_value would be
            # exhausted after the first turn.
            mock_clc.chat_stream_with_tools.side_effect = lambda *a, **k: iter([
                {"type": "done", "content": "still working on it",
                 "tool_calls": [{"id": "call_x", "function": {
                     "name": "query_health", "arguments": {}}}]},
            ])

            events = list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT, max_tool_turns=3))

        final = events[-1]
        assert final["type"] == "final"
        assert final["hit_max_turns"] is True
        assert mock_clc.chat_stream_with_tools.call_count == 3

    def test_tool_execution_failure_fed_back_not_raised(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.return_value = []
            mock_mc.call_tool.side_effect = mock_mc.McpClientError(
                "server unreachable")
            mock_clc.chat_stream_with_tools.side_effect = [
                iter([{"type": "done", "content": "", "tool_calls": [
                    {"id": "call_1", "function": {
                        "name": "query_health", "arguments": {}}}]}]),
                iter([{"type": "text", "text": "Sorry, that failed."},
                      {"type": "done", "content": "Sorry, that failed.",
                       "tool_calls": []}]),
            ]

            events = list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

        final = events[-1]
        tool_msgs = [m for m in final["messages"] if m["role"] == "tool"]
        assert "Tool error: server unreachable" in tool_msgs[0]["content"]

    def test_tool_list_fetch_failure_propagates(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc"):
            mock_mc.McpClientError = type("McpClientError", (Exception,), {})
            mock_mc.list_tools.side_effect = mock_mc.McpClientError("unreachable")

            with pytest.raises(mock_mc.McpClientError):
                list(cloud_tool_chat.converse_stream(
                    "anthropic", "claude-sonnet-4-6", "sk-test",
                    [{"role": "user", "content": "hi"}],
                    mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

    def test_cloud_llm_error_mid_stream_propagates(self):
        # A generator function's own failures surface during iteration,
        # not at call time — the for-loop inside converse_stream() must
        # still let this propagate uncaught, same contract as converse().
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_clc.CloudLlmError = type("CloudLlmError", (Exception,), {})
            mock_mc.list_tools.return_value = []

            def _boom(*a, **k):
                yield {"type": "text", "text": "partial"}
                raise mock_clc.CloudLlmError("bad key")

            mock_clc.chat_stream_with_tools.side_effect = _boom

            with pytest.raises(mock_clc.CloudLlmError):
                list(cloud_tool_chat.converse_stream(
                    "anthropic", "claude-sonnet-4-6", "sk-test",
                    [{"role": "user", "content": "hi"}],
                    mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

    def test_system_prompt_injected_when_history_has_none(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_stream_with_tools.return_value = iter([
                {"type": "done", "content": "hi", "tool_calls": []}])

            list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="You are helpful."))

        sent_messages = mock_clc.chat_stream_with_tools.call_args[0][3]
        assert sent_messages[0] == {"role": "system", "content": "You are helpful."}

    def test_system_prompt_not_injected_when_history_already_has_one(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            mock_mc.list_tools.return_value = []
            mock_clc.chat_stream_with_tools.return_value = iter([
                {"type": "done", "content": "hi", "tool_calls": []}])

            list(cloud_tool_chat.converse_stream(
                "anthropic", "claude-sonnet-4-6", "sk-test",
                [{"role": "system", "content": "Existing prompt."},
                 {"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT,
                system_prompt="Should be ignored."))

        sent_messages = mock_clc.chat_stream_with_tools.call_args[0][3]
        assert sent_messages[0] == {"role": "system", "content": "Existing prompt."}

    def test_passes_provider_and_raw_mcp_tools_through_unmodified(self):
        with patch("cloud_tool_chat.mc") as mock_mc, \
             patch("cloud_tool_chat.clc") as mock_clc:
            raw_tools = [{"name": "query_health", "description": "d",
                          "inputSchema": {"a": 1}}]
            mock_mc.list_tools.return_value = raw_tools
            mock_clc.chat_stream_with_tools.return_value = iter([
                {"type": "done", "content": "hi", "tool_calls": []}])

            list(cloud_tool_chat.converse_stream(
                "openai", "gpt-4.1", "sk-test",
                [{"role": "user", "content": "hi"}],
                mcp_base_url=_URL, mcp_timeout=_TIMEOUT))

        args = mock_clc.chat_stream_with_tools.call_args[0]
        assert args[0] == "openai"
        assert args[1] == "gpt-4.1"
        assert args[2] == "sk-test"
        assert args[4] == raw_tools
