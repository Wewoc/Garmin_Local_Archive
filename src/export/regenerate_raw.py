#!/usr/bin/env python3
"""
regenerate_raw.py

Regenerates raw/ and summary/ from the source/ archive.
No API calls needed — reads from garmin_data/source/, writes via garmin_writer.

Use this after garmin_normalizer.py has been updated to reprocess all days
from the immutable source record without re-authenticating against Garmin.

Downgrade protection: existing quality log entries with a higher label
(e.g. high) are never downgraded — even if the source file produces a lower
label. This protects days where source/ data is degraded (>180 days) but
raw/ was originally captured at full intraday resolution.

Documented Exception:
  Reads quality_log.json directly via _load_quality_log / _save_quality_log.
  Analog to regenerate_summaries.py — maintenance utility, offline, outside
  the live pipeline. garmin_writer is used for all file writes (not direct).

Configuration via environment variables — see garmin_config.py.

Options:
  --dry-run       Show what would be processed without writing any files.
  --date YYYY-MM-DD   Process a single date only.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# garmin/ must be on sys.path for all pipeline imports.
# export/ sits one level below src/ root; garmin/ is a sibling of export/.
sys.path.insert(0, str(Path(__file__).parent.parent / "garmin"))

try:
    import garmin_config as cfg
except ImportError as e:
    print(f"ERROR: Could not import garmin_config.py: {e}")
    sys.exit(1)

try:
    from garmin_normalizer import normalize, summarize
except ImportError as e:
    print(f"ERROR: Could not import garmin_normalizer.py: {e}")
    sys.exit(1)

try:
    import garmin_quality as quality
    from quality._io import _load_quality_log, _save_quality_log
except ImportError as e:
    print(f"ERROR: Could not import garmin_quality: {e}")
    sys.exit(1)

try:
    import garmin_writer as writer
except ImportError as e:
    print(f"ERROR: Could not import garmin_writer.py: {e}")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _existing_label(quality_data: dict, date_str: str) -> str | None:
    """Returns the current quality label for date_str, or None if not present."""
    for entry in quality_data.get("days", []):
        if entry.get("date") == date_str:
            return entry.get("quality")
    return None


def _rank(label: str | None) -> int:
    """Returns numeric rank for downgrade comparison."""
    return quality.QUALITY_RANK.get(label or "failed", 0)


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate raw/ and summary/ from source/ archive."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without writing any files.",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Process a single date only.",
    )
    args = parser.parse_args()

    dry_run     = args.dry_run
    single_date = args.date

    # ── Validate source dir ───────────────────────────────────────────────────
    if not cfg.SOURCE_DIR.exists():
        print(f"ERROR: Source folder not found: {cfg.SOURCE_DIR}")
        sys.exit(1)

    # ── Collect source files ──────────────────────────────────────────────────
    if single_date:
        src_file = cfg.SOURCE_DIR / f"garmin_source_{single_date}.json"
        if not src_file.exists():
            print(f"ERROR: No source file for {single_date}: {src_file}")
            sys.exit(1)
        source_files = [src_file]
    else:
        source_files = sorted(cfg.SOURCE_DIR.glob("garmin_source_*.json"))

    if not source_files:
        print("No source files found. Nothing to do.")
        sys.exit(0)

    # ── Ensure output dirs exist ──────────────────────────────────────────────
    if not dry_run:
        cfg.RAW_DIR.mkdir(parents=True, exist_ok=True)
        cfg.SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)

    mode_label = "[DRY RUN] " if dry_run else ""
    print(f"{mode_label}Regenerating raw/ and summary/ from {len(source_files)} source file(s) ...")
    print(f"  Source:  {cfg.SOURCE_DIR}")
    print(f"  Raw:     {cfg.RAW_DIR}")
    print(f"  Summary: {cfg.SUMMARY_DIR}")
    print()

    # ── Load quality log once ─────────────────────────────────────────────────
    if not dry_run:
        with quality.QUALITY_LOCK:
            quality_data = _load_quality_log()
    else:
        quality_data = {"first_day": None, "devices": [], "days": []}

    ok      = 0
    skipped = 0
    failed  = 0

    for src_file in source_files:
        # Extract date from filename: garmin_source_YYYY-MM-DD.json
        stem = src_file.stem  # garmin_source_YYYY-MM-DD
        date_str = stem.replace("garmin_source_", "")

        # Basic date validation
        try:
            date.fromisoformat(date_str)
        except ValueError:
            print(f"  ✗ {src_file.name}: cannot parse date from filename — skipped")
            failed += 1
            continue

        try:
            raw_source = json.loads(src_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ✗ {date_str}: cannot read source file: {e}")
            failed += 1
            continue

        try:
            normalized = normalize(raw_source, source="api")
            summary    = summarize(normalized)
            new_label  = quality.assess_quality(normalized)
            fields     = quality.assess_quality_fields(normalized)
        except Exception as e:
            print(f"  ✗ {date_str}: pipeline error: {e}")
            failed += 1
            continue

        # ── Downgrade protection ──────────────────────────────────────────────
        # If the existing quality log entry is higher than what source replay
        # produces, the day is skipped entirely — no file write, no log update.
        # Rationale: raw/ was captured at full intraday resolution (high);
        # source/ for days >180 days old may be degraded. The original high-
        # quality raw is the ground truth — replay cannot improve on it.
        existing = _existing_label(quality_data, date_str)
        if _rank(existing) > _rank(new_label):
            print(f"  ~ {date_str}: skipped (existing {existing} > replay {new_label})")
            skipped += 1
            continue

        if dry_run:
            existing_info = f" [existing: {existing}]" if existing else " [new]"
            print(f"  → {date_str}: would write ({new_label}){existing_info}")
            ok += 1
            continue

        # ── Write files ───────────────────────────────────────────────────────
        try:
            writer.write_day(normalized, summary, date_str)
        except Exception as e:
            print(f"  ✗ {date_str}: write_day failed: {e}")
            failed += 1
            continue

        # ── Update quality log ────────────────────────────────────────────────
        try:
            day = date.fromisoformat(date_str)
            with quality.QUALITY_LOCK:
                quality._upsert_quality(
                    quality_data,
                    day,
                    new_label,
                    f"Quality: {new_label} — source replay",
                    written=True,
                    source="api",
                    fields=fields,
                )
                _save_quality_log(quality_data)
        except Exception as e:
            print(f"  ✗ {date_str}: quality log update failed: {e}")
            failed += 1
            continue

        print(f"  ✓ {date_str} ({new_label})")
        ok += 1

    print()
    if dry_run:
        print(f"Dry run complete. {ok} would be processed, {skipped} downgrade-protected, {failed} errors.")
    else:
        print(f"Done. {ok} regenerated, {skipped} downgrade-protected, {failed} errors.")


if __name__ == "__main__":
    main()
