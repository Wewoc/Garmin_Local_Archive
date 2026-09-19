# v1.7.2.2 — Baustein 4: Ollama-Dropdown-Sortierung + README-Modelltabelle

**Kurztitel:** ollama-model-table-refresh

## Kontext

Vierter Punkt aus `ROADMAP.md`s v1.7.2.2-Liste: Ollama-Modell-Dropdown
qwen3 zuerst sortieren, plus `README_APP.md`s Modell-Empfehlungstabelle
auffrischen, gestützt auf `mcp_test/`-Benchmarkdaten (avg. response time
je Modell, Läufe `lauf_22-2` 2026-09-17 und `lauf_20` 2026-09-14).

## Fund

**Sortierung:** bereits vorhanden — `_sort_models_qwen_first()`
([panel_chat.py:348](src/app/panel_chat.py:348)) existierte schon vor
dieser Session und ist am Dropdown verdrahtet
([panel_chat.py:874](src/app/panel_chat.py:874)); die zugehörigen Tests
(`test_sort_models_qwen_first*`) liefen bereits grün mit. Kein Code-Bedarf
in diesem Baustein.

**README-Tabelle:** `mcp_test/`-Ordner existiert nicht in diesem Repo
(`garmin_collector-1_work`) — auf Timos Hinweis unter
`D:\Garmin\template\mcp_test` gefunden. Dort keine vorgerechnete
Zusammenfassung ("avg response time per model"), nur pro-Frage-Timings
(`duration_seconds`) in den Roh-JSON-Ergebnisdateien:
- `results\lauf_20_20260914_v17117_test_garanite\mcp_llm_test_2026-09-14_153522.json`
  — 75 Einträge, Katalog `question_catalog_quickeval_v1.py` (25 einfache
  Single-Field-Fragen je Modell: `granite4.1:3b`, `granite4.1:8b`, `qwen3:4b`)
- `results\lauf_22-2_20260917_v172_mulit_Systempormt\mcp_llm_test_2026-09-17_193838.json`
  — 240 Einträge, Katalog `question_catalog_longrange_health-context.py`
  (60 mehrstufige Long-Range-/Korrelationsfragen je Modell:
  `granite4.1:8b`, `qwen2.5-coder:14b`, `qwen3:14b`, `qwen3:8b`); der
  frühere `..._152235.json`-Snapshot desselben Laufs (136 Einträge) ist
  ein überholter Zwischenstand (progressive-write Muster, siehe
  `mcp_test/changlog/anchor_delivery_mcptest-02-progressive-write-resume.md`)
  und wurde nicht mit eingerechnet.

Werte per Python direkt aus den JSONs aggregiert (Mittelwert, Median, Max,
Fehler-/Timeout-Anzahl je Modell), keine Schätzung/Erfindung von Zahlen.
Wichtiger Befund dabei: die beiden Läufe nutzen unterschiedliche
Frage-Kataloge und sind **nicht direkt vergleichbar** —
`granite4.1:8b` kommt in beiden Läufen vor und zeigt 10.8s (leichter
Katalog) vs. 44.3s (schwerer Katalog), selbes Modell, dieselbe Hardware.
In der Rückfrage hat Timo bestätigt: als unverbindliche, tendenzielle
Beobachtung betiteln, Lücken aus der Testanordnung klar auflisten —
"es ist eine Tendenz und keine belegte Wahrheit". Zusätzlich: Ordnernamen
im Doku-Text englisch benennen ("Run 20"/"Run 22-2" statt "lauf_20"/
"lauf_22-2").

## FILE: src/docs/README_APP.md

### OLD

```markdown
Rough guide, not a guarantee — results depend on the exact question
phrasing and may shift with future Ollama/model versions. Test tool and
methodology: [mcp-llm-tester](https://github.com/Wewoc/GLA-NeedfulThings/tree/main/mcp-llm-tester).
```

### NEW

