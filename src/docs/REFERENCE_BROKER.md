# Garmin Local Archive — Broker Layer Reference

Technical reference for the Broker Layer (`maps/`) — the routing interface
between dashboard specialists and all data sources (Garmin, external
context APIs, and future sources). For shared paths, constants, and project
structure see `REFERENCE_GLOBAL.md`.

---

## Scope

The Broker Layer is the single point of contact for anything that reads
archived data — dashboard specialists, the Custom Dashboard Builder, and
future consumers (Export Layer, MCP Server). It knows nothing about how any
source stores its data; that knowledge lives one level down, in the
per-source `*_map.py` modules.

**In scope:** routing, request/response contract, error behaviour.
**Not in scope:** per-field internal key mappings — these are documented in
the per-domain reference files (`REFERENCE_GARMIN.md`, `REFERENCE_CONTEXT.md`).
**Architecture principle:** see `GLA_HANDBUCH.md` → "Broker-Pattern" for the
underlying rule ("Spezialisten lesen nie direkt aus dem Dateisystem").

---

## Broker overview

| Broker | Domain | Routes to | Registered via |
|---|---|---|---|
| `field_map.py` | Garmin health data | `garmin_map` | `_SOURCES = {"garmin": garmin_map}` |
| `context_map.py` | External context data | `weather_map`, `pollen_map`, `brightsky_map`, `airquality_map` | `_SOURCES = {"weather": ..., "pollen": ..., "brightsky": ..., "airquality": ...}` |
| `fit_map.py` *(planned, v1.7)* | Activity data (Garmin FIT, later Strava) | `garmin_fit_map`, future `strava_fit_map` | see `ROADMAP.md` → v1.7 FIT Pipeline |
| `mcp_map.py` *(planned, v1.9)* | Aggregator for MCP Server queries | all of the above | see `ROADMAP.md` → v1.9 MCP Server |

Both `field_map.py` and `context_map.py` are structurally identical — same
broker principle, different domain and source registry. Both register their
sources via relative imports (`from . import <source>_map`) — this pattern
is invisible to naive static import scanners (confirmed against
`build_dep_map.py` output, 2026-07-05: both files showed zero imports).
Verify against the actual source file, not a dependency map, when in doubt.

---

## `field_map.get()` — Garmin data

```python
from maps.field_map import get as field_get

result = field_get(field, date_from, date_to, resolution="daily")
# result["garmin"] contains the broker return dict
```

`date_from` / `date_to`: ISO-8601 date strings (`YYYY-MM-DD`), inclusive on both ends.

`result["garmin"]` contract:

```python
{
    "values":            list,   # [{"date": str, "value": any}, ...]  — daily
                                 # [{"date": str, "series": list|None}, ...]  — intraday
    "fallback":          bool,   # True if requested resolution was unavailable, downgraded
    "source_resolution": str,    # actual resolution used: "daily" or "intraday"
}
```

`values` always contains exactly one entry per day in the requested range —
a day with no data is represented as `"value": None` (or `"series": None`
for intraday), never by omitting the day. An empty `values: []` is reserved
for one specific case: `date_from` after `date_to` silently produces an
empty range — no exception is raised, there is simply nothing to iterate
over.

Raises `KeyError` if field is not registered in `garmin_map._FIELD_MAP`.
Raises `ValueError` if resolution is not `"daily"` or `"intraday"`.

Field-level table (which generic field maps to which Garmin-internal key):
see `REFERENCE_GARMIN.md` → "Registered fields".

---

## `context_map.get()` — external context data

```python
from maps.context_map import get as context_get

result = context_get(field, date_from, date_to, resolution="daily")
# result is keyed by source name
```

`date_from` / `date_to`: ISO-8601 date strings (`YYYY-MM-DD`), inclusive on both ends.

`result[source_name]` contract — same structure as `field_map` broker return:

