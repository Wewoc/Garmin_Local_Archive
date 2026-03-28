#!/usr/bin/env python3
"""
garmin_import.py

Importer — lädt und parst Garmin Bulk-Export Daten in das Raw-Format.

PLATZHALTER — nicht implementiert in v1.2.0.
Struktur und Schnittstellen sind definiert, Implementierung folgt später.

---

## Absichtserklärung

Garmin erlaubt den Export aller persönlichen Daten als ZIP-Archiv
(Einstellungen → Datenverwaltung → Daten exportieren).
Dieses Modul soll dieses Archiv einlesen und tageweise in dasselbe
Raw-Format übersetzen das garmin_api.fetch_raw() liefert.

Damit kann ein Nutzer seine komplette Garmin-Historie importieren —
auch für Zeiträume die über die API nicht mehr erreichbar sind
(Garmin archiviert Intraday-Daten nach ca. 1–2 Jahren).

Das normalisierte dict fließt danach durch denselben Pipeline-Pfad
wie API-Daten: garmin_normalizer → garmin_quality → garmin_collector.

---

## Geplante Schnittstelle

    load_bulk(path) → Iterator[dict]
        Öffnet ZIP oder Ordner, liefert pro Tag ein raw dict.
        path: str | Path — Pfad zum Garmin Export ZIP oder entpacktem Ordner

    parse_day(data, date_str) → dict
        Extrahiert einen einzelnen Tag aus den Bulk-Daten.
        data:     dict — rohe Bulk-Daten für diesen Tag
        date_str: str  — Datum im Format YYYY-MM-DD

---

## Geplante source-Flags (ab v1.2.2)

    "source": "bulk"   — Garmin ZIP Export
    "source": "csv"    — manueller CSV Import
    "source": "manual" — manuell bereitgestelltes JSON

Nur Daten mit source="api" erhalten recheck=True im quality_log.
Bulk/CSV/Manual haben keine Live-Quelle zum Nachladen.

---

## Abhängigkeiten (geplant)

    garmin_normalizer  — Empfänger des normalisierten dict
    garmin_config      — Pfade und Konstanten (GARMIN_IMPORT_PATH, noch nicht aktiv)

Kein Zugriff auf quality_log.json, keine API-Calls.
"""

import logging

log = logging.getLogger(__name__)


def load_bulk(path) -> list:
    """
    Platzhalter — nicht implementiert.
    Soll ZIP oder Ordner einlesen und pro Tag ein raw dict liefern.
    """
    log.warning("garmin_import.load_bulk() ist noch nicht implementiert.")
    return []


def parse_day(data: dict, date_str: str) -> dict:
    """
    Platzhalter — nicht implementiert.
    Soll einen einzelnen Tag aus Bulk-Daten extrahieren.
    """
    log.warning("garmin_import.parse_day() ist noch nicht implementiert.")
    return {"date": date_str}
