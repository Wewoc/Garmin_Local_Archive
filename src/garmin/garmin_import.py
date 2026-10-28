#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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
    DI-Connect-Wellness/*_healthStatusData.json — Gesundheitsstatus, ein Eintrag je Tag (v1.7.6.7)
    DI-Connect-Wellness/*_AbnormalHrEvents.json — Pulsalarm-Ereignisse, mehrere je Tag (v1.7.6.7)

Dazu gesicherte Familien (_SAVED_FAMILIES, v1.7.6.7): gear, personalRecord, courses, Zonen. Sie werden nicht
ausgewertet, aber gelesen, damit der read_hook ihre Bytes bekommt (der Bulk-Speicher hebt sie auf).

Public interface:
    load_bulk(path)             → Iterator[dict]  — liefert pro Tag ein raw dict
    load_bulk_with_entries(path, read_hook=None, inventory=None)
                                → Iterator[(dict, dict)] — pro Tag das raw dict UND die Einträge,
                                  aus denen es gebaut wurde; read_hook(name, bytes) wird für jede
                                  gelesene JSON-Datei gerufen (v1.7.6.1, Bulk-Speicher);
                                  inventory (dict) wird mit build_inventory() des Exports gefüllt
                                  und zählt beim Lesen "unreadable" / "too_large" (v1.7.6.7)
    build_inventory(names)      → dict            — was der Export an JSON-Dateien hält: Zahlen und
                                  Ordnergruppen, nie ein Dateiname (v1.7.6.7)
    parse_day(entries, date_str) → dict           — baut einen Tag aus gesammelten Einträgen
    detect_kind(data)           → str | None      — Art einer Export-JSON-Datei am Inhalt (v1.7.6.5)
    days_from_originals(originals, on_unrecognised=None, on_conflict=None)
                                → Iterator[(dict, dict)] — wie load_bulk_with_entries, aber aus bereits
                                  gelesenen Dateien ohne Pfad; Art am Inhalt (v1.7.6.5, Neuaufbau)
"""

import json
import logging
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

# Relevante Dateipfade im Garmin Export (relativ zum Export-Root)
_UDS_PREFIX        = "DI_CONNECT/DI-Connect-Aggregator/"
_SLEEP_PREFIX      = "DI_CONNECT/DI-Connect-Wellness/"
_READINESS_PREFIX  = "DI_CONNECT/DI-Connect-Metrics/"
_ACTIVITIES_FILE   = "DI_CONNECT/DI-Connect-Fitness/"
_ROUTING_PREFIX    = "DI_CONNECT/DI-Connect-Routing/"

# A JSON file of the export larger than this is not read, not hashed and not kept (v1.7.6.7): the largest
# file of an export is below 1 MB, the limit only protects against a foreign or damaged file. The same
# value as the FIT scanner's limit for one file.
MAX_JSON_BYTES = 64 * 1024 * 1024


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
    yield from _load(path, with_entries=False, read_hook=None)


def load_bulk_with_entries(path, read_hook=None, inventory=None) -> Iterator[tuple]:
    """
    Wie load_bulk(), liefert aber pro Tag ein Paar (raw dict, Einträge): die Einträge sind das
    Dict {"uds": ..., "sleep": ..., "readiness": ..., "activities": [...], "health_status": ...,
    "alert_events": [...]}, aus dem parse_day() den Tag gebaut hat (nur die Teile, die der Export für
    diesen Tag hat). Damit kann der Aufrufer den Herkunftsnachweis je Eintrag bilden (v1.7.6.1,
    Bulk-Speicher).

    read_hook : callable(name, data: bytes) | None — wird für jede JSON-Datei gerufen, bevor sie
        geparst wird (zum Hashen und Aufheben der Originale). Der Hook darf nicht werfen: eine
        Ausnahme beendet die Iteration wie jeder unerwartete Fehler (geloggt).
    inventory : dict | None — wird, sobald die Dateiliste des Exports bekannt ist, mit build_inventory()
        gefüllt (vor dem ersten Tag); beim Lesen zählen "unreadable" und "too_large" darin hoch (v1.7.6.7).
    """
    yield from _load(path, with_entries=True, read_hook=read_hook, inventory=inventory)


def days_from_originals(originals, on_unrecognised=None, on_conflict=None) -> Iterator[tuple]:
    """
    Wie load_bulk_with_entries(), aber aus Dateien, die schon gelesen sind und keinen Pfad tragen
    (die aufgehobenen Originale in bulk/source, v1.7.6.5): die Art jeder Datei kommt aus ihrem Inhalt
    (detect_kind), nicht aus dem Namen. Liefert pro Tag das Paar (raw dict, Einträge), nach Datum sortiert.

    originals       : iterable of (label, parsed JSON) — die Reihenfolge bestimmt der Aufrufer; sie
                      entscheidet, welcher von zwei verschiedenen UDS- oder Schlaf-Einträgen eines Datums
                      gewinnt (der später gegebene) und die Reihenfolge der Aktivitäten eines Tages.
                      Bei Readiness entscheidet der timestamp, nicht die Reihenfolge.
    on_unrecognised : callable(label) | None — für jede Datei, deren Art nicht erkannt wird (übersprungen)
    on_conflict     : callable(kind, date_str) | None — wenn ein UDS- oder Schlaf-Eintrag einen anderen
                      desselben Datums ersetzt
    """
    by_date: dict[str, dict] = {}
    for label, data in originals:
        kind = detect_kind(data)
        if kind is None:
            if on_unrecognised is not None:
                on_unrecognised(label)
            continue
        _index_file(by_date, kind, label, data, on_conflict)
    yield from _days_from_entries(by_date, with_entries=True)


def _load(path, with_entries: bool, read_hook, inventory=None) -> Iterator:
    """Öffnet den Export (ZIP oder Ordner) und liefert die Tage — die Arbeit hinter load_bulk()."""
    path = Path(path)
    if not path.exists():
        log.error(f"  load_bulk: path not found: {path}")
        return

    try:
        if path.suffix.lower() == ".zip":
            yield from _load_from_zip(path, with_entries, read_hook, inventory)
        elif path.is_dir():
            yield from _load_from_dir(path, with_entries, read_hook, inventory)
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
    health_status = entries.get("health_status") or {}
    alert_events = entries.get("alert_events") or []

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
            # The export's "restingHeartRate" is the 7-day average; the value of
            # the day is "currentDayRestingHeartRate". A missing day value stays
            # empty — it never falls back to the average (v1.7.5.7).
            "restingHeartRate":         uds.get("currentDayRestingHeartRate"),
            "lastSevenDaysAvgRestingHeartRate": uds.get("restingHeartRate"),
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
            "score":         readiness.get("score"),
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

    # ── health_status / alert_events (v1.7.6.7) — optional, unverändert wie geliefert ──
    # Nur gespeichert: der Broker liest sie noch nicht (eigener späterer Schritt). Die Ereignisse eines
    # Tages stehen in fester Reihenfolge (Zeitpunkt, dann Text), damit Import und Neuaufbau dieselbe Datei
    # ergeben, gleich in welcher Reihenfolge die Dateien gelesen wurden.
    if health_status:
        raw["health_status"] = health_status
    if alert_events:
        raw["alert_events"] = sorted(alert_events, key=_alert_sort_key)

    return raw


def detect_kind(data) -> str | None:
    """
    Art einer geparsten Export-JSON-Datei am Inhalt (v1.7.6.5, P2.2) — für Originale ohne Pfad.

    Returns "uds" | "sleep" | "readiness" | "activities" | "health_status" | "alert_events" (die Schlüssel
    des entries-Dicts von parse_day) oder None = nicht erkannt. Die gesicherten Familien (_SAVED_FAMILIES)
    haben keine Regel: ihr Aufbau ist nicht belegt, sie bleiben None (v1.7.6.7). Eine Art gilt, wenn ihre Schlüsselregel bei mindestens
    einem Eintrag trifft; keine oder mehrere Arten ergeben None, es wird nie geraten.
    Reine Funktion: liest nichts, schreibt nichts, loggt nichts — Melden und Überspringen von
    None ist Sache des Aufrufers. Das Datum prüft sie nicht (das filtert die Tagesschleife).
    """
    if not isinstance(data, list):
        return None
    kinds = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if "summarizedActivitiesExport" in entry:
            kinds.add("activities")
        if "totalSteps" in entry and "uuid" in entry:
            kinds.add("uds")
        if "sleepStartTimestampGMT" in entry or "deepSleepSeconds" in entry:
            kinds.add("sleep")
        if "acwrFactorPercent" in entry or "recoveryTimeFactorPercent" in entry:
            kinds.add("readiness")
        if "metrics" in entry and "outliersCount" in entry:
            kinds.add("health_status")
        if "abnormalHrEventGMT" in entry:
            kinds.add("alert_events")
    return next(iter(kinds)) if len(kinds) == 1 else None


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — ZIP loader
# ══════════════════════════════════════════════════════════════════════════════

def _load_from_zip(zip_path: Path, with_entries: bool = False, read_hook=None, inventory=None) -> Iterator:
    """Reads a Garmin export ZIP and yields one raw dict per day (with_entries: (dict, entries))."""
    log.info(f"  load_bulk: reading ZIP {zip_path.name}")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            yield from _process_entries(names, reader=lambda n: _read_zip_json(zf, n, read_hook, inventory),
                                        with_entries=with_entries, inventory=inventory)
    except zipfile.BadZipFile as e:
        log.error(f"  load_bulk: bad ZIP file: {e}")


def _load_from_dir(dir_path: Path, with_entries: bool = False, read_hook=None, inventory=None) -> Iterator:
    """Reads an unpacked Garmin export folder and yields one raw dict per day (with_entries: (dict, entries))."""
    log.info(f"  load_bulk: reading folder {dir_path.name}")
    # Normalize to forward slashes for consistent prefix matching
    names = [str(p.relative_to(dir_path)).replace("\\", "/") for p in dir_path.rglob("*.json")]
    yield from _process_entries(names, reader=lambda n: _read_dir_json(dir_path, n, read_hook, inventory),
                                with_entries=with_entries, inventory=inventory)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — entry processing
# ══════════════════════════════════════════════════════════════════════════════

def _entry_time(entry):
    """
    "timestamp" of an entry as datetime, or None (missing, not a string, not readable).
    Only "YYYY-MM-DD" + "T" or " " + "HH:MM:SS" is read: fractions of a second and a zone suffix
    are ignored (datetime.fromisoformat reads ".0" only from Python 3.11, the README says 3.10+).
    """
    ts = entry.get("timestamp")
    if not isinstance(ts, str):
        return None
    try:
        return datetime.strptime(ts[:19].replace(" ", "T"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _later_entry_wins(candidate: dict, current: dict) -> bool:
    """
    Choice between two entries of the same date, independent of the order they were read in
    (v1.7.6.5, P2.2a): an entry with a readable "timestamp" beats one without, the later one
    beats the earlier one; with the same time (or none on both sides) the smaller canonical
    JSON text wins. True = candidate replaces current.
    """
    t_new, t_old = _entry_time(candidate), _entry_time(current)
    if t_new != t_old:
        if t_old is None:
            return True
        if t_new is None:
            return False
        return t_new > t_old
    def _canon(e):
        return json.dumps(e, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return _canon(candidate) < _canon(current)


def _alert_sort_key(event):
    """Order of the pulse-alert events of one day: the time of the event, then the canonical text."""
    text = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    when = event.get("abnormalHrEventGMT") if isinstance(event, dict) else None
    return (when if isinstance(when, str) else "", text)


# The kinds of file in the export, in the order they are read: kind (the key in the entries of a day),
# folder in the export, part of the file name, and how the entries of one date are kept (mode):
#   single    one entry per date; an entry read later replaces an earlier, different one (on_conflict)
#   latest    one entry per date; the one with the latest "timestamp" wins (_later_entry_wins)
#   wrapped   a list of wrappers {summarizedActivitiesExport: [...]}; the date is that of startTimeLocal;
#             every activity is kept, as a list
#   list      every entry is kept, as a list; an entry that is already in the list is not added again
#             (neighbouring files may overlap)
_KINDS = (
    ("uds",           _UDS_PREFIX,       "UDSFile_",             "single"),
    ("sleep",         _SLEEP_PREFIX,     "sleepData",            "single"),
    ("readiness",     _READINESS_PREFIX, "TrainingReadinessDTO", "latest"),
    ("activities",    _ACTIVITIES_FILE,  "summarizedActivities", "wrapped"),
    ("health_status", _SLEEP_PREFIX,     "healthStatusData",     "single"),
    ("alert_events",  _SLEEP_PREFIX,     "AbnormalHrEvents",     "list"),
)
_KIND_MODE = {kind: mode for kind, _prefix, _keyword, mode in _KINDS}

# Families of the export that are only kept: they are read (so that read_hook gets their bytes and the bulk
# store keeps the original) but nothing is taken from them. Only a name that matches is kept — a file of an
# unknown family is not (it is only counted by build_inventory). family, folder, pattern for the file name
# (the name carries the e-mail address of the account in front, so the pattern anchors at the end).
# The patterns of gear, personalRecord and courses are taken from REFERENCE_GARMIN_EXPORT, the zones from an
# export; none of the first three was available as a sample (v1.7.6.7).
_SAVED_FAMILIES = (
    ("gear",            _ACTIVITIES_FILE, re.compile(r"(?:^|_)gear\.json$")),
    ("personalRecord",  _ACTIVITIES_FILE, re.compile(r"(?:^|_)personalRecord\.json$")),
    ("courses",         _ROUTING_PREFIX,  re.compile(r"courses.*\.json$")),
    ("zones",           _SLEEP_PREFIX,    re.compile(r"(?:^|_)(?:heartRateZones|powerZones)\.json$")),
)


def _saved_family(name: str) -> str | None:
    """The family of _SAVED_FAMILIES a file name belongs to, None if it belongs to none."""
    folder, _, base = name.rpartition("/")
    for family, prefix, pattern in _SAVED_FAMILIES:
        if (folder + "/") == prefix and pattern.search(base):
            return family
    return None


def _kind_of_name(name: str) -> str | None:
    """The kind of _KINDS a file name belongs to (folder prefix and part of the name), None if none."""
    for kind, prefix, keyword, _mode in _KINDS:
        if prefix in name and keyword in name and name.endswith(".json"):
            return kind
    return None


def build_inventory(names) -> dict:
    """
    What the export holds in JSON files, from the file names alone (v1.7.6.7, E6): numbers and folder
    groups, never a file name — the names carry the e-mail address of the account. The same function serves
    the preview and the import, so both show the same.

    Returns {"read":  {kind: files}   for every kind of _KINDS (0 when the export has none),
             "kept":  {family: files} for every family of _SAVED_FAMILIES,
             "unknown": {"files": n, "folders": [folder, ...]} the JSON files of no known kind or family and
                        the folders (sorted) they lie in; a folder with an "@" in it is shown as "<hidden>",
             "unreadable": 0, "too_large": 0}  (the last two count up while the files are read)
    A name counts when it ends with ".json". A file that matches a kind and a family counts as the kind.
    """
    read = {kind: 0 for kind, *_ in _KINDS}
    kept = {family: 0 for family, *_ in _SAVED_FAMILIES}
    unknown_files, folders = 0, set()
    for name in names:
        if not isinstance(name, str) or not name.endswith(".json"):
            continue
        kind = _kind_of_name(name)
        if kind is not None:
            read[kind] += 1
            continue
        family = _saved_family(name)
        if family is not None:
            kept[family] += 1
            continue
        unknown_files += 1
        folder = name.rpartition("/")[0] or "(top level)"
        folders.add("<hidden>" if "@" in folder else folder)
    return {"read": read, "kept": kept, "unknown": {"files": unknown_files, "folders": sorted(folders)},
            "unreadable": 0, "too_large": 0}


def _index_file(by_date: dict, kind: str, label: str, data, on_conflict=None) -> None:
    """
    Enters the entries of one parsed export file of this kind into by_date (date_str → entries of the
    day). label names the file in warnings. Nothing is raised: what is not a list, not an object or has
    no valid date is skipped.
    on_conflict(kind, date_str) is called when a UDS or sleep entry replaces a different entry of the same
    date (the entry read later wins, as always); the import by name passes none.
    """
    if not isinstance(data, list):
        return
    mode = _KIND_MODE.get(kind, "single")
    if mode == "wrapped":
        # summarizedActivities is a list of {summarizedActivitiesExport: [...]}
        for wrapper in data:
            if not isinstance(wrapper, dict):
                log.warning(f"  load_bulk: {label} — malformed activities wrapper (not an object), skipped: {wrapper!r}")
                continue
            acts = wrapper.get("summarizedActivitiesExport") or []
            for act in acts:
                if not isinstance(act, dict):
                    log.warning(f"  load_bulk: {label} — malformed activity entry (not an object), skipped: {act!r}")
                    continue
                d = _timestamp_to_date(act.get("startTimeLocal"))
                if not _valid_date(d):
                    continue
                by_date.setdefault(d, {}).setdefault("activities", []).append(act)
        return
    for entry in data:
        # Fix 2 (v1.7.4.6) — an entry that is not an object (e.g. a stray
        # string) is skipped with a warning naming the file, instead of
        # raising AttributeError on .get() and losing every day in the
        # whole export (load_bulk()'s outer try/except used to catch this
        # one bad entry and discard the entire generator before any day
        # was yielded).
        if not isinstance(entry, dict):
            log.warning(f"  load_bulk: {label} — malformed entry (not an object), skipped: {entry!r}")
            continue
        d = entry.get("calendarDate")
        if not _valid_date(d):
            continue
        if mode == "latest":
            current = by_date.get(d, {}).get(kind)
            if current is None or _later_entry_wins(entry, current):
                by_date.setdefault(d, {})[kind] = entry
        elif mode == "list":
            entries_of_day = by_date.setdefault(d, {}).setdefault(kind, [])
            if entry not in entries_of_day:
                entries_of_day.append(entry)
        else:
            previous = by_date.get(d, {}).get(kind)
            if on_conflict is not None and previous is not None and previous != entry:
                on_conflict(kind, d)
            by_date.setdefault(d, {})[kind] = entry


def _collect_entries(names: list, reader) -> dict:
    """
    Scans file list, reads relevant files (kind by file name), indexes by date.
    reader: callable(name) → parsed JSON object or None
    Returns date_str → {"uds": ..., "sleep": ..., "readiness": ..., "activities": [...]}
    """
    # Index: date_str → {"uds": ..., "sleep": ..., "readiness": ..., "activities": [...]}
    by_date: dict[str, dict] = {}
    for kind, prefix, keyword, _mode in _KINDS:
        files = [n for n in names if prefix in n and keyword in n and n.endswith(".json")]
        for name in files:
            _index_file(by_date, kind, name, reader(name))
    # Families that are only kept (v1.7.6.7): read for the hook's sake, the content is dropped.
    for name in names:
        if name.endswith(".json") and _kind_of_name(name) is None and _saved_family(name) is not None:
            reader(name)
    return by_date


def _days_from_entries(by_date: dict, with_entries: bool = False) -> Iterator:
    """
    Yields one day at a time — sorted chronologically — built from the entries of by_date.
    with_entries: yield (raw dict, entries of the day) instead of the raw dict alone
    """
    for date_str in sorted(by_date.keys()):
        day = parse_day(by_date[date_str], date_str)
        yield (day, by_date[date_str]) if with_entries else day


def _process_entries(names: list, reader, with_entries: bool = False, inventory=None) -> Iterator:
    """
    Scans file list, reads relevant files, indexes by date, yields per day.
    reader: callable(name) → parsed JSON object or None
    with_entries: yield (raw dict, entries of the day) instead of the raw dict alone
    inventory: dict | None — filled with build_inventory(names) before anything is read (v1.7.6.7)
    """
    if inventory is not None:
        inventory.update(build_inventory(names))
    by_date = _collect_entries(names, reader)
    log.info(f"  load_bulk: {len(by_date)} days found in export")
    yield from _days_from_entries(by_date, with_entries)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — file readers
# ══════════════════════════════════════════════════════════════════════════════

def _count(inventory, key: str) -> None:
    """Counts a read problem in the inventory ("unreadable" / "too_large"), if there is one."""
    if inventory is not None:
        inventory[key] = inventory.get(key, 0) + 1


def _too_large(size, inventory) -> bool:
    """True (counted, warned without a file name) if a file of this size is over MAX_JSON_BYTES (v1.7.6.7)."""
    if isinstance(size, int) and size > MAX_JSON_BYTES:
        _count(inventory, "too_large")
        log.warning(f"  load_bulk: a JSON file of {size / 1e6:.0f} MB is over the limit of "
                    f"{MAX_JSON_BYTES // (1024 * 1024)} MB, skipped")
        return True
    return False


def _read_zip_json(zf: zipfile.ZipFile, name: str, hook=None, inventory=None):
    """Reads and parses a JSON file from an open ZipFile. hook(name, bytes) gets the bytes first (v1.7.6.1)."""
    try:
        if _too_large(zf.getinfo(name).file_size, inventory):
            return None
    except KeyError:
        pass                                    # the read below reports it
    if hook is not None:
        try:
            with zf.open(name) as f:
                data = f.read()
        except Exception as e:
            log.warning(f"  load_bulk: could not read {name}: {e}")
            _count(inventory, "unreadable")
            return None
        hook(name, data)
        try:
            return json.loads(data)
        except Exception as e:
            log.warning(f"  load_bulk: could not read {name}: {e}")
            _count(inventory, "unreadable")
            return None
    try:
        with zf.open(name) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"  load_bulk: could not read {name}: {e}")
        _count(inventory, "unreadable")
        return None


def _read_dir_json(base: Path, name: str, hook=None, inventory=None):
    """Reads and parses a JSON file from a directory. hook(name, bytes) gets the bytes first (v1.7.6.1)."""
    try:
        if _too_large((base / name).stat().st_size, inventory):
            return None
    except OSError:
        pass                                    # the read below reports it
    if hook is not None:
        try:
            data = (base / name).read_bytes()
        except Exception as e:
            log.warning(f"  load_bulk: could not read {name}: {e}")
            _count(inventory, "unreadable")
            return None
        hook(name, data)
        try:
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            log.warning(f"  load_bulk: could not read {name}: {e}")
            _count(inventory, "unreadable")
            return None
    try:
        with open(base / name, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"  load_bulk: could not read {name}: {e}")
        _count(inventory, "unreadable")
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
