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

Ollama model list: reuses the same lazy-import helper pattern as
app/panel_chat.py (_load_ollama_client(), clients/ollama_client.py) — a
lightweight background-thread call to list_models(), populating a
QComboBox. Not started automatically on tab-open (unlike Chat's
reachability ping) — only on explicit "Refresh" click, since this tab has
no other reason to touch the network on open.

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

import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QFrame, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import frozen_paths
import garmin_config as cfg


def _load_ollama_client():
    """Lazy import — identical pattern to app/panel_chat.py's helper of
    the same name. Not imported at module top-level so panel_mcp.py stays
    importable before sys.path is fully wired up."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    import ollama_client
    return ollama_client


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


def _mcp_server_is_running() -> int | None:
    """Reads garmin_config.MCP_SERVER_LOCK_FILE and checks via `tasklist`
    whether that PID is still alive. Returns the PID if a live process
    holds it, None otherwise — covers both "no lock file" and "lock file
    present but stale" (the expected common case after a normal window
    close, see clients/mcp_server_gui.py's module docstring on the
    interpreter-shutdown crash that prevents reliable unlink()) as the
    same "not running" outcome. Stdlib-only (subprocess + tasklist
    parsing) — no psutil dependency, session decision (NOTES_v1.7_teilg.md)."""
    try:
        pid_text = cfg.MCP_SERVER_LOCK_FILE.read_text(encoding="utf-8").strip()
        pid = int(pid_text)
    except (FileNotFoundError, ValueError):
        return None

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Can't determine liveness — fail open (allow start) rather than
        # block the button on an unrelated tasklist failure.
        return None

    return pid if str(pid) in result.stdout else None


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

        # ── Ollama model row (visible when backend == "ollama") ──────────────
        self._mcp_ollama_box = QFrame()
        ollama_lay = QVBoxLayout(self._mcp_ollama_box)
        ollama_lay.setContentsMargins(0, 0, 0, 0)
        ollama_lay.setSpacing(6)

        ollama_row = QHBoxLayout()
        ollama_row.setSpacing(8)
        ollama_lbl = QLabel("Ollama model")
        ollama_lbl.setFixedWidth(120)
        ollama_lbl.setFont(QFont("Segoe UI", 9))
        ollama_lbl.setStyleSheet(f"color: {self._app.TEXT2};")
        self._mcp_ollama_model = QComboBox()
        self._mcp_ollama_model.setFixedWidth(200)
        self._mcp_ollama_model.setStyleSheet(
            f"QComboBox {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 10px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {self._app.BG3}; "
            f"color: {self._app.TEXT}; "
            f"selection-background-color: {self._app.ACCENT2}; }}")
        self._mcp_ollama_refresh_btn = QPushButton("🔄  Refresh")
        self._mcp_ollama_refresh_btn.setFont(QFont("Segoe UI", 9))
        self._mcp_ollama_refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT}; "
            f"border: none; padding: 5px 12px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; }}")
        self._mcp_ollama_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mcp_ollama_refresh_btn.clicked.connect(self._mcp_refresh_ollama_models)
        ollama_row.addWidget(ollama_lbl)
        ollama_row.addWidget(self._mcp_ollama_model)
        ollama_row.addWidget(self._mcp_ollama_refresh_btn)
        ollama_row.addStretch()
        ollama_lay.addLayout(ollama_row)

        self._mcp_ollama_status = QLabel("")
        self._mcp_ollama_status.setFont(QFont("Segoe UI", 8))
        self._mcp_ollama_status.setStyleSheet(f"color: {self._app.TEXT2};")
        ollama_lay.addWidget(self._mcp_ollama_status)

        outer.addWidget(self._mcp_ollama_box)
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
            "mcp_llm_backend":  self._mcp_backend.currentText(),
            "mcp_ollama_model": self._mcp_ollama_model.currentText(),
        }

    def load_mcp_settings(self, s: dict):
        """Populates MCP fields from settings dict. Called by GarminApp
        after construction.

        mcp_ollama_model (v1.7 Teilbauauftrag f): the combo box is empty
        until "Refresh" is clicked (no Ollama call happens automatically
        on tab-open — see module docstring), so the saved value is
        inserted as a single placeholder entry rather than requiring a
        live Ollama connection just to restore the last selection. A
        later Refresh click repopulates the list from live models and
        findText() re-selects the same string if it's still installed
        (see _mcp_on_ollama_models_loaded's existing current-selection
        preservation logic)."""
        idx = self._mcp_backend.findText(s.get("mcp_llm_backend", "ollama"))
        self._mcp_backend.setCurrentIndex(max(0, idx))
        saved_model = s.get("mcp_ollama_model", "")
        if saved_model:
            self._mcp_ollama_model.addItem(saved_model)
            self._mcp_ollama_model.setCurrentText(saved_model)
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
        is_ollama = self._mcp_backend.currentText() == "ollama"
        self._mcp_ollama_box.setVisible(is_ollama)
        self._mcp_cloud_box.setVisible(not is_ollama)
        self._mcp_ollama_box.adjustSize()
        self._mcp_cloud_box.adjustSize()
        self.layout().activate()
        self.adjustSize()

    # ── Ollama model list ────────────────────────────────────────────────────

    def _mcp_refresh_ollama_models(self):
        """Background-thread model fetch — mirrors panel_chat.py's worker
        pattern (D-5: workers never touch widgets directly)."""
        self._mcp_ollama_refresh_btn.setEnabled(False)
        self._mcp_ollama_status.setText("Loading models …")

        def worker():
            client = _load_ollama_client()
            try:
                models = client.list_models()
                error = None
            except client.OllamaError as e:
                models, error = [], str(e)
            self._app._dispatch(
                lambda: self._mcp_on_ollama_models_loaded(models, error))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _mcp_on_ollama_models_loaded(self, models: list, error: str):
        self._mcp_ollama_refresh_btn.setEnabled(True)
        if error:
            self._mcp_ollama_status.setText(f"Ollama not reachable: {error}")
            return
        if not models:
            self._mcp_ollama_status.setText(
                "No models installed — `ollama pull <model>` and refresh.")
            return

        current = self._mcp_ollama_model.currentText()
        self._mcp_ollama_model.blockSignals(True)
        self._mcp_ollama_model.clear()
        self._mcp_ollama_model.addItems(models)
        idx = self._mcp_ollama_model.findText(current)
        self._mcp_ollama_model.setCurrentIndex(max(0, idx))
        self._mcp_ollama_model.blockSignals(False)
        self._mcp_ollama_status.setText(f"{len(models)} model(s) found.")

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
            "mcp_llm_backend":  s.get("mcp_llm_backend", "ollama"),
            "base_dir":         s.get("base_dir", ""),
            "mcp_ollama_model": s.get("mcp_ollama_model", ""),
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
        running_pid = _mcp_server_is_running()
        if running_pid is not None:
            QMessageBox.warning(
                self, "MCP Server",
                f"MCP server already appears to be running (PID {running_pid}).\n\n"
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
