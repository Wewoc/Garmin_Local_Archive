# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
check_vulture.py — Dead Code Finder
Garmin Local Archive · report tool · no project imports

Runs Vulture twice against src/:
  Run A ("production")       — everything except tests/, compiler/,
                                support-tools/ (build-only / standalone
                                probe tooling, not shipped code)
  Run B ("production+tests") — Run A's scope plus tests/

Run B's scope is a superset of Run A's, so Run B can only ever find a
subset of what Run A finds (more references, never fewer). That means
Run A alone is the complete list of dead-code candidates — Run B is used
only to label each Run A finding, not as a second independent check:
  dead_everywhere — still unused even counting tests (Run B finds it too)
  test_only       — only a test references it; production never calls it

Both runs are filtered against vulture_whitelist.py's VULTURE_WHITELIST
dict AFTER parsing — not fed to Vulture as a scan path. Vulture's own
whitelist mechanism matches by name only, with no way to scope an entry
to one file; a (file, name) filter here avoids a generic attribute name
(e.g. "alignment") suppressing a genuinely dead one elsewhere just
because it shares a name with a confirmed false positive.

This tool never blocks a build or a test run by itself — it has no hook
into run_tests.ps1 or build_all.py. It is meant to be read by a human
(via run_vulture_check.bat) as the FINAL_DOKU_PROMPT precondition check,
and by generate_metrics.py, which reads vulture.json to record the last
known-clean state in docs/METRICS.md.

Exit code: 0 only if Run A found nothing (after whitelist) — i.e. both
runs are clean, since Run B can't find more than Run A. Non-zero
otherwise. This is a signal for the human running it, not a build gate.

Run via run_vulture_check.bat, or standalone:
    python tests/check_vulture.py [--target-version vX.Y.Z]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vulture_whitelist  # noqa: E402

SRC_DIR = Path(__file__).parent.parent
VERSION_FILE = SRC_DIR / "version.py"
OUTPUT_FILE = SRC_DIR / "vulture.json"

# Relative to SRC_DIR. Excluded from BOTH runs — not project source
# (compiler/ is build-only tooling, support-tools/ are standalone
# probe scripts, neither ships as part of the app).
EXCLUDED_ALWAYS = ["compiler", "support-tools"]

MIN_CONFIDENCE = 60

_REPORT_LINE_RE = re.compile(
    r"^(?P<file>.+):(?P<line>\d+): (?P<kind>unused \S+) '(?P<name>[^']+)' "
    r"\((?P<confidence>\d+)% confidence\)$"
)


# ─── Vulture invocation ──────────────────────────────────────────────────────


def _scan_paths(include_tests: bool) -> list[str]:
    excluded = set(EXCLUDED_ALWAYS)
    if not include_tests:
        excluded.add("tests")

    paths = [
        p.name for p in SRC_DIR.iterdir()
        if p.name not in excluded
    ]
    return paths


