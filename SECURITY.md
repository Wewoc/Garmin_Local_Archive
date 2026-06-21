# Security Policy

## Protected Assets

This project protects two independent assets, using two separate cryptographic systems:

| Asset | Mechanism | Module |
|---|---|---|
| Garmin OAuth token | AES-256-GCM + Windows Credential Manager | `garmin_security.py` |
| Mirror archive (`mirror.gla`) | PBKDF2 master key → HKDF section keys → AES-256-GCM per section + HMAC-SHA256 header | `garmin_container.py` |

Additionally, the quality index (`quality_log.json`) is protected by a SHA-256 integrity checksum with automatic restore. See [Data Integrity](#data-integrity) below.

No data is sent to any server operated by this project.
No cloud storage, no telemetry, no third-party services beyond the external APIs listed in [Out of Scope](#out-of-scope).

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
- Issues caused by modified or self-compiled builds
- General Python or Windows security questions

---

## Supported Versions

Only the latest release on GitHub is actively maintained.
No backport fixes are provided.
