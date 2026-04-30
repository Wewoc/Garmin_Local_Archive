#!/usr/bin/env python3
"""
build_standalone.py
Builds two headless/GUI targets (no Python required on target machine).

  T3.1 — Garmin_Local_Archive_Standalone.exe   GUI entry point
  T3.2 — daily_update.exe                      Headless entry point (Task Scheduler)

All scripts and Python dependencies are embedded via PyInstaller.

Run from root:
    python build_standalone.py

Targets:
  Target 1 — Dev:          python garmin_app.py             (no build needed)
  Target 2 — EXE:          python build.py                  (Python required on target)
  Target 3.1 — Standalone: Garmin_Local_Archive_Standalone.exe  (this script)
  Target 3.2 — Headless:   daily_update.exe                     (this script)
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import build_manifest as manifest

EMBEDDED_SCRIPTS  = manifest.EMBEDDED_SCRIPTS
INFO_INCLUDE      = manifest.INFO_INCLUDE_T3
RUNTIME_DEPS      = manifest.RUNTIME_DEPS

SCRIPT_SIGNATURES = {
    **manifest.SCRIPT_SIGNATURES_BASE,
    "garmin_app_standalone.py": ["class GarminApp"],
    "daily_update.py":          ["def main"],
}


def check_dependencies(root: Path):
    print("\n[1/3] Checking build dependencies ...")

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
    expected function/class signatures.
    """
    print("\n[2/3] Validating scripts ...")
    errors = []

    # Entry points in root
    for ep, sig in [
        ("garmin_app_standalone.py", "class GarminApp"),
        ("daily_update.py",          "def main"),
    ]:
        entry = root / ep
        if not entry.exists():
            errors.append(f"  ✗ Missing entry point: {ep}")
        else:
            content = entry.read_text(encoding="utf-8", errors="replace")
            if sig not in content:
                errors.append(f"  ✗ Wrong content: {ep} (expected: '{sig}')")

    # Embedded scripts
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
    print(f"  ✓ Entry points: garmin_app_standalone.py, daily_update.py")
    for s in EMBEDDED_SCRIPTS:
        print(f"  ✓ Embed: {s}")


def build_exe(root: Path, name: str, entry_point: Path, windowed: bool = True):
    print(f"\n  Building {name}.exe ...")
    print(f"  Entry point: {entry_point}")
    print(f"  Embedding {len(EMBEDDED_SCRIPTS)} scripts as data ...")

    sep = ";" if sys.platform == "win32" else ":"

    add_data_args = []
    for script in EMBEDDED_SCRIPTS:
        src = root / script
        subfolder = Path(script).parent
        dest = f"scripts/{subfolder}" if str(subfolder) != "." else "scripts"
        add_data_args += ["--add-data", f"{src}{sep}{dest}"]

    # Embed garmin_dataformat.json
    dataformat_src = root / "garmin" / "garmin_dataformat.json"
    if dataformat_src.exists():
        add_data_args += ["--add-data", f"{dataformat_src}{sep}scripts/garmin"]
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
        "--name", name,
        "--distpath", str(root),
        "--workpath", str(root / f"build_{name}_work"),
        "--specpath", str(root),
        *add_data_args,
        *hidden_args,
        str(entry_point),
    ]
    if windowed:
        cmd.insert(3, "--windowed")

    result = subprocess.run(cmd, cwd=str(root))
    if result.returncode != 0:
        print(f"\n  ✗ Build failed — check output above.")
        sys.exit(1)

    print(f"  ✓ {name}.exe built successfully.")


def build_combined_zip(root: Path):
    """Packs T3.1 + T3.2 EXEs into a single release ZIP."""
    zip_path = root / "Garmin_Local_Archive_Standalone.zip"
    info_dir = root / "info"

    print(f"\n  Creating Garmin_Local_Archive_Standalone.zip (T3.1 + T3.2) ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(root / "Garmin_Local_Archive_Standalone.exe",
                 "Garmin_Local_Archive_Standalone.exe")
        zf.write(root / "daily_update.exe",
                 "daily_update.exe")
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    print(f"  -> {zip_path}")
    print(f"  ZIP: Garmin_Local_Archive_Standalone.exe + daily_update.exe + info/")
    print(f"  Upload Garmin_Local_Archive_Standalone.zip to GitHub release.")


def main():
    print("Garmin Local Archive — Build Script (Target 3: Standalone, no Python required)")
    print("=" * 80)

    root = Path(__file__).parent

    check_dependencies(root)
    validate_scripts(root)

    # info/ für ZIP aus docs/ befüllen
    import shutil
    info_dir = root / "info"
    info_dir.mkdir(exist_ok=True)
    for name in INFO_INCLUDE:
        src = root / name if (root / name).exists() else root / "docs" / name
        if src.exists():
            shutil.copy2(src, info_dir / name)

    print(f"\n[3/3] Building ...")

    # --- T3.1: GUI ---
    print(f"\n  --- T3.1: Garmin_Local_Archive_Standalone.exe ---")
    build_exe(root,
              name="Garmin_Local_Archive_Standalone",
              entry_point=root / "garmin_app_standalone.py",
              windowed=True)
    # --- T3.2: Headless ---
    print(f"\n  --- T3.2: daily_update.exe ---")
    build_exe(root,
              name="daily_update",
              entry_point=root / "daily_update.py",
              windowed=False)

    build_combined_zip(root)

    print(f"\n  Done. Distribute Garmin_Local_Archive_Standalone.zip — no Python installation needed on target.")


if __name__ == "__main__":
    main()