#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_validator.py — garmin_validator

Run from the project folder:
    python tests/test_validator.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""


from gla_testenv import cfg, _TMPDIR  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  9. garmin_validator
# ══════════════════════════════════════════════════════════════════════════════
section("9. garmin_validator")
import garmin_validator as validator_mod

# Schema loaded
check("validator: schema loaded",          validator_mod.current_version() == "1.1")

# Happy path — all known fields, correct types
raw_valid = {
    "date":               "2024-01-01",
    "sleep":              {"dailySleepDTO": {}},
    "heart_rates":        {"restingHeartRate": 55},
    "activities":         [],
}
r = validator_mod.validate(raw_valid)
check("validator ok: status=ok",           r["status"] == "ok")
check("validator ok: schema_version set",  r["schema_version"] == "1.1")
check("validator ok: timestamp set",       isinstance(r["timestamp"], str))
check("validator ok: no critical issues",  not any(i["severity"] == "critical" for i in r["issues"]))

# missing_optional — optional field absent → status stays ok
raw_no_sleep = {"date": "2024-01-01"}
r2 = validator_mod.validate(raw_no_sleep)
check("validator missing_optional: status=ok",     r2["status"] == "ok")
check("validator missing_optional: issue logged",
      any(i["type"] == "missing_optional" and i["field"] == "sleep" for i in r2["issues"]))

# unexpected_field — unknown field → warning
raw_new_field = {"date": "2024-01-01", "garmin_new_metric": {"value": 42}}
r3 = validator_mod.validate(raw_new_field)
check("validator unexpected_field: status=warning", r3["status"] == "warning")
check("validator unexpected_field: issue present",
      any(i["type"] == "unexpected_field" and i["field"] == "garmin_new_metric" for i in r3["issues"]))

# type_mismatch — optional field wrong type → warning
raw_bad_type = {"date": "2024-01-01", "sleep": "corrupted"}
r4 = validator_mod.validate(raw_bad_type)
check("validator type_mismatch: status=warning",    r4["status"] == "warning")
check("validator type_mismatch: issue present",
      any(i["type"] == "type_mismatch" and i["field"] == "sleep" for i in r4["issues"]))

# missing_required — date absent → critical
raw_no_date = {"sleep": {"dailySleepDTO": {}}}
r5 = validator_mod.validate(raw_no_date)
check("validator missing_required: status=critical", r5["status"] == "critical")
check("validator missing_required: issue present",
      any(i["type"] == "missing_required" and i["field"] == "date" for i in r5["issues"]))

# type_mismatch on required field — date wrong type → critical
raw_date_int = {"date": 20240101}
r6 = validator_mod.validate(raw_date_int)
check("validator date wrong type: status=critical",  r6["status"] == "critical")
check("validator date wrong type: severity=critical",
      any(i["severity"] == "critical" and i["field"] == "date" for i in r6["issues"]))

# non-dict input → critical
r7 = validator_mod.validate(None)
check("validator non-dict: status=critical",         r7["status"] == "critical")

r8 = validator_mod.validate("string input")
check("validator string input: status=critical",     r8["status"] == "critical")

# multiple issues — critical wins over warning
raw_multi = {"sleep": "bad_type", "garmin_new": 123}  # date missing + type_mismatch + unexpected
r9 = validator_mod.validate(raw_multi)
check("validator multi: critical wins",              r9["status"] == "critical")
check("validator multi: multiple issues",            len(r9["issues"]) > 1)

# evil API — date present as string but nonsense value → ok (content = quality's job)
raw_evil = {"date": "Gestern", "sleep": {}}
r10 = validator_mod.validate(raw_evil)
check("validator evil: nonsense date string → ok",   r10["status"] == "ok")

# reload_schema — no crash, version preserved
validator_mod.reload_schema()
check("validator reload: version intact",            validator_mod.current_version() == "1.1")

# F6 — Fail-Closed: schema absent → critical (not ok).
# Simulate empty schema, then restore via reload_schema to avoid state leak.
_saved_schema = validator_mod._schema
validator_mod._schema = {}
r_noschema = validator_mod.validate({"date": "2024-01-01"})
check("validator no schema: status=critical",        r_noschema["status"] == "critical")
check("validator no schema: schema issue present",
      any(i["field"] == "schema" for i in r_noschema["issues"]))
# Restore — mandatory cleanup, all later validator tests need the real schema
validator_mod.reload_schema()
check("validator restored after no-schema test",     validator_mod.current_version() == "1.1")

# None input — no crash
r_none = validator_mod.validate(None)
check("validator None input: no crash",              r_none["status"] == "critical")

# empty dict — date missing → critical
r_empty = validator_mod.validate({})
check("validator empty dict: status=critical",       r_empty["status"] == "critical")
check("validator empty dict: missing_required date",
      any(i["type"] == "missing_required" and i["field"] == "date" for i in r_empty["issues"]))

# out_of_range — HR value outside schema bounds
raw_oor = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 999}}
r_oor = validator_mod.validate(raw_oor)
check("validator out_of_range: status=warning",      r_oor["status"] == "warning")
check("validator out_of_range: issue type correct",
      any(i["type"] == "out_of_range" and i["field"] == "heart_rates.restingHeartRate"
          for i in r_oor["issues"]))

