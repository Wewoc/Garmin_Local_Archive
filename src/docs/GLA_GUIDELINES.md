# Garmin Local Archive — Developer Guidelines

> A snapshot of the project's architecture and working process.
> Authoritative sources (always more current than this document):
> [CHANGELOG.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/CHANGELOG.md) · [ROADMAP.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/ROADMAP.md) · [REFERENCE_GARMIN.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/REFERENCE_GARMIN.md) · [REFERENCE_DASHBOARD.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/REFERENCE_DASHBOARD.md) · [REFERENCE_BROKER.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/REFERENCE_BROKER.md) · [MAINTENANCE_GARMIN.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/MAINTENANCE_GARMIN.md) · [MAINTENANCE_DASHBOARD.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/MAINTENANCE_DASHBOARD.md) · [SECURITY.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/SECURITY.md) · [MINDSET.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/MINDSET.md) · [REFERENCE_INVARIANTS.md](REFERENCE_INVARIANTS.md)

This document describes both the software architecture and the development
process side by side, deliberately. Neither makes full sense without the
other: the architecture (sole-write-authority, the broker pattern) exists
*because* the process enforces it; the process only makes sense in light of
the architecture it protects. Garmin Local Archive is built by a developer
with no prior Python background, working through an AI coding assistant —
this document is both the architectural reference and the record of the
discipline that keeps a project built this way maintainable over hundreds
of releases.

---

## Contents

**Part I — Architecture**

