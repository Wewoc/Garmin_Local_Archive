#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_static.py — Garmin Local Archive — Static Analysis Suite

Run from the project folder:
    python tests/test_static.py

Covers static code analysis tools — independent of runtime behaviour.
Complements the functional test suites (test_local, test_dashboard, etc.).

Tools covered:
  1. ruff   — linting + style (0 errors required)
  2. bandit — security linting (HIGH severity, 0 errors required)

Prepared for extension:
  3. (reserved) mypy — type checking

No network, no GUI, no API calls.
"""

import ast
import subprocess
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from support import check, section, summary  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
#  1. ruff — linting + style
# ══════════════════════════════════════════════════════════════════════════════
section("1. ruff — linting + style")

# Check ruff is available
_ruff_available = False
try:
    result = subprocess.run(
        ["ruff", "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _ruff_available = result.returncode == 0
    _ruff_version   = result.stdout.strip() if _ruff_available else "not found"
except FileNotFoundError:
    _ruff_version = "not found"

check(f"ruff is installed ({_ruff_version})", _ruff_available)

if _ruff_available:
    result = subprocess.run(
        ["ruff", "check", "."],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _ruff_clean = result.returncode == 0

    if not _ruff_clean:
        # Print ruff output so failures are visible
        print()
        for line in result.stdout.splitlines():
            print(f"    {line}")
        print()

    check("ruff check . → 0 errors", _ruff_clean)
else:
    print("  –  ruff check skipped (ruff not installed)")

# ══════════════════════════════════════════════════════════════════════════════
#  2. bandit — security linting (HIGH severity only)
# ══════════════════════════════════════════════════════════════════════════════
section("2. bandit — security linting")

_bandit_available = False
try:
    result = subprocess.run(
        ["bandit", "--version"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _bandit_available = result.returncode == 0
    _bandit_version   = result.stdout.splitlines()[0].strip() if _bandit_available else "not found"
except FileNotFoundError:
    _bandit_version = "not found"

check(f"bandit is installed ({_bandit_version})", _bandit_available)

if _bandit_available:
    result = subprocess.run(
        [
            "bandit", "-r", ".",
            "--severity-level", "high",
            "--confidence-level", "high",
            "--exclude", ".venv,dist,build",
            "-q",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_ROOT)
    )
    _bandit_clean = result.returncode == 0

    if not _bandit_clean:
        print()
        for line in result.stdout.splitlines():
            print(f"    {line}")
        print()

    check("bandit HIGH severity → 0 issues", _bandit_clean)
else:
    print("  –  bandit check skipped (bandit not installed)")

# ══════════════════════════════════════════════════════════════════════════════
#  3. build_manifest — SHARED_SCRIPTS Vollständigkeit (bidirektional)
# ══════════════════════════════════════════════════════════════════════════════
section("3. build_manifest — SHARED_SCRIPTS Vollständigkeit")

sys.path.insert(0, str(_ROOT / "compiler"))
import build_manifest  # noqa: E402

# Bewusst nicht im Build — offline/manuelle Werkzeuge, kein Laufzeitpfad.
# Siehe NOTES_v1657_fortsetzung.md, Netz 0 (Session v1.6.5.7).
_EXCLUDED_FROM_BUILD = {
    "export/backfill_source_backup.py",
    "export/backfill_source_intraday.py",
    "export/regenerate_summaries.py",
    "garmin_app_screenshot.py",
}

# ── 3a. Jeder gelistete Pfad existiert ─────────────────────────────────────────
_missing = [p for p in build_manifest.SHARED_SCRIPTS if not (_ROOT / p).is_file()]
check("SHARED_SCRIPTS: alle gelisteten Dateien existieren", not _missing)
if _missing:
    print("  Fehlende Dateien:")
    for p in _missing:
        print(f"    - {p}")

# ── 3b. Jede .py-Datei in den vollständig erfassten Ordnern ist gelistet ──────
_FULLY_COVERED_DIRS = [
    "app", "garmin", "garmin/quality", "context", "maps",
    "dashboards", "layouts", "layouts/render",
    "exports", "exports/export_adapters",
]
_listed   = set(build_manifest.SHARED_SCRIPTS)
_unlisted = []
for _d in _FULLY_COVERED_DIRS:
    for _f in sorted((_ROOT / _d).glob("*.py")):
        _rel = f"{_d}/{_f.name}"
        if _rel not in _listed and _rel not in _EXCLUDED_FROM_BUILD:
            _unlisted.append(_rel)

check("SHARED_SCRIPTS: keine .py-Datei in den erfassten Ordnern fehlt", not _unlisted)
if _unlisted:
    print("  Nicht gelistete Dateien:")
    for p in _unlisted:
        print(f"    - {p}")

# ── 3c. Root-Verzeichnis — .py-Dateien außer den drei Entry-Points ────────────
_ROOT_ENTRY_POINTS = {"garmin_app.py", "garmin_app_standalone.py", "daily_update.py"}
_root_unlisted = []
for _f in sorted(_ROOT.glob("*.py")):
    if _f.name in _ROOT_ENTRY_POINTS:
        continue
    if _f.name not in _listed and _f.name not in _EXCLUDED_FROM_BUILD:
        _root_unlisted.append(_f.name)

check("SHARED_SCRIPTS: Root — keine .py-Datei (außer Entry-Points) fehlt", not _root_unlisted)
if _root_unlisted:
    print("  Nicht gelistete Root-Dateien:")
    for p in _root_unlisted:
        print(f"    - {p}")

# ══════════════════════════════════════════════════════════════════════════════
#  4. Regression-Wächter — stille except-Handler in den Netz-3-Kandidatenmodulen
# ══════════════════════════════════════════════════════════════════════════════
section("4. Regression-Wächter — stille except-Handler")

def _count_silent_handlers(path: Path) -> int:
    """
    AST-basiert (kein Regex — mehrzeilige except-Blöcke sind sonst unsichtbar,
    siehe Falle F-1 im DEPS-Scan-Pattern-Katalog). Zählt ExceptHandler-Knoten,
    deren Body ausschließlich aus einem einzelnen `pass`-Statement besteht —
    unabhängig vom Exception-Typ (bare except, except Exception, except OSError, ...).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                count += 1
    return count

