# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Timo (github.com/wewoc)

"""
add_spdx_headers.py
Garmin Local Archive — SPDX License Header Tool

Fügt GPL-3.0-or-later SPDX-Header in alle .py-Dateien ein die noch keinen haben.
Läuft standardmäßig im Dry-Run — erst anzeigen, dann auf Bestätigung patchen.

Verwendung:
    python add_spdx_headers.py              # Dry-Run (nur anzeigen)
    python add_spdx_headers.py --apply      # Wirklich schreiben
    python add_spdx_headers.py --root /pfad/zum/repo
"""

import argparse
import sys
from pathlib import Path

# ── Konfiguration ──────────────────────────────────────────────────────────────

HEADER_LINES = [
    "# SPDX-License-Identifier: GPL-3.0-or-later\n",
    "# Copyright (C) 2024 Wewoc (github.com/wewoc)\n",
]

HEADER_MARKER = "SPDX-License-Identifier"

# Verzeichnisse die übersprungen werden
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
    """Findet alle .py-Dateien rekursiv, überspringt SKIP_DIRS."""
    result = []
    for path in sorted(root.rglob("*.py")):
        # Prüfe ob ein SKIP_DIR im Pfad vorkommt
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        result.append(path)
    return result


def has_spdx_header(path: Path) -> bool:
    """Prüft ob die Datei bereits einen SPDX-Header hat."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 5:
                    # Header steht immer ganz oben — nach 5 Zeilen aufhören
                    break
                if HEADER_MARKER in line:
                    return True
    except (OSError, UnicodeDecodeError):
        return True  # Im Zweifel: nicht anfassen
    return False


def patch_file(path: Path) -> bool:
    """Fügt SPDX-Header am Anfang der Datei ein. Respektiert Shebang-Zeilen."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"  FEHLER beim Lesen: {path} — {e}")
        return False

    lines = content.splitlines(keepends=True)

    # Shebang in Zeile 1 behalten — Header kommt dahinter
    if lines and lines[0].startswith("#!"):
        insert_at = 1
        prefix = lines[:1]
        rest = lines[1:]
    else:
        insert_at = 0
        prefix = []
        rest = lines

    new_content = "".join(prefix + HEADER_LINES + ["\n"] + rest)

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
    print(f"\nGLA SPDX Header Tool — {mode}")
    print(f"Root: {root}")
    print("=" * 60)

    py_files = find_py_files(root)
    print(f"Gefundene .py-Dateien: {len(py_files)}\n")

    already_ok = []
    to_patch   = []

    for path in py_files:
        rel = path.relative_to(root)
        if has_spdx_header(path):
            already_ok.append(rel)
        else:
            to_patch.append((path, rel))

    # Bericht: bereits ok
    print(f"✓ Bereits mit Header ({len(already_ok)}):")
    for rel in already_ok:
        print(f"    {rel}")

    print()

    # Bericht: werden gepatcht
    print(f"→ Ohne Header — werden gepatcht ({len(to_patch)}):")
    for _, rel in to_patch:
        print(f"    {rel}")

    print()
    print("=" * 60)

    if not to_patch:
        print("Alle Dateien haben bereits einen SPDX-Header. Nichts zu tun.")
        return

    if not apply:
        print(f"DRY-RUN — keine Änderungen geschrieben.")
        print(f"Zum Anwenden: python add_spdx_headers.py --apply")
        return

    # Bestätigung
    print(f"\n{len(to_patch)} Dateien werden gepatcht. Fortfahren? [j/N] ", end="")
    answer = input().strip().lower()
    if answer not in ("j", "ja", "y", "yes"):
        print("Abgebrochen.")
        return

    patched = 0
    failed  = 0
    for path, rel in to_patch:
        if patch_file(path):
            print(f"  ✓ {rel}")
            patched += 1
        else:
            print(f"  ✗ {rel}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Fertig — {patched} gepatcht, {failed} fehlgeschlagen.")


# ── Entry Point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fügt SPDX GPL-3.0-or-later Header in .py-Dateien ein."
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
