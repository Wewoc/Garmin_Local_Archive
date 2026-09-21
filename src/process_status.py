#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
process_status.py

Leaf-Node. "Läuft Prozess X gerade" für die GLA-Prozesse, die (anders
als MCP) keinen Port haben, den man abfragen könnte — GUI und
daily_update.exe. Für v1.7.2.4 (Updater): die GUI muss vor dem eigenen
Update-Swap wissen, ob `daily_update.exe` gerade läuft; umgekehrt muss
`daily_update.exe` bei seinem unbeaufsichtigten Auto-Apply-Lauf wissen,
ob die GUI gerade offen ist.

PID-Lock-Datei statt tasklist/netstat: dieses Projekt hat mit
Subprozess-basierten Prozess-Checks bereits reale Timeouts erlebt
(clients/mcp_process.py, Kommentar zum 20s-Timeout-Fallback,
"netstat/taskkill subprocess spawns were observed timing out"). Hier
stattdessen ein fester Lock-Datei-Pfad pro Prozess-Name unter
Path.home() (gleiche Konvention wie .garmin_archive_settings.json /
.garmin_mcp_server_config.json) + ein Liveness-Check über die
Windows-API (ctypes, kein Subprozess-Spawn).

is_mcp_running() — TCP-Connect-Probe, identisch zur bisherigen Logik in
    app/panel_mcp.py::_mcp_server_is_running() (die jetzt hierher
    delegiert, um Duplikation zu vermeiden — siehe KNOWN_ISSUES.md
    Cluster F). Lazy-Import von garmin_config INNERHALB der Funktion,
    nicht auf Modulebene: garmin_config liest os.environ beim eigenen
    Import und cacht das Ergebnis; ein verfrühter Top-Level-Import
    hier (bevor scheduler/daily_update.py seine ENVs gesetzt hat) würde
    genau das Caching-Problem riskieren, vor dem sich daily_update.py
    an mehreren Stellen bereits ausdrücklich schützt ("Lazy import
    after ENVs are set"). Dieses Modul selbst bleibt dadurch frei von
    Nebeneffekten beim Import — sicher für jeden Build-Zeitpunkt.

write_lock(name) / clear_lock(name) / is_running(name) — feste Datei
    Path.home()/f".garmin_{name}_lock" mit der eigenen PID. is_running()
    behandelt eine verwaiste Datei mit einer nicht mehr lebenden PID
    (Absturz, kein sauberes Beenden) korrekt als "läuft nicht", nicht
    als falsches Positiv.
"""

import ctypes
import os
import socket
from pathlib import Path

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def is_mcp_running() -> bool:
    """TCP-Connect-Probe gegen 127.0.0.1:MCP_HTTP_PORT — siehe
    Moduldocstring. app/panel_mcp.py delegiert hierher."""
    import garmin_config as cfg  # lazy — siehe Moduldocstring
    try:
        with socket.create_connection(
                ("127.0.0.1", cfg.MCP_HTTP_PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _lock_path(name: str) -> Path:
    return Path.home() / f".garmin_{name}_lock"


def write_lock(name: str) -> None:
    """Schreibt die eigene PID in die feste Lock-Datei für `name`."""
    _lock_path(name).write_text(str(os.getpid()))


def clear_lock(name: str) -> None:
    """Entfernt die Lock-Datei für `name` — best effort, kein Fehler
    wenn sie bereits fehlt."""
    _lock_path(name).unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    """True, wenn ein Prozess mit dieser PID aktuell existiert — per
    WinAPI OpenProcess, kein Subprozess-Spawn (kein tasklist/netstat)."""
    handle = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def is_running(name: str) -> bool:
    """True, wenn die Lock-Datei für `name` existiert UND die darin
    gespeicherte PID aktuell noch lebt."""
    return get_pid(name) is not None


def get_pid(name: str) -> int | None:
    """Liefert die in der Lock-Datei für `name` gespeicherte PID, aber
    nur wenn sie aktuell noch lebt — None bei fehlender/verwaister/
    kaputter Datei. Für v1.7.2.4: der PowerShell-Helfer wartet auf
    konkrete PIDs (-WaitPids), nicht auf ein bloßes Ja/Nein."""
    try:
        pid = int(_lock_path(name).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None
