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
| `health_map.py` | Garmin health data | `garmin_health_map` | `_SOURCES = {"garmin": garmin_health_map}` |
| `context_map.py` | External context data | `weather_map`, `pollen_map`, `brightsky_map`, `airquality_map` | `_SOURCES = {"weather": ..., "pollen": ..., "brightsky": ..., "airquality": ...}` |
| `gateway_map.py` | Cross-domain routing for external/aggregate consumers | `health_map`, `fit_map` *(planned)*, `context_map` | `_DOMAIN_BROKERS = {"health": health_map, "fit": None, "context": context_map}` |
| `metadata_map.py` *(v1.6.9.1)* | Archive-state introspection (not time-series) | — reads archive files directly, catch-all for data outside health/fit/context | routed via `gateway_map.get_metadata()`, not `_DOMAIN_BROKERS` — see below |
| `fit_map.py` *(planned, v1.8)* | Activity data (Garmin FIT, later Strava) | `garmin_fit_map`, future `strava_fit_map` | see `ROADMAP.md` → v1.8 FIT Pipeline |
| `mcp_map.py` *(v1.7)* | MCP protocol translation | `gateway_map` | pure delegation, no `_SOURCES`/`_DOMAIN_BROKERS` registry of its own — see `mcp_map.py` contract section below |

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

**`health_map` → `garmin`** (25 fields)

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

**`health_map` → `garmin` raw-passthrough** (13 fields, v1.6.8 Session 4)

Not part of `list_fields()`/`get()` — a deliberately separate access path,
see `health_map.get_raw()` above and `REFERENCE_GARMIN.md` →
"Raw-passthrough fields" for the rationale. No unit/description column —
these are unprocessed Garmin payloads, structure varies per endpoint, the
caller interprets them.

| Field | Source endpoint |
|---|---|
| `daily_weigh_ins` | `get_daily_weigh_ins` |
| `blood_pressure` | `get_blood_pressure` |
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

## `gateway_map.get_metadata()` — archive-state introspection (v1.6.9.1)

```python
from maps.gateway_map import get_metadata

result = get_metadata("stats")
# result == {"data": {...}, "error": None}

result = get_metadata("quality_log", date_from="2026-08-01", date_to="2026-08-27")
# result == {"data": {...filtered...}, "error": None}
# (v1.7.0.4) date_from/date_to only affect five of the thirteen kinds —
# see mcp_map.py's get_archive_metadata() below for the full list and
# the 30-day default behaviour when neither is given.

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
# list_recent_log_filenames() wrappers (see mcp_map.py section below),
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
# passthrough sync (see mcp_map.py's get_raw_file_hashes() wrapper
# below) to detect content changes — including data delivered after a
# day's recheck window had already closed — without re-reading every
# raw-passthrough field value on every sync pass.
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

## `mcp_map.py` — MCP protocol translation (v1.7)

```python
from maps.mcp_map import query_health, query_context, query_fit_activities, \
    query_raw, get_archive_metadata, list_available_fields
```

Thin delegation to `gateway_map.get()`/`get_raw()`/`get_metadata()` —
`mcp_map.py` owns no data, no state, no MCP-SDK dependency, and is fully
testable without a running MCP server (`tests/test_mcp.py`). Tool
granularity is domain-named, not a 1:1 wrapper around `gateway_map`
parameters — one function per domain (`query_health`/`query_context`/
`query_fit_activities`) rather than a single generic `query(domain=...)`,
so a domain typo is a Python-level caller error (wrong function name)
instead of a silent runtime string mismatch.

```python
query_health(field, date_from, date_to, resolution="daily") -> dict
# {"health": <gateway_map.get(..., domain="health")["health"]>, "_meta": {...}}

query_context(field, date_from, date_to, resolution="daily") -> dict
# {"context": <gateway_map.get(..., domain="context")["context"]>, "_meta": {...}}

