#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
exports/export_adapters/influxdb_adapter.py

InfluxDB Line Protocol export adapter — Export Layer (v1.7.4). Writes a
.lp text file (InfluxDB's import format) — enables garmin-grafana and
similar tools to consume GLA data without fetching from the Garmin API
(ROADMAP.md v1.7.4). GLA itself does not run or connect to an InfluxDB
server; this is a batch file export only, same as every other adapter.

Design (v1.7.4 Export Layer session 3, 2026-10-01, Timo's decisions):
- Full resolution, including intraday/series fields — unlike csv_adapter
  (which skips them as unusable in a spreadsheet), InfluxDB/Grafana's
  whole purpose is time-series graphing, so series data is the main
  reason this adapter exists at all.
- One measurement per domain ("health"/"context"), field name as the
  field key within it — mirrors collect()'s own domain grouping, no
  extra per-field measurement sprawl.
- Context gets a "source" tag (weather/pollen/brightsky/airquality) —
  needed because a field name can be registered by more than one source
  at once (e.g. "wind_speed_max" under both weather and brightsky,
  context_map.py's own documented naming collision), same reason
  csv_adapter prefixes its column names. Health gets no tag — its
  source is currently always "garmin" (mcp_sql.get_health_range()'s own
  docstring), and a tag that never varies has no filtering value, only
  added series cardinality.
- Series timestamps: garmin_health_map._ts_to_iso() deliberately returns
  a naive, device-local timestamp (no UTC suffix, NOTES v1.6.5.6 — avoids
  double timezone correction downstream). This adapter treats that naive
  string literally as UTC, the same simplification already made for
  daily fields (a date becomes midnight "UTC" of that calendar day, with
  no real timezone grounding either) — consistent, not a new
  correctness claim.
- fallback/source_resolution (field-level metadata) are dropped, same
  reasoning as csv_adapter's wide-format cutover (Baustein 15): would
  have to be duplicated per point, no natural home in a single line.
- No metadata kinds (stats/quality_log/...) — Line Protocol is strictly
  timestamp+value; most metadata kinds are not date-indexed at all, so
  unlike csv_adapter's separate export_metadata.csv there is no
  time-series-shaped place to put them here. include_metadata is
  accepted (export_runner.build() always passes it) but ignored.

Rules (ROADMAP.md v1.7.4 design principles):
- Read-only consumer of the Broker Layer, via export_common.collect() only.
- No shared state with other adapters — calls collect() independently.
- No write access outside its own output file.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import export_common

META = {
    "name":        "InfluxDB Line Protocol",
    "description": "Full-resolution time-series export (.lp) for InfluxDB/Grafana",
    "extension":   ".lp",
}

_EPOCH = datetime(1970, 1, 1)


def _escape_measurement(s: str) -> str:
    """Line Protocol measurement escaping — comma and space only."""
    return str(s).replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")


def _escape_key(s: str) -> str:
    """Line Protocol tag-key/tag-value/field-key escaping."""
    return (str(s).replace("\\", "\\\\").replace(",", "\\,")
            .replace("=", "\\=").replace(" ", "\\ "))


def _render_field_value(value) -> str | None:
    """
    Renders a single field value as its Line Protocol literal, or None
    if the value can't/shouldn't be written (None, or an unsupported
    nested shape). Numbers are written as plain (unsuffixed) float
    literals — Line Protocol's own default numeric type — never with
    the "i" integer suffix, since GLA's own values are floats already
    (see garmin_health_map._extract_series()'s "v = float(val) - offset").
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value))
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return None  # unsupported shape (e.g. nested dict) — skip, not a hard failure


def _date_to_ns(date_str: str) -> int:
    """Midnight of date_str, treated literally as UTC (see module docstring)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int((dt - _EPOCH).total_seconds()) * 1_000_000_000


def _ts_to_ns(ts_str) -> int | None:
    """
    Parses a garmin_health_map._ts_to_iso()-style naive ISO timestamp
    ("YYYY-MM-DDTHH:MM:SS"), treated literally as UTC (see module
    docstring). Returns None if unparseable rather than raising — a
    malformed point is skipped individually, not the whole export.
    """
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return None
    return int((dt - _EPOCH).total_seconds()) * 1_000_000_000


def _lines_for_field(measurement: str, tags: dict[str, str], field_key: str,
                      field_result: dict) -> list[str]:
    """
    One Line Protocol line per daily value, or per series point for an
    intraday field (see module docstring for the series decision).
    "fallback"/"source_resolution" are deliberately not included (see
    module docstring).
    """
    lines = []
    measurement_part = _escape_measurement(measurement)
    tag_str = "".join(f",{_escape_key(k)}={_escape_key(v)}" for k, v in tags.items())
    field_name = _escape_key(field_key)

    for entry in field_result.get("values", []):
        if "series" in entry:
            series = entry.get("series")
            if not series:
                continue  # None (missing day) or [] (empty day) — nothing to write
            for point in series:
                rendered = _render_field_value(point.get("value"))
                ts_ns = _ts_to_ns(point.get("ts"))
                if rendered is None or ts_ns is None:
                    continue
                lines.append(f"{measurement_part}{tag_str} {field_name}={rendered} {ts_ns}")
        else:
            rendered = _render_field_value(entry.get("value"))
            if rendered is None:
                continue
            ts_ns = _date_to_ns(entry["date"])
            lines.append(f"{measurement_part}{tag_str} {field_name}={rendered} {ts_ns}")

    return lines


def build(date_from: str, date_to: str, domains: list[str],
          include_metadata: bool, output_dir: Path) -> dict:
    """
    Fetch via export_common.collect() and write a single InfluxDB Line
    Protocol (.lp) text file, one line per data point, nanosecond
    timestamps (see module docstring for the timestamp/UTC caveat).

    Args:
        date_from:         Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:            End date ISO string (YYYY-MM-DD), inclusive.
        domains:            Domain keys to include, e.g. ["health", "context"].
        include_metadata:   Accepted for signature parity with
                             export_runner.build()'s uniform call, but
                             ignored — see module docstring.
        output_dir:         Directory to write the output file into.

    Returns:
        {"name": "InfluxDB Line Protocol", "file": Path, "success": bool,
         "error": str} ("error" only present if success=False)
    """
    name = META["name"]
    try:
        data = export_common.collect(date_from, date_to, domains, include_metadata=False)

        lines: list[str] = []

        health = data["domains"].get("health")
        if isinstance(health, dict):
            for field, field_result in health.items():
                if isinstance(field_result, dict):
                    lines.extend(_lines_for_field("health", {}, field, field_result))

        context = data["domains"].get("context")
        if isinstance(context, dict):
            for source, fields in context.items():
                if not isinstance(fields, dict):
                    continue
                for field, field_result in fields.items():
                    if isinstance(field_result, dict):
                        lines.extend(
                            _lines_for_field("context", {"source": source}, field, field_result))

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"export{META['extension']}"
        out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        return {"name": name, "file": out_path, "success": True}
    except Exception as exc:
        return {"name": name, "success": False, "error": str(exc)}
