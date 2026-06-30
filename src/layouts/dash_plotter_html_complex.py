#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
dash_plotter_html_complex.py

Facade — routes specialist data dicts to the correct renderer
via a layout registry. No rendering logic lives here.

Layout key (data.get("layout")):
    "explorer"  → layouts/render/explorer.py
    "sleep"     → layouts/render/sleep.py
    None / any  → layouts/render/recovery_context.py  (default)

Adding a new layout:
    1. Create layouts/render/<name>.py with render(data, output_path) -> None
    2. Add one entry to _REGISTRY below
    3. Add to build_manifest.py SHARED_SCRIPTS + SCRIPT_SIGNATURES_BASE

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- No rendering logic — routing only.
- Receives neutral dict from dash_runner, delegates to renderer.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import importlib.util
import sys
from pathlib import Path

# ── Path setup — ensure layouts/ and layouts/render/ are importable ───────────
_LAYOUTS_DIR = Path(__file__).parent
_RENDER_DIR  = _LAYOUTS_DIR / "render"

if str(_LAYOUTS_DIR) not in sys.path:
    sys.path.insert(0, str(_LAYOUTS_DIR))

# Register render/ as a package in sys.modules so sub-imports resolve correctly
# when loaded via importlib.util.spec_from_file_location (e.g. from dash_runner)
if "render" not in sys.modules:
    import types as _types
    _render_pkg = _types.ModuleType("render")
    _render_pkg.__path__ = [str(_RENDER_DIR)]
    _render_pkg.__package__ = "render"
    sys.modules["render"] = _render_pkg


def _load_renderer(name: str):
    """Load a renderer module from layouts/render/<name>.py."""
    path = _RENDER_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"render.{name}", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render


# ══════════════════════════════════════════════════════════════════════════════
#  Render registry — layout key → render function
#  None is the default (fallback) key.
# ══════════════════════════════════════════════════════════════════════════════

_REGISTRY: dict = {
    "explorer": _load_renderer("explorer"),
    "sleep":    _load_renderer("sleep"),
    None:       _load_renderer("recovery_context"),
}


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Route data dict to the registered renderer for its layout type.

    Layout type is determined by data.get("layout"):
        "explorer"      → Explorer dashboard (free metric dropdowns)
        "sleep"         → Sleep Dashboard (HTML/CSS table, no Plotly)
        None / any other → Recovery Context dashboard (fixed metrics, tabs)

    Raises:
        ValueError: if required keys are missing (raised by renderer).
        OSError:    if output file cannot be written (raised by renderer).
    """
    key      = data.get("layout")
    renderer = _REGISTRY.get(key, _REGISTRY[None])
    renderer(data, Path(output_path))
