#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
app/panel_mcp.py
Garmin Local Archive — MCP Server Panel

PanelMcp — PyQt6 QWidget, eigenständiger Tab "MCP Server" in
garmin_app_base.py's QTabWidget (v1.7 Teilbauauftrag d).

Layout injected by garmin_app_base._build_ui():
  - self._panel_mcp added as Tab 4 "MCP Server"

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - Panel-private helpers use _mcp_* prefix (E-7)
  - get_mcp_settings() / load_mcp_settings(s) — settings passthrough pair,
    analogous to PanelTimer.get_timer_settings() / load_timer_settings(s).
    Called by GarminApp._collect_settings() / GarminApp.__init__().

Scope note (v1.7 Teilbauauftrag d, superseded in part by Teilbauauftrag
g): this panel was originally settings-persistence-only, never
starting/stopping clients/mcp_server.py itself (Teil b/c architecture
decision). Teil (g) added a "Start MCP Server" button that does launch
the process directly — the settings/dropdown fields below still only
control what gets written to SETTINGS_FILE, but process control is no
longer out of scope for this panel. The former "Enable MCP server"
checkbox and its GARMIN_MCP_ENABLED flag were removed in Teil (g) — the
flag stopped being read by main() back in Teil (f), and the new Start
button made the whole on/off concept moot. See NOTES_v1.7_teild.md for
the original reasoning and NOTES_v1.7_teilg.md for the removal.

Server config mirror (v1.7 Teilbauauftrag f): _mcp_save() additionally
writes garmin_config.MCP_SERVER_CONFIG_FILE (~/.garmin_mcp_server_config.json)
with the same three values (mcp_enabled, mcp_llm_backend, base_dir) — a
mirror, not a new source of truth. Lets a standalone mcp_server.exe (no
GLA installation, no ENV set) discover the archive path and MCP settings
this GUI session last saved. Still no os.environ write — this remains a
pure file-persistence step, same as the SETTINGS_FILE write beside it.
A write failure here is logged, not shown as a blocking dialog — see
_mcp_save() below.

Cloud LLM config file: this panel is the first and only writer of
garmin_config.MCP_LLM_CONFIG_FILE (~/.garmin_mcp_llm_config.json,
Teil c). Same three required fields mcp_server.py's
_cloud_llm_config_available() checks (provider, api_key, model) — see
clients/mcp_server.py for the read side. The API key field never
reloads a previously saved key into the widget (QLineEdit.Password
echo mode plus deliberately not pre-filled) — avoids holding the
plaintext key in UI widget state longer than a save action requires.
A status label shows whether a key is currently on disk without
displaying it.
"""

import socket
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QFrame, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_config as cfg


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
    """TCP-connect probe against 127.0.0.1:MCP_HTTP_PORT (v1.7.0.1) —
    replaces the PID-lockfile + `tasklist` check this button used under
    the stdio transport. The server now listens on a real socket, so a
    successful connect is a direct, unambiguous liveness signal — no
    stale-file interpretation needed (the old code's "no lock file" and
    "lock file present but stale" cases collapse into one: connect
    fails, socket closed cleanly either way). Short timeout — this only
    needs to catch "already running", not tolerate a slow remote host
    (there is none, host is always 127.0.0.1)."""
    try:
        with socket.create_connection(("127.0.0.1", cfg.MCP_HTTP_PORT), timeout=0.3):
            return True
    except OSError:
        return False


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
        self._mcp_headless = QCheckBox("Headless starten (ohne Fenster)")
        self._mcp_headless.setFont(QFont("Segoe UI", 9))
        self._mcp_headless.setStyleSheet(f"color: {self._app.TEXT2};")
        outer.addWidget(self._mcp_headless)
        outer.addSpacing(10)

        # ── Cloud credentials block (visible when backend == "cloud") ────────
        self._mcp_cloud_box = QFrame()
        self._mcp_cloud_box.setStyleSheet(f"background: {self._app.BG2};")
        cloud_lay = QVBoxLayout(self._mcp_cloud_box)
        cloud_lay.setContentsMargins(10, 10, 10, 10)
        cloud_lay.setSpacing(8)

        warn = QLabel(
            "⚠  Saved as plaintext to ~/.garmin_mcp_llm_config.json — not "
            "encrypted. WCM/AES encryption is a later roadmap item.")
        warn.setFont(QFont("Segoe UI", 8))
        warn.setStyleSheet(f"color: {self._app.YELLOW};")
        warn.setWordWrap(True)
        cloud_lay.addWidget(warn)

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

        self._mcp_cloud_provider = _cloud_field("Provider")
        self._mcp_cloud_provider.setPlaceholderText("e.g. anthropic, openai")
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

        save_row.addStretch()
        outer.addLayout(save_row)

        outer.addStretch()

    # ── Settings passthrough ─────────────────────────────────────────────────

    def get_mcp_settings(self) -> dict:
        """Returns current MCP field values. Called by _collect_settings."""
        return {
            "mcp_llm_backend": self._mcp_backend.currentText(),
            "mcp_http_port":   self._mcp_port.text().strip(),
            "mcp_headless":    self._mcp_headless.isChecked(),
        }

    def load_mcp_settings(self, s: dict):
        """Populates MCP fields from settings dict. Called by GarminApp
        after construction."""
        idx = self._mcp_backend.findText(s.get("mcp_llm_backend", "ollama"))
        self._mcp_backend.setCurrentIndex(max(0, idx))
        self._mcp_port.setText(str(s.get("mcp_http_port") or cfg.MCP_HTTP_PORT))
        self._mcp_headless.setChecked(bool(s.get("mcp_headless", False)))
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

    # ── Cloud config file (garmin_config.MCP_LLM_CONFIG_FILE) ───────────────

    def _mcp_refresh_cloud_key_status(self):
        """Shows whether a key is currently on disk, without reading or
        displaying it — see module docstring."""
        import garmin_config as cfg
        try:
            data = __import__("json").loads(
                cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._mcp_cloud_provider.setText("")
            self._mcp_cloud_model.setText("")
            self._mcp_cloud_key_status.setText("No cloud config file on disk.")
            return
        self._mcp_cloud_provider.setText(str(data.get("provider", "")))
        self._mcp_cloud_model.setText(str(data.get("model", "")))
        has_key = bool(data.get("api_key"))
        self._mcp_cloud_key_status.setText(
            "API key is set on disk — leave the field empty to keep it."
            if has_key else "No API key set.")

    def _mcp_save_cloud_config(self):
        """Writes garmin_config.MCP_LLM_CONFIG_FILE. This panel is the
        first and only writer of this file — same three required fields
        clients/mcp_server.py::_cloud_llm_config_available() checks."""
        import json
        import garmin_config as cfg

        provider = self._mcp_cloud_provider.text().strip()
        model    = self._mcp_cloud_model.text().strip()
        new_key  = self._mcp_cloud_key.text().strip()

        existing_key = ""
        try:
            existing = json.loads(
                cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
            existing_key = existing.get("api_key", "")
        except (FileNotFoundError, ValueError):
            pass

        api_key = new_key if new_key else existing_key

        if not provider or not api_key or not model:
            QMessageBox.warning(
                self, "MCP Cloud Config",
                "Provider, API key and Model are all required — "
                "leave API key empty only if a key is already saved.")
            return

        data = {"provider": provider, "api_key": api_key, "model": model}
        try:
            cfg.MCP_LLM_CONFIG_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self, "MCP Cloud Config", f"Could not save config:\n{exc}")
            return

        self._mcp_cloud_key.clear()
        self._mcp_refresh_cloud_key_status()
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
