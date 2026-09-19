# v1.7.2.2 — Baustein 3: You/Assistant Kontrast + Leerzeile

**Kurztitel:** chat-turn-contrast

## Kontext

Dritter Punkt aus `ROADMAP.md`s v1.7.2.2-Liste: visueller Kontrast zwischen
"You"- und "Assistant"-Turns (Akzentfarbe) plus eine Leerzeile dazwischen —
aktuell auf den ersten Blick zu schwer auseinanderzuhalten. In der
Rückfrage zum Analyse-Schritt hat Timo die ursprünglich vorgeschlagene
Variante (nur "You" farbig, "Assistant" bleibt Standardtext) korrigiert:
beide Sprecher-Label sollen die Akzentfarbe bekommen — "auch der assistant
verschwindet schnell im text". Ziel ist also Kontrast gegen den
Nachrichtentext, nicht Unterscheidung der beiden Sprecher voneinander.

## Fund

Zwei Render-Stellen bauen die Sprecher-Zeile identisch, beide ohne Farbe
und ohne Absatzabstand: `_chat_append_line()` (nicht-gestreamte Turns,
u. a. "You") und `_chat_start_stream_line()` (gestreamte
Assistant-Antworten, Fortsetzung über `_chat_append_stream_chunk()`).
`theme.py` hält bewusst nur ein knappes Farbset ohne
Domain-/Funktionsfarben — für den Kontrast reicht `self._app.ACCENT`
(bereits im ganzen Panel für Primär-Aktionen genutzt), kein neuer
Theme-Token nötig.

## FILE: src/app/panel_chat.py

### OLD

```python
    def _chat_append_line(self, speaker: str, text: str):
        safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace("\n", "<br>"))
        self._chat_view.append(f"<b>{speaker}:</b> {safe}")
```

```python
        self._chat_view.append(f"<b>{speaker}:</b> ")
        self._chat_view.moveCursor(QTextCursor.MoveOperation.End)
```

### NEW

```python
    def _chat_append_line(self, speaker: str, text: str):
        safe = (text.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace("\n", "<br>"))
        self._chat_view.append(
            f"<br><b style='color:{self._app.ACCENT};'>{speaker}:</b> {safe}")
```

```python
        self._chat_view.append(
            f"<br><b style='color:{self._app.ACCENT};'>{speaker}:</b> ")
        self._chat_view.moveCursor(QTextCursor.MoveOperation.End)
```

## Verifikation

Pflichtabgleich vor dem Edit: Grep nach `"You"`/`"Assistant"`,
`_chat_view.append`, `_chat_append_line`/`_chat_start_stream_line`/
`_chat_append_stream_chunk`/`_chat_append_system` in `panel_chat.py` und
`tests/test_qt_app.py`. `_chat_append_system()` (Systemmeldungen, gelb/
kursiv) bewusst unverändert gelassen — nicht Teil dieses Roadmap-Punkts.
Testabgleich vorab: alle Chat-View-Assertions in `test_qt_app.py` prüfen
ausschließlich `toPlainText()` (Substring/Count/`.strip()`-Vergleich), kein
Test prüft HTML/Styling direkt — das führende `<br>` bricht keine davon.

Echter Testlauf (reale Qt-Widgets via `qtbot`, kein Mock der Render-Pfade):

```
pytest tests/test_qt_app.py -k "PanelChat" -v
84 passed, 82 deselected in 1.37s
```

Alle 84 `TestPanelChat`-Tests grün, inkl. der Streaming-/History-/
Mehrfach-Turn-Tests, die die Sprecher-Label-Ausgabe direkt prüfen
(`test_start_stream_line_shows_speaker_label`,
`test_append_stream_chunk_continues_same_line`,
`test_cloud_mcp_worker_routes_text_events_to_new_bubble_per_turn`).

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- Nebeneffekt: die allererste Zeile eines neuen Chats bekommt durch das
  führende `<br>` ebenfalls etwas Abstand nach oben (kein separater
  "erster Turn"-Sonderfall gebaut) — kosmetisch, von Timo nicht beanstandet.
- `_chat_append_system()` (Systemmeldungen/Warnungen) bleibt unverändert,
  kein Leerzeilen-/Farb-Update dort — nicht Teil dieses Roadmap-Punkts.
- Die übrigen zwei v1.7.2.2-Punkte (Ollama-Dropdown-Sortierung +
  README-Tabelle, `dash_encryptor.py`-Theme-Fix) sind nicht Teil dieser
  Datei.
