#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
custom_dash_builder.py

Builds an ad-hoc, in-memory dashboard specialist from a user-defined field
selection (Custom Dashboard Builder, v1.6.4).

Deliberately does NOT match the *_dash.py naming convention — dash_runner.
scan()'s glob("*_dash.py") must never pick this up as a real specialist file.
This module is not a specialist itself; it manufactures one at runtime.

Rules:
- No direct file access — calls field_map.get() / context_map.get() only.
- Returns a types.ModuleType with META + build(), consumable by
  dash_runner.build() exactly like a file-based specialist. Verified:
  build() only requires .META, .build(date_from, date_to, settings) and
  .__name__ — no importlib/spec_from_file_location path anywhere in it.
- Output shape matches the existing health_garmin-weather-pollen_html-xls_dash
  contract ("fields" list, each with "days") — renders via the existing
  dash_plotter_html_mobile and dash_plotter_excel, no new plotter, no new
  layout key needed.
- Daily-only (v1.6.4 scope) — intraday fields are out of scope, deferred.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from maps.field_map      import get as field_get, list_fields as garmin_list_fields
from maps.context_map    import get as context_get, list_fields as context_list_fields
from layouts.dash_layout import get_metric_meta

# ══════════════════════════════════════════════════════════════════════════════
#  Field picker — Daily-selectable fields
# ══════════════════════════════════════════════════════════════════════════════

# Local copy of explorer_garmin-context_html_dash.py's exclusion set.
# Specialists are standalone by design — no cross-specialist imports (mirrors
# the existing _QUALITY_RANK precedent in garmin_import_mirror.py). Keep in
# sync manually if Explorer's set changes.
_EXCLUDE_FROM_DAILY = {
    "sleep_score_feedback",
    "sleep_score_qualifier",
    "sleep_deep_pct",
    "sleep_light_pct",
    "sleep_rem_pct",
    "sleep_awake_pct",
}

_SERIES_SUFFIX    = "_series"
_CONTEXT_SOURCES  = ["weather", "pollen", "airquality"]


def list_available_fields() -> dict:
    """
    Return Daily-selectable Garmin + Context fields for the picker dialog.

    Returns:
        {
            "garmin":  [str, ...],
            "context": [str, ...],
        }
    """
    garmin_fields = [
        f for f in garmin_list_fields()
        if not f.endswith(_SERIES_SUFFIX) and f not in _EXCLUDE_FROM_DAILY
    ]
    context_fields = []
    for src in _CONTEXT_SOURCES:
        context_fields.extend(context_list_fields(src))

    return {"garmin": garmin_fields, "context": context_fields}


# ══════════════════════════════════════════════════════════════════════════════
#  Ad-hoc specialist assembly
# ══════════════════════════════════════════════════════════════════════════════

def build_ad_hoc_specialist(name: str, description: str,
                             garmin_fields: list[str],
                             context_fields: list[str]) -> types.ModuleType:
    """
    Assemble an in-memory specialist module for the given field selection.

    Args:
        name:           Display name (GUI + dashboard title).
        description:    One-line description (informational only).
        garmin_fields:  Garmin daily field names (from list_available_fields()["garmin"]).
        context_fields: Context daily field names (from list_available_fields()["context"]).

    Returns:
        types.ModuleType with .META and .build(date_from, date_to, settings) —
        drop-in compatible with dash_runner.build()'s specialist contract.
        No file is written to disk.
    """
    mod = types.ModuleType(f"custom_dashboard_{abs(hash(name))}")

    mod.META = {
        "name":        name,
        "description": description,
        "source":      "Custom selection",
        "formats": {
            "html_mobile": "custom_dashboard.html",
            "excel":       "custom_dashboard.xlsx",
        },
    }

    def _build(date_from: str, date_to: str, settings: dict) -> dict:
        fields_out = []

        for f in garmin_fields:
            result = field_get(f, date_from, date_to, resolution="daily")
            meta   = get_metric_meta(f)
            days = [
                {"date": entry["date"], "value": entry["value"]}
                for entry in result.get("garmin", {}).get("values", [])
            ]
            fields_out.append({
                "field": f,
                "label": meta.get("label", f),
                "unit":  meta.get("unit", ""),
                "group": "garmin",
                "days":  days,
            })

        for f in context_fields:
            result        = context_get(f, date_from, date_to)
            source_result = next(iter(result.values()), {}) if result else {}
            source_name   = next(iter(result.keys()), "context") if result else "context"
            meta          = get_metric_meta(f)
            days = [
                {"date": entry["date"], "value": entry["value"]}
                for entry in source_result.get("values", [])
            ]
            fields_out.append({
                "field": f,
                "label": meta.get("label", f),
                "unit":  meta.get("unit", ""),
                "group": source_name,
                "days":  days,
            })

        return {
            "title":     name,
            "subtitle":  f"{date_from} \u2192 {date_to}",
            "date_from": date_from,
            "date_to":   date_to,
            "fields":    fields_out,
        }

    mod.build = _build
    return mod
