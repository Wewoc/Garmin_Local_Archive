# v1.7.2.2 — Baustein 1: Model-Switch mid-chat kein Reset mehr

**Kurztitel:** model-switch-no-reset

## Kontext

`ROADMAP.md`s v1.7.2.2-Planung (Abschnitt "Chat panel", erster Punkt) listet
dies als ersten von fünf unabhängig lieferbaren Fixes für diese Runde:
Modellwechsel mitten im Chat sollte die laufende Konversation nicht mehr
zurücksetzen. `_chat_on_model_changed()` rief bisher `_chat_on_new_chat()`
auf — jeder Wechsel im Modell-Dropdown löschte History und Chat-Ansicht,
auch wenn der Nutzer nur das Modell wechseln, nicht neu anfangen wollte.

## Fund

`_chat_on_model_changed()` (`app/panel_chat.py`) rief unbedingt
`_chat_on_new_chat()` auf, sobald das Modell-Dropdown aktiviert war
(`isEnabled()`-Guard nur zum Unterdrücken des Resets während des
programmatischen `addItems()`-Aufrufs in `_build_ui()`). Root Cause war
keine Fehlfunktion, sondern eine bewusste v1.6.6-KONZEPT-§4-Entscheidung
("verschiedene Modelle haben unterschiedliche Context-Limits/Stile — History
über einen Modellwechsel hinweg mitzunehmen ist ein bewusstes Nicht-Ziel"),
die laut ROADMAP-Planung als nicht mehr zwingend akzeptiert wird: das
bestehende Context-Limit-Error-Handling deckt einen Overflow durch Wechsel
auf ein kleineres Modell bereits ab, und `_chat_save_session()` liest das
aktive Modell bei jedem Turn live aus `_model_combo.currentText()` — kein
Schema-/Stale-State-Risiko beim Sessions-Speichern.

## FILE: src/app/panel_chat.py

### OLD

```python
    def _chat_on_model_changed(self, _index: int):
        # Different models have different context limits/styles — carrying
        # history across a model switch is a deliberate non-goal (KONZEPT §4).
        if self._model_combo.isEnabled():
            self._chat_on_new_chat()
```

### NEW

```python
    def _chat_on_model_changed(self, _index: int):
        # v1.7.2.2: deliberately a no-op. Switching models mid-chat used to
        # reset the conversation (KONZEPT §4 — different models have
        # different context limits/styles); that reset is no longer
        # triggered here. Different-context-window risk is covered by the
        # existing context-limit error handling, and _chat_save_session()
        # already reads the model live from _model_combo on every turn, so
        # the saved session file reflects whichever model was last used —
        # no separate reset needed.
        pass
```

## FILE: src/tests/test_qt_app.py

### OLD

```python
    def test_model_changed_triggers_new_chat_only_when_enabled(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._model_combo.setEnabled(False)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]

        panel._model_combo.setEnabled(True)
        panel._chat_on_model_changed(0)
        assert panel._history == []
```

### NEW

```python
    def test_model_changed_does_not_reset_history(self, qtbot, app_mock):
        from app.panel_chat import PanelChat
        panel = PanelChat(app_mock)
        qtbot.addWidget(panel)
        panel._history = [{"role": "user", "content": "hi"}]
        panel._model_combo.setEnabled(False)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]

        panel._model_combo.setEnabled(True)
        panel._chat_on_model_changed(0)
        assert panel._history == [{"role": "user", "content": "hi"}]
```

## Verifikation

Pflichtabgleich vor dem Edit: repo-weiter Grep nach
`_chat_on_model_changed`/`_chat_on_new_chat` (siehe PROTOKOLL-Eintrag für
Details) — einziger Produktivcode-Aufrufer war der Signal-Connect in
`_build_ui()`, keine weiteren Callsites. `_chat_loaded_model`-Fluss separat
geprüft: wird unabhängig vom Reset in `_chat_on_model_changed()` an anderer
Stelle (Vorbelegung nach Session-Load) genullt, keine Kollision.

Echter Testlauf (kein Mock), reale Qt-Widgets via `qtbot`:

```
pytest tests/test_qt_app.py -k "model_changed or new_chat" -v
7 passed, 156 deselected in 0.73s
```

Alle sieben Tests im New-Chat/Model-Changed-Umfeld grün, inkl. dem
umbenannten `test_model_changed_does_not_reset_history`.

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- Volle Testsuite (alle 14 Suites) in dieser Runde nicht zusätzlich
  gelaufen — auf Wunsch von Timo, gezielter Lauf als ausreichend bewertet.
- Die übrigen vier v1.7.2.2-Punkte (Chat-History-Multi-Select,
  You/Assistant-Kontrast, Ollama-Dropdown-Sortierung + README-Tabelle,
  `dash_encryptor.py`-Theme-Fix) sind nicht Teil dieser Datei — jeweils
  eigene Anchor-Delivery pro Baustein.
- Punkt 6 (`garmin_extended_anaysis.py` in T3) bewusst separat betrachtet,
  noch nicht begonnen — erfordert laut ROADMAP erst einen
  Build-Target-Vergleich, kein reiner Fix.
