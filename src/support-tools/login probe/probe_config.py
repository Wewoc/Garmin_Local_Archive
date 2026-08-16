#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
probe_config.py

Config for garmin_login_probe.py — paths and credentials, kept separate
from the script code. Do NOT commit this file with real credentials
filled in (add it to .gitignore if you edit it in place).

Paths: enter as r"..." (keep the r prefix!). Paste the Explorer path
1:1. One rule only: if the copied path ends with a backslash, drop
that last backslash before the closing quote — otherwise Python fails
to parse the file.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  Block A — Test account (plaintext, optional). Leave both empty to use
#  Block B (standard account / existing token) instead.
# ══════════════════════════════════════════════════════════════════════════════

GARMIN_TEST_EMAIL    = ""
GARMIN_TEST_PASSWORD = ""

# ══════════════════════════════════════════════════════════════════════════════
#  Block B — Standard account (existing token / WCM). No credentials here —
#  email and password are read from the same place the GUI stores them
#  (Windows Credential Manager + ~/.garmin_archive_settings.json), via
#  app/garmin_app_settings.py. Requires GARMIN_REPO_DIR below to be set,
#  with "app/" sitting next to "garmin/" under the same "src/" folder —
#  the standard GLA layout.
# ══════════════════════════════════════════════════════════════════════════════

# Folder containing garmin_data/ (token, quality log, etc.)
GARMIN_OUTPUT_DIR = r"C:\path\to\your\local_archive"

# Folder containing garmin_api.py, garmin_config.py, garmin_security.py,
# garmin_utils.py. Leave empty ("") if this script sits directly next
# to those modules (then the script's own folder is used).
GARMIN_REPO_DIR = r"C:\path\to\your\GLA\src\garmin"
