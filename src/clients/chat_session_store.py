#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/chat_session_store.py
Garmin Local Archive — Chat Session Persistence (Baustein 21, garmin_collector-3_experiment)

Leaf-Node. Reads/writes/deletes saved chat sessions under
<base_dir>/chats/ for app/panel_chat.py's Chat History button
(app/dialog_chat_history.py shows the list; this module owns every
file access). No Qt, no project-internal imports besides stdlib — same
leaf-node contract as ollama_client.py/mcp_client.py.

Session file = one JSON file per conversation. "One conversation" is
bounded by app/panel_chat.py's own New Chat boundary (KONZEPT_v1.7.2
§4 context reset, garmin_collector-3_experiment session decision,
2026-09-15): every New Chat — explicit click, or an implicit one via a
model/backend/datasource switch, all of which already route through
_chat_on_new_chat() — starts a fresh file; every completed turn before
the next New Chat overwrites the SAME file (auto-save, no explicit
"Save" action).

Schema: {"created_at", "backend", "datasource", "model", "provider",
"source_hash", "messages"}. "messages" is app/panel_chat.py's
self._history verbatim (same shape mcp_tool_chat.py/cloud_tool_chat.py
already build up) — this module never inspects its contents beyond
scanning for the first user turn (list_sessions()'s preview).

Filename: chat_<YYYY-MM-DD_HHMMSS>_<backend>_<datasource>.json —
backend/datasource encoded for at-a-glance listing without opening
every file; the timestamp both guarantees uniqueness and gives a
correct newest-first sort as a plain string, no need to read
"created_at" back out just to order the list.

source_hash: SHA-256 over the raw bytes of dashboards/health_garmin.json
at save time, recomputed on every save_session() call (not just the
first) — None for datasource "mcp" (always resumable, see
is_resumable() below; the underlying data is live at query time, never
bound to a snapshot) or if health_garmin.json did not exist at save
time. A content hash, not mtime, per KONZEPT_v1.7.2's own reasoning: an
mtime can stay unchanged despite the content changing (e.g. a manual
edit that preserves the original timestamp), which a content hash
cannot silently miss.
"""

import hashlib
import json
from pathlib import Path


class ChatSessionError(Exception):
    """Base class for all chat_session_store errors — raised for a
    session file that cannot be read (missing, corrupt JSON, wrong
    shape), matching this project's typed-exception convention (see
    ollama_client.py's OllamaError family) rather than letting a raw
    OSError/JSONDecodeError propagate to the caller."""


def _chats_dir(base_dir) -> Path:
    return Path(base_dir) / "chats"


def compute_source_hash(json_path) -> str | None:
    """SHA-256 over the raw bytes of json_path — None if the file
    does not exist (nothing to hash yet; not an error, mirrors
    app/panel_chat.py::_chat_refresh_age_display()'s own "not found"
    handling for the same file)."""
    path = Path(json_path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_session(base_dir, path, session_data: dict) -> Path:
    """Writes session_data as the session file at `path` (creating
    <base_dir>/chats/ if needed). path is None on the FIRST save of a
    new conversation — a fresh filename is generated here from
    session_data's own backend/datasource fields and the CURRENT
    time, so the timestamp reflects when the file actually first
    appears on disk. Every later save of the same conversation must
    pass the Path this function returned the first time, so it
    overwrites in place rather than creating a new file per turn.
    Returns the Path actually written to — the caller (app/panel_chat.py)
    keeps it as self._chat_session_path for the next save.

    source_hash is computed HERE, not by the caller (single source of
    truth for the hashing rule, see this module's own docstring) —
    fresh on every call, not only the first, in case
    dashboards/health_garmin.json changes while a datasource "json"
    session is still ongoing. session_data is copied before mutating
    it — the caller's own dict (app/panel_chat.py's in-memory session
    state) is never touched by this function.

    Write is atomic (write to a .tmp file, then Path.replace()) — an
    interrupted write (crash/power loss mid-save) must never leave a
    half-written, unparseable session file behind; the previous
    complete version stays intact until the new one is fully written."""
    chats_dir = _chats_dir(base_dir)
    chats_dir.mkdir(parents=True, exist_ok=True)

    if path is None:
        import datetime
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backend = session_data.get("backend", "unknown")
        datasource = session_data.get("datasource", "unknown")
        path = chats_dir / f"chat_{stamp}_{backend}_{datasource}.json"
    path = Path(path)

    data = dict(session_data)
    if data.get("datasource") == "json":
        data["source_hash"] = compute_source_hash(
            Path(base_dir) / "dashboards" / "health_garmin.json")
    else:
        data["source_hash"] = None

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_session(path) -> dict:
    """Reads and returns one session file's full content (including
    "messages") — raises ChatSessionError on any read/parse failure
    instead of letting a bare OSError/JSONDecodeError propagate."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ChatSessionError(f"Could not read session {path}: {e}") from e


def delete_session(path) -> None:
    """Deletes one session file. Silently succeeds if it is already
    gone — a dialog entry that races a second delete (or a file
    removed outside the app) must not surface as an error here."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def list_sessions(base_dir) -> list[dict]:
    """Lists every saved session under <base_dir>/chats/, newest
    first (the filename timestamp sorts correctly as a plain string —
    see this module's own docstring). Each entry: {"path", "created_at",
    "backend", "datasource", "model", "provider", "preview"} — a
    lightweight summary for app/dialog_chat_history.py's list view,
    deliberately NOT including "messages" (the dialog never needs the
    full transcript, only load_session() does, once a specific entry
    is picked). preview is the first user turn's content, truncated to
    80 chars — "" if none exists (should not normally happen, since a
    session is only ever saved after a completed turn, i.e. after at
    least one user message).

    A corrupt/unreadable file is skipped, not raised — one bad file
    must not break the whole listing (same "isolate the failure"
    principle as e.g. garmin_collector.py's run_capability_scan()
    exception isolation, applied here to a much smaller scope)."""
    chats_dir = _chats_dir(base_dir)
    if not chats_dir.exists():
        return []

    entries = []
    for path in sorted(chats_dir.glob("chat_*.json"), reverse=True):
        try:
            data = load_session(path)
        except ChatSessionError:
            continue
        preview = ""
        for m in data.get("messages", []):
            if m.get("role") == "user":
                preview = str(m.get("content", ""))[:80]
                break
        entries.append({
            "path": path,
            "created_at": data.get("created_at", ""),
            "backend": data.get("backend", ""),
            "datasource": data.get("datasource", ""),
            "model": data.get("model", ""),
            "provider": data.get("provider", ""),
            "preview": preview,
        })
    return entries


def is_resumable(session_data: dict, base_dir) -> bool:
    """True if this session can still accept new messages, False if
    it can only be viewed read-only.

    datasource "mcp": always True — the underlying data is live at
    query time, never bound to a snapshot (KONZEPT_v1.7.2).

    datasource "json": True only if dashboards/health_garmin.json is
    still byte-identical to what it was at save time (source_hash
    comparison). A session with no stored source_hash (should not
    happen for anything saved by this module going forward, but
    defensive against a file from an earlier build) is treated as NOT
    resumable rather than an unconditional pass — the whole point of
    this check is to never let a stale-data conversation silently
    continue as if nothing changed."""
    if session_data.get("datasource") == "mcp":
        return True
    stored_hash = session_data.get("source_hash")
    if not stored_hash:
        return False
    current_hash = compute_source_hash(
        Path(base_dir) / "dashboards" / "health_garmin.json")
    return stored_hash == current_hash
