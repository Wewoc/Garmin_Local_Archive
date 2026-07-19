#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
frozen_paths.py

Leaf-Node. Zentrale Frozen-Path-Auflösung — ersetzt die bislang mehrfach
duplizierten sys.frozen / sys._MEIPASS / sys.executable Zweige in
panel_outputs.py (6x), panel_home.py, garmin_live_fetch-Aufrufstelle und
den Doku-Lookups.

Kein Projekt-Import, keine I/O außer Path.exists()-Prüfungen. Darf von
app/panel_*.py, den Entry Points und scheduler/daily_update.py importiert
werden — genau wie crash_handler.py und qwebengine_hardening.py, die im
selben src/-Root liegen (v1.6.0.4.3 / v1.6.0.4.4).

Drei Funktionen, bewusst getrennt statt einer Funktion mit Nebeneffekten:

  scripts_root() — seiteneffektfrei. Liefert die Wurzel, unter der
      garmin/, maps/, dashboards/, layouts/, context/ liegen.
      Kanonischer T2/T3-Distinguisher (MAINTENANCE_GLOBAL.md):
      prüft dash_runner.py unter scripts/dashboards/, nicht nur die
      Existenz von scripts/ selbst (schließt P1-02 / Doc-Drift).

  add_to_path(root, *subs) — mutiert sys.path bewusst als eigener,
      expliziter Schritt. Ohne subs wird root selbst eingefügt.
      Reihenfolge und Duplikat-Check identisch zum bisherigen Code an
      allen sieben Aufrufstellen.

  doc_path(filename) — sucht mitgelieferte Doku (README_APP.md,
      QUICKSTART.txt, USER_GUIDE.txt, daily_update_task.xml).
      Frozen: info/ neben der EXE (T2 + T3, identisch befüllt).
      Dev: dieselbe dreistufige Kette wie build.py::prepare_scripts_dir()
      — Repo-Root -> src/docs/ -> src/scheduler/. Eine Wahrheitsquelle
      für "wo liegt Doku", identisch in Build und Laufzeit.
      Gibt None zurück wenn nichts gefunden wird — kein Raten, kein
      Erzeugen eines Pfads der nicht existiert.
"""

import sys
from pathlib import Path


def scripts_root() -> Path:
    """
    Wurzel für garmin/, maps/, dashboards/, layouts/, context/.

    Dev:    Ordner dieser Datei (src/) — frozen_paths.py liegt im src/-Root,
            identisch zu crash_handler.py und qwebengine_hardening.py.
    T3:     sys._MEIPASS/scripts, verifiziert über den kanonischen
            Distinguisher (dash_runner.py muss dort tatsächlich existieren).
    T2:     sys.executable.parent/scripts (Fallback, wenn der T3-Check
            nicht zutrifft).
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).parent

    if (hasattr(sys, "_MEIPASS") and
            (Path(sys._MEIPASS) / "scripts" / "dashboards" /
             "dash_runner.py").exists()):
        return Path(sys._MEIPASS) / "scripts"

    return Path(sys.executable).parent / "scripts"


def add_to_path(root: Path, *subs: str) -> None:
    """
    Fügt root/sub für jedes sub in sys.path ein (ohne Duplikate).
    Ohne subs wird root selbst eingefügt.

    Getrennt von scripts_root() — eine Funktion, die eine "Root" liefert
    und dabei sys.path mutiert, wäre eine versteckte Nebenwirkung genau
    der Art, die diese Zentralisierung vermeiden soll.
    """
    candidates = [root / sub for sub in subs] if subs else [root]
    for p in candidates:
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)


def doc_path(filename: str) -> Path | None:
    """
    Findet eine mitgelieferte Doku-Datei. None wenn nicht gefunden.

    Frozen (T2 + T3): info/ neben der EXE — beide Targets befüllen
    info/ identisch aus INFO_INCLUDE_T2 / INFO_INCLUDE_T3.

    Dev: dieselbe Suchkette wie build.py::prepare_scripts_dir() beim
    Befüllen von info/ — Repo-Root, dann src/docs/, dann src/scheduler/.
    """
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "info" / filename
        return candidate if candidate.exists() else None

    src_root  = Path(__file__).parent
    repo_root = src_root.parent
    candidates = [
        repo_root / filename,
        src_root / "docs" / filename,
        src_root / "scheduler" / filename,
    ]
    return next((p for p in candidates if p.exists()), None)
