#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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
    "app/dialog_force_refetch.py",
    "app/dialog_chat_history.py",
    "app/dialog_context_check.py",
    # app/popups/ — extracted panel_outputs.py popups (Codereview v1.7.0.1).
    # Listed after app/__init__.py above, so prepare_scripts_dir()'s
    # per-entry dst.parent.mkdir(exist_ok=True) (no parents=True) always
    # finds scripts/app/ already created by the time it reaches these.
    "app/popups/__init__.py",
    "app/popups/_dashboard_build.py",
    "app/popups/capability_scan.py",
    "app/popups/dashboard_create.py",
    "app/popups/custom_dashboard.py",
    "app/popups/encrypted_dashboards.py",
    "app/garmin_app_settings.py",
    "app/garmin_dashboard_presets.py",
    "app/garmin_app_controller.py",
    "app/panel_settings.py",
    "app/panel_connection.py",
    "app/panel_archive.py",
    "app/panel_timer.py",
    "app/panel_outputs.py",
    "app/panel_home.py",
    "app/panel_chat.py",
    "app/panel_mcp.py",
    # app base
    "version.py",
    "garmin_app_base.py",
    "theme.py",
    "crash_handler.py",
    "qwebengine_hardening.py",
    "frozen_paths.py",
    "log_utils.py",
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
    "garmin/quality/_fieldhash.py",
    "garmin/quality/_scan.py",
    "garmin/quality/_maint.py",
    "garmin/quality/_stats.py",
    "garmin/garmin_redact.py",
    "garmin/garmin_sync.py",
    "garmin/garmin_import.py",
    "garmin/garmin_writer.py",
    "garmin/garmin_collector.py",
    "garmin/garmin_api_capability.py",
    "garmin/garmin_backup.py",
    "garmin/garmin_mirror.py",
    "garmin/garmin_container.py",
    "garmin/garmin_import_mirror.py",
    "garmin/garmin_source_quality.py",
    "garmin/garmin_source_writer.py",
    "garmin/garmin_merge.py",
    "garmin/garmin_backup_source.py",
    "garmin/garmin_force_refetch.py",
    "garmin/garmin_silo_check.py",
    "garmin/garmin_silo_repair.py",
    "garmin/garmin_live_fetch.py",
    "garmin/garmin_extended_anaysis.py",
    # clients (external tool/service integrations — e.g. Ollama, the MCP
    # server; flat imports like garmin/ and app/, no relative imports
    # inside the package, no sys.modules registration needed)
    "clients/__init__.py",
    "clients/ollama_client.py",
    "clients/mcp_server.py",
    "clients/mcp_field_registry.py",
    "clients/mcp_query_common.py",
    "clients/mcp_health.py",
    "clients/mcp_context.py",
    "clients/mcp_server_gui.py",
    "clients/mcp_sql.py",
    "clients/mcp_update.py",
    "clients/chat_session_store.py",
    "clients/cloud_credential_store.py",
    # v1.7.2 — In-App Chat: MCP tool-calling, Cloud LLM connector
    "clients/mcp_client.py",
    "clients/mcp_process.py",
    "clients/mcp_tool_chat.py",
    "clients/openai_tool_schema.py",
    "clients/cloud_llm_client.py",
    "clients/cloud_llm_anthropic.py",
    "clients/cloud_llm_openai.py",
    "clients/cloud_tool_chat.py",
    # maps (routing only)
    "maps/__init__.py",
    "maps/health_map.py",
    "maps/garmin_health_map.py",
    "maps/gateway_map.py",
    "maps/context_map.py",
    "maps/weather_map.py",
    "maps/pollen_map.py",
    "maps/brightsky_map.py",
    "maps/airquality_map.py",
    "maps/metadata_map.py",
    "maps/mcp_map.py",
    "maps/_context_io.py",   # v1.7.1.11 — shared summary/raw read helpers
                              # for the four *_map.py resolvers above
    # context pipeline
    "context/__init__.py",
    "context/context_collector.py",
    "context/context_api.py",
    "context/context_writer.py",
    "context/weather_plugin.py",
    "context/pollen_plugin.py",
    "context/brightsky_plugin.py",
    "context/airquality_plugin.py",
    "context/context_silo_check.py",   # v1.7.2.3 — Context Archive Integrity Check
    "context/context_silo_repair.py",  # v1.7.2.3 — Context Archive Integrity Check
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
    "layouts/dash_autosize.py",
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
    "app/garmin_app_controller.py": ["def build_env_dict", "def check_connection", "def timer_run_repair", "def check_integrity", "def timer_run_source_backfill", "def timer_run_steps_backfill"],
    "app/panel_settings.py":    ["class PanelSettings"],
    "app/panel_connection.py":  ["class PanelConnection"],
    "app/panel_archive.py":     ["class PanelArchive"],
    "app/panel_timer.py":       ["class PanelTimer"],
    "app/dialogs.py":           ["class PasswordConfirmDialog"],
    "app/dialog_chat_history.py": ["class ChatHistoryDialog"],
    "app/dialog_context_check.py": ["class ContextCheckResultDialog", "class ContextCoordinateFixDialog"],
    "app/panel_outputs.py":     ["class PanelOutputs"],
    "app/popups/capability_scan.py": ["def open_popup"],
    "app/popups/dashboard_create.py": ["def open_popup"],
    "app/popups/custom_dashboard.py": ["def open_popup"],
    "app/popups/encrypted_dashboards.py": ["def open_popup"],
    "app/popups/_dashboard_build.py": ["def run_dashboards", "def run_encrypted"],
    "layouts/dash_encryptor.py": ["def encrypt_html"],
    "layouts/dash_autosize.py": ["def compute_autosize_bounds", "def autosize_note"],
    "app/panel_home.py":        ["class PanelHome"],
    "context/brightsky_plugin.py": ["FETCH_ADAPTER", "AGGREGATION_MAP"],
    "maps/brightsky_map.py":       ["def get", "def list_fields"],
    "garmin/garmin_api.py":        ["def login", "def fetch_raw"],
    "garmin/garmin_merge.py":      ["def merge_field"],
    "garmin/quality/_fieldhash.py": ["def compare_source_fields"],
    "garmin/garmin_collector.py":  ["def main", "def _fetch_and_assess", "def run_import", "def _run_schema_migration", "def _run_source_backfill", "def _run_steps_backfill", "def run_capability_scan"],
    "garmin/garmin_api_capability.py": ["def load_config", "def save_config", "def build_args"],
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
    "garmin/garmin_force_refetch.py": ["def snapshot_source", "def restore_snapshot"],
    "garmin/garmin_silo_check.py":    ["def check_silos"],
    "garmin/garmin_silo_repair.py":   ["def repair_silos"],
    "context/context_silo_check.py":  ["def check_context_archive"],
    "context/context_silo_repair.py": ["def fix_coordinates"],
    "garmin/garmin_live_fetch.py":    ["def fetch_live"],
    "layouts/garmin_mobile_landing.py": ["def write_index_html", "def ensure_index_html"],
    "layouts/render/recovery_context.py": ["def render", "def _render_recovery_context"],
    "layouts/render/sleep.py":            ["def render", "def _render_sleep"],
    "layouts/render/explorer.py":         ["def render", "def _render_explorer"],
    "layouts/render/live.py":             ["def render"],
    "crash_handler.py": ["def install"],
    "qwebengine_hardening.py": ["def harden"],
    "frozen_paths.py": ["def scripts_root", "def add_to_path", "def doc_path"],
    "log_utils.py": ["def with_timestamp"],
    "garmin/garmin_redact.py": ["def redact"],
    "app/panel_chat.py": ["class PanelChat"],
    "app/panel_mcp.py": ["class PanelMcp"],
    "clients/ollama_client.py": ["def chat", "def list_models", "def is_reachable"],
    "clients/mcp_server.py": ["def main"],
    "clients/mcp_field_registry.py": ["FIELD_UNITS", "HEALTH_FIELD_ALIASES"],
    "clients/mcp_query_common.py": ["def _route_query", "def _enrich_with_units"],
    "clients/mcp_health.py": ["def query_health"],
    "clients/mcp_context.py": ["def query_context"],
    "clients/mcp_server_gui.py": ["def run_gui"],
    "clients/mcp_sql.py": ["def init_db", "def get_connection"],
    "clients/mcp_update.py": ["def sync_all"],
    "clients/chat_session_store.py": ["def list_sessions", "def save_session", "def load_session"],
    "clients/cloud_credential_store.py": ["def get_api_key", "def store_api_key", "def clear_api_key"],
    "clients/mcp_client.py": ["def is_reachable", "def list_tools", "def call_tool"],
    "clients/mcp_process.py": ["def start", "def stop", "def is_running"],
    "clients/mcp_tool_chat.py": ["def converse"],
    "clients/openai_tool_schema.py": ["def to_openai_style_tools"],
    "clients/cloud_llm_client.py": ["def chat", "def chat_with_tools", "def chat_stream", "def chat_stream_with_tools"],
    "clients/cloud_llm_anthropic.py": ["def chat", "def chat_with_tools", "def chat_stream", "def chat_stream_with_tools"],
    "clients/cloud_llm_openai.py": ["def chat", "def chat_with_tools", "def chat_stream", "def chat_stream_with_tools"],
    "clients/cloud_tool_chat.py": ["def converse", "def converse_stream"],
    "theme.py": ["ACTIVE_THEME", "_THEMES"],
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


