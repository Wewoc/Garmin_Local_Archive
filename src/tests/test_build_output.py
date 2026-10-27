#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

import py_compile
import sys
import zipfile
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "compiler"))
sys.path.insert(0, str(Path(__file__).parent))

import build_manifest as manifest
from support import check, skip, section, summary

# ── Build root ─────────────────────────────────────────────────────────────────
# Both build targets write output to the project root (--distpath = root)
_BUILD_ROOT  = _ROOT
_SCRIPTS_DIR = _BUILD_ROOT / "scripts"
_T2_EXE      = _BUILD_ROOT / "Garmin_Local_Archive.exe"
_T2_ZIP      = _BUILD_ROOT / "Garmin_Local_Archive.zip"
_T2_CHECKSUM = _BUILD_ROOT / "Garmin_Local_Archive.zip.sha256"
_T3_DIR      = _BUILD_ROOT / "Garmin_Local_Archive_Standalone"         # --onedir folder
_T3_EXE      = _T3_DIR / "Garmin_Local_Archive_Standalone.exe"         # EXE inside folder
_T3_ZIP      = _BUILD_ROOT / "Garmin_Local_Archive_Standalone.zip"
_T3_CHECKSUM = _BUILD_ROOT / "Garmin_Local_Archive_Standalone.zip.sha256"
_MCP_EXE     = _BUILD_ROOT / "mcp_server.exe"                          # T3.3 (--onefile)

_T2_BUILT  = _T2_EXE.exists()
_T3_BUILT  = _T3_DIR.exists() and _T3_EXE.exists()                     # onedir: folder + EXE
_MCP_BUILT = _MCP_EXE.exists()

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
check("ALL_SCRIPTS contains daily_update.py",
      "daily_update.py" in manifest.ALL_SCRIPTS)
check("REQUIRED_DATA_FILES not empty",
      len(manifest.REQUIRED_DATA_FILES) > 0)
check("REQUIRED_DATA_FILES entries are (subdir, filename) tuples",
      all(isinstance(t, tuple) and len(t) == 2 for t in manifest.REQUIRED_DATA_FILES))
check("garmin_dataformat.json in REQUIRED_DATA_FILES",
      ("garmin", "garmin_dataformat.json") in manifest.REQUIRED_DATA_FILES)
check("plotly.min.js in REQUIRED_DATA_FILES",
      ("layouts", "plotly.min.js") in manifest.REQUIRED_DATA_FILES)

_all_known = set(manifest.ALL_SCRIPTS) | set(manifest.SHARED_SCRIPTS)
for sig_key in manifest.SCRIPT_SIGNATURES_BASE:
    check(f"SCRIPT_SIGNATURES_BASE key exists in manifest: {sig_key}",
          sig_key in _all_known)

# ── Hidden imports (P7-03, v1.6.5.5) ───────────────────────────────────────────
# Guards the consolidated HIDDEN_IMPORTS_COMMON/_T3_EXTRA (P3-02) against
# silent drift — same failure class as the four missing hidden imports
# fixed in v1.6.5.3 (P3-01).
check("HIDDEN_IMPORTS_COMMON not empty",
      len(manifest.HIDDEN_IMPORTS_COMMON) > 0)
check("No duplicates in HIDDEN_IMPORTS_COMMON",
      len(manifest.HIDDEN_IMPORTS_COMMON) == len(set(manifest.HIDDEN_IMPORTS_COMMON)))
check("No duplicates in HIDDEN_IMPORTS_T3_EXTRA",
      len(manifest.HIDDEN_IMPORTS_T3_EXTRA) == len(set(manifest.HIDDEN_IMPORTS_T3_EXTRA)))
check("HIDDEN_IMPORTS_COMMON and HIDDEN_IMPORTS_T3_EXTRA don't overlap",
      set(manifest.HIDDEN_IMPORTS_COMMON).isdisjoint(set(manifest.HIDDEN_IMPORTS_T3_EXTRA)))
