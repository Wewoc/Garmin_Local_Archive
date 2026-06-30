# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

"""
update_spdx_copyright.py
Garmin Local Archive — SPDX Copyright Update Tool

Ersetzt den alten Copyright-Header (Timo) durch den neuen (Wewoc).
Läuft standardmäßig im Dry-Run — erst anzeigen, dann auf Bestätigung patchen.

Verwendung:
    python update_spdx_copyright.py              # Dry-Run (nur anzeigen)
    python update_spdx_copyright.py --apply      # Wirklich schreiben
    python update_spdx_copyright.py --root /pfad/zum/repo
"""

import argparse
import sys
from pathlib import Path

# ── Konfiguration ──────────────────────────────────────────────────────────────

OLD_COPYRIGHT = "# Copyright (C) 2024 Timo (github.com/wewoc)\n"
NEW_COPYRIGHT = "# Copyright (C) 2024 Wewoc (github.com/wewoc)\n"

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    ".mypy_cache",
    ".ruff_cache",
}

# ── Logik ──────────────────────────────────────────────────────────────────────

def find_py_files(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        result.append(path)
    return result


def needs_update(path: Path) -> bool:
    """Prüft ob die Datei den alten Copyright-Header enthält."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 5:
                    break
                if line == OLD_COPYRIGHT:
                    return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


def update_file(path: Path) -> bool:
    """Ersetzt den alten Copyright-Header durch den neuen."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"  FEHLER beim Lesen: {path} — {e}")
        return False

    if OLD_COPYRIGHT not in content:
        return False

    new_content = content.replace(OLD_COPYRIGHT, NEW_COPYRIGHT, 1)

    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        return True
    except OSError as e:
        print(f"  FEHLER beim Schreiben: {path} — {e}")
        return False


# ── Haupt-Logik ────────────────────────────────────────────────────────────────

def run(root: Path, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\nGLA SPDX Copyright Update Tool — {mode}")
    print(f"Root: {root}")
    print(f"ALT: {OLD_COPYRIGHT.strip()}")
    print(f"NEU: {NEW_COPYRIGHT.strip()}")
    print("=" * 60)

    py_files = find_py_files(root)
    print(f"Gefundene .py-Dateien: {len(py_files)}\n")

    to_update  = []
    already_ok = []
    skipped    = []

    for path in py_files:
        rel = path.relative_to(root)
        try:
            with open(path, encoding="utf-8") as f:
                lines = [next(f, "") for _ in range(6)]
            content_head = "".join(lines)

            if OLD_COPYRIGHT in content_head:
                to_update.append((path, rel))
            elif NEW_COPYRIGHT in content_head:
                already_ok.append(rel)
            else:
                skipped.append(rel)
        except (OSError, UnicodeDecodeError):
            skipped.append(rel)

    print(f"✓ Bereits aktuell ({len(already_ok)}):")
    for rel in already_ok:
        print(f"    {rel}")

    print()
    print(f"→ Wird aktualisiert ({len(to_update)}):")
    for _, rel in to_update:
        print(f"    {rel}")

    if skipped:
        print()
        print(f"○ Kein GLA-Header — übersprungen ({len(skipped)}):")
        for rel in skipped:
            print(f"    {rel}")

    print()
    print("=" * 60)

    if not to_update:
        print("Nichts zu aktualisieren.")
        return

    if not apply:
        print(f"DRY-RUN — keine Änderungen geschrieben.")
        print(f"Zum Anwenden: python update_spdx_copyright.py --apply")
        return

    print(f"\n{len(to_update)} Dateien werden aktualisiert. Fortfahren? [j/N] ", end="")
    answer = input().strip().lower()
    if answer not in ("j", "ja", "y", "yes"):
        print("Abgebrochen.")
        return

    updated = 0
    failed  = 0
    for path, rel in to_update:
        if update_file(path):
            print(f"  ✓ {rel}")
            updated += 1
        else:
            print(f"  ✗ {rel}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Fertig — {updated} aktualisiert, {failed} fehlgeschlagen.")


# ── Entry Point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aktualisiert den SPDX Copyright-Namen in allen .py-Dateien."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Wirklich schreiben (ohne diesen Flag: Dry-Run)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent,
        help="Repo-Root (Standard: Verzeichnis dieser Datei)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        print(f"FEHLER: Root-Verzeichnis nicht gefunden: {root}")
        sys.exit(1)

    run(root=root, apply=args.apply)


if __name__ == "__main__":
    main()
