#!/usr/bin/env python3
"""
garmin_import.py

Importer — lädt und parst Garmin Bulk-Export Daten in das Raw-Format.

Liest einen Garmin GDPR-Export (ZIP oder entpackter Ordner) und liefert
pro Tag ein raw dict im selben Format wie garmin_api.fetch_raw().

Das dict fließt durch dieselbe Pipeline wie API-Daten:
    garmin_normalizer.normalize(raw, source="bulk")
    → garmin_quality.assess_quality()
    → garmin_collector (schreibt raw/ + summary/)

Kein Zugriff auf quality_log.json, keine API-Calls, kein File-IO
außer dem Lesen des Exports.

Unterstützte Dateien im Export:
    DI-Connect-Aggregator/UDSFile_*.json        — Tages-Aggregate (Steps, HR, Kalorien, Stress)
    DI-Connect-Wellness/*_sleepData.json        — Schlafdaten
    DI-Connect-Metrics/TrainingReadinessDTO_*.json — Training Readiness
    DI-Connect-Fitness/*_summarizedActivities.json — Aktivitäten

Public interface:
    load_bulk(path)             → Iterator[dict]  — liefert pro Tag ein raw dict
    parse_day(entries, date_str) → dict           — baut einen Tag aus gesammelten Einträgen
"""

import json
import logging
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# Relevante Dateipfade im Garmin Export (relativ zum Export-Root)
_UDS_PREFIX        = "DI_CONNECT/DI-Connect-Aggregator/"
_SLEEP_PREFIX      = "DI_CONNECT/DI-Connect-Wellness/"
_READINESS_PREFIX  = "DI_CONNECT/DI-Connect-Metrics/"
_ACTIVITIES_FILE   = "DI_CONNECT/DI-Connect-Fitness/"


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def load_bulk(path) -> Iterator[dict]:
    """
    Öffnet einen Garmin Export (ZIP oder Ordner) und liefert pro Tag ein
    raw dict — im selben Format wie garmin_api.fetch_raw().

    Verarbeitung: lesen → einen Tag bauen → yielden → repeat.
    Bei Abbruch sind bereits gelieferte Tage geschrieben.

    Parameters
    ----------
    path : str | Path — Pfad zum Garmin Export ZIP oder entpacktem Ordner

    Yields
    ------
    dict — raw dict mit "date" als YYYY-MM-DD und allen verfügbaren Feldern
    """
    path = Path(path)
    if not path.exists():
        log.error(f"  load_bulk: path not found: {path}")
        return

    try:
        if path.suffix.lower() == ".zip":
            yield from _load_from_zip(path)
        elif path.is_dir():
            yield from _load_from_dir(path)
        else:
            log.error(f"  load_bulk: unsupported path type: {path}")
    except Exception as e:
        log.error(f"  load_bulk: unexpected error: {e}")


