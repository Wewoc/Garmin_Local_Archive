#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

Fünf Funktionen, bewusst getrennt statt einer Funktion mit Nebeneffekten:

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

  is_t3_standalone() — True nur für T3 (GUI-EXE aus T3.1 oder
      daily_update.exe aus T3.2, beide laut build_combined_zip() im
      selben flachen Ordner mit daily_update.exe UND mcp_server.exe als
      Siblings). T1 (Dev) und T2 (--onefile + scripts/-Sidecar) liefern
      beide False. Für v1.7.2.4 (Updater, T3 only) — steuert, ob der
      dritte "Update"-Button im Popup erscheint bzw. ob
      daily_update.py seine Auto-Apply-Logik überhaupt ausführt.

  is_t2_standard(reference_file=None) — True nur für T2 (--onefile GUI-
      EXE + scripts/-Sidecar, Python auf dem Zielsystem nötig). Zwei
      Aufrufkontexte, weil T2s Daily-Sync-Pfad NIE frozen läuft:
        - GUI-EXE (frozen): sys.executable ist die EXE selbst, exe_dir
          ist bereits der Install-Ordner. Von T3.1 unterschieden über
          is_t3_standalone()==False plus denselben scripts/dashboards/
          dash_runner.py-Kanonik-Check wie scripts_root().
        - daily_update.py (nie frozen — Starte_Daily_Sync.bat ruft den
          Python-Interpreter, sys.executable zeigt dorthin, nicht auf
          die Installation): Aufrufer übergibt sein eigenes __file__ als
          reference_file, Install-Root ist parent.parent
          (scheduler/daily_update.py -> Root/). Ohne reference_file in
          diesem Fall: False (kein Raten).
      T1 (Dev) liefert in beiden Fällen False. Für v1.7.2.4-Nach-
      erweiterung (Updater, jetzt auch T2) — Pendant zu
      is_t3_standalone(), absichtlich eine eigene Funktion statt eines
      Umbaus der bestehenden (die bleibt unverändert, ihr Verhalten ist
      bereits an mehreren Stellen fest verdrahtet).
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


def is_t3_standalone() -> bool:
    """
    True nur für T3 (die --onedir GUI-EXE aus T3.1 oder daily_update.exe
    aus T3.2) — beide liegen laut build_combined_zip()
    (compiler/build_standalone.py) im selben flachen T3-Installations-
    ordner, mit daily_update.exe UND mcp_server.exe als Siblings. T1
    (Dev) und T2 (--onefile + scripts/-Sidecar, braucht Python auf dem
    Zielsystem) liefern beide False.

    Reiner Existenz-Check, kein gespeicherter Marker — gleiches Muster
    wie bereits panel_mcp.py::_resolve_mcp_server_launch_command() für
    die T2-vs-T3.3-Unterscheidung nutzt.
    """
    if not getattr(sys, "frozen", False):
        return False
    exe_dir = Path(sys.executable).parent
    return ((exe_dir / "daily_update.exe").exists()
            and (exe_dir / "mcp_server.exe").exists())


def is_t2_standard(reference_file: str | None = None) -> bool:
    """
    True nur für T2 (--onefile GUI-EXE + scripts/-Sidecar, Python auf
    dem Zielsystem nötig).

    Frozen (GUI-EXE): exe_dir = sys.executable.parent ist bereits der
    Install-Ordner. Unterschieden von T3.1 über is_t3_standalone()==False
    plus den gleichen scripts/dashboards/dash_runner.py-Kanonik-Check wie
    scripts_root() (reine scripts/-Existenz würde nicht reichen).

    Nicht frozen (daily_update.py läuft nie frozen — Starte_Daily_Sync.bat
    ruft den Python-Interpreter direkt): reference_file muss das __file__
    des Aufrufers sein (z. B. scheduler/daily_update.py), Install-Root ist
    dann reference_file.parent.parent. Ohne reference_file: False, kein
    Raten.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        return (not is_t3_standalone()
                and (exe_dir / "scripts" / "dashboards"
                     / "dash_runner.py").exists())

    if reference_file is None:
        return False
    install_root = Path(reference_file).resolve().parent.parent
    return (install_root / "Garmin_Local_Archive.exe").exists()
