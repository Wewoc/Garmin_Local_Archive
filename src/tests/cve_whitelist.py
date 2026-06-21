"""
cve_whitelist.py — Garmin Local Archive
Known-used functions per package, for A1 CVE relevance filtering.

Purpose: pip-audit reports vulnerabilities at the package level, not the
function level. A CVSS "high" finding may describe a code path GLA never
calls. This whitelist lets check_cve_whitelist.py distinguish "this package
has a known vulnerability" from "the vulnerable function is actually part
of our call graph" — without claiming certainty either way (see verdict
rules in check_cve_whitelist.py).

Edit this file whenever GLA starts or stops using a specific package
function. Keep entries narrow — list the actual functions/classes called,
not the whole package surface.

Plotly is deliberately excluded — covered by its own hash-pinning +
check_deps.py monitoring mechanism (A2, v1.6.0.4.4), not by this list.
"""

CVE_WHITELIST = {
    "cryptography": {
        "used_functions": [
            "AESGCM",
            "AESGCM.encrypt",
            "AESGCM.decrypt",
        ],
        "note": "AES-256-GCM token encryption — garmin_security.py",
    },
    "garminconnect": {
        "used_functions": [
            "Garmin.login",
            "Garmin.get_stats",
            "Garmin.get_sleep_data",
        ],
        "note": "Login + data retrieval — garmin_api.py. PLACEHOLDER: full "
                "method surface used by garmin_api.py not yet enumerated — "
                "verify against actual call sites before relying on this "
                "entry.",
    },
    "curl_cffi": {
        "used_functions": [
            "requests.Session",
            "requests.get",
            "requests.post",
        ],
        "note": "TLS impersonation for Garmin API calls — transitive via "
                "garminconnect, not a direct requirements.txt entry "
                "(confirmed — see MAINTENANCE_GLOBAL.md hidden-import list).",
    },
    "keyring": {
        "used_functions": [
            "set_password",
            "get_password",
            "delete_password",
        ],
        "note": "Windows Credential Manager — garmin_security.py, "
                "app/garmin_app_settings.py",
    },
    "PyQt6": {
        "used_functions": [
            "QWebEngineView",
            "QWebEngineSettings",
        ],
        "note": "Dashboard/XLSX viewer — garmin_app_base.py, panel_home.py. "
                "PLACEHOLDER: PyQt6 surface used across app/ is broad — this "
                "entry only covers the WebEngine-related classes relevant "
                "to A5 (QWebEngineSettings hardening). Widen if needed.",
    },
    "openpyxl": {
        "used_functions": [
            "Workbook",
            "load_workbook",
            "PatternFill",
        ],
        "note": "Excel dashboard export — dash_plotter_excel.py",
    },
}