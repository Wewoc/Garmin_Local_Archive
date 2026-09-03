# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

95#!/usr/bin/env python3
"""
garmin_app_screenshot.py
Garmin Local Archive — Screenshot / Demo Mode

Inherits the complete UI from GarminApp without modification.
Overrides only:
  - Settings / password loading  → dummy data
  - All button commands          → no-ops
  - closeEvent                   → no save

Usage PowerShell:
    python .\\garmin_app_screenshot.py

Optional automated mode (used by external multi-theme screenshot
tooling — lives outside this repo):
    python .\\garmin_app_screenshot.py --auto-shot <output_dir>

    Iterates every tab of the running window, saves one JPEG per tab
    into <output_dir> (created if missing), then exits automatically.
    Without --auto-shot, behavior is 100% unchanged (window stays open,
    manual close).

No credentials, no file I/O (except the JPEGs written under
--auto-shot), no subprocesses.
Safe to run on any machine.
"""

import argparse
import sys
from pathlib import Path

# sys.path setup — identical to garmin_app.py
_root = Path(__file__).parent
for _sub in ("garmin", "maps", "dashboards", "layouts", "context"):
    sys.path.insert(0, str(_root / _sub))
sys.path.insert(0, str(_root / "app"))

from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtCore import Qt, QUrl, QTimer

from garmin_app import GarminApp
import theme


# ── Demo dashboard HTML (embedded — no file dependency) ───────────────────────
# dashboard_desktop.html inlined — Chart.js loaded from cdnjs (requires internet)

