#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
  - Non-streaming requests only ("stream": false) — see ollama_client.py
  - No active chat prep (model list, system prompt load) before the user
    clicks "Start" — only age display + a lightweight reachability ping run
    automatically on tab-open (KONZEPT §5)
  - Model switch mid-chat resets history (KONZEPT §4) — deliberate, not a
    bug: different models have different context limits/styles
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextBrowser, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

import frozen_paths


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


class PanelChat(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._history = []          # [{"role": ..., "content": ...}, ...]
        self._system_prompt = None  # loaded once, on Start
        self._request_running = False
        self._elapsed_seconds = 0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._chat_tick_elapsed)
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

        start_row = QHBoxLayout()
        self._start_btn = QPushButton("Start")
        self._start_btn.setFont(QFont("Segoe UI", 9))
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.ACCENT}; color: white; "
            f"border: none; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ background: {self._app.BG3}; color: {self._app.TEXT2}; }}")
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self._chat_on_start)
        start_row.addWidget(self._start_btn)
        start_row.addStretch()
        status_lay.addLayout(start_row)

        outer.addWidget(status_box)

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

        # ── Chat history ─────────────────────────────────────────────────────
        self._chat_view = QTextBrowser()
        self._chat_view.setStyleSheet(
            f"background: {self._app.BG2}; color: {self._app.TEXT}; border: none;")
        self._chat_view.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Expanding)
        outer.addWidget(self._chat_view, stretch=1)

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

    # ── Start ────────────────────────────────────────────────────────────────

    def _chat_on_start(self):
        self._start_btn.setEnabled(False)
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
            self._status_label.setText("")
            return
        if not models:
            self._chat_append_system(
                "No models installed — install one via `ollama pull <model>` "
                "and click Start again.")
            self._start_btn.setEnabled(True)
            self._status_label.setText("")
            return

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(models)
        self._model_combo.blockSignals(False)

        self._chat_load_system_prompt()

        self._model_combo.setEnabled(True)
        self._new_chat_btn.setEnabled(True)
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._start_btn.setEnabled(False)
        self._status_label.setText("")

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

        self._history = []
        if self._system_prompt:
            self._history.append({"role": "system", "content": self._system_prompt})

    # ── New Chat (context reset — mandatory, not optional, KONZEPT §4) ─────────

    def _chat_on_new_chat(self):
        self._history = []
        if self._system_prompt:
            self._history.append({"role": "system", "content": self._system_prompt})
        self._chat_view.clear()

    def _chat_on_model_changed(self, _index: int):
        # Different models have different context limits/styles — carrying
        # history across a model switch is a deliberate non-goal (KONZEPT §4).
        if self._model_combo.isEnabled():
            self._chat_on_new_chat()

    # ── Send ─────────────────────────────────────────────────────────────────

    def _chat_on_send(self):
        if self._request_running:
            return
        text = self._input.text().strip()
        if not text:
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

        def worker():
            client = _load_ollama_client()
            try:
                reply = client.chat(model, history)
                self._app._dispatch(lambda: self._chat_on_reply(reply))
            except client.OllamaError as e:
                self._app._dispatch(lambda err=e: self._chat_on_error(err))

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

    # ── Chat view helpers ────────────────────────────────────────────────────

    def _chat_append_line(self, speaker: str, text: str):
        safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace("\n", "<br>"))
        self._chat_view.append(f"<b>{speaker}:</b> {safe}")

    def _chat_append_system(self, text: str):
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._chat_view.append(
            f"<i style='color:{self._app.YELLOW};'>⚠ {safe}</i>")
