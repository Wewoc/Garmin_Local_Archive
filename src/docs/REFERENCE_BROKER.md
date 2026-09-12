# Garmin Local Archive — Broker Layer Reference

Technical reference for the Broker Layer (`maps/`) — the routing interface
between dashboard specialists and all data sources (Garmin, external
context APIs, and future sources). For shared paths, constants, and project
structure see `REFERENCE_GLOBAL.md`. For the MCP Server layer built on
top of this broker (`clients/mcp_server.py`, `maps/mcp_map.py`), see
`REFERENCE_MCP.md` — split out 2026-09-11 once that section grew past
half this file's length.

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
| `health_map.py` | Garmin health data | `garmin_health_map` | `_SOURCES = {"garmin": garmin_health_map}` |
| `context_map.py` | External context data | `weather_map`, `pollen_map`, `brightsky_map`, `airquality_map` | `_SOURCES = {"weather": ..., "pollen": ..., "brightsky": ..., "airquality": ...}` |
| `gateway_map.py` | Cross-domain routing for external/aggregate consumers | `health_map`, `fit_map` *(planned)*, `context_map` | `_DOMAIN_BROKERS = {"health": health_map, "fit": None, "context": context_map}` |
| `metadata_map.py` *(v1.6.9.1)* | Archive-state introspection (not time-series) | — reads archive files directly, catch-all for data outside health/fit/context | routed via `gateway_map.get_metadata()`, not `_DOMAIN_BROKERS` — see below |
| `fit_map.py` *(planned, v1.8)* | Activity data (Garmin FIT, later Strava) | `garmin_fit_map`, future `strava_fit_map` | see `ROADMAP.md` → v1.8 FIT Pipeline |
| `mcp_map.py` *(v1.7)* | MCP protocol translation | `gateway_map` | pure delegation, no `_SOURCES`/`_DOMAIN_BROKERS` registry of its own — see `REFERENCE_MCP.md` for the full contract |

Both `health_map.py` and `context_map.py` are structurally identical — same
broker principle, different domain and source registry. Both register their
sources via relative imports (`from . import <source>_map`) — this pattern
is invisible to naive static import scanners (confirmed against
`build_dep_map.py` output, 2026-07-05: both files showed zero imports).
Verify against the actual source file, not a dependency map, when in doubt.

---

## `health_map.get()` — Garmin data

```python
from maps.health_map import get as health_get

result = health_get(field, date_from, date_to, resolution="daily")
# result["garmin"] contains the broker return dict
```

`date_from` / `date_to`: ISO-8601 date strings (`YYYY-MM-DD`), inclusive on both ends.

`result["garmin"]` contract:

```python
{
    "values":            list,   # [{"date": str, "value": any}, ...]  — daily
                                 # [{"date": str, "series": list|None,
                                 #   "dst_transition": bool}, ...]  — intraday/live
    "fallback":          bool,   # True if requested resolution was unavailable, downgraded
    "source_resolution": str,    # actual resolution used: "daily", "intraday", or "live"
}
```

`values` always contains exactly one entry per day in the requested range —
a day with no data is represented as `"value": None` (or `"series": None`
for intraday), never by omitting the day. An empty `values: []` is reserved
for one specific case: `date_from` after `date_to` silently produces an
empty range — no exception is raised, there is simply nothing to iterate
over.

Raises `KeyError` if field is not registered in `garmin_health_map._FIELD_MAP`.
Raises `ValueError` if resolution is not `"daily"`, `"intraday"`, or `"live"`.

`resolution="live"` (v1.6.5, `garmin` source only) is a single always-current
snapshot — `date_from`/`date_to` are ignored, and unlike `"daily"`/`"intraday"`
(which fall back to each other) it never falls back on a miss. Not every
field has a live route — fields without one return `fallback=True`, empty
`values`. Which fields support it and how: see `REFERENCE_GARMIN.md` →
"Live route".

