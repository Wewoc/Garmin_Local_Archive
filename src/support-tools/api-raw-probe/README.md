# Garmin API Raw Probe

Standalone diagnostic tool for Garmin Local Archive. Fetches specific
days directly via the Garmin API (`garmin_api.fetch_raw()`, the same 15
baseline endpoints `garmin_collector.py` uses for a normal sync) and
saves the raw result as JSON in this tool's own `downloads/` subfolder.

## Why this exists

Bulk-imported days (Garmin's official data export, pre-2024 in most
archives) and API-synced days differ structurally — `load_bulk()`
(`garmin_import.py`) only ever extracts `stress` (aggregate), `sleep`,
`training_readiness`, and `activities`. Fields like `hrv`, `spo2`,
`body_battery`, `respiration`, `training_status`, `race_predictions`,
and `max_metrics` have no extraction logic there at all, so bulk-sourced
days show those as permanently `failed` in `quality_log.json` —
regardless of age.

This tool lets you fetch a bulk-sourced day fresh via the API and
compare it directly against the existing bulk-sourced
`garmin_raw_<date>.json`, to check whether a given field gap is a
client-side extraction gap (confirmed if the API pull has data the bulk
file structurally lacks) or a genuine server-side/device limitation
(both pulls come back empty for that field).

## What it does NOT do

- **Never touches the archive.** No write to `raw/`, `source/`, or
  `quality_log.json`, and it does not go through `garmin_collector.py`
  at all. Every fetched day lands only in this tool's own
  `downloads/` folder.
- No credentials stored in this folder — reuses your existing GLA
  login (saved token via `garmin_app_settings.py` +
  `garmin_api.login()`), same as `support-tools/login-probe` Block B.

## Setup

1. Copy this folder (`fetch_raw_days.py`, `api_raw_probe_config.py`)
   anywhere you like — it does not need to sit inside the GLA repo.
2. Open `api_raw_probe_config.py` and fill in:
   - `GARMIN_OUTPUT_DIR` — the folder containing `garmin_data/` (token,
     quality log, etc.) — same as GLA's `GARMIN_OUTPUT_DIR`
   - `GARMIN_REPO_DIR` — the folder containing `garmin_api.py`,
     `garmin_config.py`, etc. (e.g. the `garmin/` subfolder of your GLA
     install). Leave empty if this script sits directly next to those
     modules (standard GLA layout).
3. You must have already saved your email/password once via the GLA
   GUI's Settings tab (so a token/credentials exist in Windows
   Credential Manager + `~/.garmin_archive_settings.json`).

## Usage

```bash
python fetch_raw_days.py 2023-12-31 2023-06-15
```

One `downloads/garmin_api_<date>.json` per requested day. Each run logs
which endpoints returned no data for that day, so a field that's
`failed` on both the API pull and the existing bulk file for the same
date is a device/period limitation, not something this tool (or an
eventual backfill) could fix.

## Path formatting

Same rule as `login-probe`: paste any Windows path straight from
Explorer, wrapped in `r"..."`, and drop a trailing backslash before the
closing quote if the copied path ends with one.

## License

GPL-3.0-or-later, same as the rest of Garmin Local Archive.