query_fit_activities(field, date_from, date_to, resolution="daily") -> dict
# {"fit": <gateway_map.get(..., domain="fit")["fit"]>, "_meta": {...}}
# until garmin_fit_map.py lands (v1.8): {"fit": {"error": "domain not yet
# available"}, "_meta": {...}} — gateway_map's existing unregistered-domain
# handling, no FIT-specific code path here (see
# KONZEPT_mcp_sqlite_proxy_V2.md, "FIT-Anbindung: Stöpsel statt
# Vollintegration")

query_raw(field, date_from, date_to, domain=None) -> dict
# gateway_map.get_raw() result + "_meta" key added

get_archive_metadata(kind, date_from=None, date_to=None) -> dict
# gateway_map.get_metadata(kind, date_from, date_to) result, unchanged —
# no "_meta" weekday block here either way, that concept is specific to
# the time-series query_*() functions above. date_from/date_to (v1.7.0.4)
# are a plain date-RANGE FILTER, not the same thing as a time-series
# "resolution" — only five of the nine LLM-facing kinds honor them
# ("quality_log", "source_api_log", "daily_logs", "fail_logs",
# "recent_logs"); the other four ("stats", "device_table", "token_log",
# "capability_config") silently ignore both arguments. Omitting both on
# a filterable kind returns the last 30 days (anchored on the latest
# available date, not on today) plus a "note" field in the result
# explaining that, rather than the previous unfiltered full-archive
# dump. get_archive_metadata() itself only ever exposes these original
# nine kinds to the LLM — the four internal-sync-only kinds below
# (three filename-only kinds + raw_file_hashes) are reachable only
# through mcp_map.py's own dedicated wrapper functions, never through
# get_archive_metadata() itself.

list_available_fields(domain=None) -> dict
# {"domains": [...], "metadata_kinds": [...],
#  "fields": {"health": {...}, "context": {...}, "fit": []}}

# v1.7.1 — internal sync use only, NOT registered as MCP tools in
# clients/mcp_server.py (deliberately — clients/mcp_update.py is the
# only intended caller, an LLM has no use for a raw filename list). Same
# thin-delegation, no-"_meta"-block pattern as get_archive_metadata()
# above.
list_daily_log_filenames(date_from=None, date_to=None) -> dict
# gateway_map.get_metadata("daily_log_filenames", date_from, date_to)

list_fail_log_filenames(date_from=None, date_to=None) -> dict
# gateway_map.get_metadata("fail_log_filenames", date_from, date_to)

list_recent_log_filenames(date_from=None, date_to=None) -> dict
# gateway_map.get_metadata("recent_log_filenames", date_from, date_to)

# v1.7.1.1 — same internal-sync-only rationale, raw-passthrough cache
# side (Ziel 4). Both required, no optional-range default — see
# get_metadata()'s own "raw_file_hashes" section above for why.
get_raw_file_hashes(date_from, date_to) -> dict
# gateway_map.get_metadata("raw_file_hashes", date_from, date_to)

