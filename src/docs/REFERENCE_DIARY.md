# Garmin Local Archive — Diary Reference

Technical reference for the diary (`diary/` package and the "Diary" tab, v1.7.8).
For shared paths, constants and project structure see `REFERENCE_GLOBAL.md`.
For maintenance, ownership rules and tests see `MAINTENANCE_DIARY.md`.

The diary holds what the user types by hand (a note per day, values such as blood pressure,
hydration, weight, medication, cycle). It is the only data of GLA that cannot be built again:
there is no source to fetch it from. Hence it has a second copy (backup, mirror container).
Everything of it is removable (marker `DIARY v1.7.8 — REMOVABLE`).

---

## Architecture overview

```
Tab "Diary" (app/panel_diary.py)
  ├── reads    → diary_reader      (read only: master, days, search)
  ├── writes   → diary_writer      (sole writer of diary_data/)
  ├── copies   → diary_backup      (sole writer of garmin_data/backup/diary/)
  └── dialogs  → dialog_diary_field (Create field), dialog_diary_manage (Manage fields),
                 dialog_diary_history (History); boxes of a field: diary_entry_editor

Mirror container (garmin_container.py, garmin_import_mirror.py)
  ├── lock():  section "diary" = diary_data/fields.json + diary_data/days/diary_YYYY-MM-DD.json
  └── import:  restore through diary_writer.restore_day() / restore_master()
```

**Key principle:** the package `diary/` imports only the standard library and its own modules;
the one exception is `diary_backup.py`, a thin shell over `garmin_backup_common`.
`diary/` is not known to `clients/`, `maps/` or the MCP server: no tool reads `diary_data/`.

---

## Data layout

```
<archive folder>/
  diary_data/
    fields.json                       the field list (master file)
    days/diary_YYYY-MM-DD.json        one file per day with content
  garmin_data/backup/diary/           the backup (diary_backup.py)
    days/YYYY-MM/diary_YYYY-MM-DD.json   open month: the newest copy of a day
    days/diary_backup_YYYY-MM.zip        completed month
    master/fields.json                   copy of the field list
    master/fields.previous.json          the copy before that one
```

Files are written as `<name>.tmp` + `os.replace` (retried for a moment when a virus scanner holds
the file). A leftover `.damaged` (numbered `.damaged2`, ...) is a file that could not be read and
was set aside before a restore.

### Fields (definition)

```json
{"name": "Blood pressure", "set": "garmin", "maps_to": "get_blood_pressure", "with_time": true,
 "values": [{"label": "systolic", "type": "number", "unit": "mmHg"},
            {"label": "diastolic", "type": "number", "unit": "mmHg"},
            {"label": "Pulse", "type": "number", "unit": "bpm"}]}
```

| Key | Meaning |
|---|---|
| `name` | display name (the only part that can change later, `rename_field`); at most 80 characters, unique without regard to case |
| `set` | `garmin` (Set 1: Garmin-compatible fields entered by hand, from `diary_catalog.CATALOG`, key `G001`...) or `user` (Set 2: free fields, key `U0001`...) |
| `maps_to` | Garmin endpoint of a Set 1 field; stored, read by nothing in v1.7.8 |
| `with_time` | `true`: any number of entries per day, each with a time `HH:MM`; `false`: exactly one entry per day, no time |
| `values` | 1 to 12 named values: `label` (at most 40 characters, unique without regard to case), `type`, `unit` (numbers only, at most 20 characters), optional `group` |

Value types: `number` (int or float, finite, not bool), `yesno` (bool), `text` (one line, at most 200
characters, no control characters). A **group** (`group` on a number value) makes several numbers
alternatives of each other (steps or distance): per entry at most one value of a group is entered;
a group has at least two members, they stand together, only numbers.

A definition never changes after the field was made (a different unit or type is a new field with a
new key). Keys are never reused; `next_id` in `fields.json` counts the user keys up.

### The field list (`fields.json`)

`{"schema_version": 1, "next_id": N, "fields": {"U0001": {definition..., "favorite": false, "archived": false}, ...}}`.
Archiving only hides a field; its key stays taken.

### A day (`days/diary_YYYY-MM-DD.json`)

