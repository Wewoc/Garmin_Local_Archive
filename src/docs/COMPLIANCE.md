# Compliance & License Audit

This document summarizes the measures taken to ensure license compliance
and copyright integrity for Garmin Local Archive (GLA). It serves as a
record of due diligence, not as a legal opinion.

## 1. License Model

GLA is fully licensed under the **GNU General Public License v3.0 (GPL-3.0)**.
The `LICENSE` file in the repository root contains the official full text.

Exception: `src/docs/correlation_concept.md` (including appendices) is
deliberately licensed under **CC BY-NC 4.0**, marked by its own license
block at the top of the file. This applies exclusively to that single
documentation file, not to the codebase.

## 2. Automated Checks (GitHub Actions)

- **CodeQL** (default setup): continuous scanning for security
  vulnerabilities in the codebase.
- **License Bestandsscan** (manually triggered, `.github/workflows/license-scan.yml`):
  - `pip-licenses` — lists licenses of all Python dependencies
  - `ScanCode Toolkit` — scans the entire codebase for embedded
    copyright notices and license fragments

Result of the first full scan (2026-09-05, 213 files): no findings of
unlicensed third-party code. All identified license mentions originate
either from the project's own dependency list or from the project's own
SPDX headers.

## 3. SPDX Headers

Most Python source files carry the header:

```
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)
```

A systematic check of which files still lack this header remains an
optional follow-up (`grep -L "SPDX-License-Identifier"`).

Note: source file headers were initially dated 2024 in error; GLA
originated in 2026. Correction of all affected headers is planned.

## 4. Architectural Plausibility Review

In addition to the automated scan, several core modules
(`gateway_map.py`, `metadata_map.py`, `daily_update.py`,
`clients/mcp_server.py`, `garmin_quality.py`) were reviewed for content
and architecture by a second, independent AI model (Google Gemini).

**Caveat:** This review is a plausibility check of writing style and
architecture — not a legal opinion and not a forensic comparison against
all existing code worldwide. No AI model (Gemini or Claude included) can
conclusively determine that code does not constitute a copyright
infringement; that is a legal judgment that, in a dispute, only a court
or a qualified professional can make. The review provides an
indicator — specifically, that the reviewed modules show no recognizable
copied, generic "third-party code fingerprint," but instead reflect
project-specific architectural decisions (e.g. routing/broker
separation, facade pattern with single-writer locking, degraded error
handling instead of exceptions).

## 5. History

The `LICENSE` file was at one point accidentally removed from the
repository and restored promptly upon discovery (commit history is
visible via `git log --all -- LICENSE`).

## 6. Conclusion

A multi-layered, documented due-diligence chain is in place: automated
dependency/license scanning, SPDX marking in the code, a consistent
project license, and a supplementary architectural plausibility review.
This does not constitute an absolute legal guarantee (which is
practically impossible for software of this scale), but it documents
traceable, repeatable verification steps.

*Last updated: 2026-09-05*
