#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
_context_io.py

Shared I/O helpers for the four context-side field resolvers
(weather_map.py, pollen_map.py, brightsky_map.py, airquality_map.py).

v1.7.1.11 — replaces the four independent _read_field()/_date_range()
copies with a single parametrized implementation: one function for
summary/ (daily values, identical behaviour to the old _read_field())
and one for raw/ (hourly values, new).

Rules:
- Never writes. Read-only.
- No knowledge of any specific source — takes dir/prefix/key as parameters.
- Called exclusively by the four *_map.py resolvers — never directly by
  context_map.py or specialists.
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def _date_range(date_from: str, date_to: str) -> list[str]:
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def read_summary_field(output_dir: Path, file_prefix: str, internal_key: str,
                        date_from: str, date_to: str) -> dict:
    """Read daily values from summary/*.json. Source-agnostic version of
    the previous per-module _read_field() — identical behaviour."""
    values = []
    for ds in _date_range(date_from, date_to):
        f     = output_dir / f"{file_prefix}{ds}.json"
        value = None
        if f.exists():
            try:
                data  = json.loads(f.read_text(encoding="utf-8"))
                value = data.get("fields", {}).get(internal_key)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"_context_io: could not read {f}: {e}")
        values.append({"date": ds, "value": value})
    return {"values": values, "source_resolution": "daily"}


def read_raw_field(raw_dir: Path, file_prefix: str, internal_key: str,
                    date_from: str, date_to: str) -> dict:
    """Read hourly values from raw/*.json. Each day's file stores the
    field as a list of {"ts": str, "value": ...} pairs, already
    timestamped at write time (context_writer.py) — this is a direct
    pass-through into the broker's series return shape, not a
    reconstruction from a fixed-length index."""
    values = []
    for ds in _date_range(date_from, date_to):
        f      = raw_dir / f"{file_prefix}{ds}.json"
        series = []
        if f.exists():
            try:
                data   = json.loads(f.read_text(encoding="utf-8"))
                series = data.get("fields", {}).get(internal_key, [])
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"_context_io: could not read {f}: {e}")
        values.append({"date": ds, "series": series})
    return {"values": values, "source_resolution": "intraday"}