def parse_day(entries: dict, date_str: str) -> dict:
    """
    Baut ein raw dict für einen einzelnen Tag aus den gesammelten Einträgen.

    Parameters
    ----------
    entries  : dict — gesammelte Rohdaten pro Typ:
                      {"uds": dict, "sleep": dict, "readiness": dict,
                       "activities": list}
    date_str : str  — Datum im Format YYYY-MM-DD

    Returns
    -------
    dict — raw dict kompatibel mit garmin_normalizer.normalize(source="bulk")
    """
    raw = {"date": date_str}

    uds       = entries.get("uds") or {}
    sleep     = entries.get("sleep") or {}
    readiness = entries.get("readiness") or {}
    activities = entries.get("activities") or []

    # ── user_summary (aus UDS) ──
    if uds:
        raw["user_summary"] = {
            "totalSteps":               uds.get("totalSteps"),
            "dailyStepGoal":            uds.get("dailyStepGoal"),
            "totalKilocalories":        uds.get("totalKilocalories"),
            "activeKilocalories":       uds.get("activeKilocalories"),
            "totalDistanceMeters":      uds.get("totalDistanceMeters"),
            "moderateIntensityMinutes": uds.get("moderateIntensityMinutes"),
            "vigorousIntensityMinutes": uds.get("vigorousIntensityMinutes"),
            "floorsAscended":           _meters_to_floors(uds.get("floorsAscendedInMeters")),
            "restingHeartRate":         uds.get("restingHeartRate"),
            "minHeartRate":             uds.get("minHeartRate"),
            "maxHeartRate":             uds.get("maxHeartRate"),
        }

        # ── stress (Aggregat aus UDS — kein Intraday) ──
        all_day_stress = uds.get("allDayStress") or {}
        agg_list = all_day_stress.get("aggregatorList") or []
        if agg_list and isinstance(agg_list, list):
            agg = agg_list[0]
            raw["stress"] = {
                "averageStressLevel": agg.get("averageStressLevel"),
                "maxStressLevel":     agg.get("maxStressLevel"),
                "stressDuration":     agg.get("stressDuration"),
                "restDuration":       agg.get("restDuration"),
                "lowDuration":        agg.get("lowDuration"),
                "mediumDuration":     agg.get("mediumDuration"),
                "highDuration":       agg.get("highDuration"),
            }

    # ── sleep (aus sleepData) ──
    if sleep:
        raw["sleep"] = {
            "dailySleepDTO": {
                "sleepTimeSeconds":  _total_sleep(sleep),
                "deepSleepSeconds":  sleep.get("deepSleepSeconds"),
                "lightSleepSeconds": sleep.get("lightSleepSeconds"),
                "remSleepSeconds":   sleep.get("remSleepSeconds"),
                "awakeSleepSeconds": sleep.get("awakeSleepSeconds"),
            }
        }

    # ── training_readiness (aus TrainingReadinessDTO) ──
    if readiness:
        raw["training_readiness"] = {
            "level":         readiness.get("level"),
            "feedbackLong":  readiness.get("feedbackLong"),
            "feedbackShort": readiness.get("feedbackShort"),
            "score":         None,  # nicht im Bulk-Export vorhanden
        }

    # ── activities (aus summarizedActivities) ──
    if activities:
        raw["activities"] = [
            {
                "activityName":              a.get("name"),
                "activityType":              a.get("activityType"),
                "duration":                  a.get("duration"),
                "distance":                  a.get("distance"),
                "averageHR":                 a.get("avgHr"),
                "maxHR":                     a.get("maxHr"),
                "calories":                  a.get("calories"),
                "aerobicTrainingEffect":     a.get("aerobicTrainingEffect"),
                "anaerobicTrainingEffect":   a.get("anaerobicTrainingEffect"),
            }
            for a in activities
        ]

    return raw


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — ZIP loader
# ══════════════════════════════════════════════════════════════════════════════

def _load_from_zip(zip_path: Path) -> Iterator[dict]:
    """Reads a Garmin export ZIP and yields one raw dict per day."""
    log.info(f"  load_bulk: reading ZIP {zip_path.name}")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            yield from _process_entries(names, reader=lambda n: _read_zip_json(zf, n))
    except zipfile.BadZipFile as e:
        log.error(f"  load_bulk: bad ZIP file: {e}")


def _load_from_dir(dir_path: Path) -> Iterator[dict]:
    """Reads an unpacked Garmin export folder and yields one raw dict per day."""
    log.info(f"  load_bulk: reading folder {dir_path.name}")
    # Normalize to forward slashes for consistent prefix matching
    names = [str(p.relative_to(dir_path)).replace("\\", "/") for p in dir_path.rglob("*.json")]
    yield from _process_entries(names, reader=lambda n: _read_dir_json(dir_path, n))


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — entry processing
# ══════════════════════════════════════════════════════════════════════════════

