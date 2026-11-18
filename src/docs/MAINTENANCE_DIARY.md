# Garmin Local Archive — Diary Maintenance Guide

Maintenance, debugging and extension guide for the diary (`diary/` package, the "Diary" tab, v1.7.8).
For build and release process see `MAINTENANCE_GLOBAL.md`.
For the complete function reference see `REFERENCE_DIARY.md`.

---

## Architecture

```
Tab "Diary" (app/panel_diary.py)
  ├── diary_reader.read_master / read_day / list_days / search_notes      (read only)
  ├── diary_writer.save_day / create_user_field / rename_field / ...      (writes diary_data/)
  └── diary_backup.backup_day / backup_master / backup_all                (writes garmin_data/backup/diary/)

Mirror container: garmin_container (section "diary")  ←→  garmin_import_mirror → diary_writer.restore_day/restore_master
```

### Module ownership

| Module | Sole write authority |
|---|---|
| `diary_writer.py` | `diary_data/` (`fields.json`, `days/`; also the `.damaged` remnants of a restore) |
| `diary_backup.py` | `garmin_data/backup/diary/` (`days/` through `garmin_backup_common`, `master/`) |

`garmin_import_mirror.py` writes no diary file itself: it hands the bytes of the container to
`diary_writer.restore_day()` / `restore_master()`, which check every file again.

### Invariants

- `diary_writer` is the only module that creates or removes files in `diary_data/`; `diary_backup` is the only
  one that writes below `garmin_data/backup/diary/`. A second writer is a regression.
- The package `diary/` imports only the standard library and its own modules, except `diary_backup.py`
  (`garmin_backup_common`, which is not changed by the diary). A test reads the imports with `ast`.
- No module of `clients/` or `maps/` mentions the diary (no way to the MCP server, no broker). A test checks it.
- No log line carries a note, a value, a field name or a search word (the log has the date, the key, the kind of
  an error). Tests capture the log and look for strings that occur nowhere else.
- A definition never changes after the field was made, except its display name. Keys are never reused. A day file
  keeps a `key_snapshot` of the definitions it uses; the snapshot only gains keys.
- A free day (first saved today) is overwritten by a save; an older day is refused (`history_required`) unless the
  caller says `keep_history=True`; then the state before is appended to `history` (only appended, oldest first).
- A file that cannot be read is never overwritten, never copied over a good copy, and a file of a newer
  `schema_version` is never interpreted or replaced. A restore keeps the file it replaces as `.damaged`.
- A readable day is never replaced by a restore or by the mirror import (the diary has no quality hierarchy and
  nothing to decide which of two stands is right).
- Nothing in the diary raises for bad input: every function answers with a status or a state.
- Workers never touch widgets: the backup at the start runs in a thread and tells a failure through
  `GarminApp._dispatch()`.

---

## `test_diary.py` and `test_diary_panel.py`

Check and section totals are tracked in `docs/METRICS.md` (`test_diary.py`, `test_diary_panel.py`) — not restated
here to avoid drift. `test_diary.py` is a script test (`python tests/test_diary.py`, registered in `run_tests.ps1`
and in `tests/conftest.py` `collect_ignore`); `test_diary_panel.py` is a pytest file with one real `GarminApp`
window (more than one window in one pytest process ends in a crash of the interpreter at exit in this
environment).

```bash
python tests/test_diary.py
python -m pytest tests/test_diary_panel.py
```

### What is tested

`test_diary.py` (script, no Qt):
1. Catalogue and start templates (`diary_catalog`)
2. Model: dates, times, keys, names; definitions (also text and groups of alternatives); entries; whole files;
   time stamps and the history of a day
3. Writer: fields, `save_day` (free window, `history_required`, `keep_history`, emptied day removed, atomic write with a
   failing move, locked file, damaged and newer files), `restore_history`, `recover_master`, `restore_day`,
   `restore_master`
4. Reader: states, names, `search_notes` (words, case, literal characters, snippets, limits, unreadable days, notes only)
5. Backup: `diary_backup` (copy after a change, ZIP of a completed month, valid files only, never deleted,
   `backup_all`, `check`)
6. Privacy of the log (no note, value, name or search word)
7. Guards: the imports of the package, `build_manifest.py`, no mention in `clients/` and `maps/`

