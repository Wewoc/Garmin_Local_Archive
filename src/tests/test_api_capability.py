#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
test_api_capability.py — garmin_api_capability (leaf node)

Run from the project folder:
    python tests/test_api_capability.py

Part of the per-module split of the former test_local.py (v1.7.4.0.2);
shared setup and helpers live in gla_testenv.py.
"""

import json
from unittest.mock import patch

from gla_testenv import cfg  # sets up the environment; must precede garmin_* imports
from support import check, section, summary

# ══════════════════════════════════════════════════════════════════════════════
#  K. garmin_api_capability (v1.6.8 — API-Capability-Scan config, Leaf-Node)
# ══════════════════════════════════════════════════════════════════════════════
section("K. garmin_api_capability (Leaf-Node)")
import garmin_api_capability as capability

check("cfg: CAPABILITY_CONFIG_FILE derived",
      capability.cfg.CAPABILITY_CONFIG_FILE == cfg.LOG_DIR / "garmin_api_capability_config.json")

# ── load_config() ────────────────────────────────────────────────────────────

capability.cfg.CAPABILITY_CONFIG_FILE.unlink(missing_ok=True)

# missing file → fresh default, all 19 candidates not_observed
_cap_cfg_missing = capability.load_config()
check("load_config: missing file → schema_version present",
      _cap_cfg_missing.get("schema_version") == capability.SCHEMA_VERSION)
check("load_config: missing file → 19 endpoints",
      len(_cap_cfg_missing["endpoints"]) == 19)
check("load_config: missing file → all not_observed",
      all(e["status"] == "not_observed" for e in _cap_cfg_missing["endpoints"].values()))
check("load_config: missing file → all disabled",
      all(e["enabled_by_user"] is False for e in _cap_cfg_missing["endpoints"].values()))

# corrupt JSON → default, no exception
capability.cfg.CAPABILITY_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
capability.cfg.CAPABILITY_CONFIG_FILE.write_text("{not valid json", encoding="utf-8")
try:
    _cap_cfg_corrupt = capability.load_config()
    check("load_config: corrupt JSON → no exception", True)
    check("load_config: corrupt JSON → default returned",
          len(_cap_cfg_corrupt["endpoints"]) == 19)
except Exception:
    check("load_config: corrupt JSON → no exception", False)
    check("load_config: corrupt JSON → default returned", False)

# valid JSON, wrong top-level structure (list instead of dict) → default
capability.cfg.CAPABILITY_CONFIG_FILE.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
_cap_cfg_wrong_shape = capability.load_config()
check("load_config: wrong structure (list) → default",
      len(_cap_cfg_wrong_shape["endpoints"]) == 19)

# valid dict but missing 'endpoints' key → default
capability.cfg.CAPABILITY_CONFIG_FILE.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
_cap_cfg_no_endpoints_key = capability.load_config()
check("load_config: missing 'endpoints' key → default",
      len(_cap_cfg_no_endpoints_key["endpoints"]) == 19)

# valid file → parsed content returned unchanged
_cap_cfg_valid = capability.update_endpoint(capability._default_config(),
                                             "get_body_composition", "found",
                                             enabled_by_user=True)
capability.cfg.CAPABILITY_CONFIG_FILE.write_text(json.dumps(_cap_cfg_valid), encoding="utf-8")
_cap_cfg_loaded = capability.load_config()
check("load_config: valid file → status found preserved",
      _cap_cfg_loaded["endpoints"]["get_body_composition"]["status"] == "found")
check("load_config: valid file → enabled_by_user preserved",
      _cap_cfg_loaded["endpoints"]["get_body_composition"]["enabled_by_user"] is True)

# ── save_config() ────────────────────────────────────────────────────────────

capability.cfg.CAPABILITY_CONFIG_FILE.unlink(missing_ok=True)
_cap_save_ok = capability.save_config(capability._default_config())
check("save_config: success → True", _cap_save_ok is True)
check("save_config: file exists after save",
      capability.cfg.CAPABILITY_CONFIG_FILE.exists())

_cap_roundtrip = capability.load_config()
check("save_config round-trip: 19 endpoints",
      len(_cap_roundtrip["endpoints"]) == 19)

# simulated write failure (os.replace raises) → False, no crash
with patch.object(capability.os, "replace", side_effect=OSError("disk full (simuliert)")):
    try:
        _cap_save_fail = capability.save_config(capability._default_config())
        check("save_config: OSError on replace → False, no crash", _cap_save_fail is False)
    except Exception:
        check("save_config: OSError on replace → False, no crash", False)

# ── update_endpoint() ────────────────────────────────────────────────────────

_cap_base = capability._default_config()
_cap_updated = capability.update_endpoint(_cap_base, "get_hydration_data", "found",
                                           enabled_by_user=True,
                                           last_scan="2026-08-14T10:00:00")
check("update_endpoint: pure function — original config unchanged",
      _cap_base["endpoints"]["get_hydration_data"]["status"] == "not_observed")
check("update_endpoint: target endpoint updated",
      _cap_updated["endpoints"]["get_hydration_data"]["status"] == "found")
check("update_endpoint: enabled_by_user set",
      _cap_updated["endpoints"]["get_hydration_data"]["enabled_by_user"] is True)
check("update_endpoint: last_scan set",
      _cap_updated["endpoints"]["get_hydration_data"]["last_scan"] == "2026-08-14T10:00:00")
check("update_endpoint: other endpoints untouched",
      _cap_updated["endpoints"]["get_floors"]["status"] == "not_observed")

for _cap_status in ("found", "not_observed", "error"):
    _cap_status_result = capability.update_endpoint(_cap_base, "get_floors", _cap_status)
    check(f"update_endpoint: status={_cap_status} accepted",
          _cap_status_result["endpoints"]["get_floors"]["status"] == _cap_status)

# invalid status → config unchanged, no exception
_cap_invalid_status = capability.update_endpoint(_cap_base, "get_floors", "banana")
check("update_endpoint: invalid status → config unchanged",
      _cap_invalid_status["endpoints"]["get_floors"]["status"] == "not_observed")

# unknown endpoint → config unchanged, no exception
_cap_unknown_ep = capability.update_endpoint(_cap_base, "get_nonexistent_endpoint", "found")
check("update_endpoint: unknown endpoint → config unchanged",
      "get_nonexistent_endpoint" not in _cap_unknown_ep["endpoints"])

# ── reset_config() ───────────────────────────────────────────────────────────

capability.save_config(_cap_updated)  # non-default state on disk first
_cap_before_reset = capability.cfg.CAPABILITY_CONFIG_FILE.read_text(encoding="utf-8")
_cap_reset = capability.reset_config()
check("reset_config: returns 19 endpoints", len(_cap_reset["endpoints"]) == 19)
check("reset_config: all not_observed",
      all(e["status"] == "not_observed" for e in _cap_reset["endpoints"].values()))
check("reset_config: all disabled",
      all(e["enabled_by_user"] is False for e in _cap_reset["endpoints"].values()))
_cap_after_reset = capability.cfg.CAPABILITY_CONFIG_FILE.read_text(encoding="utf-8")
check("reset_config: no side effect — file on disk unchanged",
      _cap_before_reset == _cap_after_reset)

# ── build_args() / ENDPOINT_ARGS ─────────────────────────────────────────────

check("build_args: single_date default (unlisted endpoint)",
      capability.build_args("get_body_composition", "2026-08-14") == ("2026-08-14",))
check("build_args: no_args → get_pregnancy_summary",
      capability.build_args("get_pregnancy_summary", "2026-08-14") == ())
check("build_args: no_args → get_lactate_threshold",
      capability.build_args("get_lactate_threshold", "2026-08-14") == ())
check("build_args: date_range → get_menstrual_calendar_data",
      capability.build_args("get_menstrual_calendar_data", "2026-08-14") == ("2026-08-14", "2026-08-14"))
check("build_args: date_range → get_calories_daily",
      capability.build_args("get_calories_daily", "2026-08-14") == ("2026-08-14", "2026-08-14"))
check("build_args: date_range → get_running_tolerance",
      capability.build_args("get_running_tolerance", "2026-08-14") == ("2026-08-14", "2026-08-14"))

# ── get_enabled_candidates() (v1.6.8.1 — extracted from garmin_collector's
#    fetch-loop double-gate filter, see NOTES_v1681_01.md) ───────────────────

_gec_base = capability._default_config()

# both gates satisfied → endpoint included
_gec_both = capability.update_endpoint(_gec_base, "get_hydration_data", "found",
                                        enabled_by_user=True)
check("get_enabled_candidates: both gates satisfied → included",
      "get_hydration_data" in capability.get_enabled_candidates(_gec_both))

# status == "found" but enabled_by_user missing/False → excluded
_gec_found_only = capability.update_endpoint(_gec_base, "get_hydration_data", "found")
check("get_enabled_candidates: found but not enabled_by_user → excluded",
      "get_hydration_data" not in capability.get_enabled_candidates(_gec_found_only))

# enabled_by_user == True but status != "found" → excluded
_gec_enabled_only = capability.update_endpoint(_gec_base, "get_hydration_data", "not_observed",
                                                enabled_by_user=True)
check("get_enabled_candidates: enabled_by_user but not found → excluded",
      "get_hydration_data" not in capability.get_enabled_candidates(_gec_enabled_only))

# endpoint missing from endpoints dict entirely → excluded, no KeyError
_gec_missing = dict(_gec_base)
_gec_missing["endpoints"] = {k: v for k, v in _gec_base["endpoints"].items()
                              if k != "get_hydration_data"}
try:
    _gec_missing_result = capability.get_enabled_candidates(_gec_missing)
    check("get_enabled_candidates: endpoint missing from dict → no crash",
          "get_hydration_data" not in _gec_missing_result)
except Exception:
    check("get_enabled_candidates: endpoint missing from dict → no crash", False)

# empty endpoints dict → empty list, no crash
_gec_empty = dict(_gec_base)
_gec_empty["endpoints"] = {}
check("get_enabled_candidates: empty endpoints dict → empty list",
      capability.get_enabled_candidates(_gec_empty) == [])

# multiple enabled candidates → order follows CANDIDATE_ENDPOINTS
_gec_multi = capability.update_endpoint(_gec_base, "get_floors", "found", enabled_by_user=True)
_gec_multi = capability.update_endpoint(_gec_multi, "get_hydration_data", "found", enabled_by_user=True)
_gec_multi_result = capability.get_enabled_candidates(_gec_multi)
check("get_enabled_candidates: multiple enabled → both included",
      "get_hydration_data" in _gec_multi_result and "get_floors" in _gec_multi_result)
check("get_enabled_candidates: order follows CANDIDATE_ENDPOINTS",
      _gec_multi_result == [ep for ep in capability.CANDIDATE_ENDPOINTS if ep in _gec_multi_result])

# cleanup
capability.cfg.CAPABILITY_CONFIG_FILE.unlink(missing_ok=True)

summary()
