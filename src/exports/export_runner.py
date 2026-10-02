#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
exports/export_runner.py

Auto-discovery and orchestration of export adapters — Export Layer
(v1.7.4), same role as dashboards/dash_runner.py for the Dashboard
Layer.

Scans export_adapters/ for all *_adapter.py files. Reads META from each
adapter, orchestrates builds on user request.

Rules:
- No knowledge of fields, data sources, or output formats — those live
  in export_common.py / each adapter.
- No direct file access — delegates entirely to adapters.
- output_dir is supplied by the caller (GUI / daily_update.py), same
  convention as dash_runner.build() — this module does not compute a
  default path itself.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import log_utils

# Flat import, relying on the caller (GUI / daily_update.py) having
# already added clients/ to sys.path at process startup — same
# assumption clients/mcp_server.py's own "import mcp_update" makes
# about its caller, see TODO_export_layer.md's Shared Cache Layer
# section.
import mcp_update


def _load_adapter(path: Path):
    """
    Load an adapter module from path.
    Returns (module, None) on success, (None, error_str) on failure.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:
        return None, str(exc)


def scan(log=None) -> list[dict]:
    """
    Scan export_adapters/ for all *_adapter.py files.

    Returns a list of adapter descriptors:
    [
        {"module": <module>, "id": str, "name": str, "description": str, "extension": str},
        ...
    ]
    Adapters that fail to load (import error) or have missing/malformed
    META are skipped, not silently — skip reason is logged via the
    optional log callback. Mirrors dash_runner.py's scan().

    "id" is the filename stem (e.g. "json_adapter") — a stable,
    settings-safe identifier distinct from "name" (the display label,
    from META, may change independently). Used to persist a saved
    export selection (app/popups/export_data.py's "Save & Add to Daily
    Sync") across runs, since module objects themselves can't be stored
    in settings.json — daily_update.py re-scans and matches by "id".
    """
    log = log_utils.with_timestamp(log)
    if log is None:
        log = lambda msg: None  # noqa: E731

    adapters_dir = Path(__file__).parent / "export_adapters"
    adapters:  list[dict] = []
    skipped:   dict[str, str] = {}

    for path in sorted(adapters_dir.glob("*_adapter.py")):
        mod, err = _load_adapter(path)
        if mod is None:
            skipped[path.name] = err or "unknown load error"
            log(f"  ✗ Adapter skipped: {path.name} — {skipped[path.name]}")
            continue
        meta = getattr(mod, "META", None)
        if not isinstance(meta, dict):
            skipped[path.name] = "missing or malformed META"
            log(f"  ✗ Adapter skipped: {path.name} — {skipped[path.name]}")
            continue
        adapters.append({
            "module":      mod,
            "id":          path.stem,
            "name":        meta.get("name", path.stem),
            "description": meta.get("description", ""),
            "extension":   meta.get("extension", ""),
        })

    if skipped:
        log(f"  scan(): {len(skipped)} adapter(s) skipped — see above")

    return adapters


def build(
    selections: list[tuple],
    date_from: str,
    date_to: str,
    output_dir: Path,
    log=None,
) -> list[dict]:
    """
    Build selected export adapters.

    Args:
        selections:         List of (adapter_module, domains, include_metadata,
                             options) tuples — one entry per adapter, each
                             with its own domain/metadata selection. Same
                             shape as dash_runner.build()'s (specialist,
                             format) pairs, adapted: unlike dashboards, one
                             adapter module already is one fixed output
                             format, so there is no separate per-format
                             fan-out here — domains/include_metadata vary
                             per adapter instead. `options` (v1.7.4,
                             2026-10-01 session) is an adapter-specific
                             keyword-argument dict, passed through unchanged
                             via **options — empty for adapters that take no
                             extra options (e.g. json_adapter), {"delimiter":
                             ...} for csv_adapter. Keeps build() generic
                             instead of giving every adapter a parameter only
                             one of them uses.
        date_from:           Start date ISO string (YYYY-MM-DD).
        date_to:             End date ISO string (YYYY-MM-DD).
        output_dir:          Directory to write output files into.
        log:                 Optional callable(str) for progress messages.

    Returns:
        List of result dicts, one per selection — same shape each
        adapter's own build() returns:
        {"name": str, "file": Path, "success": bool, "error": str}
        ("error" only present if success=False)
    """
    log = log_utils.with_timestamp(log)
    if log is None:
        log = lambda msg: None  # noqa: E731

    log("Syncing Shared Cache ...")
    try:
        sync_result = mcp_update.sync_all()
        log(f"  Sync complete ({sync_result['duration_seconds']:.1f}s)")
    except Exception as exc:
        log(f"  ✗ Sync failed, reading from cache as-is: {exc}")

    results = []
    for mod, domains, include_metadata, options in selections:
        name = getattr(mod, "META", {}).get("name", mod.__name__)
        log(f"Exporting: {name} ...")
        try:
            result = mod.build(date_from, date_to, domains, include_metadata,
                                output_dir, **options)
        except Exception as exc:
            result = {"name": name, "success": False, "error": f"build() failed: {exc}"}

        if result.get("success"):
            log(f"  ✓ {name}: {result['file'].name}")
        else:
            log(f"  ✗ {name}: {result.get('error')}")
        results.append(result)

    return results
