#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
layouts/garmin_mobile_landing.py
Garmin Local Archive — Mobile Landing Page Generator

Generates index.html in BASE_DIR/dashboards/ with status data embedded
directly as a JavaScript variable — no fetch(), works with file:// protocol.

Called after every sync via panel_archive._refresh_archive_info().
Called at app start via garmin_app_base._ensure_mobile_landing().

Rules:
  - Read-only access to quality_log.json and device_table.json (no QUALITY_LOCK needed)
  - Sole write authority for index.html in BASE_DIR/dashboards/
  - No imports from other project modules except garmin_config
  - No Qt, no GUI dependencies
  - write_index_html() always regenerates index.html with current data
  - ensure_index_html() calls write_index_html() only if file is absent
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import garmin_config as cfg

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  write_index_html — called after every sync + at app start if absent
# ══════════════════════════════════════════════════════════════════════════════

def write_index_html(base_dir: Path | None = None) -> bool:
    """
    Reads quality_log.json and device_table.json, writes index.html with
    status data embedded as a JS variable — no fetch() required.

    base_dir: optional override — uses cfg.BASE_DIR if None.
    Returns True on success, False on any error.
    """
    try:
        bd       = Path(base_dir) if base_dir else cfg.BASE_DIR
        log_path = bd / "garmin_data" / "log" / "quality_log.json"
        dt_path  = bd / "garmin_data" / "log" / "device_table.json"
        out_dir  = bd / "dashboards"

        if not log_path.exists():
            log.debug("write_index_html: quality_log.json not found — skipped")
            return False

        # ── Read quality_log ──────────────────────────────────────────────────
        try:
            import garmin_quality as _quality
            stats = _quality.get_archive_stats(quality_log_path=log_path)
        except Exception as e:
            log.warning(f"write_index_html: get_archive_stats failed: {e}")
            return False

        if not stats.get("total"):
            log.debug("write_index_html: no data in quality_log — skipped")
            return False

        # ── Read device_table ─────────────────────────────────────────────────
        device_table = []
        if dt_path.exists():
            try:
                device_table = json.loads(dt_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"write_index_html: device_table.json read error: {e}")

        # ── Build status dict ─────────────────────────────────────────────────
        rng = (
            f"{stats['date_min']} → {stats['date_max']}"
            if stats.get("date_min") and stats.get("date_max")
            else "—"
        )
        integrity_warnings = stats.get("integrity_warnings", [])

        status = {
            "generated":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "failed":       stats.get("failed",   0),
            "recheck":      stats.get("recheck",  0),
            "missing":      stats.get("missing",  0) or 0,
            "range":        rng,
            "coverage":     f"{stats['coverage_pct']}%" if stats.get("coverage_pct") is not None else "—",
            "last_api":     stats.get("last_api")  or "—",
            "last_bulk":    stats.get("last_bulk") or "—",
            "integrity":    ("⚠  " + ", ".join(integrity_warnings)) if integrity_warnings else "",
            "device_table": [
                row for row in device_table
                if row.get("device_id") != "__total__"
            ],
            "total_high":     next((r["days_high"]     for r in device_table if r.get("device_id") == "__total__"), 0),
            "total_standard": next((r["days_standard"] for r in device_table if r.get("device_id") == "__total__"), 0),
            "total_all":      next((r["days_total"]    for r in device_table if r.get("device_id") == "__total__"), 0),
        }

        # ── Read dashboard files for inline embedding ─────────────────────────
        # Strategy: extract <script> tags from <head> (Plotly etc.) + <body> content.
        # Dropping <html>/<head>/<style> prevents dashboard CSS from overriding
        # index.html styling, while keeping JS dependencies (Plotly) intact.
        import re as _re
        def _read_dash(filename: str) -> str:
            p = out_dir / filename
            if not p.exists():
                return ""
            try:
                raw = p.read_text(encoding="utf-8")

                # Extract <script> tags from <head> (src= and inline)
                head_m = _re.search(r"<head[^>]*>(.*?)</head>", raw, _re.DOTALL | _re.IGNORECASE)
                head_scripts = ""
                if head_m:
                    head_scripts = "".join(
                        _re.findall(r"<script[^>]*>.*?</script>", head_m.group(1),
                                    _re.DOTALL | _re.IGNORECASE)
                    )

                # Extract <body> content
                body_m = _re.search(r"<body[^>]*>(.*?)</body>", raw, _re.DOTALL | _re.IGNORECASE)
                body_content = body_m.group(1) if body_m else raw

                return head_scripts + body_content

            except Exception as e:
                log.warning(f"write_index_html: could not read {filename}: {e}")
            return ""

        dash_mobile = _read_dash("health_garmin_mobile.html")
        dash_sleep  = _read_dash("sleep_garmin_html-xls_dash.html")

        # ── Render and write index.html atomically ────────────────────────────
        out_dir.mkdir(parents=True, exist_ok=True)
        html_content = _render_html(status, dash_mobile, dash_sleep)
        html_path    = out_dir / "index.html"
        tmp_path     = out_dir / "index.html.tmp"
        tmp_path.write_text(html_content, encoding="utf-8")
        tmp_path.replace(html_path)
        log.info("write_index_html: index.html written")
        return True

    except Exception as e:
        log.warning(f"write_index_html: unexpected error: {e}")
        return False


