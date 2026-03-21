#!/usr/bin/env python3
"""
garmin_analysis_html.py

Generates an interactive HTML analysis dashboard showing:
  - Daily metric values (line)
  - Personal 90-day rolling baseline (dashed line)
  - Age/sex/fitness-adjusted reference range (shaded band)

Metrics: HRV, Resting HR, SpO2, Sleep, Body Battery, Stress

Also exports a compact JSON summary for Ollama / Open WebUI.

Configuration via environment variables (all optional — hardcoded fallbacks below):
  GARMIN_OUTPUT_DIR       Root data folder (summary/ lives here)
  GARMIN_ANALYSIS_HTML    Full path for the output .html file
  GARMIN_ANALYSIS_JSON    Full path for the output .json file
  GARMIN_DATE_FROM        Start date (YYYY-MM-DD)
  GARMIN_DATE_TO          End date (YYYY-MM-DD)
  GARMIN_PROFILE_AGE      Age in years (integer)
  GARMIN_PROFILE_SEX      "male" or "female"
"""

import json
import os
import statistics
from datetime import date, timedelta
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — edit fallback values here, or set environment variables.
#  Environment variables always take priority over the values below.
# ══════════════════════════════════════════════════════════════════════════════

_BASE = Path(os.environ.get("GARMIN_OUTPUT_DIR", "~/garmin_data")).expanduser()

SUMMARY_DIR = _BASE / "summary"
OUTPUT_HTML = Path(os.environ.get("GARMIN_ANALYSIS_HTML",
                   str(_BASE / "garmin_analysis.html")))
OUTPUT_JSON = Path(os.environ.get("GARMIN_ANALYSIS_JSON",
                   str(_BASE / "garmin_analysis.json")))

# Date range to display — format: "YYYY-MM-DD"
DATE_FROM = os.environ.get("GARMIN_DATE_FROM", "2026-01-01")
DATE_TO   = os.environ.get("GARMIN_DATE_TO",   "2026-03-17")

# Personal profile
PROFILE = {
    "age": int(os.environ.get("GARMIN_PROFILE_AGE", "35")),
    "sex": os.environ.get("GARMIN_PROFILE_SEX", "male"),
    # fitness_level is auto-detected from VO2max — no need to set manually
}

# ══════════════════════════════════════════════════════════════════════════════

# Baseline window — rolling average over last N days
BASELINE_DAYS = 90

# ══════════════════════════════════════════════════════════════════════════════
#  Reference ranges
#  Sources: AHA, ACSM, Garmin/Firstbeat HRV whitepapers, WHO SpO2 guidelines
#  Ranges are (low, high) — values outside are flagged
#  Adjusted by age group and sex where evidence supports it
# ══════════════════════════════════════════════════════════════════════════════

