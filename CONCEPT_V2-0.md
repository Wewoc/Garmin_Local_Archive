# Garmin Local Archive — v2.0 Architecture Concept

> This is a planning document. All module names, structures, and implementation details
> are placeholders — they describe responsibilities and boundaries, not final
> implementations. Concrete decisions will be made at the time of actual development.
>
> Nothing here is committed or scheduled. This document describes a possible future
> direction, not a roadmap with dates or guarantees.

---

## Motivation

v1.x is designed for a single data source — Garmin Connect. In practice, health and
fitness data comes from multiple sources in parallel: Garmin provides HRV, sleep,
stress and Body Battery; a bike computer (e.g. Wahoo Elemnt) provides cadence, power
and GPS tracks via Strava; Komoot provides routes and elevation data. These data sets
complement each other — meaningful analysis requires all of them.

v2.0 extends the architecture to support any number of data sources without touching
the existing Garmin logic.

---

## Directory Structure

```
base_dir/
├── master/
│   ├── master_index.json        — routing index: date → sources → paths
│   └── log/                     — master log (format TBD)
│
├── garmin_data/
│   ├── raw/
│   ├── summary/
│   └── log/
│
├── strava_data/
│   ├── raw/
│   ├── summary/
│   └── log/
│
└── komoot_data/                 — or any additional source
    ├── raw/
    ├── summary/
    └── log/
```

Each source is fully isolated — its own raw data, its own summaries, its own quality
log. No source writes into another source's directory.

---

## Master Index

```json
{
  "2026-03-22": {
    "garmin": "garmin_data/summary/garmin_2026-03-22.json",
    "strava": "strava_data/summary/strava_2026-03-22.json",
    "komoot": "komoot_data/summary/komoot_2026-03-22.json"
  }
}
```

The Master Index is a pure **routing layer** — it contains no data, makes no decisions,
and holds no logic. It answers exactly one question:
"Which sources have data for this day, and where are the files?"

What a script does with this information is entirely the script's own concern —
the Master Index anticipates nothing.

---

## Module Architecture

### Global Actors — source-agnostic

Global actors have no direct knowledge of any source. They define the process flow and
retrieve all source-specific details at runtime from the relevant plugin module.

```
master_collector.py  — orchestrator across all sources
writer.py            — writes raw/ + summary/ for every source
normalizer.py        — normalises raw data into a common schema
sync.py              — date logic, source-aware
security.py          — token management, global
config.py            — configuration, global
field_map.py         — global field translator (see below)
```

### Plugin Modules — source-specific

Each plugin module is the **source's adapter for the global actors**. It implements a
unified interface and delivers all source-specific details on demand — paths, formats,
validation rules, token location.

```
garmin_master.py     — Garmin plugin
strava_master.py     — Strava plugin
komoot_master.py     — Komoot plugin
```

Interface (placeholder — concrete form will be defined at implementation time):

```python
def get_paths()      → paths for raw/ and summary/
def get_format()     → expected raw format
def get_validator()  → validation rules
def get_token()      → token location for security.py
```

### Source-Specific Actors

Each source brings its own specialised modules — following the same pattern as the
existing Garmin architecture in v1.x.

```
garmin_api.py        — Garmin API only (login, fetch, devices)
garmin_quality.py    — Garmin quality_log.json only
garmin_import.py     — Garmin bulk import

strava_api.py        — Strava API only
strava_quality.py    — Strava quality_log.json only
strava_import.py     — Strava bulk import (FIT files)

komoot_api.py        — Komoot API only
komoot_quality.py    — Komoot quality_log.json only
komoot_import.py     — Komoot bulk import
```

---

## The Plugin Principle

The global actor defines the **process flow**. The plugin module delivers the
**source-specific details**. No global actor contains source-specific code.

```
master_collector: "I want Garmin data for 2026-03-22"
        │
        ├── loads garmin_master as plugin
        │
        ▼
writer.py asks the plugin:
        │   source.get_paths()       → where to write?
        │   source.get_format()      → which raw format?
        │   source.get_validator()   → which validation rules?
        ▼
writer writes — without any knowledge of Garmin-specific code
```

The same principle applies to all global actors:

```
normalizer.py  + *_master  → knows what the source JSON looks like
sync.py        + *_master  → knows which dates are missing
security.py    + *_master  → knows where the token is stored
writer.py      + *_master  → knows where to write
```

**Adding a new source:**
1. Write `komoot_master.py` — implement the plugin interface
2. Write `komoot_api.py` + `komoot_quality.py`
3. Extend `field_map.py` with Komoot fields
4. All global actors work without modification

---

## Global Translator

`field_map.py` is the **single place** in the entire project that knows how fields
map between sources and the common schema. Dashboard and export scripts only import
`field_map` — they have no knowledge of source-specific details.

Conceptual representation (placeholder — actual implementation may be significantly
more complex, see note below):

```python
FIELD_MAP = {
    "heart_rate_series": {
        "garmin": "heartRateValues",
        "strava": "streams.heartrate.data",
        "komoot": "hr_data"
    },
    "timestamp": {
        "garmin": "time",
        "strava": "time_offset",
        "komoot": "timestamp"
    }
}

def get(field: str, source: str) -> str:
    """Returns the source-specific field name."""
    return FIELD_MAP[field][source]
```

Adding a new source means only extending `field_map` — all scripts work automatically.

> **Note:** `field_map` is shown here as a simple dict. In practice it could grow into
> its own subsystem — with validation logic, source-specific mapping files, version
> tracking (if API fields change), or a schema registry. The responsibility stays the
> same; the implementation complexity will be evaluated at the time of development.

---

## Three Layers, Three Responsibilities

```
field_map            — where each field lives per source      (translation)
master_index.json    — which sources have data on day X       (routing)
*_master.py          — how source X behaves                   (plugin)
```

Each layer has exactly one responsibility. No layer takes on the task of another.

---

## Flow Principle

```
master_collector
   │
   ├── "Garmin strand" → garmin_master as plugin
   │       garmin_api      → fetch raw data
   │       garmin_quality  → assess quality
   │       normalizer      → garmin_master provides schema
   │       writer          → garmin_master provides paths
   │       master_index    → add entry
   │
   ├── "Strava strand" → strava_master as plugin
   │       strava_api      → fetch raw data
   │       strava_quality  → assess quality
   │       normalizer      → strava_master provides schema
   │       writer          → strava_master provides paths
   │       master_index    → add entry
   │
   └── master_index complete → dashboard/export readable
```

---

## What Stays Global

```
master_collector.py    — orchestrator across all sources
writer.py              — writes for all sources
normalizer.py          — normalises for all sources
sync.py                — date logic for all sources
security.py            — token management for all APIs
config.py              — global configuration
field_map.py           — global field translator

HTML/Excel scripts     — read master index + summaries via field_map
build.py               — stays global
build_standalone.py    — stays global
```

---

## Placeholder Notice

All module names, interface definitions, and implementation details in this document
are placeholders. They describe **responsibilities and boundaries**, not finished
implementations.

Particularly open:

- **`*_master.py`** — may become a formal Abstract Base Class rather than plain
  functions if multiple sources are implemented
- **`field_map.py`** — may grow into its own subsystem (see above)
- **`master_collector.py`** — may require threading or async for parallel sources
- **`master/log/`** — content and format not yet defined

This concept defines **what** each layer is responsible for. **How** it is implemented
remains open until actual development begins.
