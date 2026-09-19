# v1.7.2.2 — Release-Doku-Abschluss (FINAL_DOKU_PROMPT_v4.md Precondition + Schritt 1-8)

**Kurztitel:** release-doku-schritt1-8

## Kontext

Timo hat für den Abschluss dieser v1.7.2.2-Runde die extern mitgeschickte
`FINAL_DOKU_PROMPT_v4.md`-Checkliste eingebracht — ein Session-Abschluss-
Protokoll, das über die reine Anchor-Delivery/`PROTOKOLL_experiment.md`-
Pflicht dieses Repos hinausgeht (Versionsbump, CHANGELOG/ROADMAP-Pflege,
REFERENCE_*/MAINTENANCE_*-Abgleich, README_APP.md-Version, Testlauf,
Doku-Automatisierung). Auftrag: "bis punkt 9 — dann lasse ich die scripte
laufen dann schauen wir weiter" — also Precondition + Schritt 1 bis 8
selbst erledigen, Schritt 9 (Testsuite-Lauf) bewusst Timo überlassen.

## Fund / Durchgeführte Schritte

**Precondition Teil A (Architektur-Check):** für alle in dieser Session
geänderten Module (`panel_chat.py`, `dialog_chat_history.py`,
`_dashboard_build.py`, `dash_encryptor.py`, zugehörige Tests/Doku) geprüft:
keine Sole-Write-Authority-, Broker-Pattern-, Plugin-Prinzip- oder
QUALITY_LOCK-Berührung. `dash_encryptor.py`s Leaf-Node-Eigenschaft explizit
bewahrt (Baustein 5) — kein neuer Fund, grün.

**Precondition Teil B (Drift-Check):** Pflicht, da `layouts/dash_encryptor.py`
geändert wurde. Lauf über das externe Tool `D:\Garmin\template\
03_build_dep_map\build_dep_map.py --baseline output\2026-09-19_Run-01\
dep_map_records.json` (Run-02 erzeugt):

```
DELTA vs 2026-09-19_Run-01: 0 NEU · 0 WEG · 0 GEKIPPT-Regression · 0 GEKIPPT-Verbesserung
```

Grün, kein Blocker — die Theme-Parametrisierung hat keine Exception-Handler
oder File-I/O-Operationen hinzugefügt/entfernt, nur String-Interpolation.

## FILE: src/version.py

### OLD
```python
APP_VERSION = "1.7.2.1"
```
### NEW
```python
APP_VERSION = "1.7.2.2"
```

## FILE: src/docs/CHANGELOG.md

Neuer Eintrag ganz oben eingefügt: `## v1.7.2.2 — Chat Panel Polish & Quick
Fixes` mit 2-3-Satz-Zusammenfassung, vollständiger "Changed modules"-Liste
(alle in dieser Session geänderten Dateien mit konkreter Beschreibung,
keine neuen Module) und ehrlichem Test-Result-Vermerk: die in dieser
Session tatsächlich gelaufenen Testläufe (gezielte pytest-Läufe je
Baustein + volle `test_dashboard.py`-Suite, 472/472) werden benannt; die
kanonische Vier-Skript-Suite (`test_local.py`/`test_local_context.py`/
`test_dashboard.py`/`test_app_logic.py`) wird explizit als "nicht in
dieser Session end-to-end gelaufen — Lauf steht noch aus" markiert, statt
fälschlich "all green" zu behaupten.

## FILE: src/docs/ROADMAP.md

`### v1.7.2.2 — Chat Panel Polish & Quick Fixes (planned)`-Abschnitt
vollständig entfernt (folgt der bestehenden lokalen Konvention dieser
Datei — ausgelieferte Versionen werden nicht als Strikethrough-Archiv
gehalten, das übernimmt `CHANGELOG.md`; `ROADMAP.md` zeigt nur noch
Geplantes). `**Currently stable — v1.7.2.1**` → `**Currently stable —
v1.7.2.2**`. (Der Punkt-6-Eintrag im "Not planned"-Abschnitt war bereits
im vorherigen Baustein nachgetragen.)

## FILE: src/docs/MAINTENANCE_DASHBOARD.md

Zeile 163 (Sektion 17, `dash_encryptor`) ergänzt um die drei neuen
Theme-Parameter-Checks, statt nur "output structure, ValueError guards"
zu nennen.

