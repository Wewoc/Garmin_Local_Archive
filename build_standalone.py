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

At runtime the EXE extracts scripts to a temp folder and uses its own
embedded Python interpreter (sys.executable) to run them as subprocesses.
garmin_app_standalone.py is used as the entry point — it differs from
garmin_app.py only in script_dir() and _find_python().

Targets:
  Target 1 — Dev:        python garmin_app.py         (no build needed)
  Target 2 — EXE:        python build.py              (Python required on target)
  Target 3 — Standalone: python build_standalone.py   (this script)
"""

import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "Garmin_Local_Archive_Standalone"

# All scripts to embed — garmin_app_standalone.py is the entry point,
# the rest are embedded as data and extracted at runtime.
EMBEDDED_SCRIPTS = [
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

# Runtime dependencies that must be installed before building
RUNTIME_DEPS = [
    "garminconnect",
    "openpyxl",
    "keyring",
    "cryptography",
    "requests",
]

INFO_INCLUDE = {"README.md", "README_APP_Standalone.md"}

# All scripts that belong in scripts/ (including standalone entry point)
ALL_SCRIPTS = [
    "garmin_app.py",
    "garmin_app_standalone.py",
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

DOCS = ["README.md", "README_APP.md", "README_APP_Standalone.md", "MAINTENANCE.md", "SETUP.md"]


# Required signatures per script — used by validate_scripts()
SCRIPT_SIGNATURES = {
    "garmin_app_standalone.py": ["class GarminApp"],
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

# All scripts checked by validate_scripts (entry point + embedded)
_ALL_VALIDATED = ["garmin_app_standalone.py"] + EMBEDDED_SCRIPTS


def validate_scripts(scripts_dir: Path):
    """
    Pre-build validation — checks all required scripts exist and contain
    expected function/class signatures. Aborts with a clear message on failure.
    """
    print("\n  Validating scripts ...")
    errors = []

    for name in _ALL_VALIDATED:
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

    print(f"  ✓ All {len(_ALL_VALIDATED)} scripts present and valid.")


def migrate_layout(root: Path, scripts_dir: Path, info_dir: Path):
    """Move scripts and docs from root to subfolders if still in root."""
    scripts_in_root = [s for s in ALL_SCRIPTS if (root / s).exists()]
    if scripts_in_root:
        print(f"  Scripts found in root — moving to scripts/ ...")
        scripts_dir.mkdir(exist_ok=True)
        for name in scripts_in_root:
            (root / name).rename(scripts_dir / name)
            print(f"    {name}")
        print(f"  ✓ Moved {len(scripts_in_root)} files to scripts/")

    docs_in_root = [d for d in DOCS if (root / d).exists()]
    if docs_in_root:
        print(f"  Docs found in root — moving to info/ ...")
        info_dir.mkdir(exist_ok=True)
        for name in docs_in_root:
            (root / name).rename(info_dir / name)
            print(f"    {name}")
        print(f"  ✓ Moved {len(docs_in_root)} files to info/")


def check_dependencies(root: Path):
    print("\n[1/4] Checking build dependencies ...")

    # PyInstaller
    try:
        import PyInstaller
        print(f"  ✓ PyInstaller {PyInstaller.__version__} already installed")
    except ImportError:
        print("  Installing PyInstaller ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("  ✓ PyInstaller installed")

    # Runtime deps — must be present so PyInstaller can bundle them
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


def check_entry_point(scripts_dir: Path) -> Path:
    entry = scripts_dir / "garmin_app_standalone.py"
    if not entry.exists():
        print(f"\n  ✗ Entry point not found: {entry}")
        print(f"    garmin_app_standalone.py must be in scripts/")
        print(f"    Run: python build_standalone.py  (from the repo root)")
        sys.exit(1)
    return entry


def check_embedded_scripts(scripts_dir: Path):
    missing = [s for s in EMBEDDED_SCRIPTS if not (scripts_dir / s).exists()]
    if missing:
        print(f"\n  ✗ Missing scripts in scripts/:")
        for s in missing:
            print(f"    {s}")
        sys.exit(1)


def build_exe(root: Path, scripts_dir: Path, entry_point: Path):
    print(f"\n[3/4] Building {APP_NAME}.exe ...")
    print(f"  Entry point: {entry_point}")
    print(f"  Embedding {len(EMBEDDED_SCRIPTS)} scripts as data ...")

    # --add-data embeds scripts/ into sys._MEIPASS/scripts/ at runtime
    # separator is ; on Windows, : on Linux/macOS
    sep = ";" if sys.platform == "win32" else ":"

    add_data_args = []
    for script in EMBEDDED_SCRIPTS:
        src = scripts_dir / script
        add_data_args += ["--add-data", f"{src}{sep}scripts"]

    # Hidden imports for libraries that PyInstaller may miss
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
    print(f"  ZIP contents: {APP_NAME}.exe + info/README.md + info/README_APP_Standalone.md")
    print(f"  No scripts/ folder needed — everything is embedded in the EXE.")
    print(f"  Upload {APP_NAME}.zip to the GitHub release.")


def main():
    print(f"Garmin Local Archive — Build Script (Target 3: Standalone, no Python required)")
    print("=" * 75)

    root        = Path(__file__).parent
    scripts_dir = root / "scripts"
    info_dir    = root / "info"

    check_dependencies(root)

    print("\n[2/4] Preparing layout ...")
    migrate_layout(root, scripts_dir, info_dir)

    print("\n  Checking scripts ...")
    entry_point = check_entry_point(scripts_dir)
    validate_scripts(scripts_dir)
    print(f"  ✓ Entry point:  garmin_app_standalone.py")
    for s in EMBEDDED_SCRIPTS:
        print(f"  ✓ Embed:        {s}")

    build_exe(root, scripts_dir, entry_point)

    exe = root / f"{APP_NAME}.exe"
    print(f"\n  ✓ Build successful: {exe}")

    build_zip(root)

    print(f"\n  Done. Distribute {APP_NAME}.zip — no Python installation needed on target.")


if __name__ == "__main__":
    main()
