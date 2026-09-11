# Garmin Local Archive — MCP Server Reference

Technical reference for the MCP Server (`clients/mcp_server.py`,
`maps/mcp_map.py`) — the standalone MCP protocol layer that exposes
archived data to LLM clients. Split out of `REFERENCE_BROKER.md`
(2026-09-11) once the MCP section grew past half that file's length;
see that file for the underlying Broker Layer (`health_map`/
`context_map`/`gateway_map`) this server sits on top of. For shared
paths, constants, and project structure see `REFERENCE_GLOBAL.md`.

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
Three unknown-field outcomes, checked in this order (superseded by
`v1.7.1.12` below — retained here for the historical progression):
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
against the registry queried at request time. `query_health`/`get_health_range()` had the same underlying gap (an
unregistered health field returned the same silent empty result as a
data-free valid one) — addressed in `v1.7.1.9` (see that entry below),
not pulled into this fix.

**(v1.7.1.9)** `query_health()` gained the same three-outcome
unknown-field detection as `query_context()` above (`v1.7.1.4`),
mirrored rather than shared code — checked before the `_route_query()`
switch, so it applies regardless of branch. Difference from
`query_context`'s version: outcome 1 (unambiguous near-match) resolves
against the live health field registry
(`mcp_map.list_available_fields(domain="health")["fields"]["health"]
["garmin"]`) instead of the context one; outcome 2 (domain confusion)
checks the field against the FULL context field registry (all sources
flattened via `.values()`) and, if found, returns an error naming
`query_context` — the mirror image of `query_context`'s existing
check against the health registry. A `_CONTEXT_CATEGORY_BUNDLES` key
(e.g. `"weather"`) reaching `query_health()` is treated as outcome 2
as well (a bundle name is a `query_context`-only concept, never a
registered health field) — checked first, before the registry lookup,
for the same reason `query_context()` checks its own bundle key
before its unknown-field block. Outcome 3 (generic error) is
unchanged in shape, `did_you_mean` sourced from the health registry.

**Verified against a real before/after test run** (2026-09-05,
`health_fallback_questions.py`, 78 questions × 5 local models, 390
cases each run): silent wrong answers (empty result combined with the
model denying or hallucinating a value) fell from 35.9% to 8.4% of all
cases; `field_correct` rose from 26.4% to 33.6%; no regressions in
previously-correct cases. Two apparent anomalies in the raw category
counts were investigated and both traced to causes unrelated to this
fix: (a) the `field_wrong_but_real_data` category (a model picking a
completely unrelated but real, registered field) rose from 1.0% to
2.6% between runs, but 8 of the 10 cases in the new run involve the
SAME questions/models choosing a DIFFERENT wrong field than in the
prior run with no `fallback` flag set on the tool call — ordinary
LLM sampling variance between two independent runs, not something this
fix causes or could prevent (it never reaches the near-match check,
since the wrongly-chosen field is itself valid); (b) the `uncertain`
category rose from 15.1% to 32.1%, traced entirely to the evaluation
script (`evaluate_health_fallback_results.py`) not yet recognizing two
new success patterns this fix introduces (a bare "unknown field" error
with no `did_you_mean`, and a resolved typo without a `fallback: true`
key in the response) — not a server-side issue.

**Known gap, confirmed NOT fixable by cutoff tuning (2026-09-05,
simulated against all 26 registered health fields):** short natural
words that are a genuine prefix of a longer field name (e.g. `"steps"`
vs. `"steps_series"`, ratio 0.588; also affects `"spo2"`, `"hrv"`,
`"hill"`, and the two `sleep_score_*` fields) fall well under any
defensible `difflib` cutoff — confirmed down to `cutoff=0.7`, at which
point other fields (`sleep_rem_pct` vs. `sleep_score`) start producing
ambiguous multi-candidate matches that would block outcome 1 entirely.
This is a structural limit of `difflib.SequenceMatcher` on short-prefix-
vs-long-suffix pairs, not a tunable parameter — cutoff tuning has
reached what it can achieve for this field set. Confirmed the fallback
mechanism does not make this worse: the one traceable case
(Hermes3, previously the field_wrong_but_real_data reference case in
`AKTIONSPLAN_v1.7.1.9_health_fallback.md`, field `"steps"`) now
correctly reaches outcome 3 (honest "unknown field" error) instead of
answering with an unrelated field's value, though still without a
useful `did_you_mean` suggestion. Addressed via an explicit
synonym/alias mapping, same version (see below) — verified against the
live field registry rather than the candidate list above, which was
reconstructed from the 78 test questions, not read from
`mcp_map.list_available_fields()` directly.

