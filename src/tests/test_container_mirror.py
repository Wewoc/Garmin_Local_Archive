#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_container_mirror.py — garmin_container, garmin_mirror

Run from the project folder:
    python tests/test_container_mirror.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from gla_testenv import _TMPDIR  # sets up the environment; must precede garmin_* imports

# Section C registers a stub 'garmin_normalizer' with setdefault(); import the real one
# first so the stub never replaces it (the old single file had already loaded it).
import garmin_normalizer  # noqa: F401
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  4g. garmin_container, garmin_mirror — failure paths and hand-built containers
#      (v1.7.4.0.2). Containers are built from hand-made sections so single
#      parts (missing section, bad bytes, tampering) can be broken on purpose.
# ══════════════════════════════════════════════════════════════════════════════
section("4g. garmin_container, garmin_mirror — failure paths, crafted containers")
import struct as _struct
import types as _types4
import garmin_container as _gc4
import garmin_mirror as _mir4

# lock() imports version.APP_VERSION, which is not on the test path. Section C
# below registers its own stub with setdefault() and later changes that very
# object, so this block removes its temporary stub again at the end.
_ver4_added = "version" not in sys.modules
if _ver4_added:
    _ver4 = _types4.ModuleType("version")
    _ver4.APP_VERSION = "test"
    sys.modules["version"] = _ver4

_M4 = _TMPDIR / "mir4g"
shutil.rmtree(_M4, ignore_errors=True)
_M4.mkdir()
_M4_EMPTY_SRC = _M4 / "empty_src"
_M4_EMPTY_SRC.mkdir()


def _craft_container(path, sections, password="pw"):
    """Pack hand-made {section: {relative path: bytes}} into a real container."""
    def _fake_collect(_src):
        data = {s: {} for s in _gc4._SECTIONS}
        data.update(sections)
        data["_errors"] = 0
        return data
    with patch.object(_gc4, "_collect_sections", _fake_collect):
        return _gc4.lock(_M4_EMPTY_SRC, path, password)


def _flip_byte(src, dst, index):
    """Copy a container and flip all bits of one byte (index < 0 counts from the end)."""
    data = bytearray(Path(src).read_bytes())
    data[index] ^= 0xFF
    Path(dst).write_bytes(bytes(data))


_QL4 = json.dumps({"days": [{"date": "2024-01-01", "quality": "high"}]}).encode("utf-8")
_RAW_A = "garmin_data/raw/garmin_raw_2024-01-01.json"
_RAW_BIN = "garmin_data/raw/binary.bin"
_CTX_A = "context_data/weather/raw/2024-01-01.json"
_good4 = _M4 / "good.gla"
_r = _craft_container(_good4, {
    "quality_log": {"garmin_data/log/quality_log.json": _QL4,
                    "garmin_data/log/device_table.json": b"[]"},
    "raw":         {_RAW_A: b'{"a": 1}', _RAW_BIN: b"\x00\xff\x10"},
    "context":     {_CTX_A: b'{"t": 5}'},
})
check("setup: hand-built container is created and recognised",
      _r["ok"] == True and _gc4.is_container(_good4))

# -- lock: failure paths ---------------------------------------------------------
_r = _gc4.lock(_M4 / "does_not_exist", _M4 / "none.gla", "pw")
check("lock: missing source folder -> ok False, one error, no container",
      _r["ok"] == False and _r["errors"] == 1 and not (_M4 / "none.gla").exists())
(_M4 / "a_file").write_text("not a folder", encoding="utf-8")
_r = _gc4.lock(_M4 / "a_file", _M4 / "none.gla", "pw")
check("lock: source is a file, not a folder -> ok False",
      _r["ok"] == False and _r["errors"] == 1)

with patch("os.replace", side_effect=OSError("locked")):
    _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "swapfail.gla", "pw")
check("lock: failing swap -> ok False, nothing packed, no container, no .tmp left",
      _r["ok"] == False and _r["files_packed"] == 0
      and not (_M4 / "swapfail.gla").exists() and list(_M4.glob("*.tmp")) == [])
with patch("os.replace", side_effect=OSError("locked")), \
     patch.object(Path, "unlink", side_effect=OSError("also locked")):
    _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "swapfail2.gla", "pw")
check("lock: failing swap and failing cleanup -> no crash, ok False", _r["ok"] == False)
for _t in _M4.glob("*.tmp"):
    _t.unlink()

# -- unlock_meta: hand-built broken containers ------------------------------------
_c = _M4 / "no_ql.gla"
_craft_container(_c, {"raw": {_RAW_A: b"{}"}})
_u = _gc4.unlock_meta(_c, "pw")
check("unlock_meta: container without a quality_log section -> error says so",
      _u["ok"] == False and "quality_log section missing" in _u["error"])

_c = _M4 / "ql_missing_file.gla"
_craft_container(_c, {"quality_log": {"garmin_data/log/device_table.json": b"[]"}})
_u = _gc4.unlock_meta(_c, "pw")
check("unlock_meta: quality_log section without quality_log.json -> error says so",
      _u["ok"] == False and "not found in section" in _u["error"])

