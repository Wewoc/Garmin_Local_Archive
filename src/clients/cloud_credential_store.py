#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/cloud_credential_store.py
Garmin Local Archive — Cloud LLM API Key Storage via Windows Credential Manager

Leaf-Node. Stores/retrieves/clears cloud LLM provider API keys in WCM
(Baustein 23, garmin_collector-3_experiment), one entry per provider —
Timo decision: "einen wcm eintrag pro anbieter machen, dann kann man
schnell und einfach wechseln" (switching providers back and forth
never requires re-entering a key that was already saved once).

Same underlying `keyring` library garmin/garmin_security.py already
uses for the Garmin token encryption key (get_enc_key()/store_enc_key()
— see that module's own docstring), same plain "value in, value out"
WCM round-trip. No AES/PBKDF2 layer on top, unlike garmin_security.py's
actual token encryption: an API key is a short string, not a multi-
field JSON blob, so it fits directly into one WCM credential entry —
the extra layer that module needs for the larger Garmin token simply
does not apply here.

Deliberately a separate module, not an added function in
garmin_security.py: that module's own docstring is explicit —
"No GUI logic. No direct calls to garmin_api or other project
modules" — and it lives in garmin/, the Sole-Write-Authority pipeline
package for Garmin data specifically. Cloud LLM credentials are a
different concern, so this lives in clients/ instead, alongside the
other external-tool/service integrations (ollama_client.py,
cloud_llm_client.py, mcp_client.py, chat_session_store.py).

Same WCM service name ("GarminLocalArchive") as garmin_security.py —
one place in Windows Credential Manager's own UI to find every secret
this app stores — a distinct username per provider so the two never
collide: "cloud_llm_<provider>_api_key".

Error handling mirrors garmin_security.py's own WCM functions exactly
(get_enc_key_status()/store_enc_key()/clear_token()): every keyring
call is wrapped in a broad except Exception — a WCM read/write/delete
failure (backend unavailable, entry genuinely absent, permission
issue) is never raised, only reported as False/None. The caller
(app/panel_mcp.py, clients/mcp_server_gui.py) decides how to surface
that in the UI, same "this module only classifies" split used
throughout clients/.

`keyring` is imported inside each function, not at module top level —
same lazy-import convention garmin_security.py itself already uses
for the same library (see that module's get_enc_key_status()/
store_enc_key()), not a new pattern introduced here.

_username() normalizes (strip + lower) the provider name before
building the WCM username (garmin_collector-3_experiment, found
during a post-Baustein-23 review, not part of the original Baustein
23 delivery). Baustein 23 originally fixed this only on the read side
(app/panel_chat.py::_chat_on_cloud_config_loaded(), which normalizes
before its own get_api_key() call, see that function's docstring) —
but app/panel_mcp.py and clients/mcp_server_gui.py's own Save paths
only ever `.strip()` the provider string, never `.lower()` it, and
both insert an unrecognized legacy provider value from
MCP_LLM_CONFIG_FILE into their dropdown VERBATIM (pre-dropdown
free-text data, e.g. "Anthropic" with a capital A, predates Baustein
16). Left un-normalized at this module's own boundary, a Save from
that state would have stored the key under a differently-cased WCM
username than panel_chat.py's normalized lookup would ever query —
the key would look "missing" to the Chat tab immediately after being
saved from the MCP tab. Normalizing once here, at the one place every
caller already funnels through, closes this for every current and
future caller in one spot — cheaper and more robust than fixing each
of the three call sites (and mcp_server.py's own get_api_key() call)
separately, and matches this module's own "this module only
classifies" boundary better than pushing normalization out to every
caller.
"""

KEYRING_SERVICE = "GarminLocalArchive"


def _username(provider: str) -> str:
    return f"cloud_llm_{provider.strip().lower()}_api_key"


def get_api_key(provider: str) -> str | None:
    """Reads provider's API key from WCM. Returns None if not found
    or on a WCM read failure — absence is not an error, same contract
    as garmin_security.get_enc_key()."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, _username(provider)) or None
    except Exception:
        return None


def store_api_key(provider: str, api_key: str) -> bool:
    """Stores provider's API key in WCM, overwriting any existing
    entry for that same provider. Returns True on success, False on a
    WCM write failure — never raises, same contract as
    garmin_security.store_enc_key()."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, _username(provider), api_key)
        return True
    except Exception:
        return False


def clear_api_key(provider: str) -> bool:
    """Deletes provider's API key from WCM. Returns True on success,
    False on any failure (including "no key was stored for this
    provider" — same broad except-Exception contract as
    garmin_security.clear_token()'s own WCM delete step, not a special
    "already absent" case)."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, _username(provider))
        return True
    except Exception:
        return False
