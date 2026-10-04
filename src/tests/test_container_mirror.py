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

# Ist-Stand: a leftover .tmp file in raw/ or summary/ is packed into the container
# (see ROADMAP v1.7.4.3). To be rewritten when .tmp files are left out.
_tree2 = _M4 / "tree_tmp"
(_tree2 / "garmin_data" / "raw").mkdir(parents=True)
(_tree2 / "garmin_data" / "summary").mkdir(parents=True)
(_tree2 / "garmin_data" / "raw" / "garmin_raw_2024-01-01.tmp").write_text("half", encoding="utf-8")
(_tree2 / "garmin_data" / "summary" / "garmin_2024-01-01.tmp").write_text("half", encoding="utf-8")
_sec2 = _gc4._collect_sections(_tree2)
check("Ist-Stand container: a stray .tmp in raw/ is packed into the raw section",
      "garmin_data/raw/garmin_raw_2024-01-01.tmp" in _sec2["raw"])
check("Ist-Stand container: a stray .tmp in summary/ is packed into the summary section",
      "garmin_data/summary/garmin_2024-01-01.tmp" in _sec2["summary"])

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

summary()
