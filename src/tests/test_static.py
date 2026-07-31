#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    "dashboards", "layouts", "layouts/render", "export",
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
    "garmin/garmin_writer.py":        2,
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
_LEAF_NODES = ["garmin/garmin_utils.py", "garmin/garmin_validator.py"]

# garmin_validator.py's own docstring documents this exception explicitly:
# "No imports from other project modules except garmin_config (leaf-node
# constraint)." — needed to load DATAFORMAT_FILE at module import.
# garmin_utils.py does not import garmin_config at all — listing it here
# does not weaken the check for that file.
_LEAF_NODE_ALLOWED_EXCEPTIONS = {"garmin_config"}

def _project_imports(path: Path) -> list[str]:
    """Returns import module names (top-level names only) that match a
    known project module — i.e. violations of the leaf-node invariant.
    Excludes documented exceptions (see _LEAF_NODE_ALLOWED_EXCEPTIONS)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _PROJECT_MODULE_NAMES and top not in _LEAF_NODE_ALLOWED_EXCEPTIONS:
                    found.append(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _PROJECT_MODULE_NAMES and top not in _LEAF_NODE_ALLOWED_EXCEPTIONS:
                    found.append(top)
    return found

for _leaf in _LEAF_NODES:
    _violations = _project_imports(_ROOT / _leaf)
    check(f"{_leaf}: keine Projekt-Modul-Importe (Leaf-Node)", not _violations)
    if _violations:
        print(f"  Gefundene Projekt-Importe in {_leaf}:")
        for v in _violations:
            print(f"    - {v}")

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

# Baseline aus DEPS-Scan v1657_40 (2026-07-30): 10 Fundstellen in
# Produktivcode (panel_outputs.py 7x, dash_runner.py 2x,
# dash_plotter_html_complex.py 1x). Alle zehn laden über einen zur Laufzeit
# berechneten Pfad — kein String-Literal, daher hier kein Ziel-gegen-Manifest-
# Abgleich möglich (das leistet Sektion 3b bereits für die betroffenen
# Ordner: dashboards/, layouts/). Ein Anstieg dieser Zahl ist kein Fehler an
# sich, nur ein Hinweis: eine neue dynamische Lade-Stelle ist aufgetaucht —
# prüfen, ob ihr Zielordner in _FULLY_COVERED_DIRS (Sektion 3b) steht.
_SPEC_FROM_FILE_LOCATION_BASELINE = 10

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
#  7. (reserved) mypy — type checking
# ══════════════════════════════════════════════════════════════════════════════
# section("7. mypy — type checking")
# Uncomment and implement when mypy is added to the toolchain.

# ── Summary ────────────────────────────────────────────────────────────────────
summary()