```json
{"schema_version": 1, "date": "2026-11-18", "created": "2026-11-18T09:30:00",
 "note": "free text", "entries": {"U0001": [{"time": "08:00", "values": {"Anzahl": 1}}]},
 "key_snapshot": {"U0001": {definition as it was}}, "history": []}
```

`key_snapshot` keeps the definitions the day uses, so the file can be read when the field list is
gone; it only ever gains keys. `entries` holds, per field key, a list of entries (`values` carries
only the labels that were entered; empty is not 0). A day without note, entries and history does
not exist (the file is removed).

### History

A day is free to edit until the end of the calendar day of its first save (`created`). After that a
change needs the history: the whole state before the change is appended to `history`
(`{"timestamp": "YYYY-MM-DDTHH:MM:SS", "before": {"note", "entries"}}`, oldest first, only appended).
A day that has no file can be written for any date without a history.

---

## `diary/diary_catalog.py`

Data only. `CATALOG` (Set 1: G001 Blood pressure, G002 Hydration, G003 Weight; only fields whose
Garmin structure is evidenced in the repository), `TEMPLATES` (start templates for Set 2: Cycle,
Pregnancy, Calorie intake, Alcohol, Caffeine, Walk), `templates()`, `keys()`, `definition(key)`
(a copy), `names()`.

## `diary/diary_model.py`

Pure checks (no files). Every check answers with a list of error codes (empty = fine) or a bool and
never raises: `valid_date`, `valid_time`, `valid_timestamp`, `check_definition`, `check_entries`,
`check_master`, `check_day`, `check_history`, key helpers (`is_garmin_key`, `is_user_key`,
`format_user_key`, `user_key_number`), `clean_name`, `normalized_name`, `snapshot_of`,
`definition_of`, path helpers (`diary_dir`, `fields_path`, `days_dir`, `day_path`,
`date_of_day_file_name`) and the limits (`MAX_NAME_LEN`, `MAX_LABEL_LEN`, `MAX_UNIT_LEN`,
`MAX_TEXT_LEN`, `MAX_VALUES`, `MAX_NOTE_LEN`, `MAX_ENTRIES_PER_FIELD`).

## `diary/diary_reader.py`

Read only. Every read answers `(state, data)`; states: `ok`, `missing`, `damaged` (not readable or
fails its checks), `unsupported` (written by a newer version: never interpreted, never overwritten),
`invalid_date`.

| Function | Returns |
|---|---|
| `read_master(base_dir)` | `(state, master)` |
| `read_day(base_dir, date_str)` | `(state, day)` |
| `list_days(base_dir)` | sorted dates that have a day file (names only) |
| `search_notes(base_dir, query, limit=200)` | `{"ok", "hits": [{"date", "snippet"}], "searched", "unreadable", "truncated"}`; all words of the query in the note, case-insensitive, characters taken literally, newest day first; a query shorter than 2 or longer than 200 characters is refused (`reason`); notes only (not entries, not history); days that cannot be read are counted, not hidden |

## `diary/diary_writer.py`

Sole write authority over `diary_data/`. Nothing raises: every function returns
`{"status": "written" | "deleted" | "unchanged" | "rejected" | "failed", "reason": ...}`;
`rejected` = checked and refused, nothing written; `failed` = the write failed (a `.tmp` is removed,
a stored file is untouched). One lock covers every read-modify-write. The log carries the date, the
key and the kind of an error, never a note, a value or a field name.

| Function | Purpose |
|---|---|
| `create_user_field(base, name, values, with_time)` | new Set 2 field; `key` in the result; refuses an invalid definition or a taken name (also a catalogue name) |
| `activate_catalog_field(base, key)` | takes a Set 1 field into the list (once) |
| `set_flags(base, key, favorite=None, archived=None)` | favorite / archived |
| `rename_field(base, key, new_name)` | the display name, nothing else |
| `save_day(base, date, note, entries, now=None, keep_history=False)` | replaces the whole day; `deleted` when emptied and without history; `history_required` for a day first saved on an earlier day unless `keep_history=True` |
| `restore_history(base, date, index, now=None)` | puts an earlier state back (0 = oldest); the state it replaces is appended to the history |
| `recover_master(base, overwrite=False)` | rebuilds a lost field list from the key snapshots of the days (flags start false) |
| `restore_day(base, date, data)` | puts a missing or damaged day back from the bytes of a backup copy or a mirror container; a readable day or one of a newer version is never replaced; the damaged file is kept as `.damaged` |
| `restore_master(base, data)` | same for the field list; the copy must know every key the days use (`copy_behind`), and every day must be readable (`days_unreadable`): `recover_master` is the way otherwise |

