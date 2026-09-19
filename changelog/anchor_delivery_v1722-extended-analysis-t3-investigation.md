# v1.7.2.2 — Baustein 6: garmin_extended_anaysis.py T3-Verfügbarkeit (Untersuchung, kein Fix)

**Kurztitel:** extended-analysis-t3-investigation

## Kontext

Sechster, als "Low priority, only if it fits well" eingestufter Punkt aus
`ROADMAP.md`s v1.7.2.2-Liste: unklar, ob `garmin/garmin_extended_anaysis.py`
(ein Easter Egg, per Klick auf das Unicorn-Logo im Header ausgelöst) auf
Target 3 (Standalone) tatsächlich funktioniert. Auf Timos Wunsch geprüft,
ob sich ein Fix lohnt — reine Recherche, kein Bauauftrag.

## Fund

Kein Bündelungsproblem, wie die Roadmap-Formulierung vermuten ließ — die
Datei steht bereits in `compiler/build_manifest.py:87`s `SHARED_SCRIPTS`,
die laut eigenem Kommentar "Both Target 2 and Target 3 include these" auf
beide Targets angewendet wird. Die Datei liegt also physisch in jedem
T3-Build.

Der eigentliche Befund liegt am Trigger, nicht an der Bündelung:
- `garmin_app_base.py:206` — Klick auf das Unicorn-Logo ruft
  `self._run_extended_analysis()` auf.
- `garmin_app_base.py:596-598` — Basisklasse definiert das als bewussten
  No-Op-Stub: `"""Subclass (garmin_app.py) overrides with _find_python()
  access."""` / `pass`.
- `garmin_app.py:219-235` (T1/T2-Entry-Point) überschreibt das mit der
  echten Implementierung: `subprocess.Popen([_find_python(), script],
  ..., creationflags=CREATE_NEW_CONSOLE, ...)`.
- `garmin_app_standalone.py` (T3-Entry-Point) hat **kein** eigenes
  Override und kein `_find_python()` — Grep über die ganze Datei ergab
  keinen Treffer für `_run_extended_analysis`/`extended_anaysis`/
  `_find_python`.

Auf T3 landet der Klick also im Basis-`pass` — kein Fehler, kein Crash,
kein Log, einfach keine sichtbare Reaktion. Konsistent mit dem "Easter
egg — fails silently"-Kommentar in `garmin_app.py`, nur dass dort gar
nicht erst versucht wird, etwas zu starten.

## Bewertung — lohnt sich ein Fix?

Nein. Ein echter Fix bräuchte entweder:
- einen vierten eigenständigen PyInstaller-Exe-Baustein (analog zu
  `daily_update.exe`/`mcp_server.exe`), nur für dieses Easter Egg, oder
- eine In-Process-Umstellung (z. B. `runpy.run_path()` statt
  `subprocess.Popen`), die das aktuelle Design ("eigenes neues
  Konsolenfenster") bewusst ändern würde.

Beides ist unverhältnismäßiger Aufwand für ein verstecktes Easter Egg
ohne funktionale Bedeutung — laut `docs/MAINTENANCE_GLOBAL.md:30` und
`docs/MINDSET.md:104` bewusst aus der regulären Referenz-Doku
ausgeschlossen, separat CC-BY-4.0-lizenziert, reiner Projekt-Humor. Die
Roadmap selbst stufte den Punkt bereits als niedrigste Priorität aller
sechs v1.7.2.2-Punkte ein. Timo hat die Empfehlung bestätigt: weglassen.

## FILE: src/docs/ROADMAP.md

### OLD

```markdown
**Encrypted Dashboards**
- `dash_encryptor.py`'s HTML lock screen still hardcodes hex colors instead of
  pulling from `theme.py` — the dashboard content behind the lock screen already
  does. Single-file fix, string injection into the generated HTML.

**Low priority, only if it fits well**
- `garmin_extended_anaysis.py` availability in T3 — may already be bundled (listed
  in `build_manifest.py`'s file list); needs a real T1/T2/T3 build-target comparison
  before the actual gap, if any, is known.

---
```

... (am Ende der Datei, im "Not planned"-Abschnitt) ...

```markdown
- qwen3/qwen2.5-coder enforcement for the Chat tab's `mcp` source (v1.7.2) —
  stays an advisory hint (`_mcp_model_hint`), not an enforced restriction;
  any installed Ollama model remains technically selectable. Decision taken
  during the v1.7.2 build, not a gap.

---
```

### NEW

```markdown
**Encrypted Dashboards**
- `dash_encryptor.py`'s HTML lock screen still hardcodes hex colors instead of
  pulling from `theme.py` — the dashboard content behind the lock screen already
  does. Single-file fix, string injection into the generated HTML.

---
```

... (am Ende der Datei, im "Not planned"-Abschnitt) ...

```markdown
- qwen3/qwen2.5-coder enforcement for the Chat tab's `mcp` source (v1.7.2) —
  stays an advisory hint (`_mcp_model_hint`), not an enforced restriction;
  any installed Ollama model remains technically selectable. Decision taken
  during the v1.7.2 build, not a gap.
- `garmin_extended_anaysis.py` (Easter Egg) on T3 (v1.7.2.2) — investigated,
  not fixed. The file is already bundled on both T2 and T3
  (`build_manifest.py`'s `SHARED_SCRIPTS`), so it's not a bundling gap as
  originally suspected. The actual issue: the hidden trigger (a click on the
  header unicorn) calls `_run_extended_analysis()`, which `garmin_app_base.py`
  defines as a no-op stub ("Subclass (garmin_app.py) overrides with
  `_find_python()` access") — `garmin_app.py` (T1/T2) overrides it with a real
  `subprocess.Popen([_find_python(), script], ...)` call, but
  `garmin_app_standalone.py` (T3) never does, so on T3 the click silently does
  nothing. A real fix would need either a fourth standalone PyInstaller exe
  (next to the GUI, `daily_update.exe`, `mcp_server.exe`) or an in-process
  rewrite (e.g. `runpy` instead of a subprocess'd new console window) — both
  disproportionate effort for a hidden Easter Egg with no functional role
  (`MAINTENANCE_GLOBAL.md`/`MINDSET.md`: intentionally excluded from the
  regular reference docs, project-humor module, separately CC-BY-licensed).
  Left as a silent no-op on T3, decided against fixing.

---
```

## Verifikation

Reine Recherche — Grep nach `garmin_extended_anaysis`/`_run_extended_analysis`/
`_find_python` über das gesamte `src/`-Verzeichnis, gezielt auch gegen
`garmin_app_standalone.py` (kein Treffer dort — bestätigt das fehlende
Override). Kein Code geändert, kein Testlauf nötig/anwendbar.

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- Kein Code-Fix — bewusste Entscheidung, den Zustand so zu belassen.
- Damit ist die komplette v1.7.2.2-Roadmap-Liste (alle sechs Punkte)
  bearbeitet: fünf umgesetzt (Bausteine 1-5), einer bewusst
  zurückgestellt/nicht geplant (dieser Baustein).
