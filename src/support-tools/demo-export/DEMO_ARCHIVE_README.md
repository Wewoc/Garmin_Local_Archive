# Fictional Demo Archive — Garmin Local Archive (GLA)

Every file in this archive is **synthetic, fictional demo data** —
randomly generated (seed=42) so you can try the GLA MCP server
(clients/mcp_server.py) without a real Garmin account. It is not
derived from, and does not represent, any real person's health data.

Date range: 2026-04-04 .. 2026-09-30 (180 days)
Location in context files: a placeholder (Berlin by default), not a
real user's location.

Every generated file carries a machine-readable marker:
- Health files (raw/, summary/): top-level key `"_fictional_demo_data": true`
- Context files (weather/, pollen/): `"source"` field ends in `-demo-fictional`
- `quality_log.json`: each day entry's `"source"` field is `"demo-fictional"`

## Known limitations

- Health raw/ files only populate the fields the MCP server's query
  tools actually expose (via garmin_normalizer.summarize()) — not a
  full replica of Garmin Connect's native API response shape.
- Weather has no raw/ (hourly) files, matching real GLA archives —
  Open-Meteo never delivers intraday weather data. Pollen raw/ files
  repeat the same flat average value for every hour of the day, not
  real hourly variation.
- `device_table.json` is not populated (no device/training-status
  simulation) — archive-metadata queries for that kind return empty.
  Every `quality_log.json` day entry has `device_id: null`, same as a
  real "no device match" day.

## Using it

1. Point `GARMIN_OUTPUT_DIR` at this folder (or wherever you extracted
   the .zip).
2. Start the MCP server — its SQLite query cache builds itself on the
   first start, nothing else to prepare.
