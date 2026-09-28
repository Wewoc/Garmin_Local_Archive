#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
generate_demo_archive.py

Generates a fully fictional demo GLA archive — synthetic health data
(raw/, summary/) plus synthetic context data (weather, pollen) — so
someone can try the MCP server (clients/mcp_server.py) without a real
Garmin account or Garmin data of their own.

Nothing here is derived from real Garmin/Open-Meteo data and no network
calls are made. Health values are randomly generated per day (seeded,
reproducible). Context values (weather, pollen) are fixed averages for
the whole period, not fetched — deliberate, see ROADMAP/PROTOKOLL
discussion (no third-party calls for a demo-data generator).

Every written file carries a machine-readable "this is fictional" marker
(see _build_normalized_day()/_demo_plugin() below) plus a
DEMO_ARCHIVE_README.md at the archive root.

Scope, deliberately not covered here (see
changelog/anchor_delivery_demo-export-generator-pflichtabgleich.md):
  - Health raw/ files only populate the fields garmin_normalizer.
    summarize() actually reads — not a full replica of Garmin Connect's
    native API response shape (which has ~90 further undocumented
    fields with no accessible real-world reference to build against).
  - Weather has no raw/ (hourly) files, matching real GLA archives —
    Open-Meteo never delivers intraday weather data (see
    context/weather_plugin.py). Pollen raw/ has one flat value repeated
    for every hour, not real hourly variation.
  - quality_log.json / device_table.json are not populated.
  - The SQLite query cache is not pre-built — it builds itself on the
    MCP server's first start (see clients/mcp_server.py::main() ->
    _run_startup_sync()), so this script does not need to touch it.

Safety: this script ALWAYS writes to --out, overriding any
GARMIN_OUTPUT_DIR already present in the environment before importing
anything that reads it — it can never accidentally write into a real
archive.

Options:
  --out       Output directory (default: ./demo_archive).
  --days      Number of days to generate, ending yesterday (default: 180).
  --seed      Random seed for reproducible demo data (default: 42).
  --lat/--lon Placeholder coordinates written into context files
              (default: Berlin — a public, non-personal location).
  --no-zip    Skip building the .zip release asset.
  --dry-run   Show what would be generated without writing any files.