# Header background/text and the two theme-linked tokens below are the
# only theme-linked parts of this otherwise fixed light-mode demo report
# (same pattern as dash_layout_html.py/_MOBILE_CSS — see theme01-03).
_DEMO_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1200">
<title>Garmin Health Analysis — Desktop</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f2f5;min-width:1200px}
.app{width:1200px;margin:0 auto;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.12)}
.header{background:__THEME_BG3__;color:#e8edf5;padding:16px 28px}
.header h1{font-size:18px;font-weight:500;letter-spacing:.01em;margin-bottom:3px}
.header p{font-size:12px;color:#8a9ab8;letter-spacing:.02em}
.notice{background:#fffbea;border-bottom:1px solid #f0d878;padding:10px 28px;font-size:12px;color:#7a6010;display:flex;align-items:center;gap:8px}
.meta{padding:11px 28px;font-size:13px;color:#555;display:flex;gap:24px;border-bottom:1px solid #e8eaed;background:#fafbfc}
.meta strong{color:__THEME_BG3__}
.legend-row{padding:8px 28px;display:flex;gap:24px;align-items:center;border-bottom:1px solid #e8eaed;background:#fafbfc}
.leg{display:flex;align-items:center;gap:7px;font-size:12px;color:#666}
.l-solid{width:30px;height:2px;background:__THEME_ACCENT__}
.l-dash{width:30px;height:0;border-top:2px dashed __THEME_ACCENT__;opacity:.6}
.l-rect{width:18px;height:12px;background:#cde8c8;border:1px solid #a6cfa0;border-radius:2px}
.tabs{display:flex;padding:0 28px;border-bottom:1px solid #dde0e6;background:#fff}
.tab{padding:11px 18px;font-size:13px;cursor:pointer;border:none;border-bottom:2px solid transparent;background:none;color:#666;font-family:inherit}
.tab.active{color:#2660b0;border-bottom-color:#2660b0;font-weight:500}
.tab:hover:not(.active){color:#333}
.chart-section{padding:16px 28px 12px;background:#fff}
.y-label{font-size:11px;color:#888;margin-bottom:6px}
.chart-wrap{position:relative;width:100%;height:340px}
.footer{text-align:center;font-size:11px;color:#999;padding:12px 28px;border-top:1px solid #e8eaed;background:#fafbfc}
.footer a{color:__THEME_ACCENT__;text-decoration:none}
</style>
</head>
<body>
<div class="app">
  <div class="header">
    <h1>🦄 GARMIN LOCAL ARCHIVE - Garmin Health Analysis</h1>
    <p>2024-06-01 → 2025-03-15 &nbsp;·&nbsp; 90-day rolling baseline &nbsp;·&nbsp; Age/fitness-adjusted reference ranges</p>
  </div>
  <div class="notice">⚠&nbsp; Informational only — not medical advice. Reference ranges are general health guidelines (AHA, ACSM, Garmin/Firstbeat). Consult a healthcare professional for medical decisions.</div>
  <div class="meta">
    <span>Age: <strong>38</strong></span>
    <span>Sex: <strong>male</strong></span>
    <span>VO2max: <strong>47.2</strong></span>
    <span>Fitness level: <strong>excellent</strong></span>
  </div>
  <div class="legend-row">
    <div class="leg"><div class="l-solid"></div>Daily value</div>
    <div class="leg"><div class="l-dash"></div>90d baseline</div>
    <div class="leg"><div class="l-rect"></div>Reference range</div>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="switchTab(0,this)">HRV</button>
    <button class="tab" onclick="switchTab(1,this)">Resting HR</button>
    <button class="tab" onclick="switchTab(2,this)">Sleep</button>
    <button class="tab" onclick="switchTab(3,this)">Body Battery</button>
    <button class="tab" onclick="switchTab(4,this)">Stress</button>
    <button class="tab" onclick="switchTab(5,this)">SpO2</button>
  </div>
  <div class="chart-section">
    <div class="chart-wrap"><canvas id="mainChart" role="img" aria-label="Health metric time series">Loading…</canvas></div>
  </div>
  <div class="footer">
    Generated locally &nbsp;·&nbsp; No data sent externally &nbsp;·&nbsp; <a href="https://github.com/Wewoc/Garmin_Local_Archive">github.com/Wewoc/Garmin_Local_Archive</a> &nbsp;·&nbsp; GNU GPL v3 &nbsp;·&nbsp; <em>Synthetic demo data</em>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const N=288;
function gen(base,amp,noise,trend){
  const a=[];
  let rng=42;
  function rand(){rng=(rng*1664525+1013904223)&0xffffffff;return(rng>>>0)/0xffffffff;}
  for(let i=0;i<N;i++){
    const v=base+trend*(i/N)+amp*Math.sin(i/20)*Math.cos(i/7)+(rand()-.5)*noise;
    a.push(Math.round(v*10)/10);
  }
  return a;
}
function moving(arr,w){
  return arr.map((_,i)=>{
    const s=Math.max(0,i-w+1),sl=arr.slice(s,i+1);
    return Math.round(sl.reduce((a,b)=>a+b,0)/sl.length*10)/10;
  });
}
const labels=[];
for(let i=0;i<N;i++){const d=new Date(2024,5,1);d.setDate(d.getDate()+i);labels.push(d.toISOString().slice(0,10));}
const DS={
  hrv:{raw:gen(56,8,6,-8),ref:[45,85],yLabel:'HRV (ms)',yMin:25,yMax:110,color:'__THEME_ACCENT__'},
  rhr:{raw:gen(52,4,3,4),ref:[45,65],yLabel:'HR (bpm)',yMin:35,yMax:80,color:'#b84a2e'},
  sleep:{raw:gen(6.8,0.8,.5,-.3),ref:[7,9],yLabel:'Sleep (h)',yMin:3,yMax:10,color:'#5a3db8'},
  bb:{raw:gen(72,15,8,-10),ref:[60,100],yLabel:'Body Battery',yMin:0,yMax:100,color:'#2e8b57'},
  stress:{raw:gen(35,12,8,5),ref:[20,50],yLabel:'Stress',yMin:0,yMax:100,color:'#c07a10'},
  spo2:{raw:gen(97,1,.5,0),ref:[95,100],yLabel:'SpO2 (%)',yMin:90,yMax:100,color:'#2a8faa'},
};
const keys=['hrv','rhr','sleep','bb','stress','spo2'];
let chart=null;
function buildChart(idx){
  const k=keys[idx],d=DS[k],base=moving(d.raw,90);
  if(chart){chart.destroy();chart=null;}
  const ctx=document.getElementById('mainChart').getContext('2d');
  chart=new Chart(ctx,{
    type:'line',
    data:{labels,datasets:[
      {label:'ref_hi',data:Array(N).fill(d.ref[1]),fill:'-1',backgroundColor:'rgba(180,225,170,.32)',borderColor:'transparent',borderWidth:0,pointRadius:0,tension:0,order:3},
      {label:'ref_lo',data:Array(N).fill(d.ref[0]),fill:false,borderColor:'transparent',borderWidth:0,pointRadius:0,tension:0,order:3},
      {label:'90d baseline',data:base,borderColor:d.color,borderWidth:1.5,borderDash:[5,4],pointRadius:0,fill:false,tension:.4,order:2},
      {label:'Daily value',data:d.raw,borderColor:d.color,borderWidth:1.5,pointRadius:1.8,pointBackgroundColor:d.color,fill:false,tension:0,order:1},
    ]},
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{display:false},
        tooltip:{filter:i=>i.datasetIndex>=2,callbacks:{label:ctx=>ctx.datasetIndex===2?'90d: '+ctx.formattedValue:'Value: '+ctx.formattedValue}}
      },
      scales:{
        x:{type:'category',ticks:{maxTicksLimit:10,maxRotation:0,font:{size:11},color:'#888'},grid:{color:'rgba(0,0,0,.04)'}},
        y:{min:d.yMin,max:d.yMax,title:{display:true,text:d.yLabel,font:{size:11},color:'#888'},ticks:{font:{size:11},color:'#888'},grid:{color:'rgba(0,0,0,.05)'}}
      }
    }
  });
}
function switchTab(idx,el){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  buildChart(idx);
}
buildChart(0);
</script>
</body>
</html>

"""

DEMO_HTML = (
    _DEMO_HTML_TEMPLATE
    .replace("__THEME_BG3__",    theme.BG3)
    .replace("__THEME_ACCENT__", theme.ACCENT)
)

# ── Demo XLSX table (embedded — no file dependency) ───────────────────────────

_DEMO_XLSX_HTML_TEMPLATE = """<!DOCTYPE html><html><head><meta charset='UTF-8'>
<style>
body{background:__THEME_BG__;margin:0;padding:12px;font-family:'Segoe UI',sans-serif;}
table{border-collapse:collapse;width:100%;}
th{background:__THEME_BG3__;color:__THEME_ACCENT__;padding:6px 12px;text-align:left;font-size:11px;font-weight:600;border-bottom:1px solid __THEME_ACCENT__;}
td{padding:5px 12px;font-size:11px;color:__THEME_TEXT__;border-bottom:1px solid __THEME_BG3__;}
tr:nth-child(even) td{background:__THEME_BG2__;}
</style></head><body>
<table>
<thead><tr>
<th>Date</th><th>Steps</th><th>Resting HR</th><th>Body Battery</th><th>Sleep (h)</th><th>Quality</th>
</tr></thead>
<tbody>
<tr><td>2026-06-07</td><td>9 842</td><td>52</td><td>87</td><td>7.4</td><td>high</td></tr>
<tr><td>2026-06-06</td><td>11 203</td><td>51</td><td>91</td><td>7.8</td><td>high</td></tr>
<tr><td>2026-06-05</td><td>7 654</td><td>54</td><td>74</td><td>6.9</td><td>standard</td></tr>
<tr><td>2026-06-04</td><td>13 401</td><td>50</td><td>95</td><td>8.1</td><td>high</td></tr>
<tr><td>2026-06-03</td><td>8 177</td><td>53</td><td>80</td><td>7.2</td><td>high</td></tr>
<tr><td>2026-06-02</td><td>6 290</td><td>56</td><td>68</td><td>6.5</td><td>standard</td></tr>
<tr><td>2026-06-01</td><td>10 558</td><td>52</td><td>88</td><td>7.6</td><td>high</td></tr>
<tr><td>2026-05-31</td><td>12 034</td><td>49</td><td>93</td><td>8.0</td><td>high</td></tr>
<tr><td>2026-05-30</td><td>5 812</td><td>57</td><td>61</td><td>6.1</td><td>standard</td></tr>
<tr><td>2026-05-29</td><td>9 321</td><td>53</td><td>82</td><td>7.3</td><td>high</td></tr>
</tbody>
</table>
</body></html>"""

DEMO_XLSX_HTML = (
    _DEMO_XLSX_HTML_TEMPLATE
    .replace("__THEME_BG__",     theme.BG)
    .replace("__THEME_BG2__",    theme.BG2)
    .replace("__THEME_BG3__",    theme.BG3)
    .replace("__THEME_ACCENT__", theme.ACCENT)
    .replace("__THEME_TEXT__",   theme.TEXT)
)

# ── Dummy data ─────────────────────────────────────────────────────────────────

DEMO = {
    "email":              "demo@example.com",
    "password":           "MySecurePassword",
    "base_dir":           r"C:\Users\Demo\garmin_data",
    "sync_mode":          "recent",
    "sync_days":          "90",
    "sync_from":          "2023-01-01",
    "sync_to":            "2023-12-31",
    "sync_auto_fallback": "365",
    "date_from":          "",
    "date_to":            "",
    "age":                "35",
    "sex":                "male",
    "request_delay_min":  "5.0",
    "request_delay_max":  "20.0",
    "timer_min_interval": "5",
    "timer_max_interval": "30",
    "timer_min_days":     "3",
    "timer_max_days":     "10",
    "context_latitude":   "0.0",
    "context_longitude":  "0.0",
    "context_location":   "",
    "mirror_dir":         "",
    "backup_raw_backfill_asked": False,
}

DEMO_LOG = [
    "✓ Settings loaded.",
    "✓ Connection verified — Garmin Connect reachable.",
    "▶  Sync started  [recent · 90 days]",
    "  → 2024-03-15  high   ✓",
    "  → 2024-03-14  high   ✓",
    "  → 2024-03-13  standard ✓",
    "  → 2024-03-12  high   ✓",
    "  → 2024-03-11  high   ✓",
    "✓ Sync complete — 5 days processed.",
]


class ScreenshotApp(GarminApp):
    """
    GarminApp subclass for screenshots and documentation.

    What is overridden:
      __init__              — bypasses real settings/password load, fills demo data,
                              sets connection indicators green, writes demo log,
                              disables all buttons.
      closeEvent            — destroys window without saving anything.
      _refresh_archive_info — static demo values.
      _scan_dashboards      — loads embedded DEMO_HTML into Tab 2, no file I/O.
      _scan_xlsx_files      — loads embedded DEMO_XLSX_HTML into Tab 3, no file I/O.

    Everything else (layout, colours, fonts, sections, widgets) is inherited
    directly from GarminApp and stays in sync automatically.
    """

    def __init__(self, auto_shot_dir: str = None):
        from PyQt6.QtCore import QTimer
        super().__init__()
        self._auto_shot_dir = auto_shot_dir
        self._auto_shot_index = 0
        self._load_demo_settings()
        self._set_connection_indicators_green()
        self._write_demo_log()
        self._load_demo_chat()
        self._disable_all_buttons()
        self.setWindowTitle("Garmin Local Archive  [SCREENSHOT MODE]")
        if self._auto_shot_dir:
            # Fixed, generous window size for auto-shot mode — the default
            # window size can be too small to show tab content (e.g. the
            # HRV/Resting HR/... chart in the Dashboard tab) without
            # scrolling, and self.grab() only captures what's visible.
            self.resize(1500, 1150)
        # Delay so table widget is fully laid out before we insert rows
        QTimer.singleShot(100, self._refresh_archive_info)
        if self._auto_shot_dir:
            # Extra delay on top of the table refresh above, so dashboard/
            # xlsx HTML views also have time to finish rendering before the
            # first tab screenshot is taken.
            QTimer.singleShot(500, self._auto_shot_next_tab)

    # ── Auto-shot mode (used by external multi-theme screenshot tooling) ───────

    def _auto_shot_next_tab(self):
        """Advance to the next tab, wait for it to settle, capture a JPEG,
        then either schedule the next tab or quit once all tabs are done.
        Guessed settle delay (400ms) — first thing to tune if a captured
        tab looks empty or half-rendered."""
        tabs = self._right_tabs
        if self._auto_shot_index >= tabs.count():
            QApplication.instance().quit()
            return
        tabs.setCurrentIndex(self._auto_shot_index)
        QTimer.singleShot(400, self._auto_shot_capture_current_tab)

    def _auto_shot_capture_current_tab(self):
        out_dir = Path(self._auto_shot_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tab_title = self._right_tabs.tabText(self._auto_shot_index)
        slug = tab_title.lower().replace(" ", "_").replace("-", "_")
        target = out_dir / f"{slug}.jpg"
        self.grab().save(str(target), "JPG", quality=90)
        self._auto_shot_index += 1
        self._auto_shot_next_tab()

    # ── Demo settings ──────────────────────────────────────────────────────────

    def _load_demo_settings(self):
        ps = self._panel_settings
        ps._email.setText(DEMO["email"])
        ps._password.setText(DEMO["password"])
        ps._base_dir.setText(DEMO["base_dir"])
        ps._mirror_dir.setText(DEMO["mirror_dir"])
        idx = ps._sync_mode.findText(DEMO["sync_mode"])
        ps._sync_mode.setCurrentIndex(max(0, idx))
        ps._sync_days.setText(DEMO["sync_days"])
        ps._sync_from.setText(DEMO["sync_from"])
        ps._sync_to.setText(DEMO["sync_to"])
        ps._sync_fallback.setText(DEMO["sync_auto_fallback"])
        ps._date_from.setText(DEMO["date_from"])
        ps._date_to.setText(DEMO["date_to"])
        ps._age.setText(DEMO["age"])
        idx_sex = ps._sex.findText(DEMO["sex"])
        ps._sex.setCurrentIndex(max(0, idx_sex))
        ps._delay_min.setText(DEMO["request_delay_min"])
        ps._delay_max.setText(DEMO["request_delay_max"])
        pt = self._panel_timer
        pt._timer_min_interval.setText(DEMO["timer_min_interval"])
        pt._timer_max_interval.setText(DEMO["timer_max_interval"])
        pt._timer_min_days.setText(DEMO["timer_min_days"])
        pt._timer_max_days.setText(DEMO["timer_max_days"])
        ps._on_sync_mode_change()

    # ── Override: close without saving ────────────────────────────────────────

    def closeEvent(self, event):
        self._timer_generation += 1
        self._timer_stop.set()
        event.accept()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_connection_indicators_green(self):
        for dot in self._panel_home._conn_indicators.values():
            dot.setStyleSheet(f"color: {self.GREEN};")

    def _refresh_archive_info(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        ph = self._panel_home
        ph._info_qdots["failed"].setText("fail 9")
        ph._info_recheck.setText("Recheck: 0")
        ph._info_missing.setText("Missing: 0")
        ph._info_source.setText("Source: 290 days · 178/180d")
        ph._info_range.setText("Range: 2018-12-19 → 2026-06-06")
        ph._info_coverage.setText("Coverage: 100%")
        ph._info_last_api.setText("Last API: 2026-06-06")
        ph._info_last_bulk.setText("Last Bulk: 2023-12-31")

        # Device table — demo rows
        _DEMO_ROWS = [
            ("2024-09-12", "2026-06-06", "fenix 7X Sapphire Solar", 312, 181, 493),
            ("2022-03-04", "2024-09-11", "fenix 5x",                  0, 684, 684),
            ("2019-01-07", "2022-03-03", "vívoactive 3",               0,1147,1147),
        ]
        tbl = ph._info_device_table
        tbl.setRowCount(0)
        total_high = total_std = total_all = 0
        for date_from, date_to, name, high, std, total in _DEMO_ROWS:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(date_from))
            tbl.setItem(r, 1, QTableWidgetItem(date_to))
            tbl.setItem(r, 2, QTableWidgetItem(name))
            tbl.setItem(r, 3, QTableWidgetItem(str(high) if high else ""))
            tbl.setItem(r, 4, QTableWidgetItem(str(std)))
            tbl.setItem(r, 5, QTableWidgetItem(str(total)))
            for col in (3, 4, 5):
                item = tbl.item(r, col)
                if item:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            total_high += high
            total_std  += std
            total_all  += total
        # Summary row
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 2, QTableWidgetItem("Total"))
        tbl.setItem(r, 3, QTableWidgetItem(str(total_high) if total_high else ""))
        tbl.setItem(r, 4, QTableWidgetItem(str(total_std)))
        tbl.setItem(r, 5, QTableWidgetItem(str(total_all)))
        for col in (2, 3, 4, 5):
            item = tbl.item(r, col)
            if item:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                f = item.font()
                f.setBold(True)
                item.setFont(f)
        # Fix height
        row_h  = tbl.verticalHeader().defaultSectionSize()
        hdr_h  = tbl.horizontalHeader().height()
        tbl.setFixedHeight(hdr_h + row_h * tbl.rowCount() + 4)

    def _write_demo_log(self):
        for line in DEMO_LOG:
            self._log(line)

    def _load_demo_chat(self):
        """Populate the Ollama-Chat tab (panel_chat.py) with demo state —
        no live Ollama call, no file I/O. Two exchanges: one answerable
        from current summary data, one that surfaces the current
        summary-only limitation (full intraday resolution planned for v1.9)."""
        pc = self._panel_chat
        pc._age_label.setText("Context files: health_garmin.json — 2026-06-06 (today)")
        pc._reach_label.setText("Ollama: reachable")
        pc._model_combo.blockSignals(True)
        pc._model_combo.clear()
        pc._model_combo.addItems(["qwen3:14b", "llama3.1:8b"])
        pc._model_combo.blockSignals(False)
        pc._model_combo.setEnabled(True)
        pc._new_chat_btn.setEnabled(True)
        pc._input.setEnabled(True)
        pc._send_btn.setEnabled(True)
        pc._start_btn.setEnabled(False)

        pc._chat_append_line(
            "You",
            "How was my sleep and HRV over the past week?")
        pc._chat_append_line(
            "Assistant",
            "Your HRV averaged 61 ms, slightly above your 90-day baseline "
            "of 58 ms. Sleep averaged 7.4h at mostly \"high\" quality, "
            "except Tuesday (6.1h, \"standard\"). Resting HR stayed stable "
            "between 51 and 54 bpm all week.")
        pc._chat_append_line(
            "You",
            "Can you show me my heart rate curve minute-by-minute for yesterday?")
        pc._chat_append_line(
            "Assistant",
            "I currently only have access to your daily summary data — "
            "resting HR, sleep duration, HRV, Body Battery, etc. "
            "Minute-level intraday values aren't wired in yet; that's "
            "planned for v1.9. For yesterday I can tell you: resting HR "
            "52 bpm, HRV 58 ms, sleep 7.6h at \"high\" quality.")

    def _disable_all_buttons(self):
        """Walk every QPushButton and replace command with no-op."""
        def _walk(widget):
            if isinstance(widget, QPushButton):
                try:
                    widget.clicked.disconnect()
                except RuntimeError:
                    pass
                widget.setCursor(Qt.CursorShape.ArrowCursor)
            for child in widget.findChildren(type(widget).__mro__[0]):
                pass  # findChildren handles recursion
        # Use Qt's own recursive widget walk
        for btn in self.findChildren(QPushButton):
            try:
                btn.clicked.disconnect()
            except RuntimeError:
                pass
            btn.setCursor(Qt.CursorShape.ArrowCursor)

    # ── Override: demo dashboard — no real files ───────────────────────────────

    def _scan_dashboards(self, auto_load: str = None):
        """Load embedded DEMO_HTML into Tab 2. No file scan, no real data."""
        self._panel_home._dash_combo.blockSignals(True)
        self._panel_home._dash_combo.clear()
        self._panel_home._dash_combo.addItem("Garmin Health Analysis (Demo)")
        self._panel_home._dash_combo.setEnabled(True)
        self._panel_home._dash_combo.blockSignals(False)
        self._panel_home._dash_view.setHtml(DEMO_HTML, QUrl("about:blank"))

    def _scan_xlsx_files(self):
        """Load embedded DEMO_XLSX_HTML into Tab 3. No file scan, no real data."""
        self._xlsx_combo.blockSignals(True)
        self._xlsx_combo.clear()
        self._xlsx_combo.addItem("Garmin Health Summary (Demo).xlsx")
        self._xlsx_combo.setEnabled(True)
        self._xlsx_open_btn.setEnabled(False)
        self._xlsx_combo.blockSignals(False)
        self._xlsx_view.setHtml(DEMO_XLSX_HTML, QUrl("about:blank"))


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--auto-shot",
        metavar="OUTPUT_DIR",
        default=None,
        help=(
            "Automated mode: capture one JPEG per tab into OUTPUT_DIR, "
            "then exit. Without this flag, behavior is unchanged."
        ),
    )
    args = parser.parse_args()

    qapp = QApplication(sys.argv)
    qapp.setStyle("Fusion")
    window = ScreenshotApp(auto_shot_dir=args.auto_shot)
    window.show()
    sys.exit(qapp.exec())
