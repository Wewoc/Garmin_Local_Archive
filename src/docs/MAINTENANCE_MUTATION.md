# Garmin Local Archive — Mutation Testing Guide

How the tests are checked for blind spots, which rounds have been run, and the list of
mutants that are known to be equivalent (changes the tests cannot and need not notice).
For the test suite itself see `MAINTENANCE_GLOBAL.md`.

> A mutation test changes one spot in the code (for example `<` to `<=`) and runs the
> tests. If a test fails, the change was **caught**. If every test still passes, the
> mutant **survived**: either the tests miss a behaviour, or the change is harmless
> (an **equivalent** mutant). The repository is never touched; all runs work on a copy.

---

## Tools

Both tools live outside the repository (maintainer tooling, not shipped).

| Tool | Use |
|---|---|
| `run_mutation.py` (Cosmic Ray 8.7.0) | Systematic run over one module at a time against its own test file (stage 1), then every survivor against all other test files (stage 2). `--lines` limits a run to given source lines (one module), `--resume` continues an interrupted run. New modules need an entry in its `TEST_FOR` table, otherwise they are skipped silently. |
| Hand-picked mutant lists (`mutate_vX.py`) | One list per build step: a fresh copy of `src/`, one exact-text replacement per mutant, the suite named for it must go red. Used for rules that a generic operator does not reach (limits, order of checks, the choice of a source). |

Both start from a fresh copy of `src/`; a run on the working tree is never done.

## How a round runs

1. Fix the scope: new modules completely, changed modules on the changed lines only
   (`git diff` against the last measured state gives the line ranges).
2. Stage 1 per module, then stage 2 for the survivors.
3. Judge every survivor: add a test (a regression check that fails on the mutant), or
   record it below as equivalent with the reason. Survivors that only touch log text or
   formatting are judged like any other; the tool's "format/log" label is only a guess.
4. Re-run the mutants of the new tests (`MUT_ONLY` for hand lists, `--lines` for Cosmic Ray).
5. Only tests and this file change in a mutation round, never the behaviour. A behaviour
   problem found on the way goes to the ROADMAP as a finding.

## Writing tests that a mutant cannot pass by chance

Every one of these cost a surviving mutant at least once:

- Choose data so that the mutated and the original code give **different** results: a
  boundary test needs a value exactly on the boundary; a counter test needs a counter
  that is not already at its limit; a type test needs a value of the wrong type.
- A check that only runs on days which already hold the target value cannot catch `<=`
  instead of `<`.
- A test that checks log lines has to lift the suite's global `logging.disable` itself
  and restore it afterwards.
- No test with a fixed date that becomes "today" tomorrow.
- Count the anchor hits per mutant (exactly one); a mutant whose anchor does not hit is
  not a mutant.
- A test run is red only through its exit code or a failing check with a number above 0
  before "failed" — the word "failed" alone also appears in "0 failed".

## Rounds

| Round | Method | Scope | Result |
|---|---|---|---|
| v1.7.4.0.3 / v1.7.4.0.4 | Cosmic Ray, stage 1 + 2 (2026-10-05) | `src/garmin/` as of v1.7.4 (27 modules) | Gaps closed in v1.7.4.0.3; behaviour findings fixed in v1.7.4.0.4. Survivors that were not individually judged stay in the run's `survivors.json` and are **not** listed as equivalent here. |
| v1.7.6.9 | hand list | device repair | 56 mutants |
| v1.7.6.10 | hand list | race-prediction repair, normalizer | 56 mutants, all caught |
| v1.7.6.11 | hand list against the property tests | bulk writer, normalizer, rules, prediction plan, backup, FIT reader, export scanner | 74 mutants, 73 caught, 1 equivalent (not named in the notes) |
| v1.7.6.11.1 | hand list | import path check and robustness | 33 mutants, 31 caught, 2 equivalent (EQ-12, EQ-13) |
| v1.7.6.11.2 | hand list | prediction catch-up and its wiring | 67 mutants, 66 caught, 1 equivalent (EQ-14) |
| v1.7.6.12 | Cosmic Ray, stage 1 + 2 (2026-11-09) | all modules built in v1.7.6.x; changed lines of the core modules and of the mirror import | 9905 mutants in stage 1, 8343 caught; every survivor judged, 434 new checks, the rest equivalent (EQ-16 to EQ-46), see below |

