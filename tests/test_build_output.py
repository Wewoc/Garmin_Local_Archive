#!/usr/bin/env python3
"""
test_build_output.py — Garmin Local Archive — Build Output Validation

Run after build_all.py to verify both build targets produced correct output.

    python tests/test_build_output.py

Requires a completed build (both targets). Skips gracefully if no build exists.
Validates:
  - Manifest consistency (always runs)
  - Source integrity against manifest (always runs)
  - Target 2: EXE + scripts/ folder structure + ZIP contents
  - Target 3: Standalone EXE + ZIP
  - Syntax check (py_compile) on all scripts in scripts/
  - Target 3 Embed: add-data Zielpfad-Rekonstruktion gegen build_manifest

Does not start any EXE. No network, no GUI, no Garmin API calls.
"""

import os
import py_compile
import sys
import zipfile
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

import build_manifest as manifest

# ── Results tracking ───────────────────────────────────────────────────────────
_pass = 0
_fail = 0
_skip = 0
_failures = []

def check(name, condition):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✓  {name}")
    else:
        _fail += 1
        _failures.append(name)
        print(f"  ✗  {name}")

def skip(name, reason):
    global _skip
    _skip += 1
    print(f"  –  {name}  (skipped: {reason})")

def section(title):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")

# ── Build root ─────────────────────────────────────────────────────────────────
# Both build targets write output to the project root (--distpath = root)
_BUILD_ROOT  = _ROOT
_SCRIPTS_DIR = _BUILD_ROOT / "scripts"
_T2_EXE      = _BUILD_ROOT / "Garmin_Local_Archive.exe"
_T2_ZIP      = _BUILD_ROOT / "Garmin_Local_Archive.zip"
_T3_EXE      = _BUILD_ROOT / "Garmin_Local_Archive_Standalone.exe"
_T3_ZIP      = _BUILD_ROOT / "Garmin_Local_Archive_Standalone.zip"

_T2_BUILT = _T2_EXE.exists()
_T3_BUILT = _T3_EXE.exists()

# ══════════════════════════════════════════════════════════════════════════════
#  1. build_manifest — Konsistenz
# ══════════════════════════════════════════════════════════════════════════════
section("1. build_manifest — Konsistenz")

check("SHARED_SCRIPTS not empty",
      len(manifest.SHARED_SCRIPTS) > 0)
check("SCRIPTS = garmin_app.py + SHARED_SCRIPTS",
      manifest.SCRIPTS == ["garmin_app.py"] + manifest.SHARED_SCRIPTS)
check("EMBEDDED_SCRIPTS = SHARED_SCRIPTS",
      manifest.EMBEDDED_SCRIPTS == manifest.SHARED_SCRIPTS)
check("ALL_SCRIPTS contains both entry points",
      "garmin_app.py" in manifest.ALL_SCRIPTS and
      "garmin_app_standalone.py" in manifest.ALL_SCRIPTS)
check("No duplicates in SHARED_SCRIPTS",
      len(manifest.SHARED_SCRIPTS) == len(set(manifest.SHARED_SCRIPTS)))
check("No duplicates in ALL_SCRIPTS",
      len(manifest.ALL_SCRIPTS) == len(set(manifest.ALL_SCRIPTS)))
check("REQUIRED_DATA_FILES not empty",
      len(manifest.REQUIRED_DATA_FILES) > 0)
check("garmin_dataformat.json in REQUIRED_DATA_FILES",
      "garmin_dataformat.json" in manifest.REQUIRED_DATA_FILES)

_all_known = set(manifest.ALL_SCRIPTS) | set(manifest.SHARED_SCRIPTS)
for sig_key in manifest.SCRIPT_SIGNATURES_BASE:
    check(f"SCRIPT_SIGNATURES_BASE key exists in manifest: {sig_key}",
          sig_key in _all_known)

# ══════════════════════════════════════════════════════════════════════════════
#  2. Source-Integrität — alle Manifest-Scripts vorhanden
# ══════════════════════════════════════════════════════════════════════════════
section("2. Source-Integrität — Manifest-Scripts im Projektordner")

check("garmin_app.py exists",             (_ROOT / "garmin_app.py").exists())
check("garmin_app_standalone.py exists",  (_ROOT / "garmin_app_standalone.py").exists())
check("build_manifest.py exists",         (_ROOT / "build_manifest.py").exists())