for _dep in ("curl_cffi", "curl_cffi.requests", "ua_generator", "openpyxl.cell._writer"):
    check(f"HIDDEN_IMPORTS_COMMON contains known lazy dep: {_dep}",
          _dep in manifest.HIDDEN_IMPORTS_COMMON)

# ── v1.7.6: sqlite3 in the T2 GUI process ──────────────────────────────────────
# The automatic export loads exports/export_runner.py inside the GUI process
# (app/outputs/export_auto.py); the runner imports mcp_update -> mcp_sql -> sqlite3. A T2
# EXE without sqlite3 answered "No module named 'sqlite3'" and wrote no export (found in a
# real sync, 2026-10-17). T2 builds from HIDDEN_IMPORTS_COMMON only, T3 from COMMON + T3_EXTRA.
for _dep in ("sqlite3", "_sqlite3"):
    check(f"HIDDEN_IMPORTS_COMMON contains {_dep} (T2 GUI process: the automatic export needs it)",
          _dep in manifest.HIDDEN_IMPORTS_COMMON)
    check(f"{_dep} is in the T3 list too (COMMON + T3_EXTRA), and listed once",
          (manifest.HIDDEN_IMPORTS_COMMON + manifest.HIDDEN_IMPORTS_T3_EXTRA).count(_dep) == 1)

# ── v1.7.6: standard-library modules only the bulk import uses ────────────────
# The scripts under garmin/ are loose files, PyInstaller does not analyse them: a
# standard-library module that no other part of the app imports is in the frozen T3
# process only by luck. HIDDEN_IMPORTS_T3_EXTRA already does this for sqlite3.
import ast
_stdlib = set(sys.stdlib_module_names) - {"__future__"}


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found & _stdlib


_scripts = [n for n in manifest.SHARED_SCRIPTS + ["garmin_app.py", "garmin_app_standalone.py"] if n.endswith(".py")]
_bulk_scripts = [n for n in _scripts if Path(n).name.startswith("garmin_bulk_")]
_other_std = set().union(*(_imports(_ROOT / n) for n in _scripts if n not in _bulk_scripts))
_bulk_only = set().union(*(_imports(_ROOT / n) for n in _bulk_scripts)) - _other_std
_BULK_STDLIB = {"array", "bisect", "dataclasses", "tempfile"}      # tempfile is also used by garmin_app_base.py; listed anyway
check("bulk import: the seven bulk scripts are found (fit reader, export scanner, normalizer, writer, import, daily-values import, rebuild)", len(_bulk_scripts) == 7)
check("bulk import: the modules only the bulk scripts import are array and bisect — "
      "a new standard-library import in a bulk script must be looked at and listed in HIDDEN_IMPORTS_T3_EXTRA "
      "(dataclasses is used by the bulk scripts too, but garmin_backup_common imports it since v1.7.6.2, so it is no longer 'only bulk'; "
      "it stays in the list below)",
      _bulk_only == {"array", "bisect"} and _bulk_only <= _BULK_STDLIB)
check("bulk import: dataclasses is imported by a bulk script and stays listed in HIDDEN_IMPORTS_T3_EXTRA",
      any("dataclasses" in _imports(_ROOT / n) for n in _bulk_scripts) and "dataclasses" in manifest.HIDDEN_IMPORTS_T3_EXTRA)
for _dep in sorted(_BULK_STDLIB):
    check(f"HIDDEN_IMPORTS_T3_EXTRA contains a module the bulk import needs: {_dep}",
          _dep in manifest.HIDDEN_IMPORTS_T3_EXTRA)
    check(f"bulk import: {_dep} is not in HIDDEN_IMPORTS_COMMON (T2 runs the collector with the Python of the target)",
          _dep not in manifest.HIDDEN_IMPORTS_COMMON)

