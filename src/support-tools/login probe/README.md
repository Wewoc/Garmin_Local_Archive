# Garmin Login Probe

**⚠️ After using Block A (test account), delete the credentials from
`probe_config.py` again.** `GARMIN_TEST_EMAIL` / `GARMIN_TEST_PASSWORD`
only need to be there for the run itself — leaving them filled in
afterward is an unnecessary risk, especially if the file is ever
shared, backed up, or accidentally committed. Block B never stores
credentials in this file at all — see below.

A small standalone diagnostic tool for Garmin Local Archive. Attempts
a single login pass — one call into the login flow — and reports
`LOGIN OK` or `LOGIN FAILED`. That one call can still involve multiple
requests internally (e.g. a token probe, then an SSO attempt that
itself tries several strategies inside the `garminconnect` library) —
"one pass" means the tool calls the login flow exactly once, not that
exactly one HTTP request happens on the wire.

## Why this exists

Garmin Connect's login endpoints are occasionally rate-limited or
blocked by Cloudflare (`429` / `403` responses), independent of GLA
itself — this affects the underlying `garminconnect` library broadly,
not just this project. When a sync fails with a login error, it's
useful to isolate the question "is Garmin currently blocking logins at
all?" from "is something wrong with my GLA setup?" — without running a
full sync, without fetching any health data, and (optionally) without
touching your main account at all.

## What it does NOT do

- No data sync, no bulk API calls beyond the login step itself
- No changes to `garmin_api.py`, `garmin_security.py`, or
  `garmin_config.py` in your GLA install — it only calls into them
- Block A never reads or writes your saved token

## What Block B *can* change

Block A is a fully isolated probe — no token access at all. Block B is
not: it runs the exact same login flow a normal GLA sync uses, so it
can change your local login state the same way a normal sync would.

Specifically, if your saved token has expired or is rejected by
Garmin, Block B's login flow deletes it and — if the following SSO
attempt succeeds — saves a new one. That's the same behavior you'd get
from a regular sync hitting an expired token, not something extra this
tool does. But it means Block B is a diagnostic *and recovery* probe
for your GLA login state, not a read-only check the way Block A is.
If you want a check that's guaranteed not to touch your main account
at all, use Block A instead.

## Setup

1. Copy this folder (`garmin_login_probe.py`, `probe_config.py`,
   `run_login_probe.bat`) anywhere you like — it does not need to sit
   inside the GLA repo.
2. Open `probe_config.py` and fill in the values for your setup (see
   below).
3. Run `run_login_probe.bat` (double-click), or `python
   garmin_login_probe.py` from a terminal.
4. **If you used Block A**, delete the credentials you entered in
   `probe_config.py` — clear `GARMIN_TEST_EMAIL` / `GARMIN_TEST_PASSWORD`
   back to empty strings once you're done testing. Block B never
   requires this step, since it never stores credentials in the file.

**Do not commit `probe_config.py` with a test account's credentials
filled in.** If you keep this tool inside your own fork/clone of the
repo, add `probe_config.py` to `.gitignore` once you've edited it, or
keep your edited copy outside version control entirely.

## Two modes

### Block A — Test account (recommended first)

If you don't already have a spare Garmin account, consider creating
one purely for login testing. Since Garmin's rate limiting can be
triggered by repeated login attempts, testing against a disposable
account avoids putting your main account's login status at risk.

Set `GARMIN_TEST_EMAIL` (and optionally `GARMIN_TEST_PASSWORD`) in
`probe_config.py`. If the password is left empty, the script prompts
for it via `getpass` (hidden input, nothing written to disk).

This mode talks directly to the `garminconnect` library with a
disposable/secondary Garmin account. It never imports GLA's token
handling and never touches your main account's saved token — useful
for testing login behavior without any risk to your primary archive.

### Block B — Standard account (your real GLA setup, WCM-backed)

Used automatically when `GARMIN_TEST_EMAIL` is left empty. Runs the
same `garmin_api.login()` flow your GLA install uses for a normal
sync: reuses the saved encrypted token if valid, or attempts one SSO
login if not.

**No credentials are ever entered in `probe_config.py` for this mode.**
Email and password are read from the same place the GLA GUI stores
them — Windows Credential Manager plus
`~/.garmin_archive_settings.json` — via `app/garmin_app_settings.py`.
This requires:

- You've already saved your email and password once via the GLA GUI's
  Settings tab (so they exist in WCM / settings file to begin with)
- `GARMIN_REPO_DIR` in `probe_config.py` points to your GLA install's
  `garmin/` folder, with `app/` sitting next to it under the same
  `src/` folder — the standard GLA layout. The script derives the
  `app/` path automatically from `GARMIN_REPO_DIR`; you don't set it
  separately.

Two paths still go in `probe_config.py`:

- `GARMIN_OUTPUT_DIR` — the folder containing `garmin_data/` (token,
  quality log, etc.) — same as GLA's `GARMIN_OUTPUT_DIR`
- `GARMIN_REPO_DIR` — the folder containing `garmin_api.py`,
  `garmin_config.py`, `garmin_security.py`, `garmin_utils.py` (e.g.
  the `garmin/` subfolder of your GLA install). Leave empty if this
  script sits directly next to those modules.

If email/password can't be found in WCM/settings, or `app/` can't be
found next to `garmin/`, the script fails with a clear message instead
of falling back to anything silently.

## Path formatting

Paste any Windows path straight from Explorer's address bar into
`probe_config.py`, wrapped in `r"..."` (keep the `r` prefix — it tells
Python not to interpret backslashes as escape sequences). The only
exception: if the copied path ends with a backslash, drop that one
trailing backslash before the closing quote, since a backslash
directly before a quote still breaks Python's parser even inside a
raw string.

```python
GARMIN_REPO_DIR = r"D:\Garmin\template\src\garmin"
```

## Example output

```
2026-08-16 10:35:53 INFO Connecting to Garmin Connect ...
2026-08-16 10:35:53 INFO   No saved token found
2026-08-16 10:35:54 WARNING mobile+cffi returned 429: ...
2026-08-16 10:35:54 WARNING mobile+requests returned 429: ...
2026-08-16 10:36:03 INFO   ✓ Login successful (SSO)
2026-08-16 10:36:04 INFO   ✓ Token encrypted and saved

LOGIN OK
```

A `LOGIN FAILED: ...` line with the underlying exception means either
your credentials are wrong, or Garmin is currently blocking the login
strategy chain entirely — the error message distinguishes the two
(`401 Unauthorized` vs. `429` / `403` / `GarminConnectTooManyRequestsError`).

## License

GPL-3.0-or-later, same as the rest of Garmin Local Archive.
