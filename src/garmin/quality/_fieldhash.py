#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin/quality/_fieldhash.py

Force-Refetch field-level comparison (v1.7.1.7).

Compares two source dicts (the unmodified API response as archived by
garmin_source_writer — NOT the normalized/raw pipeline dict, which is
identical to source for the "api" origin anyway, and NOT the condensed
daily summary) field by field, using the same KNOWN_FIELDS list that
assess_quality_fields() assesses.

Purpose: after a deliberate per-day Force-Refetch, show the user which
fields actually changed — a label diff alone is too coarse (two different
source payloads can coincidentally produce the same quality label), and a
full content diff has no clear benefit for the intended control purpose
("wrong day? no real change?").

Pure function — no file IO. Internal — import only via garmin_quality
(facade), same convention as _assess.py, _maint.py, etc.
"""

import hashlib
import json
import logging

from quality._assess import KNOWN_FIELDS

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def compare_source_fields(old_source: dict, new_source: dict) -> list[str]:
    """
    Compares two source dicts field by field via SHA-256 hash and returns
    the names of fields that differ.

    Each field's value is serialized with json.dumps(..., sort_keys=True)
    before hashing, so key order inside a field's value never causes a
    false difference. A field missing from one side is treated as None —
    a field appearing, disappearing, or changing all count as a difference.

    Parameters
    ----------
    old_source : dict — previously archived source content (or {} / None-safe
                 if no prior file existed)
    new_source : dict — freshly fetched raw_data (before write_source())

    Returns
    -------
    list[str] — names of fields (from KNOWN_FIELDS) that differ, in
                 KNOWN_FIELDS order. Empty list — no differences found.
    """
    old_source = old_source if isinstance(old_source, dict) else {}
    new_source = new_source if isinstance(new_source, dict) else {}

    changed = []
    for field in KNOWN_FIELDS:
        old_hash = _hash_field(old_source.get(field))
        new_hash = _hash_field(new_source.get(field))
        if old_hash != new_hash:
            changed.append(field)

    return changed


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _hash_field(value) -> str:
    """SHA-256 hex digest of a field's value, order-independent via sort_keys."""
    try:
        payload = json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError) as e:
        log.warning(f"  _fieldhash._hash_field: could not serialize value — {e}")
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()