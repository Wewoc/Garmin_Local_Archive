#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
garmin_bulk_fit_reader.py

Reader for the FIT files of the Garmin GDPR export — bytes in, messages out.
Part of the bulk store (v1.7.6); the module that writes the store is
garmin_bulk_writer.py. This module only reads and never writes anything.

Leaf node: standard library only (struct, typing), no project imports, no
garmin_config. Replaceable: everything the rest of the bulk store needs from
FIT files goes through parse_fit(), so a different parser (e.g. the one of the
FIT pipeline planned for v1.8) can take its place.

What it does
  - checks the file as a whole before reading a single record: signature,
    header size, size given in the header against the real length, header CRC
    (only when set) and file CRC. A file that fails any check is rejected as a
    whole with FitFormatError — never half-read.
  - walks definition and data messages (both byte orders, developer fields
    skipped, compressed timestamp headers resolved) and decodes the messages
    whose global number the caller asked for.
  - returns file_id.type and file_id.time_created for every file.

What it does not do (belongs to the normalisation step)
  - no conversion of FIT seconds to Unix time (the FIT epoch offset is applied
    there), no plausibility checks (a heart rate of 0 is a valid uint8 here),
    no 16-bit timestamp completion, no assignment to days.

Values
  A field is keyed by its field number. The invalid value of its base type
  (0xFF for uint8, 0xFFFF for uint16, 0xFFFFFFFF for uint32, 0 for the z types,
  NaN for floats, ...) becomes None. Arrays become tuples, strings are cut at
  the first NUL (empty -> None). A field whose size does not fit its base type,
  or whose base type is unknown, is returned as raw bytes.

Compressed timestamp headers
  The timestamp of such a record is computed from the last full timestamp
  (field 253 of any message) and the 5-bit offset, as the FIT SDK defines it,
  and stored under field 253 of the returned record. Without a reference
  timestamp a wanted record is rejected as "structure". Not present in the
  export this was built against (checked on all 34,875 files); covered by
  synthetic files only.

Privacy
  The input is bytes: no file name ever reaches this module, so none can appear
  in an error message or log. (The entries of the export are named after the
  e-mail address of the account; callers must not print them either.)

Public API:
  parse_fit(data, wanted=()) -> FitFile
  FitFile            — NamedTuple: file_type, time_created, messages
  FitFormatError     — .reason is one of "not_fit", "truncated", "crc", "structure"
"""

import struct
from typing import NamedTuple


class FitFormatError(Exception):
    """The input is not a readable FIT file. `reason` is a short code the
    caller can count: "not_fit" (no FIT signature / too short to be one),
    "truncated" (shorter than the header says), "crc" (header or file CRC
    wrong), "structure" (inconsistent content, e.g. trailing bytes, an
    undefined local message type, a record running past the data)."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class FitFile(NamedTuple):
    """Result of parse_fit().

    file_type     file_id.type (e.g. 32 = monitoring), None if absent/invalid
    time_created  file_id.time_created in raw FIT seconds, None if absent/invalid
    messages      {global message number: [ {field number: value}, ... ]} — only
                  the numbers the caller asked for, only those that occur,
                  records in file order
    """
    file_type: int | None
    time_created: int | None
    messages: dict


# ══════════════════════════════════════════════════════════════════════════════
#  CRC-16 (CRC-16/ARC, as used by FIT)
# ══════════════════════════════════════════════════════════════════════════════

def _make_crc_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        table.append(c)
    return table


_CRC_TABLE = _make_crc_table()


def _crc16(data):
    crc = 0
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


# ══════════════════════════════════════════════════════════════════════════════
#  Base types
# ══════════════════════════════════════════════════════════════════════════════

# base type number (low 5 bits of the type byte) -> (struct code, size, invalid value)
# Float types have no invalid integer; NaN is mapped to None in _decode_record().
_BASE = {
    0:  ("B", 1, 0xFF),                  # enum
    1:  ("b", 1, 0x7F),                  # sint8
    2:  ("B", 1, 0xFF),                  # uint8
    3:  ("h", 2, 0x7FFF),                # sint16
    4:  ("H", 2, 0xFFFF),                # uint16
    5:  ("i", 4, 0x7FFFFFFF),            # sint32
    6:  ("I", 4, 0xFFFFFFFF),            # uint32
    8:  ("f", 4, None),                  # float32
    9:  ("d", 8, None),                  # float64
    10: ("B", 1, 0),                     # uint8z
    11: ("H", 2, 0),                     # uint16z
    12: ("I", 4, 0),                     # uint32z
    13: ("B", 1, 0xFF),                  # byte
    14: ("q", 8, 0x7FFFFFFFFFFFFFFF),    # sint64
    15: ("Q", 8, 0xFFFFFFFFFFFFFFFF),    # uint64
    16: ("Q", 8, 0),                     # uint64z
}
_STRING = 7

_MODE_SCALAR, _MODE_ARRAY, _MODE_STRING, _MODE_RAW = 0, 1, 2, 3

_STRUCTS = {}


def _struct_for(fmt):
    st = _STRUCTS.get(fmt)
    if st is None:
        st = _STRUCTS[fmt] = struct.Struct(fmt)
    return st


def _build_plan(fields, endian):
    """Decoding plan of one definition: [(number, offset, size, Struct, invalid, mode)]."""
    plan = []
    off = 0
    for num, size, btype in fields:
        kind = btype & 0x1F
        base = _BASE.get(kind)
        if kind == _STRING:
            plan.append((num, off, size, None, None, _MODE_STRING))
        elif base is None or size == 0 or size % base[1]:
            plan.append((num, off, size, None, None, _MODE_RAW))
        else:
            code, tsize, invalid = base
            count = size // tsize
            plan.append((num, off, size, _struct_for(endian + code * count), invalid,
                         _MODE_SCALAR if count == 1 else _MODE_ARRAY))
        off += size
    return plan


