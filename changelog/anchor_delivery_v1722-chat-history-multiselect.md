# v1.7.2.2 — Baustein 2: Chat-History-Dialog Multi-Select Delete

**Kurztitel:** chat-history-multiselect

## Kontext

Zweiter Punkt aus `ROADMAP.md`s v1.7.2.2-Liste: "Delete Chat" im
`ChatHistoryDialog` (`app/dialog_chat_history.py`) erlaubte bisher nur
Single-Selection — jede Löschung einzeln, ein Klick pro gespeichertem Chat.
Vorgabe: Multi-Select für Delete, "Load"-Button dimmt sobald mehr als ein
Chat ausgewählt ist (Load ergibt bei Mehrfachauswahl keinen Sinn — man kann
immer nur eine Session gleichzeitig laden).

## Fund

`QListWidget` stand im PyQt6-Default (`SingleSelection`), `_update_button_state()`
aktivierte Load/Delete gleich (beide bei ≥1 Auswahl), `_on_delete()`/
`get_result()` gaben `("delete", <ein-path-string>)` zurück — Vertrag ließ
strukturell nur einen Pfad pro Delete-Aktion zu. Einziger Aufrufer
`app/panel_chat.py`s `_chat_on_open_history()` entpackte entsprechend
`action, path = result` und rief `store.delete_session(path)` genau einmal
auf. Kein Bug, nur ein Vertrag, der für Mehrfachauswahl erweitert werden
musste.

**Design-Entscheidung (mit Timo abgestimmt):** `get_result()` liefert bei
`"delete"` künftig immer eine Liste von Pfaden — auch bei genau einer
Auswahl, kein Sonderfall Single- vs. Multi-Delete. `"load"` bleibt ein
einzelner String.

## FILE: src/app/dialog_chat_history.py

### OLD

```python
Usage
-----
    dlg = ChatHistoryDialog(self, sessions)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        action, path = dlg.get_result()   # action: "load" | "delete"
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox,
)
```

```python
    Modal dialog listing saved chat sessions, newest first (the order
    `sessions` already arrives in — this dialog does not re-sort).
    Load and Delete act on the currently selected row; both start
    disabled until a row is selected. Delete asks for confirmation
    (QMessageBox.question, same pattern as panel_archive.py's/
    panel_outputs.py's own destructive actions) before returning —
    still only reports the choice, see module docstring.
```

```python
        self._list = QListWidget()
        self._list.setFont(QFont("Segoe UI", 9))
```

```python
    def _update_button_state(self):
        has_selection = bool(self._list.selectedItems())
        self._load_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _selected_path(self) -> str | None:
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _on_load(self):
        path = self._selected_path()
        if path is None:
            return
        self._result = ("load", path)
        self.accept()

    def _on_delete(self):
        path = self._selected_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self, "Delete Chat",
            "Delete this saved chat? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._result = ("delete", path)
        self.accept()

    def get_result(self):
        """Returns (action, path) — action is "load" or "delete",
        path is the string path of the selected session — or None if
        the dialog was closed without choosing either (Close button,
        Esc, or a declined delete confirmation followed by Close)."""
        return self._result
```

### NEW

```python
Usage
-----
    dlg = ChatHistoryDialog(self, sessions)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        action, data = dlg.get_result()   # action: "load" | "delete"
        # "load"   -> data is a single path string (Load stays single-select)
        # "delete" -> data is a list of path strings (multi-select allowed)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView,
)
```

```python
    Modal dialog listing saved chat sessions, newest first (the order
    `sessions` already arrives in — this dialog does not re-sort).
    Multi-select is allowed (ExtendedSelection — ctrl/shift-click).
    Delete acts on every selected row; Load only ever acts on exactly
    one, so it disables itself the moment more than one row is
    selected. Both start disabled until a row is selected. Delete asks
    for confirmation (QMessageBox.question, same pattern as
    panel_archive.py's/panel_outputs.py's own destructive actions)
    before returning — still only reports the choice, see module
    docstring.
```

```python
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setFont(QFont("Segoe UI", 9))
```