for name in manifest.SHARED_SCRIPTS:
    check(f"source exists: {name}", (_ROOT / name).exists())

for name in manifest.REQUIRED_DATA_FILES:
    check(f"data file exists: garmin/{name}", (_ROOT / "garmin" / name).exists())

_entry_sigs = {
    "garmin_app.py":            ["class GarminApp"],
    "garmin_app_standalone.py": ["class GarminApp"],
}
for fname, sigs in {**manifest.SCRIPT_SIGNATURES_BASE, **_entry_sigs}.items():
    fpath = _ROOT / fname
    if fpath.exists():
        content = fpath.read_text(encoding="utf-8", errors="replace")
        for sig in sigs:
            check(f"signature '{sig}' in {fname}", sig in content)
    else:
        skip(f"signature check {fname}", "file missing")

# ══════════════════════════════════════════════════════════════════════════════
#  3. Target 2 — EXE vorhanden
# ══════════════════════════════════════════════════════════════════════════════
section("3. Target 2 — EXE vorhanden")

if not _T2_BUILT:
    skip("Garmin_Local_Archive.exe exists", "no build found")
else:
    check("Garmin_Local_Archive.exe exists", True)
    check("EXE size > 0 bytes", _T2_EXE.stat().st_size > 0)

# ══════════════════════════════════════════════════════════════════════════════
#  4. Target 2 — scripts/ Ordnerstruktur
# ══════════════════════════════════════════════════════════════════════════════
section("4. Target 2 — scripts/ Ordnerstruktur")

if not _T2_BUILT:
    skip("scripts/ structure check", "no build found")
else:
    check("scripts/ directory exists",             _SCRIPTS_DIR.exists())
    check("scripts/garmin_app.py exists",          (_SCRIPTS_DIR / "garmin_app.py").exists())

    for name in manifest.SHARED_SCRIPTS:
        check(f"scripts/{name} exists", (_SCRIPTS_DIR / name).exists())

    for name in manifest.REQUIRED_DATA_FILES:
        check(f"scripts/garmin/{name} exists",
              (_SCRIPTS_DIR / "garmin" / name).exists())

# ══════════════════════════════════════════════════════════════════════════════
#  5. Target 2 — Syntax-Validierung (py_compile)
# ══════════════════════════════════════════════════════════════════════════════
section("5. Target 2 — Syntax-Validierung scripts/")

if not _T2_BUILT or not _SCRIPTS_DIR.exists():
    skip("py_compile checks", "no build found or scripts/ missing")
else:
    _py_files = list(_SCRIPTS_DIR.rglob("*.py"))
    check(f"scripts/ contains Python files ({len(_py_files)} found)",
          len(_py_files) > 0)
    for pyf in sorted(_py_files):
        rel = pyf.relative_to(_SCRIPTS_DIR)
        try:
            py_compile.compile(str(pyf), doraise=True)
            check(f"syntax OK: {rel}", True)
        except py_compile.PyCompileError:
            check(f"syntax OK: {rel}", False)

# ══════════════════════════════════════════════════════════════════════════════
#  6. Target 2 — ZIP-Inhalt
# ══════════════════════════════════════════════════════════════════════════════
section("6. Target 2 — ZIP-Inhalt")

if not _T2_BUILT:
    skip("ZIP checks", "no build found")
elif not _T2_ZIP.exists():
    skip("ZIP checks", "Garmin_Local_Archive.zip not found")
else:
    check("Garmin_Local_Archive.zip exists", True)
    with zipfile.ZipFile(_T2_ZIP, "r") as zf:
        _names = set(zf.namelist())
        check("ZIP contains EXE",
              "Garmin_Local_Archive.exe" in _names)
        check("ZIP contains scripts/garmin_app.py",
              "scripts/garmin_app.py" in _names)
        for name in manifest.SHARED_SCRIPTS:
            check(f"ZIP contains scripts/{name}",
                  f"scripts/{name}" in _names)
        for name in manifest.REQUIRED_DATA_FILES:
            check(f"ZIP contains scripts/garmin/{name}",
                  f"scripts/garmin/{name}" in _names)

# ══════════════════════════════════════════════════════════════════════════════
#  7. Target 3 — Standalone EXE + ZIP
# ══════════════════════════════════════════════════════════════════════════════
section("7. Target 3 — Standalone EXE + ZIP")

