#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
garmin/quality/_assess.py

Quality assessment sub-module for garmin_quality.
Pure functions — no file IO.

Internal — import only via garmin_quality (facade).
"""

import logging

from garmin_normalizer import _parse_list_values

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _safe_get(d, *keys, default=None):
    """Traverses nested dicts safely. Returns default if any key is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _record_downgrade(fields: dict, field_name: str, reason: str) -> None:
    """
    Records a short reason when a field's intraday array was present but
    structurally unparseable, causing the label to fall through to a lower
    tier (v1.6.5.8, F8). Stored under a reserved key inside the fields dict
    — never a real field name, extracted by _maint.py into
    entry["field_downgrades"] and popped before storage.
    """
    fields.setdefault("_downgrade_reasons", {})[field_name] = reason
    log.warning(f"  assess_quality_fields: {field_name} — {reason}")


# ══════════════════════════════════════════════════════════════════════════════
#  Quality assessment (pure, no file IO)
# ══════════════════════════════════════════════════════════════════════════════

def assess_quality(raw: dict) -> str:
    """
    Assesses the quality of a raw data dict based on content.

    Returns one of:
      "high"     — intraday data present (HR values or stress values array)
      "standard" — no intraday, but daily aggregates present — maximum for this device/era
      "failed"   — nothing usable, not even basic stats

    Note: "medium" and "low" are no longer returned. Both collapse to "standard".
    Device-level differentiation is handled via device_rank in quality_log.json.
    assess_quality_fields() still returns "high"/"medium"/"low"/"failed" per endpoint
    — that is internal field-level diagnosis, not user-facing quality.
    """
    # Check for intraday data
    hr = raw.get("heart_rates") or {}
    hr_values = hr.get("heartRateValues") if isinstance(hr, dict) else None
    has_intraday_hr = isinstance(hr_values, list) and len(hr_values) > 0

    stress = raw.get("stress") or {}
    stress_values = stress.get("stressValuesArray") if isinstance(stress, dict) else None
    has_intraday_stress = isinstance(stress_values, list) and len(stress_values) > 0

    if has_intraday_hr or has_intraday_stress:
        return "high"

    # Check for daily aggregates
    stats = raw.get("stats") or {}
    user_summary = raw.get("user_summary") or {}

    has_steps = (
        _safe_get(stats, "totalSteps") is not None or
        _safe_get(user_summary, "totalSteps") is not None
    )
    has_hr_resting = (
        _safe_get(stats, "restingHeartRate") is not None or
        _safe_get(user_summary, "restingHeartRate") is not None
    )

    if has_steps or has_hr_resting:
        return "standard"

    # Check bare minimum — any stats at all
    if isinstance(stats, dict) and stats:
        return "standard"
    if isinstance(user_summary, dict) and user_summary:
        return "standard"

    return "failed"