### v1.7.6.12

Scope: the modules built during v1.7.6.x in full; `garmin_import_mirror` and the core modules they touched (`garmin_collector`, `garmin_writer`, `garmin_normalizer`,
`garmin_import`, `garmin_api`, `quality/*`) on the changed lines only. `garmin_extended_anaysis.py` is left out on purpose (easter egg, no tests).

Stage 1 (every mutant against the tests of its own module), 32 modules:

| Group | Modules | Mutants | Caught | Survived |
|---|---|---:|---:|---:|
| Bulk store, backups, repairs, migration | `garmin_backup_bulk`, `garmin_backup_common`, `garmin_bulk_export_scanner`, `garmin_bulk_fit_reader`, `garmin_bulk_import`, `garmin_bulk_json_import`, `garmin_bulk_normalizer`, `garmin_bulk_rebuild`, `garmin_bulk_writer`, `garmin_catchup_predictions`, `garmin_migration_snapshot`, `garmin_repair_devices`, `garmin_repair_predictions`, `garmin_repair_resting_hr`, `garmin_track_migration` | 6539 | 5491 | 1041 |
| Backup, container, silo, import | `garmin_backup`, `garmin_backup_source`, `garmin_container`, `garmin_mirror`, `garmin_import`, `garmin_silo_check`, `garmin_silo_repair` | 1978 | 1833 | 143 |
| Mirror import (changed lines) | `garmin_import_mirror` | 333 | 284 | 49 |
| Core modules (changed lines) | `garmin_collector`, `garmin_normalizer`, `garmin_writer`, `quality/_maint`, `garmin_api`, `garmin_config`, `garmin_source_writer`, `quality/_io`, `quality/_assess` | 1055 | 735 | 320 |
| **Total** | 32 modules | **9905** | **8343** | **1553** |

The difference between the mutants and caught plus survived (9 in all) are mutants that could not be run (incompetent: the changed code did not compile or the test run did not start).
The caught share of the first stage depends on how much a module does with text (progress and result lines, stop reasons) and with boundaries; the numbers say where to look, not how good a module is.
Every survivor was run against all other suites (stage 2; `garmin_normalizer` could not be cross-checked because its baseline was red in stage 2 and was judged in full) and then judged one by one. After the new tests,
the changed lines were run again, repeatedly, until only the equivalent changes of the list below were left. 434 new checks in 26 existing test files (sections "mutation round v1.7.6.12"); no new test file;
no production code changed.

What the round found in the tests (none of it in the code): progress and result lines with numbers that equalled their input by chance (ten folders: `10 * done // 10 == done`); a stop reason compared with `>=`;
a `break` that no test told from a `continue`; a ZIP entry identical to a file outside the ZIP; limits of counters and sizes without a value exactly on the boundary; negative milliseconds, path parts and `..`;
the device and field marks of the quality log; comparisons of values that come from the environment at run time; a boundary of seconds tested only with `:00`; a cleanup that an earlier test had already made invisible.
One finding concerns the code, not the tests (F-29, register `AUDIT_FINDINGS_v1_7_6.md`, not fixed): the date check `_valid_date` exists in nine near-identical copies and on Python 3.11 and later passes the ISO week form
(`2025-W35-3`) in seven of them.

Not tested: the mutants that only an input the program never produces can tell apart (EQ-20); the first-stage survivors of `garmin_import_mirror` outside the changed lines.

## Equivalent mutants

