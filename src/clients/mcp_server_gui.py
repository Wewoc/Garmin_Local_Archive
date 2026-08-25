#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
clients/mcp_server_gui.py
Garmin Local Archive — MCP Server Window (v1.7.0.1)

Role (v1.7.0.1, corrected after an initial misreading of Eckpunkt 6 —
see NOTES_v1.7.0.1vorbereitung.md): this window stays the default entry
point, exactly as it was under v1.7 Teilbauauftrag f's "the window is
the server" — Timo's explicit decision was to KEEP that coupling
(window closed = process closed), not to make the server headless by
default. What actually changes with the streamable-http transport is
narrower: run_gui() (renamed from the transport-era-agnostic name this
function has always had) starts mcp.run(transport="streamable-http")
in a daemon thread instead of transport="stdio", and the Restart
button's health-check switches from polling garmin_config.
MCP_SERVER_LOCK_FILE for a new PID to a plain TCP-connect probe against
garmin_config.MCP_HTTP_PORT (Eckpunkt 4a, Fall 2 — the lockfile itself
is gone, see garmin_config.py).

Headless mode (v1.7.0.1, new): garmin_config.MCP_HEADLESS, settable
from a checkbox in THIS window (a "next start" setting — checking it
here does not affect the already-running server this same window
started, only a subsequent launch) and from app/panel_mcp.py's Port row
for the GLA-integrated case. When set, clients/mcp_server.py::main()
skips this window entirely and runs the server directly on the calling
thread (see that module's _run_headless()) — analogous to
scheduler/daily_update.py. This window is never required for the
server to run; it is simply the default when MCP_HEADLESS is false.

Tkinter, not PyQt6 — deliberate (session decision, unchanged from v1.7):
PyQt6 in GLA proper is tied to the WebEngine dashboard view, which this
window has no need for. tkinter.filedialog/messagebox/ttk/scrolledtext
are already in HIDDEN_IMPORTS_COMMON (compiler/build_manifest.py), so
this adds no new bundling weight for T3.3.

Restart (v1.7.0.1, replacing the v1.7 Teilbauauftrag h button of the
same intent): unlike the server start itself, which now happens
automatically the moment this window opens (no separate "Start" click
needed — Timo's corrected Eckpunkt 6), the "🔄 Restart Server" button
still exists for the same reason it did before: a config change (port,
archive path, backend, headless) needs a new process to take effect,
and there is still no clean-stop API on a running mcp.run() call under
either transport (Eckpunkt 4b, re-confirmed for streamable-http — an
open FastMCP/uvicorn upstream issue tracks exactly this gap). Self-
Relaunch via subprocess.Popen (Option C reasoning from Teilbauauftrag h
retained): launches a new process with current on-disk settings
(Save first, then Restart — same two-step as before), polls
_is_server_reachable() against the (possibly changed) target port, and
on success calls root.destroy() — which ends THIS process, and with it
the daemon thread holding the old server, completing the handover. A
timeout leaves the old server running untouched and re-enables the
button. If the saved settings switched MCP_HEADLESS to true, the new
process comes up without a window at all, but is still TCP-reachable on
its port the same way — the restart flow does not need to special-case
that transition.

Log display: unchanged in shape from v1.7 — since the server runs in
this same process again (daemon thread), its log records reach this
window's root logger exactly like this window's own log lines do, both
via the single _QueueLogHandler + root.after(100, ...) poll loop
(architectural port of garmin_app_standalone.py's PyQt6
_QueueWriter/_QueueHandler/_poll_log_queue trio). No file-tailing, no
cross-process log mechanism needed — that only existed in the
(corrected-away) headless-by-default draft of this Bauauftrag.

Persistence — two separate files, unchanged in shape from v1.7:
  - garmin_config.MCP_SERVER_CONFIG_FILE (mcp_llm_backend, base_dir,
    mcp_http_port, mcp_headless as of v1.7.0.1 — mcp_ollama_model
    removed, see below) — this window is a second, independent writer
    alongside panel_mcp.py's mirror-on-save (documented as a deliberate
    Sole-Write-Authority exception in garmin_config.py's docstring: the
    two writers serve mutually exclusive operating modes and never run
    against the file at the same time in practice). base_dir here is a
    real, user-editable field (no GLA instance to mirror from), unlike
    panel_mcp.py's read-only mirror value.
  - garmin_config.MCP_LLM_CONFIG_FILE (provider, api_key, model) — cloud
    LLM credentials, same file panel_mcp.py's Cloud Config section
    already owns; this window is simply a second writer with the same
    read-merge-write shape (_save_cloud_config() below mirrors
    panel_mcp.py::_mcp_save_cloud_config() field-for-field).

Ollama model selection removed (v1.7.0.1, Zusatzpunkt from
NOTES_v1.7.0.1vorbereitung.md): MCP itself never calls an LLM — the MCP
host (Ollama, Open WebUI, Claude Desktop, ...) decides which model runs
and this server never sees that choice. mcp_ollama_model was architected
into the wrong process; it is gone from this window, from
MCP_SERVER_CONFIG_FILE, and from garmin_config.py entirely. The
mcp_llm_backend choice itself (ollama vs. cloud) is unrelated and stays
— it still gates whether the cloud-credentials block below is shown.
"""

import json
import logging
import queue
import socket
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
# to Tkinter (root.after()). Feeds from BOTH this window's own log lines
# (config load/save, launch attempts) and the server's own log records —
# both go through the same root logger, since the server runs in this
# same process (daemon thread) once run_gui() has started it.


class _QueueLogHandler(logging.Handler):
    """logging.Handler that pushes formatted records onto a queue.Queue
    instead of writing anywhere directly — Tkinter widgets may only be
    touched from the main thread, and the server's own log records
    arrive from the daemon thread running mcp.run(), so this handler is
    genuinely thread-safety-load-bearing here (not just a defensive
    habit) — root.after() picks records off the queue on the main
    thread only."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except Exception:
            # A full or broken queue must never raise out of logging
            # machinery — silently drop rather than crash over a GUI
            # display concern.
            pass


# ── Server reachability — TCP connect probe (v1.7.0.1) ──────────────────
# Replaces the v1.7 lockfile/PID mechanism (garmin_config.
# MCP_SERVER_LOCK_FILE, removed). A short-timeout connect is enough to
# know "something is listening on this port" — no MCP protocol handshake
# needed, same "best-effort convenience check, not a security boundary"
# reasoning the lockfile carried before it. Standalone copy, not a
# shared helper — clients/ does not import from app/, and app/panel_mcp.py
# has its own copy of the same few lines (module boundary, SESSION_BASE.md).


def _is_server_reachable(port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


# ── Server config persistence — direct read/write, standalone case ──────


def _load_server_config() -> dict:
    """Raw read of MCP_SERVER_CONFIG_FILE for form pre-fill — deliberately
    not via garmin_config.MCP_LLM_BACKEND/MCP_BASE_DIR/MCP_HTTP_PORT/
    MCP_HEADLESS (those already fold in ENV precedence, which this form
    does not need to display or respect; the form edits the file
    directly). Returns {} if missing/corrupt, same fallback as
    garmin_config._read_mcp_server_config()."""
    try:
        return json.loads(cfg.MCP_SERVER_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_server_config(data: dict, logger: logging.Logger) -> None:
    """Direct write of MCP_SERVER_CONFIG_FILE — second writer alongside
    app/panel_mcp.py's mirror-on-save, see module docstring. Write
    failure is logged only, not shown as a blocking dialog — same
    reasoning as panel_mcp.py::_mcp_save_server_config()."""
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


# ── Launch command resolution (v1.7 Teilbauauftrag h, unchanged shape) ──
# Shortened copy of app/panel_mcp.py::_resolve_mcp_server_launch_command()
# — not imported, since clients/ does not import from app/ (module
# boundary, SESSION_BASE.md). Kept in sync manually if the build-artefact
# layout ever changes; see panel_mcp.py for the canonical, fully
# commented version. Launches mcp_server.py/mcp_server.exe with no extra
# arguments — windowed vs. headless is entirely config-driven
# (garmin_config.MCP_HEADLESS), not a launch-time CLI flag, so the same
# command is correct for both outcomes.


def _resolve_mcp_server_launch_command() -> list[str] | None:
    """Build-context-aware launch command for the Restart button.
    Returns a Popen-ready argv list, or None if no valid launch target
    exists at the resolved path (caller shows the warning — this
    function does not touch the GUI).

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
            boot_handler: logging.FileHandler,
            start_operational_log) -> None:
    """Opens the MCP server window and starts the server together
    (v1.7.0.1 default entry point — Timo decision, NOTES_
    v1.7.0.1vorbereitung.md Eckpunkt 6: the window stays coupled to the
    server exactly as under the stdio-era "the window is the server"
    model; only the transport and the restart-health-check mechanism
    changed). Called only from clients/mcp_server.py::main() when
    garmin_config.MCP_HEADLESS is False (the default) — see that
    module's _run_headless() for the alternative path.

    start_operational_log is passed in rather than imported to avoid a
    circular import (clients/mcp_server.py imports this module to call
    run_gui(); this module must not import clients/mcp_server.py back) —
    it is clients/mcp_server.py::_start_operational_log(), the exact
    same function the headless path calls, so both paths hand off from
    the boot log to the operational log identically.

    mcp_instance.run(transport="streamable-http") runs in a daemon=True
    thread; root.mainloop() blocks the main thread until the window
    closes. Closing the window ends this process, which ends the daemon
    thread with it — same shutdown model as v1.7's stdio version (no
    clean-stop API exists on a running mcp.run() call under either
    transport, see NOTES Eckpunkt 4b). Whether streamable-http's daemon
    thread (an anyio/uvicorn event loop) shuts down as quietly as this
    at process exit, or produces its own version of the stdio transport's
    old interpreter-shutdown warning, is untested in this environment —
    verify on a real Windows run."""

    op_handler = start_operational_log(cfg.MCP_BASE_DIR)
    if op_handler is not None:
        logging.getLogger().removeHandler(boot_handler)
        boot_handler.close()
        logger.info("Operational log started under %s — boot log closed",
                    cfg.MCP_BASE_DIR)
    else:
        logger.warning(
            "Could not start operational log under %s — boot log stays "
            "active for this session", cfg.MCP_BASE_DIR)

    server_state = {"error": None}

    def _run_server():
        logger.info("Starting Garmin Local Archive MCP server on "
                    "http://127.0.0.1:%d", cfg.MCP_HTTP_PORT)
        try:
            mcp_instance.run(transport="streamable-http")
        except OSError as exc:
            server_state["error"] = exc
            logger.error(
                "Could not start MCP server on 127.0.0.1:%d — port already "
                "in use (a second instance already running?) or not "
                "permitted: %s", cfg.MCP_HTTP_PORT, exc)

    threading.Thread(target=_run_server, daemon=True).start()

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

    ttk.Label(config_frame, text="Port:").grid(
        row=2, column=0, sticky="w", pady=(6, 0))
    port_var = tk.StringVar(
        value=str(saved.get("mcp_http_port") or cfg.MCP_HTTP_PORT))
    ttk.Entry(config_frame, textvariable=port_var, width=8).grid(
        row=2, column=1, sticky="w", pady=(6, 0))
    ttk.Label(
        config_frame,
        text="127.0.0.1 only — not remotely reachable, by design.",
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))

    headless_var = tk.BooleanVar(value=bool(saved.get("mcp_headless", False)))
    ttk.Checkbutton(
        config_frame, text="Headless starten (ohne Fenster)",
        variable=headless_var,
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Label(
        config_frame,
        text="Wirkt erst beim nächsten Start — nicht auf diese laufende Instanz.",
    ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

    config_frame.columnconfigure(1, weight=1)

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
        if backend_var.get() == "cloud":
            cloud_frame.pack(fill="x", after=config_frame)
        else:
            cloud_frame.pack_forget()

    backend_combo.bind("<<ComboboxSelected>>", _on_backend_changed)
    _on_backend_changed()

    # ── Save (server config: backend, base_dir, port, headless) ────────
    def _on_save():
        port_text = port_var.get().strip()
        try:
            port = int(port_text)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                f"'{port_text}' is not a valid port number (1-65535).")
            return

        data = {
            "mcp_llm_backend": backend_var.get(),
            "base_dir":        base_dir_var.get().strip(),
            "mcp_http_port":   port,
            "mcp_headless":    headless_var.get(),
        }
        _save_server_config(data, logger)
        messagebox.showinfo(
            "Garmin Local Archive — MCP Server",
            "Config saved. Restart the server for a changed archive "
            "path, port, or headless setting to take effect.",
        )

    ttk.Button(root, text="💾 Save", command=_on_save).pack(
        anchor="w", padx=10, pady=(4, 0))

    # ── Restart (v1.7.0.1) ───────────────────────────────────────────────
    # The server itself is already running by the time this window is
    # visible (started above, before root = tk.Tk()) — this button only
    # ever restarts, it never does an initial "start". Self-Relaunch via
    # subprocess.Popen (Option C reasoning from v1.7 Teilbauauftrag h
    # retained), confirmed via a TCP probe on the configured port rather
    # than a lockfile PID poll; on success this window (and with it, the
    # old server's daemon thread) is torn down, handing over to the new
    # process.
    RESTART_POLL_MS = 500
    RESTART_TIMEOUT_MS = 12_000

    def _set_transition_state(active: bool):
        restart_btn.configure(state="disabled" if active else "normal")
        status_var.set("Restarting — please wait …" if active else "")

    def _on_restart():
        cmd = _resolve_mcp_server_launch_command()
        if cmd is None:
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                "Could not find clients/mcp_server.py, mcp_server.exe, or "
                "Starte_MCP_Server.bat — check the installation.",
            )
            return

        try:
            target_port = int(port_var.get().strip())
        except ValueError:
            target_port = cfg.MCP_HTTP_PORT

        confirmed = messagebox.askyesno(
            "Garmin Local Archive — MCP Server",
            "This starts a new MCP server process with the saved "
            "settings and closes this window (and the server it is "
            "currently running) once the new one answers on its port. "
            "Save first if you just changed something.\n\nContinue?",
        )
        if not confirmed:
            return

        _set_transition_state(True)
        logger.info("Restart requested — launch command: %s", cmd)

        try:
            subprocess.Popen(cmd)
        except OSError as exc:
            logger.error("Restart failed to launch new process: %s", exc)
            _set_transition_state(False)
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                f"Could not start the server process:\n{exc}",
            )
            return

        _elapsed = {"ms": 0}

        def _poll_reachable():
            if _is_server_reachable(target_port):
                logger.info(
                    "New server confirmed reachable on 127.0.0.1:%d — "
                    "closing this window", target_port)
                root.destroy()
                return

            _elapsed["ms"] += RESTART_POLL_MS
            if _elapsed["ms"] >= RESTART_TIMEOUT_MS:
                logger.error(
                    "Restart: no response on 127.0.0.1:%d after %d ms — "
                    "old server left running", target_port,
                    RESTART_TIMEOUT_MS)
                _set_transition_state(False)
                messagebox.showwarning(
                    "Garmin Local Archive — MCP Server",
                    "The new server did not become reachable in time — "
                    "the old one is still running. Check the archive "
                    "path/port and the boot log "
                    "(~/.garmin_mcp_server_boot.log).",
                )
                return

            root.after(RESTART_POLL_MS, _poll_reachable)

        root.after(RESTART_POLL_MS, _poll_reachable)

    restart_btn = ttk.Button(
        root, text="🔄 Restart Server", command=_on_restart)
    restart_btn.pack(anchor="w", padx=10, pady=(4, 0))

    status_var = tk.StringVar(value="")
    ttk.Label(root, textvariable=status_var).pack(
        anchor="w", padx=10, pady=(2, 0))

    def _check_bind_result():
        if server_state["error"] is not None:
            status_var.set("Server not running — port bind failed, see log.")
            messagebox.showwarning(
                "Garmin Local Archive — MCP Server",
                f"The server could not bind 127.0.0.1:{cfg.MCP_HTTP_PORT} — "
                f"{server_state['error']}\n\nAnother instance may already "
                "be running. This window stays open for configuration, "
                "but no server is currently listening.",
            )

    root.after(300, _check_bind_result)

    # ── Log section ──────────────────────────────────────────────────────
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

    def _append_log_line(line: str):
        log_widget.configure(state="normal")
        log_widget.insert(tk.END, line + "\n")
        log_widget.see(tk.END)
        log_widget.configure(state="disabled")

    # ── Queue-based log wiring — this window's own AND the server's log
    # lines, since the server runs in this same process (daemon thread) ─
    log_queue: queue.Queue = queue.Queue()
    queue_handler = _QueueLogHandler(log_queue)
    queue_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(queue_handler)
    logging.getLogger().setLevel(logging.INFO)  # matches "Simple" default

    def _poll_log_queue():
        try:
            while True:
                _append_log_line(log_queue.get_nowait())
        except queue.Empty:
            pass
        root.after(100, _poll_log_queue)

    root.after(100, _poll_log_queue)

    def _on_close():
        logger.info("Window closing — the server (daemon thread) ends "
                    "with this process, same as the v1.7 stdio model.")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
