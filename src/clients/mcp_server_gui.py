#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
clients/mcp_server_gui.py
Garmin Local Archive — MCP Server Standalone Window (v1.7 Teilbauauftrag f)

The window IS the server — starting mcp_server.exe means the server
runs, no separate on/off state, no --configure flag, no headless mode.
Session decision (Timo): "das Fenster ist der Server — wie das intern am
besten läuft, überlasse ich dir." No Enabled checkbox exists in this
window for that same reason — it would have had no function.

Tkinter, not PyQt6 — deliberate (session decision): PyQt6 in GLA proper
is tied to the WebEngine dashboard view, which this window has no need
for. tkinter.filedialog/messagebox/ttk/scrolledtext are already in
HIDDEN_IMPORTS_COMMON (compiler/build_manifest.py), so this adds no new
bundling weight for T3.3.

Threading model: Tkinter's mainloop() is main-thread-bound on Windows —
this is the fixed point, not a choice. mcp.run(transport="stdio")
therefore runs in a daemon thread instead (threading.Thread(...,
daemon=True)) — no cancel API exists on mcp.run() to stop it cleanly
from outside, and none is needed: the process interpreter kills the
daemon thread automatically on exit, and a stdio responder holds no
transactional state to lose mid-request (see Session analysis, Eckpunkt
4). A single informational log line is written just before the window
closes — cosmetic only, not a blocking shutdown handshake.

