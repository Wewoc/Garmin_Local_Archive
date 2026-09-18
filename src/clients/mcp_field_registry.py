#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
clients/mcp_field_registry.py
Garmin Local Archive — MCP Field Metadata Registry

Extracted from clients/mcp_server.py (Codereview v1.7.0.1, Baustein 2.1)
— pure data, no logic, no behavior change. Holds the field-unit lookup
table and the alias/ambiguous-field registries query_health()/
query_context() use for typo-correction and domain-confusion detection.
_get_field_unit()/_enrich_with_units() and the mcp = FastMCP(...) server
object deliberately stayed in mcp_server.py — this file holds only the
five pure-data dicts, not the functions that consume them.

mcp_server.py imports these five names via
`from mcp_field_registry import (...)` — every existing reference in
query_health()/query_context()/_enrich_with_units()/_get_field_unit()
(FIELD_UNITS[...], `field in HEALTH_FIELD_ALIASES`, etc.) keeps working
unchanged, since the imported names are the same bare identifiers. Flat
sibling module in clients/, same shape as mcp_sql.py/mcp_update.py —
picked up automatically by clients/mcp_server.py's own
_register_embedded_packages() (adds the whole clients/ dir to sys.path,
not individual module names) and by compiler/build_manifest.py's
SHARED_SCRIPTS entry for this file.

