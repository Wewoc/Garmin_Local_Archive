#!/usr/bin/env python3
"""
app/panel_archive.py
Garmin Local Archive — Archive Panel Mixin

PanelArchiveMixin — archive info display, integrity check, restore data,
clean archive, schema migration popup, failed-days popup, mirror operation.

Rules:
  - No __init__ — all state lives on the GarminAppBase instance (self)
  - All widget references stored as self._xyz
  - Panel-private helpers use _archive_* prefix (E-7)
"""

import json
import threading
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import garmin_app_controller as _controller


class PanelArchiveMixin(object):

    def _refresh_archive_info(self):
        """Refresh archive info labels from quality_log.json (C1)."""
        s        = self._collect_settings()
        base_dir = Path(s.get("base_dir", "")).expanduser()
        log_path = base_dir / "garmin_data" / "log" / "quality_log.json"

        if not log_path.exists():
            return
        try:
            data    = json.loads(log_path.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            if not entries:
                return

            total  = len(entries)
            counts = {"high": 0, "medium": 0, "low": 0, "failed": 0}
            for e in entries:
                q = e.get("quality", e.get("category", ""))
                if q in counts:
                    counts[q] += 1

            recheck  = sum(1 for e in entries if e.get("recheck"))
            missing  = sum(1 for e in entries
                           if e.get("quality", e.get("category", "")) in ("failed", "low"))
            dates    = sorted(e["date"] for e in entries if "date" in e)
            rng      = f"{dates[0]} → {dates[-1]}" if dates else "—"
            coverage = f"{total / max(1, (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1):.0%}" \
                       if len(dates) >= 2 else "—"
            last_api  = data.get("last_api_sync",  "—")
            last_bulk = data.get("last_bulk_import", "—")

            def _update():
                self._info_total.config(text=f"Days: {total}")
                for q, lbl in self._info_qdots.items():
                    lbl.config(text=f"{q[:3] if q != 'failed' else 'fail'} {counts[q]}")
                self._info_recheck.config(text=f"Recheck: {recheck}")
                self._info_missing.config(text=f"Missing: {missing}")
                self._info_range.config(text=f"Range: {rng}")
                self._info_coverage.config(text=f"Coverage: {coverage}")
                self._info_last_api.config(text=f"Last API: {last_api}")
                self._info_last_bulk.config(text=f"Last Bulk: {last_bulk}")
            self.after(0, _update)
        except Exception:
            pass

    def _startup_integrity_check(self):
        """
        Runs check_integrity() via controller at startup (B5).
        Updates _restore_btn state via self.after().
        """
        s      = self._collect_settings()
        result = _controller.check_integrity(s)
        if not result.get("missing_days") and not result.get("no_backup"):
            missing = result.get("missing_days", [])
            if not missing:
                def _reset():
                    self._set_restore_button_state(False,
                                                   text="Restore Data", color=self.TEXT2)
                self.after(0, _reset)
                return

        missing = result.get("missing_days", [])
        no_bkup = result.get("no_backup", [])

        def _update():
            if not missing:
                self._set_restore_button_state(False,
                                               text="Restore Data", color=self.TEXT2)
                return
            if no_bkup:
                label = f"⚠ {len(missing)} days missing, {len(no_bkup)} no backup"
            else:
                label = f"⚠ {len(missing)} days missing"
            self._set_restore_button_state(True, text=label, color=self.YELLOW,
                command=lambda: self._on_restore_data(missing, no_bkup))

        self.after(0, _update)

    def _on_restore_data(self, missing_days: list = None, no_backup: list = None):
        """Handles Restore Data button click (B5)."""
        if not missing_days:
            return

        if no_backup:
            detail = "\n".join(no_backup[:10])
            if len(no_backup) > 10:
                detail += f"\n… and {len(no_backup) - 10} more"
            messagebox.showwarning(
                "Restore Data",
                f"{len(no_backup)} day(s) have no backup and cannot be restored:\n\n"
                f"{detail}\n\nThese days must be re-fetched from Garmin Connect.",
            )

        restorable = [d for d in missing_days if d not in (no_backup or [])]
        if not restorable:
            return

        confirmed = messagebox.askyesno(
            "Restore Data",
            f"Restore {len(restorable)} day(s) from backup?\n\n"
            f"First day: {restorable[0]}\nLast day:  {restorable[-1]}",
        )
        if not confirmed:
            return

        def _do_restore():
            try:
                import garmin_backup as _backup
                result   = _backup.restore_raw_days(restorable)
                restored = result.get("restored", [])
                failed   = result.get("failed", [])
                self._log_bg(
                    f"✓ Restore complete: {len(restored)} restored"
                    + (f", {len(failed)} failed" if failed else "")
                )
                self.after(0, lambda: self._set_restore_button_state(
                    False, text="Restore Data", color=self.TEXT2))
            except Exception as e:
                self._log_bg(f"✗ Restore failed: {e}")

        threading.Thread(target=_do_restore, daemon=True).start()

    def _clean_archive(self):
        import json as _json
        s        = self._collect_settings()
        base_dir = Path(s["base_dir"]).expanduser() if s["base_dir"] else None
        if not base_dir:
            self._log("✗ Clean Archive: no data folder set.")
            return
        quality_log = base_dir / "garmin_data" / "log" / "quality_log.json"
        if not quality_log.exists():
            self._log("✗ Clean Archive: quality_log.json not found.")
            return
        try:
            data = _json.loads(quality_log.read_text(encoding="utf-8"))
        except Exception as e:
            self._log(f"✗ Clean Archive: could not read quality_log.json: {e}")
            return
        first_day_str = data.get("first_day")
        if not first_day_str:
            self._log("✗ Clean Archive: first_day not set in quality_log.json.")
            return
        try:
            cutoff = date.fromisoformat(first_day_str)
        except ValueError:
            self._log(f"✗ Clean Archive: invalid first_day value '{first_day_str}'.")
            return

        to_delete = []
        raw_dir     = base_dir / "garmin_data" / "raw"
        summary_dir = base_dir / "garmin_data" / "summary"
        for folder, pattern, prefix in [
            (raw_dir,     "garmin_raw_*.json", "garmin_raw_"),
            (summary_dir, "garmin_*.json",     "garmin_"),
        ]:
            if not folder.exists():
                continue
            for f in sorted(folder.glob(pattern)):
                try:
                    d = date.fromisoformat(f.stem.replace(prefix, ""))
                    if d < cutoff:
                        to_delete.append(f)
                except ValueError:
                    pass

        entries_to_remove = [
            e for e in data.get("days", [])
            if e.get("date", "9999") < first_day_str
        ]

        if not to_delete and not entries_to_remove:
            self._log(f"✓ Clean Archive: nothing to clean before {first_day_str}.")
            return

        popup = tk.Toplevel(self)
        popup.title("Clean Archive")
        popup.configure(bg=self.BG)
        popup.resizable(False, False)
        popup.grab_set()
        tk.Label(popup, text="🗑  Clean Archive",
                 font=("Segoe UI", 12, "bold"), bg=self.BG, fg=self.TEXT,
                 padx=20, pady=14).pack(anchor="w")
        tk.Frame(popup, bg=self.ACCENT, height=1).pack(fill="x", padx=20)
        info_frame = tk.Frame(popup, bg=self.BG, padx=20, pady=10)
        info_frame.pack(fill="x")
        tk.Label(info_frame, text=f"first_day:  {first_day_str}",
                 font=("Segoe UI", 9, "bold"), bg=self.BG, fg=self.ACCENT).pack(anchor="w")
        tk.Label(info_frame,
                 text="The following files will be permanently deleted:",
                 font=self.FONT_BODY, bg=self.BG, fg=self.TEXT2, pady=6).pack(anchor="w")
        list_frame = tk.Frame(popup, bg=self.BG, padx=20)
        list_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                             bg=self.BG3, fg=self.TEXT2, font=("Consolas", 8),
                             selectbackground=self.ACCENT2, height=12,
                             relief="flat", bd=0)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=listbox.yview)
        for f in to_delete:
            listbox.insert(tk.END, f.name)
        for e in entries_to_remove:
            listbox.insert(tk.END, f"[log entry] {e.get('date', '?')}")

        def do_delete():
            errors = 0
            for f in to_delete:
                try:
                    f.unlink()
                except Exception:
                    errors += 1
            if entries_to_remove:
                data["days"] = [
                    e for e in data.get("days", [])
                    if e.get("date", "9999") >= first_day_str
                ]
                try:
                    quality_log.write_text(
                        _json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8"
                    )
                except Exception:
                    errors += 1
            popup.destroy()
            msg = f"✓ Clean Archive: {len(to_delete)} files deleted"
            if errors:
                msg += f" ({errors} errors)"
            self._log(msg)

        btn_frame = tk.Frame(popup, bg=self.BG, padx=20, pady=10)
        btn_frame.pack(fill="x")
        tk.Button(btn_frame, text="Cancel", font=self.FONT_BTN,
                  bg=self.BG3, fg=self.TEXT2, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=popup.destroy).pack(side="left")
        tk.Button(btn_frame, text="🗑  Löschen", font=self.FONT_BTN,
                  bg="#e94560", fg=self.TEXT, relief="flat", bd=0,
                  pady=6, padx=18, cursor="hand2",
                  command=do_delete).pack(side="right")

    def _check_schema_migration(self, base_dir: str) -> bool:
        summary_dir = Path(base_dir) / "garmin_data" / "summary"
        if not summary_dir.exists():
            return False
        try:
            import garmin_normalizer as normalizer
            current_version = normalizer.CURRENT_SCHEMA_VERSION
        except Exception:
            return False
        outdated = 0
        for f in summary_dir.glob("garmin_*.json"):
            try:
                import json as _json
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("schema_version", 0) < current_version:
                    outdated += 1
            except Exception:
                continue
        if outdated == 0:
            return False
        answer = messagebox.askyesno(
            "Data Migration — Backup Required",
            f"A schema update requires rewriting {outdated} summary file(s).\n\n"
            f"Raw data files will NOT be modified.\n"
            f"Summary files will be regenerated from raw data.\n\n"
            f"Please make a backup of your data directory before continuing.\n\n"
            f"I have a backup — continue with migration?",
            icon="warning",
        )
        return answer

    def _check_failed_days_popup(self, base_dir: str, sync_mode: str,
                                  sync_days: str, sync_from: str, sync_to: str) -> bool:
        failed_file = Path(base_dir) / "garmin_data" / "log" / "quality_log.json"
        if not failed_file.exists():
            return False
        try:
            data    = json.loads(failed_file.read_text(encoding="utf-8"))
            entries = data.get("days", [])
            if not entries:
                return False
            today     = date.today()
            yesterday = today - timedelta(days=1)
            try:
                if sync_mode == "recent":
                    start = today - timedelta(days=int(sync_days or 90))
                    end   = yesterday
                elif sync_mode == "range":
                    start = date.fromisoformat(sync_from) if sync_from \
                            else today - timedelta(days=90)
                    end   = date.fromisoformat(sync_to) if sync_to else yesterday
                else:
                    start = date.fromisoformat(entries[0]["date"]) if entries \
                            else today - timedelta(days=90)
                    end   = yesterday
            except (ValueError, KeyError):
                return False
            count = sum(
                1 for e in entries
                if e.get("quality", e.get("category", "")) in ("failed", "low")
                and start <= date.fromisoformat(e["date"]) <= end
            )
            if count == 0:
                return False
            answer = messagebox.askyesno(
                "Incomplete records found",
                f"There are incomplete records:\n\n"
                f"  {count} days in the selected range\n\n"
                f"Refresh now?",
                icon="warning",
            )
            return answer
        except Exception:
            return False

    def _startup_mirror_check(self):
        """
        Checks at startup if mirror_dir is set and reachable (C3).
        Updates _mirror_btn state via self.after().
        """
        s         = self._collect_settings()
        reachable = _controller.check_mirror(s)

        def _update():
            if reachable:
                self._set_mirror_button_state(True, color=self.TEXT)
            else:
                self._set_mirror_button_state(False, color=self.TEXT2)
        self.after(0, _update)

    def _on_mirror(self):
        """Starts mirror operation in background thread (C4/C5)."""
        if self._mirror_running:
            return
        s          = self._collect_settings()
        mirror_dir = s.get("mirror_dir", "").strip()
        if not mirror_dir:
            messagebox.showwarning("Data Mirror", "No mirror folder configured.")
            return
        base_dir = Path(s.get("base_dir", "")).expanduser()

        if self._is_running():
            messagebox.showwarning("Data Mirror",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._timer_active:
            messagebox.showwarning("Data Mirror",
                "Background timer is active.\nStop the timer before mirroring.")
            return
        if self._ctx_running:
            messagebox.showwarning("Data Mirror",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        self._mirror_running = True
        self._set_mirror_button_state(False, text="🔁  Mirroring…", color=self.YELLOW)
        self._log("🔁  Data Mirror started …")

        def _do_mirror():
            try:
                import garmin_mirror as _mirror
                result = _mirror.run_mirror(base_dir, Path(mirror_dir))
                msg = (
                    f"✓ Mirror complete: {result['copied']} copied, "
                    f"{result['deleted']} deleted, {result['skipped']} skipped"
                )
                if result["errors"]:
                    msg += f", {result['errors']} errors"
                self._log_bg(msg)
            except Exception as e:
                self._log_bg(f"✗ Mirror failed: {e}")
            finally:
                self._mirror_running = False
                self.after(0, lambda: self._set_mirror_button_state(
                    True, text="🔁  Data Mirror", color=self.TEXT))

        threading.Thread(target=_do_mirror, daemon=True).start()
