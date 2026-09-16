#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
build_all.py
Runs both build targets sequentially:
  Target 2 — Garmin_Local_Archive.exe          (Python required)
  Target 3 — Garmin_Local_Archive_Standalone.exe (no Python required)

If Target 2 fails, Target 3 is not started.
Note: Standalone build embeds all dependencies and takes significantly longer.

Plotly pre-build check (v1.6.0.4.4+): ensures layouts/plotly.min.js exists and
matches the pinned PLOTLY_SHA256 (dash_layout_html.PLOTLY_VERSION) before any
test or build step runs. This is the only place in the project that ever
downloads Plotly from the CDN — dash_layout_html.get_plotly_script() is a
pure read at render time (T1/T2/T3 alike), never a network call.
"""

import hashlib
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import build
import build_standalone


class _Tee:
    """Writes every write() to both the real console stream and a log
    file, so `python compiler/build_all.py`'s full output (including
    subprocess output re-printed by run_and_tee() below, and build.py's/
    build_standalone.py's own in-process print()s) survives a build even
    if the terminal itself is closed, cleared, or only partially copied
    — see PROTOKOLL_experiment.md, the T3.1-self-test-log-got-cut-off
    incident that prompted this (garmin_collector-3_experiment,
    2026-09-15). Console write is best-effort (errors="replace" — some
    Windows terminals default to a legacy codepage, e.g. cp1252, that
    cannot render every character PyInstaller or this script prints);
    the log file itself is always clean UTF-8, never lossy."""

    def __init__(self, real_stream, logfile):
        self._real = real_stream
        self._log = logfile

    def write(self, data):
        self._log.write(data)
        try:
            self._real.write(data)
        except UnicodeEncodeError:
            self._real.write(data.encode(
                self._real.encoding or "utf-8", errors="replace"
            ).decode(self._real.encoding or "utf-8", errors="replace"))

    def flush(self):
        self._log.flush()
        self._real.flush()


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def phase(title: str) -> None:
    """Timestamped section header — printed through the Tee above, so it
    lands in both the console and the log file. Mirrors run_tests.ps1's
    own Write-Log timestamp convention (start/end of each phase, not
    every line — PyInstaller's own output is verbose enough already)."""
    print(f"\n{'=' * 55}")
    print(f"  [{_ts()}] {title}")
    print("=" * 55)


def run_and_tee(cmd: list[str]) -> int:
    """subprocess.run() replacement that streams the child process's
    stdout+stderr through print() line by line, so it passes through
    whatever sys.stdout currently is (the _Tee installed in __main__
    below) instead of inheriting the OS file descriptor directly and
    bypassing the log file entirely — subprocess output inherited that
    way is exactly what went missing during the T3.1-self-test incident
    above. Live console streaming is unaffected — lines print as the
    child produces them, not buffered until the process exits.

    PYTHONIOENCODING=utf-8 forced on the child: piping stdout (required
    to capture it at all) means the child no longer sees a real console
    device, so on Windows it can silently fall back to a narrower legacy
    codepage for its OWN internal stdout encoding — a Python subprocess
    (e.g. tests/test_static.py, which prints ─/✓ box-drawing/checkmark
    characters) would then raise UnicodeEncodeError itself, before this
    function ever gets to decode/re-print anything. Same fix
    run_tests.ps1 already applies for its own child processes
    ($env:PYTHONIOENCODING = "utf-8")."""
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=child_env,
    )
    for line in proc.stdout:
        print(line, end="")
    proc.wait()
    return proc.returncode


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ensure_plotly_bundle(root: Path) -> None:
    """
    Ensures layouts/plotly.min.js exists and matches the pinned hash for the
    currently configured PLOTLY_VERSION. Re-downloads from PLOTLY_CDN only if
    missing or mismatched. Aborts the build on download failure or hash
    mismatch after download — never silently proceeds with an unverified file.
    """
    # root + layouts/ alone are not enough: theme.py itself does
    # `import garmin_app_settings as _settings` at import time (reads
    # active_theme), and that module lives under app/, not root — same
    # three-path pattern already fixed in tests/test_dashboard.py
    # (v1.7.1.8). All three needed: layouts/ (dash_layout_html itself),
    # root (theme.py), app/ (garmin_app_settings.py, theme.py's own import).
    sys.path.insert(0, str(root / "app"))
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "layouts"))
    import dash_layout_html as layout_html  # noqa: E402

    local        = root / "layouts" / layout_html.get_plotly_local_filename()
    expected_sha = layout_html.get_plotly_sha256()

    if local.exists() and _sha256_of(local) == expected_sha:
        print(f"  ✓ Plotly {layout_html.get_plotly_version()} present and verified.")
        return

    if local.exists():
        print(f"  ⚠ {local} exists but hash mismatch — re-fetching pinned version.")
    else:
        print(f"  Plotly {layout_html.get_plotly_version()} not found locally — fetching ...")

    try:
        req = urllib.request.Request(
            layout_html.get_plotly_cdn(),
            headers={"User-Agent": "garmin-local-archive-build/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception as exc:
        print(f"  ✗ Failed to download Plotly: {exc}")
        print("  Build aborted — see PLOTLY_CDN in dash_layout_html.py.")
        sys.exit(1)

    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != expected_sha:
        print("  ✗ Downloaded Plotly hash mismatch.")
        print(f"    expected: {expected_sha}")
        print(f"    actual:   {actual_sha}")
        print("  Build aborted — CDN content does not match the pinned hash.")
        print("  If this is an intentional version bump, update PLOTLY_VERSION")
        print("  and PLOTLY_SHA256 in dash_layout_html.py together.")
        sys.exit(1)

    local.write_bytes(data)
    print(f"  ✓ Plotly {layout_html.get_plotly_version()} fetched and verified.")


if __name__ == "__main__":
    _root = Path(__file__).parent.parent   # compiler/ → Root/

    # Timestamped log, tee'd alongside the console — same convention as
    # run_tests.ps1's test_all_log.txt (overwritten each run, not one
    # file per run: a single build_all_log.txt is what NOTES_*/PROTOKOLL
    # entries already point people at, and an ever-growing pile of
    # timestamped files would just have to be cleaned up by hand).
    _logpath = _root / "build_all_log.txt"
    _logfile = _logpath.open("w", encoding="utf-8", newline="")
    _real_stdout, _real_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(_real_stdout, _logfile)
    sys.stderr = _Tee(_real_stderr, _logfile)

    try:
        print(f"build_all.py — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

        phase("Pre-build: verifying Plotly bundle ...")
        ensure_plotly_bundle(_root)

        phase("Pre-build: running test suite ...")

        test_path = _root / "tests" / "test_local.py"
        if run_and_tee([sys.executable, str(test_path)]) != 0:
            print("\n  ✗ Tests failed — build aborted.")
            sys.exit(1)

        test_context_path = _root / "tests" / "test_local_context.py"
        if run_and_tee([sys.executable, str(test_context_path)]) != 0:
            print("\n  ✗ Context tests failed — build aborted.")
            sys.exit(1)

        test_dashboard_path = _root / "tests" / "test_dashboard.py"
        if run_and_tee([sys.executable, str(test_dashboard_path)]) != 0:
            print("\n  ✗ Dashboard tests failed — build aborted.")
            sys.exit(1)

        test_broker_path = _root / "tests" / "test_broker.py"
        if run_and_tee([sys.executable, str(test_broker_path)]) != 0:
            print("\n  ✗ Broker tests failed — build aborted.")
            sys.exit(1)

        test_mcp_path = _root / "tests" / "test_mcp.py"
        if run_and_tee([sys.executable, str(test_mcp_path)]) != 0:
            print("\n  ✗ MCP tests failed — build aborted.")
            sys.exit(1)

        test_static_path = _root / "tests" / "test_static.py"
        if run_and_tee([sys.executable, str(test_static_path)]) != 0:
            print("\n  ✗ Static analysis failed — build aborted.")
            sys.exit(1)

        print(f"\n  ✓ [{_ts()}] All tests passed — starting build.\n")

        phase("Target 2: Garmin_Local_Archive.exe ...")
        build.main()

        phase("Target 3: Standalone + Headless EXEs ...")
        build_standalone.main()

        phase("Post-build: running output validation ...")

        test_build_path = _root / "tests" / "test_build_output.py"
        if run_and_tee([sys.executable, str(test_build_path)]) != 0:
            print("\n  ✗ Build output validation failed — check output above.")
            sys.exit(1)

        print(f"\n  ✓ [{_ts()}] Build output validated successfully.")

        phase("Post-build: Netz 1 — T3.1 self-test (module loadability) ...")

        # Runs the built T3.1 EXE with --self-test, which imports every module
        # listed in build_manifest.SHARED_SCRIPTS inside the frozen process
        # itself (garmin_app_standalone.py::_run_self_test()), before any GUI
        # initialization. Catches modules that are present on disk (verified
        # above by test_build_output) but fail to actually import in the
        # frozen environment — a class of failure static validation cannot see.
        # Real gate, unlike check_cve_whitelist below: returncode aborts the
        # build, T3.1 is not shipped with an artifact that fails its own
        # loadability check.
        t31_exe = _root / "Garmin_Local_Archive_Standalone" / "Garmin_Local_Archive_Standalone.exe"
        if t31_exe.exists():
            if run_and_tee([str(t31_exe), "--self-test"]) != 0:
                print("\n  ✗ T3.1 self-test failed — a module in SHARED_SCRIPTS "
                      "could not be loaded in the frozen process.")
                sys.exit(1)
            print(f"\n  ✓ [{_ts()}] T3.1 self-test passed — all SHARED_SCRIPTS modules load.")
        else:
            print(f"\n  ✗ T3.1 self-test skipped — EXE not found: {t31_exe}")
            sys.exit(1)

        phase("Post-build: running app logic tests ...")

        test_app_path = _root / "tests" / "test_app_logic.py"
        if run_and_tee([sys.executable, str(test_app_path)]) != 0:
            print("\n  ✗ App logic tests failed — check output above.")
            sys.exit(1)

        print(f"\n  ✓ [{_ts()}] App logic tests passed.")

        phase("Post-build: CVE whitelist check (informational only) ...")

        test_cve_path = _root / "tests" / "check_cve_whitelist.py"
        run_and_tee([sys.executable, str(test_cve_path)])
        # No returncode check — this is a report-only step, never a build gate.
        # See NOTES_v1_6_0_4_4.md A1 for the rationale (180° scope change away
        # from any abort/severity-threshold mechanism).

        print(f"\nbuild_all.py done — {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    finally:
        # Runs on every exit path, including sys.exit(1) aborts above
        # (SystemExit still triggers finally) — the log file must capture
        # a failed run just as completely as a successful one; that was
        # the whole point of this Tee.
        sys.stdout, sys.stderr = _real_stdout, _real_stderr
        _logfile.close()
        print(f"  Full log: {_logpath}")
