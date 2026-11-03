#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_prop_backup.py — property tests of garmin_backup_common (v1.7.6.11)

Run from the project folder:
    python tests/test_prop_backup.py

The monthly backup flow (month folder -> monthly ZIP) with generated states; the hand-picked
cases stay in test_backup_common.py. Rules of REFERENCE_INVARIANTS.md "Source / Quality / Backup":
  - a file in the month folder is the newest backup copy of its day: it replaces the ZIP entry
    whenever its bytes differ; entries of other files are copied as they are
  - the current month and later ones are not consolidated
  - a ZIP that does not open or fails its check is not touched, the month folder stays
  - `force_filenames` never changes what the result holds (it only adds a replace of identical bytes)
  - read_copy gives the newest copy: the month folder first, then the ZIP entry
  - after backup_file the copy of the day is the bytes of the source, whatever the history

Folders are created in the test temp folder; nothing outside it is touched.
"""

import shutil
import tempfile
import zipfile
from datetime import date

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
from prop_support import prop, given, st

import garmin_backup_common as bc

_PAST = ["2020-01", "2020-02", "2020-03"]                 # always completed months
_OPEN_MONTH = date.today().strftime("%Y-%m")                  # the month backup_file() treats as open
_BYTES = st.sampled_from([b"{\"a\":1}", b"{\"a\":2}", b"{\"b\":3}", b"x"])
_DAY_OF_MONTH = st.integers(1, 28)


def _kind(root):
    return bc.BackupKind(area="raw", src_dir=root / "raw", backup_dir=root / "backup", prefix="garmin_raw_",
                         zip_prefix="raw_backup_", is_valid=lambda data, d: True)


class _Sandbox:
    """A fresh folder for one example, removed afterwards."""
    def __enter__(self):
        self.root = __import__("pathlib").Path(tempfile.mkdtemp(prefix="prop_backup_", dir=_TMPDIR))
        (self.root / "raw").mkdir()
        (self.root / "backup").mkdir()
        return self.root

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)


def _fname(month, day):
    return f"garmin_raw_{month}-{day:02d}.json"


def _zip_entries(path):
    with zipfile.ZipFile(path) as zf:
        return {i.filename: zf.read(i.filename) for i in zf.infolist()}


def _write_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@st.composite
def months(draw):
    """{month: {"dir": {name: bytes}, "zip": {name: bytes} | None | "damaged"}} for the completed months."""
    state = {}
    for month in draw(st.lists(st.sampled_from(_PAST), min_size=1, max_size=3, unique=True)):
        days = draw(st.lists(_DAY_OF_MONTH, max_size=4, unique=True))
        in_dir = {_fname(month, d): draw(_BYTES) for d in days if draw(st.booleans())}
        zip_kind = draw(st.sampled_from(["none", "none", "intact", "intact", "damaged"]))
        if zip_kind == "intact":
            zip_days = draw(st.lists(_DAY_OF_MONTH, max_size=4, unique=True))
            zipped = {_fname(month, d): draw(_BYTES) for d in zip_days}
        else:
            zipped = None if zip_kind == "none" else "damaged"
        state[month] = {"dir": in_dir, "zip": zipped}
    return state


def _build(root, state, kind):
    for month, parts in state.items():
        if parts["dir"] or parts["zip"] is None or parts["zip"] == "damaged":
            (kind.backup_dir / month).mkdir(parents=True, exist_ok=True)      # an empty month folder is a state too
            for name, data in parts["dir"].items():
                (kind.backup_dir / month / name).write_bytes(data)
        if parts["zip"] == "damaged":
            kind.zip_path(month).write_bytes(b"this is not a zip file")
        elif parts["zip"] is not None:
            _write_zip(kind.zip_path(month), parts["zip"])


# ══════════════════════════════════════════════════════════════════════════════
section("B1. consolidate_months — month folders into monthly ZIPs")
# ══════════════════════════════════════════════════════════════════════════════

@prop("consolidate_months: the folder copy wins, other ZIP entries stay as they are, the folder goes; a damaged ZIP is left alone", examples=60)
@given(months(), st.booleans())
def _(state, force):
    with _Sandbox() as root:
        kind = _kind(root)
        _build(root, state, kind)
        names = {n for p in state.values() for n in p["dir"]}
        bc.consolidate_months(kind, "2020-12", {n for n in names} if force else None)
        for month, parts in state.items():
            folder, zpath = kind.backup_dir / month, kind.zip_path(month)
            if not parts["dir"]:
                assert not folder.exists(), "an empty month folder was kept"
                if parts["zip"] is None:
                    assert not zpath.exists()
                elif parts["zip"] == "damaged":
                    assert zpath.read_bytes() == b"this is not a zip file"
                else:
                    assert _zip_entries(zpath) == parts["zip"]
            elif parts["zip"] == "damaged":
                assert zpath.read_bytes() == b"this is not a zip file", "a damaged ZIP was touched"
                assert {p.name: p.read_bytes() for p in folder.iterdir()} == parts["dir"], "the folder fallback changed"
            else:
                assert not folder.exists(), "the folder of an intact month was kept"
                assert _zip_entries(zpath) == {**(parts["zip"] or {}), **parts["dir"]}


@prop("consolidate_months: the current month and later months are not touched; running it twice changes nothing", examples=60)
@given(months(), st.sampled_from(["2020-01", "2020-02", "2020-03", "2020-04"]))
def _(state, current):
    with _Sandbox() as root:
        kind = _kind(root)
        _build(root, state, kind)
        before = _tree(kind.backup_dir)
        bc.consolidate_months(kind, current)
        after_first = _tree(kind.backup_dir)
        for month in state:
            if month >= current:
                assert {k: v for k, v in after_first.items() if k.startswith(month + "/") or k == f"raw_backup_{month}.zip"} == \
                       {k: v for k, v in before.items() if k.startswith(month + "/") or k == f"raw_backup_{month}.zip"}
        bc.consolidate_months(kind, current)
        assert _tree(kind.backup_dir) == after_first, "a second run changed the backup"


@prop("consolidate_months: force_filenames never changes what the result holds", examples=60)
@given(months())
def _(state):
    results = []
    for force in (False, True):
        with _Sandbox() as root:
            kind = _kind(root)
            _build(root, state, kind)
            names = {n for p in state.values() for n in p["dir"]}
            bc.consolidate_months(kind, "2020-12", names if force else None)
            results.append({k: (_zip_entries(kind.zip_path(m)) if kind.zip_path(m).exists() and state[m]["zip"] != "damaged" else None)
                            for m, k in ((m, m) for m in state)})
    assert results[0] == results[1]


# ══════════════════════════════════════════════════════════════════════════════
section("B2. backup_file and read_copy — the newest copy of a day")
# ══════════════════════════════════════════════════════════════════════════════

_BACKUP_OPS = st.lists(st.tuples(st.sampled_from(_PAST + [_OPEN_MONTH]), st.integers(1, 3), _BYTES, st.booleans(), st.booleans()),
                       min_size=1, max_size=8)


@prop("backup_file: after every backup the copy of the day is the bytes of the source (month folder or ZIP), whatever came before", examples=40)
@given(_BACKUP_OPS)
def _(ops):
    with _Sandbox() as root:
        kind = _kind(root)
        latest = {}
        for month, day, data, force, damage_zip in ops:
            name = _fname(month, day)
            if month != _OPEN_MONTH and damage_zip and kind.zip_path(month).exists():
                kind.zip_path(month).write_bytes(b"damaged")
                # the test itself destroyed the copies of the other days of that month that lived in the ZIP only
                for lost in [n for n in latest if n[len("garmin_raw_"):][:7] == month and not (kind.backup_dir / month / n).exists()]:
                    del latest[lost]
            (kind.src_dir / name).write_bytes(data)
            ok = bc.backup_file(kind, f"{month}-{day:02d}", force=force)
            assert ok is True
            latest[name] = data
            for known, want in latest.items():
                # a damaged ZIP is not built on: the month folder stays and holds the newest copy of the day
                assert bc.read_copy(kind, known) == want, known
        assert not list(kind.backup_dir.rglob("*.tmp"))


@prop("backup_file: a day that does not exist in the source is a False answer, never an exception, and writes nothing", examples=30)
@given(st.sampled_from(_PAST), st.integers(1, 28))
def _(month, day):
    with _Sandbox() as root:
        kind = _kind(root)
        assert bc.backup_file(kind, f"{month}-{day:02d}") is False
        assert not _tree(kind.backup_dir)


@prop("read_copy: the month folder is the newest copy and comes first, otherwise the ZIP entry, otherwise nothing", examples=60)
@given(st.sampled_from(_PAST), st.integers(1, 3), st.one_of(st.none(), _BYTES), st.one_of(st.none(), _BYTES))
def _(month, day, in_dir, in_zip):
    with _Sandbox() as root:
        kind = _kind(root)
        name = _fname(month, day)
        if in_dir is not None:
            (kind.backup_dir / month).mkdir(parents=True)
            (kind.backup_dir / month / name).write_bytes(in_dir)
        if in_zip is not None:
            _write_zip(kind.zip_path(month), {name: in_zip})
        assert bc.read_copy(kind, name) == (in_dir if in_dir is not None else in_zip)


# ══════════════════════════════════════════════════════════════════════════════
section("Findings of v1.7.6.11 (pinned as they are — the decision per finding is the maintainer's)")
# ══════════════════════════════════════════════════════════════════════════════

# Finding 7 (found while modelling the month folder for B1): consolidate_months() zips the files that match the pattern
# of the kind and then removes the WHOLE month folder (shutil.rmtree), so a file of another name in it (a stray
# notes.txt, a copy somebody put there) is deleted without a trace and without a log line. Only the app writes into
# backup/<area>/<month>/; the pattern files are the only files the app puts there.
with _Sandbox() as _root:
    _kind_f = _kind(_root)
    _month_dir = _kind_f.backup_dir / "2020-01"
    _month_dir.mkdir(parents=True)
    (_month_dir / _fname("2020-01", 1)).write_bytes(b"x")
    (_month_dir / "notes.txt").write_bytes(b"not a backup file")
    bc.consolidate_months(_kind_f, "2020-12")
    _entries = _zip_entries(_kind_f.zip_path("2020-01"))
    check("finding 7: a file in a completed month folder that does not match the pattern is deleted with the folder (pinned)",
          _entries == {_fname("2020-01", 1): b"x"} and not _month_dir.exists())

summary()
