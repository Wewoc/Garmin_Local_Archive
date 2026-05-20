#!/usr/bin/env python3
"""
app/panel_outputs.py
Garmin Local Archive — Outputs Panel Mixin

PanelOutputsMixin — data collection buttons (sync, import, context sync),
dashboard popup, output buttons (folder, error log, task scheduler XML),
and all related callbacks.

Rules:
  - No __init__ — all state lives on the GarminAppBase instance (self)
  - All widget references stored as self._xyz
  - Panel-private helpers use _outputs_* prefix (E-7)
"""

import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import garmin_app_settings as _settings


class PanelOutputsMixin(object):

    def _build_outputs_panel(self, parent):
        # ── Data Collection ────────────────────────────────────────────────────
        f = tk.Frame(parent, bg=self.BG, pady=4)
        f.pack(fill="x", padx=20, pady=2)
        tk.Label(f, text="DATA COLLECTION", font=("Segoe UI", 7, "bold"),
                 bg=self.BG, fg=self.ACCENT).pack(anchor="w")
        tk.Frame(f, bg=self.ACCENT, height=1).pack(fill="x", pady=(2, 6))
        row = tk.Frame(f, bg=self.BG)
        row.pack(fill="x", pady=2)
        sync_btn = tk.Button(row, text="▶  Sync Garmin", font=self.FONT_BTN,
                             bg=self.ACCENT, fg=self.TEXT, relief="flat", bd=0,
                             pady=7, padx=14, anchor="w", cursor="hand2",
                             command=self._run_collector)
        sync_btn.pack(side="left", fill="x", expand=True)
        self._stop_btn = tk.Button(row, text="⏹  Stop", font=self.FONT_BTN,
                                   bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                                   pady=7, padx=14, cursor="hand2",
                                   state="disabled",
                                   command=self._stop_collector)
        self._stop_btn.pack(side="left", padx=(4, 0))
        tk.Label(row, text="Fetch missing days from Garmin Connect",
                 font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2).pack(side="left", padx=10)

        imp_row = tk.Frame(f, bg=self.BG)
        imp_row.pack(fill="x", pady=2)
        tk.Button(imp_row, text="📥  Import Bulk Export", font=self.FONT_BTN,
                  bg=self.BG3, fg=self.TEXT, relief="flat", bd=0,
                  pady=7, padx=14, anchor="w", cursor="hand2",
                  command=self._run_import).pack(side="left", fill="x", expand=True)
        tk.Label(imp_row,
                 text="Import Garmin GDPR export ZIP or folder (recommended for history)",
                 font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2).pack(side="left", padx=10)

        _EXPORT_URL = "https://www.garmin.com/en-US/account/datamanagement/exportdata/"
        imp_link_row = tk.Frame(f, bg=self.BG)
        imp_link_row.pack(fill="x", pady=(0, 2))
        imp_link = tk.Label(imp_link_row, text="→ Request export at garmin.com",
                            font=("Segoe UI", 8), bg=self.BG, fg=self.ACCENT, cursor="hand2")
        imp_link.pack(side="left", padx=14)
        imp_link.bind("<Button-1>", lambda e: _settings._open_url(_EXPORT_URL))

        _exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) \
                   else Path(__file__).parent
        _readme_candidates = [
            _exe_dir / "info" / "README_APP.md",
            Path(__file__).parent / "docs" / "README_APP.md",
        ]
        _readme = next((p for p in _readme_candidates if p.exists()), None)
        readme_link = tk.Label(imp_link_row, text="→ Open README",
                               font=("Segoe UI", 8), bg=self.BG,
                               fg=self.ACCENT, cursor="hand2")
        readme_link.pack(side="left", padx=14)
        readme_link.bind("<Button-1>",
                         lambda e: os.startfile(_readme) if _readme else None)

        ctx_row = tk.Frame(f, bg=self.BG)
        ctx_row.pack(fill="x", pady=2)
        self._ctx_btn = tk.Button(ctx_row, text="🌍  Sync Context", font=self.FONT_BTN,
                                  bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                                  pady=7, padx=14, anchor="w", cursor="hand2",
                                  command=self._run_context_sync)
        self._ctx_btn.pack(side="left", fill="x", expand=True)
        self._ctx_stop_btn = tk.Button(ctx_row, text="⏹  Stop", font=self.FONT_BTN,
                                       bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                                       pady=7, padx=14, cursor="hand2",
                                       state="disabled",
                                       command=self._stop_context_sync)
        self._ctx_stop_btn.pack(side="left", padx=(4, 0))
        self._ctx_csv_btn = tk.Button(ctx_row, text="📄  CSV", font=self.FONT_BTN,
                                      bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                                      pady=7, padx=14, cursor="hand2",
                                      command=self._open_local_config)
        self._ctx_csv_btn.pack(side="left", padx=(4, 0))
        tk.Label(ctx_row, text="Fetch weather & pollen from Open-Meteo",
                 font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT2).pack(side="left", padx=10)

        # Export + Output sections use Base helper _action_section
        self._action_section(parent, "Export", [
            ("📊  Create Reports", self.BG3, self._open_dashboard_popup,
             "Select dashboards and create as HTML, Excel or JSON"),
        ])
        self._action_section(parent, "Output", [
            ("📁  Open Data Folder",        self.BG3, self._open_data_folder,
             "Open garmin_data/ in Explorer"),
            ("📋  Copy Last Error Log",     self.BG3, self._copy_last_error_log,
             "Copy most recent error log to clipboard"),
            ("🗓  Create Task Scheduler XML", self.BG3, self._create_task_scheduler_xml,
             "Generate daily_update_task.xml for Windows Task Scheduler"),
        ])

    # ── Sync actions ───────────────────────────────────────────────────────────

    def _check_raw_backfill_popup(self, s: dict) -> None:
        try:
            import importlib
            os.environ["GARMIN_OUTPUT_DIR"] = s.get("base_dir", "")
            import garmin_backup as _backup
            import garmin_config as _cfg
            importlib.reload(_cfg)
            importlib.reload(_backup)
            count = _backup.check_raw_backfill_needed()
        except Exception:
            return

        if count == 0:
            self.settings["backup_raw_backfill_asked"] = True
            self._safe_save(self.settings)
            return

        confirmed = messagebox.askyesno(
            "Raw Backup — New Feature",
            f"Garmin Local Archive v1.5.1 introduced automatic raw file backups.\n\n"
            f"{count} existing raw file(s) have no backup copy yet.\n\n"
            f"Create backups now? This runs in the background and does not\n"
            f"affect the sync. Completed months are stored as ZIP archives\n"
            f"in garmin_data/backup/raw/.\n\n"
            f"You can also skip this — new files will be backed up automatically\n"
            f"after every sync from now on.",
            icon="info",
        )
        if not confirmed:
            return

        def _do_backfill():
            try:
                result = _backup.backfill_raw()
                self._log_bg(
                    f"✓ Raw backup complete: {result['copied']} files backed up"
                    + (f", {result['errors']} errors" if result["errors"] else "")
                )
            except Exception as e:
                self._log_bg(f"✗ Raw backup failed: {e}")

        self.settings["backup_raw_backfill_asked"] = True
        self._safe_save(self.settings)
        threading.Thread(target=_do_backfill, daemon=True).start()
        self._log("🗄  Raw backup running in background …")

    def _run_collector(self):
        """Run connection test first (once per session), then start sync."""
        s = self._collect_settings()
        if not s["email"] or not s["password"]:
            self._log("✗ Email or password missing.")
            return

        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for manual sync.")
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        if not self.settings.get("backup_raw_backfill_asked", False):
            self._check_raw_backfill_popup(s)

        refresh_failed = self._check_failed_days_popup(
            base_dir  = s["base_dir"],
            sync_mode = s["sync_mode"],
            sync_days = s["sync_days"],
            sync_from = s.get("sync_from", ""),
            sync_to   = s.get("sync_to", ""),
        )
        run_migration = self._check_schema_migration(base_dir=s["base_dir"])
        env_extra     = {"GARMIN_SCHEMA_MIGRATE": "1"} if run_migration else {}

        if self._connection_verified:
            self._run("garmin_collector.py", enable_stop=True,
                      refresh_failed=refresh_failed,
                      env_overrides=env_extra,
                      on_done=lambda: (
                          self._timer_resume_after_sync(timer_was_active),
                          self._refresh_archive_info(),
                      ))
            return

        self._run_connection_test(
            on_success=lambda: self._run(
                "garmin_collector.py", enable_stop=True,
                refresh_failed=refresh_failed,
                env_overrides=env_extra,
                on_done=lambda: (
                    self._timer_resume_after_sync(timer_was_active),
                    self._refresh_archive_info(),
                )))

    def _run_import(self):
        """Open file dialog and run bulk import."""
        choice = messagebox.askquestion(
            "Import Bulk Export",
            "Select ZIP file?\n\nYes = ZIP file\nNo = unpacked folder",
            icon="question",
        )
        if choice == "yes":
            path = filedialog.askopenfilename(
                title="Select Garmin Export ZIP",
                filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            )
        else:
            path = filedialog.askdirectory(
                title="Select unpacked Garmin Export folder")
        if not path:
            return

        timer_was_active = self._timer_active
        if self._timer_active:
            self._log("⏱  Background timer paused for import.")
            self._timer_stop.set()
            self._timer_active = False
            self.after(0, self._timer_update_btn)

        self._log(f"   Source: {path}")
        self._run(
            "garmin_collector.py",
            enable_stop=True,
            log_prefix="garmin_bulk",
            env_overrides={"GARMIN_IMPORT_PATH": path},
            on_done=lambda: (
                self._timer_resume_after_sync(timer_was_active),
                self._refresh_archive_info(),
            ),
        )

    # ── Context sync ───────────────────────────────────────────────────────────

    def _run_context_sync(self):
        """Run context collect (weather + pollen) in background thread."""
        s = self._collect_settings()
        if float(s.get("context_latitude", "0.0")) == 0.0 and \
           float(s.get("context_longitude", "0.0")) == 0.0:
            messagebox.showwarning(
                "Location not configured",
                "Please set a location in Settings before running Context Sync.\n"
                "Use the Settings panel to enter coordinates."
            )
            return
        self._ctx_btn.config(state="disabled")
        self._ctx_stop_btn.config(state="normal")
        self._context_stop_event = threading.Event()
        self._ctx_running        = True

        def run():
            try:
                if not getattr(sys, "frozen", False):
                    _root = Path(__file__).parent.parent
                elif hasattr(sys, "_MEIPASS") and \
                        (Path(sys._MEIPASS) / "scripts").exists():
                    _root = Path(sys._MEIPASS) / "scripts"
                else:
                    _root = Path(sys.executable).parent / "scripts"
                if str(_root) not in sys.path:
                    sys.path.insert(0, str(_root))
                from context import context_collector
                result  = context_collector.run(
                    settings=s,
                    stop_event=self._context_stop_event
                )
                plugins = result.get("plugins", {})
                lines   = ["Context sync complete"]
                for name, stats in plugins.items():
                    lines.append(
                        f"{name.capitalize():<10}{stats.get('written', 0)} written")
                msg = "\n".join(lines)
                if result.get("error"):
                    msg = f"Error: {result['error']}"
                self.after(0, lambda: self._log(msg))
            except Exception as exc:
                self.after(0, lambda: self._log(f"Context sync error: {exc}"))
            finally:
                self.after(0, self._on_context_sync_done)

        threading.Thread(target=run, daemon=True).start()

    def _stop_context_sync(self):
        self._context_stop_event.set()

    def _on_context_sync_done(self):
        self._ctx_btn.config(state="normal")
        self._ctx_stop_btn.config(state="disabled")
        self._ctx_running = False

    # ── Dashboard popup ────────────────────────────────────────────────────────

    def _open_dashboard_popup(self):
        """Scan specialists, show selection popup, build selected dashboards."""
        import importlib.util as _ilu

        if not getattr(sys, "frozen", False):
            root = Path(__file__).parent.parent
        elif hasattr(sys, "_MEIPASS") and \
                (Path(sys._MEIPASS) / "scripts").exists():
            root = Path(sys._MEIPASS) / "scripts"
        else:
            root = Path(sys.executable).parent / "scripts"
        for p in (root / "dashboards", root / "layouts", root / "maps"):
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)

        try:
            runner_path = root / "dashboards" / "dash_runner.py"
            spec = _ilu.spec_from_file_location("dash_runner", runner_path)
            if spec is None:
                raise FileNotFoundError(
                    f"dash_runner.py nicht gefunden: {runner_path}")
            dash_runner = _ilu.module_from_spec(spec)
            spec.loader.exec_module(dash_runner)
        except Exception as exc:
            self._log(f"✗ Dashboard runner konnte nicht geladen werden: {exc}")
            return

        try:
            specialists = dash_runner.scan()
        except Exception as exc:
            self._log(f"✗ scan() fehlgeschlagen: {exc}")
            return
        if not specialists:
            messagebox.showinfo("Create Reports",
                                "No dashboards found in dashboards/")
            return

        popup = tk.Toplevel(self)
        popup.title("Create Reports")
        popup.configure(bg=self.BG)
        popup.resizable(False, False)
        popup.grab_set()

        tk.Label(popup, text="CREATE REPORTS", font=("Segoe UI", 9, "bold"),
                 bg=self.BG, fg=self.ACCENT).grid(
                 row=0, column=0, columnspan=10, sticky="w", padx=16, pady=(14, 4))
        tk.Frame(popup, bg=self.ACCENT, height=1).grid(
                 row=1, column=0, columnspan=10, sticky="ew", padx=16, pady=(0, 8))

        all_formats = []
        for sp in specialists:
            for fmt in sp["formats"]:
                if fmt not in all_formats:
                    all_formats.append(fmt)

        tk.Label(popup, text="Dashboard", font=("Segoe UI", 8, "bold"),
                 bg=self.BG, fg=self.TEXT, width=28, anchor="w").grid(
                 row=2, column=0, padx=(16, 4), pady=2)
        for col_idx, fmt in enumerate(all_formats, start=1):
            tk.Label(popup, text=dash_runner.display_label(fmt).upper(),
                     font=("Segoe UI", 8, "bold"), bg=self.BG, fg=self.TEXT,
                     width=7, anchor="center").grid(
                     row=2, column=col_idx, padx=4, pady=2)

        check_vars = {}
        for row_idx, spec in enumerate(specialists, start=3):
            tk.Label(popup,
                     text=f"{spec['name']} — {spec['description'][:45]}",
                     font=("Segoe UI", 8), bg=self.BG, fg=self.TEXT,
                     width=46, anchor="w").grid(
                     row=row_idx, column=0, padx=(16, 4), pady=3)
            for col_idx, fmt in enumerate(all_formats, start=1):
                if fmt in spec["formats"]:
                    var = tk.BooleanVar(value=False)
                    check_vars[(row_idx - 3, fmt)] = var
                    tk.Checkbutton(popup, variable=var, bg=self.BG,
                                   activebackground=self.BG,
                                   selectcolor="white").grid(
                                   row=row_idx, column=col_idx, padx=4)
                else:
                    tk.Label(popup, text="—", font=("Segoe UI", 8),
                             bg=self.BG, fg="#555555").grid(
                             row=row_idx, column=col_idx, padx=4)

        last_row = 3 + len(specialists)
        tk.Frame(popup, bg=self.ACCENT, height=1).grid(
                 row=last_row, column=0, columnspan=10,
                 sticky="ew", padx=16, pady=(8, 4))

        def _build():
            selections = []
            for (spec_idx, fmt), var in check_vars.items():
                if var.get():
                    selections.append((specialists[spec_idx]["module"], fmt))
            if not selections:
                messagebox.showinfo("Create Reports",
                                    "Please select at least one format.")
                return
            popup.destroy()
            self._run_dashboards(dash_runner, selections)

        btn_frame = tk.Frame(popup, bg=self.BG)
        btn_frame.grid(row=last_row + 1, column=0, columnspan=10,
                       pady=(4, 14), padx=16, sticky="ew")

        _all_selected = [False]

        def _toggle_all():
            _all_selected[0] = not _all_selected[0]
            for var in check_vars.values():
                var.set(_all_selected[0])
            toggle_btn.config(
                text="☑  Deselect All" if _all_selected[0] else "☐  Select All")

        toggle_btn = tk.Button(btn_frame, text="☐  Select All",
                               font=("Segoe UI", 8), bg=self.BG2, fg=self.TEXT2,
                               relief="flat", bd=0, padx=8, pady=6,
                               cursor="hand2", command=_toggle_all)
        toggle_btn.pack(side="left")

        tk.Button(btn_frame, text="Abbrechen", font=self.FONT_BTN,
                  bg=self.BG2, fg=self.TEXT, relief="flat", bd=0,
                  pady=6, padx=14, cursor="hand2",
                  command=popup.destroy).pack(side="right", padx=(6, 0))
        tk.Button(btn_frame, text="📊 Create", font=self.FONT_BTN,
                  bg=self.ACCENT2, fg=self.TEXT, relief="flat", bd=0,
                  pady=6, padx=14, cursor="hand2",
                  command=_build).pack(side="right")

    def _run_dashboards(self, dash_runner, selections):
        """Run dashboard build in background thread, stream progress to log."""
        s         = self._collect_settings()
        date_from = s.get("date_from", "").strip()
        date_to   = s.get("date_to",   "").strip()
        if not date_from:
            date_from = (date.today() - timedelta(days=30)).isoformat()
        if not date_to:
            date_to = date.today().isoformat()
        output_dir = Path(s["base_dir"]) / "dashboards"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"\n▶  Berichte erstellen ...")
        self._log(f"   Output: {output_dir}")
        self._log(f"   Zeitraum: {date_from} → {date_to}")

        def worker():
            try:
                import importlib
                os.environ["GARMIN_OUTPUT_DIR"] = s["base_dir"]
                import garmin_config as _cfg
                importlib.reload(_cfg)
                results = dash_runner.build(
                    selections=selections,
                    date_from=date_from,
                    date_to=date_to,
                    settings=s,
                    output_dir=output_dir,
                    log=lambda msg: self.after(
                        0, lambda m=msg: self._log(f"   {m}")),
                )

                def on_done():
                    ok  = [r for r in results if r["success"]]
                    err = [r for r in results if not r["success"]]
                    self._log(f"\n  ✓ {len(ok)} Bericht(e) erstellt")
                    for r in err:
                        self._log(
                            f"  ✗ {r['name']} ({r['format']}): {r.get('error', '')}")
                    if ok:
                        last_html = next(
                            (r.get("path") for r in ok
                             if r.get("format") == "html"), None)
                        if last_html:
                            self._last_html = str(last_html)
                    if ok:
                        os.startfile(str(output_dir))
                self.after(0, on_done)
            except Exception as exc:
                self.after(0, lambda: self._log(f"  ✗ Fehler: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    # ── Output helpers ─────────────────────────────────────────────────────────

    def _open_data_folder(self):
        folder = Path(self._collect_settings()["base_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _open_last_html(self):
        html = self._last_html
        if not html or not Path(html).exists():
            base  = Path(self._collect_settings()["base_dir"])
            files = list(base.glob("*.html"))
            if not files:
                self._log("✗ No HTML files found in data folder.")
                return
            html = str(max(files, key=lambda f: f.stat().st_mtime))
        os.startfile(html)

    def _copy_last_error_log(self):
        fail_dir = Path(
            self._collect_settings()["base_dir"]) / "garmin_data" / "log" / "fail"
        if not fail_dir.exists():
            self._log("✗ No error logs found (log/fail/ does not exist).")
            return
        logs = sorted(fail_dir.glob("garmin_*.log"),
                      key=lambda f: f.stat().st_mtime)
        if not logs:
            self._log("✓ No error logs — no failed sessions recorded.")
            return
        latest = logs[-1]
        try:
            content = latest.read_text(encoding="utf-8")
            self.clipboard_clear()
            self.clipboard_append(content)
            self.update()
            self._log(f"✓ Error log copied to clipboard ({latest.name})")
        except Exception as e:
            self._log(f"✗ Could not read error log: {e}")

    def _open_local_config(self):
        """Open local_config.csv in default editor. Create if missing."""
        import garmin_config as cfg
        csv_path = cfg.LOCAL_CONFIG_FILE
        if not csv_path.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "date_from;date_to;country;place;latitude;longitude\n",
                encoding="utf-8"
            )
            readme_path = csv_path.parent / "local_config_README.txt"
            if not readme_path.exists():
                readme_path.write_text(
                    "Garmin Local Archive — Location Config\n"
                    "======================================\n\n"
                    "Edit local_config.csv to define your location per time period.\n\n"
                    "Columns:\n"
                    "  date_from   : YYYY-MM-DD — start of period\n"
                    "  date_to     : YYYY-MM-DD — end of period\n"
                    "  country     : English name (e.g. Germany, Spain, France)\n"
                    "  place       : City or town name (e.g. Herford, Palma de Mallorca)\n"
                    "  latitude    : Filled automatically — leave empty\n"
                    "  longitude   : Filled automatically — leave empty\n\n"
                    "Example row:\n"
                    "  2025-07-14,2025-07-21,Spain,Palma de Mallorca,,\n\n"
                    "Leave latitude and longitude empty.\n"
                    "The app fills them automatically on next Context Sync.\n"
                    "If no entry matches a date, the app uses the location from Settings.\n",
                    encoding="utf-8"
                )
        os.startfile(csv_path)

    def _create_task_scheduler_xml(self):
        """Generate a configured daily_update_task.xml for Windows Task Scheduler."""
        import shutil as _shutil

        _exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) \
                   else Path(__file__).parent.parent
        _candidates = [
            _exe_dir / "info" / "daily_update_task.xml",
            Path(__file__).parent.parent / "scheduler" / "daily_update_task.xml",
        ]
        template_path = next((p for p in _candidates if p.exists()), None)
        if template_path is None:
            messagebox.showerror(
                "Task Scheduler XML",
                "Template file 'daily_update_task.xml' not found.\n"
                "Expected in docs/ (dev) or info/ (build).",
            )
            return

        dlg = tk.Toplevel(self)
        dlg.title("Create Task Scheduler XML")
        dlg.configure(bg=self.BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Create Task Scheduler XML",
                 font=self.FONT_HEAD, bg=self.BG, fg=self.TEXT).pack(
                 padx=20, pady=(16, 4))
        tk.Label(dlg,
                 text="Select your build target and entry point path.\n"
                      "The XML will be saved ready to import into Windows Task Scheduler.",
                 font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2,
                 justify="left").pack(padx=20, pady=(0, 10))

        target_frame = tk.Frame(dlg, bg=self.BG)
        target_frame.pack(fill="x", padx=20, pady=4)
        tk.Label(target_frame, text="Build target:", font=self.FONT_BODY,
                 bg=self.BG, fg=self.TEXT2).pack(anchor="w")

        v_target = tk.StringVar(value="T2")

        def _default_path(target: str) -> str:
            if target == "T2":
                p = _exe_dir / "scheduler" / "daily_update.bat"
            elif target == "T3":
                p = _exe_dir / "daily_update.exe"
            else:
                return ""
            return str(p) if p.exists() else ""

        def _on_target_change(*_):
            v_path.set(_default_path(v_target.get()))

        for label, val in [
            ("T2 — Standard EXE  (daily_update.bat)",   "T2"),
            ("T3 — Standalone EXE  (daily_update.exe)", "T3"),
            ("T1 — Dev  (python daily_update.py)",      "T1"),
        ]:
            tk.Radiobutton(target_frame, text=label, variable=v_target, value=val,
                           font=self.FONT_BODY, bg=self.BG, fg=self.TEXT,
                           selectcolor=self.BG3, activebackground=self.BG,
                           activeforeground=self.TEXT,
                           command=_on_target_change).pack(anchor="w")

        path_frame = tk.Frame(dlg, bg=self.BG)
        path_frame.pack(fill="x", padx=20, pady=(8, 4))
        tk.Label(path_frame, text="Entry point path:", font=self.FONT_BODY,
                 bg=self.BG, fg=self.TEXT2).pack(anchor="w")
        v_path = tk.StringVar(value=_default_path("T2"))
        path_row = tk.Frame(path_frame, bg=self.BG)
        path_row.pack(fill="x")
        tk.Entry(path_row, textvariable=v_path, font=self.FONT_BODY,
                 bg=self.BG3, fg=self.TEXT, insertbackground=self.TEXT,
                 relief="flat", bd=4, width=44).pack(side="left", fill="x", expand=True)

        def _browse():
            t = v_target.get()
            ft = (
                [("Batch files", "*.bat"), ("All files", "*.*")] if t == "T2"
                else [("Executable", "*.exe"), ("All files", "*.*")] if t == "T3"
                else [("Python files", "*.py"), ("All files", "*.*")]
            )
            p = filedialog.askopenfilename(title="Select entry point", filetypes=ft)
            if p:
                v_path.set(p)

        tk.Button(path_row, text="…", font=self.FONT_BODY,
                  bg=self.ACCENT2, fg=self.TEXT, relief="flat", bd=0,
                  padx=6, command=_browse).pack(side="left", padx=(4, 0))

        tk.Label(dlg,
                 text="⚠  For T1 (Dev): enter the full path to python.exe followed by\n"
                      "   the full path to daily_update.py, separated by a space.",
                 font=("Segoe UI", 7), bg=self.BG, fg=self.YELLOW,
                 justify="left").pack(padx=20, pady=(0, 8))

        def _generate():
            entry = v_path.get().strip()
            if not entry:
                messagebox.showwarning("Task Scheduler XML",
                                       "Please enter the entry point path.",
                                       parent=dlg)
                return
            try:
                xml = template_path.read_text(encoding="utf-16")
            except UnicodeError:
                xml = template_path.read_text(encoding="utf-8")

            working_dir = str(Path(entry.split()[0]).parent)
            xml = xml.replace("{ENTRY_POINT_PATH}", entry)
            xml = xml.replace("<WorkingDirectory></WorkingDirectory>",
                              f"<WorkingDirectory>{working_dir}</WorkingDirectory>")

            save_path = filedialog.asksaveasfilename(
                parent=dlg,
                title="Save Task Scheduler XML",
                initialfile="daily_update_task.xml",
                defaultextension=".xml",
                filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
            )
            if not save_path:
                return
            try:
                Path(save_path).write_text(xml, encoding="utf-16")
                messagebox.showinfo(
                    "Task Scheduler XML",
                    f"Saved to:\n{save_path}\n\n"
                    "Import via Task Scheduler → Action → Import Task…",
                    parent=dlg,
                )
                dlg.destroy()
            except OSError as exc:
                messagebox.showerror("Task Scheduler XML",
                                     f"Could not write file:\n{exc}", parent=dlg)

        btn_row = tk.Frame(dlg, bg=self.BG)
        btn_row.pack(pady=(4, 16))
        tk.Button(btn_row, text="Generate & Save", font=self.FONT_BTN,
                  bg=self.ACCENT, fg=self.TEXT, relief="flat", bd=0,
                  pady=7, padx=16, cursor="hand2",
                  command=_generate).pack(side="left", padx=4)
        tk.Button(btn_row, text="Cancel", font=self.FONT_BTN,
                  bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                  pady=7, padx=16, cursor="hand2",
                  command=dlg.destroy).pack(side="left", padx=4)
