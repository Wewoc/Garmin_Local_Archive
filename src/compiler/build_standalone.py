#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    "mcp_server.py":            ["def main"],
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
    _ep_paths = {
        "garmin_app_standalone.py": root / "garmin_app_standalone.py",
        "daily_update.py":          root / "scheduler" / "daily_update.py",
        "mcp_server.py":            root / "clients" / "mcp_server.py",
    }
    for ep, sig in [
        ("garmin_app_standalone.py", "class GarminApp"),
        ("daily_update.py",          "def main"),
        ("mcp_server.py",            "def main"),
    ]:
        entry = _ep_paths[ep]
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
    for subdir, name in manifest.REQUIRED_DATA_FILES:
        path = root / subdir / name
        if not path.exists():
            errors.append(f"  ✗ Missing data file: {subdir}/{name}")

    if errors:
        print("  Build aborted — validation failed:")
        for e in errors:
            print(e)
        sys.exit(1)

    print("  ✓ All scripts and data files present and valid.")
    print("  ✓ Entry points: garmin_app_standalone.py, daily_update.py")
    for s in EMBEDDED_SCRIPTS:
        print(f"  ✓ Embed: {s}")


def embed_dest(subfolder) -> str:
    """Compute the --add-data destination folder under scripts/ for a given
    subfolder (str or Path). '.' or '' means scripts/ root itself.
    Single source of truth for both EMBEDDED_SCRIPTS and REQUIRED_DATA_FILES
    destination paths — imported directly by test_build_output.py §8 (P7-02,
    v1.6.5.5) instead of being reconstructed there."""
    subfolder = str(subfolder)
    if subfolder in (".", ""):
        return "scripts"
    return f"scripts/{subfolder}"


def build_exe(root: Path, name: str, entry_point: Path, windowed: bool = True,
              onedir: bool = False):
    print(f"\n  Building {name}.exe ...")
    print(f"  Entry point: {entry_point}")
    print(f"  Embedding {len(EMBEDDED_SCRIPTS)} scripts as data ...")
    print(f"  Mode: {'--onedir' if onedir else '--onefile'}")

    sep = ";" if sys.platform == "win32" else ":"

    add_data_args = []
    for script in EMBEDDED_SCRIPTS:
        src = root / script
        subfolder = Path(script).parent
        dest = embed_dest(subfolder)
        add_data_args += ["--add-data", f"{src}{sep}{dest}"]

    # build_manifest.py — embedded separately at scripts root (A1, v1.6.5.7).
    # Not part of EMBEDDED_SCRIPTS/SHARED_SCRIPTS: it is compiler/-only,
    # pure data (no imports, no side effects — see its own docstring), and
    # deliberately lands at "scripts" root — same destination as version.py/
    # garmin_app_base.py — not "scripts/compiler", so garmin_app_standalone.py's
    # Netz-1 self-test can load it exactly like the other root-level modules
    # instead of needing a second sys.path registration for compiler/.
    _manifest_src = Path(__file__).parent / "build_manifest.py"
    add_data_args += ["--add-data", f"{_manifest_src}{sep}scripts"]

    # Embed required data files (generic — was hardcoded to garmin_dataformat.json only)
    # NOTE: loop variable deliberately named data_name, not name — this function's
    # own `name` parameter (the PyInstaller --name / EXE filename) was being silently
    # overwritten by this loop once REQUIRED_DATA_FILES grew to 2+ entries, causing
    # both T3.1 and T3.2 to be built as "plotly.min.js.exe" instead of their real
    # names. Found via a real build_all.py run (v1.6.0.4.4).
    for subdir, data_name in manifest.REQUIRED_DATA_FILES:
        data_src = root / subdir / data_name
        if data_src.exists():
            add_data_args += ["--add-data", f"{data_src}{sep}{embed_dest(subdir)}"]
        else:
            print(f"  ✗ {data_name} not found in {subdir}/ — aborting build")
            sys.exit(1)


    hidden = manifest.HIDDEN_IMPORTS_COMMON + manifest.HIDDEN_IMPORTS_T3_EXTRA
    hidden_args = []
    for h in hidden:
        hidden_args += ["--hidden-import", h]

    packaging_flag = "--onedir" if onedir else "--onefile"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        packaging_flag,
        "--name", name,
        "--distpath", str(root),
        "--workpath", str(root / f"build_{name}_work"),
        "--specpath", str(Path(__file__).parent),   # .spec bleibt in compiler/
        *add_data_args,
        *hidden_args,
        str(entry_point),
    ]
    if windowed:
        cmd.append("--windowed")

    result = subprocess.run(cmd, cwd=str(root))
    if result.returncode != 0:
        print("\n  ✗ Build failed — check output above.")
        sys.exit(1)

    print(f"  ✓ {name}.exe built successfully.")


