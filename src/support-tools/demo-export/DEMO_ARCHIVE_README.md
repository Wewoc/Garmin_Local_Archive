# Fictional Demo Archive — Garmin Local Archive (GLA)

Every file in this archive is **synthetic, fictional demo data** —
randomly generated (seed=42) so you can try Garmin Local Archive —
dashboards, Chat and the MCP server (clients/mcp_server.py) — without
a real Garmin account. It is not derived from, and does not represent,
any real person's health data.

Date range: 2026-04-01 .. 2026-09-27 (180 days)
Location in context files: a placeholder (Berlin by default), not a
real user's location.

Every generated file carries a machine-readable marker:
- Health files (raw/, summary/): top-level key `"_fictional_demo_data": true`
- Context files (weather/, pollen/): `"source"` field ends in `-demo-fictional`

## Known limitations

- Health raw/ files only populate the fields the MCP server's query
  tools actually expose (via garmin_normalizer.summarize()) — not a
  full replica of Garmin Connect's native API response shape.
- Weather has no raw/ (hourly) files, matching real GLA archives —
  Open-Meteo never delivers intraday weather data. Pollen raw/ files
  repeat the same flat average value for every hour of the day, not
  real hourly variation.
- `quality_log.json` / `device_table.json` are not populated —
  archive-metadata queries for those two kinds return empty.

## Using it

Via the main app (recommended — also unlocks dashboards and Chat):
1. Extract this .zip.
2. Settings tab -> set Data folder to the extracted path -> "Save
   Settings".
3. Use "Create Reports" for dashboards, the Chat tab, or start the
   MCP server from the MCP Server tab.

MCP server only, without the main app:
1. Point `GARMIN_OUTPUT_DIR` at this folder (or wherever you extracted
   the .zip).
2. Start the MCP server (standalone `mcp_server.exe` or
   `clients/Starte_MCP_Server.bat`) — its SQLite query cache builds
   itself on the first start, nothing else to prepare.
