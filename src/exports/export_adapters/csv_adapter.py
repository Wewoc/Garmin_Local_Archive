#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
exports/export_adapters/csv_adapter.py

CSV export adapter — Export Layer (v1.7.4). Writes a wide, one-row-
per-day table (Health/Context fields as columns) — deliberately NOT
intraday/series data (v1.7.4 Export Layer session, 2026-10-01: a CSV
with real per-minute series values would be too large to meaningfully
open in Excel/LibreOffice, and defeats CSV's purpose as a human/
spreadsheet-readable format). Anyone needing intraday data uses the
JSON adapter instead, which passes it through unchanged.

Row-per-day-with-field-columns, not row-per-(field,day) (2026-10-01,
same session, Timo after testing the first version against his real
archive: "da sollte für health und context pro zeile mehrere werte wie
puls/stress/body battery ... auftauchen, so ist die csv wertlos") —
matches how a human actually wants to read daily health/context data
in a spreadsheet. Metadata does not fit this per-day-row shape at all
(several kinds, e.g. stats/device_table, are not date-indexed) and
goes into a second, separate file instead of forcing it into the same
table.

Rules (ROADMAP.md v1.7.4 design principles):
- Read-only consumer of the Broker Layer, via export_common.collect() only.
- No shared state with other adapters — calls collect() independently,
  does not read json_adapter.py's output.
- No write access outside its own output file(s).
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import export_common

META = {
    "name":        "CSV",
    "description": "Wide daily table (one row per day, fields as columns) + a separate metadata file",
    "extension":   ".csv",
}

_METADATA_FIELDNAMES = ["domain", "source", "field", "date", "value"]


def _collect_wide_values(data: dict, decimal_sep: str) -> tuple[dict[str, dict[str, object]], list[str]]:
    """
    Pivots Health/Context domain data into {date: {column: value}}, plus
    the sorted list of value columns actually seen.

    Column names are prefixed per domain (and, for context, per source —
    "context_<source>_<field>") rather than the bare field name: a field
    can legitimately be registered by more than one context source at
    once (e.g. "wind_speed_max" under both "weather" and "brightsky",
    context_map.py's own documented naming collision) — without the
    source prefix, two sources would silently overwrite the same column.

    Series-shaped entries ({"date", "series"}) are skipped, same
    principle as every other value-vs-series check in this module — see
    module docstring for why intraday data has no place in this CSV at
    all. A day/field with no "values" entry simply has no key for that
    column in that day's row (DictWriter's restval="" fills the gap at
    write time), not a KeyError.

    decimal_sep (v1.7.4, 2026-10-01 session, same day as the delimiter
    option): a float value is re-rendered with this decimal separator
    instead of Python's own "." — German-locale Excel also uses "." as
    its date separator (TT.MM.JJJJ), so a plain decimal like "9.57"
    gets auto-recognized as a short date ("Sep 57") rather than a
    number. Tied to the same German/RFC-4180 choice as the field
    delimiter (","-delimiter keeps "."; ";"-delimiter switches to ",",
    the correct German decimal convention, which cannot collide with
    the ";" field separator). Only applied to float values pulled out
    of "values" entries here — never to the metadata file's JSON blobs,
    which must stay valid JSON (see _metadata_rows()).
    """
    by_date: dict[str, dict[str, object]] = {}
    columns: set[str] = set()

    def _render(value):
        if isinstance(value, float) and decimal_sep != ".":
            return str(value).replace(".", decimal_sep)
        return value

    health = data["domains"].get("health")
    if isinstance(health, dict):
        for field, field_result in health.items():
            if not isinstance(field_result, dict):
                continue
            column = f"health_{field}"
            for entry in field_result.get("values", []):
                if "value" not in entry:
                    continue  # series-shaped entry, deliberately skipped
                by_date.setdefault(entry["date"], {})[column] = _render(entry["value"])
                columns.add(column)

    context = data["domains"].get("context")
    if isinstance(context, dict):
        for source, fields in context.items():
            if not isinstance(fields, dict):
                continue
            for field, field_result in fields.items():
                if not isinstance(field_result, dict):
                    continue
                column = f"context_{source}_{field}"
                for entry in field_result.get("values", []):
                    if "value" not in entry:
                        continue
                    by_date.setdefault(entry["date"], {})[column] = _render(entry["value"])
                    columns.add(column)

    return by_date, sorted(columns)


def _metadata_rows(metadata: dict) -> list[dict]:
    """
    metadata: {kind: {"data": ..., "error": ...}} — mcp_sql.get_metadata_range()'s
    envelope per kind. Three underlying shapes (Form-B snapshot dict,
    Form-C date-keyed entry list, Form-C filename-keyed entry list),
    deliberately unified here into one row per top-level item instead
    of three separate flattening schemes — "field"/"source" both carry
    the kind name, "value" carries the item's full content as a JSON
    string so no information is lost, "date" is filled where the item
    is date-indexed (empty otherwise, e.g. recent-log entries, which
    are filename-keyed, not date-keyed). Written to its own file
    (export_metadata.csv) — see module docstring for why metadata
    doesn't belong in the wide per-day table.
    """
    rows = []
    for kind, envelope in metadata.items():
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if data is None:
            continue
        if isinstance(data, list):
            for entry in data:
                date = entry.get("date") if isinstance(entry, dict) else None
                rows.append({
                    "domain": "metadata", "source": kind, "field": kind,
                    "date": date, "value": json.dumps(entry, ensure_ascii=False),
                })
        else:
            rows.append({
                "domain": "metadata", "source": kind, "field": kind,
                "date": "", "value": json.dumps(data, ensure_ascii=False),
            })
    return rows


def build(date_from: str, date_to: str, domains: list[str],
          include_metadata: bool, output_dir: Path,
          delimiter: str = ";") -> dict:
    """
    Fetch via export_common.collect() and write two files:
    - export.csv — one row per day, Health/Context fields as columns
      ("health_<field>" / "context_<source>_<field>"). Series/intraday
      entries are skipped (see module docstring).
    - export_metadata.csv — only written if include_metadata and at
      least one metadata kind had data; one row per metadata item, see
      _metadata_rows().

    Args:
        date_from:         Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:            End date ISO string (YYYY-MM-DD), inclusive.
        domains:            Domain keys to include, e.g. ["health", "context"].
        include_metadata:   If True, also write export_metadata.csv.
        output_dir:         Directory to write the output file(s) into.
        delimiter:          CSV field separator (v1.7.4, 2026-10-01 session)
                             — default ";" because a comma-separated file
                             opens as one unsplit column in a German-locale
                             Excel (comma is the decimal separator there),
                             not because ";" is the CSV standard (it is
                             ",", RFC 4180). export_data.py's popup lets
                             the user pick "," instead for a non-German
                             Excel locale. Also picks the decimal
                             separator for numeric values — "," when
                             delimiter is ";", otherwise "." — see
                             _collect_wide_values()'s own docstring for
                             why ";" needs "," too, not just the field
                             separator.

    Returns:
        {"name": "CSV", "file": Path, "success": bool, "error": str}
        ("file" is export.csv — the primary output; "error" only
        present if success=False)
    """
    name = META["name"]
    try:
        data = export_common.collect(date_from, date_to, domains, include_metadata)

        decimal_sep = "," if delimiter == ";" else "."
        by_date, columns = _collect_wide_values(data, decimal_sep)

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"export{META['extension']}"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["date"] + columns, delimiter=delimiter, restval="")
            writer.writeheader()
            for date in sorted(by_date):
                writer.writerow({"date": date, **by_date[date]})

        if include_metadata and "metadata" in data:
            meta_rows = _metadata_rows(data["metadata"])
            if meta_rows:
                meta_path = output_dir / f"export_metadata{META['extension']}"
                with meta_path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=_METADATA_FIELDNAMES, delimiter=delimiter)
                    writer.writeheader()
                    writer.writerows(meta_rows)

        return {"name": name, "file": out_path, "success": True}
    except Exception as exc:
        return {"name": name, "success": False, "error": str(exc)}
