#!/usr/bin/env python3
"""
reference_ranges.py

Shared reference range logic for specialist dashboards.
Provides age/sex/fitness-adjusted health metric thresholds.

Sources: AHA, ACSM, Garmin/Firstbeat HRV whitepapers, WHO SpO2 guidelines.

Rules:
- No file I/O, no imports beyond stdlib.
- Called by specialists in dashboards/ — never by plotters.
"""


def fitness_level(age: int, sex: str, vo2max: float) -> str:
    """Classify fitness level from age, sex, VO2max."""
    if sex == "male":
        if age < 30:
            return "superior" if vo2max >= 55 else "excellent" if vo2max >= 48 else "good" if vo2max >= 42 else "fair" if vo2max >= 36 else "poor"
        elif age < 40:
            return "superior" if vo2max >= 53 else "excellent" if vo2max >= 46 else "good" if vo2max >= 40 else "fair" if vo2max >= 34 else "poor"
        elif age < 50:
            return "superior" if vo2max >= 50 else "excellent" if vo2max >= 43 else "good" if vo2max >= 37 else "fair" if vo2max >= 31 else "poor"
        else:
            return "superior" if vo2max >= 46 else "excellent" if vo2max >= 39 else "good" if vo2max >= 33 else "fair" if vo2max >= 27 else "poor"
    else:
        if age < 30:
            return "superior" if vo2max >= 49 else "excellent" if vo2max >= 43 else "good" if vo2max >= 37 else "fair" if vo2max >= 31 else "poor"
        elif age < 40:
            return "superior" if vo2max >= 47 else "excellent" if vo2max >= 41 else "good" if vo2max >= 35 else "fair" if vo2max >= 29 else "poor"
        elif age < 50:
            return "superior" if vo2max >= 44 else "excellent" if vo2max >= 38 else "good" if vo2max >= 32 else "fair" if vo2max >= 26 else "poor"
        else:
            return "superior" if vo2max >= 41 else "excellent" if vo2max >= 35 else "good" if vo2max >= 29 else "fair" if vo2max >= 23 else "poor"


def reference_ranges(age: int, sex: str, fitness: str) -> dict:
    """
    Return age/sex/fitness-adjusted reference ranges per metric field.

    Returns:
        {field_key: (low, high), ...}
    """
    bonus = {"superior": 15, "excellent": 10, "good": 5, "average": 0, "fair": -5, "poor": -10}.get(fitness, 0)
    if age < 30:
        hrv = (50 + bonus, 100 + bonus)
    elif age < 40:
        hrv = (40 + bonus, 85 + bonus)
    elif age < 50:
        hrv = (32 + bonus, 72 + bonus)
    elif age < 60:
        hrv = (25 + bonus, 62 + bonus)
    else:
        hrv = (18 + bonus, 50 + bonus)
    if sex == "female":
        hrv = (hrv[0] - 3, hrv[1] - 3)

    if fitness in ("superior", "excellent"):
        hr = (40, 60)
    elif fitness == "good":
        hr = (50, 65)
    else:
        hr = (55, 75) if age < 50 else (58, 78)

    sleep = (7.0, 8.0) if age >= 65 else (7.0, 9.0)

    return {
        "hrv_last_night":     hrv,
        "resting_heart_rate": hr,
        "spo2_avg":           (95, 100),
        "sleep_duration":     sleep,
        "body_battery_max":   (50, 100),
        "stress_avg":         (0, 50),
    }