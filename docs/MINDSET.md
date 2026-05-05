```
<!--
© 2026 Wewoc
Licensed under Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)
https://creativecommons.org/licenses/by-nc/4.0/

You are free to share and adapt this material for any non-commercial purpose,
as long as you give appropriate credit.

If used in research or publications, please cite as:
  Garmin Local Archive — Human-AI Collaboration Documentation
  https://github.com/Wewoc/Garmin_Local_Archive
-->
```

# Mindset

*The thinking behind Garmin Local Archive — why it exists, how it was 
built, and why the architecture looks the way it does.*

---

## Why this exists

I read an article about analyzing Garmin data with AI. Sounded great —
except I didn't want to send my health data to another cloud service.
One cloud is already enough.

But there's a second problem that's less obvious and harder to recover 
from: Garmin deletes your intraday data. The fine-grained stuff — 
second-by-second heart rate, the stress curve from a difficult 
afternoon, the breathing pattern during a night your HRV dropped — 
disappears from their servers in stages — full resolution gone after roughly six months, reduced data after roughly two and a half years, based on what's visible in archive data from April 2026. For Garmin, old high-resolution data has no business value. For you, it's 
gone permanently. There's no export that brings it back.

This tool exists because of both problems.

---

## How it was built

I can't write Python. My options were learn it from scratch, pay 
someone, or find a different way. This is the different way.

The architecture, module boundaries, data flow, and quality rules came 
from engineering instinct applied to a software problem — my background
is mechanical system design. The implementation — every line of Python 
— came from Claude as coding partner.

It started with 2-3 scripts and a dashboard. Then it escalated.
30 days, 20 USD, 214 commits, 20 releases.30 days, 20 USD, 214 commits, 20 releases.

Roughly half the time went into planning, architecture decisions, and 
cross-model review — not implementation. No code without a prior 
design decision.

The result works because it was treated like any other engineering 
problem: define responsibilities clearly, keep modules from crossing 
into each other's territory, test against real data, document decisions
including the ones not taken.

*This didn't happen because there was time for it. It happened because stopping wasn't really an option.*

---

## Why the architecture looks the way it does

Three decisions shape everything else.

**One module, one responsibility.**
Every module owns exactly one thing and cannot touch what belongs to 
another. `garmin_writer.py` is the only module that writes to `raw/` 
and `summary/`. Nothing else writes there. This sounds obvious until 
you see what happens when it isn't true: two modules write the same 
file, one overwrites the other's work, and the failure is silent.

**The broker layer as the only data access point.**
Dashboard specialists never read files directly. They ask `field_map` 
and `context_map` — two routing modules that know where data lives. 
Adding a new dashboard means writing one new specialist file. No 
existing code changes. Adding a new data source means extending the 
broker. All dashboards work automatically.

**Plugins contain no logic.**
`weather_plugin.py` and `pollen_plugin.py` are metadata only — 
endpoints, field names, file prefixes. No executable code. Adding a 
new external data source means writing a new plugin file. The collect 
and write modules work without modification.

These patterns have names in software development. I didn't know the 
names when I made the decisions. I made them because the alternative 
— modules that do multiple things, direct file access everywhere, 
logic scattered across plugins — creates failures that are hard to 
find and harder to fix. **Claude recognized that the solutions had names.**

---

## Collaboration — Who had which idea?

