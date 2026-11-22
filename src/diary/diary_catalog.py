#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/diary_catalog.py

DIARY v1.7.8 — REMOVABLE. The fixed catalogue of "Set 1" fields: Garmin-compatible fields the user
enters by hand (no smart device, or hydration by choice). Data only, nothing else; standard library
only.

Only fields whose Garmin structure is evidenced in this repository belong here (provenance rule):
  G001 Blood pressure  get_blood_pressure    measurements: systolic, diastolic, pulse, local time
                                             (garmin_normalizer.py, summarize(): measurementSummaries[].measurements[])
  G002 Hydration       get_hydration_data    valueInML
  G003 Weight          get_body_composition  totalAverage.weight (Garmin: grams, unit unverified)

The other Garmin candidates (single weigh-ins, nutrition log, meals, lifestyle logging, cycle,
pregnancy) have no observed response in the repository: they are not here until a real response
has been observed and documented. A new entry gets a new key; an existing entry never changes
(a definition is immutable, only the display name of a stored field can be changed).

TEMPLATES are start templates for Set 2 (user fields without a Garmin counterpart): when the user picks one,
the panel makes a normal user field from it (new key U..., own copy of the definition). They have no
"maps_to": no Garmin response has been observed for them. A template that was used is no longer offered
(its name is taken by the field).

"maps_to" names the Garmin endpoint. It is stored and not read by anything in v1.7.8.
The weight is kept in kg; the conversion to Garmin's grams belongs to the later connection to
the broker, not to the storage.
"""

import copy

CATALOG = {
    "G001": {
        "name": "Blood pressure",
        "set": "garmin",
        "maps_to": "get_blood_pressure",
        "with_time": True,
        "values": [
            {"label": "systolic", "type": "number", "unit": "mmHg"},
            {"label": "diastolic", "type": "number", "unit": "mmHg"},
            {"label": "Pulse", "type": "number", "unit": "bpm"},
        ],
    },
    "G002": {
        "name": "Hydration",
        "set": "garmin",
        "maps_to": "get_hydration_data",
        "with_time": True,
        "values": [
            {"label": "Amount", "type": "number", "unit": "ml"},
        ],
    },
    "G003": {
        "name": "Weight",
        "set": "garmin",
        "maps_to": "get_body_composition",
        "with_time": False,
        "values": [
            {"label": "Weight", "type": "number", "unit": "kg"},
        ],
    },
}


TEMPLATES = [
    {"name": "Cycle", "with_time": False,
     "values": [{"label": "Period", "type": "yesno"},
                {"label": "Day of cycle", "type": "number", "unit": "day"}]},
    {"name": "Pregnancy", "with_time": False,
     "values": [{"label": "Week", "type": "number", "unit": "week"}]},
    {"name": "Calorie intake", "with_time": False,
     "values": [{"label": "Calories", "type": "number", "unit": "kcal"}]},
    {"name": "Alcohol", "with_time": True,
     "values": [{"label": "Drinks", "type": "number", "unit": "units"},
                {"label": "Type", "type": "text"}]},
    {"name": "Caffeine", "with_time": True,
     "values": [{"label": "Cups", "type": "number", "unit": "cups"}]},
    {"name": "Walk", "with_time": False,
     "values": [{"label": "Done", "type": "yesno"},
                {"label": "Steps", "type": "number", "unit": "steps", "group": "amount"},
                {"label": "Distance", "type": "number", "unit": "km", "group": "amount"}]},
]


def templates():
    """The start templates as copies, in order: [{"name", "with_time", "values"}, ...]."""
    return copy.deepcopy(TEMPLATES)


def keys():
    """The catalogue keys, in order."""
    return sorted(CATALOG)


def definition(key):
    """A copy of the definition of a catalogue key, or None for a key that is not in the catalogue."""
    entry = CATALOG.get(key)
    return copy.deepcopy(entry) if entry is not None else None


def names():
    """The names of all catalogue fields (a user field may not take one of them)."""
    return [entry["name"] for entry in CATALOG.values()]
