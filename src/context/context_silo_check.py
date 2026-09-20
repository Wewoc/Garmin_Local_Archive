#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
context/context_silo_check.py
Garmin Local Archive — Context-Archive Ist-Stand-Erfassung

Read-only inventory of context_data/: which days have a file per source
(weather/pollen/brightsky/airquality), and what coordinate/place/country
is on record for each day. First step of the planned Context Archive
Integrity Check (ROADMAP v1.7.2.3) — pure "Ist" capture, no Soll-vs-Ist
coordinate validation yet (that is a separate, later step, once the real
numbers from this pass are known).

Leaf-Node in spirit of garmin/garmin_silo_check.py: does not import
context_collector.py — its _load_csv()/_ensure_csv() etc. are that
module's own internal helpers, and _ensure_csv() has a file-creation
side effect a read-only check must never trigger. local_config.csv
parsing is duplicated here, minimally — same "small local helper over
cross-module reuse" precedent garmin_silo_check.py already sets.

Brightsky exemption: mirrors the DACH bounding-box skip
context_collector.run() already applies at fetch time (47.2-55.1 lat,
5.8-15.1 lon) — a brightsky day outside that box is expected, not a
defect, so it is excluded from missing_days["brightsky"].

Coordinate validation (v1.7.2.3 Baustein 2, added after a real-archive
Ist-Stand run showed the naive approach would misfire): a day's stored
coordinate is compared against its expected location (CSV row, or the
current GUI default) via great-circle distance, not exact equality — a
real archive run showed a legitimate ~27m drift after a Settings
location tweak, which an exact-match check would have flagged as
"broken" for every one of the ~2800 days fetched before that tweak.
Only a distance beyond COORDINATE_DRIFT_RADIUS_KM counts as a defect.
0.0/0.0 and out-of-range values are always a defect regardless of
distance — those indicate a fetch/write bug, not normal drift.

Public API:
  check_context_archive(base_dir, default_lat=0.0, default_lon=0.0,
                         radius_km=COORDINATE_DRIFT_RADIUS_KM) -> dict
