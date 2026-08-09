#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
dash_autosize.py

Sole owner of the auto-size boundary calculation shared by dashboard
specialists. Auto-size means: if the requested date range exceeds the
range for which data actually exists, the specialist narrows its
effective range to the actual data boundaries and surfaces a note in
its subtitle.

Two functions, deliberately separate:

- compute_autosize_bounds() — pure boundary calculation. No text
  formatting, no assumptions about subtitle style. Identical for every
  specialist that implements auto-size.
- autosize_note() — optional formatting helper for the recurring
  " · adjusted to available data (requested: X -> Y)" subtitle
  fragment. Specialists with their own subtitle-assembly style can
  still call this — it only depends on the bounds dict, not on how
  the rest of the subtitle is built.

Rules:
- No file I/O, no imports beyond stdlib.
- Called by specialists in dashboards/ — never by plotters.
"""


def compute_autosize_bounds(dates: set, date_from: str, date_to: str) -> dict:
    """
    Determine actual data boundaries against the requested range.

    Args:
        dates:     Set of ISO date strings (YYYY-MM-DD) for which data
                   actually exists.
        date_from: Originally requested start date, ISO.
        date_to:   Originally requested end date, ISO.

    Returns:
        {
            "actual_first":  str | None,   # min(dates), None if dates is empty
            "actual_last":   str | None,   # max(dates), None if dates is empty
            "adjusted_from": str | None,   # date_from, set only if actual_first > date_from
            "adjusted_to":   str | None,   # date_to,   set only if actual_last  < date_to
        }
    """
    if not dates:
        return {
            "actual_first":  None,
            "actual_last":   None,
            "adjusted_from": None,
            "adjusted_to":   None,
        }

    actual_first = min(dates)
    actual_last  = max(dates)

    return {
        "actual_first":  actual_first,
        "actual_last":   actual_last,
        "adjusted_from": date_from if actual_first > date_from else None,
        "adjusted_to":   date_to   if actual_last  < date_to   else None,
    }


def autosize_note(bounds: dict, date_from: str, date_to: str) -> str:
    """
    Build the recurring subtitle fragment for an adjusted range.
    Returns "" if no adjustment occurred.

    Args:
        bounds:    Return value of compute_autosize_bounds().
        date_from: Originally requested start date, ISO.
        date_to:   Originally requested end date, ISO.

    Returns:
        " · adjusted to available data (requested: X -> Y)"  or  ""
    """
    adjusted_from = bounds.get("adjusted_from")
    adjusted_to   = bounds.get("adjusted_to")

    if not (adjusted_from or adjusted_to):
        return ""

    return (
        f" \u00b7 adjusted to available data"
        f" (requested: {adjusted_from or date_from} \u2192 {adjusted_to or date_to})"
    )
