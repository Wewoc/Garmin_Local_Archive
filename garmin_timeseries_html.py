#!/usr/bin/env python3
"""
garmin_timeseries_html.py

Reads raw JSON files and generates an interactive HTML dashboard
with one tab per metric. Fully self-contained — no internet required.

Metrics: Heart Rate, Stress, SpO2, Body Battery, Respiration

Configuration via environment variables (all optional — hardcoded fallbacks below):
  GARMIN_OUTPUT_DIR       Root data folder (raw/ lives here)
  GARMIN_DASHBOARD_FILE   Full path for the output .html file
  GARMIN_DATE_FROM        Start date (YYYY-MM-DD)
  GARMIN_DATE_TO          End date (YYYY-MM-DD)
"""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — edit fallback values here, or set environment variables.
#  Environment variables always take priority over the values below.
# ══════════════════════════════════════════════════════════════════════════════

_BASE = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()

RAW_DIR     = _BASE / "raw"
OUTPUT_FILE = Path(os.environ.get("GARMIN_DASHBOARD_FILE",
                   str(_BASE / "garmin_dashboard.html")))

# Date range — format: "YYYY-MM-DD"
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "2026-03-01")
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "2026-03-16")

# ══════════════════════════════════════════════════════════════════════════════

# Metrics to include (True = show, False = hide)
METRICS = {
    "heart_rate":   True,
    "stress":       True,
    "spo2":         True,
    "body_battery": True,
    "respiration":  True,
}

# ══════════════════════════════════════════════════════════════════════════════
#  Data extraction  (same logic as garmin_timeseries_excel.py)
# ══════════════════════════════════════════════════════════════════════════════

def ts_to_iso(ts) -> str:
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return str(ts)[:19]
    except Exception:
        return str(ts)


def extract_pairs(raw, key, val_field, ts_field=None):
    """Generic extractor for [ts, val] lists or list-of-dicts."""
    day    = raw.get("date", "")
    source = raw.get(key)
    if isinstance(source, dict):
        for candidate in ("heartRateValues", "bodyBatteryValuesArray",
                          "respirationValuesArray", "respirationValues",
                          "spO2HourlyAverages", "continuousReadingDTOList"):
            if candidate in source:
                source = source[candidate]
                break
    if not isinstance(source, list):
        return []
    rows = []
    for item in source:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts, val = item[0], item[1]
        elif isinstance(item, dict):
            ts  = item.get(ts_field or "startGMT") or item.get("timestamp")
            val = item.get(val_field) or item.get("value")
        else:
            continue
        if val is not None:
            try:
                rows.append((day, ts_to_iso(ts), float(val)))
            except (TypeError, ValueError):
                continue
    return rows


def extract_stress_rows(raw):
    """
    Stress: stress.stressValuesArray is a list of [ts, val] pairs.
    Negative values = unmeasured periods, filtered out.
    Offset applied if stressChartValueOffset is set.
    """
    day  = raw.get("date", "")
    src  = raw.get("stress")
    rows = []
    if not isinstance(src, dict):
        return rows
    arr    = src.get("stressValuesArray") or []
    offset = src.get("stressChartValueOffset") or 0
    for item in arr:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts, val = item[0], item[1]
        elif isinstance(item, dict):
            ts  = item.get("startGMT") or item.get("timestamp")
            val = item.get("stressLevel") or item.get("value")
        else:
            continue
        try:
            v = float(val) - offset
            if v >= 0:
                rows.append((day, ts_to_iso(ts), v))
        except (TypeError, ValueError):
            continue
    return rows


def extract_body_battery_rows(raw):
    """
    Body battery: stress.bodyBatteryValuesArray is a list of
    [ts, status_str, level, version] sublists. Level is at index 2.
    """
    day  = raw.get("date", "")
    rows = []
    src  = raw.get("stress") or {}
    arr  = src.get("bodyBatteryValuesArray") if isinstance(src, dict) else None
    if not arr:
        bb  = raw.get("body_battery") or {}
        arr = bb.get("bodyBatteryValuesArray") if isinstance(bb, dict) else None
    if not isinstance(arr, list):
        return rows
    for item in arr:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            ts, val = item[0], item[2]   # index 2 = bodyBatteryLevel
        elif isinstance(item, dict):
            ts  = item.get("startGMT") or item.get("timestamp")
            val = item.get("bodyBatteryLevel") or item.get("value")
        else:
            continue
        try:
            rows.append((day, ts_to_iso(ts), float(val)))
        except (TypeError, ValueError):
            continue
    return rows


EXTRACTORS = {
    "heart_rate":   lambda r: extract_pairs(r, "heart_rates",  "heartRate"),
    "stress":       extract_stress_rows,
    "spo2":         lambda r: extract_pairs(r, "spo2",         "spO2Reading"),
    "body_battery": extract_body_battery_rows,
    "respiration":  lambda r: extract_pairs(r, "respiration",  "respirationValue"),
}

METRIC_META = {
    "heart_rate":   {"label": "Heart Rate",   "unit": "bpm",   "color": "#E85D24"},
    "stress":       {"label": "Stress",        "unit": "level", "color": "#1D9E75"},
    "spo2":         {"label": "SpO2",          "unit": "%",     "color": "#185FA5"},
    "body_battery": {"label": "Body Battery",  "unit": "level", "color": "#BA7517"},
    "respiration":  {"label": "Respiration",   "unit": "brpm",  "color": "#7F77DD"},
}

# ══════════════════════════════════════════════════════════════════════════════
#  Load raw files
# ══════════════════════════════════════════════════════════════════════════════

