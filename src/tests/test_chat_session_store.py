# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_chat_session_store.py
Garmin Local Archive — Chat Session Store Test Suite (Baustein 21)

Run with:
    pytest tests/test_chat_session_store.py -v

Scope: clients/chat_session_store.py — plain Python, no Qt, real
filesystem via tmp_path (matches test_cloud_llm.py's own "separate
lightweight file" reasoning for leaf-node modules with no project-
internal imports besides frozen_paths — this module has none at all).
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import chat_session_store as css


# ══════════════════════════════════════════════════════════════════════════════
#  compute_source_hash()
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeSourceHash:

    def test_missing_file_returns_none(self, tmp_path):
        assert css.compute_source_hash(tmp_path / "does_not_exist.json") is None

    def test_deterministic_for_same_content(self, tmp_path):
        f = tmp_path / "health_garmin.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        h1 = css.compute_source_hash(f)
        h2 = css.compute_source_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_content_different_hash(self, tmp_path):
        f = tmp_path / "health_garmin.json"
        f.write_text('{"a": 1}', encoding="utf-8")
        h1 = css.compute_source_hash(f)
        f.write_text('{"a": 2}', encoding="utf-8")
        h2 = css.compute_source_hash(f)
        assert h1 != h2


# ══════════════════════════════════════════════════════════════════════════════
#  save_session() / load_session()
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveAndLoadSession:

    def _session(self, datasource="json"):
        return {
            "created_at": "2026-09-15T14:32:05",
            "backend": "ollama",
            "datasource": datasource,
            "model": "qwen3:14b",
            "provider": "",
            "messages": [{"role": "user", "content": "hi"}],
        }

    def test_first_save_creates_chats_dir(self, tmp_path):
        path = css.save_session(tmp_path, None, self._session())
        assert (tmp_path / "chats").is_dir()
        assert path.parent == tmp_path / "chats"

    def test_first_save_filename_encodes_backend_and_datasource(self, tmp_path):
        path = css.save_session(tmp_path, None, self._session(datasource="mcp"))
        assert "_ollama_mcp" in path.name
        assert path.name.startswith("chat_")
        assert path.suffix == ".json"

    def test_second_save_with_returned_path_overwrites_same_file(self, tmp_path):
        path1 = css.save_session(tmp_path, None, self._session())
        session2 = self._session()
        session2["messages"].append({"role": "assistant", "content": "hello"})
        path2 = css.save_session(tmp_path, path1, session2)
        assert path1 == path2
        assert len(list((tmp_path / "chats").glob("chat_*.json"))) == 1

    def test_load_session_round_trips_messages(self, tmp_path):
        session = self._session()
        path = css.save_session(tmp_path, None, session)
        loaded = css.load_session(path)
        assert loaded["messages"] == session["messages"]
        assert loaded["backend"] == "ollama"

    def test_save_does_not_mutate_caller_dict(self, tmp_path):
        session = self._session()
        original = dict(session)
        css.save_session(tmp_path, None, session)
        assert "source_hash" not in session  # caller's dict untouched
        assert session == original

    def test_load_missing_file_raises_chat_session_error(self, tmp_path):
        with pytest.raises(css.ChatSessionError):
            css.load_session(tmp_path / "nope.json")

    def test_load_corrupt_json_raises_chat_session_error(self, tmp_path):
        f = tmp_path / "corrupt.json"
        f.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(css.ChatSessionError):
            css.load_session(f)

    def test_save_json_datasource_computes_source_hash(self, tmp_path):
        (tmp_path / "dashboards").mkdir()
        (tmp_path / "dashboards" / "health_garmin.json").write_text(
            '{"x": 1}', encoding="utf-8")
        path = css.save_session(tmp_path, None, self._session(datasource="json"))
        loaded = css.load_session(path)
        assert loaded["source_hash"] == css.compute_source_hash(
            tmp_path / "dashboards" / "health_garmin.json")

    def test_save_mcp_datasource_source_hash_is_none(self, tmp_path):
        (tmp_path / "dashboards").mkdir()
        (tmp_path / "dashboards" / "health_garmin.json").write_text(
            '{"x": 1}', encoding="utf-8")
        path = css.save_session(tmp_path, None, self._session(datasource="mcp"))
        loaded = css.load_session(path)
        assert loaded["source_hash"] is None

    def test_save_json_datasource_no_source_file_hash_is_none(self, tmp_path):
        path = css.save_session(tmp_path, None, self._session(datasource="json"))
        loaded = css.load_session(path)
        assert loaded["source_hash"] is None

    def test_save_is_atomic_no_tmp_file_left_behind(self, tmp_path):
        path = css.save_session(tmp_path, None, self._session())
        assert not path.with_suffix(path.suffix + ".tmp").exists()


# ══════════════════════════════════════════════════════════════════════════════
#  delete_session()
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteSession:

    def test_deletes_existing_file(self, tmp_path):
        path = css.save_session(tmp_path, None, {
            "created_at": "x", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "", "messages": []})
        assert path.exists()
        css.delete_session(path)
        assert not path.exists()

    def test_missing_file_no_error(self, tmp_path):
        css.delete_session(tmp_path / "already_gone.json")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
