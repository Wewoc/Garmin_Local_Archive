# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

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
# Sleep Dashboard demo (layouts/render/sleep.py output shape) — inlined,
# no file dependency. :root block is theme-linked 1:1 to theme.py's roles
# (bg0/bg/bg2/bg3/accent/accent2/text/text2/green/yellow/red); the sleep-
# phase colors, score/HRV gradients and quality badges stay fixed per
# theme.py's own convention (functional colors, not theme-bound).
_DEMO_SLEEP_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sleep Dashboard</title>
<style>
:root {
  --bg0:     __THEME_BG0__;
  --bg:      __THEME_BG__;
  --bg2:     __THEME_BG2__;
  --bg3:     __THEME_BG3__;
  --accent:  __THEME_ACCENT__;
  --accent2: __THEME_ACCENT2__;
  --text:    __THEME_TEXT__;
  --text2:   __THEME_TEXT2__;
  --green:   __THEME_GREEN__;
  --yellow:  __THEME_YELLOW__;
  --red:     __THEME_RED__;
}

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: var(--bg0); color: var(--text); }
  header { background: var(--bg2); color: var(--text); padding: 16px 24px; border-bottom: 1px solid var(--bg3); }
  header h1 { font-size: 20px; font-weight: 600; }
  header p  { font-size: 13px; color: var(--text2); margin-top: 4px; }
  .disclaimer { font-size: 11px; color: var(--text2); padding: 8px 24px 0; background: var(--bg); }
  footer { text-align: center; padding: 16px; font-size: 11px; color: var(--text2); }
</style>
<style>
/* Sleep-phase colors (Deep/Light/REM/Awake), score/HRV value gradients
   (hsl(...) inline styles), and quality badges (EXCELLENT/GOOD/FAIR/POOR)
   are functional colors and deliberately NOT theme-bound — see theme.py
   header notes ("They should look the same regardless of the chosen
   theme"). Only the table's structural surface colors follow the theme. */
.sleep-table { width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:13px; }
.sleep-table th { background:var(--bg2); color:var(--text2); padding:8px 10px; text-align:left; font-size:12px; font-weight:600; border-bottom:2px solid var(--accent); }
.sleep-table tr:nth-child(even) { background:var(--bg); }
.sleep-table tr:nth-child(odd)  { background:var(--bg0); }
.sleep-table tr:hover           { background:var(--bg3); }
.sleep-table td { color: var(--text); }
</style>
</head>
<body>

<header>
  <h1>🦄 GARMIN LOCAL ARCHIVE - Sleep Dashboard</h1>
  <p>2025-04-01 → 2025-04-14 · Sleep · HRV · Body Battery</p>
</header>
<div class="disclaimer">For personal informational use only — not medical advice. Data sourced from Garmin Connect via unofficial API.</div>

<div style="padding:16px 24px;">
<table class="sleep-table">
<thead>
<tr>
  <th>Date</th>
  <th>Sleep Phases</th>
  <th>Duration</th>
  <th>Score</th>
  <th>Quality</th>
  <th>Feedback</th>
  <th style="border-left:2px solid #2d6a9f;">HRV</th>
  <th>Body Battery</th>
  <th>HRV 7d Ø</th>
</tr>
</thead>
<tbody>

<!-- Row 1: EXCELLENT night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-14</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:19.2;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 19.2%">D</div>
      <div style="flex:52.1;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 52.1%">L</div>
      <div style="flex:22.4;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 22.4%">R</div>
      <div style="flex:6.3;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 6.3%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(101, 65%, 45%);">7.8h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(110, 65%, 45%);">88</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f5e5;color:#1a7a4a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">EXCELLENT</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">High Resting Heart Rate · Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(104, 65%, 45%);">62</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(114, 65%, 45%);">91</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(53, 65%, 45%);font-size:12px;">52.1</td>
</tr>

<!-- Row 2: GOOD night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-13</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:16.5;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 16.5%">D</div>
      <div style="flex:55.3;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 55.3%">L</div>
      <div style="flex:20.8;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 20.8%">R</div>
      <div style="flex:7.4;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 7.4%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(78, 65%, 45%);">7.4h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(93, 65%, 45%);">82</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f0f0;color:#1a6a6a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">GOOD</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(90, 65%, 45%);">58</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(96, 65%, 45%);">84</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(50, 65%, 45%);font-size:12px;">50.9</td>
</tr>

