#!/usr/bin/env python3
"""
context_api.py

Fetches external API data based on plugin metadata.

Reads plugin definitions (URL, fields, resolution, chunk size) and
executes the appropriate API calls against Open-Meteo endpoints.

Rules:
- Never writes files — that is context_writer.py's responsibility.
- Never knows what a dashboard looks like.
- Only called by context_collector.py.

Aggregation:
- daily plugins:  API response parsed directly to {date: {field: value}}
- hourly plugins: API response aggregated to daily max before returning
"""

import json
import logging
import time
import urllib.request
import urllib.parse
from datetime import date, timedelta

log = logging.getLogger(__name__)

_RETRY_COUNT   = 3    # attempts per chunk (1 = no retry)
_RETRY_BACKOFF = 1.0  # initial backoff in seconds — doubled on each retry

# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _date_range(date_from: str, date_to: str) -> list[str]:
    d   = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _select_url(plugin, date_from: str) -> str:
    """Select historical or forecast URL based on plugin lag days."""
    lag      = getattr(plugin, "HISTORICAL_LAG_DAYS", 0)
    cutoff   = (date.today() - timedelta(days=lag)).isoformat()
    return plugin.API_URL_FORECAST if date_from > cutoff else plugin.API_URL_HISTORICAL


def _fetch_chunk(url: str, date_from: str, date_to: str,
                 lat: float, lon: float, fields: list,
                 resolution: str) -> dict | None:
    """Execute one API call with retry. Returns parsed JSON or None on failure."""
    params = {
        resolution:   ",".join(fields),
        "latitude":   lat,
        "longitude":  lon,
        "start_date": date_from,
        "end_date":   date_to,
        "timezone":   "auto",
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    backoff  = _RETRY_BACKOFF

    for attempt in range(_RETRY_COUNT):
        try:
            log.debug(f"  context_api: GET {full_url}")
            with urllib.request.urlopen(full_url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt < _RETRY_COUNT - 1:
                log.warning(
                    f"  context_api: fetch failed {date_from}→{date_to} "
                    f"(attempt {attempt + 1}/{_RETRY_COUNT}) — retrying in {backoff:.0f}s: {exc}"
                )
                time.sleep(backoff)
                backoff *= 2
            else:
                log.warning(
                    f"  context_api: fetch failed {date_from}→{date_to} "
                    f"(attempt {attempt + 1}/{_RETRY_COUNT}) — giving up: {exc}"
                )
    return None


def _parse_daily(response: dict, fields: list) -> dict[str, dict]:
    """Parse daily API response to {date: {field: value}}."""
    daily = response.get("daily", {})
    times = daily.get("time", [])
    result = {}
    for i, ds in enumerate(times):
        result[ds] = {
            field: (daily.get(field, [])[i]
                    if i < len(daily.get(field, [])) else None)
            for field in fields
        }
    return result


def _parse_hourly_to_daily_max(response: dict, fields: list) -> dict[str, dict]:
    """Aggregate hourly API response to daily max per field."""
    hourly = response.get("hourly", {})
    times  = hourly.get("time", [])   # "YYYY-MM-DDTHH:MM"

    by_date: dict[str, dict[str, list]] = {}
    for i, ts in enumerate(times):
        ds = ts[:10]
        if ds not in by_date:
            by_date[ds] = {f: [] for f in fields}
        for field in fields:
            val = hourly.get(field, [])
            v   = val[i] if i < len(val) else None
            if v is not None:
                by_date[ds][field].append(v)

    return {
        ds: {field: (max(vals) if vals else None)
             for field, vals in field_data.items()}
        for ds, field_data in by_date.items()
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def fetch(plugin, date_from: str, date_to: str,
          lat: float, lon: float,
          skip_dates: set = None) -> dict[str, dict]:
    """
    Fetch data for a plugin over a date range.

    Args:
        plugin:      Plugin module (weather_plugin or pollen_plugin).
        date_from:   Start date ISO string, inclusive.
        date_to:     End date ISO string, inclusive.
        lat:         Latitude (WGS84).
        lon:         Longitude (WGS84).
        skip_dates:  Set of date strings already collected — skipped.

    Returns:
        {date_str: {field: value}} for all successfully fetched dates.
        Missing dates are not in the result — context_writer handles None.
    """
    skip_dates  = skip_dates or set()
    all_dates   = _date_range(date_from, date_to)
    missing     = [d for d in all_dates if d not in skip_dates]
    resolution  = plugin.API_RESOLUTION
    fields      = plugin.API_FIELDS
    chunk_size  = plugin.CHUNK_DAYS
    result      = {}

    for chunk in _chunks(missing, chunk_size):
        url      = _select_url(plugin, chunk[0])
        response = _fetch_chunk(url, chunk[0], chunk[-1],
                                lat, lon, fields, resolution)
        if response is None:
            continue

        if resolution == "daily":
            parsed = _parse_daily(response, fields)
        else:
            parsed = _parse_hourly_to_daily_max(response, fields)

        # Only keep dates that were actually requested — skip_dates stay out
        for ds, val in parsed.items():
            if ds not in skip_dates:
                result[ds] = val
        time.sleep(0.5)

    return result
