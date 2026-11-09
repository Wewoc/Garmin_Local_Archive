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

# ══════════════════════════════════════════════════════════════════════════════
#  Mutation round v1.7.6.12 — survivors of the Cosmic Ray run
# ══════════════════════════════════════════════════════════════════════════════
section("B1b. garmin_bulk_fit_reader — mutation round v1.7.6.12")
U16Z, U64 = 0x8B, 0x8F


def _msg(data, wanted=()):
    try:
        fr.parse_fit(data, wanted)
    except fr.FitFormatError as e:
        return str(e)
    return None


# -- the tables: CRC-16/ARC, the base types, the modes ---------------------------------------------------------------------
check("CRC table: 256 entries of CRC-16/ARC (0, 0xC0C1, 0xC181 ... 0x4040)",
      len(fr._CRC_TABLE) == 256 and fr._CRC_TABLE[:3] == [0, 0xC0C1, 0xC181] and fr._CRC_TABLE[255] == 0x4040)
check("_crc16 of '123456789' is the check value of CRC-16/ARC (0xBB3D)", fr._crc16(b"123456789") == 0xBB3D)
check("base types: struct code, size and invalid value of every FIT base type the reader knows",
      fr._BASE == {0: ("B", 1, 0xFF), 1: ("b", 1, 0x7F), 2: ("B", 1, 0xFF), 3: ("h", 2, 0x7FFF), 4: ("H", 2, 0xFFFF),
                   5: ("i", 4, 0x7FFFFFFF), 6: ("I", 4, 0xFFFFFFFF), 8: ("f", 4, None), 9: ("d", 8, None),
                   10: ("B", 1, 0), 11: ("H", 2, 0), 12: ("I", 4, 0), 13: ("B", 1, 0xFF),
                   14: ("q", 8, 0x7FFFFFFFFFFFFFFF), 15: ("Q", 8, 0xFFFFFFFFFFFFFFFF), 16: ("Q", 8, 0)}
      and fr._STRING == 7 and (fr._MODE_SCALAR, fr._MODE_ARRAY, fr._MODE_STRING, fr._MODE_RAW) == (0, 1, 2, 3))

# -- the decoding plan of a definition ---------------------------------------------------------------------------------------
_plan = fr._build_plan([(1, 8, STR), (2, 0, U8), (3, 3, U16), (4, 4, U16), (5, 2, U16), (6, 1, 0x1F)], "<")
check("_build_plan: a string, a field of size 0, a size that is no multiple, an array, a scalar and an unknown base type",
      [(p[0], p[1], p[2], getattr(p[3], "format", None), p[4], p[5]) for p in _plan]
      == [(1, 0, 8, None, None, fr._MODE_STRING), (2, 8, 0, None, None, fr._MODE_RAW), (3, 8, 3, None, None, fr._MODE_RAW),
          (4, 11, 4, "<HH", 0xFFFF, fr._MODE_ARRAY), (5, 15, 2, "<H", 0xFFFF, fr._MODE_SCALAR), (6, 17, 1, None, None, fr._MODE_RAW)])


def _one_message(btype, size, payload, wanted_num=20):
    data = _fit(_file_id() + [_define(1, wanted_num, [(7, size, btype)]), _row(1, payload)])
    return fr.parse_fit(data, {wanted_num}).messages[wanted_num][0][7]


check("arrays: the invalid value of a type becomes None (uint16 0xFFFF; uint16z 0 — a value of 5 and 7 stays)",
      _one_message(U16, 6, struct.pack("<HHH", 0xFFFF, 5, 0xFFFF)) == (None, 5, None)
      and _one_message(U16Z, 6, struct.pack("<HHH", 0, 5, 7)) == (None, 5, 7))
check("arrays: a float that is not a number becomes None", _one_message(F32, 8, struct.pack("<ff", float("nan"), 1.5)) == (None, 1.5))
check("strings: up to the first zero byte, an empty string is None",
      _one_message(STR, 8, b"Fenix 7\x00") == "Fenix 7" and _one_message(STR, 8, b"ab\x00cd\x00\x00\x00") == "ab"
      and _one_message(STR, 8, b"\x00" * 8) is None)

# -- the checks of the whole file ---------------------------------------------------------------------------------------------
_h12 = bytes([12, 0x10]) + struct.pack("<HI", 2132, 0) + b".FIT"
check("a file of exactly 12 bytes with the FIT signature is no 'not_fit' but truncated: it is shorter than header and CRC",
      _msg(_h12).startswith("truncated"))
check("a header of 12 bytes and one byte more: 'shorter than the header'", _msg(_h12 + b"\x00") == "truncated: shorter than the header")
check("the smallest valid file: a 12-byte header and the CRC, 14 bytes, no messages",
      fr.parse_fit(_fit([], header_size=12)) == fr.FitFile(None, None, {}))
_big = _fit(_file_id() + [_define(1, 55, _MON)] + [_mon_row(1, 5000 + 60 * i, (5000 + 60 * i) & 0xFFFF, 60 + i % 7) for i in range(200)])
check("a valid file of more than 256 bytes is read to the end, every record (no length check by identity)",
      len(_big) > 256 and len(fr.parse_fit(_big, {55}).messages[55]) == 200)
