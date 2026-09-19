# v1.7.2.2 — Baustein 5: dash_encryptor.py Theme-Fix

**Kurztitel:** dash-encryptor-theme

## Kontext

Fünfter und letzter Hauptpunkt aus `ROADMAP.md`s v1.7.2.2-Liste: der HTML-
Lock-Screen, den `layouts/dash_encryptor.py` für den Encrypted-Dashboards-
Export generiert, hatte noch hartkodierte Hex-Farben statt sie aus
`theme.py` zu ziehen — der Dashboard-Inhalt hinter dem Lock-Screen macht
das schon richtig. In der Rückfrage klärte Timo, ob die vorgeschlagene
Lösung ein "indirekter Import" sei — Antwort: nein, reine Parameter-
Übergabe (Dependency Injection), kein Import, auch kein indirekter — die
Datei bleibt vollständig unabhängig von `theme.py`s Existenz/Struktur.

## Fund

`layouts/dash_encryptor.py` ist laut eigenem Docstring und
`docs/REFERENCE_INVARIANTS.md:26` ein **Leaf-Node — keine Projekt-Modul-
Imports, nur stdlib + cryptography**. Ein `import theme` hier würde diese
Invariante brechen. Die hartkodierten Hex-Werte (`#12101f`, `#1a1729`,
`#a259f7`, `#a0a0b0`, `#6e3fcf`, `#eaeaea`, `#e94560`) entsprachen 1:1
`THEME_2` ("Violet Legacy") aus `theme.py` — der Lock-Screen war auf den
alten Default-Theme eingefroren, von vor dem Mehr-Themen-System.

Einziger Aufrufer: `app/popups/_dashboard_build.py:176-203` — lädt
`dash_encryptor.py` dynamisch per `importlib.util.spec_from_file_location`
(bewusst kein normaler Import) und ruft `encrypt_html()` innerhalb von
`panel._app`-Kontext auf. `garmin_app_base.py:94-103` spiegelt die
Theme-Farben bereits als Klassenattribute (`self._app.BG/BG2/ACCENT/
ACCENT2/TEXT/TEXT2/RED`, direkt aus `theme.py`) — der Aufrufer hat die
Farben also schon zur Hand, ohne dass `dash_encryptor.py` selbst etwas
importieren müsste.

**Design:** `encrypt_html()` bekommt optionale, keyword-only
Theme-Parameter mit den bisherigen Hex-Werten als Default — reine
String-Übergabe, kein Kopplungspunkt im Code. `_build_wrapper()` reicht
sie in die CSS-Stellen durch. `_dashboard_build.py` übergibt
`panel._app.BG/BG2/ACCENT/ACCENT2/TEXT/TEXT2/RED`. Der bestehende
zweiargumentige Testaufruf bleibt unverändert gültig (nutzt die Defaults)
— byte-identischer Output wie vor dem Fix.

## FILE: src/layouts/dash_encryptor.py

### OLD

```python
Public interface:
    encrypt_html(html_content: str, password: str) -> str
"""

import base64
import json
import os

_PBKDF2_ITERATIONS = 100_000
_SALT_LEN          = 16   # bytes
_IV_LEN            = 12   # bytes — AES-GCM standard nonce


def encrypt_html(html_content: str, password: str) -> str:
    """
    Verschlüsselt einen HTML-String mit AES-256-GCM (PBKDF2-HMAC-SHA256 Key Derivation).

    Parameters
    ----------
    html_content : str  — fertiger HTML-String (UTF-8)
    password     : str  — Passwort das der Nutzer eingegeben hat

    Returns
    -------
    str — self-decrypting HTML (enthält Ciphertext + Decrypt-Dialog + Web Crypto JS)

    Raises
    ------
    ValueError   — wenn html_content oder password leer sind
    RuntimeError — wenn Verschlüsselung fehlschlägt
    """
```

