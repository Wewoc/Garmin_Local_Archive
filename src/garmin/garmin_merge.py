#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_merge.py

Leaf-Node — additive field merge for backfill operations.

Used exclusively by backfill paths (Steps Backfill and any future case that
retrofits an optional field into an already-archived day) to add a single
field to an existing raw dict without touching any other content.

Rules:
- Never overwrites a field that already has a non-empty value.
- Never mutates the input dict — returns a new dict.
- No file IO, no project-module imports except stdlib.

Public functions:
  merge_field(raw, field, value) -> dict
"""

import logging

log = logging.getLogger(__name__)


def merge_field(raw: dict, field: str, value) -> dict:
    """
    Additively merges a single field into a raw dict.

    Only sets raw[field] if the field is absent or currently empty
    (None, empty list, empty dict, empty string, 0, False). Never overwrites
    an existing non-empty value — the merge is purely additive, by
    construction incapable of downgrading already-archived content.

    Parameters
    ----------
    raw   : dict — existing raw dict (e.g. from garmin_writer.read_raw())
    field : str  — top-level key to add or fill
    value : any  — value to merge in

    Returns
    -------
    dict — new dict with the field merged in. Input is not mutated.
           Returns the input unchanged (not a copy) if it is not a dict.
    """
    if not isinstance(raw, dict):
        log.warning(
            f"garmin_merge.merge_field: raw is not a dict "
            f"(got {type(raw).__name__}) — returning unchanged"
        )
        return raw

    merged = dict(raw)
    existing = merged.get(field)

    if existing:
        log.debug(f"garmin_merge.merge_field: '{field}' already present and non-empty — skipped")
        return merged

    merged[field] = value
    return merged