def load_raw_files() -> list[dict]:
    d_from = date.fromisoformat(DATE_FROM)
    d_to   = date.fromisoformat(DATE_TO)
    raws   = []
    for f in sorted(RAW_DIR.glob("garmin_raw_*.json")):
        try:
            d = date.fromisoformat(f.stem.replace("garmin_raw_", ""))
        except ValueError:
            continue
        if d_from <= d <= d_to:
            with open(f, encoding="utf-8") as fp:
                raws.append(json.load(fp))
    return raws

# ══════════════════════════════════════════════════════════════════════════════
#  HTML generator
# ══════════════════════════════════════════════════════════════════════════════

def build_html(metric_data: dict) -> str:
    active_metrics = [m for m, enabled in METRICS.items() if enabled and metric_data.get(m)]

    # Build tab buttons
    tab_buttons = ""
    for i, m in enumerate(active_metrics):
        meta   = METRIC_META[m]
        active = "active" if i == 0 else ""
        tab_buttons += f'<button class="tab-btn {active}" onclick="showTab(\'{m}\')" id="btn-{m}">{meta["label"]}</button>\n'

    # Build chart divs + JS data
    chart_divs = ""
    js_data     = ""
    for i, m in enumerate(active_metrics):
        meta    = METRIC_META[m]
        rows    = metric_data[m]
        display = "block" if i == 0 else "none"
        chart_divs += f'<div id="chart-{m}" class="chart-container" style="display:{display}"><div id="plot-{m}" style="width:100%;height:500px"></div></div>\n'

        timestamps = [r[1] for r in rows]
        values     = [r[2] for r in rows]
        ts_json    = json.dumps(timestamps)
        val_json   = json.dumps(values)

        js_data += f"""
  Plotly.newPlot('plot-{m}', [{{
    x: {ts_json},
    y: {val_json},
    type: 'scatter',
    mode: 'lines',
    name: '{meta["label"]}',
    line: {{ color: '{meta["color"]}', width: 1.5 }},
    hovertemplate: '%{{x}}<br>{meta["label"]}: %{{y}} {meta["unit"]}<extra></extra>'
  }}], {{
    margin: {{ t: 40, r: 20, b: 60, l: 60 }},
    xaxis: {{
      title: 'Time',
      type: 'date',
      rangeslider: {{ visible: true }},
      rangeselector: {{
        buttons: [
          {{ count: 1,  label: '1d', step: 'day',  stepmode: 'backward' }},
          {{ count: 7,  label: '7d', step: 'day',  stepmode: 'backward' }},
          {{ count: 1,  label: '1m', step: 'month',stepmode: 'backward' }},
          {{ step: 'all', label: 'All' }}
        ]
      }}
    }},
    yaxis: {{ title: '{meta["label"]} ({meta["unit"]})' }},
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor:  'rgba(0,0,0,0)',
    font: {{ family: 'Arial, sans-serif', size: 12 }}
  }}, {{ responsive: true, displayModeBar: true }});
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Garmin Dashboard — {DATE_FROM} to {DATE_TO}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; background: #f5f5f5; color: #333; }}
  header {{ background: #1F3864; color: #fff; padding: 16px 24px; }}
  header h1 {{ font-size: 20px; font-weight: 600; }}
  header p  {{ font-size: 13px; opacity: 0.75; margin-top: 4px; }}
  .tabs {{ display: flex; gap: 4px; padding: 16px 24px 0; background: #fff; border-bottom: 1px solid #ddd; flex-wrap: wrap; }}
  .tab-btn {{
    padding: 8px 18px; border: none; border-radius: 6px 6px 0 0;
    background: #eee; cursor: pointer; font-size: 13px; font-family: Arial, sans-serif;
    border-bottom: 3px solid transparent; transition: background 0.15s;
  }}
  .tab-btn:hover  {{ background: #ddd; }}
  .tab-btn.active {{ background: #fff; border-bottom: 3px solid #1F3864; font-weight: 600; }}
  .chart-container {{ background: #fff; margin: 0; padding: 16px 24px 24px; }}
  footer {{ text-align: center; padding: 16px; font-size: 11px; color: #999; }}
</style>
</head>
<body>
<header>
  <h1>Garmin Health Dashboard</h1>
  <p>{DATE_FROM} &nbsp;→&nbsp; {DATE_TO} &nbsp;·&nbsp; Use the range selector or drag to zoom</p>
</header>
<div class="tabs">
{tab_buttons}</div>
{chart_divs}
<footer>Generated locally · No data sent externally · <a href="https://github.com/Wewoc/garmin-local-archive" style="color:#6ab0f5;text-decoration:none;">github.com/Wewoc/garmin-local-archive</a> · GNU GPL v3</footer>
<script>
function showTab(metric) {{
  document.querySelectorAll('.chart-container').forEach(d => d.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('chart-' + metric).style.display = 'block';
  document.getElementById('btn-'   + metric).classList.add('active');
}}
{js_data}
</script>
</body>
</html>"""
    return html

# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Garmin → Interactive HTML dashboard")
    print(f"  Source:  {RAW_DIR}")
    print(f"  Output:  {OUTPUT_FILE}")
    print(f"  Range:   {DATE_FROM} → {DATE_TO}")

    if not RAW_DIR.exists():
        print(f"  ERROR: folder not found: {RAW_DIR}")
        return

    raws = load_raw_files()
    if not raws:
        print("  No raw files found for the given date range.")
        return

    print(f"  {len(raws)} raw files loaded")

    metric_data = {}
    for metric, enabled in METRICS.items():
        if not enabled:
            continue
        rows = []
        for raw in raws:
            rows.extend(EXTRACTORS[metric](raw))
        metric_data[metric] = rows
        print(f"  ✓ {METRIC_META[metric]['label']:15s} {len(rows)} data points")

    html = build_html(metric_data)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"  ✓ Saved: {OUTPUT_FILE}")
    print(f"  → Open in browser: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
