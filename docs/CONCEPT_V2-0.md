# Garmin Local Archive — v2.0 Vision

> ⚠️ **Read the README and the current codebase first.**
> This is a vision document — it describes where the project could go, not where it is.
>
> Nothing here is implemented. Nothing is committed or scheduled.
> All module names, interfaces, and structures are placeholders.
> Concrete decisions will be made when actual development begins.



## Directory Structure

```
base_dir/
├── source_registry.json             — which sources exist + active/inactive status
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

## Source Registry

`source_registry.json` is the single place that knows which sources exist and whether
they are currently active.

```json
{
  "sources": {
    "garmin": "active",
    "strava": "inactive",
    "komoot": "inactive"
  }
}
```

**Three separate responsibilities — three separate actors:**

| Who | Does what | When |
|---|---|---|
| Developer / user | adds a new source to the registry | once, when a new pipeline is created |
| `master_collector.py` | checks each source against `config` — writes `active`/`inactive` | on every sync |
| `field_map.py` | loads registry, contacts only active `*_map.py` modules | on demand, per dashboard request |

`source_registry.json` is never written by `field_map.py` and never read by the
individual `*_map.py` modules — it is purely the handshake layer between pipeline
setup and runtime use.

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
3. Write `komoot_map.py` — register with `field_map.py`
4. All global actors work without modification — `field_map.py` itself is never touched

---

## Global Translator

`field_map.py` is the **stable request broker** between dashboard/export scripts and
the source-specific map modules. Dashboard and export scripts only call `field_map` —
they have no knowledge of any source-specific field names or data structures.

`field_map.py` knows which common names exist (e.g. `heart_rate_series`) and which
`*_map.py` modules are registered. It does **not** know how any source stores its data
internally. That knowledge lives exclusively in the source map modules.

```
Dashboard:       "give me heart_rate_series"
    ↓
field_map.py:    asks all registered *_map.py: "give me heart_rate_series"
    ↓
garmin_map.py:   checks garmin_quality.json → has data → returns value
strava_map.py:   checks strava_quality.json → no data  → returns None
    ↓
field_map.py:    aggregates only what is available
    ↓
Dashboard:       receives values from all sources that have data
```

Source filtering is carried in the request — a Strava-only dashboard simply passes
a filter and `field_map.py` asks only `strava_map.py`:

```
Dashboard:       "give me heart_rate_series [strava only]"
    ↓
field_map.py:    asks only strava_map.py
```

Each `*_map.py` checks its own `quality_log.json` for availability — this is its own
house, not a foreign responsibility. No central index is needed: availability
information already exists in each source's quality log and is never duplicated.

Conceptual representation (placeholder — actual implementation may be significantly
more complex):

```python
# field_map.py — knows common names and registered modules, not field names
_SOURCES = [garmin_map, strava_map]  # registered at startup

def get(field: str):
    """Ask all registered sources for the value of a common field."""
    return {source.NAME: source.get(field) for source in _SOURCES}


# garmin_map.py — knows Garmin internals, nothing else
NAME = "garmin"

def get(field: str):
    """Return the Garmin value for a common field name."""
    _MAP = {
        "heart_rate_series": "heartRateValues",
        "timestamp": "time",
    }
    return _read_garmin_data(_MAP[field])
```

**Adding a new source** means writing a new `xxx_map.py` and registering it —
`field_map.py` itself is never modified. All dashboard and export scripts work
automatically.

---

## Three Layers, Three Responsibilities

```
*_map.py             — where each field lives, and whether data exists  (field knowledge + availability)
field_map.py         — stable request broker to all *_map.py            (aggregation)
*_master.py          — how source X behaves                             (plugin)
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
   │
   ├── "Strava strand" → strava_master as plugin
   │       strava_api      → fetch raw data
   │       strava_quality  → assess quality
   │       normalizer      → strava_master provides schema
   │       writer          → strava_master provides paths
   │
   └── each source's quality_log updated → dashboard/export readable via field_map
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
field_map.py           — global field broker
source_registry.json   — which sources exist + active/inactive status

HTML/Excel scripts     — read summaries via field_map
build.py               — stays global
build_standalone.py    — stays global
```

---

## Migration Principle

When rebuilding from v1.x to v2.0, no module is assumed to be source-agnostic or
plugin-based by default. Each component is evaluated individually at the point of
migration:

- Is the logic truly identical across sources → extract into a global actor
- Does the logic differ meaningfully per source → keep in the plugin
- Would a plugin interface add real value here → build one; otherwise don't

This avoids both premature abstraction (building structure before the need is proven)
and unnecessary duplication (copying code that is structurally identical across all
sources). The decision is made at migration time, with real code in front of us —
not in advance.

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
- **Standalone build** — the impact of a multi-source plugin architecture on the
  Standalone build target (single EXE, no Python required) has not yet been evaluated.
  Each source plugin brings its own dependencies — the current single-EXE approach
  may not be viable for v2.0 and may require a fundamentally different distribution model.

  The plugin system operates dynamically at runtime — global actors load `*_master.py`
  modules on demand via the source registry. PyInstaller cannot detect dynamic imports
  statically, which means the standard single-EXE build process breaks by design.

  Target 2 (standard EXE, Python required) is unaffected — all files sit openly in the
  filesystem and are loaded at runtime as-is.

  For Target 3 (Standalone EXE), `build_standalone.py` acts as the translation layer
  between the dynamic plugin world and the static EXE world: it scans all registered
  `*_master.py` modules at build time, resolves their dependencies explicitly, and
  passes a complete static import list to PyInstaller. The EXE itself contains only
  source-agnostic global actors — all plugin compositions are resolved before the build,
  not at runtime.

  > 💡 **Thought fragment — not a decision**
  > A further idea: `build_standalone.py` does not just declare plugins statically but
  > generates pre-composed script variants — each global actor merged with its plugin
  > into a single self-contained module (`writer_garmin.py`, `writer_strava.py`, ...).
  > The Standalone EXE would then contain no plugin system at runtime whatsoever — only
  > flat, fully resolved modules. Conceptually clean. Whether the implementation effort
  > is justified over the simpler static-import approach is an open question.
  > Evaluate at build time, with real plugins in front of us — not in advance.

This concept defines **what** each layer is responsible for. **How** it is implemented
remains open until actual development begins.