def assess_quality_fields(raw: dict) -> dict:
    """
    Assesses quality per endpoint from a raw data dict.

    Returns a dict with one quality label per known endpoint:
      "high"   — intraday data present
      "medium" — daily aggregate present, no intraday
      "low"    — minimal data present
      "failed" — endpoint missing or empty

    Pure function — no file IO. Called after assess_quality() in the pipeline.
    """
    fields = {}

    # ── heart_rates ──
    hr = raw.get("heart_rates") or {}
    hr_values = hr.get("heartRateValues") if isinstance(hr, dict) else None
    hr_has_array  = isinstance(hr_values, list) and len(hr_values) > 0
    hr_parseable  = hr_has_array and len(_parse_list_values(hr_values, 1)) > 0
    if hr_parseable:
        fields["heart_rates"] = "high"
    elif isinstance(hr, dict) and hr.get("restingHeartRate") is not None:
        fields["heart_rates"] = "medium"
    elif isinstance(hr, dict) and hr:
        fields["heart_rates"] = "low"
    else:
        fields["heart_rates"] = "failed"
    if hr_has_array and not hr_parseable:
        _record_downgrade(fields, "heart_rates", "array present, not parseable as [ts,val]")

    # ── stress ──
    stress = raw.get("stress") or {}
    stress_values = stress.get("stressValuesArray") if isinstance(stress, dict) else None
    stress_has_array = isinstance(stress_values, list) and len(stress_values) > 0
    stress_parseable = stress_has_array and len(_parse_list_values(stress_values, 1)) > 0
    if stress_parseable:
        fields["stress"] = "high"
    elif isinstance(stress, dict) and stress.get("averageStressLevel") is not None:
        fields["stress"] = "medium"
    elif isinstance(stress, dict) and stress:
        fields["stress"] = "low"
    else:
        fields["stress"] = "failed"
    if stress_has_array and not stress_parseable:
        _record_downgrade(fields, "stress", "array present, not parseable as [ts,val]")

    # ── sleep ──
    sleep = raw.get("sleep") or {}
    has_sleep_intraday = (
        isinstance(sleep, dict) and
        isinstance(sleep.get("sleepLevels"), list) and
        len(sleep["sleepLevels"]) > 0
    )
    has_sleep_aggregate = _safe_get(sleep, "dailySleepDTO", "sleepTimeSeconds") is not None
    if has_sleep_intraday:
        fields["sleep"] = "high"
    elif has_sleep_aggregate:
        fields["sleep"] = "medium"
    elif isinstance(sleep, dict) and sleep:
        fields["sleep"] = "low"
    else:
        fields["sleep"] = "failed"

    # ── hrv ──
    hrv = raw.get("hrv") or {}
    hrv_sum = _safe_get(hrv, "hrvSummary") if isinstance(hrv, dict) else None
    if isinstance(hrv_sum, dict) and hrv_sum.get("lastNight") is not None:
        fields["hrv"] = "medium"
    elif isinstance(hrv, dict) and hrv:
        fields["hrv"] = "low"
    else:
        fields["hrv"] = "failed"

    # ── spo2 ──
    spo2 = raw.get("spo2") or {}
    spo2_readings = spo2.get("spO2HourlyAverages") if isinstance(spo2, dict) else None
    spo2_has_array = isinstance(spo2_readings, list) and len(spo2_readings) > 0
    spo2_parseable = spo2_has_array and len(_parse_list_values(spo2_readings, 1)) > 0
    if spo2_parseable:
        fields["spo2"] = "high"
    elif isinstance(spo2, dict) and spo2.get("averageSpO2") is not None:
        fields["spo2"] = "medium"
    elif isinstance(spo2, dict) and spo2:
        fields["spo2"] = "low"
    else:
        fields["spo2"] = "failed"
    if spo2_has_array and not spo2_parseable:
        _record_downgrade(fields, "spo2", "array present, not parseable as [ts,val]")

    # ── stats ──
    stats = raw.get("stats") or {}
    user_summary = raw.get("user_summary") or {}
    has_steps = (
        _safe_get(stats, "totalSteps") is not None or
        _safe_get(user_summary, "totalSteps") is not None
    )
    if has_steps:
        fields["stats"] = "medium"
    elif (isinstance(stats, dict) and stats) or (isinstance(user_summary, dict) and user_summary):
        fields["stats"] = "low"
    else:
        fields["stats"] = "failed"

    # ── steps ──
    # Intraday array (get_steps_data, 15-min bins) → high.
    # Daily aggregate only (totalSteps in stats/user_summary, reused from
    # the stats-block check above) → medium. Present but empty list → low.
    # Absent entirely → failed. Does not feed assess_quality()'s top-level
    # label — field-level only, same precedent as spo2/body_battery/respiration.
    steps_raw = raw.get("steps")
    if isinstance(steps_raw, list) and len(steps_raw) > 0:
        fields["steps"] = "high"
    elif has_steps:
        fields["steps"] = "medium"
    elif isinstance(steps_raw, list):
        fields["steps"] = "low"
    else:
        fields["steps"] = "failed"

    # ── body_battery ──
    bb = raw.get("body_battery") or {}
    bb_values = bb.get("bodyBatteryValuesArray") if isinstance(bb, dict) else None
    stress_bb = (raw.get("stress") or {}).get("bodyBatteryValuesArray") if isinstance(raw.get("stress"), dict) else None
    bb_has_array = (isinstance(bb_values, list) and len(bb_values) > 0) or \
                   (isinstance(stress_bb, list) and len(stress_bb) > 0)
    # val_index=2 — bodyBatteryValuesArray is a [ts, status, value] triplet
    # (garmin_health_map._FIELD_MAP canonical form), not a [ts, value] pair.
    bb_parseable = (
        (isinstance(stress_bb, list) and len(_parse_list_values(stress_bb, 2)) > 0) or
        (isinstance(bb_values, list) and len(_parse_list_values(bb_values, 2)) > 0)
    )
    if bb_parseable:
        fields["body_battery"] = "high"
    elif isinstance(bb, dict) and bb:
        fields["body_battery"] = "low"
    else:
        fields["body_battery"] = "failed"
    if bb_has_array and not bb_parseable:
        _record_downgrade(fields, "body_battery", "array present, not parseable as [ts,status,val]")

    # ── respiration ──
    resp = raw.get("respiration") or {}
    resp_values = resp.get("respirationValuesArray") if isinstance(resp, dict) else None
    resp_has_array = isinstance(resp_values, list) and len(resp_values) > 0
    resp_parseable = resp_has_array and len(_parse_list_values(resp_values, 1)) > 0
    if resp_parseable:
        fields["respiration"] = "high"
    elif isinstance(resp, dict) and resp.get("avgWakingRespirationValue") is not None:
        fields["respiration"] = "medium"
    elif isinstance(resp, dict) and resp:
        fields["respiration"] = "low"
    else:
        fields["respiration"] = "failed"
    if resp_has_array and not resp_parseable:
        _record_downgrade(fields, "respiration", "array present, not parseable as [ts,val]")

    # ── activities ──
    acts = raw.get("activities")
    if isinstance(acts, list) and len(acts) > 0:
        fields["activities"] = "high"
    else:
        fields["activities"] = "failed"

    # ── training_status ──
    ts = raw.get("training_status") or {}
    if isinstance(ts, dict) and (ts.get("latestTrainingStatus") or ts.get("trainingStatus")):
        fields["training_status"] = "medium"
    elif isinstance(ts, dict) and ts:
        fields["training_status"] = "low"
    else:
        fields["training_status"] = "failed"

    # ── training_readiness ──
    tr = raw.get("training_readiness") or {}
    if isinstance(tr, dict) and (tr.get("score") is not None or tr.get("trainingReadinessScore") is not None):
        fields["training_readiness"] = "medium"
    elif isinstance(tr, dict) and tr.get("level") is not None:
        fields["training_readiness"] = "low"
    elif isinstance(tr, dict) and tr:
        fields["training_readiness"] = "low"
    else:
        fields["training_readiness"] = "failed"

    # ── race_predictions ──
    rp = raw.get("race_predictions") or {}
    if isinstance(rp, dict) and rp:
        fields["race_predictions"] = "medium"
    else:
        fields["race_predictions"] = "failed"

    # ── max_metrics ──
    mm = raw.get("max_metrics") or {}
    if isinstance(mm, dict) and (
        mm.get("vo2MaxPreciseValue") is not None or
        _safe_get(mm, "generic", "vo2MaxPreciseValue") is not None
    ):
        fields["max_metrics"] = "medium"
    elif isinstance(mm, dict) and mm:
        fields["max_metrics"] = "low"
    else:
        fields["max_metrics"] = "failed"

    return fields