## FILE: src/docs/README_APP.md

Titelzeile `# Garmin Local Archive — Desktop App v1.7.2.1` →
`v1.7.2.2`.

## Geprüft, keine Änderung nötig

- `REFERENCE_DASHBOARD.md` — bereits in Baustein 5 auf die neue
  `encrypt_html()`-Signatur aktualisiert, kein weiterer Bedarf.
- `REFERENCE_GLOBAL.md`/`REFERENCE_GARMIN.md`/`REFERENCE_CONTEXT.md`/
  `REFERENCE_BROKER.md`/`REFERENCE_INVARIANTS.md` — keine neuen ENVs,
  Pfade, Build-Targets, Broker-Contract-Änderungen oder Invarianten in
  dieser Runde.
- `GLA_GUIDELINES.md` Abschnitt 1 (Architektur) und Part II (Workflow) —
  gegengelesen, beide weiterhin akkurat; die Leaf-Node-Beispielliste
  (§2) nennt `dash_encryptor.py` nicht namentlich, war aber bereits vor
  dieser Session unvollständig (fehlt auch in `dash_autosize.py`) —
  vorbestehende Lücke, nicht durch diese Session verursacht, bewusst
  nicht mitkorrigiert (Scope-Grenze).
- `README.md` (Projekt-Root) — keine neuen Module in `garmin/`/
  `context/`/`maps/`/`dashboards/`, keine neuen User-Features im Sinne
  der Checkliste (Polish/Fixes an bestehenden Features), keine
  versionsgebundene Aussage im Text gefunden, die aktualisiert werden
  müsste.
- `QUICKSTART.txt`/`USER_GUIDE.txt` — keine Versionsnummer-Erwähnung
  gefunden, kein Update nötig.
- `build_manifest.py` — keine neuen/gelöschten Module in dieser Session;
  alle vier geänderten Dateien (`panel_chat.py`, `dialog_chat_history.py`,
  `_dashboard_build.py`, `dash_encryptor.py`) waren bereits in
  `SHARED_SCRIPTS`/`SCRIPT_SIGNATURES_BASE` gelistet, Signatur-Substring
  `"def encrypt_html"` bleibt nach dem Baustein-5-Edit unverändert gültig.

## Verifikation

Precondition Teil A/B wie oben beschrieben, beide grün. Alle
Doku-Edits sind reine Textänderungen ohne Code-Auswirkung — kein
zusätzlicher Testlauf in diesem Baustein, da keine Programmlogik berührt
wurde (Testläufe der eigentlichen Code-Bausteine 1-5 stehen in ihren
jeweils eigenen Anchor-Deliveries).

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- **Offene Rückfrage an Timo:** der frische `dep_map_records.json`
  (Run-02) liegt aktuell nur im externen Tool-Output
  (`D:\Garmin\template\03_build_dep_map\output\2026-09-19_Run-02\`).
  `FINAL_DOKU_PROMPT_v4.md`s Precondition-Block verlangt zusätzlich,
  ihn nach `docs/dep_map_records.json` in diesem Repo zu committen als
  Baseline für die nächste Session — dieses Repo hatte diese Konvention
  bisher nicht (keine vorbestehende `docs/dep_map_records.json`-Datei).
  Nicht eigenmächtig angelegt, da das eine neue Repo-Konvention wäre;
  Rückfrage steht.
- Schritt 9 (Testsuite-Lauf: `test_local.py`/`test_local_context.py`/
  `test_dashboard.py`/`test_app_logic.py`) bewusst nicht durchgeführt —
  Timo übernimmt das selbst, laut expliziter Absprache.
- Schritt 6 (MAINTENANCE_*.md) nur punktuell nachgezogen (Zeile zu
  Sektion 17) — Test-Count-Abgleich gegen `docs/METRICS.md` bewusst
  nicht angefasst, da das laut Checkliste erst nach einem grünen
  Schritt 9 über `tools/generate_metrics.py` automatisiert läuft
  (Schritt 9b), nicht hier von Hand.
- Schritte 10-13 (`NOTES_vX.Y.Z.md`, GitHub-Release-Text,
  `SESSION_BASE.md`, nächster Session-Prompt) nicht Teil dieses
  Bausteins — laut Absprache erst nach Schritt 9 weiter besprochen.
