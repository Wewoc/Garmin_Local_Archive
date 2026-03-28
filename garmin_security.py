#!/usr/bin/env python3
"""
garmin_security.py

Security — sole authority over token encryption/decryption.

Responsibilities:
  - Encrypt/decrypt garmin_token.enc using AES-256-GCM
  - Store/retrieve encryption key via Windows Credential Manager (keyring)
  - clear_token() removes both the encrypted file and the WCM entry

Encryption key design:
  - User-defined on first setup (comparable to a password manager master password)
  - Stored in Windows Credential Manager under GarminLocalArchive / token_enc_key
  - Never stored in plaintext anywhere else
  - If lost: re-entry triggers re-derivation of the same AES key from the same enc_key
  - AES-256-GCM: authenticated encryption — detects file manipulation

No GUI logic. No direct calls to garmin_api or other project modules.
"""

import logging
import os

import garmin_config as cfg

log = logging.getLogger(__name__)

KEYRING_SERVICE  = "GarminLocalArchive"
KEYRING_ENC_USER = "token_enc_key"


# ══════════════════════════════════════════════════════════════════════════════
#  WCM helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_enc_key() -> str | None:
    """Read encryption key from Windows Credential Manager. Returns None if not found."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ENC_USER) or None
    except Exception as e:
        log.warning(f"  Could not read enc_key from WCM: {e}")
        return None


def store_enc_key(enc_key: str) -> bool:
    """Store encryption key in Windows Credential Manager. Returns True on success."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_ENC_USER, enc_key)
        log.info("  ✓ Encryption key stored in Windows Credential Manager")
        return True
    except Exception as e:
        log.error(f"  Could not store enc_key in WCM: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Crypto helpers
# ══════════════════════════════════════════════════════════════════════════════

def _derive_aes_key(enc_key: str) -> bytes:
    """Derives a 32-byte AES key from the user's enc_key string via PBKDF2-HMAC-SHA256.

    Fixed salt rationale:
      Single-user, single-installation tool. Salt's purpose (preventing
      cross-installation rainbow tables) is irrelevant here. A fixed salt
      ensures the same enc_key always produces the same AES key — which is
      required for WCM-loss recovery without a salt file on disk.
    """
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    FIXED_SALT = b"GarminLocalArchive_v1"

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=FIXED_SALT,
        iterations=600_000,
    )
    return kdf.derive(enc_key.encode("utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def save_token(token_string: str) -> bool:
    """
    Encrypts token_string with AES-256-GCM and writes garmin_token.enc to LOG_DIR.
    Reads enc_key from WCM — must already be stored before calling this.
    Returns True on success.
    """
    enc_key = get_enc_key()
    if enc_key is None:
        log.error("  Cannot save token — encryption key not found in WCM")
        return False

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aes_key    = _derive_aes_key(enc_key)
        nonce      = os.urandom(12)  # 96-bit nonce, standard for AES-GCM
        aesgcm     = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, token_string.encode("utf-8"), None)

        cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
        cfg.GARMIN_TOKEN_FILE.write_bytes(nonce + ciphertext)

        log.info("  ✓ Token encrypted and saved")
        return True

    except Exception as e:
        log.error(f"  Token save failed: {e}")
        return False


def load_token() -> str | None:
    """
    Reads enc_key from WCM, decrypts garmin_token.enc, returns plaintext token string.
    Plaintext never written to disk.
    Returns None if: file missing, WCM empty, decryption failed.
    """
    if not cfg.GARMIN_TOKEN_FILE.exists():
        log.info("  No saved token found")
        return None

    enc_key = get_enc_key()
    if enc_key is None:
        log.warning("  Encryption key not found in WCM — re-entry required")
        return None

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aes_key    = _derive_aes_key(enc_key)
        data       = cfg.GARMIN_TOKEN_FILE.read_bytes()
        nonce      = data[:12]
        ciphertext = data[12:]
        aesgcm     = AESGCM(aes_key)

        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        log.info("  ✓ Token decrypted successfully")
        return plaintext.decode("utf-8")

    except Exception as e:
        log.error(f"  Token decryption failed: {e}")
        return None


def clear_token() -> None:
    """Removes garmin_token.enc from disk and the enc_key from WCM."""
    try:
        if cfg.GARMIN_TOKEN_FILE.exists():
            cfg.GARMIN_TOKEN_FILE.unlink()
            log.info("  Token file removed")
    except Exception as e:
        log.warning(f"  Could not remove token file: {e}")

    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ENC_USER)
        log.info("  Encryption key removed from WCM")
    except Exception as e:
        log.warning(f"  Could not remove enc_key from WCM: {e}")