"""

import argparse
import os
import random
import shutil
import sys
import types
from datetime import date, timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# demo-export/ sits two levels below src/ (src/support-tools/demo-export/),
# garmin/ and context/ are siblings of support-tools/.
_SCRIPT_DIR = Path(__file__).parent
_SRC_ROOT   = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_SRC_ROOT / "garmin"))
sys.path.insert(0, str(_SRC_ROOT / "context"))


# ══════════════════════════════════════════════════════════════════════════════
#  Fictional-data marker for context plugins
# ══════════════════════════════════════════════════════════════════════════════

def _demo_plugin(plugin):
    """Wraps a real context plugin module in a stand-in with the same
    attributes context_writer.write() reads, except SOURCE_TAG gets a
    '-demo-fictional' suffix. Does not mutate the real plugin module —
    other code importing it in the same process keeps seeing the
    original SOURCE_TAG."""
    return types.SimpleNamespace(
        NAME=plugin.NAME,
        OUTPUT_DIR=plugin.OUTPUT_DIR,
        RAW_OUTPUT_DIR=getattr(plugin, "RAW_OUTPUT_DIR", None),
        FILE_PREFIX=plugin.FILE_PREFIX,
        SOURCE_TAG=f"{plugin.SOURCE_TAG}-demo-fictional",
        AGGREGATION=getattr(plugin, "AGGREGATION", None),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Synthetic health data — one normalized-shape dict per day
# ══════════════════════════════════════════════════════════════════════════════

_ACTIVITY_CHOICES = [
    ("Morning Run",       "running"),
    ("Easy Ride",         "cycling"),
    ("Strength Training", "strength_training"),
    ("Trail Run",         "trail_running"),
    ("Indoor Cycling",    "indoor_cycling"),
]

_TRAINING_STATUS_CHOICES = ["PRODUCTIVE", "MAINTAINING", "RECOVERY", "PEAKING", "UNPRODUCTIVE"]
_SLEEP_QUALIFIERS         = ["EXCELLENT", "GOOD", "FAIR", "POOR"]
_HRV_STATUS_CHOICES       = ["BALANCED", "UNBALANCED", "LOW"]


def _build_normalized_day(rng: random.Random, date_str: str) -> dict:
    """Builds a synthetic dict shaped like garmin_normalizer.normalize()'s
    output, populated only at the paths garmin_normalizer.summarize()
    actually reads (see garmin_normalizer.py:130-326) — not a full
    Garmin Connect API replica, see module docstring."""
    sleep_total_s = rng.randint(6 * 3600, int(8.5 * 3600))
    deep_s        = int(sleep_total_s * rng.uniform(0.12, 0.22))
    rem_s         = int(sleep_total_s * rng.uniform(0.15, 0.25))
    awake_s       = rng.randint(0, 1800)
    light_s       = max(sleep_total_s - deep_s - rem_s - awake_s, 0)
    sleep_score   = rng.randint(55, 95)

    resting_hr = rng.randint(48, 66)
    max_hr     = rng.randint(140, 185)
    min_hr     = rng.randint(42, 52)
    hr_values  = [[f"{date_str}T{h:02d}:00:00", rng.randint(min_hr, max_hr)] for h in range(0, 24, 2)]

    hrv_last_night = rng.randint(28, 75)
    hrv_weekly     = max(hrv_last_night + rng.randint(-8, 8), 0)

    body_battery_points = [
        {"value": v} for v in
        [rng.randint(70, 100), rng.randint(40, 90), rng.randint(20, 60), rng.randint(10, 45)]
    ]

    steps       = rng.randint(3500, 15000)
    distance_m  = steps * rng.uniform(0.70, 0.85)

    activities = []
    if rng.random() < 0.45:
        act_name, act_type = rng.choice(_ACTIVITY_CHOICES)
        duration_s = rng.randint(1200, 5400)
        is_distance_activity = "run" in act_type or "cycl" in act_type
        activities.append({
            "activityName":              act_name,
            "activityType":              {"typeKey": act_type},
            "duration":                  duration_s,
            "distance":                  duration_s * rng.uniform(2.2, 4.2) if is_distance_activity else None,
            "averageHR":                 rng.randint(110, 160),
            "maxHR":                     rng.randint(150, 185),
            "calories":                  rng.randint(200, 750),
            "aerobicTrainingEffect":     round(rng.uniform(1.5, 4.5), 1),
            "anaerobicTrainingEffect":   round(rng.uniform(0.5, 3.0), 1),
        })

    readiness_score = rng.randint(35, 92)
    readiness_level = "HIGH" if readiness_score >= 75 else "MODERATE" if readiness_score >= 50 else "LOW"
    readiness_feedback = (
        "You're ready for a solid training session today." if readiness_score >= 60
        else "Consider a lighter day — recovery is still catching up."
    )

    return {
        "date": date_str,
        # Machine-readable marker — see module docstring. Harmless extra
        # key: garmin_normalizer.summarize() only ever reads named paths
        # via safe_get(), unknown keys are silently ignored.
        "_fictional_demo_data": True,
        "sleep": {
            "dailySleepDTO": {
                "sleepTimeSeconds":       sleep_total_s,
                "deepSleepSeconds":       deep_s,
                "remSleepSeconds":        rem_s,
                "lightSleepSeconds":      light_s,
                "awakeSleepSeconds":      awake_s,
                "sleepScores":            {"overall": {"value": sleep_score,
                                                         "qualifierKey": rng.choice(_SLEEP_QUALIFIERS)}},
                "averageSpO2Value":       round(rng.uniform(93.0, 98.5), 1),
                "averageRespirationValue": round(rng.uniform(12.0, 16.5), 1),
                "sleepScoreFeedback":     "NEGATIVE_LONG_SLEEP" if sleep_score < 60 else "POSITIVE_DEEP_SLEEP",
            }
        },
        "hrv": {
            "hrvSummary": {
                "lastNightAvg":   hrv_last_night,
                "weeklyAvg":      hrv_weekly,
                "status":         rng.choice(_HRV_STATUS_CHOICES),
                "feedbackPhrase": "HRV_BALANCED_7",
            }
        },
        "heart_rates": {
            "restingHeartRate": resting_hr,
            "maxHeartRate":     max_hr,
            "minHeartRate":     min_hr,
            "heartRateValues":  hr_values,
        },
        "stress": {
            "averageStressLevel": rng.randint(15, 45),
            "maxStressLevel":     rng.randint(55, 90),
        },
        "body_battery": body_battery_points,
        "user_summary": {
            "totalSteps":                steps,
            "dailyStepGoal":             10000,
            "activeKilocalories":        round(rng.uniform(250, 900), 1),
            "totalKilocalories":         round(rng.uniform(1900, 2700), 1),
            "moderateIntensityMinutes":  rng.randint(5, 55),
            "vigorousIntensityMinutes":  rng.randint(0, 30),
            "floorsAscended":            float(rng.randint(1, 16)),
            "totalDistanceMeters":       round(distance_m, 1),
        },
        "get_calories_daily":     [{"resting": round(rng.uniform(1500, 1800), 1)}],
        "get_body_composition":   {"totalAverage": {"weight": round(rng.uniform(62000, 88000), 0)}},
        "get_hydration_data":     {"valueInML": rng.randint(400, 2600)},
        "get_blood_pressure": {
            "measurementSummaries": [{
                "highSystolic":     rng.randint(118, 138),
                "highDiastolic":    rng.randint(72, 90),
                "lowSystolic":      rng.randint(105, 118),
                "lowDiastolic":     rng.randint(65, 75),
                "numOfMeasurements": 1,
                "category":         "NORMAL",
                "measurements":     [],
            }]
        },
        "training_readiness": {
            "score":        readiness_score,
            "level":        readiness_level,
            "feedbackLong": readiness_feedback,
        },
        "training_status": {
            "latestTrainingStatus": rng.choice(_TRAINING_STATUS_CHOICES),
            "trainingLoadBalance":  {"sevenDayTrainingLoad": rng.randint(200, 650)},
        },
        "max_metrics":          {"vo2MaxPreciseValue": round(rng.uniform(36.0, 54.0), 1)},
        "get_endurance_score":  {"overallScore": rng.randint(25, 75)},
        "get_hill_score":       {"overallScore": rng.randint(200, 900)},
        "get_fitnessage_data":  {"fitnessAge": rng.randint(24, 48)},
        "activities":           activities,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Synthetic context data — fixed averages for the whole period, no API calls
# ══════════════════════════════════════════════════════════════════════════════

_WEATHER_AVERAGES = {
    "temperature_2m_max": 15.5,
    "temperature_2m_min": 7.0,
    "precipitation_sum":  1.8,
    "wind_speed_10m_max": 14.0,
    "uv_index_max":       3.2,
    "sunshine_duration":  18500.0,
}

_POLLEN_AVERAGES = {
    "birch_pollen":   8.0,
    "grass_pollen":   12.0,
    "alder_pollen":   4.0,
    "mugwort_pollen": 2.0,
    "olive_pollen":   0.5,
    "ragweed_pollen": 1.0,
}


def _write_context_data(date_strs, weather_plugin, pollen_plugin, context_writer, lat, lon):
    weather_data = {
        "summary": {d: dict(_WEATHER_AVERAGES) for d in date_strs},
        "raw":     {},  # weather has no raw/ — matches real archives, see module docstring
    }
    result = context_writer.write(_demo_plugin(weather_plugin), weather_data, lat, lon)
    print(f"  Weather context: {result['written']} written, {result['failed']} failed "
          f"(summary/ only, no raw/ — matches real GLA archives).")

    pollen_data = {
        "summary": {d: dict(_POLLEN_AVERAGES) for d in date_strs},
        "raw": {
            d: {field: [{"ts": f"{d}T{h:02d}:00:00", "value": value} for h in range(24)]
                for field, value in _POLLEN_AVERAGES.items()}
            for d in date_strs
        },
    }
    result = context_writer.write(_demo_plugin(pollen_plugin), pollen_data, lat, lon)
    print(f"  Pollen context: {result['written']} written, {result['failed']} failed "
          f"(summary/ + flat hourly raw/).")


# ══════════════════════════════════════════════════════════════════════════════
#  README
# ══════════════════════════════════════════════════════════════════════════════

def _write_readme(out_dir: Path, first_date: str, last_date: str, seed: int, days: int) -> None:
    (out_dir / "DEMO_ARCHIVE_README.md").write_text(
        f"""# Fictional Demo Archive — Garmin Local Archive (GLA)