```python
    def _update_button_state(self):
        count = len(self._list.selectedItems())
        self._load_btn.setEnabled(count == 1)
        self._delete_btn.setEnabled(count >= 1)

    def _selected_path(self) -> str | None:
        items = self._list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _selected_paths(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self._list.selectedItems()]

    def _on_load(self):
        path = self._selected_path()
        if path is None:
            return
        self._result = ("load", path)
        self.accept()

    def _on_delete(self):
        paths = self._selected_paths()
        if not paths:
            return
        if len(paths) == 1:
            prompt = "Delete this saved chat? This cannot be undone."
        else:
            prompt = f"Delete {len(paths)} saved chats? This cannot be undone."
        answer = QMessageBox.question(
            self, "Delete Chat", prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._result = ("delete", paths)
        self.accept()

    def get_result(self):
        """Returns (action, data) or None if the dialog was closed
        without choosing either (Close button, Esc, or a declined
        delete confirmation followed by Close).
        action == "load"   -> data is a single path string
        action == "delete" -> data is a list of path strings (always
                               a list, even for a single selection)"""
        return self._result
```

## FILE: src/app/panel_chat.py

### OLD

```python
        result = dlg.get_result()
        if result is None:
            return
        action, path = result
        if action == "delete":
            store.delete_session(path)
        elif action == "load":
            self._chat_on_load_session(store, path)
```

### NEW

```python
        result = dlg.get_result()
        if result is None:
            return
        action, data = result
        if action == "delete":
            for path in data:
                store.delete_session(path)
        elif action == "load":
            self._chat_on_load_session(store, data)
```

## FILE: src/tests/test_qt_app.py

- `test_on_delete_confirmed_sets_result` — Assertion auf `("delete", ["…"])`
  statt `("delete", "…")` umgestellt.
- Neuer Test `test_multi_select_dims_load_keeps_delete_enabled` — zwei Items
  selektiert, prüft `_load_btn.isEnabled() == False` /
  `_delete_btn.isEnabled() == True`.
- Neuer Test `test_on_delete_confirmed_multi_select_returns_all_paths` — zwei
  Items selektiert, confirmter Delete, `get_result()` enthält beide Pfade.
- `test_open_history_delete_calls_store_delete` — `fake_dialog.get_result`
  liefert jetzt `("delete", ["/base/chats/x.json"])` (Liste statt String).
- Neuer Test `test_open_history_delete_multi_select_calls_store_delete_for_each`
  — zwei Pfade im Fake-Result, prüft `delete_session()` wird für beide
  einzeln aufgerufen (`call_count == 2`).

## Verifikation

Pflichtabgleich vor dem Edit: repo-weiter Grep nach `ChatHistoryDialog`,
`get_result`, `_chat_on_open_history`, `delete_session` über `src/` (siehe
PROTOKOLL-Eintrag für die volle Fundliste). Einziger Produktivcode-Aufrufer
war `panel_chat.py:_chat_on_open_history()`; `clients/chat_session_store.py`s
`delete_session()` nimmt weiterhin genau einen Pfad — Multi-Delete wird per
Schleife im Aufrufer gelöst, kein Store-Änderung nötig.

Echter Testlauf (kein Mock der Dialog-Logik selbst, nur `QMessageBox.question`
gemockt wie schon zuvor in den bestehenden Delete-Tests), reale Qt-Widgets:

```
pytest tests/test_qt_app.py -k "ChatHistoryDialog or open_history" -v
14 passed, 152 deselected in 0.63s
```

Alle 14 Tests grün — 10 `TestChatHistoryDialog` (8 bestehend + 2 neu) und
4 `TestPanelChat`-Open-History-Tests (3 bestehend + 1 neu).

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- Volle Testsuite in dieser Runde nicht zusätzlich gelaufen — gezielter Lauf
  wie bei Baustein 1 als ausreichend bewertet.
- Der Bestätigungsdialog (`QMessageBox.question`) zeigt bei Mehrfachauswahl
  nur die Anzahl ("Delete N saved chats?"), keine Liste der einzelnen
  Chat-Titel/Zeitstempel — bewusst einfach gehalten, kein Scope-Punkt der
  Roadmap-Vorgabe.
- Die übrigen drei v1.7.2.2-Punkte (You/Assistant-Kontrast, Ollama-Dropdown-
  Sortierung + README-Tabelle, `dash_encryptor.py`-Theme-Fix) sind nicht Teil
  dieser Datei.
