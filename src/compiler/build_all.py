#!/usr/bin/env python3
"""
build_all.py
Runs both build targets sequentially:
  Target 2 — Garmin_Local_Archive.exe          (Python required)
  Target 3 — Garmin_Local_Archive_Standalone.exe (no Python required)

If Target 2 fails, Target 3 is not started.
Note: Standalone build embeds all dependencies and takes significantly longer.

Plotly pre-build check (v1.6.0.4.4+): ensures layouts/plotly.min.js exists and
matches the pinned PLOTLY_SHA256 (dash_layout_html.PLOTLY_VERSION) before any
test or build step runs. This is the only place in the project that ever
downloads Plotly from the CDN — dash_layout_html.get_plotly_script() is a
pure read at render time (T1/T2/T3 alike), never a network call.
"""

import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

import build
import build_standalone


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ensure_plotly_bundle(root: Path) -> None:
    """
    Ensures layouts/plotly.min.js exists and matches the pinned hash for the
    currently configured PLOTLY_VERSION. Re-downloads from PLOTLY_CDN only if
    missing or mismatched. Aborts the build on download failure or hash
    mismatch after download — never silently proceeds with an unverified file.
    """
    sys.path.insert(0, str(root / "layouts"))
    import dash_layout_html as layout_html  # noqa: E402

    local        = root / "layouts" / layout_html.get_plotly_local_filename()
    expected_sha = layout_html.get_plotly_sha256()

    if local.exists() and _sha256_of(local) == expected_sha:
        print(f"  ✓ Plotly {layout_html.get_plotly_version()} present and verified.")
        return

    if local.exists():
        print(f"  ⚠ {local} exists but hash mismatch — re-fetching pinned version.")
    else:
        print(f"  Plotly {layout_html.get_plotly_version()} not found locally — fetching ...")

    try:
        req = urllib.request.Request(
            layout_html.get_plotly_cdn(),
            headers={"User-Agent": "garmin-local-archive-build/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
    except Exception as exc:
        print(f"  ✗ Failed to download Plotly: {exc}")
        print("  Build aborted — see PLOTLY_CDN in dash_layout_html.py.")
        sys.exit(1)

    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != expected_sha:
        print("  ✗ Downloaded Plotly hash mismatch.")
        print(f"    expected: {expected_sha}")
        print(f"    actual:   {actual_sha}")
        print("  Build aborted — CDN content does not match the pinned hash.")
        print("  If this is an intentional version bump, update PLOTLY_VERSION")
        print("  and PLOTLY_SHA256 in dash_layout_html.py together.")
        sys.exit(1)

    local.write_bytes(data)
    print(f"  ✓ Plotly {layout_html.get_plotly_version()} fetched and verified.")


if __name__ == "__main__":
    _root = Path(__file__).parent.parent   # compiler/ → Root/

    print("=" * 55)
    print("  Pre-build: verifying Plotly bundle ...")
    print("=" * 55)
    ensure_plotly_bundle(_root)

    print("\n" + "=" * 55)
    print("  Pre-build: running test suite ...")
    print("=" * 55)

    test_path = _root / "tests" / "test_local.py"
    result = subprocess.run([sys.executable, str(test_path)])
    if result.returncode != 0:
        print("\n  ✗ Tests failed — build aborted.")
        sys.exit(1)

    test_context_path = _root / "tests" / "test_local_context.py"
    result_context = subprocess.run([sys.executable, str(test_context_path)])
    if result_context.returncode != 0:
        print("\n  ✗ Context tests failed — build aborted.")
        sys.exit(1)

    test_dashboard_path = _root / "tests" / "test_dashboard.py"
    result_dashboard = subprocess.run([sys.executable, str(test_dashboard_path)])
    if result_dashboard.returncode != 0:
        print("\n  ✗ Dashboard tests failed — build aborted.")
        sys.exit(1)

    print("\n  ✓ All tests passed — starting build.\n")

    print("=" * 55)
    print("  Target 2: Garmin_Local_Archive.exe ...")
    print("=" * 55)
    build.main()

    print("\n" + "=" * 55)
    print("  Target 3: Standalone + Headless EXEs ...")
    print("=" * 55)
    build_standalone.main()

    print("\n" + "=" * 55)
    print("  Post-build: running output validation ...")
    print("=" * 55)

    test_build_path = _root / "tests" / "test_build_output.py"
    result_build = subprocess.run([sys.executable, str(test_build_path)])
    if result_build.returncode != 0:
        print("\n  ✗ Build output validation failed — check output above.")
        sys.exit(1)

    print("\n  ✓ Build output validated successfully.")

    print("\n" + "=" * 55)
    print("  Post-build: running app logic tests ...")
    print("=" * 55)

    test_app_path = _root / "tests" / "test_app_logic.py"
    result_app = subprocess.run([sys.executable, str(test_app_path)])
    if result_app.returncode != 0:
        print("\n  ✗ App logic tests failed — check output above.")
        sys.exit(1)

    print("\n  ✓ App logic tests passed.")

    print("\n" + "=" * 55)
    print("  Post-build: CVE whitelist check (informational only) ...")
    print("=" * 55)

    test_cve_path = _root / "tests" / "check_cve_whitelist.py"
    subprocess.run([sys.executable, str(test_cve_path)])
    # No returncode check — this is a report-only step, never a build gate.
    # See NOTES_v1_6_0_4_4.md A1 for the rationale (180° scope change away
    # from any abort/severity-threshold mechanism).
