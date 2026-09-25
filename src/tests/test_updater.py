#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_updater.py — Garmin Local Archive — self-updater (v1.7.2.4 T3,
v1.7.2.4-Nacherweiterung auch T2)

Run from the project folder:
    python tests/test_updater.py

No network, no GUI. Covers the four new Leaf-Node modules built for
the self-updater: version.py (is_newer), frozen_paths.py
(is_t3_standalone, is_t2_standard), process_status.py (lock files + MCP
probe), and updater.py (asset resolution + download/verify/extract).
Focus is on edge cases — malformed input, stale/corrupt state, failure
paths — not just the happy path, since every one of these functions
guards a step that can auto-apply a file-system change without a human
looking at it first (see changelog/anchor_delivery_v1-7-2-4-updater-*.md).

Uses real files, real hashes, real zip archives, and real sockets via
temp directories and file:// URLs — no mocks — matching how these
modules were originally verified during the Bauauftrag steps. Cleans
up after itself — leaves no files behind.
"""

import hashlib
import socket
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import pathname2url

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "garmin"))

import version
import frozen_paths
import process_status
import updater

sys.path.insert(0, str(Path(__file__).parent))
from support import check, section, summary

# ── Temp dir ───────────────────────────────────────────────────────────────────
_TMPDIR = Path(tempfile.mkdtemp(prefix="garmin_updatertest_"))


def _file_url(p: Path) -> str:
    return "file:" + pathname2url(str(p))


# ══════════════════════════════════════════════════════════════════════════════
#  1. version.py — is_newer()
# ══════════════════════════════════════════════════════════════════════════════
section("1. version.py — is_newer()")

check("strictly newer -> True",
      version.is_newer("1.7.2.4", "1.7.2.3") is True)
check("same version -> False",
      version.is_newer("1.7.2.3", "1.7.2.3") is False)
check("older version -> False",
      version.is_newer("1.7.2.2", "1.7.2.3") is False)
check("'v' prefix on latest only -> still compares correctly",
      version.is_newer("v1.7.2.4", "1.7.2.3") is True)
check("'v' prefix on both -> still compares correctly",
      version.is_newer("v1.7.2.4", "v1.7.2.3") is True)
check("'V' (uppercase) prefix -> still stripped",
      version.is_newer("V1.7.2.4", "1.7.2.3") is True)
check("non-numeric segment in latest -> False, no crash",
      version.is_newer("garbage", "1.7.2.3") is False)
check("non-numeric segment in current -> False, no crash",
      version.is_newer("1.7.2.4", "garbage") is False)
check("empty string -> False, no crash",
      version.is_newer("", "1.7.2.3") is False)
check("double dot (empty segment) -> False, no crash",
      version.is_newer("1..2", "1.7.2.3") is False)
check("longer tuple, same prefix, extra trailing component -> newer",
      version.is_newer("1.7.2.3.1", "1.7.2.3") is True)
check("shorter tuple, same prefix -> not newer (missing trailing component)",
      version.is_newer("1.7.2", "1.7.2.3") is False)
check("leading whitespace in a segment -> tolerated (int() strips it)",
      version.is_newer(" 1.7.2.4", "1.7.2.3") is True)
check("trailing whitespace in a segment -> tolerated (int() strips it)",
      version.is_newer("1.7.2.4 ", "1.7.2.3") is True)
check("three-component vs four-component current -> compares as given",
      version.is_newer("2.0.0", "1.7.2.3") is True)


# ══════════════════════════════════════════════════════════════════════════════
#  2. frozen_paths.py — is_t3_standalone() / is_t2_standard()
# ══════════════════════════════════════════════════════════════════════════════
section("2. frozen_paths.py — is_t3_standalone() / is_t2_standard()")

check("not frozen (dev/T1) -> False",
      frozen_paths.is_t3_standalone() is False)
check("is_t2_standard() not frozen, no reference_file -> False (no guessing)",
      frozen_paths.is_t2_standard() is False)


def _with_frozen(exe_dir: Path, siblings: list[str], fn):
    """Simulates a frozen build: sets sys.frozen/sys.executable for the
    duration of fn(), restores both afterward regardless of outcome."""
    exe = exe_dir / "Garmin_Local_Archive_Standalone.exe"
    exe.write_text("x")
    for name in siblings:
        (exe_dir / name).write_text("x")
    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)
    old_exe = sys.executable
    sys.frozen = True
    sys.executable = str(exe)
    try:
        return fn()
    finally:
        if had_frozen:
            sys.frozen = old_frozen
        else:
            del sys.frozen
        sys.executable = old_exe


_t3_case1 = _TMPDIR / "t3_case1"; _t3_case1.mkdir()
check("frozen, no siblings at all -> False",
      _with_frozen(_t3_case1, [], frozen_paths.is_t3_standalone) is False)

_t3_case2 = _TMPDIR / "t3_case2"; _t3_case2.mkdir()
check("frozen, only daily_update.exe (no mcp_server.exe) -> False",
      _with_frozen(_t3_case2, ["daily_update.exe"],
                   frozen_paths.is_t3_standalone) is False)

_t3_case3 = _TMPDIR / "t3_case3"; _t3_case3.mkdir()
check("frozen, only mcp_server.exe (no daily_update.exe) -> False",
      _with_frozen(_t3_case3, ["mcp_server.exe"],
                   frozen_paths.is_t3_standalone) is False)

_t3_case4 = _TMPDIR / "t3_case4"; _t3_case4.mkdir()
check("frozen, both siblings present (real T3) -> True",
      _with_frozen(_t3_case4, ["daily_update.exe", "mcp_server.exe"],
                   frozen_paths.is_t3_standalone) is True)


def _with_frozen_t2(exe_dir: Path, has_dash_runner: bool,
                     siblings: list[str], fn):
    """v1.7.2.4-Nacherweiterung — simulates a frozen T2 GUI EXE (no
    _Standalone suffix), optionally with scripts/dashboards/
    dash_runner.py (the canonical T2 marker, same as scripts_root()
    uses) and/or contradictory T3 siblings, to check precedence."""
    exe = exe_dir / "Garmin_Local_Archive.exe"
    exe.write_text("x")
    if has_dash_runner:
        d = exe_dir / "scripts" / "dashboards"
        d.mkdir(parents=True, exist_ok=True)
        (d / "dash_runner.py").write_text("x")
    for name in siblings:
        (exe_dir / name).write_text("x")
    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)
    old_exe = sys.executable
    sys.frozen = True
    sys.executable = str(exe)
    try:
        return fn()
    finally:
        if had_frozen:
            sys.frozen = old_frozen
        else:
            del sys.frozen
        sys.executable = old_exe


_t2_case1 = _TMPDIR / "t2_case1"; _t2_case1.mkdir()
check("frozen T2-GUI (scripts/dashboards/dash_runner.py present, no T3 "
      "siblings) -> is_t2_standard() True",
      _with_frozen_t2(_t2_case1, True, [], frozen_paths.is_t2_standard)
      is True)

_t2_case2 = _TMPDIR / "t2_case2"; _t2_case2.mkdir()
check("frozen, dash_runner.py present but T3 siblings also present "
      "(is_t3_standalone() wins) -> is_t2_standard() False",
      _with_frozen_t2(_t2_case2, True,
                       ["daily_update.exe", "mcp_server.exe"],
                       frozen_paths.is_t2_standard) is False)

_t2_case3 = _TMPDIR / "t2_case3"; _t2_case3.mkdir()
check("frozen but no scripts/dashboards/dash_runner.py at all -> "
      "is_t2_standard() False (no guessing)",
      _with_frozen_t2(_t2_case3, False, [], frozen_paths.is_t2_standard)
      is False)

_t2_case4 = _TMPDIR / "t2_case4"; _t2_case4.mkdir()
_t2_c4_scheduler = _t2_case4 / "scheduler"; _t2_c4_scheduler.mkdir()
_t2_c4_ref = _t2_c4_scheduler / "daily_update.py"; _t2_c4_ref.write_text("x")
(_t2_case4 / "Garmin_Local_Archive.exe").write_text("x")
check("not frozen, reference_file = scheduler/daily_update.py with a "
      "Garmin_Local_Archive.exe sibling two levels up (real T2 "
      "daily_update.py run) -> True",
      frozen_paths.is_t2_standard(str(_t2_c4_ref)) is True)

_t2_case5 = _TMPDIR / "t2_case5"; _t2_case5.mkdir()
_t2_c5_scheduler = _t2_case5 / "scheduler"; _t2_c5_scheduler.mkdir()
_t2_c5_ref = _t2_c5_scheduler / "daily_update.py"; _t2_c5_ref.write_text("x")
check("not frozen, reference_file without the EXE sibling (T1 dev "
      "checkout) -> False",
      frozen_paths.is_t2_standard(str(_t2_c5_ref)) is False)


# ══════════════════════════════════════════════════════════════════════════════
#  3. process_status.py — lock file lifecycle
# ══════════════════════════════════════════════════════════════════════════════
section("3. process_status.py — lock file lifecycle")

import os as _os
_orig_home = Path.home


def _fake_home():
    return _TMPDIR / "home"


(_TMPDIR / "home").mkdir(exist_ok=True)
Path.home = staticmethod(_fake_home)  # redirect ~ for this section only

try:
    check("is_running() with no lock file at all -> False",
          process_status.is_running("nonexistent_proc") is False)
    check("get_pid() with no lock file at all -> None",
          process_status.get_pid("nonexistent_proc") is None)

    process_status.write_lock("self_test")
    check("write_lock() then is_running() on own (alive) PID -> True",
          process_status.is_running("self_test") is True)
    check("get_pid() returns our own real PID",
          process_status.get_pid("self_test") == _os.getpid())

    process_status.clear_lock("self_test")
    check("clear_lock() then is_running() -> False",
          process_status.is_running("self_test") is False)
    try:
        process_status.clear_lock("self_test")
        _no_raise = True
    except Exception:
        _no_raise = False
    check("clear_lock() on an already-missing file -> no exception",
          _no_raise)

    stale_path = process_status._lock_path("stale_proc")
    stale_path.write_text("999999")  # astronomically unlikely to be a real PID
    check("stale lock file with a long-dead PID -> is_running() False, "
          "not a false positive",
          process_status.is_running("stale_proc") is False)
    check("stale lock file with a long-dead PID -> get_pid() None",
          process_status.get_pid("stale_proc") is None)
    stale_path.unlink(missing_ok=True)

    corrupt_path = process_status._lock_path("corrupt_proc")
    corrupt_path.write_text("not-a-pid")
    check("corrupt (non-numeric) lock file content -> is_running() False, "
          "no crash",
          process_status.is_running("corrupt_proc") is False)
    corrupt_path.unlink(missing_ok=True)

    empty_path = process_status._lock_path("empty_proc")
    empty_path.write_text("")
    check("empty lock file content -> is_running() False, no crash",
          process_status.is_running("empty_proc") is False)
    empty_path.unlink(missing_ok=True)
finally:
    Path.home = _orig_home


# ══════════════════════════════════════════════════════════════════════════════
#  4. process_status.py — is_mcp_running() (real TCP probe)
# ══════════════════════════════════════════════════════════════════════════════
section("4. process_status.py — is_mcp_running() (real TCP probe)")

import garmin_config as _cfg

check("nothing listening on MCP_HTTP_PORT -> False",
      process_status.is_mcp_running() is False)

_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    _srv.bind(("127.0.0.1", _cfg.MCP_HTTP_PORT))
    _srv.listen(1)
    check("a real listener on MCP_HTTP_PORT -> True",
          process_status.is_mcp_running() is True)
finally:
    _srv.close()

check("listener closed again -> back to False",
      process_status.is_mcp_running() is False)


# ══════════════════════════════════════════════════════════════════════════════
#  5. updater.py — resolve_release_asset()
# ══════════════════════════════════════════════════════════════════════════════
section("5. updater.py — resolve_release_asset()")

_release = {
    "tag_name": "v1.7.2.4",
    "assets": [
        {"name": updater.T2_ZIP_ASSET_NAME,
         "browser_download_url": "https://example.com/t2.zip"},
        {"name": updater.T2_ZIP_CHECKSUM_ASSET_NAME,
         "browser_download_url": "https://example.com/t2.zip.sha256"},
        {"name": updater.T3_ZIP_ASSET_NAME,
         "browser_download_url": "https://example.com/t3.zip"},
        {"name": updater.T3_ZIP_CHECKSUM_ASSET_NAME,
         "browser_download_url": "https://example.com/t3.zip.sha256"},
    ],
}

check("finds the T3 ZIP, not the T2 ZIP sitting next to it",
      updater.resolve_release_asset(_release, updater.T3_ZIP_ASSET_NAME)
      == "https://example.com/t3.zip")
check("finds the T3 checksum asset",
      updater.resolve_release_asset(_release, updater.T3_ZIP_CHECKSUM_ASSET_NAME)
      == "https://example.com/t3.zip.sha256")
check("v1.7.2.4-Nacherweiterung: finds the T2 ZIP, not the T3 ZIP "
      "sitting next to it",
      updater.resolve_release_asset(_release, updater.T2_ZIP_ASSET_NAME)
      == "https://example.com/t2.zip")
check("v1.7.2.4-Nacherweiterung: finds the T2 checksum asset",
      updater.resolve_release_asset(_release, updater.T2_ZIP_CHECKSUM_ASSET_NAME)
      == "https://example.com/t2.zip.sha256")
check("asset name not present at all -> None, no crash",
      updater.resolve_release_asset(_release, "does_not_exist.zip") is None)
check("release JSON with no 'assets' key at all -> None, no crash",
      updater.resolve_release_asset({"tag_name": "v1.7.2.4"},
                                     updater.T3_ZIP_ASSET_NAME) is None)
check("empty assets list -> None, no crash",
      updater.resolve_release_asset({"assets": []},
                                     updater.T3_ZIP_ASSET_NAME) is None)
check("asset present but missing browser_download_url -> None, no crash",
      updater.resolve_release_asset(
          {"assets": [{"name": updater.T3_ZIP_ASSET_NAME}]},
          updater.T3_ZIP_ASSET_NAME) is None)


# ══════════════════════════════════════════════════════════════════════════════
#  6. updater.py — prepare_update() (real files, real hashes, real zips)
# ══════════════════════════════════════════════════════════════════════════════
section("6. updater.py — prepare_update()")

_server_dir = _TMPDIR / "server"; _server_dir.mkdir()


def _make_release_zip(content_suffix: str = "") -> Path:
    zp = _server_dir / f"release{content_suffix}.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("Garmin_Local_Archive_Standalone.exe", f"exe{content_suffix}")
        zf.writestr("_internal/dummy.dll", f"dll{content_suffix}")
        zf.writestr("updater_helper.ps1", "# fake helper")
    return zp


def _checksum_file_for(zp: Path, *, corrupt: bool = False,
                        with_filename_suffix: bool = False) -> Path:
    digest = "0" * 64 if corrupt else hashlib.sha256(zp.read_bytes()).hexdigest()
    text = f"{digest}  {zp.name}" if with_filename_suffix else digest
    cp = _server_dir / (zp.name + ".sha256")
    cp.write_text(text)
    return cp


# -- success case --------------------------------------------------------------
_zip1 = _make_release_zip("_a")
_checksum1 = _checksum_file_for(_zip1)
_install1 = _TMPDIR / "install1"; _install1.mkdir()
_result1 = updater.prepare_update(
    _install1, _file_url(_zip1), _file_url(_checksum1))
check("success: returns the _update_pending dir",
      _result1 == _install1 / updater.UPDATE_PENDING_DIRNAME)
check("success: GUI exe extracted correctly",
      (_result1 / "Garmin_Local_Archive_Standalone.exe").read_text() == "exe_a")
check("success: nested _internal/ file extracted correctly",
      (_result1 / "_internal" / "dummy.dll").read_text() == "dll_a")
check("success: updater_helper.ps1 extracted correctly",
      (_result1 / "updater_helper.ps1").exists())

# -- checksum file with a "hash  filename" suffix (alternate format) ----------
_zip1b = _make_release_zip("_a2")
_checksum1b = _checksum_file_for(_zip1b, with_filename_suffix=True)
_install1b = _TMPDIR / "install1b"; _install1b.mkdir()
_result1b = updater.prepare_update(
    _install1b, _file_url(_zip1b), _file_url(_checksum1b))
check("checksum file with 'hash  filename' format is also accepted",
      (_result1b / "Garmin_Local_Archive_Standalone.exe").exists())

# -- missing checksum_url: fail closed, nothing left on disk ------------------
_zip2 = _make_release_zip("_b")
_install2 = _TMPDIR / "install2"; _install2.mkdir()
try:
    updater.prepare_update(_install2, _file_url(_zip2), None)
    _raised2 = False
except RuntimeError:
    _raised2 = True
check("missing checksum_url -> RuntimeError raised (fail closed)", _raised2)
check("missing checksum_url -> pending dir cleaned up, nothing left",
      not (_install2 / updater.UPDATE_PENDING_DIRNAME).exists())

# -- wrong checksum: fail closed, nothing left on disk -------------------------
_zip3 = _make_release_zip("_c")
_checksum3 = _checksum_file_for(_zip3, corrupt=True)
_install3 = _TMPDIR / "install3"; _install3.mkdir()
try:
    updater.prepare_update(_install3, _file_url(_zip3), _file_url(_checksum3))
    _raised3 = False
except RuntimeError:
    _raised3 = True
check("checksum mismatch -> RuntimeError raised (fail closed)", _raised3)
check("checksum mismatch -> pending dir cleaned up, nothing left",
      not (_install3 / updater.UPDATE_PENDING_DIRNAME).exists())

# -- downloaded file is not a valid zip ----------------------------------------
_notzip = _server_dir / "not_a_zip.zip"
_notzip.write_text("this is not a zip file")
_checksum4 = _checksum_file_for(_notzip)
_install4 = _TMPDIR / "install4"; _install4.mkdir()
try:
    updater.prepare_update(_install4, _file_url(_notzip), _file_url(_checksum4))
    _raised4 = False
except RuntimeError:
    _raised4 = True
check("downloaded content is not a valid ZIP -> RuntimeError raised", _raised4)
check("invalid ZIP -> pending dir cleaned up, nothing left",
      not (_install4 / updater.UPDATE_PENDING_DIRNAME).exists())

# -- network/URL failure (unreachable file:// path) ----------------------------
_install5 = _TMPDIR / "install5"; _install5.mkdir()
_missing_url = _file_url(_server_dir / "does_not_exist.zip")
_missing_checksum_url = _file_url(_server_dir / "does_not_exist.zip.sha256")
try:
    updater.prepare_update(_install5, _missing_url, _missing_checksum_url)
    _raised5 = False
except RuntimeError:
    _raised5 = True
check("unreachable download URL -> RuntimeError raised, not a crash", _raised5)
check("unreachable download URL -> pending dir cleaned up",
      not (_install5 / updater.UPDATE_PENDING_DIRNAME).exists())

# -- stale leftover _update_pending/ from a previous crashed attempt ----------
_zip6 = _make_release_zip("_d")
_checksum6 = _checksum_file_for(_zip6)
_install6 = _TMPDIR / "install6"
_stale_pending = _install6 / updater.UPDATE_PENDING_DIRNAME
_stale_pending.mkdir(parents=True)
(_stale_pending / "leftover_garbage.txt").write_text("junk from a crashed run")
_result6 = updater.prepare_update(
    _install6, _file_url(_zip6), _file_url(_checksum6))
check("stale leftover _update_pending/ is wiped before a new attempt",
      not (_result6 / "leftover_garbage.txt").exists())
check("fresh extraction still succeeds after cleaning a stale leftover",
      (_result6 / "Garmin_Local_Archive_Standalone.exe").read_text() == "exe_d")


# ══════════════════════════════════════════════════════════════════════════════
#  7. updater.py — write_success_flag() (v1.7.2.4.1 startup handshake)
# ══════════════════════════════════════════════════════════════════════════════
section("7. updater.py — write_success_flag()")

check("UPDATE_SUCCESS_FLAG_NAME matches updater_helper.ps1's hardcoded "
      "literal (same string duplicated across Python/PowerShell, not "
      "parametrised, same as _update_pending/_update_backup)",
      updater.UPDATE_SUCCESS_FLAG_NAME == "_update_success.flag")

_flag_install = _TMPDIR / "flag_install"; _flag_install.mkdir()
_flag_path = _flag_install / updater.UPDATE_SUCCESS_FLAG_NAME
updater.write_success_flag(_flag_install)
check("write_success_flag() creates the flag file at exe_dir",
      _flag_path.exists())
check("write_success_flag() creates it empty (only existence matters)",
      _flag_path.read_text() == "")

updater.write_success_flag(_flag_install)
check("calling it again (flag already present) does not raise",
      _flag_path.exists())

_missing_dir = _TMPDIR / "flag_install_does_not_exist" / "nested"
try:
    updater.write_success_flag(_missing_dir)
    _flag_no_raise = True
except Exception:
    _flag_no_raise = False
check("exe_dir does not exist -> swallowed (OSError), no exception "
      "(best-effort, must never block app startup)",
      _flag_no_raise)


# ══════════════════════════════════════════════════════════════════════════════
#  8. updater_helper.ps1 — startup handshake + auto-rollback (v1.7.2.4.1,
#     real powershell.exe subprocess, first automated test of this script)
# ══════════════════════════════════════════════════════════════════════════════
section("8. updater_helper.ps1 — startup handshake + auto-rollback")

import subprocess

_PS1_HELPER = _ROOT / "updater_helper.ps1"
_HELPER_LOG = _TMPDIR / "helper_gui_launches.log"


def _run_helper(exe_dir: Path, pending_dir: Path, gui_exe_name: str,
                 timeout_s: int = 2, max_attempts: int = 1):
    """Runs the real updater_helper.ps1 against a fake ExeDir/PendingDir.
    stdin=DEVNULL so a failure path's Read-Host can never block the test.
    max_attempts defaults to 1 (not the script's own default of 3) so
    existing single-shot success/rollback checks below don't have to
    account for retries - the retry behaviour itself gets its own tests."""
    return subprocess.run(
        ["powershell.exe", "-ExecutionPolicy", "Bypass",
         "-File", str(_PS1_HELPER),
         "-ExeDir", str(exe_dir),
         "-PendingDir", str(pending_dir),
         "-RestartGui",
         "-GuiExeName", gui_exe_name,
         "-SuccessTimeoutSeconds", str(timeout_s),
         "-MaxLaunchAttempts", str(max_attempts)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        timeout=(timeout_s * max_attempts) + 30)


# -- success path: the "new GUI" writes the flag right away -------------------
_h_exe1 = _TMPDIR / "helper_exe1"; _h_exe1.mkdir()
(_h_exe1 / "old_file.txt").write_text("old content")
_h_pending1 = _TMPDIR / "helper_pending1"; _h_pending1.mkdir()
(_h_pending1 / "new_file.txt").write_text("new content")
(_h_pending1 / "fake_gui.bat").write_text(
    "@echo off\r\n"
    'echo. > "%~dp0_update_success.flag"\r\n')

_res_ok = _run_helper(_h_exe1, _h_pending1, "fake_gui.bat")
check("success path: exit code 0",
      _res_ok.returncode == 0)
check("success path: stdout reports success",
      "Update applied successfully." in _res_ok.stdout)
check("success path: new file swapped into ExeDir",
      (_h_exe1 / "new_file.txt").exists())
check("success path: old file moved into _update_backup/",
      (_h_exe1 / "_update_backup" / "old_file.txt").exists())
check("success path: success flag consumed (deleted again)",
      not (_h_exe1 / "_update_success.flag").exists())

# -- rollback path: the "new GUI" never writes the flag, and hangs ------------
# Same fake_gui.bat filename on both sides of the swap (old and new versions
# share the GUI EXE's name across an update) - content differs so the test
# can tell, via a shared log file outside ExeDir/PendingDir, which one a
# given Start-Process call actually launched.
#
# The "new" one hangs (ping, not an instant exit) rather than just skipping
# the flag write - cmd.exe keeps its own file handle on fake_gui.bat open
# for as long as the batch script is still running, which reproduces the
# real bug found on 2026-09-24: a real build with a missing DLL doesn't
# crash cleanly, it hangs behind a native Windows error dialog, and the
# still-running process (and its open handle on its own EXE) blocks the
# rollback's Move-Item unless the helper kills it first. Without that fix,
# this exact test reproduces the "cannot create a file that already
# exists" failure a plain instant-exit fake GUI would never trigger.
_h_exe2 = _TMPDIR / "helper_exe2"; _h_exe2.mkdir()
(_h_exe2 / "fake_gui.bat").write_text(
    f'@echo off\r\necho old_launched >> "{_HELPER_LOG}"\r\n')
(_h_exe2 / "old_marker.txt").write_text("old content")
_h_pending2 = _TMPDIR / "helper_pending2"; _h_pending2.mkdir()
(_h_pending2 / "fake_gui.bat").write_text(
    f'@echo off\r\necho new_launched >> "{_HELPER_LOG}"\r\nping -n 60 127.0.0.1 >nul\r\n')
(_h_pending2 / "new_marker.txt").write_text("new content")

_res_bad = _run_helper(_h_exe2, _h_pending2, "fake_gui.bat")
check("rollback path: non-zero exit code",
      _res_bad.returncode != 0)
check("rollback path: stdout reports failure, not success",
      "UPDATE FAILED" in _res_bad.stdout
      and "Update applied successfully." not in _res_bad.stdout)
check("rollback path: stdout names the actual attempt count/timeout used, "
      "not a hardcoded default - the message stayed in sync with the "
      "new params",
      "after 1 attempt(s) (2 seconds each)" in _res_bad.stdout)
check("rollback path: the new (broken) version's marker file is gone from "
      "ExeDir after rollback",
      not (_h_exe2 / "new_marker.txt").exists())
check("rollback path: the old version's marker file is back in ExeDir",
      (_h_exe2 / "old_marker.txt").exists())
check("rollback path: old fake_gui.bat content restored in ExeDir "
      "(not the new one)",
      "old_launched" in (_h_exe2 / "fake_gui.bat").read_text())
def _wait_for_log_lines(path: Path, expected: list[str], timeout_s: float = 5):
    """Start-Process launches detached, non-waited-on child processes - the
    parent script (and this test's subprocess.run call) can return before a
    child cmd.exe has actually flushed its echo to disk. Poll briefly
    instead of asserting on the very first read."""
    import time
    deadline = time.monotonic() + timeout_s
    lines = []
    while time.monotonic() < deadline:
        if path.exists():
            lines = path.read_text().split()
            if lines == expected:
                return lines
        time.sleep(0.2)
    return lines


check("rollback path: both the new (broken) and the restored old GUI were "
      "actually launched, in that order",
      _wait_for_log_lines(_HELPER_LOG, ["new_launched", "old_launched"])
      == ["new_launched", "old_launched"])

# -- retry path: fails once, succeeds on the 2nd attempt (v1.7.2.4.1, ------
# Baustein: retry against a real, intermittent onefile-bootloader failure,
# 2026-09-25) - the fake GUI here fails fast (no flag, clean exit) instead
# of hanging, since a real onefile crash observed on 2026-09-25 also
# exited fast (native error dialog closed almost immediately), not a hang.
_h_exe4 = _TMPDIR / "helper_exe4"; _h_exe4.mkdir()
_h_pending4 = _TMPDIR / "helper_pending4"; _h_pending4.mkdir()
(_h_pending4 / "fake_gui.bat").write_text(
    '@echo off\r\n'
    'set /a n=0\r\n'
    'if exist "%~dp0_attempt_counter.txt" set /p n=<"%~dp0_attempt_counter.txt"\r\n'
    'set /a n=%n%+1\r\n'
    'echo %n% > "%~dp0_attempt_counter.txt"\r\n'
    'if %n% GEQ 2 echo. > "%~dp0_update_success.flag"\r\n')

_res_retry = _run_helper(_h_exe4, _h_pending4, "fake_gui.bat",
                          timeout_s=5, max_attempts=3)
check("retry path: exit code 0 (eventually succeeded)",
      _res_retry.returncode == 0)
check("retry path: stdout reports success, not failure",
      "Update applied successfully." in _res_retry.stdout)
check("retry path: stdout logged the first failed attempt before retrying",
      "Launch attempt 1 of 3 did not signal success - retrying"
      in _res_retry.stdout)
check("retry path: flag consumed after the successful 2nd attempt",
      not (_h_exe4 / "_update_success.flag").exists())
check("retry path: the fake GUI actually ran twice (counter proves it, "
      "not just a lucky first-attempt timing coincidence)",
      (_h_exe4 / "_attempt_counter.txt").read_text().strip() == "2")

# -- retry path: exhausts every attempt, still rolls back ---------------------
_h_exe5 = _TMPDIR / "helper_exe5"; _h_exe5.mkdir()
(_h_exe5 / "fake_gui.bat").write_text(
    f'@echo off\r\necho old_launched >> "{_HELPER_LOG}"\r\n')
(_h_exe5 / "old_marker.txt").write_text("old content")
_h_pending5 = _TMPDIR / "helper_pending5"; _h_pending5.mkdir()
(_h_pending5 / "fake_gui.bat").write_text(
    f'@echo off\r\necho new_launched >> "{_HELPER_LOG}"\r\n')
(_h_pending5 / "new_marker.txt").write_text("new content")

_HELPER_LOG.unlink(missing_ok=True)
_res_exhausted = _run_helper(_h_exe5, _h_pending5, "fake_gui.bat",
                              timeout_s=1, max_attempts=3)
check("retry-exhausted path: non-zero exit code",
      _res_exhausted.returncode != 0)
check("retry-exhausted path: stdout names the full attempt count",
      "after 3 attempt(s) (1 seconds each)" in _res_exhausted.stdout)
check("retry-exhausted path: the fake new GUI was actually launched 3 "
      "times before giving up, then the old one once more",
      _wait_for_log_lines(
          _HELPER_LOG,
          ["new_launched", "new_launched", "new_launched", "old_launched"])
      == ["new_launched", "new_launched", "new_launched", "old_launched"])
check("retry-exhausted path: old version fully restored in ExeDir",
      (_h_exe5 / "old_marker.txt").exists()
      and not (_h_exe5 / "new_marker.txt").exists())

# -- lock file: a second concurrent run is refused, not a silent collision ----
_h_exe3 = _TMPDIR / "helper_exe3"; _h_exe3.mkdir()
(_h_exe3 / "_update_helper.lock").write_text(str(_os.getpid()))
_h_pending3 = _TMPDIR / "helper_pending3"; _h_pending3.mkdir()
_res_locked = _run_helper(_h_exe3, _h_pending3, "fake_gui.bat")
check("existing lock file with a live PID (this test process) -> refused, "
      "non-zero exit",
      _res_locked.returncode != 0
      and "already in progress" in _res_locked.stdout)


# ── Cleanup ────────────────────────────────────────────────────────────────────
import shutil
shutil.rmtree(_TMPDIR, ignore_errors=True)

# ── Summary ───────────────────────────────────────────────────────────────────
summary()