**Alias mapping and sleep_score fan-out (same version, second work
session):** `HEALTH_FIELD_ALIASES` in `clients/mcp_server.py` —
`{"steps": "steps_series", "hrv": "hrv_last_night", "hill":
"hill_score"}` — checked in `query_health()` before outcome 1 above (an
alias hit is more certain than a near-match and should not have to
pass through it). All three verified unambiguous against the live
25-field registry (`REFERENCE_BROKER.md`'s own "Field index" table)
before being added — each is the only field starting with that
prefix, no collision.

`"spo2"` was considered and deliberately excluded, unlike the three
above — a real collision exists between `spo2_avg` (daily) and
`spo2_series` (intraday), both registered. Analysis: `query_health()`'s
`resolution` parameter is accepted for forward compatibility but not
currently used to pick between two resolutions of the same field
(confirmed via this file's and the function's own docstring — no field
in the archive previously offered both, so `spo2` would be the first);
wiring it up now would be a behavior change to a previously-inert
parameter, not the use of an existing signal. Independently,
`resolution` is empirically unreliable as a disambiguation signal even
if wired up — 335 of 465 tool calls (72%) in the Lauf 7 test data omit
it entirely, so a resolution-based alias would silently default most
intraday-intended requests to the daily value, reproducing exactly the
kind of silent wrong-field answer this fallback mechanism exists to
prevent. The project's one existing precedent for "one word means
several fields" (`_CONTEXT_CATEGORY_BUNDLES`) resolves ambiguity via
fan-out (collect all candidates) rather than 1:1 selection — applying
that here would mean querying and returning both `spo2_avg` and
`spo2_series` together, a larger, new architectural element judged out
of scope for this fix. `"spo2"` therefore stayed on outcome 3 (generic
error) at the time — superseded by the dedicated ambiguity mechanism
introduced in `v1.7.1.12`, see below.

`sleep_score` required a third, different mechanism from the other
four candidates: it is itself already a valid, registered field (see
`REFERENCE_BROKER.md`'s "Field index"), so unlike `"steps"`/`"hrv"`/
`"hill"`/`"spo2"` it never reaches any of the unknown-field outcomes at
all — the near-match check, domain-confusion check, and generic error
all require `field` to be unrecognized first. A dedicated fan-out
branch in `query_health()` checks for the exact string `"sleep_score"`
before the bundle check (the earliest point in the function) and, when
matched, queries `sleep_score`, `sleep_score_feedback`, and
`sleep_score_qualifier` individually — three separate calls through
the same `_route_query()` sqlite/live switch used everywhere else, no
bypass data-access path, same principle as the `v1.7.1.5` bundle
mechanism below. Results are merged into the same flattened
`{field: {"values": ...}}` shape `_resolve_context_bundle()` already
produces, matching `get_health_range()`'s own real return shape
(confirmed by reading `mcp_sql.py` directly — see "Bug found and
fixed" below) — no third shape introduced, `_enrich_with_units()`
already recognizes this as its documented "already-flattened shape"
case and needs no change. `_meta.field_resolved_from` is set to
`"sleep_score"` to mark that fan-out occurred; no `_meta.field_used`,
since — unlike the 1:1 alias case above, where the substitution would
otherwise be invisible — all three delivered field names are already
the result's own dict keys. A direct, targeted call to
`sleep_score_feedback` or `sleep_score_qualifier` is unaffected:
neither string matches the fan-out's exact-match check, so both
continue to return exactly the one requested field, unchanged from
before this addition.

**Bug found and fixed before verification (2026-09-06):** the first
implementation of the sleep_score fan-out wrongly assumed
`mcp_sql.get_health_range()` nests its per-field result under an
additional `{"garmin": {...}}` key — confusing this call's return
shape with `health_map.get()`'s own live-side contract, which does
nest under a source name. `get_health_range()` already reads through
that layer itself before returning (see `REFERENCE_BROKER.md`'s own
`get_health_range()` entry, "v1.7.1.1 Bug-C correction") and returns
`{"health": {field: {"values": ...}}}` directly. The wrong assumption
meant every extraction inside the fan-out loop produced `None`, so all
29 sleep_score calls in the first post-implementation test run
(informally "Lauf 8", discarded as void) returned an empty result
despite `_meta.field_resolved_from` being set correctly — reproducible
across all 5 models and all affected question IDs, not model sampling
noise. Root cause confirmed by reading `mcp_sql.py` directly rather
than continuing to reason from documentation fragments; the same wrong
assumption had also been built into the test mocks for this branch, so
they could not have caught the bug either — both fixed together.
156/156 unit tests green after the fix.

**Verified against a real before/after test run (Lauf 7 vs. Lauf 9 —
the discarded Lauf 8 attempt above is not a valid comparison point):**
`field_correct` rose from 176 to 180 (of 390), `field_wrong_empty_honest`
fell from 79 to 58. `hrv` resolved correctly in 3 of 4 previously-failing
cases; `steps` in 5 of 7 (the remaining 2 attributed to model timeouts,
unrelated to the alias mechanism); the one real `hill` test case
resolved correctly to `hill_score` (no data point existed for that day
in the archive — not a mapping defect). `spo2` unchanged, as intended —
the one real `spo2` call stayed on the generic unknown-field error, no
unintended resolution. `sleep_score` fan-out returned all three fields
with real data in every case checked. A rise in `error_or_timeout`/
`no_tool_call` counts between the two runs was checked on a sample
basis and attributed to ordinary model sampling variance (timeouts,
wrong tool selection, date validation) unrelated to either the alias
mapping or the fan-out — not verified case-by-case; a future run
surfacing an alias or fan-out field within these categories would
warrant its own look rather than being assumed to be the same noise.

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
`{field: {...}}` directly under `"context"`. The sole naming collision
in the current registry between distinct sources, `wind_speed_max`
(registered by both `weather` and `brightsky` under different internal
keys and different values — Modell vs. Messstation, see
`context_map.py`'s naming-collision note), is resolved PER DAY, not
per whole field, when reached through this bundle path: for each date
in range, the first source in the bundle's priority list with a
non-`None` value for that specific day wins — a field's final
`values` array can therefore be stitched together from more than one
source across a range (e.g. brightsky for most days, weather filling
in a day brightsky has no data for). The winning source per
collision-day is recorded in `_meta.field_sources` (e.g.
`{"wind_speed_max": {"2026-03-01": "brightsky", "2026-03-02":
"weather"}}`) — only for fields that actually had more than one
candidate source in the bundle; a field copied through from a single
source (the normal case for `pollen`/`air`, and most `weather` fields)
gets no `field_sources` entry. **A direct field request
(`field="wind_speed_max"`) bypassed this tie-break entirely until
`v1.7.1.12` — see that entry below for the fix.**

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

**(v1.7.1.11)** Context-intraday raw/summary split (`pollen`/`brightsky`/
`airquality` — see `REFERENCE_CONTEXT.md`) added one `<field>_series`
entry per daily field to the context field registry. `_series` fields
flow through the exact same sqlite/live routing weiche as any other
context field — no field-name branching in front of `_route_query()`,
same principle `query_health()`'s own `steps_series` already
established: the field name itself (the `_series` suffix) is what
tells a caller which shape to expect (a single daily value vs. a full
timeseries), not a flag on the response. `clients/mcp_update.py::
_sync_context_days()` syncs the full, unfiltered field list — daily
and `_series` alike — into `mcp_context_days`, exactly like every other
context field; `query_context()` in `clients/mcp_server.py` has no
`_series`-specific branch left, direct-field and typo-resolution call
sites both fall straight through to the same `_route_query("context")`
switch every other field uses.

`_resolve_context_bundle()` is the one deliberate exception: it skips
any `source_field` ending in `"_series"` during collection — the
bundle mechanism answers a daily-value source-collision question (e.g.
`wind_speed_max`, weather vs. brightsky); at intraday resolution none
of the three affected sources ever has more than one candidate for the
same field, so the collision machinery has nothing to resolve. A
`_series` field remains individually queryable via `query_context()`
— never through a bundle name.

`mcp_sql.py`'s own functions are unchanged — `get_context_range()`
already handled the `{"date","value"}` vs. `{"date","series"}` shape
difference correctly without modification: neither shape is
interpreted there, only copied through per the field's own `"values"`
list, with `"source_resolution"` ("daily"/"intraday") as the signal a
caller uses to know which inner shape to expect. `mcp_sql.py` stays a
pure, field-agnostic access layer per the `v1.7.1.4` precedent
restated above.

Session 5 of the same version (2026-09-09, informally "Lauf 12/12b"):
the `difflib` cutoff for both `query_health()`'s and `query_context()`'s
outcome-1 near-match check was lowered from `0.8` to `0.65`, tested
empirically against `qwen3:14b`/`qwen2.5-coder:7b` (138 context
questions, 78 health questions). health `typo` hit rate rose from
5.0% to 75.0%; context `field_correct` rose by +9 (qwen3:14b)/+6
(qwen2.5-coder:7b) over cutoff 0.8. Trade-off found in the same test
run: 7 new, confirmed silent mismatches in the context half, all on
short/generic words (`humidity`, `pressure`, `air_pressure`,
`wind_speed`) matching a similarly-named but semantically different
field. `0.65` is the adopted production value — the 7 mismatches were
addressed via explicit aliases rather than reverting the cutoff, see
`v1.7.1.12` below.

**Cache rebuild note:** `mcp_context_days` is purely derived (never a
source of truth). Since `complete_sources`/`missing_sources` tracking
in `_sync_context_days()` is per-source, not per-field, a day already
marked complete under a pre-`v1.7.1.11` field list will not
automatically pick up its source's new `_series` fields on the next
incremental sync — the source is already "done" as far as that check
is concerned. `mcp_cache.db` must be deleted once after upgrading to
this version so the next full sync/boot-sync rebuilds every day's
`complete_sources` state against the current, `_series`-inclusive
field list.

**(v1.7.1.6)** `query_health()`, `query_context()` (both its direct-field
and its category-bundle path), and `list_available_fields()` gained an
explicit unit per field — closing the gap `REFERENCE_BROKER.md`'s own
"Field index" table already existed to bridge for a human reader, but
which the MCP tool schema itself never exposed to an LLM caller
(verified empirically against `qwen3:14b`/`qwen2.5-coder:7b`/
`mistral-nemo` — see `NOTES_v1716_session2.md` for the test
transcript). `query_health()`/`query_context()` results gain a
`"unit"` key alongside `"values"`/`"fallback"`/`"source_resolution"`
on every field-level dict, for both the SQLite and the live branch
identically (applied after the `_route_query()` switch, not before).
`list_available_fields()` gains an additive `"units"` key (flat
`{field_name: unit}`) alongside its existing `"fields"` key, which
itself keeps its original name-list shape unchanged. Unit values
transcribed from `REFERENCE_BROKER.md`'s own "Field index" table, no
new research — including the "no exceptions" rule (every field gets a
unit, including ones with no physical unit, e.g. `vo2max`/
`airquality_european_aqi` → `"—"`/`"index"`, never an omitted key) to
avoid a mixed state that would itself become a new source of LLM
misinterpretation.

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

---

## (v1.7.1.12) Context field-name resolution — alias tables, ambiguity rückfrage, domain-check ordering, wind_speed_max direct-path fix

Four related corrections to `query_health()`/`query_context()`'s
field-resolution logic, one production build (2026-09-10/11), split
across five delivery anchors. Grounded in the Lauf 11 test report
(138 context questions × 7 models) and the `v1.7.1.11` Session 5
cutoff finding above; three of the four were discovered mid-session
via the actual `test_mcp.py` unit-test run, not planned at session
start. Full per-candidate reasoning (including rejected candidates
and deferred decisions) lives in `NOTES_v1.7.1.12.md` — this entry is
the settled contract, not the working notes.

**1. `CONTEXT_FIELD_ALIASES`** (36 entries) — same mechanism as
`HEALTH_FIELD_ALIASES` above, checked in `query_context()` before the
`_CONTEXT_CATEGORY_BUNDLES` check. Four entries are the confirmed
`cutoff=0.65` silent-mismatch fixes from `v1.7.1.11` Session 5
(`humidity`→`humidity_avg`, `pressure`→`pressure_avg`,
`air_pressure`→`pressure_avg`, `wind_speed`→`wind_speed_max`); the
remaining 32 are individually re-verified requested→expected
discrepancies from the Lauf 11 Appendix A candidate list. Four
candidates from that same list were deliberately NOT added —
`"ozone"` (shares the same daily/series ambiguity as item 2 below,
inconsistent to resolve unilaterally), `"pollen_pollen_airborne"`,
`"air_quality_pm2_5"`, and `"weather_summary"` (each judged
unrecoverable from the requested name itself, same failure mode as
candidates already rejected in the original Lauf 11 analysis).
`"temperature"`/`"sun"` remain excluded, as originally decided (three
co-equal daily targets / too short and generic, collision risk).

**2. `CONTEXT_FIELD_AMBIGUOUS`** (5 entries: `pm25`, `pm2_5`, `pm10`,
`no2`, `air_quality_index`) and **`HEALTH_FIELD_AMBIGUOUS`** (2
entries: `spo2`, `stress`) — a new third outcome for fields where the
requested name itself does not reveal whether a daily value or a
`_series` was meant, checked before the generic unknown-field
handling. Deliberately reuses the EXISTING `error`/`did_you_mean`
response shape rather than introducing a new one (e.g. an
`"ambiguous": true` marker) — weaker local models already struggle
with the existing schema (Lauf 11: `mistral-nemo` skips
`query_context` in 74% of cases, `command-r7b` refuses tool calls
entirely); a new response concept would add reasoning burden
precisely where models are weakest, whereas `did_you_mean` is a shape
every model already has to handle for typos. No `field_used`/
`field_resolved_from` — nothing is resolved, the caller must re-ask
with the exact name. A majority-default alias was considered and
rejected for all seven fields — it would silently return a wrong
value in the minority of cases (20–50%, field-dependent), the exact
failure mode `v1.7.1.9`'s alias mechanism exists to prevent.

`HEALTH_FIELD_AMBIGUOUS`'s two entries were found via a systematic
scan (all 26 registered health fields' `_avg`/`_series`/`_max`/`_pct`-
suffixed prefixes checked against `cutoff=0.65`), triggered by an
unrelated test failure: the `cutoff=0.65` change (`v1.7.1.11` Session
5) had unintentionally undermined the `v1.7.1.9` decision to leave
`"spo2"` unresolved — at `0.8` the exclusion held implicitly (no
match at all); at `0.65` it now matched exactly one candidate
(`spo2_avg`), so the pre-existing near-match auto-resolve silently
fired for a case the architecture explicitly wanted left alone.
`"stress"` showed the identical shape, previously undiscovered.
`"respiration"` was checked and deliberately NOT added — only one
target (`respiration_series`) exists for that prefix, no ambiguity,
the pre-existing auto-resolve there is correct and unaffected.
`"body_battery"`, `"heart_rate"`, `"sleep_deep"`, `"sleep_rem"` were
also checked — all already fall through correctly to the generic
unknown-field error (2–3 close matches each, auto-resolve condition
not met), no change needed.

**3. Domain check before similarity comparison** — a structural
reordering in both `query_health()` and `query_context()`, not a new
table. Found via the same test run: at `cutoff=0.65`, the "outcome 2"
domain-confusion check (documented under `v1.7.1.4`/`v1.7.1.9` above)
ran AFTER the near-match difflib check, so an exact, registered field
of the OTHER domain could be silently near-matched to a similarly-
named field of the wrong domain before domain-confusion detection was
ever reached — e.g. `"sleep_duration"` (an exact health field) sent to
`query_context()` matched `"sunshine_duration"` and was silently
answered, instead of returning the domain-confusion error. A
systematic scan of both field registries at `cutoff=0.65` found eight
such cases total (four per direction): `sleep_duration`→
`sunshine_duration`, `stress_avg`/`stress_series`→`pressure_avg`/
`pressure_avg_series` (query_context() direction), and the mirror
image in `query_health()`: `condition_series`/
`precipitation_sum_series`→`respiration_series`, `pressure_avg`/
`pressure_avg_series`→`stress_avg`/`stress_series`, `sunshine_duration`
→`sleep_duration`. Fix: the other domain's full field registry is now
computed and checked BEFORE the difflib call in both functions — an
exact cross-domain field match is caught immediately, difflib never
gets the chance to claim it for the wrong domain first. Bundle names
(`"weather"`/`"pollen"`/`"air"`) were already correctly ordered before
this fix (the `_CONTEXT_CATEGORY_BUNDLES` check has always run before
difflib) — verified, not just assumed, no further action needed there.
Verified against the real LLM test run below: 16/16 of these eight
cases (both models) now return the correct domain-confusion error.

**4. `wind_speed_max` direct-field-path fix** — the collision
described under `v1.7.1.5` above (`_resolve_context_bundle()`'s
per-day tie-break, `brightsky` vs. `weather`) was never reachable via
a direct field request (`field="wind_speed_max"`, bypassing the
bundle path entirely) — both source values were returned unresolved.
Confirmed via cross-check against `weather_map.py`/`brightsky_map.py`'s
field lists and `REFERENCE_BROKER.md`'s own naming-collision note that
`wind_speed_max` is the ONLY such collision in the current registry —
no generic `_KNOWN_FIELD_COLLISIONS` table was built for a single
confirmed case. Fix: for `field == "wind_speed_max"` specifically, the
direct path now fetches both sources in one call (`mcp_sql.
get_context_range()`/`mcp_map.query_context()` already fan out across
every source registering a given field name — confirmed by reading
`mcp_sql.py`'s own docstring rather than assumed, since an earlier
draft of this fix wrongly issued two identical calls) and applies the
same per-day, `brightsky`-first value precedence as the bundle path —
no location/config check, no fallback concept beyond "use `brightsky`
when it has a non-`None` value for that day, otherwise `weather` for
that same day" (Timo decision — plain value precedence, deliberately
not the more elaborate location-bounding-box check originally
considered, since `context_collector.py`'s existing DE-bounding-box
skip already encodes that decision into file presence: a day with no
`brightsky` value already means "location was outside Germany that
day", checking values is equivalent). `_meta.field_sources` is
populated identically to the bundle path, carrying over the existing
`_meta` (date/weekday block) from the underlying fan-out call rather
than replacing it. `mcp_sql.py`/`mcp_map.py`/`context_map.py`
untouched — same containment principle as `v1.7.1.5`.

**Discovered and fixed during the same session, unit-test fixtures
only, no production behaviour change:** two `test_mcp.py` fixtures
predating the `v1.7.1.11` Session 5 cutoff change no longer held at
`cutoff=0.65` — `"sunshine_duratio"` (two occurrences) now matches
three candidates instead of one (`sunshine_duration`/`sunshine_sum`/
`sunshine_sum_series`), replaced with `"condiiton"`→`"condition"`
(`condition` is the sole string-type field in the context registry,
no `_avg`/`_max`/`_sum` sibling to collide with). A second, broader
fixture problem was found the same way: `"pollenbirch_series"` (a
mid-prefix typo of a `_series` field, used to test unambiguous
auto-resolve) also stopped resolving uniquely — a systematic check of
all 19 registered `_series` fields against two typo patterns found
that NONE stay unique under `cutoff=0.65`; each collides with its own
daily counterpart. This is a structural property of `cutoff=0.65`
against the `X`/`X_series` naming scheme, not a fixable fixture choice
— no replacement typo exists. Reframed the test as a second documented
collision case (same principle as the pre-existing `airquality_
european_aqi_series` collision test) rather than patched with a new
alias or cutoff change — left open for a future session (see
`NOTES_v1.7.1.12.md`, "Ziel 6").

**Verified against a real LLM test run** (2026-09-10, `qwen2.5-coder:7b`
+ `qwen3:8b`, 80 targeted questions × 2 models = 160 cases,
`question_catalog_v17112_context_field_resolution.py` — a targeted
follow-up covering only the new/changed cases above, not the full
Lauf-11-style catalog): **160/160 server-side responses correct** —
every alias resolved to its documented target (120/120, four
`MAX_TOOL_TURNS` cases traced to model non-termination on an already-
successful call, not resolution failure), all 16 domain-confusion
regression cases returned the correct error, the three `_series`-
collision examples returned the documented multi-candidate
`did_you_mean`, and all 14 ambiguity-check first-calls returned the
correct rückfrage shape. Model-level (not server-level) variance
observed and NOT a server defect: `qwen2.5-coder:7b` respected the
ambiguity rückfrage (asked the user rather than guessing) in 1/7
cases, `qwen3:8b` in 5/7 — expected LLM behaviour variance per Lauf
11's own precedent for differing model tool-call discipline, not
something this mechanism controls or claims to.