_c = _M4 / "ql_bad_json.gla"
_craft_container(_c, {"quality_log": {"garmin_data/log/quality_log.json": b"{not json"}})
_u = _gc4.unlock_meta(_c, "pw")
check("unlock_meta: quality_log.json that is not JSON -> parse error",
      _u["ok"] == False and "JSON parse failed" in _u["error"])

_magic, _salt, _master, _hdr, _data_off = _gc4._open_and_verify(_good4, "pw")
_idx = _hdr["section_index"]
_ql_mid = _data_off + _idx["quality_log"]["offset"] + _idx["quality_log"]["length"] // 2
_flip_byte(_good4, _M4 / "ql_tampered.gla", _ql_mid)
_u = _gc4.unlock_meta(_M4 / "ql_tampered.gla", "pw")
check("unlock_meta: tampered quality_log section -> decrypt error, no crash",
      _u["ok"] == False and "decrypt failed" in _u["error"])

_flip_byte(_good4, _M4 / "bad_version.gla", 4)       # format version byte
_u = _gc4.unlock_meta(_M4 / "bad_version.gla", "pw")
check("unlock_meta: unsupported format version -> clear error",
      _u["ok"] == False and "Unsupported container format version" in _u["error"])

_hj = b"{this header is not json"
_salt2 = b"\x01" * 16
_hm = _gc4._authenticate_header(_gc4._derive_master("pw", _salt2), _hj)
(_M4 / "bad_header.gla").write_bytes(
    _gc4._MAGIC + bytes([_gc4._FORMAT_VER]) + _salt2 + _hm
    + _struct.pack(">I", len(_hj)) + _hj)
_u = _gc4.unlock_meta(_M4 / "bad_header.gla", "pw")
check("unlock_meta: valid HMAC but header that is not JSON -> parse error",
      _u["ok"] == False and "Header JSON parse failed" in _u["error"])
check("list_files: header that is not JSON -> [] (no crash)",
      _gc4.list_files(_M4 / "bad_header.gla", "raw") == [])

# -- list_files ---------------------------------------------------------------------
(_M4 / "plain.txt").write_text("hello", encoding="utf-8")
check("list_files: file that is not a container -> []",
      _gc4.list_files(_M4 / "plain.txt", "raw") == [])
check("list_files: missing file -> []",
      _gc4.list_files(_M4 / "missing.gla", "raw") == [])
check("list_files: section that is not in the container -> []",
      _gc4.list_files(_good4, "summary") == [])
check("list_files: lists the stored file names of a section",
      sorted(_gc4.list_files(_good4, "raw")) == sorted([_RAW_A, _RAW_BIN]))

# -- fulfill_order --------------------------------------------------------------------
check("fulfill_order: empty order -> {}", _gc4.fulfill_order(_good4, "pw", {}) == {})
_f = _gc4.fulfill_order(_good4, "pw", {
    "raw": [_RAW_A, _RAW_BIN, "garmin_data/raw/not_there.json"],
    "context": [],
    "unknown_section": ["x"],
})
check("fulfill_order: delivers the requested files, bytes unchanged (incl. binary)",
      _f == {_RAW_A: b'{"a": 1}', _RAW_BIN: b"\x00\xff\x10"})
check("fulfill_order: a file that is not in the section is simply missing from the result",
      "garmin_data/raw/not_there.json" not in _f)
check("fulfill_order: wrong password -> {}", _gc4.fulfill_order(_good4, "wrong", {"raw": [_RAW_A]}) == {})
check("fulfill_order: bad format version -> {}",
      _gc4.fulfill_order(_M4 / "bad_version.gla", "pw", {"raw": [_RAW_A]}) == {})

_raw_mid = _data_off + _idx["raw"]["offset"] + _idx["raw"]["length"] // 2
_flip_byte(_good4, _M4 / "raw_tampered.gla", _raw_mid)
_f = _gc4.fulfill_order(_M4 / "raw_tampered.gla", "pw", {"raw": [_RAW_A], "context": [_CTX_A]})
check("fulfill_order: a tampered section delivers nothing, other sections still arrive",
      _RAW_A not in _f and _f.get(_CTX_A) == b'{"t": 5}')

# -- is_container -----------------------------------------------------------------------
check("is_container: missing file -> False", _gc4.is_container(_M4 / "missing.gla") == False)
check("is_container: a folder -> False", _gc4.is_container(_M4) == False)
check("is_container: plain text file -> False", _gc4.is_container(_M4 / "plain.txt") == False)
check("is_container: genuine container -> True", _gc4.is_container(_good4) == True)
with patch("builtins.open", side_effect=PermissionError("denied")):
    check("is_container: unreadable file -> False, no crash", _gc4.is_container(_good4) == False)