"""

import csv
import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_SOURCES = ["weather", "pollen", "brightsky", "airquality"]
_FILE_PREFIX = {
    "weather":    "weather_",
    "pollen":     "pollen_",
    "brightsky":  "brightsky_",
    "airquality": "airquality_",
}
# lat_min, lat_max, lon_min, lon_max — same box as context_collector.run()
_BRIGHTSKY_BBOX = (47.2, 55.1, 5.8, 15.1)

# Default tolerance for coordinate drift — small re-geocoding/Settings
# adjustments stay within this, a genuinely wrong location (wrong city,
# wrong country, 0/0) does not. Overridable per call, not exposed in the
# GUI (single narrow use case, not worth a settings field yet).
COORDINATE_DRIFT_RADIUS_KM = 2.0
_EARTH_RADIUS_KM = 6371.0


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _read_date_range(base: Path) -> tuple[str, str] | tuple[None, None]:
    """Archive date range from quality_log.json — same source
    context_collector._resolve_date_range() uses, read directly here to
    avoid importing garmin_quality into a context/-only module."""
    qlog = base / "garmin_data" / "log" / "quality_log.json"
    if not qlog.exists():
        return None, None
    try:
        data = json.loads(qlog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("context_silo_check: could not read quality_log.json — %s", exc)
        return None, None
    dates = sorted(e["date"] for e in data.get("days", []) if e.get("date"))
    if not dates:
        return None, None
    date_to = min(dates[-1], date.today().isoformat())
    return dates[0], date_to


def _read_csv_entries(base: Path) -> list[dict]:
    """Location periods from local_config.csv — date_from/date_to/country/
    place/lat/lon per row. Minimal re-parse of the same format
    context_collector._load_csv() reads; see module docstring for why
    that function is not imported directly."""
    csv_path = base / "local_config.csv"
    entries: list[dict] = []
    if not csv_path.exists():
        return entries
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("date_from"):
                    continue
                parts = next(csv.reader([line], delimiter=";"))
                if len(parts) < 6:
                    continue
                try:
                    entries.append({
                        "date_from": parts[0].strip(),
                        "date_to":   parts[1].strip(),
                        "country":   parts[2].strip() or None,
                        "place":     parts[3].strip() or None,
                        "lat":       float(parts[4].strip()),
                        "lon":       float(parts[5].strip()),
                    })
                except (ValueError, IndexError):
                    continue   # skip rows with missing/invalid coordinates
    except OSError as exc:
        log.warning("context_silo_check: could not read local_config.csv — %s", exc)
    return entries


def _location_for_day(day: str, csv_entries: list[dict],
                       default_lat: float, default_lon: float) -> dict:
    """CSV entries take priority (exact date-range match); falls back to
    the GUI default location — same precedence as
    context_collector._build_location_map(). A day covered only by the
    default has no place/country on record anywhere in the app."""
    for e in csv_entries:
        if e["date_from"] <= day <= e["date_to"]:
            return {"lat": e["lat"], "lon": e["lon"],
                    "place": e["place"], "country": e["country"]}
    return {"lat": default_lat, "lon": default_lon, "place": None, "country": None}


def _existing_filenames(base: Path, source: str) -> set[str]:
    """Date strings for existing summary/ files of one source."""
    d = base / "context_data" / source / "summary"
    if not d.exists():
        return set()
    prefix = _FILE_PREFIX[source]
    return {f.stem.replace(prefix, "", 1) for f in d.glob(f"{prefix}*.json")}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km — stdlib-only, sufficient at this
    precision (a few km, not surveying-grade)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2)
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _read_stored_coordinate(base: Path, source: str, day: str) -> tuple[float, float] | None:
    """Reads latitude/longitude from one source's file for one day.
    Returns None if the file is missing/unreadable/has no coordinate —
    caller treats that as "nothing to validate", not a coordinate
    defect (a missing file is already covered by missing_days)."""
    path = base / "context_data" / source / "summary" / f"{_FILE_PREFIX[source]}{day}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lat, lon = data.get("latitude"), data.get("longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _check_coordinate(base: Path, source: str, day: str,
                       expected: tuple[float, float], radius_km: float) -> dict | None:
    """Returns a bad_coordinates finding dict, or None if the stored
    coordinate is fine (missing/unreadable file also returns None — see
    _read_stored_coordinate())."""
    stored = _read_stored_coordinate(base, source, day)
    if stored is None:
        return None
    lat, lon = stored

    if lat == 0.0 and lon == 0.0:
        reason, distance = "zero", None
    elif not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        reason, distance = "out_of_range", None
    else:
        distance = round(_haversine_km(lat, lon, expected[0], expected[1]), 3)
        reason = "drift" if distance > radius_km else None

    if reason is None:
        return None
    return {
        "date": day, "source": source, "reason": reason,
        "stored": stored, "expected": expected, "distance_km": distance,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def check_context_archive(base_dir: str, default_lat: float = 0.0,
                           default_lon: float = 0.0,
                           radius_km: float = COORDINATE_DRIFT_RADIUS_KM) -> dict:
    """
    Read-only Ist-Stand-Erfassung of context_data/, plus coordinate
    plausibility validation.

    Returns:
      missing_days    : {source: [date_str, ...]} — days with no summary/
                        file for that source. brightsky excludes days
                        outside the DACH bounding box (expected, not a
                        defect — see module docstring).
      bad_coordinates : [{"date", "source", "reason", "stored", "expected",
                        "distance_km"}, ...] — reason is "zero",
                        "out_of_range", or "drift" (beyond radius_km of
                        the expected location). Only checked for days
                        that have a file — a missing file is already
                        covered by missing_days, not double-reported here.
      day_location    : [{"date", "lat", "lon", "place", "country"}, ...],
                        one entry per day in range, sorted with days that
                        have no CSV-backed place/country first.
      totals          : {"days_in_range": int, source: file_count, ...}
      checked_at      : ISO-8601 timestamp
    """
    base = Path(base_dir)
    result = {
        "missing_days": {s: [] for s in _SOURCES},
        "bad_coordinates": [],
        "day_location": [],
        "totals": {"days_in_range": 0, **{s: 0 for s in _SOURCES}},
        "checked_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    date_from, date_to = _read_date_range(base)
    if not date_from:
        return result

    csv_entries = _read_csv_entries(base)
    existing = {s: _existing_filenames(base, s) for s in _SOURCES}
    for s in _SOURCES:
        result["totals"][s] = len(existing[s])

    d = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    days_in_range = 0
    while d <= end:
        ds = d.isoformat()
        days_in_range += 1
        loc = _location_for_day(ds, csv_entries, default_lat, default_lon)
        result["day_location"].append({"date": ds, **loc})
        expected = (loc["lat"], loc["lon"])

        for s in _SOURCES:
            if ds in existing[s]:
                finding = _check_coordinate(base, s, ds, expected, radius_km)
                if finding:
                    result["bad_coordinates"].append(finding)
                continue
            if s == "brightsky":
                lat_min, lat_max, lon_min, lon_max = _BRIGHTSKY_BBOX
                if not (lat_min <= loc["lat"] <= lat_max
                        and lon_min <= loc["lon"] <= lon_max):
                    continue   # outside Germany — not a defect
            result["missing_days"][s].append(ds)

        d += timedelta(days=1)

    result["totals"]["days_in_range"] = days_in_range
    result["day_location"].sort(key=lambda e: (e["place"] is not None, e["date"]))

    log.debug(
        "context_silo_check: done — days=%d, missing=%s, bad_coordinates=%d",
        days_in_range, {s: len(v) for s, v in result["missing_days"].items()},
        len(result["bad_coordinates"]),
    )
    return result
