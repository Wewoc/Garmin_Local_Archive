#!/usr/bin/env python3
"""
app/panel_archive.py
Garmin Local Archive — Archive Panel

PanelArchive — PyQt6 QWidget for archive info display, integrity check,
restore data, clean archive, schema migration dialog, failed-days dialog,
and mirror operation.

Rules:
  - __init__(self, app) — app is the GarminApp(QMainWindow) instance
  - All widget references stored as self._xyz
  - Panel-private helpers use _archive_* prefix (E-7)
  - Workers never touch widgets — use self._app._dispatch()
  - Accessor calls go via self._app._panel_connection.set_*_button_state()
"""

import json
import threading
from datetime import date, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QListWidget, QMessageBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_controller as _controller


class PanelArchive(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        # Owner (D-4)
        self._mirror_running = False
        # No UI widgets owned here — archive info labels live on PanelConnection
        # This panel owns the logic; PanelConnection owns the display labels.

    # ── Archive info ───────────────────────────────────────────────────────────

    def _refresh_archive_info(self):
        """Refresh archive info labels from quality_log.json (C1).
        Safe to call from any thread — dispatches UI update to Main Thread."""
        s        = self._app._panel_settings._collect_settings()
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
                           if e.get("quality", e.get("category", ""))
                           in ("failed", "low"))
            dates    = sorted(e["date"] for e in entries if "date" in e)
            rng      = f"{dates[0]} → {dates[-1]}" if dates else "—"
            coverage = (
                f"{total / max(1, (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1):.0%}"
                if len(dates) >= 2 else "—"
            )
            last_api  = data.get("last_api_sync",  "—")
            last_bulk = data.get("last_bulk_import", "—")

            pc = self._app._panel_connection

            def _update():
                pc._info_total.setText(f"Days: {total}")
                for q, lbl in pc._info_qdots.items():
                    lbl.setText(f"{q[:3] if q != 'failed' else 'fail'} {counts[q]}")
                pc._info_recheck.setText(f"Recheck: {recheck}")
                pc._info_missing.setText(f"Missing: {missing}")
                pc._info_range.setText(f"Range: {rng}")
                pc._info_coverage.setText(f"Coverage: {coverage}")
                pc._info_last_api.setText(f"Last API: {last_api}")
                pc._info_last_bulk.setText(f"Last Bulk: {last_bulk}")

            self._app._dispatch(_update)
        except Exception:
            pass

    # ── Integrity check ────────────────────────────────────────────────────────

    def _startup_integrity_check(self):
        """Runs check_integrity() at startup (B5). Worker-safe."""
        s      = self._app._panel_settings._collect_settings()
        result = _controller.check_integrity(s)
        missing = result.get("missing_days", [])
        no_bkup = result.get("no_backup", [])

        def _update():
            pc = self._app._panel_connection
            if not missing:
                pc.set_restore_button_state(False, text="Restore Data")
                return
            if no_bkup:
                label = f"⚠ {len(missing)} days missing, {len(no_bkup)} no backup"
            else:
                label = f"⚠ {len(missing)} days missing"
            pc.set_restore_button_state(
                True, text=label,
                command=lambda: self._on_restore_data(missing, no_bkup))

        self._app._dispatch(_update)

    # ── Restore data ───────────────────────────────────────────────────────────

    def _on_restore_data(self, missing_days: list = None, no_backup: list = None):
        """Handles Restore Data button click (B5). Main Thread only."""
        if not missing_days:
            return

        if no_backup:
            detail = "\n".join(no_backup[:10])
            if len(no_backup) > 10:
                detail += f"\n… and {len(no_backup) - 10} more"
            QMessageBox.warning(
                self._app, "Restore Data",
                f"{len(no_backup)} day(s) have no backup and cannot be restored:\n\n"
                f"{detail}\n\nThese days must be re-fetched from Garmin Connect.",
            )

        restorable = [d for d in missing_days if d not in (no_backup or [])]
        if not restorable:
            return

        answer = QMessageBox.question(
            self._app, "Restore Data",
            f"Restore {len(restorable)} day(s) from backup?\n\n"
            f"First day: {restorable[0]}\nLast day:  {restorable[-1]}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def _do_restore():
            try:
                import garmin_backup as _backup
                result   = _backup.restore_raw_days(restorable)
                restored = result.get("restored", [])
                failed   = result.get("failed", [])
                self._app._log_bg(
                    f"✓ Restore complete: {len(restored)} restored"
                    + (f", {len(failed)} failed" if failed else "")
                )
                self._app._dispatch(
                    lambda: self._app._panel_connection.set_restore_button_state(
                        False, text="Restore Data"))
            except Exception as e:
                self._app._log_bg(f"✗ Restore failed: {e}")

        threading.Thread(target=_do_restore, daemon=True).start()

    # ── Clean archive ──────────────────────────────────────────────────────────

    def _clean_archive(self):
        """Opens Clean Archive dialog. Main Thread only."""
        import json as _json
        s        = self._app._panel_settings._collect_settings()
        base_dir = Path(s["base_dir"]).expanduser() if s["base_dir"] else None
        if not base_dir:
            self._app._log("✗ Clean Archive: no data folder set.")
            return
        quality_log = base_dir / "garmin_data" / "log" / "quality_log.json"
        if not quality_log.exists():
            self._app._log("✗ Clean Archive: quality_log.json not found.")
            return
        try:
            data = _json.loads(quality_log.read_text(encoding="utf-8"))
        except Exception as e:
            self._app._log(f"✗ Clean Archive: could not read quality_log.json: {e}")
            return

        first_day_str = data.get("first_day")
        if not first_day_str:
            self._app._log("✗ Clean Archive: first_day not set in quality_log.json.")
            return
        try:
            cutoff = date.fromisoformat(first_day_str)
        except ValueError:
            self._app._log(
                f"✗ Clean Archive: invalid first_day value '{first_day_str}'.")
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
            self._app._log(
                f"✓ Clean Archive: nothing to clean before {first_day_str}.")
            return

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = QDialog(self._app)
        dlg.setWindowTitle("Clean Archive")
        dlg.setModal(True)
        dlg.setMinimumWidth(480)
        dlg.setStyleSheet(f"background: {self._app.BG}; color: {self._app.TEXT};")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)

        title = QLabel("🗑  Clean Archive")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {self._app.TEXT};")
        lay.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(sep)

        info = QLabel(f"first_day:  {first_day_str}")
        info.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        info.setStyleSheet(f"color: {self._app.ACCENT};")
        lay.addWidget(info)

        hint = QLabel("The following files will be permanently deleted:")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet(f"color: {self._app.TEXT2};")
        lay.addWidget(hint)

        listbox = QListWidget()
        listbox.setStyleSheet(
            f"background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; font-family: Consolas; font-size: 8pt;")
        listbox.setFixedHeight(200)
        for f in to_delete:
            listbox.addItem(f.name)
        for e in entries_to_remove:
            listbox.addItem(f"[log entry] {e.get('date', '?')}")
        lay.addWidget(listbox)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        cancel_btn.setStyleSheet(
            f"QPushButton {{ background: {self._app.BG3}; color: {self._app.TEXT2}; "
            f"border: none; padding: 6px 18px; }}")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)

        delete_btn = QPushButton("🗑  Löschen")
        delete_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        delete_btn.setStyleSheet(
            "QPushButton { background: #e94560; color: #eaeaea; "
            "border: none; padding: 6px 18px; }")
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)

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
            dlg.accept()
            msg = f"✓ Clean Archive: {len(to_delete)} files deleted"
            if errors:
                msg += f" ({errors} errors)"
            self._app._log(msg)

        delete_btn.clicked.connect(do_delete)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(delete_btn)
        lay.addLayout(btn_row)
        dlg.exec()

    # ── Schema migration check ─────────────────────────────────────────────────

    def _check_schema_migration(self, base_dir: str) -> bool:
        """Returns True if migration confirmed. Main Thread only."""
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
        answer = QMessageBox.question(
            self._app, "Data Migration — Backup Required",
            f"A schema update requires rewriting {outdated} summary file(s).\n\n"
            f"Raw data files will NOT be modified.\n"
            f"Summary files will be regenerated from raw data.\n\n"
            f"Please make a backup of your data directory before continuing.\n\n"
            f"I have a backup — continue with migration?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    # ── Failed days popup ──────────────────────────────────────────────────────

    def _check_failed_days_popup(self, base_dir: str, sync_mode: str,
                                  sync_days: str, sync_from: str,
                                  sync_to: str) -> bool:
        """Returns True if user confirms refresh. Main Thread only."""
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
            answer = QMessageBox.question(
                self._app, "Incomplete records found",
                f"There are incomplete records:\n\n"
                f"  {count} days in the selected range\n\n"
                f"Refresh now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            return answer == QMessageBox.StandardButton.Yes
        except Exception:
            return False

    # ── Mirror check ───────────────────────────────────────────────────────────

    def _startup_mirror_check(self):
        """Checks at startup if mirror_dir is reachable (C3). Worker-safe."""
        s         = self._app._panel_settings._collect_settings()
        reachable = _controller.check_mirror(s)

        def _update():
            self._app._panel_connection.set_mirror_button_state(
                reachable,
                text="🔁  Data Mirror",
            )
        self._app._dispatch(_update)

    # ── Mirror operation ───────────────────────────────────────────────────────

    def _on_mirror(self):
        """Starts mirror operation in background thread (C4/C5). Main Thread only."""
        if self._mirror_running:
            return
        s          = self._app._panel_settings._collect_settings()
        mirror_dir = s.get("mirror_dir", "").strip()
        if not mirror_dir:
            QMessageBox.warning(self._app, "Data Mirror",
                                "No mirror folder configured.")
            return
        base_dir = Path(s.get("base_dir", "")).expanduser()

        if self._app._is_running():
            QMessageBox.warning(self._app, "Data Mirror",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._timer_active:
            QMessageBox.warning(self._app, "Data Mirror",
                "Background timer is active.\nStop the timer before mirroring.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Data Mirror",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        self._mirror_running = True
        self._app._panel_connection.set_mirror_button_state(
            False, text="🔁  Mirroring…")
        self._app._log("🔁  Data Mirror started …")

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
                self._app._log_bg(msg)
            except Exception as e:
                self._app._log_bg(f"✗ Mirror failed: {e}")
            finally:
                self._mirror_running = False
                self._app._dispatch(
                    lambda: self._app._panel_connection.set_mirror_button_state(
                        True, text="🔁  Data Mirror"))

        threading.Thread(target=_do_mirror, daemon=True).start()