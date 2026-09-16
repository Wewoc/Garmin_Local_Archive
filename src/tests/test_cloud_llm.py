# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_cloud_llm.py
Garmin Local Archive — Cloud LLM Connector Test Suite

Run with:
    pytest tests/test_cloud_llm.py -v

Scope: clients/cloud_llm_client.py (dispatcher), clients/
cloud_llm_anthropic.py and clients/cloud_llm_openai.py (providers) —
plain Python, no Qt involved, so a separate lightweight file rather
than test_qt_app.py (Qt-specific scope) or test_app_logic.py (heavier
script-style harness importing the full garmin_app_base stack —
unrelated to these leaf-node modules, which have no project-internal
imports besides frozen_paths). conftest.py's shared sys.path does not
include clients/ (app/panel_chat.py's own lazy loaders add it via
frozen_paths instead) — added locally here, same as test_app_logic.py's
own Section 21 setup for ollama_client.py.

No live API call anywhere in this file — no Anthropic/OpenAI API key
available in this session (see cloud_llm_anthropic.py's / cloud_llm_
openai.py's own docstrings). Every SDK client call is mocked.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import cloud_llm_client
import cloud_llm_anthropic
import cloud_llm_openai


# ══════════════════════════════════════════════════════════════════════════════
#  cloud_llm_client.py — dispatcher
# ══════════════════════════════════════════════════════════════════════════════

class TestCloudLlmClient:

    def test_unknown_provider_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat("not-a-real-provider", "some-model",
                                   "key", [{"role": "user", "content": "hi"}])

    def test_unknown_provider_message_lists_known_providers(self):
        # "gemini" specifically, not a real _PROVIDERS entry — do not
        # reuse a name that might become a real provider later (that
        # already bit "openai" once, see Baustein 15).
        with pytest.raises(cloud_llm_client.CloudLlmConfigError, match="anthropic"):
            cloud_llm_client._load_provider("gemini")

    def test_missing_model_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat("anthropic", "", "key", [])

    def test_missing_api_key_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat("anthropic", "claude-sonnet-4-6", "", [])

    def test_provider_name_is_normalized(self):
        # "Anthropic"/"ANTHROPIC "/"anthropic" must all resolve the same
        # way — the MCP tab's Provider field is free text (see
        # app/panel_mcp.py's _mcp_cloud_provider).
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat.return_value = "hi there"
            load_provider.return_value = mock_module
            cloud_llm_client.chat("  Anthropic ", "claude-sonnet-4-6",
                                   "key", [{"role": "user", "content": "hi"}])
        load_provider.assert_called_once_with("anthropic")

    def test_successful_dispatch_returns_provider_reply(self):
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat.return_value = "hi there"
            load_provider.return_value = mock_module
            reply = cloud_llm_client.chat(
                "anthropic", "claude-sonnet-4-6", "key",
                [{"role": "user", "content": "hi"}])
        assert reply == "hi there"

    def test_provider_exception_wrapped_into_cloud_llm_error(self):
        # panel_chat.py's worker only ever catches CloudLlmError, regardless
        # of provider — a raw RuntimeError from a provider module must not
        # leak past the dispatcher.
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat.side_effect = RuntimeError("boom")
            load_provider.return_value = mock_module
            with pytest.raises(cloud_llm_client.CloudLlmError):
                cloud_llm_client.chat("anthropic", "claude-sonnet-4-6",
                                       "key", [{"role": "user", "content": "hi"}])

    def test_openai_is_a_registered_provider(self):
        # Baustein 15 — _load_provider() must resolve "openai" to the
        # real cloud_llm_openai module, not raise CloudLlmConfigError.
        module = cloud_llm_client._load_provider("openai")
        assert module is cloud_llm_openai

    # ── chat_with_tools() dispatch (Baustein 18) ─────────────────────────

    def test_chat_with_tools_unknown_provider_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat_with_tools(
                "not-a-real-provider", "some-model", "key", [], [])

    def test_chat_with_tools_missing_model_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat_with_tools("anthropic", "", "key", [], [])

    def test_chat_with_tools_missing_api_key_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            cloud_llm_client.chat_with_tools(
                "anthropic", "claude-sonnet-4-6", "", [], [])

    def test_chat_with_tools_successful_dispatch_passes_mcp_tools_through(self):
        # mcp_tools must reach the provider module unmodified — schema
        # translation is each provider's own job, not this dispatcher's
        # (see chat_with_tools()'s own docstring).
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_with_tools.return_value = {
                "content": "hi", "tool_calls": []}
            load_provider.return_value = mock_module
            mcp_tools = [{"name": "t", "description": "d", "inputSchema": {}}]

            result = cloud_llm_client.chat_with_tools(
                "anthropic", "claude-sonnet-4-6", "key",
                [{"role": "user", "content": "hi"}], mcp_tools)

        assert result == {"content": "hi", "tool_calls": []}
        mock_module.chat_with_tools.assert_called_once_with(
            "claude-sonnet-4-6", "key",
            [{"role": "user", "content": "hi"}], mcp_tools)

    def test_chat_with_tools_provider_exception_wrapped(self):
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_with_tools.side_effect = RuntimeError("boom")
            load_provider.return_value = mock_module
            with pytest.raises(cloud_llm_client.CloudLlmError):
                cloud_llm_client.chat_with_tools(
                    "anthropic", "claude-sonnet-4-6", "key", [], [])

    # ── chat_stream() dispatch (Baustein 20, Phase 1 Streaming) ───────────

    def test_chat_stream_unknown_provider_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream(
                "not-a-real-provider", "some-model", "key", []))

    def test_chat_stream_missing_model_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream("anthropic", "", "key", []))

    def test_chat_stream_missing_api_key_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream(
                "anthropic", "claude-sonnet-4-6", "", []))

    def test_chat_stream_yields_provider_chunks(self):
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_stream.return_value = iter(["Hel", "lo"])
            load_provider.return_value = mock_module
            chunks = list(cloud_llm_client.chat_stream(
                "anthropic", "claude-sonnet-4-6", "key",
                [{"role": "user", "content": "hi"}]))
        assert chunks == ["Hel", "lo"]

    def test_chat_stream_exception_during_iteration_wrapped_into_cloud_llm_error(self):
        # The case chat()/chat_with_tools() don't have to handle: the
        # provider's chat_stream() is itself a generator, so a failure
        # can surface mid-iteration, not just at call time — the
        # try/except here must wrap the for-loop, not just the call
        # that creates the generator (see chat_stream()'s own
        # docstring).
        def _boom():
            yield "partial"
            raise RuntimeError("boom")

        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_stream.return_value = _boom()
            load_provider.return_value = mock_module
            with pytest.raises(cloud_llm_client.CloudLlmError):
                list(cloud_llm_client.chat_stream(
                    "anthropic", "claude-sonnet-4-6", "key", []))

    # ── chat_stream_with_tools() dispatch (Baustein 22, Phase 2 Streaming) ─

    def test_chat_stream_with_tools_unknown_provider_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream_with_tools(
                "not-a-real-provider", "some-model", "key", [], []))

    def test_chat_stream_with_tools_missing_model_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream_with_tools(
                "anthropic", "", "key", [], []))

    def test_chat_stream_with_tools_missing_api_key_raises_config_error(self):
        with pytest.raises(cloud_llm_client.CloudLlmConfigError):
            list(cloud_llm_client.chat_stream_with_tools(
                "anthropic", "claude-sonnet-4-6", "", [], []))

    def test_chat_stream_with_tools_yields_provider_events_and_passes_mcp_tools(self):
        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_stream_with_tools.return_value = iter([
                {"type": "text", "text": "hi"},
                {"type": "done", "content": "hi", "tool_calls": []},
            ])
            load_provider.return_value = mock_module
            mcp_tools = [{"name": "t", "description": "d", "inputSchema": {}}]

            events = list(cloud_llm_client.chat_stream_with_tools(
                "anthropic", "claude-sonnet-4-6", "key",
                [{"role": "user", "content": "hi"}], mcp_tools))

        assert events == [
            {"type": "text", "text": "hi"},
            {"type": "done", "content": "hi", "tool_calls": []},
        ]
        mock_module.chat_stream_with_tools.assert_called_once_with(
            "claude-sonnet-4-6", "key", [{"role": "user", "content": "hi"}], mcp_tools)

    def test_chat_stream_with_tools_exception_during_iteration_wrapped(self):
        def _boom():
            yield {"type": "text", "text": "partial"}
            raise RuntimeError("boom")

        with patch("cloud_llm_client._load_provider") as load_provider:
            mock_module = MagicMock()
            mock_module.chat_stream_with_tools.return_value = _boom()
            load_provider.return_value = mock_module
            with pytest.raises(cloud_llm_client.CloudLlmError):
                list(cloud_llm_client.chat_stream_with_tools(
                    "anthropic", "claude-sonnet-4-6", "key", [], []))


