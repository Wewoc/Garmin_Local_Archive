# v1.7.2.2 — Baustein 7: build_manifest.py Stale-Path-Fix (export/ → support-tools/archive-maintenance/)

**Kurztitel:** build-manifest-export-move-fix

## Kontext

Timo hat Schritt 9 (Testsuite) selbst laufen lassen. Alle 13 Kern-Suiten
grün (2.376 Checks, 0 failed), aber `test_static.py` brach ab und riss
`generate_metrics.py`/Schritt 9b mit ("Abbruch — METRICS.md bleibt
unverändert. Grund: Unerkanntes Testergebnis"). Kein Fund aus dieser
Session — Timo bestätigte: die Verschiebung der vier Dateien
(`export/*.py` → `support-tools/archive-maintenance/*.py`) war eine
bewusste, separate Aktion seinerseits.

## Fund

`export/` existiert nicht mehr — auf `support-tools/archive-maintenance/`
verschoben (deckt sich mit dem vorab mitgeschickten `dep_map_delta.md`).
Zeitstempel-Check (`stat` auf `regenerate_raw.py`): Change-Zeit
2026-09-19 13:24 — die Verschiebung geschah vor bzw. zu Beginn dieser
Session, nicht durch einen Edit in diesem Gespräch.

`compiler/build_manifest.py:93` listete in `SHARED_SCRIPTS` weiterhin den
alten Pfad `"export/regenerate_raw.py"`. Die drei anderen verschobenen
Dateien (`backfill_source_backup.py`, `backfill_source_intraday.py`,
`regenerate_summaries.py`) standen nie in `build_manifest.py` — nur
`regenerate_raw.py` war dort als "standalone CLI tool" gelistet.

Zwei Symptome derselben Ursache:
1. `test_static.py` Abschnitt 3 ("build_manifest — SHARED_SCRIPTS
   Vollständigkeit"): meldete die fehlende Datei.
2. `test_static.py` Abschnitt 6 ("Regression-Wächter —
   spec_from_file_location") crashte hart mit `FileNotFoundError` beim
   Versuch, die Datei für die AST-Analyse zu lesen — dieser Crash ließ
   `run_metrics.bat`s Log-Parser das Testergebnis nicht mehr erkennen,
   daher der Komplett-Abbruch von Schritt 9b.

`garmin_backup_source.py`s Erwähnung von `regenerate_raw.py` (Zeile 16)
ist nur ein Doku-Kommentar, kein Laufzeit-Import/Aufruf — kein
funktionaler Bruch, rein Build-Manifest-Drift.

**Lösung (mit Timo abgestimmt):** `regenerate_raw.py` wird wie seine drei
Geschwister-Dateien behandelt — unbundled Dev-/Maintenance-Tool, nicht
Teil des App-Bundles. Passt zur bereits etablierten Konvention
(`support-tools/login-probe/`, `support-tools/mcp-call-logger/` stehen
ebenfalls nicht in `SHARED_SCRIPTS`).

## FILE: src/compiler/build_manifest.py

### OLD

```python
    "garmin/garmin_extended_anaysis.py",
    # export / repair tooling — regenerate_raw.py remains a standalone CLI
    # tool ("Source Replay", referenced by garmin_backup_source.py) but is
    # no longer called from panel_archive.py::_on_silo_repair(); that path
    # was moved in-process in v1.6.5.7 and the repair logic itself was
    # extracted to garmin_silo_repair.py above in the same session arc.
    "export/regenerate_raw.py",
    # clients (external tool/service integrations — e.g. Ollama, the MCP
```

### NEW

```python
    "garmin/garmin_extended_anaysis.py",
    # clients (external tool/service integrations — e.g. Ollama, the MCP
```

## Verifikation

Echter Testlauf, keine Vermutung:

```
python tests/test_static.py
16 checks — 16 passed, 0 failed
```

Sektion 3 (`SHARED_SCRIPTS Vollständigkeit`) und Sektion 6
(`spec_from_file_location`) beide grün, letztere ohne Crash
(`spec_from_file_location: 9 Fundstelle(n) in SHARED_SCRIPTS <= Baseline
(10)` — Rückgang um 1, da eine Datei weniger im Scan-Set; `<=`-Vergleich,
kein Regressions-Alarm).

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- `docs/DOC_DRIFT_REPORT.md` (generiert von `tools/doc_guard.py`, laut
  eigenem Header "do not edit by hand") listet `export/regenerate_raw.py`
  noch in Abschnitt D als "not found anywhere in README.md" — Snapshot
  von vor diesem Fix. Korrigiert sich automatisch beim nächsten
  `doc_guard.py`-Lauf, hier bewusst nicht von Hand angefasst.
- `docs/METRICS.md` wurde durch den vorherigen Abbruch nicht aktualisiert
  — Timo muss `generate_metrics.py`/`doc_guard.py` erneut laufen lassen,
  jetzt mit diesem Fix sollte Schritt 9b durchlaufen.
- Die drei anderen verschobenen Dateien
  (`backfill_source_backup.py`/`backfill_source_intraday.py`/
  `regenerate_summaries.py`) waren nie in `build_manifest.py` gelistet —
  keine Änderung an ihnen nötig.