<!-- Row 3: FAIR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-12</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:12.1;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 12.1%">D</div>
      <div style="flex:58.7;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 58.7%">L</div>
      <div style="flex:18.2;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 18.2%">R</div>
      <div style="flex:11.0;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 11.0%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(42, 65%, 45%);">6.9h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(67, 65%, 45%);">72</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#fff3cc;color:#8a6a00;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">FAIR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Long But Not Enough REM</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(60, 65%, 45%);">48</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(72, 65%, 45%);">72</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(40, 65%, 45%);font-size:12px;">46.6</td>
</tr>

<!-- Row 4: GOOD night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-11</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:17.8;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 17.8%">D</div>
      <div style="flex:53.4;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 53.4%">L</div>
      <div style="flex:21.6;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 21.6%">R</div>
      <div style="flex:7.2;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 7.2%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(90, 65%, 45%);">7.6h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(87, 65%, 45%);">80</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f0f0;color:#1a6a6a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">GOOD</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">—</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(84, 65%, 45%);">56</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(102, 65%, 45%);">87</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(39, 65%, 45%);font-size:12px;">46.3</td>
</tr>

<!-- Row 5: POOR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-10</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:8.4;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 8.4%">D</div>
      <div style="flex:62.1;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 62.1%">L</div>
      <div style="flex:13.6;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 13.6%">R</div>
      <div style="flex:15.9;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 15.9%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(12, 65%, 45%);">6.1h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(27, 65%, 45%);">58</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#ffe0d0;color:#8a2000;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">POOR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Short · Not Enough Deep · Not Enough REM</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(18, 65%, 45%);">31</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(24, 65%, 45%);">47</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(39, 65%, 45%);font-size:12px;">46.4</td>
</tr>

<!-- Row 6: FAIR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-09</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:14.3;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 14.3%">D</div>
      <div style="flex:56.8;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 56.8%">L</div>
      <div style="flex:19.7;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 19.7%">R</div>
      <div style="flex:9.2;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 9.2%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(54, 65%, 45%);">7.1h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(60, 65%, 45%);">70</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#fff3cc;color:#8a6a00;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">FAIR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">High Stress · Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(48, 65%, 45%);">44</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(60, 65%, 45%);">68</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(50, 65%, 45%);font-size:12px;">51.0</td>
</tr>

<!-- Row 7: EXCELLENT night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-08</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:21.1;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 21.1%">D</div>
      <div style="flex:49.6;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 49.6%">L</div>
      <div style="flex:23.8;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 23.8%">R</div>
      <div style="flex:5.5;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 5.5%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(108, 65%, 45%);">8.1h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(115, 65%, 45%);">91</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f5e5;color:#1a7a4a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">EXCELLENT</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">—</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(110, 65%, 45%);">66</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(118, 65%, 45%);">96</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(53, 65%, 45%);font-size:12px;">52.1</td>
</tr>

<!-- Row 8: GOOD night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-07</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:15.9;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 15.9%">D</div>
      <div style="flex:54.2;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 54.2%">L</div>
      <div style="flex:22.1;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 22.1%">R</div>
      <div style="flex:7.8;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 7.8%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(72, 65%, 45%);">7.3h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(84, 65%, 45%);">78</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f0f0;color:#1a6a6a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">GOOD</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(78, 65%, 45%);">53</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(90, 65%, 45%);">80</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(45, 65%, 45%);font-size:12px;">48.7</td>
</tr>

<!-- Row 9: POOR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-06</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:9.7;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 9.7%">D</div>
      <div style="flex:60.4;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 60.4%">L</div>
      <div style="flex:15.8;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 15.8%">R</div>
      <div style="flex:14.1;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 14.1%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(6, 65%, 45%);">6.0h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(21, 65%, 45%);">55</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#ffe0d0;color:#8a2000;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">POOR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Short · High Resting Heart Rate</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(12, 65%, 45%);">28</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(18, 65%, 45%);">44</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(43, 65%, 45%);font-size:12px;">48.0</td>
</tr>

<!-- Row 10: FAIR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-05</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:13.5;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 13.5%">D</div>
      <div style="flex:57.2;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 57.2%">L</div>
      <div style="flex:20.3;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 20.3%">R</div>
      <div style="flex:9.0;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 9.0%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(48, 65%, 45%);">7.0h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(63, 65%, 45%);">71</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#fff3cc;color:#8a6a00;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">FAIR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Long But Not Enough REM · Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(54, 65%, 45%);">46</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(66, 65%, 45%);">70</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(53, 65%, 45%);font-size:12px;">52.0</td>
</tr>

