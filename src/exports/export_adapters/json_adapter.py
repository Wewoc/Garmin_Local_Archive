#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
exports/export_adapters/json_adapter.py

JSON export adapter — Export Layer (v1.7.4). Writes the archive data
collected by export_common.collect() as a single JSON file. No
format-specific transformation needed beyond json.dump() — gateway_map's
own return shape is already JSON-serializable, making this the Export
Layer's quick-win first adapter.

Rules (ROADMAP.md v1.7.4 design principles):
- Read-only consumer of the Broker Layer, via export_common.collect() only.
- No shared state with other adapters.
- No write access outside its own output file.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import export_common

META = {
    "name":        "JSON",
    "description": "Raw archive passthrough — domain fields + optional metadata",
    "extension":   ".json",
}


def build(date_from: str, date_to: str, domains: list[str],
          include_metadata: bool, output_dir: Path) -> dict:
    """
    Fetch via export_common.collect() and write as a single JSON file.

    Args:
        date_from:         Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:            End date ISO string (YYYY-MM-DD), inclusive.
        domains:            Domain keys to include, e.g. ["health", "context"].
        include_metadata:   If True, also include the metadata kinds.
        output_dir:         Directory to write the output file into.

    Returns:
        {"name": "JSON", "file": Path, "success": bool, "error": str}
        ("error" only present if success=False)
    """
    name = META["name"]
    try:
        data = export_common.collect(date_from, date_to, domains, include_metadata)
        data["generated"] = date.today().isoformat()

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"export{META['extension']}"
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return {"name": name, "file": out_path, "success": True}
    except Exception as exc:
        return {"name": name, "success": False, "error": str(exc)}