# Netz-3-Kandidatenmodule (v1.6.5.7) — nach dem Aufräumen dort ist ein Anstieg
# der stillen Handler-Anzahl ein Regressionssignal, keine exakte Null erwartet
# (einige stille Handler sind bewusst best-effort, siehe NOTES_v1657_fortsetzung.md).
# Baseline noch nicht gesetzt (None) — dieser Lauf ist rein informativ, die
# tatsächlichen Werte werden in einem Folge-Anchor eingetragen.
_SILENT_HANDLER_BASELINE = {
    "garmin/garmin_import_mirror.py": 5,
    "garmin/garmin_backup.py":        0,
    "garmin/garmin_security.py":      0,
    "garmin/garmin_writer.py":        2,  # v1.7.8.2 (Block 8 (a), Schritt 7): 3 -> 2. Verbleibend:
                                          # ImportError beim Backup-Auslöser und das
                                          # best-effort .tmp-Aufräumen in write_day();
                                          # _write_summary_file() schreibt über atomic_io
                                          # (das räumt selbst auf), dort entfiel der Handler
}

for _rel, _baseline in _SILENT_HANDLER_BASELINE.items():
    _count = _count_silent_handlers(_ROOT / _rel)
    if _baseline is None:
        check(f"{_rel}: stille except-Handler = {_count} (Baseline noch nicht gesetzt)", True)
    else:
        check(f"{_rel}: stille except-Handler ({_count}) <= Baseline ({_baseline})",
              _count <= _baseline)