<!-- Row 11: GOOD night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-04</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:18.2;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 18.2%">D</div>
      <div style="flex:52.7;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 52.7%">L</div>
      <div style="flex:21.9;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 21.9%">R</div>
      <div style="flex:7.2;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 7.2%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(84, 65%, 45%);">7.5h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(90, 65%, 45%);">81</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f0f0;color:#1a6a6a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">GOOD</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">—</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(87, 65%, 45%);">57</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(99, 65%, 45%);">85</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(56, 65%, 45%);font-size:12px;">53.5</td>
</tr>

<!-- Row 12: EXCELLENT night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-03</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:20.4;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 20.4%">D</div>
      <div style="flex:50.3;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 50.3%">L</div>
      <div style="flex:23.1;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 23.1%">R</div>
      <div style="flex:6.2;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 6.2%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(96, 65%, 45%);">7.7h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(112, 65%, 45%);">89</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f5e5;color:#1a7a4a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">EXCELLENT</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">—</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(100, 65%, 45%);">63</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(114, 65%, 45%);">93</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(54, 65%, 45%);font-size:12px;">52.3</td>
</tr>

<!-- Row 13: GOOD night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-02</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:16.0;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 16.0%">D</div>
      <div style="flex:54.9;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 54.9%">L</div>
      <div style="flex:21.3;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 21.3%">R</div>
      <div style="flex:7.8;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 7.8%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(75, 65%, 45%);">7.4h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(81, 65%, 45%);">77</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#d4f0f0;color:#1a6a6a;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">GOOD</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(75, 65%, 45%);">52</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(84, 65%, 45%);">78</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(41, 65%, 45%);font-size:12px;">47.0</td>
</tr>

<!-- Row 14: FAIR night -->
<tr>
  <td style="white-space:nowrap;padding:6px 10px;color:#ccc;">2025-04-01</td>
  <td style="padding:6px 10px;min-width:160px;">
    <div style="display:flex;width:100%;height:18px;border-radius:3px;overflow:hidden;">
      <div style="flex:11.8;background:#2d6a9f;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Deep: 11.8%">D</div>
      <div style="flex:59.3;background:#7eb8d4;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="Light: 59.3%">L</div>
      <div style="flex:18.9;background:#9b7fc7;display:flex;align-items:center;justify-content:center;font-size:9px;color:#fff;overflow:hidden;" title="REM: 18.9%">R</div>
      <div style="flex:10.0;background:#d4c5a9;display:flex;align-items:center;justify-content:center;font-size:9px;color:#555;overflow:hidden;" title="Awake: 10.0%">A</div>
    </div>
  </td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(30, 65%, 45%);">6.8h</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(57, 65%, 45%);">69</td>
  <td style="padding:6px 10px;text-align:center;"><span style="background:#fff3cc;color:#8a6a00;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;">FAIR</span></td>
  <td style="padding:6px 10px;"><span style="color:#aaa;font-size:12px;">High Resting Heart Rate · Not Enough Deep</span></td>
  <td style="padding:6px 10px;text-align:center;border-left:2px solid var(--bg3);font-weight:700;color:hsl(42, 65%, 45%);">42</td>
  <td style="padding:6px 10px;text-align:center;font-weight:700;color:hsl(54, 65%, 45%);">65</td>
  <td style="padding:6px 10px;text-align:center;color:hsl(29, 65%, 45%);font-size:12px;">42.0</td>
</tr>

</tbody>
</table>

<!-- Phase legend -->
<div style="display:flex;gap:16px;margin-top:12px;padding:8px 4px;flex-wrap:wrap;">
  <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);">
    <div style="width:14px;height:14px;background:#2d6a9f;border-radius:2px;"></div> Deep
  </div>
  <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);">
    <div style="width:14px;height:14px;background:#7eb8d4;border-radius:2px;"></div> Light
  </div>
  <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);">
    <div style="width:14px;height:14px;background:#9b7fc7;border-radius:2px;"></div> REM
  </div>
  <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text2);">
    <div style="width:14px;height:14px;background:#d4c5a9;border-radius:2px;"></div> Awake
  </div>
  <div style="margin-left:16px;font-size:11px;color:var(--text2);">
    Color intensity: gradient against personal reference ranges (HRV 30–80 ms · Duration 7.0–9.0 h · Body Battery 50–100)
  </div>
</div>

</div>