1. [Architecture overview](#1-architecture-overview)
2. [Core design principles](#2-core-design-principles)
3. [Forbidden actions — hard rules](#3-forbidden-actions--hard-rules)
4. [Data pipeline — Garmin](#4-data-pipeline--garmin)
5. [Data pipeline — Context](#5-data-pipeline--context)
6. [Dashboard pipeline](#6-dashboard-pipeline)
7. [Data silos and sole-write authority](#7-data-silos-and-sole-write-authority)
8. [Quality model](#8-quality-model)
9. [Threading discipline](#9-threading-discipline)
10. [Security and token management](#10-security-and-token-management)
11. [Build targets](#11-build-targets)
12. [garmin_config.py — coupling risk](#12-garmin_configpy--coupling-risk)
13. [garmin_app_controller.py — the bridge between GUI and pipeline](#13-garmin_app_controllerpy--the-bridge-between-gui-and-pipeline)

**Part II — Development Process**

14. [Test suite](#14-test-suite)
15. [Session workflow](#15-session-workflow)
16. [Anchor delivery format](#16-anchor-delivery-format)
17. [Roadmap overview](#17-roadmap-overview)

---

---

# Part I — Architecture

---

## 1. Architecture overview

The project is organized into **five layers**. No layer crosses its own
responsibility boundary.

```
┌─────────────────────────────────────────────────────┐
│  GUI / App  (garmin_app_base.py + Panels)           │
├─────────────────────────────────────────────────────┤
│  Export Layer  (dashboards/ · layouts/)             │
├─────────────────────────────────────────────────────┤
│  Broker Layer  (maps/health_map · maps/context_map  │
│                 · maps/gateway_map · maps/mcp_map)  │
├──────────────────────────┬──────────────────────────┤
│  Garmin Pipeline         │  Context Pipeline        │
│  (garmin/)               │  (context/)              │
├──────────────────────────┴──────────────────────────┤
│  Local data  (garmin_data/ · context_data/)         │
└─────────────────────────────────────────────────────┘
```

**MCP Server:** `clients/mcp_server.py` runs as its own standalone
process outside this layer diagram — not part of the GUI/App layer, not a
layer of its own. It enters the Broker Layer exclusively through
`maps/mcp_map.py`, the same entry-point principle the GUI/App layer uses
via `health_map`/`context_map` — same rule, different process.

**No cross-connections between layers** — neither the Garmin pipeline nor
the Context pipeline ever reaches directly into dashboards; dashboards
never read the filesystem directly, only through a broker. The MCP Server
is not a sixth layer but an external consumer alongside the GUI/Export
layer that enters the Broker Layer exclusively through
`gateway_map`/`mcp_map` — no direct pipeline access, no write access.

`maps/gateway_map.py` adds a selective cross-domain entry point to the
Broker Layer, for consumers that don't know at runtime which domain owns a
given field. `maps/mcp_map.py` is the first real consumer of this path — a
pure, stateless protocol translator for the MCP Server, with no routing
logic of its own. Named specialists (dashboards) still import
`health_map`/`context_map` directly — `gateway_map` doesn't replace that,
it complements it for the narrow case of external/aggregating consumers.
Details: `REFERENCE_BROKER.md`.

`maps/metadata_map.py` reads archive state files directly — unlike
`health_map`/`context_map`, which route onward to per-source registries,
there is no source fan-out here. This is not a violation of "specialists
never read directly" — `metadata_map` itself is the broker, not a
specialist bypassing one. It's wired in via
`gateway_map.get_metadata(kind)`, kept separate from `gateway_map.get()`.

---

## 2. Core design principles

### Sole-Write-Authority

Every file owner is **exclusive**. No other module writes to its
directory.

| Module | Sole Write Authority |
|---|---|
| `garmin_writer.py` | `raw/` and `summary/` |
| `garmin_quality.py` (facade → `quality/`) | `quality_log.json` and `device_table.json` |
| `garmin_security.py` | `garmin_token.enc` and `garmin_token_log.json` (an observation-only file — no credentials or token content, see `REFERENCE_GARMIN.md`) |
| `garmin_source_writer.py` | `garmin_data/source/` and `source_api_log.json` |
| `garmin_backup.py` | `garmin_data/backup/raw/` + `backup/log/` |
| `garmin_backup_source.py` | `garmin_data/backup/source/` |
| `garmin_force_refetch.py` | `garmin_data/backup/force_refetch/` |
| `garmin_mirror.py` → `garmin_container.py` | `mirror.gla` |
| `context_writer.py` | `context_data/` |

Violations of this invariant are regressions, not technical debt.

### Leaf-Node Isolation

Modules with no project dependencies (standard library only) are called
Leaf Nodes:
- `garmin_utils.py`, `garmin_validator.py`, `garmin_source_quality.py`
- A Leaf Node never imports another project module
- Guarantees no circular dependencies and fully isolated testing

### Plugin Principle

`weather_plugin.py` and `pollen_plugin.py` contain **metadata only**
(endpoints, field names, file prefixes). No executable logic. A new
context plugin means a new plugin file — no change to the collector or
writer.

### Broker Pattern

Dashboard specialists **never** read the filesystem directly. They only
ever ask `health_map` (Garmin data) or `context_map` (context data). The
brokers know where data lives; the specialists don't.

`gateway_map` is not a third path for specialists, but a selective,
additional broker for cross-domain/external consumers (e.g. `mcp_map`)
that decide at runtime which domain they need. Named specialists with a
fixed domain need stay on `health_map`/`context_map`.

### Evaluate ≠ Decide

Tools report; humans decide. No hard stop in background pipelines —
degraded mode is always preferred over aborting.

### Silent failure as the primary audit lens

A tool that exists to catch Garmin's own silent data loss must not itself
produce silent data loss. Every change is evaluated against this
principle.

---

## 3. Forbidden actions — hard rules

Violations of these rules are **regressions**, not technical debt. No
exceptions without explicit documentation.

### Architecture

- **No module writes to a directory owned by another** — sole-write-authority is absolute
- **No Leaf Node imports another project module** — standard library only
- **No dashboard specialist reads the filesystem directly** — always through `health_map` / `context_map`
- **No submodule of `garmin/quality/` acquires `QUALITY_LOCK` itself** — that's exclusively the orchestrator's job
- **No background worker touches widgets** — file-only; UI updates only via `_dispatch()`
- **No module injects a stop event via `module.__dict__`** — only via `set_stop_event(ev)`

### Data integrity

- **`high` is never overwritten by a worse quality label** — the downgrade guard is non-negotiable
- **`quality_log.json` is never mutated without `QUALITY_LOCK`** — load-modify-save always under lock, **held continuously from load to the final save** — never load, release, then re-acquire per individual operation
- **`source/` is never written by bulk import** — live API responses only
- **A `source/` file with `intraday_present=True` is never overwritten** — conservative guard, first good capture wins
- **No hard stop in background pipelines** — degraded mode is always preferred over aborting

### Development process

- **No build order without a current dependency scan and a current scope snapshot** of the affected modules (see §15)
- **No code anchor without first reading the target file** — never reconstructed from memory
- **`garmin_app_standalone.py` is never treated as "identical to garmin_app.py"** — always written out explicitly
- **No release without a clean lint pass and a fully green test suite**

---

## 4. Data pipeline — Garmin

### API sync path

```
Garmin Connect API
      │
      ▼
garmin_api.py           — fetch_raw(): every endpoint, (raw, failed_endpoints)
      │
      ▼
garmin_source_writer.py — write_source(): stores the unmodified API response
      │                   in source/, before any pipeline processing
      │                   ↳ calls garmin_source_quality.assess_source() internally
      │                     conservative guard: "freeze-when-present" —
      │                     never overwritten by a degraded response
      ▼
garmin_validator.py     — validate(): structural check against garmin_dataformat.json
      │                   fail-closed: schema absent → status="critical"
      ▼
garmin_normalizer.py    — normalize(raw, source="api"): guarantees {"date": ...}
      │                   summarize(): compact dict carrying schema_version
      ▼
garmin_quality.py       — assess_quality(): "high" / "standard" / "failed"
      │                   assess_quality_fields(): per-endpoint label
      ▼
garmin_writer.py        — write_day(): writes raw/ and summary/
      │                   backup after every successful write (lazy import)
      ▼
garmin_quality.py       — _upsert_quality() + _save_quality_log()
                          atomic resume point: every day is its own checkpoint
```

### Bulk import path (GDPR export)

```
Garmin GDPR export ZIP / folder
      │
      ▼
garmin_import.py       — load_bulk(): iterator over days, parse_day()
      │
      ▼
garmin_validator.py    — validate() (identical to the API path)
      │
      ▼
garmin_normalizer.py   — normalize(raw, source="bulk")
      │                  special case: remaps HR aggregates from user_summary → heart_rates
      │                  no intraday data in the GDPR export → quality is always standard/failed, never high
      ▼
garmin_quality.py      — assess_quality(), assess_quality_fields()
      │
      ▼
garmin_writer.py       — write_day() — identical format to API data
      │
      ▼
garmin_quality.py      — source="bulk" recorded in the quality log entry
```

### Self-healing loop

On a schema-version mismatch (`CURRENT_SCHEMA_VERSION` in
`garmin_normalizer.py`):
1. The collector detects outdated summaries via the `schema_version` field
2. `garmin_writer.read_raw()` loads the existing raw file
3. The normalizer re-summarizes from raw — no API call needed
4. The user sees a backup dialog before the migration runs

### Downgrade protection

`garmin_collector.main()` checks before every write whether the new API
result is qualitatively worse than what's already stored. **The write is
blocked** if the new result is inferior. This guard sits in the
collector, not in the writer or the quality module.

---

## 5. Data pipeline — Context

Context data (weather, pollen, air quality) follows the same shape as the
Garmin pipeline, structurally simpler since there is no bulk-import path
and no intraday concept:

```
External API (Open-Meteo / Brightsky-DWD)
      │
      ▼
{source}_plugin.py       — metadata only: endpoints, field names, aggregation rules
      │
      ▼
context_api.py           — fetch(): chunked requests, retry with backoff,
      │                     per-source parser (hourly-to-daily aggregation
      │                     where applicable)
      ▼
context_writer.py        — write(): sole owner of context_data/, atomic write
```

Each context source is a self-contained plugin — adding a new one means
adding a new plugin file, never touching the collector or writer. The
plugin itself carries no executable logic beyond declaring what to fetch
and how to aggregate it; `context_api.py` is the only place that actually
calls out to the network.

---

## 6. Dashboard pipeline

```
dashboards/{name}_dash.py   — specialist: declares META, fetches data via
      │                        health_map/context_map, returns a neutral dict
      ▼
layouts/dash_runner.py      — orchestrates: scans available specialists,
      │                        drives the build for the requested formats
      ▼
layouts/dash_plotter_*.py   — plotter: renders the neutral dict to one
                               output format (HTML, Excel, JSON) — no
                               knowledge of where the data came from
```

A specialist never reads a file directly and never writes an output file
itself — it hands a plain dict to a plotter, which is the only thing that
touches disk on the output side. This separation is what lets new output
formats or new dashboards be added independently of each other.

`dashboards/custom_dash_builder.py` is the one deliberate exception to the
naming convention: it builds an in-memory specialist object at runtime
from a free field selection, rather than being a static `*_dash.py` file
discovered by `dash_runner.scan()`.

---

## 7. Data silos and sole-write authority

Three parallel silos under `garmin_data/`, each derived from the one
before it by a real transformation — not a copy:

| Silo | Content | Derived from |
|---|---|---|
| `source/` | Unmodified raw API response, written before any pipeline processing | Nothing — this is the ground truth |
| `raw/` | Canonical, normalized form (`garmin_normalizer.normalize()`) — guarantees a consistent shape (e.g. a `date` field) regardless of which path (API or bulk import) produced it | `source/`, via `normalize()` |
| `summary/` | Compact, derived daily values (`summarize()`) | `raw/`, via `summarize()` |

Reconstruction only ever flows forward through this chain: a lost
`summary/` file is rebuilt from `raw/`; a lost `raw/` file can be rebuilt
from `source/` by replaying it through `normalize()` again — never the
other way around.

Conservative guard for `source/` — "freeze-when-present":

| Existing file | New response | Action |
|---|---|---|
| none | any | write |
| intraday absent | present | write |
| intraday absent | absent | write (refresh, harmless) |
| intraday present | present | skip (first good capture wins) |
| intraday present | absent | skip_warn (degradation blocked) |

### Silo reconciliation (`garmin_silo_check.py`)

Read-only drift detection. Recognizes four inconsistency categories:

- `raw_without_quality` — a raw file with no quality-log entry
- `source_without_raw` — a source file with no matching raw file
- `summary_without_raw` — a summary with no raw file
- `raw_without_summary` — a raw file with no summary

**No repair inside the silo check itself** — pure detection. Repair runs
through `garmin_silo_repair.py` (`repair_silos()`, headless-callable, not
a Leaf Node), which itself delegates to the existing owner modules
(`garmin_writer`, `garmin_quality`, `garmin_normalizer`) and never writes
directly.

---

## 8. Quality model

### Quality labels

| Label | Meaning |
|---|---|
| `high` | Intraday data present (HR curve, stress timeline, Body Battery) |
| `standard` | Full daily summary, no intraday |
| `failed` | No usable data |

**Downgrade protection:** `high` stays `high`. `_upsert_quality()` never
writes a worse label over a better one.

### quality_log.json

Checksum-protected via SHA-256 over stable core fields. On a mismatch:
auto-restore from `backup/log/` plus a yellow warning label in the GUI.

Full entry format, checksum fields, and migration paths:
→ [REFERENCE_GARMIN.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/REFERENCE_GARMIN.md)

### Facade pattern (`garmin_quality.py`)

Implementation lives in `garmin/quality/` submodules (`_io`, `_assess`,
`_scan`, `_maint`, `_stats`). `garmin_quality.py` re-exports every public
symbol — callers always import from `garmin_quality`, never from a
submodule directly.

---

## 9. Threading discipline

### QUALITY_LOCK

`QUALITY_LOCK = threading.Lock()` — defined in `garmin_quality.py`.

**Required:** every load-modify-save cycle on `quality_log.json` must hold
the lock.

```python
with quality.QUALITY_LOCK:
    data = quality._load_quality_log()
    quality._upsert_quality(data, ...)
    quality._save_quality_log(data)
```

Submodules of `garmin/quality/` never acquire the lock themselves — that's
the job of whichever module is orchestrating the call. Several modules
acquire `QUALITY_LOCK` directly, each holding it continuously from load to
the final save, as required by the hard rule in §3.

### Worker rule

- Background workers: file-only — never touch widgets
- `sys.excepthook` (main thread): fail-loud, writes a crash log, shows a message box, `exit(1)`
- `threading.excepthook` (workers): fail-isolated, writes a crash log, the thread dies, the GUI stays up

### Lockless read

`quality_log.json` is written atomically via `os.replace()` — a
concurrent read always sees a complete file. Lockless reads are therefore
safe.

### Timer safety

The background timer and bulk import must never write to `raw/` and
`summary/` at the same time. The timer is paused before an import starts
and resumed in a `finally` block afterward.

---

## 10. Security and token management

### Token encryption

`garmin_security.py` stores the token encrypted. Principles:
- Symmetric encryption (AES-GCM)
- The encryption key lives in Windows Credential Manager (WCM), never on disk
- The plaintext token is deleted from the temp directory immediately after login
- Library-side write-back attempts are actively blocked

Algorithms, iteration counts, and implementation detail:
→ [REFERENCE_GARMIN.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/REFERENCE_GARMIN.md) · [SECURITY.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/SECURITY.md)

### Credential redaction in logs

`RedactFilter` is registered at every logging entry point. Credentials
never appear in log files.

### Plaintext archive (a deliberate choice)

`raw/`, `summary/`, and `context_data/` are plaintext JSON — **no
at-rest encryption**. This is an explicit trade-off: openness and
readability with any tool are core goals of the project. Users who need
encryption at rest use the AES-256-GCM-encrypted Mirror export instead.

---

## 11. Build targets

Three build targets, each serving a different audience:

| Target | Description | Requires |
|---|---|---|
| T1 | Dev mode, run from source | Python + dependencies |
| T2 | Standard EXE | Python 3.10+ on the target machine |
| T3 | Standalone EXE | Nothing — fully self-contained |

`build_manifest.py` is the single source of truth for which scripts and
data files go into each target — both build scripts (`compiler/build.py`
for T2, `compiler/build_standalone.py` for T3) import their script and
hidden-import lists from it rather than maintaining their own copies.
`validate_scripts()` runs before PyInstaller starts, checking that every
required file exists and contains an expected function/class signature —
the build aborts immediately on a mismatch rather than producing a broken
EXE that fails at runtime.

---

## 12. garmin_config.py — coupling risk

`garmin_config.py` is the most connected module in the project: roughly
30 direct importers. That makes it the primary structural coupling risk.

### What that means

Any change to `garmin_config.py` — a new constant, a renamed path, a
changed default — potentially affects every one of those importers. The
module is de facto a global namespace for the whole project. No other
module comes close to this many dependents.

This is not a bug, it's a deliberate choice: `garmin_config` is the only
place environment variables are read and resolved into paths. The
alternative — scattered environment-variable reads across every module —
would be worse.

### What this means for changes

Before any change to `garmin_config.py`:

1. **Run a full dependency scan** — shows every current importer, not just the expected ones
2. **Check backward compatibility** — renaming a constant breaks all importers simultaneously; prefer introducing an alias and deprecating the old name
3. **Respect the lazy-import pattern** — several modules (`garmin_security.py`, `garmin_source_writer.py`) import `garmin_config` lazily, *inside* functions, not at module level. Reason: the test suite sets `GARMIN_OUTPUT_DIR` and calls `importlib.reload(cfg)` — a module-level import would freeze the wrong path. This pattern is mandatory for any module that needs to be reloaded in a test context.
4. Prefer additive changes (new constant, new optional parameter) over renames or removals wherever possible.

---

## 13. garmin_app_controller.py — the bridge between GUI and pipeline

`garmin_app_controller.py` is the sole permitted bridge between the GUI
layer and pipeline logic that would otherwise require the GUI to reach
into `garmin/` internals directly. It holds no GUI framework imports of
its own — pure functions, return values and callbacks only — but is
explicitly allowed a small, documented set of direct reads
(`quality_log.json` for status displays, `device_table.json` for the
device list) rather than going through the full broker chain, since these
are GUI-status reads, not pipeline writes. Each such exception is marked
`INTENTIONAL DIRECT READ` in the code and listed under Documented
Exceptions in `REFERENCE_GARMIN.md`.

Panels never call pipeline modules directly for anything beyond these
documented reads — every write-triggering action (sync, repair, device
rename) goes through the controller, which is what keeps the GUI
replaceable (as happened during the PyQt6 migration) without touching
pipeline code.

---

---

# Part II — Development Process

---

## 14. Test suite

Eight suites cover the full pipeline, no network or GUI required except
where noted:

| Suite | Scope |
|---|---|
| `test_local.py` | Garmin pipeline (normalizer, writer, quality, sync, collector) |
| `test_local_context.py` | Context pipeline (external APIs mocked) |
| `test_dashboard.py` | Dashboard pipeline (maps, specialists, plotters) |
| `test_broker.py` | Broker layer (`health_map`/`gateway_map` routing, `metadata_map`) |
| `test_mcp.py` | MCP layer (`mcp_map` protocol translation) |
| `test_app_logic.py` | App layer (entry points, path resolution) |
| `test_qt_app.py` | PyQt6 App layer (run via `pytest`) |
| `test_static.py` | Lint + security scan + AST-based regression guards |

Expected coverage varies by layer — the pipeline core (`garmin/`) is
tested densely since it's the critical data path; the GUI layer is
structurally harder to test and carries deliberately lighter coverage.
Entry points that run only as a subprocess (`garmin_collector.main()`)
show near-zero direct coverage in a coverage report — a structural
limitation of the subprocess model, not a real gap; the same code path is
exercised end-to-end by the E2E tests in `test_local.py`.

A pre-build test chain runs the pipeline and static-analysis suites as a
hard gate before either build target is produced; a smaller post-build
chain validates the build's own output afterward. `test_qt_app.py` is run
separately via `pytest`.

---

## 15. Session workflow

Each unit of work runs through a strict phase sequence — **Evaluate →
Analyze → Build Order** — no phase skipped, no code changed without an
explicit build order following a confirmed analysis. This mirrors the
project's own hard rule in §3: no build order without a current
dependency picture of the modules the change will touch.

### Required steps before any build order

```
1. Load project context relevant to the session's stated goal.
2. Dependency scan: a pattern- and AI-assisted scanner runs against the
   codebase for the constants/modules the session is expected to touch,
   producing a report of matches that plausibly need attention.
   Obvious misclassifications are filtered before anything is treated
   as confirmed.
3. Scope snapshot: from the confirmed matches, a symbol map (function/
   method signatures, constants, class attributes) is generated for
   every file the change might touch — not a substitute for reading the
   target file before writing an anchor, but a reduction in the risk of
   wrong cross-file assumptions about files that aren't directly edited.
4. Cross-reference check: the affected sections of the reference and
   maintenance documentation are checked against the confirmed scope.
5. Only after steps 1–4: the build order is issued.
```

### Multi-model review gate

For cross-module refactors or anything touching security-relevant code,
independent review from more than one AI model is required, not optional.
The intersection of findings across models is treated as the
highest-priority signal. Each finding is still evaluated critically
before being adopted — a flagged issue isn't automatically correct just
because a model raised it.

### After a build order

```
Anchor delivered → applied → tests run → documentation updated
(changelog, roadmap, affected reference/maintenance sections, README)
→ lint clean → next session's starting context prepared
```

### Tooling

The scanning, anchor-application, and dependency-mapping tools that
support this workflow are maintained as a separate, general-purpose
toolkit — [`GLA-NeedfulThings`](https://github.com/Wewoc/GLA-NeedfulThings) —
kept independent of this repository so the tooling can be reused across
projects. Diagnostic tooling for deeper runtime-behavior verification
(the "netz2" scenario scripts) lives there too, under
[`netz2_diagnostics`](https://github.com/Wewoc/GLA-NeedfulThings/tree/main/netz2_diagnostics).

### Required steps before any release build

1. Lint check — zero errors
2. Full test suite — all green
3. `version.py` updated to the new version number

---

## 16. Anchor delivery format

Changes to existing files are delivered as a precise, parseable diff
format that both a human and a tool can apply mechanically — the AI never
touches the filesystem directly.

### Format

```markdown
## FILE: path/to/file.py

### OLD
```python
# exact code as it currently stands in the file
```

### NEW
```python
# replacement code
```
```

**Rules:**

- `OLD`/`NEW` labels sit outside the code fences, as plain text
- Code fences are mandatory — a missing fence is a parser error
- Multiple anchors per file are allowed, each as its own `OLD`/`NEW` pair
- Deletion: the `NEW` block contains only `#DELETE`
- **The target file is always read before an anchor is written** — never reconstructed from memory
- `garmin_app_standalone.py` is always written out explicitly, never treated as identical to `garmin_app.py`
- Full-file delivery only above a significant change threshold or on explicit request

### Applying anchors

A two-pass parser applies these mechanically:

1. **Pass 1 — Locate:** find every `OLD` block in every referenced file
2. **Pass 2 — Write:** apply every `NEW` block

Overlap detection catches `OLD` blocks that overlap each other — a
reliable signal that the anchor itself has a bug. The parser tool itself
is always delivered as a complete file, never as an anchor delivery
against itself.

---

## 17. Roadmap overview

> Authoritative source: [ROADMAP.md](https://github.com/Wewoc/Garmin_Local_Archive/blob/main/src/docs/ROADMAP.md) in the repository.

### Architectural direction (stable)

Planned development follows a sequence of increasing complexity:

| Stage | Focus | Architectural significance |
|---|---|---|
| v1.6.x | Dependency audit · render registry · live dashboard | Internal consolidation before expansion |
| v1.7.x | MCP Server + SQLite proxy | LLM access to the archive via the Model Context Protocol; `mcp_map.py` as a pure protocol translator over `gateway_map.py` |
| v1.8 | FIT pipeline | A new, independent pipeline alongside the health pipeline; `fit_map.py` as a peer broker |
| v2.0 | Multi-source architecture | Garmin + other sources, each fully isolated with its own silos |

**Invariant:** every new pipeline follows the same principles as the
Garmin pipeline — sole-write-authority, Leaf-Node isolation, the broker
pattern. The v1.x work is deliberate groundwork for v2.0.

---

## Appendix: Garmin pipeline module quick reference

| Module | Role | Leaf Node |
|---|---|---|
| `garmin_collector.py` | Orchestrator — decides, delegates, coordinates | No |
| `garmin_config.py` | Configuration, environment variables, paths (~30 importers — highest coupling risk) | No |
| `garmin_api.py` | Login + all Garmin Connect API calls | No |
| `garmin_security.py` | Token encryption, AES-256-GCM | No |
| `garmin_validator.py` | Structural validation against `garmin_dataformat.json` | **Yes** |
| `garmin_normalizer.py` | Canonical schema + `summarize()`. Schema version documented in `REFERENCE_GARMIN.md` | No |
| `garmin_quality.py` | Facade: quality assessment, sole owner of `quality_log.json` | No |
| `garmin_sync.py` | Determines missing days | No |
| `garmin_writer.py` | Sole owner of `raw/` + `summary/` | No |
| `garmin_import.py` | GDPR export importer | No |
| `garmin_source_writer.py` | Sole owner of `source/` + `source_api_log.json` — writes files, calls `garmin_source_quality` for the guard decision | No |
| `garmin_source_quality.py` | Sole owner of the **assessment logic** (not the files) — no write access, called by `garmin_source_writer` | **Yes** |
| `garmin_silo_check.py` | Read-only drift detection | **Yes** |
| `garmin_silo_repair.py` | Headless-callable repair core for the four silo-drift categories — delegates to owner modules, never writes directly | No |
| `garmin_backup.py` | Sole owner of `backup/raw/` + `backup/log/` | No |
| `garmin_backup_source.py` | Sole owner of `backup/source/` | No |
| `garmin_force_refetch.py` | Sole owner of `backup/force_refetch/` — per-day snapshot/restore for the deliberate Force-Refetch freeze-guard bypass | No |
| `garmin_mirror.py` | Mirror operation, delegates to `garmin_container.py` | No |
| `garmin_import_mirror.py` | Mirror-import orchestrator (never writes directly) | No |
| `garmin_utils.py` | Shared utilities: date parsing, filenames | **Yes** |
| `garmin_merge.py` | Additive field-merge logic for backfill operations — `merge_field()` | **Yes** |
| `crash_handler.py` | `sys.excepthook` + `threading.excepthook` (standard library only) | **Yes** |

---

*This document covers architecture invariants and principles — these
change rarely. Version-specific detail (module APIs, schema versions,
test counts, current roadmap status) always belongs in the linked
reference documents.*