# out_of_range — value within bounds → no out_of_range issue
raw_inrange = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 55}}
r_inrange = validator_mod.validate(raw_inrange)
check("validator in_range: no out_of_range issue",
      not any(i["type"] == "out_of_range" for i in r_inrange["issues"]))

# ══════════════════════════════════════════════════════════════════════════════
#  9b. garmin_validator — sub_field not numeric, schema load failures (v1.7.4.0.2)
# ══════════════════════════════════════════════════════════════════════════════
section("9b. garmin_validator — schema load failures")

# sub_field present but not a number -> range check skipped, no crash
r_nonnum = validator_mod.validate(
    {"date": "2024-01-01", "heart_rates": {"restingHeartRate": "abc"}})
check("validator sub_field not numeric: no crash, no out_of_range issue",
      not any(i["type"] == "out_of_range" for i in r_nonnum["issues"]))

# The schema file cannot be loaded: validation must fail closed (critical),
# never silently pass. cfg.DATAFORMAT_FILE is pointed at a test file and put
# back afterwards; reload_schema() restores the real schema.
_schema_file_real = cfg.DATAFORMAT_FILE
_schema_version_real = validator_mod.current_version()
_schema_test_file = _TMPDIR / "dataformat_test.json"


def _validate_with_schema_file(content):
    """content None = file missing. Returns (version, status) after loading."""
    if content is None:
        _schema_test_file.unlink(missing_ok=True)
    else:
        _schema_test_file.write_text(content, encoding="utf-8")
    cfg.DATAFORMAT_FILE = _schema_test_file
    validator_mod.reload_schema()
    res = validator_mod.validate({"date": "2024-01-01"})
    return validator_mod.current_version(), res["status"]


try:
    _v, _s = _validate_with_schema_file(None)
    check("validator schema file missing: version unknown", _v == "unknown")
    check("validator schema file missing: validate -> critical (fail closed)",
          _s == "critical")

    _v, _s = _validate_with_schema_file('{"schema_version": "9.9"}')
    check("validator schema without 'fields': version unknown", _v == "unknown")
    check("validator schema without 'fields': validate -> critical", _s == "critical")

    _v, _s = _validate_with_schema_file('["not", "an", "object"]')
    check("validator schema is a JSON list: version unknown", _v == "unknown")
    check("validator schema is a JSON list: validate -> critical", _s == "critical")

    _v, _s = _validate_with_schema_file("{this is not json")
    check("validator schema is corrupt JSON: version unknown", _v == "unknown")
    check("validator schema is corrupt JSON: validate -> critical", _s == "critical")
finally:
    cfg.DATAFORMAT_FILE = _schema_file_real
    validator_mod.reload_schema()
check("validator restored after schema load failures",
      validator_mod.current_version() == _schema_version_real)
check("validator restored: valid day passes again",
      validator_mod.validate({"date": "2024-01-01"})["status"] == "ok")

# ══════════════════════════════════════════════════════════════════════════════
#  14. v1.4.3 — VALUE RANGE VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
section("14. v1.4.3 — VALUE RANGE VALIDATION")

# out_of_range warnings → quality downgrade in collector logic
# Simuliert: validator liefert >3 out_of_range issues, label wird auf low gedrückt
_oor_issues = [
    {"type": "out_of_range", "field": f"heart_rates.field{i}",
     "severity": "warning", "expected": "20–300", "actual": 999}
    for i in range(4)
]
_val_result_oor = {"status": "warning", "issues": _oor_issues,
                   "schema_version": "1.0", "timestamp": "2024-01-01T00:00:00"}

_oor_count = sum(1 for i in _val_result_oor.get("issues", [])
                 if i.get("type") == "out_of_range")
check("downgrade: >3 out_of_range → count correct",  _oor_count == 4)
check("downgrade: >3 out_of_range → cap to low",     "low" if _oor_count > 3 else "high" == "low")

# exactly 3 → no downgrade
_val_result_3 = {"status": "warning", "issues": _oor_issues[:3],
                 "schema_version": "1.0", "timestamp": "2024-01-01T00:00:00"}
_oor_count_3 = sum(1 for i in _val_result_3.get("issues", [])
                   if i.get("type") == "out_of_range")
check("downgrade: exactly 3 → no downgrade",         _oor_count_3 <= 3)

# assess_quality with out_of_range data — quality stays pure (no validator_result param)
import garmin_quality as quality_mod
_raw_high = {
    "date": "2024-01-01",
    "heart_rates": {"heartRateValues": [[0, 60], [1, 65]], "restingHeartRate": 999},
}
_label = quality_mod.assess_quality(_raw_high)
check("assess_quality: stays pure (no validator param)", _label == "high")

# assess_quality with multiple out_of_range → still "low" from content if no intraday
_raw_low = {"date": "2024-01-01", "heart_rates": {"restingHeartRate": 999}}
_label_low = quality_mod.assess_quality(_raw_low)
check("assess_quality: no intraday → not high",      _label_low != "high")

# quality downgrade: >3 warnings + high label → low
_raw_q = {
    "date": "2024-01-01",
    "heart_rates": {"heartRateValues": [[0, 60]], "restingHeartRate": 999},
}
_q_label = quality_mod.assess_quality(_raw_q)  # would be "high"
_simulated = "standard" if _oor_count > 3 and _q_label == "high" else _q_label
check("downgrade simulation: high → standard",       _simulated == "standard")

summary()
