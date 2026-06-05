#!/usr/bin/env python3
"""
tests/support.py
Garmin Local Archive — shared test runner utilities

Provides check(), section(), summary() as free functions.
Import: from support import check, section, summary

Compatible with:
  - standalone script execution (python tests/test_local.py from project root)
  - pytest (imported as module)
"""

import sys

# ── State ──────────────────────────────────────────────────────────────────────
_pass     = 0
_fail     = 0
_failures = []


# ── Public API ─────────────────────────────────────────────────────────────────

def check(name: str, condition: bool) -> None:
    """Record a single test result and print it immediately."""
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  ✓  {name}")
    else:
        _fail += 1
        _failures.append(name)
        print(f"  ✗  {name}")


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


def summary() -> None:
    """Print final results and exit with appropriate code."""
    total = _pass + _fail
    print(f"\n{'═' * 55}")
    print(f"  {total} checks — {_pass} passed, {_fail} failed")
    if _failures:
        print(f"\n  Failed:")
        for name in _failures:
            print(f"    ✗  {name}")
    print(f"{'═' * 55}\n")
    sys.exit(0 if _fail == 0 else 1)