# v1.7.1.1 — closes a gap discovered mid-session: no existing mcp_map.py
# function exposed gateway_map.list_raw_fields() to clients/mcp_update.py,
# which clients/mcp_update.py::_sync_raw_fields() needs to read the live
# raw-passthrough field registry on every sync pass rather than
# hard-coding a field count (the registry is documented as "open for
# community feedback" and can grow or shrink — see REFERENCE_GARMIN.md,
# "Raw-passthrough fields"). Distinct from list_available_fields()
# above: that function's "fields" key never included raw-passthrough
# fields at all (see its own docstring — "fit" always an empty list,
# raw-passthrough is a structurally separate registry).
list_raw_fields(domain=None) -> dict
# gateway_map.list_raw_fields(domain) — same shape as that function's
# own contract (see gateway_map.get_raw() section above), passed through
# unchanged.
```

**`_meta` block** — attached to every date-ranged query response
(`query_health`/`query_context`/`query_fit_activities`/`query_raw`), built
by `_build_meta(date_from, date_to)`:

```python
{
    "date_from_iso":      str,   # "2026-08-01"
    "date_from_readable": str,   # "August 01, 2026"
    "date_to_iso":         str,
    "date_to_readable":    str,
    "weekdays": {                # one entry per calendar day in range
        "2026-08-01": "Saturday",
        "2026-08-02": "Sunday",
        # ...
    },
}
```

Deliberately one entry per calendar day, not per data point — at intraday
resolution the latter would repeat the same weekday string thousands of
times. Addresses a documented LLM failure mode (miscalculating weekdays
from a bare ISO date) found during reference analysis ahead of the v1.7
build (`NOTES_v1.7-vorbereitung.md`).

**Error behaviour** — identical principle to `gateway_map.py`, never
raises for data-availability reasons:
- Degraded `{"error": ...}` results from `gateway_map` are passed through
  unchanged, nested under the domain/result key — a normal successful
  return with an `error` field in the payload, not an exception.
- `gateway_map.get()`'s `ValueError` for a genuinely unknown domain string
  cannot occur via `query_health`/`query_context`/`query_fit_activities` —
  domain is fixed per function, not caller-supplied.
- `query_raw()` raises `ValueError` if `domain` is set to an unknown
  string — passed through unchanged from `gateway_map.get_raw()`.
- `get_archive_metadata()` raises `ValueError` if `kind` is not a known
  metadata kind — passed through unchanged from `gateway_map.get_metadata()`.

**Consumer:** `clients/mcp_server.py` (v1.7 Teilbauauftrag b, extended
v1.7.1/v1.7.1.1) — standalone MCP server process, streamable-http
transport (`mcp>=1.28,<2`, v1.7.0.1 — replaces the earlier stdio
transport). Registers the original six functions above as MCP tools via
`@mcp.tool()`, same names, same signatures, plus a seventh,
`refresh_cache()` (v1.7.1, manual SQLite-proxy sync trigger — see
`KONZEPT_mcp_sqlite_proxy_V2.md`), which does not live in `mcp_map.py`
at all — it delegates directly to `clients/mcp_update.py::sync_all()`.
The three `list_*_log_filenames()` functions plus `get_raw_file_hashes()`/
`list_raw_fields()` (v1.7.1.1) above are **not** part of either group —
`mcp_map.py` exposes them for `clients/mcp_update.py`'s own internal
use, but `mcp_server.py` deliberately does not register them as MCP
tools (eleven `mcp_map.py` functions total; seven MCP tools total). No
error-translation code in `mcp_server.py` itself — the MCP SDK
automatically converts any uncaught exception raised inside a
`@mcp.tool()`-decorated function into `CallToolResult(isError=True, ...)`
with `str(exception)` as the message, so the two `ValueError` cases
above reach the MCP client without `mcp_map.py` or `mcp_server.py`
doing any translation work. Degraded `{"error": ...}` results are
ordinary tool payloads — `isError` stays `False`.

**Routing weiche (v1.7.1.1, `_route_query()`):** `clients/mcp_server.py`
gained an internal routing decision point that all six query tools
(`query_health`/`query_context`/`query_fit_activities`/`query_raw`/
`get_archive_metadata`/`list_available_fields`) now call before
delegating — placeholder today, always returns `"sqlite"`, `TODO
v1.7.x` for a real cost/staleness heuristic. `refresh_cache()`
deliberately does not route (a sync trigger, not a data query — see
`KONZEPT_mcp_sqlite_proxy_V2.md`). The `"sqlite"` branch calls the
matching `clients/mcp_sql.py` cache-read function
(`get_health_range()`/`get_context_range()`/`get_raw_range()`/
`get_metadata_range()`) instead of the `mcp_map.py` functions
documented above; `query_fit_activities`/`list_available_fields` route
through the same decision point but both branches currently call the
identical `mcp_map.py` function (no `mcp_sql.get_fit_range()` until
`fit_map.py` lands, v1.8; no cache benefit at all for a code-registry
read in the latter case) — this file's `mcp_map.py` contract above
remains the authoritative description of what each tool *returns*; the
weiche only changes *which module supplies it*, never the per-field
shape. **(v1.7.1.2)** `get_health_range()` now accepts the same `field`
its caller was given and returns only that field, rather than every
health field regardless of request — a `v1.7.1.1` defect (`field` was
silently dropped at the `mcp_server.py` call site) that this file did
not previously document, since the weiche's own routing logic was
unaffected and the gap sat one layer below it. Per-field shape
(`{"values": [...], "fallback": bool, "source_resolution": str}`)
itself is unchanged. **(v1.7.1.3)** `get_context_range()` likewise now
accepts and honors `field` — a distinct, longer-lived defect than
`get_health_range()`'s: the function's own signature never accepted a
`field` argument at all before this fix, so `v1.7.1.1`'s partial
`query_health()` fix had nothing to build on here. Filtering keeps
every source carrying the requested field (a field can be registered
by more than one source, see `context_map.py`'s documented
`wind_speed_max` naming collision) rather than collapsing to a single
source. Per-source, per-field shape
(`{source: {field: {"values": [...], "fallback": bool,
"source_resolution": str}}}`) itself is unchanged.

**(v1.7.1.4)** `query_context()` gained unknown-field detection,
checked in `clients/mcp_server.py` before the `_route_query()` switch
above — applies regardless of which branch ends up serving the
request, since the field registry itself
(`mcp_map.list_available_fields`) is unrelated to that routing
decision. `v1.7.1.3`'s field-filter fix made `field` reach
`get_context_range()` correctly, but left the caller unable to tell
"field does not exist" apart from "field exists, no data in this
range" — both previously returned an identical `{"context": {}}`.
Three unknown-field outcomes, checked in this order:
1. **Unambiguous near-match** against the live context field registry
   (`difflib.get_close_matches`, `cutoff=0.8`, exactly one candidate)
   — auto-resolved transparently: the resolved field is queried
   instead, and the result gains `_meta.field_resolved_from` (the
   caller's original input) and `_meta.field_used` (the resolved
   field) — never a silent, unmarked substitution.
2. **Domain confusion** — the field IS registered, but under
   `query_health`'s field registry, not `query_context`'s (e.g. a
   Garmin sleep field mistakenly sent to `query_context`) — returns
   `{"context": {}, "error": "field '<field>' belongs to query_health,
   not query_context", "_meta": {...}}`, no `did_you_mean` (a
   context-domain suggestion would be actively wrong here).