def ensure_index_html(base_dir: Path | None = None) -> bool:
    """
    Writes index.html only if not yet present.
    Safe to call at every app start.

    base_dir: optional override — uses cfg.BASE_DIR if None.
    Returns True if written, False if already present or on error.
    """
    try:
        bd      = Path(base_dir) if base_dir else cfg.BASE_DIR
        html    = bd / "dashboards" / "index.html"
        if html.exists():
            return False
        return write_index_html(base_dir)
    except Exception as e:
        log.warning(f"ensure_index_html: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  HTML renderer — embeds status data as JS variable
# ══════════════════════════════════════════════════════════════════════════════

def _render_html(status: dict, dash_mobile: str = "", dash_sleep: str = "") -> str:
    """Renders index.html with status data and dashboard content embedded inline.

    dash_mobile: full HTML content of health_garmin_mobile.html, or "" if not found.
    dash_sleep:  full HTML content of sleep_garmin_html-xls_dash.html, or "" if not found.
    Both are embedded as hidden <div> blocks — no external file references needed.
    Works with file:// protocol (OneDrive mobile viewer compatible).
    """
    status_json   = json.dumps(status, ensure_ascii=False, indent=2)
    html = _HTML_TEMPLATE.replace("__STATUS_JSON_PLACEHOLDER__", status_json)
    html = html.replace("__DASH_MOBILE_PLACEHOLDER__",  dash_mobile)
    html = html.replace("__DASH_SLEEP_PLACEHOLDER__",   dash_sleep)
    return html


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🦄 GLA — Archive Overview</title>
<style>
  :root {
    --bg:      #12101f;
    --bg2:     #1a1729;
    --bg3:     #231f38;
    --accent:  #a259f7;
    --accent2: #6e3fcf;
    --text:    #eaeaea;
    --text2:   #a0a0b0;
    --green:   #4ecca3;
    --yellow:  #f5a623;
    --red:     #e94560;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { background: var(--bg); }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', sans-serif;
    min-height: 100vh;
  }
  .page { max-width: 480px; margin: 0 auto; padding-bottom: 40px; }

  .header {
    background: var(--bg2);
    border-bottom: 2px solid var(--accent);
    padding: 14px 18px 10px;
  }
  .header-label {
    font-size: 9px; font-weight: 700;
    letter-spacing: 0.18em; color: var(--accent);
    text-transform: uppercase; margin-bottom: 2px;
  }
  .header-title { font-size: 17px; font-weight: 700; color: var(--text); }
  .header-sub   { font-size: 10px; color: var(--text2); margin-top: 3px; }

  .content { padding: 16px 18px 0; }
  .section-label {
    font-size: 8px; font-weight: 700;
    letter-spacing: 0.14em; color: var(--accent);
    text-transform: uppercase; margin-bottom: 8px;
  }
  .divider { height: 1px; background: var(--bg3); margin: 16px 0; }

  .pills { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
  .pill {
    display: flex; align-items: center; gap: 5px;
    background: var(--bg3); border-radius: 3px; padding: 3px 8px;
  }
  .pill-label { font-size: 10px; color: var(--text2); }
  .pill-value { font-size: 11px; font-weight: 700; }

  .status-row {
    display: flex; justify-content: space-between;
    margin-bottom: 5px; font-size: 11px;
  }
  .status-row .lbl { color: var(--text2); }
  .status-row .val { font-weight: 600; color: var(--text); }

  .integrity {
    margin-top: 10px; padding: 6px 10px;
    background: rgba(245,166,35,0.1);
    border: 1px solid rgba(245,166,35,0.35);
    border-radius: 3px; font-size: 10px; color: var(--yellow);
    display: none;
  }

  table { width: 100%; border-collapse: collapse; font-size: 10px; }
  thead th {
    text-align: left; color: var(--text); font-weight: 700;
    padding-bottom: 5px; font-size: 9px;
    border-bottom: 1px solid var(--bg3);
  }
  thead th.r { text-align: right; padding-right: 4px; }
  tbody tr:nth-child(even) { background: var(--bg3); }
  tbody td { padding: 4px 0; color: var(--text2); }
  tbody td.name { color: var(--text); }
  tbody td.r  { text-align: right; padding-right: 4px; color: var(--text); }
  tbody td.hi { text-align: right; padding-right: 4px; color: var(--green); }
  tfoot td {
    border-top: 1px solid var(--bg3);
    padding: 5px 0; font-weight: 700; font-size: 11px; color: var(--text);
  }
  tfoot td.hi { color: var(--green); text-align: right; padding-right: 4px; }
  tfoot td.r  { text-align: right; padding-right: 4px; }

  .dash-card {
    background: var(--bg2); border: 1px solid var(--bg3);
    border-radius: 4px; margin-bottom: 8px;
  }
  .dash-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 9px 14px; background: var(--bg3);
  }
  .dash-meta { display: flex; align-items: center; gap: 8px; }
  .dash-icon { font-size: 14px; }
  .dash-name { font-size: 11px; font-weight: 700; color: var(--text); }
  .dash-file { font-size: 9px; color: var(--text2); }
  .dash-btn {
    font-size: 10px; font-weight: 700; color: var(--text);
    background: var(--accent); border-radius: 3px;
    padding: 3px 10px; text-decoration: none; white-space: nowrap;
  }
  .dash-btn:hover { background: var(--accent2); }
</style>
</head>
<body>
<script>
window.__GLA_STATUS__ = __STATUS_JSON_PLACEHOLDER__;
</script>
<div class="page">

  <div class="header">
    <div class="header-label">🦄 Garmin Local Archive</div>
    <div class="header-title">Archive Overview</div>
    <div class="header-sub" id="generated">—</div>
  </div>

  <div class="content">

    <div class="section-label">Archiv-Status</div>
    <div class="pills">
      <div class="pill"><span class="pill-label">fail</span><span class="pill-value" id="p-failed" style="color:var(--text2)">—</span></div>
      <div class="pill"><span class="pill-label">recheck</span><span class="pill-value" id="p-recheck" style="color:var(--text2)">—</span></div>
      <div class="pill"><span class="pill-label">missing</span><span class="pill-value" id="p-missing" style="color:var(--text2)">—</span></div>
    </div>
    <div class="status-row"><span class="lbl">Range</span>    <span class="val" id="s-range">—</span></div>
    <div class="status-row"><span class="lbl">Coverage</span> <span class="val" id="s-coverage" style="color:var(--green)">—</span></div>
    <div class="status-row"><span class="lbl">Last API</span> <span class="val" id="s-lastapi">—</span></div>
    <div class="status-row"><span class="lbl">Last Bulk</span><span class="val" id="s-lastbulk">—</span></div>
    <div class="integrity" id="integrity-box"></div>

    <div class="divider"></div>

    <div class="section-label">Geräte</div>
    <table>
      <thead>
        <tr>
          <th>From</th><th>To</th><th>Device</th>
          <th class="r">High</th><th class="r">Std</th><th class="r">Total</th>
        </tr>
      </thead>
      <tbody id="device-tbody"></tbody>
      <tfoot id="device-tfoot"></tfoot>
    </table>

    <div class="divider"></div>

    <div class="section-label">Dashboards</div>

    <div class="dash-card" id="card-mobile">
      <div class="dash-header">
        <div class="dash-meta">
          <span class="dash-icon">📱</span>
          <div>
            <div class="dash-name">Mobile Dashboard</div>
            <div class="dash-file" id="lbl-mobile">health_garmin_mobile.html</div>
          </div>
        </div>
        <button class="dash-btn" id="btn-mobile" onclick="showDash('mobile')">▶ öffnen</button>
      </div>
    </div>

    <div class="dash-card" id="card-sleep">
      <div class="dash-header">
        <div class="dash-meta">
          <span class="dash-icon">🌙</span>
          <div>
            <div class="dash-name">Sleep Dashboard</div>
            <div class="dash-file" id="lbl-sleep">sleep_garmin_html-xls_dash.html</div>
          </div>
        </div>
        <button class="dash-btn" id="btn-sleep" onclick="showDash('sleep')">▶ öffnen</button>
      </div>
    </div>

  </div>
</div>

<!-- ── Inline dashboard embeds (shown on demand, hidden by default) ────── -->
<div id="view-mobile" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:#12101f; z-index:100; overflow:auto;">
  <div style="position:fixed; top:8px; right:12px; z-index:200;">
    <button onclick="hideDash()" style="background:#a259f7; color:#fff; border:none; border-radius:4px; padding:6px 14px; font-size:13px; cursor:pointer;">✕ zurück</button>
  </div>
  <div id="content-mobile">__DASH_MOBILE_PLACEHOLDER__</div>
</div>

<div id="view-sleep" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:#12101f; z-index:100; overflow:auto;">
  <div style="position:fixed; top:8px; right:12px; z-index:200;">
    <button onclick="hideDash()" style="background:#a259f7; color:#fff; border:none; border-radius:4px; padding:6px 14px; font-size:13px; cursor:pointer;">✕ zurück</button>
  </div>
  <div id="content-sleep">__DASH_SLEEP_PLACEHOLDER__</div>
</div>

<script>
function showDash(which) {
  document.getElementById("view-mobile").style.display = "none";
  document.getElementById("view-sleep").style.display  = "none";
  var el = document.getElementById("view-" + which);
  if (el) el.style.display = "block";
  window.scrollTo(0, 0);
}
function hideDash() {
  document.getElementById("view-mobile").style.display = "none";
  document.getElementById("view-sleep").style.display  = "none";
}

(function () {
  // Mark buttons unavailable if dashboard was not embedded
  function markMissing(btnId, lblId) {
    var btn = document.getElementById(btnId);
    var lbl = document.getElementById(lblId);
    if (btn) { btn.textContent = "nicht verfügbar"; btn.disabled = true;
               btn.style.background = "#3a3a4a"; btn.style.cursor = "default"; }
    if (lbl) lbl.style.color = "var(--red)";
  }
  var cm = document.getElementById("content-mobile");
  var cs = document.getElementById("content-sleep");
  if (cm && cm.innerHTML.trim() === "") markMissing("btn-mobile", "lbl-mobile");
  if (cs && cs.innerHTML.trim() === "") markMissing("btn-sleep",  "lbl-sleep");
})();

(function () {
  var s = window.__GLA_STATUS__;
  if (!s) return;

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  function setColor(id, color) {
    var el = document.getElementById(id);
    if (el) el.style.color = color;
  }

  setText("generated", "Generated: " + (s.generated || "—"));

  setText("p-failed",  s.failed);
  setColor("p-failed",  s.failed  > 0 ? "var(--red)"    : "var(--green)");
  setText("p-recheck", s.recheck);
  setColor("p-recheck", s.recheck > 0 ? "var(--yellow)"  : "var(--green)");
  setText("p-missing", s.missing);

  setText("s-range",    s.range    || "—");
  setText("s-coverage", s.coverage || "—");
  setText("s-lastapi",  s.last_api  || "—");
  setText("s-lastbulk", s.last_bulk || "—");

  if (s.integrity) {
    var box = document.getElementById("integrity-box");
    if (box) { box.textContent = s.integrity; box.style.display = "block"; }
  }

  var tbody = document.getElementById("device-tbody");
  var tfoot = document.getElementById("device-tfoot");
  if (tbody && s.device_table) {
    s.device_table.forEach(function(row) {
      var tr = document.createElement("tr");
      tr.innerHTML =
        "<td>" + (row.date_from || "") + "</td>" +
        "<td>" + (row.date_to   || "") + "</td>" +
        "<td class='name'>" + (row.name || "") + "</td>" +
        "<td class='hi'>"  + (row.days_high     || "") + "</td>" +
        "<td class='r'>"   + (row.days_standard  || "") + "</td>" +
        "<td class='r'>"   + (row.days_total     || "") + "</td>";
      tbody.appendChild(tr);
    });
  }
  if (tfoot) {
    tfoot.innerHTML =
      "<tr>" +
      "<td colspan='2'></td>" +
      "<td>Total</td>" +
      "<td class='hi'>" + (s.total_high     || "") + "</td>" +
      "<td class='r'>"  + (s.total_standard  || "") + "</td>" +
      "<td class='r'>"  + (s.total_all       || "") + "</td>" +
      "</tr>";
  }
})();
</script>
</body>
</html>
"""