def get_reference_ranges(age: int, sex: str, vo2max: float | None) -> dict:
    """Returns age/sex/fitness adjusted reference ranges per metric."""

    # Fitness level from VO2max (Garmin/ACSM classification)
    fitness = "average"
    if vo2max is not None:
        if sex == "male":
            if age < 30:
                fitness = "superior" if vo2max >= 55 else "excellent" if vo2max >= 48 else "good" if vo2max >= 42 else "fair" if vo2max >= 36 else "poor"
            elif age < 40:
                fitness = "superior" if vo2max >= 53 else "excellent" if vo2max >= 46 else "good" if vo2max >= 40 else "fair" if vo2max >= 34 else "poor"
            elif age < 50:
                fitness = "superior" if vo2max >= 50 else "excellent" if vo2max >= 43 else "good" if vo2max >= 37 else "fair" if vo2max >= 31 else "poor"
            else:
                fitness = "superior" if vo2max >= 46 else "excellent" if vo2max >= 39 else "good" if vo2max >= 33 else "fair" if vo2max >= 27 else "poor"
        else:
            if age < 30:
                fitness = "superior" if vo2max >= 49 else "excellent" if vo2max >= 43 else "good" if vo2max >= 37 else "fair" if vo2max >= 31 else "poor"
            elif age < 40:
                fitness = "superior" if vo2max >= 47 else "excellent" if vo2max >= 41 else "good" if vo2max >= 35 else "fair" if vo2max >= 29 else "poor"
            elif age < 50:
                fitness = "superior" if vo2max >= 44 else "excellent" if vo2max >= 38 else "good" if vo2max >= 32 else "fair" if vo2max >= 26 else "poor"
            else:
                fitness = "superior" if vo2max >= 41 else "excellent" if vo2max >= 35 else "good" if vo2max >= 29 else "fair" if vo2max >= 23 else "poor"

    # HRV (ms) — higher = better, varies significantly by age and fitness
    # Source: Shaffer & Ginsberg 2017, Garmin HRV whitepaper
    hrv_fit_bonus = {"superior": 15, "excellent": 10, "good": 5, "average": 0, "fair": -5, "poor": -10}
    bonus = hrv_fit_bonus.get(fitness, 0)
    if age < 30:
        hrv_range = (50 + bonus, 100 + bonus)
    elif age < 40:
        hrv_range = (40 + bonus, 85 + bonus)
    elif age < 50:
        hrv_range = (32 + bonus, 72 + bonus)
    elif age < 60:
        hrv_range = (25 + bonus, 62 + bonus)
    else:
        hrv_range = (18 + bonus, 50 + bonus)
    if sex == "female":
        hrv_range = (hrv_range[0] - 3, hrv_range[1] - 3)

    # Resting HR (bpm) — lower = better for fit individuals
    # Source: AHA guidelines
    if fitness in ("superior", "excellent"):
        hr_range = (40, 60)
    elif fitness == "good":
        hr_range = (50, 65)
    else:
        hr_range = (55, 75) if age < 50 else (58, 78)

    # SpO2 (%) — tight range, not strongly age dependent
    # Source: WHO, AHA
    spo2_range = (95, 100)

    # Sleep (h) — age dependent
    # Source: National Sleep Foundation 2023
    if age < 26:
        sleep_range = (7.0, 9.0)
    elif age < 65:
        sleep_range = (7.0, 9.0)
    else:
        sleep_range = (7.0, 8.0)

    # Body Battery — Garmin proprietary, no external norms
    # Using general Garmin guidance: >75 well-rested, <25 exhausted
    bb_range = (50, 100)

    # Stress — Garmin scale 0-100, <25 = rest, 26-50 = low, 51-75 = medium, >75 = high
    stress_range = (0, 50)

    return {
        "hrv":          {"range": hrv_range,   "unit": "ms",    "higher_better": True,  "fitness_level": fitness},
        "resting_hr":   {"range": hr_range,    "unit": "bpm",   "higher_better": False, "fitness_level": fitness},
        "spo2":         {"range": spo2_range,  "unit": "%",     "higher_better": True,  "fitness_level": None},
        "sleep":        {"range": sleep_range, "unit": "h",     "higher_better": None,  "fitness_level": None},
        "body_battery": {"range": bb_range,    "unit": "level", "higher_better": True,  "fitness_level": None},
        "stress":       {"range": stress_range,"unit": "level", "higher_better": False, "fitness_level": None},
    }

# ══════════════════════════════════════════════════════════════════════════════
#  Data loading
# ══════════════════════════════════════════════════════════════════════════════

def load_summaries(date_from: date, date_to: date, extra_days: int = 0) -> list[dict]:
    """Load summary JSONs. extra_days extends the window back for baseline calculation."""
    start = date_from - timedelta(days=extra_days)
    rows  = []
    for f in sorted(SUMMARY_DIR.glob("garmin_*.json")):
        try:
            d = date.fromisoformat(f.stem.replace("garmin_", ""))
        except ValueError:
            continue
        if start <= d <= date_to:
            with open(f, encoding="utf-8") as fp:
                rows.append(json.load(fp))
    return rows


def extract_metric(summaries: list[dict], key: str) -> dict[str, float | None]:
    """Returns {date_str: value} for a given dotted key like 'sleep.hrv_last_night_ms'."""
    section, field = key.split(".", 1)
    return {
        s["date"]: (s.get(section) or {}).get(field)
        for s in summaries
        if s.get("date")
    }


def rolling_avg(values: dict[str, float | None], d: date, window: int) -> float | None:
    """Rolling average of the window days ending on d (exclusive)."""
    nums = []
    for i in range(1, window + 1):
        v = values.get((d - timedelta(days=i)).isoformat())
        if v is not None:
            nums.append(v)
    return round(statistics.mean(nums), 2) if nums else None


# ══════════════════════════════════════════════════════════════════════════════
#  Analysis
# ══════════════════════════════════════════════════════════════════════════════

