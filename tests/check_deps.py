"""
check_deps.py — Dependency & Ecosystem Monitor
Garmin Local Archive · T1 only · standalone (no project imports)

Checks PyPI versions of direct dependencies and monitors GitHub repos
for recent releases/commits that may signal Garmin API or auth changes.

Run via run_T1.bat in the project root — do not run directly.
Cache file is written to the project root (one level up from tests/).

Config: edit PYPI_PACKAGES and GITHUB_REPOS below to add/remove targets.
"""

import sys
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.metadata

# ─── Configuration ────────────────────────────────────────────────────────────

# PyPI packages to check (importlib name → PyPI package name)
PYPI_PACKAGES = {
    "garminconnect": "garminconnect",
    "garth":         "garth",
}

# GitHub repos to monitor
# type "dependency" = directly used by this project
# type "sentinel"   = ecosystem early warning, not a direct dependency
GITHUB_REPOS = [
    {
        "repo":  "cyberjunky/python-garminconnect",
        "type":  "dependency",
        "label": "garminconnect library",
    },
    {
        "repo":  "matin/garth",
        "type":  "dependency",
        "label": "garth (auth layer)",
    },
    {
        "repo":  "nrvim/garmin-givemydata",
        "type":  "sentinel",
        "label": "garmin-givemydata (ecosystem sentinel)",
    },
]

# How many days back to consider "recent"
LOOKBACK_DAYS = 30

# Cache lives in project root (parent of tests/)
CACHE_FILE      = Path(__file__).parent.parent / ".check_deps_cache.json"
CACHE_TTL_HOURS = 12

