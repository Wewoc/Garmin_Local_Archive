#!/usr/bin/env python3
"""
build_standalone.py
Builds Garmin_Local_Archive_Standalone.exe (Target 3 — no Python required).

All scripts and Python dependencies are embedded in the EXE via PyInstaller.
The target machine needs no Python installation.

Target layout (what gets distributed):
  /release/
  |-- Garmin_Local_Archive_Standalone.exe   <- everything embedded
  +-- Garmin_Local_Archive_Standalone.zip   <- same, zipped for distribution

At runtime the EXE extracts scripts to a temp folder (sys._MEIPASS/scripts/)
and uses its own embedded Python interpreter to run them as subprocesses.
garmin_app_standalone.py is the entry point.

Targets:
  Target 1 — Dev:        python garmin_app.py             (no build needed)
  Target 2 — EXE:        python build.py                  (Python required on target)
  Target 3 — Standalone: python build_standalone.py       (this script)
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import build_manifest as manifest

APP_NAME = "Garmin_Local_Archive_Standalone"

EMBEDDED_SCRIPTS  = manifest.EMBEDDED_SCRIPTS
INFO_INCLUDE      = manifest.INFO_INCLUDE_T3
RUNTIME_DEPS      = manifest.RUNTIME_DEPS

SCRIPT_SIGNATURES = {
    **manifest.SCRIPT_SIGNATURES_BASE,
    "garmin_app_standalone.py": ["class GarminApp"],
}


def check_dependencies(root: Path):
    print("\n[1/4] Checking build dependencies ...")

    try:
        import PyInstaller
        print(f"  ✓ PyInstaller {PyInstaller.__version__} already installed")
    except ImportError:
        print("  Installing PyInstaller ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  ✓ PyInstaller installed")

    print("\n  Checking runtime dependencies (must be installed for bundling) ...")
    for pkg in RUNTIME_DEPS:
        try:
            import importlib.metadata
            ver = importlib.metadata.version(pkg)
            print(f"  ✓ {pkg} {ver}")
        except Exception:
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
    entry = root / "garmin_app_standalone.py"
    if not entry.exists():
        errors.append("  ✗ Missing entry point: garmin_app_standalone.py")
    else:
        content = entry.read_text(encoding="utf-8", errors="replace")
        if "class GarminApp" not in content:
            errors.append("  ✗ Wrong content: garmin_app_standalone.py (expected: 'class GarminApp')")

    # Embedded scripts in garmin/ and export/
    for name in EMBEDDED_SCRIPTS:
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
    print(f"  ✓ Entry point: garmin_app_standalone.py")
    for s in EMBEDDED_SCRIPTS:
        print(f"  ✓ Embed: {s}")


def build_exe(root: Path):
    entry_point = root / "garmin_app_standalone.py"
    print(f"\n[3/4] Building {APP_NAME}.exe ...")
    print(f"  Entry point: {entry_point}")
    print(f"  Embedding {len(EMBEDDED_SCRIPTS)} scripts as data ...")

    # --add-data embeds scripts into sys._MEIPASS/scripts/ at runtime
    # garmin_app_standalone.py uses script_dir() → sys.executable.parent / "scripts"
    # so all scripts land in scripts/ flat (no subfolders at runtime)
    sep = ";" if sys.platform == "win32" else ":"

    add_data_args = []
    for name in EMBEDDED_SCRIPTS:
        src = root / name
        # Preserve subfolder structure under scripts/
        # e.g. context/context_collector.py → scripts/context/
        subfolder = Path(name).parent  # e.g. "context", "maps", "garmin"
        dest = f"scripts/{subfolder}" if str(subfolder) != "." else "scripts"
        add_data_args += ["--add-data", f"{src}{sep}{dest}"]

    # Embed garmin_dataformat.json
    dataformat_src = root / "garmin" / "garmin_dataformat.json"
    if dataformat_src.exists():
        add_data_args += ["--add-data", f"{dataformat_src}{sep}scripts"]
    else:
        print(f"  ✗ garmin_dataformat.json not found in garmin/ — aborting build")
        sys.exit(1)

    hidden = [
        "garminconnect",
        "openpyxl",
        "openpyxl.styles",
        "openpyxl.chart",
        "openpyxl.utils",
        "keyring",
        "keyring.backends",
        "keyring.backends.Windows",
        "cryptography",
        "cryptography.hazmat.primitives.kdf.pbkdf2",
        "cryptography.hazmat.primitives.ciphers.aead",
        "cryptography.hazmat.primitives.hashes",
        "requests",
        "cloudscraper",
        "lxml",
        "lxml.etree",
    ]
    hidden_args = []
    for h in hidden:
        hidden_args += ["--hidden-import", h]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", str(root),
        "--workpath", str(root / "build_standalone_work"),
        "--specpath", str(root),
        *add_data_args,
        *hidden_args,
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
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    print(f"  -> {zip_path}")
    print(f"  ZIP contents: {APP_NAME}.exe + info/")
    print(f"  No scripts/ folder needed — everything is embedded in the EXE.")
    print(f"  Upload {APP_NAME}.zip to the GitHub release.")


def main():
    print(f"Garmin Local Archive — Build Script (Target 3: Standalone, no Python required)")
    print("=" * 75)

    root = Path(__file__).parent

    check_dependencies(root)

    validate_scripts(root)

    # info/ für ZIP aus docs/ befüllen
    import shutil
    info_dir = root / "info"
    info_dir.mkdir(exist_ok=True)
    for name in INFO_INCLUDE:
        # README.md liegt im Root, alle anderen in docs/
        src = root / name if (root / name).exists() else root / "docs" / name
        if src.exists():
            shutil.copy2(src, info_dir / name)

    build_exe(root)

    exe = root / f"{APP_NAME}.exe"
    print(f"\n  ✓ Build successful: {exe}")

    build_zip(root)

    print(f"\n  Done. Distribute {APP_NAME}.zip — no Python installation needed on target.")


if __name__ == "__main__":
    main()