METRIC_KEYS = {
    "hrv":          "sleep.hrv_last_night_ms",
    "resting_hr":   "heartrate.resting_bpm",
    "spo2":         "sleep.spo2_avg",
    "sleep":        "sleep.duration_h",
    "body_battery": "stress.body_battery_max",
    "stress":       "stress.stress_avg",
}

METRIC_META = {
    "hrv":          {"label": "HRV",          "color": "#7F77DD"},
    "resting_hr":   {"label": "Resting HR",   "color": "#E85D24"},
    "spo2":         {"label": "SpO2",         "color": "#185FA5"},
    "sleep":        {"label": "Sleep",        "color": "#1D9E75"},
    "body_battery": {"label": "Body Battery", "color": "#BA7517"},
    "stress":       {"label": "Stress",       "color": "#D4537E"},
}


def analyse(summaries: list[dict], d_from: date, d_to: date, refs: dict) -> dict:
    """Build per-metric daily analysis for the display window."""
    all_values = {m: extract_metric(summaries, k) for m, k in METRIC_KEYS.items()}
    display_dates = [
        (d_from + timedelta(days=i)).isoformat()
        for i in range((d_to - d_from).days + 1)
    ]

    result = {}
    for metric, values in all_values.items():
        ref  = refs[metric]
        days = []
        for ds in display_dates:
            val      = values.get(ds)
            baseline = rolling_avg(values, date.fromisoformat(ds), BASELINE_DAYS)
            low, high = ref["range"]
            status = None
            if val is not None:
                if ref["higher_better"] is True:
                    status = "low" if val < low else "ok"
                elif ref["higher_better"] is False:
                    status = "high" if val > high else "ok"
                else:
                    status = "low" if val < low else "high" if val > high else "ok"
            days.append({
                "date":     ds,
                "value":    val,
                "baseline": baseline,
                "status":   status,
            })
        result[metric] = {
            "days":      days,
            "ref_low":   low,
            "ref_high":  high,
            "unit":      ref["unit"],
            "fitness":   ref["fitness_level"],
            "higher_better": ref["higher_better"],
        }
    return result


def build_ollama_summary(analysis: dict, refs: dict, vo2max: float | None) -> dict:
    """Compact JSON suitable as Ollama context."""
    fitness = refs["hrv"]["fitness_level"]
    summary = {
        "generated": date.today().isoformat(),
        "period":    f"{DATE_FROM} to {DATE_TO}",
        "profile":   {**PROFILE, "fitness_level": fitness, "vo2max": vo2max},
        "metrics":   {},
    }
    for metric, data in analysis.items():
        vals     = [d["value"] for d in data["days"] if d["value"] is not None]
        baselines= [d["baseline"] for d in data["days"] if d["baseline"] is not None]
        flags    = [d for d in data["days"] if d["status"] in ("low", "high")]
        summary["metrics"][metric] = {
            "unit":          data["unit"],
            "period_avg":    round(statistics.mean(vals), 2) if vals else None,
            "baseline_avg":  round(statistics.mean(baselines), 2) if baselines else None,
            "ref_range":     [data["ref_low"], data["ref_high"]],
            "flagged_days":  len(flags),
            "flagged_dates": [f["date"] for f in flags[-5:]],  # last 5 only
        }
    return summary


# ══════════════════════════════════════════════════════════════════════════════
#  HTML generator
# ══════════════════════════════════════════════════════════════════════════════

