#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
app/popups/_export_scan_units.py
Garmin Local Archive — units of the numeric fields of the export, for the values view

EXPORT-SCAN v1.7.7 — REMOVABLE (removal list: see garmin_export_scan.py).

Pure data and one lookup: no PyQt, no file access, no project imports.

RULE: a unit is named ONLY where there is evidence, and every unit says where it comes from. Nothing is
taken from memory and nothing is converted: the values stay as the export holds them, the unit is a label.
A field with no evidence has no unit; the view then says "not documented".

The two origins:
  "name"     the LAST WORD of the field name states the unit (deepSleepSeconds, totalDistanceMeters,
             totalKilocalories, acwrPercent, vigorousIntensityMinutes, durationInMilliseconds). Only the end
             of the name counts, not a word in the middle (userIntensityMinutesGoal says nothing).
  "GLA code" a module of this project treats the field as that unit: garmin_normalizer.py maps the raw field
             to an archive field whose name says it (restingHeartRate -> resting_bpm) and passes totalSteps
             on as the day's steps, and garmin_bulk_normalizer.py keeps the FIT heart rate of the day view
             (family "fit_monitoring") as bpm. The source is named in the entry. The units of the ARCHIVE fields
             (FIELD_UNITS of the MCP server) are NOT used: the archive converts (its distance is in km, the
             export's totalDistanceMeters is in metres).
What the reference says (REFERENCE_GARMIN_EXPORT.md, section 3, "Seen"): durations in seconds or
milliseconds, distances in metres, floors as metres (floorsAscendedInMeters is metres of climb, not a
count) — the name rule covers exactly these.

Add an entry to EXPLICIT only with its evidence (the source text); a field that is only guessed does not get one.

Public API:
  unit_of(family, field) -> {"unit", "origin", "source"} | None
  with_unit(text, found) -> str            "name (unit)" or the text alone
  NOT_DOCUMENTED, NAME_RULES, EXPLICIT
"""

import re

NOT_DOCUMENTED = "unit not documented, raw value as Garmin writes it"

# (the end of the last word of the field name, unit, what the name says)
NAME_RULES = (
    (re.compile(r"Milliseconds$"), "ms", "milliseconds"),
    (re.compile(r"Seconds$"), "s", "seconds"),
    (re.compile(r"Minutes$"), "min", "minutes"),
    (re.compile(r"Meters$"), "m", "meters"),
    (re.compile(r"Kilocalories$"), "kcal", "kilocalories"),
    (re.compile(r"(Percent|Percentage)$"), "%", "percent"),
)

# (family key, field path) -> (unit, the evidence)
EXPLICIT = {
    ("uds", "restingHeartRate"): ("bpm", "garmin_normalizer.py: restingHeartRate -> resting_bpm"),
    ("uds", "currentDayRestingHeartRate"): ("bpm", "garmin_import.py: currentDayRestingHeartRate -> restingHeartRate, "
                                                     "garmin_normalizer.py: restingHeartRate -> resting_bpm"),
    ("uds", "minHeartRate"): ("bpm", "garmin_normalizer.py: minHeartRate -> min_bpm"),
    ("uds", "maxHeartRate"): ("bpm", "garmin_normalizer.py: maxHeartRate -> max_bpm"),
    ("uds", "totalSteps"): ("steps", "garmin_normalizer.py: totalSteps -> steps (the day's step count)"),
    # the heart-rate day view (garmin_export_scan_day.py): FIT message 55, field 27
    ("fit_monitoring", "heartRate"): ("bpm", "garmin_bulk_normalizer.py: FIT message 55 field 27 is kept as bpm "
                                             "(DaySamples values are [ms UTC, bpm])"),
}


def unit_of(family, field):
    """The unit of a field and where it comes from, None if there is no evidence for one.
    Returns {"unit": "bpm", "origin": "name" | "GLA code", "source": text}."""
    if not isinstance(field, str) or not field:
        return None
    explicit = EXPLICIT.get((family, field))
    if explicit:
        return {"unit": explicit[0], "origin": "GLA code", "source": explicit[1]}
    last = field.split(".")[-1]
    for pattern, unit, word in NAME_RULES:
        if pattern.search(last):
            return {"unit": unit, "origin": "name", "source": f"the field name ends with the word for {word}"}
    return None


def with_unit(text: str, found) -> str:
    """"deepSleepSeconds (s)" for a field with a unit, the text alone for a field without."""
    return f"{text} ({found['unit']})" if found else text
