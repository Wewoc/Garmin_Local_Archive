#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_fuzz_parsers.py — fuzzing of the parsers that read foreign bytes (v1.7.6.11)

Run from the project folder:
    python tests/test_fuzz_parsers.py

The FIT reader (garmin_bulk_fit_reader) and the export scanner (garmin_bulk_export_scanner)
get valid files that are then changed; they must end in their declared results only:
  - FIT reader : a FitFile, or FitFormatError with reason not_fit / truncated / crc / structure.
                 Never another exception, whatever the bytes are. Any change of a sealed file is
                 caught by the CRC; a change that is sealed again (CRC fixed) is caught by the walk
                 of the records or accepted as a different valid file — never a crash.
  - scanner    : never raises (but FileNotFoundError for a path that is not there), counts what it
                 skips, and its counters add up: fit_seen = yielded + duplicates + oversize + unreadable.
The files are built by tests/fit_builder.py (an independent CRC), not by the reader.

Examples are derived (prop_support.py), the seeds are synthetic: no file of an export is used.
"""

import hashlib
import io
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary
from prop_support import prop, given, st
from fit_builder import (ENUM, U8, S16, U16, U32, STR, F32, U8Z, U32Z, FIT_EPOCH_OFFSET, build_fit, crc, define,  # noqa: F401
                         file_id, monitoring_fit, row, simple_fit)

import garmin_bulk_export_scanner as scanner
import garmin_bulk_fit_reader as fr

_REASONS = {"not_fit", "truncated", "crc", "structure"}


def _outcome(data, wanted=(55,)):
    """("ok", FitFile) or ("error", reason); any other exception propagates (= a failed property)."""
    try:
        return "ok", fr.parse_fit(data, wanted)
    except fr.FitFormatError as e:
        assert e.reason in _REASONS, e.reason
        return "error", e.reason


def _seal(body, header_size):
    """The bytes of a FIT file around an arbitrary body: data size, header CRC and file CRC are right."""
    return build_fit([bytes(body)], header_size=header_size)


# ══════════════════════════════════════════════════════════════════════════════
section("F1. valid files — the seeds")
# ══════════════════════════════════════════════════════════════════════════════

_BPM = st.one_of(st.none(), st.just(0), st.integers(1, 254))


@st.composite
def monitoring_files(draw):
    """(file bytes, [(unix, bpm)] as written)."""
    t = draw(st.integers(1_500_000_000, 1_900_000_000))
    samples = []
    for _ in range(draw(st.integers(0, 12))):
        t += draw(st.sampled_from([1, 1, 60, 60, 61, 599, 601, 3600, 40000]))
        samples.append((t, draw(_BPM)))
    created = draw(st.integers(1_500_000_000, 1_900_000_000))
    return monitoring_fit(created, samples, serial=draw(st.integers(1, 2**31))), samples, created


@prop("valid monitoring file: the reader gives back exactly the samples that were written (an independent builder)", examples=100)
@given(monitoring_files())
def _(case):
    data, samples, created = case
    kind, ft = _outcome(data)
    assert kind == "ok"
    assert ft.file_type == 32 and ft.time_created == created - FIT_EPOCH_OFFSET
    records = ft.messages.get(55, [])
    assert len(records) == len(samples)
    assert [r.get(27) if r.get(27) is not None else None for r in records] == [None if b is None else b for _t, b in samples]
    full = [r for r in records if r.get(253) is not None]
    assert all(r[253] + FIT_EPOCH_OFFSET in {t for t, _b in samples} for r in full)


_FIELD_TYPES = [(U8, 1), (U16, 2), (U32, 4), (S16, 2), (F32, 4), (U8Z, 1), (U32Z, 4), (ENUM, 1), (STR, 6), (U8, 5), (U16, 6)]


@st.composite
def mixed_files(draw):
    """A file_id plus a few definitions (any base type, both byte orders, developer fields) and data messages."""
    records = file_id(draw(st.sampled_from([32, 49, 44, 4])), draw(st.integers(0, 2**32 - 2)), draw(st.integers(1, 2**31)), local=0)
    sizes = {}
    for local in draw(st.lists(st.integers(1, 5), min_size=1, max_size=3, unique=True)):
        fields, total = [], 0
        for number in draw(st.lists(st.integers(0, 250), min_size=1, max_size=4, unique=True)):
            base, size = draw(st.sampled_from(_FIELD_TYPES))
            fields.append((number, size, base))
            total += size
        dev = [(draw(st.integers(0, 3)), draw(st.integers(1, 3)), 0) for _ in range(draw(st.integers(0, 2)))]
        records.append(define(local, draw(st.sampled_from([55, 20, 21, 55, 999])), fields, big=draw(st.booleans()), dev=dev))
        sizes[local] = total + sum(d[1] for d in dev)
    for _ in range(draw(st.integers(0, 6))):
        local = draw(st.sampled_from(sorted(sizes)))
        records.append(row(local, draw(st.binary(min_size=sizes[local], max_size=sizes[local]))))
    return build_fit(records, header_size=draw(st.sampled_from([12, 14])))


@prop("valid files of any shape (base types, arrays, strings, byte orders, developer fields) are read without error", examples=150)
@given(mixed_files())
def _(data):
    kind, ft = _outcome(data, {55, 20, 21, 999})
    assert kind == "ok", ft


@prop("the numbers asked for change only what is returned: file_type and time_created never depend on them", examples=100)
@given(mixed_files(), st.sets(st.sampled_from([0, 20, 21, 55, 999]), max_size=3))
def _(data, wanted):
    _k, a = _outcome(data, ())
    _k, b = _outcome(data, wanted)
    assert (a.file_type, a.time_created) == (b.file_type, b.time_created)
    assert a.messages == {}
    assert set(b.messages) <= wanted
    _k, everything = _outcome(data, {0, 20, 21, 55, 999})
    for number, records in b.messages.items():
        assert everything.messages[number] == records, "a message differs when more numbers are asked for"


# ══════════════════════════════════════════════════════════════════════════════
section("F2. changed files — only the declared errors")
# ══════════════════════════════════════════════════════════════════════════════

@prop("a sealed file with any one byte changed is never accepted — the CRC finds it (error from the declared set)", examples=200)
@given(monitoring_files() | mixed_files().map(lambda d: (d, None, None)), st.data())
def _(case, data):
    original = case[0]
    index = data.draw(st.integers(0, len(original) - 1))
    flip = data.draw(st.integers(1, 255))
    changed = bytearray(original)
    changed[index] ^= flip
    kind, why = _outcome(bytes(changed))
    assert kind == "error", f"byte {index} changed by {flip:#x} was accepted"


@prop("every proper prefix of a file is refused: not_fit below 12 bytes or without the signature, otherwise truncated", examples=200)
@given(monitoring_files(), st.data())
def _(case, data):
    original = case[0]
    n = data.draw(st.integers(0, len(original) - 1))
    kind, why = _outcome(original[:n])
    assert kind == "error"
    if n < 12:
        assert why == "not_fit"
    else:
        assert why in ("truncated", "structure"), why        # a header size byte cut to 14 bytes needs 14 + 2


@prop("bytes after the end of a file are refused as structure", examples=100)
@given(monitoring_files(), st.binary(min_size=1, max_size=20))
def _(case, tail):
    assert _outcome(case[0] + tail) == ("error", "structure")


@prop("a file sealed again after its records were changed ends in a FitFile or in structure — never in another exception", examples=400)
@given(mixed_files() | monitoring_files().map(lambda c: c[0]), st.data())
def _(original, data):
    header_size = original[0]
    body = bytearray(original[header_size:-2])
    for _ in range(data.draw(st.integers(1, 4))):
        op = data.draw(st.sampled_from(["replace", "replace", "delete", "insert", "bit"]))
        if not body and op != "insert":
            continue
        pos = data.draw(st.integers(0, max(len(body) - 1, 0)))
        if op == "replace":
            body[pos] = data.draw(st.integers(0, 255))
        elif op == "bit":
            body[pos] ^= 1 << data.draw(st.integers(0, 7))
        elif op == "delete":
            del body[pos:pos + data.draw(st.integers(1, 6))]
        else:
            body[pos:pos] = data.draw(st.binary(min_size=1, max_size=8))
    kind, outcome = _outcome(_seal(body, header_size), {55, 20, 21, 999, 0})
    if kind == "error":
        assert outcome == "structure", outcome            # the CRCs and the length are right: only the walk can object


def _seal_head(head, body):
    """A file around a given first 12 header bytes: data size, header CRC (if the size byte says 14) and file CRC are right."""
    size = head[0] if head[0] in (12, 14) else 14
    raw = bytes([size]) + head[1:4] + struct.pack("<I", len(body)) + head[8:12]
    if size == 14:
        raw += struct.pack("<H", crc(raw))
    raw += bytes(body)
    return raw + struct.pack("<H", crc(raw))


@prop("a header with any first 12 bytes (signature kept, size and CRCs right) ends in a FitFile or a declared error", examples=300)
@given(st.binary(min_size=12, max_size=12), st.binary(max_size=40))
def _(head, body):
    head = bytearray(head)
    head[8:12] = b".FIT"
    kind, why = _outcome(_seal_head(bytes(head), body))
    assert kind in ("ok", "error")


@prop("arbitrary bytes, with and without the FIT signature, end in a declared error; without the signature it is not_fit", examples=300)
@given(st.binary(max_size=60), st.booleans())
def _(blob, with_signature):
    if with_signature and len(blob) >= 12:
        blob = blob[:8] + b".FIT" + blob[12:]
    kind, why = _outcome(blob)
    assert kind == "error" or len(blob) >= 14
    if len(blob) < 12 or blob[8:12] != b".FIT":
        assert (kind, why) == ("error", "not_fit")


@prop("a header CRC that is wrong is refused as crc, also when the file CRC was made right afterwards; 0 means unset and is accepted", examples=100)
@given(monitoring_files(), st.integers(1, 0xFFFF))
def _(case, wrong):
    original = case[0]
    sealed = build_fit([original[14:-2]], header_size=14, header_crc=False)
    assert _outcome(sealed)[0] == "ok", "header CRC 0 (unset) must be accepted"
    right = struct.unpack_from("<H", build_fit([original[14:-2]], header_size=14), 12)[0]
    if wrong != right:
        assert _outcome(build_fit([original[14:-2]], header_size=14, header_crc=wrong)) == ("error", "crc")


# ══════════════════════════════════════════════════════════════════════════════
section("S1. export scanner — structure of an export")
# ══════════════════════════════════════════════════════════════════════════════

_NAME_END = st.sampled_from([".fit", ".FIT", ".Fit", ".txt", ".json", ".zip", ".ZIP", ""])
_PAYLOAD = st.sampled_from([b"A", b"BB", b"CCC", b"D" * 40])


@st.composite
def trees(draw, depth=0):
    """[(name, kind, payload)]: kind "fit" (payload bytes), "other" (bytes) or "zip" (payload = a tree)."""
    entries = []
    for i in range(draw(st.integers(0, 4))):
        end = draw(_NAME_END)
        name = f"e{i}{end}"
        low = end.lower()
        if low == ".fit":
            entries.append((name, "fit", draw(_PAYLOAD)))
        elif low == ".zip":
            entries.append((name, "zip", draw(trees(depth + 1)) if depth < 4 else []))
        else:
            entries.append((name, "other", draw(_PAYLOAD)))
    return entries


def _zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, kind, payload in entries:
            zf.writestr(name, _zip_bytes(payload) if kind == "zip" else payload)
    return buffer.getvalue()


def _expect(entries, level, found, counts):
    """The model of the walk: what a ZIP of this level holds (an independent re-statement of the documented rules)."""
    counts["zips_opened"] += 1
    for name, kind, payload in entries:
        if kind == "fit":
            counts["fit_seen"] += 1
            found.append(payload)
        elif kind == "zip":
            if level + 1 > scanner.MAX_ZIP_DEPTH:
                counts["too_deep"] += 1
            else:
                _expect(payload, level + 1, found, counts)
        else:
            counts["ignored"] += 1


def _scan(path):
    stats = scanner.ScanStats()
    items = list(scanner.iter_fit_files(path, stats))
    return items, stats


class _Tmp:
    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="fuzz_scan_", dir=_TMPDIR))
        return self.root

    def __exit__(self, *exc):
        shutil.rmtree(self.root, ignore_errors=True)


@prop("scanner: a ZIP with nested ZIPs delivers each different FIT file once, to the depth allowed, and counts the rest", examples=80)
@given(trees())
def _(entries):
    with _Tmp() as root:
        path = root / "export.zip"
        path.write_bytes(_zip_bytes(entries))
        items, stats = _scan(path)
    found, counts = [], dict.fromkeys(("zips_opened", "fit_seen", "too_deep", "ignored"), 0)
    _expect(entries, 1, found, counts)
    assert {digest for digest, _data in items} == {hashlib.sha256(b).hexdigest() for b in found}
    assert all(hashlib.sha256(data).hexdigest() == digest for digest, data in items)
    assert len({d for d, _x in items}) == len(items), "a file was delivered twice"
    assert (stats.zips_opened, stats.fit_seen, stats.too_deep, stats.ignored) == (counts["zips_opened"], counts["fit_seen"], counts["too_deep"], counts["ignored"])
    assert stats.fit_yielded == len(items) and stats.fit_seen == stats.fit_yielded + stats.duplicates + stats.oversize + stats.unreadable_entries
    assert stats.zips_unreadable == 0 and stats.oversize == 0 and stats.unreadable_entries == 0


@prop("scanner: a folder is not a ZIP level — the ZIPs inside it start at level 1, so it reads one level deeper than a ZIP of the same entries", examples=60)
@given(trees())
def _(entries):
    with _Tmp() as root:
        folder = root / "export"
        folder.mkdir()
        for name, kind, payload in entries:
            (folder / name).write_bytes(_zip_bytes(payload) if kind == "zip" else payload)
        items, stats = _scan(folder)
    found, counts = [], dict.fromkeys(("zips_opened", "fit_seen", "too_deep", "ignored"), 0)
    _expect(entries, 0, found, counts)                      # the folder takes the place of level 0
    assert {d for d, _x in items} == {hashlib.sha256(b).hexdigest() for b in found}
    assert (stats.zips_opened, stats.fit_seen, stats.too_deep, stats.ignored) == (counts["zips_opened"] - 1, counts["fit_seen"], counts["too_deep"], counts["ignored"])
    assert stats.fit_seen == stats.fit_yielded + stats.duplicates + stats.oversize + stats.unreadable_entries


@prop("scanner: a single .fit file is delivered as it is; a path that is not there is the one error", examples=40)
@given(_PAYLOAD)
def _(payload):
    with _Tmp() as root:
        single = root / "one.fit"
        single.write_bytes(payload)
        items, stats = _scan(single)
        assert items == [(hashlib.sha256(payload).hexdigest(), payload)] and stats.fit_seen == 1
        try:
            scanner.iter_fit_files(root / "nope")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("a missing path did not raise FileNotFoundError")


# ══════════════════════════════════════════════════════════════════════════════
section("S2. export scanner — changed archives")
# ══════════════════════════════════════════════════════════════════════════════

_SEED_TREE = [("a.fit", "fit", b"AAAA"), ("notes.txt", "other", b"hello"),
              ("inner.zip", "zip", [("b.fit", "fit", b"BBBB"), ("deep.zip", "zip", [("c.fit", "fit", b"CCCC")])])]
_SEED = _zip_bytes(_SEED_TREE)


@prop("scanner: an archive with bytes changed, cut or added never raises; what it skips it counts; the counters add up", examples=300)
@given(st.data())
def _(data):
    blob = bytearray(_SEED)
    for _ in range(data.draw(st.integers(1, 5))):
        op = data.draw(st.sampled_from(["flip", "flip", "set", "cut", "insert", "delete"]))
        pos = data.draw(st.integers(0, max(len(blob) - 1, 0)))
        if op == "flip" and blob:
            blob[pos] ^= data.draw(st.integers(1, 255))
        elif op == "set" and blob:
            blob[pos] = data.draw(st.integers(0, 255))
        elif op == "cut":
            del blob[pos:]
        elif op == "insert":
            blob[pos:pos] = data.draw(st.binary(min_size=1, max_size=8))
        elif blob:
            del blob[pos:pos + data.draw(st.integers(1, 12))]
    with _Tmp() as root:
        path = root / "export.zip"
        path.write_bytes(bytes(blob))
        items, stats = _scan(path)                               # must not raise
    assert stats.fit_seen == stats.fit_yielded + stats.duplicates + stats.oversize + stats.unreadable_entries
    assert stats.fit_yielded == len(items)
    assert all(hashlib.sha256(d).hexdigest() == h for h, d in items)
    assert len({h for h, _d in items}) == len(items)


@prop("scanner: a file that is no ZIP and no FIT is counted as unreadable, never raises", examples=80)
@given(st.binary(max_size=80), st.sampled_from([".zip", ".bin", ".fit", ""]))
def _(blob, suffix):
    with _Tmp() as root:
        path = root / f"thing{suffix}"
        path.write_bytes(blob)
        items, stats = _scan(path)
    assert stats.fit_seen == stats.fit_yielded + stats.duplicates + stats.oversize + stats.unreadable_entries


# ══════════════════════════════════════════════════════════════════════════════
section("Findings of v1.7.6.11 (pinned as they are — the decision per finding is the maintainer's)")
# ══════════════════════════════════════════════════════════════════════════════

# Finding 8 (found while writing the nesting model): MAX_FIT_BYTES (64 MB) caps a .fit entry, but an inner .zip entry is
# copied to a temporary file whole, whatever its size (_walk_nested). An inner ZIP of stored zeros compresses to almost
# nothing in the outer ZIP, so a small export file can make the scanner write gigabytes into the temp folder. The export
# is the user's own download; nothing in the maintainer's archive is near it. Shown here with a cap of 1 MB and 3 MB of
# zeros: the .fit entry of that size is counted as oversize, the ZIP of that size is opened and walked.
_pad = io.BytesIO()
with zipfile.ZipFile(_pad, "w", zipfile.ZIP_STORED) as _inner:
    _inner.writestr("small.fit", b"FIT")
    _inner.writestr("pad.bin", b"\0" * (3 * 1024 * 1024))
_outer = io.BytesIO()
with zipfile.ZipFile(_outer, "w", zipfile.ZIP_DEFLATED) as _zf:
    _zf.writestr("inner.zip", _pad.getvalue())
    _zf.writestr("big.fit", b"\0" * (3 * 1024 * 1024))
with _Tmp() as _root:
    _path = _root / "export.zip"
    _path.write_bytes(_outer.getvalue())
    _saved_cap = scanner.MAX_FIT_BYTES
    scanner.MAX_FIT_BYTES = 1024 * 1024
    try:
        _items, _stats = _scan(_path)
    finally:
        scanner.MAX_FIT_BYTES = _saved_cap
check("finding 8: with a cap of 1 MB a 3 MB .fit entry is oversize, but a 3 MB inner ZIP is copied, opened and walked (pinned)",
      _stats.oversize == 1 and _stats.zips_opened == 2 and [d for _h, d in _items] == [b"FIT"])
check("finding 8: ... the archive itself is small (the size of the outer file is not what the scanner has to hold)",
      len(_outer.getvalue()) < 20_000)

summary()
