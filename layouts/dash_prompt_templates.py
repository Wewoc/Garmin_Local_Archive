#!/usr/bin/env python3
"""
dash_prompt_templates.py

Passive resource — Markdown prompt templates for JSON plotter output.
One template function per specialist type.

Rules:
- No logic beyond string formatting.
- No file I/O, no imports.
- Called exclusively by dash_plotter_json.py.

Each template function receives the specialist data dict and returns
a ready-to-use Markdown string for Open WebUI / Ollama context.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  Shared header / footer blocks
# ══════════════════════════════════════════════════════════════════════════════

_DISCLAIMER = (
    "> ⚠️ **Informational only — not medical advice.** "
    "Reference ranges are general health guidelines based on published research "
    "(AHA, ACSM, Garmin/Firstbeat). Individual variation is normal. "
    "Consult a healthcare professional for medical decisions."
)

_FOOTER = (
    "---\n"
    "*Generated locally by Garmin Local Archive · "
    "github.com/Wewoc/Garmin_Local_Archive · GNU GPL v3*"
)


# ══════════════════════════════════════════════════════════════════════════════
#  Template: health_analysis
#  Used by: health_garmin_*_dash.py
# ══════════════════════════════════════════════════════════════════════════════

def health_analysis(data: dict) -> str:
    """
    Generate a Markdown start prompt for health analysis data.
    Suitable as system context for Open WebUI / Ollama sessions.

    Args:
        data: Dict from specialist.build() with profile and fields.

    Returns:
        Markdown string ready to save as _prompt.md.
    """
    profile   = data.get("profile", {})
    fields    = data.get("fields", [])
    date_from = data.get("date_from", "")
    date_to   = data.get("date_to", "")

    age     = profile.get("age", "unknown")
    sex     = profile.get("sex", "unknown")
    vo2max  = profile.get("vo2max")
    fitness = profile.get("fitness", "unknown")

    vo2_str     = f"{vo2max:.1f}" if vo2max is not None else "not available"
    fitness_str = fitness.capitalize() if fitness else "unknown"

    # Build metric summary table
    table_rows = ""
    flagged    = []

    for entry in fields:
        field    = entry.get("field", "")
        label    = entry.get("label", field)
        unit     = entry.get("unit", "")
        avg      = entry.get("period_avg")
        baseline = entry.get("baseline_avg")
        ref_low  = entry.get("ref_low")
        ref_high = entry.get("ref_high")
        n_flags  = entry.get("flagged_days", 0)
        dates    = entry.get("flagged_dates", [])

        avg_str      = f"{avg:.1f} {unit}"      if avg      is not None else "—"
        baseline_str = f"{baseline:.1f} {unit}" if baseline is not None else "—"
        ref_str      = (
            f"{ref_low:.0f}–{ref_high:.0f} {unit}"
            if ref_low is not None and ref_high is not None else "—"
        )

        table_rows += (
            f"| {label} | {avg_str} | {baseline_str} | {ref_str} | {n_flags} |\n"
        )

        if n_flags > 0:
            dates_str = ", ".join(dates[-3:]) if dates else "—"
            flagged.append(f"- **{label}**: {n_flags} day(s) outside range — last flagged: {dates_str}")

    flagged_block = "\n".join(flagged) if flagged else "- No metrics flagged outside reference ranges."

    lines = [
        "# Garmin Health Analysis — Personal Context",
        "",
        _DISCLAIMER,
        "",
        "---",
        "",
        "## Analysis Period",
        "",
        f"**From:** {date_from}  ",
        f"**To:** {date_to}",
        "",
        "---",
        "",
        "## Personal Profile",
        "",
        f"| Parameter | Value |",
        f"|---|---|",
        f"| Age | {age} |",
        f"| Sex | {sex.capitalize() if sex else '—'} |",
        f"| VO2max | {vo2_str} |",
        f"| Fitness level | {fitness_str} |",
        "",
        "---",
        "",
        "## Metric Summary",
        "",
        "| Metric | Period avg | 90d baseline | Reference range | Flagged days |",
        "|---|---|---|---|---|",
        table_rows.rstrip(),
        "",
        "---",
        "",
        "## Flagged Metrics",
        "",
        flagged_block,
        "",
        "---",
        "",
        "## Instructions for Assistant",
        "",
        "You are a personal health data assistant. Your role is to help the user "
        "understand their Garmin health data in the context of the analysis above.",
        "",
        "- Refer to the metric summary and flagged days when answering questions.",
        "- Do not make medical diagnoses or prescribe treatments.",
        "- Highlight trends, patterns, and correlations when relevant.",
        "- Be concise. Use the user's language.",
        "- If asked about a metric not listed above, say it is not available in this dataset.",
        "",
        _FOOTER,
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Template registry — maps template key to function
#  Add new templates here as specialists grow.
# ══════════════════════════════════════════════════════════════════════════════

TEMPLATES = {
    "health_analysis": health_analysis,
}


def get(template_key: str) -> callable:
    """
    Return template function for a given key.
    Raises KeyError if template is not registered.
    """
    if template_key not in TEMPLATES:
        raise KeyError(f"dash_prompt_templates: unknown template '{template_key}'")
    return TEMPLATES[template_key]


def list_templates() -> list[str]:
    """Return all registered template keys."""
    return list(TEMPLATES.keys())