3. **Neither of the above** (a category/source name like `"weather"`,
   or no close match at all) — returns `{"context": {}, "error":
   "unknown field '<field>'", "_meta": {...}}`, with an additional
   `did_you_mean` list when `difflib` found any candidates, omitted
   when it found none.

A valid field's result (with or without data in the requested range)
is unaffected — none of the above runs unless `field` is unrecognized
against the registry queried at request time. `query_health`/
`get_health_range()` have the same underlying gap (an unregistered
health field returns the same silent empty result as a data-free valid
one) — deliberately not addressed here, tracked as a known,
not-yet-scheduled follow-up rather than pulled into this fix.

**(v1.7.1.5)** `query_context()` gained category-bundle resolution,
checked BEFORE the three unknown-field outcomes above (a bundle name
is never itself a registered field, so without this check it would
always fall into outcome 3) but still routed through the same
`_route_query()` sqlite/live switch per bundle field — no bypass
data-access path. `_CONTEXT_CATEGORY_BUNDLES` in `clients/mcp_server.py`
maps `"weather"`/`"pollen"`/`"air"` to a PRIORITY-ORDERED list of
`context_map` source names (`"weather": ["brightsky", "weather"]`,
`"pollen": ["pollen"]`, `"air": ["airquality"]`) — not a field list;
field names per source are resolved at call time via
`mcp_map.list_available_fields(domain="context")`, so a source's own
field additions need no change here. See
`KONZEPT_query_context_kategorie_aufloesung.md` for the full
architecture decision (server-side register chosen over relying on
model-driven multi-field selection, given the project's Ollama
model-diversity requirement).

