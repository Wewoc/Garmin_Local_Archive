#!/usr/bin/env python3
"""
build_manifest.py

Single source of truth for all build lists shared between build.py and
build_standalone.py. Add new modules here — both builds pick them up
automatically.

No logic, no imports, no side effects — pure data.
"""

# ── Shared scripts (all modules except entry points) ──────────────────────────
# Add new modules here. Both Target 2 and Target 3 include these.

SHARED_SCRIPTS = [
    # garmin pipeline
    "garmin/garmin_config.py",
    "garmin/garmin_utils.py",
    "garmin/garmin_api.py",
    "garmin/garmin_security.py",
    "garmin/garmin_validator.py",
    "garmin/garmin_normalizer.py",
    "garmin/garmin_quality.py",
    "garmin/garmin_sync.py",
    "garmin/garmin_import.py",
    "garmin/garmin_writer.py",
    "garmin/garmin_collector.py",
    # maps (routing only)
    "maps/field_map.py",
    "maps/garmin_map.py",
    "maps/context_map.py",
    "maps/weather_map.py",
    "maps/pollen_map.py",
    "maps/brightsky_map.py",
    "maps/airquality_map.py",
    # context pipeline
    "context/context_collector.py",
    "context/context_api.py",
    "context/context_writer.py",
    "context/weather_plugin.py",
    "context/pollen_plugin.py",
    "context/brightsky_plugin.py",
    "context/airquality_plugin.py",
    # dashboards (specialists + runner)
    "dashboards/dash_runner.py",
    "dashboards/timeseries_garmin_html-xls_dash.py",
    "dashboards/health_garmin_html-json_dash.py",
    "dashboards/overview_garmin_xls_dash.py",
    "dashboards/health_garmin-weather-pollen_html-xls_dash.py",
    "dashboards/sleep_recovery_context_dash.py",
    "dashboards/sleep_garmin_html-xls_dash.py",
    "dashboards/explorer_garmin-context_html_dash.py",
    # layouts (plotters + passive resources)
    "layouts/dash_layout.py",
    "layouts/dash_layout_html.py",
    "layouts/dash_plotter_html.py",
    "layouts/dash_plotter_html_complex.py",
    "layouts/dash_plotter_html_mobile.py",
    "layouts/dash_plotter_excel.py",
    "layouts/dash_plotter_json.py",
    "layouts/dash_prompt_templates.py",
    "layouts/reference_ranges.py",
]
# Target 2 (build.py): entry point + shared scripts
SCRIPTS = ["garmin_app.py"] + SHARED_SCRIPTS

# Target 3 (build_standalone.py): shared scripts embedded as data
EMBEDDED_SCRIPTS = SHARED_SCRIPTS

# Target 3: all scripts (entry points + shared)
ALL_SCRIPTS = ["garmin_app.py", "garmin_app_standalone.py"] + SHARED_SCRIPTS

# ── Signature checks ──────────────────────────────────────────────────────────
# Shared signatures — applied to both builds.
# Entry-point signatures are added per-build in each build script.

SCRIPT_SIGNATURES_BASE = {
    "context/brightsky_plugin.py": ["FETCH_ADAPTER", "AGGREGATION_MAP"],
    "maps/brightsky_map.py":       ["def get", "def list_fields"],
    "garmin/garmin_api.py":        ["def login", "def fetch_raw"],
    "garmin/garmin_collector.py":  ["def main", "def _fetch_and_assess", "def run_import", "def _run_schema_migration"],
    "garmin/garmin_import.py":     ["def load_bulk", "def parse_day"],
    "garmin/garmin_quality.py":    ["def _upsert_quality"],
    "garmin/garmin_config.py":     ["GARMIN_EMAIL"],
    "garmin/garmin_security.py":   ["def load_token", "def save_token"],
    "garmin/garmin_normalizer.py": ["def normalize", "def summarize"],
    "garmin/garmin_validator.py":  ["def validate", "def reload_schema", "def current_version"],
    "garmin/garmin_writer.py":     ["def write_day", "def read_raw", "def read_summary"],
    "context/airquality_plugin.py": ["AGGREGATION_MAP", "CHUNK_DAYS"],
    "maps/airquality_map.py":       ["def get", "def list_fields"],
    "garmin/garmin_sync.py":       ["def get_local_dates", "def resolve_date_range"],
}

# ── Docs ──────────────────────────────────────────────────────────────────────

DOCS = ["README.md", "README_APP.md", "MAINTENANCE.md", "SETUP.md"]

INFO_INCLUDE_T2 = {"README.md", "README_APP.md"}
INFO_INCLUDE_T3 = {"README.md", "README_APP.md"}

# ── Required non-Python files (must be present alongside scripts) ─────────────
# Paths relative to garmin/ — build scripts prepend the folder.

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
