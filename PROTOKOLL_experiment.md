# PROTOKOLL — garmin_collector-1_work (Experimentierraum)

Append-only. Ein Abschnitt `## <Datum> — <Titel>` pro Schritt, chronologisch
ans Ende angehängt, nichts wird nachträglich umgeschrieben. Das Warum hinter
den Bausteinen — Details je Fund/Änderung stehen in den zugehörigen
`changelog/anchor_delivery_*.md`-Dateien.

---

## 2026-09-19 — v1.7.2.2 Planungsrunde + Baustein 1: Model-Switch kein Reset mehr

**Planung:** `ROADMAP.md`s v1.7.2.2-Abschnitt ("Chat Panel Polish & Quick
Fixes") als Bauauftragsgrundlage bestätigt — fünf unabhängig lieferbare
Punkte (Model-Switch-Reset, Chat-History-Multi-Select, You/Assistant-
Kontrast, Ollama-Dropdown-Sortierung + README-Tabelle,
`dash_encryptor.py`-Theme-Fix) plus ein separat zu betrachtender
Low-Priority-Punkt (`garmin_extended_anaysis.py` in T3, erfordert erst
Build-Target-Vergleich statt eines direkten Fixes). Reihenfolge: der Reihe
nach wie in der Roadmap gelistet, Punkt 6 gesondert.

**Baustein 1 — Model-Switch mid-chat kein Reset mehr:**

- Pflichtabgleich (vor dem Edit): repo-weiter Grep nach
  `_chat_on_model_changed`/`_chat_on_new_chat` über `src/`. Treffer:
  `app/panel_chat.py` (Definition, Signal-Connect in `_build_ui()`, mehrere
  Kommentarstellen), `clients/chat_session_store.py` (Doku-Kommentar, kein
  Code-Aufruf), `tests/test_qt_app.py` (mehrere Tests, darunter der direkt
  betroffene `test_model_changed_triggers_new_chat_only_when_enabled`),
  `docs/REFERENCE_GLOBAL.md`/`docs/MAINTENANCE_GLOBAL.md` (Doku-Erwähnung,
  nicht code-relevant). Einziger Produktivcode-Aufrufer von
  `_chat_on_model_changed()` war der Signal-Connect — kein weiterer
  Callsite-Fund. `_chat_loaded_model`-Fluss separat geprüft: wird an anderer
  Stelle (Vorbelegung nach Session-Load, Zeile ~883) unabhängig genullt,
  keine Kollision mit dem Wegfall des Resets hier. `_chat_save_session()`
  bestätigt: liest das aktive Modell live aus `_model_combo.currentText()`
  bei jedem Save — kein Schema-Impact, kein Stale-State-Risiko.
- Gebaut: `_chat_on_model_changed()` zu einem bewussten No-Op reduziert
  (erklärender Kommentar statt stillschweigend leer); Test
  `test_model_changed_triggers_new_chat_only_when_enabled` →
  `test_model_changed_does_not_reset_history` umbenannt und auf "History
  bleibt in beiden Enabled-Zuständen erhalten" umgestellt. Details/Diff in
  `changelog/anchor_delivery_v1722-model-switch-no-reset.md`.
- Live-Test-Ergebnis: `pytest tests/test_qt_app.py -k "model_changed or
  new_chat" -v` — 7 passed, 0 failed, echter Lauf über reale Qt-Widgets
  (`qtbot`), kein Mock. Volle Suite auf Wunsch von Timo in dieser Runde
  nicht zusätzlich gelaufen.
- Keine selbst gefundenen Bugs in diesem Baustein.

---

## 2026-09-19 — v1.7.2.2 Baustein 2: Chat-History-Dialog Multi-Select Delete

- Design-Entscheidung (mit Timo abgestimmt, ohne Rückfrage-Widerspruch
  bestätigt): `ChatHistoryDialog.get_result()` liefert bei `"delete"` ab
  sofort immer eine Liste von Pfaden — auch bei genau einer Auswahl, kein
  Sonderfall Single- vs. Multi-Delete. `"load"` bleibt ein einzelner String
  (Load bleibt auf genau 1 Auswahl begrenzt).
- Pflichtabgleich (vor dem Edit): repo-weiter Grep nach `ChatHistoryDialog`,
  `get_result`, `_chat_on_open_history`, `delete_session` über `src/`.
  Treffer: `app/dialog_chat_history.py` (Definition), `app/panel_chat.py`
  (einziger Produktivcode-Aufrufer, `_chat_on_open_history()` Zeile
  ~1174-1188), `clients/chat_session_store.py` (`delete_session()` nimmt
  genau einen Pfad — bleibt so, Multi-Delete wird per Schleife im Aufrufer
  gelöst), `tests/test_qt_app.py` (`TestChatHistoryDialog`-Klasse, 8
  bestehende Tests, plus zwei `TestPanelChat`-Tests für Load/Delete-
  Delegation), `compiler/build_manifest.py`/`docs/REFERENCE_GLOBAL.md`/
  `docs/MAINTENANCE_GLOBAL.md`/`docs/DOC_DRIFT_REPORT.md` (reine
  Doku-/Build-Manifest-Erwähnungen, nicht code-relevant).
- Gebaut: `QListWidget.setSelectionMode(ExtendedSelection)`;
  `_update_button_state()` — Load nur bei genau 1 Auswahl aktiv, Delete bei
  ≥1; neue `_selected_paths()`-Helper; `_on_delete()` sammelt alle
  selektierten Pfade, Confirm-Text pluralisiert ab 2 Chats; `get_result()`
  liefert bei `"delete"` eine Liste. `panel_chat.py`s
  `_chat_on_open_history()` iteriert entsprechend über die Pfad-Liste beim
  Löschen. Details/Diff in
  `changelog/anchor_delivery_v1722-chat-history-multiselect.md`.
- Test-Anpassungen: bestehender `test_on_delete_confirmed_sets_result` auf
  Listen-Ergebnis umgestellt; zwei neue Dialog-Tests (Load dimmt bei
  Mehrfachauswahl, Delete liefert alle Pfade); bestehender
  `test_open_history_delete_calls_store_delete` auf Listen-Fake-Result
  umgestellt; ein neuer `TestPanelChat`-Test für Mehrfach-Löschung
  (`delete_session()` wird pro Pfad einzeln aufgerufen).
- Live-Test-Ergebnis: `pytest tests/test_qt_app.py -k "ChatHistoryDialog or
  open_history" -v` — 14 passed, 0 failed, echter Lauf über reale
  Qt-Widgets (`qtbot`), nur `QMessageBox.question` gemockt (wie schon zuvor
  bei den bestehenden Delete-Tests üblich). Volle Suite auf Wunsch von Timo
  in dieser Runde nicht zusätzlich gelaufen.
- Keine selbst gefundenen Bugs in diesem Baustein.

---

## 2026-09-19 — v1.7.2.2 Baustein 3: You/Assistant Kontrast + Leerzeile

- Pflichtabgleich (vor dem Edit): Grep nach `"You"`/`"Assistant"`,
  `_chat_view.append`, `_chat_append_line`/`_chat_start_stream_line`/
  `_chat_append_stream_chunk`/`_chat_append_system` über `app/panel_chat.py`
  und `tests/test_qt_app.py`. Zwei Render-Stellen gefunden
  (`_chat_append_line()`, `_chat_start_stream_line()`), beide identisch
  ohne Farbe/Abstand. `theme.py` gelesen — hält bewusst kein
  Domain-/Funktionsfarbset, `self._app.ACCENT` (im Panel bereits für
  Primär-Aktionen genutzt) reicht für den Kontrast, kein neuer Token.
  Testabgleich: alle Chat-View-Assertions in `test_qt_app.py` prüfen nur
  `toPlainText()` (Substring/Count/`.strip()`), keine HTML-/Styling-Checks
  — Änderung bricht strukturell keinen bestehenden Test.
- Rückfrage/Korrektur: Analyse-Vorschlag war zunächst nur "You" farbig,
  "Assistant" bleibt Standardtext (Unterscheidung der Sprecher
  voneinander). Timo hat das korrigiert — beide Sprecher-Label sollen die
  Akzentfarbe bekommen, weil auch "Assistant" im Fließtext untergeht.
  Zielsetzung also Kontrast gegen den Nachrichtentext, nicht Unterscheidung
  der beiden Rollen voneinander.
- Gebaut: `_chat_append_line()` und `_chat_start_stream_line()` — Sprecher-
  Label jetzt `<b style='color:{ACCENT}'>`, plus führendes `<br>` für die
  Leerzeile zwischen Turns. `_chat_append_system()` (Systemmeldungen)
  bewusst unverändert gelassen. Details/Diff in
  `changelog/anchor_delivery_v1722-chat-turn-contrast.md`.
- Live-Test-Ergebnis: `pytest tests/test_qt_app.py -k "PanelChat" -v` —
  84 passed, 0 failed, echter Lauf über reale Qt-Widgets (`qtbot`). Volle
  Suite auf Wunsch von Timo in dieser Runde nicht zusätzlich gelaufen.
- Keine selbst gefundenen Bugs in diesem Baustein. Kosmetischer
  Nebeneffekt notiert: führendes `<br>` gibt auch der allerersten Zeile
  eines neuen Chats etwas Abstand nach oben — akzeptiert, kein
  Sonderfall gebaut.

---

## 2026-09-19 — v1.7.2.2 Baustein 4: Ollama-Dropdown-Sortierung + README-Modelltabelle

- Status-Check zuerst: `_sort_models_qwen_first()` existierte bereits vor
  dieser Session (Grep-Fund in `panel_chat.py:348`, verdrahtet an
  `panel_chat.py:874`, zugehörige Tests liefen im Baustein-3-Testlauf
  schon grün mit) — Sortierungs-Teil des Roadmap-Punkts ohne weiteren Code
  erledigt.
- Blocker gefunden: kein `mcp_test/`-Ordner in diesem Repo, die von der
  Roadmap geforderten Benchmark-Läufe (`lauf_22-2` 2026-09-17, `lauf_20`
  2026-09-14) waren nicht auffindbar. Nicht geraten, sondern
  zurückgefragt — Timo nannte den Pfad `D:\Garmin\template\mcp_test`.
- Pfad geprüft: keine vorgerechnete "avg response time"-Zusammenfassung
  vorhanden, nur pro-Frage-`duration_seconds` in den Roh-JSON-Ergebnissen.
  Werte per Python direkt aus den JSONs aggregiert (Mittelwert, Median,
  Max, Fehler-/Timeout-Anzahl je Modell) — siehe
  `changelog/anchor_delivery_v1722-ollama-model-table-refresh.md` für die
  vollständigen Zahlen und den genutzten Dateipfad je Lauf.
- Wichtiger Befund: die beiden Läufe nutzen unterschiedliche
  Frage-Kataloge (leichte Single-Field-Fragen vs. schwere Long-Range-/
  Korrelationsfragen) und sind nicht direkt vergleichbar —
  `granite4.1:8b` kommt in beiden vor und zeigt 10.8s vs. 44.3s Ø, selbes
  Modell, dieselbe Hardware, nur schwererer Katalog.
- Rückfrage/Korrektur: Timo wollte den Abschnitt explizit als
  unverbindliche, tendenzielle Beobachtung betitelt haben, mit den
  Testanordnungs-Lücken klar aufgelistet ("es ist eine Tendenz und keine
  belegte Wahrheit") — plus englische Bezeichnung der Läufe im Doku-Text
  ("Run 20"/"Run 22-2" statt "lauf_20"/"lauf_22-2").
- Gebaut: neuer Abschnitt "Response time — informal tendency, not a
  benchmark" in `docs/README_APP.md`, direkt unter der bestehenden
  Suitability-Tabelle — zwei Tabellen (eine je Lauf/Katalog) plus fünf
  explizit benannte Lücken (Katalog-Unterschied, Einzel-Lauf ohne
  Wiederholung, ungeloggte Systemlast, Timeouts aus dem Mittelwert
  herausgefallen, `granite4.1` weiterhin ohne Korrektheits-Pass).
  Reiner Doku-Edit, kein Code betroffen, kein Testlauf nötig.
- Keine selbst gefundenen Bugs in diesem Baustein.

---

## 2026-09-19 — v1.7.2.2 Baustein 5: dash_encryptor.py Theme-Fix

- Rückfrage von Timo zum Analyse-Vorschlag: ob die geplante Lösung ein
  "indirekter Import" sei. Klargestellt: nein — reine Parameter-Übergabe
  (Dependency Injection), `dash_encryptor.py` bleibt komplett unabhängig
  von `theme.py`s Existenz/Struktur, die Kopplung an Theme-Farben lebt
  ausschließlich in der Aufrufstelle `_dashboard_build.py`, die diese
  Abhängigkeit ohnehin schon hat.
- Pflichtabgleich (vor dem Edit): repo-weiter Grep nach `encrypt_html`/
  `dash_encryptor` über `src/`. Einziger Aufrufer bestätigt
  (`app/popups/_dashboard_build.py:176-203`, dynamisch per
  `spec_from_file_location` geladen). Leaf-Node-Invariante in
  `docs/REFERENCE_INVARIANTS.md:26` und im Modul-Docstring gegengelesen.
  `garmin_app_base.py:94-103` als Quelle der `self._app.BG/BG2/ACCENT/
  ACCENT2/TEXT/TEXT2/RED`-Attribute verifiziert (direkt aus `theme.py`
  gespiegelt). Hartkodierte Hex-Werte im Lock-Screen entsprachen 1:1
  `THEME_2` ("Violet Legacy") — Fund: eingefroren auf den alten
  Default-Theme von vor dem Mehr-Themen-System.
- Gebaut: `encrypt_html()` bekommt optionale, keyword-only Theme-Parameter
  (`bg`/`bg2`/`accent`/`accent2`/`text`/`text2`/`red`) mit den alten
  Hex-Werten als Default; `_build_wrapper()` reicht sie in die CSS-Stellen
  durch statt der Hex-Literale. `_dashboard_build.py` übergibt jetzt
  `panel._app.BG/BG2/ACCENT/ACCENT2/TEXT/TEXT2/RED`. Details/Diff in
  `changelog/anchor_delivery_v1722-dash-encryptor-theme.md`.
- Test-Ergänzung: drei neue Checks in `tests/test_dashboard.py` Abschnitt
  17 (Custom-Farben erscheinen im Output; Default-Aufruf bleibt
  byte-identisch zur alten Palette). Bestehender zweiargumentiger
  Testaufruf unverändert gültig dank Defaults.
- Live-Test-Ergebnis: volle `test_dashboard.py`-Suite (eigenes
  Check-Framework, kein pytest) — `PYTHONIOENCODING=utf-8 python
  tests/test_dashboard.py` — 472 checks, 472 passed, 0 failed. Abschnitt
  17 im Detail: alle 13 Checks grün, inkl. der 3 neuen.
- Selbst gefundener Nebenbefund (nicht behoben, nicht Teil dieses Fixes):
  `python tests/test_dashboard.py` ohne `PYTHONIOENCODING=utf-8` bricht
  auf dieser Windows-Konsole mit `UnicodeEncodeError` in
  `tests/support.py`s `section()` ab (cp1252-Codepage) — vorbestehend,
  reproduzierbar auch auf unverändertem HEAD, unabhängig von dieser
  Änderung.
- Damit sind alle fünf Hauptpunkte der v1.7.2.2-Roadmap-Liste bearbeitet.
  Punkt 6 (`garmin_extended_anaysis.py` in T3) war laut Absprache von
  Beginn an separat zu betrachten.

---

## 2026-09-19 — v1.7.2.2 Baustein 6: garmin_extended_anaysis.py T3-Verfügbarkeit (Untersuchung, kein Fix)

- Reine Recherche auf Timos Wunsch ("schau dir das mal an ob sich das
  lohnt oder ob wir das einfach weg lassen") — kein Bauauftrag, nur
  Grep/Read.
- Pflichtabgleich: Grep nach `garmin_extended_anaysis`/
  `_run_extended_analysis`/`_find_python` über `src/`. Fund: Datei bereits
  in `compiler/build_manifest.py:87`s `SHARED_SCRIPTS` (für T2 und T3
  gleichermaßen) — kein Bündelungsproblem. Eigentlicher Befund am Trigger:
  `garmin_app_base.py:596-598` definiert `_run_extended_analysis()` als
  bewussten No-Op-Stub, `garmin_app.py` (T1/T2) überschreibt ihn mit der
  echten `subprocess.Popen`-Implementierung, `garmin_app_standalone.py`
  (T3) hat kein Override — Klick auf das Unicorn-Logo tut auf T3 still
  nichts (kein Fehler, kein Log).
- Bewertung: Fix nicht lohnend — bräuchte entweder einen vierten
  PyInstaller-Exe-Baustein oder eine In-Process-Umstellung
  (`runpy` statt Subprocess/neues Konsolenfenster), beides
  unverhältnismäßig für ein verstecktes, funktionslos dokumentiertes
  Easter Egg (`MAINTENANCE_GLOBAL.md`/`MINDSET.md`). Timo hat die
  Empfehlung bestätigt: weglassen.
- Gebaut (Doku-only): `docs/ROADMAP.md` — Punkt aus der v1.7.2.2-Liste
  entfernt, stattdessen neuer Eintrag im "Not planned"-Abschnitt mit
  Fund + Begründung. Details/Diff in
  `changelog/anchor_delivery_v1722-extended-analysis-t3-investigation.md`.
- Kein Testlauf nötig (reiner Doku-Edit, keine Code-Änderung).
- Damit ist die komplette v1.7.2.2-Roadmap-Liste (alle sechs Punkte)
  bearbeitet — fünf umgesetzt, einer bewusst zurückgestellt.

---

## 2026-09-19 — v1.7.2.2 Release-Doku-Abschluss (FINAL_DOKU_PROMPT_v4.md Precondition + Schritt 1-8)

- Timo hat die externe `FINAL_DOKU_PROMPT_v4.md`-Checkliste (Session-
  Abschluss-Protokoll, umfangreicher als die reine Anchor-Delivery/
  Protokoll-Pflicht dieses Repos) eingebracht und beauftragt: "bis punkt
  9 — dann lasse ich die scripte laufen dann schauen wir weiter". Auftrag
  also Precondition + Schritt 1-8, Schritt 9 (Testsuite) bewusst Timo
  überlassen.
- Precondition Teil A (Architektur-Check): alle Session-Module gegen
  Sole-Write-Authority/Broker-Pattern/Plugin-Prinzip/Leaf-Node/
  QUALITY_LOCK geprüft — kein Fund, grün.
- Precondition Teil B (Drift-Check): Pflicht, da `layouts/dash_encryptor.py`
  geändert wurde. Externes Tool `D:\Garmin\template\03_build_dep_map\
  build_dep_map.py --baseline output\2026-09-19_Run-01\dep_map_records.json`
  gelaufen (erzeugt Run-02) — Ergebnis: 0 NEU · 0 WEG · 0
  GEKIPPT-Regression · 0 GEKIPPT-Verbesserung. Grün, kein Blocker.
- Schritt 1: `version.py` → `1.7.2.2`.
- Schritt 2: neuer `CHANGELOG.md`-Eintrag oben, vollständige
  Changed-modules-Liste, ehrlicher Test-Result-Vermerk (gezielte Läufe +
  volle `test_dashboard.py`-Suite benannt, kanonische Vier-Skript-Suite
  explizit als "steht noch aus" markiert statt fälschlich "all green").
- Schritt 3: `ROADMAP.md` — v1.7.2.2-Planungsabschnitt entfernt (folgt der
  bestehenden lokalen Konvention: keine Strikethrough-Archivierung in
  dieser Datei), `Currently stable` → v1.7.2.2.
- Schritt 4: `build_manifest.py` — keine neuen/gelöschten Module in
  dieser Session, alle vier geänderten Dateien bereits gelistet, nichts
  zu tun.
- Schritt 5: `REFERENCE_*.md` — nur `REFERENCE_DASHBOARD.md` betroffen,
  bereits in Baustein 5 erledigt. Übrige REFERENCE-Dateien geprüft, keine
  Änderung nötig.
- Schritt 6: `MAINTENANCE_DASHBOARD.md` Zeile 163 (Sektion 17) um die drei
  neuen Theme-Parameter-Checks ergänzt.
- Schritt 6b: `GLA_GUIDELINES.md` Abschnitt 1 + Part II gegengelesen,
  weiterhin akkurat. Vorbestehende Lücke gefunden (Leaf-Node-Beispielliste
  nennt `dash_encryptor.py` nicht), nicht durch diese Session verursacht,
  bewusst nicht mitkorrigiert.
- Schritt 7: `README.md` (Projekt-Root) geprüft, kein Update nötig.
- Schritt 8: `README_APP.md`-Titelzeile → v1.7.2.2. `QUICKSTART.txt`/
  `USER_GUIDE.txt` geprüft, keine Versionsnummer-Erwähnung gefunden.
- Details/vollständige Diffs in
  `changelog/anchor_delivery_v1722-release-doku-schritt1-8.md`.
- Offene Rückfrage an Timo (siehe Anchor-Delivery): soll der frische
  `dep_map_records.json` (Run-02) nach `docs/dep_map_records.json` in
  dieses Repo committet werden als neue Baseline-Konvention, oder bleibt
  die Historie beim externen Tool in `03_build_dep_map/output/`?
- Schritt 9 (Testsuite-Lauf) bewusst nicht durchgeführt — Timo übernimmt
  das selbst laut Absprache.

---

## 2026-09-19 — v1.7.2.2 Baustein 7: build_manifest.py Stale-Path-Fix (export/ → support-tools/archive-maintenance/)

- Timo hat Schritt 9 selbst laufen lassen: alle 13 Kern-Suiten grün
  (2.376 Checks, 0 failed), aber `test_static.py` brach ab und riss
  `generate_metrics.py`/Schritt 9b mit ("Abbruch — METRICS.md bleibt
  unverändert").
- Pflichtabgleich: `export/` existiert nicht mehr (verschoben nach
  `support-tools/archive-maintenance/`, deckt sich mit dem vorab
  mitgeschickten `dep_map_delta.md`). Zeitstempel bestätigt: Verschiebung
  heute 13:24, nicht durch diese Session verursacht. `grep` bestätigt:
  `compiler/build_manifest.py:93` einzige verbliebene Referenz auf den
  alten Pfad (`"export/regenerate_raw.py"`); die drei anderen
  verschobenen Dateien standen nie in `build_manifest.py`.
  `garmin_backup_source.py`s Erwähnung ist nur ein Doku-Kommentar, kein
  Laufzeit-Bezug.
- Timo bestätigte: Verschiebung der vier Dateien war bewusst. Fix:
  `regenerate_raw.py`-Eintrag + Erklärkommentar aus `SHARED_SCRIPTS`
  entfernt — passt jetzt zur bestehenden Konvention (unbundled
  Dev-Tool, wie `support-tools/login-probe/`/`support-tools/
  mcp-call-logger/`, keine dieser Tools steht in `SHARED_SCRIPTS`).
  Details/Diff in
  `changelog/anchor_delivery_v1722-build-manifest-export-move-fix.md`.
- Live-Test-Ergebnis: `python tests/test_static.py` — 16 passed, 0
  failed, kein Crash mehr in Sektion 6.
- Selbst gefundener Bug (durch Timos Testlauf aufgedeckt, nicht durch
  diese Session verursacht): stale `export/regenerate_raw.py`-Pfad in
  `build_manifest.py` nach externer Ordner-Umstrukturierung — Root Cause
  wie oben, behoben.
- Offen für Timo: `docs/DOC_DRIFT_REPORT.md` (generiert, nicht von Hand
  bearbeitet) und `docs/METRICS.md` (durch den Abbruch nicht
  aktualisiert) korrigieren sich erst beim nächsten
  `generate_metrics.py`/`doc_guard.py`-Lauf.

---

## 2026-09-19 — v1.7.2.2 Schritt 9b bestätigt: METRICS.md + DOC_DRIFT_REPORT.md sauber

- Timo hat `generate_metrics.py`/`doc_guard.py` nach dem Baustein-7-Fix
  erneut laufen lassen und beide Ergebnisdateien mitgeschickt.
- `docs/METRICS.md`: 14 Suiten, 2392 Checks, 0 failed (inkl.
  `test_static.py` 16/16), Version korrekt 1.7.2.2, Modulzahl 133 (−1
  gegenüber vorher — passt exakt zum in Baustein 7 entfernten
  `regenerate_raw.py`-Eintrag).
- `docs/DOC_DRIFT_REPORT.md`: A) 159/159 Signaturen, kein Drift. B)
  122/123 — einziger Fund `garmin_extended_anaysis.py` fehlt in den
  REFERENCE_*.md-Überschriften; kein neuer Drift, sondern bewusste,
  bereits in `MAINTENANCE_GLOBAL.md:30` dokumentierte
  Architektur-Entscheidung (Easter Egg, absichtlich ausgeschlossen) —
  hiermit explizit vermerkt, nicht stillschweigend übergangen. C) keine
  Test-Count-Behauptungen zu prüfen. D) niedrigste Priorität, erwartete
  Liste interner Module ohne README-Erwähnung, nichts Neues.