# -- _classify_file and _collect_sections ----------------------------------------------
check("_classify_file: empty path -> None", _gc4._classify_file(()) is None)
check("_classify_file: quality_log and device_table go to quality_log",
      _gc4._classify_file(("garmin_data", "log", "quality_log.json")) == "quality_log"
      and _gc4._classify_file(("garmin_data", "log", "device_table.json")) == "quality_log")
check("_classify_file: other files in the log folder are not packed",
      _gc4._classify_file(("garmin_data", "log", "other.json")) is None)
check("_classify_file: raw, summary, source and context sections",
      _gc4._classify_file(("garmin_data", "raw", "a.json")) == "raw"
      and _gc4._classify_file(("garmin_data", "summary", "a.json")) == "summary"
      and _gc4._classify_file(("garmin_data", "source", "a.json")) == "source"
      and _gc4._classify_file(("context_data", "weather", "raw", "a.json")) == "context")
check("_classify_file: unknown top-level files are not packed",
      _gc4._classify_file(("README.txt",)) is None
      and _gc4._classify_file(("garmin_data", "backup", "x.zip")) is None)

_tree = _M4 / "tree"
for _rel, _txt in {
    "garmin_data/log/quality_log.json": "{}",
    "garmin_data/log/device_table.json": "[]",
    "garmin_data/log/other.json": "not packed",
    "garmin_data/raw/a.json": "raw a",
    "garmin_data/raw/bad.json": "unreadable",
    "garmin_data/raw/__pycache__/junk.json": "excluded folder",
    "garmin_data/summary/s.json": "summary",
    "garmin_data/source/src.json": "source",
    "context_data/weather/raw/c.json": "context",
    "garmin_token/secret.enc": "never packed",
    "README.txt": "not packed",
}.items():
    _p = _tree / _rel
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(_txt, encoding="utf-8")
_orig_read_bytes = Path.read_bytes


def _read_bytes_except_bad(self):
    if self.name == "bad.json":
        raise OSError("locked")
    return _orig_read_bytes(self)


with patch.object(Path, "read_bytes", _read_bytes_except_bad):
    _sec = _gc4._collect_sections(_tree)
check("_collect_sections: each file lands in its section with forward-slash keys",
      set(_sec["quality_log"]) == {"garmin_data/log/quality_log.json",
                                   "garmin_data/log/device_table.json"}
      and set(_sec["summary"]) == {"garmin_data/summary/s.json"}
      and set(_sec["source"]) == {"garmin_data/source/src.json"}
      and set(_sec["context"]) == {"context_data/weather/raw/c.json"})
check("_collect_sections: an unreadable file is counted, the others are still packed",
      _sec["_errors"] == 1 and set(_sec["raw"]) == {"garmin_data/raw/a.json"})
_all_keys = [k for s in _gc4._SECTIONS for k in _sec[s]]
check("_collect_sections: excluded folders, token folder and unrelated files are not packed",
      not any("__pycache__" in k or "garmin_token" in k or "README" in k or "other.json" in k
              for k in _all_keys))

# Fixed contract (ROADMAP v1.7.4.3, Fall 3): a leftover .tmp file in raw/ or
# summary/ (left by an aborted writer.write_day()) is never packed into the
# container — a real .json file in the same folder is still packed, to make
# sure the new filter does not reach too wide.
_tree2 = _M4 / "tree_tmp"
(_tree2 / "garmin_data" / "raw").mkdir(parents=True)
(_tree2 / "garmin_data" / "summary").mkdir(parents=True)
(_tree2 / "garmin_data" / "raw" / "garmin_raw_2024-01-01.tmp").write_text("half", encoding="utf-8")
(_tree2 / "garmin_data" / "summary" / "garmin_2024-01-01.tmp").write_text("half", encoding="utf-8")
(_tree2 / "garmin_data" / "raw" / "garmin_raw_2024-01-02.json").write_text("{}", encoding="utf-8")
(_tree2 / "garmin_data" / "summary" / "garmin_2024-01-02.json").write_text("{}", encoding="utf-8")
_sec2 = _gc4._collect_sections(_tree2)
check("container: a stray .tmp in raw/ is not packed into the raw section",
      "garmin_data/raw/garmin_raw_2024-01-01.tmp" not in _sec2["raw"])
check("container: a stray .tmp in summary/ is not packed into the summary section",
      "garmin_data/summary/garmin_2024-01-01.tmp" not in _sec2["summary"])
check("container: a real .json file next to the stray .tmp is still packed (filter is not too wide)",
      "garmin_data/raw/garmin_raw_2024-01-02.json" in _sec2["raw"]
      and "garmin_data/summary/garmin_2024-01-02.json" in _sec2["summary"])

# -- garmin_mirror ----------------------------------------------------------------------
check("is_reachable: a value that is not a path -> False, no crash",
      _mir4.is_reachable(12345) == False)

if _ver4_added:
    del sys.modules["version"]

# ══════════════════════════════════════════════════════════════════════════════
#  C. garmin_mirror (v1.5.6.1 — Container-Modell)
# ══════════════════════════════════════════════════════════════════════════════
section("C. garmin_mirror (v1.5.6.1)")
import garmin_mirror as mirror
import garmin_container as _gc
importlib.reload(mirror)

