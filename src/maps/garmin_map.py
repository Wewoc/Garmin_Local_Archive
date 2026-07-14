#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_map.py

Garmin-side field resolver for the dashboard broker architecture.

Knows the full internal structure of Garmin data: which generic field name
maps to which resolution, which JSON section, and which key path.

Rules:
- Never writes. Never knows what a dashboard looks like.
- Never touches files of any other source.
- Called exclusively by field_map.py — never directly by specialists.

Generic field names (dashboard-side):
  no suffix   → daily    → reads from summary/
  _series     → intraday → reads from raw/

Internal Garmin key format (garmin-side, never visible to specialists):
  "section.key"  or  "section.nested.key"

Architecture boundary:
  Any Garmin-internal key (section.field) appearing outside this module
  is an architecture violation — detectable by name format alone.
"""

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# garmin_map lives in maps/ — garmin/ is one level up (sibling package)
# This is the one sys.path bridge between maps/ and garmin/
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  Field map — single source of truth for all Garmin field definitions
#
#  Structure per field:
#    "intraday": (section, key)  or  None if intraday not available
#    "daily":    (section, key)  or  None if daily not available
#
#  section = top-level key in the raw/summary JSON
#  key     = dot-separated path within that section
# ══════════════════════════════════════════════════════════════════════════════

_FIELD_MAP = {

    # ── Daily fields (summary/) ───────────────────────────────────────────────

    "hrv_last_night": {
        "intraday": None,
        "daily":    ("sleep",     "hrv_last_night_ms"),
        "live_nested": [
            ("hrv", "hrvSummary.lastNight"),
            ("hrv", "hrvSummary.lastNight5MinHigh"),
        ],
    },
    "sleep_deep_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "deepSleepSeconds",  "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "deepSleepSeconds",  "sleepTimeSeconds"),
    },
    "sleep_light_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "lightSleepSeconds", "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "lightSleepSeconds", "sleepTimeSeconds"),
    },
    "sleep_rem_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "remSleepSeconds",   "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "remSleepSeconds",   "sleepTimeSeconds"),
    },
    "sleep_awake_pct": {
        "intraday": None,
        "daily":    None,
        "raw_pct":  ("sleep", "dailySleepDTO", "awakeSleepSeconds", "sleepTimeSeconds"),
        "live_pct": ("sleep", "dailySleepDTO", "awakeSleepSeconds", "sleepTimeSeconds"),
    },
    "resting_heart_rate": {
        "intraday": None,
        "daily":    ("heartrate", "resting_bpm"),
    },
    "spo2_avg": {
        "intraday": None,
        "daily":    ("sleep",     "spo2_avg"),
    },
    "sleep_duration": {
        "intraday": None,
        "daily":    ("sleep",     "duration_h"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepTimeSeconds", 3600),
        ],
    },
    "body_battery_max": {
        "intraday": None,
        "daily":    ("stress",    "body_battery_max"),
    },
    "stress_avg": {
        "intraday": None,
        "daily":    ("stress",    "stress_avg"),
    },
    "vo2max": {
        "intraday": None,
        "daily":    ("training",  "vo2max"),
    },

    "sleep_score": {
        "intraday": None,
        "daily":    ("sleep", "score"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScores.overall.value"),
        ],
    },
    "sleep_score_feedback": {
        "intraday": None,
        "daily":    ("sleep", "sleep_score_feedback"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScoreFeedback"),
        ],
    },
    "sleep_score_qualifier": {
        "intraday": None,
        "daily":    ("sleep", "sleep_score_qualifier"),
        "live_nested": [
            ("sleep", "dailySleepDTO.sleepScores.overall.qualifierKey"),
        ],
    },

    # ── Intraday fields (raw/) ────────────────────────────────────────────────
    #
    #  "intraday": (section, array_key, extract)
    #
    #  extract describes how to normalize each array item to {"ts": str, "value": float}:
    #    ts_index:   index of the timestamp in a list-item  (None = dict-based)
    #    val_index:  index of the value    in a list-item  (None = dict-based)
    #    ts_key:     dict key for timestamp  (used when ts_index is None)
    #    val_key:    dict key for value      (used when val_index is None)
    #    val_min:    drop items where value < val_min (None = no filter)
    #    offset_key: sibling key in the section dict to subtract from value (None = no offset)

    "heart_rate_series": {
        "intraday": ("heart_rates", "heartRateValues", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "heartRate",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("heart_rates", "heartRateValues", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "heartRate",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "stress_series": {
        "intraday": ("stress", "stressValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "stressLevel",
            "val_min":    0,
            "offset_key": "stressChartValueOffset",
        }),
        "live": ("stress", "stressValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "stressLevel",
            "val_min":    0,
            "offset_key": "stressChartValueOffset",
        }),
        "daily": None,
    },
    "spo2_series": {
        "intraday": ("spo2", "spO2HourlyAverages", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "spO2Reading",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("spo2", "spO2HourlyAverages", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "spO2Reading",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "body_battery_series": {
        "intraday": ("stress", "bodyBatteryValuesArray", {
            "ts_index":   0,
            "val_index":  2,
            "ts_key":     "startGMT",
            "val_key":    "bodyBatteryLevel",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("stress", "bodyBatteryValuesArray", {
            "ts_index":   0,
            "val_index":  2,
            "ts_key":     "startGMT",
            "val_key":    "bodyBatteryLevel",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "respiration_series": {
        "intraday": ("respiration", "respirationValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "respirationValue",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("respiration", "respirationValuesArray", {
            "ts_index":   0,
            "val_index":  1,
            "ts_key":     "startGMT",
            "val_key":    "respirationValue",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
    "steps_series": {
        "intraday": ("steps", None, {
            "ts_index":   None,
            "val_index":  None,
            "ts_key":     "startGMT",
            "val_key":    "steps",
            "val_min":    None,
            "offset_key": None,
        }),
        "live": ("steps", None, {
            "ts_index":   None,
            "val_index":  None,
            "ts_key":     "startGMT",
            "val_key":    "steps",
            "val_min":    None,
            "offset_key": None,
        }),
        "daily": None,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _date_range(date_from: str, date_to: str) -> list[str]:
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    result = []
    while d <= end:
        result.append(d.isoformat())
        d += timedelta(days=1)
    return result


def _get_nested(obj: dict, key: str):
    """Resolve a dot-separated key path within a dict. Returns None if missing."""
    parts = key.split(".")
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _ts_to_iso(ts) -> str:
    """Normalize a Garmin timestamp (ms epoch or ISO string) to ISO-8601."""
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return str(ts)[:19]
    except Exception:
        return str(ts)


def _extract_series(arr: list, section_data: dict, extract: dict) -> list:
    """
    Normalize a raw Garmin array to [{"ts": str, "value": float}, ...].
    Uses the extract descriptor from _FIELD_MAP to handle field-specific
    array structures without leaking Garmin internals to callers.
    """
    offset = 0
    if extract["offset_key"]:
        raw_offset = section_data.get(extract["offset_key"]) or 0
        try:
            offset = float(raw_offset)
        except (TypeError, ValueError):
            offset = 0

    result = []
    for item in arr:
        try:
            if extract["ts_index"] is not None and isinstance(item, (list, tuple)):
                ts  = item[extract["ts_index"]]
                val = item[extract["val_index"]]
            elif isinstance(item, dict):
                ts  = item.get(extract["ts_key"]) or item.get("timestamp")
                val = item.get(extract["val_key"]) or item.get("value")
            else:
                continue
            if val is None:
                continue
            v = float(val) - offset
            if extract["val_min"] is not None and v < extract["val_min"]:
                continue
            result.append({"ts": _ts_to_iso(ts), "value": v})
        except (TypeError, ValueError, IndexError):
            continue
    return result


def _read_raw_pct(field: str, date_from: str, date_to: str) -> dict:
    """
    Read a percentage value from raw/ by dividing seconds_key by total_key.
    Returns {"values": [{"date": str, "value": float|None}, ...], "source_resolution": "daily"}.
    """
    section, dto_key, seconds_key, total_key = _FIELD_MAP[field]["raw_pct"]

    values = []
    for ds in _date_range(date_from, date_to):
        f     = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
        value = None
        if f.exists():
            try:
                data  = json.loads(f.read_text(encoding="utf-8"))
                dto   = data.get(section, {}).get(dto_key, {})
                if isinstance(dto, dict):
                    part  = dto.get(seconds_key)
                    total = dto.get(total_key)
                    if part is not None and total and total > 0:
                        value = round(part / total * 100, 1)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_map: could not read {f}: {e}")
        values.append({"date": ds, "value": value})

    return {"values": values, "source_resolution": "daily"}


def _read_daily(field: str, date_from: str, date_to: str) -> dict:
    """
    Read daily values from summary/.
    Returns {"values": [{"date": str, "value": any}, ...], "source_resolution": "daily"}.
    """
    section, key = _FIELD_MAP[field]["daily"]

    values = []
    for ds in _date_range(date_from, date_to):
        f = cfg.SUMMARY_DIR / f"{cfg.SUMMARY_FILE_PREFIX}{ds}.json"
        value = None
        if f.exists():
            try:
                data         = json.loads(f.read_text(encoding="utf-8"))
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    value = _get_nested(section_data, key)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_map: could not read {f}: {e}")
        values.append({"date": ds, "value": value})

    return {"values": values, "source_resolution": "daily"}


def _read_intraday(field: str, date_from: str, date_to: str) -> dict:
    """
    Read intraday series from raw/.
    Normalizes each day's array to [{"ts": str, "value": float}, ...].
    Returns {"values": [{"date": str, "series": list|None}, ...], "source_resolution": "intraday"}.
    series is None if the file is missing or the field is absent.
    series is [] if the file exists but the array is empty after normalization.
    """
    section, array_key, extract = _FIELD_MAP[field]["intraday"]

    values = []
    for ds in _date_range(date_from, date_to):
        f = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
        series = None
        if f.exists():
            try:
                data         = json.loads(f.read_text(encoding="utf-8"))
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    arr = section_data.get(array_key)
                    if isinstance(arr, list):
                        series = _extract_series(arr, section_data, extract)
                elif isinstance(section_data, list):
                    series = _extract_series(section_data, {}, extract)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_map: could not read {f}: {e}")
        values.append({"date": ds, "series": series})

    return {"values": values, "source_resolution": "intraday"}


def _read_live(field: str) -> dict:
    """
    Read an intraday series from the live snapshot (cfg.LIVE_FILE).
    Same array-extraction logic as _read_intraday(), single always-current
    source instead of a dated file — date_from/date_to are not used.
    Returns {"values": [{"date": str, "series": list}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE or missing field in the snapshot → fallback=True,
    empty values, never an exception.
    """
    section, array_key, extract = _FIELD_MAP[field]["live"]

    series = None
    snapshot_date = None
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            section_data  = data.get(section)
            if isinstance(section_data, dict):
                arr = section_data.get(array_key)
                if isinstance(arr, list):
                    series = _extract_series(arr, section_data, extract)
            elif isinstance(section_data, list):
                series = _extract_series(section_data, {}, extract)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_map: could not read {cfg.LIVE_FILE}: {e}")

    if series is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "series": series}],
        "fallback":          False,
        "source_resolution": "live",
    }


def _read_live_pct(field: str) -> dict:
    """
    Read a percentage value from the live snapshot (cfg.LIVE_FILE) by
    dividing seconds_key by total_key. Same math as _read_raw_pct(), single
    always-current source instead of a dated file.
    Returns {"values": [{"date": str, "value": float}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE, missing section, or total <= 0 → fallback=True,
    empty values, never an exception.
    """
    section, dto_key, seconds_key, total_key = _FIELD_MAP[field]["live_pct"]

    value = None
    snapshot_date = None
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            dto           = data.get(section, {}).get(dto_key, {})
            if isinstance(dto, dict):
                part  = dto.get(seconds_key)
                total = dto.get(total_key)
                if part is not None and total and total > 0:
                    value = round(part / total * 100, 1)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_map: could not read {cfg.LIVE_FILE}: {e}")

    if value is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "value": value}],
        "fallback":          False,
        "source_resolution": "live",
    }


def _read_live_nested(field: str) -> dict:
    """
    Read a single nested value from the live snapshot (cfg.LIVE_FILE) via a
    dotted key path, trying each candidate in order until one resolves to a
    non-None value. Uses the existing _get_nested() helper against a fixed
    live source with a fallback chain instead of a single path.

    Candidates are 2-tuples (section, dotted_key) or 3-tuples (section,
    dotted_key, divisor) — divisor divides the raw value before it is
    returned (e.g. sleepTimeSeconds / 3600 → hours). Omit for values used
    as-is.

    Returns {"values": [{"date": str, "value": any}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE or no candidate resolves → fallback=True, empty
    values, never an exception.
    """
    candidates = _FIELD_MAP[field]["live_nested"]

    value = None
    snapshot_date = None
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            for candidate in candidates:
                section, dotted_key = candidate[0], candidate[1]
                divisor = candidate[2] if len(candidate) > 2 else None
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    raw = _get_nested(section_data, dotted_key)
                    if raw is not None:
                        value = round(raw / divisor, 1) if divisor else raw
                        break
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_map: could not read {cfg.LIVE_FILE}: {e}")

    if value is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "value": value}],
        "fallback":          False,
        "source_resolution": "live",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface — called exclusively by field_map.py
# ══════════════════════════════════════════════════════════════════════════════

def get(field: str, date_from: str, date_to: str,
        resolution: str = "daily") -> dict:
    """
    Resolve a generic field name to Garmin data.

    Args:
        field:       Generic field name (dashboard-side). Must exist in _FIELD_MAP.
        date_from:   Start date ISO string (YYYY-MM-DD), inclusive.
        date_to:     End date ISO string (YYYY-MM-DD), inclusive.
        resolution:  "daily", "intraday", or "live". Fallback applied if
                     requested "daily"/"intraday" resolution is unavailable
                     for this field. "live" bypasses fallback entirely —
                     single always-current snapshot, no archive equivalent
                     to swap to.

    Returns:
        {
            "values":            [...],
            "fallback":          bool,   # True if resolution was downgraded
            "source_resolution": str,    # actual resolution used
        }

    Raises:
        KeyError:   if field is not registered in _FIELD_MAP.
        ValueError: if resolution is not "daily", "intraday", or "live".
    """
    if field not in _FIELD_MAP:
        raise KeyError(f"garmin_map: unknown field '{field}'")
    if resolution not in ("daily", "intraday", "live"):
        raise ValueError(f"garmin_map: invalid resolution '{resolution}'")

    definition = _FIELD_MAP[field]

    # live fields bypass the daily/intraday fallback logic entirely — single
    # always-current snapshot, date_from/date_to are ignored, no archive
    # equivalent to swap to on a miss. Three live descriptor sub-types,
    # checked in order — a field registers at most one.
    if resolution == "live":
        if definition.get("live") is not None:
            return _read_live(field)
        if definition.get("live_pct") is not None:
            return _read_live_pct(field)
        if definition.get("live_nested") is not None:
            return _read_live_nested(field)
        return {"values": [], "fallback": True, "source_resolution": "live"}

    # raw_pct fields bypass the standard daily/intraday resolution logic
    if definition.get("raw_pct") is not None:
        result = _read_raw_pct(field, date_from, date_to)
        result["fallback"] = False
        return result

    requested_available = definition[resolution] is not None

    if requested_available:
        fallback           = False
        actual_resolution  = resolution
    else:
        other = "daily" if resolution == "intraday" else "intraday"
        if definition[other] is not None:
            fallback          = True
            actual_resolution = other
        else:
            # Field registered but no resolution available — should not happen
            return {
                "values":            [],
                "fallback":          False,
                "source_resolution": resolution,
            }

    if actual_resolution == "daily":
        result = _read_daily(field, date_from, date_to)
    else:
        result = _read_intraday(field, date_from, date_to)

    result["fallback"] = fallback
    return result


def list_fields() -> list[str]:
    """Return all registered generic field names."""
    return list(_FIELD_MAP.keys())