def _process_entries(names: list, reader) -> Iterator[dict]:
    """
    Scans file list, reads relevant files, indexes by date, yields per day.
    reader: callable(name) → parsed JSON object or None
    """
    # Index: date_str → {"uds": ..., "sleep": ..., "readiness": ..., "activities": [...]}
    by_date: dict[str, dict] = {}

    # ── UDS files ──
    uds_files = [n for n in names if _UDS_PREFIX in n and "UDSFile_" in n and n.endswith(".json")]
    for name in uds_files:
        data = reader(name)
        if not isinstance(data, list):
            continue
        for entry in data:
            d = entry.get("calendarDate")
            if not _valid_date(d):
                continue
            by_date.setdefault(d, {})["uds"] = entry

    # ── Sleep files ──
    sleep_files = [n for n in names if _SLEEP_PREFIX in n and "sleepData" in n and n.endswith(".json")]
    for name in sleep_files:
        data = reader(name)
        if not isinstance(data, list):
            continue
        for entry in data:
            d = entry.get("calendarDate")
            if not _valid_date(d):
                continue
            by_date.setdefault(d, {})["sleep"] = entry

    # ── Training Readiness files ──
    readiness_files = [n for n in names if _READINESS_PREFIX in n and "TrainingReadinessDTO" in n and n.endswith(".json")]
    for name in readiness_files:
        data = reader(name)
        if not isinstance(data, list):
            continue
        for entry in data:
            d = entry.get("calendarDate")
            if not _valid_date(d):
                continue
            by_date.setdefault(d, {})["readiness"] = entry

    # ── Activities file ──
    act_files = [n for n in names if _ACTIVITIES_FILE in n and "summarizedActivities" in n and n.endswith(".json")]
    for name in act_files:
        data = reader(name)
        if not isinstance(data, list):
            continue
        # summarizedActivities is a list of {summarizedActivitiesExport: [...]}
        for wrapper in data:
            acts = wrapper.get("summarizedActivitiesExport") or []
            for act in acts:
                d = _timestamp_to_date(act.get("startTimeLocal"))
                if not _valid_date(d):
                    continue
                by_date.setdefault(d, {}).setdefault("activities", []).append(act)

    log.info(f"  load_bulk: {len(by_date)} days found in export")

    # Yield one day at a time — sorted chronologically
    for date_str in sorted(by_date.keys()):
        yield parse_day(by_date[date_str], date_str)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — file readers
# ══════════════════════════════════════════════════════════════════════════════

def _read_zip_json(zf: zipfile.ZipFile, name: str):
    """Reads and parses a JSON file from an open ZipFile."""
    try:
        with zf.open(name) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"  load_bulk: could not read {name}: {e}")
        return None


def _read_dir_json(base: Path, name: str):
    """Reads and parses a JSON file from a directory."""
    try:
        with open(base / name, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"  load_bulk: could not read {name}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — helpers
# ══════════════════════════════════════════════════════════════════════════════

def _valid_date(d) -> bool:
    """Returns True if d is a valid YYYY-MM-DD string."""
    if not isinstance(d, str) or len(d) != 10:
        return False
    try:
        date.fromisoformat(d)
        return True
    except ValueError:
        return False


def _timestamp_to_date(ts) -> str | None:
    """
    Converts a Garmin local timestamp to YYYY-MM-DD.
    Garmin stores startTimeLocal as seconds since epoch (local time).
    """
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone
        # Local timestamp — interpret as UTC to get the date
        dt = datetime.fromtimestamp(int(ts) / 1000 if int(ts) > 1e10 else int(ts),
                                    tz=timezone.utc)
        return dt.date().isoformat()
    except Exception:
        return None


def _meters_to_floors(meters) -> int | None:
    """Converts meters ascended to floor count (1 floor ≈ 3 meters)."""
    if meters is None:
        return None
    try:
        return round(float(meters) / 3.0)
    except (TypeError, ValueError):
        return None


def _total_sleep(sleep: dict) -> int | None:
    """Calculates total sleep seconds from sleep stage components."""
    keys = ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")
    values = [sleep.get(k) for k in keys]
    if all(v is None for v in values):
        return None
    return sum(v or 0 for v in values)