Log architecture (Eckpunkt 7): two file logs, sequential, never both
active — boot_handler (already attached by mcp_server.py::main() before
this module is even imported) covers everything up to this window
opening; the moment the operational log (inside the archive, rotating,
mirrors scheduler/daily_update.py::_start_daily_log()'s pattern) is
successfully attached, boot_handler is removed from the root logger.
No permanent duplication. A third destination, the Tkinter log widget,
runs continuously via a queue-based logging.Handler (this module's own
implementation — no existing Tkinter precedent in the project;
garmin_app_standalone.py's _QueueWriter/_QueueHandler/_poll_log_queue
trio is the architectural model, ported from PyQt6's QTimer.singleShot
to Tkinter's root.after()). File handlers always stay at DEBUG
regardless of the widget toggle below — only the widget's effective
verbosity changes.

Log level toggle: mirrors app/panel_settings.py's "📋 Log: Simple" /
"📋 Log: Detailed" button, same wording, same meaning (INFO vs DEBUG).
Unlike that panel's version there is no "takes effect on next sync"
caveat — this process has no comparable in-flight-operation concept,
the toggle sets logging.getLogger().setLevel(...) immediately.

Lock file reliability (v1.7 Teilbauauftrag g, real test finding
2026-08-24): a normal window close reliably triggers a
"Fatal Python error: _enter_buffered_busy" during interpreter shutdown
— the mcp.run(transport="stdio") daemon thread's blocking stdin read
cannot be cleanly interrupted (no cancel API, see above). This happens
after _on_close()'s log line but appears to prevent the lock-file
unlink() from reliably completing before the crash — the stale lock
file is the expected normal outcome after closing this window, not an
edge case limited to hard kills. app/panel_mcp.py's liveness check must
treat a present-but-stale lock file as the common case. No fix attempted
here — not a quick change (would need os._exit() or explicit stdin/
stdout closure ahead of the thread join), deferred, see
NOTES_v1.7_teilg.md.

Persistence — two separate files, mirroring app/panel_mcp.py's split:
  - garmin_config.MCP_SERVER_CONFIG_FILE (mcp_llm_backend, base_dir,
    mcp_ollama_model) — this window is a second, independent writer
    alongside panel_mcp.py's mirror-on-save (documented as a deliberate
    Sole-Write-Authority exception in garmin_config.py's docstring: the
    two writers serve mutually exclusive operating modes and never run
    against the file at the same time in practice). base_dir here is a
    real, user-editable field (no GLA instance to mirror from), unlike
    panel_mcp.py's read-only mirror value. A fourth field, mcp_enabled,
    existed here through Teil (f) but was removed in Teil (g) — the
    "Enable MCP server" checkbox it backed had no functional effect
    once main() stopped gating on it, and the "Start MCP Server" button
    made the whole on/off concept moot.
  - garmin_config.MCP_LLM_CONFIG_FILE (provider, api_key, model) — cloud
    LLM credentials, same file panel_mcp.py's Cloud Config section
    already owns; this window is simply a second writer with the same
    read-merge-write shape (_save_cloud_config() below mirrors
    panel_mcp.py::_mcp_save_cloud_config() field-for-field).
"""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import garmin_config as cfg

# ── Queue-based log forwarding ───────────────────────────────────────────
# Architectural model: garmin_app_standalone.py's _QueueWriter/
# _QueueHandler/_poll_log_queue trio, ported from PyQt6 (QTimer.singleShot)
# to Tkinter (root.after()). No existing Tkinter precedent in the project
# to copy from — this is a new implementation of an established pattern,
# not a shared import (consistent with this module's overall "standalone
# copy, not shared code" stance — see clients/mcp_server.py's docstring on
# why T3.1/T3.3 never share bootstrap code).


class _QueueLogHandler(logging.Handler):
    """logging.Handler that pushes formatted records onto a queue.Queue
    instead of writing anywhere directly — Tkinter widgets may only be
    touched from the main thread, and log records can originate from the
    daemon thread running mcp.run(). The queue is the thread-safe handoff
    point; _poll_log_queue() (main-thread-only, via root.after()) is the
    sole consumer."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            # A full or broken queue must never raise out of logging
            # machinery — silently drop rather than crash the server
            # thread over a GUI display concern.
            pass


# ── Operational (archive) log — analogous to
# scheduler/daily_update.py::_start_daily_log() ─────────────────────────

LOG_MCP_MAX = 30  # rolling log file limit, same convention as
                  # garmin_config.LOG_RECENT_MAX / daily_update.LOG_DAILY_MAX


def _start_operational_log(base_dir: Path) -> logging.FileHandler | None:
    """Creates <base_dir>/garmin_data/log/mcp/mcp_YYYY-MM-DD_HHMMSS.log,
    attaches a FileHandler to the root logger, and prunes older files
    beyond LOG_MCP_MAX — same rotation shape as daily_update.py's
    _start_daily_log(). Returns None (not an error) if base_dir is not
    writable — the boot log and the widget remain the only destinations
    in that case; the caller decides whether to warn."""
    import datetime

    log_dir = base_dir / "garmin_data" / "log" / "mcp"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = log_dir / f"mcp_{timestamp}.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)

    # Prune — oldest first, same glob+mtime pattern as daily_update.py.
    logs = sorted(log_dir.glob("mcp_*.log"), key=lambda f: f.stat().st_mtime)
    for old in logs[:-LOG_MCP_MAX] if len(logs) > LOG_MCP_MAX else []:
        try:
            old.unlink()
        except OSError:
            pass

    return handler


# ── Server config persistence — direct read/write, standalone case ──────


def _load_server_config() -> dict:
    """Raw read of MCP_SERVER_CONFIG_FILE for form pre-fill — deliberately
    not via garmin_config.MCP_LLM_BACKEND/MCP_BASE_DIR/MCP_OLLAMA_MODEL
    (those already fold in ENV precedence, which this form does not need
    to display or respect; the form edits the file directly). Returns {}
    if missing/corrupt, same fallback as garmin_config._read_mcp_server_config()."""
    try:
        return json.loads(cfg.MCP_SERVER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_server_config(data: dict, logger: logging.Logger) -> None:
    """Direct write of MCP_SERVER_CONFIG_FILE — second writer alongside
    app/panel_mcp.py's mirror-on-save, see module docstring. Write
    failure is logged only, not shown as a blocking dialog — same
    reasoning as panel_mcp.py::_mcp_save_server_config(). mcp_enabled is
    preserved as-is from whatever panel_mcp.py last wrote (or omitted if
    never written) — this window has no checkbox to derive a new value
    from and must not silently erase or reset that field for the GLA
    side's benefit."""
    existing = _load_server_config()
    existing.update(data)
    try:
        cfg.MCP_SERVER_CONFIG_FILE.write_text(
            json.dumps(existing, indent=2), encoding="utf-8")
        logger.info("Server config saved to %s", cfg.MCP_SERVER_CONFIG_FILE)
    except OSError as exc:
        logger.warning("Server config save failed: %s", exc)


# ── Cloud LLM credentials — same file/shape as
# app/panel_mcp.py::_mcp_save_cloud_config() ─────────────────────────────


def _load_cloud_config() -> dict:
    try:
        return json.loads(cfg.MCP_LLM_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_cloud_config(provider: str, model: str, new_key: str,
                        logger: logging.Logger) -> tuple[bool, str]:
    """Read-merge-write, field-for-field mirror of
    panel_mcp.py::_mcp_save_cloud_config() — an empty new_key keeps
    whatever key is already on disk (same "leave empty to keep current
    key" convention). Returns (ok, message) instead of showing a dialog
    directly — the caller decides how to present it in this window."""
    existing = _load_cloud_config()
    existing_key = existing.get("api_key", "")
    api_key = new_key if new_key else existing_key

    if not provider or not api_key or not model:
        return False, ("Provider, API key and Model are all required — "
                        "leave API key empty only if a key is already saved.")

    data = {"provider": provider, "api_key": api_key, "model": model}
    try:
        cfg.MCP_LLM_CONFIG_FILE.write_text(
            json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        return False, f"Could not save config:\n{exc}"

    logger.info("Cloud LLM config saved.")
    return True, "Cloud credentials saved."


# ── Ollama model list — same worker pattern as
# app/panel_mcp.py::_mcp_refresh_ollama_models() ─────────────────────────


def _load_ollama_client():
    """Lazy import — same reasoning as panel_mcp.py's helper of the same
    name: keeps this module importable before sys.path is fully wired,
    and avoids importing the Ollama client at all in the (Session-
    confirmed-common) case where the backend is set to cloud."""
    from clients import ollama_client
    return ollama_client


# ── Restart — launch command resolution (v1.7 Teilbauauftrag h) ─────────
# Shortened copy of app/panel_mcp.py::_resolve_mcp_server_launch_command()
# — not imported, since clients/ does not import from app/ (module
# boundary, SESSION_BASE.md). Kept in sync manually if the build-artefact
# layout ever changes; see panel_mcp.py for the canonical, fully
# commented version and the real-build test history behind the T2/T3.3
# path decisions (Starte_MCP_Server.bat sits next to the main EXE, not
# under a clients/ subfolder — corrected after a real T2 build test in
# Teil g).


def _resolve_mcp_server_launch_command() -> list[str] | None:
    """Build-context-aware launch command for the Restart button (v1.7
    Teilbauauftrag h). Returns a Popen-ready argv list, or None if no
    valid launch target exists at the resolved path (caller shows the
    warning — this function does not touch the GUI).

    T1 (sys.frozen False): [sys.executable, <path to this script>] — this
    script (mcp_server_gui.py) is imported by mcp_server.py, which is the
    actual entry point; the T1 launch target is mcp_server.py itself,
    sitting next to this file.

    T2 (sys.frozen True, mcp_server.exe absent next to the EXE):
    [str(bat_path)] — clients/Starte_MCP_Server.bat, resolves its own
    python/cwd internally.

    T3.3 (sys.frozen True, mcp_server.exe present next to the EXE):
    [str(exe_path)] — the standalone --onefile artefact.

    T2 vs T3.3 disambiguation is a plain existence check, not a stored
    marker, same as panel_mcp.py's version."""
    if not getattr(sys, "frozen", False):
        script = Path(__file__).resolve().parent / "mcp_server.py"
        if not script.exists():
            return None
        return [sys.executable, str(script)]

    exe_dir = Path(sys.executable).parent
    exe_path = exe_dir / "mcp_server.exe"
    if exe_path.exists():
        return [str(exe_path)]

    bat_path = exe_dir / "Starte_MCP_Server.bat"
    if bat_path.exists():
        return [str(bat_path)]

    return None


# ── Main entry point ──────────────────────────────────────────────────────


def run_gui(mcp_instance, logger: logging.Logger,
            boot_handler: logging.FileHandler) -> None:
    """Opens the always-on Tkinter window and starts the stdio server in
    a daemon thread. Blocks until the window is closed (Tkinter's
    mainloop() runs on this, the main, thread) — this is the new main()
    body for clients/mcp_server.py, called once, unconditionally."""

    root = tk.Tk()
    root.title("Garmin Local Archive — MCP Server")
    root.geometry("700x560")

    saved = _load_server_config()
    saved_cloud = _load_cloud_config()

    # ── Config section ────────────────────────────────────────────────
    config_frame = ttk.Frame(root, padding=10)
    config_frame.pack(fill="x")

    ttk.Label(config_frame, text="LLM backend:").grid(
        row=0, column=0, sticky="w")
    backend_var = tk.StringVar(value=saved.get("mcp_llm_backend", "ollama"))
    backend_combo = ttk.Combobox(
        config_frame, textvariable=backend_var,
        values=["ollama", "cloud"], state="readonly", width=15,
    )
    backend_combo.grid(row=0, column=1, sticky="w")

    ttk.Label(config_frame, text="Archive path:").grid(
        row=1, column=0, sticky="w", pady=(6, 0))
    base_dir_var = tk.StringVar(
        value=saved.get("base_dir") or str(cfg.MCP_BASE_DIR))
    ttk.Entry(config_frame, textvariable=base_dir_var, width=50).grid(
        row=1, column=1, sticky="we", pady=(6, 0))

    def _browse_base_dir():
        chosen = filedialog.askdirectory(
            initialdir=base_dir_var.get() or str(Path.home()))
        if chosen:
            base_dir_var.set(chosen)

    ttk.Button(config_frame, text="…", width=3, command=_browse_base_dir).grid(
        row=1, column=2, sticky="w", padx=(4, 0), pady=(6, 0))

    config_frame.columnconfigure(1, weight=1)

    # ── Ollama backend fields — shown only when backend == "ollama" ────
    ollama_frame = ttk.Frame(root, padding=(10, 4))
    ttk.Label(ollama_frame, text="Ollama model:").grid(row=0, column=0, sticky="w")
    ollama_model_var = tk.StringVar(value=saved.get("mcp_ollama_model", ""))
    ollama_model_combo = ttk.Combobox(
        ollama_frame, textvariable=ollama_model_var, state="readonly", width=30)
    if saved.get("mcp_ollama_model"):
        ollama_model_combo["values"] = [saved["mcp_ollama_model"]]
    ollama_model_combo.grid(row=0, column=1, sticky="w", padx=(4, 0))
    ollama_status_var = tk.StringVar(value="")
    ttk.Label(ollama_frame, textvariable=ollama_status_var).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _on_ollama_models_loaded(models: list, error: str):
        if error:
            ollama_status_var.set(f"Ollama not reachable: {error}")
            return
        if not models:
            ollama_status_var.set(
                "No models installed — `ollama pull <model>` and refresh.")
            return
        current = ollama_model_var.get()
        ollama_model_combo["values"] = models
        if current not in models and models:
            ollama_model_var.set(models[0])
        ollama_status_var.set(f"{len(models)} model(s) found.")

    def _refresh_ollama_models():
        ollama_status_var.set("Loading models …")

        def worker():
            client = _load_ollama_client()
            try:
                models = client.list_models()
                error = None
            except client.OllamaError as e:
                models, error = [], str(e)
            root.after(0, lambda: _on_ollama_models_loaded(models, error))

        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(ollama_frame, text="Refresh", command=_refresh_ollama_models).grid(
        row=0, column=2, padx=(6, 0))

    # ── Cloud backend fields — shown only when backend == "cloud" ──────
    cloud_frame = ttk.Frame(root, padding=(10, 4))
    ttk.Label(
        cloud_frame,
        text="⚠ Saved as plaintext to ~/.garmin_mcp_llm_config.json — "
             "not encrypted.",
    ).grid(row=0, column=0, columnspan=2, sticky="w")

    ttk.Label(cloud_frame, text="Provider:").grid(row=1, column=0, sticky="w", pady=(4, 0))
    cloud_provider_var = tk.StringVar(value=saved_cloud.get("provider", ""))
    ttk.Entry(cloud_frame, textvariable=cloud_provider_var, width=30).grid(
        row=1, column=1, sticky="w", pady=(4, 0))

    ttk.Label(cloud_frame, text="API key:").grid(row=2, column=0, sticky="w", pady=(4, 0))
    cloud_key_var = tk.StringVar(value="")
    ttk.Entry(cloud_frame, textvariable=cloud_key_var, width=30, show="•").grid(
        row=2, column=1, sticky="w", pady=(4, 0))

    ttk.Label(cloud_frame, text="Model:").grid(row=3, column=0, sticky="w", pady=(4, 0))
    cloud_model_var = tk.StringVar(value=saved_cloud.get("model", ""))
    ttk.Entry(cloud_frame, textvariable=cloud_model_var, width=30).grid(
        row=3, column=1, sticky="w", pady=(4, 0))

    cloud_key_status_var = tk.StringVar(
        value="API key is set on disk — leave the field empty to keep it."
        if saved_cloud.get("api_key") else "No API key set.")
    ttk.Label(cloud_frame, textvariable=cloud_key_status_var).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def _on_save_cloud_config():
        ok, message = _save_cloud_config(
            cloud_provider_var.get().strip(),
            cloud_model_var.get().strip(),
            cloud_key_var.get().strip(),
            logger,
        )
        if not ok:
            messagebox.showwarning("MCP Cloud Config", message)
            return
        cloud_key_var.set("")
        refreshed = _load_cloud_config()
        cloud_key_status_var.set(
            "API key is set on disk — leave the field empty to keep it."
            if refreshed.get("api_key") else "No API key set.")

    ttk.Button(cloud_frame, text="Save Cloud Credentials",
               command=_on_save_cloud_config).grid(
        row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _on_backend_changed(*_args):
        if backend_var.get() == "ollama":
            cloud_frame.pack_forget()
            ollama_frame.pack(fill="x", after=config_frame)
        else:
            ollama_frame.pack_forget()
            cloud_frame.pack(fill="x", after=config_frame)

    backend_combo.bind("<<ComboboxSelected>>", _on_backend_changed)
    _on_backend_changed()

    # ── Save (server config: backend, base_dir, ollama model) ──────────
    def _on_save():
        data = {
            "mcp_llm_backend":  backend_var.get(),
            "base_dir":         base_dir_var.get().strip(),
            "mcp_ollama_model": ollama_model_var.get(),
        }
        _save_server_config(data, logger)
        messagebox.showinfo(
            "Garmin Local Archive — MCP Server",
            "Config saved. Restart the server for a changed archive "
            "path to take effect.",
        )

    ttk.Button(root, text="💾 Save", command=_on_save).pack(
        anchor="w", padx=10, pady=(4, 0))

    # ── Restart (v1.7 Teilbauauftrag h) ─────────────────────────────────
    # Self-Relaunch with a transitional window state (Option C, session
    # decision) — the current process is not killed outright; a new
    # process is started first, and this window only closes once the new
    # process confirms it is up (via a new PID in MCP_SERVER_LOCK_FILE).
    # Deliberately a separate button from Save (Eckpunkt 3) — Save has no
    # diff check and fires on every click, coupling would trigger a
    # disruptive restart on routine saves too.
    _this_pid = os.getpid()
    RESTART_POLL_MS = 500
    RESTART_TIMEOUT_MS = 12_000

    def _set_transition_state(active: bool):
        """Disables the Restart button itself during the wait — prevents
        a second, overlapping restart attempt, which is the actual
        purpose of this guard. Save/Browse are deliberately left alone
        (both are anonymous ttk.Button() calls with no variable to
        reference, and neither is unsafe to use mid-transition: Save
        only rewrites the config file, no process is touched)."""
        restart_btn.configure(state="disabled" if active else "normal")
        status_var.set("Restarting — please wait …" if active else "")

    def _on_restart():
        cmd = _resolve_mcp_server_launch_command()
        if cmd is None:
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                "Could not find clients/mcp_server.py, mcp_server.exe, or "
                "Starte_MCP_Server.bat — check the installation. "
                "The current server keeps running.",
            )
            return

        confirmed = messagebox.askyesno(
            "Garmin Local Archive — MCP Server",
            "This will restart the MCP server process to apply the "
            "current settings. The window will briefly show a "
            "restarting state, then reopen automatically.\n\n"
            "Continue?",
        )
        if not confirmed:
            return

        _set_transition_state(True)
        logger.info("Restart requested — launch command: %s", cmd)

        # Unlink attempt for the OLD process's lock file is triggered
        # first, before the new process starts — per NOTES_v1.7_teilh.md
        # ordering decision. This mirrors _on_close()'s unlink step but
        # does NOT destroy the window here (that only happens once the
        # new process is confirmed running, see _poll_for_new_process
        # below). Best-effort, same fail-open reasoning as _on_close().
        try:
            cfg.MCP_SERVER_LOCK_FILE.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove lock file %s: %s",
                            cfg.MCP_SERVER_LOCK_FILE, exc)

        try:
            subprocess.Popen(cmd)
        except OSError as exc:
            logger.error("Restart failed to launch new process: %s", exc)
            _set_transition_state(False)
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                f"Could not start the new server process:\n{exc}\n\n"
                "The previous server may no longer be reachable — check "
                "the log above.",
            )
            return

        _elapsed = {"ms": 0}

        def _poll_for_new_process():
            try:
                pid_text = cfg.MCP_SERVER_LOCK_FILE.read_text(
                    encoding="utf-8").strip()
                new_pid = int(pid_text)
            except (FileNotFoundError, ValueError):
                new_pid = None

            if new_pid is not None and new_pid != _this_pid:
                logger.info(
                    "Restart confirmed — new process PID %d, closing "
                    "this window", new_pid)
                root.destroy()
                return

            _elapsed["ms"] += RESTART_POLL_MS
            if _elapsed["ms"] >= RESTART_TIMEOUT_MS:
                logger.error(
                    "Restart timed out after %d ms — no new PID seen "
                    "in lock file", RESTART_TIMEOUT_MS)
                _set_transition_state(False)
                messagebox.showwarning(
                    "Garmin Local Archive — MCP Server",
                    "Restart failed — the new server process did not "
                    "start in time. The previous server keeps running "
                    "in this window (check the log above for details).",
                )
                return

            root.after(RESTART_POLL_MS, _poll_for_new_process)

        root.after(RESTART_POLL_MS, _poll_for_new_process)

    restart_btn = ttk.Button(
        root, text="🔄 Restart Server", command=_on_restart)
    restart_btn.pack(anchor="w", padx=10, pady=(4, 0))

    status_var = tk.StringVar(value="")
    ttk.Label(root, textvariable=status_var).pack(
        anchor="w", padx=10, pady=(2, 0))

    # ── Log section — analogous to garmin_app_base.py's log widget ─────
    log_bar = ttk.Frame(root, padding=(10, 4))
    log_bar.pack(fill="x")
    ttk.Label(log_bar, text="LOG", font=("Segoe UI", 8, "bold")).pack(side="left")

    log_level_state = {"level": "INFO"}  # mutable box, closures below need it

    def _toggle_log_level():
        if log_level_state["level"] == "INFO":
            log_level_state["level"] = "DEBUG"
            log_level_btn.config(text="📋  Log: Detailed")
        else:
            log_level_state["level"] = "INFO"
            log_level_btn.config(text="📋  Log: Simple")
        logging.getLogger().setLevel(
            getattr(logging, log_level_state["level"]))

    def _clear_log():
        log_widget.configure(state="normal")
        log_widget.delete("1.0", tk.END)
        log_widget.configure(state="disabled")

    ttk.Button(log_bar, text="Clear", command=_clear_log).pack(side="right")
    log_level_btn = ttk.Button(
        log_bar, text="📋  Log: Simple", command=_toggle_log_level)
    log_level_btn.pack(side="right", padx=(0, 6))

    log_widget = scrolledtext.ScrolledText(
        root, height=14, state="disabled", font=("Consolas", 9),
        background="#0a0a1a", foreground="#33ff66")
    log_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ── Queue-based log wiring ──────────────────────────────────────────
    log_queue: queue.Queue = queue.Queue()
    queue_handler = _QueueLogHandler(log_queue)
    queue_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(queue_handler)
    logging.getLogger().setLevel(logging.INFO)  # matches "Simple" default

    def _poll_log_queue():
        try:
            while True:
                line = log_queue.get_nowait()
                log_widget.configure(state="normal")
                log_widget.insert(tk.END, line + "\n")
                log_widget.see(tk.END)
                log_widget.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(100, _poll_log_queue)

    root.after(100, _poll_log_queue)

    # ── Operational log — replaces boot log now that base_dir is known ──
    op_base_dir = Path(base_dir_var.get()).expanduser()
    op_handler = _start_operational_log(op_base_dir)
    if op_handler is not None:
        logging.getLogger().removeHandler(boot_handler)
        boot_handler.close()
        logger.info("Operational log started under %s — boot log closed",
                    op_base_dir)
    else:
        logger.warning(
            "Could not start operational log under %s — boot log stays "
            "active for this session", op_base_dir)

    # ── Server thread — daemon, no cancel handshake (see module docstring) ──
    def _server_thread():
        logger.info("Starting Garmin Local Archive MCP server (stdio transport)")
        try:
            mcp_instance.run(transport="stdio")
        except Exception as exc:  # pragma: no cover — last-resort visibility
            # mcp.run() failures here have nowhere else to surface once
            # stdout is reserved as the protocol channel — log it so the
            # widget/log files show *something* instead of a silent thread
            # death. The daemon thread ending does not close the window.
            logger.error("MCP server thread ended: %s", exc)

    threading.Thread(target=_server_thread, daemon=True).start()

    def _on_close():
        logger.info("mcp_server.exe window closing — server thread will "
                    "end with the process")
        try:
            cfg.MCP_SERVER_LOCK_FILE.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove lock file %s: %s",
                            cfg.MCP_SERVER_LOCK_FILE, exc)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