# ══════════════════════════════════════════════════════════════════════════════
#  5. Verbotene Importmuster
# ══════════════════════════════════════════════════════════════════════════════
section("5. Verbotene Importmuster")

# ── 5a. Leaf-Node-Invariante — garmin_utils.py / garmin_validator.py ──────────
# Diese beiden Module dürfen keine anderen Projekt-Module importieren (nur
# stdlib/Drittanbieter). Prüfung generisch gegen build_manifest.SHARED_SCRIPTS —
# kein hartcodiertes Stdlib-Allowlist nötig.
_PROJECT_MODULE_NAMES = {
    Path(p).stem for p in build_manifest.SHARED_SCRIPTS
    if Path(p).stem != "__init__"
}
_LEAF_NODES = ["garmin/garmin_utils.py", "garmin/garmin_validator.py", "log_utils.py",
               "date_utils.py", "garmin/atomic_io.py", "garmin/garmin_bulk_fit_reader.py", "garmin/garmin_bulk_export_scanner.py",
               "garmin/garmin_bulk_normalizer.py",
               # v1.7.8.2 (Block 8 (a), Schritt 11): Leaf laut Regelwerk, importieren nur den Schreibhelfer atomic_io
               # (siehe _LEAF_NODE_FILE_EXCEPTIONS)
               "garmin/garmin_export_scan.py", "garmin/garmin_api_capability.py", "clients/chat_session_store.py"]

# garmin_validator.py's own docstring documents this exception explicitly:
# "No imports from other project modules except garmin_config (leaf-node
# constraint)." — needed to load DATAFORMAT_FILE at module import.
# garmin_utils.py does not import garmin_config at all — listing it here
# does not weaken the check for that file.
_LEAF_NODE_ALLOWED_EXCEPTIONS = {"garmin_config"}

# v1.7.8.2 (Block 8 (a)): atomic_io ist der eine gemeinsame Schreibhelfer und selbst ein Leaf (nur Standardbibliothek,
# siehe oben). Diese drei Leaf-Module importieren ihn, um nicht eine eigene Kopie von "Temp-Datei + os.replace" zu
# tragen (Beschluss des Maintainers, 2026-11-26). Die Ausnahme gilt bewusst NUR für diese Dateien, nicht global:
# garmin_utils.py, garmin_validator.py und die übrigen Leaf-Module dürfen ihn weiter nicht importieren.
_LEAF_NODE_FILE_EXCEPTIONS = {
    "garmin/garmin_export_scan.py": {"atomic_io"},
    "garmin/garmin_api_capability.py": {"atomic_io"},
    "clients/chat_session_store.py": {"atomic_io"},
}

