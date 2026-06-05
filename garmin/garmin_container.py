#!/usr/bin/env python3
"""
garmin_container.py

Encrypted Mirror Container — Sole Owner of mirror.gla.

Creates and opens GLA container files (.gla) for encrypted mirror transport.
No other module reads or writes the container file directly.

Container format:
  magic_bytes      4 bytes   "GLA1"
  format_version   1 byte    0x01
  salt             16 bytes  PBKDF2 salt (random per lock())
  header_hmac      32 bytes  HMAC-SHA256 over header_json with master key
  header_len       4 bytes   big-endian uint32 — length of header_json
  header_json      N bytes   UTF-8 JSON with container_meta + section_index
  [section data]             AES-256-GCM encrypted sections

Key derivation:
  PBKDF2-HMAC-SHA256 (600 000 iterations) → master key
  HKDF-Expand(master, info="gla-{section}") → section key

Sections: quality_log, raw, summary, context
  Each section: nonce (12 bytes) + ciphertext (AES-256-GCM)

Sole-owner invariant:
  This module is the only module that reads or writes .gla files.
  garmin_mirror.py calls lock() to create.
  garmin_import_mirror.py calls unlock_meta(), list_files(), fulfill_order().

Called by:
  garmin/garmin_mirror.py       — lock()
  garmin/garmin_import_mirror.py — unlock_meta(), list_files(), fulfill_order()
"""

import json
import os
import secrets
import struct
import zlib
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Container magic bytes and format version
_MAGIC         = b"GLA1"
_FORMAT_VER    = 0x01
_PBKDF2_ITERS  = 600_000
_SALT_LEN      = 16
_HMAC_LEN      = 32
_HEADER_LEN_SZ = 4   # bytes for header_json length field
_NONCE_LEN     = 12  # AES-GCM nonce

# Section names — order defines section index
_SECTIONS = ["quality_log", "raw", "summary", "context"]