An entry is only made when a protocol names it. Where an older protocol only says "one
equivalent" without naming it, the entry says so; the reason is then not recorded and
must not be assumed.

| ID | Version | Module | Mutation | Why it is equivalent |
|---|---|---|---|---|
| EQ-01 | v1.7.6.1 | `garmin_bulk_writer.py` | `new >= old` | Not recorded in the protocol (named as equivalent). |
| EQ-02 | v1.7.6.1 | `garmin_writer.py` | the date check in `rebuild_summary` | Changes nothing in the result; stays as a clear error message. |
| EQ-03 | v1.7.6.1 | `garmin_import.py` | default value of a function that is never called without a value | The default is never used. |
| EQ-04 | v1.7.6.1 | collector / quality block | one mutant, not named | Not recorded in the protocol. |
| EQ-05 | v1.7.6.1 | bulk import / bulk normalizer | one mutant, not named | Not recorded in the protocol. |
| EQ-06 | v1.7.6.1 | `garmin_bulk_normalizer.py` (`plan_days`) | `isinstance` check replaced by `if window:` | `plan_days` discards non-dicts itself. |
| EQ-07 | v1.7.6.1 | `maps/garmin_health_map.py` (bulk daily values) | `isinstance(section_data, dict)` | `_get_nested` already handles it. |
| EQ-08 | v1.7.6.2 | `garmin_backup_bulk.py` | "every folder counts as a prefix" (B3) | The name check (file name starts with the folder name) makes the folder-name check redundant. |
| EQ-09 | v1.7.6.3 | `garmin_writer.py` (`_fill_fields`, fill step of the migration) | empty API section `{}` filled field by field instead of as a whole (M7) | `_fill_fields({}, x)` gives the same result as `merge_field`. |
| EQ-10 | v1.7.6.3 | migration | source not copied before `normalize` (R19) | `normalize(api)` passes the dict through unchanged and the copy is not used afterwards; the copy stays as protection. |
| EQ-11 | v1.7.6.4 | `app/dialog_docs.py` (outside `src/garmin`) | `.lower()` removed from the URL scheme (M11) | `QUrl` normalizes the scheme to lower case when parsing (checked). |
| EQ-12 | v1.7.6.11.1 | `garmin_import.py` (call of `_total_sleep`) | `_total_sleep(sleep)` instead of `_total_sleep(secs)` | The helper skips non-numbers itself; same result. |
| EQ-13 | v1.7.6.11.1 | import (path check) | `.strip(" ")` instead of `.rstrip(" ")` in the name | A space before `NUL` is also rejected (fail closed); names with spaces at the edge are deliberately left to the system. |
| EQ-14 | v1.7.6.11.2 | `quality/_maint.py` (`record_field_given_up`) | `limit < 1` instead of `limit < 0` | No counter is negative; both reject the same limits. Since v1.7.6.12 a test pins the difference with a hand-made negative counter, so the mutant is caught there. |
| EQ-15 | v1.7.6.11 | rules / bulk / backup (one mutant, not named) | not named | Proven equivalent at the time; the protocol does not name it. |
| EQ-16 | v1.7.6.12 | `garmin_backup_bulk.py` (`_write_prefix_zip`) | `added == 0` → `added <= 0` | `added` counts files and is never negative. |
| EQ-17 | v1.7.6.12 | `garmin_backup_bulk.py` (`backup_originals`, progress) | `10 * done // total > last_step` → `!=` / `is not` | `done` only grows, so the step never falls below `last_step`: `!=` and `>` answer alike in every call. |
| EQ-18 | v1.7.6.12 | `garmin_backup_bulk.py` (`backup_originals`, progress) | `last_step = 10 * done // total` → `/` | A float `last_step` is not below the integer step and below the integer step plus one, so `step > last_step` is decided the same way. |
| EQ-19 | v1.7.6.12 | `garmin_backup_common.py` (`consolidate_months`) | `continue` → `break` at a month that is not complete | The month folders are visited in sorted order: every folder after the first current-or-later one is current or later too. |
| EQ-20 | v1.7.6.12 | `garmin_backup_common.py` (`_scan`) | `crc32(data) & 0xFFFFFFFF` → `% 0xFFFFFFFF` | Differs only for a CRC32 of exactly `0xFFFFFFFF` (one file in 4.3 billion). Not forced by a test: a file with that CRC would have to be crafted. Accepted. |
| EQ-21 | v1.7.6.12 | `garmin_backup_common.py` (`refresh`) | `mkdir(parents=True)` → `parents=False` | The parent of a month folder is `backup_dir`; it exists whenever a backup copy exists, and a copy is why the file is refreshed. |
| EQ-22 | v1.7.6.12 | `_valid_date` of the repair, catch-up and migration modules (devices, resting HR, predictions, catch-up, track migration) | `len(value) != 10` → `len(value) < 10` | `date.fromisoformat` rejects every string longer than ten characters itself. (`> 10` is not equivalent: the 8-character form `20220304` is valid for it; a test pins that.) |
| EQ-23 | v1.7.6.12 | `garmin_repair_devices.py` (`_serial_of`) | `serial <= 0` → `< 0` / `== 0` / `<= -1` | The FIT reader returns no value for a serial of 0 (invalid `uint32z`) and cannot return a negative one. |
| EQ-24 | v1.7.6.12 | `garmin_repair_devices.py` (`find_candidates`) | `len(serials) == 1` → `<= 1` / `>= 1` | The branch before it takes `> 1`; with `complete` true there is at least one serial. |
| EQ-25 | v1.7.6.12 | `garmin_repair_devices.py` (`days_per_device`) | `-kv[1]` → `~kv[1]` | `~x` is `-x - 1`, which orders like `-x`. |
| EQ-26 | v1.7.6.12 | `garmin_repair_resting_hr.py` | `total == 0` → `total <= 0` | A length is never negative. |
| EQ-27 | v1.7.6.12 | `garmin_catchup_predictions.py` (`_ranges`) | `MAX_RANGE_DAYS - 1` → `MAX_RANGE_DAYS ^ 1` | 365 is odd, so `365 ^ 1` is 364; the constant is pinned by a test (C0). |
| EQ-28 | v1.7.6.12 | `garmin_repair_predictions.py` | `len({...}) > 1` → `!= 1`; `set(plan_set) \| set(plan_remove)` → `^` | The set is never empty; `plan_set` and `plan_remove` are disjoint by construction (`remove - set(out["set"])`). |
| EQ-29 | v1.7.6.12 | `garmin_repair_predictions.py` (`repair_predictions`) | `label == 'medium'` → `>=` / `is` | The labels are `medium` and `failed`; `failed` sorts before `medium`. `is` compares the module's own literals. |
| EQ-30 | v1.7.6.12 | `garmin_bulk_import.py`, `garmin_bulk_json_import.py`, `garmin_bulk_rebuild.py` (`run_*`: `ok`) | `failed == 0` → `<= 0` (originals, days; `read % PROGRESS_EVERY == 0` too) | Counts and remainders are never negative. |
| EQ-31 | v1.7.6.12 | `garmin_bulk_import.py` (`_work`), `garmin_bulk_json_import.py` (`store_day`) | `result == bw.WRITTEN` → `>=` / `is`; `status == "new"` → `<=` / `is`; `validator status == "critical"` → `<=` / `is`; `assess_quality(...) == "failed"` → `<=` / `is` | Each is a string of the program's own set of answers and sorts first or last in it (`written` after `present`, `kept`, `failed`, `unchanged`; `new` before `unchanged`, `unreadable`, `update`; `critical` before `ok`, `warning`; `failed` before `high`, `standard`). `is` compares the same literals. |
| EQ-32 | v1.7.6.12 | `garmin_bulk_json_import.py` (`comparison_lines`, `_compare_into`) | `field[DIFFER] > len(differ_days)` → `!=` / `is not`; `state == DIFFER` → `is` | The count is never below the number of listed days; the small numbers are the same objects; the state strings are the module's literals. |
| EQ-33 | v1.7.6.12 | `garmin_bulk_json_import.py` (`inventory_lines`) | the MB figure of the 64 MB limit with `1024 * 1023` | 64 MB // (1023 KiB) is 64 as well. |
| EQ-34 | v1.7.6.12 | `garmin_bulk_export_scanner.py` (`_walk_nested`) | the buffer size of `copyfileobj` (`1024 * 1024` with another operator or ±1; 0 and negative values mean "default") and `tmp.seek(0)` → `seek(1)` | The buffer size changes the speed only; `ZipFile` seeks by itself. |
| EQ-35 | v1.7.6.12 | `garmin_bulk_fit_reader.py` | the small mode numbers compared with `is` / `<=` (`mode == _MODE_SCALAR`, `kind == _STRING`, `count == 1`, `size == 0`, `gmn == 0`), `[0]` → `[-1]` of a one-element tuple, `split(b"\x00", 2)[0]`, `not isinstance(data, bytes)`, `n < 12` → `n < 11`, `needed < n` → `!=`, `header_size == 14` → `>= 14`, `stored_header_crc != 0` → `> 0`, `h & 0x40` / `h & 0x80` → `//`, `bool(h & 0x80)` → `//`, `pos < end` → `!=`, `253 in rec` → 254 / 252, `v != 0xFFFFFFFF` → `<`, `compressed and ts is not None` → `or` | Small integers are the same objects; the modes are 0..3 in order; the second element of a one-value `unpack_from` is the first; the first element of `split` ends at the first zero either way; `bytearray` and `memoryview` behave like `bytes` downstream; an 11-byte file has no signature at 8..12 either; `needed > n` is refused before; only header sizes 12 and 14 reach the comparison; the CRC is unsigned; the truth value of an 8-bit flag is the same with `//`; `pos` never exceeds `end`; field 253 read from the record or from its bytes gives the same number; `0xFFFFFFFF` is the largest value; a compressed record of a wanted message without a reference is refused before, of any other message its record is not returned. |
| EQ-36 | v1.7.6.12 | `garmin_migration_snapshot.py` | `_valid_date`: `len == 10` → `>= 10`; `_cleanup`: `missing_ok=False`; `create_snapshot`: `wanted == {"quality_log"}` → `<=` and the MB figure `// 1048577` / `// 1048575`; `_check_zip`: `set(expected) \| {MANIFEST}` → `^`, kind `== "raw"` / `"summary"` → `is` / `>=`; `restore_snapshot`: `res["log_saved"] is False` → `==` / `<` / `<=` | `fromisoformat` rejects strings above ten characters; an OS error of the missing file is caught either way; `wanted` is never empty there; the size of a ZIP cannot be set to a value that tells a divisor of 1048575 or 1048577 from 1048576; `MANIFEST` is never in `expected`; `summary` is the largest kind; `log_saved` is True, False or None (None == False is False). |
| EQ-37 | v1.7.6.12 | `garmin_track_migration.py` | string comparisons against the module's own kinds, statuses, states and reasons (`kind == KIND_MIGRATE` → `>=` / `<=` / `is`, `prev["state"] == "unreadable"` → `>=` / `is`, `prev["state"] != "ok"` → `<` / `is not`, `status == "ready"` → `>=` / `is`, `status == "blocked"` → `<=` / `is`, `kind == KIND_CONVERT` / `KIND_REFRESH` in the counts → `>=` / `<=` / `is`, `copy_made["reason"] == "stopped"` → `is`, `reason == "snapshot_failed"` / `"preview_stopped"` → `is`, `_is_empty`: `value == ""` → `is`); `handled` set union → `^` / `-`; `_valid_date` `!= 10` → `< 10` (EQ-22); `_entries` / `_migrate_day`: `ensure_ascii` flag; `format_plan`: `len(group) > max_dates` → `is not`; `_plan_import_day`: `kind != KIND_MIGRATE or new_api.get(key) != value` → `>` / `<` / `is not` | Kinds are migrate, convert, refresh, unresolved, api; states ok, none, unreadable; statuses ready, blocked, left. In the places where the mutant selects more than the original, the extra members carry another status ("left") or cannot reach the line (for `_plan_import_day` only migrate and convert days do; a convert day has `new_api == {}`, so `new_api.get(key) != value` is true for every non-empty value either way). The disjoint kinds of one day make union and symmetric difference equal. `ensure_ascii` is applied on both sides of a comparison or to a text that is read back. Small numbers are the same objects. |
| EQ-38 | v1.7.6.12 | `garmin_silo_repair.py` (`repair_silos`), `garmin_silo_check.py` | results of the bulk writer compared with `is` (`UNCHANGED`, `KEPT`, `PRESENT`, `!= WRITTEN` → `is not`), `kind == "aggregates"` → `is` / `<=`, `load_aggregates(...)[0] == "missing"` → `is`; `_collect_backup_original_hashes`: `not z.is_file() or not regex` → `and`, `m.group(2) == ".fit"` → `<=` | The writer's answers and the kinds are the module's literals; `intraday` sorts after `aggregates`; a ZIP whose name is not two hex characters can never equal the first two characters of an entry name that matches the hash pattern; `.fit` sorts before `.json`. |
| EQ-39 | v1.7.6.12 | `garmin_backup.py` (`backup_quality_log`) | `old_days > 0` → `>= 0` / `!= 0` / `> -1` | With no day in the old snapshot, `new_days < 0` cannot hold. |
| EQ-40 | v1.7.6.12 | `garmin_bulk_writer.py` | `_cleanup`: `missing_ok=False`; `_replace`: `attempt == REPLACE_ATTEMPTS - 1` → `^ 1` / `>=` / `is`; `_compare`: `stored_version == current_version` → `>=` / `is`, `new > old` → `>=`; the stored-state, status and kind comparisons with `"unreadable"`, `"unchanged"`, `"ok"`, `"intraday"`, `"aggregates"`, `"raw"` → `is` / `>=` / `<=`; `write_day`: `ensure_ascii` flag (the day file holds ASCII only); `describe_container_path`: `len(parts) < 4` → `< 3`, `len(parts) == 4` → `<= 4`, `len(parts) == 5` → `<= 5`, `m.group(1)[:2]` → `m.group(0)[:2]` | An OS error of a missing file is caught either way; `5 ^ 1` is 4 and `attempt` never exceeds 4; the larger-version case is handled before; `new == old` before; the strings are the module's literals and sort first or last in their sets (states missing, damaged, ok, unreadable; statuses new, unchanged, update, smaller, newer, unreadable; kinds intraday, aggregates; areas raw, aggregates, source); the day file has no non-ASCII text; a path with three parts has no area and name; four-part and five-part paths are tested for their exact shape; the first two characters of the whole match are those of the hash. |
| EQ-41 | v1.7.6.12 | `garmin_bulk_normalizer.py` | `plan_days`: `boundary = [None] * (n + 1)` → `n + 2` / `<<`; `i = 0` → `1` / `-1`; `i = j + 1` → `j + 2`; `left = boundary[i - 1][0] if i > 0` → `i != 0`; `a[1] == "prev_day_end"` → `>=` / `is`; `file_samples`: `bpm == 0` → `<= 0`; `_ranks`: `rank = [0] * len(files)` → `[1]` / `[-1]`, `files[i][0] is not None` → `files[i][1]` / `[-1]`, `else 0` → `else 1` / `-1`; `_resolve`: `bpms[k] == values[-1][1]` → `>=` / `is` | A longer list is never indexed beyond `n`; the first boundary has no left neighbour whatever the start; the element at `j + 1` is filled, so skipping it changes nothing; `i` is never negative; `neighbours` sorts before `prev_day_end`; a heart rate is never below 0; every entry of `rank` is overwritten; the hash of a file is never None; the constant in the key of files without a creation time is the same for all of them; small numbers are the same objects. |
| EQ-42 | v1.7.6.12 | `garmin_writer.py` (`_usable_aggregates`, `_is_empty`, `write_day`, `write_summary_only`, `rebuild_summary`, `resolve_preview`) | the state strings compared with `is` / `>=` / `<` (`state == "unreadable"` → `>=` / `is`, `state != "ok"` → `<` / `is not`, `agg_state == "ok"` → `>=` / `is`), `value == ""` → `is ""` | The states come from the module's own literals (`missing`, `damaged`, `ok`, `unreadable`; after `_usable_aggregates` only `none`, `ok`, `unreadable`); `unreadable` sorts last, and `none`, `damaged` and `missing` sort before `ok`. The empty string is one object in CPython. (`agg_state <= "ok"` in `rebuild_summary` is **not** equivalent: it sends a day without aggregates through the export merge and puts `"unknown"` into `date`; a test pins that.) |
| EQ-43 | v1.7.6.12 | `quality/_maint.py` (`record_field_given_up`) | `attempts.get(field, 0)` → `attempts.get(field, -1)` | The limit is at least 1 there (smaller limits are refused first), so a missing counter (0 or -1) is below it either way. |
| EQ-44 | v1.7.6.12 | `garmin_normalizer.py` (`_is_iso_date`, `own_day_prediction`, `_latest_entry`) | `len(text) != 10` → `< 10` (EQ-22); `k != "race_predictions"` → `is not`; `t > best_t` → `>=` | The first is the `fromisoformat` case of EQ-22; the key is the module's own literal; inside the `t != best_t` branch equal times are already left out. |
| EQ-45 | v1.7.6.12 | `garmin_container.py` (`list_files`, `is_container`, `_open_and_verify`, `_collect_sections`, `_classify_file`) | `unpack(">I", ...)[0]` / `f.read(1)[0]` → `[-1]`; `fmt_ver != _FORMAT_VER` → `is not`; `not p.exists() or not p.is_file()` → `and`; the progress step (`10 * i // total > last_step` → `!=` / `is not`, `last_step = 10 * i // total` → `/`); `len(parts) > 1` → `!= 1` | The first element and the last element of a one-value tuple or one byte are the same; the format number is a small int (the same object); for a folder instead of a file `open()` raises an error that is caught and answers `False` too; the progress step only grows (EQ-17, EQ-18); `parts` has at least one element there. |
| EQ-46 | v1.7.6.12 | `garmin_collector.py` (`_mark_bulk_days`, `main`) | `len(days) > marked` → `!=` (`is not` is caught with 300 days: equal numbers above 256 are not one object); `_track_mode == "preview"` / `_rebuild_mode == "preview"` → `>=` | `marked` never exceeds the number of days; only `"1"` and `"preview"` reach the comparison, and `"1"` sorts before `"preview"`. (`is` is **not** equivalent: the value comes from the environment at run time, a string made then, not the program's literal; a test uses `b"preview".decode()`.) |
| EQ-47 | v1.7.6.12 | `garmin_import_mirror.py` (`_run_import_container`, `_RESERVED_DEVICE_NAMES`, `_is_reserved_name`, `_analyse_bulk_delta`, `_report_tenth`, `_import_bulk_from_bytes`) | `errors == 0` → `<= 0`; `\| {COM…}` and `\| {LPT…}` → `^` (`-` on the LPT set is caught); `split(".", 1)[0]` → `split(".", 2)[0]`; `info[0] == "original"` → `>=` / `is`; `result == "written"` → `>=` / `is`; `result != "present"` → `is not`; `kind == "aggregates"` → `<=` / `is`; `_report_tenth`: `total <= 0` → `== 0` / `< 0` / `<= 1` / `<= -1`, `progress is None or …` → `and`, and the tenth test written with `/` for one `//` or with `!=` / `is not` instead of `<` | A count is never negative; the COM and LPT names are not in the first set, so `^` joins like `\|`; the first piece of `split` ends at the first dot either way; the kinds and answers are the literals of the bulk writer and sort as in EQ-31 (`original` after `aggregates` and `intraday`, `written` last); for `done >= total` the function returns before, so `total <= 1`, `<= -1`, `== 0`, `< 0` change nothing (`total` is the length of a list that is walked from 1); `report_progress` does nothing without a callback, so `and` changes nothing; `x // 10 < y // 10` with `x <= y` decides like `x / 10 < y // 10`, like `x // 10 < y / 10` and like `!=`. (`101` in place of `100` and a loop that starts at 2 are **not** equivalent: a test with 29 items, which do not divide 100, and a marker per item catches them.) |

Equivalent mutants found in v1.7.6.12 are added below, with the run and the module.

## Known findings that stay as they are

Property tests (v1.7.6.11) and this round found behaviours that look wrong at first sight. The maintainer decided on 2026-11-09 to **pin them and leave them as they are**: F-21, F-22, F-25, F-27 and F-28 are kept by a test that
states today's behaviour (so they are not lost, and a change shows up as a red test), F-29 only by this list and the register; each was judged as not reaching operation. If a later round, a property test or a review meets one of them again,
it is **not a new finding**: do not open it a second time; check it against this list and change it only after a new decision. The register with the full text is `AUDIT_FINDINGS_v1_7_6.md` (maintainer's folder, not in the repository).

| ID | Where | Behaviour | Kept by | Why it stays |
|---|---|---|---|---|
| F-21 | `garmin_bulk_normalizer.plan_days` | An empty string as a day with no window raises `ValueError`. | `test_prop_bulk_normalizer.py` | The only caller passes no days. If the function is ever called with days, widen the pre-check to `not first_date`. |
| F-22 | `garmin_bulk_normalizer.plan_days` (rule 2) | A gap without proof takes the offset both sides agree on, even if it differed in between (a one-day trip, daylight saving over a gap of months). | `test_prop_bulk_normalizer.py` | Decision E6 (any number of missing days); the days carry `offset_source = "neighbours"`. A day with proof on both boundaries stays exact. |
| F-25 | `garmin_normalizer._normalize_import` | `normalize(raw, source="bulk")` adds `heart_rates` to the dict it was given. | `test_prop_rules.py` | The only caller (`garmin_writer._resolve`) passes a copy. A new caller that hands over a stored dict must copy first. |
| F-27 | `garmin_backup_common.consolidate_months` | The whole month folder is removed after zipping the files of the pattern; a foreign file in it is gone without a log line. | `test_prop_backup.py` | The folder belongs to the program (leftovers such as `*.tmp` are meant to go). |
| F-28 | `garmin_bulk_export_scanner._walk_nested` | An inner ZIP of the export is copied to a temporary file without a size limit. | `test_fuzz_parsers.py` | The export is the user's own download. A limit is set only after the real sizes of inner ZIPs are measured (read only). |
| F-29 | `_valid_date` in nine near-identical copies | On Python 3.11 and later seven copies accept the ISO week form (`2025-W35-3`), two refuse it. | none (found by this round) | Day keys are made by the program. If it is ever touched: one shared strict helper, not nine single changes. |

## Using the list

When a run reports a survivor, look here first by module and mutation. A survivor that is
not listed is either a new gap (add a test) or a new equivalent (add it here with the
reason). Line numbers change with the code, so entries are matched by module, function and
mutation text, not by line.