def _decode_record(plan, data, base):
    rec = {}
    for num, off, size, st, invalid, mode in plan:
        p = base + off
        if mode == _MODE_SCALAR:
            v = st.unpack_from(data, p)[0]
            rec[num] = None if (v == invalid or v != v) else v
        elif mode == _MODE_ARRAY:
            rec[num] = tuple(None if (v == invalid or v != v) else v for v in st.unpack_from(data, p))
        elif mode == _MODE_STRING:
            rec[num] = bytes(data[p:p + size]).split(b"\x00", 1)[0].decode("utf-8", "replace") or None
        else:
            rec[num] = bytes(data[p:p + size])
    return rec


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def parse_fit(data, wanted=()) -> FitFile:
    """
    Parses one FIT file given as bytes.

    Parameters
    ----------
    data   : bytes-like — the complete file
    wanted : iterable of int — global message numbers whose records are returned
             (default: none; file_id is always read for file_type/time_created)

    Returns
    -------
    FitFile

    Raises
    ------
    FitFormatError — the file is rejected as a whole (see the class docstring)
    """
    if not isinstance(data, bytes):
        data = bytes(data)
    wanted = frozenset(wanted)
    n = len(data)

    # ── whole-file checks, before any record is read ──────────────────────────
    if n < 12 or data[8:12] != b".FIT":
        raise FitFormatError("not_fit")
    header_size = data[0]
    if header_size not in (12, 14):
        raise FitFormatError("structure", f"header size {header_size}")
    if n < header_size + 2:
        raise FitFormatError("truncated", "shorter than the header")
    data_size = struct.unpack_from("<I", data, 4)[0]
    needed = header_size + data_size + 2
    if needed > n:
        raise FitFormatError("truncated", f"{n} of {needed} bytes")
    if needed < n:
        raise FitFormatError("structure", f"{n - needed} bytes after the end of the file")
    if header_size == 14:
        stored_header_crc = struct.unpack_from("<H", data, 12)[0]
        if stored_header_crc != 0 and stored_header_crc != _crc16(data[:12]):
            raise FitFormatError("crc", "header")
    if struct.unpack_from("<H", data, n - 2)[0] != _crc16(memoryview(data)[:n - 2]):
        raise FitFormatError("crc", "file")

    # ── walk the messages ─────────────────────────────────────────────────────
    decode_numbers = wanted | {0}
    defs = {}                     # local type -> (global number, record size, plan, ts offset, ts struct)
    messages = {}
    file_type = time_created = None
    have_file_id = False
    last_ts = None
    pos = header_size
    end = n - 2
    try:
        while pos < end:
            h = data[pos]
            pos += 1

            if h & 0x40 and not h & 0x80:                    # definition message
                arch = data[pos + 1]
                if arch > 1:
                    raise FitFormatError("structure", "byte order")
                endian = ">" if arch else "<"
                gmn = struct.unpack_from(endian + "H", data, pos + 2)[0]
                nfields = data[pos + 4]
                p = pos + 5
                fields = []
                for _ in range(nfields):
                    fields.append((data[p], data[p + 1], data[p + 2]))
                    p += 3
                size = sum(f[1] for f in fields)
                if h & 0x20:                                 # developer fields: counted, never decoded
                    for _ in range(data[p]):
                        size += data[p + 2]
                        p += 3
                    p += 1
                if p > end:
                    raise FitFormatError("structure", "definition past the end")
                ts_off, off = None, 0
                for num, fsize, _bt in fields:
                    if num == 253 and fsize == 4:
                        ts_off = off
                    off += fsize
                plan = _build_plan(fields, endian) if gmn in decode_numbers else None
                defs[h & 0x0F] = (gmn, size, plan, ts_off, _struct_for(endian + "I"))
                pos = p
                continue

            compressed = bool(h & 0x80)
            d = defs.get((h >> 5) & 0x03 if compressed else h & 0x0F)
            if d is None:
                raise FitFormatError("structure", "record for an undefined local message type")
            gmn, size, plan, ts_off, ts_struct = d
            if pos + size > end:
                raise FitFormatError("structure", "record past the end")

            ts = None
            if compressed:
                if last_ts is not None:
                    last_off, off5 = last_ts & 0x1F, h & 0x1F
                    ts = last_ts + (off5 - last_off if off5 >= last_off else 0x20 - last_off + off5)
                    last_ts = ts
                elif plan is not None and gmn in wanted:
                    raise FitFormatError("structure", "compressed timestamp without a reference")

            rec = None
            if plan is not None:
                rec = _decode_record(plan, data, pos)
                if compressed and ts is not None:
                    rec[253] = ts
                if gmn == 0 and not have_file_id:
                    have_file_id = True
                    file_type, time_created = rec.get(0), rec.get(4)
                if gmn in wanted:
                    messages.setdefault(gmn, []).append(rec)

            if not compressed and ts_off is not None:       # full timestamp: new reference
                v = rec.get(253) if rec is not None and 253 in rec else ts_struct.unpack_from(data, pos + ts_off)[0]
                if v is not None and v != 0xFFFFFFFF:
                    last_ts = v
            pos += size
    except (IndexError, struct.error) as e:
        raise FitFormatError("structure", "record or definition past the end") from e

    return FitFile(file_type, time_created, messages)
