#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
api_raw_probe_config.py

Config for fetch_raw_days.py — paths only, kept separate from the script
code so Windows paths with backslashes can be pasted from Explorer without
touching that file. Same pattern as support-tools/login-probe/probe_config.py.

Paths: enter as r"..." (keep the r prefix!). Paste the Explorer path 1:1.
One rule only: if the copied path ends with a backslash, drop that last
backslash before the closing quote — otherwise Python fails to parse the
file.
"""

# Folder containing garmin_data/ (token, quality log, etc.) — the same
# folder your GLA GUI uses as its archive base dir.
GARMIN_OUTPUT_DIR = r"C:\path\to\your\local_archive"

# Folder containing garmin_api.py, garmin_config.py, garmin_security.py,
# garmin_utils.py. Leave empty ("") if GLA's standard layout applies
# (this script sits under support-tools/, with garmin/ and app/ as
# siblings under the same src/ folder).
GARMIN_REPO_DIR = r"C:\path\to\your\GLA\src\garmin"