#  list_sessions()
# ══════════════════════════════════════════════════════════════════════════════

class TestListSessions:

    def test_no_chats_dir_returns_empty_list(self, tmp_path):
        assert css.list_sessions(tmp_path) == []

    def test_empty_chats_dir_returns_empty_list(self, tmp_path):
        (tmp_path / "chats").mkdir()
        assert css.list_sessions(tmp_path) == []

    def test_lists_saved_sessions_with_metadata(self, tmp_path):
        css.save_session(tmp_path, None, {
            "created_at": "2026-09-15T14:00:00", "backend": "ollama",
            "datasource": "json", "model": "qwen3:14b", "provider": "",
            "messages": [{"role": "user", "content": "how many steps?"}]})
        sessions = css.list_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0]["backend"] == "ollama"
        assert sessions[0]["datasource"] == "json"
        assert sessions[0]["model"] == "qwen3:14b"
        assert sessions[0]["preview"] == "how many steps?"

    def test_newest_first_by_filename_timestamp(self, tmp_path, monkeypatch):
        import datetime

        class _FrozenDatetime(datetime.datetime):
            _now = datetime.datetime(2026, 9, 15, 14, 0, 0)

            @classmethod
            def now(cls, tz=None):
                return cls._now

        monkeypatch.setattr(datetime, "datetime", _FrozenDatetime)
        _FrozenDatetime._now = datetime.datetime(2026, 9, 15, 14, 0, 0)
        path1 = css.save_session(tmp_path, None, {
            "created_at": "a", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "", "messages": []})
        _FrozenDatetime._now = datetime.datetime(2026, 9, 15, 15, 0, 0)
        path2 = css.save_session(tmp_path, None, {
            "created_at": "b", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "", "messages": []})

        sessions = css.list_sessions(tmp_path)
        assert [s["path"] for s in sessions] == [path2, path1]

    def test_preview_empty_when_no_user_message(self, tmp_path):
        css.save_session(tmp_path, None, {
            "created_at": "x", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "",
            "messages": [{"role": "system", "content": "sys"}]})
        sessions = css.list_sessions(tmp_path)
        assert sessions[0]["preview"] == ""

    def test_preview_truncated_to_80_chars(self, tmp_path):
        long_text = "x" * 200
        css.save_session(tmp_path, None, {
            "created_at": "x", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "",
            "messages": [{"role": "user", "content": long_text}]})
        sessions = css.list_sessions(tmp_path)
        assert len(sessions[0]["preview"]) == 80

    def test_corrupt_session_file_skipped_not_raised(self, tmp_path):
        chats_dir = tmp_path / "chats"
        chats_dir.mkdir()
        (chats_dir / "chat_2026-09-15_140000_ollama_json.json").write_text(
            "{not valid json", encoding="utf-8")
        css.save_session(tmp_path, None, {
            "created_at": "x", "backend": "ollama", "datasource": "json",
            "model": "m", "provider": "", "messages": []})
        sessions = css.list_sessions(tmp_path)
        assert len(sessions) == 1  # only the valid one


# ══════════════════════════════════════════════════════════════════════════════
#  is_resumable()
# ══════════════════════════════════════════════════════════════════════════════

class TestIsResumable:

    def test_mcp_always_resumable(self, tmp_path):
        assert css.is_resumable({"datasource": "mcp"}, tmp_path) is True

    def test_mcp_resumable_even_without_source_hash(self, tmp_path):
        assert css.is_resumable(
            {"datasource": "mcp", "source_hash": None}, tmp_path) is True

    def test_json_no_stored_hash_not_resumable(self, tmp_path):
        assert css.is_resumable(
            {"datasource": "json", "source_hash": None}, tmp_path) is False

    def test_json_matching_hash_is_resumable(self, tmp_path):
        (tmp_path / "dashboards").mkdir()
        f = tmp_path / "dashboards" / "health_garmin.json"
        f.write_text('{"x": 1}', encoding="utf-8")
        stored_hash = css.compute_source_hash(f)
        assert css.is_resumable(
            {"datasource": "json", "source_hash": stored_hash}, tmp_path) is True

    def test_json_changed_source_not_resumable(self, tmp_path):
        (tmp_path / "dashboards").mkdir()
        f = tmp_path / "dashboards" / "health_garmin.json"
        f.write_text('{"x": 1}', encoding="utf-8")
        stored_hash = css.compute_source_hash(f)
        f.write_text('{"x": 2}', encoding="utf-8")  # changed since save
        assert css.is_resumable(
            {"datasource": "json", "source_hash": stored_hash}, tmp_path) is False

    def test_json_source_file_deleted_not_resumable(self, tmp_path):
        (tmp_path / "dashboards").mkdir()
        f = tmp_path / "dashboards" / "health_garmin.json"
        f.write_text('{"x": 1}', encoding="utf-8")
        stored_hash = css.compute_source_hash(f)
        f.unlink()
        assert css.is_resumable(
            {"datasource": "json", "source_hash": stored_hash}, tmp_path) is False
