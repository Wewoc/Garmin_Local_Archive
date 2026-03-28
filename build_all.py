#!/usr/bin/env python3
"""
build_all.py
Runs both build targets sequentially:
  Target 2 — Garmin_Local_Archive.exe          (Python required)
  Target 3 — Garmin_Local_Archive_Standalone.exe (no Python required)

If Target 2 fails, Target 3 is not started.
Note: Standalone build embeds all dependencies and takes significantly longer.
"""

import build
import build_standalone

if __name__ == "__main__":
    build.main()
    build_standalone.main()
