#!/usr/bin/env python3
"""
dash_runner.py

Auto-discovery and orchestration of dashboard specialists.

Scans dashboards/ for all *_dash.py files at startup.
Reads META from each specialist, builds the format matrix for the GUI,
and orchestrates the build on user request.

Rules:
- No knowledge of fields, data sources, or output formats.
- No direct file access — delegates entirely to specialists and plotters.
- One call to specialist.build() per specialist, regardless of how many
  formats are selected. Data is fetched once, rendered multiple times.
"""

import importlib.util
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Plotter registry — maps format key to plotter module
#  Add new plotters here as layouts/ grows.
# ══════════════════════════════════════════════════════════════════════════════

def _load_plotters() -> dict:
    """
    Import registered plotters lazily.
    Returns dict of {format_key: plotter_module}.
    Only formats with an available plotter module are included.
    """
    plotters = {}
    # __file__ points into _MEIPASS temp in frozen builds — resolve via sys.path instead
    _here = Path(__file__).parent
    layouts_dir = _here.parent / "layouts"
    if not layouts_dir.exists():
        for _p in sys.path:
            _candidate = Path(_p).parent / "layouts"
            if _candidate.exists():
                layouts_dir = _candidate
                break

    plotter_map = {
        "html":         "dash_plotter_html",
        "html_complex": "dash_plotter_html_complex",
        "html_mobile":  "dash_plotter_html_mobile",
        "excel":        "dash_plotter_excel",
        "json":         "dash_plotter_json",
        "pdf":          "dash_plotter_pdf",
        "word":         "dash_plotter_word",
    }

    for fmt, module_name in plotter_map.items():
        mod_path = layouts_dir / f"{module_name}.py"
        if mod_path.exists():
            spec = importlib.util.spec_from_file_location(module_name, mod_path)
            mod  = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                plotters[fmt] = mod
            except Exception as exc:
                plotters[f"{fmt}_err"] = str(exc)  # surfaced in build()

    return plotters


# ══════════════════════════════════════════════════════════════════════════════
#  Specialist discovery
# ══════════════════════════════════════════════════════════════════════════════

def _load_specialist(path: Path):
    """Load a specialist module from path. Returns module or None on failure."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def display_label(fmt: str) -> str:
    """Return human-readable format label for GUI display."""
    if fmt == "html_complex":
        return "html"
    if fmt == "html_mobile":
        return "mobile"
    return fmt


def scan() -> list[dict]:
    """
    Scan dashboards/ for all *_dash.py files.
    Returns a list of specialist descriptors:
    [
        {
            "module":   <module>,
            "name":     str,
            "description": str,
            "source":   str,
            "formats":  {"html": "file.html", "excel": "file.xlsx", ...},
        },
        ...
    ]
    Specialists with missing or malformed META are silently skipped.
    """
    dashboards_dir = Path(__file__).parent
    plotters       = _load_plotters()
    specialists    = []

    for path in sorted(dashboards_dir.glob("*_dash.py")):
        if path.name == "dash_runner.py":
            continue
        mod = _load_specialist(path)
        if mod is None:
            continue
        meta = getattr(mod, "META", None)
        if not isinstance(meta, dict):
            continue
        # Only expose formats that have a registered plotter
        available_formats = {
            fmt: filename
            for fmt, filename in meta.get("formats", {}).items()
            if fmt in plotters
        }
        # Normalise display key — html_complex shows as "html" in the GUI
        available_formats = {
            ("html" if fmt == "html_complex" else fmt): filename
            for fmt, filename in available_formats.items()
        }
        if not available_formats:
            continue
        specialists.append({
            "module":      mod,
            "name":        meta.get("name", path.stem),
            "description": meta.get("description", ""),
            "source":      meta.get("source", ""),
            "formats":     available_formats,
        })

    return specialists


# ══════════════════════════════════════════════════════════════════════════════
#  Build orchestration
# ══════════════════════════════════════════════════════════════════════════════

def build(
    selections: list[tuple],
    date_from: str,
    date_to: str,
    settings: dict,
    output_dir: Path,
    log=None,
) -> list[dict]:
    """
    Build selected dashboards.

    Args:
        selections:  List of (specialist_module, format_key) pairs from GUI.
        date_from:   Start date ISO string (YYYY-MM-DD).
        date_to:     End date ISO string (YYYY-MM-DD).
        settings:    Settings dict from GUI (base_dir, profile, etc.).
        output_dir:  Directory to write output files into.
        log:         Optional callable(str) for progress messages to GUI.

    Returns:
        List of result dicts:
        [
            {
                "name":    str,
                "format":  str,
                "file":    Path,
                "success": bool,
                "error":   str,   # only present if success=False
            },
            ...
        ]
    """
    if log is None:
        log = lambda msg: None

    plotters = _load_plotters()

    # Group selections by specialist — build() called once per specialist
    by_specialist = {}
    for mod, fmt in selections:
        by_specialist.setdefault(id(mod), {"module": mod, "formats": []})
        by_specialist[id(mod)]["formats"].append(fmt)

    results = []

    for entry in by_specialist.values():
        mod     = entry["module"]
        meta    = mod.META
        name    = meta.get("name", mod.__name__)
        formats = entry["formats"]

        log(f"Building: {name} ...")

        # Fetch data once
        try:
            data = mod.build(date_from, date_to, settings)
        except Exception as exc:
            for fmt in formats:
                results.append({
                    "name":    name,
                    "format":  fmt,
                    "success": False,
                    "error":   f"build() failed: {exc}",
                })
            log(f"  ✗ {name}: data fetch failed — {exc}")
            continue

        # Render each selected format
        for fmt in formats:
            # html_complex registered under its own key — remap display key back
            plotter_key = "html_complex" if (
                fmt == "html" and plotters.get("html_complex") is not None
                and meta.get("formats", {}).get("html_complex") is not None
            ) else fmt
            plotter  = plotters.get(plotter_key)
            filename = meta.get("formats", {}).get(fmt, f"{mod.__name__}.{fmt}")
            out_path = output_dir / filename

            if plotter is None:
                err_detail = plotters.get(f"{plotter_key}_err", "")
                error_msg  = (
                    f"plotter failed to load: {err_detail}"
                    if err_detail
                    else f"no plotter registered for '{fmt}'"
                )
                results.append({
                    "name":    name,
                    "format":  fmt,
                    "success": False,
                    "error":   error_msg,
                })
                log(f"  ✗ {name} → {fmt.upper()}: {error_msg}")
                continue

            try:
                plotter.render(data, out_path, settings)
                results.append({
                    "name":    name,
                    "format":  fmt,
                    "file":    out_path,
                    "success": True,
                })
                log(f"  ✓ {name} → {fmt.upper()}: {out_path.name}")
            except Exception as exc:
                results.append({
                    "name":    name,
                    "format":  fmt,
                    "success": False,
                    "error":   f"render() failed: {exc}",
                })
                log(f"  ✗ {name} → {fmt.upper()}: {exc}")

    return results