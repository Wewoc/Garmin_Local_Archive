#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
tests/fit_builder.py — builds FIT files from scratch for the bulk store tests (v1.7.6)

Shared by test_bulk_fit_reader.py, test_bulk_import.py and any later test that needs
FIT bytes. No import of a project module on purpose: the CRC is computed by an
independent implementation (the nibble algorithm of the FIT SDK), so the tests cannot
share a bug with the table version in garmin_bulk_fit_reader.py.
"""

import struct

_NIB = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]

# base type bytes as they stand in a definition (0x80 = endian ability flag)
ENUM, U8, S16, U16, U32, STR, F32, U8Z, U32Z = 0x00, 0x02, 0x83, 0x84, 0x86, 0x07, 0x88, 0x0A, 0x8C

FIT_EPOCH_OFFSET = 631065600          # 1989-12-31 00:00 UTC in Unix seconds


def crc(data):
    value = 0
    for b in data:
        tmp = _NIB[value & 0xF]
        value = (value >> 4) & 0x0FFF
        value = value ^ tmp ^ _NIB[b & 0xF]
        tmp = _NIB[value & 0xF]
        value = (value >> 4) & 0x0FFF
        value = value ^ tmp ^ _NIB[(b >> 4) & 0xF]
    return value


def build_fit(records, header_size=14, header_crc=True):
    """The bytes of a FIT file around the given records.
    header_crc: True = correct, False = 0 (unset), int = that (wrong) value."""
    body = b"".join(records)
    head = bytes([header_size, 0x10]) + struct.pack("<HI", 2132, len(body)) + b".FIT"
    if header_size == 14:
        value = crc(head) if header_crc is True else (0 if header_crc is False else header_crc)
        head += struct.pack("<H", value)
    raw = head + body
    return raw + struct.pack("<H", crc(raw))


def define(local, gmn, fields, big=False, dev=()):
    """A definition message: local type, global number, fields [(number, size, base type)]."""
    e = ">" if big else "<"
    out = bytes([0x40 | local | (0x20 if dev else 0), 0, 1 if big else 0])
    out += struct.pack(e + "H", gmn) + bytes([len(fields)])
    out += b"".join(bytes(f) for f in fields)
    if dev:
        out += bytes([len(dev)]) + b"".join(bytes(d) for d in dev)
    return out


def row(local, payload):
    """A data message of a local type."""
    return bytes([local]) + payload


def file_id(ftype=32, tcreated=1000, serial=7, local=0):
    """The two records of a file_id message: type, serial number and creation time (raw FIT seconds)."""
    return [define(local, 0, [(0, 1, ENUM), (3, 4, U32Z), (4, 4, U32)]),
            row(local, bytes([ftype]) + struct.pack("<II", serial, tcreated))]


MON = [(253, 4, U32), (26, 2, U16), (27, 1, U8)]


def mon_row(local, ts, ts16, hr):
    return row(local, struct.pack("<IHB", ts, ts16, hr))


def monitoring_fit(unix_created, samples, serial=7, full_gap=600):
    """A monitoring file (type 32): file_id plus message 55 with heart-rate samples.

    samples: [(unix seconds, bpm), ...] in file order. The first sample carries a full
    timestamp, the others the 16-bit timestamp only (as the real files do); after a pause of
    more than `full_gap` seconds a full timestamp is written again, as a device does (a 16-bit
    timestamp cannot carry a step of more than about nine hours). A bpm of None is written as
    'no heart rate' (0xFF, invalid)."""
    e = FIT_EPOCH_OFFSET
    records = file_id(32, unix_created - e, serial)
    records.append(define(1, 55, [(253, 4, U32), (27, 1, U8)]))
    records.append(define(2, 55, [(26, 2, U16), (27, 1, U8)]))
    previous = None
    for unix, bpm in samples:
        value = 0xFF if bpm is None else bpm
        if previous is None or unix - previous > full_gap:
            records.append(row(1, struct.pack("<IB", unix - e, value)))
        else:
            records.append(row(2, struct.pack("<HB", (unix - e) & 0xFFFF, value)))
        previous = unix
    return build_fit(records)


def simple_fit(ftype, unix_created, serial=7):
    """A file that holds only a file_id of the given type (stands in for sleep, HRV, activity ... files)."""
    return build_fit(file_id(ftype, unix_created - FIT_EPOCH_OFFSET, serial))