def build_html(analysis: dict, refs: dict, vo2max: float | None) -> str:
    fitness   = refs["hrv"]["fitness_level"]
    tab_btns  = ""
    chart_divs= ""
    js_plots  = ""

    metrics = list(analysis.keys())
    for i, metric in enumerate(metrics):
        meta    = METRIC_META[metric]
        data    = analysis[metric]
        active  = "active" if i == 0 else ""
        display = "block"  if i == 0 else "none"

        tab_btns   += f'<button class="tab-btn {active}" onclick="showTab(\'{metric}\')" id="btn-{metric}">{meta["label"]}</button>\n'
        chart_divs += f'<div id="chart-{metric}" class="chart-container" style="display:{display}"><div id="plot-{metric}" style="width:100%;height:480px"></div></div>\n'

        dates     = [d["date"]     for d in data["days"]]
        values    = [d["value"]    for d in data["days"]]
        baselines = [d["baseline"] for d in data["days"]]
        ref_low   = data["ref_low"]
        ref_high  = data["ref_high"]
        unit      = data["unit"]
        color     = meta["color"]
        label     = meta["label"]

        # Reference band (filled area between low and high)
        ref_band_y_upper = [ref_high] * len(dates)
        ref_band_y_lower = [ref_low]  * len(dates)

        js_plots += f"""
  Plotly.newPlot('plot-{metric}', [
    {{
      x: {json.dumps(dates)}, y: {json.dumps(ref_band_y_upper)},
      type: 'scatter', mode: 'lines', name: 'Norm high',
      line: {{width: 0}}, showlegend: false, hoverinfo: 'skip'
    }},
    {{
      x: {json.dumps(dates)}, y: {json.dumps(ref_band_y_lower)},
      type: 'scatter', mode: 'lines', name: 'Reference range',
      fill: 'tonexty', fillcolor: 'rgba(100,180,100,0.12)',
      line: {{width: 0}}, hoverinfo: 'skip'
    }},
    {{
      x: {json.dumps(dates)}, y: {json.dumps(baselines)},
      type: 'scatter', mode: 'lines', name: '90d baseline',
      line: {{color: '{color}', width: 1.5, dash: 'dash'}},
      hovertemplate: '%{{x}}<br>90d avg: %{{y:.1f}} {unit}<extra></extra>'
    }},
    {{
      x: {json.dumps(dates)}, y: {json.dumps(values)},
      type: 'scatter', mode: 'lines+markers', name: '{label}',
      line: {{color: '{color}', width: 2}},
      marker: {{size: 5, color: '{color}'}},
      hovertemplate: '%{{x}}<br>{label}: %{{y:.1f}} {unit}<extra></extra>'
    }}
  ], {{
    margin: {{t: 40, r: 20, b: 60, l: 60}},
    xaxis: {{
      title: 'Date', type: 'date',
      rangeslider: {{visible: true}},
      rangeselector: {{buttons: [
        {{count:7, label:'7d', step:'day', stepmode:'backward'}},
        {{count:1, label:'1m', step:'month', stepmode:'backward'}},
        {{step:'all', label:'All'}}
      ]}}
    }},
    yaxis: {{title: '{label} ({unit})'}},
    legend: {{orientation: 'h', y: -0.25}},
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor:  'rgba(0,0,0,0)',
    font: {{family: 'Arial, sans-serif', size: 12}}
  }}, {{responsive: true}});
"""

    vo2_str = f"{vo2max:.1f}" if vo2max else "n/a"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Garmin Analysis — {DATE_FROM} to {DATE_TO}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  * {{box-sizing:border-box;margin:0;padding:0}}
  body {{font-family:Arial,sans-serif;background:#f5f5f5;color:#333}}
  header {{background:#1F3864;color:#fff;padding:16px 24px}}
  header h1 {{font-size:20px;font-weight:600}}
  header p  {{font-size:13px;opacity:0.75;margin-top:4px}}
  .profile-bar {{background:#fff;border-bottom:1px solid #eee;padding:10px 24px;font-size:12px;color:#666;display:flex;gap:24px;flex-wrap:wrap}}
  .profile-bar span b {{color:#333}}
  .legend-bar {{background:#fff;padding:8px 24px;font-size:11px;color:#888;display:flex;gap:20px;align-items:center;border-bottom:1px solid #eee}}
  .leg {{display:flex;align-items:center;gap:6px}}
  .leg-line {{width:24px;height:2px}}
  .leg-band {{width:24px;height:10px;background:rgba(100,180,100,0.25);border:1px solid rgba(100,180,100,0.4)}}
  .tabs {{display:flex;gap:4px;padding:16px 24px 0;background:#fff;border-bottom:1px solid #ddd;flex-wrap:wrap}}
  .tab-btn {{padding:8px 18px;border:none;border-radius:6px 6px 0 0;background:#eee;cursor:pointer;font-size:13px;font-family:Arial,sans-serif;border-bottom:3px solid transparent;transition:background .15s}}
  .tab-btn:hover {{background:#ddd}}
  .tab-btn.active {{background:#fff;border-bottom:3px solid #1F3864;font-weight:600}}
  .chart-container {{background:#fff;padding:16px 24px 24px}}
  .disclaimer {{font-size:11px;color:#aaa;padding:8px 24px;background:#fff;border-top:1px solid #eee}}
  .disclaimer-banner {{font-size:12px;color:#7a5c00;background:#fff8e1;border:1px solid #ffe082;border-radius:6px;padding:10px 20px;margin:12px 24px;}}
  footer {{text-align:center;padding:12px;font-size:11px;color:#999}}
</style>
</head>
<body>
<header>
  <h1>Garmin Health Analysis</h1>
  <p>{DATE_FROM} &nbsp;→&nbsp; {DATE_TO} &nbsp;·&nbsp; 90-day rolling baseline &nbsp;·&nbsp; Age/fitness-adjusted reference ranges</p>
</header>
<div class="disclaimer-banner">⚠️ <b>Informational only — not medical advice.</b> Reference ranges are general health guidelines based on published research (AHA, ACSM, Garmin/Firstbeat). Individual variation is normal. Consult a healthcare professional for medical decisions.</div>
<div class="profile-bar">
  <span>Age: <b>{PROFILE["age"]}</b></span>
  <span>Sex: <b>{PROFILE["sex"]}</b></span>
  <span>VO2max: <b>{vo2_str}</b></span>
  <span>Fitness level: <b>{fitness}</b></span>
</div>
<div class="legend-bar">
  <div class="leg"><div class="leg-line" style="background:#555"></div> Daily value</div>
  <div class="leg"><div class="leg-line" style="background:#555;border-top:2px dashed #555;height:0"></div> 90d personal baseline</div>
  <div class="leg"><div class="leg-band"></div> Reference range (age/fitness)</div>
</div>
<div class="tabs">
{tab_btns}</div>
{chart_divs}
<div class="disclaimer">Reference ranges are general health guidelines based on published research (AHA, ACSM, Garmin/Firstbeat). They are not medical advice. Individual variation is normal.</div>
<footer>Generated locally · No data sent externally · <a href="https://github.com/Wewoc/Garmin_Local_Archive" style="color:#6ab0f5;text-decoration:none;">github.com/Wewoc/Garmin_Local_Archive</a> · GNU GPL v3</footer>
<script>
function showTab(m) {{
  document.querySelectorAll('.chart-container').forEach(d => d.style.display='none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('chart-'+m).style.display='block';
  document.getElementById('btn-'+m).classList.add('active');
}}
{js_plots}
</script>
</body>
</html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Garmin → Analysis dashboard")
    print(f"  Source:  {SUMMARY_DIR}")
    print(f"  HTML:    {OUTPUT_HTML}")
    print(f"  JSON:    {OUTPUT_JSON}")
    print(f"  Range:   {DATE_FROM} → {DATE_TO}")

    if not SUMMARY_DIR.exists():
        print(f"  ERROR: folder not found: {SUMMARY_DIR}")
        return

    d_from = date.fromisoformat(DATE_FROM)
    d_to   = date.fromisoformat(DATE_TO)

    # Load enough history for baseline calculation
    summaries = load_summaries(d_from, d_to, extra_days=BASELINE_DAYS + 30)
    if not summaries:
        print("  No summary files found.")
        return
    print(f"  {len(summaries)} summary files loaded")

    # Auto-detect VO2max from most recent non-null value
    vo2max = None
    for s in reversed(summaries):
        v = (s.get("training") or {}).get("vo2max")
        if v is not None:
            vo2max = v
            break
    if vo2max:
        print(f"  VO2max detected: {vo2max}")

    refs     = get_reference_ranges(PROFILE["age"], PROFILE["sex"], vo2max)
    analysis = analyse(summaries, d_from, d_to, refs)

    # HTML
    html = build_html(analysis, refs, vo2max)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"  ✓ HTML saved: {OUTPUT_HTML}")

    # JSON for Ollama
    ollama_data = build_ollama_summary(analysis, refs, vo2max)
    OUTPUT_JSON.write_text(
        json.dumps(ollama_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"  ✓ JSON saved: {OUTPUT_JSON}")

    # Quick flags summary
    print("\n  Flagged metrics:")
    for metric, data in analysis.items():
        flags = [d for d in data["days"] if d["status"] in ("low", "high")]
        if flags:
            print(f"    {METRIC_META[metric]['label']:15s} {len(flags)} days flagged")
        else:
            print(f"    {METRIC_META[metric]['label']:15s} all within range")


if __name__ == "__main__":
    main()