def _project_imports(path: Path, extra_allowed=frozenset()) -> list[str]:
    """Returns import module names (top-level names only) that match a
    known project module — i.e. violations of the leaf-node invariant.
    Excludes documented exceptions (see _LEAF_NODE_ALLOWED_EXCEPTIONS and,
    per file, extra_allowed = _LEAF_NODE_FILE_EXCEPTIONS[file])."""
    allowed = _LEAF_NODE_ALLOWED_EXCEPTIONS | set(extra_allowed)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _PROJECT_MODULE_NAMES and top not in allowed:
                    found.append(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _PROJECT_MODULE_NAMES and top not in allowed:
                    found.append(top)
    return found

for _leaf in _LEAF_NODES:
    _violations = _project_imports(_ROOT / _leaf, _LEAF_NODE_FILE_EXCEPTIONS.get(_leaf, ()))
    check(f"{_leaf}: keine Projekt-Modul-Importe (Leaf-Node)", not _violations)
    if _violations:
        print(f"  Gefundene Projekt-Importe in {_leaf}:")
        for v in _violations:
            print(f"    - {v}")

# Die Ausnahme für atomic_io ist nötig und gilt nur für die drei Dateien (Schritt 11):
check("atomic_io-Ausnahme: ohne sie würde garmin_export_scan.py den Import melden",
      _project_imports(_ROOT / "garmin/garmin_export_scan.py") == ["atomic_io"])
check("atomic_io-Ausnahme: die Ausnahmeliste nennt genau diese drei Dateien, und alle stehen in _LEAF_NODES",
      set(_LEAF_NODE_FILE_EXCEPTIONS) == {"garmin/garmin_export_scan.py", "garmin/garmin_api_capability.py", "clients/chat_session_store.py"}
      and set(_LEAF_NODE_FILE_EXCEPTIONS) <= set(_LEAF_NODES))
check("atomic_io-Ausnahme: für eine andere Leaf-Datei (garmin_utils.py) gilt sie nicht (ein atomic_io-Import würde dort gemeldet)",
      "garmin/garmin_utils.py" not in _LEAF_NODE_FILE_EXCEPTIONS and "atomic_io" not in _LEAF_NODE_ALLOWED_EXCEPTIONS)

# ── 5b. garmin_security.py — garmin_config muss lazy importiert werden ────────
_security_path = _ROOT / "garmin/garmin_security.py"
_sec_tree = ast.parse(_security_path.read_text(encoding="utf-8"))
_module_level_cfg_import = any(
    (isinstance(node, ast.Import) and any(a.name == "garmin_config" for a in node.names))
    or (isinstance(node, ast.ImportFrom) and node.module == "garmin_config")
    for node in _sec_tree.body  # nur Modulebene, nicht in Funktionskörper hinein
)
check("garmin_security.py: garmin_config nicht auf Modulebene importiert",
      not _module_level_cfg_import)

# ══════════════════════════════════════════════════════════════════════════════
#  6. Regression-Wächter — spec_from_file_location-Fundstellen
# ══════════════════════════════════════════════════════════════════════════════
section("6. Regression-Wächter — spec_from_file_location")

def _count_spec_from_file_location(path: Path) -> int:
    """
    AST-basiert. Zählt Call-Knoten, deren Funktionsname (Attribut oder
    direkter Name) 'spec_from_file_location' ist — unabhängig vom
    Import-Alias (importlib.util.spec_from_file_location,
    _ilu.spec_from_file_location, ...).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None
            )
            if name == "spec_from_file_location":
                count += 1
    return count

# Baseline aus DEPS-Scan v1657_40 (2026-07-30): ursprünglich 10 Fundstellen.
# Angehoben auf 11 (v1.7.4 Export Layer, 2026-10-01): zwei neue, legitime
# Lade-Stellen dazugekommen — app/popups/export_data.py lädt
# exports/export_runner.py, exports/export_runner.py selbst lädt die
# *_adapter.py-Dateien, exakt dasselbe Muster wie dashboard_create.py/
# dash_runner.py für die Dashboard-Layer. Zielordner (exports/,
# exports/export_adapters/) wurde entsprechend in _FULLY_COVERED_DIRS
# (Sektion 3b) ergänzt — dort stand vorher fälschlich "export" (Singular,
# nicht existentes Verzeichnis), jetzt korrigiert. Alle Fundstellen laden
# über einen zur Laufzeit berechneten Pfad — kein String-Literal, daher
# hier kein Ziel-gegen-Manifest-Abgleich möglich (das leistet Sektion 3b
# bereits für die betroffenen Ordner). Ein weiterer Anstieg dieser Zahl ist
# kein Fehler an sich, nur ein Hinweis: eine neue dynamische Lade-Stelle ist
# aufgetaucht — prüfen, ob ihr Zielordner in _FULLY_COVERED_DIRS steht.
#
# Angehoben auf 12 (v1.7.4 Export Layer, Baustein 17, 2026-10-01): GUI
# "Daily Sync"-Button rief export_auto_run nie auf (nur der headless
# daily_update.py-Pfad) — neue app/outputs/export_auto.py lädt
# exports/export_runner.py exakt wie app/popups/export_data.py, selber
# bereits abgedeckter Zielordner (exports/), kein neuer Eintrag in
# _FULLY_COVERED_DIRS nötig.
_SPEC_FROM_FILE_LOCATION_BASELINE = 12

_spec_total = sum(
    _count_spec_from_file_location(_ROOT / p)
    for p in build_manifest.SHARED_SCRIPTS
    if (_ROOT / p).suffix == ".py"
)
check(
    f"spec_from_file_location: {_spec_total} Fundstelle(n) in SHARED_SCRIPTS "
    f"<= Baseline ({_SPEC_FROM_FILE_LOCATION_BASELINE})",
    _spec_total <= _SPEC_FROM_FILE_LOCATION_BASELINE,
)
if _spec_total > _SPEC_FROM_FILE_LOCATION_BASELINE:
    print("  Neue Fundstelle(n) — prüfen, ob Zielordner in "
          "_FULLY_COVERED_DIRS (Sektion 3b) enthalten ist.")

# ══════════════════════════════════════════════════════════════════════════════
#  7. Regression-Wächter — atomares Schreiben nur über atomic_io (Block 8 (a), Schritt 9)
# ══════════════════════════════════════════════════════════════════════════════
section("7. Regression-Wächter — atomares Schreiben nur über atomic_io")

# Seit v1.7.8.2 gibt es genau einen atomaren Schreibhelfer (garmin/atomic_io.py: Temp-Datei, fsync, os.replace mit
# Wiederholung bei gesperrter Datei). Dieser Wächter meldet jede neue eigene Kopie des Musters im Produktivcode:
# os.replace / os.rename / os.fsync (auch über einen Alias oder "from os import ..."), das Tauschen einer Datei mit
# einem einstelligen .replace(x) / .rename(x) (Path) und einen eigenen "except PermissionError" (Wiederholung bei
# Sperre). Nicht gemeldet werden shutil.move (verschiebt Ordner), einfache Schreibzugriffe ohne Tausch (write_text,
# write_bytes auf die Zieldatei selbst) und Treffer in tests/, docs/, support-tools/ und compiler/.
#
# Grenze: eine Kopie, die ihre Aufrufe versteckt (eigene Hüllfunktion um os.replace in einem anderen Modul,
# getattr, subprocess) wird nicht erkannt. Der Wächter fängt das Muster, nicht jede mögliche Umgehung.
_ATOMIC_HELPER = "garmin/atomic_io.py"
_ATOMIC_SKIP_TOP = {"tests", "docs", "support-tools", "compiler"}

# Begründete Ausnahmen: Datei -> {Art: genaue Anzahl}. Eine Ausnahme, die nicht mehr zutrifft (Anzahl ungleich),
# lässt den Test rot werden: weniger = veralteter Eintrag, mehr = neue Kopie in derselben Datei.
_ATOMIC_EXCEPTIONS = {
    # ZIP-Dateien: die neue ZIP wird vor dem Tausch geprüft (Lesen, CRC); der Tausch ist ein einzelner os.replace ohne
    # Wiederholung und ohne fsync, die alte ZIP bleibt bis dahin. Kein Text-/JSON-Schreiben, das atomic_io leistet.
    "garmin/garmin_backup_bulk.py": {"os.replace": 1},
    "garmin/garmin_backup_common.py": {"os.replace": 1},
    "garmin/garmin_migration_snapshot.py": {"os.replace": 1},
    # fsync nach dem Schreiben des eigenen Absturzprotokolls, kein Tausch einer Datei.
    "crash_handler.py": {"os.fsync": 1},
    # Wiederholung beim LÖSCHEN einer gesperrten Datei (diary_writer._remove), kein Schreiben und kein Tausch.
    "diary/diary_writer.py": {"except PermissionError": 1},
}


def _find_atomic_copies(source: str) -> list:
    """
    AST-basiert. Liefert [(Zeile, Art)] der Stellen, die wie eine eigene Kopie des atomaren Schreibens aussehen:
    'os.replace' / 'os.rename' / 'os.fsync' (auch über 'import os as x' und 'from os import replace as y'),
    '.replace(one argument)' / '.rename(one argument)' (Datei tauschen; str.replace hat zwei Argumente,
    datetime.replace nur Schlüsselwörter) und 'except PermissionError'.
    """
    tree = ast.parse(source)
    os_names = {"os"}
    from_os = {}                                   # lokaler Name -> "os.<name>"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_names.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name in ("replace", "rename", "fsync"):
                    from_os[alias.asname or alias.name] = f"os.{alias.name}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                recv = func.value.id if isinstance(func.value, ast.Name) else None
                if recv in os_names and func.attr in ("replace", "rename", "fsync"):
                    found.append((node.lineno, f"os.{func.attr}"))
                elif func.attr in ("replace", "rename") and len(node.args) == 1 and not node.keywords:
                    found.append((node.lineno, f".{func.attr}(one argument)"))
            elif isinstance(func, ast.Name) and func.id in from_os:
                found.append((node.lineno, from_os[func.id]))
        elif isinstance(node, ast.ExceptHandler) and node.type is not None:
            types = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            if any(isinstance(t, ast.Name) and t.id == "PermissionError" for t in types):
                found.append((node.lineno, "except PermissionError"))
    return sorted(found)


def _compare_atomic(found: dict, exceptions: dict):
    """found: {Datei: {Art: Anzahl}}. Liefert (unerwartet, veraltet): Funde außerhalb der Ausnahmen bzw. Ausnahmen, deren Anzahl nicht (mehr) stimmt."""
    unexpected, stale = [], []
    for rel, kinds in sorted(found.items()):
        allowed = exceptions.get(rel, {})
        for kind, n in sorted(kinds.items()):
            if allowed.get(kind, 0) != n and kind not in allowed:
                unexpected.append(f"{rel}: {kind} x{n}")
    for rel, allowed in sorted(exceptions.items()):
        for kind, n in sorted(allowed.items()):
            if found.get(rel, {}).get(kind, 0) != n:
                stale.append(f"{rel}: {kind} erwartet x{n}, gefunden x{found.get(rel, {}).get(kind, 0)}")
    return unexpected, stale


# -- 7a. der Wächter selbst: Beispielquellen -------------------------------------------------------------------------
def _kinds(src):
    return [k for _, k in _find_atomic_copies(src)]


check("7a os.replace wird gefunden", _kinds("import os\nos.replace(a, b)\n") == ["os.replace"])
check("7a os.rename und os.fsync werden gefunden", _kinds("import os\nos.rename(a, b)\nos.fsync(1)\n") == ["os.rename", "os.fsync"])
check("7a 'import os as x' (Alias) wird gefunden", _kinds("import os as _o\n_o.fsync(f.fileno())\n") == ["os.fsync"])
check("7a 'from os import replace as r' wird gefunden", _kinds("from os import replace as r\nr(a, b)\n") == ["os.replace"])
check("7a ein Pfad-Tausch tmp.replace(dst) und p.rename(q) wird gefunden",
      _kinds("tmp.replace(dst)\np.rename(q)\n") == [".replace(one argument)", ".rename(one argument)"])
check("7a 'except PermissionError' (auch im Tupel) wird gefunden",
      _kinds("try:\n    pass\nexcept PermissionError:\n    pass\ntry:\n    pass\nexcept (OSError, PermissionError):\n    pass\n")
      == ["except PermissionError", "except PermissionError"])
check("7a str.replace, datetime.replace(tzinfo=...), shutil.move, os.remove, os.path.join, einfaches write_text und except OSError werden nicht gemeldet",
      _kinds("import os, shutil\ns.replace('a', 'b')\nd.replace(tzinfo=None)\nshutil.move(a, b)\nos.remove(x)\n"
             "os.path.join(a, b)\np.write_text('x')\ntry:\n    pass\nexcept OSError:\n    pass\n") == [])
_f1, _s1 = _compare_atomic({"a.py": {"os.replace": 1}}, {})
check("7a eine Kopie ohne Ausnahme ist unerwartet", _f1 == ["a.py: os.replace x1"] and _s1 == [])
_f2, _s2 = _compare_atomic({"a.py": {"os.replace": 1}}, {"a.py": {"os.replace": 1}})
check("7a eine begründete Ausnahme mit passender Anzahl ist weder unerwartet noch veraltet", _f2 == [] and _s2 == [])
_f3, _s3 = _compare_atomic({"a.py": {"os.replace": 2}}, {"a.py": {"os.replace": 1}})
check("7a eine zweite Kopie in einer Ausnahme-Datei lässt den Test rot werden (Anzahl 2 statt 1)", _s3 == ["a.py: os.replace erwartet x1, gefunden x2"])
_f4, _s4 = _compare_atomic({}, {"a.py": {"os.replace": 1}})
check("7a ein veralteter Ausnahme-Eintrag (nichts mehr gefunden) wird gemeldet", _s4 == ["a.py: os.replace erwartet x1, gefunden x0"])
_f5, _s5 = _compare_atomic({"a.py": {"os.replace": 1, "os.fsync": 1}}, {"a.py": {"os.replace": 1}})
check("7a eine andere Art in einer Ausnahme-Datei (os.fsync neben erlaubtem os.replace) ist unerwartet", _f5 == ["a.py: os.fsync x1"])

# -- 7b. der Produktivcode ---------------------------------------------------------------------------------------------
_atomic_found = {}
for _p in sorted(_ROOT.rglob("*.py")):
    _rel_parts = _p.relative_to(_ROOT).parts
    if (_rel_parts[0] in _ATOMIC_SKIP_TOP or any(part == "__pycache__" or part.startswith(".") for part in _rel_parts)
            or "/".join(_rel_parts) == _ATOMIC_HELPER):
        continue
    _hits = _find_atomic_copies(_p.read_text(encoding="utf-8"))
    if _hits:
        _counts = {}
        for _line, _kind in _hits:
            _counts[_kind] = _counts.get(_kind, 0) + 1
        _atomic_found["/".join(_rel_parts)] = _counts

_atomic_unexpected, _atomic_stale = _compare_atomic(_atomic_found, _ATOMIC_EXCEPTIONS)
check("7b keine eigene Kopie des atomaren Schreibens im Produktivcode außerhalb von atomic_io.py und der begründeten Ausnahmen",
      _atomic_unexpected == [])
if _atomic_unexpected:
    print("  Neue Stelle(n) — über garmin/atomic_io.py schreiben oder mit Begründung in _ATOMIC_EXCEPTIONS eintragen:")
    for _entry in _atomic_unexpected:
        print(f"    {_entry}")
check("7b jeder Eintrag von _ATOMIC_EXCEPTIONS trifft noch zu (genaue Anzahl)", _atomic_stale == [])
if _atomic_stale:
    for _entry in _atomic_stale:
        print(f"    veraltet: {_entry}")
check("7b der Helfer garmin/atomic_io.py existiert und hat die Schreibwege selbst (os.replace, os.fsync)",
      {"os.replace", "os.fsync"} <= set(_kinds((_ROOT / _ATOMIC_HELPER).read_text(encoding="utf-8"))))

# ══════════════════════════════════════════════════════════════════════════════
#  8. (reserved) mypy — type checking
# ══════════════════════════════════════════════════════════════════════════════
# section("8. mypy — type checking")
# Uncomment and implement when mypy is added to the toolchain.

# ── Summary ────────────────────────────────────────────────────────────────────
summary()
