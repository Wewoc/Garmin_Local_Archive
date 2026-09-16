# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_cloud_credential_store.py
Garmin Local Archive — Cloud Credential Store Test Suite (Baustein 23)

Run with:
    pytest tests/test_cloud_credential_store.py -v

Scope: clients/cloud_credential_store.py — plain Python, no Qt.
`keyring` is imported lazily inside each function under test (same
convention garmin/garmin_security.py already uses for the same
library), so it is mocked the same way tests/test_local.py's own
garmin_security tests already do: patch.dict("sys.modules", {"keyring":
mock_kr}) BEFORE calling the function, not patch.object() on an
already-imported module attribute.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import cloud_credential_store as ccs


class TestGetApiKey:

    def test_returns_stored_value(self):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "sk-test-anthropic"
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            result = ccs.get_api_key("anthropic")
        assert result == "sk-test-anthropic"
        mock_kr.get_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_anthropic_api_key")

    def test_returns_none_when_absent(self):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            assert ccs.get_api_key("anthropic") is None

    def test_returns_none_on_empty_string(self):
        # An empty string is treated the same as "nothing stored" —
        # matches garmin_security.get_enc_key_status()'s own
        # "or None" normalization.
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = ""
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            assert ccs.get_api_key("anthropic") is None

    def test_returns_none_on_wcm_failure(self):
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = Exception("WCM read error")
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            assert ccs.get_api_key("anthropic") is None

    def test_different_providers_use_different_usernames(self):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "x"
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.get_api_key("anthropic")
            ccs.get_api_key("openai")
        usernames = [c.args[1] for c in mock_kr.get_password.call_args_list]
        assert usernames == [
            "cloud_llm_anthropic_api_key", "cloud_llm_openai_api_key"]


class TestStoreApiKey:

    def test_stores_value_returns_true(self):
        mock_kr = MagicMock()
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ok = ccs.store_api_key("anthropic", "sk-test-123")
        assert ok is True
        mock_kr.set_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_anthropic_api_key", "sk-test-123")

    def test_wcm_failure_returns_false(self):
        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = Exception("WCM write error")
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            assert ccs.store_api_key("anthropic", "sk-test-123") is False


class TestClearApiKey:

    def test_deletes_returns_true(self):
        mock_kr = MagicMock()
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ok = ccs.clear_api_key("anthropic")
        assert ok is True
        mock_kr.delete_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_anthropic_api_key")

    def test_wcm_failure_returns_false(self):
        mock_kr = MagicMock()
        mock_kr.delete_password.side_effect = Exception("WCM delete error")
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            assert ccs.clear_api_key("anthropic") is False


class TestProviderNormalization:
    # garmin_collector-3_experiment, post-Baustein-23 review: a Save
    # from app/panel_mcp.py or clients/mcp_server_gui.py only ever
    # .strip()s the provider string, never .lower()s it, and both
    # insert an unrecognized legacy provider value from
    # MCP_LLM_CONFIG_FILE (pre-dropdown free-text data) into their
    # dropdown verbatim. _username() now normalizes at this module's
    # own boundary instead, so every caller — normalized or not —
    # lands on the same WCM entry.

    def test_get_api_key_normalizes_mixed_case(self):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "sk-test"
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.get_api_key("  Anthropic ")
        mock_kr.get_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_anthropic_api_key")

    def test_store_api_key_normalizes_mixed_case(self):
        mock_kr = MagicMock()
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.store_api_key("OpenAI", "sk-test")
        mock_kr.set_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_openai_api_key", "sk-test")

    def test_clear_api_key_normalizes_mixed_case(self):
        mock_kr = MagicMock()
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.clear_api_key("Anthropic")
        mock_kr.delete_password.assert_called_once_with(
            "GarminLocalArchive", "cloud_llm_anthropic_api_key")

    def test_unnormalized_write_reaches_normalized_read(self):
        # The exact regression scenario: a legacy "Anthropic" value
        # (mixed case, from before the provider dropdown existed)
        # saves the key — a lookup with the normalized "anthropic"
        # (what app/panel_chat.py's own normalized read path always
        # uses) must still find it.
        store = {}

        def _set(service, username, value):
            store[(service, username)] = value

        def _get(service, username):
            return store.get((service, username))

        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = _set
        mock_kr.get_password.side_effect = _get
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.store_api_key("Anthropic", "sk-legacy-case")
            result = ccs.get_api_key("anthropic")
        assert result == "sk-legacy-case"


class TestRoundTrip:

    def test_store_then_get_uses_same_username(self):
        # Not a real round trip (keyring itself is mocked, stateless
        # across the two calls) — verifies both functions address the
        # exact same WCM entry for a given provider, which is what
        # makes a real round trip work.
        store = {}

        def _set(service, username, value):
            store[(service, username)] = value

        def _get(service, username):
            return store.get((service, username))

        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = _set
        mock_kr.get_password.side_effect = _get
        with patch.dict("sys.modules", {"keyring": mock_kr}):
            ccs.store_api_key("openai", "sk-openai-test")
            result = ccs.get_api_key("openai")
        assert result == "sk-openai-test"
