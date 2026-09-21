#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/panel_mcp.py
Garmin Local Archive — MCP Server Panel

PanelMcp — PyQt6 QWidget, eigenständiger Tab "MCP Server" in
garmin_app_base.py's QTabWidget.

Layout injected by garmin_app_base._build_ui():
  - self._panel_mcp added as Tab 4 "MCP Server"

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _mcp_* prefix (E-7)
  - get_mcp_settings() / load_mcp_settings(s) — settings passthrough pair,
    analogous to PanelTimer.get_timer_settings() / load_timer_settings(s).
    Called by GarminApp._collect_settings() / GarminApp.__init__().

Scope: this panel was originally settings-persistence-only, never
starting/stopping clients/mcp_server.py itself. A "Start MCP Server"
button was added later that does launch the process directly — the
settings/dropdown fields below still only control what gets written to
SETTINGS_FILE, but process control is no longer out of scope for this
panel. The former "Enable MCP server" checkbox and its
GARMIN_MCP_ENABLED flag were removed once main() stopped reading it and
the Start button made the whole on/off concept moot (see
NOTES_v1.7_teild.md for the original reasoning, NOTES_v1.7_teilg.md for
the removal).

Server config mirror: _mcp_save() additionally writes
garmin_config.MCP_SERVER_CONFIG_FILE
(~/.garmin_mcp_server_config.json) with the same three values
(mcp_enabled, mcp_llm_backend, base_dir) — a mirror, not a new source of
truth. Lets a standalone mcp_server.exe (no GLA installation, no ENV
set) discover the archive path and MCP settings this GUI session last
saved. Still no os.environ write — this remains a pure
file-persistence step, same as the SETTINGS_FILE write beside it. A
write failure here is logged, not shown as a blocking dialog — see
_mcp_save() below.

Cloud LLM config file: this panel is the first and only writer of
garmin_config.MCP_LLM_CONFIG_FILE (~/.garmin_mcp_llm_config.json). Same
three required fields mcp_server.py's _cloud_llm_config_available()
checks (provider, api_key, model) — see clients/mcp_server.py for the
read side. The API key field never reloads a previously saved key into
the widget (QLineEdit.Password echo mode plus deliberately not
pre-filled) — avoids holding the plaintext key in UI widget state
longer than a save action requires. A status label shows whether a key
is currently on disk without displaying it.

Entstehungsgeschichte: siehe CHANGELOG.md v1.7.0.
"""

import subprocess
import sys
from pathlib import Path

import process_status as _process_status

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QFrame, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import frozen_paths
import garmin_config as cfg


def _load_cloud_credential_store():
    """Lazy import, same pattern as _load_mcp_process() below —
    clients/cloud_credential_store.py (Baustein 23, WCM-backed cloud
    API key storage, one entry per provider) lives in clients/
    alongside cloud_llm_client.py."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import cloud_credential_store
    return cloud_credential_store


