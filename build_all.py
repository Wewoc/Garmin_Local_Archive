#!/usr/bin/env python3
"""
build_all.py
Runs both build targets sequentially:
  Target 2 — Garmin_Local_Archive.exe          (Python required)
  Target 3 — Garmin_Local_Archive_Standalone.exe (no Python required)

If Target 2 fails, Target 3 is not started.
Note: Standalone build embeds all dependencies and takes significantly longer.
"""

import subprocess
import sys
from pathlib import Path

import build
import build_standalone

if __name__ == "__main__":
    print("=" * 55)
    print("  Pre-build: running test suite ...")
    print("=" * 55)

    test_path = Path(__file__).parent / "tests" / "test_local.py"
    result = subprocess.run([sys.executable, str(test_path)])
    if result.returncode != 0:
        print("\n  ✗ Tests failed — build aborted.")
        sys.exit(1)

    test_context_path = Path(__file__).parent / "tests" / "test_local_context.py"
    result_context = subprocess.run([sys.executable, str(test_context_path)])
    if result_context.returncode != 0:
        print("\n  ✗ Context tests failed — build aborted.")
        sys.exit(1)

    test_dashboard_path = Path(__file__).parent / "tests" / "test_dashboard.py"
    result_dashboard = subprocess.run([sys.executable, str(test_dashboard_path)])
    if result_dashboard.returncode != 0:
        print("\n  ✗ Dashboard tests failed — build aborted.")
        sys.exit(1)

    print("\n  ✓ All tests passed — starting build.\n")
    build.main()
    build_standalone.main()
