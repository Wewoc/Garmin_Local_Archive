#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
layouts/dash_encryptor.py
Garmin Local Archive — Encrypted Dashboard Export

Sole Owner der HTML-Verschlüsselungs-Logik für den Encrypted-Dashboards-Export.
Leaf-Node — keine Projekt-Modul-Imports, nur stdlib + cryptography.

Nimmt einen fertigen HTML-String und gibt ein self-decrypting HTML zurück.
Entschlüsselung läuft vollständig im Browser via Web Crypto API (SubtleCrypto).
Kein Server, kein Python-Callback, kein externes Asset.

Public interface:
    encrypt_html(html_content: str, password: str) -> str
"""

import base64
import json
import os

_PBKDF2_ITERATIONS = 100_000
_SALT_LEN          = 16   # bytes
_IV_LEN            = 12   # bytes — AES-GCM standard nonce


def encrypt_html(html_content: str, password: str) -> str:
    """
    Verschlüsselt einen HTML-String mit AES-256-GCM (PBKDF2-HMAC-SHA256 Key Derivation).

    Parameters
    ----------
    html_content : str  — fertiger HTML-String (UTF-8)
    password     : str  — Passwort das der Nutzer eingegeben hat

    Returns
    -------
    str — self-decrypting HTML (enthält Ciphertext + Decrypt-Dialog + Web Crypto JS)

    Raises
    ------
    ValueError   — wenn html_content oder password leer sind
    RuntimeError — wenn Verschlüsselung fehlschlägt
    """
    if not html_content or not html_content.strip():
        raise ValueError("encrypt_html: html_content darf nicht leer sein")
    if not password:
        raise ValueError("encrypt_html: password darf nicht leer sein")

    try:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RuntimeError(
            f"encrypt_html: cryptography-Bibliothek nicht verfügbar: {exc}"
        ) from exc

    try:
        salt      = os.urandom(_SALT_LEN)
        iv        = os.urandom(_IV_LEN)
        plaintext = html_content.encode("utf-8")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        key        = kdf.derive(password.encode("utf-8"))
        aesgcm     = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, plaintext, None)

        salt_b64   = base64.b64encode(salt).decode("ascii")
        iv_b64     = base64.b64encode(iv).decode("ascii")
        cipher_b64 = base64.b64encode(ciphertext).decode("ascii")

    except Exception as exc:
        raise RuntimeError(
            f"encrypt_html: Verschlüsselung fehlgeschlagen: {exc}"
        ) from exc

    meta = json.dumps({
        "iterations": _PBKDF2_ITERATIONS,
        "salt":       salt_b64,
        "iv":         iv_b64,
        "cipher":     cipher_b64,
    }, separators=(",", ":"))

    return _build_wrapper(meta)


# ══════════════════════════════════════════════════════════════════════════════
#  Wrapper-HTML — Decrypt-Dialog + Web Crypto API
# ══════════════════════════════════════════════════════════════════════════════

def _build_wrapper(meta_json: str) -> str:
    """
    Baut das self-decrypting HTML-Dokument.
    meta_json enthält: iterations, salt (b64), iv (b64), cipher (b64).
    Alles inline — kein externes Asset, funktioniert mit file:// Protokoll.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔒 Encrypted Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; background: #12101f; color: #eaeaea;
               font-family: 'Segoe UI', sans-serif; }}
  #gla-lock {{
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; min-height: 100vh; padding: 24px;
  }}
  #gla-lock-box {{
    background: #1a1729; border: 1px solid #a259f7;
    border-radius: 8px; padding: 32px 36px; width: 100%;
    max-width: 380px; text-align: center;
  }}
  #gla-lock-box h1 {{ font-size: 15px; color: #a259f7;
                      letter-spacing: 0.12em; margin-bottom: 6px; }}
  #gla-lock-box p  {{ font-size: 12px; color: #a0a0b0; margin-bottom: 22px; }}
  #gla-pin {{
    width: 100%; padding: 10px 14px; font-size: 15px;
    background: #12101f; color: #eaeaea; border: 1px solid #6e3fcf;
    border-radius: 4px; margin-bottom: 14px; text-align: center;
    letter-spacing: 0.08em;
  }}
  #gla-pin:focus {{ outline: none; border-color: #a259f7; }}
  #gla-unlock-btn {{
    width: 100%; padding: 10px; font-size: 14px; font-weight: 700;
    background: #a259f7; color: #fff; border: none; border-radius: 4px;
    cursor: pointer;
  }}
  #gla-unlock-btn:hover {{ background: #6e3fcf; }}
  #gla-error {{
    display: none; margin-top: 12px; font-size: 12px; color: #e94560;
  }}
  #gla-content {{ display: none; }}
</style>
</head>
<body>

<div id="gla-lock">
  <div id="gla-lock-box">
    <h1>🔒 GARMIN LOCAL ARCHIVE</h1>
    <p>Encrypted Dashboard<br>Enter password to unlock.</p>
    <input id="gla-pin" type="password" placeholder="Password"
           autocomplete="off" spellcheck="false" />
    <button id="gla-unlock-btn" onclick="glaDecrypt()">Unlock</button>
    <div id="gla-error">Wrong password or corrupted file.</div>
  </div>
</div>

<div id="gla-content"></div>

<script>
const GLA_META = {meta_json};

document.getElementById('gla-pin').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') glaDecrypt();
}});

async function glaDecrypt() {{
  const pw  = document.getElementById('gla-pin').value;
  const err = document.getElementById('gla-error');
  err.style.display = 'none';

  if (!pw) {{ err.textContent = 'Please enter a password.';
              err.style.display = 'block'; return; }}

  try {{
    const enc   = new TextEncoder();
    const salt  = Uint8Array.from(atob(GLA_META.salt),  c => c.charCodeAt(0));
    const iv    = Uint8Array.from(atob(GLA_META.iv),    c => c.charCodeAt(0));
    const data  = Uint8Array.from(atob(GLA_META.cipher),c => c.charCodeAt(0));

    const baseKey = await crypto.subtle.importKey(
      'raw', enc.encode(pw), 'PBKDF2', false, ['deriveKey']
    );
    const aesKey  = await crypto.subtle.deriveKey(
      {{ name: 'PBKDF2', salt, iterations: GLA_META.iterations, hash: 'SHA-256' }},
      baseKey,
      {{ name: 'AES-GCM', length: 256 }},
      false,
      ['decrypt']
    );
    const plain   = await crypto.subtle.decrypt(
      {{ name: 'AES-GCM', iv }}, aesKey, data
    );

    const html = new TextDecoder().decode(plain);
    document.getElementById('gla-lock').remove();
    const cont = document.getElementById('gla-content');
    cont.style.display = 'block';
    cont.innerHTML = html;

    // Re-execute inline scripts from decrypted content
    cont.querySelectorAll('script').forEach(function(old) {{
      const s = document.createElement('script');
      if (old.src) {{ s.src = old.src; }} else {{ s.textContent = old.textContent; }}
      document.head.appendChild(s);
      old.remove();
    }});

  }} catch (e) {{
    err.textContent = 'Wrong password or corrupted file.';
    err.style.display = 'block';
    document.getElementById('gla-pin').value = '';
    document.getElementById('gla-pin').focus();
  }}
}}
</script>
</body>
</html>"""