Every file in this archive is **synthetic, fictional demo data** —
randomly generated (seed={seed}) so you can try the GLA MCP server
(clients/mcp_server.py) without a real Garmin account. It is not
derived from, and does not represent, any real person's health data.

Date range: {first_date} .. {last_date} ({days} days)
Location in context files: a placeholder (Berlin by default), not a
real user's location.

Every generated file carries a machine-readable marker:
- Health files (raw/, summary/): top-level key `"_fictional_demo_data": true`
- Context files (weather/, pollen/): `"source"` field ends in `-demo-fictional`

## Known limitations

- Health raw/ files only populate the fields the MCP server's query
  tools actually expose (via garmin_normalizer.summarize()) — not a
  full replica of Garmin Connect's native API response shape.
- Weather has no raw/ (hourly) files, matching real GLA archives —
  Open-Meteo never delivers intraday weather data. Pollen raw/ files
  repeat the same flat average value for every hour of the day, not
  real hourly variation.
- `quality_log.json` / `device_table.json` are not populated —
  archive-metadata queries for those two kinds return empty.

## Using it

1. Point `GARMIN_OUTPUT_DIR` at this folder (or wherever you extracted
   the .zip).
2. Start the MCP server — its SQLite query cache builds itself on the
   first start, nothing else to prepare.