**Garmin Local Archive** · [github.com/Wewoc/Garmin_Local_Archive](https://github.com/Wewoc/Garmin_Local_Archive)

The following table documents how architectural and design decisions emerged during development (approximately from v0.4 to v1.4.2).

It distinguishes between:

- human input, where priorities, constraints, or strategic decisions were defined,
- AI input, where implementation paths, structural refinements, or technical formulations were proposed,
- dialog-driven outcomes, where the final solution resulted from iterative refinement between both.

The purpose is not to assign ownership, but to show how decisions emerged: the human side defining intent and constraints, the AI side contributing technical elaboration within those boundaries.

---

| Category | Idea / Decision | Human input | AI input |
|---|---|---|---|
| **User** | Project core: local-first, no cloud, no third parties | Defining sentence before any code: *"I don't want to give the data to an AI company"* | Proposed the technical path (garminconnect library, Ollama) |
| **User** | Two-layer architecture (raw + summary) | Idea in response to Claude's question — not a reaction to a proposal | Asked which format to use |
| **User** | Bulk-first over API-first (v1.3.0) | Overruled Claude's assessment with concrete experience: Garmin API lockout (429) for over a week — live sync unreliable as sole strategy | Had rated bulk as operationally impractical |
| **User** | Backfill mode with random days | *"Check what's there and load 10–20 random days"* — mimics natural user behaviour | Analysed consequences, suggested weighted random selection |
| **User** | Monthly backup as .zip | Concrete decision after Claude's scope brake against file splitting | Had proposed splitting into separate files |
| **User** | Recheck backoff logic (n×5 days, max 3) | Core idea: *"next attempt earliest on yyyy-mm-dd"* | Worked out the formula and edge cases |
| **User** | Multi-source architecture v2.0 | Realisation that Wahoo/Strava is the actual data gap | Documented concept, named patterns (Adapter, Broker) |
| **User** | Multi-AI reviews as QA method | *"I run more than one review. There's usually an intersection."* | Evaluated findings, identified false positives from other reviewers |
| **User** | "Assess first" principle | Explicit rule: *"just assess, nothing yet"* — enforced as memory rule | Acknowledged own failure mode: *"question recognised → solution built without request"* |
| **User** | F/A schema for decisions | Format developed to lock in scope before implementation begins | Applied the format, waited for explicit instruction |
| **User** | Project character and humour | Accepted the esoteric dashboard, kept the intentional typo in `garmin_extended_anaysis.py` | Built it when asked |
| **User** | `garmin_dataformat.json` as machine-readable field source | Decision after refactoring: all field types and descriptions in one JSON file instead of code | Defined structure, used as single source of truth for normalizer + validator |
| **User** | `field_map.py` queries by concept, not by name | *"field_map.py doesn't ask: what is 'heartRateValues' called at your end — it asks: give me the value for 'heartRateValues'"* — core idea of the broker pattern | Formalised as architectural principle in `maps/` layer |
| **User** | v1.4 as testbed for v2.0 architecture | *"Could we use v1.4 as a dry run for the architecture?"* — idea to introduce real structure already in v1.4 | Analysed trade-offs, recommended dummy implementation of maps layer |
| **User** | Dataset merge instead of overwrite (Bulk + API) | *"Take the better part from each source"* — after 429 lockout and bulk import rework | Developed merge logic and field-flagging concept |
| **User** | Weather + pollen dashboard with toggleable charts | *"A dashboard showing pollen/weather data and sleep/HRV/Body Battery — individual charts can be toggled"* | Evaluated, implemented as Sleep & Recovery Context Dashboard |
| **Claude** | Single-owner principle for `quality_log.json` | *"Quality writes quality.json"* — User's idea for responsibility | Formulated it as an architecture principle, applied it consistently |
| **Claude** | Schema versioning for summary files | — | Proposed `schema_version` field so `regenerate_summaries.py` can work selectively |
| **Claude** | `NOTES_vX_Y_Z.md` workflow | Adopted immediately, applied in every subsequent session | Proposed: document decisions taken and not taken within a session |
| **Claude** | Naming: Dirigent / Transformator / Schreiber | User: *"Collector directs. Normalizer organises."* | Precision: *"I'd say: transforms"* — then named and systematised the roles |
| **Claude** | ENV timing as critical failure class | — | Identified and documented: `garmin_config` resolves constants at import time — any module imported before ENV is set silently falls back to defaults |
| **Claude** | Return `None` not `[]` for missing intraday data | — | Rationale: `None` = file missing, `[]` = file empty — semantically distinct |
| **Claude** | 90-day baseline as reference framework for dashboards | — | Proposed rolling 90-day window values instead of fixed thresholds for HRV, sleep, etc. |
| **Claude** | Disclaimer block in all dashboards | — | Proposed unified medical disclaimer: *"Informational only — not medical advice"* |
| **Dialog** | `garmin_writer.py` as separate layer | *"You'd need to put a writer.py alongside it"* | Analysed consequences, showed where it helps for the roadmap |
| **Dialog** | `correlation_concept.md` | *"Weather data, moon phases"* — then: *"as md, that's too good"* | Esoteric list, including Mercury retrograde with zero explanation |
| **Dialog** | Standalone EXE as third build target | *"Scripts for purists, EXE for everyone else"* | Analysed the consequences, worked out the three-target solution |
| **Dialog** | Module structure (collector / normalizer / quality / writer) | *"If we're touching it anyway, why not do it properly?"* | Technical formulation of boundaries, identified cross-dependencies |
| **Dialog** | Export range vs. sync range in UI | *"The range in the interface is only for sync, not for the scripts."* — Claude had conflated two separate UI concepts | Corrected, distinction applied throughout |
| **Dialog** | Bulk-first vs. API-first | Overruled Claude's assessment with operational experience: API blocked via 429 for over a week | Had rated bulk as impractical — updated after correction |
| **Dialog** | Two collector scripts vs. one with config block | *"Scripts for purists — they won't have Python anyway"* | Had proposed a single file with config block — dropped |
| **Dialog** | No SSD backup in the application | Proposed built-in backup — stepped back after pushback: *"Ok, I was thinking too far."* | *"That's OS responsibility, not application responsibility"* |
| **Dialog** | No file split for `quality_log.json` | Accepted the argument | Argued against splitting despite growing file size |
| **Dialog** | No implementation without explicit instruction | *"nothing yet"* as working rule — acknowledged as compensation, not ideal | Self-correction documented in chat, stored as memory rule |
| **Dialog** | Garmin SSO infrastructure change (March 2026) — detected and fixed | Reported symptom: 429 errors for over a week, no login possible | Identified: Garmin changed SSO API; updated `garminconnect` to 0.3.2, rewrote Path 3 with `prompt_mfa` constructor |
| **Dialog** | `GARMIN_OUTPUT_DIR` ENV bug in `_run_connection_test()` | Reported symptom: wrong data folder after connection test | Identified root cause: `garmin_config` imported before ENV was set → cascading 429 spiral |
| **Dialog** | Context pipeline (Open-Meteo weather + pollen) | Idea: external context data for sleep/recovery analysis | Architecture with `context/`, `weather_plugin.py`, `pollen_plugin.py` — no API key required |
| **Dialog** | Multi-LLM loop as standard QA process | *"I ran Gemini through the project once — evaluate only, no changes"* | Claude evaluates Gemini/ChatGPT findings critically — architecturally valid points accepted, false positives rejected with reasoning |
| **Dialog** | Local LLM for isolated single-file tasks | Decision: `qwen2.5-coder:14b` on RTX 4060 Ti for clearly scoped tasks | Formulated rule: architecture, multi-file, project context → Claude; single file without context → local model |
---

## What each side contributed

**User (User):**
The project's core stance. Structural decisions about module responsibilities. The working method ("assess first", F/A schema, versioned documentation). Corrections when Claude misunderstood the system. Quality assurance via multi-AI reviews. Most concrete feature ideas. The humour and character of the project.

**Claude.ai:**
All Python implementation. Technical formulation of architecture principles. Specific proposals like schema versioning and NOTES workflow. Identification and naming of problems (sys.exit in library functions, race conditions, Garmin API quirks). Documentation in structured form.

---

## What this isn't

This is not a commercial product and not a demonstration of what AI 
can do alone. It's a demonstration that the combination works — 
domain understanding and engineering instinct from a human, 
implementation from AI — and that the result can be something neither 
would have produced independently.

It's maintained when there's time and motivation. No support contract,
no roadmap commitment. If you want something polished and guaranteed: 
this isn't that. If you want something that works, that you can 
inspect, and that keeps your data where it belongs: this might be 
exactly that.

---

*Garmin Local Archive · github.com/Wewoc/Garmin_Local_Archive*