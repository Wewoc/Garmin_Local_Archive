#!/usr/bin/env python3
"""
garmin_api.py

Worker — sole authority over Garmin Connect API calls.

Responsibilities:
  - Login to Garmin Connect, return client object
  - Execute single API calls with delay and stop-check (api_call)
  - Fetch all raw endpoints for a given date (fetch_raw)
  - Fetch registered device list (get_devices)

No file IO, no quality log access, no date strategy logic.

Stop-event note:def login(on_key_required=None, on_token_expired=None):
  In Standalone mode (Target 3), garmin_app_standalone.py injects a
  threading.Event into this module via module.__dict__["_STOP_EVENT"].
  api_call() checks this event before each request via _is_stopped().
  In Dev/Standard mode (Target 1+2) no event is injected — _is_stopped()
  returns False safely via globals().get().
"""

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
#  Stop-event (injected by standalone GUI via module.__dict__)
# ══════════════════════════════════════════════════════════════════════════════

def _is_stopped() -> bool:
    """Returns True if the standalone GUI has requested a stop."""
    ev = globals().get("_STOP_EVENT")
    return ev is not None and ev.is_set()


# ══════════════════════════════════════════════════════════════════════════════
#  Login
# ══════════════════════════════════════════════════════════════════════════════

def login(on_key_required=None, on_token_expired=None, on_mfa_required=None):
    """
    Logs in to Garmin Connect. Tries saved token first, falls back to SSO.

    Token flow:
      Path 1 — Token valid:
        load_token() → garmin.login(token_dir) → probe call → return client
      Path 2 — Token expired (probe fails):
        clear_token() → on_token_expired() → Proceed? → SSO (Path 3)
      Path 3 — No token (first setup or after clear):
        Garmin(email, pw, return_on_mfa=True) → login()
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
    """
    try:
        from garminconnect import Garmin
    except ImportError:
        log.error("garminconnect not installed: pip install garminconnect")
        raise GarminLoginError("garminconnect not installed")

    import garmin_security

    log.info("Connecting to Garmin Connect ...")

    # ── Path 3b — Enc-key missing: prompt user to re-enter ────────────────────
    if cfg.GARMIN_TOKEN_FILE.exists() and garmin_security.get_enc_key() is None:
        log.warning("  Encryption key not found in WCM")
        if on_key_required:
            enc_key = on_key_required()
            if enc_key:
                garmin_security.store_enc_key(enc_key)

    # ── Path 1 — Try saved token ───────────────────────────────────────────────
    if garmin_security.load_token():
        try:
            client = Garmin()
            client.login(str(cfg.GARMIN_TOKEN_DIR))
            garmin_security._clear_token_dir()
            # Probe call — verify token is still accepted by Garmin
            from datetime import date
            client.get_user_summary(date.today().isoformat())
            log.info("  ✓ Login via saved token")
            return client
        except Exception:
            log.warning("  Saved token rejected by Garmin — token expired")
            garmin_security._clear_token_dir()
            garmin_security.clear_token()

            # ── Path 2 — Token expired: warn about 429 risk ───────────────────
            if on_token_expired:
                proceed = on_token_expired()
                if not proceed:
                    log.info("  Login cancelled by user")
                    return None

    # ── Path 3 — SSO login (first setup or after expired token) ───────────────
    if garmin_security.get_enc_key() is None and on_key_required:
        enc_key = on_key_required()
        if enc_key:
            garmin_security.store_enc_key(enc_key)

    try:
        client = Garmin(cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD, return_on_mfa=True)
        result = client.login()

        if result == "needs_mfa":
            log.info("  MFA required")
            if not on_mfa_required:
                raise GarminLoginError("MFA required but no handler provided")
            mfa_code = on_mfa_required()
            if not mfa_code:
                log.info("  MFA cancelled by user")
                return None
            client.resume_login(result, mfa_code)

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
        error_msg = str(e)
        if "429" in error_msg:
            log.critical(f"  ✗ RATE LIMIT (429) — stopping immediately to protect IP.")
            ev = globals().get("_STOP_EVENT")
            if ev:
                ev.set()
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
