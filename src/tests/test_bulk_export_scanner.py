#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_export_scanner.py — garmin_bulk_export_scanner (v1.7.6)

Run from the project folder:
    python tests/test_bulk_export_scanner.py

All exports are built here from scratch (real ZIP files and folders with small
byte strings as "FIT files"; the scanner does not parse them) — no export of the
maintainer is needed. Entry names carry a marker that stands for the e-mail
address in the names of a real export; it must never show up in any output.
"""

import ast
import hashlib
import io
import shutil
import zipfile
from pathlib import Path

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

section("B2. garmin_bulk_export_scanner (v1.7.6)")
import garmin_bulk_export_scanner as sc

BASE = _TMPDIR / "scanner_tests"
shutil.rmtree(BASE, ignore_errors=True)
BASE.mkdir(parents=True)

SECRET = "secret.name@example.invalid"


def _zip_bytes(entries, compression=zipfile.ZIP_DEFLATED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _scan(path):
    st = sc.ScanStats()
    return list(sc.iter_fit_files(path, st)), st


def _hashes(items):
    return [h for h, _ in items]


def _snapshot(root):
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


def _payload(n):
    return (f"FIT-PAYLOAD-{n}-" * 6).encode()


P1, P2, P3, P4, P5 = (_payload(i) for i in range(1, 6))
EXPECTED = {_sha(p) for p in (P1, P2, P3, P4)}

# ── One export, in all the shapes it can reach us ──────────────────────────────
inner1 = _zip_bytes({f"{SECRET}_1.fit": P1, f"{SECRET}_2.fit": P2})
inner2 = _zip_bytes({f"{SECRET}_2b.fit": P2, f"{SECRET}_3.fit": P3, "notes.txt": b"x"})
other = _zip_bytes({"dev.bak": b"b", "w.fit": P4})
tree = {"DI/Up/Part1.zip": inner1, "DI/Up/Part2.zip": inner2, "DI/Dev/other.zip": other, "customer.json": b"{}"}

export_zip = _put(BASE / "export.zip", _zip_bytes(tree))                       # 1. the whole export as one ZIP
for _name, _data in tree.items():                                               # 2. unpacked once, inner ZIPs still packed
    _put(BASE / "packed" / _name, _data)
_put(BASE / "unpacked" / "DI" / "Up" / "Part1" / f"{SECRET}_1.fit", P1)           # 3. inner ZIPs unpacked as well
_put(BASE / "unpacked" / "DI" / "Up" / "Part1" / f"{SECRET}_2.fit", P2)
_put(BASE / "unpacked" / "DI" / "Up" / "Part2" / f"{SECRET}_2b.fit", P2)
_put(BASE / "unpacked" / "DI" / "Up" / "Part2" / f"{SECRET}_3.fit", P3)
_put(BASE / "unpacked" / "DI" / "Up" / "Part2" / "notes.txt", b"x")
_put(BASE / "unpacked" / "DI" / "Dev" / "other" / "dev.bak", b"b")
_put(BASE / "unpacked" / "DI" / "Dev" / "other" / "w.fit", P4)
_put(BASE / "unpacked" / "customer.json", b"{}")
inner_zip_file = _put(BASE / "Part1.zip", inner1)                                # 4. one inner ZIP chosen directly
fit_file = _put(BASE / "single" / "one.fit", P1)                                 # (and a single .fit file)

before = _snapshot(BASE)
items1, st1 = _scan(export_zip)
items2, st2 = _scan(BASE / "packed")
items3, st3 = _scan(BASE / "unpacked")
items4, st4 = _scan(inner_zip_file)
items5, st5 = _scan(fit_file)

check("shape 1 (whole export as ZIP): all different files, once each", set(_hashes(items1)) == EXPECTED and len(items1) == 4)
check("shape 2 (folder, inner ZIPs still packed): same files", set(_hashes(items2)) == EXPECTED and len(items2) == 4)
check("shape 3 (folder, inner ZIPs unpacked too): same files", set(_hashes(items3)) == EXPECTED and len(items3) == 4)
check("shape 4 (one inner ZIP chosen directly): its two files", set(_hashes(items4)) == {_sha(P1), _sha(P2)})
check("a single .fit file chosen directly is delivered", _hashes(items5) == [_sha(P1)])
check("each item is (sha256 of the bytes, the bytes)", all(h == _sha(d) for h, d in items1 + items2 + items3))
check("shape 1: the delivered bytes are the original contents", {d for _, d in items1} == {P1, P2, P3, P4})
check("shape 1 counters: 5 FIT entries seen, 4 delivered, 1 duplicate",
      (st1.fit_seen, st1.fit_yielded, st1.duplicates) == (5, 4, 1))
check("shape 1 counters: 4 ZIPs opened (outer + 3 inner), none unreadable, 3 other entries ignored",
      (st1.zips_opened, st1.zips_unreadable, st1.ignored) == (4, 0, 3))
check("shape 2 counters: 3 inner ZIPs opened, 1 duplicate, 3 other files ignored",
      (st2.zips_opened, st2.duplicates, st2.ignored) == (3, 1, 3))
check("shape 3 counters: no ZIP to open, 1 duplicate, 3 other files ignored",
      (st3.zips_opened, st3.duplicates, st3.ignored) == (0, 1, 3))
check("the same file in two inner ZIPs is delivered once (duplicate by content, not by name)",
      _hashes(items1).count(_sha(P2)) == 1)
check("a duplicate of a loose file is found as well (shape 3)", _hashes(items3).count(_sha(P2)) == 1)
check("the order is by entry name and the same on every run",
      _hashes(items1) == [_sha(P4), _sha(P1), _sha(P2), _sha(P3)] and _hashes(_scan(export_zip)[0]) == _hashes(items1))
check("scanning writes nothing into the export (ZIP, packed and unpacked folders unchanged)", _snapshot(BASE) == before)

# ── Names never leave the scanner ──────────────────────────────────────────────
every_stat = (st1, st2, st3, st4, st5)
check("the entry names (stand-in for the e-mail address) appear in no counter",
      all(SECRET not in repr(s) for s in every_stat))
check("the stats object holds numbers only", all(isinstance(v, int) for s in every_stat for v in vars(s).values()))
check("the entry names are not part of what is delivered",
      all(SECRET.encode() not in d and SECRET not in h for h, d in items1 + items2 + items3))

# ── Damaged input: counted, the rest still runs ────────────────────────────────
cut = _put(BASE / "cut.zip", _zip_bytes(tree)[:-15])
items, st = _scan(cut)
check("a cut-off ZIP: nothing delivered, counted as unreadable, no exception", items == [] and st.zips_unreadable == 1)

mixed = _put(BASE / "mixed.zip", _zip_bytes({"bad.zip": b"not a zip at all", "ok.zip": inner1}))
items, st = _scan(mixed)
check("a damaged inner ZIP does not stop the others",
      set(_hashes(items)) == {_sha(P1), _sha(P2)} and st.zips_unreadable == 1)

stored = _zip_bytes({"a.fit": P1, "b.fit": P2}, compression=zipfile.ZIP_STORED)
at = stored.find(P1)
broken = _put(BASE / "crc.zip", stored[:at + 3] + bytes([stored[at + 3] ^ 0xFF]) + stored[at + 4:])
items, st = _scan(broken)
check("an entry with a wrong CRC is skipped and counted, the neighbour is delivered",
      _hashes(items) == [_sha(P2)] and st.unreadable_entries == 1)

garbage = _put(BASE / "readme.txt", b"this is not an archive")
items, st = _scan(garbage)
check("a chosen file that is neither ZIP nor FIT: nothing delivered, counted, no exception",
      items == [] and st.zips_unreadable == 1)

(BASE / "empty").mkdir()
items, st = _scan(BASE / "empty")
check("an empty folder delivers nothing and raises nothing", items == [] and st.fit_seen == 0)

try:
    sc.iter_fit_files(BASE / "does_not_exist")
    _missing = None
except FileNotFoundError as e:
    _missing = e
check("a path that does not exist raises FileNotFoundError at the call (not at the first item)", _missing is not None)

items, st = _scan(_put(BASE / "empty_entry.zip", _zip_bytes({"e.fit": b""})))
check("an empty .fit entry is delivered (the reader rejects it later)", items == [(_sha(b""), b"")])

items, st = _scan(_put(BASE / "upper.zip", _zip_bytes({"A.FIT": P1, "B.ZIP": inner2})))
check("extensions are matched case-insensitively (.FIT, .ZIP) inside a ZIP",
      set(_hashes(items)) == {_sha(P1), _sha(P2), _sha(P3)})
_put(BASE / "updir" / "A.FIT", P1)
_put(BASE / "updir" / "B.ZIP", inner2)
items, st = _scan(BASE / "updir")
check("extensions are matched case-insensitively (.FIT, .ZIP) in a folder too",
      set(_hashes(items)) == {_sha(P1), _sha(P2), _sha(P3)})

items, st = _scan(_put(BASE / "with_dirs.zip", _zip_bytes({"d/": b"", "d/e/": b"", "d/a.fit": P1})))
check("directory entries inside a ZIP are neither delivered nor counted as ignored files",
      _hashes(items) == [_sha(P1)] and st.ignored == 0 and st.fit_seen == 1)

items, st = _scan(_put(BASE / "odd_name.dat", inner1))
check("a ZIP is recognised by its content, not by the extension of the chosen file",
      set(_hashes(items)) == {_sha(P1), _sha(P2)} and st.zips_opened == 1)

# ── Limits ─────────────────────────────────────────────────────────────────────
ok3 = _put(BASE / "levels3.zip", _zip_bytes({"z1.zip": _zip_bytes({"z2.zip": _zip_bytes({"x.fit": P5})})}))
items, st = _scan(ok3)
check("three ZIP levels (the limit) are read", _hashes(items) == [_sha(P5)] and st.too_deep == 0)

deep4 = _put(BASE / "levels4.zip", _zip_bytes({"z1.zip": _zip_bytes({"z2.zip": _zip_bytes({"z3.zip": _zip_bytes({"x.fit": P5})})})}))
items, st = _scan(deep4)
check("a fourth ZIP level is not opened and is counted", items == [] and st.too_deep == 1)
_old_depth = sc.MAX_ZIP_DEPTH
sc.MAX_ZIP_DEPTH = 4
try:
    check("the depth limit is a module constant (raised to 4, the fourth level is read)",
          _hashes(_scan(deep4)[0]) == [_sha(P5)])
finally:
    sc.MAX_ZIP_DEPTH = _old_depth

_old_size = sc.MAX_FIT_BYTES
sc.MAX_FIT_BYTES = len(P1)
try:
    big = P1 + b"x"
    items, st = _scan(_put(BASE / "big.zip", _zip_bytes({"ok.fit": P1, "big.fit": big})))
    check("a FIT entry over the size limit is skipped and counted; one exactly at the limit is read",
          _hashes(items) == [_sha(P1)] and st.oversize == 1 and st.fit_seen == 2)
    _put(BASE / "bigdir" / "ok.fit", P1)
    _put(BASE / "bigdir" / "big.fit", big)
    items, st = _scan(BASE / "bigdir")
    check("the size limit applies to loose files too", _hashes(items) == [_sha(P1)] and st.oversize == 1)
finally:
    sc.MAX_FIT_BYTES = _old_size
check("limits as decided: 3 ZIP levels, 64 MB per file", (sc.MAX_ZIP_DEPTH, sc.MAX_FIT_BYTES) == (3, 64 * 1024 * 1024))

# ── Temporary files are always closed, also when the caller stops early ────────
_made = []
_real_tf = sc.tempfile.TemporaryFile


def _tracking(*a, **k):
    f = _real_tf(*a, **k)
    _made.append(f)
    return f


sc.tempfile.TemporaryFile = _tracking
try:
    list(sc.iter_fit_files(export_zip))
    check("temporary files were used for the inner ZIPs and all are closed after a full run",
          len(_made) == 3 and all(f.closed for f in _made))
    _made.clear()
    gen = sc.iter_fit_files(export_zip)
    next(gen)
    still_open = any(not f.closed for f in _made)
    gen.close()
    check("stopping in the middle of an inner ZIP closes its temporary file",
          still_open and len(_made) >= 1 and all(f.closed for f in _made))
    _made.clear()
    list(sc.iter_fit_files(mixed))
    check("a temporary file of a damaged inner ZIP is closed as well", len(_made) == 2 and all(f.closed for f in _made))
finally:
    sc.tempfile.TemporaryFile = _real_tf

# ── Leaf node, no output channel ───────────────────────────────────────────────
_tree = ast.parse(Path(sc.__file__).read_text(encoding="utf-8"))
_imports = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Import):
        _imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _imports.add(_n.module.split(".")[0])
check("leaf node: imports standard library only (no project module, no garmin_config)",
      _imports <= {"dataclasses", "hashlib", "pathlib", "shutil", "tempfile", "typing", "zipfile", "zlib", "__future__"})
check("no logging and no print: a name cannot reach a log or the console from here",
      "logging" not in _imports and not any(
          isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print" for n in ast.walk(_tree)))

summary()
