#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_local.py — Garmin Local Archive: cross-module tests of the Garmin pipeline

Determinism, invariants, robustness against dirty input and one end-to-end run
(normalize -> validate -> quality -> write -> read back). Each of these checks
several modules together; the tests of a single module live in their own file
(test_normalizer.py, test_validator.py, test_writer.py, test_quality.py,
test_collector.py, ...). Until v1.7.4.0.2 this file held all of them.

Run from the project folder:
    python tests/test_local.py

No external dependencies beyond what the project already requires.
No network, no GUI, no Garmin API calls.
Cleans up after itself — leaves no files behind.
"""

from copy import deepcopy
from datetime import date
from unittest.mock import patch

from gla_testenv import raw_full, mock_client  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

import garmin_collector as collector
import garmin_normalizer as normalizer
import garmin_quality as quality
import garmin_validator as validator_mod
import garmin_writer as writer

# ══════════════════════════════════════════════════════════════════════════════
#  11. DETERMINISM
# ══════════════════════════════════════════════════════════════════════════════
section("11. DETERMINISM")

r1 = normalizer.summarize(raw_full)
r2 = normalizer.summarize(raw_full)
check("determinism: summarize stable",       r1 == r2)

def _strip_val_timestamp(result: tuple) -> tuple:
    """Remove timestamp from val_result before comparison — datetime.now() causes flakiness."""
    label, norm, summ, fields, val = result
    val_no_ts = {k: v for k, v in val.items() if k != "timestamp"}
    return (label, norm, summ, fields, val_no_ts)

with patch("garmin_collector.api.fetch_raw", return_value=(raw_full, [])):
    rd1 = collector._fetch_and_assess(mock_client, "2024-03-15")
    rd2 = collector._fetch_and_assess(mock_client, "2024-03-15")
check("determinism: fetch_and_assess stable", _strip_val_timestamp(rd1) == _strip_val_timestamp(rd2))

# ══════════════════════════════════════════════════════════════════════════════
#  12. INVARIANTS
# ══════════════════════════════════════════════════════════════════════════════
section("12. INVARIANTS")

# Quality darf nicht downgraden
data_inv = {"first_day": None, "devices": [], "days": []}
quality._upsert_quality(data_inv, date(2024, 9, 1), "high", "Quality: high", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 1), "low",  "Quality: low",  written=True)
check("invariant: high not downgraded to low",    data_inv["days"][0]["quality"] == "high")

quality._upsert_quality(data_inv, date(2024, 9, 2), "standard", "Quality: standard", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 2), "failed", "API error",           written=False)
check("invariant: standard not downgraded to failed", data_inv["days"][1]["quality"] == "standard")

quality._upsert_quality(data_inv, date(2024, 9, 3), "high", "Quality: high", written=True)
quality._upsert_quality(data_inv, date(2024, 9, 3), "high", "Quality: high", written=True)
check("invariant: high stays high on repeat",     data_inv["days"][2]["quality"] == "high")

# Failed darf niemals schreiben — explizit als Invariante
with patch("garmin_collector.api.fetch_raw", return_value=({"date": "2024-01-01"}, [])), \
     patch("garmin_collector.writer.write_day") as mock_w:
    label_inv, _, _, _, _ = collector._fetch_and_assess(mock_client, "2024-01-01")
check("invariant: failed never writes",  label_inv == "failed" and not mock_w.called)

# ══════════════════════════════════════════════════════════════════════════════
#  12. ROBUSTNESS — Dirty Input
# ══════════════════════════════════════════════════════════════════════════════
section("12. ROBUSTNESS")

# Validator: fehlende Pflichtfelder blockieren zwingend
r_no_date = validator_mod.validate({"sleep": {}, "heart_rates": {}})
check("robustness: missing date → critical",      r_no_date["status"] == "critical")

# Validator: falsche Typen erkannt
r_wrong_type = validator_mod.validate({"date": "2024-01-01", "sleep": "corrupted", "heart_rates": "60"})
check("robustness: wrong types → warning/critical", r_wrong_type["status"] in ("warning", "critical"))

# Validator: None-Input kein Crash
r_none = validator_mod.validate(None)
check("robustness: None input → critical, no crash", r_none["status"] == "critical")

# Validator: leeres Dict kein Crash
r_empty = validator_mod.validate({})
check("robustness: empty dict → critical, no crash", r_empty["status"] == "critical")

# Normalizer: leere Hülle — kein Crash, kein Exception
raw_shell = {"date": "2024-01-01", "sleep": None, "heart_rates": None, "activities": []}
try:
    s_shell = normalizer.summarize(raw_shell)
    check("robustness: empty shell no crash",     isinstance(s_shell, dict))
    check("robustness: empty shell date correct", s_shell.get("date") == "2024-01-01")
except Exception:
    check("robustness: empty shell no crash",     False)
    check("robustness: empty shell date correct", False)

# Normalizer: raw nicht mutiert durch summarize
raw_immut = {"date": "2024-06-01", "heart_rates": {"restingHeartRate": 55}}
raw_before = deepcopy(raw_immut)
normalizer.summarize(raw_immut)
check("robustness: raw not mutated by summarize", raw_immut == raw_before)

# Normalizer: absurde Werte — kein Crash
raw_garbage = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 9999},
               "user_summary": {"totalSteps": -500}}
try:
    s_garbage = normalizer.summarize(raw_garbage)
    check("robustness: garbage values no crash", isinstance(s_garbage, dict))
except Exception:
    check("robustness: garbage values no crash", False)

# ══════════════════════════════════════════════════════════════════════════════
#  13. PIPELINE_E2E
# ══════════════════════════════════════════════════════════════════════════════
section("13. PIPELINE_E2E")

raw_e2e = {
    "date": "2024-07-15",
    "heart_rates": {"restingHeartRate": 58, "heartRateValues": [[0, 58], [60, 62]]},
    "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 27000}},
    "user_summary": {"totalSteps": 7200},
}

# normalize → validate → quality → write → read back
val_e2e  = validator_mod.validate(raw_e2e)
check("e2e: validator ok",            val_e2e["status"] == "ok")

norm_e2e = normalizer.normalize(raw_e2e, "api")
check("e2e: normalize returns dict",  isinstance(norm_e2e, dict))
check("e2e: date preserved",          norm_e2e.get("date") == "2024-07-15")

summ_e2e = normalizer.summarize(raw_e2e)
q_e2e    = quality.assess_quality(raw_e2e)
check("e2e: quality = high",          q_e2e == "high")

ok_e2e   = writer.write_day(raw_e2e, summ_e2e, "2024-07-15")
check("e2e: write_day ok",            ok_e2e == True)

read_e2e = writer.read_raw("2024-07-15")
check("e2e: read_raw returns dict",   isinstance(read_e2e, dict))
check("e2e: read_raw date correct",   read_e2e.get("date") == "2024-07-15")
check("e2e: read_raw content intact", read_e2e.get("heart_rates", {}).get("restingHeartRate") == 58)

summary()
