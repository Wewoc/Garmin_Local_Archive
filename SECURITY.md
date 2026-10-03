# Security Policy

## Protected Assets

This project protects two independent assets, using two separate cryptographic systems:

| Asset | Mechanism | Module |
|---|---|---|
| Garmin OAuth token | AES-256-GCM + Windows Credential Manager | `garmin_security.py` |
| Mirror archive (`mirror.gla`) | PBKDF2 master key → HKDF section keys → AES-256-GCM per section + HMAC-SHA256 header | `garmin_container.py` |

Additionally, the quality index (`quality_log.json`) is protected by a SHA-256 integrity checksum with automatic restore. See [Data Integrity](#data-integrity) below.

No data is sent to any server operated by this project. There is no telemetry and no cloud storage.
The app connects to external services only as described in [Network Connections](#network-connections).

---

## Token Security

The Garmin OAuth token grants access to your Garmin Connect account and is treated accordingly.

- Encrypted with **AES-256-GCM** before being written to disk
- Encryption key derived via **PBKDF2-HMAC-SHA256** (600,000 iterations — current OWASP recommendation)
- Encryption key stored in **Windows Credential Manager** — never on disk in plaintext
- A fresh random salt on every save — same key produces different ciphertext each time
- Tampered token files are detected on load (authenticated encryption)

| Threat | Protected? |
|---|---|
| Token file in cloud sync / accidental upload | ✅ Yes |
| Token file copied from disk without WCM access | ✅ Yes |
| Tampered token file | ✅ Yes — detected on load |
| Attacker with full Windows account access | ❌ No — system-level boundary |

### Token Event Log (v1.6.5.2, extended v1.6.5.7.1)

`garmin_token_log.json` records when and why a token was created, reused, or
invalidated (timestamp, event/trigger type, app version, which of the app's
entry points triggered it, exception type name, a truncated error string) —
introduced to measure actual token lifetime instead of guessing it. Routine
reuse (`valid`/`token_reused`, v1.6.5.7.1) carries no exception type or
error string, since no error occurred. This file is **not encrypted and not
a protected asset** in the sense of the table above, by design: it contains
no credentials, no token content, and no data that grants account access.
Sole write authority: `garmin_security.py`.

---

## Container Security

The Mirror feature packs the entire local archive into a single encrypted file (`mirror.gla`). This file is designed to be safe to store on untrusted media (USB drive, cloud sync folder, network share) without exposing any health data.

The container includes five sections: **raw, summary, context, source** (unmodified API responses), and **quality index**. Each section is independently encrypted.

The container uses a layered key design:

1. **Master key** — derived from the container password via PBKDF2-HMAC-SHA256
2. **Per-section keys** — derived from the master key via HKDF, one key per section (raw, summary, context, source, quality index). Compromising one section key does not affect others.
3. **Encryption** — AES-256-GCM per section. Each section is independently encrypted with a fresh nonce.
4. **Header authentication** — HMAC-SHA256 over the container header, verified before any decryption attempt. A manipulated header is detected immediately.

| Threat | Protected? |
|---|---|
| Container file copied from disk or cloud | ✅ Yes — useless without the password |
| Container file partially modified or corrupted | ✅ Yes — HMAC verification fails on open |
| Section-level tampering | ✅ Yes — AES-GCM authentication tag fails |
| Attacker with the container password | ❌ No — password is the trust boundary |
| Brute-force of a weak password | ⚠️ Partial — PBKDF2 with 600k iterations slows attacks; a strong password is the user's responsibility |

The container password is not stored anywhere by the application. It must be entered on each Mirror or Import operation.

### Plaintext Archive & Cloud Folders

The protections above cover the Garmin OAuth token and the Mirror container. The main archive itself — `raw/`, `summary/`, and `context_data/` — is **not encrypted**. This is a deliberate design choice (see [MINDSET.md](docs/MINDSET.md) for the "Open Archive over At-Rest Encryption" reasoning), but it has a practical consequence: if `garmin_data/` is placed inside a cloud sync folder (OneDrive, Dropbox, Google Drive, etc.), that sync client will upload your unencrypted health data automatically — this project has no way to detect or prevent that.

The same applies to data derived from the archive, all stored unencrypted under your base folder:

- `chats/` — saved Chat conversations. With live MCP tool-calling as the data source they contain the health data the model asked for. The API key is not stored in these files.
- `sqlite/mcp_cache.db` — a rebuildable, directly queryable copy of archive data (used by the MCP server and the Export Layer).
- Export Layer output (JSON, CSV, InfluxDB Line Protocol) — written wherever you point it.

None of these are part of the Mirror container; keep them outside cloud-synced folders as well.

If you need cloud storage or off-device backup, use the Mirror feature instead: it packs the entire archive into a single encrypted `.gla` file, which is safe to sync, as described above. For the live working archive, keep `garmin_data/` outside any cloud-synced folder, or accept the plaintext-in-cloud trade-off knowingly.

---

## Data Integrity

The quality index (`quality_log.json`) is the authoritative record of which days are archived and at what quality level. Corruption or silent modification would make the archive unreliable.

- A **SHA-256 checksum** is computed over stable core fields on every save
- The checksum is verified on every load
- A mismatch triggers **automatic restore** from the most recent monthly backup
- The corrupted file is preserved in `backup/autorestore/` before overwrite, for inspection

This is an integrity mechanism, not a confidentiality one — `quality_log.json` is not encrypted.

---

## Cloud LLM Chat (optional)

The Chat tab can use a local Ollama model or, optionally, a cloud provider (Anthropic or OpenAI). The cloud backend stays off until you select it and save an API key.

- The API key is stored in Windows Credential Manager, one entry per provider. It is not encrypted a second time and is not written into saved chats.
- With the cloud backend, your messages and the archive data used to answer them (live MCP query results or the daily summary, depending on the data source) are sent to the provider's API.
- Local Ollama models never leave your machine. If you select an Ollama cloud model (names ending in `-cloud`), Ollama sends your prompts to its own servers; GLA lists these like any other installed model.
- What a provider does with this data is governed by its own terms. See the AI disclaimer in the [README](README.md#project-status--disclaimer).

---

## MCP Server

The MCP server is optional and does not start with the app — only when you start it from the MCP tab or run the standalone MCP executable.

- It binds to `127.0.0.1` only (default port 8756); the host is not configurable.
- **It has no authentication.** Any program on the same machine that can reach that port can call its tools and read the archive. The tools are read-only queries, plus `refresh_cache`, which rebuilds the local cache.
- "Extra allowed hosts" (off by default, for clients in Docker via `host.docker.internal`) widens the host allow-list. The server still binds to `127.0.0.1`.

| Threat | Protected? |
|---|---|
| Web page in your browser calling the server | ✅ Yes — host/origin allow-list |
| Another computer on the network | ✅ Yes — bound to `127.0.0.1` |
| Another program on your machine querying the archive | ❌ No — no authentication; stop the server when you are not using it |

---

## Self-Update

The Windows builds can update themselves from GitHub Releases, triggered from the app or — only if you enable "Auto-apply updates in Daily Sync" (off by default) — by the scheduled daily sync.

- The release ZIP is checked against its SHA-256 checksum file, which is an asset of the same release. A release without a checksum file is refused.
- The previous version is kept in a backup folder. An update started from the app rolls back automatically if the new version does not start; the unattended variant does not.
- **Limits:** the checksum detects a corrupted or incomplete download. It does not prove who published the release (it comes from the same channel as the ZIP), and the executables are not code-signed. Update security therefore rests on the security of the maintainer's GitHub account and release workflow.

---

## Network Connections

| Connection | When | What is sent |
|---|---|---|
| Garmin Connect | every sync | login and requests for your own data |
| Open-Meteo, Brightsky (DWD) | context sync | coordinates, to fetch weather, pollen and air quality |
| GitHub Releases | update check and self-update | a request for the latest release; the release files are downloaded |
| Anthropic / OpenAI | only with the Chat tab's cloud backend | see [Cloud LLM Chat](#cloud-llm-chat-optional) |

---

## Reporting a Vulnerability

If you find a security issue — especially anything related to token handling,
credential exposure, container integrity, or the auth flow — please **do not open a public Issue**.

Report privately via GitHub's built-in mechanism:

**[Report a vulnerability (private)](../../security/advisories/new)**

Include:
- What you found
- How to reproduce it (if applicable)
- Which version you were using

I'll respond when time allows. This is a solo project with no SLA —
but auth-related reports will be prioritized.

---

## Out of Scope

- Garmin Connect itself, its API, or its SSO infrastructure
- Open-Meteo API (weather, air quality, pollen data — no account, no key)
- Brightsky / Deutscher Wetterdienst API (no account, no key)
- Anthropic, OpenAI and Ollama cloud services, if you choose to use them
- GitHub (release hosting)
- Issues caused by modified or self-compiled builds
- General Python or Windows security questions

---

## Supported Versions

Only the latest release on GitHub is actively maintained.
No backport fixes are provided.