## `diary/diary_backup.py`

Sole writer of `garmin_data/backup/diary/`. Thin shell over `garmin_backup_common` (not changed).
Only a file that passes its checks is copied; a copy is never deleted (a deleted day stays in the
backup). Answers `{"ok", "status", "reason"}`.

| Function | Purpose |
|---|---|
| `backup_day(base, date)` | after a save; a damaged or newer day file is not copied; a day without a file has nothing to copy |
| `backup_master(base)` | after a change of the field list; keeps the copy before as `fields.previous.json` |
| `backup_all(base)` | at the start: the field list, missing and outdated days; reports damaged days |
| `read_day_copy`, `read_master_copy(base, previous=False)` | bytes of a copy or `None` |
| `read_valid_day_copy`, `read_valid_master_copy` | only a copy that passes the checks |
| `check(base)` | read only: damaged and newer days, which are restorable, copies without a file, days not backed up or outdated |

---

## The tab (app/)

| File | Content |
|---|---|
| `panel_diary.py` | `PanelDiary` (tab "Diary", behind "MCP Server"), `DiaryCalendar` (dots on days with content, future days cannot be picked), `DiaryFieldRow` |
| `diary_entry_editor.py` | `EntryEditor` / `EntryLine`: the boxes of one field on one day (number text box with decimal comma, Yes/No, text, time, "+ Add entry", selector for a group of alternatives); `parse_number`, `clean_text` |
| `dialog_diary_field.py` | "Create field" (`DiaryFieldDialog`), `describe_failure()` |
| `dialog_diary_manage.py` | "Manage fields" (rename, archive, restore) |
| `dialog_diary_history.py` | "History" (earlier states of a day, restore one); `describe_state()`, `summarize_state()` |

What the tab does:

- The archive folder is the "Archive folder" of Settings; without it everything is disabled.
- Calendar, note ("Save", "Delete all"), favorite rows with entry boxes, dropdown "Add field" (your fields,
  start templates, Garmin fields; a Garmin field that Garmin already delivers is hidden unless the checkbox asks),
  "Create field", "Manage fields", "History (n)", "Restore from backup", search box with hit list (click jumps to the day).
- Unsaved changes are asked about on every way out: another day, another tab, closing the window
  (Save / Discard / Cancel).
- A day first saved on an earlier day: one question per day shown ("Save and keep history").
- After every save and every change of the field list a backup copy is made; the first time the tab is shown
  for an archive folder a background thread copies what is missing or outdated; a copy that could not be made
  is told in the status line.
- "Restore from backup" is enabled only for a day or a field list that cannot be read and has a valid copy.

---

## Mirror container

Section `diary` (the eighth and last; format byte stays `0x01`). `garmin_container._classify_file`
packs exactly `diary_data/fields.json` and `diary_data/days/diary_YYYY-MM-DD.json`.

`garmin_import_mirror` imports it with the rule "nothing readable is ever replaced": a day that is missing
or damaged here is restored when its field keys fit the field list here (same definition, the name may
differ; with no list here the one of the container is the reference); a day that does not fit is a
conflict (counted, not imported, not an error); the field list is restored only when there is none or it is
damaged; days first, then the list. Result keys (only when the container has a diary): `diary_days_copied`,
`diary_days_skipped`, `diary_conflicts`, `diary_master` (`restored` / `kept` / `refused:<reason>`); dry run:
`diary_to_copy`. Two archives that made fields on their own cannot be merged.

---

## Privacy

Nothing of the diary reaches a log line, the MCP server or a cloud model. `diary_data/`, its backup and the
mirror container section hold health data (cycle, pregnancy, medication, notes): the container is encrypted
with the user's password. Deleting a day does not delete its backup copy and does not remove it from an
earlier mirror.
