"""
theme.py — Garmin Local Archive, central design base colors (Single Source of Truth)

This file can be opened with any text editor (Notepad works too).

HOW DOES THIS WORK?
Below are one or more complete color schemes (THEME_1, THEME_2, ...).
Which one is active is stored in the app settings (active_theme), set via
Settings tab → Design in the app itself — no manual editing needed here
for a normal theme switch (restart the program afterwards). The rest of
the app reads the values via BG, ACCENT, TEXT etc. (auto-resolved from the
active theme below — don't change that part).

Adding a new theme: copy an existing THEME_x dict, adjust the values, give
it the next free number, and register it in _THEMES. No limit on how many.
It will then appear automatically in the app's theme dropdown.

COLOR ROLES (same meaning in every theme):
  bg0      — deepest background, for inset elements (e.g. the log console)
  bg       — main background (window)
  bg2      — raised surface (cards, header)
  bg3      — dividers, row striping, third layer
  accent   — primary: active tabs, primary buttons, links, focus
  accent2  — secondary: hover state of accent
  text     — main text
  text2    — secondary text, labels, muted
  green    — success / OK
  yellow   — warning
  red      — error

Tip: VS Code shows a small color swatch next to every hex code. Clicking it
opens a color picker that replaces the value automatically.

Palette inspiration (if you're looking for new values):
  https://coolors.co
  https://color.adobe.com
  https://paletton.com

Function-specific colors (heart-rate orange, sleep phases, quality
indicators EXCELLENT/GOOD/FAIR/POOR etc.) are deliberately NOT here — they
stay in their respective files (dash_layout.py, layouts/render/live.py,
dash_plotter_excel.py etc.), because they carry domain meaning rather than
pure theme aesthetics. They should look the same regardless of the chosen
theme (e.g. stress is always green, in every theme).
"""

# ── Theme selection ─────────────────────────────────────────────────────
# Which theme is active — read from app settings (active_theme), set via
# Settings tab → Design in the app. Falls back to 1 (Monochrome + Rust Accent) if
# the settings file has no value yet (fresh install) or an invalid one.
#
#   1 — Monochrome + Rust Accent  (default)
#   2 — Violet           (original)
#   3 — Amber & Copper
#   4 — Olive & Sand
#   5 — Toxic            (metallic/silver + toxic olive-green accent)
#   6 — Ice Blue         (steel base + deep blue accent)
#
# Removed: Bordeaux (was 3) — its dark-red accent conflicted with the
# app-wide convention that red is reserved for error/failure states
# (see REFERENCE_INVARIANTEN.md, DateToggleCalendar). Numbers below were
# renumbered (not left with a gap) — a saved active_theme: 3 from before
# this change now loads what used to be Amber & Copper (was 4) instead of
# falling back to the default. Anyone who built a custom theme on top of
# THEME_4..THEME_7 needs to renumber it to match after updating.
import garmin_app_settings as _settings

ACTIVE_THEME = _settings.load_settings().get("active_theme", 1)

# ── Theme table ───────────────────────────────────────────────────────────
# Add as many further THEME_x entries as you like — see note above.

THEME_1 = {
    "name":    "Monochrome + Rust Accent (default)",
    "bg0":     "#0a0b0c",
    "bg":      "#111214",
    "bg2":     "#191b1e",
    "bg3":     "#232629",
    "accent":  "#c76a3f",
    "accent2": "#9c5330",
    "text":    "#e8e9eb",
    "text2":   "#9a9ea3",
    "green":   "#4ecca3",
    "yellow":  "#f5c542",
    "red":     "#e94560",
}

THEME_2 = {
    "name":    "Violet (Legacy)",
    "bg0":     "#0a0a1a",
    "bg":      "#12101f",
    "bg2":     "#1a1729",
    "bg3":     "#231f38",
    "accent":  "#a259f7",
    "accent2": "#6e3fcf",
    "text":    "#eaeaea",
    "text2":   "#a0a0b0",
    "green":   "#4ecca3",
    "yellow":  "#f5a623",
    "red":     "#e94560",
}

THEME_3 = {
    "name":    "Amber & Copper",
    "bg0":     "#0d0a08",
    "bg":      "#161210",
    "bg2":     "#201a17",
    "bg3":     "#2b231e",
    "accent":  "#d98a3d",
    "accent2": "#b56c28",
    "text":    "#f0e6da",
    "text2":   "#b8a894",
    "green":   "#4ecca3",
    "yellow":  "#f5c542",
    "red":     "#e94560",
}

THEME_4 = {
    "name":    "Olive & Sand",
    "bg0":     "#0e0f0a",
    "bg":      "#14150f",
    "bg2":     "#1c1e15",
    "bg3":     "#262919",
    "accent":  "#a9b34d",
    "accent2": "#818c37",
    "text":    "#eeeadb",
    "text2":   "#aeaa96",
    "green":   "#4ecca3",
    "yellow":  "#f5c542",
    "red":     "#e94560",
}

THEME_5 = {
    "name":    "Toxic",
    "bg0":     "#0a0c0b",
    "bg":      "#121513",
    "bg2":     "#262c2a",
    "bg3":     "#3a423e",
    "accent":  "#7a9e00",
    "accent2": "#6b8c00",
    "text":    "#e4e8e5",
    "text2":   "#9aa39d",
    "green":   "#4ecca3",
    "yellow":  "#f5c542",
    "red":     "#e94560",
}

THEME_6 = {
    "name":    "Ice Blue",
    "bg0":     "#0a0c0b",
    "bg":      "#121513",
    "bg2":     "#262c2a",
    "bg3":     "#3a423e",
    "accent":  "#1f6488",
    "accent2": "#184e69",
    "text":    "#e4e8e5",
    "text2":   "#9aa39d",
    "green":   "#4ecca3",
    "yellow":  "#f5c542",
    "red":     "#e94560",
}

# To add a further theme: copy a dict above, adjust the values, register it
# below in _THEMES. Example:
#
# THEME_7 = {
#     "name":    "My new theme",
#     "bg0":     "#......",
#     "bg":      "#......",
#     "bg2":     "#......",
#     "bg3":     "#......",
#     "accent":  "#......",
#     "accent2": "#......",
#     "text":    "#......",
#     "text2":   "#......",
#     "green":   "#......",
#     "yellow":  "#......",
#     "red":     "#......",
# }

_THEMES = {
    1: THEME_1,
    2: THEME_2,
    3: THEME_3,
    4: THEME_4,
    5: THEME_5,
    6: THEME_6,
}

# ── Resolve the active theme (don't change anything below this line) ──────
# Falls back to theme 1 if active_theme in settings is an unknown/invalid
# number (e.g. leftover value from a removed theme).
_active = _THEMES.get(ACTIVE_THEME, THEME_1)

BG0     = _active["bg0"]
BG      = _active["bg"]
BG2     = _active["bg2"]
BG3     = _active["bg3"]
ACCENT  = _active["accent"]
ACCENT2 = _active["accent2"]
TEXT    = _active["text"]
TEXT2   = _active["text2"]
GREEN   = _active["green"]
YELLOW  = _active["yellow"]
RED     = _active["red"]

# ── Excel color tokens (openpyxl expects hex WITHOUT '#') ──────────────────
# Used by dash_layout.py for the Excel export header fill, so Excel
# reports match the chosen app theme instead of a fixed navy. Header font
# stays fixed black in dash_layout.py (checked for contrast against every
# built-in theme's accent) — no themed token needed for it.
ACCENT_EXCEL = ACCENT.lstrip("#")
