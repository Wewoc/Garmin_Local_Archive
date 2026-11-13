# Export Scan — Guide

The Export Scan looks into **your own Garmin account export** (the ZIP file you get from Garmin, or the folder it is
unpacked in) and shows which data it holds and how complete that data is. It is a check for you, not a part of the
import: nothing is written to your archive, nothing is stored between runs, and the export itself is only read.

Open it in the **Settings** tab, section **Data Collection**, with **📂 Export Scan** (next to **🔍 API Scan**: the API Scan asks what your account
can deliver, the Export Scan shows what your export holds). The window stays open while you work in the app.

## Start

1. Click **ZIP file ...** (the export as Garmin sent it) or **Folder ...** (the export unpacked).
2. The JSON files are read first (seconds). Then the FIT files are counted by type and year; this takes longer on a
   large export (about 30 seconds for 35,000 files on the author's export) and shows its progress at the top.
3. **Stop** ends a running scan; what was counted so far stays visible and is marked as incomplete.

## The window

- **Right: the tree.** The export grouped by topic: *Daily values*, *Sleep & body*, *Training & metrics*,
  *Activities*, *Account data*, then *FIT files*, *Not recognised* and *Folders*. The dot in front of a family tells what
  GLA does with it: **green** — GLA reads it in the import, **yellow** — GLA keeps the file but does not read it,
  **grey** — known from the export reference, not read by GLA.
- **Left: a table or a graph** of the chosen item (switch **Table** / **Graph**).
  - *Overview*: how many files of which kind.
  - A group: rows per year and family.
  - A family: every **field** by year. A cell shows the share of rows that have a value (filled, or a 0 — a 0 is a
    value). Hover a cell for the four states: **filled**, **zero**, **empty** (null, `""`, `[]`, `{}`) and **absent**
    (the key is not in the row). The graph is a heat map of the same shares.
  - *FIT files*: type by year (the graph shows stacked bars). Type names are working names, not Garmin terms.
  - *Not recognised* and *Folders*: only folder names and counts, never a file name.
- The colours are those of the active theme of the app.

## One field in detail

Double-click a cell in the table of a family. The detail of that field opens; **← Back** (or another item of the tree)
leaves it. Only the table is clickable, the graph is not.

- **Counts** — the four states of the field by **Month** or by **Year**, with the first and the last month that has a
  value.
- **Values** — the numbers of that field, read from the export on request: a table (date and value), the statistics
  (count, minimum, maximum, mean, median, number of zeros) and two graphs, **Over time** and **Distribution**.
  Only numbers are shown; a field inside a list (a path with `[]`) cannot be shown as values. More than 20,000 points
  are thinned for the view; the statistics always use all values.
- **Units.** A unit is named only where there is evidence, and it always says where it comes from: *name* (the last word
  of the field name says it, for example `...Seconds`, `...Meters`, `...Percent`) or *GLA code* (a module of GLA treats
  the field as that unit, for example the resting heart rate as bpm). Everything else says *unit not documented*.
  Nothing is converted: the values are shown as the export holds them, which can differ from the archive (the archive
  keeps distances in km, the export has metres).

## The heart rate of one day

When the FIT files are counted, the **FIT files** item shows a date field with **◀** and **▶** and the button
**Heart rate of the day**. It reads the heart rate of that day from the FIT monitoring files of the export and shows it
like the values of a field (table, **Over time**, **Distribution**).

- **◀** and **▶** jump to the previous or next day that has files and read it at once. The date field takes any day
  between the first and the last day that has files; a day without files says so.
- The times are **local time**: the offset at the start of the day is added to the UTC time of the samples. A day with
  a clock change says so in the note.
- A day whose boundaries cannot be determined from the daily files of the export is not read (*nothing is guessed*).
  This needs the daily files (`UDSFile`) of the export.
- Where two files hold the same second, the file created first wins, as in the import.
- Reading a day takes a few seconds, because the export has to be walked again; only the heart rate is read.

## The report

**Save report** writes a text file and a JSON file (`export_scan_report.txt`, `export_scan_report.json`) into the `log`
folder of your data folder (`garmin_data/log`) and replaces the ones of the last run. The report holds names and numbers
only: family and field names, folder names, counts. It is meant for a bug report or for comparing two exports.

## Privacy

- The files of a real export are named after the e-mail address of the account. **No file name** is shown, saved or
  logged; a folder name that contains an `@` is shown as `<hidden>`.
- **Values** appear only in the values views (a field, or the heart rate of a day). They are kept in memory only and are
  forgotten when you go back, choose another item, start a new scan or close the window. They are never written to the
  report, the log, the status line or any file.
- **A screenshot of a values view contains the values.** The window says so above the values.
- The graphs run without a network connection. The page of a graph is a temporary file that holds no values; the
  temporary folder is removed when the window closes.
- An error shows a fixed sentence, never the text of the error (it could contain a path).

## Limits

- Only the JSON and FIT files are read; other files are counted. A JSON file over 64 MB is not read, and at most 500
  field paths are kept per family (the table says when the list was cut).
- The status of a family (green, yellow, grey) is what GLA does **today**; a grey family can still be worth a look.
- The scan shows what the export holds, not whether the values are right.
- Values are numbers only; names, ids and other text fields are not shown.

See also: `REFERENCE_GARMIN_EXPORT.md` (how the export is built), `README_APP.md` and `USER_GUIDE.txt`.