```python
{
    "values":            list,
    "fallback":          bool,
    "source_resolution": str,
    "error":             str,    # optional — only present if source failed
}
```

Three distinct cases produce different `values` states — do not conflate them:
- **Missing data for a day within a valid range:** the day still gets an
  entry in `values`, with `"value": None`. Days are never omitted.
- **`error` present:** the source raised an exception during read (e.g. a
  corrupt file). Only in this case is `values` an empty list `[]`.
- **`date_from` after `date_to`:** the underlying date-range helper yields
  no dates at all. `values` is `[]`, but silently — no `error` key, no
  exception.

Sources that do not know the requested field are silently skipped (`KeyError` caught internally).
Unknown field with no matching source → empty dict `{}`.

`weather_map.get()`, `pollen_map.get()`, `brightsky_map.get()`, and
`airquality_map.get()` follow the same contract as `garmin_map.get()` but
raise only `KeyError` (no `ValueError` — resolution is always treated as
daily, with `fallback=True` for intraday requests).

Field-level tables (generic field → internal key, per source): see
`REFERENCE_CONTEXT.md` → "Registered fields".

---

## `list_fields()` / `list_sources()`

Both brokers expose the same auxiliary functions:

| Function | `field_map` default | `context_map` default |
|---|---|---|
| `list_fields(source=...)` | `"garmin"` | `"weather"` |
| `list_sources()` | returns `["garmin"]` | returns `["weather", "pollen", "brightsky", "airquality"]` |

Unknown source name → `list_fields()` returns `[]` (no exception, no `KeyError`).

---

## Field index — all registered fields

Names only, no internal keys/units — for those see `REFERENCE_GARMIN.md`
(garmin) and `REFERENCE_CONTEXT.md` (weather/pollen/brightsky/airquality).
This list is a convenience lookup, not the source of truth — `list_fields()`
in the corresponding `*_map.py` module always reflects the current state.
Update this list whenever a field is added or removed (see `FINAL_DOKU_PROMPT`).

**Maintenance note:** the "Value" column below duplicates unit information
that also lives in `REFERENCE_GARMIN.md` and `REFERENCE_CONTEXT.md` — a
deliberate exception to this file's own "never duplicates, only points to"
rule, kept for quick readability. When a field's unit changes or a field is
added/removed, update both places. `list_fields()` in the corresponding
`*_map.py` module remains the actual source of truth for which fields exist.

**`field_map` → `garmin`** (19 fields)

| Field | Value | Description |
|---|---|---|
| `hrv_last_night` | ms | Heart rate variability, overnight average |
| `resting_heart_rate` | bpm | Resting heart rate for the day |
| `spo2_avg` | % | Average blood oxygen saturation, overnight |
| `sleep_duration` | hours | Total sleep duration |
| `body_battery_max` | 0–100 | Peak Body Battery energy level for the day |
| `stress_avg` | 0–100 | Average stress level for the day |
| `vo2max` | — | VO2max estimate — no fixed unit, device-calculated index |
| `sleep_score_feedback` | text | Categorical sleep feedback, e.g. `POSITIVE_DEEP` |
| `sleep_score_qualifier` | text | Categorical sleep quality label, e.g. `FAIR`, `EXCELLENT` |
| `sleep_deep_pct` | % | Share of deep sleep, calculated from raw seconds |
| `sleep_light_pct` | % | Share of light sleep, calculated from raw seconds |
| `sleep_rem_pct` | % | Share of REM sleep, calculated from raw seconds |
| `sleep_awake_pct` | % | Share of time awake during the sleep window |
| `heart_rate_series` | bpm per timestamp | Intraday heart rate readings |
| `stress_series` | 0–100 per timestamp | Intraday stress level readings |
| `spo2_series` | % per timestamp | Intraday blood oxygen readings, hourly averages |
| `body_battery_series` | 0–100 per timestamp | Intraday Body Battery readings |
| `respiration_series` | per timestamp | Intraday respiration readings — unit not fixed in source docs, see `REFERENCE_GARMIN.md` |
| `steps_series` | steps per 15-min bin | Intraday step counts in 15-minute bins |