# is_reachable — leer / None → False
check("is_reachable: empty string → False",  mirror.is_reachable("") == False)
check("is_reachable: None → False",          mirror.is_reachable(None) == False)

# is_reachable — Pfad dessen Parent existiert → True (Container muss noch nicht existieren)
_mir_parent = Path(tempfile.mkdtemp(prefix="garmin_mirror_parent_"))
_mir_gla    = _mir_parent / "mirror.gla"
check("is_reachable: parent exists → True",  mirror.is_reachable(_mir_gla) == True)

# is_reachable — Parent existiert nicht → False
check("is_reachable: missing parent → False",
      mirror.is_reachable(_mir_parent / "nonexistent" / "mirror.gla") == False)

# run_mirror — source nicht vorhanden → ok=False
_bad_src = _TMPDIR / "nonexistent_source"
_result_bad = mirror.run_mirror(_bad_src, _mir_gla, "test-pw")
check("run_mirror: missing source → ok=False",  _result_bad["ok"] == False)
check("run_mirror: missing source → errors=1",  _result_bad["errors"] == 1)
# v1.6.5.7 — Netz 3: Ursache muss im Rückgabewert stehen, nicht nur im Log
check("run_mirror: missing source → error field present",
      bool(_result_bad.get("error")))

# run_mirror — echte Quelle → Container entsteht
# sys.modules stubs: version + garmin_normalizer liegen nicht im garmin/-Path
import types as _types
_ver_stub  = _types.ModuleType("version");           _ver_stub.APP_VERSION = "test"
_norm_stub = _types.ModuleType("garmin_normalizer"); _norm_stub.CURRENT_SCHEMA_VERSION = 2
sys.modules.setdefault("version",           _ver_stub)
sys.modules.setdefault("garmin_normalizer", _norm_stub)

_mir_src = Path(tempfile.mkdtemp(prefix="garmin_mirror_src_"))
(_mir_src / "garmin_data" / "log").mkdir(parents=True)
(_mir_src / "garmin_data" / "raw" / "2024-01-15").mkdir(parents=True)
(_mir_src / "context_data" / "weather" / "raw").mkdir(parents=True)
(_mir_src / "garmin_token").mkdir()
import json as _json
(_mir_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": [{"date": "2024-01-15", "quality": "high"}]}),
    encoding="utf-8"
)
(_mir_src / "garmin_data" / "raw" / "2024-01-15" / "garmin_raw_2024-01-15.json").write_text(
    _json.dumps({"hr": 60, "source": "api"}), encoding="utf-8"
)
(_mir_src / "context_data" / "weather" / "raw" / "2024-01-15.json").write_text(
    _json.dumps({"temp": 5}), encoding="utf-8"
)
(_mir_src / "garmin_token" / "secret.enc").write_text("should_not_appear", encoding="utf-8")

_result_ok = mirror.run_mirror(_mir_src, _mir_gla, "test-pw")
check("run_mirror: returns dict",          isinstance(_result_ok, dict))
check("run_mirror: ok=True",               _result_ok["ok"] == True)
check("run_mirror: files_packed > 0",      _result_ok.get("files_packed", 0) > 0)
check("run_mirror: errors=0",              _result_ok.get("errors", 0) == 0)
check("run_mirror: container created",     _mir_gla.exists())
check("run_mirror: is valid container",    _gc.is_container(_mir_gla))

# garmin_token nie im Container
_raw_listed = _gc.list_files(_mir_gla, "raw")
_ctx_listed = _gc.list_files(_mir_gla, "context")
check("run_mirror: garmin_token not in raw",
      not any("garmin_token" in p for p in _raw_listed))
check("run_mirror: garmin_token not in context",
      not any("garmin_token" in p for p in _ctx_listed))