# ── v1.7.6: signatures of the new entry points ────────────────────────────────
check("signature: garmin_collector lists the bulk import phases and the quality-log marking",
      {"def _run_bulk_import", "def _mark_bulk_days", "def _apply_bulk_marks", "def _run_bulk_mark_catch_up",
       "def _run_bulk_backup", "def _finish_aggregates", "def _apply_aggregates"}
      <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_collector.py"]))
check("signature: the old garmin_collector entries are all still there",
      {"def main", "def run_import", "def _run_resting_hr_repair", "def run_capability_scan"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_collector.py"]))
check("signature: garmin_collector lists the track migration step (v1.7.6.3)",
      "def _run_track_migration" in manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_collector.py"])
check("signature: garmin_collector lists the bulk rebuild step (v1.7.6.5)",
      "def _run_bulk_rebuild" in manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_collector.py"])
check("signature: garmin_track_migration lists the entry points of scan, preview and run (v1.7.6.3)",
      {"def scan_archive", "def pending", "def plan_migration", "def run_migration", "def format_result"}
      <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_track_migration.py"]))
check("signature: garmin_quality lists record_bulk_intraday",
      "record_bulk_intraday" in manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_quality.py"])
check("signature: garmin_quality lists the catch-up of missing bulk marks (v1.7.6.1)",
      {"unmarked_bulk_days", "catch_up_bulk_intraday", "record_bulk_aggregates", "catch_up_bulk_aggregates"}
      <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_quality.py"]))
check("signature: garmin_bulk_writer lists list_days and keeps its old entries (v1.7.6.1)",
      {"def list_days", "def write_day", "def day_status", "def store_original", "def original_present"}
      <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_writer.py"]))
check("signature: garmin_bulk_writer lists the functions the mirror import uses (v1.7.6.2)",
      {"def import_day_file", "def describe_container_path", "def list_originals"}
      <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_writer.py"]))
check("signature: garmin_bulk_writer lists the aggregates and JSON-original functions (v1.7.6.1)",
      {"def write_aggregates", "def aggregates_status", "def read_aggregates", "def list_aggregate_days",
       "def store_original_json", "def original_json_present"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_writer.py"]))
check("signature: garmin_writer lists rebuild_summary, garmin_bulk_writer load_aggregates, old entries stay (v1.7.6.1)",
      {"def write_day", "def read_raw", "def read_summary", "def rebuild_summary"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_writer.py"])
      and "def load_aggregates" in manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_writer.py"])
check("signature: garmin_import lists load_bulk_with_entries and keeps load_bulk and parse_day (v1.7.6.1)",
      {"def load_bulk", "def parse_day", "def load_bulk_with_entries"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_import.py"]))
check("signature: garmin_import lists detect_kind and days_from_originals, garmin_bulk_json_import store_day (v1.7.6.5)",
      {"def detect_kind", "def days_from_originals"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_import.py"])
      and {"def store_day", "def empty_summary", "def run_aggregates_import"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_json_import.py"]))
check("signature: garmin_bulk_rebuild is listed with its entry point and is a shared script (v1.7.6.5)",
      {"def run_aggregates_rebuild", "def format_summary"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_bulk_rebuild.py"])
      and "garmin/garmin_bulk_rebuild.py" in manifest.SHARED_SCRIPTS)
check("signature: garmin_quality keeps its old entries",
      {"from quality._maint import", "QUALITY_LOCK"} <= set(manifest.SCRIPT_SIGNATURES_BASE["garmin/garmin_quality.py"]))

# ══════════════════════════════════════════════════════════════════════════════
#  2. Source-Integrität — alle Manifest-Scripts vorhanden
# ══════════════════════════════════════════════════════════════════════════════
section("2. Source-Integrität — Manifest-Scripts im Projektordner")

check("garmin_app.py exists",             (_ROOT / "garmin_app.py").exists())
check("garmin_app_standalone.py exists",  (_ROOT / "garmin_app_standalone.py").exists())
check("build_manifest.py exists",         (_ROOT / "compiler" / "build_manifest.py").exists())

for name in manifest.SHARED_SCRIPTS:
    check(f"source exists: {name}", (_ROOT / name).exists())

for subdir, name in manifest.REQUIRED_DATA_FILES:
    check(f"data file exists: {subdir}/{name}", (_ROOT / subdir / name).exists())

check("daily_update.py exists",          (_ROOT / "scheduler" / "daily_update.py").exists())
check("daily_update.bat exists",              (_ROOT / "scheduler" / "daily_update.bat").exists())
check("daily_update.py exists",               (_ROOT / "scheduler" / "daily_update.py").exists())
check("daily_update_task.xml exists",         (_ROOT / "scheduler" / "daily_update_task.xml").exists())
check("Starte_Daily_Sync.bat exists",         (_ROOT / "scheduler" / "Starte_Daily_Sync.bat").exists())

_entry_sigs = {
    "garmin_app.py":            ["class GarminApp"],
    "garmin_app_standalone.py": ["class GarminApp"],
    "daily_update.py":          ["def main"],
}
# Entry points nicht im Root-Pfad: daily_update.py liegt nach Umbau in scheduler/
_entry_overrides = {
    "daily_update.py": _ROOT / "scheduler" / "daily_update.py",
}
for fname, sigs in {**manifest.SCRIPT_SIGNATURES_BASE, **_entry_sigs}.items():
    fpath = _entry_overrides.get(fname, _ROOT / fname)
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

    for subdir, name in manifest.REQUIRED_DATA_FILES:
        check(f"scripts/{subdir}/{name} exists",
              (_SCRIPTS_DIR / subdir / name).exists())

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
        check("ZIP contains scheduler/daily_update.bat",
              "scheduler/daily_update.bat" in _names)
        check("ZIP contains scheduler/daily_update.py",
              "scheduler/daily_update.py" in _names)
        check("ZIP contains Starte_Daily_Sync.bat",
              "Starte_Daily_Sync.bat" in _names)
        check("ZIP contains info/daily_update_task.xml",
              "info/daily_update_task.xml" in _names)
        for name in manifest.SHARED_SCRIPTS:
            check(f"ZIP contains scripts/{name}",
                  f"scripts/{name}" in _names)
        for subdir, name in manifest.REQUIRED_DATA_FILES:
            check(f"ZIP contains scripts/{subdir}/{name}",
                  f"scripts/{subdir}/{name}" in _names)
        # v1.7.2.4-Nacherweiterung — self-update delivery files (build.py::build_zip())
        check("ZIP contains updater_helper.ps1",
              "updater_helper.ps1" in _names)

if not _T2_BUILT:
    skip("Garmin_Local_Archive.zip.sha256 exists", "no build found")
else:
    check("Garmin_Local_Archive.zip.sha256 exists", _T2_CHECKSUM.exists())

# ══════════════════════════════════════════════════════════════════════════════
#  7. Target 3 — Standalone EXE + ZIP
# ══════════════════════════════════════════════════════════════════════════════
section("7. Target 3 — Standalone EXEs + combined ZIP")

_DU_EXE   = _BUILD_ROOT / "daily_update.exe"
_DU_BUILT = _DU_EXE.exists()

# T3.1 — --onedir
if not _T3_BUILT:
    skip("Garmin_Local_Archive_Standalone/ folder exists", "no build found")
    skip("Garmin_Local_Archive_Standalone.exe exists", "no build found")
    skip("Standalone _internal/ exists", "no build found")
else:
    check("Garmin_Local_Archive_Standalone/ folder exists", _T3_DIR.exists())
    check("Garmin_Local_Archive_Standalone.exe exists", _T3_EXE.exists())
    check("Standalone EXE size > 0 bytes", _T3_EXE.stat().st_size > 0)
    _t3_internal = _T3_DIR / "_internal"
    check("Standalone _internal/ exists (--onedir layout)", _t3_internal.exists())

# T3.2 — --onefile
if not _DU_BUILT:
    skip("daily_update.exe exists", "no build found")
else:
    check("daily_update.exe exists", True)
    check("daily_update.exe size > 0 bytes", _DU_EXE.stat().st_size > 0)

# T3.3 — --onefile (MCP server)
if not _MCP_BUILT:
    skip("mcp_server.exe exists", "no build found")
else:
    check("mcp_server.exe exists", True)
    check("mcp_server.exe size > 0 bytes", _MCP_EXE.stat().st_size > 0)

if not _T3_BUILT or not _DU_BUILT or not _MCP_BUILT:
    skip("combined ZIP checks", "one or more targets missing")
elif not _T3_ZIP.exists():
    skip("combined ZIP checks", "Garmin_Local_Archive_Standalone.zip not found")
else:
    check("Garmin_Local_Archive_Standalone.zip exists", True)
    with zipfile.ZipFile(_T3_ZIP, "r") as zf:
        _names_sa = set(zf.namelist())
        # T3.1 — flat layout: EXE + _internal/ directly in ZIP root
        check("combined ZIP contains Standalone EXE (flat in root)",
              "Garmin_Local_Archive_Standalone.exe" in _names_sa)
        check("combined ZIP contains _internal/ (flat, --onedir)",
              any(n.startswith("_internal/") for n in _names_sa))
        # T3.2 flat in ZIP root
        check("combined ZIP contains daily_update.exe (flat in root)",
              "daily_update.exe" in _names_sa)
        # T3.3 flat in ZIP root
        check("combined ZIP contains mcp_server.exe (flat in root)",
              "mcp_server.exe" in _names_sa)
        # v1.7.2.4 — self-update helper, flat in ZIP root
        check("combined ZIP contains updater_helper.ps1",
              "updater_helper.ps1" in _names_sa)
        # info/ flat in ZIP root
        check("combined ZIP contains info/QUICKSTART.txt",
              "info/QUICKSTART.txt" in _names_sa)
        _script_entries = [n for n in _names_sa if n.startswith("scripts/")]
        check("combined ZIP has no scripts/ folder (all embedded)",
              len(_script_entries) == 0)

if not _T3_BUILT or not _DU_BUILT or not _MCP_BUILT:
    skip("Garmin_Local_Archive_Standalone.zip.sha256 exists", "one or more targets missing")
else:
    check("Garmin_Local_Archive_Standalone.zip.sha256 exists", _T3_CHECKSUM.exists())

section("8. Target 3 — Embed-Vollständigkeit (add-data Rekonstruktion)")

# Importiert die reale Zielpfad-Funktion aus build_standalone.py statt sie
# hier nachzubilden (P7-02, v1.6.5.5) — Test läuft gegen den echten Code,
# kein Rate-Duplikat mehr, das aus dem Takt laufen kann.
# Fängt weiterhin falsche Subfolder-Zuordnung beim Einbetten (v1.4.2-Bug-Typ:
# garmin_collector.py → scripts/ statt scripts/garmin/).
from build_standalone import embed_dest

# Zielpfad-Struktur für alle EMBEDDED_SCRIPTS korrekt
for name in manifest.EMBEDDED_SCRIPTS:
    expected_dest = embed_dest(Path(name).parent)
    filename = Path(name).name
    expected_runtime_path = f"{expected_dest}/{filename}"
    # Pfad muss scripts/ als Präfix haben — nie flach im Root
    check(f"embed dest under scripts/: {expected_runtime_path}",
          expected_dest.startswith("scripts/") or expected_dest == "scripts")

# Data files: generic (subdir, filename) tuples — jetzt echte Prüfung gegen
# embed_dest() statt True-Tautologie (P7-01, v1.6.5.5). Existenz der
# Quelldatei bleibt in §2 geprüft, hier geht es nur um den Zielpfad.
for subdir, name in manifest.REQUIRED_DATA_FILES:
    expected_dest = embed_dest(subdir)
    check(f"embed: {name} dest = {expected_dest}/ (real embed_dest())",
          expected_dest == f"scripts/{subdir}")

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
summary()
