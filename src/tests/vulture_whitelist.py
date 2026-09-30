# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
vulture_whitelist.py — Garmin Local Archive
Known false positives for check_vulture.py, filtered AFTER the Vulture run —
NOT fed to Vulture as a scan path. Vulture's own whitelist mechanism
matches by name only, with no way to scope an entry to one file. Scoping
by (file, name) here means a generic attribute name (e.g. "alignment")
only gets suppressed where it's a confirmed false positive, not wherever
else that name shows up in the repo.

Vulture cannot see PyQt6 slot/signal wiring, MCP tool-handler registration,
openpyxl style-attribute writes, or anything else reached only by name or
decorator rather than a direct call — those show up as "unused" even
though they are load-bearing.

Empty until the first real check_vulture.py run — build this from actual
findings, not preemptively.

Format: {(file, name): "reason"} — file exactly as Vulture reports it
(relative to src/, same path separator it printed — Windows backslashes).
Keep entries narrow: one (file, name) pair per confirmed false positive,
with a reason a future reader can verify without re-deriving it.
"""

VULTURE_WHITELIST: dict[tuple[str, str], str] = {
    # ── Fake-module registration for embedded standalone packages ──────────
    # types.ModuleType(...) with __path__/__package__ set manually so
    # `import <pkg>` resolves inside the frozen/standalone build. Read by
    # Python's import machinery, not by visible attribute access.
    ("clients\\mcp_server.py", "__path__"): "fake-module registration (embedded package import)",
    ("clients\\mcp_server.py", "__package__"): "fake-module registration (embedded package import)",
    ("garmin_app_standalone.py", "__path__"): "fake-module registration (embedded package import)",
    ("garmin_app_standalone.py", "__package__"): "fake-module registration (embedded package import)",
    ("layouts\\dash_plotter_html_complex.py", "__path__"): "fake-module registration (embedded package import)",
    ("layouts\\dash_plotter_html_complex.py", "__package__"): "fake-module registration (embedded package import)",
    ("scheduler\\daily_update.py", "__path__"): "fake-module registration (embedded package import)",
    ("scheduler\\daily_update.py", "__package__"): "fake-module registration (embedded package import)",

    # ── Qt event handlers ────────────────────────────────────────────────
    # Called by Qt's own event dispatch, never directly from our code —
    # either a def override or an instance attribute assignment
    # (label.mousePressEvent = lambda e: ...).
    ("app\\dialog_force_refetch.py", "mousePressEvent"): "Qt event handler, called by Qt dispatch",
    ("app\\panel_outputs.py", "mousePressEvent"): "Qt event handler, called by Qt dispatch",
    ("app\\panel_settings.py", "mousePressEvent"): "Qt event handler, called by Qt dispatch",
    ("garmin_app_base.py", "mousePressEvent"): "Qt event handler, called by Qt dispatch",

    # ── openpyxl write-only style attributes ────────────────────────────
    # openpyxl reads these internally when saving the workbook; no
    # visible read access in our own code.
    ("layouts\\dash_plotter_excel.py", "alignment"): "openpyxl Cell style, write-only attribute",
    ("layouts\\dash_plotter_excel.py", "border"): "openpyxl Cell style, write-only attribute",
    ("layouts\\dash_plotter_excel.py", "number_format"): "openpyxl Cell style, write-only attribute",
    ("layouts\\dash_plotter_excel.py", "freeze_panes"): "openpyxl Worksheet style, write-only attribute",
    ("layouts\\dash_plotter_excel.py", "solidFill"): "openpyxl Chart style, write-only attribute",

    # ── Third-party object attributes, write-only from our side ─────────
    ("clients\\mcp_sql.py", "row_factory"): "sqlite3.Connection API, read internally by the C module",
    ("garmin\\garmin_api.py", "_tokenstore_path"): "attribute on garminconnect.Garmin instance, not our object",

    # ── Called only from compiler/, which is excluded from this scan ────
    ("layouts\\dash_layout_html.py", "get_plotly_sha256"): "called only from compiler/build_all.py (excluded, build-only)",
    ("layouts\\dash_layout_html.py", "get_plotly_cdn"): "called only from compiler/build_all.py (excluded, build-only)",
    ("layouts\\dash_layout_html.py", "get_plotly_version"): "called only from compiler/build_all.py (excluded, build-only)",

    # ── Confirmed test-only by design (documented in the code itself) ───
    # See app/panel_outputs.py comment above _on_context_sync_done(): kept
    # as a delegate for signature reasons, only ever called directly from
    # tests/test_qt_app.py::TestPanelOutputs.
    ("app\\panel_outputs.py", "_on_context_sync_done"): "documented test-only delegate (see comment at definition)",

    # ── MCP tools: invoked externally via the MCP protocol by name, never
    # directly from our own Python code ──────────────────────────────────
    ("clients\\mcp_server.py", "refresh_cache"): "@mcp.tool(), invoked externally via MCP protocol",

    # ── Test-only by design, no runtime call path exists ────────────────
    # Schema is already reloaded fresh at every app start (module import);
    # self-healing (garmin_collector.py::_run_self_healing) runs once right
    # after that, so it never needs to force a second reload. The app is
    # started/closed once per day, not kept open across a schema edit, so
    # there is no runtime scenario that needs this. Only exercised by
    # tests/test_local.py (F6 fail-closed test).
    ("garmin\\garmin_validator.py", "reload_schema"): "test-only by design, no runtime reload path (see docstring)",
}
