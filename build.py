#!/usr/bin/env python3
"""
build.py
Builds GarminArchive.exe — run once to create the standalone executable.

Target layout:
  /garmin_collector/
  |-- GarminArchive.exe
  |-- build.py
  |-- scripts/       <- all .py files
  |-- info/          <- README, MAINTENANCE, SETUP docs
  |-- raw/
  +-- summary/

Run from root — build.py auto-migrates scripts and docs if still in root.
"""

import subprocess
import sys
from pathlib import Path

def main():
    print("Garmin Local Archive — Build Script")
    print("=" * 40)

    print("\n[1/3] Checking dependencies ...")
    for pkg in ("pyinstaller", "keyring"):
        try:
            __import__(pkg)
            import importlib.metadata
            ver = importlib.metadata.version(pkg)
            print(f"  ✓ {pkg} {ver} already installed")
        except ImportError:
            print(f"  Installing {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
            print(f"  ✓ {pkg} installed")
    try:
        import PyInstaller
        print(f"  ✓ PyInstaller {PyInstaller.__version__} already installed")
    except ImportError:
        print("  Installing PyInstaller ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  ✓ PyInstaller installed")

    print("\n[2/3] Building .exe ...")
    root        = Path(__file__).parent
    scripts_dir = root / "scripts"
    entry_point = scripts_dir / "garmin_app.py"

    # Auto-migrate: move scripts to scripts/ if they're still in root
    SCRIPTS = [
        "garmin_app.py",
        "garmin_collector.py",
        "garmin_to_excel.py",
        "garmin_timeseries_excel.py",
        "garmin_timeseries_html.py",
        "garmin_analysis_html.py",
        "regenerate_summaries.py",
    ]
    if not entry_point.exists():
        scripts_in_root = [s for s in SCRIPTS if (root / s).exists()]
        if scripts_in_root:
            print(f"  Scripts found in root — moving to scripts/ ...")
            scripts_dir.mkdir(exist_ok=True)
            for name in scripts_in_root:
                src = root / name
                dst = scripts_dir / name
                src.rename(dst)
                print(f"    {name}")
            print(f"  ✓ Moved {len(scripts_in_root)} files to scripts/")

    # Auto-migrate: move docs to info/ if still in root
    DOCS = [
        "README.md",
        "README_APP.md",
        "MAINTENANCE.md",
        "SETUP.md",
    ]
    info_dir = root / "info"
    docs_in_root = [d for d in DOCS if (root / d).exists()]
    if docs_in_root:
        print(f"  Docs found in root — moving to info/ ...")
        info_dir.mkdir(exist_ok=True)
        for name in docs_in_root:
            src = root / name
            dst = info_dir / name
            src.rename(dst)
            print(f"    {name}")
        print(f"  ✓ Moved {len(docs_in_root)} files to info/")

    if not entry_point.exists():
        print(f"  x Entry point not found: {entry_point}")
        print("    Make sure garmin_app.py is in the scripts/ subfolder.")
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "GarminArchive",
        "--distpath", str(root),
        "--workpath", str(root / "build"),
        "--specpath", str(root),
        str(entry_point),
    ]
    result = subprocess.run(cmd, cwd=str(root))

    if result.returncode == 0:
        exe = root / "GarminArchive.exe"
        print(f"\n[3/3] Build successful!")
        print(f"\n  -> {exe}")

        # Create release ZIP
        import zipfile
        zip_path = root / "GarminArchive.zip"
        print(f"\n[+] Creating release ZIP ...")
        # Docs for end users only — MAINTENANCE.md and SETUP.md excluded
        INFO_INCLUDE = {"README.md", "README_APP.md"}
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe, "GarminArchive.exe")
            for f in sorted((root / "scripts").glob("*.py")):
                zf.write(f, f"scripts/{f.name}")
            info_dir = root / "info"
            if info_dir.exists():
                for f in sorted(info_dir.iterdir()):
                    if f.name in INFO_INCLUDE:
                        zf.write(f, f"info/{f.name}")
        print(f"  -> {zip_path}")
        print("  ZIP contents: GarminArchive.exe + scripts/ + info/README.md + info/README_APP.md")
        print("  Upload GarminArchive.zip to the GitHub release.")
    else:
        print("\n  x Build failed -- check output above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
