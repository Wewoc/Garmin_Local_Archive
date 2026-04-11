#!/usr/bin/env python3
"""
weather_plugin.py

Metadata-only plugin for Open-Meteo weather data.

This file contains NO executable logic — only metadata describing
how to fetch and store weather data. All execution is handled by
context_api.py (fetching) and context_writer.py (writing).

Adding a new context source = adding a new plugin file like this one.
No changes to context_api.py or context_writer.py required.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ── Plugin identity ────────────────────────────────────────────────────────────

NAME        = "weather"
DESCRIPTION = "Open-Meteo daily weather data (temperature, precipitation, wind, UV, sunshine)"

# ── API ────────────────────────────────────────────────────────────────────────

# Historical data endpoint (data older than ~5 days)
API_URL_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"

# Forecast endpoint (recent data)
API_URL_FORECAST   = "https://api.open-meteo.com/v1/forecast"

# Days before today where historical API ends and forecast API begins
HISTORICAL_LAG_DAYS = 5

# Resolution of the API response
API_RESOLUTION = "daily"

# Fields to request from the API (Open-Meteo internal names)
API_FIELDS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "uv_index_max",
    "sunshine_duration",
]

# ── Storage ────────────────────────────────────────────────────────────────────

# Output directory — sole write target for this plugin
OUTPUT_DIR  = cfg.CONTEXT_WEATHER_DIR

# File naming: FILE_PREFIX + YYYY-MM-DD + .json
FILE_PREFIX = "weather_"

# Source tag written into each output file
SOURCE_TAG  = "open-meteo-weather"

# ── Chunking ───────────────────────────────────────────────────────────────────

# Max days per API call
CHUNK_DAYS = 365
