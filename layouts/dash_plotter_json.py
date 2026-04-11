#!/usr/bin/env python3
"""
dash_plotter_json.py

JSON plotter — renders a specialist data dict to:
  - xxx.json       : structured data dump for programmatic use
  - xxx_prompt.md  : ready-to-use Markdown start prompt for Open WebUI / Ollama

Both files are always written together — the prompt is not optional.

Rules:
- No knowledge of Garmin internals, field names, or data sources.
- Fetches prompt templates from dash_prompt_templates.py.
- Receives neutral dict from dash_runner, writes output files.

Interface:
    render(data: dict, output_path: Path, settings: dict) -> None
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dash_prompt_templates as templates

# ══════════════════════════════════════════════════════════════════════════════
#  Internal builders
# ══════════════════════════════════════════════════════════════════════════════

def _build_json(data: dict) -> dict:
    """
    Build the JSON data structure from the specialist dict.
    Strips render-only keys (title, subtitle) and adds metadata.
    """
    return {
        "generated":  date.today().isoformat(),
        "date_from":  data.get("date_from", ""),
        "date_to":    data.get("date_to", ""),
        "profile":    data.get("profile", {}),
        "fields":     data.get("fields", []),
    }


def _build_prompt(data: dict) -> str:
    """
    Build the Markdown prompt from the specialist dict.
    Uses template_key from data — falls back to raw data summary if not found.
    """
    template_key = data.get("prompt_template") or data.get("template_key") or ""
    try:
        template_fn = templates.get(template_key)
        return template_fn(data)
    except KeyError:
        # No template registered — write minimal fallback prompt
        return (
            f"# Garmin Data Export\n\n"
            f"**Period:** {data.get('date_from', '?')} → {data.get('date_to', '?')}\n\n"
            f"No prompt template registered for this specialist type.\n"
            f"Template key: `{template_key}`\n"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Public interface
# ══════════════════════════════════════════════════════════════════════════════

def render(data: dict, output_path: Path, settings: dict) -> None:
    """
    Render specialist data dict to JSON + Markdown prompt.

    Args:
        data:        Dict from specialist.build() —
                     must contain "fields", "date_from", "date_to".
                     Optional: "profile", "template_key".
        output_path: Full path for the output .json file.
                     Prompt is written to same stem + "_prompt.md".
        settings:    Settings dict from GUI (unused here, reserved).

    Raises:
        ValueError: if no fields are present.
        OSError:    if output files cannot be written.
    """
    if not data.get("fields"):
        raise ValueError("render: no fields in data — nothing to render")

    output_path  = Path(output_path)
    prompt_path  = output_path.with_name(output_path.stem + "_prompt.md")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # JSON
    payload = _build_json(data)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Prompt
    prompt = _build_prompt(data)
    prompt_path.write_text(prompt, encoding="utf-8")