Field-level table (which generic field maps to which Garmin-internal key):
see `REFERENCE_GARMIN.md` → "Registered fields".

---

## `health_map.get_raw()` — raw passthrough (v1.6.8 Session 4)

```python
from maps.health_map import get_raw as health_get_raw, list_raw_fields as health_list_raw_fields

result = health_get_raw(field, date_from, date_to, source="garmin")
# result == {"values": [{"date": str, "raw": any|None}, ...], "source_resolution": "raw"}
```

Separate from `get()`/`list_fields()` by design — see `REFERENCE_GARMIN.md`
→ "Raw-passthrough fields" for the rationale. Returns the archived `raw/`
payload for a Capability-Scan endpoint **unprocessed** — no `"value"`
extraction, the caller interprets the structure itself. `source` defaults
to `"garmin"`, the only source currently registered for raw-passthrough.

`list_raw_fields(source="garmin")` returns the registered raw-field names
for a source — `[]` for sources without raw-passthrough support.

Raises `KeyError` if `field` is not registered, or if `source` has no
raw-passthrough support at all.

---

## `context_map.get()` — external context data

```python
from maps.context_map import get as context_get

result = context_get(field, date_from, date_to, resolution="daily")
# result is keyed by source name
```

`date_from` / `date_to`: ISO-8601 date strings (`YYYY-MM-DD`), inclusive on both ends.

`result[source_name]` contract — same structure as `health_map` broker return:

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
`airquality_map.get()` follow the same contract as `garmin_health_map.get()` but
raise only `KeyError` (no `ValueError` — resolution is always treated as
daily, with `fallback=True` for intraday requests).

Field-level tables (generic field → internal key, per source): see
`REFERENCE_CONTEXT.md` → "Registered fields".

---

## `gateway_map.get()` — cross-domain routing

```python
from maps.gateway_map import get as gateway_get

result = gateway_get(field, date_from, date_to, resolution="daily", domain=None)
```

Local API boundary (in-process, not a network endpoint) for consumers that
do not know in advance which domain broker owns a field — e.g. `mcp_map`
(v1.9). Not a replacement for direct domain-broker imports: named
specialists with a fixed domain need continue to import `health_map`/
`fit_map`/`context_map` directly (v1.6.7 scope decision).

`domain`: `None` (default) → queries all three domain keys (`"health"`,
`"fit"`, `"context"`). Set to one of those three → queries only that
domain.

Pass-through by design — `gateway_map` does not reshape or unwrap what a
domain broker returns:

```python
{
    "health":  ...,   # exactly what health_map.get() returned
    "fit":     ...,   # exactly what fit_map.get() would return, once it exists
    "context": ...,   # exactly what context_map.get() returned
}
```

`"fit"` is a reserved domain key ahead of `fit_map.py` (v1.7) — until that
broker exists, `result["fit"]` is a degraded single entry,
`{"error": "domain not yet available"}`, never a hard failure.

Error behaviour:
- Unknown `domain` string (not `"health"`/`"fit"`/`"context"`/`None`) →
  `ValueError`. Caller error, not a data-availability problem.
- Known domain whose broker is not yet registered → degraded result,
  `{"error": "domain not yet available"}` under that domain key.
- A registered domain broker raising unexpectedly → degraded result,
  `{"error": str(exc)}` under that domain key. No hard-fail — same
  degraded-mode principle the domain brokers already use for their own
  sources.

`list_domains()` returns all known domain keys regardless of registration
state, currently `["health", "fit", "context"]`.

`get_raw(field, date_from, date_to, domain=None)` / `list_raw_fields(domain=None)`
(v1.6.8 Session 4) — same fan-out shape as `get()`/`list_domains()`, for
raw-passthrough fields. Currently only `"health"` supports raw-passthrough;
other domains degrade to `{"error": "domain has no raw-passthrough support"}`
(or `[]` for `list_raw_fields()`) rather than hard-failing — same principle
as the `"fit"`-not-yet-available case above.

### Building your own tool against a local archive

