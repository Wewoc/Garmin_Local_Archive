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


# ── Device offset resolution — v1.6.5.6 Intraday Timestamp Timezone Bug ────────
#
#  Garmin's raw/live sections carry both a GMT and a Local timestamp for the
#  start and end of the covered period (e.g. startTimestampGMT/Local,
#  endTimestampGMT/Local). The difference is the device's UTC offset for
#  that day — derived from the data itself, no zoneinfo, no system clock.
#
#  If start-offset and end-offset differ, the day crosses a DST transition
#  (see NOTES v1.6.5.6 / A5). This is detected, not corrected — the offset
#  used remains the start-of-day value, consistent with how Garmin itself
#  renders the day (A6).

_OFFSET_SOURCE_SECTIONS = ("heart_rates", "stress", "respiration", "spo2")


def _parse_naive(ts: str) -> datetime:
    """Parse a Garmin ISO timestamp string (naive, ignores sub-second digits)."""
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")


def _section_offset(section_data: dict) -> tuple[float, float] | None:
    """
    Compute (start_offset_hours, end_offset_hours) from a section's
    Start/End Timestamp GMT/Local pair. Returns None if either pair is
    missing or malformed.
    """
    s_gmt = section_data.get("startTimestampGMT")
    s_loc = section_data.get("startTimestampLocal")
    e_gmt = section_data.get("endTimestampGMT")
    e_loc = section_data.get("endTimestampLocal")
    if not all(isinstance(x, str) for x in (s_gmt, s_loc, e_gmt, e_loc)):
        return None
    try:
        start_off = (_parse_naive(s_loc) - _parse_naive(s_gmt)).total_seconds() / 3600
        end_off   = (_parse_naive(e_loc) - _parse_naive(e_gmt)).total_seconds() / 3600
        return start_off, end_off
    except ValueError:
        return None


def _device_offset(data: dict) -> tuple[float, bool]:
    """
    Determine the device UTC offset (hours) for a raw/live snapshot day.
    Tries _OFFSET_SOURCE_SECTIONS in fixed order, first complete GMT/Local
    pair wins. Returns (offset_hours, dst_transition) — dst_transition is
    True when start-of-day and end-of-day offset differ (day crosses a
    DST change). Returns (0.0, False) if no section has a usable pair,
    with a warning — never a silent UTC fallback, never an exception.
    """
    for section_name in _OFFSET_SOURCE_SECTIONS:
        section_data = data.get(section_name)
        if not isinstance(section_data, dict):
            continue
        offsets = _section_offset(section_data)
        if offsets is None:
            continue
        start_off, end_off = offsets
        return start_off, (start_off != end_off)
    log.warning("garmin_map: no usable GMT/Local offset pair found for this day — defaulting to UTC (0h)")
    return 0.0, False


def _ts_to_iso(ts, offset_hours: float = 0.0) -> str:
    """
    Normalize a Garmin timestamp (ms epoch or ISO string) to ISO-8601,
    shifted by offset_hours (device UTC offset — see _device_offset()).
    Stays naive, without an offset suffix, by design (E9, NOTES v1.6.5.6) —
    downstream Plotly consumers would otherwise re-apply the browser's own
    timezone and reintroduce the offset error at a different layer.
    """
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None)
        else:
            dt = _parse_naive(str(ts))
        dt += timedelta(hours=offset_hours)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return str(ts)


def _extract_series(arr: list, section_data: dict, extract: dict,
                     offset_hours: float = 0.0) -> list:
    """
    Normalize a raw Garmin array to [{"ts": str, "value": float}, ...].
    Uses the extract descriptor from _FIELD_MAP to handle field-specific
    array structures without leaking Garmin internals to callers.

    offset_hours: device UTC offset for this day (see _device_offset()),
    applied to every timestamp via _ts_to_iso(). Not to be confused with
    `offset` below, which is Garmin's own value-offset (e.g.
    stressChartValueOffset) subtracted from the measurement value.
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
            result.append({"ts": _ts_to_iso(ts, offset_hours), "value": v})
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
    Normalizes each day's array to [{"ts": str, "value": float}, ...],
    timestamps shifted to the device's local time for that day
    (see _device_offset(), NOTES v1.6.5.6).
    Returns {"values": [{"date": str, "series": list|None, "dst_transition": bool}, ...],
             "source_resolution": "intraday"}.
    series is None if the file is missing or the field is absent.
    series is [] if the file exists but the array is empty after normalization.
    dst_transition is True if this day's device offset changes between the
    start and end of the covered period — the series is still built using
    the start-of-day offset (A6), the flag only signals the caller that
    this day is affected. Always False when series is None.
    """
    section, array_key, extract = _FIELD_MAP[field]["intraday"]

    values = []
    for ds in _date_range(date_from, date_to):
        f = cfg.RAW_DIR / f"{cfg.RAW_FILE_PREFIX}{ds}.json"
        series = None
        dst_transition = False
        if f.exists():
            try:
                data         = json.loads(f.read_text(encoding="utf-8"))
                offset_hours, dst_transition = _device_offset(data)
                section_data = data.get(section)
                if isinstance(section_data, dict):
                    arr = section_data.get(array_key)
                    if isinstance(arr, list):
                        series = _extract_series(arr, section_data, extract, offset_hours)
                elif isinstance(section_data, list):
                    series = _extract_series(section_data, {}, extract, offset_hours)
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"garmin_map: could not read {f}: {e}")
        values.append({"date": ds, "series": series, "dst_transition": dst_transition})

    return {"values": values, "source_resolution": "intraday"}


def _read_live(field: str) -> dict:
    """
    Read an intraday series from the live snapshot (cfg.LIVE_FILE).
    Same array-extraction logic as _read_intraday(), single always-current
    source instead of a dated file — date_from/date_to are not used.
    Timestamps are shifted to the device's local time
    (see _device_offset(), NOTES v1.6.5.6).
    Returns {"values": [{"date": str, "series": list, "dst_transition": bool}],
             "fallback": bool, "source_resolution": "live"}.
    Missing LIVE_FILE or missing field in the snapshot → fallback=True,
    empty values, never an exception.
    """
    section, array_key, extract = _FIELD_MAP[field]["live"]

    series = None
    snapshot_date = None
    dst_transition = False
    if cfg.LIVE_FILE.exists():
        try:
            data          = json.loads(cfg.LIVE_FILE.read_text(encoding="utf-8"))
            snapshot_date = data.get("date")
            offset_hours, dst_transition = _device_offset(data)
            section_data  = data.get(section)
            if isinstance(section_data, dict):
                arr = section_data.get(array_key)
                if isinstance(arr, list):
                    series = _extract_series(arr, section_data, extract, offset_hours)
            elif isinstance(section_data, list):
                series = _extract_series(section_data, {}, extract, offset_hours)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"garmin_map: could not read {cfg.LIVE_FILE}: {e}")

    if series is None:
        return {"values": [], "fallback": True, "source_resolution": "live"}

    return {
        "values":            [{"date": snapshot_date, "series": series, "dst_transition": dst_transition}],
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