# Aufräumen
shutil.rmtree(_mir_src,    ignore_errors=True)
shutil.rmtree(_mir_parent, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  C2. garmin_container — unlock_meta (happy path + error cases)
# ══════════════════════════════════════════════════════════════════════════════
section("C2. garmin_container — unlock_meta")

# Neues Fixture — eigener Temp-Ordner, isoliert von Section C
_c2_parent = Path(tempfile.mkdtemp(prefix="garmin_c2_"))
_c2_gla    = _c2_parent / "mirror_c2.gla"

# Quelle mit quality_log.json aufbauen
_c2_src = Path(tempfile.mkdtemp(prefix="garmin_c2_src_"))
(_c2_src / "garmin_data" / "log").mkdir(parents=True)
(_c2_src / "garmin_data" / "raw" / "2024-03-01").mkdir(parents=True)
(_c2_src / "garmin_data" / "log" / "quality_log.json").write_text(
    _json.dumps({"days": [{"date": "2024-03-01", "quality": "high"}]}),
    encoding="utf-8"
)
(_c2_src / "garmin_data" / "raw" / "2024-03-01" / "garmin_raw_2024-03-01.json").write_text(
    _json.dumps({"hr": 55, "source": "api"}), encoding="utf-8"
)
mirror.run_mirror(_c2_src, _c2_gla, "correct-pw")

# C2a — Happy Path
_um_ok = _gc.unlock_meta(_c2_gla, "correct-pw")
check("unlock_meta: ok=True on correct password",    _um_ok["ok"] == True)
check("unlock_meta: quality_log is dict",            isinstance(_um_ok.get("quality_log"), dict))
check("unlock_meta: quality_log has days",           "days" in _um_ok.get("quality_log", {}))
check("unlock_meta: container_meta not empty",       bool(_um_ok.get("container_meta")))
check("unlock_meta: error is empty string",          _um_ok.get("error") == "")

# C2b — Falsches Passwort
_um_bad_pw = _gc.unlock_meta(_c2_gla, "wrong-pw")
check("unlock_meta: ok=False on wrong password",     _um_bad_pw["ok"] == False)
check("unlock_meta: quality_log empty on wrong pw",  _um_bad_pw.get("quality_log") == {})
check("unlock_meta: error string set on wrong pw",   bool(_um_bad_pw.get("error")))

# C2c — Nicht-existente Datei
_um_missing = _gc.unlock_meta(_c2_parent / "ghost.gla", "correct-pw")
check("unlock_meta: ok=False on missing file",       _um_missing["ok"] == False)

# C2d — Kein Container (zufälliger Inhalt)
_c2_junk = _c2_parent / "junk.bin"
_c2_junk.write_bytes(b"THIS IS NOT A GLA CONTAINER AT ALL")
_um_junk = _gc.unlock_meta(_c2_junk, "correct-pw")
check("unlock_meta: ok=False on non-container file", _um_junk["ok"] == False)

# C2e — Tampered Header (HMAC-Bytes überschreiben)
import shutil as _shutil
_c2_tampered = _c2_parent / "tampered.gla"
_shutil.copy2(_c2_gla, _c2_tampered)
with open(_c2_tampered, "r+b") as _tf:
    # magic(4) + format_ver(1) + salt(16) = offset 21 → HMAC beginnt hier
    _tf.seek(4 + 1 + 16)
    _tf.write(b"\xff" * 32)  # 32 HMAC-Bytes korrumpieren
_um_tampered = _gc.unlock_meta(_c2_tampered, "correct-pw")
check("unlock_meta: ok=False on tampered HMAC",      _um_tampered["ok"] == False)

# ══════════════════════════════════════════════════════════════════════════════
#  C3. garmin_container — fulfill_order (happy path + error cases)
# ══════════════════════════════════════════════════════════════════════════════
section("C3. garmin_container — fulfill_order")

# C3a — Happy Path: raw-Datei anfordern und Inhalt prüfen
_fo_order  = {"raw": ["garmin_data/raw/2024-03-01/garmin_raw_2024-03-01.json"]}
_fo_result = _gc.fulfill_order(_c2_gla, "correct-pw", _fo_order)
_fo_key    = "garmin_data/raw/2024-03-01/garmin_raw_2024-03-01.json"
check("fulfill_order: requested key in result",      _fo_key in _fo_result)
check("fulfill_order: returned value is bytes",      isinstance(_fo_result.get(_fo_key), bytes))
_fo_parsed = _json.loads(_fo_result[_fo_key]) if _fo_key in _fo_result else {}
check("fulfill_order: content matches original",     _fo_parsed.get("hr") == 55)

# C3b — Falsches Passwort → leeres dict
_fo_bad_pw = _gc.fulfill_order(_c2_gla, "wrong-pw", _fo_order)
check("fulfill_order: empty dict on wrong password", _fo_bad_pw == {})

# C3c — Leere Order → leeres dict (kein Crash)
_fo_empty = _gc.fulfill_order(_c2_gla, "correct-pw", {})
check("fulfill_order: empty order → empty dict",     _fo_empty == {})

# Aufräumen C2/C3
shutil.rmtree(_c2_src,    ignore_errors=True)
shutil.rmtree(_c2_parent, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════════
#  4g2. garmin_container, garmin_mirror — format pinned by an independent reader,
#       return values, magic/version, order handling, path classification
#       (v1.7.4.0.3). Closes the survivors of the mutation test.
# ══════════════════════════════════════════════════════════════════════════════
section("4g2. garmin_container, garmin_mirror — independent reader, edges")
import hashlib as _hashlib
import hmac as _hmac4
import zlib as _zlib4
from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM4

_ver4b_added = "version" not in sys.modules
if _ver4b_added:
    _ver4b = _types4.ModuleType("version")
    _ver4b.APP_VERSION = "test"
    sys.modules["version"] = _ver4b


class _CLogRec:
    """Stands in for a module logger and records (level, message)."""
    def __init__(self):
        self.calls = []

    def _add(self, level, msg):
        self.calls.append((level, msg))

    def error(self, msg, *a, **k):
        self._add("error", msg)

    def warning(self, msg, *a, **k):
        self._add("warning", msg)

    def info(self, msg, *a, **k):
        self._add("info", msg)

    def debug(self, msg, *a, **k):
        self._add("debug", msg)


def _with_log(module, fn, *args, **kwargs):
    """fn(*args) with module.log recorded -> (result, calls)."""
    real, rec = module.log, _CLogRec()
    module.log = rec
    try:
        return fn(*args, **kwargs), rec.calls
    finally:
        module.log = real


def _dyn(s):
    """Equal string that is a different object (not interned): for 'is' mutants."""
    return s[:2] + s[2:]


def _indep_read(path, password):
    """Reads a container with the standard library and AES-GCM only (no garmin_container).
    Layout: GLA1 | version | salt 16 | HMAC 32 | header length 4 (big endian) | header | sections."""
    data = Path(path).read_bytes()
    magic, ver = data[:4], data[4]
    salt, stored = data[5:21], data[21:53]
    hlen = int.from_bytes(data[53:57], "big")
    header_json = data[57:57 + hlen]
    master = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000, 32)
    hmac_ok = _hmac4.compare_digest(_hmac4.new(master, header_json, "sha256").digest(), stored)
    header = json.loads(header_json)
    start = 57 + hlen
    sections = {}
    for name, info in header["section_index"].items():
        blob = data[start + info["offset"]: start + info["offset"] + info["length"]]
        # HKDF-Expand (SHA-256, 32 bytes) = HMAC(master, info + 0x01)
        key = _hmac4.new(master, b"gla-" + name.encode() + b"\x01", "sha256").digest()
        compressed = _AESGCM4(key).decrypt(blob[:12], blob[12:], None)
        sections[name] = (compressed, json.loads(_zlib4.decompress(compressed)), len(blob))
    return {"magic": magic, "ver": ver, "hmac_ok": hmac_ok, "header": header,
            "sections": sections, "total": len(data), "start": start}


# Section content large and varied enough that zlib levels 5, 6 and 7 give different output
_BIG4 = b"".join(_hashlib.sha256(str(i).encode()).hexdigest().encode()[: (i % 40) + 8] + b"\n"
                 for i in range(3000))
_RAW_BIG = "garmin_data/raw/big.json"
_ind = _M4 / "indep.gla"
_r = _craft_container(_ind, {"raw": {_RAW_BIG: _BIG4, _RAW_A: b'{"a": 1}'},
                             "context": {_CTX_A: b'{"t": 5}'}}, password="indep-pw")
_rd = _indep_read(_ind, "indep-pw")
check("4g2 format: magic GLA1, format version 1", _rd["magic"] == b"GLA1" and _rd["ver"] == 1)
check("4g2 format: header HMAC verifies with PBKDF2-SHA256, 600000 rounds, 32-byte key",
      _rd["hmac_ok"] is True)
check("4g2 format: header carries container_meta and the section index",
      set(_rd["header"]) == {"container_meta", "section_index"}
      and set(_rd["header"]["container_meta"]) == {"gla_version", "schema_version", "created_at"}
      and set(_rd["header"]["section_index"]) == {"raw", "context"})
check("4g2 format: sections decrypt with HKDF(gla-<name>) and a 12-byte nonce, content intact",
      {k: bytes(v) for k, v in _rd["sections"]["raw"][1].items()} == {_RAW_BIG: _BIG4, _RAW_A: b'{"a": 1}'}
      and {k: bytes(v) for k, v in _rd["sections"]["context"][1].items()} == {_CTX_A: b'{"t": 5}'})
_payload = json.dumps(_rd["sections"]["raw"][1], separators=(",", ":")).encode("utf-8")
check("4g2 format guard: the test payload really tells zlib levels 5/6/7 apart",
      len({_zlib4.compress(_payload, lv) for lv in (5, 6, 7)}) == 3)
check("4g2 format: raw section is zlib level 6",
      _rd["sections"]["raw"][0] == _zlib4.compress(_payload, 6))
_idx_i = _rd["header"]["section_index"]
check("4g2 format: section offsets are contiguous and lengths match the blobs",
      _idx_i["raw"]["offset"] == 0 and _idx_i["context"]["offset"] == _idx_i["raw"]["length"]
      and _idx_i["raw"]["length"] == _rd["sections"]["raw"][2]
      and _rd["start"] + _idx_i["context"]["offset"] + _idx_i["context"]["length"] == _rd["total"])
check("4g2 format: file list in the index",
      sorted(_idx_i["raw"]["files"]) == sorted([_RAW_BIG, _RAW_A]))

# -- lock: return values ----------------------------------------------------------------
check("4g2 lock: missing source -> exact result",
      _gc4.lock(_M4 / "no_such_src", _M4 / "nx.gla", "pw")
      == {"files_packed": 0, "errors": 1, "ok": False})
_srcA = _M4 / "srcA"
shutil.rmtree(_srcA, ignore_errors=True)
(_srcA / "garmin_data" / "raw").mkdir(parents=True)
(_srcA / "garmin_data" / "raw" / "garmin_raw_2024-01-01.json").write_text("{}", encoding="utf-8")
_nested = _M4 / "n1" / "n2" / "c.gla"
shutil.rmtree(_M4 / "n1", ignore_errors=True)
_r = _gc4.lock(_srcA, _nested, "pw")
check("4g2 lock: missing parent folders of the target are created",
      _r == {"files_packed": 1, "errors": 0, "ok": True} and _nested.is_file())

_one = {"raw": {"garmin_data/raw/a.json": b"1"}}
with patch.object(_gc4, "_collect_sections", lambda _s: dict(_one)):
    _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "noerrkey.gla", "pw")
