#!/usr/bin/env python3
"""
garmin_validator.py

Validator — structural integrity check at the pipeline entry point.

Validates incoming raw dicts against garmin_dataformat.json before they
reach garmin_normalizer.py. Checks structure only — not content.
Content evaluation (plausibility, ranges, missing measurements) remains
the responsibility of garmin_quality.py.

Responsibilities:
  - Load and cache garmin_dataformat.json at module import
  - Validate raw dict structure against the schema
  - Return a structured result object for every call
  - Never modify the raw dict — read only
  - Never write files, never access quality_log.json

Public functions:
  validate(raw)       → dict   — validate raw dict, return result object
  reload_schema()     → None   — reload schema from disk (self-healing loop)
  current_version()   → str    — return cached schema version string

Result object structure:
  {
    "status":         "ok" | "warning" | "critical",
    "schema_version": "1.0",
    "timestamp":      "2026-04-06T12:00:00",
    "issues": [
      {
        "field":    "sleep",
        "type":     "type_mismatch" | "missing_required" | "missing_optional" | "unexpected_field",
        "expected": "dict",
        "actual":   "str",
        "severity": "critical" | "warning" | "info"
      }
    ]
  }

Issue types:
  missing_required  — required field absent or wrong type  → critical
  type_mismatch     — known field present but wrong type   → warning (or critical if required)
  missing_optional  — optional field absent                → info (status stays ok)
  unexpected_field  — field not in schema                  → warning

No file IO after module load. No imports from other project modules
except garmin_config (leaf-node constraint).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  Type map — JSON type strings → Python types
# ══════════════════════════════════════════════════════════════════════════════

_TYPE_MAP: dict = {
    "str":   str,
    "int":   int,
    "float": float,
    "dict":  dict,
    "list":  list,
    "bool":  bool,
}

# ══════════════════════════════════════════════════════════════════════════════
#  Schema cache — loaded once at module import
# ══════════════════════════════════════════════════════════════════════════════

_schema: dict = {}
_schema_version: str = "unknown"


def _load_schema() -> None:
    """
    Loads garmin_dataformat.json into module-level cache.
    Called at module import and by reload_schema().
    Logs a warning if the file is missing or corrupt — does not raise.
    """
    global _schema, _schema_version

    path = cfg.DATAFORMAT_FILE

    if not path.exists():
        log.warning(f"[VALIDATOR] Schema file not found: {path} — validation disabled")
        _schema = {}
        _schema_version = "unknown"
        return

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict) or "fields" not in data:
            log.warning("[VALIDATOR] Schema file has unexpected structure — validation disabled")
            _schema = {}
            _schema_version = "unknown"
            return

        _schema = data.get("fields", {})
        _schema_version = str(data.get("schema_version", "unknown"))
        log.debug(f"[VALIDATOR] Schema loaded — version {_schema_version}, "
                  f"{len(_schema)} fields defined")

    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"[VALIDATOR] Failed to load schema: {exc} — validation disabled")
        _schema = {}
        _schema_version = "unknown"


# Load at module import
_load_schema()


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def reload_schema() -> None:
    """
    Reloads garmin_dataformat.json from disk.
    Called by the self-healing loop in garmin_collector.py after a
    schema version mismatch is detected.
    """
    log.info("[VALIDATOR] Reloading schema from disk ...")
    _load_schema()


def current_version() -> str:
    """Returns the currently cached schema version string."""
    return _schema_version


def validate(raw: dict) -> dict:
    """
    Validates a raw dict against the cached schema.

    Checks structure only — field presence and types.
    Does not modify the raw dict.
    Always returns a result object, even if the schema is not loaded.

    Parameters
    ----------
    raw : dict — raw data as returned by garmin_api.fetch_raw() or
                 garmin_import.load_bulk(), before normalization.

    Returns
    -------
    dict — result object with keys: status, schema_version, timestamp, issues
    """
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    issues = []

    # Schema not loaded — pass through without validation
    if not _schema:
        log.warning("[VALIDATOR] No schema loaded — skipping structural validation")
        return _result("ok", timestamp, issues)

    # Input must be a dict
    if not isinstance(raw, dict):
        issues.append({
            "field":    "root",
            "type":     "missing_required",
            "expected": "dict",
            "actual":   type(raw).__name__,
            "severity": "critical",
        })
        _log_issue("critical", "<unknown>",
                   f"Input is not a dict (got {type(raw).__name__})."
                   f" Day skipped to prevent archive corruption.")
        return _result("critical", timestamp, issues)

    date_str = str(raw.get("date", "<unknown>"))

    # ── Check all schema-defined fields ──────────────────────────────────────

    for field, spec in _schema.items():
        required      = spec.get("required", False)
        type_str      = spec.get("type", "")
        expected_type = _TYPE_MAP.get(type_str)

        if field not in raw:
            if required:
                issues.append({
                    "field":    field,
                    "type":     "missing_required",
                    "expected": type_str,
                    "actual":   "absent",
                    "severity": "critical",
                })
                _log_issue("critical", date_str,
                           f"Missing required field '{field}'."
                           f" Day skipped to prevent archive corruption.")
            else:
                issues.append({
                    "field":    field,
                    "type":     "missing_optional",
                    "expected": type_str,
                    "actual":   "absent",
                    "severity": "info",
                })
                # info only — no log output for normally absent optional fields
            continue

        # Field is present — check type
        value    = raw[field]
        if expected_type is not None and not isinstance(value, expected_type):
            severity = "critical" if required else "warning"
            issues.append({
                "field":    field,
                "type":     "type_mismatch",
                "expected": type_str,
                "actual":   type(value).__name__,
                "severity": severity,
            })
            if severity == "critical":
                _log_issue("critical", date_str,
                           f"Required field '{field}' has wrong type "
                           f"(expected {type_str}, got {type(value).__name__})."
                           f" Day skipped to prevent archive corruption.")
            else:
                _log_issue("warning", date_str,
                           f"Field '{field}' has invalid type "
                           f"(expected {type_str}, got {type(value).__name__})."
                           f" Proceeding in degraded mode.")

    # ── Check for unexpected fields ───────────────────────────────────────────

    for field in raw:
        if field not in _schema:
            issues.append({
                "field":    field,
                "type":     "unexpected_field",
                "expected": "absent",
                "actual":   type(raw[field]).__name__,
                "severity": "warning",
            })
            _log_issue("warning", date_str,
                       f"Unexpected field '{field}' — not in schema {_schema_version}."
                       f" Consider updating garmin_dataformat.json.")

    # ── Derive final status ───────────────────────────────────────────────────

    status = _derive_status(issues)
    return _result(status, timestamp, issues)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _derive_status(issues: list) -> str:
    """
    Derives the overall status from the issue list.
    critical > warning > ok.
    missing_optional (severity=info) does not affect status.
    """
    severities = {i["severity"] for i in issues}
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "ok"


def _result(status: str, timestamp: str, issues: list) -> dict:
    """Assembles the standard result object."""
    return {
        "status":         status,
        "schema_version": _schema_version,
        "timestamp":      timestamp,
        "issues":         issues,
    }


def _log_issue(level: str, date_str: str, message: str) -> None:
    """Emits a formatted validator log line."""
    tag = level.upper()
    if level in ("critical", "warning"):
        log.warning(f"[VALIDATOR] [{tag}] {date_str}: {message}")
    else:
        log.debug(f"[VALIDATOR] [{tag}] {date_str}: {message}")