check("bytes after the end of the file are named by their number", _msg(_big + b"\x00" * 5, {55}) == "structure: 5 bytes after the end of the file")
_def_arch2 = bytearray(_define(1, 55, [(27, 1, U8)]))
_def_arch2[2] = 2
check("an architecture byte of 2 is refused ('byte order'); 0 and 1 are the two known orders",
      _msg(_fit([bytes(_def_arch2), _row(1, b"\x0A")]), {55}) == "structure: byte order")
_past = _fit([_define(1, 55, [(1, 8, U64)]), _row(1, b"\x01\x02")])
check("a record that runs past the end of the data is named so, before it is decoded",
      _msg(_past, {55}) == "structure: record past the end")

# -- compressed timestamps -----------------------------------------------------------------------------------------------------
def _comp(local, off5, payload):
    return bytes([0x80 | (local << 5) | off5]) + payload


_ts_defs = [_define(1, 55, [(253, 4, U32), (27, 1, U8)]), _define(2, 55, [(27, 1, U8)])]
_c1 = _fit(_file_id() + _ts_defs + [_row(1, struct.pack("<IB", 1000, 60)), _comp(2, 12, b"\x01"), _comp(2, 3, b"\x02"), _comp(2, 3, b"\x03")])
check("compressed timestamps: reference 1000 (low bits 8): offset 12 -> 1004, then a wrap (3 after 12) -> 1027, an equal offset -> 1027 again",
      [m.get(253) for m in fr.parse_fit(_c1, {55}).messages[55]] == [1000, 1004, 1027, 1027])
_c2 = _fit(_file_id() + [_define(1, 55, [(253, 4, U32), (27, 1, U8)]), _define(0, 55, [(27, 1, U8)]), _define(3, 55, [(27, 1, U8)])]
           + [_row(1, struct.pack("<IB", 2000, 60)), _comp(0, 20, b"\x01"), _comp(3, 25, b"\x02")])
check("compressed timestamps: the local type of a compressed header is read from bits 5 and 6 (types 0 and 3)",
      [m.get(253) for m in fr.parse_fit(_c2, {55}).messages[55]] == [2000, 2004, 2009])
_c3 = _fit(_file_id() + [_define(15, 55, [(27, 1, U8)]), _row(15, b"\x07")])
check("local message type 15 is the largest data-record type", [m[27] for m in fr.parse_fit(_c3, {55}).messages[55]] == [7])
check("a compressed record of a wanted message with no reference before it is refused",
      _msg(_fit(_file_id() + [_define(2, 55, [(27, 1, U8)]), _comp(2, 5, b"\x01")]), {55})
      == "structure: compressed timestamp without a reference")
_c4 = _fit([_define(0, 0, [(0, 1, ENUM)]), _comp(0, 1, b"\x20")])
check("a compressed record of a message that is not wanted (the file_id) needs no reference: the file type is read",
      fr.parse_fit(_c4).file_type == 32)
_c5 = _fit(_file_id(32, 1000)[:0] + [_define(1, 55, [(27, 1, U8)]), _row(1, b"\x07")] + _file_id(32, 1000))
check("the file_id is found wherever it stands: a wanted message before it does not take its place",
      (fr.parse_fit(_c5, {55}).file_type, fr.parse_fit(_c5, {55}).time_created) == (32, 1000))

# the timestamp of a message that is not decoded is read from its bytes, at its own offset
_u_defs = lambda fields: [_define(1, 20, fields), _define(2, 55, [(27, 1, U8)])]
_c6 = _fit(_u_defs([(253, 4, U32), (10, 4, U32)]) + [_row(1, struct.pack("<II", 5000, 123456)), _comp(2, 11, b"\x01")])
check("the timestamp is the field 253 of size 4 (the first of two 4-byte fields), also of a message that is not decoded: 5000 + 3",
      [m.get(253) for m in fr.parse_fit(_c6, {55}).messages[55]] == [5003])
_c7 = _fit(_u_defs([(253, 4, U32), (254, 4, U32)]) + [_row(1, struct.pack("<II", 5000, 123456)), _comp(2, 11, b"\x01")])
check("a field 254 of size 4 behind it is not the timestamp", [m.get(253) for m in fr.parse_fit(_c7, {55}).messages[55]] == [5003])
_c8 = _fit(_u_defs([(253, 4, U32), (1, 4, U32)]) + [_row(1, struct.pack("<II", 5000, 123456)), _comp(2, 11, b"\x01")])
check("a field 1 of size 4 behind it is not the timestamp", [m.get(253) for m in fr.parse_fit(_c8, {55}).messages[55]] == [5003])
check("a field 253 of size 2 is no timestamp: a compressed record after it has no reference",
      _msg(_fit(_u_defs([(253, 2, U16), (1, 2, U16)]) + [_row(1, struct.pack("<HH", 7, 8)), _comp(2, 11, b"\x01")]), {55})
      == "structure: compressed timestamp without a reference")