`test_diary_panel.py` (pytest-qt, mocked app): layout and calendar, archive folder, note, dots, delete all,
unsaved note questions, closing, the entry boxes (decimal comma, empty is not 0, Yes/No, text, alternatives), fields
(create, favorite, dropdown rules, templates, manage), the history question and dialog, backup after changes and at
the start, restore from backup, search box, the tab in the real window.

Also covered elsewhere: `test_container_mirror.py` (section `diary`: classification, packing, an older program reads the
container, an old container), `test_import_mirror.py` section 4h4 (the import rules, conflicts, safety of paths) and
`test_qt_app.py` (`_import_preview_text`, `_import_result_text`).

### What is NOT tested

- A built program (the diary in a `.exe`/package): only a test build shows it
- Network and the cloud: the diary has none
- A real mirror of a real archive with a diary (the container tests use hand-built containers)
- Timing of the background backup in the real window (the tests replace the thread by a synchronous stand-in)

### When to run

After any change to: `diary/*`, `app/panel_diary.py`, `app/diary_entry_editor.py`, `app/dialog_diary_*.py`,
`garmin_container.py` (section `diary`), `garmin_import_mirror.py` (diary import), `garmin_backup_common.py`
(the backup of the diary uses it), `compiler/build_manifest.py`.

---

## Extending

### A new Set 1 field (`diary_catalog.CATALOG`)

Only with an observed Garmin response in the repository (provenance rule): a new entry gets a new key (`G004`...);
an existing entry never changes. The field is taken into a user's list when first chosen (`activate_catalog_field`);
the list keeps a copy of the definition, so a changed catalogue text does not reach an archive that already
activated the field.

### A new start template

Add it to `diary_catalog.TEMPLATES` (name unique, also compared without regard to case, not the name of a catalogue
field). A template is copied into a normal user field when chosen; a used template is no longer offered.

### A new value type

`diary_model` (`VALUE_TYPES`, `check_definition`, `check_entries`), the entry boxes (`diary_entry_editor.py`), the
dialog "Create field", the hint line of a field in the panel and `dialog_diary_history.describe_state`. A definition
that uses a type an older program does not know is read as damaged by that program.

### A change of a file format

Raise `diary_model.SCHEMA_VERSION`; older programs then read the files as `unsupported` (left alone). The mirror
container keeps the format byte `0x01`.

---

## Debugging

### The tab says a day cannot be read

The file is damaged (not JSON, or it fails the checks of a day). It is left untouched. "Restore from backup" is
enabled when a valid copy exists; the damaged file is kept next to the restored one as `diary_<date>.json.damaged`.
`diary_backup.check(base)` lists damaged days and which of them are restorable.

### "Not saved" for an older day

The writer answers `history_required` for a day first saved on an earlier calendar day; the panel asks once per day
shown. A refusal leaves everything as it was (what was typed stays in the boxes).

### The field list is lost or damaged

"Restore from backup" restores it from `garmin_data/backup/diary/master/fields.json` (flags included). If the copy
does not fit the days (`copy_behind`, `days_unreadable`) or there is none, `diary_writer.recover_master(base)` rebuilds
it from the key snapshots of the days (flags start false; a key made and never used in a day cannot be found again).

### A mirror import left days out

The result line says "N diary day(s) left out (their fields do not fit)": the field keys of those days mean something
else in this archive (two archives that made fields on their own). Nothing is guessed; the days stay in the container.
A readable day here is never replaced.

### The backup says it could not copy

The status line says "The backup copy could not be made (see the log)". The log line starts with `backup_diary:` and
names the date and the kind of the error (disk full, folder locked). The next change or the next start tries again.

---

## Removal

Every file carries the marker `DIARY v1.7.8 — REMOVABLE`. To remove the diary: the package `diary/`, the five files
`app/panel_diary.py`, `app/diary_entry_editor.py`, `app/dialog_diary_*.py`, the entries in `compiler/build_manifest.py`,
the `PanelDiary` lines in `garmin_app_base.py`, the entries of `run_tests.ps1` and `tests/conftest.py`, the two
test files, and (to leave the mirror as before) the `diary` section in `garmin_container.py`, the diary import in
`garmin_import_mirror.py` and the diary lines in `app/panel_archive.py`.
