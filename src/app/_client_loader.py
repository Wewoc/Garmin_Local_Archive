#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/_client_loader.py

Shared lazy-import helper for clients/ modules. panel_mcp.py and
panel_chat.py each had ~11 identical add_to_path()+import copies, one
per clients/ module they use (v1.7.3.2 dedup) — both now delegate to
_load_client_module() here. Each panel keeps its own named _load_X()
wrapper (grep-able, own docstring per module) — only the body changed.
"""

import importlib

import frozen_paths


def _load_client_module(name: str):
    """Lazy import — adds clients/ to sys.path (frozen_paths.add_to_path()
    is idempotent, no-ops if already present) and imports the named
    module from it. Not done at module top-level so callers stay
    importable before sys.path is fully wired up."""
    root = frozen_paths.scripts_root()
    frozen_paths.add_to_path(root, "clients")
    return importlib.import_module(name)
