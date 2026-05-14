# Security Policy

## Scope

This project is a local-first personal tool. It handles one sensitive asset:
the Garmin OAuth token, which grants access to your Garmin Connect account.

No data is sent to any server operated by this project.
No cloud storage, no telemetry, no third-party services (except Open-Meteo for weather/pollen data, which requires no account).

---

## Token Security

The OAuth token is protected as follows:

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

## Reporting a Vulnerability

If you find a security issue — especially anything related to token handling,
credential exposure, or the auth flow — please **do not open a public Issue**.

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
- Open-Meteo API
- Issues caused by modified or self-compiled builds
- General Python or Windows security questions

---

## Supported Versions

Only the latest release on GitHub is actively maintained.
No backport fixes are provided.
