# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
diary/ — Tagebuch package (DIARY v1.7.8 — REMOVABLE).

Modules (Baustein 1, the core; see KONZEPT_tagebuch_V2.md and TODO_v178_tagebuch.md):
  diary_catalog.py  the fixed Set 1 fields (Garmin-compatible, entered by hand), data only
  diary_model.py    pure checks: dates, times, keys, definitions, entries, whole files
  diary_reader.py   read only: master file, day files, list of days
  diary_writer.py   sole writer of diary_data/ (next to garmin_data/ and context_data/)
  diary_backup.py   the backup copy of the diary, sole writer of garmin_data/backup/diary/ (Baustein 5)

The modules import each other with "from . import ..." and nothing outside the standard library, except
atomic_io (the shared atomic-write helper in garmin/, used by diary_writer.py and diary_backup.py) and, in
diary_backup.py, garmin_backup_common (a thin shell over it).
Later: search (3), the mirror container section (6). The package is not known to clients/mcp_server.py or to
any module of maps/ in v1.7.8.
"""
