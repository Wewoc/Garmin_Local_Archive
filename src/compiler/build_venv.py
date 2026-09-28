#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
build_venv.py

Leaf-Node (compiler/-scoped) — creates/reuses the shared, isolated build
venv used by build.py (Target 2) and build_standalone.py (Target 3).

ensure_build_venv() previously existed as two identical copies (v1.7.3.2
dedup) — only the step-number prefix in the progress print differed
(build.py: 4 total steps, build_standalone.py: 3), now passed in by the
caller via `step`.
"""

import subprocess
import sys
from pathlib import Path

import build_manifest as manifest


def ensure_build_venv(root: Path, step: str) -> Path:
    """Creates (if missing) or reuses the shared, isolated build venv at
    manifest.BUILD_VENV_DIR, installs requirements.txt + PyInstaller into
    it, and returns its python.exe. Replaces the old check_dependencies()
    (garmin_collector-3_experiment, Baustein 27) — that function verified
    dependencies (pyinstaller/keyring/cryptography, or for T3 the
    narrower, drift-prone RUNTIME_DEPS copy) against whatever Python
    happened to be sys.executable, which on this machine also has an
    unrelated project's torch/pandas/scipy installed; PyInstaller was
    sweeping those into the build the moment HIDDEN_IMPORTS_COMMON/
    HIDDEN_IMPORTS_T3_EXTRA started requiring anthropic/openai (see
    PROTOKOLL_experiment.md, Baustein 26). Building against a venv
    containing ONLY requirements.txt's packages makes that structurally
    impossible, regardless of what else gets pip-installed globally on
    this machine later. venv creation itself still uses sys.executable
    (any Python can create a venv — that step never touches
    site-packages). Shared by both build.py (T2) and build_standalone.py
    (T3) — both build from the identical isolated environment; `step` is
    the caller's own progress-print prefix (e.g. "1/4" vs "1/3")."""
    print(f"\n[{step}] Checking build venv ...")
    venv_dir = Path(manifest.BUILD_VENV_DIR)
    venv_python = venv_dir / "Scripts" / "python.exe"

    if not venv_python.exists():
        print(f"  Not found at {venv_dir} — creating ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        print("  ✓ venv created")
    else:
        print(f"  ✓ venv already exists — reusing: {venv_dir}")

    req_file = root.parent / "requirements.txt"
    print(f"  Installing/verifying {req_file} + PyInstaller in venv ...")
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q",
                            "-r", str(req_file)])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q",
                            "pyinstaller"])
    print("  ✓ venv ready")
    return venv_python
