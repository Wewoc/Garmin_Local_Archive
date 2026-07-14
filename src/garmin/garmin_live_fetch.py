#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin_live_fetch.py

Worker — sole write authority over garmin_data/live/live.json.

Fetches sleep + HRV + all intraday endpoints for the current calendar day
("heute Nacht bis jetzt") and writes a single-file snapshot. No history —
every call overwrites the previous snapshot.

Responsibilities:
  - Fetch sleep + HRV + intraday data for today via garmin_api (reused, no
    own auth path, no own 429 handling)
  - Write the result to cfg.LIVE_FILE

Explicitly out of scope (Headless Invariant / Silo separation):
  - No archive write access (raw/, summary/, source/)
  - No quality_log.json contact
  - No garmin_validator / garmin_normalizer — data is written as-is
  - No own stop-event handling — garmin_api.api_call() already checks the
    stop event registered via garmin_api.set_stop_event()

Called from: "Update Live" button (own login) or appended after a
Daily Sync run (existing client passed in — no second login).
"""

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import garmin_api
import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Endpoints — sleep + HRV + all six intraday fields registered in garmin_map.py
# ══════════════════════════════════════════════════════════════════════════════

# (client method, args-template, key in live_data)
# args filled in with today's date string at call time.
#
# HRV note: garmin_normalizer.summarize() derives hrv_last_night_ms primarily
# from raw["hrv"]["hrvSummary"] (this endpoint), with a fallback to
# raw["sleep"]["hrvSummary"] if absent. Fetched explicitly here rather than
# relying on that fallback — keeps the live snapshot's hrv_last_night field
# reliable regardless of whether Garmin embeds it in the sleep response.
_ENDPOINTS = [
    ("get_sleep_data",       "sleep"),
    ("get_hrv_data",         "hrv"),
    ("get_heart_rates",      "heart_rates"),
    ("get_stress_data",      "stress"),
    ("get_body_battery",     "body_battery"),
    ("get_steps_data",       "steps"),
    ("get_spo2_data",        "spo2"),
    ("get_respiration_data", "respiration"),
]


# ══════════════════════════════════════════════════════════════════════════════
#  Write — sole write authority for LIVE_FILE
# ══════════════════════════════════════════════════════════════════════════════

def _write_live(live_data: dict) -> None:
    """
    Writes the live snapshot to cfg.LIVE_FILE. Plain write — no atomic
    tmp-file/fsync/replace sequence. live.json has no history to protect;
    a broken intermediate state is simply overwritten by the next fetch.
    """
    cfg.LIVE_DIR.mkdir(parents=True, exist_ok=True)
    cfg.LIVE_FILE.write_text(json.dumps(live_data, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def fetch_live(client=None, progress=None, state_cb=None) -> dict:
    """
    Fetches sleep + HRV + all intraday endpoints for the current calendar day
    and writes the result to cfg.LIVE_FILE.

    Args:
        client:   Already-authenticated Garmin client (e.g. reused right
                  after a Daily Sync run). If None, logs in headless via
                  garmin_api.login() — no GUI callbacks, same pattern as
                  scheduler/daily_update.py.
        progress: Optional callable(str) -> None for GUI-visible progress
                  messages during the ~30-60s fetch (e.g. "Fetching
                  heart_rates ..."). Deliberately a separate parameter from
                  the module logger (`log`) used for file/console logging —
                  a same-named parameter would shadow it within this
                  function. Default: no-op, existing callers unaffected.
        state_cb: Optional callable(key: str, state: str) -> None for GUI
                  connection-status indicators (token/login/api/data ×
                  ok/fail). Fired at two points: right after login succeeds
                  or fails (token+login), then immediately via a
                  lightweight probe (api = get_user_profile(), data =
                  get_stats(today)) before the real endpoint loop starts —
                  same probe pattern as
                  garmin_app_controller.check_connection(). Gives fast
                  visual feedback instead of waiting for the full
                  ~30-60s fetch; probe result is independent of the
                  endpoint loop's own failed_endpoints tracking, which
                  covers the 8 real endpoints separately (see "Returns").
                  Default: no-op, existing callers unaffected.

    Returns:
        {"ok": bool, "failed_endpoints": list[str]}
        "ok" is False only if login itself failed or was unavailable —
        individual endpoint failures are reported via "failed_endpoints",
        never abort the fetch.
    """
    if progress is None:
        progress = lambda msg: None  # noqa: E731
    if state_cb is None:
        state_cb = lambda key, state: None  # noqa: E731

    if client is None:
        progress("Logging in to Garmin Connect ...")
        try:
            client = garmin_api.login()
        except garmin_api.GarminLoginError as e:
            log.error(f"  Live fetch: login failed — {e}")
            progress(f"\u2717 Login failed: {e}")
            state_cb("token", "fail")
            state_cb("login", "fail")
            return {"ok": False, "failed_endpoints": []}
        if client is None:
            log.info("  Live fetch: login cancelled or unavailable.")
            progress("Login cancelled or unavailable.")
            state_cb("token", "fail")
            state_cb("login", "fail")
            return {"ok": False, "failed_endpoints": []}

    state_cb("token", "ok")
    state_cb("login", "ok")

    today = date.today().isoformat()

    try:
        client.get_user_profile()
        state_cb("api", "ok")
    except Exception as e:
        log.warning(f"  Live fetch: api probe failed — {e}")
        state_cb("api", "fail")

    try:
        client.get_stats(today)
        state_cb("data", "ok")
    except Exception as e:
        log.warning(f"  Live fetch: data probe failed — {e}")
        state_cb("data", "fail")

    live_data = {
        "date":       today,
        "synced_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    failed_endpoints = []

    for method, key in _ENDPOINTS:
        progress(f"Fetching {key} ...")
        data, success = garmin_api.api_call(client, method, today, label=key)
        if data is not None:
            live_data[key] = data
        elif not success:
            failed_endpoints.append(key)
            progress(f"\u2717 {key} failed")

    progress("Writing live.json ...")
    _write_live(live_data)

    ok_count = len(_ENDPOINTS) - len(failed_endpoints)
    log.info(f"  ✓ Live fetch complete ({ok_count}/{len(_ENDPOINTS)} endpoints)")
    if failed_endpoints:
        log.warning(f"    Failed endpoints: {', '.join(failed_endpoints)}")
    progress(f"\u2713 Live fetch complete ({ok_count}/{len(_ENDPOINTS)} endpoints)")

    return {"ok": True, "failed_endpoints": failed_endpoints}
