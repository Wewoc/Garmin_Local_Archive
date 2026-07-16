#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_api.py

Worker — sole authority over Garmin Connect API calls.

Responsibilities:
  - Login to Garmin Connect, return client object
  - Execute single API calls with delay and stop-check (api_call)
  - Fetch all raw endpoints for a given date (fetch_raw)
  - Fetch registered device list (get_devices)

No file IO, no quality log access, no date strategy logic.

Stop-event note:
  The collector registers a threading.Event via set_stop_event() before a run.
  api_call() checks this event before each request via _is_stopped().
  In subprocess mode (Target 1+2) no event is registered — _is_stopped()
  returns False safely. The 429 rate-limit handler sets the same event to
  stop the run immediately and protect the IP.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import logging
import random
import time

import garmin_config as cfg
import garmin_utils as utils

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Exceptions
# ══════════════════════════════════════════════════════════════════════════════

class GarminLoginError(Exception):
    """Raised when login fails unrecoverably (missing dependency, SSO failure)."""


# ══════════════════════════════════════════════════════════════════════════════
#  Stop-event (registered by the collector via set_stop_event)
# ══════════════════════════════════════════════════════════════════════════════

_stop_event = None   # threading.Event | None


def set_stop_event(ev) -> None:
    """Registers the stop event for this module. Pass None to clear.
    Same pattern as garmin_validator.reload_schema() — explicit module-level
    state setter, no globals() injection."""
    global _stop_event
    _stop_event = ev


def _is_stopped() -> bool:
    """Returns True if a stop event is registered and set."""
    return _stop_event is not None and _stop_event.is_set()


# ══════════════════════════════════════════════════════════════════════════════
#  Login
# ══════════════════════════════════════════════════════════════════════════════

