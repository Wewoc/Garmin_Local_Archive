#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
test_static.py — Garmin Local Archive — Static Analysis Suite

Run from the project folder:
    python tests/test_static.py

Covers static code analysis tools — independent of runtime behaviour.
Complements the functional test suites (test_local, test_dashboard, etc.).

Tools covered:
  1. ruff   — linting + style (0 errors required)
  2. bandit — security linting (HIGH severity, 0 errors required)

Prepared for extension:
  3. (reserved) mypy — type checking

No network, no GUI, no API calls.
"""

import subprocess
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from support import check, section, summary  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
#  1. ruff — linting + style
# ══════════════════════════════════════════════════════════════════════════════
section("1. ruff — linting + style")

# Check ruff is available
_ruff_available = False
try:
    result = subprocess.run(
        ["ruff", "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _ruff_available = result.returncode == 0
    _ruff_version   = result.stdout.strip() if _ruff_available else "not found"
except FileNotFoundError:
    _ruff_version = "not found"

check(f"ruff is installed ({_ruff_version})", _ruff_available)

if _ruff_available:
    result = subprocess.run(
        ["ruff", "check", "."],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _ruff_clean = result.returncode == 0

    if not _ruff_clean:
        # Print ruff output so failures are visible
        print()
        for line in result.stdout.splitlines():
            print(f"    {line}")
        print()

    check("ruff check . → 0 errors", _ruff_clean)
else:
    print("  –  ruff check skipped (ruff not installed)")

# ══════════════════════════════════════════════════════════════════════════════
#  2. bandit — security linting (HIGH severity only)
# ══════════════════════════════════════════════════════════════════════════════
section("2. bandit — security linting")

_bandit_available = False
try:
    result = subprocess.run(
        ["bandit", "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _bandit_available = result.returncode == 0
    _bandit_version   = result.stdout.splitlines()[0].strip() if _bandit_available else "not found"
except FileNotFoundError:
    _bandit_version = "not found"

check(f"bandit is installed ({_bandit_version})", _bandit_available)

if _bandit_available:
    result = subprocess.run(
        [
            "bandit", "-r", ".",
            "--severity-level", "high",
            "--confidence-level", "high",
            "--exclude", ".venv,dist,build",
            "-q",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _bandit_clean = result.returncode == 0

    if not _bandit_clean:
        print()
        for line in result.stdout.splitlines():
            print(f"    {line}")
        print()

    check("bandit HIGH severity → 0 issues", _bandit_clean)
else:
    print("  –  bandit check skipped (bandit not installed)")

# ══════════════════════════════════════════════════════════════════════════════
#  3. (reserved) mypy — type checking
# ══════════════════════════════════════════════════════════════════════════════
# section("3. mypy — type checking")
# Uncomment and implement when mypy is added to the toolchain.

# ── Summary ────────────────────────────────────────────────────────────────────
summary()