```python
    return _build_wrapper(meta)


# ══════════════════════════════════════════════════════════════════════════════
#  Wrapper-HTML — Decrypt-Dialog + Web Crypto API
# ══════════════════════════════════════════════════════════════════════════════

def _build_wrapper(meta_json: str) -> str:
    """
    Baut das self-decrypting HTML-Dokument.
    meta_json enthält: iterations, salt (b64), iv (b64), cipher (b64).
    Alles inline — kein externes Asset, funktioniert mit file:// Protokoll.
    """
    return f"""<!DOCTYPE html>
...
  html, body {{ height: 100%; background: #12101f; color: #eaeaea;
               font-family: 'Segoe UI', sans-serif; }}
  ...
  #gla-lock-box {{
    background: #1a1729; border: 1px solid #a259f7;
    ...
  }}
  #gla-lock-box h1 {{ font-size: 15px; color: #a259f7; ... }}
  #gla-lock-box p  {{ font-size: 12px; color: #a0a0b0; ... }}
  #gla-pin {{
    ...
    background: #12101f; color: #eaeaea; border: 1px solid #6e3fcf;
    ...
  }}
  #gla-pin:focus {{ outline: none; border-color: #a259f7; }}
  #gla-unlock-btn {{
    ...
    background: #a259f7; color: #fff; ...
  }}
  #gla-unlock-btn:hover {{ background: #6e3fcf; }}
  #gla-error {{
    display: none; margin-top: 12px; font-size: 12px; color: #e94560;
  }}
```

### NEW

```python
Public interface:
    encrypt_html(html_content: str, password: str, *, bg=..., bg2=...,
                 accent=..., accent2=..., text=..., text2=..., red=...) -> str

Theme colors are plain keyword-only strings, not a theme.py import — this
file stays independent of theme.py's structure; the caller (which already
has app/theme context) decides what to pass. Defaults reproduce the
original fixed Violet-Legacy palette this file used before v1.7.2.2, so a
call without theme kwargs (e.g. the test suite) is byte-identical to before.
"""

import base64
import json
import os

_PBKDF2_ITERATIONS = 100_000
_SALT_LEN          = 16   # bytes
_IV_LEN            = 12   # bytes — AES-GCM standard nonce


def encrypt_html(html_content: str, password: str, *,
                  bg: str = "#12101f", bg2: str = "#1a1729",
                  accent: str = "#a259f7", accent2: str = "#6e3fcf",
                  text: str = "#eaeaea", text2: str = "#a0a0b0",
                  red: str = "#e94560") -> str:
    """
    Verschlüsselt einen HTML-String mit AES-256-GCM (PBKDF2-HMAC-SHA256 Key Derivation).

    Parameters
    ----------
    html_content : str  — fertiger HTML-String (UTF-8)
    password     : str  — Passwort das der Nutzer eingegeben hat
    bg, bg2, accent, accent2, text, text2, red : str — Hex-Farben für den
        Lock-Screen (keyword-only). Default reproduziert die alte fest
        einprogrammierte Violet-Legacy-Palette — der Aufrufer übergibt
        stattdessen typischerweise die aktiven self._app.*-Theme-Farben.

    Returns
    -------
    str — self-decrypting HTML (enthält Ciphertext + Decrypt-Dialog + Web Crypto JS)

    Raises
    ------
    ValueError   — wenn html_content oder password leer sind
    RuntimeError — wenn Verschlüsselung fehlschlägt
    """
```

```python
    return _build_wrapper(meta, bg, bg2, accent, accent2, text, text2, red)


# ══════════════════════════════════════════════════════════════════════════════
#  Wrapper-HTML — Decrypt-Dialog + Web Crypto API
# ══════════════════════════════════════════════════════════════════════════════

def _build_wrapper(meta_json: str, bg: str, bg2: str, accent: str,
                    accent2: str, text: str, text2: str, red: str) -> str:
    """
    Baut das self-decrypting HTML-Dokument.
    meta_json enthält: iterations, salt (b64), iv (b64), cipher (b64).
    Alles inline — kein externes Asset, funktioniert mit file:// Protokoll.
    """
    return f"""<!DOCTYPE html>
...
  html, body {{ height: 100%; background: {bg}; color: {text};
               font-family: 'Segoe UI', sans-serif; }}
  ...
  #gla-lock-box {{
    background: {bg2}; border: 1px solid {accent};
    ...
  }}
  #gla-lock-box h1 {{ font-size: 15px; color: {accent}; ... }}
  #gla-lock-box p  {{ font-size: 12px; color: {text2}; ... }}
  #gla-pin {{
    ...
    background: {bg}; color: {text}; border: 1px solid {accent2};
    ...
  }}
  #gla-pin:focus {{ outline: none; border-color: {accent}; }}
  #gla-unlock-btn {{
    ...
    background: {accent}; color: #fff; ...
  }}
  #gla-unlock-btn:hover {{ background: {accent2}; }}
  #gla-error {{
    display: none; margin-top: 12px; font-size: 12px; color: {red};
  }}
```

