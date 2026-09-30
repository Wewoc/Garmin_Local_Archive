#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
build_all_github.py
CI-only entry point (.github/workflows/build-release.yml, workflow_dispatch).

Runs build_all.main() completely unchanged — the local build pipeline
(tests, Target 2, Target 3, post-build validation) does not know or care
whether it is running locally or in CI — then, only on success, publishes
a GitHub Release carrying the four build.py/build_standalone.py output
files (Garmin_Local_Archive.zip[.sha256], Garmin_Local_Archive_Standalone
.zip[.sha256]).

build_all.main() raises SystemExit(1) on any test/build failure (see its
own sys.exit(1) calls); since that is never caught here, no Release is
created unless the entire local pipeline actually succeeded.

Sets GLA_BUILD_VENV_DIR before importing build_all, so build_venv.py's
ensure_build_venv() (compiler/build_venv.py) builds in a CI-owned venv
instead of build_manifest.BUILD_VENV_DIR (D:\\Garmin\\.venv_gla — the
local dev machines' hardcoded path, left untouched for local builds).

Never imported by build_all.py itself or any local build script — a
local `python build_all.py` run never touches this file or the GitHub
API.
"""

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("GLA_BUILD_VENV_DIR", r"D:\_gla_ci_venv")

# Windows' console/subprocess default encoding is cp1252, not UTF-8 — same
# class of problem build_all.py's own _Tee already works around for ITS
# output. Reconfiguring here covers every print() in this module (e.g. the
# ✓ below) that runs after build_all.main() has restored the real
# stdout/stderr streams.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

import build_all

_root = Path(__file__).parent.parent   # compiler/ → src/

_ASSET_FILES = [
    "Garmin_Local_Archive.zip",
    "Garmin_Local_Archive.zip.sha256",
    "Garmin_Local_Archive_Standalone.zip",
    "Garmin_Local_Archive_Standalone.zip.sha256",
]


def _read_app_version() -> str:
    sys.path.insert(0, str(_root))
    import version  # noqa: E402 — import-free module, safe this late
    return version.APP_VERSION


def _release_notes() -> str:
    """HEAD commit message body, unless GLA_RELEASE_NOTES_OVERRIDE is set
    (workflow_dispatch input — the 99%-case default is the commit
    message of the release commit; override covers anything that went
    wrong with that commit's message or a last-minute correction)."""
    override = os.environ.get("GLA_RELEASE_NOTES_OVERRIDE", "").strip()
    if override:
        return override
    result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=str(_root.parent), capture_output=True, text=True, check=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _api(method: str, url: str, **kwargs):
    token = os.environ["GITHUB_TOKEN"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **kwargs.pop("headers", {}),
    }
    resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    resp.raise_for_status()
    return resp


def _create_release(tag: str, notes: str, prerelease: bool) -> dict:
    repo = os.environ["GITHUB_REPOSITORY"]
    payload = {
        "tag_name": tag,
        "name": tag,
        "body": notes,
        "draft": False,
        "prerelease": prerelease,
        "make_latest": "false" if prerelease else "true",
    }
    return _api("POST", f"https://api.github.com/repos/{repo}/releases",
                json=payload).json()


def _upload_asset(upload_url: str, path: Path) -> None:
    base_url = upload_url.split("{", 1)[0]   # strip the templated {?name,label} part
    _api("POST", base_url, params={"name": path.name},
         data=path.read_bytes(),
         headers={"Content-Type": "application/octet-stream"})


def main() -> None:
    build_all.main()

    version_str = _read_app_version()
    tag = f"v{version_str}"
    notes = _release_notes()
    prerelease = os.environ.get("GLA_RELEASE_PRERELEASE", "false").strip().lower() == "true"

    print(f"\nCreating GitHub Release {tag} (prerelease={prerelease}) ...")
    release = _create_release(tag, notes, prerelease)

    for name in _ASSET_FILES:
        path = _root / name
        if not path.exists():
            print(f"  ✗ Expected build output missing: {path}")
            sys.exit(1)
        print(f"  Uploading {name} ...")
        _upload_asset(release["upload_url"], path)

    print(f"\n✓ Release published: {release['html_url']}")


if __name__ == "__main__":
    main()
