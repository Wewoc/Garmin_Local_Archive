#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/panel_chat.py
Garmin Local Archive — In-App Ollama Chat Panel

PanelChat — PyQt6 QWidget, Composition (no Mixin, D-1). Tab 3 "Chat" in
garmin_app_base.py's QTabWidget.

Full concept: KONZEPT_ollama_chat_panel.md (v1.6.6).

Layout injected by garmin_app_base._build_ui():
  - self._panel_chat added as Tab 3 "Chat"
  - garmin_app_base._on_tab_changed(index=3) calls self._chat_on_tab_open()

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _chat_* prefix
  - Workers never touch widgets — use self._app._dispatch() (D-5)
  - Message history kept in RAM only (self._history) — no separate state
    module for this scope (KONZEPT §3)
  - Plain chat (no MCP tools) streams token-by-token since Baustein 20
    (Phase 1 Streaming, garmin_collector-3_experiment) — see that
    Baustein's docstring paragraph below. MCP-tool-calling turns
    (datasource "mcp", either backend) stay non-streaming — see
    ollama_client.chat_with_tools()/cloud_llm_*.chat_with_tools()
  - No active chat prep (model list, system prompt load) before the user
    clicks "Start" — only age display + a lightweight reachability ping run
    automatically on tab-open (KONZEPT §5)
  - Model switch mid-chat resets history (KONZEPT §4) — deliberate, not a
    bug: different models have different context limits/styles

