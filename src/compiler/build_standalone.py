#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import build_manifest as manifest

EMBEDDED_SCRIPTS  = manifest.EMBEDDED_SCRIPTS
INFO_INCLUDE      = manifest.INFO_INCLUDE_T3

SCRIPT_SIGNATURES = {
    **manifest.SCRIPT_SIGNATURES_BASE,
    "garmin_app_standalone.py": ["class GarminApp"],
    "daily_update.py":          ["def main"],
    "mcp_server.py":            ["def main"],
}


def ensure_build_venv(root: Path) -> Path:
    """Creates (if missing) or reuses the shared, isolated build venv at
    manifest.BUILD_VENV_DIR, installs requirements.txt + PyInstaller into
    it, and returns its python.exe. Replaces the old check_dependencies()
    (garmin_collector-3_experiment, Baustein 27) — that function checked
    RUNTIME_DEPS (a second, narrower, drift-prone copy of the dependency
    list — already missing anthropic/openai/curl_cffi/ua_generator/lxml)
    against whatever Python happened to be sys.executable. On this machine
    that same Python also has an unrelated project's torch/pandas/scipy
    installed, which PyInstaller swept into the T3 ZIP (>8 GB) the moment
    HIDDEN_IMPORTS_T3_EXTRA required openai — see PROTOKOLL_experiment.md,
    Baustein 26. Building against a venv containing ONLY requirements.txt's
    packages (the actually-maintained, complete dependency list) makes
    that structurally impossible, regardless of what else gets
    pip-installed globally on this machine later. venv creation itself
    still uses sys.executable (any Python can create a venv — that step
    never touches site-packages). Same venv/function as build.py's own
    ensure_build_venv() — both build scripts share manifest.BUILD_VENV_DIR,
    so T2 and T3 build from the identical isolated environment."""
    print("\n[1/3] Checking build venv ...")
    venv_dir = Path(manifest.BUILD_VENV_DIR)
    venv_python = venv_dir / "Scripts" / "python.exe"

    if not venv_python.exists():
        print(f"  Not found at {venv_dir} — creating ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
        print("  ✓ venv created")
    else:
        print(f"  ✓ venv already exists — reusing: {venv_dir}")

    req_file = root.parent / "requirements.txt"
    print(f"  Installing/verifying {req_file} + PyInstaller in venv ...")
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q",
                            "-r", str(req_file)])
    subprocess.check_call([str(venv_python), "-m", "pip", "install", "-q",
                            "pyinstaller"])
    print("  ✓ venv ready")
    return venv_python


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


def build_exe(root: Path, name: str, entry_point: Path, venv_python: Path,
              windowed: bool = True, onedir: bool = False):
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
        str(venv_python), "-m", "PyInstaller",
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
        mcp_server.exe
        updater_helper.ps1
        _internal/
            ...
        info/
            QUICKSTART.txt
            USER_GUIDE.txt
            README.md
            README_APP.md
            daily_update_task.xml

    Also writes Garmin_Local_Archive_Standalone.zip.sha256 next to the
    ZIP (v1.7.2.4) — updater.prepare_update() refuses to auto-apply an
    update whose release doesn't publish this file (fail closed,
    Baustein 6/12). Upload BOTH files to the GitHub release, not just
    the ZIP.
    """
    zip_path      = root / "Garmin_Local_Archive_Standalone.zip"
    checksum_path = root / "Garmin_Local_Archive_Standalone.zip.sha256"
    t31_dir   = root / "Garmin_Local_Archive_Standalone"   # --onedir output folder
    du_exe    = root / "daily_update.exe"
    mcp_exe   = root / "mcp_server.exe"
    helper_ps1 = root / "updater_helper.ps1"
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
    if not helper_ps1.exists():
        print(f"  ✗ updater_helper.ps1 not found: {helper_ps1}")
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

        # v1.7.2.4 — self-update helper, flat in ZIP root next to the EXEs.
        # updater.prepare_update()/garmin_app_base.py::_start_update()/
        # daily_update.py::_apply_update_unattended() all resolve it as
        # exe_dir / "updater_helper.ps1" — same folder as the EXEs above.
        zf.write(helper_ps1, "updater_helper.ps1")

        # Docs — flat info/ folder in ZIP root
        if info_dir.exists():
            for f in sorted(info_dir.iterdir()):
                if f.name in INFO_INCLUDE:
                    zf.write(f, f"info/{f.name}")

    # v1.7.2.4 — SHA256 of the finished ZIP, written alongside it. Plain
    # hex digest, no filename prefix — matches what updater.prepare_update()
    # already parses (it splits on whitespace and takes the first token,
    # so either form would work, but there's no need for the second one).
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path.write_text(digest, encoding="ascii")

    print(f"  -> {zip_path}")
    print(f"  -> {checksum_path}")
    print("  ZIP: flat layout — EXE + _internal/ + daily_update.exe + "
          "mcp_server.exe + updater_helper.ps1 + info/")
    print("  Upload BOTH Garmin_Local_Archive_Standalone.zip AND "
          "Garmin_Local_Archive_Standalone.zip.sha256 to the GitHub release.")


def main():
    print("Garmin Local Archive — Build Script (Target 3: Standalone, no Python required)")
    print("=" * 80)

    root = Path(__file__).parent.parent   # compiler/ → src/

    venv_python = ensure_build_venv(root)
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
              venv_python=venv_python,
              windowed=True,
              onedir=True)
    # --- T3.2: Headless — --onefile (Task Scheduler, startup time irrelevant) ---
    print("\n  --- T3.2: daily_update.exe (--onefile) ---")
    build_exe(root,
              name="daily_update",
              entry_point=root / "scheduler" / "daily_update.py",
              venv_python=venv_python,
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
              venv_python=venv_python,
              windowed=False,
              onedir=False)

    build_combined_zip(root)

    print("\n  Done. Distribute Garmin_Local_Archive_Standalone.zip — no Python installation needed on target.")


if __name__ == "__main__":
    main()