check("4g2 lock: collector result without '_errors' -> 0 errors, ok",
      _r == {"files_packed": 1, "errors": 0, "ok": True})
for _n_err in (1, 2):
    with patch.object(_gc4, "_collect_sections", lambda _s, n=_n_err: {**_one, "_errors": n}):
        _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "witherr.gla", "pw")
    check(f"4g2 lock: {_n_err} read error(s) reported -> ok False, files still packed",
          _r == {"files_packed": 1, "errors": _n_err, "ok": False} and (_M4 / "witherr.gla").is_file())

with patch.object(_gc4, "_derive_master", side_effect=RuntimeError("boom")):
    _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "boom.gla", "pw")
check("4g2 lock: unexpected failure -> exact failure result, no container, no .tmp",
      _r == {"files_packed": 0, "errors": 1, "ok": False}
      and not (_M4 / "boom.gla").exists() and not (_M4 / "boom.gla.tmp").exists()
      and list(_M4.glob("*.tmp")) == [])
with patch("os.replace", side_effect=OSError("locked")):
    _r = _gc4.lock(_M4_EMPTY_SRC, _M4 / "swapfail3.gla", "pw")
check("4g2 lock: failing swap -> exact failure result",
      _r == {"files_packed": 0, "errors": 1, "ok": False})