check("a field 253 of size 8 is no timestamp either",
      _msg(_fit(_u_defs([(253, 8, U64)]) + [_row(1, struct.pack("<Q", 7)), _comp(2, 11, b"\x01")]), {55})
      == "structure: compressed timestamp without a reference")
check("an invalid timestamp (0xFFFFFFFF) is no reference",
      _msg(_fit(_u_defs([(253, 4, U32)]) + [_row(1, struct.pack("<I", 0xFFFFFFFF)), _comp(2, 11, b"\x01")]), {55})
      == "structure: compressed timestamp without a reference")
_c9 = _fit(_file_id() + _ts_defs + [_row(1, struct.pack("<IB", 1000, 60)), _row(1, struct.pack("<IB", 0xFFFFFFFF, 61)), _comp(2, 10, b"\x01")])
check("a record with an invalid timestamp in between keeps the reference: 1000, None, then 1002",
      [m.get(253) for m in fr.parse_fit(_c9, {55}).messages[55]] == [1000, None, 1002])

# -- the arithmetic of compressed timestamps with bits that overlap (a wrap with offset 4 after 12, an offset far above the last) --------
_c10 = _fit(_file_id() + _ts_defs + [_row(1, struct.pack("<IB", 1000, 60)), _comp(2, 12, b"\x01"), _comp(2, 4, b"\x02"),
                                     _comp(2, 4, b"\x03"), _comp(2, 25, b"\x04")])
check("compressed timestamps: 1000, +12 -> 1004, a wrap to offset 4 -> 1028, equal offset -> 1028, offset 25 after 4 -> 1049",
      [m.get(253) for m in fr.parse_fit(_c10, {55}).messages[55]] == [1000, 1004, 1028, 1028, 1049])

# -- the timestamp of a message that is not decoded is read at ITS offset, wherever the record stands in the file ---------------------
for _k in range(4):
    _pad = [_define(3, 21, [(1, 1, U8)])] + [_row(3, b"\x00")] * _k
    _c11 = _fit(_pad + [_define(1, 20, [(10, 3, 0x0D), (253, 4, U32)]), _define(2, 55, [(27, 1, U8)]),
                        _row(1, b"abc" + struct.pack("<I", 5000)), _comp(2, 11, b"\x01")])
    check(f"the timestamp at offset 3 of a message that is not decoded gives the reference (record position shifted by {_k})",
          [m.get(253) for m in fr.parse_fit(_c11, {55}).messages[55]] == [5003])

# -- strings that fill their field completely (no terminating zero), at different places in the file --------------------------------
_s_recs = [_row(1, b"ABCDEFGH" + struct.pack("<H", 0x4142)) for _ in range(5)]
_s_file = _fit(_file_id() + [_define(1, 20, [(7, 8, STR), (8, 2, U16)])] + _s_recs)
check("a string field without a terminating zero is exactly its size long, in every record",
      [m[7] for m in fr.parse_fit(_s_file, {20}).messages[20]] == ["ABCDEFGH"] * 5)

# -- the whole-file checks: signature smaller or larger than '.FIT', header CRC wrong in both directions, short files ---------------
_sig_lo = bytearray(_h12)
_sig_lo[8:12] = b"\x00\x00\x00\x00"
_sig_hi = bytearray(_h12)
_sig_hi[8:12] = b"ZZZZ"
check("a signature that sorts before or after '.FIT' is 'not_fit' either way",
      _msg(bytes(_sig_lo)) == "not_fit" and _msg(bytes(_sig_hi)) == "not_fit")
_good14 = _fit(_file_id())
_hc = struct.unpack_from("<H", _good14, 12)[0]
check("a stored header CRC that is wrong (one above, one below the right value) is refused; the right one and 0 (unset) are accepted",
      _hc not in (0, 0xFFFF)
      and _msg(_fit(_file_id(), header_crc=_hc + 1)) == "crc: header" and _msg(_fit(_file_id(), header_crc=_hc - 1)) == "crc: header"
      and _msg(_fit(_file_id(), header_crc=_hc)) is None and _msg(_fit(_file_id(), header_crc=False)) is None)
_h14 = _fit([], header_size=14)
check("a header of 14 bytes with one byte after it is 'shorter than the header'", _msg(_h14[:15]) == "truncated: shorter than the header")
_empty12 = _fit([], header_size=12)
check("bytes after the end are counted as a difference (30 after a 14-byte file)",
      _msg(_empty12 + b"\x00" * 30) == "structure: 30 bytes after the end of the file")
check("a definition that ends exactly at the end of the data is fine (a file may end with one)",
      _msg(_fit(_file_id() + [_define(1, 55, [(27, 1, U8)])]), {55}) is None)
check("a definition whose last field runs into the CRC is 'definition past the end'",
      _msg(_fit([bytes([0x41, 0, 0]) + struct.pack("<H", 55) + bytes([1, 5])]), {55}) == "structure: definition past the end")

summary()
