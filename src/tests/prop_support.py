#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/prop_support.py — property tests with generated inputs (v1.7.6.11)

Shared by the test_prop_*.py and test_fuzz_*.py suites. A property is a function decorated
with hypothesis' @given; `prop(name)` runs it at once and records ONE check() for it, in the
script style of support.py (a failing property prints the falsifying example, it does not
stop the suite).

Fixed on purpose, so that the suite is the same on every machine and every run:
  - derandomize=True    the examples are derived from the test, not from a random seed
  - database=None       no database of failing examples (and its caches go to a temp folder: nothing in the source tree)
  - deadline=None       the time of one example is not a result
  - max_examples=50     the whole property suites add a few seconds, not minutes

To look further than the fixed examples (not part of the suite, only on request):
    GLA_PROP_EXAMPLES=2000 GLA_PROP_RANDOM=1 python tests/test_prop_bulk_store.py
(random seed instead of the derived one; a falsifying example found that way becomes a
fixed regression test in the suite of its module).

Usage:
    from prop_support import prop, st, given, DATES, HASHES
    @prop("a day is replaced only by a fuller one")
    @given(st.sets(HASHES), st.sets(HASHES))
    def _(old, new):
        assert ...
"""

import atexit
import datetime
import hashlib
import os
import shutil
import tempfile

from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: F401 - re-exported
from hypothesis.configuration import set_hypothesis_home_dir, storage_directory
from support import check

# database=None only switches off the database of failing examples; hypothesis still keeps caches (the Unicode tables, the
# constants it harvests from the code under test, temporary files) in a ".hypothesis" folder of the working directory.
# They go to a temp folder that is removed at exit, so a test run leaves nothing in the source tree.
_HOME = tempfile.mkdtemp(prefix="gla_hypothesis_")
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)
set_hypothesis_home_dir(_HOME)

EXAMPLES = int(os.environ.get("GLA_PROP_EXAMPLES", "50"))
RANDOM = os.environ.get("GLA_PROP_RANDOM") == "1"

PROFILE = dict(
    max_examples=EXAMPLES,
    derandomize=not RANDOM,
    database=None,
    deadline=None,
    print_blob=False,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much],
)


def prop(name, examples=None):
    """Runs the decorated @given function once (hypothesis does the repeating) and records one check().

    examples : override of the number of examples for an expensive property (disk, ZIP).
    """
    def decorate(fn):
        opts = dict(PROFILE)
        if examples is not None:
            opts["max_examples"] = max(examples, EXAMPLES) if RANDOM else examples
        try:
            settings(**opts)(fn)()
        except Exception as e:                       # noqa: BLE001 - the failure is the result
            check(name, False)
            print(f"      {type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}")
            for note in getattr(e, "__notes__", [])[:6]:
                print(f"      {note[:300]}")
        else:
            check(name, True)
        return fn
    return decorate


def storage_is_outside(folder) -> bool:
    """True if hypothesis keeps its files outside `folder` (the check of the suites: nothing is left in the source tree)."""
    return not str(storage_directory("")).startswith(str(folder))


# ── Shared strategies ──────────────────────────────────────────────────────────

def _sha(data):
    return hashlib.sha256(data).hexdigest()


# A real SHA-256 digest (64 lower-case hex characters), derived from a short byte string.
HASHES = st.binary(min_size=0, max_size=8).map(_sha)

# A real calendar day, written YYYY-MM-DD (the years the archive can hold).
DATES = st.dates(min_value=datetime.date(2012, 1, 1),
                 max_value=datetime.date(2035, 12, 31)).map(lambda d: d.isoformat())

# A JSON value of any shape (what an export file or a stored day can hold).
JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers(min_value=-10**9, max_value=10**9)
    | st.floats(allow_nan=False, allow_infinity=False, width=32) | st.text(max_size=12),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4),
    max_leaves=12,
)
