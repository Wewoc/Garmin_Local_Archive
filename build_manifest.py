#!/usr/bin/env python3
"""
build_manifest.py

Single source of truth for all build lists shared between build.py and
build_standalone.py. Add new scripts here — both builds pick them up
automatically.

No logic, no imports, no side effects — pure data.
"""

# ── Shared scripts (all modules except entry points) ──────────────────────────
# Add new modules here. Both Target 2 and Target 3 include these.

SHARED_SCRIPTS = [
    "garmin_utils.py",
    "garmin_config.py",
    "garmin_api.py",
    "garmin_security.py",
    "garmin_validator.py",
    "garmin_normalizer.py",
    "garmin_quality.py",
    "garmin_sync.py",
    "garmin_import.py",
    "garmin_writer.py",
    "garmin_collector.py",
    "garmin_to_excel.py",
    "garmin_timeseries_excel.py",
    "garmin_timeseries_html.py",
    "garmin_analysis_html.py",
    "regenerate_summaries.py",
]

# Target 2 (build.py): entry point + shared scripts
SCRIPTS = ["garmin_app.py"] + SHARED_SCRIPTS

# Target 3 (build_standalone.py): shared scripts embedded as data
EMBEDDED_SCRIPTS = SHARED_SCRIPTS

# Target 3: all scripts for layout migration check
ALL_SCRIPTS = ["garmin_app.py", "garmin_app_standalone.py"] + SHARED_SCRIPTS

# ── Signature checks ──────────────────────────────────────────────────────────
# Shared signatures — applied to both builds.
# Entry-point signatures are added per-build in each build script.

SCRIPT_SIGNATURES_BASE = {
    "garmin_api.py":        ["def login", "def fetch_raw"],
    "garmin_collector.py":  ["def main", "def _process_day", "def run_import"],
    "garmin_import.py":     ["def load_bulk", "def parse_day"],
    "garmin_quality.py":    ["def _upsert_quality"],
    "garmin_config.py":     ["GARMIN_EMAIL"],
    "garmin_security.py":   ["def load_token", "def save_token"],
    "garmin_normalizer.py": ["def normalize", "def summarize"],
    "garmin_validator.py":  ["def validate", "def reload_schema", "def current_version"],
    "garmin_writer.py":     ["def write_day", "def read_raw"],
    "garmin_sync.py":       ["def get_local_dates", "def resolve_date_range"],
}

# ── Docs ──────────────────────────────────────────────────────────────────────

DOCS = ["README.md", "README_APP.md", "README_APP_Standalone.md", "MAINTENANCE.md", "SETUP.md"]

INFO_INCLUDE_T2 = {"README.md", "README_APP.md"}
INFO_INCLUDE_T3 = {"README.md", "README_APP_Standalone.md"}

# ── Required non-Python files (must be present alongside scripts) ─────────────

REQUIRED_DATA_FILES = [
    "garmin_dataformat.json",
]

# ── Required non-Python files (must be present alongside scripts) ─────────────

REQUIRED_DATA_FILES = [
    "garmin_dataformat.json",
]

# ── Runtime dependencies (Target 3 only — must be installed for bundling) ─────

RUNTIME_DEPS = [
    "garminconnect",
    "openpyxl",
    "keyring",
    "cryptography",
    "requests",
]
