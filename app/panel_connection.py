#!/usr/bin/env python3
"""
app/panel_connection.py
Garmin Local Archive — Connection Panel

PanelConnection — PyQt6 QWidget for connection test, status indicators,
token/enc-key/MFA prompts, reset token, and archive info.

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - All widget references stored as self._xyz
  - Panel-private helpers use _connection_* prefix (E-7)
  - Signals defined at class level only — never per instance
  - Workers never touch widgets — they emit signals, Main Thread reacts
"""

import threading

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QLineEdit, QMessageBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QFont

import garmin_app_controller as _controller


# ── Dialog helpers ─────────────────────────────────────────────────────────────

class EncKeyDialog(QDialog):
    """Modal dialog for encryption key entry (setup or unlock)."""

    def __init__(self, mode: str, parent: QWidget):
        super().__init__(parent)
        self._mode   = mode
        self._result = None
        self.setWindowTitle("Encryption Key")
        self.setModal(True)
        self.setFixedWidth(420)
        bg   = parent._app.BG
        bg3  = parent._app.BG3
        text = parent._app.TEXT
        t2   = parent._app.TEXT2
        acc  = parent._app.ACCENT
        self.setStyleSheet(f"background: {bg}; color: {text};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        if mode == "setup":
            title_text = "Set Encryption Key"
            body_text  = ("This key protects your saved login.\n"
                          "Store it somewhere safe — e.g. your password manager.")
        else:
            title_text = "Encryption Key Required"
            body_text  = ("Your encryption key was not found in Windows Credential Manager.\n"
                          "Please re-enter it — you will then be prompted to log in again.")

        title = QLabel(title_text)
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {text};")
        lay.addWidget(title)

        body = QLabel(body_text)
        body.setFont(QFont("Segoe UI", 9))
        body.setStyleSheet(f"color: {t2};")
        body.setWordWrap(True)
        lay.addWidget(body)

        lay.addWidget(QLabel("Key:", font=QFont("Segoe UI", 9)))
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setStyleSheet(
            f"background: {bg3}; color: {text}; border: none; padding: 4px;")
        lay.addWidget(self._key)

        self._confirm = None
        if mode == "setup":
            lay.addWidget(QLabel("Confirm Key:", font=QFont("Segoe UI", 9)))
            self._confirm = QLineEdit()
            self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self._confirm.setStyleSheet(
                f"background: {bg3}; color: {text}; border: none; padding: 4px;")
            lay.addWidget(self._confirm)

        self._err = QLabel("")
        self._err.setStyleSheet("color: #e94560;")
        self._err.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._err)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {text}; "
            f"border: none; padding: 6px 18px; }}")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    def _on_ok(self):
        key = self._key.text().strip()
        if not key:
            self._err.setText("Key cannot be empty.")
            return
        if self._mode == "setup" and self._confirm is not None:
            if key != self._confirm.text().strip():
                self._err.setText("Keys do not match.")
                return
        self._result = key
        self.accept()

    def get_result(self) -> str | None:
        return self._result


class TokenExpiredDialog(QDialog):
    """Modal dialog asking user to confirm SSO re-login after token expiry."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Token Expired")
        self.setModal(True)
        self.setFixedWidth(400)
        bg  = parent._app.BG
        bg3 = parent._app.BG3
        t   = parent._app.TEXT
        t2  = parent._app.TEXT2
        acc = parent._app.ACCENT
        self.setStyleSheet(f"background: {bg}; color: {t};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        title = QLabel("Saved Token Expired")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(title)

        body = QLabel(
            "A full SSO login is required to generate a new token.\n"
            "This may trigger rate limiting or MFA on Garmin's side.\nProceed?"
        )
        body.setFont(QFont("Segoe UI", 9))
        body.setStyleSheet(f"color: {t2};")
        body.setWordWrap(True)
        lay.addWidget(body)

        btn_row = QHBoxLayout()
        proceed = QPushButton("Proceed")
        proceed.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        proceed.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {t}; "
            f"border: none; padding: 6px 18px; }}")
        proceed.setCursor(Qt.CursorShape.PointingHandCursor)
        proceed.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(proceed)
        btn_row.addWidget(cancel)
        lay.addLayout(btn_row)


class SsoRequiredDialog(QDialog):
    """Modal dialog asking user to confirm SSO login on first setup (no token)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Login Required")
        self.setModal(True)
        self.setFixedWidth(420)
        bg  = parent._app.BG
        bg3 = parent._app.BG3
        t   = parent._app.TEXT
        t2  = parent._app.TEXT2
        acc = parent._app.ACCENT
        self.setStyleSheet(f"background: {bg}; color: {t};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        title = QLabel("Garmin SSO Login")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(title)

        body = QLabel(
            "No saved token found. A full SSO login is required.\n\n"
            "An encryption key will be generated automatically and stored "
            "in Windows Credential Manager — no manual setup needed.\n\n"
            "garminconnect will send several requests to Garmin's servers "
            "during login — do not repeat this if you are already rate-limited.\n\n"
            "Proceed?"
        )
        body.setFont(QFont("Segoe UI", 9))
        body.setStyleSheet(f"color: {t2};")
        body.setWordWrap(True)
        lay.addWidget(body)

        btn_row = QHBoxLayout()
        proceed = QPushButton("Proceed")
        proceed.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        proceed.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {t}; "
            f"border: none; padding: 6px 18px; }}")
        proceed.setCursor(Qt.CursorShape.PointingHandCursor)
        proceed.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(proceed)
        btn_row.addWidget(cancel)
        lay.addLayout(btn_row)