garmin_collector-3_experiment addendum (2026-09-14, see that repo's
PROTOKOLL_experiment.md): Backend dropdown (ollama/cloud) + Datenquelle
dropdown (json/mcp), per NOTES_v1.7.2_chat_panel_konzept.md — replaces
an earlier, too-minimal "Use MCP tools" checkbox (session feedback:
"das war im Konzept anders beschrieben"). "cloud" is a read-only status
display for now (no cloud LLM client exists yet — see
PROTOKOLL_experiment.md's open-items list); Send shows a clear stub
message rather than a silent no-op or a crash. Both dropdowns are
enabled before Start (unlike model_combo/input/send_btn, which stay
gated behind Start — Start's own behavior depends on the selected
backend, so the choice has to be available before that click), but
locked together with start_btn the moment Start succeeds and stay
locked for the rest of the running session, re-opening only in
_chat_on_stop() or a failed Start (Baustein 12, session feedback:
switching either mid-chat used to only reset history without actually
locking anything, which let a live mcp-backed conversation be silently
mixed with a json one — see NOTES_v1.7.2_chat_panel_konzept.md's "fix
für die gesamte Dauer einer Session, festgelegt beim Start" decision).
The Ollama model dropdown is deliberately exempt from this lock — a
mid-chat model switch stays allowed, same as before (§4).

Start/Stop button pair (Baustein 8b, same session): Start recognizes an
already-running MCP server (from either panel) and only launches a new
one, headless, if datasource is "mcp" and none is reachable — see
clients/mcp_process.py. Stop is pragmatic, not ownership-based (see
that module's own docstring): it ends this panel's local chat session
and, if datasource is "mcp", also kills the MCP server unconditionally,
regardless of who started it — app/panel_mcp.py's own new Stop button
does the same, using the same shared module.

Layout order (Baustein 9, same session — session feedback: "erst
backend und quelle auswählen und dann die start stop buttons"):
Backend/Datenquelle now sit above Start/Stop, not below — Start's own
behavior depends on the selected backend/datasource, so the choice
belongs above the button that consumes it.

Split-view (Baustein 9): with datasource "mcp", a second pane appears
right of the chat view, tailing the SAME operational log file
clients/mcp_server.py already writes on every headless start
(garmin_data/log/mcp/mcp_<timestamp>.log, see that module's
_start_operational_log()) — no new logging mechanism, per
NOTES_v1.7.2_chat_panel_konzept.md's original intent (the correction
noted in PROTOKOLL_experiment.md's Baustein 1 entry still holds: the
file already existed before this session, nothing in the Qt app
previously read it — this pane is the first thing that does).
Polled on a timer (_chat_tail_mcp_log()), tied to the datasource
selection alone, independent of Start/Stop state — an empty pane
before a server exists is self-explanatory, no separate "is a server
running" gate needed. Session logging (also part of the concept)
remains follow-up work, not yet built.

Baustein 10 (same session, further UI feedback after testing the
Baustein 9 build): Start/Stop moved onto the same row as Backend/
Datenquelle (frees a row of height for the chat area); a hint label
(_mcp_model_hint) recommends qwen3/qwen2.5-coder for datasource "mcp",
sourced from mcp_test/MCP_TESTLAUF_BERICHT_FINAL.md's model findings —
advisory only, the model dropdown itself is unfiltered; and the model
dropdown itself is now sorted via _sort_models_qwen_first() (qwen
family alphabetically first, everything else alphabetically after).

Cloud-LLM-Connector (Baustein 14, same session): backend "cloud" now
does a real chat call, not just a read-only stub — routed through
clients/cloud_llm_client.py, the single dispatcher this panel imports
(_load_cloud_llm_client()). The dispatcher never lets this file know
which provider is actually configured — see that module's own
docstring for the "why" of the cloud_llm_<provider>.py split.
_chat_on_cloud_config_loaded() stores provider/model/api_key as
instance state (self._cloud_provider/_cloud_model/_cloud_api_key),
read fresh on every Start — _chat_on_send()'s cloud branch consumes
them, reusing the same _chat_on_reply()/_chat_on_error() handlers the
ollama path already has (the whole point of normalizing through one
dispatcher: no new reply-handling code needed here).

Cloud + MCP-Tool-Calling (Baustein 18, same session): datasource "mcp"
together with backend "cloud" now runs a real agentic turn loop too —
clients/cloud_tool_chat.py, the cloud counterpart to
clients/mcp_tool_chat.py's converse() (same shape, see that module's
own docstring for why a separate file rather than a generalized
converse()). _load_cloud_tool_chat() loads it lazily, same pattern as
_load_mcp_tool_chat(). Its result feeds into the same
_chat_on_mcp_reply()/_chat_on_mcp_unreachable() handlers the ollama+mcp
path already has — cloud_tool_chat.converse() returns the identical
{"content", "messages", "hit_max_turns"} shape, so nothing there needed
to change either.

Phase 1 Streaming (Baustein 20, same session): the two plain-chat
branches of _chat_on_send() (backend "ollama" or "cloud", datasource
"json" — no MCP tools involved) now call the matching client's
chat_stream() instead of chat(), and render the reply incrementally as
it arrives via _chat_start_stream_line()/_chat_append_stream_chunk()
instead of _chat_append_line(). MCP-tool-calling turns (datasource
"mcp") deliberately stay non-streaming — a tool call must be fully
assembled (name + arguments) before it can be executed, so only the
plain-text portion of a turn could ever stream; a separate, harder
problem, deliberately deferred (see PROTOKOLL_experiment.md, Baustein
20's own entry for the reasoning). _chat_view.append() always starts a
new paragraph/block — unsuitable for inline incremental text — so
_chat_start_stream_line() opens the bubble (speaker label, own block)
and _chat_append_stream_chunk() then inserts each fragment at the
document's end via QTextCursor instead, continuing that same block
(same moveCursor(End) idiom _chat_tail_mcp_log() already uses on
self._log_view). Two new terminal handlers mirror _chat_on_reply()/
_chat_on_error(): _chat_on_stream_done() only does the bookkeeping
(history/status/button) since the text is already on screen by the
time it runs; _chat_on_stream_error() additionally marks whatever
partial text is already visible as interrupted (left on screen as-is,
not erased) and — same as _chat_on_error() — never writes the
incomplete reply into self._history, and pops the user turn that
started the request so a retry does not duplicate it.

Chat-Session-Logging/Resume (Baustein 21, same session — last of the
three Bausteine agreed this session: Panel-Name -> Streaming -> this):
every completed turn (_chat_on_reply()/_chat_on_stream_done()/
_chat_on_mcp_reply()) auto-saves the running conversation via
_chat_save_session(), through clients/chat_session_store.py — no
explicit "Save" action. One file per conversation, self._chat_session_
path tracks which file (None until the first successful turn, then
fixed for the rest of that conversation); a NEW conversation always
gets a NEW file — _chat_on_new_chat() (explicit click, or the implicit
ones from a model/backend/datasource switch that already route through
it) resets self._chat_session_path back to None, and so does
_chat_on_stop() (a later Start without an intervening New Chat still
begins a fresh conversation via _chat_load_system_prompt()'s own
history reset, so the old file must not be silently overwritten by an
unrelated one).

A "Chat History" button next to Start/Stop opens app/dialog_chat_
history.py's ChatHistoryDialog (list of saved sessions, Load/Delete) —
not a dropdown as originally sketched in the concept, session decision
(the dialog can offer Delete cleanly, a dropdown could not). Loading a
session (_chat_on_load_session()) sets Backend/Datenquelle to the
saved values (signals blocked so this does not itself trigger
_chat_on_new_chat()'s reset), locks both combos immediately — even
before Start — via the same visibility toggles _chat_on_backend_
changed()/_chat_on_datasource_changed() already apply, now factored
out into _chat_apply_backend_visibility()/_chat_apply_datasource_
visibility() so both call sites share one implementation. The loaded
transcript is rendered read-only immediately (_chat_render_history(),
no network needed just to view it); continuing it live still requires
a Start click, same reachability checks as any other Start —
self._chat_resume_pending tells _chat_load_system_prompt() to skip its
normal history reset exactly once for this case.

Resume eligibility differs by datasource (KONZEPT_v1.7.2, "Fortsetz-
barkeit unterscheidet sich je nach Datenquelle"): "mcp" sessions are
always resumable (the underlying data is live at query time, never
bound to a snapshot); "json" sessions only if dashboards/
health_garmin.json is still byte-identical to what it was at save time
— clients/chat_session_store.py's is_resumable(), SHA-256 over the raw
file, not mtime (an mtime can stay the same despite the content
changing). A non-resumable session is never hidden from the dialog —
only Start stays disabled once loaded, with a system-line explanation;
_new_chat_btn is enabled regardless (a loaded, non-resumable session
would otherwise have no way back to a live chat) — self._chat_loaded_
not_started distinguishes "combos locked because a session was merely
loaded, not yet Started" from "combos locked because a session is
actually running", so _chat_on_new_chat() knows whether to re-open
them (only decided together with the user; two behaviors — dropdown vs
this dialog, load-then-Start-click vs auto-start, one file per New Chat
— were confirmed via AskUserQuestion this session, see
PROTOKOLL_experiment.md).

Cloud-origin marking (KONZEPT_v1.7.2 left this open — "noch nicht im
Detail festgelegt") is a single system-line note on load
("Loaded session — cloud (<provider>/<model>), saved <timestamp>"),
not a per-message label — confirmed this session: backend has been
fixed for the whole session since Baustein 12, so every answer in one
session already shares the same origin, making a per-bubble marker
redundant. A loaded cloud session's actual provider/model/key still
come from whatever clients/cloud_llm_client.py's config file holds at
Start time (_chat_on_cloud_config_loaded(), unchanged) — a session
saved under a provider that has since been reconfigured away continues
under the CURRENT provider, a known, narrow edge case, not solved here
(replaying old history against a differently-shaped provider is
already possible today for a live session restarted after a
reconfiguration; this does not introduce a new failure mode, only
makes an existing one reachable one step earlier).

Streaming Phase 2 (Baustein 22, same session — Cloud+MCP only): the
is_cloud and is_mcp branch of _chat_on_send() now streams too, via
clients/cloud_tool_chat.py's new converse_stream(). Ollama+MCP
(clients/mcp_tool_chat.py's converse()) deliberately has NO streaming
counterpart — Ollama's own streaming+tool-calling combination is
currently unreliable upstream (see clients/ollama_client.py's own
module docstring for the sourced reasoning) — that branch is
unchanged from Baustein 18. Session decision on how the reply appears
(three options weighed, see PROTOKOLL_experiment.md): every turn that
produces its own text streams live into its own chat bubble
(_chat_start_stream_line()/_chat_append_stream_chunk(), the same
Phase 1 methods — one bubble per LLM turn now, instead of one for the
whole multi-turn conversation), and each tool call the model requests
gets a short "🔧 Calling <name>…" system line between bubbles
(_chat_append_system()) — the most transparent of the three options
discussed, deliberately a visible change from before (where
intermediate turns were entirely invisible, only the final answer
ever appeared). _chat_on_mcp_stream_done() is the new terminal
handler, same "bookkeeping only, text already on screen" split as
_chat_on_stream_done() vs _chat_on_reply().
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextBrowser, QSizePolicy, QFrame, QSplitter,
    QDialog,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor

import frozen_paths
import garmin_config as cfg

from .dialog_chat_history import ChatHistoryDialog


def _load_ollama_client():
    """Lazy import — mirrors the add_to_path() + import pattern used for
    other flat-import package modules elsewhere in the app layer (e.g. the
    context pipeline calls in panel_outputs.py). Not done at module top-level
    so panel_chat.py stays importable before sys.path is fully wired up.

    ollama_client.py lives in clients/ — a dedicated leaf-node package for
    external tool/service integrations (Ollama now; the v1.9 SQLite-proxy is
    a plausible future sibling per KONZEPT_mcp_sqlite_proxy.md), deliberately
    separate from garmin/ (Sole-Write-Authority over the Garmin pipeline
    silos only). Flat-import style like garmin/ and app/ — no relative
    imports inside clients/, so no sys.modules package registration needed."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import ollama_client
    return ollama_client


def _load_mcp_tool_chat():
    """Lazy import, same pattern/reasoning as _load_ollama_client() above
    — mcp_tool_chat.py (the MCP tool-calling turn loop, built and
    end-to-end-verified in garmin_collector-3_experiment, see that
    repo's PROTOKOLL_experiment.md) lives in clients/ alongside
    ollama_client.py/mcp_client.py."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import mcp_tool_chat
    return mcp_tool_chat


def _load_mcp_client():
    """Lazy import — needed directly (not only via mcp_tool_chat's own
    internal use of it) so _chat_on_send()'s MCP-mode worker can catch
    McpClientError specifically, the same way it already catches
    OllamaError for the plain Ollama-only path below."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import mcp_client
    return mcp_client


def _load_cloud_tool_chat():
    """Lazy import, same pattern as _load_mcp_tool_chat() above —
    cloud_tool_chat.py (the Cloud-LLM + MCP tool-calling turn loop,
    mirrors mcp_tool_chat.py but sits on cloud_llm_client.chat_with_tools()
    instead of ollama_client's) lives in clients/ alongside the rest."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import cloud_tool_chat
    return cloud_tool_chat


def _load_mcp_process():
    """Lazy import, same pattern as the loaders above — mcp_process.py
    (Start/Stop process control for clients/mcp_server.py, shared with
    app/panel_mcp.py's own new Stop button) lives in clients/ alongside
    the other three."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import mcp_process
    return mcp_process


def _load_cloud_llm_client():
    """Lazy import, same pattern as the loaders above — cloud_llm_client.py
    (the Cloud-LLM dispatcher; never imports a provider module like
    cloud_llm_anthropic.py directly, see that file's own docstring for
    the split) lives in clients/ alongside the other four."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import cloud_llm_client
    return cloud_llm_client


def _load_cloud_credential_store():
    """Lazy import, same pattern as the loaders above —
    cloud_credential_store.py (WCM-backed cloud API key storage, one
    entry per provider, Baustein 23) lives in clients/ alongside the
    other six."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import cloud_credential_store
    return cloud_credential_store


def _load_chat_session_store():
    """Lazy import, same pattern as the loaders above —
    chat_session_store.py (Chat-Session-Logging/Resume, Baustein 21)
    lives in clients/ alongside the other five. Never imported by
    app/dialog_chat_history.py itself — that dialog only displays what
    this panel already fetched, see that module's own docstring."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import chat_session_store
    return chat_session_store


def _sort_models_qwen_first(models: list[str]) -> list[str]:
    """Model dropdown ordering (Baustein 10, session feedback: "die
    Liste so filtern das qwen oben steht und der Rest alphabetisch
    ist") — qwen-family models first (alphabetical among themselves),
    then everything else (also alphabetical). Ordering only, nothing is
    removed — pairs with self._mcp_model_hint above rather than an
    enforced filter, same "hint, not gatekeeping" reasoning. A plain
    substring/prefix check on the model tag (e.g. "qwen3:14b",
    "qwen2.5-coder:7b" both start with "qwen") — no registry of exact
    tags to keep in sync as new qwen variants get pulled."""
    qwen = sorted(m for m in models if m.lower().startswith("qwen"))
    rest = sorted(m for m in models if not m.lower().startswith("qwen"))
    return qwen + rest


class PanelChat(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._history = []          # [{"role": ..., "content": ...}, ...]
        self._system_prompt = None  # loaded once, on Start
        # Cloud LLM connector — populated by _chat_on_cloud_config_loaded()
        # on Start, consumed by _chat_on_send()'s cloud branch. Initialized
        # empty here (not just on Start) so Send's "no usable config" guard
        # never hits an AttributeError, same defensive-init reasoning as
        # self._system_prompt above.
        self._cloud_provider = ""
        self._cloud_model = ""
        self._cloud_api_key = ""
        self._request_running = False
        self._elapsed_seconds = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._chat_tick_elapsed)
        # MCP log split-view (Baustein 9) — tails garmin_data/log/mcp/
        # mcp_*.log while datasource is "mcp", see _chat_tail_mcp_log().
        self._log_file_path = None
        self._log_file_pos = 0
        self._log_tail_timer = QTimer(self)
        self._log_tail_timer.setInterval(1500)
        self._log_tail_timer.timeout.connect(self._chat_tail_mcp_log)
        # Chat-Session-Logging/Resume (Baustein 21) — see module
        # docstring's own paragraph for the full picture.
        self._chat_session_path = None       # Path | None — None until the first auto-save
        self._chat_session_created_at = None # str | None — set once, preserved across saves
        self._chat_loaded_model = None       # str | None — pre-select once the model list loads
        self._chat_resume_pending = False    # tells _chat_load_system_prompt() to skip its reset once
        self._chat_loaded_not_started = False  # combos locked by Load, not yet by a real Start
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        heading = QLabel("Chat")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {self._app.TEXT};")
        outer.addWidget(heading)

        # ── Status box — visible before Start, age display + reachability ──
        status_box = QFrame()
        status_box.setStyleSheet(f"background: {self._app.BG2};")
        status_lay = QVBoxLayout(status_box)
        status_lay.setContentsMargins(10, 8, 10, 8)
        status_lay.setSpacing(4)

        self._age_label = QLabel("Context files: —")
        self._age_label.setFont(QFont("Segoe UI", 9))
        self._age_label.setStyleSheet(f"color: {self._app.TEXT2};")
        status_lay.addWidget(self._age_label)

        self._reach_label = QLabel("Ollama: —")
        self._reach_label.setFont(QFont("Segoe UI", 9))
        self._reach_label.setStyleSheet(f"color: {self._app.TEXT2};")
        status_lay.addWidget(self._reach_label)

        outer.addWidget(status_box)

        # ── Config row: Backend (ollama/cloud) + Datenquelle (json/mcp) ─────
        # dropdowns, per NOTES_v1.7.2_chat_panel_konzept.md, PLUS Start/Stop
        # on the same row (Baustein 10, session feedback: "start/stop
        # verschieben damit mehr platz für den chat ist" — merging onto one
        # row frees a full row of vertical height for the chat area below).
        # Enabled from the start (see module docstring addendum) —
        # addItems() below is wrapped in blockSignals() so the initial
        # selection does not fire _chat_on_new_chat() before self._chat_view
        # even exists yet.
        config_row = QHBoxLayout()
        config_row.setSpacing(8)

        backend_lbl = QLabel("Backend")
        backend_lbl.setFont(QFont("Segoe UI", 9))
        backend_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        config_row.addWidget(backend_lbl)

        self._backend_combo = QComboBox()
        self._backend_combo.setFont(QFont("Segoe UI", 9))
        self._backend_combo.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox:disabled {{ background: {self._app.BG2}; color: {self._app.TEXT2}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._backend_combo.blockSignals(True)
        self._backend_combo.addItems(["ollama", "cloud"])
        self._backend_combo.blockSignals(False)
        self._backend_combo.currentTextChanged.connect(self._chat_on_backend_changed)
        config_row.addWidget(self._backend_combo)
        # ▼ fallback label — Qt6/Windows suppresses the native drop-down
        # arrow once a QComboBox has a stylesheet, same issue already
        # worked around for the xlsx/sheet combos in garmin_app_base.py.
        _backend_arrow = QLabel("▼")
        _backend_arrow.setFont(QFont("Segoe UI", 7))
        _backend_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        _backend_arrow.setFixedWidth(16)
        config_row.addWidget(_backend_arrow)

        datasource_lbl = QLabel("Source")
        datasource_lbl.setFont(QFont("Segoe UI", 9))
        datasource_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        config_row.addWidget(datasource_lbl)

        self._datasource_combo = QComboBox()
        self._datasource_combo.setFont(QFont("Segoe UI", 9))
        self._datasource_combo.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox:disabled {{ background: {self._app.BG2}; color: {self._app.TEXT2}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._datasource_combo.blockSignals(True)
        self._datasource_combo.addItems(["json", "mcp"])
        self._datasource_combo.blockSignals(False)
        self._datasource_combo.currentTextChanged.connect(
            self._chat_on_datasource_changed)
        config_row.addWidget(self._datasource_combo)
        # ▼ fallback label — same reason as _backend_arrow above.
        _datasource_arrow = QLabel("▼")
        _datasource_arrow.setFont(QFont("Segoe UI", 7))
        _datasource_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        _datasource_arrow.setFixedWidth(16)
        config_row.addWidget(_datasource_arrow)

        config_row.addStretch()

        # Start/Stop — moved onto this row from their own (Baustein 10).
        self._start_btn = QPushButton("Start")
        self._start_btn.setFont(QFont("Segoe UI", 9))
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT}; color: white; "
            f"border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ background: {self._app.BG3}; color: {self._app.TEXT2}; }}")
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self._chat_on_start)
        config_row.addWidget(self._start_btn)

        # Stop — NOTES_v1.7.2_chat_panel_konzept.md's Start/Stop pair,
        # garmin_collector-3_experiment Baustein 8b. Starts disabled (there
        # is nothing to stop before Start succeeds) — enabled together
        # with the other post-Start controls in _chat_on_models_loaded()/
        # _chat_on_cloud_config_loaded().
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFont(QFont("Segoe UI", 9))
        self._stop_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; }}")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._chat_on_stop)
        config_row.addWidget(self._stop_btn)

        # Chat History (Baustein 21, Chat-Session-Logging/Resume) — a
        # dialog rather than a dropdown, session decision (see module
        # docstring): a dropdown could not offer Delete cleanly. Always
        # enabled, independent of Start/Stop state — it only lists/loads/
        # deletes files on disk, never touches the currently running
        # conversation unless the user explicitly picks Load.
        self._chat_history_btn = QPushButton("Chat History")
        self._chat_history_btn.setFont(QFont("Segoe UI", 9))
        self._chat_history_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        self._chat_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chat_history_btn.clicked.connect(self._chat_on_open_history)
        config_row.addWidget(self._chat_history_btn)

        outer.addLayout(config_row)

        # Cloud backend has no chat client yet (see PROTOKOLL_experiment.md)
        # — read-only status line instead of a model dropdown, per
        # KONZEPT_v1.7.2's "cloud → keine freie Auswahl" decision. Hidden
        # unless backend == "cloud" (see _chat_on_backend_changed()).
        self._cloud_info_label = QLabel("")
        self._cloud_info_label.setFont(QFont("Segoe UI", 9))
        self._cloud_info_label.setStyleSheet(f"color: {self._app.YELLOW};")
        self._cloud_info_label.setWordWrap(True)
        self._cloud_info_label.setVisible(False)
        outer.addWidget(self._cloud_info_label)

        # ── Model row + New Chat ────────────────────────────────────────────
        model_row = QHBoxLayout()
        model_row.setSpacing(8)

        self._model_combo = QComboBox()
        self._model_combo.setFont(QFont("Segoe UI", 9))
        self._model_combo.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Fixed)
        self._model_combo.setEnabled(False)
        self._model_combo.currentIndexChanged.connect(self._chat_on_model_changed)
        model_row.addWidget(self._model_combo)
        # ▼ fallback label — same reason as _backend_arrow above. Instance
        # attribute (not a local var like the other two arrows) because its
        # visibility must mirror _model_combo's own in
        # _chat_on_backend_changed() (hidden for backend == "cloud").
        self._model_arrow = QLabel("▼")
        self._model_arrow.setFont(QFont("Segoe UI", 7))
        self._model_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        self._model_arrow.setFixedWidth(16)
        model_row.addWidget(self._model_arrow)

        self._new_chat_btn = QPushButton("Neuer Chat")
        self._new_chat_btn.setFont(QFont("Segoe UI", 9))
        self._new_chat_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; }}")
        self._new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_chat_btn.setEnabled(False)
        self._new_chat_btn.clicked.connect(self._chat_on_new_chat)
        model_row.addWidget(self._new_chat_btn)

        outer.addLayout(model_row)

        # MCP model hint (Baustein 10, session feedback: "hinweis das qwen3
        # oder qwen2.5 coder benutzt werden sollen") — MCP_TESTLAUF_BERICHT_
        # FINAL.md (mcp_test/) found the qwen family the only reliably
        # tool-calling-capable local models tested so far; every other
        # model tried ranged from unreliable to unusable (see that report's
        # "Gesamteinschätzung"). A hint, not an enforced restriction — the
        # dropdown still lists every installed model, nothing is filtered
        # out or blocked, matching this panel's existing "no active
        # gatekeeping, just visibility" stance elsewhere (e.g. the cloud
        # API-key-missing warning). Shown only for datasource "mcp", where
        # this actually matters — plain chat has no such constraint.
        self._mcp_model_hint = QLabel(
            "💡 For MCP tool-calling, qwen3 or qwen2.5-coder models are the "
            "recommended choice so far.")
        self._mcp_model_hint.setFont(QFont("Segoe UI", 8))
        self._mcp_model_hint.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_model_hint.setWordWrap(True)
        self._mcp_model_hint.setVisible(False)
        outer.addWidget(self._mcp_model_hint)

        # ── Chat history + MCP log split-view ───────────────────────────────
        # Right pane tails the real operational log file, only while
        # datasource is "mcp" — see _chat_tail_mcp_log()'s own docstring
        # and the module docstring's "Split-view" paragraph.
        self._chat_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._chat_view = QTextBrowser()
        self._chat_view.setStyleSheet(
            f"background: {self._app.BG2}; color: {self._app.TEXT}; border: none;")
        self._chat_view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        self._chat_splitter.addWidget(self._chat_view)

        self._log_container = QWidget()
        log_lay = QVBoxLayout(self._log_container)
        log_lay.setContentsMargins(0, 0, 0, 0)
        log_lay.setSpacing(4)

        log_heading = QLabel("MCP Log")
        log_heading.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        log_heading.setStyleSheet(f"color: {self._app.TEXT2};")
        log_lay.addWidget(log_heading)

        self._log_view = QTextBrowser()
        self._log_view.setStyleSheet(
            f"background: {self._app.BG2}; color: {self._app.TEXT2}; "
            f"border: none; font-family: Consolas, monospace;")
        self._log_view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Expanding)
        log_lay.addWidget(self._log_view)

        self._chat_splitter.addWidget(self._log_container)
        self._chat_splitter.setStretchFactor(0, 2)
        self._chat_splitter.setStretchFactor(1, 1)
        self._log_container.setVisible(False)

        outer.addWidget(self._chat_splitter, stretch=1)

        # ── Input row ────────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setFont(QFont("Segoe UI", 9))
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 6px 10px; }}")
        self._input.setEnabled(False)
        self._input.returnPressed.connect(self._chat_on_send)
        input_row.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setFont(QFont("Segoe UI", 9))
        self._send_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT}; color: white; "
            f"border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ background: {self._app.BG3}; color: {self._app.TEXT2}; }}")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._chat_on_send)
        input_row.addWidget(self._send_btn)

        outer.addLayout(input_row)

        self._status_label = QLabel("")
        self._status_label.setFont(QFont("Segoe UI", 8))
        self._status_label.setStyleSheet(f"color: {self._app.TEXT2};")
        outer.addWidget(self._status_label)

    # ── Tab-open (called from garmin_app_base._on_tab_changed) ─────────────────

    def _chat_on_tab_open(self):
        """No active chat prep here — only age display + a lightweight
        reachability ping (KONZEPT §5). Safe to call repeatedly."""
        self._chat_refresh_age_display()

        def worker():
            reachable = _load_ollama_client().is_reachable()
            self._app._dispatch(lambda: self._chat_set_reachable(reachable))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _chat_set_reachable(self, reachable: bool):
        self._reach_label.setText(
            "Ollama: reachable" if reachable else "Ollama: not reachable")

    def _chat_refresh_age_display(self):
        s = self._app._panel_settings._collect_settings()
        base = Path(s.get("base_dir", ""))
        json_path   = base / "dashboards" / "health_garmin.json"
        prompt_path = base / "dashboards" / "health_garmin_prompt.md"

        parts = []
        if json_path.exists():
            generated = None
            try:
                import json as _json
                with open(json_path, "r", encoding="utf-8") as f:
                    generated = _json.load(f).get("generated")
            except (OSError, ValueError, AttributeError):
                # OSError: Lesefehler. ValueError: json.JSONDecodeError
                # (Subklasse) bei kaputtem JSON. AttributeError: .get() auf
                # einem geladenen Nicht-Dict (z. B. Top-Level-Liste/-String).
                # Verengt aus bewusstem Anlass (Precondition Teil B, v1.6.6
                # Drift-Check) — vorher pauschales Exception, Risk: broad.
                generated = None
            parts.append(f"health_garmin.json: {generated or 'age unknown'}")
        else:
            parts.append("health_garmin.json: not found")

        parts.append(
            "health_garmin_prompt.md: found" if prompt_path.exists()
            else "health_garmin_prompt.md: not found")

        self._age_label.setText("Context files — " + " · ".join(parts))

    # ── MCP log split-view (Baustein 9) ─────────────────────────────────────

    def _chat_tail_mcp_log(self):
        """Polls the operational log file clients/mcp_server.py writes on
        every headless start (garmin_data/log/mcp/mcp_<timestamp>.log,
        see that module's _start_operational_log()) — the SAME log both
        this panel's own headless Start and app/panel_mcp.py's Start
        write to, no new logging mechanism (module docstring's "Split-
        view" paragraph). A fresh server start writes a NEW timestamped
        file — detected below by picking the lexicographically newest
        mcp_*.log each tick (the timestamp format sorts correctly as a
        plain string) and resetting the read position/view when it
        changes. No file yet (server never started, or base_dir
        unreadable) is a silent no-op — an empty pane is self-
        explanatory, not an error."""
        s = self._app._panel_settings._collect_settings()
        log_dir = Path(s.get("base_dir", "")) / "garmin_data" / "log" / "mcp"
        try:
            candidates = sorted(log_dir.glob("mcp_*.log"))
        except OSError:
            return
        if not candidates:
            return

        newest = candidates[-1]
        if newest != self._log_file_path:
            self._log_file_path = newest
            self._log_file_pos = 0
            self._log_view.clear()

        try:
            with open(self._log_file_path, "r", encoding="utf-8",
                      errors="replace") as f:
                f.seek(self._log_file_pos)
                new_text = f.read()
                self._log_file_pos = f.tell()
        except OSError:
            return

        if new_text:
            self._log_view.moveCursor(QTextCursor.MoveOperation.End)
            self._log_view.insertPlainText(new_text)
            # insertPlainText() alone does not follow the viewport — this
            # runs from a background timer, not user typing, so nothing
            # else would keep new lines in view otherwise.
            self._log_view.ensureCursorVisible()

    # ── Start ────────────────────────────────────────────────────────────────

    def _chat_on_start(self):
        self._start_btn.setEnabled(False)
        # Baustein 21 — once Start is actually attempted, combos are no
        # longer merely "locked because a session was loaded" — see
        # self._chat_loaded_not_started's own comment in __init__.
        # Reset unconditionally, regardless of whether Start ends up
        # succeeding: every failure branch below already re-enables the
        # combos itself if it bails out, same as before this Baustein.
        self._chat_loaded_not_started = False
        # Backend/Datenquelle are fixed for the duration of a session once
        # Start is clicked (NOTES_v1.7.2_chat_panel_konzept.md: "fix,
        # festgelegt beim Start — kein Wechsel während dessen") — locked
        # here, mirrored back open in every failure branch below and in
        # _chat_on_stop(). Session feedback: switching mid-chat only reset
        # history, never actually locked anything, which let a running
        # mcp-backed conversation be silently mixed with a json one.
        self._backend_combo.setEnabled(False)
        self._datasource_combo.setEnabled(False)

        if self._datasource_combo.currentText() == "mcp":
            # Ensures the MCP server is running before proceeding — per
            # KONZEPT_v1.7.2, Chat-Panel-Start recognizes an already-
            # running server (started here or from the MCP Server tab)
            # and only starts a NEW one if none is reachable (see
            # mcp_process.start()'s own docstring). Synchronous — a
            # 0.3s-timeout TCP probe plus, at most, a non-blocking Popen()
            # call, same "brief local check, no worker thread needed"
            # reasoning as _chat_on_cloud_config_loaded() below.
            mcp_process = _load_mcp_process()
            ok, message = mcp_process.start()
            if not ok:
                self._chat_append_system(f"Could not start the MCP server: {message}")
                self._start_btn.setEnabled(True)
                self._backend_combo.setEnabled(True)
                self._datasource_combo.setEnabled(True)
                self._status_label.setText("")
                return

        if self._backend_combo.currentText() == "cloud":
            # Local file read only, no network call — safe to do inline,
            # same "no active chat prep before Start" timing as the ollama
            # path below, just synchronous since it needs no worker thread.
            self._status_label.setText("Loading cloud configuration …")
            self._chat_on_cloud_config_loaded()
            return

        self._status_label.setText("Loading models …")

        def worker():
            client = _load_ollama_client()
            try:
                models = client.list_models()
                error = None
            except client.OllamaError as e:
                models, error = [], str(e)
            self._app._dispatch(lambda: self._chat_on_models_loaded(models, error))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _chat_on_models_loaded(self, models: list, error: str):
        if error:
            self._chat_append_system(f"Ollama not reachable: {error}")
            self._start_btn.setEnabled(True)
            self._backend_combo.setEnabled(True)
            self._datasource_combo.setEnabled(True)
            self._status_label.setText("")
            return
        if not models:
            self._chat_append_system(
                "No models installed — install one via `ollama pull <model>` "
                "and click Start again.")
            self._start_btn.setEnabled(True)
            self._backend_combo.setEnabled(True)
            self._datasource_combo.setEnabled(True)
            self._status_label.setText("")
            return

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(_sort_models_qwen_first(models))
        # Baustein 21 — a resumed session's own model, if it is still
        # installed; leaves the default selection untouched otherwise
        # (a model that no longer exists, or a fresh/non-resumed Start,
        # both fall through silently — same as before this Baustein).
        if self._chat_loaded_model:
            idx = self._model_combo.findText(self._chat_loaded_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            self._chat_loaded_model = None
        self._model_combo.blockSignals(False)

        self._chat_load_system_prompt()

        self._model_combo.setEnabled(True)
        self._new_chat_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("")

    def _chat_on_cloud_config_loaded(self):
        """Reads and displays the same local config file app/panel_mcp.py's
        Cloud Credentials block writes (garmin_config.MCP_LLM_CONFIG_FILE),
        read-only, matching KONZEPT_v1.7.2's "cloud → keine freie Auswahl;
        read-only Anzeige ... Warnhinweis" decision. Also stores
        provider/model/api_key as instance state (Cloud-LLM-Connector
        Baustein, garmin_collector-3_experiment) — _chat_on_send()'s cloud
        branch below reads these rather than re-reading the file on every
        Send, same "load once on Start" timing as
        _chat_load_system_prompt(). Config is read fresh on every Start,
        so no staleness risk if it changes between sessions.

        Baustein 23: the API key itself no longer lives in
        MCP_LLM_CONFIG_FILE — only provider/model do; the key is read
        from Windows Credential Manager (clients/cloud_credential_store.py,
        one entry per provider), looked up under the SAME normalized
        (stripped/lower-cased) provider name _mcp_save_cloud_config()
        used to store it — the raw file field is looked up as-is
        everywhere else in this function purely for display, but the
        WCM lookup must use the normalized form or a pre-Baustein-16
        legacy free-text value (e.g. "  Anthropic ", see
        app/panel_mcp.py::_mcp_set_cloud_provider()'s own docstring)
        would silently miss its own key."""
        import json
        try:
            data = json.loads(cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}

        provider = data.get("provider", "")
        model = data.get("model", "")
        provider_key = provider.strip().lower() if provider else ""
        api_key = _load_cloud_credential_store().get_api_key(provider_key) if provider_key else None
        has_key = bool(api_key)

        self._cloud_provider = provider_key
        self._cloud_model = model
        self._cloud_api_key = api_key or ""

        if provider and model:
            text = f"Cloud config: {provider} / {model}"
            if not has_key:
                text += "  ⚠ no API key saved — set one on the MCP Server tab."
        else:
            text = "⚠ No cloud configuration saved — set it up on the MCP Server tab."
        self._cloud_info_label.setText(text)

        self._chat_load_system_prompt()

        self._new_chat_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("")

    def _chat_on_stop(self):
        """Ends the local chat session (mirrors the pre-Start UI state)
        and, if datasource is "mcp", also stops the MCP server itself —
        unconditionally, regardless of who started it or from which
        panel (KONZEPT_v1.7.2's pragmatic, not ownership-based, Stop
        decision — see clients/mcp_process.py's own module docstring).
        self._history is left as-is; the next Start's own
        _chat_load_system_prompt()/_chat_on_cloud_config_loaded() call
        already resets it, same as it already does today.

        Baustein 21: self._chat_session_path/_chat_session_created_at
        are reset here too — a Start after Stop (without an
        intervening New Chat click) still begins a fresh conversation
        via _chat_load_system_prompt()'s own history reset, so the
        NEXT auto-save must create a new file rather than silently
        overwrite this (Stopped) conversation's file with unrelated
        content."""
        self._stop_btn.setEnabled(False)
        self._model_combo.setEnabled(False)
        self._new_chat_btn.setEnabled(False)
        self._input.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._backend_combo.setEnabled(True)
        self._datasource_combo.setEnabled(True)
        self._status_label.setText("")
        self._chat_session_path = None
        self._chat_session_created_at = None

        if self._datasource_combo.currentText() == "mcp":
            mcp_process = _load_mcp_process()
            ok, message = mcp_process.stop()
            self._chat_append_system(
                message if ok else f"Could not stop the MCP server: {message}")

    def _chat_load_system_prompt(self):
        s = self._app._panel_settings._collect_settings()
        prompt_path = Path(s.get("base_dir", "")) / "dashboards" / "health_garmin_prompt.md"
        if prompt_path.exists():
            try:
                self._system_prompt = prompt_path.read_text(encoding="utf-8")
            except OSError:
                self._system_prompt = None
        else:
            self._system_prompt = None

        if self._chat_resume_pending:
            # Baustein 21 — Start is continuing a session
            # _chat_on_load_session() already restored into
            # self._history; must not be wiped here. self._system_prompt
            # above is still refreshed unconditionally (cheap, and stays
            # correct for a LATER New Chat), only the reset below is
            # skipped, and only once.
            self._chat_resume_pending = False
            return

        # garmin_collector-3_experiment, Baustein 30: this branch already
        # reset self._history (the actual conversation data sent to the
        # model) on every fresh Start — a Stop then Start without an
        # intervening New Chat click was, from the model's point of view,
        # already a new conversation. But self._chat_view (the VISIBLE
        # transcript) was never cleared here, only in _chat_on_new_chat()
        # — so the old messages stayed on screen, looking like they were
        # still part of the (actually fresh) conversation. Found live:
        # Timo — Stop, Start again, old chat still shown. Both must reset
        # together, same as _chat_on_new_chat() already does.
        self._chat_view.clear()
        self._history = []
        if self._system_prompt:
            self._history.append({"role": "system", "content": self._system_prompt})

    # ── New Chat (context reset — mandatory, not optional, KONZEPT §4) ─────────

    def _chat_on_new_chat(self):
        self._history = []
        # The JSON-snapshot system prompt (health_garmin_prompt.md) is
        # written for "you have this snapshot", not for tool use — with
        # datasource "mcp" it is deliberately NOT seeded here, so
        # mcp_tool_chat.converse() injects its own DEFAULT_SYSTEM_PROMPT
        # instead (it only does so when history has no existing system
        # message — see that function's own docstring).
        if self._datasource_combo.currentText() != "mcp" and self._system_prompt:
            self._history.append({"role": "system", "content": self._system_prompt})
        self._chat_view.clear()
        # Baustein 21 — a fresh conversation always gets a fresh file;
        # the next completed turn's _chat_save_session() call creates a
        # new one rather than overwriting whatever was loaded/running
        # before. self._chat_loaded_model is unrelated to a specific
        # file, but stale here too (a New Chat means "start over", not
        # "keep half-applying an old load").
        self._chat_session_path = None
        self._chat_session_created_at = None
        self._chat_loaded_model = None
        if self._chat_loaded_not_started:
            # A session was loaded (combos locked immediately, before
            # any Start attempt — see _chat_on_load_session()) but never
            # actually Started — New Chat here is this panel's only way
            # back to a live chat (most concretely: a read-only,
            # non-resumable load, where Start itself stays disabled —
            # see _chat_on_load_session()'s own docstring). A session
            # that IS genuinely running (Start succeeded) never reaches
            # this branch — _chat_on_start() already clears the flag
            # the moment Start is attempted, success or failure.
            self._backend_combo.setEnabled(True)
            self._datasource_combo.setEnabled(True)
            self._chat_loaded_not_started = False

    def _chat_on_model_changed(self, _index: int):
        # Different models have different context limits/styles — carrying
        # history across a model switch is a deliberate non-goal (KONZEPT §4).
        if self._model_combo.isEnabled():
            self._chat_on_new_chat()

    def _chat_apply_backend_visibility(self, is_cloud: bool):
        """Swaps which widget is visible for the given backend — cloud
        has no model list to choose from (read-only status display
        instead, see _chat_on_cloud_config_loaded()). Factored out of
        _chat_on_backend_changed() below (Baustein 21) so
        _chat_on_load_session() can apply the same visibility without
        also triggering that handler's _chat_on_new_chat() reset (the
        loaded history must survive)."""
        self._model_combo.setVisible(not is_cloud)
        self._model_arrow.setVisible(not is_cloud)
        self._cloud_info_label.setVisible(is_cloud)

    def _chat_on_backend_changed(self, backend: str):
        # No isEnabled()-style construction guard needed here (unlike
        # _chat_on_model_changed() above) — _build_ui() wraps its
        # addItems() call in blockSignals(), so this never fires before
        # self._chat_view exists.
        self._chat_apply_backend_visibility(backend == "cloud")
        self._chat_on_new_chat()

    def _chat_apply_datasource_visibility(self, is_mcp: bool):
        """Log split-view (Baustein 9): tied to datasource alone, not to
        Start/Stop state — an empty pane before any server/log exists
        is self-explanatory, see _chat_tail_mcp_log()'s own docstring.
        Factored out of _chat_on_datasource_changed() below (Baustein
        21), same reason as _chat_apply_backend_visibility() above."""
        self._log_container.setVisible(is_mcp)
        self._mcp_model_hint.setVisible(is_mcp)
        if is_mcp:
            self._log_tail_timer.start()
        else:
            self._log_tail_timer.stop()

    def _chat_on_datasource_changed(self, datasource: str):
        # Same context-invalidation principle as a model switch above —
        # mixing plain-chat and MCP-tool-calling history in one
        # conversation is a non-goal, not just a JSON-system-prompt
        # mismatch (see _chat_on_new_chat()'s comment above). Same
        # blockSignals() reasoning as _chat_on_backend_changed() for why
        # no construction guard is needed.
        self._chat_apply_datasource_visibility(datasource == "mcp")
        self._chat_on_new_chat()

    # ── Chat History (Baustein 21, Chat-Session-Logging/Resume) ─────────────

    def _chat_render_history(self):
        """Replays self._history into self._chat_view after a session
        load — the same bubble shape a live conversation would have
        produced (_chat_append_line()), skipping system/tool-role
        entries and content-less assistant turns (a pure tool_calls
        turn with no text of its own) — mirrors what
        _chat_on_mcp_reply()'s own docstring already says about
        intermediate tool round-trips never being rendered as separate
        bubbles even during a live conversation."""
        for m in self._history:
            role = m.get("role")
            content = m.get("content", "")
            if role == "user" and content:
                self._chat_append_line("You", content)
            elif role == "assistant" and content:
                self._chat_append_line("Assistant", content)

    def _chat_save_session(self):
        """Auto-saves the current conversation after a completed turn
        — called from _chat_on_reply()/_chat_on_stream_done()/
        _chat_on_mcp_reply(). Overwrites the SAME file for the whole
        conversation (self._chat_session_path — None until this first
        successful call, fixed afterwards; reset to None by
        _chat_on_new_chat()/_chat_on_stop(), see those methods' own
        comments). source_hash is computed by
        chat_session_store.save_session() itself, not here — single
        source of truth for the hashing rule, see that module's own
        docstring.

        Best-effort: an OSError here (disk full, permissions, base_dir
        unreadable) is swallowed, not surfaced in the chat — session
        logging is a persistence convenience layered on top of the
        conversation, not a precondition for having one; the same
        "informational, never blocking" stance the existing operational
        MCP log already takes (see clients/mcp_server.py's
        _start_operational_log(), which returns None rather than
        raising on a write failure)."""
        base_dir = self._app._panel_settings._collect_settings().get("base_dir", "")
        if not base_dir:
            return
        backend = self._backend_combo.currentText()
        import datetime
        created_at = self._chat_session_created_at or datetime.datetime.now().isoformat()
        session_data = {
            "created_at": created_at,
            "backend": backend,
            "datasource": self._datasource_combo.currentText(),
            "model": self._cloud_model if backend == "cloud" else self._model_combo.currentText(),
            "provider": self._cloud_provider if backend == "cloud" else "",
            "messages": self._history,
        }
        store = _load_chat_session_store()
        try:
            self._chat_session_path = store.save_session(
                base_dir, self._chat_session_path, session_data)
            self._chat_session_created_at = created_at
        except OSError:
            pass

    def _chat_on_open_history(self):
        base_dir = self._app._panel_settings._collect_settings().get("base_dir", "")
        store = _load_chat_session_store()
        sessions = store.list_sessions(base_dir)
        dlg = ChatHistoryDialog(self, sessions)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        result = dlg.get_result()
        if result is None:
            return
        action, path = result
        if action == "delete":
            store.delete_session(path)
        elif action == "load":
            self._chat_on_load_session(store, path)

    def _chat_on_load_session(self, store, path):
        """Loads a saved session picked in ChatHistoryDialog — restores
        Backend/Datenquelle/history and renders the transcript
        read-only immediately (no network needed just to view it).
        Continuing it live still requires a Start click, same
        reachability checks as any other Start — self._chat_resume_pending
        tells _chat_load_system_prompt() (reached from either Start
        path) to skip its normal history reset exactly once. Combos are
        locked here already, before any Start attempt (see module
        docstring's own paragraph for the full reasoning) —
        self._chat_loaded_not_started remembers that this is why, so a
        later New Chat can tell "locked by Load" apart from "locked by
        a genuinely running session"."""
        try:
            session_data = store.load_session(path)
        except store.ChatSessionError as e:
            self._chat_append_system(f"Could not load session: {e}")
            return

        backend = session_data.get("backend", "ollama")
        datasource = session_data.get("datasource", "json")
        is_cloud = backend == "cloud"
        is_mcp = datasource == "mcp"

        self._backend_combo.blockSignals(True)
        self._backend_combo.setCurrentText(backend)
        self._backend_combo.blockSignals(False)
        self._datasource_combo.blockSignals(True)
        self._datasource_combo.setCurrentText(datasource)
        self._datasource_combo.blockSignals(False)
        self._chat_apply_backend_visibility(is_cloud)
        self._chat_apply_datasource_visibility(is_mcp)
        self._backend_combo.setEnabled(False)
        self._datasource_combo.setEnabled(False)
        self._chat_loaded_not_started = True

        self._history = session_data.get("messages", [])
        self._chat_session_path = Path(path)
        self._chat_session_created_at = session_data.get("created_at")
        self._chat_loaded_model = session_data.get("model")
        self._chat_resume_pending = True

        self._chat_view.clear()
        if is_cloud:
            self._chat_append_system(
                f"Loaded session — cloud "
                f"({session_data.get('provider', '?')}/{session_data.get('model', '?')}), "
                f"saved {session_data.get('created_at', '?')}")
        self._chat_render_history()

        base_dir = self._app._panel_settings._collect_settings().get("base_dir", "")
        if store.is_resumable(session_data, base_dir):
            self._start_btn.setEnabled(True)
        else:
            self._chat_append_system(
                "Read-only — source data (health_garmin.json) has changed "
                "since this session was saved. Start is disabled; use New "
                "Chat to begin a fresh conversation.")
            self._start_btn.setEnabled(False)
        self._new_chat_btn.setEnabled(True)

    # ── Send ─────────────────────────────────────────────────────────────────

    def _chat_on_send(self):
        if self._request_running:
            return
        text = self._input.text().strip()
        if not text:
            return

        is_cloud = self._backend_combo.currentText() == "cloud"
        is_mcp = self._datasource_combo.currentText() == "mcp"

        if is_cloud and not (self._cloud_provider and self._cloud_model
                              and self._cloud_api_key):
            # Mirrors _chat_on_cloud_config_loaded()'s own warning label —
            # Start already unlocks Send even with an incomplete config
            # (KONZEPT_v1.7.2: warn, don't block), so Send needs its own
            # guard against actually attempting a call that can only fail.
            self._chat_append_system(
                "No usable cloud configuration — set provider/model/API "
                "key on the MCP Server tab, then press Start again.")
            return

        model = self._model_combo.currentText()
        self._history.append({"role": "user", "content": text})
        self._chat_append_line("You", text)
        self._input.clear()

        self._request_running = True
        self._send_btn.setEnabled(False)
        self._elapsed_seconds = 0
        self._status_label.setText("Waiting for response — 0s")
        self._elapsed_timer.start()

        history = list(self._history)  # snapshot — worker never touches self._history

        if is_cloud and is_mcp:
            provider, cloud_model, api_key = (
                self._cloud_provider, self._cloud_model, self._cloud_api_key)

            def worker():
                # Lazy imports get their own guarded try/except, separate
                # from the business-logic try below (garmin_collector-3_
                # experiment, post-v1.7.2 review — see PROTOKOLL_experiment.md,
                # "silent worker death"): an import failure used to run
                # unguarded ahead of the try block below, so it killed this
                # thread with zero _app._dispatch() call — the UI stayed on
                # "Waiting for response" forever, no error, no log. A second
                # reason this needs its OWN try rather than just moving the
                # imports inside the business-logic try: the except clauses
                # below reference cloud_llm_client.CloudLlmError/mcp_client.
                # McpClientError by name — if the import that binds that
                # very name had failed, evaluating the except clause itself
                # would raise a fresh NameError while Python is still trying
                # to match the original exception, which is just as
                # unguarded as the original bug.
                try:
                    cloud_tool_chat = _load_cloud_tool_chat()
                    cloud_llm_client = _load_cloud_llm_client()
                    mcp_client = _load_mcp_client()
                except Exception as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                    return
                started = False
                try:
                    for event in cloud_tool_chat.converse_stream(
                            provider, cloud_model, api_key, history,
                            system_prompt=cloud_tool_chat.DEFAULT_SYSTEM_PROMPT):
                        etype = event["type"]
                        if etype == "text":
                            if not started:
                                self._app._dispatch(
                                    lambda: self._chat_start_stream_line("Assistant"))
                                started = True
                            self._app._dispatch(
                                lambda c=event["text"]: self._chat_append_stream_chunk(c))
                        elif etype == "tool_call":
                            # Next turn's text (if any) starts its own new
                            # bubble — see converse_stream()'s own docstring.
                            started = False
                            self._app._dispatch(
                                lambda n=event["name"]:
                                    self._chat_append_system(f"🔧 Calling {n}…"))
                        elif etype == "final":
                            self._app._dispatch(
                                lambda ev=event: self._chat_on_mcp_stream_done(ev))
                except mcp_client.McpClientError as e:
                    # Same "the MCP server itself was never reachable this
                    # turn" case as the ollama+mcp branch below — see
                    # cloud_tool_chat.converse_stream()'s own docstring.
                    self._app._dispatch(lambda err=e: self._chat_on_mcp_unreachable(err))
                except cloud_llm_client.CloudLlmError as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                except Exception as e:
                    # Fallback net (see docstring above worker()'s first
                    # try) — an unclassified failure still reaches the UI
                    # instead of silently killing this thread.
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
        elif is_cloud:
            provider, cloud_model, api_key = (
                self._cloud_provider, self._cloud_model, self._cloud_api_key)

            def worker():
                # See the is_cloud-and-is_mcp worker above for why the
                # lazy import gets its own try/except, separate from the
                # business-logic one below.
                try:
                    client = _load_cloud_llm_client()
                except Exception as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                    return
                chunks = []
                started = False
                try:
                    for chunk in client.chat_stream(provider, cloud_model, api_key, history):
                        if not started:
                            self._app._dispatch(lambda: self._chat_start_stream_line("Assistant"))
                            started = True
                        chunks.append(chunk)
                        self._app._dispatch(lambda c=chunk: self._chat_append_stream_chunk(c))
                    self._app._dispatch(lambda: self._chat_on_stream_done("".join(chunks)))
                except client.CloudLlmError as e:
                    self._app._dispatch(
                        lambda err=e, text="".join(chunks): self._chat_on_stream_error(text, err))
                except Exception as e:
                    self._app._dispatch(
                        lambda err=e, text="".join(chunks): self._chat_on_stream_error(text, err))
        elif is_mcp:
            def worker():
                # See the is_cloud-and-is_mcp worker above for why the
                # lazy imports get their own try/except, separate from
                # the business-logic one below.
                try:
                    ollama_client = _load_ollama_client()
                    mcp_tool_chat = _load_mcp_tool_chat()
                    mcp_client = _load_mcp_client()
                except Exception as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                    return
                try:
                    result = mcp_tool_chat.converse(
                        model, history,
                        system_prompt=mcp_tool_chat.DEFAULT_SYSTEM_PROMPT)
                    self._app._dispatch(lambda: self._chat_on_mcp_reply(result))
                except mcp_client.McpClientError as e:
                    # The MCP server itself was never reachable this turn
                    # (see mcp_tool_chat.converse()'s own docstring — this
                    # is the one failure mode it does not absorb into the
                    # conversation) — shown in-chat with a concrete next
                    # step, no separate dialog (KONZEPT_v1.7.2 decision).
                    self._app._dispatch(lambda err=e: self._chat_on_mcp_unreachable(err))
                except ollama_client.OllamaError as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                except Exception as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
        else:
            def worker():
                # See the is_cloud-and-is_mcp worker above for why the
                # lazy import gets its own try/except, separate from the
                # business-logic one below.
                try:
                    client = _load_ollama_client()
                except Exception as e:
                    self._app._dispatch(lambda err=e: self._chat_on_error(err))
                    return
                chunks = []
                started = False
                try:
                    for chunk in client.chat_stream(model, history):
                        if not started:
                            self._app._dispatch(lambda: self._chat_start_stream_line("Assistant"))
                            started = True
                        chunks.append(chunk)
                        self._app._dispatch(lambda c=chunk: self._chat_append_stream_chunk(c))
                    self._app._dispatch(lambda: self._chat_on_stream_done("".join(chunks)))
                except client.OllamaError as e:
                    self._app._dispatch(
                        lambda err=e, text="".join(chunks): self._chat_on_stream_error(text, err))
                except Exception as e:
                    self._app._dispatch(
                        lambda err=e, text="".join(chunks): self._chat_on_stream_error(text, err))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _chat_tick_elapsed(self):
        self._elapsed_seconds += 1
        self._status_label.setText(f"Waiting for response — {self._elapsed_seconds}s")

    def _chat_on_reply(self, reply: str):
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        self._history.append({"role": "assistant", "content": reply})
        self._chat_append_line("Assistant", reply)
        self._chat_save_session()

    def _chat_on_error(self, error: Exception):
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        # Failed turn — drop the user message we optimistically appended so
        # a retry does not duplicate it in the next request's history.
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._chat_append_system(str(error))

    def _chat_on_stream_done(self, full_text: str):
        """Streaming counterpart to _chat_on_reply() (Baustein 20,
        Phase 1 Streaming). full_text was already rendered
        chunk-by-chunk into self._chat_view via
        _chat_append_stream_chunk() while the worker was running — only
        the bookkeeping tail of _chat_on_reply() remains here (history/
        status/button), no _chat_append_line() call, or the reply would
        appear twice."""
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        self._history.append({"role": "assistant", "content": full_text})
        self._chat_save_session()

    def _chat_on_stream_error(self, partial_text: str, error: Exception):
        """Streaming counterpart to _chat_on_error() (Baustein 20,
        Phase 1 Streaming). partial_text is whatever the worker had
        already yielded before the failure — "" if the connection never
        produced a single chunk (e.g. unreachable), in which case the
        worker never even called _chat_start_stream_line(), so there is
        no dangling speaker label to clean up. Any partial text already
        on screen is left as-is, not erased — a system note below it
        marks it as interrupted rather than a complete answer. Same as
        _chat_on_error(): the incomplete reply is never written into
        self._history, and the user turn that started this request is
        popped so a retry does not duplicate it."""
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        if partial_text:
            self._chat_append_system(f"Response interrupted: {error}")
        else:
            self._chat_append_system(str(error))

    def _chat_on_mcp_reply(self, result: dict):
        """MCP-mode counterpart to _chat_on_reply() above. result is
        mcp_tool_chat.converse()'s return dict — {"content", "messages",
        "hit_max_turns"}. self._history is replaced with result["messages"]
        wholesale (not appended-to) — it already carries the user turn
        this call started from plus every assistant/tool round-trip along
        the way, so the next turn's tool-calling context is preserved.
        Intermediate tool round-trips are not rendered as separate chat
        bubbles here — only the final answer is shown, same one bubble
        per turn shape as the plain-chat path. The MCP log split-view
        (Baustein 9, _chat_tail_mcp_log()) shows the server's own raw
        activity log alongside the chat instead; a per-turn tool-call
        transcript inside the chat bubbles themselves remains a
        separate, still-open idea, not the same thing as that log."""
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        self._history = result["messages"]
        if result["hit_max_turns"]:
            self._chat_append_system(
                "Reached the tool-call turn limit before a final answer — "
                "showing the model's last response below, which may be "
                "incomplete.")
        self._chat_append_line("Assistant", result["content"])
        self._chat_save_session()

    def _chat_on_mcp_stream_done(self, event: dict):
        """Streaming counterpart to _chat_on_mcp_reply() above
        (Baustein 22, Phase 2 Streaming — Cloud+MCP only, see module
        docstring for why Ollama+MCP has no streaming path).
        event["messages"] was already fully reflected on screen while
        the worker ran: each turn's own text was rendered live via
        _chat_start_stream_line()/_chat_append_stream_chunk() (same
        Phase 1 methods, one bubble per turn instead of one for the
        whole conversation) and each tool call got its own marker via
        _chat_append_system() — only the bookkeeping tail remains
        here, same split as _chat_on_stream_done() vs _chat_on_reply()."""
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        self._history = event["messages"]
        if event["hit_max_turns"]:
            self._chat_append_system(
                "Reached the tool-call turn limit before a final answer — "
                "showing the model's last response above, which may be "
                "incomplete.")
        self._chat_save_session()

    def _chat_on_mcp_unreachable(self, error: Exception):
        self._elapsed_timer.stop()
        self._request_running = False
        self._send_btn.setEnabled(True)
        self._status_label.setText("")
        if self._history and self._history[-1]["role"] == "user":
            self._history.pop()
        self._chat_append_system(
            f"{error} — start it on the MCP Server tab, then try again.")

    # ── Chat view helpers ────────────────────────────────────────────────────

    def _chat_append_line(self, speaker: str, text: str):
        safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace("\n", "<br>"))
        self._chat_view.append(f"<b>{speaker}:</b> {safe}")

    def _chat_append_system(self, text: str):
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._chat_view.append(
            f"<i style='color:{self._app.YELLOW};'>⚠ {safe}</i>")

    def _chat_start_stream_line(self, speaker: str):
        """Opens a new chat bubble for a streaming reply (Baustein 20,
        Phase 1 Streaming) — the speaker label as its own paragraph, so
        later chunks (_chat_append_stream_chunk() below) can be
        inserted inline via the cursor instead of
        QTextEdit.append()'s own always-new-paragraph behavior."""
        self._chat_view.append(f"<b>{speaker}:</b> ")
        self._chat_view.moveCursor(QTextCursor.MoveOperation.End)

    def _chat_append_stream_chunk(self, text: str):
        """Inserts one streamed text fragment inline at the end of the
        document (Baustein 20, Phase 1 Streaming) — plain text, not
        HTML (no manual escaping needed, unlike _chat_append_line()'s
        pre-escaped f-string; insertPlainText() never interprets its
        argument as markup). moveCursor(End) runs before every call,
        not just the first — the widget is a read-only QTextBrowser,
        but its text cursor can still move via mouse click/selection
        while a reply is streaming in, same defensive idiom
        _chat_tail_mcp_log() already uses for self._log_view."""
        self._chat_view.moveCursor(QTextCursor.MoveOperation.End)
        self._chat_view.insertPlainText(text)
