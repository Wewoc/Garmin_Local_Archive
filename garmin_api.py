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

Stop-event note:
  In Standalone mode (Target 3), garmin_app_standalone.py injects a
  threading.Event into this module via module.__dict__["_STOP_EVENT"].
  api_call() checks this event before each request via _is_stopped().
  In Dev/Standard mode (Target 1+2) no event is injected — _is_stopped()
  returns False safely via globals().get().
"""

import logging
import sys
import time

import garmin_config as cfg

log = logging.getLogger(__name__)


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

def login(on_key_required=None, on_token_expired=None):
    """
    Logs in to Garmin Connect. Tries saved token first, falls back to SSO.

    Token flow:
      Path 1 — Token valid:
        load_token() -> garth.loads() -> probe call -> return client (no SSO)
      Path 2 — Token expired (probe fails):
        on_token_expired() -> Proceed? -> SSO -> save new token -> return client
      Path 3 — No token (first setup or after clear):
        SSO login -> save token -> return client
      Path 3b — Enc-key missing (WCM empty after Windows update):
        on_key_required() -> re-enter key -> retry load_token()
        -> success: Path 1 | failure: Path 3

    Callbacks (optional):
      on_key_required()   -- callable: () -> str | None
                             Returns enc_key entered by user, or None on cancel.
                             T1/T2: direct tkinter dialog.
                             T3: queue signal + threading.Event.
      on_token_expired()  -- callable: () -> bool
                             Returns True = Proceed, False = Cancel.
                             T1/T2: direct tkinter dialog.
                             T3: queue signal + threading.Event.
      If no callbacks provided: skips popups, falls through to SSO login.

    Returns the authenticated client object.
    Calls sys.exit(1) on unrecoverable failure.
    """
    try:
        from garminconnect import Garmin
    except ImportError:
        log.error("garminconnect not installed: pip install garminconnect")
        sys.exit(1)

    import garmin_security
    from datetime import date

    log.info("Connecting to Garmin Connect ...")

    # ── Path 3b — Enc-key missing: prompt user to re-enter ────────────────────
    if cfg.GARMIN_TOKEN_FILE.exists() and garmin_security.get_enc_key() is None:
        log.warning("  Encryption key not found in WCM")
        if on_key_required:
            enc_key = on_key_required()
            if enc_key:
                garmin_security.store_enc_key(enc_key)
            # load_token() will now either succeed (Path 1) or return None (Path 3)

    # ── Path 1 — Try saved token ───────────────────────────────────────────────
    token_string = garmin_security.load_token()
    if token_string:
        try:
            client = Garmin(cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD)
            client.garth.loads(token_string)
            # Probe call — verify token is still accepted by Garmin
            client.get_user_summary(date.today().isoformat())
            log.info("  ✓ Login via saved token")
            return client
        except Exception:
            log.warning("  Saved token rejected by Garmin — token expired")
            garmin_security.clear_token()

            # ── Path 2 — Token expired: warn about 429 risk ───────────────────
            if on_token_expired:
                proceed = on_token_expired()
                if not proceed:
                    log.info("  Login cancelled by user")
                    sys.exit(0)

    # ── Path 3 — SSO login (first setup or after expired token) ───────────────
    # Prompt for enc_key if not already stored (first setup)
    if garmin_security.get_enc_key() is None and on_key_required:
        enc_key = on_key_required()
        if enc_key:
            garmin_security.store_enc_key(enc_key)

    try:
        client = Garmin(cfg.GARMIN_EMAIL, cfg.GARMIN_PASSWORD)
        client.login()
        log.info("  ✓ Login successful (SSO)")

        # Save new token
        token_string = client.garth.dumps()
        garmin_security.save_token(token_string)

        return client
    except Exception as e:
        log.error(f"Login failed: {e}")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  API call wrapper
# ══════════════════════════════════════════════════════════════════════════════

def api_call(client, method: str, *args, label: str = ""):
    """Single API call with delay and error handling. Returns (data, success)."""
    if _is_stopped():
        return None, False
    try:
        data = getattr(client, method)(*args)
        time.sleep(cfg.REQUEST_DELAY)
        return data, True
    except Exception as e:
        log.warning(f"    ✗ {label or method}: {e}")
        time.sleep(cfg.REQUEST_DELAY)
        return None, False


# ══════════════════════════════════════════════════════════════════════════════
#  Raw data fetch
# ══════════════════════════════════════════════════════════════════════════════

def fetch_raw(client, date_str: str) -> dict:
    """Fetches all available Garmin API endpoints and returns raw data."""
    raw = {"date": date_str}

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
        data, _ = api_call(client, method, *args, label=key)
        if data is not None:
            raw[key] = data

    return raw


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

def _parse_device_date(val) -> str | None:
    """Converts a device date value to YYYY-MM-DD.
    Handles ISO strings, millisecond timestamps, and second timestamps."""
    from datetime import datetime
    if not val:
        return None
    s = str(val).strip()
    if len(s) >= 10 and s[4:5] == "-":
        return s[:10]
    try:
        ts = int(s)
        if ts > 1e11:
            ts //= 1000
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None