`gateway_map.get()` is the recommended entry point if you're writing your
own script or tool against a local GLA installation rather than modifying
GLA itself — one import, one contract, instead of learning `health_map`'s
and `context_map`'s contracts separately. It is a plain Python function
call (`from maps.gateway_map import get`), not a network endpoint — your
tool needs to run in the same Python environment/`sys.path` as the archive,
same as any other module in this repo.

**Single domain, one field:**

```python
from maps.gateway_map import get as gateway_get

result = gateway_get("resting_heart_rate", "2026-08-01", "2026-08-07",
                      resolution="daily", domain="health")
# result == {"health": {"garmin": {"values": [...], "fallback": False,
#                                   "source_resolution": "daily"}}}
```

Both brokers expose the same auxiliary functions:

| Function | `health_map` default | `context_map` default |
|---|---|---|
| `list_fields(source=..., active_only=...)` | `source="garmin"`, `active_only=False` | `source="weather"` — `active_only` ignored, `context_map` has no capability concept |
| `list_sources()` | returns `["garmin"]` | returns `["weather", "pollen", "brightsky", "airquality"]` |
| `list_raw_fields(source=...)` (v1.6.8 Session 4) | `source="garmin"` — 13 fields | not supported, always `[]` |

`active_only=True` (health_map/garmin only) excludes API-Capability-Scan
candidate fields whose endpoint is not `enabled_by_user` — used by the
Custom Dashboard field picker and Explorer (v1.6.8 Session 4, "Governance B").

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

**`health_map` → `garmin`** (31 fields)

