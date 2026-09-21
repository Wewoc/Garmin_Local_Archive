#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
updater.py

Leaf-Node. Client-seitige Logik für den Self-Updater (v1.7.2.4 T3-only,
v1.7.2.4-Nacherweiterung auch T2) — GitHub-Release-Asset-Auflösung,
Download, SHA256-Verifikation, Entpacken. War von Anfang an generisch
(Asset-Name/URLs sind Parameter, keine T3-Annahme im Code selbst) — die
Nacherweiterung ergänzt nur die T2-Namenskonstanten, ändert an dieser
Datei sonst nichts. Der eigentliche Datei-Swap (laufende Prozesse
schließen, Ordner ersetzen, neu starten) folgt in einem späteren
Bauauftrag-Schritt als separates PowerShell-Helferskript — alles hier
läuft noch im aufrufenden Python-Prozess selbst, bevor irgendetwas
Bestehendes gesperrt/berührt wird.

Kein Projekt-Import, keine GUI-Abhängigkeit, nur Stdlib — importierbar
von garmin_app_base.py (GUI-Button) UND scheduler/daily_update.py
(unbeaufsichtigter Auto-Apply-Pfad), analog zu version.py/frozen_paths.py.

resolve_release_asset(release_json, asset_name) — sucht ein Asset mit
    exakt diesem Namen in release_json["assets"] (GitHub-"latest
    release"-API-Response), liefert dessen browser_download_url oder
    None, wenn kein solches Asset existiert (z. B. weil ein Release vor
    v1.7.2.4 noch keine Checksum-Datei mitbringt).

prepare_update(exe_dir, zip_url, checksum_url) — lädt das Release-ZIP,
    verifiziert es gegen seine SHA256-Checksum-Datei, entpackt es nach
    exe_dir/_update_pending/. Fehlt checksum_url (kein Checksum-Asset im
    Release — z. B. jeder Release vor v1.7.2.4), wird die Anwendung
    verweigert statt unverifiziert zu entpacken (fail closed, nicht
    fail open — eine "optionale" Verifikation wäre keine echte
    Absicherung mehr). Räumt einen verwaisten Rest eines abgebrochenen
    vorherigen Versuchs vor dem Start auf. Bei jedem Fehler (Netz,
    Checksum-Mismatch, defektes ZIP) wird _update_pending/ wieder
    entfernt — die laufende Installation bleibt in jedem Fall
    unberührt, ein Fehler hier kann sie nie beschädigen.
"""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

# Asset-Namen exakt wie von compiler/build_standalone.py::build_combined_zip()
# erzeugt bzw. (Bauauftrag-Schritt 12) künftig zusätzlich hochgeladen.
T3_ZIP_ASSET_NAME           = "Garmin_Local_Archive_Standalone.zip"
T3_ZIP_CHECKSUM_ASSET_NAME  = T3_ZIP_ASSET_NAME + ".sha256"

# T2-Pendant (v1.7.2.4-Nacherweiterung, Baustein 27) — exakt wie von
# compiler/build.py::build_zip() erzeugt (APP_NAME = "Garmin_Local_Archive").
T2_ZIP_ASSET_NAME           = "Garmin_Local_Archive.zip"
T2_ZIP_CHECKSUM_ASSET_NAME  = T2_ZIP_ASSET_NAME + ".sha256"

UPDATE_PENDING_DIRNAME = "_update_pending"


def resolve_release_asset(release_json: dict, asset_name: str) -> str | None:
    """
    Liefert die browser_download_url des Assets mit exaktem Namen
    `asset_name` aus einem GitHub-"latest release"-API-Response.

    None, wenn kein Asset diesen Namen trägt — kein Raten, kein
    Teilstring-Match (ein Release enthält sowohl das T2- als auch das
    T3-ZIP nebeneinander, ein ungenauer Match würde das falsche greifen).
    """
    for asset in release_json.get("assets", []):
        if asset.get("name") == asset_name:
            return asset.get("browser_download_url")
    return None


def _download(url: str, dest: Path) -> None:
    """Streamt eine URL nach `dest`. Lässt jeden Fehler (Netz, HTTP-
    Status) unverändert nach oben durch — der Aufrufer entscheidet über
    Logging/Meldung, diese Funktion selbst bleibt dazu stumm."""
    req = urllib.request.Request(url, headers={"User-Agent": "GarminLocalArchive"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _sha256_of(path: Path) -> str:
    """Hex-Digest des Dateiinhalts, in Blöcken gelesen (sicher auch für
    ein mehrere hundert MB großes ZIP)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_update(exe_dir: Path, zip_url: str, checksum_url: str | None) -> Path:
    """
    Lädt das T3-Release-ZIP, verifiziert es gegen seine SHA256-Checksum-
    Datei und entpackt es nach `exe_dir/_update_pending/`. Liefert bei
    Erfolg den Pfad zu diesem Ordner.

    Wirft RuntimeError mit einer für Timo/das Konsolen-Log lesbaren
    Meldung bei jedem Fehler (Netz, fehlende/nicht passende Checksum,
    defektes ZIP) — nichts außerhalb von _update_pending/ wird von
    dieser Funktion je berührt, ein Fehler hier kann die laufende
    Installation also nie beschädigen.
    """
    pending_dir = exe_dir / UPDATE_PENDING_DIRNAME
    if pending_dir.exists():
        shutil.rmtree(pending_dir)   # verwaister Rest eines abgebrochenen Versuchs
    pending_dir.mkdir()

    if not checksum_url:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise RuntimeError(
            "This release does not publish a checksum file — refusing "
            "to auto-apply an unverified update.")

    zip_path = pending_dir / "update.zip"
    try:
        _download(zip_url, zip_path)
        expected = urllib.request.urlopen(checksum_url, timeout=10).read() \
                                  .decode().split()[0].lower()
    except OSError as exc:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise RuntimeError(f"Download failed: {exc}") from exc

    actual = _sha256_of(zip_path).lower()
    if actual != expected:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise RuntimeError(
            f"Checksum mismatch — expected {expected}, got {actual}. "
            "Download discarded, nothing applied.")

    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(pending_dir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(pending_dir, ignore_errors=True)
        raise RuntimeError(f"Downloaded file is not a valid ZIP: {exc}") from exc

    zip_path.unlink()
    return pending_dir
