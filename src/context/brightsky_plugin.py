#!/usr/bin/env python3
"""
brightsky_plugin.py

Metadata-only plugin for Brightsky DWD weather data.

Brightsky is a free, open API wrapper around Germany's national weather service
(Deutscher Wetterdienst / DWD). No API key required. Historical data available
from 2010-01-01 onwards.

This file contains NO executable logic — only metadata describing how to fetch
and store Brightsky data. All execution is handled by context_api.py (fetching)
and context_writer.py (writing).

Key difference from Open-Meteo plugins:
- FETCH_ADAPTER = "brightsky" → context_api.py uses a separate fetch/parse path
- AGGREGATION_MAP replaces the single AGGREGATION string — one method per field
  because Brightsky returns hourly data that must be aggregated field-specifically
  (mean for temperature, sum for precipitation, max for wind, mode for condition)
- Single API_URL — no historical/forecast split. Brightsky resolves this internally.

API endpoint: https://api.brightsky.dev/weather
Response: JSON with "weather" array of hourly entries.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ── Plugin identity ────────────────────────────────────────────────────────────

NAME        = "brightsky"
DESCRIPTION = (
    "Brightsky DWD hourly weather data aggregated to daily values "
    "(temperature, humidity, precipitation, sunshine, wind, cloud cover, "
    "pressure, condition). Germany only. Historical from 2010-01-01."
)

# ── Adapter ────────────────────────────────────────────────────────────────────

# Signals context_api.py to use the Brightsky-specific fetch + parse path
# instead of the Open-Meteo path.
FETCH_ADAPTER = "brightsky"

# ── API ────────────────────────────────────────────────────────────────────────

# Single endpoint — no historical/forecast split needed.
# Brightsky resolves data availability internally.
API_URL            = "https://api.brightsky.dev/weather"

# Required by context_api._select_url() — Brightsky uses one URL, so both
# attributes point to the same endpoint. HISTORICAL_LAG_DAYS = 0 means the
# single URL is always selected.
API_URL_HISTORICAL = API_URL
API_URL_FORECAST   = API_URL
HISTORICAL_LAG_DAYS = 0

# Raw resolution from the API — context_api.py will use _parse_brightsky()
# which handles the aggregation internally via AGGREGATION_MAP.
API_RESOLUTION = "hourly"

# Fields to extract from each hourly entry in the Brightsky "weather" array.
# These are the internal Brightsky field names.
API_FIELDS = [
    "temperature",
    "relative_humidity",
    "precipitation",
    "sunshine",
    "wind_speed",
    "wind_gust_speed",
    "cloud_cover",
    "pressure_msl",
    "condition",
]

# ── Aggregation ────────────────────────────────────────────────────────────────

# Field-specific aggregation — applied by context_api._parse_brightsky()
# when aggregating hourly entries to one daily value per field.
#
# mean  → arithmetic mean of all non-None hourly values
# sum   → sum of all non-None hourly values
# max   → maximum of all non-None hourly values
# mode  → most frequent non-None value (used for categorical "condition")
AGGREGATION_MAP = {
    "temperature":        "mean",   # °C      → daily average
    "relative_humidity":  "mean",   # %       → daily average
    "precipitation":      "sum",    # mm      → daily total
    "sunshine":           "sum",    # min     → daily total sunshine minutes
    "wind_speed":         "max",    # km/h    → daily maximum
    "wind_gust_speed":    "max",    # km/h    → daily maximum
    "cloud_cover":        "mean",   # %       → daily average
    "pressure_msl":       "mean",   # hPa     → daily average
    "condition":          "mode",   # string  → most frequent condition
}

# ── Storage ────────────────────────────────────────────────────────────────────

# Output directory — sole write target for this plugin
OUTPUT_DIR  = cfg.CONTEXT_BRIGHTSKY_DIR

# File naming: FILE_PREFIX + YYYY-MM-DD + .json
FILE_PREFIX = "brightsky_"

# Source tag written into each output file
SOURCE_TAG  = "brightsky-dwd"

# ── Chunking ───────────────────────────────────────────────────────────────────

# Conservative chunk size — Brightsky is stable with larger ranges but
# 30 days is consistent with pollen_plugin and avoids any timeout risk.
CHUNK_DAYS = 30
