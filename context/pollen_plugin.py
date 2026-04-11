#!/usr/bin/env python3
"""
pollen_plugin.py

Metadata-only plugin for Open-Meteo Air Quality pollen data.

This file contains NO executable logic — only metadata describing
how to fetch and store pollen data. All execution is handled by
context_api.py (fetching) and context_writer.py (writing).

Note on aggregation: Pollen data is only available as hourly values.
context_api.py aggregates to daily max (highest hourly reading per day)
because daily max is most relevant for correlation with health metrics
(HRV suppression, stress peaks on high pollen days).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))
import garmin_config as cfg

# ── Plugin identity ────────────────────────────────────────────────────────────

NAME        = "pollen"
DESCRIPTION = "Open-Meteo daily pollen data — birch, grass, alder, mugwort, olive, ragweed (daily max from hourly)"

# ── API ────────────────────────────────────────────────────────────────────────

API_URL_HISTORICAL = "https://air-quality-api.open-meteo.com/v1/air-quality"
API_URL_FORECAST   = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Pollen API uses same endpoint for historical and forecast
HISTORICAL_LAG_DAYS = 0

# Raw API resolution — context_api.py aggregates to daily max
API_RESOLUTION = "hourly"

# Fields to request from the API (Open-Meteo internal names)
API_FIELDS = [
    "birch_pollen",
    "grass_pollen",
    "alder_pollen",
    "mugwort_pollen",
    "olive_pollen",
    "ragweed_pollen",
]

# ── Storage ────────────────────────────────────────────────────────────────────

# Output directory — sole write target for this plugin
OUTPUT_DIR  = cfg.CONTEXT_POLLEN_DIR

# File naming: FILE_PREFIX + YYYY-MM-DD + .json
FILE_PREFIX = "pollen_"

# Source tag written into each output file
SOURCE_TAG  = "open-meteo-pollen"

# Aggregation applied before writing
AGGREGATION = "daily_max"

# ── Chunking ───────────────────────────────────────────────────────────────────

# Max days per API call — pollen API has tighter limits
CHUNK_DAYS = 30