def run_vulture(include_tests: bool) -> list[dict] | None:
    """
    Runs `python -m vulture <scan paths>` from SRC_DIR, so reported paths
    are relative and identical between both runs (needed to match findings
    across Run A / Run B by file+line+name). Whitelist filtering happens
    afterward, in filter_whitelisted() — not passed to Vulture here.

    Returns parsed findings, or None if Vulture itself could not be run
    (not installed, etc.) — reported as a finding, never raised.
    """
    paths = _scan_paths(include_tests)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "vulture", *paths,
             "--min-confidence", str(MIN_CONFIDENCE)],
            cwd=str(SRC_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    findings = []
    for line in result.stdout.splitlines():
        m = _REPORT_LINE_RE.match(line.strip())
        if m:
            findings.append({
                "file":       m.group("file"),
                "line":       int(m.group("line")),
                "kind":       m.group("kind"),
                "name":       m.group("name"),
                "confidence": int(m.group("confidence")),
            })
    return findings


# ─── Whitelist filtering ─────────────────────────────────────────────────────


def filter_whitelisted(findings: list[dict]) -> tuple[list[dict], int]:
    """
    Drops findings whose (file, name) pair is a confirmed false positive in
    vulture_whitelist.VULTURE_WHITELIST. Scoped by file, not by name alone —
    see check_vulture.py's module docstring for why.

    Returns (remaining findings, count filtered out).
    """
    remaining = [
        f for f in findings
        if (f["file"], f["name"]) not in vulture_whitelist.VULTURE_WHITELIST
    ]
    return remaining, len(findings) - len(remaining)


# ─── Delta labeling ──────────────────────────────────────────────────────────


def label_findings(findings_a: list[dict], findings_b: list[dict]) -> list[dict]:
    keys_b = {(f["file"], f["line"], f["name"]) for f in findings_b}
    labeled = []
    for f in findings_a:
        key = (f["file"], f["line"], f["name"])
        status = "dead_everywhere" if key in keys_b else "test_only"
        labeled.append({**f, "status": status})
    return labeled


# ─── version.py lookup ───────────────────────────────────────────────────────


def read_current_version() -> str | None:
    if not VERSION_FILE.exists():
        return None
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'''APP_VERSION\s*=\s*['"]([^'"]+)['"]''', text)
    return m.group(1) if m else None


# ─── vulture.json ────────────────────────────────────────────────────────────


def write_result_json(findings: list[dict], target_version: str | None, whitelisted: int) -> None:
    content = {
        "scanned_at":         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "current_version":    read_current_version(),
        "target_version":     target_version,
        "whitelisted_count":  whitelisted,
        "total_findings":     len(findings),
        "findings":           findings,
    }
    OUTPUT_FILE.write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ─── Report ──────────────────────────────────────────────────────────────────


def build_report(findings: list[dict]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("VULTURE DEAD CODE CHECK")
    lines.append("=" * 70)
    lines.append("")

    if not findings:
        lines.append("OK - no unused code found (production + test-only both clean).")
        lines.append("")
        return "\n".join(lines)

    dead_everywhere = [f for f in findings if f["status"] == "dead_everywhere"]
    test_only = [f for f in findings if f["status"] == "test_only"]

    for label, group in [
        ("DEAD EVERYWHERE - unused in production AND in tests", dead_everywhere),
        ("TEST-ONLY - production never calls this, a test still does", test_only),
    ]:
        if not group:
            continue
        lines.append("-" * 70)
        lines.append(label)
        lines.append("-" * 70)
        for f in group:
            lines.append(
                f"  {f['file']}:{f['line']}: {f['kind']} '{f['name']}' "
                f"({f['confidence']}% confidence)"
            )
        lines.append("")

    lines.append("-" * 70)
    lines.append(
        f"Summary: {len(dead_everywhere)} dead everywhere, "
        f"{len(test_only)} test-only - {len(findings)} total findings."
    )
    lines.append(
        "Confirmed false positive? Add it to vulture_whitelist.py, not here."
    )
    lines.append("")

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-version", default=None)
    args = parser.parse_args()

    print("check_vulture - Garmin Local Archive dead code finder")
    print()

    findings_a = run_vulture(include_tests=False)
    if findings_a is None:
        print("Vulture could not be run (not installed?).")
        print("  Install with: pip install vulture")
        return 1

    findings_b = run_vulture(include_tests=True)
    if findings_b is None:
        print("Vulture could not be run (not installed?).")
        print("  Install with: pip install vulture")
        return 1

    findings_a, whitelisted_a = filter_whitelisted(findings_a)
    findings_b, _ = filter_whitelisted(findings_b)

    labeled = label_findings(findings_a, findings_b)
    print(build_report(labeled))
    if whitelisted_a:
        print(f"({whitelisted_a} finding(s) suppressed via vulture_whitelist.py)")
        print()

    write_result_json(labeled, args.target_version, whitelisted_a)
    print(f"Result written to {OUTPUT_FILE}")

    return 1 if labeled else 0


if __name__ == "__main__":
    sys.exit(main())