# -- magic and format version: header otherwise intact ---------------------------------------
_gd = Path(_good4).read_bytes()
for _tag, _magic in (("greater", b"GLB1"), ("smaller", b"GLA0"), ("shorter", b"GL")):
    _p4 = _M4 / f"magic_{_tag}.gla"
    _p4.write_bytes(_magic + _gd[len(_magic):] if len(_magic) == 4 else _magic + _gd[4:])
    _u = _gc4.unlock_meta(_p4, "pw")
    check(f"4g2 magic {_tag}: list_files -> []", _gc4.list_files(_p4, "raw") == [])
    check(f"4g2 magic {_tag}: unlock_meta refuses, names the magic bytes",
          _u["ok"] is False and "magic bytes mismatch" in _u["error"])
    check(f"4g2 magic {_tag}: fulfill_order -> {{}}",
          _gc4.fulfill_order(_p4, "pw", {"raw": [_RAW_A]}) == {})
for _fv in (0, 2, 255):
    _b = bytearray(_gd)
    _b[4] = _fv
    _p4 = _M4 / f"fmt_{_fv}.gla"
    _p4.write_bytes(bytes(_b))
    _u = _gc4.unlock_meta(_p4, "pw")
    check(f"4g2 format version {_fv}: refused with the version in the message",
          _u["ok"] is False and _u["error"] == f"Unsupported container format version: {_fv}")
check("4g2 format version 1 (the real one) is accepted",
      _gc4.unlock_meta(_good4, "pw")["ok"] is True)

# -- fulfill_order: an empty or unknown entry does not stop the others -------------------------
_f = _gc4.fulfill_order(_good4, "pw", {"context": [], "raw": [_RAW_A]})
check("4g2 fulfill_order: an empty file list does not end the loop",
      _f == {_RAW_A: b'{"a": 1}'})
_f, _calls = _with_log(_gc4, _gc4.fulfill_order, _good4, "pw",
                       {"nope": ["x"], "raw": [_RAW_A, "garmin_data/raw/gone.json"]})
check("4g2 fulfill_order: an unknown section does not end the loop",
      _f == {_RAW_A: b'{"a": 1}'})
check("4g2 fulfill_order: unknown section and missing file are logged as warnings",
      ("warning", "  container: section 'nope' not in index — skipping") in _calls
      and ("warning", "  container: requested file not found in section: garmin_data/raw/gone.json") in _calls)

# -- is_container: only the first four bytes decide ------------------------------------------------
for _name, _content, _exp in (("m_less.bin", b"GLA0rest", False), ("m_more.bin", b"GLB1rest", False),
                              ("m_short.bin", b"GLA", False), ("m_empty.bin", b"", False),
                              ("m_magic_only.bin", b"GLA1", True), ("m_ok.bin", b"GLA1whatever", True)):
    (_M4 / _name).write_bytes(_content)
    check(f"4g2 is_container: {_content[:12]!r} -> {_exp}", _gc4.is_container(_M4 / _name) is _exp)
