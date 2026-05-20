#!/usr/bin/env python3
"""
app/panel_connection.py
Garmin Local Archive — Connection Panel Mixin

PanelConnectionMixin — tkinter UI for connection test, status indicators,
token/enc-key/MFA prompts, and token reset.

Rules:
  - No __init__ — all state lives on the GarminAppBase instance (self)
  - All widget references stored as self._xyz
  - Panel-private helpers use _connection_* prefix (E-7)
"""

import threading
import tkinter as tk

import garmin_app_controller as _controller


class PanelConnectionMixin(object):

    def _build_connection_panel(self, parent):
        fc = tk.Frame(parent, bg=self.BG, pady=4)
        fc.pack(fill="x", padx=20, pady=2)
        tk.Label(fc, text="CONNECTION & ARCHIVE STATUS", font=("Segoe UI", 7, "bold"),
                 bg=self.BG, fg=self.ACCENT).pack(anchor="w")
        tk.Frame(fc, bg=self.ACCENT, height=1).pack(fill="x", pady=(2, 6))
        conn_row = tk.Frame(fc, bg=self.BG)
        conn_row.pack(fill="x", pady=2)

        self._conn_indicators = {}
        ind_frame = tk.Frame(conn_row, bg=self.BG)
        ind_frame.pack(side="left", padx=(0, 0))
        for key, label in [("token", "Token"), ("login", "Login"),
                            ("api", "API Access"), ("data", "Data")]:
            cell = tk.Frame(ind_frame, bg=self.BG)
            cell.pack(side="left", padx=(0, 14))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 10),
                           bg=self.BG, fg=self.TEXT2)
            dot.pack(side="left")
            tk.Label(cell, text=label, font=self.FONT_BODY,
                     bg=self.BG, fg=self.TEXT2).pack(side="left", padx=(3, 0))
            self._conn_indicators[key] = dot

        tk.Button(conn_row, text="🗑  Clean Archive", font=self.FONT_BTN,
                  bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                  pady=7, padx=14, cursor="hand2",
                  command=self._clean_archive).pack(side="right")
        tk.Button(conn_row, text="🔑  Reset Token", font=self.FONT_BTN,
                  bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                  pady=7, padx=14, cursor="hand2",
                  command=self._reset_token).pack(side="right", padx=(0, 4))
        self._restore_btn = tk.Button(
            conn_row, text="Restore Data", font=self.FONT_BTN,
            bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
            pady=7, padx=14, cursor="hand2", state="disabled",
            command=self._on_restore_data)
        self._restore_btn.pack(side="right", padx=(0, 4))
        self._mirror_btn = tk.Button(
            conn_row, text="🔁  Data Mirror", font=self.FONT_BTN,
            bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
            pady=7, padx=14, cursor="hand2", state="disabled",
            command=self._on_mirror)
        self._mirror_btn.pack(side="right", padx=(0, 4))

        # ── Archive Info Panel ─────────────────────────────────────────────────
        info_frame = tk.Frame(fc, bg=self.BG)
        info_frame.pack(fill="x", pady=(6, 2))
        _QCOLORS = {
            "high":   self.GREEN,
            "medium": self.YELLOW,
            "low":    self.TEXT2,
            "failed": self.ACCENT,
        }

        row1 = tk.Frame(info_frame, bg=self.BG)
        row1.pack(fill="x")
        self._info_total = tk.Label(row1, text="Days: —",
                                    font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2)
        self._info_total.pack(side="left", padx=(0, 14))

        self._info_qdots = {}
        for q, label in [("high", "high"), ("medium", "med"),
                          ("low", "low"), ("failed", "fail")]:
            cell = tk.Frame(row1, bg=self.BG)
            cell.pack(side="left", padx=(0, 10))
            dot = tk.Label(cell, text="●", font=("Segoe UI", 9),
                           bg=self.BG, fg=_QCOLORS[q])
            dot.pack(side="left")
            lbl = tk.Label(cell, text=f"{label} —",
                           font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
            lbl.pack(side="left", padx=(2, 0))
            self._info_qdots[q] = lbl

        self._info_recheck = tk.Label(row1, text="Recheck: —",
                                      font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_recheck.pack(side="left", padx=(10, 0))

        self._info_missing = tk.Label(row1, text="Missing: —",
                                      font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_missing.pack(side="left", padx=(10, 0))

        row2 = tk.Frame(info_frame, bg=self.BG)
        row2.pack(fill="x", pady=(3, 0))
        self._info_range = tk.Label(row2, text="Range: —",
                                    font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_range.pack(side="left", padx=(0, 14))
        self._info_coverage = tk.Label(row2, text="Coverage: —",
                                       font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_coverage.pack(side="left", padx=(0, 14))
        self._info_last_api = tk.Label(row2, text="Last API: —",
                                       font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_last_api.pack(side="left", padx=(0, 14))
        self._info_last_bulk = tk.Label(row2, text="Last Bulk: —",
                                        font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2)
        self._info_last_bulk.pack(side="left")

        self._integrity_warning_lbl = tk.Label(
            info_frame, text="", font=("Segoe UI", 8, "bold"),
            bg=self.BG, fg=self.YELLOW)
        self._integrity_warning_lbl.pack(anchor="w", pady=(2, 0))

    # ── Button-Accessoren (Owner: PanelConnectionMixin) ───────────────────────

    def _set_mirror_button_state(self, enabled: bool,
                                  text: str = None, color=None):
        """Accessor für _mirror_btn — einziger erlaubter Zugriffspunkt
        aus Fremd-Panels. Threading-Sicherheit liegt beim Aufrufer."""
        if self._mirror_btn is None:
            return
        cfg = {"state": "normal" if enabled else "disabled"}
        if text is not None:
            cfg["text"] = text
        if color is not None:
            cfg["fg"] = color
        self._mirror_btn.config(**cfg)

    def _set_restore_button_state(self, enabled: bool,
                                   text: str = None, color=None,
                                   command=None):
        """Accessor für _restore_btn — einziger erlaubter Zugriffspunkt
        aus Fremd-Panels. Threading-Sicherheit liegt beim Aufrufer."""
        if self._restore_btn is None:
            return
        cfg = {"state": "normal" if enabled else "disabled"}
        if text is not None:
            cfg["text"] = text
        if color is not None:
            cfg["fg"] = color
        if command is not None:
            cfg["command"] = command
        self._restore_btn.config(**cfg)

    def _run_connection_test(self, on_success=None):
        """Test Token → Login → API Access → Data. Logic in controller."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Connection test: email or password missing.")
            return

        for key in self._conn_indicators:
            self._set_indicator(key, "reset")
        self._log("\n🔌  Testing connection ...")

        def _on_success_wrapper():
            self._connection_verified = True
            if on_success:
                self.after(0, on_success)

        _controller.check_connection(s, callbacks={
            "on_log":           self._log_bg,
            "on_token":         lambda st: self.after(0, self._set_indicator, "token", st),
            "on_login":         lambda st: self.after(0, self._set_indicator, "login", st),
            "on_api":           lambda st: self.after(0, self._set_indicator, "api",   st),
            "on_data":          lambda st: self.after(0, self._set_indicator, "data",  st),
            "on_success":       lambda: self.after(0, _on_success_wrapper),
            "on_enc_key":       self._prompt_enc_key,
            "on_token_expired": self._prompt_token_expired,
            "on_mfa":           self._prompt_mfa,
        })

    def _set_indicator(self, key: str, state: str):
        dot = self._conn_indicators.get(key)
        if not dot:
            return
        colors = {"ok": self.GREEN, "fail": "#e94560", "reset": self.TEXT2}
        dot.config(fg=colors.get(state, self.TEXT2))

    def _prompt_enc_key(self, mode="setup") -> str | None:
        result   = [None]
        done_evt = threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Encryption Key")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=self.BG)
            pad = {"padx": 20, "pady": 8}
            if mode == "setup":
                tk.Label(popup, text="Set Encryption Key",
                         font=("Segoe UI", 11, "bold"), bg=self.BG, fg=self.TEXT).pack(**pad)
                tk.Label(popup,
                         text="This key protects your saved login.\nStore it somewhere safe — e.g. your password manager.",
                         font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2, justify="left").pack(**pad)
            else:
                tk.Label(popup, text="Encryption Key Required",
                         font=("Segoe UI", 11, "bold"), bg=self.BG, fg=self.TEXT).pack(**pad)
                tk.Label(popup,
                         text="Your encryption key was not found in Windows Credential Manager.\nPlease re-enter it — you will then be prompted to log in again.",
                         font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2, justify="left").pack(**pad)
            tk.Label(popup, text="Key:", font=self.FONT_BODY,
                     bg=self.BG, fg=self.TEXT2).pack(anchor="w", padx=20)
            v_key = tk.StringVar()
            tk.Entry(popup, textvariable=v_key, show="*", font=self.FONT_BODY,
                     bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                     width=36).pack(padx=20, pady=(0, 8))
            v_confirm = None
            if mode == "setup":
                tk.Label(popup, text="Confirm Key:", font=self.FONT_BODY,
                         bg=self.BG, fg=self.TEXT2).pack(anchor="w", padx=20)
                v_confirm = tk.StringVar()
                tk.Entry(popup, textvariable=v_confirm, show="*", font=self.FONT_BODY,
                         bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                         width=36).pack(padx=20, pady=(0, 8))
            err_label = tk.Label(popup, text="", font=self.FONT_BODY,
                                 bg=self.BG, fg="#e94560")
            err_label.pack(padx=20)

            def _ok():
                key = v_key.get().strip()
                if not key:
                    err_label.config(text="Key cannot be empty.")
                    return
                if mode == "setup" and v_confirm is not None:
                    if key != v_confirm.get().strip():
                        err_label.config(text="Keys do not match.")
                        return
                result[0] = key
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=self.BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="OK", font=self.FONT_BTN,
                      bg=self.ACCENT, fg=self.TEXT, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_ok).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=self.FONT_BTN,
                      bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _prompt_token_expired(self) -> bool:
        result   = [False]
        done_evt = threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Token Expired")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=self.BG)
            tk.Label(popup, text="Saved Token Expired",
                     font=("Segoe UI", 11, "bold"),
                     bg=self.BG, fg=self.TEXT).pack(padx=20, pady=(16, 8))
            tk.Label(popup,
                     text="A full SSO login is required to generate a new token.\n"
                          "This may trigger rate limiting or MFA on Garmin's side.\nProceed?",
                     font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2,
                     justify="left").pack(padx=20, pady=(0, 12))

            def _proceed():
                result[0] = True
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=self.BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="Proceed", font=self.FONT_BTN,
                      bg=self.ACCENT, fg=self.TEXT, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_proceed).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=self.FONT_BTN,
                      bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _prompt_mfa(self) -> str | None:
        result   = [None]
        done_evt = threading.Event()

        def _show():
            popup = tk.Toplevel(self)
            popup.title("Two-Factor Authentication")
            popup.resizable(False, False)
            popup.grab_set()
            popup.configure(bg=self.BG)
            pad = {"padx": 20, "pady": 8}
            tk.Label(popup, text="MFA Code Required",
                     font=("Segoe UI", 11, "bold"),
                     bg=self.BG, fg=self.TEXT).pack(**pad)
            tk.Label(popup,
                     text="Garmin requires a verification code.\nCheck your Garmin app or authenticator.",
                     font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2,
                     justify="left").pack(**pad)
            tk.Label(popup, text="Code:", font=self.FONT_BODY,
                     bg=self.BG, fg=self.TEXT2).pack(anchor="w", padx=20)
            v_code = tk.StringVar()
            tk.Entry(popup, textvariable=v_code, font=self.FONT_BODY,
                     bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                     width=20).pack(padx=20, pady=(0, 8))
            err_label = tk.Label(popup, text="", font=self.FONT_BODY,
                                 bg=self.BG, fg="#e94560")
            err_label.pack(padx=20)

            def _ok():
                code = v_code.get().strip()
                if not code:
                    err_label.config(text="Code cannot be empty.")
                    return
                result[0] = code
                popup.destroy()
                done_evt.set()

            def _cancel():
                popup.destroy()
                done_evt.set()

            btn_row = tk.Frame(popup, bg=self.BG)
            btn_row.pack(pady=12)
            tk.Button(btn_row, text="OK", font=self.FONT_BTN,
                      bg=self.ACCENT, fg=self.TEXT, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_ok).pack(side="left", padx=4)
            tk.Button(btn_row, text="Cancel", font=self.FONT_BTN,
                      bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                      pady=6, padx=18, cursor="hand2",
                      command=_cancel).pack(side="left", padx=4)
            popup.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _show)
        done_evt.wait()
        return result[0]

    def _reset_token(self):
        import garmin_security
        garmin_security.clear_token()
        self._set_indicator("token", "reset")
        self._connection_verified = False
        self._log("🔑  Token reset — next sync will require a new login.")
