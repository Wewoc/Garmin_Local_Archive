# Encrypted Dashboard Viewer — Companion Concept

> ⚠️ **Read the README and the current codebase first.**
> This is a concept document — it describes where the project could go, not where it is.
>
> Nothing here is implemented. Nothing is committed or scheduled.
> All module names, interfaces, and structures are placeholders.
> Concrete decisions will be made when actual development begins.
>
> **Dependency:** Requires v1.6.1 (Encrypted Dashboards) to be complete and stable
> before any Viewer development begins. The encrypted HTML format defined in v1.6.1
> is the contract this Viewer builds on.

---

## Purpose

The Viewer is a lightweight Android companion app that allows a recipient to open,
decrypt, and view an encrypted dashboard — on their device, without any server
involvement, without any cloud dependency beyond the file transport itself.

It extends the "Local-only" philosophy to the receiving end: the person who created
the dashboard controls the encryption and the file's availability; the person who
receives it controls the decryption. No third party ever sees the plaintext.

Primary use case: sharing health data with a trainer, doctor, or trusted person
without transmitting sensitive data in readable form.

**Naming note:** The app is intentionally named "Encrypted Dashboard Viewer", not
"Garmin Viewer". The encrypted HTML format is the only contract — the Viewer has no
knowledge of Garmin, health data, or any specific dashboard content. This makes it
source-agnostic by design: future data sources added to the main project (v2.0+)
work with the same Viewer without modification.

---

## Security Model — Two Independent Layers

The Viewer operates across two security layers that are explicitly separated:

**Layer 1 — Transport:** How does the file reach the recipient?
A shared link to a file hosted on any cloud drive (Google Drive, OneDrive, Proton
Drive, Nextcloud, or any direct HTTPS URL). The link acts as a revocable access token.
No OAuth integration — a public or shared-link URL is functionally equivalent to a
long access token and is provider-agnostic.

**Layer 2 — Content:** Is the file readable without the password?
No. The HTML file is encrypted with AES-256-GCM (the same mechanism used in v1.6.1).
Without the correct password, the file is unreadable — regardless of who has the link.

**Combined model:**
```
Creator (PC)                  Recipient (Android)
────────────                  ───────────────────
1. Build dashboard
2. Encrypt with password
3. Upload to cloud drive
4. Generate share link   →    Scan QR or paste link → app downloads file
5. Send password via          Enter password
   separate channel      →    Decryption runs locally on device
   (Signal, SMS, etc.)        Dashboard displayed in WebView
```

The link and the password must travel via separate channels. A link alone is useless
without the password. A password alone is useless without the file.

---

## Two-Factor Share

The share model consists of exactly two components:

| Component | What it is | How it travels |
|---|---|---|
| **Link** | HTTPS URL to the encrypted file | QR code scan or manual paste |
| **Password** | AES-256-GCM decryption key | Separate channel (Signal, SMS, verbal) |

Both components are required. Neither is stored on any server. Neither is transmitted
by the app to any external service.

**QR code as the primary link transport:**
The PC app (v1.6.1+) generates a QR code from the share link at export time. The
recipient scans it with the Android app. No manual URL input, no clipboard, no
copy-paste across potentially insecure channels.

---

## Access Control — Existence Check

The Viewer does not implement a time-based expiry field. Instead, the creator controls
access by controlling the cloud link. The Viewer enforces this on every open:

```
Recipient opens a saved dashboard
        │
        ├── HEAD request to original source URL
        │         │
        │         ├── 200 OK  → file still live → open local copy
        │         └── 404 / 403 / gone → creator removed access → delete local copy
        │
        └── No network → behaviour intentionally undefined (open question)
```

**Why HEAD and not GET:** No re-download on every open — only an existence check.
Minimal traffic, instant response.

**What this means for the creator:**
Removing or deactivating the share link on the cloud drive is the revocation
mechanism. The Viewer enforces this on the next open attempt. There is no
"remote delete" of files already on the recipient's device — revocation affects
only the next check, not files that have already been opened offline.

This must be clearly documented in the Viewer's user-facing text to avoid false
expectations of a remote-wipe capability.

**Offline behaviour:** Intentionally left open. Whether the Viewer allows opening
a locally cached file when no network is available (e.g. grace period based on
`last_verified` timestamp) or blocks entirely is an implementation decision to be
made when real usage patterns are known. Both are architecturally valid.

**Container structure per saved entry:**
```
Saved Entry
├── label           — user-defined name ("Dr. Müller", "Coach Jan")
├── source_url      — original share link (used for HEAD check + re-download)
├── encrypted_file  — local copy in app's private storage (Android sandbox)
├── password        — stored in Android Keystore (encrypted, device-bound)
└── last_verified   — timestamp of last successful HEAD check
```

---

## What the App Does — and Does Not Do

