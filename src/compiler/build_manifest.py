#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    # app layer
    "app/__init__.py",
    "app/dialogs.py",
    "app/garmin_app_settings.py",
    "app/garmin_dashboard_presets.py",
    "app/garmin_app_controller.py",
    "app/panel_settings.py",
    "app/panel_connection.py",
    "app/panel_archive.py",
    "app/panel_timer.py",
    "app/panel_outputs.py",
    "app/panel_home.py",
    # app base
    "version.py",
    "garmin_app_base.py",
    "crash_handler.py",
    "qwebengine_hardening.py",
    # garmin pipeline
    "garmin/__init__.py",
    "garmin/garmin_config.py",
    "garmin/garmin_utils.py",
    "garmin/garmin_api.py",
    "garmin/garmin_security.py",
    "garmin/garmin_validator.py",
    "garmin/garmin_normalizer.py",
    "garmin/garmin_quality.py",
    "garmin/quality/__init__.py",
    "garmin/quality/_io.py",
    "garmin/quality/_assess.py",
    "garmin/quality/_scan.py",
    "garmin/quality/_maint.py",
    "garmin/quality/_stats.py",
    "garmin/garmin_redact.py",
    "garmin/garmin_sync.py",
    "garmin/garmin_import.py",
    "garmin/garmin_writer.py",
    "garmin/garmin_collector.py",
    "garmin/garmin_backup.py",
    "garmin/garmin_mirror.py",
    "garmin/garmin_container.py",
    "garmin/garmin_import_mirror.py",
    "garmin/garmin_source_quality.py",
    "garmin/garmin_source_writer.py",
    "garmin/garmin_merge.py",
    "garmin/garmin_backup_source.py",
    "garmin/garmin_silo_check.py",
    "garmin/garmin_live_fetch.py",
    "garmin/garmin_extended_anaysis.py",
    # maps (routing only)
    "maps/__init__.py",
    "maps/field_map.py",
    "maps/garmin_map.py",
    "maps/context_map.py",
    "maps/weather_map.py",
    "maps/pollen_map.py",
    "maps/brightsky_map.py",
    "maps/airquality_map.py",
    # context pipeline
    "context/__init__.py",
    "context/context_collector.py",
    "context/context_api.py",
    "context/context_writer.py",
    "context/weather_plugin.py",
    "context/pollen_plugin.py",
    "context/brightsky_plugin.py",
    "context/airquality_plugin.py",
    # dashboards (specialists + runner)
    "dashboards/__init__.py",
    "dashboards/dash_runner.py",
    "dashboards/timeseries_garmin_html-xls_dash.py",
    "dashboards/health_garmin_html-json_dash.py",
    "dashboards/overview_garmin_xls_dash.py",
    "dashboards/health_garmin-weather-pollen_html-xls_dash.py",
    "dashboards/sleep_recovery_context_dash.py",
    "dashboards/sleep_garmin_html-xls_dash.py",
    "dashboards/explorer_garmin-context_html_dash.py",
    "dashboards/heatmap_garmin_html_dash.py",
    "dashboards/live_tracking_html_dash.py",
    "dashboards/custom_dash_builder.py",
    # layouts (plotters + passive resources)
    "layouts/__init__.py",
    "layouts/dash_layout.py",
    "layouts/dash_layout_html.py",
    "layouts/dash_plotter_html.py",
    "layouts/dash_plotter_html_complex.py",
    "layouts/dash_plotter_html_mobile.py",
    "layouts/dash_plotter_excel.py",
    "layouts/dash_plotter_json.py",
    "layouts/dash_prompt_templates.py",
    "layouts/reference_ranges.py",
    "layouts/garmin_mobile_landing.py",
    "layouts/dash_encryptor.py",
    # render sub-package (one module per layout type)
    "layouts/render/__init__.py",
    "layouts/render/recovery_context.py",
    "layouts/render/sleep.py",
    "layouts/render/explorer.py",
    "layouts/render/heatmap.py",
    "layouts/render/live.py",
]
# Target 2 (build.py): entry point + shared scripts
SCRIPTS = ["garmin_app.py"] + SHARED_SCRIPTS

# Target 3 (build_standalone.py): shared scripts embedded as data
EMBEDDED_SCRIPTS = SHARED_SCRIPTS

# Target 3: all scripts (entry points + shared)
ALL_SCRIPTS = ["garmin_app.py", "garmin_app_standalone.py", "daily_update.py"] + SHARED_SCRIPTS

# ── Signature checks ──────────────────────────────────────────────────────────
# Shared signatures — applied to both builds.
# Entry-point signatures are added per-build in each build script.