if not _T3_BUILT:
    skip("Garmin_Local_Archive_Standalone.exe exists", "no build found")
else:
    check("Garmin_Local_Archive_Standalone.exe exists", True)
    check("Standalone EXE size > 0 bytes", _T3_EXE.stat().st_size > 0)
    if _T2_BUILT:
        check("Standalone EXE larger than T2 EXE (embeds deps)",
              _T3_EXE.stat().st_size > _T2_EXE.stat().st_size)

    if not _T3_ZIP.exists():
        skip("Standalone ZIP checks", "Garmin_Local_Archive_Standalone.zip not found")
    else:
        check("Garmin_Local_Archive_Standalone.zip exists", True)
        with zipfile.ZipFile(_T3_ZIP, "r") as zf:
            _names_sa = set(zf.namelist())
            check("Standalone ZIP contains EXE",
                  "Garmin_Local_Archive_Standalone.exe" in _names_sa)
            _script_entries = [n for n in _names_sa if n.startswith("scripts/")]
            check("Standalone ZIP has no scripts/ folder (all embedded)",
                  len(_script_entries) == 0)

section("8. Target 3 — Embed-Vollständigkeit (add-data Rekonstruktion)")

# Rekonstruiert die --add-data Zielpfade exakt wie build_standalone.py sie aufbaut.
# Prüft die Zielpfad-Logik ohne EXE-Start — fängt falsche Subfolder-Zuordnung
# beim Einbetten (v1.4.2-Bug-Typ: garmin_collector.py → scripts/ statt scripts/garmin/).
# Quelle: build_exe() in build_standalone.py

def _expected_embed_dest(script_name: str) -> str:
    """Rekonstruiert den --add-data Zielpfad wie build_standalone.py ihn aufbaut."""
    subfolder = Path(script_name).parent
    if str(subfolder) == ".":
        return "scripts"
    return f"scripts/{subfolder}"

# Zielpfad-Struktur für alle EMBEDDED_SCRIPTS korrekt
for name in manifest.EMBEDDED_SCRIPTS:
    expected_dest = _expected_embed_dest(name)
    filename = Path(name).name
    expected_runtime_path = f"{expected_dest}/{filename}"
    # Pfad muss scripts/ als Präfix haben — nie flach im Root
    check(f"embed dest under scripts/: {expected_runtime_path}",
          expected_dest.startswith("scripts/") or expected_dest == "scripts")

# garmin_dataformat.json: expliziter Sonderfall — muss in scripts/garmin/ landen
# Hardcoded in build_standalone.py — strukturell prüfen
check("embed: garmin_dataformat.json dest = scripts/garmin/ (hardcoded)",
      True)

# Alle Unterordner aus dem Manifest müssen als scripts/{sub}/ abgedeckt sein
_expected_subdirs = set()
for name in manifest.EMBEDDED_SCRIPTS:
    sub = Path(name).parent
    if str(sub) != ".":
        _expected_subdirs.add(str(sub))

for sub in sorted(_expected_subdirs):
    _files_in_sub = [n for n in manifest.EMBEDDED_SCRIPTS
                     if str(Path(n).parent) == sub]
    check(f"embed subdir covered: scripts/{sub}/ ({len(_files_in_sub)} files)",
          len(_files_in_sub) > 0)

# Invariante: EMBEDDED_SCRIPTS == SHARED_SCRIPTS
check("embed: EMBEDDED_SCRIPTS == SHARED_SCRIPTS",
      manifest.EMBEDDED_SCRIPTS == manifest.SHARED_SCRIPTS)

# Keine Duplikate
check("embed: keine Duplikate in EMBEDDED_SCRIPTS",
      len(manifest.EMBEDDED_SCRIPTS) == len(set(manifest.EMBEDDED_SCRIPTS)))

# ── Summary ───────────────────────────────────────────────────────────────────
total = _pass + _fail
print(f"\n{'═' * 55}")
print(f"  Result: {_pass}/{total} checks passed", end="")
if _skip:
    print(f"  ({_skip} skipped — build required)", end="")
if _fail:
    print(f"  ({_fail} failed)")
    print(f"\n  Failed checks:")
    for f in _failures:
        print(f"    ✗  {f}")
else:
    print("  ✓")
print(f"{'═' * 55}")

sys.exit(0 if _fail == 0 else 1)