- Kein neuer, unbehandelter Drift-Fund offen gelassen. Damit ist die
  komplette Precondition-bis-Schritt-9b-Kette für v1.7.2.2 geschlossen.
- Schritte 10-13 (`NOTES_vX.Y.Z.md`, GitHub-Release-Text,
  `SESSION_BASE.md`, nächster Session-Prompt) noch offen, auf Ansage von
  Timo.

---

## 2026-09-19 — v1.7.2.2 Schritt 11: GitHub-Release-Text

- Timo hat für Schritt 10 (`NOTES_vX.Y.Z.md`) entschieden: das
  Chat-Protokoll selbst dient ihm als Notes — kein separates
  `NOTES_v1.7.2.2.md` von mir angelegt. Schritt 12 (`SESSION_BASE.md`):
  passt laut Timo bereits, keine Änderung nötig.
- Schritt 11 (GitHub-Release-Text): Precondition erfüllt — `pip show
  garminconnect` geprüft, Version 0.3.15, im Downloads-Block mitgeführt.
  Text nach der Vorlage aus `FINAL_DOKU_PROMPT_v4.md` verfasst, user-facing
  formuliert (kein internes Jargon), basierend auf dem CHANGELOG-Eintrag
  dieser Runde.
- Ablageort auf Timos Wunsch: neuer Ordner `D:\Garmin\template\templates\`
  (existierte noch nicht, angelegt), Datei
  `github_release_v1.7.2.2.md`.
- Damit sind alle Schritte bis einschließlich 11 abgeschlossen; Schritt 13
  (nächster Session-Prompt) noch offen, auf Ansage von Timo.