<footer>Garmin Local Archive · <span style="color:var(--accent);">github.com/Wewoc/Garmin_Local_Archive</span> · Demo data — not real health data</footer>
</body>
</html>
"""

DEMO_SLEEP_HTML = (
    _DEMO_SLEEP_HTML_TEMPLATE
    .replace("__THEME_BG0__",     theme.BG0)
    .replace("__THEME_BG__",      theme.BG)
    .replace("__THEME_BG2__",     theme.BG2)
    .replace("__THEME_BG3__",     theme.BG3)
    .replace("__THEME_ACCENT__",  theme.ACCENT)
    .replace("__THEME_ACCENT2__", theme.ACCENT2)
    .replace("__THEME_TEXT__",    theme.TEXT)
    .replace("__THEME_TEXT2__",   theme.TEXT2)
    .replace("__THEME_GREEN__",   theme.GREEN)
    .replace("__THEME_YELLOW__",  theme.YELLOW)
    .replace("__THEME_RED__",     theme.RED)
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

# Demo MCP server log (Chat tab, datasource "mcp") — matches the tool
# call the demo chat conversation below narrates (intraday heart rate
# for 2026-06-05). Format mirrors clients/mcp_server.py's real
# operational log (%(asctime)s %(levelname)s %(name)s: %(message)s);
# the startup/boot-sync lines are the module's real log messages, the
# POST line is the streamable-http transport's own uvicorn access log
# — no fabricated internal log statement.
DEMO_MCP_LOG = (
    "2026-06-06 09:14:02 INFO clients.mcp_server: Starting Garmin Local "
    "Archive MCP server (headless) on 127.0.0.1:8756\n"
    "2026-06-06 09:14:02 INFO clients.mcp_server: Operational log started "
    "under C:\\Users\\Demo\\garmin_data\\garmin_data\\log\\mcp — boot log closed\n"
    "2026-06-06 09:14:03 INFO clients.mcp_server: Starting SQLite proxy "
    "boot sync...\n"
    "2026-06-06 09:14:04 INFO clients.mcp_server: Boot sync complete: "
    "{'rows_indexed': 5312, 'days_covered': 290}\n"
    "2026-06-06 09:22:17 INFO uvicorn.access: 127.0.0.1:54331 - "
    "\"POST /mcp HTTP/1.1\" 200 OK\n"
)


class ScreenshotApp(GarminApp):
    """
    GarminApp subclass for screenshots and documentation.

    What is overridden:
      __init__              — bypasses real settings/password load, fills demo data,
                              sets connection indicators green, writes demo log,
                              disables all buttons.
      closeEvent            — destroys window without saving anything.
      _refresh_archive_info — static demo values.
      _scan_dashboards      — loads embedded DEMO_SLEEP_HTML into Tab 2, no file I/O.
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
        """Populate the Chat tab (panel_chat.py) with demo state —
        no live Ollama/MCP call, no file I/O. Opens on datasource "mcp"
        (Baustein 9 split-view) so the screenshot shows the v1.7.2 live-
        query path (right pane: matching demo MCP server log) instead of
        the pre-v1.7.2 summary-only limitation. Two exchanges: one
        answerable from the daily snapshot either way, one that only the
        "mcp" datasource can answer (intraday resolution)."""
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

        pc._datasource_combo.blockSignals(True)
        pc._datasource_combo.setCurrentText("mcp")
        pc._datasource_combo.blockSignals(False)
        pc._chat_apply_datasource_visibility(True)
        pc._log_view.setPlainText(DEMO_MCP_LOG)

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
            "Pulling intraday heart rate for 2026-06-05 from the archive "
            "via the MCP server... It stayed in the low 50s overnight "
            "(49 bpm min at 03:40), rose through the morning to a daytime "
            "average of 64 bpm, with a brief spike to 88 bpm around 14:15 "
            "(a 30-minute walk), then settled back into the high 50s by "
            "22:00.")

    def _disable_all_buttons(self):
        """Walk every QPushButton and replace command with no-op."""
        # Use Qt's own recursive widget walk
        for btn in self.findChildren(QPushButton):
            try:
                btn.clicked.disconnect()
            except RuntimeError:
                pass
            btn.setCursor(Qt.CursorShape.ArrowCursor)

    # ── Override: demo dashboard — no real files ───────────────────────────────

    def _scan_dashboards(self, auto_load: str = None):
        """Load embedded DEMO_SLEEP_HTML into Tab 2. No file scan, no real data."""
        self._panel_home._dash_combo.blockSignals(True)
        self._panel_home._dash_combo.clear()
        self._panel_home._dash_combo.addItem("Sleep Dashboard (Demo)")
        self._panel_home._dash_combo.setEnabled(True)
        self._panel_home._dash_combo.blockSignals(False)
        self._panel_home._dash_view.setHtml(DEMO_SLEEP_HTML, QUrl("about:blank"))

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
