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

`result["garmin"]` contract:

```python
{
    "values":            list,   # [{"date": str, "value": any}, ...]  — daily
                                 # [{"date": str, "series": list|None}, ...]  — intraday
    "fallback":          bool,   # True if requested resolution was unavailable, downgraded
    "source_resolution": str,    # actual resolution used: "daily" or "intraday"
}
```

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

`result[source_name]` contract — same structure as `field_map` broker return:

```python
{
    "values":            list,
    "fallback":          bool,
    "source_resolution": str,
    "error":             str,    # optional — only present if source failed
}
```

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

## Future brokers

`fit_map.py` (v1.7) and `mcp_map.py` (v1.9) are planned as peers to
`field_map.py` and `context_map.py` — same broker principle, new domains.
Full architecture in `ROADMAP.md`. This file gets a dedicated section for
each once implementation actually starts — no contract is assumed here
ahead of time.

---

*Source of truth for the Broker Layer's outward-facing contract. Per-field
internal mappings live in the per-domain reference files — this file never
duplicates them, only points to them.*