**Does:**
- Accept a share link via QR scan or manual URL input
- Download the encrypted HTML file over HTTPS (direct download link required — see below)
- Store the downloaded file in the app's private sandboxed storage
- Perform a HEAD check on every open to verify the creator has not revoked access
- Prompt for the decryption password
- Decrypt the file locally (Web Crypto API via WebView)
- Display the decrypted dashboard in an embedded WebView
- Cache the password per saved entry using Android Keystore
- Verify Web Crypto API availability at app start — fail cleanly if unavailable

**Does not:**
- Transmit the password anywhere
- Upload any data
- Require an account or registration
- Require a specific cloud provider
- Communicate with any backend server beyond the HEAD check and initial download
- Access any data outside the downloaded file

---

## Direct Download Link Requirement

Cloud providers do not serve share links as direct file downloads. A Google Drive
share link delivers an HTML preview page, not the raw file. The Viewer cannot parse
provider-specific landing pages.

**The requirement:** The creator must supply a *direct download URL* — a link that
responds to an HTTPS GET with the raw file bytes, and to a HEAD request with a
meaningful status code (200 if available, 404/403 if removed).

**Provider guidance (to be documented per provider at implementation time):**

| Provider | Direct download approach |
|---|---|
| Google Drive | `https://drive.google.com/uc?export=download&id=FILE_ID` |
| OneDrive | "Embed" link option provides a direct URL |
| Nextcloud / own server | Direct file link by default |
| Proton Drive | No public direct download link currently — evaluate at implementation time |

This is a UX concern for the creator, not a technical limitation of the Viewer.
The PC app's export dialog should explain this clearly and link to per-provider
instructions.

---

## Architecture

The app is intentionally minimal. The decryption logic already lives inside the
encrypted HTML file itself (v1.6.1 design) — the app is a secure wrapper, not a
decryption engine.

```
Android App
├── QR Scanner         — reads share link
├── HTTP Client        — HTTPS GET (initial download) + HEAD (existence check)
├── Local Storage      — Android private app storage (sandboxed)
├── Password Input     — native Android UI
├── WebView            — loads local HTML file, JS decryption runs inside
│                        Web Crypto API capability check at startup
└── Android Keystore   — password cache per saved entry (encrypted, device-bound)
```

The WebView loads the file from local storage, not from a URL. The decryption
password is injected via a JavaScript bridge at load time. After decryption, the
plaintext dashboard exists only in WebView memory — it is never written to disk.

---

## PC-Side Changes (v1.6.1+)

The Android Viewer requires one addition to the v1.6.1 export flow on the PC:

- **QR code generation** at export time — renders the share link as a QR code
  displayed in the GUI (or saved as a PNG alongside the encrypted HTML file)

This is the only change required on the PC side. The encrypted HTML format itself
is unchanged — the Viewer is a consumer of the v1.6.1 output, not a co-author of it.

---

## Implementation Options

Two paths are viable. The decision depends on distribution intent.

**Option A — Minimal WebView App (Kotlin / Jetpack Compose)**
Native Android app. Full control over WebView security flags, Keystore integration,
and file handling. Suitable for Play Store distribution or sideload APK.

**Option B — Flutter**
Cross-platform from the start. Relevant if an iOS companion becomes desirable later.
Slightly more overhead for a project that currently has no iOS presence.

No decision is made here. Evaluate at implementation time based on the scope that
is actually needed.

---

## Relationship to the Main Project

The Viewer is a **separate repository and separate release** — not part of the
Garmin Local Archive Python codebase. It shares no code with the main project.

The contract between the two is the encrypted HTML format defined in v1.6.1.
As long as that format is stable, the Viewer is fully independent.

```
Garmin Local Archive (Python, Windows)
└── v1.6.1: produces encrypted HTML + QR code
                    │
                    │  contract: encrypted HTML format + AES-256-GCM spec
                    ▼
Encrypted Dashboard Viewer (Android)
└── downloads, existence-checks, decrypts, displays — source-agnostic
```

---

## Open Questions

These are not decisions — they are questions to answer when development begins.

- **Distribution:** Play Store (requires developer account, review process) or
  sideload APK only (simpler, limits reach)?
- **Offline behaviour:** Allow opening cached file without network (grace period
  based on `last_verified`)? Or block entirely without a successful HEAD check?
  Decision deferred — depends on real usage patterns.
- **QR code library on PC side:** Generate inline in the GUI or write to file?
  Which library fits the existing stack without adding heavyweight dependencies?
- **Password injection into WebView:** JavaScript bridge (straightforward) or
  alternative mechanism? Security implications to evaluate at implementation time.
- **File format versioning:** If the encrypted HTML format changes in a future
  version, how does the Viewer handle older files? Version field in the HTML needed?
- **Proton Drive:** No known direct download URL mechanism currently. Evaluate
  when development begins — may need to be listed as unsupported at launch.

---

## Not Planned

- iOS support (no current need; Option B leaves the door open)
- OAuth integration with specific cloud providers
- Any backend server or relay service
- Any analytics, telemetry, or usage tracking
- Automatic dashboard refresh or push notifications
- Remote deletion of files from recipient devices

---

*Concept recorded after v1.5.4. Implementation begins after v1.6.1 is stable.*
