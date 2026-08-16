#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_api_capability.py

Sole Owner of the API-Capability-Scan config (garmin_api_capability_config.json).

Leaf-Node — imports only garmin_config (path constant) + stdlib. No
project-pipeline imports (garmin_collector, garmin_api, garmin_quality, ...).
Analogous to garmin_validator.py's leaf-node status: garmin_config counts as
infrastructure, not a pipeline dependency (see REFERENCE_GARMIN.md).

Scope (v1.6.8, this module): pure persistence for the 19 optional
health-endpoint candidates. Does NOT call the Garmin API itself, does NOT
know about garmin_collector's sync loop, does NOT touch quality_log.json.
The scan logic, the Lock/Mutex against the regular sync, and the
per-sync-run immutable-snapshot handling are separate, later build steps
(see NOTES_v168.md).

Config is read as an immutable snapshot per caller — this module has no
module-level cache and no reload() (unlike garmin_validator.py's schema
cache). Each caller (later: garmin_collector) reads once via load_config()
and keeps its own reference for the duration of its run — this is the
race-safety property the Multi-LLM review asked for, not something this
module enforces itself.
"""

import json
import logging
import os

import garmin_config as cfg

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  Candidate endpoints (19) — see NOTES_v168.md Kandidaten-Entscheidungsmatrix
# ══════════════════════════════════════════════════════════════════════════════

CANDIDATE_ENDPOINTS = [
    # Body Composition
    "get_body_composition",
    "get_daily_weigh_ins",
    # Wellness
    "get_blood_pressure",
    "get_hydration_data",
    "get_menstrual_calendar_data",
    "get_pregnancy_summary",
    "get_lifestyle_logging_data",
    "get_nutrition_daily_food_log",
    "get_nutrition_daily_meals",
    "get_nutrition_daily_settings",
    # Daily Health
    "get_calories_daily",
    "get_floors",
    "get_intensity_minutes_data",
    # Advanced Health
    "get_body_battery_events",
    "get_endurance_score",
    "get_fitnessage_data",
    "get_hill_score",
    "get_lactate_threshold",
    "get_running_tolerance",
]

VALID_STATUSES = ("found", "not_observed", "error")

SCHEMA_VERSION = 1


# ══════════════════════════════════════════════════════════════════════════════
#  Defaults
# ══════════════════════════════════════════════════════════════════════════════

def _default_entry() -> dict:
    """Returns a fresh, untouched config entry for one candidate endpoint."""
    return {
        "status":              "not_observed",
        "last_scan":           None,
        "discovered_at":       None,
        "last_seen_with_data": None,
        "enabled_by_user":     False,
    }


def _default_config() -> dict:
    """Returns a fresh config with all 19 candidates at their untouched default."""
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoints": {ep: _default_entry() for ep in CANDIDATE_ENDPOINTS},
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Load / Save
# ══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    """
    Loads garmin_api_capability_config.json. Returns a fresh default config
    if the file does not exist yet or cannot be parsed — never raises.
    Does not write anything to disk itself.
    """
    path = cfg.CAPABILITY_CONFIG_FILE
    if not path.exists():
        return _default_config()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"[CAPABILITY] Could not read {path.name} — using defaults ({e})")
        return _default_config()

    if not isinstance(data, dict) or "endpoints" not in data:
        log.warning(f"[CAPABILITY] {path.name} has unexpected structure — using defaults")
        return _default_config()

    return data


def save_config(config: dict) -> bool:
    """
    Atomically writes config to garmin_api_capability_config.json
    (.tmp → fsync → os.replace — same pattern as
    garmin_source_writer.write_source() / garmin_mirror.lock()).
    Returns True on success, False on any failure. Non-fatal — caller
    decides whether a failed save should be surfaced to the user.
    """
    path = cfg.CAPABILITY_CONFIG_FILE
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError as e:
        log.warning(f"[CAPABILITY] Could not save {path.name} — {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Update
# ══════════════════════════════════════════════════════════════════════════════

def update_endpoint(config: dict, endpoint: str, status: str, **meta) -> dict:
    """
    Returns a new config dict with one endpoint entry updated. Pure function —
    does not call save_config() itself, caller decides when to persist.

    status must be one of VALID_STATUSES ("found" / "not_observed" / "error").
    Unknown status or unknown endpoint → returns config unchanged, logs a
    warning (never raises).

    **meta may set any of: last_scan, discovered_at, last_seen_with_data,
    enabled_by_user. Unspecified meta keys keep their existing value.
    """
    if status not in VALID_STATUSES:
        log.warning(f"[CAPABILITY] update_endpoint: invalid status '{status}' for {endpoint} — ignored")
        return config

    if endpoint not in CANDIDATE_ENDPOINTS:
        log.warning(f"[CAPABILITY] update_endpoint: unknown endpoint '{endpoint}' — ignored")
        return config

    entries = dict(config.get("endpoints", {}))
    entry = dict(entries.get(endpoint, _default_entry()))
    entry["status"] = status
    for key in ("last_scan", "discovered_at", "last_seen_with_data", "enabled_by_user"):
        if key in meta:
            entry[key] = meta[key]

    entries[endpoint] = entry
    new_config = dict(config)
    new_config["endpoints"] = entries
    return new_config


# ══════════════════════════════════════════════════════════════════════════════
#  Reset
# ══════════════════════════════════════════════════════════════════════════════

def reset_config() -> dict:
    """
    Returns a fresh default config — all candidates reset to their untouched
    default (not observed, disabled, no timestamps). Does not save; caller
    decides via save_config(). Public entry point for UI "Clear Config"
    actions, so callers never need to reach into the private
    _default_config().
    """
    return _default_config()


# ══════════════════════════════════════════════════════════════════════════════
#  Candidate selection for a sync run (v1.6.8.1)
# ══════════════════════════════════════════════════════════════════════════════

def get_enabled_candidates(config: dict) -> list[str]:
    """
    Returns the subset of CANDIDATE_ENDPOINTS that are double-gated as
    enabled for a sync run: status == "found" AND enabled_by_user == True.

    Pure function — takes an already-loaded config snapshot, does not call
    load_config() itself. Caller controls when/under which lock the config
    is read (see garmin_collector.main()'s fetch-loop section, which reads
    the snapshot once per sync run inside quality.QUALITY_LOCK for
    race-safety against a concurrent capability scan — see NOTES_v168.md).

    Extracted from garmin_collector.py::main() (v1.6.8.1) — was inline in
    the fetch-loop section, not unit-testable without invoking the rest of
    main(). Behavior unchanged from the original inline logic.
    """
    return [
        ep for ep in CANDIDATE_ENDPOINTS
        if config.get("endpoints", {}).get(ep, {}).get("status") == "found"
        and config.get("endpoints", {}).get(ep, {}).get("enabled_by_user")
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  Argument shape per candidate (discovered empirically, first live scan
#  2026-08-13 — see NOTES_v168.md)
# ══════════════════════════════════════════════════════════════════════════════

# Not every candidate takes a single date_str like the 15 baseline endpoints.
# Real TypeErrors from the first live scan revealed the true shapes for these
# five; all other candidates default to "single_date" (unverified but
# consistent with the baseline pattern until proven otherwise).
#   "single_date" — client.<method>(date_str)             — default, 14 candidates
#   "no_args"     — client.<method>()                     — no date parameter at all
#   "date_range"  — client.<method>(date_str, date_str)   — start/end, same day for a
#                                                             single-day probe
ENDPOINT_ARGS = {
    "get_pregnancy_summary":       "no_args",
    "get_lactate_threshold":       "no_args",
    "get_menstrual_calendar_data": "date_range",
    "get_calories_daily":          "date_range",
    "get_running_tolerance":       "date_range",
}


def build_args(endpoint: str, date_str: str) -> tuple:
    """
    Returns the correct positional-args tuple for a candidate endpoint.
    Endpoints not listed in ENDPOINT_ARGS default to "single_date" —
    same shape as the 15 baseline endpoints.
    """
    shape = ENDPOINT_ARGS.get(endpoint, "single_date")
    if shape == "no_args":
        return ()
    if shape == "date_range":
        return (date_str, date_str)
    return (date_str,)
