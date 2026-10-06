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
#  9c. garmin_validator — critical path, loop continuation, range limits (v1.7.4.0.3)
#  Closes the survivors of the mutation test: the "critical" branch, the three
#  `continue` statements of the loops, the range limits and the `required` default.
# ══════════════════════════════════════════════════════════════════════════════
section("9c. garmin_validator — critical path, loops, range limits")


class _LogRec:
    """Stands in for validator_mod.log and records (level, message)."""
    def __init__(self):
        self.calls = []

    def warning(self, msg, *a, **k):
        self.calls.append(("warning", msg))

    def debug(self, msg, *a, **k):
        self.calls.append(("debug", msg))

    def info(self, msg, *a, **k):
        self.calls.append(("info", msg))


def _validate_logged(raw):
    """validate(raw) with the validator's logger recorded. Returns (result, calls)."""
    real, rec = validator_mod.log, _LogRec()
    validator_mod.log = rec
    try:
        return validator_mod.validate(raw), rec.calls
    finally:
        validator_mod.log = real


def _types(res, field):
    return [i["type"] for i in res["issues"] if i["field"] == field]


# 1. Required field missing — exact issue
_r = validator_mod.validate({})
check("9c required missing: status critical", _r["status"] == "critical")
check("9c required missing: exact issue",
      [i for i in _r["issues"] if i["field"] == "date"] == [
          {"field": "date", "type": "missing_required", "expected": "str",
           "actual": "absent", "severity": "critical"}])

# 2. Required field with the wrong type -> critical
_r = validator_mod.validate({"date": 20240101})
_iss = [i for i in _r["issues"] if i["field"] == "date"]
check("9c required wrong type: status critical", _r["status"] == "critical")
check("9c required wrong type: exact issue",
      _iss == [{"field": "date", "type": "type_mismatch", "expected": "str",
                "actual": "int", "severity": "critical"}])

# 3. Optional field with the wrong type -> warning
_r = validator_mod.validate({"date": "2024-01-01", "sleep": "x"})
_iss = [i for i in _r["issues"] if i["field"] == "sleep"]
check("9c optional wrong type: status warning", _r["status"] == "warning")
check("9c optional wrong type: exact issue",
      _iss == [{"field": "sleep", "type": "type_mismatch", "expected": "dict",
                "actual": "str", "severity": "warning"}])

# 4. Log lines: the critical and the warning case are told apart
_, _calls = _validate_logged({})
check("9c log: required missing -> one warning-level line with CRITICAL",
      len(_calls) == 1 and _calls[0][0] == "warning"
      and "[VALIDATOR] [CRITICAL]" in _calls[0][1]
      and "Missing required field 'date'" in _calls[0][1]
      and "Day skipped to prevent archive corruption" in _calls[0][1])
_, _calls = _validate_logged({"date": 20240101})
check("9c log: required wrong type -> CRITICAL, day skipped",
      len(_calls) == 1 and "[VALIDATOR] [CRITICAL] 20240101:" in _calls[0][1]
      and "wrong type" in _calls[0][1] and "Day skipped" in _calls[0][1]
      and "degraded" not in _calls[0][1])
_, _calls = _validate_logged({"date": "2024-01-01", "sleep": "x"})
check("9c log: optional wrong type -> WARNING, degraded mode",
      len(_calls) == 1 and "[VALIDATOR] [WARNING] 2024-01-01:" in _calls[0][1]
      and "degraded mode" in _calls[0][1] and "CRITICAL" not in _calls[0][1])
_, _calls = _validate_logged({"date": "2024-01-01", "garmin_new_metric": 1})
check("9c log: unexpected field -> WARNING",
      len(_calls) == 1 and "[VALIDATOR] [WARNING]" in _calls[0][1]
      and "Unexpected field 'garmin_new_metric'" in _calls[0][1])
_, _calls = _validate_logged({"date": "2024-01-01"})
check("9c log: clean day logs nothing at warning level",
      not any(lvl == "warning" for lvl, _ in _calls))

# 5. _log_issue: critical/warning go to warning, everything else to debug
_real_log, _rec = validator_mod.log, _LogRec()
validator_mod.log = _rec
try:
    validator_mod._log_issue("critical", "d", "m")
    validator_mod._log_issue("warning", "d", "m")
    validator_mod._log_issue("info", "d", "m")
finally:
    validator_mod.log = _real_log
check("9c _log_issue: levels and format",
      _rec.calls == [("warning", "[VALIDATOR] [CRITICAL] d: m"),
                     ("warning", "[VALIDATOR] [WARNING] d: m"),
                     ("debug", "[VALIDATOR] [INFO] d: m")])

