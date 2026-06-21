#!/usr/bin/env python3
"""
garmin_redact.py

Leaf-Node — secret redaction for log output.
Replaces the live GARMIN_EMAIL / GARMIN_PASSWORD values with readable
placeholders before text reaches any log sink (file, GUI widget, clipboard).

Rules:
- Only import: garmin_config (for live credential values).
- No file I/O, no logging setup of its own.
- redact() reads cfg values fresh on every call — no caching — so it
  follows any importlib.reload(cfg) automatically.
"""

import logging

import garmin_config as cfg


def redact(text: str) -> str:
    """
    Replaces the current GARMIN_EMAIL / GARMIN_PASSWORD value (if non-empty)
    with a readable placeholder. Exact-value match only — no pattern
    matching on unknown exception text.
    """
    if not isinstance(text, str):
        return text

    email    = getattr(cfg, "GARMIN_EMAIL", "") or ""
    password = getattr(cfg, "GARMIN_PASSWORD", "") or ""

    if password:
        text = text.replace(password, "[GARMIN_PASSWORD]")
    if email:
        text = text.replace(email, "[GARMIN_EMAIL]")
    return text


class RedactFilter(logging.Filter):
    """
    logging.Filter — redacts GARMIN_EMAIL / GARMIN_PASSWORD from every
    LogRecord that passes through. Always returns True (never suppresses
    a record) — only mutates its text content.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True