Stays MCP-local by design, same as before the move — see the "Field
units" section comment below for the full reasoning (why this data does
NOT belong in maps/health_map.py / maps/context_map.py /
maps/gateway_map.py).
"""

# ══════════════════════════════════════════════════════════════════════════════
#  Field units (v1.7.1.6) — deliberate MCP-local stopgap, see KNOWN_ISSUES.md
#  Cluster F for the follow-up note.
# ══════════════════════════════════════════════════════════════════════════════
#
# Values transcribed from REFERENCE_BROKER.md's "Field index" table
# (health_map/garmin + context_map's four sources), verified against
# REFERENCE_GARMIN.md/REFERENCE_CONTEXT.md, 2026-08-31 (v1.7.1.6 Session 2).
# Every registered query_health()/query_context() field has an entry —
# no exceptions, including fields with no physical unit (e.g. "index",
# "text", "—") — a mixed state (some fields with unit, some without)
# would itself be a new, unpredictable source of LLM misinterpretation
# (Timo, Session 1 decision). Raw-passthrough fields (query_raw(), 13
# fields, no unit concept — see REFERENCE_GARMIN.md "Raw-passthrough
# fields") are deliberately NOT included here — out of this session's
# scope.
#
# Deliberately NOT placed in maps/health_map.py, maps/context_map.py,
# or maps/gateway_map.py: this session confirmed (DEPS-Scan v1716_02)
# that neither module currently holds a reusable unit/label structure,
# and _route_query()'s SQLite branch (currently the only branch ever
# taken, see _route_query() below) never touches maps/mcp_map.py at
# all — a unit lookup placed there would silently do nothing for every
# real request today. This dict and its two helper functions below are
# therefore intentionally kept MCP-local (clients/mcp_server.py), but
# isolated behind _get_field_unit()'s narrow signature so a future
# broker-level replacement (e.g. health_map.list_field_units()) only
# requires swapping that one function's body — no caller here or
# elsewhere needs to change. See NOTES_v1716_session2.md for the full
# reasoning trail (an mcp_map.py-based design was considered first and
# rejected for the same two reasons).
FIELD_UNITS: dict[str, str] = {
    # ── health_map -> garmin (55 fields total: 26 pre-v1.7.1.14 + 6
    #    bp_* (v1.7.1.14) + 23 v1.7.1.16 registrations — corrected
    #    v1.7.1.17; the previous "54" comment undercounted by one and
    #    never reflected the six bp_* fields at all, see
    #    REFERENCE_BROKER.md/NOTES_v1_7_1_17.md) ─────────────────────────
    "hrv_last_night":        "ms",
    "resting_heart_rate":    "bpm",
    "spo2_avg":              "%",
    "sleep_duration":        "hours",
    "body_battery_max":      "0–100",
    "stress_avg":            "0–100",
    "vo2max":                "—",
    "sleep_score":           "0–100",  # v1.7.1.6 — pre-existing REFERENCE_BROKER.md/
                                        # REFERENCE_GARMIN.md gap closed this session,
                                        # see doc anchor delivery for the table row.
    "sleep_score_feedback":  "text",
    "sleep_score_qualifier": "text",
    "sleep_deep_pct":        "%",
    "sleep_light_pct":       "%",
    "sleep_rem_pct":         "%",
    "sleep_awake_pct":       "%",
    "heart_rate_series":     "bpm",
    "stress_series":         "0–100",
    "spo2_series":           "%",
    "body_battery_series":   "0–100",
    "respiration_series":    "—",  # unit not fixed in source docs, see REFERENCE_GARMIN.md
    "steps_series":          "steps",
    "body_weight":           "grams",
    "calories_resting":      "kcal",
    "hydration_ml":          "ml",
    "endurance_score":       "index",
    "hill_score":            "index",
    "fitness_age":           "years",

    # ── health_map -> garmin, v1.7.1.14 blood-pressure scalars (6) ─────────
    #    units per REFERENCE_GARMIN.md; previously missing here entirely
    #    (v1.7.1.17 fix, see FIELD_UNITS' own header comment above) ────────
    "bp_high_systolic":      "mmHg",
    "bp_high_diastolic":     "mmHg",
    "bp_low_systolic":       "mmHg",
    "bp_low_diastolic":      "mmHg",
    "bp_num_measurements":   "count",
    "bp_category":           "text",

    # ── health_map -> garmin, v1.7.1.16 registration-gap fields (23) ──────────
    # Broker-Registrierungslücken geschlossen, siehe garmin_health_map.py
    # _FIELD_MAP-Kommentar und NOTES_v1.7.1.16.md. Einheiten mit "—"
    # bewusst offen gelassen statt geraten (gleiche Konvention wie
    # vo2max/respiration_series oben) -- REFERENCE_GARMIN.md/
    # REFERENCE_BROKER.md-Abgleich folgt im separaten Doku-Bauauftrag.
    "hrv_weekly_avg":         "ms",
    "hrv_status":             "text",
    "hrv_feedback":           "text",
    "stress_max":             "0–100",
    "body_battery_min":       "0–100",
    "body_battery_end":       "0–100",
    "heart_rate_max":         "bpm",
    "heart_rate_min":         "bpm",
    "heart_rate_avg":         "bpm",
    "steps_total":            "steps",
    "steps_goal":             "steps",
    "floors_climbed":         "floors",
    "intensity_min_moderate": "minutes",
    "intensity_min_vigorous": "minutes",
    "distance":               "km",
    "calories_active":        "kcal",
    "calories_total":         "kcal",
    "readiness_score":        "0–100",
    "readiness_level":        "text",
    "readiness_feedback":     "text",
    "training_status":        "text",
    "training_load_7d":       "—",  # Skala nicht sicher verifiziert
    "respiration_avg":        "breaths/min",

    # ── context_map -> weather (6 fields) ─────────────────────────────────────
    "temperature_max":       "°C",
    "temperature_min":       "°C",
    "precipitation":         "mm",
    "wind_speed_max":        "km/h",  # also registered by brightsky, same unit —
                                        # see context_map.py's documented naming collision
    "uv_index_max":          "index",
    "sunshine_duration":     "seconds",

    # ── context_map -> pollen (6 fields) ──────────────────────────────────────
    "pollen_birch":          "grains/m³",
    "pollen_grass":          "grains/m³",
    "pollen_alder":          "grains/m³",
    "pollen_mugwort":        "grains/m³",
    "pollen_olive":          "grains/m³",
    "pollen_ragweed":        "grains/m³",

    # ── context_map -> brightsky (9 fields) ───────────────────────────────────
    "temperature_avg":       "°C",
    "humidity_avg":          "%",
    "precipitation_sum":     "mm",
    "sunshine_sum":          "min",
    "wind_gust_max":         "km/h",
    "cloud_cover_avg":       "%",
    "pressure_avg":          "hPa",
    "condition":             "text",

    # ── context_map -> airquality (5 fields) ──────────────────────────────────
    "airquality_pm2_5":             "μg/m³",
    "airquality_pm10":              "μg/m³",
    "airquality_european_aqi":      "index",
    "airquality_nitrogen_dioxide":  "μg/m³",
    "airquality_ozone":             "μg/m³",
}


# v1.7.1.9 Session 2 -- explicit short-form alias mapping for
# query_health(). See query_health()'s own docstring for the full
# rationale (structural difflib limitation, not a tuning gap) and
# NOTES_v1.7.1.9.md Session 2 for the per-candidate verification
# against the real, current health field registry. "spo2" deliberately
# excluded -- see the same notes for the collision analysis.
HEALTH_FIELD_ALIASES: dict[str, str] = {
    "hrv": "hrv_last_night",
    "hill": "hill_score",
}


# v1.7.1.12 -- fields where the requested short form does not reveal
# whether a daily value or a _series (timeseries) was meant, same
# principle as CONTEXT_FIELD_AMBIGUOUS (see that table's own comment
# for the full rationale -- reuse of the existing error/did_you_mean
# schema, no new response shape, no majority-default alias).
#
# Discovered this session (NOT part of the original v1.7.1.9 alias
# work): lowering cutoff to 0.65 (v1.7.1.11 Session 5) unintentionally
# undermined the v1.7.1.9 Session 2 decision to keep "spo2" unresolved
# -- at cutoff=0.8 the exclusion held implicitly (no match at all); at
# 0.65 "spo2" now matches exactly one candidate (spo2_avg), so the
# existing len(close_matches) == 1 auto-resolve branch silently fires
# for a case the architecture explicitly wanted left alone. A systematic
# scan of all 26 registered health fields at cutoff=0.65 (every prefix
# with an _avg/_series/_max/_pct sibling, existing HEALTH_FIELD_ALIASES
# short forms steps/hrv/hill excluded as already resolved) found one
# more case with the identical shape: "stress" matches uniquely to
# stress_avg, though stress_avg/stress_series are just as co-equal as
# spo2_avg/spo2_series. "respiration" was checked and deliberately NOT
# included -- only one target (respiration_series) exists for that
# prefix, no ambiguity, the existing auto-resolve there is correct and
# unaffected. "body_battery", "heart_rate", "sleep_deep", "sleep_rem"
# were also checked -- all already fall through correctly to the
# generic unknown-field error (2-3 close matches each, auto-resolve
# condition not met), no change needed for those.
HEALTH_FIELD_AMBIGUOUS: dict[str, list[str]] = {
    "spo2": ["spo2_avg", "spo2_series"],
    "stress": ["stress_avg", "stress_series"],
    "steps": ["steps_total", "steps_series"],
}


# v1.7.1.12 -- explicit alias mapping for query_context(), same pattern
# as HEALTH_FIELD_ALIASES above (structural difflib limitation, not a
# tuning gap -- see query_context()'s own docstring and NOTES_v1.7.1.12.md
# for the full analysis and Lauf 11/12/12b test-run background). All 36
# entries are requested->expected discrepancies actually observed in
# Lauf 11 (7 models, cutoff 0.8) and Lauf 12b (2 models, cutoff 0.65),
# individually re-verified against the current context field registry
# before inclusion -- not taken over 1:1 from the raw candidate list.
#
# Four candidates from the original 66-entry raw list were deliberately
# NOT included, kept as an open item rather than silently dropped (see
# NOTES_v1.7.1.12.md "Ziel 1" section for the per-case reasoning):
#   "ozone" (x3) -> would alias to airquality_ozone_series, but shares
#     the same daily/series ambiguity as the CONTEXT_FIELD_AMBIGUOUS
#     entries below -- inconsistent to resolve unilaterally here while
#     pm25/pm10/no2/etc. get a rückfrage instead.
#   "pollen_pollen_airborne" (x1) -> proposed target (pollen_mugwort_
#     series) is not recoverable from the requested name itself, same
#     failure mode as the 3 candidates already rejected in Lauf 11
#     Appendix A (ragweed/pollen_elm/pollen_series mis-mappings).
#   "air_quality_pm2_5" (x1) -> proposed _series target has no _series
#     signal in the requested name; pm2_5 itself is a known ambiguity
#     case (see CONTEXT_FIELD_AMBIGUOUS), no reason this variant should
#     resolve unambiguously where the bare form does not.
#   "weather_summary" (x1) -> proposed target (condition_series)
#     contradicts the word itself ("summary" suggests a daily aggregate,
#     not a timeseries).
#
# "temperature" and "sun" deliberately excluded (per Lauf 11 Appendix A
# and confirmed in this session): temperature has three co-equal daily
# targets (_min/_max/_avg), sun is too short/generic with collision risk.
CONTEXT_FIELD_ALIASES: dict[str, str] = {
    # -- Cutoff-0.65 auto-resolve mistakes, promoted to explicit aliases
    #    (v1.7.1.11 Session 5 / Lauf 12b, individually traced to
    #    _meta.field_resolved_from root cause, not estimated) --
    "humidity": "humidity_avg",
    "pressure": "pressure_avg",
    "air_pressure": "pressure_avg",
    "wind_speed": "wind_speed_max",

    # -- Multi-observation candidates (x9 down to x2), Lauf 11 Appendix A --
    "pollen_grass_hourly": "pollen_grass_series",
    "sunshine_total": "sunshine_sum",
    "european_aqi": "airquality_european_aqi",
    "min_temperature": "temperature_min",
    "pollen_alder_hourly": "pollen_alder_series",
    "olive_pollen": "pollen_olive",
    "ragweed_pollen": "pollen_ragweed",
    "max_wind_speed_dwd": "wind_speed_max",
    "pm25_series": "airquality_pm2_5_series",
    "pm10_series": "airquality_pm10_series",
    "max_wind_speed": "wind_speed_max",
    "grass_pollen": "pollen_grass",
    "airquality_o3_series": "airquality_ozone_series",
    "uv_max": "uv_index_max",
    "alder_pollen": "pollen_alder",
    "avg_cloud_cover": "cloud_cover_avg",
    "avg_pressure": "pressure_avg",
    "airquality_no2_series": "airquality_nitrogen_dioxide_series",
    "airquality_no2": "airquality_nitrogen_dioxide",
    "mugwort_pollen": "pollen_mugwort",
    "max_wind_gust": "wind_gust_max",
    "weather_condition": "condition",
    "max_temperature": "temperature_max",
    "pollen_birch_hourly": "pollen_birch_series",
    "european_aqi_series": "airquality_european_aqi_series",
    "pollen_olive_hourly": "pollen_olive_series",
    "pollen_ambrosia": "pollen_ragweed_series",
    "avg_humidity": "humidity_avg",
    "sunshine_minutes": "sunshine_sum",
    "avg_temperature": "temperature_avg",

    # -- x1 candidates, individually re-verified this session --
    "wind_max": "wind_speed_max",
    "rain_sum": "precipitation_sum",
    "air_pressure_series": "pressure_avg_series",
    "weather_series": "condition_series",
    "ozon": "airquality_ozone",  # deutsche Schreibweise ohne "e"
    "ozone_index": "airquality_ozone_series",
    "birkenpollen_belaestigung": "pollen_birch",
    "beifußpollenbelastung": "pollen_mugwort_series",
    "olivenpollenbelastung": "pollen_olive_series",
    "brightness_index": "cloud_cover_avg",
    "airpressure": "pressure_avg_series",
    "birch_pollen_concentration": "pollen_birch",
    "outdoor_humidity": "humidity_avg",
    "air_quality_humidity_series": "humidity_avg_series",
    "rainfall_max": "precipitation_sum_series",
    "sun_minutes": "sunshine_sum",
    "brightsky_percent": "sunshine_sum_series",
    "pm25_avg": "airquality_pm2_5",
    "air_quality_index_daily_max": "airquality_european_aqi",
    "no2_avg": "airquality_nitrogen_dioxide",
    "no2_max_time": "airquality_nitrogen_dioxide_series",
    "air_quality_o3_max": "airquality_ozone",
    "ozone_max": "airquality_ozone_series",
    "sun_hours": "sunshine_duration",
    "rain_intensity_series": "precipitation_sum_series",
    "ozone_avg": "airquality_ozone",
}


# v1.7.1.12 -- fields where the requested name itself does not reveal
# whether a daily value or a _series (timeseries) was meant, unlike
# CONTEXT_FIELD_ALIASES above where every observation points to the
# same target. A majority-default alias was considered and rejected
# (see NOTES_v1.7.1.12.md "Ziel 1"/"Ziel 3") -- it would silently
# return a wrong value in the minority of cases (20-50%, depending on
# field), exactly the failure mode this session is fixing elsewhere.
#
# Instead: reuse the existing error/did_you_mean schema (checked in
# query_context() below, BEFORE the generic unknown-field handling) --
# no new response shape, no new field on the result dict. Deliberately
# NOT a new "ambiguous": true marker -- weaker local models (see Lauf 11:
# mistral-nemo skips query_context in 74% of cases, command-r7b refuses
# tool calls entirely) already struggle with the existing schema; a new
# response concept would add reasoning burden precisely where models are
# already weakest, whereas did_you_mean is a shape every model already
# has to handle for typos. field_used/field_resolved_from are NOT set --
# nothing was resolved, the caller must re-ask with the exact name.
#
# Grouped by subject matter (all air quality: particulates + gases),
# not by candidate quality -- pm25/pm2_5/pm10/no2/air_quality_index/
# ozone all showed the identical daily/series split pattern in Lauf 11
# Appendix A. "ozone" was originally left out here as an open item
# (see CONTEXT_FIELD_ALIASES comment above) -- v1.7.1.15 resolves that
# open item by including it, consistent with the other five entries.
CONTEXT_FIELD_AMBIGUOUS: dict[str, list[str]] = {
    "pm25": ["airquality_pm2_5", "airquality_pm2_5_series"],
    "pm2_5": ["airquality_pm2_5", "airquality_pm2_5_series"],
    "pm10": ["airquality_pm10", "airquality_pm10_series"],
    "no2": ["airquality_nitrogen_dioxide", "airquality_nitrogen_dioxide_series"],
    "air_quality_index": ["airquality_european_aqi", "airquality_european_aqi_series"],
    "ozone": ["airquality_ozone", "airquality_ozone_series"],
}


# ── Context category bundles (moved here Codereview v1.7.0.1, Baustein
#    2.2 — was mcp_server.py, needed by both mcp_health.py's domain-
#    confusion check and mcp_context.py's own bundle resolution;
#    living in the neutral shared registry avoids a direct health<->
#    context file dependency) ─────────────────────────────────────────
# ── Kategorie-Buendel fuer query_context() (v1.7.1.5) ────────────────────
#
# Ordnet einen Kategorienamen (z.B. "weather") einer PRIORISIERTEN LISTE
# von context_map-Quellennamen zu. Die Feldnamen jeder Quelle werden NICHT
# hier gepflegt -- sie werden zur Laufzeit ueber mcp_map.list_available_
# fields(domain="context") ermittelt (nicht direkt aus maps.context_map --
# clients/ spricht die Broker-Schicht ausschliesslich ueber mcp_map an,
# siehe NOTES_v1.7.1.5.md), damit neue Einzelfelder innerhalb einer bereits
# gelisteten Quelle automatisch im Buendel erscheinen, ohne dass diese
# Liste angefasst werden muss.
#
# REIHENFOLGE = PRIORITAET bei Namenskollision zwischen zwei Quellen
# desselben Buendels (aktuell nur "wind_speed_max" bei weather/brightsky,
# siehe context_map.py-Docstring): bei einer Kollision gewinnt fuer jeden
# Tag einzeln die ERSTE Quelle in dieser Liste, die fuer diesen Tag
# tatsaechlich einen Wert (nicht None) liefert -- liefert sie keinen,
# entscheidet die naechste Quelle in der Liste. Kollisionserkennung ist
# rein namensbasiert (gleicher Feldname in mehreren Quellen desselben
# Buendels) -- kein Mapping/keine Aehnlichkeitspruefung zwischen
# UNTERSCHIEDLICHEN Feldnamen (bewusst verworfen, siehe
# KONZEPT_query_context_kategorie_aufloesung.md, Abschnitt "Warum keine
# allgemeine Feld-Mapping-Tabelle").
#
# Neue Quelle hinzufuegen (z.B. ein US-Anbieter):
#   1. Quellennamen an der gewuenschten Prioritaets-Position eintragen.
#   2. Nur falls die neue Quelle ein bereits vorhandenes Feld dieses
#      Buendels unter demselben Namen fuehrt (echte Kollision): Position
#      in der Liste bestimmt automatisch die Prioritaet -- keine
#      zusaetzliche Regel noetig.
_CONTEXT_CATEGORY_BUNDLES = {
    "weather": ["brightsky", "weather"],  # Messstation vor Modell
    "pollen":  ["pollen"],
    "air":     ["airquality"],
}