""",
        encoding="utf-8",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a fictional demo GLA archive for trying the MCP server without a real Garmin account."
    )
    parser.add_argument("--out", default="demo_archive",
                         help="Output directory (default: ./demo_archive). Always overrides any "
                              "GARMIN_OUTPUT_DIR already set in your environment — never touches a real archive.")
    parser.add_argument("--days", type=int, default=180,
                         help="Number of days to generate, ending yesterday (default: 180).")
    parser.add_argument("--seed", type=int, default=42,
                         help="Random seed for reproducible demo data (default: 42).")
    parser.add_argument("--lat", type=float, default=52.5163,
                         help="Placeholder latitude written into context files (default: Berlin).")
    parser.add_argument("--lon", type=float, default=13.3777,
                         help="Placeholder longitude written into context files (default: Berlin).")
    parser.add_argument("--no-zip", action="store_true", help="Skip building the .zip release asset.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Show what would be generated without writing any files.")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    end     = date.today() - timedelta(days=1)
    start   = end - timedelta(days=args.days - 1)

    print(f"Demo archive output directory: {out_dir}")
    print("(GARMIN_OUTPUT_DIR is overridden for this process only — your real archive, if any, is never touched.)")

    if args.dry_run:
        print(f"[DRY RUN] Would generate {args.days} fictional days ({start} .. {end}) into {out_dir}, "
              f"zip: {not args.no_zip}")
        return

    # Redirect the archive path BEFORE importing anything that reads
    # GARMIN_OUTPUT_DIR at module import time (garmin_config and, through
    # it, every plugin below) — see module docstring "Safety".
    os.environ["GARMIN_OUTPUT_DIR"] = str(out_dir)

    import garmin_normalizer as gn   # noqa: E402
    import garmin_writer as writer   # noqa: E402
    import context_writer            # noqa: E402
    import weather_plugin            # noqa: E402
    import pollen_plugin             # noqa: E402

    rng        = random.Random(args.seed)
    dates      = [end - timedelta(days=i) for i in range(args.days)][::-1]
    date_strs  = [d.isoformat() for d in dates]

    print(f"Generating {len(date_strs)} fictional days: {date_strs[0]} .. {date_strs[-1]}")

    ok = 0
    for date_str in date_strs:
        normalized = _build_normalized_day(rng, date_str)
        summary    = gn.summarize(normalized)
        summary["_fictional_demo_data"] = True
        if writer.write_day(normalized, summary, date_str):
            ok += 1
    print(f"  Health data: {ok}/{len(date_strs)} days written.")

    _write_context_data(date_strs, weather_plugin, pollen_plugin, context_writer, args.lat, args.lon)

    _write_readme(out_dir, date_strs[0], date_strs[-1], args.seed, args.days)
    print(f"  Wrote {out_dir / 'DEMO_ARCHIVE_README.md'}")

    if not args.no_zip:
        archive_path = shutil.make_archive(str(out_dir), "zip", root_dir=str(out_dir.parent), base_dir=out_dir.name)
        print(f"Zipped demo archive: {archive_path}")

    print("Done.")


if __name__ == "__main__":
    main()