def _load_mcp_process():
    """Lazy import — mirrors app/panel_chat.py's own client-module
    loaders (see that file's _load_ollama_client() for the full
    reasoning). The Stop button below (garmin_collector-3_experiment,
    see PROTOKOLL_experiment.md, "Baustein 8b") uses the same
    clients/mcp_process.py as the Chat panel's own Start/Stop pair —
    the only clients/ import this panel has ever needed, since
    _resolve_mcp_server_launch_command() below only resolves a PATH for
    Popen, it does not import mcp_server.py as a module."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import mcp_process
    return mcp_process


def _load_cloud_llm_client():
    """Lazy import, same pattern as _load_mcp_process() above —
    clients/cloud_llm_client.py (the Cloud-LLM dispatcher, see that
    module's own docstring) is the single source of truth for which
    cloud providers are actually supported. Used here only to populate
    the Provider dropdown (_PROVIDERS.keys()) — this panel never calls
    .chat() itself, app/panel_chat.py's Start/Send flow does."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import cloud_llm_client
    return cloud_llm_client


def _resolve_mcp_server_launch_command() -> list[str] | None:
    """Build-context-aware launch command for the "Start MCP Server"
    button (v1.7 Teilbauauftrag g). Returns a Popen-ready argv list, or
    None if no valid launch target exists at the resolved path (caller
    shows the error — this function does not touch the GUI).

    T1 (sys.frozen False): [sys.executable, <path to clients/mcp_server.py>]
    — same interpreter GLA itself runs in, no python-search needed
    (unlike garmin_app.py's _find_python(), which searches for a
    standalone interpreter because T2's subprocess model needs one
    independent of the frozen GLA EXE — this button instead prefers the
    two pre-built launchers below for T2/T3.3, see module docstring for
    the "Launcher-Weg" decision).

    T2 (sys.frozen True, mcp_server.exe absent next to the EXE):
    [str(bat_path)] — clients/Starte_MCP_Server.bat, built in Teil f,
    already resolves its own python/cwd internally.

    T3.3 (sys.frozen True, mcp_server.exe present next to the EXE):
    [str(exe_path)] — the standalone --onefile artefact from Teil e.

    T2 vs T3.3 disambiguation is a plain existence check, not a stored
    marker — T3.3 uniquely has mcp_server.exe sitting next to the
    running GLA EXE (T2 never ships that file, only the loose .bat)."""
    if not getattr(sys, "frozen", False):
        script = Path(__file__).resolve().parent.parent / "clients" / "mcp_server.py"
        if not script.exists():
            return None
        return [sys.executable, str(script)]

    exe_dir = Path(sys.executable).parent
    exe_path = exe_dir / "mcp_server.exe"
    if exe_path.exists():
        return [str(exe_path)]

    # Corrected after a real T2 build test (v1.7 Teilbauauftrag g):
    # Starte_MCP_Server.bat sits directly next to the main EXE, same
    # level as mcp_server.exe above — not under a clients/ subfolder as
    # originally assumed from the T1/Dev sys.path layout.
    bat_path = exe_dir / "Starte_MCP_Server.bat"
    if bat_path.exists():
        return [str(bat_path)]

    return None


def _mcp_server_is_running() -> bool:
    """TCP-connect probe against 127.0.0.1:MCP_HTTP_PORT (v1.7.0.1).
    Delegates to process_status.is_mcp_running() (v1.7.2.4) — extracted
    there so scheduler/daily_update.py can reuse the identical check
    without importing PyQt6 into the headless T3.2 build. Kept as a
    thin wrapper here rather than replaced at every call site, so
    existing callers/imports in this module don't need to change."""
    return _process_status.is_mcp_running()


class PanelMcp(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._build_ui()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 10)
        outer.setSpacing(0)

        heading = QLabel("MCP Server")
        heading.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {self._app.TEXT};")
        outer.addWidget(heading)
        outer.addSpacing(10)

        header = QLabel("MCP SERVER")
        header.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {self._app.ACCENT};")
        outer.addWidget(header)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        sep.setFixedHeight(1)
        outer.addWidget(sep)
        outer.addSpacing(10)

        # ── LLM backend dropdown ─────────────────────────────────────────────
        backend_row = QHBoxLayout()
        backend_row.setSpacing(8)
        backend_lbl = QLabel("LLM backend")
        backend_lbl.setFixedWidth(120)
        backend_lbl.setFont(QFont("Segoe UI", 9))
        backend_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_backend = QComboBox()
        self._mcp_backend.addItems(["ollama", "cloud"])
        self._mcp_backend.setFixedWidth(140)
        self._mcp_backend.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._mcp_backend.currentTextChanged.connect(self._mcp_on_backend_changed)
        backend_row.addWidget(backend_lbl)
        backend_row.addWidget(self._mcp_backend)
        # ▼ fallback label — Qt6/Windows suppresses the native drop-down
        # arrow once a QComboBox has a stylesheet. Same fix already
        # applied to app/panel_chat.py's three dropdowns (Baustein 11) —
        # this exact combo was the other known instance of the bug,
        # flagged in NOTES_v1.7.2_chat_panel_konzept.md but left open
        # until now.
        _backend_arrow = QLabel("▼")
        _backend_arrow.setFont(QFont("Segoe UI", 7))
        _backend_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        _backend_arrow.setFixedWidth(16)
        backend_row.addWidget(_backend_arrow)
        backend_row.addStretch()
        outer.addLayout(backend_row)
        outer.addSpacing(10)


        # ── Port row (v1.7.0.1 — streamable-http transport) ──────────────────
        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        port_lbl = QLabel("Port")
        port_lbl.setFixedWidth(120)
        port_lbl.setFont(QFont("Segoe UI", 9))
        port_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_port = QLineEdit()
        self._mcp_port.setFixedWidth(80)
        self._mcp_port.setFont(QFont("Segoe UI", 9))
        self._mcp_port.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px;")
        port_row.addWidget(port_lbl)
        port_row.addWidget(self._mcp_port)
        port_row.addStretch()
        outer.addLayout(port_row)
        outer.addSpacing(10)

        # ── Headless row (v1.7.0.1) ───────────────────────────────────────────
        self._mcp_headless = QCheckBox("Start headless (no window)")
        self._mcp_headless.setFont(QFont("Segoe UI", 9))
        self._mcp_headless.setStyleSheet(f"color: {self._app.TEXT2};")
        outer.addWidget(self._mcp_headless)
        outer.addSpacing(10)

        # ── Extra allowed hosts (v1.7.0.2 — MCP transport_security) ──────────
        # Checkbox gates the field (dimmed/locked, content preserved when
        # off — session decision) instead of an empty string meaning
        # "disabled", so a saved-but-inactive value survives a toggle.
        self._mcp_extra_hosts_enabled = QCheckBox("Extra allowed hosts")
        self._mcp_extra_hosts_enabled.setFont(QFont("Segoe UI", 9))
        self._mcp_extra_hosts_enabled.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_extra_hosts_enabled.toggled.connect(self._mcp_on_extra_hosts_toggled)
        outer.addWidget(self._mcp_extra_hosts_enabled)

        extra_hosts_row = QHBoxLayout()
        extra_hosts_row.setSpacing(8)
        extra_hosts_lbl = QLabel("Hosts")
        extra_hosts_lbl.setFixedWidth(120)
        extra_hosts_lbl.setFont(QFont("Segoe UI", 9))
        extra_hosts_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_extra_hosts_field = QLineEdit()
        self._mcp_extra_hosts_field.setPlaceholderText(
            "comma-separated, e.g. host.docker.internal, otherhost")
        self._mcp_extra_hosts_field.setMinimumWidth(200)
        self._mcp_extra_hosts_field.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._mcp_extra_hosts_field.setFont(QFont("Segoe UI", 9))
        self._mcp_extra_hosts_field.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px;")
        self._mcp_extra_hosts_field.textChanged.connect(
            self._mcp_refresh_extra_hosts_preview)
        extra_hosts_row.addWidget(extra_hosts_lbl)
        extra_hosts_row.addWidget(self._mcp_extra_hosts_field)
        outer.addLayout(extra_hosts_row)

        self._mcp_extra_hosts_preview = QLabel("")
        self._mcp_extra_hosts_preview.setFont(QFont("Segoe UI", 8))
        self._mcp_extra_hosts_preview.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_extra_hosts_preview.setWordWrap(True)
        outer.addWidget(self._mcp_extra_hosts_preview)
        # Initial state: checkbox starts unchecked (default), so the field
        # must be disabled and the preview set to its "disabled" message
        # right away — otherwise QLineEdit's own default (enabled=True)
        # wins until load_mcp_settings() runs once.
        self._mcp_extra_hosts_field.setEnabled(self._mcp_extra_hosts_enabled.isChecked())
        self._mcp_refresh_extra_hosts_preview()
        outer.addSpacing(10)

        # ── Cloud credentials block (visible when backend == "cloud") ────────
        self._mcp_cloud_box = QFrame()
        self._mcp_cloud_box.setStyleSheet(f"background: {self._app.BG2};")
        cloud_lay = QVBoxLayout(self._mcp_cloud_box)
        cloud_lay.setContentsMargins(10, 10, 10, 10)
        cloud_lay.setSpacing(8)

        # Baustein 23 (garmin_collector-3_experiment): the API key itself
        # no longer goes into MCP_LLM_CONFIG_FILE at all — it is stored in
        # Windows Credential Manager instead, one entry per provider (see
        # clients/cloud_credential_store.py), same mechanism
        # garmin/garmin_security.py already uses for the Garmin token
        # encryption key. Only provider/model stay in the JSON file below.
        info = QLabel(
            "🔒  API key stored in Windows Credential Manager, one entry "
            "per provider — never written to disk in plaintext.")
        info.setFont(QFont("Segoe UI", 8))
        info.setStyleSheet(f"color: {self._app.TEXT2};")
        info.setWordWrap(True)
        cloud_lay.addWidget(info)

        def _cloud_field(label: str, password: bool = False) -> QLineEdit:
            # Korrektur: setFixedWidth() on both label and entry left no
            # room to shrink at narrow window widths — this tab has no
            # QScrollArea wrapper (unlike PanelSettings), so the row had
            # nowhere to go but overlap the row below it. Label keeps a
            # fixed width (short text, must stay legible), the entry gets
            # QSizePolicy.Expanding instead so it shrinks/grows with the
            # available width; row.addStretch() removed since the entry
            # itself now fills the remaining space.
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            entry = QLineEdit()
            entry.setMinimumWidth(120)
            entry.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            entry.setFont(QFont("Segoe UI", 9))
            entry.setStyleSheet(
                f"background: {self._app.BG3}; color: {self._app.TEXT}; "
                f"border: none; padding: 4px;")
            if password:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            row.addWidget(lbl)
            row.addWidget(entry)
            cloud_lay.addLayout(row)
            return entry

        # Dropdown, not free text (garmin_collector-3_experiment session
        # decision — closes the silent-typo failure mode a plain
        # QLineEdit allowed; see NOTES_v1.7.2_chat_panel_konzept.md's
        # own "Provider-Feld sollte von Freitext auf Dropdown umgestellt
        # werden" note). Options loaded from clients/cloud_llm_client.py's
        # _PROVIDERS — the same dispatcher registry app/panel_chat.py's
        # cloud branch actually consults, not a separately hand-kept
        # list here, so a future third provider cannot drift out of
        # sync between the two. Row built inline, not via _cloud_field()
        # above (that helper is QLineEdit-specific).
        provider_row = QHBoxLayout()
        provider_row.setSpacing(8)
        provider_lbl = QLabel("Provider")
        provider_lbl.setFixedWidth(100)
        provider_lbl.setFont(QFont("Segoe UI", 9))
        provider_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_cloud_provider = QComboBox()
        self._mcp_cloud_provider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._mcp_cloud_provider.setFont(QFont("Segoe UI", 9))
        self._mcp_cloud_provider.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._mcp_cloud_provider.addItems(
            sorted(_load_cloud_llm_client()._PROVIDERS.keys()))
        # Baustein 23 — switching providers refreshes the key-status label
        # for whichever one is now selected (WCM holds one entry per
        # provider, see clients/cloud_credential_store.py's own docstring:
        # "schnell und einfach wechseln" was the whole point of that
        # design). Also fires from _mcp_set_cloud_provider()'s own
        # setCurrentIndex() call below whenever that actually changes the
        # selection — harmless if this label refresh then runs twice for
        # the same value.
        self._mcp_cloud_provider.currentTextChanged.connect(
            self._mcp_refresh_cloud_key_status_label)
        provider_row.addWidget(provider_lbl)
        provider_row.addWidget(self._mcp_cloud_provider)
        # ▼ fallback label — same Qt6/Windows stylesheet-suppresses-the-
        # native-arrow reason as the LLM-backend dropdown above.
        _provider_arrow = QLabel("▼")
        _provider_arrow.setFont(QFont("Segoe UI", 7))
        _provider_arrow.setStyleSheet(
            f"color: {self._app.TEXT2}; background: {self._app.BG3}; "
            f"padding: 0px 6px 0px 0px;")
        _provider_arrow.setFixedWidth(16)
        provider_row.addWidget(_provider_arrow)
        cloud_lay.addLayout(provider_row)

        self._mcp_cloud_key = _cloud_field("API key", password=True)
        self._mcp_cloud_key.setPlaceholderText("leave empty to keep current key")
        self._mcp_cloud_model = _cloud_field("Model")
        self._mcp_cloud_model.setPlaceholderText("e.g. claude-sonnet-4-6")

        self._mcp_cloud_key_status = QLabel("")
        self._mcp_cloud_key_status.setFont(QFont("Segoe UI", 8))
        self._mcp_cloud_key_status.setStyleSheet(f"color: {self._app.TEXT2};")
        cloud_lay.addWidget(self._mcp_cloud_key_status)

        cloud_save_row = QHBoxLayout()
        self._mcp_cloud_save_btn = QPushButton("Save Cloud Credentials")
        self._mcp_cloud_save_btn.setFont(QFont("Segoe UI", 9))
        self._mcp_cloud_save_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 6px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        self._mcp_cloud_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mcp_cloud_save_btn.clicked.connect(self._mcp_save_cloud_config)
        cloud_save_row.addWidget(self._mcp_cloud_save_btn)
        cloud_save_row.addStretch()
        cloud_lay.addLayout(cloud_save_row)

        outer.addWidget(self._mcp_cloud_box)
        outer.addSpacing(14)


        # ── Save & Start ─────────────────────────────────────────────────────
        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT2}; color: {self._app.TEXT}; "
            f"border: none; padding: 8px 18px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT}; }}")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_btn.clicked.connect(self._mcp_save)
        save_row.addWidget(save_btn)

        start_btn = QPushButton("▶️  Start MCP Server")
        start_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        start_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 8px 18px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        start_btn.clicked.connect(self._mcp_start_server)
        save_row.addWidget(start_btn)

        # Stop — NOTES_v1.7.2_chat_panel_konzept.md explicitly calls for
        # this panel to get one too ("MCP-Tab braucht ebenfalls einen
        # Stop-Button"), symmetric to the Chat panel's own Start/Stop
        # pair (garmin_collector-3_experiment, Baustein 8b). Pure
        # addition — _mcp_start_server()/_resolve_mcp_server_launch_
        # command() above are untouched.
        stop_btn = QPushButton("⏹️  Stop MCP Server")
        stop_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        stop_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 8px 18px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}")
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        stop_btn.clicked.connect(self._mcp_stop_server)
        save_row.addWidget(stop_btn)

        save_row.addStretch()
        outer.addLayout(save_row)

        # v1.7.1 — first-start hint. The SQLite proxy syncs synchronously
        # before the server becomes reachable (clients/mcp_update.py::
        # sync_all(), called from clients/mcp_server.py's
        # _run_startup_sync()) — on the very first start, or after a long
        # idle period with a large pending delta, this can take a while.
        # Static text rather than conditional on archive size — this
        # panel has no cheap way to know the pending delta size before
        # the server process itself computes it.
        first_start_hint = QLabel(
            "First start (or a long gap since the last one) may take a "
            "while — the server builds/updates its local SQLite cache before "
            "it starts answering.")
        first_start_hint.setFont(QFont("Segoe UI", 8))
        first_start_hint.setStyleSheet(f"color: {self._app.TEXT};")
        first_start_hint.setWordWrap(True)
        outer.addWidget(first_start_hint)

        outer.addStretch()

    # ── Settings passthrough ─────────────────────────────────────────────────

    def get_mcp_settings(self) -> dict:
        """Returns current MCP field values. Called by _collect_settings."""
        return {
            "mcp_llm_backend": self._mcp_backend.currentText(),
            "mcp_http_port":   self._mcp_port.text().strip(),
            "mcp_headless":    self._mcp_headless.isChecked(),
            "mcp_extra_hosts_enabled": self._mcp_extra_hosts_enabled.isChecked(),
            "mcp_extra_hosts":         self._mcp_extra_hosts_field.text().strip(),
        }

    def load_mcp_settings(self, s: dict):
        """Populates MCP fields from settings dict. Called by GarminApp
        after construction."""
        idx = self._mcp_backend.findText(s.get("mcp_llm_backend", "ollama"))
        self._mcp_backend.setCurrentIndex(max(0, idx))
        self._mcp_port.setText(str(s.get("mcp_http_port") or cfg.MCP_HTTP_PORT))
        self._mcp_headless.setChecked(bool(s.get("mcp_headless", False)))
        self._mcp_extra_hosts_enabled.setChecked(bool(s.get("mcp_extra_hosts_enabled", False)))
        self._mcp_extra_hosts_field.setText(
            str(s.get("mcp_extra_hosts") or cfg.MCP_EXTRA_ALLOWED_HOSTS_RAW))
        self._mcp_on_extra_hosts_toggled(self._mcp_extra_hosts_enabled.isChecked())
        self._mcp_on_backend_changed()
        self._mcp_refresh_cloud_key_status()

    # ── Backend switch ───────────────────────────────────────────────────────

    def _mcp_on_backend_changed(self):
        """Shows only the field group matching the selected backend.

        Korrektur: setVisible(False) alone left stale layout geometry
        behind in this QVBoxLayout nesting — the hidden box's previous
        height stayed reserved, so the visible box below it rendered
        overlapping instead of shifting up. adjustSize() + the parent
        layout's activate() force an immediate re-layout instead of
        waiting for the next paint/resize event to pick it up.
        """
        is_cloud = self._mcp_backend.currentText() == "cloud"
        self._mcp_cloud_box.setVisible(is_cloud)
        self._mcp_cloud_box.adjustSize()
        self.layout().activate()
        self.adjustSize()

    # ── Extra allowed hosts (v1.7.0.2) ───────────────────────────────────────

    def _mcp_on_extra_hosts_toggled(self, checked: bool):
        """Dims/locks the extra-hosts field when the checkbox is off —
        content is preserved, not cleared (session decision, so a saved
        value survives a toggle)."""
        self._mcp_extra_hosts_field.setEnabled(checked)
        self._mcp_refresh_extra_hosts_preview()

    def _mcp_refresh_extra_hosts_preview(self):
        """Live preview of the parsed host list — uses the same
        garmin_config._parse_extra_hosts() helper clients/mcp_server.py
        applies at startup, so this always shows exactly what would be
        used, never a diverging guess."""
        if not self._mcp_extra_hosts_enabled.isChecked():
            self._mcp_extra_hosts_preview.setText(
                "Disabled — default hosts remain unchanged.")
            return
        parsed = cfg._parse_extra_hosts(self._mcp_extra_hosts_field.text())
        if not parsed:
            self._mcp_extra_hosts_preview.setText("Recognized: — (no valid entries)")
        else:
            self._mcp_extra_hosts_preview.setText("Recognized: " + ", ".join(parsed))

    # ── Cloud config file (garmin_config.MCP_LLM_CONFIG_FILE) ───────────────

    def _mcp_set_cloud_provider(self, provider: str):
        """Selects provider in the dropdown, inserting it as an extra
        item first if it is not one of clients/cloud_llm_client.py's
        known providers (a value saved before this dropdown existed —
        this panel used a free-text field until garmin_collector-3_
        experiment — or a typo from that old field) — so a previously-
        saved value is never silently lost/blanked on load. Empty
        string (no config on disk yet) clears the selection rather
        than falling back to whatever item happens to be first."""
        if not provider:
            self._mcp_cloud_provider.setCurrentIndex(-1)
            return
        idx = self._mcp_cloud_provider.findText(provider)
        if idx < 0:
            self._mcp_cloud_provider.addItem(provider)
            idx = self._mcp_cloud_provider.findText(provider)
        self._mcp_cloud_provider.setCurrentIndex(idx)

    def _mcp_refresh_cloud_key_status(self):
        """Loads provider/model from garmin_config.MCP_LLM_CONFIG_FILE
        (Baustein 23: the API key itself no longer lives in this file —
        see _mcp_save_cloud_config() below) and refreshes the key-status
        label for whichever provider ends up selected."""
        import garmin_config as cfg
        try:
            data = __import__("json").loads(
                cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._mcp_set_cloud_provider("")
            self._mcp_cloud_model.setText("")
            self._mcp_cloud_key_status.setText("No cloud config file on disk.")
            return
        self._mcp_set_cloud_provider(str(data.get("provider", "")))
        self._mcp_cloud_model.setText(str(data.get("model", "")))
        self._mcp_refresh_cloud_key_status_label()

    def _mcp_refresh_cloud_key_status_label(self):
        """Shows whether the CURRENTLY SELECTED provider (dropdown, not
        necessarily the one last saved to MCP_LLM_CONFIG_FILE) has an API
        key stored in Windows Credential Manager (Baustein 23, one WCM
        entry per provider) — without reading or displaying the key
        itself. Re-run on every provider-dropdown change, not only on
        load — see the currentTextChanged connection above, and
        clients/cloud_credential_store.py's own docstring for why a
        per-provider entry was chosen ("schnell und einfach wechseln")."""
        provider = self._mcp_cloud_provider.currentText().strip()
        if not provider:
            self._mcp_cloud_key_status.setText("")
            return
        store = _load_cloud_credential_store()
        has_key = bool(store.get_api_key(provider))
        self._mcp_cloud_key_status.setText(
            f"API key stored for {provider} in Windows Credential Manager "
            "— leave the field empty to keep it."
            if has_key else f"No API key stored for {provider}.")

    def _mcp_save_cloud_config(self):
        """Writes provider/model to garmin_config.MCP_LLM_CONFIG_FILE
        (this panel is the first and only writer of that file) and the
        API key to Windows Credential Manager (Baustein 23,
        clients/cloud_credential_store.py — one entry per provider, never
        written into the JSON file at all anymore, see that module's own
        docstring for why)."""
        import json
        import garmin_config as cfg

        provider = self._mcp_cloud_provider.currentText().strip()
        model    = self._mcp_cloud_model.text().strip()
        new_key  = self._mcp_cloud_key.text().strip()

        store = _load_cloud_credential_store()
        existing_key = store.get_api_key(provider) if provider else None
        api_key = new_key if new_key else (existing_key or "")

        if not provider or not api_key or not model:
            QMessageBox.warning(
                self, "MCP Cloud Config",
                "Provider, API key and Model are all required — "
                "leave API key empty only if a key is already saved.")
            return

        if new_key and not store.store_api_key(provider, new_key):
            QMessageBox.critical(
                self, "MCP Cloud Config",
                "Could not save the API key to Windows Credential Manager.")
            return

        data = {"provider": provider, "model": model}
        try:
            cfg.MCP_LLM_CONFIG_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self, "MCP Cloud Config", f"Could not save config:\n{exc}")
            return

        self._mcp_cloud_key.clear()
        self._mcp_refresh_cloud_key_status_label()
        self._app._log("✓ MCP cloud config saved.")

    # ── Save ──────────────────────────────────────────────────────────────────

    def _mcp_save(self):
        s = self._app._collect_settings()
        self._app.settings = s
        self._app._safe_save(s)
        self._mcp_save_server_config(s)
        self._app._log("✓ MCP settings saved.")

    def _mcp_save_server_config(self, s: dict):
        """Mirrors mcp_enabled/mcp_llm_backend/base_dir into
        garmin_config.MCP_SERVER_CONFIG_FILE — lets clients/mcp_server.py
        and clients/mcp_server_gui.py resolve these without GLA present
        (v1.7 Teilbauauftrag f). No merge logic needed (unlike
        _mcp_save_cloud_config()'s API-key handling) — all three values
        are always present in s. A write failure is logged only, not
        shown as a blocking dialog: SETTINGS_FILE above is already saved
        successfully at this point, and this mirror step is a convenience
        for the standalone case, not a required part of the GLA save."""
        import json
        import garmin_config as cfg

        data = {
            "mcp_llm_backend": s.get("mcp_llm_backend", "ollama"),
            "base_dir":        s.get("base_dir", ""),
            "mcp_http_port":   s.get("mcp_http_port", ""),
            "mcp_headless":    s.get("mcp_headless", False),
            "mcp_extra_hosts_enabled": s.get("mcp_extra_hosts_enabled", False),
            "mcp_extra_hosts":         s.get("mcp_extra_hosts", ""),
        }
        try:
            cfg.MCP_SERVER_CONFIG_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            self._app._log(f"⚠ MCP server config mirror failed: {exc}")

    # ── Start (v1.7 Teilbauauftrag g) ────────────────────────────────────────

    def _mcp_start_server(self):
        """Click handler for the "Start MCP Server" button. Deliberately
        separate from _mcp_save() (session decision — see
        NOTES_v1.7_teilg.md): settings persistence and process launch
        are independent concerns with different failure modes, coupling
        them would risk an unwanted process spawn on every routine
        settings save. Fire-and-forget — no health check after Popen,
        matches the already-established "start it yourself, e.g. from a
        terminal" spirit of this panel, just automated."""
        if _mcp_server_is_running():
            QMessageBox.warning(
                self, "MCP Server",
                f"MCP server already appears to be running on port "
                f"{cfg.MCP_HTTP_PORT}.\n\n"
                "Close that instance first if you want to start a new one.")
            return

        cmd = _resolve_mcp_server_launch_command()
        if cmd is None:
            self._app._log("✗ MCP server launch failed: no valid launch target found.")
            QMessageBox.warning(
                self, "MCP Server",
                "Could not find clients/mcp_server.py, mcp_server.exe, or "
                "Starte_MCP_Server.bat — check the installation.")
            return

        try:
            subprocess.Popen(cmd)
        except OSError as exc:
            self._app._log(f"✗ MCP server launch failed: {exc}")
            QMessageBox.warning(
                self, "MCP Server", f"Could not start the MCP server:\n{exc}")
            return

        self._app._log(f"✓ MCP server starting ({' '.join(cmd)}).")
        self._app._log(
            "  First start (or a long gap since the last one) may take "
            "a while — the server is building/updating its local cache "
            "before it starts answering.")

    # ── Stop (garmin_collector-3_experiment, Baustein 8b) ────────────────────

    def _mcp_stop_server(self):
        """Pragmatic, not ownership-based (see clients/mcp_process.py's
        own module docstring, and NOTES_v1.7.2_chat_panel_konzept.md's
        Stop reasoning): stops the server regardless of who started it
        or from which panel — including a Chat-tab session with
        datasource "mcp" set. That session's own next tool call (or its
        own Stop button) surfaces the resulting unreachable-server error
        exactly as it already does for an externally-killed server today
        — no special cross-panel notification needed here."""
        mcp_process = _load_mcp_process()
        ok, message = mcp_process.stop()
        self._app._log(f"✓ {message}" if ok else f"✗ {message}")