# ══════════════════════════════════════════════════════════════════════════════
#  cloud_llm_anthropic.py — provider
# ══════════════════════════════════════════════════════════════════════════════

class TestCloudLlmAnthropic:

    def test_split_system_extracts_system_message(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        system, converted = cloud_llm_anthropic._split_system(messages)
        assert system == "You are helpful."
        assert converted == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_split_system_joins_multiple_system_messages(self):
        messages = [
            {"role": "system", "content": "First."},
            {"role": "system", "content": "Second."},
            {"role": "user", "content": "hi"},
        ]
        system, converted = cloud_llm_anthropic._split_system(messages)
        assert system == "First.\n\nSecond."
        assert converted == [{"role": "user", "content": "hi"}]

    def test_split_system_no_system_message(self):
        messages = [{"role": "user", "content": "hi"}]
        system, converted = cloud_llm_anthropic._split_system(messages)
        assert system == ""
        assert converted == messages

    def test_chat_calls_sdk_with_split_messages_and_returns_text(self):
        fake_block = MagicMock(type="text", text="hello there")
        fake_response = MagicMock()
        fake_response.content = [fake_block]

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            reply = cloud_llm_anthropic.chat(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "system", "content": "Be nice."},
                 {"role": "user", "content": "hi"}])

        assert reply == "hello there"
        mock_anthropic_cls.assert_called_once_with(api_key="sk-test")
        mock_client.messages.create.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=cloud_llm_anthropic.MAX_TOKENS,
            system="Be nice.",
            messages=[{"role": "user", "content": "hi"}])

    def test_chat_ignores_non_text_blocks(self):
        # response.content can hold non-text blocks (tool_use etc.) —
        # chat() only ever does plain requests today (no tools= passed),
        # but must not choke if the SDK returns a mixed list anyway.
        text_block = MagicMock(type="text", text="answer")
        other_block = MagicMock(type="tool_use")
        fake_response = MagicMock()
        fake_response.content = [other_block, text_block]

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client
            reply = cloud_llm_anthropic.chat(
                "claude-sonnet-4-6", "sk-test", [{"role": "user", "content": "hi"}])

        assert reply == "answer"

    # ── to_anthropic_tools() (Baustein 18) ───────────────────────────────

    def test_to_anthropic_tools_uses_input_schema_not_parameters(self):
        mcp_tools = [{"name": "query_health", "description": "d",
                      "inputSchema": {"type": "object"}}]
        result = cloud_llm_anthropic.to_anthropic_tools(mcp_tools)
        assert result == [{
            "name": "query_health",
            "description": "d",
            "input_schema": {"type": "object"},
        }]

    def test_to_anthropic_tools_empty_list(self):
        assert cloud_llm_anthropic.to_anthropic_tools([]) == []

    # ── _history_to_anthropic() (Baustein 18) ────────────────────────────

    def test_history_user_message_passthrough(self):
        result = cloud_llm_anthropic._history_to_anthropic(
            [{"role": "user", "content": "hi"}])
        assert result == [{"role": "user", "content": "hi"}]

    def test_history_assistant_without_tool_calls_becomes_text_block(self):
        result = cloud_llm_anthropic._history_to_anthropic(
            [{"role": "assistant", "content": "hello", "tool_calls": []}])
        assert result == [{"role": "assistant",
                            "content": [{"type": "text", "text": "hello"}]}]

    def test_history_assistant_with_tool_call_becomes_tool_use_block(self):
        result = cloud_llm_anthropic._history_to_anthropic([{
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "call_1", "function": {
                "name": "query_health", "arguments": {"field": "steps"}}}],
        }])
        assert result == [{"role": "assistant", "content": [{
            "type": "tool_use", "id": "call_1", "name": "query_health",
            "input": {"field": "steps"},
        }]}]

    def test_history_single_tool_result_becomes_user_message(self):
        result = cloud_llm_anthropic._history_to_anthropic(
            [{"role": "tool", "content": "8000 steps", "tool_call_id": "call_1"}])
        assert result == [{"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "call_1",
            "content": "8000 steps",
        }]}]

    def test_history_multiple_consecutive_tool_results_merge_into_one_message(self):
        # Anthropic requires all tool_result blocks for one assistant
        # turn's tool_use calls to sit in a SINGLE user message, not one
        # user message per result — see _history_to_anthropic()'s own
        # docstring.
        result = cloud_llm_anthropic._history_to_anthropic([
            {"role": "tool", "content": "r1", "tool_call_id": "call_1"},
            {"role": "tool", "content": "r2", "tool_call_id": "call_2"},
        ])
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "r1"},
            {"type": "tool_result", "tool_use_id": "call_2", "content": "r2"},
        ]

    def test_history_full_turn_round_trip(self):
        messages = [
            {"role": "user", "content": "How many steps?"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "function": {
                    "name": "query_health", "arguments": {"field": "steps"}}}]},
            {"role": "tool", "content": "8000", "tool_call_id": "call_1"},
        ]
        result = cloud_llm_anthropic._history_to_anthropic(messages)
        assert [m["role"] for m in result] == ["user", "assistant", "user"]

    # ── chat_with_tools() (Baustein 18) ──────────────────────────────────

    def test_chat_with_tools_sends_translated_tools_and_history(self):
        fake_response = MagicMock()
        fake_response.content = []

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            cloud_llm_anthropic.chat_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                [{"name": "t", "description": "d", "inputSchema": {"a": 1}}])

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["tools"] == [
            {"name": "t", "description": "d", "input_schema": {"a": 1}}]
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]

    def test_chat_with_tools_parses_text_and_tool_use_blocks(self):
        text_block = MagicMock(type="text", text="Let me check.")
        # "name" is a reserved MagicMock constructor kwarg (labels the
        # mock's own repr, does not set a .name attribute) — must be
        # assigned after construction instead.
        tool_block = MagicMock(type="tool_use", id="call_9",
                                input={"field": "steps"})
        tool_block.name = "query_health"
        fake_response = MagicMock()
        fake_response.content = [text_block, tool_block]

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            result = cloud_llm_anthropic.chat_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}], [])

        assert result == {
            "content": "Let me check.",
            "tool_calls": [{"id": "call_9", "function": {
                "name": "query_health", "arguments": {"field": "steps"}}}],
        }

    def test_chat_with_tools_no_tool_use_blocks_gives_empty_tool_calls(self):
        text_block = MagicMock(type="text", text="Final answer.")
        fake_response = MagicMock()
        fake_response.content = [text_block]

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = fake_response
            mock_anthropic_cls.return_value = mock_client

            result = cloud_llm_anthropic.chat_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}], [])

        assert result == {"content": "Final answer.", "tool_calls": []}

    # ── chat_stream() (Baustein 20, Phase 1 Streaming) ────────────────────

    def test_chat_stream_yields_text_stream_chunks(self):
        mock_stream = MagicMock()
        mock_stream.text_stream = iter(["Hel", "lo"])
        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__.return_value = mock_stream
        mock_stream_cm.__exit__.return_value = False

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream_cm
            mock_anthropic_cls.return_value = mock_client

            chunks = list(cloud_llm_anthropic.chat_stream(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "system", "content": "Be nice."},
                 {"role": "user", "content": "hi"}]))

        assert chunks == ["Hel", "lo"]
        mock_client.messages.stream.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=cloud_llm_anthropic.MAX_TOKENS,
            system="Be nice.",
            messages=[{"role": "user", "content": "hi"}])

    def test_chat_stream_closes_via_context_manager(self):
        # client.messages.stream() is a context manager (MessageStreamManager) —
        # __exit__ must run once the generator is fully consumed, same
        # cleanup guarantee as a plain "with" block anywhere else.
        mock_stream = MagicMock()
        mock_stream.text_stream = iter(["hi"])
        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__.return_value = mock_stream
        mock_stream_cm.__exit__.return_value = False

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream_cm
            mock_anthropic_cls.return_value = mock_client

            list(cloud_llm_anthropic.chat_stream(
                "claude-sonnet-4-6", "sk-test", [{"role": "user", "content": "hi"}]))

        mock_stream_cm.__exit__.assert_called_once()

    # ── chat_stream_with_tools() (Baustein 22, Phase 2 Streaming) ──────────

    def test_chat_stream_with_tools_yields_text_and_tool_call(self):
        text_event = MagicMock(type="text", text="Let me check.")
        tool_block = MagicMock(type="tool_use", id="call_9", input={"field": "steps"})
        tool_block.name = "query_health"  # reserved MagicMock kwarg, see above
        stop_event = MagicMock(type="content_block_stop", content_block=tool_block)
        mock_stream = MagicMock()
        mock_stream.__iter__.return_value = iter([text_event, stop_event])
        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__.return_value = mock_stream
        mock_stream_cm.__exit__.return_value = False

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream_cm
            mock_anthropic_cls.return_value = mock_client

            events = list(cloud_llm_anthropic.chat_stream_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}], []))

        assert events == [
            {"type": "text", "text": "Let me check."},
            {"type": "done", "content": "Let me check.", "tool_calls": [
                {"id": "call_9", "function": {
                    "name": "query_health", "arguments": {"field": "steps"}}}]},
        ]

    def test_chat_stream_with_tools_sends_translated_tools(self):
        mock_stream = MagicMock()
        mock_stream.__iter__.return_value = iter([])
        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__.return_value = mock_stream
        mock_stream_cm.__exit__.return_value = False

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream_cm
            mock_anthropic_cls.return_value = mock_client

            list(cloud_llm_anthropic.chat_stream_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}],
                [{"name": "t", "description": "d", "inputSchema": {"a": 1}}]))

        _, kwargs = mock_client.messages.stream.call_args
        assert kwargs["tools"] == [
            {"name": "t", "description": "d", "input_schema": {"a": 1}}]

    def test_chat_stream_with_tools_no_tool_use_gives_empty_list(self):
        text_event = MagicMock(type="text", text="Final answer.")
        mock_stream = MagicMock()
        mock_stream.__iter__.return_value = iter([text_event])
        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__.return_value = mock_stream
        mock_stream_cm.__exit__.return_value = False

        with patch("cloud_llm_anthropic.anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.stream.return_value = mock_stream_cm
            mock_anthropic_cls.return_value = mock_client

            events = list(cloud_llm_anthropic.chat_stream_with_tools(
                "claude-sonnet-4-6", "sk-test",
                [{"role": "user", "content": "hi"}], []))

        assert events[-1] == {
            "type": "done", "content": "Final answer.", "tool_calls": []}


# ══════════════════════════════════════════════════════════════════════════════
#  cloud_llm_openai.py — provider
# ══════════════════════════════════════════════════════════════════════════════

class TestCloudLlmOpenai:

    def test_chat_passes_messages_through_unchanged_and_returns_text(self):
        # Unlike cloud_llm_anthropic.py, no system-prompt split needed —
        # OpenAI's Chat Completions API already takes role: "system" in
        # the same messages list (see module docstring).
        messages = [
            {"role": "system", "content": "Be nice."},
            {"role": "user", "content": "hi"},
        ]
        fake_message = MagicMock(content="hello there")
        fake_choice = MagicMock(message=fake_message)
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = fake_response
            mock_openai_cls.return_value = mock_client

            reply = cloud_llm_openai.chat("gpt-4.1", "sk-test", messages)

        assert reply == "hello there"
        mock_openai_cls.assert_called_once_with(api_key="sk-test")
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-4.1", messages=messages)

    def test_chat_returns_empty_string_for_none_content(self):
        # A refusal-only or tool-call-only response can leave content
        # as None — must not surface as the literal string "None".
        fake_message = MagicMock(content=None)
        fake_choice = MagicMock(message=fake_message)
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = fake_response
            mock_openai_cls.return_value = mock_client
            reply = cloud_llm_openai.chat(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}])

        assert reply == ""

    # ── chat_with_tools() (Baustein 18) ──────────────────────────────────

    def test_chat_with_tools_sends_openai_style_schema(self):
        fake_message = MagicMock(content="hi", tool_calls=None)
        fake_choice = MagicMock(message=fake_message)
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]
        mcp_tools = [{"name": "query_health", "description": "d",
                      "inputSchema": {"type": "object"}}]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = fake_response
            mock_openai_cls.return_value = mock_client

            cloud_llm_openai.chat_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}], mcp_tools)

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["tools"] == [{
            "type": "function",
            "function": {"name": "query_health", "description": "d",
                          "parameters": {"type": "object"}},
        }]

    def test_chat_with_tools_parses_tool_calls_and_json_arguments(self):
        # "name" is a reserved MagicMock constructor kwarg (labels the
        # mock's own repr, does not set a .name attribute) — assigned
        # after construction instead, same as the Anthropic tool_use
        # block test above.
        fake_function = MagicMock()
        fake_function.name = "query_health"
        fake_function.arguments = '{"field": "steps"}'
        fake_tool_call = MagicMock(id="call_1", function=fake_function)
        fake_message = MagicMock(content=None, tool_calls=[fake_tool_call])
        fake_choice = MagicMock(message=fake_message)
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = fake_response
            mock_openai_cls.return_value = mock_client

            result = cloud_llm_openai.chat_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}], [])

        assert result == {
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {
                "name": "query_health", "arguments": {"field": "steps"}}}],
        }

    def test_chat_with_tools_no_tool_calls_gives_empty_list(self):
        fake_message = MagicMock(content="Final answer.", tool_calls=None)
        fake_choice = MagicMock(message=fake_message)
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = fake_response
            mock_openai_cls.return_value = mock_client

            result = cloud_llm_openai.chat_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}], [])

        assert result == {"content": "Final answer.", "tool_calls": []}

    # ── chat_stream() (Baustein 20, Phase 1 Streaming) ────────────────────

    def test_chat_stream_yields_delta_content(self):
        chunk_role_only = MagicMock()
        chunk_role_only.choices = [MagicMock(delta=MagicMock(content=None))]
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hel"))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="lo"))]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(
                [chunk_role_only, chunk1, chunk2])
            mock_openai_cls.return_value = mock_client

            chunks = list(cloud_llm_openai.chat_stream(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}]))

        assert chunks == ["Hel", "lo"]
        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-4.1", messages=[{"role": "user", "content": "hi"}],
            stream=True)

    # ── chat_stream_with_tools() (Baustein 22, Phase 2 Streaming) ──────────

    def test_chat_stream_with_tools_yields_text_chunks(self):
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hel", tool_calls=None))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(content="lo", tool_calls=None))]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter([chunk1, chunk2])
            mock_openai_cls.return_value = mock_client

            events = list(cloud_llm_openai.chat_stream_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}], []))

        assert events == [
            {"type": "text", "text": "Hel"},
            {"type": "text", "text": "lo"},
            {"type": "done", "content": "Hello", "tool_calls": []},
        ]

    def test_chat_stream_with_tools_assembles_fragmented_tool_call(self):
        # OpenAI's own fragmentation shape: name arrives whole in the
        # first delta, arguments arrive split across several chunks —
        # must be concatenated (not parsed) until the final chunk.
        def _tc_delta(index, id_=None, name=None, arguments=None):
            # fn.name/.arguments set after construction, not via the
            # MagicMock(name=...) constructor kwarg — that kwarg is
            # reserved for the mock's own repr label, see the existing
            # "name" gotcha comments elsewhere in this file.
            fn = MagicMock()
            fn.name = name
            fn.arguments = arguments
            return MagicMock(index=index, id=id_, function=fn)

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock(delta=MagicMock(
            content=None, tool_calls=[_tc_delta(0, id_="call_1", name="query_health", arguments="")]))]
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock(delta=MagicMock(
            content=None, tool_calls=[_tc_delta(0, arguments='{"field"')]))]
        chunk3 = MagicMock()
        chunk3.choices = [MagicMock(delta=MagicMock(
            content=None, tool_calls=[_tc_delta(0, arguments=': "steps"}')]))]

        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter(
                [chunk1, chunk2, chunk3])
            mock_openai_cls.return_value = mock_client

            events = list(cloud_llm_openai.chat_stream_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}], []))

        assert events == [{
            "type": "done", "content": "", "tool_calls": [
                {"id": "call_1", "function": {
                    "name": "query_health", "arguments": {"field": "steps"}}}],
        }]

    def test_chat_stream_with_tools_sends_openai_style_schema(self):
        with patch("cloud_llm_openai.openai.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = iter([])
            mock_openai_cls.return_value = mock_client

            list(cloud_llm_openai.chat_stream_with_tools(
                "gpt-4.1", "sk-test", [{"role": "user", "content": "hi"}],
                [{"name": "query_health", "description": "d",
                  "inputSchema": {"type": "object"}}]))

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["tools"] == [{
            "type": "function",
            "function": {"name": "query_health", "description": "d",
                          "parameters": {"type": "object"}},
        }]
        assert kwargs["stream"] is True