def build_combined_zip(root: Path):
    """Packs T3.1 (--onedir folder) + T3.2 (--onefile EXE) into a single release ZIP.

    ZIP layout (flat — all contents unpacked directly into the target folder):
        Garmin_Local_Archive_Standalone.exe
        daily_update.exe
        _internal/
            ...
        info/
            QUICKSTART.txt
            USER_GUIDE.txt
            README.md
            README_APP.md
            daily_update_task.xml
    """
    zip_path  = root / "Garmin_Local_Archive_Standalone.zip"
    t31_dir   = root / "Garmin_Local_Archive_Standalone"   # --onedir output folder
    du_exe    = root / "daily_update.exe"
    mcp_exe   = root / "mcp_server.exe"
    info_dir  = root / "info"

    print("\n  Creating Garmin_Local_Archive_Standalone.zip (T3.1 + T3.2 + T3.3) ...")

    if not t31_dir.exists():
        print(f"  ✗ T3.1 folder not found: {t31_dir}")
        sys.exit(1)
    if not du_exe.exists():
        print(f"  ✗ T3.2 EXE not found: {du_exe}")
        sys.exit(1)
    if not mcp_exe.exists():
        print(f"  ✗ T3.3 EXE not found: {mcp_exe}")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # T3.1 — pack contents of --onedir folder flat into ZIP root
        for f in sorted(t31_dir.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(t31_dir)   # → flat: EXE + _internal/...
                zf.write(f, arcname)

        # T3.2 — flat single EXE in ZIP root
        zf.write(du_exe, "daily_update.exe")

        # T3.3 — flat single EXE in ZIP root
        zf.write(mcp_exe, "mcp_server.exe")

        # Docs — flat info/ folder in ZIP root
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    print(f"  -> {zip_path}")
    print("  ZIP: flat layout — EXE + _internal/ + daily_update.exe + mcp_server.exe + info/")
    print("  Upload Garmin_Local_Archive_Standalone.zip to GitHub release.")


def main():
    print("Garmin Local Archive — Build Script (Target 3: Standalone, no Python required)")
    print("=" * 80)

    root = Path(__file__).parent.parent   # compiler/ → src/

    check_dependencies(root)
    validate_scripts(root)

    # info/ für ZIP aus docs/ befüllen
    import shutil
    info_dir = root / "info"
    info_dir.mkdir(exist_ok=True)
    for name in INFO_INCLUDE:
        # README.md → Repo-Root, Docs (QUICKSTART/USER_GUIDE/README_APP) → src/docs/,
        # daily_update_task.xml → src/scheduler/
        if (root.parent / name).exists():
            src = root.parent / name
        elif (root / "docs" / name).exists():
            src = root / "docs" / name
        else:
            src = root / "scheduler" / name
        if src.exists():
            shutil.copy2(src, info_dir / name)

    print("\n[3/3] Building ...")

    # --- T3.1: GUI — --onedir (permanent unpack, fast startup) ---
    print("\n  --- T3.1: Garmin_Local_Archive_Standalone (--onedir) ---")
    build_exe(root,
              name="Garmin_Local_Archive_Standalone",
              entry_point=root / "garmin_app_standalone.py",
              windowed=True,
              onedir=True)
    # --- T3.2: Headless — --onefile (Task Scheduler, startup time irrelevant) ---
    print("\n  --- T3.2: daily_update.exe (--onefile) ---")
    build_exe(root,
              name="daily_update",
              entry_point=root / "scheduler" / "daily_update.py",
              windowed=False,
              onedir=False)
    # --- T3.3: MCP Server — --onefile (standalone process, no Python
    # required on target — mcp_server.py must run fully independently of
    # GLA's GUI, e.g. as a data source for an external MCP client).
    # windowed=False left UNCHANGED (v1.7.0.1) — the original reason
    # (mcp.run(transport="stdio") needing a real sys.stdin/sys.stdout
    # with a .buffer attribute) no longer applies now that the server
    # uses streamable-http (a TCP socket, not stdio), so windowed=True
    # is no longer blocked by that specific crash. It was deliberately
    # NOT flipped in this Bauauftrag anyway: --windowed can leave
    # sys.stderr invalid/None under Windows, and logging.basicConfig()
    # in clients/mcp_server.py writes to sys.stderr before any log
    # handler exists — an untested risk in this environment (no Windows
    # build available here). Flip to windowed=True only after Timo
    # confirms on a real Windows T3.3 build that logging still starts
    # cleanly with no console. ---
    print("\n  --- T3.3: mcp_server.exe (--onefile) ---")
    build_exe(root,
              name="mcp_server",
              entry_point=root / "clients" / "mcp_server.py",
              windowed=False,
              onedir=False)

    build_combined_zip(root)

    print("\n  Done. Distribute Garmin_Local_Archive_Standalone.zip — no Python installation needed on target.")


if __name__ == "__main__":
    main()