GITHUB_API = "https://api.github.com"
PYPI_API   = "https://pypi.org/pypi"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 8) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "check_deps/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(data.get("_ts", "2000-01-01"))
            if datetime.now(timezone.utc) - ts < timedelta(hours=CACHE_TTL_HOURS):
                return data
    except Exception:
        pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        data["_ts"] = datetime.now(timezone.utc).isoformat()
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _days_ago(iso_str: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None

# ─── Checks ───────────────────────────────────────────────────────────────────

def check_pypi(cache: dict) -> list[dict]:
    findings = []
    for pkg_name, pypi_name in PYPI_PACKAGES.items():
        installed = _installed_version(pkg_name)
        cache_key = f"pypi_{pypi_name}"

        latest = cache.get(cache_key)
        if not latest:
            data = _get(f"{PYPI_API}/{pypi_name}/json")
            latest = data["info"]["version"] if data else None
            if latest:
                cache[cache_key] = latest

        if installed is None:
            findings.append({
                "level":   "info",
                "source":  "pypi",
                "package": pkg_name,
                "msg":     f"{pkg_name}: not installed (skipping version check)",
            })
        elif latest and installed != latest:
            findings.append({
                "level":     "warn",
                "source":    "pypi",
                "package":   pkg_name,
                "installed": installed,
                "latest":    latest,
                "msg":       f"{pkg_name}: installed {installed} → latest {latest}",
            })
    return findings


def check_github(cache: dict) -> list[dict]:
    findings = []

    for entry in GITHUB_REPOS:
        repo  = entry["repo"]
        label = entry["label"]
        rtype = entry["type"]

        # ── Latest release ────────────────────────────────────────────────────
        cache_key = f"gh_release_{repo}"
        release = cache.get(cache_key)
        if not release:
            raw = _get(f"{GITHUB_API}/repos/{repo}/releases/latest")
            if raw and isinstance(raw, dict) and "tag_name" in raw:
                release = {
                    "tag":  raw.get("tag_name", "?"),
                    "date": raw.get("published_at", ""),
                    "url":  raw.get("html_url", ""),
                    "body": (raw.get("body") or "")[:300],
                }
                cache[cache_key] = release

        if release:
            days = _days_ago(release.get("date", ""))
            if days is not None and days <= LOOKBACK_DAYS:
                tag     = release.get("tag", "?")
                url     = release.get("url", "")
                body    = release.get("body", "").strip()
                snippet = (body[:120] + "…") if len(body) > 120 else body
                findings.append({
                    "level":  "warn",
                    "source": "github_release",
                    "repo":   repo,
                    "type":   rtype,
                    "label":  label,
                    "tag":    tag,
                    "days":   round(days, 1),
                    "url":    url,
                    "notes":  snippet,
                    "msg": (
                        f"[{rtype.upper()}] {label}\n"
                        f"  Release {tag} — {round(days):.0f}d ago\n"
                        f"  {url}"
                        + (f"\n  Notes: {snippet}" if snippet else "")
                    ),
                })

        # ── Recent commit (only if no release finding for this repo) ──────────
        already_reported = any(
            f["source"] == "github_release" and f["repo"] == repo
            for f in findings
        )
        if already_reported:
            continue

        cache_key_c = f"gh_commit_{repo}"
        commit_info = cache.get(cache_key_c)
        if not commit_info:
            commits = _get(f"{GITHUB_API}/repos/{repo}/commits?per_page=1")
            if commits and isinstance(commits, list) and commits:
                c = commits[0]
                commit_info = {
                    "sha":     c.get("sha", "")[:7],
                    "date":    c.get("commit", {}).get("committer", {}).get("date", ""),
                    "message": (c.get("commit", {}).get("message") or "")[:150],
                    "url":     c.get("html_url", ""),
                }
                cache[cache_key_c] = commit_info

        if commit_info:
            days = _days_ago(commit_info.get("date", ""))
            if days is not None and days <= LOOKBACK_DAYS:
                msg = commit_info.get("message", "").split("\n")[0]
                sha = commit_info.get("sha", "?")
                url = commit_info.get("url", "")
                findings.append({
                    "level":  "info",
                    "source": "github_commit",
                    "repo":   repo,
                    "type":   rtype,
                    "label":  label,
                    "days":   round(days, 1),
                    "msg": (
                        f"[{rtype.upper()}] {label}\n"
                        f"  Recent commit ({sha}, {round(days):.0f}d ago): {msg}\n"
                        f"  {url}"
                    ),
                })

    return findings

# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_analysis_prompt(findings: list[dict]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("DEPENDENCY / ECOSYSTEM CHANGE DETECTED")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Changes detected in the last {LOOKBACK_DAYS} days:")
    lines.append("")

    for f in findings:
        lines.append(f"  • {f['msg']}")
        lines.append("")

    lines.append("-" * 70)
    lines.append("WHAT THIS MAY MEAN FOR GARMIN LOCAL ARCHIVE")
    lines.append("-" * 70)
    lines.append("")

    hints      = []
    seen_hints = set()

    for f in findings:
        src   = f.get("source", "")
        repo  = f.get("repo", "")
        pkg   = f.get("package", "")
        notes = f.get("notes", "").lower()

        candidates = []

        if src == "pypi" and pkg == "garminconnect":
            candidates.append(
                "→ garminconnect update: review garmin_api.py for breaking "
                "changes (login flow, method signatures, return values)."
            )
        if src == "pypi" and pkg == "garth":
            candidates.append(
                "→ garth update: auth layer may have changed. "
                "garmin_api.py and garmin_security.py most likely affected."
            )
        if any(kw in notes for kw in ("auth", "login", "sso", "token", "oauth")):
            candidates.append(
                f"→ Release notes mention auth/login/SSO/token changes ({repo}). "
                "High risk: garmin_api.py."
            )
        if any(kw in notes for kw in ("cloudflare", "bot", "detection", "curl_cffi")):
            candidates.append(
                f"→ Cloudflare / bot detection mentioned ({repo}). "
                "May require curl_cffi or browser-based auth workaround."
            )
        if f.get("type") == "sentinel":
            candidates.append(
                f"→ Sentinel repo active ({repo}): Garmin-side changes may be "
                "in progress. Monitor before next sync."
            )

        for h in candidates:
            if h not in seen_hints:
                hints.append(h)
                seen_hints.add(h)

    for h in hints:
        lines.append(f"  {h}")
        lines.append("")

    lines.append("-" * 70)
    lines.append("RECOMMENDED ACTIONS")
    lines.append("-" * 70)
    lines.append("")
    lines.append("  1. Review the links above (release notes / commit messages)")
    lines.append("  2. Check open Issues in affected repos for user reports")
    lines.append("  3. If auth-related: run Connection Test in the app before full sync")
    lines.append("  4. Consider: pip install --upgrade garminconnect")
    lines.append("")
    lines.append("  Paste this output into Claude / Gemini / ChatGPT:")
    lines.append('  "Does this affect Garmin Local Archive? Which modules?'
                 ' What should I check?"')
    lines.append("")

    return "\n".join(lines)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    print("check_deps — Garmin Local Archive dependency monitor")
    print(f"Lookback: {LOOKBACK_DAYS} days · Cache TTL: {CACHE_TTL_HOURS}h")
    print()

    cache = _load_cache()

    print("Checking PyPI versions...", end=" ", flush=True)
    pypi_findings = check_pypi(cache)
    print("done")

    print("Checking GitHub repos...",  end=" ", flush=True)
    gh_findings = check_github(cache)
    print("done")

    _save_cache(cache)

    all_findings  = pypi_findings + gh_findings
    warn_findings = [f for f in all_findings if f["level"] == "warn"]
    info_findings = [f for f in all_findings if f["level"] == "info"]

    # ── Silent pass ───────────────────────────────────────────────────────────
    if not warn_findings:
        if info_findings:
            print()
            for f in info_findings:
                print(f"  i  {f['msg']}")
        print()
        print("✓ No significant changes detected. Starting app...")
        print()
        return 0

    # ── Block + prompt ────────────────────────────────────────────────────────
    print()
    print(build_analysis_prompt(warn_findings))

    while True:
        try:
            answer = input("Start anyway? [j/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ("j", "ja", "y", "yes"):
            print()
            print("Continuing — watch the connection log carefully.")
            print()
            return 0
        elif answer in ("n", "no", ""):
            print()
            print("Aborted.")
            return 1
        else:
            print("  Please enter 'j' to continue or 'N' to abort.")


if __name__ == "__main__":
    sys.exit(main())
