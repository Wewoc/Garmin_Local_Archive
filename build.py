#!/usr/bin/env python3
"""
build.py
Builds Garmin_Local_Archive.exe (Target 2 — Python required on target machine).

Target layout:
  /garmin-local-archive/
  |-- Garmin_Local_Archive.exe   <- built by this script
  |-- Garmin_Local_Archive.zip   <- release package
  |-- build.py
  |-- build_standalone.py
  |-- scripts/                   <- all .py files (required next to .exe at runtime)
  |-- info/                      <- README, MAINTENANCE, SETUP docs
  |-- raw/
  +-- summary/

Run from root — build.py auto-migrates scripts and docs if still in root.

Targets:
  Target 1 — Dev:        python garmin_app.py  (no build needed)
  Target 2 — EXE:        python build.py       (this script, Python required on target)
  Target 3 — Standalone: python build_standalone.py  (no Python required on target)
"""

import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "Garmin_Local_Archive"

# Scripts included in the Target 2 ZIP (standalone has its own entry point)
SCRIPTS = [
    "garmin_app.py",
    "garmin_config.py",
    "garmin_api.py",
    "garmin_security.py",
    "garmin_normalizer.py",
    "garmin_quality.py",
    "garmin_sync.py",
    "garmin_import.py",
    "garmin_writer.py",
    "garmin_collector.py",
    "garmin_to_excel.py",
    "garmin_timeseries_excel.py",
    "garmin_timeseries_html.py",
    "garmin_analysis_html.py",
    "regenerate_summaries.py",
]

# Docs shown to end users — MAINTENANCE.md and SETUP.md excluded
INFO_INCLUDE = {"README.md", "README_APP.md"}


# Required signatures per script — used by validate_scripts()
# Key: filename, Value: list of strings that must appear in the file
SCRIPT_SIGNATURES = {
    "garmin_app.py":            ["class GarminApp"],
    "garmin_api.py":            ["def login", "def fetch_raw"],
    "garmin_collector.py":      ["def main", "def _process_day"],
    "garmin_quality.py":        ["def _upsert_quality"],
    "garmin_config.py":         ["GARMIN_EMAIL"],
    "garmin_security.py":       ["def load_token", "def save_token"],
    "garmin_normalizer.py":     ["def normalize", "def summarize"],
    "garmin_writer.py":         ["def write_day"],
    "garmin_sync.py":           ["def get_local_dates", "def resolve_date_range"],
    # garmin_import.py — placeholder, no signatures required yet
}


def validate_scripts(scripts_dir: Path):
    """
    Pre-build validation — checks all required scripts exist and contain
    expected function/class signatures. Aborts with a clear message on failure.
    """
    print("\n[1/4] Validating scripts ...")
    errors = []

    for name in SCRIPTS:
        path = scripts_dir / name
        if not path.exists():
            errors.append(f"  ✗ Missing:         {name}")
            continue

        content = path.read_text(encoding="utf-8", errors="replace")
        required = SCRIPT_SIGNATURES.get(name, [])
        for sig in required:
            if sig not in content:
                errors.append(f"  ✗ Wrong content:   {name}  (expected: '{sig}')")

    if errors:
        print("  Build aborted — script validation failed:")
        for e in errors:
            print(e)
        sys.exit(1)

    print(f"  ✓ All {len(SCRIPTS)} scripts present and valid.")


def check_dependencies():
    print("\n[2/4] Checking dependencies ...")
    for pkg in ("pyinstaller", "keyring", "cryptography"):
        try:
            __import__(pkg if pkg != "pyinstaller" else "PyInstaller")
            import importlib.metadata
            ver = importlib.metadata.version(pkg)
            print(f"  ✓ {pkg} {ver} already installed")
        except (ImportError, Exception):
            print(f"  Installing {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            print(f"  ✓ {pkg} installed")


def migrate_layout(root: Path, scripts_dir: Path, info_dir: Path):
    """Move scripts and docs from root to subfolders if still in root."""
    scripts_in_root = [s for s in SCRIPTS if (root / s).exists()]
    if scripts_in_root:
        print(f"  Scripts found in root — moving to scripts/ ...")
        scripts_dir.mkdir(exist_ok=True)
        for name in scripts_in_root:
            (root / name).rename(scripts_dir / name)
            print(f"    {name}")
        print(f"  ✓ Moved {len(scripts_in_root)} files to scripts/")

    docs = ["README.md", "README_APP.md", "MAINTENANCE.md", "SETUP.md"]
    docs_in_root = [d for d in docs if (root / d).exists()]
    if docs_in_root:
        print(f"  Docs found in root — moving to info/ ...")
        info_dir.mkdir(exist_ok=True)
        for name in docs_in_root:
            (root / name).rename(info_dir / name)
            print(f"    {name}")
        print(f"  ✓ Moved {len(docs_in_root)} files to info/")


def build_exe(root: Path, scripts_dir: Path, entry_point: Path):
    print(f"\n[3/4] Building {APP_NAME}.exe (Target 2 — Python required) ...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", str(root),
        "--workpath", str(root / "build"),
        "--specpath", str(root),
        str(entry_point),
    ]
    result = subprocess.run(cmd, cwd=str(root))
    if result.returncode != 0:
        print(f"\n  ✗ Build failed — check output above.")
        sys.exit(1)


def build_zip(root: Path, scripts_dir: Path, info_dir: Path):
    exe      = root / f"{APP_NAME}.exe"
    zip_path = root / f"{APP_NAME}.zip"

    print(f"\n[4/4] Creating release ZIP ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, f"{APP_NAME}.exe")
        for name in SCRIPTS:
            f = scripts_dir / name
            if f.exists():
                zf.write(f, f"scripts/{f.name}")
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    print(f"  -> {zip_path}")
    print(f"  ZIP contents: {APP_NAME}.exe + scripts/ + info/README.md + info/README_APP.md")
    print(f"  Upload {APP_NAME}.zip to the GitHub release.")


def main():
    print(f"Garmin Local Archive — Build Script (Target 2: Python required)")
    print("=" * 60)

    root        = Path(__file__).parent
    scripts_dir = root / "scripts"
    info_dir    = root / "info"
    entry_point = scripts_dir / "garmin_app.py"

    check_dependencies()

    print("\n  Preparing layout ...")
    if not entry_point.exists():
        migrate_layout(root, scripts_dir, info_dir)

    if not entry_point.exists():
        print(f"  ✗ Entry point not found: {entry_point}")
        print(f"    Make sure garmin_app.py is in the scripts/ subfolder.")
        sys.exit(1)

    validate_scripts(scripts_dir)

    build_exe(root, scripts_dir, entry_point)

    exe = root / f"{APP_NAME}.exe"
    print(f"\n  ✓ Build successful: {exe}")

    build_zip(root, scripts_dir, info_dir)


if __name__ == "__main__":
    main()