| Field | Value | Description |
|---|---|---|
| `hrv_last_night` | ms | Heart rate variability, overnight average |
| `resting_heart_rate` | bpm | Resting heart rate for the day |
| `spo2_avg` | % | Average blood oxygen saturation, overnight |
| `sleep_duration` | hours | Total sleep duration |
| `body_battery_max` | 0–100 | Peak Body Battery energy level for the day |
| `stress_avg` | 0–100 | Average stress level for the day |
| `vo2max` | — | VO2max estimate — no fixed unit, device-calculated index |
| `sleep_score` | 0–100 | Overall sleep score (v1.7.1.6 — previously retrievable via `health_map.get()`/`get_raw()`'s `live_nested` and `daily` routes but missing its own table row here, a pre-existing gap noted in `REFERENCE_GARMIN.md`, closed this session; value range confirmed against `tests/test_dashboard.py`'s live-route fixture) |
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
| `body_weight` | grams | Body weight, from API-Capability-Scan candidate `get_body_composition` — first candidate wired into the broker (v1.6.8 pilot), unit unverified against real scale data |
| `calories_resting` | kcal | Resting/basal calories, from API-Capability-Scan candidate `get_calories_daily` — second candidate wired into the broker (v1.6.8 pilot) |
| `hydration_ml` | ml | Daily fluid intake, from API-Capability-Scan candidate `get_hydration_data` — only `valueInML` adopted (v1.6.8 Session 4) |
| `endurance_score` | index | Endurance Score, from API-Capability-Scan candidate `get_endurance_score` — device-calculated index, checked against `vo2max` for redundancy, none found (v1.6.8 Session 4) |
| `hill_score` | index | Hill Score, from API-Capability-Scan candidate `get_hill_score` — not to be confused with that same endpoint's own internal `enduranceScore` sub-field (v1.6.8 Session 4) |
| `fitness_age` | years | Fitness Age, from API-Capability-Scan candidate `get_fitnessage_data` — only `fitnessAge` adopted (v1.6.8 Session 4) |
| `bp_high_systolic` | mmHg | Highest systolic reading of the day, from API-Capability-Scan candidate `get_blood_pressure` — pulled 1:1 from Garmin's own daily aggregate (v1.7.1.14, Issue #7) |
| `bp_high_diastolic` | mmHg | Highest diastolic reading of the day, same source and rollup as above (v1.7.1.14, Issue #7) |
| `bp_low_systolic` | mmHg | Lowest systolic reading of the day, same source and rollup as above (v1.7.1.14, Issue #7) |
| `bp_low_diastolic` | mmHg | Lowest diastolic reading of the day, same source and rollup as above (v1.7.1.14, Issue #7) |
| `bp_num_measurements` | count | Number of blood pressure measurements logged that day (v1.7.1.14, Issue #7) |
| `bp_category` | text | Garmin's day-level category (e.g. `STAGE_2_HIGH`, `NORMAL`) — reflects the worst individual reading of the day, not an average (v1.7.1.14, Issue #7) |

All six `bp_*` fields are gated in `_CAPABILITY_FIELDS` against
`get_blood_pressure` — account-dependent (requires a compatible
measurement device or manual entry), same gating pattern as
`body_weight`/`hydration_ml` above. A seventh blood-pressure value,
`worstReading` (`{systolic, diastolic, pulse, timestamp}` — the individual
measurement that produced the day's `bp_category`), is deliberately NOT
part of `_FIELD_MAP` — it has no single scalar value and doesn't fit
either the daily-scalar or intraday-series shape every other registered
field assumes. It lives as a plain nested object under the
`blood_pressure` key in the summary JSON (`raw["get_blood_pressure"]` →
`garmin_normalizer.summarize()`), read directly by any consumer that
needs it, not routed through `get()`/`list_fields()` — same treatment as
`sleep_score_feedback` (excluded from Explorer/Custom Dashboard's daily
field iteration via `_EXCLUDE_FROM_DAILY`). See `CHANGELOG.md` v1.7.1.14
for the Composite-field-type evaluation that led to this choice.

**`health_map` → `garmin` raw-passthrough** (12 fields, v1.6.8 Session 4)

Not part of `list_fields()`/`get()` — a deliberately separate access path,
see `health_map.get_raw()` above and `REFERENCE_GARMIN.md` →
"Raw-passthrough fields" for the rationale. No unit/description column —
these are unprocessed Garmin payloads, structure varies per endpoint, the
caller interprets them.

| Field | Source endpoint |
|---|---|
| `daily_weigh_ins` | `get_daily_weigh_ins` |
| `menstrual_calendar_data` | `get_menstrual_calendar_data` |
| `pregnancy_summary` | `get_pregnancy_summary` |
| `lifestyle_logging_data` | `get_lifestyle_logging_data` |
| `nutrition_daily_food_log` | `get_nutrition_daily_food_log` |
| `nutrition_daily_meals` | `get_nutrition_daily_meals` |
| `nutrition_daily_settings` | `get_nutrition_daily_settings` |
| `floors` | `get_floors` |
| `intensity_minutes_data` | `get_intensity_minutes_data` |
| `body_battery_events` | `get_body_battery_events` |
| `lactate_threshold` | `get_lactate_threshold` |
| `running_tolerance` | `get_running_tolerance` |

**`context_map` → `weather`** (6 fields)

| Field | Value | Description |
|---|---|---|
| `temperature_max` | °C | Daily maximum temperature |
| `temperature_min` | °C | Daily minimum temperature |
| `precipitation` | mm | Daily precipitation sum |
| `wind_speed_max` | km/h | Daily maximum wind speed |
| `uv_index_max` | index | Daily maximum UV index |
| `sunshine_duration` | seconds | Daily sunshine duration |

**`context_map` → `pollen`** (12 fields — 6 daily + 6 `_series`, v1.7.1.11)

| Field | Value | Description |
|---|---|---|
| `pollen_birch` | grains/m³ | Daily max birch pollen concentration |
| `pollen_grass` | grains/m³ | Daily max grass pollen concentration |
| `pollen_alder` | grains/m³ | Daily max alder pollen concentration |
| `pollen_mugwort` | grains/m³ | Daily max mugwort pollen concentration |
| `pollen_olive` | grains/m³ | Daily max olive pollen concentration |
| `pollen_ragweed` | grains/m³ | Daily max ragweed pollen concentration |
| `pollen_birch_series` | grains/m³ | Hourly birch pollen readings, timestamped (raw/, v1.7.1.11) |
| `pollen_grass_series` | grains/m³ | Hourly grass pollen readings, timestamped (raw/, v1.7.1.11) |
| `pollen_alder_series` | grains/m³ | Hourly alder pollen readings, timestamped (raw/, v1.7.1.11) |
| `pollen_mugwort_series` | grains/m³ | Hourly mugwort pollen readings, timestamped (raw/, v1.7.1.11) |
| `pollen_olive_series` | grains/m³ | Hourly olive pollen readings, timestamped (raw/, v1.7.1.11) |
| `pollen_ragweed_series` | grains/m³ | Hourly ragweed pollen readings, timestamped (raw/, v1.7.1.11) |

**`context_map` → `brightsky`** (18 fields — 9 daily + 9 `_series`, v1.7.1.11)

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
| `temperature_avg_series` | °C | Hourly temperature readings, timestamped (raw/, v1.7.1.11) |
| `humidity_avg_series` | % | Hourly relative humidity readings, timestamped (raw/, v1.7.1.11) |
| `precipitation_sum_series` | mm | Hourly precipitation readings, timestamped (raw/, v1.7.1.11) |
| `sunshine_sum_series` | min | Hourly sunshine readings, timestamped (raw/, v1.7.1.11) |
| `wind_speed_max_series` | km/h | Hourly wind speed readings, timestamped (raw/, v1.7.1.11) |
| `wind_gust_max_series` | km/h | Hourly wind gust readings, timestamped (raw/, v1.7.1.11) |
| `cloud_cover_avg_series` | % | Hourly cloud cover readings, timestamped (raw/, v1.7.1.11) |
| `pressure_avg_series` | hPa | Hourly pressure readings, timestamped (raw/, v1.7.1.11) |
| `condition_series` | text | Hourly condition readings, timestamped (raw/, v1.7.1.11) |

**`context_map` → `airquality`** (10 fields — 5 daily + 5 `_series`, v1.7.1.11)

| Field | Value | Description |
|---|---|---|
| `airquality_pm2_5` | μg/m³ | Daily mean fine particulate matter (PM2.5) |
| `airquality_pm10` | μg/m³ | Daily mean particulate matter (PM10) |
| `airquality_european_aqi` | index | Daily mean European Air Quality Index |
| `airquality_nitrogen_dioxide` | μg/m³ | Daily mean nitrogen dioxide concentration |
| `airquality_ozone` | μg/m³ | Daily mean ozone concentration |
| `airquality_pm2_5_series` | μg/m³ | Hourly PM2.5 readings, timestamped (raw/, v1.7.1.11) |
| `airquality_pm10_series` | μg/m³ | Hourly PM10 readings, timestamped (raw/, v1.7.1.11) |
| `airquality_european_aqi_series` | index | Hourly European AQI readings, timestamped (raw/, v1.7.1.11) |
| `airquality_nitrogen_dioxide_series` | μg/m³ | Hourly nitrogen dioxide readings, timestamped (raw/, v1.7.1.11) |
| `airquality_ozone_series` | μg/m³ | Hourly ozone readings, timestamped (raw/, v1.7.1.11) |

**`_series` fields, general note (v1.7.1.11):** each `_series` entry is an
independently registered `_FIELD_MAP` line, not a resolution branch of its
daily counterpart — see `REFERENCE_CONTEXT.md`'s "Fallback behaviour"
section for the full read-path and `fallback` contract. `weather` has no
`_series` variants — Open-Meteo Weather delivers no intraday data.

**Naming collision, deliberate:** `weather` and `brightsky` both register a
field called `wind_speed_max` — same generic name, independently defined in
each `_FIELD_MAP`, different internal source keys (`wind_speed_10m_max` vs.
`wind_speed`). There is no `source` parameter to disambiguate at call
time — `context_map.get()` queries every registered source that recognizes
the field and returns all of them under separate source keys in the same
response dict. The consumer distinguishes between them only afterwards, by
reading the keys of the returned dict, not by choosing one in advance.

---

## `gateway_map.get_metadata()` — archive-state introspection (v1.6.9.1)

```python
from maps.gateway_map import get_metadata

result = get_metadata("stats")
# result == {"data": {...}, "error": None}

result = get_metadata("quality_log", date_from="2026-08-01", date_to="2026-08-27")
# result == {"data": {...filtered...}, "error": None}
# (v1.7.0.4) date_from/date_to only affect five of the thirteen kinds —
# see REFERENCE_MCP.md's mcp_map.py's get_archive_metadata() entry for
# the full list and the 30-day default behaviour when neither is given.

# v1.7.1 — three filename-only kinds, internal sync use only, never
# exposed as their own MCP tool: "daily_log_filenames",
# "fail_log_filenames", "recent_log_filenames". Same
# {"data": [{"filename": str, "log_date": str}, ...], "error": ...}
# envelope and date-range-filter/30-day-default behaviour as their
# get_daily_logs()/get_fail_logs()/get_recent_logs() content-reading
# siblings — content-free by design, used exclusively by
# clients/mcp_update.py's SQLite proxy sync to learn which log files
# exist without reading them. Reachable via mcp_map.py's own
# list_daily_log_filenames()/list_fail_log_filenames()/
# list_recent_log_filenames() wrappers (see REFERENCE_MCP.md),
# not through get_archive_metadata() — that MCP tool intentionally still
# only exposes the original nine kinds to the LLM.

# v1.7.1.1 — a thirteenth kind, "raw_file_hashes", internal sync use
# only, also never exposed via get_archive_metadata(). Content hash
# (SHA-256) of the raw/ file per requested day — not a filename-encoded
# date, since a mirror/restore operation can rewrite a raw/ file with
# byte-identical content, which must not register as a change (same
# reasoning the three filename-only kinds above already apply to log
# filenames, applied here to file content instead). Unlike every other
# kind in this file, date_from/date_to are REQUIRED, not optional — no
# 30-day default, no "note" field; a caller must always know the exact
# range it needs (see metadata_map.get_raw_file_hashes()'s own
# docstring). Used exclusively by clients/mcp_update.py's raw-
# passthrough sync (see REFERENCE_MCP.md's get_raw_file_hashes()
# wrapper entry) to detect content changes — including data delivered
# after a day's recheck window had already closed — without re-reading
# every raw-passthrough field value on every sync pass.
#
# result = get_metadata("raw_file_hashes", date_from="2026-08-01", date_to="2026-08-02")
# result == {"data": {"2026-08-01": "<sha256 hex>", "2026-08-02": None},
#            "error": None}
# hash is None for a day whose raw/ file does not exist yet — not an
# error, same "day genuinely not written yet" principle every other
# metadata_map function already uses.
```

`fit_map.py` (v1.8) is planned as a peer to `health_map.py` and
`context_map.py` — same broker principle (domain-level, routes to
source-specific `*_map.py` modules below it), new domain (activity data).
`gateway_map.py` is already prepared for it — the `"fit"` domain key
exists in `_DOMAIN_BROKERS` ahead of the broker itself (see
`gateway_map.get()` above).

`mcp_map.py` is not a peer at this level — it does not aggregate the
Broker Layer itself. That role belongs to `gateway_map.py` (v1.6.7),
which is a peer within the Broker Layer, providing cross-domain routing
across `health_map`/`fit_map`/`context_map` for consumers that don't know
in advance which domain owns a field. `mcp_map` is pure protocol
translation (MCP ↔ `gateway_map`) — architecturally it sits alongside the
Dashboard Layer and the planned Export Layer, both of which consume the
Broker Layer the same way, just through a different output channel (MCP
protocol instead of file/chart).

---

