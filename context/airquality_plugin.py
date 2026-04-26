#!/usr/bin/env python3
"""
airquality_plugin.py

Metadata-only plugin for Open-Meteo air quality data.

This file contains NO executable logic — only metadata describing
how to fetch and store air quality data. All execution is handled by
context_api.py (fetching) and context_writer.py (writing).

Note on aggregation: Air quality data is available as hourly values.
context_api.py aggregates to daily mean because mean concentration over
24h is the standard reference for health impact assessment (WHO, EU AQI).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ── Plugin identity ────────────────────────────────────────────────────────────

NAME        = "airquality"
DESCRIPTION = "Open-Meteo daily air quality data — PM2.5, PM10, European AQI, NO2, Ozone (daily mean from hourly)"

# ── API ────────────────────────────────────────────────────────────────────────

API_URL_HISTORICAL = "https://air-quality-api.open-meteo.com/v1/air-quality"
API_URL_FORECAST   = "https://air-quality-api.open-meteo.com/v1/air-quality"

HISTORICAL_LAG_DAYS = 0

# Raw API resolution — context_api.py aggregates to daily mean
API_RESOLUTION = "hourly"

# Fields to request from the API (Open-Meteo internal names)
API_FIELDS = [
    "pm2_5",
    "pm10",
    "european_aqi",
    "nitrogen_dioxide",
    "ozone",
]

# Per-field aggregation — used by context_api._parse_hourly_to_daily
AGGREGATION_MAP = {
    "pm2_5":            "mean",
    "pm10":             "mean",
    "european_aqi":     "mean",
    "nitrogen_dioxide": "mean",
    "ozone":            "mean",
}

# ── Storage ────────────────────────────────────────────────────────────────────

OUTPUT_DIR  = cfg.CONTEXT_AIRQUALITY_DIR
FILE_PREFIX = "airquality_"
SOURCE_TAG  = "open-meteo-airquality"
AGGREGATION = "daily_mean"

# ── Chunking ───────────────────────────────────────────────────────────────────

CHUNK_DAYS = 30