**`context_map` → `weather`** (6 fields)

| Field | Value | Description |
|---|---|---|
| `temperature_max` | °C | Daily maximum temperature |
| `temperature_min` | °C | Daily minimum temperature |
| `precipitation` | mm | Daily precipitation sum |
| `wind_speed_max` | km/h | Daily maximum wind speed |
| `uv_index_max` | index | Daily maximum UV index |
| `sunshine_duration` | seconds | Daily sunshine duration |

**`context_map` → `pollen`** (6 fields)

| Field | Value | Description |
|---|---|---|
| `pollen_birch` | grains/m³ | Daily max birch pollen concentration |
| `pollen_grass` | grains/m³ | Daily max grass pollen concentration |
| `pollen_alder` | grains/m³ | Daily max alder pollen concentration |
| `pollen_mugwort` | grains/m³ | Daily max mugwort pollen concentration |
| `pollen_olive` | grains/m³ | Daily max olive pollen concentration |
| `pollen_ragweed` | grains/m³ | Daily max ragweed pollen concentration |

**`context_map` → `brightsky`** (9 fields)

| Field | Value | Description |
|---|---|---|
| `temperature_avg` | °C | Daily mean temperature (DWD) |
| `humidity_avg` | % | Daily mean relative humidity |
| `precipitation_sum` | mm | Daily precipitation sum |
| `sunshine_sum` | min | Daily sunshine duration |
| `wind_speed_max` | km/h | Daily maximum wind speed |
| `wind_gust_max` | km/h | Daily maximum wind gust speed |
| `cloud_cover_avg` | % | Daily mean cloud cover |
| `pressure_avg` | hPa | Daily mean sea-level pressure |
| `condition` | text | Daily dominant weather condition (mode of hourly values) |

**`context_map` → `airquality`** (5 fields)

| Field | Value | Description |
|---|---|---|
| `airquality_pm2_5` | μg/m³ | Daily mean fine particulate matter (PM2.5) |
| `airquality_pm10` | μg/m³ | Daily mean particulate matter (PM10) |
| `airquality_european_aqi` | index | Daily mean European Air Quality Index |
| `airquality_nitrogen_dioxide` | μg/m³ | Daily mean nitrogen dioxide concentration |
| `airquality_ozone` | μg/m³ | Daily mean ozone concentration |

**Naming collision, deliberate:** `weather` and `brightsky` both register a
field called `wind_speed_max` — same generic name, independently defined in
each `_FIELD_MAP`, different internal source keys (`wind_speed_10m_max` vs.
`wind_speed`). There is no `source` parameter to disambiguate at call
time — `context_map.get()` queries every registered source that recognizes
the field and returns all of them under separate source keys in the same
response dict. The consumer distinguishes between them only afterwards, by
reading the keys of the returned dict, not by choosing one in advance.

---

## Future brokers

`fit_map.py` (v1.7) is planned as a peer to `field_map.py` and
`context_map.py` — same broker principle (domain-level, routes to
source-specific `*_map.py` modules below it), new domain (activity data).

`mcp_map.py` (v1.9) is not a peer at this level. It aggregates across the
full Broker Layer (`field_map`, `fit_map`, `context_map`) rather than
routing to a source-specific module — architecturally it sits alongside
the Dashboard Layer and the planned Export Layer, both of which consume
the Broker Layer the same way, just through a different output channel
(MCP protocol instead of file/chart).

Full architecture in `ROADMAP.md`. This file gets a dedicated section for
each once implementation actually starts — no contract is assumed here
ahead of time.

---

*Source of truth for the Broker Layer's outward-facing contract. Per-field
internal mappings live in the per-domain reference files — this file never
duplicates them, only points to them.*