(`#fff` for the Unlock button's text stays a literal, unthemed white —
same convention as the app's own primary buttons elsewhere, e.g.
`panel_chat.py`'s `QPushButton {{ background: {ACCENT}; color: white; }}`.)

## FILE: src/app/popups/_dashboard_build.py

### OLD

```python
                    html_content = html_path.read_text(encoding="utf-8")
                    encrypted    = dash_encryptor.encrypt_html(
                        html_content, password)
```

### NEW

```python
                    html_content = html_path.read_text(encoding="utf-8")
                    encrypted    = dash_encryptor.encrypt_html(
                        html_content, password,
                        bg=panel._app.BG, bg2=panel._app.BG2,
                        accent=panel._app.ACCENT, accent2=panel._app.ACCENT2,
                        text=panel._app.TEXT, text2=panel._app.TEXT2,
                        red=panel._app.RED)
```

## FILE: src/tests/test_dashboard.py

Drei neue Checks nach den bestehenden `encrypt_html()`-Checks angehängt:
Custom `bg`/`accent` erscheinen im Output bei explizitem Aufruf; der
zweiargumentige Default-Aufruf (bereits vorhandener Testcode,
unverändert) verwendet weiterhin die alte Palette.

## FILE: src/docs/REFERENCE_DASHBOARD.md

Funktions-Zeile für `encrypt_html()` auf die neue Signatur (Keyword-Args
+ Leaf-Node-Hinweis) aktualisiert. Die dort bereits vorher veraltete
"Called by: `panel_outputs._run_encrypted_dashboards()`"-Angabe (stimmt
seit dem v1.7.2.1-Split nicht mehr) bewusst unangetastet gelassen —
separater, vorbestehender Doku-Drift, nicht Teil dieses Fixes.

## Verifikation

Pflichtabgleich vor dem Edit: repo-weiter Grep nach `encrypt_html`/
`dash_encryptor` über `src/`. Einziger Aufrufer bestätigt
(`_dashboard_build.py`), Leaf-Node-Invariante in `REFERENCE_INVARIANTS.md`
und Modul-Docstring gegengelesen, `garmin_app_base.py` als Quelle der
`self._app.*`-Theme-Attribute verifiziert.

Echter Testlauf (kein Mock), volle `test_dashboard.py`-Suite (eigenes
Check-Framework, 20 Abschnitte):

```
PYTHONIOENCODING=utf-8 python tests/test_dashboard.py
472 checks — 472 passed, 0 failed
```

Abschnitt 17 (`dash_encryptor`) im Detail: alle 13 Checks grün, inkl. der
3 neuen (`custom bg color appears in output`, `custom accent color
appears in output`, `default call still uses old palette`).

(Nebenbefund, nicht Teil dieses Fixes: `python tests/test_dashboard.py`
ohne `PYTHONIOENCODING=utf-8` bricht auf dieser Windows-Konsole mit
`UnicodeEncodeError` in `tests/support.py`s `section()` ab — vorbestehendes
cp1252-Konsolen-Encoding-Problem, unabhängig von dieser Änderung,
reproduzierbar auch auf dem unveränderten HEAD.)

## Bekannte Einschränkungen, weiterhin nicht Teil dieser Lieferung

- `REFERENCE_DASHBOARD.md`s veraltete "Called by"-Angabe bewusst nicht
  korrigiert (siehe oben) — eigener, unabhängiger Doku-Drift-Fund.
- Der vorbestehende `UnicodeEncodeError` in `tests/support.py` bei
  Konsolen mit cp1252-Codepage (ohne `PYTHONIOENCODING=utf-8`) nicht
  behoben — nicht durch diesen Fix verursacht, separates Thema.
- Damit sind alle fünf Hauptpunkte aus der v1.7.2.2-Roadmap-Liste
  bearbeitet. Punkt 6 (`garmin_extended_anaysis.py` in T3, "Low priority,
  only if it fits well") war laut Absprache mit Timo von Beginn an separat
  zu betrachten und ist nicht Teil dieser Datei.