```markdown
Rough guide, not a guarantee — results depend on the exact question
phrasing and may shift with future Ollama/model versions. Test tool and
methodology: [mcp-llm-tester](https://github.com/Wewoc/GLA-NeedfulThings/tree/main/mcp-llm-tester).

#### Response time — informal tendency, not a benchmark (2026-09-19)

Two ad-hoc timing runs give a rough sense of per-model reply speed —
tendency only, not a controlled benchmark. Raw per-question timings in
`mcp_test/results/` (not published as part of this repo).

**Run 20, 2026-09-14 — 25 simple single-field questions per model:**

| Model | Avg | Median | Max | Timeouts/errors |
|---|---|---|---|---|
| `granite4.1:3b` | 10.2s | 6.6s | 38.6s | 0/25 |
| `granite4.1:8b` | 10.8s | 7.9s | 31.6s | 0/25 |
| `qwen3:4b` | 33.4s | 31.4s | 56.6s | 0/25 |

**Run 22-2, 2026-09-17 — 60 multi-step long-range/correlation questions per model:**

| Model | Avg | Median | Max | Timeouts/errors |
|---|---|---|---|---|
| `granite4.1:8b` | 44.3s | 40.5s | 146.7s | 6/60 |
| `qwen2.5-coder:14b` | 32.5s | 15.6s | 262.2s | 7/60 |
| `qwen3:14b` | 104.2s | 94.2s | 218.9s | 1/60 |
| `qwen3:8b` | 85.9s | 70.2s | 306.0s | 6/60 |

**Gaps this leaves open — why this is a tendency, not a measured truth:**
- Different question catalogs per run (simple single-field lookups vs.
  multi-step long-range correlation questions) — times are **not
  comparable across the two tables above**. `granite4.1:8b` appears in
  both: 10.8s on the easy catalog, 44.3s on the hard one — same model,
  same hardware, just a harder question set.
- Single run per model/catalog combination, not repeated — no variance
  or confidence data, one unusually slow or fast run can shift the
  average shown.
- Background system load on the test machine during a run isn't
  controlled or logged per run.
- Timeouts/errors (up to 7 of 60 for some models) are dropped from the
  average rather than counted as a worst-case penalty — a model that
  times out often can look artificially fast here.
- No correctness/quality pass exists yet for `granite4.1` (unlike the
  models in the Suitability table above) — timing alone says nothing
  about whether its answers are usable, so it stays out of that table
  despite competitive-looking numbers here.
```

## Verifikation

Pflichtabgleich vor dem Edit: Grep nach `qwen`/`_sort_models`/
`models_loaded` in `panel_chat.py` (bestätigte, dass die Sortierung schon
existiert) sowie nach `mcp_test`/`lauf_22`/`lauf_20` im gesamten
`garmin_collector-1_work`-Repo (kein Treffer außer dem Roadmap-Text
selbst — bestätigt, dass die Benchmarkdaten außerhalb dieses Repos
liegen). Zahlen wurden aus den Original-JSON-Dateien berechnet, nicht aus
Log-Textzeilen geparst (robuster, da `duration_seconds` ein strukturiertes
Feld pro Eintrag ist) — Berechnungsschritt und -ergebnis oben unter "Fund"
dokumentiert. Reiner Doku-Edit, kein Code betroffen — kein Testlauf nötig,
keine automatisierte Prüfung für Markdown-Prosa/Tabellen vorhanden.

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- Die Timing-Daten selbst bleiben in `D:\Garmin\template\mcp_test\` und
  werden nicht in dieses Repo kopiert/veröffentlicht — README verweist nur
  darauf.
- Keine Korrektheits-/Qualitätsauswertung für `granite4.1` gebaut oder
  angefordert — bleibt laut Roadmap ein offener, separater Schritt, bevor
  es in die Suitability-Tabelle aufgenommen werden kann.
- Der letzte v1.7.2.2-Punkt (`dash_encryptor.py`-Theme-Fix) ist nicht Teil
  dieser Datei.