# ── Build venv (PyInstaller build isolation, garmin_collector-3_experiment,
# Baustein 27) ──────────────────────────────────────────────────────────────
# Fixed, shared location — deliberately OUTSIDE any project copy (this repo,
# test2/, test3/, test4/, garmin_collector-*_work/, ...) so every copy on
# this machine builds against the exact same isolated Python environment
# instead of each needing its own multi-hundred-MB copy of PyQt6 etc., and
# so that packages installed globally for a DIFFERENT, unrelated project on
# this machine (e.g. torch/pandas/scipy, installed for a document/OCR tool)
# can never again be swept into a GLA PyInstaller build the way they were
# here — see PROTOKOLL_experiment.md, Baustein 26, for the >8 GB T3 ZIP and
# the ~3 GB T2 EXE this caused. Plain string, not a Path object — this
# module stays import-free by design (see module docstring above); build.py
# and build_standalone.py wrap it in Path() themselves. Replaces the old
# RUNTIME_DEPS list (removed here) — build.py/build_standalone.py now
# install the venv straight from requirements.txt (the actually-maintained,
# complete dependency list) instead of a second, narrower, drift-prone copy.
BUILD_VENV_DIR = r"D:\Garmin\.venv_gla"


# ── Hidden imports (PyInstaller --hidden-import, both targets) ────────────────
# COMMON: needed by the GUI build (T2, Python required on target). T2 = COMMON
# only.
# T3_EXTRA: additional modules only T3 (fully embedded, no Python on target)
# needs PyInstaller to detect. T3 = COMMON + T3_EXTRA.

