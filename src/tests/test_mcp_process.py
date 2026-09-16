# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/test_mcp_process.py
Garmin Local Archive — MCP Process Control Test Suite (Baustein 29)

Run with:
    pytest tests/test_mcp_process.py -v

Scope: clients/mcp_process.py — plain Python, no Qt. Never spawns a
real process or calls real netstat/taskkill; every subprocess.Popen/
subprocess.run call is patched.

garmin_collector-3_experiment, Baustein 29: start() now remembers the
PID it launched (_last_started_pid), and stop() tries killing that PID
first (via _kill_pid_tree(), taskkill /T) before falling back to the
pre-existing netstat-based lookup — see clients/mcp_process.py's own
docstrings for the full reasoning (a .bat/--onefile launch means the
remembered PID is not always the actual listener, hence /T). Each test
resets module-level _last_started_pid explicitly (autouse fixture) —
it is shared process-wide state, and tests must not leak it between
each other.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "clients"))

import mcp_process as mp


@pytest.fixture(autouse=True)
def _reset_last_started_pid():
    mp._last_started_pid = None
    yield
    mp._last_started_pid = None


class TestFindListeningPid:

    def test_matches_listening_socket(self):
        output = (
            "  TCP    127.0.0.1:8756         0.0.0.0:0              LISTENING       1234\n"
        )
        assert mp._find_listening_pid(output, 8756) == 1234

    def test_ignores_client_connection_to_the_port(self):
        # A connection TO the port (e.g. a test probe) has the server's
        # address as its own foreign address, not "0.0.0.0:0" — must be
        # excluded (module docstring's locale-pitfall explanation).
        output = (
            "  TCP    127.0.0.1:51000        127.0.0.1:8756         ESTABLISHED     5678\n"
        )
        assert mp._find_listening_pid(output, 8756) is None

    def test_no_match_returns_none(self):
        assert mp._find_listening_pid("", 8756) is None


class TestStart:

    def test_returns_true_if_already_running(self):
        with patch("mcp_process.is_running", return_value=True):
            ok, msg = mp.start()
        assert ok is True
        assert "already running" in msg
        assert mp._last_started_pid is None

    def test_returns_false_if_launch_command_unresolvable(self):
        with patch("mcp_process.is_running", return_value=False), \
             patch("mcp_process.resolve_launch_command", return_value=None):
            ok, msg = mp.start()
        assert ok is False
        assert "Could not find" in msg

    def test_remembers_pid_on_successful_launch(self):
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        with patch("mcp_process.is_running", return_value=False), \
             patch("mcp_process.resolve_launch_command",
                   return_value=["mcp_server.exe"]), \
             patch("mcp_process.subprocess.Popen", return_value=mock_proc):
            ok, _ = mp.start()
        assert ok is True
        assert mp._last_started_pid == 4242

    def test_popen_oserror_does_not_remember_a_pid(self):
        with patch("mcp_process.is_running", return_value=False), \
             patch("mcp_process.resolve_launch_command",
                   return_value=["mcp_server.exe"]), \
             patch("mcp_process.subprocess.Popen",
                   side_effect=OSError("no such file")):
            ok, msg = mp.start()
        assert ok is False
        assert "Could not start" in msg
        assert mp._last_started_pid is None


class TestStop:

    def test_returns_false_if_not_running(self):
        with patch("mcp_process.is_running", return_value=False):
            ok, msg = mp.stop()
        assert ok is False
        assert "not running" in msg

    def test_uses_remembered_pid_and_skips_netstat(self):
        # garmin_collector-3_experiment, Baustein 29 — the whole point of
        # remembering the PID: netstat must never even be called here.
        mp._last_started_pid = 4242
        with patch("mcp_process.is_running", return_value=True), \
             patch("mcp_process.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, msg = mp.stop()
        assert ok is True
        assert "PID 4242" in msg
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd == ["taskkill", "/PID", "4242", "/T", "/F"]
        # remembered PID is one-shot — cleared regardless of outcome, so a
        # later stop() (e.g. after a manual restart) does not reuse a
        # stale PID.
        assert mp._last_started_pid is None

    def test_falls_back_to_netstat_when_no_pid_remembered(self):
        # e.g. server started externally (manual .bat launch) — never
        # went through this module's own start().
        assert mp._last_started_pid is None
        netstat_out = (
            "  TCP    127.0.0.1:8756         0.0.0.0:0              LISTENING       9999\n"
        )
        with patch("mcp_process.is_running", return_value=True), \
             patch("mcp_process.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=netstat_out),  # netstat
                MagicMock(returncode=0),                       # taskkill
            ]
            ok, msg = mp.stop()
        assert ok is True
        assert "PID 9999" in msg
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0][0] == "netstat"
        assert mock_run.call_args_list[1][0][0] == ["taskkill", "/PID", "9999", "/F"]

    def test_falls_back_to_netstat_when_remembered_pid_is_stale(self):
        # _kill_pid_tree() fails (process already gone) — must still try
        # the netstat-based lookup instead of giving up immediately.
        mp._last_started_pid = 1111
        netstat_out = (
            "  TCP    127.0.0.1:8756         0.0.0.0:0              LISTENING       2222\n"
        )
        with patch("mcp_process.is_running", return_value=True), \
             patch("mcp_process.subprocess.run") as mock_run:
            import subprocess as _sp
            mock_run.side_effect = [
                _sp.CalledProcessError(128, ["taskkill"]),     # remembered PID kill fails
                MagicMock(returncode=0, stdout=netstat_out),   # netstat
                MagicMock(returncode=0),                        # taskkill
            ]
            ok, msg = mp.stop()
        assert ok is True
        assert "PID 2222" in msg
        assert mock_run.call_count == 3
        assert mp._last_started_pid is None

    def test_netstat_timeout_reports_failure(self):
        import subprocess as _sp
        with patch("mcp_process.is_running", return_value=True), \
             patch("mcp_process.subprocess.run",
                   side_effect=_sp.TimeoutExpired(["netstat"], 20.0)):
            ok, msg = mp.stop()
        assert ok is False
        assert "Could not determine the server's process" in msg

    def test_no_listening_pid_found_reports_failure(self):
        with patch("mcp_process.is_running", return_value=True), \
             patch("mcp_process.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            ok, msg = mp.stop()
        assert ok is False
        assert "Could not find a process listening" in msg