SCRIPT_SIGNATURES_BASE = {
    "app/garmin_app_settings.py": ["def load_settings", "def save_settings", "def load_password", "def save_password"],
    "app/garmin_dashboard_presets.py": ["def load_presets", "def save_preset", "def delete_preset"],
    "dashboards/custom_dash_builder.py": ["def build_ad_hoc_specialist", "def list_available_fields"],
    "app/garmin_app_controller.py": ["def build_env_dict", "def check_connection", "def timer_run_repair", "def check_integrity", "def check_mirror", "def timer_run_source_backfill", "def timer_run_steps_backfill"],
    "app/panel_settings.py":    ["class PanelSettings"],
    "app/panel_connection.py":  ["class PanelConnection"],
    "app/panel_archive.py":     ["class PanelArchive"],
    "app/panel_timer.py":       ["class PanelTimer"],
    "app/dialogs.py":           ["class PasswordConfirmDialog"],
    "app/panel_outputs.py":     ["class PanelOutputs"],
    "layouts/dash_encryptor.py": ["def encrypt_html"],
    "app/panel_home.py":        ["class PanelHome"],
    "context/brightsky_plugin.py": ["FETCH_ADAPTER", "AGGREGATION_MAP"],
    "maps/brightsky_map.py":       ["def get", "def list_fields"],
    "garmin/garmin_api.py":        ["def login", "def fetch_raw"],
    "garmin/garmin_merge.py":      ["def merge_field"],
    "garmin/garmin_collector.py":  ["def main", "def _fetch_and_assess", "def run_import", "def _run_schema_migration", "def _run_source_backfill", "def _run_steps_backfill"],
    "garmin/garmin_import.py":     ["def load_bulk", "def parse_day"],
    "garmin/garmin_quality.py":    ["from quality._maint import", "QUALITY_LOCK"],
    "garmin/garmin_config.py":     ["GARMIN_EMAIL"],
    "garmin/garmin_security.py":   ["def load_token", "def save_token"],
    "garmin/garmin_normalizer.py": ["def normalize", "def summarize"],
    "garmin/garmin_validator.py":  ["def validate", "def reload_schema", "def current_version"],
    "garmin/garmin_writer.py":     ["def write_day", "def read_raw", "def read_summary"],
    "context/airquality_plugin.py": ["AGGREGATION_MAP", "CHUNK_DAYS"],
    "maps/airquality_map.py":       ["def get", "def list_fields"],
    "garmin/garmin_sync.py":       ["def get_local_dates", "def resolve_date_range"],
    "garmin/garmin_backup.py":     ["def backup_raw", "def backup_quality_log", "def restore_quality_log", "def check_raw_integrity"],
    "garmin/garmin_mirror.py":     ["def run_mirror", "def is_reachable"],
    "garmin/garmin_container.py":  ["def lock", "def unlock_meta", "def fulfill_order", "def is_container", "def list_files"],
    "garmin/garmin_import_mirror.py": ["def run_import_mirror", "def detect_source"],
    "garmin/garmin_source_quality.py": ["def assess_source", "def compare_source"],
    "garmin/garmin_source_writer.py": ["def write_source", "def update_log"],
    "garmin/garmin_backup_source.py": ["def backup_source", "def backfill_source", "def check_source_backfill_needed"],
    "garmin/garmin_silo_check.py":    ["def check_silos"],
    "garmin/garmin_live_fetch.py":    ["def fetch_live"],
    "layouts/garmin_mobile_landing.py": ["def write_index_html", "def ensure_index_html"],
    "layouts/render/recovery_context.py": ["def render", "def _render_recovery_context"],
    "layouts/render/sleep.py":            ["def render", "def _render_sleep"],
    "layouts/render/explorer.py":         ["def render", "def _render_explorer"],
    "layouts/render/live.py":             ["def render"],
    "crash_handler.py": ["def install"],
    "qwebengine_hardening.py": ["def harden"],
    "garmin/garmin_redact.py": ["def redact"],
}
# ── Docs ──────────────────────────────────────────────────────────────────────

DOCS = ["README.md", "README_APP.md", "MAINTENANCE.md", "SETUP.md"]

INFO_INCLUDE_T2 = {"README.md", "README_APP.md", "daily_update_task.xml",
                   "QUICKSTART.txt", "USER_GUIDE.txt"}
INFO_INCLUDE_T3 = {"README.md", "README_APP.md", "daily_update_task.xml",
                   "QUICKSTART.txt", "USER_GUIDE.txt"}

# ── Required non-Python files (must be present alongside scripts) ─────────────
# Paths relative to garmin/ — build scripts prepend the folder.

# Each entry: (subfolder, filename) — subfolder relative to project root.
# Generic structure (v1.6.0.4.4+) — was a flat list assuming garmin/ for all
# entries; plotly.min.js lives under layouts/, not garmin/, so the tuple form
# is required. Both build.py and build_standalone.py iterate this generically.
REQUIRED_DATA_FILES = [
    ("garmin",  "garmin_dataformat.json"),
    ("layouts", "plotly.min.js"),
]


# ── Runtime dependencies (Target 3 only — must be installed for bundling) ─────

RUNTIME_DEPS = [
    "garminconnect",
    "openpyxl",
    "keyring",
    "cryptography",
    "requests",
]