def login(on_key_required=None, on_token_expired=None, on_mfa_required=None,
          on_sso_required=None):
    """
    Logs in to Garmin Connect. Tries saved token first, falls back to SSO.

    Token flow:
      Path 1 — Token valid:
        load_token() → garmin.login(token_dir) → probe call → return client
      Path 2 — Token expired (probe fails):
        clear_token() → on_token_expired() → Proceed? → SSO (Path 3)
      Path 3 — No token (first setup or after clear):
        on_sso_required() → Proceed?
        → Garmin(email, pw, return_on_mfa=True) → login()
        → MFA required: on_mfa_required() → resume_login()
        → save_token() → return client
      Path 3b — Enc-key missing (WCM empty after Windows update):
        on_key_required() → re-enter key → retry load_token()
        → success: Path 1 | failure: Path 3

    Callbacks (optional):
      on_key_required()   -- callable: () -> str | None
      on_token_expired()  -- callable: () -> bool
      on_mfa_required()   -- callable: () -> str | None
                             Returns MFA code entered by user, or None on cancel.
      on_sso_required()   -- callable: () -> bool
                             Called before first SSO request (Path 3).
                             User confirms before garminconnect fires any request.
                             Returns True to proceed, False to cancel.
                             If None (e.g. headless/standalone), SSO starts automatically.
    """
    try:
        from garminconnect import Garmin
    except ImportError:
        log.error("garminconnect not installed: pip install garminconnect")
        raise GarminLoginError("garminconnect not installed")

    import garmin_security

    log.info("Connecting to Garmin Connect ...")

    # ── Path 3b — Enc-key missing: auto-generate, token will be re-created ────
    if cfg.GARMIN_TOKEN_FILE.exists() and garmin_security.get_enc_key() is None:
        log.warning("  Encryption key not found in WCM — auto-generating new key")
        garmin_security.generate_enc_key()
        # Existing token was encrypted with the old key — cannot be decrypted.
        # Clear it so Path 3 (SSO) runs cleanly and re-encrypts with the new key.
        garmin_security.log_token_event("invalidated", "enc_key_missing_wcm")
        garmin_security.clear_token()
        log.warning("  Saved token cleared — re-login required")

    # ── Path 1 — Try saved token ───────────────────────────────────────────────
    if garmin_security.load_token():
        try:
            client = Garmin()
            client.login(str(cfg.GARMIN_TOKEN_DIR))
            client._tokenstore_path = None
            garmin_security._clear_token_dir()
            # Probe call — verify token is still accepted by Garmin
            from datetime import date
            client.get_user_summary(date.today().isoformat())
            log.info("  ✓ Login via saved token")
            return client
        except Exception as e:
            from garminconnect import GarminConnectTooManyRequestsError
            err = str(e)
            if isinstance(e, GarminConnectTooManyRequestsError) or "429" in err or "403" in err:
                log.warning(f"  Token probe failed ({err[:60]}) — not falling back to SSO to protect IP")
                garmin_security.log_token_event("blocked", "rate_limited",
                                                 exception_type=type(e).__name__, detail=err[:100])
                garmin_security._clear_token_dir()
                raise GarminLoginError(f"Token probe failed: {err}")
            log.warning(f"  Saved token rejected by Garmin — token expired ({type(e).__name__}: {e})")
            garmin_security.log_token_event("invalidated", "rejected_by_garmin",
                                             exception_type=type(e).__name__, detail=str(e)[:100])
            garmin_security._clear_token_dir()
            garmin_security.clear_token()

            # ── Path 2 — Token expired: warn about 429 risk ───────────────────
            if on_token_expired:
                proceed = on_token_expired()
                if not proceed:
                    log.info("  Login cancelled by user")
                    return None

    # ── Path 3 — SSO login (first setup or after expired token) ───────────────
    if on_sso_required:
        proceed = on_sso_required()
        if not proceed:
            log.info("  SSO login cancelled by user")
            return None

    if garmin_security.get_enc_key() is None:
        if not garmin_security.generate_enc_key():
            log.warning("  Auto-generate enc_key failed — falling back to manual entry")
            if on_key_required:
                enc_key = on_key_required()
                if enc_key:
                    garmin_security.store_enc_key(enc_key)

    try:
        cfg.GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        client = Garmin(cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD, prompt_mfa=on_mfa_required)
        client.login(str(cfg.GARMIN_TOKEN_DIR))

        log.info("  ✓ Login successful (SSO)")
        garmin_security.save_token()
        return client

    except GarminLoginError:
        raise
    except Exception as e:
        log.error(f"Login failed: {e}")
        raise GarminLoginError(f"Login failed: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
#  API call wrapper
# ══════════════════════════════════════════════════════════════════════════════

def api_call(client, method: str, *args, label: str = ""):
    """Single API call with delay and error handling. Returns (data, success)."""
    if _is_stopped():
        return None, False
    try:
        data = getattr(client, method)(*args)
        time.sleep(random.uniform(cfg.REQUEST_DELAY_MIN, cfg.REQUEST_DELAY_MAX))
        return data, True
    except Exception as e:
        from garminconnect import GarminConnectTooManyRequestsError
        if isinstance(e, GarminConnectTooManyRequestsError) or "429" in str(e):
            log.critical("  ✗ RATE LIMIT (429) — stopping immediately to protect IP.")
            if _stop_event is not None:
                _stop_event.set()
            return None, False
        log.warning(f"    ✗ {label or method}: {e}")
        time.sleep(random.uniform(cfg.REQUEST_DELAY_MIN, cfg.REQUEST_DELAY_MAX))
        return None, False


# ══════════════════════════════════════════════════════════════════════════════
#  Raw data fetch
# ══════════════════════════════════════════════════════════════════════════════

def fetch_raw(client, date_str: str) -> tuple:
    """
    Fetches all available Garmin API endpoints and returns raw data.

    Returns
    -------
    tuple (raw: dict, failed_endpoints: list[str])
      raw              — collected data keyed by endpoint label
      failed_endpoints — labels of endpoints that returned no data
    """
    raw = {"date": date_str}
    failed_endpoints = []

    endpoints = [
        ("get_sleep_data",           (date_str,), "sleep"),
        ("get_stress_data",          (date_str,), "stress"),
        ("get_body_battery",         (date_str,), "body_battery"),
        ("get_heart_rates",          (date_str,), "heart_rates"),
        ("get_respiration_data",     (date_str,), "respiration"),
        ("get_spo2_data",            (date_str,), "spo2"),
        ("get_stats",                (date_str,), "stats"),
        ("get_steps_data",           (date_str,), "steps"),
        ("get_user_summary",         (date_str,), "user_summary"),
        ("get_activities_fordate",   (date_str,), "activities"),
        ("get_training_status",      (date_str,), "training_status"),
        ("get_training_readiness",   (date_str,), "training_readiness"),
        ("get_hrv_data",             (date_str,), "hrv"),
        ("get_race_predictions",     (),          "race_predictions"),
        ("get_max_metrics",          (date_str,), "max_metrics"),
    ]

    for method, args, key in endpoints:
        if _is_stopped():
            break
        data, success = api_call(client, method, *args, label=key)
        if data is not None:
            raw[key] = data
        elif not success:
            failed_endpoints.append(key)

    if not _is_stopped():
        time.sleep(random.uniform(10, 20))

    return raw, failed_endpoints


# ══════════════════════════════════════════════════════════════════════════════
#  Device list
# ══════════════════════════════════════════════════════════════════════════════

def get_devices(client) -> list:
    """Fetches all registered devices, logs them, returns sorted list."""
    devices = []
    try:
        raw = client.get_devices()
        if not isinstance(raw, list):
            raw = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            name       = d.get("productDisplayName") or d.get("deviceTypeName") or "Unknown"
            device_id  = d.get("deviceId") or d.get("unitId")
            last_used  = _parse_device_date(d.get("lastUsed")) or "unknown"
            first_used = None
            for field in ("registeredDate", "activationDate", "firstSyncTime"):
                first_used = _parse_device_date(d.get(field))
                if first_used:
                    break
            devices.append({
                "name":       name,
                "id":         device_id,
                "first_used": first_used,
                "last_used":  last_used,
            })
        devices.sort(key=lambda x: x["first_used"] or "9999")
        log.info(f"  Registered devices ({len(devices)}):")
        for dv in devices:
            log.info(f"    {dv['name']:30s}  first: {dv['first_used'] or '?':10s}  last: {dv['last_used']}")
    except Exception as e:
        log.warning(f"  Could not fetch device list: {e}")
    return devices


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helper
# ══════════════════════════════════════════════════════════════════════════════

# _parse_device_date moved to garmin_utils.py
_parse_device_date = utils.parse_device_date