# Directories/files excluded from raw and summary sections
_EXCLUDE_DIRS = {"__pycache__", "garmin_token"}


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def lock(source_dir: Path, container_path: Path, password: str) -> dict:
    """
    Creates or overwrites container_path from source_dir.

    Writes atomically: container_path.tmp → fsync → os.replace.
    Only called on ok=True from run_mirror().

    Parameters
    ----------
    source_dir     : Path — local BASE_DIR (master)
    container_path : Path — target .gla file path
    password       : str  — container password

    Returns
    -------
    dict with keys:
      files_packed  int  — files added to container
      errors        int  — files that could not be read
      ok            bool — True if errors == 0
    """
    source_dir     = Path(source_dir)
    container_path = Path(container_path)

    if not source_dir.exists() or not source_dir.is_dir():
        log.error(f"  container: source not found: {source_dir}")
        return {"files_packed": 0, "errors": 1, "ok": False}

    container_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = container_path.with_suffix(".gla.tmp")

    try:
        salt       = secrets.token_bytes(_SALT_LEN)
        master_key = _derive_master(password, salt)

        # Collect files per section
        sections_data = _collect_sections(source_dir)
        errors        = sections_data.pop("_errors", 0)
        files_packed  = sum(len(v) for v in sections_data.values())

        # Build encrypted section blobs
        section_blobs  = {}
        section_index  = {}
        current_offset = 0  # relative to start of section data area

        for sec_name in _SECTIONS:
            files = sections_data.get(sec_name, {})
            if not files:
                continue
            sec_key  = _derive_section_key(master_key, sec_name)
            blob     = _encrypt_section(files, sec_key)
            section_blobs[sec_name] = blob
            section_index[sec_name] = {
                "offset": current_offset,
                "length": len(blob),
                "files":  list(files.keys()),
            }
            current_offset += len(blob)

        # Build header JSON
        from version import APP_VERSION
        from garmin_normalizer import CURRENT_SCHEMA_VERSION
        container_meta = {
            "gla_version":    APP_VERSION,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at":     datetime.now().isoformat(timespec="seconds"),
        }
        header_obj  = {
            "container_meta": container_meta,
            "section_index":  section_index,
        }
        header_json = json.dumps(header_obj, separators=(",", ":")).encode("utf-8")

        # Compute header HMAC
        header_hmac = _authenticate_header(master_key, header_json)

        # Write container atomically
        with open(tmp_path, "wb") as f:
            f.write(_MAGIC)
            f.write(bytes([_FORMAT_VER]))
            f.write(salt)
            f.write(header_hmac)
            f.write(struct.pack(">I", len(header_json)))
            f.write(header_json)
            for sec_name in _SECTIONS:
                if sec_name in section_blobs:
                    f.write(section_blobs[sec_name])
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, container_path)
        log.info(
            f"  container: locked {files_packed} files → {container_path.name} "
            f"({errors} errors)"
        )
        return {"files_packed": files_packed, "errors": errors, "ok": errors == 0}

    except Exception as e:
        log.error(f"  container: lock failed — {e}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return {"files_packed": 0, "errors": 1, "ok": False}


def unlock_meta(container_path: Path, password: str) -> dict:
    """
    Verifies header HMAC and decrypts only the quality_log section.

    Parameters
    ----------
    container_path : Path — .gla file
    password       : str  — container password

    Returns
    -------
    dict with keys:
      ok             bool
      container_meta dict  — gla_version, schema_version, created_at
      quality_log    dict  — parsed quality_log.json content
      error          str   — error message if ok=False
    """
    try:
        magic, salt, master_key, header_obj, section_data_offset = \
            _open_and_verify(container_path, password)
    except _ContainerError as e:
        return {"ok": False, "container_meta": {}, "quality_log": {}, "error": str(e)}

    container_meta = header_obj.get("container_meta", {})
    section_index  = header_obj.get("section_index", {})

    if "quality_log" not in section_index:
        return {
            "ok": False, "container_meta": container_meta,
            "quality_log": {}, "error": "quality_log section missing from container",
        }

    try:
        files = _decrypt_section(
            container_path, password,
            section_index["quality_log"],
            section_data_offset,
            master_key, "quality_log",
        )
    except Exception as e:
        return {
            "ok": False, "container_meta": container_meta,
            "quality_log": {}, "error": f"quality_log decrypt failed: {e}",
        }

    # quality_log section contains exactly one file
    ql_bytes = next(iter(files.values()), None)
    if ql_bytes is None:
        return {
            "ok": False, "container_meta": container_meta,
            "quality_log": {}, "error": "quality_log section is empty",
        }

    try:
        quality_log = json.loads(ql_bytes.decode("utf-8"))
    except Exception as e:
        return {
            "ok": False, "container_meta": container_meta,
            "quality_log": {}, "error": f"quality_log JSON parse failed: {e}",
        }

    log.debug(
        f"  container: unlock_meta OK — "
        f"gla_version={container_meta.get('gla_version', '?')}"
    )
    return {
        "ok":             True,
        "container_meta": container_meta,
        "quality_log":    quality_log,
        "error":          "",
    }


def list_files(container_path: Path, section: str) -> list[str]:
    """
    Returns the list of relative file paths stored in a section.
    Reads only the header — no decryption, no password required.

    Parameters
    ----------
    container_path : Path   — .gla file
    section        : str    — section name (e.g. "raw", "context")

    Returns
    -------
    list[str] — relative paths, empty list on error or missing section
    """
    try:
        with open(container_path, "rb") as f:
            magic = f.read(4)
            if magic != _MAGIC:
                return []
            f.read(1)   # format_version
            f.read(_SALT_LEN)
            f.read(_HMAC_LEN)
            header_len = struct.unpack(">I", f.read(_HEADER_LEN_SZ))[0]
            header_json = f.read(header_len)
        header_obj    = json.loads(header_json.decode("utf-8"))
        section_index = header_obj.get("section_index", {})
        return section_index.get(section, {}).get("files", [])
    except Exception as e:
        log.warning(f"  container: list_files failed for {section}: {e}")
        return []


def fulfill_order(
    container_path: Path,
    password: str,
    order: dict,
) -> dict:
    """
    Decrypts only the sections listed in order and returns requested files.

    Parameters
    ----------
    container_path : Path — .gla file
    password       : str  — container password
    order          : dict — {section_name: [rel_path, ...], ...}
                     e.g. {"raw": ["2024-01-15/garmin_raw_2024-01-15.json"],
                            "context": ["weather/raw/2024-01-15.json"]}

    Returns
    -------
    dict — {rel_path: bytes} for all requested files found
           empty dict on error (logged)
    """
    if not order:
        return {}

    try:
        magic, salt, master_key, header_obj, section_data_offset = \
            _open_and_verify(container_path, password)
    except _ContainerError as e:
        log.error(f"  container: fulfill_order verify failed — {e}")
        return {}

    section_index = header_obj.get("section_index", {})
    result        = {}

    for sec_name, requested_files in order.items():
        if not requested_files:
            continue
        if sec_name not in section_index:
            log.warning(f"  container: section '{sec_name}' not in index — skipping")
            continue
        try:
            all_files = _decrypt_section(
                container_path, password,
                section_index[sec_name],
                section_data_offset,
                master_key, sec_name,
            )
            for rel_path in requested_files:
                if rel_path in all_files:
                    result[rel_path] = all_files[rel_path]
                else:
                    log.warning(
                        f"  container: requested file not found in section: {rel_path}"
                    )
        except Exception as e:
            log.error(f"  container: decrypt failed for section {sec_name}: {e}")

    log.debug(f"  container: fulfill_order — {len(result)} file(s) delivered")
    return result


def is_container(path) -> bool:
    """
    Returns True if path exists, is a file, and starts with magic bytes GLA1.
    Fast check — no password, no decryption.
    """
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return False
        with open(p, "rb") as f:
            return f.read(4) == _MAGIC
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — key derivation + authentication
# ══════════════════════════════════════════════════════════════════════════════

def _derive_master(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERS,
    )
    return kdf.derive(password.encode("utf-8"))


def _derive_section_key(master: bytes, section: str) -> bytes:
    from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
    from cryptography.hazmat.primitives import hashes
    hkdf = HKDFExpand(
        algorithm=hashes.SHA256(),
        length=32,
        info=f"gla-{section}".encode("utf-8"),
    )
    return hkdf.derive(master)


def _authenticate_header(master: bytes, header_json: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, hmac as crypto_hmac
    h = crypto_hmac.HMAC(master, hashes.SHA256())
    h.update(header_json)
    return h.finalize()


def _verify_header_hmac(master: bytes, header_json: bytes, stored_hmac: bytes) -> bool:
    from cryptography.hazmat.primitives import hashes, hmac as crypto_hmac
    from cryptography.exceptions import InvalidSignature
    h = crypto_hmac.HMAC(master, hashes.SHA256())
    h.update(header_json)
    try:
        h.verify(stored_hmac)
        return True
    except InvalidSignature:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — encryption / decryption
# ══════════════════════════════════════════════════════════════════════════════

def _encrypt_section(files: dict, sec_key: bytes) -> bytes:
    """
    Encrypts a dict of {rel_path: bytes} as a single AES-256-GCM blob.
    Format: nonce (12 bytes) + ciphertext of zlib-compressed JSON.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    payload     = json.dumps(
        {k: list(v) for k, v in files.items()},
        separators=(",", ":"),
    ).encode("utf-8")
    compressed  = zlib.compress(payload, level=6)
    nonce       = secrets.token_bytes(_NONCE_LEN)
    aesgcm      = AESGCM(sec_key)
    ciphertext  = aesgcm.encrypt(nonce, compressed, None)
    return nonce + ciphertext


def _decrypt_section(
    container_path: Path,
    password: str,
    sec_info: dict,
    section_data_offset: int,
    master_key: bytes,
    sec_name: str,
) -> dict:
    """
    Decrypts one section and returns {rel_path: bytes}.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    sec_key = _derive_section_key(master_key, sec_name)
    offset  = section_data_offset + sec_info["offset"]
    length  = sec_info["length"]

    with open(container_path, "rb") as f:
        f.seek(offset)
        blob = f.read(length)

    nonce      = blob[:_NONCE_LEN]
    ciphertext = blob[_NONCE_LEN:]
    aesgcm     = AESGCM(sec_key)
    compressed = aesgcm.decrypt(nonce, ciphertext, None)
    payload    = zlib.decompress(compressed)
    raw_dict   = json.loads(payload.decode("utf-8"))
    return {k: bytes(v) for k, v in raw_dict.items()}


def _open_and_verify(
    container_path: Path,
    password: str,
) -> tuple:
    """
    Opens container, reads header, verifies HMAC.
    Returns (magic, salt, master_key, header_obj, section_data_offset).
    Raises _ContainerError on any failure.
    """
    try:
        with open(container_path, "rb") as f:
            magic = f.read(4)
            if magic != _MAGIC:
                raise _ContainerError("Not a valid GLA container (magic bytes mismatch)")
            fmt_ver = f.read(1)[0]
            if fmt_ver != _FORMAT_VER:
                raise _ContainerError(f"Unsupported container format version: {fmt_ver}")
            salt        = f.read(_SALT_LEN)
            stored_hmac = f.read(_HMAC_LEN)
            header_len  = struct.unpack(">I", f.read(_HEADER_LEN_SZ))[0]
            header_json = f.read(header_len)
            section_data_offset = (
                4 + 1 + _SALT_LEN + _HMAC_LEN + _HEADER_LEN_SZ + header_len
            )
    except _ContainerError:
        raise
    except Exception as e:
        raise _ContainerError(f"Cannot read container: {e}") from e

    master_key = _derive_master(password, salt)

    if not _verify_header_hmac(master_key, header_json, stored_hmac):
        raise _ContainerError(
            "Header HMAC verification failed — wrong password or corrupted container"
        )

    try:
        header_obj = json.loads(header_json.decode("utf-8"))
    except Exception as e:
        raise _ContainerError(f"Header JSON parse failed: {e}") from e

    return magic, salt, master_key, header_obj, section_data_offset


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — file collection
# ══════════════════════════════════════════════════════════════════════════════

def _collect_sections(source_dir: Path) -> dict:
    """
    Walks source_dir and collects files into section buckets.
    Returns dict with keys: quality_log, raw, summary, context, _errors.
    File values are bytes.
    """
    sections = {s: {} for s in _SECTIONS}
    errors   = 0

    for entry in source_dir.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source_dir)
        parts = rel.parts

        # Exclude always
        if any(p in _EXCLUDE_DIRS for p in parts):
            continue

        # Determine section
        sec = _classify_file(parts)
        if sec is None:
            continue

        try:
            # as_posix() — forward slashes on all platforms so container keys
            # match the forward-slash paths built by garmin_import_mirror
            sections[sec][rel.as_posix()] = entry.read_bytes()
        except OSError as e:
            log.warning(f"  container: cannot read {rel}: {e}")
            errors += 1

    sections["_errors"] = errors
    return sections


def _classify_file(parts: tuple) -> str | None:
    """
    Maps a relative path (as tuple of parts) to a section name.
    Returns None for files that should not be included.
    """
    if not parts:
        return None

    # quality_log: garmin_data/log/quality_log.json
    if (len(parts) == 3
            and parts[0] == "garmin_data"
            and parts[1] == "log"
            and parts[2] == "quality_log.json"):
        return "quality_log"

    # raw: garmin_data/raw/**
    if parts[0] == "garmin_data" and len(parts) > 1 and parts[1] == "raw":
        return "raw"

    # summary: garmin_data/summary/**
    if parts[0] == "garmin_data" and len(parts) > 1 and parts[1] == "summary":
        return "summary"

    # context: context_data/**
    if parts[0] == "context_data":
        return "context"

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Internal — exception
# ══════════════════════════════════════════════════════════════════════════════

class _ContainerError(Exception):
    """Internal exception for container open/verify failures."""
    pass