HIDDEN_IMPORTS_COMMON = [
    "openpyxl",
    "openpyxl.cell._writer",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.ttk",
    "tkinter.scrolledtext",
    "garminconnect",
    "curl_cffi",
    "curl_cffi.requests",
    "ua_generator",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "cryptography.hazmat.primitives.kdf.pbkdf2",
    "cryptography.hazmat.primitives.kdf.hkdf",
    "cryptography.hazmat.primitives.ciphers.aead",
    "cryptography.hazmat.primitives.hmac",
    "cryptography.hazmat.primitives.hashes",
    "PyQt6.QtNetwork",
    # MCP client + Cloud LLM SDKs (v1.7.2, moved here post-v1.7.2 review,
    # garmin_collector-3_experiment) — clients/mcp_client.py,
    # clients/cloud_llm_anthropic.py and clients/cloud_llm_openai.py are
    # loose scripts run inside garmin_app.exe (T2) itself, same as every
    # other clients/ module. T2 is a PyInstaller --onefile build: its
    # embedded interpreter has NO "normal site-packages" a loose script
    # could fall back on at runtime — only what PyInstaller's own Analysis
    # phase (or this list) actually bundles is present. Confirmed missing
    # via a real T2 run (garmin_collector-3_experiment): mcp_client.py's
    # own `import httpx` raised ModuleNotFoundError inside the chat panel.
    # Only the MCP *client*-side chain is listed here (verified against
    # mcp/client/streamable_http.py and mcp/client/session.py — the latter
    # lazy-imports jsonschema at line ~430) — the server-side ASGI chain
    # (uvicorn/starlette/sse_starlette/pydantic_settings/jwt/multipart/
    # win32api/win32con, plus mcp.server.fastmcp itself) stays in
    # HIDDEN_IMPORTS_T3_EXTRA below: only T3.3 (mcp_server.exe) runs an
    # actual MCP server, T2's chat panel only ever connects as a client.
    "mcp",
    "anyio",
    "httpx",
    "httpx_sse",
    "jsonschema",
    "pydantic",
    "typing_extensions",
    "typing_inspection",
    "anthropic",
    "openai",
]

HIDDEN_IMPORTS_T3_EXTRA = [
    "openpyxl.styles",
    "openpyxl.chart",
    "openpyxl.utils",
    "cryptography",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.backends",
    "cryptography.exceptions",
    "requests",
    "lxml",
    "lxml.etree",
    "sqlite3",
    "_sqlite3",
    # MCP server-only SDK chain (v1.7 Teil e) — T3.3 (mcp_server.exe) only.
    # The client-side chain (mcp, anyio, httpx, httpx_sse, jsonschema,
    # pydantic, typing_extensions, typing_inspection, anthropic, openai)
    # moved to HIDDEN_IMPORTS_COMMON above (post-v1.7.2 review,
    # garmin_collector-3_experiment) once it turned out T2 needs it too —
    # see the comment there for the client/server split rationale.
    "mcp.server.fastmcp",
    "pydantic_settings",
    "jwt",
    "multipart",
    "win32api",
    "win32con",
    "sse_starlette",
    "starlette",
    "uvicorn",
]