check("4g2 is_container: a str path works", _gc4.is_container(str(_good4)) is True)

# -- _classify_file: every branch and its neighbours ---------------------------------------------------
_cf = _gc4._classify_file
_CASES = [
    (("garmin_data", "log", "quality_log.json"), "quality_log"),
    (("garmin_data", "log", "device_table.json"), "quality_log"),
    (("garmin_data", "log", "other.json"), None),
    (("garmin_data", "log", "quality_log.json", "extra"), None),   # too deep for the log rule
    (("garmin_data", "log"), None),
    (("garmin_data", "lo", "quality_log.json"), None),
    (("garmin_data", "logs", "quality_log.json"), None),
    (("garmin_dat", "log", "quality_log.json"), None),
    (("garmin_datb", "log", "quality_log.json"), None),
    (("garmin_data", "raw", "2024-01-01", "x.json"), "raw"),
    (("garmin_data", "raw"), "raw"),
    (("garmin_data", "ra", "x"), None), (("garmin_data", "rax", "x"), None),
    (("garmin_dat", "raw", "x"), None), (("garmin_datb", "raw", "x"), None),
    (("garmin_data", "summary", "x.json"), "summary"),
    (("garmin_data", "summary"), "summary"),
    (("garmin_data", "summar", "x"), None), (("garmin_data", "summarz", "x"), None),
    (("garmin_dat", "summary", "x"), None), (("garmin_datb", "summary", "x"), None),
    (("garmin_data", "source", "x.json"), "source"),
    (("garmin_data", "source"), "source"),
    (("garmin_data", "sourcd", "x"), None), (("garmin_data", "sourcf", "x"), None),
    (("garmin_dat", "source", "x"), None), (("garmin_datb", "source", "x"), None),
    (("context_data", "weather", "raw", "x.json"), "context"),
    (("context_data",), "context"),
    (("context_dat", "x"), None), (("context_datb", "x"), None),
    (("garmin_data",), None),
    (("garmin_data", "other", "x"), None),
    (("garmin_token", "x"), None),
    (("other", "x"), None),
]
_bad_cf = [(p, e, _cf(p)) for p, e in _CASES if _cf(p) != e]
check(f"4g2 _classify_file: {len(_CASES)} paths classified as expected", _bad_cf == [])
check("4g2 _classify_file: strings that are equal but not the same object classify alike",
      _cf((_dyn("garmin_data"), _dyn("raw"), "x")) == "raw"
      and _cf((_dyn("garmin_data"), _dyn("summary"), "x")) == "summary"
      and _cf((_dyn("garmin_data"), _dyn("source"), "x")) == "source"
      and _cf((_dyn("garmin_data"), _dyn("log"), _dyn("quality_log.json"))) == "quality_log"
      and _cf((_dyn("context_data"), "x")) == "context")

# -- garmin_mirror -------------------------------------------------------------------------------------------
_afile = _M4 / "a_file2"
_afile.write_text("not a folder", encoding="utf-8")
_cm = _M4 / "mir_out.gla"
_r = _mir4.run_mirror(_afile, _cm, "pw")
check("4g2 run_mirror: source is a file -> exact failure result with the reason",
      _r == {"files_packed": 0, "errors": 1, "ok": False,
             "error": f"source not found or not a directory: {_afile}"} and not _cm.exists())
_r = _mir4.run_mirror(_M4 / "no_such_dir", _cm, "pw")
check("4g2 run_mirror: source missing -> exact failure result with the reason",
      _r == {"files_packed": 0, "errors": 1, "ok": False,
             "error": f"source not found or not a directory: {_M4 / 'no_such_dir'}"})
with patch.object(_gc4, "lock", return_value={}):
    _r, _calls = _with_log(_mir4, _mir4.run_mirror, _M4_EMPTY_SRC, _cm, "pw")
check("4g2 run_mirror: a lock result without counts is logged as 0 files, 0 errors",
      _r == {} and ("info", "  mirror done: 0 files packed, 0 errors") in _calls)
_r, _calls = _with_log(_mir4, _mir4.run_mirror, _srcA, _cm, "pw")
check("4g2 run_mirror: real run -> lock result passed through and logged",
      _r == {"files_packed": 1, "errors": 0, "ok": True}
      and ("info", "  mirror done: 1 files packed, 0 errors") in _calls and _cm.is_file())
check("4g2 is_reachable: parent that is a file -> False",
      _mir4.is_reachable(_afile / "x.gla") is False)
check("4g2 is_reachable: parent folder exists -> True, parent missing -> False",
      _mir4.is_reachable(_M4 / "x.gla") is True
      and _mir4.is_reachable(_M4 / "no_such_dir" / "x.gla") is False)
check("4g2 is_reachable: empty / None -> False",
      _mir4.is_reachable("") is False and _mir4.is_reachable(None) is False)

if _ver4b_added:
    sys.modules.pop("version", None)

summary()