A bundle's result is flattened to one value per field name — the
normal per-source grouping (`{source: {field: {...}}}`) collapses to
`{field: {...}}` directly under `"context"`. The sole real naming
collision in the current registry, `wind_speed_max` (registered by
both `weather` and `brightsky` under different internal keys and
different values — Modell vs. Messstation, see `context_map.py`'s
naming-collision note above), is resolved PER DAY, not per whole
field: for each date in range, the first source in the bundle's
priority list with a non-`None` value for that specific day wins — a
field's final `values` array can therefore be stitched together from
more than one source across a range (e.g. brightsky for most days,
weather filling in a day brightsky has no data for). The winning
source per collision-day is recorded in `_meta.field_sources` (e.g.
`{"wind_speed_max": {"2026-03-01": "brightsky", "2026-03-02":
"weather"}}`) — only for fields that actually had more than one
candidate source in the bundle; a field copied through from a single
source (the normal case for `pollen`/`air`, and most `weather` fields)
gets no `field_sources` entry.

Deliberately out of scope for this fix (see concept document's closing
section): `_meta.aqi_category` for `airquality_european_aqi`, a
GUI-panel disclaimer, and a `"bundles"` key in
`list_available_fields()` reporting the register's contents back to
callers — all tracked as follow-ups, not pulled into this session.
`mcp_sql.py`/`mcp_map.py`/`context_map.py` untouched — the bundle
register and flattening logic live entirely in the `mcp_server.py`
wrapper; `mcp_sql.py` remains a pure SQLite access layer with no
validation/bundle logic, per the `v1.7.1.4` precedent. `clients/` still
has no direct `maps.context_map` import — field names per source are
obtained via `mcp_map.list_available_fields()`, the same broker-facing
surface already used for the `v1.7.1.4` unknown-field registry lookup.

**(v1.7.1.6)** `query_health()`, `query_context()` (both its direct-field
and its category-bundle path), and `list_available_fields()` gained an
explicit unit per field — closing the gap this file's own "Field index"
table already existed to bridge for a human reader, but which the MCP
tool schema itself never exposed to an LLM caller (verified empirically
against `qwen3:14b`/`qwen2.5-coder:7b`/`mistral-nemo` — see
`NOTES_v1716_session2.md` for the test transcript). `query_health()`/
`query_context()` results gain a `"unit"` key alongside `"values"`/
`"fallback"`/`"source_resolution"` on every field-level dict, for both
the SQLite and the live branch identically (applied after the
`_route_query()` switch, not before). `list_available_fields()` gains an
additive `"units"` key (flat `{field_name: unit}`) alongside its
existing `"fields"` key, which itself keeps its original name-list shape
unchanged. Unit values transcribed from this file's own "Field index"
table above, no new research — including the "no exceptions" rule
(every field gets a unit, including ones with no physical unit, e.g.
`vo2max`/`airquality_european_aqi` → `"—"`/`"index"`, never an omitted
key) to avoid a mixed state that would itself become a new source of
LLM misinterpretation.

Deliberately kept MCP-local (`clients/mcp_server.py`'s new `FIELD_UNITS`
dict), NOT in `maps/mcp_map.py`, `maps/health_map.py`,
`maps/context_map.py`, or `maps/gateway_map.py` — two reasons found
during this session's own review, not anticipated at session start: (1)
`_route_query()` currently always returns `"sqlite"`; that branch never
reaches `mcp_map.py` at all, so a unit lookup placed there would
silently do nothing for every real request today; (2) a unit registry
living only at the MCP layer would be an island, unusable by dashboard
specialists or any other broker consumer — see `KNOWN_ISSUES.md` Cluster F,
extended this session with this stopgap as a documented, intentionally
swappable placeholder (isolated behind one function, `_get_field_unit()`,
so a future broker-level replacement needs no caller-side change).
`maps/mcp_map.py` itself is untouched this session.
