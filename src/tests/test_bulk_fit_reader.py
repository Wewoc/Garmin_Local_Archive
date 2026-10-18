#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_bulk_fit_reader.py — garmin_bulk_fit_reader (v1.7.6)

Run from the project folder:
    python tests/test_bulk_fit_reader.py

Every FIT file is built here from scratch (synthetic) — no export is needed.
The CRC is computed by an independent implementation (the nibble algorithm of
the FIT SDK), so the tests cannot share a bug with the module's table version.
"""

import ast
import struct
from pathlib import Path

import gla_testenv  # noqa: F401  sets up sys.path; must precede garmin_* imports
from support import check, section, summary

section("B1. garmin_bulk_fit_reader (v1.7.6)")
import garmin_bulk_fit_reader as fr

# ── Independent FIT builder (shared with the other bulk tests: tests/fit_builder.py) ──
from fit_builder import (ENUM, U8, S16, U16, U32, STR, F32, U8Z, U32Z,  # noqa: F401  (all base types are part of the helper)
                         MON as _MON, build_fit as _fit, define as _define, file_id as _file_id,
                         mon_row as _mon_row, row as _row)


def _reason(data, wanted=()):
    try:
        fr.parse_fit(data, wanted)
    except fr.FitFormatError as e:
        return e.reason
    return None


# ── Happy path ─────────────────────────────────────────────────────────────────
good = _fit(_file_id() + [_define(1, 55, _MON), _mon_row(1, 5000, 5000 & 0xFFFF, 61),
                          _mon_row(1, 5060, 5060 & 0xFFFF, 63), _mon_row(1, 5120, 5120 & 0xFFFF, 65)])
ft = fr.parse_fit(good, {55})
check("file_id: type read", ft.file_type == 32)
check("file_id: time_created read (raw FIT seconds)", ft.time_created == 1000)
check("message 55: three records, in file order",
      [m[27] for m in ft.messages[55]] == [61, 63, 65])
check("message 55: fields keyed by field number with decoded values",
      ft.messages[55][0] == {253: 5000, 26: 5000 & 0xFFFF, 27: 61})
check("only the wanted message numbers appear in messages", set(ft.messages) == {55})
check("wanted empty: no messages returned, file_id still read",
      fr.parse_fit(good).messages == {} and fr.parse_fit(good).file_type == 32)
check("wanted may be a list, tuple, set or frozenset",
      all(len(fr.parse_fit(good, w).messages[55]) == 3 for w in ([55], (55,), {55}, frozenset({55}))))
check("a wanted number that does not occur is simply absent",
      55 not in fr.parse_fit(_fit(_file_id()), {55}).messages)
check("wanted may include 0: the file_id record is returned like any other",
      fr.parse_fit(good, {0}).messages[0][0][0] == 32)
check("two definitions of the same global number in different local types are both collected, in order",
      [m[27] for m in fr.parse_fit(_fit([_define(1, 55, [(27, 1, U8)]), _row(1, b"\x0A"),
                                         _define(2, 55, [(27, 1, U8)]), _row(2, b"\x0B"),
                                         _row(1, b"\x0C")]), {55}).messages[55]] == [10, 11, 12])
check("12-byte header (no header CRC) is accepted", fr.parse_fit(_fit(_file_id(), header_size=12)).file_type == 32)
check("header CRC 0 (unset) is accepted", fr.parse_fit(_fit(_file_id(), header_crc=False)).file_type == 32)
two_ids = fr.parse_fit(_fit(_file_id(ftype=32, tcreated=111) + _file_id(ftype=49, tcreated=222)))
check("two file_id records: the first one describes the file",
      two_ids.file_type == 32 and two_ids.time_created == 111)
check("file without a file_id message: type and time_created are None",
      fr.parse_fit(_fit([_define(1, 55, _MON), _mon_row(1, 1, 1, 60)]), {55}).file_type is None)

# ── Invalid values and field kinds ─────────────────────────────────────────────
inv = _fit(_file_id(ftype=0xFF, tcreated=0xFFFFFFFF, serial=0)
           + [_define(1, 55, _MON), _mon_row(1, 0xFFFFFFFF, 0xFFFF, 255)])
ft_inv = fr.parse_fit(inv, {0, 55})
check("invalid enum (0xFF) -> file_type None", ft_inv.file_type is None)
check("invalid uint32 (0xFFFFFFFF) -> time_created None and field value None",
      ft_inv.time_created is None and ft_inv.messages[55][0][253] is None)
check("invalid uint8 (255) and uint16 (0xFFFF) -> None",
      ft_inv.messages[55][0][27] is None and ft_inv.messages[55][0][26] is None)
check("uint32z 0 is the invalid value of the z types -> None", ft_inv.messages[0][0][3] is None)
check("0 is a valid value for a plain uint8 (not turned into None)",
      fr.parse_fit(_fit([_define(1, 55, [(27, 1, U8)]), _row(1, b"\x00")]), {55}).messages[55][0][27] == 0)

kinds = _fit([
    _define(1, 99, [(1, 3, U8), (2, 6, STR), (3, 3, U16), (4, 1, 0x1E), (5, 4, F32), (6, 2, S16), (7, 2, S16), (8, 6, STR)]),
    _row(1, bytes([1, 2, 255]) + b"abc\x00\x00\x00" + b"\x01\x02\x03" + b"\x55"
         + struct.pack("<f", 1.5) + struct.pack("<h", -5) + struct.pack("<h", 0x7FFF) + b"\x00" * 6),
])
k = fr.parse_fit(kinds, {99}).messages[99][0]
check("array of uint8 -> tuple, invalid element -> None", k[1] == (1, 2, None))
check("string: up to the first NUL", k[2] == "abc")
check("string that is empty (all NUL) -> None", k[8] is None)
check("size that is not a multiple of the base type -> raw bytes", k[3] == b"\x01\x02\x03")
check("unknown base type -> raw bytes", k[4] == b"\x55")
check("float32 value", k[5] == 1.5)
check("signed int16", k[6] == -5)
check("signed int16 invalid (0x7FFF) -> None", k[7] is None)
nan = _fit([_define(1, 99, [(5, 4, F32)]), _row(1, b"\xff\xff\xff\xff")])
check("float32 NaN pattern (0xFFFFFFFF) -> None", fr.parse_fit(nan, {99}).messages[99][0][5] is None)

# ── Byte order, developer fields, redefinition ─────────────────────────────────
be = _fit([_define(4, 55, [(253, 4, U32)], big=True), _row(4, struct.pack(">I", 123456))])
check("big-endian definition is decoded as big-endian", fr.parse_fit(be, {55}).messages[55][0][253] == 123456)
mixed = _fit([_define(1, 55, [(253, 4, U32)], big=True), _row(1, struct.pack(">I", 7)),
              _define(2, 55, [(253, 4, U32)]), _row(2, struct.pack("<I", 9))])
check("byte order is per definition (big then little in one file)",
      [m[253] for m in fr.parse_fit(mixed, {55}).messages[55]] == [7, 9])

dev = _fit([_define(3, 55, [(27, 1, U8)], dev=[(0, 2, 0)]), _row(3, bytes([70]) + b"\xAA\xBB"), _row(3, bytes([71]) + b"\xCC\xDD")])
check("developer fields are skipped, the following record stays aligned",
      [m[27] for m in fr.parse_fit(dev, {55}).messages[55]] == [70, 71])

dev2 = _fit([_define(3, 55, [(27, 1, U8)], dev=[(0, 2, 0), (1, 3, 0), (2, 1, 1)]),
             _row(3, bytes([80]) + b"\x01\x02" + b"\x03\x04\x05" + b"\x06"),
             _row(3, bytes([81]) + b"\x01\x02" + b"\x03\x04\x05" + b"\x06")])
check("several developer fields: all their sizes are counted, records stay aligned",
      [m[27] for m in fr.parse_fit(dev2, {55}).messages[55]] == [80, 81])

redef = _fit([_define(5, 55, [(27, 1, U8)]), _row(5, b"\x2A"),
              _define(5, 55, [(253, 4, U32)]), _row(5, struct.pack("<I", 4242))])
check("redefining a local message type changes how later records are read",
      fr.parse_fit(redef, {55}).messages[55] == [{27: 42}, {253: 4242}])

# ── Compressed timestamp headers (FIT SDK rule) ────────────────────────────────
ct = _fit([
    _define(2, 55, [(253, 4, U32), (27, 1, U8)]), _row(2, struct.pack("<IB", 1000, 60)),   # 1000 & 31 = 8
    _define(1, 55, [(27, 1, U8)]),
    bytes([0x80 | (1 << 5) | 12]) + b"\x3D",                                                 # offset 12 >= 8 -> 1004
    bytes([0x80 | (1 << 5) | 3]) + b"\x3E",                                                  # offset 3 < 12 -> rollover -> 1027
])
cm = fr.parse_fit(ct, {55}).messages[55]
check("compressed header: first record keeps its own full timestamp", cm[0] == {253: 1000, 27: 60})
check("compressed header: timestamp from the offset (no rollover)", cm[1] == {27: 61, 253: 1004})
check("compressed header: timestamp after a 5-bit rollover", cm[2] == {27: 62, 253: 1027})
cm2 =fr.parse_fit(_fit([_define(3, 77, [(253, 4, U32)]), _row(3, struct.pack("<I", 2000)),
                         _define(1, 55, [(27, 1, U8)]), bytes([0x80 | (1 << 5) | 20]) + b"\x01"]), {55}).messages[55]
check("compressed header: reference taken from another message (2000 & 31 = 16, offset 20 -> 2004)",
      cm2 == [{27: 1, 253: 2004}])
check("compressed header without any reference timestamp -> structure",
      _reason(_fit([_define(1, 55, [(27, 1, U8)]), bytes([0x80 | (1 << 5) | 5]) + b"\x01"]), {55}) == "structure")

# ── Rejected files (whole file, never half-read) ───────────────────────────────
check("empty input -> not_fit", _reason(b"") == "not_fit")
check("text that is not FIT -> not_fit", _reason(b"hello world, this is definitely not a FIT file") == "not_fit")
check("input shorter than a header -> not_fit", _reason(good[:10]) == "not_fit")
sig = bytearray(good)
sig[8:12] = b".FOO"
check("wrong signature -> not_fit", _reason(bytes(sig)) == "not_fit")
check("body cut off (header says more) -> truncated", _reason(good[:30]) == "truncated")
check("last bytes missing -> truncated", _reason(good[:-5]) == "truncated")
body_flip = bytearray(good)
body_flip[20] ^= 0xFF
check("flipped byte in the body -> crc", _reason(bytes(body_flip)) == "crc")
crc_flip = bytearray(good)
crc_flip[-1] ^= 0xFF
check("wrong file CRC -> crc", _reason(bytes(crc_flip)) == "crc")
check("wrong (non-zero) header CRC with a correct file CRC -> crc",
      _reason(_fit(_file_id(), header_crc=0x1234)) == "crc")
check("bytes after the end of the file -> structure", _reason(good + b"\x00\x00") == "structure")
try:
    fr.parse_fit(good + b"\x00\x00")
    _trail_msg = ""
except fr.FitFormatError as _e:
    _trail_msg = str(_e)
check("bytes after the end of the file are caught by the size check itself (not by a later accident)",
      "after the end of the file" in _trail_msg)
hs = bytearray(good)
hs[0] = 13
check("header size other than 12 or 14 -> structure", _reason(bytes(hs)) == "structure")
check("data record for an undefined local message type (CRC valid) -> structure",
      _reason(_fit([_row(9, b"\x01")])) == "structure")
check("record running past the end of the data (CRC valid) -> structure",
      _reason(_fit([_define(1, 55, [(253, 4, U32)]), _row(1, b"\x01\x02")]), {55}) == "structure")
check("definition running past the end of the data (CRC valid) -> structure",
      _reason(_fit([bytes([0x41, 0, 0, 55, 0, 5, 253, 4])])) == "structure")
check("FitFormatError carries a reason code and is an Exception",
      issubclass(fr.FitFormatError, Exception) and fr.FitFormatError("crc").reason == "crc")
check("a rejected file raises instead of returning a partial result",
      all(_reason(d, {55}) is not None for d in (good[:-5], bytes(body_flip), bytes(crc_flip))))

# ── Leaf node ──────────────────────────────────────────────────────────────────
_tree = ast.parse(Path(fr.__file__).read_text(encoding="utf-8"))
_imports = set()
for _n in ast.walk(_tree):
    if isinstance(_n, ast.Import):
        _imports |= {a.name.split(".")[0] for a in _n.names}
    elif isinstance(_n, ast.ImportFrom) and _n.module:
        _imports.add(_n.module.split(".")[0])
check("leaf node: imports only struct/typing (no project module, no garmin_config)",
      _imports <= {"struct", "typing", "__future__"})

summary()