# Controlled schema for the loop and limit tests (restored by reload_schema())
_S = {
    "date":    {"type": "str", "required": True},
    "opt1":    {"type": "dict"},                       # no "required" key
    "mid":     {"type": "dict", "required": False,
                "sub_fields": {"x": {"min": 0, "max": 10}, "y": {"min": 0, "max": 10}}},
    "last":    {"type": "list", "required": False},
    "lo_only": {"type": "dict", "required": False, "sub_fields": {"v": {"min": 5}}},
    "hi_only": {"type": "dict", "required": False, "sub_fields": {"v": {"max": 5}}},
    "must":    {"type": "int", "required": True},
}


def _check_custom(raw):
    validator_mod._schema = _S
    return validator_mod.validate(raw)


try:
    # 6. An absent optional field does not end the field loop
    _r = _check_custom({"date": "d", "last": "x", "must": 1})
    check("9c loop: field after absent optionals is still checked",
          _types(_r, "last") == ["type_mismatch"])
    _r = _check_custom({"date": "d"})
    check("9c loop: required field behind absent optionals is still reported",
          _types(_r, "must") == ["missing_required"] and _r["status"] == "critical")

    # 11. A field without "required" is optional (default False)
    _r = _check_custom({"date": "d", "must": 1})
    check("9c default: field without 'required' is optional",
          _types(_r, "opt1") == ["missing_optional"] and _r["status"] == "ok")

    # 7./8. An absent, None or non-numeric sub_field does not end the sub_field loop
    _r = _check_custom({"date": "d", "must": 1, "mid": {"y": 99}})
    check("9c sub loop: absent sub_field, next one still checked",
          _types(_r, "mid.y") == ["out_of_range"] and _types(_r, "mid.x") == [])
    _r = _check_custom({"date": "d", "must": 1, "mid": {"x": "n/a", "y": 99}})
    check("9c sub loop: non-numeric sub_field, next one still checked",
          _types(_r, "mid.y") == ["out_of_range"] and _types(_r, "mid.x") == [])
    _r = _check_custom({"date": "d", "must": 1, "mid": {"x": None, "y": 99}})
    check("9c sub loop: None sub_field, next one still checked",
          _types(_r, "mid.y") == ["out_of_range"])

    # 9. Range limits: inclusive at both ends
    for _val, _flag in [(0, False), (10, False), (5, False), (-1, True), (11, True),
                        (10.5, True), (-0.1, True), (0.0, False)]:
        _r = _check_custom({"date": "d", "must": 1, "mid": {"x": _val}})
        check(f"9c range x={_val}: {'flagged' if _flag else 'ok'}",
              (_types(_r, "mid.x") == ["out_of_range"]) == _flag)
    _r = _check_custom({"date": "d", "must": 1, "mid": {"x": 11}})
    _oor = [i for i in _r["issues"] if i["field"] == "mid.x"]
    check("9c range: exact out_of_range issue",
          _oor == [{"field": "mid.x", "type": "out_of_range", "expected": "0–10",
                    "actual": 11, "severity": "warning"}])
    check("9c range: out_of_range -> status warning", _r["status"] == "warning")

    # 10. Only a minimum / only a maximum
    for _val, _flag in [(4, True), (5, False), (1000, False)]:
        _r = _check_custom({"date": "d", "must": 1, "lo_only": {"v": _val}})
        check(f"9c min only v={_val}: {'flagged' if _flag else 'ok'}",
              (_types(_r, "lo_only.v") == ["out_of_range"]) == _flag)
    for _val, _flag in [(6, True), (5, False), (-1000, False)]:
        _r = _check_custom({"date": "d", "must": 1, "hi_only": {"v": _val}})
        check(f"9c max only v={_val}: {'flagged' if _flag else 'ok'}",
              (_types(_r, "hi_only.v") == ["out_of_range"]) == _flag)
finally:
    validator_mod.reload_schema()

# Range limits of the shipped schema (heart_rates.restingHeartRate 20-300)
for _val, _flag in [(20, False), (300, False), (19, True), (301, True)]:
    _r = validator_mod.validate({"date": "2024-01-01", "heart_rates": {"restingHeartRate": _val}})
    check(f"9c shipped schema restingHeartRate={_val}: {'flagged' if _flag else 'ok'}",
          (_types(_r, "heart_rates.restingHeartRate") == ["out_of_range"]) == _flag)
check("9c restored: shipped schema active again",
      validator_mod.current_version() == _schema_version_real)

# ══════════════════════════════════════════════════════════════════════════════
#  14. v1.4.3 — assess_quality ignores out-of-range values (stays pure)
#  (v1.7.4.0.3: the simulated "downgrade" checks that only recomputed the rule inside
#  the test were removed — the real downgrade runs through _fetch_and_assess() in
#  test_collector.py, the validator's own range check is covered in 9 and 9c)
# ══════════════════════════════════════════════════════════════════════════════
section("14. v1.4.3 — assess_quality stays pure with out-of-range data")

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

summary()