class MfaDialog(QDialog):
    """Modal dialog for MFA code entry."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._result = None
        self.setWindowTitle("Two-Factor Authentication")
        self.setModal(True)
        self.setFixedWidth(380)
        bg  = parent._app.BG
        bg3 = parent._app.BG3
        t   = parent._app.TEXT
        t2  = parent._app.TEXT2
        acc = parent._app.ACCENT
        self.setStyleSheet(f"background: {bg}; color: {t};")
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(20, 16, 20, 16)

        title = QLabel("MFA Code Required")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lay.addWidget(title)

        body = QLabel(
            "Garmin requires a verification code.\n"
            "Check your Garmin app or authenticator."
        )
        body.setFont(QFont("Segoe UI", 9))
        body.setStyleSheet(f"color: {t2};")
        body.setWordWrap(True)
        lay.addWidget(body)

        lay.addWidget(QLabel("Code:", font=QFont("Segoe UI", 9)))
        self._code = QLineEdit()
        self._code.setFixedWidth(160)
        self._code.setStyleSheet(
            f"background: {bg3}; color: {t}; border: none; padding: 4px;")
        lay.addWidget(self._code)

        self._err = QLabel("")
        self._err.setStyleSheet("color: #e94560;")
        self._err.setFont(QFont("Segoe UI", 9))
        lay.addWidget(self._err)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {acc}; color: {t}; "
            f"border: none; padding: 6px 18px; }}")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {bg3}; color: {t2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    def _on_ok(self):
        code = self._code.text().strip()
        if not code:
            self._err.setText("Code cannot be empty.")
            return
        self._result = code
        self.accept()

    def get_result(self) -> str | None:
        return self._result


# ── Panel ──────────────────────────────────────────────────────────────────────

class PanelConnection(QWidget):

    # Signals — class level only (D-2)
    # payload: (dialog_type, callback)
    # dialog_type: "enc_key_setup" | "enc_key_unlock" | "token_expired" | "sso_required" | "mfa"
    _prompt_requested = pyqtSignal(str, object)

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._build_ui()
        # Connect signal to slot — always dispatches on Main Thread
        self._prompt_requested.connect(self._show_prompt)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 4, 20, 4)
        lay.setSpacing(0)

        # Section header
        header = QLabel("CONNECTION & ARCHIVE STATUS")
        header.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(header)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {self._app.ACCENT};")
        line.setFixedHeight(1)
        lay.addWidget(line)
        lay.addSpacing(6)

        # Connection indicators + buttons row
        conn_row = QHBoxLayout()
        conn_row.setSpacing(0)

        self._conn_indicators = {}
        ind_widget = QWidget()
        ind_lay    = QHBoxLayout(ind_widget)
        ind_lay.setContentsMargins(0, 0, 0, 0)
        ind_lay.setSpacing(0)
        for key, label in [("token", "Token"), ("login", "Login"),
                            ("api", "API Access"), ("data", "Data")]:
            dot = QLabel("●")
            dot.setFont(QFont("Segoe UI", 10))
            dot.setStyleSheet(f"color: {self._app.TEXT2};")
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            ind_lay.addWidget(dot)
            ind_lay.addWidget(lbl)
            ind_lay.addSpacing(14)
            self._conn_indicators[key] = dot

        conn_row.addWidget(ind_widget)
        conn_row.addStretch()

        def _btn(text, color, fg):
            b = QPushButton(text)
            b.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            b.setStyleSheet(
                f"QPushButton {{ background: {color}; color: {fg}; "
                f"border: none; padding: 7px 14px; }}"
                f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
                f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
                f"background: {self._app.BG3}; }}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            return b

        self._mirror_btn = _btn("🔁  Data Mirror", self._app.BG3, self._app.TEXT2)
        self._mirror_btn.setEnabled(False)
        self._mirror_btn.clicked.connect(
            lambda: self._app._panel_archive._on_mirror())

        self._restore_btn = _btn("Restore Data", self._app.BG3, self._app.TEXT2)
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(
            lambda: self._app._panel_archive._on_restore_data())

        reset_btn = _btn("🔑  Reset Token", self._app.BG3, self._app.TEXT2)
        reset_btn.clicked.connect(self._reset_token)

        clean_btn = _btn("🗑  Clean Archive", self._app.BG3, self._app.TEXT2)
        clean_btn.clicked.connect(
            lambda: self._app._panel_archive._clean_archive())

        for b in [self._mirror_btn, self._restore_btn, reset_btn, clean_btn]:
            conn_row.addWidget(b)
            conn_row.addSpacing(4)

        lay.addLayout(conn_row)
        lay.addSpacing(6)

        # Archive info — row 1
        _QCOLORS = {
            "high":   self._app.GREEN,
            "medium": self._app.YELLOW,
            "low":    self._app.TEXT2,
            "failed": self._app.ACCENT,
        }
        row1 = QHBoxLayout()
        row1.setSpacing(0)
        self._info_total = QLabel("Days: —")
        self._info_total.setFont(QFont("Segoe UI", 9))
        self._info_total.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_total)
        row1.addSpacing(14)

        self._info_qdots = {}
        for q, label in [("high", "high"), ("medium", "med"),
                          ("low", "low"), ("failed", "fail")]:
            dot = QLabel("●")
            dot.setFont(QFont("Segoe UI", 9))
            dot.setStyleSheet(f"color: {_QCOLORS[q]};")
            lbl = QLabel(f"{label} —")
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            row1.addWidget(dot)
            row1.addSpacing(2)
            row1.addWidget(lbl)
            row1.addSpacing(10)
            self._info_qdots[q] = lbl

        self._info_recheck = QLabel("Recheck: —")
        self._info_recheck.setFont(QFont("Segoe UI", 8))
        self._info_recheck.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_recheck)
        row1.addSpacing(10)

        self._info_missing = QLabel("Missing: —")
        self._info_missing.setFont(QFont("Segoe UI", 8))
        self._info_missing.setStyleSheet(f"color: {self._app.TEXT2};")
        row1.addWidget(self._info_missing)
        row1.addStretch()
        lay.addLayout(row1)

        # Archive info — row 2
        row2 = QHBoxLayout()
        row2.setSpacing(0)
        for attr, text in [
            ("_info_range",    "Range: —"),
            ("_info_coverage", "Coverage: —"),
            ("_info_last_api", "Last API: —"),
            ("_info_last_bulk","Last Bulk: —"),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet(f"color: {self._app.TEXT2};")
            setattr(self, attr, lbl)
            row2.addWidget(lbl)
            row2.addSpacing(14)
        row2.addStretch()
        lay.addLayout(row2)

        self._integrity_warning_lbl = QLabel("")
        self._integrity_warning_lbl.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._integrity_warning_lbl.setStyleSheet(f"color: {self._app.YELLOW};")
        lay.addWidget(self._integrity_warning_lbl)

    # ── Accessors — sole authorised write-path for mirror/restore buttons ──────

    def set_mirror_button_state(self, enabled: bool,
                                text: str = None, color: str = None):
        """Called from PanelArchive — Main Thread only."""
        self._mirror_btn.setEnabled(enabled)
        if text is not None:
            self._mirror_btn.setText(text)
        fg = color if color is not None else (
            self._app.TEXT if enabled else self._app.TEXT2)
        bg = self._app.BG3
        self._mirror_btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; "
            f"border: none; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {self._app.ACCENT2}; }}"
            f"QPushButton:disabled {{ color: {self._app.TEXT2}; "
            f"background: {self._app.BG3}; }}")
        self._mirror_btn.style().unpolish(self._mirror_btn)
        self._mirror_btn.style().polish(self._mirror_btn)
        self._mirror_btn.update()

    def set_restore_button_state(self, enabled: bool,
                                 text: str = None, color: str = None,
                                 command=None):
        """Called from PanelArchive — Main Thread only."""
        self._restore_btn.setEnabled(enabled)
        if text is not None:
            self._restore_btn.setText(text)
        if command is not None:
            try:
                self._restore_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._restore_btn.clicked.connect(command)

    # ── Indicator ──────────────────────────────────────────────────────────────

    def _set_indicator(self, key: str, state: str):
        dot = self._conn_indicators.get(key)
        if not dot:
            return
        colors = {
            "ok":    self._app.GREEN,
            "fail":  "#e94560",
            "reset": self._app.TEXT2,
        }
        dot.setStyleSheet(f"color: {colors.get(state, self._app.TEXT2)};")

    # ── Connection test ────────────────────────────────────────────────────────

    def _run_connection_test(self, on_success=None):
        s = self._app._panel_settings._collect_settings()
        if not s["email"] or not s["password"]:
            self._app._log("✗ Connection test: email or password missing.")
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._app._log("\n🔌  Testing connection ...")

        def _on_success_wrapper():
            self._app._connection_verified = True
            if on_success:
                on_success()

        _controller.check_connection(s, callbacks={
            "on_log":           self._app._log_bg,
            "on_token":         lambda st: self._app._dispatch(
                                    self._set_indicator, "token", st),
            "on_login":         lambda st: self._app._dispatch(
                                    self._set_indicator, "login", st),
            "on_api":           lambda st: self._app._dispatch(
                                    self._set_indicator, "api",   st),
            "on_data":          lambda st: self._app._dispatch(
                                    self._set_indicator, "data",  st),
            "on_success":       lambda: self._app._dispatch(_on_success_wrapper),
            "on_enc_key":       self._prompt_enc_key,
            "on_token_expired": self._prompt_token_expired,
            "on_sso_required":  self._prompt_sso_required,
            "on_mfa":           self._prompt_mfa,
        })

    # ── Modal dialogs — Signal/Slot pattern (D-2) ──────────────────────────────

    @pyqtSlot(str, object)
    def _show_prompt(self, dialog_type: str, callback):
        if self._app._dialog_open:
            return
        self._app._dialog_open = True

        if dialog_type in ("enc_key_setup", "enc_key_unlock"):
            mode   = "setup" if dialog_type == "enc_key_setup" else "unlock"
            dialog = EncKeyDialog(mode, self)
            dialog.finished.connect(
                lambda: setattr(self._app, "_dialog_open", False))
            result = dialog.exec()
            callback(dialog.get_result()
                     if result == QDialog.DialogCode.Accepted else None)

        elif dialog_type == "token_expired":
            dialog = TokenExpiredDialog(self)
            dialog.finished.connect(
                lambda: setattr(self._app, "_dialog_open", False))
            result = dialog.exec()
            callback(result == QDialog.DialogCode.Accepted)

        elif dialog_type == "sso_required":
            dialog = SsoRequiredDialog(self)
            dialog.finished.connect(
                lambda: setattr(self._app, "_dialog_open", False))
            result = dialog.exec()
            callback(result == QDialog.DialogCode.Accepted)

        elif dialog_type == "mfa":
            dialog = MfaDialog(self)
            dialog.finished.connect(
                lambda: setattr(self._app, "_dialog_open", False))
            result = dialog.exec()
            callback(dialog.get_result()
                     if result == QDialog.DialogCode.Accepted else None)

        else:
            self._app._dialog_open = False

    def _prompt_enc_key(self, mode="setup") -> str | None:
        """Called from Worker thread — emits signal, blocks until dialog closes."""
        response_event = threading.Event()
        result         = [None]

        def _cb(value):
            result[0] = value
            response_event.set()

        dialog_type = "enc_key_setup" if mode == "setup" else "enc_key_unlock"
        self._prompt_requested.emit(dialog_type, _cb)
        response_event.wait()
        return result[0]

    def _prompt_token_expired(self) -> bool:
        response_event = threading.Event()
        result         = [False]

        def _cb(value):
            result[0] = value
            response_event.set()

        self._prompt_requested.emit("token_expired", _cb)
        response_event.wait()
        return result[0]

    def _prompt_sso_required(self) -> bool:
        """Called from Worker thread — emits signal, blocks until dialog closes."""
        response_event = threading.Event()
        result         = [False]

        def _cb(value):
            result[0] = value
            response_event.set()

        self._prompt_requested.emit("sso_required", _cb)
        response_event.wait()
        return result[0]

    def _prompt_mfa(self) -> str | None:
        response_event = threading.Event()
        result         = [None]

        def _cb(value):
            result[0] = value
            response_event.set()

        self._prompt_requested.emit("mfa", _cb)
        response_event.wait()
        return result[0]

    # ── Reset token ────────────────────────────────────────────────────────────

    def _reset_token(self):
        import garmin_security
        garmin_security.clear_token()
        self._set_indicator("token", "reset")
        self._app._connection_verified = False
        self._app._log("🔑  Token reset — next sync will require a new login.")
