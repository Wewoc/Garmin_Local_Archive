#!/usr/bin/env python3
"""
build.py
Builds Garmin_Local_Archive.exe (Target 2 — Python required on target machine).

Target layout (what gets distributed):
  /release/
  |-- Garmin_Local_Archive.exe   <- built by this script
  |-- Garmin_Local_Archive.zip   <- release package
  |-- scripts/                   <- all .py files (required next to .exe at runtime)
  |   |-- garmin_app.py
  |   |-- garmin/
  |   +-- export/
  +-- info/                      <- README, README_APP docs

Run from root:
    python build.py

Targets:
  Target 1 — Dev:        python garmin_app.py         (no build needed)
  Target 2 — EXE:        python build.py              (this script, Python required)
  Target 3 — Standalone: python build_standalone.py   (no Python required)
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import build_manifest as manifest

APP_NAME = "Garmin_Local_Archive"

SCRIPTS         = manifest.SCRIPTS
INFO_INCLUDE    = manifest.INFO_INCLUDE_T2
SCRIPT_SIGNATURES = {
    **manifest.SCRIPT_SIGNATURES_BASE,
    "garmin_app.py": ["class GarminApp"],
}


def check_dependencies():
    print("\n[1/4] Checking dependencies ...")
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


def validate_scripts(root: Path):
    """
    Pre-build validation — checks all required scripts exist and contain
    expected function/class signatures. Scripts are now in garmin/ and export/.
    """
    print("\n[2/4] Validating scripts ...")
    errors = []

    # Entry point lives in root
    entry = root / "garmin_app.py"
    if not entry.exists():
        errors.append(f"  ✗ Missing entry point: garmin_app.py")
    else:
        content = entry.read_text(encoding="utf-8", errors="replace")
        if "class GarminApp" not in content:
            errors.append("  ✗ Wrong content: garmin_app.py (expected: 'class GarminApp')")

    # Shared scripts in garmin/ and export/
    for name in manifest.SHARED_SCRIPTS:
        path = root / name
        if not path.exists():
            errors.append(f"  ✗ Missing: {name}")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for sig in manifest.SCRIPT_SIGNATURES_BASE.get(name, []):
            if sig not in content:
                errors.append(f"  ✗ Wrong content: {name}  (expected: '{sig}')")

    # Required data files
    for name in manifest.REQUIRED_DATA_FILES:
        path = root / "garmin" / name
        if not path.exists():
            errors.append(f"  ✗ Missing data file: garmin/{name}")

    if errors:
        print("  Build aborted — validation failed:")
        for e in errors:
            print(e)
        sys.exit(1)

    print(f"  ✓ All scripts and data files present and valid.")


def build_exe(root: Path):
    entry_point = root / "garmin_app.py"
    print(f"\n[3/4] Building {APP_NAME}.exe (Target 2 — Python required) ...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--hidden-import", "openpyxl",
        "--hidden-import", "openpyxl.cell._writer",
        "--distpath", str(root),
        "--workpath", str(root / "build"),
        "--specpath", str(root),
        str(entry_point),
    ]
    result = subprocess.run(cmd, cwd=str(root))
    if result.returncode != 0:
        print(f"\n  ✗ Build failed — check output above.")
        sys.exit(1)


def build_zip(root: Path):
    exe      = root / f"{APP_NAME}.exe"
    zip_path = root / f"{APP_NAME}.zip"
    info_dir = root / "info"

    print(f"\n[4/4] Creating release ZIP ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, f"{APP_NAME}.exe")

        # Entry point
        entry = root / "garmin_app.py"
        if entry.exists():
            zf.write(entry, f"scripts/garmin_app.py")

        # Shared scripts — preserve subfolder structure inside scripts/
        for name in manifest.SHARED_SCRIPTS:
            f = root / name
            if f.exists():
                zf.write(f, f"scripts/{name}")

        # Data files
        for name in manifest.REQUIRED_DATA_FILES:
            f = root / "garmin" / name
            if f.exists():
                zf.write(f, f"scripts/garmin/{name}")

        # Daily Sync BAT
        bat = root / "daily_update.bat"
        if bat.exists():
            zf.write(bat, "daily_update.bat")

        # Docs
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    print(f"  -> {zip_path}")
    print(f"  ZIP contents: {APP_NAME}.exe + scripts/ + info/")
    print(f"  Upload {APP_NAME}.zip to the GitHub release.")


def prepare_scripts_dir(root: Path):
    """
    Copy scripts into scripts/ for distribution alongside the EXE.
    The EXE itself does not embed scripts — they must be present at runtime.
    """
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "garmin").mkdir(exist_ok=True)
    (scripts_dir / "export").mkdir(exist_ok=True)

    import shutil

    # Entry point
    shutil.copy2(root / "garmin_app.py", scripts_dir / "garmin_app.py")

    # Shared scripts
    for name in manifest.SHARED_SCRIPTS:
        src = root / name
        dst = scripts_dir / name
        dst.parent.mkdir(exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)

    # Data files
    for name in manifest.REQUIRED_DATA_FILES:
        src = root / "garmin" / name
        dst = scripts_dir / "garmin" / name
        if src.exists():
            shutil.copy2(src, dst)

    # info/ für ZIP aus docs/ befüllen
    info_dir = root / "info"
    info_dir.mkdir(exist_ok=True)
    for name in INFO_INCLUDE:
        # README.md liegt im Root, alle anderen in docs/
        src = root / name if (root / name).exists() else root / "docs" / name
        if src.exists():
            shutil.copy2(src, info_dir / name)

    print(f"  ✓ Scripts copied to scripts/")
    return scripts_dir


def main():
    print(f"Garmin Local Archive — Build Script (Target 2: Python required)")
    print("=" * 60)

    root = Path(__file__).parent

    check_dependencies()

    validate_scripts(root)

    scripts_dir = prepare_scripts_dir(root)

    build_exe(root)

    exe = root / f"{APP_NAME}.exe"
    print(f"\n  ✓ Build successful: {exe}")

    build_zip(root)


if __name__ == "__main__":
    main()
